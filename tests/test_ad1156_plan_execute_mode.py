"""AD-1156 (#1083): plan/execute mode for a one-to-one conversation.

What is proven here, and where:

* The persisted record (``probos.threads.agent_mode``) and its single writer,
  ``ChatThreadStore.set_agent_mode``, against a real SQLite store.
* The turn side (``probos.cognitive.agent_mode``): no record is the legacy
  path, an unreadable record or a failing store holds the turn in plan mode.
* The Captain's ``/mode`` command and its route, with the AD-809 harness.
* The executor: plan mode narrows the offer AND refuses every other call at
  invoke time, including a registered tool the model names without being
  offered it; a refused call is not defect evidence.
* M1, the crossing: the command writes the record, and the next real DM turn
  (``_decide_via_llm`` -> executor -> loop) reads it -- asserted on what the
  model actually received.
* OFF: a stored record is inert, and the model's request is identical to a turn
  on a thread that never had one.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive import agent_mode as agent_mode_module
from probos.cognitive import agentic_dispatch
from probos.cognitive.agent_mode import (
    PLAN_MODE_TOOL_IDS,
    TurnAgentMode,
    agent_modes_enabled,
    dm_agentic_loop_enabled,
    read_turn_agent_mode,
    render_agent_mode_instructions,
)
from probos.cognitive.agent_working_memory import AgentWorkingMemory
from probos.cognitive.agentic_dispatch import (
    DispatchToolExecutor,
    WorkItemAgenticExecutor,
    classify_tool_fault_error,
)
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.commands.mode_command import (
    MODE_CHANGED_EVENT,
    handle_mode_command,
    is_mode_command,
)
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.swe_harness.agentic_loop import PARALLEL_SAFE_TOOL_IDS
from probos.cognitive.swe_harness.tool_call import TextBlock, ToolCallRequest, ToolUseBlock
from probos.cognitive.tool_manifest import LOAD_TOOLS_ID
from probos.config import DmAgenticConfig
from probos.threads import ChatThreadStore
from probos.threads.agent_mode import (
    AGENT_MODE_METADATA_KEY,
    AgentModeRecord,
    AgentModeRecordError,
    AgentModeTransition,
    advance_agent_mode,
    parse_agent_mode_record,
)
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry

_AGENT = "counselor-ezri"
# The exact refusal text, pinned here and compared with the module constant.
_REFUSAL = (
    "This conversation is in plan mode, so that call was refused and did not "
    "run. Only the tools in your current list are open until the Captain "
    "switches to execute mode; finish the plan and name the step that needs "
    "this tool."
)
_PLAN_TEXT = "PLAN: 1. Read the figures. 2. Draft the report. 3. Save it."
_WITHHELD = frozenset({
    "run_python", "browser", "delegate_task", "publish_finding",
    "claim_work_item", "standing_interest", "find_mcp_tool",
})


# ── fixtures and fakes ──────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> ChatThreadStore:
    ticks = iter(float(n) for n in range(1_000, 100_000))
    return ChatThreadStore(tmp_path / "threads.db", clock=lambda: next(ticks))


def _record(**overrides: Any) -> dict[str, Any]:
    # A-8: a record names the agent it was set for.
    base: dict[str, Any] = {
        "mode": "plan", "revision": 1, "changed_at": 100.0,
        "changed_by": "captain", "previous": None, "agent_id": _AGENT,
    }
    base.update(overrides)
    return base


def _raw_metadata(store: ChatThreadStore, thread_id: str) -> str:
    with store._connect() as conn:
        return conn.execute(
            "SELECT metadata FROM chat_threads WHERE id = ?", (thread_id,)
        ).fetchone()["metadata"]


def _write_raw_metadata(store: ChatThreadStore, thread_id: str, metadata: Any) -> None:
    with store._connect() as conn:
        conn.execute(
            "UPDATE chat_threads SET metadata = ? WHERE id = ?",
            (json.dumps(metadata), thread_id),
        )


class _Tool:
    """A registered tool that records its calls; ``fail`` makes it error."""

    tool_type = ToolType.UTILITY_AGENT
    output_schema = {"type": "object"}

    def __init__(self, tool_id: str, *, fail: str | None = None) -> None:
        self.tool_id = tool_id
        self.name = tool_id
        self.description = f"The {tool_id} test tool."
        self.input_schema = {
            "type": "object",
            "properties": {"target": {"type": "string"}},
            "required": [],
        }
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    async def invoke(self, params: dict, context: dict | None = None) -> ToolResult:
        self.calls.append(dict(params or {}))
        if self._fail is not None:
            return ToolResult(error=self._fail)
        return ToolResult(output={"done": self.tool_id})


def _registry(*tools: _Tool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool, provider="ad1156-test", default_permissions={"ensign": "write"})
    return registry


class _Grants:
    """The permission store's one offer-time read: active grants for an agent."""

    def __init__(self, tool_ids: list[str]) -> None:
        self._grants = [SimpleNamespace(tool_id=t, is_restriction=False) for t in tool_ids]

    def get_active_grants_sync(self, agent_id: str, tool_id: str | None = None) -> list[Any]:
        return [g for g in self._grants if tool_id is None or g.tool_id == tool_id]


def _runtime(
    registry: ToolRegistry,
    grants: _Grants,
    *,
    cfg: DmAgenticConfig | None = None,
    store: ChatThreadStore | None = None,
    **config: Any,
) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(
            agentic_dispatch=SimpleNamespace(enabled=True),
            dm_agentic=cfg or DmAgenticConfig(enabled=True, max_iterations=4),
            **config,
        ),
        tool_registry=registry,
        tool_permission_store=grants,
        capability_gap_driver=None,
        intent_bus=None,
        attachment_store=None,
        emit_event=None,
        capability_request_store=None,
        action_approval_store=None,
        fault_report_store=None,
        chat_thread_store=store,
    )


class _Response:
    def __init__(self, blocks: list, content: str) -> None:
        self.content_blocks = blocks
        self.content = content
        self.tokens_used = 0
        self.error = None
        self.model = "scripted"


class _ScriptedLLM:
    """Replays ``steps`` -- ``(tool, args)`` asks for a call, a str answers --
    and records every request, which is what the model actually received."""

    def __init__(self, steps: list[Any]) -> None:
        self._steps = list(steps)
        self.requests: list[Any] = []

    async def complete(self, req: Any, **_kwargs: Any) -> _Response:
        self.requests.append(req)
        step = self._steps.pop(0) if self._steps else "(no further steps)"
        if isinstance(step, tuple):
            name, arguments = step
            call = ToolCallRequest(id=f"c{len(self.requests)}", name=name, arguments=dict(arguments))
            return _Response([TextBlock(text=f"Calling {name}."), ToolUseBlock(tool_call=call)], f"Calling {name}.")
        return _Response([TextBlock(text=step)], step)


def _offered(req: Any) -> list[str]:
    return sorted((d.get("function") or {}).get("name", "") for d in (req.tools or []))


def _transcript(req: Any) -> str:
    return (req.prompt or "") + json.dumps(req.messages or [], default=str)


def _dm_agent(runtime: Any, llm: Any) -> CognitiveAgent:
    # A real agent, so ``_decide_via_llm`` runs its real composition and loop
    # dispatch (the test_ad1208 / test_ad700c pattern).
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.instructions = "You are Ezri."
    agent.agent_type = "test_agent"
    agent.id = _AGENT
    agent.callsign = "Ezri"
    agent.confidence = 0.8
    agent._llm_client = llm
    agent._runtime = runtime
    agent._skills = {}
    agent._strategy_advisor = None
    agent._last_fallback_info = None
    agent.tool_context = None
    agent._sub_task_executor = None
    agent._pending_sub_task_chain = None
    agent._working_memory = AgentWorkingMemory()
    return agent


async def _dm_turn(
    runtime: Any, llm: Any, thread_id: str, text: str, *, agent_id: str = _AGENT,
) -> dict[str, Any]:
    agent = _dm_agent(runtime, llm)
    # A-9: a record governs only a turn of the agent it was set for, so a harness whose
    # thread belongs to another agent id runs its turn as that agent.
    agent.id = agent_id
    return await agent._decide_via_llm(
        {"intent": "direct_message", "params": {"text": text}, "thread_id": thread_id},
    )


class _EventLog:
    def __init__(self, *, fail: BaseException | None = None) -> None:
        self.rows: list[dict[str, Any]] = []
        self._fail = fail

    async def log(self, *args: Any, **kwargs: Any) -> int:
        if self._fail is not None:
            raise self._fail
        self.rows.append({"args": args, **kwargs})
        return len(self.rows)


async def _command(store: ChatThreadStore, thread: Any, message: str, **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("loop_enabled", True)
    return await handle_mode_command(
        message, thread=thread, agent_id=_AGENT, store=store, **kwargs,
    )


# ── 1. the persisted record ─────────────────────────────────────────────────


def test_parse_agent_mode_record_round_trips_through_to_dict() -> None:
    record = parse_agent_mode_record(_record(mode="execute", revision=3, previous="plan"))

    assert record == AgentModeRecord("execute", 3, 100.0, "captain", "plan", _AGENT)  # A-8: its agent
    assert parse_agent_mode_record(json.loads(json.dumps(record.to_dict()))) == record


@pytest.mark.parametrize(
    "value",
    [
        None, [], "plan",
        {k: v for k, v in _record().items() if k != "previous"},
        {**_record(), "approved_by": "captain"},
    ],
    ids=["none", "list", "str", "missing-key", "extra-key"],
)
def test_parse_agent_mode_record_rejects_a_wrong_shape(value: Any) -> None:
    with pytest.raises(AgentModeRecordError):
        parse_agent_mode_record(value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"mode": "Plan"}, {"mode": "off"}, {"mode": None},
        {"revision": 0}, {"revision": True}, {"revision": "1"}, {"revision": 1.0},
        {"changed_at": 100}, {"changed_at": float("nan")}, {"changed_at": float("inf")},
        {"changed_at": -1.0}, {"changed_by": ""}, {"changed_by": "   "},
        {"changed_by": 7}, {"changed_by": "c" * 129},
        {"previous": "plan"}, {"revision": 2, "previous": None},
        {"revision": 2, "previous": "draft"},
    ],
)
def test_parse_agent_mode_record_rejects_a_wrong_field(overrides: dict[str, Any]) -> None:
    with pytest.raises(AgentModeRecordError):
        parse_agent_mode_record(_record(**overrides))


def test_advance_agent_mode_numbers_every_transition() -> None:
    # A-8: each transition names the agent its record is set for.
    first = advance_agent_mode(None, "plan", changed_by="captain", changed_at=5, agent_id=_AGENT)
    second = advance_agent_mode(first.record, "execute", changed_by="captain", changed_at=6.5, agent_id=_AGENT)
    same = advance_agent_mode(second.record, "execute", changed_by="captain", changed_at=7.0, agent_id=_AGENT)

    assert first == AgentModeTransition(AgentModeRecord("plan", 1, 5.0, "captain", None, _AGENT), True)
    assert second == AgentModeTransition(AgentModeRecord("execute", 2, 6.5, "captain", "plan", _AGENT), True)
    assert same == AgentModeTransition(second.record, False)


@pytest.mark.parametrize("mode", ["", "PLAN", "auto", None])
def test_advance_agent_mode_refuses_an_unknown_mode(mode: Any) -> None:
    with pytest.raises(AgentModeRecordError):
        advance_agent_mode(None, mode, changed_by="captain", changed_at=1.0, agent_id=_AGENT)  # A-8: its agent


# ── 2. the store's single writer ────────────────────────────────────────────


def test_set_agent_mode_persists_across_a_store_reopen(tmp_path: Path) -> None:
    db = tmp_path / "threads.db"
    first = ChatThreadStore(db)
    thread = first.get_or_create_default_for_agent(_AGENT, "Ezri")

    transition = first.set_agent_mode(thread.id, "plan", changed_by="captain")

    reopened = ChatThreadStore(db).get_thread(thread.id)
    assert transition is not None and transition.changed is True
    assert reopened.metadata[AGENT_MODE_METADATA_KEY] == transition.record.to_dict()
    assert transition.record.revision == 1 and transition.record.previous is None


def test_set_agent_mode_keeps_sibling_metadata(store: ChatThreadStore) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    store.set_title(thread.id, "Quarterly report", lock=True)
    store.set_meeting_active(thread.id, True)

    store.set_agent_mode(thread.id, "plan", changed_by="captain")
    store.set_agent_mode(thread.id, "execute", changed_by="captain")

    metadata = store.get_thread(thread.id).metadata
    assert metadata["title_locked"] is True and metadata["meeting_active"] is True
    assert metadata[AGENT_MODE_METADATA_KEY]["revision"] == 2


def test_set_agent_mode_to_the_current_mode_writes_nothing(store: ChatThreadStore) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    first = store.set_agent_mode(thread.id, "plan", changed_by="captain")
    before = _raw_metadata(store, thread.id)

    again = store.set_agent_mode(thread.id, "plan", changed_by="captain")

    assert again is not None and again.changed is False
    assert again.record == first.record
    assert _raw_metadata(store, thread.id) == before


def test_set_agent_mode_on_a_missing_thread_returns_none(store: ChatThreadStore) -> None:
    assert store.set_agent_mode("no-such-thread", "plan", changed_by="captain") is None


@pytest.mark.parametrize(
    ("mode", "changed_by"), [("auto", "captain"), ("plan", ""), ("plan", None)],
)
def test_set_agent_mode_refuses_bad_input_and_writes_nothing(
    store: ChatThreadStore, mode: Any, changed_by: Any,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    before = _raw_metadata(store, thread.id)

    with pytest.raises(ValueError):
        store.set_agent_mode(thread.id, mode, changed_by=changed_by)

    assert _raw_metadata(store, thread.id) == before


def test_set_agent_mode_replaces_an_unreadable_record(
    store: ChatThreadStore, caplog: pytest.LogCaptureFixture,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    _write_raw_metadata(store, thread.id, {"agent_mode": {"mode": "execute"}, "keep": 1})

    with caplog.at_level(logging.WARNING, logger="probos.threads"):
        transition = store.set_agent_mode(thread.id, "execute", changed_by="captain")

    assert transition is not None and transition.changed is True
    # A-8: the record names the thread's one participant, the agent it is set for.
    assert transition.record == AgentModeRecord("execute", 1, transition.record.changed_at, "captain", None, _AGENT)
    assert store.get_thread(thread.id).metadata["keep"] == 1
    assert "unreadable mode record" in caplog.text


@pytest.mark.parametrize("stored", [[1, 2], "text", 7])
def test_set_agent_mode_repairs_a_metadata_column_that_is_not_an_object(
    store: ChatThreadStore, stored: Any,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    _write_raw_metadata(store, thread.id, stored)

    transition = store.set_agent_mode(thread.id, "plan", changed_by="captain")

    assert transition is not None and transition.changed is True
    assert store.get_thread(thread.id).metadata == {AGENT_MODE_METADATA_KEY: transition.record.to_dict()}


# ── 3. what a turn reads ────────────────────────────────────────────────────


def test_read_turn_agent_mode_without_a_record_is_the_legacy_path(
    store: ChatThreadStore, caplog: pytest.LogCaptureFixture,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")

    assert read_turn_agent_mode(store, thread.id, agent_id=_AGENT) is None
    assert read_turn_agent_mode(None, thread.id, agent_id=_AGENT) is None
    assert read_turn_agent_mode(store, "", agent_id=_AGENT) is None
    # A-9 repoint (slice 1 read a thread the store does not have as one with no record): a
    # thread gone from the store cannot confirm that no mode applies to this agent there --
    # the record the Captain set may have gone with it -- so the turn is held.
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.agent_mode"):
        gone = read_turn_agent_mode(store, "no-such-thread", agent_id=_AGENT)
    assert gone == TurnAgentMode(mode="plan", record=None)
    assert "no longer in the store" in caplog.text


def test_read_turn_agent_mode_reads_the_stored_mode(store: ChatThreadStore) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    store.set_agent_mode(thread.id, "plan", changed_by="captain")
    plan = read_turn_agent_mode(store, thread.id, agent_id=_AGENT)
    store.set_agent_mode(thread.id, "execute", changed_by="captain")
    execute = read_turn_agent_mode(store, thread.id, agent_id=_AGENT)

    assert (plan.mode, plan.held, plan.record.revision) == ("plan", False, 1)
    assert (execute.mode, execute.held, execute.record.previous) == ("execute", False, "plan")


@pytest.mark.parametrize("stored", [{"mode": "execute"}, "execute", None, 1])
def test_read_turn_agent_mode_holds_an_unreadable_record_in_plan(
    store: ChatThreadStore, stored: Any, caplog: pytest.LogCaptureFixture,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    _write_raw_metadata(store, thread.id, {"agent_mode": stored})

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.agent_mode"):
        turn = read_turn_agent_mode(store, thread.id, agent_id=_AGENT)

    assert turn == TurnAgentMode(mode="plan", record=None)
    assert turn.held is True
    assert "held in plan mode" in caplog.text


def test_read_turn_agent_mode_holds_plan_when_the_store_fails(caplog: pytest.LogCaptureFixture) -> None:
    class _Broken:
        def get_thread(self, thread_id: str) -> Any:
            raise RuntimeError("database is locked")

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.agent_mode"):
        turn = read_turn_agent_mode(_Broken(), "t1", agent_id=_AGENT)

    assert turn == TurnAgentMode(mode="plan", record=None)
    assert "held in plan mode" in caplog.text


@pytest.mark.parametrize(
    ("dm_agentic", "expected"),
    [
        (DmAgenticConfig(agent_modes_enabled=True), True),
        (DmAgenticConfig(), False),
        (MagicMock(), False),
        (None, False),
    ],
    ids=["on", "default-off", "mock-config", "absent"],
)
def test_agent_modes_enabled_needs_an_exact_true(dm_agentic: Any, expected: bool) -> None:
    runtime = SimpleNamespace(config=SimpleNamespace(dm_agentic=dm_agentic))

    assert agent_modes_enabled(runtime) is expected
    assert agent_modes_enabled(None) is False
    assert dm_agentic_loop_enabled(SimpleNamespace(config=SimpleNamespace(dm_agentic=MagicMock()))) is False


# ── 4. the words the model and the Captain see ──────────────────────────────


def _turns() -> dict[str, TurnAgentMode]:
    # A-8: a record names the agent it was set for.
    return {
        "plan": TurnAgentMode("plan", AgentModeRecord("plan", 1, 1.0, "captain", None, _AGENT)),
        "execute-after-plan": TurnAgentMode("execute", AgentModeRecord("execute", 2, 2.0, "captain", "plan", _AGENT)),
        "execute-direct": TurnAgentMode("execute", AgentModeRecord("execute", 1, 1.0, "captain", None, _AGENT)),
        "held": TurnAgentMode("plan", None),
        # A-9: a readable record that governs no turn of this agent holds it with its own block.
        "unapplied": TurnAgentMode(
            "plan", None, AgentModeRecord("execute", 1, 1.0, "captain", None, "another-agent"),
        ),
    }


def test_mode_instructions_are_distinct_and_never_read_as_a_capability_gap() -> None:
    rendered = {name: render_agent_mode_instructions(turn) for name, turn in _turns().items()}

    # A-9 repoint (4 -> 5): the block for a stored record that governs no turn of this agent
    # is new prompt text, so it is checked against the capability-gap reading with the others.
    assert len(set(rendered.values())) == 5
    for name, text in rendered.items():
        assert text.startswith("\n\n## Conversation mode: "), name
        assert not is_capability_gap(text), name
    assert "asking for the plan itself" in rendered["plan"]
    assert "/mode execute" in rendered["plan"] and "/mode execute" in rendered["held"]
    assert "approving the plan drafted in plan mode" in rendered["execute-after-plan"]
    assert "approving" not in rendered["execute-direct"]
    assert "was not set for you here" in rendered["unapplied"]
    assert "could not be read" not in rendered["unapplied"]


def test_the_plan_mode_refusal_is_a_policy_outcome() -> None:
    assert getattr(agentic_dispatch, "_PLAN_MODE_TOOL_REFUSAL", None) == _REFUSAL
    assert not is_capability_gap(_REFUSAL)
    assert classify_tool_fault_error(_REFUSAL) == "permission_denied"
    never_ran = getattr(agentic_dispatch, "_NEVER_RAN_REFUSALS", frozenset())
    assert never_ran == {_REFUSAL, agentic_dispatch._DEFERRED_SCHEMA_REFUSAL}


# ── 5. the /mode command ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("/mode", True), ("  /mode plan  ", True), ("/mode execute now", True),
        ("/modes", False), ("/model plan", False), ("/Mode plan", False),
        ("please /mode plan", False), ("", False),
    ],
)
def test_is_mode_command_matches_the_first_word_exactly(message: str, expected: bool) -> None:
    assert is_mode_command(message) is expected


@pytest.mark.asyncio
async def test_mode_command_records_each_transition_three_ways(store: ChatThreadStore) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    events = _EventLog()

    planned = await _command(store, thread, "/mode plan", event_log=events)
    approved = await _command(store, thread, "/mode EXECUTE", event_log=events)

    assert (planned["applied"], planned["system"], planned["thread_id"]) == ("plan", True, thread.id)
    assert planned["agent_mode"]["revision"] == 1
    assert "Send /mode execute to approve the plan" in planned["response"]
    assert approved["applied"] == "execute" and approved["agent_mode"]["previous"] == "plan"
    assert "This approves the plan" in approved["response"]
    assert store.get_thread(thread.id).metadata[AGENT_MODE_METADATA_KEY] == approved["agent_mode"]
    messages = store.list_messages(thread.id)
    assert [(m.role, m.body) for m in messages] == [
        ("captain", "/mode plan"), ("system", planned["response"]),
        ("captain", "/mode EXECUTE"), ("system", approved["response"]),
    ]
    assert messages[3].metadata == {
        "slash_command": "mode", "applied": "execute", "agent_mode": approved["agent_mode"],
    }
    assert [(e["event"], e["category"], e["agent_id"]) for e in events.rows] == [
        (MODE_CHANGED_EVENT, "cognitive", _AGENT)
    ] * 2
    assert events.rows[1]["data"] == {"thread_id": thread.id, **approved["agent_mode"]}
    assert events.rows[1]["detail"] == "plan -> execute"


@pytest.mark.asyncio
async def test_mode_command_status_reports_what_the_next_turn_will_read(store: ChatThreadStore) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")

    unset = await _command(store, thread, "/mode")
    await _command(store, thread, "/mode plan")
    planned = await _command(store, thread, "/mode status")
    _write_raw_metadata(store, thread.id, {"agent_mode": {"mode": "execute"}})
    held = await _command(store, thread, "/mode")

    assert unset["applied"] is None and unset["agent_mode"] is None
    assert unset["response"].startswith("No mode is set")
    assert planned["response"].startswith("This conversation is in plan mode (revision 1).")
    assert planned["applied"] is None and planned["agent_mode"]["mode"] == "plan"
    assert "held in plan mode" in held["response"] and held["agent_mode"] is None


@pytest.mark.asyncio
async def test_repeating_the_current_mode_is_not_a_transition(store: ChatThreadStore) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    events = _EventLog()
    await _command(store, thread, "/mode plan", event_log=events)

    again = await _command(store, thread, "/mode plan", event_log=events)

    assert again["applied"] is None
    assert again["response"] == "This conversation is already in plan mode (revision 1)."
    assert len(events.rows) == 1


@pytest.mark.asyncio
async def test_mode_command_refuses_a_group_conversation(store: ChatThreadStore) -> None:
    thread = store.create_thread(title="Huddle", participants=[_AGENT, "science-dax"])

    result = await _command(store, thread, "/mode plan")

    assert result["applied"] is None and result["agent_mode"] is None
    assert "one-to-one conversation" in result["response"]
    assert AGENT_MODE_METADATA_KEY not in store.get_thread(thread.id).metadata


@pytest.mark.parametrize("message", ["/mode auto", "/mode plan please", "/mode `x` " + "y" * 80])
@pytest.mark.asyncio
async def test_an_unknown_mode_changes_nothing(store: ChatThreadStore, message: str) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")

    result = await _command(store, thread, message)

    assert result["response"].startswith("Unknown mode `")
    echoed = result["response"].split("`")[1]
    assert len(echoed) <= 32 and "`" not in echoed
    assert result["applied"] is None
    assert AGENT_MODE_METADATA_KEY not in store.get_thread(thread.id).metadata


@pytest.mark.asyncio
async def test_an_event_log_failure_does_not_undo_or_misreport_the_change(
    store: ChatThreadStore, caplog: pytest.LogCaptureFixture,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.commands.mode_command"):
        result = await _command(store, thread, "/mode plan", event_log=_EventLog(fail=TimeoutError("budget")))

    assert result["applied"] == "plan"
    assert result["response"].startswith("Mode set to plan")
    assert store.get_thread(thread.id).metadata[AGENT_MODE_METADATA_KEY]["mode"] == "plan"
    assert "event log did not record" in caplog.text


@pytest.mark.asyncio
async def test_a_store_failure_reports_failure_and_records_no_event(
    store: ChatThreadStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    events = _EventLog()

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(store, "set_agent_mode", _boom)
    result = await _command(store, thread, "/mode plan", event_log=events)

    assert result["response"] == "Mode command failed; please try again."
    assert result["applied"] is None and result["agent_mode"] is None
    assert events.rows == []


@pytest.mark.asyncio
async def test_mode_command_says_when_the_loop_is_off(store: ChatThreadStore) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")

    off = await _command(store, thread, "/mode plan", loop_enabled=False)
    on = await _command(store, thread, "/mode", loop_enabled=True)

    assert off["response"].endswith("(dm_agentic.enabled).")
    assert "dm_agentic.enabled" not in on["response"]


# ── 6. the route (AD-809 harness) ───────────────────────────────────────────


def _route_runtime(tmp_path: Path, *, modes: bool) -> Any:
    from probos.cognitive.dm_sanity_gate import DmSanityGate
    from probos.config import CognitiveConfig

    runtime = MagicMock()
    agent = MagicMock()
    agent.id = "test-agent"
    agent.agent_type = "science_officer"
    agent.confidence = 0.7
    runtime.registry.get.return_value = agent
    runtime.callsign_registry.get_callsign.return_value = "Ezri"
    intent_result = MagicMock()
    intent_result.result = "Acknowledged."
    intent_result.error = None
    runtime.intent_bus.send = AsyncMock(return_value=intent_result)
    runtime.config = SimpleNamespace(
        attachments=SimpleNamespace(enabled=False),
        cognitive=CognitiveConfig(),
        perception=SimpleNamespace(enabled=False, dm_force_describe_enabled=False),
        dm_targeted_lookup=SimpleNamespace(enabled=False),
        dm_agentic=DmAgenticConfig(agent_modes_enabled=modes),
    )
    runtime.llm_client = MagicMock()
    runtime.llm_client.get_health_status = MagicMock(return_value={"tiers": {}, "overall": "operational"})
    runtime.episodic_memory = MagicMock()
    runtime.episodic_memory.store = AsyncMock()
    runtime.dm_sanity_gate = DmSanityGate()
    runtime.chat_thread_store = ChatThreadStore(tmp_path / "chat_threads.db")
    runtime.event_log = _EventLog()
    for name in (
        "avatar_sampling_state", "avatar_event_bus", "conversation_pacing_scheduler",
        "vision_consumer", "perception_mode_controller", "perception_engagement_registry",
        "recreation_service", "ward_room",
    ):
        setattr(runtime, name, None)
    return runtime


def _chat_request(message: str) -> Any:
    request = MagicMock()
    request.message = message
    request.history = []
    request.attachment_ids = []
    request.thread_id = None
    request.system_trigger = False
    return request


@pytest.mark.asyncio
async def test_route_handles_mode_without_dispatching_the_message(tmp_path: Path) -> None:
    from probos.routers.agents import agent_chat

    runtime = _route_runtime(tmp_path, modes=True)
    thread = runtime.chat_thread_store.get_or_create_default_for_agent("test-agent", "Ezri")

    with patch("probos.routers.agents.is_crew_agent", return_value=True):
        result = await agent_chat("test-agent", _chat_request("/mode plan"), runtime)

    runtime.intent_bus.send.assert_not_called()
    assert (result["system"], result["thread_id"], result["applied"]) == (True, thread.id, "plan")
    # The harness leaves dm_agentic.enabled off, and the route says so.
    assert result["response"].endswith("(dm_agentic.enabled).")
    stored = runtime.chat_thread_store.get_thread(thread.id)
    assert stored.metadata[AGENT_MODE_METADATA_KEY] == result["agent_mode"]
    assert stored.title == thread.title, "the command must not auto-name the thread"
    assert [e["event"] for e in runtime.event_log.rows] == [MODE_CHANGED_EVENT]


@pytest.mark.asyncio
async def test_route_with_modes_off_dispatches_mode_text_as_before(tmp_path: Path) -> None:
    from probos.routers.agents import agent_chat

    runtime = _route_runtime(tmp_path, modes=False)
    thread = runtime.chat_thread_store.get_or_create_default_for_agent("test-agent", "Ezri")

    with patch("probos.routers.agents.is_crew_agent", return_value=True):
        await agent_chat("test-agent", _chat_request("/mode plan"), runtime)

    runtime.intent_bus.send.assert_awaited_once()
    assert runtime.intent_bus.send.await_args.args[0].params["text"] == "/mode plan"
    assert AGENT_MODE_METADATA_KEY not in runtime.chat_thread_store.get_thread(thread.id).metadata
    captain = [m for m in runtime.chat_thread_store.list_messages(thread.id) if m.role == "captain"]
    assert [(m.body, m.metadata) for m in captain] == [("/mode plan", {})]
    assert [e for e in runtime.event_log.rows if e.get("event") == MODE_CHANGED_EVENT] == []


# ── 7. the executor ─────────────────────────────────────────────────────────


async def _execute(
    runtime: Any, llm: _ScriptedLLM, *, plan_mode_tool_ids: frozenset[str] | None = None,
) -> Any:
    kwargs: dict[str, Any] = {}
    if plan_mode_tool_ids is not None:
        kwargs["plan_mode_tool_ids"] = plan_mode_tool_ids
    return await WorkItemAgenticExecutor(llm_client=llm).run(
        agent_id=_AGENT, instructions="You are Ezri.", task_text="Write the report.",
        runtime=runtime, max_iterations=4, **kwargs,
    )


@pytest.mark.asyncio
async def test_plan_mode_offers_the_allowlist_and_refuses_everything_else() -> None:
    fetch, writer, hidden = _Tool("http_fetch"), _Tool("file_writer"), _Tool("run_python")
    runtime = _runtime(_registry(fetch, writer, hidden), _Grants(["http_fetch", "file_writer"]))
    llm = _ScriptedLLM([
        ("file_writer", {"target": "report.md"}),
        ("run_python", {"target": "print(1)"}),
        ("http_fetch", {"target": "https://example.org"}),
        _PLAN_TEXT,
    ])

    outcome = await _execute(runtime, llm, plan_mode_tool_ids=PLAN_MODE_TOOL_IDS)

    assert _offered(llm.requests[0]) == ["http_fetch"]
    assert (writer.calls, hidden.calls, len(fetch.calls)) == ([], [], 1)
    assert _transcript(llm.requests[1]).count(_REFUSAL) == 1
    assert _transcript(llm.requests[2]).count(_REFUSAL) == 2
    assert outcome.final_text == _PLAN_TEXT and outcome.denied_tools == []


@pytest.mark.asyncio
async def test_without_plan_mode_the_same_run_offers_and_runs_everything() -> None:
    """Control: the narrowing above is plan mode's doing, not the fixture's."""
    fetch, writer = _Tool("http_fetch"), _Tool("file_writer")
    runtime = _runtime(_registry(fetch, writer), _Grants(["http_fetch", "file_writer"]))
    llm = _ScriptedLLM([("file_writer", {"target": "report.md"}), "Written."])

    await _execute(runtime, llm)

    assert _offered(llm.requests[0]) == ["file_writer", "http_fetch"]
    assert len(writer.calls) == 1
    assert _REFUSAL not in _transcript(llm.requests[1])


@pytest.mark.asyncio
async def test_repeated_plan_mode_refusals_are_not_a_tool_defect() -> None:
    writer, flaky = _Tool("file_writer"), _Tool("http_fetch", fail="upstream returned 503")
    runtime = _runtime(_registry(writer, flaky), _Grants(["http_fetch", "file_writer"]))
    refused = _ScriptedLLM([("file_writer", {"target": "a"}), ("file_writer", {"target": "a"}), _PLAN_TEXT])
    failing = _ScriptedLLM([("http_fetch", {"target": "a"}), ("http_fetch", {"target": "a"}), _PLAN_TEXT])

    refused_outcome = await _execute(runtime, refused, plan_mode_tool_ids=PLAN_MODE_TOOL_IDS)
    failing_outcome = await _execute(runtime, failing, plan_mode_tool_ids=PLAN_MODE_TOOL_IDS)

    assert writer.calls == [] and refused_outcome.tool_defect is None
    # Premise: the same two identical errors from a tool that RAN are a defect.
    assert failing_outcome.tool_defect is not None
    assert failing_outcome.tool_defect.tool_id == "http_fetch"


@pytest.mark.asyncio
async def test_plan_mode_arms_neither_mcp_nor_the_browser(caplog: pytest.LogCaptureFixture) -> None:
    offers: list[str] = []

    async def _create_dispatch_offer(agent_id: str, **_kwargs: Any) -> Any:
        offers.append(agent_id)
        raise RuntimeError("no MCP servers in this test")

    def _run_for(plan: bool) -> Any:
        registry = _registry(_Tool("http_fetch"), _Tool("browser"))
        runtime = _runtime(
            registry, _Grants(["http_fetch"]),
            mcp=SimpleNamespace(agent_tools_enabled=True, max_directly_offered_tools=0),
            agentic_tools=SimpleNamespace(browser_enabled=True),
            browser_tool=SimpleNamespace(domain_allowlist=None),
        )
        runtime.mcp_workbench = SimpleNamespace(create_dispatch_offer=_create_dispatch_offer)
        llm = _ScriptedLLM([_PLAN_TEXT])
        return runtime, llm, (PLAN_MODE_TOOL_IDS if plan else None)

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.agentic_dispatch"):
        runtime, planned_llm, ids = _run_for(True)
        await _execute(runtime, planned_llm, plan_mode_tool_ids=ids)
        planned_log, planned_offers = caplog.text, list(offers)
        runtime, open_llm, ids = _run_for(False)
        await _execute(runtime, open_llm, plan_mode_tool_ids=ids)

    assert planned_offers == [] and "AD-1153" not in planned_log
    assert _offered(planned_llm.requests[0]) == ["http_fetch"]
    # Premise: the same runtime without plan mode reaches both arming sites.
    assert offers == [_AGENT] and "AD-1153" in caplog.text
    assert "browser" in _offered(open_llm.requests[0])


@pytest.mark.asyncio
async def test_run_forwards_the_allowlist_only_when_set() -> None:
    calls: list[dict[str, Any]] = []

    class _Recording(WorkItemAgenticExecutor):
        async def _run_reserved(self, **arguments: Any) -> Any:
            calls.append(arguments)
            return None

    runtime = _runtime(_registry(), _Grants([]))
    for ids in (None, PLAN_MODE_TOOL_IDS):
        await _Recording(llm_client=None).run(
            agent_id=_AGENT, instructions="i", task_text="t", runtime=runtime,
            **({} if ids is None else {"plan_mode_tool_ids": ids}),
        )

    assert "plan_mode_tool_ids" not in calls[0]
    assert calls[1]["plan_mode_tool_ids"] is PLAN_MODE_TOOL_IDS
    assert {k: v for k, v in calls[1].items() if k != "plan_mode_tool_ids"} == calls[0]


@pytest.mark.parametrize(
    "ids",
    [{"web_search"}, frozenset(), frozenset({""}), frozenset({1}), ["web_search"]],
    ids=["set", "empty", "empty-id", "non-str", "list"],
)
@pytest.mark.asyncio
async def test_run_refuses_an_allowlist_that_is_not_exact(ids: Any) -> None:
    runtime = _runtime(_registry(_Tool("http_fetch")), _Grants(["http_fetch"]))
    llm = _ScriptedLLM(["never asked"])

    with pytest.raises(ValueError, match="plan_mode_tool_ids_invalid"):
        await _execute(runtime, llm, plan_mode_tool_ids=ids)
    assert llm.requests == []


@pytest.mark.asyncio
async def test_the_executor_guard_refuses_before_resolving_the_tool() -> None:
    writer = _Tool("file_writer")
    executor = DispatchToolExecutor(registry=_registry(writer))
    executor.restrict_to_plan_mode(frozenset({"http_fetch"}))

    refused = await executor.invoke(_AGENT, "file_writer", {"target": "x"})
    unknown = await executor.invoke(_AGENT, "never_registered", {})

    assert refused.error == _REFUSAL and unknown.error == _REFUSAL
    assert writer.calls == [] and executor.denied_tools == []


def test_every_tool_the_executor_can_offer_is_classified() -> None:
    """A tool added to the offer must be decided here: allowed, or withheld."""
    source = inspect.getsource(WorkItemAgenticExecutor._run_reserved)
    literal = set(re.findall(r'_ids = \["([a-z_]+)"\]', source))
    pulled = set(re.findall(r'\("([a-z_]+)", "(?:discover|claim)"', source))
    mesh = {spec[0] for spec in agentic_dispatch._MESH_TOOL_SPECS}
    reachable = literal | pulled | mesh | {LOAD_TOOLS_ID, "find_mcp_tool"}

    # Premise: the scan reads the real offer blocks, not an empty match.
    assert {"run_python", "use_skill", "browser", "standing_interest"} <= literal
    assert pulled == {"discover_work_items", "claim_work_item"}
    assert mesh == {"web_search", "read_page", "http_fetch"}
    assert reachable == PLAN_MODE_TOOL_IDS | _WITHHELD
    assert not PLAN_MODE_TOOL_IDS & _WITHHELD
    assert PARALLEL_SAFE_TOOL_IDS <= PLAN_MODE_TOOL_IDS


# ── 8. M1: the command governs the next real DM turn ────────────────────────


@pytest.mark.asyncio
async def test_m1_the_mode_command_governs_the_next_real_dm_turn(store: ChatThreadStore) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    fetch, writer = _Tool("http_fetch"), _Tool("file_writer")
    runtime = _runtime(
        _registry(fetch, writer), _Grants(["http_fetch", "file_writer"]),
        cfg=DmAgenticConfig(enabled=True, max_iterations=4, agent_modes_enabled=True),
        store=store,
    )
    events = _EventLog()

    await _command(store, thread, "/mode plan", event_log=events)
    plan_llm = _ScriptedLLM([
        ("file_writer", {"target": "report.md"}),
        ("http_fetch", {"target": "https://example.org"}),
        _PLAN_TEXT,
    ])
    planned = await _dm_turn(runtime, plan_llm, thread.id, "Write the quarterly report.")

    assert (planned["tier_used"], planned["llm_output"]) == ("agentic", _PLAN_TEXT)
    assert _offered(plan_llm.requests[0]) == ["http_fetch"]
    assert "## Conversation mode: plan\n" in plan_llm.requests[0].system_prompt
    assert _REFUSAL in _transcript(plan_llm.requests[1])
    assert (writer.calls, len(fetch.calls)) == ([], 1)

    await _command(store, thread, "/mode execute", event_log=events)
    exec_llm = _ScriptedLLM([("file_writer", {"target": "report.md"}), "Report written."])
    executed = await _dm_turn(runtime, exec_llm, thread.id, "Go ahead.")

    assert (executed["tier_used"], executed["llm_output"]) == ("agentic", "Report written.")
    assert _offered(exec_llm.requests[0]) == ["file_writer", "http_fetch"]
    assert "approving the plan drafted in plan mode" in exec_llm.requests[0].system_prompt
    assert "## Conversation mode: plan" not in exec_llm.requests[0].system_prompt
    assert writer.calls == [{"target": "report.md"}]
    assert [e["data"]["mode"] for e in events.rows] == ["plan", "execute"]


# ── 9. OFF: a stored record is inert and the turn is unchanged ──────────────


@pytest.mark.asyncio
async def test_off_a_stored_record_is_inert_and_the_model_sees_the_legacy_turn(
    store: ChatThreadStore, monkeypatch: pytest.MonkeyPatch,
) -> None:
    thread = store.get_or_create_default_for_agent(_AGENT, "Ezri")
    run_keys: list[tuple[str, ...]] = []
    real_run = WorkItemAgenticExecutor.run

    async def _spy_run(self: Any, **kwargs: Any) -> Any:
        run_keys.append(tuple(sorted(kwargs)))
        return await real_run(self, **kwargs)

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", _spy_run)

    async def _turn(cfg: DmAgenticConfig) -> tuple[Any, ...]:
        writer = _Tool("file_writer")
        runtime = _runtime(
            _registry(_Tool("http_fetch"), writer), _Grants(["http_fetch", "file_writer"]),
            cfg=cfg, store=store,
        )
        llm = _ScriptedLLM([("file_writer", {"target": "r"}), "Done."])
        decision = await _dm_turn(runtime, llm, thread.id, "Write it.")
        first = llm.requests[0]
        return first.system_prompt, tuple(_offered(first)), len(writer.calls), decision["llm_output"]

    off = DmAgenticConfig(enabled=True, max_iterations=3)
    on = DmAgenticConfig(enabled=True, max_iterations=3, agent_modes_enabled=True)
    legacy = await _turn(off)
    on_without_record = await _turn(on)
    store.set_agent_mode(thread.id, "plan", changed_by="captain")
    on_with_plan_record = await _turn(on)

    def _never(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the mode must not be consulted while modes are off")

    monkeypatch.setattr(agent_mode_module, "read_turn_agent_mode", _never)
    monkeypatch.setattr(agent_mode_module, "render_agent_mode_instructions", _never)
    off_with_plan_record = await _turn(off)

    assert legacy == on_without_record == off_with_plan_record
    assert legacy[1:] == (("file_writer", "http_fetch"), 1, "Done.")
    assert "Conversation mode" not in legacy[0]
    # Premise: the same record, with modes on, does change what the model sees.
    assert on_with_plan_record[1:3] == (("http_fetch",), 0)
    assert on_with_plan_record[0] == legacy[0] + render_agent_mode_instructions(_turns()["plan"])
    assert [keys for keys in run_keys if "plan_mode_tool_ids" in keys] == [run_keys[2]]
    assert len({keys for i, keys in enumerate(run_keys) if i != 2}) == 1
