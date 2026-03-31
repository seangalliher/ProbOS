"""Tests for AD-397: 1:1 session mode via @callsign addressing."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.crew_profile import CallsignRegistry
from probos.runtime import ProbOSRuntime
from probos.types import IntentMessage, IntentResult


def _make_shell(session_agent_id="scout-123"):
    """Create a ProbOSShell with mocked runtime for session testing."""
    from probos.experience.shell import ProbOSShell
    from rich.console import Console

    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.registry = MagicMock()
    runtime.registry.count = 5
    runtime.registry.all.return_value = []

    # CallsignRegistry
    cr = CallsignRegistry()
    cr.load_from_profiles()
    mock_agent = MagicMock()
    mock_agent.id = session_agent_id
    mock_agent.is_alive = True
    mock_reg = MagicMock()
    mock_reg.get_by_pool.return_value = [mock_agent]
    cr.bind_registry(mock_reg)
    runtime.callsign_registry = cr

    # IntentBus
    send_result = IntentResult(
        intent_id="test",
        agent_id=session_agent_id,
        success=True,
        result="Aye, Captain.",
        confidence=0.9,
    )
    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = AsyncMock(return_value=send_result)

    # EpisodicMemory
    runtime.episodic_memory = None

    # Trust network (for _compute_health)
    runtime.trust_network = MagicMock()
    runtime.trust_network.all_scores.return_value = {}

    # self_mod_pipeline
    runtime.self_mod_pipeline = None

    # escalation_manager
    runtime.escalation_manager = None

    console = Console(file=MagicMock(), force_terminal=True)
    shell = ProbOSShell(runtime=runtime, console=console)
    return shell, runtime


class TestAtPrefixRouting:
    """Test @callsign enters 1:1 session mode."""

    @pytest.mark.asyncio
    async def test_at_prefix_enters_session(self):
        """@wesley sets session state on the shell."""
        shell, _ = _make_shell()
        await shell.execute_command("@wesley")
        assert shell._session_callsign == "Wesley"
        assert shell._session_agent_type == "scout"
        assert shell._session_department == "science"
        assert shell._session_agent_id == "scout-123"

    @pytest.mark.asyncio
    async def test_at_with_message(self):
        """@wesley report enters session AND dispatches 'report'."""
        shell, runtime = _make_shell()
        await shell.execute_command("@wesley report")
        assert shell._session_callsign == "Wesley"
        runtime.intent_bus.send.assert_awaited_once()
        call_args = runtime.intent_bus.send.call_args[0][0]
        assert call_args.intent == "direct_message"
        assert call_args.params["text"] == "report"

    @pytest.mark.asyncio
    async def test_unknown_callsign_shows_error(self):
        """@picard shows error."""
        shell, _ = _make_shell()
        await shell.execute_command("@picard")
        assert shell._session_callsign is None

    @pytest.mark.asyncio
    async def test_session_routes_to_agent(self):
        """During session, NL input dispatches to session agent."""
        shell, runtime = _make_shell()
        await shell.execute_command("@wesley")
        runtime.intent_bus.send.reset_mock()
        await shell.execute_command("run a scan")
        runtime.intent_bus.send.assert_awaited_once()
        call_args = runtime.intent_bus.send.call_args[0][0]
        assert call_args.params["text"] == "run a scan"
        assert call_args.target_agent_id == "scout-123"


class TestBridgeCommand:
    """Test /bridge exits session."""

    @pytest.mark.asyncio
    async def test_bridge_exits_session(self):
        """/bridge clears session state."""
        shell, _ = _make_shell()
        await shell.execute_command("@wesley")
        assert shell._session_callsign == "Wesley"
        await shell.execute_command("/bridge")
        assert shell._session_callsign is None
        assert shell._session_agent_id is None
        assert shell._session_history == []

    @pytest.mark.asyncio
    async def test_bridge_clears_history(self):
        """/bridge clears _session_history."""
        shell, _ = _make_shell()
        await shell.execute_command("@wesley hello")
        assert len(shell._session_history) == 2  # captain + agent
        await shell.execute_command("/bridge")
        assert shell._session_history == []


class TestSlashCommandsInSession:
    """Test that /commands still work during a session."""

    @pytest.mark.asyncio
    async def test_slash_commands_work_in_session(self):
        """/status still works during a session."""
        shell, runtime = _make_shell()
        runtime.status.return_value = {"status": "ok"}
        await shell.execute_command("@wesley")
        # /status should not error
        await shell.execute_command("/status")
        # Still in session
        assert shell._session_callsign == "Wesley"


class TestSessionHistory:
    """Test session history accumulation and episodic memory."""

    @pytest.mark.asyncio
    async def test_session_history_accumulates(self):
        """After 2 exchanges, _session_history has 4 entries."""
        shell, _ = _make_shell()
        await shell.execute_command("@wesley hello")
        await shell.execute_command("how are you")
        assert len(shell._session_history) == 4
        assert shell._session_history[0]["role"] == "captain"
        assert shell._session_history[1]["role"] == "Wesley"
        assert shell._session_history[2]["role"] == "captain"
        assert shell._session_history[3]["role"] == "Wesley"

    @pytest.mark.asyncio
    async def test_session_stores_episodic_memory(self):
        """Each exchange stores an Episode with session_type: '1:1'."""
        shell, runtime = _make_shell()
        mock_memory = MagicMock()
        mock_memory.store = AsyncMock()
        mock_memory.recall_for_agent = AsyncMock(return_value=[])
        runtime.episodic_memory = mock_memory

        await shell.execute_command("@wesley scan for repos")
        assert mock_memory.store.await_count == 1
        episode = mock_memory.store.call_args[0][0]
        assert "[1:1 with Wesley]" in episode.user_input
        assert episode.agent_ids == ["scout-123"]
        assert episode.outcomes[0]["session_type"] == "1:1"
        assert episode.outcomes[0]["callsign"] == "Wesley"

    @pytest.mark.asyncio
    async def test_session_recalls_past_conversations(self):
        """When entering a session, past 1:1 episodes are recalled and seeded into history."""
        from probos.types import Episode

        shell, runtime = _make_shell()
        past_episode = Episode(
            user_input="[1:1 with Wesley] Captain: tell me about yourself",
            timestamp=1000.0,
            agent_ids=["scout-123"],
        )
        mock_memory = MagicMock()
        mock_memory.recall_for_agent = AsyncMock(return_value=[past_episode])
        runtime.episodic_memory = mock_memory

        await shell.execute_command("@wesley")
        # Session history should include the recalled memory
        assert len(shell._session_history) >= 1
        assert shell._session_history[0]["role"] == "system"
        assert "previous conversation" in shell._session_history[0]["text"]

    @pytest.mark.asyncio
    async def test_session_recall_fallback_to_recent(self):
        """BF-028: When recall_for_agent returns [], falls back to recent_for_agent."""
        from probos.types import Episode

        shell, runtime = _make_shell()
        past_episode = Episode(
            user_input="[1:1 with Wesley] Captain: status report",
            timestamp=2000.0,
            agent_ids=["scout-123"],
        )
        mock_memory = MagicMock()
        mock_memory.recall_for_agent = AsyncMock(return_value=[])  # semantic miss
        mock_memory.recent_for_agent = AsyncMock(return_value=[past_episode])
        runtime.episodic_memory = mock_memory

        await shell.execute_command("@wesley")
        # Fallback should have fired
        mock_memory.recent_for_agent.assert_called_once_with("scout-123", k=3)
        assert len(shell._session_history) >= 1
        assert shell._session_history[0]["role"] == "system"
        assert "previous conversation" in shell._session_history[0]["text"]


class TestPromptChanges:
    """Test prompt reflects session mode."""

    def test_normal_prompt(self):
        shell, _ = _make_shell()
        prompt = shell._build_prompt()
        assert "probos>" in prompt

    def test_session_prompt(self):
        shell, _ = _make_shell()
        shell._session_callsign = "Wesley"
        prompt = shell._build_prompt()
        assert "Wesley" in prompt
        assert "\u25b8" in prompt
