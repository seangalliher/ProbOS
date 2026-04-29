"""AD-572: Episodic-procedural bridge tests."""

from __future__ import annotations

import time
from typing import Any

import pytest

from probos.cognitive.dreaming import DreamingEngine
from probos.cognitive.episode_clustering import EpisodeCluster
from probos.cognitive.episodic_procedural_bridge import EpisodicProceduralBridge
from probos.cognitive.procedures import Procedure
from probos.config import BridgeConfig, DreamingConfig
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import HebbianRouter
from probos.types import DreamReport, Episode


def _cluster(
    cluster_id: str = "cluster-1",
    episode_ids: list[str] | None = None,
    *,
    success_rate: float = 1.0,
    is_success_dominant: bool = True,
    intent_types: list[str] | None = None,
) -> EpisodeCluster:
    ids = episode_ids or [f"ep-{idx}" for idx in range(5)]
    return EpisodeCluster(
        cluster_id=cluster_id,
        episode_ids=ids,
        episode_count=len(ids),
        centroid=[1.0, 0.0],
        variance=0.0,
        success_rate=success_rate,
        is_success_dominant=is_success_dominant,
        is_failure_dominant=not is_success_dominant,
        participating_agents=["agent-a"],
        intent_types=intent_types or ["diagnose"],
        first_occurrence=1.0,
        last_occurrence=2.0,
    )


def _episodes(count: int = 5, *, intent: str = "diagnose") -> list[Episode]:
    return [
        Episode(
            id=f"ep-{idx}",
            timestamp=time.time() + idx,
            user_input=f"diagnostic pattern {idx}",
            outcomes=[{"intent": intent, "success": True}],
            agent_ids=["agent-a"],
        )
        for idx in range(count)
    ]


class _FakeProcedureStore:
    def __init__(self, procedures: list[Procedure] | None = None) -> None:
        self._procedures = {procedure.id: procedure for procedure in procedures or []}
        self.saved: list[Procedure] = []

    async def list_active(self) -> list[dict[str, Any]]:
        return [{"id": procedure_id} for procedure_id in self._procedures]

    async def get(self, procedure_id: str) -> Procedure | None:
        return self._procedures.get(procedure_id)

    async def save(self, procedure: Procedure) -> None:
        self.saved.append(procedure)
        self._procedures[procedure.id] = procedure


class _FakeEpisodicMemory:
    def __init__(self, episodes: list[Episode]) -> None:
        self._episodes = episodes

    async def get_stats(self) -> dict[str, Any]:
        return {"total": len(self._episodes)}

    async def recent(self, k: int = 10) -> list[Episode]:
        return list(reversed(self._episodes[-k:]))

    async def get_embeddings(self, episode_ids: list[str]) -> dict[str, list[float]]:
        return {episode_id: [1.0, 0.0] for episode_id in episode_ids}


def test_scan_for_procedures() -> None:
    bridge = EpisodicProceduralBridge(BridgeConfig())

    result = bridge.scan_for_procedures([_cluster()], [])

    assert len(result) == 1
    assert result[0].evolution_type == "BRIDGED"
    assert result[0].origin_cluster_id == "cluster-1"


def test_novel_pattern_detection() -> None:
    bridge = EpisodicProceduralBridge(BridgeConfig())
    existing = [Procedure(provenance=["other-1", "other-2"], intent_types=["diagnose"])]

    assert bridge._is_novel_pattern(_cluster(), existing) is True


def test_existing_pattern_skipped() -> None:
    bridge = EpisodicProceduralBridge(BridgeConfig())
    existing = [Procedure(provenance=["ep-0", "ep-1", "ep-2", "ep-3"], intent_types=["diagnose"])]

    assert bridge.scan_for_procedures([_cluster()], existing) == []


@pytest.mark.asyncio
async def test_bridge_episodes() -> None:
    store = _FakeProcedureStore()
    bridge = EpisodicProceduralBridge(BridgeConfig(), procedure_store=store)

    result = await bridge.bridge_episodes_to_procedures(_episodes(), [_cluster()])

    assert len(result) == 1
    assert result[0].intent_types == ["diagnose"]


def test_merge_cross_cycle() -> None:
    bridge = EpisodicProceduralBridge(BridgeConfig())
    procedure = Procedure(provenance=["ep-0"], success_count=1)

    result = bridge._merge_cross_cycle(_cluster(success_rate=0.8), procedure)

    assert result.provenance == ["ep-0", "ep-1", "ep-2", "ep-3", "ep-4"]
    assert result.success_count == 5


def test_min_episode_threshold() -> None:
    bridge = EpisodicProceduralBridge(BridgeConfig(min_cross_cycle_episodes=5))

    result = bridge.scan_for_procedures([_cluster(episode_ids=["ep-1", "ep-2", "ep-3"])], [])

    assert result == []


def test_novelty_threshold() -> None:
    bridge = EpisodicProceduralBridge(BridgeConfig(novelty_threshold=0.7))
    cluster = _cluster(episode_ids=[f"ep-{idx}" for idx in range(10)])
    low_overlap = [Procedure(provenance=["ep-0", "ep-1"], intent_types=["diagnose"])]
    high_overlap = [Procedure(provenance=["ep-0", "ep-1", "ep-2", "ep-3"], intent_types=["diagnose"])]

    assert bridge._is_novel_pattern(cluster, low_overlap) is True
    assert bridge._is_novel_pattern(cluster, high_overlap) is False


def test_config_disabled() -> None:
    bridge = EpisodicProceduralBridge(BridgeConfig(enabled=False))

    assert bridge.scan_for_procedures([_cluster()], []) == []


@pytest.mark.asyncio
async def test_dream_step_integration() -> None:
    episodes = _episodes(5)
    memory = _FakeEpisodicMemory(episodes)
    store = _FakeProcedureStore()
    bridge = EpisodicProceduralBridge(BridgeConfig(), procedure_store=store, episodic_memory=memory)
    engine = DreamingEngine(
        router=HebbianRouter(),
        trust_network=TrustNetwork(),
        episodic_memory=memory,
        config=DreamingConfig(replay_episode_count=10),
        procedure_store=store,
        episodic_procedural_bridge=bridge,
    )

    report = await engine.dream_cycle()

    assert report.bridged_procedures == 1
    assert len(store.saved) == 1
    assert store.saved[0].evolution_type == "BRIDGED"


def test_dream_report_field() -> None:
    assert DreamReport().bridged_procedures == 0