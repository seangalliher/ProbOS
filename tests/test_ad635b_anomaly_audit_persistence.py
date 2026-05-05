"""AD-635b v1: Clinical Telemetry — Anomaly Audit Trail Persistence."""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.clinical_audit_store import ClinicalAuditStore
from probos.cognitive.clinical_telemetry import ClinicalTelemetryService
from probos.config import ClinicalTelemetryConfig, SystemConfig
from probos.startup.finalize import _wire_clinical_telemetry


# --------------------------------------------------------------------------
# Helpers (mirror tests/test_ad635_clinical_telemetry.py:25-78)
# --------------------------------------------------------------------------

def _make_runtime(
    *,
    agents: dict[str, str] | None = None,
    journal_traces: list[dict] | None = None,
    detector_dreams: list[dict] | None = None,
):
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

    journal = AsyncMock()
    journal.get_recent_chain_traces = AsyncMock(
        return_value=list(journal_traces or [])
    )

    runtime = SimpleNamespace(
        registry=_Reg(),
        ontology=_Ont(),
        cognitive_journal=journal,
        clearance_grant_store=None,
        acm=None,
    )
    det = SimpleNamespace(
        recent_dreams=lambda limit=20: list(detector_dreams or [])[-limit:],
    )
    runtime._emergent_detector = det
    return runtime


# --------------------------------------------------------------------------
# Section 0: ClinicalTelemetryConfig defaults
# --------------------------------------------------------------------------

def test_clinical_telemetry_config_audit_persistence_default_false():
    assert ClinicalTelemetryConfig().audit_persistence_enabled is False


def test_clinical_telemetry_config_audit_db_path_default():
    assert ClinicalTelemetryConfig().audit_db_path == "data/clinical_audit.db"


# --------------------------------------------------------------------------
# Section 1: ClinicalAuditStore
# --------------------------------------------------------------------------

def test_clinical_audit_store_constructor_does_not_touch_disk(tmp_path):
    db_path = str(tmp_path / "x.db")
    store = ClinicalAuditStore(db_path=db_path)
    assert os.path.exists(db_path) is False
    assert store.is_open is False
    assert store.db_path == db_path


def test_clinical_audit_store_append_creates_file_lazily(tmp_path):
    db_path = str(tmp_path / "audit.db")
    store = ClinicalAuditStore(db_path=db_path)

    async def _drive():
        await store.append({
            "ts": 1.0,
            "requester_agent_id": "a",
            "query_type": "dream_history",
            "granted": True,
            "result_count": 0,
        })

    asyncio.run(_drive())
    assert os.path.exists(db_path) is True
    assert store.is_open is True


def test_clinical_audit_store_append_persists_row(tmp_path):
    db_path = str(tmp_path / "audit.db")
    store = ClinicalAuditStore(db_path=db_path)
    entry = {
        "ts": 1234.5,
        "requester_agent_id": "echo-1",
        "query_type": "chain_traces",
        "granted": True,
        "result_count": 3,
        "target_agent_id": "agent-x",
    }

    async def _drive():
        await store.append(entry)
        return await store.recent(10)

    rows = asyncio.run(_drive())
    assert len(rows) == 1
    row = rows[0]
    assert row["ts"] == 1234.5
    assert row["requester_agent_id"] == "echo-1"
    assert row["query_type"] == "chain_traces"
    assert row["granted"] is True
    assert row["result_count"] == 3
    assert row["target_agent_id"] == "agent-x"


def test_clinical_audit_store_recent_zero_returns_empty(tmp_path):
    db_path = str(tmp_path / "audit.db")
    store = ClinicalAuditStore(db_path=db_path)

    async def _drive():
        await store.append({
            "ts": 1.0,
            "requester_agent_id": "a",
            "query_type": "dream_history",
            "granted": True,
            "result_count": 0,
        })
        return await store.recent(0)

    assert asyncio.run(_drive()) == []


def test_clinical_audit_store_schema_columns(tmp_path):
    db_path = str(tmp_path / "audit.db")
    store = ClinicalAuditStore(db_path=db_path)

    async def _drive():
        await store.append({
            "ts": 1.0,
            "requester_agent_id": "a",
            "query_type": "dream_history",
            "granted": True,
            "result_count": 0,
        })

    asyncio.run(_drive())
    conn = sqlite3.connect(db_path)
    try:
        rows = list(conn.execute("PRAGMA table_info(clinical_audit)"))
    finally:
        conn.close()
    by_name = {r[1]: r[2] for r in rows}
    assert "id" in by_name
    assert "ts" in by_name
    assert "requester_agent_id" in by_name
    assert "query_type" in by_name
    assert "granted" in by_name
    assert "result_count" in by_name
    assert "target_agent_id" in by_name
    assert by_name["granted"] == "INTEGER"


def test_clinical_audit_store_index_exists(tmp_path):
    db_path = str(tmp_path / "audit.db")
    store = ClinicalAuditStore(db_path=db_path)

    async def _drive():
        await store.append({
            "ts": 1.0,
            "requester_agent_id": "a",
            "query_type": "dream_history",
            "granted": True,
            "result_count": 0,
        })

    asyncio.run(_drive())
    conn = sqlite3.connect(db_path)
    try:
        idx_names = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='clinical_audit'"
            )
        ]
    finally:
        conn.close()
    assert "idx_clinical_audit_ts" in idx_names


def test_clinical_audit_store_connection_factory_injected():
    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock(return_value=MagicMock())
    fake_conn.commit = AsyncMock(return_value=None)
    factory = AsyncMock(return_value=fake_conn)
    store = ClinicalAuditStore(db_path=":memory:", connection_factory=factory)
    entry = {
        "ts": 1.0,
        "requester_agent_id": "a",
        "query_type": "dream_history",
        "granted": True,
        "result_count": 0,
    }

    async def _drive():
        await store.append(entry)
        await store.append(entry)

    asyncio.run(_drive())
    assert factory.await_count == 1


# --------------------------------------------------------------------------
# Section 2: ClinicalTelemetryService write-through behavior
# --------------------------------------------------------------------------

def test_service_default_no_audit_store_preserves_ring_only():
    rt = _make_runtime(
        agents={"echo-1": "counselor"},
        detector_dreams=[{"id": "d1"}],
    )
    svc = ClinicalTelemetryService(rt, audit_max_entries=5)
    assert svc._audit_store is None

    async def _drive():
        await svc.query_dream_history(requester_agent_id="echo-1")

    asyncio.run(_drive())
    assert len(svc._write_tasks) == 0
    assert len(svc.audit_log) == 1


def test_service_with_audit_store_writes_through_on_granted_query():
    audit_store = AsyncMock()
    audit_store.append = AsyncMock(return_value=None)
    rt = _make_runtime(
        agents={"echo-1": "counselor"},
        detector_dreams=[{"id": "d1"}],
    )
    svc = ClinicalTelemetryService(
        rt, audit_max_entries=10, audit_store=audit_store
    )

    async def _drive():
        await svc.query_dream_history(requester_agent_id="echo-1")
        if svc._write_tasks:
            await asyncio.gather(*svc._write_tasks, return_exceptions=True)

    asyncio.run(_drive())
    assert audit_store.append.await_count == 1
    appended = audit_store.append.await_args[0][0]
    assert appended["requester_agent_id"] == "echo-1"
    assert appended["query_type"] == "dream_history"
    assert appended["granted"] is True
    assert "ts" in appended
    assert "result_count" in appended
    assert len(svc.audit_log) == 1


def test_service_write_through_failure_keeps_ring_intact_and_logs_warning(caplog):
    audit_store = AsyncMock()
    audit_store.append = AsyncMock(side_effect=RuntimeError("disk full"))
    rt = _make_runtime(
        agents={"echo-1": "counselor"},
        detector_dreams=[{"id": "d1"}],
    )
    svc = ClinicalTelemetryService(
        rt, audit_max_entries=10, audit_store=audit_store
    )

    async def _drive():
        await svc.query_dream_history(requester_agent_id="echo-1")
        if svc._write_tasks:
            await asyncio.gather(*svc._write_tasks, return_exceptions=True)

    with caplog.at_level(logging.WARNING):
        asyncio.run(_drive())  # MUST NOT raise

    assert len(svc.audit_log) == 1
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING
        and "AD-635b: audit write-through failed" in r.getMessage()
    ]
    assert len(warnings) == 1


# --------------------------------------------------------------------------
# Section 3: _wire_clinical_telemetry double-gating
# --------------------------------------------------------------------------

def test_finalize_no_store_when_persistence_disabled():
    cfg = SystemConfig()
    cfg.clinical_telemetry = ClinicalTelemetryConfig(
        enabled=True, audit_persistence_enabled=False
    )
    runtime = SimpleNamespace()
    wired = _wire_clinical_telemetry(runtime=runtime, config=cfg)
    assert wired is True
    assert runtime.clinical_telemetry._audit_store is None


def test_finalize_constructs_store_when_both_flags_true(tmp_path):
    db_path = str(tmp_path / "test.db")
    cfg = SystemConfig()
    cfg.clinical_telemetry = ClinicalTelemetryConfig(
        enabled=True,
        audit_persistence_enabled=True,
        audit_db_path=db_path,
    )
    runtime = SimpleNamespace()
    wired = _wire_clinical_telemetry(runtime=runtime, config=cfg)
    assert wired is True
    store = runtime.clinical_telemetry._audit_store
    assert store is not None
    assert store.db_path == db_path
    # __init__ must not have touched disk.
    assert os.path.exists(db_path) is False


def test_clinical_audit_store_append_records_granted_as_integer_zero_or_one(tmp_path):
    db_path = str(tmp_path / "audit.db")
    store = ClinicalAuditStore(db_path=db_path)

    async def _drive():
        await store.append({
            "ts": 1.0,
            "requester_agent_id": "a",
            "query_type": "dream_history",
            "granted": False,
            "result_count": 0,
        })
        await store.append({
            "ts": 2.0,
            "requester_agent_id": "b",
            "query_type": "dream_history",
            "granted": True,
            "result_count": 0,
        })

    asyncio.run(_drive())
    conn = sqlite3.connect(db_path)
    try:
        rows = list(
            conn.execute(
                "SELECT requester_agent_id, granted FROM clinical_audit ORDER BY ts ASC"
            )
        )
    finally:
        conn.close()
    assert rows == [("a", 0), ("b", 1)]
