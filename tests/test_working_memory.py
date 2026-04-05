"""Tests for working memory manager — assembly, eviction, and token budget."""

import pytest

from probos.cognitive.working_memory import WorkingMemoryManager, WorkingMemorySnapshot


class TestWorkingMemorySnapshot:
    def test_empty_snapshot_to_text(self):
        snap = WorkingMemorySnapshot()
        text = snap.to_text()
        assert "System State" in text

    def test_snapshot_with_agents(self):
        snap = WorkingMemorySnapshot(
            agent_summary={"total": 5, "crew": 3, "pools": {"fs": "3 agents"}},
        )
        text = snap.to_text()
        assert "Crew: 3 agents" in text
        assert "fs" in text

    def test_snapshot_with_capabilities(self):
        snap = WorkingMemorySnapshot(
            capabilities=["read_file", "write_file"],
        )
        text = snap.to_text()
        assert "read_file" in text
        assert "write_file" in text

    def test_snapshot_with_trust(self):
        snap = WorkingMemorySnapshot(
            trust_summary=[
                {"agent_id": "abcdef1234567890", "score": 0.95},
            ],
        )
        text = snap.to_text()
        assert "Trust scores" in text
        assert "0.95" in text

    def test_snapshot_with_connections(self):
        snap = WorkingMemorySnapshot(
            top_connections=[
                {"source": "agent_aaaaaa", "target": "agent_bbbbbb", "weight": 0.1234},
            ],
        )
        text = snap.to_text()
        assert "Hebbian" in text
        assert "0.1234" in text

    def test_token_estimate(self):
        snap = WorkingMemorySnapshot()
        est = snap.token_estimate()
        assert est > 0

    def test_token_estimate_scales_with_content(self):
        small = WorkingMemorySnapshot()
        big = WorkingMemorySnapshot(
            capabilities=["cap_" + str(i) for i in range(50)],
            trust_summary=[
                {"agent_id": f"agent_{i:032d}", "score": 0.5}
                for i in range(10)
            ],
        )
        assert big.token_estimate() > small.token_estimate()


class TestWorkingMemoryManager:
    @pytest.fixture
    def wm(self):
        return WorkingMemoryManager(token_budget=4000)

    def test_record_intent(self, wm):
        wm.record_intent("read_file", {"path": "/tmp/test.txt"})
        assert len(wm._active_intents) == 1
        assert wm._active_intents[0]["intent"] == "read_file"
        assert wm._active_intents[0]["status"] == "active"

    def test_record_result_removes_from_active(self, wm):
        wm.record_intent("read_file", {"path": "/tmp/test.txt"})
        wm.record_result("read_file", success=True, result_count=3)
        assert len(wm._active_intents) == 0
        assert len(wm._recent_results) == 1

    def test_bounded_intents(self, wm):
        for i in range(30):
            wm.record_intent(f"intent_{i}", {"i": i})
        assert len(wm._active_intents) == wm._max_recent

    def test_bounded_results(self, wm):
        for i in range(30):
            wm.record_result(f"intent_{i}", success=True)
        assert len(wm._recent_results) == wm._max_recent

    def test_assemble_without_sources(self, wm):
        wm.record_intent("read_file", {"path": "/tmp/test.txt"})
        snap = wm.assemble()
        assert len(snap.active_intents) == 1
        assert snap.agent_summary == {}
        assert snap.trust_summary == []
        assert snap.top_connections == []

    def test_eviction_under_budget(self):
        """With a very tight budget, eviction should trim connections and trust."""
        wm = WorkingMemoryManager(token_budget=15)  # ~60 chars — only header fits
        snap = WorkingMemorySnapshot(
            active_intents=[
                {"intent": f"intent_{i}", "status": "active"} for i in range(5)
            ],
            recent_results=[
                {"intent": f"result_{i}", "success": True} for i in range(5)
            ],
            trust_summary=[
                {"agent_id": f"agent_{i:032d}", "score": 0.5} for i in range(5)
            ],
            top_connections=[
                {"source": f"src_{i:012d}", "target": f"tgt_{i:012d}", "weight": 0.1}
                for i in range(5)
            ],
        )
        wm._evict_to_budget(snap)
        # Should have trimmed connections and trust first, then results/intents
        assert len(snap.top_connections) <= 2
        assert len(snap.trust_summary) <= 2

    def test_assemble_returns_copy(self, wm):
        wm.record_intent("read_file", {"path": "/tmp/a.txt"})
        snap = wm.assemble()
        snap.active_intents.clear()
        # Original should be unaffected
        assert len(wm._active_intents) == 1
