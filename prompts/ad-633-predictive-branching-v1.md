# AD-633 v1 — Predictive Cognitive Branching (Engine + Cache + Executor + Budget + Accuracy + Decision Hook)

**Closes:** GH issue #228
**HEAD:** `d85611f`
**Baseline:** 11580 → target ≥ 11615 (Δ ≥ +35)
**OSS only.** No HXI surface. No router. No new Intent. No LLM call inside the engine. No commercial content.
**Sub-ADs in scope (concrete):** AD-633a (Prediction Engine), AD-633b (Speculation Executor + Cache), AD-633c (Speculation Budget), AD-633d (Decision Pipeline Integration), AD-633e (Prediction Accuracy Tracking), AD-633h (Prediction Error event-emit).
**Sub-ADs in scope (Protocol seam only):** AD-633f (IdleSpeculationPolicy), AD-633g (PreplayHook).
**Sub-AD hard-deferred:** AD-633i (Cognitive JIT compilation — no consumer at HEAD; forcing function in module docstring).

## Problem

ProbOS crew agents are purely **reactive**. They reason only when a Ward Room event, DM, or proactive cycle trigger arrives, then start from scratch every time. The substrate to think ahead exists — `AgentWorkingMemory` (AD-573), `SubTaskExecutor` (AD-632), `HebbianRouter`, ontology, circuit breaker, EarnedAgency — but no surface combines them into "speculatively pre-compute likely sub-task chains during low-load windows and serve cached analysis when the predicted event materializes."

Three concrete gaps at HEAD `d85611f`:

1. **No prediction surface.** Nothing reads Hebbian + ward-room recency + ontology + working-memory engagement to score "how likely is this agent about to be invoked on this kind of intent?" — the inputs are public APIs, but no module aggregates them.
2. **No speculation execution path.** `SubTaskExecutor.execute()` runs operational chains; speculative chains would mix into the same token accounting, leak into operational budgets, and have no cache to serve from. There's no `runtime.speculation_executor`.
3. **No decision-pipeline cache check.** `_decide_via_llm()` always rebuilds context from scratch. Even if a cache existed, there's no hook site reading it.

GH #228 lists nine sub-ADs. Six (a, b, c, d, e, h) ship concretely. Two (f, g) ship as Protocol seams + default no-op implementations + stable dispatch entry points (Wave 81 precedent for `StandingOrderPredicate` and dream-cycle threshold tuning). One (i) is hard-deferred — its consumer (Cognitive JIT, AD-531–539) does not exist at HEAD; building a JIT-compilation-of-predictions pipeline without a JIT to consume it is unreachable code.

## Solution

One new package + one existing-module extension + finalize wirer + Pydantic config.

1. **`src/probos/cognitive/predictive_branching/`** — new package with six modules:
   - `engine.py` — `PredictionEngine.score(*, agent_id, agent_type, observation) -> PredictionDescriptor`. Pure decision; deterministic; no I/O.
   - `cache.py` — `SpeculationCache` TTL+FIFO bounded; `(agent_id, intent_type, signature)` key; emits `PREDICTION_HIT` / `PREDICTION_FLUSHED`.
   - `executor.py` — `SpeculationExecutor` wraps `runtime._sub_task_executor`; speculative chains tagged `source="speculation"`; tokens accounted to budget pool, not operational; exposes `dispatch_anticipatory(request)` for AD-633f future consumer.
   - `budget.py` — `SpeculationBudget(*, tokens_per_window, window_seconds, agency_gate)`. Per-agent rolling window; `try_reserve` / `record_consumption` / `record_outcome`. Flush-rate feedback halves budget when 1-hour rolling flush rate >30%.
   - `accuracy.py` — `AccuracyTracker` per-agent ring buffer; `record(*, agent_id, outcome)` / `get_rates(agent_id) -> AccuracyRates`.
   - `policy.py` — `IdleSpeculationPolicy` + `PreplayHook` Protocols + `NoOpIdleSpeculationPolicy` + `NoOpPreplayHook` default implementations. AD-633f / AD-633g seams.

2. **`src/probos/events.py`** — +4 EventType values.

3. **`src/probos/cognitive/cognitive_agent.py`** — pre-LLM cache check at the head of `_decide_via_llm()`. Mirrors the AD-585 ambient knowledge injection shape (lines 1428-1444).

4. **`src/probos/config.py`** — `PredictiveBranchingConfig` Pydantic model + field on `SystemConfig`. **Default-False** (operator opt-in; speculation actually consumes tokens — AD-695 default-False precedent).

5. **`src/probos/startup/finalize.py`** — `_wire_predictive_branching(*, runtime, config) -> bool`. Invocation immediately after AD-632 SubTaskExecutor wiring (depends on `runtime._sub_task_executor`).

6. **`src/probos/runtime.py`** — public typed attribute declarations.

7. **`tests/test_ad633_predictive_branching.py`** — 35 tests.

---

## Section 0 — EventTypes

### File: `src/probos/events.py`

Insert AD-633 events near the AD-581 hybrid dispatch entries (lines 315-316, end of routing-events block) — adjacent placement keeps cognitive-pipeline events together. Use a fresh comment header so future readers see the AD-633 group as one block.

```text
===MODIFY: src/probos/events.py===
===SEARCH===
    # Hybrid dispatch routing decisions (AD-581a)
    HYBRID_DISPATCH_DIRECT = "hybrid_dispatch_direct"
    HYBRID_DISPATCH_BROADCAST = "hybrid_dispatch_broadcast"
===REPLACE===
    # Hybrid dispatch routing decisions (AD-581a)
    HYBRID_DISPATCH_DIRECT = "hybrid_dispatch_direct"
    HYBRID_DISPATCH_BROADCAST = "hybrid_dispatch_broadcast"

    # Predictive cognitive branching (AD-633)
    PREDICTION_HIT = "prediction_hit"  # AD-633b cache served pre-computed analysis
    PREDICTION_MISS = "prediction_miss"  # AD-633d cache miss; fell to LLM
    PREDICTION_FLUSHED = "prediction_flushed"  # AD-633b cache entry evicted (TTL or capacity)
    PREDICTION_ERROR_RECORDED = "prediction_error_recorded"  # AD-633h prediction diverged from outcome
===END REPLACE===
```

Verification: `grep -nE "PREDICTION_(HIT|MISS|FLUSHED|ERROR_RECORDED)" src/probos/events.py` returns exactly 4 hits, all on enum lines.

---

## Section 1 — Pydantic config

### File: `src/probos/config.py`

Add `PredictiveBranchingConfig` immediately before `WorkingMemoryConfig` is referenced on `SystemConfig` (config.py:2486 is the `working_memory:` field; insertion zone is the model definition near `WorkingMemoryConfig` itself at config.py:1061). Anchor on the `WorkingMemoryConfig` class definition.

```text
===MODIFY: src/probos/config.py===
===SEARCH===
class WorkingMemoryConfig(BaseModel):
===REPLACE===
class PredictiveBranchingConfig(BaseModel):
    """AD-633 v1: Predictive Cognitive Branching.

    Default-False — speculation actually consumes tokens (separate budget pool,
    but still real LLM cost when SpeculationExecutor dispatches). Operator
    opt-in. AD-695 default-False precedent applies.
    """

    enabled: bool = False
    cache_ttl_seconds: float = Field(default=60.0, ge=1.0)
    cache_max_entries: int = Field(default=128, ge=1)
    speculation_tokens_per_window: int = Field(default=2000, ge=0)
    speculation_window_seconds: float = Field(default=300.0, ge=1.0)
    flush_rate_feedback_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    flush_rate_window_seconds: float = Field(default=3600.0, ge=1.0)
    accuracy_ring_size: int = Field(default=100, ge=10)
    cheap_tier_min_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
    standard_tier_min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    anticipatory_tier_min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)


class WorkingMemoryConfig(BaseModel):
===END REPLACE===
```

Add the field on `SystemConfig` immediately after `working_memory`:

```text
===MODIFY: src/probos/config.py===
===SEARCH===
    working_memory: WorkingMemoryConfig = WorkingMemoryConfig()
    memory_budget: MemoryBudgetConfig = MemoryBudgetConfig()  # AD-573
===REPLACE===
    working_memory: WorkingMemoryConfig = WorkingMemoryConfig()
    predictive_branching: PredictiveBranchingConfig = PredictiveBranchingConfig()  # AD-633
    memory_budget: MemoryBudgetConfig = MemoryBudgetConfig()  # AD-573
===END REPLACE===
```

Verification: `grep -n "predictive_branching\|PredictiveBranchingConfig" src/probos/config.py` returns 3 hits (class def, field, default constructor).

---

## Section 2 — Prediction Engine (AD-633a)

### File: `src/probos/cognitive/predictive_branching/__init__.py` (NEW)

```python
"""AD-633: Predictive Cognitive Branching.

Public exports for the predictive branching package. See `engine.py` for
detailed module-level docstring describing the umbrella scope.
"""

from probos.cognitive.predictive_branching.accuracy import (
    AccuracyRates,
    AccuracyTracker,
    PredictionOutcome,
)
from probos.cognitive.predictive_branching.budget import SpeculationBudget
from probos.cognitive.predictive_branching.cache import SpeculationCache
from probos.cognitive.predictive_branching.engine import (
    ConfidenceTier,
    PredictionDescriptor,
    PredictionEngine,
    compute_signature,
)
from probos.cognitive.predictive_branching.executor import (
    SpeculationExecutor,
    SpeculationRequest,
)
from probos.cognitive.predictive_branching.policy import (
    IdleSpeculationPolicy,
    NoOpIdleSpeculationPolicy,
    NoOpPreplayHook,
    PreplayHook,
)

__all__ = [
    "AccuracyRates",
    "AccuracyTracker",
    "ConfidenceTier",
    "IdleSpeculationPolicy",
    "NoOpIdleSpeculationPolicy",
    "NoOpPreplayHook",
    "PredictionDescriptor",
    "PredictionEngine",
    "PredictionOutcome",
    "PreplayHook",
    "SpeculationBudget",
    "SpeculationCache",
    "SpeculationExecutor",
    "SpeculationRequest",
    "compute_signature",
]
```

### File: `src/probos/cognitive/predictive_branching/engine.py` (NEW)

```python
"""AD-633a: Prediction Engine — deterministic confidence scoring.

Pure decision layer. Reads Hebbian weights, ward-room recent activity,
ontology department membership, and working-memory engagement to produce a
confidence score and bucketed tier. No LLM call. No I/O. No event emission.

The engine is the entry point of the AD-633 pipeline:

  PredictionEngine.score() -> PredictionDescriptor
                              \\
                               +-> SpeculationCache.lookup() (AD-633b)
                               +-> SpeculationExecutor.dispatch() (AD-633b)
                               +-> SpeculationBudget.try_reserve() (AD-633c)

AD-633i (Cognitive JIT compilation of repeated predictions into procedures)
is hard-deferred. Its consumer surface — AD-531–539's Cognitive JIT backend —
does not exist at HEAD `d85611f`. `learned_shortcuts/protocol.py:18` documents
`'cognitive_jit'` as a future identifier. Forcing function: AD-633i ships when
AD-531–539 lands a JIT consumer that subscribes to the `PREDICTION_HIT` event
stream this module already emits.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ConfidenceTier(str, Enum):
    """AD-633a: Speculation tier resolved from confidence score."""

    ZERO_COST = "zero_cost"          # Deterministic-only; do not dispatch LLM speculation
    CHEAP = "cheap"                  # Fast-tier LLM speculation
    STANDARD = "standard"            # Standard-tier LLM speculation
    ANTICIPATORY = "anticipatory"    # AD-633f reserved (idle-cycle, gated by EarnedAgency)


@dataclass(frozen=True)
class PredictionDescriptor:
    """AD-633a: Output of a prediction-engine score call."""

    agent_id: str
    agent_type: str
    intent_type: str
    confidence: float                 # [0.0, 1.0]
    tier: ConfidenceTier
    signature: str                    # Stable cache key
    computed_at: float = field(default_factory=time.time)
    components: dict[str, float] = field(default_factory=dict)  # debug breakdown
    reason: str = ""


def compute_signature(*, agent_id: str, intent_type: str, observation: dict[str, Any]) -> str:
    """AD-633a: Stable cache key for a prediction.

    Hash inputs:
      - agent_id (per-agent isolation)
      - intent_type (separate cache lanes per intent)
      - thread_id (same thread = same cache lane)
      - last_speaker_id (different speaker = different signature)

    Excluded inputs:
      - timestamp (would defeat cache hits)
      - free-form text (would defeat similar-context hits)

    Collisions across distinct semantic contexts are vanishingly rare; if
    observed in practice, AD-633a-1 expands the signature surface (e.g., adds
    `last_post_id`).
    """
    parts = [
        agent_id,
        intent_type,
        str(observation.get("thread_id", "")),
        str(observation.get("last_speaker_id", "")),
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()
    return digest[:16]


class PredictionEngine:
    """AD-633a: Deterministic confidence scoring for speculative pre-computation.

    Constructor injection only — receives runtime references and config.
    No global lookups. No event emission. Pure decision class.
    """

    # Weight allocation: components sum to 1.0
    HEBBIAN_WEIGHT = 0.4
    THREAD_ACTIVITY_WEIGHT = 0.2
    DEPARTMENT_WEIGHT = 0.2
    WORKING_MEMORY_WEIGHT = 0.2

    THREAD_ACTIVITY_WINDOW_SECONDS = 300.0   # 5 min
    THREAD_ACTIVITY_SATURATION = 5           # 5+ recent posts = 1.0

    def __init__(
        self,
        *,
        hebbian_router: Any,
        ontology: Any,
        config: Any,
        circuit_breaker: Any | None = None,
    ) -> None:
        self._hebbian = hebbian_router
        self._ontology = ontology
        self._config = config
        self._circuit_breaker = circuit_breaker

    def score(
        self,
        *,
        agent_id: str,
        agent_type: str,
        observation: dict[str, Any],
    ) -> PredictionDescriptor:
        """Score the likelihood that this agent will be invoked on this kind of intent."""
        intent_type = str(observation.get("intent", ""))

        # Hard gate: circuit breaker OPEN -> ZERO_COST regardless of confidence
        if self._circuit_breaker is not None:
            try:
                if not self._circuit_breaker.should_allow_think(agent_id):
                    sig = compute_signature(
                        agent_id=agent_id, intent_type=intent_type, observation=observation
                    )
                    return PredictionDescriptor(
                        agent_id=agent_id,
                        agent_type=agent_type,
                        intent_type=intent_type,
                        confidence=0.0,
                        tier=ConfidenceTier.ZERO_COST,
                        signature=sig,
                        components={"circuit_breaker": 0.0},
                        reason="circuit_breaker_open",
                    )
            except Exception:
                logger.warning(
                    "AD-633a: circuit_breaker check failed for %s; treating as CLOSED",
                    agent_id, exc_info=True,
                )

        components: dict[str, float] = {}

        # Component 1: Hebbian weight (source = thread origin / last_speaker_id; target = agent)
        hebbian_score = 0.0
        last_speaker = str(observation.get("last_speaker_id", ""))
        if last_speaker and self._hebbian is not None:
            try:
                hebbian_score = max(0.0, min(1.0, float(self._hebbian.get_weight(last_speaker, agent_id))))
            except Exception:
                logger.warning(
                    "AD-633a: hebbian get_weight failed (%s -> %s); using 0.0",
                    last_speaker, agent_id, exc_info=True,
                )
        components["hebbian"] = hebbian_score

        # Component 2: Recent thread activity — count posts in last 5 min that mention agent
        recent_posts = observation.get("recent_thread_posts", []) or []
        if isinstance(recent_posts, list):
            count = min(self.THREAD_ACTIVITY_SATURATION, len(recent_posts))
            thread_score = count / self.THREAD_ACTIVITY_SATURATION
        else:
            thread_score = 0.0
        components["thread_activity"] = thread_score

        # Component 3: Department membership — is observation tagged with this agent's department?
        dept_score = 0.0
        observed_dept = observation.get("department", "")
        if self._ontology is not None and observed_dept:
            try:
                agent_dept = self._ontology.get_agent_department(agent_type)
                dept_score = 1.0 if (agent_dept and agent_dept == observed_dept) else 0.0
            except Exception:
                logger.warning(
                    "AD-633a: ontology get_agent_department failed for %s; using 0.0",
                    agent_type, exc_info=True,
                )
        components["department"] = dept_score

        # Component 4: Working memory engagement match
        wm_engagements = observation.get("active_engagements", []) or []
        wm_score = 1.0 if (intent_type and intent_type in wm_engagements) else 0.0
        components["working_memory"] = wm_score

        confidence = (
            self.HEBBIAN_WEIGHT * hebbian_score
            + self.THREAD_ACTIVITY_WEIGHT * thread_score
            + self.DEPARTMENT_WEIGHT * dept_score
            + self.WORKING_MEMORY_WEIGHT * wm_score
        )
        confidence = max(0.0, min(1.0, confidence))

        tier = self._tier_for(confidence)

        signature = compute_signature(
            agent_id=agent_id, intent_type=intent_type, observation=observation
        )

        return PredictionDescriptor(
            agent_id=agent_id,
            agent_type=agent_type,
            intent_type=intent_type,
            confidence=confidence,
            tier=tier,
            signature=signature,
            components=components,
            reason="scored",
        )

    def _tier_for(self, confidence: float) -> ConfidenceTier:
        """Bucket confidence into a speculation tier."""
        cfg = self._config
        if confidence < cfg.cheap_tier_min_confidence:
            return ConfidenceTier.ZERO_COST
        if confidence < cfg.standard_tier_min_confidence:
            return ConfidenceTier.CHEAP
        if confidence < cfg.anticipatory_tier_min_confidence:
            return ConfidenceTier.STANDARD
        return ConfidenceTier.ANTICIPATORY
```

---

## Section 3 — Speculation Cache (AD-633b cache half)

### File: `src/probos/cognitive/predictive_branching/cache.py` (NEW)

```python
"""AD-633b: Speculation Cache — TTL+FIFO bounded cache for pre-computed analysis."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CacheEntry:
    signature: str
    agent_id: str
    intent_type: str
    payload: dict[str, Any]
    stored_at: float
    ttl_seconds: float

    def is_expired(self, now: float) -> bool:
        return (now - self.stored_at) >= self.ttl_seconds


class SpeculationCache:
    """AD-633b: TTL+FIFO bounded cache for speculative analysis results.

    Key: `(agent_id, intent_type, signature)` collapsed into a single string
    via the signature (which already incorporates agent_id + intent_type).
    Eviction order: TTL first, then FIFO when capacity is exceeded.
    Emits PREDICTION_HIT on lookup-hit and PREDICTION_FLUSHED on eviction.
    """

    def __init__(
        self,
        *,
        max_entries: int,
        ttl_seconds: float,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        if ttl_seconds < 1.0:
            raise ValueError("ttl_seconds must be >= 1.0")
        self._max_entries = int(max_entries)
        self._ttl = float(ttl_seconds)
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._emit = emit_event
        # Counters for AD-633e accuracy tracking introspection
        self._hits = 0
        self._misses = 0
        self._flushes = 0

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def hit_count(self) -> int:
        return self._hits

    @property
    def miss_count(self) -> int:
        return self._misses

    @property
    def flush_count(self) -> int:
        return self._flushes

    def store(
        self,
        *,
        signature: str,
        agent_id: str,
        intent_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Store a speculative result. Evicts oldest FIFO entry if at capacity."""
        now = time.time()
        # Drop expired entries opportunistically (cheap; bounded by max_entries)
        self.flush_expired()
        # FIFO eviction if still over capacity
        while len(self._entries) >= self._max_entries:
            evicted_sig, evicted = self._entries.popitem(last=False)
            self._flushes += 1
            self._emit_safe(
                "prediction_flushed",
                {
                    "signature": evicted_sig,
                    "agent_id": evicted.agent_id,
                    "intent_type": evicted.intent_type,
                    "reason": "capacity",
                },
            )
        self._entries[signature] = _CacheEntry(
            signature=signature,
            agent_id=agent_id,
            intent_type=intent_type,
            payload=payload,
            stored_at=now,
            ttl_seconds=self._ttl,
        )
        self._entries.move_to_end(signature, last=True)

    def lookup(self, signature: str) -> dict[str, Any] | None:
        """Return the cached payload or None. Hit emits PREDICTION_HIT."""
        entry = self._entries.get(signature)
        if entry is None:
            self._misses += 1
            return None
        if entry.is_expired(time.time()):
            del self._entries[signature]
            self._flushes += 1
            self._misses += 1
            self._emit_safe(
                "prediction_flushed",
                {
                    "signature": signature,
                    "agent_id": entry.agent_id,
                    "intent_type": entry.intent_type,
                    "reason": "ttl",
                },
            )
            return None
        self._hits += 1
        self._emit_safe(
            "prediction_hit",
            {
                "signature": signature,
                "agent_id": entry.agent_id,
                "intent_type": entry.intent_type,
            },
        )
        return entry.payload

    def evict(self, signature: str) -> bool:
        """Manually evict. Returns True if removed."""
        entry = self._entries.pop(signature, None)
        if entry is None:
            return False
        self._flushes += 1
        self._emit_safe(
            "prediction_flushed",
            {
                "signature": signature,
                "agent_id": entry.agent_id,
                "intent_type": entry.intent_type,
                "reason": "manual",
            },
        )
        return True

    def flush_expired(self) -> int:
        """Drop all expired entries. Returns count flushed."""
        now = time.time()
        expired = [sig for sig, e in self._entries.items() if e.is_expired(now)]
        for sig in expired:
            entry = self._entries.pop(sig)
            self._flushes += 1
            self._emit_safe(
                "prediction_flushed",
                {
                    "signature": sig,
                    "agent_id": entry.agent_id,
                    "intent_type": entry.intent_type,
                    "reason": "ttl",
                },
            )
        return len(expired)

    def _emit_safe(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._emit is None:
            return
        try:
            self._emit(event_type, payload)
        except Exception:
            logger.warning(
                "AD-633b: emit_event failed for %s; cache continues", event_type, exc_info=True
            )
```

---

## Section 4 — Speculation Executor (AD-633b executor half + AD-633h emit)

### File: `src/probos/cognitive/predictive_branching/executor.py` (NEW)

```python
"""AD-633b: Speculation Executor — wraps SubTaskExecutor with speculation accounting.

Speculative chains are tagged ``source="speculation"`` so AD-632 token
attribution can route them to the speculation budget pool. Emits
PREDICTION_ERROR_RECORDED (AD-633h) when a previously-cached prediction is
later observed to diverge from the agent's actual decision.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from probos.cognitive.predictive_branching.engine import PredictionDescriptor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SpeculationRequest:
    """AD-633b/f: Request for the executor to dispatch a speculative chain.

    Used both by the operational path (engine -> executor) and by the future
    AD-633f IdleSpeculationPolicy + AD-633g PreplayHook surfaces.
    """

    descriptor: PredictionDescriptor
    chain: Any  # SubTaskChain — Any to avoid hard import (AD-632 may be disabled)
    requested_at: float = field(default_factory=time.time)
    origin: str = "operational"  # "operational" | "anticipatory" | "preplay"


class SpeculationExecutor:
    """AD-633b: Dispatches speculative SubTaskChains and records outcomes.

    Constructor injection. ``sub_task_executor`` may be None — in that case
    ``dispatch()`` returns None and the caller falls back to operational LLM.
    """

    def __init__(
        self,
        *,
        sub_task_executor: Any,
        cache: Any,
        budget: Any,
        accuracy_tracker: Any,
        emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._executor = sub_task_executor
        self._cache = cache
        self._budget = budget
        self._accuracy = accuracy_tracker
        self._emit = emit_event

    async def dispatch(
        self,
        request: SpeculationRequest,
        *,
        context: dict[str, Any] | None = None,
        agency_level: str | None = None,
    ) -> dict[str, Any] | None:
        """Dispatch a speculative chain and store the result in the cache.

        Returns the stored payload (also written to cache) or None if dispatch
        was skipped (executor unavailable, budget exhausted, agency gate).
        Tier-2 log-and-degrade everywhere.
        """
        if self._executor is None:
            return None

        # Budget gate
        try:
            tokens_estimate = self._estimate_tokens(request.chain)
            if not self._budget.try_reserve(
                agent_id=request.descriptor.agent_id,
                tokens=tokens_estimate,
                tier=request.descriptor.tier,
                agency_level=agency_level,
            ):
                logger.debug(
                    "AD-633c: speculation budget exhausted for %s; skipping",
                    request.descriptor.agent_id,
                )
                return None
        except Exception:
            logger.warning(
                "AD-633c: budget reserve failed; skipping speculation", exc_info=True
            )
            return None

        try:
            results = await self._executor.execute(request.chain, context or {})
        except Exception:
            logger.warning(
                "AD-633b: speculative chain execute failed for %s; skipping",
                request.descriptor.agent_id, exc_info=True,
            )
            return None

        actual_tokens = self._sum_tokens(results)
        try:
            self._budget.record_consumption(
                agent_id=request.descriptor.agent_id, tokens=actual_tokens
            )
        except Exception:
            logger.warning("AD-633c: record_consumption failed", exc_info=True)

        payload = {
            "descriptor": request.descriptor,
            "results": results,
            "origin": request.origin,
            "tokens_used": actual_tokens,
        }
        try:
            self._cache.store(
                signature=request.descriptor.signature,
                agent_id=request.descriptor.agent_id,
                intent_type=request.descriptor.intent_type,
                payload=payload,
            )
        except Exception:
            logger.warning("AD-633b: cache store failed", exc_info=True)

        return payload

    async def dispatch_anticipatory(
        self, request: SpeculationRequest, *, agency_level: str | None = None
    ) -> dict[str, Any] | None:
        """AD-633f future entry point. Same semantics as ``dispatch`` with
        ``origin='anticipatory'`` already baked into the request."""
        return await self.dispatch(request, agency_level=agency_level)

    def record_outcome(
        self,
        *,
        descriptor: PredictionDescriptor,
        actual_intent: str,
        actual_decision_summary: str,
    ) -> None:
        """AD-633e/h: After the agent actually decides, compare to prediction.

        - Predicted intent matches actual intent -> ``HIT`` (already counted on lookup)
        - Predicted intent did NOT match actual intent -> ``ERROR`` and emit
          PREDICTION_ERROR_RECORDED for AD-557 (event-emit only at HEAD).
        """
        from probos.cognitive.predictive_branching.accuracy import PredictionOutcome

        try:
            if descriptor.intent_type and descriptor.intent_type == actual_intent:
                self._accuracy.record(
                    agent_id=descriptor.agent_id, outcome=PredictionOutcome.HIT
                )
                return
            self._accuracy.record(
                agent_id=descriptor.agent_id, outcome=PredictionOutcome.ERROR
            )
            if self._emit is not None:
                self._emit(
                    "prediction_error_recorded",
                    {
                        "agent_id": descriptor.agent_id,
                        "predicted_intent": descriptor.intent_type,
                        "actual_intent": actual_intent,
                        "confidence": descriptor.confidence,
                        "tier": descriptor.tier.value,
                    },
                )
        except Exception:
            logger.warning(
                "AD-633h: record_outcome failed for %s; continuing",
                descriptor.agent_id, exc_info=True,
            )

    @staticmethod
    def _estimate_tokens(chain: Any) -> int:
        """Rough estimate from prompt template lengths. Falls back to 500 on shape mismatch."""
        try:
            steps = getattr(chain, "steps", []) or []
            total = 0
            for step in steps:
                template = getattr(step, "prompt_template", "") or ""
                total += max(50, len(template) // 4)
            return max(50, total)
        except Exception:
            logger.warning(
                "AD-633b: _estimate_tokens shape mismatch on chain %r; using 500-token fallback",
                chain, exc_info=True,
            )
            return 500

    @staticmethod
    def _sum_tokens(results: Any) -> int:
        """Sum tokens_used across SubTaskResult list. Falls back to 0 on shape mismatch."""
        try:
            if not results:
                return 0
            return sum(int(getattr(r, "tokens_used", 0) or 0) for r in results)
        except Exception:
            logger.warning(
                "AD-633b: _sum_tokens shape mismatch on results; using 0-token fallback",
                exc_info=True,
            )
            return 0
```

---

## Section 5 — Speculation Budget (AD-633c)

### File: `src/probos/cognitive/predictive_branching/budget.py` (NEW)

```python
"""AD-633c: Speculation Budget — separate token pool with flush-rate feedback.

Per-agent rolling-window budget. Distinct from operational tokens (AD-617).
Standard-tier speculation requires EarnedAgency >= EXECUTING. Cheap and
ZERO_COST tiers are unrestricted by agency. Anticipatory tier is reserved
for AD-633f and defaults to gated.

Flush-rate feedback: when 1-hour rolling flush rate >= threshold (default
0.30), the agent's effective budget halves for the next window. Recovers
on the next window if flush rate drops.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass

from probos.cognitive.predictive_branching.engine import ConfidenceTier

logger = logging.getLogger(__name__)


@dataclass
class _AgentBudgetState:
    window_start: float
    tokens_consumed: int = 0
    halved: bool = False


class SpeculationBudget:
    """AD-633c: Per-agent rolling-window token budget with flush-rate feedback."""

    # Agency levels that unlock Standard-tier speculation. Lowercase strings to
    # match probos.earned_agency.AgencyLevel.value canonical form (verified at
    # src/probos/earned_agency.py:11-17 — REACTIVE/SUGGESTIVE/AUTONOMOUS/UNRESTRICTED).
    # Commander-tier and above gets Standard speculation; Lieutenants get Cheap only.
    STANDARD_TIER_AGENCY_LEVELS: frozenset[str] = frozenset({"autonomous", "unrestricted"})

    def __init__(
        self,
        *,
        tokens_per_window: int,
        window_seconds: float,
        flush_rate_threshold: float,
        flush_rate_window_seconds: float,
    ) -> None:
        if tokens_per_window < 0:
            raise ValueError("tokens_per_window must be >= 0")
        if window_seconds < 1.0:
            raise ValueError("window_seconds must be >= 1.0")
        self._tokens_per_window = int(tokens_per_window)
        self._window_seconds = float(window_seconds)
        self._flush_rate_threshold = float(flush_rate_threshold)
        self._flush_rate_window = float(flush_rate_window_seconds)
        self._states: dict[str, _AgentBudgetState] = {}
        # Per-agent outcome ring for flush-rate computation:
        # entries are (timestamp, was_flushed_or_error_bool)
        self._outcomes: dict[str, deque[tuple[float, bool]]] = {}

    def try_reserve(
        self,
        *,
        agent_id: str,
        tokens: int,
        tier: ConfidenceTier,
        agency_level: str | None = None,
    ) -> bool:
        """Attempt to reserve tokens. Returns True iff the reservation fits."""
        if tier == ConfidenceTier.ZERO_COST:
            return False  # ZERO_COST never dispatches speculation
        if tier == ConfidenceTier.ANTICIPATORY:
            # AD-633f reserved — Anticipatory speculation requires the
            # IdleSpeculationPolicy seam; v1 default-no-op never reaches here
            # via the operational path. Defensive deny.
            return False
        if tier == ConfidenceTier.STANDARD:
            if agency_level is None or agency_level.lower() not in self.STANDARD_TIER_AGENCY_LEVELS:
                return False

        now = time.time()
        state = self._states.get(agent_id)
        if state is None or (now - state.window_start) >= self._window_seconds:
            state = _AgentBudgetState(window_start=now, tokens_consumed=0)
            state.halved = self._should_halve(agent_id, now)
            self._states[agent_id] = state

        effective_budget = (
            self._tokens_per_window // 2 if state.halved else self._tokens_per_window
        )
        if state.tokens_consumed + tokens > effective_budget:
            return False
        # Reserve optimistically; record_consumption will reconcile on actual usage
        state.tokens_consumed += tokens
        return True

    def record_consumption(self, *, agent_id: str, tokens: int) -> None:
        """Reconcile actual token usage against the optimistic reservation."""
        state = self._states.get(agent_id)
        if state is None:
            return
        # If actual usage exceeded reserve, just clamp to budget — don't overflow
        effective_budget = (
            self._tokens_per_window // 2 if state.halved else self._tokens_per_window
        )
        state.tokens_consumed = min(effective_budget, max(0, int(tokens)))

    def record_outcome(self, *, agent_id: str, was_flushed: bool) -> None:
        """Record whether the most recent speculation was flushed/errored.

        ``was_flushed=True`` for FLUSHED and ERROR outcomes (both indicate
        wasted compute); ``False`` for HIT.
        """
        ring = self._outcomes.setdefault(agent_id, deque(maxlen=200))
        ring.append((time.time(), bool(was_flushed)))
        # Prune entries older than flush_rate_window
        cutoff = time.time() - self._flush_rate_window
        while ring and ring[0][0] < cutoff:
            ring.popleft()

    def get_flush_rate(self, agent_id: str) -> float:
        """1-hour rolling flush rate in [0.0, 1.0]. 0.0 if no samples."""
        ring = self._outcomes.get(agent_id)
        if not ring:
            return 0.0
        cutoff = time.time() - self._flush_rate_window
        recent = [w for ts, w in ring if ts >= cutoff]
        if not recent:
            return 0.0
        return sum(1 for w in recent if w) / len(recent)

    def get_remaining_tokens(self, agent_id: str) -> int:
        """Tokens remaining in the agent's current window."""
        state = self._states.get(agent_id)
        if state is None:
            return self._tokens_per_window
        now = time.time()
        if (now - state.window_start) >= self._window_seconds:
            return self._tokens_per_window
        effective_budget = (
            self._tokens_per_window // 2 if state.halved else self._tokens_per_window
        )
        return max(0, effective_budget - state.tokens_consumed)

    def _should_halve(self, agent_id: str, now: float) -> bool:
        """Apply flush-rate feedback to the new window."""
        return self.get_flush_rate(agent_id) >= self._flush_rate_threshold
```

---

## Section 6 — Accuracy Tracker (AD-633e)

### File: `src/probos/cognitive/predictive_branching/accuracy.py` (NEW)

```python
"""AD-633e: Prediction Accuracy Tracking — per-agent ring buffer + rates."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum


class PredictionOutcome(str, Enum):
    """AD-633e: Outcome categories for a single prediction lifecycle."""

    HIT = "hit"            # Cache served pre-computed analysis to a matching observation
    MISS = "miss"          # Cache lookup found nothing; fell to operational LLM
    FLUSHED = "flushed"    # Cache entry evicted before consumption
    ERROR = "error"        # Predicted intent differed from actual intent


@dataclass(frozen=True)
class AccuracyRates:
    """AD-633e: Per-agent accuracy snapshot."""

    hit_rate: float
    miss_rate: float
    flush_rate: float
    error_rate: float
    sample_count: int


class AccuracyTracker:
    """AD-633e: Per-agent ring buffer of recent prediction outcomes.

    Pure data structure — no event emission. Consumed by SpeculationBudget
    for flush-rate feedback and by introspection surfaces for observability.
    """

    def __init__(self, *, ring_size: int) -> None:
        if ring_size < 10:
            raise ValueError("ring_size must be >= 10")
        self._ring_size = int(ring_size)
        self._rings: dict[str, deque[PredictionOutcome]] = {}

    def record(self, *, agent_id: str, outcome: PredictionOutcome) -> None:
        ring = self._rings.setdefault(agent_id, deque(maxlen=self._ring_size))
        ring.append(outcome)

    def get_rates(self, agent_id: str) -> AccuracyRates:
        ring = self._rings.get(agent_id)
        if not ring:
            return AccuracyRates(0.0, 0.0, 0.0, 0.0, 0)
        total = len(ring)
        hits = sum(1 for o in ring if o == PredictionOutcome.HIT)
        misses = sum(1 for o in ring if o == PredictionOutcome.MISS)
        flushes = sum(1 for o in ring if o == PredictionOutcome.FLUSHED)
        errors = sum(1 for o in ring if o == PredictionOutcome.ERROR)
        return AccuracyRates(
            hit_rate=hits / total,
            miss_rate=misses / total,
            flush_rate=flushes / total,
            error_rate=errors / total,
            sample_count=total,
        )
```

---

## Section 7 — Protocol seams: IdleSpeculationPolicy + PreplayHook (AD-633f / AD-633g)

### File: `src/probos/cognitive/predictive_branching/policy.py` (NEW)

```python
"""AD-633f / AD-633g: Protocol seams for idle-cycle speculation and preplay.

Both Protocols ship with NoOp default implementations in v1. Concrete impls
follow when consumer signals arrive (see module forcing functions):

- AD-633f-1: Concrete IdleSpeculationPolicy lands once AD-633e accuracy data
  shows >= 10% hit rate from operational predictions, justifying the energy
  cost of idle-cycle speculation.
- AD-633g-1: Concrete PreplayHook + dream Step 13 wiring lands once the dream
  pipeline exposes a step registry (today only ``on_pre_dream`` /
  ``on_post_dream`` / ``on_post_micro_dream`` are extension points).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from probos.cognitive.predictive_branching.executor import SpeculationRequest


@runtime_checkable
class IdleSpeculationPolicy(Protocol):
    """AD-633f: Decides whether to dispatch anticipatory speculation during idle cycles."""

    def should_speculate_now(
        self, *, agent_id: str, runtime: Any
    ) -> SpeculationRequest | None:
        """Return a SpeculationRequest to dispatch, or None to skip this cycle."""
        ...


@runtime_checkable
class PreplayHook(Protocol):
    """AD-633g: Generates forward-simulation predictions during dream consolidation."""

    def generate_preplay_predictions(
        self, *, dream_report: Any, runtime: Any
    ) -> list[SpeculationRequest]:
        """Return a list of SpeculationRequests to dispatch as preplay rollouts."""
        ...


class NoOpIdleSpeculationPolicy:
    """AD-633f v1 default. Always returns None. Stable until AD-633f-1."""

    def should_speculate_now(
        self, *, agent_id: str, runtime: Any
    ) -> SpeculationRequest | None:
        return None


class NoOpPreplayHook:
    """AD-633g v1 default. Always returns []. Stable until AD-633g-1."""

    def generate_preplay_predictions(
        self, *, dream_report: Any, runtime: Any
    ) -> list[SpeculationRequest]:
        return []
```

---

## Section 8 — Decision pipeline integration (AD-633d)

### File: `src/probos/cognitive/cognitive_agent.py`

Insert pre-LLM cache check at the head of `_decide_via_llm()`. Tier-2 log-and-degrade — any failure proceeds to normal LLM path. This mirrors the AD-585 ambient-knowledge injection shape.

```text
===MODIFY: src/probos/cognitive/cognitive_agent.py===
===SEARCH===
    async def _decide_via_llm(self, observation: dict) -> dict:
        """AD-534b: LLM-only decision path — extracted from decide() for DRY reuse.

        Builds messages, calls LLM, records to journal.
        Returns decision dict. Does NOT check decision cache or procedural memory.
        """
        # AD-626: Load augmentation skills BEFORE building user message
        # so _build_user_message() can frame tasks with skill instructions.
        # Skip if already loaded by decide() for chain activation (AD-632f).
        if "_augmentation_skill_instructions" not in observation:
===REPLACE===
    async def _decide_via_llm(self, observation: dict) -> dict:
        """AD-534b: LLM-only decision path — extracted from decide() for DRY reuse.

        Builds messages, calls LLM, records to journal.
        Returns decision dict. Does NOT check decision cache or procedural memory.
        """
        # AD-633d: Pre-LLM speculation cache check.
        # If a SpeculationCache hit is available, prepend pre-computed analysis
        # to observation as `_speculation_prefetch`. The LLM still runs — the
        # prefetch is observation context, not a decision.
        runtime = getattr(self, "_runtime", None)
        cache = getattr(runtime, "speculation_cache", None) if runtime is not None else None
        engine = getattr(runtime, "prediction_engine", None) if runtime is not None else None
        if cache is not None and engine is not None:
            try:
                from probos.cognitive.predictive_branching.engine import compute_signature
                signature = compute_signature(
                    agent_id=self.id,
                    intent_type=str(observation.get("intent", "")),
                    observation=observation,
                )
                payload = cache.lookup(signature)
                if payload is not None:
                    observation["_speculation_prefetch"] = payload
                    tracker = getattr(runtime, "accuracy_tracker", None)
                    if tracker is not None:
                        from probos.cognitive.predictive_branching.accuracy import (
                            PredictionOutcome,
                        )
                        try:
                            tracker.record(
                                agent_id=self.id, outcome=PredictionOutcome.HIT
                            )
                        except Exception:
                            logger.warning(
                                "AD-633e: tracker.record(HIT) failed for %s",
                                self.id, exc_info=True,
                            )
                else:
                    # Miss is interesting too — track it
                    tracker = getattr(runtime, "accuracy_tracker", None)
                    if tracker is not None:
                        from probos.cognitive.predictive_branching.accuracy import (
                            PredictionOutcome,
                        )
                        try:
                            tracker.record(
                                agent_id=self.id, outcome=PredictionOutcome.MISS
                            )
                        except Exception:
                            logger.warning(
                                "AD-633e: tracker.record(MISS) failed for %s",
                                self.id, exc_info=True,
                            )
                    emit = getattr(runtime, "emit_event", None)
                    if emit is not None:
                        try:
                            emit(
                                "prediction_miss",
                                {
                                    "signature": signature,
                                    "agent_id": self.id,
                                    "intent_type": str(observation.get("intent", "")),
                                },
                            )
                        except Exception:
                            logger.warning(
                                "AD-633d: emit prediction_miss failed", exc_info=True
                            )
            except Exception:
                logger.warning(
                    "AD-633d: speculation cache check failed for %s; "
                    "proceeding with normal LLM path",
                    self.id, exc_info=True,
                )

        # AD-626: Load augmentation skills BEFORE building user message
        # so _build_user_message() can frame tasks with skill instructions.
        # Skip if already loaded by decide() for chain activation (AD-632f).
        if "_augmentation_skill_instructions" not in observation:
===END REPLACE===
```

Verification: `grep -n "_speculation_prefetch\|AD-633d" src/probos/cognitive/cognitive_agent.py` returns at least 3 hits inside `_decide_via_llm`.

---

## Section 9 — Finalize wirer + runtime attribute declarations

### File: `src/probos/runtime.py`

Add typed attribute declarations near the existing AD-557 emergence_metrics_engine block.

```text
===MODIFY: src/probos/runtime.py===
===SEARCH===
        self._emergence_metrics_engine: Any = None
===REPLACE===
        self._emergence_metrics_engine: Any = None
        # AD-633: Predictive cognitive branching (set by _wire_predictive_branching)
        self.prediction_engine: Any = None
        self.speculation_cache: Any = None
        self.speculation_executor: Any = None
        self.speculation_budget: Any = None
        self.accuracy_tracker: Any = None
===END REPLACE===
```

### File: `src/probos/startup/finalize.py`

Add the wirer immediately after `_wire_hybrid_dispatch`:

```text
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
def _wire_hybrid_dispatch(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-581 v1: Wire DepartmentDispatcher + WorkItemRouter.

    Requires ``runtime.hebbian_router``, ``runtime.ontology``,
    ``runtime.work_item_store``, AND ``runtime.dispatcher`` (AD-654c).
    Tier-2 log-and-degrade: missing any dependency -> no-op + INFO log.
    """
    cfg = getattr(config, "hybrid_dispatch", None)
    if not cfg or not cfg.enabled:
===REPLACE===
def _wire_predictive_branching(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-633 v1: Wire PredictionEngine + SpeculationCache + SpeculationExecutor
    + SpeculationBudget + AccuracyTracker.

    Requires ``runtime.hebbian_router`` AND ``runtime.ontology``. Optional:
    ``runtime._sub_task_executor`` (AD-632) — speculation cannot dispatch
    chains without it but the engine + cache still operate. Tier-2
    log-and-degrade: missing required deps -> no-op + INFO log.
    """
    cfg = getattr(config, "predictive_branching", None)
    if not cfg or not cfg.enabled:
        return False
    hebbian = getattr(runtime, "hebbian_router", None)
    if hebbian is None:
        logger.info("AD-633: hebbian_router unavailable; predictive_branching skipped")
        return False
    ontology = getattr(runtime, "ontology", None)
    if ontology is None:
        logger.info("AD-633: ontology unavailable; predictive_branching skipped")
        return False

    from probos.cognitive.predictive_branching import (
        AccuracyTracker,
        PredictionEngine,
        SpeculationBudget,
        SpeculationCache,
        SpeculationExecutor,
    )

    emit_fn = getattr(runtime, "emit_event", None)
    # AD-633a v1 deliberately does NOT integrate the AD-488 circuit breaker.
    # ProactiveCognitiveLoop's `_circuit_breaker` is a private attribute;
    # accessing it from this wirer would be a cross-module Demeter violation
    # per `.github/copilot-instructions.md`. Forcing function: AD-633a-1 ships
    # a public `ProactiveCognitiveLoop.circuit_breaker` property and re-wires
    # circuit-breaker gating into PredictionEngine.

    runtime.prediction_engine = PredictionEngine(
        hebbian_router=hebbian,
        ontology=ontology,
        config=cfg,
        circuit_breaker=None,
    )
    runtime.speculation_cache = SpeculationCache(
        max_entries=cfg.cache_max_entries,
        ttl_seconds=cfg.cache_ttl_seconds,
        emit_event=emit_fn,
    )
    runtime.speculation_budget = SpeculationBudget(
        tokens_per_window=cfg.speculation_tokens_per_window,
        window_seconds=cfg.speculation_window_seconds,
        flush_rate_threshold=cfg.flush_rate_feedback_threshold,
        flush_rate_window_seconds=cfg.flush_rate_window_seconds,
    )
    runtime.accuracy_tracker = AccuracyTracker(ring_size=cfg.accuracy_ring_size)
    runtime.speculation_executor = SpeculationExecutor(
        sub_task_executor=getattr(runtime, "_sub_task_executor", None),
        cache=runtime.speculation_cache,
        budget=runtime.speculation_budget,
        accuracy_tracker=runtime.accuracy_tracker,
        emit_event=emit_fn,
    )
    logger.info(
        "AD-633: PredictiveBranching v1 initialized "
        "(cache_max=%d, ttl=%.0fs, tokens_per_window=%d, ring=%d)",
        cfg.cache_max_entries,
        cfg.cache_ttl_seconds,
        cfg.speculation_tokens_per_window,
        cfg.accuracy_ring_size,
    )
    return True


def _wire_hybrid_dispatch(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-581 v1: Wire DepartmentDispatcher + WorkItemRouter.

    Requires ``runtime.hebbian_router``, ``runtime.ontology``,
    ``runtime.work_item_store``, AND ``runtime.dispatcher`` (AD-654c).
    Tier-2 log-and-degrade: missing any dependency -> no-op + INFO log.
    """
    cfg = getattr(config, "hybrid_dispatch", None)
    if not cfg or not cfg.enabled:
===END REPLACE===
```

Add the invocation at the boundary between the AD-632 SubTaskExecutor try/except block and the AD-594 consultation handler block. The SEARCH spans the failure-path assignment, the trailing blank line, and the AD-594 comment header — this anchor unambiguously identifies the **module-scope** insertion point (NOT the except-block scope). Critical: failing to anchor on the AD-594 boundary would put the wirer call inside the except block, where it would only fire on AD-632 wiring failure.

```text
===MODIFY: src/probos/startup/finalize.py===
===SEARCH===
        runtime._sub_task_executor = None

    # --- AD-594: Crew consultation handler wiring ---
===REPLACE===
        runtime._sub_task_executor = None

    # AD-633: Wire PredictiveBranching after SubTaskExecutor so speculation
    # can dispatch chains. Tier-2 log-and-degrade.
    try:
        _wire_predictive_branching(runtime=runtime, config=config)
    except Exception:
        logger.warning(
            "AD-633: _wire_predictive_branching raised; predictive_branching disabled",
            exc_info=True,
        )

    # --- AD-594: Crew consultation handler wiring ---
===END REPLACE===
```

Verification: `grep -n "_wire_predictive_branching" src/probos/startup/finalize.py` returns exactly 2 hits (def + invocation).

---

## Section 10 — Tests (35 total)

### File: `tests/test_ad633_predictive_branching.py` (NEW)

Test plan — 35 tests across 8 test classes. Each test isolated; no shared mutable state. Use `pytest.fixture` with explicit construction over autouse.

**Class A — `TestPredictionEngine` (8 tests)**

1. `test_engine_zero_cost_when_circuit_breaker_open` — circuit breaker `should_allow_think` returns False → tier ZERO_COST regardless of inputs.
2. `test_engine_zero_cost_when_no_signals` — empty observation, no Hebbian weight → confidence ~0.0 → ZERO_COST.
3. `test_engine_cheap_tier_at_threshold` — observation hits all components weakly so confidence in [0.30, 0.70) → CHEAP.
4. `test_engine_standard_tier_above_threshold` — strong Hebbian + dept match + WM engagement → STANDARD tier.
5. `test_engine_anticipatory_tier_at_max_confidence` — all four components at 1.0 → confidence 1.0 → ANTICIPATORY.
6. `test_engine_signature_stable_across_calls` — same agent + same intent + same thread + same speaker → identical signature.
7. `test_engine_signature_differs_per_speaker` — same observation but different `last_speaker_id` → different signature.
8. `test_engine_hebbian_failure_falls_back_to_zero` — `hebbian_router.get_weight` raises → component is 0.0, no propagation.

**Class B — `TestSpeculationCache` (7 tests)**

9. `test_cache_lookup_miss_returns_none` — empty cache returns None.
10. `test_cache_store_and_lookup_hit` — stored payload returned by lookup; emits `prediction_hit`.
11. `test_cache_ttl_expiration_flushes_on_lookup` — TTL=0.1s, sleep 0.15s, lookup returns None and emits `prediction_flushed` with reason=ttl.
12. `test_cache_capacity_eviction_fifo` — max_entries=2, store 3 → first stored is evicted with reason=capacity.
13. `test_cache_evict_existing_returns_true` — manual evict on stored signature returns True; emits `prediction_flushed` reason=manual.
14. `test_cache_evict_missing_returns_false` — manual evict on unknown signature returns False; no emit.
15. `test_cache_emit_failure_does_not_propagate` — `emit_event` raises → cache continues, lookup still works.

**Class C — `TestSpeculationBudget` (6 tests)**

16. `test_budget_zero_cost_tier_always_denied` — try_reserve with ZERO_COST returns False.
17. `test_budget_anticipatory_tier_always_denied_in_v1` — ANTICIPATORY tier returns False (AD-633f reserved).
18. `test_budget_standard_tier_requires_autonomous_agency` — STANDARD with agency=`reactive` or `suggestive` denied; with `autonomous` or `unrestricted` accepted.
19. `test_budget_cheap_tier_unrestricted_by_agency` — CHEAP with agency=None or `reactive` accepted.
20. `test_budget_window_resets_after_window_seconds` — exhaust budget; advance time past window; budget restored.
21. `test_budget_flush_rate_feedback_halves_budget` — record 10 flushed outcomes; new window starts halved.

**Class D — `TestAccuracyTracker` (4 tests)**

22. `test_accuracy_empty_returns_zero_rates` — no records → AccuracyRates(0,0,0,0,0).
23. `test_accuracy_single_hit_returns_full_hit_rate` — record 1 HIT → hit_rate=1.0, sample_count=1.
24. `test_accuracy_mixed_outcomes_compute_correctly` — record HIT, MISS, FLUSHED, ERROR → all rates 0.25.
25. `test_accuracy_ring_size_caps_history` — record ring_size+1 → oldest dropped, sample_count=ring_size.

**Class E — `TestSpeculationExecutor` (4 tests)**

26. `test_executor_no_sub_task_executor_returns_none` — sub_task_executor=None → dispatch returns None.
27. `test_executor_budget_denied_returns_none` — budget.try_reserve returns False → dispatch returns None, executor not called.
28. `test_executor_dispatch_stores_in_cache` — happy path → cache contains payload after dispatch.
29. `test_executor_record_outcome_error_emits_event` — descriptor.intent != actual_intent → AccuracyTracker.record(ERROR) + emit `prediction_error_recorded`.

**Class F — `TestPolicySeams` (3 tests)**

30. `test_noop_idle_speculation_policy_returns_none` — default policy `should_speculate_now` returns None.
31. `test_noop_preplay_hook_returns_empty_list` — default hook `generate_preplay_predictions` returns [].
32. `test_protocol_runtime_checkable` — `isinstance(NoOpIdleSpeculationPolicy(), IdleSpeculationPolicy)` is True.

**Class G — `TestConfigAndWiring` (2 tests)**

33. `test_config_defaults_disabled` — `PredictiveBranchingConfig()` has `enabled=False`; `SystemConfig().predictive_branching.enabled` is False.
34. `test_wirer_no_op_when_disabled` — finalize wirer with `enabled=False` returns False, sets no runtime attributes.

**Class H — `TestDecisionPipelineIntegration` (1 test)**

35. `test_decide_via_llm_prefetch_injection_and_hit_record` — Construct the full hook block as a unit-level test:
    - Build a `SimpleNamespace` runtime with `speculation_cache` (real `SpeculationCache` pre-populated via `.store()` for a known signature), `prediction_engine` (sentinel non-None), `accuracy_tracker` (real `AccuracyTracker`), and `emit_event = MagicMock()`.
    - Build a `SimpleNamespace` agent with `id="agent_x"` and `_runtime` set to the namespace runtime.
    - Compute a matching signature via `compute_signature(agent_id="agent_x", intent_type="foo", observation={"intent": "foo", "thread_id": "t1", "last_speaker_id": "alice"})` and pre-populate the cache under that signature.
    - Invoke the cache-check logic by calling the unit-level helper extracted from the hook (Builder may extract the block into a private `_check_speculation_cache(self, observation) -> None` method on `CognitiveAgent` to keep the test focused; if not extracted, the test exercises the full `_decide_via_llm` via mocking `_call_llm` to return `{"action": "none"}` and asserts post-conditions).
    - Assert: `observation["_speculation_prefetch"]` contains the stored payload AND `accuracy_tracker.get_rates("agent_x").hit_rate == 1.0` AND no warning logs were emitted.

---

## What This Does NOT Change (out of scope)

- AD-633i Cognitive JIT compilation (no consumer at HEAD; deferred until AD-531–539)
- ProactiveCognitiveLoop integration of IdleSpeculationPolicy (Protocol seam only; v1 ships NoOp)
- Dream adapter Step 13 wiring (Protocol seam only; v1 ships NoOp PreplayHook)
- AD-557 EmergenceMetricsEngine listener for `PREDICTION_ERROR_RECORDED` (event emit only)
- HXI surface for prediction accuracy / hit rates (no API endpoint, no UI)
- LLM-driven confidence scoring (engine is purely deterministic in v1)
- Cross-agent shared cache (per-agent only)
- Persistent cache (in-memory only)
- Speculation pre-emption when operational work arrives (executor runs to completion)
- New `runtime.sub_task_executor` public attribute (still `_sub_task_executor` private at HEAD; exposing it is a separate AD-632j candidate, not gate-blocking here)

## Tracking

- `PROGRESS.md` — append AD-633 v1 CLOSED entry under Wave 82 with concrete one-line scope.
- `docs/development/roadmap.md` — flip AD-633 status from SCOPED to v1 CLOSED for sub-ADs a/b/c/d/e/h; Protocol seam status for f/g; deferred status for i with forcing function reference.
- `DECISIONS.md` — no new architectural decision required (AD-633 + sub-ADs are pre-allocated; v1 implements within the umbrella's scope).

## Acceptance Criteria

- 35 focused tests pass (`pytest tests/test_ad633_predictive_branching.py -v -n 0`).
- Full pytest gate `pytest tests/ -q -n 4 --dist=loadfile` reports ≥ 11615 passed (Δ ≥ +35 from baseline 11580).
- Phantom-API pre-check on this prompt: 0 NEW phantoms (intra-prompt-introduction false positives excluded).
- No commercial language anywhere — no pricing, no premium-feature specs, no third-party-product positioning. AD-633 is fully OSS — there is no commercial sub-AD in this umbrella.
- All changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- GH issue #228 closes with the closure note in `WAVE-82-DISPATCH.md`'s Reframe decision section.

## Verified Against Codebase (2026-05-06, HEAD `d85611f`)

```
git rev-parse HEAD
  d85611f

# AD-573 / AD-632 / Hebbian / ontology / circuit-breaker / earned-agency substrate:
src/probos/cognitive/agent_working_memory.py:39   # @dataclass WorkingMemoryEntry
src/probos/cognitive/agent_working_memory.py:803  # def has_engagement(engagement_type=None) -> bool
src/probos/cognitive/cognitive_agent.py:163-164   # AgentWorkingMemory instance
src/probos/cognitive/cognitive_agent.py:170       # self._sub_task_executor = None (private attr)
src/probos/cognitive/cognitive_agent.py:220       # def set_sub_task_executor(executor) -> None
src/probos/cognitive/cognitive_agent.py:1410      # async def _decide_via_llm(self, observation: dict) -> dict
src/probos/cognitive/cognitive_agent.py:1428-1444 # AD-585 _knowledge_ambient injection — exact precedent shape
src/probos/cognitive/sub_task.py:29-35    # SubTaskType enum
src/probos/cognitive/sub_task.py:71       # @dataclass SubTaskChain(steps, chain_timeout_ms, fallback, source)
src/probos/cognitive/sub_task.py:174      # class SubTaskExecutor
src/probos/cognitive/sub_task.py:217      # def can_execute(chain) -> bool
src/probos/cognitive/sub_task.py:224      # async def execute(...)
src/probos/mesh/routing.py:251            # def get_weight(source, target, rel_type=None) -> float
src/probos/ontology/departments.py:65     # get_agent_department(agent_type) -> str | None
src/probos/proactive.py:540               # self._circuit_breaker.should_allow_think(agent.id)
src/probos/earned_agency.py:11-17         # AgencyLevel enum: REACTIVE/SUGGESTIVE/AUTONOMOUS/UNRESTRICTED (lowercase .value strings)
src/probos/cognitive/emergence_metrics.py:352  # class EmergenceMetricsEngine (no record_signal API — confirms event-emit-only path for AD-633h)

# Insertion / wiring anchors:
src/probos/events.py:315-316              # HYBRID_DISPATCH_DIRECT/BROADCAST — AD-633 events insert immediately after
src/probos/config.py:1061                 # class WorkingMemoryConfig — PredictiveBranchingConfig insert immediately before
src/probos/config.py:2486                 # working_memory: WorkingMemoryConfig() field — predictive_branching field insert immediately after
src/probos/runtime.py:550                 # self._emergence_metrics_engine: Any = None — typed attr declarations insert immediately after
src/probos/startup/finalize.py:762        # def _wire_hybrid_dispatch — _wire_predictive_branching insert immediately before
src/probos/startup/finalize.py:2443-2445  # SEARCH anchor spans `runtime._sub_task_executor = None` (failure-path, line 2443) + blank line + `# --- AD-594: Crew consultation handler wiring ---` boundary (line 2445). Inserting at this seam puts the wirer at MODULE SCOPE (NOT inside the AD-632 except block).

# AD-633i defer justification (consumer absent at HEAD):
src/probos/cognitive/learned_shortcuts/protocol.py:18  # 'cognitive_jit' documented as future identifier
# 0 hits for "class CognitiveJIT | runtime.cognitive_jit | cognitive_jit_compiler"
```
