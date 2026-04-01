"""Tests for AD-503: Counselor Activation — data gathering, persistence, events."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.llm_client import BaseLLMClient
from probos.events import EventType


# ---------------------------------------------------------------------------
# TestAssessmentTriggerField (Part 1a)
# ---------------------------------------------------------------------------


class TestAssessmentTriggerField:
    """Verify the new trigger field on CounselorAssessment."""

    def test_default_trigger(self) -> None:
        from probos.cognitive.counselor import CounselorAssessment
        a = CounselorAssessment()
        assert a.trigger == "manual"

    def test_trigger_roundtrip(self) -> None:
        from probos.cognitive.counselor import CounselorAssessment
        a = CounselorAssessment(trigger="sweep", agent_id="test")
        d = a.to_dict()
        assert d["trigger"] == "sweep"
        restored = CounselorAssessment.from_dict(d)
        assert restored.trigger == "sweep"

    def test_trigger_in_assess_agent(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        result = agent.assess_agent("agent-1", trigger="api")
        assert result.trigger == "api"

    def test_trigger_default_manual(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        result = agent.assess_agent("agent-1")
        assert result.trigger == "manual"


# ---------------------------------------------------------------------------
# TestCounselorProfileStore (Part 1b)
# ---------------------------------------------------------------------------


class TestCounselorProfileStore:
    """SQLite-backed persistence for cognitive profiles."""

    @pytest.fixture
    def store_dir(self, tmp_path: Path) -> Path:
        return tmp_path

    @pytest.mark.asyncio
    async def test_start_creates_db(self, store_dir: Path) -> None:
        from probos.cognitive.counselor import CounselorProfileStore
        store = CounselorProfileStore(data_dir=store_dir)
        await store.start()
        assert (store_dir / "counselor.db").exists()
        await store.stop()

    @pytest.mark.asyncio
    async def test_save_and_load_profile(self, store_dir: Path) -> None:
        from probos.cognitive.counselor import CounselorProfileStore, CognitiveProfile
        store = CounselorProfileStore(data_dir=store_dir)
        await store.start()
        profile = CognitiveProfile(
            agent_id="agent-1", agent_type="builder",
            alert_level="yellow", created_at=time.time(),
        )
        await store.save_profile(profile)
        loaded = await store.load_profile("agent-1")
        assert loaded is not None
        assert loaded.agent_id == "agent-1"
        assert loaded.alert_level == "yellow"
        await store.stop()

    @pytest.mark.asyncio
    async def test_load_nonexistent_profile(self, store_dir: Path) -> None:
        from probos.cognitive.counselor import CounselorProfileStore
        store = CounselorProfileStore(data_dir=store_dir)
        await store.start()
        result = await store.load_profile("nonexistent")
        assert result is None
        await store.stop()

    @pytest.mark.asyncio
    async def test_load_all_profiles(self, store_dir: Path) -> None:
        from probos.cognitive.counselor import CounselorProfileStore, CognitiveProfile
        store = CounselorProfileStore(data_dir=store_dir)
        await store.start()
        for i in range(3):
            await store.save_profile(CognitiveProfile(
                agent_id=f"agent-{i}", created_at=time.time(),
            ))
        all_profiles = await store.load_all_profiles()
        assert len(all_profiles) == 3
        assert "agent-0" in all_profiles
        await store.stop()

    @pytest.mark.asyncio
    async def test_save_and_get_assessment(self, store_dir: Path) -> None:
        from probos.cognitive.counselor import (
            CounselorProfileStore, CognitiveProfile, CounselorAssessment,
        )
        store = CounselorProfileStore(data_dir=store_dir)
        await store.start()
        # Save profile first (foreign key)
        await store.save_profile(CognitiveProfile(agent_id="agent-1", created_at=time.time()))
        assessment = CounselorAssessment(
            agent_id="agent-1", timestamp=time.time(),
            trigger="sweep", wellness_score=0.7,
        )
        await store.save_assessment(assessment)
        history = await store.get_assessment_history("agent-1")
        assert len(history) == 1
        assert history[0].trigger == "sweep"
        assert history[0].wellness_score == pytest.approx(0.7)
        await store.stop()

    @pytest.mark.asyncio
    async def test_assessment_history_order(self, store_dir: Path) -> None:
        from probos.cognitive.counselor import (
            CounselorProfileStore, CognitiveProfile, CounselorAssessment,
        )
        store = CounselorProfileStore(data_dir=store_dir)
        await store.start()
        await store.save_profile(CognitiveProfile(agent_id="agent-1", created_at=time.time()))
        for i in range(5):
            await store.save_assessment(CounselorAssessment(
                agent_id="agent-1", timestamp=float(i),
                wellness_score=0.5 + i * 0.1,
            ))
        history = await store.get_assessment_history("agent-1", limit=3)
        assert len(history) == 3
        # Should be newest first
        assert history[0].timestamp > history[1].timestamp
        await store.stop()

    @pytest.mark.asyncio
    async def test_crew_summary(self, store_dir: Path) -> None:
        from probos.cognitive.counselor import CounselorProfileStore, CognitiveProfile
        store = CounselorProfileStore(data_dir=store_dir)
        await store.start()
        await store.save_profile(CognitiveProfile(
            agent_id="a", alert_level="red", last_assessed=2.0,
        ))
        await store.save_profile(CognitiveProfile(
            agent_id="b", alert_level="green", last_assessed=1.0,
        ))
        summary = await store.get_crew_summary()
        assert len(summary) == 2
        assert summary[0]["agent_id"] == "a"  # red sorts first
        await store.stop()

    @pytest.mark.asyncio
    async def test_upsert_profile(self, store_dir: Path) -> None:
        from probos.cognitive.counselor import CounselorProfileStore, CognitiveProfile
        store = CounselorProfileStore(data_dir=store_dir)
        await store.start()
        p = CognitiveProfile(agent_id="agent-1", alert_level="green", created_at=time.time())
        await store.save_profile(p)
        p.alert_level = "red"
        await store.save_profile(p)
        loaded = await store.load_profile("agent-1")
        assert loaded is not None
        assert loaded.alert_level == "red"
        # Still only 1 row
        all_p = await store.load_all_profiles()
        assert len(all_p) == 1
        await store.stop()

    @pytest.mark.asyncio
    async def test_no_db_graceful(self) -> None:
        """Operations gracefully degrade when DB is not started."""
        from probos.cognitive.counselor import CounselorProfileStore, CognitiveProfile
        store = CounselorProfileStore(data_dir="/nonexistent")
        # Don't call start()
        assert await store.load_profile("x") is None
        assert await store.load_all_profiles() == {}
        assert await store.get_assessment_history("x") == []
        assert await store.get_crew_summary() == []


# ---------------------------------------------------------------------------
# TestGatherAgentMetrics (Part 1c)
# ---------------------------------------------------------------------------


class TestGatherAgentMetrics:
    """Autonomous metric gathering from runtime services."""

    def test_defaults_when_no_services(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        metrics = agent._gather_agent_metrics("agent-1")
        assert metrics["trust_score"] == 0.5
        assert metrics["confidence"] == 0.8
        assert metrics["hebbian_avg"] == 0.0
        assert metrics["success_rate"] == 0.0
        assert metrics["personality_drift"] == 0.0

    def test_trust_from_network(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        trust = MagicMock()
        trust.score.return_value = 0.85
        agent._trust_network = trust
        metrics = agent._gather_agent_metrics("agent-1")
        assert metrics["trust_score"] == 0.85

    def test_hebbian_from_router(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        router = MagicMock()
        router.get_weights_for.return_value = {"a": 0.4, "b": 0.6}
        agent._hebbian_router = router
        metrics = agent._gather_agent_metrics("agent-1")
        assert metrics["hebbian_avg"] == pytest.approx(0.5)

    def test_registry_meta(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        meta = MagicMock()
        meta.confidence = 0.92
        meta.success_rate = 0.88
        registry = MagicMock()
        registry.get.return_value = meta
        agent._registry = registry
        metrics = agent._gather_agent_metrics("agent-1")
        assert metrics["confidence"] == 0.92
        assert metrics["success_rate"] == 0.88

    def test_graceful_on_exception(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        trust = MagicMock()
        trust.score.side_effect = RuntimeError("boom")
        agent._trust_network = trust
        metrics = agent._gather_agent_metrics("agent-1")
        # Should fall back to default
        assert metrics["trust_score"] == 0.5


# ---------------------------------------------------------------------------
# TestWellnessSweep (Part 1d)
# ---------------------------------------------------------------------------


class TestWellnessSweep:
    """Full crew wellness sweep."""

    @pytest.mark.asyncio
    async def test_sweep_with_no_registry(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        results = await agent._run_wellness_sweep()
        assert results == []

    @pytest.mark.asyncio
    async def test_sweep_skips_self(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        meta_self = MagicMock()
        meta_self.id = agent.id
        meta_self.tier = "domain"
        registry = MagicMock()
        registry.all.return_value = [meta_self]
        agent._registry = registry
        results = await agent._run_wellness_sweep()
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_sweep_skips_infrastructure(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        meta = MagicMock()
        meta.id = "infra-1"
        meta.tier = "infrastructure"
        registry = MagicMock()
        registry.all.return_value = [meta]
        agent._registry = registry
        results = await agent._run_wellness_sweep()
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_sweep_assesses_crew(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        meta = MagicMock()
        meta.id = "builder-1"
        meta.tier = "domain"
        meta.confidence = 0.8
        meta.success_rate = 0.7
        registry = MagicMock()
        registry.all.return_value = [meta]
        registry.get.return_value = meta
        agent._registry = registry
        results = await agent._run_wellness_sweep()
        assert len(results) == 1
        assert results[0].agent_id == "builder-1"
        assert results[0].trigger == "sweep"

    @pytest.mark.asyncio
    async def test_sweep_respects_max_agents(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        metas = []
        for i in range(10):
            m = MagicMock()
            m.id = f"agent-{i}"
            m.tier = "domain"
            m.confidence = 0.8
            m.success_rate = 0.7
            metas.append(m)
        registry = MagicMock()
        registry.all.return_value = metas
        registry.get.side_effect = lambda aid: next((m for m in metas if m.id == aid), None)
        agent._registry = registry
        results = await agent._run_wellness_sweep(max_agents=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_sweep_persists_when_store_available(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorProfileStore
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        meta = MagicMock()
        meta.id = "builder-1"
        meta.tier = "domain"
        meta.confidence = 0.8
        meta.success_rate = 0.7
        registry = MagicMock()
        registry.all.return_value = [meta]
        registry.get.return_value = meta
        agent._registry = registry

        store = AsyncMock(spec=CounselorProfileStore)
        agent._profile_store = store
        await agent._run_wellness_sweep()
        store.save_profile.assert_called_once()
        store.save_assessment.assert_called_once()

    @pytest.mark.asyncio
    async def test_sweep_emits_events(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        meta = MagicMock()
        meta.id = "builder-1"
        meta.tier = "domain"
        meta.confidence = 0.8
        meta.success_rate = 0.7
        registry = MagicMock()
        registry.all.return_value = [meta]
        registry.get.return_value = meta
        agent._registry = registry

        emit_fn = MagicMock()
        agent._emit_event_fn = emit_fn
        await agent._run_wellness_sweep()
        emit_fn.assert_called_once()
        call_args = emit_fn.call_args
        assert call_args[0][0] == EventType.COUNSELOR_ASSESSMENT


# ---------------------------------------------------------------------------
# TestEventHandlers (Part 1e)
# ---------------------------------------------------------------------------


class TestEventHandlers:
    """Event-driven assessment handlers."""

    @pytest.mark.asyncio
    async def test_on_trust_update_significant(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CognitiveBaseline
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent.set_baseline("agent-1", CognitiveBaseline(trust_score=0.7))
        # Significant delta (0.7 → 0.4 = 0.3 delta, > 0.15 threshold)
        await agent._on_trust_update({"agent_id": "agent-1", "new_score": 0.4})
        profile = agent.get_profile("agent-1")
        assert profile is not None
        assert len(profile.assessments) == 1
        assert profile.assessments[0].trigger == "trust_update"

    @pytest.mark.asyncio
    async def test_on_trust_update_insignificant(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CognitiveBaseline
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent.set_baseline("agent-1", CognitiveBaseline(trust_score=0.7))
        # Small delta (0.05 < 0.15 threshold)
        await agent._on_trust_update({"agent_id": "agent-1", "new_score": 0.75})
        profile = agent.get_profile("agent-1")
        assert profile is not None
        assert len(profile.assessments) == 0  # No assessment triggered

    @pytest.mark.asyncio
    async def test_on_trust_update_skips_self(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        await agent._on_trust_update({"agent_id": agent.id, "new_score": 0.3})
        assert len(agent.all_profiles()) == 0

    @pytest.mark.asyncio
    async def test_on_circuit_breaker_trip(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        emit_fn = MagicMock()
        agent._emit_event_fn = emit_fn
        await agent._on_circuit_breaker_trip({
            "agent_id": "agent-1",
            "trip_count": 1,
            "cooldown_seconds": 900.0,
            "trip_reason": "velocity",
            "callsign": "TestAgent",
        })
        profile = agent.get_profile("agent-1")
        assert profile is not None
        assert len(profile.assessments) == 1
        assert profile.assessments[0].trigger == "circuit_breaker"
        # Should always alert bridge on circuit breaker
        emit_fn.assert_called()

    @pytest.mark.asyncio
    async def test_on_event_async_routes(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        # Trust update event
        await agent._on_event_async({
            "type": EventType.TRUST_UPDATE.value,
            "data": {"agent_id": "agent-1", "new_score": 0.3},
        })
        # Should not crash on DREAM_COMPLETE (no-op)
        await agent._on_event_async({
            "type": EventType.DREAM_COMPLETE.value,
            "data": {"dream_type": "full"},
        })

    @pytest.mark.asyncio
    async def test_alert_bridge(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        emit_fn = MagicMock()
        agent._emit_event_fn = emit_fn
        assessment = CounselorAssessment(
            agent_id="agent-1", fit_for_duty=False, wellness_score=0.2,
        )
        agent._alert_bridge("agent-1", assessment)
        emit_fn.assert_called_once()
        call_args = emit_fn.call_args
        assert call_args[0][0] == EventType.BRIDGE_ALERT
        assert call_args[0][1]["severity"] == "red"


# ---------------------------------------------------------------------------
# TestCounselorInitialize (Part 1g)
# ---------------------------------------------------------------------------


class TestCounselorInitialize:
    """Post-construction initialization."""

    @pytest.mark.asyncio
    async def test_initialize_loads_profiles(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorProfileStore, CognitiveProfile
        store = AsyncMock(spec=CounselorProfileStore)
        store.load_all_profiles.return_value = {
            "agent-1": CognitiveProfile(agent_id="agent-1"),
        }
        agent = CounselorAgent(
            llm_client=AsyncMock(spec=BaseLLMClient),
            profile_store=store,
        )
        await agent.initialize(
            trust_network=MagicMock(),
            add_event_listener_fn=MagicMock(),
        )
        assert "agent-1" in agent._cognitive_profiles
        store.load_all_profiles.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_registers_event_listener(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        listener_fn = MagicMock()
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        await agent.initialize(add_event_listener_fn=listener_fn)
        listener_fn.assert_called_once()
        # Should register with specific event types
        call_args = listener_fn.call_args
        assert call_args[1]["event_types"] is not None


# ---------------------------------------------------------------------------
# TestTypeFilteredEventSubscriptions (Part 0 verification)
# ---------------------------------------------------------------------------


class TestTypeFilteredEventSubscriptions:
    """Verify type-filtered event subscription infrastructure."""

    def test_add_listener_with_filter(self) -> None:
        """Type-filtered listeners only receive matching events."""
        received: list[dict] = []
        def listener(event: dict) -> None:
            received.append(event)

        # Simulate the filtering logic from runtime
        from probos.events import EventType
        type_filter = frozenset([EventType.TRUST_UPDATE.value])
        event = {"type": EventType.TRUST_UPDATE.value, "data": {}}
        type_str = event["type"]

        if type_filter is None or type_str in type_filter:
            listener(event)
        assert len(received) == 1

        # Non-matching event
        event2 = {"type": EventType.BUILD_STARTED.value, "data": {}}
        type_str2 = event2["type"]
        if type_filter is None or type_str2 in type_filter:
            listener(event2)
        assert len(received) == 1  # Still 1, not called

    def test_add_listener_without_filter(self) -> None:
        """Unfiltered listeners receive all events."""
        received: list[dict] = []
        def listener(event: dict) -> None:
            received.append(event)

        type_filter = None
        for et in [EventType.TRUST_UPDATE.value, EventType.BUILD_STARTED.value]:
            event = {"type": et, "data": {}}
            if type_filter is None or et in type_filter:
                listener(event)
        assert len(received) == 2


# ---------------------------------------------------------------------------
# TestCounselorActWellnessReport (Part 1h)
# ---------------------------------------------------------------------------


class TestCounselorActWellnessReport:
    """Verify act() handles counselor_wellness_report deterministically."""

    @pytest.mark.asyncio
    async def test_act_wellness_report(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        # Set up a registry with one crew agent
        meta = MagicMock()
        meta.id = "builder-1"
        meta.tier = "domain"
        meta.confidence = 0.8
        meta.success_rate = 0.7
        registry = MagicMock()
        registry.all.return_value = [meta]
        registry.get.return_value = meta
        agent._registry = registry

        result = await agent.act({"intent": "counselor_wellness_report"})
        assert isinstance(result, dict)
        assert result["success"] is True
        data = result["result"]
        assert data["total_assessed"] == 1
        assert "assessments" in data


# ---------------------------------------------------------------------------
# TestInitiativeEngineWire (Part 2c)
# ---------------------------------------------------------------------------


class TestInitiativeEngineWire:
    """Verify counselor_fn wiring returns agents_at_alert."""

    def test_counselor_fn_returns_alert_profiles(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CognitiveBaseline
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        # Create a yellow agent
        agent.set_baseline("agent-1", CognitiveBaseline(trust_score=0.8))
        agent.assess_agent("agent-1", current_trust=0.4, success_rate=0.3)
        # Create a healthy agent
        agent.set_baseline("agent-2", CognitiveBaseline(trust_score=0.7))
        agent.assess_agent("agent-2", current_trust=0.75, success_rate=0.9)

        fn = lambda: agent.agents_at_alert("yellow")
        results = fn()
        assert len(results) >= 1
        assert any(p.agent_id == "agent-1" for p in results)


# ---------------------------------------------------------------------------
# TestCounselorConfig (Part 4)
# ---------------------------------------------------------------------------


class TestCounselorConfig:
    """CounselorConfig defaults and parsing."""

    def test_default_values(self) -> None:
        from probos.config import CounselorConfig
        cfg = CounselorConfig()
        assert cfg.enabled is True
        assert cfg.profile_retention_days == 90
        assert cfg.trust_delta_threshold == 0.15
        assert cfg.sweep_max_agents == 50
        assert cfg.alert_on_red is True
        assert cfg.alert_on_yellow is False

    def test_system_config_has_counselor(self) -> None:
        from probos.config import SystemConfig, CounselorConfig
        cfg = SystemConfig()
        assert hasattr(cfg, "counselor")
        assert isinstance(cfg.counselor, CounselorConfig)


# ---------------------------------------------------------------------------
# TestNewEventTypes (Part 0b verification)
# ---------------------------------------------------------------------------


class TestNewEventTypes:
    """Verify new AD-503 EventType entries."""

    def test_circuit_breaker_trip_type(self) -> None:
        assert EventType.CIRCUIT_BREAKER_TRIP.value == "circuit_breaker_trip"

    def test_dream_complete_type(self) -> None:
        assert EventType.DREAM_COMPLETE.value == "dream_complete"

    def test_counselor_assessment_type(self) -> None:
        assert EventType.COUNSELOR_ASSESSMENT.value == "counselor_assessment"

    def test_typed_events_serialize(self) -> None:
        from probos.events import (
            CircuitBreakerTripEvent,
            DreamCompleteEvent,
            CounselorAssessmentEvent,
        )
        e1 = CircuitBreakerTripEvent(agent_id="a", trip_count=3)
        d1 = e1.to_dict()
        assert d1["type"] == "circuit_breaker_trip"
        assert d1["data"]["trip_count"] == 3

        e2 = DreamCompleteEvent(dream_type="full", episodes_replayed=10)
        d2 = e2.to_dict()
        assert d2["type"] == "dream_complete"

        e3 = CounselorAssessmentEvent(
            agent_id="b", wellness_score=0.8, alert_level="green",
        )
        d3 = e3.to_dict()
        assert d3["type"] == "counselor_assessment"
        assert d3["data"]["fit_for_duty"] is True


# ---------------------------------------------------------------------------
# AD-495: Circuit Breaker → Counselor Bridge Tests
# ---------------------------------------------------------------------------


class TestCircuitBreakerTripAssessment:
    """AD-495: Trip-aware clinical response on circuit breaker trip."""

    @pytest.mark.asyncio
    async def test_trip_handler_gathers_metrics_and_assesses(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        emit_fn = MagicMock()
        agent._emit_event_fn = emit_fn
        await agent._on_circuit_breaker_trip({
            "agent_id": "a1", "trip_count": 1,
            "cooldown_seconds": 900, "trip_reason": "velocity", "callsign": "Test",
        })
        profile = agent.get_profile("a1")
        assert profile is not None
        assert len(profile.assessments) == 1
        assert profile.assessments[0].trigger == "circuit_breaker"

    def test_first_velocity_trip_classified_as_monitor(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        assessment = CounselorAssessment(fit_for_duty=True, wellness_score=0.9)
        severity, _ = agent._classify_trip_severity(1, "velocity", assessment)
        assert severity == "monitor"

    def test_first_rumination_trip_classified_as_concern(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        assessment = CounselorAssessment(fit_for_duty=True, wellness_score=0.9)
        severity, _ = agent._classify_trip_severity(1, "rumination", assessment)
        assert severity == "concern"

    def test_repeated_trips_classified_as_concern(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        assessment = CounselorAssessment(fit_for_duty=True, wellness_score=0.8)
        severity, _ = agent._classify_trip_severity(2, "velocity", assessment)
        assert severity == "concern"

    def test_frequent_trips_classified_as_intervention(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        assessment = CounselorAssessment(fit_for_duty=True, wellness_score=0.7)
        severity, _ = agent._classify_trip_severity(4, "velocity", assessment)
        assert severity == "intervention"

    def test_unfit_agent_classified_as_escalate(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        assessment = CounselorAssessment(fit_for_duty=False, wellness_score=0.2)
        # Regardless of trip_count, unfit → escalate
        severity, _ = agent._classify_trip_severity(1, "velocity", assessment)
        assert severity == "escalate"

    @pytest.mark.asyncio
    async def test_trip_concerns_added_to_assessment(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._emit_event_fn = MagicMock()
        await agent._on_circuit_breaker_trip({
            "agent_id": "a1", "trip_count": 2,
            "cooldown_seconds": 1800, "trip_reason": "rumination", "callsign": "Test",
        })
        assessment = agent.get_profile("a1").assessments[0]
        assert any("circuit breaker trip #2" in c.lower() for c in assessment.concerns)

    @pytest.mark.asyncio
    async def test_trip_clinical_notes_populated(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._emit_event_fn = MagicMock()
        await agent._on_circuit_breaker_trip({
            "agent_id": "a1", "trip_count": 3,
            "cooldown_seconds": 1800, "trip_reason": "velocity", "callsign": "Test",
        })
        assessment = agent.get_profile("a1").assessments[0]
        assert "trip #3" in assessment.notes.lower()
        assert "velocity" in assessment.notes.lower()
        assert "1800" in assessment.notes
        assert "concern" in assessment.notes.lower()

    @pytest.mark.asyncio
    async def test_assessment_persisted_on_trip(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._emit_event_fn = MagicMock()
        mock_store = MagicMock(spec=["save_profile", "save_assessment"])
        mock_store.save_profile = AsyncMock()
        mock_store.save_assessment = AsyncMock()
        agent._profile_store = mock_store
        await agent._on_circuit_breaker_trip({
            "agent_id": "a1", "trip_count": 1,
            "cooldown_seconds": 900, "trip_reason": "velocity", "callsign": "T",
        })
        mock_store.save_profile.assert_called_once()
        mock_store.save_assessment.assert_called_once()

    @pytest.mark.asyncio
    async def test_bridge_alert_always_fires_on_trip(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        emit_fn = MagicMock()
        agent._emit_event_fn = emit_fn
        await agent._on_circuit_breaker_trip({
            "agent_id": "a1", "trip_count": 1,
            "cooldown_seconds": 900, "trip_reason": "velocity", "callsign": "T",
        })
        # Bridge alert (EventType.BRIDGE_ALERT) + counselor assessment event
        assert emit_fn.call_count >= 2

    @pytest.mark.asyncio
    async def test_counselor_assessment_event_emitted(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        emit_fn = MagicMock()
        agent._emit_event_fn = emit_fn
        await agent._on_circuit_breaker_trip({
            "agent_id": "a1", "trip_count": 1,
            "cooldown_seconds": 900, "trip_reason": "velocity", "callsign": "T",
        })
        assessment_calls = [
            c for c in emit_fn.call_args_list
            if c[0][0] == EventType.COUNSELOR_ASSESSMENT
        ]
        assert len(assessment_calls) == 1
        data = assessment_calls[0][0][1]
        assert data["agent_id"] == "a1"
        assert "wellness_score" in data
        assert "fit_for_duty" in data


class TestWardRoomPosting:
    """AD-495: Ward Room posting on circuit breaker assessment."""

    @pytest.mark.asyncio
    async def test_ward_room_post_on_trip(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        mock_router = AsyncMock()
        agent._ward_room_router = mock_router
        assessment = CounselorAssessment(
            timestamp=1000.0, agent_id="a1", wellness_score=0.8,
            fit_for_duty=True, concerns=["test concern"],
        )
        await agent._post_assessment_to_ward_room(
            "a1", "TestAgent", assessment, "monitor", 1, "velocity",
        )
        mock_router.deliver_bridge_alert.assert_called_once()
        alert = mock_router.deliver_bridge_alert.call_args[0][0]
        assert alert.source == "counselor"
        assert alert.alert_type == "circuit_breaker_assessment"
        assert "TestAgent" in alert.title

    @pytest.mark.asyncio
    async def test_ward_room_escalate_uses_alert_severity(self) -> None:
        from probos.bridge_alerts import AlertSeverity
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        mock_router = AsyncMock()
        agent._ward_room_router = mock_router
        assessment = CounselorAssessment(timestamp=1000.0, agent_id="a1")
        await agent._post_assessment_to_ward_room(
            "a1", "T", assessment, "escalate", 1, "velocity",
        )
        alert = mock_router.deliver_bridge_alert.call_args[0][0]
        assert alert.severity == AlertSeverity.ALERT

    @pytest.mark.asyncio
    async def test_ward_room_concern_uses_advisory_severity(self) -> None:
        from probos.bridge_alerts import AlertSeverity
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        mock_router = AsyncMock()
        agent._ward_room_router = mock_router
        assessment = CounselorAssessment(timestamp=1000.0, agent_id="a1")
        await agent._post_assessment_to_ward_room(
            "a1", "T", assessment, "concern", 2, "rumination",
        )
        alert = mock_router.deliver_bridge_alert.call_args[0][0]
        assert alert.severity == AlertSeverity.ADVISORY

    @pytest.mark.asyncio
    async def test_ward_room_monitor_uses_info_severity(self) -> None:
        from probos.bridge_alerts import AlertSeverity
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        mock_router = AsyncMock()
        agent._ward_room_router = mock_router
        assessment = CounselorAssessment(timestamp=1000.0, agent_id="a1")
        await agent._post_assessment_to_ward_room(
            "a1", "T", assessment, "monitor", 1, "velocity",
        )
        alert = mock_router.deliver_bridge_alert.call_args[0][0]
        assert alert.severity == AlertSeverity.INFO

    @pytest.mark.asyncio
    async def test_ward_room_failure_does_not_block_assessment(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        mock_router = AsyncMock()
        mock_router.deliver_bridge_alert.side_effect = RuntimeError("WR down")
        agent._ward_room_router = mock_router
        agent._emit_event_fn = MagicMock()
        # Should not raise — log-and-degrade
        await agent._on_circuit_breaker_trip({
            "agent_id": "a1", "trip_count": 1,
            "cooldown_seconds": 900, "trip_reason": "velocity", "callsign": "T",
        })
        # Assessment still happened
        assert agent.get_profile("a1") is not None
        assert len(agent.get_profile("a1").assessments) == 1

    @pytest.mark.asyncio
    async def test_ward_room_skipped_when_no_router(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._ward_room_router = None
        assessment = CounselorAssessment(timestamp=1000.0, agent_id="a1")
        # Should not raise
        await agent._post_assessment_to_ward_room(
            "a1", "T", assessment, "monitor", 1, "velocity",
        )


class TestCircuitBreakerEventEnrichment:
    """AD-495: Enriched event data in circuit breaker trip emission."""

    def test_trip_event_includes_cooldown_seconds(self) -> None:
        from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
        cb = CognitiveCircuitBreaker(velocity_threshold=2, velocity_window_seconds=60)
        cb.record_event("a1", "proactive_think", "hello world")
        cb.record_event("a1", "proactive_think", "hello again")
        cb.check_and_trip("a1")
        status = cb.get_status("a1")
        assert "cooldown_seconds" in status
        assert status["cooldown_seconds"] > 0

    def test_trip_event_includes_trip_reason(self) -> None:
        from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
        cb = CognitiveCircuitBreaker(velocity_threshold=2, velocity_window_seconds=60)
        cb.record_event("a1", "proactive_think", "hello world")
        cb.record_event("a1", "proactive_think", "different content entirely")
        cb.check_and_trip("a1")
        status = cb.get_status("a1")
        assert "trip_reason" in status
        assert status["trip_reason"] != "unknown"

    def test_circuit_breaker_records_trip_reason_velocity(self) -> None:
        from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
        # Low threshold, different content → velocity only
        cb = CognitiveCircuitBreaker(
            velocity_threshold=2, velocity_window_seconds=60,
            similarity_threshold=0.99,  # Very high so similarity won't fire
            similarity_min_events=2,
        )
        cb.record_event("a1", "proactive_think", "apple banana cherry")
        cb.record_event("a1", "proactive_think", "xylophone zebra quantum")
        assert cb.check_and_trip("a1") is True
        assert cb._trip_reasons["a1"] == "velocity"

    def test_circuit_breaker_records_trip_reason_rumination(self) -> None:
        from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
        # High velocity threshold (won't fire), identical content → rumination only
        cb = CognitiveCircuitBreaker(
            velocity_threshold=100,  # Won't fire
            velocity_window_seconds=60,
            similarity_threshold=0.5,
            similarity_min_events=4,
        )
        for _ in range(5):
            cb.record_event("a1", "proactive_think", "same words repeated here")
        assert cb.check_and_trip("a1") is True
        assert cb._trip_reasons["a1"] == "rumination"

    def test_circuit_breaker_records_trip_reason_both(self) -> None:
        from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
        # Both signals fire: low velocity threshold + identical content
        cb = CognitiveCircuitBreaker(
            velocity_threshold=4,
            velocity_window_seconds=60,
            similarity_threshold=0.5,
            similarity_min_events=4,
        )
        for _ in range(5):
            cb.record_event("a1", "proactive_think", "same words repeated here")
        assert cb.check_and_trip("a1") is True
        assert cb._trip_reasons["a1"] == "velocity+rumination"


class TestTriggerValues:
    """AD-495: Specific trigger values for each assessment source."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_trigger_value(self) -> None:
        from probos.cognitive.counselor import CounselorAgent
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._emit_event_fn = MagicMock()
        await agent._on_circuit_breaker_trip({
            "agent_id": "a1", "trip_count": 1,
            "cooldown_seconds": 900, "trip_reason": "velocity", "callsign": "T",
        })
        assert agent.get_profile("a1").assessments[0].trigger == "circuit_breaker"

    @pytest.mark.asyncio
    async def test_trust_update_trigger_value(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CognitiveBaseline
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent.set_baseline("a1", CognitiveBaseline(trust_score=0.8))
        await agent._on_trust_update({"agent_id": "a1", "new_score": 0.4})
        assert agent.get_profile("a1").assessments[0].trigger == "trust_update"


class TestSaveProfileHelper:
    """AD-495: DRY persistence helper."""

    @pytest.mark.asyncio
    async def test_save_profile_and_assessment_persists_both(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        mock_store = MagicMock(spec=["save_profile", "save_assessment"])
        mock_store.save_profile = AsyncMock()
        mock_store.save_assessment = AsyncMock()
        agent._profile_store = mock_store
        # Create profile first
        agent.get_or_create_profile("a1", "builder")
        assessment = CounselorAssessment(agent_id="a1", timestamp=1000.0)
        await agent._save_profile_and_assessment("a1", assessment)
        mock_store.save_profile.assert_called_once()
        mock_store.save_assessment.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_profile_and_assessment_handles_no_store(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        agent._profile_store = None
        agent.get_or_create_profile("a1", "builder")
        assessment = CounselorAssessment(agent_id="a1", timestamp=1000.0)
        # Should not raise
        await agent._save_profile_and_assessment("a1", assessment)

    @pytest.mark.asyncio
    async def test_save_profile_and_assessment_handles_store_error(self) -> None:
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment
        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        mock_store = MagicMock(spec=["save_profile", "save_assessment"])
        mock_store.save_profile = AsyncMock(side_effect=RuntimeError("DB error"))
        mock_store.save_assessment = AsyncMock()
        agent._profile_store = mock_store
        agent.get_or_create_profile("a1", "builder")
        assessment = CounselorAssessment(agent_id="a1", timestamp=1000.0)
        # Should not raise — logged, not propagated
        await agent._save_profile_and_assessment("a1", assessment)
