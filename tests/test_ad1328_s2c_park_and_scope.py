"""AD-1328 S2c (#1530), M1: the dispatched-item scope, its arming and the park (tests only).

The contract is ``prompts/ad-1328-s2c-command-escalation-resume.md`` ("Tests", ``test_ad1328_s2c_park_and_scope.py``,
P1-P13). The module under test is ``cognitive/command_escalation_park.py``: after a dispatched work item's run it finds
the command escalation the item waits for and parks the item on it through ``CapabilityGapDriver.block_on_request``, so
the Captain's approval resumes the item (AD-855) and a denial cancels it. Around it: ``escalation_scope``'s one added
branch (the ``DISPATCHED_WORK_ITEM_KEY`` context key), the executor's allowlist for that key, and the arming in
``CognitiveAgent._run_agentic_dispatch`` (the key travels only when the command approval route is wired).

Nothing here starts a shell. Every gate takes ``platform="linux"`` and a ``which`` that finds nothing, so the file reads
the same on any host. The stores (work items, capability requests, command approvals) are real SQLite files in
``tmp_path``; the router is the recorder AD-855's tests use. Requests are filed by the real filer
(``CommandEscalations.resolve`` over those stores, built by ``build_command_escalations``), decided by the real
``decide_capability_request`` (which drives ``fulfil_approval`` / ``record_denial`` and the AD-855 driver over the event
bus), and parked by the real ``park_on_command_escalation`` and ``CapabilityGapDriver``. The seam through
``CognitiveAgent._handle_work_item_dispatch`` and the real executor is ``test_ad1328_s2c_resume_seam.py`` (P-S1).

Mutants (the contract's "Mutation rows"; the orchestrator runs them, this file does not): MX-1 is killed by P1, MX-2 by
P5, MX-3 by P9 (and by P7's control), MX-4 by P8, MX-5 by P6, MX-6 by P3. MX-7 (the ``park_on_command_escalation`` call
removed from ``_handle_work_item_dispatch``) is the seam's alone: nothing in this file runs ``CognitiveAgent``'s park call.

Beyond P1-P13, four tests (X1-X4) cover the branches of the park module the contract's tests do not reach: the inert
inputs, a parking write that raises, an approval that cannot be read, and a creation time that is not a finite number. P3
also carries one row the contract does not list (a real route with no item id). None of them changes P1-P13.

Helpers are copies, because tests do not import each other: S1's ``_policy`` / ``_rule``, and from
tests/test_ad1328_s2b_seam_and_wiring.py ``_ASK_PUSH``, ``_Which``, ``_gate``, ``_RecordingRouter``, ``_EventBus``,
``_EventLog``, ``_Runtime``, ``wired``, ``approvals``, ``_approve`` and ``_status``; from
tests/test_ad856_agentic_dispatch.py ``_FakeLLMResponse``, ``_ScriptedLLM``, ``_text_response``, ``_FakeGapDriver``,
``_make_agent`` and ``_make_runtime``. The spawn recorder (``_Process``, ``_Tree``, ``_Spawns``, ``spawns``) is not
copied: no test here runs a command (the filer only files or refuses, and no ``RunCommandTool`` is registered), so
there is nothing for a recorder to record; the one that does run commands is the seam's.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequestStore
from probos.cognitive import agentic_dispatch
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor, WorkItemAgenticOutcome
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.command_escalation_park import (
    COMMAND_ESCALATION_BLOCKED_REASON,
    TOOL_CALL_SITE,
    awaited_command_request,
    park_on_command_escalation,
)
from probos.config_models.operations import CommandPolicyConfig
from probos.execution.command_approvals import (
    COMMAND_APPROVAL_ACTION,
    COMMAND_APPROVAL_TOOL_ID,
    WORK_ITEM_SCOPE_PREFIX,
    SqliteCommandApprovalStore,
)
from probos.execution.command_escalation import (
    DISPATCHED_WORK_ITEM_KEY,
    CommandEscalations,
    EscalationScope,
    build_command_escalations,
    command_approval_payload,
    escalation_scope,
)
from probos.execution.command_gate import CommandPolicyGate
from probos.routers.capability_requests import decide_capability_request
from probos.tools.permissions import ToolPermissionStore
from probos.tools.registry import ToolRegistry
from probos.types import AgentMeta, AgentState
from probos.workforce import WorkItemStore

# --------------------------------------------------------------------------------------
# Helpers (copied; tests do not import each other)
# --------------------------------------------------------------------------------------

PUSH = "git push origin"
PULL = "git pull origin"
_ASK_PUSH_WHY = "a push publishes work outside this session"
_ASK_PULL_WHY = "a pull rewrites the work tree"
AGENT = "agent-1"
PARK_LOGGER = "probos.cognitive.command_escalation_park"


def _policy(*rules: dict, unmatched: str = "allow", **extra: object) -> CommandPolicyConfig:
    """S1's helper (tests/test_ad1328_s1_policy_evaluation.py)."""
    return CommandPolicyConfig.model_validate({"rules": list(rules), "unmatched_decision": unmatched, **extra})


def _rule(name: str, pattern: list, decision: str, **extra: object) -> dict:
    """S1's helper (tests/test_ad1328_s1_policy_evaluation.py)."""
    base = {"name": name, "pattern": pattern, "decision": decision, "justification": f"{name} because"}
    if decision == "forbid":
        base["alternative"] = "use the governed path"
    return {**base, **extra}


_ASK_PUSH = _rule("ask-push", ["git", "push"], "escalate", justification=_ASK_PUSH_WHY)
_ASK_PULL = _rule("ask-pull", ["git", "pull"], "escalate", justification=_ASK_PULL_WHY)


class _Which:
    """A recording program lookup: it never reads the real PATH and finds nothing."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, name: str, path: str | None = None) -> None:
        self.calls.append((name, path))
        return None


def _gate(config: CommandPolicyConfig, *, platform: str = "linux", which: _Which | None = None) -> CommandPolicyGate:
    return CommandPolicyGate(
        config, platform=platform, which=which if which is not None else _Which(), is_file=lambda path: False,
    )


class _FakeLLMResponse:
    def __init__(self, content_blocks: list, content: str = "", tokens: int = 1) -> None:
        self.content_blocks = content_blocks
        self.content = content
        self.tokens_used = tokens


class _ScriptedLLM:
    """Returns a scripted sequence of responses; counts its calls."""

    def __init__(self, responses: list[_FakeLLMResponse]) -> None:
        self._responses = list(responses)
        self.last_tools: list[dict] | None = None
        self.calls = 0

    async def complete(self, req: Any, **_kwargs: Any) -> _FakeLLMResponse:
        self.calls += 1
        self.last_tools = list(req.tools or [])
        if self._responses:
            return self._responses.pop(0)
        # Default terminal: text-only response ends the loop.
        return _FakeLLMResponse(content_blocks=[], content="done")


def _text_response(text: str) -> _FakeLLMResponse:
    return _FakeLLMResponse(content_blocks=[], content=text, tokens=1)


class _FakeGapDriver:
    """Records each gap and parks nothing. BF-900: so no test with it can show the dispatch claim undoing
    a park; ``tests/test_bf900_dispatch_claim_keeps_the_park.py`` runs the real ``CapabilityGapDriver``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def on_capability_gap(self, *, work_item_id: str, gap_target: str, agent_id: str) -> None:
        self.calls.append((work_item_id, gap_target, agent_id))
        return None


def _make_agent(*, llm: Any, runtime: Any, rank: str = "ensign", agent_id: str = "counselor-001") -> Any:
    """Build a minimal CognitiveAgent without running __init__ (tests/test_ad856_agentic_dispatch.py)."""
    from probos.cognitive.cognitive_agent import CognitiveAgent, _DECISION_CACHES

    _DECISION_CACHES.pop("counselor", None)

    class _TestCognitiveAgent(CognitiveAgent):
        _handled_intents = {"test_intent"}

    agent = object.__new__(_TestCognitiveAgent)
    agent.instructions = "Test instructions."
    agent.agent_type = "counselor"
    agent.id = agent_id
    agent.callsign = "Ezri"
    agent.department = "counseling"
    agent.rank = rank
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


def _make_runtime(*, enabled: bool, registry: Any, perm_store: Any, gap_driver: Any, intent_bus: Any = None) -> Any:
    return SimpleNamespace(
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=enabled)),
        tool_registry=registry,
        tool_permission_store=perm_store,
        capability_gap_driver=gap_driver,
        intent_bus=intent_bus,
        emit_event=None,
    )


# --------------------------------------------------------------------------------------
# The wired system (tests/test_ad1328_s2b_seam_and_wiring.py, copied)
# --------------------------------------------------------------------------------------


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
    """The runtime's local event dispatch, faithfully enough to prove the chain: ``emit`` is synchronous and spawns a
    task per listener while holding the reference (BF-639), so FULFILLED really travels store -> listener -> driver."""

    def __init__(self) -> None:
        self._listeners: list[Any] = []
        self._tasks: set[asyncio.Task[Any]] = set()
        self.emitted: list[str] = []

    def add_event_listener(self, fn: Any) -> None:
        self._listeners.append(fn)

    def emit(self, event_type: Any, data: dict[str, Any]) -> None:
        type_str = str(getattr(event_type, "value", event_type))
        self.emitted.append(type_str)
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
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def log(self, *, category: str, event: str, detail: str = "", **_kw: Any) -> None:
        self.events.append((category, event))


class _Runtime(SimpleNamespace):
    """Exactly the attributes the route, the escalation service, the driver and the park read."""


class _Wired:
    """The AD-855 loop wired the way startup wires it."""

    def __init__(
        self, runtime: _Runtime, driver: CapabilityGapDriver, router: _RecordingRouter, bus: _EventBus,
        work_items: WorkItemStore, requests: CapabilityRequestStore,
    ) -> None:
        self.runtime = runtime
        self.driver = driver
        self.router = router
        self.bus = bus
        self.work_items = work_items
        self.requests = requests


@pytest.fixture
async def wired(tmp_path: Path) -> AsyncIterator[_Wired]:
    work_items = WorkItemStore(db_path=str(tmp_path / "wis.db"), tick_interval=1000)
    await work_items.start()
    bus = _EventBus()
    trust = MagicMock()
    requests = CapabilityRequestStore(
        db_path=str(tmp_path / "cap.db"), emit_event=bus.emit, trust_network=trust,
    )
    await requests.start()
    router = _RecordingRouter()
    runtime = _Runtime(
        work_item_router=router,
        work_item_store=work_items,
        capability_request_store=requests,
        trust_network=trust,
        event_log=_EventLog(),
        config=SimpleNamespace(),
    )
    driver = CapabilityGapDriver(
        runtime=runtime, work_item_store=work_items, capability_request_store=requests,
    )
    runtime.capability_gap_driver = driver
    bus.add_event_listener(driver.on_capability_event)
    try:
        yield _Wired(runtime, driver, router, bus, work_items, requests)
    finally:
        await bus.drain()
        await requests.stop()
        await work_items.stop()


@pytest.fixture
async def approvals(tmp_path: Path) -> AsyncIterator[SqliteCommandApprovalStore]:
    store = SqliteCommandApprovalStore(db_path=str(tmp_path / "command_approvals.db"))
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


async def _approve(wired: _Wired, request_id: str, *, approve: bool = True) -> dict[str, Any]:
    response = await decide_capability_request(
        request_id,
        # A reason is REQUIRED on denial (``CapabilityRequestDecideRequest`` validates it), so it cannot be omitted here.
        CapabilityRequestDecideRequest(approve=approve, reason="" if approve else "not needed"),
        runtime=wired.runtime,
    )
    await wired.bus.drain()
    return response


async def _status(wired: _Wired, item: Any) -> str:
    current = await wired.work_items.get_work_item(item.id)
    assert current is not None
    return str(current.status)


# --------------------------------------------------------------------------------------
# The rig: the wired loop plus the command approval route, as startup builds them for a policy with two escalate rules
# --------------------------------------------------------------------------------------


@dataclasses.dataclass
class _Rig:
    wired: _Wired
    approvals: SqliteCommandApprovalStore
    gate: CommandPolicyGate
    escalations: CommandEscalations

    @property
    def runtime(self) -> _Runtime:
        return self.wired.runtime

    @property
    def router(self) -> _RecordingRouter:
        return self.wired.router

    @property
    def requests(self) -> CapabilityRequestStore:
        return self.wired.requests

    async def item(self, title: str) -> Any:
        """A task assigned to the asking agent and ``in_progress``: what a dispatched item is when its run has ended and
        the park runs (``_handle_work_item_dispatch`` claimed it first)."""
        item = await self.wired.work_items.create_work_item(
            title=title, description=title, work_type="task", assigned_to=AGENT, created_by="captain",
        )
        await self.wired.work_items.transition_work_item(item.id, "in_progress", source=AGENT)
        assert await self.status(item) == "in_progress"
        return item

    async def status(self, item: Any) -> str:
        return await _status(self.wired, item)

    async def metadata(self, item: Any) -> dict[str, Any]:
        current = await self.wired.work_items.get_work_item(item.id)
        assert current is not None
        return dict(current.metadata or {})

    def dispatched_ids(self) -> list[str]:
        """The ids of the work items the router was handed to re-dispatch, in order."""
        return [event["data"]["work_item"]["id"] for event in self.router.dispatched]


@pytest.fixture
async def rig(wired: _Wired, approvals: SqliteCommandApprovalStore) -> _Rig:
    gate = _gate(_policy(_ASK_PUSH, _ASK_PULL))
    escalations = build_command_escalations(
        gate=gate, approvals=approvals, requests=wired.requests, work_items=wired.work_items, inbox=None,
    )
    assert isinstance(escalations, CommandEscalations)
    wired.runtime.command_escalations = escalations
    wired.runtime.command_approval_store = approvals
    return _Rig(wired, approvals, gate, escalations)


async def _file(
    rig: _Rig, command: str, *, agent: str = AGENT, item: Any = None, thread: str | None = None,
) -> str:
    """File ``command``'s escalation through the real filer, as the tool path does: judged at ``run_command_tool``, in
    the context ``ToolRegistry.check_and_invoke`` builds (``agent_id``, the dispatched item's key, a thread)."""
    context: dict[str, Any] = {"agent_id": agent}
    if item is not None:
        context[DISPATCHED_WORK_ITEM_KEY] = item.id
    if thread is not None:
        context["thread_id"] = thread
    verdict = rig.gate.judge(command, site="run_command_tool", search_path=None)
    assert verdict.decision == "escalate", command  # premise: the policy asks about this command
    outcome = await rig.escalations.resolve(verdict, command=command, context=context)
    assert outcome.verdict.approval is not None and outcome.message is not None
    assert outcome.verdict.approval["state"] == "filed", outcome.verdict.approval
    request_id = outcome.verdict.approval["request_id"]
    assert isinstance(request_id, str) and request_id
    return request_id


async def _park(rig: _Rig, item: Any, *, agent: str = AGENT, since: float = 0.0) -> str:
    return await park_on_command_escalation(rig.runtime, agent_id=agent, work_item_id=item.id, since=since)


async def _awaited(rig: _Rig, item: Any, *, since: float = 0.0) -> str:
    """What the park would take, without parking: the read half only."""
    return await awaited_command_request(rig.runtime, agent_id=AGENT, work_item_id=item.id, since=since)


async def _pending_ids(rig: _Rig) -> set[str]:
    return {req.id for req in await rig.requests.list_pending()}


def _run_began() -> float:
    """When a run began, for a request it files: a second before now (the request store stamps its own ``time.time()``,
    whose resolution on Windows is coarser than the filing takes, so the boundary is not left to the clock)."""
    return time.time() - 1.0


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """The WARNING messages the park module logged."""
    return [rec.getMessage() for rec in caplog.records if rec.name == PARK_LOGGER and rec.levelno == logging.WARNING]


def _browser_payload(item_id: str) -> dict[str, Any]:
    """A valid AD-1154 browser ``action`` payload that is as near a command escalation as the shape allows: it names the
    item's scope and carries the very ``call_site`` the park looks up, so only its tool and action tell it apart."""
    return {
        "tool_id": "browser",
        "action": "click",
        "params": {"call_site": TOOL_CALL_SITE, "index": 0},
        "scope_key": WORK_ITEM_SCOPE_PREFIX + item_id,
        "session_id": "sess-1",
        "thread_id": "",
    }


# --------------------------------------------------------------------------------------
# 1. The scope key and its arming (P1-P3)
# --------------------------------------------------------------------------------------


def test_dispatched_key_gives_the_work_item_scope() -> None:
    """P1. ``escalation_scope`` names the dispatched item's scope from ``DISPATCHED_WORK_ITEM_KEY``: the thread id is
    kept, the crew item still wins, and an id that is not a work-item id (or not a string) falls through to the thread
    scope or to none. Kills MX-1 (the new branch's ``return`` replaced by ``pass``: every accepted row below then
    falls through to the thread scope or none)."""
    key = DISPATCHED_WORK_ITEM_KEY
    longest = "x" * 128  # the work-item id grammar's bound
    thread_scope = EscalationScope("a1", "thread:t1", None, "t1")
    no_scope = EscalationScope("a1", "", None, "")

    # accepted: the key gives the work-item scope; the thread id is kept when there is one
    accepted = [
        ({"agent_id": "a1", key: "W-1"}, EscalationScope("a1", "work_item:W-1", "W-1", "")),
        ({"agent_id": "a1", key: "W-1", "thread_id": "t1"}, EscalationScope("a1", "work_item:W-1", "W-1", "t1")),
        ({"agent_id": "a1", key: longest}, EscalationScope("a1", "work_item:" + longest, longest, "")),
    ]
    for context, expected in accepted:
        assert escalation_scope(context) == expected, context
        # negative control: without the key the very same context is a thread or an unscoped call
        bare = {name: value for name, value in context.items() if name != key}
        assert escalation_scope(bare) in (thread_scope, no_scope), context
        assert escalation_scope(bare) != expected, context

    # the crew item wins over the dispatched one, with or without a thread
    crew = {"agent_id": "a1", "_crew_work_item_id": "C1", "thread_id": "t1"}
    crew_scope = EscalationScope("a1", "work_item:C1", "C1", "t1")
    assert escalation_scope(crew) == crew_scope  # control: a crew-only context gives S2b's answer
    assert escalation_scope({**crew, key: "W-1"}) == crew_scope
    assert escalation_scope({"agent_id": "a1", "_crew_work_item_id": "C1", key: "W-1"}) == EscalationScope(
        "a1", "work_item:C1", "C1", "",
    )
    # premise: the dispatched key alone gives another answer, so the rows above tell the two branches apart
    assert escalation_scope({"agent_id": "a1", key: "W-1", "thread_id": "t1"}) != crew_scope

    # an id that is not a work-item id, or not a string, is ignored: the thread scope, or none
    for bad in ("", "has space", "-leading", "a/b", "x" * 129, 7, None):
        with_thread = {"agent_id": "a1", key: bad, "thread_id": "t1"}
        without_thread = {"agent_id": "a1", key: bad}
        assert escalation_scope(with_thread) == thread_scope, bad
        assert escalation_scope(without_thread) == no_scope, bad
        # negative control: the same two contexts with a valid id are the work item's scope
        assert escalation_scope({**with_thread, key: "W-1"}) == EscalationScope("a1", "work_item:W-1", "W-1", "t1")
        assert escalation_scope({**without_thread, key: "W-1"}) == EscalationScope("a1", "work_item:W-1", "W-1", "")

    # no agent identity: S2b's rule stands, the new branch does not make an anonymous call askable
    assert escalation_scope({key: "W-1"}) is None
    assert escalation_scope({"agent_id": "a1", key: "W-1"}) is not None  # control: the identity is what is missing


@pytest.mark.asyncio
async def test_the_key_is_one_name_in_both_places() -> None:
    """P2. The key ``_run_agentic_dispatch`` sends (``DISPATCHED_WORK_ITEM_KEY``) is on the executor's allowlist, and is
    not the crew key. Beyond the contract's membership check, the real executor is shown to accept the key and to refuse
    an unlisted one, so the allowlist is what is being tested and not a copy of its text. Kills none of MX-1..MX-7 by
    itself: a key missing from the allowlist is refused (``agentic_context_invalid``) before the run starts, which the
    seam (P-S1) would meet first."""
    allowed = agentic_dispatch._AGENTIC_EXTRA_CONTEXT_KEYS
    assert "_crew_work_item_id" in allowed  # premise: the neighbour is admitted, so membership is the right question
    assert DISPATCHED_WORK_ITEM_KEY in allowed
    assert DISPATCHED_WORK_ITEM_KEY != "_crew_work_item_id"
    assert DISPATCHED_WORK_ITEM_KEY + "_other" not in allowed  # negative control: the allowlist is not a prefix match

    runtime = _make_runtime(
        enabled=True, registry=ToolRegistry(), perm_store=ToolPermissionStore(), gap_driver=_FakeGapDriver(),
    )
    executor = WorkItemAgenticExecutor(llm_client=_ScriptedLLM([_text_response("done")]))
    outcome = await executor.run(
        agent_id=AGENT, instructions="", task_text="do the task", runtime=runtime,
        extra_context={DISPATCHED_WORK_ITEM_KEY: "wi-1"},
    )
    assert outcome.final_text == "done"  # the executor takes the key the agent sends
    with pytest.raises(ValueError, match="agentic_context_invalid"):  # negative control: it refuses a key off the list
        await executor.run(
            agent_id=AGENT, instructions="", task_text="do the task", runtime=runtime,
            extra_context={DISPATCHED_WORK_ITEM_KEY + "_other": "wi-1"},
        )


def _route(kind: str) -> Any:
    """What ``runtime.command_escalations`` holds: a real service over stand-ins, nothing, or a mock."""
    if kind == "real":
        return CommandEscalations(
            gate=SimpleNamespace(), approvals=SimpleNamespace(), requests=SimpleNamespace(), work_items=SimpleNamespace(),
        )
    if kind == "mock":
        return MagicMock()
    assert kind == "none"
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "work_item_id", "named"),
    [
        pytest.param("real", "wi-1", True, id="real_route"),
        pytest.param("none", "wi-1", False, id="no_route"),
        pytest.param("mock", "wi-1", False, id="mock_route"),
        pytest.param("real", "", False, id="real_route_without_an_item"),
    ],
)
async def test_run_agentic_dispatch_names_the_item_only_with_the_route(
    monkeypatch: pytest.MonkeyPatch, route: str, work_item_id: str, named: bool,
) -> None:
    """P3. With a real ``CommandEscalations`` on the runtime the executor is run with ``extra_context`` naming the item;
    with no route (``None``) or a ``MagicMock`` there is no ``extra_context`` keyword at all (the call is byte-identical
    to S2b's). The failure scope is the item id in every row. The rows are each other's controls: the item is named only
    in the row with the real route. The fourth row (a real route but no item id) is beyond the contract's three: the key
    is not sent for an empty id. Kills MX-6 (``**_scope_kwargs,`` removed: the real route then no longer names the
    item)."""
    calls: list[dict[str, Any]] = []

    async def _run(self: WorkItemAgenticExecutor, **kwargs: Any) -> WorkItemAgenticOutcome:
        calls.append(kwargs)
        return WorkItemAgenticOutcome(final_text="ok")

    monkeypatch.setattr(WorkItemAgenticExecutor, "run", _run)
    llm = _ScriptedLLM([])
    runtime = _make_runtime(
        enabled=True, registry=ToolRegistry(), perm_store=ToolPermissionStore(), gap_driver=_FakeGapDriver(),
    )
    runtime.command_escalations = _route(route)
    agent = _make_agent(llm=llm, runtime=runtime)

    result = await agent._run_agentic_dispatch(work_item_id=work_item_id, task_text="do the task", runtime=runtime)

    assert result == "ok"
    assert llm.calls == 0  # premise: the recorder stood in for the executor, so nothing reached the model
    (kwargs,) = calls
    assert kwargs["agent_id"] == agent.id and kwargs["task_text"] == "do the task"
    assert kwargs["failure_scope"] == work_item_id
    if named:
        assert kwargs["extra_context"] == {DISPATCHED_WORK_ITEM_KEY: work_item_id}
    else:
        assert "extra_context" not in kwargs


# --------------------------------------------------------------------------------------
# 2. The park (P4-P12)
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_park_is_inert_without_the_route(rig: _Rig) -> None:
    """P4. With no command approval route on the runtime (``None``, or a ``MagicMock`` that is not a
    ``CommandEscalations``) the park returns ``""`` and the item stays ``in_progress`` -- although a pending request of
    the agent waits in its scope. The real route parks the same item. Kills no row of the seven-row table (MX-7, the
    removed call, is the seam's); it pins the arming that keeps every runtime without a command policy as it was."""
    item = await rig.item("push the release branch")
    request_id = await _file(rig, PUSH, item=item)
    # premise: a pending request waits in the item's scope, and what the park reads would take it
    assert await _pending_ids(rig) == {request_id}
    assert await _awaited(rig, item) == request_id

    for route in (None, MagicMock()):
        rig.runtime.command_escalations = route
        assert await _park(rig, item) == ""
        assert await rig.status(item) == "in_progress"
        assert rig.router.dispatched == []
    assert "capability_request_id" not in await rig.metadata(item)  # nothing was written to the item

    rig.runtime.command_escalations = rig.escalations  # negative control: the real route parks the same item
    assert await _park(rig, item) == request_id
    assert await rig.status(item) == "blocked"


@pytest.mark.asyncio
@pytest.mark.parametrize(("first", "second"), [(PUSH, PULL), (PULL, PUSH)], ids=["push_first", "pull_first"])
async def test_park_on_the_oldest_pending_request(rig: _Rig, first: str, second: str) -> None:
    """P5. Two pending requests in the item's scope (two escalate rules, two commands): the item is parked on the older
    one -- ``blocked`` on it, with the reason the board shows -- and the router is handed nothing. Both filing orders are
    run, so the choice follows the filing order and not the command or the rule. Kills MX-2 (``return ask.request_id``
    replaced by ``continue``: a pending request is then never taken and the park returns ``""``)."""
    item = await rig.item("push the release branch")
    older = await _file(rig, first, item=item)
    younger = await _file(rig, second, item=item)
    # premises: two distinct pending requests, and the lookup the park reads lists them oldest first
    assert older != younger and await _pending_ids(rig) == {older, younger}
    listed = rig.requests.find_action_requests_by_param(
        "call_site", TOOL_CALL_SITE, statuses=("pending",),
        tool_id=COMMAND_APPROVAL_TOOL_ID, action=COMMAND_APPROVAL_ACTION,
    )
    assert [req.id for req in listed] == [older, younger]
    assert await rig.status(item) == "in_progress"

    parked = await _park(rig, item)

    assert parked == older and parked != younger
    assert await rig.status(item) == "blocked"
    metadata = await rig.metadata(item)
    assert metadata["capability_request_id"] == older
    assert metadata["blocked_reason"] == COMMAND_ESCALATION_BLOCKED_REASON
    assert rig.router.dispatched == []
    assert await _pending_ids(rig) == {older, younger}  # control: parking decided nothing; the younger one still waits


@pytest.mark.asyncio
async def test_park_ignores_other_agents_items_and_scopes(rig: _Rig) -> None:
    """P6. A pending request of another agent in the item, of this agent in another item, of this agent in a thread
    scope, and a browser ``action`` request linked to the item: none is what the item waits for, so the park returns
    ``""`` and leaves the item as it is. One more request of this agent in the item is parked on. Kills MX-5 (``or
    ask.scope_key != scope_key`` dropped: this agent's request in the other item or the thread is then taken). The
    other agent's request also catches a dropped agent clause, which the table does not name."""
    item = await rig.item("push the release branch")
    other_item = await rig.item("push another branch")
    scope = WORK_ITEM_SCOPE_PREFIX + item.id
    other_scope = WORK_ITEM_SCOPE_PREFIX + other_item.id
    by_other_agent = await _file(rig, PUSH, agent="agent-2", item=item)
    in_other_item = await _file(rig, PUSH, item=other_item)
    in_thread = await _file(rig, PUSH, thread="t1")
    browser = await rig.requests.file_action_request(
        AGENT, _browser_payload(item.id), rationale="click", work_item_id=item.id,
    )
    assert browser is not None

    # premises: each is pending, with the agent, item and scope its case names
    pending = {req.id: req for req in await rig.requests.list_pending()}
    assert {req.status for req in pending.values()} == {"pending"}
    assert {
        rid: (req.agent_id, req.work_item_id, req.payload["tool_id"], req.payload["scope_key"])
        for rid, req in pending.items()
    } == {
        by_other_agent: ("agent-2", item.id, "run_command", scope),
        in_other_item: (AGENT, other_item.id, "run_command", other_scope),
        in_thread: (AGENT, None, "run_command", "thread:t1"),
        browser.id: (AGENT, item.id, "browser", scope),
    }
    # premise: the store's lookup hands the park all three command asks, so the agent and scope filters are what
    # leave them out (the browser one is left out by its tool and action)
    candidates = rig.requests.find_action_requests_by_param(
        "call_site", TOOL_CALL_SITE, statuses=("pending", "fulfilled", "denied"),
        tool_id=COMMAND_APPROVAL_TOOL_ID, action=COMMAND_APPROVAL_ACTION,
    )
    assert {req.id for req in candidates} == {by_other_agent, in_other_item, in_thread}

    assert await _park(rig, item) == ""
    assert await rig.status(item) == "in_progress"
    assert rig.router.dispatched == []
    assert "capability_request_id" not in await rig.metadata(item)
    assert await _pending_ids(rig) == set(pending)  # nothing was decided

    in_scope = await _file(rig, PUSH, item=item)  # negative control: one more request in this agent's scope
    assert in_scope not in pending
    assert await _park(rig, item) == in_scope
    assert await rig.status(item) == "blocked"
    assert (await rig.metadata(item))["capability_request_id"] == in_scope


@pytest.mark.asyncio
async def test_a_request_approved_during_the_run_resumes_at_once(rig: _Rig) -> None:
    """P7. The Captain approves while the run is still going (the item is ``in_progress``, so the FULFILLED event finds
    nothing to resume); the park then returns the request and BF-878 resumes the item at once: ``in_progress`` again and
    one re-dispatch of it. The control: a later run, which began after the request was filed, does not take it again,
    so the resumed item does not resume itself. Also kills MX-3 (``if not _filed_since(req, since):`` replaced by ``if
    False:``) through that control; the contract names P9 and the seam for it."""
    item = await rig.item("push the release branch")
    began = _run_began()
    request_id = await _file(rig, PUSH, item=item)

    response = await _approve(rig.wired, request_id)

    # premises: approved and fulfilled, an active approval that admitted no run, and nothing resumed the item yet
    assert response["fulfilled"] is True
    assert (await rig.requests.get(request_id)).status == "fulfilled"
    row = await rig.approvals.get(request_id)
    assert row is not None and (row.state, row.uses) == ("active", 0)
    assert await rig.status(item) == "in_progress" and rig.router.dispatched == []

    assert await _park(rig, item, since=began) == request_id

    assert await rig.status(item) == "in_progress"  # parked, then resumed by BF-878 at once
    assert rig.dispatched_ids() == [item.id]
    metadata = await rig.metadata(item)
    assert metadata["capability_request_id"] == request_id  # it really was parked on the request
    assert metadata["blocked_reason"] == COMMAND_ESCALATION_BLOCKED_REASON
    assert (await rig.approvals.get(request_id)).uses == 0  # the park uses no approval; the next run does

    later = (await rig.requests.get(request_id)).created_at + 1.0
    assert await _park(rig, item, since=later) == ""  # negative control: a run that began after it never parks on it
    assert await rig.status(item) == "in_progress"
    assert rig.dispatched_ids() == [item.id]


@pytest.mark.asyncio
async def test_an_approval_already_used_is_not_parked_on(rig: _Rig) -> None:
    """P8. An approval that has already admitted a run is not what the item waits for: the park returns ``""`` and
    re-dispatches nothing. The control, in the same scope: a second request, approved and unused, is parked on and
    resumes the item. Kills MX-4 (``and row.uses == 0`` dropped: the used approval is then taken and the item resumed)."""
    item = await rig.item("push the release branch")
    began = _run_began()
    request_id = await _file(rig, PUSH, item=item)
    assert (await _approve(rig.wired, request_id))["fulfilled"] is True

    use = await rig.approvals.use(request_id, agent_id=AGENT, scope_key=WORK_ITEM_SCOPE_PREFIX + item.id)

    # premises: the approval is still active, and admitted its run
    assert use is not None and use.use_kind == "approved_run"
    row = await rig.approvals.get(request_id)
    assert row is not None and (row.state, row.uses) == ("active", 1)
    assert await _awaited(rig, item, since=began) == ""  # nothing is awaited, so the park has nothing to take

    assert await _park(rig, item, since=began) == ""
    assert await rig.status(item) == "in_progress"
    assert rig.router.dispatched == []

    unused = await _file(rig, PULL, item=item)  # negative control: the same state with an unused approval
    assert (await _approve(rig.wired, unused))["fulfilled"] is True
    row = await rig.approvals.get(unused)
    assert row is not None and (row.state, row.uses) == ("active", 0)
    assert await _park(rig, item, since=began) == unused
    assert rig.dispatched_ids() == [item.id]
    assert await rig.status(item) == "in_progress"


@pytest.mark.asyncio
async def test_a_request_settled_before_the_run_is_never_parked_on_again(rig: _Rig) -> None:
    """P9. One approved-and-unused and one denied request, both settled before the run began: the park returns ``""``,
    re-dispatches nothing and leaves the item ``in_progress``, so a resumed run that does not re-issue its command ends
    as it would have without S2c. The control: the same requests with a run that began at the start of time parks on the
    approved one. Kills MX-3 (``if not _filed_since(req, since):`` replaced by ``if False:``: both settled requests are
    then eligible and the approved one is taken)."""
    item = await rig.item("push the release branch")
    approved_id = await _file(rig, PUSH, item=item)
    assert (await _approve(rig.wired, approved_id))["fulfilled"] is True
    denied_id = await _file(rig, PULL, item=item)
    denial = await _approve(rig.wired, denied_id, approve=False)

    # premises: one approved-unused, one denied, and a run that began after both were filed
    assert denial["request"]["status"] == "denied"
    approved_row = await rig.approvals.get(approved_id)
    assert approved_row is not None and (approved_row.state, approved_row.uses) == ("active", 0)
    denied_row = await rig.approvals.get(denied_id)
    assert denied_row is not None and denied_row.state == "denied"
    created = [(await rig.requests.get(request_id)).created_at for request_id in (approved_id, denied_id)]
    since = max(created) + 1.0
    assert all(since > stamp for stamp in created)
    assert await rig.status(item) == "in_progress" and rig.router.dispatched == []

    assert await _park(rig, item, since=since) == ""
    assert await rig.status(item) == "in_progress"
    assert rig.router.dispatched == []
    assert "capability_request_id" not in await rig.metadata(item)

    assert await _park(rig, item, since=0.0) == approved_id  # negative control: a run that began before both
    assert await rig.status(item) == "in_progress"  # parked, then resumed by BF-878
    assert rig.dispatched_ids() == [item.id]


@pytest.mark.asyncio
async def test_a_request_denied_during_the_run_cancels_the_item(rig: _Rig) -> None:
    """P10. The Captain denies while the run is still going (the DECIDED event finds the item not blocked and does
    nothing); the park then returns the request and BF-878 cancels the item, with the Captain's reason in
    ``denial_reason``. The control: the approved counterpart, on a second item, resumes instead. Kills none of
    MX-1..MX-7; it pins D2 (a denial of a parked item's command cancels the item)."""
    item = await rig.item("push the release branch")
    began = _run_began()
    request_id = await _file(rig, PUSH, item=item)

    response = await _approve(rig.wired, request_id, approve=False)

    # premises: denied and recorded, and nothing has cancelled the item yet
    assert response["request"]["status"] == "denied" and response["fulfilled"] is False
    row = await rig.approvals.get(request_id)
    assert row is not None and row.state == "denied"
    assert await rig.status(item) == "in_progress" and "denial_reason" not in await rig.metadata(item)

    assert await _park(rig, item, since=began) == request_id

    assert await rig.status(item) == "cancelled"
    assert (await rig.metadata(item))["denial_reason"] == "not needed"
    assert rig.router.dispatched == []

    approved_item = await rig.item("push another branch")  # negative control: an approval resumes, it does not cancel
    approved_id = await _file(rig, PUSH, item=approved_item)
    assert (await _approve(rig.wired, approved_id))["fulfilled"] is True
    assert await _park(rig, approved_item, since=began) == approved_id
    assert await rig.status(approved_item) == "in_progress"
    assert rig.dispatched_ids() == [approved_item.id]
    assert await rig.status(item) == "cancelled"


@pytest.mark.asyncio
async def test_pending_wins_over_settled(rig: _Rig) -> None:
    """P11. One request approved-and-unused during the run and one still pending: the item is parked on the pending one
    and nothing is re-dispatched (the approved one is not taken first). The control: before the second request is filed,
    the approved one alone is what the park would take. Kills none of MX-1..MX-7; it pins D3's order."""
    item = await rig.item("push the release branch")
    began = _run_began()
    approved_id = await _file(rig, PUSH, item=item)
    assert (await _approve(rig.wired, approved_id))["fulfilled"] is True
    row = await rig.approvals.get(approved_id)
    assert row is not None and (row.state, row.uses) == ("active", 0)  # premise: approved and unused
    assert await _awaited(rig, item, since=began) == approved_id  # negative control: alone, it is what the park takes

    pending_id = await _file(rig, PULL, item=item)
    assert (await rig.requests.get(pending_id)).status == "pending"  # premise

    assert await _awaited(rig, item, since=began) == pending_id
    assert await _park(rig, item, since=began) == pending_id
    assert await rig.status(item) == "blocked"
    assert (await rig.metadata(item))["capability_request_id"] == pending_id
    assert rig.router.dispatched == []
    assert (await rig.requests.get(approved_id)).status == "fulfilled"  # the settled one was left alone


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["read_raises", "item_done"])
async def test_park_degrades_on_faults(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, fault: str,
) -> None:
    """P12. A fault leaves the item as the run left it and the park never raises. ``read_raises``:
    ``find_action_requests_by_param`` raises (patched on the instance): ``""``, the item ``in_progress``, a WARNING
    naming the item; the same call parks once the fault is gone. ``item_done``: the item moved to ``done`` after the
    request was filed, so ``block_on_request`` refuses (``done -> blocked``): ``""``, the item ``done``, a WARNING; a
    second, open item parks. Kills none of MX-1..MX-7."""
    caplog.set_level(logging.WARNING, logger=PARK_LOGGER)
    item = await rig.item("push the release branch")
    request_id = await _file(rig, PUSH, item=item)
    assert await _awaited(rig, item) == request_id  # premise: a pending request waits, and the read finds it

    if fault == "read_raises":

        def _raises(*args: Any, **kwargs: Any) -> list[Any]:
            raise RuntimeError("the request cache cannot be read")

        with monkeypatch.context() as patched:
            patched.setattr(rig.requests, "find_action_requests_by_param", _raises)
            parked = await _park(rig, item)
        assert parked == ""
        assert await rig.status(item) == "in_progress"
        assert any(item.id in message for message in _warnings(caplog)), _warnings(caplog)
        assert await _park(rig, item) == request_id  # negative control: without the fault the same call parks
        assert await rig.status(item) == "blocked"
    else:
        await rig.wired.work_items.transition_work_item(item.id, "done", source=AGENT)
        assert await rig.status(item) == "done"  # premise: the item has ended
        assert await _awaited(rig, item) == request_id  # premise: the read still finds the request; only parking fails
        parked = await _park(rig, item)
        assert parked == ""
        assert await rig.status(item) == "done"
        assert any(item.id in message for message in _warnings(caplog)), _warnings(caplog)
        other = await rig.item("push another branch")  # negative control: an open item with a pending request parks
        other_id = await _file(rig, PUSH, item=other)
        assert await _park(rig, other) == other_id
        assert await rig.status(other) == "blocked"
    assert rig.router.dispatched == []


# --------------------------------------------------------------------------------------
# 3. The call site (P13)
# --------------------------------------------------------------------------------------


def test_call_site_is_the_tool_paths() -> None:
    """P13. The payload a tool-path escalation is filed with carries ``params["call_site"] == TOOL_CALL_SITE``, the very
    value the park looks requests up by; a verdict judged at the shell agent's site is filed under its own name and is
    not read. Kills none of MX-1..MX-7; a drifted constant would leave every request unfound by the park."""
    gate = _gate(_policy(_ASK_PUSH))
    scope = EscalationScope(AGENT, "work_item:W-1", "W-1", "")
    verdict = gate.judge(PUSH, site="run_command_tool", search_path=None)
    assert verdict.decision == "escalate"  # premise: the policy escalates this command

    payload = command_approval_payload(verdict, PUSH, scope)

    assert payload is not None
    assert payload["params"]["call_site"] == TOOL_CALL_SITE

    shell = gate.judge(PUSH, site="shell_command_agent", search_path=None)  # negative control: the mesh site
    assert shell.decision == "escalate"
    shell_payload = command_approval_payload(shell, PUSH, scope)
    assert shell_payload is not None
    assert shell_payload["params"]["call_site"] == "shell_command_agent"
    assert shell_payload["params"]["call_site"] != TOOL_CALL_SITE


# --------------------------------------------------------------------------------------
# 4. Beyond P1-P13 (X1-X4): the branches of the park module the contract's tests do not reach
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "no_runtime", "no_driver", "no_request_store",
        "empty_item_id", "non_str_item_id", "empty_agent_id", "non_str_agent_id",
    ],
)
async def test_park_is_inert_without_its_inputs(rig: _Rig, case: str) -> None:
    """X1. The park returns ``""`` and touches nothing without a runtime, a capability-gap driver, a request store, or a
    string item id and agent id -- with a pending request of the agent waiting in the item's scope. With the input
    restored, the same call parks the same item. Kills none of MX-1..MX-7."""
    item = await rig.item("push the release branch")
    request_id = await _file(rig, PUSH, item=item)
    assert await _awaited(rig, item) == request_id  # premise: a request waits, and the route is wired

    runtime: Any = rig.runtime
    kwargs: dict[str, Any] = {"agent_id": AGENT, "work_item_id": item.id, "since": 0.0}
    if case == "no_runtime":
        runtime = None
    elif case == "no_driver":
        rig.runtime.capability_gap_driver = None
    elif case == "no_request_store":
        rig.runtime.capability_request_store = None
    elif case == "empty_item_id":
        kwargs["work_item_id"] = ""
    elif case == "non_str_item_id":
        kwargs["work_item_id"] = 7
    elif case == "empty_agent_id":
        kwargs["agent_id"] = ""
    elif case == "non_str_agent_id":
        kwargs["agent_id"] = None
    else:
        raise AssertionError(case)

    assert await park_on_command_escalation(runtime, **kwargs) == ""
    assert await rig.status(item) == "in_progress"
    assert rig.router.dispatched == []
    assert "capability_request_id" not in await rig.metadata(item)

    rig.runtime.capability_gap_driver = rig.wired.driver  # negative control: the input restored, the same item parks
    rig.runtime.capability_request_store = rig.requests
    assert await _park(rig, item) == request_id
    assert await rig.status(item) == "blocked"


@pytest.mark.asyncio
async def test_park_degrades_when_parking_raises(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """X2. ``block_on_request`` raising (the driver's board write) is caught: the park returns ``""``, the item stays
    ``in_progress`` and a WARNING names the item and the request. Without the fault the same call parks. Kills none of
    MX-1..MX-7."""
    caplog.set_level(logging.WARNING, logger=PARK_LOGGER)
    item = await rig.item("push the release branch")
    request_id = await _file(rig, PUSH, item=item)
    assert await _awaited(rig, item) == request_id  # premise: a pending request waits

    async def _raises(**kwargs: Any) -> bool:
        raise RuntimeError("the board is unreachable")

    with monkeypatch.context() as patched:
        patched.setattr(rig.wired.driver, "block_on_request", _raises)
        assert await _park(rig, item) == ""

    assert await rig.status(item) == "in_progress"
    assert any(item.id in message and request_id[:12] in message for message in _warnings(caplog)), _warnings(caplog)
    assert await _park(rig, item) == request_id  # negative control: the fault gone, the same call parks
    assert await rig.status(item) == "blocked"


@pytest.mark.asyncio
async def test_an_approval_that_cannot_be_read_is_not_parked_on(rig: _Rig) -> None:
    """X3. A fulfilled request is parked on only when its approval is read and found unused: with no command approval
    store on the runtime the park cannot tell, returns ``""`` and leaves the item as it is. With the store, the same
    approved request is parked on and resumes the item. Kills none of MX-1..MX-7."""
    item = await rig.item("push the release branch")
    request_id = await _file(rig, PUSH, item=item)
    assert (await _approve(rig.wired, request_id))["fulfilled"] is True
    row = await rig.approvals.get(request_id)
    assert row is not None and (row.state, row.uses) == ("active", 0)  # premise: approved and unused
    assert await _awaited(rig, item) == request_id

    rig.runtime.command_approval_store = None
    assert await _park(rig, item) == ""
    assert await rig.status(item) == "in_progress"
    assert rig.router.dispatched == []

    rig.runtime.command_approval_store = rig.approvals  # negative control: with the store it is parked on and resumed
    assert await _park(rig, item) == request_id
    assert rig.dispatched_ids() == [item.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("created_at", [None, float("nan"), float("inf"), "1.0", True], ids=["none", "nan", "inf", "str", "bool"])
async def test_a_request_without_a_usable_creation_time_is_not_filed_during_the_run(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch, created_at: Any,
) -> None:
    """X4. A settled request whose ``created_at`` is not a finite ``int`` or ``float`` (``None``, NaN, infinity, a string,
    a ``bool``) is never taken as filed during the run, even by a run that began at the start of time. The same request
    with its real creation time is taken. Kills none of MX-1..MX-7."""
    item = await rig.item("push the release branch")
    request_id = await _file(rig, PUSH, item=item)
    assert (await _approve(rig.wired, request_id))["fulfilled"] is True
    real = await rig.requests.get(request_id)
    assert real is not None and real.status == "fulfilled"
    row = await rig.approvals.get(request_id)
    assert row is not None and (row.state, row.uses) == ("active", 0)  # premise: the approval is usable

    def _lookup(stamp: Any) -> Any:
        stand_in = SimpleNamespace(
            id=real.id, agent_id=real.agent_id, kind=real.kind, work_item_id=real.work_item_id,
            payload=real.payload, status="fulfilled", created_at=stamp,
        )
        return lambda *args, **kwargs: [stand_in]

    monkeypatch.setattr(rig.requests, "find_action_requests_by_param", _lookup(created_at))
    assert await _awaited(rig, item, since=0.0) == ""

    monkeypatch.setattr(rig.requests, "find_action_requests_by_param", _lookup(real.created_at))
    assert await _awaited(rig, item, since=0.0) == request_id  # negative control: the real creation time is taken
