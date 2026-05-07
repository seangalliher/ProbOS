"""AD-548: Tests for blocked-paths pre-hook policy."""

from __future__ import annotations

from probos.cognitive.swe_harness.policies import make_blocked_paths_hook


def test_empty_list_returns_permissive_identity_hook() -> None:
    hook = make_blocked_paths_hook([])
    assert hook({"params": {"path": "/anything"}, "tool_id": "read_file"}) is True


def test_blocked_path_substring_denies_read_file() -> None:
    hook = make_blocked_paths_hook(["src/probos/security/"])
    ctx = {
        "tool_id": "read_file",
        "params": {"path": "src/probos/security/secrets.py"},
        "agent_id": "agent-1",
    }
    assert hook(ctx) is False


def test_blocked_path_substring_denies_write_file() -> None:
    hook = make_blocked_paths_hook([".env"])
    ctx = {
        "tool_id": "write_file",
        "params": {"path": "/repo/.env", "content": "TOKEN=123"},
        "agent_id": "agent-1",
    }
    assert hook(ctx) is False


def test_blocked_command_substring_denies_run_command() -> None:
    hook = make_blocked_paths_hook(["sealed_modules.yaml"])
    ctx = {
        "tool_id": "run_command",
        "params": {"command": "cat config/sealed_modules.yaml"},
        "agent_id": "agent-1",
    }
    assert hook(ctx) is False


def test_tool_with_no_path_or_command_permitted() -> None:
    hook = make_blocked_paths_hook(["src/probos/security/"])
    ctx = {
        "tool_id": "system_self_model",
        "params": {},
        "agent_id": "agent-1",
    }
    assert hook(ctx) is True


def test_hook_fails_open_on_internal_exception() -> None:
    hook = make_blocked_paths_hook(["x"])

    class _BadParams:
        def __contains__(self, key):
            raise RuntimeError("boom")

        def get(self, *a, **k):
            raise RuntimeError("boom")

    # ctx.get will trip on the .get inside hook body — fails open.
    class _BadCtx:
        def get(self, key, default=None):
            if key == "params":
                return _BadParams()
            return default

    assert hook(_BadCtx()) is True
