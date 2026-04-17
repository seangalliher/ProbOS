"""AD-638: Cold-Start Boot Camp Protocol tests."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.boot_camp import (
    AgentBootCampState,
    BootCampCoordinator,
    _DEPARTMENT_CHIEFS,
)
from probos.config import BootCampConfig
from probos.events import EventType


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeChannel:
    id: str = "ch-001"
    channel_type: str = "ship"
    department: str = ""


@dataclass
class FakeThread:
    id: str = "thread-001"


@dataclass
class FakeDMChannel:
    id: str = "dm-001"


@dataclass
class FakePost:
    id: str = "post-001"


def _make_ward_room() -> MagicMock:
    wr = AsyncMock()
    wr.get_or_create_dm_channel = AsyncMock(return_value=FakeDMChannel())
    wr.create_thread = AsyncMock(return_value=FakeThread())
    wr.create_post = AsyncMock(return_value=FakePost())
    wr.list_channels = AsyncMock(return_value=[FakeChannel()])
    return wr


def _make_trust() -> MagicMock:
    trust = MagicMock()
    trust.get_trust_score = MagicMock(return_value=0.5)
    return trust


def _make_episodic() -> AsyncMock:
    ep = AsyncMock()
    ep.count_for_agent = AsyncMock(return_value=10)
    return ep


def _make_config(**overrides) -> BootCampConfig:
    defaults = {
        "enabled": True,
        "min_episodes": 5,
        "min_ward_room_posts": 3,
        "min_dm_conversations": 1,
        "min_trust_score": 0.55,
        "min_time_minutes": 0,  # 0 for tests — skip time gate
        "timeout_minutes": 120,
        "nudge_cooldown_seconds": 0,  # 0 for tests — no cooldown
    }
    defaults.update(overrides)
    return BootCampConfig(**defaults)


_CREW = [
    {"agent_id": "agent-1", "callsign": "Chapel", "department": "medical"},
    {"agent_id": "agent-2", "callsign": "LaForge", "department": "engineering"},
    {"agent_id": "agent-3", "callsign": "Kira", "department": "science"},
]


def _make_coordinator(**overrides) -> BootCampCoordinator:
    return BootCampCoordinator(
        config=overrides.pop("config", _make_config()),
        ward_room=overrides.pop("ward_room", _make_ward_room()),
        trust_service=overrides.pop("trust_service", _make_trust()),
        episodic_memory=overrides.pop("episodic_memory", _make_episodic()),
        emit_event_fn=overrides.pop("emit_event_fn", MagicMock()),
    )


# ---------------------------------------------------------------------------
# Test 1: Cold-start detection triggers boot camp
# ---------------------------------------------------------------------------

class TestActivation:
    @pytest.mark.asyncio
    async def test_activate_enrolls_agents(self):
        coord = _make_coordinator()
        await coord.activate(_CREW)
        assert coord.is_active
        assert len(coord._agents) == 3
        for info in _CREW:
            assert coord.is_enrolled(info["agent_id"])

    @pytest.mark.asyncio
    async def test_activate_emits_event(self):
        emit = MagicMock()
        coord = _make_coordinator(emit_event_fn=emit)
        await coord.activate(_CREW)
        emit.assert_called_once()
        args = emit.call_args
        assert args[0][0] == EventType.BOOT_CAMP_ACTIVATED
        assert args[0][1]["agent_count"] == 3

    @pytest.mark.asyncio
    async def test_activate_disabled_config(self):
        """Test 15: Config disabled → boot camp not activated."""
        coord = _make_coordinator(config=_make_config(enabled=False))
        await coord.activate(_CREW)
        assert not coord.is_active
        assert len(coord._agents) == 0

    @pytest.mark.asyncio
    async def test_duplicate_activation_ignored(self):
        coord = _make_coordinator()
        await coord.activate(_CREW)
        await coord.activate(_CREW)  # Should log warning, not double-enroll
        assert len(coord._agents) == 3


# ---------------------------------------------------------------------------
# Test 2: Enrollment only for crew agents (infra excluded — tested by caller)
# ---------------------------------------------------------------------------

class TestEnrollment:
    @pytest.mark.asyncio
    async def test_all_crew_enrolled(self):
        coord = _make_coordinator()
        await coord.activate(_CREW)
        for info in _CREW:
            state = coord.get_state(info["agent_id"])
            assert state is not None
            assert state.callsign == info["callsign"]
            assert state.department == info["department"]


# ---------------------------------------------------------------------------
# Test 3: Phase 2 introduction DMs
# ---------------------------------------------------------------------------

class TestPhase2:
    @pytest.mark.asyncio
    async def test_introduction_dms_sent(self):
        wr = _make_ward_room()
        coord = _make_coordinator(ward_room=wr)
        await coord.activate(_CREW)
        await coord.run_phase_2_introductions("counselor-id", "Echo")
        # Should have created DM channels and threads
        assert wr.get_or_create_dm_channel.call_count >= len(_CREW)
        assert wr.create_thread.call_count >= len(_CREW)

    @pytest.mark.asyncio
    async def test_phase_advance_event(self):
        emit = MagicMock()
        coord = _make_coordinator(emit_event_fn=emit)
        await coord.activate(_CREW)
        await coord.run_phase_2_introductions("counselor-id", "Echo")
        # Activation + phase advances
        phase_events = [
            c for c in emit.call_args_list
            if c[0][0] == EventType.BOOT_CAMP_PHASE_ADVANCE
        ]
        assert len(phase_events) == 3  # One per agent


# ---------------------------------------------------------------------------
# Test 4: Phase 3 observation thread
# ---------------------------------------------------------------------------

class TestPhase3:
    @pytest.mark.asyncio
    async def test_observation_thread_created(self):
        wr = _make_ward_room()
        coord = _make_coordinator(ward_room=wr)
        await coord.activate(_CREW)
        await coord.run_phase_3_observation("counselor-id", "Echo")
        # Should have created the observation thread on All Hands
        # Plus notebook prompt DMs for each agent
        assert wr.create_thread.call_count >= 1 + len(_CREW)

    @pytest.mark.asyncio
    async def test_phase_3_advance_events(self):
        emit = MagicMock()
        coord = _make_coordinator(emit_event_fn=emit)
        await coord.activate(_CREW)
        await coord.run_phase_3_observation("counselor-id", "Echo")
        phase_events = [
            c for c in emit.call_args_list
            if c[0][0] == EventType.BOOT_CAMP_PHASE_ADVANCE
        ]
        assert len(phase_events) == 3


# ---------------------------------------------------------------------------
# Test 5-6: Graduation criteria
# ---------------------------------------------------------------------------

class TestGraduation:
    @pytest.mark.asyncio
    async def test_all_criteria_met_graduates(self):
        """Test 5: All criteria met → graduated."""
        coord = _make_coordinator()
        await coord.activate(_CREW)
        coord._trust.get_trust_score.return_value = 0.6  # Above graduation threshold
        state = coord.get_state("agent-1")
        state.ward_room_posts = 5
        state.dm_conversations = 2
        result = await coord.check_graduation("agent-1")
        assert result is True
        assert state.graduated

    @pytest.mark.asyncio
    async def test_missing_episodes_not_graduated(self):
        """Test 6: Missing episodes → not graduated."""
        ep = AsyncMock()
        ep.count_for_agent = AsyncMock(return_value=2)  # Below threshold
        coord = _make_coordinator(episodic_memory=ep)
        await coord.activate(_CREW)
        state = coord.get_state("agent-1")
        state.ward_room_posts = 5
        state.dm_conversations = 2
        result = await coord.check_graduation("agent-1")
        assert result is False
        assert not state.graduated

    @pytest.mark.asyncio
    async def test_missing_posts_not_graduated(self):
        coord = _make_coordinator()
        await coord.activate(_CREW)
        state = coord.get_state("agent-1")
        state.ward_room_posts = 1  # Below threshold
        state.dm_conversations = 2
        result = await coord.check_graduation("agent-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_missing_dms_not_graduated(self):
        coord = _make_coordinator()
        await coord.activate(_CREW)
        state = coord.get_state("agent-1")
        state.ward_room_posts = 5
        state.dm_conversations = 0  # Below threshold
        result = await coord.check_graduation("agent-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_low_trust_not_graduated(self):
        trust = MagicMock()
        trust.get_trust_score = MagicMock(return_value=0.4)  # Below threshold
        coord = _make_coordinator(trust_service=trust)
        await coord.activate(_CREW)
        state = coord.get_state("agent-1")
        state.ward_room_posts = 5
        state.dm_conversations = 2
        result = await coord.check_graduation("agent-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_time_gate(self):
        config = _make_config(min_time_minutes=60)
        coord = _make_coordinator(config=config)
        await coord.activate(_CREW)
        state = coord.get_state("agent-1")
        state.ward_room_posts = 5
        state.dm_conversations = 2
        # Enrolled just now, min_time is 60 min → should fail
        result = await coord.check_graduation("agent-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_graduation_event(self):
        emit = MagicMock()
        coord = _make_coordinator(emit_event_fn=emit)
        await coord.activate(_CREW)
        coord._trust.get_trust_score.return_value = 0.6  # Above graduation threshold
        state = coord.get_state("agent-1")
        state.ward_room_posts = 5
        state.dm_conversations = 2
        await coord.check_graduation("agent-1")
        grad_events = [
            c for c in emit.call_args_list
            if c[0][0] == EventType.BOOT_CAMP_GRADUATION
        ]
        assert len(grad_events) == 1
        data = grad_events[0][0][1]
        assert data["agent_id"] == "agent-1"
        assert data["callsign"] == "Chapel"

    @pytest.mark.asyncio
    async def test_all_graduated_deactivates_boot_camp(self):
        coord = _make_coordinator()
        await coord.activate(_CREW)
        coord._trust.get_trust_score.return_value = 0.6  # Above graduation threshold
        for info in _CREW:
            state = coord.get_state(info["agent_id"])
            state.ward_room_posts = 5
            state.dm_conversations = 2
            await coord.check_graduation(info["agent_id"])
        assert not coord.is_active  # All graduated → deactivated


# ---------------------------------------------------------------------------
# Test 7-8: Quality gate bypass (evaluate/reflect)
# ---------------------------------------------------------------------------

class TestQualityGateBypass:
    @pytest.mark.asyncio
    async def test_evaluate_bypass(self):
        """Test 7: _boot_camp_active context → evaluate auto-approve."""
        from probos.cognitive.sub_task import SubTaskSpec, SubTaskType, SubTaskResult
        from probos.cognitive.sub_tasks.evaluate import EvaluateHandler

        handler = EvaluateHandler.__new__(EvaluateHandler)
        handler._llm_client = MagicMock()  # Must be non-None to pass LLM guard
        handler._runtime = None

        spec = SubTaskSpec(sub_task_type=SubTaskType.EVALUATE, name="eval-test")
        context = {"_boot_camp_active": True, "_agent_type": "test"}
        prior = [
            SubTaskResult(
                sub_task_type=SubTaskType.COMPOSE,
                name="compose-test",
                result={"output": "test output"},
            )
        ]

        result = await handler(spec, context, prior)
        assert result.result["pass"] is True
        assert result.result["bypass_reason"] == "boot_camp"
        assert result.result["score"] == 0.8

    @pytest.mark.asyncio
    async def test_reflect_bypass(self):
        """Test 8: _boot_camp_active context → reflect pass-through."""
        from probos.cognitive.sub_task import SubTaskSpec, SubTaskType, SubTaskResult
        from probos.cognitive.sub_tasks.reflect import ReflectHandler

        handler = ReflectHandler.__new__(ReflectHandler)
        handler._llm_client = MagicMock()  # Must be non-None to pass LLM guard
        handler._runtime = None

        spec = SubTaskSpec(sub_task_type=SubTaskType.REFLECT, name="reflect-test")
        context = {"_boot_camp_active": True, "_agent_type": "test"}
        prior = [
            SubTaskResult(
                sub_task_type=SubTaskType.COMPOSE,
                name="compose-test",
                result={"output": "test output"},
            )
        ]

        result = await handler(spec, context, prior)
        assert result.result["revised"] is False
        assert result.result["bypass_reason"] == "boot_camp"


# ---------------------------------------------------------------------------
# Test 9: Boot camp timeout → force-graduate
# ---------------------------------------------------------------------------

class TestTimeout:
    @pytest.mark.asyncio
    async def test_force_graduate_all(self):
        """Test 9: After timeout, all agents force-graduated."""
        emit = MagicMock()
        coord = _make_coordinator(emit_event_fn=emit)
        await coord.activate(_CREW)
        await coord.force_graduate_all()

        for info in _CREW:
            state = coord.get_state(info["agent_id"])
            assert state.graduated
            assert state.phase == 4

        assert not coord.is_active

        timeout_events = [
            c for c in emit.call_args_list
            if c[0][0] == EventType.BOOT_CAMP_TIMEOUT
        ]
        assert len(timeout_events) == 1

    @pytest.mark.asyncio
    async def test_check_timeout_triggers_force_graduate(self):
        config = _make_config(timeout_minutes=0)  # 0 = immediate timeout
        coord = _make_coordinator(config=config)
        await coord.activate(_CREW)
        # Backdate start time
        coord._started_at = time.time() - 1
        await coord.check_timeout()
        assert not coord.is_active
        for info in _CREW:
            assert coord.get_state(info["agent_id"]).graduated


# ---------------------------------------------------------------------------
# Test 10: Warm boot skips boot camp
# ---------------------------------------------------------------------------

class TestWarmBoot:
    @pytest.mark.asyncio
    async def test_not_activated_when_disabled(self):
        """Test 10: Warm boot → boot camp not activated (via config disabled)."""
        coord = _make_coordinator(config=_make_config(enabled=False))
        await coord.activate(_CREW)
        assert not coord.is_active


# ---------------------------------------------------------------------------
# Test 11: Nudge cooldown
# ---------------------------------------------------------------------------

class TestNudgeCooldown:
    @pytest.mark.asyncio
    async def test_nudge_cooldown_blocks_second_nudge(self):
        """Test 11: Second nudge within cooldown → skipped."""
        config = _make_config(nudge_cooldown_seconds=3600)  # 1 hour cooldown
        wr = _make_ward_room()
        coord = _make_coordinator(config=config, ward_room=wr)
        await coord.activate(_CREW)

        # First run sends nudges
        await coord.run_phase_2_introductions("counselor-id", "Echo")
        first_count = wr.create_thread.call_count

        # Second run — should be blocked by cooldown
        await coord.run_phase_2_introductions("counselor-id", "Echo")
        assert wr.create_thread.call_count == first_count  # No new calls


# ---------------------------------------------------------------------------
# Test 12-13: Post and DM tracking
# ---------------------------------------------------------------------------

class TestActivityTracking:
    @pytest.mark.asyncio
    async def test_post_tracking(self):
        """Test 12: Agent posts in Ward Room → on_agent_post updates state."""
        coord = _make_coordinator()
        await coord.activate(_CREW)
        await coord.on_agent_post("agent-1", "ship")
        state = coord.get_state("agent-1")
        assert state.ward_room_posts == 1

    @pytest.mark.asyncio
    async def test_dm_tracking(self):
        """Test 13: Agent sends DM → on_agent_dm updates state."""
        coord = _make_coordinator()
        await coord.activate(_CREW)
        await coord.on_agent_dm("agent-1")
        state = coord.get_state("agent-1")
        assert state.dm_conversations == 1

    @pytest.mark.asyncio
    async def test_post_triggers_graduation_check(self):
        """Post tracking triggers graduation check automatically."""
        coord = _make_coordinator()
        await coord.activate(_CREW)
        coord._trust.get_trust_score.return_value = 0.6  # Above graduation threshold
        state = coord.get_state("agent-1")
        state.dm_conversations = 2

        # Post 3 times to meet threshold
        for _ in range(3):
            await coord.on_agent_post("agent-1", "ship")

        # Should now be graduated (episodes=10, posts=3, dms=2, trust=0.6)
        assert state.graduated


# ---------------------------------------------------------------------------
# Test 14: Event emission at lifecycle points
# ---------------------------------------------------------------------------

class TestEventEmission:
    @pytest.mark.asyncio
    async def test_all_event_types_emitted(self):
        """Test 14: All 4 event types emitted at correct lifecycle points."""
        emit = MagicMock()
        coord = _make_coordinator(emit_event_fn=emit)

        # Activation
        await coord.activate(_CREW)
        coord._trust.get_trust_score.return_value = 0.6  # Above graduation threshold
        # Phase advance
        await coord.run_phase_2_introductions("counselor-id", "Echo")
        # Graduation
        state = coord.get_state("agent-1")
        state.ward_room_posts = 5
        state.dm_conversations = 2
        await coord.check_graduation("agent-1")
        # Force remaining
        await coord.force_graduate_all()

        event_types = [c[0][0] for c in emit.call_args_list]
        assert EventType.BOOT_CAMP_ACTIVATED in event_types
        assert EventType.BOOT_CAMP_PHASE_ADVANCE in event_types
        assert EventType.BOOT_CAMP_GRADUATION in event_types
        assert EventType.BOOT_CAMP_TIMEOUT in event_types


# ---------------------------------------------------------------------------
# Test 17: Graduated agent not bypassed
# ---------------------------------------------------------------------------

class TestGraduatedNotBypassed:
    @pytest.mark.asyncio
    async def test_graduated_not_enrolled(self):
        """Test 17: After graduation, is_enrolled returns False."""
        coord = _make_coordinator()
        await coord.activate(_CREW)
        coord._trust.get_trust_score.return_value = 0.6  # Above graduation threshold
        state = coord.get_state("agent-1")
        state.ward_room_posts = 5
        state.dm_conversations = 2
        await coord.check_graduation("agent-1")
        assert not coord.is_enrolled("agent-1")


# ---------------------------------------------------------------------------
# Test 18: Force-graduate cleans up state
# ---------------------------------------------------------------------------

class TestForceGraduateCleanup:
    @pytest.mark.asyncio
    async def test_cleanup(self):
        """Test 18: Post-timeout, all agents marked graduated, boot camp deactivated."""
        coord = _make_coordinator()
        await coord.activate(_CREW)
        await coord.force_graduate_all()
        assert not coord.is_active
        for info in _CREW:
            state = coord.get_state(info["agent_id"])
            assert state.graduated
            assert state.graduated_at is not None
            assert state.phase == 4


# ---------------------------------------------------------------------------
# Test 19: Full lifecycle integration
# ---------------------------------------------------------------------------

class TestFullLifecycle:
    @pytest.mark.asyncio
    async def test_full_lifecycle(self):
        """Test 19: cold start → enrollment → phase 2 → phase 3 → graduation → active duty."""
        emit = MagicMock()
        coord = _make_coordinator(emit_event_fn=emit)

        # Cold start → activation
        await coord.activate(_CREW)
        assert coord.is_active

        # Phase 2
        await coord.run_phase_2_introductions("counselor-id", "Echo")
        for info in _CREW:
            assert coord.get_state(info["agent_id"]).phase >= 2

        # Phase 3
        await coord.run_phase_3_observation("counselor-id", "Echo")
        for info in _CREW:
            assert coord.get_state(info["agent_id"]).phase >= 3

        # Simulate activity for all agents
        coord._trust.get_trust_score.return_value = 0.6  # Above graduation threshold
        for info in _CREW:
            state = coord.get_state(info["agent_id"])
            state.ward_room_posts = 5
            state.dm_conversations = 2

        # Graduate all
        for info in _CREW:
            await coord.check_graduation(info["agent_id"])
            assert coord.get_state(info["agent_id"]).graduated

        # Boot camp deactivated
        assert not coord.is_active


# ---------------------------------------------------------------------------
# Test 20: Unknown agent operations are safe
# ---------------------------------------------------------------------------

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_unknown_agent_post(self):
        coord = _make_coordinator()
        await coord.activate(_CREW)
        await coord.on_agent_post("unknown-agent", "ship")  # Should not raise

    @pytest.mark.asyncio
    async def test_unknown_agent_dm(self):
        coord = _make_coordinator()
        await coord.activate(_CREW)
        await coord.on_agent_dm("unknown-agent")  # Should not raise

    @pytest.mark.asyncio
    async def test_check_graduation_unknown_agent(self):
        coord = _make_coordinator()
        await coord.activate(_CREW)
        result = await coord.check_graduation("unknown-agent")
        assert result is True  # Unknown = treat as already graduated

    @pytest.mark.asyncio
    async def test_observation_thread_shared(self):
        """Observation thread is reused across calls."""
        coord = _make_coordinator()
        await coord.activate(_CREW)
        await coord.run_phase_3_observation("counselor-id", "Echo")
        thread_id_1 = coord._observation_thread_id
        # Reset phases so they can advance again
        for state in coord._agents.values():
            state.phase = 2
        await coord.run_phase_3_observation("counselor-id", "Echo")
        # Thread ID should be reused
        assert coord._observation_thread_id == thread_id_1

    @pytest.mark.asyncio
    async def test_emit_event_failure_safe(self):
        """Emit failure is caught and logged, not propagated."""
        emit = MagicMock(side_effect=RuntimeError("emit broken"))
        coord = _make_coordinator(emit_event_fn=emit)
        # Should not raise
        await coord.activate(_CREW)
        assert coord.is_active
