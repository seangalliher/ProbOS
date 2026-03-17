"""Tests for AD-289 P0 performance optimizations."""

import asyncio
import random

import pytest

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.substrate.registry import AgentRegistry
from probos.types import IntentMessage, IntentResult, Vote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeAgent:
    """Minimal agent stub for registry tests."""

    def __init__(self, agent_id: str, pool: str = "test"):
        self.id = agent_id
        self.agent_type = "fake"
        self.pool = pool
        self.capabilities = []
        self.state = "active"


# ---------------------------------------------------------------------------
# Fix 1: Intent Bus Pre-Filtering
# ---------------------------------------------------------------------------

class TestIntentBusPreFiltering:
    @pytest.fixture
    def bus(self):
        return IntentBus(SignalManager())

    @pytest.mark.asyncio
    async def test_only_matching_agents_receive_broadcast(self, bus):
        """Agents indexed for 'read_file' should receive 'read_file' intents;
        agents indexed for 'write_file' should not."""
        received_by: list[str] = []

        async def make_handler(agent_id: str):
            async def handler(intent: IntentMessage) -> IntentResult | None:
                received_by.append(agent_id)
                return IntentResult(
                    intent_id=intent.id, agent_id=agent_id, success=True,
                )
            return handler

        bus.subscribe("reader", await make_handler("reader"), intent_names=["read_file"])
        bus.subscribe("writer", await make_handler("writer"), intent_names=["write_file"])

        intent = IntentMessage(intent="read_file", ttl_seconds=2.0)
        results = await bus.broadcast(intent, timeout=2.0)

        assert len(results) == 1
        assert results[0].agent_id == "reader"
        assert "writer" not in received_by

    @pytest.mark.asyncio
    async def test_fallback_to_full_broadcast_for_unknown_intent(self, bus):
        """Intents not in any index should fan out to all subscribers."""
        async def handler(intent: IntentMessage) -> IntentResult | None:
            return IntentResult(
                intent_id=intent.id, agent_id="fallback", success=True,
            )

        # Subscribe without intent_names — this agent is a fallback subscriber
        bus.subscribe("fallback", handler)

        intent = IntentMessage(intent="unknown_intent", ttl_seconds=2.0)
        results = await bus.broadcast(intent, timeout=2.0)

        assert len(results) == 1
        assert results[0].agent_id == "fallback"

    @pytest.mark.asyncio
    async def test_fallback_subscribers_always_receive(self, bus):
        """Agents subscribed without intent_names receive all intents,
        even when the index has entries for that intent."""
        received_by: list[str] = []

        async def make_handler(agent_id: str):
            async def handler(intent: IntentMessage) -> IntentResult | None:
                received_by.append(agent_id)
                return IntentResult(
                    intent_id=intent.id, agent_id=agent_id, success=True,
                )
            return handler

        bus.subscribe("indexed", await make_handler("indexed"), intent_names=["read_file"])
        bus.subscribe("fallback", await make_handler("fallback"))  # no intent_names

        intent = IntentMessage(intent="read_file", ttl_seconds=2.0)
        results = await bus.broadcast(intent, timeout=2.0)

        assert len(results) == 2
        agent_ids = {r.agent_id for r in results}
        assert agent_ids == {"indexed", "fallback"}

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_from_intent_index(self, bus):
        """Unsubscribing an agent should remove it from the intent index too."""
        async def handler(intent: IntentMessage) -> IntentResult | None:
            return IntentResult(
                intent_id=intent.id, agent_id="agent", success=True,
            )

        bus.subscribe("agent", handler, intent_names=["read_file"])
        assert "agent" in bus._intent_index.get("read_file", set())

        bus.unsubscribe("agent")
        assert "agent" not in bus._intent_index.get("read_file", set())
        assert bus.subscriber_count == 0


# ---------------------------------------------------------------------------
# Fix 2: Shapley Value Factorial Explosion Guard
# ---------------------------------------------------------------------------

class TestShapleyExplosionGuard:
    def _make_votes(self, n: int, all_approve: bool = True) -> list[Vote]:
        return [
            Vote(
                agent_id=f"agent_{i}",
                approved=all_approve,
                confidence=0.8 + 0.02 * i,
                reason="test",
            )
            for i in range(n)
        ]

    def test_exact_shapley_small_coalition(self):
        """Exact computation for small coalitions (<= 10)."""
        from probos.consensus.shapley import compute_shapley_values

        votes = self._make_votes(3, all_approve=True)
        values = compute_shapley_values(votes, approval_threshold=0.5)

        assert len(values) == 3
        assert all(0 <= v <= 1 for v in values.values())
        assert abs(sum(values.values()) - 1.0) < 1e-6

    def test_approximate_shapley_large_coalition(self):
        """Monte Carlo approximation for large coalitions (> 10)."""
        from probos.consensus.shapley import compute_shapley_values

        votes = self._make_votes(15, all_approve=True)
        values = compute_shapley_values(votes, approval_threshold=0.5)

        assert len(values) == 15
        assert all(0 <= v <= 1 for v in values.values())
        # Shapley efficiency: values should sum to ~1.0
        assert abs(sum(values.values()) - 1.0) < 0.1

    def test_large_coalition_completes_quickly(self):
        """20-agent coalition should complete in under 2 seconds (not factorial time)."""
        import time

        from probos.consensus.shapley import compute_shapley_values

        votes = self._make_votes(20, all_approve=True)

        start = time.monotonic()
        values = compute_shapley_values(votes, approval_threshold=0.5)
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, f"Shapley took {elapsed:.1f}s for 20 agents (should be <2s)"
        assert len(values) == 20

    def test_approximate_values_reasonable(self):
        """Approximate values should be similar to exact for a small coalition."""
        from probos.consensus.shapley import (
            _approximate_shapley,
            _exact_shapley,
            _evaluate_coalition,
        )

        votes = [
            Vote(agent_id="a", approved=True, confidence=0.9, reason="yes"),
            Vote(agent_id="b", approved=True, confidence=0.8, reason="yes"),
            Vote(agent_id="c", approved=False, confidence=0.7, reason="no"),
        ]
        vote_by_id = {v.agent_id: v for v in votes}
        agent_ids = list(vote_by_id.keys())

        exact = _exact_shapley(agent_ids, vote_by_id, 0.5, True)
        approx = _approximate_shapley(agent_ids, vote_by_id, 0.5, True, samples=5000)

        for aid in agent_ids:
            assert abs(exact[aid] - approx[aid]) < 0.1, (
                f"Agent {aid}: exact={exact[aid]:.3f} approx={approx[aid]:.3f}"
            )


# ---------------------------------------------------------------------------
# Fix 3: Registry.all() Caching
# ---------------------------------------------------------------------------

class TestRegistryCaching:
    @pytest.fixture
    def registry(self):
        return AgentRegistry()

    @pytest.mark.asyncio
    async def test_cached_list_is_same_object(self, registry):
        """Consecutive calls to all() without changes return the same list object."""
        await registry.register(_FakeAgent("a1"))

        list1 = registry.all()
        list2 = registry.all()
        assert list1 is list2  # Same object reference

    @pytest.mark.asyncio
    async def test_cache_invalidated_on_register(self, registry):
        """Registering a new agent invalidates the cache."""
        await registry.register(_FakeAgent("a1"))
        list1 = registry.all()

        await registry.register(_FakeAgent("a2"))
        list2 = registry.all()

        assert list1 is not list2  # Different object
        assert len(list2) == 2

    @pytest.mark.asyncio
    async def test_cache_invalidated_on_unregister(self, registry):
        """Unregistering an agent invalidates the cache."""
        await registry.register(_FakeAgent("a1"))
        await registry.register(_FakeAgent("a2"))
        list1 = registry.all()

        await registry.unregister("a1")
        list2 = registry.all()

        assert list1 is not list2
        assert len(list2) == 1

    @pytest.mark.asyncio
    async def test_cached_list_reflects_current_state(self, registry):
        """The cached list correctly reflects the current set of agents."""
        await registry.register(_FakeAgent("a1"))
        await registry.register(_FakeAgent("a2"))
        await registry.register(_FakeAgent("a3"))

        agents = registry.all()
        ids = {a.id for a in agents}
        assert ids == {"a1", "a2", "a3"}
