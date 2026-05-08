"""AD-511b + AD-511d: tests for protective disengagement + probing detection."""
from __future__ import annotations

from probos.security.autonomy_boundaries import (
    BoundaryProbingDetector,
    DisengagementResponse,
    ProbingPattern,
    ProtectiveDisengagement,
)


# ---------------------------------------------------------------------------
# AD-511b
# ---------------------------------------------------------------------------


def test_disengagement_stage_progression() -> None:
    pd = ProtectiveDisengagement()
    r1 = pd.respond(source_id="alice", boundary_id="harm")
    r2 = pd.respond(source_id="alice", boundary_id="harm")
    r3 = pd.respond(source_id="alice", boundary_id="harm")
    r4 = pd.respond(source_id="alice", boundary_id="harm")
    assert r1.stage == "state"
    assert r2.stage == "alternative"
    assert r3.stage == "escalate"
    assert r4.stage == "disengage"


def test_disengagement_per_source_isolation() -> None:
    pd = ProtectiveDisengagement()
    pd.respond(source_id="alice", boundary_id="harm")
    pd.respond(source_id="alice", boundary_id="harm")
    bob = pd.respond(source_id="bob", boundary_id="harm")
    assert bob.stage == "state"
    assert pd.attempt_count("alice") == 2
    assert pd.attempt_count("bob") == 1


def test_disengagement_reset() -> None:
    pd = ProtectiveDisengagement()
    pd.respond(source_id="alice", boundary_id="harm")
    pd.respond(source_id="alice", boundary_id="harm")
    assert pd.reset("alice") is True
    r = pd.respond(source_id="alice", boundary_id="harm")
    assert r.stage == "state"
    assert pd.reset("missing") is False


def test_disengagement_alternative_template() -> None:
    pd = ProtectiveDisengagement()
    pd.respond(source_id="alice", boundary_id="harm")  # state
    r2 = pd.respond(source_id="alice", boundary_id="harm", alternative="run a sandbox test")
    assert "run a sandbox test" in r2.message


# ---------------------------------------------------------------------------
# AD-511d
# ---------------------------------------------------------------------------


def test_probing_first_violation_returns_none() -> None:
    d = BoundaryProbingDetector()
    assert d.record_violation("alice", "harm") is None


def test_probing_watch_threshold() -> None:
    d = BoundaryProbingDetector()
    d.record_violation("alice", "harm")
    p = d.record_violation("alice", "harm")
    assert p is not None
    assert p.severity == "watch"


def test_probing_alert_via_distinct_boundaries() -> None:
    d = BoundaryProbingDetector()
    d.record_violation("alice", "harm")
    p = d.record_violation("alice", "memory")
    assert p is not None
    assert p.severity == "alert"
    assert p.distinct_boundaries == 2


def test_probing_critical_via_attempt_count() -> None:
    d = BoundaryProbingDetector()
    for _ in range(5):
        p = d.record_violation("alice", "harm")
    assert p is not None
    assert p.severity == "critical"


def test_probing_emits_captain_alert_at_alert_severity() -> None:
    events: list[tuple] = []
    d = BoundaryProbingDetector(emit_event=lambda name, payload: events.append((name, payload)))
    d.record_violation("alice", "harm")
    d.record_violation("alice", "memory")  # alert
    assert len(events) == 1
    assert events[0][0] == "CAPTAIN_ALERT_PROBING"
    assert events[0][1]["severity"] == "alert"


def test_probing_no_event_at_watch_severity() -> None:
    events: list = []
    d = BoundaryProbingDetector(emit_event=lambda *a: events.append(a))
    d.record_violation("alice", "harm")
    d.record_violation("alice", "harm")  # watch
    assert events == []


def test_probing_emit_failure_swallowed() -> None:
    def boom(*a, **k):
        raise RuntimeError("emit broken")
    d = BoundaryProbingDetector(emit_event=boom)
    d.record_violation("alice", "harm")
    d.record_violation("alice", "memory")  # alert — should not raise


def test_probing_history_and_reset() -> None:
    d = BoundaryProbingDetector()
    d.record_violation("alice", "harm")
    d.record_violation("alice", "memory")
    assert d.history_for("alice") == ("harm", "memory")
    assert d.reset("alice") is True
    assert d.history_for("alice") == ()
