"""AD-1213 (#1170): the Captain's expiring approval-authority records.

``ApprovalAuthorityStore`` holds two kinds of record the Captain issues: a First
Officer delegation and a "Captain unavailable" mark. Both widen who may decide a
request, so neither may exist without an expiry: ``expires_at`` is NOT NULL in the
schema, a TTL must be a finite positive real, and a lapsed record reads as absent.

Every read of authority goes through ``live()``, which answers from the cache and
raises ``ApprovalAuthorityUnavailable`` rather than guessing when the store is not
running -- the caller refuses the agent and the Captain decides.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from probos.approval_authority import (
    CAPTAIN_UNAVAILABLE,
    FIRST_OFFICER_DELEGATION,
    MAX_REASON_CHARS,
    RECORD_KINDS,
    ApprovalAuthorityStore,
    ApprovalAuthorityUnavailable,
    AuthorityRecord,
)
from probos.storage.sqlite_factory import default_factory

_DB_NAME = "approval_authority.db"


class _Clock:
    """The store's single source of "now"; tests move it by hand."""

    def __init__(self, t: float = 1_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _rows(path: Path) -> list[dict[str, Any]]:
    """Every row on disk, read through a second connection (committed state only)."""
    conn = sqlite3.connect(path)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM approval_authority ORDER BY issued_at, id")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
async def store(tmp_path: Path, clock: _Clock):
    s = ApprovalAuthorityStore(db_path=str(tmp_path / _DB_NAME), clock=clock)
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


async def test_issue_is_live_until_it_expires(store: ApprovalAuthorityStore, clock: _Clock) -> None:
    record = await store.issue(
        FIRST_OFFICER_DELEGATION, ttl_seconds=3600, issued_by="captain", reason="Captain off watch",
    )

    assert isinstance(record, AuthorityRecord)
    assert (record.kind, record.issued_by, record.reason) == (
        FIRST_OFFICER_DELEGATION, "captain", "Captain off watch",
    )
    assert record.issued_at == clock.t and record.expires_at == clock.t + 3600
    assert (record.revoked, record.revoked_at, record.revoked_by) == (False, None, "")
    assert store.live(FIRST_OFFICER_DELEGATION) == record
    assert store.live(CAPTAIN_UNAVAILABLE) is None

    clock.t = record.expires_at - 0.001
    assert store.live(FIRST_OFFICER_DELEGATION) == record
    # Lapsed at exactly expires_at: expiry is lazy and the record reads as absent.
    clock.t = record.expires_at
    assert store.live(FIRST_OFFICER_DELEGATION) is None


async def test_issue_supersedes_the_live_record_of_its_kind(
    store: ApprovalAuthorityStore, clock: _Clock, tmp_path: Path,
) -> None:
    first = await store.issue(FIRST_OFFICER_DELEGATION, ttl_seconds=3600, issued_by="captain")
    clock.t += 10
    second = await store.issue(
        FIRST_OFFICER_DELEGATION, ttl_seconds=7200, issued_by="captain", reason="extended",
    )

    assert store.live(FIRST_OFFICER_DELEGATION) == second
    by_id = {row["id"]: row for row in _rows(tmp_path / _DB_NAME)}
    # The superseded record stays on the record: it is flagged, never deleted.
    assert set(by_id) == {first.id, second.id}
    assert by_id[first.id]["revoked"] == 1
    assert by_id[first.id]["revoked_by"] == "captain"
    assert by_id[first.id]["revoked_at"] == clock.t
    assert by_id[second.id]["revoked"] == 0
    assert by_id[second.id]["expires_at"] == clock.t + 7200


@pytest.mark.parametrize(
    "ttl",
    [0, -1, float("nan"), float("inf"), True, "60"],
    ids=["zero", "negative", "nan", "inf", "bool", "string"],
)
async def test_issue_refuses_a_ttl_that_is_not_finite_and_positive(
    store: ApprovalAuthorityStore, tmp_path: Path, ttl: Any,
) -> None:
    with pytest.raises(ValueError):
        await store.issue(FIRST_OFFICER_DELEGATION, ttl_seconds=ttl, issued_by="captain")

    assert store.live(FIRST_OFFICER_DELEGATION) is None
    assert _rows(tmp_path / _DB_NAME) == []


async def test_issue_refuses_unknown_kind_blank_issuer_and_long_reason(
    store: ApprovalAuthorityStore, tmp_path: Path,
) -> None:
    assert RECORD_KINDS == frozenset({FIRST_OFFICER_DELEGATION, CAPTAIN_UNAVAILABLE})
    assert MAX_REASON_CHARS == 500

    with pytest.raises(ValueError):
        await store.issue("admiral_override", ttl_seconds=60, issued_by="captain")
    for issuer in ("", "   ", None):
        with pytest.raises(ValueError):
            await store.issue(CAPTAIN_UNAVAILABLE, ttl_seconds=60, issued_by=issuer)
    with pytest.raises(ValueError):
        await store.issue(
            CAPTAIN_UNAVAILABLE, ttl_seconds=60, issued_by="captain",
            reason="x" * (MAX_REASON_CHARS + 1),
        )
    with pytest.raises(ValueError):
        store.live("admiral_override")
    assert _rows(tmp_path / _DB_NAME) == []

    edge = await store.issue(
        CAPTAIN_UNAVAILABLE, ttl_seconds=60, issued_by="captain", reason="x" * MAX_REASON_CHARS,
    )
    assert store.live(CAPTAIN_UNAVAILABLE) == edge


async def test_revoke_keeps_the_row_and_removes_the_authority(
    store: ApprovalAuthorityStore, clock: _Clock, tmp_path: Path,
) -> None:
    record = await store.issue(CAPTAIN_UNAVAILABLE, ttl_seconds=600, issued_by="captain")
    clock.t += 5

    assert await store.revoke(CAPTAIN_UNAVAILABLE, revoked_by="captain") == 1

    assert store.live(CAPTAIN_UNAVAILABLE) is None
    rows = _rows(tmp_path / _DB_NAME)
    assert [row["id"] for row in rows] == [record.id]
    assert (rows[0]["revoked"], rows[0]["revoked_by"], rows[0]["revoked_at"]) == (1, "captain", clock.t)
    assert await store.revoke(CAPTAIN_UNAVAILABLE, revoked_by="captain") == 0

    # A revoked record does not come back after a restart.
    reopened = ApprovalAuthorityStore(db_path=str(tmp_path / _DB_NAME), clock=clock)
    await reopened.start()
    try:
        assert reopened.live(CAPTAIN_UNAVAILABLE) is None
    finally:
        await reopened.stop()


@pytest.mark.parametrize("persistent", [True, False], ids=["sqlite", "cache_only"])
async def test_live_raises_before_start_and_after_stop(tmp_path: Path, persistent: bool) -> None:
    s = ApprovalAuthorityStore(db_path=str(tmp_path / _DB_NAME) if persistent else "")

    with pytest.raises(ApprovalAuthorityUnavailable):
        s.live(FIRST_OFFICER_DELEGATION)
    with pytest.raises(ApprovalAuthorityUnavailable):
        await s.issue(FIRST_OFFICER_DELEGATION, ttl_seconds=60, issued_by="captain")
    with pytest.raises(ApprovalAuthorityUnavailable):
        await s.revoke(FIRST_OFFICER_DELEGATION, revoked_by="captain")

    await s.start()
    try:
        assert s.live(FIRST_OFFICER_DELEGATION) is None
        issued = await s.issue(FIRST_OFFICER_DELEGATION, ttl_seconds=60, issued_by="captain")
        assert s.live(FIRST_OFFICER_DELEGATION) == issued
    finally:
        await s.stop()

    with pytest.raises(ApprovalAuthorityUnavailable):
        s.live(FIRST_OFFICER_DELEGATION)
    with pytest.raises(ApprovalAuthorityUnavailable):
        await s.issue(CAPTAIN_UNAVAILABLE, ttl_seconds=60, issued_by="captain")


async def test_live_records_survive_a_restart_and_expired_ones_do_not(
    tmp_path: Path, clock: _Clock,
) -> None:
    path = str(tmp_path / _DB_NAME)
    first = ApprovalAuthorityStore(db_path=path, clock=clock)
    await first.start()
    try:
        delegation = await first.issue(
            FIRST_OFFICER_DELEGATION, ttl_seconds=3600, issued_by="captain", reason="watch",
        )
        await first.issue(CAPTAIN_UNAVAILABLE, ttl_seconds=60, issued_by="captain")
    finally:
        await first.stop()

    clock.t += 120
    second = ApprovalAuthorityStore(db_path=path, clock=clock)
    await second.start()
    try:
        assert second.live(FIRST_OFFICER_DELEGATION) == delegation
        assert second.live(CAPTAIN_UNAVAILABLE) is None
    finally:
        await second.stop()


async def test_expires_at_is_not_null_in_the_schema(store: ApprovalAuthorityStore, tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / _DB_NAME)
    try:
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(approval_authority)")}
    finally:
        conn.close()

    assert set(columns) == {
        "id", "kind", "issued_by", "reason", "issued_at", "expires_at",
        "revoked", "revoked_at", "revoked_by",
    }
    # (cid, name, type, notnull, dflt_value, pk)
    assert columns["expires_at"][2].upper() == "REAL"
    assert columns["expires_at"][3] == 1


class _CommitFailingConnection:
    """A real connection whose commit can be made to fail on demand."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.fail_commit = False

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        return self._inner.execute(*args, **kwargs)

    async def executescript(self, script: str) -> Any:
        return await self._inner.executescript(script)

    async def commit(self) -> None:
        if self.fail_commit:
            raise sqlite3.OperationalError("AD-1213 test: injected commit failure")
        await self._inner.commit()

    async def close(self) -> None:
        await self._inner.close()


class _CommitFailingFactory:
    def __init__(self) -> None:
        self.connections: list[_CommitFailingConnection] = []

    async def connect(self, db_path: str) -> _CommitFailingConnection:
        connection = _CommitFailingConnection(await default_factory.connect(db_path))
        self.connections.append(connection)
        return connection


async def test_a_failed_commit_leaves_live_authority_unchanged(tmp_path: Path, clock: _Clock) -> None:
    factory = _CommitFailingFactory()
    path = str(tmp_path / _DB_NAME)
    s = ApprovalAuthorityStore(db_path=path, connection_factory=factory, clock=clock)
    await s.start()
    try:
        standing = await s.issue(FIRST_OFFICER_DELEGATION, ttl_seconds=3600, issued_by="captain")
        assert len(factory.connections) == 1
        factory.connections[0].fail_commit = True

        with pytest.raises(sqlite3.OperationalError):
            await s.issue(FIRST_OFFICER_DELEGATION, ttl_seconds=60, issued_by="captain")
        assert s.live(FIRST_OFFICER_DELEGATION) == standing
        with pytest.raises(sqlite3.OperationalError):
            await s.revoke(FIRST_OFFICER_DELEGATION, revoked_by="captain")
        assert s.live(FIRST_OFFICER_DELEGATION) == standing
    finally:
        await s.stop()

    # The durable state agrees: the uncommitted supersede and revoke never landed.
    reopened = ApprovalAuthorityStore(db_path=path, clock=clock)
    await reopened.start()
    try:
        assert reopened.live(FIRST_OFFICER_DELEGATION) == standing
    finally:
        await reopened.stop()


async def test_kinds_are_independent(store: ApprovalAuthorityStore, clock: _Clock) -> None:
    await store.issue(FIRST_OFFICER_DELEGATION, ttl_seconds=3600, issued_by="captain")
    mark = await store.issue(CAPTAIN_UNAVAILABLE, ttl_seconds=600, issued_by="captain")

    assert await store.revoke(FIRST_OFFICER_DELEGATION, revoked_by="captain") == 1
    assert store.live(CAPTAIN_UNAVAILABLE) == mark

    clock.t += 1
    again = await store.issue(CAPTAIN_UNAVAILABLE, ttl_seconds=600, issued_by="captain")
    assert store.live(CAPTAIN_UNAVAILABLE) == again
    assert store.live(FIRST_OFFICER_DELEGATION) is None

    delegation = await store.issue(FIRST_OFFICER_DELEGATION, ttl_seconds=60, issued_by="captain")
    assert store.live(FIRST_OFFICER_DELEGATION) == delegation
    assert store.live(CAPTAIN_UNAVAILABLE) == again
