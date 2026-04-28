"""AD-579b: Tests for temporal validity windows."""

from __future__ import annotations

import time

import pytest

from probos.cognitive.episodic import EpisodicMemory, _episode_validity_check
from probos.config import TemporalValidityConfig
from probos.types import AnchorFrame, Episode


def _episode(
    user_input: str = "Worf's trust is 0.72",
    *,
    valid_from: float = 0.0,
    valid_until: float = 0.0,
    timestamp: float = 100.0,
) -> Episode:
    return Episode(
        user_input=user_input,
        timestamp=timestamp,
        agent_ids=["agent-001"],
        outcomes=[{"intent": "status", "success": True}],
        valid_from=valid_from,
        valid_until=valid_until,
    )


def test_episode_validity_fields_default() -> None:
    episode = Episode()

    assert episode.valid_from == 0.0
    assert episode.valid_until == 0.0


def test_anchor_validity_fields_default() -> None:
    anchor = AnchorFrame()

    assert anchor.temporal_validity_start == 0.0
    assert anchor.temporal_validity_end == 0.0


def test_validity_check_excludes_expired() -> None:
    episode = _episode(valid_until=90.0)

    assert _episode_validity_check(episode, 100.0) is False


def test_validity_check_includes_valid() -> None:
    episode = _episode(valid_from=50.0, valid_until=150.0)

    assert _episode_validity_check(episode, 100.0) is True


def test_validity_zero_means_no_expiry() -> None:
    episode = _episode(valid_until=0.0)

    far_future = time.time() + 10_000_000.0

    assert _episode_validity_check(episode, far_future) is True


def test_valid_from_future_excluded() -> None:
    episode = _episode(valid_from=150.0, valid_until=0.0)

    assert _episode_validity_check(episode, 100.0) is False


def test_chromadb_metadata_roundtrip() -> None:
    episode = _episode(valid_from=100.0, valid_until=200.0)

    metadata = EpisodicMemory._episode_to_metadata(episode)
    restored = EpisodicMemory._metadata_to_episode(episode.id, episode.user_input, metadata)

    assert metadata["valid_from"] == 100.0
    assert metadata["valid_until"] == 200.0
    assert restored.valid_from == 100.0
    assert restored.valid_until == 200.0


@pytest.mark.asyncio
async def test_recall_weighted_valid_at_filters(tmp_path) -> None:
    memory = EpisodicMemory(str(tmp_path / "ep.db"))
    valid_episode = _episode("current trust status", valid_until=150.0)
    expired_episode = _episode("old trust status", valid_until=90.0)

    async def fake_scored(agent_id: str, query: str, k: int) -> list[tuple[Episode, float]]:
        return [(valid_episode, 0.9), (expired_episode, 0.9)]

    async def fake_keyword(query: str, k: int) -> list[tuple[str, float]]:
        return []

    memory.recall_for_agent_scored = fake_scored  # type: ignore[method-assign]
    memory.keyword_search = fake_keyword  # type: ignore[method-assign]

    results = await memory.recall_weighted("agent-001", "trust status", valid_at=100.0)

    assert [score.episode.user_input for score in results] == ["current trust status"]


def test_validity_config_defaults() -> None:
    config = TemporalValidityConfig()

    assert config.enabled is True
    assert config.default_validity_hours == 0.0


@pytest.mark.asyncio
async def test_mixed_valid_invalid_episodes(tmp_path) -> None:
    memory = EpisodicMemory(str(tmp_path / "ep.db"))
    valid_forever = _episode("standing fact", valid_until=0.0)
    valid_window = _episode("current fact", valid_from=50.0, valid_until=150.0)
    expired = _episode("expired fact", valid_until=90.0)
    future = _episode("future fact", valid_from=150.0)

    async def fake_scored(agent_id: str, query: str, k: int) -> list[tuple[Episode, float]]:
        return [
            (valid_forever, 0.9),
            (valid_window, 0.9),
            (expired, 0.9),
            (future, 0.9),
        ]

    async def fake_keyword(query: str, k: int) -> list[tuple[str, float]]:
        return []

    memory.recall_for_agent_scored = fake_scored  # type: ignore[method-assign]
    memory.keyword_search = fake_keyword  # type: ignore[method-assign]

    results = await memory.recall_valid_at(100.0, "agent-001", "fact")

    assert [score.episode.user_input for score in results] == [
        "standing fact",
        "current fact",
    ]