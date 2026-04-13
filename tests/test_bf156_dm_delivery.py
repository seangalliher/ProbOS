"""BF-156: DM delivery reliability tests."""

import asyncio
import time

import pytest


class TestUnreadDmBeforeEnsignGate:
    """BF-156: _check_unread_dms() runs before Ensign gate."""

    def test_check_unread_dms_before_rank_gate(self):
        """Verify _check_unread_dms is called even for Ensign-ranked agents.

        The proactive loop should check unread DMs before the
        can_think_proactively() gate, so Ensigns still receive DMs.
        """
        import ast
        from pathlib import Path

        source = Path("src/probos/proactive.py").read_text()
        tree = ast.parse(source)

        # Find _run_cycle method
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "_run_cycle":
                # Find the positions of _check_unread_dms and can_think_proactively
                dm_check_line = None
                rank_gate_line = None
                for child in ast.walk(node):
                    if isinstance(child, ast.Attribute) and child.attr == "_check_unread_dms":
                        dm_check_line = child.lineno
                    if isinstance(child, ast.Call):
                        func = child.func
                        if isinstance(func, ast.Name) and func.id == "can_think_proactively":
                            rank_gate_line = func.lineno
                assert dm_check_line is not None, "_check_unread_dms not found in _run_cycle"
                assert rank_gate_line is not None, "can_think_proactively not found in _run_cycle"
                assert dm_check_line < rank_gate_line, (
                    f"_check_unread_dms (line {dm_check_line}) must come before "
                    f"can_think_proactively (line {rank_gate_line})"
                )
                break
        else:
            pytest.fail("_run_cycle method not found")


class TestDmBypassesCooldown:
    """BF-156: DM channel notifications bypass per-agent cooldown."""

    def test_dm_channel_bypasses_cooldown(self):
        """DM channel type should set is_direct_target = True."""
        # Verify the pattern exists in source
        from pathlib import Path

        source = Path("src/probos/ward_room_router.py").read_text()
        assert 'channel.channel_type == "dm"' in source
        assert "is_direct_target" in source


class TestDmBypassesThreadDepth:
    """BF-156: DM channels bypass thread depth cap."""

    def test_dm_channel_bypasses_thread_depth_cap(self):
        """Thread depth cap check should exclude DM channels."""
        from pathlib import Path

        source = Path("src/probos/ward_room_router.py").read_text()
        # The thread depth guard should have a DM exclusion
        assert 'channel.channel_type != "dm"' in source
