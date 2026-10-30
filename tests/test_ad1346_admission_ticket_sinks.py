"""AD-1346 M3d3a (#1604): the work ticket's sink checks at the tool sink and the model gateway, in shadow.

``probos.admission.seam.check_at`` hands one effect point's call to ``AdmissionService.check_ticket``, which asks the
``TicketRegistry`` about the ticket ``probos.admission.carrier.CURRENT_TICKET`` holds for that effect (``tool`` or
``model_call``); the registry counts the finding in its tally and the sink gets None. ``ToolRegistry.check_and_invoke``
calls it after its shadow statement and before today's stop answer, and ``OpenAICompatibleClient.complete`` as its
first statement. These tests drive it over a real ``IdentityService`` and a real ``AgentStopService`` under ``tmp_path``,
a ``TicketRegistry`` on a clock the test moves, a real ``ToolRegistry``, the real gateway with the request it would send
replaced by a canned answer, and the real run entry with a scripted body in place of the agentic loop; SK9 boots twice.

- SK1  the service refuses a ``loop`` that is not an event loop; with no registry, or once closed, a sink check
       counts nothing; with one it counts the registry's finding for what the carrier holds: ``ticket_missing``
       with nothing carried, ``ticket_live`` for a live ticket (with no principal compared when the presented id is
       None), ``ticket_principal_mismatch`` for another agent's id and ``ticket_expired`` once the hold ended; it
       returns None.
- SK2  ``check_at`` passes over None, a plain object and a look-alike, and forwards the effect and the presented id to
       an exact ``AdmissionService``.
- SK3  a sink check whose registry raises is counted in ``failures`` and logged at WARNING and then DEBUG, a logging
       call that raises is passed over, no finding is counted and the sink gets None (#1604 property 6 at the service).
- SK4  the thread rule (D128): a sink on another thread, or in a worker running a loop of its own as
       ``consultation/llm_decomposer.py`` does, reads the carrier there and hands the check to the service's loop, which
       counts it in ``off_loop_checks``; the registry's checks run on that loop's thread; a check handed over and then
       closed is not run; a hand-off to a closed loop raises nothing, runs no check and counts no failure.
- SK5  #1604 property 5, the run, in memory: inside the real run entry's hold, the next model call and tool call after
       a Captain's stop on the run's agent count ``ticket_revoked``, with the stop's id on the entry; before the stop
       both count ``ticket_live`` and today's tool check admits the call.
- SK6  #1604 property 5, the delegated child, in memory: a run the first run delegates holds a child of its ticket;
       after a Captain's stop on the delegating agent, the child's next model call and tool call count
       ``ticket_revoked`` while today's tool check still admits the child's call; a root run of a third agent afterwards
       counts ``ticket_live``.
- SK7  the sink census: in ``src``, ``check_at`` is called in exactly the two sinks, once each, with the sink's own
       service attribute, effect constant and presented id; at the tool sink it is the statement right after the
       shadow statement and right before ``if stopped is not None:``, at the gateway the first statement after the
       docstring.
- SK8  in ``src``, the classes whose base is named ``BaseLLMClient`` are ``OpenAICompatibleClient`` and
       ``MockLLMClient``, no class's base is named ``OpenAICompatibleClient``, ``_complete_inner`` is called only in
       ``OpenAICompatibleClient.complete``, and ``_call_openai`` and ``_call_ollama_native`` only inside
       ``OpenAICompatibleClient``.
- SK9  the wiring: on a boot whose LLM client is an ``OpenAICompatibleClient``, the runtime builds the service with its
       running loop and hands the service to the gateway, and a model call it makes then counts a ``model_call``
       finding; with ``admission.shadow_enabled`` false the runtime hands the gateway None.
- SK10 #1604 property 12 at the sinks, and property 6: the tool sink and the gateway answer byte for byte the same with
       the service and without it, with nothing carried, with a live ticket, while the registry's clock raises, and
       after a Captain's stop.

Each boot uses ``SystemConfig()`` with the naming ceremony, the proactive loop and QA turned off, as
``tests/test_ad1346_admission_ticket_issue.py`` does, and an ``OpenAICompatibleClient`` subclass that starts no health
probe and answers each request with a canned response in place of sending it. Besides each test's own loop, SK4
creates two event loops (one through ``asyncio.run`` in a worker thread, and one it closes at once) and starts worker
threads.
"""

from __future__ import annotations

import ast
import asyncio
import concurrent.futures
import dataclasses
import json
import logging
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

import probos
from probos.admission import AdmissionService
from probos.admission import service as service_module
from probos.admission.carrier import CURRENT_TICKET
from probos.admission.checks import resolve_principal
from probos.admission.seam import check_at
from probos.admission.taxonomy import SEAM_MODEL_CALL
from probos.admission.tickets import TicketFinding, TicketRegistry
from probos.agent_stop import SEAM_TOOL, AgentStopService
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.config import SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.identity import AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.runtime import ProbOSRuntime
from probos.substrate.registry import AgentRegistry
from probos.tools.registry import ToolRegistry
from probos.types import LLMRequest, LLMResponse
from tests.fixtures.ad1343_seam_census import calls, census, function

INSTANCE_ID = "ad1346-m3d3a-ship"
VESSEL_NAME = "Ad1346m3d3a"
AGENT_A = "ad1346-m3d3a-agent-a"
AGENT_B = "ad1346-m3d3a-agent-b"
AGENT_C = "ad1346-m3d3a-agent-c"
_ABSENT = "ad1346_m3d3a_absent"  # a tool id no registry holds: the tool sink answers "not found" and runs nothing
_NOT_FOUND = f"Tool '{_ABSENT}' not found"
_SRC = Path(probos.__file__).resolve().parent
_LLM = "src/probos/cognitive/llm_client.py"
#: (file, sink) -> (the effect constant its check names, the expression it presents as the principal).
_SINK_SITES: dict[tuple[str, str], tuple[str, str]] = {
    ("src/probos/tools/registry.py", "ToolRegistry.check_and_invoke"): ("SEAM_TOOL", "agent_id"),
    (_LLM, "OpenAICompatibleClient.complete"): ("SEAM_MODEL_CALL", "getattr(request, 'agent_id', None)"),
}


class _Clock:
    """A monotonic clock that only the test moves, and that raises while ``boom`` is set."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.boom = False

    def __call__(self) -> float:
        if self.boom:
            raise RuntimeError("INJECTED clock failure")
        return self.now


class _ThreadRecordingRegistry(TicketRegistry):
    """A ticket registry that records the thread each ``check`` runs on."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.threads: list[int] = []

    def check(self, ticket: object, *, effect: str, presented_key: str = "") -> TicketFinding:
        self.threads.append(threading.get_ident())
        return super().check(ticket, effect=effect, presented_key=presented_key)


class _OfflineGateway(OpenAICompatibleClient):
    """The model gateway with no endpoint: it starts no health probe and answers with a canned response where it would
    send the request."""

    async def start_health_probe(self, interval_seconds: float = 30.0, emit_fn: Any = None) -> None:
        return None

    async def _complete_inner(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(content="ad1346-m3d3a", model="m", tier="standard")


class _ScriptedRun(WorkItemAgenticExecutor):
    """The real run entry (its stop check, shadow statement and hold) over a scripted body in place of the agentic loop."""

    def __init__(self, bodies: dict[str, Callable[[dict[str, Any]], Awaitable[str]]]) -> None:
        super().__init__(llm_client=None)
        self.bodies = bodies

    async def _run_reserved(self, **arguments: Any) -> Any:
        return await self.bodies[arguments["agent_id"]](arguments)


@pytest_asyncio.fixture
async def identity_registry(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    """A real identity registry, started and commissioned as tests/test_ad1346_admission_service.py does."""
    reg = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await reg.start()
        await reg.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        yield reg
    finally:
        await reg.stop()


@pytest.fixture
def identities(tmp_path: Path, identity_registry: AgentIdentityRegistry) -> IdentityService:
    """The real facade over the registry and a ``CallsignRegistry`` bound to an empty ``AgentRegistry``."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "surgeon.yaml").write_text("callsign: Meridian\n", encoding="utf-8")
    callsigns = CallsignRegistry()
    callsigns.load_from_profiles(str(profiles))
    callsigns.bind_registry(AgentRegistry())
    return IdentityService(identity_registry, callsigns)


@pytest_asyncio.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    """A real Captain's stop record."""
    record = AgentStopService(data_dir=tmp_path / "stops")
    await record.start()
    try:
        yield record
    finally:
        await record.stop()


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def tickets(stops: AgentStopService, clock: _Clock) -> TicketRegistry:
    """A production-shaped registry at the default delegation depth of 1, on the test's clock."""
    return TicketRegistry(stops, max_depth=1, clock=clock)


@pytest.fixture
def gate(identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry) -> AdmissionService:
    """A service built with no loop, so it checks in place."""
    return AdmissionService(identities, stops, tickets=tickets)


async def _settle() -> None:
    """Let the loop run the checks a sink elsewhere handed to it."""
    for _ in range(3):
        await asyncio.sleep(0)


def _tools(stops: AgentStopService, service: AdmissionService | None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.set_stop_gate(stops)
    registry.set_admission(service)
    return registry


def _gateway(service: AdmissionService | None) -> _OfflineGateway:
    client = _OfflineGateway()
    client.set_admission(service)
    return client


def _runtime(tools: ToolRegistry, service: AdmissionService) -> SimpleNamespace:
    """A runtime holding the tool registry (its stop gate) and the admission service; the run entry's other reads of a
    runtime (``getattr`` with a default) find nothing."""
    return SimpleNamespace(tool_registry=tools, admission_service=service)


async def _run(runner: _ScriptedRun, runtime: SimpleNamespace, agent_id: str, extra: dict[str, Any] | None = None) -> Any:
    """The real run entry: its stop check, shadow statement and hold, then the scripted body under the hold."""
    return await runner.run(agent_id=agent_id, instructions="i", task_text="t", runtime=runtime, extra_context=extra)


def _config(*, shadow_enabled: bool) -> SystemConfig:
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    config.admission.shadow_enabled = shadow_enabled
    return config


async def _boot(tmp_path: Path, name: str, *, shadow_enabled: bool) -> ProbOSRuntime:
    runtime = ProbOSRuntime(config=_config(shadow_enabled=shadow_enabled), data_dir=tmp_path / name, llm_client=_OfflineGateway())
    await runtime.start()
    return runtime


def _src_classes_and_calls(callees: frozenset[str]) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str]]]:
    """In ``src/probos``: (file, class, base) for each class whose base, by simple name, is ``BaseLLMClient`` or
    ``OpenAICompatibleClient``; and (file, enclosing qualified name, callee) for each call of a name in ``callees``."""
    bases: set[tuple[str, str, str]] = set()
    found: set[tuple[str, str, str]] = set()
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC.parents[1]).as_posix()
        text = path.read_text(encoding="utf-8")
        if "LLMClient" not in text and "OpenAICompatibleClient" not in text and not any(c in text for c in callees):
            continue

        def visit(node: ast.AST, scope: tuple[str, ...], rel: str = rel) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    for base in child.bases:
                        name = ast.unparse(base).split(".")[-1]
                        if name in ("BaseLLMClient", "OpenAICompatibleClient"):
                            bases.add((rel, child.name, name))
                if isinstance(child, ast.Call):
                    func = child.func
                    callee = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
                    if callee in callees:
                        found.add((rel, ".".join(scope), callee))
                named = isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                visit(child, (*scope, child.name) if named else scope)

        visit(ast.parse(text, filename=rel), ())
    return bases, found


async def test_a_sink_check_counts_the_registrys_finding_for_what_the_carrier_holds_and_returns_none(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, gate: AdmissionService,
) -> None:
    """SK1 (kills SKX-1, SKX-5, SKX-6, SKX-7, SKX-10): no registry, or a closed service, counts nothing; each of the
    registry's findings for nothing carried, a live ticket, another agent's id and an ended ticket is counted once."""
    with pytest.raises(TypeError, match="event loop"):
        AdmissionService(identities, stops, loop=object())  # type: ignore[arg-type]
    assert resolve_principal(AGENT_A, identities).key == AGENT_A, "premise: the test's ids do not resolve; each is its own key"
    bare = AdmissionService(identities, stops)
    assert bare.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A) is None
    assert bare.failures == 0 and tickets.tally() == {}
    assert gate.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A) is None
    assert gate.check_ticket(effect=SEAM_MODEL_CALL, presented_id=None) is None
    held = gate.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    assert held.ticket is not None, "premise: the registry issued the ticket"
    try:
        gate.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A)
        gate.check_ticket(effect=SEAM_MODEL_CALL, presented_id=None)
        gate.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_B)
    finally:
        held.end()
    token = CURRENT_TICKET.set(held.ticket)
    try:
        gate.check_ticket(effect=SEAM_MODEL_CALL, presented_id=AGENT_A)
    finally:
        CURRENT_TICKET.reset(token)
    expected = {
        ("tool", "ticket_missing"): 1, ("model_call", "ticket_missing"): 1, ("issue", "ticket_issued"): 1,
        ("tool", "ticket_live"): 1, ("model_call", "ticket_live"): 1, ("tool", "ticket_principal_mismatch"): 1,
        ("model_call", "ticket_expired"): 1,
    }
    assert tickets.tally() == expected
    gate.close()
    assert gate.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A) is None
    assert tickets.tally() == expected, "a closed service checks nothing"
    assert gate.failures == 0 and gate.off_loop_checks() == {}


async def test_check_at_calls_only_an_exact_service_and_forwards_the_effect_and_the_presented_id(
    gate: AdmissionService, tickets: TicketRegistry,
) -> None:
    """SK2 (kills SKX-11, SKX-17)."""

    class _LookAlike:
        calls = 0

        def check_ticket(self, **kwargs: Any) -> None:
            _LookAlike.calls += 1

    for other in (None, object(), _LookAlike()):
        assert check_at(other, effect=SEAM_TOOL, presented_id=AGENT_A) is None
    assert _LookAlike.calls == 0 and tickets.tally() == {}
    assert check_at(gate, effect=SEAM_MODEL_CALL, presented_id=AGENT_A) is None
    assert tickets.tally() == {("model_call", "ticket_missing"): 1}
    held = gate.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    assert held.ticket is not None, "premise: the registry issued the ticket"
    try:
        assert check_at(gate, effect=SEAM_TOOL, presented_id=AGENT_B) is None
    finally:
        held.end()
    assert tickets.tally() == {
        ("model_call", "ticket_missing"): 1, ("issue", "ticket_issued"): 1, ("tool", "ticket_principal_mismatch"): 1,
    }, "check_at forwards the presented id: another agent's id is compared with the ticket's principal"


async def test_a_sink_check_that_raises_is_counted_and_logged_and_the_sink_gets_none(
    gate: AdmissionService, tickets: TicketRegistry, clock: _Clock, caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SK3 (kills SKX-9): #1604 property 6 at the service."""
    held = gate.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    assert held.ticket is not None, "premise: the registry issued the ticket"
    try:
        clock.boom = True
        with caplog.at_level(logging.DEBUG, logger="probos.admission.service"):
            assert gate.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A) is None
            assert gate.check_ticket(effect=SEAM_MODEL_CALL, presented_id=AGENT_A) is None
        levels = [r.levelno for r in caplog.records if "AD-1346 M3d3a" in r.getMessage()]
        assert levels == [logging.WARNING, logging.DEBUG] and gate.failures == 2

        def _raise(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("INJECTED logging failure")

        monkeypatch.setattr(service_module.logger, "log", _raise)
        assert gate.check_ticket(effect=SEAM_TOOL, presented_id=AGENT_A) is None
        assert gate.failures == 3
    finally:
        clock.boom = False
        monkeypatch.undo()
        held.end()
    assert tickets.tally() == {("issue", "ticket_issued"): 1}, "a check that raised counted no finding"


async def test_a_sink_off_the_services_loop_hands_its_check_to_that_loop(
    identities: IdentityService, stops: AgentStopService, clock: _Clock,
) -> None:
    """SK4 (kills SKX-2, SKX-3, SKX-4, SKX-5, SKX-8): the thread rule (D128)."""
    loop_thread = threading.get_ident()
    registry = _ThreadRecordingRegistry(stops, max_depth=1, clock=clock)
    service = AdmissionService(identities, stops, tickets=registry, loop=asyncio.get_running_loop())
    held = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
    assert held.ticket is not None, "premise: the registry issued the ticket"

    async def _model_call_in_a_worker_loop() -> None:
        check_at(service, effect=SEAM_MODEL_CALL, presented_id=AGENT_A)

    try:
        await asyncio.to_thread(check_at, service, effect=SEAM_TOOL, presented_id=AGENT_A)
        await _settle()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            await asyncio.wrap_future(pool.submit(lambda: asyncio.run(_model_call_in_a_worker_loop())))
        await _settle()
        assert check_at(service, effect=SEAM_TOOL, presented_id=AGENT_A) is None
    finally:
        held.end()
    assert registry.threads == [loop_thread] * 3, "each check ran on the service's loop's thread"
    assert registry.tally() == {
        ("issue", "ticket_issued"): 1, ("tool", "ticket_live"): 2, ("model_call", "ticket_missing"): 1,
    }, "asyncio.to_thread copies the caller's context; the submitted worker's check carried no ticket"
    assert service.off_loop_checks() == {"tool": 1, "model_call": 1}, "the check made on the loop is not counted as handed over"
    worker = threading.Thread(target=check_at, args=(service,), kwargs={"effect": SEAM_TOOL, "presented_id": AGENT_A})
    worker.start()
    worker.join()
    service.close()
    await _settle()
    assert registry.threads == [loop_thread] * 3 and service.off_loop_checks() == {"tool": 1, "model_call": 1}, (
        "a check handed over before close is not run after it"
    )
    closed = asyncio.new_event_loop()
    closed.close()
    orphan = AdmissionService(identities, stops, tickets=registry, loop=closed)
    assert check_at(orphan, effect=SEAM_TOOL, presented_id=AGENT_A) is None
    assert orphan.failures == 0 and service.failures == 0 and registry.threads == [loop_thread] * 3


async def test_a_captains_stop_reaches_the_next_model_and_tool_call_of_an_in_flight_run(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry,
) -> None:
    """SK5 (kills SKX-12, SKX-13): #1604 property 5 for the run's own calls, counted in memory."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    tools = _tools(stops, service)
    gateway = _gateway(service)
    seen: dict[str, Any] = {}

    async def body(arguments: dict[str, Any]) -> str:
        seen["ticket"] = CURRENT_TICKET.get()
        await gateway.complete(LLMRequest(prompt="p", agent_id=AGENT_A))
        seen["tool_before"] = await tools.check_and_invoke(AGENT_A, _ABSENT, {})
        seen["tally_before"] = tickets.tally()
        issued = await stops.issue_stop(AGENT_A, reason="ad1346-m3d3a: the Captain stops a run in flight")
        seen["stop_id"] = issued.record.stop_id
        await gateway.complete(LLMRequest(prompt="p", agent_id=AGENT_A))
        seen["tool_after"] = await tools.check_and_invoke(AGENT_A, _ABSENT, {})
        return "ran"

    assert await _run(_ScriptedRun({AGENT_A: body}), _runtime(tools, service), AGENT_A) == "ran"
    assert seen["ticket"] is not None, "premise: the run entry's hold carried the run's ticket into its body"
    assert seen["tally_before"] == {
        ("issue", "ticket_issued"): 1, ("model_call", "ticket_live"): 1, ("tool", "ticket_live"): 1,
    }
    assert seen["tool_before"].error == _NOT_FOUND, "premise: before the stop today's check admits the call"
    assert tickets.tally() == {**seen["tally_before"], ("model_call", "ticket_revoked"): 1, ("tool", "ticket_revoked"): 1}
    assert seen["tool_after"].error.startswith(f"Tool '{_ABSENT}' was not run."), "today's check refuses the stopped agent"
    entry = tickets.entry(seen["ticket"])
    assert entry is not None and entry.stop_id == seen["stop_id"] and entry.revoked_at is not None
    assert service.failures == 0


async def test_a_captains_stop_reaches_a_delegated_childs_next_calls_and_not_a_root_of_another_agent(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry,
) -> None:
    """SK6 (kills SKX-12, SKX-13 too): #1604 property 5 for a delegated child, counted in memory, with a root run of
    another agent as the control that does not differ."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())
    tools = _tools(stops, service)
    gateway = _gateway(service)
    runtime = _runtime(tools, service)
    seen: dict[str, Any] = {}

    async def parent(arguments: dict[str, Any]) -> str:
        seen["parent"] = CURRENT_TICKET.get()
        return await _run(runner, runtime, AGENT_B, {"_delegation_depth": 1})

    async def child(arguments: dict[str, Any]) -> str:
        seen["child"] = CURRENT_TICKET.get()
        await gateway.complete(LLMRequest(prompt="p", agent_id=AGENT_B))
        seen["tool_before"] = await tools.check_and_invoke(AGENT_B, _ABSENT, {})
        seen["tally_before"] = tickets.tally()
        issued = await stops.issue_stop(AGENT_A, reason="ad1346-m3d3a: the Captain stops the delegating agent")
        seen["stop_id"] = issued.record.stop_id
        await gateway.complete(LLMRequest(prompt="p", agent_id=AGENT_B))
        seen["tool_after"] = await tools.check_and_invoke(AGENT_B, _ABSENT, {})
        return "child ran"

    async def other(arguments: dict[str, Any]) -> str:
        await gateway.complete(LLMRequest(prompt="p", agent_id=AGENT_C))
        seen["other_tool"] = await tools.check_and_invoke(AGENT_C, _ABSENT, {})
        return "other ran"

    runner = _ScriptedRun({AGENT_A: parent, AGENT_B: child, AGENT_C: other})
    assert await _run(runner, runtime, AGENT_A) == "child ran"
    after_child = tickets.tally()
    assert await _run(runner, runtime, AGENT_C) == "other ran"
    parent_entry, child_entry = tickets.entry(seen["parent"]), tickets.entry(seen["child"])
    assert parent_entry is not None and child_entry is not None
    assert child_entry.parent_id == parent_entry.ticket_id and child_entry.depth == 1, (
        "premise: the delegated run holds a child of the delegating run's ticket"
    )
    assert seen["tally_before"] == {
        ("issue", "ticket_issued"): 2, ("model_call", "ticket_live"): 1, ("tool", "ticket_live"): 1,
    }
    assert seen["tool_before"].error == _NOT_FOUND, "premise: before the stop today's check admits the child's call"
    assert after_child == {**seen["tally_before"], ("model_call", "ticket_revoked"): 1, ("tool", "ticket_revoked"): 1}
    assert seen["tool_after"].error == _NOT_FOUND and stops.stop_for(AGENT_B) is None, (
        "today's check admits the child's call: its own agent is not stopped"
    )
    assert child_entry.stop_id == seen["stop_id"] and parent_entry.revoked_at is not None
    assert tickets.tally() == {
        **after_child, ("issue", "ticket_issued"): 3, ("model_call", "ticket_live"): 2, ("tool", "ticket_live"): 2,
    }, "a root run of another agent is not reached by the stop"
    assert seen["other_tool"].error == _NOT_FOUND and service.failures == 0


def test_the_sink_check_is_called_once_in_each_of_the_two_sinks_in_its_place() -> None:
    """SK7: the sink census, in the manner of 9b, 9c and I10."""
    found = {(c.file, c.function) for c in census() if c.callee == "check_at"}
    assert found == set(_SINK_SITES), sorted(found)
    for (rel, qualname), (effect, presented) in _SINK_SITES.items():
        fn = function(rel, qualname)
        sinks = [n for n in ast.walk(fn) if calls("check_at")(n)]
        assert len(sinks) == 1, (qualname, len(sinks))
        call = sinks[0]
        assert [ast.unparse(a) for a in call.args] == ["self._admission"], qualname
        assert {k.arg: ast.unparse(k.value) for k in call.keywords} == {"effect": effect, "presented_id": presented}, qualname
        index = next((i for i, stmt in enumerate(fn.body) if isinstance(stmt, ast.Expr) and stmt.value is call), None)
        assert index is not None, (qualname, "the sink check is a statement of the function's own body")
        if qualname == "ToolRegistry.check_and_invoke":
            before, after = fn.body[index - 1], fn.body[index + 1]
            assert isinstance(before, ast.Expr) and calls("shadow_at")(before.value), qualname
            assert isinstance(after, ast.If) and ast.unparse(after.test) == "stopped is not None", qualname
        else:
            docstring = fn.body[0]
            assert index == 1 and isinstance(docstring, ast.Expr) and isinstance(docstring.value, ast.Constant), qualname


def test_in_src_the_gateway_alone_calls_the_completion_internals_and_the_model_clients_are_the_two_known() -> None:
    """SK8: the facts that make the gateway's first statement a check of every completion an ``OpenAICompatibleClient``
    sends through ``complete``."""
    bases, found = _src_classes_and_calls(frozenset({"_complete_inner", "_call_openai", "_call_ollama_native"}))
    assert bases == {(_LLM, "OpenAICompatibleClient", "BaseLLMClient"), (_LLM, "MockLLMClient", "BaseLLMClient")}, sorted(bases)
    inner = {(rel, fn, callee) for rel, fn, callee in found if callee == "_complete_inner"}
    assert inner == {(_LLM, "OpenAICompatibleClient.complete", "_complete_inner")}, sorted(inner)
    transports = {(rel, fn.split(".")[0], callee) for rel, fn, callee in found if callee != "_complete_inner"}
    assert transports == {
        (_LLM, "OpenAICompatibleClient", "_call_openai"), (_LLM, "OpenAICompatibleClient", "_call_ollama_native"),
    }, sorted(found)


async def test_the_runtime_gives_the_service_its_loop_and_hands_it_to_the_model_gateway(tmp_path: Path) -> None:
    """SK9 (kills SKX-14, SKX-15, SKX-16): the wiring, on two boots."""
    on = await _boot(tmp_path, "on", shadow_enabled=True)
    try:
        service = on.admission_service
        assert service is not None and isinstance(on.llm_client, _OfflineGateway), "premise: the boot built the service"
        assert vars(service)["_loop"] is asyncio.get_running_loop()
        assert vars(on.llm_client)["_admission"] is service
        registry = vars(service)["_tickets"]
        before = registry.tally().get(("model_call", "ticket_missing"), 0)
        await on.llm_client.complete(LLMRequest(prompt="ad1346-m3d3a"))
        assert registry.tally().get(("model_call", "ticket_missing"), 0) > before
    finally:
        await on.stop()
    off = await _boot(tmp_path, "off", shadow_enabled=False)
    try:
        assert off.admission_service is None and vars(off.llm_client)["_admission"] is None
    finally:
        await off.stop()


async def test_with_and_without_the_service_the_sinks_answer_byte_identically(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, clock: _Clock,
) -> None:
    """SK10: #1604 property 12 at the two sinks, and property 6: a check that raises changes no answer."""
    service = AdmissionService(identities, stops, tickets=tickets, loop=asyncio.get_running_loop())

    async def drive(with_service: bool) -> str:
        tools = _tools(stops, service if with_service else None)
        gateway = _gateway(service if with_service else None)
        answers: list[dict[str, Any]] = []

        async def both() -> None:
            answers.append(dataclasses.asdict(await tools.check_and_invoke(AGENT_A, _ABSENT, {})))
            answers.append(dataclasses.asdict(await gateway.complete(LLMRequest(prompt="p", agent_id=AGENT_A))))

        await both()
        held = service.hold(presented_id=AGENT_A, work_kind="agentic_run", seam="agentic_run", child=False)
        try:
            await both()
            clock.boom = True
            try:
                await both()
            finally:
                clock.boom = False
        finally:
            held.end()
        return json.dumps(answers, sort_keys=True, default=repr)

    first = (await drive(True), await drive(False))
    await stops.issue_stop(AGENT_A, reason="ad1346-m3d3a: the golden test's stop")
    second = (await drive(True), await drive(False))
    assert first[0] == first[1] and second[0] == second[1]
    assert first[0] != second[0], "premise: the stop changes today's answer, so the comparison can see a difference"
    assert ("tool", "ticket_revoked") in tickets.tally() and service.failures == 4, (
        "premise: with the service the sinks checked, saw the stop and counted each raising check"
    )
