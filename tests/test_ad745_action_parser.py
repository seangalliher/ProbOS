"""AD-745: action bracket-marker parser tests."""
from __future__ import annotations

from probos.cognitive.dm.action_parser import (
    ActionEnvelope,
    parse_action_envelopes,
    strip_action_markers,
)


def test_parse_extracts_one_envelope() -> None:
    text = 'Looking at the page. [ACTION: {"verb":"click","args":{"selector":"#submit"},"intent":"the Submit button"}] Done.'
    envelopes = parse_action_envelopes(text)
    assert len(envelopes) == 1
    e = envelopes[0]
    assert isinstance(e, ActionEnvelope)
    assert e.verb == "click"
    assert e.args == {"selector": "#submit"}
    assert e.raw_intent == "the Submit button"


def test_parse_handles_multiple_envelopes() -> None:
    text = (
        '[ACTION: {"verb":"screenshot","args":{}}] then '
        '[ACTION: {"verb":"click","args":{"selector":"#next"},"intent":"next"}]'
    )
    envelopes = parse_action_envelopes(text)
    assert len(envelopes) == 2
    assert envelopes[0].verb == "screenshot"
    assert envelopes[1].verb == "click"


def test_parse_skips_malformed_json(caplog) -> None:
    text = '[ACTION: {not json}] and [ACTION: {"verb":"state","args":{}}]'
    envelopes = parse_action_envelopes(text)
    # Only the well-formed envelope survives; malformed one is skipped.
    assert len(envelopes) == 1
    assert envelopes[0].verb == "state"


def test_parse_empty_text_returns_empty_list() -> None:
    assert parse_action_envelopes("") == []
    assert parse_action_envelopes("no markers here at all") == []


def test_parse_skips_envelope_missing_verb() -> None:
    text = '[ACTION: {"args":{"x":1}}]'
    envelopes = parse_action_envelopes(text)
    assert envelopes == []


def test_strip_removes_markers_even_when_malformed() -> None:
    text = 'Before [ACTION: {"verb":"click","args":{}}] middle [ACTION: {malformed}] after.'
    stripped = strip_action_markers(text)
    assert "[ACTION" not in stripped
    assert "Before" in stripped
    assert "middle" in stripped
    assert "after." in stripped


def test_strip_returns_input_when_no_marker() -> None:
    text = "Just a plain reply."
    assert strip_action_markers(text) == text
