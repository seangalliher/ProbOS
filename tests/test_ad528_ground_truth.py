"""AD-528 Ground-Truth Task Verification tests."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.ground_truth import (
    GroundTruthResult,
    GroundTruthVerifier,
    VerificationEpisodeWriter,
)
from probos.config import GroundTruthConfig
from probos.events import EventType
from probos.types import Episode, MemorySource


# ----- Helpers -----


def _journal_entry(*, journal_type="working", duration=10.0, tokens=500, billable=True):
    return SimpleNamespace(
        journal_type=journal_type,
        duration_seconds=duration,
        tokens_consumed=tokens,
        billable=billable,
    )


def _make_runtime(*, journal_entries=None, events=None):
    rt = SimpleNamespace()
    if journal_entries is None:
        rt.work_item_store = None
    else:
        wf = SimpleNamespace()
        wf.get_booking_journal = AsyncMock(return_value=journal_entries)
        rt.work_item_store = wf
    if events is None:
        rt.event_log = None
    else:
        log = SimpleNamespace()
        log.query = AsyncMock(return_value=events)
        rt.event_log = log
    return rt


# ----- EventTypes & Config -----


def test_event_type_verification_passed_exists():
    assert EventType.VERIFICATION_PASSED.value == "verification_passed"


def test_event_type_verification_failed_exists():
    assert EventType.VERIFICATION_FAILED.value == "verification_failed"


def test_ground_truth_config_defaults():
    cfg = GroundTruthConfig()
    assert cfg.enabled is True
    assert cfg.threshold == 0.75
    assert cfg.event_window_seconds == 600.0
    assert cfg.write_episode is True


# ----- Verifier -----


@pytest.mark.asyncio
async def test_verify_no_runtime_returns_unverified():
    emit = MagicMock()
    verifier = GroundTruthVerifier(runtime=None, emit_event=emit)
    result = await verifier.verify(
        booking_id="bk1", agent_id="a1", claimed_summary="x"
    )
    assert result.verified is False
    assert result.score == 0.0
    assert result.signals == []
    emit.assert_called_once()
    et, payload = emit.call_args[0]
    assert et == EventType.VERIFICATION_FAILED


@pytest.mark.asyncio
async def test_verify_full_match_passes():
    emit = MagicMock()
    completed_at = time.time()
    rt = _make_runtime(
        journal_entries=[_journal_entry(duration=10.0, tokens=500, billable=True)],
        events=[{"timestamp": completed_at - 30}],
    )
    verifier = GroundTruthVerifier(runtime=rt, emit_event=emit)
    result = await verifier.verify(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="did the thing",
        completed_at=completed_at,
    )
    assert result.verified is True
    assert result.score == 1.0
    assert set(result.signals) == {
        "journal_present",
        "duration_nonzero",
        "tokens_recorded",
        "event_within_window",
    }
    et, _ = emit.call_args[0]
    assert et == EventType.VERIFICATION_PASSED


@pytest.mark.asyncio
async def test_verify_journal_missing_fails():
    emit = MagicMock()
    completed_at = time.time()
    rt = _make_runtime(
        journal_entries=[],
        events=[{"timestamp": completed_at - 30}],
    )
    verifier = GroundTruthVerifier(runtime=rt, emit_event=emit)
    result = await verifier.verify(
        booking_id="bk1", agent_id="a1", claimed_summary="x", completed_at=completed_at
    )
    assert result.verified is False
    assert result.score == 0.25
    assert result.signals == ["event_within_window"]
    et, _ = emit.call_args[0]
    assert et == EventType.VERIFICATION_FAILED


@pytest.mark.asyncio
async def test_verify_zero_duration_fails_duration_signal():
    emit = MagicMock()
    completed_at = time.time()
    rt = _make_runtime(
        journal_entries=[_journal_entry(duration=0.0, tokens=500)],
        events=[{"timestamp": completed_at - 30}],
    )
    verifier = GroundTruthVerifier(runtime=rt, emit_event=emit)
    result = await verifier.verify(
        booking_id="bk1", agent_id="a1", claimed_summary="x", completed_at=completed_at
    )
    assert "journal_present" in result.signals
    assert "duration_nonzero" not in result.signals


@pytest.mark.asyncio
async def test_verify_billable_false_passes_tokens_signal():
    emit = MagicMock()
    completed_at = time.time()
    rt = _make_runtime(
        journal_entries=[_journal_entry(duration=10.0, tokens=0, billable=False)],
        events=[{"timestamp": completed_at - 30}],
    )
    verifier = GroundTruthVerifier(runtime=rt, emit_event=emit)
    result = await verifier.verify(
        booking_id="bk1", agent_id="a1", claimed_summary="x", completed_at=completed_at
    )
    assert "tokens_recorded" in result.signals


@pytest.mark.asyncio
async def test_verify_event_outside_window_fails_event_signal():
    emit = MagicMock()
    completed_at = time.time()
    rt = _make_runtime(
        journal_entries=[_journal_entry(duration=10.0, tokens=500)],
        events=[{"timestamp": completed_at - 99999}],  # way outside 600s window
    )
    verifier = GroundTruthVerifier(runtime=rt, emit_event=emit)
    result = await verifier.verify(
        booking_id="bk1", agent_id="a1", claimed_summary="x", completed_at=completed_at
    )
    assert "event_within_window" not in result.signals


@pytest.mark.asyncio
async def test_verify_threshold_boundary():
    """Score exactly equal to threshold verifies (>=)."""
    emit = MagicMock()
    completed_at = time.time()
    rt = _make_runtime(
        journal_entries=[_journal_entry(duration=10.0, tokens=500, billable=True)],
        events=[{"timestamp": completed_at - 30}],
    )
    # 3 of 4 signals = 0.75; threshold default 0.75 -> verified True
    # Force exactly 3 signals by zeroing duration -> only 3 of 4 match
    rt = _make_runtime(
        journal_entries=[_journal_entry(duration=0.0, tokens=500, billable=True)],
        events=[{"timestamp": completed_at - 30}],
    )
    verifier = GroundTruthVerifier(runtime=rt, emit_event=emit, threshold=0.75)
    result = await verifier.verify(
        booking_id="bk1", agent_id="a1", claimed_summary="x", completed_at=completed_at
    )
    assert result.score == 0.75
    assert result.verified is True


@pytest.mark.asyncio
async def test_verify_emits_failed_event_with_signals_list():
    emit = MagicMock()
    rt = _make_runtime(journal_entries=[], events=[])
    verifier = GroundTruthVerifier(runtime=rt, emit_event=emit)
    result = await verifier.verify(
        booking_id="bk1", agent_id="a1", claimed_summary="summary"
    )
    et, payload = emit.call_args[0]
    assert et == EventType.VERIFICATION_FAILED
    assert "signals" in payload
    assert payload["score"] == result.score
    assert payload["booking_id"] == "bk1"
    assert payload["agent_id"] == "a1"


# ----- Episode Writer -----


@pytest.mark.asyncio
async def test_episode_writer_stores_typed_episode():
    em = SimpleNamespace()
    em.store = AsyncMock()
    rt = SimpleNamespace(episodic_memory=em)
    writer = VerificationEpisodeWriter(runtime=rt)

    result = GroundTruthResult(
        verified=False,
        score=0.5,
        signals=["journal_present", "event_within_window"],
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="claim summary",
        completed_at=12345.0,
    )
    ok = await writer.write(result)

    assert ok is True
    em.store.assert_awaited_once()
    episode = em.store.await_args.args[0]
    assert isinstance(episode, Episode)
    assert episode.dag_summary["kind"] == "ground_truth_verification"
    assert episode.dag_summary["score"] == 0.5
    assert episode.dag_summary["booking_id"] == "bk1"
    assert episode.agent_ids == ["a1"]
    assert episode.source == MemorySource.DIRECT.value
    assert episode.importance == 7  # failed verification


@pytest.mark.asyncio
async def test_episode_writer_no_runtime_returns_false():
    writer = VerificationEpisodeWriter(runtime=None)
    result = GroundTruthResult(verified=True, score=1.0)
    ok = await writer.write(result)
    assert ok is False


@pytest.mark.asyncio
async def test_episode_writer_handles_missing_episodic_memory():
    rt = SimpleNamespace()  # no episodic_memory attribute
    writer = VerificationEpisodeWriter(runtime=rt)
    result = GroundTruthResult(verified=True, score=1.0)
    ok = await writer.write(result)
    assert ok is False
