"""AD-1347 S2 (#1627): the chain's agent-work tags, against the real service and the real chain paths.

The real ``AgentWorkService`` over a real ``WorkItemStore`` (``_ship`` from ``tests/test_ad1347_s1_agent_work.py``),
the real ``ProactiveCognitiveLoop._extract_and_execute_actions``, the real ``WardRoomPostPipeline`` over a real
``WardRoomService`` (C12) and the real ``ComposeHandler`` (C11). The runtime the loop reads is a ``MagicMock`` with the
``ProbOSRuntime`` spec carrying the real service and a real ``TrustNetwork``, as ``tests/test_ad868_self_originated_crew.py``
builds it. On today's tree every test fails at import: ``probos.agent_work_tags`` is absent.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

import probos.agent_work_tags as tags_module
from probos.agent_work import read_agent_work
from probos.agent_work_tags import AGENT_WORK_INSTRUCTIONS, MAX_TAGS_PER_REPLY, AgentWorkTag, split_agent_work_tags
from probos.cognitive.sub_task import SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.compose import (
    ComposeHandler,
    _build_dm_compose_prompt,
    _build_proactive_compose_prompt,
    _build_ward_room_compose_prompt,
)
from probos.consensus.trust import TrustNetwork
from probos.proactive import ProactiveCognitiveLoop
from probos.runtime import ProbOSRuntime
from probos.types import LLMResponse
from probos.ward_room.service import WardRoomService
from probos.ward_room_pipeline import WardRoomPostPipeline
from probos.ward_room_router import WardRoomRouter
from tests.test_ad1347_s1_agent_work import STOP_REASON, _discovered, _section, _ship

REQUEST = (
    "[REQUEST_WORK]\nTitle: Read the EventLog window\nReason: the thread cannot show what the log holds\n"
    "Tool: event_log_query\n[/REQUEST_WORK]"
)
SELF_TASK = "[SELF_TASK]\nTitle: Check my build log\nReason: the relay drifted twice\n[/SELF_TASK]"


def _loop_runtime(service: Any, trust: TrustNetwork) -> Any:
    """The runtime the extractor reads, as tests/test_ad868_self_originated_crew.py builds it, with ``agent_work``."""
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.ward_room = MagicMock()
    runtime.trust_network = trust
    runtime.ward_room_router = MagicMock(spec=WardRoomRouter)
    runtime.ward_room_router.extract_endorsements.return_value = (None, [])
    runtime.config = MagicMock()
    runtime.config.communications = MagicMock()
    runtime.config.communications.dm_min_rank = "ensign"
    runtime.crew_session_service = None
    runtime.dispatcher = None
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "callsign"
    runtime.callsign_registry.resolve.return_value = None
    runtime.agent_work = service
    return runtime


def _loop(runtime: Any) -> ProactiveCognitiveLoop:
    loop = ProactiveCognitiveLoop(cooldown=0)
    loop.set_runtime(runtime)
    return loop


def _posts(path: Path, thread_id: str) -> list[tuple[str, str]]:
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return raw.execute(
            "SELECT author_id, body FROM posts WHERE thread_id = ? ORDER BY created_at", (thread_id,),
        ).fetchall()


# C1
@pytest.mark.parametrize(("text", "expected", "cleaned"), [
    (f"Note.\n{SELF_TASK}", [AgentWorkTag("self_task", title="Check my build log", reason="the relay drifted twice")], "Note."),
    (
        "[REQUEST_WORK]\nTitle: Read it\nReason: first\nsecond line\nTool: event_log_query\nDepartment: Engineering\n"
        "Assignee: @Forge\n[/REQUEST_WORK] after",
        [AgentWorkTag("request", title="Read it", reason="first second line", tool_id="event_log_query",
                      department="engineering", assignee="Forge")],
        "after",
    ),
    ("Taking it. [CLAIM_WORK wi-123]", [AgentWorkTag("claim", work_item_id="wi-123")], "Taking it."),
    ("[DECLINE_WORK wi-9]\nOn the warp core\nall shift.\n[/DECLINE_WORK]",
     [AgentWorkTag("decline", work_item_id="wi-9", reason="On the warp core all shift.")], ""),
    ("Open [SELF_TASK]\nTitle: never closed", [], "Open \nTitle: never closed"),
    ("Stray [/REQUEST_WORK] and [CLAIM_WORK] and [DECLINE_WORK bad id!]", [], "Stray  and  and"),
])
def test_the_parser_reads_each_tag_and_strips_every_marker(text: str, expected: list[AgentWorkTag], cleaned: str) -> None:
    got, tags = split_agent_work_tags(text)
    assert list(tags) == expected
    assert got == cleaned


# C2
def test_a_text_without_agent_work_tags_is_returned_unchanged() -> None:
    text = "  Relay 4 is at 93 percent. [ENDORSE p1 UP]\n"
    assert split_agent_work_tags(text) == (text, ())


# C3
async def test_a_self_task_tag_in_a_ward_room_reply_files_under_the_agents_slot_with_the_thread_as_origin(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        cleaned, actions = await loop._extract_and_execute_actions(
            ship.agents["forge-1"], f"Checking.\n{SELF_TASK}", thread_id="thread-9", post_id="post-9",
        )
        [item] = await ship.store.list_agent_work(False, None, 10)
        assert (item.created_by, item.assigned_to) == ("forge-1", "forge-1")
        assert item.metadata["agent_work"]["origin"] == {"channel": "ward_room", "thread_id": "thread-9", "post_id": "post-9"}
        assert "[SELF_TASK]" not in cleaned and "[/SELF_TASK]" not in cleaned
        assert cleaned.startswith("Checking.") and item.id[:8] in cleaned and "Ship's Computer" in cleaned
        assert actions[-1] == {"type": "agent_work", "action": "self_task", "outcome": "created", "work_item_id": item.id}


# C4
async def test_a_request_tag_publishes_to_a_department_and_the_chain_request_is_discoverable(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        cleaned, _ = await loop._extract_and_execute_actions(ship.agents["pulaski-1"], REQUEST, thread_id="t1")
        [item] = await ship.store.list_agent_work(False, None, 10)
        record = read_agent_work(item)
        assert record is not None
        assert (record.kind, record.department, record.tool_id) == ("request", "engineering", "event_log_query")
        assert (item.created_by, item.assigned_to) == ("pulaski-1", None)
        assert await _discovered(ship, "forge-1") == [item.id]  # the placement trap (premise 6), through the chain
        assert "engineering" in cleaned and item.id[:8] in cleaned
        named = REQUEST.replace("Title: Read the EventLog window", "Title: Read the access log").replace(
            "Tool: event_log_query", "Tool: event_log_query\nDepartment: Security",
        )
        await loop._extract_and_execute_actions(ship.agents["pulaski-1"], named, thread_id="t1")
        security = [read_agent_work(i) for i in await ship.store.list_agent_work(False, None, 10) if i.id != item.id]
        assert [r.department for r in security if r is not None] == ["security"]


# C5
async def test_while_off_the_extractor_never_enters_the_agent_work_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entered: list[dict[str, Any]] = []

    async def _spy(*args: Any, **kwargs: Any) -> Any:
        entered.append(kwargs)
        raise AssertionError("the agent-work path was entered while agent_work is off")

    monkeypatch.setattr(tags_module, "apply_agent_work_tags", _spy)
    async with _ship(tmp_path) as ship:
        for service in (None, MagicMock()):  # off, and a double that is not the real service
            loop = _loop(_loop_runtime(service, TrustNetwork()))
            await loop._extract_and_execute_actions(ship.agents["forge-1"], f"Obs.\n{SELF_TASK}", thread_id="t1")
        assert entered == []
        assert await ship.store.list_agent_work(False, None, 10) == []


# C6
async def test_an_ensigns_tags_are_stripped_and_nothing_is_filed(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        trust = TrustNetwork()
        trust.create_with_prior("forge-2", 1.0, 3.0)  # 0.25: an ensign
        loop = _loop(_loop_runtime(ship.service, trust))
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["forge-2"], f"Obs.\n{SELF_TASK}", thread_id="t1")
        assert cleaned == "Obs." and [a for a in actions if a.get("type") == "agent_work"] == []
        assert await ship.store.list_agent_work(False, None, 10) == []


# C7
@pytest.mark.parametrize("who", ["unresolved", "stopped"])
async def test_an_unresolved_or_stopped_requester_is_refused_and_nothing_is_written(tmp_path: Path, who: str) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        if who == "unresolved":
            agent: Any = SimpleNamespace(id="ghost-1", agent_type="builder", callsign="Ghost")
        else:
            issued = await ship.stops.issue_stop("forge-1", reason=STOP_REASON)
            agent = ship.agents["forge-1"]
        cleaned, actions = await loop._extract_and_execute_actions(agent, SELF_TASK, thread_id="t1")
        assert "not filed" in cleaned and "CANARY" not in cleaned
        code = "requester_unresolved" if who == "unresolved" else "agent_stopped"
        assert actions[-1] == {"type": "agent_work", "action": "self_task", "outcome": f"refused:{code}"}
        assert await ship.store.list_agent_work(False, None, 10) == []
        if who == "stopped":
            assert ship.stops.refused_counts(issued.record.stop_id) == {"agent_work": 1}


# C8
async def test_at_most_three_actions_are_taken_from_one_reply(tmp_path: Path) -> None:
    async with _ship(tmp_path, section=_section(max_open_per_agent=10, max_created_per_agent_per_hour=10)) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        blocks = "\n".join(
            f"[SELF_TASK]\nTitle: Task {n}\nReason: the relay drifted\n[/SELF_TASK]" for n in ("one", "two", "three", "four")
        )
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["forge-1"], blocks, thread_id="t1")
        assert len(await ship.store.list_agent_work(False, None, 10)) == MAX_TAGS_PER_REPLY
        assert len([a for a in actions if a.get("type") == "agent_work"]) == MAX_TAGS_PER_REPLY
        assert f"only {MAX_TAGS_PER_REPLY} agent-work actions" in cleaned


# C9
@pytest.mark.parametrize("thread_id", [" t1", "x" * 129])
async def test_an_origin_the_service_cannot_record_is_a_refused_tag(tmp_path: Path, thread_id: str) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["forge-1"], SELF_TASK, thread_id=thread_id)
        assert "could not be recorded as its origin" in cleaned
        assert actions[-1]["outcome"] == "refused:invalid_origin"
        assert await ship.store.list_agent_work(False, None, 10) == []


# C10
async def test_a_second_requester_of_the_same_request_becomes_its_watcher_through_the_chain(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        await loop._extract_and_execute_actions(ship.agents["pulaski-1"], REQUEST, thread_id="t1")
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["ogawa-1"], REQUEST, thread_id="t2")
        [item] = await ship.store.list_agent_work(False, None, 10)
        assert await ship.store.list_work_watchers(item.id) == ("ogawa-1",)
        assert "watcher" in cleaned and actions[-1]["outcome"] == "deduplicated"


class _Capture:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def complete(self, request: Any, **kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content="ok", tokens_used=1)


_BUILDERS = {
    "ward_room_response": _build_ward_room_compose_prompt,
    "proactive_observation": _build_proactive_compose_prompt,
    "dm_response": _build_dm_compose_prompt,
}


# C11
@pytest.mark.parametrize("mode", sorted(_BUILDERS))
async def test_the_compose_prompt_teaches_the_tags_only_while_agent_work_is_on(tmp_path: Path, mode: str) -> None:
    """The byte-identical golden of the prompt: off, the compose system prompt is exactly the mode's builder output."""
    context = {"_agent_type": "builder", "_callsign": "Forge", "_department": "engineering"}
    expected, _ = _BUILDERS[mode](dict(context), [], "Forge", "engineering")
    prompts: dict[str, str] = {}
    async with _ship(tmp_path) as ship:
        for label, service in (("off", None), ("on", ship.service)):
            llm = _Capture()
            handler = ComposeHandler(llm_client=llm, runtime=SimpleNamespace(agent_work=service))
            spec = SubTaskSpec(sub_task_type=SubTaskType.COMPOSE, name="compose", prompt_template=mode)
            result = await handler(spec, dict(context), [])
            assert result.success, result.error
            prompts[label] = llm.requests[0].system_prompt
    assert prompts["off"] == expected
    if mode == "dm_response":
        assert prompts["on"] == expected
    else:
        assert prompts["on"] == expected + "\n\n" + AGENT_WORK_INSTRUCTIONS
        assert "[SELF_TASK]" in prompts["on"] and "[REQUEST_WORK]" in prompts["on"]


# C12
async def test_the_ward_room_pipeline_passes_its_thread_and_post_to_the_extractor(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        wr = WardRoomService(db_path=str(tmp_path / "wr.db"))
        await wr.start()
        try:
            medical = await wr.get_channel_by_department("medical")
            thread = await wr.create_thread(medical.id, "bones-1", "Relay", "The relay drifted.", author_callsign="Bones")
            post = await wr.create_post(thread.id, "bones-1", "Twice now.", author_callsign="Bones")
            runtime = _loop_runtime(ship.service, TrustNetwork())
            runtime.ward_room = wr
            router = MagicMock(spec=WardRoomRouter)
            router.extract_recreation_commands = AsyncMock(side_effect=lambda agent, text, callsign: text)
            pipeline = WardRoomPostPipeline(
                ward_room=wr, ward_room_router=router, proactive_loop=_loop(runtime), trust_network=None,
                callsign_registry=None, config=MagicMock(),
            )
            posted = await pipeline.process_and_post(
                agent=ship.agents["pulaski-1"], response_text=f"I need the log.\n{REQUEST}",
                thread_id=thread.id, event_type="ward_room_post_created", post_id=post.id,
            )
            assert posted is True
            [item] = await ship.store.list_agent_work(False, None, 10)
            assert item.metadata["agent_work"]["origin"] == {"channel": "ward_room", "thread_id": thread.id, "post_id": post.id}
            replies = [body for author, body in _posts(tmp_path / "wr.db", thread.id) if author == "pulaski-1"]
            assert len(replies) == 1 and item.id[:8] in replies[0] and "[REQUEST_WORK]" not in replies[0]
        finally:
            await wr.stop()


# C13
async def test_a_chief_assigns_a_member_of_its_department_by_callsign(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        runtime = _loop_runtime(ship.service, TrustNetwork())
        runtime.callsign_registry.resolve.return_value = {"agent_id": "forge-1"}
        assigned = REQUEST.replace("Tool: event_log_query", "Tool: event_log_query\nAssignee: @Forge")
        cleaned, actions = await _loop(runtime)._extract_and_execute_actions(ship.agents["laforge-1"], assigned, thread_id="t1")
        [item] = await ship.store.list_agent_work(False, None, 10)
        record = read_agent_work(item)
        assert record is not None and (record.kind, item.assigned_to, item.created_by) == ("assignment", "forge-1", "laforge-1")
        assert "assigned to forge-1" in cleaned and actions[-1]["outcome"] == "created"
