"""AD-647d: tests for ChainCheckpointStore + suspend/resume primitives."""
from __future__ import annotations

from pathlib import Path

import pytest

from probos.cognitive.chain_checkpoint import (
    ChainCheckpoint,
    ChainCheckpointStore,
    ChainSuspended,
    SuspendChain,
    write_checkpoint,
)
from probos.cognitive.process_chains import (
    ProcessChainDefinition,
    ProcessChainExecutionError,
    ProcessChainExecutor,
    ProcessChainStep,
    ProcessChainStepKind,
)


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    store = ChainCheckpointStore(root=tmp_path)
    cp = ChainCheckpoint(
        checkpoint_id="cp1",
        chain_name="incident_response",
        suspended_at_step="captain_approval",
        suspended_at=1234.5,
        running_context={"facts": ["a", "b"], "score": 0.8},
        reason="awaiting captain",
    )
    store.save(cp)
    loaded = store.load("cp1")
    assert loaded is not None
    assert loaded.chain_name == "incident_response"
    assert loaded.suspended_at_step == "captain_approval"
    assert loaded.running_context == {"facts": ["a", "b"], "score": 0.8}
    assert loaded.reason == "awaiting captain"


def test_load_missing_returns_none(tmp_path: Path) -> None:
    store = ChainCheckpointStore(root=tmp_path)
    assert store.load("nonexistent") is None


def test_delete_removes_file(tmp_path: Path) -> None:
    store = ChainCheckpointStore(root=tmp_path)
    cp = ChainCheckpoint(
        checkpoint_id="cp1", chain_name="x", suspended_at_step="s", suspended_at=0.0,
    )
    store.save(cp)
    assert store.delete("cp1") is True
    assert store.delete("cp1") is False  # idempotent
    assert store.load("cp1") is None


def test_list_ids_returns_sorted(tmp_path: Path) -> None:
    store = ChainCheckpointStore(root=tmp_path)
    for cid in ["c", "a", "b"]:
        store.save(ChainCheckpoint(
            checkpoint_id=cid, chain_name="x", suspended_at_step="s", suspended_at=0.0,
        ))
    assert store.list_ids() == ["a", "b", "c"]


def test_load_corrupt_json_returns_none(tmp_path: Path) -> None:
    store = ChainCheckpointStore(root=tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid", encoding="utf-8")
    assert store.load("bad") is None


def test_write_checkpoint_helper_assigns_id(tmp_path: Path) -> None:
    store = ChainCheckpointStore(root=tmp_path)
    cp = write_checkpoint(
        store, chain_name="x", step_name="s",
        running_context={"k": 1}, reason="testing",
    )
    assert cp.checkpoint_id != ""
    assert store.load(cp.checkpoint_id) is not None


# ---------------------------------------------------------------------------
# Executor integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_suspends_chain_when_handler_raises_suspend(tmp_path: Path) -> None:
    store = ChainCheckpointStore(root=tmp_path)

    async def step1(ctx):
        ctx["ran_step1"] = True
        return {"ran_step1": True}

    async def step2_consult(ctx):
        raise SuspendChain(
            reason="captain approval needed",
            context_extra={"awaiting": "captain"},
        )

    chain = ProcessChainDefinition(
        name="approval_flow",
        steps=(
            ProcessChainStep(kind=ProcessChainStepKind.QUERY, name="gather", handler=step1),
            ProcessChainStep(kind=ProcessChainStepKind.CONSULT, name="approve", handler=step2_consult),
        ),
    )
    executor = ProcessChainExecutor(checkpoint_store=store)

    with pytest.raises(ChainSuspended) as exc_info:
        await executor.run(chain, context={"trigger": "alpha"})

    suspended = exc_info.value
    assert suspended.chain_name == "approval_flow"
    assert suspended.step_name == "approve"

    cp = store.load(suspended.checkpoint_id)
    assert cp is not None
    assert cp.running_context["ran_step1"] is True
    assert cp.running_context["trigger"] == "alpha"
    assert cp.running_context["awaiting"] == "captain"
    assert cp.reason == "captain approval needed"


@pytest.mark.asyncio
async def test_executor_without_store_treats_suspend_as_failure(tmp_path: Path) -> None:
    async def consult(ctx):
        raise SuspendChain(reason="x")

    chain = ProcessChainDefinition(
        name="no_cp",
        steps=(
            ProcessChainStep(kind=ProcessChainStepKind.CONSULT, name="ask", handler=consult),
        ),
    )
    executor = ProcessChainExecutor()  # no checkpoint_store
    with pytest.raises(ProcessChainExecutionError):
        await executor.run(chain)


@pytest.mark.asyncio
async def test_executor_normal_step_failure_unaffected(tmp_path: Path) -> None:
    """Non-SuspendChain exceptions still propagate as ProcessChainExecutionError."""
    store = ChainCheckpointStore(root=tmp_path)

    async def boom(ctx):
        raise RuntimeError("real failure")

    chain = ProcessChainDefinition(
        name="x",
        steps=(
            ProcessChainStep(kind=ProcessChainStepKind.TRANSFORM, name="bad", handler=boom),
        ),
    )
    executor = ProcessChainExecutor(checkpoint_store=store)
    with pytest.raises(ProcessChainExecutionError):
        await executor.run(chain)
    # No checkpoint should have been written.
    assert store.list_ids() == []
