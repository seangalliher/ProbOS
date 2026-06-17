"""AD-1019c: submit_mcp_invoke_with_consensus — the CONSENSUS tier + era-4 guard.

Real ``ProbOSRuntime`` + a real ``McpConsensusProposer`` pool + the AD-1014 echo
fixture wired into a real ``_CountingBridge`` (BF-287 — no MagicMock at the
runtime/bridge boundary). The headline assertion is the **era-4 / AD-362 guard**:
a rejected or insufficient vote performs ZERO ``MCPBridge.invoke`` calls — the
invoke is the *commit*, gated on APPROVED, never on the broadcast/vote.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from probos.agents.mcp_consensus_proposer import McpConsensusProposer
from probos.cognitive.episodic import EpisodicMemory
from probos.integrations.mcp_bridge import MCPBridge
from probos.runtime import ProbOSRuntime
from probos.types import ConsensusOutcome, QuorumPolicy

FIXTURE = str(Path(__file__).parent / "fixtures" / "echo_mcp_server.py")


class _CountingBridge(MCPBridge):
    """Real MCPBridge instrumented to count invoke() calls."""

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


class _StoreSpy:
    """Real delegating wrapper recording every episode store (not a Mock)."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.stored: list = []

    async def store(self, episode: object) -> None:
        self.stored.append(episode)
        return await self._inner.store(episode)  # type: ignore[attr-defined]

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


async def _echo_bridge() -> _CountingBridge:
    bridge = _CountingBridge()
    ok = await bridge.register_stdio_server(
        name="echo", command=sys.executable, args=[FIXTURE], env={}, cwd="",
        timeout=5.0,
    )
    assert ok is True
    return bridge


@pytest.fixture
async def runtime(tmp_path):
    rt = ProbOSRuntime(data_dir=tmp_path / "data")
    rt.spawner.register_template("mcp_consensus_proposer", McpConsensusProposer)
    await rt.start()
    yield rt
    await rt.stop()


@pytest.mark.asyncio
async def test_approved_commits_single_invoke(runtime):
    """APPROVED + no failed verifications → exactly one MCPBridge.invoke commit."""
    await runtime.create_pool(
        "mcp_consensus", "mcp_consensus_proposer", target_size=3
    )
    bridge = await _echo_bridge()
    runtime.mcp_bridge = bridge

    result = await runtime.submit_mcp_invoke_with_consensus(
        "echo", "echo", {"q": "hi"}, timeout=5.0
    )

    assert result["consensus"].outcome == ConsensusOutcome.APPROVED
    assert result["committed"] is True
    assert bridge.invoke_count == 1
    assert result["invoke_result"]["content"][0]["text"] == '{"q": "hi"}'

    events = await runtime.event_log.query(category="consensus")
    assert "mcp_invoke_committed" in {e["event"] for e in events}
    await bridge.close_all()


@pytest.mark.asyncio
async def test_rejected_vote_performs_zero_invoke(runtime):
    """era-4 guard: a REJECTED vote must NOT call MCPBridge.invoke."""
    await runtime.create_pool(
        "mcp_consensus", "mcp_consensus_proposer", target_size=3
    )
    bridge = await _echo_bridge()
    runtime.mcp_bridge = bridge

    # An impossible approval threshold forces REJECTED even with all-success
    # proposals (the proposers vote success=True, ratio 1.0 < 1.1).
    result = await runtime.submit_mcp_invoke_with_consensus(
        "echo", "echo", {"q": "hi"}, timeout=5.0,
        policy=QuorumPolicy(min_votes=3, approval_threshold=1.1),
    )

    assert result["consensus"].outcome == ConsensusOutcome.REJECTED
    assert result["committed"] is False
    assert result["invoke_result"] is None
    assert bridge.invoke_count == 0  # <-- the era-4 regression guard
    await bridge.close_all()


@pytest.mark.asyncio
async def test_insufficient_votes_performs_zero_invoke(runtime):
    """era-4 guard: no proposer pool → INSUFFICIENT → zero invoke."""
    # Deliberately do NOT create the proposer pool: no agent answers mcp_invoke.
    bridge = await _echo_bridge()
    runtime.mcp_bridge = bridge

    result = await runtime.submit_mcp_invoke_with_consensus(
        "echo", "echo", {"q": "hi"}, timeout=5.0
    )

    assert result["consensus"].outcome == ConsensusOutcome.INSUFFICIENT
    assert result["committed"] is False
    assert bridge.invoke_count == 0  # <-- the era-4 regression guard
    await bridge.close_all()


@pytest.mark.asyncio
async def test_proposers_do_not_execute_during_vote(runtime):
    """The proposers only PROPOSE — the single invoke is the runtime's commit."""
    await runtime.create_pool(
        "mcp_consensus", "mcp_consensus_proposer", target_size=3
    )
    bridge = await _echo_bridge()
    runtime.mcp_bridge = bridge

    result = await runtime.submit_mcp_invoke_with_consensus(
        "echo", "echo", {"q": "x"}, timeout=5.0
    )

    # 3 proposers voted, but only ONE invoke fired (the runtime commit), proving
    # the proposals/votes never executed the side effect.
    assert len(result["results"]) == 3
    assert bridge.invoke_count == 1
    await bridge.close_all()


@pytest.mark.asyncio
async def test_store_mcp_invoke_episode_records_with_mcp_anchor(runtime, tmp_path):
    """DD-5: an invoke stores an episode; no trust write for the MCP tool."""
    spy = _StoreSpy(EpisodicMemory(db_path=str(tmp_path / "ep_dd5")))
    runtime.episodic_memory = spy

    before = set(runtime.trust_network.all_scores().keys())
    await runtime._store_mcp_invoke_episode(
        server_url="echo", tool="echo", tier="open", success=True, agent_id="agent-1"
    )

    assert len(spy.stored) == 1
    ep = spy.stored[0]
    assert ep.anchors.channel == "mcp"
    assert ep.anchors.trigger_type == "mcp_invoke"
    assert ep.agent_ids == ["agent-1"]
    assert ep.outcomes[0]["kind"] == "mcp_invoke"
    assert ep.outcomes[0]["tool"] == "echo"
    assert ep.outcomes[0]["tier"] == "open"

    # DD-5: no trust/Hebbian write attributable to the MCP tool/server itself.
    after = set(runtime.trust_network.all_scores().keys())
    assert after == before
    assert "echo" not in after


@pytest.mark.asyncio
async def test_store_mcp_invoke_episode_honest_degrade_when_no_memory(runtime):
    """No episodic memory → the helper is a no-op, never raises."""
    runtime.episodic_memory = None
    await runtime._store_mcp_invoke_episode(
        server_url="echo", tool="echo", tier="open", success=True
    )  # must not raise
