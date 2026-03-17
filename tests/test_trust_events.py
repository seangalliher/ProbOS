"""Tests for AD-295a: Trust Event Log."""

from __future__ import annotations

import time

import pytest

from probos.consensus.trust import TrustEvent, TrustNetwork


class TestTrustEventLog:
    def test_trust_event_recorded(self):
        """record_outcome() with causal kwargs produces a TrustEvent."""
        tn = TrustNetwork()
        tn.record_outcome(
            "agent-1", success=True, weight=0.8,
            intent_type="read_file", episode_id="ep-001", verifier_id="rt-0",
        )
        events = tn.get_recent_events()
        assert len(events) == 1
        e = events[0]
        assert e.agent_id == "agent-1"
        assert e.success is True
        assert e.weight == 0.8
        assert e.intent_type == "read_file"
        assert e.episode_id == "ep-001"
        assert e.verifier_id == "rt-0"

    def test_trust_event_scores(self):
        """old_score and new_score are accurately captured."""
        tn = TrustNetwork()
        # Default prior: alpha=2, beta=2 → score=0.5
        tn.record_outcome("agent-1", success=True)
        events = tn.get_recent_events()
        assert len(events) == 1
        e = events[0]
        assert e.old_score == 0.5
        # After success: alpha=3, beta=2 → score=0.6
        assert abs(e.new_score - 0.6) < 0.001

    def test_trust_event_log_capped(self):
        """Ring buffer caps at 500 events."""
        tn = TrustNetwork()
        for i in range(600):
            tn.record_outcome(f"agent-{i % 10}", success=True)
        events = tn.get_recent_events(n=1000)
        assert len(events) == 500

    def test_get_events_for_agent(self):
        """Filter events by agent_id returns correct subset."""
        tn = TrustNetwork()
        tn.record_outcome("agent-a", success=True)
        tn.record_outcome("agent-b", success=False)
        tn.record_outcome("agent-a", success=True)
        tn.record_outcome("agent-c", success=True)

        events_a = tn.get_events_for_agent("agent-a")
        assert len(events_a) == 2
        assert all(e.agent_id == "agent-a" for e in events_a)

        events_b = tn.get_events_for_agent("agent-b")
        assert len(events_b) == 1

    def test_get_events_since(self):
        """Time-based filtering returns events after timestamp."""
        tn = TrustNetwork()
        tn.record_outcome("agent-1", success=True)
        tn.record_outcome("agent-2", success=False)
        tn.record_outcome("agent-3", success=True)

        # Manually set timestamps to ensure ordering
        events = list(tn._event_log)
        events[0].timestamp = 100.0
        events[1].timestamp = 200.0
        events[2].timestamp = 300.0

        result = tn.get_events_since(150.0)
        assert len(result) == 2
        assert result[0].agent_id == "agent-2"
        assert result[1].agent_id == "agent-3"

    def test_backward_compatible(self):
        """Calling record_outcome without new kwargs still works."""
        tn = TrustNetwork()
        score = tn.record_outcome("agent-1", success=True)
        assert score > 0.5

        events = tn.get_recent_events()
        assert len(events) == 1
        e = events[0]
        # Causal fields should have defaults
        assert e.intent_type == ""
        assert e.episode_id == ""
        assert e.verifier_id == ""
