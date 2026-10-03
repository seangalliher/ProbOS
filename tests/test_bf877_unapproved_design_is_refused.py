"""BF-877 (#1438): a self-mod design nobody approved is refused, not built.

The defect. ``SelfModificationPipeline.handle_unhandled_intent`` asked for approval
only when a callback was wired (``require_user_approval and _user_approval_fn and not
pre_approved``). The only code that wired one was ``ProbOSShell``, which the CLI builds
and the API builds once for every HXI slash command. So with the unified ladder off, a
``serve`` vessel designed and registered agents nobody approved -- from unattended NL
requests and from AD-855 work-item builds -- and after its first HXI slash command its
"approval" was a console prompt on the server's stdin.

The Captain's decision (#1438, comment 5945966053): the pipeline refuses a design that
needs approval, is not pre-approved and has nobody to ask, with a recorded
``approval_unavailable`` status and a reply that says so; the HXI Build Agent button and
the shell's strategy choice are the Captain's approval and pass ``pre_approved=True``; no
server process installs a console prompt -- only the CLI REPL does, not ``serve`` with or
without ``--interactive`` (A-1.1); and a build card the Captain approves is designed with
the ladder on or off, through the approval policy (A-1.2).

A-2: every unattended consumer of ``process_natural_language`` -- persistent tasks, the
in-memory task scheduler, the workflow cron and the correction retry -- reads the refusal
with ``approval_refusal`` and treats it as a failure, never as a success; a refused cron
replay uses its slot without counting a fire.

A-3: a refusal ends once the Captain approves the design, so it fails one run, never a
schedule: a refused recurring persistent task stays pending and tries again at its next
run, and a refused DAG resume keeps its checkpoint and returns the refusal.

The crossing tests run a booted runtime with the real pipeline, approval gate,
registration and designed pool; only the LLM designer, validator and sandbox are stubbed
(``_real_design``). The chain each one spans:

* unattended gap: ``process_natural_language`` -> design branch -> gate refuses -> the
  reply carries the refusal -> nothing registered, no request filed;
* HXI Build Agent: ``_run_selfmod`` -> pipeline, pre-approved -> registered (and, under
  the ladder, the card fulfilled); an operator's console prompt is neither asked nor
  replaced;
* shell strategy prompt: renderer -> pipeline, pre-approved -> registered;
* HXI slash command: ``_handle_slash_command`` -> API shell -> no prompt installed ->
  the next unattended gap is refused without opening one;
* CLI REPL shell: console prompt installed -> asked once -> "y" designs and registers;
* ladder card: decide route -> build fulfiller -> pipeline, pre-approved -> registered;
* AD-855 work-item gap, ladder off: filed and refused at file time -> the Captain
  approves on the route -> the fulfiller re-reads the committed approval -> one design
  -> registered and fulfilled;
* a delegate's approval of a build that requires consensus, ladder off: the fulfiller's
  policy refuses it -> nothing designed, the request stays approved;
* R11, ladder off: a gap that requires consensus is offered no skill, and the new agent
  is designed with the requirement and pre-approved;
* persistent task, ladder off: the store fires ``process_natural_language`` -> the gate
  refuses -> the store reads the refusal with ``approval_refusal`` -> the task is failed,
  not completed, and nothing is designed (A-2).
"""

from __future__ import annotations

import ast
import json
import logging
import sqlite3
import time
from contextlib import closing
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.responses import JSONResponse

import probos
from probos.api_models import CapabilityRequestDecideRequest, SelfModRequest
from probos.cognitive import nl_gap_triage
from probos.cognitive.capability_triage import triage_and_file
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.self_mod import (
    APPROVAL_UNAVAILABLE,
    APPROVAL_UNAVAILABLE_DETAIL,
    SelfModificationPipeline,
    approval_refusal,
)
from probos.cognitive.task_scheduler import TaskScheduler
from probos.cognitive.workflow_cron import WorkflowCronScheduler
from probos.events import EventType
from probos.persistent_tasks import PersistentTaskStore
from probos.routers.capability_requests import decide_capability_request, fulfil_on_approval
from probos.routers.scheduled_tasks import resume_dag_checkpoint
from probos.self_mod_manager import SelfModManager
from tests.test_ad1194_unified_capability_triage import (  # noqa: F401 -- booted is a fixture
    _META,
    _captain_takes_the_skill,
    _gap_dag,
    _one_option_shell,
    _skill_first_shell,
    _skill_runtime,
    booted,
)
from tests.test_bf817_resume_redecomposes import _write_checkpoint

_PARAMS = {"text": "the text to count"}
_SELF_MOD_LOGGER = "probos.cognitive.self_mod"
_ROUTE_LOGGER = "probos.routers.capability_requests"
_TASKS_LOGGER = "probos.persistent_tasks"
_SCHEDULER_LOGGER = "probos.cognitive.task_scheduler"
_CRON_LOGGER = "probos.cognitive.workflow_cron"


def _rig(approval: Any = None, *, require: bool = True) -> SimpleNamespace:
    designer = SimpleNamespace(
        design_agent=AsyncMock(return_value="class X: pass"),
        _build_class_name=lambda _name: "X",
        _build_agent_type=lambda name: name,
    )
    rig = SimpleNamespace(designer=designer, register=AsyncMock(), pool=AsyncMock(), trust=AsyncMock())
    rig.pipe = SelfModificationPipeline(
        designer=designer,
        validator=SimpleNamespace(validate=lambda *_a, **_k: []),
        sandbox=SimpleNamespace(test_agent=AsyncMock(return_value=SimpleNamespace(
            success=True, agent_class=object, execution_time_ms=1.0, error="",
        ))),
        monitor=MagicMock(),
        config=SimpleNamespace(
            max_designed_agents=5, require_user_approval=require,
            research_enabled=False, allowed_imports=[],
        ),
        register_fn=rig.register, create_pool_fn=rig.pool, set_trust_fn=rig.trust,
        user_approval_fn=approval,
    )
    return rig


# == 1. The gate ==============================================================


@pytest.mark.asyncio
async def test_a_design_nobody_can_approve_is_refused_and_nothing_is_designed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rig = _rig()

    with caplog.at_level(logging.WARNING, logger=_SELF_MOD_LOGGER):
        record = await rig.pipe.handle_unhandled_intent("count_words", "count words", _PARAMS)

    assert record is not None
    assert (record.intent_name, record.status, record.error) == (
        "count_words", APPROVAL_UNAVAILABLE, APPROVAL_UNAVAILABLE_DETAIL,
    )
    assert rig.pipe.design_records == [record]
    rig.designer.design_agent.assert_not_awaited()
    for fn in (rig.register, rig.pool, rig.trust):
        fn.assert_not_awaited()
    [warning] = [
        r.getMessage() for r in caplog.records
        if r.name == _SELF_MOD_LOGGER and r.levelno == logging.WARNING
    ]
    assert "BF-877" in warning and "'count_words'" in warning
    assert "capability_triage.unified_ladder_enabled" in warning


@pytest.mark.asyncio
async def test_a_pre_approved_design_needs_no_approval_callback() -> None:
    rig = _rig()

    record = await rig.pipe.handle_unhandled_intent(
        "count_words", "count words", _PARAMS, pre_approved=True,
    )

    assert record is not None and record.status == "active"
    rig.designer.design_agent.assert_awaited_once()
    rig.register.assert_awaited_once()


@pytest.mark.parametrize(("answer", "status", "designs"), [(True, "active", 1), (False, "rejected_by_user", 0)])
@pytest.mark.asyncio
async def test_a_wired_approval_callback_still_decides_the_design(
    answer: bool, status: str, designs: int,
) -> None:
    approval = AsyncMock(return_value=answer)
    rig = _rig(approval)

    record = await rig.pipe.handle_unhandled_intent("count_words", "count words", _PARAMS)

    assert record is not None and record.status == status
    approval.assert_awaited_once()
    assert rig.designer.design_agent.await_count == designs


@pytest.mark.asyncio
async def test_with_approval_not_required_no_callback_is_needed() -> None:
    rig = _rig(require=False)

    record = await rig.pipe.handle_unhandled_intent("count_words", "count words", _PARAMS)

    assert record is not None and record.status == "active"
    rig.designer.design_agent.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_user_approval_fn_installs_and_clears_the_approval_callback() -> None:
    rig = _rig()
    approval = AsyncMock(return_value=True)

    rig.pipe.set_user_approval_fn(approval)
    asked = await rig.pipe.handle_unhandled_intent("count_words", "count words", _PARAMS)
    rig.pipe.set_user_approval_fn(None)
    refused = await rig.pipe.handle_unhandled_intent("count_lines", "count lines", _PARAMS)

    assert asked is not None and asked.status == "active"
    approval.assert_awaited_once()
    assert refused is not None and refused.status == APPROVAL_UNAVAILABLE


def test_the_refusal_reads_as_a_refusal_not_a_capability_gap() -> None:
    assert APPROVAL_UNAVAILABLE_DETAIL.startswith("Not designed:")
    assert not is_capability_gap(APPROVAL_UNAVAILABLE_DETAIL)


# == 2. Across the runtime ====================================================


def _real_design(booted: Any, monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Stub only the LLM designer, validator and sandbox, as the R13 chain test does:
    the approval gate, the runtime's registration and the designed pool are real.
    Returns the consensus requirement of every design that reached the designer."""
    from probos.cognitive.cognitive_agent import CognitiveAgent
    from probos.types import IntentDescriptor

    designed_with: list[bool] = []

    def designed(consensus: bool) -> type:
        class WipeDiskAgent(CognitiveAgent):
            agent_type = "wipe_disk"
            _handled_intents = {"wipe_disk"}
            instructions = "You wipe the disk the Captain names."
            intent_descriptors = [
                IntentDescriptor(
                    name="wipe_disk", params={"device": "which disk"}, description="wipe a disk",
                    requires_consensus=consensus, requires_reflect=True, tier="domain",
                )
            ]

            async def act(self, decision: dict) -> dict:
                return {"success": True, "result": "wiped"}

        return WipeDiskAgent

    async def design_agent(**kwargs: Any) -> str:
        designed_with.append(kwargs["requires_consensus"])
        return "# designed"

    async def test_agent(_source: str, _intent: str, test_params: Any = None) -> Any:
        return SimpleNamespace(
            success=True, agent_class=designed(designed_with[-1]), execution_time_ms=1.0, error="",
        )

    pipe = booted.self_mod_pipeline
    monkeypatch.setattr(pipe, "_designer", SimpleNamespace(
        design_agent=design_agent, _build_class_name=lambda _name: "WipeDiskAgent",
        _build_agent_type=lambda name: name,
    ))
    monkeypatch.setattr(pipe, "_validator", SimpleNamespace(validate=lambda *_a, **_k: []))
    monkeypatch.setattr(pipe, "_sandbox", SimpleNamespace(test_agent=test_agent))
    monkeypatch.setattr(pipe, "_dependency_resolver", None, raising=False)
    monkeypatch.setattr(booted, "_system_qa", None)
    return designed_with


def _registered(booted: Any) -> bool:
    return "designed_wipe_disk" in booted.pools or any(
        d.name == "wipe_disk" for d in booted._collect_intent_descriptors()
    )


def _statuses(booted: Any) -> list[str]:
    return [record.status for record in booted.self_mod_pipeline.design_records]


def _arm_unattended_gap(booted: Any, monkeypatch: pytest.MonkeyPatch, reply: str) -> AsyncMock:
    dag = _gap_dag("please wipe the spare disk")
    dag.response = reply
    monkeypatch.setattr(booted.decomposer, "decompose", AsyncMock(return_value=dag))
    extract = AsyncMock(return_value=dict(_META))
    monkeypatch.setattr(booted, "_extract_unhandled_intent", extract)
    return extract


def _prompts(monkeypatch: pytest.MonkeyPatch, answer: str) -> list[str]:
    opened: list[str] = []

    def prompt(text: str = "") -> str:
        opened.append(text)
        return answer

    monkeypatch.setattr("builtins.input", prompt)
    return opened


async def _file_work_item_build(booted: Any) -> Any:
    """AD-855's route with the ladder off: an unregistered tool files a build, and the
    file-time route takes it straight to the pipeline."""
    return await triage_and_file(
        gap_target="wipe_disk", agent_id="agent-1", store=booted.capability_request_store,
        rationale="work item blocked on capability: wipe_disk",
        tool_registry=getattr(booted, "tool_registry", None),
        permission_store=getattr(booted, "tool_permission_store", None),
        mcp_server_store=getattr(booted, "mcp_server_store", None),
        self_mod_pipeline=booted.self_mod_pipeline,
        design_context={
            "intent_description": "wipe a disk", "parameters": {"device": "which disk"},
            "requires_consensus": True,
        },
    )


@pytest.mark.parametrize("reply", ["I don't have that capability yet.", ""])
@pytest.mark.asyncio
async def test_crossing_an_unattended_gap_with_the_ladder_off_is_refused_and_registers_nothing(
    booted: Any, monkeypatch: pytest.MonkeyPatch, reply: str,
) -> None:
    monkeypatch.setattr(booted.config.capability_triage, "unified_ladder_enabled", False)
    designed_with = _real_design(booted, monkeypatch)
    extract = _arm_unattended_gap(booted, monkeypatch, reply)
    opened = _prompts(monkeypatch, "y")

    result = await booted.process_natural_language("please wipe the spare disk")

    extract.assert_awaited_once()  # premise: the gap reached the design branch
    assert result["self_mod"] == {
        "status": APPROVAL_UNAVAILABLE, "intent": "wipe_disk", "error": APPROVAL_UNAVAILABLE_DETAIL,
    }
    assert APPROVAL_UNAVAILABLE_DETAIL in result["response"]
    assert (designed_with, opened) == ([], [])
    assert not _registered(booted)
    assert await booted.capability_request_store.list_pending() == []


@pytest.mark.parametrize("console", [False, True])
@pytest.mark.parametrize("ladder", [False, True])
@pytest.mark.asyncio
async def test_crossing_the_hxi_build_button_designs_without_asking(
    booted: Any, monkeypatch: pytest.MonkeyPatch, ladder: bool, console: bool,
) -> None:
    from probos.routers.chat import _run_selfmod

    monkeypatch.setattr(booted.config.capability_triage, "unified_ladder_enabled", ladder)
    designed_with = _real_design(booted, monkeypatch)
    # An operator's console prompt that would decline if it were asked.
    prompt = AsyncMock(return_value=False) if console else None
    monkeypatch.setattr(booted.self_mod_pipeline, "_user_approval_fn", prompt)
    click: dict[str, Any] = {
        "intent_name": "wipe_disk", "intent_description": "wipe a disk",
        "parameters": {"device": "which disk"}, "original_message": "",
    }
    card = None
    if ladder:
        card = await nl_gap_triage.file_nl_gap(booted, dict(_META))
        assert card is not None, "premise: the proposal filed the gap"
        click["capability_request_id"] = card.id

    await _run_selfmod(SelfModRequest(**click), booted)

    assert designed_with == [ladder]  # under the ladder, the card's consensus requirement
    assert _registered(booted)
    assert booted.self_mod_pipeline._user_approval_fn is prompt
    if prompt is not None:
        prompt.assert_not_awaited()
    if card is not None:
        done = await booted.capability_request_store.get(card.id)
        assert done is not None and done.status == "fulfilled"


@pytest.mark.parametrize("console", [False, True])
@pytest.mark.asyncio
async def test_crossing_the_shell_strategy_prompt_designs_without_asking_again(
    booted: Any, monkeypatch: pytest.MonkeyPatch, console: bool,
) -> None:
    from rich.console import Console

    monkeypatch.setattr(booted.config.capability_triage, "unified_ladder_enabled", False)
    designed_with = _real_design(booted, monkeypatch)
    _arm_unattended_gap(booted, monkeypatch, "I don't have that capability yet.")
    renderer_mod = _one_option_shell(monkeypatch, "y")
    prompt = AsyncMock(return_value=False) if console else None
    monkeypatch.setattr(booted.self_mod_pipeline, "_user_approval_fn", prompt)
    renderer = renderer_mod.ExecutionRenderer(
        Console(file=StringIO(), force_terminal=True, width=120), booted, debug=False,
    )

    await renderer.process_with_feedback("please wipe the spare disk")

    assert designed_with == [True]
    assert _registered(booted)
    assert booted.self_mod_pipeline._user_approval_fn is prompt
    if prompt is not None:
        prompt.assert_not_awaited()


@pytest.mark.asyncio
async def test_crossing_an_hxi_slash_command_installs_no_console_approval_prompt(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.api import _handle_slash_command

    monkeypatch.setattr(booted.config.capability_triage, "unified_ladder_enabled", False)
    designed_with = _real_design(booted, monkeypatch)
    _arm_unattended_gap(booted, monkeypatch, "I don't have that capability yet.")
    opened = _prompts(monkeypatch, "y")

    reply = await _handle_slash_command("/help", booted)
    result = await booted.process_natural_language("please wipe the spare disk")

    assert reply["response"] and not reply["response"].startswith("Command error"), "premise"
    assert booted.self_mod_pipeline._user_approval_fn is None
    assert result["self_mod"]["status"] == APPROVAL_UNAVAILABLE
    assert (designed_with, opened) == ([], [])


@pytest.mark.asyncio
async def test_crossing_an_interactive_shell_still_asks_at_the_console(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rich.console import Console

    from probos.experience.shell import ProbOSShell

    monkeypatch.setattr(booted.config.capability_triage, "unified_ladder_enabled", False)
    designed_with = _real_design(booted, monkeypatch)
    _arm_unattended_gap(booted, monkeypatch, "I don't have that capability yet.")
    opened = _prompts(monkeypatch, "y")

    ProbOSShell(booted, Console(file=StringIO()), self_mod_console_approval=True)
    result = await booted.process_natural_language("please wipe the spare disk")

    assert opened == ["  Approve? [y/n]: "]
    assert result["self_mod"]["status"] == "active"
    assert designed_with == [True]
    assert _registered(booted)


def test_only_the_attended_entry_points_build_a_shell_that_asks() -> None:
    """A-1.1: the CLI REPL asks; ``serve`` (with or without ``--interactive``) and the
    API do not. Every ``ProbOSShell(...)`` construction in the package, in line order."""
    root = Path(probos.__file__).resolve().parent
    sites: dict[str, list[Any]] = {}
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "ProbOSShell":
                continue
            flag = next((kw.value for kw in node.keywords if kw.arg == "self_mod_console_approval"), None)
            value = None if flag is None else (flag.value if isinstance(flag, ast.Constant) else "dynamic")
            sites.setdefault(path.relative_to(root).as_posix(), []).append((node.lineno, value))
    in_order = {site: [value for _line, value in sorted(calls)] for site, calls in sites.items()}

    assert in_order == {"__main__.py": [True, None], "api.py": [None]}


@pytest.mark.asyncio
async def test_crossing_a_captain_approved_build_card_designs_with_no_approval_callback(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    designed_with = _real_design(booted, monkeypatch)
    card = await nl_gap_triage.file_nl_gap(booted, dict(_META))
    assert card is not None, "premise: the gap was filed"

    response = await decide_capability_request(
        card.id, CapabilityRequestDecideRequest(approve=True, reason=""), runtime=booted,
    )

    assert response["fulfilled"] is True
    assert designed_with == [True]
    assert _registered(booted)


@pytest.mark.asyncio
async def test_crossing_a_work_item_build_gap_with_the_ladder_off_waits_for_and_honours_the_captains_approval(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(booted.config.capability_triage, "unified_ladder_enabled", False)
    designed_with = _real_design(booted, monkeypatch)
    store = booted.capability_request_store

    request = await _file_work_item_build(booted)

    assert request.kind == "build", "premise: an unregistered tool files a build"
    assert _statuses(booted) == [APPROVAL_UNAVAILABLE], "premise: the file-time route reached the gate"
    filed = await store.get(request.id)
    assert filed is not None and filed.status == "pending"
    assert designed_with == [] and not _registered(booted)

    response = await decide_capability_request(
        request.id, CapabilityRequestDecideRequest(approve=True, reason=""), runtime=booted,
    )

    assert response["fulfilled"] is True
    assert designed_with == [True]
    assert _statuses(booted) == [APPROVAL_UNAVAILABLE, "active"]
    assert _registered(booted)
    done = await store.get(request.id)
    assert done is not None and (done.status, done.decided_by) == ("fulfilled", "captain")


@pytest.mark.asyncio
async def test_a_delegate_approval_of_a_consensus_build_with_the_ladder_off_designs_nothing(
    booted: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(booted.config.capability_triage, "unified_ladder_enabled", False)
    designed_with = _real_design(booted, monkeypatch)
    store = booted.capability_request_store
    request = await _file_work_item_build(booted)
    assert request.kind == "build" and _statuses(booted) == [APPROVAL_UNAVAILABLE], "premise"
    # Filed with the ladder off, the request carries no triage record, so the store
    # records any decider's approval; the fulfiller's policy is what refuses this one.
    decided = await store.decide(request.id, True, reason="a delegate approves", decided_by="architect_0")
    assert decided is not None and (decided.status, decided.decided_by) == ("approved", "architect_0"), "premise"

    with caplog.at_level(logging.ERROR, logger=_ROUTE_LOGGER):
        fulfilled = await fulfil_on_approval(booted, store, decided, approve=True)

    assert fulfilled is False
    assert designed_with == []
    assert _statuses(booted) == [APPROVAL_UNAVAILABLE]
    assert not _registered(booted)
    [error] = [
        r.getMessage() for r in caplog.records if r.name == _ROUTE_LOGGER and r.levelno == logging.ERROR
    ]
    assert "BF-877" in error and "AD-1194" in error and "'architect_0'" in error
    kept = await store.get(request.id)
    assert kept is not None and (kept.status, kept.decided_by) == ("approved", "architect_0")


@pytest.mark.asyncio
async def test_with_the_ladder_off_a_gap_that_requires_consensus_is_offered_no_skill(
    booted: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rich.console import Console

    monkeypatch.setattr(booted.config.capability_triage, "unified_ladder_enabled", False)
    pipe = _skill_runtime(booted, monkeypatch, requires_consensus=True)
    proposed: list[list[str]] = []
    renderer_mod = _skill_first_shell(monkeypatch, proposed)
    monkeypatch.setattr("builtins.input", _captain_takes_the_skill)
    out = StringIO()
    renderer = renderer_mod.ExecutionRenderer(
        Console(file=out, force_terminal=True, width=120), booted, debug=False,
    )

    await renderer.process_with_feedback("please wipe the spare disk")

    shown = out.getvalue()
    assert proposed == [["add_skill", "new_agent"]], "premise: the recommender proposed a skill"
    assert "Add skill to existing agent" not in shown and "Create WipeDiskAgent" in shown
    assert "this intent requires consensus" in shown
    assert "an approved build request" not in shown
    assert pipe.skill_calls == []
    [(_args, kwargs)] = pipe.calls
    assert (kwargs["requires_consensus"], kwargs["pre_approved"]) == (True, True)
    assert await booted.capability_request_store.list_pending() == []


# == 3. Unattended consumers (A-2) ============================================
#
# Every unattended consumer of ``process_natural_language`` treated a returned result as a
# success, and the refusal is a returned result. Each now asks ``approval_refusal``.

_REFUSED_REPLY = f"I don't have that capability yet.\n\n{APPROVAL_UNAVAILABLE_DETAIL}"
_REFUSAL = {"status": APPROVAL_UNAVAILABLE, "intent": "wipe_disk"}


def _refusal_result() -> dict[str, Any]:
    """The NL result ``process_natural_language`` returns for a refused design: the record
    in ``self_mod``, and its detail in the reply."""
    return {
        "input": "wipe the spare disk", "results": {}, "complete": True, "node_count": 0,
        "completed_count": 0, "failed_count": 0, "response": _REFUSED_REPLY,
        "self_mod": {**_REFUSAL, "error": APPROVAL_UNAVAILABLE_DETAIL},
    }


def _replies() -> dict[str, dict[str, Any]]:
    """A refused request and, as each test's premise, one that succeeds."""
    return {"wipe the spare disk": _refusal_result(), "count the spare disks": {"response": "2 disks"}}


def _warnings(caplog: pytest.LogCaptureFixture, logger: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == logger and r.levelno == logging.WARNING]


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"self_mod": {**_REFUSAL, "error": "refused: nobody to ask"}}, "refused: nobody to ask"),
        (_refusal_result(), APPROVAL_UNAVAILABLE_DETAIL),
        ({"self_mod": {**_REFUSAL, "error": ""}}, APPROVAL_UNAVAILABLE_DETAIL),
        ({"self_mod": dict(_REFUSAL)}, APPROVAL_UNAVAILABLE_DETAIL),
        ({"self_mod": {**_REFUSAL, "error": None}}, APPROVAL_UNAVAILABLE_DETAIL),
        ({"response": "done", "self_mod": {"status": "active", "intent": "wipe_disk", "agent_type": "wipe_disk"}}, None),
        ({"response": "done"}, None),
        (None, None),
        (APPROVAL_UNAVAILABLE, None),
        ({"self_mod": APPROVAL_UNAVAILABLE}, None),
        ({"self_mod": {"status": "rejected_by_user", "intent": "wipe_disk", "error": "declined"}}, None),
    ],
    ids=[
        "refusal", "nl-result", "empty-error", "no-error", "none-error", "success", "no-self-mod", "none",
        "not-a-dict", "self-mod-not-a-dict", "another-status",
    ],
)
def test_approval_refusal_classifies_only_the_refusal(result: object, expected: str | None) -> None:
    assert approval_refusal(result) == expected


@pytest.mark.asyncio
async def test_a_one_shot_persistent_task_refused_for_want_of_approval_is_failed_not_completed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    replies = _replies()
    fired: list[str] = []

    async def process_fn(text: str, **_kwargs: Any) -> dict[str, Any]:
        fired.append(text)
        return replies[text]

    emitted: list[tuple[Any, dict[str, Any]]] = []
    store = PersistentTaskStore(
        db_path=str(tmp_path / "scheduled_tasks.db"),
        emit_event=lambda kind, data: emitted.append((kind, data)),
        process_fn=process_fn, tick_interval=100,
    )
    await store.start()
    try:
        refused = await store.create_task("wipe the spare disk", schedule_type="once", execute_at=time.time() - 1)
        done = await store.create_task("count the spare disks", schedule_type="once", execute_at=time.time() - 1)
        with caplog.at_level(logging.WARNING, logger=_TASKS_LOGGER):
            await store._execute_due_tasks()
            await store._execute_due_tasks()
        refused_row = await store.get_task(refused.id)
        done_row = await store.get_task(done.id)
    finally:
        await store.stop()

    assert done_row is not None and done_row.status == "completed", "premise: a success completes the task"
    assert sorted(fired) == ["count the spare disks", "wipe the spare disk"]  # once each: neither is due again
    assert refused_row is not None and (refused_row.status, refused_row.run_count) == ("failed", 1)
    assert json.loads(refused_row.last_result or "null") == {"error": APPROVAL_UNAVAILABLE_DETAIL}
    updated = [
        data["status"] for kind, data in emitted
        if kind == EventType.SCHEDULED_TASK_UPDATED and data["task_id"] == refused.id
    ]
    assert updated == ["failed"]
    [warning] = _warnings(caplog, _TASKS_LOGGER)
    assert "BF-877" in warning and refused.id in warning


@pytest.mark.asyncio
async def test_a_refused_task_scheduler_task_is_failed_and_still_delivers_the_refusal(
    caplog: pytest.LogCaptureFixture,
) -> None:
    replies = _replies()
    delivered: list[tuple[str, str]] = []

    class _FakeChannel:
        async def send_response(self, channel_id: str, text: str, **_kwargs: Any) -> None:
            delivered.append((channel_id, text))

    async def process_fn(text: str) -> dict[str, Any]:
        return replies[text]

    scheduler = TaskScheduler(process_fn=process_fn, channel_adapters=[_FakeChannel()])
    refused = scheduler.schedule("wipe the spare disk", delay_seconds=0, channel_id="refused-channel")
    done = scheduler.schedule("count the spare disks", delay_seconds=0, channel_id="done-channel")

    with caplog.at_level(logging.WARNING, logger=_SCHEDULER_LOGGER):
        for task in (refused, done):
            await scheduler._execute_task(task)

    assert done.status == "completed", "premise: a success completes the task"
    assert (refused.status, refused.last_result) == ("failed", replies["wipe the spare disk"])
    assert dict(delivered) == {"refused-channel": _REFUSED_REPLY, "done-channel": "2 disks"}
    [warning] = _warnings(caplog, _SCHEDULER_LOGGER)
    assert "BF-877" in warning and refused.id in warning


@pytest.mark.asyncio
async def test_a_refused_cron_replay_uses_its_slot_without_counting_a_fire(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    replies = _replies()
    replayed: list[str] = []
    clock = [1_700_000_000.0]

    async def process_nl(user_input: str) -> dict[str, Any]:
        replayed.append(user_input)
        return replies[user_input]

    db_path = tmp_path / "workflow_cron.db"
    # A one-hour background tick never runs here; the test ticks by hand on its own clock.
    scheduler = WorkflowCronScheduler(
        process_nl, db_path=str(db_path), tick_interval_seconds=3600.0, clock=lambda: clock[0],
    )
    await scheduler.start()
    try:
        refused = await scheduler.register("wipe the spare disk", "*/1 * * * *")
        done = await scheduler.register("count the spare disks", "*/1 * * * *")
        clock[0] += 120.0
        now = clock[0]
        with caplog.at_level(logging.WARNING, logger=_CRON_LOGGER):
            await scheduler._tick_once()
            await scheduler._tick_once()
    finally:
        await scheduler.stop()

    assert (done.fire_count, done.last_fired_at) == (1, now), "premise: a replay counts a fire"
    assert replayed == ["wipe the spare disk", "count the spare disks"]  # the second tick replays neither
    assert (refused.fire_count, refused.last_fired_at) == (0, now)
    with closing(sqlite3.connect(db_path)) as db:
        rows = {
            trigger_id: (last_fired_at, fire_count)
            for trigger_id, last_fired_at, fire_count in db.execute(
                "SELECT id, last_fired_at, fire_count FROM workflow_cron_triggers"
            )
        }
    assert rows == {refused.id: (now, 0), done.id: (now, 1)}
    [warning] = _warnings(caplog, _CRON_LOGGER)
    assert "BF-877" in warning and refused.id in warning


class _FakeFeedback:
    def __init__(self) -> None:
        self.scored: list[bool] = []

    async def apply_correction_feedback(self, **kwargs: Any) -> None:
        self.scored.append(kwargs["retry_success"])


def _correction_manager(feedback: _FakeFeedback, retry: dict[str, Any]) -> SelfModManager:
    """A real manager whose hot reload and retry need none of the absent services."""
    manager = SelfModManager(
        self_mod_pipeline=None, knowledge_store=None, trust_network=None, intent_bus=None,
        capability_registry=None, registry=None, pools={}, spawner=SimpleNamespace(_templates={}),
        decomposer=None, feedback_engine=feedback, llm_client=None, event_emitter=None, config=None,
        semantic_layer=None, collect_intent_descriptors_fn=list,
        process_natural_language_fn=AsyncMock(return_value=retry), add_skill_to_agents_fn=None,
        register_agent_type_fn=None, unregister_agent_type_fn=None, create_pool_fn=None,
    )
    manager._last_execution_text = "wipe the spare disk"  # as the runtime sets it before a correction
    return manager


@pytest.mark.asyncio
async def test_a_refused_correction_retry_is_not_scored_as_success() -> None:
    feedback = _FakeFeedback()

    for retry in _replies().values():
        record = SimpleNamespace(
            strategy="new_agent", agent_type="wipe_disk", intent_name="wipe_disk", source_code="", status="active",
        )
        patch = SimpleNamespace(agent_class=object, patched_source="# patched", changes_description="device path fixed")

        corrected = await _correction_manager(feedback, retry).apply_correction(SimpleNamespace(), patch, record)

        assert (corrected.retried, corrected.retry_result) == (True, retry), "premise: the retry ran"
    assert feedback.scored == [False, True]


@pytest.mark.asyncio
async def test_crossing_an_unattended_gap_refused_for_want_of_approval_fails_its_persistent_task(
    booted: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(booted.config.capability_triage, "unified_ladder_enabled", False)
    designed_with = _real_design(booted, monkeypatch)
    extract = _arm_unattended_gap(booted, monkeypatch, "I don't have that capability yet.")
    opened = _prompts(monkeypatch, "y")
    # Wired as startup/communication.py wires it; the test fires it instead of the tick.
    store = PersistentTaskStore(
        db_path=str(tmp_path / "scheduled_tasks.db"), process_fn=booted.process_natural_language,
        tick_interval=100,
    )
    await store.start()
    try:
        task = await store.create_task(
            "please wipe the spare disk", schedule_type="once", execute_at=time.time() - 1,
        )
        await store._execute_due_tasks()
        fired = await store.get_task(task.id)
    finally:
        await store.stop()

    extract.assert_awaited_once()  # premise: the task's request reached the design branch
    assert fired is not None and (fired.status, fired.run_count) == ("failed", 1)
    assert json.loads(fired.last_result or "null") == {"error": APPROVAL_UNAVAILABLE_DETAIL}
    assert _statuses(booted) == [APPROVAL_UNAVAILABLE]
    assert (designed_with, opened) == ([], [])
    assert not _registered(booted)


# == 4. A refusal is recoverable (A-3) ========================================
#
# A refusal ends once the Captain approves the design, so it fails one run, never a schedule,
# and a refused resume keeps the checkpoint a later resume needs.


@pytest.mark.asyncio
async def test_a_refused_recurring_persistent_task_stays_scheduled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    clock = [1_700_000_000.0]
    monkeypatch.setattr("probos.persistent_tasks.time", SimpleNamespace(time=lambda: clock[0]))
    fired: list[str] = []

    async def process_fn(text: str, **_kwargs: Any) -> dict[str, Any]:
        fired.append(text)
        return _refusal_result()

    emitted: list[tuple[Any, dict[str, Any]]] = []
    store = PersistentTaskStore(
        db_path=str(tmp_path / "scheduled_tasks.db"),
        emit_event=lambda kind, data: emitted.append((kind, data)),
        process_fn=process_fn, tick_interval=100,
    )
    await store.start()
    try:
        hourly = await store.create_task("wipe the spare disk hourly", schedule_type="interval", interval_seconds=3600)
        last = await store.create_task(
            "wipe the spare disk one last time", schedule_type="interval", interval_seconds=3600, max_runs=1,
        )
        once = await store.create_task("wipe the spare disk once", schedule_type="once", execute_at=clock[0] + 60)
        clock[0] += 3600
        with caplog.at_level(logging.WARNING, logger=_TASKS_LOGGER):
            await store._execute_due_tasks()
            refused = await store.get_task(hourly.id)
            ended = [await store.get_task(task.id) for task in (last, once)]
            await store._execute_due_tasks()  # not due again before its next run
            assert refused is not None and refused.next_run_at is not None
            clock[0] = refused.next_run_at + 1
            await store._execute_due_tasks()
        retried = await store.get_task(hourly.id)
    finally:
        await store.stop()

    assert (refused.status, refused.run_count) == ("pending", 1)
    assert refused.last_run_at is not None and refused.next_run_at > refused.last_run_at
    assert json.loads(refused.last_result or "null") == {"error": APPROVAL_UNAVAILABLE_DETAIL}
    assert retried is not None and (retried.status, retried.run_count) == ("pending", 2)
    assert [task.status if task else None for task in ended] == ["failed", "failed"], (
        "premise: a refused one-shot task, and one with no run left, are failed"
    )
    assert sorted(fired) == sorted([hourly.intent_text, hourly.intent_text, last.intent_text, once.intent_text])
    updated = [
        data["status"] for kind, data in emitted
        if kind == EventType.SCHEDULED_TASK_UPDATED and data["task_id"] == hourly.id
    ]
    assert updated == ["pending", "pending"]
    warnings = _warnings(caplog, _TASKS_LOGGER)
    recurring = [warning for warning in warnings if hourly.id in warning]
    assert (len(warnings), len(recurring)) == (4, 2)
    assert all("BF-877" in warning and "stays scheduled" in warning for warning in recurring)


@pytest.mark.asyncio
async def test_a_refused_dag_resume_keeps_its_checkpoint(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    replies = [_refusal_result(), {"response": "deployed"}]
    resumed: list[str] = []

    async def process_fn(text: str, **_kwargs: Any) -> dict[str, Any]:
        resumed.append(text)
        return replies.pop(0)

    emitted: list[tuple[Any, dict[str, Any]]] = []
    store = PersistentTaskStore(
        emit_event=lambda kind, data: emitted.append((kind, data)),
        process_fn=process_fn, checkpoint_dir=str(tmp_path),
    )
    runtime = SimpleNamespace(persistent_task_store=store)
    dag_id = "3f9c2a7b41d0"
    _write_checkpoint(tmp_path, dag_id, completed=[], pending=["a"])
    checkpoint = tmp_path / f"{dag_id}.json"

    with caplog.at_level(logging.WARNING, logger=_TASKS_LOGGER):
        refused = await resume_dag_checkpoint(dag_id, runtime=runtime)
    kept = checkpoint.exists()
    events_when_refused = [kind for kind, _data in emitted]
    approved = await resume_dag_checkpoint(dag_id, runtime=runtime)  # once the Captain approves the design

    assert isinstance(refused, JSONResponse) and refused.status_code == 400
    assert json.loads(refused.body) == {"error": APPROVAL_UNAVAILABLE_DETAIL, "dag_id": dag_id}
    assert kept and EventType.SCHEDULED_TASK_DAG_RESUMED not in events_when_refused
    [warning] = _warnings(caplog, _TASKS_LOGGER)
    assert "BF-877" in warning and dag_id[:8] in warning
    assert approved == {"success": True, "dag_id": dag_id, "result": {"response": "deployed"}}
    assert not checkpoint.exists(), "premise: a resume that succeeds deletes its checkpoint"
    assert [kind for kind, _data in emitted].count(EventType.SCHEDULED_TASK_DAG_RESUMED) == 1
    assert resumed == ["deploy the thing", "deploy the thing"]
