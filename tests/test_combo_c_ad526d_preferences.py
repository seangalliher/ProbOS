"""Combo C AD-526d: GamePreferenceTracker tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from probos.events import EventType
from probos.recreation.preferences import GamePreferenceTracker


def test_record_game_increments_and_emits():
    tracker = GamePreferenceTracker()
    emit = MagicMock()
    tracker.set_event_callback(emit)

    tracker.record_game("agent-1", "chess")
    tracker.record_game("agent-1", "chess")

    assert tracker.get_preferences("agent-1") == {"chess": 2}
    assert emit.call_count == 2
    et, payload = emit.call_args_list[1][0]
    assert et == EventType.GAME_PREFERENCE_RECORDED
    assert payload == {"agent_id": "agent-1", "game_type": "chess", "count": 2}


def test_get_preferences_returns_frozen_copy():
    tracker = GamePreferenceTracker()
    tracker.record_game("agent-1", "go")

    snap = tracker.get_preferences("agent-1")
    snap["go"] = 99  # mutate caller copy
    snap["poker"] = 1

    # internal state untouched
    assert tracker.get_preferences("agent-1") == {"go": 1}


def test_top_game_for_returns_max():
    tracker = GamePreferenceTracker()
    tracker.record_game("a", "chess")
    tracker.record_game("a", "chess")
    tracker.record_game("a", "go")

    assert tracker.top_game_for("a") == "chess"
    assert tracker.top_game_for("unknown") is None


def test_record_game_unknown_agent_creates_entry():
    tracker = GamePreferenceTracker()
    tracker.record_game("new-agent", "chess")

    assert tracker.get_preferences("new-agent") == {"chess": 1}
    # empty / falsy inputs are no-ops
    tracker.record_game("", "chess")
    tracker.record_game("new-agent", "")
    assert tracker.get_preferences("new-agent") == {"chess": 1}
