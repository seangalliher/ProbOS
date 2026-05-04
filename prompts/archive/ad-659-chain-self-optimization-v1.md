# AD-659 v1: Cognitive Chain Self-Optimization Loop (ANALYSIS ONLY)

**Status:** Drafted (Wave 31)
**Risk:** low (additive — new analysis service, new config block, new read-only API router with stub decision endpoint, in-memory proposal storage, no mutation of any runtime parameter)
**Depends on:** AD-658 v1 shipped — `ChainExecutionTrace` (`src/probos/cognitive/chain_trace.py`), `CognitiveJournal.get_recent_chain_traces` (`src/probos/cognitive/journal.py:295`), `runtime.cognitive_journal` wired (`src/probos/runtime.py:1597`); routers pattern (`src/probos/routers/chain_traces.py`); finalize-wiring pattern (`src/probos/startup/finalize.py:_wire_*`).
**Closes:** GitHub issue #318
**Source:** Meta-Harness research (Lee et al., Stanford/UW, arXiv:2603.28052) — outer-loop: propose, evaluate, store traces, iterate. v1 ships **propose** + Captain approval surface only; **evaluate** (A/B framework) and **iterate** (apply) are explicitly deferred.

---

## v1 Scope: ANALYSIS ONLY

**No automated prompt rewriting. No automatic parameter adjustment.** v1 ships the analysis service that reads chain traces, identifies failure patterns, and **PROPOSES** adjustments. Captain approval workflow and A/B testing framework are scaffolded (proposals can be approved/rejected and the decision is recorded), but **applying** an approved optimization is explicitly **NOT IMPLEMENTED** in v1 — `apply_proposal()` exists as a stub raising `NotImplementedError`.

**Guard rails per issue #318:** Captain approval (REST endpoint records decision), A/B testing mandatory (decisions are scaffolded but cannot apply), rollback on regression (n/a until apply lands), Counselor monitors (out of scope for v1; AD-659c).

This shape is the **proposal/approval surface only** — it produces evidence, lets the Captain weigh it, but does not mutate Code-Switching or chain-tuning state.

---

## Solution Overview

The chain harness already records per-step traces to `CognitiveJournal.chain_traces` (AD-658). v1 adds a **read-only analysis service** that mines those traces for three failure-pattern shapes and emits structured proposals against the **already-adjustable** Code-Switching modulation surface (AD-639 `ChainTuningConfig.low_trust_ceiling` / `high_trust_floor`; AD-639/638/649 are the **observation-derived** keys — those are observation-only and not directly tunable, so v1 proposes adjustments to the underlying config, not the per-observation snapshot).

Five additive pieces:

1. **`OptimizationProposal` dataclass** + **`ChainOptimizer` service** (`src/probos/cognitive/chain_optimizer.py`, NEW module).
2. **Three pure detector functions** (same module): `detect_latency_p95_regression`, `detect_success_rate_floor_breach`, `detect_high_error_rate_by_chain_source`. Pure: take `list[dict]` (raw journal rows) + thresholds, return `list[OptimizationProposal]`. No I/O. Easy to unit-test in isolation.
3. **`ChainOptimizerConfig`** Pydantic block on `SystemConfig` (`src/probos/config.py`) with detector thresholds and analysis window.
4. **Wirer** `_wire_chain_optimizer` in `src/probos/startup/finalize.py` (mirrors `_wire_duty_scope_provider` shape — sibling pattern). Sets `runtime.chain_optimizer` public attribute.
5. **`/api/chain-optimizer` router** (`src/probos/routers/chain_optimizer.py`, NEW) with:
   - `GET /api/chain-optimizer/proposals` — list pending proposals
   - `POST /api/chain-optimizer/proposals/{id}/decide` — record approve/reject decision (decision stored in proposal; **does NOT apply**)

## Adjustable Modulation Parameters (verify-first findings)

The "Code-Switching modulation space" referenced in issue #318 is realised at HEAD across three ADs. v1 must distinguish **adjustable config** from **observation-derived snapshot keys**:

| Source | Key | Adjustable? | Notes |
|---|---|---|---|
| AD-639 `ChainTuningConfig.low_trust_ceiling` | `0.60` (config.py:331) | ✅ YES | Pydantic config; tunable. v1 proposes adjustments here. |
| AD-639 `ChainTuningConfig.high_trust_floor` | `0.75` (config.py:332) | ✅ YES | Pydantic config; tunable. v1 proposes adjustments here. |
| AD-639 `_chain_trust_band` | "low"/"mid"/"high" | ❌ NO (derived) | Computed at observation-build time from current trust score and the ceilings above (cognitive_agent.py:2076–2085). Adjusting the ceilings shifts band assignment. |
| AD-639 `_trust_score` | float | ❌ NO (derived) | Pulled live from `runtime.trust_network.get_score(agent_type)` (cognitive_agent.py:2078). Tuned indirectly via trust outcomes, not via this AD. |
| AD-649 `_communication_context` | str | ❌ NO (derived) | Computed by `derive_communication_context(channel_name, is_dm_channel)` at cognitive_agent.py:2061. Function-shape, not threshold-shape. Out of scope. |
| AD-638 `_boot_camp_active` | bool | ❌ NO (derived) | Pulled live from `runtime.boot_camp.is_enrolled(self.id)` at cognitive_agent.py:2066–2068. Out of scope. |

**v1 proposes adjustments only to `ChainTuningConfig.low_trust_ceiling` and `ChainTuningConfig.high_trust_floor`.** The other modulation keys are observation-only — adjusting them in-flight would require AD-659b's apply path (which is explicitly deferred).

## Captain Approval Pattern (verify-first findings)

The closest existing approval surface in the codebase is the **build queue approval** flow at `src/probos/routers/build.py:150–177`:

```
POST /api/build/queue/approve  → BuildQueueApproveRequest → runtime.build_dispatcher.approve_and_merge(build_id)
POST /api/build/queue/reject   → BuildQueueRejectRequest  → runtime.build_dispatcher.reject_build(build_id)
```

v1 mirrors this REST shape exactly — `POST /api/chain-optimizer/proposals/{id}/decide` accepts `{"decision": "approve"|"reject", "actor": "captain"}` and records on the in-memory proposal. It does NOT call any merge/apply path (none exists yet).

## Counselor Integration

**Out of scope for v1.** The Counselor agent / profile store ships at `src/probos/routers/counselor.py:1–80` and provides crew-wellness summaries — not chain-trace anomaly monitoring. Wiring the Counselor as a regression watchdog requires the apply path (AD-659b) to be in place first; without apply there is nothing for the Counselor to roll back. Defer to AD-659c.

---

## Dependencies (verified anchors, all confirmed at HEAD)

```
git log -1 --oneline
  9b3abc7 (HEAD -> main, origin/main) Plan Waves 31-35: AD-659/660/661/647/635

# AD-658 surfaces (the data source)
src/probos/cognitive/chain_trace.py:14   @dataclass(frozen=True) class ChainExecutionTrace
src/probos/cognitive/chain_trace.py:18-50 fields: chain_id, step_index, step_name, sub_task_type, tier,
                                             chain_source, agent_id, agent_type, intent, intent_id,
                                             started_at, duration_ms, tokens_used, success, error_truncated,
                                             context_keys_declared, context_keys_passed, context_filter_applied,
                                             communication_context, chain_trust_band, trust_score,
                                             boot_camp_active, from_captain, is_dm
src/probos/cognitive/journal.py:295      async def get_recent_chain_traces(*, limit=50, agent_id=None, since=None) -> list[dict]
src/probos/cognitive/journal.py:325      WHERE clauses: agent_id, since (started_at)
src/probos/cognitive/journal.py:329      ORDER BY started_at DESC LIMIT ?
src/probos/cognitive/journal.py:330      returns [dict(row) for row in rows]    # rows are sqlite Row objects
src/probos/routers/chain_traces.py:1-39  GET /api/chain-traces — read pattern to mirror
src/probos/runtime.py:1597               self.cognitive_journal = comm.cognitive_journal

# AD-639 ChainTuningConfig (the proposal target)
src/probos/config.py:325                 class ChainTuningConfig(BaseModel)
src/probos/config.py:329                 enabled: bool = True
src/probos/config.py:331                 low_trust_ceiling: float = 0.60
src/probos/config.py:332                 high_trust_floor: float = 0.75
src/probos/config.py:2002                chain_tuning: ChainTuningConfig = ChainTuningConfig()  # AD-639

# Wirer pattern to mirror (sibling: AD-508 DutyScopeProvider)
src/probos/startup/finalize.py:200       def _wire_duty_scope_provider(*, runtime, config) -> bool
src/probos/startup/finalize.py:209       runtime.duty_scope_provider = DutyScopeProvider(runtime, emit_event=emit_fn)
src/probos/startup/finalize.py:159       def _wire_ship_state_snapshot(*, runtime, config) -> bool   # AD-683 v1 sibling
src/probos/startup/finalize.py:486       if _wire_ship_state_snapshot(...): logger.info(...)
src/probos/startup/finalize.py:489       if _wire_duty_scope_provider(...): logger.info(...)

# Router-registration pattern
src/probos/api.py:192                    from probos.routers import (... chain_traces, counselor, ...)
src/probos/api.py:199                    for r in (... chain_traces, counselor, ...): app.include_router(r.router)
src/probos/routers/build.py:150-177      POST /api/build/queue/{approve,reject} — approval REST shape
src/probos/routers/deps.py               get_runtime — dependency (already shipped)

# Modulation source sites (read-only context for proposals — not mutated by v1)
src/probos/cognitive/cognitive_agent.py:2061  observation["_communication_context"] = derive_communication_context(...)
src/probos/cognitive/cognitive_agent.py:2076-2085  observation["_chain_trust_band"] = "low"|"mid"|"high"
src/probos/cognitive/cognitive_agent.py:2066-2068  observation["_boot_camp_active"]

# runtime.chain_optimizer NOT YET DECLARED (verified — the new public attribute introduced by this AD)
Select-String src/probos/runtime.py "chain_optimizer"
  (no matches — confirmed)

# emit_event for tier-2 log-and-degrade events
src/probos/runtime.py:807                def emit_event(self, event, data=None) -> None
```

All grep hits accounted for. No phantom APIs. New public symbols introduced by this prompt: `OptimizationProposal`, `ChainOptimizer`, `ChainOptimizerConfig`, `_wire_chain_optimizer`, `routers.chain_optimizer`, `/api/chain-optimizer/*`, `runtime.chain_optimizer` — all defined within this prompt.

---

## Sections

### Section 1 — `OptimizationProposal` dataclass + `ChainOptimizer` service (NEW module)

Create `src/probos/cognitive/chain_optimizer.py`:

```python
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
from dataclasses import dataclass, field, asdict
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
    supporting_metric: str         # e.g. "success rate 0.42 over last 100 traces (dm_comprehension/standard)"
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
```

No private-attr leaks. `pending_proposals`, `list_pending`, `decide`, `apply_proposal`, `analyze` all public (Wave 5 convention #1). `emit_event` is a public field matching AD-456/AD-530/AD-508/AD-683 sibling shape.

### Section 2 — `ChainOptimizerConfig` Pydantic block

In `src/probos/config.py`, add a new config class adjacent to `ChainTuningConfig` (after line 333):

```python
class ChainOptimizerConfig(BaseModel):
    """AD-659 v1: Cognitive Chain Self-Optimization analysis service.

    v1 is analysis-only — produces OptimizationProposal instances which
    require Captain approval. apply_proposal() raises NotImplementedError;
    automatic application is deferred to AD-659b.
    """

    enabled: bool = False  # opt-in until validated
    analysis_window: int = 100
    latency_p95_ms_floor: float = 10000.0
    success_rate_floor: float = 0.7
    error_rate_ceiling: float = 0.3
    min_samples_per_group: int = 20
```

And register it on `SystemConfig` adjacent to the AD-639 entry. **SEARCH/REPLACE** at `config.py:2002`:

```
SEARCH:
    chain_tuning: ChainTuningConfig = ChainTuningConfig()  # AD-639
REPLACE:
    chain_tuning: ChainTuningConfig = ChainTuningConfig()  # AD-639
    chain_optimizer: ChainOptimizerConfig = ChainOptimizerConfig()  # AD-659
```

`enabled: bool = False` per Wave 10 lesson "default-True on transitional flags is breaking-change-on-first-commit anti-pattern". Captain explicitly opts in via YAML.

### Section 3 — Wirer in `startup/finalize.py`

Add `_wire_chain_optimizer` mirroring `_wire_duty_scope_provider` shape (`finalize.py:200–214`). Insert after `_wire_duty_scope_provider`:

```python
def _wire_chain_optimizer(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-659 v1: Wire ChainOptimizer analysis-only proposal service."""
    cfg = getattr(config, "chain_optimizer", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.chain_optimizer import ChainOptimizer

    emit_fn = getattr(runtime, "emit_event", None)
    runtime.chain_optimizer = ChainOptimizer(
        runtime,
        analysis_window=cfg.analysis_window,
        latency_p95_ms_floor=cfg.latency_p95_ms_floor,
        success_rate_floor=cfg.success_rate_floor,
        error_rate_ceiling=cfg.error_rate_ceiling,
        min_samples_per_group=cfg.min_samples_per_group,
        emit_event=emit_fn,
    )
    logger.info(
        "AD-659: ChainOptimizer v1 initialized "
        "(analysis-only; apply path deferred to AD-659b)"
    )
    return True
```

Register the call in the finalize entry point alongside the other `_wire_*` blocks (after `_wire_duty_scope_provider` invocation around `finalize.py:489`):

```
SEARCH:
    if _wire_duty_scope_provider(runtime=runtime, config=config):
        logger.info("AD-508: DutyScopeProvider v1 wired during finalization")

    if _wire_workspace_ontology(runtime=runtime, config=config):
REPLACE:
    if _wire_duty_scope_provider(runtime=runtime, config=config):
        logger.info("AD-508: DutyScopeProvider v1 wired during finalization")

    if _wire_chain_optimizer(runtime=runtime, config=config):
        logger.info("AD-659: ChainOptimizer v1 wired during finalization")

    if _wire_workspace_ontology(runtime=runtime, config=config):
```

### Section 4 — `/api/chain-optimizer` router (NEW module)

Create `src/probos/routers/chain_optimizer.py`:

```python
"""ProbOS API — Cognitive Chain Optimizer routes (AD-659 v1).

v1 exposes proposal listing and Captain decision recording. Application
of an approved proposal is NOT implemented — the underlying service's
apply_proposal() raises NotImplementedError.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chain-optimizer", tags=["chain-optimizer"])


class DecisionRequest(BaseModel):
    decision: str  # "approve" | "reject"
    actor: str = "captain"


@router.get("/proposals")
async def list_proposals(
    include_decided: bool = False,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-659 v1: List pending optimization proposals.

    Args:
        include_decided: If True, returns ALL proposals including
            already-approved/rejected ones. Default False = pending only.
    """
    optimizer = getattr(runtime, "chain_optimizer", None)
    if optimizer is None:
        return {"proposals": [], "enabled": False}
    if include_decided:
        proposals = optimizer.pending_proposals
    else:
        proposals = optimizer.list_pending()
    return {
        "proposals": [p.to_dict() for p in proposals],
        "enabled": True,
    }


@router.post("/proposals/{proposal_id}/decide")
async def decide_proposal(
    proposal_id: str,
    req: DecisionRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-659 v1: Record Captain's decision on a proposal.

    v1 records the decision in-memory only. Approved proposals are NOT
    applied — apply_proposal() raises NotImplementedError until AD-659b.
    """
    optimizer = getattr(runtime, "chain_optimizer", None)
    if optimizer is None:
        raise HTTPException(status_code=503, detail="ChainOptimizer not enabled")
    if req.decision not in ("approve", "reject"):
        raise HTTPException(
            status_code=400,
            detail="decision must be 'approve' or 'reject'",
        )
    proposal = optimizer.decide(proposal_id, req.decision, actor=req.actor)
    if proposal is None:
        raise HTTPException(
            status_code=404, detail=f"proposal {proposal_id} not found"
        )
    return {
        "status": "recorded",
        "applied": False,  # explicit v1 limitation
        "proposal": proposal.to_dict(),
    }
```

Register in `src/probos/api.py:192–202`. **SEARCH/REPLACE** the import tuple AND the for-loop tuple, inserting `chain_optimizer` alphabetically between `chain_traces` and `counselor`:

```
SEARCH:
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic,
    )
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic,
    ):
REPLACE:
    from probos.routers import (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic,
    )
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, chain_traces, chain_optimizer,
        counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic,
    ):
```

**Twin-block SEARCH/REPLACE risk:** the import tuple and for-loop tuple are byte-identical apart from the `from probos.routers import (` prefix and `for r in (` prefix. The single combined SEARCH block above bundles both into one replacement — disambiguation handled by including both prefix-distinct lines in one block.

---

## Tests

Create `tests/test_ad659_chain_self_optimization.py`. Minimum 7 tests; v1 ships **8** (one per detector × 3 cases + 2 service tests + 2 API tests = 8).

1. **`test_detect_latency_p95_regression_happy_path`** — synthesize 25 trace dicts for `step_name="dm_compose"`, `tier="standard"`, `duration_ms` distribution where p95 = 12000ms (above 10000ms floor); call `detect_latency_p95_regression(traces, p95_floor_ms=10000, min_samples=20)`; assert exactly one proposal returned, `target_parameter` starts with `chain_step.tier[`, `proposed_value=="fast"`, `risk_level=="medium"`, `detector_name=="latency_p95_regression"`.

2. **`test_detect_latency_p95_regression_below_min_samples_returns_empty`** — synthesize 19 traces (one below `min_samples=20`); assert returns `[]`. Validates the threshold-respect branch.

3. **`test_detect_success_rate_floor_breach_low_band`** — synthesize 25 traces with `chain_trust_band="low"`, `sub_task_type="evaluate"`, `success` 50/50 (rate 0.5 < 0.7 floor); assert exactly one proposal, `target_parameter=="chain_tuning.low_trust_ceiling"`, `current_value==0.60`, `proposed_value==0.65`. Validates band → knob mapping.

4. **`test_detect_success_rate_floor_breach_mid_band_no_proposal`** — synthesize 25 traces with `chain_trust_band="mid"`, success rate 0.5; assert returns `[]` (no single-knob fix for mid band). Validates the "skip mid/unknown" branch.

5. **`test_detect_high_error_rate_by_chain_source_happy_path`** — synthesize 25 traces with `chain_source="dm_comprehension"`, success 60/40 (error rate 0.4 > 0.3 ceiling); assert one proposal, `target_parameter` starts with `chain_source.review[`, `risk_level=="low"`. Validates observation-only proposal shape.

6. **`test_chain_optimizer_analyze_aggregates_all_detectors`** — build a `ChainOptimizer` with a stub runtime whose `cognitive_journal.get_recent_chain_traces` is an `AsyncMock` returning a hand-crafted trace list that triggers all three detectors; `await optimizer.analyze()`; assert `len(optimizer.pending_proposals) >= 3` (at least one from each detector); assert `list_pending()` returns same set; assert `optimizer.decide(p.proposal_id, "approve", actor="captain")` flips `decision`/`decided_by`/`decided_at`. Validates aggregation + decision-recording.

7. **`test_chain_optimizer_apply_proposal_raises_not_implemented`** — instantiate `ChainOptimizer(runtime=SimpleNamespace())`; assert `pytest.raises(NotImplementedError, match="AD-659b")` when calling `apply_proposal("anything")`. Validates v1 hard limit.

8. **`test_chain_optimizer_router_list_and_decide_endpoints`** — instantiate FastAPI test client with a stub runtime carrying `chain_optimizer` (real `ChainOptimizer` instance with one hand-built `OptimizationProposal` appended to `pending_proposals`); GET `/api/chain-optimizer/proposals` returns `{"proposals": [...], "enabled": True}` with the proposal; POST `/api/chain-optimizer/proposals/{id}/decide` body `{"decision": "approve", "actor": "captain"}` returns `{"status": "recorded", "applied": False, ...}`; GET again with `include_decided=False` returns empty list; POST with `decision: "garbage"` returns 400; POST against missing id returns 404. Validates the API surface end-to-end.

**Floor:** 7 tests. **Target:** 8 (current count). All tests use `tmp_path` where DB-backed (not needed for v1 since detectors are pure and journal is mocked); SimpleNamespace + AsyncMock for runtime stubs (matches existing AD-657/AD-683 fixture style).

---

## Standing Conventions Compliance

- **Convention #1 (Wave 5):** No private-attribute access. Router uses `runtime.chain_optimizer` (public). Service exposes `pending_proposals`, `list_pending`, `decide`, `apply_proposal`, `analyze`, `emit_event` — all public.
- **Convention #3 (Wave 5):** Aggressive pre-deferral. Apply path, A/B execution, persistence of decisions, automatic rollback, prompt rewriting, Counselor regression watchdog all explicitly out of scope. v1 is analysis + decision-recording only.
- **Convention #7 (Wave 5):** No theatre — three real detectors with real branches; `apply_proposal()` is honestly stubbed with `NotImplementedError("AD-659b")`. v1 limitation surfaced in API response (`"applied": False`).
- **Convention #14:** v1 ships only the **analysis surface**. Apply, persistence, A/B framework execution are explicit follow-ups (AD-659b/c).
- **Convention #15:** Three-tier exception handling — `analyze()`'s journal-call wrapped in try/except → log-and-degrade (returns `[]`); `decide()` raises `ValueError` on bad input (propagate); `apply_proposal()` raises `NotImplementedError` (propagate — explicit v1 boundary).
- **Convention #16:** Phantom-API pre-check ran. New symbols introduced by this prompt: `OptimizationProposal`, `ChainOptimizer`, `ChainOptimizerConfig`, `_wire_chain_optimizer`, `routers.chain_optimizer`. All defined within sections above. Existing surfaces all verified live (see "Verified Against Codebase").
- **Default-flag discipline (Wave 10 lesson):** `ChainOptimizerConfig.enabled = False`. Opt-in only; flip on by Captain via YAML when AD-658 has accumulated baseline data.
- **AD-682 fixture isolation:** All tests are state-isolated; service tests build a fresh `ChainOptimizer` each test; API tests build a fresh runtime stub each test.
- **Type annotations:** All public methods fully typed. Detector functions are kwargs-only on thresholds (force callers to be explicit).
- **Logging:** `analyze()` logs at `warning` level on journal failure, `info` level on wirer success. No `print()`. No bare log strings.

## What This Does NOT Change

- **No `apply_proposal()` implementation.** v1 stubs the method. AD-659b ships the apply path with mandatory A/B testing scaffolding.
- **No persistence of proposals.** `pending_proposals` is in-memory; restart clears the queue. Persistence (chain_optimizer_proposals SQLite table) deferred to AD-659b — v1 limitation called out in API response and prompt body.
- **No A/B framework execution.** v1 declares fields (`decision`, `decided_by`, `decided_at`) but does NOT spin up parallel control/treatment runs. AD-659b.
- **No automatic prompt rewriting.** Detectors propose adjustments to threshold config (`chain_tuning.low_trust_ceiling` etc.) and tier-shift hints. Prompt-text mutation is explicitly out of scope.
- **No Counselor integration.** Counselor regression-monitoring requires the apply path to exist first. AD-659c.
- **No EventType.** v1 emission is to in-memory state + REST. Live event-bus broadcast for proposals deferred to AD-659b (when apply lands and HXI needs to surface approval queues live).
- **No periodic background analyze loop.** v1 requires Captain (or test) to call `analyze()` explicitly. Scheduled analysis (every N minutes) deferred to AD-659b.
- **No de-duplication of proposals.** Re-running `analyze()` over the same window appends a fresh batch. AD-659b adds dedup keyed by `(detector_name, target_parameter)`.
- **No rollback.** Without apply, there is nothing to roll back. AD-659b.
- **No changes to AD-658 schema or `ChainExecutionTrace` dataclass.** v1 is a strict consumer of the existing chain_traces table.
- **No mutation of `ChainTuningConfig`.** v1 PROPOSES adjustments; mutating the live `runtime.config.chain_tuning.*` is the apply path (AD-659b).

## Acceptance Criteria

1. New file `src/probos/cognitive/chain_optimizer.py` exists with `OptimizationProposal` dataclass, three detector pure functions, and `ChainOptimizer` service.
2. `src/probos/config.py` has new `ChainOptimizerConfig` Pydantic class; `SystemConfig.chain_optimizer` field registered with default-disabled instance.
3. `src/probos/startup/finalize.py` has `_wire_chain_optimizer` mirroring `_wire_duty_scope_provider` shape; wirer invoked in finalize entry point.
4. New file `src/probos/routers/chain_optimizer.py` exists with `GET /api/chain-optimizer/proposals` and `POST /api/chain-optimizer/proposals/{id}/decide`.
5. `src/probos/api.py` router-registration tuples include `chain_optimizer` (in BOTH the import and the for-loop tuples).
6. `apply_proposal()` raises `NotImplementedError("v1 analysis-only; apply deferred to AD-659b")`.
7. ≥7 focused tests pass at `tests/test_ad659_chain_self_optimization.py` (target: 8).
8. Full gate `pytest tests/ -q -n 4 --dist=loadfile` passes with delta `+7` to `+8` over Wave 30 baseline (10927).
9. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
10. PROGRESS.md gets a new top entry: `AD-659 v1 CLOSED. Cognitive Chain Self-Optimization Loop — analysis only (GH issue #318). [...]`.
11. `docs/development/roadmap.md` AD-659 row flipped to ✅ v1 with explicit "analysis only" annotation; AD-659b/c forward-references added if not already present.
12. GitHub issue #318 closed via commit message footer `Closes #318`.

## Tracking

- **PROGRESS.md** — top of file: new AD-659 v1 CLOSED entry. Field set, file paths, test count, gate delta, and EXPLICIT call-out that v1 is analysis-only with apply deferred to AD-659b.
- **docs/development/roadmap.md** — flip AD-659 status to ✅ v1; add AD-659b (apply + A/B + persistence) and AD-659c (Counselor regression watchdog) as forward-references if not present.
- **DECISIONS.md** — NOT required for v1 (AD-659 design recorded under issue #318; v1 executes the analysis half of the design without architectural fork). Add a brief entry only if Builder hits an unexpected fork.

## v1 Limitations (explicitly documented for Captain)

1. Proposals are in-memory only — server restart clears the queue. Persistence is AD-659b.
2. Approving a proposal records the decision but does NOT apply it. The system continues to run on the unmutated parameters. AD-659b ships the apply path.
3. Re-running `analyze()` accumulates duplicate proposals over the same window. Dedup is AD-659b.
4. No background scheduler — `analyze()` must be triggered manually (or by AD-659b's scheduler).
5. Counselor regression monitoring is not wired. AD-659c.

These limitations are surfaced in API responses (`"applied": False`) and in the wirer log message ("analysis-only; apply path deferred to AD-659b").
