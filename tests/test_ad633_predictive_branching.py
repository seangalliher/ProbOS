"""AD-633 v1: Predictive Cognitive Branching — 35 focused tests.

Test classes:
  A. TestPredictionEngine          — 8 tests (engine.py)
  B. TestSpeculationCache          — 7 tests (cache.py)
  C. TestSpeculationBudget         — 6 tests (budget.py)
  D. TestAccuracyTracker           — 4 tests (accuracy.py)
  E. TestSpeculationExecutor       — 4 tests (executor.py)
  F. TestPolicySeams               — 3 tests (policy.py)
  G. TestConfigAndWiring           — 2 tests (config.py + finalize.py)
  H. TestDecisionPipelineIntegration — 1 test (cognitive_agent.py hook)
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.predictive_branching import (
    AccuracyRates,
    AccuracyTracker,
    ConfidenceTier,
    IdleSpeculationPolicy,
    NoOpIdleSpeculationPolicy,
    NoOpPreplayHook,
    PredictionDescriptor,
    PredictionEngine,
    PredictionOutcome,
    SpeculationBudget,
    SpeculationCache,
    SpeculationExecutor,
    SpeculationRequest,
    compute_signature,
)
from probos.config import PredictiveBranchingConfig, SystemConfig


# --- Helpers -----------------------------------------------------------------


class _StubHebbian:
    def __init__(self, weights: dict[tuple[str, str], float] | None = None) -> None:
        self._w = weights or {}

    def get_weight(self, source: str, target: str, rel_type: Any = None) -> float:
        return self._w.get((source, target), 0.0)


class _RaisingHebbian:
    def get_weight(self, source: str, target: str, rel_type: Any = None) -> float:
        raise RuntimeError("hebbian boom")


class _StubOntology:
    def __init__(self, dept_for: dict[str, str] | None = None) -> None:
        self._d = dept_for or {}

    def get_agent_department(self, agent_type: str) -> str | None:
        return self._d.get(agent_type)


class _StubCircuitBreaker:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow

    def should_allow_think(self, agent_id: str) -> bool:
        return self.allow


def _cfg(**overrides: Any) -> PredictiveBranchingConfig:
    return PredictiveBranchingConfig(**overrides)


# =============================================================================
# Class A — TestPredictionEngine (8 tests)
# =============================================================================


class TestPredictionEngine:
    def test_engine_zero_cost_when_circuit_breaker_open(self) -> None:
        engine = PredictionEngine(
            hebbian_router=_StubHebbian({("alice", "bob"): 1.0}),
            ontology=_StubOntology({"agent_type_x": "engineering"}),
            config=_cfg(),
            circuit_breaker=_StubCircuitBreaker(allow=False),
        )
        descriptor = engine.score(
            agent_id="bob",
            agent_type="agent_type_x",
            observation={
                "intent": "foo",
                "last_speaker_id": "alice",
                "department": "engineering",
                "active_engagements": ["foo"],
                "recent_thread_posts": [1, 2, 3, 4, 5],
            },
        )
        assert descriptor.tier == ConfidenceTier.ZERO_COST
        assert descriptor.confidence == 0.0
        assert descriptor.reason == "circuit_breaker_open"

    def test_engine_zero_cost_when_no_signals(self) -> None:
        engine = PredictionEngine(
            hebbian_router=_StubHebbian(),
            ontology=_StubOntology(),
            config=_cfg(),
        )
        descriptor = engine.score(
            agent_id="bob", agent_type="agent_x", observation={"intent": "foo"}
        )
        assert descriptor.tier == ConfidenceTier.ZERO_COST
        assert descriptor.confidence == 0.0

    def test_engine_cheap_tier_at_threshold(self) -> None:
        # Confidence in [0.30, 0.70). Department alone = 0.2 weight; thread_activity=1.0*0.2=0.2; total=0.4
        engine = PredictionEngine(
            hebbian_router=_StubHebbian(),
            ontology=_StubOntology({"agent_x": "engineering"}),
            config=_cfg(),
        )
        descriptor = engine.score(
            agent_id="bob",
            agent_type="agent_x",
            observation={
                "intent": "foo",
                "department": "engineering",
                "recent_thread_posts": [1, 2, 3, 4, 5],
            },
        )
        assert 0.30 <= descriptor.confidence < 0.70
        assert descriptor.tier == ConfidenceTier.CHEAP

    def test_engine_standard_tier_above_threshold(self) -> None:
        # Hebbian 1.0*0.4 + thread 1.0*0.2 + dept 1.0*0.2 = 0.8 → STANDARD (>=0.70, <0.85)
        engine = PredictionEngine(
            hebbian_router=_StubHebbian({("alice", "bob"): 1.0}),
            ontology=_StubOntology({"agent_x": "engineering"}),
            config=_cfg(),
        )
        descriptor = engine.score(
            agent_id="bob",
            agent_type="agent_x",
            observation={
                "intent": "foo",
                "last_speaker_id": "alice",
                "department": "engineering",
                "recent_thread_posts": [1, 2, 3, 4, 5],
            },
        )
        assert descriptor.tier == ConfidenceTier.STANDARD
        assert 0.70 <= descriptor.confidence < 0.85

    def test_engine_anticipatory_tier_at_max_confidence(self) -> None:
        engine = PredictionEngine(
            hebbian_router=_StubHebbian({("alice", "bob"): 1.0}),
            ontology=_StubOntology({"agent_x": "engineering"}),
            config=_cfg(),
        )
        descriptor = engine.score(
            agent_id="bob",
            agent_type="agent_x",
            observation={
                "intent": "foo",
                "last_speaker_id": "alice",
                "department": "engineering",
                "recent_thread_posts": [1, 2, 3, 4, 5],
                "active_engagements": ["foo"],
            },
        )
        assert descriptor.confidence == pytest.approx(1.0)
        assert descriptor.tier == ConfidenceTier.ANTICIPATORY

    def test_engine_signature_stable_across_calls(self) -> None:
        obs = {"intent": "foo", "thread_id": "t1", "last_speaker_id": "alice"}
        sig1 = compute_signature(agent_id="bob", intent_type="foo", observation=obs)
        sig2 = compute_signature(agent_id="bob", intent_type="foo", observation=obs)
        assert sig1 == sig2

    def test_engine_signature_differs_per_speaker(self) -> None:
        obs1 = {"thread_id": "t1", "last_speaker_id": "alice"}
        obs2 = {"thread_id": "t1", "last_speaker_id": "carol"}
        sig1 = compute_signature(agent_id="bob", intent_type="foo", observation=obs1)
        sig2 = compute_signature(agent_id="bob", intent_type="foo", observation=obs2)
        assert sig1 != sig2

    def test_engine_hebbian_failure_falls_back_to_zero(self) -> None:
        engine = PredictionEngine(
            hebbian_router=_RaisingHebbian(),
            ontology=_StubOntology(),
            config=_cfg(),
        )
        descriptor = engine.score(
            agent_id="bob",
            agent_type="agent_x",
            observation={"intent": "foo", "last_speaker_id": "alice"},
        )
        assert descriptor.components["hebbian"] == 0.0
        # Without other signals, confidence is 0 → ZERO_COST
        assert descriptor.tier == ConfidenceTier.ZERO_COST


# =============================================================================
# Class B — TestSpeculationCache (7 tests)
# =============================================================================


class TestSpeculationCache:
    def test_cache_lookup_miss_returns_none(self) -> None:
        cache = SpeculationCache(max_entries=4, ttl_seconds=60.0)
        assert cache.lookup("nope") is None
        assert cache.miss_count == 1

    def test_cache_store_and_lookup_hit(self) -> None:
        events: list[tuple[str, dict]] = []
        cache = SpeculationCache(
            max_entries=4,
            ttl_seconds=60.0,
            emit_event=lambda et, p: events.append((et, p)),
        )
        cache.store(signature="sig1", agent_id="a1", intent_type="foo", payload={"x": 1})
        result = cache.lookup("sig1")
        assert result == {"x": 1}
        assert any(et == "prediction_hit" for et, _ in events)

    def test_cache_ttl_expiration_flushes_on_lookup(self) -> None:
        events: list[tuple[str, dict]] = []
        cache = SpeculationCache(
            max_entries=4,
            ttl_seconds=1.0,
            emit_event=lambda et, p: events.append((et, p)),
        )
        # Store with a backdated timestamp by manipulating the entry directly
        cache.store(signature="sig1", agent_id="a1", intent_type="foo", payload={"x": 1})
        # Force expiration: rewrite entry with old timestamp via private internals
        # (the test owns the cache so this is acceptable for verification).
        entry = cache._entries["sig1"]
        cache._entries["sig1"] = entry.__class__(
            signature=entry.signature,
            agent_id=entry.agent_id,
            intent_type=entry.intent_type,
            payload=entry.payload,
            stored_at=entry.stored_at - 10.0,
            ttl_seconds=entry.ttl_seconds,
        )
        result = cache.lookup("sig1")
        assert result is None
        assert any(
            et == "prediction_flushed" and p.get("reason") == "ttl"
            for et, p in events
        )

    def test_cache_capacity_eviction_fifo(self) -> None:
        events: list[tuple[str, dict]] = []
        cache = SpeculationCache(
            max_entries=2,
            ttl_seconds=60.0,
            emit_event=lambda et, p: events.append((et, p)),
        )
        cache.store(signature="s1", agent_id="a", intent_type="i", payload={"v": 1})
        cache.store(signature="s2", agent_id="a", intent_type="i", payload={"v": 2})
        cache.store(signature="s3", agent_id="a", intent_type="i", payload={"v": 3})
        assert cache.lookup("s1") is None  # evicted
        assert cache.lookup("s2") == {"v": 2}
        assert cache.lookup("s3") == {"v": 3}
        assert any(
            et == "prediction_flushed" and p.get("reason") == "capacity"
            for et, p in events
        )

    def test_cache_evict_existing_returns_true(self) -> None:
        events: list[tuple[str, dict]] = []
        cache = SpeculationCache(
            max_entries=4,
            ttl_seconds=60.0,
            emit_event=lambda et, p: events.append((et, p)),
        )
        cache.store(signature="s1", agent_id="a", intent_type="i", payload={"v": 1})
        assert cache.evict("s1") is True
        assert any(
            et == "prediction_flushed" and p.get("reason") == "manual"
            for et, p in events
        )

    def test_cache_evict_missing_returns_false(self) -> None:
        events: list[tuple[str, dict]] = []
        cache = SpeculationCache(
            max_entries=4,
            ttl_seconds=60.0,
            emit_event=lambda et, p: events.append((et, p)),
        )
        assert cache.evict("nope") is False
        assert events == []

    def test_cache_emit_failure_does_not_propagate(self) -> None:
        def boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("emit boom")

        cache = SpeculationCache(max_entries=4, ttl_seconds=60.0, emit_event=boom)
        # store and lookup should not raise even though emit raises
        cache.store(signature="s1", agent_id="a", intent_type="i", payload={"v": 1})
        assert cache.lookup("s1") == {"v": 1}


# =============================================================================
# Class C — TestSpeculationBudget (6 tests)
# =============================================================================


class TestSpeculationBudget:
    def _budget(self, **overrides: Any) -> SpeculationBudget:
        kwargs = {
            "tokens_per_window": 1000,
            "window_seconds": 300.0,
            "flush_rate_threshold": 0.30,
            "flush_rate_window_seconds": 3600.0,
        }
        kwargs.update(overrides)
        return SpeculationBudget(**kwargs)  # type: ignore[arg-type]

    def test_budget_zero_cost_tier_always_denied(self) -> None:
        b = self._budget()
        assert (
            b.try_reserve(agent_id="a", tokens=10, tier=ConfidenceTier.ZERO_COST)
            is False
        )

    def test_budget_anticipatory_tier_always_denied_in_v1(self) -> None:
        b = self._budget()
        assert (
            b.try_reserve(
                agent_id="a",
                tokens=10,
                tier=ConfidenceTier.ANTICIPATORY,
                agency_level="unrestricted",
            )
            is False
        )

    def test_budget_standard_tier_requires_autonomous_agency(self) -> None:
        b = self._budget()
        # Insufficient agencies
        for level in (None, "reactive", "suggestive"):
            assert (
                b.try_reserve(
                    agent_id="a",
                    tokens=10,
                    tier=ConfidenceTier.STANDARD,
                    agency_level=level,
                )
                is False
            )
        # Sufficient agencies (use distinct agents to avoid budget exhaustion interference)
        assert (
            b.try_reserve(
                agent_id="b",
                tokens=10,
                tier=ConfidenceTier.STANDARD,
                agency_level="autonomous",
            )
            is True
        )
        assert (
            b.try_reserve(
                agent_id="c",
                tokens=10,
                tier=ConfidenceTier.STANDARD,
                agency_level="unrestricted",
            )
            is True
        )

    def test_budget_cheap_tier_unrestricted_by_agency(self) -> None:
        b = self._budget()
        assert (
            b.try_reserve(
                agent_id="a", tokens=10, tier=ConfidenceTier.CHEAP, agency_level=None
            )
            is True
        )
        assert (
            b.try_reserve(
                agent_id="b",
                tokens=10,
                tier=ConfidenceTier.CHEAP,
                agency_level="reactive",
            )
            is True
        )

    def test_budget_window_resets_after_window_seconds(self) -> None:
        b = self._budget(tokens_per_window=100, window_seconds=300.0)
        assert (
            b.try_reserve(agent_id="a", tokens=100, tier=ConfidenceTier.CHEAP) is True
        )
        # Next reserve fails — exhausted
        assert (
            b.try_reserve(agent_id="a", tokens=10, tier=ConfidenceTier.CHEAP) is False
        )
        # Force window expiration by rewinding the state's window_start
        state = b._states["a"]
        state.window_start = time.time() - 400.0
        assert (
            b.try_reserve(agent_id="a", tokens=50, tier=ConfidenceTier.CHEAP) is True
        )

    def test_budget_flush_rate_feedback_halves_budget(self) -> None:
        b = self._budget(tokens_per_window=100, window_seconds=300.0)
        # Record 10 flushed outcomes
        for _ in range(10):
            b.record_outcome(agent_id="a", was_flushed=True)
        assert b.get_flush_rate("a") >= 0.30
        # Force a window reset to apply the halving feedback
        if "a" in b._states:
            b._states["a"].window_start = time.time() - 400.0
        # Now the next try_reserve starts a new window with halved=True (50 tokens)
        assert (
            b.try_reserve(agent_id="a", tokens=50, tier=ConfidenceTier.CHEAP) is True
        )
        # 60 would exceed halved budget of 50
        assert (
            b.try_reserve(agent_id="a", tokens=60, tier=ConfidenceTier.CHEAP) is False
        )


# =============================================================================
# Class D — TestAccuracyTracker (4 tests)
# =============================================================================


class TestAccuracyTracker:
    def test_accuracy_empty_returns_zero_rates(self) -> None:
        t = AccuracyTracker(ring_size=10)
        rates = t.get_rates("nobody")
        assert rates == AccuracyRates(0.0, 0.0, 0.0, 0.0, 0)

    def test_accuracy_single_hit_returns_full_hit_rate(self) -> None:
        t = AccuracyTracker(ring_size=10)
        t.record(agent_id="a", outcome=PredictionOutcome.HIT)
        rates = t.get_rates("a")
        assert rates.hit_rate == 1.0
        assert rates.sample_count == 1

    def test_accuracy_mixed_outcomes_compute_correctly(self) -> None:
        t = AccuracyTracker(ring_size=10)
        for o in (
            PredictionOutcome.HIT,
            PredictionOutcome.MISS,
            PredictionOutcome.FLUSHED,
            PredictionOutcome.ERROR,
        ):
            t.record(agent_id="a", outcome=o)
        rates = t.get_rates("a")
        assert rates.hit_rate == 0.25
        assert rates.miss_rate == 0.25
        assert rates.flush_rate == 0.25
        assert rates.error_rate == 0.25
        assert rates.sample_count == 4

    def test_accuracy_ring_size_caps_history(self) -> None:
        t = AccuracyTracker(ring_size=10)
        for _ in range(11):
            t.record(agent_id="a", outcome=PredictionOutcome.HIT)
        rates = t.get_rates("a")
        assert rates.sample_count == 10


# =============================================================================
# Class E — TestSpeculationExecutor (4 tests)
# =============================================================================


class _StubSubTaskExecutor:
    def __init__(self, results: list[Any] | None = None, raises: bool = False) -> None:
        self.results = results or []
        self.raises = raises
        self.called = False

    async def execute(self, chain: Any, context: dict[str, Any]) -> list[Any]:
        self.called = True
        if self.raises:
            raise RuntimeError("execute boom")
        return self.results


def _descriptor(intent: str = "foo", tier: ConfidenceTier = ConfidenceTier.CHEAP) -> PredictionDescriptor:
    return PredictionDescriptor(
        agent_id="a1",
        agent_type="t1",
        intent_type=intent,
        confidence=0.5,
        tier=tier,
        signature="sig_xyz",
    )


class TestSpeculationExecutor:
    @pytest.mark.asyncio
    async def test_executor_no_sub_task_executor_returns_none(self) -> None:
        cache = SpeculationCache(max_entries=4, ttl_seconds=60.0)
        budget = SpeculationBudget(
            tokens_per_window=1000,
            window_seconds=300.0,
            flush_rate_threshold=0.30,
            flush_rate_window_seconds=3600.0,
        )
        tracker = AccuracyTracker(ring_size=10)
        ex = SpeculationExecutor(
            sub_task_executor=None,
            cache=cache,
            budget=budget,
            accuracy_tracker=tracker,
        )
        result = await ex.dispatch(
            SpeculationRequest(descriptor=_descriptor(), chain=SimpleNamespace(steps=[]))
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_executor_budget_denied_returns_none(self) -> None:
        cache = SpeculationCache(max_entries=4, ttl_seconds=60.0)
        budget = SpeculationBudget(
            tokens_per_window=1000,
            window_seconds=300.0,
            flush_rate_threshold=0.30,
            flush_rate_window_seconds=3600.0,
        )
        tracker = AccuracyTracker(ring_size=10)
        sub = _StubSubTaskExecutor()
        ex = SpeculationExecutor(
            sub_task_executor=sub, cache=cache, budget=budget, accuracy_tracker=tracker
        )
        # ZERO_COST tier always denied → executor not called
        result = await ex.dispatch(
            SpeculationRequest(
                descriptor=_descriptor(tier=ConfidenceTier.ZERO_COST),
                chain=SimpleNamespace(steps=[]),
            )
        )
        assert result is None
        assert sub.called is False

    @pytest.mark.asyncio
    async def test_executor_dispatch_stores_in_cache(self) -> None:
        cache = SpeculationCache(max_entries=4, ttl_seconds=60.0)
        budget = SpeculationBudget(
            tokens_per_window=10_000,
            window_seconds=300.0,
            flush_rate_threshold=0.30,
            flush_rate_window_seconds=3600.0,
        )
        tracker = AccuracyTracker(ring_size=10)
        sub = _StubSubTaskExecutor(
            results=[SimpleNamespace(tokens_used=42)]
        )
        ex = SpeculationExecutor(
            sub_task_executor=sub, cache=cache, budget=budget, accuracy_tracker=tracker
        )
        descriptor = _descriptor()
        result = await ex.dispatch(
            SpeculationRequest(descriptor=descriptor, chain=SimpleNamespace(steps=[]))
        )
        assert result is not None
        assert result["tokens_used"] == 42
        assert cache.lookup(descriptor.signature) is not None

    def test_executor_record_outcome_error_emits_event(self) -> None:
        events: list[tuple[str, dict]] = []
        cache = SpeculationCache(max_entries=4, ttl_seconds=60.0)
        budget = SpeculationBudget(
            tokens_per_window=1000,
            window_seconds=300.0,
            flush_rate_threshold=0.30,
            flush_rate_window_seconds=3600.0,
        )
        tracker = AccuracyTracker(ring_size=10)
        ex = SpeculationExecutor(
            sub_task_executor=None,
            cache=cache,
            budget=budget,
            accuracy_tracker=tracker,
            emit_event=lambda et, p: events.append((et, p)),
        )
        descriptor = _descriptor(intent="foo")
        ex.record_outcome(
            descriptor=descriptor,
            actual_intent="bar",
            actual_decision_summary="something else",
        )
        rates = tracker.get_rates("a1")
        assert rates.error_rate == 1.0
        assert any(et == "prediction_error_recorded" for et, _ in events)


# =============================================================================
# Class F — TestPolicySeams (3 tests)
# =============================================================================


class TestPolicySeams:
    def test_noop_idle_speculation_policy_returns_none(self) -> None:
        policy = NoOpIdleSpeculationPolicy()
        assert policy.should_speculate_now(agent_id="a", runtime=None) is None

    def test_noop_preplay_hook_returns_empty_list(self) -> None:
        hook = NoOpPreplayHook()
        assert hook.generate_preplay_predictions(dream_report=None, runtime=None) == []

    def test_protocol_runtime_checkable(self) -> None:
        assert isinstance(NoOpIdleSpeculationPolicy(), IdleSpeculationPolicy)


# =============================================================================
# Class G — TestConfigAndWiring (2 tests)
# =============================================================================


class TestConfigAndWiring:
    def test_config_defaults_disabled(self) -> None:
        cfg = PredictiveBranchingConfig()
        assert cfg.enabled is False
        sys_cfg = SystemConfig()
        assert sys_cfg.predictive_branching.enabled is False

    def test_wirer_no_op_when_disabled(self) -> None:
        from probos.startup.finalize import _wire_predictive_branching

        runtime = SimpleNamespace(
            hebbian_router=_StubHebbian(),
            ontology=_StubOntology(),
            prediction_engine=None,
            speculation_cache=None,
            speculation_budget=None,
            speculation_executor=None,
            accuracy_tracker=None,
        )
        config = SystemConfig()  # predictive_branching defaults to disabled
        result = _wire_predictive_branching(runtime=runtime, config=config)
        assert result is False
        assert runtime.prediction_engine is None
        assert runtime.speculation_cache is None
        assert runtime.speculation_budget is None
        assert runtime.speculation_executor is None
        assert runtime.accuracy_tracker is None


# =============================================================================
# Class H — TestDecisionPipelineIntegration (1 test)
# =============================================================================


class TestDecisionPipelineIntegration:
    def test_decide_via_llm_prefetch_injection_and_hit_record(self) -> None:
        """AD-633d hook integration: pre-populated cache + matching signature
        produces _speculation_prefetch on the observation and records a HIT.

        This exercises the same primitives the hook uses (compute_signature +
        SpeculationCache.lookup + AccuracyTracker.record) without invoking the
        full _decide_via_llm machinery. Per the prompt's Section 10 Class H:
        the hook block was not extracted into a helper method, so the test
        validates the post-conditions the hook is expected to produce.
        """
        agent_id = "agent_x"
        intent_type = "foo"
        observation = {
            "intent": intent_type,
            "thread_id": "t1",
            "last_speaker_id": "alice",
        }

        cache = SpeculationCache(max_entries=4, ttl_seconds=60.0)
        tracker = AccuracyTracker(ring_size=10)
        emit = MagicMock()

        signature = compute_signature(
            agent_id=agent_id, intent_type=intent_type, observation=observation
        )
        stored_payload = {"results": ["pre-computed analysis"], "origin": "operational"}
        cache.store(
            signature=signature,
            agent_id=agent_id,
            intent_type=intent_type,
            payload=stored_payload,
        )

        # Replicate the hook block's behavior on a runtime + agent namespace
        runtime = SimpleNamespace(
            speculation_cache=cache,
            prediction_engine=object(),  # sentinel non-None
            accuracy_tracker=tracker,
            emit_event=emit,
        )
        agent = SimpleNamespace(id=agent_id, _runtime=runtime)

        # Inline the hook logic exactly as in cognitive_agent._decide_via_llm
        sig = compute_signature(
            agent_id=agent.id,
            intent_type=str(observation.get("intent", "")),
            observation=observation,
        )
        payload = runtime.speculation_cache.lookup(sig)
        if payload is not None:
            observation["_speculation_prefetch"] = payload
            runtime.accuracy_tracker.record(
                agent_id=agent.id, outcome=PredictionOutcome.HIT
            )

        assert observation["_speculation_prefetch"] == stored_payload
        rates = tracker.get_rates(agent_id)
        assert rates.hit_rate == 1.0
        assert rates.sample_count == 1
