"""AD-576: LLM Unavailability Awareness — EPS Power Brownout Protocol tests."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.crew_profile import CallsignRegistry
from probos.events import EventType, LlmHealthChangedEvent
from probos.knowledge.records_store import RecordsStore
from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent
from probos.substrate.registry import AgentRegistry
from probos.ward_room import WardRoomService
from probos.ward_room_router import WardRoomRouter
from probos.cognitive.circuit_breaker import (
    CognitiveCircuitBreaker,
    CognitiveEvent,
)


# ── Helper ──


def _make_loop(**kwargs):
    """Create a ProactiveCognitiveLoop with mocked runtime."""
    from probos.proactive import ProactiveCognitiveLoop

    loop = ProactiveCognitiveLoop(interval=60, cooldown=60, **kwargs)
    rt = MagicMock(spec=ProbOSRuntime)
    rt.ward_room = MagicMock(spec=WardRoomService)
    rt.ward_room.list_channels = AsyncMock(return_value=[])
    rt.ward_room.create_thread = AsyncMock()
    rt.ward_room.get_thread = AsyncMock(return_value=None)
    rt.ward_room.get_recent_activity = AsyncMock(return_value=[])
    rt.trust_network = MagicMock(spec=TrustNetwork)
    rt.trust_network.get_score = MagicMock(return_value=0.6)
    rt.trust_network.record_outcome = MagicMock(return_value=0.6)
    rt.ward_room_router = MagicMock(spec=WardRoomRouter)
    rt.ward_room_router.extract_endorsements = MagicMock(return_value=("", []))
    rt.ward_room_router.deliver_bridge_alert = AsyncMock()
    rt._records_store = MagicMock(spec=RecordsStore)
    rt._records_store.write_notebook = AsyncMock()
    rt.ontology = None
    rt.callsign_registry = MagicMock(spec=CallsignRegistry)
    rt.callsign_registry.get_callsign = MagicMock(return_value="TestAgent")
    rt.config = MagicMock(spec=SystemConfig)
    rt.config.communications = MagicMock(dm_min_rank="ensign")
    rt.episodic_memory = None
    rt.bridge_alerts = MagicMock()
    rt.event_log = None
    rt.skill_service = None
    rt.hebbian_router = None
    rt.acm = None
    rt.registry = MagicMock(spec=AgentRegistry)
    loop.set_runtime(rt)
    return loop, rt


# ── LLM Status State Machine ──


class TestLlmStatusStateMachine:
    """Tests for the LLM status state machine in ProactiveCognitiveLoop."""

    def test_initial_llm_status_is_operational(self):
        """New ProactiveCognitiveLoop starts with operational status."""
        loop, _ = _make_loop()
        assert loop._llm_status == "operational"

    @pytest.mark.asyncio
    async def test_status_transition_operational_to_degraded(self):
        """BF-228: 3+ failures transitions operational -> degraded."""
        loop, _ = _make_loop()
        loop._llm_failure_count = 3
        await loop._update_llm_status(failure=True)
        assert loop._llm_status == "degraded"

    @pytest.mark.asyncio
    async def test_status_transition_degraded_to_offline(self):
        """BF-228: 6+ failures transition degraded -> offline."""
        loop, _ = _make_loop()
        loop._llm_status = "degraded"
        loop._llm_failure_count = 6
        await loop._update_llm_status(failure=True)
        assert loop._llm_status == "offline"

    @pytest.mark.asyncio
    async def test_status_transition_offline_to_operational(self):
        """Success after offline transitions to operational and resets offline_since."""
        loop, _ = _make_loop()
        loop._llm_status = "offline"
        loop._llm_offline_since = time.monotonic() - 60
        loop._llm_failure_count = 0
        await loop._update_llm_status(failure=False)
        assert loop._llm_status == "operational"
        assert loop._llm_offline_since == 0.0

    @pytest.mark.asyncio
    async def test_no_event_when_status_unchanged(self):
        """No event emitted when status stays the same."""
        events = []
        loop, _ = _make_loop(on_event=lambda d: events.append(d))
        loop._llm_status = "degraded"
        loop._llm_failure_count = 2
        await loop._update_llm_status(failure=True)
        # Still degraded (count < 3)
        assert loop._llm_status == "degraded"
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_event_emitted_on_transition(self):
        """LLM_HEALTH_CHANGED event emitted on status transition."""
        events = []
        loop, _ = _make_loop(on_event=lambda d: events.append(d))
        loop._llm_failure_count = 3
        await loop._update_llm_status(failure=True)
        assert len(events) == 1
        assert events[0]["type"] == EventType.LLM_HEALTH_CHANGED.value
        assert events[0]["data"]["old_status"] == "operational"
        assert events[0]["data"]["new_status"] == "degraded"


# ── Bridge Alerts ──


class TestLlmBridgeAlerts:
    """Tests for Bridge Alert emission on LLM status transitions."""

    @pytest.mark.asyncio
    async def test_bridge_alert_on_offline(self):
        """Offline transition emits ALERT-severity bridge alert."""
        loop, rt = _make_loop()
        loop._llm_status = "degraded"
        loop._llm_failure_count = 6
        loop._llm_offline_since = time.monotonic() - 10
        await loop._update_llm_status(failure=True)

        rt.ward_room_router.deliver_bridge_alert.assert_called_once()
        alert = rt.ward_room_router.deliver_bridge_alert.call_args[0][0]
        assert alert.alert_type == "llm_offline"
        from probos.bridge_alerts import AlertSeverity
        assert alert.severity == AlertSeverity.ALERT

    @pytest.mark.asyncio
    async def test_bridge_alert_on_degraded(self):
        """Degraded transition emits ADVISORY-severity bridge alert."""
        loop, rt = _make_loop()
        loop._llm_failure_count = 3
        await loop._update_llm_status(failure=True)

        rt.ward_room_router.deliver_bridge_alert.assert_called_once()
        alert = rt.ward_room_router.deliver_bridge_alert.call_args[0][0]
        assert alert.alert_type == "llm_degraded"
        from probos.bridge_alerts import AlertSeverity
        assert alert.severity == AlertSeverity.ADVISORY

    @pytest.mark.asyncio
    async def test_bridge_alert_on_recovery(self):
        """Recovery transition emits INFO-severity bridge alert with downtime."""
        loop, rt = _make_loop()
        loop._llm_status = "offline"
        loop._llm_offline_since = time.monotonic() - 120
        loop._llm_failure_count = 0
        await loop._update_llm_status(failure=False)

        rt.ward_room_router.deliver_bridge_alert.assert_called_once()
        alert = rt.ward_room_router.deliver_bridge_alert.call_args[0][0]
        assert alert.alert_type == "llm_restored"
        from probos.bridge_alerts import AlertSeverity
        assert alert.severity == AlertSeverity.INFO
        assert "downtime" in alert.detail.lower()

    @pytest.mark.asyncio
    async def test_no_bridge_alert_when_no_runtime(self):
        """No exception when runtime is None."""
        loop, _ = _make_loop()
        loop._runtime = None
        loop._llm_failure_count = 3
        # Should not raise
        await loop._update_llm_status(failure=True)
        assert loop._llm_status == "degraded"


# ── Infrastructure Context Injection ──


class TestInfrastructureContext:
    """Tests for infrastructure context injection into _gather_context()."""

    @pytest.mark.asyncio
    async def test_gather_context_includes_infrastructure_when_degraded(self):
        """Infrastructure status present when LLM is degraded."""
        loop, _ = _make_loop()
        loop._llm_status = "degraded"
        loop._llm_failure_count = 2

        agent = MagicMock(spec=BaseAgent)
        agent.id = "agent_001"
        agent.agent_type = "scout"
        agent.is_alive = True

        context = await loop._gather_context(agent, 0.6)
        assert "infrastructure_status" in context
        assert context["infrastructure_status"]["llm_status"] == "degraded"

    @pytest.mark.asyncio
    async def test_gather_context_excludes_infrastructure_when_operational(self):
        """No infrastructure status when LLM is operational."""
        loop, _ = _make_loop()
        loop._llm_status = "operational"

        agent = MagicMock(spec=BaseAgent)
        agent.id = "agent_001"
        agent.agent_type = "scout"
        agent.is_alive = True

        context = await loop._gather_context(agent, 0.6)
        assert "infrastructure_status" not in context

    @pytest.mark.asyncio
    async def test_build_user_message_renders_infrastructure_note(self):
        """_build_user_message includes INFRASTRUCTURE NOTE when status present."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._working_memory = None

        observation = {
            "intent": "proactive_think",
            "params": {
                "context_parts": {
                    "infrastructure_status": {
                        "llm_status": "degraded",
                        "message": "The ship's communications array (LLM backend) is currently degraded.",
                    },
                },
                "trust_score": 0.5,
                "agency_level": "suggestive",
            },
            "timestamp": time.time(),
        }

        result = await agent._build_user_message(observation)
        assert "INFRASTRUCTURE NOTE" in result
        assert "communications array" in result.lower()

    @pytest.mark.asyncio
    async def test_build_user_message_no_infrastructure_note_when_healthy(self):
        """No INFRASTRUCTURE NOTE when infrastructure_status absent."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._working_memory = None

        observation = {
            "intent": "proactive_think",
            "params": {
                "context_parts": {},
                "trust_score": 0.5,
                "agency_level": "suggestive",
            },
            "timestamp": time.time(),
        }

        result = await agent._build_user_message(observation)
        assert "INFRASTRUCTURE NOTE" not in result


# ── Circuit Breaker Infrastructure Filtering ──


class TestCircuitBreakerInfraFiltering:
    """Tests for infrastructure_degraded flag and signal filtering."""

    def test_cognitive_event_has_infrastructure_flag_default_false(self):
        """CognitiveEvent defaults infrastructure_degraded to False."""
        event = CognitiveEvent(
            timestamp=time.monotonic(),
            event_type="proactive_think",
            content_fingerprint=set(),
            agent_id="a1",
        )
        assert event.infrastructure_degraded is False

    def test_record_event_passes_infrastructure_flag(self):
        """record_event passes infrastructure_degraded to CognitiveEvent."""
        cb = CognitiveCircuitBreaker()
        cb.record_event("a1", "proactive_think", "hello world", infrastructure_degraded=True)
        state = cb._get_state("a1")
        assert len(state.events) == 1
        assert state.events[0].infrastructure_degraded is True

    def test_compute_signals_excludes_infrastructure_events(self):
        """Infrastructure-correlated events excluded from velocity count."""
        cb = CognitiveCircuitBreaker(velocity_threshold=5, velocity_window_seconds=300.0)
        # 3 infra events + 2 normal
        for _ in range(3):
            cb.record_event("a1", "proactive_think", "infra event", infrastructure_degraded=True)
        for _ in range(2):
            cb.record_event("a1", "proactive_think", "normal event")
        signals = cb._compute_signals("a1")
        assert signals["velocity_count"] == 2

    def test_compute_signals_uses_only_normal_for_similarity(self):
        """Similarity computation uses only non-infrastructure events."""
        cb = CognitiveCircuitBreaker(
            velocity_threshold=20,
            velocity_window_seconds=300.0,
            similarity_min_events=3,
        )
        # 4 infra events (identical content — would trigger similarity if counted)
        for _ in range(4):
            cb.record_event("a1", "proactive_think", "identical repeated content here", infrastructure_degraded=True)
        # 4 normal events (completely different content from each other)
        distinct_content = [
            "alpha bravo charlie delta foxtrot",
            "golf hotel india juliet kilo lima",
            "mike november oscar papa quebec romeo",
            "sierra tango uniform victor whiskey xray",
        ]
        for content in distinct_content:
            cb.record_event("a1", "proactive_think", content)
        signals = cb._compute_signals("a1")
        # Normal events are totally diverse — similarity should be zero
        assert signals["similarity_ratio"] < 0.5

    def test_all_infrastructure_events_produces_zero_signals(self):
        """All infra events -> velocity_count 0, similarity_ratio 0."""
        cb = CognitiveCircuitBreaker(velocity_threshold=5, velocity_window_seconds=300.0)
        for _ in range(10):
            cb.record_event("a1", "proactive_think", "same content", infrastructure_degraded=True)
        signals = cb._compute_signals("a1")
        assert signals["velocity_count"] == 0
        assert signals["similarity_ratio"] == 0.0


# ── Counselor Gating ──


class TestCounselorGating:
    """Tests for Counselor suppression of infrastructure-correlated concerns."""

    @pytest.mark.asyncio
    async def test_counselor_suppresses_infrastructure_correlated_concern(self):
        """_on_self_monitoring_concern returns early when infrastructure_correlated=True."""
        from probos.cognitive.counselor import CounselorAgent

        counselor = CounselorAgent.__new__(CounselorAgent)
        counselor.id = "counselor_001"
        counselor._gather_agent_metrics = MagicMock()
        counselor.assess_agent = MagicMock()

        data = {
            "agent_id": "a1",
            "agent_callsign": "Cortez",
            "zone": "amber",
            "similarity_ratio": 0.8,
            "velocity_ratio": 0.5,
            "infrastructure_correlated": True,
        }
        await counselor._on_self_monitoring_concern(data)
        counselor.assess_agent.assert_not_called()

    @pytest.mark.asyncio
    async def test_counselor_processes_non_infrastructure_concern(self):
        """_on_self_monitoring_concern processes when infrastructure_correlated=False."""
        from probos.cognitive.counselor import CounselorAgent

        counselor = CounselorAgent.__new__(CounselorAgent)
        counselor.id = "counselor_001"
        counselor._gather_agent_metrics = MagicMock(return_value={
            "trust_score": 0.5,
            "confidence": 0.5,
            "hebbian_avg": 0.0,
            "success_rate": 1.0,
            "personality_drift": 0.0,
        })
        counselor.assess_agent = MagicMock(return_value=MagicMock())
        counselor._save_profile_and_assessment = AsyncMock()

        data = {
            "agent_id": "a1",
            "agent_callsign": "Cortez",
            "zone": "amber",
            "similarity_ratio": 0.8,
            "velocity_ratio": 0.5,
            "infrastructure_correlated": False,
        }
        await counselor._on_self_monitoring_concern(data)
        counselor.assess_agent.assert_called_once()


# ── BF-116: Dead Context Removal + AD-567g Completion ──


class TestBF116AndAD567g:
    """Tests for dead circuit_breaker_redirect removal and orientation_supplement wiring."""

    @pytest.mark.asyncio
    async def test_gather_context_no_circuit_breaker_redirect(self):
        """BF-116: circuit_breaker_redirect no longer in _gather_context output."""
        loop, _ = _make_loop()
        agent = MagicMock(spec=BaseAgent)
        agent.id = "agent_001"
        agent.agent_type = "scout"
        agent.is_alive = True

        context = await loop._gather_context(agent, 0.6)
        assert "circuit_breaker_redirect" not in context

    @pytest.mark.asyncio
    async def test_gather_context_includes_orientation_supplement_for_young_agent(self):
        """AD-567g: orientation_supplement in context for agents within orientation window."""
        loop, rt = _make_loop()

        # Setup orientation service
        mock_orient_svc = MagicMock()
        mock_orient_svc.build_orientation = MagicMock(return_value=MagicMock(
            __dataclass_fields__=MagicMock(values=MagicMock(return_value=[]))
        ))
        mock_orient_svc.render_proactive_orientation = MagicMock(
            return_value="ORIENTATION ACTIVE: Ground observations in evidence."
        )
        loop._orientation_service = mock_orient_svc

        # Config with orientation enabled
        from probos.config import SystemConfig
        orient_cfg = MagicMock()
        orient_cfg.proactive_supplement = True
        orient_cfg.orientation_window_seconds = 3600
        rt.config.orientation = orient_cfg
        loop._config = MagicMock()

        agent = MagicMock(spec=BaseAgent)
        agent.id = "agent_001"
        agent.agent_type = "scout"
        agent.is_alive = True
        agent._birth_timestamp = time.time() - 60  # Born 60s ago, within 3600s window

        # Mock OrientationContext dataclass
        from unittest.mock import patch as mock_patch
        with mock_patch("probos.proactive.OrientationContext") as MockOC:
            MockOC.return_value = MagicMock()
            context = await loop._gather_context(agent, 0.6)

        assert "orientation_supplement" in context
        assert "ORIENTATION" in context["orientation_supplement"]

    @pytest.mark.asyncio
    async def test_build_user_message_renders_orientation_supplement(self):
        """_build_user_message includes orientation_supplement content."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._working_memory = None

        observation = {
            "intent": "proactive_think",
            "params": {
                "context_parts": {
                    "orientation_supplement": "ORIENTATION: Ground claims in evidence.",
                },
                "trust_score": 0.5,
                "agency_level": "suggestive",
            },
            "timestamp": time.time(),
        }
        result = await agent._build_user_message(observation)
        assert "ORIENTATION: Ground claims in evidence." in result

    @pytest.mark.asyncio
    async def test_build_user_message_no_orientation_supplement_when_absent(self):
        """No orientation text when orientation_supplement absent from context."""
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._working_memory = None

        observation = {
            "intent": "proactive_think",
            "params": {
                "context_parts": {},
                "trust_score": 0.5,
                "agency_level": "suggestive",
            },
            "timestamp": time.time(),
        }
        result = await agent._build_user_message(observation)
        assert "ORIENTATION:" not in result


# ── BF-117: Convergence Bridge Alert Fix ──


class TestBF117ConvergenceAlertFix:
    """Tests for corrected convergence/divergence bridge alert delivery."""

    @pytest.mark.asyncio
    async def test_convergence_bridge_alert_uses_correct_attributes(self):
        """_emit_convergence_bridge_alert uses public bridge_alerts + ward_room_router."""
        loop, rt = _make_loop()
        mock_alert = MagicMock()
        rt.bridge_alerts.check_realtime_convergence = MagicMock(return_value=[mock_alert])

        conv_result = {"topic": "test", "agents": ["a1", "a2"]}
        await loop._emit_convergence_bridge_alert(conv_result)

        rt.bridge_alerts.check_realtime_convergence.assert_called_once_with(conv_result)
        rt.ward_room_router.deliver_bridge_alert.assert_called_once_with(mock_alert)

    @pytest.mark.asyncio
    async def test_divergence_bridge_alert_uses_correct_attributes(self):
        """_emit_divergence_bridge_alert uses public bridge_alerts + ward_room_router."""
        loop, rt = _make_loop()
        mock_alert = MagicMock()
        rt.bridge_alerts.check_divergence = MagicMock(return_value=[mock_alert])

        conv_result = {"topic": "test", "agents": ["a1", "a2"]}
        await loop._emit_divergence_bridge_alert(conv_result)

        rt.bridge_alerts.check_divergence.assert_called_once_with(conv_result)
        rt.ward_room_router.deliver_bridge_alert.assert_called_once_with(mock_alert)


# ── Integration ──


class TestLlmStatusIntegration:
    """End-to-end flow tests for failure/recovery cycles."""

    @pytest.mark.asyncio
    async def test_failure_cycle_full_flow(self):
        """BF-228: 6 consecutive failures: operational -> degraded -> offline with events."""
        events = []
        loop, rt = _make_loop(on_event=lambda d: events.append(d))

        # Simulate 6 failures (BF-228: degraded at 3, offline at 6)
        for i in range(6):
            loop._llm_failure_count = i + 1
            await loop._update_llm_status(failure=True)

        assert loop._llm_status == "offline"
        # Two transitions: operational->degraded (at 3), degraded->offline (at 6)
        health_events = [e for e in events if e.get("type") == EventType.LLM_HEALTH_CHANGED.value]
        assert len(health_events) == 2
        assert health_events[0]["data"]["old_status"] == "operational"
        assert health_events[0]["data"]["new_status"] == "degraded"
        assert health_events[1]["data"]["old_status"] == "degraded"
        assert health_events[1]["data"]["new_status"] == "offline"
        # Bridge alerts delivered twice
        assert rt.ward_room_router.deliver_bridge_alert.call_count == 2

    @pytest.mark.asyncio
    async def test_recovery_cycle_full_flow(self):
        """Recovery from offline: offline -> operational with downtime in alert."""
        events = []
        loop, rt = _make_loop(on_event=lambda d: events.append(d))
        loop._llm_status = "offline"
        loop._llm_offline_since = time.monotonic() - 120
        loop._llm_failure_count = 0

        await loop._update_llm_status(failure=False)

        assert loop._llm_status == "operational"
        assert loop._llm_failure_count == 0
        assert loop._llm_offline_since == 0.0  # Reset after alert delivery

        # Recovery event emitted
        health_events = [e for e in events if e.get("type") == EventType.LLM_HEALTH_CHANGED.value]
        assert len(health_events) == 1
        assert health_events[0]["data"]["old_status"] == "offline"
        assert health_events[0]["data"]["new_status"] == "operational"
        assert health_events[0]["data"]["downtime_seconds"] > 0

        # Recovery bridge alert
        rt.ward_room_router.deliver_bridge_alert.assert_called_once()
        alert = rt.ward_room_router.deliver_bridge_alert.call_args[0][0]
        assert alert.alert_type == "llm_restored"
        assert "downtime" in alert.detail.lower()
