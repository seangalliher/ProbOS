"""AD-670: Tests for Working Memory Metabolism."""

from __future__ import annotations

import time
from collections import deque

import pytest

from probos.cognitive.agent_working_memory import (
    AgentWorkingMemory,
    WorkingMemoryEntry,
)
from probos.cognitive.memory_metabolism import (
    AuditFlag,
    MemoryMetabolism,
    MetabolismReport,
)


def _make_entry(
    content: str = "test entry",
    category: str = "observation",
    source: str = "system",
    age_seconds: float = 0.0,
    metadata: dict | None = None,
) -> WorkingMemoryEntry:
    """Helper to create a WorkingMemoryEntry with a specific age."""
    return WorkingMemoryEntry(
        content=content,
        category=category,
        source_pathway=source,
        timestamp=time.time() - age_seconds,
        metadata=metadata or {},
    )


def _make_buffer(
    entries: list[WorkingMemoryEntry],
    maxlen: int = 10,
) -> deque[WorkingMemoryEntry]:
    buffer: deque[WorkingMemoryEntry] = deque(maxlen=maxlen)
    buffer.extend(entries)
    return buffer


class TestDecay:
    """DECAY operation tests."""

    def test_decay_fresh_entry_score_near_one(self) -> None:
        metabolism = MemoryMetabolism(decay_half_life_seconds=3600)
        buffer = _make_buffer([_make_entry(age_seconds=0)])

        metabolism.decay(buffer)
        score = buffer[0].metadata["_decay_score"]

        assert 0.99 <= score <= 1.0

    def test_decay_half_life_entry(self) -> None:
        metabolism = MemoryMetabolism(decay_half_life_seconds=3600)
        buffer = _make_buffer([_make_entry(age_seconds=3600)])

        metabolism.decay(buffer)
        score = buffer[0].metadata["_decay_score"]

        assert 0.49 <= score <= 0.51

    def test_decay_very_old_entry_near_zero(self) -> None:
        metabolism = MemoryMetabolism(decay_half_life_seconds=3600)
        buffer = _make_buffer([_make_entry(age_seconds=36000)])

        metabolism.decay(buffer)
        score = buffer[0].metadata["_decay_score"]

        assert score < 0.01

    def test_decay_returns_count(self) -> None:
        metabolism = MemoryMetabolism()
        entries = [_make_entry(content=f"e{index}") for index in range(5)]
        buffer = _make_buffer(entries)

        count = metabolism.decay(buffer)

        assert count == 5

    def test_decay_empty_buffer(self) -> None:
        metabolism = MemoryMetabolism()
        buffer: deque[WorkingMemoryEntry] = deque(maxlen=10)

        assert metabolism.decay(buffer) == 0


class TestForget:
    """FORGET operation tests."""

    def test_forget_removes_below_threshold(self) -> None:
        metabolism = MemoryMetabolism(forget_threshold=0.1, min_entries_per_buffer=0)
        entries = [
            _make_entry(content="fresh", age_seconds=0),
            _make_entry(content="stale", age_seconds=36000),
        ]
        buffer = _make_buffer(entries)

        metabolism.decay(buffer)
        removed = metabolism.forget(buffer)

        assert removed == 1
        assert len(buffer) == 1
        assert buffer[0].content == "fresh"

    def test_forget_respects_min_entries(self) -> None:
        metabolism = MemoryMetabolism(
            forget_threshold=0.5,
            min_entries_per_buffer=2,
            decay_half_life_seconds=3600,
        )
        entries = [_make_entry(content=f"old{index}", age_seconds=7200) for index in range(5)]
        buffer = _make_buffer(entries)

        metabolism.decay(buffer)
        metabolism.forget(buffer)

        assert len(buffer) >= 2

    def test_forget_without_prior_decay_keeps_all(self) -> None:
        metabolism = MemoryMetabolism(forget_threshold=0.5, min_entries_per_buffer=0)
        entries = [_make_entry(content=f"e{index}") for index in range(3)]
        buffer = _make_buffer(entries)

        removed = metabolism.forget(buffer)

        assert removed == 0
        assert len(buffer) == 3

    def test_forget_empty_buffer(self) -> None:
        metabolism = MemoryMetabolism()
        buffer: deque[WorkingMemoryEntry] = deque(maxlen=10)

        assert metabolism.forget(buffer) == 0


class TestAudit:
    """AUDIT operation tests."""

    def test_audit_flags_contradiction(self) -> None:
        metabolism = MemoryMetabolism(audit_enabled=True)
        now = time.time()
        entries = [
            WorkingMemoryEntry(
                content="Trust scores are stable and healthy",
                category="observation",
                source_pathway="proactive",
                timestamp=now,
            ),
            WorkingMemoryEntry(
                content="Trust scores are not stable at all",
                category="observation",
                source_pathway="proactive",
                timestamp=now + 10,
            ),
        ]
        buffer = _make_buffer(entries)

        flags = metabolism.audit(buffer, "observations")

        assert len(flags) >= 1
        assert isinstance(flags[0], AuditFlag)
        assert flags[0].buffer_name == "observations"
        assert "contradiction" in flags[0].reason.lower()

    def test_audit_no_flag_for_different_sources(self) -> None:
        metabolism = MemoryMetabolism(audit_enabled=True)
        now = time.time()
        entries = [
            WorkingMemoryEntry(
                content="Trust scores are stable",
                category="observation",
                source_pathway="proactive",
                timestamp=now,
            ),
            WorkingMemoryEntry(
                content="Trust scores are not stable",
                category="observation",
                source_pathway="dm",
                timestamp=now + 10,
            ),
        ]
        buffer = _make_buffer(entries)

        flags = metabolism.audit(buffer, "observations")

        assert len(flags) == 0

    def test_audit_disabled(self) -> None:
        metabolism = MemoryMetabolism(audit_enabled=False)
        now = time.time()
        entries = [
            WorkingMemoryEntry(
                content="System is healthy",
                category="observation",
                source_pathway="proactive",
                timestamp=now,
            ),
            WorkingMemoryEntry(
                content="System is not healthy",
                category="observation",
                source_pathway="proactive",
                timestamp=now + 10,
            ),
        ]
        buffer = _make_buffer(entries)

        assert metabolism.audit(buffer, "obs") == []

    def test_audit_no_flag_for_distant_timestamps(self) -> None:
        metabolism = MemoryMetabolism(audit_enabled=True)
        now = time.time()
        entries = [
            WorkingMemoryEntry(
                content="Latency is normal",
                category="observation",
                source_pathway="proactive",
                timestamp=now,
            ),
            WorkingMemoryEntry(
                content="Latency is not normal anymore",
                category="observation",
                source_pathway="proactive",
                timestamp=now + 400,
            ),
        ]
        buffer = _make_buffer(entries)

        flags = metabolism.audit(buffer, "observations")

        assert len(flags) == 0


class TestTriage:
    """TRIAGE operation tests."""

    def test_triage_admits_normal_entry(self) -> None:
        metabolism = MemoryMetabolism(triage_base_score=0.3)
        entry = _make_entry(content="Normal observation about system health")
        buffer = _make_buffer([], maxlen=10)

        assert metabolism.triage(entry, buffer) is True

    def test_triage_rejects_empty_content(self) -> None:
        metabolism = MemoryMetabolism()
        entry = _make_entry(content="   ")
        buffer = _make_buffer([], maxlen=10)

        assert metabolism.triage(entry, buffer) is False

    def test_triage_raises_bar_when_full(self) -> None:
        metabolism = MemoryMetabolism(
            triage_fullness_threshold=0.8,
            triage_base_score=0.3,
        )
        entries = [_make_entry(content=f"entry {index} with enough words") for index in range(9)]
        buffer = _make_buffer(entries, maxlen=10)
        short_entry = _make_entry(content="ok")

        assert metabolism.triage(short_entry, buffer) is False

    def test_triage_unbounded_buffer_always_admits(self) -> None:
        metabolism = MemoryMetabolism()
        entry = _make_entry(content="x")
        buffer: deque[WorkingMemoryEntry] = deque()

        assert metabolism.triage(entry, buffer) is True


class TestRunCycle:
    """Full metabolism cycle tests."""

    def test_run_cycle_returns_report(self) -> None:
        metabolism = MemoryMetabolism()
        buffers = {
            "actions": _make_buffer([_make_entry(content="action 1")]),
            "observations": _make_buffer([]),
        }

        report = metabolism.run_cycle(buffers)

        assert isinstance(report, MetabolismReport)
        assert report.decayed_count == 1
        assert report.forgotten_count == 0
        assert report.cycle_duration_ms >= 0

    def test_run_cycle_forgets_stale_entries(self) -> None:
        metabolism = MemoryMetabolism(
            decay_half_life_seconds=3600,
            forget_threshold=0.1,
            min_entries_per_buffer=0,
        )
        entries = [
            _make_entry(content="very old entry about system", age_seconds=36000),
            _make_entry(content="fresh entry about system", age_seconds=0),
        ]
        buffers = {"observations": _make_buffer(entries)}

        report = metabolism.run_cycle(buffers)

        assert report.forgotten_count == 1
        assert len(buffers["observations"]) == 1


class TestConstructorValidation:
    """Constructor input validation."""

    def test_negative_half_life_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            MemoryMetabolism(decay_half_life_seconds=-1)

    def test_forget_threshold_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="between"):
            MemoryMetabolism(forget_threshold=1.5)

    def test_negative_min_entries_raises(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            MemoryMetabolism(min_entries_per_buffer=-1)


class TestAgentWorkingMemoryIntegration:
    """Integration: AgentWorkingMemory + MemoryMetabolism."""

    def test_set_metabolism_and_run_cycle(self) -> None:
        wm = AgentWorkingMemory()
        metabolism = MemoryMetabolism()
        wm.set_metabolism(metabolism)
        wm.record_action("did something", source="system")

        wm.run_metabolism_cycle()

        entry = list(wm.get_buffers()["actions"])[0]
        assert "_decay_score" in entry.metadata

    def test_run_metabolism_cycle_without_metabolism_is_noop(self) -> None:
        wm = AgentWorkingMemory()
        wm.record_action("test", source="system")

        wm.run_metabolism_cycle()

        assert len(wm.get_buffers()["actions"]) == 1

    def test_triage_gate_rejects_empty_content(self) -> None:
        wm = AgentWorkingMemory()
        metabolism = MemoryMetabolism()
        wm.set_metabolism(metabolism)

        wm.record_action("   ", source="system")

        assert len(wm.get_buffers()["actions"]) == 0

    def test_no_metabolism_admits_all(self) -> None:
        wm = AgentWorkingMemory()

        wm.record_action("   ", source="system")

        assert len(wm.get_buffers()["actions"]) == 1
