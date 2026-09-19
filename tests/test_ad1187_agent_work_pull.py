"""AD-1187: governed ready-work admission and its actual agent consumer."""

from __future__ import annotations

import asyncio
import ast
import dataclasses
import json
import sqlite3
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Literal, Sequence

import pytest
import httpx
from fastapi import FastAPI

from probos.protocols import DatabaseConnection
from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor
from probos.cognitive.swe_harness.agentic_loop import AgenticLoop, AgenticResult, truncate_tool_output
from probos.cognitive.swe_harness.tool_call import (
    TextBlock, ToolCallRequest, ToolUseBlock, render_tool_output,
)
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime
from probos.routers.deps import get_runtime
from probos.routers.workforce import router as workforce_router
from probos.startup.communication import init_communication
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.substrate.registry import AgentRegistry
from probos.tools.protocol import ToolPermission, ToolResult, ToolResultPresentation, ToolType
from probos.tools.executor import ToolExecutor
from probos.tools.registry import ToolRegistry
from probos.tools.work_item_pull_tool import ClaimWorkItemTool, DiscoverWorkItemsTool
from probos.tools.work_item_status_tool import WorkItemStatusTool
from probos.types import LLMRequest, LLMResponse
from probos.workforce import (
    BookableResource, Booking, CrewSessionParentCreate, ReadyWorkPage, WorkItem, WorkItemStore,
)


_PUBLICATION = {"agent_pull": {"version": 1, "scope": "ship"}}


class _Authority:
    def __init__(self) -> None:
        self.resources = {"agent-a": _resource(), "agent-b": _resource("agent-b")}
        self.calls: list[tuple[str, str, bool]] = []
        self.denied = False

    def __call__(
        self, resource_id: str,
        action: Literal["discover", "claim", "assign", "resume"],
        agent_pull: bool,
    ) -> BookableResource | None:
        self.calls.append((resource_id, action, agent_pull))
        return None if self.denied else self.resources.get(resource_id)


class _Connection:
    def __init__(self, delegate: DatabaseConnection) -> None:
        self._delegate = delegate
        self.fail_sql = ""
        self.fail_rollback = False
        self.refuse_sql = ""
        self.pause_sql = ""
        self.reached = asyncio.Event()
        self.release = asyncio.Event()
        self.statements: list[str] = []

    @property
    def row_factory(self) -> Any:
        return self._delegate.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._delegate.row_factory = value

    async def execute(self, sql: str, parameters: Sequence[Any] = ()) -> Any:
        self.statements.append(sql)
        if self.fail_rollback and sql == "ROLLBACK":
            raise RuntimeError("injected_rollback_failure")
        if self.fail_sql and self.fail_sql in sql:
            raise RuntimeError("injected_database_failure")
        if self.pause_sql and self.pause_sql in sql:
            self.reached.set()
            await self.release.wait()
        if self.refuse_sql and self.refuse_sql in sql:
            sql += " AND 0"
        return await self._delegate.execute(sql, parameters)

    async def executemany(self, sql: str, parameters: Iterable[Sequence[Any]]) -> Any:
        return await self._delegate.executemany(sql, parameters)

    async def executescript(self, sql_script: str) -> None:
        await self._delegate.executescript(sql_script)

    async def fetchone(self) -> Any:
        return await self._delegate.fetchone()

    async def fetchall(self) -> Any:
        return await self._delegate.fetchall()

    async def commit(self) -> None:
        self.statements.append("COMMIT")
        if self.fail_sql == "COMMIT":
            raise RuntimeError("injected_database_failure")
        await self._delegate.commit()

    async def close(self) -> None:
        await self._delegate.close()


class _Factory:
    def __init__(self) -> None:
        self.connection: _Connection | None = None

    async def connect(self, db_path: str) -> DatabaseConnection:
        self.connection = _Connection(await SQLiteConnectionFactory().connect(db_path))
        return self.connection


@dataclasses.dataclass
class _Agent:
    id: str = "agent-a"
    agent_type: str = "scout"
    agent_uuid: str = ""
    department: str = "untrusted-agent-department"
    is_alive: bool = True
    pool: str = "scout"
    instructions: str = "Choose only work you intend to own."


class _Trust:
    def __init__(self) -> None:
        self.score: Any = 0.75

    def get_score(self, agent_id: str) -> float:
        return self.score


class _Ontology:
    def get_agent_department(self, agent_type: str) -> str:
        return "science"


class _Instrument:
    name = "Temporary authority fixture"
    tool_type = ToolType.INFRA_SERVICE
    description = "Authority-only fixture."
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(self, tool_id: str) -> None:
        self.tool_id = tool_id

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        raise AssertionError("Authority fixture must not execute")


@pytest.fixture
def db_factory() -> _Factory:
    return _Factory()


@pytest.fixture
def workforce_events() -> list[tuple[str, dict[str, Any]]]:
    return []


@pytest.fixture
async def runtime(
    db_factory: _Factory, workforce_events: list[tuple[str, dict[str, Any]]],
) -> AsyncIterator[ProbOSRuntime]:
    runtime = object.__new__(ProbOSRuntime)
    runtime.config = SystemConfig()
    runtime.registry = AgentRegistry()
    runtime.ontology = _Ontology()
    runtime.trust_network = _Trust()
    runtime.tool_registry = ToolRegistry()
    for tool_id, permission in (("discover_work_items", "read"), ("claim_work_item", "write")):
        runtime.tool_registry.register(
            _Instrument(tool_id),
            allowed_departments=("science", "engineering", "medical", "security", "operations", "bridge"),
            default_permissions={
                rank: permission for rank in ("ensign", "lieutenant", "commander", "senior_officer")
            },
        )
    await runtime.registry.register(_Agent())
    runtime.work_item_store = WorkItemStore(
        db_path=":memory:", tick_interval=1000,
        connection_factory=db_factory,
        emit_event=lambda event, data: workforce_events.append((event, data)),
        pull_resource_resolver=runtime.resolve_workforce_pull_resource,
    )
    runtime.work_item_store.register_resource(_resource())
    await runtime.work_item_store.start()
    try:
        yield runtime
    finally:
        await runtime.work_item_store.stop()


def _resource(resource_id: str = "agent-a", *, capacity: int = 1) -> BookableResource:
    return BookableResource(
        resource_id=resource_id,
        agent_type="scout",
        department="science",
        capacity=capacity,
        characteristics=[
            {"skill": "scout", "proficiency": 1.0},
            {"skill": "science", "proficiency": 1.0},
            {"skill": "trust", "proficiency": 0.75},
        ],
    )


@pytest.fixture
async def pull_store() -> AsyncIterator[WorkItemStore]:
    store = WorkItemStore(db_path=":memory:", tick_interval=1000)
    store.register_resource(_resource())
    store.register_resource(_resource("agent-b"))
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


@pytest.fixture
def authority() -> _Authority:
    return _Authority()


@pytest.fixture
async def governed_store(authority: _Authority) -> AsyncIterator[WorkItemStore]:
    store = WorkItemStore(
        db_path=":memory:", tick_interval=1000, pull_resource_resolver=authority,
    )
    for resource in authority.resources.values():
        store.register_resource(dataclasses.replace(resource))
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


async def test_claim_competing_agents_persists_one_owner(pull_store: WorkItemStore) -> None:
    item = await pull_store.create_work_item(title="One open row")
    assert item.status == "open" and item.assigned_to is None
    assert await pull_store.list_bookings(work_item_id=item.id) == []

    results = await asyncio.wait_for(asyncio.gather(
        pull_store.claim_work_item("agent-a"),
        pull_store.claim_work_item("agent-b"),
    ), timeout=5)

    assert sum(result is not None for result in results) == 1
    bookings = await pull_store.list_bookings(work_item_id=item.id)
    stored = await pull_store.get_work_item(item.id)
    assert len(bookings) == 1
    assert stored is not None and stored.assigned_to == bookings[0].resource_id


async def test_assign_occupied_row_preserves_owner(pull_store: WorkItemStore) -> None:
    item = await pull_store.create_work_item(title="Owned")
    first = await pull_store.assign_work_item(item.id, "agent-a")
    assert first is not None

    second = await pull_store.assign_work_item(item.id, "agent-b")

    assert second is None
    stored = await pull_store.get_work_item(item.id)
    assert stored is not None and stored.assigned_to == "agent-a"
    assert [b.id for b in await pull_store.list_bookings(work_item_id=item.id)] == [first.id]


async def test_claim_capacity_counts_beyond_snapshot(pull_store: WorkItemStore) -> None:
    owned = await pull_store.create_work_item(title="Old occupied capacity")
    booking = await pull_store.assign_work_item(owned.id, "agent-a")
    assert booking is not None
    pull_store.register_resource(_resource("agent-b", capacity=101))
    for index in range(101):
        item = await pull_store.create_work_item(title=f"Unrelated {index}")
        assert await pull_store.assign_work_item(item.id, "agent-b") is not None
    snapshot = pull_store.snapshot()["bookings"]
    assert len(snapshot) == 100
    assert all(row["resource_id"] != "agent-a" for row in snapshot)
    target = await pull_store.create_work_item(title="Must stay open")

    assert await pull_store.claim_work_item("agent-a") is None
    stored = await pull_store.get_work_item(target.id)
    assert stored is not None and stored.assigned_to is None


@pytest.mark.parametrize("fields", [
    {"depends_on": ["missing-dependency"]},
    {"ttl_seconds": 1, "created_at": 1.0},
    {"parent_id": "crew-parent"},
    {"metadata": {"crew_session": {"thread_id": "room"}}},
])
async def test_claim_nonready_row_is_not_admitted(
    pull_store: WorkItemStore, fields: dict[str, Any],
) -> None:
    item = await pull_store.create_work_item(title="Not ready", **fields)
    assert item.status == "open" and item.assigned_to is None
    assert await pull_store.list_bookings(work_item_id=item.id) == []

    assert await pull_store.claim_work_item("agent-a") is None


async def test_resume_rechecks_released_capacity(pull_store: WorkItemStore) -> None:
    first = await pull_store.create_work_item(title="Paused")
    paused = await pull_store.assign_work_item(first.id, "agent-a")
    assert paused is not None
    assert await pull_store.start_booking(paused.id) is not None
    assert (await pull_store.pause_booking(paused.id)).status == "on_break"
    second = await pull_store.create_work_item(title="New owner of capacity")
    admitted = await pull_store.claim_work_item("agent-a")
    assert admitted is not None and admitted[0].id == second.id

    assert await pull_store.resume_booking(paused.id) is None
    assert (await pull_store.get_booking(paused.id)).status == "on_break"


async def test_discovery_empty_board_returns_frozen_page(governed_store: WorkItemStore) -> None:
    page = await governed_store.list_claimable_work_items("agent-a")
    assert page == ReadyWorkPage((), None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        page.next_offset = 1


@pytest.mark.parametrize("query", [
    {"limit": True}, {"limit": 0}, {"limit": 51}, {"limit": 1.0},
    {"offset": True}, {"offset": -1}, {"offset": "0"},
    {"work_type": ""}, {"work_type": 7}, {"work_type": "x" * 65},
])
async def test_discovery_invalid_bounds_raise(
    governed_store: WorkItemStore, query: dict[str, Any],
) -> None:
    with pytest.raises(ValueError, match="work_pull_query_invalid"):
        await governed_store.list_claimable_work_items("agent-a", **query)


@pytest.mark.parametrize("metadata", [
    {}, {"agent_pull": None}, {"agent_pull": True},
    {"agent_pull": {"version": True, "scope": "ship"}},
    {"agent_pull": {"version": 2, "scope": "ship"}},
    {"agent_pull": {"version": 1, "scope": "private"}},
    {"agent_pull": {"version": 1, "scope": "ship", "extra": "private"}},
    {"agent_pull": {"version": 1, "scope": "department"}},
    {"agent_pull": {"version": 1, "scope": "department", "department": "engineering"}},
])
async def test_discovery_private_rows_and_exact_claim_are_denied(
    governed_store: WorkItemStore, metadata: dict[str, Any],
) -> None:
    item = await governed_store.create_work_item(title="Private", metadata=metadata)
    assert item.status == "open" and item.assigned_to is None

    assert await governed_store.list_claimable_work_items("agent-a") == ReadyWorkPage((), None)
    assert await governed_store.claim_work_item(
        "agent-a", work_item_id=item.id, agent_pull=True,
    ) is None
    assert await governed_store.list_bookings(work_item_id=item.id) == []


async def test_discovery_department_and_dependency_done_convention(
    governed_store: WorkItemStore,
) -> None:
    dependency = await governed_store.create_work_item(title="Dependency")
    metadata = {"agent_pull": {"version": 1, "scope": "department", "department": "science"}}
    item = await governed_store.create_work_item(
        title="Public after done", metadata=metadata, depends_on=[dependency.id],
    )
    assert (await governed_store.list_claimable_work_items("agent-a")).items == ()
    await governed_store.update_work_item(dependency.id, status="done")

    page = await governed_store.list_claimable_work_items("agent-a")

    assert [row.id for row in page.items] == [item.id]
    assert page.next_offset is None
    result = await governed_store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
    assert result is not None and result[0].id == item.id


async def test_discovery_scans_past_fifty_and_reports_empty_continuation(
    governed_store: WorkItemStore,
) -> None:
    for index in range(205):
        await governed_store.create_work_item(
            id=f"blocked-{index:03}", title="Trust gated", trust_requirement=0.95,
            metadata=_PUBLICATION, created_at=1.0,
        )
    target = await governed_store.create_work_item(
        id="selected-row", title="Eligible after row 205", metadata=_PUBLICATION, created_at=1.0,
    )
    all_rows = await governed_store.list_work_items(limit=300)
    assert len(all_rows) == 206
    assert all(row.status == "open" for row in all_rows)

    first = await governed_store.list_claimable_work_items("agent-a")
    assert first.items == () and first.next_offset == 200
    second = await governed_store.list_claimable_work_items("agent-a", offset=first.next_offset)
    assert [row.id for row in second.items] == [target.id]
    assert second.next_offset is None
    result = await governed_store.claim_work_item("agent-a", work_item_id=target.id, agent_pull=True)
    assert result is not None and result[0].id == target.id


async def test_discovery_default_maximum_and_stable_ties(governed_store: WorkItemStore) -> None:
    for index in reversed(range(51)):
        await governed_store.create_work_item(
            id=f"tie-{index:03}", title="Tie", created_at=1.0, metadata=_PUBLICATION,
        )
    default = await governed_store.list_claimable_work_items("agent-a")
    assert [item.id for item in default.items] == [f"tie-{index:03}" for index in range(20)]
    assert default.next_offset == 20
    maximum = await governed_store.list_claimable_work_items("agent-a", limit=50)
    assert len(maximum.items) == 50 and maximum.next_offset == 50
    last = await governed_store.list_claimable_work_items("agent-a", offset=50, limit=50)
    assert [item.id for item in last.items] == ["tie-050"] and last.next_offset is None
    assert (await governed_store.list_claimable_work_items("agent-a", work_type="duty")).items == ()


async def test_claim_selected_id_never_falls_through(governed_store: WorkItemStore) -> None:
    selected = await governed_store.create_work_item(title="Selected", metadata=_PUBLICATION)
    other = await governed_store.create_work_item(title="Other", metadata=_PUBLICATION)
    assert await governed_store.assign_work_item(selected.id, "agent-b") is not None
    for wanted in (selected.id, selected.id[:8], "missing"):
        assert await governed_store.claim_work_item(
            "agent-a", work_item_id=wanted, agent_pull=True,
        ) is None
    assert (await governed_store.get_work_item(other.id)).assigned_to is None


async def test_claim_replay_precedes_readiness_capacity_and_publication(
    governed_store: WorkItemStore, authority: _Authority,
) -> None:
    item = await governed_store.create_work_item(
        title="Replay", metadata=_PUBLICATION, trust_requirement=0.7,
    )
    fresh = await governed_store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
    assert fresh is not None
    await governed_store.update_work_item(
        item.id, metadata={}, ttl_seconds=1, created_at=time.time() - 10,
        depends_on=["now-missing"], trust_requirement=0.99,
    )
    authority.resources["agent-a"] = dataclasses.replace(
        _resource(), characteristics=[{"skill": "trust", "proficiency": 0.1}],
    )
    replay = await governed_store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
    assert replay is not None and replay[1] == fresh[1]
    assert len(await governed_store.list_bookings(work_item_id=item.id)) == 1
    assert (await governed_store.list_claimable_work_items("agent-a")).items == ()
    assert await governed_store.start_booking(fresh[1].id) is not None
    assert await governed_store.pause_booking(fresh[1].id) is not None
    paused = await governed_store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
    assert paused is not None and paused[1].status == "on_break"
    authority.denied = True
    with pytest.raises(PermissionError, match="authority_denied"):
        await governed_store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)


@pytest.mark.parametrize("terminal", ["done", "failed", "cancelled"])
async def test_claim_terminal_owner_does_not_reacquire(
    governed_store: WorkItemStore, terminal: str,
) -> None:
    item = await governed_store.create_work_item(title="Terminal", metadata=_PUBLICATION)
    fresh = await governed_store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
    assert fresh is not None
    await governed_store.update_work_item(item.id, status=terminal)
    assert await governed_store.claim_work_item(
        "agent-a", work_item_id=item.id, agent_pull=True,
    ) is None
    assert len(await governed_store.list_bookings(work_item_id=item.id)) == 1


async def test_claim_cancelled_or_unassigned_booking_does_not_reacquire(
    governed_store: WorkItemStore,
) -> None:
    item = await governed_store.create_work_item(title="Cancelled", metadata=_PUBLICATION)
    fresh = await governed_store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
    assert fresh is not None
    assert await governed_store.unassign_work_item(item.id)
    assert (await governed_store.get_booking(fresh[1].id)).status == "cancelled"
    assert await governed_store.claim_work_item(
        "agent-a", work_item_id=item.id, agent_pull=True,
    ) is None


async def test_authority_resolver_denial_never_uses_cached_resource(
    governed_store: WorkItemStore, authority: _Authority,
) -> None:
    item = await governed_store.create_work_item(title="Fresh authority", metadata=_PUBLICATION)
    assert governed_store.get_resource("agent-a").active is True
    authority.denied = True
    with pytest.raises(PermissionError):
        await governed_store.list_claimable_work_items("agent-a")
    with pytest.raises(PermissionError):
        await governed_store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
    assert await governed_store.claim_work_item("agent-a") is None
    assert await governed_store.assign_work_item(item.id, "agent-a", source="agent") is None
    assert authority.calls == [
        ("agent-a", "discover", True), ("agent-a", "claim", True),
        ("agent-a", "claim", False), ("agent-a", "assign", False),
    ]


async def test_standalone_agent_mode_requires_resolver(pull_store: WorkItemStore) -> None:
    item = await pull_store.create_work_item(title="No runtime", metadata=_PUBLICATION)
    with pytest.raises(PermissionError):
        await pull_store.list_claimable_work_items("agent-a")
    with pytest.raises(PermissionError):
        await pull_store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
    assert await pull_store.assign_work_item(item.id, "agent-a", source="agent") is not None


@pytest.mark.parametrize("race", ["item", "capacity", "resume"])
async def test_admission_separate_connections_share_one_capacity_transaction(
    tmp_path: Path, race: str,
) -> None:
    path = str(tmp_path / "admission.db")
    stores = [WorkItemStore(db_path=path, tick_interval=1000) for _ in range(2)]
    try:
        for store in stores:
            await store.start()
            store.register_resource(_resource())
            store.register_resource(_resource("agent-b"))
        first = await stores[0].create_work_item(title="First")
        second = await stores[0].create_work_item(title="Second")
        if race == "resume":
            booking = await stores[0].assign_work_item(first.id, "agent-a")
            assert booking is not None
            await stores[0].start_booking(booking.id)
            await stores[0].pause_booking(booking.id)
            calls = [
                stores[0].resume_booking(booking.id),
                stores[1].claim_work_item("agent-a", work_item_id=second.id),
            ]
        else:
            calls = [
                stores[0].claim_work_item("agent-a", work_item_id=first.id),
                stores[1].claim_work_item(
                    "agent-b" if race == "item" else "agent-a",
                    work_item_id=first.id if race == "item" else second.id,
                ),
            ]
        results = await asyncio.wait_for(asyncio.gather(*calls), timeout=5)
        assert sum(result is not None for result in results) == 1
        rows = await stores[1].list_bookings(limit=1000)
        active = [row for row in rows if row.status in ("active", "scheduled")]
        assert len(active) == 1
        persisted = await stores[1].get_work_item(active[0].work_item_id)
        assert persisted.assigned_to == active[0].resource_id
    finally:
        for store in reversed(stores):
            await store.stop()


@pytest.mark.parametrize("cancel", [False, True])
async def test_admission_fault_or_cancellation_rolls_back_every_row(cancel: bool) -> None:
    factory = _Factory()
    store = WorkItemStore(db_path=":memory:", tick_interval=1000, connection_factory=factory)
    await store.start()
    try:
        store.register_resource(_resource())
        item = await store.create_work_item(title="Rollback")
        connection = factory.connection
        assert connection is not None
        marker = "INSERT INTO booking_timestamps"
        if cancel:
            connection.pause_sql = marker
            task = asyncio.create_task(store.claim_work_item("agent-a"))
            try:
                await asyncio.wait_for(connection.reached.wait(), timeout=3)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                connection.release.set()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        else:
            connection.fail_sql = marker
            with pytest.raises(RuntimeError, match="injected_database_failure"):
                await store.claim_work_item("agent-a")
        assert "ROLLBACK" in connection.statements
        assert (await store.get_work_item(item.id)).assigned_to is None
        assert await store.list_bookings(work_item_id=item.id) == []
        requirements = await connection.execute(
            "SELECT fulfilled FROM resource_requirements WHERE work_item_id = ?", (item.id,),
        )
        assert [row[0] for row in await requirements.fetchall()] == [0]
        timestamps = await connection.execute("SELECT COUNT(*) FROM booking_timestamps")
        assert (await timestamps.fetchone())[0] == 0
        connection.fail_sql = connection.pause_sql = ""
        assert await store.claim_work_item("agent-a") is not None
    finally:
        await store.stop()


async def test_runtime_resolver_uses_current_trust_department_and_store_capacity(
    runtime: ProbOSRuntime,
) -> None:
    store = runtime.work_item_store
    resource = store.get_resource("agent-a")
    resource.capacity = 3
    assert resource.characteristics[-1]["proficiency"] == 0.75
    assert runtime.registry.get("agent-a").department != "science"
    runtime.trust_network.score = 0.2

    resolved = runtime.resolve_workforce_pull_resource("agent-a", "discover", True)

    assert resolved is not None and resolved is not resource
    assert resolved.department == "science" and resolved.capacity == 3
    assert resolved.characteristics == [
        {"skill": "scout", "proficiency": 1.0},
        {"skill": "trust", "proficiency": 0.2},
        {"skill": "science", "proficiency": 1.0},
    ]
    assert resource.characteristics[-1]["proficiency"] == 0.75
    resource.active = False
    assert runtime.resolve_workforce_pull_resource("agent-a", "discover", True) is None


@pytest.mark.parametrize("action", ["claim", "assign"])
async def test_legacy_admission_current_trust_drop_rejects_cached_eligibility(
    runtime: ProbOSRuntime, action: str,
) -> None:
    store = runtime.work_item_store
    item = await store.create_work_item(title="Current trust", trust_requirement=0.7)
    assert store.get_resource("agent-a").characteristics[-1]["proficiency"] == 0.75
    runtime.trust_network.score = 0.1
    result = (
        await store.claim_work_item("agent-a")
        if action == "claim"
        else await store.assign_work_item(item.id, "agent-a")
    )
    assert result is None
    assert (await store.get_work_item(item.id)).assigned_to is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1, True, "0.75", None])
async def test_runtime_resolver_malformed_trust_denies(
    runtime: ProbOSRuntime, value: Any,
) -> None:
    runtime.trust_network.score = value
    assert runtime.resolve_workforce_pull_resource("agent-a", "discover", True) is None
    assert runtime.resolve_workforce_pull_resource("agent-a", "assign", False) is None


async def test_runtime_resolver_unknown_inactive_ambiguous_and_uuid_fail_closed(
    runtime: ProbOSRuntime,
) -> None:
    assert runtime.resolve_workforce_pull_resource("missing", "claim", True) is None
    agent = runtime.registry.get("agent-a")
    agent.is_alive = False
    assert runtime.resolve_workforce_pull_resource("agent-a", "claim", True) is None
    agent.is_alive = True
    await runtime.registry.register(_Agent(id="agent-b", agent_uuid="agent-a"))
    assert runtime.resolve_workforce_pull_resource("agent-a", "claim", True) is None
    assert runtime.resolve_workforce_pull_resource("agent-a", "assign", False) is None
    await runtime.registry.unregister("agent-b")
    agent.agent_uuid = "distinct-uuid"
    runtime.work_item_store.register_resource(_resource("distinct-uuid"))
    assert runtime.resolve_workforce_pull_resource("distinct-uuid", "claim", True) is None
    assert runtime.resolve_workforce_pull_resource("agent-a", "claim", True) is None
    # Legacy Captain assignment retains its exact registered resource key.
    assert runtime.resolve_workforce_pull_resource("distinct-uuid", "assign", False) is not None


async def test_runtime_resolver_requires_current_write_permission_only_in_agent_mode(
    runtime: ProbOSRuntime,
) -> None:
    registration = runtime.tool_registry.get("claim_work_item")
    registration.default_permissions = {
        rank: "read" for rank in ("ensign", "lieutenant", "commander", "senior_officer")
    }
    assert runtime.resolve_workforce_pull_resource("agent-a", "claim", True) is None
    assert runtime.resolve_workforce_pull_resource("agent-a", "discover", True) is not None
    assert runtime.resolve_workforce_pull_resource("agent-a", "assign", False) is not None
    assert runtime.resolve_workforce_pull_resource("agent-a", "claim", False) is not None


async def test_runtime_resolver_loto_and_restriction_are_current(runtime: ProbOSRuntime) -> None:
    registration = runtime.tool_registry.get("claim_work_item")
    registration.concurrency = "exclusive"
    assert runtime.tool_registry.acquire_lock("claim_work_item", "agent-b", "Owned lock")
    assert runtime.resolve_workforce_pull_resource("agent-a", "claim", True) is None
    assert runtime.tool_registry.release_lock("claim_work_item", "agent-b")
    assert runtime.resolve_workforce_pull_resource("agent-a", "claim", True) is not None
    registration.restricted_to = ["agent-b"]
    assert runtime.resolve_workforce_pull_resource("agent-a", "claim", True) is None


async def test_discovery_item_offsets_track_filtered_rows(governed_store: WorkItemStore) -> None:
    for index in range(8):
        await governed_store.create_work_item(
            id=f"offset-{index}", title="Offset", created_at=1.0,
            trust_requirement=0.99 if index % 2 == 0 else 0.0,
            metadata=_PUBLICATION,
        )

    page = await governed_store.list_claimable_work_items("agent-a", offset=2, limit=2)

    assert [item.id for item in page.items] == ["offset-3", "offset-5"]
    assert page.item_offsets == (3, 5)
    assert page.next_offset == 6
    tail = await governed_store.list_claimable_work_items("agent-a", offset=page.next_offset)
    assert tail.item_offsets == (7,)
    assert tail.next_offset is None


async def test_claim_preparation_uses_actual_plan_before_first_write() -> None:
    factory = _Factory()
    store = WorkItemStore(db_path=":memory:", connection_factory=factory, tick_interval=1000)
    await store.start()
    try:
        store.register_resource(_resource())
        item = await store.create_work_item(title="Prepared")
        connection = factory.connection
        assert connection is not None
        connection.statements.clear()
        prepared: list[tuple[dict[str, Any], dict[str, Any]]] = []

        def prepare(planned_item: WorkItem, booking: Booking) -> None:
            assert not any(
                sql.lstrip().startswith(("UPDATE", "INSERT", "DELETE"))
                for sql in connection.statements
            )
            assert planned_item.id == item.id
            assert planned_item.assigned_to == booking.resource_id == "agent-a"
            assert planned_item.status == booking.status == "scheduled"
            assert booking.work_item_id == item.id and booking.requirement_id
            prepared.append((planned_item.to_dict(), booking.to_dict()))

        result = await store.claim_work_item("agent-a", work_item_id=item.id, prepare_claim=prepare)

        assert result is not None
        assert prepared == [(result[0].to_dict(), result[1].to_dict())]
        assert (await store.get_booking(result[1].id)).to_dict() == prepared[0][1]
    finally:
        await store.stop()


@pytest.mark.parametrize("refusal", ["raise", "return", "mutate"])
async def test_claim_preparation_refusal_has_no_mutation_sql(refusal: str) -> None:
    factory = _Factory()
    events: list[str] = []
    store = WorkItemStore(
        db_path=":memory:", connection_factory=factory, tick_interval=1000,
        emit_event=lambda event, data: events.append(event),
    )
    await store.start()
    try:
        store.register_resource(_resource())
        item = await store.create_work_item(title="No writes")
        connection = factory.connection
        assert connection is not None
        connection.statements.clear()
        events.clear()

        def prepare(planned_item: WorkItem, booking: Booking) -> None:
            if refusal == "raise":
                raise ValueError("test_budget_refusal")
            if refusal == "mutate":
                booking.resource_id = "agent-b"
            else:
                return "not-a-readonly-validation"  # type: ignore[return-value]

        with pytest.raises(ValueError, match="test_budget_refusal|work_pull_preparation_invalid"):
            await store.claim_work_item("agent-a", prepare_claim=prepare)

        assert "ROLLBACK" in connection.statements
        assert not any(
            sql.lstrip().startswith(("UPDATE", "INSERT", "DELETE"))
            for sql in connection.statements
        )
        assert (await store.get_work_item(item.id)).to_dict() == item.to_dict()
        assert await store.list_bookings(work_item_id=item.id) == []
        assert events == []
    finally:
        await store.stop()


@pytest.mark.parametrize("marker", [
    "UPDATE work_items SET assigned_to", "UPDATE resource_requirements",
    "INSERT INTO bookings", "INSERT INTO booking_timestamps", "COMMIT",
])
async def test_claim_postpreparation_failure_rolls_back(marker: str) -> None:
    factory = _Factory()
    store = WorkItemStore(db_path=":memory:", connection_factory=factory, tick_interval=1000)
    await store.start()
    try:
        store.register_resource(_resource())
        item = await store.create_work_item(title="Prepared then failed")
        connection = factory.connection
        assert connection is not None
        prepared: list[str] = []
        connection.fail_sql = marker

        def prepare(planned_item: WorkItem, booking: Booking) -> None:
            prepared.append(booking.id)

        with pytest.raises(RuntimeError, match="injected_database_failure"):
            await store.claim_work_item("agent-a", prepare_claim=prepare)

        assert len(prepared) == 1
        assert (await store.get_work_item(item.id)).to_dict() == item.to_dict()
        assert await store.list_bookings(work_item_id=item.id) == []
        cursor = await connection.execute("SELECT COUNT(*) FROM booking_timestamps")
        assert (await cursor.fetchone())[0] == 0
        cursor = await connection.execute("SELECT fulfilled FROM resource_requirements")
        assert [row[0] for row in await cursor.fetchall()] == [0]
        connection.fail_sql = ""
    finally:
        await store.stop()


async def test_claim_preparation_cas_refusal_does_not_return_ownership() -> None:
    factory = _Factory()
    store = WorkItemStore(db_path=":memory:", connection_factory=factory, tick_interval=1000)
    await store.start()
    try:
        store.register_resource(_resource())
        item = await store.create_work_item(title="CAS refusal")
        connection = factory.connection
        assert connection is not None
        connection.refuse_sql = "UPDATE work_items SET assigned_to"
        prepared: list[str] = []

        def prepare(planned_item: WorkItem, booking: Booking) -> None:
            prepared.append(booking.id)

        result = await store.claim_work_item("agent-a", prepare_claim=prepare)

        assert result is None and len(prepared) == 1
        assert (await store.get_work_item(item.id)).to_dict() == item.to_dict()
        assert await store.list_bookings(work_item_id=item.id) == []
    finally:
        await store.stop()


async def test_claim_replay_prepares_paused_receipt_at_full_capacity(
    governed_store: WorkItemStore, authority: _Authority,
) -> None:
    item = await governed_store.create_work_item(title="Replay", metadata=_PUBLICATION)
    first = await governed_store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
    assert first is not None
    await governed_store.start_booking(first[1].id)
    await governed_store.pause_booking(first[1].id)
    other = await governed_store.create_work_item(title="Capacity", metadata=_PUBLICATION)
    assert await governed_store.claim_work_item(
        "agent-a", work_item_id=other.id, agent_pull=True,
    ) is not None
    prepared: list[tuple[str, str]] = []

    def prepare(planned_item: WorkItem, booking: Booking) -> None:
        prepared.append((booking.id, booking.status))

    replay = await governed_store.claim_work_item(
        "agent-a", work_item_id=item.id, agent_pull=True, prepare_claim=prepare,
    )

    assert replay is not None and prepared == [(first[1].id, "on_break")]
    authority.denied = True
    with pytest.raises(PermissionError):
        await governed_store.claim_work_item(
            "agent-a", work_item_id=item.id, agent_pull=True, prepare_claim=prepare,
        )
    assert len(prepared) == 1


@pytest.mark.parametrize("callback", [False, 1, "callback"])
async def test_claim_invalid_preparation_denied(
    pull_store: WorkItemStore, callback: Any,
) -> None:
    with pytest.raises(ValueError, match="work_pull_claim_invalid"):
        await pull_store.claim_work_item("agent-a", prepare_claim=callback)


async def test_claim_async_preparation_denied(pull_store: WorkItemStore) -> None:
    async def prepare(planned_item: WorkItem, booking: Booking) -> None:
        raise AssertionError("Asynchronous preparation must not execute")

    with pytest.raises(ValueError, match="work_pull_claim_invalid"):
        await pull_store.claim_work_item("agent-a", prepare_claim=prepare)


class _ScriptedClient:
    def __init__(
        self, responses: list[LLMResponse | Callable[[LLMRequest], LLMResponse]],
    ) -> None:
        self.responses = responses
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
        self.requests.append(request)
        response = self.responses[len(self.requests) - 1]
        return response(request) if callable(response) else response


def _call_response(tool_id: str, params: dict[str, Any], call_id: str = "pull-call") -> LLMResponse:
    return LLMResponse(
        content="", tokens_used=1,
        content_blocks=[ToolUseBlock(ToolCallRequest(name=tool_id, arguments=params, id=call_id))],
    )


def _final_response() -> LLMResponse:
    return LLMResponse(content="Recorded.", tokens_used=1, content_blocks=[TextBlock("Recorded.")])


def _next_tool_text(request: LLMRequest, *, structured: bool, call_id: str = "pull-call") -> str:
    if structured:
        messages = [
            message for message in request.messages or []
            if message.get("role") == "tool" and message.get("tool_call_id") == call_id
        ]
        assert len(messages) == 1
        return messages[0]["content"]
    marker = f"[tool_result:{call_id} error="
    assert marker in request.prompt
    return request.prompt.split(marker, 1)[1].split("]\n", 1)[1].split("\n\n", 1)[0]


class _PresentationExecutor:
    def __init__(self, value: Any) -> None:
        self.value = value
        self.contexts: list[dict[str, Any]] = []

    async def invoke(self, *, context: dict[str, Any], **kwargs: Any) -> ToolResult:
        self.contexts.append(context)
        carrier = context["_tool_result_presentation"]
        assert type(carrier) is ToolResultPresentation
        await asyncio.sleep(0)
        rendered = carrier.render_complete(self.value)
        return ToolResult(output=rendered) if rendered is not None else ToolResult(error="!")


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("cap", [0, 6000])
@pytest.mark.parametrize("tool_id", ["discover_work_items", "claim_work_item"])
async def test_loop_presentation_overwrites_forged_context_and_preserves_next_request(
    structured: bool, cap: int, tool_id: str,
) -> None:
    value = {"description": "quotes '\" slash\\ CRLF\r\n" * 400, "owned": True}
    executor = _PresentationExecutor(value)
    client = _ScriptedClient([_call_response(tool_id, {}), _final_response()])
    forged = ToolResultPresentation(lambda value: "forged")
    context = {"agent_id": "agent-a", "_tool_result_presentation": forged}
    loop = AgenticLoop(
        llm_client=client, tool_executor=executor, structured_tool_messages=structured,
        tool_result_max_chars=cap,
    )

    result = await loop.run(system_prompt="SYS", user_message="Task", tools=[], context=context)

    assert len(client.requests) == 2
    assert context["_tool_result_presentation"] is forged
    assert executor.contexts[0]["_tool_result_presentation"] is not forged
    expected = render_tool_output(value, max_chars=0) if cap == 0 else "!"
    assert _next_tool_text(client.requests[1], structured=structured) == expected
    assert result.tool_results[0].is_error is (cap != 0)


@pytest.mark.parametrize("structured", [False, True])
async def test_loop_concurrent_presentations_are_invocation_local(structured: bool) -> None:
    value = {"description": "x" * 7000}
    executor = _PresentationExecutor(value)
    clients = [
        _ScriptedClient([_call_response("claim_work_item", {}), _final_response()])
        for _ in range(2)
    ]
    loops = [
        AgenticLoop(
            llm_client=client, tool_executor=executor,
            structured_tool_messages=structured, tool_result_max_chars=cap,
        )
        for client, cap in zip(clients, (0, 6000))
    ]
    tasks = [
        asyncio.create_task(loop.run(
            system_prompt="SYS", user_message="Task", tools=[], context={"agent_id": "agent-a"},
        ))
        for loop in loops
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    assert _next_tool_text(clients[0].requests[1], structured=structured) == str(value)
    assert _next_tool_text(clients[1].requests[1], structured=structured) == "!"
    assert executor.contexts[0]["_tool_result_presentation"] is not executor.contexts[1]["_tool_result_presentation"]


async def test_loop_presentation_exact_render_fit_and_frozen_carrier() -> None:
    value = {"description": "é'\\\r\n"}
    plain = render_tool_output(value, max_chars=0)
    executor = _PresentationExecutor(value)
    client = _ScriptedClient([_call_response("discover_work_items", {}), _final_response()])
    loop = AgenticLoop(llm_client=client, tool_executor=executor, tool_result_max_chars=len(plain))
    await loop.run(system_prompt="SYS", user_message="Task", tools=[], context={"agent_id": "agent-a"})
    carrier = executor.contexts[0]["_tool_result_presentation"]
    assert carrier.render_complete(value) == plain
    assert truncate_tool_output(plain, max_chars=len(plain)) == plain
    assert carrier.render_complete({"description": value["description"] + "x"}) is None
    assert carrier.render_complete("") == ""
    with pytest.raises(dataclasses.FrozenInstanceError):
        carrier.render_complete = lambda value: "forged"


@pytest.mark.parametrize("bounds", [
    {"tool_result_max_chars": -1}, {"tool_result_max_chars": True},
    {"tool_result_max_chars": 1.5}, {"tool_result_head_chars": -1},
    {"tool_result_tail_chars": False},
])
async def test_loop_invalid_presentation_bounds_refuse_admission(bounds: dict[str, Any]) -> None:
    executor = _PresentationExecutor({"owned": True})
    loop = AgenticLoop(llm_client=_ScriptedClient([]), tool_executor=executor, **bounds)
    result = await loop._execute_one_tool(
        ToolUseBlock(ToolCallRequest(name="claim_work_item")), agent_id="agent-a",
        iteration=1, context={"agent_id": "agent-a"},
    )
    assert result.is_error is True
    assert "work_pull_presentation_invalid" in result.output


async def test_loop_rendering_failure_is_error_not_successful_empty() -> None:
    class _BrokenValue(dict):
        def __repr__(self) -> str:
            raise ValueError("broken_repr")

    executor = _PresentationExecutor(_BrokenValue())
    loop = AgenticLoop(llm_client=_ScriptedClient([]), tool_executor=executor)
    result = await loop._execute_one_tool(
        ToolUseBlock(ToolCallRequest(name="discover_work_items")), agent_id="agent-a",
        iteration=1, context={"agent_id": "agent-a"},
    )
    assert result.is_error is True
    assert "work_pull_presentation_render_failed" in result.output


async def test_loop_other_tools_keep_existing_context() -> None:
    context = {"agent_id": "agent-a", "_tool_result_presentation": "unchanged"}

    class _OtherExecutor:
        async def invoke(self, *, context: dict[str, Any], **kwargs: Any) -> ToolResult:
            assert context["_tool_result_presentation"] == "unchanged"
            return ToolResult(output="ordinary")

    client = _ScriptedClient([_call_response("other_tool", {}), _final_response()])
    result = await AgenticLoop(llm_client=client, tool_executor=_OtherExecutor()).run(
        system_prompt="SYS", user_message="Task", tools=[], context=context,
    )
    assert result.tool_results[0].output == "ordinary"
    assert context == {"agent_id": "agent-a", "_tool_result_presentation": "unchanged"}


@pytest.fixture
def tool_runtime(runtime: ProbOSRuntime) -> ProbOSRuntime:
    for tool_class in (DiscoverWorkItemsTool, ClaimWorkItemTool):
        tool = tool_class(
            store=runtime.work_item_store,
            pull_resource_resolver=runtime.resolve_workforce_pull_resource,
        )
        registration = runtime.tool_registry.get(tool.tool_id)
        assert registration is not None
        runtime.tool_registry.register(
            tool, allowed_departments=registration.allowed_departments,
            default_permissions=registration.default_permissions,
        )
    return runtime


async def _invoke_pull(
    runtime: ProbOSRuntime, tool_id: str, params: dict[str, Any], *,
    cap: int = 0, structured: bool = True, context: dict[str, Any] | None = None,
) -> tuple[AgenticResult, _ScriptedClient]:
    client = _ScriptedClient([_call_response(tool_id, params), _final_response()])
    result = await AgenticLoop(
        llm_client=client, tool_executor=ToolExecutor(registry=runtime.tool_registry),
        structured_tool_messages=structured, tool_result_max_chars=cap,
    ).run(
        system_prompt="Choose work; read the ownership receipt.", user_message="Task",
        tools=[], context={
            "agent_id": "agent-a", "department": "science", "rank": "ensign",
            **(context or {}),
        },
    )
    assert len(client.requests) == 2
    return result, client


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("cap", [0, 6000])
@pytest.mark.parametrize("description", [
    "", "Complete instructions.", "quotes '\" backslash\\ and CRLF\r\n",
    '{"step":"read","nested":{"literal":"value"}}',
    "opaque-" + "0123456789abcdef" * 1020,
    "a" * 16_384, "a" * 16_385, "é" * 8192, "é" * 8192 + "x",
], ids=["empty", "prose", "escapes", "json-like", "opaque", "ascii-limit",
        "ascii-over", "utf8-limit", "utf8-over"])
async def test_claim_description_reaches_next_request_whole_or_explicitly_omitted(
    tool_runtime: ProbOSRuntime, structured: bool, cap: int, description: str,
) -> None:
    item = await tool_runtime.work_item_store.create_work_item(
        title="Instructions", description=description, metadata=_PUBLICATION,
    )
    tool_runtime.config.agentic_loop.tool_result_max_chars = 6000 if cap == 0 else 0

    result, client = await _invoke_pull(
        tool_runtime, "claim_work_item", {"work_item_id": item.id}, cap=cap, structured=structured,
    )

    receipt = _next_tool_text(client.requests[1], structured=structured)
    assert result.tool_results[0].is_error is False
    assert receipt == result.tool_results[0].output
    assert not cap or len(receipt) <= cap
    value = ast.literal_eval(receipt)
    assert value["owned"] is True
    assert value["work_item"]["description_utf8_bytes"] == len(description.encode("utf-8"))
    if len(description.encode("utf-8")) > 16_384:
        assert value["work_item"]["description"] is None
        assert value["omitted_fields"]["work_item.description"] == "size_limit"
    elif value["work_item"]["description"] is None:
        assert cap > 0
        assert value["omitted_fields"].pop("work_item.description") == "result_budget"
        value["work_item"]["description"] = description
        assert len(render_tool_output(value, max_chars=0)) > cap
    else:
        assert value["work_item"]["description"] == description
        assert "work_item.description" not in value["omitted_fields"]
    stored = await tool_runtime.work_item_store.get_work_item(item.id)
    booking = await tool_runtime.work_item_store.get_booking(value["booking"]["id"])
    assert stored.assigned_to == booking.resource_id == value["work_item"]["assigned_to"] == "agent-a"
    assert stored.status == value["work_item"]["status"] == "scheduled"
    assert booking.status == value["booking"]["status"] == "scheduled"
    assert value["omitted_fields"] == {
        **{
            f"work_item.{field.name}": "not_exposed"
            for field in dataclasses.fields(WorkItem)
            if field.name not in value["work_item"]
        },
        **{
            f"booking.{field.name}": "not_exposed"
            for field in dataclasses.fields(Booking)
            if field.name not in value["booking"]
        },
        **({"work_item.description": "size_limit"} if len(description.encode("utf-8")) > 16_384 else {}),
    }


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("cap", [1, len("work_pull_result_budget"), 500])
async def test_claim_tiny_cap_refuses_before_mutation_sql(
    tool_runtime: ProbOSRuntime, db_factory: _Factory,
    workforce_events: list[tuple[str, dict[str, Any]]],
    structured: bool, cap: int, caplog: pytest.LogCaptureFixture,
) -> None:
    item = await tool_runtime.work_item_store.create_work_item(title="Tiny", metadata=_PUBLICATION)
    connection = db_factory.connection
    assert connection is not None
    connection.statements.clear()
    workforce_events.clear()

    result, client = await _invoke_pull(
        tool_runtime, "claim_work_item", {"work_item_id": item.id}, cap=cap, structured=structured,
    )

    assert result.tool_results[0].is_error is True
    expected = "!" if cap == 1 else "work_pull_result_budget"
    assert _next_tool_text(client.requests[1], structured=structured) == expected
    assert "work_pull_result_budget" in caplog.text
    assert not any(sql.lstrip().startswith(("INSERT", "UPDATE", "DELETE")) for sql in connection.statements)
    assert (await tool_runtime.work_item_store.get_work_item(item.id)).to_dict() == item.to_dict()
    assert await tool_runtime.work_item_store.list_bookings(work_item_id=item.id) == []
    cursor = await connection.execute("SELECT COUNT(*) FROM booking_timestamps")
    assert (await cursor.fetchone())[0] == 0
    cursor = await connection.execute("SELECT fulfilled FROM resource_requirements")
    assert [row[0] for row in await cursor.fetchall()] == [0]
    assert workforce_events == []


@pytest.mark.parametrize("structured", [False, True])
async def test_claim_replay_essential_exact_fit_and_one_below(
    tool_runtime: ProbOSRuntime, db_factory: _Factory, structured: bool,
) -> None:
    item = await tool_runtime.work_item_store.create_work_item(title="Fit", metadata=_PUBLICATION)
    first, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": item.id})
    receipt = first.tool_results[0].output
    assert ast.literal_eval(receipt)["work_item"]["description"] == ""
    connection = db_factory.connection
    assert connection is not None
    connection.statements.clear()

    fits, client = await _invoke_pull(
        tool_runtime, "claim_work_item", {"work_item_id": item.id},
        cap=len(receipt), structured=structured,
    )
    refused, smaller = await _invoke_pull(
        tool_runtime, "claim_work_item", {"work_item_id": item.id},
        cap=len(receipt) - 1, structured=structured,
    )

    assert fits.tool_results[0].is_error is False
    assert _next_tool_text(client.requests[1], structured=structured) == receipt
    assert refused.tool_results[0].is_error is True
    assert _next_tool_text(smaller.requests[1], structured=structured) == "work_pull_result_budget"
    assert not any(sql.lstrip().startswith(("INSERT", "UPDATE", "DELETE")) for sql in connection.statements)
    assert len(await tool_runtime.work_item_store.list_bookings(work_item_id=item.id)) == 1


@pytest.mark.parametrize("key,value", [
    ("agent_id", "agent-b"), ("rank", "senior_officer"), ("department", "science"),
    ("trust", 1), ("capacity", 99), ("permission", "full"),
    ("_tool_result_presentation", {"max_chars": 0}),
])
@pytest.mark.parametrize("tool_id", ["discover_work_items", "claim_work_item"])
async def test_pull_tools_reject_undeclared_model_authority(
    tool_runtime: ProbOSRuntime, tool_id: str, key: str, value: Any,
) -> None:
    item = await tool_runtime.work_item_store.create_work_item(title="Guard", metadata=_PUBLICATION)
    params = {"work_item_id": item.id} if tool_id == "claim_work_item" else {}

    result, _ = await _invoke_pull(tool_runtime, tool_id, {**params, key: value})

    assert result.tool_results[0].is_error is True
    assert (await tool_runtime.work_item_store.get_work_item(item.id)).assigned_to is None


@pytest.mark.parametrize("carrier", [None, {}, "unbounded", lambda value: str(value)])
@pytest.mark.parametrize("tool_id", ["discover_work_items", "claim_work_item"])
async def test_pull_tools_missing_or_untrusted_presentation_fail_closed(
    tool_runtime: ProbOSRuntime, db_factory: _Factory, tool_id: str, carrier: Any,
) -> None:
    item = await tool_runtime.work_item_store.create_work_item(title="Carrier", metadata=_PUBLICATION)
    connection = db_factory.connection
    assert connection is not None
    connection.statements.clear()
    tool = tool_runtime.tool_registry.get_tool(tool_id)
    params = {"work_item_id": item.id} if tool_id == "claim_work_item" else {}

    result = await tool.invoke(params, {"agent_id": "agent-a", "_tool_result_presentation": carrier})

    assert result.success is False
    assert connection.statements == []


@pytest.mark.parametrize("key", ["_crew_session_id", "_crew_work_item_id"])
@pytest.mark.parametrize("tool_id", ["discover_work_items", "claim_work_item"])
async def test_pull_tools_room_and_correction_context_denied(
    tool_runtime: ProbOSRuntime, tool_id: str, key: str,
) -> None:
    item = await tool_runtime.work_item_store.create_work_item(title="Room guard", metadata=_PUBLICATION)
    params = {"work_item_id": item.id} if tool_id == "claim_work_item" else {}
    result, _ = await _invoke_pull(tool_runtime, tool_id, params, context={key: "bound-room"})
    assert result.tool_results[0].is_error is True
    assert (await tool_runtime.work_item_store.get_work_item(item.id)).assigned_to is None


async def test_claim_read_only_grant_fails_current_write_check(tool_runtime: ProbOSRuntime) -> None:
    registration = tool_runtime.tool_registry.get("claim_work_item")
    registration.default_permissions = {rank: "read" for rank in registration.default_permissions}
    assert tool_runtime.tool_registry.check_permission(
        "agent-a", "claim_work_item", ToolPermission.READ,
        agent_department="science", agent_rank="ensign",
    )
    item = await tool_runtime.work_item_store.create_work_item(title="WRITE", metadata=_PUBLICATION)

    result, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": item.id})

    assert result.tool_results[0].is_error is True
    assert (await tool_runtime.work_item_store.get_work_item(item.id)).assigned_to is None


@pytest.mark.parametrize("structured", [False, True])
async def test_discovery_budget_uses_first_omitted_offset_without_rescan(
    tool_runtime: ProbOSRuntime, db_factory: _Factory, structured: bool,
) -> None:
    for index in range(10):
        await tool_runtime.work_item_store.create_work_item(
            id=f"page-{index:02}", title="T" * 257, description="é" * 257,
            created_at=1, metadata=_PUBLICATION, trust_requirement=0.99 if index % 2 == 0 else 0,
        )
    full, _ = await _invoke_pull(tool_runtime, "discover_work_items", {})
    value = ast.literal_eval(full.tool_results[0].output)
    assert len(value["items"]) == 5
    prefix = {**value, "items": value["items"][:2], "next_offset": 5,
              "omitted_fields": {**value["omitted_fields"], "items": "result_budget"}}
    cap = len(render_tool_output(prefix, max_chars=0))
    connection = db_factory.connection
    assert connection is not None
    connection.statements.clear()
    collected: list[str] = []
    offset = 0
    for page_index in range(3):
        result, client = await _invoke_pull(
            tool_runtime, "discover_work_items", {"offset": offset}, cap=cap, structured=structured,
        )
        assert result.tool_results[0].is_error is False
        received = ast.literal_eval(_next_tool_text(client.requests[1], structured=structured))
        if page_index == 0:
            assert received == prefix
        assert received["omitted_fields"]["items[].description"] == "preview_only"
        for row in received["items"]:
            assert row["title"] == "T" * 256 and row["title_truncated"] is True
            assert row["description_preview"] == "é" * 256 and row["description_truncated"] is True
            assert row["description_utf8_bytes"] == 514
            collected.append(row["id"])
        offset = received["next_offset"]
        if offset is None:
            break
    assert collected == [f"page-{index:02}" for index in (1, 3, 5, 7, 9)]
    scans = [sql for sql in connection.statements if sql.startswith("SELECT * FROM work_items WHERE status")]
    assert len(scans) == 3


async def test_discovery_first_row_refusal_is_not_empty_page(tool_runtime: ProbOSRuntime) -> None:
    await tool_runtime.work_item_store.create_work_item(title="Too small", metadata=_PUBLICATION)
    result, _ = await _invoke_pull(tool_runtime, "discover_work_items", {}, cap=500)
    assert result.tool_results[0].is_error is True
    assert result.tool_results[0].output == "work_pull_result_budget"


@pytest.mark.parametrize("marker", ["INSERT INTO bookings", "COMMIT"])
async def test_claim_prepared_receipt_is_discarded_after_database_fault(
    tool_runtime: ProbOSRuntime, db_factory: _Factory, marker: str,
) -> None:
    item = await tool_runtime.work_item_store.create_work_item(title="DB fault", metadata=_PUBLICATION)
    connection = db_factory.connection
    assert connection is not None
    connection.fail_sql = marker
    result, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": item.id})
    connection.fail_sql = ""
    assert result.tool_results[0].is_error is True
    assert (await tool_runtime.work_item_store.get_work_item(item.id)).assigned_to is None
    assert await tool_runtime.work_item_store.list_bookings(work_item_id=item.id) == []


async def test_claim_prepared_receipt_is_discarded_after_cas_refusal(
    tool_runtime: ProbOSRuntime, db_factory: _Factory,
) -> None:
    item = await tool_runtime.work_item_store.create_work_item(title="CAS", metadata=_PUBLICATION)
    connection = db_factory.connection
    assert connection is not None
    connection.refuse_sql = "UPDATE work_items SET assigned_to"
    result, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": item.id})
    assert result.tool_results[0].is_error is False
    assert ast.literal_eval(result.tool_results[0].output) == {"owned": False, "reason": "not_claimable"}
    assert (await tool_runtime.work_item_store.get_work_item(item.id)).assigned_to is None
    assert await tool_runtime.work_item_store.list_bookings(work_item_id=item.id) == []


class _StartupRuntime(ProbOSRuntime):
    @property
    def attachment_store(self) -> None:
        return None


@asynccontextmanager
async def _communication_runtime(
    path: Path, *, enabled: bool = True, with_resolver: bool = True,
    events: list[tuple[str, dict[str, Any]]] | None = None,
) -> AsyncIterator[ProbOSRuntime]:
    runtime = object.__new__(_StartupRuntime)
    runtime.config = SystemConfig()
    runtime.config.workforce.enabled = enabled
    runtime.config.workforce.tick_interval_seconds = 1000
    runtime.config.persistent_tasks.enabled = False
    runtime.config.ward_room.enabled = False
    runtime.config.assignments.enabled = False
    runtime.config.cognitive_journal.enabled = False
    runtime.config.knowledge_edges.enabled = False
    runtime.config.skill_requests.enabled = False
    runtime.registry = AgentRegistry()
    await runtime.registry.register(_Agent())
    runtime.trust_network = _Trust()
    runtime.ontology = None
    runtime.work_item_store = None
    runtime.tool_registry = None
    runtime.intent_bus = None
    captured = events if events is not None else []

    def emit(event: str, data: dict[str, Any]) -> None:
        captured.append((event, data))

    async def unused(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Unrelated startup activity must stay disabled")

    runtime.emit_event = emit
    comm = await init_communication(
        config=runtime.config, data_dir=path, checkpoint_dir=path / "checkpoints",
        registry=runtime.registry, identity_registry=None, episodic_memory=None,
        hebbian_router=None, emit_event_fn=emit, process_natural_language_fn=unused,
        register_workforce_resources_fn=runtime._register_workforce_resources,
        journal_prune_loop_fn=unused, event_log_reader=None, event_log_audit_sink=None,
        pull_resource_resolver=runtime.resolve_workforce_pull_resource if with_resolver else None,
    )
    try:
        for field in dataclasses.fields(comm):
            setattr(runtime, field.name, getattr(comm, field.name))
        yield runtime
    finally:
        for field in reversed(dataclasses.fields(comm)):
            service = getattr(comm, field.name)
            stop = getattr(service, "stop", None)
            if callable(stop):
                await stop()


@pytest.mark.parametrize("enabled,resolver", [(False, True), (True, False), (True, True)])
async def test_startup_work_pull_registration_requires_store_and_resolver(
    tmp_path: Path, enabled: bool, resolver: bool,
) -> None:
    async with _communication_runtime(tmp_path, enabled=enabled, with_resolver=resolver) as runtime:
        for tool_id, permission, tool_class in (
            ("discover_work_items", ToolPermission.READ, DiscoverWorkItemsTool),
            ("claim_work_item", ToolPermission.WRITE, ClaimWorkItemTool),
        ):
            registration = runtime.tool_registry.get(tool_id)
            if not (enabled and resolver):
                assert registration is None
                continue
            assert type(registration.tool) is tool_class
            assert set(registration.allowed_departments) == {
                "engineering", "science", "medical", "security", "operations", "bridge",
            }
            assert registration.default_permissions == {
                rank: permission.value for rank in ("ensign", "lieutenant", "commander", "senior_officer")
            }
            assert registration.tool.output_schema["type"] == "string"
            assert registration.tool.input_schema["additionalProperties"] is False
            assert runtime.tool_registry.check_permission(
                "agent-a", tool_id, permission, agent_department="science", agent_rank="ensign",
            )
            assert not runtime.tool_registry.check_permission(
                "agent-a", tool_id, permission, agent_department="science", agent_rank="captain",
            )
            assert not runtime.tool_registry.check_permission(
                "agent-a", tool_id, permission, agent_department="unlisted", agent_rank="senior_officer",
            )
        client = _ScriptedClient([_final_response()])
        await WorkItemAgenticExecutor(llm_client=client).run(
            agent_id="agent-a", instructions="Choose work.", task_text="Inspect options.", runtime=runtime,
        )
        offered = {tool["function"]["name"] for tool in client.requests[0].tools}
        assert ("discover_work_items" in offered) is (enabled and resolver)
        assert ("claim_work_item" in offered) is (enabled and resolver)


@pytest.mark.parametrize("context", [
    {"_crew_session_id": "session", "_crew_work_item_id": "crew-child"},
    {"_crew_session_id": "session", "_crew_work_item_id": "correction-child"},
    {"_crew_session_id": ""},
])
async def test_agentic_offer_excludes_room_context_even_with_captain_grant(
    tmp_path: Path, context: dict[str, Any],
) -> None:
    async with _communication_runtime(tmp_path) as runtime:
        for tool_id in ("discover_work_items", "claim_work_item"):
            await runtime.tool_permission_store.issue_grant("agent-a", tool_id, ToolPermission.FULL)
        client = _ScriptedClient([_final_response()])

        await WorkItemAgenticExecutor(llm_client=client).run(
            agent_id="agent-a", instructions="Room work.", task_text="Keep this assignment.",
            runtime=runtime, thread_id="room", extra_context=context,
        )

        offered = {tool["function"]["name"] for tool in client.requests[0].tools}
        assert "discover_work_items" not in offered and "claim_work_item" not in offered


async def test_agentic_offer_filters_write_restriction_and_department_scope(tmp_path: Path) -> None:
    async with _communication_runtime(tmp_path) as runtime:
        restriction = await runtime.tool_permission_store.issue_grant(
            "agent-a", "claim_work_item", ToolPermission.READ, is_restriction=True,
        )
        client = _ScriptedClient([_final_response()])
        await WorkItemAgenticExecutor(llm_client=client).run(
            agent_id="agent-a", instructions="Choose work.", task_text="Inspect options.", runtime=runtime,
        )
        offered = {tool["function"]["name"] for tool in client.requests[0].tools}
        assert "discover_work_items" in offered and "claim_work_item" not in offered
        await runtime.tool_permission_store.revoke_grant(restriction.id)
        for tool_id in ("discover_work_items", "claim_work_item"):
            await runtime.tool_permission_store.issue_grant("agent-a", tool_id, ToolPermission.FULL)
            runtime.tool_registry.get(tool_id).allowed_departments = ("engineering",)
        client = _ScriptedClient([_final_response()])
        await WorkItemAgenticExecutor(llm_client=client).run(
            agent_id="agent-a", instructions="Choose work.", task_text="Inspect options.", runtime=runtime,
        )
        offered = {tool["function"]["name"] for tool in client.requests[0].tools}
        assert "discover_work_items" not in offered and "claim_work_item" not in offered


async def _captain_publish(store: WorkItemStore, body: dict[str, Any]) -> dict[str, Any]:
    app = FastAPI()
    app.include_router(workforce_router)
    app.dependency_overrides[get_runtime] = lambda: SimpleNamespace(work_item_store=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://in-process.test", trust_env=False,
    ) as client:
        response = await client.post("/api/work-items", json=body)
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"work_item"}
    return payload["work_item"]


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("cap", [0, 6000])
async def test_captain_publication_startup_discovery_chosen_claim_next_request_persisted_status(
    tmp_path: Path, structured: bool, cap: int,
) -> None:
    path = str(tmp_path / "workforce.db")
    publication_store = WorkItemStore(db_path=path, tick_interval=1000)
    await publication_store.start()
    description = "éX" * 4000
    try:
        first = await _captain_publish(publication_store, {
            "title": "First but not chosen", "priority": 1, "metadata": _PUBLICATION,
        })
        target = await _captain_publish(publication_store, {
            "title": "Chosen by the agent", "description": description,
            "metadata": {**_PUBLICATION, "private_key": "not-shared"},
            "steps": [{"private_step": "not-shared"}],
        })
        assert target["assigned_to"] is None and target["created_by"] == "captain"
        assert target["metadata"]["agent_pull"] == _PUBLICATION["agent_pull"]
    finally:
        await publication_store.stop()

    events: list[tuple[str, dict[str, Any]]] = []
    async with _communication_runtime(tmp_path, events=events) as runtime:
        runtime.config.agentic_loop.structured_tool_messages = structured
        runtime.config.agentic_loop.tool_result_max_chars = cap
        assert type(runtime.tool_registry.get_tool("discover_work_items")) is DiscoverWorkItemsTool
        assert type(runtime.tool_registry.get_tool("claim_work_item")) is ClaimWorkItemTool
        assert runtime.resolve_workforce_pull_resource("agent-a", "claim", True) is not None
        chosen: list[str] = []
        receipts: list[dict[str, Any]] = []
        statuses: list[dict[str, Any]] = []

        def discover(request: LLMRequest) -> LLMResponse:
            offered = {tool["function"]["name"] for tool in request.tools}
            assert {"discover_work_items", "claim_work_item", "work_item_status"} <= offered
            return _call_response("discover_work_items", {}, "discover")

        def select(request: LLMRequest) -> LLMResponse:
            page = ast.literal_eval(_next_tool_text(request, structured=structured, call_id="discover"))
            assert [item["id"] for item in page["items"]] == [first["id"], target["id"]]
            selected = next(item for item in page["items"] if item["title"] == "Chosen by the agent")
            chosen.append(selected["id"])
            return _call_response("claim_work_item", {"work_item_id": selected["id"]}, "claim")

        def read_receipt(request: LLMRequest) -> LLMResponse:
            text = _next_tool_text(request, structured=structured, call_id="claim")
            receipt = ast.literal_eval(text)
            assert receipt["owned"] is True
            assert receipt["work_item"]["id"] == chosen[0]
            assert receipt["work_item"]["assigned_to"] == receipt["booking"]["resource_id"] == "agent-a"
            assert receipt["work_item"]["status"] == receipt["booking"]["status"] == "scheduled"
            assert receipt["work_item"]["description_utf8_bytes"] == len(description.encode("utf-8"))
            if cap:
                assert len(text) <= cap
                assert receipt["work_item"]["description"] is None
                assert receipt["omitted_fields"]["work_item.description"] == "result_budget"
            else:
                assert receipt["work_item"]["description"] == description
            assert "not-shared" not in text
            receipts.append(receipt)
            return _call_response("work_item_status", {"work_item_id": chosen[0]}, "status")

        def read_status(request: LLMRequest) -> LLMResponse:
            status = ast.literal_eval(_next_tool_text(request, structured=structured, call_id="status"))
            assert status["found"] is True and status["work_item_id"] == chosen[0]
            assert status["status"] == receipts[0]["work_item"]["status"] == "scheduled"
            assert "description" not in status and "metadata" not in status
            statuses.append(status)
            return _final_response()

        client = _ScriptedClient([discover, select, read_receipt, read_status])
        outcome = await WorkItemAgenticExecutor(llm_client=client).run(
            agent_id="agent-a", instructions="Select the work you intend to own.",
            task_text="Discover, select and claim one task, then read its status.",
            runtime=runtime, max_iterations=5,
        )
        assert outcome.stopped_reason == "complete"
        assert len(client.requests) == 4 and chosen == [target["id"]]
        assert len(receipts) == len(statuses) == 1
        connection = await SQLiteConnectionFactory().connect(path)
        try:
            cursor = await connection.execute(
                "SELECT assigned_to, status FROM work_items WHERE id = ?", (chosen[0],),
            )
            assert tuple(await cursor.fetchone()) == ("agent-a", "scheduled")
            cursor = await connection.execute(
                "SELECT id, resource_id, status FROM bookings WHERE work_item_id = ?", (chosen[0],),
            )
            assert [tuple(row) for row in await cursor.fetchall()] == [
                (receipts[0]["booking"]["id"], "agent-a", "scheduled"),
            ]
            cursor = await connection.execute(
                "SELECT assigned_to, status FROM work_items WHERE id = ?", (first["id"],),
            )
            assert tuple(await cursor.fetchone()) == (None, "open")
        finally:
            await connection.close()
        assigned = [data for event, data in events if event == "work_item_assigned"]
        claimed = [data for event, data in events if event == "work_item_claimed"]
        assert len(assigned) == len(claimed) == 1


async def test_discovery_malformed_publications_do_not_consume_authorized_scan(
    governed_store: WorkItemStore,
) -> None:
    for index in range(201):
        await governed_store.create_work_item(
            id=f"hidden-{index:03}", title="Malformed private publication", created_at=1,
            metadata={"agent_pull": {"version": 1, "scope": "ship", "private": True}},
        )
    visible = await governed_store.create_work_item(
        id="visible-row", title="Visible", created_at=1, metadata=_PUBLICATION,
    )

    page = await governed_store.list_claimable_work_items("agent-a")

    assert [item.id for item in page.items] == [visible.id]
    assert page.item_offsets == (0,) and page.next_offset is None


@pytest.mark.parametrize("fields", [
    {"parent_id": "crew-parent"},
    {"metadata": {**_PUBLICATION, "thread_id": "room"}},
    {"metadata": {**_PUBLICATION, "crew_session": {"thread_id": "room"}}},
])
async def test_claim_replay_excludes_room_or_child_rows(
    governed_store: WorkItemStore, fields: dict[str, Any],
) -> None:
    item = await governed_store.create_work_item(title="Now room-bound", metadata=_PUBLICATION)
    first = await governed_store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
    assert first is not None
    await governed_store.update_work_item(item.id, **fields)

    replay = await governed_store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)

    assert replay is None
    assert [booking.id for booking in await governed_store.list_bookings(work_item_id=item.id)] == [first[1].id]


@pytest.mark.parametrize("query", [
    None, [], {"work_type": None}, {"work_type": ""}, {"work_type": True},
    {"work_type": "x" * 65}, {"limit": True}, {"limit": 0}, {"limit": 51},
    {"limit": 1.0}, {"offset": True}, {"offset": -1}, {"offset": "0"},
], ids=["none", "list", "null-type", "empty-type", "bool-type", "long-type",
        "bool-limit", "zero-limit", "large-limit", "float-limit", "bool-offset",
        "negative-offset", "string-offset"])
async def test_discovery_invalid_parameters_are_errors(tool_runtime: ProbOSRuntime, query: Any) -> None:
    result, _ = await _invoke_pull(tool_runtime, "discover_work_items", query)
    assert result.tool_results[0].is_error is True


@pytest.mark.parametrize("params", [None, [], {}, {"work_item_id": None},
                                   {"work_item_id": ""}, {"work_item_id": True},
                                   {"work_item_id": "x" * 129}])
async def test_claim_invalid_parameters_are_errors(tool_runtime: ProbOSRuntime, params: Any) -> None:
    result, _ = await _invoke_pull(tool_runtime, "claim_work_item", params)
    assert result.tool_results[0].is_error is True


@pytest.mark.parametrize("tool_id", ["discover_work_items", "claim_work_item"])
@pytest.mark.parametrize("context", [None, [], {}, {"agent_id": None}, {"agent_id": ""}])
async def test_pull_context_boundaries_fail_closed(
    tool_runtime: ProbOSRuntime, tool_id: str, context: Any,
) -> None:
    if type(context) is dict:
        context = {**context, "_tool_result_presentation": ToolResultPresentation(render_tool_output)}
    params = {"work_item_id": "missing-id"} if tool_id == "claim_work_item" else {}
    result = await tool_runtime.tool_registry.get_tool(tool_id).invoke(params, context)
    assert result.success is False and result.output is None


@pytest.mark.parametrize("tool_class", [DiscoverWorkItemsTool, ClaimWorkItemTool])
@pytest.mark.parametrize("store_missing", [False, True])
def test_pull_tool_missing_dependencies_rejected(tool_class: Any, store_missing: bool) -> None:
    with pytest.raises(ValueError, match="work_pull_dependencies_required"):
        tool_class(
            store=None if store_missing else object(),
            pull_resource_resolver=_Authority() if store_missing else None,
        )


def test_pull_registration_serializes_truthful_schema(tool_runtime: ProbOSRuntime) -> None:
    for tool_id, name in (
        ("discover_work_items", "Discover Ready Work"), ("claim_work_item", "Claim Selected Work"),
    ):
        value = tool_runtime.tool_registry.get(tool_id).to_dict()
        assert value["name"] == name and value["tool_type"] == "infra_service"
        assert value["output_schema"]["type"] == "string"
        assert "not JSON" in value["output_schema"]["description"]


@pytest.mark.parametrize("tool_id", ["discover_work_items", "claim_work_item"])
async def test_pull_invalid_actual_loop_bounds_refuse_before_mutation(
    tool_runtime: ProbOSRuntime, db_factory: _Factory, tool_id: str,
) -> None:
    item = await tool_runtime.work_item_store.create_work_item(title="Bounds", metadata=_PUBLICATION)
    connection = db_factory.connection
    assert connection is not None
    connection.statements.clear()
    client = _ScriptedClient([_call_response(
        tool_id, {"work_item_id": item.id} if tool_id == "claim_work_item" else {},
    ), _final_response()])
    result = await AgenticLoop(
        llm_client=client, tool_executor=ToolExecutor(registry=tool_runtime.tool_registry),
        tool_result_head_chars=-1,
    ).run(
        system_prompt="SYS", user_message="Task", tools=[],
        context={"agent_id": "agent-a", "department": "science", "rank": "ensign"},
    )
    assert result.tool_results[0].is_error is True
    assert not any(sql.lstrip().startswith(("INSERT", "UPDATE", "DELETE")) for sql in connection.statements)
    assert (await tool_runtime.work_item_store.get_work_item(item.id)).assigned_to is None


async def test_discovery_infrastructure_fault_is_not_empty_success(
    tool_runtime: ProbOSRuntime, db_factory: _Factory,
) -> None:
    connection = db_factory.connection
    assert connection is not None
    connection.fail_sql = "SELECT * FROM work_items WHERE status"
    result, _ = await _invoke_pull(tool_runtime, "discover_work_items", {})
    connection.fail_sql = ""
    assert result.tool_results[0].is_error is True
    assert result.tool_results[0].output == "work_pull_discovery_failed"


@pytest.mark.parametrize("description", [None, b"not-text"])
@pytest.mark.parametrize("tool_id", ["discover_work_items", "claim_work_item"])
async def test_pull_invalid_stored_description_errors_without_mutation(
    tool_runtime: ProbOSRuntime, db_factory: _Factory, description: Any, tool_id: str,
) -> None:
    item = await tool_runtime.work_item_store.create_work_item(title="Invalid text", metadata=_PUBLICATION)
    connection = db_factory.connection
    assert connection is not None
    if description is None:
        # SQLite rejects NULL before projection; the non-SQL boundary fixture
        # below exercises a collaborator that supplies an invalid None value.
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            await connection.execute(
                "UPDATE work_items SET description = ? WHERE id = ?", (description, item.id),
            )
        await connection.commit()
        assert (await tool_runtime.work_item_store.get_work_item(item.id)).description == ""
        assert await tool_runtime.work_item_store.list_bookings(work_item_id=item.id) == []
        return
    await connection.execute("UPDATE work_items SET description = ? WHERE id = ?", (description, item.id))
    await connection.commit()
    connection.statements.clear()
    result, _ = await _invoke_pull(
        tool_runtime, tool_id, {"work_item_id": item.id} if tool_id == "claim_work_item" else {},
    )
    assert result.tool_results[0].is_error is True
    assert not any(sql.lstrip().startswith(("INSERT", "UPDATE", "DELETE")) for sql in connection.statements)
    assert (await tool_runtime.work_item_store.get_work_item(item.id)).assigned_to is None


class _ProjectionStore:
    """Corrupt boundary values only; real mutations are tested with SQLite above."""

    def __init__(self) -> None:
        self.item = WorkItem(id="selected-id", assigned_to="agent-a", status="scheduled")
        self.items = (self.item,)
        self.booking = Booking(work_item_id=self.item.id, resource_id="agent-a")
        self.offsets = (0,)
        self.skip_preparation = False
        self.mutation_attempted = False

    async def list_claimable_work_items(
        self, resource_id: str, *, work_type: str | None = None, limit: int = 20, offset: int = 0,
    ) -> ReadyWorkPage:
        return ReadyWorkPage(self.items, None, self.offsets)

    async def claim_work_item(
        self, resource_id: str, work_type: str | None = None,
        department: str | None = None, *, work_item_id: str | None = None,
        agent_pull: bool = False, prepare_claim: Callable[[WorkItem, Booking], None] | None = None,
    ) -> tuple[WorkItem, Booking] | None:
        assert agent_pull is True and prepare_claim is not None
        if not self.skip_preparation:
            prepare_claim(self.item, self.booking)
        self.mutation_attempted = True
        return self.item, self.booking


@pytest.mark.parametrize("field,value", [
    ("description", "\ud800"), ("description", None), ("priority", True), ("id", "other-id"),
    ("assigned_to", "agent-b"), ("title", None),
], ids=["unencodable", "null-description", "bool-priority", "wrong-id", "wrong-owner", "null-title"])
async def test_claim_invalid_plan_projection_refused(field: str, value: Any) -> None:
    store = _ProjectionStore()
    setattr(store.item, field, value)
    tool = ClaimWorkItemTool(store=store, pull_resource_resolver=_Authority())
    result = await tool.invoke(
        {"work_item_id": "selected-id"},
        {"agent_id": "agent-a", "_tool_result_presentation": ToolResultPresentation(render_tool_output)},
    )
    assert result.success is False and store.mutation_attempted is False


@pytest.mark.parametrize("field,value", [
    ("work_item_id", "wrong-item"), ("resource_id", "agent-b"), ("id", ""),
])
async def test_claim_invalid_booking_projection_refused(field: str, value: Any) -> None:
    store = _ProjectionStore()
    setattr(store.booking, field, value)
    tool = ClaimWorkItemTool(store=store, pull_resource_resolver=_Authority())
    result = await tool.invoke(
        {"work_item_id": "selected-id"},
        {"agent_id": "agent-a", "_tool_result_presentation": ToolResultPresentation(render_tool_output)},
    )
    assert result.success is False and store.mutation_attempted is False


@pytest.mark.parametrize("offsets", [(), (-1,), (True,), (0, 0)])
async def test_discovery_invalid_offset_alignment_is_error(offsets: tuple[int, ...]) -> None:
    store = _ProjectionStore()
    store.offsets = offsets
    if len(offsets) == 2:
        store.items = (store.item, dataclasses.replace(store.item, id="second-item"))
    tool = DiscoverWorkItemsTool(store=store, pull_resource_resolver=_Authority())
    result = await tool.invoke(
        {}, {"agent_id": "agent-a", "_tool_result_presentation": ToolResultPresentation(render_tool_output)},
    )
    assert result.success is False


@pytest.mark.parametrize("rendered", [False, 1, ""])
async def test_claim_malformed_presentation_result_is_error(rendered: Any) -> None:
    store = _ProjectionStore()
    tool = ClaimWorkItemTool(store=store, pull_resource_resolver=_Authority())
    result = await tool.invoke(
        {"work_item_id": "selected-id"},
        {"agent_id": "agent-a", "_tool_result_presentation": ToolResultPresentation(lambda value: rendered)},
    )
    assert result.success is False and store.mutation_attempted is False


async def test_claim_store_missing_preparation_is_error_not_cached_success() -> None:
    store = _ProjectionStore()
    store.skip_preparation = True
    tool = ClaimWorkItemTool(store=store, pull_resource_resolver=_Authority())
    result = await tool.invoke(
        {"work_item_id": "selected-id"},
        {"agent_id": "agent-a", "_tool_result_presentation": ToolResultPresentation(render_tool_output)},
    )
    assert result.success is False and result.error == "work_pull_claim_failed"


async def test_claim_missing_item_tiny_budget_is_error(tool_runtime: ProbOSRuntime) -> None:
    result, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": "missing"}, cap=1)
    assert result.tool_results[0].is_error is True and result.tool_results[0].output == "!"


async def test_discovery_empty_page_retains_scan_continuation_in_next_request(
    tool_runtime: ProbOSRuntime,
) -> None:
    for index in range(200):
        await tool_runtime.work_item_store.create_work_item(
            id=f"blocked-{index:03}", title="Trust", trust_requirement=0.99,
            metadata=_PUBLICATION, created_at=1,
        )
    target = await tool_runtime.work_item_store.create_work_item(
        id="visible-row", title="Visible", metadata=_PUBLICATION, created_at=1,
    )
    first, client = await _invoke_pull(tool_runtime, "discover_work_items", {}, cap=6000)
    page = ast.literal_eval(_next_tool_text(client.requests[1], structured=True))
    assert first.tool_results[0].is_error is False
    assert page["items"] == [] and page["next_offset"] == 200
    second, _ = await _invoke_pull(tool_runtime, "discover_work_items", {"offset": page["next_offset"]})
    tail = ast.literal_eval(second.tool_results[0].output)
    assert [item["id"] for item in tail["items"]] == [target.id]
    assert tail["next_offset"] is None


async def test_pull_empty_board_and_exact_type_filter(tool_runtime: ProbOSRuntime) -> None:
    empty, _ = await _invoke_pull(tool_runtime, "discover_work_items", {})
    assert ast.literal_eval(empty.tool_results[0].output)["items"] == []
    await tool_runtime.work_item_store.create_work_item(title="Case sensitive", metadata=_PUBLICATION)
    empty, _ = await _invoke_pull(tool_runtime, "discover_work_items", {"work_type": "Task"})
    assert ast.literal_eval(empty.tool_results[0].output)["items"] == []
    matching, _ = await _invoke_pull(tool_runtime, "discover_work_items", {"work_type": "task"})
    assert len(ast.literal_eval(matching.tool_results[0].output)["items"]) == 1


@pytest.mark.parametrize("race", ["same-item", "same-capacity", "isolated-budgets"])
async def test_real_tools_concurrent_claims_preserve_ownership_and_local_receipts(
    tool_runtime: ProbOSRuntime, race: str,
) -> None:
    await tool_runtime.registry.register(_Agent(id="agent-b"))
    tool_runtime.work_item_store.register_resource(_resource("agent-b"))
    first = await tool_runtime.work_item_store.create_work_item(
        title="First", description="x" * 10_000, metadata=_PUBLICATION,
    )
    second = await tool_runtime.work_item_store.create_work_item(
        title="Second", description="y" * 10_000, metadata=_PUBLICATION,
    )
    tasks = [
        asyncio.create_task(_invoke_pull(
            tool_runtime, "claim_work_item", {"work_item_id": first.id}, cap=0,
        )),
        asyncio.create_task(_invoke_pull(
            tool_runtime, "claim_work_item",
            {"work_item_id": first.id if race == "same-item" else second.id},
            cap=6000, context={"agent_id": "agent-a" if race == "same-capacity" else "agent-b"},
        )),
    ]
    try:
        outcomes = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    receipts = [ast.literal_eval(outcome[0].tool_results[0].output) for outcome in outcomes]
    assert all(not outcome[0].tool_results[0].is_error for outcome in outcomes)
    assert sum(receipt["owned"] for receipt in receipts) == (2 if race == "isolated-budgets" else 1)
    if race == "isolated-budgets":
        assert receipts[0]["work_item"]["description"] == first.description
        assert receipts[1]["work_item"]["description"] is None
        assert receipts[1]["omitted_fields"]["work_item.description"] == "result_budget"
        assert receipts[0]["booking"]["resource_id"] == "agent-a"
        assert receipts[1]["booking"]["resource_id"] == "agent-b"
    assert len(await tool_runtime.work_item_store.list_bookings()) == (2 if race == "isolated-budgets" else 1)


class _TaskDispatcher:
    def __init__(self, *, fail: bool = False) -> None:
        self.events: list[Any] = []
        self.fail = fail

    async def dispatch(self, event: Any) -> Any:
        self.events.append(event)
        if self.fail:
            raise RuntimeError("injected_notification_failure")
        return SimpleNamespace(accepted=1, rejected=0, unroutable=0)


async def test_governed_claim_and_replay_emit_once_without_self_notification(
    tool_runtime: ProbOSRuntime, workforce_events: list[tuple[str, dict[str, Any]]],
) -> None:
    store = tool_runtime.work_item_store
    dispatcher = _TaskDispatcher()
    store.attach_dispatcher(dispatcher)
    item = await store.create_work_item(title="No redundant task", metadata=_PUBLICATION)
    workforce_events.clear()

    first, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": item.id})
    replay, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": item.id})

    assert first.tool_results[0].is_error is False and replay.tool_results[0].is_error is False
    assert first.tool_results[0].output == replay.tool_results[0].output
    assert [event for event, _ in workforce_events] == ["work_item_assigned", "work_item_claimed"]
    assert dispatcher.events == []
    assert len(await store.list_bookings(work_item_id=item.id)) == 1


@pytest.mark.parametrize("structured", [False, True])
async def test_paused_replay_small_budget_refuses_then_returns_same_booking_at_capacity(
    tool_runtime: ProbOSRuntime, db_factory: _Factory,
    workforce_events: list[tuple[str, dict[str, Any]]], structured: bool,
) -> None:
    store = tool_runtime.work_item_store
    item = await store.create_work_item(title="Paused", description="x" * 9000, metadata=_PUBLICATION)
    first, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": item.id})
    booking_id = ast.literal_eval(first.tool_results[0].output)["booking"]["id"]
    await store.start_booking(booking_id)
    await store.pause_booking(booking_id)
    other = await store.create_work_item(title="Full capacity", metadata=_PUBLICATION)
    admitted, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": other.id})
    assert ast.literal_eval(admitted.tool_results[0].output)["owned"] is True
    await store.update_work_item(item.id, metadata={}, depends_on=["missing"], trust_requirement=0.99)
    workforce_events.clear()
    connection = db_factory.connection
    assert connection is not None
    connection.statements.clear()

    small, _ = await _invoke_pull(
        tool_runtime, "claim_work_item", {"work_item_id": item.id}, cap=1, structured=structured,
    )
    replay, client = await _invoke_pull(
        tool_runtime, "claim_work_item", {"work_item_id": item.id}, cap=6000, structured=structured,
    )

    assert small.tool_results[0].is_error is True and small.tool_results[0].output == "!"
    assert replay.tool_results[0].is_error is False
    receipt = ast.literal_eval(_next_tool_text(client.requests[1], structured=structured))
    assert receipt["booking"]["id"] == booking_id and receipt["booking"]["status"] == "on_break"
    assert receipt["work_item"]["status"] == "in_progress"
    assert receipt["work_item"]["description"] is None
    assert receipt["omitted_fields"]["work_item.description"] == "result_budget"
    assert (await store.get_booking(booking_id)).status == "on_break"
    assert len(await store.list_bookings(work_item_id=item.id)) == 1
    assert not any(sql.lstrip().startswith(("INSERT", "UPDATE", "DELETE")) for sql in connection.statements)
    assert workforce_events == []


async def test_legacy_postcommit_notification_failure_retains_receipt(
    pull_store: WorkItemStore, caplog: pytest.LogCaptureFixture,
) -> None:
    dispatcher = _TaskDispatcher(fail=True)
    pull_store.attach_dispatcher(dispatcher)
    item = await pull_store.create_work_item(title="Durable despite notification")
    planned: list[str] = []

    def prepare(item: WorkItem, booking: Booking) -> None:
        planned.append(booking.id)

    result = await pull_store.claim_work_item("agent-a", work_item_id=item.id, prepare_claim=prepare)
    replay = await pull_store.claim_work_item("agent-a", work_item_id=item.id)

    assert result is not None and replay is not None
    assert result[1].id == replay[1].id == planned[0]
    assert len(dispatcher.events) == 1
    assert len(await pull_store.list_bookings(work_item_id=item.id)) == 1
    assert "booking stands" in caplog.text


async def test_governed_postcommit_event_failure_retains_committed_outcome(authority: _Authority) -> None:
    fail = False
    attempted: list[str] = []

    def emit(event: str, data: dict[str, Any]) -> None:
        if fail:
            attempted.append(event)
            raise RuntimeError("injected_event_failure")

    store = WorkItemStore(
        db_path=":memory:", emit_event=emit, tick_interval=1000, pull_resource_resolver=authority,
    )
    await store.start()
    try:
        store.register_resource(_resource())
        item = await store.create_work_item(title="Event failure", metadata=_PUBLICATION)
        fail = True
        result = await store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
        assert result is not None
        assert (await store.get_work_item(item.id)).assigned_to == "agent-a"
        replay = await store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
        assert replay[1].id == result[1].id
        assert attempted == ["work_item_assigned", "work_item_claimed"]
        assert len(await store.list_bookings(work_item_id=item.id)) == 1
    finally:
        await store.stop()


async def test_claim_rollback_failure_never_returns_prepared_success(
    tool_runtime: ProbOSRuntime, db_factory: _Factory,
) -> None:
    store = tool_runtime.work_item_store
    item = await store.create_work_item(title="Rollback fault", metadata=_PUBLICATION)
    connection = db_factory.connection
    assert connection is not None
    connection.fail_sql = "INSERT INTO booking_timestamps"
    connection.fail_rollback = True
    try:
        result, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": item.id})
        assert result.tool_results[0].is_error is True
        assert "owned" not in result.tool_results[0].output
    finally:
        connection.fail_sql = ""
        connection.fail_rollback = False
        await connection.execute("ROLLBACK")
    assert (await store.get_work_item(item.id)).assigned_to is None
    assert await store.list_bookings(work_item_id=item.id) == []


@pytest.mark.parametrize("operation", [
    "create", "update", "start", "pause", "resume", "complete", "cancel", "journal", "unassign",
])
async def test_other_public_writes_cannot_split_a_claim_transaction(operation: str) -> None:
    factory = _Factory()
    store = WorkItemStore(db_path=":memory:", connection_factory=factory, tick_interval=1000)
    await store.start()
    tasks: list[asyncio.Task[Any]] = []
    try:
        store.register_resource(_resource())
        store.register_resource(_resource("agent-b"))
        other = await store.create_work_item(title="Existing booking")
        booking = await store.assign_work_item(other.id, "agent-b")
        assert booking is not None
        if operation in ("pause", "resume", "complete", "journal"):
            await store.start_booking(booking.id)
        if operation == "resume":
            await store.pause_booking(booking.id)
        target = await store.create_work_item(title="Must roll back")
        connection = factory.connection
        assert connection is not None
        connection.statements.clear()
        connection.pause_sql = "INSERT INTO booking_timestamps"
        claim = asyncio.create_task(store.claim_work_item("agent-a", work_item_id=target.id))
        tasks.append(claim)
        await asyncio.wait_for(connection.reached.wait(), timeout=3)
        assert (await store.get_work_item(target.id)).assigned_to == "agent-a"
        marker = len(connection.statements)

        async def other_write() -> Any:
            if operation == "create":
                return await store.create_work_item(title="Concurrent create")
            if operation == "update":
                return await store.update_work_item(other.id, title="Concurrent update")
            if operation == "unassign":
                return await store.unassign_work_item(other.id)
            if operation == "journal":
                return await store.generate_journal(booking.id)
            return await getattr(store, f"{operation}_booking")(booking.id)

        writer = asyncio.create_task(other_write())
        tasks.append(writer)
        await asyncio.sleep(0)
        assert not writer.done()
        assert "COMMIT" not in connection.statements[marker:]
        claim.cancel()
        with pytest.raises(asyncio.CancelledError):
            await claim
        connection.pause_sql = ""
        connection.release.set()
        await asyncio.wait_for(writer, timeout=3)
        assert (await store.get_work_item(target.id)).assigned_to is None
        assert await store.list_bookings(work_item_id=target.id) == []
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await store.stop()


async def test_conflicting_booking_replay_is_integrity_error(
    tool_runtime: ProbOSRuntime, db_factory: _Factory,
) -> None:
    store = tool_runtime.work_item_store
    item = await store.create_work_item(title="Conflicting bookings", metadata=_PUBLICATION)
    fresh = await store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
    assert fresh is not None
    connection = db_factory.connection
    assert connection is not None
    await connection.execute(
        "INSERT INTO bookings (id, resource_id, work_item_id, status, start_time) VALUES (?, ?, ?, ?, ?)",
        ("duplicate-booking", "agent-a", item.id, "scheduled", time.time()),
    )
    await connection.commit()
    with pytest.raises(RuntimeError, match="work_pull_booking_integrity"):
        await store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
    result, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": item.id})
    assert result.tool_results[0].is_error is True
    assert len(await store.list_bookings(work_item_id=item.id)) == 2


@pytest.mark.parametrize("change", ["missing", "completed", "reassigned"])
async def test_claim_replay_missing_terminal_or_reassigned_booking_never_reacquires(
    tool_runtime: ProbOSRuntime, db_factory: _Factory, change: str,
) -> None:
    store = tool_runtime.work_item_store
    item = await store.create_work_item(title="Old ownership", metadata=_PUBLICATION)
    first = await store.claim_work_item("agent-a", work_item_id=item.id, agent_pull=True)
    assert first is not None
    connection = db_factory.connection
    assert connection is not None
    if change == "missing":
        await connection.execute("DELETE FROM booking_timestamps WHERE booking_id = ?", (first[1].id,))
        await connection.execute("DELETE FROM bookings WHERE id = ?", (first[1].id,))
        await connection.commit()
    elif change == "completed":
        await store.complete_booking(first[1].id)
    else:
        await tool_runtime.registry.register(_Agent(id="agent-b"))
        store.register_resource(_resource("agent-b"))
        await store.unassign_work_item(item.id)
        assert await store.assign_work_item(item.id, "agent-b") is not None
    before = [booking.to_dict() for booking in await store.list_bookings(work_item_id=item.id)]

    result, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": item.id})

    assert ast.literal_eval(result.tool_results[0].output) == {"owned": False, "reason": "not_claimable"}
    assert [booking.to_dict() for booking in await store.list_bookings(work_item_id=item.id)] == before


async def test_requirement_department_blocks_discovery_claim_and_legacy_assign(
    tool_runtime: ProbOSRuntime, db_factory: _Factory,
) -> None:
    store = tool_runtime.work_item_store
    item = await store.create_work_item(title="Engineering only", metadata=_PUBLICATION)
    connection = db_factory.connection
    assert connection is not None
    await connection.execute(
        "UPDATE resource_requirements SET department_constraint = ? WHERE work_item_id = ?",
        ("engineering", item.id),
    )
    await connection.commit()
    discovered, _ = await _invoke_pull(tool_runtime, "discover_work_items", {})
    claimed, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": item.id})
    assert ast.literal_eval(discovered.tool_results[0].output)["items"] == []
    assert ast.literal_eval(claimed.tool_results[0].output)["owned"] is False
    assert await store.assign_work_item(item.id, "agent-a") is None


async def test_current_write_revocation_after_offer_denies_actual_claim(tmp_path: Path) -> None:
    async with _communication_runtime(tmp_path) as runtime:
        item = await runtime.work_item_store.create_work_item(title="Revoked", metadata=_PUBLICATION)

        class _RevokingClient(_ScriptedClient):
            async def complete(self, request: LLMRequest, **kwargs: Any) -> LLMResponse:
                if not self.requests:
                    offered = {tool["function"]["name"] for tool in request.tools}
                    assert "claim_work_item" in offered
                    await runtime.tool_permission_store.issue_grant(
                        "agent-a", "claim_work_item", ToolPermission.READ, is_restriction=True,
                    )
                return await super().complete(request, **kwargs)

        client = _RevokingClient([
            _call_response("claim_work_item", {"work_item_id": item.id}), _final_response(),
        ])
        await WorkItemAgenticExecutor(llm_client=client).run(
            agent_id="agent-a", instructions="Choose work.", task_text="Claim selected work.", runtime=runtime,
        )
        assert _next_tool_text(client.requests[1], structured=False) == "work_pull_authority_denied"
        assert (await runtime.work_item_store.get_work_item(item.id)).assigned_to is None
        assert await runtime.work_item_store.list_bookings(work_item_id=item.id) == []


async def test_provider_failure_after_commit_recovers_by_exact_id_replay(
    tool_runtime: ProbOSRuntime, workforce_events: list[tuple[str, dict[str, Any]]],
) -> None:
    item = await tool_runtime.work_item_store.create_work_item(title="Recover receipt", metadata=_PUBLICATION)
    workforce_events.clear()

    def failed_response(request: LLMRequest) -> LLMResponse:
        assert ast.literal_eval(_next_tool_text(request, structured=True))["owned"] is True
        raise RuntimeError("scripted_provider_failure")

    client = _ScriptedClient([
        _call_response("claim_work_item", {"work_item_id": item.id}), failed_response,
    ])
    result = await AgenticLoop(
        llm_client=client, tool_executor=ToolExecutor(registry=tool_runtime.tool_registry),
        structured_tool_messages=True,
    ).run(
        system_prompt="SYS", user_message="Task", tools=[],
        context={"agent_id": "agent-a", "department": "science", "rank": "ensign"},
    )
    assert result.error is not None
    first = ast.literal_eval(result.tool_results[0].output)
    replay, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": item.id})
    assert ast.literal_eval(replay.tool_results[0].output)["booking"]["id"] == first["booking"]["id"]
    assert len(await tool_runtime.work_item_store.list_bookings(work_item_id=item.id)) == 1
    assert [event for event, _ in workforce_events] == ["work_item_assigned", "work_item_claimed"]


@pytest.mark.parametrize("fields", [
    {"status": "discussing"}, {"status": "planned"}, {"status": "in_progress"},
    {"status": "draft"}, {"status": "scheduled"},
    {"parent_id": "parent"},
    {"metadata": {**_PUBLICATION, "ui_scaffold": True}},
    {"metadata": {**_PUBLICATION, "room_id": "room"}},
    {"metadata": {**_PUBLICATION, "session_id": "session"}},
    {"metadata": {**_PUBLICATION, "crew_execution": {}}},
    {"required_capabilities": ["not-a-current-characteristic"]},
])
async def test_pull_nonstandalone_nonready_or_ineligible_rows_are_uniform_misses(
    tool_runtime: ProbOSRuntime, db_factory: _Factory, fields: dict[str, Any],
) -> None:
    if "ui_scaffold" in fields.get("metadata", {}):
        with pytest.raises(ValueError, match="ui_scaffold_write_reserved"):
            await tool_runtime.work_item_store.create_work_item(title="Excluded", **fields)
        # Ordinary writes reserve this flag. Model a previously persisted UI
        # scaffold in the isolated test DB, without weakening that write guard.
        item = await tool_runtime.work_item_store.create_work_item(title="Excluded", metadata=_PUBLICATION)
        connection = db_factory.connection
        assert connection is not None
        await connection.execute(
            "UPDATE work_items SET metadata = ? WHERE id = ?", (json.dumps(fields["metadata"]), item.id),
        )
        await connection.commit()
    else:
        item = await tool_runtime.work_item_store.create_work_item(
            **{"title": "Excluded", "metadata": _PUBLICATION, **fields},
        )
    discovery, _ = await _invoke_pull(tool_runtime, "discover_work_items", {})
    claim, _ = await _invoke_pull(tool_runtime, "claim_work_item", {"work_item_id": item.id})
    assert ast.literal_eval(discovery.tool_results[0].output)["items"] == []
    assert ast.literal_eval(claim.tool_results[0].output) == {"owned": False, "reason": "not_claimable"}
    assert await tool_runtime.work_item_store.list_bookings(work_item_id=item.id) == []


@pytest.mark.parametrize("field,value", [
    ("active", False), ("active", 1), ("capacity", 0), ("capacity", True),
    ("capacity", 1.5), ("department", None), ("agent_type", None),
    ("characteristics", {}), ("characteristics", [{"skill": "trust", "proficiency": float("nan")}]),
    ("characteristics", [{"skill": "trust", "proficiency": True}]),
], ids=["inactive", "integer-active", "zero-capacity", "bool-capacity", "float-capacity",
        "null-department", "null-type", "invalid-characteristics", "nonfinite-trust", "bool-trust"])
async def test_store_malformed_declared_authority_denies(
    governed_store: WorkItemStore, authority: _Authority, field: str, value: Any,
) -> None:
    resource = authority.resources["agent-a"]
    setattr(resource, field, value)
    governed_store.register_resource(dataclasses.replace(resource))
    with pytest.raises(PermissionError, match="work_pull_authority_denied"):
        await governed_store.list_claimable_work_items("agent-a")
    with pytest.raises(PermissionError, match="work_pull_authority_denied"):
        await governed_store.claim_work_item("agent-a", work_item_id="missing", agent_pull=True)
    assert await governed_store.claim_work_item("agent-a") is None


async def test_store_unstarted_public_pull_methods_fail_honestly(authority: _Authority) -> None:
    store = WorkItemStore(pull_resource_resolver=authority)
    with pytest.raises(RuntimeError, match="work_pull_store_unavailable"):
        await store.list_claimable_work_items("agent-a")
    with pytest.raises(RuntimeError, match="work_pull_store_unavailable"):
        await store.claim_work_item("agent-a", work_item_id="missing", agent_pull=True)
    assert await store.claim_work_item("agent-a") is None


@pytest.mark.parametrize("arguments", [
    (None, "claim", True), ("", "claim", True), ("agent-a", "unknown", True),
    ("agent-a", "claim", 1), ("agent-a", "assign", True), ("agent-a", "resume", True),
])
def test_runtime_resolver_invalid_pull_boundary_returns_none(
    runtime: ProbOSRuntime, arguments: tuple[Any, Any, Any],
) -> None:
    assert runtime.resolve_workforce_pull_resource(*arguments) is None


async def test_legacy_rest_envelopes_and_optin_patch_remain_compatible(tool_runtime: ProbOSRuntime) -> None:
    store = tool_runtime.work_item_store
    app = FastAPI()
    app.include_router(workforce_router)
    app.dependency_overrides[get_runtime] = lambda: tool_runtime
    tool_runtime.tool_registry.get("claim_work_item").default_permissions = {
        rank: "none" for rank in ("ensign", "lieutenant", "commander", "senior_officer")
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://in-process.test", trust_env=False,
    ) as client:
        response = await client.post("/api/work-items", json={"title": "Captain private work"})
        assert response.status_code == 200 and set(response.json()) == {"work_item"}
        created = response.json()["work_item"]
        assert set(created) == {field.name for field in dataclasses.fields(WorkItem)}
        legacy = await client.post("/api/work-items/claim", json={
            "resource_id": "agent-a", "work_type": "task", "department": "science",
        })
        assert legacy.status_code == 200
        claimed = legacy.json()
        assert set(claimed) == {"work_item", "booking"}
        assert claimed["work_item"]["id"] == created["id"]
        assert claimed["work_item"]["metadata"] == {}
        assert set(claimed["booking"]) == {field.name for field in dataclasses.fields(Booking)}
        second = await client.post("/api/work-items", json={"title": "Publish by patch"})
        other_id = second.json()["work_item"]["id"]
        patched = await client.patch(f"/api/work-items/{other_id}", json={"metadata": _PUBLICATION})
        assert patched.status_code == 200 and patched.json()["work_item"]["metadata"] == _PUBLICATION
        await store.start_booking(claimed["booking"]["id"])
        await store.pause_booking(claimed["booking"]["id"])
        page, _ = await _invoke_pull(tool_runtime, "discover_work_items", {})
        assert [row["id"] for row in ast.literal_eval(page.tool_results[0].output)["items"]] == [other_id]


@pytest.mark.parametrize("resource_id", ["agent-a", "missing-resource"])
async def test_assign_crew_reservation_precedes_resource_resolution(
    governed_store: WorkItemStore, resource_id: str,
) -> None:
    port = governed_store.claim_crew_session_admission_port()
    async with port.reserve() as reservation:
        parent = await reservation.create_parent(CrewSessionParentCreate(
            id="reserved-parent", title="Reserved", description="Reserved work",
            assigned_to="facilitator", created_by="captain", metadata={},
        ))
    with pytest.raises(ValueError, match="^crew_session_write_reserved$"):
        await governed_store.assign_work_item(parent.id, resource_id)
    assert await governed_store.get_work_item(parent.id) == parent
    assert await governed_store.list_bookings(work_item_id=parent.id) == []


class _IdString(str):
    pass


@pytest.mark.parametrize("item_id", [
    "", None, 0, 17, False, b"x", "x" * 129, _IdString("x"),
], ids=["empty", "none", "zero", "integer", "bool", "bytes", "129", "str-subclass"])
async def test_claim_invalid_id_domain_rejects_before_readiness_reads(
    runtime: ProbOSRuntime, db_factory: _Factory, monkeypatch: pytest.MonkeyPatch,
    item_id: Any,
) -> None:
    store = runtime.work_item_store
    item = await store.create_work_item(
        title="Malformed collaborator row", metadata=_PUBLICATION,
        depends_on=["dependency-id"],
    )
    connection = db_factory.connection
    assert connection is not None
    lookups: list[str] = []
    original_get = store.get_work_item

    async def get_work_item(wanted: str) -> WorkItem | None:
        lookups.append(wanted)
        if wanted == item.id:
            return dataclasses.replace(item, id=item_id)
        return await original_get(wanted)

    connection.statements.clear()
    with monkeypatch.context() as patch:
        patch.setattr(store, "get_work_item", get_work_item)
        result = await store.claim_work_item(
            "agent-a", work_item_id=item.id, agent_pull=True,
        )

    assert result is None
    assert lookups == [item.id]
    assert not any("SELECT department_constraint" in sql for sql in connection.statements)
    assert not any(sql.lstrip().startswith(("INSERT", "UPDATE", "DELETE")) for sql in connection.statements)
    assert await store.get_work_item(item.id) == item
    assert await store.list_bookings(work_item_id=item.id) == []


@pytest.mark.parametrize("item_id", [
    "", "x", "x" * 7, "x" * 8, "x" * 128, "x" * 129, " x ", " ", " " * 8,
], ids=["empty", "1", "7", "8", "128", "129", "padded", "space", "spaces"])
async def test_discovery_id_domain_preserves_exact_ids_and_legacy_rows(
    governed_store: WorkItemStore, item_id: str,
) -> None:
    item = await governed_store.create_work_item(
        id=item_id, title="Legacy ID", metadata=_PUBLICATION,
    )

    page = await governed_store.list_claimable_work_items("agent-a")

    admitted = 1 <= len(item_id) <= 128
    assert [row.id for row in page.items] == ([item_id] if admitted else [])
    assert page.item_offsets == ((0,) if admitted else ())
    assert page.next_offset is None
    assert await governed_store.get_work_item(item_id) == item
    assert await governed_store.list_bookings(work_item_id=item_id) == []


async def test_discovery_id_domain_filtered_gaps_preserve_examined_offsets(
    governed_store: WorkItemStore,
) -> None:
    ids = ("L" * 129, "x", "M" * 129, "seven77", "N" * 129, " " * 8)
    for index, item_id in enumerate(ids):
        await governed_store.create_work_item(
            id=item_id, title="Examined row", metadata=_PUBLICATION,
            created_at=float(index + 1),
        )

    page = await governed_store.list_claimable_work_items("agent-a", limit=2)

    assert [item.id for item in page.items] == ["x", "seven77"]
    assert page.item_offsets == (1, 3)
    assert page.next_offset == 4
    tail = await governed_store.list_claimable_work_items("agent-a", offset=page.next_offset)
    assert [item.id for item in tail.items] == [" " * 8]
    assert tail.item_offsets == (5,)
    assert tail.next_offset is None
    assert len(await governed_store.list_work_items()) == len(ids)


async def test_discovery_id_domain_invalid_scan_keeps_empty_continuation(
    governed_store: WorkItemStore,
) -> None:
    for index in range(201):
        await governed_store.create_work_item(
            id=f"{index:03}" + "x" * 126, title="Unclaimable ID",
            metadata=_PUBLICATION, created_at=float(index + 1),
        )
    item = await governed_store.create_work_item(
        id="selected-row", title="After invalid scan", metadata=_PUBLICATION,
        created_at=202.0,
    )

    page = await governed_store.list_claimable_work_items("agent-a")

    assert page == ReadyWorkPage((), 200)
    tail = await governed_store.list_claimable_work_items("agent-a", offset=page.next_offset)
    assert [row.id for row in tail.items] == [item.id]
    assert tail.item_offsets == (201,)
    assert tail.next_offset is None
    assert len(await governed_store.list_work_items(limit=300)) == 202


async def test_legacy_claim_id_domain_keeps_long_untargeted_claim(
    pull_store: WorkItemStore,
) -> None:
    item = await pull_store.create_work_item(id="L" * 129, title="Legacy long ID")

    claimed = await pull_store.claim_work_item("agent-a")

    assert claimed is not None and claimed[0].id == item.id
    assert (await pull_store.get_work_item(item.id)).assigned_to == "agent-a"
    assert [booking.id for booking in await pull_store.list_bookings(work_item_id=item.id)] == [
        claimed[1].id,
    ]


@pytest.mark.parametrize("item_id", [
    "", None, 0, 17, False, b"x", "x" * 129, _IdString("x"),
], ids=["empty", "none", "zero", "integer", "bool", "bytes", "129", "str-subclass"])
async def test_discovery_id_domain_projection_rejects_instead_of_omitting(
    item_id: Any,
) -> None:
    store = _ProjectionStore()
    store.item.id = item_id
    store.items = (WorkItem(id="valid-first"), store.item)
    store.offsets = (0, 1)
    tool = DiscoverWorkItemsTool(store=store, pull_resource_resolver=_Authority())

    result = await tool.invoke(
        {}, {"agent_id": "agent-a", "_tool_result_presentation": ToolResultPresentation(render_tool_output)},
    )

    assert result.success is False
    assert result.error == "work_pull_input_or_projection_invalid"
    assert result.output is None
    assert store.mutation_attempted is False


@pytest.mark.parametrize("item_id", [
    "x", "x" * 7, "x" * 8, "x" * 128, " x ", " ", " " * 8,
], ids=["1", "7", "8", "128", "padded", "space", "spaces"])
@pytest.mark.parametrize("claim", [False, True], ids=["discover", "claim"])
async def test_pull_id_domain_projection_preserves_exact_strings(
    item_id: str, claim: bool,
) -> None:
    store = _ProjectionStore()
    store.item.id = store.booking.work_item_id = item_id
    tool_class = ClaimWorkItemTool if claim else DiscoverWorkItemsTool
    tool = tool_class(store=store, pull_resource_resolver=_Authority())

    result = await tool.invoke(
        {"work_item_id": item_id} if claim else {},
        {"agent_id": "agent-a", "_tool_result_presentation": ToolResultPresentation(render_tool_output)},
    )

    assert result.success is True
    value = ast.literal_eval(result.output)
    projected = value["work_item"] if claim else value["items"][0]
    assert projected["id"] == item_id
    assert store.mutation_attempted is claim


_SHORT_STATUS_ID_REASON = "a task id of at least 8 characters is needed to identify one task"
_MISSING_STATUS_ID_REASON = (
    "no task with that id belongs to you. It may belong to "
    "another crew member, or the id may be wrong."
)


class _FakeStatusStore:
    def __init__(
        self, items: Sequence[WorkItem] = (), *, fail_get: str | None = None,
        fail_list: bool = False,
    ) -> None:
        self.items = list(items)
        self.calls: list[tuple[str, str | None]] = []
        self.fail_get = fail_get
        self.fail_list = fail_list

    async def get_work_item(self, wanted: str) -> WorkItem | None:
        self.calls.append(("get", wanted))
        if wanted == self.fail_get:
            raise RuntimeError("injected_status_lookup_failure")
        return next((item for item in self.items if item.id == wanted), None)

    async def list_work_items(self) -> list[WorkItem]:
        self.calls.append(("list", None))
        if self.fail_list:
            raise RuntimeError("injected_status_listing_failure")
        return self.items


class _NonStringId:
    def __str__(self) -> str:
        raise AssertionError("A non-string task ID must not be coerced")

    def __bool__(self) -> bool:
        raise AssertionError("A non-string task ID must not be truth-tested")


@pytest.mark.parametrize("item_id", [
    "x", "x" * 7, "x" * 8, "x" * 128, "x" * 129,
    " x ", " xxxxxxxx ", " ", " " * 8, "\t\r\n", _IdString("x"),
], ids=["1", "7", "8", "128", "legacy-129", "padded-short", "padded-long",
        "space", "spaces", "whitespace", "str-subclass"])
async def test_status_id_domain_owned_raw_exact_precedes_collisions(item_id: str) -> None:
    rows = [
        WorkItem(id=item_id + "-longer", assigned_to="agent-a", title="Raw prefix collision"),
        WorkItem(id=item_id.strip() + "-longer", assigned_to="agent-a", title="Trimmed prefix collision"),
    ]
    if item_id.strip() != item_id:
        rows.append(WorkItem(id=item_id.strip(), assigned_to="agent-a", title="Trimmed exact collision"))
    rows.append(WorkItem(
        id=item_id, assigned_to="agent-a", title="Raw exact owner", status="scheduled",
        description="private-description", metadata={"private": "private-metadata"},
    ))
    store = _FakeStatusStore(rows, fail_list=True)
    tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=store))

    result = await tool.invoke({"work_item_id": item_id}, {"agent_id": "agent-a"})

    assert result.error is None and result.output["found"] is True
    assert result.output["work_item_id"] == item_id
    assert result.output["title"] == "Raw exact owner"
    assert result.output["status"] == "scheduled"
    assert set(result.output) == {
        "found", "work_item_id", "title", "status", "is_final", "created_at",
        "updated_at", "age_seconds", "seconds_since_last_change", "summary",
    }
    assert "private-description" not in str(result.output)
    assert "private-metadata" not in str(result.output)
    assert store.calls == [("get", item_id)]


@pytest.mark.parametrize("foreign_raw", [False, True], ids=["absent-raw", "foreign-raw"])
@pytest.mark.parametrize("trimmed_state", ["owned", "foreign", "absent"])
async def test_status_id_domain_trimmed_fallback_stays_owned(
    foreign_raw: bool, trimmed_state: str,
) -> None:
    wanted = " xxxxxxxx "
    rows = [
        WorkItem(id="xxxxxxxx-foreign", assigned_to="agent-b", title="secret-prefix"),
        WorkItem(id="xxxxxxxx-owned", assigned_to="agent-a", title="Owned prefix"),
    ]
    if foreign_raw:
        rows.append(WorkItem(id=wanted, assigned_to="agent-b", title="secret-raw"))
    if trimmed_state != "absent":
        rows.append(WorkItem(
            id=wanted.strip(), assigned_to="agent-a" if trimmed_state == "owned" else "agent-b",
            title="Owned exact" if trimmed_state == "owned" else "secret-trimmed",
        ))
    store = _FakeStatusStore(rows)
    tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=store))

    result = await tool.invoke({"work_item_id": wanted}, {"agent_id": "agent-a"})

    assert result.error is None and result.output["found"] is True
    assert result.output["work_item_id"] == (
        "xxxxxxxx" if trimmed_state == "owned" else "xxxxxxxx-owned"
    )
    assert "secret" not in str(result.output)
    expected_calls: list[tuple[str, str | None]] = [("get", wanted), ("get", wanted.strip())]
    if trimmed_state != "owned":
        expected_calls.append(("list", None))
    assert store.calls == expected_calls


@pytest.mark.parametrize("foreign_exact", [False, True], ids=["absent-exact", "foreign-exact"])
async def test_status_id_domain_eight_character_prefix_filters_owners(foreign_exact: bool) -> None:
    rows = [
        WorkItem(id="xxxxxxxx-foreign", assigned_to="agent-b", title="secret-prefix"),
        WorkItem(id="xxxxxxxx-owned", assigned_to="agent-a", title="Owned prefix"),
    ]
    if foreign_exact:
        rows.append(WorkItem(id="xxxxxxxx", assigned_to="agent-b", title="secret-exact"))
    store = _FakeStatusStore(rows)
    tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=store))

    result = await tool.invoke({"work_item_id": "xxxxxxxx"}, {"agent_id": "agent-a"})

    assert result.error is None and result.output["work_item_id"] == "xxxxxxxx-owned"
    assert "secret" not in str(result.output)
    assert store.calls == [("get", "xxxxxxxx"), ("list", None)]


@pytest.mark.parametrize("wanted", ["x", "xxxxxxx", " x ", " xxxxxxx ", " " * 8])
@pytest.mark.parametrize("foreign_exact", [False, True], ids=["absent-exact", "foreign-exact"])
async def test_status_id_domain_short_prefix_never_resolves(
    wanted: str, foreign_exact: bool,
) -> None:
    rows = [
        WorkItem(id=wanted + "-owned", assigned_to="agent-a", title="Owned raw prefix"),
        WorkItem(id=wanted.strip() + "-owned", assigned_to="agent-a", title="Owned trimmed prefix"),
    ]
    if wanted.strip() and wanted.strip() != wanted:
        rows.append(WorkItem(id=wanted.strip(), assigned_to="agent-a", title="Owned short trimmed ID"))
    if foreign_exact:
        rows.append(WorkItem(id=wanted, assigned_to="agent-b", title="secret-exact"))
    store = _FakeStatusStore(rows, fail_list=True)
    tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=store))

    result = await tool.invoke({"work_item_id": wanted}, {"agent_id": "agent-a"})

    assert result.error is None
    assert result.output == {"found": False, "reason": _SHORT_STATUS_ID_REASON}
    assert store.calls == [("get", wanted)]


@pytest.mark.parametrize("wanted", [
    None, "", 0, False, 17, 12345678, b"12345678", ["12345678"],
    {"id": "12345678"}, _NonStringId(),
], ids=["none", "empty", "zero", "bool", "short-integer", "long-integer",
        "bytes", "list", "dict", "no-coercion"])
async def test_status_id_domain_invalid_input_is_benign_without_lookup(wanted: Any) -> None:
    store = _FakeStatusStore([WorkItem(id="12345678", assigned_to="agent-a")])
    tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=store))

    result = await tool.invoke({"work_item_id": wanted}, {"agent_id": "agent-a"})

    assert result.error is None
    assert result.output == {"found": False, "reason": _SHORT_STATUS_ID_REASON}
    assert store.calls == []


async def test_status_id_domain_missing_input_is_benign_without_lookup() -> None:
    store = _FakeStatusStore()
    tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=store))

    result = await tool.invoke({}, {"agent_id": "agent-a"})

    assert result.error is None
    assert result.output == {"found": False, "reason": _SHORT_STATUS_ID_REASON}
    assert store.calls == []


@pytest.mark.parametrize("wanted", [
    "x", "x" * 7, "x" * 8, "x" * 128, "x" * 129, " x ", " ", " " * 8, None, 0, 12345678,
], ids=["1", "7", "8", "128", "129", "padded", "space", "spaces", "none", "zero", "integer"])
async def test_status_id_domain_no_store_keeps_existing_reasons(wanted: Any) -> None:
    tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=None))

    result = await tool.invoke({"work_item_id": wanted}, {"agent_id": "agent-a"})

    reason = (
        "task records are not available on this ship"
        if isinstance(wanted, str) and len(wanted.strip()) >= 8 else _SHORT_STATUS_ID_REASON
    )
    assert result.error is None
    assert result.output == {"found": False, "reason": reason}


@pytest.mark.parametrize("wanted", ["x", "xxxxxxxx"])
@pytest.mark.parametrize("context", [None, {}, {"agent_id": ""}])
async def test_status_id_domain_anonymous_never_reads_owned_rows(
    wanted: str, context: dict[str, Any] | None,
) -> None:
    store = _FakeStatusStore([
        WorkItem(id=wanted, assigned_to="agent-a", title="secret-owned"),
        WorkItem(id=wanted + "-longer", assigned_to="agent-a", title="secret-prefix"),
        WorkItem(id=wanted + "-unassigned", assigned_to=None, title="secret-unassigned"),
    ])
    tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=store))

    result = await tool.invoke({"work_item_id": wanted}, context)

    assert result.error is None and result.output["found"] is False
    assert "secret" not in str(result.output)
    assert store.calls == [("get", wanted)] + ([("list", None)] if len(wanted) >= 8 else [])


@pytest.mark.parametrize("foreign_rows", [False, True], ids=["absent", "private"])
async def test_status_id_domain_unknown_and_private_have_identical_misses(foreign_rows: bool) -> None:
    wanted = " unknown-id "
    store = _FakeStatusStore([
        WorkItem(id=item_id, assigned_to="agent-b", title="secret-title", metadata={"private": True})
        for item_id in (wanted, wanted.strip(), wanted.strip() + "-longer")
    ] if foreign_rows else [])
    tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=store))

    result = await tool.invoke({"work_item_id": wanted}, {"agent_id": "agent-a"})

    assert result.error is None
    assert result.output == {
        "found": False, "work_item_id": wanted.strip(), "reason": _MISSING_STATUS_ID_REASON,
    }
    assert store.calls == [("get", wanted), ("get", wanted.strip()), ("list", None)]


@pytest.mark.parametrize("wanted,fail_get,fail_list,calls", [
    ("x", "x", False, [("get", "x")]),
    (" xxxxxxxx ", " xxxxxxxx ", False, [("get", " xxxxxxxx ")]),
    (" xxxxxxxx ", "xxxxxxxx", False, [("get", " xxxxxxxx "), ("get", "xxxxxxxx")]),
    ("xxxxxxxx", None, True, [("get", "xxxxxxxx"), ("list", None)]),
], ids=["short-exact-error", "raw-exact-error", "trimmed-exact-error", "prefix-error"])
async def test_status_id_domain_lookup_failures_keep_degradation(
    wanted: str, fail_get: str | None, fail_list: bool, calls: list[tuple[str, str | None]],
) -> None:
    store = _FakeStatusStore(fail_get=fail_get, fail_list=fail_list)
    tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=store))

    result = await tool.invoke({"work_item_id": wanted}, {"agent_id": "agent-a"})

    assert result.error is None
    assert result.output == {"found": False, "reason": "the task record could not be read just now"}
    assert store.calls == calls


@pytest.mark.parametrize("wanted", ["x", "xxxxxxxx"])
@pytest.mark.parametrize("available", ["get", "list", "neither"])
async def test_status_id_domain_optional_store_methods_preserve_fallback(
    wanted: str, available: str,
) -> None:
    store = _FakeStatusStore([WorkItem(id=wanted, assigned_to="agent-a")])
    boundary = SimpleNamespace(
        get_work_item=store.get_work_item if available == "get" else None,
        list_work_items=store.list_work_items if available == "list" else None,
    )
    tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=boundary))

    result = await tool.invoke({"work_item_id": wanted}, {"agent_id": "agent-a"})

    assert result.error is None
    assert result.output["found"] is (available == "get" or (available == "list" and len(wanted) >= 8))
    if available == "list" and len(wanted) < 8:
        assert store.calls == []


async def test_status_id_domain_unknown_keys_remain_errors() -> None:
    store = _FakeStatusStore([WorkItem(id="x", assigned_to="agent-a")])
    tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=store))

    result = await tool.invoke(
        {"work_item_id": "x", "agent_id": "agent-b"}, {"agent_id": "agent-a"},
    )

    assert result.output is None
    assert result.error == "work_item_status: unknown parameter(s) agent_id. Accepted: work_item_id."
    assert store.calls == []


async def test_status_id_domain_legacy_long_owned_row_is_read_only(governed_store: WorkItemStore) -> None:
    item = await governed_store.create_work_item(
        id="L" * 129, title="Legacy owned ID", assigned_to="agent-a", status="cancelled",
    )
    tool = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=governed_store))

    result = await tool.invoke({"work_item_id": item.id}, {"agent_id": "agent-a"})

    assert result.error is None and result.output["found"] is True
    assert result.output["work_item_id"] == item.id
    assert result.output["status"] == item.status and result.output["is_final"] is True
    assert await governed_store.get_work_item(item.id) == item
    assert await governed_store.list_bookings(work_item_id=item.id) == []


def test_status_id_domain_schema_describes_exact_and_prefix_without_claim_cap() -> None:
    schema = WorkItemStatusTool(runtime=SimpleNamespace(work_item_store=None)).input_schema

    assert schema["required"] == ["work_item_id"]
    assert set(schema["properties"]) == {"work_item_id"}
    declaration = schema["properties"]["work_item_id"]
    assert declaration["type"] == "string"
    assert "minLength" not in declaration and "maxLength" not in declaration
    # The original wire description remains true; exact-ID details are covered
    # by behavior tests and docs, not by changing the immutable AD-1179 offer.
    assert declaration["description"] == (
        "The task id to look up. A prefix of at least 8 characters is accepted, "
        "so an id quoted from the conversation works."
    )
    assert "prefix" in declaration["description"].lower() and "8" in declaration["description"]


@pytest.mark.parametrize("structured", [False, True], ids=["legacy-transcript", "structured-transcript"])
@pytest.mark.parametrize("item_id,claimable", [
    ("x", True), ("x" * 7, True), ("x" * 8, True), ("x" * 128, True),
    (" x ", True), (" ", True), (" " * 8, True), ("\t\r\n", True), ("L" * 129, False),
], ids=["1", "7", "8", "128", "padded", "space", "spaces", "whitespace", "129"])
async def test_id_domain_http_startup_claim_status_and_independent_readback(
    tmp_path: Path, structured: bool, item_id: str, claimable: bool,
) -> None:
    path = str(tmp_path / "workforce.db")
    publication_store = WorkItemStore(db_path=path, tick_interval=1000)
    await publication_store.start()
    try:
        published = await _captain_publish(publication_store, {
            "id": item_id, "title": "Published exact ID", "description": "Ready instructions.",
            "metadata": _PUBLICATION,
        })
        assert published["id"] == item_id
        assert published["assigned_to"] is None and published["status"] == "open"
        assert published["created_by"] == "captain"
    finally:
        await publication_store.stop()

    events: list[tuple[str, dict[str, Any]]] = []
    async with _communication_runtime(tmp_path, events=events) as runtime:
        runtime.config.agentic_loop.structured_tool_messages = structured
        assert type(runtime.tool_registry.get_tool("discover_work_items")) is DiscoverWorkItemsTool
        assert type(runtime.tool_registry.get_tool("claim_work_item")) is ClaimWorkItemTool
        chosen: list[str] = []
        receipts: list[dict[str, Any]] = []
        statuses: list[dict[str, Any]] = []

        def discover(request: LLMRequest) -> LLMResponse:
            offered = {tool["function"]["name"] for tool in request.tools}
            assert {"discover_work_items", "claim_work_item", "work_item_status"} <= offered
            return _call_response("discover_work_items", {}, "discover")

        def select(request: LLMRequest) -> LLMResponse:
            page = ast.literal_eval(_next_tool_text(request, structured=structured, call_id="discover"))
            assert [item["id"] for item in page["items"]] == ([item_id] if claimable else [])
            assert page["next_offset"] is None
            if claimable:
                chosen.append(page["items"][0]["id"])
                wanted = chosen[0]
            else:
                wanted = item_id
            return _call_response("claim_work_item", {"work_item_id": wanted}, "claim")

        def read_receipt(request: LLMRequest) -> LLMResponse:
            text = _next_tool_text(request, structured=structured, call_id="claim")
            if claimable:
                receipt = ast.literal_eval(text)
                assert receipt["owned"] is True
                assert receipt["work_item"]["id"] == receipt["booking"]["work_item_id"] == item_id
                assert receipt["work_item"]["assigned_to"] == receipt["booking"]["resource_id"] == "agent-a"
                assert receipt["work_item"]["status"] == receipt["booking"]["status"] == "scheduled"
                receipts.append(receipt)
            else:
                assert text == "work_pull_input_or_projection_invalid"
            return _call_response("work_item_status", {"work_item_id": item_id}, "status")

        def read_status(request: LLMRequest) -> LLMResponse:
            status = ast.literal_eval(_next_tool_text(request, structured=structured, call_id="status"))
            assert status["found"] is claimable
            assert status["work_item_id"] == item_id
            if claimable:
                assert status["status"] == receipts[0]["work_item"]["status"]
                assert status["title"] == published["title"]
            else:
                assert "title" not in status and "status" not in status
            assert "description" not in status and "metadata" not in status
            statuses.append(status)
            return _final_response()

        client = _ScriptedClient([discover, select, read_receipt, read_status])
        outcome = await WorkItemAgenticExecutor(llm_client=client).run(
            agent_id="agent-a", instructions="Select the work you intend to own.",
            task_text="Discover, claim the exact selected ID, then read its status.",
            runtime=runtime, max_iterations=5,
        )

        assert outcome.stopped_reason == "complete"
        assert len(client.requests) == 4 and len(statuses) == 1
        assert chosen == ([item_id] if claimable else [])
        assert len(receipts) == int(claimable)
        connection = await SQLiteConnectionFactory().connect(path)
        try:
            cursor = await connection.execute(
                "SELECT id, assigned_to, status, updated_at FROM work_items WHERE id = ?", (item_id,),
            )
            row = await cursor.fetchone()
            assert row is not None
            assert tuple(row[:3]) == (
                item_id, "agent-a" if claimable else None, "scheduled" if claimable else "open",
            )
            if claimable:
                assert statuses[0]["status"] == row[2]
            else:
                assert row[3] == published["updated_at"]
            cursor = await connection.execute(
                "SELECT id, work_item_id, resource_id, status FROM bookings WHERE work_item_id = ?",
                (item_id,),
            )
            assert [tuple(row) for row in await cursor.fetchall()] == ([
                (receipts[0]["booking"]["id"], item_id, "agent-a", "scheduled"),
            ] if claimable else [])
            cursor = await connection.execute(
                "SELECT fulfilled FROM resource_requirements WHERE work_item_id = ?", (item_id,),
            )
            assert [row[0] for row in await cursor.fetchall()] == [int(claimable)]
        finally:
            await connection.close()
        assigned = [data for event, data in events if event == "work_item_assigned"]
        claimed = [data for event, data in events if event == "work_item_claimed"]
        assert len(assigned) == len(claimed) == int(claimable)
