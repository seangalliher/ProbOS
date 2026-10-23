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
import time
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
FENCE = "`" * 3  # A1: a Markdown code fence, spelled so this file holds no literal fence


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
    # A1 (F6): a fenced example and a quoted claim are stripped and never acted on. A2: an inert marker is removed
    # alone, so the example's text stays.
    (f"Example syntax only:\n{FENCE}\n[SELF_TASK]\nTitle: x\n[/SELF_TASK]\n{FENCE}", [], f"Example syntax only:\n{FENCE}\n\nTitle: x\n\n{FENCE}"),
    ("> [CLAIM_WORK wi-1]\nNot mine to take.", [], "> \nNot mine to take."),
    # A1 (F6): a nested block is broken, removed whole, and files nothing ("Outer Inner" before A1).
    ("[SELF_TASK]\nTitle: Outer\n[SELF_TASK]\nTitle: Inner\n[/SELF_TASK]\n[/SELF_TASK]", [], ""),
    # A1 (F7): names in any case, and every marker goes, the claim closer included.
    ("Ok. [Self_Task]\nTitle: Mixed\n[/sELF_tASK] [claim_work wi-123] [/CLAIM_WORK]",
     [AgentWorkTag("self_task", title="Mixed"), AgentWorkTag("claim", work_item_id="wi-123")], "Ok."),
    # A1 (F7): an unclosed opener and every marker after it are removed; the text stays.
    ("Open [SELF_TASK] then [CLAIM_WORK wi-2]", [], "Open  then"),
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

    asked: list[Any] = []
    service_of = tags_module.agent_work_service

    def _service_of(runtime: Any) -> Any:
        asked.append(runtime.agent_work)
        return service_of(runtime)

    monkeypatch.setattr(tags_module, "apply_agent_work_tags", _spy)
    monkeypatch.setattr(tags_module, "agent_work_service", _service_of)
    async with _ship(tmp_path) as ship:
        doubles = (None, MagicMock())  # off, and a double that is not the real service
        for service in doubles:
            loop = _loop(_loop_runtime(service, TrustNetwork()))
            await loop._extract_and_execute_actions(ship.agents["forge-1"], f"Obs.\n{SELF_TASK}", thread_id="t1")
        assert entered == []
        assert asked == [doubles[1]]  # A1 (F12): off neither imports nor calls the tag module
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


# C14
async def test_an_example_a_quotation_or_a_broken_block_is_stripped_and_nothing_is_filed(tmp_path: Path) -> None:
    """A1 (F6, F7): fenced and quoted tags are examples and a nested block is broken; none is acted on, every marker
    goes, in any letter case."""
    text = (
        f"Example syntax only:\n{FENCE}\n{SELF_TASK}\n{FENCE}\n> [CLAIM_WORK wi-1]\n"
        "[SELF_TASK]\nTitle: Outer\n[Self_Task]\nTitle: Inner\n[/SELF_TASK]\n[/self_task] [/CLAIM_WORK]"
    )
    async with _ship(tmp_path) as ship:
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        cleaned, actions = await loop._extract_and_execute_actions(ship.agents["forge-1"], text, thread_id="t1")
        assert await ship.store.list_agent_work(False, None, 10) == []
        assert [action for action in actions if action.get("type") == "agent_work"] == []
        lowered = cleaned.lower()
        assert "self_task" not in lowered and "claim_work" not in lowered and cleaned.startswith("Example syntax only:")


# C15
@pytest.mark.parametrize(("text", "cleaned"), [
    ("[SELF_TASK]" * 6_000, ""),
    ("[SELF_TASK]" * 6_000 + "[/SELF_TASK]" * 6_000, ""),
    (f"{FENCE}\n" + "[CLAIM_WORK wi-1]\n" * 3_500, FENCE),
    ("> [CLAIM_WORK wi-1]\n" * 3_000, ("> \n" * 3_000).strip()),
    ("`[CLAIM_WORK wi-1]` " * 3_000, ("`` " * 3_000).strip()),
    ("- " * 30_000 + "x", "- " * 30_000 + "x"),
], ids=["unclosed_openers", "nested_levels", "fenced_lines", "quote_lines", "code_spans", "list_markers"])
def test_repeated_unclosed_openers_are_parsed_in_one_bounded_pass(
    text: str, cleaned: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 (F11): 66 KB of unclosed openers. The review measured 3.1 s for this shape before A1 (one rescan per opener).
    A2 (F16, F17): the same bound over 6,000 nested levels, fence lines, quote lines and code spans, and each line is
    read for a fence exactly once (no rescan). A2b: and over one line of 30,000 list item markers."""
    lines = len(text.splitlines())
    reads = 0
    fence_re = tags_module._FENCE_RE

    def _read_once(content: str) -> Any:
        nonlocal reads
        reads += 1
        return fence_re.fullmatch(content)

    monkeypatch.setattr(tags_module, "_FENCE_RE", SimpleNamespace(fullmatch=_read_once))
    started = time.perf_counter()
    assert split_agent_work_tags(text) == (cleaned, ())
    assert time.perf_counter() - started < 0.5
    assert reads == lines


# C16
async def test_a_work_store_fault_on_one_tag_is_acknowledged_and_the_rest_of_the_reply_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A1 (F10): the reply is posted, the next tag is acted on, and the failed one is acknowledged, not retried."""
    async with _ship(tmp_path) as ship:
        async def _broken(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("attempt to write a readonly database")

        monkeypatch.setattr(ship.service, "create_self_task", _broken)
        loop = _loop(_loop_runtime(ship.service, TrustNetwork()))
        cleaned, actions = await loop._extract_and_execute_actions(
            ship.agents["pulaski-1"], f"Obs.\n{SELF_TASK}\n{REQUEST}", thread_id="t1",
        )
        [item] = await ship.store.list_agent_work(False, None, 10)
        record = read_agent_work(item)
        assert record is not None and record.kind == "request"
        assert cleaned.startswith("Obs.") and "could not be confirmed" in cleaned and item.id[:8] in cleaned
        assert [action["outcome"] for action in actions if action.get("type") == "agent_work"] == ["error", "created"]


TILDES = "~" * 3
LONG_FENCE = "`" * 4  # A2: a four-backtick fence, spelled as FENCE is
EXAMPLE = "[SELF_TASK]\nTitle: x\n[/SELF_TASK]"
REAL = "[SELF_TASK]\nTitle: Real\n[/SELF_TASK]"
REAL_TAG = AgentWorkTag("self_task", title="Real")


def _claim(work_item_id: str) -> AgentWorkTag:
    return AgentWorkTag("claim", work_item_id=work_item_id)


#: A2 (F16, F17): the inert-region and block grammar, one row per construct (CommonMark 0.31.2 with the differences
#: contract section 9 names; the out_of_scope rows are those differences, read as written). A2d (F25): every other
#: row's markers are where CommonMark puts them, so a row that quotes a line puts a blank line before the tag after it
#: (a line straight after a quote line continues the quote lazily, register R13).
GRAMMAR = [
    pytest.param(f"Ex:\n{FENCE}\n{EXAMPLE}\n{FENCE}\n{REAL}", [REAL_TAG], f"Ex:\n{FENCE}\n\nTitle: x\n\n{FENCE}", id="fence_backtick"),
    pytest.param(f"Ex:\n{TILDES}\n{EXAMPLE}\n{TILDES}\n{REAL}", [REAL_TAG], f"Ex:\n{TILDES}\n\nTitle: x\n\n{TILDES}", id="fence_tilde"),
    pytest.param(
        f"Ex:\n{FENCE}\n{TILDES}\n{EXAMPLE}\n{FENCE}\n{REAL}", [REAL_TAG], f"Ex:\n{FENCE}\n{TILDES}\n\nTitle: x\n\n{FENCE}",
        id="fence_tilde_inside_backtick_is_content",
    ),
    pytest.param(
        f"Ex:\n{LONG_FENCE}\n{FENCE}\n{EXAMPLE}\n{FENCE}\n{LONG_FENCE}\n{REAL}", [REAL_TAG],
        f"Ex:\n{LONG_FENCE}\n{FENCE}\n\nTitle: x\n\n{FENCE}\n{LONG_FENCE}", id="fence_shorter_run_inside_is_content",
    ),
    pytest.param(
        f"Ex:\n{FENCE}\n{FENCE}python\n{EXAMPLE}\n{FENCE}\n{REAL}", [REAL_TAG],
        f"Ex:\n{FENCE}\n{FENCE}python\n\nTitle: x\n\n{FENCE}", id="fence_line_with_info_inside_is_content",
    ),
    pytest.param(f"Ex:\n{FENCE}\n{EXAMPLE}\n{LONG_FENCE}\n{REAL}", [REAL_TAG], f"Ex:\n{FENCE}\n\nTitle: x\n\n{LONG_FENCE}", id="fence_longer_closer_closes"),
    pytest.param(f"Ex:\n{FENCE}\n{REAL}", [], f"Ex:\n{FENCE}\n\nTitle: Real", id="fence_unclosed_runs_to_the_end"),
    pytest.param(
        f"1. Example:\n    {FENCE}\n    [CLAIM_WORK wi-1]\n    {FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-2")],
        f"1. Example:\n    {FENCE}\n    \n    {FENCE}", id="fence_indented_in_a_list_item",
    ),
    pytest.param(f"{FENCE}\n[DECLINE_WORK wi-1] busy [/DECLINE_WORK]\n{FENCE}", [], f"{FENCE}\n busy \n{FENCE}", id="fenced_decline_is_not_acted_on"),
    pytest.param(
        f"{FENCE}inline{FENCE} then\n[CLAIM_WORK wi-3]", [_claim("wi-3")], f"{FENCE}inline{FENCE} then",
        id="backtick_run_with_a_backtick_after_is_a_code_span",
    ),
    pytest.param("> [CLAIM_WORK wi-1]\n\n[CLAIM_WORK wi-2]", [_claim("wi-2")], ">", id="quote_line"),
    pytest.param("   > [CLAIM_WORK wi-1]", [], ">", id="quote_line_indented"),
    pytest.param(f"> [SELF_TASK]\n\n{REAL}", [REAL_TAG], ">", id="quoted_opener_leaves_the_real_block_actionable"),
    pytest.param("Reply with `[CLAIM_WORK wi-1]` to take it.", [], "Reply with `` to take it.", id="code_span_claim"),
    pytest.param("Syntax: `[SELF_TASK] Title: x [/SELF_TASK]`", [], "Syntax: ` Title: x `", id="code_span_block"),
    pytest.param("`a` [CLAIM_WORK wi-4] `b`", [_claim("wi-4")], "`a`  `b`", id="text_between_two_spans_is_actionable"),
    pytest.param("`a`` [CLAIM_WORK wi-5] ``b", [], "`a``  ``b", id="span_closes_only_on_a_run_of_its_length"),
    pytest.param("It is `odd [CLAIM_WORK wi-6]", [_claim("wi-6")], "It is `odd", id="unmatched_backtick_is_text"),
    pytest.param(
        "[SELF_TASK]\nTitle: Outer\n[SELF_TASK]\nTitle: Inner\n[/SELF_TASK]\n[SELF_TASK]\nTitle: Tail\n[/SELF_TASK]\n[/SELF_TASK]",
        [], "", id="nested_tail",
    ),
    pytest.param(
        "[SELF_TASK]\nTitle: Outer\n[SELF_TASK]\nTitle: Inner\n[/SELF_TASK]\nafter", [],
        "Title: Outer\n\nTitle: Inner\n\nafter", id="unclosed_outer_with_a_closed_inner",
    ),
    pytest.param(
        "[SELF_TASK]\nTitle: a\n[/REQUEST_WORK]\n[/SELF_TASK]\n[CLAIM_WORK wi-7]", [_claim("wi-7")], "",
        id="closer_of_the_other_name_breaks_the_block",
    ),
    pytest.param(
        "[SELF_TASK]\nTitle: `[/SELF_TASK]` x\n[/SELF_TASK]\n[CLAIM_WORK wi-8]", [_claim("wi-8")], "",
        id="inert_closer_inside_a_block_breaks_it",
    ),
    pytest.param("Done [/SELF_TASK] [CLAIM_WORK wi-9]", [_claim("wi-9")], "Done", id="closer_without_opener_is_removed"),
    pytest.param(
        f"Ex:\r\n{FENCE}\r\n[CLAIM_WORK wi-1]\r\n{FENCE}\r\n[CLAIM_WORK wi-2]", [_claim("wi-2")], f"Ex:\r\n{FENCE}\r\n\r\n{FENCE}",
        id="crlf",
    ),
    pytest.param(f"Ex:\r{FENCE}\r[CLAIM_WORK wi-1]", [], f"Ex:\r{FENCE}", id="lone_cr_ends_a_line"),
    pytest.param(
        f"Ex:\n{FENCE}\nx\u2028{FENCE}\n[CLAIM_WORK wi-1]", [], f"Ex:\n{FENCE}\nx\u2028{FENCE}",
        id="unicode_line_separator_does_not_end_a_line",
    ),
    pytest.param("[SELF_TASK\r]\nTitle: x\n[/SELF_TASK]", [], "[SELF_TASK\r]\nTitle: x", id="marker_does_not_cross_a_line_end"),
    pytest.param("Example:\n\n    [CLAIM_WORK wi-1]", [], "Example:", id="indented_code_after_a_blank_line"),
    pytest.param("    [CLAIM_WORK wi-1]", [], "", id="indented_code_at_the_start"),
    pytest.param(f"Text\n{FENCE}\nx\n{FENCE}\n    [CLAIM_WORK wi-1]", [], f"Text\n{FENCE}\nx\n{FENCE}", id="indented_code_after_a_fence"),
    pytest.param("## Example\n    [CLAIM_WORK wi-1]", [], "## Example", id="indented_code_after_a_heading"),
    pytest.param("Text\n***\n    [CLAIM_WORK wi-1]", [], "Text\n***", id="indented_code_after_a_thematic_break"),
    pytest.param("Example:\n\n\t[CLAIM_WORK wi-1]", [], "Example:", id="indented_code_by_a_tab"),
    pytest.param("Text\n    [CLAIM_WORK wi-1]", [_claim("wi-1")], "Text", id="indented_line_continuing_a_paragraph_is_text"),
    pytest.param(
        f"{FENCE}\n    {FENCE}\n[CLAIM_WORK wi-1]", [], f"{FENCE}\n    {FENCE}",
        id="top_level_fence_four_column_line_inside_is_content",
    ),
    pytest.param(f"{FENCE}\n   {FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"{FENCE}\n   {FENCE}", id="top_level_closer_indented_three_closes"),
    pytest.param(
        f"   {FENCE}\n      {FENCE}\n[CLAIM_WORK wi-1]", [], f"{FENCE}\n      {FENCE}",
        id="top_level_closer_indented_four_does_not_close",
    ),
    pytest.param(f"    {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [], f"{FENCE}\n{FENCE}", id="indented_code_then_a_top_level_fence"),
    pytest.param(
        f"1. Example:\n    {FENCE}\n            {FENCE}\n    [CLAIM_WORK wi-1]\n    {FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-2")],
        f"1. Example:\n    {FENCE}\n            {FENCE}\n    \n    {FENCE}", id="list_closer_more_than_three_past_its_opener_is_content",
    ),
    pytest.param(
        f"- {FENCE}\n  [CLAIM_WORK wi-1]\n  {FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-2")], f"- {FENCE}\n  \n  {FENCE}",
        id="fence_on_a_list_marker_line",
    ),
    pytest.param(
        f"- {FENCE}\n  a\n- {FENCE}\n  [CLAIM_WORK wi-1]\n  {FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-2")],
        f"- {FENCE}\n  a\n- {FENCE}\n  \n  {FENCE}", id="new_list_item_fence_line_does_not_close",
    ),
    pytest.param("- > [CLAIM_WORK wi-1]\n\n[CLAIM_WORK wi-2]", [_claim("wi-2")], "- >", id="quote_in_a_list_item"),
    pytest.param(f"    {FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], FENCE, id="indented_fence_line_ends_at_an_unindented_line"),
    pytest.param(f"- {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [], f"- {FENCE}\n{FENCE}", id="marker_line_fence_ends_at_an_unindented_fence_line"),
    pytest.param(
        f"- {FENCE}\n[CLAIM_WORK wi-1]\n   {FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-1")], f"- {FENCE}\n\n   {FENCE}",
        id="marker_line_fence_ends_at_an_outdented_line",
    ),
    pytest.param(
        f"- {FENCE}\n> [CLAIM_WORK wi-1]\n  {LONG_FENCE}\n   [CLAIM_WORK wi-2]", [], f"- {FENCE}\n> \n  {LONG_FENCE}",
        id="fence_in_an_item_ends_at_a_quote",
    ),
    pytest.param(
        f"+ [CLAIM_WORK wi-1]\n   {FENCE}\n{FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-1")], f"+ \n   {FENCE}\n{FENCE}",
        id="continuation_fence_ends_at_an_outdented_fence_line",
    ),
    pytest.param(
        f"1. a\n   {FENCE}\n  {FENCE}\n[CLAIM_WORK wi-1]", [], f"1. a\n   {FENCE}\n  {FENCE}",
        id="outdented_fence_line_after_an_item_fence_opens_a_top_level_fence",
    ),
    pytest.param(f"1. a\n\n   {FENCE}\n  {FENCE}\n[CLAIM_WORK wi-1]", [], f"1. a\n\n   {FENCE}\n  {FENCE}", id="blank_line_keeps_the_list_item"),
    pytest.param(
        f"1. a\n    {FENCE}\n\n   [CLAIM_WORK wi-1]\n    {FENCE}\n[CLAIM_WORK wi-2]", [_claim("wi-2")],
        f"1. a\n    {FENCE}\n\n   \n    {FENCE}", id="blank_line_inside_a_list_fence_keeps_it_open",
    ),
    pytest.param(
        f"- {FENCE}\n\n  x\n  {FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"- {FENCE}\n\n  x\n  {FENCE}",
        id="blank_line_inside_a_marker_line_fence_keeps_it_open",
    ),
    pytest.param(f"-\n  {FENCE}\n {FENCE}\n[CLAIM_WORK wi-1]", [], f"-\n  {FENCE}\n {FENCE}", id="bare_marker_item_fence_ends_at_column_one"),
    pytest.param(f"{FENCE}\n- {FENCE}\n[CLAIM_WORK wi-1]\n{FENCE}", [], f"{FENCE}\n- {FENCE}\n\n{FENCE}", id="marker_line_inside_a_fence_is_content"),
    pytest.param(
        f"1. Example:\n    {FENCE}\n    x\n    {FENCE}\n   [CLAIM_WORK wi-1]", [_claim("wi-1")],
        f"1. Example:\n    {FENCE}\n    x\n    {FENCE}", id="text_after_a_list_fence_in_its_item_is_actionable",
    ),
    pytest.param(
        f"- a\n\n     {FENCE}\n      {FENCE}\n  [CLAIM_WORK wi-1]", [], f"- a\n\n     {FENCE}\n      {FENCE}",
        id="list_closer_counts_from_the_item_column",
    ),
    pytest.param(
        f"-     x\n  {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [], f"-     x\n  {FENCE}\n{FENCE}",
        id="padding_five_starts_the_item_with_indented_code",
    ),
    pytest.param(
        f"-    x\n  {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"-    x\n  {FENCE}\n{FENCE}",
        id="padding_four_is_the_item_column",
    ),
    pytest.param(
        f"-      x\n  {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [], f"-      x\n  {FENCE}\n{FENCE}",
        id="padding_six_starts_the_item_with_indented_code",
    ),
    pytest.param(
        f"-\t\tx\n  {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [], f"-\t\tx\n  {FENCE}\n{FENCE}",
        id="tab_padding_is_counted_in_columns",
    ),
    pytest.param("-     [CLAIM_WORK wi-1]\n[CLAIM_WORK wi-2]", [_claim("wi-2")], "-", id="wide_padded_line_is_indented_code"),
    pytest.param(
        f"-     {FENCE}\n  [CLAIM_WORK wi-1]", [_claim("wi-1")], f"-     {FENCE}", id="fence_on_a_wide_padded_line_is_code_text",
    ),
    pytest.param(
        f"-\n\n  {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"-\n\n  {FENCE}\n{FENCE}",
        id="empty_item_ends_at_a_blank_line",
    ),
    pytest.param(
        f"-\n\n\n  {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"-\n\n\n  {FENCE}\n{FENCE}",
        id="empty_item_ends_at_two_blank_lines",
    ),
    pytest.param(
        f"- \n\n   {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"- \n\n   {FENCE}\n{FENCE}",
        id="empty_item_with_a_trailing_blank_ends_at_a_blank_line",
    ),
    pytest.param("-\n\n[CLAIM_WORK wi-1]", [_claim("wi-1")], "-", id="empty_item_then_a_plain_tag"),
    pytest.param(
        f"-\n  {FENCE}\n  x\n  {FENCE}\n\n  {FENCE}\n {FENCE}\n[CLAIM_WORK wi-1]", [],
        f"-\n  {FENCE}\n  x\n  {FENCE}\n\n  {FENCE}\n {FENCE}",
        id="empty_item_that_opens_a_fence_keeps_its_column_across_a_blank_line",
    ),
    pytest.param("\u00a0> [CLAIM_WORK wi-1]", [], ">", id="out_of_scope_nbsp_before_a_quote_mark_is_a_quote"),
    pytest.param("\u2003> [CLAIM_WORK wi-1]", [], ">", id="out_of_scope_em_space_before_a_quote_mark_is_a_quote"),
    pytest.param("- a\n \t> [CLAIM_WORK wi-1]", [], "- a\n \t>", id="tab_before_a_quote_mark_in_a_list_item_is_a_quote"),
    pytest.param(
        f"1. a\nlazy\n   {FENCE}\n{FENCE}\n[CLAIM_WORK wi-1]", [_claim("wi-1")], f"1. a\nlazy\n   {FENCE}\n{FENCE}",
        id="out_of_scope_lazy_line_then_an_item_fence_is_read_as_written",
    ),
    pytest.param("> Forge wrote:\n[CLAIM_WORK wi-1]", [_claim("wi-1")], "> Forge wrote:", id="out_of_scope_lazy_quote_continuation_is_read_as_written"),
    pytest.param(
        "> Forge wrote:\n\u00a0> [CLAIM_WORK wi-1]", [], "> Forge wrote:\n\u00a0>",
        id="nbsp_line_after_a_quote_is_quoted",
    ),
    pytest.param(
        "-     x\n    [CLAIM_WORK wi-1]", [], "-     x",
        id="out_of_scope_wide_item_paragraph_indented_four_is_read_as_written",
    ),
    pytest.param("`start\n[CLAIM_WORK wi-1]\nend`", [_claim("wi-1")], "`start\n\nend`", id="out_of_scope_span_across_lines_is_read_as_written"),
]


# C17
@pytest.mark.parametrize(("text", "expected", "cleaned"), GRAMMAR)
def test_every_inert_construct_and_block_form_is_read_as_the_grammar_says(
    text: str, expected: list[AgentWorkTag], cleaned: str,
) -> None:
    """A2 (F16, F17), A2b: each construct's tags and posted text. A marker in a fence, indented code, a quote or a span is
    removed alone and never acted on; a nested block stays one block until its own closer."""
    got, tags = split_agent_work_tags(text)
    assert list(tags) == expected
    assert got == cleaned
