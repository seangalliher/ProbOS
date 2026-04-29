import json
import time
from types import SimpleNamespace

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.retroactive_evolver import EvolutionReport, RetroactiveEvolver
from probos.types import AnchorFrame, Episode


class _FakeRetroactiveConfig:
    def __init__(
        self,
        *,
        enabled: bool = True,
        neighbor_k: int = 5,
        similarity_threshold: float = 0.7,
        max_relations_per_episode: int = 10,
        propagate_watch_section: bool = True,
        propagate_department: bool = True,
    ) -> None:
        self.enabled = enabled
        self.neighbor_k = neighbor_k
        self.similarity_threshold = similarity_threshold
        self.max_relations_per_episode = max_relations_per_episode
        self.propagate_watch_section = propagate_watch_section
        self.propagate_department = propagate_department


class _FakeEpisodicMemory:
    def __init__(self) -> None:
        self.metadata_store: dict[str, dict] = {}
        self.recall_results: list = []
        self.recall_calls: list[dict] = []

    async def recall_weighted(self, agent_id: str, query: str, k: int = 5, **kwargs):
        self.recall_calls.append({"agent_id": agent_id, "query": query, "k": k})
        return self.recall_results[:k]

    async def update_episode_metadata(self, episode_id: str, metadata_updates: dict) -> bool:
        if episode_id not in self.metadata_store:
            return False
        self.metadata_store[episode_id].update(metadata_updates)
        return True

    async def get_episode_metadata(self, episode_id: str) -> dict | None:
        return self.metadata_store.get(episode_id)


class _FakeCollection:
    def __init__(self) -> None:
        self.metadata_store: dict[str, dict] = {}
        self.document_store: dict[str, str] = {}

    def get(self, ids: list[str] | None = None, include: list[str] | None = None, **kwargs) -> dict:
        if ids is None:
            all_ids = list(self.metadata_store)
            result = {"ids": all_ids}
            if include and "metadatas" in include:
                result["metadatas"] = [self.metadata_store[episode_id] for episode_id in all_ids]
            if include and "documents" in include:
                result["documents"] = [self.document_store.get(episode_id, "") for episode_id in all_ids]
            return result

        found_ids = [episode_id for episode_id in ids if episode_id in self.metadata_store]
        result = {"ids": found_ids}
        if include and "metadatas" in include:
            result["metadatas"] = [self.metadata_store[episode_id] for episode_id in found_ids]
        return result

    def update(self, ids: list[str], metadatas: list[dict]) -> None:
        for episode_id, metadata in zip(ids, metadatas):
            self.metadata_store[episode_id] = metadata

    def add(self, ids: list[str], documents: list[str], metadatas: list[dict]) -> None:
        for episode_id, document, metadata in zip(ids, documents, metadatas):
            self.document_store[episode_id] = document
            self.metadata_store[episode_id] = metadata

    def count(self) -> int:
        return len(self.metadata_store)


class _FakeStoreEvolver:
    def __init__(self) -> None:
        self.calls: list[Episode] = []

    async def evolve_on_store(self, episode: Episode) -> EvolutionReport:
        self.calls.append(episode)
        return EvolutionReport()


@pytest.fixture
def fake_memory() -> _FakeEpisodicMemory:
    return _FakeEpisodicMemory()


@pytest.fixture
def evolver(fake_memory: _FakeEpisodicMemory) -> RetroactiveEvolver:
    return RetroactiveEvolver(
        config=_FakeRetroactiveConfig(),
        episodic_memory=fake_memory,
        agent_id="test-agent",
    )


def _make_episode(
    *,
    episode_id: str = "",
    user_input: str = "test observation",
    anchors: AnchorFrame | None = None,
    timestamp: float = 0.0,
) -> Episode:
    return Episode(
        id=episode_id or f"episode-{time.time_ns()}",
        timestamp=timestamp or time.time(),
        user_input=user_input,
        anchors=anchors,
    )


def _make_score(episode: Episode, score: float = 0.9) -> SimpleNamespace:
    return SimpleNamespace(
        episode=episode,
        composite_score=score,
        semantic_similarity=score,
    )


def _relations(metadata: dict) -> list[dict]:
    return json.loads(metadata.get("relations_json", "[]"))


@pytest.mark.asyncio
async def test_evolve_finds_neighbors(
    evolver: RetroactiveEvolver,
    fake_memory: _FakeEpisodicMemory,
) -> None:
    source = _make_episode(episode_id="source", user_input="shared memory topic")
    neighbor = _make_episode(episode_id="neighbor", user_input="shared memory topic")
    fake_memory.metadata_store = {"source": {}, "neighbor": {}}
    fake_memory.recall_results = [_make_score(neighbor)]

    report = await evolver.evolve_on_store(source)

    assert fake_memory.recall_calls == [{"agent_id": "test-agent", "query": "shared memory topic", "k": 5}]
    assert report.relations_added == 2


@pytest.mark.asyncio
async def test_relate_to_similar(
    evolver: RetroactiveEvolver,
    fake_memory: _FakeEpisodicMemory,
) -> None:
    source = _make_episode(episode_id="source")
    neighbor = _make_episode(episode_id="neighbor")
    fake_memory.metadata_store = {"source": {}, "neighbor": {}}
    fake_memory.recall_results = [_make_score(neighbor)]

    await evolver.evolve_on_store(source)

    source_relations = _relations(fake_memory.metadata_store["source"])
    assert source_relations[0]["related_episode_id"] == "neighbor"
    assert source_relations[0]["relation_type"] == "associative"


@pytest.mark.asyncio
async def test_propagate_watch_section(
    evolver: RetroactiveEvolver,
    fake_memory: _FakeEpisodicMemory,
) -> None:
    source = _make_episode(
        episode_id="source",
        anchors=AnchorFrame(watch_section="alpha"),
    )
    neighbor = _make_episode(episode_id="neighbor")
    fake_memory.metadata_store = {"source": {}, "neighbor": {"anchor_watch_section": ""}}
    fake_memory.recall_results = [_make_score(neighbor)]

    await evolver.evolve_on_store(source)

    assert fake_memory.metadata_store["neighbor"]["anchor_watch_section"] == "alpha"


@pytest.mark.asyncio
async def test_propagate_department(
    evolver: RetroactiveEvolver,
    fake_memory: _FakeEpisodicMemory,
) -> None:
    source = _make_episode(
        episode_id="source",
        anchors=AnchorFrame(department="science"),
    )
    neighbor = _make_episode(episode_id="neighbor")
    fake_memory.metadata_store = {"source": {}, "neighbor": {"anchor_department": ""}}
    fake_memory.recall_results = [_make_score(neighbor)]

    await evolver.evolve_on_store(source)

    assert fake_memory.metadata_store["neighbor"]["anchor_department"] == "science"


@pytest.mark.asyncio
async def test_max_relations_cap(fake_memory: _FakeEpisodicMemory) -> None:
    evolver = RetroactiveEvolver(
        config=_FakeRetroactiveConfig(max_relations_per_episode=1),
        episodic_memory=fake_memory,
    )
    source = _make_episode(episode_id="source")
    neighbor = _make_episode(episode_id="neighbor")
    capped_relation = json.dumps([{"related_episode_id": "existing", "relation_type": "associative"}])
    fake_memory.metadata_store = {
        "source": {"relations_json": capped_relation},
        "neighbor": {"relations_json": capped_relation},
    }
    fake_memory.recall_results = [_make_score(neighbor)]

    report = await evolver.evolve_on_store(source)

    assert report.relations_added == 0
    assert len(_relations(fake_memory.metadata_store["source"])) == 1


@pytest.mark.asyncio
async def test_no_self_relation(
    evolver: RetroactiveEvolver,
    fake_memory: _FakeEpisodicMemory,
) -> None:
    source = _make_episode(episode_id="source")
    fake_memory.metadata_store = {"source": {}}
    fake_memory.recall_results = [_make_score(source)]

    report = await evolver.evolve_on_store(source)

    assert report.relations_added == 0
    assert "relations_json" not in fake_memory.metadata_store["source"]


@pytest.mark.asyncio
async def test_bidirectional_relations(
    evolver: RetroactiveEvolver,
    fake_memory: _FakeEpisodicMemory,
) -> None:
    source = _make_episode(episode_id="source")
    neighbor = _make_episode(episode_id="neighbor")
    fake_memory.metadata_store = {"source": {}, "neighbor": {}}
    fake_memory.recall_results = [_make_score(neighbor)]

    await evolver.evolve_on_store(source)

    source_relations = _relations(fake_memory.metadata_store["source"])
    neighbor_relations = _relations(fake_memory.metadata_store["neighbor"])
    assert source_relations[0]["related_episode_id"] == "neighbor"
    assert neighbor_relations[0]["related_episode_id"] == "source"


@pytest.mark.asyncio
async def test_evolution_report_counts(
    evolver: RetroactiveEvolver,
    fake_memory: _FakeEpisodicMemory,
) -> None:
    source = _make_episode(
        episode_id="source",
        anchors=AnchorFrame(watch_section="alpha", department="science"),
    )
    neighbor = _make_episode(episode_id="neighbor")
    fake_memory.metadata_store = {
        "source": {},
        "neighbor": {"anchor_watch_section": "", "anchor_department": ""},
    }
    fake_memory.recall_results = [_make_score(neighbor)]

    report = await evolver.evolve_on_store(source)

    assert report.episodes_updated == 1
    assert report.relations_added == 2
    assert report.anchor_fields_propagated == 2


@pytest.mark.asyncio
async def test_similarity_threshold_filter(
    evolver: RetroactiveEvolver,
    fake_memory: _FakeEpisodicMemory,
) -> None:
    source = _make_episode(episode_id="source")
    neighbor = _make_episode(episode_id="neighbor")
    fake_memory.metadata_store = {"source": {}, "neighbor": {}}
    fake_memory.recall_results = [_make_score(neighbor, score=0.2)]

    report = await evolver.evolve_on_store(source)

    assert report.relations_added == 0
    assert "relations_json" not in fake_memory.metadata_store["source"]


@pytest.mark.asyncio
async def test_disabled_config(fake_memory: _FakeEpisodicMemory) -> None:
    evolver = RetroactiveEvolver(
        config=_FakeRetroactiveConfig(enabled=False),
        episodic_memory=fake_memory,
    )
    source = _make_episode(episode_id="source")

    report = await evolver.evolve_on_store(source)

    assert report == EvolutionReport()
    assert fake_memory.recall_calls == []


@pytest.mark.asyncio
async def test_update_episode_metadata(tmp_path) -> None:
    memory = EpisodicMemory(tmp_path / "memory")
    collection = _FakeCollection()
    collection.metadata_store["episode-1"] = {"anchor_department": ""}
    memory._collection = collection

    updated = await memory.update_episode_metadata("episode-1", {"anchor_department": "science"})
    metadata = await memory.get_episode_metadata("episode-1")

    assert updated is True
    assert metadata == {"anchor_department": "science"}


@pytest.mark.asyncio
async def test_integration_with_store(tmp_path) -> None:
    memory = EpisodicMemory(tmp_path / "memory", max_episodes=10)
    collection = _FakeCollection()
    memory._collection = collection
    evolver = _FakeStoreEvolver()
    memory.set_retroactive_evolver(evolver)
    episode = _make_episode(episode_id="episode-1", user_input="unique store integration")

    await memory.store(episode)

    assert evolver.calls == [episode]
    assert "episode-1" in collection.metadata_store