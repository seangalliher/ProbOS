"""Escalation cascade manager — 3-tier error recovery for ProbOS.

Tier 1: Retry with a different agent (pool rotation)
Tier 2: LLM arbitration (approve / reject / modify)
Tier 3: User consultation (interactive prompt)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from probos.types import (
    ConsensusOutcome,
    EscalationResult,
    EscalationTier,
    LLMRequest,
)

logger = logging.getLogger(__name__)

ARBITRATION_PROMPT = """You are the escalation arbiter for ProbOS, a probabilistic agent-native OS.

An agent operation has failed or consensus was rejected. You must decide what to do.

You will receive:
- The original intent (what was attempted)
- The error or rejection reason
- Any partial results from agents
- The consensus outcome (if applicable)

Respond with ONLY a JSON object:
{
    "action": "approve" | "reject" | "modify",
    "reason": "Brief explanation of your decision",
    "params": {}  // Only if action is "modify" — the corrected parameters to retry with
}

Rules:
- "approve" if the partial results are acceptable despite the error
- "reject" if the operation is fundamentally flawed and should not be retried
- "modify" if you can suggest corrected parameters that might succeed
- Be conservative — when in doubt, reject and let the user decide
"""


class EscalationManager:
    """Orchestrates the 3-tier escalation cascade.

    The manager is event-silent — it returns results to its caller
    (DAGExecutor) which is responsible for logging events.
    """

    def __init__(
        self,
        runtime: Any,          # ProbOSRuntime (for submitting retries)
        llm_client: Any,       # For Tier 2 arbitration
        max_retries: int = 2,  # Max Tier 1 retry attempts
        user_callback: Callable | None = None,  # Tier 3: async callback to prompt user
        pre_user_hook: Callable | None = None,   # Called before user_callback (e.g. live.stop)
        surge_fn: Callable | None = None,  # async (pool_name, extra) -> bool
    ) -> None:
        self.runtime = runtime
        self.llm_client = llm_client
        self.max_retries = max_retries
        self._user_callback = user_callback
        self._pre_user_hook = pre_user_hook
        self._surge_fn = surge_fn

    def set_user_callback(
        self, callback: Callable[[str, dict], Awaitable[bool | None]]
    ) -> None:
        """Set the Tier 3 user prompt callback."""
        self._user_callback = callback

    def set_pre_user_hook(self, hook: Callable) -> None:
        """Set a hook called before user consultation (e.g., live.stop)."""
        self._pre_user_hook = hook

    async def escalate(
        self,
        node: Any,  # TaskNode
        error: str,
        context: dict,
    ) -> EscalationResult:
        """Run the full 3-tier escalation cascade.

        Returns when resolved or fully exhausted.
        """
        tiers_attempted: list[EscalationTier] = []

        # ---- Tier 1: Retry with different agent ----
        tiers_attempted.append(EscalationTier.RETRY)
        tier1_result = await self._tier1_retry(node, error, context)
        if tier1_result.resolved:
            tier1_result.tiers_attempted = tiers_attempted
            return tier1_result

        # ---- Tier 2: LLM arbitration ----
        if self.llm_client is not None and not self._is_mock_llm():
            tiers_attempted.append(EscalationTier.ARBITRATION)
            tier2_result = await self._tier2_arbitrate(node, error, context)
            if tier2_result.resolved:
                tier2_result.tiers_attempted = tiers_attempted
                return tier2_result
            # If tier2 returned "modify" and retry failed, fall through to tier 3
            # If tier2 returned "reject", fall through to tier 3
        else:
            # Mock LLM or None — attempt tier 2 anyway (mock will reject)
            if self.llm_client is not None:
                tiers_attempted.append(EscalationTier.ARBITRATION)
                tier2_result = await self._tier2_arbitrate(node, error, context)
                if tier2_result.resolved:
                    tier2_result.tiers_attempted = tiers_attempted
                    return tier2_result

        # ---- Tier 3: User consultation ----
        tiers_attempted.append(EscalationTier.USER)
        context_with_tiers = {**context, "tiers_attempted": tiers_attempted}
        tier3_result = await self._tier3_user(node, error, context_with_tiers)
        tier3_result.tiers_attempted = tiers_attempted
        return tier3_result

    def _is_mock_llm(self) -> bool:
        """Check if the LLM client is a MockLLMClient."""
        return type(self.llm_client).__name__ == "MockLLMClient"

    # ------------------------------------------------------------------
    # Tier 1: Retry with different agent
    # ------------------------------------------------------------------

    async def _tier1_retry(
        self, node: Any, error: str, context: dict
    ) -> EscalationResult:
        """Retry the intent up to max_retries times."""
        # Request surge capacity if available
        if self._surge_fn:
            pool_name = context.get("pool_name")
            if pool_name:
                try:
                    await self._surge_fn(pool_name, 1)
                except Exception as e:
                    logger.debug("Surge request failed: %s", e)

        for attempt in range(1, self.max_retries + 1):
            try:
                if node.use_consensus:
                    if node.intent == "write_file":
                        result = await self.runtime.submit_write_with_consensus(
                            path=node.params.get("path", ""),
                            content=node.params.get("content", ""),
                            timeout=10.0,
                        )
                    else:
                        result = await self.runtime.submit_intent_with_consensus(
                            intent=node.intent,
                            params=dict(node.params),
                            timeout=10.0,
                        )
                    # Check if consensus approved
                    consensus = result.get("consensus")
                    if consensus and consensus.outcome == ConsensusOutcome.APPROVED:
                        return EscalationResult(
                            tier=EscalationTier.RETRY,
                            resolved=True,
                            original_error=error,
                            resolution=result,
                            attempts=attempt,
                            reason=f"Retry {attempt} succeeded with consensus approval",
                        )
                    # Consensus rejected/insufficient — continue retrying
                else:
                    results = await self.runtime.submit_intent(
                        intent=node.intent,
                        params=dict(node.params),
                        timeout=10.0,
                    )
                    if any(r.success for r in results):
                        return EscalationResult(
                            tier=EscalationTier.RETRY,
                            resolved=True,
                            original_error=error,
                            resolution={
                                "intent": node.intent,
                                "results": results,
                                "success": True,
                                "result_count": len(results),
                            },
                            attempts=attempt,
                            reason=f"Retry {attempt} succeeded",
                        )
            except Exception as e:
                logger.debug("Tier 1 retry %d failed: %s", attempt, e)

        return EscalationResult(
            tier=EscalationTier.RETRY,
            resolved=False,
            original_error=error,
            attempts=self.max_retries,
            reason=f"All {self.max_retries} retries failed",
        )

    # ------------------------------------------------------------------
    # Tier 2: LLM arbitration
    # ------------------------------------------------------------------

    async def _tier2_arbitrate(
        self, node: Any, error: str, context: dict
    ) -> EscalationResult:
        """Ask the LLM to judge the failure."""
        prompt = (
            f"Intent: {node.intent}\n"
            f"Params: {json.dumps(node.params, default=str)}\n"
            f"Error: {error}\n"
            f"Context: {json.dumps(context, default=str)}\n"
        )

        request = LLMRequest(
            prompt=prompt,
            system_prompt=ARBITRATION_PROMPT,
            tier=None,
            temperature=0.0,
        )

        try:
            response = await self.llm_client.complete(request)
            if response.error:
                return EscalationResult(
                    tier=EscalationTier.ARBITRATION,
                    resolved=False,
                    original_error=error,
                    reason=f"LLM error: {response.error}",
                )

            decision = json.loads(response.content)
            action = decision.get("action", "reject")
            reason = decision.get("reason", "")

            if action == "approve":
                return EscalationResult(
                    tier=EscalationTier.ARBITRATION,
                    resolved=True,
                    original_error=error,
                    resolution=node.result,
                    reason=reason,
                )
            elif action == "modify":
                # Retry once with modified params
                modified_params = decision.get("params", {})
                try:
                    if node.use_consensus:
                        result = await self.runtime.submit_intent_with_consensus(
                            intent=node.intent,
                            params=modified_params,
                            timeout=10.0,
                        )
                        consensus = result.get("consensus")
                        if consensus and consensus.outcome == ConsensusOutcome.APPROVED:
                            return EscalationResult(
                                tier=EscalationTier.ARBITRATION,
                                resolved=True,
                                original_error=error,
                                resolution=result,
                                reason=f"Modified retry succeeded: {reason}",
                            )
                    else:
                        results = await self.runtime.submit_intent(
                            intent=node.intent,
                            params=modified_params,
                            timeout=10.0,
                        )
                        if any(r.success for r in results):
                            return EscalationResult(
                                tier=EscalationTier.ARBITRATION,
                                resolved=True,
                                original_error=error,
                                resolution={
                                    "intent": node.intent,
                                    "results": results,
                                    "success": True,
                                    "result_count": len(results),
                                },
                                reason=f"Modified retry succeeded: {reason}",
                            )
                except Exception as e:
                    logger.debug("Tier 2 modified retry failed: %s", e)

            # action == "reject" or modify retry failed
            return EscalationResult(
                tier=EscalationTier.ARBITRATION,
                resolved=False,
                original_error=error,
                reason=reason or "LLM rejected the operation",
            )

        except (json.JSONDecodeError, Exception) as e:
            logger.debug("Tier 2 arbitration failed: %s", e)
            return EscalationResult(
                tier=EscalationTier.ARBITRATION,
                resolved=False,
                original_error=error,
                reason=f"Arbitration failed: {e}",
            )

    # ------------------------------------------------------------------
    # Tier 3: User consultation
    # ------------------------------------------------------------------

    async def _tier3_user(
        self, node: Any, error: str, context: dict
    ) -> EscalationResult:
        """Ask the user for a decision."""
        if self._user_callback is None:
            return EscalationResult(
                tier=EscalationTier.USER,
                resolved=False,
                original_error=error,
                reason="No user callback available",
            )

        # Call pre-user hook (e.g., stop Rich Live display)
        if self._pre_user_hook is not None:
            try:
                self._pre_user_hook()
            except Exception as e:
                logger.debug("Pre-user hook failed: %s", e)

        description = f"Operation '{node.intent}' failed: {error}"
        ctx = {
            "intent": node.intent,
            "params": node.params,
            "error": error,
            **context,
        }

        try:
            user_decision = await self._user_callback(description, ctx)
        except Exception as e:
            logger.debug("User callback failed: %s", e)
            return EscalationResult(
                tier=EscalationTier.USER,
                resolved=False,
                original_error=error,
                reason=f"User callback error: {e}",
            )

        if user_decision is True:
            # User approved — re-execute the intent without consensus
            # to get actual results (node.result still holds the
            # consensus-rejected dict from the initial attempt).
            resolution = await self._reexecute_without_consensus(node)
            return EscalationResult(
                tier=EscalationTier.USER,
                resolved=True,
                original_error=error,
                user_approved=True,
                resolution=resolution,
                reason="User approved",
            )
        elif user_decision is False:
            return EscalationResult(
                tier=EscalationTier.USER,
                resolved=True,
                original_error=error,
                user_approved=False,
                reason="User rejected",
            )
        else:
            # None — skipped
            return EscalationResult(
                tier=EscalationTier.USER,
                resolved=False,
                original_error=error,
                user_approved=None,
                reason="User skipped",
            )

    async def _reexecute_without_consensus(self, node: Any) -> dict[str, Any] | None:
        """Get actual agent output after user approves a consensus-rejected op.

        The consensus pipeline rejected the *policy* (e.g. "shell commands
        are risky"), not the agent results themselves.  The original
        result dict (``node.result``) already contains the successful
        IntentResults with real stdout/stderr.  So we first look there
        before attempting a fresh re-execution.
        """
        # --- Strategy 1: reuse original successful results ---
        original = node.result
        if isinstance(original, dict) and "results" in original:
            original_results = original["results"]
            if isinstance(original_results, list) and any(
                getattr(r, "success", False) for r in original_results
            ):
                logger.info(
                    "Using original agent results (consensus rejected "
                    "policy, not output): intent=%s agents=%d",
                    node.intent, len(original_results),
                )
                return {
                    "intent": node.intent,
                    "results": original_results,
                    "success": True,
                    "result_count": len(original_results),
                }

        # --- Strategy 2: re-execute without consensus ---
        try:
            results = await self.runtime.submit_intent(
                intent=node.intent,
                params=dict(node.params),
                timeout=30.0,
            )
            if results:
                successful = any(r.success for r in results)
                if successful:
                    logger.info(
                        "Re-execution succeeded: intent=%s agents=%d",
                        node.intent, len(results),
                    )
                else:
                    logger.warning(
                        "Re-execution returned results but none successful: "
                        "intent=%s agents=%d errors=%s",
                        node.intent, len(results),
                        [r.error or "(empty)" for r in results if not r.success],
                    )
                return {
                    "intent": node.intent,
                    "results": results,
                    "success": successful,
                    "result_count": len(results),
                }
            else:
                logger.warning(
                    "Re-execution returned no results: intent=%s", node.intent,
                )
        except Exception as e:
            logger.warning("Re-execution after user approval failed: %s", e)

        # Fallback: return whatever was there before
        logger.warning(
            "Falling back to original node.result for intent=%s", node.intent,
        )
        return node.result
