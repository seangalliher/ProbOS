"""Tests for AD-396: Quality hardening — encoding, paths, type boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from probos.runtime import ProbOSRuntime
from probos.cognitive.scout import ScoutAgent, _load_seen, _save_seen


# ── 1. Subprocess encoding tests ──


class TestSubprocessEncoding:
    """Verify all subprocess calls handle UTF-8 correctly on Windows."""

    def test_credential_store_uses_utf8(self):
        """CredentialStore CLI resolution uses encoding='utf-8'."""
        from probos.credential_store import CredentialSpec, CredentialStore

        store = CredentialStore(config=MagicMock(), event_log=None)
        spec = CredentialSpec(
            name="test_cred",
            cli_command=["echo", "héllo"],
        )
        store.register(spec)
        with patch("probos.credential_store.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "token123\n"
            mock_run.return_value = mock_result
            store.get("test_cred")
            # Verify encoding args
            call_kwargs = mock_run.call_args
            assert call_kwargs.kwargs.get("encoding") == "utf-8"
            assert call_kwargs.kwargs.get("errors") == "replace"
            assert "text" not in call_kwargs.kwargs or call_kwargs.kwargs.get("text") is not True

    def test_knowledge_store_git_uses_utf8(self):
        """KnowledgeStore._git_run uses encoding='utf-8'."""
        import inspect

        from probos.knowledge.store import KnowledgeStore

        source = inspect.getsource(KnowledgeStore._git_run)
        assert "encoding" in source
        assert "text=True" not in source

    def test_dependency_resolver_uses_utf8(self):
        """DependencyResolver install commands use encoding='utf-8'."""
        import inspect

        from probos.cognitive.dependency_resolver import DependencyResolver

        source = inspect.getsource(DependencyResolver._install_package)
        assert source.count("text=True") == 0
        assert "encoding" in source

    def test_main_reset_uses_utf8(self):
        """__main__ reset subprocess calls use encoding='utf-8'."""
        import inspect

        from probos.__main__ import _cmd_reset

        source = inspect.getsource(_cmd_reset)
        assert "text=True" not in source


# ── 2. Scout data directory tests ──


class TestScoutDataDirectory:
    """Verify Scout uses runtime data_dir, not hardcoded __file__ paths."""

    def test_scout_uses_runtime_data_dir(self, tmp_path: Path):
        """ScoutAgent resolves _data_dir from runtime when available."""
        mock_runtime = MagicMock(spec=ProbOSRuntime)
        mock_runtime._data_dir = tmp_path / "data"
        agent = ScoutAgent(runtime=mock_runtime)
        assert agent._data_dir == tmp_path / "data"

    def test_scout_falls_back_to_default(self):
        """ScoutAgent falls back to project default when runtime is None."""
        agent = ScoutAgent(runtime=None)
        assert agent._data_dir.name == "data"

    def test_seen_file_uses_data_dir(self, tmp_path: Path):
        """_load_seen and _save_seen use provided path."""
        seen_file = tmp_path / "scout_seen.json"
        assert _load_seen(seen_file) == {}
        _save_seen({"owner/repo": "2026-03-22T00:00:00+00:00"}, seen_file)
        loaded = _load_seen(seen_file)
        assert "owner/repo" in loaded

    def test_reports_dir_uses_data_dir(self, tmp_path: Path):
        """ScoutAgent._reports_dir resolves from runtime data_dir."""
        mock_runtime = MagicMock(spec=ProbOSRuntime)
        mock_runtime._data_dir = tmp_path / "data"
        agent = ScoutAgent(runtime=mock_runtime)
        assert agent._reports_dir == tmp_path / "data" / "scout_reports"


# ── 3. Standing orders personality type safety ──


class TestPersonalityTypeSafety:
    """Verify personality trait comparison handles non-numeric values."""

    def test_string_trait_skipped(self):
        """String personality trait values don't crash _build_personality_block."""
        from probos.cognitive.standing_orders import _build_personality_block

        # Clear cache to ensure fresh call
        _build_personality_block.cache_clear()

        with patch("probos.cognitive.standing_orders.load_seed_profile") as mock_load:
            mock_load.return_value = {
                "display_name": "Test",
                "personality": {
                    "openness": "high",  # string instead of float
                    "conscientiousness": 0.8,
                },
            }
            # Should not raise TypeError
            result = _build_personality_block("test_agent", "science")
            assert "Test" in result

        _build_personality_block.cache_clear()

    def test_none_trait_skipped(self):
        """None personality trait values are skipped cleanly."""
        from probos.cognitive.standing_orders import _build_personality_block

        _build_personality_block.cache_clear()

        with patch("probos.cognitive.standing_orders.load_seed_profile") as mock_load:
            mock_load.return_value = {
                "display_name": "Test",
                "personality": {
                    "openness": None,
                    "conscientiousness": 0.8,
                },
            }
            result = _build_personality_block("test_agent_none", "science")
            assert "Test" in result

        _build_personality_block.cache_clear()

    def test_valid_traits_produce_guidance(self):
        """Valid numeric traits produce behavioral guidance."""
        from probos.cognitive.standing_orders import _build_personality_block

        _build_personality_block.cache_clear()

        with patch("probos.cognitive.standing_orders.load_seed_profile") as mock_load:
            mock_load.return_value = {
                "display_name": "Test",
                "personality": {
                    "openness": 0.9,
                    "conscientiousness": 0.2,
                },
            }
            result = _build_personality_block("test_agent_valid", "science")
            assert "Behavioral Style:" in result

        _build_personality_block.cache_clear()


# ── 4. Shell↔Agent boundary tests ──


class TestShellAgentBoundary:
    """Verify shell correctly constructs IntentMessage and looks up agents."""

    def test_intent_message_has_intent_attr(self):
        """IntentMessage dataclass has .intent attribute (not dict key)."""
        from probos.types import IntentMessage

        msg = IntentMessage(intent="test_intent", params={}, context="test")
        assert hasattr(msg, "intent")
        assert msg.intent == "test_intent"

    def test_healthy_agents_returns_ids(self):
        """pool.healthy_agents returns AgentID strings, not agent objects."""
        from probos.substrate.pool import ResourcePool

        pool = ResourcePool(
            name="test",
            agent_type="test",
            spawner=MagicMock(),
            registry=MagicMock(),
            config=MagicMock(),
            target_size=0,
        )
        agents = pool.healthy_agents
        for aid in agents:
            assert isinstance(aid, str)
