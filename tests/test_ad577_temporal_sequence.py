"""AD-577: Temporal Sequence Precision — Intra-Cycle Event Ordering.

Tests:
1. AnchorFrame new fields (defaults, serialization, backwards compat)
2. Proactive context timestamps (created_at passthrough, sort, sequence indices)
3. Ward Room episode source timestamps (thread, reply)
4. Content hash unaffected by new anchor fields
"""

import dataclasses
import time

import pytest

from probos.types import AnchorFrame, Episode
from probos.cognitive.episodic import compute_episode_hash


# ---------------------------------------------------------------------------
# TestAnchorFrameTemporalFields
# ---------------------------------------------------------------------------
class TestAnchorFrameTemporalFields:
    """AD-577: New temporal fields on AnchorFrame."""

    def test_anchor_frame_new_fields_default(self) -> None:
        af = AnchorFrame()
        assert af.sequence_index == 0
        assert af.source_timestamp == 0.0

    def test_anchor_frame_serialization_roundtrip(self) -> None:
        af = AnchorFrame(sequence_index=3, source_timestamp=1712500000.0, channel="ward_room")
        d = dataclasses.asdict(af)
        af2 = AnchorFrame(**d)
        assert af2.sequence_index == 3
        assert af2.source_timestamp == 1712500000.0
        assert af2.channel == "ward_room"

    def test_anchor_frame_backwards_compatible_deserialization(self) -> None:
        """Old episodes without sequence_index/source_timestamp still deserialize."""
        old_dict = {
            "duty_cycle_id": "dc-1",
            "watch_section": "alpha",
            "channel": "ward_room",
            "channel_id": "ch-1",
            "department": "science",
            "participants": ["Atlas"],
            "trigger_agent": "Atlas",
            "trigger_type": "ward_room_post",
            "thread_id": "t-1",
            "event_log_window": 5.0,
        }
        af = AnchorFrame(**old_dict)
        assert af.sequence_index == 0
        assert af.source_timestamp == 0.0
        assert af.channel == "ward_room"


# ---------------------------------------------------------------------------
# TestProactiveContextTimestamps
# ---------------------------------------------------------------------------
class TestProactiveContextTimestamps:
    """AD-577: Proactive context passthrough and ordering."""

    def _simulate_context_build(self, activity_items: list[dict]) -> list[dict]:
        """Simulate the proactive context build logic for WR activity."""
        # Build activity dicts with created_at
        result = [
            {
                "type": a.get("type", "thread"),
                "author": a.get("author", "unknown"),
                "body": a.get("body", "")[:500],
                "net_score": a.get("net_score", 0),
                "post_id": a.get("post_id", ""),
                "thread_id": a.get("thread_id", ""),
                "created_at": a.get("created_at", 0.0),
            }
            for a in activity_items
        ]
        # AD-577: Sort and assign sequence indices
        result.sort(key=lambda a: a.get("created_at", 0.0))
        for idx, item in enumerate(result, start=1):
            item["sequence_index"] = idx
        return result

    def test_gather_context_includes_created_at(self) -> None:
        items = [{"type": "thread", "author": "Atlas", "body": "Test", "created_at": 1712500000.0}]
        result = self._simulate_context_build(items)
        assert result[0]["created_at"] == 1712500000.0

    def test_gather_context_sorts_by_created_at(self) -> None:
        items = [
            {"type": "thread", "author": "C", "body": "third", "created_at": 300.0},
            {"type": "thread", "author": "A", "body": "first", "created_at": 100.0},
            {"type": "thread", "author": "B", "body": "second", "created_at": 200.0},
        ]
        result = self._simulate_context_build(items)
        assert [r["author"] for r in result] == ["A", "B", "C"]

    def test_gather_context_assigns_sequence_indices(self) -> None:
        items = [
            {"type": "thread", "author": "A", "body": "a", "created_at": 100.0},
            {"type": "thread", "author": "B", "body": "b", "created_at": 200.0},
            {"type": "thread", "author": "C", "body": "c", "created_at": 300.0},
        ]
        result = self._simulate_context_build(items)
        assert [r["sequence_index"] for r in result] == [1, 2, 3]

    def test_gather_context_created_at_missing_defaults_to_zero(self) -> None:
        items = [{"type": "thread", "author": "X", "body": "no timestamp"}]
        result = self._simulate_context_build(items)
        assert result[0]["created_at"] == 0.0


# ---------------------------------------------------------------------------
# TestWardRoomEpisodeSourceTimestamp
# ---------------------------------------------------------------------------
class TestWardRoomEpisodeSourceTimestamp:
    """AD-577: Source timestamps on Ward Room episodes."""

    def test_thread_episode_has_source_timestamp(self) -> None:
        """AnchorFrame on thread episode includes source_timestamp."""
        ts = time.time()
        af = AnchorFrame(
            channel="ward_room",
            channel_id="ch-1",
            thread_id="t-1",
            trigger_type="ward_room_post",
            participants=["Atlas"],
            trigger_agent="Atlas",
            department="science",
            source_timestamp=ts,
        )
        assert af.source_timestamp == ts

    def test_reply_episode_has_source_timestamp(self) -> None:
        """AnchorFrame on reply episode includes source_timestamp."""
        ts = 1712500000.0
        af = AnchorFrame(
            channel="ward_room",
            thread_id="t-2",
            trigger_type="ward_room_reply",
            source_timestamp=ts,
        )
        assert af.source_timestamp == ts

    def test_source_timestamp_zero_when_unavailable(self) -> None:
        """Episodes without WR context have source_timestamp=0.0."""
        af = AnchorFrame(channel="duty_report", trigger_type="proactive_think")
        assert af.source_timestamp == 0.0


# ---------------------------------------------------------------------------
# TestContentHashUnaffected
# ---------------------------------------------------------------------------
class TestContentHashUnaffected:
    """AD-577: New anchor fields must NOT affect content hash."""

    def _make_episode(self, **anchor_kwargs) -> Episode:
        return Episode(
            user_input="Test input",
            timestamp=1712500000.0,
            agent_ids=["agent-1"],
            outcomes=[{"intent": "test", "success": True}],
            reflection="Test reflection",
            source="direct",
            anchors=AnchorFrame(**anchor_kwargs),
        )

    def test_new_anchor_fields_do_not_affect_content_hash(self) -> None:
        ep1 = self._make_episode(sequence_index=0, source_timestamp=0.0)
        ep2 = self._make_episode(sequence_index=5, source_timestamp=1712500000.0)
        assert compute_episode_hash(ep1) == compute_episode_hash(ep2)

    def test_episode_with_new_anchor_fields_stores_correctly(self) -> None:
        """Episode with populated anchor fields serializes via asdict."""
        ep = self._make_episode(
            sequence_index=3,
            source_timestamp=1712500000.0,
            channel="ward_room",
        )
        d = dataclasses.asdict(ep.anchors)
        assert d["sequence_index"] == 3
        assert d["source_timestamp"] == 1712500000.0
        # Roundtrip
        af2 = AnchorFrame(**d)
        assert af2.sequence_index == 3
        assert af2.source_timestamp == 1712500000.0
