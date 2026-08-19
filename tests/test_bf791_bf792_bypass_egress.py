"""BF-791/792: a reply that bypasses the pipeline still owes its egress.

Two paths answer the Captain without ``DmReplyPipeline`` -- the AD-1165
promotion report and the AD-1230 deferred replay. The matrix below is the point
of the file: BOTH markers are checked on BOTH paths, because the defect being
closed is that BF-702 fixed one marker on one path and the other three cells
stayed open for three releases.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from probos.cognitive.dm.bypass_egress import (
    UNRENDERABLE_NOTE,
    compose_bypass_reply,
    render_a2ui_as_text,
)

_EMOTION = "<intent emotion=warm>"
_CHOICE = json.dumps({
    "kind": "choice",
    "prompt": "Which deploy target?",
    "options": ["staging", "production"],
})
_MULTI = json.dumps({
    "kind": "multiselect",
    "prompt": "Which checks?",
    "options": ["lint", "types", "tests"],
    "min_select": 1,
})
_FORM = json.dumps({
    "kind": "form",
    "prompt": "Who is on call?",
    "fields": [{"label": "Name"}, {"label": "Pager"}],
})


def _a2ui(body: str) -> str:
    return f"[A2UI]{body}[/A2UI]"


# ── the function itself ─────────────────────────────────────────────────────


def test_untagged_text_is_returned_unchanged() -> None:
    """The no-op property that lets both callers apply it unconditionally."""
    text = "Deploy finished. Two services restarted."
    assert compose_bypass_reply(text) == text


def test_marker_free_text_keeps_its_whitespace_exactly() -> None:
    """Byte-identical, not merely equal-after-trim.

    The first draft trimmed unconditionally, which silently reflowed every
    ordinary deferred answer -- indented Markdown among them. The test above
    used a fixture with no leading or trailing space, so it could not see it.
    """
    text = "  - step one\n  - step two\n"
    assert compose_bypass_reply(text) == text


def test_whitespace_only_text_becomes_empty() -> None:
    """The carve-out in the byte-identity rule, and it is load-bearing.

    Both callers branch on falsiness to pick their empty-reply wording. Adding
    byte-identity without this returned ``"   "`` -- truthy -- and a silent
    promoted run posted three spaces instead of its report. Caught by
    ``test_ad1165_turn_promotion.py::test_a_silent_promoted_run_still_reports``.
    """
    assert compose_bypass_reply("   \n  ") == ""


def test_the_emotion_self_tag_is_removed() -> None:
    assert _EMOTION not in compose_bypass_reply(f"All done. {_EMOTION}")


def test_the_a2ui_block_is_replaced_by_its_question_and_options() -> None:
    out = compose_bypass_reply("Ready. " + _a2ui(_CHOICE))
    assert "[A2UI]" not in out.upper()
    assert "Which deploy target?" in out
    assert "1. staging" in out
    assert "2. production" in out


def test_a_multiselect_says_more_than_one_may_be_picked() -> None:
    out = compose_bypass_reply(_a2ui(_MULTI))
    assert "Which checks?" in out
    assert "3. tests" in out
    assert "more than one" in out
def test_a_form_renders_its_field_labels() -> None:
    out = compose_bypass_reply(_a2ui(_FORM))
    assert "Who is on call?" in out
    assert "- Name" in out
    assert "- Pager" in out


def test_both_markers_in_one_reply_are_both_removed() -> None:
    """The cell that a per-marker fix leaves open."""
    out = compose_bypass_reply(f"Pick one. {_a2ui(_CHOICE)} {_EMOTION}")
    assert "[A2UI]" not in out.upper()
    assert _EMOTION not in out
    assert "1. staging" in out


def test_a_reply_that_was_only_markers_composes_to_empty() -> None:
    """Both callers have empty-reply wording; a bare stripped tag is worse."""
    assert compose_bypass_reply(_EMOTION) == ""


def test_composition_is_idempotent() -> None:
    once = compose_bypass_reply(f"Ready. {_a2ui(_CHOICE)} {_EMOTION}")
    assert compose_bypass_reply(once) == once


def test_a_malformed_block_is_replaced_by_a_note_not_left_in_place() -> None:
    """Inverted from what this test first asserted, and kept rather than deleted.

    It originally pinned "leave the raw block alone", on the reasoning that
    protocol noise the Captain can report beats content silently removed.
    Review rejected that: the defect being fixed IS protocol framing reaching
    the Captain, so preserving the framing whenever parsing fails keeps the
    defect for exactly the inputs most likely to produce it. The note is the
    third option -- neither deletion nor leakage.
    """
    out = render_a2ui_as_text("Ready. " + _a2ui("{not json at all"))
    assert "[A2UI]" not in out.upper()
    assert UNRENDERABLE_NOTE in out
    assert "Ready." in out


def test_an_unknown_widget_kind_is_replaced_by_a_note() -> None:
    out = render_a2ui_as_text(_a2ui(json.dumps({"kind": "hologram", "prompt": "x"})))
    assert "[A2UI]" not in out.upper()
    assert UNRENDERABLE_NOTE in out


@pytest.mark.parametrize(
    "low,high,expected",
    [
        (1, 1, "(Pick one.)"),
        (2, 2, "(Pick exactly 2.)"),
        (1, 3, "(Pick between 1 and 3.)"),
        (2, None, "(Pick at least 2.)"),
        (1, None, "(You may pick more than one.)"),
    ],
)
def test_a_multiselect_states_its_actual_bounds(
    low: int, high: int | None, expected: str,
) -> None:
    """``min_select=1, max_select=1`` is a permitted shape and is ONE pick.

    The first draft printed "you may pick more than one" unconditionally, so a
    valid single-pick multiselect was given a false instruction.
    """
    payload: dict[str, object] = {
        "kind": "multiselect",
        "prompt": "Which checks?",
        "options": ["lint", "types", "tests"],
        "min_select": low,
    }
    if high is not None:
        payload["max_select"] = high
    out = compose_bypass_reply(_a2ui(json.dumps(payload)))
    assert expected in out


def test_none_and_empty_are_tolerated() -> None:
    assert compose_bypass_reply("") == ""
    assert compose_bypass_reply(None) == ""  # type: ignore[arg-type]


# ── the matrix: both markers, both bypass paths ─────────────────────────────


_MARKERS = [
    pytest.param(_EMOTION, _EMOTION, id="emotion-self-tag"),
    pytest.param(_a2ui(_CHOICE), "[A2UI]", id="a2ui-block"),
]


@pytest.mark.parametrize("marker,forbidden", _MARKERS)
async def test_the_promotion_report_reaches_the_thread_clean(
    marker: str, forbidden: str,
) -> None:
    """AD-1165 promotion, driven through the real reporter to its real sink.

    Asserting on the shared function through a module alias would prove only
    that the module imports it. This drives ``_finish_promoted_turn`` and reads
    what ``ChatThreadStore.append_message`` was handed, so deleting the call
    fails the test.
    """
    from types import SimpleNamespace

    from probos.cognitive import turn_promotion

    posted: list[dict[str, object]] = []

    class _Store:
        def append_message(self, thread_id: str, **kwargs: object) -> None:
            posted.append(kwargs)

    runtime = SimpleNamespace(chat_thread_store=_Store())

    async def _run() -> str:
        return f"The run finished. {marker}"

    await turn_promotion._finish_promoted_turn(
        asyncio.create_task(_run()),
        runtime=runtime,
        agent_id="ezri",
        thread_id="thread-1",
        work_item_id="wi-1",
    )

    assert posted, "the promoted report never reached the thread"
    body = str(posted[0]["body"])
    assert forbidden.upper() not in body.upper()
    assert "The run finished." in body


@pytest.mark.parametrize("marker,forbidden", _MARKERS)
async def test_the_deferred_replay_reaches_the_thread_clean(
    marker: str, forbidden: str,
) -> None:
    """AD-1230 deferred replay, driven through the real queue to its real sink."""
    from probos.cognitive.deferred_turns import DeferredTurnQueue

    posted: list[str] = []

    async def _dispatch(thread_id: str, agent_id: str, params: dict) -> str:
        return f"Sorry for the wait. {marker}"

    queue = DeferredTurnQueue(
        dispatch=_dispatch,
        post=lambda _t, _a, body: posted.append(body),
        is_healthy=lambda: True,
    )
    assert queue.offer(thread_id="thread-1", agent_id="ezri", params={})

    answered = await queue.drain_once()

    assert answered == 1
    assert posted, "the replayed answer never reached the thread"
    assert forbidden.upper() not in posted[0].upper()
    assert "Sorry for the wait." in posted[0]


async def test_a_deferred_reply_of_only_markers_is_not_delivered_as_an_answer() -> None:
    """It composes to empty, so it is not an answer and must not be posted."""
    from probos.cognitive.deferred_turns import DeferredTurnQueue

    posted: list[str] = []

    async def _dispatch(thread_id: str, agent_id: str, params: dict) -> str:
        return _EMOTION

    queue = DeferredTurnQueue(
        dispatch=_dispatch,
        post=lambda _t, _a, body: posted.append(body),
        is_healthy=lambda: True,
    )
    assert queue.offer(thread_id="thread-1", agent_id="ezri", params={})

    assert await queue.drain_once() == 0
    assert not any(_EMOTION in body for body in posted)


def test_both_bypass_modules_share_one_composition() -> None:
    """Named for the actual defect: the fix was applied to a path, not a shape.

    If a third bypass path appears, it should reach for this same object. If
    these two ever stop being the same function, a marker added later lands on
    one path and not the other -- which is exactly how BF-791 and BF-792 came
    to exist.
    """
    from probos.cognitive import deferred_turns, turn_promotion

    assert turn_promotion.compose_bypass_reply is compose_bypass_reply
    assert deferred_turns.compose_bypass_reply is compose_bypass_reply


# ── the sinks this does NOT cover, enumerated so they cannot be forgotten ────

#: Direct writers wired to ``compose_bypass_reply``.
#:
#: ``deferred_turns`` is composed too but is NOT here: it posts through an
#: injected callable rather than touching the store, so it does not appear in a
#: scan for the call. ``test_both_bypass_modules_share_one_composition`` is what
#: covers it. That asymmetry is worth stating -- a scan for the sink call is not
#: a scan for the paths that reach it.
_COMPOSED_SINKS = {
    "probos/cognitive/turn_promotion.py",
}

#: Every other module that appends into a chat thread, measured rather than
#: recalled. Mixed on purpose: some are Captain/system/API rows where marker-
#: looking text may be intentional user content and composing would be wrong;
#: others are model-authored replies with the same gap this module closes for
#: two paths. Review reached the ``cognitive_agent`` work-item acknowledgement
#: and got a stored body carrying BOTH markers.
#:
#: The point of listing them is that the gap is counted, not that every entry
#: should be composed.
_OTHER_SINKS = {
    "probos/cognitive/cognitive_agent.py",
    "probos/cognitive/crew_executor.py",
    "probos/proactive.py",
    "probos/routers/agents.py",
    "probos/routers/chat.py",
    "probos/routers/thread_fanout.py",
    "probos/routers/threads.py",
    "probos/startup/finalize.py",
    "probos/threads/__init__.py",
    "probos/threads/agent_group_chat.py",
}


def test_the_set_of_thread_writers_is_the_one_that_was_enumerated() -> None:
    """A new Captain-visible writer must be classified, not inherited.

    Fails loudly in BOTH directions: a module that starts appending messages is
    an unclassified sink, and a module that stops is a stale entry. Either way
    somebody has to look.

    The list came from running this scan, not from recall -- the first draft was
    assembled from an adversarial review's enumeration and this test immediately
    found three modules it had missed.
    """
    import pathlib
    import re

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "probos"
    pattern = re.compile(r"\.append_message(?:_once)?\s*\(")

    found = {
        path.relative_to(src.parent).as_posix()
        for path in src.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    }

    assert found, "the scan found no thread writers at all -- it is broken"

    known = _COMPOSED_SINKS | _OTHER_SINKS
    assert found == known, (
        "the set of modules appending Captain-visible messages changed. New "
        f"({sorted(found - known)}) must be classified as composed or tracked; "
        f"missing ({sorted(known - found)}) are stale entries."
    )


def test_the_composed_sinks_actually_import_the_composition() -> None:
    """Guards the other half: membership in the composed set must be earned."""
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src"
    for rel in sorted(_COMPOSED_SINKS):
        text = (src / rel).read_text(encoding="utf-8")
        assert "compose_bypass_reply" in text, (
            f"{rel} is listed as a composed sink but does not reference "
            "compose_bypass_reply"
        )
