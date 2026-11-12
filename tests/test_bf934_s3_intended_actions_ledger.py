"""BF-934 (#1673) S3: every action a decision intended is carried out or recorded as dropped, with a reason, per agent and action.

Real: the think cycle, the extraction (the Ward Room, its router, Ship's Records, the DM path), the cognitive agent's lifecycle and a real EventLog on tmp_path, which is
the record the crew reconciles against Improvement Proposals. Doubles (tests/bf934_world.py): the model, the triage's handlers, and a thinker whose ``handle_intent``
answers the text a model wrote with the ``intended_actions`` metadata the lifecycle would attach. The classes hold the cases the unfixed tree fails; the functions before
them pass on both. No BF-934 name is imported at module level.
"""

from __future__ import annotations

import importlib
import logging
import re
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.cognitive_agent import _build_result_metadata
from probos.cognitive.sub_tasks.analyze import _build_thread_analysis_prompt, _build_situation_review_prompt
from probos.types import IntentResult
from tests.bf934_world import NothingIsNovel, crew, obeys_decision, think, thinker, threads, world

PROPOSAL = "[PROPOSAL]\nTitle: Cache the roster\nRationale: The roster is read forty times per cycle.\nAffected Systems: Ward Room\nPriority: low\n[/PROPOSAL]"
NOTEBOOK = "[NOTEBOOK roster-cache]\nThe roster is read 40 times per cycle.\n[/NOTEBOOK]"
REPEATED = "The roster is read forty times per cycle and never changes anywhere."
ACTION_TAGS = ["ward_room_post", "ward_room_reply", "endorse", "dm", "notebook", "proposal"]  # the tags an output carries out
OTHER_TAGS = ["silent", "speak_freely", "leadership_review", "oracle_query", "ward_room_lookup"]  # carried out by something else (see the registry)


def _built(name: str):
    """The module M2 builds. Until then this fails at its own assert, as the xfail marker requires (an ImportError would not)."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        assert False, f"{name} is built by M2"


async def _rows(w, event: str) -> list[dict]:
    """The EventLog rows of the intended_actions category, oldest first."""
    return list(reversed(await w.events.query_structured(category="intended_actions", event=event, limit=200)))


def _said(caplog, message: str) -> list[str]:
    """The levels at which the accounting module logged a line containing *message* (other loggers' lines are not counted)."""
    return [r.levelname for r in caplog.records if r.name == "probos.cognitive.action_accounting" and message in r.getMessage()]


async def _target(w, tag: str) -> str:
    """The reply, endorsement or DM block for *tag*, aimed at a thread and post Worf made (the others need none), or plain text for ``ward_room_post``."""
    science = await w.ws.get_channel_by_department("science")
    thread = await w.ws.create_thread(science.id, w.ids["security_officer"], "Coolant audit", "Loop B reads 41 C.", author_callsign="Worf")
    post = await w.ws.create_post(thread.id, w.ids["security_officer"], "Confirmed at 0300.", author_callsign="Worf")
    return {
        "ward_room_post": "The coolant audit needs a second reading.",
        "ward_room_reply": f"[REPLY {thread.id}]\nSecond reading agrees.\n[/REPLY]",
        "endorse": f"[ENDORSE {post.id} UP]",
        "dm": "[DM @Worf]\nThe coolant audit needs a second reading.\n[/DM]",
        "notebook": NOTEBOOK,
        "proposal": PROPOSAL,
    }[tag]


async def _carried_out(w, tag: str) -> bool:
    """Whether the world holds what carrying *tag* out leaves, read from the Ward Room and Ship's Records and not from the loop."""
    titles = await threads(w)
    if tag == "ward_room_post":
        return any(t.startswith("[Observation]") for t in titles)
    if tag == "dm":
        return any(t.startswith("[DM to @Worf]") for t in titles)
    if tag == "notebook":
        return w.notebook("Kira", "roster-cache").is_file()
    if tag == "proposal":
        return "[Proposal] Cache the roster" in titles
    science = await w.ws.get_channel_by_department("science")
    (thread,) = [th for th in await w.ws.list_threads(science.id, limit=50) if th.title == "Coolant audit"]
    posts = (await w.ws.get_thread(thread.id))["posts"]
    if tag == "ward_room_reply":
        return any(p.get("author_id") == w.ids["science_officer"] for p in posts)
    return any(p.get("net_score", 0) > 0 for p in posts)  # endorse


@pytest.mark.parametrize("tag", ACTION_TAGS)
async def test_control_each_action_a_think_is_asked_to_carry_out_is_carried_out_by_the_loop(tmp_path, tag):
    async with world(tmp_path, event_log=True) as w:
        await think(w, thinker(w, await _target(w, tag)))
        assert await _carried_out(w, tag)


@pytest.mark.parametrize("tag", ACTION_TAGS)
async def test_an_action_the_output_carries_leaves_no_drop(tmp_path, tag):
    async with world(tmp_path, event_log=True) as w:
        await think(w, thinker(w, await _target(w, tag), {"intended_actions": [tag]}))
        assert await _carried_out(w, tag) and await _rows(w, "dropped") == []


@pytest.mark.parametrize("tag", OTHER_TAGS)
async def test_a_tag_something_else_carries_out_never_has_a_drop(tmp_path, tag):
    async with world(tmp_path, event_log=True) as w:
        await think(w, thinker(w, "[NO_RESPONSE]", {"intended_actions": [tag]}))
        assert await _rows(w, "dropped") == []


async def test_a_decision_that_names_no_action_leaves_no_record(tmp_path):
    async with world(tmp_path, event_log=True) as w:
        agent, _ = await crew(w, ["silent"], obeys_decision)
        await think(w, agent)
        assert await _rows(w, "declared") == [] and await _rows(w, "dropped") == []


class TestEveryIntendedActionIsCarriedOutOrDropped:
    @pytest.mark.parametrize("tag", [t for t in ACTION_TAGS if t != "ward_room_post"])
    async def test_an_action_the_output_does_not_carry_is_dropped_with_a_reason_and_said(self, tmp_path, caplog, tag):
        async with world(tmp_path, event_log=True) as w:
            with caplog.at_level(logging.INFO, logger="probos.cognitive.action_accounting"):
                await think(w, thinker(w, "Only an observation.", {"intended_actions": [tag]}))
            rows = await _rows(w, "dropped")
            assert len(rows) == 1
            row = rows[0]
            assert row["agent_type"] == "science_officer" and row["correlation_id"] and row["data"]["intent_id"] == row["correlation_id"]
            assert (row["data"]["action"], row["data"]["reason"]) == (tag, "no_block_executed")
            assert _said(caplog, f"intended {tag} and nothing carried it out: no_block_executed") == ["WARNING"]

    async def test_an_observation_the_gates_withhold_is_dropped_too_but_only_noted(self, tmp_path, caplog):
        async with world(tmp_path, event_log=True) as w:
            with caplog.at_level(logging.INFO, logger="probos.cognitive.action_accounting"):
                await think(w, thinker(w, "[NO_RESPONSE]", {"intended_actions": ["ward_room_post"]}))
            rows = await _rows(w, "dropped")
            assert len(rows) == 1 and (rows[0]["data"]["action"], rows[0]["data"]["reason"]) == ("ward_room_post", "no_response")
            assert _said(caplog, "intended ward_room_post and nothing carried it out: no_response") == ["INFO"]

    async def test_a_notebook_entry_the_writer_declines_as_a_repeat_is_only_noted(self, tmp_path, caplog):
        async with world(tmp_path, event_log=True) as w:
            await think(w, thinker(w, NOTEBOOK, {"intended_actions": ["notebook"]}))
            assert await _rows(w, "dropped") == []
            with caplog.at_level(logging.INFO, logger="probos.cognitive.action_accounting"):
                await think(w, thinker(w, NOTEBOOK, {"intended_actions": ["notebook"]}))  # the same entry again: AD-550 declines it, by design
            assert _said(caplog, "intended notebook and nothing carried it out: content unchanged from recent entry") == ["INFO"]
            assert [r["data"]["by_design"] for r in await _rows(w, "dropped")] == [True]

    async def test_an_output_that_fails_to_think_drops_every_action_the_decision_named(self, tmp_path):
        async with world(tmp_path, event_log=True) as w:
            agent = thinker(w, "")

            async def failed(intent):
                return IntentResult(intent_id=intent.id, agent_id=agent.id, success=False, error="llm down", metadata={"intended_actions": ["proposal", "notebook"]})

            agent.handle_intent = failed
            await think(w, agent)
            assert [(r["data"]["action"], r["data"]["reason"]) for r in await _rows(w, "dropped")] == [("proposal", "think_failed"), ("notebook", "think_failed")]

    async def test_a_row_that_cannot_be_written_never_blocks_the_think(self, tmp_path, caplog, monkeypatch):
        async with world(tmp_path, event_log=True) as w:
            monkeypatch.setattr(w.events, "log", AsyncMock(side_effect=OSError("disk full")))
            with caplog.at_level(logging.WARNING, logger="probos.cognitive.action_accounting"):
                await think(w, thinker(w, "[NO_RESPONSE]", {"intended_actions": ["proposal"]}))
            assert "the dropped row for Kira (science_officer) was not recorded" in caplog.text

    @pytest.mark.parametrize("reply, how, intended, action, reason", [
        ('{"intents": [{"intent": "ward_room_post"}]}', None, ["proposal"], "proposal", "raw_intent_json"),
        (PROPOSAL, None, ["ward_room_post", "proposal"], "ward_room_post", "empty_after_extraction"),
        (f"[NO_RESPONSE]\n{PROPOSAL}", None, ["ward_room_post", "proposal"], "ward_room_post", "no_response"),
        (REPEATED, "similar", ["ward_room_post"], "ward_room_post", "similar_to_recent_post"),
        (REPEATED, "novelty", ["ward_room_post"], "ward_room_post", "not_novel"),
    ])
    async def test_each_exit_of_the_think_names_its_reason(self, tmp_path, monkeypatch, reply, how, intended, action, reason):
        async with world(tmp_path, event_log=True) as w:
            if how == "similar":
                monkeypatch.setattr(w.loop, "_is_similar_to_recent_posts", AsyncMock(return_value=True))
            if how == "novelty":
                w.loop.set_novelty_gate(NothingIsNovel())
            await think(w, thinker(w, reply, {"intended_actions": intended}))
            assert [(r["data"]["action"], r["data"]["reason"]) for r in await _rows(w, "dropped")] == [(action, reason)]

    async def test_the_observation_post_says_whether_a_thread_was_created(self, tmp_path, caplog, monkeypatch):
        async with world(tmp_path) as w:
            agent = thinker(w, "")
            assert await w.loop._post_to_ward_room(agent, "Observation one.") is True
            monkeypatch.setattr(w.ws, "list_channels", AsyncMock(return_value=[]))
            with caplog.at_level(logging.WARNING, logger="probos.proactive"):
                assert await w.loop._post_to_ward_room(agent, "Observation two.") is False
            assert "no channel to post the observation of science_officer" in caplog.text

    async def test_an_observation_no_channel_can_take_is_dropped_as_not_posted(self, tmp_path, monkeypatch):
        async with world(tmp_path, event_log=True) as w:
            monkeypatch.setattr(w.ws, "list_channels", AsyncMock(return_value=[]))
            await think(w, thinker(w, "The coolant audit needs a second reading.", {"intended_actions": ["ward_room_post"]}))
            assert [(r["data"]["action"], r["data"]["reason"]) for r in await _rows(w, "dropped")] == [("ward_room_post", "not_posted")]


class TestTheDecisionRecordReconcilesAgainstWhatWasPosted:
    async def test_decided_equals_posted_plus_dropped_per_agent_and_action(self, tmp_path):
        """The crew's reconciliation, from its three named sources: the decision record (events.db), Improvement Proposals (Ward Room) and the drop rows (events.db)."""
        async with world(tmp_path, event_log=True) as w:
            def another(request):  # A3: the same title again would be refused as a duplicate: the author already filed it
                return obeys_decision(request).replace("Cache the roster", "Index the roster")

            for answer in (obeys_decision, lambda request: "[NO_RESPONSE]", another):
                agent, _ = await crew(w, ["proposal", "notebook"], answer)
                await think(w, agent)
            decided = [r for r in await _rows(w, "declared") if "proposal" in r["data"]["intended"]]
            posted = await threads(w, "Improvement Proposals")
            dropped = [r for r in await _rows(w, "dropped") if r["data"]["action"] == "proposal"]
            assert len(decided) == 3 and len(posted) == 2 and len(dropped) == 1
            assert len(decided) == len(posted) + len(dropped)
            assert {r["correlation_id"] for r in dropped} <= {r["correlation_id"] for r in decided}  # a drop closes a decision made by the same think
            assert {r["agent_id"] for r in decided} == {w.ids["science_officer"]} and decided[0]["data"] == {
                "intended": ["proposal", "notebook"], "path": "single_call", "intent": "proactive_think",
                "intent_id": decided[0]["correlation_id"], "callsign": "Kira"}
            notebook = [r["data"]["reason"] for r in await _rows(w, "dropped") if r["data"]["action"] == "notebook"]
            assert sorted(notebook) == ["content unchanged from recent entry", "no_response"]  # a dedup is by design, and still counted
            assert [r["data"]["reason"] for r in await _rows(w, "dropped") if r["data"].get("by_design")] == ["content unchanged from recent entry"]

    async def test_a_decision_made_for_another_intent_is_not_recorded(self, tmp_path):
        async with world(tmp_path, event_log=True) as w:
            await _built("probos.cognitive.action_accounting").record_declared(
                w.rt, agent_id="agent-1", agent_type="science_officer", callsign="Kira", intent="ward_room_notification", intent_id="intent-1",
                intended=["ward_room_reply"], path="chain")
            assert await _rows(w, "declared") == []


class TestTheRegistryAndTheMetadata:
    def test_the_registry_holds_exactly_the_tags_the_analyze_prompts_offer(self):
        accounting = _built("probos.cognitive.action_accounting")
        offered: set[str] = set()
        for build in (_build_situation_review_prompt, _build_thread_analysis_prompt):
            _, user = build({"context": "x", "params": {}, "_agent_type": "science_officer"}, [], "Kira", "science")
            offered |= set(re.findall(r"[a-z_]+", re.search(r"JSON array from:\s*([a-z_,\s]+)\.", user).group(1)))
        assert offered == set(accounting.ACTION_TAGS) and set(ACTION_TAGS) | set(OTHER_TAGS) == offered
        assert {t for t, spec in accounting.ACTION_TAGS.items() if spec.evidence} == set(ACTION_TAGS)
        assert set(ACTION_TAGS) == set(_built("probos.cognitive.action_billets").BILLET_TAGS)  # the six S1's billet names (A1): two definitions, pinned equal
        assert all(accounting.ACTION_TAGS[t].how for t in OTHER_TAGS)

    @pytest.mark.parametrize("executed, reason, expected", [
        ([], "no_response", [("proposal", "no_response"), ("ward_room_post", "no_response")]),
        ([], "empty_after_extraction", [("proposal", "no_block_executed"), ("ward_room_post", "empty_after_extraction")]),
        ([{"type": "proposal"}], "not_posted", [("ward_room_post", "not_posted")]),
        ([{"type": "proposal"}, {"type": "ward_room_post"}], "not_posted", []),
        ([{"type": "proposal_suppressed", "reason": "missing_title"}, {"type": "ward_room_post"}], "not_posted", [("proposal", "missing_title")]),
    ])
    def test_what_nothing_carried_out_and_why(self, executed, reason, expected):
        drops = _built("probos.cognitive.action_accounting").unaccounted(["Proposal", "ward_room_post", "proposal", "silent", "no_such_tag"], executed, reason)
        assert sorted((d["action"], d["reason"]) for d in drops) == sorted(expected) and {d["type"] for d in drops} <= {"action_dropped"}

    def test_the_lifecycle_carries_the_decision_to_the_caller_bounded(self):
        assert _build_result_metadata({}, {}, {"_intended_actions": ["proposal", "notebook"]}) == {"intended_actions": ["proposal", "notebook"]}
        assert len(_build_result_metadata({}, {}, {"_intended_actions": ["x" * 90] * 40})["intended_actions"]) == 16
        assert _build_result_metadata({}, {}, {"_intended_actions": ["x" * 90]})["intended_actions"] == ["x" * 40]
        for none in ({}, {"_intended_actions": []}, {"_intended_actions": "proposal"}, {"_intended_actions": None}):
            assert "intended_actions" not in _build_result_metadata({}, {}, none)
