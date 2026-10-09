"""AD-1323 (#1478): the durable continue-extension permit store."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from probos.continue_extension_permits import (
    STATE_ACTIVE,
    STATE_CONSUMED,
    ContinueExtensionPermits,
    SqliteContinueExtensionPermitStore,
)
from probos.storage.sqlite_factory import SQLiteConnectionFactory


class _Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _CountingFactory:
    """A ConnectionFactory that is not the default, proving the injection point is used."""

    def __init__(self) -> None:
        self.paths: list[str] = []
        self._inner = SQLiteConnectionFactory()

    async def connect(self, db_path: str) -> Any:
        self.paths.append(db_path)
        return await self._inner.connect(db_path)


async def _store(tmp_path: Path, clock: _Clock | None = None, **kw: Any) -> SqliteContinueExtensionPermitStore:
    store = SqliteContinueExtensionPermitStore(
        str(tmp_path / "permits.db"), clock=clock or _Clock(), **kw,
    )
    await store.start()
    return store


async def _reserve(store: SqliteContinueExtensionPermitStore, request_id: str = "req-1", **kw: Any) -> bool:
    args: dict[str, Any] = dict(
        request_id=request_id, agent_id="agent-a", work_item_id="wi-1", thread_id="th-1",
        cap_tokens=500, stop_text="partial work", plan_mode=False, configured_budget=1000,
    )
    args.update(kw)
    return await store.reserve(**args)


@pytest.mark.asyncio
async def test_store_satisfies_protocol_and_uses_injected_factory(tmp_path: Path) -> None:
    factory = _CountingFactory()
    store = SqliteContinueExtensionPermitStore(str(tmp_path / "p.db"), connection_factory=factory)
    await store.start()
    try:
        assert isinstance(store, ContinueExtensionPermits)
        assert factory.paths == [str(tmp_path / "p.db")]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_reserve_second_permit_for_same_work_item_refused(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        assert await _reserve(store, "req-1") is True
        assert await _reserve(store, "req-2") is False
        assert await store.has_work_item("wi-1") is True
        assert await store.has_work_item("other") is False
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{"request_id": ""}, {"cap_tokens": -1}, {"configured_budget": 0}])
async def test_reserve_malformed_argument_raises(tmp_path: Path, bad: dict[str, Any]) -> None:
    store = await _store(tmp_path)
    try:
        with pytest.raises(ValueError):
            await _reserve(store, **bad)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_duplicate_approval_single_permit(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        await _reserve(store)
        first = await store.activate("req-1", decided_by="captain")
        replay = await store.activate("req-1", decided_by="captain")
        assert first is not None and replay is not None
        assert first.activated_at == replay.activated_at
        assert len(await store.list_active()) == 1
        assert await store.activate("req-1", decided_by="someone-else") is None
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_agent_cannot_activate_own_permit(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        await _reserve(store)
        assert await store.activate("req-1", decided_by="agent-a") is None
        assert await store.activate("req-1", decided_by="  ") is None
        assert await store.activate("req-1", decided_by="") is None
        permit = await store.get("req-1")
        assert permit is not None and permit.state == "requested"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_consume_requires_active_and_matching_identity(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    ident = dict(agent_id="agent-a", work_item_id="wi-1", thread_id="th-1")
    try:
        await _reserve(store)
        assert await store.consume("req-1", **ident) is None  # still requested
        await store.activate("req-1", decided_by="captain")
        assert await store.consume("req-1", **{**ident, "agent_id": "x"}) is None
        assert await store.consume("req-1", **{**ident, "thread_id": "x"}) is None
        assert await store.consume("nope", **ident) is None
        got = await store.consume("req-1", **ident)
        assert got is not None and got.state == STATE_CONSUMED
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_consumed_permit_cannot_be_reused(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    ident = dict(agent_id="agent-a", work_item_id="wi-1", thread_id="th-1")
    try:
        await _reserve(store)
        await store.activate("req-1", decided_by="captain")
        assert await store.consume("req-1", **ident) is not None
        assert await store.consume("req-1", **ident) is None
        assert await store.activate("req-1", decided_by="captain") is None
        assert await store.void("req-1") is False
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_concurrent_consume_exactly_one(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    ident = dict(agent_id="agent-a", work_item_id="wi-1", thread_id="th-1")
    try:
        await _reserve(store)
        await store.activate("req-1", decided_by="captain")
        results = await asyncio.gather(*[store.consume("req-1", **ident) for _ in range(12)])
        assert sum(r is not None for r in results) == 1
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_expired_permit_is_not_consumable_and_is_voided(tmp_path: Path) -> None:
    clock = _Clock()
    store = await _store(tmp_path, clock, ttl_seconds=60)
    ident = dict(agent_id="agent-a", work_item_id="wi-1", thread_id="th-1")
    try:
        await _reserve(store)
        await store.activate("req-1", decided_by="captain")
        clock.now += 61
        assert await store.consume("req-1", **ident) is None
        assert await store.void_expired() == 1
        permit = await store.get("req-1")
        assert permit is not None and permit.state == "voided"
        assert await store.void_expired() == 0
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_ttl_runs_from_activation_not_from_request(tmp_path: Path) -> None:
    clock = _Clock()
    store = await _store(tmp_path, clock, ttl_seconds=60)
    ident = dict(agent_id="agent-a", work_item_id="wi-1", thread_id="th-1")
    try:
        await _reserve(store)
        clock.now += 10_000  # a long wait for the approval
        await store.activate("req-1", decided_by="captain")
        clock.now += 30
        assert await store.consume("req-1", **ident) is not None
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_restart_reopen_keeps_state_and_snapshot(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    await _reserve(store, plan_mode=True)
    await store.activate("req-1", decided_by="captain")
    await store.stop()
    reopened = await _store(tmp_path)
    try:
        active = await reopened.list_active()
        assert [p.request_id for p in active] == ["req-1"]
        assert active[0].state == STATE_ACTIVE
        assert active[0].stop_text == "partial work"
        assert active[0].plan_mode is True
        assert active[0].configured_budget == 1000
    finally:
        await reopened.stop()


@pytest.mark.asyncio
async def test_start_migrates_a_table_without_snapshot_columns(tmp_path: Path) -> None:
    db = tmp_path / "permits.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE continue_extension_permits (request_id TEXT PRIMARY KEY, agent_id TEXT, "
        "work_item_id TEXT, thread_id TEXT, state TEXT, cap_tokens INTEGER, created_at REAL, "
        "decided_by TEXT, activated_at REAL, expires_at REAL, consumed_at REAL, voided_at REAL)"
    )
    con.commit()
    con.close()
    store = SqliteContinueExtensionPermitStore(str(db))
    await store.start()
    await store.stop()
    again = SqliteContinueExtensionPermitStore(str(db))
    await again.start()  # idempotent
    await again.stop()
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(continue_extension_permits)")}
    assert {"stop_text", "plan_mode", "configured_budget"} <= cols


@pytest.mark.asyncio
async def test_stopped_store_fails_closed(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    await store.stop()
    with pytest.raises(RuntimeError):
        await store.get("req-1")


@pytest.mark.asyncio
async def test_non_finite_clock_refuses_instead_of_granting(tmp_path: Path) -> None:
    clock = _Clock(float("nan"))
    store = await _store(tmp_path, clock)
    try:
        with pytest.raises(RuntimeError):
            await _reserve(store)
    finally:
        await store.stop()


def test_module_never_deletes_rows() -> None:
    source = Path(__import__("probos.continue_extension_permits", fromlist=["x"]).__file__).read_text(encoding="utf-8")
    assert "DELETE FROM" not in source.upper().replace("NO DELETE FROM", "")


# ---- AD-1323 amendment 2: unbound filing, start-claim and bounded reclaim


async def _reserve_filing(store: SqliteContinueExtensionPermitStore, wi: str = "wi-1", **kw: Any) -> str | None:
    args: dict[str, Any] = dict(
        agent_id="agent-a", work_item_id=wi, thread_id="th-1", cap_tokens=500,
        stop_text="partial work", plan_mode=False, configured_budget=1000,
    )
    args.update(kw)
    return await store.reserve_filing(**args)


@pytest.mark.asyncio
async def test_reserve_filing_creates_unbound_requested_row_and_refuses_second_for_item(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        placeholder = await _reserve_filing(store)
        assert placeholder == "filing:wi-1"
        row = await store.get(placeholder)
        assert row is not None
        assert (row.state, row.bound, row.started_at, row.reclaims) == ("requested", False, None, 0)
        assert await _reserve_filing(store) is None
        assert await _reserve(store, "req-x") is False  # any row for the item, bound or not
        assert await _reserve_filing(store, "wi-2") == "filing:wi-2"
        with pytest.raises(ValueError):
            await _reserve_filing(store, "")
        with pytest.raises(ValueError):
            await _reserve_filing(store, "wi-3", configured_budget=0)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_reserve_filing_refuses_after_void(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        assert await _reserve_filing(store) is not None
        assert await store.void_unbound("wi-1") is True
        assert await _reserve_filing(store) is None  # rows are never deleted: one ask per item
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_bind_cas_exactly_once_and_rewrites_request_id(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        await _reserve_filing(store)
        assert await store.activate("filing:wi-1", decided_by="captain") is None  # unbound: not activatable
        assert await store.bind("wi-1", "req-1") is True
        assert await store.bind("wi-1", "req-2") is False
        assert await store.get("filing:wi-1") is None
        row = await store.get("req-1")
        assert row is not None and row.bound is True and row.state == "requested"
        assert await store.bind("wi-1", "") is False
        assert await store.activate("req-1", decided_by="captain") is not None
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_get_for_request_resolves_by_id_or_unbound_work_item(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        assert await store.get_for_request("req-1", "wi-1") is None
        await _reserve_filing(store)
        by_item = await store.get_for_request("req-1", "wi-1")
        assert by_item is not None and by_item.bound is False
        assert await store.get_for_request("req-1", None) is None
        assert await store.get_for_request("req-1", "other") is None
        await store.bind("wi-1", "req-1")
        by_id = await store.get_for_request("req-1", "wi-1")
        assert by_id is not None and by_id.bound is True
        assert await store.get_for_request("req-9", "wi-1") is None  # bound rows resolve by id only
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_void_unbound_only_voids_unbound(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        await _reserve_filing(store, "wi-1")
        await _reserve_filing(store, "wi-2")
        await store.bind("wi-2", "req-2")
        assert await store.void_unbound("wi-1") is True
        assert await store.void_unbound("wi-1") is False
        assert await store.void_unbound("wi-2") is False
        row = await store.get("req-2")
        assert row is not None and row.state == "requested"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_begin_pass_cas_exactly_once_and_only_from_consumed(tmp_path: Path) -> None:
    clock = _Clock()
    store = await _store(tmp_path, clock)
    try:
        await _reserve(store)
        assert await store.begin_pass("req-1") is False  # requested
        await store.activate("req-1", decided_by="captain")
        assert await store.begin_pass("req-1") is False  # active
        await store.consume("req-1", agent_id="agent-a", work_item_id="wi-1", thread_id="th-1")
        clock.now = 1005.0
        assert await store.begin_pass("req-1") is True
        assert await store.begin_pass("req-1") is False
        row = await store.get("req-1")
        assert row is not None and row.started_at == 1005.0
        assert await store.begin_pass("missing") is False
    finally:
        await store.stop()


async def _consumed(store: SqliteContinueExtensionPermitStore, rid: str = "req-1", wi: str = "wi-1") -> None:
    await _reserve(store, rid, work_item_id=wi)
    await store.activate(rid, decided_by="captain")
    assert await store.consume(rid, agent_id="agent-a", work_item_id=wi, thread_id="th-1") is not None


@pytest.mark.asyncio
async def test_reclaim_unstarted_once_only_and_respects_ttl(tmp_path: Path) -> None:
    clock = _Clock()
    store = await _store(tmp_path, clock)
    try:
        await _consumed(store)
        again = await store.reclaim_unstarted("req-1")
        assert again is not None
        assert (again.state, again.consumed_at, again.reclaims) == (STATE_ACTIVE, None, 1)
        assert await store.consume("req-1", agent_id="agent-a", work_item_id="wi-1", thread_id="th-1") is not None
        assert await store.reclaim_unstarted("req-1") is None  # reclaims < 1 refuses a second
        row = await store.get("req-1")
        assert row is not None and row.state == STATE_CONSUMED and row.reclaims == 1

        await _consumed(store, "req-2", "wi-2")
        clock.now += 10_000  # past the 3600s approval TTL
        assert await store.reclaim_unstarted("req-2") is None
        # a started pass is never reclaimed
        clock.now = 1000.0
        await _consumed(store, "req-3", "wi-3")
        await store.begin_pass("req-3")
        assert await store.reclaim_unstarted("req-3") is None
        assert await store.reclaim_unstarted("missing") is None
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_list_unbound_and_consumed_unstarted(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        await _reserve_filing(store, "wi-u")
        await _reserve_filing(store, "wi-b")
        await store.bind("wi-b", "req-b")
        assert [p.work_item_id for p in await store.list_unbound()] == ["wi-u"]
        assert [p.request_id for p in await store.list_requested()] == ["req-b"]
        await _consumed(store, "req-c1", "wi-c1")
        await _consumed(store, "req-c2", "wi-c2")
        await store.begin_pass("req-c2")
        assert [p.request_id for p in await store.list_consumed_unstarted()] == ["req-c1"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_migration_adds_bound_started_reclaims_columns_idempotently_and_old_rows_read_bound(
    tmp_path: Path,
) -> None:
    db = tmp_path / "permits.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE continue_extension_permits (request_id TEXT PRIMARY KEY, agent_id TEXT, "
        "work_item_id TEXT, thread_id TEXT, state TEXT, cap_tokens INTEGER, created_at REAL, "
        "decided_by TEXT, activated_at REAL, expires_at REAL, consumed_at REAL, voided_at REAL)"
    )
    con.execute(
        "INSERT INTO continue_extension_permits (request_id, agent_id, work_item_id, thread_id, "
        "state, cap_tokens, created_at) VALUES ('old', 'a', 'w', 't', 'requested', 0, 1.0)"
    )
    con.commit()
    con.close()
    for _ in range(2):
        store = SqliteContinueExtensionPermitStore(str(db))
        await store.start()
        row = await store.get("old")
        await store.stop()
        assert row is not None and (row.bound, row.started_at, row.reclaims) == (True, None, 0)
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(continue_extension_permits)")}
    assert {"bound", "started_at", "reclaims"} <= cols

# ---- AD-1323 amendment 5: void_reservation


async def _unbound_row(store: SqliteContinueExtensionPermitStore, wi: str = "wi-1") -> str:
    placeholder = await store.reserve_filing(
        agent_id="agent-a", work_item_id=wi, thread_id="th-1", cap_tokens=500,
        stop_text="partial", plan_mode=False, configured_budget=1000,
    )
    assert placeholder, "premise: an unbound permit must exist"
    return placeholder


@pytest.mark.asyncio
async def test_void_reservation_voids_unbound_placeholder_by_work_item(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        placeholder = await _unbound_row(store)
        assert await store.void_reservation("wi-1", "") is True
        row = await store.get(placeholder)
        assert row is not None and row.state == "voided"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_void_reservation_voids_bound_requested_row_when_request_id_matches(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        await _unbound_row(store)
        assert await store.bind("wi-1", "req-1") is True
        assert await store.void_reservation("wi-1", "req-1") is True
        row = await store.get("req-1")
        assert row is not None and row.state == "voided" and row.bound is True
        assert await store.activate("req-1", decided_by="captain") is None
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_void_reservation_wrong_request_id_leaves_bound_row_untouched(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        await _unbound_row(store)
        await store.bind("wi-1", "req-1")
        assert await store.void_reservation("wi-1", "other") is False
        assert await store.void_reservation("wi-1", "") is False
        row = await store.get("req-1")
        assert row is not None and row.state == "requested"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_void_reservation_never_touches_active_consumed_or_voided_rows(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        for wi, rid in (("wi-a", "r-a"), ("wi-c", "r-c"), ("wi-v", "r-v")):
            await _reserve(store, rid, work_item_id=wi)
        await store.activate("r-a", decided_by="captain")
        await store.activate("r-c", decided_by="captain")
        await store.consume("r-c", agent_id="agent-a", work_item_id="wi-c", thread_id="th-1")
        await store.void("r-v")
        for wi, rid, state in (("wi-a", "r-a", "active"), ("wi-c", "r-c", "consumed"), ("wi-v", "r-v", "voided")):
            assert await store.void_reservation(wi, rid) is False
            row = await store.get(rid)
            assert row is not None and row.state == state
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_void_reservation_rejects_non_str_and_empty_inputs_without_writing(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        await _unbound_row(store)
        writes: list[str] = []
        original = store._write

        async def _spy(sql: str, params: tuple[Any, ...]) -> int:
            writes.append(sql)
            return await original(sql, params)

        store._write = _spy  # type: ignore[method-assign]
        for wi, rid in (("", ""), (None, ""), (5, ""), ("wi-1", None), ("wi-1", 7)):
            assert await store.void_reservation(wi, rid) is False  # type: ignore[arg-type]
        assert writes == []
        assert [p.state for p in await store.list_unbound()] == ["requested"]
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_void_reservation_unknown_work_item_returns_false(tmp_path: Path) -> None:
    store = await _store(tmp_path)
    try:
        assert await store.void_reservation("nope", "") is False
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_void_reservation_then_activate_returns_none_and_activate_then_void_keeps_active(
    tmp_path: Path,
) -> None:
    store = await _store(tmp_path)
    try:
        await _reserve(store, "r-1", work_item_id="wi-1")
        await _reserve(store, "r-2", work_item_id="wi-2")
        assert await store.void_reservation("wi-1", "r-1") is True
        assert await store.activate("r-1", decided_by="captain") is None
        assert await store.activate("r-2", decided_by="captain") is not None
        assert await store.void_reservation("wi-2", "r-2") is False
        row = await store.get("r-2")
        assert row is not None and row.state == "active"
    finally:
        await store.stop()
