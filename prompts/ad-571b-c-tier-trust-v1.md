# AD-571b + AD-571c v1 — Agent Tier Trust Separation: Operational Status + Hebbian Scope Reduction

**Status:** Draft (ready for Builder)
**Dependencies:** AD-571a (shipped — `AgentTier`, `AgentTierRegistry`, `set_tier_registry()` plumbing).
**Estimated tests:** +16 net (window [+14, +20]).
**HEAD at draft:** `4d0242a`. **Baseline:** 11463.

## Problem

Per GH issue #21 and `decisions-era-4-evolution.md:2812`, the trust infrastructure has three phases. AD-571a shipped Phase 1 (tier-aware filtering — verified in dispatch). Phase 2 (Operational Status Model) and Phase 3 (Hebbian Scope Reduction) are still planned: utility agents currently get meaningless `Rank.from_trust()` outputs, no reliability metrics, and `HebbianRouter.decay_all()` applies one rate to every relationship type while `record_interaction()` accumulates utility-utility intent-routing weight that has no social or collaborative meaning.

This prompt closes the producer side of Phase 2 and Phase 3 in one wave. The 20+ existing `Rank.from_trust()` call sites and the HXI roster surfacing are deferred to AD-571b-i and AD-571b-ii respectively (Wave-10 6+ rule + HXI fragility per `.github/copilot-instructions.md`).

## Solution

1. **`OperationalStatus` enum + `ReliabilityMetrics` dataclass + `OperationalStatusTracker`** in a new `substrate/operational_status.py`. In-memory ring buffer of recent calls per agent. Status derives from a sample window: AVAILABLE if success_rate ≥ threshold, DEGRADED if p95 latency exceeds threshold OR success_rate dipped, OFFLINE if recent error count exceeds threshold, MAINTENANCE only when explicitly set by an operator.
2. **`OperationalStatusConfig`** (Pydantic, top-level under `SystemConfig`) — sample window size, success-rate threshold, p95 latency threshold, error count threshold. All defaults; zero-config.
3. **`MeshConfig.hebbian_social_decay_rate`** new field (default `0.995` = same as `hebbian_decay_rate` so behavior is unchanged at v1; v2 forcing function flips to `0.999`).
4. **`HebbianRouter.__init__` accepts `social_decay_rate`** (default falls back to `decay_rate`).
5. **`HebbianRouter.decay_all()`** applies per-`rel_type` decay (REL_SOCIAL gets `social_decay_rate`; everything else keeps `decay_rate`).
6. **`HebbianRouter.record_interaction()`** — utility-utility prune on `REL_INTENT` only, when both endpoints' tiers are `AgentTier.UTILITY`.
7. **Runtime wiring** — `runtime.operational_status_tracker` constructed alongside `hebbian_router` at `runtime.py:304`. `startup/finalize.py` wires the tier registry into the tracker.
8. **One production call site** — `HttpFetchAgent.handle_intent()` records each fetch with latency. Proves the wiring; full sweep deferred to AD-571b-i.

## Architect calls (Decision Log)

1. **OperationalStatus lives in `substrate/`.** Mirrors `agent_tier.py` placement (`src/probos/substrate/agent_tier.py:8`). Operational health is substrate-tier; trust is consensus-tier.
2. **In-memory tracker only.** No SQLite, no ConnectionFactory wiring, no async start()/stop(). Reliability metrics are runtime-observable; persistence is AD-571b-iii if ever needed.
3. **Tracker silently no-ops for crew agents.** When `tier_registry.is_crew(agent_id) is True`, `record_call` returns immediately. Crew use Rank, not status. This prevents the dual-surface confusion.
4. **Single mandatory v1 call site: `HttpFetchAgent.handle_intent()`.** Tools fetch HTTP; latency + success are the canonical reliability signal. Twenty-call-site fan-out is AD-571b-i.
5. **`Rank.from_trust()` is NOT modified.** 20+ existing call sites (verified — `agent_onboarding.py:140,441`, `ward_room_router.py:663,807,835,910`, `proactive.py:526,1980,2011,2453`, `runtime.py:876,1033`, `ontology/service.py:552`, `cognitive_agent.py:3741,3742,3750,5115`, `commands_tool_access.py:270`). Wave-10 6+ deferral rule. No new sibling helper either — adds public API the consumers haven't asked for.
6. **`social_decay_rate` defaults to fall back to `decay_rate`.** Behavior-equivalent at v1; the dial ships, the new default doesn't. AD-571c-i forcing function: AD-557 emergence-metric benchmark before flipping the YAML.
7. **Utility-utility prune is `REL_INTENT`-only.** `REL_AGENT` (verification), `REL_BUILDER_VARIANT`, `REL_STRATEGY` are pipeline-correctness signals with legitimate utility-to-utility semantics. Per-rel_type semantic review is AD-571c-ii.
8. **CORE_INFRASTRUCTURE is exempt from the prune.** Tools-routing-to-event_log etc. are valid intent edges; only utility-pair-of-tools is noise. Prune fires only when `BOTH` endpoints are exact-`UTILITY`.
9. **Tracker wiring at `startup/finalize.py:853-862`.** Same precedent block as AD-571a wiring for trust / emergence / router. New `if hasattr(...)` block inserts after line 862.
10. **`OperationalStatusConfig` is a top-level `SystemConfig` field.** Mirrors `AgentTierConfig` placement at `config.py:2202`. Substrate concern; not nested under MeshConfig.
11. **No HXI / no router changes this wave.** AD-571b-ii forcing function: public `runtime.operational_status_tracker` surface must exist first.
12. **Commercial-leak audit: clean.** Tier discipline is core mesh hygiene, not a paid SKU.

---

## Section 1 — `config.py` additions

### Section 1.1 — `MeshConfig.hebbian_social_decay_rate`

`src/probos/config.py:125-133`:

```
===SEARCH===
class MeshConfig(BaseModel):
    """Mesh communication configuration."""

    gossip_interval_ms: int = 1000
    hebbian_decay_rate: float = 0.995
    hebbian_reward: float = 0.05
    signal_ttl_seconds: float = 30.0
    capability_broadcast_interval_seconds: float = 5.0
    semantic_matching: bool = True  # Enable semantic matching in CapabilityRegistry
===REPLACE===
class MeshConfig(BaseModel):
    """Mesh communication configuration."""

    gossip_interval_ms: int = 1000
    hebbian_decay_rate: float = 0.995
    # AD-571c v1: per-rel_type decay. SOCIAL weights persist longer than intent-routing
    # weights. Default falls back to hebbian_decay_rate so v1 is behavior-equivalent;
    # AD-571c-i forcing function flips this to 0.999 once AD-557 benchmarks land.
    hebbian_social_decay_rate: float = 0.995
    hebbian_reward: float = 0.05
    signal_ttl_seconds: float = 30.0
    capability_broadcast_interval_seconds: float = 5.0
    semantic_matching: bool = True  # Enable semantic matching in CapabilityRegistry
===END REPLACE===
```

### Section 1.2 — `OperationalStatusConfig` Pydantic class

Insert immediately after `class AgentTierConfig` at `config.py:2202-2213` (the block ends at the `core_types` line 2213).

`src/probos/config.py:2210-2215`:

```
===SEARCH===
    crew_types: list[str] = Field(default_factory=lambda: [
        "architect", "builder", "code_reviewer", "counselor",
        "diagnostician", "surgeon", "pharmacist", "pathologist",
        "red_team", "system_qa", "scout",
        "data_analyst", "systems_analyst", "research_specialist",
    ])
    core_types: list[str] = Field(default_factory=lambda: ["event_log", "vitals_monitor", "introspect"])
===REPLACE===
    crew_types: list[str] = Field(default_factory=lambda: [
        "architect", "builder", "code_reviewer", "counselor",
        "diagnostician", "surgeon", "pharmacist", "pathologist",
        "red_team", "system_qa", "scout",
        "data_analyst", "systems_analyst", "research_specialist",
    ])
    core_types: list[str] = Field(default_factory=lambda: ["event_log", "vitals_monitor", "introspect"])


class OperationalStatusConfig(BaseModel):
    """Operational status tracker configuration (AD-571b)."""

    # Number of recent calls retained per agent for rolling metrics.
    sample_window_size: int = 50
    # Minimum success rate to be considered AVAILABLE. Below this → DEGRADED.
    available_success_rate: float = 0.85
    # p95 latency (ms) above which an otherwise-healthy agent is DEGRADED.
    degraded_p95_latency_ms: float = 5000.0
    # Consecutive error count that flips an agent to OFFLINE.
    offline_consecutive_errors: int = 5
===END REPLACE===
```

### Section 1.3 — `SystemConfig.operational_status` field

The AD-571a field is named `agent_tiers` (plural) at `config.py:2429` and uses plain assignment, not `Field(default_factory=...)`. Add `operational_status` directly below it in the same style.

```
===SEARCH===
    agent_tiers: AgentTierConfig = AgentTierConfig()  # AD-571
===REPLACE===
    agent_tiers: AgentTierConfig = AgentTierConfig()  # AD-571
    operational_status: OperationalStatusConfig = OperationalStatusConfig()  # AD-571b
===END REPLACE===
```

**Hard-stop** if the SEARCH block matches more than one location — verified at HEAD as exactly one match at line 2429.

---

## Section 2 — NEW `src/probos/substrate/operational_status.py`

Create the file with this exact content:

```python
"""Operational Status Model — reliability metrics for non-crew agents (AD-571b).

Non-crew agents (utility tools, core infrastructure) do not earn Rank — they
maintain Operational Status. This module provides:
- OperationalStatus: AVAILABLE / DEGRADED / OFFLINE / MAINTENANCE.
- ReliabilityMetrics: success rate, p50/p95 latency, error count.
- OperationalStatusTracker: in-memory rolling window per agent.

The tracker is wired alongside AgentTierRegistry at startup. Crew agents are
intentional no-ops (they use Rank via TrustNetwork instead).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class OperationalStatus(StrEnum):
    """Health status for non-crew agents (AD-571b)."""

    AVAILABLE = "available"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    MAINTENANCE = "maintenance"


@dataclass(frozen=True)
class ReliabilityMetrics:
    """Rolling reliability snapshot computed from a tracker's sample window."""

    sample_count: int
    success_rate: float
    p50_latency_ms: float
    p95_latency_ms: float
    consecutive_errors: int


class OperationalStatusTracker:
    """In-memory tracker that records call outcomes for non-crew agents.

    Per-agent ring buffer of (success, latency_ms) tuples. Status is derived
    from rolling metrics and config thresholds; MAINTENANCE is sticky and only
    cleared explicitly via clear_maintenance().
    """

    def __init__(self, config: Any, tier_registry: Any | None = None) -> None:
        # Accept the OperationalStatusConfig pydantic model duck-typed via attrs.
        self._config = config
        self._tier_registry: Any = tier_registry
        # agent_id -> deque[(success: bool, latency_ms: float)]
        self._records: dict[str, deque[tuple[bool, float]]] = {}
        self._maintenance: set[str] = set()

    def set_tier_registry(self, registry: Any) -> None:
        """Late-bind the tier registry (matches AD-571a TrustNetwork pattern)."""
        self._tier_registry = registry

    def _is_crew(self, agent_id: str) -> bool:
        if self._tier_registry is None:
            return False
        try:
            return bool(self._tier_registry.is_crew(agent_id))
        except Exception:
            return False

    def record_call(self, agent_id: str, success: bool, latency_ms: float) -> None:
        """Record a single call outcome. No-op for crew agents (DLog #3)."""
        if self._is_crew(agent_id):
            return
        buf = self._records.get(agent_id)
        if buf is None:
            buf = deque(maxlen=self._config.sample_window_size)
            self._records[agent_id] = buf
        buf.append((bool(success), float(latency_ms)))

    def set_maintenance(self, agent_id: str) -> None:
        """Operator-driven MAINTENANCE flag. Sticky until cleared."""
        self._maintenance.add(agent_id)

    def clear_maintenance(self, agent_id: str) -> None:
        self._maintenance.discard(agent_id)

    def get_metrics(self, agent_id: str) -> ReliabilityMetrics | None:
        """Return rolling metrics, or None if no samples yet."""
        buf = self._records.get(agent_id)
        if not buf:
            return None
        n = len(buf)
        successes = sum(1 for s, _ in buf if s)
        latencies = sorted(lat for _, lat in buf)
        p50 = latencies[n // 2] if n > 0 else 0.0
        p95_idx = max(0, int(0.95 * n) - 1) if n > 0 else 0
        p95 = latencies[p95_idx] if n > 0 else 0.0
        # Consecutive errors counted from the most recent end of the buffer.
        consec = 0
        for s, _ in reversed(buf):
            if s:
                break
            consec += 1
        return ReliabilityMetrics(
            sample_count=n,
            success_rate=successes / n if n else 0.0,
            p50_latency_ms=p50,
            p95_latency_ms=p95,
            consecutive_errors=consec,
        )

    def get_status(self, agent_id: str) -> OperationalStatus:
        """Derive status from current metrics + config thresholds."""
        if agent_id in self._maintenance:
            return OperationalStatus.MAINTENANCE
        m = self.get_metrics(agent_id)
        if m is None or m.sample_count == 0:
            return OperationalStatus.AVAILABLE
        if m.consecutive_errors >= self._config.offline_consecutive_errors:
            return OperationalStatus.OFFLINE
        if m.success_rate < self._config.available_success_rate:
            return OperationalStatus.DEGRADED
        if m.p95_latency_ms > self._config.degraded_p95_latency_ms:
            return OperationalStatus.DEGRADED
        return OperationalStatus.AVAILABLE

    def all_statuses(self) -> dict[str, OperationalStatus]:
        """Return current status for every recorded agent."""
        ids = set(self._records) | set(self._maintenance)
        return {a: self.get_status(a) for a in sorted(ids)}
```

---

## Section 3 — `mesh/routing.py` updates

### Section 3.1 — `__init__` accepts `social_decay_rate`

`src/probos/mesh/routing.py:53-77`:

```
===SEARCH===
    def __init__(
        self,
        decay_rate: float = 0.995,
        reward: float = 0.05,
        db_path: str | Path | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.decay_rate = decay_rate
        self.reward = reward
        self.db_path = str(db_path) if db_path else None
        # Full key: (source, target, rel_type)
        self._weights: dict[_FullKey, float] = {}
        # Backward-compat view: (source, target) → weight (aggregated)
        self._compat_weights: dict[_WeightKey, float] = {}
        self._db: DatabaseConnection | None = None
        self._connection_factory = connection_factory
        self._tier_registry: Any = None
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    def set_tier_registry(self, registry: Any) -> None:
        """Inject agent tier registry for tier-aware reporting (AD-571)."""
        self._tier_registry = registry
===REPLACE===
    def __init__(
        self,
        decay_rate: float = 0.995,
        reward: float = 0.05,
        db_path: str | Path | None = None,
        connection_factory: ConnectionFactory | None = None,
        social_decay_rate: float | None = None,
    ) -> None:
        self.decay_rate = decay_rate
        # AD-571c v1: per-rel_type decay. None → fall back to decay_rate (v1 default).
        self.social_decay_rate = (
            social_decay_rate if social_decay_rate is not None else decay_rate
        )
        self.reward = reward
        self.db_path = str(db_path) if db_path else None
        # Full key: (source, target, rel_type)
        self._weights: dict[_FullKey, float] = {}
        # Backward-compat view: (source, target) → weight (aggregated)
        self._compat_weights: dict[_WeightKey, float] = {}
        self._db: DatabaseConnection | None = None
        self._connection_factory = connection_factory
        self._tier_registry: Any = None
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    def set_tier_registry(self, registry: Any) -> None:
        """Inject agent tier registry for tier-aware reporting (AD-571)."""
        self._tier_registry = registry

    def _decay_rate_for(self, rel_type: str) -> float:
        """AD-571c: route per-rel_type to the right decay rate."""
        if rel_type == REL_SOCIAL:
            return self.social_decay_rate
        return self.decay_rate
===END REPLACE===
```

### Section 3.2 — Utility-utility prune in `record_interaction()`

`src/probos/mesh/routing.py:99-126`:

```
===SEARCH===
    def record_interaction(
        self,
        source: AgentID,
        target: AgentID,
        success: bool,
        rel_type: str = REL_INTENT,
    ) -> float:
        """Update connection weight after an interaction.

        Returns the new weight.
        """
        full_key = (source, target, rel_type)
        compat_key = (source, target)
        current = self._weights.get(full_key, 0.0)

        if success:
            new_weight = current * self.decay_rate + self.reward
        else:
            new_weight = current * self.decay_rate

        # Clamp to [0.0, 1.0]
        new_weight = max(0.0, min(1.0, new_weight))
        self._weights[full_key] = new_weight
        self._compat_weights[compat_key] = new_weight
        return new_weight
===REPLACE===
    def record_interaction(
        self,
        source: AgentID,
        target: AgentID,
        success: bool,
        rel_type: str = REL_INTENT,
    ) -> float:
        """Update connection weight after an interaction.

        Returns the new weight.

        AD-571c v1: utility-utility prune for REL_INTENT only — when both
        endpoints are AgentTier.UTILITY, the edge is collaborative noise
        (tools don't form intent-routing relationships with each other).
        CORE_INFRASTRUCTURE pairs and any crew-touching edge always record.
        """
        if (
            self._tier_registry is not None
            and rel_type == REL_INTENT
            and self._is_utility_pair(source, target)
        ):
            return 0.0
        full_key = (source, target, rel_type)
        compat_key = (source, target)
        current = self._weights.get(full_key, 0.0)
        rate = self._decay_rate_for(rel_type)

        if success:
            new_weight = current * rate + self.reward
        else:
            new_weight = current * rate

        # Clamp to [0.0, 1.0]
        new_weight = max(0.0, min(1.0, new_weight))
        self._weights[full_key] = new_weight
        self._compat_weights[compat_key] = new_weight
        return new_weight

    def _is_utility_pair(self, source: AgentID, target: AgentID) -> bool:
        """AD-571c: True only when BOTH endpoints are exact-AgentTier.UTILITY."""
        from probos.substrate.agent_tier import AgentTier
        try:
            src_tier = self._tier_registry.get_tier(source)
            tgt_tier = self._tier_registry.get_tier(target)
        except Exception:
            return False
        return src_tier == AgentTier.UTILITY and tgt_tier == AgentTier.UTILITY
===END REPLACE===
```

### Section 3.3 — Per-rel_type decay in `decay_all()`

`src/probos/mesh/routing.py:188-208` (the existing `decay_all` body):

```
===SEARCH===
    def decay_all(self) -> int:
        """Apply decay to all weights. Returns count of pruned zero-weights."""
        pruned = 0
        keys_to_remove = []
        for key, weight in self._weights.items():
            new_weight = weight * self.decay_rate
            if new_weight < 0.001:
                keys_to_remove.append(key)
                pruned += 1
            else:
                self._weights[key] = new_weight
        for key in keys_to_remove:
            del self._weights[key]
        # Rebuild compat view
        self._compat_weights.clear()
        for (src, tgt, _), w in self._weights.items():
            self._compat_weights[(src, tgt)] = w
        return pruned
===REPLACE===
    def decay_all(self) -> int:
        """Apply decay to all weights. Returns count of pruned zero-weights.

        AD-571c v1: per-rel_type decay. REL_SOCIAL uses social_decay_rate
        (slow); all other rel_types use decay_rate (existing default).
        """
        pruned = 0
        keys_to_remove = []
        for key, weight in self._weights.items():
            rel_type = key[2]
            new_weight = weight * self._decay_rate_for(rel_type)
            if new_weight < 0.001:
                keys_to_remove.append(key)
                pruned += 1
            else:
                self._weights[key] = new_weight
        for key in keys_to_remove:
            del self._weights[key]
        # Rebuild compat view
        self._compat_weights.clear()
        for (src, tgt, _), w in self._weights.items():
            self._compat_weights[(src, tgt)] = w
        return pruned
===END REPLACE===
```

---

## Section 4 — `runtime.py` wiring

`src/probos/runtime.py:300-320` — pass `social_decay_rate` to `HebbianRouter()` and add `operational_status_tracker`:

```
===SEARCH===
        self.hebbian_router = HebbianRouter(
            decay_rate=self.config.mesh.hebbian_decay_rate,
            reward=self.config.mesh.hebbian_reward,
            db_path=self._data_dir / "hebbian_weights.db",
        )
        self.gossip = GossipProtocol(
            interval_seconds=self.config.mesh.gossip_interval_ms / 1000.0,
        )
===REPLACE===
        self.hebbian_router = HebbianRouter(
            decay_rate=self.config.mesh.hebbian_decay_rate,
            reward=self.config.mesh.hebbian_reward,
            db_path=self._data_dir / "hebbian_weights.db",
            social_decay_rate=self.config.mesh.hebbian_social_decay_rate,  # AD-571c
        )
        # AD-571b: operational status for non-crew agents (in-memory tracker).
        from probos.substrate.operational_status import OperationalStatusTracker
        self.operational_status_tracker = OperationalStatusTracker(
            config=self.config.operational_status,  # AD-571b: SystemConfig.operational_status (singular)
        )
        self.gossip = GossipProtocol(
            interval_seconds=self.config.mesh.gossip_interval_ms / 1000.0,
        )
===END REPLACE===
```

---

## Section 5 — `startup/finalize.py` tier-registry wiring

`src/probos/startup/finalize.py:861-865`:

```
===SEARCH===
    router = getattr(runtime, "hebbian_router", None)
    if router and hasattr(router, "set_tier_registry"):
        router.set_tier_registry(registry)

    runtime._tier_registry = registry
===REPLACE===
    router = getattr(runtime, "hebbian_router", None)
    if router and hasattr(router, "set_tier_registry"):
        router.set_tier_registry(registry)

    op_tracker = getattr(runtime, "operational_status_tracker", None)
    if op_tracker and hasattr(op_tracker, "set_tier_registry"):
        op_tracker.set_tier_registry(registry)

    runtime._tier_registry = registry
===END REPLACE===
```

---

## Section 6 — `agents/http_fetch.py` — single v1 call site

`src/probos/agents/http_fetch.py:100-125`:

```
===SEARCH===
    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report."""
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None

        plan = await self.decide(observation)
        if plan is None:
            return None

        result = await self.act(plan)
        report = await self.report(result)

        success = report.get("success", False)
        self.update_confidence(success)

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("data"),
            error=report.get("error"),
            confidence=self.confidence,
        )
===REPLACE===
    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report."""
        import time as _time
        _start = _time.monotonic()
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None

        plan = await self.decide(observation)
        if plan is None:
            return None

        result = await self.act(plan)
        report = await self.report(result)

        success = report.get("success", False)
        self.update_confidence(success)

        # AD-571b: record operational call outcome on the runtime tracker.
        # self._runtime can be None in sandbox per repo-notes; in production it
        # is the live runtime and operational_status_tracker is guaranteed by
        # runtime.py:304. Telemetry must never break a fetch (swallow tier).
        _rt = getattr(self, "_runtime", None)
        if _rt is not None:
            try:
                _latency_ms = (_time.monotonic() - _start) * 1000.0
                _rt.operational_status_tracker.record_call(self.id, bool(success), _latency_ms)
            except Exception:
                pass  # AD-571b: telemetry must never break a fetch.

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("data"),
            error=report.get("error"),
            confidence=self.confidence,
        )
===END REPLACE===
```

---

## Section 7 — NEW `tests/test_ad571bc_tier_trust.py`

Create the file with these 16 tests:

```python
"""AD-571b + AD-571c v1: Operational status + Hebbian scope reduction tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from probos.config import OperationalStatusConfig
from probos.mesh.routing import (
    HebbianRouter,
    REL_AGENT,
    REL_INTENT,
    REL_SOCIAL,
)
from probos.substrate.agent_tier import AgentTier, AgentTierRegistry
from probos.substrate.operational_status import (
    OperationalStatus,
    OperationalStatusTracker,
    ReliabilityMetrics,
)


def _registry_with(**tiers: AgentTier) -> AgentTierRegistry:
    reg = AgentTierRegistry()
    for agent_id, tier in tiers.items():
        reg.register(agent_id, tier)
    return reg


# ---------------- AD-571b: OperationalStatus / Tracker ----------------


def test_status_enum_has_four_values() -> None:
    assert {s.value for s in OperationalStatus} == {
        "available", "degraded", "offline", "maintenance",
    }


def test_tracker_no_samples_returns_available() -> None:
    tracker = OperationalStatusTracker(OperationalStatusConfig())
    assert tracker.get_status("tool-1") is OperationalStatus.AVAILABLE
    assert tracker.get_metrics("tool-1") is None


def test_tracker_records_metrics_for_utility_agent() -> None:
    cfg = OperationalStatusConfig(sample_window_size=10)
    tracker = OperationalStatusTracker(cfg)
    for _ in range(5):
        tracker.record_call("tool-1", True, latency_ms=100.0)
    m = tracker.get_metrics("tool-1")
    assert isinstance(m, ReliabilityMetrics)
    assert m.sample_count == 5
    assert m.success_rate == 1.0
    assert m.p50_latency_ms == 100.0


def test_tracker_silently_ignores_crew_agent() -> None:
    cfg = OperationalStatusConfig()
    reg = _registry_with(crew_1=AgentTier.CREW)
    tracker = OperationalStatusTracker(cfg, tier_registry=reg)
    tracker.record_call("crew_1", True, latency_ms=50.0)
    assert tracker.get_metrics("crew_1") is None  # DLog #3


def test_tracker_status_degraded_on_low_success_rate() -> None:
    cfg = OperationalStatusConfig(available_success_rate=0.85)
    tracker = OperationalStatusTracker(cfg)
    for _ in range(8):
        tracker.record_call("tool-1", True, 10.0)
    for _ in range(2):
        tracker.record_call("tool-1", False, 10.0)
    # 8/10 = 0.8 < 0.85 → DEGRADED
    assert tracker.get_status("tool-1") is OperationalStatus.DEGRADED


def test_tracker_status_degraded_on_high_p95_latency() -> None:
    cfg = OperationalStatusConfig(degraded_p95_latency_ms=500.0)
    tracker = OperationalStatusTracker(cfg)
    for _ in range(19):
        tracker.record_call("tool-1", True, 100.0)
    tracker.record_call("tool-1", True, 5000.0)  # tail latency spike
    assert tracker.get_status("tool-1") is OperationalStatus.DEGRADED


def test_tracker_status_offline_on_consecutive_errors() -> None:
    cfg = OperationalStatusConfig(offline_consecutive_errors=3)
    tracker = OperationalStatusTracker(cfg)
    tracker.record_call("tool-1", True, 10.0)
    for _ in range(3):
        tracker.record_call("tool-1", False, 10.0)
    assert tracker.get_status("tool-1") is OperationalStatus.OFFLINE


def test_tracker_maintenance_is_sticky() -> None:
    tracker = OperationalStatusTracker(OperationalStatusConfig())
    tracker.set_maintenance("tool-1")
    for _ in range(50):
        tracker.record_call("tool-1", True, 10.0)
    assert tracker.get_status("tool-1") is OperationalStatus.MAINTENANCE
    tracker.clear_maintenance("tool-1")
    assert tracker.get_status("tool-1") is OperationalStatus.AVAILABLE


def test_tracker_late_bind_tier_registry() -> None:
    tracker = OperationalStatusTracker(OperationalStatusConfig())
    tracker.record_call("crew_1", True, 10.0)  # records before registry set
    assert tracker.get_metrics("crew_1") is not None
    tracker.set_tier_registry(_registry_with(crew_1=AgentTier.CREW))
    # New calls after registry set are no-op'd.
    tracker.record_call("crew_1", True, 10.0)
    m = tracker.get_metrics("crew_1")
    assert m is not None and m.sample_count == 1


# ---------------- AD-571c: per-rel_type decay + utility-utility prune ----------------


def test_router_social_decay_rate_falls_back_to_decay_rate() -> None:
    router = HebbianRouter(decay_rate=0.9)
    assert router.social_decay_rate == 0.9


def test_router_social_decay_rate_explicit_value() -> None:
    router = HebbianRouter(decay_rate=0.9, social_decay_rate=0.999)
    assert router.social_decay_rate == 0.999


def test_decay_all_uses_per_rel_type_rate() -> None:
    router = HebbianRouter(decay_rate=0.5, social_decay_rate=0.99, reward=0.1)
    router.record_interaction("a", "b", success=True, rel_type=REL_INTENT)
    router.record_interaction("a", "b", success=True, rel_type=REL_SOCIAL)
    intent_before = router.get_weight("a", "b", rel_type=REL_INTENT)
    social_before = router.get_weight("a", "b", rel_type=REL_SOCIAL)
    router.decay_all()
    intent_after = router.get_weight("a", "b", rel_type=REL_INTENT)
    social_after = router.get_weight("a", "b", rel_type=REL_SOCIAL)
    # Intent decayed harder than social.
    assert intent_after < social_after
    assert intent_after == pytest.approx(intent_before * 0.5, rel=1e-3)
    assert social_after == pytest.approx(social_before * 0.99, rel=1e-3)


def test_utility_utility_intent_pair_is_pruned() -> None:
    reg = _registry_with(tool_a=AgentTier.UTILITY, tool_b=AgentTier.UTILITY)
    router = HebbianRouter(decay_rate=0.9, reward=0.1)
    router.set_tier_registry(reg)
    w = router.record_interaction("tool_a", "tool_b", success=True, rel_type=REL_INTENT)
    assert w == 0.0
    assert router.get_weight("tool_a", "tool_b", rel_type=REL_INTENT) == 0.0


def test_utility_utility_rel_agent_still_records() -> None:
    """REL_AGENT (verification) is NOT pruned — DLog #7."""
    reg = _registry_with(tool_a=AgentTier.UTILITY, tool_b=AgentTier.UTILITY)
    router = HebbianRouter(decay_rate=0.9, reward=0.1)
    router.set_tier_registry(reg)
    w = router.record_interaction("tool_a", "tool_b", success=True, rel_type=REL_AGENT)
    assert w > 0.0


def test_crew_to_utility_intent_records() -> None:
    reg = _registry_with(crew_1=AgentTier.CREW, tool_b=AgentTier.UTILITY)
    router = HebbianRouter(decay_rate=0.9, reward=0.1)
    router.set_tier_registry(reg)
    w = router.record_interaction("crew_1", "tool_b", success=True, rel_type=REL_INTENT)
    assert w > 0.0


def test_core_infrastructure_pair_records() -> None:
    """CORE-CORE intent pair is NOT pruned — DLog #8."""
    reg = _registry_with(
        core_a=AgentTier.CORE_INFRASTRUCTURE,
        core_b=AgentTier.CORE_INFRASTRUCTURE,
    )
    router = HebbianRouter(decay_rate=0.9, reward=0.1)
    router.set_tier_registry(reg)
    w = router.record_interaction("core_a", "core_b", success=True, rel_type=REL_INTENT)
    assert w > 0.0


# ---------------- finalize wiring (mock runtime per dispatch hard-stop) ----------------


def test_finalize_wires_tier_registry_into_tracker() -> None:
    """Section 5 wiring fires through hasattr() guard. SimpleNamespace per AD-571a precedent.

    Verified anchors at HEAD 4d0242a:
    - finalize signature: `_populate_agent_tiers(*, runtime, config)` (kw-only)
    - agent registry: `runtime.registry` (not `agent_registry`)
    - config field: `config.agent_tiers` (plural)
    """
    from probos.config import AgentTierConfig
    from probos.startup.finalize import _populate_agent_tiers

    tracker = OperationalStatusTracker(OperationalStatusConfig())

    runtime = SimpleNamespace(
        registry=SimpleNamespace(all=lambda: []),
        trust_network=None,
        emergence_metrics_engine=None,
        hebbian_router=None,
        operational_status_tracker=tracker,
    )
    config = SimpleNamespace(agent_tiers=AgentTierConfig())
    _populate_agent_tiers(runtime=runtime, config=config)
    assert tracker._tier_registry is runtime._tier_registry  # type: ignore[attr-defined]
```

Builder note on the last test: SimpleNamespace mirrors the AD-571a `test_startup_population` fixture pattern at `tests/test_ad571_tier_separation.py`. **Do not boot a real `ProbOSRuntime`** — hard-stop per dispatch rule 9.

---

## What This Does NOT Change

1. `src/probos/crew_profile.py` — `Rank.from_trust()` is untouched. AD-571b-i is the call-site sweep.
2. `src/probos/consensus/trust.py` — AD-571a already shipped here. No changes.
3. `src/probos/cognitive/emergence_metrics.py` — already crew-only filtered by AD-571a.
4. Any HXI / `ui/` / `routers/` file. AD-571b-ii is the surfacing AD.
5. `OperationalStatus` is **not** persisted to SQLite (DLog #2). Tracker state is regenerable from event_log if needed.
6. The `OperationalStatusTracker` is an in-memory object on the runtime; no `start()/stop()` lifecycle.
7. `MeshConfig.hebbian_social_decay_rate` defaults to the existing `0.995` so v1 is behavior-equivalent (DLog #6). AD-571c-i flips this default.
8. `REL_AGENT`, `REL_BUILDER_VARIANT`, `REL_STRATEGY` records continue to flow utility-to-utility (DLog #7).
9. No new SQLite schema, ConnectionFactory, or async wiring for the tracker.
10. No call sites of `Rank.from_trust()` are migrated to the tracker (AD-571b-i scope).

## Tracking

- `PROGRESS.md` — append CLOSED paragraph for AD-571b v1 + AD-571c v1.
- `docs/development/roadmap.md` — flip AD-571 entry status as detailed in dispatch step 10.
- `prompts/wave-plan.yaml` (id 74) — `status: done`.
- GH issue #21 — close with summary table (a shipped / b v1 / c v1 / b-i b-ii c-i c-ii deferred).

## Acceptance criteria

1. Full gate passes at 11479 ± 2 (target +16; window [11477, 11483]).
2. All seven sections applied byte-for-byte.
3. 16 new tests pass.
4. No file outside the named set is modified.
5. Build report cites the test count delta + 10 "what this does NOT change" verifications.
6. Build report explicitly cites four deferred children (AD-571b-i, AD-571b-ii, AD-571c-i, AD-571c-ii) with forcing functions.
7. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-05, HEAD `4d0242a`)

```
grep -n "class AgentTier" src/probos/substrate/agent_tier.py
  8:class AgentTier(StrEnum):
  16:class AgentTierRegistry:
  (DLog #1 substrate placement; DLog #3 registry has is_crew())

grep -n "AgentTierConfig" src/probos/config.py
  2202:class AgentTierConfig(BaseModel):
  2429:    agent_tiers: AgentTierConfig = AgentTierConfig()  # AD-571
  (Section 1.2 anchor at 2202; Section 1.3 anchor at 2429 — note PLURAL `agent_tiers`
   and plain assignment, not Field(default_factory=...). Verified exactly one match at 2429.)

grep -n "hebbian_decay_rate" src/probos/config.py
  129:    hebbian_decay_rate: float = 0.995
  (Section 1.1 anchor.)

grep -n "self.hebbian_router = HebbianRouter(" src/probos/runtime.py
  304:        self.hebbian_router = HebbianRouter(
  (Section 4 anchor.)

grep -n "REL_INTENT\|REL_SOCIAL\|REL_AGENT" src/probos/mesh/routing.py
  28:REL_INTENT = "intent"
  29:REL_AGENT = "agent"
  30:REL_SOCIAL = "social"
  (Section 3.x and tests reference these constants.)

grep -n "def __init__" src/probos/mesh/routing.py
  53:    def __init__(
  (Section 3.1 anchor.)

grep -n "def record_interaction" src/probos/mesh/routing.py
  99:    def record_interaction(
  (Section 3.2 anchor.)

grep -n "def decay_all" src/probos/mesh/routing.py
  188:    def decay_all(self) -> int:
  (Section 3.3 anchor.)

grep -n "set_tier_registry" src/probos/startup/finalize.py
  853:    if trust and hasattr(trust, "set_tier_registry"):
  857:    if emergence and hasattr(emergence, "set_tier_registry"):
  861:    if router and hasattr(router, "set_tier_registry"):
  (Section 5 anchor — tracker block inserts after line 862.)

grep -n "def _populate_agent_tiers" src/probos/startup/finalize.py
  828:def _populate_agent_tiers(*, runtime: Any, config: "SystemConfig") -> int:
  (KW-only signature; agent registry read as `runtime.registry`; config read as
   `config.agent_tiers.crew_types/core_types`. Section 7 finalize test must match.)

grep -n "async def handle_intent" src/probos/agents/http_fetch.py
  100:    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
  (Section 6 anchor.)

grep -n "return IntentResult(" src/probos/agents/http_fetch.py
  116:        return IntentResult(
  (Section 6 — telemetry inserts immediately above this return.)

grep -n "def from_trust" src/probos/crew_profile.py
  38:    def from_trust(cls, trust_score: float) -> "Rank":
  (DLog #5 — NOT modified this wave.)

grep -rn "Rank.from_trust" src/probos/ tests/ | wc -l
  20+ call sites (verified)
  (Wave-10 6+ deferral rule justifies AD-571b-i.)

grep -n "class OperationalStatus" src/probos/
  (No matches at HEAD — DLog #2 confirms substrate/operational_status.py is NEW.)

grep -n "operational_status_tracker" src/probos/
  (No matches at HEAD — runtime attribute is NEW; Section 4 introduces it.)

grep -n "social_decay_rate\|hebbian_social_decay_rate" src/probos/
  (No matches at HEAD — Section 1.1 + Section 3.1 introduce both names.)

grep -n "test_ad571" tests/
  test_ad571_tier_separation.py (15 tests, AD-571a — must remain green after Section 3.x.)
```
