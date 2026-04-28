"""AD-603: Anchor recall composite scoring."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.episodic import EpisodicMemory
from probos.types import AnchorFrame, Episode, RecallScore


class _FakeCollection:
    def __init__(self, query_result: dict | None = None, count: int = 1) -> None:
        self._query_result = query_result or {"ids": [[]], "distances": [[]]}
        self._count = count

    def count(self) -> int:
        return self._count

    def query(self, **kwargs: object) -> dict:
        return self._query_result


def _make_episode(
    ep_id: str,
    user_input: str = "test input",
    agent_ids: list[str] | None = None,
    timestamp: float = 0.0,
    department: str = "",
    channel: str = "",
    trigger_agent: str = "",
    watch_section: str = "",
    importance: int = 5,
) -> Episode:
    anchors = (
        AnchorFrame(
            department=department,
            channel=channel,
            trigger_agent=trigger_agent,
            watch_section=watch_section,
        )
        if any([department, channel, trigger_agent, watch_section])
        else None
    )
    return Episode(
        id=ep_id,
        timestamp=timestamp or time.time(),
        user_input=user_input,
        dag_summary={},
        outcomes=[],
        agent_ids=agent_ids or ["agent_1"],
        duration_ms=100.0,
        anchors=anchors,
        importance=importance,
    )


def _make_memory(
    episodes: list[Episode],
    *,
    collection: _FakeCollection | None = None,
    keyword_results: list[tuple[str, float]] | None = None,
) -> EpisodicMemory:
    em = EpisodicMemory.__new__(EpisodicMemory)
    em._collection = collection
    em._query_reformulation_enabled = False
    em.recall_by_anchor = AsyncMock(return_value=episodes)
    em.keyword_search = AsyncMock(return_value=keyword_results or [])
    return em


def _score(ep: Episode, score: float) -> RecallScore:
    return RecallScore(episode=ep, composite_score=score)


def _merge_recall(
    anchor_results: list | None,
    scored_results: list[RecallScore],
    episodes: list[Episode],
    query_watch_section: str = "",
) -> tuple[list[RecallScore], list[Episode]]:
    if not anchor_results:
        return scored_results, episodes

    is_scored = bool(anchor_results and isinstance(anchor_results[0], RecallScore))
    if is_scored:
        seen_ids = {rs.episode.id for rs in anchor_results}
        merged = list(anchor_results)
        for rs in scored_results:
            if rs.episode.id in seen_ids:
                continue
            if (
                query_watch_section
                and getattr(rs.episode, "anchors", None)
                and getattr(rs.episode.anchors, "watch_section", "")
                and rs.episode.anchors.watch_section != query_watch_section
            ):
                continue
            merged.append(rs)
            seen_ids.add(rs.episode.id)
        merged.sort(key=lambda result: result.composite_score, reverse=True)
        return merged, [rs.episode for rs in merged]

    seen_ids = {getattr(ep, "id", id(ep)) for ep in anchor_results}
    for ep in episodes:
        if getattr(ep, "id", id(ep)) in seen_ids:
            continue
        if (
            query_watch_section
            and getattr(ep, "anchors", None)
            and getattr(ep.anchors, "watch_section", "")
            and ep.anchors.watch_section != query_watch_section
        ):
            continue
        anchor_results.append(ep)
        seen_ids.add(getattr(ep, "id", id(ep)))
    return [], anchor_results


class TestRecallByAnchorScoredPipeline:
    @pytest.mark.asyncio
    async def test_scored_returns_recall_score_objects(self) -> None:
        ep = _make_episode("ep1", department="science")
        em = _make_memory([ep])

        results = await em.recall_by_anchor_scored(department="science")

        assert isinstance(results[0], RecallScore)

    @pytest.mark.asyncio
    async def test_scored_includes_composite_score(self) -> None:
        ep = _make_episode("ep1", department="science")
        em = _make_memory([ep])

        results = await em.recall_by_anchor_scored(department="science")

        assert results[0].composite_score > 0.0

    @pytest.mark.asyncio
    async def test_scored_sorted_by_composite_descending(self) -> None:
        old = _make_episode("old", department="science", timestamp=time.time() - 30 * 86400)
        recent = _make_episode("recent", department="science", timestamp=time.time())
        em = _make_memory([old, recent])

        results = await em.recall_by_anchor_scored(department="science")

        assert [result.episode.id for result in results] == ["recent", "old"]

    @pytest.mark.asyncio
    async def test_scored_applies_anchor_bonus(self) -> None:
        ep = _make_episode("ep1", department="science")
        em = _make_memory([ep])

        results = await em.recall_by_anchor_scored(department="science")

        assert results[0].composite_score >= 0.08

    @pytest.mark.asyncio
    async def test_scored_custom_anchor_bonus(self) -> None:
        ep = _make_episode("ep1", department="science")
        em = _make_memory([ep])

        without_bonus = await em.recall_by_anchor_scored(department="science", anchor_bonus=0.0)
        with_bonus = await em.recall_by_anchor_scored(department="science", anchor_bonus=0.20)

        assert with_bonus[0].composite_score == pytest.approx(
            without_bonus[0].composite_score + 0.20
        )

    @pytest.mark.asyncio
    async def test_scored_empty_results(self) -> None:
        em = _make_memory([])

        results = await em.recall_by_anchor_scored(department="science")

        assert results == []

    @pytest.mark.asyncio
    async def test_scored_with_semantic_query(self) -> None:
        ep = _make_episode("ep1", user_input="warp field report", department="science")
        collection = _FakeCollection({"ids": [["ep1"]], "distances": [[0.25]]})
        em = _make_memory([ep], collection=collection)

        results = await em.recall_by_anchor_scored(
            department="science",
            semantic_query="warp field",
        )

        assert results[0].semantic_similarity == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_scored_without_semantic_query(self) -> None:
        ep = _make_episode("ep1", department="science")
        em = _make_memory([ep], collection=_FakeCollection())

        results = await em.recall_by_anchor_scored(department="science")

        assert results[0].semantic_similarity == 0.0


class TestRecallByAnchorScoredSignals:
    @pytest.mark.asyncio
    async def test_scored_trust_weight_propagated(self) -> None:
        ep = _make_episode("ep1", department="science")
        em = _make_memory([ep])
        trust_network = MagicMock()
        trust_network.get_score.return_value = 0.9

        results = await em.recall_by_anchor_scored(
            agent_id="agent_1",
            department="science",
            trust_network=trust_network,
        )

        assert results[0].trust_weight == 0.9

    @pytest.mark.asyncio
    async def test_scored_hebbian_weight_propagated(self) -> None:
        ep = _make_episode("ep1", department="science")
        em = _make_memory([ep])
        hebbian_router = MagicMock()
        hebbian_router.get_weight.return_value = 0.8

        results = await em.recall_by_anchor_scored(
            agent_id="agent_1",
            department="science",
            hebbian_router=hebbian_router,
            intent_type="direct_message",
        )

        assert results[0].hebbian_weight == 0.8

    @pytest.mark.asyncio
    async def test_scored_recency_weight_computed(self) -> None:
        recent = _make_episode("recent", department="science", timestamp=time.time())
        old = _make_episode("old", department="science", timestamp=time.time() - 30 * 86400)
        em = _make_memory([old, recent])

        results = await em.recall_by_anchor_scored(department="science")
        by_id = {result.episode.id: result for result in results}

        assert by_id["recent"].recency_weight > by_id["old"].recency_weight

    @pytest.mark.asyncio
    async def test_scored_temporal_match_bonus(self) -> None:
        matching = _make_episode("matching", department="science", watch_section="alpha")
        mismatched = _make_episode("mismatched", department="science", watch_section="beta")
        em = _make_memory([mismatched, matching])

        results = await em.recall_by_anchor_scored(
            department="science",
            query_watch_section="alpha",
            anchor_bonus=0.0,
        )
        by_id = {result.episode.id: result for result in results}

        assert by_id["matching"].composite_score > by_id["mismatched"].composite_score


class TestMergeRecall:
    def test_merge_scored_anchor_and_semantic(self) -> None:
        anchor_ep = _make_episode("anchor", department="science")
        semantic_ep = _make_episode("semantic", department="science")

        scored, episodes = _merge_recall(
            [_score(anchor_ep, 0.2)],
            [_score(semantic_ep, 0.9)],
            [semantic_ep],
        )

        assert [result.episode.id for result in scored] == ["semantic", "anchor"]
        assert [episode.id for episode in episodes] == ["semantic", "anchor"]

    def test_merge_deduplicates_by_id(self) -> None:
        ep = _make_episode("same", department="science")

        scored, episodes = _merge_recall([_score(ep, 0.7)], [_score(ep, 0.9)], [ep])

        assert len(scored) == 1
        assert scored[0].composite_score == 0.7
        assert [episode.id for episode in episodes] == ["same"]

    def test_merge_bf155_temporal_filter(self) -> None:
        anchor_ep = _make_episode("anchor", watch_section="alpha")
        mismatched_ep = _make_episode("mismatched", watch_section="beta")

        scored, episodes = _merge_recall(
            [_score(anchor_ep, 0.5)],
            [_score(mismatched_ep, 0.9)],
            [mismatched_ep],
            query_watch_section="alpha",
        )

        assert [result.episode.id for result in scored] == ["anchor"]
        assert [episode.id for episode in episodes] == ["anchor"]

    def test_merge_fallback_unscored(self) -> None:
        anchor_ep = _make_episode("anchor", department="science")
        semantic_ep = _make_episode("semantic", department="science")

        scored, episodes = _merge_recall([anchor_ep], [_score(semantic_ep, 0.9)], [semantic_ep])

        assert scored == []
        assert [episode.id for episode in episodes] == ["anchor", "semantic"]

    def test_merge_empty_anchor(self) -> None:
        semantic_ep = _make_episode("semantic", department="science")

        scored, episodes = _merge_recall(None, [_score(semantic_ep, 0.9)], [semantic_ep])

        assert [result.episode.id for result in scored] == ["semantic"]
        assert [episode.id for episode in episodes] == ["semantic"]

    def test_merge_empty_semantic(self) -> None:
        anchor_ep = _make_episode("anchor", department="science")

        scored, episodes = _merge_recall([_score(anchor_ep, 0.7)], [], [])

        assert [result.episode.id for result in scored] == ["anchor"]
        assert [episode.id for episode in episodes] == ["anchor"]