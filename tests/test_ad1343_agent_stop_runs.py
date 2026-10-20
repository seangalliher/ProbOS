"""AD-1343 S1 (#1595), amendment A2: the run entry, a delegated task and the inline browser action refuse a stopped agent (T30, T31, T34).

``prompts/ad-1343-a2-amendment.md`` answers a cross-family review of the S1 candidate: a new agentic run started outside
``handle_intent`` (a task delegated to a stopped colleague, a crew subtask, a correction re-run) and an inline browser action proposed
by a turn admitted before the order were not refused. These tests cover three of its seams, each over the real class and a real
``AgentStopService`` over ``agent_stops.db`` in ``tmp_path``:

* T30: ``WorkItemAgenticExecutor.run`` raises ``AgentStopped`` before any validation, browser reservation, context or model work, unless
  the agent's own admitted turn passes ``admitted_turn=True``. The gate is the one the run's tool calls are refused by,
  ``runtime.tool_registry.stop_gate``: the runtime here has no ``agent_stops`` attribute.
* T31: ``DelegateTaskTool.invoke`` answers a stopped target as not started, with no tree slot, no broker binding and no nested run,
  and answers the same when the order lands between its own check and the run (the race).
* T34: ``DmReplyPipeline.step_4e_action_dispatch`` strips the action markers of a stopped agent and registers and runs nothing.

The names A2 adds (``AgentStopped``) are read from the module when a test runs, so a tree without A2 fails each test on its own
behaviour rather than all of them at import. Every store lives in ``tmp_path``; the live data directory is never read. Nothing here
sleeps or waits on a timer: the service's clock is injected and every collaborator is in memory.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos import agent_stop
from probos.agent_stop import AgentStopService, StopRecord
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.dm.action_dispatcher import ActionDispatcher, ActionStatus, DispatchedAction
from probos.cognitive.dm.reply_pipeline import DmReplyPipeline
from probos.execution.effect_types import EffectDispatchContext, EffectOperationHandle, EffectPermit
from probos.tools.delegate_task_tool import DelegateTaskTool
from probos.tools.delegation_budget import DELEGATION_TREE_BUDGET_KEY, DelegationTreeBudget, TreeCeilings, TreeUsage
from probos.tools.registry import ToolRegistry
from tests.test_ad1072_agentic_tools import _Agent, _callsign_registry, _delegation_runtime
from tests.test_ad1343_agent_stop import AGENT, LIFT_REASON, OTHER, PRIVATE_FRAGMENT, REASON, _Clock, _service
from tests.test_ad745_pipeline_dispatch import _build_pipeline, _build_runtime

THREAD_ID = "ad1343-runs-thread"
CHILD_ID = "ad1343-child-0001"
PARENT_ID = "ad1343-parent-0001"
BASHIR = "Bashir"  # the callsign of AGENT in T31
ACTION_REPLY = 'Looking. [ACTION: {"verb":"screenshot","args":{}}]'  # a tier-1 action: the pipeline runs it inline
RESERVED_OUTCOME = object()  # what the spy ``_run_reserved`` answers
LOGGERS_OF_THE_RUN_ENTRY = ("probos.agent_stop", "probos.cognitive.agentic_dispatch")
LOGGERS_OF_THE_DELEGATION = ("probos.agent_stop", "probos.tools.delegate_task_tool")
LOGGERS_OF_THE_ACTION = ("probos.agent_stop", "probos.cognitive.dm.reply_pipeline")


def _unstopped_log(caplog: pytest.LogCaptureFixture, names: tuple[str, ...]) -> list[tuple[str, int, str]]:
    """Every record at INFO or above that the named loggers wrote since ``caplog.clear()``, as ``(logger, level, message)``."""
    return [(r.name, r.levelno, r.getMessage()) for r in caplog.records if r.levelno >= logging.INFO and r.name in names]


class _CountingLLM:
    """Test-local LLM client that counts every request it is asked to complete and answers an empty completion."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request: Any, **_kwargs: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(content="", content_blocks=[], tokens_used=0)


class _ReservedSpy:
    """Stands in for ``_run_reserved``: keeps the keyword arguments of every call and answers ``RESERVED_OUTCOME``."""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> object:
        self.received.append(kwargs)
        return RESERVED_OUTCOME


class _OwnedStepsPortSpy:
    """Test-local owned-steps execution port: counts ``validate`` calls, the first thing ``run`` does with an owned step."""

    def __init__(self) -> None:
        self.validated: list[tuple[Any, Any]] = []

    async def validate(self, lease: Any, permit: Any) -> None:
        self.validated.append((lease, permit))


def _owned_run_arguments(port: _OwnedStepsPortSpy) -> dict[str, Any]:
    """The arguments of an owned-steps run for AGENT whose binding checks pass, so that ``validate`` is the next thing ``run`` does."""
    return {
        "agent_id": AGENT,
        "instructions": "You are the Surgeon.",
        "task_text": "AD-1343: close the incision.",
        "thread_id": THREAD_ID,
        "extra_context": {"_crew_work_item_id": CHILD_ID, "_crew_session_id": PARENT_ID},
        "owned_steps_execution_port": port,
        "owned_steps_execution_lease": SimpleNamespace(snapshot=SimpleNamespace(control=SimpleNamespace(thread_id=THREAD_ID))),
        "owned_steps_execution_permit": SimpleNamespace(assignee_id=AGENT, child_id=CHILD_ID, parent_id=PARENT_ID),
    }


# T30
async def test_the_run_entry_refuses_a_stopped_agent_before_any_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    llm, port, reserved = _CountingLLM(), _OwnedStepsPortSpy(), _ReservedSpy()
    executor = WorkItemAgenticExecutor(llm_client=llm)
    monkeypatch.setattr(executor, "_run_reserved", reserved)
    registry = ToolRegistry()
    runtime = SimpleNamespace(tool_registry=registry)  # no ``agent_stops``: the gate is the one the run's own tool calls are refused by
    run_arguments = _owned_run_arguments(port)
    async with _service(tmp_path, clock=_Clock()) as service:
        assert not hasattr(runtime, "agent_stops") and registry.stop_gate is None  # premise: a bare runtime and an ungated registry

        # Golden: the arguments ``_run_reserved`` receives are the same with no gate and with a gate that holds no order.
        with caplog.at_level(logging.INFO):
            caplog.clear()
            assert await executor.run(runtime=runtime, **run_arguments) is RESERVED_OUTCOME
            registry.set_stop_gate(service)
            assert registry.stop_gate is service and service.active() == ()  # premise: a gate with no order in force
            assert await executor.run(runtime=runtime, **run_arguments) is RESERVED_OUTCOME
            unstopped_log = _unstopped_log(caplog, LOGGERS_OF_THE_RUN_ENTRY)
        assert len(reserved.received) == 2 and reserved.received[1] == reserved.received[0]
        assert reserved.received[0]["runtime"] is runtime and reserved.received[0]["agent_id"] == AGENT
        assert len(port.validated) == 2  # premise: the owned-steps check is reached on the unstopped path, so 'not validated' below says something
        assert unstopped_log == []  # the gate adds no INFO or higher line for an agent that is not stopped

        record = (await service.issue_stop(AGENT, reason=REASON)).record
        assert service.stop_for(AGENT) is record and llm.calls == 0  # premise: the order is in force and nothing has used the client
        with pytest.raises(agent_stop.AgentStopped) as refused:
            await executor.run(runtime=runtime, **run_arguments)
        assert refused.value.record.stop_id == record.stop_id
        assert record.stop_id in str(refused.value) and PRIVATE_FRAGMENT not in str(refused.value)  # the order, never the reason
        assert llm.calls == 0  # no model work
        assert len(reserved.received) == 2  # ``_run_reserved`` was not reached
        assert len(port.validated) == 2  # the owned-steps port was not asked to validate
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}

        other = await executor.run(agent_id=OTHER, instructions="You are the Counselor.", task_text="AD-1343: sit in.", runtime=runtime)
        assert other is RESERVED_OUTCOME and reserved.received[-1]["agent_id"] == OTHER  # the order names one agent

        admitted = await executor.run(runtime=runtime, admitted_turn=True, **run_arguments)
        assert admitted is RESERVED_OUTCOME and len(reserved.received) == 4  # the agent's own admitted turn reaches ``_run_reserved``
        assert reserved.received[-1] == reserved.received[0]  # ``admitted_turn`` is consumed by the entry, never forwarded
        assert len(port.validated) == 3  # and its owned-steps check still runs
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}  # the admitted turn is not a refusal


class _StubOutcome(SimpleNamespace):
    """What the stub executor answers: the fields ``DelegateTaskTool`` reads from a finished run."""


def _stub_executor() -> type:
    """A new stand-in for ``WorkItemAgenticExecutor`` on the delegation path that records each construction and answers a fixed outcome."""

    class _Stub:
        built: list[dict[str, Any]] = []

        def __init__(self, **kwargs: Any) -> None:
            type(self).built.append(kwargs)

        async def run(self, **_kwargs: Any) -> _StubOutcome:
            return _StubOutcome(final_text="stub outcome", stopped_reason="complete", total_tokens=1, iterations=1)

    return _Stub


class _BrokerSpy:
    """Test-local effect broker: records every ``bind_delegated_run``; ``on_bind`` runs inside it (the race: an order lands there)."""

    def __init__(self, on_bind: Callable[[], Awaitable[object]] | None = None) -> None:
        self.bound: list[str] = []
        self._on_bind = on_bind

    async def bind_delegated_run(self, *, parent: EffectDispatchContext, child_agent_id: str, child_run_id: str) -> SimpleNamespace:
        self.bound.append(child_agent_id)
        if self._on_bind is not None:
            await self._on_bind()
        return SimpleNamespace(parent_operation_id=parent.operation_id, parent_attempt_id=parent.attempt_id, binding_token="ad1343-binding")


def _dispatch_context() -> EffectDispatchContext:
    """A strict delegation dispatch context as the tool reads it: a handle of the 'delegation' adapter that matches its operation."""
    handle = EffectOperationHandle("ad1343-op", "ad1343-attempt", "delegation", "ad1343-continuation", "unknown", "reconcile")
    permit = EffectPermit("ad1343-op", "ad1343-attempt", "0" * 64, 1, "ad1343-nonce", "ad1343-signature")
    return EffectDispatchContext("ad1343-op", "ad1343-attempt", permit, None, None, handle)


def _delegation_context(budget: DelegationTreeBudget) -> dict[str, Any]:
    """The context a delegating agent's tool call carries: the caller, its tree budget and the strict dispatch context."""
    return {"agent_id": OTHER, "thread_id": THREAD_ID, DELEGATION_TREE_BUDGET_KEY: budget, "_effect_dispatch_context": _dispatch_context()}


def _new_budget() -> DelegationTreeBudget:
    return DelegationTreeBudget(TreeCeilings(max_children=4))


# T31
async def test_a_delegation_to_a_stopped_target_is_refused_not_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    callsigns, agents = _callsign_registry(tmp_path, [
        _Agent(AGENT, "bashir", instructions="You are Dr. Bashir.", agent_type="diagnostician", department="medical", rank="lieutenant"),
        _Agent(OTHER, "ezri"),
    ])
    runtime = _delegation_runtime(tmp_path, cs=callsigns, agent_registry=agents)
    llm = _CountingLLM()
    tool = DelegateTaskTool(runtime=runtime, llm_client=llm, max_depth=1, max_iterations=3, tier="standard")
    broker = _BrokerSpy()
    runtime.effect_broker = broker
    params = {"task": "AD-1343: report in.", "to": BASHIR}
    untouched = TreeUsage(0, 0, 0, 0, 0, 0)

    async with _service(tmp_path, clock=_Clock()) as service:
        runtime.agent_stops = service  # the tool's own check reads this
        runtime.tool_registry.set_stop_gate(service)  # the real run entry (the race) reads this
        assert callsigns.resolve(BASHIR)["agent_id"] == AGENT  # premise: the callsign names the agent the order will name
        assert service.stop_for(AGENT) is None and broker.bound == []

        stub = _stub_executor()
        with caplog.at_level(logging.INFO):
            with monkeypatch.context() as patch:
                patch.setattr("probos.cognitive.agentic_dispatch.WorkItemAgenticExecutor", stub)

                # Golden: nothing stopped. The delegation runs, takes a slot and binds the child, as it always did.
                caplog.clear()
                golden_budget = _new_budget()
                delegated = await tool.invoke(params, _delegation_context(golden_budget))
                golden_log = _unstopped_log(caplog, LOGGERS_OF_THE_DELEGATION)
                assert delegated.error is None and delegated.output["delegated"] is True
                assert delegated.output["result"] == "stub outcome" and len(stub.built) == 1
                assert broker.bound == [AGENT]  # premise: the binding spy is on the production path, so 'not bound' below says something
                assert golden_budget.usage().children_admitted == 1 and golden_budget.usage().in_flight == 0  # premise: a run takes a slot
                assert golden_log == []

                # Stopped: refused before any tree slot, binding or run.
                record = (await service.issue_stop(AGENT, reason=REASON)).record
                budget = _new_budget()
                assert budget.usage() == untouched  # premise: nothing is admitted yet
                stopped = await tool.invoke(params, _delegation_context(budget))
                assert stopped.error is None
                assert stopped.output == {"delegated": False, "reason": "agent_stopped", "stop": record.sender_detail()}
                assert stopped.evidence.status == "not_started"
                assert budget.usage() == untouched  # no tree slot was taken
                assert broker.bound == [AGENT]  # no binding for the stopped target (the golden's one is the only one)
                assert len(stub.built) == 1  # no nested executor was constructed
                assert PRIVATE_FRAGMENT not in json.dumps(stopped.output) and PRIVATE_FRAGMENT not in repr(stopped.evidence)
                assert service.refused_counts(record.stop_id) == {"delegation": 1}
                await service.lift_stop(AGENT, reason=LIFT_REASON)

            # Race: the order lands inside the binding, after the tool's own check; the real run entry refuses the run.
            assert service.stop_for(AGENT) is None  # premise: lifted, so the tool's own check passes
            issued: list[StopRecord] = []

            async def _order_lands() -> None:
                issued.append((await service.issue_stop(AGENT, reason=REASON)).record)

            racing_broker = _BrokerSpy(on_bind=_order_lands)
            runtime.effect_broker = racing_broker
            race_budget = _new_budget()
            caplog.clear()
            raced = await tool.invoke(params, _delegation_context(race_budget))
            assert len(issued) == 1 and racing_broker.bound == [AGENT]  # premise: the order landed in the binding, past the tool's own check
            assert raced.error is None
            assert raced.output == {"delegated": False, "reason": "agent_stopped", "stop": issued[0].sender_detail()}
            assert raced.evidence.status == "not_started"
            assert llm.calls == 0  # the real executor refused before any model work
            assert race_budget.usage().in_flight == 0  # the slot the check admitted was settled
            assert PRIVATE_FRAGMENT not in json.dumps(raced.output)
            assert service.refused_counts(issued[0].stop_id) == {"agentic_run": 1}  # refused by the run entry, not by the tool's own check
            failed = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING and "delegation failed" in r.getMessage()]
            assert failed == []  # a stop is not a fault


class _RegisteringDispatcher(ActionDispatcher):
    """The real in-memory dispatcher, plus a record of every action registered with it."""

    def __init__(self) -> None:
        super().__init__()
        self.registered: list[DispatchedAction] = []

    def register(self, action: DispatchedAction, *args: Any, **kwargs: Any) -> Any:
        self.registered.append(action)
        return super().register(action, *args, **kwargs)


def _action_pipeline(gate: AgentStopService) -> tuple[DmReplyPipeline, Any]:
    """AD-745's pipeline over its runtime (action dispatch enabled, a recording browser tool), with a recording dispatcher and ``gate``."""
    runtime = _build_runtime()
    runtime.action_dispatcher = _RegisteringDispatcher()
    runtime.agent_stops = gate
    return _build_pipeline(runtime, ACTION_REPLY), runtime


# T34
async def test_a_stopped_agents_browser_action_is_neither_registered_nor_run(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    async with _service(tmp_path, clock=_Clock()) as service:
        # Golden: nothing stopped. The tier-1 action is registered once and the browser tool is invoked once, as before.
        free, free_runtime = _action_pipeline(service)
        agent_id = free.ctx.agent_id
        assert service.active() == () and free_runtime.config.browser_tool.action_dispatch_enabled is True  # premise: enabled, nothing stopped
        assert "[ACTION" in free.ctx.response_text  # premise: the reply proposes an action
        with caplog.at_level(logging.INFO):
            caplog.clear()
            await free.step_4e_action_dispatch()
            golden_log = _unstopped_log(caplog, LOGGERS_OF_THE_ACTION)
        assert len(free_runtime.browser_tool.invoked) == 1 and len(free_runtime.action_dispatcher.registered) == 1
        proposed = free_runtime.action_dispatcher.list_for_thread("t-1")
        assert len(proposed) == 1 and proposed[0].status == ActionStatus.EXECUTED  # premise: the action really ran
        assert "[ACTION" not in free.ctx.response_text
        assert golden_log == []

        # Stopped: the markers are stripped, nothing is registered, the browser tool is not invoked, and the refusal is one tool refusal.
        record = (await service.issue_stop(agent_id, reason=REASON)).record
        held, held_runtime = _action_pipeline(service)
        assert held.ctx.agent_id == agent_id and "[ACTION" in held.ctx.response_text  # premise: the same reply from the stopped agent
        await held.step_4e_action_dispatch()
        assert held_runtime.browser_tool.invoked == []
        assert held_runtime.action_dispatcher.registered == []
        assert held_runtime.action_dispatcher.list_for_thread("t-1") == []
        assert "[ACTION" not in held.ctx.response_text and "Looking." in held.ctx.response_text  # the prose stays, the markers go
        assert service.refused_counts(record.stop_id) == {"tool": 1}

        # Lifted: the same reply runs its action again.
        await service.lift_stop(agent_id, reason=LIFT_REASON)
        again, again_runtime = _action_pipeline(service)
        await again.step_4e_action_dispatch()
        assert len(again_runtime.browser_tool.invoked) == 1 and len(again_runtime.action_dispatcher.registered) == 1
