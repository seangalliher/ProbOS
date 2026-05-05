"""AD-528b: Ground-Truth Active Rejection & Quarantine tests.

Wraps the existing AD-528 GroundTruthVerifier with a rejection gate that
takes corrective action when verification fails: emits VERIFICATION_REJECTED,
attempts to merge a quarantine payload into the work item's metadata via
WorkItemStore.update_work_item, and emits WORK_ITEM_QUARANTINED when the
merge succeeds. v1 surfaces the layer; caller integration is AD-528b-2.
"""

from __future__ import annotations

import dataclasses
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.ground_truth import (
    GroundTruthRejectionGate,
    GroundTruthResult,
    GroundTruthVerifier,
    RejectionDecision,
)
from probos.config import GroundTruthConfig
from probos.events import EventType


# ----- Helpers -----


def _journal_entry(*, journal_type="working", duration=10.0, tokens=500, billable=True):
    return SimpleNamespace(
        journal_type=journal_type,
        duration_seconds=duration,
        tokens_consumed=tokens,
        billable=billable,
    )


def _make_runtime_with_store(
    *,
    journal_entries=None,
    events=None,
    work_item=None,
    update_returns=None,
    update_side_effect=None,
):
    """Build a SimpleNamespace runtime with AsyncMock work_item_store + event_log."""
    rt = SimpleNamespace()
    store = SimpleNamespace()
    if journal_entries is not None:
        store.get_booking_journal = AsyncMock(return_value=journal_entries)
    else:
        store.get_booking_journal = AsyncMock(return_value=[])
    store.get_work_item = AsyncMock(return_value=work_item)
    if update_side_effect is not None:
        store.update_work_item = AsyncMock(side_effect=update_side_effect)
    else:
        store.update_work_item = AsyncMock(return_value=update_returns)
    rt.work_item_store = store
    if events is not None:
        log = SimpleNamespace()
        log.query = AsyncMock(return_value=events)
        rt.event_log = log
    else:
        rt.event_log = None
    return rt, store


def _make_gate(rt, *, emit=None, metadata_key="ground_truth_quarantine", threshold=0.75):
    """Construct a GroundTruthVerifier + GroundTruthRejectionGate pair."""
    if emit is None:
        emit = MagicMock()
    verifier = GroundTruthVerifier(
        runtime=rt, emit_event=emit, threshold=threshold,
    )
    gate = GroundTruthRejectionGate(
        verifier=verifier,
        runtime=rt,
        emit_event=emit,
        metadata_key=metadata_key,
    )
    return gate, verifier, emit


# ----- 1-2: EventTypes -----


def test_event_type_verification_rejected_exists():
    assert EventType.VERIFICATION_REJECTED.value == "verification_rejected"


def test_event_type_work_item_quarantined_exists():
    assert EventType.WORK_ITEM_QUARANTINED.value == "work_item_quarantined"


# ----- 3-4: Config defaults -----


def test_ground_truth_config_active_rejection_default_false():
    cfg = GroundTruthConfig()
    assert cfg.active_rejection_enabled is False


def test_ground_truth_config_quarantine_metadata_key_default():
    cfg = GroundTruthConfig()
    assert cfg.quarantine_metadata_key == "ground_truth_quarantine"


# ----- 5: RejectionDecision dataclass shape -----


def test_rejection_decision_dataclass_shape():
    fields = {f.name: f for f in dataclasses.fields(RejectionDecision)}
    assert set(fields.keys()) == {
        "verified", "score", "action",
        "quarantine_metadata", "signals",
        "booking_id", "agent_id", "work_item_id",
    }
    # Frozen
    decision = RejectionDecision(verified=True, score=1.0, action="allow")
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.action = "reject"  # type: ignore[misc]
    # Mutable defaults via default_factory (not bare {})
    a = RejectionDecision(verified=True, score=1.0, action="allow")
    b = RejectionDecision(verified=True, score=1.0, action="allow")
    assert a.quarantine_metadata is not b.quarantine_metadata
    assert a.signals is not b.signals


# ----- 6: evaluate allow path -----


@pytest.mark.asyncio
async def test_evaluate_allow_when_verified():
    completed_at = time.time()
    rt, _store = _make_runtime_with_store(
        journal_entries=[_journal_entry(duration=10.0, tokens=500, billable=True)],
        events=[{"timestamp": completed_at - 30}],
    )
    gate, _verifier, emit = _make_gate(rt)
    decision = await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="did the thing",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    assert decision.verified is True
    assert decision.action == "allow"
    assert decision.score == 1.0
    assert decision.quarantine_metadata == {}
    assert decision.work_item_id == "wi1"
    # The verifier's PASSED emit fired; the gate's REJECTED/QUARANTINED did NOT.
    emitted_types = [c.args[0] for c in emit.call_args_list]
    assert EventType.VERIFICATION_PASSED in emitted_types
    assert EventType.VERIFICATION_REJECTED not in emitted_types
    assert EventType.WORK_ITEM_QUARANTINED not in emitted_types


# ----- 7: evaluate reject path -----


@pytest.mark.asyncio
async def test_evaluate_reject_when_unverified():
    completed_at = time.time()
    work_item = SimpleNamespace(metadata={})
    rt, _store = _make_runtime_with_store(
        journal_entries=[],
        events=[],
        work_item=work_item,
    )
    gate, _verifier, _emit = _make_gate(rt)
    decision = await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="claimed",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    assert decision.verified is False
    assert decision.action == "reject"
    assert decision.score == 0.0
    assert decision.quarantine_metadata["reason"] == "ground_truth_score_below_threshold"
    assert decision.quarantine_metadata["booking_id"] == "bk1"
    assert decision.quarantine_metadata["agent_id"] == "a1"
    assert "rejected_at" in decision.quarantine_metadata
    assert decision.signals == []


# ----- 8: emit VERIFICATION_REJECTED on reject path -----


@pytest.mark.asyncio
async def test_evaluate_emits_verification_rejected_on_reject():
    completed_at = time.time()
    work_item = SimpleNamespace(metadata={})
    rt, _store = _make_runtime_with_store(
        journal_entries=[],
        events=[],
        work_item=work_item,
    )
    gate, _verifier, emit = _make_gate(rt)
    await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="claimed",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    emitted_types = [c.args[0] for c in emit.call_args_list]
    # FAILED fires inside verifier.verify; REJECTED fires from the gate.
    assert EventType.VERIFICATION_FAILED in emitted_types
    assert EventType.VERIFICATION_REJECTED in emitted_types


# ----- 9: no REJECTED/QUARANTINED on allow path -----


@pytest.mark.asyncio
async def test_evaluate_does_not_emit_rejected_or_quarantined_on_allow():
    completed_at = time.time()
    rt, _store = _make_runtime_with_store(
        journal_entries=[_journal_entry(duration=10.0, tokens=500, billable=True)],
        events=[{"timestamp": completed_at - 30}],
    )
    gate, _verifier, emit = _make_gate(rt)
    await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="x",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    emitted_types = [c.args[0] for c in emit.call_args_list]
    assert EventType.VERIFICATION_REJECTED not in emitted_types
    assert EventType.WORK_ITEM_QUARANTINED not in emitted_types


# ----- 10: quarantine metadata applied to work item -----


@pytest.mark.asyncio
async def test_evaluate_applies_quarantine_metadata_to_work_item():
    completed_at = time.time()
    work_item = SimpleNamespace(metadata={})
    rt, store = _make_runtime_with_store(
        journal_entries=[],
        events=[],
        work_item=work_item,
    )
    gate, _verifier, _emit = _make_gate(rt, metadata_key="gt_quarantine_v1")
    await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="x",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    store.update_work_item.assert_awaited_once()
    call_args = store.update_work_item.await_args
    assert call_args.args == ("wi1",)
    merged = call_args.kwargs["metadata"]
    assert "gt_quarantine_v1" in merged
    payload = merged["gt_quarantine_v1"]
    assert payload["reason"] == "ground_truth_score_below_threshold"
    assert payload["booking_id"] == "bk1"


# ----- 11: existing metadata preserved -----


@pytest.mark.asyncio
async def test_evaluate_preserves_existing_work_item_metadata():
    completed_at = time.time()
    work_item = SimpleNamespace(metadata={"sentinel": "keep_me", "other": 42})
    rt, store = _make_runtime_with_store(
        journal_entries=[],
        events=[],
        work_item=work_item,
    )
    gate, _verifier, _emit = _make_gate(rt)
    await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="x",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    merged = store.update_work_item.await_args.kwargs["metadata"]
    assert merged["sentinel"] == "keep_me"
    assert merged["other"] == 42
    assert "ground_truth_quarantine" in merged


# ----- 12: WORK_ITEM_QUARANTINED emitted after successful apply -----


@pytest.mark.asyncio
async def test_evaluate_emits_work_item_quarantined_after_apply():
    completed_at = time.time()
    work_item = SimpleNamespace(metadata={})
    rt, _store = _make_runtime_with_store(
        journal_entries=[],
        events=[],
        work_item=work_item,
    )
    gate, _verifier, emit = _make_gate(rt)
    await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="x",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    emitted = [c.args for c in emit.call_args_list]
    quarantined_calls = [
        (et, p) for (et, p) in emitted if et == EventType.WORK_ITEM_QUARANTINED
    ]
    assert len(quarantined_calls) == 1
    _et, payload = quarantined_calls[0]
    assert payload["work_item_id"] == "wi1"
    assert payload["metadata_key"] == "ground_truth_quarantine"
    assert payload["reason"] == "ground_truth_score_below_threshold"


# ----- 13: missing work_item_store handled gracefully -----


@pytest.mark.asyncio
async def test_evaluate_handles_missing_work_item_store_gracefully():
    completed_at = time.time()
    rt = SimpleNamespace()
    rt.work_item_store = None  # No store available
    rt.event_log = None
    emit = MagicMock()
    verifier = GroundTruthVerifier(runtime=rt, emit_event=emit)
    gate = GroundTruthRejectionGate(verifier=verifier, runtime=rt, emit_event=emit)
    decision = await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="x",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    # Decision is still rejected; quarantine apply silently fails.
    assert decision.action == "reject"
    emitted_types = [c.args[0] for c in emit.call_args_list]
    assert EventType.VERIFICATION_REJECTED in emitted_types
    assert EventType.WORK_ITEM_QUARANTINED not in emitted_types


# ----- 14: update_work_item exception swallowed (tier-2 log-and-degrade) -----


@pytest.mark.asyncio
async def test_evaluate_handles_update_exception_log_and_degrade(caplog):
    import logging
    completed_at = time.time()
    work_item = SimpleNamespace(metadata={})
    rt, _store = _make_runtime_with_store(
        journal_entries=[],
        events=[],
        work_item=work_item,
        update_side_effect=RuntimeError("disk full"),
    )
    gate, _verifier, emit = _make_gate(rt)
    with caplog.at_level(logging.WARNING):
        decision = await gate.evaluate(
            booking_id="bk1",
            agent_id="a1",
            claimed_summary="x",
            work_item_id="wi1",
            completed_at=completed_at,
        )
    # Exception swallowed; decision still produced; QUARANTINED NOT emitted.
    assert decision.action == "reject"
    emitted_types = [c.args[0] for c in emit.call_args_list]
    assert EventType.VERIFICATION_REJECTED in emitted_types
    assert EventType.WORK_ITEM_QUARANTINED not in emitted_types
    assert any(
        "AD-528b: quarantine metadata apply failed" in rec.getMessage()
        for rec in caplog.records
    )
