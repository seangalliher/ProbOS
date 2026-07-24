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
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from probos.agents.mcp_consensus_proposer import McpConsensusProposer
from probos.cognitive.episodic import EpisodicMemory
from probos.config import SystemConfig
from probos.integrations.mcp_bridge import MCPBridge
from probos.runtime import ProbOSRuntime
from probos.substrate.identity import generate_pool_ids
from probos.substrate.pool import ResourcePool
from probos.types import AgentState, ConsensusOutcome, QuorumPolicy

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


class _FailingStartProposer(McpConsensusProposer):
    agent_type = "failing_start_proposer"

    async def start(self) -> None:
        raise RuntimeError("proposer start failed")


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
    # Explicit default SystemConfig() isolates these consensus tests from operator
    # config/system.yaml: with agent_tools_enabled at its default (False) the runtime
    # does NOT auto-create the mcp_consensus pool, so each test controls the pool.
    rt = ProbOSRuntime(data_dir=tmp_path / "data", config=SystemConfig())
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
async def test_runtime_create_pool_initial_and_recycle_wire_exactly_once(runtime):
    original_wire = runtime.onboarding.wire_agent
    wire_spy = AsyncMock(side_effect=original_wire)
    runtime.onboarding.wire_agent = wire_spy

    pool = await runtime.create_pool(
        "mcp_consensus",
        "mcp_consensus_proposer",
        target_size=3,
    )
    assert wire_spy.await_count == 3

    victim_id = pool.get_agent_ids()[0]
    victim = runtime.registry.get(victim_id)
    assert victim is not None
    victim.state = AgentState.DEGRADED
    await pool.check_health()

    assert wire_spy.await_count == 4
    assert runtime.registry.get(victim_id) is not None
    assert runtime.intent_bus.has_subscriber(victim_id)


@pytest.mark.asyncio
async def test_runtime_create_pool_initial_wiring_failure_rolls_back(runtime):
    original_wire = runtime.onboarding.wire_agent
    wire_count = 0

    async def fail_second_wire(agent) -> None:
        nonlocal wire_count
        wire_count += 1
        if wire_count == 2:
            raise RuntimeError("initial wire failed")
        await original_wire(agent)

    runtime.onboarding.wire_agent = AsyncMock(side_effect=fail_second_wire)
    expected_ids = generate_pool_ids(
        "mcp_consensus_proposer",
        "mcp_consensus",
        3,
    )

    with pytest.raises(RuntimeError, match="initial wire failed"):
        await runtime.create_pool(
            "mcp_consensus",
            "mcp_consensus_proposer",
            target_size=3,
        )

    assert "mcp_consensus" not in runtime.pools
    assert runtime.registry.get_by_pool("mcp_consensus") == []
    assert all(
        runtime.intent_bus.has_subscriber(agent_id) is False
        for agent_id in expected_ids
    )


@pytest.mark.asyncio
async def test_runtime_create_pool_failed_rollback_retains_pool_owner(runtime):
    original_wire = runtime.onboarding.wire_agent
    runtime.onboarding.wire_agent = AsyncMock(
        side_effect=RuntimeError("initial wire failed")
    )
    original_stop = ResourcePool.stop

    with patch.object(
        ResourcePool,
        "stop",
        new=AsyncMock(side_effect=RuntimeError("rollback stop failed")),
    ):
        with pytest.raises(RuntimeError, match="initial wire failed"):
            await runtime.create_pool(
                "mcp_consensus",
                "mcp_consensus_proposer",
                target_size=1,
            )

    assert "mcp_consensus" in runtime.pools
    assert runtime.registry.get_by_pool("mcp_consensus")
    runtime.onboarding.wire_agent = original_wire
    await original_stop(runtime.pools["mcp_consensus"])
    runtime.pools.pop("mcp_consensus", None)


@pytest.mark.asyncio
async def test_runtime_create_pool_agent_start_failure_rolls_back(runtime):
    runtime.spawner.register_template(
        "failing_start_proposer",
        _FailingStartProposer,
    )
    expected_id = generate_pool_ids(
        "failing_start_proposer",
        "failing_start_pool",
        1,
    )[0]

    with pytest.raises(RuntimeError, match="proposer start failed"):
        await runtime.create_pool(
            "failing_start_pool",
            "failing_start_proposer",
            target_size=1,
        )

    assert "failing_start_pool" not in runtime.pools
    assert runtime.registry.get(expected_id) is None
    assert runtime.intent_bus.has_subscriber(expected_id) is False


@pytest.mark.asyncio
async def test_recycle_delete_failure_does_not_wire_replacement(runtime):
    pool = await runtime.create_pool(
        "mcp_consensus",
        "mcp_consensus_proposer",
        target_size=3,
    )
    original_wire = runtime.onboarding.wire_agent
    wire_spy = AsyncMock(side_effect=original_wire)
    runtime.onboarding.wire_agent = wire_spy
    transport = SimpleNamespace(
        remove_tracked_subscriptions=AsyncMock(return_value=2),
        delete_consumer=AsyncMock(side_effect=TimeoutError("nats timeout")),
    )
    original_transport = runtime.intent_bus._nats_bus
    victim_id = pool.get_agent_ids()[0]
    victim = runtime.registry.get(victim_id)
    assert victim is not None
    victim.state = AgentState.DEGRADED

    runtime.intent_bus._nats_bus = transport
    try:
        with pytest.raises(TimeoutError, match="nats timeout"):
            await pool.check_health()

        assert runtime.registry.get(victim_id) is victim
        assert victim_id in pool.get_agent_ids()
        assert runtime.intent_bus.has_subscriber(victim_id)
        wire_spy.assert_not_awaited()
    finally:
        runtime.intent_bus._nats_bus = original_transport


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
