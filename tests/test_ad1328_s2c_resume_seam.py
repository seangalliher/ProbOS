"""AD-1328 S2c (#1530), M2: the resume seam.

Tests only. The contract is ``prompts/ad-1328-s2c-command-escalation-resume.md`` ("Tests", the file section for this module;
P-S1 is the seam of record). One escalated ``run_command`` in a plain dispatched work item crosses the whole chain and comes
back: the agent's run (``CognitiveAgent._handle_work_item_dispatch`` -> ``_run_agentic_dispatch`` -> the real
``WorkItemAgenticExecutor``) -> the real ``ToolRegistry`` / ``DispatchToolExecutor`` -> ``RunCommandTool`` -> the real
``CommandPolicyGate`` -> ``CommandEscalations`` (``build_command_escalations``) -> the real ``CapabilityRequestStore`` -> the park
(``park_on_command_escalation`` -> ``CapabilityGapDriver.block_on_request``) -> the Captain's decision through the real
``decide_capability_request`` -> ``fulfil_approval`` -> the real ``SqliteCommandApprovalStore`` -> FULFILLED on the bus ->
``CapabilityGapDriver.on_capability_event`` -> the resume and the re-dispatch -> the agent's next run -> the command runs once.
Each half passing alone is the signature of this repo's most common defect (every link correct, the chain dead), so one test
walks the whole chain.

Real: ``WorkItemStore``, ``CapabilityRequestStore`` (emitting through ``_EventBus``), ``SqliteCommandApprovalStore``,
``ToolPermissionStore``, ``CapabilityGapDriver`` (subscribed to the bus), ``CommandPolicyGate`` (``_ASK_PUSH``),
``build_command_escalations``, ``RunCommandTool`` in a real ``ToolRegistry`` (every rank ``full``, so the premise is reached),
``decide_capability_request``, a ``CognitiveAgent`` built as test_ad856's ``_make_agent``, and the dispatch path above. The
stores are SQLite files in ``tmp_path``.

Stand-ins, named: the model (``_ScriptedLLM``), the router (``_RecordingRouter``; the hop from router to agent is built by
``_Seam.dispatch`` as ``mesh/work_item_router.py:111-117`` builds it: an ``IntentMessage`` ``work_item_dispatched`` whose params
carry the dict's ``work_item_id``, ``title`` and ``description``), the thread store (``_ThreadStore``), the event bus
(``_EventBus``) and the shell (``spawns``: ``asyncio.create_subprocess_shell`` and the tool module's ``ProcessTree`` are replaced,
so no shell starts). Every gate takes ``platform="linux"`` and a ``which`` that finds nothing, so the file reads the same on any
host.

Where a copied helper differs from its original, and why: the runtime carries no ``trust_network`` (a mock there with no registry
or ontology makes ``_resolve_agentic_identity`` refuse the run, ``agentic_dispatch.py:471-498``; the request store keeps its own
mock); ``_EventLog.log`` answers a positive row id (the AD-1224 hooks of the dispatch run, ``tools/executor.py:1471-1494``, read
anything else as "not acknowledged" and warn); ``_ScriptedLLM`` takes its script per run and records what each call was offered
and asked.

Mutants (the contract's "Mutation rows"; the orchestrator runs the campaign on the source, this file only names what each test
kills, checked with in-process equivalents of the mutants: one module attribute replaced per mutant, nothing edited): MX-1, MX-2,
MX-6 and MX-7 are killed by P-S1 (and fail P-S2, P-S3 and P-S4 in their setup or control). MX-3 is killed by P-S4 alone: the
contract lists P-S1 for it, but when P-S1's run ends the approval has been used, so ``row.uses == 0`` (MX-4's clause) alone keeps
the item from parking on it again; P-S4 leaves the approval unused, which isolates ``_filed_since``. MX-5 is killed by P-S2 (the
second parked item). MX-4 is P8's and survives this file.

Helpers are copies, because tests do not import each other: tests/test_ad1328_s2b_seam_and_wiring.py (``_policy``, ``_rule``,
``_ASK_PUSH``, ``_Which``, ``_gate``, ``_Process``, ``_Tree``, ``_Spawns``, ``spawns``, ``_RecordingRouter``, ``_EventBus``,
``_EventLog``, ``_Runtime``, ``wired``, ``approvals``, ``_approve``, ``_status``) and tests/test_ad856_agentic_dispatch.py
(``_FakeLLMResponse``, ``_ScriptedLLM``, ``_text_response``, ``_make_agent``).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequestStore
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.command_escalation_park import COMMAND_ESCALATION_BLOCKED_REASON
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tool_call import ToolCallRequest, ToolUseBlock
from probos.cognitive.swe_harness.tools import RunCommandTool
from probos.config_models.operations import CommandPolicyConfig
from probos.execution.command_approvals import SqliteCommandApprovalStore
from probos.execution.command_escalation import CommandEscalations, build_command_escalations
from probos.execution.command_gate import CommandPolicyGate
from probos.routers.capability_requests import decide_capability_request
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission
from probos.tools.registry import ToolRegistry
from probos.types import AgentMeta, AgentState, IntentMessage
from probos.workforce import WorkItemStore

# --------------------------------------------------------------------------------------
# Helpers (copied; tests do not import each other)
# --------------------------------------------------------------------------------------

PUSH = "git push origin"
_ASK_PUSH_WHY = "a push publishes work outside this session"
_AGENT_ID = "counselor-001"
#: ``run_command`` for every rank, so the rank the dispatch path resolves (``ensign``, the run's default) reaches the premise.
_FULL_FOR_EVERY_RANK = {"ensign": "full", "lieutenant": "full", "commander": "full", "senior_officer": "full"}


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


class _Process:
    """What ``create_subprocess_shell`` returns: ``communicate()`` gives ``(b"out", b"")`` and the exit code is 0."""

    pid = 4242
    returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"out", b""


class _Tree:
    """What the fake ``ProcessTree.attach`` returns."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    def kill(self) -> None:
        self._events.append("kill")

    def close(self) -> None:
        self._events.append("close")


class _Spawns:
    """Records every spawn ``(args, kwargs)``, every tree attached, and what was done to each tree."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.attached: list[_Process] = []
        self.tree_events: list[str] = []

    async def create_subprocess_shell(self, *args: Any, **kwargs: Any) -> _Process:
        self.calls.append((args, kwargs))
        return _Process()

    def attach(self, proc: _Process) -> _Tree:
        self.attached.append(proc)
        return _Tree(self.tree_events)

    @property
    def commands(self) -> list[str]:
        """The command text of each spawn, in order."""
        return [args[0] for args, _ in self.calls]


@pytest.fixture
def spawns(monkeypatch: pytest.MonkeyPatch) -> _Spawns:
    recorder = _Spawns()
    monkeypatch.setattr(asyncio, "create_subprocess_shell", recorder.create_subprocess_shell)
    monkeypatch.setattr(swe_tools, "ProcessTree", SimpleNamespace(attach=recorder.attach))
    return recorder


# --------------------------------------------------------------------------------------
# The wired system (tests/test_ad1211_approval_fulfils_every_kind.py via the S2b seam file, trimmed to what an ``action`` needs)
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
    """``runtime.event_log`` for the route and for the dispatch run's AD-1224 hooks. ``log`` is the only method either calls;
    it answers a positive row id, which is what the hooks count as an acknowledged write."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def log(self, *, category: str, event: str, detail: str = "", **_kw: Any) -> int:
        self.events.append((category, event))
        return len(self.events)


class _Runtime(SimpleNamespace):
    """Exactly the attributes the route, the escalation service, the driver and the dispatch run read."""


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
    requests = CapabilityRequestStore(
        db_path=str(tmp_path / "cap.db"), emit_event=bus.emit, trust_network=MagicMock(),
    )
    await requests.start()
    router = _RecordingRouter()
    runtime = _Runtime(
        work_item_router=router,
        work_item_store=work_items,
        capability_request_store=requests,
        event_log=_EventLog(),
        config=SimpleNamespace(agentic_dispatch=SimpleNamespace(enabled=True)),
        intent_bus=None,
        emit_event=None,
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


@pytest.fixture
async def perms(tmp_path: Path) -> AsyncIterator[ToolPermissionStore]:
    store = ToolPermissionStore(db_path=str(tmp_path / "tool_permissions.db"))
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


def _redispatched(wired: _Wired) -> list[dict[str, Any]]:
    """The work item dicts AD-855 handed back to the router (``_RecordingRouter.dispatch_work_item``), in order."""
    return [event["data"]["work_item"] for event in wired.router.dispatched]


async def _clock_past(timestamp: float) -> float:
    """The wall clock once it is strictly past ``timestamp``. The park compares ``created_at >= since`` on the wall clock, and a
    coarse tick (15.6 ms on Windows) could otherwise start a run in the very tick its request was filed in."""
    now = time.time()
    while now <= timestamp:
        await asyncio.sleep(0.001)
        now = time.time()
    return now


# --------------------------------------------------------------------------------------
# The agent and its model (tests/test_ad856_agentic_dispatch.py, copied; the model is scripted per run)
# --------------------------------------------------------------------------------------


class _FakeLLMResponse:
    def __init__(self, content_blocks: list, content: str = "", tokens: int = 1) -> None:
        self.content_blocks = content_blocks
        self.content = content
        self.tokens_used = tokens


class _ScriptedLLM:
    """Returns a scripted sequence of responses; captures the tools presented and the prompt of every call. A text-only response
    ends the loop; a call past the script answers ``done`` (``_Seam.dispatch`` counts the calls, so that never goes unseen)."""

    def __init__(self, responses: list[_FakeLLMResponse]) -> None:
        self._responses = list(responses)
        self.last_tools: list[dict] | None = None
        self.offered: list[set[str]] = []
        self.prompts: list[str] = []
        self.calls = 0

    def queue(self, *responses: _FakeLLMResponse) -> None:
        self._responses.extend(responses)

    @property
    def unused(self) -> int:
        return len(self._responses)

    async def complete(self, req: Any, **_kwargs: Any) -> _FakeLLMResponse:
        self.calls += 1
        self.last_tools = list(req.tools or [])
        self.offered.append({tool["function"]["name"] for tool in self.last_tools})
        self.prompts.append(str(getattr(req, "prompt", "") or ""))
        if self._responses:
            return self._responses.pop(0)
        # Default terminal: text-only response ends the loop.
        return _FakeLLMResponse(content_blocks=[], content="done")


def _text_response(text: str) -> _FakeLLMResponse:
    return _FakeLLMResponse(content_blocks=[], content=text, tokens=1)


def _run_command_response(command: str = PUSH) -> _FakeLLMResponse:
    """The model asks for ``run_command`` with ``command`` (test_ad856's ``_tool_use_response``, with its arguments)."""
    block = ToolUseBlock(tool_call=ToolCallRequest(name="run_command", arguments={"command": command}))
    return _FakeLLMResponse(content_blocks=[block], content="", tokens=1)


def _make_agent(
    *,
    llm: Any,
    runtime: Any,
    rank: str = "ensign",
    agent_id: str = _AGENT_ID,
) -> Any:
    """Build a minimal CognitiveAgent without running __init__."""
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


class _ThreadStore:
    """Stands in for the chat thread store: the one default thread ``_handle_work_item_dispatch`` writes the task and the
    agent's answer to, recorded as the real store's ``get_or_create_default_for_agent`` / ``append_message`` take them."""

    def __init__(self) -> None:
        self.thread = SimpleNamespace(id="thread-1")
        self.created: list[tuple[str, str]] = []
        self.messages: list[dict[str, Any]] = []

    def get_or_create_default_for_agent(self, agent_id: str, agent_callsign: str) -> Any:
        self.created.append((agent_id, agent_callsign))
        return self.thread

    def append_message(
        self, thread_id: str, *, author_id: str, role: str, body: str, metadata: dict | None = None, **_kw: Any,
    ) -> None:
        self.messages.append(
            {"thread_id": thread_id, "author_id": author_id, "role": role, "body": body, "metadata": dict(metadata or {})},
        )

    @property
    def agent_messages(self) -> list[dict[str, Any]]:
        return [message for message in self.messages if message["role"] == "agent"]


class _Seam:
    """The dispatch path under test, wired over ``wired``'s stores: one agent, its scripted model and the thread store."""

    def __init__(self, agent: Any, llm: _ScriptedLLM, threads: _ThreadStore, gate: CommandPolicyGate) -> None:
        self.agent = agent
        self.llm = llm
        self.threads = threads
        self.gate = gate

    async def dispatch(self, work_item: dict[str, Any], *script: _FakeLLMResponse) -> Any:
        """One run of ``work_item``: the router's hop to the agent (``mesh/work_item_router.py:111-117``), then the real
        ``_handle_work_item_dispatch`` -> ``_run_agentic_dispatch`` -> ``WorkItemAgenticExecutor``, with this run's script."""
        calls_before = self.llm.calls
        self.llm.queue(*script)
        intent = IntentMessage(
            intent="work_item_dispatched",
            params={
                "work_item_id": work_item.get("id", ""),
                "title": work_item.get("title", ""),
                "description": work_item.get("description", ""),
            },
            target_agent_id=self.agent.id,
        )
        result = await self.agent._handle_work_item_dispatch(intent)
        assert self.llm.calls - calls_before == len(script), "the loop made other model calls than the run's script has responses"
        assert self.llm.unused == 0
        return result


async def _build_seam(
    wired: _Wired, approvals: SqliteCommandApprovalStore, perms: ToolPermissionStore, gate: CommandPolicyGate,
    *, routed: bool,
) -> _Seam:
    """What startup builds for one policy, plus the dispatch path over it. ``routed`` wires the approval route
    (``build_command_escalations``, the real factory, as ``runtime.command_escalations`` and into the tool); otherwise the
    runtime and the tool carry ``command_escalations=None``. The approval store is on the runtime either way, so the only
    difference between the two is the route. A second call stands for another policy (or another agent) over the same stores."""
    runtime = wired.runtime
    escalations = None
    if routed:
        escalations = build_command_escalations(
            gate=gate, approvals=approvals, requests=wired.requests, work_items=wired.work_items, inbox=None,
        )
        assert isinstance(escalations, CommandEscalations)
    runtime.command_escalations = escalations
    runtime.command_approval_store = approvals
    registry = ToolRegistry()
    registry.register(
        RunCommandTool(runtime, command_policy_gate=gate, command_escalations=escalations),  # type: ignore[arg-type]
        default_permissions=dict(_FULL_FOR_EVERY_RANK),
    )
    registry.set_permission_store(perms)
    await perms.issue_grant(_AGENT_ID, "run_command", ToolPermission.FULL, reason="the dispatch run offers granted tools")
    threads = _ThreadStore()
    llm = _ScriptedLLM([])
    runtime.tool_registry = registry
    runtime.tool_permission_store = perms
    runtime.chat_thread_store = threads
    return _Seam(_make_agent(llm=llm, runtime=runtime), llm, threads, gate)


async def _dispatched_task(wired: _Wired, agent_id: str, title: str) -> Any:
    """A ``task`` item as the router finds it: ``open`` and assigned to the agent that will run it."""
    item = await wired.work_items.create_work_item(
        title=title, description=title, work_type="task", assigned_to=agent_id, created_by="captain",
    )
    assert await _status(wired, item) == "open"
    return item


async def _escalate_and_park(
    wired: _Wired, seam: _Seam, spawns: _Spawns, *, title: str = "push the release branch",
) -> tuple[Any, Any]:
    """Run 1 of the story. A ``task`` item is dispatched; the agent calls ``run_command`` with ``PUSH`` and then reports it is
    waiting; the policy escalates; the item is left ``blocked`` on the request that was filed. Asserts every link up to the
    Captain's decision and returns ``(item, request)``."""
    item = await _dispatched_task(wired, seam.agent.id, title)
    scope = f"work_item:{item.id}"
    spawned = len(spawns.calls)
    handed_back = len(wired.router.dispatched)
    calls_before = seam.llm.calls

    result = await seam.dispatch(item.to_dict(), _run_command_response(PUSH), _text_response("Waiting for approval."))

    assert result.success is True
    offered = seam.llm.offered[calls_before:]
    assert offered and all("run_command" in names for names in offered), "premise: the model was offered run_command"
    assert "Waiting for approval." in seam.threads.agent_messages[-1]["body"]
    # one request, filed in the item's scope and linked to it
    (req,) = [r for r in await wired.requests.list_pending() if r.work_item_id == item.id]
    assert (req.kind, req.agent_id, req.work_item_id) == ("action", seam.agent.id, item.id)
    assert (req.payload["tool_id"], req.payload["action"], req.payload["scope_key"]) == ("run_command", "execute", scope)
    assert req.payload["params"]["command"] == PUSH
    assert len(spawns.calls) == spawned  # escalated: nothing ran
    # and the item is parked on it, not merely left in_progress
    parked = await wired.work_items.get_work_item(item.id)
    assert parked is not None
    assert parked.status == "blocked"
    assert parked.metadata["capability_request_id"] == req.id
    assert parked.metadata["blocked_reason"] == COMMAND_ESCALATION_BLOCKED_REASON
    assert len(wired.router.dispatched) == handed_back  # parking dispatches nothing
    return item, req


# --------------------------------------------------------------------------------------
# The seam
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seam_escalate_park_approve_resume_runs_once(
    wired: _Wired, approvals: SqliteCommandApprovalStore, perms: ToolPermissionStore, spawns: _Spawns,
) -> None:
    """P-S1, the seam of record. A plain dispatched item's run escalates ``run_command`` -> the request is filed in the item's
    scope and linked to it -> the item is parked ``blocked`` on it -> the Captain approves through the real REST function ->
    the approval is recorded, the request fulfilled, the item resumed and re-dispatched -> the re-dispatched run issues the same
    command -> it runs exactly once, recorded as the approved run before it starts -> the run ends without parking again.

    Premises: the policy escalates this very command; the model was offered ``run_command``; one pending request, filed in the
    item's scope. Controls: nothing spawned and nothing handed back to the router before the decision; nothing filed by the
    repeat; no second re-dispatch after the run (no self-resume).

    Kills MX-1 (``escalation_scope`` without the dispatched-item branch: the request is filed unlinked, in scope ``""``), MX-2
    (the oldest-pending return becomes ``continue``: nothing to park on), MX-6 (``**_scope_kwargs`` removed from the executor
    call: the same unlinked request) and MX-7 (the park call removed: the item is left ``in_progress``). Not MX-3, which the
    contract lists here: when this run ends the approval has been used, and ``row.uses == 0`` alone already refuses the park,
    so an in-process equivalent of MX-3 (``_filed_since`` always true) leaves this test green; P-S4 is its test."""
    gate = _gate(_policy(_ASK_PUSH))
    seam = await _build_seam(wired, approvals, perms, gate, routed=True)
    verdict = gate.judge(PUSH, site="run_command_tool", search_path=None)
    assert (verdict.decision, verdict.runs) == ("escalate", False)  # premise: the policy escalates this command
    assert isinstance(wired.runtime.command_escalations, CommandEscalations)
    assert await wired.requests.list_pending() == []

    # 1. run 1: escalated, filed in the item's scope, linked to it, parked on it; nothing ran
    item, req = await _escalate_and_park(wired, seam, spawns)
    scope = f"work_item:{item.id}"
    assert spawns.calls == []
    assert wired.router.dispatched == []
    assert await approvals.get(req.id) is None  # nothing is recorded until the Captain decides

    # 2. the Captain approves: recorded, fulfilled, the item resumed and re-dispatched once; nothing is replayed
    response = await _approve(wired, req.id)
    assert response["fulfilled"] is True
    assert response["request"]["status"] == "fulfilled"
    row = await approvals.get(req.id)
    assert row is not None
    assert (row.state, row.agent_id, row.scope_key, row.approver, row.uses) == (
        "active", seam.agent.id, scope, "captain", 0,
    )
    assert spawns.calls == []  # approval never replays the command (AD-1154, BF-830)
    (handed,) = _redispatched(wired)
    assert handed["id"] == item.id
    assert await _status(wired, item) == "in_progress"

    # 3. run 2, from the dict the router was handed: the command is issued again and runs once, under the approval
    result = await seam.dispatch(handed, _run_command_response(PUSH), _text_response("Pushed."))
    assert result.success is True
    assert spawns.commands == [PUSH]
    uses = await approvals.list_uses(req.id)
    assert [(u.use_kind, u.request_id, u.agent_id, u.scope_key) for u in uses] == [
        ("approved_run", req.id, seam.agent.id, scope),
    ]
    row = await approvals.get(req.id)
    assert row is not None and row.uses == 1
    assert await _status(wired, item) == "in_progress"  # not parked again
    await wired.bus.drain()
    assert len(_redispatched(wired)) == 1  # no self-resume
    assert await wired.requests.list_pending() == []  # the repeat was admitted, so nothing new was filed
    last = seam.threads.agent_messages[-1]
    assert last["body"] == "Pushed."
    assert last["metadata"]["work_item_id"] == item.id


@pytest.mark.asyncio
async def test_seam_denial_cancels_the_parked_item(
    wired: _Wired, approvals: SqliteCommandApprovalStore, perms: ToolPermissionStore, spawns: _Spawns,
) -> None:
    """P-S2. Run 1 as in P-S1, then the Captain denies: the parked item is cancelled with the Captain's reason, nothing is
    re-dispatched, nothing runs, and the denial is recorded (D2: AD-855's own cancel on a denial, unchanged).

    Premise: both items are parked, each on its own request. Control: the second item, parked on the other request in the same
    agent's name, is not touched by the denial of the first, and nothing is recorded for its request.

    Kills MX-5 (``ask.scope_key != scope_key`` dropped: the second item is parked on the FIRST item's request, which the setup
    sees). Its setup is P-S1's run 1, so MX-1, MX-2, MX-6 and MX-7 fail it there; what it adds is the way from a denial to the
    cancel (AD-855's ``_cancel``, unchanged) and the record of the denial."""
    gate = _gate(_policy(_ASK_PUSH))
    seam = await _build_seam(wired, approvals, perms, gate, routed=True)
    item, req = await _escalate_and_park(wired, seam, spawns)
    other_item, other_req = await _escalate_and_park(wired, seam, spawns, title="push the docs branch")
    assert req.id != other_req.id  # premise: two items, two requests, both parked
    assert len(await wired.requests.list_pending()) == 2

    response = await _approve(wired, req.id, approve=False)

    assert response["fulfilled"] is False
    assert response["request"]["status"] == "denied"
    cancelled = await wired.work_items.get_work_item(item.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.metadata["denial_reason"] == "not needed"
    assert wired.router.dispatched == []  # a denial resumes nothing
    assert spawns.calls == []
    row = await approvals.get(req.id)
    assert row is not None
    assert (row.state, row.scope_key) == ("denied", f"work_item:{item.id}")
    # control: the other parked item and its request are untouched
    kept = await wired.work_items.get_work_item(other_item.id)
    assert kept is not None
    assert kept.status == "blocked"
    assert kept.metadata["capability_request_id"] == other_req.id
    assert await approvals.get(other_req.id) is None
    assert [r.id for r in await wired.requests.list_pending()] == [other_req.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["no_policy", "escalate_without_route"])
async def test_seam_without_a_route_nothing_parks(
    wired: _Wired, approvals: SqliteCommandApprovalStore, perms: ToolPermissionStore, spawns: _Spawns, variant: str,
) -> None:
    """P-S3: the controls, the same agent and script as P-S1, without the approval route. (a) ``no_policy``: a gate with no rules
    and no route; the command runs as before (one spawn), nothing is filed, the item is left ``in_progress``. (b)
    ``escalate_without_route``: ``_ASK_PUSH`` with ``command_escalations=None``; the tool answers S2a's refusal
    (``verdict.refusal_message``), nothing spawns, nothing is filed, the item is left ``in_progress``.

    Premises: (a) ``build_command_escalations`` gives no route for a gate with no rules; (b) the policy escalates the command and
    the runtime has no route; in both the model was offered ``run_command`` and called it, which the spawn (a) and the refusal
    in the model's next prompt (b) show. Control: with the route wired, the same script over the same stores does park an item
    (so "nothing parks" here is the route's absence and not a harness that cannot park).

    Kills none of MX-1..MX-7 by itself: they all live behind the route. Through its control it fails under MX-1, MX-2, MX-6 and
    MX-7 as P-S1 does. What it pins is the acceptance criterion "no command policy, or no approval route: nothing new happens",
    end to end."""
    config = CommandPolicyConfig() if variant == "no_policy" else _policy(_ASK_PUSH)
    gate = _gate(config)
    if variant == "no_policy":
        assert gate.configured is False
        assert build_command_escalations(
            gate=gate, approvals=approvals, requests=wired.requests, work_items=wired.work_items, inbox=None,
        ) is None
    else:
        verdict = gate.judge(PUSH, site="run_command_tool", search_path=None)
        assert (verdict.decision, verdict.runs) == ("escalate", False)
        assert "ask-push" in verdict.refusal_message  # so the check that the model was told it is not vacuous
    seam = await _build_seam(wired, approvals, perms, gate, routed=False)
    assert wired.runtime.command_escalations is None
    item = await _dispatched_task(wired, seam.agent.id, "push the release branch")

    result = await seam.dispatch(item.to_dict(), _run_command_response(PUSH), _text_response("Waiting for approval."))

    assert result.success is True
    assert all("run_command" in names for names in seam.llm.offered)  # premise: offered
    if variant == "no_policy":
        assert spawns.commands == [PUSH]  # runs as before, once
    else:
        assert spawns.calls == []
        assert verdict.refusal_message in seam.llm.prompts[-1]  # premise: the call reached the tool and was refused (S2a)
    assert await wired.requests.list_pending() == []
    assert wired.requests.find_action_requests_by_param(
        "call_site", "run_command_tool", statuses=("pending", "fulfilled", "denied"),
        tool_id="run_command", action="execute",
    ) == []
    current = await wired.work_items.get_work_item(item.id)
    assert current is not None
    assert current.status == "in_progress"
    assert "capability_request_id" not in current.metadata
    assert wired.router.dispatched == []

    # control: with the route wired, the same script does file and park
    routed_gate = _gate(_policy(_ASK_PUSH))
    routed = await _build_seam(wired, approvals, perms, routed_gate, routed=True)
    parked_item, parked_req = await _escalate_and_park(wired, routed, spawns, title="push the docs branch")
    assert parked_item.id != item.id
    assert [r.id for r in await wired.requests.list_pending()] == [parked_req.id]


@pytest.mark.asyncio
async def test_seam_a_resumed_run_that_does_not_reissue_does_not_resume_itself(
    wired: _Wired, approvals: SqliteCommandApprovalStore, perms: ToolPermissionStore, spawns: _Spawns,
) -> None:
    """P-S4 (added to the contract's three; see the module docstring). The Captain approves, the item is re-dispatched, and
    the resumed run does NOT issue the command again. The approval is still active and unused (``uses == 0``) and fulfilled,
    but it was settled before this run began, so the park leaves the item ``in_progress`` instead of parking on it, resuming
    on the spot and re-dispatching it again, round and round. This is the acceptance criterion "a resumed run that does not
    re-issue the command does not resume itself", with the approval unused so that only ``_filed_since`` stands between the item
    and the loop.

    Premises: the approval is ``active`` with ``uses == 0``; the request's ``created_at`` is earlier than the moment the run
    begins; the item was re-dispatched exactly once. Control: nothing ran (the approval stays unused), and the item is not
    parked.

    Kills MX-3 (``if not _filed_since(req, since):`` -> ``if False:``: the item parks on the settled request, resumes at once
    and is handed to the router a second time)."""
    gate = _gate(_policy(_ASK_PUSH))
    seam = await _build_seam(wired, approvals, perms, gate, routed=True)
    item, req = await _escalate_and_park(wired, seam, spawns)
    await _approve(wired, req.id)
    (handed,) = _redispatched(wired)
    row = await approvals.get(req.id)
    assert row is not None
    assert (row.state, row.uses) == ("active", 0)  # premise: approved and unused, so only _filed_since can refuse the park
    settled = await wired.requests.get(req.id)
    assert settled is not None and settled.status == "fulfilled"
    began = await _clock_past(settled.created_at)
    assert settled.created_at < began  # premise: settled before the next run begins (the run's own start is later still)

    result = await seam.dispatch(handed, _text_response("Nothing further to run."))
    await wired.bus.drain()

    assert result.success is True
    assert spawns.calls == []  # control: the command did not run, so the approval is unspent
    row = await approvals.get(req.id)
    assert row is not None and (row.state, row.uses) == ("active", 0)
    assert await _status(wired, item) == "in_progress"  # not parked on the settled request
    assert len(_redispatched(wired)) == 1  # no self-resume
