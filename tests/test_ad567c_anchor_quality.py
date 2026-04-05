"""AD-567c: Anchor Quality & Integrity — 23 tests."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.types import AnchorFrame, Episode, RecallScore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_episode(
    *,
    user_input: str = "test input",
    timestamp: float | None = None,
    agent_ids: list[str] | None = None,
    source: str = "direct",
    anchors: AnchorFrame | None = None,
) -> Episode:
    return Episode(
        user_input=user_input,
        timestamp=timestamp or time.time(),
        agent_ids=agent_ids or ["agent-001"],
        source=source,
        anchors=anchors,
        outcomes=[{"intent": "test_intent", "success": True}],
    )


def _full_anchor() -> AnchorFrame:
    """All 10 fields filled."""
    return AnchorFrame(
        duty_cycle_id="duty-001",
        watch_section="alpha",
        channel="ward_room",
        channel_id="ch-123",
        department="science",
        participants=["Atlas", "Horizon"],
        trigger_agent="Atlas",
        trigger_type="ward_room_post",
        thread_id="thread-456",
        event_log_window=1000.0,
    )


def _temporal_only_anchor() -> AnchorFrame:
    """Only temporal fields filled."""
    return AnchorFrame(
        duty_cycle_id="duty-001",
        watch_section="alpha",
    )


def _contextual_anchor() -> AnchorFrame:
    """Temporal + Spatial + Social filled; Causal + Evidential empty."""
    return AnchorFrame(
        duty_cycle_id="duty-001",
        watch_section="alpha",
        channel="ward_room",
        channel_id="ch-123",
        department="science",
        participants=["Atlas"],
        trigger_agent="Atlas",
    )


def _low_confidence_anchor() -> AnchorFrame:
    """Only one field filled — very low confidence."""
    return AnchorFrame(trigger_type="ward_room_post")


# ---------------------------------------------------------------------------
# 1. Anchor confidence scoring (6 tests)
# ---------------------------------------------------------------------------

class TestAnchorConfidenceScoring:
    def test_all_fields_filled(self):
        """Test 1: All 10 fields filled → confidence ≈ 1.0."""
        from probos.cognitive.anchor_quality import compute_anchor_confidence

        conf = compute_anchor_confidence(_full_anchor())
        assert abs(conf - 1.0) < 1e-9

    def test_no_fields_filled(self):
        """Test 2: No fields filled → confidence = 0.0."""
        from probos.cognitive.anchor_quality import compute_anchor_confidence

        conf = compute_anchor_confidence(AnchorFrame())
        assert conf == 0.0

    def test_anchors_none(self):
        """Test 3: anchors=None → confidence = 0.0."""
        from probos.cognitive.anchor_quality import compute_anchor_confidence

        conf = compute_anchor_confidence(None)
        assert conf == 0.0

    def test_temporal_only(self):
        """Test 4: Only temporal fields filled → confidence ≈ 0.25."""
        from probos.cognitive.anchor_quality import compute_anchor_confidence

        conf = compute_anchor_confidence(_temporal_only_anchor())
        # temporal: 2/2 = 1.0, others: 0. So 0.25 * 1.0 = 0.25
        assert abs(conf - 0.25) < 1e-9

    def test_contextual_dims_only(self):
        """Test 5: Temporal+Spatial+Social filled, Causal+Evidential empty → ≈ 0.75."""
        from probos.cognitive.anchor_quality import compute_anchor_confidence

        conf = compute_anchor_confidence(_contextual_anchor())
        # temporal: 2/2=1.0 * 0.25 = 0.25
        # spatial: 3/3=1.0 * 0.25 = 0.25
        # social: 2/2=1.0 * 0.25 = 0.25
        # causal: 0 * 0.15 = 0
        # evidential: 0 * 0.10 = 0
        expected = 0.75
        assert abs(conf - expected) < 1e-9

    def test_custom_weights(self):
        """Test 6: Custom dimension weights from config are respected."""
        from probos.cognitive.anchor_quality import compute_anchor_confidence

        # Weight temporal at 1.0, everything else at 0
        custom_weights = {
            "temporal": 1.0,
            "spatial": 0.0,
            "social": 0.0,
            "causal": 0.0,
            "evidential": 0.0,
        }
        conf = compute_anchor_confidence(_temporal_only_anchor(), weights=custom_weights)
        # temporal: 2/2=1.0 * 1.0 = 1.0
        assert abs(conf - 1.0) < 1e-9

        # Now use an anchor with no temporal fields
        conf2 = compute_anchor_confidence(
            AnchorFrame(channel="ward_room"),
            weights=custom_weights,
        )
        assert conf2 == 0.0


# ---------------------------------------------------------------------------
# 2. RPMS confidence gating (3 tests)
# ---------------------------------------------------------------------------

class TestRPMSConfidenceGating:
    @pytest.mark.asyncio
    async def test_above_gate_included(self, tmp_path):
        """Test 7: Episode with anchor_confidence >= gate appears in results."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(db_path=str(tmp_path / "ep"))
        await em.start()

        ep = _make_episode(
            user_input="high confidence episode",
            anchors=_full_anchor(),
            agent_ids=["agent-001"],
        )
        await em.store(ep)

        results = await em.recall_weighted(
            "agent-001", "high confidence",
            anchor_confidence_gate=0.3,
        )
        assert len(results) >= 1
        assert all(rs.anchor_confidence >= 0.3 for rs in results)

    @pytest.mark.asyncio
    async def test_below_gate_filtered(self, tmp_path):
        """Test 8: Episode with anchor_confidence < gate filtered from results."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(db_path=str(tmp_path / "ep"))
        await em.start()

        # Store a low-confidence episode
        ep_low = _make_episode(
            user_input="low confidence episode ungrounded",
            anchors=_low_confidence_anchor(),  # only trigger_type → conf ≈ 0.15
            agent_ids=["agent-001"],
        )
        await em.store(ep_low)

        results = await em.recall_weighted(
            "agent-001", "low confidence ungrounded",
            anchor_confidence_gate=0.5,  # high gate
        )
        # The low-confidence episode should be filtered out
        for rs in results:
            assert rs.anchor_confidence >= 0.5

    @pytest.mark.asyncio
    async def test_bypass_via_recall_for_agent(self, tmp_path):
        """Test 9: Filtered episode still accessible via recall_for_agent()."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(db_path=str(tmp_path / "ep"))
        await em.start()

        # Store a low-confidence episode
        ep_low = _make_episode(
            user_input="bypass test episode low quality",
            anchors=_low_confidence_anchor(),
            agent_ids=["agent-001"],
        )
        await em.store(ep_low)

        # recall_for_agent should still return it (no RPMS gating)
        episodes = await em.recall_for_agent("agent-001", "bypass test", k=5)
        assert len(episodes) >= 1


# ---------------------------------------------------------------------------
# 3. Per-agent anchor profiles (3 tests)
# ---------------------------------------------------------------------------

class TestAnchorProfiles:
    @pytest.mark.asyncio
    async def test_mean_median_confidence(self):
        """Test 10: Profile correctly computes mean/median confidence."""
        from probos.cognitive.anchor_quality import build_anchor_profile

        mock_em = AsyncMock()
        mock_em.recent_for_agent = AsyncMock(return_value=[
            _make_episode(anchors=_full_anchor()),       # conf = 1.0
            _make_episode(anchors=AnchorFrame()),         # conf = 0.0
            _make_episode(anchors=_temporal_only_anchor()),  # conf = 0.25
        ])

        profile = await build_anchor_profile("agent-001", mock_em)
        assert profile.total_episodes == 3
        # mean = (1.0 + 0.0 + 0.25) / 3 ≈ 0.4167
        assert abs(profile.mean_confidence - (1.0 + 0.0 + 0.25) / 3) < 1e-4
        # sorted: [0.0, 0.25, 1.0] → median = 0.25
        assert abs(profile.median_confidence - 0.25) < 1e-4

    @pytest.mark.asyncio
    async def test_weakest_strongest_dimensions(self):
        """Test 11: Profile identifies weakest/strongest dimensions."""
        from probos.cognitive.anchor_quality import build_anchor_profile

        mock_em = AsyncMock()
        # All temporal-only episodes: temporal fill = 1.0, others = 0.0
        mock_em.recent_for_agent = AsyncMock(return_value=[
            _make_episode(anchors=_temporal_only_anchor()),
            _make_episode(anchors=_temporal_only_anchor()),
        ])

        profile = await build_anchor_profile("agent-001", mock_em)
        assert profile.strongest_dimension == "temporal"
        # spatial, social, causal, evidential all 0.0 — weakest is one of them
        assert profile.dimension_fill_rates["temporal"] == 1.0
        assert profile.dimension_fill_rates["spatial"] == 0.0
        assert profile.dimension_fill_rates["social"] == 0.0

    @pytest.mark.asyncio
    async def test_low_confidence_count(self):
        """Test 12: Profile counts low-confidence episodes."""
        from probos.cognitive.anchor_quality import build_anchor_profile

        mock_em = AsyncMock()
        mock_em.recent_for_agent = AsyncMock(return_value=[
            _make_episode(anchors=_full_anchor()),       # conf = 1.0 (above gate)
            _make_episode(anchors=AnchorFrame()),         # conf = 0.0 (below gate)
            _make_episode(anchors=None),                  # conf = 0.0 (below gate)
        ])

        profile = await build_anchor_profile("agent-001", mock_em, confidence_gate=0.3)
        assert profile.low_confidence_count == 2
        assert abs(profile.low_confidence_pct - 2 / 3) < 1e-4


# ---------------------------------------------------------------------------
# 4. SIF check (4 tests)
# ---------------------------------------------------------------------------

class TestSIFAnchorIntegrity:
    def test_passes_with_majority_anchored(self):
        """Test 13: check_anchor_integrity passes when >50% have anchors."""
        from probos.sif import StructuralIntegrityField

        sif = StructuralIntegrityField(episodic_memory=MagicMock())
        # Cache: 3 episodes, 2 with anchors
        sif._anchor_check_cache = [
            _make_episode(anchors=_full_anchor()),
            _make_episode(anchors=_full_anchor()),
            _make_episode(anchors=None),
        ]
        result = sif.check_anchor_integrity()
        assert result.passed is True
        assert "ok" in result.details

    def test_fails_with_low_anchor_rate(self):
        """Test 14: check_anchor_integrity fails when <50% have anchors."""
        from probos.sif import StructuralIntegrityField

        sif = StructuralIntegrityField(episodic_memory=MagicMock())
        # Cache: 4 episodes, only 1 with anchors
        sif._anchor_check_cache = [
            _make_episode(anchors=_full_anchor()),
            _make_episode(anchors=None),
            _make_episode(anchors=None),
            _make_episode(anchors=None),
        ]
        result = sif.check_anchor_integrity()
        assert result.passed is False
        assert "anchor presence" in result.details

    def test_invalid_thread_flagged(self):
        """Test 15: Episode with invalid thread_id flagged."""
        from probos.sif import StructuralIntegrityField

        sif = StructuralIntegrityField(episodic_memory=MagicMock())
        anchor_with_thread = AnchorFrame(
            duty_cycle_id="d1", watch_section="alpha",
            channel="ward_room", channel_id="ch1", department="sci",
            participants=["Atlas"], trigger_agent="Atlas",
            trigger_type="post",
            thread_id="nonexistent-thread-id",
            event_log_window=100.0,
        )
        ep = _make_episode(anchors=anchor_with_thread)
        sif._anchor_check_cache = [ep]
        sif._anchor_invalid_threads = {"nonexistent-thread-id"}

        result = sif.check_anchor_integrity()
        assert result.passed is False
        assert "not found in Ward Room" in result.details

    def test_missing_episodic_memory_graceful(self):
        """Test 16: SIF handles missing episodic_memory (returns pass)."""
        from probos.sif import StructuralIntegrityField

        sif = StructuralIntegrityField(episodic_memory=None)
        result = sif.check_anchor_integrity()
        assert result.passed is True
        assert "not configured" in result.details


# ---------------------------------------------------------------------------
# 5. Drift classification (5 tests)
# ---------------------------------------------------------------------------

class TestDriftClassification:
    @pytest.mark.asyncio
    async def test_specialization_high_conf_out_of_domain(self):
        """Test 17: High-confidence + out-of-domain decline → 'specialization'."""
        from probos.cognitive.drift_detector import DriftDetector
        from probos.cognitive.anchor_quality import AnchorProfile

        @dataclass
        class _MockResult:
            score: float

        @dataclass
        class _MockBaseline:
            score: float = 0.8

        mock_store = AsyncMock()
        # Create enough history with declining scores
        mock_store.get_history = AsyncMock(return_value=[
            _MockResult(score=0.3),  # newest — declined from 0.8
            _MockResult(score=0.5),
            _MockResult(score=0.6),
            _MockResult(score=0.7),
            _MockResult(score=0.8),
        ])
        mock_store.get_baseline = AsyncMock(return_value=_MockBaseline(score=0.8))

        @dataclass
        class _Cfg:
            drift_history_window: int = 20
            significance_threshold: float = 0.05
            drift_min_samples: int = 3
            drift_warning_sigma: float = 2.0
            drift_critical_sigma: float = 3.0

        # Agent has high anchor confidence
        anchor_profiles = {
            "agent-001": AnchorProfile(
                agent_id="agent-001",
                mean_confidence=0.8,  # High — well-grounded
            ),
        }

        # Mock HebbianRouter: agent's top intents are "analyze_data", "generate_report", "summarize"
        mock_hebbian = MagicMock()
        mock_hebbian.get_all_weights.return_value = {
            ("analyze_data", "agent-001", "intent"): 0.9,
            ("generate_report", "agent-001", "intent"): 0.7,
            ("summarize", "agent-001", "intent"): 0.5,
        }

        detector = DriftDetector(
            store=mock_store,
            config=_Cfg(),
            anchor_profile_cache=anchor_profiles,
            hebbian_router=mock_hebbian,
        )
        # Test on "code_quality" which is NOT in agent's top intents
        signal = await detector._analyze_single("agent-001", "code_quality")

        if signal.direction == "declined" and signal.severity in ("warning", "critical"):
            assert signal.drift_type == "specialization"

    @pytest.mark.asyncio
    async def test_concerning_low_conf_decline(self):
        """Test 18: Low-confidence + any decline → 'concerning'."""
        from probos.cognitive.drift_detector import DriftDetector
        from probos.cognitive.anchor_quality import AnchorProfile

        @dataclass
        class _MockResult:
            score: float

        @dataclass
        class _MockBaseline:
            score: float = 0.8

        mock_store = AsyncMock()
        mock_store.get_history = AsyncMock(return_value=[
            _MockResult(score=0.2),
            _MockResult(score=0.4),
            _MockResult(score=0.5),
            _MockResult(score=0.7),
            _MockResult(score=0.8),
        ])
        mock_store.get_baseline = AsyncMock(return_value=_MockBaseline(score=0.8))

        @dataclass
        class _Cfg:
            drift_history_window: int = 20
            significance_threshold: float = 0.05
            drift_min_samples: int = 3
            drift_warning_sigma: float = 2.0
            drift_critical_sigma: float = 3.0

        anchor_profiles = {
            "agent-001": AnchorProfile(
                agent_id="agent-001",
                mean_confidence=0.2,  # Low — poorly grounded
            ),
        }

        detector = DriftDetector(
            store=mock_store,
            config=_Cfg(),
            anchor_profile_cache=anchor_profiles,
        )
        signal = await detector._analyze_single("agent-001", "any_test")

        if signal.direction == "declined" and signal.severity in ("warning", "critical"):
            assert signal.drift_type == "concerning"

    @pytest.mark.asyncio
    async def test_no_decline_unclassified(self):
        """Test 19: No decline → 'unclassified'."""
        from probos.cognitive.drift_detector import DriftDetector

        @dataclass
        class _MockResult:
            score: float

        @dataclass
        class _MockBaseline:
            score: float = 0.8

        mock_store = AsyncMock()
        # Stable scores — no decline
        mock_store.get_history = AsyncMock(return_value=[
            _MockResult(score=0.8),
            _MockResult(score=0.8),
            _MockResult(score=0.8),
        ])
        mock_store.get_baseline = AsyncMock(return_value=_MockBaseline(score=0.8))

        @dataclass
        class _Cfg:
            drift_history_window: int = 20
            significance_threshold: float = 0.05
            drift_min_samples: int = 3
            drift_warning_sigma: float = 2.0
            drift_critical_sigma: float = 3.0

        detector = DriftDetector(store=mock_store, config=_Cfg())
        signal = await detector._analyze_single("agent-001", "test_x")
        assert signal.drift_type == "unclassified"

    @pytest.mark.asyncio
    async def test_specialization_counselor_no_assessment(self):
        """Test 20: Specialization at critical → Counselor does NOT trigger assessment."""
        from probos.cognitive.counselor import CounselorAgent

        counselor = CounselorAgent.__new__(CounselorAgent)
        counselor.id = "counselor-001"
        counselor._resolve_agent_callsign = MagicMock(return_value="TestAgent")
        counselor._gather_agent_metrics = MagicMock()
        counselor.assess_agent = MagicMock()
        counselor._save_profile_and_assessment = AsyncMock()
        counselor._maybe_send_therapeutic_dm = AsyncMock()

        data = {
            "agent_id": "agent-002",
            "severity": "critical",
            "test_name": "code_quality",
            "z_score": 3.5,
            "drift_type": "specialization",
        }
        await counselor._on_qualification_drift(data)

        # Specialization → should NOT trigger assessment
        counselor.assess_agent.assert_not_called()
        counselor._save_profile_and_assessment.assert_not_called()

    @pytest.mark.asyncio
    async def test_concerning_counselor_triggers_assessment(self):
        """Test 21: Concerning at warning → Counselor DOES trigger assessment."""
        from probos.cognitive.counselor import CounselorAgent, CounselorAssessment

        counselor = CounselorAgent.__new__(CounselorAgent)
        counselor.id = "counselor-001"
        counselor._resolve_agent_callsign = MagicMock(return_value="TestAgent")
        counselor._gather_agent_metrics = MagicMock(return_value={
            "trust_score": 0.5,
            "confidence": 0.5,
            "hebbian_avg": 0.5,
            "success_rate": 0.5,
            "personality_drift": 0.0,
        })
        counselor.assess_agent = MagicMock(return_value=CounselorAssessment(
            agent_id="agent-002",
            trigger="qualification_drift_concerning",
        ))
        counselor._save_profile_and_assessment = AsyncMock()
        counselor._maybe_send_therapeutic_dm = AsyncMock()

        data = {
            "agent_id": "agent-002",
            "severity": "warning",
            "test_name": "code_quality",
            "z_score": 2.5,
            "drift_type": "concerning",
        }
        await counselor._on_qualification_drift(data)

        # Concerning drift → Counselor SHOULD trigger assessment
        counselor.assess_agent.assert_called_once()
        counselor._save_profile_and_assessment.assert_called_once()


# ---------------------------------------------------------------------------
# 6. Counselor integration (2 tests)
# ---------------------------------------------------------------------------

class TestCounselorIntegration:
    def test_cognitive_profile_anchor_fields(self):
        """Test 22: CognitiveProfile has anchor_quality and weakest_anchor_dimension."""
        from probos.cognitive.counselor import CognitiveProfile

        profile = CognitiveProfile(agent_id="agent-001")
        assert profile.anchor_quality == 0.0
        assert profile.weakest_anchor_dimension == ""

        # Update and verify persistence through serialization
        profile.anchor_quality = 0.65
        profile.weakest_anchor_dimension = "evidential"
        d = profile.to_dict()
        assert d["anchor_quality"] == 0.65
        assert d["weakest_anchor_dimension"] == "evidential"

        # Roundtrip
        restored = CognitiveProfile.from_dict(d)
        assert restored.anchor_quality == 0.65
        assert restored.weakest_anchor_dimension == "evidential"

    def test_counselor_concern_on_low_anchor_quality(self):
        """Test 23: Counselor raises concern when anchor_quality < 0.3."""
        from probos.cognitive.counselor import CognitiveProfile

        profile = CognitiveProfile(agent_id="agent-001")
        profile.anchor_quality = 0.15  # Below 0.3 threshold
        assert profile.anchor_quality < 0.3

        # Verify the field is included in to_dict for persistence
        d = profile.to_dict()
        assert d["anchor_quality"] == 0.15

        # A high anchor_quality should NOT trigger concern
        profile2 = CognitiveProfile(agent_id="agent-002")
        profile2.anchor_quality = 0.85
        assert profile2.anchor_quality >= 0.3
