"""AD-1328 S2b (#1530), M2: the escalation service -- one ``escalate`` verdict to the chain of command and back.

Tests only. The contract is ``prompts/ad-1328-s2b-command-policy-escalation.md`` ("Tests", M2). The module under test is
``probos.execution.command_escalation``: ``escalation_scope``, ``CommandEscalations`` (``resolve``, ``fulfil_approval``,
``record_denial``), ``command_approval_payload`` and ``build_command_escalations``.

Nothing here starts a shell or reads this host. Every gate is built with ``platform="linux"`` and a ``which`` that finds
nothing; the stores are the real ones on ``tmp_path`` -- ``SqliteCommandApprovalStore`` and
``CapabilityRequestStore(db_path=...)`` -- so a test crosses the whole chain the Captain's decision travels: the ask is filed,
the Captain decides it (``decide``), ``fulfil_approval`` records the approval and fulfils the request, the re-issued command
runs (or reuses), and a work-item end, a policy change, another agent, a denial or a failing store stops it. The work-item
store is a dict-backed stand-in and one clock is injected into the approval store and the service. The router
(``_maybe_fulfil_on_approval``) and the tool (``RunCommandTool``) are the next milestones' seams (M3, M4): here the Captain's
decision is made by calling ``decide`` and then ``fulfil_approval`` / ``record_denial``, exactly as the router does.

Each test asserts its premise (what the gate decided, what the store holds) and a negative control: the accepted neighbour of
every refusal and the refused neighbour of every run, so a test cannot pass because the whole machine refuses (or runs)
everything. The helpers are copies, because tests do not import each other: S1's ``_policy`` / ``_rule`` and S2a's
``_not_a_capability_gap`` (the real ``probos.cognitive.decomposer._CAPABILITY_GAP_RE``).

Mutants of the contract's "Mutation campaign of record" (the orchestrator runs the campaign), and the test that kills each:

* S-E1 ``resolve`` no longer returns early for a non-escalate verdict -> ``test_forbid_never_reaches_approvals``.
* S-E2 an approval is used without asking whether its work item is open -> ``test_scope_end_stops_reuse``.
* S-E3 ``fulfil_approval`` ignores the policy digest -> ``test_fulfil_refuses[other_digest]``,
  ``test_policy_change_escalates_again``.
* S-E4 ``fulfil_approval`` ignores who decided -> ``test_fulfil_refuses[not_captain]``.
* S-E5 a denial is not honoured in its scope -> ``test_denial_sticks_in_its_scope``.
* S-E6 the per-agent inbox cap is not applied -> ``test_inbox_full_files_nothing``.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
import re
import sqlite3
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from probos.capability_request import THREAD_ID_MAX_CHARS, CapabilityRequestStore
from probos.cognitive import decomposer
from probos.config_models.experience import ApprovalInboxConfig
from probos.config_models.operations import CommandPolicyConfig
from probos.execution import command_escalation
from probos.execution.command_approvals import (
    ENDED_WORK_ITEM_STATUSES,
    SqliteCommandApprovalStore,
    command_approval_request,
)
from probos.execution.command_escalation import (
    CommandEscalations,
    EscalationOutcome,
    EscalationScope,
    build_command_escalations,
    command_approval_payload,
    escalation_scope,
)
from probos.execution.command_gate import NO_POLICY, CommandGateVerdict, CommandPolicyGate

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


def _not_a_capability_gap(text: str) -> None:
    """The frames are error-shaped, not a capability gap (AD-1154 DD-2): the real decomposer regex must not fire."""
    assert decomposer._CAPABILITY_GAP_RE.search(text) is None, text


_PUSH = "git push origin main"
_PUSH_OTHER = "git push origin dev"
_PUSH_THIRD = "git push origin release"
_CURL = "curl http://example.invalid/data"
_SENTINEL = "zebrafish-sentinel"
_ASK_PUSH_WHY = "a push publishes work outside this session"
_NO_CURL_WHY = "curl reaches the network outside the governed fetch path"
_NO_CURL_INSTEAD = "use the fetch_url tool"
_SEARCH_PATH = "/usr/bin"
_HEX32 = re.compile(r"[0-9a-f]{32}")
_WORK_ITEM_LIFETIME = 7 * 86400
_SINGLE_USE_LIFETIME = 3600
_BROWSER_ACTION: dict[str, Any] = {
    "tool_id": "browser", "action": "navigate", "params": {"url": "http://example.invalid/"},
    "scope_key": "", "session_id": None, "thread_id": "",
}

_FILED_PREFIX = (
    "The command policy requires the Captain's approval before this command runs. It was filed for review as request "
)
_INBOX_FULL_HEAD = (
    "The command policy requires the Captain's approval before this command runs. Too many of your requests are already "
    "awaiting review, so it was refused rather than filed, and it was not run. "
)
_UNFILED_HEAD = (
    "The command policy requires the Captain's approval before this command runs. Filing it for review failed, so it was "
    "not run. "
)


def _filed_head(request_id: str) -> str:
    return f"{_FILED_PREFIX}{request_id} and was not run. "


def _denied_head(request_id: str) -> str:
    return f"The Captain denied this command for this work (request {request_id}), so it was not run. "


class _Which:
    """A ``which`` that finds nothing and never reads this host's PATH."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, name: str, path: str | None = None) -> str | None:
        self.calls.append((name, path))
        return None


def _gate(config: CommandPolicyConfig) -> CommandPolicyGate:
    return CommandPolicyGate(config, platform="linux", which=_Which(), is_file=lambda path: False)


def _ask_push() -> dict:
    return _rule("ask-push", ["git", "push"], "escalate", justification=_ASK_PUSH_WHY)


def _no_curl() -> dict:
    return _rule("no-curl", ["curl"], "forbid", justification=_NO_CURL_WHY, alternative=_NO_CURL_INSTEAD)


def _escalate_gate(*extra: dict, unmatched: str = "allow") -> CommandPolicyGate:
    """``git push`` escalates, with a justification; what no rule covers is allowed (``unmatched_decision="allow"``)."""
    return _gate(_policy(_ask_push(), *extra, unmatched=unmatched))


def _forbid_gate() -> CommandPolicyGate:
    """``curl`` is forbidden, with an alternative."""
    return _gate(_policy(_no_curl()))


def _stack_gate() -> CommandPolicyGate:
    """``curl`` is forbidden and ``git push`` escalates: a line holding both is forbidden (the strictest rule wins)."""
    return _gate(_policy(_no_curl(), _ask_push()))


def _worst_case_gate() -> CommandPolicyGate:
    """Six escalate rules with 64-character names, 300-character justifications and 300-character alternatives."""
    rules = [
        _rule(f"r{index}-" + "n" * 61, [f"cmd{index}"], "escalate", justification="j" * 300, alternative="a" * 300)
        for index in range(6)
    ]
    return _gate(_policy(*rules))


def _ctx(agent: str = "agent-1", *, item: str | None = "W1", thread: str | None = "thr-1") -> dict[str, Any]:
    """The invocation context ``ToolRegistry.check_and_invoke`` builds: the agent, a crew work item, a thread."""
    context: dict[str, Any] = {"agent_id": agent}
    if item is not None:
        context["_crew_work_item_id"] = item
    if thread is not None:
        context["thread_id"] = thread
    return context


class _Clock:
    """One settable clock for the approval store and the service (the request store stamps with the real time)."""

    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _WorkItems:
    """A dict-backed work-item store: ``get_work_item(id)`` answers ``SimpleNamespace(status=...)`` or None."""

    def __init__(self, statuses: dict[str, str]) -> None:
        self.statuses: dict[str, str] = dict(statuses)
        self.reads: list[str] = []
        self.fail = False

    async def get_work_item(self, work_item_id: str) -> SimpleNamespace | None:
        self.reads.append(work_item_id)
        if self.fail:
            raise RuntimeError("the work item store is down")
        status = self.statuses.get(work_item_id)
        return None if status is None else SimpleNamespace(status=status)


class _Spy:
    """Records every call to a real async method and delegates to it."""

    def __init__(self, target: Callable[..., Awaitable[Any]]) -> None:
        self.target = target
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        return await self.target(*args, **kwargs)


def _spy(monkeypatch: pytest.MonkeyPatch, owner: object, name: str) -> _Spy:
    spy = _Spy(getattr(owner, name))
    monkeypatch.setattr(owner, name, spy)
    return spy


async def _aboom(*args: object, **kwargs: object) -> object:
    raise RuntimeError("injected failure")


def _boom(*args: object, **kwargs: object) -> object:
    raise RuntimeError("injected failure")


async def _none(*args: object, **kwargs: object) -> None:
    return None


@dataclasses.dataclass
class _Rig:
    clock: _Clock
    approvals: SqliteCommandApprovalStore
    requests: CapabilityRequestStore
    work_items: _WorkItems
    approvals_db: str
    requests_db: str
    gate: CommandPolicyGate
    service: CommandEscalations

    def judge(self, command: str, gate: CommandPolicyGate | None = None) -> CommandGateVerdict:
        return (gate or self.gate).judge(command, site="run_command_tool", search_path=_SEARCH_PATH)

    def service_for(self, gate: CommandPolicyGate, **kwargs: Any) -> CommandEscalations:
        """Another service over the same two stores (another policy, cap or work-item store)."""
        kwargs.setdefault("work_items", self.work_items)
        return CommandEscalations(
            gate=gate, approvals=self.approvals, requests=self.requests, clock=self.clock, **kwargs,
        )


@pytest_asyncio.fixture
async def rig(tmp_path: Path) -> AsyncIterator[_Rig]:
    clock = _Clock()
    approvals_db = str(tmp_path / "command_approvals.db")
    requests_db = str(tmp_path / "capability_requests.db")
    approvals = SqliteCommandApprovalStore(approvals_db, clock=clock)
    requests = CapabilityRequestStore(db_path=requests_db)
    work_items = _WorkItems({"W1": "in_progress", "W2": "in_progress"})
    await approvals.start()
    try:
        await requests.start()
        try:
            gate = _escalate_gate()
            service = CommandEscalations(
                gate=gate, approvals=approvals, requests=requests, work_items=work_items, clock=clock,
            )
            yield _Rig(clock, approvals, requests, work_items, approvals_db, requests_db, gate, service)
        finally:
            await requests.stop()
    finally:
        await approvals.stop()


def _request_rows(rig: _Rig) -> int:
    """Rows in the request table on disk: what was durably filed, not what a cache holds."""
    with closing(sqlite3.connect(rig.requests_db)) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM capability_requests").fetchone()[0])


def _state(outcome: EscalationOutcome) -> str:
    assert outcome.verdict.approval is not None
    return outcome.verdict.approval["state"]


def _rid(outcome: EscalationOutcome) -> str:
    assert outcome.verdict.approval is not None
    request_id = outcome.verdict.approval["request_id"]
    assert isinstance(request_id, str) and request_id
    return request_id


async def _resolve(
    rig: _Rig, command: str, context: object, *, service: CommandEscalations | None = None,
    gate: CommandPolicyGate | None = None,
) -> tuple[CommandGateVerdict, EscalationOutcome]:
    verdict = rig.judge(command, gate)
    outcome = await (service or rig.service).resolve(verdict, command=command, context=context)
    return verdict, outcome


async def _approve(rig: _Rig, request_id: str, *, service: CommandEscalations | None = None) -> tuple[Any, Any]:
    """The Captain approves, then the router's second step: ``fulfil_approval`` on the decided request."""
    decided = await rig.requests.decide(request_id, True, decided_by="captain")
    assert decided is not None and decided.status == "approved"
    return decided, await (service or rig.service).fulfil_approval(rig.requests, decided)


# --------------------------------------------------------------------------------------
# 1. The scope of a call
# --------------------------------------------------------------------------------------

_LONG_ITEM = "x" * 129  # one character past the work-item id grammar's 128


@pytest.mark.parametrize(
    ("pairs", "control"),
    [
        pytest.param(
            [
                ({"agent_id": "a1", "_crew_work_item_id": "W1", "thread_id": "thr-1"},
                 EscalationScope("a1", "work_item:W1", "W1", "thr-1")),
                ({"agent_id": "a1", "_crew_work_item_id": "W1"}, EscalationScope("a1", "work_item:W1", "W1", "")),
            ],
            ({"agent_id": "a1", "thread_id": "thr-1"}, EscalationScope("a1", "thread:thr-1", None, "thr-1")),
            id="crew_item",
        ),
        pytest.param(
            [({"agent_id": "a1", "thread_id": "thr-1"}, EscalationScope("a1", "thread:thr-1", None, "thr-1"))],
            ({"agent_id": "a1"}, EscalationScope("a1", "", None, "")),
            id="thread_only",
        ),
        pytest.param(
            [
                ({"agent_id": "a1"}, EscalationScope("a1", "", None, "")),
                ({"agent_id": "a1", "thread_id": ""}, EscalationScope("a1", "", None, "")),
                ({"agent_id": "a1", "thread_id": 7, "_crew_work_item_id": 7}, EscalationScope("a1", "", None, "")),
            ],
            ({"agent_id": "a1", "thread_id": "x"}, EscalationScope("a1", "thread:x", None, "x")),
            id="neither",
        ),
        pytest.param(
            [
                ({}, None),
                ({"thread_id": "thr-1", "_crew_work_item_id": "W1"}, None),
                ({"agent_id": ""}, None),
                ({"agent_id": "   "}, None),
                ({"agent_id": 7}, None),
                ({"agent_id": "a" * 129}, None),
                (None, None),
                ("a1", None),
                ([("agent_id", "a1")], None),
                (type("_DictSubclass", (dict,), {})(agent_id="a1"), None),
            ],
            ({"agent_id": "a" * 128}, EscalationScope("a" * 128, "", None, "")),
            id="no_agent",
        ),
        pytest.param(
            [
                ({"agent_id": "a1", "_crew_work_item_id": bad, "thread_id": "thr-1"},
                 EscalationScope("a1", "thread:thr-1", None, "thr-1"))
                for bad in ("", "has space", "-leading", "a/b", _LONG_ITEM)
            ]
            + [({"agent_id": "a1", "_crew_work_item_id": "bad id"}, EscalationScope("a1", "", None, ""))],
            (
                {"agent_id": "a1", "_crew_work_item_id": "W-1.a:b_c", "thread_id": "thr-1"},
                EscalationScope("a1", "work_item:W-1.a:b_c", "W-1.a:b_c", "thr-1"),
            ),
            id="bad_item_id",
        ),
        pytest.param(
            [
                ({"agent_id": "a1", "thread_id": "t" * 65}, EscalationScope("a1", "", None, "")),
                ({"agent_id": "a1", "_crew_work_item_id": "W1", "thread_id": "t" * 65},
                 EscalationScope("a1", "work_item:W1", "W1", "")),
            ],
            (
                {"agent_id": "a1", "thread_id": "t" * 64},
                EscalationScope("a1", "thread:" + "t" * 64, None, "t" * 64),
            ),
            id="long_thread",
        ),
    ],
)
def test_escalation_scope(pairs: list[tuple[object, EscalationScope | None]], control: tuple[object, Any]) -> None:
    control_context, control_scope = control
    assert THREAD_ID_MAX_CHARS == 64  # premise: the bound the long_thread case sits one past
    for context, expected in pairs:
        assert expected != control_scope  # premise: the control is a different answer
        assert escalation_scope(context) == expected, context
    assert escalation_scope(control_context) == control_scope  # negative control: the neighbour that is accepted


# --------------------------------------------------------------------------------------
# 2. Filing
# --------------------------------------------------------------------------------------


async def test_files_the_escalation_with_its_causes(rig: _Rig) -> None:
    command = f"git push origin {_SENTINEL}"
    context = _ctx(item="W1", thread="thr-1")
    verdict = rig.judge(command)
    assert verdict.decision == "escalate" and verdict.runs is False  # premise: an escalate verdict, nothing runs
    assert verdict.approval is None and verdict.record is not None and verdict.record["approval"] is None
    assert await rig.requests.list_pending() == []

    outcome = await rig.service.resolve(verdict, command=command, context=context)

    pending = await rig.requests.list_pending()
    assert len(pending) == 1
    request = pending[0]
    message = outcome.message
    assert message is not None
    assert message.startswith(_filed_head(request.id))  # the filed frame, naming the request, and that it was not run
    assert f"Rule 'ask-push': {_ASK_PUSH_WHY}." in message  # the rule's justification
    assert "Do not repeat this call now" in message
    assert "running the same command again in this task runs it" in message
    assert "within an hour" not in message
    _not_a_capability_gap(message)

    assert request.kind == "action" and request.agent_id == "agent-1" and request.work_item_id == "W1"
    assert "ask-push" in request.rationale
    payload = request.payload
    assert payload is not None
    assert (payload["tool_id"], payload["action"]) == ("run_command", "execute")
    assert payload["scope_key"] == "work_item:W1" and payload["thread_id"] == "thr-1" and payload["session_id"] is None
    params = payload["params"]
    assert params["command"] == command and params["command_chars"] == len(command)
    assert params["canonical_key"] == verdict.canonical.key
    assert params["canonical_kind"] == verdict.canonical.kind
    assert params["policy_digest"] == rig.gate.digest == verdict.evaluation.policy_digest
    assert params["dialect"] == "posix" and params["call_site"] == "run_command_tool"
    assert params["rules"] == ["ask-push"]
    assert params["causes"] == [{"kind": "rule", "rule": "ask-push", "text": _ASK_PUSH_WHY, "alternative": None}]
    assert params["causes_omitted"] == 0

    assert outcome.verdict is not verdict and verdict.approval is None  # the judged verdict is left as judged
    assert outcome.verdict.runs is False and outcome.verdict.denial_reason == "command_policy_escalate"
    assert outcome.verdict.record["approval"] == {"state": "filed", "request_id": request.id, "use_id": None}
    encoded = json.dumps(outcome.verdict.record)
    assert _SENTINEL not in encoded and _ASK_PUSH_WHY not in encoded  # the record carries no command text
    assert _SENTINEL in json.dumps(payload)  # negative control: the command text lives in the request the Captain reads

    again = await rig.service.resolve(verdict, command=command, context=context)  # a repeat folds into the pending ask
    assert again.verdict.approval == {"state": "filed", "request_id": request.id, "use_id": None}
    assert [r.id for r in await rig.requests.list_pending()] == [request.id] and _request_rows(rig) == 1

    _, other = await _resolve(rig, _PUSH_OTHER, context)  # negative control: another command is another ask
    assert _rid(other) != request.id and _request_rows(rig) == 2


async def test_an_escalation_no_rule_decided_names_the_reason(rig: _Rig) -> None:
    gate = _escalate_gate(unmatched="escalate")
    service = rig.service_for(gate)

    verdict, outcome = await _resolve(rig, "make all", _ctx(), service=service, gate=gate)

    assert verdict.decision == "escalate" and verdict.record["matched_rules"] == []  # premise: no rule decided it
    reason = "no rule covers 'make', and commands no rule covers are set to escalate"
    request = (await rig.requests.list_pending())[0]
    params = request.payload["params"]
    assert params["rules"] == []
    assert params["causes"] == [{"kind": "unmatched", "rule": None, "text": reason, "alternative": None}]
    assert outcome.message is not None
    assert "No rule covers 'make', and commands no rule covers are set to escalate." in outcome.message
    _not_a_capability_gap(outcome.message)
    assert request.rationale == "AD-1328 command policy escalation (unmatched)"

    _, ruled = await _resolve(rig, _PUSH, _ctx(), service=service, gate=gate)  # negative control: a rule names itself
    ruled_request = await rig.requests.get(_rid(ruled))
    assert ruled_request.payload["params"]["rules"] == ["ask-push"]
    assert ruled_request.payload["params"]["causes"][0]["text"] == _ASK_PUSH_WHY
    assert ruled_request.rationale == "AD-1328 command policy escalation (ask-push)"


# --------------------------------------------------------------------------------------
# 3. forbid never reaches the approvals
# --------------------------------------------------------------------------------------


async def test_forbid_never_reaches_approvals(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``forbid`` is refused with the gate's own message; the approval store and the request store are never asked.

    Kills S-E1 (``resolve`` without the ``decision != "escalate"`` guard would look the command up and file it).
    """
    stack = _stack_gate()
    service = rig.service_for(stack)
    find = _spy(monkeypatch, rig.approvals, "find")
    file_action = _spy(monkeypatch, rig.requests, "file_action_request")
    context = _ctx()

    for gate, command in ((_forbid_gate(), _CURL), (stack, f"{_CURL} && {_PUSH}")):
        verdict = rig.judge(command, gate)
        assert verdict.decision == "forbid" and verdict.runs is False  # premise: forbidden (the mixed line too)
        assert verdict.refusal_message is not None and _NO_CURL_INSTEAD in verdict.refusal_message
        outcome = await service.resolve(verdict, command=command, context=context)
        assert outcome.message == verdict.refusal_message
        assert outcome.verdict is verdict and verdict.approval is None
    assert find.calls == [] and file_action.calls == []
    assert _request_rows(rig) == 0

    allowed = rig.judge("git status", stack)  # negative control: what is not refused is handed back as it is
    assert allowed.decision == "allow" and allowed.runs is True
    for verdict in (allowed, NO_POLICY):
        outcome = await service.resolve(verdict, command="git status", context=context)
        assert outcome.message is None and outcome.verdict is verdict
    assert find.calls == [] and file_action.calls == []

    escalate = rig.judge(_PUSH, stack)  # negative control: an escalate verdict does reach both stores
    assert escalate.decision == "escalate"
    outcome = await service.resolve(escalate, command=_PUSH, context=context)
    assert [kwargs["state"] for _, kwargs in find.calls] == ["active", "denied"]
    assert len(file_action.calls) == 1 and _state(outcome) == "filed" and _request_rows(rig) == 1


# --------------------------------------------------------------------------------------
# 4-5. Approval, run, reuse
# --------------------------------------------------------------------------------------


async def test_approval_then_run_then_reuse_in_one_work_item(rig: _Rig) -> None:
    context = _ctx(item="W1")
    verdict, filed = await _resolve(rig, _PUSH, context)
    request_id = _rid(filed)
    assert filed.message is not None and filed.verdict.runs is False  # premise: nothing runs before the Captain decides
    assert await rig.approvals.get(request_id) is None

    decided = await rig.requests.decide(request_id, True, decided_by="captain")
    assert decided is not None and decided.status == "approved"
    assert await rig.approvals.get(request_id) is None  # deciding alone records nothing: fulfil_approval does
    fulfilled = await rig.service.fulfil_approval(rig.requests, decided)
    assert fulfilled is not None and fulfilled.id == request_id and fulfilled.status == "fulfilled"
    assert (await rig.requests.get(request_id, durable=True)).status == "fulfilled"
    row = await rig.approvals.get(request_id)
    assert (row.state, row.agent_id, row.scope_key, row.approver, row.uses) == (
        "active", "agent-1", "work_item:W1", "captain", 0,
    )

    first = await rig.service.resolve(verdict, command=_PUSH, context=context)
    assert first.message is None and first.verdict.runs is True
    assert first.verdict.refusal_message is None and first.verdict.denial_reason == ""
    assert first.verdict.decision == "escalate"  # the verdict is still an escalation: an approval admitted it
    assert verdict.runs is False  # the verdict as judged is not turned into a run
    first_approval = first.verdict.approval
    assert first_approval["state"] == "approved_run" and first_approval["request_id"] == request_id
    assert _HEX32.fullmatch(first_approval["use_id"])
    assert first.verdict.record["approval"] == first_approval

    second = await rig.service.resolve(verdict, command=_PUSH, context=context)
    assert second.message is None and second.verdict.runs is True
    second_approval = second.verdict.approval
    assert second_approval["state"] == "reuse" and second_approval["request_id"] == request_id
    assert _HEX32.fullmatch(second_approval["use_id"]) and second_approval["use_id"] != first_approval["use_id"]

    uses = await rig.approvals.list_uses(request_id)
    assert [(use.use_kind, use.request_id) for use in uses] == [("approved_run", request_id), ("reuse", request_id)]
    assert [use.use_id for use in uses] == [first_approval["use_id"], second_approval["use_id"]]
    assert (await rig.approvals.get(request_id)).uses == 2
    assert rig.work_items.reads and set(rig.work_items.reads) == {"W1"}  # a work-item scope asks whether its item is open

    _, other = await _resolve(rig, _PUSH_OTHER, context)  # negative control: the approval is for this command only
    assert other.message is not None and _state(other) == "filed" and _rid(other) != request_id
    assert (await rig.approvals.get(request_id)).uses == 2


@pytest.mark.parametrize(
    ("thread", "scope_key", "where"),
    [
        pytest.param("thr-1", "thread:thr-1", "in this conversation ", id="thread"),
        pytest.param(None, "", "", id="none"),
    ],
)
async def test_single_use_outside_a_work_item(rig: _Rig, thread: str | None, scope_key: str, where: str) -> None:
    context = _ctx(item=None, thread=thread)
    verdict, filed = await _resolve(rig, _PUSH, context)
    first_id = _rid(filed)
    assert filed.message is not None and filed.message.startswith(_filed_head(first_id))  # premise: filed, not run
    assert f"running the same command again {where}within an hour runs it once" in filed.message
    assert "in this task" not in filed.message
    assert ("in this conversation" in filed.message) == bool(thread)
    _not_a_capability_gap(filed.message)

    await _approve(rig, first_id)
    assert (await rig.approvals.get(first_id)).scope_key == scope_key
    run = await rig.service.resolve(verdict, command=_PUSH, context=context)
    assert run.message is None and _state(run) == "approved_run" and _rid(run) == first_id

    again = await rig.service.resolve(verdict, command=_PUSH, context=context)  # the same approval does not run it twice
    assert again.message is not None and again.verdict.runs is False and _state(again) == "filed"
    second_id = _rid(again)
    assert second_id != first_id  # a new request, not the fulfilled one
    assert (await rig.approvals.get(first_id)).uses == 1 and len(await rig.approvals.list_uses(first_id)) == 1
    assert await rig.approvals.find("agent-1", scope_key, verdict.canonical.key, rig.gate.digest, state="active") is None
    assert [request.id for request in await rig.requests.list_pending()] == [second_id]
    assert rig.work_items.reads == []  # a thread or no scope ends by time alone: the work-item store is never asked

    await _approve(rig, second_id)  # negative control: each approval admits one run of its own
    again_run = await rig.service.resolve(verdict, command=_PUSH, context=context)
    assert again_run.message is None and _state(again_run) == "approved_run" and _rid(again_run) == second_id


# --------------------------------------------------------------------------------------
# 6. fulfil_approval refuses
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case", ["not_captain", "other_digest", "item_ended", "not_approved", "not_a_command_request"],
)
async def test_fulfil_refuses(rig: _Rig, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    """``fulfil_approval`` returns None, records no row and fulfils nothing; once the cause is fixed a retry works.

    Kills S-E3 (the policy-digest check; ``other_digest``) and S-E4 (the Captain check; ``not_captain``).
    """
    context = _ctx(item="W1")
    _, filed = await _resolve(rig, _PUSH, context)
    request_id = _rid(filed)
    mark = _spy(monkeypatch, rig.requests, "mark_fulfilled")
    refusing = rig.service
    refused: list[Any] = []
    status_left = "approved"

    async def captain_decides_again() -> tuple[Any, CommandEscalations]:
        return await rig.requests.decide(request_id, True, decided_by="captain"), rig.service

    retry: Callable[[], Awaitable[tuple[Any, CommandEscalations]]] = captain_decides_again
    if case == "not_captain":
        refused.append(await rig.requests.decide(request_id, True, decided_by="first_officer"))
    elif case == "other_digest":
        other_gate = _escalate_gate(_rule("ask-rebase", ["git", "rebase"], "escalate", justification="a rebase rewrites"))
        assert other_gate.digest != rig.gate.digest  # premise: the running policy is not the one the ask was filed under
        refusing = rig.service_for(other_gate)
        refused.append(await rig.requests.decide(request_id, True, decided_by="captain"))
        decided = refused[0]

        async def policy_is_back() -> tuple[Any, CommandEscalations]:  # the filing policy is the running one again
            return decided, rig.service

        retry = policy_is_back
    elif case == "item_ended":
        rig.work_items.statuses["W1"] = "done"
        refused.append(await rig.requests.decide(request_id, True, decided_by="captain"))

        async def item_reopened() -> tuple[Any, CommandEscalations]:
            rig.work_items.statuses["W1"] = "in_progress"
            return await rig.requests.decide(request_id, True, decided_by="captain"), rig.service

        retry = item_reopened
    elif case == "not_approved":
        status_left = "pending"
        refused.append(await rig.requests.get(request_id))
        assert refused[0].status == "pending"
    else:  # not_a_command_request: approved requests that are not this command's escalation
        status_left = "pending"
        grant = await rig.requests.file_request("agent-1", "grant", "some_clearance")
        refused.append(await rig.requests.decide(grant.id, True, decided_by="captain"))
        browser = await rig.requests.file_action_request("agent-1", copy.deepcopy(_BROWSER_ACTION))
        assert browser is not None
        refused.append(await rig.requests.decide(browser.id, True, decided_by="captain"))
        assert all(request.status == "approved" for request in refused)  # premise: approved, just not command escalations

    for request in refused:
        assert await refusing.fulfil_approval(rig.requests, request) is None, case
        assert await rig.approvals.get(request.id) is None  # no row
    assert mark.calls == []  # nothing was fulfilled
    assert (await rig.requests.get(request_id, durable=True)).status == status_left  # left as decided: the Captain can retry

    decided_again, service = await retry()  # negative control (BF-722): the retry works once the cause is fixed
    fulfilled = await service.fulfil_approval(rig.requests, decided_again)
    assert fulfilled is not None and fulfilled.status == "fulfilled"
    assert [args for args, _ in mark.calls] == [(request_id,)]
    row = await rig.approvals.get(request_id)
    assert row is not None and row.state == "active" and row.approver == "captain"


# --------------------------------------------------------------------------------------
# 7. The scope ends
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("ended", ["done", "cancelled", "failed"])
async def test_scope_end_stops_reuse(rig: _Rig, ended: str) -> None:
    """An approval granted in a work item stops admitting runs when that item ends.

    Kills S-E2 (an approval used without asking whether its work item is still open).
    """
    assert ended in ENDED_WORK_ITEM_STATUSES  # premise
    context = _ctx(item="W1")
    verdict, filed = await _resolve(rig, _PUSH, context)
    request_id = _rid(filed)
    await _approve(rig, request_id)
    first = await rig.service.resolve(verdict, command=_PUSH, context=context)
    second = await rig.service.resolve(verdict, command=_PUSH, context=context)
    assert (_state(first), _state(second)) == ("approved_run", "reuse")  # premise: while W1 is open the approval admits
    assert first.message is None and second.message is None

    rig.work_items.statuses["W1"] = ended
    after = await rig.service.resolve(verdict, command=_PUSH, context=context)

    assert after.message is not None and after.verdict.runs is False and _state(after) == "filed"
    new_id = _rid(after)
    assert new_id != request_id
    assert [request.id for request in await rig.requests.list_pending()] == [new_id]  # a new ask, nothing ran
    assert (await rig.approvals.get(request_id)).uses == 2 and len(await rig.approvals.list_uses(request_id)) == 2
    _not_a_capability_gap(after.message)


@pytest.mark.parametrize("failure", ["item_unknown", "read_raises", "no_work_item_store"])
async def test_a_work_item_scope_fails_closed(rig: _Rig, failure: str) -> None:
    context = _ctx(item="W1")
    verdict, filed = await _resolve(rig, _PUSH, context)
    request_id = _rid(filed)
    await _approve(rig, request_id)
    ran = await rig.service.resolve(verdict, command=_PUSH, context=context)
    assert ran.message is None and _state(ran) == "approved_run"  # premise: the approval admits while W1 can be read

    service = rig.service
    if failure == "item_unknown":
        del rig.work_items.statuses["W1"]
    elif failure == "read_raises":
        rig.work_items.fail = True
    else:
        service = rig.service_for(rig.gate, work_items=None)
    outcome = await service.resolve(verdict, command=_PUSH, context=context)

    assert outcome.message is not None and outcome.verdict.runs is False and _state(outcome) == "filed"
    assert (await rig.approvals.get(request_id)).uses == 1  # nothing more was admitted
    decided = await rig.requests.decide(_rid(outcome), True, decided_by="captain")
    assert await service.fulfil_approval(rig.requests, decided) is None  # and nothing is granted while it cannot be read
    assert await rig.approvals.get(decided.id) is None
    if failure == "no_work_item_store":  # negative control: a thread scope needs no work item
        thread_context = _ctx(item=None)
        thread_verdict, thread_filed = await _resolve(rig, _PUSH_OTHER, thread_context, service=service)
        await _approve(rig, _rid(thread_filed), service=service)
        thread_run = await service.resolve(thread_verdict, command=_PUSH_OTHER, context=thread_context)
        assert thread_run.message is None and _state(thread_run) == "approved_run"


@pytest.mark.parametrize(
    ("item", "thread", "elapsed", "runs"),
    [
        pytest.param("W1", "thr-1", _SINGLE_USE_LIFETIME + 1, True, id="work_item_outlives_an_hour"),
        pytest.param("W1", "thr-1", _WORK_ITEM_LIFETIME + 1, False, id="work_item_ends_after_seven_days"),
        pytest.param(None, "thr-1", _SINGLE_USE_LIFETIME - 1, True, id="thread_inside_an_hour"),
        pytest.param(None, "thr-1", _SINGLE_USE_LIFETIME + 1, False, id="thread_past_an_hour"),
        pytest.param(None, None, _SINGLE_USE_LIFETIME + 1, False, id="none_past_an_hour"),
    ],
)
async def test_an_approval_lives_as_long_as_its_scope_allows(
    rig: _Rig, item: str | None, thread: str | None, elapsed: float, runs: bool,
) -> None:
    context = _ctx(item=item, thread=thread)
    verdict, filed = await _resolve(rig, _PUSH, context)
    request_id = _rid(filed)
    await _approve(rig, request_id)
    row = await rig.approvals.get(request_id)
    assert row.expires_at - row.decided_at == pytest.approx(_WORK_ITEM_LIFETIME if item else _SINGLE_USE_LIFETIME)

    rig.clock.advance(elapsed)
    outcome = await rig.service.resolve(verdict, command=_PUSH, context=context)

    assert (outcome.message is None) is runs
    assert _state(outcome) == ("approved_run" if runs else "filed")
    if not runs:
        assert outcome.verdict.runs is False and (await rig.approvals.get(request_id)).uses == 0


# --------------------------------------------------------------------------------------
# 8-9. Another policy, another agent, another scope
# --------------------------------------------------------------------------------------


async def test_policy_change_escalates_again(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """An approval holds for the policy it was filed under only.

    Kills S-E3 (``fulfil_approval`` that ignores the policy digest would record gate A's request under gate B).
    """
    gate_a = rig.gate
    gate_b = _escalate_gate(_rule("ask-rebase", ["git", "rebase"], "escalate", justification="a rebase rewrites history"))
    assert gate_a.digest and gate_b.digest and gate_a.digest != gate_b.digest  # premise: one more rule, another digest
    service_b = rig.service_for(gate_b)
    context = _ctx(item="W1")

    verdict_a, filed = await _resolve(rig, _PUSH, context)
    old_id = _rid(filed)
    decided_old, fulfilled = await _approve(rig, old_id)
    assert fulfilled is not None and fulfilled.status == "fulfilled"
    run = await rig.service.resolve(verdict_a, command=_PUSH, context=context)
    assert run.message is None and _state(run) == "approved_run"  # premise: the approval is good under policy A

    verdict_b = rig.judge(_PUSH, gate_b)
    assert verdict_b.canonical.key == verdict_a.canonical.key  # the same command...
    assert verdict_b.evaluation.policy_digest == gate_b.digest != verdict_a.evaluation.policy_digest  # ...under another policy
    under_b = await service_b.resolve(verdict_b, command=_PUSH, context=context)
    assert under_b.message is not None and under_b.verdict.runs is False and _state(under_b) == "filed"
    new_id = _rid(under_b)
    assert new_id != old_id and (await rig.approvals.get(old_id)).uses == 1  # the old approval admitted nothing under B
    assert [request.id for request in await rig.requests.list_pending()] == [new_id]

    mark = _spy(monkeypatch, rig.requests, "mark_fulfilled")
    assert await service_b.fulfil_approval(rig.requests, decided_old) is None  # B will not record A's request
    assert mark.calls == []

    decided_new, fulfilled_new = await _approve(rig, new_id, service=service_b)  # negative control: B's own ask works under B
    assert fulfilled_new is not None and fulfilled_new.status == "fulfilled"
    assert (await rig.approvals.get(new_id)).policy_digest == gate_b.digest
    under_b_again = await service_b.resolve(verdict_b, command=_PUSH, context=context)
    assert under_b_again.message is None and _state(under_b_again) == "approved_run" and _rid(under_b_again) == new_id


async def test_other_agent_never_uses_the_approval(rig: _Rig) -> None:
    verdict, filed = await _resolve(rig, _PUSH, _ctx("agent-1"))
    request_id = _rid(filed)
    await _approve(rig, request_id)
    row = await rig.approvals.get(request_id)
    assert (row.state, row.agent_id, row.uses) == ("active", "agent-1", 0)  # premise: agent-1 holds an active approval

    other = await rig.service.resolve(verdict, command=_PUSH, context=_ctx("agent-2"))  # same command, same work item

    assert other.message is not None and other.verdict.runs is False and _state(other) == "filed"
    other_id = _rid(other)
    assert other_id != request_id and (await rig.requests.get(other_id)).agent_id == "agent-2"
    assert (await rig.approvals.get(request_id)).uses == 0 and await rig.approvals.list_uses(request_id) == []
    assert await rig.approvals.get(other_id) is None  # agent-2 has no approval of its own

    mine = await rig.service.resolve(verdict, command=_PUSH, context=_ctx("agent-1"))  # negative control: the owner runs
    assert mine.message is None and _state(mine) == "approved_run" and _rid(mine) == request_id


async def test_other_scope_never_uses_the_approval(rig: _Rig) -> None:
    verdict, filed = await _resolve(rig, _PUSH, _ctx(item="W1", thread="thr-1"))
    request_id = _rid(filed)
    await _approve(rig, request_id)
    assert (await rig.approvals.get(request_id)).scope_key == "work_item:W1"  # premise

    elsewhere = (_ctx(item="W2", thread="thr-1"), _ctx(item=None, thread="thr-1"), _ctx(item=None, thread=None))
    seen = {request_id}
    for context in elsewhere:
        outcome = await rig.service.resolve(verdict, command=_PUSH, context=context)
        assert outcome.message is not None and outcome.verdict.runs is False and _state(outcome) == "filed", context
        assert _rid(outcome) not in seen  # each other scope files an ask of its own
        seen.add(_rid(outcome))
    assert (await rig.approvals.get(request_id)).uses == 0

    mine = await rig.service.resolve(verdict, command=_PUSH, context=_ctx(item="W1", thread="thr-1"))  # negative control
    assert mine.message is None and _state(mine) == "approved_run" and _rid(mine) == request_id


# --------------------------------------------------------------------------------------
# 10. Denial
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("item", "thread", "scope_key", "elsewhere"),
    [
        pytest.param("W1", "thr-1", "work_item:W1", {"item": "W2", "thread": "thr-1"}, id="work_item"),
        pytest.param(None, "thr-1", "thread:thr-1", {"item": None, "thread": "thr-2"}, id="thread"),
    ],
)
async def test_denial_sticks_in_its_scope(
    rig: _Rig, item: str | None, thread: str | None, scope_key: str, elsewhere: dict[str, Any],
) -> None:
    """A recorded denial is refused again in its scope without filing; it follows neither another scope nor another command.

    Kills S-E5 (a denial not honoured would file the command again).
    """
    context = _ctx(item=item, thread=thread)
    verdict, filed = await _resolve(rig, _PUSH, context)
    request_id = _rid(filed)
    denied = await rig.requests.decide(request_id, False, reason="not for this work", decided_by="captain")
    assert denied is not None and denied.status == "denied"  # premise
    assert await rig.approvals.get(request_id) is None  # nothing is recorded until the router's second step
    assert await rig.service.record_denial(denied) is True
    row = await rig.approvals.get(request_id)
    assert (row.state, row.scope_key, row.agent_id, row.approver) == ("denied", scope_key, "agent-1", "captain")
    rows = _request_rows(rig)
    assert rows == 1 and await rig.requests.list_pending() == []

    outcome = await rig.service.resolve(verdict, command=_PUSH, context=context)

    assert outcome.message is not None and outcome.message.startswith(_denied_head(request_id))
    assert f"Rule 'ask-push': {_ASK_PUSH_WHY}." in outcome.message
    _not_a_capability_gap(outcome.message)
    assert outcome.verdict.approval == {"state": "denied", "request_id": request_id, "use_id": None}
    assert outcome.verdict.runs is False
    assert _request_rows(rig) == rows and await rig.requests.list_pending() == []  # nothing was filed again
    assert await rig.approvals.find("agent-1", scope_key, verdict.canonical.key, rig.gate.digest, state="active") is None

    other_scope = await rig.service.resolve(verdict, command=_PUSH, context=_ctx(**elsewhere))  # negative controls
    assert _state(other_scope) == "filed" and _rid(other_scope) != request_id  # the denial is for this scope only
    other_command = await rig.service.resolve(rig.judge(_PUSH_OTHER), command=_PUSH_OTHER, context=context)
    assert _state(other_command) == "filed"  # and for this command only


async def test_a_denial_outside_a_scope_is_not_recorded(rig: _Rig) -> None:
    """M2 #10, second half: outside a scope ``record_denial`` is False and the next ``resolve`` files again."""
    context = _ctx(item=None, thread=None)
    verdict, filed = await _resolve(rig, _PUSH, context)
    request_id = _rid(filed)
    denied = await rig.requests.decide(request_id, False, decided_by="captain")
    assert denied.status == "denied" and command_approval_request(denied).scope_key == ""  # premise: no scope to stick in

    assert await rig.service.record_denial(denied) is False
    assert await rig.approvals.get(request_id) is None

    again = await rig.service.resolve(verdict, command=_PUSH, context=context)  # nothing sticks: the next call files
    assert again.message is not None and _state(again) == "filed" and _rid(again) != request_id
    assert _request_rows(rig) == 2

    scoped_verdict, scoped_filed = await _resolve(rig, _PUSH, _ctx(item="W1"))  # negative control: in a scope it is recorded
    scoped_denied = await rig.requests.decide(_rid(scoped_filed), False, decided_by="captain")
    assert await rig.service.record_denial(scoped_denied) is True


async def test_a_recorded_denial_is_not_undone_by_a_later_approval(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _ctx(item="W1")
    verdict, filed = await _resolve(rig, _PUSH, context)
    request_id = _rid(filed)
    denied = await rig.requests.decide(request_id, False, decided_by="captain")
    assert await rig.service.record_denial(denied) is True
    mark = _spy(monkeypatch, rig.requests, "mark_fulfilled")

    flipped = await rig.requests.decide(request_id, True, decided_by="captain")  # the request store lets a decision be re-made
    assert flipped.status == "approved"
    assert await rig.service.fulfil_approval(rig.requests, flipped) is None  # the first decision wins
    assert (await rig.approvals.get(request_id)).state == "denied" and mark.calls == []
    outcome = await rig.service.resolve(verdict, command=_PUSH, context=context)
    assert outcome.message is not None and outcome.message.startswith(_denied_head(request_id))

    _, other_filed = await _resolve(rig, _PUSH_OTHER, context)  # negative control: an untouched ask approves
    _, fulfilled = await _approve(rig, _rid(other_filed))
    assert fulfilled is not None and fulfilled.status == "fulfilled"


_PUSH_VARIANT = "git  push origin main"  # two spaces: the same canonical command as _PUSH, another request


@pytest.mark.parametrize("order", [
    pytest.param("approve_then_deny", id="approve_then_deny"),
    pytest.param("deny_then_approve", id="deny_then_approve"),
])
async def test_denial_dominates_an_approval_of_the_same_command(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, order: str,
) -> None:
    """AD-1328 S2b repair r1: a live denial of a command beats an approval of it under another request id, in either order.

    Kills St4 (``use`` ignores the denial: approve_then_deny would run the command) and St10 (``record_decision`` ignores
    the denial: deny_then_approve would record the approval and fulfil the request).
    """
    context = _ctx(item="W1")
    verdict_a, filed_a = await _resolve(rig, _PUSH, context)
    verdict_b, filed_b = await _resolve(rig, _PUSH_VARIANT, context)
    request_a, request_b = _rid(filed_a), _rid(filed_b)
    assert verdict_a.canonical.key == verdict_b.canonical.key  # premise: one command, spelled two ways
    assert request_a != request_b and len(await rig.requests.list_pending()) == 2
    mark = _spy(monkeypatch, rig.requests, "mark_fulfilled")

    async def deny_b() -> None:
        denied = await rig.requests.decide(request_b, False, reason="not for this work", decided_by="captain")
        assert denied is not None and denied.status == "denied"
        assert await rig.service.record_denial(denied) is True
        assert (await rig.approvals.get(request_b)).state == "denied"

    if order == "approve_then_deny":
        _, fulfilled = await _approve(rig, request_a)
        assert fulfilled is not None and fulfilled.status == "fulfilled"
        assert (await rig.approvals.get(request_a)).state == "active"  # premise: the approval was in force
        await deny_b()
        rows = _request_rows(rig)

        outcome = await rig.service.resolve(verdict_a, command=_PUSH, context=context)

        assert outcome.message is not None and outcome.message.startswith(_denied_head(request_b))
        assert outcome.verdict.approval == {"state": "denied", "request_id": request_b, "use_id": None}
        assert outcome.verdict.runs is False
        assert (await rig.approvals.get(request_a)).uses == 0 and await rig.approvals.list_uses(request_a) == []
        assert _request_rows(rig) == rows and await rig.requests.list_pending() == []  # nothing new was filed
    else:
        await deny_b()
        with caplog.at_level(logging.WARNING, logger="probos.execution.command_escalation"):
            decided, fulfilled = await _approve(rig, request_a)
        assert decided.status == "approved" and fulfilled is None
        assert (await rig.requests.get(request_a, durable=True)).status == "approved"  # left approved: BF-722 retry
        assert mark.calls == [] and await rig.approvals.get(request_a) is None
        warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
        assert any("was not recorded: a denial of the same command" in text for text in warnings)
        assert not any("git" in text and "push" in text for text in caplog.messages)  # ids and scope, never the command
        rows = _request_rows(rig)

        outcome = await rig.service.resolve(verdict_a, command=_PUSH, context=context)

        assert outcome.message is not None and outcome.message.startswith(_denied_head(request_b))
        assert outcome.verdict.approval == {"state": "denied", "request_id": request_b, "use_id": None}
        assert outcome.verdict.runs is False
        assert _request_rows(rig) == rows

    _, other_command = await _resolve(rig, _PUSH_OTHER, context)  # negative controls: another command, another work item
    assert _state(other_command) == "filed"
    _, other_item = await _resolve(rig, _PUSH, _ctx(item="W2"))
    assert _state(other_item) == "filed"


async def test_reuse_stops_when_a_denial_lands(rig: _Rig) -> None:
    """AD-1328 S2b repair r1: a denial of the same command stops reuse of an earlier approval; a run already made stands.

    Kills St4 (``use`` ignores the denial: the resolve after the denial would be a ``reuse``).

    The variant request is filed before the approval, not after: once the approval is active the variant resolves to a
    reuse of it and files nothing.
    """
    context = _ctx(item="W1")
    verdict_a, filed_a = await _resolve(rig, _PUSH, context)
    verdict_b, filed_b = await _resolve(rig, _PUSH_VARIANT, context)
    verdict_c, filed_c = await _resolve(rig, _PUSH_OTHER, context)
    request_a, request_b, request_c = _rid(filed_a), _rid(filed_b), _rid(filed_c)
    assert verdict_a.canonical.key == verdict_b.canonical.key != verdict_c.canonical.key  # premise
    assert len({request_a, request_b, request_c}) == 3

    _, fulfilled_a = await _approve(rig, request_a)
    _, fulfilled_c = await _approve(rig, request_c)
    assert fulfilled_a is not None and fulfilled_c is not None
    first = await rig.service.resolve(verdict_a, command=_PUSH, context=context)
    assert first.message is None and _state(first) == "approved_run"
    control_first = await rig.service.resolve(verdict_c, command=_PUSH_OTHER, context=context)
    assert _state(control_first) == "approved_run"
    assert (await rig.approvals.get(request_a)).uses == 1

    denied = await rig.requests.decide(request_b, False, decided_by="captain")
    assert denied is not None and await rig.service.record_denial(denied) is True
    after = await rig.service.resolve(verdict_a, command=_PUSH, context=context)

    assert after.message is not None and after.message.startswith(_denied_head(request_b))
    assert after.verdict.approval == {"state": "denied", "request_id": request_b, "use_id": None}
    assert after.verdict.runs is False
    assert (await rig.approvals.get(request_a)).uses == 1  # the earlier run stands, no reuse was added
    assert len(await rig.approvals.list_uses(request_a)) == 1

    control_after = await rig.service.resolve(verdict_c, command=_PUSH_OTHER, context=context)  # negative control
    assert control_after.message is None and _state(control_after) == "reuse"


async def test_record_denial_ignores_what_is_not_a_command_denial(rig: _Rig) -> None:
    _, filed = await _resolve(rig, _PUSH, _ctx())
    approved = await rig.requests.decide(_rid(filed), True, decided_by="captain")
    assert approved.status == "approved"  # premise: an approval is not a denial
    assert await rig.service.record_denial(approved) is False
    assert await rig.approvals.get(approved.id) is None

    grant = await rig.requests.file_request("agent-1", "grant", "some_clearance")
    denied_grant = await rig.requests.decide(grant.id, False, decided_by="captain")
    assert denied_grant.status == "denied"  # premise: denied, but not a command escalation
    assert await rig.service.record_denial(denied_grant) is False
    assert await rig.approvals.get(grant.id) is None

    _, other = await _resolve(rig, _PUSH_OTHER, _ctx())  # negative control: a real command denial is recorded
    real = await rig.requests.decide(_rid(other), False, decided_by="captain")
    assert await rig.service.record_denial(real) is True


@pytest.mark.parametrize(
    ("decided_by", "recorded"),
    [pytest.param("first_officer", "first_officer", id="named"), pytest.param("", "captain", id="unnamed")],
)
async def test_record_denial_records_who_denied(rig: _Rig, decided_by: str, recorded: str) -> None:
    context = _ctx(item="W1")
    verdict, filed = await _resolve(rig, _PUSH, context)
    request_id = _rid(filed)
    denied = await rig.requests.decide(request_id, False, decided_by=decided_by)
    assert denied.decided_by == decided_by  # premise

    assert await rig.service.record_denial(denied) is True

    row = await rig.approvals.get(request_id)
    assert (row.state, row.approver) == ("denied", recorded)  # a denial from anyone sticks; an unnamed one is the Captain's
    outcome = await rig.service.resolve(verdict, command=_PUSH, context=context)
    assert _state(outcome) == "denied" and outcome.verdict.runs is False


# --------------------------------------------------------------------------------------
# 11. The inbox
# --------------------------------------------------------------------------------------


async def test_inbox_full_files_nothing(rig: _Rig) -> None:
    """At the per-agent cap nothing is filed and the agent is told so.

    Kills S-E6 (an unapplied cap would file the command).
    """
    service = rig.service_for(rig.gate, max_pending_per_agent=1)
    context = _ctx("agent-1")
    _, first = await _resolve(rig, _PUSH, context, service=service)
    assert _state(first) == "filed"
    assert rig.requests.count_pending_sync("agent-1") == 1 and _request_rows(rig) == 1  # premise: the inbox is at its cap

    verdict, outcome = await _resolve(rig, _PUSH_OTHER, context, service=service)

    assert outcome.message is not None and outcome.message.startswith(_INBOX_FULL_HEAD)
    assert _ASK_PUSH_WHY in outcome.message and "report what remains open" in outcome.message
    _not_a_capability_gap(outcome.message)
    assert outcome.verdict.approval == {"state": "inbox_full", "request_id": None, "use_id": None}
    assert outcome.verdict.runs is False
    assert _request_rows(rig) == 1 and len(await rig.requests.list_pending()) == 1  # nothing was filed

    repeat = await service.resolve(rig.judge(_PUSH), command=_PUSH, context=context)  # the cap is checked before the fold
    assert _state(repeat) == "inbox_full" and _request_rows(rig) == 1

    other_agent = await service.resolve(verdict, command=_PUSH_OTHER, context=_ctx("agent-2"))  # negative controls
    assert _state(other_agent) == "filed"  # the cap is per agent
    roomier = rig.service_for(rig.gate, max_pending_per_agent=2)
    assert _state(await roomier.resolve(verdict, command=_PUSH_OTHER, context=context)) == "filed"  # and a cap of 2 has room


async def test_stale_asks_leave_the_inbox_count(rig: _Rig) -> None:
    service = rig.service_for(rig.gate, max_pending_per_agent=1, pending_ttl_hours=72)
    context = _ctx()
    _, first = await _resolve(rig, _PUSH, context, service=service)
    _, full = await _resolve(rig, _PUSH_OTHER, context, service=service)
    assert (_state(first), _state(full)) == ("filed", "inbox_full")  # premise: the first ask counts against the cap

    rig.clock.advance(72 * 3600 + 60)
    later = await service.resolve(rig.judge(_PUSH_OTHER), command=_PUSH_OTHER, context=context)

    assert _state(later) == "filed"  # a stale ask no longer fills the inbox...
    assert {request.id for request in await rig.requests.list_pending()} == {_rid(first), _rid(later)}  # ...nor is it decided


# --------------------------------------------------------------------------------------
# 12. Fail toward refusal
# --------------------------------------------------------------------------------------


def _fault_store_raises(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(rig.requests, "file_action_request", _aboom)
    return _ctx()


def _fault_store_returns_none(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(rig.requests, "file_action_request", _none)
    return _ctx()


def _fault_payload_invalid(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(command_escalation, "validate_action_payload", lambda payload: None)
    return _ctx()


def _fault_no_agent(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return {"thread_id": "thr-1", "_crew_work_item_id": "W1"}


def _fault_count_raises(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(rig.requests, "count_pending_sync", _boom)
    return _ctx()


@pytest.mark.parametrize(
    "fault",
    [
        pytest.param(_fault_store_raises, id="store_raises"),
        pytest.param(_fault_store_returns_none, id="store_returns_none"),
        pytest.param(_fault_payload_invalid, id="payload_invalid"),
        pytest.param(_fault_no_agent, id="no_agent"),
        pytest.param(_fault_count_raises, id="count_raises"),
    ],
)
async def test_unfiled_paths(rig: _Rig, monkeypatch: pytest.MonkeyPatch, fault: Callable[..., dict[str, Any]]) -> None:
    verdict = rig.judge(_PUSH)
    assert verdict.decision == "escalate"  # premise
    context = fault(rig, monkeypatch)

    outcome = await rig.service.resolve(verdict, command=_PUSH, context=context)

    assert outcome.message is not None and outcome.message.startswith(_UNFILED_HEAD)
    assert _ASK_PUSH_WHY in outcome.message and "Do not repeat this call" in outcome.message
    _not_a_capability_gap(outcome.message)
    assert outcome.verdict.approval == {"state": "unfiled", "request_id": None, "use_id": None}
    assert outcome.verdict.runs is False
    assert _request_rows(rig) == 0 and await rig.requests.list_pending() == []  # nothing was filed

    monkeypatch.undo()  # negative control: the same call files once nothing is broken
    retry = await rig.service.resolve(verdict, command=_PUSH, context=_ctx())
    assert retry.message is not None and retry.message.startswith(_filed_head(_rid(retry)))
    assert _state(retry) == "filed" and _request_rows(rig) == 1


@pytest.mark.parametrize("failing", ["find", "use"])
async def test_a_failing_approval_store_files_and_never_admits(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch, failing: str,
) -> None:
    context = _ctx(item="W1")
    verdict, filed = await _resolve(rig, _PUSH, context)
    request_id = _rid(filed)
    await _approve(rig, request_id)
    first = await rig.service.resolve(verdict, command=_PUSH, context=context)
    assert first.message is None and _state(first) == "approved_run"  # premise: the approval admits a run

    # M2 #12, last sentence: a store that raises on the lookup or on the use never admits the run; the command is filed.
    monkeypatch.setattr(rig.approvals, failing, _aboom)
    outcome = await rig.service.resolve(verdict, command=_PUSH, context=context)

    assert outcome.message is not None and outcome.verdict.runs is False  # never admitted
    assert _state(outcome) == "filed" and _rid(outcome) != request_id  # filed for review instead
    _not_a_capability_gap(outcome.message)
    assert (await rig.approvals.get(request_id)).uses == 1 and len(await rig.approvals.list_uses(request_id)) == 1

    monkeypatch.undo()  # negative control: the approval was not consumed by the failure
    healthy = await rig.service.resolve(verdict, command=_PUSH, context=context)
    assert healthy.message is None and _state(healthy) == "reuse" and _rid(healthy) == request_id


async def test_a_racing_run_of_a_single_use_approval_is_refused(rig: _Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    context = _ctx(item=None)
    verdict, filed = await _resolve(rig, _PUSH, context)
    request_id = _rid(filed)
    await _approve(rig, request_id)
    real_find = rig.approvals.find
    raced: list[Any] = []

    async def find_then_lose_the_race(*args: Any, **kwargs: Any) -> Any:
        row = await real_find(*args, **kwargs)
        if kwargs.get("state") == "active" and row is not None and not raced:
            # another run takes the approval's only use between this lookup and this call's own use
            raced.append(await rig.approvals.use(row.request_id, agent_id="agent-1", scope_key="thread:thr-1"))
        return row

    monkeypatch.setattr(rig.approvals, "find", find_then_lose_the_race)
    outcome = await rig.service.resolve(verdict, command=_PUSH, context=context)

    assert raced and raced[0] is not None and raced[0].use_kind == "approved_run"  # premise: the other run won the use
    assert outcome.message is not None and outcome.verdict.runs is False and _state(outcome) == "filed"
    uses = await rig.approvals.list_uses(request_id)
    assert [use.use_id for use in uses] == [raced[0].use_id]  # exactly one run was admitted
    assert (await rig.approvals.get(request_id)).uses == 1


# --------------------------------------------------------------------------------------
# 13. Payload bounds
# --------------------------------------------------------------------------------------

_TEN_THOUSAND = "git push origin " + "x" * 10_000  # past the policy's 8,192-character limit: unparseable, so it escalates
_TWO_THOUSAND = "git push origin " + "x" * 2_000
_LONE_SURROGATE = "git push origin \udc80"
_WORST_CASE = " && ".join(f"cmd{index} {'z' * 200}" for index in range(6))


@pytest.mark.parametrize(
    ("make_gate", "command", "item", "thread", "shown", "truncated", "kinds"),
    [
        pytest.param(_escalate_gate, _TEN_THOUSAND, "W1", "thr-1", 1200, True, ["unparseable"], id="ten_thousand_chars"),
        pytest.param(_escalate_gate, _TWO_THOUSAND, "W1", "thr-1", 1200, True, ["rule"], id="two_thousand_chars"),
        pytest.param(
            _escalate_gate, _LONE_SURROGATE, "W1", "thr-1", len("git push origin \\udc80"), False, ["unparseable"],
            id="lone_surrogate",
        ),
        pytest.param(
            _worst_case_gate, _WORST_CASE, "W" * 128, "t" * 64, 300, True, ["rule"] * 5, id="worst_case_causes",
        ),
    ],
)
async def test_payload_bounds(
    rig: _Rig, make_gate: Callable[[], CommandPolicyGate], command: str, item: str, thread: str, shown: int,
    truncated: bool, kinds: list[str],
) -> None:
    gate = make_gate()
    service = rig.service_for(gate)
    verdict = rig.judge(command, gate)
    assert verdict.decision == "escalate"  # premise: the command reaches the service as an escalation
    if command == _LONE_SURROGATE:
        with pytest.raises(UnicodeEncodeError):  # premise: the raw text cannot be encoded, so a naive payload would fail
            command.encode("utf-8")

    outcome = await service.resolve(verdict, command=command, context=_ctx(item=item, thread=thread))

    assert outcome.message is not None and _state(outcome) == "filed"  # it files
    _not_a_capability_gap(outcome.message)
    request = await rig.requests.get(_rid(outcome))
    assert request is not None and request.payload is not None
    encoded = json.dumps(request.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert len(encoded) <= 4000  # the AD-1154 limit
    encoded.encode("utf-8")  # no lone surrogate survives into the request
    params = request.payload["params"]
    assert params["command_chars"] == len(command)
    assert [cause["kind"] for cause in params["causes"]] == kinds
    display = params["command"]
    if truncated:
        assert display.endswith("more characters]")
        assert display.startswith(command[:shown]) and " ...[" in display
        assert display == f"{command[:shown]} ...[{len(command) - shown} more characters]"
    else:
        assert not display.endswith("more characters]")
        assert display == "git push origin \\udc80"  # escaped, not dropped
    if command == _WORST_CASE:  # the second display pair: the first would not fit the limit
        assert params["causes_omitted"] == 1 and len(params["rules"]) == 6
        assert len(params["causes"][0]["text"]) < 200 and len(display) < 400
    if command == _TWO_THOUSAND:  # negative control: a payload that fits keeps the first pair's 1,200 characters
        assert len(display) > 1200 and params["causes"][0]["text"] == _ASK_PUSH_WHY


def test_no_payload_without_an_evaluated_verdict() -> None:
    gate = _escalate_gate()
    scope = EscalationScope("agent-1", "work_item:W1", "W1", "thr-1")
    verdict = gate.judge(_PUSH, site="run_command_tool", search_path=_SEARCH_PATH)

    payload = command_approval_payload(verdict, _PUSH, scope)  # control: an evaluated verdict has one
    assert payload is not None and payload["scope_key"] == "work_item:W1" and payload["thread_id"] == "thr-1"
    assert command_approval_payload(NO_POLICY, _PUSH, scope) is None


# --------------------------------------------------------------------------------------
# 14. The frames
# --------------------------------------------------------------------------------------


def test_frames_do_not_read_as_a_capability_gap() -> None:
    frames = {name: value for name, value in vars(command_escalation).items() if name.endswith("_FRAME")}
    assert set(frames) == {
        "_FILED_IN_TASK_FRAME", "_FILED_ONCE_FRAME", "_DENIED_FRAME", "_INBOX_FULL_FRAME", "_UNFILED_FRAME",
    }  # premise: every frame this module tells an agent; a new one must be added here
    causes = "Rule 'r': Pushes need review."
    for name, frame in frames.items():
        for where in ("", "in this conversation "):
            text = frame.format(causes=causes, request_id="x", where=where)
            assert causes in text, name
            _not_a_capability_gap(text)
    for gap in ("I don't have a tool for that.", "I can't run this command.", "That is not available here."):
        assert decomposer._CAPABILITY_GAP_RE.search(gap) is not None, gap  # negative control: the real regex does fire
    unfiled = frames["_UNFILED_FRAME"].format(causes=causes, request_id="x", where="")
    assert decomposer._CAPABILITY_GAP_RE.search(unfiled + " I cannot.") is not None  # and it fires on a frame that says so


# --------------------------------------------------------------------------------------
# 15. The builder
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["no_gate", "unconfigured", "no_approvals", "no_requests", "configured"])
async def test_build_command_escalations(rig: _Rig, caplog: pytest.LogCaptureFixture, case: str) -> None:
    def build(**overrides: Any) -> CommandEscalations | None:
        arguments: dict[str, Any] = {
            "gate": rig.gate, "approvals": rig.approvals, "requests": rig.requests, "work_items": rig.work_items,
            "inbox": ApprovalInboxConfig(),
        }
        arguments.update(overrides)
        return build_command_escalations(**arguments)

    assert isinstance(build(), CommandEscalations)  # premise: these arguments, unmodified, build a service
    assert {"max_pending_per_agent", "pending_ask_ttl_hours"} <= set(ApprovalInboxConfig.model_fields)  # the names read
    with caplog.at_level(logging.WARNING, logger="probos.execution.command_escalation"):
        if case == "no_gate":
            assert build(gate=None) is None
            assert not caplog.records  # no policy is not a fault: nothing is warned
        elif case == "unconfigured":
            no_rules = _gate(CommandPolicyConfig())
            assert no_rules.configured is False  # premise: a gate with no rules
            assert build(gate=no_rules) is None
            assert build(gate=SimpleNamespace(configured=1)) is None  # truthy is not configured: it must be True
            assert not caplog.records
        elif case == "no_approvals":
            assert build(approvals=None) is None
            assert "the command approval store is not running" in caplog.text
        elif case == "no_requests":
            assert build(requests=None) is None
            assert "the capability request store is not running" in caplog.text
        else:
            service = build(inbox=ApprovalInboxConfig(max_pending_per_agent=2))
            assert isinstance(service, CommandEscalations)
            context = _ctx("agent-1", item="W1")
            states = [_state((await _resolve(rig, command, context, service=service))[1])
                      for command in (_PUSH, _PUSH_OTHER, _PUSH_THIRD)]
            assert states == ["filed", "filed", "inbox_full"]  # the inbox config's cap
            assert not caplog.records

            stand_in = SimpleNamespace(max_pending_per_agent=1, pending_ask_ttl_hours=0)  # a window in which nothing is pending
            wide = build(inbox=stand_in)
            first_state = _state((await _resolve(rig, _PUSH, _ctx("agent-2"), service=wide))[1])
            second_state = _state((await _resolve(rig, _PUSH_OTHER, _ctx("agent-2"), service=wide))[1])
            assert (first_state, second_state) == ("filed", "filed")  # the inbox config's window, not the 72-hour default

            _, filed = await _resolve(rig, _PUSH, _ctx("agent-3", item="W1"), service=service)  # the work-item store flows on
            await _approve(rig, _rid(filed), service=service)
            ran = await _resolve(rig, _PUSH, _ctx("agent-3", item="W1"), service=service)
            assert ran[1].message is None and _state(ran[1]) == "approved_run"


# --------------------------------------------------------------------------------------
# Logs: no command text and no justification in any log line the S2b modules add (contract D5)
# --------------------------------------------------------------------------------------


async def test_no_log_line_of_the_service_or_the_store_carries_the_command(
    rig: _Rig, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = f"git push origin {_SENTINEL}"
    context = _ctx(item="W1")
    ours = ("probos.execution.command_escalation", "probos.execution.command_approvals")
    with caplog.at_level(logging.DEBUG):
        verdict, filed = await _resolve(rig, command, context)
        await _approve(rig, _rid(filed))
        assert _state(await rig.service.resolve(verdict, command=command, context=context)) == "approved_run"
        assert _state(await rig.service.resolve(verdict, command=command, context=context)) == "reuse"

        second = f"{command}-two"
        second_verdict, second_filed = await _resolve(rig, second, context)
        assert await rig.service.record_denial(await rig.requests.decide(_rid(second_filed), False)) is True
        assert _state(await rig.service.resolve(second_verdict, command=second, context=context)) == "denied"

        third = f"{command}-three"
        _, third_filed = await _resolve(rig, third, context)
        by_officer = await rig.requests.decide(_rid(third_filed), True, decided_by="first_officer")
        assert await rig.service.fulfil_approval(rig.requests, by_officer) is None

        assert _state(await rig.service.resolve(verdict, command=command, context={})) == "unfiled"  # no agent identity
        fourth = f"{command}-four"
        monkeypatch.setattr(rig.requests, "count_pending_sync", _boom)
        assert _state(await rig.service.resolve(rig.judge(fourth), command=fourth, context=context)) == "unfiled"

    formatter = logging.Formatter("%(message)s")  # a record with an exception is formatted with its traceback
    lines = [formatter.format(record) for record in caplog.records if record.name in ours]
    for expected in ("runs an escalated command as approved_run", "not the Captain", "no agent identity", "could not count"):
        assert any(expected in line for line in lines), expected  # premise: the lines this test is about were written
    assert [line for line in lines if _SENTINEL in line or _ASK_PUSH_WHY in line] == []
    request = await rig.requests.get(_rid(filed))
    assert _SENTINEL in json.dumps(request.payload)  # negative control: the command is in the request, where the Captain reads it
