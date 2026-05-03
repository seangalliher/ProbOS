"""Combo C AD-573f: Commitment lifecycle helpers on dict-list shape."""

from __future__ import annotations

from probos.cognitive.working_memory import WorkingMemoryManager
from probos.events import EventType


def test_add_commitment_emits_record_event():
    mgr = WorkingMemoryManager()
    emitted: list = []
    mgr.set_event_callback(lambda et, data: emitted.append((et, data)))

    mgr.add_commitment("c-1", "ping captain", due_at=100.0)

    assert len(mgr._commitments) == 1
    assert mgr._commitments[0] == {"id": "c-1", "summary": "ping captain", "due": 100.0}
    assert emitted == [
        (EventType.COMMITMENT_RECORDED, {"commitment_id": "c-1", "action": "record"}),
    ]


def test_mark_commitment_complete_mutates_status_and_emits():
    mgr = WorkingMemoryManager()
    mgr.add_commitment("c-1", "summary")
    mgr.add_commitment("c-2", "another")

    emitted: list = []
    mgr.set_event_callback(lambda et, data: emitted.append((et, data)))

    mgr.mark_commitment_complete("c-1")

    by_id = {c["id"]: c for c in mgr._commitments}
    assert by_id["c-1"]["status"] == "done"
    assert "status" not in by_id["c-2"]
    assert emitted == [
        (EventType.COMMITMENT_RECORDED, {"commitment_id": "c-1", "action": "complete"}),
    ]


def test_mark_commitment_complete_unknown_id_is_noop():
    mgr = WorkingMemoryManager()
    mgr.add_commitment("c-1", "summary")

    emitted: list = []
    mgr.set_event_callback(lambda et, data: emitted.append((et, data)))

    mgr.mark_commitment_complete("does-not-exist")

    # No exception, no status mutation, no emit
    assert all("status" not in c for c in mgr._commitments)
    assert emitted == []


def test_pending_commitments_excludes_done_and_expired():
    mgr = WorkingMemoryManager()
    mgr.add_commitment("c-1", "first")
    mgr.add_commitment("c-2", "second")
    mgr.add_commitment("c-3", "third")
    mgr.mark_commitment_complete("c-1")
    # Manually mark c-3 expired (the lifecycle terminus, no public setter)
    for entry in mgr._commitments:
        if entry["id"] == "c-3":
            entry["status"] = "expired"

    pending = mgr.pending_commitments()
    pending_ids = [c["id"] for c in pending]
    assert pending_ids == ["c-2"]


def test_expired_commitments_filters_by_due_and_status():
    mgr = WorkingMemoryManager()
    mgr.add_commitment("past-pending", "first", due_at=50.0)
    mgr.add_commitment("past-done", "second", due_at=50.0)
    mgr.add_commitment("future", "third", due_at=200.0)
    mgr.add_commitment("no-due", "fourth")  # no due_at — never expired
    mgr.mark_commitment_complete("past-done")

    expired = mgr.expired_commitments(now=100.0)
    expired_ids = [c["id"] for c in expired]
    assert expired_ids == ["past-pending"]
