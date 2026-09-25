"""AD-1195 (#1132) M4: every DURABLE member has a success-path producer events.db can answer for.

PROD-1 pins each routed member's producer: an emit-like call whose first argument is
``EventType.<NAME>``, found by AST in the member's producer files. PROD-2 drives a real
``ToolRegistry`` denial, the one producer that emitted its member's NAME string instead.
ACCEPT-1 crosses the whole chain for every routed member (the real ``_emit_event`` ->
``DurableEventRouter`` -> a real ``EventLog`` -> ``durable_answer``) and for the owner
members whose rows AD-1224 and AD-1265 write themselves.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

import probos
from probos.event_persistence import DECLARATIONS, OWNER_RECORDS, ROUTED_CATEGORY, Persistence
from probos.events import EventType
from probos.infrastructure.backup import BackupResult
from probos.runtime import ProbOSRuntime
from probos.substrate.durable_events import ROUTED_VALUES, durable_answer
from probos.substrate.event_log import EventLog
from probos.tools.executor import ToolExecutor, make_start_hook, wire_tool_invocation_hooks
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolPermissionDenied, ToolRegistry
from tests.test_ad1195_durable_event_seam import _bound_router, _EmitHost

_SRC = Path(probos.__file__).resolve().parent
_ROUTED = sorted(m.name for m in EventType if m.value in ROUTED_VALUES)

# Where each routed member's success-path producer lives (AD-1195 DURABLE table).
_PRODUCER_FILES: dict[str, tuple[str, ...]] = {
    "CAPABILITY_REQUEST_FILED": ("capability_request.py",),
    "CAPABILITY_REQUEST_DECIDED": ("capability_request.py",),
    "CAPABILITY_REQUEST_FULFILLED": ("capability_request.py",),
    "TOOL_PERMISSION_DENIED": ("tools/registry.py",),
    "TOOL_INTERVENTION_REQUIRED": ("tools/browser/tool.py",),
    "SELF_MOD_STARTED": ("routers/chat.py",),
    "SELF_MOD_IMPORT_APPROVED": ("routers/chat.py",),
    "SELF_MOD_SUCCESS": ("routers/chat.py",),
    "SELF_MOD_FAILURE": ("routers/chat.py",),
    "DESIGN_GENERATED": ("routers/design.py",),
    "SHIP_NAMED": ("startup/communication.py",),
    "THREAT_DETECTED": ("security/threat_detector.py",),
    "TRUST_INTEGRITY_VIOLATION": ("security/trust_integrity.py",),
    "SECURITY_INPUT_REJECTED": ("security/input_validator.py",),
    "EGRESS_BLOCKED": ("security/egress.py",),
    "BOUNDARY_VIOLATION_DETECTED": ("security/autonomy_boundaries.py",),
    "CLASSIFICATION_DISCLOSURE_BLOCKED": ("security/classification.py",),
    "CREDENTIAL_READ": ("tools/browser/credentials.py",),
    "CREDENTIAL_READ_DENIED": ("tools/browser/credentials.py",),
    "SECRET_ROTATED": ("credential_store.py",),
    "CREDENTIAL_TIER_DENIED": ("credential_store.py",),
    "MCP_BRIDGE_INVOKE": ("integrations/mcp_bridge/client.py", "federation/mcp_server.py"),
    "MCP_BRIDGE_FAILED": (
        "integrations/mcp_bridge/client.py",
        "integrations/mcp_bridge/bridge.py",
        "federation/mcp_server.py",
    ),
    "WORK_ITEM_STATUS_CHANGED": ("workforce.py",),
    "WORK_ITEM_QUARANTINED": ("agents/quartermaster.py", "cognitive/ground_truth.py"),
    "CREW_TASK_STARTED": ("cognitive/crew_executor.py",),
    "CREW_TASK_COMPLETED": ("cognitive/crew_synth.py",),
    "CONFIG_CHANGED": ("runtime_config_service.py",),
}

# Owner members ACCEPT-1 drives through the writer that owns their row.
_OWNER_TOOL_MEMBERS = ("TOOL_STARTED", "TOOL_INVOKED", "TOOL_RECORD_BUDGET_EXHAUSTED")
_OWNER_BACKUP_MEMBERS = ("BACKUP_COMPLETE", "BACKUP_FAILED")
# Written inside onboarding and consensus: DRIFT-5 pins their pairs; test_consensus_integration and
# test_ad490 drive the quorum_evaluated and agent_wired writers, agent_self_named has only DRIFT-5.
_OWNER_COVERED_ELSEWHERE = ("CONSENSUS", "AGENT_WIRED", "AGENT_SELF_NAMED")


class _BusHost(_EmitHost):
    """The BF-708 host plus the public ``emit_event`` that finalize wires into the tool hooks."""

    emit_event = ProbOSRuntime.emit_event


class _BackupHost:
    """BF-708 shape: the unmodified AD-1265 writer on a minimal object holding a real EventLog."""

    _log_backup_tick = ProbOSRuntime._log_backup_tick

    def __init__(self, event_log: EventLog) -> None:
        self.event_log = event_log


class _ProbeTool:
    """A registered tool that always succeeds."""

    tool_id = "probe_tool"
    name = "Probe Tool"
    tool_type = ToolType.DETERMINISTIC_FUNCTION
    description = "AD-1195 acceptance probe"
    input_schema: dict[str, Any] = {"type": "object"}
    output_schema: dict[str, Any] = {"type": "object"}

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        return ToolResult(output={"ok": True})


@pytest.fixture
async def event_log(tmp_path: Path):
    log = EventLog(tmp_path / "events.db")
    await log.start()
    yield log
    await log.stop()


def _denying_registry() -> ToolRegistry:
    """A real registry whose one tool an ensign may read but not write."""
    registry = ToolRegistry()
    registry.register(_ProbeTool(), default_permissions={"ensign": "read"})
    return registry


def _callee(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _passes_member(node: ast.expr, name: str) -> bool:
    """True for ``EventType.<name>`` or ``EventType.<name>.value``."""
    if isinstance(node, ast.Attribute) and node.attr == "value":
        node = node.value
    return (
        isinstance(node, ast.Attribute)
        and node.attr == name
        and isinstance(node.value, ast.Name)
        and node.value.id == "EventType"
    )


def _producer_lines(rel: str, name: str) -> list[int]:
    path = _SRC / rel
    tree = ast.parse(path.read_bytes().decode("utf-8"), filename=str(path))
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and node.args
        and _passes_member(node.args[0], name)
        and "emit" in _callee(node).lower()
    )


# ── premises ─────────────────────────────────────────────────────────────────


def test_producer_table_names_exactly_the_routed_members() -> None:
    """PROD-1 and ACCEPT-1 parametrize over these; a drift must not silently shrink them."""
    assert len(_ROUTED) == 28
    assert set(_PRODUCER_FILES) == set(_ROUTED)
    missing = [rel for files in _PRODUCER_FILES.values() for rel in files if not (_SRC / rel).is_file()]
    assert missing == []


def test_acceptance_covers_every_durable_member() -> None:
    """Every DURABLE member is answered for below, or its owner writer is covered elsewhere."""
    durable = {name for name, cls in DECLARATIONS.items() if cls is Persistence.DURABLE}
    owners = {*_OWNER_TOOL_MEMBERS, *_OWNER_BACKUP_MEMBERS, *_OWNER_COVERED_ELSEWHERE}
    assert len(durable) == 36
    assert owners == set(OWNER_RECORDS)
    assert set(_ROUTED) | owners == durable


# ── PROD-1 ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", _ROUTED)
def test_routed_member_has_an_emit_call_passing_its_enum_member(name: str) -> None:
    """PROD-1: each producer file passes ``EventType.<NAME>``, whose value is what the router admits."""
    missing = [rel for rel in _PRODUCER_FILES[name] if not _producer_lines(rel, name)]
    assert missing == [], (
        f"no emit-like call passing EventType.{name} in {missing}; the router admits "
        f"{EventType[name].value!r}, so a producer passing anything else is never recorded"
    )


# ── PROD-2 ───────────────────────────────────────────────────────────────────


async def test_real_registry_denial_emits_the_enum_member() -> None:
    """PROD-2: a denial delivers ``EventType.TOOL_PERMISSION_DENIED``, whose value is the wire string."""
    registry = _denying_registry()
    events: list[tuple[Any, dict[str, Any]]] = []
    registry.set_event_callback(lambda event, payload: events.append((event, payload)))

    with pytest.raises(ToolPermissionDenied):
        await registry.check_and_invoke("agent-7", "probe_tool", {}, required=ToolPermission.WRITE)

    assert len(events) == 1
    event, payload = events[0]
    assert event is EventType.TOOL_PERMISSION_DENIED
    assert event == "tool_permission_denied"
    assert payload == {
        "agent_id": "agent-7", "tool_id": "probe_tool", "required": "write", "held": "read",
    }


async def test_real_registry_denial_is_recorded_through_the_real_emit_seam(
    event_log: EventLog,
) -> None:
    """PROD-2 crossed: a real denial -> the real _emit_event -> router -> events.db -> answer."""
    router = _bound_router(event_log)
    host = _EmitHost(router)
    delivered: list[dict[str, Any]] = []
    host.add_event_listener(delivered.append)
    registry = _denying_registry()
    registry.set_event_callback(host._emit_event)  # boot wires runtime._emit_event the same way
    member = EventType.TOOL_PERMISSION_DENIED
    assert (await durable_answer(event_log, member, router=router)).status == "not_recorded"

    with pytest.raises(ToolPermissionDenied):
        await registry.check_and_invoke("agent-7", "probe_tool", {}, required=ToolPermission.WRITE)
    stats = await router.drain(wait_budget_s=5.0)

    answer = await durable_answer(event_log, member, router=router)
    assert answer.status == "recorded"
    assert answer.record_key == (ROUTED_CATEGORY, "tool_permission_denied")
    assert answer.row is not None
    # A2 R5: routed rows leave the indexed agent_id column NULL; the id stays in the payload below.
    assert answer.row["agent_id"] is None
    assert answer.row["data"]["payload"] == {
        "agent_id": "agent-7", "tool_id": "probe_tool", "required": "write", "held": "read",
    }
    assert [event["type"] for event in delivered] == ["tool_permission_denied"]
    assert (stats.offered, stats.written, dict(stats.dropped)) == (1, 1, {})


# ── ACCEPT-1 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", _ROUTED)
async def test_routed_member_emitted_through_the_real_seam_is_recorded(
    name: str, event_log: EventLog,
) -> None:
    """ACCEPT-1: real _emit_event -> router -> events.db; the answer names this member and no other."""
    member = EventType[name]
    control = EventType[_ROUTED[(_ROUTED.index(name) + 1) % len(_ROUTED)]]
    router = _bound_router(event_log)
    host = _EmitHost(router)
    assert (await durable_answer(event_log, member, router=router)).status == "not_recorded"

    host._emit_event(member, {"agent_id": "agent-accept-1", "probe": name})
    stats = await router.drain(wait_budget_s=5.0)

    answer = await durable_answer(event_log, member, router=router)
    assert answer.status == "recorded"
    assert answer.record_key == (ROUTED_CATEGORY, member.value)
    assert answer.row is not None
    assert (answer.row["category"], answer.row["event"]) == (ROUTED_CATEGORY, member.value)
    # A2 R5: routed rows leave the indexed agent_id column NULL; the id stays in the payload below.
    assert answer.row["agent_id"] is None
    assert answer.row["data"]["payload"] == {"agent_id": "agent-accept-1", "probe": name}
    assert (await durable_answer(event_log, control, router=router)).status == "not_recorded"
    assert (stats.offered, stats.written, stats.pending, dict(stats.dropped)) == (1, 1, 0, {})


@pytest.mark.parametrize("name", _OWNER_TOOL_MEMBERS)
async def test_owner_tool_member_is_recorded_by_the_production_tool_hooks(
    name: str, event_log: EventLog,
) -> None:
    """ACCEPT-1: the AD-1224 hooks write the owner row, and the router passes over the bus copy."""
    member = EventType[name]
    router = _bound_router(event_log)
    host = _BusHost(router)
    delivered: list[str] = []
    host.add_event_listener(lambda event: delivered.append(event["type"]))
    registry = ToolRegistry()
    registry.register(_ProbeTool())
    executor = ToolExecutor(registry=registry)
    if name == "TOOL_RECORD_BUDGET_EXHAUSTED":
        # Production caps a run at 500 pairs; a zero cap reaches the same writer on the first call.
        executor.add_pre_hook(
            make_start_hook(emit_fn=host.emit_event, event_log=event_log, max_records_per_run=0)
        )
    else:
        # finalize wires the shared executor exactly so.
        assert wire_tool_invocation_hooks(executor, emit_fn=host.emit_event, event_log=event_log)
    assert (await durable_answer(event_log, member, router=router)).status == "not_recorded"

    result = await executor.invoke("agent-accept-1", "probe_tool", {})
    stats = await router.drain(wait_budget_s=5.0)

    assert result.error is None and result.output == {"ok": True}
    answer = await durable_answer(event_log, member, router=router)
    assert answer.status == "recorded"
    assert answer.record_key == OWNER_RECORDS[name]
    assert answer.row is not None
    assert (answer.row["category"], answer.row["event"]) == OWNER_RECORDS[name]
    assert answer.row["detail"] == "probe_tool"
    assert answer.row["agent_id"] == "agent-accept-1"
    assert member.value in delivered
    assert await event_log.query_structured(category=ROUTED_CATEGORY, limit=10) == []
    assert stats.offered == 0


@pytest.mark.parametrize(
    ("name", "succeeded"), [("BACKUP_COMPLETE", True), ("BACKUP_FAILED", False)]
)
async def test_backup_member_is_recorded_by_the_runtime_backup_tick(
    name: str, succeeded: bool, event_log: EventLog, tmp_path: Path,
) -> None:
    """ACCEPT-1: the real ProbOSRuntime._log_backup_tick writes the AD-1265 owner row."""
    member = EventType[name]
    sibling = EventType.BACKUP_FAILED if succeeded else EventType.BACKUP_COMPLETE
    host = _BackupHost(event_log)
    snapshot_dir = str(tmp_path / "snapshot")
    assert (await durable_answer(event_log, member)).status == "not_recorded"

    await host._log_backup_tick(BackupResult(
        succeeded=succeeded, snapshot_dir=snapshot_dir, error="" if succeeded else "disk full",
    ))

    answer = await durable_answer(event_log, member)
    assert answer.status == "recorded"
    assert answer.record_key == OWNER_RECORDS[name]
    assert answer.row is not None
    assert (answer.row["category"], answer.row["event"]) == OWNER_RECORDS[name]
    assert answer.row["detail"] == snapshot_dir
    assert (await durable_answer(event_log, sibling)).status == "not_recorded"
