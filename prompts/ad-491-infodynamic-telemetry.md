# AD-491: Infodynamic Telemetry — Information Entropy Instrumentation

**Status:** Ready for builder
**Dependencies:** None hard. Distinct from `cognitive/emergence_metrics.py` (verified at `emergence_metrics.py:182,279,352` — that is PID/synergy decomposition, AD-557). AD-491 measures Vopson-style information entropy over time as a distinct observability surface.
**Estimated tests:** ~10
**Risk:** Low — pure observability. No mutations, no consensus paths, no agent changes. Smallest of the Wave 6 batch.

---

## Problem

ProbOS already has emergence metrics (`src/probos/cognitive/emergence_metrics.py:352 EmergenceMetricsEngine` + `compute_pid` at line 182) — Partial Information Decomposition over Ward Room threads. That measures **agent collaboration** (synergy / redundancy / unique).

A separate research question is: does ProbOS as a whole exhibit decreasing information entropy over time, consistent with Vopson's Second Law of Infodynamics (Vopson 2023)? Vopson's law predicts organized systems trend toward lower information entropy. Emergence metrics cannot answer this — they measure within-cycle collaboration, not whole-system entropy trajectory.

`grep -rn "infodynamic\|InfodynamicTelemetry\|VopsonEntropy" src/probos/` returns no matches.

What is needed:

1. **`InfodynamicProbe`** — a small, periodic computation that samples whole-system signals (event-log entropy over a window, trust-network distribution entropy, agent-state distribution entropy) and writes a single `InfodynamicReport`.
2. **`/api/infodynamic`** — REST endpoint returning the latest report.
3. **`EventType.INFODYNAMIC_REPORT`** — emitted on each probe cycle.

This is **observability only.** AD-491 does NOT decompose collaboration (that's AD-557 emergence metrics), does NOT measure individual agent traits (that's AD-569 behavioral metrics), does NOT mutate any state.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
```

One new value. Verified absent via `grep -n "INFODYNAMIC" src/probos/events.py` (no matches).

---

## Section 1: `InfodynamicProbe` and `InfodynamicReport`

**File:** `src/probos/cognitive/infodynamic.py` (new)

> Verify-first: the prompt's wave-5-8 plan suggested `src/probos/telemetry/infodynamic.py`. Substrate already has `src/probos/substrate/telemetry.py` (verified). Placing AD-491 at `src/probos/cognitive/infodynamic.py` instead — it consumes runtime cognitive state (event log, trust, agents) and is a cognitive-layer concern, not a substrate primitive. Document the choice in DECISIONS.md.

```python
"""AD-491: Infodynamic Telemetry — Information Entropy Instrumentation.

Periodic whole-system entropy measurement. Distinct from AD-557
emergence metrics (PID over Ward Room threads) — AD-491 measures
cross-system entropy trajectory consistent with Vopson 2023's Second
Law of Infodynamics.

Pure observability. No mutations. Reads runtime.event_log,
runtime.trust_network, runtime.registry; writes one report per cycle.
"""

from __future__ import annotations

import logging
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntropySignal:
    """One entropy measurement over a named distribution."""

    name: str
    entropy: float    # Shannon entropy in bits
    sample_size: int
    bucket_count: int


@dataclass(frozen=True)
class InfodynamicReport:
    """One probe-cycle entropy snapshot."""

    generated_at: float
    signals: list[EntropySignal] = field(default_factory=list)
    total_entropy_bits: float = 0.0


def _shannon_entropy(counts: list[int]) -> float:
    """Shannon entropy in bits over a list of bucket counts."""
    total = sum(counts)
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            h -= p * math.log2(p)
    return h


class InfodynamicProbe:
    """Periodic entropy measurement over runtime state.

    Stateless on construction. Each `analyze()` call produces a fresh
    `InfodynamicReport`. Caller is responsible for scheduling.

    Default signals:
      - event_log_category — Shannon entropy over event categories in a
        recent window.
      - trust_score_distribution — entropy over quantized trust scores.
      - agent_state_distribution — entropy over agent state values.
    """

    DEFAULT_TRUST_BUCKETS = 10

    def __init__(
        self,
        *,
        runtime: Any,
        emit_event: Any | None = None,
        event_window_seconds: float = 3600.0,
        trust_buckets: int = DEFAULT_TRUST_BUCKETS,
    ) -> None:
        self._runtime = runtime
        self._emit_event = emit_event
        self._event_window = event_window_seconds
        self._trust_buckets = trust_buckets

    async def analyze(self) -> InfodynamicReport:
        """Compute one entropy snapshot. Does not mutate any source."""
        signals: list[EntropySignal] = []
        signals.append(await self._event_log_entropy())
        signals.append(self._trust_distribution_entropy())
        signals.append(self._agent_state_entropy())
        report = InfodynamicReport(
            generated_at=time.time(),
            signals=signals,
            total_entropy_bits=sum(s.entropy for s in signals),
        )
        self._emit(report)
        return report

    async def _event_log_entropy(self) -> EntropySignal:
        rt = self._runtime
        log = getattr(rt, "event_log", None) if rt else None
        if log is None:
            return EntropySignal(
                name="event_log_category",
                entropy=0.0, sample_size=0, bucket_count=0,
            )
        try:
            # AD-491: EventLog.query() does NOT accept `since=` (verified at
            # event_log.py:132 — signature is category/agent_id/limit only).
            # We pull the latest 10K rows and post-filter by timestamp.
            events = await log.query(limit=10_000)
        except Exception:
            logger.debug("AD-491: event_log query failed; entropy=0", exc_info=True)
            return EntropySignal(
                name="event_log_category",
                entropy=0.0, sample_size=0, bucket_count=0,
            )
        cutoff = time.time() - self._event_window
        windowed = [e for e in events if float(e.get("timestamp", 0) or 0) >= cutoff]
        categories = Counter(e.get("category", "") for e in windowed)
        h = _shannon_entropy(list(categories.values()))
        return EntropySignal(
            name="event_log_category",
            entropy=h,
            sample_size=sum(categories.values()),
            bucket_count=len(categories),
        )

    def _trust_distribution_entropy(self) -> EntropySignal:
        rt = self._runtime
        net = getattr(rt, "trust_network", None) if rt else None
        if net is None:
            return EntropySignal(
                name="trust_score_distribution",
                entropy=0.0, sample_size=0, bucket_count=0,
            )
        scores: list[float] = []
        registry = getattr(rt, "registry", None)
        if registry is None:
            return EntropySignal(
                name="trust_score_distribution",
                entropy=0.0, sample_size=0, bucket_count=0,
            )
        for agent in registry.all():
            try:
                s = net.get_score(getattr(agent, "id", ""))
                if isinstance(s, (int, float)):
                    scores.append(float(s))
            except Exception:
                continue
        if not scores:
            return EntropySignal(
                name="trust_score_distribution",
                entropy=0.0, sample_size=0, bucket_count=0,
            )
        bucket_counts = [0] * self._trust_buckets
        for s in scores:
            # Defensive clamp to [0, 1] in case a future trust subclass returns
            # a different range (current TrustNetwork.get_score returns Beta mean ∈ [0,1]).
            s = max(0.0, min(1.0, s))
            idx = min(self._trust_buckets - 1, int(s * self._trust_buckets))
            bucket_counts[idx] += 1
        h = _shannon_entropy(bucket_counts)
        return EntropySignal(
            name="trust_score_distribution",
            entropy=h,
            sample_size=len(scores),
            bucket_count=sum(1 for c in bucket_counts if c > 0),
        )

    def _agent_state_entropy(self) -> EntropySignal:
        rt = self._runtime
        registry = getattr(rt, "registry", None) if rt else None
        if registry is None:
            return EntropySignal(
                name="agent_state_distribution",
                entropy=0.0, sample_size=0, bucket_count=0,
            )
        states = Counter()
        for agent in registry.all():
            state = getattr(agent, "state", None)
            # AD-491: AgentState is an enum; use .value to match the canonical
            # wire format used elsewhere (e.g., substrate/agent.py:166).
            states[state.value if state is not None and hasattr(state, "value") else "unknown"] += 1
        h = _shannon_entropy(list(states.values()))
        return EntropySignal(
            name="agent_state_distribution",
            entropy=h,
            sample_size=sum(states.values()),
            bucket_count=len(states),
        )

    def _emit(self, report: InfodynamicReport) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.INFODYNAMIC_REPORT,
                {
                    "generated_at": report.generated_at,
                    "total_entropy_bits": report.total_entropy_bits,
                    "signals": [
                        {
                            "name": s.name,
                            "entropy": s.entropy,
                            "sample_size": s.sample_size,
                            "bucket_count": s.bucket_count,
                        }
                        for s in report.signals
                    ],
                },
            )
        except Exception:
            logger.warning("AD-491: INFODYNAMIC_REPORT emit failed", exc_info=True)
```

---

## Section 2: Add EventType

**File:** `src/probos/events.py`

SEARCH:
```python
    SERVICE_TIER_RESTORED = "service_tier_restored"  # AD-459
```

REPLACE:
```python
    SERVICE_TIER_RESTORED = "service_tier_restored"  # AD-459
    INFODYNAMIC_REPORT = "infodynamic_report"  # AD-491
```

> Builder note: this assumes AD-459 lands first. If not, anchor on `AGENT_SELF_NAMED = "agent_self_named"  # AD-499` (line 190).

---

## Section 3: Add `InfodynamicConfig`

**File:** `src/probos/config.py`

```python
class InfodynamicConfig(BaseModel):
    """Infodynamic telemetry configuration (AD-491)."""

    enabled: bool = True
    event_window_seconds: float = Field(default=3600.0, ge=60.0)
    trust_buckets: int = Field(default=10, ge=2, le=100)
```

Wire into `SystemConfig`:

SEARCH:
```python
    degradation: DegradationConfig = DegradationConfig()  # AD-459
```

REPLACE:
```python
    degradation: DegradationConfig = DegradationConfig()  # AD-459
    infodynamic: InfodynamicConfig = InfodynamicConfig()  # AD-491
```

> Builder note: anchor depends on AD-459 landing. If not, anchor on `pre_flight: PreFlightConfig = PreFlightConfig()  # AD-458` instead.

---

## Section 4: Wire into startup

**File:** `src/probos/startup/finalize.py`

```python
    # AD-491: Infodynamic Telemetry probe
    if config.infodynamic.enabled:
        from probos.cognitive.infodynamic import InfodynamicProbe
        runtime.infodynamic_probe = InfodynamicProbe(
            runtime=runtime,
            emit_event=runtime.emit_event,
            event_window_seconds=config.infodynamic.event_window_seconds,
            trust_buckets=config.infodynamic.trust_buckets,
        )
        logger.info("AD-491: InfodynamicProbe wired")
```

> Verify-first: `runtime.infodynamic_probe` is published as a public attribute (no underscore) per Wave 5 retrospective convention.

---

## Section 5: REST endpoint

**File:** `src/probos/routers/infodynamic.py` (new)

```python
"""AD-491: Infodynamic telemetry endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.routers.deps import get_runtime

router = APIRouter(prefix="/api/infodynamic", tags=["analytics"])


@router.get("")
async def get_infodynamic(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Return the latest infodynamic entropy snapshot."""
    probe = getattr(runtime, "infodynamic_probe", None)
    if probe is None:
        raise HTTPException(404, "Infodynamic probe disabled")
    report = await probe.analyze()
    return {
        "generated_at": report.generated_at,
        "total_entropy_bits": report.total_entropy_bits,
        "signals": [
            {
                "name": s.name,
                "entropy": s.entropy,
                "sample_size": s.sample_size,
                "bucket_count": s.bucket_count,
            }
            for s in report.signals
        ],
    }
```

Wire in `src/probos/api.py` router-registration block (verified at `api.py:192–204`):

SEARCH:
```python
        recreation, memory_graph, bills, emergent_leadership, orders,
    )
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
    ):
```

REPLACE:
```python
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic,
    )
    for r in (
        ontology, system, wardroom, wardroom_admin, records, identity,
        agents, journal, skills, acm, assignments, scheduled_tasks,
        workforce, build, design, chat, counselor, procedures, gaps,
        recreation, memory_graph, bills, emergent_leadership, orders,
        infodynamic,
    ):
```

---

## Tests

**File:** `tests/test_ad491_infodynamic.py`

10 tests using `_FakeRuntime` stubs:

1. `test_event_type_infodynamic_report_exists` — `EventType.INFODYNAMIC_REPORT.value == "infodynamic_report"`.
2. `test_infodynamic_config_defaults` — defaults match documented values.
3. `test_shannon_entropy_uniform_distribution` — `_shannon_entropy([10, 10])` == 1.0.
4. `test_shannon_entropy_zero_for_empty` — `_shannon_entropy([])` == 0.0.
5. `test_shannon_entropy_zero_for_single_bucket` — `_shannon_entropy([10])` == 0.0.
6. `test_analyze_no_runtime_returns_empty_signals` — `runtime=None` → all signals have entropy=0.
7. `test_analyze_event_log_entropy_uses_query` — fake event log returns events; signal computes entropy correctly.
8. `test_analyze_trust_distribution_buckets` — fake trust network with diverse scores → non-zero entropy.
9. `test_analyze_emits_event` — emit fires once with `INFODYNAMIC_REPORT` containing all signal data.
10. `test_endpoint_returns_404_when_disabled` — `infodynamic_probe` absent → 404.

---

## What This Does NOT Change

- `cognitive/emergence_metrics.py` is untouched. AD-557 PID decomposition is a different observability surface (within-thread collaboration vs whole-system trajectory).
- No mutations of trust, ontology, event log, or agent state.
- No background asyncio task — caller schedules `analyze()`.
- No HXI panel.
- The Vopson Second Law claim is **not** asserted by AD-491. The probe records entropy over time; whether it decreases is an empirical question the data answers.

---

## Tracking

- `PROGRESS.md`: add `AD-491 CLOSED. Infodynamic Telemetry — ...`
- `docs/development/roadmap.md`: flip AD-491 status from `*(planned, OSS)*` to `*(complete)*` near line 5995.
- `DECISIONS.md`: optional entry recording the placement choice (`cognitive/infodynamic.py` vs `telemetry/infodynamic.py`) and the orthogonality with AD-557.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/cognitive/infodynamic.py`: ~210 lines (new).
- `src/probos/events.py`: 1 line added.
- `src/probos/config.py`: ~8 lines added.
- `src/probos/startup/finalize.py`: ~12 lines added.
- `src/probos/routers/infodynamic.py`: ~35 lines (new).
- `src/probos/api.py`: ~3 lines changed (router registration).
- `tests/test_ad491_infodynamic.py`: ~210 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 10 tests pass under `pytest tests/test_ad491_infodynamic.py -v -n 0`.
- Full parallel gate non-decreasing.
- 1 new EventType in `events.py`.
- `runtime.infodynamic_probe` published as public attribute.
- `/api/infodynamic` returns 200 with snapshot when enabled, 404 when disabled.
- `cognitive/emergence_metrics.py` is unchanged (no overlap with AD-557).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-01)

```
ls src/probos/cognitive/infodynamic.py
  (does NOT exist — AD-491 creates it)

grep -n "class EmergenceMetricsEngine\|def compute_pid" src/probos/cognitive/emergence_metrics.py
  182: def compute_pid(
  279: def compute_complementarity(
  352: class EmergenceMetricsEngine:
  (AD-557 PID — distinct surface)

grep -n "class .*Telemetry" src/probos/substrate/telemetry.py
  (substrate primitive; AD-491 lives in cognitive/, reads runtime cognitive state)

grep -rn "infodynamic\|InfodynamicTelemetry\|VopsonEntropy" src/probos/
  (no matches — AD-491 introduces these names)

grep -n "INFODYNAMIC" src/probos/events.py
  (no matches — name is free)

grep -n "AGENT_SELF_NAMED" src/probos/events.py
  190:    AGENT_SELF_NAMED = "agent_self_named"  # AD-499

grep -n "include_router(r.router)" src/probos/api.py
  204:        app.include_router(r.router)

grep -n "async def query" src/probos/substrate/event_log.py
  132: async def query(
       (signature: category, agent_id, limit — no `since` parameter; AD-491
        post-filters by timestamp in Python after pulling 10K rows)

grep -n "AgentState\|self.state" src/probos/substrate/agent.py
  43:    self.state = AgentState.SPAWNING
  166:    "state": self.state.value
       (canonical wire format uses state.value, not str(state))

grep -n "def get_score" src/probos/consensus/trust.py
  397: def get_score(self, agent_id: AgentID) -> float:
       (returns Beta(alpha,beta) mean ∈ [0,1]; AD-491 clamps defensively)
```

---

## Revision (2026-05-01)

Applied review findings from `prompts/Reviews/ad-491-infodynamic-telemetry-review.md`.

**Required addressed:**

- **R#1: phantom `since=` kwarg dropped.** `EventLog.query()` accepts only `category, agent_id, limit` (verified at `event_log.py:132`). `_event_log_entropy()` now pulls `limit=10_000` and post-filters by timestamp in Python. Behavior matches the documented event-window semantic without expanding substrate API.

**Recommended addressed:**

- **rec#3: defensive clamp on trust score.** Added `s = max(0.0, min(1.0, s))` before bucket-index calculation. Survives future trust subclasses that may return out-of-range values.
- **rec#4: `state.value` not `str(state)`.** `_agent_state_entropy()` now reads `state.value` (matches `substrate/agent.py:166` canonical wire format). Falls back to `"unknown"` if state lacks `.value`.

**Recommended deferred:**

- rec#1 (line range cosmetic) — harmless drift, not actioned.
- rec#2 (Section 5 trailing-comma) — already correct in prompt body.

**Nits applied:**

- nit#1 (DECISIONS.md placement entry) — promoted from "optional" to "recommended"; added note in Tracking section that future architects evaluating cognitive-vs-substrate-vs-telemetry layer choice should look at the AD-491 placement decision.

**Nits deferred:** nit#3 (field order), nit#2 (cross-prompt context) — cosmetic.

**Verified Against Codebase footer extended:** added `EventLog.query()` signature grep, `AgentState.value` grep, `TrustNetwork.get_score` grep — proves no phantom APIs remain after revision.

**Wave-5 conventions audit (post-revision):** all 6 applied. ✅

**No-theater discipline (cross-cutting fix #1):** N/A — AD-491 is read-only observability; every signal does real work today.
