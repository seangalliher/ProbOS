"""BF-900 (#1573): the dispatch claim does not undo a park made earlier in the same run.

The contract is ``prompts/bf-900-dispatch-claim-keeps-the-park.md``. ``CognitiveAgent._handle_work_item_dispatch``
claims the item after the run (AD-839). When the run was denied a tool, ``_run_agentic_dispatch`` has already parked
the item ``blocked`` on a capability request (AD-855); the claim used to move it straight back to ``in_progress``,
so the grant found it not blocked and never resumed it (BF-878's guard). The claim is now a compare-and-set on the
status it read.

Real: ``WorkItemStore``, ``CapabilityRequestStore`` (emitting through ``_EventBus``), ``ToolPermissionStore``,
``ToolRegistry`` (a tool only the captain rank may use), ``CapabilityGapDriver`` (subscribed to the bus),
``CommandPolicyGate``, ``build_command_escalations`` and ``SqliteCommandApprovalStore`` (T3), a ``CognitiveAgent``
built as test_ad856's ``_make_agent``, and the dispatch path ``_handle_work_item_dispatch`` -> ``_run_agentic_dispatch``
-> ``WorkItemAgenticExecutor``. Stand-ins, named: the model (``_ScriptedLLM``), the router (``_RecordingRouter``), the
event bus (``_EventBus``), the thread store (``_ThreadStore``); in T4 one concurrent writer (``_RacedStore``) and in T5
an unreadable store. The store records no ``source`` for a move (``transition_work_item`` does not read it), so "the
driver resumed it" is shown by the router's hand-back, which only the driver makes here.

Mutants (the contract's section 10): B1 is killed by T1 (and T3), B2 by T4, B3 by T5, B4 by T4, B5 by T7.

Helpers are copies, because tests do not import each other: tests/test_ad1328_s2c_resume_seam.py (``_RecordingRouter``,
``_EventBus``, ``_EventLog``, ``_Runtime``, ``_ThreadStore``, ``_FakeLLMResponse``, ``_ScriptedLLM``, ``_text_response``,
``_make_agent``), tests/test_ad1328_s2c_park_and_scope.py (``_policy``, ``_rule``, ``_Which``, ``_gate``, the filing in
``_file``) and tests/test_ad856_agentic_dispatch.py (``_FakeTool``, ``_tool_use_response``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace  # not a ProbOS class
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.capability_request import CapabilityRequestStore
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.command_escalation_park import COMMAND_ESCALATION_BLOCKED_REASON
from probos.config_models.operations import CommandPolicyConfig
from probos.events import EventType
from probos.execution.command_approvals import SqliteCommandApprovalStore
from probos.execution.command_escalation import (
    DISPATCHED_WORK_ITEM_KEY,
    CommandEscalations,
    build_command_escalations,
)
from probos.execution.command_gate import CommandPolicyGate
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import AgentMeta, AgentState, IntentMessage, IntentResult
from probos.workforce import WorkItemStore

AGENT = "counselor-001"
RESTRICTED = "restricted_tool"
PUSH = "git push origin"
CA_LOGGER = "probos.cognitive.cognitive_agent"

# --------------------------------------------------------------------------------------
# Helpers (copied; tests do not import each other)
# --------------------------------------------------------------------------------------


def _policy(*rules: dict, unmatched: str = "allow", **extra: object) -> CommandPolicyConfig:
    # pydantic's model_validate (not a ProbOS method) builds the policy from a dict
    return CommandPolicyConfig.model_validate({"rules": list(rules), "unmatched_decision": unmatched, **extra})


def _rule(name: str, pattern: list, decision: str, **extra: object) -> dict:
    base = {"name": name, "pattern": pattern, "decision": decision, "justification": f"{name} because"}
    if decision == "forbid":
        base["alternative"] = "use the governed path"
    return {**base, **extra}


_ASK_PUSH = _rule("ask-push", ["git", "push"], "escalate", justification="a push publishes work outside this session")


class _Which:
    """A recording program lookup: it never reads the real PATH and finds nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, name: str, path: str | None = None) -> None:
        self.calls.append((name, path))
        return None


def _gate(config: CommandPolicyConfig) -> CommandPolicyGate:
    return CommandPolicyGate(config, platform="linux", which=_Which(), is_file=lambda path: False)


class _FakeTool:
    """Real Tool-protocol implementation that counts invocations."""

    def __init__(self, tool_id: str) -> None:
        self._tid = tool_id
        self.invocations = 0

    @property
    def tool_id(self) -> str:
        return self._tid

    @property
    def name(self) -> str:
        return self._tid

    @property
    def tool_type(self) -> ToolType:
        return ToolType.DETERMINISTIC_FUNCTION

    @property
    def description(self) -> str:
        return f"Fake tool {self._tid}"

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    @property
    def output_schema(self) -> dict:
        return {"type": "object"}

    async def invoke(self, params: dict, context: dict | None = None) -> ToolResult:
        self.invocations += 1
        return ToolResult(output="ok")


class _FakeLLMResponse:
    def __init__(self, content_blocks: list, content: str = "", tokens: int = 1) -> None:
        self.content_blocks = content_blocks
        self.content = content
        self.tokens_used = tokens


class _ScriptedLLM:
    """Returns the queued responses in order; counts its calls. A call past the script answers ``done``."""

    def __init__(self) -> None:
        self._responses: list[_FakeLLMResponse] = []
        self.calls = 0

    def queue(self, *responses: _FakeLLMResponse) -> None:
        self._responses.extend(responses)

    async def complete(self, req: Any, **_kwargs: Any) -> _FakeLLMResponse:
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return _FakeLLMResponse(content_blocks=[], content="done")


def _text_response(text: str) -> _FakeLLMResponse:
    return _FakeLLMResponse(content_blocks=[], content=text, tokens=1)


def _tool_use_response(tool_id: str) -> _FakeLLMResponse:
    from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock

    block = ToolUseBlock(tool_call=ToolCallRequest(name=tool_id, arguments={}))
    return _FakeLLMResponse(content_blocks=[block], content="", tokens=1)


def _make_agent(*, llm: Any, runtime: Any) -> Any:
    """Build a minimal CognitiveAgent without running __init__ (tests/test_ad856_agentic_dispatch.py)."""
    from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES

    _DECISION_CACHES.pop("counselor", None)

    class _TestCognitiveAgent(CognitiveAgent):
        _handled_intents = {"test_intent"}

    agent = object.__new__(_TestCognitiveAgent)
    agent.instructions = "Test instructions."
    agent.agent_type = "counselor"
    agent.id = AGENT
    agent.callsign = "Ezri"
    agent.department = "counseling"
    agent.rank = "ensign"
    agent.confidence = 0.5
    agent.meta = AgentMeta()
    agent.state = AgentState.ACTIVE
    agent.trust_score = 0.5
    agent._llm_client = llm
    agent._runtime = runtime
    agent._skills = {}
    agent._strategy_advisor = None
    agent._last_fallback_info = None
    return agent


class _RecordingRouter:
    """Stub WorkItemRouter that records re-dispatch calls (AD-855's shape)."""

    def __init__(self) -> None:
        self.dispatched: list[dict[str, Any]] = []

    async def on_work_item_created(self, event: dict[str, Any]) -> None:
        self.dispatched.append(event)

    async def dispatch_work_item(self, wi: dict[str, Any]) -> bool:
        self.dispatched.append({"type": "work_item_created", "data": {"work_item": wi}})
        return True

    def is_dispatchable(self, wi: dict[str, Any]) -> bool:
        return True


class _EventBus:
    """``emit`` is synchronous and spawns a task per listener while holding the reference (BF-639)."""

    def __init__(self) -> None:
        self._listeners: list[Any] = []
        self._tasks: set[asyncio.Task[Any]] = set()

    def add_event_listener(self, fn: Any) -> None:
        self._listeners.append(fn)

    def emit(self, event_type: Any, data: dict[str, Any]) -> None:
        type_str = str(getattr(event_type, "value", event_type))
        event = {"type": type_str, "data": dict(data or {}), "timestamp": time.time()}
        for fn in self._listeners:
            task = asyncio.create_task(fn(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Await every listener task, including ones they spawn in turn."""
        while self._tasks:
            pending = tuple(self._tasks)
            try:
                await asyncio.gather(*pending)
            finally:
                self._tasks.difference_update(task for task in pending if task.done())


class _EventLog:
    """``log`` answers a positive row id, which the dispatch run's AD-1224 hooks count as acknowledged."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def log(self, *, category: str, event: str, detail: str = "", **_kw: Any) -> int:
        self.events.append((category, event))
        return len(self.events)


class _Runtime(SimpleNamespace):
    """Exactly the attributes the dispatch run, the driver and the park read."""


class _ThreadStore:
    """Stands in for the chat thread store: the one default thread the handler writes to."""

    def __init__(self) -> None:
        self.thread = SimpleNamespace(id="thread-1")
        self.messages: list[dict[str, Any]] = []

    def get_or_create_default_for_agent(self, agent_id: str, agent_callsign: str) -> Any:
        return self.thread

    def append_message(
        self, thread_id: str, *, author_id: str, role: str, body: str, metadata: dict | None = None, **_kw: Any,
    ) -> None:
        self.messages.append({"thread_id": thread_id, "author_id": author_id, "role": role, "body": body})


class _Transitions:
    """The work-item store's ``emit_event``: every status move, in order, as (item id, old, new)."""

    def __init__(self) -> None:
        self.moves: list[tuple[str, str, str]] = []

    def __call__(self, event_type: Any, data: dict[str, Any]) -> None:
        if event_type == EventType.WORK_ITEM_STATUS_CHANGED:
            self.moves.append((data["work_item"]["id"], data["old_status"], data["new_status"]))

    def of(self, item_id: str) -> list[tuple[str, str]]:
        return [(old, new) for wid, old, new in self.moves if wid == item_id]


class _Wired:
    def __init__(self, **parts: Any) -> None:
        self.__dict__.update(parts)


@pytest.fixture
async def wired(tmp_path: Path) -> AsyncIterator[_Wired]:
    transitions = _Transitions()
    work_items = WorkItemStore(db_path=str(tmp_path / "wis.db"), emit_event=transitions, tick_interval=1000)
    await work_items.start()
    bus = _EventBus()
    requests = CapabilityRequestStore(db_path=str(tmp_path / "cap.db"), emit_event=bus.emit, trust_network=MagicMock())
    await requests.start()
    perms = ToolPermissionStore(db_path=str(tmp_path / "tool_permissions.db"))
    await perms.start()
    registry = ToolRegistry()
    restricted = _FakeTool(RESTRICTED)
    # Captain-only: an ensign resolves to no access, so the call raises ToolPermissionDenied (test_ad856:217).
    registry.register(restricted, provider="test", default_permissions={"captain": "full"})
    registry.set_permission_store(perms)
    router = _RecordingRouter()
    runtime = _Runtime(
        work_item_router=router,
        work_item_store=work_items,
        capability_request_store=requests,
        event_log=_EventLog(),
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=True)),
        intent_bus=None,
        emit_event=None,
        tool_registry=registry,
        tool_permission_store=perms,
        chat_thread_store=_ThreadStore(),
    )
    driver = CapabilityGapDriver(runtime=runtime, work_item_store=work_items, capability_request_store=requests)
    runtime.capability_gap_driver = driver
    bus.add_event_listener(driver.on_capability_event)
    llm = _ScriptedLLM()
    try:
        yield _Wired(
            runtime=runtime, driver=driver, router=router, bus=bus, work_items=work_items, requests=requests,
            transitions=transitions, restricted=restricted, llm=llm, agent=_make_agent(llm=llm, runtime=runtime),
        )
    finally:
        await bus.drain()
        await perms.stop()
        await requests.stop()
        await work_items.stop()


async def _task(wired: _Wired, title: str, *, assigned_to: str | None = None) -> Any:
    item = await wired.work_items.create_work_item(
        title=title, description=title, work_type="task", assigned_to=assigned_to, created_by="captain",
    )
    assert (await wired.work_items.get_work_item(item.id)).status == "open"  # premise
    return item


async def _dispatch(wired: _Wired, item: Any, *script: _FakeLLMResponse) -> IntentResult:
    """One run of ``item`` through the real handler, as the router's hop builds it (``mesh/work_item_router.py``)."""
    calls_before = wired.llm.calls
    wired.llm.queue(*script)
    intent = IntentMessage(
        intent="work_item_dispatched",
        params={"work_item_id": item.id, "title": item.title, "description": item.description},
        target_agent_id=AGENT,
    )
    result = await wired.agent._handle_work_item_dispatch(intent)
    assert wired.llm.calls - calls_before == len(script), "premise: the run made exactly the scripted calls"
    return result


async def _current(wired: _Wired, item: Any) -> Any:
    current = await wired.work_items.get_work_item(item.id)
    assert current is not None
    return current


def _bf900_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        rec.getMessage() for rec in caplog.records
        if rec.name == CA_LOGGER and rec.levelno == logging.WARNING and rec.getMessage().startswith("BF-900")
    ]


# --------------------------------------------------------------------------------------
# The seam (the issue's reproduction, with no fake gap driver)
# --------------------------------------------------------------------------------------


async def test_a_denied_tool_leaves_the_item_parked_and_its_grant_resumes_it_once(wired: _Wired) -> None:
    """T1. Dispatch an item whose agent calls a tool its rank denies: the item is still ``blocked`` on the pending
    request (the claim did not undo the park), the agent holds it (BF-607), and nothing was re-dispatched. Fulfilling
    the request then produces exactly one ``blocked -> in_progress`` and one hand-back of this item to the router."""
    item = await _task(wired, "use the restricted tool")

    result = await _dispatch(wired, item, _tool_use_response(RESTRICTED), _text_response("Waiting for access."))

    assert result.success is True
    assert wired.restricted.invocations == 0  # premise: denied at the permission check, never run
    (req,) = [r for r in await wired.requests.list_pending() if r.work_item_id == item.id]
    assert req.target == RESTRICTED  # premise: the denial reached the driver and filed a request
    parked = await _current(wired, item)
    assert parked.status == "blocked"
    assert parked.metadata["capability_request_id"] == req.id
    assert parked.metadata["blocked_reason"] == RESTRICTED
    assert parked.assigned_to == AGENT  # BF-607's claim still assigns a parked item
    assert wired.transitions.of(item.id) == [("open", "blocked")]
    assert wired.router.dispatched == []

    await wired.requests.mark_fulfilled(req.id)
    await wired.bus.drain()

    assert wired.transitions.of(item.id) == [("open", "blocked"), ("blocked", "in_progress")]
    assert [e["data"]["work_item"]["id"] for e in wired.router.dispatched] == [item.id]
    assert (await _current(wired, item)).status == "in_progress"


async def test_a_run_with_no_denial_still_claims_the_item(wired: _Wired) -> None:
    """T2, the control: the same rig and a clean run. The claim moves the item ``open -> in_progress`` as before."""
    item = await _task(wired, "a task with nothing denied")

    result = await _dispatch(wired, item, _text_response("Done."))

    assert result.success is True
    current = await _current(wired, item)
    assert current.status == "in_progress"
    assert current.assigned_to == AGENT
    assert "capability_request_id" not in (current.metadata or {})
    assert wired.transitions.of(item.id) == [("open", "in_progress")]
    assert await wired.requests.list_pending() == []
    assert wired.router.dispatched == []


async def test_a_command_park_after_a_gap_park_in_one_run_ends_on_the_command_request(
    wired: _Wired, tmp_path: Path,
) -> None:
    """T3, the S2c assertion: the claim's ``blocked`` skip does not suppress AD-1328 S2c's command park, which runs
    after the claim. One run parks the item on a capability gap and then on a pending command escalation in its scope:
    the command park writes last (``blocked -> blocked`` with its metadata), so the item ends parked on the command
    request, the same end state as on the base, where the claim's ``in_progress`` came between the two parks. The gap
    request stays pending with no item parked on it (the contract's section 9, item 2)."""
    approvals = SqliteCommandApprovalStore(db_path=str(tmp_path / "command_approvals.db"))
    await approvals.start()
    try:
        gate = _gate(_policy(_ASK_PUSH))
        escalations = build_command_escalations(
            gate=gate, approvals=approvals, requests=wired.requests, work_items=wired.work_items, inbox=None,
        )
        assert isinstance(escalations, CommandEscalations)  # premise: the approval route is wired
        wired.runtime.command_escalations = escalations
        wired.runtime.command_approval_store = approvals
        item = await _task(wired, "push and use the restricted tool", assigned_to=AGENT)
        verdict = gate.judge(PUSH, site="run_command_tool", search_path=None)
        assert verdict.decision == "escalate"  # premise: the policy asks about this command
        outcome = await escalations.resolve(
            verdict, command=PUSH, context={"agent_id": AGENT, DISPATCHED_WORK_ITEM_KEY: item.id},
        )
        assert outcome.verdict.approval is not None and outcome.verdict.approval["state"] == "filed"
        command_request = outcome.verdict.approval["request_id"]
        assert (await _current(wired, item)).status == "open"  # premise: filing parks nothing

        result = await _dispatch(wired, item, _tool_use_response(RESTRICTED), _text_response("Waiting."))

        assert result.success is True
        pending = {r.id: r for r in await wired.requests.list_pending()}
        (gap_request,) = [r for r in pending.values() if r.target == RESTRICTED]  # premise: the gap park ran
        assert command_request in pending
        current = await _current(wired, item)
        assert current.status == "blocked"
        assert current.metadata["capability_request_id"] == command_request
        assert current.metadata["blocked_reason"] == COMMAND_ESCALATION_BLOCKED_REASON
        assert gap_request.id != command_request
        assert wired.transitions.of(item.id) == [("open", "blocked")]
    finally:
        await approvals.stop()


# --------------------------------------------------------------------------------------
# The compare-and-set and its degrade paths
# --------------------------------------------------------------------------------------


class _RacedStore:
    """The real store with one concurrent writer: after the claim's read returns, another run parks the item."""

    def __init__(self, real: WorkItemStore) -> None:
        self._real = real
        self._raced = False

    async def get_work_item(self, work_item_id: str) -> Any:
        item = await self._real.get_work_item(work_item_id)
        if not self._raced:
            self._raced = True
            parked = await self._real.transition_work_item(
                work_item_id, "blocked", source="another-run",
                metadata_patch={"blocked_reason": "another_run", "capability_request_id": "req-other"},
            )
            assert parked is not None  # premise: the concurrent park landed
        return item

    async def update_work_item(self, work_item_id: str, **updates: Any) -> Any:
        return await self._real.update_work_item(work_item_id, **updates)

    async def transition_work_item(self, *args: Any, **kwargs: Any) -> Any:
        return await self._real.transition_work_item(*args, **kwargs)


def _gated_off_agent(store: Any) -> Any:
    """The AD-839 single-shot path: the agentic run is off, ``handle_intent`` answers, then the claim runs."""
    runtime = SimpleNamespace(
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=False)),
        work_item_store=store,
        chat_thread_store=None,
    )
    agent = _make_agent(llm=AsyncMock(), runtime=runtime)
    agent.handle_intent = AsyncMock(
        return_value=IntentResult(intent_id="dm", agent_id=AGENT, success=True, result="On it.", confidence=0.5),
    )
    return agent


def _dispatch_intent(work_item_id: str) -> IntentMessage:
    return IntentMessage(
        intent="work_item_dispatched",
        params={"work_item_id": work_item_id, "title": "a task", "description": "a task"},
        target_agent_id=AGENT,
    )


async def test_a_move_made_after_the_read_is_not_undone(wired: _Wired, caplog: pytest.LogCaptureFixture) -> None:
    """T4. Another writer parks the item between the claim's read (``open``) and its move. The store's in-transaction
    check refuses the claim, the item stays ``blocked``, and the warning names the item and the status read."""
    caplog.set_level(logging.INFO, logger=CA_LOGGER)
    item = await _task(wired, "raced")
    agent = _gated_off_agent(_RacedStore(wired.work_items))

    result = await agent._handle_work_item_dispatch(_dispatch_intent(item.id))

    assert result.success is True
    current = await _current(wired, item)
    assert current.status == "blocked"
    assert current.metadata["capability_request_id"] == "req-other"
    assert wired.transitions.of(item.id) == [("open", "blocked")]
    warnings = _bf900_warnings(caplog)
    assert len(warnings) == 1
    assert item.id in warnings[0] and "'open'" in warnings[0]


class _UnreadableStore:
    """A store whose read raises or finds nothing; it records any move it is asked for."""

    def __init__(self, *, raises: bool) -> None:
        self._raises = raises
        self.transitions: list[tuple[str, str, str | None]] = []
        self.updates: list[str] = []

    async def get_work_item(self, work_item_id: str) -> Any:
        if self._raises:
            raise RuntimeError("store down")
        return None

    async def update_work_item(self, work_item_id: str, **updates: Any) -> Any:
        self.updates.append(work_item_id)
        return None

    async def transition_work_item(
        self, work_item_id: str, new_status: str, source: str = "system", *, expected_status: str | None = None,
    ) -> Any:
        self.transitions.append((work_item_id, new_status, expected_status))
        return SimpleNamespace(id=work_item_id, status=new_status)


@pytest.mark.parametrize("raises", [True, False], ids=["raises", "missing"])
async def test_an_item_that_cannot_be_read_is_not_moved(raises: bool, caplog: pytest.LogCaptureFixture) -> None:
    """T5. With no status read there is nothing to compare against, so no move is attempted (no unconditional
    fallback), and a BF-900 warning names the item."""
    caplog.set_level(logging.INFO, logger=CA_LOGGER)
    store = _UnreadableStore(raises=raises)
    agent = _gated_off_agent(store)

    result = await agent._handle_work_item_dispatch(_dispatch_intent("wi-unreadable"))

    assert result.success is True
    assert store.transitions == []
    assert store.updates == []
    warnings = _bf900_warnings(caplog)
    assert len(warnings) == 1
    assert "wi-unreadable" in warnings[0]


async def test_an_item_parked_before_the_run_stays_parked(wired: _Wired) -> None:
    """T6, the contract's section 9 item 1, pinned: an item already ``blocked`` when this agent's claim reads it (an
    earlier run's park) stays parked on its earlier request after a clean run, and the agent still claims it."""
    item = await _task(wired, "parked earlier")
    earlier = await wired.requests.file_request(
        agent_id="another-agent", kind="grant", target="another_tool", rationale="an earlier run", work_item_id=item.id,
    )
    assert await wired.driver.block_on_request(work_item_id=item.id, request_id=earlier.id, reason="another_tool")

    result = await _dispatch(wired, item, _text_response("Nothing to do."))

    assert result.success is True
    current = await _current(wired, item)
    assert current.status == "blocked"
    assert current.metadata["capability_request_id"] == earlier.id
    assert current.assigned_to == AGENT
    assert wired.transitions.of(item.id) == [("open", "blocked")]
    assert wired.router.dispatched == []


async def test_an_item_created_blocked_with_no_request_is_not_moved(
    wired: _Wired, caplog: pytest.LogCaptureFixture,
) -> None:
    """T7, the contract's section 9 item 1 with no request behind it (Amendment A1). The work-item API keeps a status
    it is given (``routers/workforce.py:223``), so a dispatchable task can be created already ``blocked`` on a
    dependency, and the router dispatches on dispatchability, not status (``mesh/work_item_router.py:59-66``, ``:187``).
    The claim reads ``blocked`` and does not move it. Its INFO line states only what it read, because nothing links
    the item to a request."""
    caplog.set_level(logging.INFO, logger=CA_LOGGER)
    item = await wired.work_items.create_work_item(
        title="waits on a dependency", description="waits on a dependency", work_type="task",
        created_by="captain", status="blocked",
        metadata={"blocked_reason": "awaiting dependency", "dispatchable": True},
    )
    assert (await _current(wired, item)).status == "blocked"  # premise: created blocked, not moved there

    result = await _dispatch(wired, item, _text_response("Done."))

    assert result.success is True
    current = await _current(wired, item)
    assert current.status == "blocked"
    assert "capability_request_id" not in current.metadata  # premise: no request linkage
    assert await wired.requests.list_pending() == []
    assert current.assigned_to == AGENT
    assert wired.transitions.of(item.id) == []
    assert wired.router.dispatched == []
    infos = [
        rec.getMessage() for rec in caplog.records
        if rec.name == CA_LOGGER and rec.levelno == logging.INFO and rec.getMessage().startswith("BF-900")
    ]
    assert infos == [f"BF-900: work_item {item.id} was blocked when read; the claim does not move it"]
    assert _bf900_warnings(caplog) == []
