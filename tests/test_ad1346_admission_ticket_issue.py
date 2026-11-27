"""AD-1346 M3d2 (#1604): the work ticket each admitted entry holds, its carrier, and the switch's golden test.

``AdmissionService.hold``, reached through ``probos.admission.seam.hold_at``, issues the ticket of one unit of work an
entry's own stop check admitted and puts it in ``probos.admission.carrier.CURRENT_TICKET``. These tests drive it over
a real ``IdentityService`` and a real ``AgentStopService`` under ``tmp_path`` and a
``TicketRegistry`` on a clock the test moves, and the three entries on real boots:

- I1  the service takes a ``TicketRegistry`` or None; without one, or once closed, ``hold`` returns ``NO_HOLD``; an
      empty registry, which is falsy, still issues.
- I2  ``hold`` issues a root keyed on the slot a presented DID resolves to, with both effect points in scope and no
      ceiling, and the carrier holds it; ``end`` puts back the ticket the carrier held before and ends the new one.
- I3  a hold with ``child=True`` under a carried ticket issues a child one level deeper; with ``child=True`` and nothing
      carried, or with ``child=False`` at each of the three work kinds, it issues a root.
- I4  an issue the registry refuses (too deep, or under a parent whose work ended) leaves the unit with None in the
      carrier, is counted in the registry's tally and adds no entry; its ``end`` puts back what was carried.
- I5  a hold whose issue raises returns ``NO_HOLD``, leaves the carrier as it was, is counted in ``failures`` and logged
      at WARNING and then DEBUG, and a logging call that raises is passed over.
- I6  ``end`` raises nothing when its token was already used, when it runs in another context or when the registry's
      clock raises during the release; ``NO_HOLD.end()`` leaves the carrier as it was.
- I7  ``hold_at`` returns ``NO_HOLD`` for None, a look-alike and any other object, and forwards the unit's work kind
      and seam to an exact ``AdmissionService``.
- I8  on a boot whose delegation depth is 2: the runtime builds the registry over its stop record with that depth; the
      intent entry's work holds a root keyed on the agent; inside it a delegated run holds a child of it, a run that is
      not delegated and a consultation hold roots, and each entry's end puts the intent's ticket back; each ticket ends
      when its entry returns, raises or is cancelled, and the carrier is back to None.
- I9  #1604 property 12 at the issue points: two boots, ``admission.shadow_enabled`` true and then false, answer an
      admitted intent, an admitted consultation, an admitted run and a delegated run under a carried ticket the
      registry never issued byte for byte once the agent's id is replaced; the first boot issued at least three tickets
      during the drive and refused the unknown parent once.
- I10 the census: ``hold_at`` is called in exactly the three entries, once each, after their last shadow statement with
      no await between, with the shadow statement's work kind, the entry's seam constant and its ``child`` source, and
      each entry's last statement is a ``try`` whose ``finally`` is that hold's ``end()`` alone.
- I11 in ``src`` only ``AdmissionService.hold`` sets the carrier, only it and, from AD-1346 M3d3a, the sink check
      ``AdmissionService.check_ticket`` read it, only ``TicketHold.end`` resets it, and only ``carrier.py`` and
      ``service.py`` name it.

Each boot uses ``SystemConfig()`` with the naming ceremony, the proactive loop and QA turned off, as
``tests/test_ad1346_admission_shadow_seams.py`` does, and ``MockLLMClient``.
"""

from __future__ import annotations

import ast
import asyncio
import contextvars
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

import probos
from probos.admission import AdmissionService
from probos.admission import service as service_module
from probos.admission.carrier import CURRENT_TICKET, NO_HOLD, TicketHold
from probos.admission.seam import hold_at
from probos.admission.tickets import TICKET_EFFECTS, TicketBudget, TicketRegistry, TicketScope, WorkTicket
from probos.agent_stop import SEAM_TOOL, AgentStopService
from probos.cognitive import agentic_dispatch
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.consultation import ConsultationRequest
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.crew_utils import is_crew_agent
from probos.identity import AgentBirthCertificate, AgentIdentityRegistry
from probos.identity_service import IdentityService
from probos.runtime import ProbOSRuntime
from probos.substrate.registry import AgentRegistry
from probos.types import IntentMessage
from probos.work_item_steps import OwnedStepsError
from tests.fixtures.ad1343_seam_census import calls, census, function
from tests.fixtures.ad1343_seam_registry import SHADOW_SITES

INSTANCE_ID = "ad1346-m3d2-ship"
VESSEL_NAME = "Ad1346m3d2"
SURGEON_SLOT = "surgeon_medical_surgeon_0_b2321292"
COUNSELOR_SLOT = "counselor_counselor_0_67c601cb"
_PROBE = "ad1346_m3d2_probe"  # an intent no agent handles: an admitted agent self-deselects before any model work
_UNHELD = WorkTicket("0" * 32)  # a well-formed id the registry never issued
_SCOPE = TicketScope(frozenset(TICKET_EFFECTS))
_SRC = Path(probos.__file__).resolve().parent
#: (file, entry) -> (its stop check's callee, the seam constant its hold names, the source of its ``child`` argument).
_HOLD_SITES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_intent"): ("refusal", "SEAM_INTENT", "False"),
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_consultation_request"): (
        "refusal", "SEAM_CONSULTATION", "False",
    ),
    ("src/probos/cognitive/agentic_dispatch.py", "WorkItemAgenticExecutor.run"): (
        "refuse_new_run", "SEAM_AGENTIC_RUN", "type(extra_context) is dict and '_delegation_depth' in extra_context",
    ),
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


class _Halt(Exception):
    """Raised by the run entry's patched fault-observer lookup, inside the run's ``try``, to end the run there."""


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
    return AdmissionService(identities, stops, tickets=tickets)


async def _certify(reg: AgentIdentityRegistry) -> AgentBirthCertificate:
    return await reg.resolve_or_issue(
        slot_id=SURGEON_SLOT, agent_type="surgeon", callsign="Surgeon", instance_id=INSTANCE_ID,
        vessel_name=VESSEL_NAME, department="medical", post_id="surgeon", baseline_version="v1",
    )


def _hold(
    gate: AdmissionService, presented_id: str = SURGEON_SLOT, *, kind: str = "agentic_run", child: bool = False,
) -> TicketHold:
    """A hold for one unit of ``kind``; each of the three work kinds is also its seam's name."""
    return gate.hold(presented_id=presented_id, work_kind=kind, seam=kind, child=child)


def _config(*, shadow_enabled: bool = True, delegation_max_depth: int = 1) -> SystemConfig:
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    config.admission.shadow_enabled = shadow_enabled
    config.agentic_tools.delegation_max_depth = delegation_max_depth
    return config


async def _boot(tmp_path: Path, name: str, **settings: Any) -> ProbOSRuntime:
    runtime = ProbOSRuntime(config=_config(**settings), data_dir=tmp_path / name, llm_client=MockLLMClient())
    await runtime.start()
    return runtime


def _certified_crew(rt: ProbOSRuntime) -> CognitiveAgent:
    crew = next(
        (
            a for a in rt.registry.all()
            if isinstance(a, CognitiveAgent) and is_crew_agent(a, rt.ontology)
            and getattr(rt.identity_service.resolve(a.id), "did", "")
        ),
        None,
    )
    assert crew is not None, "premise: the boot has a certified crew agent"
    return crew


async def _run_entry(runner: WorkItemAgenticExecutor, rt: ProbOSRuntime, agent_id: str, extra: dict[str, Any] | None) -> list[str]:
    """The run entry's answer: the owned-steps binding error the deliberately incomplete binding raises inside the run's
    ``try``, after its check and its hold and before any run work."""
    try:
        await runner.run(
            agent_id=agent_id, instructions="i", task_text="t", runtime=rt, extra_context=extra,
            owned_steps_execution_port=object(),
        )
    except OwnedStepsError as exc:
        return [type(exc).__name__, str(exc)]
    raise AssertionError("premise: the run entry answers before any run starts")


async def _drive_issue_points(rt: ProbOSRuntime) -> str:
    """The three entries' admitted paths, and a delegated run under a carried ticket the registry never issued: their
    answers and the carrier's state, as JSON with the agent's id replaced."""
    crew = _certified_crew(rt)
    runner = WorkItemAgenticExecutor(llm_client=rt.llm_client)
    answers: dict[str, Any] = {}
    answers["intent"] = await crew.handle_intent(IntentMessage(intent=_PROBE, target_agent_id=crew.id))
    reply = await crew.handle_consultation_request(
        ConsultationRequest(
            request_id="ad1346-m3d2", requester_id="ad1346-m3d2", topic="t", question="q", target_agent_id=crew.id,
        )
    )
    answers["consultation"] = [
        reply.request_id, reply.responder_id, reply.responder_callsign, reply.answer, reply.confidence,
        reply.reasoning_summary,
    ]
    answers["run"] = await _run_entry(runner, rt, crew.id, None)
    token = CURRENT_TICKET.set(_UNHELD)
    try:
        answers["delegated_run"] = await _run_entry(runner, rt, crew.id, {"_delegation_depth": 1})
        answers["carried_ticket_kept"] = CURRENT_TICKET.get() == _UNHELD
    finally:
        CURRENT_TICKET.reset(token)
    answers["carrier_after"] = repr(CURRENT_TICKET.get())
    return json.dumps(answers, sort_keys=True, default=repr).replace(crew.id, "<agent>")


def _carrier_calls(tree: ast.Module, rel: str) -> set[tuple[str, str, str]]:
    """(file, enclosing qualified name, method) for each call of a ``CURRENT_TICKET`` method in one module."""
    found: set[tuple[str, str, str]] = set()

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            named = isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            inner = (*scope, child.name) if named else scope
            func = child.func if isinstance(child, ast.Call) else None
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "CURRENT_TICKET":
                found.add((rel, ".".join(scope), func.attr))
            visit(child, inner)

    visit(tree, ())
    return found


async def test_the_service_takes_an_optional_registry_and_an_empty_one_still_issues(
    identities: IdentityService, stops: AgentStopService, tickets: TicketRegistry, gate: AdmissionService,
) -> None:
    """I1 (kills IX-4, IX-5): a registry or None; no registry, or a closed service, issues nothing; an empty
    registry, which is falsy, is still the service's registry."""
    with pytest.raises(TypeError, match="TicketRegistry"):
        AdmissionService(identities, stops, tickets=object())  # type: ignore[arg-type]
    bare = AdmissionService(identities, stops)
    assert vars(bare)["_tickets"] is None
    assert _hold(bare, kind="intent") is NO_HOLD and CURRENT_TICKET.get() is None
    assert not tickets and len(tickets) == 0, "premise: an empty registry is falsy"
    held = _hold(gate)
    try:
        assert held is not NO_HOLD and held.ticket is not None and CURRENT_TICKET.get() == held.ticket
    finally:
        held.end()
    gate.close()
    assert _hold(gate) is NO_HOLD and len(tickets) == 1, "a closed service issues nothing"
    assert CURRENT_TICKET.get() is None


async def test_a_hold_issues_a_root_keyed_on_the_resolved_slot_and_end_puts_back_the_carried_ticket(
    identity_registry: AgentIdentityRegistry, gate: AdmissionService, tickets: TicketRegistry,
) -> None:
    """I2 (kills IX-1, IX-2, IX-6, IX-8, IX-9): the entry's principal, scope and budget; the carrier during the hold and
    after its end; the ticket ended and the carried one untouched."""
    cert = await _certify(identity_registry)
    outer = tickets.issue(principal_key=COUNSELOR_SLOT, work_kind="intent", seam="intent", scope=_SCOPE, budget=TicketBudget()).ticket
    assert outer is not None
    token = CURRENT_TICKET.set(outer)
    try:
        held = _hold(gate, cert.did, kind="intent")
        assert held.ticket is not None and held.ticket != outer
        assert CURRENT_TICKET.get() == held.ticket, "the carrier holds the unit's ticket"
        entry = tickets.entry(held.ticket)
        assert entry is not None
        assert (entry.principal_key, entry.work_kind, entry.seam, entry.parent_id, entry.depth) == (
            SURGEON_SLOT, "intent", "intent", "", 0,
        ), "a root keyed on the slot the DID resolves to, even under a carried ticket"
        assert entry.scope == _SCOPE and entry.budget == TicketBudget()
        assert tickets.check(held.ticket, effect=SEAM_TOOL).code == "ticket_live"
        held.end()
        assert CURRENT_TICKET.get() == outer, "end puts back what the carrier held"
        assert tickets.check(held.ticket, effect=SEAM_TOOL).code == "ticket_expired", "end ends the unit's ticket"
        assert tickets.check(outer, effect=SEAM_TOOL).code == "ticket_live", "the carried ticket is untouched"
    finally:
        CURRENT_TICKET.reset(token)


async def test_only_a_hold_for_a_delegated_run_takes_a_child_of_the_carried_ticket(
    gate: AdmissionService, tickets: TicketRegistry,
) -> None:
    """I3 (kills IX-7)."""
    root = _hold(gate, child=True)
    try:
        root_entry = tickets.entry(root.ticket)
        assert root_entry is not None and (root_entry.parent_id, root_entry.depth) == ("", 0), "nothing carried: a root"
        child = _hold(gate, COUNSELOR_SLOT, child=True)
        try:
            child_entry = tickets.entry(child.ticket)
            assert child_entry is not None
            assert (child_entry.parent_id, child_entry.depth, child_entry.principal_key) == (
                root.ticket.ticket_id, 1, COUNSELOR_SLOT,
            )
            for kind in ("agentic_run", "intent", "consultation"):
                sibling = _hold(gate, COUNSELOR_SLOT, kind=kind, child=False)
                try:
                    entry = tickets.entry(sibling.ticket)
                    assert entry is not None and (entry.parent_id, entry.depth) == ("", 0), kind
                finally:
                    sibling.end()
            assert CURRENT_TICKET.get() == child.ticket
        finally:
            child.end()
        assert CURRENT_TICKET.get() == root.ticket
    finally:
        root.end()
    assert CURRENT_TICKET.get() is None


async def test_a_refused_issue_leaves_the_unit_ticketless_counts_its_finding_and_adds_no_entry(
    gate: AdmissionService, tickets: TicketRegistry,
) -> None:
    """I4: a child beyond ``max_depth`` and a child of a parent whose work ended."""
    root = _hold(gate)
    child = _hold(gate, COUNSELOR_SLOT, child=True)
    held_before = len(tickets)
    deeper = _hold(gate, child=True)
    assert deeper is not NO_HOLD and deeper.ticket is None and CURRENT_TICKET.get() is None, "too deep: no ticket held"
    assert tickets.tally().get(("issue", "ticket_too_deep")) == 1 and len(tickets) == held_before
    deeper.end()
    assert CURRENT_TICKET.get() == child.ticket
    child.end()
    root.end()
    token = CURRENT_TICKET.set(root.ticket)  # a parent whose work has ended
    try:
        late = _hold(gate, COUNSELOR_SLOT, child=True)
        assert late.ticket is None and CURRENT_TICKET.get() is None
        assert tickets.tally().get(("issue", "ticket_expired")) == 1 and len(tickets) == held_before
        late.end()
        assert CURRENT_TICKET.get() == root.ticket
    finally:
        CURRENT_TICKET.reset(token)


async def test_a_hold_whose_issue_raises_is_counted_and_logged_and_leaves_the_carrier_as_it_was(
    identities: IdentityService, gate: AdmissionService, tickets: TicketRegistry, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """I5 (kills IX-10)."""
    caplog.set_level(logging.DEBUG, logger="probos.admission.service")
    outer = _hold(gate)
    try:
        def boom(key: str) -> None:
            raise RuntimeError("INJECTED resolver failure")

        monkeypatch.setattr(identities, "resolve", boom)
        assert _hold(gate) is NO_HOLD and _hold(gate) is NO_HOLD
        assert gate.failures == 2 and CURRENT_TICKET.get() == outer.ticket and len(tickets) == 1
        records = [r for r in caplog.records if r.name == "probos.admission.service"]
        assert [r.levelno for r in records] == [logging.WARNING, logging.DEBUG]
        assert all(r.exc_info and "work ticket" in r.getMessage() for r in records)

        def broken_log(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("INJECTED logging failure")

        monkeypatch.setattr(service_module.logger, "log", broken_log)
        assert _hold(gate) is NO_HOLD and gate.failures == 3, "a logging call that raised is passed over"
        assert CURRENT_TICKET.get() == outer.ticket
    finally:
        outer.end()


async def test_end_raises_nothing_for_a_used_token_another_context_or_a_raising_release(
    gate: AdmissionService, tickets: TicketRegistry, clock: _Clock,
) -> None:
    """I6 (kills IX-3)."""
    NO_HOLD.end()
    assert CURRENT_TICKET.get() is None
    held = _hold(gate)
    held.end()
    held.end()  # the token was already used
    assert CURRENT_TICKET.get() is None
    other = _hold(gate)
    contextvars.copy_context().run(other.end)  # a context that did not create the token
    assert CURRENT_TICKET.get() == other.ticket, "a reset in another context leaves this context's carrier"
    assert tickets.check(other.ticket, effect=SEAM_TOOL).code == "ticket_expired", "the release still ran"
    other.end()
    assert CURRENT_TICKET.get() is None
    last = _hold(gate)
    clock.boom = True
    try:
        last.end()  # the release reads the raising clock
        assert CURRENT_TICKET.get() is None, "the carrier was reset before the release"
    finally:
        clock.boom = False


async def test_hold_at_calls_only_an_exact_service_and_forwards_the_units_kind_and_seam(
    gate: AdmissionService, tickets: TicketRegistry,
) -> None:
    """I7 (kills IX-11)."""
    for service in (None, SimpleNamespace(hold=lambda **kwargs: TicketHold()), object()):
        assert hold_at(service, presented_id=SURGEON_SLOT, work_kind="intent", seam="intent", child=False) is NO_HOLD
    assert len(tickets) == 0
    held = hold_at(gate, presented_id=SURGEON_SLOT, work_kind="consultation", seam="consultation", child=False)
    try:
        entry = tickets.entry(held.ticket)
        assert entry is not None and (entry.work_kind, entry.seam) == ("consultation", "consultation")
    finally:
        held.end()


async def test_each_entry_holds_its_ticket_for_its_work_and_ends_it_on_every_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """I8 (kills IX-12 to IX-17)."""
    rt = await _boot(tmp_path, "data", delegation_max_depth=2)
    try:
        assert isinstance(rt.admission_service, AdmissionService), "premise: the default boot builds the service"
        tickets = vars(rt.admission_service)["_tickets"]
        assert tickets is not None and type(tickets) is TicketRegistry, "the runtime builds the registry"
        assert vars(tickets)["_stops"] is rt.agent_stops and vars(tickets)["_max_depth"] == 2
        crew = _certified_crew(rt)
        runner = WorkItemAgenticExecutor(llm_client=rt.llm_client)
        seen: dict[str, Any] = {"runs": []}

        def observe_run(runtime: Any) -> None:
            seen["runs"].append(CURRENT_TICKET.get())
            raise _Halt

        monkeypatch.setattr(agentic_dispatch, "fault_observer_for", observe_run)

        async def answer(request: Any) -> str:
            seen["consultation"] = CURRENT_TICKET.get()
            return "answered"

        monkeypatch.setattr(crew, "_answer_consultation", answer)

        async def work(intent: IntentMessage) -> None:
            seen["intent"] = CURRENT_TICKET.get()
            for extra in ({"_delegation_depth": 1}, None):
                with pytest.raises(_Halt):
                    await runner.run(agent_id=crew.id, instructions="i", task_text="t", runtime=rt, extra_context=extra)
                assert CURRENT_TICKET.get() == seen["intent"], "the run's end puts the intent's ticket back"
            request = ConsultationRequest(
                request_id="ad1346-m3d2", requester_id="ad1346-m3d2", topic="t", question="q", target_agent_id=crew.id,
            )
            assert await crew.handle_consultation_request(request) == "answered"
            assert CURRENT_TICKET.get() == seen["intent"], "the consultation's end puts the intent's ticket back"
            return None

        monkeypatch.setattr(crew, "_handle_admitted_intent", work)
        assert await crew.handle_intent(IntentMessage(intent=_PROBE, target_agent_id=crew.id)) is None
        assert CURRENT_TICKET.get() is None
        delegated, undelegated = seen["runs"]
        held = {"intent": seen["intent"], "delegated": delegated, "run": undelegated, "consultation": seen["consultation"]}
        entries = {name: tickets.entry(ticket) for name, ticket in held.items()}
        assert all(entry is not None for entry in entries.values()), entries
        assert (entries["intent"].work_kind, entries["intent"].parent_id, entries["intent"].principal_key) == (
            "intent", "", crew.id,
        )
        assert (entries["delegated"].parent_id, entries["delegated"].depth, entries["delegated"].work_kind) == (
            held["intent"].ticket_id, 1, "agentic_run",
        )
        assert (entries["run"].parent_id, entries["run"].depth) == ("", 0)
        assert (entries["consultation"].work_kind, entries["consultation"].parent_id) == ("consultation", "")
        for name, ticket in held.items():
            assert tickets.check(ticket, effect=SEAM_TOOL).code == "ticket_expired", name

        async def fails(intent: IntentMessage) -> None:
            seen["failed"] = CURRENT_TICKET.get()
            raise RuntimeError("INJECTED intent failure")

        monkeypatch.setattr(crew, "_handle_admitted_intent", fails)
        with pytest.raises(RuntimeError, match="INJECTED"):
            await crew.handle_intent(IntentMessage(intent=_PROBE, target_agent_id=crew.id))
        assert CURRENT_TICKET.get() is None
        assert tickets.check(seen["failed"], effect=SEAM_TOOL).code == "ticket_expired"

        started = asyncio.Event()

        async def waits(intent: IntentMessage) -> None:
            seen["cancelled"] = CURRENT_TICKET.get()
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(crew, "_handle_admitted_intent", waits)
        task = asyncio.create_task(crew.handle_intent(IntentMessage(intent=_PROBE, target_agent_id=crew.id)))
        await started.wait()
        assert tickets.check(seen["cancelled"], effect=SEAM_TOOL).code == "ticket_live"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert tickets.check(seen["cancelled"], effect=SEAM_TOOL).code == "ticket_expired"
    finally:
        await rt.stop()


async def test_with_the_switch_on_and_off_the_issue_points_answer_byte_identically(tmp_path: Path) -> None:
    """I9: #1604 property 12 at the three issue points' admitted paths and a delegated run's refused issue (M3c1's G2
    pins their refused paths)."""
    texts: dict[bool, str] = {}
    for enabled in (True, False):
        rt = await _boot(tmp_path, "on" if enabled else "off", shadow_enabled=enabled)
        try:
            if not enabled:
                assert rt.admission_service is None, "premise: the switch decides the service and its registry"
                texts[enabled] = await _drive_issue_points(rt)
                continue
            assert isinstance(rt.admission_service, AdmissionService), "premise: the switch decides the service"
            tickets = vars(rt.admission_service)["_tickets"]
            before = tickets.tally()
            texts[enabled] = await _drive_issue_points(rt)
            after = tickets.tally()
            issued = after.get(("issue", "ticket_issued"), 0) - before.get(("issue", "ticket_issued"), 0)
            unknown = after.get(("issue", "ticket_unknown"), 0) - before.get(("issue", "ticket_unknown"), 0)
            assert issued >= 3 and unknown == 1, (issued, unknown)
        finally:
            await rt.stop()
    assert texts[True] == texts[False]


def test_tickets_are_taken_only_at_the_three_entries_after_their_shadow_statements_and_ended_in_a_finally() -> None:
    """I10 (kills IX-18): the hold census, in the manner of 9b and 9c."""
    found = {(c.file, c.function) for c in census() if c.callee == "hold_at"}
    assert found == set(_HOLD_SITES), sorted(found)
    keywords = {"presented_id", "work_kind", "seam", "child"}
    for (rel, qualname), (callee, seam, child) in _HOLD_SITES.items():
        fn = function(rel, qualname)
        holds = [n for n in ast.walk(fn) if calls("hold_at")(n)]
        assert len(holds) == 1, (qualname, len(holds))
        hold = holds[0]
        given = {k.arg: k.value for k in hold.keywords}
        assert set(given) == keywords and len(hold.args) == 1, (qualname, sorted(given))
        assert ast.unparse(given["seam"]) == seam and ast.unparse(given["child"]) == child, qualname
        work_kind, _count = SHADOW_SITES[(rel, qualname, callee)]
        assert isinstance(given["work_kind"], ast.Constant) and given["work_kind"].value == work_kind, qualname
        last_shadow = max(n.lineno for n in ast.walk(fn) if calls("shadow_at")(n))
        assert hold.lineno > last_shadow, (qualname, hold.lineno, last_shadow)
        between = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Await) and last_shadow < n.lineno < hold.lineno]
        assert between == [], (qualname, between)
        assigned = [n for n in ast.walk(fn) if isinstance(n, ast.Assign) and n.value is hold]
        assert len(assigned) == 1 and isinstance(assigned[0].targets[0], ast.Name), qualname
        name = assigned[0].targets[0].id
        last = fn.body[-1]
        assert isinstance(last, ast.Try) and last.lineno > hold.lineno, qualname
        assert [ast.unparse(stmt) for stmt in last.finalbody] == [f"{name}.end()"], qualname
        assert not last.handlers and not last.orelse, qualname
        reads = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)]
        assert len(reads) == 1, (qualname, reads)


def test_only_hold_sets_the_carrier_and_only_end_resets_it() -> None:
    """I11."""
    named: set[str] = set()
    found: set[tuple[str, str, str]] = set()
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC.parent).as_posix()
        text = path.read_text(encoding="utf-8")
        if "CURRENT_TICKET" not in text:
            continue
        named.add(rel)
        found |= _carrier_calls(ast.parse(text, filename=rel), rel)
    assert named == {"probos/admission/carrier.py", "probos/admission/service.py"}, sorted(named)
    assert found == {
        ("probos/admission/service.py", "AdmissionService.hold", "get"),
        ("probos/admission/service.py", "AdmissionService.hold", "set"),
        ("probos/admission/service.py", "AdmissionService.check_ticket", "get"),  # AD-1346 M3d3a: the sink check
        ("probos/admission/carrier.py", "TicketHold.end", "reset"),
    }, sorted(found)
