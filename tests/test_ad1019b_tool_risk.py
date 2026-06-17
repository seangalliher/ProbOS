"""AD-1019b: Tool risk classification tests.

Tests the ``McpToolRisk`` enum, ``resolve_tool_risk`` pure function, and
``McpToolRiskStore`` persistence layer.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1019b_tool_risk.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

import pytest

from probos.integrations.mcp_bridge.risk import (
    McpToolRisk,
    McpToolRiskStore,
    resolve_tool_risk,
)


# --------------------------------------------------------------------------- #
# McpToolRisk enum
# --------------------------------------------------------------------------- #


def test_enum_values() -> None:
    assert McpToolRisk.OPEN.value == "open"
    assert McpToolRisk.CONFIRM.value == "confirm"
    assert McpToolRisk.CONSENSUS.value == "consensus"


def test_enum_names() -> None:
    assert McpToolRisk.OPEN.name == "OPEN"
    assert McpToolRisk.CONFIRM.name == "CONFIRM"
    assert McpToolRisk.CONSENSUS.name == "CONSENSUS"


def test_enum_iteration_order() -> None:
    # str Enum iteration order is definition order
    levels = list(McpToolRisk)
    assert levels == [McpToolRisk.OPEN, McpToolRisk.CONFIRM, McpToolRisk.CONSENSUS]


# --------------------------------------------------------------------------- #
# resolve_tool_risk (pure function)
# --------------------------------------------------------------------------- #


def test_resolve_tool_override_wins() -> None:
    """Tool-specific override beats server default."""
    result = resolve_tool_risk(
        server_default=McpToolRisk.OPEN,
        tool_override=McpToolRisk.CONSENSUS,
    )
    assert result == McpToolRisk.CONSENSUS


def test_resolve_falls_back_to_server_default() -> None:
    """No tool override → use server_default."""
    result = resolve_tool_risk(
        server_default=McpToolRisk.CONFIRM,
        tool_override=None,
    )
    assert result == McpToolRisk.CONFIRM


def test_resolve_open_override_respected() -> None:
    """OPEN override is NOT ignored (it's a valid override)."""
    result = resolve_tool_risk(
        server_default=McpToolRisk.CONSENSUS,
        tool_override=McpToolRisk.OPEN,
    )
    assert result == McpToolRisk.OPEN


# --------------------------------------------------------------------------- #
# McpToolRiskStore (persistence)
# --------------------------------------------------------------------------- #


@pytest.fixture
def store() -> McpToolRiskStore:
    return McpToolRiskStore(db_path="")


async def _start(store: McpToolRiskStore) -> McpToolRiskStore:
    await store.start()
    return store


@pytest.mark.asyncio
async def test_store_set_and_get(store: McpToolRiskStore) -> None:
    store = await _start(store)
    try:
        # Initial set
        await store.set_risk("system", "run_command", McpToolRisk.CONSENSUS)
        result = store.get_risk_sync("system", "run_command")
        assert result == McpToolRisk.CONSENSUS
        # Update (upsert)
        await store.set_risk("system", "run_command", McpToolRisk.CONFIRM)
        result = store.get_risk_sync("system", "run_command")
        assert result == McpToolRisk.CONFIRM
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_store_get_unknown_returns_none(store: McpToolRiskStore) -> None:
    store = await _start(store)
    try:
        result = store.get_risk_sync("unknown", "unknown")
        assert result is None
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_store_clear(store: McpToolRiskStore) -> None:
    store = await _start(store)
    try:
        await store.set_risk("system", "run_command", McpToolRisk.CONSENSUS)
        existed = await store.clear_risk("system", "run_command")
        assert existed is True
        result = store.get_risk_sync("system", "run_command")
        assert result is None
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_store_clear_unknown_returns_false(store: McpToolRiskStore) -> None:
    store = await _start(store)
    try:
        existed = await store.clear_risk("unknown", "unknown")
        assert existed is False
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_store_list_sync(store: McpToolRiskStore) -> None:
    store = await _start(store)
    try:
        await store.set_risk("system", "run_command", McpToolRisk.CONSENSUS)
        await store.set_risk("system", "read_file", McpToolRisk.CONFIRM)
        await store.set_risk("weather", "get_forecast", McpToolRisk.OPEN)
        all_risks = store.list_sync()
        assert len(all_risks) == 3
        # Convert to set for order-independent comparison
        keys = {(r["server_id"], r["tool_name"]) for r in all_risks}
        assert keys == {
            ("system", "run_command"),
            ("system", "read_file"),
            ("weather", "get_forecast"),
        }
    finally:
        await store.stop()


# --------------------------------------------------------------------------- #
# Integration: resolve_tool_risk with store data
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_resolve_with_store_data(store: McpToolRiskStore) -> None:
    store = await _start(store)
    try:
        await store.set_risk("system", "run_command", McpToolRisk.CONSENSUS)
        await store.set_risk("system", "read_file", McpToolRisk.CONFIRM)
        # Tool with override
        run = resolve_tool_risk(
            server_default=McpToolRisk.OPEN,
            tool_override=store.get_risk_sync("system", "run_command"),
        )
        assert run == McpToolRisk.CONSENSUS
        # Tool without override → fallback to server default
        unknown = resolve_tool_risk(
            server_default=McpToolRisk.CONFIRM,
            tool_override=store.get_risk_sync("system", "list_dir"),
        )
        assert unknown == McpToolRisk.CONFIRM
    finally:
        await store.stop()


# --------------------------------------------------------------------------- #
# Real-DB persistence (tmp_path) — exercises the SQLite path that db_path=""
# tests bypass: schema, upsert INSERT, DELETE, _load_cache (incl. the bad-value
# ValueError guard). BF-287: cache-only tests can't catch a column misalignment.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_real_db_roundtrip_reloads_overrides(tmp_path) -> None:
    """Overrides persist and a fresh store reloads them via _load_cache."""
    db = str(tmp_path / "risk.db")
    store = McpToolRiskStore(db_path=db)
    await store.start()
    await store.set_risk("system", "run_command", McpToolRisk.CONSENSUS)
    await store.set_risk("weather", "get_forecast", McpToolRisk.CONFIRM)
    await store.stop()

    store2 = McpToolRiskStore(db_path=db)
    await store2.start()
    try:
        assert store2.get_risk_sync("system", "run_command") == McpToolRisk.CONSENSUS
        assert store2.get_risk_sync("weather", "get_forecast") == McpToolRisk.CONFIRM
    finally:
        await store2.stop()


@pytest.mark.asyncio
async def test_real_db_upsert_replaces_row(tmp_path) -> None:
    """set_risk on an existing (server, tool) upserts (no duplicate row)."""
    db = str(tmp_path / "risk.db")
    store = McpToolRiskStore(db_path=db)
    await store.start()
    await store.set_risk("system", "run_command", McpToolRisk.CONSENSUS)
    await store.set_risk("system", "run_command", McpToolRisk.CONFIRM)  # upsert
    await store.stop()

    store2 = McpToolRiskStore(db_path=db)
    await store2.start()
    try:
        assert store2.get_risk_sync("system", "run_command") == McpToolRisk.CONFIRM
        assert len(store2.list_sync()) == 1  # upsert, not a second row
    finally:
        await store2.stop()


@pytest.mark.asyncio
async def test_real_db_clear_persists(tmp_path) -> None:
    """clear_risk hard-deletes the row; a reload does not resurrect it."""
    db = str(tmp_path / "risk.db")
    store = McpToolRiskStore(db_path=db)
    await store.start()
    await store.set_risk("system", "run_command", McpToolRisk.CONSENSUS)
    assert await store.clear_risk("system", "run_command") is True
    await store.stop()

    store2 = McpToolRiskStore(db_path=db)
    await store2.start()
    try:
        assert store2.get_risk_sync("system", "run_command") is None
    finally:
        await store2.stop()


@pytest.mark.asyncio
async def test_real_db_load_cache_skips_bad_value(tmp_path) -> None:
    """_load_cache logs-and-ignores an unparseable risk string (defensive guard)
    while keeping the valid rows. Only reachable with a real DB."""
    db = str(tmp_path / "risk.db")
    store = McpToolRiskStore(db_path=db)
    await store.start()
    await store.set_risk("system", "run_command", McpToolRisk.CONSENSUS)
    # Inject a corrupt row directly, then force a cache reload.
    await store._db.execute(
        "INSERT INTO mcp_tool_risk (id, server_id, tool_name, risk, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("bad-id", "weather", "get_forecast", "banana", 1.0),
    )
    await store._db.commit()
    await store._load_cache()
    try:
        # Valid row survived; corrupt row was dropped (not raised).
        assert store.get_risk_sync("system", "run_command") == McpToolRisk.CONSENSUS
        assert store.get_risk_sync("weather", "get_forecast") is None
    finally:
        await store.stop()
