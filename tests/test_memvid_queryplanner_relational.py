"""Tests for Memvid pattern 1 — QueryPlanner relational lookup.

Wave 130. Closes #490 (QueryPlanner only; VersionRelation enum + per-engine
version are out of scope).
"""

from __future__ import annotations

from typing import Any

import pytest

from probos.cognitive.query_planner import QueryPlan, QueryPlanner


class _FakeEpisodic:
    """Minimal stub mimicking EpisodicMemory's recall + recall_by_anchor."""

    def __init__(
        self,
        anchor_results: list[Any] | None = None,
        recall_results: list[Any] | None = None,
        anchor_raises: bool = False,
    ) -> None:
        self.anchor_results = anchor_results or []
        self.recall_results = recall_results or []
        self.anchor_raises = anchor_raises
        self.anchor_calls: list[dict[str, Any]] = []
        self.recall_calls: list[tuple[str, int]] = []

    async def recall_by_anchor(self, **kwargs: Any) -> list[Any]:
        self.anchor_calls.append(kwargs)
        if self.anchor_raises:
            raise RuntimeError("simulated anchor lookup failure")
        return list(self.anchor_results)

    async def recall(self, query: str, k: int = 5) -> list[Any]:
        self.recall_calls.append((query, k))
        return list(self.recall_results)


def test_classify_who_works_at_returns_relational_who_with_department() -> None:
    plan = QueryPlanner().classify("who works at engineering")
    assert plan.shape == "RELATIONAL_WHO"
    assert plan.relational is True
    assert plan.anchor_kwargs.get("department") == "engineering"
    assert "semantic_query" in plan.anchor_kwargs


def test_classify_who_works_at_multiword_uses_participants() -> None:
    plan = QueryPlanner().classify("who works at the bridge crew")
    assert plan.shape == "RELATIONAL_WHO"
    assert plan.relational is True
    assert "participants" in plan.anchor_kwargs
    assert plan.anchor_kwargs["participants"] == ["the bridge crew"]


def test_classify_where_is_returns_relational_where_with_channel() -> None:
    plan = QueryPlanner().classify("where is the standup notes")
    assert plan.shape == "RELATIONAL_WHERE"
    assert plan.relational is True
    assert plan.anchor_kwargs.get("channel") == "the standup notes"


def test_classify_when_did_returns_relational_when() -> None:
    plan = QueryPlanner().classify("when did the deployment happen")
    assert plan.shape == "RELATIONAL_WHEN"
    assert plan.relational is True
    assert "semantic_query" in plan.anchor_kwargs


def test_classify_plain_query_returns_semantic() -> None:
    plan = QueryPlanner().classify("what is consensus")
    assert plan.shape == "SEMANTIC"
    assert plan.relational is False


def test_classify_empty_query_returns_semantic() -> None:
    plan = QueryPlanner().classify("")
    assert plan.shape == "SEMANTIC"
    assert plan.relational is False
    plan2 = QueryPlanner().classify("   ")
    assert plan2.shape == "SEMANTIC"


def test_classify_who_works_at_handles_trailing_punctuation_and_words() -> None:
    plan = QueryPlanner().classify("who works at engineering, please?")
    assert plan.shape == "RELATIONAL_WHO"
    # Trailing "please?" and "," must be stripped.
    assert plan.anchor_kwargs.get("department") == "engineering"


@pytest.mark.asyncio
async def test_recall_with_fallback_uses_anchor_when_relational_hits() -> None:
    fake = _FakeEpisodic(
        anchor_results=["ep1", "ep2"], recall_results=["sem1"]
    )
    qp = QueryPlanner()

    results = await qp.recall_with_fallback(fake, "who works at engineering", k=5)

    assert results == ["ep1", "ep2"]
    assert len(fake.anchor_calls) == 1
    assert fake.recall_calls == []  # never reached


@pytest.mark.asyncio
async def test_recall_with_fallback_falls_back_when_anchor_empty() -> None:
    fake = _FakeEpisodic(anchor_results=[], recall_results=["sem1", "sem2"])
    qp = QueryPlanner()

    results = await qp.recall_with_fallback(fake, "who works at marketing", k=3)

    assert results == ["sem1", "sem2"]
    assert len(fake.anchor_calls) == 1
    assert fake.recall_calls == [("who works at marketing", 3)]


@pytest.mark.asyncio
async def test_recall_with_fallback_falls_back_on_anchor_exception(caplog) -> None:
    fake = _FakeEpisodic(anchor_raises=True, recall_results=["sem1"])
    qp = QueryPlanner()

    results = await qp.recall_with_fallback(fake, "where is the brief", k=4)

    assert results == ["sem1"]
    assert fake.recall_calls == [("where is the brief", 4)]
    # Anchor failure must surface as a warning, not silent.
    assert any("anchor lookup raised" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_recall_with_fallback_uses_semantic_for_non_relational() -> None:
    fake = _FakeEpisodic(recall_results=["sem1"])
    qp = QueryPlanner()

    results = await qp.recall_with_fallback(fake, "explain the reactor design", k=2)

    assert results == ["sem1"]
    assert fake.anchor_calls == []  # classifier said SEMANTIC
    assert fake.recall_calls == [("explain the reactor design", 2)]


def test_query_plan_is_immutable() -> None:
    plan = QueryPlan(shape="SEMANTIC", relational=False)
    # frozen dataclass — assignment must raise.
    with pytest.raises(Exception):
        plan.shape = "RELATIONAL_WHO"  # type: ignore[misc]


def test_query_planner_config_defaults() -> None:
    from probos.config import QueryPlannerConfig

    cfg = QueryPlannerConfig()
    assert cfg.enabled is False  # convention #14
    assert cfg.fall_through_on_empty is True
