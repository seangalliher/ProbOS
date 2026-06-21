"""AD-1043: tests for the representative-query miner (federation/ard/representative_queries.py).

BF-287 real fixtures: a real ``WorkflowCache`` (the PRIMARY, zero-I/O source)
with real ``TaskDAG``/``TaskNode`` entries, plus explicit ``_Fake*`` episodic
stubs (NOT MagicMock) for the SECONDARY source. Asserts the ``episodic_k`` gate
and the per-resource cap.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1043_representative_queries.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

from typing import Any

import pytest

from probos.cognitive.workflow_cache import WorkflowCache
from probos.federation.ard import mine_representative_queries
from probos.types import TaskDAG, TaskNode


# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


class _Runtime:
    def __init__(self, *, workflow_cache: Any = None, episodic_memory: Any = None) -> None:
        self.workflow_cache = workflow_cache
        self.episodic_memory = episodic_memory


class _FakeEpisode:
    def __init__(self, user_input: str, *, dag_summary: dict[str, Any] | None = None,
                 outcomes: list[dict[str, Any]] | None = None) -> None:
        self.user_input = user_input
        self.dag_summary = dag_summary or {}
        self.outcomes = outcomes or []


class _FakeEpisodic:
    def __init__(self, episodes: list[_FakeEpisode]) -> None:
        self._episodes = episodes
        self.recent_called = False

    async def recent(self, k: int) -> list[_FakeEpisode]:
        self.recent_called = True
        return list(self._episodes[:k])


def _store(cache: WorkflowCache, user_input: str, *intents: str) -> None:
    dag = TaskDAG(
        nodes=[TaskNode(id=f"t{i}", intent=intent, status="completed") for i, intent in enumerate(intents, 1)],
    )
    cache.store(user_input, dag)


# --------------------------------------------------------------------------- #
# Workflow cache (PRIMARY)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_workflow_cache_intent_maps_to_pattern() -> None:
    cache = WorkflowCache()
    _store(cache, "Read my file", "read_file")
    rq = await mine_representative_queries(_Runtime(workflow_cache=cache))
    # pattern is normalized (lowercased) by the cache.
    assert rq == {"read_file": ["read my file"]}


@pytest.mark.asyncio
async def test_per_resource_cap_bounds_queries() -> None:
    cache = WorkflowCache()
    for i in range(7):
        _store(cache, f"query number {i}", "read_file")
    rq = await mine_representative_queries(_Runtime(workflow_cache=cache))
    assert len(rq["read_file"]) == 5


# --------------------------------------------------------------------------- #
# Episodic memory (SECONDARY, gated by episodic_k)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_episodic_contributes_via_intent_types_when_k_positive() -> None:
    episodic = _FakeEpisodic([_FakeEpisode("search for cats", dag_summary={"intent_types": ["search_files"]})])
    runtime = _Runtime(workflow_cache=WorkflowCache(), episodic_memory=episodic)
    rq = await mine_representative_queries(runtime, episodic_k=10)
    assert rq == {"search_files": ["search for cats"]}
    assert episodic.recent_called is True


@pytest.mark.asyncio
async def test_episodic_falls_back_to_outcomes_intent() -> None:
    episodic = _FakeEpisodic([_FakeEpisode("run the build", outcomes=[{"intent": "run_command"}])])
    runtime = _Runtime(workflow_cache=WorkflowCache(), episodic_memory=episodic)
    rq = await mine_representative_queries(runtime, episodic_k=10)
    assert rq == {"run_command": ["run the build"]}


@pytest.mark.asyncio
async def test_episodic_k_zero_skips_episodic_entirely() -> None:
    episodic = _FakeEpisodic([_FakeEpisode("should not appear", dag_summary={"intent_types": ["x"]})])
    runtime = _Runtime(workflow_cache=WorkflowCache(), episodic_memory=episodic)
    rq = await mine_representative_queries(runtime, episodic_k=0)
    assert episodic.recent_called is False
    assert rq == {}


@pytest.mark.asyncio
async def test_both_sources_merge_when_k_positive() -> None:
    cache = WorkflowCache()
    _store(cache, "read my file", "read_file")
    episodic = _FakeEpisodic([_FakeEpisode("search cats", dag_summary={"intent_types": ["search_files"]})])
    runtime = _Runtime(workflow_cache=cache, episodic_memory=episodic)
    rq = await mine_representative_queries(runtime, episodic_k=10)
    assert rq == {"read_file": ["read my file"], "search_files": ["search cats"]}


# --------------------------------------------------------------------------- #
# Honest-degrade (absent sources)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_absent_sources_return_empty_map() -> None:
    rq = await mine_representative_queries(_Runtime())
    assert rq == {}


@pytest.mark.asyncio
async def test_empty_cache_returns_empty_map() -> None:
    rq = await mine_representative_queries(_Runtime(workflow_cache=WorkflowCache()))
    assert rq == {}
