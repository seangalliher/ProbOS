"""AD-574: Episodic decay reconsolidation scheduling tests."""

from __future__ import annotations

import time
from typing import Any

import pytest

from probos.cognitive.dreaming import DreamingEngine
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.reconsolidation import ReconsolidationEntry, ReconsolidationScheduler
from probos.config import DreamingConfig
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import HebbianRouter
from probos.types import Episode


class _FakeReconsolidationConfig:
    def __init__(
        self,
        *,
        enabled: bool = True,
        base_intervals_hours: list[float] | None = None,
        importance_scale_factor: float = 0.1,
        max_scheduled: int = 500,
    ) -> None:
        self.enabled = enabled
        self.base_intervals_hours = base_intervals_hours or [1.0, 6.0, 24.0, 72.0, 168.0, 720.0]
        self.importance_scale_factor = importance_scale_factor
        self.max_scheduled = max_scheduled


@pytest.fixture
def scheduler() -> ReconsolidationScheduler:
    return ReconsolidationScheduler(config=_FakeReconsolidationConfig())


def _episode(episode_id: str = "ep-high", *, importance: int = 8) -> Episode:
    return Episode(
        id=episode_id,
        timestamp=time.time(),
        user_input=f"important diagnostic memory {episode_id}",
        outcomes=[{"intent": "diagnose", "success": True}],
        agent_ids=["agent-recon"],
        importance=importance,
    )


class _FakeEpisodicMemory:
    def __init__(self, episodes: list[Episode]) -> None:
        self._episodes = episodes

    async def get_stats(self) -> dict[str, Any]:
        return {"total": len(self._episodes)}

    async def recent(self, k: int = 10) -> list[Episode]:
        return list(reversed(self._episodes[-k:]))

    async def get_embeddings(self, episode_ids: list[str]) -> dict[str, list[float]]:
        return {episode_id: [1.0, 0.0] for episode_id in episode_ids}


class _FakeDreamReconsolidationScheduler:
    def __init__(self, due_ids: list[str]) -> None:
        self.due_ids = due_ids
        self.reviewed: list[tuple[str, bool]] = []

    def get_due_reviews(self, now: float | None = None, limit: int = 10) -> list[str]:
        return self.due_ids[:limit]

    def mark_reviewed(self, episode_id: str, retained: bool) -> None:
        self.reviewed.append((episode_id, retained))


def test_schedule_review_adds_entry(scheduler: ReconsolidationScheduler) -> None:
    scheduler.schedule_review("ep-1", importance=8)

    entry = scheduler._schedule["ep-1"]

    assert isinstance(entry, ReconsolidationEntry)
    assert entry.episode_id == "ep-1"
    assert entry.importance == 8
    assert scheduler.scheduled_count == 1


def test_get_due_reviews_returns_due(scheduler: ReconsolidationScheduler) -> None:
    scheduler.schedule_review("older", importance=8)
    scheduler.schedule_review("newer", importance=8)
    scheduler._schedule["older"].next_review_at = 10.0
    scheduler._schedule["newer"].next_review_at = 20.0

    result = scheduler.get_due_reviews(now=30.0, limit=10)

    assert result == ["older", "newer"]


def test_mark_reviewed_extends_interval(scheduler: ReconsolidationScheduler) -> None:
    scheduler.schedule_review("ep-1", importance=8)
    scheduler._schedule["ep-1"].next_review_at = time.time() - 1.0

    scheduler.mark_reviewed("ep-1", retained=True)

    entry = scheduler._schedule["ep-1"]
    assert entry.review_count == 1
    assert entry.retained is True
    assert entry.next_review_at > time.time()


def test_mark_not_retained_flags_episode(scheduler: ReconsolidationScheduler) -> None:
    scheduler.schedule_review("ep-1", importance=8)

    scheduler.mark_reviewed("ep-1", retained=False)

    assert scheduler._schedule["ep-1"].retained is False
    assert scheduler.get_due_reviews(now=time.time() + 10_000.0) == []


def test_ebbinghaus_intervals_progressive() -> None:
    scheduler = ReconsolidationScheduler(
        config=_FakeReconsolidationConfig(base_intervals_hours=[1.0, 6.0, 24.0]),
    )

    intervals = [scheduler._compute_next_review(count, importance=5) for count in range(3)]

    assert intervals[0] < intervals[1] < intervals[2]


def test_importance_scaling_shortens_interval() -> None:
    scheduler = ReconsolidationScheduler(config=_FakeReconsolidationConfig())

    low_importance = scheduler._compute_next_review(review_count=0, importance=1)
    high_importance = scheduler._compute_next_review(review_count=0, importance=10)

    assert high_importance < low_importance


def test_max_scheduled_cap() -> None:
    scheduler = ReconsolidationScheduler(config=_FakeReconsolidationConfig(max_scheduled=2))

    scheduler.schedule_review("ep-1", importance=8)
    scheduler.schedule_review("ep-2", importance=8)
    scheduler.schedule_review("ep-3", importance=8)

    assert scheduler.scheduled_count == 2
    assert "ep-3" not in scheduler._schedule


def test_no_due_reviews_when_future(scheduler: ReconsolidationScheduler) -> None:
    scheduler.schedule_review("ep-1", importance=8)

    assert scheduler.get_due_reviews(now=0.0) == []


def test_config_disabled_no_ops() -> None:
    scheduler = ReconsolidationScheduler(config=_FakeReconsolidationConfig(enabled=False))

    scheduler.schedule_review("ep-1", importance=8)

    result = scheduler.get_due_reviews(now=time.time() + 10_000.0)

    assert scheduler.scheduled_count == 0
    assert result == []


@pytest.mark.asyncio
async def test_auto_schedule_high_importance(tmp_path) -> None:
    memory = EpisodicMemory(str(tmp_path / "episodes.db"), max_episodes=100)
    scheduler = ReconsolidationScheduler(config=_FakeReconsolidationConfig())
    await memory.start()
    try:
        memory.set_reconsolidation_scheduler(scheduler)

        await memory.store(_episode(importance=8))

        assert scheduler.scheduled_count == 1
        assert "ep-high" in scheduler._schedule
    finally:
        await memory.stop()


def test_multiple_reviews_progressive() -> None:
    scheduler = ReconsolidationScheduler(
        config=_FakeReconsolidationConfig(base_intervals_hours=[1.0, 6.0, 24.0]),
    )
    scheduler.schedule_review("ep-1", importance=5)

    scheduler.mark_reviewed("ep-1", retained=True)
    first_interval = scheduler._schedule["ep-1"].next_review_at - scheduler._schedule["ep-1"].last_reviewed_at
    scheduler.mark_reviewed("ep-1", retained=True)
    second_interval = scheduler._schedule["ep-1"].next_review_at - scheduler._schedule["ep-1"].last_reviewed_at

    assert first_interval < second_interval


@pytest.mark.asyncio
async def test_dream_step_integration() -> None:
    episodes = [_episode(f"ep-{idx}", importance=8) for idx in range(5)]
    memory = _FakeEpisodicMemory(episodes)
    scheduler = _FakeDreamReconsolidationScheduler(due_ids=["ep-0", "ep-1"])
    engine = DreamingEngine(
        router=HebbianRouter(),
        trust_network=TrustNetwork(),
        episodic_memory=memory,
        config=DreamingConfig(replay_episode_count=10),
        reconsolidation_scheduler=scheduler,
    )

    await engine.dream_cycle()

    assert scheduler.reviewed == [("ep-0", True), ("ep-1", True)]