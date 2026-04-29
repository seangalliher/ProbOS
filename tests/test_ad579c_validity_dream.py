"""AD-579c: Validity-aware dream consolidation tests."""

from __future__ import annotations

import time
from typing import Any

import pytest

from probos.cognitive import dreaming as dreaming_module
from probos.cognitive.dreaming import DreamingEngine
from probos.cognitive.episode_clustering import EpisodeCluster, cluster_episodes, compute_cluster_validity
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.procedures import EvolutionResult, Procedure
from probos.config import DreamingConfig
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import HebbianRouter
from probos.types import Episode


def _episode(
    episode_id: str,
    *,
    timestamp: float = 100.0,
    valid_from: float = 0.0,
    valid_until: float = 0.0,
    intent: str = "diagnose",
) -> Episode:
    return Episode(
        id=episode_id,
        timestamp=timestamp,
        user_input=f"diagnostic memory {episode_id}",
        outcomes=[{"intent": intent, "success": True}],
        agent_ids=["agent-a"],
        valid_from=valid_from,
        valid_until=valid_until,
    )


class _FakeProcedureStore:
    def __init__(self, parent: Procedure) -> None:
        self.parent = parent
        self.saved: list[Procedure] = []
        self.deactivated: list[tuple[str, str]] = []

    async def list_active(self) -> list[dict[str, Any]]:
        return [{"id": self.parent.id}]

    async def get_quality_metrics(self, procedure_id: str) -> dict[str, Any]:
        return {"total_selections": 10, "fallback_rate": 0.8, "completion_rate": 0.2}

    async def get(self, procedure_id: str) -> Procedure | None:
        return self.parent if procedure_id == self.parent.id else None

    async def save(self, procedure: Procedure, content_diff: str = "", change_summary: str = "") -> None:
        self.saved.append(procedure)

    async def deactivate(self, procedure_id: str, superseded_by: str = "") -> None:
        self.deactivated.append((procedure_id, superseded_by))


class _FakeEvolutionMemory:
    def __init__(self, episodes: list[Episode]) -> None:
        self.episodes = episodes
        self.validity_updates: list[tuple[str, float]] = []

    async def recall_by_intent(self, intent_type: str) -> list[Episode]:
        return [episode for episode in self.episodes if episode.outcomes[0]["intent"] == intent_type]

    async def update_episode_validity(self, episode_id: str, valid_until: float) -> bool:
        self.validity_updates.append((episode_id, valid_until))
        return True


def test_compute_cluster_validity_basic() -> None:
    episodes = [
        _episode("ep-1", valid_from=10.0, valid_until=50.0),
        _episode("ep-2", valid_from=20.0, valid_until=80.0),
    ]

    assert compute_cluster_validity(episodes) == (10.0, 80.0)


def test_compute_cluster_validity_open_ended() -> None:
    episodes = [
        _episode("ep-1", valid_from=10.0, valid_until=50.0),
        _episode("ep-2", valid_from=20.0, valid_until=0.0),
    ]

    assert compute_cluster_validity(episodes) == (10.0, 0.0)


def test_compute_cluster_validity_uses_timestamp_fallback() -> None:
    episodes = [
        _episode("ep-1", timestamp=30.0, valid_from=0.0, valid_until=60.0),
        _episode("ep-2", timestamp=40.0, valid_from=35.0, valid_until=70.0),
    ]

    assert compute_cluster_validity(episodes) == (30.0, 70.0)


def test_episode_cluster_has_validity_fields() -> None:
    cluster = EpisodeCluster(
        cluster_id="cluster",
        episode_ids=[],
        episode_count=0,
        centroid=[],
        variance=0.0,
        success_rate=0.0,
        is_success_dominant=False,
        is_failure_dominant=False,
        participating_agents=[],
    )

    assert cluster.valid_from == 0.0
    assert cluster.valid_until == 0.0


def test_cluster_episodes_populates_validity() -> None:
    episodes = [
        _episode("ep-1", valid_from=10.0, valid_until=50.0),
        _episode("ep-2", valid_from=20.0, valid_until=70.0),
        _episode("ep-3", valid_from=30.0, valid_until=90.0),
    ]
    embeddings = {episode.id: [1.0, 0.0] for episode in episodes}

    clusters = cluster_episodes(episodes, embeddings, min_episodes=3)

    assert len(clusters) == 1
    assert clusters[0].valid_from == 10.0
    assert clusters[0].valid_until == 90.0


@pytest.mark.asyncio
async def test_update_episode_validity_succeeds(tmp_path) -> None:
    memory = EpisodicMemory(str(tmp_path / "episodes.db"))
    await memory.start()
    try:
        episode = _episode("stored-ep", valid_until=0.0)
        await memory.store(episode)

        updated = await memory.update_episode_validity("stored-ep", valid_until=123.0)
        result = memory._collection.get(ids=["stored-ep"], include=["metadatas"])

        assert updated is True
        assert result["metadatas"][0]["valid_until"] == 123.0
    finally:
        await memory.stop()


@pytest.mark.asyncio
async def test_update_episode_validity_not_found(tmp_path) -> None:
    memory = EpisodicMemory(str(tmp_path / "episodes.db"))
    await memory.start()
    try:
        assert await memory.update_episode_validity("missing", valid_until=123.0) is False
    finally:
        await memory.stop()


@pytest.mark.asyncio
async def test_superseded_episodes_get_valid_until(monkeypatch: pytest.MonkeyPatch) -> None:
    episodes = [_episode("ep-1"), _episode("ep-2")]
    memory = _FakeEvolutionMemory(episodes)
    parent = Procedure(id="parent", name="Parent", intent_types=["diagnose"])
    child = Procedure(id="child", name="Child", intent_types=["diagnose"], evolution_type="FIX")
    store = _FakeProcedureStore(parent)

    async def fake_evolve_fix(*args: Any, **kwargs: Any) -> EvolutionResult:
        return EvolutionResult(procedure=child, content_diff="diff", change_summary="summary")

    monkeypatch.setattr(dreaming_module, "diagnose_procedure_health", lambda *args, **kwargs: "FIX: stale")
    monkeypatch.setattr(dreaming_module, "evolve_fix_procedure", fake_evolve_fix)

    engine = DreamingEngine(
        router=HebbianRouter(),
        trust_network=TrustNetwork(),
        episodic_memory=memory,
        config=DreamingConfig(),
        llm_client=object(),
        procedure_store=store,
    )

    before = time.time()
    evolved = await engine._evolve_degraded_procedures([], [])

    assert evolved == 1
    assert store.deactivated == [("parent", "child")]
    assert [episode_id for episode_id, _ in memory.validity_updates] == ["ep-1", "ep-2"]
    assert all(valid_until >= before for _, valid_until in memory.validity_updates)