"""AD-959: Lean shutdown consolidation — skip LLM-bound idle steps at shutdown.

The shutdown handler used to run the full ``dream_cycle`` under a hard 30s
budget. At real episode volume its per-cluster LLM calls (procedure extraction,
spaced-retrieval therapy, …) overran the budget, so consolidation was cancelled
mid-flight — which AD-820 stamps as a ``partial`` integrity marker that refuses
the next boot (and historically tore ChromaDB's HNSW index when the cancelled
writes left it half-written, #750).

``DreamingEngine.consolidate_for_shutdown`` runs ONLY the cheap, in-memory
learning-weight updates (micro-dream Hebbian replay + prune + trust) and makes
no episodic-collection writes, so it finishes well under budget; the deferred
idle-time steps re-run on the next dream cycle.

BF-287 discipline: real ``HebbianRouter`` / ``TrustNetwork`` / ``DreamingConfig``
plus a small real ``_FakeEpisodicMemory`` stub with scripted async returns —
NOT ``MagicMock`` (which would auto-create phantom write methods and hide a
regression where the lean path started writing to the episodic collection).
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from probos.cognitive.dreaming import DreamingEngine
from probos.config import DreamingConfig
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import REL_INTENT, HebbianRouter
from probos.types import DreamReport


# --- BF-287 real-but-fake fixtures (no MagicMock) --------------------------


class _FakeEpisodicMemory:
    """Scripted episodic-memory stub.

    Serves recent episodes + stats for the read path, and records whether any
    *write* path (``store``) was touched — the lean shutdown path must make no
    episodic-collection writes.
    """

    def __init__(self, episodes=None, *, recent_raises=False):
        self._episodes = list(episodes or [])
        self._recent_raises = recent_raises
        self.recent_calls = 0
        self.store_called = False
        self.stop_called = False

    async def get_stats(self):
        return {"total": len(self._episodes)}

    async def recent(self, k=10):
        self.recent_calls += 1
        if self._recent_raises:
            raise RuntimeError("simulated episodic read failure")
        return list(self._episodes[:k])

    async def store(self, *args, **kwargs):  # pragma: no cover - must not run
        self.store_called = True

    async def stop(self):  # pragma: no cover - not exercised by lean path
        self.stop_called = True


class _RecordingLLMClient:
    """Any attribute that gets *called* is recorded.

    The lean shutdown path must never touch the LLM client — this proves no
    procedure extraction / spaced-retrieval therapy runs at shutdown.
    """

    def __init__(self):
        self.calls: list[str] = []

    def __getattr__(self, name):
        async def _rec(*args, **kwargs):
            self.calls.append(name)
            return None

        return _rec


def _episode(agent_id="agent-1", *, success=True, intent="analyze", eid="ep"):
    return SimpleNamespace(
        id=eid,
        agent_ids=[agent_id],
        outcomes=[{"intent": intent, "success": success}],
    )


def _make_engine(*, episodes=None, llm_client=None, recent_raises=False):
    config = DreamingConfig(
        idle_threshold_seconds=1.0,
        dream_interval_seconds=1.0,
        replay_episode_count=50,
    )
    router = HebbianRouter(decay_rate=0.995, reward=0.05)
    trust = TrustNetwork(prior_alpha=2.0, prior_beta=2.0, decay_rate=0.999)
    memory = _FakeEpisodicMemory(episodes, recent_raises=recent_raises)
    engine = DreamingEngine(router, trust, memory, config, llm_client=llm_client)
    return engine, router, trust, memory


# --- happy path ------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_dreamreport_with_duration():
    engine, *_ = _make_engine(episodes=[_episode()])
    report = await engine.consolidate_for_shutdown()
    assert isinstance(report, DreamReport)
    assert report.duration_ms >= 0.0


@pytest.mark.asyncio
async def test_never_calls_llm_even_with_success_clusters():
    rec = _RecordingLLMClient()
    eps = [_episode(eid=f"ep{i}") for i in range(5)]  # success-dominant
    engine, *_ = _make_engine(episodes=eps, llm_client=rec)
    await engine.consolidate_for_shutdown()
    # No procedure extraction / therapy at shutdown.
    assert rec.calls == []


@pytest.mark.asyncio
async def test_makes_no_episodic_writes():
    # The core architectural guarantee: no Chroma writes → no torn HNSW.
    eps = [_episode(eid="ep1"), _episode(eid="ep2")]
    engine, _router, _trust, mem = _make_engine(episodes=eps)
    await engine.consolidate_for_shutdown()
    assert mem.store_called is False


@pytest.mark.asyncio
async def test_runs_trust_consolidation_real_network():
    # Two all-success episodes for one agent → count > 1 → trust boost.
    eps = [
        _episode("agent-win", success=True, eid="ep1"),
        _episode("agent-win", success=True, eid="ep2"),
    ]
    engine, _router, trust, _mem = _make_engine(episodes=eps)
    before = trust.get_score("agent-win")
    report = await engine.consolidate_for_shutdown()
    after = trust.get_score("agent-win")
    assert report.trust_adjustments >= 1
    assert after > before  # success-dominant agent boosted


@pytest.mark.asyncio
async def test_prunes_below_threshold_weights():
    engine, router, *_ = _make_engine(episodes=[_episode()])
    # Seed a weight below prune_threshold (0.01).
    router._weights[("dead-intent", "ghost", REL_INTENT)] = 0.005
    router._compat_weights[("dead-intent", "ghost")] = 0.005
    report = await engine.consolidate_for_shutdown()
    assert report.weights_pruned >= 1
    assert ("dead-intent", "ghost", REL_INTENT) not in router._weights


@pytest.mark.asyncio
async def test_micro_dream_replay_strengthens_weights():
    eps = [_episode("agent-1", success=True, intent="search", eid="ep1")]
    engine, router, *_ = _make_engine(episodes=eps)
    report = await engine.consolidate_for_shutdown()
    assert report.episodes_replayed >= 1
    assert report.weights_strengthened >= 1
    # The replayed success pathway exists in the router.
    assert router.get_weight("search", "agent-1", REL_INTENT) > 0.0


# --- edge cases / honest-degrade ------------------------------------------


@pytest.mark.asyncio
async def test_empty_memory_returns_zeros():
    engine, *_ = _make_engine(episodes=[])
    report = await engine.consolidate_for_shutdown()
    assert report.episodes_replayed == 0
    assert report.trust_adjustments == 0
    assert report.weights_pruned == 0


@pytest.mark.asyncio
async def test_honest_degrades_when_recent_raises():
    # episodic_memory.recent raises → both micro-dream and trust steps degrade,
    # but the method still returns a clean DreamReport (so the shutdown handler
    # can stamp a non-partial marker).
    engine, _router, _trust, _mem = _make_engine(
        episodes=[_episode()], recent_raises=True
    )
    report = await engine.consolidate_for_shutdown()
    assert isinstance(report, DreamReport)
    assert report.trust_adjustments == 0


@pytest.mark.asyncio
async def test_does_not_invoke_full_dream_cycle():
    eps = [_episode()]

    class _SpyEngine(DreamingEngine):
        async def dream_cycle(self):  # type: ignore[override]
            self.dream_cycle_called = True
            return DreamReport()

    config = DreamingConfig(
        idle_threshold_seconds=1.0,
        dream_interval_seconds=1.0,
        replay_episode_count=50,
    )
    router = HebbianRouter(decay_rate=0.995, reward=0.05)
    trust = TrustNetwork(prior_alpha=2.0, prior_beta=2.0, decay_rate=0.999)
    memory = _FakeEpisodicMemory(eps)
    spy = _SpyEngine(router, trust, memory, config)
    await spy.consolidate_for_shutdown()
    assert getattr(spy, "dream_cycle_called", False) is False


# --- wiring guard (regression) --------------------------------------------


def test_shutdown_wiring_calls_lean_path_not_dream_cycle():
    # BF-287 phantom guard: assert the literal API name appears in the shutdown
    # source, and that the full dream_cycle is no longer called on the shutdown
    # path (would re-introduce the 30s-overrun / torn-HNSW class).
    import probos.startup.shutdown as shutdown_mod

    src = inspect.getsource(shutdown_mod)
    assert "engine.consolidate_for_shutdown()" in src
    assert "engine.dream_cycle()" not in src
