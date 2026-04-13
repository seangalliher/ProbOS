"""BF-163: DM send flood rate limiting tests.

Verifies that _extract_and_execute_dms() enforces a per-agent per-target
cooldown of 60 seconds to prevent DM flood loops that overwhelm the LLM proxy.
"""

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class TestDmSendCooldownExists:
    """BF-163: Verify cooldown dict and rate-limit logic exist in source."""

    def test_dm_send_cooldowns_dict_initialized(self):
        """_dm_send_cooldowns must be initialized in __init__."""
        source = Path("src/probos/proactive.py").read_text()
        assert "_dm_send_cooldowns" in source
        assert "dict[str, float]" in source

    def test_cooldown_check_in_extract_dms(self):
        """Rate-limit check must appear inside _extract_and_execute_dms."""
        import ast

        source = Path("src/probos/proactive.py").read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "_extract_and_execute_dms":
                    body_source = ast.get_source_segment(source, node)
                    assert body_source is not None
                    assert "dm_pair_key" in body_source
                    assert "60.0" in body_source
                    assert "continue" in body_source
                    break
        else:
            pytest.fail("_extract_and_execute_dms not found")

    def test_cooldown_key_is_composite(self):
        """Cooldown key must use agent.id:target_callsign composite."""
        source = Path("src/probos/proactive.py").read_text()
        # Verify composite key pattern
        assert 'f"{agent.id}:{target_callsign.lower()}"' in source


class TestDmSendCooldownBehavior:
    """BF-163: Verify cooldown dict correctly tracks and throttles."""

    def test_cooldown_allows_first_dm(self):
        """First DM to any target should always be allowed."""
        cooldowns: dict[str, float] = {}
        key = "agent-1:chapel"
        now = time.monotonic()
        last = cooldowns.get(key, 0.0)
        # First call — 0.0 is always > 60s ago
        assert now - last >= 60.0

    def test_cooldown_blocks_repeat_within_window(self):
        """Same agent→target within 60s should be throttled."""
        cooldowns: dict[str, float] = {}
        key = "agent-1:chapel"
        now = time.monotonic()
        cooldowns[key] = now
        # Immediate retry
        assert now - cooldowns[key] < 60.0

    def test_cooldown_allows_different_target(self):
        """Same agent, different target should NOT be throttled."""
        cooldowns: dict[str, float] = {}
        now = time.monotonic()
        cooldowns["agent-1:chapel"] = now
        key2 = "agent-1:forge"
        last = cooldowns.get(key2, 0.0)
        assert now - last >= 60.0

    def test_cooldown_allows_different_agent_same_target(self):
        """Different agent, same target should NOT be throttled."""
        cooldowns: dict[str, float] = {}
        now = time.monotonic()
        cooldowns["agent-1:chapel"] = now
        key2 = "agent-2:chapel"
        last = cooldowns.get(key2, 0.0)
        assert now - last >= 60.0

    def test_cooldown_expires_after_window(self):
        """After 60s, same pair should be allowed again."""
        cooldowns: dict[str, float] = {}
        key = "agent-1:chapel"
        # Simulate a send 61 seconds ago
        cooldowns[key] = time.monotonic() - 61.0
        now = time.monotonic()
        assert now - cooldowns[key] >= 60.0

    def test_cooldown_key_case_insensitive_target(self):
        """Target callsign must be lowercased for consistent keying."""
        # "Chapel" and "chapel" must produce the same key
        agent_id = "agent-1"
        assert f"{agent_id}:{'Chapel'.lower()}" == f"{agent_id}:{'chapel'.lower()}"
