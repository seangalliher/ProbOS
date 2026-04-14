"""AD-611: 3D Memory Graph Visualization tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.types import Episode, AnchorFrame


def _make_episode(
    ep_id: str = "ep-001",
    user_input: str = "test input",
    importance: int = 5,
    timestamp: float = 1000.0,
    agent_ids: list[str] | None = None,
    channel: str = "bridge",
    department: str = "bridge",
    thread_id: str = "",
    participants: list[str] | None = None,
    source: str = "ward_room",
) -> Episode:
    return Episode(
        id=ep_id,
        user_input=user_input,
        importance=importance,
        timestamp=timestamp,
        agent_ids=agent_ids or ["agent-a"],
        source=source,
        anchors=AnchorFrame(
            channel=channel,
            department=department,
            thread_id=thread_id,
            participants=participants or [],
        ),
    )


def _make_runtime(episodes: list[Episode] | None = None):
    runtime = MagicMock()
    episodes = episodes or []

    runtime.episodic_memory = AsyncMock()
    runtime.episodic_memory.recent_for_agent = AsyncMock(return_value=episodes)
    runtime.episodic_memory.recall_by_anchor = AsyncMock(return_value=[])
    runtime.episodic_memory.count_for_agent = AsyncMock(return_value=len(episodes))
    runtime.episodic_memory.get_embeddings = AsyncMock(return_value={})
    runtime.episodic_memory._collection = None  # No ChromaDB in tests
    runtime.episodic_memory._activation_tracker = None
    runtime.identity_registry = None
    runtime.registry = MagicMock()
    runtime.registry.all.return_value = []

    return runtime


@pytest.mark.asyncio
async def test_empty_memory_returns_empty_graph():
    from probos.routers.memory_graph import get_memory_graph

    runtime = _make_runtime([])
    result = await get_memory_graph("agent-a", runtime, max_nodes=200, ship_wide=False, semantic_k=5, time_range_hours=None)
    assert result["nodes"] == []
    assert result["edges"] == []
    assert result["meta"]["nodes_shown"] == 0


@pytest.mark.asyncio
async def test_nodes_built_from_episodes():
    from probos.routers.memory_graph import get_memory_graph

    eps = [
        _make_episode("ep-1", "Hello bridge", importance=8, timestamp=1000),
        _make_episode("ep-2", "Engineering report", importance=3, timestamp=2000,
                       channel="engineering"),
    ]
    runtime = _make_runtime(eps)
    result = await get_memory_graph("agent-a", runtime, max_nodes=200, ship_wide=False, semantic_k=5, time_range_hours=None)

    assert len(result["nodes"]) == 2
    node_ids = {n["id"] for n in result["nodes"]}
    assert "ep-1" in node_ids
    assert "ep-2" in node_ids
    # Verify importance → size mapping
    node_1 = next(n for n in result["nodes"] if n["id"] == "ep-1")
    assert node_1["importance"] == 8
    assert node_1["size"] > 4.0  # 2 + (8/10)*4 = 5.2


@pytest.mark.asyncio
async def test_node_color_by_channel():
    from probos.routers.memory_graph import get_memory_graph

    eps = [
        _make_episode("ep-1", "test", channel="bridge"),
        _make_episode("ep-2", "test", channel="medical"),
    ]
    runtime = _make_runtime(eps)
    result = await get_memory_graph("agent-a", runtime, max_nodes=200, ship_wide=False, semantic_k=5, time_range_hours=None)

    node_1 = next(n for n in result["nodes"] if n["id"] == "ep-1")
    node_2 = next(n for n in result["nodes"] if n["id"] == "ep-2")
    assert node_1["color"] == "#f0b060"  # bridge
    assert node_2["color"] == "#52c474"  # medical


@pytest.mark.asyncio
async def test_thread_edges_created():
    from probos.routers.memory_graph import _build_edges

    eps = [
        _make_episode("ep-1", "msg 1", thread_id="thread-abc", timestamp=1000),
        _make_episode("ep-2", "msg 2", thread_id="thread-abc", timestamp=1001),
        _make_episode("ep-3", "msg 3", thread_id="thread-xyz", timestamp=1002),
    ]
    episodic = AsyncMock()
    episodic.get_embeddings = AsyncMock(return_value={})
    episodic._collection = None

    edges = await _build_edges(episodic, eps, [e.id for e in eps], semantic_k=5)
    thread_edges = [e for e in edges if e["type"] == "thread"]
    assert len(thread_edges) == 1  # ep-1 ↔ ep-2 share thread-abc
    assert {thread_edges[0]["source"], thread_edges[0]["target"]} == {"ep-1", "ep-2"}


@pytest.mark.asyncio
async def test_temporal_edges_within_5_minutes():
    from probos.routers.memory_graph import _build_edges

    eps = [
        _make_episode("ep-1", "msg 1", timestamp=1000),
        _make_episode("ep-2", "msg 2", timestamp=1120),   # 2 min later
        _make_episode("ep-3", "msg 3", timestamp=2000),   # 16 min later
    ]
    episodic = AsyncMock()
    episodic.get_embeddings = AsyncMock(return_value={})
    episodic._collection = None

    edges = await _build_edges(episodic, eps, [e.id for e in eps], semantic_k=5)
    temporal_edges = [e for e in edges if e["type"] == "temporal"]
    assert len(temporal_edges) == 1  # only ep-1 ↔ ep-2
    assert temporal_edges[0]["weight"] > 0.5  # 1 - (120/300) = 0.6


@pytest.mark.asyncio
async def test_participant_edges_jaccard():
    from probos.routers.memory_graph import _build_edges

    eps = [
        _make_episode("ep-1", "msg 1", participants=["atlas", "lynx", "kira"]),
        _make_episode("ep-2", "msg 2", participants=["atlas", "lynx"]),
        _make_episode("ep-3", "msg 3", participants=["bones"]),
    ]
    episodic = AsyncMock()
    episodic.get_embeddings = AsyncMock(return_value={})
    episodic._collection = None

    edges = await _build_edges(episodic, eps, [e.id for e in eps], semantic_k=5)
    part_edges = [e for e in edges if e["type"] == "participant"]
    # ep-1(atlas,lynx,kira) ↔ ep-2(atlas,lynx): Jaccard = 2/3 ≈ 0.667 > 0.3 → edge
    # ep-1 ↔ ep-3: no overlap → no edge
    # ep-2 ↔ ep-3: no overlap → no edge
    assert len(part_edges) == 1
    assert part_edges[0]["weight"] == pytest.approx(0.667, abs=0.01)


@pytest.mark.asyncio
async def test_edge_cap_enforced():
    from probos.routers.memory_graph import _build_edges, MAX_EDGES_CAP

    # Create many episodes close in time to generate lots of temporal edges
    eps = [
        _make_episode(f"ep-{i}", f"msg {i}", timestamp=1000 + i)
        for i in range(100)
    ]
    episodic = AsyncMock()
    episodic.get_embeddings = AsyncMock(return_value={})
    episodic._collection = None

    edges = await _build_edges(episodic, eps, [e.id for e in eps], semantic_k=5)
    assert len(edges) <= MAX_EDGES_CAP


@pytest.mark.asyncio
async def test_max_nodes_cap():
    from probos.routers.memory_graph import get_memory_graph

    eps = [_make_episode(f"ep-{i}", f"msg {i}") for i in range(10)]
    runtime = _make_runtime(eps)
    # Request more than MAX_NODES_CAP
    result = await get_memory_graph("agent-a", runtime, max_nodes=9999, ship_wide=False, semantic_k=5, time_range_hours=None)
    # Should be capped (and won't exceed episode count either)
    assert result["meta"]["nodes_shown"] <= 500


@pytest.mark.asyncio
async def test_no_episodic_memory_returns_503():
    from probos.routers.memory_graph import get_memory_graph

    runtime = MagicMock()
    runtime.episodic_memory = None
    result = await get_memory_graph("agent-a", runtime)
    assert result.status_code == 503


@pytest.mark.asyncio
async def test_activation_drives_node_opacity():
    from probos.routers.memory_graph import get_memory_graph

    eps = [_make_episode("ep-1", "test")]
    runtime = _make_runtime(eps)
    tracker = AsyncMock()
    tracker.get_activations_batch = AsyncMock(return_value={"ep-1": 3.0})
    runtime.episodic_memory._activation_tracker = tracker

    result = await get_memory_graph("agent-a", runtime, max_nodes=200, ship_wide=False, semantic_k=5, time_range_hours=None)
    node = result["nodes"][0]
    # sigmoid(3.0) ≈ 0.953
    assert node["activation"] > 0.9


@pytest.mark.asyncio
async def test_ship_wide_merges_agents():
    from probos.routers.memory_graph import get_memory_graph

    ep_a = _make_episode("ep-a", "agent A", agent_ids=["agent-a"])
    ep_b = _make_episode("ep-b", "agent B", agent_ids=["agent-b"])

    runtime = _make_runtime([])
    # Ship-wide queries each agent separately
    agent_a = MagicMock()
    agent_a.id = "agent-a"
    agent_b = MagicMock()
    agent_b.id = "agent-b"
    runtime.registry.all.return_value = [agent_a, agent_b]

    # Mock is_crew_agent to return True for both
    with patch("probos.crew_utils.is_crew_agent", return_value=True):
        # recent_for_agent returns different episodes per agent
        call_count = 0
        async def side_effect(sid, k=5):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [ep_a]
            return [ep_b]
        runtime.episodic_memory.recent_for_agent = AsyncMock(side_effect=side_effect)

        result = await get_memory_graph("agent-a", runtime, max_nodes=200, ship_wide=True, semantic_k=5, time_range_hours=None)
        node_ids = {n["id"] for n in result["nodes"]}
        assert "ep-a" in node_ids
        assert "ep-b" in node_ids
