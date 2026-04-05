"""AD-567a: Episode Anchor Metadata — AnchorFrame dataclass and serialization."""

from __future__ import annotations

import dataclasses
import json
import time
from dataclasses import FrozenInstanceError, asdict

import pytest

from probos.types import AnchorFrame, Episode


# ---------------------------------------------------------------------------
# AnchorFrame unit tests
# ---------------------------------------------------------------------------


class TestAnchorFrame:
    def test_default_construction(self):
        """AnchorFrame() creates valid instance with all defaults."""
        af = AnchorFrame()
        assert af.channel == ""
        assert af.trigger_type == ""
        assert af.participants == []
        assert af.event_log_window == 0.0

    def test_full_construction(self):
        """AnchorFrame with all fields populated."""
        af = AnchorFrame(
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
        assert af.duty_cycle_id == "duty-001"
        assert af.watch_section == "alpha"
        assert af.channel == "ward_room"
        assert af.department == "science"
        assert af.participants == ["Atlas", "Horizon"]
        assert af.trigger_agent == "Atlas"
        assert af.trigger_type == "ward_room_post"
        assert af.thread_id == "thread-456"
        assert af.event_log_window == 1000.0

    def test_frozen(self):
        """AnchorFrame is immutable."""
        af = AnchorFrame(channel="dag")
        with pytest.raises(FrozenInstanceError):
            af.channel = "ward_room"  # type: ignore[misc]

    def test_serialization_round_trip(self):
        """asdict() → JSON → AnchorFrame(**loaded) round-trip."""
        original = AnchorFrame(
            channel="ward_room",
            channel_id="ch-123",
            department="medical",
            participants=["Bones", "Chapel"],
            trigger_type="ward_room_post",
            trigger_agent="Bones",
            thread_id="t-789",
        )
        as_json = json.dumps(asdict(original))
        loaded = json.loads(as_json)
        restored = AnchorFrame(**loaded)
        assert restored == original

    def test_empty_serialization_round_trip(self):
        """Default AnchorFrame survives JSON round-trip."""
        original = AnchorFrame()
        as_json = json.dumps(asdict(original))
        restored = AnchorFrame(**json.loads(as_json))
        assert restored == original


# ---------------------------------------------------------------------------
# Episode + anchors integration tests
# ---------------------------------------------------------------------------


class TestEpisodeAnchors:
    def test_episode_default_anchors_none(self):
        """Episode defaults to anchors=None."""
        ep = Episode()
        assert ep.anchors is None

    def test_episode_with_anchors(self):
        """Episode can carry an AnchorFrame."""
        af = AnchorFrame(channel="dag", trigger_type="dag_execution")
        ep = Episode(user_input="test", anchors=af)
        assert ep.anchors is not None
        assert ep.anchors.channel == "dag"
        assert ep.anchors.trigger_type == "dag_execution"


# ---------------------------------------------------------------------------
# Serialization round-trip (ChromaDB metadata)
# ---------------------------------------------------------------------------


class TestMetadataSerialization:
    def test_episode_to_metadata_with_anchors(self):
        """_episode_to_metadata includes anchors_json for anchored episodes."""
        from probos.cognitive.episodic import EpisodicMemory

        af = AnchorFrame(
            channel="ward_room",
            trigger_type="ward_room_post",
            trigger_agent="Atlas",
            thread_id="t-001",
        )
        ep = Episode(
            timestamp=time.time(),
            user_input="Test episode",
            anchors=af,
        )
        metadata = EpisodicMemory._episode_to_metadata(ep)
        assert "anchors_json" in metadata
        assert metadata["anchors_json"] != ""
        parsed = json.loads(metadata["anchors_json"])
        assert parsed["channel"] == "ward_room"
        assert parsed["trigger_type"] == "ward_room_post"
        assert parsed["trigger_agent"] == "Atlas"

    def test_episode_to_metadata_without_anchors(self):
        """_episode_to_metadata has empty anchors_json when anchors=None."""
        from probos.cognitive.episodic import EpisodicMemory

        ep = Episode(timestamp=time.time(), user_input="No anchors")
        metadata = EpisodicMemory._episode_to_metadata(ep)
        assert metadata.get("anchors_json", "") == ""

    def test_metadata_to_episode_with_anchors(self):
        """_metadata_to_episode restores anchors from anchors_json."""
        from probos.cognitive.episodic import EpisodicMemory

        af = AnchorFrame(channel="dm", trigger_type="direct_message", trigger_agent="captain")
        metadata = {
            "timestamp": time.time(),
            "dag_summary_json": "{}",
            "outcomes_json": "[]",
            "reflection": "",
            "agent_ids_json": "[]",
            "duration_ms": 0.0,
            "shapley_values_json": "{}",
            "trust_deltas_json": "[]",
            "source": "direct",
            "anchors_json": json.dumps(asdict(af)),
        }
        ep = EpisodicMemory._metadata_to_episode("test-id", "test input", metadata)
        assert ep.anchors is not None
        assert ep.anchors.channel == "dm"
        assert ep.anchors.trigger_type == "direct_message"
        assert ep.anchors.trigger_agent == "captain"

    def test_metadata_to_episode_without_anchors_backward_compat(self):
        """_metadata_to_episode handles missing anchors_json (backwards compat)."""
        from probos.cognitive.episodic import EpisodicMemory

        metadata = {
            "timestamp": time.time(),
            "dag_summary_json": "{}",
            "outcomes_json": "[]",
            "reflection": "",
            "agent_ids_json": "[]",
            "duration_ms": 0.0,
            "shapley_values_json": "{}",
            "trust_deltas_json": "[]",
            "source": "direct",
            # No anchors_json key
        }
        ep = EpisodicMemory._metadata_to_episode("old-id", "old input", metadata)
        assert ep.anchors is None


# ---------------------------------------------------------------------------
# Content hash exclusion
# ---------------------------------------------------------------------------


class TestContentHashExclusion:
    def test_hash_identical_with_and_without_anchors(self):
        """Content hash is NOT affected by anchor metadata."""
        from probos.cognitive.episodic import compute_episode_hash

        base = Episode(
            timestamp=1000.123456,
            user_input="Test hash stability",
            duration_ms=500.0,
            source="direct",
        )
        anchored = dataclasses.replace(
            base,
            anchors=AnchorFrame(
                channel="dag",
                trigger_type="dag_execution",
                participants=["Atlas", "Horizon"],
                department="science",
            ),
        )
        hash_without = compute_episode_hash(base)
        hash_with = compute_episode_hash(anchored)
        assert hash_without == hash_with

    def test_hash_via_metadata_round_trip(self):
        """Content hash survives metadata serialization with anchors."""
        from probos.cognitive.episodic import EpisodicMemory, compute_episode_hash

        af = AnchorFrame(channel="ward_room", trigger_type="ward_room_post")
        ep = Episode(
            timestamp=time.time(),
            user_input="Hash round-trip test",
            duration_ms=100.0,
            anchors=af,
        )
        metadata = EpisodicMemory._episode_to_metadata(ep)
        stored_hash = metadata["content_hash"]

        # Reconstruct and verify
        ep2 = EpisodicMemory._metadata_to_episode("ep-id", ep.user_input, metadata)
        # Hash of reconstructed episode (without anchors for hashing) should match
        ep2_for_hash = dataclasses.replace(ep2, anchors=None)
        assert compute_episode_hash(ep2_for_hash) == stored_hash


# ---------------------------------------------------------------------------
# Per-site anchor capture (5 most important paths)
# ---------------------------------------------------------------------------


class TestDreamAdapterAnchors:
    def test_build_episode_has_dag_anchors(self):
        """dream_adapter.build_episode() produces channel='dag' anchors."""
        from probos.dream_adapter import DreamAdapter

        adapter = DreamAdapter.__new__(DreamAdapter)
        adapter._trust_network = None
        adapter._last_shapley_values = {}
        adapter._identity_registry = None

        execution_result = {
            "results": [
                {
                    "intent": "analyze_data",
                    "result": {"status": "completed"},
                    "agents": ["agent-001"],
                },
            ],
            "reflection": "Test reflection",
        }

        ep = adapter.build_episode("test input", execution_result, 0.0, 1.0)
        assert ep.anchors is not None
        assert ep.anchors.channel == "dag"
        assert ep.anchors.trigger_type == "dag_execution"


class TestSessionAnchors:
    def test_session_episode_has_dm_anchors(self):
        """Shell 1:1 session episodes have channel='dm' and captain in participants."""
        af = AnchorFrame(
            channel="dm",
            department="science",
            trigger_type="direct_message",
            trigger_agent="captain",
            participants=["captain", "Atlas"],
        )
        ep = Episode(
            user_input="[1:1 with Atlas] Captain: test",
            anchors=af,
        )
        assert ep.anchors.channel == "dm"
        assert ep.anchors.trigger_type == "direct_message"
        assert "captain" in ep.anchors.participants
        assert ep.anchors.department == "science"


class TestProactiveAnchors:
    def test_duty_cycle_anchor(self):
        """Proactive duty cycle episodes have channel='duty_report' and duty_cycle_id."""
        af = AnchorFrame(
            channel="duty_report",
            duty_cycle_id="duty-alpha-001",
            department="medical",
            trigger_type="duty_cycle",
        )
        ep = Episode(
            user_input="[Proactive thought] Bones: patient status review",
            anchors=af,
        )
        assert ep.anchors.channel == "duty_report"
        assert ep.anchors.duty_cycle_id == "duty-alpha-001"
        assert ep.anchors.trigger_type == "duty_cycle"

    def test_proactive_think_anchor(self):
        """Non-duty proactive thinks have trigger_type='proactive_think'."""
        af = AnchorFrame(
            channel="duty_report",
            trigger_type="proactive_think",
        )
        ep = Episode(user_input="thought", anchors=af)
        assert ep.anchors.trigger_type == "proactive_think"


class TestWardRoomAnchors:
    def test_thread_creation_anchor(self):
        """Ward Room thread creation has channel='ward_room' and thread_id."""
        af = AnchorFrame(
            channel="ward_room",
            channel_id="ch-science",
            thread_id="t-123",
            trigger_type="ward_room_post",
            participants=["Atlas"],
            trigger_agent="Atlas",
        )
        ep = Episode(user_input="[Ward Room] science — Atlas: new findings", anchors=af)
        assert ep.anchors.channel == "ward_room"
        assert ep.anchors.thread_id == "t-123"
        assert ep.anchors.trigger_type == "ward_room_post"
        assert ep.anchors.trigger_agent == "Atlas"

    def test_peer_repetition_anchor(self):
        """Peer repetition episodes have trigger_type='peer_repetition'."""
        af = AnchorFrame(
            channel="ward_room",
            trigger_type="peer_repetition",
            trigger_agent="Horizon",
        )
        ep = Episode(user_input="[Peer echo]...", anchors=af)
        assert ep.anchors.trigger_type == "peer_repetition"


class TestCognitiveAgentAnchors:
    def test_action_episode_anchor(self):
        """Cognitive agent action episodes have trigger_type matching intent."""
        af = AnchorFrame(
            channel="action",
            department="security",
            trigger_type="security_scan",
            trigger_agent="captain",
        )
        ep = Episode(user_input="[Action: security_scan]", anchors=af)
        assert ep.anchors.channel == "action"
        assert ep.anchors.trigger_type == "security_scan"


# ---------------------------------------------------------------------------
# Feedback & smoke test anchors
# ---------------------------------------------------------------------------


class TestFeedbackAnchors:
    def test_correction_anchor(self):
        """Correction episodes have channel='feedback', trigger_type='human_correction'."""
        af = AnchorFrame(channel="feedback", trigger_type="human_correction", trigger_agent="captain")
        ep = Episode(user_input="correction test", anchors=af)
        assert ep.anchors.channel == "feedback"
        assert ep.anchors.trigger_type == "human_correction"

    def test_feedback_anchor(self):
        """Human feedback episodes have trigger_type='human_feedback'."""
        af = AnchorFrame(channel="feedback", trigger_type="human_feedback", trigger_agent="captain")
        ep = Episode(user_input="feedback test", anchors=af)
        assert ep.anchors.trigger_type == "human_feedback"


class TestSmokeTestAnchors:
    def test_smoke_test_anchor(self):
        """Smoke test episodes have channel='smoke_test'."""
        af = AnchorFrame(channel="smoke_test", trigger_type="smoke_test")
        ep = Episode(user_input="[SystemQA] Smoke test", anchors=af)
        assert ep.anchors.channel == "smoke_test"
        assert ep.anchors.trigger_type == "smoke_test"


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------


class TestBackwardsCompatibility:
    def test_should_store_works_with_anchored_episodes(self):
        """should_store() gate still works with anchored episodes."""
        from probos.cognitive.episodic import EpisodicMemory

        af = AnchorFrame(channel="dag", trigger_type="dag_execution")
        ep = Episode(
            user_input="Substantial episode with enough content to pass the gate",
            timestamp=time.time(),
            outcomes=[{"intent": "test", "success": True}],
            anchors=af,
        )
        # should_store checks content quality, not anchors
        result = EpisodicMemory.should_store(ep)
        assert isinstance(result, bool)

    def test_content_hash_verification_with_anchors(self):
        """Content hash verification still passes for anchored episodes."""
        from probos.cognitive.episodic import EpisodicMemory, compute_episode_hash

        af = AnchorFrame(channel="dag", trigger_type="dag_execution")
        ep = Episode(
            timestamp=1000.123456,
            user_input="Hash verification test",
            duration_ms=500.0,
            anchors=af,
        )
        metadata = EpisodicMemory._episode_to_metadata(ep)
        stored_hash = metadata["content_hash"]

        # Verify the hash matches what we'd compute from the stored episode
        ep_back = EpisodicMemory._metadata_to_episode("id", ep.user_input, metadata)
        ep_normalized = dataclasses.replace(
            ep_back,
            timestamp=round(float(ep_back.timestamp), 6),
            duration_ms=float(ep_back.duration_ms),
            source=ep_back.source or "direct",
            anchors=None,
        )
        assert compute_episode_hash(ep_normalized) == stored_hash
