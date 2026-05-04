"""Causal Reasoning Framework — structured metacognitive template (AD-660 v1).

Agents (or system services on their behalf) fill a four-step causal-reasoning
template when an unexpected outcome triggers analysis:

    1. what_changed             — observable deltas from baseline
    2. confounded_variables     — overlapping changes that cannot be cleanly isolated
    3. testable_hypotheses      — falsifiable explanations
    4. diagnostic_actions       — concrete next steps to discriminate hypotheses

v1 is TEMPLATE + STORAGE + INTEGRATION POINT only — there is no causal-inference
engine. The LLM fills the template; ProbOS persists the artifact. Hypothesis
ranking, action execution, and automatic invocation are deferred to AD-660b/c.

Built on AD-504 SelfMonitoringConcernEvent surface and AD-557 emergence
metrics as the trigger sources, but v1 only wires AD-504 (counselor concern
hook). AD-557 wiring is AD-660b.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from probos.types import LLMRequest
from probos.utils.json_extract import extract_json

logger = logging.getLogger(__name__)


_MAX_LIST_LEN = 8           # cap each step's list length post-parse
_MAX_FIELD_CHARS = 500      # truncate any single bullet


@dataclass(frozen=True)
class CausalReasoningTemplate:
    """Structured causal-reasoning artifact (AD-660 v1).

    Immutable record of one analysis pass. The four list fields correspond
    to the Lee et al. (arXiv:2603.28052) Meta-Harness proposer's four-step
    causal-reasoning protocol.
    """

    template_id: str
    agent_id: str
    triggered_at: datetime
    trigger_summary: str
    what_changed: list[str]
    confounded_variables: list[str]
    testable_hypotheses: list[str]
    diagnostic_actions: list[str]
    confidence: float                         # 0.0–1.0; LLM's self-reported confidence
    source_event_ref: str | None = None       # opt. correlation id / event token

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # ISO-format datetime for JSON-friendly storage / API
        d["triggered_at"] = self.triggered_at.isoformat()
        return d


_SYSTEM_PROMPT = """You are a metacognitive analyst helping an autonomous agent
diagnose an unexpected outcome. Fill the four-step causal reasoning template.

Return ONLY a JSON object with these exact keys (lists may be empty if you
genuinely have no hypothesis to offer — do NOT pad):

{
  "what_changed": ["short bullets of observable deltas from baseline"],
  "confounded_variables": ["overlapping changes that cannot be cleanly isolated"],
  "testable_hypotheses": ["falsifiable explanations of the unexpected outcome"],
  "diagnostic_actions": ["concrete next steps to discriminate hypotheses"],
  "confidence": 0.0
}

confidence is your self-reported confidence in your own causal account
(0.0 = guessing, 1.0 = strong evidence). Do NOT fabricate. If context is
sparse, return short lists and low confidence."""


def _coerce_list(raw: Any) -> list[str]:
    """Normalize an LLM-returned list field. Truncates length and per-item chars."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw[:_MAX_LIST_LEN]:
        if not isinstance(item, str):
            item = str(item)
        out.append(item[:_MAX_FIELD_CHARS])
    return out


def _coerce_confidence(raw: Any) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def _empty_template(
    *,
    agent_id: str,
    trigger_summary: str,
    source_event_ref: str | None,
) -> CausalReasoningTemplate:
    """Degraded template — used when the LLM returns unparseable output."""
    return CausalReasoningTemplate(
        template_id=uuid.uuid4().hex[:16],
        agent_id=agent_id,
        triggered_at=datetime.now(timezone.utc),
        trigger_summary=trigger_summary[:_MAX_FIELD_CHARS],
        what_changed=[],
        confounded_variables=[],
        testable_hypotheses=[],
        diagnostic_actions=[],
        confidence=0.0,
        source_event_ref=source_event_ref,
    )


class CausalReasoner:
    """Fill a CausalReasoningTemplate via the LLM (AD-660 v1).

    v1 is on-demand only — no background loop, no automatic invocation
    across concern paths. Caller decides when to invoke. The integration
    point in counselor._on_self_monitoring_concern is gated by
    CausalReasoningConfig.enabled (default False).
    """

    def __init__(
        self,
        runtime: Any,
        *,
        max_tokens: int = 700,
        tier: str = "standard",
    ) -> None:
        self._runtime = runtime
        self._max_tokens = max_tokens
        self._tier = tier

    async def analyze(
        self,
        *,
        trigger: str,
        agent_id: str,
        context: dict[str, Any] | None = None,
        source_event_ref: str | None = None,
    ) -> CausalReasoningTemplate:
        """Run one causal-reasoning pass via the LLM.

        Returns a CausalReasoningTemplate. On any LLM failure or JSON-parse
        failure, returns a degraded (empty-list, confidence=0.0) template.
        Never raises.
        """
        ctx_json = ""
        if context:
            try:
                # Best-effort serialization; truncated for prompt-budget safety.
                ctx_json = json.dumps(context, default=str)[:4000]
            except (TypeError, ValueError):
                ctx_json = ""
        user_prompt = (
            f"Trigger:\n{trigger[:1500]}\n\n"
            f"Context (JSON):\n{ctx_json}\n\n"
            "Fill the four-step causal reasoning template now."
        )

        llm_client = getattr(self._runtime, "llm_client", None)
        if llm_client is None:
            logger.debug("AD-660: causal_reasoner has no llm_client; degraded.")
            return _empty_template(
                agent_id=agent_id,
                trigger_summary=trigger,
                source_event_ref=source_event_ref,
            )

        request = LLMRequest(
            prompt=user_prompt,
            system_prompt=_SYSTEM_PROMPT,
            tier=self._tier,
            temperature=0.0,
            max_tokens=self._max_tokens,
        )
        try:
            response = await llm_client.complete(request)
        except Exception:
            logger.warning("AD-660: causal_reasoner LLM call failed", exc_info=True)
            return _empty_template(
                agent_id=agent_id,
                trigger_summary=trigger,
                source_event_ref=source_event_ref,
            )

        content = getattr(response, "content", "") or ""
        try:
            parsed = extract_json(content)
        except (ValueError, TypeError):
            parsed = None
        if not isinstance(parsed, dict):
            logger.debug(
                "AD-660: causal_reasoner JSON parse failed (%d chars); degraded.",
                len(content),
            )
            return _empty_template(
                agent_id=agent_id,
                trigger_summary=trigger,
                source_event_ref=source_event_ref,
            )

        return CausalReasoningTemplate(
            template_id=uuid.uuid4().hex[:16],
            agent_id=agent_id,
            triggered_at=datetime.now(timezone.utc),
            trigger_summary=trigger[:_MAX_FIELD_CHARS],
            what_changed=_coerce_list(parsed.get("what_changed")),
            confounded_variables=_coerce_list(parsed.get("confounded_variables")),
            testable_hypotheses=_coerce_list(parsed.get("testable_hypotheses")),
            diagnostic_actions=_coerce_list(parsed.get("diagnostic_actions")),
            confidence=_coerce_confidence(parsed.get("confidence")),
            source_event_ref=source_event_ref,
        )

    async def analyze_concern(
        self, concern_data: dict[str, Any],
    ) -> CausalReasoningTemplate | None:
        """Convenience: run analyze() against an AD-504 concern payload.

        Returns None if the payload lacks an agent_id (defensive — a malformed
        concern event must not crash the integration point).
        """
        agent_id = concern_data.get("agent_id") or ""
        if not agent_id:
            return None
        callsign = concern_data.get("agent_callsign", agent_id[:8])
        zone = concern_data.get("zone", "amber")
        sim = concern_data.get("similarity_ratio", 0.0)
        vel = concern_data.get("velocity_ratio", 0.0)
        trigger = (
            f"Agent {callsign} entered {zone} zone — "
            f"similarity_ratio={sim:.2f}, velocity_ratio={vel:.2f}. "
            "Diagnose the unexpected behavior change."
        )
        # Persist a lightweight correlation token so analyst can join with the
        # original event downstream. v1 has no real correlation_id surface.
        source_event_ref = f"self_monitoring_concern:{agent_id}"
        return await self.analyze(
            trigger=trigger,
            agent_id=agent_id,
            context={
                "zone": zone,
                "similarity_ratio": sim,
                "velocity_ratio": vel,
                "callsign": callsign,
            },
            source_event_ref=source_event_ref,
        )
