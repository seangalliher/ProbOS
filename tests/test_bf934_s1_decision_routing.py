"""BF-934 (#1673) S1: a triage that decided to file a proposal or write a notebook entry hands the decision to the call that writes the output.

The real think cycle runs end to end (``ProactiveCognitiveLoop._think_for_agent`` into ``CognitiveAgent.handle_intent``: AD-643a's routing, the single call, the
real extraction, the real Ward Room and Ship's Records on tmp_path). The model double obeys a decision it is shown and otherwise answers ``[NO_RESPONSE]``, the single
call's default (the issue's own cases); the triage's ANALYZE and QUERY handlers are doubles (tests/bf934_world.py). The classes hold the cases the unfixed tree
fails; the functions before them pass on both, except the pin of A1's constant (``BILLET_TAGS``), which S1's M3 head fails. No BF-934 name is imported at module level. A1
(review round 1) added two classes at the end, which S1's M3 head fails, and before the first class two controls that pass on both trees and that pin: the billet repeats no
word of the triage, and a decision belongs to the turn whose triage made it.
"""

from __future__ import annotations

import importlib
import re
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.sub_task import SubTaskError, SubTaskResult, SubTaskType
from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt, _build_thread_analysis_prompt
from probos.cognitive.sub_tasks.compose import _build_proactive_compose_prompt
from tests.bf934_world import BLOCKS, DECIDED, crew, obeys_decision, observation, think, threads, world

CLOSING = "Include your justification. Otherwise respond with exactly: [NO_RESPONSE]"  # the single call's last line for a free-form think


def _built(name: str):
    """The module M2 builds. Until then this fails at its own assert, as the xfail marker requires (an ImportError would not)."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        assert False, f"{name} is built by M2"


async def test_control_a_model_that_writes_the_blocks_has_them_posted_and_written(tmp_path):
    async with world(tmp_path) as w:
        agent, _ = await crew(w, ["proposal", "notebook"], lambda request: BLOCKS)
        await think(w, agent)
        assert await threads(w, "Improvement Proposals") == ["[Proposal] Cache the roster"]
        assert "read 40 times" in w.notebook("Kira", "roster-cache").read_text(encoding="utf-8")


@pytest.mark.parametrize("intended", [["silent"], ["oracle_query"], ["leadership_review"], ["speak_freely"]])
async def test_a_decision_that_names_no_proposal_or_notebook_leaves_the_single_call_as_it_was(tmp_path, intended):
    async with world(tmp_path) as w:
        agent, model = await crew(w, intended, obeys_decision)
        decision = await agent.decide(observation())
        if intended == ["silent"]:
            assert decision["llm_output"] == "[NO_RESPONSE]" and model.requests == []
        else:
            assert len(model.requests) == 1 and DECIDED not in model.requests[0].prompt
            assert model.requests[0].prompt.endswith(CLOSING)


async def test_a_decision_does_not_outlive_its_turn(tmp_path):
    async with world(tmp_path) as w:
        agent, model = await crew(w, ["proposal"], obeys_decision)
        agent._sub_task_executor.execute = AsyncMock(side_effect=SubTaskError("triage timed out"))
        reused = observation()
        reused["_intended_actions"] = ["proposal"]  # what an earlier triage left on a dict that is used again
        await agent.decide(reused)
        assert len(model.requests) == 1 and DECIDED not in model.requests[0].prompt


def _offered_tags() -> set[str]:
    """The tags the two ANALYZE prompts offer for ``intended_actions`` (slice 3's registry test reads the same two prompts)."""
    offered: set[str] = set()
    for build in (_build_situation_review_prompt, _build_thread_analysis_prompt):
        _, user = build({"context": "x", "params": {}, "_agent_type": "science_officer"}, [], "Kira", "science")
        offered |= set(re.findall(r"[a-z_]+", re.search(r"JSON array from:\s*([a-z_,\s]+)\.", user).group(1)))
    return offered


def test_the_tags_a_billet_names_are_the_six_the_analyze_prompts_offer_for_them():
    billets = _built("probos.cognitive.action_billets")
    assert set(billets.BILLET_TAGS) == {"proposal", "notebook", "ward_room_post", "ward_room_reply", "endorse", "dm"}
    assert set(billets.BILLET_TAGS) <= _offered_tags()


async def test_the_routing_function_clears_an_older_decision_itself_when_its_triage_fails(tmp_path):
    async with world(tmp_path) as w:
        agent, _ = await crew(w, ["proposal"], obeys_decision)
        agent._sub_task_executor.execute = AsyncMock(side_effect=SubTaskError("triage timed out"))
        reused = observation()
        reused["_intended_actions"] = ["proposal"]  # what an earlier triage left on a dict that is used again
        assert await agent._execute_chain_with_intent_routing(reused) is None
        assert "_intended_actions" not in reused


async def test_a_decision_with_no_block_leaves_the_message_byte_for_byte_as_it_was(tmp_path):
    async with world(tmp_path) as w:
        agent, _ = await crew(w, ["silent"], obeys_decision)
        agent._build_temporal_context = lambda: ""  # the message carries the clock to the second (AD-502): the comparison must not read it
        for duty in (None, {"duty_id": "systems_check", "description": "Review systems"}):
            plain = observation()
            plain["params"]["duty"] = duty
            expected = await agent._build_user_message(plain)
            for intended in ([], ["silent"], ["ward_room_post"], ["oracle_query", "dm"], ["speak_freely"], ["leadership_review"], ["ward_room_lookup", "deadbeef5678"]):
                decided = observation()
                decided["params"]["duty"] = duty
                decided["_intended_actions"] = intended
                assert await agent._build_user_message(decided) == expected, (duty, intended)


class TestTheDecisionReachesTheCallThatWritesTheOutput:
    async def test_a_decided_proposal_and_notebook_are_posted_and_written(self, tmp_path):
        async with world(tmp_path) as w:
            agent, _ = await crew(w, ["proposal", "notebook"], obeys_decision)
            await think(w, agent)
            assert await threads(w, "Improvement Proposals") == ["[Proposal] Cache the roster"]
            note = w.notebook("Kira", "roster-cache")
            assert note.is_file() and "read 40 times" in note.read_text(encoding="utf-8")

    @pytest.mark.parametrize("intended", [["proposal"], ["notebook"], ["proposal", "notebook"], ["notebook", "ward_room_lookup"], ["silent", "proposal"]])
    async def test_the_single_call_is_shown_the_decision(self, tmp_path, intended):
        async with world(tmp_path) as w:
            agent, model = await crew(w, intended, obeys_decision)
            observed = observation()
            await agent.decide(observed)
            prompt = model.requests[0].prompt
            assert DECIDED in prompt and "Otherwise respond with exactly" not in prompt
            billet = prompt.split(DECIDED)[1]
            assert ("[PROPOSAL]" in billet) == ("proposal" in intended)
            assert ("[NOTEBOOK topic-slug]" in billet) == ("notebook" in intended)
            assert observed["_intended_actions"] == intended

    async def test_a_duty_think_keeps_its_report_line_and_loses_the_default_of_silence(self, tmp_path):
        async with world(tmp_path) as w:
            agent, model = await crew(w, ["proposal"], obeys_decision)
            observed = observation()
            observed["params"]["duty"] = {"duty_id": "systems_check", "description": "Review systems"}
            await agent.decide(observed)
            prompt = model.requests[0].prompt
            assert DECIDED in prompt and "Compose a Ward Room post with your findings" in prompt
            assert "If nothing noteworthy to report, respond with exactly" not in prompt

    async def test_a_chain_that_cannot_run_still_hands_over_the_decision(self, tmp_path):
        async with world(tmp_path) as w:
            agent, model = await crew(w, ["ward_room_post", "proposal"], obeys_decision)  # no COMPOSE handler: the chain falls back to the single call
            await agent.decide(observation())
            prompt = model.requests[0].prompt
            assert DECIDED in prompt
            billet = prompt.split(DECIDED)[1]
            assert "ward_room_post" in billet and "[PROPOSAL]" in billet


class TestTheBilletText:
    def test_the_proposal_format_is_the_one_compose_shows(self):
        billets = _built("probos.cognitive.action_billets")
        prior = [SubTaskResult(sub_task_type=SubTaskType.ANALYZE, name="analyze", success=True, result={
            "intended_actions": ["ward_room_post", "proposal"], "composition_brief": {"situation": "s"}, "contribution_assessment": "RESPOND"})]
        system, _ = _build_proactive_compose_prompt({"context": "x", "mode": "proactive_observation"}, prior, "Keiko", "medical")
        start = system.index("AFTER your observation text:\n") + len("AFTER your observation text:\n")
        assert system[start:system.index("The proposal will be automatically posted")] == billets.PROPOSAL_FORMAT

    def test_the_billet_names_the_decision_and_only_the_formats_it_needs(self):
        billets = _built("probos.cognitive.action_billets")
        both = billets.decision_billet(["proposal", "notebook"])
        assert billets.DECISION_HEADING in both and billets.PROPOSAL_FORMAT.rstrip("\n") in both and billets.NOTEBOOK_FORMAT.rstrip("\n") in both
        only = billets.decision_billet([" Notebook "])
        assert "[NOTEBOOK topic-slug]" in only and "[PROPOSAL]" not in only
        assert billets.DECISION_HEADING == DECIDED

    @pytest.mark.parametrize("intended", [None, [], ["silent"], ["ward_room_post"], ["oracle_query", "dm"], ["speak_freely"]])
    def test_any_other_decision_gets_no_billet(self, intended):
        assert _built("probos.cognitive.action_billets").decision_billet(intended) == ""


class TestTheBilletRepeatsNoWordOfTheTriage:
    async def test_identifiers_the_triage_made_up_do_not_ground_a_reply_that_cites_them(self, tmp_path):
        made_up = ("deadbeef5678", "feedcafe1234")  # two identifiers a model invented: BF-204 suppresses a reply that cites two the call was not shown
        async with world(tmp_path) as w:
            agent, model = await crew(w, ["ward_room_post", "proposal", *made_up], lambda request: f"Noted {made_up[0]} and {made_up[1]} in the roster.")
            decision = await agent.decide(observation())  # no COMPOSE handler: the chain falls back to the single call, whose reply BF-922 judges
            prompt = model.requests[0].prompt
            assert len(model.requests) == 1 and DECIDED in prompt and "[PROPOSAL]" in prompt
            assert not any(word in prompt for word in made_up)
            assert decision.get("_suppressed") is True and decision.get("_suppression_reason") == "confabulation_detected"
            assert decision["llm_output"] == "[NO_RESPONSE]"

    @pytest.mark.parametrize("extra", ["deadbeef5678", "a note about the roster", "ward_room_lookup", "silent", 7])
    def test_a_tag_that_is_not_one_the_billet_names_changes_nothing(self, extra):
        billets = _built("probos.cognitive.action_billets")
        assert billets.decision_billet(["proposal", extra]) == billets.decision_billet(["proposal"])

    def test_the_billet_names_each_decided_tag_by_its_own_constant_in_their_order(self):
        billets = _built("probos.cognitive.action_billets")
        billet = billets.decision_billet([" DM", "ward_room_post", "Notebook", "proposal", "frobnicate"])
        assert "decided to take these actions: proposal, notebook, ward_room_post, dm." in billet and "frobnicate" not in billet
        assert "You also decided: ward_room_post, dm. Use the formats your standing orders give for them." in billet


class TestTheDecisionBelongsToItsTurn:
    async def test_a_dict_decided_on_again_by_a_turn_with_no_triage_is_not_told_the_older_decision(self, tmp_path):
        async with world(tmp_path) as w:
            agent, model = await crew(w, ["proposal"], obeys_decision)
            agent._sub_task_executor = None  # AD-632f's first gate: no triage runs, so the routing function is never entered
            reused = observation()
            reused["_intended_actions"] = ["proposal"]  # what an earlier turn's triage left on a dict that is decided on again
            await agent.decide(reused)
            assert len(model.requests) == 1 and DECIDED not in model.requests[0].prompt
            assert "_intended_actions" not in reused

    async def test_a_decision_cache_hit_leaves_no_older_decision_on_the_dict(self, tmp_path):
        from probos.cognitive.cognitive_agent import _CACHE_HITS, _CACHE_MISSES, _DECISION_CACHES
        async with world(tmp_path) as w:
            try:
                w.rt.config.cognitive.decision_cache_enabled = True  # BF-864's gate: off by default, on in this ship's config only
                agent, model = await crew(w, ["proposal"], obeys_decision)
                await agent.decide(observation())  # the first turn's answer is cached
                reused = observation()
                reused["_intended_actions"] = ["proposal"]
                decision = await agent.decide(reused)
                assert decision.get("cached") is True and len(model.requests) == 1  # premise: the second turn made no call
                assert "_intended_actions" not in reused
            finally:
                _DECISION_CACHES.clear()
                _CACHE_HITS.clear()
                _CACHE_MISSES.clear()
