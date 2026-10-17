"""AD-1328 S2b (#1530), M3: an escalated ``run_command`` at the tool, the record gate, the router and the shell agent.

Tests only. The contract is ``prompts/ad-1328-s2b-command-policy-escalation.md`` ("Tests", M3). Nothing here starts a shell:
``asyncio.create_subprocess_shell`` and the tool module's ``ProcessTree`` are replaced by recorders (S2a M2's, copied),
``ShellCommandAgent._run_sync`` by a recorder (S2a M3's, copied), and every gate is built with ``platform="linux"`` and a ``which``
that finds nothing, so the file reads the same on any host. The stores are real: ``SqliteCommandApprovalStore`` and
``CapabilityRequestStore(db_path=...)`` on SQLite files in ``tmp_path``; only the work-item reader is a dict-backed stand-in.

Each test asserts its premise (what the policy itself says about the very text) and a negative control: the accepted neighbour of
every refusal and the refused neighbour of every run, so a test cannot pass because the whole machine refuses (or runs) everything.
The helpers are copies, because tests do not import each other: S1's ``_policy`` / ``_rule``, S2a M2's spawn recorder and its
AD-1224 sink helpers, S2a M3's ``_run_sync`` recorder.

Mutation map (the contract's "Mutation campaign of record", which the orchestrator runs): E1 is killed by #3; G-E2 by #5; G-E3 by
#5 ``approval_on_forbid``; G-E4 by #5, #11 and #12; R-E1 by #6; R-E2 by #7; Sh-E1 by #9.

Measurements of record (D5, re-anchoring S2a's B10 and B31 at record v2): see #11 and #12, where each measured size is written.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.agents.shell_command import ShellCommandAgent
from probos.api_models import CapabilityRequestDecideRequest
from probos.capability_request import CapabilityRequest, CapabilityRequestStore
from probos.cognitive import decomposer
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import RunCommandTool
from probos.config_models.operations import CommandPolicyConfig
from probos.events import EventType
from probos.execution.command_approvals import SqliteCommandApprovalStore, command_approval_request
from probos.execution.command_env import build_command_env
from probos.execution.command_escalation import CommandEscalations
from probos.execution.command_gate import (
    COMMAND_POLICY_UNAVAILABLE_MESSAGE,
    MAX_RECORD_CHARS,
    RECORD_SCHEMA,
    CommandPolicyGate,
    command_policy_record_of,
    compact_command_policy_record,
)
from probos.execution.command_policy import parse_command
from probos.execution.process_tree import process_tree_popen_kwargs
from probos.routers import capability_requests as router_mod
from probos.substrate.event_log import EventLog
from probos.tools import executor as executor_module
from probos.tools.executor import DEFAULT_MAX_RECORDS_PER_RUN, ToolExecutor, make_audit_hook, make_start_hook
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import IntentMessage
from probos.workforce import build_value_provenance

# --------------------------------------------------------------------------------------
# Helpers (copied; tests do not import each other)
# --------------------------------------------------------------------------------------


def _policy(*rules: dict, unmatched: str = "allow", **extra: object) -> CommandPolicyConfig:
    """S1's helper (tests/test_ad1328_s1_policy_evaluation.py)."""
    return CommandPolicyConfig.model_validate({"rules": list(rules), "unmatched_decision": unmatched, **extra})


def _rule(name: str, pattern: list, decision: str, **extra: object) -> dict:
    """S1's helper (tests/test_ad1328_s1_policy_evaluation.py)."""
    base = {"name": name, "pattern": pattern, "decision": decision, "justification": f"{name} because"}
    if decision == "forbid":
        base["alternative"] = "use the governed path"
    return {**base, **extra}


_ASK_PUSH_WHY = "a push publishes work outside this session"
_NO_PUSH_WHY = "pushes go through the release agent"
_NO_PUSH_INSTEAD = "ask the release agent to push"
_CHILD_PATH = "S2B-SENTINEL-PATH"
_V1_SCHEMA = "probos.command_policy.record/v1"  # S2a's record version: S2b's sink admits only v2
_WORK_ITEM = "W1"
_COMMAND = "git push origin"
_OTHER_COMMAND = "git push --force"
_ALLOWED = "git status"
_SHELL_PERMISSIONS = {"ensign": "none", "lieutenant": "none", "commander": "write", "senior_officer": "full"}


def _stack() -> CommandPolicyConfig:
    """``git`` allowed and ``git push`` escalated: the strictest matching rule wins, so a push escalates and ``git status`` runs."""
    return _policy(
        _rule("allow-git", ["git"], "allow"),
        _rule("ask-push", ["git", "push"], "escalate", justification=_ASK_PUSH_WHY),
        unmatched="allow",
    )


def _forbid_stack() -> CommandPolicyConfig:
    """``git`` allowed and ``git push`` forbidden."""
    return _policy(
        _rule("allow-git", ["git"], "allow"),
        _rule("no-push", ["git", "push"], "forbid", justification=_NO_PUSH_WHY, alternative=_NO_PUSH_INSTEAD),
        unmatched="allow",
    )


def _no_which(name: str, path: str | None = None) -> None:
    """A program lookup that finds nothing: no test here reads the real PATH."""
    return None


def _gate(config: CommandPolicyConfig) -> CommandPolicyGate:
    return CommandPolicyGate(config, platform="linux", which=_no_which)


def _words(command: str, config: CommandPolicyConfig) -> list[list[str]]:
    """The simple commands S1's closed grammar reads ``command`` as under ``posix``: the premise of a test that names one."""
    parsed = parse_command(command, dialect="posix", limits=config)  # type: ignore[arg-type]
    assert parsed.unparseable is None, parsed.unparseable
    assert all(segment.unparseable is None for segment in parsed.segments), command
    return [list(segment.tokens) for segment in parsed.segments]


def _not_a_capability_gap(text: str) -> None:
    """The frames are error-shaped, not a capability gap (AD-1154 DD-2): the real decomposer regex must not fire."""
    assert decomposer._CAPABILITY_GAP_RE.search(text) is None, text


def _context() -> dict[str, Any]:
    """What ``ToolRegistry.check_and_invoke`` hands a crew child's tool: the asker and its work item."""
    return {"agent_id": "a1", "_crew_work_item_id": _WORK_ITEM}


# --------------------------------------------------------------------------------------
# The spawn recorder (S2a M2's; no real shell)
# --------------------------------------------------------------------------------------


class _Process:
    """What ``create_subprocess_shell`` returns: ``communicate()`` gives ``(b"out", b"")`` and the exit code is 0."""

    pid = 4242
    returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"out", b""

    def kill(self) -> None:
        raise AssertionError("the tool ends the tree through ProcessTree, never the process directly")


class _Tree:
    """What the fake ``ProcessTree.attach`` returns."""

    def kill(self) -> None:
        return None

    def close(self) -> None:
        return None


class _Spawns:
    """Records every spawn ``(args, kwargs)`` and every tree attached."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.attached: list[_Process] = []

    async def create_subprocess_shell(self, *args: Any, **kwargs: Any) -> _Process:
        self.calls.append((args, kwargs))
        return _Process()

    def attach(self, proc: _Process) -> _Tree:
        self.attached.append(proc)
        return _Tree()


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
    """The one spawn the tool makes for ``command``: the args and S2a's exact keyword arguments (BF-890, BF-893)."""
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


# --------------------------------------------------------------------------------------
# The approval route: real stores in tmp_path, a dict-backed work-item reader
# --------------------------------------------------------------------------------------


class _WorkItems:
    """The work-item reader the service consults: ``get_work_item(id)`` -> an item with a ``status``, or None."""

    def __init__(self, statuses: dict[str, str]) -> None:
        self.statuses = dict(statuses)

    async def get_work_item(self, work_item_id: str) -> Any:
        status = self.statuses.get(work_item_id)
        return None if status is None else SimpleNamespace(status=status)


@dataclasses.dataclass
class _Wired:
    gate: CommandPolicyGate
    approvals: SqliteCommandApprovalStore
    requests: CapabilityRequestStore
    work_items: _WorkItems
    service: CommandEscalations


@contextlib.asynccontextmanager
async def _wired(tmp_path: Path, gate: CommandPolicyGate) -> AsyncIterator[_Wired]:
    """The real command-approval store and AD-1154 request store on SQLite in ``tmp_path``, and the real service over them."""
    approvals = SqliteCommandApprovalStore(str(tmp_path / "command_approvals.db"))
    requests = CapabilityRequestStore(db_path=str(tmp_path / "capability_requests.db"))
    await approvals.start()
    try:
        await requests.start()
        try:
            work_items = _WorkItems({_WORK_ITEM: "in_progress"})
            service = CommandEscalations(gate=gate, approvals=approvals, requests=requests, work_items=work_items)
            yield _Wired(gate, approvals, requests, work_items, service)
        finally:
            await requests.stop()
    finally:
        await approvals.stop()


class _RecordedRoute:
    """The real ``CommandEscalations`` behind a recorder: each ``(decision, command)`` the tool handed to ``resolve``."""

    def __init__(self, inner: CommandEscalations) -> None:
        self._inner = inner
        self.resolved: list[tuple[str | None, str]] = []

    async def resolve(self, verdict: Any, *, command: str, context: Any) -> Any:
        self.resolved.append((verdict.decision, command))
        return await self._inner.resolve(verdict, command=command, context=context)


class _ExplodingRoute:
    """An approval route whose ``resolve`` raises."""

    def __init__(self) -> None:
        self.calls = 0

    async def resolve(self, verdict: Any, *, command: str, context: Any) -> Any:
        self.calls += 1
        raise RuntimeError("the approval route exploded")


class _SpyRoute:
    """What the router asks of the route, answered as the real one answers a recorded decision."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def fulfil_approval(self, request_store: Any, decided: Any) -> Any:
        self.calls.append(("fulfil_approval", decided.id))
        return decided

    async def record_denial(self, decided: Any) -> bool:
        self.calls.append(("record_denial", decided.id))
        return True


class _RaisingRoute:
    """A route whose two router-facing methods raise."""

    async def fulfil_approval(self, request_store: Any, decided: Any) -> Any:
        raise RuntimeError("the route exploded while fulfilling")

    async def record_denial(self, decided: Any) -> bool:
        raise RuntimeError("the route exploded while recording a denial")


def _tool(gate: CommandPolicyGate | None = None, route: Any = None) -> RunCommandTool:
    return RunCommandTool(SimpleNamespace(), command_policy_gate=gate, command_escalations=route)  # type: ignore[arg-type]


async def _filed(tool: RunCommandTool, wired: _Wired, command: str) -> CapabilityRequest:
    """Escalate ``command`` through the tool and return the AD-1154 request it filed (the premise of the router tests)."""
    result = await tool.invoke({"command": command}, _context())
    assert result.error is not None
    approval = result.metadata["command_policy"]["approval"]
    assert approval["state"] == "filed"
    request = await wired.requests.get(approval["request_id"])
    assert request is not None and request.status == "pending"
    assert command_approval_request(request) is not None  # premise: a well-formed command escalation
    return request


def _browser_payload(selector: str) -> dict[str, Any]:
    """An ordinary AD-1154 browser action payload: the kind of ``action`` request that is not a command escalation."""
    return {
        "tool_id": "browser_click", "action": "click", "params": {"selector": selector},
        "scope_key": "", "session_id": "s1", "thread_id": "t1",
    }


# --------------------------------------------------------------------------------------
# 1-4. The tool
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_files_then_runs_once_then_reuses(spawns: _Spawns, child_path: str, tmp_path: Path) -> None:
    """The whole chain at the tool: an escalation is filed and not run; once the Captain's approval is recorded the same command
    runs (``approved_run``) and runs again in the same work item (``reuse``). Controls: another escalated command is filed anew
    and not run, and an allowed command runs without ever reaching the route."""
    config = _stack()
    gate = _gate(config)
    assert _words(_COMMAND, config) == [["git", "push", "origin"]]  # premise: one plain simple command ...
    verdict = gate.judge(_COMMAND, site="run_command_tool", search_path=child_path)
    assert (verdict.decision, verdict.runs) == ("escalate", False)  # ... which the policy escalates, by this rule
    assert [cause.rule for cause in verdict.causes] == ["ask-push"]
    other = gate.judge(_OTHER_COMMAND, site="run_command_tool", search_path=child_path)
    assert (other.decision, other.runs) == ("escalate", False)  # premise: the control is escalated too ...
    assert other.canonical.key != verdict.canonical.key  # ... under another approval key

    async with _wired(tmp_path, gate) as wired:
        route = _RecordedRoute(wired.service)
        tool = _tool(gate, route)

        # 1. Escalated: filed, not run.
        filed = await tool.invoke({"command": _COMMAND}, _context())

        assert spawns.calls == [] and spawns.attached == []
        assert filed.output is None
        assert filed.error is not None
        approval = filed.metadata["command_policy"]["approval"]
        assert set(approval) == {"state", "request_id", "use_id"}
        assert (approval["state"], approval["use_id"]) == ("filed", None)
        request_id = approval["request_id"]
        assert str(uuid.UUID(request_id)) == request_id  # a real AD-1154 request id
        assert f"filed for review as request {request_id}" in filed.error
        assert "was not run" in filed.error
        assert "Rule 'ask-push'" in filed.error and _ASK_PUSH_WHY in filed.error
        assert "no approval was requested" not in filed.error  # not S2a's frame: the route did file it
        _not_a_capability_gap(filed.error)
        request = await wired.requests.get(request_id)
        assert request is not None and request.status == "pending"
        assert (request.agent_id, request.kind, request.work_item_id) == ("a1", "action", _WORK_ITEM)
        ask = command_approval_request(request)
        assert ask is not None
        assert (ask.scope_key, ask.canonical_key, ask.policy_digest) == (
            f"work_item:{_WORK_ITEM}", verdict.canonical.key, gate.digest,
        )

        # A repeat before any approval is folded into the same request and is not run either.
        repeated = await tool.invoke({"command": _COMMAND}, _context())
        assert repeated.metadata["command_policy"]["approval"] == approval
        assert len(await wired.requests.list_pending()) == 1
        assert spawns.calls == []

        # 2. The Captain approves and the approval is recorded; approving does not run the command (AD-1154, BF-830).
        decided = await wired.requests.decide(request_id, True, decided_by="captain")
        assert decided is not None and decided.status == "approved"
        assert await wired.approvals.get(request_id) is None
        fulfilled = await wired.service.fulfil_approval(wired.requests, decided)
        assert fulfilled is not None and fulfilled.status == "fulfilled"
        row = await wired.approvals.get(request_id)
        assert row is not None and (row.state, row.uses) == ("active", 0)
        assert spawns.calls == []

        # 3. The agent issues the same command again: one spawn, with S2a's exact keyword arguments, recorded as approved_run.
        ran = await tool.invoke({"command": _COMMAND}, _context())

        assert ran.error is None
        assert ran.output == {"stdout": "out", "stderr": "", "exit_code": 0}
        assert spawns.calls == [_spawn_of(_COMMAND)]
        first_use = ran.metadata["command_policy"]["approval"]
        assert (first_use["state"], first_use["request_id"]) == ("approved_run", request_id)
        assert len(first_use["use_id"]) == 32 and int(first_use["use_id"], 16) >= 0

        # 4. And again in the same work item: a second spawn, recorded as a reuse of the same approval.
        reused = await tool.invoke({"command": _COMMAND}, _context())

        assert reused.error is None
        assert spawns.calls == [_spawn_of(_COMMAND), _spawn_of(_COMMAND)]
        second_use = reused.metadata["command_policy"]["approval"]
        assert (second_use["state"], second_use["request_id"]) == ("reuse", request_id)
        assert second_use["use_id"] != first_use["use_id"]
        uses = await wired.approvals.list_uses(request_id)
        assert [(use.use_kind, use.use_id, use.request_id) for use in uses] == [
            ("approved_run", first_use["use_id"], request_id), ("reuse", second_use["use_id"], request_id),
        ]
        assert (await wired.approvals.get(request_id)).uses == 2

        # Control: an approval is for one command; another escalated command is filed anew and not run.
        refiled = await tool.invoke({"command": _OTHER_COMMAND}, _context())
        assert refiled.error is not None
        other_approval = refiled.metadata["command_policy"]["approval"]
        assert other_approval["state"] == "filed" and other_approval["request_id"] != request_id
        assert len(spawns.calls) == 2  # still only the two approved runs

        # Control: an allowed command runs under the same gate and never reaches the route.
        allowed = await tool.invoke({"command": _ALLOWED}, _context())
        assert allowed.error is None
        assert allowed.metadata["command_policy"]["decision"] == "allow"
        assert allowed.metadata["command_policy"]["approval"] is None
        assert spawns.calls[-1] == _spawn_of(_ALLOWED) and len(spawns.calls) == 3
        assert {decision for decision, _ in route.resolved} == {"escalate"}
        assert _ALLOWED not in [command for _, command in route.resolved]

        # The seam to the AD-1224 sink: every record the real tool produced above, with ids issued by the real stores, is one
        # the sink admits unchanged. A store id outside the sink's closed forms would drop the record: every link right, the chain dead.
        for result in (filed, repeated, ran, reused, refiled, allowed):
            record = result.metadata["command_policy"]
            assert _admitted(record) == record


@pytest.mark.asyncio
async def test_tool_without_a_route_keeps_the_s2a_refusal(spawns: _Spawns, child_path: str, tmp_path: Path) -> None:
    """``command_escalations=None``: an escalation is refused with S2a's frame, as before, and the record says no route was asked."""
    config = _stack()
    gate = _gate(config)
    verdict = gate.judge(_COMMAND, site="run_command_tool", search_path=child_path)
    assert (verdict.decision, verdict.runs) == ("escalate", False)  # premise
    tool = _tool(gate, None)

    refused = await tool.invoke({"command": _COMMAND}, _context())

    assert spawns.calls == [] and spawns.attached == []
    assert refused.output is None
    assert refused.error == verdict.refusal_message  # S2a's frame, word for word
    assert "no approval was requested" in refused.error
    _not_a_capability_gap(refused.error)
    assert set(refused.metadata) == {"command_policy"}
    record = refused.metadata["command_policy"]
    assert record["schema"] == RECORD_SCHEMA
    assert record["decision"] == "escalate"
    assert record["approval"] is None
    # control: with a route the same call, under the same gate, is filed: another frame and an approval entry
    async with _wired(tmp_path, gate) as wired:
        routed = await _tool(gate, wired.service).invoke({"command": _COMMAND}, _context())
        assert routed.error is not None and routed.error != refused.error
        assert "no approval was requested" not in routed.error
        assert routed.metadata["command_policy"]["approval"]["state"] == "filed"
        assert len(await wired.requests.list_pending()) == 1
    # control: an allowed command runs through the route-less tool
    ran = await tool.invoke({"command": _ALLOWED}, _context())
    assert ran.error is None and spawns.calls == [_spawn_of(_ALLOWED)]


@pytest.mark.asyncio
async def test_forbid_with_an_approval_on_record_is_refused(spawns: _Spawns, child_path: str, tmp_path: Path) -> None:
    """Kills E1. An approval never runs a command whose own decision is ``forbid``: not through the tool, and not by the
    verdict's own ``runs`` when an approval is put on it."""
    forbid_config = _forbid_stack()
    gate = _gate(forbid_config)
    forbidden = gate.judge(_COMMAND, site="run_command_tool", search_path=child_path)
    assert (forbidden.decision, forbidden.runs) == ("forbid", False)  # premise: the policy forbids this very command
    escalated = _gate(_stack()).judge(_COMMAND, site="run_command_tool", search_path=child_path)
    assert (escalated.decision, escalated.runs) == ("escalate", False)  # control: the same command, escalated

    async with _wired(tmp_path, gate) as wired:
        request_id = str(uuid.uuid4())
        row = await wired.approvals.record_decision(
            request_id=request_id, agent_id="a1", scope_key=f"work_item:{_WORK_ITEM}",
            canonical_key=forbidden.canonical.key, policy_digest=gate.digest, state="active", approver="captain",
            ttl_seconds=3600.0,
        )
        assert row is not None and row.state == "active"
        # premise: the approval is on record for exactly this agent, scope, canonical command and digest
        assert await wired.approvals.find(
            "a1", f"work_item:{_WORK_ITEM}", forbidden.canonical.key, gate.digest, state="active",
        ) is not None
        route = _RecordedRoute(wired.service)
        tool = _tool(gate, route)

        refused = await tool.invoke({"command": _COMMAND}, _context())

        assert spawns.calls == [] and spawns.attached == []
        assert refused.output is None
        assert refused.error == forbidden.refusal_message  # the forbid frame, not a filing and not a run
        assert _NO_PUSH_WHY in refused.error and _NO_PUSH_INSTEAD in refused.error
        _not_a_capability_gap(refused.error)
        record = refused.metadata["command_policy"]
        assert (record["decision"], record["approval"]) == ("forbid", None)
        assert route.resolved == []  # a forbid never reaches the approval route
        assert await wired.requests.list_pending() == []  # nothing filed
        assert (await wired.approvals.get(request_id)).uses == 0 and await wired.approvals.list_uses(request_id) == []
        # control: an allowed neighbour runs under the same gate
        ran = await tool.invoke({"command": _ALLOWED}, _context())
        assert ran.error is None and spawns.calls == [_spawn_of(_ALLOWED)]

    # The verdict itself: an approved_run entry put on a forbid verdict does not make it run (kills E1) ...
    entry = {"state": "approved_run", "request_id": str(uuid.uuid4()), "use_id": uuid.uuid4().hex}
    approved_forbid = dataclasses.replace(forbidden, approval=entry)
    assert approved_forbid.approval == entry  # premise: the approval is on the verdict
    assert approved_forbid.runs is False
    assert approved_forbid.denial_reason == "command_policy_forbid"
    assert approved_forbid.refusal_message == forbidden.refusal_message
    # ... while the same entry on an escalation does (the control: `runs` does read the approval), and a filed one does not
    assert dataclasses.replace(escalated, approval=entry).runs is True
    assert dataclasses.replace(
        escalated, approval={"state": "filed", "request_id": entry["request_id"], "use_id": None},
    ).runs is False


@pytest.mark.asyncio
async def test_service_error_does_not_spawn(spawns: _Spawns, child_path: str) -> None:
    """A route that raises does not run the command: the tool answers ``run_command failed:`` and keeps the escalate record."""
    gate = _gate(_stack())
    assert gate.judge(_COMMAND, site="run_command_tool", search_path=child_path).runs is False  # premise
    route = _ExplodingRoute()
    tool = _tool(gate, route)

    failed = await tool.invoke({"command": _COMMAND}, _context())

    assert route.calls == 1  # premise: the route was asked, and it is what raised
    assert spawns.calls == [] and spawns.attached == []
    assert failed.output is None
    assert failed.error is not None and failed.error.startswith("run_command failed:")
    assert "the approval route exploded" in failed.error
    record = failed.metadata["command_policy"]
    assert (record["decision"], record["approval"]) == ("escalate", None)  # the decision stands; nothing was approved
    # control: an allowed command never needs the route and runs
    ran = await tool.invoke({"command": _ALLOWED}, _context())
    assert ran.error is None
    assert spawns.calls == [_spawn_of(_ALLOWED)]
    assert route.calls == 1


# --------------------------------------------------------------------------------------
# 5. The record gate: record v2
# --------------------------------------------------------------------------------------


def _admitted(record: Any) -> dict[str, Any] | None:
    """What the AD-1224 sink keeps of the record a ``run_command`` result carried."""
    return command_policy_record_of(ToolResult(output={}, metadata={"command_policy": record}), tool_id="run_command")


def _record_of(config: CommandPolicyConfig, command: str, decision: str) -> dict[str, Any]:
    verdict = _gate(config).judge(command, site="run_command_tool", search_path=_CHILD_PATH)
    record = verdict.record
    assert record is not None and record["decision"] == decision and record["approval"] is None
    assert record["schema"] == RECORD_SCHEMA
    return record


def _uuid_with_a_letter() -> str:
    """A request id whose upper-case form differs from it (a uuid of ten digits and no letter is possible, if rare)."""
    while True:
        candidate = str(uuid.uuid4())
        if candidate != candidate.upper():
            return candidate


_ACCEPTED_CASES = ("none", "filed", "denied", "inbox_full", "approved_run", "reuse")
_REJECTED_CASES = (
    "extra_key", "bad_state", "list_state", "request_id_not_uuid", "request_id_upper", "use_id_not_hex32",
    "use_id_on_filed", "request_id_on_unfiled", "run_without_use_id", "approval_on_forbid", "v1_schema",
)


def _record_case(case: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The record a tool result carries for ``case`` and its accepted neighbour: the same record one change from valid.

    Both are built from a real verdict's record: an ``escalate``, or for ``approval_on_forbid`` a ``forbid``.
    """
    request_id = _uuid_with_a_letter()
    use_id = uuid.uuid4().hex
    filed = {"state": "filed", "request_id": request_id, "use_id": None}
    unfiled = {"state": "unfiled", "request_id": None, "use_id": None}
    ran = {"state": "approved_run", "request_id": request_id, "use_id": use_id}
    entries: dict[str, Any] = {
        "none": None,
        "filed": filed,
        "denied": {**filed, "state": "denied"},
        "inbox_full": {"state": "inbox_full", "request_id": None, "use_id": None},
        "approved_run": ran,
        "reuse": {**ran, "state": "reuse"},
        "extra_key": {**filed, "command": "git push --token=abc"},
        "bad_state": {**filed, "state": "approved"},
        "list_state": {**filed, "state": ["filed"]},
        "request_id_not_uuid": {**filed, "request_id": "not-a-request-id"},
        "request_id_upper": {**filed, "request_id": request_id.upper()},
        "use_id_not_hex32": {**ran, "use_id": str(uuid.uuid4())},
        "use_id_on_filed": {**filed, "use_id": use_id},
        "request_id_on_unfiled": {**unfiled, "request_id": request_id},
        "run_without_use_id": {**ran, "use_id": None},
        "approval_on_forbid": filed,
        "v1_schema": None,
    }
    valid: dict[str, Any] = {  # the nearest valid entry for each refused one
        "extra_key": filed, "bad_state": filed, "list_state": filed, "request_id_not_uuid": filed,
        "request_id_upper": filed, "use_id_not_hex32": ran, "use_id_on_filed": filed, "request_id_on_unfiled": unfiled,
        "run_without_use_id": ran, "approval_on_forbid": filed, "v1_schema": None,
    }
    escalate = _record_of(_stack(), _COMMAND, "escalate")
    base = _record_of(_forbid_stack(), _COMMAND, "forbid") if case == "approval_on_forbid" else escalate
    record = {**base, "approval": entries[case]}
    if case == "v1_schema":
        record["schema"] = _V1_SCHEMA
    neighbour = {**escalate, "approval": valid.get(case, entries[case])}
    return record, neighbour


@pytest.mark.parametrize("case", [*_ACCEPTED_CASES, *_REJECTED_CASES])
def test_record_v2_validation(case: str) -> None:
    """Kills G-E2 (every refused entry), G-E3 (``approval_on_forbid``) and G-E4 (the two ids of ``approved_run`` and ``reuse``).

    The sink admits exactly the six forms the approval route writes (and no approval), rebuilds the ``approval`` entry field by
    field, and drops the whole record, never repairing it, for anything else.
    """
    record, neighbour = _record_case(case)
    assert _admitted(neighbour) == neighbour  # premise: the neighbour is admitted unchanged, so only this one change can refuse
    if case == "approval_on_forbid":
        assert (record["decision"], record["approval"]["state"]) == ("forbid", "filed")
        assert neighbour["decision"] == "escalate"  # the same entry on an escalation is the control
        assert _admitted({**record, "approval": None}) == {**record, "approval": None}  # premise: the forbid record itself is fine
    if case == "v1_schema":
        assert (record["schema"], record["approval"]) == (_V1_SCHEMA, None)
        assert neighbour["schema"] == RECORD_SCHEMA

    admitted = _admitted(record)

    if case in _ACCEPTED_CASES:
        assert admitted == record
        assert admitted is not record
        if record["approval"] is not None:
            assert type(admitted["approval"]) is dict
            assert admitted["approval"] == record["approval"]
            assert admitted["approval"] is not record["approval"]  # rebuilt, not carried over
    else:
        assert admitted is None
        assert record != neighbour


# --------------------------------------------------------------------------------------
# 6-8. The router
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_router_fulfils_and_records_denial(spawns: _Spawns, child_path: str, tmp_path: Path) -> None:
    """Kills R-E1. Approving a command escalation records the approval and fulfils the request; denying one records the denial.

    A router with no route, a route that raises, or an ordinary browser request records nothing and answers False (the request
    stays approved, so the Captain can retry: BF-722). Then the tool, crossing the seam, runs the approved command and refuses the
    denied one.
    """
    gate = _gate(_stack())
    async with _wired(tmp_path, gate) as wired:
        tool = _tool(gate, wired.service)
        first = await _filed(tool, wired, _COMMAND)
        second = await _filed(tool, wired, _OTHER_COMMAND)
        ordinary = await wired.requests.file_action_request(
            "a1", _browser_payload("#buy"), rationale="an ordinary browser action", work_item_id=_WORK_ITEM,
        )
        ordinary_two = await wired.requests.file_action_request(
            "a1", _browser_payload("#cancel"), rationale="another browser action", work_item_id=_WORK_ITEM,
        )
        assert ordinary is not None and ordinary_two is not None
        assert command_approval_request(ordinary) is None  # premise: an ordinary action request is not a command escalation
        approved = await wired.requests.decide(first.id, True, decided_by="captain")
        denied = await wired.requests.decide(second.id, False, reason="not this push", decided_by="captain")
        ordinary_approved = await wired.requests.decide(ordinary.id, True, decided_by="captain")
        ordinary_denied = await wired.requests.decide(ordinary_two.id, False, reason="no", decided_by="captain")
        assert approved is not None and approved.status == "approved"
        assert denied is not None and denied.status == "denied"
        assert ordinary_approved is not None and ordinary_denied is not None
        fulfil = router_mod._maybe_fulfil_on_approval
        no_route = SimpleNamespace()  # no ``command_escalations`` at all
        unwired = SimpleNamespace(command_escalations=None)

        # No route: False, and nothing is recorded, for an approval and for a denial.
        assert await fulfil(no_route, wired.requests, approved, approve=True) is False
        assert await fulfil(unwired, wired.requests, approved, approve=True) is False
        assert await fulfil(no_route, wired.requests, denied, approve=False) is False
        assert await wired.approvals.get(first.id) is None and await wired.approvals.get(second.id) is None

        # A route that raises: False, nothing recorded, and the request is left approved for a retry.
        raising = SimpleNamespace(command_escalations=_RaisingRoute())
        assert await fulfil(raising, wired.requests, approved, approve=True) is False
        assert await fulfil(raising, wired.requests, denied, approve=False) is False
        assert await wired.approvals.get(first.id) is None and await wired.approvals.get(second.id) is None
        assert (await wired.requests.get(first.id)).status == "approved"

        # A route that is asked: a command escalation reaches it; an ordinary action request does not (no fulfiller).
        spy = _SpyRoute()
        spied = SimpleNamespace(command_escalations=spy)
        assert await fulfil(spied, wired.requests, approved, approve=True) is True
        assert spy.calls == [("fulfil_approval", first.id)]
        assert await fulfil(spied, wired.requests, denied, approve=False) is False
        assert spy.calls == [("fulfil_approval", first.id), ("record_denial", second.id)]
        assert await fulfil(spied, wired.requests, ordinary_approved, approve=True) is False
        assert await fulfil(spied, wired.requests, ordinary_denied, approve=False) is False
        assert len(spy.calls) == 2  # the ordinary requests never touched the route

        # The real route: an approval is recorded active and the request fulfilled; a denial is recorded denied.
        runtime = SimpleNamespace(command_escalations=wired.service)
        assert await fulfil(runtime, wired.requests, approved, approve=True) is True
        row = await wired.approvals.get(first.id)
        assert row is not None
        assert (row.state, row.approver, row.agent_id, row.scope_key) == ("active", "captain", "a1", f"work_item:{_WORK_ITEM}")
        assert (await wired.requests.get(first.id)).status == "fulfilled"
        assert await fulfil(runtime, wired.requests, denied, approve=False) is False
        denial = await wired.approvals.get(second.id)
        assert denial is not None
        assert (denial.state, denial.agent_id, denial.scope_key) == ("denied", "a1", f"work_item:{_WORK_ITEM}")
        assert (await wired.requests.get(second.id)).status == "denied"
        assert spawns.calls == []  # approving and denying run nothing

        # Across the seam: the agent's next identical call runs, and the denied command is refused as denied.
        ran = await tool.invoke({"command": _COMMAND}, _context())
        assert ran.error is None and spawns.calls == [_spawn_of(_COMMAND)]
        assert ran.metadata["command_policy"]["approval"]["state"] == "approved_run"
        assert ran.metadata["command_policy"]["approval"]["request_id"] == first.id
        refused = await tool.invoke({"command": _OTHER_COMMAND}, _context())
        assert refused.error is not None and len(spawns.calls) == 1
        assert refused.metadata["command_policy"]["approval"] == {"state": "denied", "request_id": second.id, "use_id": None}
        for result in (ran, refused):  # the seam to the AD-1224 sink: the records built from the real stores' ids are admitted
            record = result.metadata["command_policy"]
            assert _admitted(record) == record


@pytest.mark.asyncio
async def test_command_request_grants_no_standing_rule(spawns: _Spawns, child_path: str, tmp_path: Path) -> None:
    """Kills R-E2. A command escalation grants no standing rule, with every other gate open: the control is an ordinary browser
    action request, decided the same way under the same runtime, which does get one."""

    class _ActionApprovals:
        """The AD-1154 standing-rule store as ``_maybe_issue_standing_rule`` calls it; it records each rule issued."""

        def __init__(self) -> None:
            self.issued: list[tuple[str, str, str, str]] = []

        async def issue_approval(
            self, agent_id: str, tool_id: str, action: str, *, scope_key: str, ttl_seconds: float, reason: str,
            issued_by: str,
        ) -> Any:
            self.issued.append((agent_id, tool_id, action, scope_key))
            return SimpleNamespace(
                id="rule-1", agent_id=agent_id, tool_id=tool_id, action=action, scope_key=scope_key, issued_at=1.0,
                expires_at=1.0 + ttl_seconds,
            )

    class _ConfirmedWorkItems:
        """A work item whose value band and stakes are both confirmed by the Captain (AD-1321): the last gate to a rule."""

        async def get_work_item(self, work_item_id: str) -> Any:
            confirmed = build_value_provenance(source_kind="captain", source_id="captain", recorded_at=10.0, confirmed=True)
            return SimpleNamespace(
                value_band="minor", value_band_provenance=confirmed, stakes="low", stakes_provenance=dict(confirmed),
            )

    gate = _gate(_stack())
    async with _wired(tmp_path, gate) as wired:
        first = await _filed(_tool(gate, wired.service), wired, _COMMAND)
        ordinary = await wired.requests.file_action_request(
            "a1", _browser_payload("#buy"), rationale="an ordinary browser action", work_item_id=_WORK_ITEM,
        )
        assert ordinary is not None
        command_request = await wired.requests.decide(first.id, True, decided_by="captain")
        ordinary_request = await wired.requests.decide(ordinary.id, True, decided_by="captain")
        assert command_request is not None and ordinary_request is not None
        assert command_request.kind == ordinary_request.kind == "action"  # premise: the same kind, so only the guard tells them apart
        assert command_request.work_item_id == ordinary_request.work_item_id == _WORK_ITEM
        store = _ActionApprovals()
        runtime = SimpleNamespace(
            action_approval_store=store,
            work_item_store=_ConfirmedWorkItems(),
            config=SimpleNamespace(
                approval_inbox=SimpleNamespace(
                    standing_rules_enabled=True, standing_rule_max_ttl_hours=168, standing_rule_default_ttl_hours=24,
                ),
            ),
        )
        decision = CapabilityRequestDecideRequest(
            approve=True, reason="run exactly this", grant_standing=True, standing_ttl_hours=1,
        )

        granted = await router_mod._maybe_issue_standing_rule(runtime, command_request, decision)

        assert granted is None
        assert store.issued == []  # the action-approval store was never touched
        # control: the ordinary request, under the same runtime and the same decision, is issued a rule
        rule = await router_mod._maybe_issue_standing_rule(runtime, ordinary_request, decision)
        assert rule is not None
        assert (rule["agent_id"], rule["tool_id"], rule["action"], rule["scope_key"]) == ("a1", "browser_click", "click", "")
        assert store.issued == [("a1", "browser_click", "click", "")]
        assert spawns.calls == []


def test_existing_router_pins_hold() -> None:
    """S2b adds no ``action`` fulfiller and does not widen the standing-rule kinds: the command route is its own branch."""
    assert "action" not in router_mod._APPROVAL_FULFILLERS
    assert router_mod._STANDING_RULE_KINDS == {"action", "continue"}
    # control: the map is the real, populated one, so the first line is not true of an empty dict
    assert {"continue", "grant"} <= set(router_mod._APPROVAL_FULFILLERS)
    assert "browser" not in router_mod._STANDING_RULE_KINDS and "grant" not in router_mod._STANDING_RULE_KINDS


# --------------------------------------------------------------------------------------
# 9-10. The shell agent (the mesh path: S2a's refusal, no route)
# --------------------------------------------------------------------------------------


def _ran_sync(command: str) -> dict[str, Any]:
    """What the recorder's ``_run_sync`` answers: the shape the real one returns on success."""
    return {"success": True, "data": {"stdout": "ok", "stderr": "", "exit_code": 0, "command": command}}


class _Runs:
    """Every ``(command, deadline, slot)`` ``ShellCommandAgent._run_sync`` was asked to run (S2a M3's recorder, copied)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, Any]] = []
        self.answer: dict[str, Any] | None = None  # a fixed answer; None: the success shape

    def __call__(self, command: str, deadline: Any, slot: Any) -> dict[str, Any]:
        self.calls.append((command, deadline, slot))
        return _ran_sync(command) if self.answer is None else dict(self.answer)

    @property
    def commands(self) -> list[str]:
        return [call[0] for call in self.calls]


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> _Runs:
    recorder = _Runs()
    monkeypatch.setattr(
        ShellCommandAgent, "_run_sync",
        lambda self, command, deadline=None, slot=None: recorder(command, deadline, slot),
    )
    return recorder


def _explode(
    self: CommandPolicyGate, command: str, *, site: str, search_path: str | None, cwd: str | None = None,
    pathext: str | None = None,
) -> Any:
    raise RuntimeError("the judgement exploded")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["forbid", "escalate", "judgement_error"])
async def test_shell_refusals_do_not_move_confidence(case: str, runs: _Runs, monkeypatch: pytest.MonkeyPatch) -> None:
    """Kills Sh-E1. A command-policy refusal is the policy's decision, not the agent's failure: through ``handle_intent`` the
    agent's confidence and counters do not move and ``_run_sync`` is not called. Control: an agent with no policy has its
    confidence lowered by a failed run and raised by a successful one."""
    config = _forbid_stack() if case == "forbid" else _stack()
    gate = _gate(config)
    agent = ShellCommandAgent(pool="shell", command_policy_gate=gate)
    initial = agent.confidence
    intent = IntentMessage(intent="run_command", params={"command": _COMMAND})
    # premise: decide() plans to run it (git is one of its builtins on every host), so the refusal below is the policy's
    plan = await agent.decide(await agent.perceive(intent.__dict__))
    assert plan == {"action": "run", "command": _COMMAND}
    if case == "judgement_error":
        monkeypatch.setattr(CommandPolicyGate, "judge", _explode)
        with pytest.raises(RuntimeError):
            gate.judge(_COMMAND, site="shell_command_agent", search_path=None)  # premise: the judgement itself raises
        expected = COMMAND_POLICY_UNAVAILABLE_MESSAGE
    else:
        verdict = gate.judge(_COMMAND, site="shell_command_agent", search_path=None)
        assert (verdict.decision, verdict.runs) == (case, False)  # premise: the policy itself refuses this very command
        expected = verdict.refusal_message

    result = await agent.handle_intent(intent)

    assert result is not None
    assert result.success is False
    assert result.result is None
    assert result.error == expected
    assert runs.calls == []  # nothing was run
    assert result.confidence == initial and agent.confidence == initial  # unchanged ...
    assert (agent.meta.success_count, agent.meta.failure_count) == (0, 0)  # ... and no outcome was counted

    # control: an agent with no policy is moved by what it runs (the judgement patched above is never reached: there is no gate)
    plain = ShellCommandAgent(pool="shell")
    runs.answer = {"success": False, "error": "x"}
    failed = await plain.handle_intent(IntentMessage(intent="run_command", params={"command": _ALLOWED}))
    assert failed is not None and failed.success is False and failed.error == "x"
    assert plain.confidence < initial and plain.meta.failure_count == 1
    runs.answer = None
    succeeded = await plain.handle_intent(IntentMessage(intent="run_command", params={"command": _ALLOWED}))
    assert succeeded is not None and succeeded.success is True
    assert plain.confidence > failed.confidence and plain.meta.success_count == 1
    assert runs.commands == [_ALLOWED, _ALLOWED]  # only the two control runs reached _run_sync, never a refused command


@pytest.mark.asyncio
async def test_mesh_escalation_files_nothing(runs: _Runs, spawns: _Spawns, child_path: str, tmp_path: Path) -> None:
    """The mesh path has no approval route: a shell agent under an escalating gate refuses with S2a's frame and files nothing,
    in a request store that is running in this test. Control: the tool, with a route, files the same command in the same store."""
    gate = _gate(_stack())
    verdict = gate.judge(_COMMAND, site="shell_command_agent", search_path=None)
    assert (verdict.decision, verdict.runs) == ("escalate", False)  # premise: the policy escalates this very command
    async with _wired(tmp_path, gate) as wired:
        agent = ShellCommandAgent(pool="shell", command_policy_gate=gate)
        # the agent holds no store and no route: it has nothing to file with
        assert not any(
            isinstance(value, (CapabilityRequestStore, CommandEscalations, SqliteCommandApprovalStore))
            for value in vars(agent).values()
        )

        result = await agent.handle_intent(IntentMessage(intent="run_command", params={"command": _COMMAND}))

        assert result is not None
        assert result.success is False and result.result is None
        assert result.error is not None and "no approval was requested" in result.error
        assert result.error == verdict.refusal_message
        _not_a_capability_gap(result.error)
        assert runs.calls == []
        assert await wired.requests.list_pending() == [] and await wired.requests.list_actionable() == []
        assert wired.requests.count_pending_sync(agent.id) == 0

        # control: through the tool, with the route over this very store, the same escalation is filed for this agent
        routed = await _tool(gate, wired.service).invoke({"command": _COMMAND}, {"agent_id": agent.id})
        assert routed.error is not None and "no approval was requested" not in routed.error
        assert routed.metadata["command_policy"]["approval"]["state"] == "filed"
        pending = await wired.requests.list_pending()
        assert [(request.agent_id, request.kind) for request in pending] == [(agent.id, "action")]
        assert spawns.calls == []


# --------------------------------------------------------------------------------------
# 11-12. Measurements of record (D5): the largest record, and its place in the AD-1224 envelope
# --------------------------------------------------------------------------------------


def _largest_record(approval: dict[str, Any] | None) -> dict[str, Any]:
    """S2a's B10 maximum at v2: the longest value of every typed field, with ``approval`` as given."""
    names = [f"r{index}-" + "x" * 61 for index in range(8)]
    assert [len(name) for name in names] == [64] * 8
    return {
        "schema": RECORD_SCHEMA,
        "call_site": "run_command_tool",
        "decision": "escalate",
        "dialect": "posix",
        "policy_digest": "a" * 64,
        "canonical_key": "b" * 64,
        "canonical_kind": "script",
        "matched_rules": list(names),
        "matched_rules_omitted": 2**31 - 1,
        "causes": [{"kind": "rule", "segment": 2**31 - 1, "rule": name} for name in names],
        "causes_omitted": 2**31 - 1,
        "approval": approval,
    }


def _approved_run() -> dict[str, Any]:
    """The longest ``approval`` entry: the two ids, and the longest state that carries them."""
    return {"state": "approved_run", "request_id": str(uuid.uuid4()), "use_id": uuid.uuid4().hex}


def test_the_largest_v2_record_is_within_the_bound() -> None:
    """S2a's B10 maximum, re-anchored at record v2 (D5): 8 rule names of 64 characters, 8 ``rule`` causes with segment
    ``2**31 - 1``, both counts ``2**31 - 1``, and the longest ``approval`` entry. Also kills G-E4 (an ``approved_run`` whose use id
    is not carried through is not accepted unchanged).

    Measured 2026-10-16 (``json.dumps(record, sort_keys=True)``): this record, with ``approval`` = ``approved_run`` and a
    36-character request id and 32-character use id, is 2,037 characters, 11 under ``MAX_RECORD_CHARS`` (2,048); with
    ``"approval": None`` it is 1,916, 121 shorter.
    """
    approval = _approved_run()
    record = _largest_record(approval)

    admitted = _admitted(record)

    assert admitted == record  # accepted unchanged
    assert admitted["approval"] == approval and admitted["approval"] is not approval
    size = len(json.dumps(record, sort_keys=True))
    assert size <= MAX_RECORD_CHARS  # measured: 2,037 characters, 11 under the 2,048 bound (D5)
    # control: without the approval the record is exactly the approval entry's extra length shorter ...
    without = {**record, "approval": None}
    assert _admitted(without) == without
    assert len(json.dumps(without, sort_keys=True)) == size - 121
    # ... and each field is typed to its own bound, so no admitted record is longer than this one: a ninth rule name, a
    # 65-character rule name, a count above 2**31 - 1 and a second approval key are all refused
    assert _admitted({**record, "matched_rules": [*record["matched_rules"], "x"]}) is None
    assert _admitted({**record, "matched_rules": ["x" * 65]}) is None
    assert _admitted({**record, "causes_omitted": 2**31}) is None
    assert _admitted({**record, "approval": {**approval, "command": "x"}}) is None


_WIDE_COMMAND = ";".join(f"c{index:02d}" for index in range(20))


class _StandInTool:
    """Not a RunCommandTool: a tool whose result metadata is whatever the test hands it (S2a M2's, copied)."""

    tool_id = "stand_in_tool"
    name = "Stand In"
    tool_type = ToolType.UTILITY_AGENT
    description = "returns the metadata it was given"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(self, metadata: Any) -> None:
        self._metadata = metadata

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(error="stand-in refusal", metadata=self._metadata)


class _RunCommandStandIn(_StandInTool):
    """A tool that registers as ``run_command`` and reports the metadata it was given."""

    tool_id = "run_command"


class _MaximalRecordTool(_RunCommandStandIn):
    """Registers as ``run_command`` and returns a successful result carrying the metadata it was given."""

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(output={}, metadata=self._metadata)


def _recorded(tool: Any) -> tuple[ToolRegistry, ToolExecutor, list[tuple[Any, dict[str, Any]]]]:
    """A real executor over a real registry holding ``tool`` (shell permission by rank), with the AD-1224 hook on the bus."""
    registry = ToolRegistry()
    registry.register(tool, default_permissions=dict(_SHELL_PERMISSIONS))
    executor = ToolExecutor(registry=registry)
    emitted: list[tuple[Any, dict[str, Any]]] = []
    executor.add_post_hook(make_audit_hook(lambda event, payload: emitted.append((event, payload))))
    return registry, executor, emitted


def _paired(executor: ToolExecutor, log: Any, *, max_records_per_run: int = DEFAULT_MAX_RECORDS_PER_RUN) -> None:
    """tests/test_ad1224_durable_tool_start.py:114-125 (copied; tests do not import each other)."""
    executor.add_pre_hook(make_start_hook(event_log=log, max_records_per_run=max_records_per_run))
    audit = make_audit_hook(event_log=log)
    executor.add_post_hook(audit)
    executor.add_terminal_hook(audit)


async def _rows(log: EventLog, event: str) -> list[dict[str, Any]]:
    """tests/test_ad1224_durable_tool_start.py:110-112 (copied)."""
    return [row for row in await log.query(category="tool", limit=1000) if row["event"] == event]


async def _wide_call(executor: ToolExecutor, provenance: str) -> ToolResult:
    return await executor.invoke(
        provenance, "run_command", {"command": _WIDE_COMMAND}, required=ToolPermission.WRITE, agent_rank="commander",
        context={"thread_id": provenance, "_crew_work_item_id": provenance, "_agentic_run_id": provenance},
    )


async def _durable_data(tmp_path: Path, name: str, record: dict[str, Any], provenance: str) -> dict[str, Any]:
    """The ``data`` of the one durable ``TOOL_INVOKED`` row a call leaves in a real ``EventLog`` in ``tmp_path``."""
    log = EventLog(db_path=tmp_path / name)
    await log.start()
    try:
        registry = ToolRegistry()
        registry.register(_MaximalRecordTool({"command_policy": record}), default_permissions=dict(_SHELL_PERMISSIONS))
        executor = ToolExecutor(registry=registry)
        _paired(executor, log)

        await _wide_call(executor, provenance)

        rows = await _rows(log, EventType.TOOL_INVOKED.value)
        assert len(rows) == 1
        return rows[0]["data"]
    finally:
        await log.stop()


@pytest.mark.asyncio
async def test_the_largest_approved_record_is_compacted_with_its_approval(tmp_path: Path) -> None:
    """S2a's B31 at record v2 (D5), no patch: the real 4,096-byte bound and maximal provenance. The largest admitted record
    with an approval no longer fits whole, so the sink keeps its compact form, and the compact form keeps the approval. Also
    kills G-E4 (the retained record is the admitted one, with the use id carried through).

    Measured 2026-10-16 (``executor._record_size``, the AD-1224 envelope with ``'"' * 200`` provenance): with the #11 record whole
    the emitted envelope is 4,147 bytes and the durable EventLog row 4,127, both over 4,096 (by 51 and 31); with the compact
    record they are 2,575 emitted and 2,555 durable. The control (``"approval": None``, whole) is 4,014 emitted and 3,993
    durable: 82 and 103 bytes under the bound, so an envelope that grows by more than 82 bytes compacts it too.
    """
    bound = executor_module._RECORD_MAX_BYTES
    assert bound == 4096  # premise: the real bound
    size = executor_module._record_size
    quotes = '"' * 200  # every character of caller-chosen provenance doubles when escaped into the envelope
    approval = _approved_run()
    record = _largest_record(approval)
    compact = compact_command_policy_record(record)
    assert _admitted(record) == record  # premise: the sink admits this record unchanged (#11)
    assert compact != record and compact["approval"] == approval  # premise: the compact form is smaller and keeps the approval
    assert (compact["matched_rules"], compact["causes"]) == ([], [])

    _, executor, emitted = _recorded(_MaximalRecordTool({"command_policy": record}))
    await _wide_call(executor, quotes)

    assert len(emitted) == 1
    event, payload = emitted[0]
    assert event is EventType.TOOL_INVOKED
    # premises: in this very envelope the whole record is over the bound and the compact one is within it
    emitted_whole = size({**payload, "command_policy": record})
    assert emitted_whole > bound  # measured: 4,147 bytes, 51 over (D5)
    assert size({**payload, "command_policy": compact}) <= bound
    # the emitted envelope is within the bound, with the compact record and the approval the whole record carried
    assert payload["command_policy"] == compact
    assert payload["command_policy"]["approval"] == record["approval"]
    assert size(payload) <= bound  # measured: 2,575 bytes
    assert "params" not in payload or "detail_omitted" not in payload["params"]  # no parameter detail was dropped to make room: only the record was compacted

    # durable: a real EventLog persists the same compact record with its approval, within the same bound
    data = await _durable_data(tmp_path, "events.db", record, quotes)
    durable_whole = size({**data, "command_policy": record})
    assert durable_whole > bound  # premise, on the persisted envelope; measured: 4,127 bytes, 31 over (D5)
    assert size(data) <= bound  # measured: 2,555 bytes
    assert data["command_policy"] == compact
    assert data["command_policy"]["approval"] == record["approval"]

    # control (S2a B31's case at v2): the same record with no approval is kept whole, in both
    whole = {**record, "approval": None}
    assert _admitted(whole) == whole
    _, plain_executor, plain_emitted = _recorded(_MaximalRecordTool({"command_policy": whole}))
    await _wide_call(plain_executor, quotes)
    plain = plain_emitted[0][1]
    assert plain["command_policy"] == whole
    assert plain["command_policy"]["approval"] is None
    assert size(plain) <= bound  # measured: 4,014 bytes whole, 82 under (D5)
    plain_data = await _durable_data(tmp_path, "events-whole.db", whole, quotes)
    assert plain_data["command_policy"] == whole
    assert size(plain_data) <= bound  # measured: 3,993 bytes whole, 103 under (D5)
