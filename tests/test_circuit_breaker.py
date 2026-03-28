"""AD-488: Cognitive Circuit Breaker tests."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.circuit_breaker import (
    BreakerState,
    CognitiveCircuitBreaker,
)


# ── Core circuit breaker tests ──


class TestBreakerCore:
    """Core circuit breaker state machine and detection tests."""

    def test_breaker_starts_closed(self):
        """New breaker state is CLOSED. should_allow_think() returns True."""
        cb = CognitiveCircuitBreaker()
        assert cb.should_allow_think("agent_001") is True
        status = cb.get_status("agent_001")
        assert status["state"] == "closed"
        assert status["trip_count"] == 0

    def test_velocity_trips_breaker(self):
        """Record N events within the velocity window → breaker trips."""
        cb = CognitiveCircuitBreaker(velocity_threshold=5, velocity_window_seconds=300.0)
        for i in range(5):
            cb.record_event("agent_001", "proactive_think", f"thought content {i}")
        tripped = cb.check_and_trip("agent_001")
        assert tripped is True
        status = cb.get_status("agent_001")
        assert status["state"] == "open"
        assert status["trip_count"] == 1

    def test_velocity_below_threshold_no_trip(self):
        """Record N-1 events → breaker does NOT trip."""
        cb = CognitiveCircuitBreaker(velocity_threshold=5, velocity_window_seconds=300.0)
        for i in range(4):
            cb.record_event("agent_001", "proactive_think", f"thought content {i}")
        tripped = cb.check_and_trip("agent_001")
        assert tripped is False
        assert cb.get_status("agent_001")["state"] == "closed"

    def test_similarity_trips_breaker(self):
        """Events with high Jaccard overlap → breaker trips on similarity signal."""
        cb = CognitiveCircuitBreaker(
            velocity_threshold=100,  # Disable velocity
            similarity_threshold=0.6,
            similarity_min_events=4,
        )
        # All events share >60% words
        base = "the medical diagnostic analysis shows critical patient status"
        for i in range(5):
            # Minor variations that keep high Jaccard
            cb.record_event("agent_001", "proactive_think", f"{base} iteration {i}")
        tripped = cb.check_and_trip("agent_001")
        assert tripped is True
        assert cb.get_status("agent_001")["state"] == "open"

    def test_dissimilar_events_no_trip(self):
        """Events with genuinely different content → breaker does NOT trip."""
        cb = CognitiveCircuitBreaker(
            velocity_threshold=100,  # Disable velocity
            similarity_threshold=0.6,
            similarity_min_events=4,
        )
        topics = [
            "the warp drive needs recalibration for efficiency",
            "crew morale has improved significantly this week",
            "external sensor array detected unusual subspace anomaly",
            "medical supplies inventory requires immediate restocking",
            "security protocols updated for new threat assessment",
        ]
        for topic in topics:
            cb.record_event("agent_001", "proactive_think", topic)
        tripped = cb.check_and_trip("agent_001")
        assert tripped is False
        assert cb.get_status("agent_001")["state"] == "closed"

    def test_open_blocks_think(self):
        """Trip the breaker → should_allow_think() returns False."""
        cb = CognitiveCircuitBreaker(velocity_threshold=3, velocity_window_seconds=300.0)
        for i in range(3):
            cb.record_event("agent_001", "proactive_think", f"content {i}")
        cb.check_and_trip("agent_001")
        assert cb.should_allow_think("agent_001") is False

    def test_cooldown_transitions_to_half_open(self):
        """After cooldown elapses → HALF_OPEN, should_allow_think() returns True."""
        cb = CognitiveCircuitBreaker(
            velocity_threshold=3,
            velocity_window_seconds=300.0,
            base_cooldown_seconds=1.0,  # Short for testing
        )
        for i in range(3):
            cb.record_event("agent_001", "proactive_think", f"content {i}")
        cb.check_and_trip("agent_001")
        assert cb.should_allow_think("agent_001") is False

        # Fast-forward past cooldown
        state = cb._get_state("agent_001")
        state.tripped_at = time.monotonic() - 2.0  # 2s ago, cooldown is 1s
        assert cb.should_allow_think("agent_001") is True
        assert state.state == BreakerState.HALF_OPEN

    def test_half_open_recovery_closes(self):
        """In HALF_OPEN with no signals → transitions to CLOSED."""
        cb = CognitiveCircuitBreaker(
            velocity_threshold=100,  # High threshold so probe doesn't re-trip
            velocity_window_seconds=300.0,
            base_cooldown_seconds=1.0,
        )
        # Trip it
        state = cb._get_state("agent_001")
        state.state = BreakerState.HALF_OPEN
        state.trip_count = 1
        state.tripped_at = time.monotonic() - 10.0

        # Record a single clean event (won't hit velocity or similarity)
        cb.record_event("agent_001", "proactive_think", "completely fresh new topic")

        tripped = cb.check_and_trip("agent_001")
        assert tripped is False
        assert state.state == BreakerState.CLOSED

    def test_half_open_re_trips(self):
        """In HALF_OPEN with signals still firing → re-trips with escalated cooldown."""
        cb = CognitiveCircuitBreaker(
            velocity_threshold=3,
            velocity_window_seconds=300.0,
            base_cooldown_seconds=100.0,
        )
        # First trip
        for i in range(3):
            cb.record_event("agent_001", "proactive_think", f"content {i}")
        cb.check_and_trip("agent_001")
        assert cb.get_status("agent_001")["trip_count"] == 1
        first_cooldown = cb.get_status("agent_001")["cooldown_seconds"]

        # Move to HALF_OPEN
        state = cb._get_state("agent_001")
        state.state = BreakerState.HALF_OPEN

        # Add more events (still above velocity threshold)
        cb.record_event("agent_001", "proactive_think", "still ruminating")

        tripped = cb.check_and_trip("agent_001")
        assert tripped is True
        assert state.state == BreakerState.OPEN
        assert cb.get_status("agent_001")["trip_count"] == 2
        # Cooldown should have escalated
        assert cb.get_status("agent_001")["cooldown_seconds"] == first_cooldown * 2

    def test_escalating_cooldown(self):
        """Trip 3 times → cooldown doubles each time, capped at max."""
        cb = CognitiveCircuitBreaker(
            velocity_threshold=2,
            velocity_window_seconds=300.0,
            base_cooldown_seconds=100.0,
            max_cooldown_seconds=500.0,
        )

        # Trip 1
        cb.record_event("agent_001", "proactive_think", "a")
        cb.record_event("agent_001", "proactive_think", "b")
        cb.check_and_trip("agent_001")
        assert cb.get_status("agent_001")["cooldown_seconds"] == 100.0

        # Reset state to HALF_OPEN, clear events, trip again
        state = cb._get_state("agent_001")
        state.state = BreakerState.HALF_OPEN
        state.events.clear()
        cb.record_event("agent_001", "proactive_think", "c")
        cb.record_event("agent_001", "proactive_think", "d")
        cb.check_and_trip("agent_001")
        assert cb.get_status("agent_001")["cooldown_seconds"] == 200.0

        # Trip 3 — would be 400 but capped at 500
        state.state = BreakerState.HALF_OPEN
        state.events.clear()
        cb.record_event("agent_001", "proactive_think", "e")
        cb.record_event("agent_001", "proactive_think", "f")
        cb.check_and_trip("agent_001")
        assert cb.get_status("agent_001")["cooldown_seconds"] == 400.0

        # Trip 4 — would be 800 but capped at 500
        state.state = BreakerState.HALF_OPEN
        state.events.clear()
        cb.record_event("agent_001", "proactive_think", "g")
        cb.record_event("agent_001", "proactive_think", "h")
        cb.check_and_trip("agent_001")
        assert cb.get_status("agent_001")["cooldown_seconds"] == 500.0

    def test_attention_redirect_after_trip(self):
        """After trip + cooldown → get_attention_redirect() returns prompt."""
        cb = CognitiveCircuitBreaker(
            velocity_threshold=2,
            velocity_window_seconds=300.0,
            base_cooldown_seconds=10.0,
        )
        # Trip
        cb.record_event("agent_001", "proactive_think", "a")
        cb.record_event("agent_001", "proactive_think", "b")
        cb.check_and_trip("agent_001")

        # While OPEN, no redirect
        assert cb.get_attention_redirect("agent_001") is None

        # Move to HALF_OPEN
        state = cb._get_state("agent_001")
        state.state = BreakerState.HALF_OPEN

        redirect = cb.get_attention_redirect("agent_001")
        assert redirect is not None
        assert "circuit breaker" in redirect.lower()
        assert "trip #1" in redirect

    def test_no_redirect_when_never_tripped(self):
        """Fresh agent → get_attention_redirect() returns None."""
        cb = CognitiveCircuitBreaker()
        assert cb.get_attention_redirect("agent_001") is None

    def test_reset_agent_clears_state(self):
        """Trip breaker, reset agent → state is gone."""
        cb = CognitiveCircuitBreaker(velocity_threshold=2, velocity_window_seconds=300.0)
        cb.record_event("agent_001", "proactive_think", "a")
        cb.record_event("agent_001", "proactive_think", "b")
        cb.check_and_trip("agent_001")
        assert cb.get_status("agent_001")["trip_count"] == 1

        cb.reset_agent("agent_001")
        assert cb.get_status("agent_001")["trip_count"] == 0
        assert cb.get_status("agent_001")["state"] == "closed"


# ── Integration with proactive loop ──


def _make_loop():
    """Create a ProactiveCognitiveLoop with mocked runtime."""
    from probos.proactive import ProactiveCognitiveLoop

    loop = ProactiveCognitiveLoop(interval=60, cooldown=60)
    rt = MagicMock()
    rt.ward_room = MagicMock()
    rt.ward_room.list_channels = AsyncMock(return_value=[])
    rt.ward_room.create_thread = AsyncMock()
    rt.ward_room.get_thread = AsyncMock(return_value=None)
    rt.ward_room.get_recent_activity = AsyncMock(return_value=[])
    rt.trust_network = MagicMock()
    rt.trust_network.get_score = MagicMock(return_value=0.6)
    rt.trust_network.record_outcome = MagicMock(return_value=0.6)
    rt._extract_endorsements = MagicMock(return_value=("", []))
    rt._records_store = MagicMock()
    rt._records_store.write_notebook = AsyncMock()
    rt.ontology = None
    rt.callsign_registry = MagicMock()
    rt.callsign_registry.get_callsign = MagicMock(return_value="TestAgent")
    rt.config = MagicMock()
    rt.config.communications = MagicMock(dm_min_rank="ensign")
    rt.episodic_memory = None
    rt.bridge_alerts = None
    rt.event_log = None
    rt.skill_service = None
    rt.hebbian_router = None
    rt._is_crew_agent = MagicMock(return_value=True)
    rt.acm = None
    rt.registry = MagicMock()
    rt.dream_scheduler = None
    loop.set_runtime(rt)
    return loop, rt


class TestProactiveIntegration:
    """Integration tests: circuit breaker within ProactiveCognitiveLoop."""

    @pytest.mark.asyncio
    async def test_proactive_skips_open_breaker(self):
        """Agent with OPEN breaker is skipped in _run_cycle."""
        loop, rt = _make_loop()

        agent = MagicMock()
        agent.id = "agent_001"
        agent.agent_type = "scout"
        agent.callsign = "Atlas"
        agent.is_alive = True
        agent.handle_intent = AsyncMock()
        rt.registry.all = MagicMock(return_value=[agent])

        # Trip the breaker for this agent
        loop.circuit_breaker._trip("agent_001", "test trip")

        await loop._run_cycle()
        # Agent's handle_intent should NOT have been called
        agent.handle_intent.assert_not_called()

    @pytest.mark.asyncio
    async def test_bridge_alert_on_trip(self):
        """Breaker trip fires a bridge alert event."""
        events: list[dict] = []
        loop, rt = _make_loop()
        loop._on_event = lambda e: events.append(e)

        # Configure breaker with low threshold for easy tripping
        loop._circuit_breaker = CognitiveCircuitBreaker(
            velocity_threshold=2, velocity_window_seconds=300.0,
        )

        agent = MagicMock()
        agent.id = "agent_001"
        agent.agent_type = "scout"
        agent.callsign = "Atlas"
        agent.is_alive = True
        agent.confidence = 0.8

        # Mock a successful proactive think with enough content to trigger
        result = MagicMock()
        result.success = True
        result.result = "I observed something interesting about the systems."
        agent.handle_intent = AsyncMock(return_value=result)

        # Pre-record events so the next check_and_trip will trigger
        loop._circuit_breaker.record_event("agent_001", "proactive_think", "thought 1")

        from probos.crew_profile import Rank
        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.6)

        # Should have fired a bridge alert
        bridge_alerts = [e for e in events if e.get("type") == "bridge_alert"]
        assert len(bridge_alerts) == 1
        alert = bridge_alerts[0]
        assert alert["source"] == "circuit_breaker"
        assert alert["severity"] == "warning"
        assert "health protection" in alert["detail"]

    def test_no_response_counts_toward_velocity(self):
        """Empty no-response events contribute to velocity but not similarity."""
        cb = CognitiveCircuitBreaker(
            velocity_threshold=4,
            velocity_window_seconds=300.0,
            similarity_threshold=0.6,
            similarity_min_events=4,
        )
        # Record 4 no-response events (empty content)
        for _ in range(4):
            cb.record_event("agent_001", "no_response", "")
        tripped = cb.check_and_trip("agent_001")
        assert tripped is True  # Velocity signal fired
        status = cb.get_status("agent_001")
        assert status["state"] == "open"

    @pytest.mark.asyncio
    async def test_context_includes_redirect_after_recovery(self):
        """After breaker recovery, _gather_context includes redirect."""
        loop, rt = _make_loop()

        agent = MagicMock()
        agent.id = "agent_001"
        agent.agent_type = "scout"
        agent.is_alive = True

        # Trip and move to HALF_OPEN
        loop._circuit_breaker._trip("agent_001", "test")
        state = loop._circuit_breaker._get_state("agent_001")
        state.state = BreakerState.HALF_OPEN

        context = await loop._gather_context(agent, 0.6)
        assert "circuit_breaker_redirect" in context
        assert "circuit breaker" in context["circuit_breaker_redirect"].lower()


# ── API endpoint test ──


class TestCircuitBreakerAPI:
    """API endpoint for circuit breaker status."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_api_returns_statuses(self):
        """GET /api/system/circuit-breakers returns breaker states with callsign."""
        from probos.api import create_app
        from httpx import AsyncClient, ASGITransport

        rt = MagicMock()
        rt.ward_room = MagicMock()
        rt.registry = MagicMock()

        # Create a mock proactive loop with circuit breaker
        proactive_loop = MagicMock()
        cb = CognitiveCircuitBreaker()
        cb.record_event("agent_001", "proactive_think", "some thought")
        proactive_loop.circuit_breaker = cb
        rt.proactive_loop = proactive_loop

        # Mock agent for callsign enrichment
        mock_agent = MagicMock()
        mock_agent.callsign = "Atlas"
        mock_agent.agent_type = "scout"
        rt.registry.get = MagicMock(return_value=mock_agent)

        app = create_app(rt)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/system/circuit-breakers")
            assert resp.status_code == 200
            data = resp.json()
            assert "breakers" in data
            assert len(data["breakers"]) == 1
            breaker = data["breakers"][0]
            assert breaker["agent_id"] == "agent_001"
            assert breaker["state"] == "closed"
            assert breaker["callsign"] == "Atlas"
