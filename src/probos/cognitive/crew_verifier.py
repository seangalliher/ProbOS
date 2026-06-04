"""AD-860: Adversarial verification + convergence gate for crew sub-tasks.

The crew fan-out executor (AD-859) drives a parent's child sub-tasks to
completion and collects a :class:`SubtaskResult` per child. Those results are
*unverified* — a single agent's self-asserted output. :class:`SubtaskVerifier`
is the semantic sibling of the deterministic ``RedTeamAgent``: instead of
re-executing tools, it runs an **independent** crew member as an LLM judge that
tries to *refute* the result against the sub-task's declared acceptance
criterion (``expected_output``), or — when no criterion was declared — against a
free-text "find the flaw" critique prompt (honest-degrade).

Independence is the point: the verifier agent MUST differ from the producer
agent (picked from :meth:`AgentRegistry.all` excluding the producer id). If no
independent agent is available, the result is honest-degraded to ``unverified``
with a logged reason — an agent is never allowed to verify itself.

Convergence: a refuted result is re-run through the **public** AD-859a
:class:`WorkItemAgenticExecutor` with the critique appended to the task text,
up to :attr:`AgenticDispatchConfig.max_convergence_rounds` (Safety Budget). A
still-refuted result after the last round is escalated as ``unverified`` — never
silently accepted.

Attribution reuses the consensus path, not a parallel one: each verdict is
recorded against the :class:`TrustNetwork` ledger (synchronously) so good
verifiers and good producers both earn trust over runs, and each verdict maps
to the real :class:`Vote` shape so AD-861 can compute Shapley values. This
module does NOT call ``compute_shapley_values`` (that is AD-861) and does NOT
add a ``done -> in_progress`` duty transition (re-run via the AD-859a executor
is state-machine-independent).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from probos.types import LLMRequest, Vote

if TYPE_CHECKING:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
    from probos.cognitive.crew_executor import SubtaskResult
    from probos.consensus.trust import TrustNetwork
    from probos.substrate.registry import AgentRegistry
    from probos.workforce import WorkItemStore

logger = logging.getLogger(__name__)

# Convergence status constants — what the loop concluded for a sub-task.
_STATUS_CONVERGED = "converged"
_STATUS_UNVERIFIED = "unverified"


@dataclass
class VerificationVerdict:
    """The outcome of one adversarial verification pass over a sub-task result.

    ``accepted`` is the judge's decision (did the result survive refutation),
    ``confidence`` is the judge's self-reported confidence in ``[0, 1]``,
    ``critique`` is the human-readable flaw/justification (fed back into the
    convergence re-run on refusal), and ``verifier_agent_id`` is the independent
    agent that rendered the verdict (empty string when honest-degraded because
    no independent verifier was available).
    """

    accepted: bool
    confidence: float
    critique: str
    verifier_agent_id: str


@dataclass
class ConvergenceOutcome:
    """The terminal result of the verify -> re-run -> re-verify loop.

    ``result`` is the (possibly re-run-updated) :class:`SubtaskResult`,
    ``verdict`` is the final verification verdict, ``status`` is one of
    ``converged`` / ``unverified``, and ``rounds`` is how many re-run rounds
    were spent (0 when the first verdict already accepted).
    """

    result: "SubtaskResult"
    verdict: VerificationVerdict
    status: str
    rounds: int = 0


class SubtaskVerifier:
    """Adversarially verify crew sub-task results and drive them to convergence.

    Constructor injection (Dependency Inversion): every collaborator is supplied
    by the caller so the verifier depends on abstractions, not concretions, and
    is trivially testable with fakes.
    """

    def __init__(
        self,
        *,
        llm_client: Any,
        work_item_store: "WorkItemStore",
        agent_registry: "AgentRegistry",
        trust_network: "TrustNetwork",
        agentic_executor: "WorkItemAgenticExecutor",
        runtime: Any,
        max_convergence_rounds: int = 2,
    ) -> None:
        self._llm = llm_client
        self._store = work_item_store
        self._registry = agent_registry
        self._trust = trust_network
        self._executor = agentic_executor
        self._runtime = runtime
        self._max_rounds = max(1, int(max_convergence_rounds))

    # ------------------------------------------------------------------ public

    async def verify(self, result: "SubtaskResult") -> VerificationVerdict:
        """Run one adversarial verification pass over ``result``.

        Picks an independent verifier (different from the producer), resolves the
        declared acceptance criterion from the work item's metadata, asks the
        LLM judge to refute the result, records the verdict against the trust
        ledger, and returns the :class:`VerificationVerdict`. Honest-degrades to
        an ``unverified`` verdict (empty ``verifier_agent_id``, no trust write)
        when no independent agent is available.
        """
        verifier_id = self._pick_independent_verifier(result.agent_id)
        if verifier_id is None:
            logger.warning(
                "AD-860: no independent verifier available for sub-task %s "
                "(producer=%s); honest-degrading to unverified — an agent is "
                "never allowed to verify itself",
                result.work_item_id, result.agent_id,
            )
            return VerificationVerdict(
                accepted=False,
                confidence=0.0,
                critique="No independent verifier available; result unverified.",
                verifier_agent_id="",
            )

        expected = await self._resolve_expected_output(result.work_item_id)
        request = LLMRequest(
            prompt=self._build_judge_prompt(result, expected),
            system_prompt=self._JUDGE_SYSTEM_PROMPT,
            tier="standard",
        )
        try:
            response = await self._llm.complete(request)
            verdict = self._parse_verdict(getattr(response, "content", ""), verifier_id)
        except Exception:
            logger.warning(
                "AD-860: LLM judge call failed for sub-task %s (verifier=%s); "
                "honest-degrading to refuted (unverified) — never silently "
                "accept an unjudged result",
                result.work_item_id, verifier_id, exc_info=True,
            )
            verdict = VerificationVerdict(
                accepted=False,
                confidence=0.0,
                critique="LLM judge unavailable; result could not be verified.",
                verifier_agent_id=verifier_id,
            )

        # Reuse the consensus path for attribution — record the verifier's
        # outcome against the trust ledger SYNCHRONOUSLY (keywords only; the
        # producer is the verifier_id field). Skip when honest-degraded.
        if verdict.verifier_agent_id:
            self._trust.record_outcome(
                verdict.verifier_agent_id,
                success=verdict.accepted,
                intent_type="crew_verification",
                verifier_id=result.agent_id,
                source="crew_verification",
            )
        return verdict

    async def converge(
        self,
        result: "SubtaskResult",
        *,
        instructions: str,
        task_text: str,
    ) -> ConvergenceOutcome:
        """Verify ``result`` and, on refusal, re-run + re-verify to convergence.

        Loops up to ``max_convergence_rounds``: verify; if accepted, converged;
        if refuted, re-run the sub-task through the public AD-859a
        :class:`WorkItemAgenticExecutor` with the critique appended to
        ``task_text``, update ``result.output`` from the re-run, then re-verify.
        A still-refuted result after the final round is escalated as
        ``unverified`` — never silently accepted.
        """
        verdict = await self.verify(result)
        if verdict.accepted:
            return ConvergenceOutcome(
                result=result, verdict=verdict, status=_STATUS_CONVERGED, rounds=0
            )

        rounds = 0
        while rounds < self._max_rounds:
            rounds += 1
            critiqued_task = (
                f"{task_text}\n\nCRITIQUE:\n{verdict.critique}"
            )
            try:
                outcome = await self._executor.run(
                    agent_id=result.agent_id,
                    instructions=instructions,
                    task_text=critiqued_task,
                    runtime=self._runtime,
                )
                result.output = outcome.final_text or result.output
            except Exception:
                logger.warning(
                    "AD-860: convergence re-run failed for sub-task %s "
                    "(producer=%s, round=%d); keeping prior output and "
                    "re-verifying",
                    result.work_item_id, result.agent_id, rounds, exc_info=True,
                )
            verdict = await self.verify(result)
            if verdict.accepted:
                return ConvergenceOutcome(
                    result=result,
                    verdict=verdict,
                    status=_STATUS_CONVERGED,
                    rounds=rounds,
                )

        logger.warning(
            "AD-860: sub-task %s (producer=%s) still refuted after %d "
            "convergence round(s); escalating as unverified — not silently "
            "accepting a refuted result",
            result.work_item_id, result.agent_id, rounds,
        )
        return ConvergenceOutcome(
            result=result, verdict=verdict, status=_STATUS_UNVERIFIED, rounds=rounds
        )

    @staticmethod
    def verdict_to_vote(verdict: VerificationVerdict) -> Vote:
        """Map a verdict to the real :class:`Vote` shape for AD-861 attribution.

        AD-861 builds the Shapley input from these votes; this module does NOT
        call ``compute_shapley_values`` itself.
        """
        return Vote(
            agent_id=verdict.verifier_agent_id,
            approved=verdict.accepted,
            confidence=verdict.confidence,
            reason=verdict.critique,
        )

    # ------------------------------------------------------------------ internals

    _JUDGE_SYSTEM_PROMPT = (
        "You are an adversarial verifier on a crew of collaborating agents. "
        "Your job is to find flaws, missing requirements, or unsupported "
        "claims in another agent's work — NOT to be agreeable. Respond ONLY "
        "with a single JSON object of the form "
        '{"accepted": <bool>, "confidence": <0..1 float>, "critique": '
        '"<short reason>"}. Set "accepted" to true only if the work is correct '
        "and complete; otherwise false with a concrete critique."
    )

    def _pick_independent_verifier(self, producer_id: str) -> str | None:
        """Return an agent id that differs from ``producer_id``, or ``None``.

        Independence is the gate: the producer can never verify itself. Returns
        the first registered agent whose id is not the producer's.
        """
        try:
            agents = self._registry.all()
        except Exception:
            logger.warning(
                "AD-860: agent registry lookup failed while picking a verifier "
                "for producer %s; treating as no independent agent available",
                producer_id, exc_info=True,
            )
            return None
        for agent in agents:
            agent_id = getattr(agent, "id", None)
            if agent_id and agent_id != producer_id:
                return agent_id
        return None

    async def _resolve_expected_output(self, work_item_id: str) -> str | None:
        """Resolve the declared acceptance criterion from the work item.

        AD-858 persists ``expected_output`` into the work item metadata (the
        AD-860 one-line dispatch fix). Honest-degrades to ``None`` — the
        free-text critique path — when the item or key is absent.
        """
        try:
            wi = await self._store.get_work_item(work_item_id)
        except Exception:
            logger.warning(
                "AD-860: work item lookup failed for %s; falling back to the "
                "free-text critique path",
                work_item_id, exc_info=True,
            )
            return None
        if wi is None:
            return None
        expected = (wi.metadata or {}).get("expected_output")
        return expected if isinstance(expected, str) and expected else None

    def _build_judge_prompt(
        self, result: "SubtaskResult", expected: str | None
    ) -> str:
        """Build the judge prompt, anchored to ``expected`` when declared."""
        if expected:
            return (
                "A crew member produced the following result for a sub-task "
                "with a DECLARED acceptance criterion. Decide whether the "
                "result satisfies that criterion.\n\n"
                f"DECLARED ACCEPTANCE CRITERION:\n{expected}\n\n"
                f"PRODUCED RESULT:\n{result.output}\n\n"
                "Does the result satisfy the declared acceptance criterion? "
                "Respond with the JSON verdict object."
            )
        return (
            "A crew member produced the following result for a sub-task. No "
            "explicit acceptance criterion was declared, so judge it on "
            "general correctness, completeness, and whether every claim is "
            "supported.\n\n"
            f"PRODUCED RESULT:\n{result.output}\n\n"
            "Find any flaw, missing requirement, or unsupported claim. Respond "
            "with the JSON verdict object."
        )

    def _parse_verdict(self, content: str, verifier_id: str) -> VerificationVerdict:
        """Parse the judge's JSON response into a verdict (robust to non-JSON).

        Honest-degrades an unparseable response to a refuted verdict — the
        conservative direction — so a malformed judge reply never silently
        accepts a result.
        """
        raw = (content or "").strip()
        payload = self._extract_json_object(raw)
        if payload is None:
            logger.warning(
                "AD-860: judge response was not parseable JSON (verifier=%s); "
                "honest-degrading to refuted so an unparseable reply never "
                "silently accepts a result",
                verifier_id,
            )
            return VerificationVerdict(
                accepted=False,
                confidence=0.0,
                critique=f"Unparseable judge response: {raw[:200]}",
                verifier_agent_id=verifier_id,
            )
        accepted = bool(payload.get("accepted", False))
        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(1.0, max(0.0, confidence))
        critique = str(payload.get("critique", "")).strip()
        return VerificationVerdict(
            accepted=accepted,
            confidence=confidence,
            critique=critique,
            verifier_agent_id=verifier_id,
        )

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, Any] | None:
        """Extract the first top-level JSON object from ``raw``, or ``None``."""
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except (ValueError, TypeError):
            pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            parsed = json.loads(raw[start : end + 1])
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
