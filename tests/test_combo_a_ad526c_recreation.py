"""Combo A AD-526c: Recreation System Extensions tests."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from probos.events import EventType
from probos.recreation.engine import TicTacToeEngine
from probos.recreation.metadata import GameMetadata
from probos.recreation.service import RecreationService


def test_recreation_register_engine_with_metadata_stores_both():
    """register_engine accepts optional GameMetadata + stores in _metadata dict."""
    svc = RecreationService(emit_event_fn=MagicMock())
    engine = TicTacToeEngine()  # already auto-registered by __init__
    meta = GameMetadata(
        description="Tic-tac-toe game",
        agent_count_min=2,
        agent_count_max=2,
        registered_at=time.time(),
    )
    # Re-register with explicit metadata
    svc.register_engine(engine, metadata=meta)
    stored = svc.get_metadata(engine.game_type)
    assert stored is not None
    assert stored.description == "Tic-tac-toe game"
    assert stored.agent_count_min == 2


def test_recreation_register_engine_emits_event():
    emit = MagicMock()
    svc = RecreationService(emit_event_fn=emit)
    # __init__ auto-registers TicTacToeEngine -> 1 emit
    assert emit.call_count >= 1
    # Find the RECREATION_GAME_REGISTERED call
    found = False
    for call in emit.call_args_list:
        et, payload = call.args
        if et == EventType.RECREATION_GAME_REGISTERED:
            found = True
            assert "game_type" in payload
            assert "agent_count_min" in payload
    assert found


def test_recreation_default_game_property_returns_init_value():
    svc = RecreationService(emit_event_fn=MagicMock(), default_game="custom_game")
    assert svc.default_game == "custom_game"
    # Default falls back when not set
    svc2 = RecreationService(emit_event_fn=MagicMock())
    assert svc2.default_game == "tictactoe"
