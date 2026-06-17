"""AD-1019c: _McpTool adapter — tier enforcement, DD-4 risk, auth, episode.

Real ``MCPBridge`` + the AD-1014 echo fixture subprocess (BF-287 — no MagicMock
at the bridge boundary). A real ``_CountingBridge`` subclass instruments
``invoke`` so the CONFIRM-no-token path can be proven to perform ZERO invokes.
The CONSENSUS tier is exercised here through a real async stub for
``consensus_invoke`` (the full runtime path is in test_ad1019c_consensus.py).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import (
    MCP_CONFIRM_TOKEN_KEY,
    _coerce_risk,
    _McpTool,
)
from probos.integrations.mcp_bridge import MCPBridge
from probos.integrations.mcp_bridge.risk import McpToolRisk, McpToolRiskStore

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")


class _CountingBridge(MCPBridge):
    """Real MCPBridge that counts invoke() calls (BF-287: a real object)."""

    def __init__(self) -> None:
        super().__init__(
            request_timeout=5.0,
            stdio_enabled=True,
            command_allowlist=[sys.executable],
        )
        self.invoke_count = 0

    async def invoke(self, server_url: str, tool_name: str, arguments: dict) -> dict:
        self.invoke_count += 1
        return await super().invoke(server_url, tool_name, arguments)


class _EpisodeRecorder:
    """A real async callable recording episode writes."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


async def _never_consensus(server_url: str, tool: str, args: dict) -> dict:
    raise AssertionError("consensus path must not be taken for this tier")


async def _register_echo(bridge: MCPBridge) -> None:
    ok = await bridge.register_stdio_server(
        name="echo", command=sys.executable, args=[FIXTURE], env={}, cwd="",
        timeout=5.0,
    )
    assert ok is True


def _make_tool(
    bridge: MCPBridge,
    *,
    risk: str = "open",
    risk_store: Any = None,
    consensus_invoke: Any = None,
    episode_writer: Any = None,
    authorize: Any = None,
    touch: Any = None,
    tool_name: str = "echo",
) -> _McpTool:
    return _McpTool(
        bridge=bridge,
        server_url="echo",
        server_name="echo",
        server_id="echo-id",
        tool_name=tool_name,
        name=tool_name,
        description="echo back arguments",
        input_schema={"type": "object"},
        server_default_risk=risk,
        risk_store=risk_store,
        consensus_invoke=consensus_invoke or _never_consensus,
        authorize=authorize or (lambda aid: True),
        episode_writer=episode_writer,
        touch=touch,
    )


# --------------------------------------------------------------------------- #
# DD-4 risk coercion
# --------------------------------------------------------------------------- #


def test_coerce_risk_known_values():
    assert _coerce_risk("open") is McpToolRisk.OPEN
    assert _coerce_risk("confirm") is McpToolRisk.CONFIRM
    assert _coerce_risk("consensus") is McpToolRisk.CONSENSUS


def test_coerce_risk_unknown_fails_closed_to_consensus():
    # An unknown/legacy value never crashes — it FAILS CLOSED to CONSENSUS
    # (the most-gated tier), never OPEN: a risk classifier that cannot determine
    # the risk must assume the maximum (Safety Budget axiom).
    assert _coerce_risk("garbage") is McpToolRisk.CONSENSUS
    assert _coerce_risk("") is McpToolRisk.CONSENSUS


def test_effective_risk_override_wins():
    store = McpToolRiskStore(db_path="")  # cache-only is fine for routing
    # server default OPEN, per-tool override CONSENSUS -> override wins.
    store._cache[("echo-id", "echo")] = McpToolRisk.CONSENSUS
    tool = _make_tool(MCPBridge(), risk="open", risk_store=store)
    assert tool.effective_risk() is McpToolRisk.CONSENSUS


# --------------------------------------------------------------------------- #
# OPEN tier
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_open_tier_invokes_directly_and_records_episode():
    bridge = _CountingBridge()
    await _register_echo(bridge)
    recorder = _EpisodeRecorder()
    touched: list[int] = []
    tool = _make_tool(
        bridge, risk="open", episode_writer=recorder, touch=lambda: touched.append(1)
    )

    result = await tool.invoke({"q": "hi"}, {"agent_id": "agent-1"})

    assert bridge.invoke_count == 1
    assert result.success is True
    assert result.output["content"][0]["text"] == '{"q": "hi"}'
    assert result.metadata["mcp_tier"] == "open"
    # DD-5 episode on invoke, attributed to the invoking agent.
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["tier"] == "open"
    assert recorder.calls[0]["agent_id"] == "agent-1"
    assert recorder.calls[0]["success"] is True
    assert touched == [1]
    await bridge.close_all()


# --------------------------------------------------------------------------- #
# CONFIRM tier
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_confirm_tier_without_token_blocks_no_invoke():
    bridge = _CountingBridge()
    await _register_echo(bridge)
    recorder = _EpisodeRecorder()
    tool = _make_tool(bridge, risk="confirm", episode_writer=recorder)

    result = await tool.invoke({"q": "hi"}, {"agent_id": "agent-1"})

    assert bridge.invoke_count == 0  # blocked — no invoke
    assert result.success is False
    assert result.error == "requires_confirmation"
    assert result.metadata["outcome"] == "requires_confirmation"
    assert recorder.calls == []  # no episode for a blocked (non-)invoke
    await bridge.close_all()


@pytest.mark.asyncio
async def test_confirm_tier_with_token_invokes():
    bridge = _CountingBridge()
    await _register_echo(bridge)
    recorder = _EpisodeRecorder()
    tool = _make_tool(bridge, risk="confirm", episode_writer=recorder)

    result = await tool.invoke(
        {"q": "go"}, {"agent_id": "agent-1", MCP_CONFIRM_TOKEN_KEY: "ok"}
    )

    assert bridge.invoke_count == 1
    assert result.success is True
    assert result.metadata["mcp_tier"] == "confirm"
    assert recorder.calls[0]["tier"] == "confirm"
    await bridge.close_all()


# --------------------------------------------------------------------------- #
# CONSENSUS tier (stubbed consensus_invoke; full path in test_ad1019c_consensus)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_consensus_tier_approved_returns_invoke_result_no_double_episode():
    bridge = _CountingBridge()
    recorder = _EpisodeRecorder()
    seen: list[tuple] = []

    async def _consensus(server_url, tool, args):
        seen.append((server_url, tool, args))
        return {"committed": True, "invoke_result": {"ok": 1}, "consensus": None}

    tool = _make_tool(
        bridge, risk="consensus", consensus_invoke=_consensus, episode_writer=recorder
    )

    result = await tool.invoke({"q": "z"}, {"agent_id": "agent-1"})

    assert seen == [("echo", "echo", {"q": "z"})]
    assert bridge.invoke_count == 0  # the adapter never calls bridge.invoke
    assert result.success is True
    assert result.output == {"ok": 1}
    assert result.metadata["outcome"] == "approved"
    # The consensus tier stores its episode in the runtime, NOT the adapter.
    assert recorder.calls == []


@pytest.mark.asyncio
async def test_consensus_tier_blocked_returns_outcome():
    rejected = types.SimpleNamespace(outcome=types.SimpleNamespace(value="rejected"))

    async def _consensus(server_url, tool, args):
        return {"committed": False, "invoke_result": None, "consensus": rejected}

    tool = _make_tool(MCPBridge(), risk="consensus", consensus_invoke=_consensus)

    result = await tool.invoke({"q": "z"}, {"agent_id": "agent-1"})

    assert result.success is False
    assert result.error == "consensus_blocked"
    assert result.metadata["outcome"] == "rejected"


# --------------------------------------------------------------------------- #
# Authorization re-check + deny-safe
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_unauthorized_agent_denied_no_invoke():
    bridge = _CountingBridge()
    await _register_echo(bridge)
    tool = _make_tool(bridge, risk="open", authorize=lambda aid: False)

    result = await tool.invoke({"q": "hi"}, {"agent_id": "intruder"})

    assert bridge.invoke_count == 0
    assert result.success is False
    assert "not authorized" in (result.error or "")
    await bridge.close_all()


@pytest.mark.asyncio
async def test_invoke_is_deny_safe_on_bridge_error():
    # An unregistered server makes bridge.invoke raise; the adapter must return
    # an error ToolResult, never crash.
    bridge = _CountingBridge()  # echo NOT registered
    tool = _make_tool(bridge, risk="open")

    result = await tool.invoke({"q": "hi"}, {"agent_id": "agent-1"})

    assert result.success is False
    assert result.error  # surfaced, not raised


def test_tool_id_and_type():
    tool = _make_tool(MCPBridge(), risk="open")
    assert tool.tool_id == "mcp:echo:echo"
    from probos.tools.protocol import ToolType

    assert tool.tool_type is ToolType.MCP_SERVER
