"""BF-934 (#1673) S2: no gate discards an action the output carries, and a proposal that is not filed says why.

Real: the think cycle, the action extraction, the Ward Room and its router, and the AD-643b re-reflect through AD-643a's routing. Doubles (tests/bf934_world.py): the triage's
ANALYZE and QUERY handlers, COMPOSE and REFLECT stand-ins below (no model call), a thinker whose ``handle_intent`` answers the text a model wrote, and a novelty gate that
finds everything repeated. The classes hold the cases the unfixed tree fails; the functions before them pass on both. No BF-934 name is imported at module level.
"""

from __future__ import annotations

import importlib
import logging
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskType
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
