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
    ProvenanceValidationResult,
    SocialVerificationService,
    build_provenance_report,
    compute_anchor_independence,
    _are_independently_anchored,
    _share_artifact_ancestry,
    _in_anomaly_window,
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

    @pytest.mark.asyncio
    async def test_corroboration_shared_ancestry_reduces_independence(self):
        """Two agents with same source_origin_id should have low independence."""
        # Use _rich_anchors() to ensure episodes pass confidence gate (0.3),
        # then override source_origin_id to test ancestry check
        anchors_1 = dataclasses.replace(
            _rich_anchors(1), source_origin_id="shared-artifact-001",
        )
        anchors_2 = dataclasses.replace(
            _rich_anchors(2), source_origin_id="shared-artifact-001",
        )
        eps = [
            _make_episode(agent_ids=["B"], anchors=anchors_1, timestamp=100.0, ep_id="ep-1"),
            _make_episode(agent_ids=["C"], anchors=anchors_2, timestamp=110.0, ep_id="ep-2"),
        ]
        svc = _make_service(episodes=eps)
        result = await svc.check_corroboration("agent-A", "test claim")
        # Despite different duty_cycles and channels, shared ancestry → not independent
        assert result.anchor_independence_score == 0.0


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

    @pytest.mark.asyncio
    async def test_cascade_shared_ancestry_flags_risk(self):
        """Peer matches sharing artifact ancestry should flag cascade risk."""
        # Use _rich_anchors() base for confidence gate, override origin
        anchors = dataclasses.replace(
            _rich_anchors(1), source_origin_id="corrupted-artifact-001",
        )
        eps = [
            _make_episode(agent_ids=["B"], ep_id="ep-B", anchors=anchors, timestamp=100.0),
            _make_episode(agent_ids=["C"], ep_id="ep-C", anchors=anchors, timestamp=110.0),
            _make_episode(agent_ids=["A"], ep_id="ep-A", anchors=anchors, timestamp=120.0),
        ]
        svc = _make_service(episodes=eps)
        peer_matches = [
            {"author_id": "B", "author_callsign": "Bravo", "timestamp": 100.0},
            {"author_id": "C", "author_callsign": "Charlie", "timestamp": 110.0},
        ]
        result = await svc.check_cascade_risk(
            "A", "Alpha", "post body", "ch-1", peer_matches=peer_matches,
        )
        assert result is not None
        # Shared ancestry → not independent → cascade risk flagged
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
        bas._dismissed = {}
        bas._resolved = {}
        bas._muted = set()
        bas._last_detected = {}

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
        bas._dismissed = {}
        bas._resolved = {}
        bas._muted = set()
        bas._last_detected = {}

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


# ===========================================================================
# 6. Source Provenance tests (AD-662) (11)
# ===========================================================================

class TestSourceProvenance:
    """Tests for AD-662: Corroboration Source Provenance Validation."""

    # --- _share_artifact_ancestry ---

    def test_shared_origin_detected(self):
        """Same source_origin_id = shared ancestry."""
        a = AnchorFrame(source_origin_id="artifact-X", duty_cycle_id="dc-1")
        b = AnchorFrame(source_origin_id="artifact-X", duty_cycle_id="dc-2")
        assert _share_artifact_ancestry(a, b) is True

    def test_different_origin_independent(self):
        """Different source_origin_id = no shared ancestry."""
        a = AnchorFrame(source_origin_id="artifact-X")
        b = AnchorFrame(source_origin_id="artifact-Y")
        assert _share_artifact_ancestry(a, b) is False

    def test_shared_version_alone_not_sufficient(self):
        """Same artifact_version WITHOUT same origin = NOT shared ancestry.
        Version strings may collide across unrelated artifacts."""
        a = AnchorFrame(source_origin_id="artifact-X", artifact_version="v1-abc123")
        b = AnchorFrame(source_origin_id="artifact-Y", artifact_version="v1-abc123")
        assert _share_artifact_ancestry(a, b) is False

    def test_shared_origin_with_version(self):
        """Same origin AND same version = shared ancestry (strongest signal)."""
        a = AnchorFrame(source_origin_id="artifact-X", artifact_version="v1-abc123")
        b = AnchorFrame(source_origin_id="artifact-X", artifact_version="v1-abc123")
        assert _share_artifact_ancestry(a, b) is True

    def test_empty_provenance_no_ancestry(self):
        """Empty provenance fields = no ancestry detected (don't block)."""
        a = AnchorFrame(duty_cycle_id="dc-1")
        b = AnchorFrame(duty_cycle_id="dc-2")
        assert _share_artifact_ancestry(a, b) is False

    def test_none_anchors_no_ancestry(self):
        """None anchors = no ancestry (can't determine)."""
        assert _share_artifact_ancestry(None, None) is False
        assert _share_artifact_ancestry(AnchorFrame(), None) is False

    # --- _in_anomaly_window ---

    def test_anomaly_window_detected(self):
        """Non-empty anomaly_window_id = in anomaly window."""
        a = AnchorFrame(anomaly_window_id="aw-001")
        assert _in_anomaly_window(a) is True

    def test_no_anomaly_window(self):
        """Empty anomaly_window_id = not in anomaly window."""
        a = AnchorFrame()
        assert _in_anomaly_window(a) is False

    # --- Integration: ancestry vetoes spatiotemporal independence ---

    def test_independence_vetoed_by_shared_ancestry(self):
        """Different duty cycles + channels BUT same origin = NOT independent."""
        a = AnchorFrame(
            duty_cycle_id="dc-1", channel_id="ch-1",
            source_origin_id="artifact-X",
        )
        b = AnchorFrame(
            duty_cycle_id="dc-2", channel_id="ch-2",
            source_origin_id="artifact-X",
        )
        # Timestamps within 60s so time_separated doesn't bypass the veto
        ep1 = _make_episode(agent_ids=["A"], anchors=a, timestamp=100.0, ep_id="ep-1")
        ep2 = _make_episode(agent_ids=["B"], anchors=b, timestamp=110.0, ep_id="ep-2")
        score = compute_anchor_independence([ep1, ep2])
        assert score == 0.0

    def test_independence_granted_with_different_ancestry(self):
        """Different duty cycles + different origin = independent."""
        a = AnchorFrame(
            duty_cycle_id="dc-1", channel_id="ch-1",
            source_origin_id="artifact-X",
        )
        b = AnchorFrame(
            duty_cycle_id="dc-2", channel_id="ch-2",
            source_origin_id="artifact-Y",
        )
        ep1 = _make_episode(agent_ids=["A"], anchors=a, timestamp=100.0, ep_id="ep-1")
        ep2 = _make_episode(agent_ids=["B"], anchors=b, timestamp=110.0, ep_id="ep-2")
        score = compute_anchor_independence([ep1, ep2])
        assert score == 1.0

    # --- Anomaly window scoring discount ---

    def test_anomaly_window_discounts_independence_score(self):
        """Episodes in anomaly window get discounted independence contribution."""
        # Two normal episodes that are independently anchored
        ep_normal_1 = _make_episode(
            agent_ids=["A"], ep_id="ep-1",
            anchors=AnchorFrame(duty_cycle_id="dc-1", channel_id="ch-1"),
            timestamp=100.0,
        )
        ep_normal_2 = _make_episode(
            agent_ids=["B"], ep_id="ep-2",
            anchors=AnchorFrame(duty_cycle_id="dc-2", channel_id="ch-2"),
            timestamp=110.0,
        )
        # An anomaly episode that is DEPENDENT (same duty cycle, close timestamp)
        ep_anomaly = _make_episode(
            agent_ids=["C"], ep_id="ep-3",
            anchors=AnchorFrame(
                duty_cycle_id="dc-1", channel_id="ch-1",
                anomaly_window_id="aw-001",
            ),
            timestamp=105.0,
        )

        # Without anomaly episode: 1 pair (ep1-ep2), independent → score = 1.0
        score_clean = compute_anchor_independence([ep_normal_1, ep_normal_2])
        assert score_clean == 1.0

        # With anomaly episode: 3 pairs
        # ep1-ep2: independent, weight=1.0, contributes 1.0
        # ep1-ep3: same duty_cycle, <60s → dependent, weight=0.5, contributes 0
        # ep2-ep3: different duty_cycle → independent, weight=0.5, contributes 0.5
        # total_weight = 1.0 + 0.5 + 0.5 = 2.0
        # independent_weight = 1.0 + 0.0 + 0.5 = 1.5
        # score = 1.5 / 2.0 = 0.75
        score_with_anomaly = compute_anchor_independence([ep_normal_1, ep_normal_2, ep_anomaly])
        assert score_with_anomaly == 0.75


# ===========================================================================
# 7. Provenance Validation tests (AD-665) (16)
# ===========================================================================

class TestProvenanceValidation:
    """Tests for AD-665: graded provenance source validation."""

    def _provenance_episode(
        self,
        idx: int,
        *,
        origin: str = "",
        version: str = "",
        anomaly_window_id: str = "",
        agent_id: str = "",
    ) -> Episode:
        anchors = dataclasses.replace(
            _rich_anchors(idx),
            source_origin_id=origin,
            artifact_version=version,
            anomaly_window_id=anomaly_window_id,
        )
        return _make_episode(
            agent_ids=[agent_id or f"agent-{idx}"],
            anchors=anchors,
            timestamp=100.0 + idx * 10,
            ep_id=f"ep-{idx}",
        )

    def test_provenance_all_independent(self) -> None:
        """Different source origins retain full independence."""
        episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1"),
            self._provenance_episode(2, origin="origin-b", version="v1"),
            self._provenance_episode(3, origin="origin-c", version="v1"),
        ]

        score = compute_anchor_independence(episodes, version_independence_weight=0.7)
        report = build_provenance_report(episodes, version_independence_weight=0.7)

        assert score == 1.0
        assert isinstance(report, ProvenanceValidationResult)
        assert report.total_pairs_checked == 3
        assert report.independent_pairs == 3
        assert report.shared_ancestry_pairs == 0
        assert report.discounted_pairs == 0

    def test_provenance_shared_ancestry_same_version(self) -> None:
        """Same origin and same version retain AD-662 full veto behavior."""
        episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1"),
            self._provenance_episode(2, origin="origin-a", version="v1"),
        ]

        score = compute_anchor_independence(episodes, version_independence_weight=0.7)
        report = build_provenance_report(episodes, version_independence_weight=0.7)

        assert score == 0.0
        assert report.shared_ancestry_pairs == 1
        assert report.discounted_pairs == 0
        assert report.ancestry_details[0]["reason"] == "shared_ancestry"
        assert report.ancestry_details[0]["weight"] == 0.0

    def test_provenance_shared_ancestry_different_version(self) -> None:
        """Same origin and different version receive partial independence."""
        episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1"),
            self._provenance_episode(2, origin="origin-a", version="v2"),
        ]

        score = compute_anchor_independence(episodes, version_independence_weight=0.7)
        report = build_provenance_report(episodes, version_independence_weight=0.7)

        assert score == pytest.approx(0.7)
        assert report.shared_ancestry_pairs == 0
        assert report.discounted_pairs == 1
        assert report.ancestry_details[0]["reason"] == "version_discounted"
        assert report.ancestry_details[0]["weight"] == pytest.approx(0.7)

    def test_provenance_mixed_pairs(self) -> None:
        """Mixed independent, shared, and version-discounted pairs score correctly."""
        episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1"),
            self._provenance_episode(2, origin="origin-b", version="v1"),
            self._provenance_episode(3, origin="origin-b", version="v1"),
            self._provenance_episode(4, origin="origin-a", version="v2"),
        ]

        score = compute_anchor_independence(episodes, version_independence_weight=0.7)
        report = build_provenance_report(episodes, version_independence_weight=0.7)

        assert score == pytest.approx(4.7 / 6.0, abs=1e-3)
        assert report.independent_pairs == 4
        assert report.shared_ancestry_pairs == 1
        assert report.discounted_pairs == 1

    def test_provenance_empty_origin_treated_as_independent(self) -> None:
        """Empty source origin does not trigger shared ancestry."""
        episodes = [
            self._provenance_episode(1, origin="", version="v1"),
            self._provenance_episode(2, origin="origin-b", version="v1"),
        ]

        assert _share_artifact_ancestry(episodes[0].anchors, episodes[1].anchors) is False
        score = compute_anchor_independence(episodes, version_independence_weight=0.7)
        assert score == 1.0

    def test_provenance_anomaly_window_orthogonal_to_version_weight(self) -> None:
        """Anomaly discount affects pair weight while version weight affects credit."""
        episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1", anomaly_window_id="aw-1"),
            self._provenance_episode(2, origin="origin-a", version="v2", anomaly_window_id="aw-1"),
        ]

        score = compute_anchor_independence(
            episodes,
            anomaly_discount=0.5,
            version_independence_weight=0.7,
        )

        assert 0.69 < score < 0.71

    @pytest.mark.asyncio
    async def test_provenance_disabled_config(self) -> None:
        """Disabled provenance validation preserves AD-662 binary veto and omits report."""
        episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1", agent_id="B"),
            self._provenance_episode(2, origin="origin-a", version="v2", agent_id="C"),
        ]
        cfg = SocialVerificationConfig(provenance_validation_enabled=False)
        svc = _make_service(episodes=episodes, config=cfg)

        result = await svc.check_corroboration("A", "test claim")

        assert result.anchor_independence_score == 0.0
        assert result.anchor_summary["provenance_validation"] is None

    @pytest.mark.asyncio
    async def test_provenance_wired_into_corroboration(self) -> None:
        """Corroboration score uses version-weighted anchor independence."""
        episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1", agent_id="B"),
            self._provenance_episode(2, origin="origin-a", version="v2", agent_id="C"),
        ]
        cfg = SocialVerificationConfig(provenance_version_independence_weight=0.7)
        svc = _make_service(episodes=episodes, config=cfg)

        result = await svc.check_corroboration("A", "test claim")

        assert result.anchor_independence_score == pytest.approx(0.7)
        assert result.corroboration_score == pytest.approx(0.565)

    @pytest.mark.asyncio
    async def test_provenance_wired_into_cascade(self) -> None:
        """Cascade risk uses the same graded provenance independence score."""
        episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1", agent_id="B"),
            self._provenance_episode(2, origin="origin-a", version="v2", agent_id="A"),
        ]
        svc = _make_service(episodes=episodes)
        peer_matches = [{"author_id": "B", "author_callsign": "Bravo", "timestamp": 100.0}]

        result = await svc.check_cascade_risk(
            "A", "Alpha", "post body", "ch-1", peer_matches=peer_matches,
        )

        assert result is not None
        assert result.anchor_independence_score == pytest.approx(0.7)
        assert result.risk_level == "none"

    @pytest.mark.asyncio
    async def test_provenance_event_emitted_on_shared_ancestry(self) -> None:
        """Shared ancestry emits provenance validation event with counts."""
        emit = MagicMock()
        episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1", agent_id="B"),
            self._provenance_episode(2, origin="origin-a", version="v1", agent_id="C"),
        ]
        cfg = SocialVerificationConfig(corroboration_threshold=0.99)
        svc = _make_service(episodes=episodes, config=cfg, emit=emit)

        await svc.check_corroboration("A", "test claim")

        emit.assert_called_once()
        event_name, payload = emit.call_args.args
        assert event_name == "corroboration_provenance_validated"
        assert payload["requesting_agent"] == "A"
        assert payload["shared_ancestry_pairs"] == 1
        assert payload["discounted_pairs"] == 0
        assert payload["total_pairs_checked"] == 1

    @pytest.mark.asyncio
    async def test_provenance_no_event_when_all_independent(self) -> None:
        """All-independent provenance produces no provenance event."""
        emit = MagicMock()
        episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1", agent_id="B"),
            self._provenance_episode(2, origin="origin-b", version="v1", agent_id="C"),
        ]
        cfg = SocialVerificationConfig(corroboration_threshold=0.99)
        svc = _make_service(episodes=episodes, config=cfg, emit=emit)

        await svc.check_corroboration("A", "test claim")

        emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_provenance_result_in_anchor_summary(self) -> None:
        """Anchor summary always exposes provenance_validation key."""
        episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1", agent_id="B"),
            self._provenance_episode(2, origin="origin-a", version="v2", agent_id="C"),
        ]
        enabled_svc = _make_service(episodes=episodes)
        disabled_svc = _make_service(
            episodes=episodes,
            config=SocialVerificationConfig(provenance_validation_enabled=False),
        )

        enabled = await enabled_svc.check_corroboration("A", "test claim")
        disabled = await disabled_svc.check_corroboration("A", "test claim")

        report = enabled.anchor_summary["provenance_validation"]
        assert set(report.keys()) == {
            "total_pairs_checked",
            "independent_pairs",
            "shared_ancestry_pairs",
            "discounted_pairs",
            "ancestry_details",
        }
        assert disabled.anchor_summary["provenance_validation"] is None

    def test_provenance_single_episode_returns_trivial(self) -> None:
        """Zero or one episode is trivially independent and has an empty report."""
        episode = self._provenance_episode(1, origin="origin-a", version="v1")

        assert compute_anchor_independence([]) == 1.0
        assert compute_anchor_independence([episode]) == 1.0
        report = build_provenance_report([episode])
        assert report.total_pairs_checked == 0
        assert report.ancestry_details == []

    def test_provenance_details_respect_privacy_boundary(self) -> None:
        """Report details expose only opaque IDs, reason, and weight."""
        episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1"),
            self._provenance_episode(2, origin="origin-a", version="v1"),
        ]

        report = build_provenance_report(episodes, version_independence_weight=0.7)

        assert report.ancestry_details
        assert set(report.ancestry_details[0].keys()) == {
            "episode_a",
            "episode_b",
            "reason",
            "weight",
        }
        assert "participants" not in report.ancestry_details[0]
        assert "source_origin_id" not in report.ancestry_details[0]

    def test_provenance_disabled_reverts_to_ad662(self) -> None:
        """Version weight 0.0 preserves AD-662 binary veto for same-origin pairs."""
        cases = [("v1", "v1"), ("v1", "v2")]

        for version_a, version_b in cases:
            episodes = [
                self._provenance_episode(1, origin="origin-a", version=version_a),
                self._provenance_episode(2, origin="origin-a", version=version_b),
            ]
            score = compute_anchor_independence(episodes, version_independence_weight=0.0)

            assert score == 0.0

    def test_provenance_score_interaction(self) -> None:
        """Graded same-origin-different-version score sits between veto and full independence."""
        binary_episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1"),
            self._provenance_episode(2, origin="origin-a", version="v2"),
        ]
        independent_episodes = [
            self._provenance_episode(1, origin="origin-a", version="v1"),
            self._provenance_episode(2, origin="origin-b", version="v2"),
        ]

        binary_score = compute_anchor_independence(binary_episodes, version_independence_weight=0.0)
        graded_score = compute_anchor_independence(binary_episodes, version_independence_weight=0.7)
        fully_independent_score = compute_anchor_independence(
            independent_episodes,
            version_independence_weight=0.7,
        )

        assert binary_score == 0.0
        assert 0.0 < graded_score < fully_independent_score
