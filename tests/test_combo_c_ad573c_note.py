"""Combo C AD-573c: [NOTE] action tag → working memory scratchpad."""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.working_memory import WorkingMemoryManager
from probos.events import EventType


# Regex contract — kept in sync with proactive.py:2668
_NOTE_PATTERN = r'\[NOTE\s+([\w-]+)\](.*?)\[/NOTE\]'


def test_markers_dict_includes_note_tag():
    """AD-573c: gap-detector recognizes [NOTE ...] as a known action."""
    output = "Some thinking [NOTE topic-a]body text[/NOTE] more text."
    undeclared = CognitiveAgent._detect_undeclared_actions(output, [])
    assert "note" in undeclared

    # When declared, must NOT be flagged as undeclared
    undeclared2 = CognitiveAgent._detect_undeclared_actions(output, ["note"])
    assert "note" not in undeclared2


def test_note_pattern_extracts_single_note():
    text = "Thinking [NOTE plan]Remember to ping Captain[/NOTE] done."
    matches = re.findall(_NOTE_PATTERN, text, re.DOTALL)
    assert matches == [("plan", "Remember to ping Captain")]


def test_note_pattern_extracts_multi_line_and_multiple_notes():
    text = (
        "[NOTE alpha]first\nline\nbody[/NOTE]\n"
        "interlude\n"
        "[NOTE beta]second body[/NOTE]"
    )
    matches = re.findall(_NOTE_PATTERN, text, re.DOTALL)
    assert matches == [
        ("alpha", "first\nline\nbody"),
        ("beta", "second body"),
    ]


def test_note_handler_writes_to_scratchpad_and_emits_event():
    """Smoke-test the wiring: add_scratchpad + emit_event with the
    same call-shape the AD-573c extractor uses in proactive.py."""
    wm = WorkingMemoryManager()
    emitted: list = []

    def emit(et, data):
        emitted.append((et, data))

    wm.set_event_callback(emit)  # AD-573f setter — works for any EventType emit too

    rt = SimpleNamespace(working_memory=wm, emit_event=emit)
    text = "[NOTE plan]ping captain[/NOTE]"

    # Mirror the production extractor body
    for tag, body in re.findall(_NOTE_PATTERN, text, re.DOTALL):
        cleaned = body.strip()
        rt.working_memory.add_scratchpad(cleaned)
        rt.emit_event(
            EventType.WORKING_MEMORY_NOTE_RECORDED,
            {"agent_id": "agent-1", "tag": tag, "text_len": len(cleaned)},
        )

    assert wm._scratchpad == ["ping captain"]
    assert len(emitted) == 1
    et, payload = emitted[0]
    assert et == EventType.WORKING_MEMORY_NOTE_RECORDED
    assert payload == {"agent_id": "agent-1", "tag": "plan", "text_len": 12}
