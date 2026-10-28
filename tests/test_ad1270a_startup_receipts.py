"""AD-1270a migration step 2 (#1324 slice 5): activation receipts at startup ownership points.

Finalization records a receipt after the boot camp's late-bind and enrolment, after
working-memory cognition starts, and for the Night Orders escalation from what it hands the
runtime. A receipt names the owner and the evidence; it is not a health claim. Production
writes receipts and reads none: the two source censuses at the
end pin it.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import logging
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from probos.agents.http_fetch import HttpFetchAgent
from probos.boot_camp import BootCampCoordinator
from probos.bridge_alerts import BridgeAlertService
from probos.cognitive.working_memory_cognition import WorkingMemoryCognition
from probos.config import (
    AgenticDispatchConfig,
    BootCampConfig,
    DiscoveryLearningConfig,
    MCPConfig,
    ModelRoutingConfig,
    SecurityInfraConfig,
    SystemConfig,
    WorkingMemoryConfig,
    WorkstationsConfig,
)
from probos.consensus.trust import TrustNetwork
from probos.maturity.model import LiveState, TriState
from probos.maturity.receipts import ActivationReceipt, ActivationReceipts
from probos.maturity.registry import load_default_registry
from probos.maturity.report import build_rows
from probos.onboarding import ShipStateSnapshot
from probos.startup import activation_receipts as ar
from probos.startup import finalize
from probos.ward_room_router import WardRoomRouter
from probos.watch_rotation import NightOrdersManager

_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"
_LOGGER = "probos.startup.activation_receipts"
_BC = "runtime.boot_camp: probos.boot_camp.BootCampCoordinator"


class _Episodes:
    async def count_for_agent(self, agent_id: str) -> int:
        return 10


class _Builder:
    """The one method the coordinator calls on an AD-683 builder."""

    def __init__(self) -> None:
        self.builds = 0

    async def build(self) -> ShipStateSnapshot:
        self.builds += 1
        return ShipStateSnapshot(captured_at=1_000_000.0, vessel_name="Enterprise", active_crew_count=1)


class _NewCrewStats:
    """The one episodic-memory read ``finalize._is_new_crew_start`` makes: an empty store."""

    async def get_stats(self) -> dict:
        return {"total": 0}


def _coordinator() -> BootCampCoordinator:
    return BootCampCoordinator(
        config=BootCampConfig(min_time_minutes=0, timeout_minutes=120),
        trust_service=TrustNetwork(),
        episodic_memory=_Episodes(),
        clock=lambda: 1_000_000.0,
    )


def _bare(cls: type) -> Any:
    """An instance of ``cls`` without running its constructor: a receipt reads only its type."""
    return cls.__new__(cls)


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == _LOGGER]


# --- the declarations and the owners ---------------------------------------------------------


@pytest.mark.parametrize(
    ("capability_id", "owner"),
    [
        pytest.param(ar.BOOT_CAMP, ar.BOOT_CAMP_OWNER, id="boot-camp"),
        pytest.param(ar.WORKING_MEMORY_COGNITION, ar.COGNITION_OWNER, id="working-memory-cognition"),
        pytest.param(ar.NIGHT_ORDERS_ESCALATION, ar.BRIDGE_ALERTS_OWNER, id="night-orders-escalation"),
    ],
)
def test_each_receipt_owner_is_its_declarations_owner(capability_id: str, owner: str) -> None:
    declaration = load_default_registry().get(capability_id)

    assert declaration is not None, f"{capability_id} has a receipt point but no declaration"
    assert f"{declaration.owner_module}.{declaration.owner_symbol}" == owner


@pytest.mark.parametrize(
    "owner",
    [
        pytest.param(ar.BOOT_CAMP_OWNER, id="boot-camp"),
        pytest.param(ar.COGNITION_OWNER, id="working-memory-cognition"),
        pytest.param(ar.BRIDGE_ALERTS_OWNER, id="bridge-alerts"),
        pytest.param(ar.NIGHT_ORDERS_OWNER, id="night-orders"),
        pytest.param(ar.WARD_ROOM_ROUTER_OWNER, id="ward-room-router"),
    ],
)
def test_the_declared_owners_are_the_classes_startup_wires(owner: str) -> None:
    module_name, _, symbol = owner.rpartition(".")
    cls = getattr(importlib.import_module(module_name), symbol)

    assert ar.type_path(_bare(cls)) == owner


# --- the boot camp ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("late_bind", "enrolled", "late_bind_text", "enrolment_text"),
    [
        pytest.param(True, True, "bound", "ran", id="bound-ran"),
        pytest.param(None, False, "not attempted", "skipped", id="not-attempted-skipped"),
        pytest.param(False, False, "not bound", "skipped", id="not-bound-skipped"),
    ],
)
def test_boot_camp_activated_when_phase_7_wired_the_coordinator(
    late_bind: bool | None, enrolled: bool, late_bind_text: str, enrolment_text: str
) -> None:
    """A warm boot skips the enrolment and is still an activation (systemd's "active (exited)")."""
    receipt = ar.boot_camp_receipt(
        SimpleNamespace(boot_camp=_bare(BootCampCoordinator)),
        late_bind=late_bind,
        enrolled=enrolled,
        enrolment_error=None,
    )

    assert (receipt.capability_id, receipt.owner) == (ar.BOOT_CAMP, ar.BOOT_CAMP_OWNER)
    assert receipt.activated is True
    assert receipt.evidence == (
        _BC,
        f"ship-state builder late-bind: {late_bind_text}",
        f"cold-start enrolment: {enrolment_text}",
    )


@pytest.mark.parametrize(
    ("coordinator", "seen"),
    [pytest.param(None, "None", id="none"), pytest.param(MagicMock(), "unittest.mock.MagicMock", id="stand-in")],
)
def test_boot_camp_not_activated_without_a_coordinator_or_with_a_stand_in(coordinator: Any, seen: str) -> None:
    receipt = ar.boot_camp_receipt(
        SimpleNamespace(boot_camp=coordinator), late_bind=None, enrolled=False, enrolment_error=None
    )

    assert receipt.activated is False
    assert receipt.evidence[0] == f"runtime.boot_camp: {seen}"


def test_a_failed_enrolment_is_not_an_activation() -> None:
    receipt = ar.boot_camp_receipt(
        SimpleNamespace(boot_camp=_bare(BootCampCoordinator)),
        late_bind=True,
        enrolled=False,
        enrolment_error="RuntimeError",
    )

    assert receipt.activated is False
    assert receipt.evidence == (_BC, "ship-state builder late-bind: bound", "cold-start enrolment: failed (RuntimeError)")


# --- working-memory cognition ----------------------------------------------------------------


async def test_working_memory_cognition_activated_when_startup_started_it() -> None:
    runtime = SimpleNamespace(registry=SimpleNamespace(all=lambda: []), ontology=None)
    config = SystemConfig.model_validate({"working_memory": {"cognition_enabled": True}})

    await finalize._start_working_memory_cognition(runtime=runtime, config=config)
    try:
        receipt = ar.working_memory_cognition_receipt(runtime, start_error=None)
    finally:
        if runtime.working_memory_cognition is not None:
            await runtime.working_memory_cognition.stop()

    assert receipt.activated is True
    assert receipt.evidence == (f"runtime.working_memory_cognition: {ar.COGNITION_OWNER}",)


async def test_working_memory_cognition_off_is_not_activated() -> None:
    runtime = SimpleNamespace(registry=SimpleNamespace(all=lambda: []), ontology=None)

    await finalize._start_working_memory_cognition(runtime=runtime, config=SystemConfig())
    receipt = ar.working_memory_cognition_receipt(runtime, start_error=None)

    assert receipt.activated is False
    assert receipt.evidence == ("runtime.working_memory_cognition: None",)


def test_a_failed_cognition_start_is_not_an_activation() -> None:
    runtime = SimpleNamespace(working_memory_cognition=_bare(WorkingMemoryCognition))

    receipt = ar.working_memory_cognition_receipt(runtime, start_error="RuntimeError")

    assert receipt.activated is False
    assert receipt.evidence == (
        f"runtime.working_memory_cognition: {ar.COGNITION_OWNER}",
        "start failed (RuntimeError)",
    )


# --- the Night Orders escalation -------------------------------------------------------------


@pytest.mark.parametrize(
    ("missing", "replacement"),
    [
        pytest.param(None, None, id="all"),
        pytest.param("night_orders_mgr", None, id="no-manager"),
        pytest.param("bridge_alerts", None, id="no-alerts"),
        pytest.param("ward_room_router", None, id="no-router"),
        pytest.param("bridge_alerts", "stand-in", id="stand-in-alerts"),
    ],
)
def test_night_orders_escalation_activated_only_with_all_three_links(missing: str | None, replacement: str | None) -> None:
    links: dict[str, Any] = {
        "night_orders_mgr": _bare(NightOrdersManager),
        "bridge_alerts": _bare(BridgeAlertService),
        "ward_room_router": _bare(WardRoomRouter),
    }
    if missing is not None:
        links[missing] = MagicMock() if replacement == "stand-in" else None

    receipt = ar.night_orders_escalation_receipt(
        SimpleNamespace(bridge_alerts=links["bridge_alerts"]),
        night_orders_mgr=links["night_orders_mgr"],
        ward_room_router=links["ward_room_router"],
    )

    assert (receipt.capability_id, receipt.owner) == (ar.NIGHT_ORDERS_ESCALATION, ar.BRIDGE_ALERTS_OWNER)
    assert receipt.activated is (missing is None)
    assert receipt.evidence == (
        f"night orders manager: {ar.type_path(links['night_orders_mgr'])}",
        f"runtime.bridge_alerts: {ar.type_path(links['bridge_alerts'])}",
        f"ward room router: {ar.type_path(links['ward_room_router'])}",
    )


# --- log-and-degrade -------------------------------------------------------------------------


def test_a_receipt_that_cannot_be_built_costs_only_that_receipt(caplog: pytest.LogCaptureFixture) -> None:
    receipts = ActivationReceipts()

    def _broken() -> ActivationReceipt:
        raise RuntimeError("owner unreadable")

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        ar.record_activation(receipts, _broken)
        ar.record_activation(
            receipts, lambda: ActivationReceipt(capability_id="a.next", activated=True, owner="probos.x.Y")
        )

    assert [receipt.capability_id for receipt in receipts.receipts()] == ["a.next"]
    assert _messages(caplog) == ["AD-1270a: an activation receipt could not be recorded; startup continues"]


def test_begin_publishes_a_fresh_receipt_set_on_the_runtime() -> None:
    runtime = SimpleNamespace()

    first = ar.begin_activation_receipts(runtime)
    assert isinstance(first, ActivationReceipts) and runtime.activation_receipts is first
    second = ar.begin_activation_receipts(runtime)

    assert runtime.activation_receipts is second and second is not first


class _Sealed:
    __slots__ = ()


def test_a_runtime_that_refuses_the_attribute_still_gets_receipts(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        receipts = ar.begin_activation_receipts(_Sealed())

    assert isinstance(receipts, ActivationReceipts)
    assert _messages(caplog) == [
        "AD-1270a: activation receipts could not be published on the runtime; they are still logged"
    ]


# --- across the seam -------------------------------------------------------------------------


async def test_the_boot_camp_receipt_from_the_real_helpers_reaches_the_report_row() -> None:
    """Finalization's own helpers, in finalization's order, into a receipt, into the report."""
    builder = _Builder()
    member = SimpleNamespace(id="crew-1", agent_type="security_officer", callsign="Tester", department="security")
    runtime = SimpleNamespace(
        boot_camp=_coordinator(),
        ship_state_snapshot=builder,
        ontology=None,
        _lifecycle_state="first_boot",
        episodic_memory=_NewCrewStats(),
        registry=SimpleNamespace(all=lambda: [member]),
    )
    receipts = ar.begin_activation_receipts(runtime)
    late_bind = finalize._late_bind_boot_camp_snapshot(runtime=runtime) is True
    enrolled = await finalize._activate_boot_camp_on_cold_start(runtime=runtime) is True
    ar.record_activation(
        receipts,
        lambda: ar.boot_camp_receipt(runtime, late_bind=late_bind, enrolled=enrolled, enrolment_error=None),
    )

    rows = {
        row.declaration.id: row
        for row in await build_rows(load_default_registry(), config=SystemConfig(), receipts=runtime.activation_receipts)
    }

    assert (late_bind, enrolled, builder.builds) == (True, True, 1)
    assert runtime.activation_receipts.receipt_for(ar.BOOT_CAMP).evidence == (
        _BC,
        "ship-state builder late-bind: bound",
        "cold-start enrolment: ran",
    )
    assert rows[ar.BOOT_CAMP].activated is TriState.TRUE
    assert rows[ar.BOOT_CAMP].live is LiveState.UNKNOWN
    assert {key for key, row in rows.items() if row.activated is not TriState.UNKNOWN} == {ar.BOOT_CAMP}


def _finalize_startup() -> ast.AsyncFunctionDef:
    tree = ast.parse((_SRC / "startup" / "finalize.py").read_bytes())
    return next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "finalize_startup")


def _call_lines(body: ast.AST, name: str) -> list[int]:
    return sorted(
        node.lineno
        for node in ast.walk(body)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    )


def test_finalization_records_each_receipt_after_its_ownership_point() -> None:
    """Source scan of production source (a shared contract), parsed from bytes."""
    body = _finalize_startup()
    wirers = sorted(
        node.lineno
        for node in ast.walk(body)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.startswith("_wire_")
    )
    begin = _call_lines(body, "begin_activation_receipts")
    records = _call_lines(body, "record_activation")
    boot = _call_lines(body, "boot_camp_receipt")
    cognition = _call_lines(body, "working_memory_cognition_receipt")
    night = _call_lines(body, "night_orders_escalation_receipt")
    binds = _call_lines(body, "_late_bind_boot_camp_snapshot")
    enrolments = _call_lines(body, "_activate_boot_camp_on_cold_start")
    starts = _call_lines(body, "_start_working_memory_cognition")
    routers = [
        node.lineno
        for node in ast.walk(body)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "ward_room_router" for target in node.targets)
    ]
    finals = [
        node.lineno
        for node in ast.walk(body)
        if isinstance(node, ast.Return)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "FinalizationResult"
    ]

    assert (len(begin), len(records), len(boot), len(cognition), len(night), len(finals)) == (1, 3, 1, 1, 1, 1)
    assert begin[0] < wirers[0]
    assert binds[0] < enrolments[0] < boot[0]  # slice 4b's order, then its receipt
    assert starts[0] < cognition[0]
    assert max(routers) < night[0] < finals[0]


def _finalize_rig() -> tuple[MagicMock, MagicMock]:
    """test_new_crew_auto_welcome's rig (a MagicMock runtime that runs the whole finalize_startup),
    with a real boot-camp coordinator and working-memory cognition off."""
    agent1 = SimpleNamespace(
        callsign="Kira", agent_type="data_analyst", _newly_commissioned=True, id="sci_data_analyst_0_abc12345"
    )
    agent2 = SimpleNamespace(
        callsign="Lynx", agent_type="systems_analyst", _newly_commissioned=True, id="sci_systems_analyst_0_def67890"
    )
    ward_room = AsyncMock()
    ward_room.get_channel_by_name = AsyncMock(return_value=SimpleNamespace(id="ch-1", name="All Hands"))
    ward_room.create_thread = AsyncMock()
    registry = MagicMock()
    registry.all.return_value = [agent1, agent2]
    registry.count = 2

    runtime = MagicMock()
    runtime.ward_room = ward_room
    runtime._cold_start = False
    runtime.registry = registry
    runtime._started = False
    runtime._lifecycle_state = "restart"
    runtime._stasis_duration = 0
    runtime._previous_session = None
    runtime.event_log = AsyncMock()
    runtime.pools = {}
    runtime.red_team_agents = []
    runtime.ontology = None
    runtime.trust_network = MagicMock()
    runtime.trust_network.set_department_lookup = MagicMock()
    runtime.trust_network.set_event_callback = MagicMock()
    runtime.dream_scheduler = None
    runtime.self_mod_pipeline = None
    runtime.callsign_registry = None
    runtime.episodic_memory = None
    runtime.intent_bus = None
    runtime._knowledge_store = None
    runtime.initiative = None
    runtime._emergent_detector = None
    runtime.hebbian_router = None
    runtime.bridge_alerts = None
    runtime.behavioral_monitor = None
    runtime.acm = None
    runtime.onboarding = MagicMock()
    runtime.nats_bus = None
    runtime.boot_camp = _coordinator()  # AD-1270a step 2: a real owner, so the receipt can read activated
    runtime.working_memory_cognition = None

    config = MagicMock()
    config.proactive_cognitive.enabled = False
    config.agentic_dispatch = AgenticDispatchConfig(orchestrator_enabled=False)
    config.discovery_learning = DiscoveryLearningConfig(enabled=False)
    config.mcp = MCPConfig(enabled=False)
    config.model_routing = ModelRoutingConfig(enabled=False)
    config.workstations = WorkstationsConfig(enabled=False)
    config.working_memory = WorkingMemoryConfig()  # cognition off: the builder returns None
    # S5-F1: a real security config. A MagicMock one reads egress_active_enforcement as true, so
    # finalization installs an egress policy on the HttpFetchAgent class that outlives the test.
    config.security_infra = SecurityInfraConfig()
    return runtime, config


async def _enrol(**_: Any) -> bool:
    return True


async def _raise(**_: Any) -> bool:
    raise RuntimeError("wiring failed")


def _record_sqlite_connections(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """A1: every aiosqlite connection opened while the rig runs, so the test can close it.

    Production opens each one through a call-time ``aiosqlite.connect(...)`` lookup, so the
    patched name sees them all. Their worker threads are not daemons: one left open keeps a
    ``-n 0`` interpreter alive after the session ends.
    """
    opened: list[Any] = []
    connect = aiosqlite.connect

    def _connect(*args: Any, **kwargs: Any) -> Any:
        connection = connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(aiosqlite, "connect", _connect)
    return opened


async def _close_what_finalization_opened(runtime: Any, opened: list[Any]) -> None:
    """A1: close the rig's sqlite connections, then its attachment store's I/O threads.

    ``aiosqlite.Connection.close`` returns at once for a connection never opened, and stops
    the worker thread in its ``finally``, so a close error still ends the thread. Errors are
    collected, not raised: this is teardown. A connection opened while closing is closed in
    the next pass.
    """
    from probos.routers.chat import close_attachment_store

    while opened:
        batch = opened[:]
        del opened[:]
        await asyncio.gather(*(connection.close() for connection in batch), return_exceptions=True)
    close_attachment_store(runtime)


@pytest.mark.parametrize(
    ("case", "boot_activated", "enrolment"),
    [
        pytest.param("skipped", True, "skipped", id="skipped"),
        pytest.param("enrolled", True, "ran", id="enrolled"),
        pytest.param("failed", False, "failed (RuntimeError)", id="failed"),
    ],
)
async def test_a_finalization_publishes_its_receipts_on_the_runtime(
    case: str, boot_activated: bool, enrolment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real finalize_startup, end to end: receipts on the runtime, in order, into the report.
    A failing ownership point costs its receipt's activation, never the finalization."""
    runtime, config = _finalize_rig()
    opened = _record_sqlite_connections(monkeypatch)
    if case == "enrolled":
        monkeypatch.setattr(finalize, "_activate_boot_camp_on_cold_start", _enrol)
    if case == "failed":
        monkeypatch.setattr(finalize, "_activate_boot_camp_on_cold_start", _raise)
        monkeypatch.setattr(finalize, "_start_working_memory_cognition", _raise)

    egress_policy_before = HttpFetchAgent._egress_policy
    try:
        await finalize.finalize_startup(runtime=runtime, config=config)
    finally:
        await _close_what_finalization_opened(runtime, opened)

    # S5-F1: finalization must leave the class-level egress policy as it found it.
    assert HttpFetchAgent._egress_policy is egress_policy_before, "finalize_startup installed an egress policy"
    receipts = runtime.activation_receipts
    assert isinstance(receipts, ActivationReceipts)
    by_id = {receipt.capability_id: receipt for receipt in receipts.receipts()}
    assert list(by_id) == [ar.BOOT_CAMP, ar.WORKING_MEMORY_COGNITION, ar.NIGHT_ORDERS_ESCALATION]
    assert by_id[ar.BOOT_CAMP].activated is boot_activated
    assert by_id[ar.BOOT_CAMP].evidence == (_BC, "ship-state builder late-bind: bound", f"cold-start enrolment: {enrolment}")
    cognition = ("runtime.working_memory_cognition: None",) + (
        ("start failed (RuntimeError)",) if case == "failed" else ()
    )
    assert (by_id[ar.WORKING_MEMORY_COGNITION].activated, by_id[ar.WORKING_MEMORY_COGNITION].evidence) == (False, cognition)
    assert by_id[ar.NIGHT_ORDERS_ESCALATION].activated is False
    assert by_id[ar.NIGHT_ORDERS_ESCALATION].evidence == (
        "night orders manager: None",
        "runtime.bridge_alerts: None",
        f"ward room router: {ar.WARD_ROOM_ROUTER_OWNER}",
    )
    rows = {
        row.declaration.id: row
        for row in await build_rows(load_default_registry(), config=SystemConfig(), receipts=receipts)
    }
    assert rows[ar.BOOT_CAMP].activated is (TriState.TRUE if boot_activated else TriState.FALSE)
    assert LiveState.LIVE not in {row.live for row in rows.values()}


async def test_a_real_boot_publishes_its_receipts(tmp_path: Path) -> None:
    """The production path, as BF-927's boot test runs it: a real runtime and a default config,
    where no Ward Room exists, cognition is off and the proactive loop is off."""
    from probos.runtime import ProbOSRuntime

    rt = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)
    try:
        await rt.start()
        receipts = rt.activation_receipts
    finally:
        await rt.stop()

    assert isinstance(receipts, ActivationReceipts)
    assert [receipt.capability_id for receipt in receipts.receipts()] == [
        ar.BOOT_CAMP,
        ar.WORKING_MEMORY_COGNITION,
        ar.NIGHT_ORDERS_ESCALATION,
    ]
    assert {receipt.capability_id: receipt.evidence[0] for receipt in receipts.receipts()} == {
        ar.BOOT_CAMP: "runtime.boot_camp: None",
        ar.WORKING_MEMORY_COGNITION: "runtime.working_memory_cognition: None",
        ar.NIGHT_ORDERS_ESCALATION: "night orders manager: None",
    }
    assert [receipt.activated for receipt in receipts.receipts()] == [False, False, False]


# --- the two source censuses -----------------------------------------------------------------


def _production_trees() -> Iterator[tuple[str, ast.AST]]:
    for path in sorted(_SRC.rglob("*.py")):
        relative = path.relative_to(_SRC).as_posix()
        if relative.startswith("maturity/"):
            continue
        yield relative, ast.parse(path.read_bytes())


def _maturity_imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(
                alias.name for alias in node.names
                if alias.name == "probos.maturity" or alias.name.startswith("probos.maturity.")
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "probos.maturity" or node.module.startswith("probos.maturity."):
                names.add(node.module)
            elif node.module == "probos" and any(alias.name == "maturity" for alias in node.names):
                names.add("probos.maturity")
    return names


def test_production_imports_of_the_maturity_package_are_the_known_set() -> None:
    """Declarations import the model; one startup module imports the receipts. Nothing else."""
    found = {relative: names for relative, tree in _production_trees() if (names := _maturity_imports(tree))}

    assert found == {
        "agents/maturity_declarations.py": {"probos.maturity.model"},
        "cognitive/maturity_declarations.py": {"probos.maturity.model"},
        "infrastructure/maturity_declarations.py": {"probos.maturity.model"},
        "maturity_declarations.py": {"probos.maturity.model"},
        "startup/activation_receipts.py": {"probos.maturity.receipts"},
        "tools/maturity_declarations.py": {"probos.maturity.model"},
    }


_READS = frozenset({"activation_for", "exercise_for", "health_for", "receipt_for", "receipts"})


def test_production_writes_the_receipts_and_reads_none() -> None:
    """The ledger is observation-only: no routing, permission, trust or startup decision reads it."""
    published: list[tuple[str, str]] = []
    reads: list[tuple[str, str]] = []
    for relative, tree in _production_trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "activation_receipts":
                published.append((relative, type(node.ctx).__name__))
            elif isinstance(node, ast.Attribute) and node.attr in _READS:
                reads.append((relative, node.attr))

    assert published == [("startup/activation_receipts.py", "Store")]
    assert reads == []
