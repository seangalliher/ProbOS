"""AD-1080: WorkItem.steps as a senior-validated Todo checklist.

The room's Todo list lives on its task work item's ``steps``. Each step runs a
small state machine: pending -> in_progress -> submitted (worker self-reports
done) -> done (a SENIOR confirms) | rejected (-> back to in_progress). A work
item flagged ``steps_gate_completion`` cannot transition to 'done' until EVERY
step is senior-confirmed — nothing is complete until validated.

BF-287: real WorkItemStore on tmp_path.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from probos.workforce import (
    WorkItemStore,
    _all_steps_done,
    validate_step_transition,
)


@pytest_asyncio.fixture
async def store(tmp_path: Path):
    s = WorkItemStore(db_path=str(tmp_path / "wis.db"))
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


# ---------------- pure helpers ----------------


def test_validate_step_transition_happy_path():
    assert validate_step_transition("pending", "in_progress")
    assert validate_step_transition("pending", "submitted")   # worker reports done w/o explicit start
    assert validate_step_transition("in_progress", "submitted")
    assert validate_step_transition("submitted", "done")
    assert validate_step_transition("submitted", "rejected")
    assert validate_step_transition("rejected", "in_progress")
    assert validate_step_transition("rejected", "submitted")  # rework reported done


def test_validate_step_transition_rejects_skips_and_unknown():
    assert not validate_step_transition("pending", "done")       # cannot skip review
    assert not validate_step_transition("pending", "rejected")   # cannot reject un-submitted work
    assert not validate_step_transition("done", "in_progress")   # done is terminal
    assert not validate_step_transition("pending", "banana")     # unknown status
    assert validate_step_transition("in_progress", "in_progress")  # idempotent


def test_all_steps_done():
    assert not _all_steps_done([])  # empty is NOT done
    assert _all_steps_done([{"status": "done"}, {"status": "done"}])
    assert not _all_steps_done([{"status": "done"}, {"status": "submitted"}])


# ---------------- set_steps ----------------


@pytest.mark.asyncio
async def test_set_steps_normalizes_strings_and_dicts(store):
    wi = await store.create_work_item(title="T", work_type="task")
    out = await store.set_steps(wi.id, ["Draft the spec", {"label": "Review", "status": "in_progress"}, {"label": ""}])
    assert [s["label"] for s in out.steps] == ["Draft the spec", "Review"]  # empty dropped
    assert out.steps[0]["status"] == "pending"     # bare string -> pending
    assert out.steps[1]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_set_steps_gate_completion_sets_metadata(store):
    wi = await store.create_work_item(title="T", work_type="task")
    out = await store.set_steps(wi.id, ["a", "b"], gate_completion=True)
    assert out.metadata.get("steps_gate_completion") is True


# ---------------- the validation loop ----------------


@pytest.mark.asyncio
async def test_step_loop_work_submit_confirm_records_actors(store):
    wi = await store.create_work_item(title="T", work_type="task")
    await store.set_steps(wi.id, ["Build the widget"])

    w = await store.update_step(wi.id, 0, status="in_progress", actor="worker-1")
    assert w.steps[0]["status"] == "in_progress"
    assert w.steps[0]["assigned_to"] == "worker-1"

    w = await store.update_step(wi.id, 0, status="submitted", actor="worker-1")
    assert w.steps[0]["status"] == "submitted"
    assert w.steps[0]["submitted_by"] == "worker-1"

    w = await store.update_step(wi.id, 0, status="done", actor="senior-1")
    assert w.steps[0]["status"] == "done"
    assert w.steps[0]["confirmed_by"] == "senior-1"


@pytest.mark.asyncio
async def test_step_reject_sends_work_back(store):
    wi = await store.create_work_item(title="T", work_type="task")
    await store.set_steps(wi.id, ["Build the widget"])
    await store.update_step(wi.id, 0, status="in_progress", actor="worker-1")
    await store.update_step(wi.id, 0, status="submitted", actor="worker-1")

    w = await store.update_step(wi.id, 0, status="rejected", actor="senior-1", note="missing tests")
    assert w.steps[0]["status"] == "rejected"
    assert w.steps[0]["note"] == "missing tests"

    # ... and the work goes back for completion.
    w = await store.update_step(wi.id, 0, status="in_progress", actor="worker-1")
    assert w.steps[0]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_invalid_step_transition_returns_none_and_preserves(store):
    wi = await store.create_work_item(title="T", work_type="task")
    await store.set_steps(wi.id, ["x"])
    assert await store.update_step(wi.id, 0, status="done") is None  # pending->done skips review
    reread = await store.get_work_item(wi.id)
    assert reread.steps[0]["status"] == "pending"  # untouched


@pytest.mark.asyncio
async def test_bad_step_index_returns_none(store):
    wi = await store.create_work_item(title="T", work_type="task")
    await store.set_steps(wi.id, ["x"])
    assert await store.update_step(wi.id, 5, status="in_progress") is None


# ---------------- the completion gate ----------------


@pytest.mark.asyncio
async def test_gated_task_cannot_complete_until_all_steps_done(store):
    wi = await store.create_work_item(title="T", work_type="card")
    await store.set_steps(wi.id, [{"label": "a", "status": "pending"}], gate_completion=True)
    # card allows draft->done in AD-498, but AD-1080 refuses while a step is open.
    assert await store.transition_work_item(wi.id, "done") is None
    assert (await store.get_work_item(wi.id)).status != "done"


@pytest.mark.asyncio
async def test_gated_task_completes_when_all_steps_done(store):
    wi = await store.create_work_item(title="T", work_type="card")
    await store.set_steps(wi.id, [{"label": "a", "status": "done"}], gate_completion=True)
    done = await store.transition_work_item(wi.id, "done")
    assert done is not None and done.status == "done"


@pytest.mark.asyncio
async def test_ungated_task_is_unaffected(store):
    # No gate flag -> AD-1080 never blocks (byte-identical to AD-498).
    wi = await store.create_work_item(title="T", work_type="card")
    await store.set_steps(wi.id, [{"label": "a", "status": "pending"}])  # steps but NO gate
    done = await store.transition_work_item(wi.id, "done")
    assert done is not None and done.status == "done"
