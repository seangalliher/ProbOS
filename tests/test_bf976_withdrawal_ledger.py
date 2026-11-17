"""BF-976 (#1807): a judged withdrawal is recorded apart from a lost action, its line does not reach the Ward Room, and a retried think settles once.

Real: the think cycle, the extraction, the Ward Room and Ship's Records on tmp_path, an EventLog on tmp_path and, where a case calls ``crew``, the cognitive
agent's lifecycle with the single call. Doubles (tests/bf934_world.py): the model, the triage's handlers, and a thinker whose ``handle_intent`` answers a fixed
text with the ``intended_actions`` metadata the lifecycle would attach. The ``built`` cases fail on the base at their own assert; the two controls pass on both.
b9, which R2 added, is neither: its docstring says which of its cases pass on the base.
No name that M2 adds is imported at module level. Each docstring names the mutation rows (contract section 8.3) the case kills.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import probos.cognitive.action_accounting as accounting
import probos.cognitive.action_billets as billets
import probos.proactive as proactive
from probos.protocols import EventLogQuerySpec
from probos.types import IntentResult
from tests.bf934_world import DECIDED, crew, think, thinker, threads, world

def built(func):
    """The built cases failed on the base at their own assert and pass now; the marker is a no-op."""
    return func

PROPOSAL = "[PROPOSAL]\nTitle: Cache the roster\nRationale: The roster is read forty times per cycle.\nAffected Systems: Ward Room\nPriority: low\n[/PROPOSAL]"
WITHDRAWAL = "[NO_RESPONSE]\n[WITHDRAWN] evidence changed"
EMOJI = "\U0001F600"  # a code point outside the BMP: 4 bytes in UTF-8, 12 as a JSON ASCII escape
NOTEBOOK = "[NOTEBOOK roster-cache]\nRoster reads repeat: read 40 times per cycle.\n[/NOTEBOOK]"
MARKER = "[WITHDRAWN] evidence changed"


def _parser():
    """M2's parser. Until then this fails at its own assert, as the xfail marker requires."""
    parse = getattr(billets, "withdrawal_reason", None)
    assert parse is not None, "withdrawal_reason is built by M2"
    return parse


async def _rows(w, event: str) -> list[dict]:
    """The EventLog rows of the intended_actions category, oldest first."""
    return list(reversed(await w.events.query_structured(category="intended_actions", event=event, limit=200)))


def _drops(rows: list[dict]) -> list[tuple[str, str, str | None]]:
    return [(r["data"]["action"], r["data"]["reason"], r["data"].get("withdrawal")) for r in rows]


async def _ward_room_text(w) -> list[str]:
    """Every thread's title and body and every post's body, in every channel."""
    texts: list[str] = []
    for channel in await w.ws.list_channels():
        for thread in await w.ws.list_threads(channel.id, limit=500):
            texts += [thread.title, thread.body]
            texts += [str(post.get("body", "")) for post in (await w.ws.get_thread(thread.id))["posts"]]
    return texts


def _said(caplog, message: str) -> list[str]:
    """The levels at which the accounting module logged a line containing *message*."""
    return [r.levelname for r in caplog.records if r.name == "probos.cognitive.action_accounting" and message in r.getMessage()]


class _InstantBackoff:
    """``probos.proactive``'s ``asyncio`` with AD-576b's backoff made instant and recorded; every other name is asyncio's own."""

    def __init__(self, slept: list[float]) -> None:
        self._slept = slept

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)

    async def sleep(self, delay: float, result: Any = None) -> Any:
        self._slept.append(delay)
        return result


async def test_control_a_bare_silence_after_a_proposal_billet_is_still_no_response(tmp_path):
    """Rows R2 and R12."""
    async with world(tmp_path, event_log=True) as w:
        agent, model = await crew(w, ["proposal"], lambda request: "[NO_RESPONSE]")
        await think(w, agent)
        assert len(model.requests) == 1 and DECIDED in model.requests[0].prompt and len(await _rows(w, "declared")) == 1  # premise
        assert _drops(await _rows(w, "dropped")) == [("proposal", "no_response", None)]


async def test_control_a_retried_think_declares_once_per_attempt_under_one_correlation_id_and_settles_once(tmp_path, monkeypatch):
    """Row R16. Passes on the base: it pins AD-576b's retry as #1673's re-measure reads it (the latest declared row per agent and correlation id)."""
    slept: list[float] = []
    monkeypatch.setattr(proactive, "asyncio", _InstantBackoff(slept))
    settled: list[str] = []
    real_settle = proactive.settle_intended_actions

    async def settle(*args: Any, **kwargs: Any) -> Any:
        settled.append(args[5])  # the reason: every call site passes it as the sixth positional argument
        return await real_settle(*args, **kwargs)

    monkeypatch.setattr(proactive, "settle_intended_actions", settle)
    async with world(tmp_path, event_log=True) as w:
        agent, model = await crew(w, ["proposal"], lambda request: "[NO_RESPONSE]")
        real = agent.handle_intent
        attempts: list[IntentResult] = []

        async def flaky(intent: Any) -> IntentResult:
            result = await real(intent)  # the triage runs and writes its declared row
            attempts.append(result)
            if len(attempts) == 1:  # a transient model error after the triage: AD-576b retries it
                return IntentResult(intent_id=intent.id, agent_id=agent.id, success=False, error="LLM connection error", metadata=result.metadata)
            return result

        agent.handle_intent = flaky
        await think(w, agent)
        assert len(attempts) == 2 and len(model.requests) == 2 and slept == [0.5]  # premise: two attempts, one backoff, no wall-clock wait
        assert attempts[0].metadata.get("intended_actions") == ["proposal"]
        declared = await _rows(w, "declared")
        assert len(declared) == 2 and {r["data"]["path"] for r in declared} == {"single_call"}
        assert len({r["correlation_id"] for r in declared}) == 1
        assert settled == ["no_response"]
        dropped = await _rows(w, "dropped")
        assert _drops(dropped) == [("proposal", "no_response", None)] and dropped[0]["correlation_id"] == declared[0]["correlation_id"]


@built
async def test_a_withdrawal_after_a_proposal_billet_is_recorded_as_withdrawn_with_its_reason(tmp_path):
    """The issue's first acceptance case. Rows R6, R7, R8, R9 and R11 (the issue's own: the withdrawal mapped back to no_response)."""
    async with world(tmp_path, event_log=True) as w:
        agent, model = await crew(w, ["proposal"], lambda request: WITHDRAWAL if DECIDED in request.prompt else "[NO_RESPONSE]")
        await think(w, agent)
        declared = await _rows(w, "declared")
        assert len(model.requests) == 1 and DECIDED in model.requests[0].prompt and len(declared) == 1  # premise: the billet's call answered
        assert "[WITHDRAWN]" in model.requests[0].prompt  # the billet teaches the line
        dropped = await _rows(w, "dropped")
        assert _drops(dropped) == [("proposal", "withdrawn", "evidence changed")]
        assert dropped[0]["correlation_id"] == declared[0]["correlation_id"] and dropped[0]["detail"] == "Kira intended proposal: withdrawn"
        assert await threads(w) == []


@built
@pytest.mark.parametrize("reply", [
    WITHDRAWAL,
    "[NO_RESPONSE] [WITHDRAWN] evidence changed",
    "[WITHDRAWN] evidence changed",
    "The coolant loop needs a second reading, said the log.\n[WITHDRAWN] evidence changed",
])
async def test_the_withdrawal_line_never_reaches_the_ward_room(tmp_path, reply):
    """The issue's second acceptance case. Rows R7, R8, R9, R11; R13 (the two replies without the token)."""
    async with world(tmp_path, event_log=True) as w:
        await think(w, thinker(w, reply, {"intended_actions": ["proposal"]}))
        assert _drops(await _rows(w, "dropped")) == [("proposal", "withdrawn", "evidence changed")]
        assert await threads(w) == [] and not any("evidence changed" in text for text in await _ward_room_text(w))


@built
@pytest.mark.parametrize("token", ["[NO_RESPONSE]\n", ""])
async def test_a_withdrawal_beside_a_valid_block_files_the_block_and_records_the_rest_as_withdrawn(tmp_path, token):
    """The settle at proactive.py:1569. Rows R3, R7, R8, R9, R15; R13 and R14 (the reply without the token)."""
    async with world(tmp_path, event_log=True) as w:
        reply = f"{token}[WITHDRAWN] the notebook entry can wait\n{PROPOSAL}"
        await think(w, thinker(w, reply, {"intended_actions": ["proposal", "notebook"]}))
        assert await threads(w) == ["[Proposal] Cache the roster"]
        assert _drops(await _rows(w, "dropped")) == [("notebook", "withdrawn", "the notebook entry can wait")]
        assert not any("can wait" in text for text in await _ward_room_text(w))


@built
async def test_a_withdrawal_is_logged_at_info_and_its_text_stays_out_of_the_log(tmp_path, caplog):
    """Rows R7, R10 and R11."""
    async with world(tmp_path, event_log=True) as w:
        with caplog.at_level(logging.INFO, logger="probos.cognitive.action_accounting"):
            await think(w, thinker(w, WITHDRAWAL, {"intended_actions": ["proposal"]}))
        assert _said(caplog, "intended proposal and nothing carried it out: withdrawn") == ["INFO"]
        assert not any("evidence changed" in r.getMessage() for r in caplog.records if r.name == "probos.cognitive.action_accounting")


@built
@pytest.mark.parametrize("text, reason", [
    (WITHDRAWAL, "evidence changed"),
    ("[NO_RESPONSE]", None),
    ("", None),
    ("[NO_RESPONSE]\n[WITHDRAWN]", ""),
    ("[NO_RESPONSE]\n[WITHDRAWN] \t evidence\x00 changed \r\nThe next line.", "evidence changed"),
    ("[WITHDRAWN] first reason\n[WITHDRAWN] second reason", "first reason"),
    ("[NO_RESPONSE]\n[withdrawn] lower case", None),
    ("[NO_RESPONSE] [WITHDRAWN] on the same line", "on the same line"),
    ("[WITHDRAWN] one\u2028two", "one two"),
])
def test_the_parser_reads_the_first_withdrawal_line(text, reason):
    """Rows R1, R2, R3 and R4."""
    assert _parser()(text) == reason


@built
@pytest.mark.parametrize("body, reason", [
    ("evidence changed, " * 30, ("evidence changed, " * 12)[:200]),
    (EMOJI * 300, EMOJI * 200),
])
def test_the_reason_is_cut_to_200_code_points(body, reason):
    """Row R5."""
    assert getattr(billets, "WITHDRAWAL_REASON_CHARS", None) == 200
    assert _parser()("[WITHDRAWN] " + body) == reason and len(reason) == 200


@built
async def test_a_longest_reason_of_four_byte_characters_is_stored_and_read_back_whole(tmp_path):
    """The row-size bound of D3. Rows R5, R7, R8 and R9."""
    assert "withdrawal" in inspect.signature(accounting.settle_intended_actions).parameters
    reason = _parser()("[WITHDRAWN] " + EMOJI * 300)
    async with world(tmp_path, event_log=True) as w:
        drops = await accounting.settle_intended_actions(
            w.rt, thinker(w, ""), "intent-1", {"intended_actions": ["proposal"]}, [], "withdrawn", withdrawal=reason)
        assert [(d["action"], d["reason"], d.get("withdrawal")) for d in drops] == [("proposal", "withdrawn", EMOJI * 200)]
        assert _drops(await _rows(w, "dropped")) == [("proposal", "withdrawn", EMOJI * 200)]
        now = datetime.now(timezone.utc)
        batch = await w.events.query_governed(EventLogQuerySpec(
            start_time=now - timedelta(hours=1), end_time=now + timedelta(minutes=1), category="intended_actions", event="dropped", correlation_id=None,
            agent_id=None, limit=10, order="oldest_first", aggregate="none"))
        assert batch.truncated is False and [row.data["withdrawal"] for row in batch.rows] == [EMOJI * 200]


@built
def test_the_billet_teaches_the_withdrawal_line_and_its_reason():
    """Row R6."""
    assert getattr(billets, "WITHDRAWN_MARKER", None) == "[WITHDRAWN]"
    billet = billets.decision_billet(["proposal"])
    assert "withdraw it: write [NO_RESPONSE] on one line and, on the next, [WITHDRAWN] followed by one plain sentence on why." in billet
    assert "That withdrawal is recorded with its reason." in billet and "answer exactly [NO_RESPONSE]; that withdrawal is recorded." not in billet


@pytest.mark.parametrize("reply, expected_threads, expected_drops", [
    (PROPOSAL.replace("Cache the roster", MARKER), ["[Proposal] [WITHDRAWN] evidence changed"], [("notebook", "no_block_executed", None)]),
    (PROPOSAL.replace("per cycle.", f"per cycle.\n{MARKER}"), ["[Proposal] Cache the roster"], [("notebook", "no_block_executed", None)]),
    (NOTEBOOK.replace("per cycle.", f"per cycle.\n{MARKER}"), [], [("proposal", "no_block_executed", None)]),
    (f"[PROPOSAL]\nRationale: The roster is read forty times per cycle.\n{MARKER}\n[/PROPOSAL]", [], [("proposal", "missing_title", None), ("notebook", "no_block_executed", None)]),
    ("Roster reads repeat.\n" + PROPOSAL.replace("Cache the roster", MARKER), ["[Observation] Roster reads repeat.", "[Proposal] [WITHDRAWN] evidence changed"], [("notebook", "no_block_executed", None)]),
    (PROPOSAL.replace("Cache the roster", MARKER) + "\n[WITHDRAWN] the notebook entry can wait", ["[Proposal] [WITHDRAWN] evidence changed"], [("notebook", "withdrawn", "the notebook entry can wait")]),
    (PROPOSAL.replace("[PROPOSAL]\n", "[PROPOSAL] ").replace("per cycle.", f"per cycle.\n{MARKER}"), [], [("proposal", "withdrawn", "evidence changed"), ("notebook", "withdrawn", "evidence changed")]),
    ("[WITH" + PROPOSAL + "DRAWN] evidence changed", ["[Observation] evidence changed", "[Proposal] Cache the roster"], [("notebook", "no_block_executed", None)]),
    ("[WITH" + NOTEBOOK + "DRAWN] evidence changed", ["[Observation] evidence changed"], [("proposal", "no_block_executed", None)]),
    ("[WITHDRAWN] first part " + PROPOSAL + " trailing text", ["[Proposal] Cache the roster"], [("notebook", "withdrawn", "first part")]),
    (f"[PROPOSAL]\nTitle: Cache the roster\n{MARKER}{NOTEBOOK}[/PROPOSAL]", [], [("proposal", "malformed_block", None)]),
    (f"Roster reads repeat.\n[PROPOSAL]\nTitle: Cache the roster\nRationale: The roster is read forty times per cycle.{NOTEBOOK}[/PROPOSAL]\nAffected Systems: Ward Room\n{MARKER}\n[/PROPOSAL]",
     ["[Observation] Roster reads repeat.", "[Proposal] Cache the roster"], []),
    ("[WITHDRAWN] first\x0csecond", [], [("proposal", "withdrawn", "first second"), ("notebook", "withdrawn", "first second")]),
], ids=["in-title", "in-rationale", "in-notebook", "refused-block", "with-observation", "inside-and-beside", "unmatched-block", "split-by-proposal", "split-by-notebook", "reason-before-block",
        "closer-after-notebook", "early-closer-after-notebook", "form-feed-in-reason"])
async def test_a_marker_inside_a_proposal_or_notebook_block_is_that_blocks_own_text(tmp_path, reply, expected_threads, expected_drops):
    """Review rounds 1 and 2, F1 and F2. A marker inside a strict proposal block (filed or refused) or a notebook block withdraws nothing: the block is carried out as written,
    the observation beside it is judged as before and an action nothing carried out is lost, not withdrawn. A marker beside the blocks still decides (inside-and-beside),
    and a proposal that the extractor's pattern does not match is no block (unmatched-block). A removed block reaches the parser as a line break, so that a marker the model did
    not write does not form across it (split-by-proposal, split-by-notebook) and a reason ends where a removed block begins (reason-before-block). While the blocks are found it
    is a form feed, because the extractor joins the text around a removed notebook block and a line break there made a closer that the joined text lacks (closer-after-notebook:
    the marker is outside any block, so the reply withdraws) and closed a block early that the joined text closes later (early-closer-after-notebook: the marker is inside it,
    so the observation is posted). A form feed that the model wrote is a space, as the parser reads it (form-feed-in-reason). On the base every case passes except inside-and-beside,
    unmatched-block, reason-before-block, closer-after-notebook and form-feed-in-reason, which need the withdrawal line; the others pin what the base does. On the tree of R6,
    which joined the text around a removed block, split-by-proposal, split-by-notebook and reason-before-block fail; on the tree of R7, which left a line break,
    closer-after-notebook and early-closer-after-notebook fail. Rows R17 to R25."""
    async with world(tmp_path, event_log=True) as w:
        await think(w, thinker(w, reply, {"intended_actions": ["proposal", "notebook"]}))
        assert sorted(await threads(w)) == sorted(expected_threads)
        assert _drops(await _rows(w, "dropped")) == expected_drops
