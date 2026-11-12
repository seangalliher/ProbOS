"""BF-934 (#1673) S1: a triage that decided to file a proposal or write a notebook entry hands the decision to the call that writes the output.

The real think cycle runs end to end (``ProactiveCognitiveLoop._think_for_agent`` into ``CognitiveAgent.handle_intent``: AD-643a's routing, the single call, the
real extraction, the real Ward Room and Ship's Records on tmp_path). The model double obeys a decision it is shown and otherwise answers ``[NO_RESPONSE]``, the single
call's default (22 of the issue's 24 cases); the triage's ANALYZE and QUERY handlers are doubles (tests/bf934_world.py). The classes hold the cases the unfixed tree
fails; the functions before them pass on both. No BF-934 name is imported at module level.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.sub_task import SubTaskError, SubTaskResult, SubTaskType
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


class TestTheDecisionReachesTheCallThatWritesTheOutput:
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S1 M2 builds it")

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
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-934 S1 M2 builds it")

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
