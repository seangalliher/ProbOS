"""AD-1328 S2b (#1530), M4: the seam, the wiring and the golden.

Tests only. The contract is ``prompts/ad-1328-s2b-command-policy-escalation.md`` ("Tests", M4). Nothing here starts a
shell: ``asyncio.create_subprocess_shell`` and the tool module's ``ProcessTree`` are replaced by recorders (as S2a M2 does)
and ``ShellCommandAgent._run_sync`` by a recorder (as S2a M3 does). Every gate takes ``platform="linux"`` and a ``which``
that finds nothing, so the file reads the same on any host. The stores are real SQLite files in ``tmp_path``.

Test #1 is the seam of record: tool -> real ``ToolRegistry`` / ``ToolExecutor`` -> ``CommandEscalations`` -> real
``CapabilityRequestStore`` -> the real ``decide_capability_request`` -> ``fulfil_approval`` -> the approval store -> the
tool again. Each half passing alone is the signature of this repo's most common defect (every link correct, the chain
dead), so one test walks the whole chain, on the tool path and on the mesh path.

Mutants (the contract's "Mutation campaign of record"; the orchestrator runs them): F-E1 (``startup/finalize.py``,
``command_escalations=command_escalations,`` -> ``command_escalations=None,``) is killed by #3; R-E1
(``routers/capability_requests.py``, ``return await escalations.fulfil_approval(store, decided) is not None`` ->
``return False``) is killed by #1 (its ``_approve`` answers ``fulfilled`` true).

Helpers are copies, because tests do not import each other: S1's ``_policy`` / ``_rule``, S2a M2's spawn recorder
(``_Spawns``), and AD-1211's ``wired`` fixture and ``_approve`` (tests/test_ad1211_approval_fulfils_every_kind.py).
"""

from __future__ import annotations

import asyncio
import importlib
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.agents.shell_command import ShellCommandAgent
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequestStore
from probos.cognitive.capability_gap_driver import CapabilityGapDriver
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import RunCommandTool
from probos.config import SystemConfig
from probos.config_models.operations import CommandPolicyConfig
from probos.events import EventType
from probos.execution.command_approvals import SqliteCommandApprovalStore
from probos.execution.command_env import build_command_env
from probos.execution.command_escalation import (
    CommandEscalations,
    EscalationOutcome,
    build_command_escalations,
)
from probos.execution.command_gate import CommandPolicyGate
from probos.execution.process_tree import process_tree_popen_kwargs
from probos.execution.storage_declarations import STORE_DECLARATIONS
from probos.routers.capability_requests import decide_capability_request
from probos.startup.communication import _start_command_approval_store
from probos.startup.finalize import _wire_native_swe_harness
from probos.tools.executor import ToolExecutor
from probos.tools.protocol import ToolPermission, ToolResult
from probos.tools.registry import ToolRegistry
from probos.types import IntentMessage
from probos.workforce import WorkItemStore

# --------------------------------------------------------------------------------------
# Helpers (copied; tests do not import each other)
# --------------------------------------------------------------------------------------

PUSH = "git push origin"
_ASK_PUSH_WHY = "a push publishes work outside this session"
_CHILD_PATH = "S2B-SENTINEL-PATH"
#: What ``register_native_swe_tools`` gives ``run_command`` (``shell_perms``): the rank ladder the executor enforces.
_SHELL_PERMISSIONS = {"ensign": "none", "lieutenant": "none", "commander": "write", "senior_officer": "full"}


def _policy_raw(*rules: dict, unmatched: str = "allow") -> dict[str, Any]:
    """The mapping an operator writes under ``execution.command_policy`` (a ``SystemConfig`` is validated from it)."""
    return {"rules": list(rules), "unmatched_decision": unmatched}


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


class _EnvSpy:
    """Wraps the tool module's ``build_command_env`` and counts its calls; the answer is the real one."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, declared: Any = (), **kwargs: Any) -> dict[str, str]:
        self.calls.append(tuple(declared))
        return build_command_env(declared, **kwargs)


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


@pytest.fixture
def child_path(monkeypatch: pytest.MonkeyPatch) -> str:
    """The child's PATH comes from ``build_command_env``, i.e. from this process's: pin it so a test can name it."""
    monkeypatch.setenv("PATH", _CHILD_PATH)
    return _CHILD_PATH


def _spawn_of(command: str, *, cwd: str | None = None) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """The one spawn the tool makes for ``command``: the args and the exact keyword arguments (BF-890, BF-893)."""
    return (
        (command,),
        {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "cwd": cwd,
            "env": build_command_env(()),
            **process_tree_popen_kwargs(),
        },
    )


def _ran() -> ToolResult:
    """What a command that ran returns when the recorder's process answered ``(b"out", b"")`` with exit code 0."""
    return ToolResult(output={"stdout": "out", "stderr": "", "exit_code": 0})


# --------------------------------------------------------------------------------------
# The wired system (tests/test_ad1211_approval_fulfils_every_kind.py, copied and trimmed to what an ``action`` needs)
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
    """Exactly the attributes the route, the escalation service and the driver read."""


class _Wired:
    """The AD-855 loop wired the way startup wires it, plus the route."""

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


async def _work_item(wired: _Wired, title: str) -> Any:
    """A work item the asking agent is working on (``in_progress``), as a crew child's loop context names it."""
    item = await wired.work_items.create_work_item(
        title=title, description=title, work_type="task", assigned_to="agent-1", created_by="captain",
    )
    await wired.work_items.transition_work_item(item.id, "in_progress", source="agent-1")
    assert await _status(wired, item) == "in_progress"
    return item


async def _status(wired: _Wired, item: Any) -> str:
    current = await wired.work_items.get_work_item(item.id)
    assert current is not None
    return str(current.status)


def _route(wired: _Wired, approvals: SqliteCommandApprovalStore, gate: CommandPolicyGate) -> tuple[ToolExecutor, ToolRegistry]:
    """What startup builds for one policy: the service (``build_command_escalations``, the real factory) exposed as
    ``runtime.command_escalations`` for the router, and a real registry holding ``RunCommandTool(gate, service)`` behind
    a real executor. A second call stands for a restart under another policy over the same stores."""
    escalations = build_command_escalations(
        gate=gate, approvals=approvals, requests=wired.requests, work_items=wired.work_items, inbox=None,
    )
    assert isinstance(escalations, CommandEscalations)
    wired.runtime.command_escalations = escalations
    registry = ToolRegistry()
    registry.register(
        RunCommandTool(wired.runtime, command_policy_gate=gate, command_escalations=escalations),  # type: ignore[arg-type]
        default_permissions=dict(_SHELL_PERMISSIONS),
    )
    wired.runtime.tool_registry = registry
    return ToolExecutor(registry=registry), registry


async def _call(executor: ToolExecutor, command: str, item: Any, *, agent_id: str = "agent-1") -> ToolResult:
    """``run_command`` through the real executor and registry, for ``agent_id`` at rank ``commander``, in ``item``'s scope."""
    return await executor.invoke(
        agent_id, "run_command", {"command": command}, required=ToolPermission.WRITE, agent_rank="commander",
        context={"_crew_work_item_id": item.id, "thread_id": "t1"},
    )


def _ran_shell(command: str) -> dict[str, Any]:
    """What the shell agent's recorder ``_run_sync`` answers: the shape the real one returns on success."""
    return {"success": True, "data": {"stdout": "ok", "stderr": "", "exit_code": 0, "command": command}}


# --------------------------------------------------------------------------------------
# 1. The seam of record: escalate -> approve -> run once -> reuse -> fresh escalations (and the mesh path)
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seam_escalate_approve_run_once_reuse_then_fresh_escalation(
    wired: _Wired, approvals: SqliteCommandApprovalStore, spawns: _Spawns, child_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M4 #1, the seam of record. One escalated ``run_command`` crosses the whole chain: the tool (real registry and
    executor) -> the service -> the real request store -> the REST decision (the real ``decide_capability_request``) ->
    ``fulfil_approval`` -> the approval store -> the tool again, then the scope, digest and mesh controls. Kills R-E1
    (``fulfil_approval`` answering nothing leaves ``fulfilled`` false, the approval unrecorded and the re-issue refused)."""
    gate = _gate(_policy(_ASK_PUSH))
    executor, registry = _route(wired, approvals, gate)
    item = await _work_item(wired, "push the release branch")
    scope = f"work_item:{item.id}"
    # premises: the policy escalates this very command and allows its neighbour; the real rank ladder lets a commander
    # run it and an ensign not; nothing is filed or decided yet
    verdict = gate.judge(PUSH, site="run_command_tool", search_path=None)
    assert (verdict.decision, verdict.runs) == ("escalate", False)
    assert gate.judge("echo hi", site="run_command_tool", search_path=None).runs is True
    assert registry.check_permission("agent-1", "run_command", ToolPermission.WRITE, agent_rank="commander")
    assert not registry.check_permission("agent-1", "run_command", ToolPermission.WRITE, agent_rank="ensign")
    assert await wired.requests.list_pending() == []
    assert wired.runtime.command_escalations is not None

    # 1. escalate: nothing spawns and one pending request names the rule and its justification
    filed = await _call(executor, PUSH, item)
    assert filed.error is not None and filed.output is None
    assert spawns.commands == []
    (req1,) = await wired.requests.list_pending()
    assert (req1.kind, req1.agent_id, req1.work_item_id) == ("action", "agent-1", item.id)
    payload = req1.payload
    assert (payload["tool_id"], payload["action"], payload["scope_key"]) == ("run_command", "execute", scope)
    assert payload["params"]["rules"] == ["ask-push"]
    assert [(c["kind"], c["rule"], c["text"]) for c in payload["params"]["causes"]] == [
        ("rule", "ask-push", _ASK_PUSH_WHY),
    ]
    assert payload["params"]["policy_digest"] == gate.digest
    assert f"request {req1.id}" in filed.error and "ask-push" in filed.error and _ASK_PUSH_WHY in filed.error
    assert filed.metadata["command_policy"]["approval"] == {"state": "filed", "request_id": req1.id, "use_id": None}
    assert await approvals.get(req1.id) is None  # nothing is recorded until the Captain decides

    # 2. the Captain approves through the real route: it records the approval, fulfils the request, and runs nothing
    response = await _approve(wired, req1.id)
    assert response["fulfilled"] is True
    assert response["request"]["status"] == "fulfilled"
    assert EventType.CAPABILITY_REQUEST_FULFILLED.value in wired.bus.emitted
    row = await approvals.get(req1.id)
    assert row is not None
    assert (row.state, row.agent_id, row.scope_key, row.policy_digest, row.approver, row.uses) == (
        "active", "agent-1", scope, gate.digest, "captain", 0,
    )
    assert row.canonical_key == payload["params"]["canonical_key"]
    assert spawns.commands == []  # approval never replays the command (AD-1154, BF-830)
    assert await _status(wired, item) == "in_progress"  # S2b parks nothing, so the AD-855 driver has nothing to resume

    # 3. the agent issues the same command again: it runs once, recorded as the approved run naming the request
    first_run = await _call(executor, PUSH, item)
    assert first_run.error is None
    assert first_run.output == _ran().output
    assert spawns.commands == [PUSH]
    (use1,) = await approvals.list_uses(req1.id)
    assert (use1.use_kind, use1.request_id, use1.agent_id, use1.scope_key) == ("approved_run", req1.id, "agent-1", scope)
    record = first_run.metadata["command_policy"]
    assert record["decision"] == "escalate"  # the policy's own decision stands; the approval is what admitted the run
    assert record["approval"] == {"state": "approved_run", "request_id": req1.id, "use_id": use1.use_id}

    # 4. again: it runs again, as a reuse naming the same request, and files nothing
    second_run = await _call(executor, PUSH, item)
    assert second_run.error is None
    assert spawns.commands == [PUSH, PUSH]
    uses = await approvals.list_uses(req1.id)
    assert [(u.use_kind, u.request_id) for u in uses] == [("approved_run", req1.id), ("reuse", req1.id)]
    assert second_run.metadata["command_policy"]["approval"] == {
        "state": "reuse", "request_id": req1.id, "use_id": uses[1].use_id,
    }
    assert await wired.requests.list_pending() == []

    # 5. control, the scope: the same command in a second work item is a new request and spawns nothing
    other_item = await _work_item(wired, "push another branch")
    other = await _call(executor, PUSH, other_item)
    assert other.error is not None and other.metadata["command_policy"]["approval"]["state"] == "filed"
    (req2,) = await wired.requests.list_pending()
    assert req2.id != req1.id and req2.work_item_id == other_item.id
    assert req2.payload["scope_key"] == f"work_item:{other_item.id}"
    assert spawns.commands == [PUSH, PUSH]
    assert len(await approvals.list_uses(req1.id)) == 2  # the first scope's approval was not touched

    # 6. control, the digest: a new gate with one more rule (another digest) and a new service over the same stores asks again
    gate2 = _gate(_policy(_ASK_PUSH, _rule("ok-echo", ["echo"], "allow")))
    assert gate2.digest != gate.digest  # premise
    executor2, _ = _route(wired, approvals, gate2)
    again = await _call(executor2, PUSH, item)
    assert again.error is not None and again.metadata["command_policy"]["approval"]["state"] == "filed"
    pending = await wired.requests.list_pending()
    (req3,) = [req for req in pending if req.id not in (req1.id, req2.id)]
    assert req3.work_item_id == item.id and req3.payload["params"]["policy_digest"] == gate2.digest
    assert len(pending) == 2
    assert spawns.commands == [PUSH, PUSH]  # the old approval admits nothing under another policy
    assert len(await approvals.list_uses(req1.id)) == 2

    # control, the machine: a command the policy allows runs through the same chain and files nothing
    allowed = await _call(executor2, "echo hi", item)
    assert allowed.error is None and allowed.metadata["command_policy"]["decision"] == "allow"
    assert allowed.metadata["command_policy"]["approval"] is None
    assert spawns.commands == [PUSH, PUSH, "echo hi"]
    assert len(await wired.requests.list_pending()) == 2

    # the mesh half: a shell agent with the same escalate gate keeps S2a's refusal -- no spawn, no request, no confidence
    mesh_runs: list[str] = []
    monkeypatch.setattr(
        ShellCommandAgent, "_run_sync",
        lambda self, command, deadline=None, slot=None: mesh_runs.append(command) or _ran_shell(command),
    )
    agent = ShellCommandAgent(pool="shell", command_policy_gate=gate)
    intent = IntentMessage(intent="run_command", params={"command": PUSH})
    plan = await agent.decide(await agent.perceive(intent.__dict__))
    assert plan == {"action": "run", "command": PUSH}  # premise: the agent plans to run it, so the refusal is the policy's
    confidence = agent.confidence
    requests_before = len(await wired.requests.list_pending())

    mesh = await agent.handle_intent(intent)

    assert mesh is not None and mesh.success is False and mesh.result is None
    assert "ask-push" in mesh.error and "no approval was requested" in mesh.error
    assert mesh_runs == []
    assert len(await wired.requests.list_pending()) == requests_before
    assert len(await approvals.list_uses(req1.id)) == 2  # the mesh path never touches the approval store
    assert agent.confidence == confidence and mesh.confidence == confidence
    # control: an allowed command through the same agent runs, and its success does move the confidence
    ran = await agent.handle_intent(IntentMessage(intent="run_command", params={"command": "git status"}))
    assert ran is not None and ran.success is True
    assert mesh_runs == ["git status"]
    assert agent.confidence > confidence
    assert await _status(wired, item) == "in_progress"


# --------------------------------------------------------------------------------------
# 2. A denial stays a denial in its scope, and parks nothing
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seam_denial(
    wired: _Wired, approvals: SqliteCommandApprovalStore, spawns: _Spawns, child_path: str,
) -> None:
    """Escalate -> the Captain denies -> the same call is refused as denied: no new request, no spawn, and the work item's
    status is unchanged (S2b parks nothing, so the AD-855 driver, which cancels a BLOCKED item on a denial, has nothing to cancel)."""
    gate = _gate(_policy(_ASK_PUSH))
    executor, _ = _route(wired, approvals, gate)
    item = await _work_item(wired, "push the release branch")
    await _call(executor, PUSH, item)
    (req,) = await wired.requests.list_pending()  # premise: one pending ask

    response = await _approve(wired, req.id, approve=False)

    assert response["fulfilled"] is False
    assert response["request"]["status"] == "denied"
    assert EventType.CAPABILITY_REQUEST_DECIDED.value in wired.bus.emitted
    assert EventType.CAPABILITY_REQUEST_FULFILLED.value not in wired.bus.emitted
    row = await approvals.get(req.id)
    assert row is not None and (row.state, row.scope_key, row.approver) == ("denied", f"work_item:{item.id}", "captain")

    again = await _call(executor, PUSH, item)

    assert again.error is not None and again.output is None
    assert "denied this command" in again.error and f"request {req.id}" in again.error
    assert again.metadata["command_policy"]["approval"] == {"state": "denied", "request_id": req.id, "use_id": None}
    assert spawns.commands == []
    assert await wired.requests.list_pending() == []  # no new request: the denial answers the repeat
    assert await _status(wired, item) == "in_progress"  # nothing parked it, so nothing cancelled it

    # control 1: the denial is for this command only -- a neighbour in the same scope is filed, approved, and runs
    neighbour = "git push origin main"
    await _call(executor, neighbour, item)
    (req2,) = await wired.requests.list_pending()
    assert req2.id != req.id
    assert (await _approve(wired, req2.id))["fulfilled"] is True
    ran = await _call(executor, neighbour, item)
    assert ran.error is None and spawns.commands == [neighbour]
    # control 2: the AD-855 driver is live in this very fixture -- an item PARKED on a denied request is cancelled
    parked = await _work_item(wired, "parked on an ordinary action")
    ordinary = await wired.requests.file_request(
        agent_id="agent-1", kind="action", target="browser.click",
        rationale=f"work item {parked.id} blocked on capability: browser.click", work_item_id=parked.id,
    )
    assert await wired.driver.block_on_request(
        work_item_id=parked.id, request_id=ordinary.id, reason="browser.click",
    ) is True
    assert await _status(wired, parked) == "blocked"
    await _approve(wired, ordinary.id, approve=False)
    assert await _status(wired, parked) == "cancelled"
    assert await _status(wired, item) == "in_progress"  # and the escalating item was never touched


@pytest.mark.asyncio
async def test_seam_denial_dominates_an_earlier_approval(
    wired: _Wired, approvals: SqliteCommandApprovalStore, spawns: _Spawns, child_path: str,
) -> None:
    """AD-1328 S2b repair r1, M4 #7. Two requests carry one identity (``PUSH`` and its two-space spelling canonicalise
    alike, but the payload's display command differs, so AD-1154 dedup does not fold them). The Captain approves A, the
    command runs once, then denies B through the real REST decision: the next call is the denied frame naming B and
    spawns nothing. The chain is tool -> registry -> service -> request store -> REST decision -> store -> tool.
    Kills St4 (``command_approvals.py``, the ``use`` UPDATE's ``AND denial.state = 'denied' AND denial.expires_at > ?) ``
    -> ``AND 0 AND ...``): without the denial clause in ``use`` the approved A is still admitted and the command runs again."""
    gate = _gate(_policy(_ASK_PUSH))
    executor, _ = _route(wired, approvals, gate)
    item = await _work_item(wired, "push the release branch")
    scope = f"work_item:{item.id}"
    variant = "git  push origin"

    # premises: both spellings escalate and share one canonical key; two distinct requests are pending; nothing ran
    assert variant != PUSH
    verdict = gate.judge(PUSH, site="run_command_tool", search_path=None)
    verdict2 = gate.judge(variant, site="run_command_tool", search_path=None)
    assert (verdict.decision, verdict.runs) == ("escalate", False)
    assert (verdict2.decision, verdict2.runs) == ("escalate", False)
    assert verdict.canonical.key == verdict2.canonical.key
    await _call(executor, PUSH, item)
    (req_a,) = await wired.requests.list_pending()
    await _call(executor, variant, item)
    pending = await wired.requests.list_pending()
    assert len(pending) == 2
    (req_b,) = [req for req in pending if req.id != req_a.id]
    assert req_a.payload["params"]["canonical_key"] == req_b.payload["params"]["canonical_key"]
    assert (req_a.payload["scope_key"], req_b.payload["scope_key"]) == (scope, scope)
    assert spawns.commands == []

    # approve A: it is fulfilled and the command runs (the control: an approval alone admits the run)
    assert (await _approve(wired, req_a.id))["fulfilled"] is True
    first = await _call(executor, PUSH, item)
    assert first.error is None
    assert spawns.commands == [PUSH]
    assert first.metadata["command_policy"]["approval"]["state"] == "approved_run"
    assert first.metadata["command_policy"]["approval"]["request_id"] == req_a.id
    assert len(await approvals.list_uses(req_a.id)) == 1

    # deny B through the REST decision: a live denial of the same identity under another request id
    response = await _approve(wired, req_b.id, approve=False)
    assert response["fulfilled"] is False
    assert response["request"]["status"] == "denied"
    denied_row = await approvals.get(req_b.id)
    assert denied_row is not None and (denied_row.state, denied_row.scope_key) == ("denied", scope)
    approved_row = await approvals.get(req_a.id)
    assert approved_row is not None and (approved_row.state, approved_row.uses) == ("active", 1)  # A still stands, used once

    # the repeat is refused as denied, names B, spawns nothing, files nothing, and A's use count does not move
    again = await _call(executor, PUSH, item)

    assert again.error is not None and again.output is None
    assert "denied this command" in again.error and f"request {req_b.id}" in again.error
    assert again.metadata["command_policy"]["approval"] == {"state": "denied", "request_id": req_b.id, "use_id": None}
    assert spawns.commands == [PUSH]  # no new spawn
    assert await wired.requests.list_pending() == []
    assert len(await approvals.list_uses(req_a.id)) == 1
    refreshed = await approvals.get(req_a.id)
    assert refreshed is not None and refreshed.uses == 1

    # negative control: a neighbouring command in the same scope is not caught by the denial; it is filed, approved, runs
    neighbour = "git push origin main"
    await _call(executor, neighbour, item)
    (req_n,) = await wired.requests.list_pending()
    assert req_n.id not in (req_a.id, req_b.id)
    assert (await _approve(wired, req_n.id))["fulfilled"] is True
    ran = await _call(executor, neighbour, item)
    assert ran.error is None
    assert spawns.commands == [PUSH, neighbour]


# --------------------------------------------------------------------------------------
# 3. Startup builds the route and hands it to the tool
# --------------------------------------------------------------------------------------


class _FakeExecutor:
    """Stands in for the ToolExecutor: ``_wire_native_swe_harness`` only calls ``add_pre_hook`` on it."""

    def __init__(self) -> None:
        self.pre_hooks: list[Any] = []

    def add_pre_hook(self, hook: Any) -> None:
        self.pre_hooks.append(hook)


class _FakeApprovals:
    """Records the lookups the service makes on the approval store; it holds no approval."""

    def __init__(self) -> None:
        self.finds: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def find(self, *args: Any, **kwargs: Any) -> None:
        self.finds.append((args, kwargs))
        return None


class _FakeRequests:
    """Records what the service files on the request store, and answers a request id of the AD-1154 form."""

    FILED_ID = "00000000-0000-4000-8000-000000000001"

    def __init__(self) -> None:
        self.filed: list[tuple[str, dict[str, Any], str | None]] = []

    def count_pending_sync(self, agent_id: str, *, stale_before: float = 0.0) -> int:
        return 0

    async def file_action_request(
        self, agent_id: str, payload: dict[str, Any], *, rationale: str = "", work_item_id: str | None = None,
    ) -> Any:
        self.filed.append((agent_id, payload, work_item_id))
        return SimpleNamespace(id=self.FILED_ID)


@pytest.mark.asyncio
async def test_finalize_builds_and_injects_the_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_wire_native_swe_harness`` builds the one ``CommandEscalations`` from the runtime's gate and stores, hands it to
    ``register_native_swe_tools`` and exposes it as ``runtime.command_escalations``; with no rules (or a store missing) it is
    None in both places. Kills F-E1 (``command_escalations=command_escalations,`` -> ``command_escalations=None,`` in
    ``startup/finalize.py``): the exposed service would still be built, but the registered tool would get none."""
    captured: list[dict[str, Any]] = []

    def capture(registry: Any, runtime: Any, **kwargs: Any) -> int:
        captured.append(kwargs)
        return 0

    monkeypatch.setattr(swe_tools, "register_native_swe_tools", capture)
    config = SystemConfig()
    gate = _gate(_policy(_ASK_PUSH))
    approvals, requests, items = _FakeApprovals(), _FakeRequests(), object()
    stand_in = SimpleNamespace(
        tool_registry=ToolRegistry(), config=config, command_policy_gate=gate,
        command_approval_store=approvals, capability_request_store=requests, work_item_store=items,
    )
    assert gate.configured is True  # premise: a policy with rules

    # No llm_client: the wiring registers the tools (here, the capture), then returns False before building a harness.
    assert _wire_native_swe_harness(runtime=stand_in, config=config, tool_executor=_FakeExecutor()) is False

    (kwargs,) = captured  # premise: the registration was reached, exactly once
    route = kwargs["command_escalations"]
    assert isinstance(route, CommandEscalations)
    assert stand_in.command_escalations is route  # the router reads the very object the tool was given
    assert kwargs["command_policy_gate"] is gate
    # the route holds the runtime's own stores, each in its own place: an escalation consults the approval store, then files
    # on the request store, scoped to the work item
    verdict = gate.judge(PUSH, site="run_command_tool", search_path=None)
    outcome = await route.resolve(
        verdict, command=PUSH, context={"agent_id": "agent-1", "_crew_work_item_id": "wi-1"},
    )
    assert outcome.verdict.approval == {"state": "filed", "request_id": _FakeRequests.FILED_ID, "use_id": None}
    assert approvals.finds != []
    assert [(agent, work_item) for agent, _, work_item in requests.filed] == [("agent-1", "wi-1")]

    # controls: with no rules, or a store the route needs missing, nothing is built, and the tool is given None
    unconfigured = _gate(CommandPolicyConfig())
    assert unconfigured.configured is False
    for label, runtime in (
        ("no_rules", SimpleNamespace(
            tool_registry=ToolRegistry(), config=config, command_policy_gate=unconfigured,
            command_approval_store=approvals, capability_request_store=requests, work_item_store=items)),
        ("no_approval_store", SimpleNamespace(
            tool_registry=ToolRegistry(), config=config, command_policy_gate=gate,
            command_approval_store=None, capability_request_store=requests, work_item_store=items)),
        ("no_gate", SimpleNamespace(
            tool_registry=ToolRegistry(), config=config,
            command_approval_store=approvals, capability_request_store=requests, work_item_store=items)),
    ):
        captured.clear()
        assert _wire_native_swe_harness(runtime=runtime, config=config, tool_executor=_FakeExecutor()) is False, label
        (kwargs,) = captured
        assert kwargs["command_escalations"] is None, label
        assert runtime.command_escalations is None, label


# --------------------------------------------------------------------------------------
# 4. The approval store starts only with rules
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_starts_only_with_rules(tmp_path: Path) -> None:
    """No rules: no store and no database file (zero-config boot unchanged). One rule: a started store and its file."""
    empty = SystemConfig()
    assert empty.execution.command_policy.rules == ()  # premise
    database = tmp_path / "command_approvals.db"

    assert await _start_command_approval_store(empty, tmp_path) is None
    assert not database.exists()

    ruled = SystemConfig.model_validate({"execution": {"command_policy": _policy_raw(_ASK_PUSH)}})
    assert len(ruled.execution.command_policy.rules) == 1  # premise: the control has a rule
    store = await _start_command_approval_store(ruled, tmp_path)
    assert isinstance(store, SqliteCommandApprovalStore)
    try:
        assert database.exists()
        assert await store.find("agent-1", "", "a" * 64, "digest", state="active") is None  # started: it answers
    finally:
        await store.stop()
    with pytest.raises(RuntimeError):  # stopped: it fails closed
        await store.find("agent-1", "", "a" * 64, "digest", state="active")


# --------------------------------------------------------------------------------------
# 5. The store is declared
# --------------------------------------------------------------------------------------


def test_store_declaration_resolves() -> None:
    """``execution.command-approvals`` is declared, its owner imports, and it names the file the starter writes."""
    declared = {declaration.id: declaration for declaration in STORE_DECLARATIONS}
    assert len(declared) == len(STORE_DECLARATIONS)  # premise: ids are unique
    assert "execution.command-approvals" in declared
    declaration = declared["execution.command-approvals"]

    module = importlib.import_module(declaration.owner_module)

    assert getattr(module, declaration.owner_symbol) is SqliteCommandApprovalStore
    assert declaration.canonical_path == "command_approvals.db"
    # control: the declarations hold another store with another owner, and a symbol the module lacks does not resolve
    others = [d for d in STORE_DECLARATIONS if d.id != declaration.id]
    assert others and all((d.owner_module, d.owner_symbol) != (declaration.owner_module, declaration.owner_symbol) for d in others)
    assert getattr(module, "NoSuchCommandApprovalStore", None) is None


# --------------------------------------------------------------------------------------
# 6. No policy: byte for byte what the tool did before, with an escalation service handed in
# --------------------------------------------------------------------------------------


class _SpyEscalations:
    """A stand-in service: records every call and refuses with a fixed text."""

    REFUSAL = "the spy refuses"

    def __init__(self) -> None:
        self.calls: list[tuple[Any, str, Any]] = []

    async def resolve(self, verdict: Any, *, command: str, context: Any) -> EscalationOutcome:
        self.calls.append((verdict, command, context))
        return EscalationOutcome(verdict, self.REFUSAL)


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["no_gate", "unconfigured_gate"])
async def test_no_policy_is_byte_identical(
    variant: str, spawns: _Spawns, child_path: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S2a M2 #1's assertions, with ``command_escalations=`` a spy: with no policy the spy is never called, and the spawn and
    the result are exactly what the tool did before S2a."""
    monkeypatch.setenv("S2B_PROBE_SECRET", "planted")
    expected_env = build_command_env(())
    # premise: the process holds a planted secret that the child's allowlisted environment leaves out, and the child's PATH is ours
    assert os.environ["S2B_PROBE_SECRET"] == "planted"
    assert "S2B_PROBE_SECRET" not in expected_env
    assert expected_env["PATH"] == child_path
    env_spy = _EnvSpy()
    monkeypatch.setattr(swe_tools, "build_command_env", env_spy)
    which = _Which()
    gate = None if variant == "no_gate" else _gate(CommandPolicyConfig(), which=which)
    if gate is not None:
        assert gate.configured is False  # premise: no rules, so no policy
        assert gate.digest is None
    spy = _SpyEscalations()
    tool = RunCommandTool(SimpleNamespace(), command_policy_gate=gate, command_escalations=spy)  # type: ignore[arg-type]

    result = await tool.invoke({"command": "echo hi"})

    assert spy.calls == []  # the service is never consulted without a policy
    assert spawns.calls == [_spawn_of("echo hi")]  # one spawn: the command text and every keyword argument, exactly
    assert result == _ran()
    assert result.metadata == {}
    assert len(spawns.attached) == 1  # the BF-893 tree is attached to the spawned process and released
    assert spawns.tree_events == ["close"]
    assert env_spy.calls == [()]  # exactly one child environment was built: the spawn's
    assert which.calls == []

    # control: a configured policy that escalates DOES reach the spy (so the silence above is not a spy that cannot be
    # reached), and the tool then refuses with the spy's text and spawns nothing more
    escalating = RunCommandTool(
        SimpleNamespace(), command_policy_gate=_gate(_policy(_ASK_PUSH)), command_escalations=spy,  # type: ignore[arg-type]
    )
    refused = await escalating.invoke({"command": PUSH})
    assert [(command, context) for _, command, context in spy.calls] == [(PUSH, None)]
    assert refused.error == _SpyEscalations.REFUSAL
    assert spawns.calls == [_spawn_of("echo hi")]
