"""AD-1346 M3d1 (#1604): work tickets and the ticket registry, over a real Captain's stop record.

``probos.admission.tickets`` is the ticket library of epic #1601's design note, and no ``src`` file outside the package
names it yet (K15). These tests drive ``TicketRegistry`` over a real ``AgentStopService`` under ``tmp_path`` with a
clock the test moves, and pin the registry's half of #1604 property 9 and the in-process half of property 5:

- K1  the ticket codes are a closed tuple in the AD-1316 stable-code syntax, disjoint from the verdict's
      ``REASON_CODES``; the effects, the operations, the finding's keys and the bounds are pinned.
- K2  ``WorkTicket`` holds its id and nothing else; ``TestTicket`` is not a ``WorkTicket`` and is not a pytest test
      class; a scope, a budget and a finding refuse values outside their sets.
- K3  ``issue`` registers a root ticket whose entry holds what it was given, depth 0, no parent and an expiry one TTL
      away; the constructor and ``issue`` refuse the wrong types and values.
- K4  a forged ticket: a hand-built ``WorkTicket`` whose valid-looking id is not registered is ``ticket_unknown``; one
      carrying a live id resolves to the registered entry, whose scope decides; a subclass that adds a wider scope,
      or a look-alike, carrying a live id is ``ticket_unknown``.
- K5  production refuses a ``TestTicket``: a registry built without ``allow_test_tickets`` answers
      ``ticket_test_refused``, and one built with it answers ``ticket_live``; no ``src`` file but the module names
      either.
- K6  no ticket is ``ticket_missing``, and each other object this test presents is ``ticket_unknown``, with no raise.
- K7  a child's scope and ceilings are no wider than its parent's entry, a ceiling it leaves unset is the parent's,
      and it expires no later; a wider child is refused and adds no entry.
- K8  a child's depth is bounded by ``max_depth``.
- K9  a child needs a live, registered parent: an unknown, revoked or expired parent is refused with
      ``ticket_unknown``, ``ticket_revoked`` or ``ticket_expired``.
- K10 revoking a ticket revokes its registered descendants and no other ticket.
- K11 a Captain's stop on the parent's principal revokes the parent's ticket and the delegated child's at the child's
      next check; it is read with ``stop_for``, so the stop's refusal counts stay empty; the revocation outlasts the
      lift; and no cause carries the Captain's reason.
- K12 a ticket is live until its expiry and ``ticket_expired`` at it; ``release`` ends a ticket at once.
- K13 a ticket presented for another principal is ``ticket_principal_mismatch``.
- K14 a full registry refuses with ``ticket_registry_full`` and adds no entry; an issue first drops entries from the
      oldest while the oldest ended more than ``retain_seconds`` ago.
- K15 no ``src`` file outside the package names the registry, the ticket or the module, and the registry's class
      stays within the SRP trigger's method count.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio

import probos
from probos.admission import tickets as tickets_module
from probos.admission.taxonomy import REASON_CODES, SEAM_MODEL_CALL, TICKET_REASON_CODES
from probos.admission.tickets import (
    MAX_TICKETS,
    TICKET_EFFECTS,
    TICKET_FINDING_KEYS,
    TICKET_OPERATIONS,
    TICKET_RETAIN_SECONDS,
    TICKET_TTL_SECONDS,
    TestTicket,
    TicketBudget,
    TicketFinding,
    TicketIssue,
    TicketRegistry,
    TicketScope,
    WorkTicket,
)
from probos.agent_stop import SEAM_TOOL, AgentStopService
from probos.execution import authority

PARENT_SLOT = "surgeon_medical_surgeon_0_b2321292"
CHILD_SLOT = "counselor_counselor_0_67c601cb"
OTHER_SLOT = "calculator_calculator_0_5f3a9c1e"
CANARY = "CANARY-ad1346-m3d1: the Captain's private reason"
T0 = 1_000.0
BOTH = TicketScope(frozenset({SEAM_TOOL, SEAM_MODEL_CALL}))
MODEL_ONLY = TicketScope(frozenset({SEAM_MODEL_CALL}))
OPEN_BUDGET = TicketBudget()
_SRC = Path(probos.__file__).resolve().parent


class _Clock:
    """A monotonic clock that only the test moves."""

    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now


@pytest_asyncio.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    """A real Captain's stop record over ``tmp_path``."""
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
def registry(stops: AgentStopService, clock: _Clock) -> TicketRegistry:
    """A production-shaped registry: test tickets refused, and the default delegation depth of 1."""
    return TicketRegistry(stops, max_depth=1, clock=clock)


def _root(
    registry: TicketRegistry, principal_key: str = PARENT_SLOT, *, scope: TicketScope = BOTH,
    budget: TicketBudget = OPEN_BUDGET,
) -> WorkTicket:
    issued = registry.issue(
        principal_key=principal_key, work_kind="agentic_run", seam="agentic_run", scope=scope, budget=budget,
    )
    assert issued.ticket is not None and issued.finding.code == "ticket_issued", issued.finding
    return issued.ticket


def _child(
    registry: TicketRegistry, parent: object, principal_key: str = CHILD_SLOT, *, scope: TicketScope = BOTH,
    budget: TicketBudget = OPEN_BUDGET,
) -> TicketIssue:
    return registry.issue_child(
        parent, principal_key=principal_key, work_kind="delegated_task", seam="delegation", scope=scope, budget=budget,
    )


def test_the_ticket_vocabularies_are_closed_and_disjoint_from_the_verdict_codes() -> None:
    """K1 (kills TK-23): the ticket codes, the effects, the operations, the finding's keys and the bounds."""
    assert TICKET_REASON_CODES == (
        "ticket_issued", "ticket_live", "ticket_missing", "ticket_unknown", "ticket_test_refused", "ticket_revoked",
        "ticket_expired", "ticket_principal_mismatch", "ticket_out_of_scope", "ticket_widened", "ticket_too_deep",
        "ticket_registry_full",
    )
    assert len(set(TICKET_REASON_CODES)) == len(TICKET_REASON_CODES)
    assert not set(TICKET_REASON_CODES) & set(REASON_CODES), "one taxonomy: no ticket code is a verdict code"
    for code in TICKET_REASON_CODES:
        assert authority._REASON_CODE_RE.fullmatch(code), code
    assert TICKET_EFFECTS == (SEAM_TOOL, SEAM_MODEL_CALL) == ("tool", "model_call")
    assert TICKET_OPERATIONS == ("issue", "tool", "model_call")
    assert TICKET_FINDING_KEYS == (
        "operation", "code", "cause", "ticket_id", "principal_key", "presented_key", "parent_id", "depth",
        "work_kind", "stop_id",
    )
    assert [field.name for field in dataclasses.fields(TicketFinding)] == list(TICKET_FINDING_KEYS)
    assert (MAX_TICKETS, TICKET_TTL_SECONDS, TICKET_RETAIN_SECONDS) == (50_000, 3_600.0, 600.0)


def test_the_ticket_records_are_frozen_and_checked() -> None:
    """K2: a WorkTicket is its id; a TestTicket is no WorkTicket and no pytest test class; scope, budget and finding
    refuse values outside their sets."""
    assert [field.name for field in dataclasses.fields(WorkTicket)] == ["ticket_id"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        WorkTicket("a").ticket_id = "b"  # type: ignore[misc]
    with pytest.raises(TypeError):
        WorkTicket(1)  # type: ignore[arg-type]
    assert not issubclass(TestTicket, WorkTicket) and TestTicket.__test__ is False
    for effects in (frozenset({"intent"}), {SEAM_TOOL}, frozenset({1})):
        with pytest.raises(ValueError):
            TicketScope(effects)  # type: ignore[arg-type]
    assert TicketScope(frozenset()).effects == frozenset()
    for value in (0, -1, True, 1.5, "3"):
        with pytest.raises(ValueError):
            TicketBudget(max_tokens=value)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            TicketBudget(max_iterations=value)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        TicketFinding("intent", "ticket_live", "")
    with pytest.raises(ValueError):
        TicketFinding("tool", "admitted", "")
    assert list(TicketFinding("tool", "ticket_missing", "No ticket.").to_dict()) == list(TICKET_FINDING_KEYS)


async def test_issue_registers_a_root_ticket_the_registry_owns(stops: AgentStopService, registry: TicketRegistry) -> None:
    """K3: the root entry holds what issue was given, depth 0, no parent and an expiry one TTL away; the id is 32
    lowercase hex characters; the constructor and issue refuse the wrong types and values."""
    issued = registry.issue(
        principal_key=PARENT_SLOT, work_kind="intent", seam="intent", scope=MODEL_ONLY,
        budget=TicketBudget(max_tokens=4096, max_iterations=5),
    )
    ticket = issued.ticket
    assert ticket is not None and type(ticket) is WorkTicket
    assert len(ticket.ticket_id) == 32 and set(ticket.ticket_id) <= set("0123456789abcdef")
    entry = registry.entry(ticket)
    assert entry is not None
    assert (entry.principal_key, entry.work_kind, entry.seam, entry.scope, entry.budget) == (
        PARENT_SLOT, "intent", "intent", MODEL_ONLY, TicketBudget(4096, 5),
    )
    assert (entry.parent_id, entry.depth, entry.issued_at, entry.expires_at, entry.revoked_at, entry.stop_id) == (
        "", 0, T0, T0 + TICKET_TTL_SECONDS, None, "",
    )
    assert issued.finding.to_dict() == {
        "operation": "issue", "code": "ticket_issued", "cause": issued.finding.cause, "ticket_id": ticket.ticket_id,
        "principal_key": PARENT_SLOT, "presented_key": "", "parent_id": "", "depth": 0, "work_kind": "intent",
        "stop_id": "",
    }
    assert _root(registry).ticket_id != ticket.ticket_id and len(registry) == 2
    assert registry.tally() == {("issue", "ticket_issued"): 2}
    registry.tally()[("issue", "ticket_issued")] = 99
    assert registry.tally() == {("issue", "ticket_issued"): 2}, "tally() returns a copy"
    for bad in ({"principal_key": ""}, {"work_kind": "chess"}, {"seam": "nowhere"}):
        fields = {"principal_key": PARENT_SLOT, "work_kind": "intent", "seam": "intent", **bad}
        with pytest.raises(ValueError):
            registry.issue(**fields, scope=BOTH, budget=OPEN_BUDGET)
    with pytest.raises(TypeError):
        registry.issue(principal_key=PARENT_SLOT, work_kind="intent", seam="intent", scope=frozenset(), budget=OPEN_BUDGET)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        registry.issue(principal_key=1, work_kind="intent", seam="intent", scope=BOTH, budget=OPEN_BUDGET)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        TicketRegistry(SimpleNamespace(), max_depth=1)  # type: ignore[arg-type]
    for kwargs in (
        {"max_depth": -1}, {"max_depth": True}, {"max_depth": 1, "ttl_seconds": 0},
        {"max_depth": 1, "retain_seconds": float("inf")}, {"max_depth": 1, "ttl_seconds": float("nan")},
    ):
        with pytest.raises(ValueError):
            TicketRegistry(stops, **kwargs)
    with pytest.raises(TypeError):
        TicketRegistry(stops, max_depth=1, allow_test_tickets=1)  # type: ignore[arg-type]
    assert len(registry) == 2, "nothing refused was added"


async def test_a_forged_ticket_is_unknown_or_resolves_to_its_registered_entry(registry: TicketRegistry) -> None:
    """K4 (#1604 property 9, the design note's rule 2; kills TK-3, TK-19): the registry's entry decides, never the
    presented object."""
    live = _root(registry, scope=MODEL_ONLY)
    valid_looking = WorkTicket("0123456789abcdef" * 2)
    assert registry.check(valid_looking, effect=SEAM_MODEL_CALL).code == "ticket_unknown"
    assert registry.entry(valid_looking) is None
    hand_built = WorkTicket(live.ticket_id)
    assert registry.entry(hand_built) == registry.entry(live)
    assert registry.check(hand_built, effect=SEAM_MODEL_CALL).code == "ticket_live"
    outside = registry.check(hand_built, effect=SEAM_TOOL)
    assert (outside.code, outside.ticket_id, outside.principal_key) == ("ticket_out_of_scope", live.ticket_id, PARENT_SLOT)

    @dataclasses.dataclass(frozen=True)
    class Widened(WorkTicket):
        scope: TicketScope = BOTH

    forged = Widened(live.ticket_id)
    look_alike = SimpleNamespace(ticket_id=live.ticket_id, scope=BOTH)
    for impostor in (forged, look_alike):
        assert registry.check(impostor, effect=SEAM_TOOL).code == "ticket_unknown", impostor
        assert registry.entry(impostor) is None, impostor


async def test_production_refuses_a_test_ticket(
    stops: AgentStopService, clock: _Clock, registry: TicketRegistry,
) -> None:
    """K5 (#1601 Risks, #1604 property 9; kills TK-1, TK-2, TK-22): a registry built without allow_test_tickets
    refuses a TestTicket at each effect and as a parent; one built with it answers ticket_live and parents nothing;
    no src file but the module names TestTicket or allow_test_tickets."""
    assert inspect.signature(TicketRegistry).parameters["allow_test_tickets"].default is False
    for effect in TICKET_EFFECTS:
        refused = registry.check(TestTicket("k5"), effect=effect)
        assert (refused.code, refused.operation) == ("ticket_test_refused", effect)
    assert _child(registry, TestTicket()).finding.code == "ticket_test_refused"
    built_for_tests = TicketRegistry(stops, max_depth=1, clock=clock, allow_test_tickets=True)
    for effect in TICKET_EFFECTS:
        assert built_for_tests.check(TestTicket(), effect=effect).code == "ticket_live"
    assert _child(built_for_tests, TestTicket()).finding.code == "ticket_unknown", "a TestTicket parents nothing"
    named: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC.parent).as_posix()
        text = path.read_text(encoding="utf-8")
        if rel != "probos/admission/tickets.py" and ("TestTicket" in text or "allow_test_tickets" in text):
            named.append(rel)
    assert named == [], named


async def test_check_answers_any_presented_object_without_raising(registry: TicketRegistry) -> None:
    """K6 (kills TK-21): no ticket is ticket_missing; each other object here is ticket_unknown, and none raises."""
    missing = registry.check(None, effect=SEAM_TOOL, presented_key=CHILD_SLOT)
    assert (missing.code, missing.presented_key, missing.ticket_id) == ("ticket_missing", CHILD_SLOT, "")
    empty = object.__new__(WorkTicket)
    for odd in (empty, "a-ticket-id", 7, [], {"ticket_id": "x"}, WorkTicket("x" * 10_000), SimpleNamespace()):
        found = registry.check(odd, effect=SEAM_MODEL_CALL)
        assert found.code == "ticket_unknown" and len(found.ticket_id) <= 64, (odd, found)
    with pytest.raises(ValueError):
        registry.check(None, effect="intent")
    with pytest.raises(TypeError):
        registry.check(None, effect=SEAM_TOOL, presented_key=None)  # type: ignore[arg-type]
    assert registry.tally() == {("tool", "ticket_missing"): 1, ("model_call", "ticket_unknown"): 7}


async def test_a_child_is_no_wider_than_its_parent(registry: TicketRegistry, clock: _Clock) -> None:
    """K7 (the design note's rule 3; kills TK-11 to TK-15): scope and ceilings within the parent's entry, an unset
    ceiling is the parent's, the expiry is no later; a wider child is refused and adds no entry."""
    parent = _root(registry, scope=MODEL_ONLY, budget=TicketBudget(max_tokens=4096, max_iterations=5))
    clock.now += 100.0
    inherited = _child(registry, parent, scope=MODEL_ONLY)
    assert inherited.ticket is not None, inherited.finding
    entry = registry.entry(inherited.ticket)
    assert entry is not None and entry.budget == TicketBudget(4096, 5)
    assert (entry.parent_id, entry.depth, entry.expires_at) == (parent.ticket_id, 1, T0 + TICKET_TTL_SECONDS)
    narrower = _child(
        registry, parent, scope=TicketScope(frozenset()), budget=TicketBudget(max_tokens=1024, max_iterations=5),
    )
    assert narrower.ticket is not None, narrower.finding
    narrower_entry = registry.entry(narrower.ticket)
    assert narrower_entry is not None and narrower_entry.budget == TicketBudget(1024, 5)
    held = len(registry)
    for scope, budget in (
        (BOTH, OPEN_BUDGET),
        (MODEL_ONLY, TicketBudget(max_tokens=4097)),
        (MODEL_ONLY, TicketBudget(max_iterations=6)),
    ):
        refused = _child(registry, parent, scope=scope, budget=budget)
        assert refused.ticket is None and refused.finding.code == "ticket_widened", refused.finding
        assert (refused.finding.parent_id, refused.finding.ticket_id) == (parent.ticket_id, "")
    assert len(registry) == held
    open_parent = _root(registry, OTHER_SLOT)
    unbounded = _child(registry, open_parent, budget=TicketBudget(max_tokens=10**9))
    assert unbounded.ticket is not None, "an unbounded parent bounds no ceiling"


async def test_child_depth_is_bounded_by_the_delegation_depth(stops: AgentStopService, clock: _Clock) -> None:
    """K8 (kills TK-10): with max_depth 1 a root's child is issued and its child is ticket_too_deep; 0 allows no
    child; 2 allows a grandchild."""
    one = TicketRegistry(stops, max_depth=1, clock=clock)
    child = _child(one, _root(one)).ticket
    assert child is not None
    too_deep = _child(one, child, OTHER_SLOT)
    assert (too_deep.ticket, too_deep.finding.code, too_deep.finding.depth) == (None, "ticket_too_deep", 2)
    zero = TicketRegistry(stops, max_depth=0, clock=clock)
    assert _child(zero, _root(zero)).finding.code == "ticket_too_deep"
    two = TicketRegistry(stops, max_depth=2, clock=clock)
    middle = _child(two, _root(two)).ticket
    assert middle is not None
    grandchild = _child(two, middle, OTHER_SLOT).ticket
    assert grandchild is not None
    grandchild_entry = two.entry(grandchild)
    assert grandchild_entry is not None and grandchild_entry.depth == 2


async def test_a_child_needs_a_live_registered_parent(registry: TicketRegistry, clock: _Clock) -> None:
    """K9 (kills TK-20): an unknown, revoked or expired parent is refused with ticket_unknown, ticket_revoked or
    ticket_expired."""
    assert _child(registry, WorkTicket("f" * 32)).finding.code == "ticket_unknown"
    revoked = _root(registry)
    assert registry.revoke(revoked) == 1
    refused = _child(registry, revoked)
    assert (refused.ticket, refused.finding.code, refused.finding.parent_id) == (None, "ticket_revoked", revoked.ticket_id)
    expired = _root(registry, OTHER_SLOT)
    clock.now += TICKET_TTL_SECONDS
    held = len(registry)
    assert _child(registry, expired).finding.code == "ticket_expired"
    assert len(registry) == held


async def test_revoking_a_parent_revokes_its_children(stops: AgentStopService, clock: _Clock) -> None:
    """K10 (#1601 Attenuation; kills TK-4, TK-9): revoke reaches every registered descendant and no other ticket."""
    registry = TicketRegistry(stops, max_depth=2, clock=clock)
    root = _root(registry)
    child = _child(registry, root).ticket
    assert child is not None
    grandchild = _child(registry, child, OTHER_SLOT).ticket
    assert grandchild is not None
    other = _root(registry, OTHER_SLOT)
    assert registry.revoke(root) == 3 and registry.revoke(root) == 0
    for ticket in (root, child, grandchild):
        found = registry.check(ticket, effect=SEAM_TOOL)
        assert (found.code, found.stop_id) == ("ticket_revoked", ""), found
    assert registry.check(other, effect=SEAM_TOOL).code == "ticket_live"
    assert registry.revoke(WorkTicket("0" * 32)) == 0 and registry.revoke(TestTicket()) == 0


async def test_a_captains_stop_revokes_the_principals_tickets_and_their_children_and_counts_nothing(
    registry: TicketRegistry, stops: AgentStopService, clock: _Clock,
) -> None:
    """K11 (#1604 properties 5 and 10, in process; kills TK-6, TK-7, TK-8): a stop on the parent's principal revokes
    the delegated child's ticket at its next check, with the order's id; stop_for counts no refusal; the revocation
    outlasts the lift; no cause carries the Captain's reason."""
    parent = _root(registry)
    child = _child(registry, parent).ticket
    assert child is not None
    assert registry.check(child, effect=SEAM_MODEL_CALL, presented_key=CHILD_SLOT).code == "ticket_live"
    issued = await stops.issue_stop(PARENT_SLOT, reason=CANARY)
    stop_id = issued.record.stop_id
    clock.now += 1.0
    at_model = registry.check(child, effect=SEAM_MODEL_CALL, presented_key=CHILD_SLOT)
    assert (at_model.code, at_model.stop_id, at_model.ticket_id) == ("ticket_revoked", stop_id, child.ticket_id)
    parent_entry = registry.entry(parent)
    assert parent_entry is not None and (parent_entry.revoked_at, parent_entry.stop_id) == (T0 + 1.0, stop_id)
    assert stops.refused_counts(stop_id) == {}
    await stops.lift_stop(PARENT_SLOT, reason="lifted")
    after_lift = [registry.check(ticket, effect=SEAM_TOOL) for ticket in (parent, child)]
    assert [(found.code, found.stop_id) for found in after_lift] == [("ticket_revoked", stop_id)] * 2
    assert all(CANARY not in found.cause for found in (*after_lift, at_model)) and stop_id in at_model.cause


async def test_a_ticket_expires_and_release_ends_it(registry: TicketRegistry, clock: _Clock) -> None:
    """K12 (kills TK-5): live until its expiry and ticket_expired at it; release ends a ticket at once."""
    ticket = _root(registry)
    clock.now = T0 + TICKET_TTL_SECONDS - 0.5
    assert registry.check(ticket, effect=SEAM_TOOL).code == "ticket_live"
    clock.now = T0 + TICKET_TTL_SECONDS
    assert registry.check(ticket, effect=SEAM_TOOL).code == "ticket_expired"
    released = _root(registry, OTHER_SLOT)
    assert registry.release(released) is True
    assert registry.check(released, effect=SEAM_MODEL_CALL).code == "ticket_expired"
    assert registry.release(WorkTicket("0" * 32)) is False and registry.release(None) is False


async def test_a_ticket_presented_by_another_principal_is_a_mismatch(registry: TicketRegistry) -> None:
    """K13 (kills TK-18): a presented key that is not the entry's principal is ticket_principal_mismatch; with no key
    presented nothing is compared."""
    ticket = _root(registry)
    found = registry.check(ticket, effect=SEAM_TOOL, presented_key=OTHER_SLOT)
    assert (found.code, found.principal_key, found.presented_key) == (
        "ticket_principal_mismatch", PARENT_SLOT, OTHER_SLOT,
    )
    assert registry.check(ticket, effect=SEAM_TOOL, presented_key=PARENT_SLOT).code == "ticket_live"
    assert registry.check(ticket, effect=SEAM_TOOL).code == "ticket_live"


async def test_the_registry_is_bounded_and_drops_ended_entries_in_issue_order(
    registry: TicketRegistry, clock: _Clock, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """K14 (F-209; kills TK-16, TK-17): a full registry refuses and adds no entry; an issue first drops entries from
    the oldest while the oldest ended more than retain_seconds ago."""
    monkeypatch.setattr(tickets_module, "MAX_TICKETS", 3)
    first = _root(registry)
    _root(registry)
    third = _root(registry)
    full = registry.issue(principal_key=OTHER_SLOT, work_kind="intent", seam="intent", scope=BOTH, budget=OPEN_BUDGET)
    assert (full.ticket, full.finding.code, len(registry)) == (None, "ticket_registry_full", 3)
    assert registry.release(first) is True
    clock.now += TICKET_RETAIN_SECONDS
    kept = registry.issue(principal_key=OTHER_SLOT, work_kind="intent", seam="intent", scope=BOTH, budget=OPEN_BUDGET)
    assert kept.ticket is None, "an entry that ended exactly retain_seconds ago is still kept"
    clock.now += 0.5
    _root(registry, OTHER_SLOT)
    assert len(registry) == 3
    assert registry.check(first, effect=SEAM_TOOL).code == "ticket_unknown", "the oldest ended entry was dropped"
    assert registry.check(third, effect=SEAM_TOOL).code == "ticket_live"
    clock.now += TICKET_TTL_SECONDS + TICKET_RETAIN_SECONDS + 1.0
    _root(registry)
    assert len(registry) == 1, "every entry that ended long enough ago was dropped first"


def test_the_registry_has_no_caller_outside_the_package_and_stays_within_the_srp_method_trigger() -> None:
    """K15: no src file outside ``probos/admission/`` contains the text ``WorkTicket``, ``TicketRegistry``,
    ``admission.tickets`` or ``admission import tickets`` (the slice that adds the first caller updates this test), and
    ``TicketRegistry`` has at most 15 direct methods, the SRP trigger of ``scripts/check_architecture_principles.py``."""
    named: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC.parent).as_posix()
        if rel.startswith("probos/admission/"):
            continue
        text = path.read_text(encoding="utf-8")
        if any(name in text for name in ("WorkTicket", "TicketRegistry", "admission.tickets", "admission import tickets")):
            named.append(rel)
    assert named == [], named
    tree = ast.parse((_SRC / "admission" / "tickets.py").read_text(encoding="utf-8"))
    (registry_class,) = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "TicketRegistry"]
    methods = [node.name for node in registry_class.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert len(methods) <= 15, methods
