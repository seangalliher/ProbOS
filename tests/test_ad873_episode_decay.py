"""AD-873: Ebbinghaus episode decay + composite retrieval reranking.

Covers the five wave items:
  * Episode.strength / Episode.stability fields round-trip through ChromaDB.
  * decayed_strength / reinforced_stability pure helpers.
  * DreamingEngine.dream_cycle() decay sweep (honest-degrade).
  * recall() composite reranking (config-gated, neutral by default).
  * Neutral-default reproduction of semantic-only ordering.

Uses REAL fixtures (real EpisodicMemory on a ChromaDB tmp_path, real
DreamingEngine with MockEpisodicMemory) — no MagicMock at the substrate
boundary (BF-287).
"""

import math
import time

import pytest

from probos.cognitive.episodic import (
    EpisodicMemory,
    decayed_strength,
    reinforced_stability,
)
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.cognitive.dreaming import DreamingEngine
from probos.config import DreamingConfig
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import HebbianRouter
from probos.types import Episode, EBBINGHAUS_DEFAULT_STABILITY_SECONDS


# ---------------------------------------------------------------------------
# Item 2 — pure decay / reinforcement helpers
# ---------------------------------------------------------------------------


class TestDecayHelpers:
    def test_decayed_strength_reduces_over_time(self):
        """Strength falls monotonically as elapsed time grows."""
        stability = 1000.0
        s_short = decayed_strength(1.0, stability, 100.0)
        s_long = decayed_strength(1.0, stability, 500.0)
        assert s_short < 1.0
        assert s_long < s_short

    def test_decayed_strength_matches_closed_form(self):
        """Helper reproduces S(t) = S0 * e^(-dt/stability)."""
        got = decayed_strength(0.8, 2000.0, 400.0)
        expected = 0.8 * math.exp(-400.0 / 2000.0)
        assert got == pytest.approx(expected)

    def test_decayed_strength_zero_stability_guard(self):
        """Non-positive stability has no decay constant — return unchanged."""
        assert decayed_strength(0.7, 0.0, 500.0) == 0.7
        assert decayed_strength(0.7, -5.0, 500.0) == 0.7

    def test_decayed_strength_zero_delta_guard(self):
        """No elapsed time — return strength unchanged."""
        assert decayed_strength(0.6, 1000.0, 0.0) == 0.6
        assert decayed_strength(0.6, 1000.0, -10.0) == 0.6

    def test_reinforced_stability_grows_with_activation(self):
        """Positive activation grows stability above the baseline."""
        base = EBBINGHAUS_DEFAULT_STABILITY_SECONDS
        grown = reinforced_stability(base, 2.0)
        assert grown > base

    def test_reinforced_stability_monotonic_in_activation(self):
        """Higher activation => more stability."""
        base = 1000.0
        low = reinforced_stability(base, 1.0)
        high = reinforced_stability(base, 4.0)
        assert high > low > base

    def test_reinforced_stability_never_shrinks_on_neg_inf(self):
        """A never-accessed episode (tracker returns -inf) is unchanged."""
        base = 1000.0
        assert reinforced_stability(base, float("-inf")) == base
        assert reinforced_stability(base, 0.0) == base
        assert reinforced_stability(base, -3.0) == base

    def test_replay_grows_stability_then_slows_decay(self):
        """Reinforced stability decays slower for the same elapsed time."""
        base = EBBINGHAUS_DEFAULT_STABILITY_SECONDS
        reinforced = reinforced_stability(base, 3.0)
        age = 86400.0  # one day
        s_base = decayed_strength(1.0, base, age)
        s_reinforced = decayed_strength(1.0, reinforced, age)
        assert s_reinforced > s_base


# ---------------------------------------------------------------------------
# Item 1 — composite score + field defaults (pure / unit)
# ---------------------------------------------------------------------------


class TestCompositeScore:
    def test_all_zero_weights_reproduce_similarity(self):
        """Neutral (all-zero) weights => composite == similarity."""
        ep = Episode(timestamp=time.time(), user_input="x", strength=0.3,
                     importance=2, confidence=0.4)
        score = EpisodicMemory._composite_recall_score(
            0.75, ep, {}, time.time()
        )
        assert score == pytest.approx(0.75)

    def test_strength_weight_lowers_weak_episode(self):
        """A weak-strength episode scores below a fresh one at equal similarity."""
        now = time.time()
        weak = Episode(timestamp=now, user_input="x", strength=0.1)
        fresh = Episode(timestamp=now, user_input="x", strength=1.0)
        weights = {"strength": 1.0}
        s_weak = EpisodicMemory._composite_recall_score(0.8, weak, weights, now)
        s_fresh = EpisodicMemory._composite_recall_score(0.8, fresh, weights, now)
        assert s_fresh > s_weak

    def test_importance_weight_contributes(self):
        """Importance measurably raises the composite when weighted."""
        now = time.time()
        low = Episode(timestamp=now, user_input="x", importance=1)
        high = Episode(timestamp=now, user_input="x", importance=9)
        weights = {"importance": 1.0}
        s_low = EpisodicMemory._composite_recall_score(0.7, low, weights, now)
        s_high = EpisodicMemory._composite_recall_score(0.7, high, weights, now)
        assert s_high > s_low

    def test_recency_weight_contributes(self):
        """A recent episode scores above an older one when recency is weighted."""
        now = time.time()
        old = Episode(timestamp=now - 30 * 86400.0, user_input="x")
        recent = Episode(timestamp=now - 60.0, user_input="x")
        weights = {"recency": 1.0}
        s_old = EpisodicMemory._composite_recall_score(0.7, old, weights, now)
        s_recent = EpisodicMemory._composite_recall_score(0.7, recent, weights, now)
        assert s_recent > s_old


# ---------------------------------------------------------------------------
# Item 1 — metadata round-trip (real ChromaDB)
# ---------------------------------------------------------------------------


class TestFieldRoundTrip:
    @pytest.fixture
    async def mem(self, tmp_path):
        m = EpisodicMemory(
            db_path=tmp_path / "ad873.db",
            max_episodes=100,
            relevance_threshold=0.3,
        )
        await m.start()
        yield m
        await m.stop()

    @pytest.mark.asyncio
    async def test_strength_stability_survive_store_recall(self, mem):
        """strength/stability written to and read back from ChromaDB metadata."""
        ep = Episode(
            timestamp=time.time(),
            user_input="the quarterly report is due friday",
            outcomes=[{"intent": "read_file", "success": True}],
            strength=0.42,
            stability=99999.0,
        )
        await mem.store(ep)
        results = await mem.recall("quarterly report", k=5)
        assert len(results) >= 1
        match = next(r for r in results if r.id == ep.id)
        assert match.strength == pytest.approx(0.42)
        assert match.stability == pytest.approx(99999.0)

    def test_pre_ad873_metadata_defaults_cleanly(self, mem):
        """An episode with no strength/stability keys defaults to baseline."""
        ep = mem._metadata_to_episode("legacy-id", "doc", {})
        assert ep.strength == 1.0
        assert ep.stability == EBBINGHAUS_DEFAULT_STABILITY_SECONDS

    def test_corrupt_metadata_values_default_cleanly(self, mem):
        """Non-numeric metadata values fall back to defaults, not crash."""
        ep = mem._metadata_to_episode(
            "bad-id", "doc", {"strength": "not-a-number", "stability": None}
        )
        assert ep.strength == 1.0
        assert ep.stability == EBBINGHAUS_DEFAULT_STABILITY_SECONDS


# ---------------------------------------------------------------------------
# Item 3 — decay sweep (real EpisodicMemory)
# ---------------------------------------------------------------------------


class _FakeActivationTracker:
    """Minimal stand-in for AD-567d ActivationTracker.get_activations_batch."""

    def __init__(self, activations: dict[str, float]):
        self._activations = dict(activations)

    async def get_activations_batch(self, episode_ids: list[str]) -> dict[str, float]:
        # BF-633: mirror the REAL ActivationTracker.get_activations_batch, which
        # is `async def`. A sync fake here is exactly why the missing-await bug
        # shipped green — the fake's contract diverged from production.
        return {eid: self._activations.get(eid, float("-inf")) for eid in episode_ids}


class TestDecaySweep:
    @pytest.fixture
    async def mem(self, tmp_path):
        m = EpisodicMemory(
            db_path=tmp_path / "ad873_sweep.db",
            max_episodes=100,
            relevance_threshold=0.3,
        )
        await m.start()
        yield m
        await m.stop()

    @pytest.mark.asyncio
    async def test_sweep_decays_old_episode_without_tracker(self, mem):
        """Old episode loses strength after a sweep; reinforced stays 0."""
        old_ts = time.time() - 10 * 86400.0  # 10 days old
        ep = Episode(
            timestamp=old_ts,
            user_input="an old memory about reading files",
            outcomes=[{"intent": "read_file", "success": True}],
        )
        await mem.store(ep)

        counts = await mem.sweep_episode_decay(None)

        assert counts["swept"] >= 1
        assert counts["reinforced"] == 0
        results = await mem.recall("old memory reading files", k=5)
        match = next(r for r in results if r.id == ep.id)
        assert match.strength < 1.0

    @pytest.mark.asyncio
    async def test_sweep_reinforces_with_positive_activation(self, mem):
        """A positive activation grows stability and is counted as reinforced."""
        ep = Episode(
            timestamp=time.time() - 86400.0,
            user_input="a frequently recalled memory",
            outcomes=[{"intent": "read_file", "success": True}],
        )
        await mem.store(ep)
        tracker = _FakeActivationTracker({ep.id: 3.0})

        counts = await mem.sweep_episode_decay(tracker)

        assert counts["reinforced"] >= 1
        results = await mem.recall("frequently recalled memory", k=5)
        match = next(r for r in results if r.id == ep.id)
        assert match.stability > EBBINGHAUS_DEFAULT_STABILITY_SECONDS

    @pytest.mark.asyncio
    async def test_sweep_idempotent_on_repeated_runs(self, mem):
        """Repeated sweeps converge (stability recomputed from baseline)."""
        ep = Episode(
            timestamp=time.time() - 86400.0,
            user_input="convergent memory",
            outcomes=[{"intent": "read_file", "success": True}],
        )
        await mem.store(ep)
        tracker = _FakeActivationTracker({ep.id: 2.0})

        await mem.sweep_episode_decay(tracker)
        first = next(r for r in await mem.recall("convergent memory", k=5)
                     if r.id == ep.id)
        await mem.sweep_episode_decay(tracker)
        second = next(r for r in await mem.recall("convergent memory", k=5)
                      if r.id == ep.id)

        assert second.stability == pytest.approx(first.stability, rel=1e-6)

    @pytest.mark.asyncio
    async def test_sweep_honest_degrades_on_empty_collection(self, mem):
        """No episodes => zero counts, never raises."""
        counts = await mem.sweep_episode_decay(None)
        assert counts == {"swept": 0, "reinforced": 0}

    @pytest.mark.asyncio
    async def test_sweep_survives_failing_tracker(self, mem):
        """A tracker that raises degrades to neutral activation, never aborts."""
        ep = Episode(
            timestamp=time.time() - 86400.0,
            user_input="resilient memory",
            outcomes=[{"intent": "read_file", "success": True}],
        )
        await mem.store(ep)

        class _BrokenTracker:
            async def get_activations_batch(self, episode_ids):
                raise RuntimeError("tracker down")

        counts = await mem.sweep_episode_decay(_BrokenTracker())

        assert counts["swept"] >= 1
        assert counts["reinforced"] == 0

    @pytest.mark.asyncio
    async def test_sweep_awaits_async_tracker(self, mem):
        """BF-633: sweep_episode_decay MUST await the async activation tracker.

        The real ActivationTracker.get_activations_batch is `async def`. The
        shipped bug called it without `await`, so `activations` was an
        un-awaited coroutine; every episode then raised AttributeError on
        `.get(...)` and decay/reinforcement silently no-op'd (the live
        RuntimeWarning). This locks the contract: the real method is a
        coroutine function, the fake awaited tap fires, and reinforcement is
        actually applied.
        """
        import inspect

        from probos.cognitive.activation_tracker import ActivationTracker

        assert inspect.iscoroutinefunction(ActivationTracker.get_activations_batch)

        ep = Episode(
            timestamp=time.time() - 86400.0,
            user_input="an awaited memory",
            outcomes=[{"intent": "read_file", "success": True}],
        )
        await mem.store(ep)

        awaited = {"called": False}

        class _AsyncTracker:
            async def get_activations_batch(self, episode_ids):
                awaited["called"] = True
                return {ep.id: 3.0}

        counts = await mem.sweep_episode_decay(_AsyncTracker())

        assert awaited["called"] is True
        assert counts["reinforced"] >= 1


# ---------------------------------------------------------------------------
# Item 4/5 — composite recall reranking (real EpisodicMemory)
# ---------------------------------------------------------------------------


class TestRecallRerank:
    @pytest.mark.asyncio
    async def test_rerank_disabled_by_default_is_semantic_only(self, tmp_path):
        """Default construction leaves rerank off — semantic ordering intact."""
        m = EpisodicMemory(
            db_path=tmp_path / "ad873_default.db",
            max_episodes=100,
            relevance_threshold=0.3,
        )
        await m.start()
        try:
            assert m._recall_rerank_enabled is False
            ep_high = Episode(timestamp=time.time(),
                              user_input="the quarterly report is due friday",
                              strength=1.0)
            ep_low = Episode(timestamp=time.time(),
                             user_input="the quarterly report is due friday",
                             strength=0.1)
            await m.store(ep_high)
            await m.store(ep_low)
            results = await m.recall("quarterly report", k=2)
            ids = {r.id for r in results}
            assert ids == {ep_high.id, ep_low.id}
        finally:
            await m.stop()

    @pytest.mark.asyncio
    async def test_rerank_strength_promotes_strong_episode(self, tmp_path):
        """With strength-weighted rerank, the stronger episode ranks first."""
        m = EpisodicMemory(
            db_path=tmp_path / "ad873_strong.db",
            max_episodes=100,
            relevance_threshold=0.3,
            recall_rerank_enabled=True,
            recall_rerank_weights={"strength": 1.0},
        )
        await m.start()
        try:
            ep_high = Episode(timestamp=time.time(),
                              user_input="the quarterly report is due friday",
                              strength=1.0)
            ep_low = Episode(timestamp=time.time(),
                             user_input="the quarterly report is due friday",
                             strength=0.1)
            await m.store(ep_low)
            await m.store(ep_high)
            results = await m.recall("quarterly report", k=2)
            assert len(results) == 2
            assert results[0].id == ep_high.id
        finally:
            await m.stop()

    @pytest.mark.asyncio
    async def test_neutral_weights_reproduce_semantic_only(self, tmp_path):
        """Rerank enabled with all-zero weights returns the same set, k-bounded."""
        m = EpisodicMemory(
            db_path=tmp_path / "ad873_neutral.db",
            max_episodes=100,
            relevance_threshold=0.3,
            recall_rerank_enabled=True,
            recall_rerank_weights={"strength": 0.0, "recency": 0.0,
                                   "importance": 0.0, "confidence": 0.0},
        )
        await m.start()
        try:
            ep_a = Episode(timestamp=time.time(),
                           user_input="the quarterly report is due friday",
                           strength=0.1, importance=1)
            ep_b = Episode(timestamp=time.time(),
                           user_input="the quarterly report is due friday",
                           strength=1.0, importance=9)
            await m.store(ep_a)
            await m.store(ep_b)
            results = await m.recall("quarterly report", k=2)
            ids = {r.id for r in results}
            assert ids == {ep_a.id, ep_b.id}
            assert len(results) == 2
        finally:
            await m.stop()


# ---------------------------------------------------------------------------
# Item 3 — dream_cycle integration (real DreamingEngine)
# ---------------------------------------------------------------------------


def _dream_config() -> DreamingConfig:
    return DreamingConfig(
        idle_threshold_seconds=1.0,
        dream_interval_seconds=1.0,
        replay_episode_count=50,
        prune_threshold=0.01,
        pre_warm_top_k=5,
    )


class TestDreamCycleDecayIntegration:
    @pytest.mark.asyncio
    async def test_dream_cycle_invokes_sweep(self):
        """dream_cycle() calls episodic_memory.sweep_episode_decay once."""
        memory = MockEpisodicMemory(relevance_threshold=0.3)
        await memory.store(Episode(
            timestamp=time.time(),
            user_input="seed episode for dream cycle",
            outcomes=[{"intent": "read_file", "success": True}],
            agent_ids=["agent_a"],
        ))
        calls: list[object] = []

        async def _recording_sweep(activation_tracker=None, *, limit: int = 500):
            calls.append(activation_tracker)
            return {"swept": 0, "reinforced": 0}

        memory.sweep_episode_decay = _recording_sweep
        engine = DreamingEngine(
            HebbianRouter(decay_rate=0.995, reward=0.05),
            TrustNetwork(prior_alpha=2.0, prior_beta=2.0, decay_rate=0.999),
            memory,
            _dream_config(),
        )

        await engine.dream_cycle()

        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_dream_cycle_survives_sweep_failure(self):
        """A failing sweep must not abort the dream cycle (Tier-2 honest-degrade)."""
        memory = MockEpisodicMemory(relevance_threshold=0.3)
        await memory.store(Episode(
            timestamp=time.time(),
            user_input="seed episode for dream cycle",
            outcomes=[{"intent": "read_file", "success": True}],
            agent_ids=["agent_a"],
        ))

        async def _broken_sweep(activation_tracker=None, *, limit: int = 500):
            raise RuntimeError("decay exploded")

        memory.sweep_episode_decay = _broken_sweep
        engine = DreamingEngine(
            HebbianRouter(decay_rate=0.995, reward=0.05),
            TrustNetwork(prior_alpha=2.0, prior_beta=2.0, decay_rate=0.999),
            memory,
            _dream_config(),
        )

        report = await engine.dream_cycle()

        assert report is not None
