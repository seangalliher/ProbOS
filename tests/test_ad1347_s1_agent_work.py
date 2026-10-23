"""AD-1347 S1 (#1627): the Ship's Computer service that owns agent-created work, against real objects.

The real ``WorkItemStore`` on a SQLite file under ``tmp_path``; the real ``ToolRegistry`` with ``event_log_query``
registered by its production function and a real ``ToolPermissionStore``; the real ``AgentStopService``; a real
``VesselOntologyService`` over a copy of ``config/ontology``; a real ``AgentRegistry`` of started agents; a real
``TrustNetwork``. Discovery and claim run through ``ToolRegistry.check_and_invoke`` and the runtime's own
``resolve_workforce_pull_resource``. Identity resolution is the one stand-in (``_SlotIdentities``): it answers as
``IdentityService.resolve`` does (AD-1346 M1a), and ``tests/test_ad1347_s1_wiring.py`` runs the real facade on a boot.

Acceptance 2's whole chain (tag, item, notice, claim, run, report) is ``tests/test_ad1347_s3_execution.py`` X1.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import logging
import shutil
import sqlite3
import time
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import probos.agent_work as agent_work_module
from probos.agent_stop import AgentStopService
from probos.agent_work import (
    AgentWorkCreated,
    AgentWorkOrigin,
    AgentWorkRefusal,
    AgentWorkService,
    CrewMember,
    normalize_title,
    open_agent_work_service,
    read_agent_work,
)
from probos.cognitive.crew_directory import RuntimeCrewDirectory
from probos.config import AgentWorkConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.identity_service import IdentityRef
from probos.ontology import VesselOntologyService
from probos.runtime import ProbOSRuntime
from probos.startup.communication import _register_event_log_query_tool, _register_work_item_pull_tools
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResultPresentation
from probos.tools.registry import ToolRegistry
from probos.workforce import BookableResource, WorkItemStore
from tests.test_ad1187_agent_work_pull import _Instrument
from tests.test_ad864_crew_assignment import _make_registry

_REPO = Path(__file__).resolve().parents[1]
CREW = (
    ("engineering_officer", "laforge-1"),
    ("builder", "forge-1"),
    ("builder", "forge-2"),
    ("security_officer", "worf-1"),
    ("data_analyst", "rahda-1"),
    ("diagnostician", "bones-1"),
    ("surgeon", "pulaski-1"),
    ("pharmacist", "ogawa-1"),
)
# The chiefs' posts, and the first officer's (another department's superior, so never a chief here).
WIRED = (("engineering_officer", "laforge-1"), ("diagnostician", "bones-1"), ("architect", "numberone-1"))
ENSIGNS = ("forge-2",)
RANKS = ("ensign", "lieutenant", "commander", "senior_officer")
ORIGIN = AgentWorkOrigin("ward_room", thread_id="51d91a7d", post_id="post-1")
PRESENTATION = ToolResultPresentation(render_complete=repr)
REASON = "the EventLog shows what the thread cannot"
STOP_REASON = "CANARY-ad1347: the Captain's private reason"
LIFT_REASON = "lifted by the test"
_UNUSED = object()


class _SlotIdentities:
    """``IdentityService.resolve``'s contract (AD-1346 M1a): a slot id or its UUID resolves; anything else is None."""

    def __init__(self, slots: Iterable[str]) -> None:
        refs = {
            slot: IdentityRef(slot_id=slot, sovereign_id=f"uuid-{slot}", did=f"did:probos:test:{slot}", callsign=slot, agent_type="crew")
            for slot in slots
        }
        self._refs = {**refs, **{ref.sovereign_id: ref for ref in refs.values()}}

    def resolve(self, key: str) -> IdentityRef | None:
        return self._refs.get(key)


@dataclass
class _Ship:
    service: AgentWorkService
    store: WorkItemStore
    tools: ToolRegistry
    permissions: ToolPermissionStore
    stops: AgentStopService
    directory: RuntimeCrewDirectory
    agents: dict[str, Any]
    db_path: Path


def _section(**limits: Any) -> AgentWorkConfig:
    return AgentWorkConfig(enabled=True, **limits)


def _schema(path: Path) -> list[tuple[str, str, str]]:
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return raw.execute("SELECT type, name, coalesce(sql, '') FROM sqlite_master ORDER BY type, name").fetchall()


@contextlib.asynccontextmanager
async def _ship(
    tmp_path: Path,
    *,
    section: AgentWorkConfig | None = None,
    event_log: bool = True,
    clock: Callable[[], float] | None = None,
    tick: float = 1000.0,
) -> AsyncIterator[_Ship]:
    """One vessel's worth of the real collaborators; every file is under ``tmp_path`` and is reopened on a later call."""
    ontology_dir = tmp_path / "ontology"
    if not ontology_dir.exists():
        shutil.copytree(_REPO / "config" / "ontology", ontology_dir)
    (tmp_path / "ontology-data").mkdir(exist_ok=True)
    ontology = VesselOntologyService(ontology_dir, data_dir=tmp_path / "ontology-data")
    await ontology.initialize()
    for agent_type, slot in WIRED:
        ontology.wire_agent(agent_type, slot)
    registry = await _make_registry(list(CREW))
    agents = {agent.id: agent for agent in registry.all()}
    trust = TrustNetwork()
    for slot in ENSIGNS:
        trust.create_with_prior(slot, 1.0, 3.0)  # 0.25: an ensign; the default prior (0.5) is a lieutenant
    permissions = ToolPermissionStore(db_path=str(tmp_path / "tool_permissions.db"))
    stops = AgentStopService(data_dir=tmp_path / "stops")
    runtime = object.__new__(ProbOSRuntime)  # the pull authority's attributes only, as tests/test_ad1187_agent_work_pull.py does
    store = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"), tick_interval=tick,
        pull_resource_resolver=runtime.resolve_workforce_pull_resource,
    )
    tools = ToolRegistry()
    started: list[Any] = []
    try:
        for agent in agents.values():
            await agent.start()
        await permissions.start()
        started.append(permissions)
        await stops.start()
        started.append(stops)
        tools.set_permission_store(permissions)
        tools.set_stop_gate(stops)
        _register_event_log_query_tool(
            tool_registry=tools, enabled=event_log,
            event_log_reader=_UNUSED, event_log_audit_sink=_UNUSED,  # type: ignore[arg-type]  # registered, never invoked
        )
        tools.register(_Instrument("hull_survey"), allowed_departments=("engineering",), default_permissions=dict.fromkeys(RANKS, "read"))
        tools.register(_Instrument("sealed_survey"), restricted_to=["nobody"])
        runtime.registry = registry
        runtime.ontology = ontology
        runtime.trust_network = trust
        runtime.tool_registry = tools
        runtime.work_item_store = store
        for slot, agent in agents.items():
            store.register_resource(BookableResource(resource_id=slot, agent_type=agent.agent_type, department="", capacity=5, characteristics=[]))
        await store.start()
        started.append(store)
        _register_work_item_pull_tools(
            tool_registry=tools, work_item_store=store, pull_resource_resolver=runtime.resolve_workforce_pull_resource,
        )
        directory = RuntimeCrewDirectory(agent_registry=registry, ontology=ontology, trust_network=trust)
        service = await open_agent_work_service(
            config=section or _section(), store=store, tools=tools,
            identities=_SlotIdentities([*agents, "ghost-1"]), directory=directory,
            stop_gate=stops, clock=clock or time.time,
        )
        assert isinstance(service, AgentWorkService)
        yield _Ship(service, store, tools, permissions, stops, directory, agents, tmp_path / "workforce.db")
    finally:
        for resource in reversed(started):
            await resource.stop()
        for agent in agents.values():
            if agent.is_alive:
                await agent.stop()


async def _invoke(ship: _Ship, slot: str, tool_id: str, params: dict[str, Any]) -> Any:
    member = ship.directory.member(slot)
    assert member is not None, slot
    required = ToolPermission.READ if tool_id == "discover_work_items" else ToolPermission.WRITE
    return await ship.tools.check_and_invoke(
        slot, tool_id, params, required=required, agent_department=member.department,
        agent_rank=member.rank, agent_types=[member.agent_type],
        context={"agent_id": slot, "_tool_result_presentation": PRESENTATION},
    )


async def _discovered(ship: _Ship, slot: str) -> list[str]:
    result = await _invoke(ship, slot, "discover_work_items", {})
    assert not result.error, result.error
    return [entry["id"] for entry in ast.literal_eval(result.output)["items"]]


async def _claimed(ship: _Ship, slot: str, work_item_id: str) -> bool:
    result = await _invoke(ship, slot, "claim_work_item", {"work_item_id": work_item_id})
    assert not result.error, result.error
    return ast.literal_eval(result.output)["owned"] is True


async def _request(
    ship: _Ship, requester: str = "pulaski-1", *, title: str = "Read the EventLog window",
    tool_id: str = "event_log_query", **extra: Any,
) -> AgentWorkCreated | AgentWorkRefusal:
    return await ship.service.request_work(
        requester, title=title, description="", reason=REASON, origin=ORIGIN, tool_id=tool_id, **extra,
    )


async def _self_task(
    ship: _Ship, requester: str = "forge-1", *, title: str = "Check my build log", **extra: Any,
) -> AgentWorkCreated | AgentWorkRefusal:
    return await ship.service.create_self_task(
        requester, title=title, description="", reason=REASON, origin=ORIGIN, **extra,
    )


def _code(result: AgentWorkCreated | AgentWorkRefusal) -> str:
    assert isinstance(result, AgentWorkRefusal), result
    return result.code


# 1
async def test_premise_the_fixture_is_the_production_shape(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        assert {member.slot_id for member in ship.directory.members()} == {slot for _, slot in CREW}
        registration = ship.tools.get("event_log_query")
        assert registration is not None
        assert registration.allowed_departments == ("engineering", "science", "security")
        assert registration.default_permissions["ensign"] == "none" and registration.default_permissions["lieutenant"] == "read"


# 2
async def test_a_self_task_is_assigned_to_its_creator_with_nested_provenance(tmp_path: Path) -> None:
    """Acceptance 6: created_by is the slot the requester's identity resolves to, never "captain"."""
    async with _ship(tmp_path) as ship:
        created = await _self_task(ship, "uuid-forge-1")
        assert isinstance(created, AgentWorkCreated), created
        item = created.work_item
        assert (created.kind, item.created_by, item.assigned_to, item.status) == ("self", "forge-1", "forge-1", "open")
        assert item.parent_id is None and item.ttl_seconds == 86_400 and item.tags == ["agent_work"]
        assert "thread_id" not in item.metadata and "agent_pull" not in item.metadata
        assert item.metadata["agent_work"] == {
            "version": 1, "kind": "self", "requester": "forge-1", "requester_sovereign_id": "uuid-forge-1",
            "origin": {"channel": "ward_room", "thread_id": "51d91a7d", "post_id": "post-1"},
            "reason": REASON, "depth": 1, "department": "engineering", "tool_id": None,
            "dedup_key": None, "spawned_from": None, "assignee_requested": None,
        }
        stored = await ship.store.get_work_item(item.id)
        assert stored is not None and stored.metadata == item.metadata and stored.created_by == "forge-1"
        tables = {name for kind, name, _ in _schema(ship.db_path) if kind == "table"}
        assert {"agent_work_watchers", "agent_work_notices"} <= tables


# 3
@pytest.mark.parametrize("requester", ["did:probos:agent:nobody", "ghost-1", "captain"])
async def test_an_unresolved_requester_is_refused_and_nothing_is_written(tmp_path: Path, requester: str) -> None:
    """Premise 8: no identity, or no live crew member behind it, is refused; nothing falls back to "captain"."""
    async with _ship(tmp_path) as ship:
        assert _code(await _self_task(ship, requester)) == "requester_unresolved"
        assert _code(await _request(ship, requester)) == "requester_unresolved"
        assert await ship.store.list_agent_work(False, None, 10) == []


# 4
async def test_a_self_task_naming_a_tool_needs_its_creator_to_hold_it(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        held = await _self_task(ship, "forge-1", tool_id="event_log_query")
        assert isinstance(held, AgentWorkCreated) and held.work_item.metadata["agent_work"]["tool_id"] == "event_log_query"
        for requester, tool_id, code in (
            ("pulaski-1", "event_log_query", "requester_not_eligible"),  # medical: outside the tool's departments
            ("forge-2", "event_log_query", "requester_not_eligible"),  # an ensign: the rank matrix says none
            ("forge-1", "no_such_tool", "tool_unavailable"),
            ("forge-1", "", "invalid_request"),
        ):
            assert _code(await _self_task(ship, requester, title=f"{requester} {tool_id}", tool_id=tool_id)) == code


# 5
async def test_a_chief_assigns_within_its_department(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        assigned = await _request(ship, "laforge-1", assignee="forge-1")
        assert isinstance(assigned, AgentWorkCreated), assigned
        assert (assigned.kind, assigned.converted, assigned.work_item.assigned_to) == ("assignment", False, "forge-1")
        assert "agent_pull" not in assigned.work_item.metadata
        assert _code(await _request(ship, "laforge-1", title="an ensign", assignee="forge-2")) == "assignee_not_eligible"
        await ship.stops.issue_stop("forge-1", reason=STOP_REASON)
        try:
            assert _code(await _request(ship, "laforge-1", title="stopped", assignee="forge-1")) == "assignee_stopped"
        finally:
            await ship.stops.lift_stop("forge-1", reason=LIFT_REASON)


# 6
async def test_a_peer_or_cross_department_assignment_becomes_a_request(tmp_path: Path) -> None:
    """Acceptance 3: a non-chief cannot assign; a peer or cross-department assignment becomes a request."""
    async with _ship(tmp_path) as ship:
        peer = await _request(ship, "pulaski-1", assignee="ogawa-1")
        across = await _request(ship, "worf-1", title="Survey the hull", tool_id="hull_survey", assignee="forge-1")
        aimed = await _request(ship, "pulaski-1", title="Read the security log window", assignee="worf-1")
        for created, department, named in (
            (peer, "engineering", "ogawa-1"), (across, "engineering", "forge-1"), (aimed, "security", "worf-1"),
        ):
            assert isinstance(created, AgentWorkCreated), created
            assert (created.kind, created.converted, created.work_item.assigned_to) == ("request", True, None)
            record = created.work_item.metadata["agent_work"]
            assert (record["department"], record["assignee_requested"]) == (department, named)
            assert created.work_item.metadata["agent_pull"] == {"version": 1, "scope": "department", "department": department}


# 7
async def test_a_request_goes_to_the_department_with_most_eligible_members_unless_one_is_named(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        default = await _request(ship, "pulaski-1")
        assert isinstance(default, AgentWorkCreated)
        assert default.work_item.metadata["agent_pull"]["department"] == "engineering"
        assert default.notify == ("forge-1", "laforge-1")  # engineering's lieutenants; forge-2 is an ensign
        named = await _request(ship, "ogawa-1", title="Science reads it", department="science")
        assert isinstance(named, AgentWorkCreated) and named.notify == ("rahda-1",)
        assert _code(await _request(ship, "bones-1", title="Medical reads it", department="medical")) == "department_not_eligible"


# 8
async def test_eligibility_is_the_registrys_own_answer_for_each_member(tmp_path: Path) -> None:
    """Premise 3: restricted_to, the rank matrix and the Captain's grants and restrictions decide, per member."""
    async with _ship(tmp_path) as ship:
        def eligible(tool_id: str) -> set[str]:
            return {member.slot_id for member in ship.service.eligible_members(tool_id)}

        assert eligible("event_log_query") == {"laforge-1", "forge-1", "worf-1", "rahda-1"}
        await ship.permissions.issue_grant("forge-2", "event_log_query", ToolPermission.READ, reason="AD-1347 test grant")
        await ship.permissions.issue_grant(
            "forge-1", "event_log_query", ToolPermission.NONE, is_restriction=True, reason="AD-1347 test restriction",
        )
        assert eligible("event_log_query") == {"laforge-1", "forge-2", "worf-1", "rahda-1"}
        assert eligible("hull_survey") == {"laforge-1", "forge-1", "forge-2"}
        assert eligible("sealed_survey") == set()
        assert _code(await _request(ship, "rahda-1")) == "requester_holds_tool"


# 9
async def test_an_unregistered_tool_or_a_tool_nobody_may_use_is_refused_at_creation(tmp_path: Path) -> None:
    """Premise 4: event_log_query exists only when agentic_dispatch.orchestrator_enabled is on; unregistered is no department."""
    async with _ship(tmp_path / "off", event_log=False) as ship:
        assert ship.tools.get("event_log_query") is None
        assert ship.service.eligible_members("event_log_query") == ()
        assert _code(await _request(ship, "pulaski-1")) == "tool_unavailable"
    async with _ship(tmp_path / "on") as ship:
        assert _code(await _request(ship, "pulaski-1", tool_id="sealed_survey")) == "no_eligible_member"
        for slot in ("laforge-1", "forge-1", "worf-1", "rahda-1"):
            await ship.stops.issue_stop(slot, reason=STOP_REASON)
        assert _code(await _request(ship, "pulaski-1")) == "no_eligible_member"


# 10
async def test_request_is_created_published_and_claimed_by_an_eligible_member(tmp_path: Path) -> None:
    """The S1 half of acceptance 2, and acceptance 3's claim half, through the real tools and the runtime's pull authority.

    The whole chain, from the tag before creation to the post in the origin thread after the run, is
    tests/test_ad1347_s3_execution.py X1.
    """
    async with _ship(tmp_path) as ship:
        created = await _request(ship, "pulaski-1")
        assert isinstance(created, AgentWorkCreated), created
        item_id = created.work_item.id
        assert item_id not in await _discovered(ship, "worf-1")  # security: another department's request
        assert item_id not in await _discovered(ship, "forge-2")  # engineering, but an ensign
        assert await _claimed(ship, "forge-2", item_id) is False
        assert await _discovered(ship, "forge-1") == [item_id]
        assert await _claimed(ship, "forge-1", item_id) is True
        claimed = await ship.store.get_work_item(item_id)
        assert claimed is not None and (claimed.assigned_to, claimed.status) == ("forge-1", "scheduled")
        assert item_id not in await _discovered(ship, "laforge-1")


# 11
async def test_a_request_with_a_top_level_thread_id_would_reach_nobody(tmp_path: Path) -> None:
    """Premise 6: the placement trap; the same publication with the origin at the top level is not discoverable."""
    async with _ship(tmp_path) as ship:
        created = await _request(ship, "pulaski-1")
        assert isinstance(created, AgentWorkCreated)
        assert created.work_item.metadata["agent_work"]["origin"]["thread_id"] == "51d91a7d"
        trapped = await ship.store.create_work_item(
            title="trapped", metadata={**created.work_item.metadata, "thread_id": "51d91a7d"},
        )
        assert await _discovered(ship, "forge-1") == [created.work_item.id]
        assert trapped.id not in await _discovered(ship, "laforge-1")


# 12
async def test_the_legacy_claim_route_applies_the_same_gate(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        created = await _request(ship, "pulaski-1")
        assert isinstance(created, AgentWorkCreated)
        assert await ship.store.claim_work_item("forge-2") is None  # an ensign
        assert await ship.store.claim_work_item("worf-1") is None  # another department
        issued = await ship.stops.issue_stop("forge-1", reason=STOP_REASON)
        try:
            assert await ship.store.claim_work_item("forge-1") is None  # stopped
            assert ship.stops.refused_counts(issued.record.stop_id) == {}  # a candidate question counts nothing
        finally:
            await ship.stops.lift_stop("forge-1", reason=LIFT_REASON)
        claimed = await ship.store.claim_work_item("forge-1")
        assert claimed is not None and claimed[0].id == created.work_item.id


# 13
async def test_without_a_gate_agent_work_is_never_ready_and_other_work_is_unchanged(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        created = await _request(ship, "pulaski-1")
        assert isinstance(created, AgentWorkCreated)
        plain = await ship.store.create_work_item(
            title="plain", metadata={"agent_pull": {"version": 1, "scope": "department", "department": "engineering"}},
        )
        assert set(await _discovered(ship, "forge-1")) == {created.work_item.id, plain.id}
        ship.store.set_agent_work_claim_gate(None)
        assert await _discovered(ship, "forge-1") == [plain.id]
        assert await _claimed(ship, "forge-1", created.work_item.id) is False
        ship.store.set_agent_work_claim_gate(ship.service.claim_allowed)
        assert created.work_item.id in await _discovered(ship, "forge-1")


# 14
async def test_a_stopped_requester_cannot_create_and_each_refusal_counts_at_agent_work(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        issued = await ship.stops.issue_stop("pulaski-1", reason=STOP_REASON)
        for refused in (await _self_task(ship, "pulaski-1"), await _request(ship, "pulaski-1")):
            assert _code(refused) == "agent_stopped"
            assert isinstance(refused, AgentWorkRefusal) and "CANARY" not in refused.detail
        assert ship.stops.refused_counts(issued.record.stop_id) == {"agent_work": 2}
        assert await ship.store.list_agent_work(False, None, 10) == []


# 15
async def test_a_stopped_claimant_is_refused_at_the_tool_and_the_request_stays_open(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        created = await _request(ship, "pulaski-1")
        assert isinstance(created, AgentWorkCreated)
        issued = await ship.stops.issue_stop("forge-1", reason=STOP_REASON)
        result = await _invoke(ship, "forge-1", "claim_work_item", {"work_item_id": created.work_item.id})
        assert result.error and "agent_stop" in result.metadata
        assert ship.stops.refused_counts(issued.record.stop_id) == {"tool": 1}
        still = await ship.store.get_work_item(created.work_item.id)
        assert still is not None and (still.status, still.assigned_to) == ("open", None)


# 16
async def test_depth_two_is_allowed_and_depth_three_is_refused(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        first = await _self_task(ship, "forge-1", title="depth one")
        assert isinstance(first, AgentWorkCreated)
        second = await _request(ship, "pulaski-1", title="depth two", spawned_from=first.work_item.id)
        assert isinstance(second, AgentWorkCreated)
        assert [created.work_item.metadata["agent_work"]["depth"] for created in (first, second)] == [1, 2]
        assert _code(await _self_task(ship, "forge-1", title="depth three", spawned_from=second.work_item.id)) == "depth_exceeded"
        captains = await ship.store.create_work_item(title="the Captain's task")
        under = await _self_task(ship, "forge-1", title="under the Captain", spawned_from=captains.id)
        assert isinstance(under, AgentWorkCreated) and under.work_item.metadata["agent_work"]["depth"] == 1
        assert _code(await _self_task(ship, "forge-1", title="orphan", spawned_from="no-such-item")) == "parent_unknown"


# 17
async def test_the_per_agent_cap_counts_open_items_only(tmp_path: Path) -> None:
    async with _ship(tmp_path, section=_section(max_open_per_agent=2)) as ship:
        first = await _self_task(ship, "forge-1", title="one")
        assert isinstance(first, AgentWorkCreated)
        assert isinstance(await _self_task(ship, "forge-1", title="two"), AgentWorkCreated)
        assert _code(await _self_task(ship, "forge-1", title="three")) == "agent_cap_reached"
        assert isinstance(await _self_task(ship, "laforge-1", title="another agent"), AgentWorkCreated)
        await ship.store.transition_work_item(first.work_item.id, "cancelled", source="ad1347-test")
        assert isinstance(await _self_task(ship, "forge-1", title="three"), AgentWorkCreated)


# 18
async def test_the_rate_counts_every_creation_in_the_trailing_hour(tmp_path: Path) -> None:
    now = [time.time()]
    async with _ship(tmp_path, section=_section(max_created_per_agent_per_hour=2), clock=lambda: now[0]) as ship:
        assert isinstance(await _self_task(ship, "forge-1", title="one"), AgentWorkCreated)
        assert isinstance(await _self_task(ship, "forge-1", title="two"), AgentWorkCreated)
        assert _code(await _self_task(ship, "forge-1", title="three")) == "rate_limited"
        now[0] += 3600  # the first two are exactly an hour old: still in the window
        assert _code(await _self_task(ship, "forge-1", title="three")) == "rate_limited"
        now[0] += 0.5
        assert isinstance(await _self_task(ship, "forge-1", title="three"), AgentWorkCreated)


# 19
async def test_the_department_and_ship_caps(tmp_path: Path) -> None:
    async with _ship(tmp_path / "department", section=_section(max_open_per_department=1)) as ship:
        assert isinstance(await _request(ship, "pulaski-1", title="first"), AgentWorkCreated)
        assert _code(await _request(ship, "ogawa-1", title="second")) == "department_cap_reached"
        assert isinstance(await _request(ship, "ogawa-1", title="second", department="security"), AgentWorkCreated)
    limits = _section(max_open_per_agent=2, max_open_per_department=2, max_open_ship=2)
    async with _ship(tmp_path / "ship", section=limits) as ship:
        assert isinstance(await _self_task(ship, "forge-1", title="first"), AgentWorkCreated)
        assert isinstance(await _self_task(ship, "laforge-1", title="second"), AgentWorkCreated)
        assert _code(await _self_task(ship, "worf-1", title="third")) == "ship_cap_reached"


# 20
async def test_an_open_request_with_the_same_department_tool_and_title_is_returned_and_watched(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        first = await _request(ship, "pulaski-1", title="Read the EventLog window")
        assert isinstance(first, AgentWorkCreated) and not first.deduplicated
        item_id = first.work_item.id
        for requester, title in (("ogawa-1", "  read the  EVENTLOG\twindow "), ("bones-1", "Ｒｅａｄ the EventLog window")):
            again = await _request(ship, requester, title=title)
            assert isinstance(again, AgentWorkCreated) and again.deduplicated and again.work_item.id == item_id, requester
        repeat = await _request(ship, "pulaski-1", title="Read the EventLog window")
        assert isinstance(repeat, AgentWorkCreated) and repeat.deduplicated and repeat.work_item.id == item_id
        assert set(await ship.store.list_work_watchers(item_id)) == {"ogawa-1", "bones-1"}  # never the requester
        assert await ship.store.add_work_watcher(item_id, "ogawa-1", time.time()) is False
        recipients = await ship.service.notice_recipients(item_id)
        assert recipients[0] == "pulaski-1" and set(recipients[1:]) == {"ogawa-1", "bones-1"} and len(recipients) == 3
        other_tool = await _request(ship, "pulaski-1", title="Read the EventLog window", tool_id="hull_survey")
        other_department = await _request(ship, "ogawa-1", title="Read the EventLog window", department="security")
        for created in (other_tool, other_department):
            assert isinstance(created, AgentWorkCreated) and not created.deduplicated and created.work_item.id != item_id
        await ship.store.transition_work_item(item_id, "cancelled", source="ad1347-test")
        reopened = await _request(ship, "bones-1", title="Read the EventLog window")
        assert isinstance(reopened, AgentWorkCreated) and not reopened.deduplicated


# 21
@pytest.mark.parametrize(("left", "right", "same"), [
    ("Read the log", "read  the LOG", True),
    ("Read the log", " Read\nthe\tlog ", True),
    ("Ｒｅａｄ", "read", True),
    ("Straße", "STRASSE", True),
    ("Read the log", "Read the logs", False),
    ("Read the log.", "Read the log", False),
], ids=["case-and-spaces", "whitespace-kinds", "nfkc", "casefold", "different-word", "punctuation-kept"])
def test_dedup_titles_are_compared_in_one_normal_form(left: str, right: str, same: bool) -> None:
    assert (normalize_title(left) == normalize_title(right)) is same


def _two_minutes_ago() -> float:
    return time.time() - 120


# 22
async def test_expiry_is_the_stores_sweep_and_each_notice_is_claimed_once_across_restarts(tmp_path: Path) -> None:
    """Premise 9: one owner of expiry (the store's tick), idempotent notices. Premise 10: every watcher is a recipient."""
    section = _section(ttl_seconds=60)
    async with _ship(tmp_path, section=section, clock=_two_minutes_ago) as ship:
        created = await _request(ship, "pulaski-1")
        watched = await _request(ship, "ogawa-1")
        assert isinstance(created, AgentWorkCreated) and isinstance(watched, AgentWorkCreated)
        assert watched.deduplicated and watched.work_item.id == created.work_item.id
        item_id = created.work_item.id
        assert item_id not in await _discovered(ship, "forge-1")  # past its TTL: not claimable before the sweep
        assert await ship.service.terminal_notices_due() == ()  # still open
    async with _ship(tmp_path, section=section, tick=0.05) as ship:
        expired = None
        for _ in range(200):
            expired = await ship.store.get_work_item(item_id)
            if expired is not None and expired.status == "cancelled":
                break
            await asyncio.sleep(0.05)
        assert expired is not None and expired.status == "cancelled"
        due = await ship.service.terminal_notices_due()
        assert {(notice.recipient, notice.outcome) for notice in due} == {("pulaski-1", "expired"), ("ogawa-1", "expired")}
        assert await ship.service.claim_notice(item_id, "pulaski-1") is True
        assert [notice.recipient for notice in await ship.service.terminal_notices_due()] == ["ogawa-1"]
        assert await ship.service.claim_notice(item_id, "ogawa-1") is True
        assert await ship.service.claim_notice(item_id, "ogawa-1") is False
        assert await ship.service.terminal_notices_due() == ()
    async with _ship(tmp_path, section=section) as ship:
        assert await ship.service.terminal_notices_due() == ()
        assert await ship.service.claim_notice(item_id, "pulaski-1") is False
        assert await ship.service.notice_recipients(item_id) == ("pulaski-1", "ogawa-1")


# 23
def test_the_service_owns_no_sweep_writes_no_status_and_never_names_the_captain() -> None:
    """Premises 8 and 9, on the module's syntax tree."""
    tree = ast.parse(Path(agent_work_module.__file__).read_text(encoding="utf-8"))
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called & {"transition_work_item", "create_task", "decide", "assign_work_item", "update_work_item"}
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Constant) and node.value == "captain"]


# 24
@pytest.mark.parametrize("change", [
    {"title": "   "}, {"title": "x" * 201}, {"reason": ""}, {"description": "d" * 4001},
    {"origin": "ward_room"}, {"spawned_from": ""},
], ids=["blank-title", "long-title", "blank-reason", "long-description", "origin-not-typed", "blank-parent"])
async def test_invalid_input_is_a_typed_refusal_and_writes_nothing(tmp_path: Path, change: dict[str, Any]) -> None:
    async with _ship(tmp_path) as ship:
        arguments: dict[str, Any] = {"title": "Check", "description": "", "reason": REASON, "origin": ORIGIN, **change}
        assert _code(await ship.service.create_self_task("forge-1", **arguments)) == "invalid_request"
        assert await ship.store.list_agent_work(False, None, 10) == []


# 25
async def test_the_text_limits_are_inclusive_and_an_origin_validates_itself(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        edge = await ship.service.create_self_task(
            "forge-1", title="t" * 200, description="d" * 4000, reason="r" * 500, origin=ORIGIN,
        )
        assert isinstance(edge, AgentWorkCreated) and edge.work_item.title == "t" * 200
    for bad in ({"channel": "telepathy"}, {"channel": "dm", "thread_id": "x" * 129}, {"channel": "dm", "post_id": " padded"}):
        with pytest.raises(ValueError):
            AgentWorkOrigin(**bad)


# 26
async def test_the_directory_reads_department_rank_and_chief_from_the_live_ship(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        members = {member.slot_id: member for member in ship.directory.members()}
        assert members["forge-1"] == CrewMember("forge-1", "builder", "engineering", "lieutenant", "laforge-1")
        assert members["forge-2"] == CrewMember("forge-2", "builder", "engineering", "ensign", "laforge-1")
        assert members["laforge-1"].chief_slot_id is None  # the first officer is wired, but in another department
        assert members["pulaski-1"].chief_slot_id == "bones-1"
        assert ship.directory.member("numberone-1") is None  # wired to a post, not a live agent
        await ship.agents["ogawa-1"].stop()
        assert ship.directory.member("ogawa-1") is None
        assert _code(await _request(ship, "pulaski-1", assignee="ogawa-1")) == "assignee_unknown"


# 27
def test_the_configuration_defaults_off_and_validates_at_parse_time() -> None:
    section = AgentWorkConfig()
    assert section.model_dump() == {
        "enabled": False, "max_open_per_agent": 3, "max_open_per_department": 8, "max_open_ship": 24,
        "max_created_per_agent_per_hour": 6, "ttl_seconds": 86_400, "max_depth": 2,
    }
    assert SystemConfig().agent_work == section
    assert AgentWorkConfig(max_open_per_agent=24, max_open_per_department=24, max_open_ship=24).max_open_ship == 24
    for bad in ({"max_open_per_agent": 25}, {"max_open_per_department": 25}, {"max_depth": 0}, {"ttl_seconds": 59}, {"max_open_ship": 0}):
        with pytest.raises(ValueError):
            AgentWorkConfig(**bad)


# 28
async def test_the_opener_builds_nothing_while_off_or_without_its_collaborators(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance 7. While off the opener touches nothing even with every collaborator present, so its own guard is
    pinned apart from the missing-collaborator branch, which also returns None (A3, F4: mutation row R4)."""
    path = tmp_path / "workforce.db"
    store = WorkItemStore(db_path=str(path), tick_interval=1000)
    await store.start()
    store_calls: list[str] = []

    async def _schema_spy() -> None:
        store_calls.append("ensure_agent_work_schema")

    def _gate_spy(gate: object) -> None:
        store_calls.append("set_agent_work_claim_gate")

    monkeypatch.setattr(store, "ensure_agent_work_schema", _schema_spy)
    monkeypatch.setattr(store, "set_agent_work_claim_gate", _gate_spy)
    try:
        before = _schema(path)
        off_directory = RuntimeCrewDirectory(
            agent_registry=await _make_registry([]), trust_network=TrustNetwork(), ontology=VesselOntologyService(_REPO / "config" / "ontology"),
        )
        off_stops = AgentStopService(data_dir=tmp_path / "stops")
        off = await open_agent_work_service(
            config=AgentWorkConfig(), store=store, tools=ToolRegistry(), identities=_SlotIdentities(()),
            directory=off_directory, stop_gate=off_stops,
        )
        assert off is None and _schema(path) == before
        assert store_calls == [], "while off the opener calls neither the schema nor the gate method"
        caplog.set_level(logging.WARNING, logger="probos.agent_work")
        missing = await open_agent_work_service(
            config=_section(), store=store, tools=ToolRegistry(), identities=_SlotIdentities(()),
            directory=None, stop_gate=None,
        )
        assert missing is None and _schema(path) == before and store_calls == []
        assert "missing: crew_directory, agent_stops" in caplog.text
    finally:
        await store.stop()


# 29
async def test_a_same_owner_replay_is_the_persisted_receipt_and_a_restriction_refuses_every_new_claim(
    tmp_path: Path,
) -> None:
    """Property 6 (A3, F2). Eligibility is asked at every discovery and every new claim, on both routes. A same-owner
    replay acquires nothing: it is AD-1187's receipt of a claim already persisted and precedes readiness, as it does
    when a trust requirement, a TTL or a dependency changes after the claim
    (``tests/test_ad1187_agent_work_pull.py::test_claim_replay_precedes_readiness_capacity_and_publication``).
    S3 asks again before it runs anything. Mutation row W7 is the gated replay."""
    async with _ship(tmp_path) as ship:
        first = await _request(ship, "pulaski-1")
        second = await _request(ship, "pulaski-1", title="Read the next EventLog window")
        assert isinstance(first, AgentWorkCreated) and isinstance(second, AgentWorkCreated)
        assert await _claimed(ship, "forge-1", first.work_item.id) is True
        await ship.permissions.issue_grant("forge-1", "event_log_query", ToolPermission.NONE, is_restriction=True)
        owned = await ship.store.get_work_item(first.work_item.id)
        assert owned is not None and owned.assigned_to == "forge-1"
        assert ship.service.claim_allowed(
            owned, BookableResource(resource_id="forge-1", agent_type="builder", department="", capacity=5, characteristics=[]),
        ) is False, "premise: the gate asked directly refuses forge-1 now"
        assert await _claimed(ship, "forge-1", first.work_item.id) is True  # the receipt of what is already persisted
        assert second.work_item.id not in await _discovered(ship, "forge-1")
        assert await _claimed(ship, "forge-1", second.work_item.id) is False
        assert await ship.store.claim_work_item("forge-1") is None  # the legacy route
        assert await _claimed(ship, "laforge-1", second.work_item.id) is True  # the restriction is forge-1's alone


_SURROGATE = json.loads('"\\ud800"')  # what a JSON body's "\ud800" decodes to: a str that UTF-8 cannot encode
_SURROGATE_CASES = [
    *(("self_task", field) for field in ("requester", "title", "description", "reason", "tool_id", "spawned_from")),
    *(("request", field) for field in (
        "requester", "title", "description", "reason", "tool_id", "assignee", "department", "spawned_from",
    )),
]


# 30
@pytest.mark.parametrize(("method", "field"), _SURROGATE_CASES, ids=[f"{method}-{field}" for method, field in _SURROGATE_CASES])
async def test_a_value_utf8_cannot_encode_is_a_typed_refusal_and_writes_nothing(
    tmp_path: Path, method: str, field: str,
) -> None:
    """A3 (F3). SQLite's bind and the dedup key's sha256 raise on an unpaired surrogate, and a field that reaches
    neither would be stored as poisoned provenance. Every text and id input of both create methods is refused as
    invalid_request before any lookup or write; the same call with the clean value then creates."""
    async with _ship(tmp_path) as ship:
        parent = await ship.store.create_work_item(title="An ordinary parent")
        clean: dict[str, Any] = {
            "requester": "forge-1" if method == "self_task" else "pulaski-1", "title": "Check the window",
            "description": "", "reason": REASON, "origin": ORIGIN, "tool_id": "event_log_query",
            "spawned_from": parent.id,
        }
        if method == "request":
            clean.update(assignee="forge-1", department="engineering")
        create: Callable[..., Any] = ship.service.create_self_task if method == "self_task" else ship.service.request_work
        poisoned = {**clean, field: f"{clean[field]}{_SURROGATE}"}
        assert _code(await create(poisoned.pop("requester"), **poisoned)) == "invalid_request"
        assert await ship.store.list_agent_work(False, None, 10) == []
        assert isinstance(await create(clean.pop("requester"), **clean), AgentWorkCreated)


# 31
@pytest.mark.parametrize("field", ["thread_id", "post_id"])
def test_an_origin_refuses_an_id_utf8_cannot_encode(field: str) -> None:
    """A3 (F3). The caller builds the origin (S2's parser), so the origin's own ValueError is the refusal; the create
    methods accept only an AgentWorkOrigin (test 24), so an id that cannot be stored never reaches the service."""
    with pytest.raises(ValueError, match="agent_work_origin_id_invalid"):
        AgentWorkOrigin("ward_room", **{field: f"51d91a7d{_SURROGATE}"})
    assert AgentWorkOrigin("ward_room", **{field: "51d91a7d"}).to_dict()[field] == "51d91a7d"


_OPTIONAL_ID_CASES = [("self_task", "tool_id"), ("request", "tool_id"), ("request", "assignee"), ("request", "department")]


# 32
@pytest.mark.parametrize(("method", "field"), _OPTIONAL_ID_CASES, ids=[f"{method}-{field}" for method, field in _OPTIONAL_ID_CASES])
async def test_a_malformed_optional_id_is_refused_before_the_requester_the_stop_or_the_parent(
    tmp_path: Path, method: str, field: str,
) -> None:
    """A4 (R2-2). The optional ids are input like the text: a malformed one is invalid_request before the requester
    is resolved, the Captain's stop is asked or the parent is read. Each clean control shows the refusal it would
    otherwise meet; a stopped requester's malformed attempt is not counted at agent_work, as malformed text is not."""
    async with _ship(tmp_path) as ship:
        create: Callable[..., Any] = ship.service.create_self_task if method == "self_task" else ship.service.request_work
        member = "forge-1" if method == "self_task" else "pulaski-1"
        clean: dict[str, Any] = {
            "title": "Check the window", "description": "", "reason": REASON, "origin": ORIGIN,
            "tool_id": "event_log_query",
        }
        poisoned = {**clean, field: f"event_log_query{_SURROGATE}"}
        for requester, extra, earlier in (
            ("ghost-1", {}, "requester_unresolved"),
            (member, {"spawned_from": "no-such-parent"}, "parent_unknown"),
        ):
            assert _code(await create(requester, **poisoned, **extra)) == "invalid_request"
            assert _code(await create(requester, **clean, **extra)) == earlier, "premise: the earlier refusal"
        issued = await ship.stops.issue_stop(member, reason=STOP_REASON)
        assert _code(await create(member, **poisoned)) == "invalid_request"
        assert ship.stops.refused_counts(issued.record.stop_id) == {}, "a malformed attempt is not a stop refusal"
        assert _code(await create(member, **clean)) == "agent_stopped", "premise: the stop refuses the clean call"
        assert ship.stops.refused_counts(issued.record.stop_id) == {"agent_work": 1}
        assert await ship.store.list_agent_work(False, None, 10) == []
