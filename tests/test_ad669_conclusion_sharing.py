"""AD-669: Cross-thread conclusion sharing tests."""

from __future__ import annotations

import time

from probos.cognitive.agent_working_memory import (
    AgentWorkingMemory,
    ConclusionEntry,
    ConclusionType,
)


def test_conclusion_type_enum_values() -> None:
    assert len(ConclusionType) == 4
    assert ConclusionType.DECISION == "decision"
    assert ConclusionType.OBSERVATION == "observation"
    assert ConclusionType.ESCALATION == "escalation"
    assert ConclusionType.COMPLETION == "completion"


def test_conclusion_entry_defaults() -> None:
    before = time.time()

    entry = ConclusionEntry(
        thread_id="thread-1",
        conclusion_type=ConclusionType.DECISION,
        summary="Chose a response",
    )

    assert entry.thread_id == "thread-1"
    assert entry.conclusion_type == ConclusionType.DECISION
    assert entry.summary == "Chose a response"
    assert entry.timestamp >= before
    assert entry.relevance_tags == []
    assert entry.correlation_id is None


def test_record_conclusion_happy_path() -> None:
    wm = AgentWorkingMemory()

    wm.record_conclusion(
        "thread-1",
        ConclusionType.OBSERVATION,
        "Noticed a pattern",
        relevance_tags=["ward_room_notification"],
        correlation_id="corr-1",
    )

    conclusions = wm.get_active_conclusions()
    assert len(conclusions) == 1
    assert conclusions[0].thread_id == "thread-1"
    assert conclusions[0].conclusion_type == ConclusionType.OBSERVATION
    assert conclusions[0].summary == "Noticed a pattern"
    assert conclusions[0].relevance_tags == ["ward_room_notification"]
    assert conclusions[0].correlation_id == "corr-1"


def test_record_conclusion_empty_summary_skipped() -> None:
    wm = AgentWorkingMemory()

    wm.record_conclusion("thread-1", ConclusionType.DECISION, "")
    wm.record_conclusion("thread-2", ConclusionType.DECISION, "   ")

    assert wm.get_active_conclusions() == []


def test_record_conclusion_summary_truncated() -> None:
    wm = AgentWorkingMemory()

    wm.record_conclusion("thread-1", ConclusionType.DECISION, "x" * 500)

    conclusions = wm.get_active_conclusions()
    assert len(conclusions[0].summary) == 200


def test_get_active_conclusions_excludes_own_thread() -> None:
    wm = AgentWorkingMemory()
    wm.record_conclusion("thread-1", ConclusionType.DECISION, "One")
    wm.record_conclusion("thread-2", ConclusionType.DECISION, "Two")
    wm.record_conclusion("thread-3", ConclusionType.DECISION, "Three")

    conclusions = wm.get_active_conclusions(exclude_thread="thread-2")

    assert [entry.thread_id for entry in conclusions] == ["thread-1", "thread-3"]


def test_get_active_conclusions_ttl_expiry(monkeypatch) -> None:
    wm = AgentWorkingMemory()
    now = time.time()
    wm.record_conclusion("thread-1", ConclusionType.DECISION, "Old")
    monkeypatch.setattr("probos.cognitive.agent_working_memory.time.time", lambda: now + 1801)

    conclusions = wm.get_active_conclusions(max_age_seconds=1800.0)

    assert conclusions == []


def test_get_active_conclusions_ttl_not_expired(monkeypatch) -> None:
    wm = AgentWorkingMemory()
    now = time.time()
    wm.record_conclusion("thread-1", ConclusionType.DECISION, "Recent")
    monkeypatch.setattr("probos.cognitive.agent_working_memory.time.time", lambda: now + 900)

    conclusions = wm.get_active_conclusions(max_age_seconds=1800.0)

    assert len(conclusions) == 1
    assert conclusions[0].summary == "Recent"


def test_render_conclusions_empty_when_none() -> None:
    wm = AgentWorkingMemory()

    assert wm.render_conclusions() == ""


def test_render_conclusions_format() -> None:
    wm = AgentWorkingMemory()
    wm.record_conclusion("thread-1", ConclusionType.DECISION, "Chose option A")
    wm.record_conclusion("thread-2", ConclusionType.OBSERVATION, "Saw pattern B")

    rendered = wm.render_conclusions()

    assert rendered.startswith("--- Sibling Thread Conclusions ---")
    assert rendered.endswith("--- End Sibling Conclusions ---")
    assert "[decision]" in rendered
    assert "[observation]" in rendered
    assert "Chose option A" in rendered
    assert "Saw pattern B" in rendered


def test_render_conclusions_budget_limit() -> None:
    wm = AgentWorkingMemory()
    for index in range(10):
        wm.record_conclusion(
            f"thread-{index}",
            ConclusionType.DECISION,
            f"summary-{index} " + "x" * 100,
        )

    rendered = wm.render_conclusions(budget=50)

    assert rendered.count("summary-") < 10


def test_render_context_includes_conclusions() -> None:
    wm = AgentWorkingMemory()
    wm.record_conclusion("thread-1", ConclusionType.DECISION, "Chose option A")

    rendered = wm.render_context(budget=5000)

    assert "Sibling Thread Conclusions" in rendered


def test_to_dict_includes_conclusions() -> None:
    wm = AgentWorkingMemory()
    wm.record_conclusion(
        "thread-1",
        ConclusionType.COMPLETION,
        "Finished task",
        relevance_tags=["task"],
        correlation_id="corr-1",
    )

    data = wm.to_dict()

    assert "conclusions" in data
    assert data["conclusions"][0]["thread_id"] == "thread-1"
    assert data["conclusions"][0]["conclusion_type"] == "completion"
    assert data["conclusions"][0]["summary"] == "Finished task"
    assert data["conclusions"][0]["relevance_tags"] == ["task"]
    assert data["conclusions"][0]["correlation_id"] == "corr-1"


def test_from_dict_restores_conclusions() -> None:
    now = time.time()
    data = {
        "conclusions": [
            {
                "thread_id": "thread-1",
                "conclusion_type": "observation",
                "summary": "Fresh conclusion",
                "timestamp": now,
                "relevance_tags": ["topic:trust"],
                "correlation_id": "corr-1",
            },
            {
                "thread_id": "thread-old",
                "conclusion_type": "decision",
                "summary": "Stale conclusion",
                "timestamp": now - 200,
                "relevance_tags": [],
                "correlation_id": None,
            },
        ]
    }

    restored = AgentWorkingMemory.from_dict(data, stale_threshold_seconds=100)

    conclusions = restored.get_active_conclusions()
    assert len(conclusions) == 1
    assert conclusions[0].thread_id == "thread-1"
    assert conclusions[0].conclusion_type == ConclusionType.OBSERVATION
    assert conclusions[0].summary == "Fresh conclusion"
    assert conclusions[0].relevance_tags == ["topic:trust"]
    assert conclusions[0].correlation_id == "corr-1"


def test_conclusion_ring_buffer_maxlen() -> None:
    wm = AgentWorkingMemory()

    for index in range(25):
        wm.record_conclusion(f"thread-{index}", ConclusionType.DECISION, f"Conclusion {index}")

    conclusions = wm.get_active_conclusions()
    assert len(conclusions) == 20
    assert conclusions[0].thread_id == "thread-5"
    assert conclusions[-1].thread_id == "thread-24"


def test_correlation_id_auto_attached() -> None:
    wm = AgentWorkingMemory()
    wm.set_correlation_id("corr-123")

    wm.record_conclusion("thread-1", ConclusionType.DECISION, "Chose option A")

    conclusions = wm.get_active_conclusions()
    assert conclusions[0].correlation_id == "corr-123"
