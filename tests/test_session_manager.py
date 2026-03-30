"""Tests for SessionManager (AD-519)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from rich.console import Console
from io import StringIO

from probos.experience.commands.session import SessionManager


@pytest.fixture
def console():
    return Console(file=StringIO(), force_terminal=True, width=120)


def get_output(console: Console) -> str:
    console.file.seek(0)
    return console.file.read()


@pytest.fixture
def mock_runtime():
    rt = MagicMock()
    rt.callsign_registry.resolve.return_value = None
    rt.episodic_memory = None
    rt.intent_bus.send = AsyncMock(return_value=None)
    return rt


class TestSessionManager:
    def test_initially_inactive(self):
        sm = SessionManager()
        assert not sm.active
        assert sm.callsign is None
        assert sm.agent_id is None

    def test_active_property(self):
        sm = SessionManager()
        sm.callsign = "Echo"
        assert sm.active

    @pytest.mark.asyncio
    async def test_handle_at_unknown_callsign(self, console, mock_runtime):
        sm = SessionManager()
        mock_runtime.callsign_registry.resolve.return_value = None
        await sm.handle_at_parsed("unknown", "hello", mock_runtime, console)
        output = get_output(console)
        assert "Unknown crew member" in output
        assert not sm.active

    @pytest.mark.asyncio
    async def test_handle_at_not_on_duty(self, console, mock_runtime):
        sm = SessionManager()
        mock_runtime.callsign_registry.resolve.return_value = {
            "callsign": "Echo",
            "agent_id": None,
            "agent_type": "analyst",
            "department": "science",
        }
        await sm.handle_at_parsed("echo", "hello", mock_runtime, console)
        output = get_output(console)
        assert "not currently on duty" in output
        assert not sm.active

    @pytest.mark.asyncio
    async def test_handle_at_enter_session(self, console, mock_runtime):
        sm = SessionManager()
        mock_runtime.callsign_registry.resolve.return_value = {
            "callsign": "Echo",
            "agent_id": "agent-123",
            "agent_type": "analyst",
            "department": "science",
        }
        await sm.handle_at_parsed("echo", "", mock_runtime, console)
        assert sm.active
        assert sm.callsign == "Echo"
        assert sm.agent_id == "agent-123"
        output = get_output(console)
        assert "1:1" in output

    @pytest.mark.asyncio
    async def test_handle_message_dispatches_intent(self, console, mock_runtime):
        sm = SessionManager()
        sm.callsign = "Echo"
        sm.agent_id = "agent-123"
        sm.agent_type = "analyst"
        sm.department = "science"

        result = MagicMock()
        result.result = "Test response"
        mock_runtime.intent_bus.send = AsyncMock(return_value=result)

        await sm.handle_message("hello there", mock_runtime, console)
        output = get_output(console)
        assert "Test response" in output
        assert len(sm.history) == 2

    def test_exit_session(self, console):
        sm = SessionManager()
        sm.callsign = "Echo"
        sm.agent_id = "agent-123"
        sm.exit_session(console)
        assert not sm.active
        output = get_output(console)
        assert "bridge" in output.lower()

    def test_exit_session_already_on_bridge(self, console):
        sm = SessionManager()
        sm.exit_session(console)
        output = get_output(console)
        assert "already" in output.lower()
