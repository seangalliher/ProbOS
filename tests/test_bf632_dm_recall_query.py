"""BF-632: the per-message DM recall query must be the RAW Captain message.

Root cause (proven 2026-06-18 via the BF-631 DM-recall diagnostic on the live
runtime): the HXI router (``routers/agents.py:agent_chat``) PREPENDS the
visual-context block (AD-733a), project preamble (AD-793), and targeted-recall
block (AD-725) onto ``params['text']`` so the receiving agent's LLM sees them.
``_recall_relevant_memories`` then used ``params['text'][:200]`` as the episodic
recall query -- which, post-prepend, is the *visual scene description*
("--- Current Visual Context --- Most recent observation ..."), NOT what the
Captain asked. Every 1:1 recall searched for the room, never the words, so the
dog episodes (and everything else the Captain actually said) never surfaced.

BF-632 threads the raw ``req.message`` through as ``params['captain_message']``
and ``_dm_recall_query`` prefers it, falling back to ``text`` for callers that
don't set it.
"""

from __future__ import annotations

from probos.cognitive.cognitive_agent import _dm_recall_query

_VISUAL = (
    "--- Current Visual Context ---\n"
    "Most recent observation (14h ago): the Captain is in the chair, graphic "
    "shirt, a wall of framed pictures behind him.\n--- End Visual Context ---\n\n"
)
_ASK = "What do you know about my dogs?"


def test_prefers_raw_captain_message_over_prepended_text() -> None:
    # text leads with the visual block (the live bug); captain_message is clean
    params = {"text": _VISUAL + _ASK, "captain_message": _ASK}
    assert _dm_recall_query(params) == _ASK


def test_without_captain_message_falls_back_to_text() -> None:
    # work-item dispatch path: text is already the raw task, no captain_message
    params = {"text": "Investigate the warp core anomaly"}
    assert _dm_recall_query(params) == "Investigate the warp core anomaly"


def test_contaminated_text_alone_would_yield_the_visual_block() -> None:
    # Demonstrates the bug: without captain_message, the query is the scene.
    params = {"text": _VISUAL + _ASK}
    q = _dm_recall_query(params)
    assert q.startswith("--- Current Visual Context ---")
    assert _ASK not in q  # the Captain's actual words are pushed past 200 chars


def test_truncates_to_200_and_strips() -> None:
    # Truncate-then-strip (mirrors the prior text[:200].strip() shape).
    assert _dm_recall_query({"captain_message": "x" * 500}) == "x" * 200
    assert _dm_recall_query({"captain_message": "   hello there   "}) == "hello there"


def test_empty_captain_message_falls_back_to_text() -> None:
    params = {"text": "fallback text here", "captain_message": ""}
    assert _dm_recall_query(params) == "fallback text here"


def test_empty_params() -> None:
    assert _dm_recall_query({}) == ""
