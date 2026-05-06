"""AD-526e: SpectatorRegistry tests."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from probos.events import EventType
from probos.recreation.spectators import SpectatorRegistry


# ----------------------------------------------------------------------
# Section 1 — EventType existence
# ----------------------------------------------------------------------


def test_event_type_recreation_spectator_joined_exists() -> None:
    assert EventType.RECREATION_SPECTATOR_JOINED.value == "recreation_spectator_joined"


def test_event_type_recreation_spectator_commentary_exists() -> None:
    assert (
        EventType.RECREATION_SPECTATOR_COMMENTARY.value
        == "recreation_spectator_commentary"
    )


# ----------------------------------------------------------------------
# Section 2 — add_spectator / remove_spectator behavior
# ----------------------------------------------------------------------


def test_add_spectator_first_call_returns_true_and_emits() -> None:
    emit = MagicMock()
    reg = SpectatorRegistry()
    reg.set_event_callback(emit)
    assert reg.add_spectator("g1", "a1") is True
    assert emit.call_count == 1
    args, _ = emit.call_args
    assert args[0] is EventType.RECREATION_SPECTATOR_JOINED
    assert args[1] == {"game_id": "g1", "agent_id": "a1", "spectator_count": 1}


def test_add_spectator_duplicate_returns_false_and_does_not_re_emit() -> None:
    emit = MagicMock()
    reg = SpectatorRegistry()
    reg.set_event_callback(emit)
    assert reg.add_spectator("g1", "a1") is True
    assert reg.add_spectator("g1", "a1") is False
    assert emit.call_count == 1


def test_remove_spectator_present_returns_true() -> None:
    reg = SpectatorRegistry()
    reg.add_spectator("g1", "a1")
    assert reg.remove_spectator("g1", "a1") is True
    assert reg.get_spectators("g1") == ()


def test_remove_spectator_absent_returns_false() -> None:
    reg = SpectatorRegistry()
    assert reg.remove_spectator("g1", "a1") is False
    reg.add_spectator("g1", "a1")
    assert reg.remove_spectator("g1", "a2") is False


# ----------------------------------------------------------------------
# Section 3 — get_spectators ordering + frozen contract
# ----------------------------------------------------------------------


def test_get_spectators_returns_frozen_tuple_in_insertion_order() -> None:
    reg = SpectatorRegistry()
    reg.add_spectator("g1", "a1")
    reg.add_spectator("g1", "a2")
    reg.add_spectator("g1", "a3")
    spectators = reg.get_spectators("g1")
    assert isinstance(spectators, tuple)
    assert spectators == ("a1", "a2", "a3")


def test_get_spectators_unknown_game_returns_empty_tuple() -> None:
    reg = SpectatorRegistry()
    assert reg.get_spectators("nonexistent") == ()


# ----------------------------------------------------------------------
# Section 4 — record_commentary + get_commentary
# ----------------------------------------------------------------------


def test_record_commentary_stores_entry_and_emits_event() -> None:
    emit = MagicMock()
    reg = SpectatorRegistry()
    reg.set_event_callback(emit)
    reg.record_commentary("g1", "a1", "Nice move!")
    entries = reg.get_commentary("g1")
    assert len(entries) == 1
    assert entries[0]["agent_id"] == "a1"
    assert entries[0]["text"] == "Nice move!"
    assert isinstance(entries[0]["timestamp"], float)
    assert emit.call_count == 1
    args, _ = emit.call_args
    assert args[0] is EventType.RECREATION_SPECTATOR_COMMENTARY
    assert args[1] == {"game_id": "g1", "agent_id": "a1", "comment_count": 1}


def test_record_commentary_empty_inputs_no_op() -> None:
    emit = MagicMock()
    reg = SpectatorRegistry()
    reg.set_event_callback(emit)
    reg.record_commentary("", "a1", "x")
    reg.record_commentary("g1", "", "x")
    reg.record_commentary("g1", "a1", "")
    reg.record_commentary("g1", "a1", "   ")  # whitespace-only suppressed
    assert reg.get_commentary("g1") == ()
    assert emit.call_count == 0


def test_get_commentary_returns_frozen_tuple_with_timestamp() -> None:
    reg = SpectatorRegistry()
    reg.record_commentary("g1", "a1", "first")
    reg.record_commentary("g1", "a2", "second")
    entries = reg.get_commentary("g1")
    assert isinstance(entries, tuple)
    assert len(entries) == 2
    assert entries[0]["text"] == "first"
    assert entries[1]["text"] == "second"
    assert entries[0]["timestamp"] <= entries[1]["timestamp"]


# ----------------------------------------------------------------------
# Section 5 — clear_game lifecycle
# ----------------------------------------------------------------------


def test_clear_game_drops_spectators_and_commentary() -> None:
    reg = SpectatorRegistry()
    reg.add_spectator("g1", "a1")
    reg.add_spectator("g1", "a2")
    reg.record_commentary("g1", "a1", "hi")
    reg.clear_game("g1")
    assert reg.get_spectators("g1") == ()
    assert reg.get_commentary("g1") == ()
    # Safe to call on unknown game_id
    reg.clear_game("nonexistent")


# ----------------------------------------------------------------------
# Section 6 — emit-failure log-and-degrade
# ----------------------------------------------------------------------


def test_emit_failure_logged_and_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def bad_emit(*_args, **_kwargs):
        raise RuntimeError("emitter exploded")

    reg = SpectatorRegistry()
    reg.set_event_callback(bad_emit)
    with caplog.at_level(logging.WARNING):
        # State mutation must succeed despite emit failure
        assert reg.add_spectator("g1", "a1") is True
        reg.record_commentary("g1", "a1", "comment")
    assert reg.get_spectators("g1") == ("a1",)
    assert len(reg.get_commentary("g1")) == 1
    assert any("AD-526e" in rec.message for rec in caplog.records)


# ----------------------------------------------------------------------
# Section 7 — runtime wiring (no-boot smoke)
# ----------------------------------------------------------------------


def test_runtime_wires_recreation_spectator_registry_with_callback() -> None:
    """Verify runtime.py constructs SpectatorRegistry + binds emit_event.

    Reads runtime.py source directly to avoid booting a real ProbOSRuntime
    (per Wave 13/66/67 fixture precedent — full-runtime fixtures explode
    wave-gate runtime budget).
    """
    from pathlib import Path

    runtime_src = Path(__file__).resolve().parents[1] / "src" / "probos" / "runtime.py"
    text = runtime_src.read_text(encoding="utf-8")
    assert "from probos.recreation.spectators import SpectatorRegistry" in text
    assert (
        "self.recreation_spectator_registry: SpectatorRegistry = SpectatorRegistry()"
        in text
    )
    assert (
        "self.recreation_spectator_registry.set_event_callback(self.emit_event)"
        in text
    )
