"""Tests for the BaseAgent class and agent lifecycle."""

import asyncio
from typing import Any

import pytest

from probos.substrate.agent import BaseAgent
from probos.types import AgentState, CapabilityDescriptor


class DummyAgent(BaseAgent):
    """Minimal concrete agent for testing."""

    agent_type = "dummy"
    default_capabilities = [
        CapabilityDescriptor(can="test", detail="A test agent"),
    ]
    initial_confidence = 0.8

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return intent

    async def decide(self, observation: Any) -> Any:
        return {"action": "echo", "data": observation}

    async def act(self, plan: Any) -> Any:
        return plan.get("data")

    async def report(self, result: Any) -> dict[str, Any]:
        return {"result": result, "agent_id": self.id}


class TestAgentCreation:
    def test_agent_has_unique_id(self):
        a = DummyAgent()
        b = DummyAgent()
        assert a.id != b.id
        assert len(a.id) == 32  # hex UUID

    def test_agent_starts_in_spawning_state(self):
        a = DummyAgent()
        assert a.state == AgentState.SPAWNING

    def test_agent_has_initial_confidence(self):
        a = DummyAgent()
        assert a.confidence == 0.8

    def test_agent_has_capabilities(self):
        a = DummyAgent()
        assert len(a.capabilities) == 1
        assert a.capabilities[0].can == "test"

    def test_agent_pool_assignment(self):
        a = DummyAgent(pool="filesystem")
        assert a.pool == "filesystem"

    def test_agent_info(self):
        a = DummyAgent(pool="test_pool")
        info = a.info()
        assert info["type"] == "dummy"
        assert info["pool"] == "test_pool"
        assert info["state"] == "spawning"
        assert info["confidence"] == 0.8
        assert "test" in info["capabilities"]

    def test_agent_repr(self):
        a = DummyAgent()
        r = repr(a)
        assert "DummyAgent" in r
        assert "spawning" in r


class TestAgentLifecycle:
    @pytest.mark.asyncio
    async def test_start_transitions_to_active(self):
        a = DummyAgent()
        await a.start()
        assert a.state == AgentState.ACTIVE
        assert a.is_alive
        await a.stop()

    @pytest.mark.asyncio
    async def test_stop_transitions_to_recycling(self):
        a = DummyAgent()
        await a.start()
        await a.stop()
        assert a.state == AgentState.RECYCLING
        assert not a.is_alive

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self):
        a = DummyAgent()
        await a.start()
        await a.stop()
        await a.stop()  # Should not raise
        assert a.state == AgentState.RECYCLING

    @pytest.mark.asyncio
    async def test_lifecycle_methods(self):
        a = DummyAgent()
        obs = await a.perceive({"intent": "test"})
        assert obs == {"intent": "test"}

        plan = await a.decide(obs)
        assert plan["action"] == "echo"

        result = await a.act(plan)
        assert result == {"intent": "test"}

        report = await a.report(result)
        assert report["agent_id"] == a.id


class TestConfidenceTracking:
    def test_confidence_increases_on_success(self):
        a = DummyAgent()
        original = a.confidence
        a.update_confidence(True)
        assert a.confidence > original
        assert a.meta.success_count == 1

    def test_confidence_decreases_on_failure(self):
        a = DummyAgent()
        original = a.confidence
        a.update_confidence(False)
        assert a.confidence < original
        assert a.meta.failure_count == 1

    def test_confidence_stays_in_bounds(self):
        a = DummyAgent()
        # Many successes
        for _ in range(100):
            a.update_confidence(True)
        assert a.confidence <= 1.0

        # Many failures
        for _ in range(200):
            a.update_confidence(False)
        assert a.confidence >= 0.01

    def test_degradation_on_low_confidence(self):
        a = DummyAgent()
        a.state = AgentState.ACTIVE
        # Drive confidence below 0.2
        for _ in range(50):
            a.update_confidence(False)
        assert a.state == AgentState.DEGRADED

    def test_total_operations_tracked(self):
        a = DummyAgent()
        a.update_confidence(True)
        a.update_confidence(False)
        a.update_confidence(True)
        assert a.meta.total_operations == 3
        assert a.meta.success_count == 2
        assert a.meta.failure_count == 1


# ---------------------------------------------------------------------------
# BF-023: Degraded agent recovery
# ---------------------------------------------------------------------------


class TestConfidenceRecovery:
    """BF-023: Degraded agents can recover when confidence rises above 0.2."""

    def test_recovery_from_degraded_on_success(self):
        """Agent transitions DEGRADED -> ACTIVE when confidence >= 0.2."""
        a = DummyAgent()
        a.state = AgentState.ACTIVE
        # Drive into DEGRADED
        for _ in range(50):
            a.update_confidence(False)
        assert a.state == AgentState.DEGRADED
        assert a.confidence < 0.2

        # Enough successes to climb back above 0.2
        while a.confidence < 0.2:
            a.update_confidence(True)
        assert a.state == AgentState.ACTIVE

    def test_degraded_stays_degraded_on_failure(self):
        """Continued failures keep agent in DEGRADED state."""
        a = DummyAgent()
        a.state = AgentState.ACTIVE
        for _ in range(50):
            a.update_confidence(False)
        assert a.state == AgentState.DEGRADED
        # More failures don't change state
        a.update_confidence(False)
        assert a.state == AgentState.DEGRADED

    def test_degradation_warning_only_on_transition(self):
        """DEGRADED warning only logs on first transition, not repeated failures."""
        a = DummyAgent()
        a.state = AgentState.ACTIVE
        # First failure that crosses threshold triggers state change
        for _ in range(50):
            a.update_confidence(False)
        assert a.state == AgentState.DEGRADED
        # Agent is already DEGRADED — further failures should not re-log
        # (no exception, state stays DEGRADED)
        for _ in range(10):
            a.update_confidence(False)
        assert a.state == AgentState.DEGRADED


class TestAgentInfoCallsign:
    def test_info_includes_callsign_field(self):
        """info() dict includes callsign key."""
        a = DummyAgent()
        a.callsign = "Wesley"
        info = a.info()
        assert "callsign" in info
        assert info["callsign"] == "Wesley"

    def test_info_callsign_default_empty(self):
        """info() callsign defaults to empty string."""
        a = DummyAgent()
        info = a.info()
        assert info["callsign"] == ""
