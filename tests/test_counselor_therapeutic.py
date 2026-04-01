"""AD-505: Counselor Therapeutic Intervention — tests."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.counselor import (
    COUNSELOR_WELLNESS_YELLOW,
    CounselorAssessment,
    CounselorAgent,
)


def _make_assessment(
    agent_id: str = "agent-1",
    wellness: float = 0.3,
    fit: bool = False,
    concerns: list[str] | None = None,
    recommendations: list[str] | None = None,
    trigger: str = "manual",
) -> CounselorAssessment:
    return CounselorAssessment(
        timestamp=time.time(),
        agent_id=agent_id,
        trigger=trigger,
        wellness_score=wellness,
        fit_for_duty=fit,
        concerns=concerns or ["Repetitive output detected"],
        recommendations=recommendations or ["Redirect attention"],
    )


def _make_counselor(**kwargs: Any) -> CounselorAgent:
    """Create a minimal CounselorAgent for testing."""
    agent = CounselorAgent.__new__(CounselorAgent)
    agent._agent_type = "counselor"
    agent.id = "counselor-001"
    agent.callsign = "Counselor"
    agent._ward_room = kwargs.get("ward_room")
    agent._ward_room_router = kwargs.get("ward_room_router")
    agent._directive_store = kwargs.get("directive_store")
    agent._dream_scheduler = kwargs.get("dream_scheduler")
    agent._proactive_loop = kwargs.get("proactive_loop")
    agent._registry = kwargs.get("registry")
    agent._dm_cooldowns = {}
    agent._cognitive_profiles = {}
    agent._emit_event_fn = kwargs.get("emit_event_fn")
    agent._trust_network = None
    agent._hebbian_router = None
    agent._crew_profiles = None
    agent._episodic_memory = None
    agent._add_event_listener_fn = None
    agent._profile_store = None
    return agent


# ===== Test Class 1: TestTherapeuticDM =====

class TestTherapeuticDM:
    @pytest.mark.asyncio
    async def test_send_therapeutic_dm_creates_channel_and_thread(self) -> None:
        ward_room = AsyncMock()
        channel = MagicMock()
        channel.id = "dm-ch-1"
        ward_room.get_or_create_dm_channel = AsyncMock(return_value=channel)
        ward_room.create_thread = AsyncMock()
        c = _make_counselor(ward_room=ward_room)
        result = await c._send_therapeutic_dm("agent-1", "Worf", "Hello")
        assert result is True
        ward_room.get_or_create_dm_channel.assert_called_once_with(
            agent_a_id="counselor-001",
            agent_b_id="agent-1",
            callsign_a="Counselor",
            callsign_b="Worf",
        )
        ward_room.create_thread.assert_called_once()
        call_kw = ward_room.create_thread.call_args
        assert call_kw[1].get("thread_mode", call_kw[0][5] if len(call_kw[0]) > 5 else None) == "discuss" or \
            "discuss" in str(call_kw)

    @pytest.mark.asyncio
    async def test_send_therapeutic_dm_rate_limited(self) -> None:
        ward_room = AsyncMock()
        channel = MagicMock()
        channel.id = "dm-ch-1"
        ward_room.get_or_create_dm_channel = AsyncMock(return_value=channel)
        ward_room.create_thread = AsyncMock()
        c = _make_counselor(ward_room=ward_room)
        # First DM succeeds
        assert await c._send_therapeutic_dm("agent-1", "Worf", "Hello") is True
        # Second DM within cooldown returns False
        assert await c._send_therapeutic_dm("agent-1", "Worf", "Hello again") is False
        # Only one thread created
        assert ward_room.create_thread.call_count == 1

    @pytest.mark.asyncio
    async def test_send_therapeutic_dm_no_ward_room(self) -> None:
        c = _make_counselor(ward_room=None)
        result = await c._send_therapeutic_dm("agent-1", "Worf", "Hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_therapeutic_dm_exception_graceful(self) -> None:
        ward_room = AsyncMock()
        ward_room.get_or_create_dm_channel = AsyncMock(side_effect=RuntimeError("db error"))
        c = _make_counselor(ward_room=ward_room)
        result = await c._send_therapeutic_dm("agent-1", "Worf", "Hello")
        assert result is False

    def test_build_therapeutic_message_circuit_breaker(self) -> None:
        c = _make_counselor()
        assessment = _make_assessment(concerns=["Repetitive output"], recommendations=["Take a break"])
        msg = c._build_therapeutic_message("Worf", assessment, "circuit_breaker")
        assert "circuit breaker" in msg.lower()
        assert "Repetitive output" in msg
        assert "Take a break" in msg
        assert "notebook" in msg

    def test_build_therapeutic_message_sweep(self) -> None:
        c = _make_counselor()
        assessment = _make_assessment()
        msg = c._build_therapeutic_message("LaForge", assessment, "sweep")
        assert "wellness review" in msg.lower()

    def test_build_therapeutic_message_trust_update(self) -> None:
        c = _make_counselor()
        assessment = _make_assessment()
        msg = c._build_therapeutic_message("Data", assessment, "trust_update")
        assert "trust dynamics" in msg.lower()

    @pytest.mark.asyncio
    async def test_maybe_send_dm_skips_healthy_agents(self) -> None:
        ward_room = AsyncMock()
        c = _make_counselor(ward_room=ward_room)
        assessment = _make_assessment(wellness=0.8, fit=True)
        await c._maybe_send_therapeutic_dm("agent-1", "Worf", assessment, "sweep")
        ward_room.get_or_create_dm_channel.assert_not_called()


# ===== Test Class 2: TestTherapeuticDMTriggers =====

class TestTherapeuticDMTriggers:
    @pytest.mark.asyncio
    async def test_circuit_breaker_trip_sends_dm_on_concern(self) -> None:
        c = _make_counselor()
        c._send_therapeutic_dm = AsyncMock(return_value=True)
        c._maybe_send_therapeutic_dm = AsyncMock()
        c._apply_intervention = AsyncMock()
        c._gather_agent_metrics = MagicMock(return_value={
            "trust_score": 0.5, "confidence": 0.5, "hebbian_avg": 0.5,
            "success_rate": 0.5, "personality_drift": 0.0,
        })
        c.assess_agent = MagicMock(return_value=_make_assessment(wellness=0.3, fit=False))
        c._classify_trip_severity = MagicMock(return_value=("concern", "Monitor closely"))
        c._save_profile_and_assessment = AsyncMock()
        c._alert_bridge = MagicMock()
        c._post_assessment_to_ward_room = AsyncMock()

        await c._on_circuit_breaker_trip({
            "agent_id": "agent-1", "trip_count": 2,
            "cooldown_seconds": 900, "trip_reason": "rumination",
            "callsign": "Worf",
        })
        c._maybe_send_therapeutic_dm.assert_called_once()
        assert c._maybe_send_therapeutic_dm.call_args[1].get("trigger", c._maybe_send_therapeutic_dm.call_args[0][3] if len(c._maybe_send_therapeutic_dm.call_args[0]) > 3 else None) == "circuit_breaker" or \
            "circuit_breaker" in str(c._maybe_send_therapeutic_dm.call_args)

    @pytest.mark.asyncio
    async def test_circuit_breaker_trip_no_dm_on_monitor(self) -> None:
        c = _make_counselor()
        c._maybe_send_therapeutic_dm = AsyncMock()
        c._apply_intervention = AsyncMock()
        c._gather_agent_metrics = MagicMock(return_value={
            "trust_score": 0.7, "confidence": 0.7, "hebbian_avg": 0.7,
            "success_rate": 0.8, "personality_drift": 0.0,
        })
        c.assess_agent = MagicMock(return_value=_make_assessment(wellness=0.8, fit=True))
        c._classify_trip_severity = MagicMock(return_value=("monitor", "No action"))
        c._save_profile_and_assessment = AsyncMock()
        c._alert_bridge = MagicMock()
        c._post_assessment_to_ward_room = AsyncMock()

        await c._on_circuit_breaker_trip({
            "agent_id": "agent-1", "trip_count": 1,
            "cooldown_seconds": 900, "trip_reason": "topic_exhaustion",
            "callsign": "Worf",
        })
        c._maybe_send_therapeutic_dm.assert_not_called()

    @pytest.mark.asyncio
    async def test_circuit_breaker_trip_intervention_applies_intervention(self) -> None:
        c = _make_counselor()
        c._maybe_send_therapeutic_dm = AsyncMock()
        c._apply_intervention = AsyncMock()
        c._gather_agent_metrics = MagicMock(return_value={
            "trust_score": 0.3, "confidence": 0.3, "hebbian_avg": 0.3,
            "success_rate": 0.3, "personality_drift": 0.0,
        })
        c.assess_agent = MagicMock(return_value=_make_assessment(wellness=0.2, fit=False))
        c._classify_trip_severity = MagicMock(return_value=("intervention", "Need intervention"))
        c._save_profile_and_assessment = AsyncMock()
        c._alert_bridge = MagicMock()
        c._post_assessment_to_ward_room = AsyncMock()

        await c._on_circuit_breaker_trip({
            "agent_id": "agent-1", "trip_count": 4,
            "cooldown_seconds": 900, "trip_reason": "rumination",
            "callsign": "Worf",
        })
        c._apply_intervention.assert_called_once()

    @pytest.mark.asyncio
    async def test_wellness_sweep_sends_dm_for_yellow(self) -> None:
        c = _make_counselor()
        c._maybe_send_therapeutic_dm = AsyncMock()
        mock_agent = MagicMock()
        mock_agent.id = "agent-1"
        mock_agent.agent_id = "agent-1"
        mock_agent.callsign = "LaForge"
        mock_agent.agent_type = "engineer"
        mock_agent.tier = "crew"
        registry = MagicMock()
        registry.all = MagicMock(return_value=[mock_agent])
        c._registry = registry
        c.assess_agent = MagicMock(return_value=_make_assessment(wellness=0.3, fit=False))
        c._gather_agent_metrics = MagicMock(return_value={
            "trust_score": 0.5, "confidence": 0.5, "hebbian_avg": 0.5,
            "success_rate": 0.5, "personality_drift": 0.0,
        })
        c._profile_store = None

        await c._run_wellness_sweep(max_agents=10)
        c._maybe_send_therapeutic_dm.assert_called_once()

    @pytest.mark.asyncio
    async def test_trust_update_sends_dm_when_unfit(self) -> None:
        c = _make_counselor()
        c._maybe_send_therapeutic_dm = AsyncMock()
        c._gather_agent_metrics = MagicMock(return_value={
            "trust_score": 0.2, "confidence": 0.3, "hebbian_avg": 0.3,
            "success_rate": 0.3, "personality_drift": 0.0,
        })
        c.assess_agent = MagicMock(return_value=_make_assessment(wellness=0.2, fit=False))
        c._save_profile_and_assessment = AsyncMock()
        c._alert_bridge = MagicMock()
        # Must have a profile to pass the guard
        from probos.cognitive.counselor import CognitiveProfile
        c._cognitive_profiles["agent-1"] = CognitiveProfile()
        c._cognitive_profiles["agent-1"].baseline.trust_score = 0.8

        agent_mock = MagicMock()
        agent_mock.callsign = "Worf"
        agent_mock.agent_type = "security"
        registry = MagicMock()
        registry.get = MagicMock(return_value=agent_mock)
        c._registry = registry

        await c._on_trust_update({"agent_id": "agent-1", "new_score": 0.2})
        c._maybe_send_therapeutic_dm.assert_called_once()


# ===== Test Class 3: TestCooldownAdjustment =====

class TestCooldownAdjustment:
    def _make_loop(self) -> Any:
        from probos.proactive import ProactiveCognitiveLoop
        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        loop._agent_cooldowns = {}
        loop._cooldown_reasons = {}
        loop._cooldown = 300.0
        loop._knowledge_store = None
        return loop

    def test_set_agent_cooldown_with_reason(self) -> None:
        loop = self._make_loop()
        loop.set_agent_cooldown("agent-1", 600, reason="Counselor: repetitive output")
        assert loop.get_cooldown_reason("agent-1") == "Counselor: repetitive output"
        assert loop.get_agent_cooldown("agent-1") == 600

    def test_set_agent_cooldown_clears_reason_when_empty(self) -> None:
        loop = self._make_loop()
        loop.set_agent_cooldown("agent-1", 600, reason="Old reason")
        loop.set_agent_cooldown("agent-1", 300, reason="")
        assert loop.get_cooldown_reason("agent-1") == ""

    def test_clear_counselor_cooldown(self) -> None:
        loop = self._make_loop()
        loop.set_agent_cooldown("agent-1", 600, reason="Counselor intervention")
        loop.clear_counselor_cooldown("agent-1")
        assert loop.get_agent_cooldown("agent-1") == 300.0  # back to default
        assert loop.get_cooldown_reason("agent-1") == ""

    @pytest.mark.asyncio
    async def test_cooldown_reason_in_self_monitoring(self) -> None:
        from probos.proactive import ProactiveCognitiveLoop
        loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        loop._agent_cooldowns = {}
        loop._cooldown_reasons = {"agent-1": "Counselor: elevated cognitive load"}
        loop._cooldown = 300.0
        loop._knowledge_store = None
        loop._pending_notebook_reads = {}
        # Build a minimal agent and rt for context builder
        agent = MagicMock()
        agent.id = "agent-1"
        agent.agent_type = "security"
        rt = MagicMock()
        rt.ward_room = None
        rt.callsign_registry = MagicMock()
        rt.callsign_registry.get_callsign = MagicMock(return_value="Worf")
        # Agency level that enables self-monitoring
        with patch("probos.proactive.agency_from_rank") as mock_agency:
            from probos.earned_agency import AgencyLevel
            mock_agency.return_value = AgencyLevel.AUTONOMOUS
            result = await loop._build_self_monitoring_context(agent, "Worf", rt)
        assert result.get("cooldown_reason") == "Counselor: elevated cognitive load"

    def test_cooldown_reason_displayed_in_prompt(self) -> None:
        from probos.cognitive.cognitive_agent import CognitiveAgent
        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._agent_type = "test_agent"
        obs = {
            "intent": "proactive_think",
            "params": {
                "context_parts": {
                    "self_monitoring": {
                        "cooldown_increased": True,
                        "cooldown_reason": "Counselor intervention: repetitive output",
                    },
                },
                "trust_score": 0.5,
                "agency_level": "suggestive",
                "rank": "Ensign",
                "duty": None,
            },
        }
        msg = agent._build_user_message(obs)
        assert "Counselor note: Counselor intervention: repetitive output" in msg


# ===== Test Class 4: TestRecommendationAlert =====

class TestRecommendationAlert:
    @pytest.mark.asyncio
    async def test_post_recommendation_creates_bridge_alert(self) -> None:
        router = AsyncMock()
        c = _make_counselor(ward_room_router=router)
        assessment = _make_assessment()
        await c._post_recommendation_to_ward_room(
            "agent-1", "Worf", assessment, ["Extended cooldown to 900s"]
        )
        router.deliver_bridge_alert.assert_called_once()
        alert = router.deliver_bridge_alert.call_args[0][0]
        assert alert.alert_type == "counselor_recommendation"
        assert "Worf" in alert.title
        assert "Extended cooldown" in alert.detail

    @pytest.mark.asyncio
    async def test_recommendation_advisory_for_fit_agent(self) -> None:
        router = AsyncMock()
        c = _make_counselor(ward_room_router=router)
        assessment = _make_assessment(fit=True)
        await c._post_recommendation_to_ward_room("agent-1", "Worf", assessment, ["Action"])
        alert = router.deliver_bridge_alert.call_args[0][0]
        from probos.bridge_alerts import AlertSeverity
        assert alert.severity == AlertSeverity.ADVISORY

    @pytest.mark.asyncio
    async def test_recommendation_alert_for_unfit_agent(self) -> None:
        router = AsyncMock()
        c = _make_counselor(ward_room_router=router)
        assessment = _make_assessment(fit=False)
        await c._post_recommendation_to_ward_room("agent-1", "Worf", assessment, ["Action"])
        alert = router.deliver_bridge_alert.call_args[0][0]
        from probos.bridge_alerts import AlertSeverity
        assert alert.severity == AlertSeverity.ALERT

    @pytest.mark.asyncio
    async def test_recommendation_no_router_graceful(self) -> None:
        c = _make_counselor(ward_room_router=None)
        assessment = _make_assessment()
        # Should not crash
        await c._post_recommendation_to_ward_room("agent-1", "Worf", assessment, ["Action"])


# ===== Test Class 5: TestDirectiveCreation =====

class TestDirectiveCreation:
    def test_issue_guidance_directive_success(self) -> None:
        store = MagicMock()
        store.get_active_for_agent = MagicMock(return_value=[])
        directive_mock = MagicMock()
        store.create_directive = MagicMock(return_value=(directive_mock, None))
        c = _make_counselor(directive_store=store)
        result = c._issue_guidance_directive("security", "Redirect attention")
        assert result is True
        store.create_directive.assert_called_once()
        call_kw = store.create_directive.call_args[1]
        assert call_kw["issuer_type"] == "counselor"
        from probos.directive_store import DirectiveType
        assert call_kw["directive_type"] == DirectiveType.COUNSELOR_GUIDANCE

    def test_issue_guidance_directive_rate_limited(self) -> None:
        store = MagicMock()
        from probos.directive_store import DirectiveType
        existing = [MagicMock(directive_type=DirectiveType.COUNSELOR_GUIDANCE) for _ in range(3)]
        store.get_active_for_agent = MagicMock(return_value=existing)
        c = _make_counselor(directive_store=store)
        result = c._issue_guidance_directive("security", "Another directive")
        assert result is False
        store.create_directive.assert_not_called()

    def test_issue_guidance_directive_no_store(self) -> None:
        c = _make_counselor(directive_store=None)
        result = c._issue_guidance_directive("security", "Test")
        assert result is False

    def test_issue_guidance_directive_authorization_failure(self) -> None:
        store = MagicMock()
        store.get_active_for_agent = MagicMock(return_value=[])
        store.create_directive = MagicMock(return_value=(None, "Insufficient authority"))
        c = _make_counselor(directive_store=store)
        result = c._issue_guidance_directive("security", "Test")
        assert result is False

    def test_directive_has_24h_default_expiry(self) -> None:
        store = MagicMock()
        store.get_active_for_agent = MagicMock(return_value=[])
        directive_mock = MagicMock()
        store.create_directive = MagicMock(return_value=(directive_mock, None))
        c = _make_counselor(directive_store=store)
        before = time.time()
        c._issue_guidance_directive("security", "Test")
        after = time.time()
        call_kw = store.create_directive.call_args[1]
        expires_at = call_kw["expires_at"]
        # Should be ~24 hours in the future
        assert expires_at >= before + (23.9 * 3600)
        assert expires_at <= after + (24.1 * 3600)


# ===== Test Class 6: TestApplyIntervention =====

class TestApplyIntervention:
    @pytest.mark.asyncio
    async def test_intervention_extends_cooldown_1_5x(self) -> None:
        proactive = MagicMock()
        proactive.get_agent_cooldown = MagicMock(return_value=300.0)
        c = _make_counselor(proactive_loop=proactive, ward_room_router=AsyncMock())
        c._issue_guidance_directive = MagicMock(return_value=False)
        assessment = _make_assessment()
        await c._apply_intervention("agent-1", "Worf", assessment, "intervention")
        proactive.set_agent_cooldown.assert_called_once()
        args = proactive.set_agent_cooldown.call_args
        assert args[0][1] == 450.0  # 300 * 1.5
        assert "reason" in args[1]

    @pytest.mark.asyncio
    async def test_escalate_extends_cooldown_2x(self) -> None:
        proactive = MagicMock()
        proactive.get_agent_cooldown = MagicMock(return_value=300.0)
        c = _make_counselor(proactive_loop=proactive, ward_room_router=AsyncMock())
        c._issue_guidance_directive = MagicMock(return_value=False)
        assessment = _make_assessment()
        await c._apply_intervention("agent-1", "Worf", assessment, "escalate")
        args = proactive.set_agent_cooldown.call_args
        assert args[0][1] == 600.0  # 300 * 2.0

    @pytest.mark.asyncio
    async def test_intervention_forces_dream_cycle(self) -> None:
        dream = AsyncMock()
        dream.is_dreaming = False
        dream.force_dream = AsyncMock()
        c = _make_counselor(dream_scheduler=dream, ward_room_router=AsyncMock())
        c._issue_guidance_directive = MagicMock(return_value=False)
        assessment = _make_assessment()
        await c._apply_intervention("agent-1", "Worf", assessment, "intervention")
        dream.force_dream.assert_called_once()

    @pytest.mark.asyncio
    async def test_intervention_issues_guidance_directive(self) -> None:
        agent_mock = MagicMock()
        agent_mock.agent_type = "security"
        registry = MagicMock()
        registry.get = MagicMock(return_value=agent_mock)
        c = _make_counselor(registry=registry, ward_room_router=AsyncMock())
        c._issue_guidance_directive = MagicMock(return_value=True)
        assessment = _make_assessment(concerns=["Repetitive output detected"])
        await c._apply_intervention("agent-1", "Worf", assessment, "intervention")
        c._issue_guidance_directive.assert_called_once()
        call_args = c._issue_guidance_directive.call_args[0]
        assert call_args[0] == "security"  # agent_type
        assert "Repetitive output" in call_args[1]

    @pytest.mark.asyncio
    async def test_intervention_posts_recommendation_alert(self) -> None:
        proactive = MagicMock()
        proactive.get_agent_cooldown = MagicMock(return_value=300.0)
        router = AsyncMock()
        c = _make_counselor(proactive_loop=proactive, ward_room_router=router)
        c._issue_guidance_directive = MagicMock(return_value=False)
        assessment = _make_assessment()
        await c._apply_intervention("agent-1", "Worf", assessment, "intervention")
        router.deliver_bridge_alert.assert_called_once()

    @pytest.mark.asyncio
    async def test_intervention_graceful_without_services(self) -> None:
        c = _make_counselor()
        assessment = _make_assessment(concerns=[])
        # Should not crash with no services
        await c._apply_intervention("agent-1", "Worf", assessment, "intervention")


# ===== Test Class 7: TestCounselorWiring =====

class TestCounselorWiring:
    @pytest.mark.asyncio
    async def test_initialize_accepts_new_parameters(self) -> None:
        c = _make_counselor()
        wr = MagicMock()
        ds = MagicMock()
        dream = MagicMock()
        pl = MagicMock()
        await c.initialize(
            ward_room=wr,
            directive_store=ds,
            dream_scheduler=dream,
            proactive_loop=pl,
        )
        assert c._ward_room is wr
        assert c._directive_store is ds
        assert c._dream_scheduler is dream
        assert c._proactive_loop is pl

    def test_finalize_passes_local_ward_room_router(self) -> None:
        """Verify finalize.py passes local variable, not getattr(runtime, ...)."""
        import ast
        from pathlib import Path
        source = Path("src/probos/startup/finalize.py").read_text()
        tree = ast.parse(source)
        # Should NOT contain getattr(runtime, 'ward_room_router', None)
        assert "getattr(runtime, 'ward_room_router'" not in source
        # Should contain ward_room_router=ward_room_router
        assert "ward_room_router=ward_room_router" in source

    def test_finalize_passes_new_dependencies(self) -> None:
        """Verify finalize.py passes ward_room, directive_store, dream_scheduler, proactive_loop."""
        from pathlib import Path
        source = Path("src/probos/startup/finalize.py").read_text()
        assert "ward_room=runtime.ward_room" in source
        assert "directive_store=" in source
        assert "dream_scheduler=" in source
        assert "proactive_loop=proactive_loop" in source

    def test_resolve_callsign_from_registry(self) -> None:
        agent_mock = MagicMock()
        agent_mock.callsign = "Worf"
        agent_mock.agent_type = "security"
        registry = MagicMock()
        registry.get = MagicMock(return_value=agent_mock)
        c = _make_counselor(registry=registry)
        assert c._resolve_callsign("agent-1") == "Worf"

        # Fallback when registry unavailable
        c2 = _make_counselor(registry=None)
        assert c2._resolve_callsign("agent-12345678-abcd") == "agent-12"


# ===== Test Class 8: TestIntegration =====

class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_circuit_breaker_to_dm_flow(self) -> None:
        """End-to-end: CB trip → assessment → DM → intervention → recommendation."""
        ward_room = AsyncMock()
        channel = MagicMock()
        channel.id = "dm-1"
        ward_room.get_or_create_dm_channel = AsyncMock(return_value=channel)
        ward_room.create_thread = AsyncMock()
        router = AsyncMock()
        proactive = MagicMock()
        proactive.get_agent_cooldown = MagicMock(return_value=300.0)
        dream = AsyncMock()
        dream.is_dreaming = False

        agent_mock = MagicMock()
        agent_mock.agent_type = "security"
        registry = MagicMock()
        registry.get = MagicMock(return_value=agent_mock)

        c = _make_counselor(
            ward_room=ward_room, ward_room_router=router,
            proactive_loop=proactive, dream_scheduler=dream,
            registry=registry,
        )
        c._gather_agent_metrics = MagicMock(return_value={
            "trust_score": 0.3, "confidence": 0.3, "hebbian_avg": 0.3,
            "success_rate": 0.3, "personality_drift": 0.0,
        })
        c.assess_agent = MagicMock(return_value=_make_assessment(
            wellness=0.2, fit=False,
            concerns=["Repetitive output detected"],
        ))
        c._classify_trip_severity = MagicMock(return_value=("intervention", "Need intervention"))
        c._save_profile_and_assessment = AsyncMock()
        c._alert_bridge = MagicMock()
        c._issue_guidance_directive = MagicMock(return_value=True)

        await c._on_circuit_breaker_trip({
            "agent_id": "agent-1", "trip_count": 4,
            "cooldown_seconds": 900, "trip_reason": "rumination",
            "callsign": "Worf",
        })

        # DM sent
        ward_room.create_thread.assert_called_once()
        # Cooldown extended
        proactive.set_agent_cooldown.assert_called_once()
        # Dream triggered
        dream.force_dream.assert_called_once()
        # Recommendation posted
        router.deliver_bridge_alert.assert_called()

    @pytest.mark.asyncio
    async def test_full_sweep_to_dm_flow(self) -> None:
        """Wellness sweep with one struggling agent → DM sent."""
        ward_room = AsyncMock()
        channel = MagicMock()
        channel.id = "dm-1"
        ward_room.get_or_create_dm_channel = AsyncMock(return_value=channel)
        ward_room.create_thread = AsyncMock()

        agent1 = MagicMock()
        agent1.id = "agent-1"
        agent1.agent_id = "agent-1"
        agent1.callsign = "LaForge"
        agent1.agent_type = "engineer"
        agent1.tier = "crew"

        agent2 = MagicMock()
        agent2.id = "agent-2"
        agent2.agent_id = "agent-2"
        agent2.callsign = "Data"
        agent2.agent_type = "science"
        agent2.tier = "crew"

        registry = MagicMock()
        registry.all = MagicMock(return_value=[agent1, agent2])
        c = _make_counselor(ward_room=ward_room, registry=registry)
        c._profile_store = None

        # agent-1 struggling, agent-2 fine
        call_count = [0]
        def mock_assess(agent_id, **kw):
            call_count[0] += 1
            if agent_id == "agent-1":
                return _make_assessment(wellness=0.3, fit=False)
            return _make_assessment(wellness=0.8, fit=True)

        c.assess_agent = MagicMock(side_effect=mock_assess)
        c._gather_agent_metrics = MagicMock(return_value={
            "trust_score": 0.5, "confidence": 0.5, "hebbian_avg": 0.5,
            "success_rate": 0.5, "personality_drift": 0.0,
        })

        await c._run_wellness_sweep(max_agents=10)
        # Only one DM (the struggling agent)
        assert ward_room.create_thread.call_count == 1

    @pytest.mark.asyncio
    async def test_dm_rate_limit_across_triggers(self) -> None:
        """CB trip sends DM → sweep within 1 hour to same agent → second DM skipped."""
        ward_room = AsyncMock()
        channel = MagicMock()
        channel.id = "dm-1"
        ward_room.get_or_create_dm_channel = AsyncMock(return_value=channel)
        ward_room.create_thread = AsyncMock()

        c = _make_counselor(ward_room=ward_room)
        assessment = _make_assessment(wellness=0.2, fit=False)

        # First DM (circuit breaker trigger)
        await c._maybe_send_therapeutic_dm("agent-1", "Worf", assessment, "circuit_breaker")
        assert ward_room.create_thread.call_count == 1

        # Second DM attempt (sweep trigger) within cooldown
        await c._maybe_send_therapeutic_dm("agent-1", "Worf", assessment, "sweep")
        assert ward_room.create_thread.call_count == 1  # Still 1, rate limited
