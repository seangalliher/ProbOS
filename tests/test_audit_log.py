"""AD-754: assistant audit log tests."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from probos.security.audit_log import AuditLog


@pytest.mark.asyncio
async def test_log_intent_and_query_returns_entry(tmp_path) -> None:
    log = AuditLog(str(tmp_path / "assistant_audit.db"), retention_days=90)

    await log.log_intent("intent_executed", "resource://alpha", "Yeo", True)
    rows = await log.query(days_back=7)

    assert len(rows) == 1
    assert rows[0].action == "intent_executed"
    assert rows[0].actor == "Yeo"


@pytest.mark.asyncio
async def test_log_intent_redacts_pii_in_resource(tmp_path) -> None:
    log = AuditLog(str(tmp_path / "assistant_audit.db"), retention_days=90)

    await log.log_intent(
        "intent_executed",
        "https://example.com/report?docid=abc user=alice@example.com",
        "Yeo",
        True,
    )
    rows = await log.query(days_back=7)

    assert rows
    assert "alice@example.com" not in rows[0].resource
    assert "docid=abc" not in rows[0].resource


@pytest.mark.asyncio
async def test_retention_policy_prunes_entries_older_than_cutoff(tmp_path) -> None:
    db_path = tmp_path / "assistant_audit.db"
    log = AuditLog(str(db_path), retention_days=1)

    await log.log_intent("intent_executed", "resource://stale", "Yeo", True)

    stale_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()

    def _age_row() -> None:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE assistant_audit_log SET timestamp = ? WHERE resource = ?",
                (stale_time, "resource://stale"),
            )
            conn.commit()
        finally:
            conn.close()

    await asyncio.to_thread(_age_row)

    await log.log_intent("intent_executed", "resource://fresh", "Yeo", True)
    rows = await log.query(days_back=30)

    resources = {row.resource for row in rows}
    assert "resource://fresh" in resources
    assert "resource://stale" not in resources
