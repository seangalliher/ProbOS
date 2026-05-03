"""Combo A AD-573b: Working Memory Extensions tests."""

from __future__ import annotations

from probos.cognitive.working_memory import WorkingMemoryManager, WorkingMemorySnapshot


def test_wm_snapshot_includes_new_fields():
    snap = WorkingMemorySnapshot()
    assert snap.relational_links == []
    assert snap.scratchpad == []
    assert snap.commitments == []


def test_wm_record_relation_appends_to_links():
    mgr = WorkingMemoryManager()
    mgr.record_relation("agent-a", "agent-b", kind="mention")
    assert len(mgr._relational_links) == 1
    link = mgr._relational_links[0]
    assert link == {"from": "agent-a", "to": "agent-b", "kind": "mention"}


def test_wm_scratchpad_cap_drops_oldest_at_17th_entry():
    mgr = WorkingMemoryManager()
    for i in range(20):
        mgr.add_scratchpad(f"note-{i}")
    # cap is 16; oldest dropped
    assert len(mgr._scratchpad) == 16
    assert mgr._scratchpad[0] == "note-4"
    assert mgr._scratchpad[-1] == "note-19"
