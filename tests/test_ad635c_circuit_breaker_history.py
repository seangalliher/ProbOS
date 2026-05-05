"""AD-635c: Clinical Telemetry — Circuit Breaker State History Persistence."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.circuit_breaker import (
    BreakerState,
    CognitiveCircuitBreaker,
    CognitiveZone,
)
from probos.cognitive.circuit_breaker_history_store import CircuitBreakerHistoryStore
from probos.cognitive.clinical_telemetry import ClinicalTelemetryService
from probos.config import ClinicalTelemetryConfig


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _make_clinical_runtime(*, agents: dict[str, str] | None = None):
    """Minimal runtime stub for ClinicalTelemetryService gate tests."""
    agents = agents or {}

    class _Reg:
        def get(self, aid):
            atype = agents.get(aid)
            if atype is None:
                return None
            return SimpleNamespace(agent_type=atype)

    class _Ont:
        _MAP = {"diagnostician": "FULL", "counselor": "ORACLE"}

        def get_post_for_agent(self, agent_type):
            cl = self._MAP.get(agent_type)
            if cl is None:
                return None
            return SimpleNamespace(clearance=cl)

    return SimpleNamespace(
        registry=_Reg(),
        ontology=_Ont(),
        cognitive_journal=AsyncMock(),
        clearance_grant_store=None,
        acm=None,
    )


async def _drain_write_tasks(breaker: CognitiveCircuitBreaker) -> None:
    """Wait for all in-flight history-write tasks to finish."""
    if breaker._write_tasks:
        await asyncio.gather(*breaker._write_tasks, return_exceptions=True)


# --------------------------------------------------------------------------
# Config + store basics (tests 1-3)
# --------------------------------------------------------------------------


def test_clinical_telemetry_config_breaker_history_default_false():
    cfg = ClinicalTelemetryConfig()
    assert cfg.circuit_breaker_history_persistence_enabled is False


def test_clinical_telemetry_config_breaker_history_db_path_default():
    cfg = ClinicalTelemetryConfig()
    assert cfg.circuit_breaker_history_db_path == "data/circuit_breaker_history.db"


def test_circuit_breaker_history_store_constructor_does_not_touch_disk(tmp_path):
    db_path = str(tmp_path / "x.db")
    store = CircuitBreakerHistoryStore(db_path=db_path)
    assert os.path.exists(db_path) is False
    assert store.is_open is False
    assert store.db_path == db_path


# --------------------------------------------------------------------------
# Store CRUD (tests 4-6)
# --------------------------------------------------------------------------


def test_circuit_breaker_history_store_append_creates_file_lazily(tmp_path):
    db_path = str(tmp_path / "cbh.db")
    store = CircuitBreakerHistoryStore(db_path=db_path)

    async def _run():
        await store.append({
            "ts": 1.0,
            "agent_id": "agent-1",
            "transition_kind": "state",
            "old_value": "closed",
            "new_value": "open",
            "trip_count": 1,
            "cooldown_seconds": 900.0,
            "reason": "rumination",
        })

    asyncio.run(_run())
    assert os.path.exists(db_path) is True
    assert store.is_open is True


def test_circuit_breaker_history_store_append_persists_state_and_zone_rows(tmp_path):
    db_path = str(tmp_path / "cbh.db")
    store = CircuitBreakerHistoryStore(db_path=db_path)

    async def _run():
        await store.append({
            "ts": 100.0,
            "agent_id": "agent-1",
            "transition_kind": "state",
            "old_value": "closed",
            "new_value": "open",
            "trip_count": 1,
            "cooldown_seconds": 900.0,
            "reason": "rumination",
        })
        await store.append({
            "ts": 200.0,
            "agent_id": "agent-1",
            "transition_kind": "zone",
            "old_value": "green",
            "new_value": "amber",
            "trip_count": 0,
            "cooldown_seconds": 0.0,
        })
        return await store.recent(10)

    rows = asyncio.run(_run())
    assert len(rows) == 2
    # DESC ts order
    assert rows[0]["ts"] == 200.0
    assert rows[0]["transition_kind"] == "zone"
    assert rows[0]["old_value"] == "green"
    assert rows[0]["new_value"] == "amber"
    assert "reason" not in rows[0]
    assert rows[1]["ts"] == 100.0
    assert rows[1]["transition_kind"] == "state"
    assert rows[1]["old_value"] == "closed"
    assert rows[1]["new_value"] == "open"
    assert rows[1]["trip_count"] == 1
    assert rows[1]["cooldown_seconds"] == 900.0
    assert rows[1]["reason"] == "rumination"


def test_circuit_breaker_history_store_recent_zero_returns_empty(tmp_path):
    db_path = str(tmp_path / "cbh.db")
    store = CircuitBreakerHistoryStore(db_path=db_path)

    async def _run():
        await store.append({
            "ts": 1.0,
            "agent_id": "agent-1",
            "transition_kind": "state",
            "old_value": "closed",
            "new_value": "open",
        })
        return (
            await store.recent(0),
            await store.recent(0, agent_id="agent-1"),
        )

    all_rows, agent_rows = asyncio.run(_run())
    assert all_rows == []
    assert agent_rows == []


# --------------------------------------------------------------------------
# Breaker hooks (tests 7-11)
# --------------------------------------------------------------------------


def test_breaker_trip_records_state_transition_with_reason():
    breaker = CognitiveCircuitBreaker()
    store = AsyncMock()
    breaker.set_history_store(store)

    async def _run():
        breaker._trip("agent-1", "rumination")
        await _drain_write_tasks(breaker)

    asyncio.run(_run())
    assert store.append.call_count == 1
    entry = store.append.call_args.args[0]
    assert entry["transition_kind"] == "state"
    assert entry["old_value"] == "closed"
    assert entry["new_value"] == "open"
    assert entry["trip_count"] == 1
    assert entry["reason"] == "rumination"
    assert entry["cooldown_seconds"] > 0


def test_breaker_trip_after_half_open_records_half_open_to_open():
    breaker = CognitiveCircuitBreaker()
    breaker._get_state("agent-1").state = BreakerState.HALF_OPEN
    store = AsyncMock()
    breaker.set_history_store(store)

    async def _run():
        breaker._trip("agent-1", "rumination")
        await _drain_write_tasks(breaker)

    asyncio.run(_run())
    assert store.append.call_count == 1
    entry = store.append.call_args.args[0]
    assert entry["old_value"] == "half_open"
    assert entry["new_value"] == "open"


def test_breaker_should_allow_think_records_open_to_half_open_on_cooldown_elapse():
    breaker = CognitiveCircuitBreaker()
    state = breaker._get_state("agent-1")
    state.state = BreakerState.OPEN
    state.tripped_at = time.monotonic() - 100000.0
    state.cooldown_seconds = 1.0
    state.trip_count = 1
    store = AsyncMock()
    breaker.set_history_store(store)

    async def _run():
        allowed = breaker.should_allow_think("agent-1")
        await _drain_write_tasks(breaker)
        return allowed

    allowed = asyncio.run(_run())
    assert allowed is True
    assert store.append.call_count == 1
    entry = store.append.call_args.args[0]
    assert entry["transition_kind"] == "state"
    assert entry["old_value"] == "open"
    assert entry["new_value"] == "half_open"


def test_breaker_check_and_trip_records_half_open_to_closed_on_recovery():
    breaker = CognitiveCircuitBreaker()
    state = breaker._get_state("agent-1")
    state.state = BreakerState.HALF_OPEN
    # No events recorded → no signals fire → recovery branch hits.
    store = AsyncMock()
    breaker.set_history_store(store)

    async def _run():
        result = breaker.check_and_trip("agent-1")
        await _drain_write_tasks(breaker)
        return result

    tripped = asyncio.run(_run())
    assert tripped is False
    # Two appends are possible if zone changed; ensure the half_open→closed
    # state transition is among them.
    state_appends = [
        c.args[0] for c in store.append.call_args_list
        if c.args[0]["transition_kind"] == "state"
    ]
    assert len(state_appends) == 1
    entry = state_appends[0]
    assert entry["old_value"] == "half_open"
    assert entry["new_value"] == "closed"


def test_breaker_update_zone_records_zone_transitions():
    breaker = CognitiveCircuitBreaker()
    store = AsyncMock()
    breaker.set_history_store(store)

    async def _run():
        # Manually call _update_zone with synthetic signals to force GREEN→AMBER.
        signals = {
            "velocity_fired": False,
            "similarity_fired": False,
            "similarity_ratio": 0.5,  # > amber_similarity_ratio 0.25
            "velocity_ratio": 0.0,
            "reason": "",
        }
        breaker._update_zone("agent-1", signals, tripped=False)
        await _drain_write_tasks(breaker)

    asyncio.run(_run())
    zone_appends = [
        c.args[0] for c in store.append.call_args_list
        if c.args[0]["transition_kind"] == "zone"
    ]
    assert len(zone_appends) >= 1
    entry = zone_appends[-1]
    assert entry["old_value"] == "green"
    assert entry["new_value"] == "amber"


# --------------------------------------------------------------------------
# Failure + no-loop semantics (tests 12-13)
# --------------------------------------------------------------------------


def test_breaker_history_write_failure_does_not_block_state_transition(caplog):
    breaker = CognitiveCircuitBreaker()
    store = AsyncMock()
    store.append.side_effect = RuntimeError("disk full")
    breaker.set_history_store(store)

    async def _run():
        breaker._trip("agent-1", "rumination")
        await asyncio.gather(*breaker._write_tasks, return_exceptions=True)

    with caplog.at_level(logging.WARNING):
        asyncio.run(_run())

    assert breaker._get_state("agent-1").state == BreakerState.OPEN
    assert any(
        "AD-635c: circuit-breaker history write-through failed" in rec.message
        for rec in caplog.records
    )


def test_breaker_history_no_running_loop_skips_write_silently(caplog):
    breaker = CognitiveCircuitBreaker()
    store = AsyncMock()
    breaker.set_history_store(store)

    # No event loop running here.
    with caplog.at_level(logging.DEBUG):
        breaker._trip("agent-1", "rumination")

    assert len(breaker._write_tasks) == 0
    assert breaker._get_state("agent-1").state == BreakerState.OPEN
    # Append never reached.
    store.append.assert_not_called()


# --------------------------------------------------------------------------
# Clinical query method (tests 14-17)
# --------------------------------------------------------------------------


def test_query_circuit_breaker_history_denied_for_non_clinical_role():
    rt = _make_clinical_runtime(agents={"engineer-1": "engineer"})
    store = AsyncMock()
    svc = ClinicalTelemetryService(rt, circuit_breaker_history_store=store)

    async def _run():
        return await svc.query_circuit_breaker_history(
            requester_agent_id="engineer-1",
        )

    rows = asyncio.run(_run())
    assert rows == []
    assert len(svc.audit_log) == 1
    entry = svc.audit_log[0]
    assert entry["granted"] is False
    assert entry["query_type"] == "circuit_breaker_history"


def test_query_circuit_breaker_history_returns_rows_for_clinical_role():
    rt = _make_clinical_runtime(agents={"echo-1": "counselor"})
    store = AsyncMock()
    expected_rows = [
        {
            "transition_kind": "state",
            "old_value": "closed",
            "new_value": "open",
            "agent_id": "khan-1",
            "ts": 100.0,
            "trip_count": 1,
            "cooldown_seconds": 900.0,
        }
    ]
    store.recent.return_value = expected_rows
    svc = ClinicalTelemetryService(rt, circuit_breaker_history_store=store)

    async def _run():
        return await svc.query_circuit_breaker_history(
            requester_agent_id="echo-1",
            target_agent_id="khan-1",
            limit=10,
        )

    rows = asyncio.run(_run())
    assert rows == expected_rows
    store.recent.assert_called_once_with(10, agent_id="khan-1")
    assert len(svc.audit_log) == 1
    entry = svc.audit_log[0]
    assert entry["granted"] is True
    assert entry["target_agent_id"] == "khan-1"
    assert entry["query_type"] == "circuit_breaker_history"


def test_query_circuit_breaker_history_returns_empty_when_store_is_none():
    rt = _make_clinical_runtime(agents={"echo-1": "counselor"})
    svc = ClinicalTelemetryService(rt, circuit_breaker_history_store=None)

    async def _run():
        return await svc.query_circuit_breaker_history(
            requester_agent_id="echo-1",
        )

    rows = asyncio.run(_run())
    assert rows == []
    assert len(svc.audit_log) == 1
    entry = svc.audit_log[0]
    assert entry["granted"] is True
    assert entry["result_count"] == 0


def test_query_circuit_breaker_history_logs_warning_and_returns_empty_on_store_failure(caplog):
    rt = _make_clinical_runtime(agents={"echo-1": "counselor"})
    store = AsyncMock()
    store.recent.side_effect = RuntimeError("disk")
    svc = ClinicalTelemetryService(rt, circuit_breaker_history_store=store)

    async def _run():
        return await svc.query_circuit_breaker_history(
            requester_agent_id="echo-1",
        )

    with caplog.at_level(logging.WARNING):
        rows = asyncio.run(_run())

    assert rows == []
    assert any(
        "AD-635c: circuit_breaker_history query failed" in rec.message
        for rec in caplog.records
    )
    assert len(svc.audit_log) == 1
    entry = svc.audit_log[0]
    assert entry["granted"] is True
    assert entry["result_count"] == 0
