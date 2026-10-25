"""AD-1347 S4 (#1627) M2: the chain asks for a Ward Room record by id, and COMPOSE sees the answer.

Real ``CognitiveAgent``, ``SubTaskExecutor``, ``QueryHandler`` and ``WardRoomService`` (an archive
the real prune wrote in ``tmp_path``). ANALYZE and COMPOSE are stand-ins with no model call:
ANALYZE returns its JSON contract, and COMPOSE records the prompt the real
``_build_user_prompt`` makes from the context it is given.
"""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.sub_task import SubTaskExecutor, SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt, _build_thread_analysis_prompt
from probos.cognitive.sub_tasks.compose import _build_user_prompt
from probos.cognitive.sub_tasks.query import _QUERY_OPERATIONS, QueryHandler, _query_ward_room_lookup
from probos.config_models.crew import WardRoomConfig
from probos.ward_room.service import WardRoomService

FORGE = "forge-1"
LAFORGE = "laforge-1"
CHAPEL = "chapel-1"
ARCHIVED_BODY = "Loop B read 41 C at 0300."
UNAVAILABLE = "The Ward Room is not available, so the lookup returned nothing."
_SPEC = SubTaskSpec(sub_task_type=SubTaskType.QUERY, name="lookup", context_keys=("ward_room_lookup",))


class _Runtime:
    """The one runtime attribute ``QueryHandler`` reads for this operation."""

    def __init__(self, ward_room: Any) -> None:
        self.ward_room = ward_room


class _FailingWardRoom:
    async def lookup_record(self, requester_id: str, ref: str) -> Any:
        raise sqlite3.OperationalError("database is locked")


class _Analysis:
    """ANALYZE's JSON contract (``intended_actions`` and the new ref), with no model call."""

    def __init__(self, result: dict) -> None:
        self._result = result

    async def __call__(self, spec: Any, context: dict, prior_results: list) -> SubTaskResult:
        return SubTaskResult(sub_task_type=SubTaskType.ANALYZE, name=spec.name, result=dict(self._result), success=True)


class _Compose:
    """Records the COMPOSE user prompt the real builder makes from the context it is given."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def __call__(self, spec: Any, context: dict, prior_results: list) -> SubTaskResult:
        self.prompts.append(_build_user_prompt(context, prior_results))
        return SubTaskResult(sub_task_type=SubTaskType.COMPOSE, name=spec.name, result={"output": "Acknowledged."}, success=True)


_STARTED: list[Any] = []


@pytest.fixture(autouse=True)
async def _stop_started_services() -> AsyncIterator[None]:
    """A failed assertion skips the test's own ``stop()``, and an open connection keeps the interpreter from exiting."""
    yield
    while _STARTED:
        await _STARTED.pop().stop()


async def _ship(tmp_path: Path) -> tuple[Any, str, str]:
    """A started Ward Room: an Engineering thread pruned into the archive, and a live one to reply in."""
    started = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await started.start()
    _STARTED.append(started)
    engineering = await started.get_channel_by_department("engineering")
    for agent_id in (FORGE, LAFORGE):
        await started.subscribe(agent_id, engineering.id)
    archive = tmp_path / "ward_room_archive"
    await started.start_prune_loop(WardRoomConfig(prune_interval_seconds=3600.0), archive)
    await started.stop_prune_loop()
    pruned = await started.create_thread(engineering.id, LAFORGE, "Coolant audit", ARCHIVED_BODY, author_callsign="LaForge")
    await started.prune_old_threads(
        retention_days=-1, retention_days_endorsed=-1, archive_path=str(archive / "ward_room_archive_2026-10.jsonl"),
    )
    live = await started.create_thread(
        engineering.id, LAFORGE, "Follow-up", "Forge, what did the coolant audit say?", author_callsign="LaForge",
    )
    return started, pruned.id, live.id


def _executor(wr: Any, analysis: dict, compose: _Compose) -> SubTaskExecutor:
    executor = SubTaskExecutor(config=None)
    executor.register_handler(SubTaskType.QUERY, QueryHandler(_Runtime(wr)))
    executor.register_handler(SubTaskType.ANALYZE, _Analysis(analysis))
    executor.register_handler(SubTaskType.COMPOSE, compose)
    return executor


def _agent(executor: Any) -> Any:
    """A real agent; returned as ``Any`` so the precheck does not type it before the new method exists."""
    built = CognitiveAgent(agent_id=FORGE, instructions="Test instructions.", runtime=None)
    built.agent_type = "engineering_officer"
    built.callsign = "Forge"
    built.set_sub_task_executor(executor)
    return built


def _observation(live_id: str) -> dict:
    return {
        "intent": "ward_room_notification",
        "intent_id": "ad1347-s4",
        "context": "LaForge: Forge, what did the coolant audit say?",
        "params": {
            "thread_id": live_id, "channel_name": "Engineering", "is_dm_channel": False,
            "author_id": LAFORGE, "author_callsign": "LaForge",
            "title": "Follow-up", "text": "Forge, what did the coolant audit say?",
        },
    }


def test_the_operation_is_in_the_query_catalog() -> None:
    assert _QUERY_OPERATIONS["ward_room_lookup"] is _query_ward_room_lookup


async def test_the_asker_is_the_chains_agent_id_never_a_params_agent_id(tmp_path: Path) -> None:
    wr, pruned_id, _ = await _ship(tmp_path)
    ref = pruned_id[:8]

    smuggled = await _query_ward_room_lookup(_Runtime(wr), _SPEC, {"ward_room_lookup_ref": ref, "params": {"agent_id": FORGE}})
    own = await _query_ward_room_lookup(_Runtime(wr), _SPEC, {"ward_room_lookup_ref": ref, "_agent_id": FORGE})
    outsider = await _query_ward_room_lookup(_Runtime(wr), _SPEC, {"ward_room_lookup_ref": ref, "_agent_id": CHAPEL})

    # BF-922 (#1639): the typed outcome travels with the text, so BF-204 can tell a record from a failed lookup's echo.
    assert smuggled == {
        "ward_room_lookup": "The Ward Room lookup could not confirm who is asking, so it returned nothing.",
        "ward_room_lookup_outcome": "refused",
    }
    assert ARCHIVED_BODY in own["ward_room_lookup"] and own["ward_room_lookup_outcome"] == "found"
    assert outsider["ward_room_lookup"].startswith("No Ward Room thread or post with id ")
    assert outsider["ward_room_lookup_outcome"] == "not_found"
    await wr.stop()


async def test_no_ref_means_no_read_and_a_failing_ward_room_reads_as_unavailable() -> None:
    assert await _query_ward_room_lookup(_Runtime(None), _SPEC, {"_agent_id": FORGE}) == {"ward_room_lookup": ""}
    assert await _query_ward_room_lookup(
        _Runtime(None), _SPEC, {"_agent_id": FORGE, "ward_room_lookup_ref": "   "},
    ) == {"ward_room_lookup": ""}
    # BF-922 (#1639): a lookup that ran carries its typed outcome; no ref (above) runs none and carries none.
    assert await _query_ward_room_lookup(
        _Runtime(None), _SPEC, {"_agent_id": FORGE, "ward_room_lookup_ref": "aa000001"},
    ) == {"ward_room_lookup": UNAVAILABLE, "ward_room_lookup_outcome": "unavailable"}

    handled = await QueryHandler(_Runtime(_FailingWardRoom()))(
        _SPEC, {"_agent_id": FORGE, "ward_room_lookup_ref": "aa000001"}, [],
    )
    assert handled.success
    assert handled.result == {"ward_room_lookup": UNAVAILABLE, "ward_room_lookup_outcome": "unavailable"}


async def test_the_helper_reads_the_ref_from_analyze_and_runs_once(tmp_path: Path) -> None:
    wr, pruned_id, _ = await _ship(tmp_path)
    agent = _agent(_executor(wr, {}, _Compose()))
    triage = [SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE, name="analyze-thread", success=True,
        result={"intended_actions": ["ward_room_reply", "ward_room_lookup"], "ward_room_lookup_ref": f" {pruned_id[:8]} "},
    )]
    observation: dict = {"_agent_id": FORGE, "intent": "ward_room_notification"}

    await agent._maybe_dispatch_ward_room_lookup(triage, observation)

    assert observation["ward_room_lookup_ref"] == pruned_id[:8]
    assert observation["_ward_room_lookup_fired"] is True
    assert ARCHIVED_BODY in observation["_ward_room_lookup_context"]
    assert observation["_ward_room_lookup_outcome"] == "found"  # BF-922: the outcome travels with the text

    again: dict = {"_agent_id": FORGE, "_ward_room_lookup_fired": True}
    await agent._maybe_dispatch_ward_room_lookup(triage, again)
    assert "_ward_room_lookup_context" not in again

    for bad in (None, "", "   ", 5):
        blank = [SubTaskResult(sub_task_type=SubTaskType.ANALYZE, name="a", success=True, result={"ward_room_lookup_ref": bad})]
        untouched: dict = {"_agent_id": FORGE}
        await agent._maybe_dispatch_ward_room_lookup(blank, untouched)
        assert untouched == {"_agent_id": FORGE}, bad
    await wr.stop()


async def test_a_lookup_named_in_analyze_reaches_the_compose_prompt_through_the_real_chain(tmp_path: Path) -> None:
    wr, pruned_id, live_id = await _ship(tmp_path)
    compose = _Compose()
    analysis = {
        "intended_actions": ["ward_room_reply", "ward_room_lookup"],
        "ward_room_lookup_ref": pruned_id[:8],
        "contribution_assessment": "RESPOND",
    }
    agent = _agent(_executor(wr, analysis, compose))
    observation = _observation(live_id)

    await agent._execute_chain_with_intent_routing(observation)

    assert compose.prompts, "premise: the communication chain ran to COMPOSE"
    prompt = compose.prompts[-1]
    assert "## Ward Room Record (looked up by id)" in prompt
    assert ARCHIVED_BODY in prompt
    assert "the Ward Room archive (pruned " in prompt
    await wr.stop()


async def test_a_lookup_with_no_communication_action_reads_nothing(tmp_path: Path) -> None:
    wr, pruned_id, live_id = await _ship(tmp_path)
    compose = _Compose()
    analysis = {"intended_actions": ["notebook", "ward_room_lookup"], "ward_room_lookup_ref": pruned_id[:8]}
    agent = _agent(_executor(wr, analysis, compose))
    observation = _observation(live_id)

    assert await agent._execute_chain_with_intent_routing(observation) is None

    assert "_ward_room_lookup_context" not in observation
    assert observation["_ward_room_lookup_fired"] is False
    assert compose.prompts == []
    await wr.stop()


async def test_each_routed_chain_starts_with_the_lookup_unfired(tmp_path: Path) -> None:
    wr, pruned_id, live_id = await _ship(tmp_path)
    analysis = {"intended_actions": ["ward_room_reply", "ward_room_lookup"], "ward_room_lookup_ref": pruned_id[:8]}
    agent = _agent(_executor(wr, analysis, _Compose()))
    observation = _observation(live_id)
    observation["_ward_room_lookup_fired"] = True  # left over from an earlier chain on a reused dict

    await agent._execute_chain_with_intent_routing(observation)

    assert ARCHIVED_BODY in observation["_ward_room_lookup_context"]
    await wr.stop()


def test_both_analyze_prompts_teach_the_lookup_and_its_key() -> None:
    _, thread_user = _build_thread_analysis_prompt({"context": "test", "params": {}}, [], "Forge", "Engineering")
    _, situation_user = _build_situation_review_prompt({"context": "test"}, [], "Forge", "Engineering")

    for user in (thread_user, situation_user):
        assert '"ward_room_lookup"' in user and "ward_room_lookup_ref" in user
    assert "9 keys" in thread_user and "8 keys" in situation_user


def test_compose_renders_the_record_only_when_one_was_looked_up() -> None:
    with_record = _build_user_prompt({"_ward_room_lookup_context": "RECORD TEXT"}, [])

    assert "## Ward Room Record (looked up by id)" in with_record and "RECORD TEXT" in with_record
    assert "Ward Room Record" not in _build_user_prompt({}, [])
