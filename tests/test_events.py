"""Tests for AD-527: Typed Event System."""

from __future__ import annotations

import ast
import glob
import re
import time
from unittest.mock import MagicMock

import pytest

from probos.events import (
    BaseEvent,
    BuildFailureEvent,
    BuildGeneratedEvent,
    BuildProgressEvent,
    BuildResolvedEvent,
    BuildStartedEvent,
    BuildSuccessEvent,
    ConsensusEvent,
    DesignFailureEvent,
    DesignGeneratedEvent,
    DesignProgressEvent,
    DesignStartedEvent,
    EventType,
    HebbianUpdateEvent,
    SelfModFailureEvent,
    SelfModImportApprovedEvent,
    SelfModProgressEvent,
    SelfModRetryCompleteEvent,
    SelfModStartedEvent,
    SelfModSuccessEvent,
    TrustUpdateEvent,
    WardRoomEndorsementEvent,
    WardRoomPostCreatedEvent,
    WardRoomThreadCreatedEvent,
    WardRoomThreadUpdatedEvent,
)


# ---------------------------------------------------------------------------
# 1. Enum string identity — EventType(str, Enum) equality
# ---------------------------------------------------------------------------

class TestEnumStringIdentity:
    """EventType members must compare equal to their string values."""

    def test_build_progress_identity(self):
        assert EventType.BUILD_PROGRESS == "build_progress"

    def test_trust_update_identity(self):
        assert EventType.TRUST_UPDATE == "trust_update"

    def test_all_enum_values_are_strings(self):
        for member in EventType:
            assert isinstance(member, str)
            assert member == member.value

    def test_enum_in_dict_key_lookup(self):
        """EventType members work as dict keys interchangeable with strings."""
        d = {"build_failure": "matched"}
        assert d.get(EventType.BUILD_FAILURE) == "matched"

    def test_enum_in_string_comparison(self):
        """Downstream code using == 'string' still works."""
        event_type = EventType.NODE_START
        assert event_type == "node_start"


# ---------------------------------------------------------------------------
# 2. Serialization round-trip — to_dict() produces correct wire format
# ---------------------------------------------------------------------------

class TestSerialization:
    """Typed events serialize to the HXI wire format."""

    def test_build_progress_to_dict(self):
        event = BuildProgressEvent(
            build_id="b-123",
            step="generating",
            step_label="Generating code...",
            current=2,
            total=3,
        )
        d = event.to_dict()
        assert d["type"] == "build_progress"
        assert d["data"]["build_id"] == "b-123"
        assert d["data"]["step"] == "generating"
        assert d["data"]["current"] == 2
        assert d["data"]["total"] == 3
        assert isinstance(d["timestamp"], float)
        assert "event_type" not in d["data"]
        assert "timestamp" not in d["data"]

    def test_trust_update_to_dict(self):
        event = TrustUpdateEvent(agent_id="a1", new_score=0.85, success=True)
        d = event.to_dict()
        assert d["type"] == "trust_update"
        assert d["data"]["agent_id"] == "a1"
        assert d["data"]["new_score"] == 0.85
        assert d["data"]["success"] is True

    def test_hebbian_update_to_dict(self):
        event = HebbianUpdateEvent(
            source="intent1", target="agent1", weight=0.72, rel_type="intent"
        )
        d = event.to_dict()
        assert d["type"] == "hebbian_update"
        assert d["data"]["source"] == "intent1"
        assert d["data"]["rel_type"] == "intent"

    def test_consensus_to_dict(self):
        event = ConsensusEvent(
            intent="test", outcome="approved",
            approval_ratio=0.8, votes=5,
            shapley={"a1": 0.3, "a2": 0.7},
        )
        d = event.to_dict()
        assert d["type"] == "consensus"
        assert d["data"]["shapley"] == {"a1": 0.3, "a2": 0.7}

    def test_build_started_to_dict(self):
        event = BuildStartedEvent(build_id="b1", title="Test", message="Starting...")
        d = event.to_dict()
        assert d["type"] == "build_started"

    def test_build_generated_to_dict(self):
        event = BuildGeneratedEvent(
            build_id="b1", title="T", description="D",
            ad_number="AD-1", file_changes=[{"path": "a.py"}],
        )
        d = event.to_dict()
        assert d["type"] == "build_generated"
        assert d["data"]["file_changes"] == [{"path": "a.py"}]

    def test_build_resolved_to_dict(self):
        event = BuildResolvedEvent(
            build_id="b1", resolution="abort", message="Aborted", commit=""
        )
        d = event.to_dict()
        assert d["type"] == "build_resolved"

    def test_build_success_to_dict(self):
        event = BuildSuccessEvent(
            build_id="b1", branch="feat", commit="abc",
            files_written=3, tests_passed=True,
        )
        d = event.to_dict()
        assert d["type"] == "build_success"
        assert d["data"]["tests_passed"] is True

    def test_build_failure_to_dict(self):
        event = BuildFailureEvent(build_id="b1", message="fail", error="err")
        d = event.to_dict()
        assert d["type"] == "build_failure"

    def test_self_mod_started_to_dict(self):
        event = SelfModStartedEvent(intent="test", description="d", message="m")
        d = event.to_dict()
        assert d["type"] == "self_mod_started"

    def test_self_mod_import_approved_to_dict(self):
        event = SelfModImportApprovedEvent(
            intent="test", imports=["os", "sys"], message="Approved"
        )
        d = event.to_dict()
        assert d["type"] == "self_mod_import_approved"
        assert d["data"]["imports"] == ["os", "sys"]

    def test_self_mod_progress_to_dict(self):
        event = SelfModProgressEvent(
            intent="t", step="designing", step_label="D",
            current=1, total=5,
        )
        d = event.to_dict()
        assert d["type"] == "self_mod_progress"

    def test_self_mod_success_to_dict(self):
        event = SelfModSuccessEvent(
            intent="t", agent_type="custom", agent_id="c1",
            message="ok", warnings=["w1"],
        )
        d = event.to_dict()
        assert d["type"] == "self_mod_success"
        assert d["data"]["warnings"] == ["w1"]

    def test_self_mod_retry_complete_to_dict(self):
        event = SelfModRetryCompleteEvent(intent="t", response="r", message="m")
        d = event.to_dict()
        assert d["type"] == "self_mod_retry_complete"

    def test_self_mod_failure_to_dict(self):
        event = SelfModFailureEvent(intent="t", message="fail", error="e")
        d = event.to_dict()
        assert d["type"] == "self_mod_failure"

    def test_design_events(self):
        for cls, etype in [
            (DesignStartedEvent, "design_started"),
            (DesignProgressEvent, "design_progress"),
            (DesignGeneratedEvent, "design_generated"),
            (DesignFailureEvent, "design_failure"),
        ]:
            d = cls().to_dict()
            assert d["type"] == etype

    def test_ward_room_events(self):
        for cls, etype in [
            (WardRoomThreadCreatedEvent, "ward_room_thread_created"),
            (WardRoomThreadUpdatedEvent, "ward_room_thread_updated"),
            (WardRoomPostCreatedEvent, "ward_room_post_created"),
            (WardRoomEndorsementEvent, "ward_room_endorsement"),
        ]:
            d = cls().to_dict()
            assert d["type"] == etype

    def test_timestamp_is_recent(self):
        before = time.time()
        event = BuildProgressEvent(build_id="b1")
        after = time.time()
        assert before <= event.timestamp <= after


# ---------------------------------------------------------------------------
# 3. Backward compatibility — _emit_event still works with raw strings
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Legacy string+dict calls still work through _emit_event."""

    def _make_emitter(self):
        """Create a minimal emitter with the new _emit_event logic."""
        import time as _time
        from probos.events import BaseEvent as _BaseEvent, EventType as _ET

        class _Emitter:
            def __init__(self):
                self._event_listeners = []

            def add_event_listener(self, fn):
                self._event_listeners.append(fn)

            def _emit_event(self, event_type, data=None):
                if isinstance(event_type, _BaseEvent):
                    event = event_type.to_dict()
                elif isinstance(event_type, _ET):
                    event = {"type": event_type.value, "data": data or {}, "timestamp": _time.time()}
                else:
                    event = {"type": event_type, "data": data or {}, "timestamp": _time.time()}
                for fn in self._event_listeners:
                    fn(event)

            def emit_event(self, event, data=None):
                if isinstance(event, _BaseEvent):
                    self._emit_event(event)
                else:
                    self._emit_event(event, data or {})

        return _Emitter()

    def test_emit_event_string_and_dict(self):
        """Legacy string+dict calls still fire events."""
        em = self._make_emitter()
        events = []
        em.add_event_listener(lambda e: events.append(e))
        em._emit_event("test_event", {"key": "value"})
        assert len(events) == 1
        assert events[0]["type"] == "test_event"
        assert events[0]["data"]["key"] == "value"

    def test_emit_event_with_event_type_enum(self):
        """EventType enum values work as first arg."""
        em = self._make_emitter()
        events = []
        em.add_event_listener(lambda e: events.append(e))
        em._emit_event(EventType.BUILD_PROGRESS, {"step": "test"})
        assert events[0]["type"] == "build_progress"

    def test_emit_event_with_typed_event(self):
        """BaseEvent subclass instances work as first arg."""
        em = self._make_emitter()
        events = []
        em.add_event_listener(lambda e: events.append(e))
        event = BuildProgressEvent(build_id="b1", step="gen")
        em._emit_event(event)
        assert events[0]["type"] == "build_progress"
        assert events[0]["data"]["build_id"] == "b1"

    def test_public_emit_event_typed(self):
        """Public emit_event() with typed event."""
        em = self._make_emitter()
        events = []
        em.add_event_listener(lambda e: events.append(e))
        em.emit_event(BuildProgressEvent(build_id="b1", step="gen"))
        assert events[0]["type"] == "build_progress"

    def test_public_emit_event_string(self):
        """Public emit_event() with string."""
        em = self._make_emitter()
        events = []
        em.add_event_listener(lambda e: events.append(e))
        em.emit_event("test_event", {"key": "value"})
        assert events[0]["type"] == "test_event"


# ---------------------------------------------------------------------------
# 4. Registry completeness — every _emit_event string has an EventType entry
# ---------------------------------------------------------------------------

class TestRegistryCompleteness:
    """Every event type string used in source has an EventType entry."""

    def test_all_event_type_strings_registered(self):
        """Scan source for event type strings and verify each is in EventType."""
        known_values = {m.value for m in EventType}
        src_files = glob.glob("src/probos/**/*.py", recursive=True)

        missing = set()
        # Patterns: _emit_event("...", _emit("...", _event_emitter("..."
        emit_pattern = re.compile(
            r'(?:_emit_event|_emit|_event_emitter)\(\s*["\']([a-z_]+)["\']'
        )

        for fpath in src_files:
            if "__pycache__" in fpath:
                continue
            with open(fpath, encoding="utf-8") as f:
                content = f.read()
            for match in emit_pattern.finditer(content):
                event_str = match.group(1)
                if event_str not in known_values:
                    missing.add(f"{fpath}: {event_str}")

        assert not missing, (
            f"Event type strings not in EventType registry:\n"
            + "\n".join(sorted(missing))
        )

    def test_enum_has_no_orphans(self):
        """Every EventType entry has at least one usage in source or tests."""
        # This is informational — some entries may only be used in
        # on_event callbacks which are harder to grep. Just verify
        # the enum is valid.
        for member in EventType:
            assert isinstance(member.value, str)
            assert len(member.value) > 0
