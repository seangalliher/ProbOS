"""AD-700a: /diagnostic slash command tests."""

from __future__ import annotations

from io import StringIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console

from probos.experience.commands import commands_diagnostic


def _make_runtime(intent_result=None, raise_exc=None):
    """Build a runtime stub with a medical_diagnostician pool."""
    agent = MagicMock()
    if raise_exc is not None:
        agent.handle_intent = AsyncMock(side_effect=raise_exc)
    else:
        if intent_result is None:
            # Default: minimal valid IntentResult-like object
            intent_result = MagicMock()
            intent_result.result = {
                "severity": "low",
                "category": "routine",
                "affected_components": ["heartbeat"],
                "root_cause": "none observed",
                "evidence": "snapshot ok",
                "recommended_treatment": "no action",
                "treatment_intent": "monitor",
            }
        agent.handle_intent = AsyncMock(return_value=intent_result)

    pool = MagicMock()
    pool.healthy_agents = ["agent-001"]
    pool.registry = MagicMock()
    pool.registry.get = MagicMock(return_value=agent)

    runtime = MagicMock()
    runtime.pools = {"medical_diagnostician": pool}
    return runtime, agent


def _make_console():
    buf = StringIO()
    return Console(file=buf, force_terminal=False, width=120), buf


@pytest.mark.asyncio
async def test_cmd_diagnostic_no_args_prints_usage():
    runtime, _ = _make_runtime()
    console, buf = _make_console()
    await commands_diagnostic.cmd_diagnostic(runtime, console, "")
    out = buf.getvalue()
    assert "Usage: /diagnostic" in out


@pytest.mark.asyncio
async def test_cmd_diagnostic_parses_level_token():
    runtime, agent = _make_runtime()
    console, _ = _make_console()
    await commands_diagnostic.cmd_diagnostic(runtime, console, "L2 trust_network")
    agent.handle_intent.assert_awaited_once()
    intent_msg = agent.handle_intent.call_args.args[0]
    assert intent_msg.intent == "diagnose_system"
    assert intent_msg.params == {"level": "L2", "focus": "trust_network"}


@pytest.mark.asyncio
async def test_cmd_diagnostic_numeric_level_token():
    runtime, agent = _make_runtime()
    console, _ = _make_console()
    await commands_diagnostic.cmd_diagnostic(runtime, console, "3")
    intent_msg = agent.handle_intent.call_args.args[0]
    assert intent_msg.params["level"] == "L3"


@pytest.mark.asyncio
async def test_cmd_diagnostic_unknown_level_falls_back_to_l3():
    runtime, agent = _make_runtime()
    console, _ = _make_console()
    await commands_diagnostic.cmd_diagnostic(runtime, console, "banana")
    agent.handle_intent.assert_awaited_once()
    intent_msg = agent.handle_intent.call_args.args[0]
    assert intent_msg.params["level"] == "L3"


@pytest.mark.asyncio
async def test_cmd_diagnostic_no_focus_passes_empty():
    runtime, agent = _make_runtime()
    console, _ = _make_console()
    await commands_diagnostic.cmd_diagnostic(runtime, console, "L1")
    intent_msg = agent.handle_intent.call_args.args[0]
    assert intent_msg.params == {"level": "L1", "focus": ""}


@pytest.mark.asyncio
async def test_cmd_diagnostic_renders_panel_on_success():
    runtime, _ = _make_runtime()
    console, buf = _make_console()
    await commands_diagnostic.cmd_diagnostic(runtime, console, "L3 hebbian_router")
    out = buf.getvalue()
    assert "Diagnostic" in out
    # At least one structured field label should appear
    assert "Severity" in out or "Root cause" in out or "Recommended" in out


@pytest.mark.asyncio
async def test_cmd_diagnostic_runtime_failure_prints_red_error():
    runtime, _ = _make_runtime(raise_exc=RuntimeError("simulated diagnostician failure"))
    console, buf = _make_console()
    await commands_diagnostic.cmd_diagnostic(runtime, console, "L3")
    out = buf.getvalue()
    assert "Diagnostic error" in out
    # No traceback frames leak through
    assert "Traceback" not in out


@pytest.mark.asyncio
async def test_dispatch_slash_routes_diagnostic(monkeypatch):
    """Shell._dispatch_slash must invoke commands_diagnostic.cmd_diagnostic."""
    from probos.experience.shell import ProbOSShell

    captured: dict = {}

    async def _fake(rt, con, args):
        captured["rt"] = rt
        captured["args"] = args

    monkeypatch.setattr(
        "probos.experience.commands.commands_diagnostic.cmd_diagnostic",
        _fake,
    )

    shell = ProbOSShell.__new__(ProbOSShell)
    shell.runtime = MagicMock()
    shell.console = MagicMock()
    shell.renderer = MagicMock()

    await shell._dispatch_slash("/diagnostic L3 trust_network")

    assert captured.get("args") == "L3 trust_network"


def test_diagnostic_appears_in_help_registry():
    from probos.experience.shell import ProbOSShell

    assert "/diagnostic" in ProbOSShell.COMMANDS
    assert "AD-700a" in ProbOSShell.COMMANDS["/diagnostic"]
