"""AD-1163: tell the agent the Captain's browser session exists.

AD-1158 bound the session through the call context and AD-1162 supplied the
binding. Both work. Live test result: Ezri, holding a ``write`` grant on
``browser``, offered the tool, and bound to the Captain's exact session, made
**zero tool calls** and replied that she could not control the Captain's screen.

That was correct reasoning from what she knew. AD-1158's own decision record
states the design intent: *"The binding travels through the call context, so no
prompt text and no model accuracy is involved."* Right for reliability — no UUID
has to survive a model copying it — but invisible to the plumbing turned out to
mean invisible to the agent. She saw a tool for "driving a Chromium browser" and
a request about "the document I have open", and those do not read as the same
thing.

So: the offered description names the Captain's open page. These tests pin the
ANNOUNCEMENT, which is the half that was missing; the binding already had suites
that passed while the feature went unused.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import (
    _announce_shared_session,
    _captain_browser_session,
    _captain_browser_session_id,
    _shared_session_note,
)
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE


def _definition(description: str = "Drive a Chromium browser.") -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "browser",
            "description": description,
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _describe(definition: dict[str, Any]) -> str:
    return definition["function"]["description"]


# -- the note itself ------------------------------------------------------


def test_the_note_names_the_page_title_when_present() -> None:
    note = _shared_session_note({"page_title": "Document 5.docx", "url": "https://x"})
    assert "Document 5.docx" in note


def test_the_note_falls_back_to_the_url_without_a_title() -> None:
    note = _shared_session_note({"page_title": "", "url": "https://onedrive.example/doc"})
    assert "https://onedrive.example/doc" in note


def test_the_note_accepts_last_url_as_the_url_key() -> None:
    """``list_sessions`` reports ``last_url``; don't depend on one spelling."""
    note = _shared_session_note({"last_url": "https://example.test/page"})
    assert "https://example.test/page" in note


def test_the_note_survives_a_row_with_neither_title_nor_url() -> None:
    note = _shared_session_note({})
    assert "shared with the Captain" in note
    assert "session_id" in note


def test_the_note_makes_the_connection_the_agent_was_missing() -> None:
    """The live failure was not knowing that 'the document I have open' IS the
    browser session. The note must say so explicitly."""
    note = _shared_session_note({"page_title": "Doc"})
    lowered = note.lower()
    assert "open" in lowered
    assert "omit session_id" in lowered


def test_the_note_is_clean_under_the_real_capability_gap_regex() -> None:
    """Phrasing that reads as a capability gap would undo the whole point."""
    note = _shared_session_note({"page_title": "Document 5.docx", "url": "https://x"})
    match = _CAPABILITY_GAP_RE.search(note)
    assert match is None, f"tripped on {match.group(0)!r} in: {note}"


def test_a_long_title_is_bounded() -> None:
    note = _shared_session_note({"page_title": "T" * 500})
    assert len(note) < 400


def test_a_long_url_is_bounded() -> None:
    note = _shared_session_note({"url": "https://example.test/" + "p" * 500})
    assert len(note) < 400


# -- the annotation -------------------------------------------------------


def test_the_note_is_appended_to_the_offered_description() -> None:
    annotated = _announce_shared_session(_definition(), {"page_title": "Doc"})
    assert _describe(annotated).startswith("Drive a Chromium browser.")
    assert "shared with the Captain" in _describe(annotated)


def test_annotating_does_not_mutate_the_source_definition() -> None:
    definition = _definition()
    before = _describe(definition)
    annotated = _announce_shared_session(definition, {"page_title": "Doc"})
    assert _describe(definition) == before
    assert annotated is not definition


def test_it_composes_with_the_bf690_read_only_narrowing() -> None:
    """A restricted agent still needs to know the session exists."""
    read_only = _definition(
        "Read a Chromium browser session. This session is offered in read-only "
        "mode, with these actions: goto, state."
    )
    annotated = _announce_shared_session(read_only, {"page_title": "Doc"})
    assert "read-only mode" in _describe(annotated)
    assert "shared with the Captain" in _describe(annotated)


@pytest.mark.parametrize(
    "definition",
    [{}, {"function": None}, {"function": "not-a-dict"}, {"function": []}],
)
def test_a_malformed_definition_degrades_and_warns(
    definition: dict[str, Any], caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        result = _announce_shared_session(definition, {"page_title": "Doc"})
    assert result is definition
    assert "AD-1163" in caplog.text


def test_a_definition_without_a_description_still_gets_the_note() -> None:
    definition = {"type": "function", "function": {"name": "browser"}}
    annotated = _announce_shared_session(definition, {"page_title": "Doc"})
    assert "shared with the Captain" in _describe(annotated)


# -- the resolver ---------------------------------------------------------


def test_resolver_returns_none_without_a_browser_tool() -> None:
    assert _captain_browser_session(SimpleNamespace()) is None
    assert _captain_browser_session(SimpleNamespace(browser_tool=None)) is None


def test_resolver_returns_the_row() -> None:
    row = {"session_id": "s1", "url": "https://x", "page_title": "Doc"}
    tool = SimpleNamespace(captain_session=row)
    assert _captain_browser_session(SimpleNamespace(browser_tool=tool)) == row


def test_resolver_degrades_when_the_property_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Raising:
        @property
        def captain_session(self) -> dict[str, Any]:
            raise RuntimeError("session table corrupt")

    with caplog.at_level(logging.WARNING):
        result = _captain_browser_session(SimpleNamespace(browser_tool=_Raising()))
    assert result is None
    assert "AD-1163" in caplog.text


@pytest.mark.parametrize("bad", [None, "", 7, [], object()])
def test_resolver_rejects_a_non_dict_row(bad: Any) -> None:
    tool = SimpleNamespace(captain_session=bad)
    assert _captain_browser_session(SimpleNamespace(browser_tool=tool)) is None


def test_the_id_helper_still_derives_from_the_row() -> None:
    """AD-1162's contract must survive the AD-1163 refactor."""
    tool = SimpleNamespace(captain_session={"session_id": "s-42"})
    assert _captain_browser_session_id(SimpleNamespace(browser_tool=tool)) == "s-42"


@pytest.mark.parametrize("bad", [None, "", 7, {"nested": 1}])
def test_the_id_helper_rejects_a_malformed_session_id(bad: Any) -> None:
    tool = SimpleNamespace(captain_session={"session_id": bad})
    assert _captain_browser_session_id(SimpleNamespace(browser_tool=tool)) is None
