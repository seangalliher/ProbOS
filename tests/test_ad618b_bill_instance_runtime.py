"""AD-618b: Bill Instance + Runtime tests."""

from __future__ import annotations

from dataclasses import field
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.config import BillConfig
from probos.events import EventType
from probos.sop.instance import (
    BillInstance,
    InstanceStatus,
    RoleAssignment,
    StepState,
    StepStatus,
)
from probos.sop.runtime import BillActivationError, BillRuntime
from probos.sop.schema import BillDefinition, BillRole, BillStep


# ── Helpers ──────────────────────────────────────────────────────────


def _make_bill(
    *,
    bill: str = "general-quarters",
    title: str = "General Quarters",
    version: int = 1,
    roles: dict[str, BillRole] | None = None,
    steps: list[BillStep] | None = None,
) -> BillDefinition:
    """Create a minimal BillDefinition for testing."""
    if roles is None:
        roles = {
            "lead": BillRole(id="lead", department="engineering"),
            "support": BillRole(id="support", department="science"),
        }
    if steps is None:
        steps = [
            BillStep(id="step-1", name="Assess situation", role="lead", action="cognitive_skill"),
            BillStep(id="step-2", name="Report findings", role="support", action="post_to_channel"),
        ]
    return BillDefinition(
        bill=bill,
        title=title,
        version=version,
        roles=roles,
        steps=steps,
    )


def _make_billet_holder(
    *,
    billet_id: str = "eng-1",
    title: str = "Engineer",
    department: str = "engineering",
    agent_id: str = "agent-forge",
    agent_type: str = "engineering_officer",
    callsign: str = "Forge",
):
    """Create a mock BilletHolder."""
    bh = MagicMock()
    bh.billet_id = billet_id
    bh.title = title
    bh.department = department
    bh.holder_agent_id = agent_id
    bh.holder_agent_type = agent_type
    bh.holder_callsign = callsign
    return bh


def _make_registry(holders: list | None = None):
    """Create a mock BilletRegistry with roster and qualification checks."""
    registry = MagicMock()
    holders = holders or [
        _make_billet_holder(),
        _make_billet_holder(
            billet_id="sci-1", title="Scientist", department="science",
            agent_id="agent-atlas", agent_type="science_officer", callsign="Atlas",
        ),
    ]
    registry.get_roster.return_value = holders
    registry.get_department_roster.side_effect = lambda dept: [
        h for h in holders if h.department == dept
    ]
    registry.check_qualifications = AsyncMock(return_value=(True, []))
    return registry


def _make_runtime(
    *,
    config: BillConfig | None = None,
    registry=None,
    events: list | None = None,
) -> tuple[BillRuntime, list]:
    """Create a BillRuntime with event capture."""
    captured = events if events is not None else []

    def capture(event_type, data):
        captured.append((event_type, data))

    rt = BillRuntime(
        config=config,
        billet_registry=registry,
        emit_event_fn=capture,
    )
    return rt, captured


# ── Instance Tests ───────────────────────────────────────────────────


def test_bill_instance_defaults():
    """BillInstance defaults — id generated, status PENDING."""
    inst = BillInstance()
    assert len(inst.id) == 12
    assert inst.status == InstanceStatus.PENDING
    assert inst.role_assignments == {}
    assert inst.step_states == {}
    assert inst.activation_data == {}


def test_bill_instance_to_dict():
    """to_dict() serializes all fields including nested structures."""
    inst = BillInstance(
        id="test-123",
        bill_id="gq",
        bill_title="General Quarters",
        status=InstanceStatus.ACTIVE,
    )
    inst.role_assignments["lead"] = RoleAssignment(
        role_id="lead", agent_id="a1", agent_type="eng",
        callsign="Forge", department="engineering",
    )
    inst.step_states["s1"] = StepState(
        step_id="s1", status=StepStatus.COMPLETED,
        assigned_agent_id="a1", assigned_agent_callsign="Forge",
        started_at=1000.0, completed_at=1005.0,
    )
    d = inst.to_dict()
    assert d["id"] == "test-123"
    assert d["status"] == "active"
    assert d["role_assignments"]["lead"]["agent_id"] == "a1"
    assert d["step_states"]["s1"]["status"] == "completed"


def test_bill_instance_is_terminal():
    """is_terminal True for COMPLETED/FAILED/CANCELLED, False for PENDING/ACTIVE."""
    for status in (InstanceStatus.COMPLETED, InstanceStatus.FAILED, InstanceStatus.CANCELLED):
        inst = BillInstance(status=status)
        assert inst.is_terminal is True

    for status in (InstanceStatus.PENDING, InstanceStatus.ACTIVE):
        inst = BillInstance(status=status)
        assert inst.is_terminal is False


def test_bill_instance_progress():
    """progress — 0.0 empty, 0.5 half done, 1.0 all done."""
    inst = BillInstance()
    assert inst.progress == 0.0

    inst.step_states["a"] = StepState(step_id="a", status=StepStatus.COMPLETED)
    inst.step_states["b"] = StepState(step_id="b", status=StepStatus.PENDING)
    assert inst.progress == 0.5

    inst.step_states["b"].status = StepStatus.SKIPPED
    assert inst.progress == 1.0


def test_step_state_lifecycle():
    """StepState lifecycle PENDING → ACTIVE → COMPLETED."""
    ss = StepState(step_id="s1")
    assert ss.status == StepStatus.PENDING
    assert ss.started_at is None

    ss.status = StepStatus.ACTIVE
    ss.started_at = 1000.0
    assert ss.status == StepStatus.ACTIVE

    ss.status = StepStatus.COMPLETED
    ss.completed_at = 1005.0
    assert ss.completed_at == 1005.0


# ── Runtime Activation Tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_creates_instance():
    """activate() creates instance with correct bill metadata."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()

    inst = await rt.activate(bill, activated_by="captain")

    assert inst.bill_id == "general-quarters"
    assert inst.bill_title == "General Quarters"
    assert inst.bill_version == 1
    assert inst.status == InstanceStatus.ACTIVE
    assert inst.activated_by == "captain"


@pytest.mark.asyncio
async def test_activate_initializes_step_states():
    """activate() initializes one StepState per BillStep, all PENDING."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()

    inst = await rt.activate(bill)

    assert len(inst.step_states) == 2
    assert "step-1" in inst.step_states
    assert "step-2" in inst.step_states
    assert all(ss.status == StepStatus.PENDING for ss in inst.step_states.values())


@pytest.mark.asyncio
async def test_activate_concurrency_limit():
    """activate() raises BillActivationError when max_concurrent_instances exceeded."""
    config = BillConfig(max_concurrent_instances=1)
    registry = _make_registry()
    rt, events = _make_runtime(config=config, registry=registry)
    bill = _make_bill()

    await rt.activate(bill)

    with pytest.raises(BillActivationError, match="Max concurrent"):
        await rt.activate(bill)


@pytest.mark.asyncio
async def test_activate_emits_bill_activated():
    """activate() emits BILL_ACTIVATED event."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()

    inst = await rt.activate(bill)

    activated_events = [e for e in events if e[0] == EventType.BILL_ACTIVATED]
    assert len(activated_events) == 1
    data = activated_events[0][1]
    assert data["instance_id"] == inst.id
    assert data["bill_id"] == "general-quarters"
    assert data["total_steps"] == 2


@pytest.mark.asyncio
async def test_activate_emits_role_assigned():
    """activate() emits BILL_ROLE_ASSIGNED for each assigned role."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()

    await rt.activate(bill)

    role_events = [e for e in events if e[0] == EventType.BILL_ROLE_ASSIGNED]
    assert len(role_events) == 2
    role_ids = {e[1]["role_id"] for e in role_events}
    assert role_ids == {"lead", "support"}


@pytest.mark.asyncio
async def test_activate_manual_role_overrides():
    """role_overrides dict bypasses WQSB for specified roles."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()

    inst = await rt.activate(bill, role_overrides={"lead": "agent-forge"})

    assert inst.role_assignments["lead"].agent_id == "agent-forge"


@pytest.mark.asyncio
async def test_activate_partial_assignment_rejected():
    """allow_partial_assignment=False raises on incomplete assignment."""
    config = BillConfig(allow_partial_assignment=False)
    # No registry → no auto-assignment possible
    rt, events = _make_runtime(config=config)
    bill = _make_bill()

    with pytest.raises(BillActivationError, match="Cannot assign roles"):
        await rt.activate(bill)


@pytest.mark.asyncio
async def test_activate_partial_assignment_allowed():
    """allow_partial_assignment=True allows incomplete — instance created."""
    config = BillConfig(allow_partial_assignment=True)
    rt, events = _make_runtime(config=config)
    bill = _make_bill()

    inst = await rt.activate(bill)

    assert inst.status == InstanceStatus.ACTIVE
    assert len(inst.role_assignments) == 0  # No registry → no assignments


# ── Step Lifecycle Tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_step_marks_active():
    """start_step() marks step ACTIVE with agent info."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()
    inst = await rt.activate(bill)

    result = rt.start_step(inst.id, "step-1", "agent-forge", agent_callsign="Forge")

    assert result is True
    ss = inst.step_states["step-1"]
    assert ss.status == StepStatus.ACTIVE
    assert ss.assigned_agent_id == "agent-forge"
    assert ss.started_at is not None


@pytest.mark.asyncio
async def test_start_step_returns_false_non_pending():
    """start_step() returns False for non-PENDING step."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()
    inst = await rt.activate(bill)

    rt.start_step(inst.id, "step-1", "agent-forge")
    result = rt.start_step(inst.id, "step-1", "agent-forge")

    assert result is False


@pytest.mark.asyncio
async def test_start_step_returns_false_terminal_instance():
    """start_step() returns False for terminal instance."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()
    inst = await rt.activate(bill)

    rt.cancel(inst.id)
    result = rt.start_step(inst.id, "step-1", "agent-forge")

    assert result is False


@pytest.mark.asyncio
async def test_complete_step_marks_completed():
    """complete_step() marks step COMPLETED with result."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()
    inst = await rt.activate(bill)

    rt.start_step(inst.id, "step-1", "agent-forge", action="cognitive_skill")
    result = rt.complete_step(inst.id, "step-1", result={"finding": "ok"})

    assert result is True
    ss = inst.step_states["step-1"]
    assert ss.status == StepStatus.COMPLETED
    assert ss.completed_at is not None
    assert ss.result == {"finding": "ok"}


@pytest.mark.asyncio
async def test_complete_all_steps_triggers_bill_completion():
    """All steps completed → instance transitions to COMPLETED."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()
    inst = await rt.activate(bill)

    rt.start_step(inst.id, "step-1", "agent-forge")
    rt.complete_step(inst.id, "step-1")
    rt.start_step(inst.id, "step-2", "agent-atlas")
    rt.complete_step(inst.id, "step-2")

    assert inst.status == InstanceStatus.COMPLETED
    assert inst.completed_at is not None

    completed_events = [e for e in events if e[0] == EventType.BILL_COMPLETED]
    assert len(completed_events) == 1
    assert completed_events[0][1]["instance_id"] == inst.id


@pytest.mark.asyncio
async def test_complete_step_emits_event_with_duration():
    """complete_step() emits BILL_STEP_COMPLETED with duration_s."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()
    inst = await rt.activate(bill)

    rt.start_step(inst.id, "step-1", "agent-forge", action="cognitive_skill")
    rt.complete_step(inst.id, "step-1")

    step_events = [e for e in events if e[0] == EventType.BILL_STEP_COMPLETED]
    assert len(step_events) == 1
    assert step_events[0][1]["action"] == "cognitive_skill"
    assert "duration_s" in step_events[0][1]


@pytest.mark.asyncio
async def test_fail_step_marks_step_and_instance_failed():
    """fail_step() marks step and instance FAILED."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()
    inst = await rt.activate(bill)

    rt.start_step(inst.id, "step-1", "agent-forge")
    result = rt.fail_step(inst.id, "step-1", error="LLM timeout")

    assert result is True
    assert inst.step_states["step-1"].status == StepStatus.FAILED
    assert inst.step_states["step-1"].error == "LLM timeout"
    assert inst.status == InstanceStatus.FAILED


@pytest.mark.asyncio
async def test_fail_step_emits_both_events():
    """fail_step() emits BILL_STEP_FAILED and BILL_FAILED."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()
    inst = await rt.activate(bill)

    rt.start_step(inst.id, "step-1", "agent-forge")
    rt.fail_step(inst.id, "step-1", error="timeout")

    step_failed = [e for e in events if e[0] == EventType.BILL_STEP_FAILED]
    bill_failed = [e for e in events if e[0] == EventType.BILL_FAILED]
    assert len(step_failed) == 1
    assert len(bill_failed) == 1


@pytest.mark.asyncio
async def test_skip_step_marks_skipped():
    """skip_step() marks step SKIPPED."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()
    inst = await rt.activate(bill)

    result = rt.skip_step(inst.id, "step-1")

    assert result is True
    assert inst.step_states["step-1"].status == StepStatus.SKIPPED


@pytest.mark.asyncio
async def test_skip_and_complete_mixed_completes_bill():
    """Mixed skip + complete → instance COMPLETED with progress 1.0."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()
    inst = await rt.activate(bill)

    rt.skip_step(inst.id, "step-1")
    rt.start_step(inst.id, "step-2", "agent-atlas")
    rt.complete_step(inst.id, "step-2")

    assert inst.status == InstanceStatus.COMPLETED
    assert inst.progress == 1.0


@pytest.mark.asyncio
async def test_cancel_instance():
    """cancel() cancels active instance."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()
    inst = await rt.activate(bill)

    result = rt.cancel(inst.id, reason="drill over")

    assert result is True
    assert inst.status == InstanceStatus.CANCELLED
    assert inst.completed_at is not None

    cancelled_events = [e for e in events if e[0] == EventType.BILL_CANCELLED]
    assert len(cancelled_events) == 1
    assert cancelled_events[0][1]["reason"] == "drill over"


@pytest.mark.asyncio
async def test_cancel_terminal_returns_false():
    """cancel() returns False for already-terminal instance."""
    registry = _make_registry()
    rt, events = _make_runtime(registry=registry)
    bill = _make_bill()
    inst = await rt.activate(bill)

    rt.cancel(inst.id)
    result = rt.cancel(inst.id)

    assert result is False


# ── Query Tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_instance_returns_none_unknown():
    """get_instance() returns None for unknown ID."""
    rt, _ = _make_runtime()
    assert rt.get_instance("nonexistent") is None


@pytest.mark.asyncio
async def test_list_instances_filters():
    """list_instances() filters by bill_id, status, active_only."""
    registry = _make_registry()
    rt, _ = _make_runtime(registry=registry)
    bill1 = _make_bill(bill="gq")
    bill2 = _make_bill(bill="fire-drill")

    inst1 = await rt.activate(bill1)
    inst2 = await rt.activate(bill2)
    rt.cancel(inst2.id)

    assert len(rt.list_instances()) == 2
    assert len(rt.list_instances(bill_id="gq")) == 1
    assert len(rt.list_instances(status=InstanceStatus.CANCELLED)) == 1
    assert len(rt.list_instances(active_only=True)) == 1


@pytest.mark.asyncio
async def test_get_agent_assignments_active():
    """get_agent_assignments() returns active assignments."""
    registry = _make_registry()
    rt, _ = _make_runtime(registry=registry)
    bill = _make_bill()

    inst = await rt.activate(bill)

    assignments = rt.get_agent_assignments("agent-forge")
    assert len(assignments) == 1
    assert assignments[0]["bill_id"] == "general-quarters"
    assert assignments[0]["role_id"] == "lead"


@pytest.mark.asyncio
async def test_get_agent_assignments_excludes_terminal():
    """get_agent_assignments() excludes terminal instances."""
    registry = _make_registry()
    rt, _ = _make_runtime(registry=registry)
    bill = _make_bill()

    inst = await rt.activate(bill)
    rt.cancel(inst.id)

    assert rt.get_agent_assignments("agent-forge") == []


@pytest.mark.asyncio
async def test_active_count_property():
    """active_count counts only ACTIVE instances."""
    registry = _make_registry()
    rt, _ = _make_runtime(registry=registry)
    bill = _make_bill()

    assert rt.active_count == 0

    inst1 = await rt.activate(bill)
    assert rt.active_count == 1

    rt.cancel(inst1.id)
    assert rt.active_count == 0
