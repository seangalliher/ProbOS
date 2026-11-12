"""BF-934 (#1673) S2: no gate discards an action the output carries, and a proposal that is not filed says why.

Real: the think cycle, the action extraction, the Ward Room and its router, and the AD-643b re-reflect through AD-643a's routing. Doubles (tests/bf934_world.py): the triage's
ANALYZE and QUERY handlers, COMPOSE and REFLECT stand-ins below (no model call), a thinker whose ``handle_intent`` answers the text a model wrote, and a novelty gate that
finds everything repeated. The classes hold the cases the unfixed tree fails; the functions before them pass on both. No BF-934 name is imported at module level.
A3 (review round 1) adds four controls before the first class, which pass on both trees (T14 to T17), and two classes at the end, which S2's M3 head fails (T18 to T23): the actions of a
repeated output (an endorsement, a reply, a proposal) and a re-reflect that keeps the marker and loses the block. The one clock they read is BF-171's reply cooldown, which ``_elapse`` clears.
A4 (review round 2) changes what the reply guard calls the same reply (word for word, against the agent's newest post) and where it runs (after the commands the reply carries): one control before the
first class (T27) and the cases A3's head fails at the end (T24 to T26, T28). The Ward Room pipeline, the second caller of the reply extractor, is built here (``_pipeline``).
A5 (review round 3) wires what the world left out between the reply and the stored post, the content firewall as ``startup/finalize.py`` wires it (``_with_firewall``), because it puts a label
before the stored body of a flagged reply: the class at the end (T29 to T35) holds the cases A4's head fails (a flagged reply repeated on every cycle, the stored body read as the body given) and the controls around them.
"""

from __future__ import annotations

import importlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskType
from probos.mesh.intent import IntentBus
from probos.recreation.service import RecreationService
from probos.substrate.registry import AgentRegistry
from probos.ward_room.content_firewall import ContentFirewall
from probos.ward_room_pipeline import WardRoomPostPipeline
from probos.ward_room_router import WardRoomRouter
from tests.bf934_world import NothingIsNovel, crew, think, thinker, threads, world

PROPOSAL = "[PROPOSAL]\nTitle: Cache the roster\nRationale: The roster is read forty times per cycle.\nAffected Systems: Ward Room\nPriority: low\n[/PROPOSAL]"
NOTEBOOK = "[NOTEBOOK roster-cache]\nThe roster is read 40 times per cycle.\n[/NOTEBOOK]"
POSTED = "[Proposal] Cache the roster"
REPEATED = "The roster is read forty times per cycle and never changes anywhere."


def _built(name: str):
    """The module M2 builds. Until then this fails at its own assert, as the xfail marker requires (an ImportError would not)."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        assert False, f"{name} is built by M2"


class _Compose:
    async def __call__(self, spec, context, prior):
        return SubTaskResult(sub_task_type=SubTaskType.COMPOSE, name=spec.name, success=True, result={"output": f"Roster reads repeat.\n{PROPOSAL}"})


class _Reflect:
    """The first REFLECT keeps COMPOSE's output; the AD-643b re-reflect (the one handed the undeclared-action feedback) answers *second*."""

    def __init__(self, second: str) -> None:
        self.second = second

    async def __call__(self, spec, context, prior):
        kept = next((p.result["output"] for p in reversed(prior) if p.sub_task_type == SubTaskType.COMPOSE), "")
        output = self.second if context.get("_undeclared_action_feedback") else kept
        return SubTaskResult(sub_task_type=SubTaskType.REFLECT, name=spec.name, success=True, result={"output": output})


async def _undeclared_proposal(w, second):
    """Kira's triage intends only an observation; COMPOSE writes one with a proposal beside it (undeclared); the re-reflect answers *second*."""
    agent, _ = await crew(w, ["ward_room_post"], lambda request: "[NO_RESPONSE]")
    agent._sub_task_executor.register_handler(SubTaskType.COMPOSE, _Compose())
    agent._sub_task_executor.register_handler(SubTaskType.REFLECT, _Reflect(second))
    await think(w, agent)


async def test_control_a_valid_proposal_beside_an_observation_is_filed_beside_it(tmp_path):
    async with world(tmp_path) as w:
        await think(w, thinker(w, f"The roster is read too often.\n{PROPOSAL}"))
        assert sorted(await threads(w)) == sorted([POSTED, "[Observation] The roster is read too often."])


@pytest.mark.parametrize("reply", ["[NO_RESPONSE]", "[NO_RESPONSE]\n[PROPOSAL] Title: X [/PROPOSAL]", "[NO_RESPONSE]\n[PROPOSAL]\nTitle: X\n[/PROPOSAL]"])
async def test_a_withdrawn_output_without_a_valid_block_posts_nothing(tmp_path, reply):
    async with world(tmp_path) as w:
        await think(w, thinker(w, reply))
        assert await threads(w) == []


async def test_control_a_re_reflect_that_keeps_every_block_still_replaces_the_approved_output(tmp_path):
    async with world(tmp_path) as w:
        await _undeclared_proposal(w, f"Roster reads repeat, reworded.\n{PROPOSAL}")
        assert sorted(await threads(w)) == sorted([POSTED, "[Observation] Roster reads repeat, reworded."])


async def _worfs_thread(w):
    """A thread and a post Worf made in the science channel, for Kira to answer or to endorse."""
    science = await w.ws.get_channel_by_department("science")
    thread = await w.ws.create_thread(science.id, w.ids["security_officer"], "Coolant audit", "Loop B reads 41 C.", author_callsign="Worf")
    post = await w.ws.create_post(thread.id, w.ids["security_officer"], "Confirmed at 0300.", author_callsign="Worf")
    return thread, post


def _with_real_trust(w):
    """The world's router holds a MagicMock for trust; this one holds the loop's own TrustNetwork, so an endorsement's trust signal can be read."""
    w.rt.ward_room_router = WardRoomRouter(
        ward_room=w.ws, registry=MagicMock(spec=AgentRegistry), intent_bus=MagicMock(spec=IntentBus), trust_network=w.rt.trust_network,
        ontology=None, callsign_registry=w.rt.callsign_registry, episodic_memory=None, event_emitter=MagicMock(), event_log=AsyncMock(), config=w.rt.config,
    )
    return w.rt.trust_network


def _elapse(w):
    """Stand for the time between two cycles: BF-171's 120 s reply cooldown is the one clock the reply path reads, and no test sleeps."""
    w.loop._reply_cooldowns.clear()


class _ComposeNoRationale(_Compose):
    async def __call__(self, spec, context, prior):
        return SubTaskResult(sub_task_type=SubTaskType.COMPOSE, name=spec.name, success=True, result={"output": "Roster reads repeat.\n[PROPOSAL]\nTitle: Cache the roster\n[/PROPOSAL]"})


async def test_control_a_flipped_endorsement_still_counts_for_its_author(tmp_path):
    async with world(tmp_path) as w:
        trust = _with_real_trust(w)
        _, post = await _worfs_thread(w)
        worf = w.ids["security_officer"]
        alpha, beta = trust.get_or_create(worf).alpha, trust.get_or_create(worf).beta
        await think(w, thinker(w, f"[ENDORSE {post.id} UP]"))
        assert trust.get_or_create(worf).alpha > alpha and trust.get_or_create(worf).beta == beta
        await think(w, thinker(w, f"[ENDORSE {post.id} DOWN]"))
        assert trust.get_or_create(worf).beta > beta and (await w.ws.get_post(post.id))["net_score"] == -1


async def test_control_a_reply_that_says_something_new_is_still_posted(tmp_path):
    async with world(tmp_path) as w:
        thread, _ = await _worfs_thread(w)
        await w.ws.create_post(thread.id, w.ids["security_officer"], "Second reading agrees.", author_callsign="Worf")  # another crew member said it first
        new = "Loop B should be read again after the purge, not before."
        for body in ("Second reading agrees.", new):
            await think(w, thinker(w, f"[REPLY {thread.id}]\n{body}\n[/REPLY]"))
            _elapse(w)
        mine = [p["body"] for p in (await w.ws.get_thread(thread.id))["posts"] if p["author_id"] == w.ids["science_officer"]]
        assert mine == ["Second reading agrees.", new]


async def test_control_a_proposal_with_another_title_or_by_another_author_is_still_filed(tmp_path):
    async with world(tmp_path) as w:
        worf = SimpleNamespace(id=w.ids["security_officer"], agent_type="security_officer", callsign="Worf")
        for who, text in ((thinker(w, ""), PROPOSAL), (thinker(w, ""), PROPOSAL.replace("Cache the roster", "Index the roster")), (worf, PROPOSAL)):
            await w.loop._extract_and_execute_actions(who, text)
        assert sorted(await threads(w, "Improvement Proposals")) == sorted([POSTED, POSTED, "[Proposal] Index the roster"])


async def test_control_a_proposal_the_extractor_never_could_file_does_not_hold_a_rewrite_back(tmp_path):
    async with world(tmp_path) as w:
        agent, _ = await crew(w, ["ward_room_post"], lambda request: "[NO_RESPONSE]")
        agent._sub_task_executor.register_handler(SubTaskType.COMPOSE, _ComposeNoRationale())
        agent._sub_task_executor.register_handler(SubTaskType.REFLECT, _Reflect("Roster reads repeat, reworded.\n[PROPOSAL]\nTitle: Cache the roster\n[/PROPOSAL]"))
        await think(w, agent)
        assert await threads(w) == ["[Observation] Roster reads repeat, reworded."]


async def _kiras_replies(w, thread) -> list[str]:
    """The bodies of Kira's live posts in *thread*, sorted (the order of two posts made within one clock tick is not the point)."""
    posts = (await w.ws.get_thread(thread.id))["posts"]
    return sorted(p["body"] for p in posts if p["author_id"] == w.ids["science_officer"] and not p["deleted"])


def _pipeline(w) -> WardRoomPostPipeline:
    """The Ward Room pipeline, the second caller of the reply extractor, over the world's loop, router and Ward Room."""
    return WardRoomPostPipeline(
        ward_room=w.ws, ward_room_router=w.rt.ward_room_router, proactive_loop=w.loop, trust_network=w.rt.trust_network,
        callsign_registry=w.rt.callsign_registry, config=w.rt.config, runtime=w.rt,
    )


async def test_control_a_reply_that_differs_only_in_case_and_spacing_is_still_a_repeat(tmp_path):
    async with world(tmp_path) as w:
        thread, _ = await _worfs_thread(w)
        for body in ("Second reading agrees.", "SECOND   reading\nagrees."):
            await think(w, thinker(w, f"[REPLY {thread.id}]\n{body}\n[/REPLY]"))
            _elapse(w)
        assert await _kiras_replies(w, thread) == ["Second reading agrees."]


class TestNoGateDiscardsAnActionTheOutputCarries:
    @pytest.mark.parametrize("blocks", [PROPOSAL, NOTEBOOK, f"{PROPOSAL}\n{NOTEBOOK}"])
    async def test_a_withdrawn_observation_does_not_withdraw_a_valid_block(self, tmp_path, blocks):
        async with world(tmp_path) as w:
            await think(w, thinker(w, f"[NO_RESPONSE]\n{blocks}"))
            assert await threads(w) == ([POSTED] if "PROPOSAL" in blocks else [])  # and no thread whose text is the marker
            note = w.notebook("Kira", "roster-cache")
            assert note.is_file() == ("NOTEBOOK" in blocks) and (not note.is_file() or "read 40 times" in note.read_text(encoding="utf-8"))

    async def test_a_withdrawn_observation_stays_withdrawn_beside_a_valid_block(self, tmp_path):
        async with world(tmp_path) as w:
            await think(w, thinker(w, f"Roster reads repeat. [NO_RESPONSE]\n{PROPOSAL}"))
            assert await threads(w) == [POSTED]  # the proposal is filed; the observation the model withdrew is not posted

    async def test_a_proposal_attached_to_a_repeated_observation_is_still_filed(self, tmp_path, monkeypatch):
        async with world(tmp_path) as w:
            monkeypatch.setattr(w.loop, "_is_similar_to_recent_posts", AsyncMock(return_value=True))  # BF-032's verdict is the input here (L-S2-1)
            await think(w, thinker(w, f"{REPEATED}\n{PROPOSAL}"))
            assert await threads(w) == [POSTED]  # the repeat itself is still not posted

    async def test_a_notebook_entry_attached_to_a_rehashed_observation_is_still_written(self, tmp_path):
        async with world(tmp_path) as w:
            w.loop.set_novelty_gate(NothingIsNovel())
            await think(w, thinker(w, f"Rehashed again.\n{NOTEBOOK}"))
            note = w.notebook("Kira", "roster-cache")
            assert note.is_file() and "read 40 times" in note.read_text(encoding="utf-8")
            assert await threads(w) == []  # the rehash itself is still not posted

    @pytest.mark.parametrize("second", ["[NO_RESPONSE]", "Roster reads repeat."])
    async def test_a_re_reflect_may_not_remove_an_action_or_silence_an_approved_output(self, tmp_path, second):
        async with world(tmp_path) as w:
            await _undeclared_proposal(w, second)
            assert sorted(await threads(w)) == sorted([POSTED, "[Observation] Roster reads repeat."])

    @pytest.mark.parametrize("text, reason, said", [
        ("[PROPOSAL] Title: X Rationale: Y [/PROPOSAL]", "malformed_block", "Malformed [PROPOSAL] block"),
        ("[PROPOSAL]\nRationale: Y\n[/PROPOSAL]", "missing_title", "not posted: missing_title"),
        ("[PROPOSAL]\nTitle: X\n[/PROPOSAL]", "missing_rationale", "not posted: missing_rationale"),
    ])
    async def test_a_proposal_that_cannot_be_filed_says_so(self, tmp_path, caplog, text, reason, said):
        async with world(tmp_path) as w:
            with caplog.at_level(logging.WARNING, logger="probos.proactive"):
                _, actions = await w.loop._extract_and_execute_actions(thinker(w, ""), f"Observation.\n{text}")
            assert {"type": "proposal_suppressed", "reason": reason} in actions and not [a for a in actions if a["type"] == "proposal"]
            assert said in caplog.text and "Kira" in caplog.text
            assert await threads(w, "Improvement Proposals") == []

    @pytest.mark.parametrize("failure, reason", [("no_router", "no_router"), ("refused", "router_refused: Improvement Proposals channel not found"), ("raises", "post_failed: ValueError")])
    async def test_a_proposal_the_router_does_not_file_is_not_counted_as_filed(self, tmp_path, caplog, monkeypatch, failure, reason):
        async with world(tmp_path) as w:
            if failure == "no_router":
                w.rt.ward_room_router = None
            elif failure == "refused":
                monkeypatch.setattr(w.ws, "get_channel_by_name", AsyncMock(return_value=None))
            else:
                monkeypatch.setattr(w.ws, "create_thread", AsyncMock(side_effect=ValueError("Author is restricted from posting")))
            with caplog.at_level(logging.WARNING, logger="probos.proactive"):
                _, actions = await w.loop._extract_and_execute_actions(thinker(w, ""), f"Observation.\n{PROPOSAL}")
            assert {"type": "proposal_suppressed", "reason": reason} in actions and not [a for a in actions if a["type"] == "proposal"]
            assert f"not posted: {reason}" in caplog.text and "Kira" in caplog.text

    async def test_a_second_proposal_block_is_not_silently_dropped(self, tmp_path, caplog):
        async with world(tmp_path) as w:
            second = PROPOSAL.replace("Cache the roster", "Index the roster")
            with caplog.at_level(logging.WARNING, logger="probos.proactive"):
                _, actions = await w.loop._extract_and_execute_actions(thinker(w, ""), f"{PROPOSAL}\n{second}")
            assert await threads(w, "Improvement Proposals") == [POSTED]
            assert [a["title"] for a in actions if a["type"] == "proposal"] == ["Cache the roster"]
            assert "1 more [PROPOSAL] block(s)" in caplog.text


class TestOneReadingOfAProposalBlock:
    @pytest.mark.parametrize("text, problem", [
        ("Just an observation.", "no_block"),
        ("[PROPOSAL] Title: X Rationale: Y [/PROPOSAL]", "malformed_block"),
        ("[PROPOSAL]\nRationale: Y\n[/PROPOSAL]", "missing_title"),
        ("[PROPOSAL]\nTitle: X\n[/PROPOSAL]", "missing_rationale"),
        ("[PROPOSAL]  \n\nTitle: X\nRationale: Y  \n [/PROPOSAL]", ""),
    ])
    def test_the_problem_a_text_has(self, text, problem):
        assert _built("probos.cognitive.proposal_block").parse_proposal_block(text).problem == problem

    def test_a_valid_block_is_read_as_the_extractor_always_read_it(self):
        parsed = _built("probos.cognitive.proposal_block").parse_proposal_block(
            "Intro.\n[PROPOSAL]\nTitle: Improve dream consolidation\nRationale: Dream cycles discard low-weight memories\nthat could still be useful.\n"
            "Affected Systems: EpisodicMemory, DreamEngine\nPriority: HIGH\n[/PROPOSAL]\nOutro.\n[PROPOSAL]\nTitle: B\nRationale: C\n[/PROPOSAL]")
        assert (parsed.valid, parsed.found, parsed.title) == (True, True, "Improve dream consolidation")
        assert parsed.rationale == "Dream cycles discard low-weight memories\nthat could still be useful."
        assert (parsed.affected, parsed.priority, parsed.extra_blocks) == (("EpisodicMemory", "DreamEngine"), "high", 1)


class TestARepeatedOutputRepeatsNoEffect:
    async def test_the_ward_room_says_whether_an_endorsement_changed_the_stored_vote(self, tmp_path):
        async with world(tmp_path) as w:
            _, post = await _worfs_thread(w)
            kira = w.ids["science_officer"]
            votes = [await w.ws.endorse(target_id=post.id, target_type="post", voter_id=kira, direction=d) for d in ("up", "up", "down", "down", "unvote", "unvote")]
            assert [(v["voter_direction"], v.get("changed")) for v in votes] == [("up", True), ("up", False), ("down", True), ("down", False), ("none", True), ("none", False)]

    async def test_a_repeated_endorsement_earns_its_author_trust_once(self, tmp_path):
        async with world(tmp_path) as w:
            trust = _with_real_trust(w)
            _, post = await _worfs_thread(w)
            w.loop.set_novelty_gate(NothingIsNovel())  # every observation is a repeat; S2 carries the output's actions out all the same
            worf = w.ids["security_officer"]
            start, seen = trust.get_or_create(worf).alpha, []
            for _ in range(3):
                await think(w, thinker(w, f"{REPEATED}\n[ENDORSE {post.id} UP]"))
                seen.append(trust.get_or_create(worf).alpha)
            assert seen[0] > start  # the first vote counts
            assert seen[1] == pytest.approx(seen[0]) and seen[2] == pytest.approx(seen[0])  # the repeats do not
            assert (await w.ws.get_post(post.id))["net_score"] == 1

    async def test_a_reply_repeated_on_every_cycle_is_posted_once(self, tmp_path):
        async with world(tmp_path) as w:
            thread, _ = await _worfs_thread(w)
            w.loop.set_novelty_gate(NothingIsNovel())
            for _ in range(3):
                await think(w, thinker(w, f"{REPEATED}\n[REPLY {thread.id}]\nSecond reading agrees.\n[/REPLY]"))
                _elapse(w)
            posts = (await w.ws.get_thread(thread.id))["posts"]
            assert [p["body"] for p in posts if p["author_id"] == w.ids["science_officer"]] == ["Second reading agrees."]
            assert await threads(w) == ["Coolant audit"]  # the repeated observation itself is still not posted

    async def test_a_proposal_repeated_by_its_author_is_filed_once_and_says_why(self, tmp_path):
        async with world(tmp_path) as w:
            w.loop.set_novelty_gate(NothingIsNovel())
            for _ in range(3):
                await think(w, thinker(w, f"{REPEATED}\n{PROPOSAL}"))
            assert await threads(w, "Improvement Proposals") == [POSTED]
            again = PROPOSAL.replace("Cache the roster", "cache  THE roster")  # the same title as a person reads it
            _, actions = await w.loop._extract_and_execute_actions(thinker(w, ""), f"Observation.\n{again}")
            assert {"type": "proposal_suppressed", "reason": "router_refused: Proposal already filed"} in actions and not [a for a in actions if a["type"] == "proposal"]
            assert await threads(w, "Improvement Proposals") == [POSTED]

    def test_a_thread_of_another_shape_is_no_evidence_of_a_repeat(self):
        repeats = getattr(_built("probos.proactive"), "repeats_own_reply", None)
        assert repeats is not None, "repeats_own_reply is built by A3"
        mine = {"posts": [{"author_id": "kira", "body": "Second reading agrees.", "children": []}]}
        assert [repeats(t, "kira", "Second reading agrees.") for t in (None, {}, {"posts": None}, mine)] == [False, False, False, True]
        assert repeats(mine, "worf", "Second reading agrees.") is False  # another author's post is not mine
        assert repeats({"posts": [{**mine["posts"][0], "deleted": True}]}, "kira", "Second reading agrees.") is False  # a deleted post is not in the thread
        nested = {"posts": [{"author_id": "worf", "body": "Loop B reads 41 C.", "children": [{"author_id": "kira", "body": "Second reading agrees.", "children": []}]}]}
        assert repeats(nested, "kira", "Second reading agrees.") is True


class TestARewriteKeepsAProposalTheExtractorCanFile:
    @pytest.mark.parametrize("second", [
        "Roster reads repeat.\n[PROPOSAL]\nTitle: Cache the roster\nAffected Systems: Ward Room\nPriority: low\n[/PROPOSAL]",  # the Rationale is gone
        "Roster reads repeat.\n" + PROPOSAL.lower(),  # the marker matches in any case; the extractor reads only [PROPOSAL]
    ])
    async def test_a_re_reflect_may_not_leave_a_proposal_the_extractor_cannot_file(self, tmp_path, second):
        async with world(tmp_path) as w:
            await _undeclared_proposal(w, second)
            assert sorted(await threads(w)) == sorted([POSTED, "[Observation] Roster reads repeat."])


class TestAReplyIsARepeatOnlyWordForWord:
    async def test_a_reply_that_changes_a_value_is_posted(self, tmp_path):
        async with world(tmp_path) as w:
            thread, _ = await _worfs_thread(w)
            first = "Loop B coolant temperature is now 41 C and the purge is complete."
            second = first.replace("41 C", "49 C")  # the same words but one token: a changed measurement, not a repeat
            for body in (first, second):
                await think(w, thinker(w, f"[REPLY {thread.id}]\n{body}\n[/REPLY]"))
                _elapse(w)
            assert await _kiras_replies(w, thread) == sorted([first, second])

    async def test_a_reply_the_agent_took_back_is_posted_when_it_comes_back(self, tmp_path):
        async with world(tmp_path) as w:
            thread, _ = await _worfs_thread(w)
            said = ["The valve is open.", "Correction: the valve is closed.", "The valve is open."]  # the last says what the first said, after the thread changed
            for body in said:
                await think(w, thinker(w, f"[REPLY {thread.id}]\n{body}\n[/REPLY]"))
                _elapse(w)
            assert await _kiras_replies(w, thread) == sorted(said)

    @pytest.mark.parametrize("caller", ["think", "pipeline"])
    @pytest.mark.parametrize("command", ["[MOVE 5]", "[CHALLENGE @Worf tictactoe]"])
    async def test_a_repeated_reply_still_carries_out_the_command_it_brings(self, tmp_path, caller, command):
        async with world(tmp_path) as w:
            service = w.rt.recreation_service = RecreationService()
            thread, post = await _worfs_thread(w)
            if "MOVE" in command:
                await service.create_game("tictactoe", "Kira", "Worf")  # Kira to move
            said = "Loop B reads 41 C and the purge window is closed for the rest of the shift."
            for text in (said, f"{said} {command}"):
                reply = f"[REPLY {thread.id}]\n{text}\n[/REPLY]"
                if caller == "think":
                    await think(w, thinker(w, reply))
                else:
                    await _pipeline(w).process_and_post(agent=thinker(w, ""), response_text=reply, thread_id=thread.id, event_type="ward_room_post_created", post_id=post.id)
                _elapse(w)
            assert await _kiras_replies(w, thread) == [said]  # the prose is posted once
            assert [(g["challenger"], g["opponent"], g["moves_count"]) for g in service.get_active_games()] == [("Kira", "Worf", 1 if "MOVE" in command else 0)]  # and the command ran

    def test_only_the_agents_newest_live_post_is_the_one_a_reply_repeats(self):
        repeats = _built("probos.proactive").repeats_own_reply

        def post(body, at, author="kira", **more):
            return {"author_id": author, "body": body, "created_at": at, "children": [], **more}

        def thread_of(*posts):
            return {"posts": list(posts)}

        assert repeats(thread_of(post("Valve open.", 1), post("Valve closed.", 2)), "kira", "Valve open.") is False  # the agent took it back since
        assert repeats(thread_of(post("Valve closed.", 1), post("Valve open.", 2)), "kira", "Valve open.") is True
        assert repeats(thread_of(post("Valve open.", 1), post("Valve closed.", 2, deleted=True)), "kira", "Valve open.") is True  # the newest live post is the one that counts
        assert repeats(thread_of(post("Valve open.", 5), post("Valve closed.", 5)), "kira", "Valve open.") is False  # two newest posts that differ are no evidence
        assert repeats(thread_of(post("Valve open.", 5), post("Valve open.", 5)), "kira", "Valve open.") is True
        assert [repeats(thread_of(post("Valve open.", 1)), "kira", text) for text in ("  VALVE\nopen. ", "Valve open", "Valve open. ")] == [True, False, True]  # case and spacing aside, nothing else
        assert repeats(thread_of(post("", 1)), "kira", "") is False and repeats(thread_of(post("Valve open.", 1)), "kira", "   ") is False  # no words, no repeat
        assert repeats(thread_of(post("Valve open.", 1, author="worf")), "kira", "Valve open.") is False  # another author's post is not mine


LABEL = "[UNVERIFIED \u2014 "  # what the Ward Room puts before the body of a flagged post; the reasons and "] " follow (messages.py and threads.py hold the dash itself)
PHANTOM_LABEL = LABEL + "phantom_thread_ref] "
PURGE = "The purge is complete and Loop B reads 41 C."
PHANTOM = "As discussed in thread abc12345 the purge is complete and Loop B reads 41 C."  # a thread reference the thread does not hold: flagged phantom_thread_ref
HEX_AND_PHANTOM = "As discussed in thread abc12345 with refs deadbeef01 and cafebabe02 the purge is complete."  # flagged ungrounded_hex_ids and phantom_thread_ref
ECHO = PHANTOM_LABEL + PURGE  # a reply that itself begins with a label, as an agent that copies one writes it: not flagged, stored as written
FLAGGED_ECHO = PHANTOM_LABEL + PHANTOM  # the same, and flagged: stored with two labels


def _with_firewall(w) -> None:
    """The content firewall wired as ``startup/finalize.py`` wires it (the default ``FirewallConfig``, the loop's own TrustNetwork, one firewall for the posts and the threads), and the router
    holding that TrustNetwork too. The world builds neither, so a test that does not call this stores every body as it was given."""
    _with_real_trust(w)
    firewall = ContentFirewall(trust_network=w.rt.trust_network, emit_event_fn=w.rt.emit_event, config=w.rt.config.firewall)
    w.ws._messages.set_content_firewall(firewall)
    w.ws._threads.set_content_firewall(firewall)


def _strip_label():
    """The helper A5 builds. Until then this fails at its own assert, as the red run requires (an AttributeError would not)."""
    strip = getattr(importlib.import_module("probos.ward_room.content_firewall"), "strip_unverified_label", None)
    assert strip is not None, "strip_unverified_label is built by A5"
    return strip


async def _says(w, caller, thread, post, text) -> None:
    """One cycle in which Kira's whole output is a ``[REPLY]`` block holding *text*, through the think or through the Ward Room pipeline: the two callers of the reply extractor."""
    reply = f"[REPLY {thread.id}]\n{text}\n[/REPLY]"
    if caller == "think":
        await think(w, thinker(w, reply))
    else:
        await _pipeline(w).process_and_post(agent=thinker(w, ""), response_text=reply, thread_id=thread.id, event_type="ward_room_post_created", post_id=post.id)


class TestAFlaggedReplyIsStillARepeat:
    """A5: the content firewall puts ``[UNVERIFIED ...]`` before the stored body of a flagged reply, and the reply about to be posted does not carry it."""

    @pytest.mark.parametrize("caller", ["think", "pipeline"])
    @pytest.mark.parametrize("said, label", [
        pytest.param(PURGE, "", id="plain"),
        pytest.param(PHANTOM, PHANTOM_LABEL, id="one reason"),
        pytest.param(HEX_AND_PHANTOM, LABEL + "ungrounded_hex_ids, phantom_thread_ref] ", id="two reasons"),
        pytest.param(ECHO, "", id="label echo"),
        pytest.param(FLAGGED_ECHO, PHANTOM_LABEL, id="flagged label echo"),
    ])
    async def test_a_reply_repeated_on_every_cycle_is_posted_once_whatever_the_firewall_made_of_it(self, tmp_path, caller, said, label):
        async with world(tmp_path) as w:
            _with_firewall(w)
            thread, post = await _worfs_thread(w)
            counts = []
            for cycle in range(3):
                await _says(w, caller, thread, post, said)
                _elapse(w)
                mine = await _kiras_replies(w, thread)
                counts.append(len(mine))
                if cycle == 0:
                    assert mine == [label + said]  # first: the stored body carries the label this row says (none, one, or the echo's own), so the test fails here if the wiring stops flagging
            assert counts == [1, 1, 1]

    @pytest.mark.parametrize("caller", ["think", "pipeline"])
    async def test_a_flagged_reply_that_changes_a_value_is_still_posted(self, tmp_path, caller):
        async with world(tmp_path) as w:
            _with_firewall(w)
            thread, post = await _worfs_thread(w)
            changed = PHANTOM.replace("41 C", "49 C")  # the first reply grounds the thread reference, so the second is stored as it was said
            counts = []
            for cycle, text in enumerate((PHANTOM, changed, changed)):
                await _says(w, caller, thread, post, text)
                _elapse(w)
                mine = await _kiras_replies(w, thread)
                counts.append(len(mine))
                if cycle == 0:
                    assert mine == [PHANTOM_LABEL + PHANTOM]  # first: the stored body carries the label, so the test fails here, not at the counts, if the wiring stops flagging
            assert counts == [1, 2, 2]  # the changed value is a new reply and the repeat of it is not
            assert await _kiras_replies(w, thread) == sorted([PHANTOM_LABEL + PHANTOM, changed])

    @pytest.mark.parametrize("body, label, lowly", [
        pytest.param(PURGE, "", False, id="plain"),
        pytest.param(PHANTOM, PHANTOM_LABEL, False, id="one reason"),
        pytest.param(HEX_AND_PHANTOM, LABEL + "ungrounded_hex_ids, phantom_thread_ref] ", False, id="two reasons"),
        pytest.param(ECHO, "", False, id="label echo"),
        pytest.param(FLAGGED_ECHO, PHANTOM_LABEL, False, id="flagged label echo"),
        pytest.param("  " + FLAGGED_ECHO, PHANTOM_LABEL, False, id="flagged label echo after spaces"),
        pytest.param("  " + PURGE + "  ", "", False, id="padded"),
        pytest.param("Line one.\nLine two reads 41 C.\n\nLine four.", "", False, id="multi-line"),
        pytest.param("Caf\u00e9 \u2014 r\u00e9sum\u00e9 reads 41\u00b0C \u2603", "", False, id="unicode"),
        pytest.param("[Observation] " + PURGE, "", False, id="bracket-prefixed"),
        pytest.param(("The purge is complete. " * 300)[:6000], "", False, id="6000 characters"),
        pytest.param("The system showed 50ms baseline with 200ms spikes and \u00b13.2% variance in throughput.", LABEL + "fabricated_metrics] ", True, id="fabricated metrics"),
    ])
    async def test_the_body_the_ward_room_stores_reads_as_the_body_it_was_given(self, tmp_path, body, label, lowly):
        read = _built("probos.proactive")._as_read
        async with world(tmp_path) as w:
            _with_firewall(w)
            thread, _ = await _worfs_thread(w)
            kira = w.ids["science_officer"]
            if lowly:
                w.rt.trust_network.record_outcome(kira, False)  # the firewall reads a body for fabricated metrics only below 0.45, and a fresh author holds 0.5
            await w.ws.create_post(thread.id, kira, body, author_callsign="Kira")
            (stored,) = await _kiras_replies(w, thread)
            assert stored == label + body  # first: the label is the only change the store makes, and it is there when the firewall flags the body
            assert read(stored) == read(body)

    async def test_the_label_on_a_thread_body_is_the_one_the_helper_removes(self, tmp_path):
        async with world(tmp_path) as w:
            _with_firewall(w)
            science = await w.ws.get_channel_by_department("science")
            thread = await w.ws.create_thread(science.id, w.ids["science_officer"], "Purge", PHANTOM, author_callsign="Kira")
            assert thread.body == PHANTOM_LABEL + PHANTOM  # create_thread is the label's other producer (ward_room/threads.py)
            assert _strip_label()(thread.body) == PHANTOM

    def test_every_leading_label_goes_and_the_spacing_after_it(self):
        strip = _strip_label()
        rows = {
            "one label": (PHANTOM_LABEL + PURGE, PURGE),
            "two reasons": (LABEL + "ungrounded_hex_ids, phantom_thread_ref] " + PURGE, PURGE),
            "two labels": (PHANTOM_LABEL + LABEL + "fabricated_metrics] " + PURGE, PURGE),
            "two labels on two lines": (PHANTOM_LABEL.strip() + "\n" + LABEL + "fabricated_metrics]\n" + PURGE, PURGE),
            "a label after spaces": ("  " + PHANTOM_LABEL + PURGE, PURGE),
            "a label alone": (PHANTOM_LABEL.strip(), ""),
        }
        assert {name: strip(given) for name, (given, _) in rows.items()} == {name: want for name, (_, want) in rows.items()}

    def test_nothing_that_is_not_a_leading_label_is_touched(self):
        strip = _strip_label()
        kept = [
            PURGE,
            "  " + PURGE + "  ",  # no label: the text is returned as it is, spacing included
            "The purge " + PHANTOM_LABEL + "is complete.",  # a label inside the text
            "[Observation] " + PURGE,  # another bracket
            "[UNVERIFIED: no independent corroboration found] " + PURGE,  # social verification's own text: a colon, no dash
            "[UNVERIFIED - phantom_thread_ref] " + PURGE,  # a hyphen is not the label's dash
            "[unverified \u2014 phantom_thread_ref] " + PURGE,  # the case is the label's
            LABEL + "phantom_thread_ref " + PURGE,  # no closing bracket
        ]
        assert [strip(text) for text in kept] == kept

    def test_removing_the_labels_twice_changes_nothing(self):
        strip = _strip_label()
        for text in (PURGE, PHANTOM_LABEL + PURGE, PHANTOM_LABEL + LABEL + "fabricated_metrics] " + PURGE, PHANTOM_LABEL.strip(), ""):
            assert strip(strip(text)) == strip(text)
