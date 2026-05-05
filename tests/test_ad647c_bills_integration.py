"""AD-647c v1 — Bills + Watch Bill integration for process chains."""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.cognitive.process_chains import (
    ProcessChainDefinition,
    ProcessChainExecutionError,
    ProcessChainExecutor,
    ProcessChainRegistry,
    ProcessChainStep,
    ProcessChainStepKind,
)


# ----------------------------------------------------------------------
# Fixtures / helpers
# ----------------------------------------------------------------------

async def _noop(ctx: dict[str, Any]) -> dict[str, Any]:
    return {}


def _step(name: str = "s", *, kind=ProcessChainStepKind.TRANSFORM,
          handler=_noop, bill_step_id: str = "", assigned_role: str = ""):
    return ProcessChainStep(
        kind=kind, name=name, handler=handler,
        bill_step_id=bill_step_id, assigned_role=assigned_role,
    )


def _make_instance(instance_id: str = "i1", role_holder: dict | None = None):
    """Build a stub BillInstance with role_assignments dict."""
    assignments = {}
    if role_holder:
        for role, agent_id in role_holder.items():
            assignments[role] = SimpleNamespace(
                role_id=role, agent_id=agent_id, agent_type="x",
                callsign="x", department="x", assigned_at=0.0,
            )
    return SimpleNamespace(id=instance_id, role_assignments=assignments)


# ----------------------------------------------------------------------
# Section 1: Field additions on ProcessChainStep
# ----------------------------------------------------------------------

def test_step_accepts_bill_step_id_field():
    s = _step(bill_step_id="check_alarms")
    assert s.bill_step_id == "check_alarms"


def test_step_accepts_assigned_role_field():
    s = _step(assigned_role="oncall_engineer")
    assert s.assigned_role == "oncall_engineer"


def test_consult_step_kind_constructs_cleanly():
    s = _step(kind=ProcessChainStepKind.CONSULT)
    assert s.kind is ProcessChainStepKind.CONSULT
    assert s.kind.value == "consult"


# ----------------------------------------------------------------------
# Section 2: Executor backward compat
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_without_bill_runtime_runs_identically_to_v1():
    async def h(ctx):
        return {"x": 1}
    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", handler=h, bill_step_id="bstep_ignored"),),
    )
    executor = ProcessChainExecutor()
    out = await executor.run(chain)
    assert out == {"x": 1}


@pytest.mark.asyncio
async def test_executor_with_bill_runtime_but_no_instance_id_skips_recording():
    bill_rt = MagicMock()
    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", bill_step_id="bs1"),),
    )
    executor = ProcessChainExecutor(bill_runtime=bill_rt)
    await executor.run(chain)
    bill_rt.get_instance.assert_not_called()
    bill_rt.complete_step.assert_not_called()


# ----------------------------------------------------------------------
# Section 3: Bill step lifecycle recording
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_executor_records_complete_step_on_success():
    bill_rt = MagicMock()
    bill_rt.get_instance.return_value = _make_instance("i1")

    async def h(ctx):
        return {"out": 42}

    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", handler=h, bill_step_id="bstep_alpha"),),
    )
    executor = ProcessChainExecutor(bill_runtime=bill_rt)
    await executor.run(chain, {"bill_instance_id": "i1"})

    bill_rt.get_instance.assert_called_once_with("i1")
    bill_rt.complete_step.assert_called_once_with("i1", "bstep_alpha", result={"out": 42})


@pytest.mark.asyncio
async def test_executor_records_fail_step_on_handler_exception():
    bill_rt = MagicMock()
    bill_rt.get_instance.return_value = _make_instance("i1")

    async def boom(ctx):
        raise RuntimeError("nope")

    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", handler=boom, bill_step_id="bstep_beta"),),
    )
    executor = ProcessChainExecutor(bill_runtime=bill_rt)
    with pytest.raises(ProcessChainExecutionError):
        await executor.run(chain, {"bill_instance_id": "i1"})

    bill_rt.fail_step.assert_called_once()
    args, kwargs = bill_rt.fail_step.call_args
    assert args == ("i1", "bstep_beta")
    assert "RuntimeError" in kwargs["error"] and "nope" in kwargs["error"]
    bill_rt.complete_step.assert_not_called()


@pytest.mark.asyncio
async def test_bill_recording_tier2_log_and_degrade_does_not_break_chain(caplog):
    bill_rt = MagicMock()
    bill_rt.get_instance.return_value = _make_instance("i1")
    bill_rt.complete_step.side_effect = RuntimeError("bill-side bug")

    async def h(ctx):
        return {"ok": True}

    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", handler=h, bill_step_id="bs1"),),
    )
    executor = ProcessChainExecutor(bill_runtime=bill_rt)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.process_chains"):
        out = await executor.run(chain, {"bill_instance_id": "i1"})
    assert out == {"ok": True, "bill_instance_id": "i1"}
    assert any("bill_runtime.complete_step" in r.message for r in caplog.records)


# ----------------------------------------------------------------------
# Section 4: Role resolution
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_assigned_role_injects_resolved_agent_id_into_context():
    bill_rt = MagicMock()
    bill_rt.get_instance.return_value = _make_instance(
        "i1", role_holder={"oncall": "agent-007"}
    )

    captured: dict[str, Any] = {}

    async def h(ctx):
        captured.update(ctx)
        return {}

    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", handler=h, assigned_role="oncall"),),
    )
    executor = ProcessChainExecutor(bill_runtime=bill_rt)
    await executor.run(chain, {"bill_instance_id": "i1"})
    assert captured.get("_resolved_agent_id_s1") == "agent-007"


@pytest.mark.asyncio
async def test_unresolved_role_log_and_degrade(caplog):
    bill_rt = MagicMock()
    bill_rt.get_instance.return_value = _make_instance("i1")

    captured: dict[str, Any] = {}

    async def h(ctx):
        captured.update(ctx)
        return {"x": 1}

    chain = ProcessChainDefinition(
        name="c",
        steps=(_step("s1", handler=h, assigned_role="oncall"),),
    )
    executor = ProcessChainExecutor(bill_runtime=bill_rt)
    with caplog.at_level(logging.WARNING, logger="probos.cognitive.process_chains"):
        await executor.run(chain, {"bill_instance_id": "i1"})
    assert "_resolved_agent_id_s1" not in captured
    assert any("has no holder" in r.message for r in caplog.records)


# ----------------------------------------------------------------------
# Section 5: register_bill_chain validation
# ----------------------------------------------------------------------

def _fake_bill(slug: str, step_ids: list[str]):
    return SimpleNamespace(
        bill=slug,
        steps=[SimpleNamespace(id=sid) for sid in step_ids],
    )


def test_register_bill_chain_happy_path():
    registry = ProcessChainRegistry()
    bill = _fake_bill("incident_response", ["triage", "mitigate", "close"])
    chain = ProcessChainDefinition(
        name="ir_chain",
        steps=(
            _step("p1", bill_step_id="triage"),
            _step("p2", bill_step_id="mitigate"),
        ),
    )
    registry.register_bill_chain(bill, chain)
    assert registry.get_chain("ir_chain") is chain


def test_register_bill_chain_rejects_mismatched_bill_step_ids():
    registry = ProcessChainRegistry()
    bill = _fake_bill("ir", ["triage", "mitigate"])
    chain = ProcessChainDefinition(
        name="bad",
        steps=(
            _step("p1", bill_step_id="triage"),
            _step("p2", bill_step_id="not_a_real_step"),
        ),
    )
    with pytest.raises(ValueError, match="unknown bill step ids"):
        registry.register_bill_chain(bill, chain)
    assert registry.get_chain("bad") is None


def test_register_bill_chain_permits_empty_bill_step_ids():
    registry = ProcessChainRegistry()
    bill = _fake_bill("ir", ["a"])
    chain = ProcessChainDefinition(
        name="mixed",
        steps=(
            _step("p1", bill_step_id="a"),
            _step("p2"),
        ),
    )
    registry.register_bill_chain(bill, chain)
    assert registry.get_chain("mixed") is chain
