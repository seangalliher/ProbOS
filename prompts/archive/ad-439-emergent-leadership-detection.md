# AD-439: Emergent Leadership Detection

**Status:** Ready for builder
**Dependencies:** None (AD-429 ontology and AD-571a `is_crew` filtering already landed)
**Estimated tests:** ~10
**Risk:** Low–Medium — analytics-only feature; reads existing Hebbian weights and ontology, emits one new EventType. No source-of-truth mutations.

---

## Problem

The ontology (`config/ontology/organization.yaml` + `src/probos/ontology/service.py`) defines a designed chain of command via `authority_over` (verified at `organization.yaml:28,38,80`). Hebbian routing (`src/probos/mesh/routing.py`) records actual influence patterns through agent-to-agent weight reinforcement (verified at `routing.py:39 class HebbianRouter`, with a public `get_agent_weights()` and `all_weights()` API at lines 180 and 237).

ProbOS has no service that compares the **designed structure** with the **emergent influence graph**. When agents naturally defer to someone other than their designated superior — measurable via Hebbian weights from subordinates to a non-superior post — the divergence is invisible. Captain has no signal that role miscasting or emergent talent is occurring.

## Solution Overview

Add `EmergentLeadershipDetector` as a read-only analytics service that:

1. Builds the **designed superior map** from `VesselOntologyService` (each agent → its `reports_to` ontology post).
2. Builds the **emergent influence map** from `HebbianRouter.all_weights(crew_only=True)` — for each subordinate, identify the highest-weight peer it actually defers to.
3. Compares the two; emits `EventType.LEADERSHIP_DIVERGENCE` when an agent's strongest influence target is consistently NOT its designated superior over a configurable confidence threshold.
4. Exposes `/api/emergent-leadership` with the divergence report for HXI consumption.

The detector runs on demand (called from a periodic cycle or HXI request); it does not own a background task in this AD. No mutation of ontology, trust, or Hebbian weights.

---

## Section 0: Event Types

Add to `src/probos/events.py` in the analytics/diagnostic block (near `WRONG_CONVERGENCE_DETECTED` at line 163):

```
LEADERSHIP_DIVERGENCE = "leadership_divergence"  # AD-439
```

Single new value. No collision check required — verified absent via `grep -n "LEADERSHIP" src/probos/events.py` (no matches).

---

## Section 1.5: Add public `get_agents_for_post` passthrough on `VesselOntologyService`

**File:** `src/probos/ontology/service.py`

`VesselOntologyService` already exposes ~10 public delegating wrappers (`get_post`, `get_chain_of_command`, `get_subordinate_agent_types`, etc. at lines 120–151). Add `get_agents_for_post` to keep AD-439's detector module free of `_dept` private-attr access:

SEARCH:
```python
    def get_subordinate_agent_types(self, agent_type: str) -> list[str]:
```

REPLACE:
```python
    def get_agents_for_post(self, post_id: str) -> list[Assignment]:
        """AD-439: Public passthrough — agents currently filling a post."""
        return self._dept.get_agents_for_post(post_id)  # type: ignore[union-attr]

    def get_subordinate_agent_types(self, agent_type: str) -> list[str]:
```

This is a single 3-line addition matching the existing delegation pattern. `DepartmentService.get_agents_for_post(post_id)` exists at `departments.py:117`.

## Section 1: Create `EmergentLeadershipDetector`

**File:** `src/probos/cognitive/emergent_leadership.py` (new)

```python
"""AD-439: Emergent Leadership Detection.

Read-only analytics that compares the designed chain of command (ontology)
with the emergent influence graph (Hebbian weights). Surfaces divergences
where an agent's strongest peer-influence target is NOT its designated
superior. Captain-facing diagnostic; no mutations.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from probos.events import EventType

if TYPE_CHECKING:
    from probos.mesh.routing import HebbianRouter
    from probos.ontology.service import VesselOntologyService
    from probos.substrate.registry import AgentRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LeadershipDivergence:
    """One subordinate-vs-superior mismatch."""

    agent_id: str
    agent_type: str
    designed_superior_post: str  # ontology post_id (e.g., "chief_engineer")
    emergent_target_id: str       # agent_id with highest Hebbian weight
    emergent_weight: float
    designed_weight: float
    detected_at: float


@dataclass(frozen=True)
class LeadershipReport:
    """Full divergence snapshot."""

    generated_at: float
    divergences: list[LeadershipDivergence]
    sample_size: int   # number of crew agents analyzed
    skipped: int       # number skipped (no superior, no weights, etc.)


class EmergentLeadershipDetector:
    """Compare designed authority_over hierarchy against Hebbian influence.

    Stateless on construction. Each `analyze()` call produces a fresh
    `LeadershipReport`. Caller is responsible for scheduling.
    """

    def __init__(
        self,
        *,
        ontology: VesselOntologyService,
        hebbian: HebbianRouter,
        registry: AgentRegistry,
        emit_event: Any | None = None,
        min_weight: float = 0.10,
        min_ratio: float = 1.5,
    ) -> None:
        self._ontology = ontology
        self._hebbian = hebbian
        self._registry = registry
        self._emit_event = emit_event
        self._min_weight = min_weight
        self._min_ratio = min_ratio

    def analyze(self) -> LeadershipReport:
        """Produce a divergence report. Does not mutate any source."""
        agents = list(self._registry.all())
        divergences: list[LeadershipDivergence] = []
        skipped = 0
        sample = 0
        now = time.time()

        for agent in agents:
            if not getattr(agent, "is_alive", True):
                skipped += 1
                continue
            agent_type = getattr(agent, "agent_type", "")
            agent_id = getattr(agent, "id", "")
            if not agent_type or not agent_id:
                skipped += 1
                continue

            assignment = self._ontology.get_assignment_for_agent(agent_type)
            if not assignment:
                skipped += 1
                continue
            post = self._ontology.get_post(assignment.post_id)
            if not post or not post.reports_to:
                skipped += 1
                continue

            weights = self._hebbian.get_agent_weights(agent_id)
            if not weights:
                skipped += 1
                continue

            target_id, target_weight = max(weights.items(), key=lambda kv: kv[1])
            if target_weight < self._min_weight:
                skipped += 1
                continue

            superior_assignments = self._superior_agent_ids(post.reports_to)
            designed_weight = max(
                (weights.get(sid, 0.0) for sid in superior_assignments),
                default=0.0,
            )

            if target_id in superior_assignments:
                sample += 1
                continue

            if designed_weight > 0 and target_weight < designed_weight * self._min_ratio:
                sample += 1
                continue

            divergences.append(LeadershipDivergence(
                agent_id=agent_id,
                agent_type=agent_type,
                designed_superior_post=post.reports_to,
                emergent_target_id=target_id,
                emergent_weight=target_weight,
                designed_weight=designed_weight,
                detected_at=now,
            ))
            sample += 1

            if self._emit_event:
                try:
                    self._emit_event(
                        EventType.LEADERSHIP_DIVERGENCE,
                        {
                            "agent_id": agent_id,
                            "agent_type": agent_type,
                            "designed_superior_post": post.reports_to,
                            "emergent_target_id": target_id,
                            "emergent_weight": target_weight,
                            "designed_weight": designed_weight,
                        },
                    )
                except Exception:
                    logger.warning(
                        "AD-439: emit failed for %s; divergence still recorded",
                        agent_id,
                        exc_info=True,
                    )

        report = LeadershipReport(
            generated_at=now,
            divergences=divergences,
            sample_size=sample,
            skipped=skipped,
        )
        if divergences:
            logger.info(
                "AD-439: %d leadership divergences in %d sampled agents",
                len(divergences), sample,
            )
        return report

    def _superior_agent_ids(self, superior_post_id: str) -> set[str]:
        """All agent_ids currently filling the superior post."""
        try:
            assignments = self._ontology.get_agents_for_post(superior_post_id)
        except Exception:
            return set()
        result: set[str] = set()
        for a in assignments:
            sup_agent_type = a.agent_type
            for agent in self._registry.all():
                if getattr(agent, "agent_type", "") == sup_agent_type:
                    result.add(getattr(agent, "id", ""))
        return result - {""}
```

> Builder note: `get_agents_for_post` is added as a public passthrough on `VesselOntologyService` in Section 1.5 above. AD-439's detector module never reaches into `_dept` directly.

---

## Section 2: Add `LEADERSHIP_DIVERGENCE` event type

**File:** `src/probos/events.py`

SEARCH (around line 163):
```python
    WRONG_CONVERGENCE_DETECTED = "wrong_convergence_detected"  # AD-583
    WARD_ROOM_ECHO_DETECTED = "ward_room_echo_detected"  # AD-583g
```

REPLACE:
```python
    WRONG_CONVERGENCE_DETECTED = "wrong_convergence_detected"  # AD-583
    LEADERSHIP_DIVERGENCE = "leadership_divergence"  # AD-439
    WARD_ROOM_ECHO_DETECTED = "ward_room_echo_detected"  # AD-583g
```

---

## Section 3: Add `EmergentLeadershipConfig`

**File:** `src/probos/config.py`

Place near `EmergenceMetricsConfig` (search for `class EmergenceMetricsConfig` to find the correct neighborhood):

```python
class EmergentLeadershipConfig(BaseModel):
    """Emergent leadership detection configuration (AD-439)."""

    enabled: bool = True
    min_weight: float = 0.10
    min_ratio: float = 1.5
```

Wire into `SystemConfig`:

SEARCH:
```python
    emergence_metrics: EmergenceMetricsConfig = EmergenceMetricsConfig()
```

REPLACE:
```python
    emergence_metrics: EmergenceMetricsConfig = EmergenceMetricsConfig()
    emergent_leadership: EmergentLeadershipConfig = EmergentLeadershipConfig()  # AD-439
```

---

## Section 4: Wire into startup

**File:** `src/probos/startup/finalize.py`

Place the wiring next to the existing risk-registry block (verified at `finalize.py:297`). Guard for `runtime.ontology is None` since `ontology: VesselOntologyService | None`:

```python
    # AD-439: Emergent Leadership Detector
    if config.emergent_leadership.enabled and runtime.ontology is not None:
        from probos.cognitive.emergent_leadership import EmergentLeadershipDetector
        detector = EmergentLeadershipDetector(
            ontology=runtime.ontology,
            hebbian=runtime.hebbian_router,
            registry=runtime.registry,
            emit_event=runtime.emit_event,
            min_weight=config.emergent_leadership.min_weight,
            min_ratio=config.emergent_leadership.min_ratio,
        )
        runtime.emergent_leadership_detector = detector
        logger.info("AD-439: EmergentLeadershipDetector wired")
```

> Verify-first: `runtime.hebbian_router` is the public attribute on `ProbOSRuntime` at `runtime.py:180,304`. `runtime.ontology` is public at `runtime.py:218,454`. `runtime.registry` is public at `runtime.py:293`. `runtime.emit_event(event_type, data)` is the post-AD-680 public method at `runtime.py:771`. The runtime attribute `emergent_leadership_detector` is published as a public name (no leading underscore) per the AD-680 / Wave 5 review precedent.

---

## Section 5: REST endpoint

**File:** `src/probos/routers/emergent_leadership.py` (new)

```python
"""AD-439: Emergent leadership analytics endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.routers.deps import get_runtime

router = APIRouter(prefix="/api/emergent-leadership", tags=["analytics"])


@router.get("")
async def get_emergent_leadership(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Return the latest emergent-leadership divergence report."""
    detector = getattr(runtime, "emergent_leadership_detector", None)
    if detector is None:
        raise HTTPException(404, "Emergent leadership detection disabled")
    report = detector.analyze()
    return {
        "generated_at": report.generated_at,
        "sample_size": report.sample_size,
        "skipped": report.skipped,
        "divergences": [
            {
                "agent_id": d.agent_id,
                "agent_type": d.agent_type,
                "designed_superior_post": d.designed_superior_post,
                "emergent_target_id": d.emergent_target_id,
                "emergent_weight": d.emergent_weight,
                "designed_weight": d.designed_weight,
                "detected_at": d.detected_at,
            }
            for d in report.divergences
        ],
    }
```

Wire in `src/probos/routers/__init__.py` (or wherever existing analytics routers are registered — match `routers/task_router.py` for AD-438 if present).

---

## Tests

**File:** `tests/test_ad439_emergent_leadership.py`

10 tests, pytest + pytest-asyncio. Use `_FakeOntology`, `_FakeHebbian`, `_FakeRegistry` stubs with `_make_mock_runtime` style.

1. `test_event_type_leadership_divergence_exists` — `EventType.LEADERSHIP_DIVERGENCE.value == "leadership_divergence"`.
2. `test_config_defaults` — `EmergentLeadershipConfig().enabled is True`, `min_weight == 0.10`, `min_ratio == 1.5`.
3. `test_analyze_no_agents_returns_empty_report` — empty registry → `divergences == []`, `sample_size == 0`, `skipped == 0`.
4. `test_analyze_aligned_chain_no_divergence` — agent's max-weight target IS its superior → `divergences == []`, `sample_size == 1`.
5. `test_analyze_divergent_chain_emits_event` — agent's max-weight target is a peer, not its superior, with weight ≥ `min_ratio × designed_weight` → one divergence + emit called once with `EventType.LEADERSHIP_DIVERGENCE`.
6. `test_analyze_below_min_weight_skipped` — max weight 0.05 with `min_weight=0.10` → skipped, no divergence.
7. `test_analyze_no_reports_to_skipped` — agent's post has `reports_to=None` → skipped.
8. `test_analyze_no_assignment_skipped` — agent_type not in ontology assignments → skipped.
9. `test_analyze_emit_failure_logs_and_continues` — `emit_event` raises → divergence still recorded; warning logged via `caplog` at WARNING level.
10. `test_endpoint_returns_404_when_disabled` — `emergent_leadership_detector` absent on runtime → 404.

Naming follows `test_{method}_{scenario}_{expected}`. Each test creates its own fixtures via `tmp_path` where needed; no shared state.

---

## What This Does NOT Change

- Hebbian weights are not mutated. AD-439 is read-only.
- Ontology is not mutated.
- Trust scores are not affected. Divergences are diagnostic, not punitive.
- No background asyncio task in this AD. Caller schedules `analyze()`.
- No proactive context injection. AD-439 surfaces divergences via event log + REST only.
- No HXI panel. Future AD may add one.

---

## Tracking

- `PROGRESS.md`: add `AD-439 CLOSED. Emergent Leadership Detection — ...`
- `docs/development/roadmap.md`: flip AD-439 status from `*(planned)*` to `*(complete)*` at line ~4083.
- `DECISIONS.md`: no entry required (architecture is straightforward analytics — single class, event, config, route).

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any single tracker file (`PROGRESS.md`, `roadmap.md`, `DECISIONS.md`) shows >200 deletions, STOP. Tracker files are append-mostly.

Expected delta:
- `src/probos/cognitive/emergent_leadership.py`: ~210 lines added (new file).
- `src/probos/events.py`: 1 line added.
- `src/probos/config.py`: ~10 lines added.
- `src/probos/startup/finalize.py`: ~12 lines added.
- `src/probos/routers/emergent_leadership.py`: ~40 lines added (new file).
- `tests/test_ad439_emergent_leadership.py`: ~250 lines added (new file).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed total.

---

## Acceptance Criteria

- All 10 tests pass under `pytest tests/test_ad439_emergent_leadership.py -v -n 0`.
- Full parallel gate `pytest tests/ -q -n 8 --dist=loadfile` is non-decreasing vs baseline.
- `/api/emergent-leadership` returns 200 with a report when enabled, 404 when disabled.
- New `EventType.LEADERSHIP_DIVERGENCE` is in `events.py` exactly once at the documented insertion point.
- `EmergentLeadershipDetector` is wired only when `config.emergent_leadership.enabled` is True.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-04-30, updated 2026-05-01)

```
grep -n "class HebbianRouter" src/probos/mesh/routing.py
  39: class HebbianRouter:

grep -n "def get_agent_weights" src/probos/mesh/routing.py
  180:    def get_agent_weights(self, agent_id: AgentID) -> dict[AgentID, float]:

grep -n "def all_weights" src/probos/mesh/routing.py
  237:    def all_weights(self, crew_only: bool = False) -> dict[tuple[AgentID, AgentID], float]:

grep -n "class VesselOntologyService" src/probos/ontology/service.py
  45: class VesselOntologyService:

grep -n "def get_assignment_for_agent" src/probos/ontology/service.py
  153:    def get_assignment_for_agent(self, agent_type: str) -> Assignment | None:

grep -n "def get_subordinate_agent_types" src/probos/ontology/service.py
  174:    def get_subordinate_agent_types(self, agent_type: str) -> list[str]:

grep -n "def get_agents_for_post" src/probos/ontology/departments.py
  117:    def get_agents_for_post(self, post_id: str) -> list[Assignment]:

grep -n "authority_over" src/probos/ontology/service.py
  177:        Uses authority_over from ontology to find subordinate posts,
  187:        if not post or not post.authority_over:
  190:        for sub_post_id in post.authority_over:

grep -n "reports_to" config/ontology/organization.yaml
  27:    reports_to: null
  38:    reports_to: captain
  56:    reports_to: captain

grep -n "from probos.routers" src/probos/routers/system.py
  14: from probos.routers.deps import get_runtime, get_task_tracker
  (deps module — no leading underscore)

grep -rn "LEADERSHIP\|LEADERSHIP_DIVERGENCE" src/probos/events.py
  (no matches — name is free)

grep -n "WRONG_CONVERGENCE_DETECTED" src/probos/events.py
  163:    WRONG_CONVERGENCE_DETECTED = "wrong_convergence_detected"  # AD-583

grep -n "if config.risk_tiers.enabled" src/probos/startup/finalize.py
  297:    if config.risk_tiers.enabled:

grep -n "emergence_metrics: EmergenceMetricsConfig" src/probos/config.py
  1544:    emergence_metrics: EmergenceMetricsConfig = EmergenceMetricsConfig()

grep -n "def emit_event" src/probos/runtime.py
  771:    def emit_event(self, event: BaseEvent | EventType | str, ...

grep -n "self.hebbian_router\|self.ontology\|self.registry" src/probos/runtime.py
  180:    hebbian_router: HebbianRouter
  218:    ontology: VesselOntologyService | None
  293:        self.registry = AgentRegistry()
  304:        self.hebbian_router = HebbianRouter(
  454:        self.ontology: VesselOntologyService | None = None
```

---

## Revision (2026-05-01)

Applied review findings from `prompts/Reviews/ad-439-emergent-leadership-detection-review.md`:

- **Required #1 (`routers._deps` phantom):** Section 5 import path corrected to `probos.routers.deps` (no underscore). Verified via `routers/system.py:14` and 20+ other routers using the canonical path.
- **Required #2 (Demeter on `_dept`):** Added Section 1.5 — public `get_agents_for_post(post_id)` passthrough on `VesselOntologyService`. The detector's `_superior_agent_ids` now calls `self._ontology.get_agents_for_post(...)` cleanly. No private-attribute access across module boundaries.
- **Required #3 (verify-first for `emit_event` signature):** Verified Against Codebase footer now includes `def emit_event` line at `runtime.py:771`.
- **Recommended R1 (`runtime.ontology is None` guard):** Section 4 wiring now guards on `runtime.ontology is not None`.
- **Recommended R2 (test signature):** Test 5's docstring should reflect the positional-arg shape; Builder applies during test write.
- **Recommended R3 (perf):** noted as future optimization; non-blocking for v1.
- **Recommended R4 (slots):** deferred — codebase precedent does not require slots.
- **Nits:** stateless-on-construction docstring left as-is; "read-only on shared state" is a clearer rephrasing the Builder may apply if desired.
- **Demeter uplift (cross-cutting Wave 5):** runtime attribute `emergent_leadership_detector` is published WITHOUT leading underscore. Section 4 wiring sets `runtime.emergent_leadership_detector = detector` (public name). Section 5 endpoint reads via `getattr(runtime, "emergent_leadership_detector", None)`. Test 10 updated to match.
