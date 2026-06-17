"""AD-1019b: DepartmentToolGrantStore tests (the "department locker" tier).

The store mirrors ``ToolPermissionStore`` but is keyed by department name
(e.g. "science", "engineering", "counseling") instead of agent_id.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1019b_department_grants.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

import pytest

from probos.integrations.mcp_bridge.access import mcp_tool_tool_id, mcp_server_tool_id
from probos.integrations.mcp_bridge.department_grants import DepartmentToolGrantStore
from probos.tools.protocol import ToolPermission


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def store() -> DepartmentToolGrantStore:
    """In-memory store (db_path="")."""
    return DepartmentToolGrantStore(db_path="")


async def _start(store: DepartmentToolGrantStore) -> DepartmentToolGrantStore:
    await store.start()
    return store


# --------------------------------------------------------------------------- #
# Basic CRUD
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_issue_tool_grant_happy_path(store: DepartmentToolGrantStore) -> None:
    store = await _start(store)
    try:
        tool_id = mcp_tool_tool_id("weather", "get_forecast")
        grant = await store.issue_grant(
            department="science",
            tool_id=tool_id,
            permission=ToolPermission.READ,
            is_restriction=False,
            reason="science needs weather data",
            issued_by="captain",
        )
        assert grant.agent_id == "science"  # department stored in agent_id field
        assert grant.tool_id == tool_id
        assert grant.permission == ToolPermission.READ
        assert grant.is_restriction is False
        assert grant.issued_by == "captain"
        assert grant.revoked is False
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_issue_tool_restriction(store: DepartmentToolGrantStore) -> None:
    store = await _start(store)
    try:
        tool_id = mcp_tool_tool_id("system", "run_command")
        grant = await store.issue_grant(
            department="engineering",
            tool_id=tool_id,
            permission=ToolPermission.NONE,
            is_restriction=True,
            reason="dangerous tool",
            issued_by="captain",
        )
        assert grant.is_restriction is True
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_server_level_grant(store: DepartmentToolGrantStore) -> None:
    store = await _start(store)
    try:
        server_id = mcp_server_tool_id("monitoring")
        grant = await store.issue_grant(
            department="ops",
            tool_id=server_id,
            permission=ToolPermission.READ,
            is_restriction=False,
            issued_by="captain",
        )
        assert grant.tool_id == server_id
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_revoke_soft_deletes(store: DepartmentToolGrantStore) -> None:
    store = await _start(store)
    try:
        tool_id = mcp_tool_tool_id("weather", "get_forecast")
        grant = await store.issue_grant(
            department="science",
            tool_id=tool_id,
            permission=ToolPermission.READ,
            issued_by="captain",
        )
        success = await store.revoke_grant(grant.id)
        assert success is True
        # Active grants exclude revoked
        active = store.get_active_grants_sync("science")
        assert len(active) == 0
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_list_by_department(store: DepartmentToolGrantStore) -> None:
    store = await _start(store)
    try:
        await store.issue_grant(
            department="science",
            tool_id=mcp_tool_tool_id("weather", "get_forecast"),
            permission=ToolPermission.READ,
            issued_by="captain",
        )
        await store.issue_grant(
            department="science",
            tool_id=mcp_tool_tool_id("weather", "get_humidity"),
            permission=ToolPermission.READ,
            issued_by="captain",
        )
        await store.issue_grant(
            department="engineering",
            tool_id=mcp_tool_tool_id("build", "compile"),
            permission=ToolPermission.WRITE,
            issued_by="captain",
        )
        science = store.get_active_grants_sync("science")
        assert len(science) == 2
        eng = store.get_active_grants_sync("engineering")
        assert len(eng) == 1
    finally:
        await store.stop()


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_unknown_department_returns_empty(store: DepartmentToolGrantStore) -> None:
    store = await _start(store)
    try:
        active = store.get_active_grants_sync("nonexistent")
        assert active == []
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_revoke_unknown_grant_cache_only_behavior(store: DepartmentToolGrantStore) -> None:
    """Cache-only mode (db_path='') can't verify if grant existed; returns True."""
    store = await _start(store)
    try:
        # In cache-only mode, revoke_grant always returns True because
        # it can't query the DB to verify existence. This is acceptable
        # for test fixtures; production uses db_path.
        result = await store.revoke_grant("00000000-0000-0000-0000-000000000000")
        assert result is True  # Cache-only mode returns True
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_duplicate_grant_creates_new_row(store: DepartmentToolGrantStore) -> None:
    store = await _start(store)
    try:
        tool_id = mcp_tool_tool_id("weather", "get_forecast")
        g1 = await store.issue_grant(
            department="science",
            tool_id=tool_id,
            permission=ToolPermission.READ,
            issued_by="captain",
        )
        g2 = await store.issue_grant(
            department="science",
            tool_id=tool_id,
            permission=ToolPermission.READ,
            issued_by="xo",  # Different approver
        )
        # Both exist as separate grants (append-only audit model)
        assert g1.id != g2.id
        active = store.get_active_grants_sync("science")
        # Both are active (soft-revoke doesn't dedupe)
        assert len(active) == 2
    finally:
        await store.stop()


# --------------------------------------------------------------------------- #
# Cache coherence (sync accessor accuracy after mutations)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_sync_cache_coherence(store: DepartmentToolGrantStore) -> None:
    store = await _start(store)
    try:
        # Before any grant
        assert store.get_active_grants_sync("science") == []
        # After grant
        tool_id = mcp_tool_tool_id("weather", "get_forecast")
        grant = await store.issue_grant(
            department="science",
            tool_id=tool_id,
            permission=ToolPermission.READ,
            issued_by="captain",
        )
        active = store.get_active_grants_sync("science")
        assert len(active) == 1
        # After revoke
        await store.revoke_grant(grant.id)
        assert store.get_active_grants_sync("science") == []
    finally:
        await store.stop()


# --------------------------------------------------------------------------- #
# Real-DB persistence (tmp_path) — exercises the SQLite path that db_path=""
# tests bypass entirely: schema, INSERT column alignment, _load_cache,
# _row_to_grant field mapping, and the revoke rowcount branch (BF-287 lesson).
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_real_db_roundtrip_reloads_all_fields(tmp_path) -> None:
    """A grant persists and a fresh store reloads it via _load_cache/_row_to_grant
    with every field intact (proves the INSERT↔column↔_row_to_grant alignment)."""
    db = str(tmp_path / "dtg.db")
    tool_id = mcp_tool_tool_id("weather", "get_forecast")
    store = DepartmentToolGrantStore(db_path=db)
    await store.start()
    issued = await store.issue_grant(
        department="science",
        tool_id=tool_id,
        permission=ToolPermission.READ,
        is_restriction=False,
        reason="needs weather",
        issued_by="captain",
    )
    await store.stop()

    # A new store over the same DB loads its cache from disk.
    store2 = DepartmentToolGrantStore(db_path=db)
    await store2.start()
    try:
        active = store2.get_active_grants_sync("science")
        assert len(active) == 1
        g = active[0]
        assert g.id == issued.id
        assert g.agent_id == "science"  # department carried in agent_id
        assert g.tool_id == tool_id
        assert g.permission == ToolPermission.READ
        assert g.is_restriction is False
        assert g.reason == "needs weather"
        assert g.issued_by == "captain"
        assert g.revoked is False
    finally:
        await store2.stop()


@pytest.mark.asyncio
async def test_real_db_revoke_returns_true_then_false(tmp_path) -> None:
    """The production revoke contract (only reachable with a real DB): True for an
    existing grant, False for an unknown id. (Nit #5 — the db_path="" fixture
    cannot distinguish these and always returns True.)"""
    db = str(tmp_path / "dtg.db")
    store = DepartmentToolGrantStore(db_path=db)
    await store.start()
    try:
        grant = await store.issue_grant(
            department="science",
            tool_id=mcp_tool_tool_id("weather", "get_forecast"),
            permission=ToolPermission.READ,
            issued_by="captain",
        )
        assert await store.revoke_grant(grant.id) is True
        # Already revoked → the rowcount==0 guard returns False.
        assert await store.revoke_grant(grant.id) is False
        # Never-existed id → False.
        assert await store.revoke_grant("does-not-exist") is False
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_real_db_expired_grant_not_loaded(tmp_path) -> None:
    """An already-expired grant is excluded by _load_cache's WHERE clause."""
    import time as _time

    db = str(tmp_path / "dtg.db")
    store = DepartmentToolGrantStore(db_path=db)
    await store.start()
    await store.issue_grant(
        department="science",
        tool_id=mcp_tool_tool_id("weather", "get_forecast"),
        permission=ToolPermission.READ,
        issued_by="captain",
        expires_at=_time.time() - 1.0,  # already expired
    )
    await store.stop()

    store2 = DepartmentToolGrantStore(db_path=db)
    await store2.start()
    try:
        assert store2.get_active_grants_sync("science") == []
    finally:
        await store2.stop()
