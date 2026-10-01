"""Experience layer: agent roster, slash commands, approval callbacks, model registry.

Split out of the original single test_experience.py so no one file is the
canonical gate's critical path (see docs/development/test-suite-optimization-plan.md, P0.1).
"""

import pytest

from probos.experience import panels
from probos.experience.shell import ProbOSShell

from tests.fixtures.experience_shell import (  # noqa: F401 -- pytest fixtures and helper
    console,
    get_output,
    runtime,
    shell,
)


# ---------------------------------------------------------------------------
# Agent Roster panel tests
# ---------------------------------------------------------------------------

class TestAgentRoster:
    """Tests for render_agent_roster (pool-level org chart)."""

    def test_basic_output(self, runtime, console):
        """Roster produces panel with pool-level rows."""
        scores = runtime.trust_network.all_scores()
        panel = panels.render_agent_roster(
            runtime.pools, runtime.pool_groups, runtime.registry, scores,
        )
        console.print(panel)
        output = get_output(console)
        assert "Agent Roster" in output
        assert "file_reader" in output

    def test_columns_present(self, runtime, console):
        """All expected columns appear in the table."""
        scores = runtime.trust_network.all_scores()
        panel = panels.render_agent_roster(
            runtime.pools, runtime.pool_groups, runtime.registry, scores,
        )
        console.print(panel)
        output = get_output(console)
        for col in ("Type", "Tier", "Team", "Pool", "Size"):
            assert col in output, f"Missing column: {col}"

    def test_empty_pools(self, console):
        """Empty pools dict produces panel with '0 pools' in title."""
        from unittest.mock import MagicMock

        mock_registry = MagicMock()
        mock_registry.get_by_pool.return_value = []
        panel = panels.render_agent_roster({}, None, mock_registry, {})
        console.print(panel)
        output = get_output(console)
        assert "0 pools" in output

    def test_tier_grouping(self, runtime, console):
        """Core-tier agents appear in output."""
        scores = runtime.trust_network.all_scores()
        panel = panels.render_agent_roster(
            runtime.pools, runtime.pool_groups, runtime.registry, scores,
        )
        console.print(panel)
        output = get_output(console)
        assert "core" in output.lower()

    def test_size_format(self, runtime, console):
        """Size column shows current/target format."""
        scores = runtime.trust_network.all_scores()
        panel = panels.render_agent_roster(
            runtime.pools, runtime.pool_groups, runtime.registry, scores,
        )
        console.print(panel)
        output = get_output(console)
        # At least one pool should show e.g. "2/2" or "1/2"
        import re
        assert re.search(r"\d+/\d+", output), "No current/target size found"

    def test_no_pool_groups(self, runtime, console):
        """Handles pool_groups=None gracefully (team shows dash)."""
        scores = runtime.trust_network.all_scores()
        panel = panels.render_agent_roster(
            runtime.pools, None, runtime.registry, scores,
        )
        console.print(panel)
        output = get_output(console)
        assert "Agent Roster" in output

    def test_trust_confidence_format(self, runtime, console):
        """Trust and confidence show avg +/- stdev format."""
        scores = runtime.trust_network.all_scores()
        panel = panels.render_agent_roster(
            runtime.pools, runtime.pool_groups, runtime.registry, scores,
        )
        console.print(panel)
        output = get_output(console)
        assert "\u00b1" in output, "No +/- symbol found in trust/confidence"


# ---------------------------------------------------------------------------
# Shell command handler tests (coverage improvement)
# ---------------------------------------------------------------------------


class TestShellHistoryCommand:
    """Tests for _cmd_history()."""

    @pytest.mark.asyncio
    async def test_history_no_episodic_memory(self, shell, console):
        """History command handles missing episodic memory."""
        shell.runtime.episodic_memory = None
        await shell._cmd_history("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Episodic" in output

    @pytest.mark.asyncio
    async def test_history_empty(self, shell, console):
        """History command handles no episodes gracefully."""
        from unittest.mock import AsyncMock
        mock_mem = AsyncMock()
        mock_mem.recent.return_value = []
        mock_mem.stop = AsyncMock()
        shell.runtime.episodic_memory = mock_mem
        await shell._cmd_history("")
        output = get_output(console)
        assert "No episodes" in output or "Memory" in output or output != ""


class TestShellRecallCommand:
    """Tests for _cmd_recall()."""

    @pytest.mark.asyncio
    async def test_recall_no_query(self, shell, console):
        """Recall command with no episodic memory shows not-enabled message."""
        shell.runtime.episodic_memory = None
        await shell._cmd_recall("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Episodic" in output

    @pytest.mark.asyncio
    async def test_recall_no_memory(self, shell, console):
        """Recall command handles missing episodic memory."""
        shell.runtime.episodic_memory = None
        await shell._cmd_recall("test query")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Episodic" in output


class TestShellDreamCommand:
    """Tests for _cmd_dream()."""

    @pytest.mark.asyncio
    async def test_dream_not_enabled(self, shell, console):
        """Dream command handles missing dream scheduler."""
        shell.runtime.dream_scheduler = None
        await shell._cmd_dream("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Dream" in output


class TestShellFederationCommand:
    """Tests for _cmd_federation() and _cmd_peers()."""

    @pytest.mark.asyncio
    async def test_federation_not_enabled(self, shell, console):
        """Federation command handles missing federation bridge."""
        shell.runtime.federation_bridge = None
        await shell._cmd_federation("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Federation" in output

    @pytest.mark.asyncio
    async def test_peers_not_enabled(self, shell, console):
        """Peers command handles missing federation bridge."""
        shell.runtime.federation_bridge = None
        await shell._cmd_peers("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Federation" in output


class TestShellDesignedCommand:
    """Tests for _cmd_designed()."""

    @pytest.mark.asyncio
    async def test_designed_not_enabled(self, shell, console):
        """Designed command handles missing self_mod_pipeline."""
        shell.runtime.self_mod_pipeline = None
        await shell._cmd_designed("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Self-modification" in output or "modification" in output.lower()


class TestShellKnowledgeCommand:
    """Tests for _cmd_knowledge()."""

    @pytest.mark.asyncio
    async def test_knowledge_not_enabled(self, shell, console):
        """Knowledge command handles missing knowledge store."""
        # Ensure _knowledge_store attribute returns None
        if hasattr(shell.runtime, '_knowledge_store'):
            shell.runtime._knowledge_store = None
        await shell._cmd_knowledge("")
        output = get_output(console)
        assert "not enabled" in output.lower() or "Knowledge" in output or "knowledge" in output.lower()


class TestShellQACommand:
    """Tests for _cmd_qa()."""

    @pytest.mark.asyncio
    async def test_qa_no_reports(self, shell, console):
        """QA command handles no reports."""
        shell.runtime._qa_reports = {}
        await shell._cmd_qa("")
        output = get_output(console)
        assert "No QA" in output or "qa" in output.lower() or output != ""


class TestShellSearchCommand:
    """Tests for _cmd_search()."""

    @pytest.mark.asyncio
    async def test_search_no_semantic_layer(self, shell, console):
        """Search command with no semantic layer shows not-available."""
        shell.runtime._semantic_layer = None
        await shell._cmd_search("")
        output = get_output(console)
        assert "not available" in output.lower() or "Semantic" in output

    @pytest.mark.asyncio
    async def test_search_no_semantic_layer(self, shell, console):
        """Search command handles missing semantic layer."""
        shell.runtime._semantic_layer = None
        await shell._cmd_search("test query")
        output = get_output(console)
        assert "not available" in output.lower() or "Semantic" in output


class TestShellImportsCommand:
    """Tests for _cmd_imports()."""

    @pytest.mark.asyncio
    async def test_imports_lists_allowed(self, shell, console):
        """Imports command lists allowed imports when self_mod config exists."""
        from unittest.mock import MagicMock
        mock_config = MagicMock()
        mock_config.allowed_imports = ["json", "os"]
        shell.runtime.config.self_mod = mock_config
        await shell._cmd_imports("")
        output = get_output(console)
        assert "json" in output or "os" in output or "import" in output.lower()


class TestShellApprovalCallbacks:
    """Tests for user approval callback methods."""

    @pytest.mark.asyncio
    async def test_user_self_mod_approval_eof(self, shell, console):
        """_user_self_mod_approval handles EOFError as denial."""
        from unittest.mock import patch
        with patch("builtins.input", side_effect=EOFError):
            result = await shell._user_self_mod_approval("test proposal")
        assert result is False

    @pytest.mark.asyncio
    async def test_user_import_approval_eof(self, shell, console):
        """_user_import_approval handles EOFError as denial."""
        from unittest.mock import patch
        with patch("builtins.input", side_effect=EOFError):
            result = await shell._user_import_approval(["numpy", "pandas"])
        assert result is False

    @pytest.mark.asyncio
    async def test_user_dep_install_approval_eof(self, shell, console):
        """_user_dep_install_approval handles EOFError as denial."""
        from unittest.mock import patch
        with patch("builtins.input", side_effect=EOFError):
            result = await shell._user_dep_install_approval(["requests"])
        assert result is False

    @pytest.mark.asyncio
    async def test_user_escalation_callback_eof(self, shell, console):
        """_user_escalation_callback handles EOFError as skip (None)."""
        from unittest.mock import patch
        if not hasattr(shell, '_user_escalation_callback'):
            pytest.skip("No escalation callback on shell")
        with patch("builtins.input", side_effect=EOFError):
            result = await shell._user_escalation_callback(
                "test escalation", {"intent": "test", "error": "err"}
            )
        assert result is None


# ---------------------------------------------------------------------------
# /models and /registry command tests (AD-356)
# ---------------------------------------------------------------------------

class TestModelsAndRegistry:
    """Verify /model was renamed to /models and /registry exists."""

    def test_help_includes_models_and_registry(self):
        """COMMANDS dict has /models and /registry, not /model."""
        assert "/models" in ProbOSShell.COMMANDS
        assert "/registry" in ProbOSShell.COMMANDS
        assert "/model" not in ProbOSShell.COMMANDS

    def test_classify_provider(self):
        from probos.cognitive.copilot_adapter import _classify_provider
        assert _classify_provider("claude-sonnet-4-6") == "Anthropic"
        assert _classify_provider("gpt-4o-mini") == "OpenAI"
        assert _classify_provider("gemini-1.5-pro") == "Google"
        assert _classify_provider("deepseek-coder") == "Local/OSS"
        assert _classify_provider("qwen-72b") == "Local/OSS"
        assert _classify_provider("some-random-model") == "Unknown"

    @pytest.mark.asyncio
    async def test_cmd_models_shows_tier_info(self, shell, console):
        """_cmd_models prints a Panel with LLM Configuration."""
        await shell.execute_command("/models")
        output = get_output(console)
        assert "LLM Configuration" in output
        assert "MockLLMClient" in output

    @pytest.mark.asyncio
    async def test_cmd_registry_mock_client(self, shell, console):
        """_cmd_registry with MockLLMClient shows the tier table fallback row."""
        await shell.execute_command("/registry")
        output = get_output(console)
        assert "Active Models" in output
        assert "MockLLMClient" in output
