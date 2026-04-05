"""Tests for AD-567f: Social Verification Protocol.

28 tests covering corroboration, cascade detection, anchor independence,
integration (verification context + bridge alerts), and events.
"""

from __future__ import annotations

import dataclasses
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.social_verification import (
    CascadeRiskResult,
    CorroborationResult,
    SocialVerificationService,
    compute_anchor_independence,
    _are_independently_anchored,
)
from probos.config import SocialVerificationConfig
from probos.types import AnchorFrame, Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    *,
    agent_ids: list[str] | None = None,
    anchors: AnchorFrame | None = None,
    timestamp: float = 0.0,
    ep_id: str = "",
) -> Episode:
    return Episode(
        id=ep_id or f"ep-{id(agent_ids)}",
        agent_ids=agent_ids or [],
        anchors=anchors,
        timestamp=timestamp or time.time(),
        user_input="test episode",
    )


def _rich_anchors(idx: int) -> AnchorFrame:
    """Create anchors with enough fields to pass 0.3 confidence gate."""
    return AnchorFrame(
        duty_cycle_id=f"dc-{idx}",
        channel=f"ward_room",
        channel_id=f"ch-{idx}",
        department=f"dept-{idx}",
        participants=[f"agent-{idx}"],
        trigger_agent=f"agent-{idx}",
        trigger_type="observation",
    )


def _make_service(
    episodes: list[Episode] | None = None,
    config: SocialVerificationConfig | None = None,
    emit: MagicMock | None = None,
) -> SocialVerificationService:
    mem = AsyncMock()
    mem.recall = AsyncMock(return_value=episodes or [])
    cfg = config or SocialVerificationConfig()
    return SocialVerificationService(
        episodic_memory=mem,
        config=cfg,
        emit_event_fn=emit,
    )


# ===========================================================================
# 1. CorroborationResult tests (8)
# ===========================================================================

class TestCorroboration:
    """Tests for check_corroboration()."""

    @pytest.mark.asyncio
    async def test_corroboration_no_matching_episodes(self):
        """Empty recall returns score 0, not corroborated."""
        svc = _make_service(episodes=[])
        result = await svc.check_corroboration("agent-A", "test claim")
        assert isinstance(result, CorroborationResult)
        assert result.corroboration_score == 0.0
        assert not result.is_corroborated
        assert result.corroborating_agent_count == 0
        assert result.total_matching_episodes == 0

    @pytest.mark.asyncio
    async def test_corroboration_self_excluded(self):
        """Requesting agent's own episodes are excluded."""
        ep = _make_episode(agent_ids=["agent-A"], timestamp=100.0)
        svc = _make_service(episodes=[ep])
        result = await svc.check_corroboration("agent-A", "test claim")
        assert result.corroborating_agent_count == 0
        assert result.total_matching_episodes == 0

    @pytest.mark.asyncio
    async def test_corroboration_single_independent_agent(self):
        """One corroborating agent with good anchors."""
        anchors = AnchorFrame(
            duty_cycle_id="dc-1", channel_id="ch-1",
            department="science", participants=["Lynx"],
        )
        ep = _make_episode(
            agent_ids=["agent-B"], anchors=anchors, timestamp=100.0,
        )
        svc = _make_service(episodes=[ep])
        result = await svc.check_corroboration("agent-A", "test claim")
        assert result.corroborating_agent_count == 1
        assert result.total_matching_episodes == 1
        assert "agent-B" in result.matching_agents

    @pytest.mark.asyncio
    async def test_corroboration_multiple_independent_agents(self):
        """3+ agents with independent anchors → high independence and score."""
        eps = []
        for i in range(3):
            anchors = AnchorFrame(
                duty_cycle_id=f"dc-{i}", channel_id=f"ch-{i}",
                department=f"dept-{i}", participants=[f"agent-{i}"],
            )
            eps.append(_make_episode(
                agent_ids=[f"agent-{chr(66 + i)}"],
                anchors=anchors,
                timestamp=100.0 + i * 120,
                ep_id=f"ep-{i}",
            ))
        svc = _make_service(episodes=eps)
        result = await svc.check_corroboration("agent-A", "test claim")
        assert result.corroborating_agent_count == 3
        assert result.anchor_independence_score > 0.5
        assert result.corroboration_score > 0.0

    @pytest.mark.asyncio
    async def test_corroboration_same_thread_not_independent(self):
        """Two episodes from same thread_id count as dependent."""
        anchors_1 = AnchorFrame(
            duty_cycle_id="dc-1", channel_id="ch-1", thread_id="thread-X",
            department="eng",
        )
        anchors_2 = AnchorFrame(
            duty_cycle_id="dc-1", channel_id="ch-1", thread_id="thread-X",
            department="eng",
        )
        eps = [
            _make_episode(agent_ids=["B"], anchors=anchors_1, timestamp=100.0, ep_id="ep-1"),
            _make_episode(agent_ids=["C"], anchors=anchors_2, timestamp=105.0, ep_id="ep-2"),
        ]
        svc = _make_service(episodes=eps)
        result = await svc.check_corroboration("agent-A", "test claim")
        assert result.anchor_independence_score == 0.0

    @pytest.mark.asyncio
    async def test_corroboration_below_confidence_gate_filtered(self):
        """Low-anchor episodes excluded by min_confidence."""
        # No anchors → confidence 0.0 → below default 0.3 gate
        ep = _make_episode(agent_ids=["agent-B"], anchors=None, timestamp=100.0)
        svc = _make_service(episodes=[ep])
        result = await svc.check_corroboration("agent-A", "test claim")
        assert result.total_matching_episodes == 0

    @pytest.mark.asyncio
    async def test_corroboration_privacy_no_content_exposed(self):
        """Result contains NO episode content, only metadata."""
        anchors = AnchorFrame(
            duty_cycle_id="dc-1", channel_id="ch-1",
            department="science", participants=["agent-B"],
        )
        ep = _make_episode(agent_ids=["agent-B"], anchors=anchors, timestamp=100.0)
        svc = _make_service(episodes=[ep])
        result = await svc.check_corroboration("agent-A", "claim about topic X")

        result_dict = dataclasses.asdict(result)
        # Should NOT contain episode content fields
        assert "user_input" not in str(result_dict)
        assert "dag_summary" not in str(result_dict)
        assert "reflection" not in str(result_dict)
        # Should contain metadata
        assert result.anchor_summary is not None
        assert isinstance(result.matching_agents, list)
        assert isinstance(result.matching_departments, list)

    @pytest.mark.asyncio
    async def test_corroboration_threshold_boundary(self):
        """Score at threshold passes, below fails."""
        anchors = AnchorFrame(
            duty_cycle_id="dc-1", channel_id="ch-1",
            department="science", participants=["B"],
        )
        # Single agent with anchors — score will be some value
        ep = _make_episode(agent_ids=["B"], anchors=anchors, timestamp=100.0)

        # With very high threshold — should NOT be corroborated
        cfg = SocialVerificationConfig(corroboration_threshold=0.99)
        svc = _make_service(episodes=[ep], config=cfg)
        result = await svc.check_corroboration("A", "test claim")
        assert not result.is_corroborated

        # With very low threshold — should be corroborated
        cfg2 = SocialVerificationConfig(corroboration_threshold=0.01)
        svc2 = _make_service(episodes=[ep], config=cfg2)
        result2 = await svc2.check_corroboration("A", "test claim")
        assert result2.is_corroborated


# ===========================================================================
# 2. CascadeRiskResult tests (7)
# ===========================================================================

class TestCascadeRisk:
    """Tests for check_cascade_risk()."""

    @pytest.mark.asyncio
    async def test_cascade_no_peer_matches_returns_none(self):
        """No peer similarity = no cascade risk."""
        svc = _make_service()
        result = await svc.check_cascade_risk(
            "A", "Alpha", "post body", "ch-1", peer_matches=None,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_cascade_independent_anchors_no_risk(self):
        """Peer matches with independent anchors → 'none' risk."""
        # Episodes with different duty cycles → independent
        eps = [
            _make_episode(
                agent_ids=["B"], ep_id="ep-B",
                anchors=AnchorFrame(duty_cycle_id="dc-1", channel_id="ch-1"),
                timestamp=100.0,
            ),
            _make_episode(
                agent_ids=["A"], ep_id="ep-A",
                anchors=AnchorFrame(duty_cycle_id="dc-2", channel_id="ch-2"),
                timestamp=200.0,
            ),
        ]
        svc = _make_service(episodes=eps)
        peer_matches = [{"author_id": "B", "author_callsign": "Bravo", "timestamp": 100.0}]
        result = await svc.check_cascade_risk(
            "A", "Alpha", "post body", "ch-1", peer_matches=peer_matches,
        )
        assert result is not None
        assert result.risk_level == "none"

    @pytest.mark.asyncio
    async def test_cascade_low_risk(self):
        """1 match with weak anchors → 'low' risk."""
        # Episodes with no anchors → independence 0.0
        eps = [
            _make_episode(agent_ids=["B"], ep_id="ep-B", timestamp=100.0),
            _make_episode(agent_ids=["A"], ep_id="ep-A", timestamp=105.0),
        ]
        svc = _make_service(episodes=eps)
        peer_matches = [{"author_id": "B", "author_callsign": "Bravo", "timestamp": 100.0}]
        result = await svc.check_cascade_risk(
            "A", "Alpha", "post body", "ch-1", peer_matches=peer_matches,
        )
        assert result is not None
        assert result.risk_level == "low"

    @pytest.mark.asyncio
    async def test_cascade_medium_risk(self):
        """2 matches with weak anchors → 'medium' risk."""
        eps = [
            _make_episode(agent_ids=["B"], ep_id="ep-B", timestamp=100.0),
            _make_episode(agent_ids=["C"], ep_id="ep-C", timestamp=105.0),
            _make_episode(agent_ids=["A"], ep_id="ep-A", timestamp=110.0),
        ]
        svc = _make_service(episodes=eps)
        peer_matches = [
            {"author_id": "B", "author_callsign": "Bravo", "timestamp": 100.0},
            {"author_id": "C", "author_callsign": "Charlie", "timestamp": 105.0},
        ]
        result = await svc.check_cascade_risk(
            "A", "Alpha", "post body", "ch-1", peer_matches=peer_matches,
        )
        assert result is not None
        assert result.risk_level == "medium"

    @pytest.mark.asyncio
    async def test_cascade_high_risk(self):
        """3+ matches with zero anchors → 'high' risk."""
        eps = [
            _make_episode(agent_ids=["B"], ep_id="ep-B", timestamp=100.0),
            _make_episode(agent_ids=["C"], ep_id="ep-C", timestamp=105.0),
            _make_episode(agent_ids=["D"], ep_id="ep-D", timestamp=110.0),
            _make_episode(agent_ids=["A"], ep_id="ep-A", timestamp=115.0),
        ]
        svc = _make_service(episodes=eps)
        peer_matches = [
            {"author_id": "B", "author_callsign": "Bravo", "timestamp": 100.0},
            {"author_id": "C", "author_callsign": "Charlie", "timestamp": 105.0},
            {"author_id": "D", "author_callsign": "Delta", "timestamp": 110.0},
        ]
        result = await svc.check_cascade_risk(
            "A", "Alpha", "post body", "ch-1", peer_matches=peer_matches,
        )
        assert result is not None
        assert result.risk_level == "high"

    @pytest.mark.asyncio
    async def test_cascade_source_agent_earliest_post(self):
        """source_agent is the match with earliest timestamp."""
        eps = [
            _make_episode(agent_ids=["C"], ep_id="ep-C", timestamp=100.0),
            _make_episode(agent_ids=["B"], ep_id="ep-B", timestamp=200.0),
            _make_episode(agent_ids=["A"], ep_id="ep-A", timestamp=300.0),
        ]
        svc = _make_service(episodes=eps)
        peer_matches = [
            {"author_id": "B", "author_callsign": "Bravo", "timestamp": 200.0},
            {"author_id": "C", "author_callsign": "Charlie", "timestamp": 100.0},
        ]
        result = await svc.check_cascade_risk(
            "A", "Alpha", "post body", "ch-1", peer_matches=peer_matches,
        )
        assert result is not None
        assert result.source_agent == "Charlie"

    @pytest.mark.asyncio
    async def test_cascade_same_thread_dependent(self):
        """Matches sharing thread_id are not independent."""
        anchors = AnchorFrame(
            duty_cycle_id="dc-1", channel_id="ch-1", thread_id="same-thread",
        )
        eps = [
            _make_episode(agent_ids=["B"], ep_id="ep-B", anchors=anchors, timestamp=100.0),
            _make_episode(agent_ids=["C"], ep_id="ep-C", anchors=anchors, timestamp=105.0),
            _make_episode(agent_ids=["A"], ep_id="ep-A", anchors=anchors, timestamp=110.0),
        ]
        svc = _make_service(episodes=eps)
        peer_matches = [
            {"author_id": "B", "author_callsign": "Bravo", "timestamp": 100.0},
            {"author_id": "C", "author_callsign": "Charlie", "timestamp": 105.0},
        ]
        result = await svc.check_cascade_risk(
            "A", "Alpha", "post body", "ch-1", peer_matches=peer_matches,
        )
        assert result is not None
        # Same thread = not independent → should flag cascade risk
        assert result.anchor_independence_score == 0.0


# ===========================================================================
# 3. AnchorIndependence tests (5)
# ===========================================================================

class TestAnchorIndependence:
    """Tests for anchor independence computation."""

    def test_anchor_independence_different_duty_cycles(self):
        """Different duty_cycle_id = independent."""
        a = AnchorFrame(duty_cycle_id="dc-1")
        b = AnchorFrame(duty_cycle_id="dc-2")
        assert _are_independently_anchored(a, b) is True

    def test_anchor_independence_different_channels(self):
        """Different channel_id = independent."""
        a = AnchorFrame(channel_id="ch-1")
        b = AnchorFrame(channel_id="ch-2")
        assert _are_independently_anchored(a, b) is True

    def test_anchor_independence_time_separation(self):
        """Timestamps > 60s apart = independent (via compute_anchor_independence)."""
        ep1 = _make_episode(timestamp=100.0, ep_id="ep-1")
        ep2 = _make_episode(timestamp=200.0, ep_id="ep-2")
        score = compute_anchor_independence([ep1, ep2])
        assert score > 0.0

    def test_anchor_independence_same_thread_dependent(self):
        """Same thread_id = NOT independent."""
        a = AnchorFrame(thread_id="thread-X", duty_cycle_id="dc-1")
        b = AnchorFrame(thread_id="thread-X", duty_cycle_id="dc-2")
        assert _are_independently_anchored(a, b) is False

    def test_anchor_independence_no_anchors(self):
        """Episodes without anchors = not independent (score 0)."""
        ep1 = _make_episode(anchors=None, ep_id="ep-1", timestamp=100.0)
        ep2 = _make_episode(anchors=None, ep_id="ep-2", timestamp=105.0)
        # No anchors and timestamps only 5s apart
        assert _are_independently_anchored(None, None) is False
        score = compute_anchor_independence([ep1, ep2])
        assert score == 0.0


# ===========================================================================
# 4. Integration tests (5)
# ===========================================================================

class TestIntegration:
    """Tests for verification context and bridge alert integration."""

    @pytest.mark.asyncio
    async def test_verification_context_corroborated(self):
        """Returns '[VERIFIED: ...]' string."""
        eps = [
            _make_episode(
                agent_ids=[f"agent-{i}"], ep_id=f"ep-{i}",
                anchors=_rich_anchors(i),
                timestamp=100.0 + i * 120,
            )
            for i in range(3)
        ]
        cfg = SocialVerificationConfig(corroboration_threshold=0.01)
        svc = _make_service(episodes=eps, config=cfg)
        ctx = await svc.get_verification_context("agent-X", "test claim")
        assert ctx.startswith("[VERIFIED:")

    @pytest.mark.asyncio
    async def test_verification_context_unverified(self):
        """Returns '[UNVERIFIED: ...]' string."""
        svc = _make_service(episodes=[])
        ctx = await svc.get_verification_context("agent-X", "test claim")
        assert ctx.startswith("[UNVERIFIED:")

    @pytest.mark.asyncio
    async def test_verification_context_cascade(self):
        """Returns '[CASCADE RISK: ...]' string."""
        # Two agents echoing with same thread → cascade risk
        # Rich anchors so they pass confidence gate, but same thread = dependent
        anchors = AnchorFrame(
            duty_cycle_id="dc-1", channel="ward_room", channel_id="ch-1",
            department="eng", participants=["B", "C"],
            trigger_agent="B", trigger_type="observation",
            thread_id="thread-X",
        )
        eps = [
            _make_episode(agent_ids=["B"], anchors=anchors, timestamp=100.0, ep_id="ep-1"),
            _make_episode(agent_ids=["C"], anchors=anchors, timestamp=105.0, ep_id="ep-2"),
        ]
        cfg = SocialVerificationConfig(
            corroboration_threshold=0.99,
            cascade_independence_threshold=0.5,
        )
        svc = _make_service(episodes=eps, config=cfg)
        ctx = await svc.get_verification_context("agent-A", "test claim")
        assert ctx.startswith("[CASCADE RISK:")

    def test_bridge_alert_cascade_medium(self):
        """Medium risk creates ADVISORY bridge alert."""
        from probos.bridge_alerts import BridgeAlertService, AlertSeverity

        bas = BridgeAlertService.__new__(BridgeAlertService)
        bas._alert_log = []
        bas._recent = {}
        bas._cooldown = 300
        bas._max_log = 100

        alerts = bas.check_cascade_risk({
            "risk_level": "medium",
            "source_agent": "Bravo",
            "affected_agents": ["Bravo", "Charlie"],
            "propagation_count": 2,
            "anchor_independence_score": 0.1,
            "detail": "test cascade",
        })
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ADVISORY
        assert alerts[0].alert_type == "cascade_confabulation"

    def test_bridge_alert_cascade_high(self):
        """High risk creates ALERT severity bridge alert."""
        from probos.bridge_alerts import BridgeAlertService, AlertSeverity

        bas = BridgeAlertService.__new__(BridgeAlertService)
        bas._alert_log = []
        bas._recent = {}
        bas._cooldown = 300
        bas._max_log = 100

        alerts = bas.check_cascade_risk({
            "risk_level": "high",
            "source_agent": "Bravo",
            "affected_agents": ["Bravo", "Charlie", "Delta"],
            "propagation_count": 3,
            "anchor_independence_score": 0.0,
            "detail": "critical cascade",
        })
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ALERT


# ===========================================================================
# 5. Event tests (3)
# ===========================================================================

class TestEvents:
    """Tests for event emission."""

    @pytest.mark.asyncio
    async def test_cascade_event_emitted(self):
        """CascadeConfabulationEvent emitted on medium/high risk."""
        emit = MagicMock()
        eps = [
            _make_episode(agent_ids=["B"], ep_id="ep-B", timestamp=100.0),
            _make_episode(agent_ids=["C"], ep_id="ep-C", timestamp=105.0),
            _make_episode(agent_ids=["A"], ep_id="ep-A", timestamp=110.0),
        ]
        svc = _make_service(episodes=eps, emit=emit)
        peer_matches = [
            {"author_id": "B", "author_callsign": "Bravo", "timestamp": 100.0},
            {"author_id": "C", "author_callsign": "Charlie", "timestamp": 105.0},
        ]
        result = await svc.check_cascade_risk(
            "A", "Alpha", "post body", "ch-1", peer_matches=peer_matches,
        )
        assert result is not None
        if result.risk_level in ("medium", "high"):
            emit.assert_called()
            call_args = emit.call_args
            assert "cascade_confabulation_detected" in str(call_args)

    @pytest.mark.asyncio
    async def test_corroboration_event_emitted(self):
        """CorroborationVerifiedEvent emitted when corroborated."""
        emit = MagicMock()
        eps = [
            _make_episode(
                agent_ids=[f"agent-{i}"], ep_id=f"ep-{i}",
                anchors=_rich_anchors(i),
                timestamp=100.0 + i * 120,
            )
            for i in range(3)
        ]
        cfg = SocialVerificationConfig(corroboration_threshold=0.01)
        svc = _make_service(episodes=eps, config=cfg, emit=emit)
        result = await svc.check_corroboration("agent-X", "test claim")
        assert result.is_corroborated
        emit.assert_called_once()
        call_args = emit.call_args
        assert "corroboration_verified" in str(call_args)

    @pytest.mark.asyncio
    async def test_cascade_event_not_emitted_on_low(self):
        """Low risk does NOT emit event."""
        emit = MagicMock()
        eps = [
            _make_episode(agent_ids=["B"], ep_id="ep-B", timestamp=100.0),
            _make_episode(agent_ids=["A"], ep_id="ep-A", timestamp=105.0),
        ]
        svc = _make_service(episodes=eps, emit=emit)
        peer_matches = [
            {"author_id": "B", "author_callsign": "Bravo", "timestamp": 100.0},
        ]
        result = await svc.check_cascade_risk(
            "A", "Alpha", "post body", "ch-1", peer_matches=peer_matches,
        )
        assert result is not None
        assert result.risk_level == "low"
        emit.assert_not_called()
