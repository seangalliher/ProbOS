"""BF-257: DM receive rate limiter tests.

Verifies that the per-agent DM response budget and per-pair exchange budget
prevent ping-pong loops where agents auto-reply to each other's DMs
indefinitely, exhausting LLM capacity.
"""

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Section 1: Source-level verification
# ---------------------------------------------------------------------------

class TestBf257SourcePresence:
    """BF-257: Verify rate limiter structures exist in source."""

    def test_dm_response_counts_initialized(self):
        """_dm_response_counts dict must be in __init__."""
        source = Path("src/probos/proactive.py").read_text()
        assert "_dm_response_counts" in source

    def test_dm_pair_counts_initialized(self):
        """_dm_pair_counts dict must be in __init__."""
        source = Path("src/probos/proactive.py").read_text()
        assert "_dm_pair_counts" in source

    def test_budget_check_method_exists(self):
        """_dm_response_budget_exceeded method must exist."""
        source = Path("src/probos/proactive.py").read_text()
        assert "_dm_response_budget_exceeded" in source

    def test_config_fields_exist(self):
        """WardRoomConfig must have BF-257 config fields.

        Resolves the DECLARING module rather than hard-coding
        ``src/probos/config.py``. AD-1270e2 is moving config models into
        ``config_models/`` while ``probos.config`` keeps re-exporting them, so a
        literal path here goes stale the moment this model is moved -- which is
        exactly what happened to two sibling guards in an earlier batch.
        """
        import inspect

        from probos.config import WardRoomConfig

        source = Path(inspect.getfile(WardRoomConfig)).read_text(encoding="utf-8")
        assert "dm_response_budget" in source
        assert "dm_response_window_seconds" in source
        assert "dm_pair_exchange_budget" in source

    def test_dm_exchange_limit_lowered(self):
        """dm_exchange_limit default should be 15, not 40."""
        from probos.config import WardRoomConfig
        cfg = WardRoomConfig()
        assert cfg.dm_exchange_limit == 15


# ---------------------------------------------------------------------------
# Section 2: Budget check logic
# ---------------------------------------------------------------------------

class TestDmResponseBudget:
    """BF-257: _dm_response_budget_exceeded unit tests."""

    def _make_proactive(self):
        """Create minimal ProactiveCognitiveLoop-like object with BF-257 state."""
        obj = MagicMock()
        obj._dm_response_counts = {}
        obj._dm_pair_counts = {}
        from probos.proactive import ProactiveCognitiveLoop
        import types
        obj._dm_response_budget_exceeded = types.MethodType(
            ProactiveCognitiveLoop._dm_response_budget_exceeded, obj,
        )
        return obj

    def _make_config(self, budget=6, window=600.0, pair_budget=8):
        cfg = MagicMock()
        cfg.dm_response_budget = budget
        cfg.dm_response_window_seconds = window
        cfg.dm_pair_exchange_budget = pair_budget
        return cfg

    def test_allows_first_dm(self):
        """First DM response should always be allowed."""
        p = self._make_proactive()
        cfg = self._make_config()
        result = p._dm_response_budget_exceeded("agent-a", "agent-b", cfg)
        assert result is None

    def test_blocks_after_budget_exhausted(self):
        """Should block after budget responses in window."""
        p = self._make_proactive()
        cfg = self._make_config(budget=3, window=600.0)
        now = time.monotonic()
        p._dm_response_counts["agent-a"] = [now - 10, now - 5, now - 1]
        result = p._dm_response_budget_exceeded("agent-a", "agent-b", cfg)
        assert result is not None
        assert "agent_budget" in result

    def test_expired_timestamps_pruned(self):
        """Timestamps older than window should be pruned and not count."""
        p = self._make_proactive()
        cfg = self._make_config(budget=3, window=60.0)
        now = time.monotonic()
        p._dm_response_counts["agent-a"] = [now - 120, now - 90, now - 61]
        result = p._dm_response_budget_exceeded("agent-a", "agent-b", cfg)
        assert result is None
        assert len(p._dm_response_counts["agent-a"]) == 0

    def test_pair_budget_bidirectional(self):
        """A->B and B->A should share the same pair counter."""
        p = self._make_proactive()
        cfg = self._make_config(pair_budget=2, window=600.0)
        now = time.monotonic()
        pair_key = ":".join(sorted(["agent-a", "agent-b"]))
        p._dm_pair_counts[pair_key] = [now - 10, now - 5]
        result_a = p._dm_response_budget_exceeded("agent-a", "agent-b", cfg)
        assert result_a is not None
        assert "pair_budget" in result_a
        p._dm_pair_counts[pair_key] = [now - 10, now - 5]
        result_b = p._dm_response_budget_exceeded("agent-b", "agent-a", cfg)
        assert result_b is not None
        assert "pair_budget" in result_b

    def test_agent_budget_checked_before_pair(self):
        """Agent-level budget should be checked first."""
        p = self._make_proactive()
        cfg = self._make_config(budget=2, pair_budget=8, window=600.0)
        now = time.monotonic()
        p._dm_response_counts["agent-a"] = [now - 10, now - 5]
        result = p._dm_response_budget_exceeded("agent-a", "agent-b", cfg)
        assert result is not None
        assert "agent_budget" in result

    def test_different_partners_share_agent_budget(self):
        """DMs to different partners all count toward agent budget."""
        p = self._make_proactive()
        cfg = self._make_config(budget=3, window=600.0)
        now = time.monotonic()
        p._dm_response_counts["agent-a"] = [now - 30, now - 20, now - 10]
        result = p._dm_response_budget_exceeded("agent-a", "agent-c", cfg)
        assert result is not None
        assert "agent_budget" in result


# ---------------------------------------------------------------------------
# Section 3: Integration -- _check_unread_dms gating
# ---------------------------------------------------------------------------

class TestCheckUnreadDmsGating:
    """BF-257: Verify _check_unread_dms applies budget gate."""

    def test_budget_check_in_check_unread_dms(self):
        """_check_unread_dms must call _dm_response_budget_exceeded."""
        import ast
        source = Path("src/probos/proactive.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "_check_unread_dms":
                    body_source = ast.get_source_segment(source, node)
                    assert body_source is not None
                    assert "_dm_response_budget_exceeded" in body_source
                    assert "BF-257" in body_source
                    break
        else:
            pytest.fail("_check_unread_dms not found")

    def test_captain_dm_exempt(self):
        """Captain DMs must bypass the budget check."""
        import ast
        source = Path("src/probos/proactive.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "_check_unread_dms":
                    body_source = ast.get_source_segment(source, node)
                    assert body_source is not None
                    assert 'captain' in body_source.lower()
                    break
        else:
            pytest.fail("_check_unread_dms not found")

    def test_throttled_dm_not_added_to_notified(self):
        """Throttled DMs should NOT be added to _notified_dm_threads."""
        import ast
        source = Path("src/probos/proactive.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "_check_unread_dms":
                    body_source = ast.get_source_segment(source, node)
                    assert body_source is not None
                    bf257_pos = body_source.find("BF-257")
                    continue_pos = body_source.find("continue", bf257_pos)
                    add_pos = body_source.find("_notified_dm_threads.add", continue_pos)
                    assert bf257_pos < continue_pos < add_pos, (
                        "BF-257 throttle 'continue' must come before _notified_dm_threads.add"
                    )
                    break
        else:
            pytest.fail("_check_unread_dms not found")
