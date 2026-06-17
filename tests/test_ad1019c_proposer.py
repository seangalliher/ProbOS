"""AD-1019c: McpConsensusProposer — propose-only voter for ``mcp_invoke``.

The DD-1 option-A voter population. It must validate the request shape and
propose (``requires_consensus=True``) but NEVER execute the invoke — the runtime
commits ``MCPBridge.invoke`` only on APPROVED. These tests assert the
propose-only contract with a real agent (no MagicMock).
"""

from __future__ import annotations

import pytest

from probos.agents.mcp_consensus_proposer import McpConsensusProposer
from probos.types import IntentMessage


def _proposer() -> McpConsensusProposer:
    return McpConsensusProposer(pool="mcp_consensus")


@pytest.mark.asyncio
async def test_proposer_proposes_valid_invoke_with_consensus_flag():
    agent = _proposer()
    msg = IntentMessage(
        intent="mcp_invoke",
        params={"server_url": "echo", "tool": "echo", "arguments": {"q": "hi"}},
    )

    result = await agent.handle_intent(msg)

    assert result is not None
    assert result.success is True
    assert result.result["requires_consensus"] is True
    assert result.result["server_url"] == "echo"
    assert result.result["tool"] == "echo"
    assert result.result["arguments"] == {"q": "hi"}


@pytest.mark.asyncio
async def test_proposer_rejects_missing_server_url():
    agent = _proposer()
    msg = IntentMessage(intent="mcp_invoke", params={"tool": "echo"})

    result = await agent.handle_intent(msg)

    assert result is not None
    assert result.success is False
    assert "server_url" in (result.error or "")


@pytest.mark.asyncio
async def test_proposer_rejects_missing_tool():
    agent = _proposer()
    msg = IntentMessage(intent="mcp_invoke", params={"server_url": "echo"})

    result = await agent.handle_intent(msg)

    assert result is not None
    assert result.success is False
    assert "tool" in (result.error or "")


@pytest.mark.asyncio
async def test_proposer_ignores_unhandled_intent():
    agent = _proposer()
    msg = IntentMessage(intent="write_file", params={"path": "/x", "content": "y"})

    result = await agent.handle_intent(msg)

    assert result is None


@pytest.mark.asyncio
async def test_proposer_arguments_default_empty():
    agent = _proposer()
    msg = IntentMessage(intent="mcp_invoke", params={"server_url": "echo", "tool": "echo"})

    result = await agent.handle_intent(msg)

    assert result is not None
    assert result.success is True
    assert result.result["arguments"] == {}


def test_proposer_intent_descriptor_requires_consensus():
    # The mcp_invoke descriptor must be consensus-gated so the runtime treats it
    # as a proposal, not an execution.
    descs = {d.name: d for d in McpConsensusProposer.intent_descriptors}
    assert "mcp_invoke" in descs
    assert descs["mcp_invoke"].requires_consensus is True


def test_proposer_is_utility_tier():
    assert McpConsensusProposer.tier == "utility"
