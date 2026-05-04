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

    Mutable — `decision` and `decided_at`/`decided_by` are populated when
    the Captain approves or rejects via the API. Frozen would block that.
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
    """Analysis-only proposal service (AD-659 v1).

    Reads recent chain traces from runtime.cognitive_journal, runs detector
    functions, accumulates proposals in `pending_proposals`. Does NOT apply
    any proposal — `apply_proposal()` raises NotImplementedError until AD-659b.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        analysis_window: int = 100,
        latency_p95_ms_floor: float = 10000.0,
        success_rate_floor: float = 0.7,
        error_rate_ceiling: float = 0.3,
        min_samples_per_group: int = 20,
        emit_event: Callable[..., None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._analysis_window = analysis_window
        self._latency_p95_ms_floor = latency_p95_ms_floor
        self._success_rate_floor = success_rate_floor
        self._error_rate_ceiling = error_rate_ceiling
        self._min_samples_per_group = min_samples_per_group
        self.emit_event = emit_event
        self.pending_proposals: list[OptimizationProposal] = []

    async def analyze(
        self, *, window: int | None = None,
    ) -> list[OptimizationProposal]:
        """Read recent traces, run detectors, append new proposals.

        Returns the list of proposals produced by this analysis pass
        (NOT the cumulative `pending_proposals`). Idempotent in the sense
        that re-running over the same window appends a fresh batch — v1
        does NOT de-duplicate (deferred to AD-659b).
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
        new_proposals: list[OptimizationProposal] = []
        new_proposals.extend(detect_latency_p95_regression(
            traces,
            p95_floor_ms=self._latency_p95_ms_floor,
            min_samples=self._min_samples_per_group,
        ))
        new_proposals.extend(detect_success_rate_floor_breach(
            traces,
            success_floor=self._success_rate_floor,
            min_samples=self._min_samples_per_group,
        ))
        new_proposals.extend(detect_high_error_rate_by_chain_source(
            traces,
            error_rate_ceiling=self._error_rate_ceiling,
            min_samples=self._min_samples_per_group,
        ))
        self.pending_proposals.extend(new_proposals)
        return new_proposals

    def list_pending(self) -> list[OptimizationProposal]:
        """Return all pending (undecided) proposals."""
        return [p for p in self.pending_proposals if p.decision is None]

    def decide(
        self, proposal_id: str, decision: str, *, actor: str = "captain",
    ) -> OptimizationProposal | None:
        """Record approve/reject on a proposal. v1 stores decision only —
        does NOT apply.
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
                return p
        return None

    def apply_proposal(self, proposal_id: str) -> None:
        """v1 stub. Apply path is AD-659b; v1 is analysis-only."""
        raise NotImplementedError(
            "v1 analysis-only; apply deferred to AD-659b"
        )
