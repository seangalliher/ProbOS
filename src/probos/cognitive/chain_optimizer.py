"""ChainOptimizer — analysis-only proposal service for cognitive-chain tuning (AD-659 v1).

v1 reads recent ChainExecutionTrace rows via runtime.cognitive_journal,
runs three pure detector functions, and accumulates OptimizationProposal
instances in an in-memory pending queue. v1 does NOT apply any proposal —
apply_proposal() raises NotImplementedError; the apply path is AD-659b.

Captain approval surface is exposed via routers/chain_optimizer.py.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class OptimizationProposal:
    """Single proposed adjustment to a Code-Switching modulation parameter.

    Mutable — `decision`/`decided_at`/`decided_by` are populated by the
    Captain via the API; `applied`/`applied_at`/`applied_by`/`pre_apply_value`
    are populated by `ChainOptimizer.apply_proposal()` (AD-659b).
    """

    target_parameter: str          # e.g. "chain_tuning.low_trust_ceiling"
    current_value: Any             # e.g. 0.60
    proposed_value: Any            # e.g. 0.55
    rationale: str                 # human-readable reasoning
    supporting_metric: str         # e.g. "success rate 0.42 over last 100 traces"
    risk_level: str                # "low" | "medium" | "high"
    detector_name: str             # name of the detector that produced this
    proposal_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: float = field(default_factory=time.time)
    decision: str | None = None    # None | "approve" | "reject"
    decided_at: float | None = None
    decided_by: str | None = None  # actor id (e.g. "captain")
    # AD-659b: apply-tracking fields (all defaulted; preserves field-order rule)
    applied: bool = False
    applied_at: float | None = None
    applied_by: str | None = None
    pre_apply_value: Any = None    # captured pre-mutation for revert

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict projection for JSON serialization."""
        return asdict(self)


# --- Pure detector functions ----------------------------------------------
# Each detector takes a list[dict] of raw chain_traces rows (as returned
# by CognitiveJournal.get_recent_chain_traces) plus threshold parameters,
# and returns a list of OptimizationProposal. No I/O. No runtime access.


def detect_latency_p95_regression(
    traces: list[dict[str, Any]],
    *,
    p95_floor_ms: float,
    min_samples: int,
) -> list[OptimizationProposal]:
    """Group by (step_name, tier); flag groups whose p95 duration_ms exceeds floor.

    Proposes shifting tier downward (standard → fast) for the offending group.
    Risk: medium (changes which model handles the step).
    """
    proposals: list[OptimizationProposal] = []
    groups: dict[tuple[str, str], list[float]] = {}
    for row in traces:
        key = (row.get("step_name", ""), row.get("tier", ""))
        groups.setdefault(key, []).append(float(row.get("duration_ms", 0.0)))
    for (step_name, tier), durations in groups.items():
        if len(durations) < min_samples:
            continue
        durations_sorted = sorted(durations)
        idx = max(0, int(len(durations_sorted) * 0.95) - 1)
        p95 = durations_sorted[idx]
        if p95 <= p95_floor_ms:
            continue
        # Only propose tier shift when current tier is "deep" or "standard"
        # ("fast" is already the lowest; nothing left to propose).
        if tier not in ("deep", "standard"):
            continue
        proposed_tier = "fast" if tier == "standard" else "standard"
        proposals.append(OptimizationProposal(
            target_parameter=f"chain_step.tier[{step_name}]",
            current_value=tier,
            proposed_value=proposed_tier,
            rationale=(
                f"Step '{step_name}' p95 latency {p95:.0f}ms exceeds "
                f"floor {p95_floor_ms:.0f}ms over {len(durations)} samples; "
                f"shift to faster tier."
            ),
            supporting_metric=(
                f"p95={p95:.0f}ms n={len(durations)} step={step_name} tier={tier}"
            ),
            risk_level="medium",
            detector_name="latency_p95_regression",
        ))
    return proposals


def detect_success_rate_floor_breach(
    traces: list[dict[str, Any]],
    *,
    success_floor: float,
    min_samples: int,
) -> list[OptimizationProposal]:
    """Group by (sub_task_type, chain_trust_band); flag groups whose success
    rate falls below floor.

    Proposes adjusting `chain_tuning.low_trust_ceiling` / `high_trust_floor`
    so fewer agents land in the offending band. Risk: medium.
    """
    proposals: list[OptimizationProposal] = []
    groups: dict[tuple[str, str], list[int]] = {}
    for row in traces:
        band = row.get("chain_trust_band") or "unknown"
        key = (row.get("sub_task_type", ""), band)
        groups.setdefault(key, []).append(int(bool(row.get("success", 0))))
    for (sub_task_type, band), outcomes in groups.items():
        if len(outcomes) < min_samples:
            continue
        rate = sum(outcomes) / len(outcomes)
        if rate >= success_floor:
            continue
        # Propose nudging the offending band's threshold inward by 0.05.
        if band == "low":
            target = "chain_tuning.low_trust_ceiling"
            current = 0.60
            proposed = round(current + 0.05, 2)
        elif band == "high":
            target = "chain_tuning.high_trust_floor"
            current = 0.75
            proposed = round(current + 0.05, 2)
        else:
            # "mid" / "unknown" — no single-knob fix; record observation only.
            continue
        proposals.append(OptimizationProposal(
            target_parameter=target,
            current_value=current,
            proposed_value=proposed,
            rationale=(
                f"sub_task_type='{sub_task_type}' under trust_band='{band}' "
                f"shows success rate {rate:.2f} below floor {success_floor:.2f} "
                f"over {len(outcomes)} samples; tighten band threshold."
            ),
            supporting_metric=(
                f"success_rate={rate:.2f} n={len(outcomes)} "
                f"sub_task_type={sub_task_type} band={band}"
            ),
            risk_level="medium",
            detector_name="success_rate_floor_breach",
        ))
    return proposals


def detect_high_error_rate_by_chain_source(
    traces: list[dict[str, Any]],
    *,
    error_rate_ceiling: float,
    min_samples: int,
) -> list[OptimizationProposal]:
    """Group by chain_source; flag sources whose error rate exceeds ceiling.

    Observation-only proposal: flags chain_source as a candidate for review
    (no specific config knob to nudge — proposal asks Captain to inspect).
    Risk: low (no parameter change proposed).
    """
    proposals: list[OptimizationProposal] = []
    groups: dict[str, list[int]] = {}
    for row in traces:
        src = row.get("chain_source") or "unknown"
        groups.setdefault(src, []).append(0 if bool(row.get("success", 0)) else 1)
    for src, errors in groups.items():
        if len(errors) < min_samples:
            continue
        rate = sum(errors) / len(errors)
        if rate <= error_rate_ceiling:
            continue
        proposals.append(OptimizationProposal(
            target_parameter=f"chain_source.review[{src}]",
            current_value="active",
            proposed_value="review",
            rationale=(
                f"chain_source='{src}' shows error rate {rate:.2f} above "
                f"ceiling {error_rate_ceiling:.2f} over {len(errors)} samples; "
                f"flag for Captain review."
            ),
            supporting_metric=(
                f"error_rate={rate:.2f} n={len(errors)} chain_source={src}"
            ),
            risk_level="low",
            detector_name="high_error_rate_by_chain_source",
        ))
    return proposals


# --- Service ---------------------------------------------------------------


class ChainOptimizer:
    """Cognitive-chain self-optimization service (AD-659 v1 + AD-659b).

    AD-659 shipped analysis-only proposal generation; AD-659b adds:
      - SQLite persistence via runtime.cognitive_journal
      - dedup keyed on (detector_name, target_parameter) for pending entries
      - apply_proposal() (gated by apply_enabled) for chain_tuning.* targets
      - revert_proposal() for manual rollback
      - opt-in scheduled analyze loop (analysis_interval_seconds > 0)

    Apply path is intentionally narrow: only `chain_tuning.low_trust_ceiling`
    and `chain_tuning.high_trust_floor` are mutated. Tier shifts and chain-
    source-review flags raise ValueError — those are AD-659b-1 territory.
    """

    # AD-659b: target_parameters that the apply path can mutate.
    _APPLYABLE_TUNING_FIELDS = ("low_trust_ceiling", "high_trust_floor")

    def __init__(
        self,
        runtime: Any,
        *,
        analysis_window: int = 100,
        latency_p95_ms_floor: float = 10000.0,
        success_rate_floor: float = 0.7,
        error_rate_ceiling: float = 0.3,
        min_samples_per_group: int = 20,
        apply_enabled: bool = False,
        analysis_interval_seconds: int = 0,
        emit_event: Callable[..., None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._analysis_window = analysis_window
        self._latency_p95_ms_floor = latency_p95_ms_floor
        self._success_rate_floor = success_rate_floor
        self._error_rate_ceiling = error_rate_ceiling
        self._min_samples_per_group = min_samples_per_group
        self._apply_enabled = apply_enabled
        self._analysis_interval_seconds = analysis_interval_seconds
        self.emit_event = emit_event
        self.pending_proposals: list[OptimizationProposal] = []
        self._loop_task: Any = None  # asyncio.Task when scheduled loop active

    async def analyze(
        self, *, window: int | None = None,
    ) -> list[OptimizationProposal]:
        """Read recent traces, run detectors, append new proposals.

        AD-659b: dedup on (detector_name, target_parameter) — if an undecided
        proposal already exists in `pending_proposals` OR in the journal
        with the same key, the new proposal is dropped. Persists every
        retained proposal to `runtime.cognitive_journal`.
        """
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is None:
            return []
        n = window if window is not None else self._analysis_window
        try:
            traces = await journal.get_recent_chain_traces(limit=n)
        except Exception:
            logger.warning(
                "AD-659: get_recent_chain_traces failed; skipping analysis",
                exc_info=True,
            )
            return []
        candidate_proposals: list[OptimizationProposal] = []
        candidate_proposals.extend(detect_latency_p95_regression(
            traces,
            p95_floor_ms=self._latency_p95_ms_floor,
            min_samples=self._min_samples_per_group,
        ))
        candidate_proposals.extend(detect_success_rate_floor_breach(
            traces,
            success_floor=self._success_rate_floor,
            min_samples=self._min_samples_per_group,
        ))
        candidate_proposals.extend(detect_high_error_rate_by_chain_source(
            traces,
            error_rate_ceiling=self._error_rate_ceiling,
            min_samples=self._min_samples_per_group,
        ))
        retained: list[OptimizationProposal] = []
        for proposal in candidate_proposals:
            if await self._is_duplicate_pending(journal, proposal):
                continue
            self.pending_proposals.append(proposal)
            retained.append(proposal)
            await journal.record_optimization_proposal(proposal)
        return retained

    async def _is_duplicate_pending(
        self, journal: Any, proposal: OptimizationProposal,
    ) -> bool:
        """AD-659b: True if an undecided proposal with the same dedup key exists."""
        # In-memory check (covers the current session)
        for existing in self.pending_proposals:
            if (
                existing.decision is None
                and existing.detector_name == proposal.detector_name
                and existing.target_parameter == proposal.target_parameter
            ):
                return True
        # Journal check (covers prior-restart entries)
        try:
            rows = await journal.get_pending_optimization_proposals(
                detector_name=proposal.detector_name,
                target_parameter=proposal.target_parameter,
            )
        except Exception:
            return False
        return bool(rows)

    def list_pending(self) -> list[OptimizationProposal]:
        """Return all pending (undecided) proposals."""
        return [p for p in self.pending_proposals if p.decision is None]

    async def decide(
        self, proposal_id: str, decision: str, *, actor: str = "captain",
    ) -> OptimizationProposal | None:
        """AD-659 v1 + AD-659b: Record approve/reject. Persists the update
        to the journal. Does NOT mutate `runtime.config` — call apply_proposal
        for that.
        """
        if decision not in ("approve", "reject"):
            raise ValueError(
                f"decision must be 'approve' or 'reject', got {decision!r}"
            )
        for p in self.pending_proposals:
            if p.proposal_id == proposal_id:
                p.decision = decision
                p.decided_at = time.time()
                p.decided_by = actor
                journal = getattr(self._runtime, "cognitive_journal", None)
                if journal is not None:
                    await journal.record_optimization_proposal(p)
                return p
        return None

    async def apply_proposal(
        self, proposal_id: str, *, actor: str = "captain",
    ) -> OptimizationProposal:
        """AD-659b: Apply an approved proposal to live `runtime.config`.

        Only `chain_tuning.low_trust_ceiling` and `chain_tuning.high_trust_floor`
        are mutable in v1. Tier shifts and chain-source review flags raise
        ValueError (deferred to AD-659b-1).

        Raises:
            RuntimeError: if `apply_enabled=False` (Captain has not opted in).
            ValueError: if proposal not found, not approved, or non-tunable target.
        """
        if not self._apply_enabled:
            raise RuntimeError(
                "AD-659b: apply_enabled=False; Captain must opt in via config"
            )
        proposal = next(
            (p for p in self.pending_proposals if p.proposal_id == proposal_id),
            None,
        )
        if proposal is None:
            raise ValueError(f"AD-659b: proposal {proposal_id!r} not found")
        if proposal.decision != "approve":
            raise ValueError(
                f"AD-659b: proposal {proposal_id!r} is not approved "
                f"(decision={proposal.decision!r})"
            )
        if proposal.applied:
            raise ValueError(
                f"AD-659b: proposal {proposal_id!r} already applied"
            )
        # Only chain_tuning.<applyable_field> targets are mutable in v1.
        if not proposal.target_parameter.startswith("chain_tuning."):
            raise ValueError(
                f"AD-659b: target {proposal.target_parameter!r} is not apply-able "
                f"in v1; deferred to AD-659b-1"
            )
        field_name = proposal.target_parameter.split(".", 1)[1]
        if field_name not in self._APPLYABLE_TUNING_FIELDS:
            raise ValueError(
                f"AD-659b: target {proposal.target_parameter!r} is not apply-able "
                f"in v1; deferred to AD-659b-1"
            )
        chain_tuning = getattr(
            getattr(self._runtime, "config", None), "chain_tuning", None,
        )
        if chain_tuning is None:
            raise ValueError(
                "AD-659b: runtime.config.chain_tuning unavailable"
            )
        proposal.pre_apply_value = getattr(chain_tuning, field_name)
        setattr(chain_tuning, field_name, proposal.proposed_value)
        proposal.applied = True
        proposal.applied_at = time.time()
        proposal.applied_by = actor
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is not None:
            await journal.record_optimization_proposal(proposal)
        logger.info(
            "AD-659b: applied proposal %s — %s: %s -> %s (actor=%s)",
            proposal.proposal_id, proposal.target_parameter,
            proposal.pre_apply_value, proposal.proposed_value, actor,
        )
        # AD-659c: emit event so OptimizationCounselor watchdog can snapshot baseline.
        if self.emit_event is not None:
            try:
                from probos.events import EventType as _ET
                self.emit_event(_ET.OPTIMIZATION_PROPOSAL_APPLIED, {
                    "proposal_id": proposal.proposal_id,
                    "target_parameter": proposal.target_parameter,
                    "pre_apply_value": proposal.pre_apply_value,
                    "proposed_value": proposal.proposed_value,
                    "detector_name": proposal.detector_name,
                    "actor": actor,
                    "applied_at": proposal.applied_at,
                })
            except Exception:
                logger.debug(
                    "AD-659c: emit OPTIMIZATION_PROPOSAL_APPLIED failed",
                    exc_info=True,
                )
        return proposal

    async def revert_proposal(
        self, proposal_id: str, *, actor: str = "captain",
    ) -> OptimizationProposal:
        """AD-659b: Manually revert an applied proposal (restore pre_apply_value).

        Raises:
            ValueError: if proposal not found or not currently applied.
        """
        proposal = next(
            (p for p in self.pending_proposals if p.proposal_id == proposal_id),
            None,
        )
        if proposal is None:
            raise ValueError(f"AD-659b: proposal {proposal_id!r} not found")
        if not proposal.applied:
            raise ValueError(
                f"AD-659b: proposal {proposal_id!r} is not currently applied"
            )
        field_name = proposal.target_parameter.split(".", 1)[1]
        chain_tuning = getattr(
            getattr(self._runtime, "config", None), "chain_tuning", None,
        )
        if chain_tuning is None:
            raise ValueError(
                "AD-659b: runtime.config.chain_tuning unavailable"
            )
        setattr(chain_tuning, field_name, proposal.pre_apply_value)
        prior_value = proposal.proposed_value
        proposal.applied = False
        proposal.applied_at = time.time()
        proposal.applied_by = actor
        journal = getattr(self._runtime, "cognitive_journal", None)
        if journal is not None:
            await journal.record_optimization_proposal(proposal)
        logger.info(
            "AD-659b: reverted proposal %s — %s: %s -> %s (actor=%s)",
            proposal.proposal_id, proposal.target_parameter,
            prior_value, proposal.pre_apply_value, actor,
        )
        # AD-659c: emit event for audit trail (covers Captain-driven and
        # watchdog-driven reverts; actor distinguishes).
        if self.emit_event is not None:
            try:
                from probos.events import EventType as _ET
                self.emit_event(_ET.OPTIMIZATION_PROPOSAL_REVERTED, {
                    "proposal_id": proposal.proposal_id,
                    "target_parameter": proposal.target_parameter,
                    "reverted_to": proposal.pre_apply_value,
                    "from_value": prior_value,
                    "detector_name": proposal.detector_name,
                    "actor": actor,
                    "reverted_at": proposal.applied_at,
                })
            except Exception:
                logger.debug(
                    "AD-659c: emit OPTIMIZATION_PROPOSAL_REVERTED failed",
                    exc_info=True,
                )
        return proposal

    def start_scheduled_loop(self) -> None:
        """AD-659b: Start the periodic analyze loop if `analysis_interval_seconds > 0`.

        Idempotent — calling twice is a no-op. Stores the task on
        `self._loop_task` so the wirer can mirror it onto
        `runtime.chain_optimizer_analyze_task` for shutdown observability.
        """
        if self._analysis_interval_seconds <= 0:
            return
        if self._loop_task is not None and not self._loop_task.done():
            return
        import asyncio
        self._loop_task = asyncio.create_task(self._scheduled_loop())

    async def _scheduled_loop(self) -> None:
        """AD-659b: Periodic background analysis. Cancellation-safe."""
        import asyncio
        try:
            while True:
                try:
                    await self.analyze()
                except Exception:
                    logger.warning(
                        "AD-659b: scheduled analyze iteration failed",
                        exc_info=True,
                    )
                await asyncio.sleep(self._analysis_interval_seconds)
        except asyncio.CancelledError:
            logger.info("AD-659b: scheduled analyze loop cancelled")
            raise

    async def stop(self) -> None:
        """AD-659b: Cancel the scheduled loop if running. Idempotent."""
        if self._loop_task is None:
            return
        task = self._loop_task
        self._loop_task = None
        if task.done():
            return
        task.cancel()
        try:
            await task
        except BaseException:
            pass
