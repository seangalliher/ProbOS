"""Tests for AD-664: EventLog Diagnostic Infrastructure."""

from __future__ import annotations

import pytest

from probos.substrate.event_log import EventLog


@pytest.fixture
async def event_log(tmp_path):
    el = EventLog(db_path=tmp_path / "test_events.db")
    await el.start()
    yield el
    await el.stop()


# --- Schema migration ---

@pytest.mark.asyncio
async def test_eventlog_new_schema_has_columns(event_log):
    async with event_log._db.execute("PRAGMA table_info(events)") as cursor:
        columns = {row[1] async for row in cursor}
    assert "correlation_id" in columns
    assert "parent_event_id" in columns
    assert "data" in columns


@pytest.mark.asyncio
async def test_eventlog_migration_idempotent(tmp_path):
    el = EventLog(db_path=tmp_path / "test.db")
    await el.start()
    await el.start()  # second call must not error
    async with el._db.execute("PRAGMA table_info(events)") as cursor:
        columns = {row[1] async for row in cursor}
    assert "correlation_id" in columns
    await el.stop()


@pytest.mark.asyncio
async def test_eventlog_migration_adds_missing_columns(tmp_path):
    """Simulate old schema, then migrate."""
    import aiosqlite
    db = await aiosqlite.connect(str(tmp_path / "old.db"))
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS events (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT    NOT NULL,
            category  TEXT    NOT NULL,
            event     TEXT    NOT NULL,
            agent_id  TEXT,
            agent_type TEXT,
            pool      TEXT,
            detail    TEXT
        );
    """)
    await db.commit()
    await db.close()

    el = EventLog(db_path=tmp_path / "old.db")
    await el.start()
    async with el._db.execute("PRAGMA table_info(events)") as cursor:
        columns = {row[1] async for row in cursor}
    assert "correlation_id" in columns
    assert "parent_event_id" in columns
    assert "data" in columns
    await el.stop()


# --- Structured logging ---

@pytest.mark.asyncio
async def test_log_with_structured_data(event_log):
    await event_log.log(
        category="emergent",
        event="consolidation_anomaly",
        data={"weights_strengthened": 42, "ratio": 2.1},
    )
    rows = await event_log.query(category="emergent")
    assert len(rows) == 1
    assert rows[0]["data"] == {"weights_strengthened": 42, "ratio": 2.1}
    assert isinstance(rows[0]["data"], dict)


@pytest.mark.asyncio
async def test_log_with_correlation_id(event_log):
    await event_log.log(
        category="emergent",
        event="test",
        correlation_id="dream-abc123",
    )
    rows = await event_log.query(category="emergent")
    assert rows[0]["correlation_id"] == "dream-abc123"


@pytest.mark.asyncio
async def test_log_returns_row_id(event_log):
    row_id = await event_log.log(category="test", event="ping")
    assert isinstance(row_id, int)
    assert row_id > 0


@pytest.mark.asyncio
async def test_log_parent_event_id_chain(event_log):
    id_a = await event_log.log(category="test", event="root")
    id_b = await event_log.log(category="test", event="child", parent_event_id=id_a)
    rows = await event_log.query(category="test", limit=10)
    child = [r for r in rows if r["event"] == "child"][0]
    assert child["parent_event_id"] == id_a


# --- Query methods ---

@pytest.mark.asyncio
async def test_query_returns_new_columns(event_log):
    await event_log.log(
        category="test", event="x",
        correlation_id="c1", parent_event_id=None,
        data={"key": "val"},
    )
    rows = await event_log.query(category="test")
    assert "correlation_id" in rows[0]
    assert "parent_event_id" in rows[0]
    assert "data" in rows[0]


@pytest.mark.asyncio
async def test_query_structured_by_correlation(event_log):
    await event_log.log(category="e", event="a", correlation_id="chain-1")
    await event_log.log(category="e", event="b", correlation_id="chain-1")
    await event_log.log(category="e", event="c", correlation_id="chain-2")
    rows = await event_log.query_structured(correlation_id="chain-1")
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_query_structured_by_event_name(event_log):
    await event_log.log(category="emergent", event="consolidation_anomaly")
    await event_log.log(category="emergent", event="emergence_trends")
    rows = await event_log.query_structured(event="consolidation_anomaly")
    assert len(rows) == 1
    assert rows[0]["event"] == "consolidation_anomaly"


@pytest.mark.asyncio
async def test_query_structured_combined_filters(event_log):
    await event_log.log(category="emergent", event="consolidation_anomaly")
    await event_log.log(category="mesh", event="consolidation_anomaly")
    await event_log.log(category="emergent", event="other")
    rows = await event_log.query_structured(
        category="emergent", event="consolidation_anomaly",
    )
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_event_chain(event_log):
    id_a = await event_log.log(category="test", event="root")
    id_b = await event_log.log(category="test", event="mid", parent_event_id=id_a)
    id_c = await event_log.log(category="test", event="leaf", parent_event_id=id_b)
    chain = await event_log.get_event_chain(id_c)
    assert len(chain) == 3
    assert chain[0]["event"] == "root"   # root first
    assert chain[2]["event"] == "leaf"   # leaf last


# --- Backward compatibility ---

@pytest.mark.asyncio
async def test_log_without_new_params_still_works(event_log):
    row_id = await event_log.log(
        category="system", event="pool_created", pool="test",
    )
    assert isinstance(row_id, int)
    rows = await event_log.query(category="system")
    assert rows[0]["correlation_id"] is None
    assert rows[0]["parent_event_id"] is None
    assert rows[0]["data"] is None


@pytest.mark.asyncio
async def test_query_old_shape_preserved(event_log):
    await event_log.log(
        category="lifecycle", event="agent_wired",
        agent_id="a1", agent_type="test", pool="p1", detail="test detail",
    )
    rows = await event_log.query(category="lifecycle")
    r = rows[0]
    for key in ("id", "timestamp", "category", "event", "agent_id",
                "agent_type", "pool", "detail",
                "correlation_id", "parent_event_id", "data"):
        assert key in r, f"Missing key: {key}"


# --- Engineering capability ---

def test_engineering_agent_has_diagnostic_capability():
    from probos.cognitive.engineering_officer import EngineeringAgent
    caps = [c.can for c in EngineeringAgent.default_capabilities]
    assert "eventlog_diagnostic_query" in caps


def test_engineering_agent_has_diagnostic_intent():
    from probos.cognitive.engineering_officer import EngineeringAgent
    intents = [i.name for i in EngineeringAgent.intent_descriptors]
    assert "eventlog_diagnostic_query" in intents


def test_engineering_agent_handled_intents():
    from probos.cognitive.engineering_officer import EngineeringAgent
    assert "eventlog_diagnostic_query" in EngineeringAgent._handled_intents
