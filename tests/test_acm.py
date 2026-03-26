"""Tests for AD-427: Agent Capital Management (ACM) — Core Framework."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from probos.acm import (
    AgentCapitalService,
    LifecycleState,
    LifecycleTransition,
)


@pytest.fixture
async def acm(tmp_path):
    """Provide a started AgentCapitalService."""
    svc = AgentCapitalService(data_dir=str(tmp_path))
    await svc.start()
    yield svc
    await svc.stop()


# ---------------------------------------------------------------------------
# Lifecycle State Machine
# ---------------------------------------------------------------------------


class TestLifecycleStateMachine:
    """AD-427: Agent lifecycle transitions."""

    @pytest.mark.asyncio
    async def test_initial_state_is_registered(self, acm):
        """New agent starts as REGISTERED."""
        state = await acm.get_lifecycle_state("unknown-agent")
        assert state == LifecycleState.REGISTERED

    @pytest.mark.asyncio
    async def test_onboard_transitions_to_probationary(self, acm):
        """onboard() creates record and transitions REGISTERED → PROBATIONARY."""
        t = await acm.onboard("a1", "scout", "recon_pool", "science")
        assert t.from_state == "registered"
        assert t.to_state == "probationary"
        state = await acm.get_lifecycle_state("a1")
        assert state == LifecycleState.PROBATIONARY

    @pytest.mark.asyncio
    async def test_probationary_to_active(self, acm):
        """transition() allows PROBATIONARY → ACTIVE."""
        await acm.onboard("a1", "scout", "pool", "science")
        t = await acm.transition("a1", LifecycleState.ACTIVE, reason="Trust threshold met")
        assert t.from_state == "probationary"
        assert t.to_state == "active"
        assert await acm.get_lifecycle_state("a1") == LifecycleState.ACTIVE

    @pytest.mark.asyncio
    async def test_active_to_suspended(self, acm):
        """transition() allows ACTIVE → SUSPENDED (Captain order)."""
        await acm.onboard("a1", "scout", "pool", "science")
        await acm.transition("a1", LifecycleState.ACTIVE)
        t = await acm.transition(
            "a1", LifecycleState.SUSPENDED,
            reason="Captain order", initiated_by="captain",
        )
        assert t.to_state == "suspended"
        assert await acm.get_lifecycle_state("a1") == LifecycleState.SUSPENDED

    @pytest.mark.asyncio
    async def test_suspended_to_active(self, acm):
        """transition() allows SUSPENDED → ACTIVE (reinstatement)."""
        await acm.onboard("a1", "scout", "pool", "science")
        await acm.transition("a1", LifecycleState.ACTIVE)
        await acm.transition("a1", LifecycleState.SUSPENDED)
        t = await acm.transition(
            "a1", LifecycleState.ACTIVE,
            reason="Reinstated", initiated_by="captain",
        )
        assert t.from_state == "suspended"
        assert t.to_state == "active"

    @pytest.mark.asyncio
    async def test_active_to_decommissioned(self, acm):
        """decommission() transitions ACTIVE → DECOMMISSIONED."""
        await acm.onboard("a1", "scout", "pool", "science")
        await acm.transition("a1", LifecycleState.ACTIVE)
        t = await acm.decommission("a1", reason="End of service")
        assert t.to_state == "decommissioned"
        assert await acm.get_lifecycle_state("a1") == LifecycleState.DECOMMISSIONED

    @pytest.mark.asyncio
    async def test_illegal_transition_raises(self, acm):
        """Illegal transitions (e.g., REGISTERED → ACTIVE) raise ValueError."""
        await acm.onboard("a1", "scout", "pool", "science")
        # PROBATIONARY → SUSPENDED is not legal
        with pytest.raises(ValueError, match="Illegal lifecycle transition"):
            await acm.transition("a1", LifecycleState.SUSPENDED)

    @pytest.mark.asyncio
    async def test_decommissioned_is_terminal(self, acm):
        """Cannot transition out of DECOMMISSIONED."""
        await acm.onboard("a1", "scout", "pool", "science")
        await acm.transition("a1", LifecycleState.ACTIVE)
        await acm.decommission("a1")
        with pytest.raises(ValueError):
            await acm.transition("a1", LifecycleState.ACTIVE)

    @pytest.mark.asyncio
    async def test_transition_history_recorded(self, acm):
        """All transitions are recorded in audit trail."""
        await acm.onboard("a1", "scout", "pool", "science")
        await acm.transition("a1", LifecycleState.ACTIVE)
        history = await acm.get_transition_history("a1")
        assert len(history) == 2  # registered→probationary, probationary→active
        assert all(isinstance(t, LifecycleTransition) for t in history)

    @pytest.mark.asyncio
    async def test_transition_history_ordered_by_timestamp(self, acm):
        """get_transition_history() returns transitions in chronological order."""
        await acm.onboard("a1", "scout", "pool", "science")
        await acm.transition("a1", LifecycleState.ACTIVE)
        await acm.transition("a1", LifecycleState.SUSPENDED)
        history = await acm.get_transition_history("a1")
        assert len(history) == 3
        for i in range(len(history) - 1):
            assert history[i].timestamp <= history[i + 1].timestamp

    @pytest.mark.asyncio
    async def test_probationary_to_decommissioned(self, acm):
        """Failed probation: PROBATIONARY → DECOMMISSIONED is legal."""
        await acm.onboard("a1", "scout", "pool", "science")
        t = await acm.decommission("a1", reason="Failed probation")
        assert t.to_state == "decommissioned"

    @pytest.mark.asyncio
    async def test_suspended_to_decommissioned(self, acm):
        """SUSPENDED → DECOMMISSIONED is legal."""
        await acm.onboard("a1", "scout", "pool", "science")
        await acm.transition("a1", LifecycleState.ACTIVE)
        await acm.transition("a1", LifecycleState.SUSPENDED)
        t = await acm.decommission("a1")
        assert t.to_state == "decommissioned"


# ---------------------------------------------------------------------------
# Consolidated Profile
# ---------------------------------------------------------------------------


class TestConsolidatedProfile:
    """AD-427: Consolidated profile view."""

    @pytest.mark.asyncio
    async def test_profile_includes_lifecycle_state(self, acm):
        """Consolidated profile contains lifecycle_state field."""
        await acm.onboard("a1", "scout", "pool", "science")
        rt = MagicMock()
        rt.trust_network = MagicMock()
        rt.trust_network.get_score = MagicMock(return_value=0.65)
        rt.registry = MagicMock()
        rt.registry.get = MagicMock(return_value=None)
        rt.skill_service = None
        rt.episodic_memory = None
        rt.profile_store = None

        profile = await acm.get_consolidated_profile("a1", rt)
        assert profile["lifecycle_state"] == "probationary"
        assert profile["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_profile_includes_trust(self, acm):
        """Consolidated profile contains trust from TrustNetwork."""
        await acm.onboard("a1", "scout", "pool", "science")
        rt = MagicMock()
        rt.trust_network = MagicMock()
        rt.trust_network.get_score = MagicMock(return_value=0.7523)
        rt.registry = MagicMock()
        rt.registry.get = MagicMock(return_value=None)
        rt.skill_service = None
        rt.episodic_memory = None
        rt.profile_store = None

        profile = await acm.get_consolidated_profile("a1", rt)
        assert profile["trust"] == 0.7523

    @pytest.mark.asyncio
    async def test_profile_includes_skills(self, acm):
        """Consolidated profile contains skill_count and avg_proficiency."""
        await acm.onboard("a1", "scout", "pool", "science")

        mock_skill_profile = MagicMock()
        mock_skill_profile.total_skills = 5
        mock_skill_profile.avg_proficiency = 3.2

        rt = MagicMock()
        rt.trust_network = MagicMock()
        rt.trust_network.get_score = MagicMock(return_value=0.7)
        rt.registry = MagicMock()
        rt.registry.get = MagicMock(return_value=None)
        rt.skill_service = MagicMock()
        rt.skill_service.get_profile = AsyncMock(return_value=mock_skill_profile)
        rt.episodic_memory = None
        rt.profile_store = None

        profile = await acm.get_consolidated_profile("a1", rt)
        assert profile["skill_count"] == 5
        assert profile["avg_proficiency"] == 3.2

    @pytest.mark.asyncio
    async def test_profile_includes_episode_count(self, acm):
        """Consolidated profile contains episode_count from EpisodicMemory."""
        await acm.onboard("a1", "scout", "pool", "science")
        rt = MagicMock()
        rt.trust_network = MagicMock()
        rt.trust_network.get_score = MagicMock(return_value=0.7)
        rt.registry = MagicMock()
        rt.registry.get = MagicMock(return_value=None)
        rt.skill_service = None
        rt.profile_store = None
        rt.episodic_memory = MagicMock()
        rt.episodic_memory.count_for_agent = AsyncMock(return_value=42)

        profile = await acm.get_consolidated_profile("a1", rt)
        assert profile["episode_count"] == 42

    @pytest.mark.asyncio
    async def test_profile_graceful_when_subsystems_unavailable(self, acm):
        """Profile returns partial data when some subsystems are missing."""
        await acm.onboard("a1", "scout", "pool", "science")
        rt = MagicMock(spec=[])  # No attributes at all

        profile = await acm.get_consolidated_profile("a1", rt)
        # Should still have lifecycle data
        assert profile["lifecycle_state"] == "probationary"
        assert profile["agent_id"] == "a1"
        # Should not have trust, skills, etc.
        assert "trust" not in profile
        assert "skill_count" not in profile


# ---------------------------------------------------------------------------
# Onboarding Integration
# ---------------------------------------------------------------------------


class TestOnboardingIntegration:
    """AD-427: Onboarding during agent wiring."""

    @pytest.mark.asyncio
    async def test_crew_agent_onboarded_during_wiring(self, acm):
        """Crew agents get onboarded (PROBATIONARY) during onboard()."""
        await acm.onboard("eng-1", "engineering_officer", "eng_pool", "engineering")
        state = await acm.get_lifecycle_state("eng-1")
        assert state == LifecycleState.PROBATIONARY

    @pytest.mark.asyncio
    async def test_warm_boot_does_not_duplicate_onboarding(self, acm):
        """Second onboard attempt for same agent doesn't create duplicate."""
        await acm.onboard("eng-1", "engineering_officer", "eng_pool", "engineering")
        # Second call — agent is already PROBATIONARY, transition will fail
        with pytest.raises(ValueError, match="Illegal lifecycle transition"):
            await acm.onboard("eng-1", "engineering_officer", "eng_pool", "engineering")

        # But state is still correct
        state = await acm.get_lifecycle_state("eng-1")
        assert state == LifecycleState.PROBATIONARY
        # Only one transition recorded
        history = await acm.get_transition_history("eng-1")
        assert len(history) == 1

    @pytest.mark.asyncio
    async def test_onboard_reason_includes_agent_type(self, acm):
        """Onboard transition reason includes agent_type and department."""
        t = await acm.onboard("sec-1", "security_officer", "sec_pool", "security")
        assert "security_officer" in t.reason
        assert "security" in t.reason


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestACMPersistence:
    """AD-427: ACM data persists across restarts."""

    @pytest.mark.asyncio
    async def test_state_persists_across_restart(self, tmp_path):
        """Lifecycle state survives service restart."""
        svc1 = AgentCapitalService(data_dir=str(tmp_path))
        await svc1.start()
        await svc1.onboard("a1", "scout", "pool", "science")
        await svc1.transition("a1", LifecycleState.ACTIVE)
        await svc1.stop()

        svc2 = AgentCapitalService(data_dir=str(tmp_path))
        await svc2.start()
        state = await svc2.get_lifecycle_state("a1")
        assert state == LifecycleState.ACTIVE
        history = await svc2.get_transition_history("a1")
        assert len(history) == 2
        await svc2.stop()


# ---------------------------------------------------------------------------
# API Endpoints (unit-level)
# ---------------------------------------------------------------------------


class TestACMEndpoints:
    """AD-427: ACM REST API endpoint logic."""

    @pytest.mark.asyncio
    async def test_get_profile_endpoint(self, acm):
        """get_consolidated_profile returns expected structure."""
        await acm.onboard("a1", "scout", "pool", "science")
        rt = MagicMock()
        rt.trust_network = MagicMock()
        rt.trust_network.get_score = MagicMock(return_value=0.7)
        rt.registry = MagicMock()
        rt.registry.get = MagicMock(return_value=None)
        rt.skill_service = None
        rt.episodic_memory = None
        rt.profile_store = None

        profile = await acm.get_consolidated_profile("a1", rt)
        assert "agent_id" in profile
        assert "lifecycle_state" in profile
        assert "trust" in profile

    @pytest.mark.asyncio
    async def test_get_lifecycle_endpoint(self, acm):
        """Lifecycle query returns state + history."""
        await acm.onboard("a1", "scout", "pool", "science")
        state = await acm.get_lifecycle_state("a1")
        history = await acm.get_transition_history("a1")
        assert state == LifecycleState.PROBATIONARY
        assert len(history) == 1

    @pytest.mark.asyncio
    async def test_decommission_endpoint(self, acm):
        """decommission() transitions to DECOMMISSIONED."""
        await acm.onboard("a1", "scout", "pool", "science")
        await acm.transition("a1", LifecycleState.ACTIVE)
        t = await acm.decommission("a1", reason="Retiring")
        assert t.to_state == "decommissioned"

    @pytest.mark.asyncio
    async def test_suspend_endpoint(self, acm):
        """Suspend transitions ACTIVE → SUSPENDED."""
        await acm.onboard("a1", "scout", "pool", "science")
        await acm.transition("a1", LifecycleState.ACTIVE)
        t = await acm.transition("a1", LifecycleState.SUSPENDED, reason="Investigation")
        assert t.to_state == "suspended"

    @pytest.mark.asyncio
    async def test_reinstate_endpoint(self, acm):
        """Reinstate transitions SUSPENDED → ACTIVE."""
        await acm.onboard("a1", "scout", "pool", "science")
        await acm.transition("a1", LifecycleState.ACTIVE)
        await acm.transition("a1", LifecycleState.SUSPENDED)
        t = await acm.transition("a1", LifecycleState.ACTIVE, reason="Cleared")
        assert t.to_state == "active"

    @pytest.mark.asyncio
    async def test_illegal_transition_returns_error(self, acm):
        """Illegal transitions raise ValueError."""
        await acm.onboard("a1", "scout", "pool", "science")
        # PROBATIONARY → SUSPENDED is illegal
        with pytest.raises(ValueError):
            await acm.transition("a1", LifecycleState.SUSPENDED)
