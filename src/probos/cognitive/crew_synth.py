"""AD-861: Result synthesis + Shapley attribution -> parent completion.

The crew fan-out executor (AD-859) drives a parent's child sub-tasks to
completion; the adversarial verifier (AD-860) folds each child into a
:class:`ConvergenceOutcome` carrying the producer's :class:`SubtaskResult` plus
the independent verifier's :class:`VerificationVerdict`. :class:`CrewSynthesizer`
is the final stage: it folds the *verified* outcomes into one parent completion.

Three things happen, in order, all honest-degrading:

1. **Synthesis.** The accepted outcomes (``oc.verdict.accepted``) are summarised
   by the LLM (standard tier) into the parent's final output. A bad/empty LLM
   response degrades to a deterministic concatenation of the accepted outputs —
   never a silent empty completion.
2. **Completion.** The parent is moved to ``done`` via the *validated*
   :meth:`WorkItemStore.transition_work_item` (AD-498 state machine) — NOT a raw
   ``update_work_item(status=...)`` which would bypass the gate. A ``None`` return
   is an honest-degrade (logged), never treated as silent success. The full
   provenance (which sub-tasks + which verifiers contributed) is stored as a
   content-addressable ref via :meth:`AttachmentStore.write` (AD-731 — never
   inline in the work-item metadata), and only the ref + a small attribution
    summary are written back with ``merge_work_item_metadata(...)``.
3. **Attribution + learning.** One producer :class:`Vote` per accepted outcome
   plus one verifier Vote per outcome with a non-empty ``verifier_agent_id``
   (reusing :meth:`SubtaskVerifier.verdict_to_vote`) feed
   :func:`compute_shapley_values` (the same consensus path, not a parallel one)
   to compute each crew member's marginal contribution. Each agent's success is
   recorded against the :class:`TrustNetwork` ledger (synchronously), and a
   collaboration :class:`Episode` is stored (guarded — ``episodic_memory`` is
   ``None`` when disabled) so the Hebbian "which collaborators work well
   together" payoff lands.

Constructor injection mirrors :class:`SubtaskVerifier`: every collaborator is
supplied by the caller so the synthesiser depends on abstractions, not
concretions, and is trivially testable with fakes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from probos.cognitive.crew_verifier import SubtaskVerifier
from probos.consensus.shapley import compute_shapley_values
from probos.events import EventType
from probos.types import Episode, LLMRequest, QuorumPolicy, Vote

if TYPE_CHECKING:
    from collections.abc import Callable

    from probos.attachments.store import AttachmentStore
    from probos.cognitive.crew_verifier import (
        ConvergenceOutcome,
        SessionConvergenceOutcome,
    )
    from probos.cognitive.episodic import EpisodicMemory
    from probos.consensus.trust import TrustNetwork
    from probos.workforce import WorkItemStore

logger = logging.getLogger(__name__)

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_MAX_SESSION_SYNTHESIS_INPUT_BYTES = 1_048_576
_MAX_SESSION_SYNTHESIS_OUTPUT_BYTES = 262_144
_MAX_SESSION_RESULT_BYTES = 65_536
_MAX_SESSION_TOKENS = 9_223_372_036_854_775_807


@dataclass
class SynthesisResult:
    """The terminal result of folding a crew's verified outcomes into the parent.

    ``final_output`` is the synthesised parent answer, ``completed`` is whether
    the parent reached ``done`` through the validated state machine (``False``
    when ``transition_work_item`` honest-degraded), ``shapley_values`` maps each
    crew member's ``agent_id`` to their marginal contribution in ``[0, 1]``,
    ``provenance_ref`` is the content-addressable hash of the stored provenance
    blob (``None`` when the attachment store was unwired or write failed), and
    ``accepted_count`` / ``total_count`` record how many of the input outcomes
    were accepted (a partial collaboration synthesises from accepted-only).
    """

    parent_id: str
    final_output: str
    completed: bool
    shapley_values: dict[str, float] = field(default_factory=dict)
    provenance_ref: str | None = None
    accepted_count: int = 0
    total_count: int = 0


@dataclass(frozen=True)
class SessionSynthesisDraft:
    producer_agent_id: str
    final_text: str
    tokens_used: int


class CrewSynthesizer:
    """Fold verified crew :class:`ConvergenceOutcome`s into parent completion.

    Constructor injection (Dependency Inversion): every collaborator is supplied
    by the caller, mirroring :class:`SubtaskVerifier`.
    """

    _SYSTEM_PROMPT = (
        "You are the lead of a crew of collaborating agents. Your crew has each "
        "completed and independently verified a sub-task of a larger task. Fold "
        "their verified outputs into a single, coherent final answer for the "
        "parent task. Do not invent content beyond what the sub-task outputs "
        "support. Respond with the final answer only — no preamble, no meta "
        "commentary."
    )
    _SESSION_SYSTEM_PROMPT = (
        "You are the server-selected facilitator producing the final human-visible "
        "result for a durable crew session. Synthesize only from the accepted "
        "child outputs and the exact parent contract. Do not claim unsupported "
        "artifacts or invent evidence. Return only the final result."
    )

    def __init__(
        self,
        *,
        llm_client: Any,
        work_item_store: "WorkItemStore",
        trust_network: "TrustNetwork",
        episodic_memory: "EpisodicMemory | None",
        attachment_store: "AttachmentStore | None",
        runtime: Any,
        emit_fn: "Callable[[EventType, dict[str, Any]], None] | None" = None,
        quorum_policy: QuorumPolicy | None = None,
    ) -> None:
        self._llm = llm_client
        self._store = work_item_store
        self._trust = trust_network
        self._episodic = episodic_memory
        self._attachments = attachment_store
        self._runtime = runtime
        self._emit_fn = emit_fn
        self._policy = quorum_policy or QuorumPolicy()

    # ------------------------------------------------------------------ public

    async def synthesize(
        self, parent_id: str, outcomes: list["ConvergenceOutcome"],
    ) -> SynthesisResult:
        """Fold ``outcomes`` (from AD-860) into the parent's completion.

        Synthesises the parent output from the accepted outcomes, transitions the
        parent to ``done`` through the validated state machine, computes Shapley
        attribution across producers and verifiers, records each agent's success
        against the trust ledger, stores a collaboration episode (guarded), and
        emits :attr:`EventType.CREW_TASK_COMPLETED`. Honest-degrades at every
        boundary — a missing LLM, attachment store, or invalid transition never
        raises.
        """
        accepted = [oc for oc in outcomes if oc.verdict.accepted]
        final_output = await self._synthesize_output(parent_id, accepted)

        provenance_ref = await self._store_provenance(parent_id, outcomes, accepted)
        completed = await self._complete_parent(parent_id, provenance_ref, accepted, outcomes)

        votes = self._build_votes(accepted)
        shapley = self._attribute(votes)
        self._record_trust(shapley, accepted)
        await self._store_episode(parent_id, final_output, accepted, outcomes, shapley)

        self._emit(EventType.CREW_TASK_COMPLETED, {
            "parent_id": parent_id,
            "completed": completed,
            "accepted_count": len(accepted),
            "total_count": len(outcomes),
            "shapley_values": dict(shapley),
            "provenance_ref": provenance_ref,
        })

        return SynthesisResult(
            parent_id=parent_id,
            final_output=final_output,
            completed=completed,
            shapley_values=shapley,
            provenance_ref=provenance_ref,
            accepted_count=len(accepted),
            total_count=len(outcomes),
        )

    async def synthesize_for_session(
        self,
        *,
        parent_id: str,
        producer_agent_id: str,
        producer_instructions: str,
        goal: str,
        success_criteria: tuple[str, ...],
        expected_deliverable: str,
        outcomes: tuple["SessionConvergenceOutcome", ...],
    ) -> SessionSynthesisDraft:
        """Produce one bounded session draft without completion or learning writes."""
        parent_key = self._session_id(parent_id)
        producer_key = self._session_id(producer_agent_id)
        instructions = self._session_text(
            producer_instructions,
            maximum_bytes=32_768,
            error="session_synthesis_producer_invalid",
        )
        normalized_goal = self._session_text(
            goal,
            maximum_bytes=16_384,
            error="session_synthesis_input_invalid",
        )
        deliverable = self._session_text(
            expected_deliverable,
            maximum_bytes=8_192,
            error="session_synthesis_input_invalid",
        )
        if (
            type(success_criteria) is not tuple
            or not 1 <= len(success_criteria) <= 16
            or type(outcomes) is not tuple
            or not 1 <= len(outcomes) <= 1_000
        ):
            raise ValueError("session_synthesis_input_invalid")
        criteria = tuple(
            self._session_text(
                criterion,
                maximum_bytes=2_048,
                error="session_synthesis_input_invalid",
            )
            for criterion in success_criteria
        )
        if len(set(criteria)) != len(criteria):
            raise ValueError("session_synthesis_input_invalid")

        chunks = [
            f"PARENT SESSION: {parent_key}\n",
            f"GOAL:\n{normalized_goal}\n\n",
            "SUCCESS CRITERIA:\n",
        ]
        prompt_bytes = sum(len(chunk.encode("utf-8")) for chunk in chunks)
        for index, criterion in enumerate(criteria, start=1):
            chunk = f"{index}. {criterion}\n"
            prompt_bytes += len(chunk.encode("utf-8"))
            if prompt_bytes > _MAX_SESSION_SYNTHESIS_INPUT_BYTES:
                raise ValueError("session_synthesis_input_too_large")
            chunks.append(chunk)
        tail = [
            f"\nEXPECTED DELIVERABLE:\n{deliverable}\n\n",
            "ACCEPTED CHILD OUTPUTS:\n",
        ]
        prompt_bytes += sum(len(chunk.encode("utf-8")) for chunk in tail)
        if prompt_bytes > _MAX_SESSION_SYNTHESIS_INPUT_BYTES:
            raise ValueError("session_synthesis_input_too_large")
        chunks.extend(tail)
        for index, outcome in enumerate(outcomes, start=1):
            if (
                getattr(outcome, "accepted", None) is not True
                or getattr(outcome, "status", None) != "converged"
            ):
                raise ValueError("session_synthesis_outcome_invalid")
            result = getattr(outcome, "result", None)
            child_id = self._session_id(getattr(result, "work_item_id", None))
            child_producer = self._session_id(getattr(result, "agent_id", None))
            output = self._session_text(
                getattr(result, "output", None),
                maximum_bytes=_MAX_SESSION_RESULT_BYTES,
                error="session_synthesis_outcome_invalid",
            )
            chunk = (
                f"--- CHILD {index} id={child_id} producer={child_producer} ---\n"
                f"{output}\n"
            )
            prompt_bytes += len(chunk.encode("utf-8"))
            if prompt_bytes > _MAX_SESSION_SYNTHESIS_INPUT_BYTES:
                raise ValueError("session_synthesis_input_too_large")
            chunks.append(chunk)
        prompt = "".join(chunks)
        if len(prompt.encode("utf-8")) > _MAX_SESSION_SYNTHESIS_INPUT_BYTES:
            raise ValueError("session_synthesis_input_too_large")
        system_prompt = f"{self._SESSION_SYSTEM_PROMPT}\n\nFACILITATOR INSTRUCTIONS:\n{instructions}"
        try:
            response = await self._llm.complete(LLMRequest(
                prompt=prompt,
                system_prompt=system_prompt,
                tier="standard",
            ))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ValueError("session_synthesis_failed") from exc
        final_text = self._session_text(
            getattr(response, "content", None),
            maximum_bytes=_MAX_SESSION_SYNTHESIS_OUTPUT_BYTES,
            error="session_synthesis_failed",
        )
        tokens = getattr(response, "tokens_used", None)
        if type(tokens) is not int or not 0 <= tokens <= _MAX_SESSION_TOKENS:
            raise ValueError("session_synthesis_failed")
        return SessionSynthesisDraft(
            producer_agent_id=producer_key,
            final_text=final_text,
            tokens_used=tokens,
        )

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _session_id(value: Any) -> str:
        if type(value) is not str or _SESSION_ID_RE.fullmatch(value) is None:
            raise ValueError("session_synthesis_id_invalid")
        return value

    @staticmethod
    def _session_text(value: Any, *, maximum_bytes: int, error: str) -> str:
        if type(value) is not str or "\x00" in value:
            raise ValueError(error)
        normalized = value.strip()
        if not normalized or len(normalized.encode("utf-8")) > maximum_bytes:
            raise ValueError(error)
        return normalized

    async def _synthesize_output(
        self, parent_id: str, accepted: list["ConvergenceOutcome"],
    ) -> str:
        """LLM-synthesise the parent output from accepted outputs; degrade to a
        deterministic concatenation on any failure or empty response."""
        fallback = self._concat_fallback(accepted)
        if not accepted:
            logger.warning(
                "AD-861: no accepted sub-task outcomes for parent %s; "
                "synthesising an empty/degraded parent output (caveat recorded)",
                parent_id,
            )
            return fallback
        try:
            request = LLMRequest(
                prompt=self._build_synthesis_prompt(accepted),
                system_prompt=self._SYSTEM_PROMPT,
                tier="standard",
            )
            response = await self._llm.complete(request)
            content = (getattr(response, "content", "") or "").strip()
            if not content:
                logger.warning(
                    "AD-861: LLM synthesis returned empty content for parent %s; "
                    "degrading to a deterministic concatenation of accepted outputs",
                    parent_id,
                )
                return fallback
            return content
        except Exception:
            logger.warning(
                "AD-861: LLM synthesis failed for parent %s; degrading to a "
                "deterministic concatenation of accepted outputs",
                parent_id, exc_info=True,
            )
            return fallback

    def _build_synthesis_prompt(self, accepted: list["ConvergenceOutcome"]) -> str:
        parts = ["Fold these verified sub-task outputs into one final answer:\n"]
        for i, oc in enumerate(accepted, start=1):
            parts.append(
                f"--- Sub-task {i} (agent {oc.result.agent_id}) ---\n{oc.result.output}\n"
            )
        return "\n".join(parts)

    @staticmethod
    def _concat_fallback(accepted: list["ConvergenceOutcome"]) -> str:
        return "\n\n".join(oc.result.output for oc in accepted)

    async def _store_provenance(
        self,
        parent_id: str,
        outcomes: list["ConvergenceOutcome"],
        accepted: list["ConvergenceOutcome"],
    ) -> str | None:
        """Persist the full provenance blob as a content-addressable ref (AD-731).

        Returns the sha256 ref, or ``None`` when the attachment store is unwired
        or the write fails (honest-degrade — provenance is best-effort)."""
        if self._attachments is None:
            logger.warning(
                "AD-861: no attachment store wired; parent %s provenance will not "
                "be persisted (ref=None)",
                parent_id,
            )
            return None
        try:
            provenance = {
                "parent_id": parent_id,
                "accepted_count": len(accepted),
                "total_count": len(outcomes),
                "subtasks": [
                    {
                        "work_item_id": oc.result.work_item_id,
                        "spec_id": oc.result.spec_id,
                        "producer_agent_id": oc.result.agent_id,
                        "verifier_agent_id": oc.verdict.verifier_agent_id,
                        "accepted": oc.verdict.accepted,
                        # BF-784: without this a reader cannot tell work that was
                        # judged and found wanting from work that was never judged.
                        "verification_defect": oc.verdict.verification_defect,
                        "confidence": oc.verdict.confidence,
                        "status": oc.status,
                        "rounds": oc.rounds,
                        "critique": oc.verdict.critique,
                    }
                    for oc in outcomes
                ],
            }
            blob = json.dumps(provenance, sort_keys=True, default=str).encode("utf-8")
            content_hash = hashlib.sha256(blob).hexdigest()
            await self._attachments.write(
                content_hash=content_hash,
                blob=blob,
                mime="application/json",
                origin="crew_synth_provenance",
            )
            return content_hash
        except Exception:
            logger.warning(
                "AD-861: failed to persist provenance for parent %s; "
                "provenance_ref will be None",
                parent_id, exc_info=True,
            )
            return None

    async def _complete_parent(
        self,
        parent_id: str,
        provenance_ref: str | None,
        accepted: list["ConvergenceOutcome"],
        outcomes: list["ConvergenceOutcome"],
    ) -> bool:
        """Transition the parent to ``done`` through the validated AD-498 state
        machine, then write the provenance ref + attribution summary as metadata.

        Returns ``True`` only when the validated transition succeeded; a ``None``
        return from :meth:`transition_work_item` is an honest-degrade, never
        silent success."""
        transitioned = await self._store.transition_work_item(
            parent_id, "done", source="crew_synth",
        )
        if transitioned is None:
            logger.warning(
                "AD-861: parent %s could not transition to 'done' (invalid "
                "transition for its work type or item missing); honest-degrading "
                "— the parent is NOT marked complete",
                parent_id,
            )
            completed = False
        else:
            completed = True
        # Provenance metadata is written regardless of the status outcome so the
        # contribution record survives even an honest-degraded completion.
        try:
            await self._store.merge_work_item_metadata(
                parent_id,
                {"crew_synth": {
                    "provenance_ref": provenance_ref,
                    "completed": completed,
                    "accepted_count": len(accepted),
                    "total_count": len(outcomes),
                    "caveat": (
                        ""
                        if len(accepted) == len(outcomes)
                        else "partial: synthesised from accepted sub-tasks only"
                    ),
                }},
            )
        except Exception:
            logger.warning(
                "AD-861: failed to write crew-synth provenance metadata for "
                "parent %s; the completion stands but provenance is unrecorded",
                parent_id, exc_info=True,
            )
        return completed

    def _build_votes(self, accepted: list["ConvergenceOutcome"]) -> list[Vote]:
        """Build the Shapley input: one producer Vote per accepted outcome plus
        one verifier Vote per outcome with a non-empty ``verifier_agent_id``.

        Skips the honest-degrade ``unverified`` case (empty ``verifier_agent_id``
        — producer Vote only). Shapley keys by ``agent_id``: an agent that is both
        a producer and a verifier in the same set yields two Votes, and
        ``compute_shapley_values`` builds ``{v.agent_id: v}`` — so the LAST one
        wins outright rather than being combined. Filed separately; it does not
        reach trust today because ``_record_trust`` writes a flat success rather
        than a Shapley-weighted one."""
        votes: list[Vote] = []
        for oc in accepted:
            votes.append(Vote(
                agent_id=oc.result.agent_id,
                approved=oc.verdict.accepted,
                confidence=oc.verdict.confidence,
                reason=f"producer of sub-task {oc.result.spec_id}",
            ))
            if oc.verdict.verifier_agent_id:
                votes.append(SubtaskVerifier.verdict_to_vote(oc.verdict))
        return votes

    def _attribute(self, votes: list[Vote]) -> dict[str, float]:
        """Compute each crew member's marginal contribution via the consensus
        Shapley path. Pins ``approval_threshold`` from the runtime quorum policy
        (AD-498) rather than a bare literal."""
        if not votes:
            return {}
        return compute_shapley_values(
            votes,
            approval_threshold=self._policy.approval_threshold,
            use_confidence_weights=self._policy.use_confidence_weights,
        )

    def _record_trust(
        self,
        shapley: dict[str, float],
        accepted: list["ConvergenceOutcome"],
    ) -> None:
        """Record each contributing PRODUCER's success against the trust ledger.

        BF-783: this recorded every attributed agent with `success=True`, which
        included accepted verifiers and so reconstituted the exact incentive
        BF-778 removed one layer down -- accepting paid, refusing paid nothing,
        because a refused result never reaches synthesis at all. Measured: an
        accepting verifier went from Beta(2,2) to Beta(3,2) on acceptance alone.

        A producer contributed work the synthesis shows was good. A verifier
        contributed a JUDGEMENT, whose correctness the work shipping does not
        establish -- a judge that waves everything through appears in every
        successful synthesis.

        Verifier trust is therefore left NEUTRAL here, and no other live path
        moves it: `record_verification_outcome` has no production caller
        pending BF-782. This is a deliberate absence, not a delegation -- a
        verifier earns trust only in another role until that lands.

        Agents that both produced and verified keep their producer credit; the
        exclusion is verifier-ONLY agents. `accepted` is required rather than
        defaulted: an omitted argument would silently restore the defect.

        Synchronous keyword call (mirrors AD-860) -- never ``await``.
        """
        producers = {oc.result.agent_id for oc in accepted if oc.result.agent_id}
        verifiers = {
            oc.verdict.verifier_agent_id
            for oc in accepted
            if oc.verdict.verifier_agent_id
        }
        verifier_only = verifiers - producers

        for agent_id in shapley:
            if not agent_id or agent_id in verifier_only:
                continue
            try:
                self._trust.record_outcome(
                    agent_id,
                    success=True,
                    intent_type="crew_collaboration",
                    source="crew_synth",
                )
            except Exception:
                logger.warning(
                    "AD-861: failed to record trust outcome for crew member %s; "
                    "continuing — attribution stands but the ledger update was skipped",
                    agent_id, exc_info=True,
                )

    async def _store_episode(
        self,
        parent_id: str,
        final_output: str,
        accepted: list["ConvergenceOutcome"],
        outcomes: list["ConvergenceOutcome"],
        shapley: dict[str, float],
    ) -> None:
        """Store a collaboration episode (guarded) so the Hebbian "which
        collaborators work well together" payoff lands.

        Honest-degrades when ``episodic_memory`` is disabled (``None``) — the
        learning signal is best-effort, never a crash."""
        if self._episodic is None:
            logger.debug(
                "AD-861: episodic memory disabled; skipping the collaboration "
                "episode for parent %s (no learning-loop payoff this run)",
                parent_id,
            )
            return
        try:
            agent_ids = sorted(shapley.keys())
            episode_outcomes = [
                {
                    "work_item_id": oc.result.work_item_id,
                    "producer_agent_id": oc.result.agent_id,
                    "verifier_agent_id": oc.verdict.verifier_agent_id,
                    "accepted": oc.verdict.accepted,
                    "verification_defect": oc.verdict.verification_defect,
                    "status": oc.status,
                }
                for oc in outcomes
            ]
            episode = Episode(
                timestamp=time.time(),
                user_input=f"crew collaboration on parent work item {parent_id}",
                dag_summary={
                    "parent_id": parent_id,
                    "accepted_count": len(accepted),
                    "total_count": len(outcomes),
                },
                outcomes=episode_outcomes,
                reflection=final_output,
                agent_ids=agent_ids,
                shapley_values=dict(shapley),
                source="crew_collaboration",
            )
            await self._episodic.store(episode)
        except Exception:
            logger.warning(
                "AD-861: failed to store the collaboration episode for parent %s; "
                "the collaboration completed but the learning signal was lost",
                parent_id, exc_info=True,
            )

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Publish a lifecycle event, honest-degrading when no emit fn is wired."""
        if self._emit_fn is None:
            return
        try:
            self._emit_fn(event_type, data)
        except Exception:
            logger.warning(
                "AD-861: crew synthesiser failed to emit %s; continuing without "
                "the event",
                event_type, exc_info=True,
            )
