"""AD-444: Knowledge confidence scoring tests."""

from __future__ import annotations

import pytest

from probos.config import ConfidenceConfig
from probos.knowledge.confidence_tracker import ConfidenceTracker
from probos.knowledge.records_store import RecordsStore


class _FakeRecordsConfig:
    repo_path = "unused"
    auto_commit = False


def test_default_confidence() -> None:
    tracker = ConfidenceTracker(ConfidenceConfig())

    confidence = tracker.initialize_entry("notebooks/entry.md")

    assert confidence == 0.5
    assert tracker.get_confidence("notebooks/entry.md") == 0.5


def test_confirm_increases() -> None:
    tracker = ConfidenceTracker(ConfidenceConfig())

    confidence = tracker.confirm("notebooks/entry.md")

    assert confidence == pytest.approx(0.65)


def test_contradict_decreases() -> None:
    tracker = ConfidenceTracker(ConfidenceConfig())

    confidence = tracker.contradict("notebooks/entry.md")

    assert confidence == pytest.approx(0.25)


def test_confidence_floor_zero() -> None:
    tracker = ConfidenceTracker(ConfidenceConfig())

    for _ in range(10):
        confidence = tracker.contradict("notebooks/entry.md")

    assert confidence == 0.0


def test_confidence_cap_one() -> None:
    tracker = ConfidenceTracker(ConfidenceConfig())

    for _ in range(10):
        confidence = tracker.confirm("notebooks/entry.md")

    assert confidence == 1.0


def test_auto_supersede_below_threshold() -> None:
    tracker = ConfidenceTracker(ConfidenceConfig())
    for _ in range(2):
        tracker.contradict("notebooks/entry.md")

    assert tracker.auto_supersede_check("notebooks/entry.md") is True


def test_presentation_tier_auto_apply() -> None:
    tracker = ConfidenceTracker(ConfidenceConfig())
    for _ in range(2):
        tracker.confirm("notebooks/entry.md")

    assert tracker.get_presentation_tier("notebooks/entry.md") == "auto_apply"


def test_presentation_tier_with_caveat() -> None:
    tracker = ConfidenceTracker(ConfidenceConfig())

    assert tracker.get_presentation_tier("notebooks/entry.md") == "with_caveat"


def test_presentation_tier_suppress() -> None:
    tracker = ConfidenceTracker(ConfidenceConfig())
    tracker.contradict("notebooks/entry.md")

    assert tracker.get_presentation_tier("notebooks/entry.md") == "suppress"


def test_config_disabled() -> None:
    tracker = ConfidenceTracker(ConfidenceConfig(enabled=False))

    assert tracker.initialize_entry("notebooks/entry.md") == 0.5
    assert tracker.confirm("notebooks/entry.md") == 0.5
    assert tracker.contradict("notebooks/entry.md") == 0.5
    assert tracker.get_confidence("notebooks/entry.md") == 0.5
    assert tracker.auto_supersede_check("notebooks/entry.md") is False
    assert tracker.get_presentation_tier("notebooks/entry.md") == "with_caveat"
    assert tracker.get_all_entries() == {}


def test_multiple_confirmations() -> None:
    tracker = ConfidenceTracker(ConfidenceConfig())

    for _ in range(5):
        confidence = tracker.confirm("notebooks/entry.md")

    assert confidence == 1.0
    entry = tracker.get_all_entries()["notebooks/entry.md"]
    assert entry.confirmations == 5


@pytest.mark.asyncio
async def test_records_store_confirm_contradict() -> None:
    store = RecordsStore(_FakeRecordsConfig())
    tracker = ConfidenceTracker(ConfidenceConfig())
    store.set_confidence_tracker(tracker)

    confirmed = await store.confirm_entry("notebooks/entry.md")
    contradicted = await store.contradict_entry("notebooks/entry.md")

    assert confirmed == pytest.approx(0.65)
    assert contradicted == pytest.approx(0.4)
