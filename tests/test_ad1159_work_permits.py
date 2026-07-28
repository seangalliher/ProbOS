"""AD-1159: WorkPermitStore — single-holder, TTL-bounded workstation authority.

Covers every invariant in the AD's Section 5.3 with a named test each, plus
happy-path / error / empty-input boundary coverage for every public method, the
Cloud-Ready Storage rule (``ConnectionFactory`` injection), the config
byte-identity guarantee, and the two "do not touch" assertions the AD requires
(``_BROWSER_LOOP_ACTIONS`` unchanged, ``classify_action``'s tier vocabulary
unchanged).

Nothing in this AD consumes the store, so there is deliberately no integration
test here — the store is constructed by these tests only.
"""

from __future__ import annotations

import inspect
import sqlite3
import time
from collections.abc import Callable
from typing import Any

import pytest

from probos.cognitive.agentic_dispatch import _BROWSER_LOOP_ACTIONS
from probos.config import ApprovalInboxConfig, SystemConfig
from probos.protocols import ConnectionFactory, DatabaseConnection
from probos.storage.sqlite_factory import SQLiteConnectionFactory
from probos.tools.work_permits import (
    PermitConflict,
    WorkPermit,
    WorkPermitStore,
    _VALID_TIERS,
)


class _RecordingConnectionFactory:
    """A real factory that records every ``connect`` call.

    Deliberately not a Mock: the store must survive a genuine SQLite round trip
    while we prove the injected factory — not ``aiosqlite.connect`` — is what
    opened the handle.
    """

    def __init__(self) -> None:
        self.paths: list[str] = []
        self._inner = SQLiteConnectionFactory()

    async def connect(self, db_path: str) -> DatabaseConnection:
        self.paths.append(db_path)
        return await self._inner.connect(db_path)


class _FakeClock:
    """A manually advanced clock, injected in place of ``time.time``.

    Expiry is the one behaviour of this store that depends on time passing, and
    it cannot be constructed with a negative ``ttl_seconds`` — ``issue_permit``
    rejects a non-positive TTL precisely because such a permit would report a
    granted authority while granting nothing. So expiry is exercised the way it
    actually happens: a permit is issued live, and then time moves.

    Deliberately not ``monkeypatch.setattr(time, "time", ...)``: the store takes
    a ``clock`` parameter (mirroring ``CrewSessionService.__init__``), so the
    seam is the constructor, and patching a module global would also move time
    for every unrelated thing sharing this process.
    """

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


async def _store(
    tmp_path: Any,
    name: str = "permits.db",
    clock: Callable[[], float] = time.time,
) -> WorkPermitStore:
    store = WorkPermitStore(db_path=str(tmp_path / name), clock=clock)
    await store.start()
    return store


async def _issue(
    store: WorkPermitStore,
    *,
    session_id: str = "sess-1",
    workstation_id: str = "browser",
    holder_id: str = "agent-holder",
    issued_by: str = "captain",
    max_tier: int = 2,
    ttl_seconds: float = 3600.0,
    reason: str = "",
) -> WorkPermit:
    return await store.issue_permit(
        session_id=session_id,
        workstation_id=workstation_id,
        holder_id=holder_id,
        issued_by=issued_by,
        max_tier=max_tier,
        ttl_seconds=ttl_seconds,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Section 5.3 — the invariants, one named test each
# ---------------------------------------------------------------------------


class TestInvariantSingleHolder:
    """Invariant 1: at most one open, unexpired permit per space."""

    @pytest.mark.asyncio
    async def test_issue_permit_on_occupied_space_raises_permit_conflict(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, holder_id="agent-a")
            # Act / Assert
            with pytest.raises(PermitConflict):
                await _issue(store, holder_id="agent-b")
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_conflict_leaves_the_incumbent_untouched(
        self, tmp_path
    ):
        """A permit that vanishes because someone else asked is the failure PTW prevents."""
        # Arrange
        store = await _store(tmp_path)
        try:
            first = await _issue(store, holder_id="agent-a", max_tier=2)
            # Act
            with pytest.raises(PermitConflict):
                await _issue(store, holder_id="agent-b", max_tier=1)
            # Assert
            assert store.holder_sync("sess-1", "browser") == "agent-a"
            assert store.permitted_tier_sync("agent-a", "sess-1", "browser") == 2
            assert store.permitted_tier_sync("agent-b", "sess-1", "browser") == 0
            assert store.get_sync(first.id) is not None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_after_closure_succeeds(self, tmp_path):
        """Exclusion is over LIVE permits — closing frees the space."""
        # Arrange
        store = await _store(tmp_path)
        try:
            first = await _issue(store, holder_id="agent-a")
            await store.close_permit(first.id, closed_by="captain")
            # Act
            second = await _issue(store, holder_id="agent-b")
            # Assert
            assert second.holder_id == "agent-b"
            assert store.holder_sync("sess-1", "browser") == "agent-b"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_after_expiry_succeeds(self, tmp_path):
        """A lapsed permit does not hold the space hostage."""
        # Arrange
        clock = _FakeClock()
        store = await _store(tmp_path, clock=clock)
        try:
            await _issue(store, holder_id="agent-a", ttl_seconds=60.0)
            assert store.holder_sync("sess-1", "browser") == "agent-a"
            clock.advance(61.0)
            # Act
            second = await _issue(store, holder_id="agent-b")
            # Assert
            assert store.holder_sync("sess-1", "browser") == "agent-b"
            assert second.holder_id == "agent-b"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_for_a_different_workstation_is_not_a_conflict(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, workstation_id="browser", holder_id="agent-a")
            # Act
            await _issue(store, workstation_id="monaco", holder_id="agent-b")
            # Assert
            assert store.holder_sync("sess-1", "browser") == "agent-a"
            assert store.holder_sync("sess-1", "monaco") == "agent-b"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_for_a_different_session_is_not_a_conflict(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, session_id="sess-1", holder_id="agent-a")
            # Act
            await _issue(store, session_id="sess-2", holder_id="agent-b")
            # Assert
            assert store.holder_sync("sess-1", "browser") == "agent-a"
            assert store.holder_sync("sess-2", "browser") == "agent-b"
        finally:
            await store.stop()


class TestInvariantIssuingIsNotPerforming:
    """Invariant 2: the officer who authorizes never performs."""

    @pytest.mark.asyncio
    async def test_issue_permit_rejects_self_issue(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            with pytest.raises(ValueError, match="issued_by must differ"):
                await _issue(store, holder_id="agent-a", issued_by="agent-a")
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_rejects_self_issue_of_empty_identities(
        self, tmp_path
    ):
        """Two empty strings are still the same authority."""
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            with pytest.raises(ValueError, match="issued_by must differ"):
                await _issue(store, holder_id="", issued_by="")
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_rejected_self_issue_writes_nothing(self, tmp_path):
        # Arrange
        db = str(tmp_path / "selfissue.db")
        store = WorkPermitStore(db_path=db)
        await store.start()
        try:
            with pytest.raises(ValueError):
                await _issue(store, holder_id="agent-a", issued_by="agent-a")
            # Act
            rows = list(
                sqlite3.connect(db).execute("SELECT COUNT(*) FROM work_permits")
            )
            # Assert
            assert rows[0][0] == 0
            assert store.list_open_sync() == []
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_accepts_distinct_issuer_and_holder(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act
            permit = await _issue(store, holder_id="agent-a", issued_by="captain")
            # Assert
            assert permit.holder_id == "agent-a"
            assert permit.issued_by == "captain"
        finally:
            await store.stop()


class TestInvariantTierBounds:
    """Invariant 3: max_tier ∈ {1, 2, 3}, and bool is not int enough."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tier", [1, 2, 3])
    async def test_issue_permit_accepts_each_valid_tier(self, tmp_path, tier):
        # Arrange
        store = await _store(tmp_path, name=f"tier{tier}.db")
        try:
            # Act
            permit = await _issue(store, max_tier=tier)
            # Assert
            assert permit.max_tier == tier
            assert store.permitted_tier_sync(
                "agent-holder", "sess-1", "browser"
            ) == tier
        finally:
            await store.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tier", [0, 4, -1, 100])
    async def test_issue_permit_rejects_out_of_range_tier(self, tmp_path, tier):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            with pytest.raises(ValueError, match="max_tier must be one of"):
                await _issue(store, max_tier=tier)
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_rejects_bool_true_which_would_mean_tier_one(
        self, tmp_path
    ):
        """isinstance(True, int) is True — an authorization created by a typo."""
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            with pytest.raises(ValueError, match="not bool"):
                await _issue(store, max_tier=True)  # type: ignore[arg-type]
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_rejects_bool_false(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            with pytest.raises(ValueError, match="not bool"):
                await _issue(store, max_tier=False)  # type: ignore[arg-type]
        finally:
            await store.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("tier", [None, "2", 2.0])
    async def test_issue_permit_rejects_non_int_tier(self, tmp_path, tier):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            with pytest.raises(ValueError, match="max_tier must be one of"):
                await _issue(store, max_tier=tier)  # type: ignore[arg-type]
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_rejected_tier_writes_nothing(self, tmp_path):
        # Arrange
        db = str(tmp_path / "badtier.db")
        store = WorkPermitStore(db_path=db)
        await store.start()
        try:
            with pytest.raises(ValueError):
                await _issue(store, max_tier=True)  # type: ignore[arg-type]
            # Act
            rows = list(
                sqlite3.connect(db).execute("SELECT COUNT(*) FROM work_permits")
            )
            # Assert
            assert rows[0][0] == 0
            assert store.holder_sync("sess-1", "browser") is None
        finally:
            await store.stop()

    def test_valid_tiers_matches_the_classify_action_ladder(self):
        """The tier vocabulary is READ from classify_action, never widened here."""
        # Assert
        assert _VALID_TIERS == (1, 2, 3)


class TestInvariantExpiresAtNotNull:
    """Invariant 4: the TTL lives in the schema, not merely in the signature."""

    def test_issue_permit_has_no_parameter_that_yields_a_null_expiry(self):
        # Act
        signature = inspect.signature(WorkPermitStore.issue_permit)
        ttl = signature.parameters["ttl_seconds"]
        # Assert
        assert "expires_at" not in signature.parameters
        assert ttl.kind is inspect.Parameter.KEYWORD_ONLY
        assert ttl.default is inspect.Parameter.empty
        assert ttl.annotation == "float"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ttl", [0, 0.0, -1, -0.5, -3600.0])
    async def test_issue_permit_rejects_a_non_positive_ttl(self, tmp_path, ttl):
        """A permit that expires at or before it is returned is a success-shaped no-op.

        This is the failure mode AD-1154 exists to eliminate: the call returns a
        WorkPermit, the caller reads a granted authority, and every subsequent
        read treats it as absent because ``_live_permit_sync`` filters
        ``expires_at <= now``. Nothing ever says so.
        """
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            with pytest.raises(ValueError, match="ttl_seconds must be a finite"):
                await _issue(store, ttl_seconds=ttl)
        finally:
            await store.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ttl", [True, False])
    async def test_issue_permit_rejects_a_bool_ttl(self, tmp_path, ttl):
        """``ttl_seconds=True`` would silently mean a one-second authority."""
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            with pytest.raises(ValueError, match="not bool"):
                await _issue(store, ttl_seconds=ttl)  # type: ignore[arg-type]
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_rejects_a_nan_ttl(self, tmp_path):
        """``nan <= 0`` is False, so a bare positivity test would let it through.

        Every later ``expires_at > now`` comparison would be False too, giving an
        inert permit that no error ever explained.
        """
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            with pytest.raises(ValueError, match="ttl_seconds must be a finite"):
                await _issue(store, ttl_seconds=float("nan"))
        finally:
            await store.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ttl", [float("inf"), float("-inf")])
    async def test_issue_permit_rejects_an_infinite_ttl(self, tmp_path, ttl):
        """``inf`` is the never-expiring authority this invariant forbids."""
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            with pytest.raises(ValueError, match="ttl_seconds must be a finite"):
                await _issue(store, ttl_seconds=ttl)
        finally:
            await store.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ttl", [None, "3600", [3600]])
    async def test_issue_permit_rejects_a_non_real_ttl(self, tmp_path, ttl):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            with pytest.raises(ValueError, match="ttl_seconds must be a finite"):
                await _issue(store, ttl_seconds=ttl)  # type: ignore[arg-type]
        finally:
            await store.stop()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ttl", [1, 0.001, 3600.0, 86400])
    async def test_issue_permit_accepts_any_finite_positive_ttl(self, tmp_path, ttl):
        """The happy path: int and float, small and large, all still work."""
        # Arrange
        clock = _FakeClock()
        store = await _store(tmp_path, name=f"ttl{ttl}.db", clock=clock)
        try:
            # Act
            permit = await _issue(store, ttl_seconds=ttl)
            # Assert
            assert permit.issued_at == clock.now
            assert permit.expires_at == clock.now + ttl
            assert store.holder_sync("sess-1", "browser") == "agent-holder"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_a_rejected_ttl_writes_no_row_and_leaves_the_space_free(
        self, tmp_path
    ):
        """Rejection is total: no cache entry, no row, no occupancy."""
        # Arrange
        db = str(tmp_path / "ttl_reject.db")
        store = WorkPermitStore(db_path=db)
        await store.start()
        try:
            # Act
            with pytest.raises(ValueError):
                await _issue(store, ttl_seconds=0)
            # Assert
            assert store.holder_sync("sess-1", "browser") is None
            assert store.list_open_sync() == []
            rows = list(
                sqlite3.connect(db).execute("SELECT COUNT(*) FROM work_permits")
            )
            assert rows[0][0] == 0
            # ... and the space is still issuable
            permit = await _issue(store, ttl_seconds=60.0)
            assert store.holder_sync("sess-1", "browser") == permit.holder_id
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_the_ttl_check_runs_before_the_occupancy_check(self, tmp_path):
        """A malformed request is rejected as malformed, not as a conflict.

        ``PermitConflict`` is a statement about the world that a caller may retry
        after closing the incumbent; ``ValueError`` can never be retried without
        changing the request. Reporting the wrong one would send a caller into a
        retry loop that cannot terminate.
        """
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, holder_id="agent-a")
            # Act / Assert
            with pytest.raises(ValueError, match="ttl_seconds must be a finite"):
                await _issue(store, holder_id="agent-b", ttl_seconds=0)
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_the_schema_declares_expires_at_not_null(self, tmp_path):
        """Enforced in the SCHEMA so a future caller cannot bypass it."""
        # Arrange
        db = str(tmp_path / "notnull.db")
        store = WorkPermitStore(db_path=db)
        await store.start()
        try:
            # Act
            columns = {
                row[1]: row[3]
                for row in sqlite3.connect(db).execute(
                    "PRAGMA table_info(work_permits)"
                )
            }
            # Assert
            assert columns["expires_at"] == 1
            with pytest.raises(sqlite3.IntegrityError):
                conn = sqlite3.connect(db)
                conn.execute(
                    "INSERT INTO work_permits "
                    "(id, session_id, workstation_id, holder_id, issued_by, "
                    "max_tier, reason, issued_at, expires_at, closed, closed_at, "
                    "close_reason, closed_by) "
                    "VALUES ('x','s','browser','h','captain',1,'',1.0,NULL,0,"
                    "NULL,'','')"
                )
                conn.commit()
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_the_schema_declares_the_identity_columns_not_null(self, tmp_path):
        # Arrange
        db = str(tmp_path / "notnull2.db")
        store = WorkPermitStore(db_path=db)
        await store.start()
        try:
            # Act
            columns = {
                row[1]: row[3]
                for row in sqlite3.connect(db).execute(
                    "PRAGMA table_info(work_permits)"
                )
            }
            # Assert
            for column in (
                "session_id",
                "workstation_id",
                "holder_id",
                "issued_by",
                "max_tier",
                "issued_at",
                "closed",
            ):
                assert columns[column] == 1, column
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_the_schema_creates_both_indexes(self, tmp_path):
        # Arrange
        db = str(tmp_path / "idx.db")
        store = WorkPermitStore(db_path=db)
        await store.start()
        try:
            # Act
            names = {
                row[0]
                for row in sqlite3.connect(db).execute(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='work_permits'"
                )
            }
            # Assert
            assert "idx_wp_lookup" in names
            assert "idx_wp_active" in names
        finally:
            await store.stop()


class TestInvariantLazyExpiry:
    """Invariant 5: expiry is enforced on read. No reaper."""

    @pytest.mark.asyncio
    async def test_holder_sync_returns_none_once_expired(self, tmp_path):
        # Arrange
        clock = _FakeClock()
        store = await _store(tmp_path, clock=clock)
        try:
            await _issue(store, holder_id="agent-a", ttl_seconds=60.0)
            assert store.holder_sync("sess-1", "browser") == "agent-a"
            # Act
            clock.advance(61.0)
            # Assert
            assert store.holder_sync("sess-1", "browser") is None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_holder_sync_still_answers_one_tick_before_expiry(self, tmp_path):
        """The boundary is ``expires_at <= now``, so a permit is live until it is not."""
        # Arrange
        clock = _FakeClock()
        store = await _store(tmp_path, clock=clock)
        try:
            await _issue(store, holder_id="agent-a", ttl_seconds=60.0)
            # Act
            clock.advance(59.9)
            # Assert
            assert store.holder_sync("sess-1", "browser") == "agent-a"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_permitted_tier_sync_returns_zero_once_expired(self, tmp_path):
        # Arrange
        clock = _FakeClock()
        store = await _store(tmp_path, clock=clock)
        try:
            await _issue(store, holder_id="agent-a", max_tier=3, ttl_seconds=60.0)
            assert store.permitted_tier_sync("agent-a", "sess-1", "browser") == 3
            # Act
            clock.advance(61.0)
            # Assert
            assert store.permitted_tier_sync("agent-a", "sess-1", "browser") == 0
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_get_sync_returns_none_once_expired(self, tmp_path):
        # Arrange
        clock = _FakeClock()
        store = await _store(tmp_path, clock=clock)
        try:
            permit = await _issue(store, ttl_seconds=60.0)
            assert store.get_sync(permit.id) is not None
            # Act
            clock.advance(61.0)
            # Assert
            assert store.get_sync(permit.id) is None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_a_sync_read_drops_the_expired_row_from_the_cache(self, tmp_path):
        """Lazy sweep is the whole of expiry enforcement — no background task."""
        # Arrange
        clock = _FakeClock()
        store = await _store(tmp_path, clock=clock)
        try:
            await _issue(store, ttl_seconds=60.0)
            assert len(store.list_open_sync()) == 1
            clock.advance(61.0)
            # Act — one sync read sweeps the lapsed entry out
            assert store.holder_sync("sess-1", "browser") is None
            # Assert — rewinding time does not bring it back, which is only true
            # if the read REMOVED the entry rather than filtering it on the way
            # past. A negative TTL could never have shown this.
            clock.advance(-61.0)
            assert store.list_open_sync() == []
            assert store.holder_sync("sess-1", "browser") is None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_expired_rows_are_not_reloaded_into_the_cache(self, tmp_path):
        # Arrange
        db = str(tmp_path / "wp_expired.db")
        clock = _FakeClock()
        s1 = WorkPermitStore(db_path=db, clock=clock)
        await s1.start()
        await _issue(s1, ttl_seconds=60.0)
        await s1.stop()
        clock.advance(61.0)
        # Act
        s2 = WorkPermitStore(db_path=db, clock=clock)
        await s2.start()
        try:
            # Assert
            assert s2.holder_sync("sess-1", "browser") is None
            assert s2.list_open_sync() == []
            rows = list(
                sqlite3.connect(db).execute("SELECT COUNT(*) FROM work_permits")
            )
            assert rows[0][0] == 1
        finally:
            await s2.stop()


class TestInvariantClosureIsTerminal:
    """Invariant 6: a closed permit never reopens."""

    @pytest.mark.asyncio
    async def test_close_permit_returns_true_the_first_time(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            permit = await _issue(store)
            # Act / Assert
            assert await store.close_permit(permit.id, closed_by="captain") is True
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_close_permit_returns_false_the_second_time(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            permit = await _issue(store)
            await store.close_permit(permit.id, closed_by="captain")
            # Act / Assert — returns False, does NOT raise
            assert await store.close_permit(permit.id, closed_by="captain") is False
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_close_permit_on_unknown_id_returns_false(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            assert await store.close_permit("nope", closed_by="captain") is False
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_close_permit_on_empty_id_returns_false(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            assert await store.close_permit("", closed_by="") is False
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_close_permit_records_who_closed_it_and_why(self, tmp_path):
        """Closure is where an outcome is recorded."""
        # Arrange
        db = str(tmp_path / "closed.db")
        store = WorkPermitStore(db_path=db)
        await store.start()
        try:
            permit = await _issue(store)
            # Act
            await store.close_permit(
                permit.id, closed_by="captain", close_reason="task complete"
            )
            row = list(
                sqlite3.connect(db).execute(
                    "SELECT closed, closed_by, close_reason, closed_at "
                    "FROM work_permits WHERE id = ?",
                    (permit.id,),
                )
            )[0]
            # Assert
            assert row[0] == 1
            assert row[1] == "captain"
            assert row[2] == "task complete"
            assert row[3] is not None and row[3] > 0
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_close_permit_survives_a_restart_as_closed(self, tmp_path):
        # Arrange
        db = str(tmp_path / "wp_closed_restart.db")
        s1 = WorkPermitStore(db_path=db)
        await s1.start()
        permit = await _issue(s1)
        await s1.close_permit(permit.id, closed_by="captain")
        await s1.stop()
        # Act
        s2 = WorkPermitStore(db_path=db)
        await s2.start()
        try:
            # Assert
            assert s2.get_sync(permit.id) is None
            assert s2.holder_sync("sess-1", "browser") is None
            assert await s2.close_permit(permit.id, closed_by="captain") is False
        finally:
            await s2.stop()

    @pytest.mark.asyncio
    async def test_close_permit_succeeds_on_an_expired_but_open_permit(
        self, tmp_path
    ):
        """Expiry makes a permit inert; closure is what records an outcome."""
        # Arrange
        clock = _FakeClock()
        store = await _store(tmp_path, clock=clock)
        try:
            permit = await _issue(store, ttl_seconds=60.0)
            clock.advance(61.0)
            assert store.get_sync(permit.id) is None
            # Act / Assert
            assert await store.close_permit(
                permit.id, closed_by="captain", close_reason="lapsed"
            ) is True
        finally:
            await store.stop()


class TestInvariantNoWildcards:
    """Invariant 7: identifiers match exactly; '' matches only ''."""

    @pytest.mark.asyncio
    async def test_holder_sync_does_not_treat_empty_session_as_a_wildcard(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, session_id="sess-1", holder_id="agent-a")
            # Act / Assert
            assert store.holder_sync("", "browser") is None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_holder_sync_does_not_treat_empty_workstation_as_a_wildcard(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, workstation_id="browser", holder_id="agent-a")
            # Act / Assert
            assert store.holder_sync("sess-1", "") is None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_permitted_tier_sync_does_not_treat_empty_agent_as_a_wildcard(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, holder_id="agent-a")
            # Act / Assert
            assert store.permitted_tier_sync("", "sess-1", "browser") == 0
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_an_empty_identifier_matches_only_an_empty_identifier(
        self, tmp_path
    ):
        """A permit genuinely scoped to '' is reachable by '' and nothing else."""
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(
                store, session_id="", workstation_id="", holder_id="agent-a"
            )
            # Act / Assert
            assert store.holder_sync("", "") == "agent-a"
            assert store.holder_sync("sess-1", "browser") is None
            assert store.permitted_tier_sync("agent-a", "", "") == 2
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_identifiers_are_not_prefix_matched(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, session_id="sess-1", holder_id="agent-a")
            # Act / Assert
            assert store.holder_sync("sess", "browser") is None
            assert store.holder_sync("sess-10", "browser") is None
            assert store.permitted_tier_sync("agent", "sess-1", "browser") == 0
        finally:
            await store.stop()


class TestInvariantAgentScopedTier:
    """Invariant 8: a permit authorizes its holder, not the space."""

    @pytest.mark.asyncio
    async def test_permitted_tier_sync_returns_the_ceiling_for_the_holder(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, holder_id="agent-a", max_tier=3)
            # Act / Assert
            assert store.permitted_tier_sync("agent-a", "sess-1", "browser") == 3
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_permitted_tier_sync_returns_zero_for_a_bystander(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, holder_id="agent-a", max_tier=3)
            # Act / Assert
            assert store.permitted_tier_sync("agent-b", "sess-1", "browser") == 0
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_permitted_tier_sync_returns_zero_for_the_issuer(self, tmp_path):
        """Issuing authority is not performing authority — not even for reads."""
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, holder_id="agent-a", issued_by="captain")
            # Act / Assert
            assert store.permitted_tier_sync("captain", "sess-1", "browser") == 0
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_permitted_tier_sync_returns_zero_when_no_permit_exists(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            assert store.permitted_tier_sync("agent-a", "sess-1", "browser") == 0
        finally:
            await store.stop()


# ---------------------------------------------------------------------------
# Public-method boundary coverage (happy path / error / empty input)
# ---------------------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_the_table(self, tmp_path):
        # Arrange
        db = str(tmp_path / "life.db")
        store = WorkPermitStore(db_path=db)
        # Act
        await store.start()
        try:
            names = {
                row[0]
                for row in sqlite3.connect(db).execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            # Assert
            assert "work_permits" in names
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_start_with_empty_db_path_is_a_cache_only_store(self, tmp_path):
        """Empty path = no I/O at all; the store still functions in memory."""
        # Arrange
        store = WorkPermitStore(db_path="")
        # Act
        await store.start()
        try:
            permit = await _issue(store)
            # Assert
            assert store.holder_sync("sess-1", "browser") == "agent-holder"
            assert store.get_sync(permit.id) is not None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        # Act
        await store.stop()
        # Assert — a second stop must not raise
        await store.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start_does_not_raise(self):
        # Arrange
        store = WorkPermitStore(db_path="")
        # Act / Assert
        await store.stop()

    @pytest.mark.asyncio
    async def test_a_permit_round_trips_through_a_real_db(self, tmp_path):
        # Arrange
        db = str(tmp_path / "wp_persist.db")
        s1 = WorkPermitStore(db_path=db)
        await s1.start()
        await _issue(s1, holder_id="agent-a", max_tier=3, reason="repair")
        await s1.stop()
        # Act
        s2 = WorkPermitStore(db_path=db)
        await s2.start()
        try:
            # Assert
            assert s2.holder_sync("sess-1", "browser") == "agent-a"
            assert s2.permitted_tier_sync("agent-a", "sess-1", "browser") == 3
            assert s2.list_open_sync("sess-1")[0].reason == "repair"
        finally:
            await s2.stop()


class TestConnectionFactoryInjection:
    """The Cloud-Ready Storage rule: never aiosqlite.connect() directly."""

    @pytest.mark.asyncio
    async def test_start_uses_the_injected_connection_factory(self, tmp_path):
        # Arrange
        db = str(tmp_path / "injected.db")
        factory = _RecordingConnectionFactory()
        store = WorkPermitStore(db_path=db, connection_factory=factory)
        # Act
        await store.start()
        try:
            await _issue(store)
            # Assert
            assert factory.paths == [db]
            assert store.holder_sync("sess-1", "browser") == "agent-holder"
        finally:
            await store.stop()

    def test_the_default_factory_is_used_when_none_is_injected(self):
        # Arrange / Act
        store = WorkPermitStore(db_path="")
        # Assert
        assert isinstance(store._connection_factory, SQLiteConnectionFactory)

    def test_the_injected_factory_satisfies_the_connection_factory_protocol(self):
        # Arrange / Act / Assert
        assert isinstance(_RecordingConnectionFactory(), ConnectionFactory)

    def test_the_module_does_not_import_aiosqlite(self):
        """A direct aiosqlite dependency would defeat the storage abstraction."""
        # Arrange
        import probos.tools.work_permits as module

        source = inspect.getsource(module)
        # Assert
        assert "aiosqlite" not in source


class TestClockInjection:
    """The clock is a constructor seam, mirroring CrewSessionService."""

    def test_the_default_clock_is_time_time(self):
        """Shipped behaviour is unchanged: no injection means the wall clock."""
        # Arrange
        signature = inspect.signature(WorkPermitStore.__init__)
        # Assert
        assert signature.parameters["clock"].default is time.time
        assert WorkPermitStore(db_path="")._clock is time.time

    @pytest.mark.asyncio
    async def test_issued_at_and_expires_at_come_from_the_injected_clock(
        self, tmp_path
    ):
        # Arrange
        clock = _FakeClock(now=5_000.0)
        store = await _store(tmp_path, clock=clock)
        try:
            # Act
            permit = await _issue(store, ttl_seconds=90.0)
            # Assert
            assert permit.issued_at == 5_000.0
            assert permit.expires_at == 5_090.0
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_closed_at_comes_from_the_injected_clock(self, tmp_path):
        # Arrange
        db = str(tmp_path / "clock_closed.db")
        clock = _FakeClock(now=7_000.0)
        store = WorkPermitStore(db_path=db, clock=clock)
        await store.start()
        try:
            permit = await _issue(store, ttl_seconds=3600.0)
            clock.advance(30.0)
            # Act
            await store.close_permit(permit.id, closed_by="captain")
            # Assert
            row = list(
                sqlite3.connect(db).execute(
                    "SELECT closed_at FROM work_permits WHERE id = ?", (permit.id,)
                )
            )[0]
            assert row[0] == 7_030.0
        finally:
            await store.stop()

    def test_the_module_never_calls_time_time_directly(self):
        """The seam decays the moment one call site reads the wall clock instead.

        Parallel to the aiosqlite guard above: an abstraction that only most of
        the module honours is not an abstraction. ``time.time`` still appears as
        the parameter default, which is why this asserts on the CALL form.
        """
        # Arrange
        import probos.tools.work_permits as module

        source = inspect.getsource(module)
        # Assert
        assert "time.time()" not in source
        assert source.count("self._clock()") >= 6

    @pytest.mark.asyncio
    async def test_a_frozen_clock_never_expires_a_live_permit(self, tmp_path):
        """Time is the only thing that expires a permit; nothing else does."""
        # Arrange
        clock = _FakeClock()
        store = await _store(tmp_path, clock=clock)
        try:
            await _issue(store, ttl_seconds=1.0)
            # Act / Assert — many reads, no advance, still live
            for _ in range(5):
                assert store.holder_sync("sess-1", "browser") == "agent-holder"
            assert len(store.list_open_sync()) == 1
        finally:
            await store.stop()


class TestRevokePermit:
    @pytest.mark.asyncio
    async def test_revoke_permit_closes_the_permit(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            permit = await _issue(store)
            # Act
            revoked = await store.revoke_permit(permit.id, revoked_by="captain")
            # Assert
            assert revoked is True
            assert store.holder_sync("sess-1", "browser") is None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_revoke_permit_records_the_reason_as_revoked(self, tmp_path):
        """No separate column — revocation is a closure with a distinct reason."""
        # Arrange
        db = str(tmp_path / "revoked.db")
        store = WorkPermitStore(db_path=db)
        await store.start()
        try:
            permit = await _issue(store)
            # Act
            await store.revoke_permit(permit.id, revoked_by="captain")
            row = list(
                sqlite3.connect(db).execute(
                    "SELECT closed, close_reason, closed_by FROM work_permits "
                    "WHERE id = ?",
                    (permit.id,),
                )
            )[0]
            # Assert
            assert row[0] == 1
            assert row[1] == "revoked"
            assert row[2] == "captain"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_revoke_permit_on_unknown_id_returns_false(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            assert await store.revoke_permit("nope", revoked_by="captain") is False
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_revoke_permit_on_empty_id_returns_false(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            assert await store.revoke_permit("", revoked_by="") is False
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_revoke_permit_twice_returns_false(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            permit = await _issue(store)
            await store.revoke_permit(permit.id, revoked_by="captain")
            # Act / Assert
            assert (
                await store.revoke_permit(permit.id, revoked_by="captain") is False
            )
        finally:
            await store.stop()


class TestGetSync:
    @pytest.mark.asyncio
    async def test_get_sync_returns_the_permit(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            permit = await _issue(store, reason="diagnostics")
            # Act
            found = store.get_sync(permit.id)
            # Assert
            assert found is not None
            assert found.id == permit.id
            assert found.reason == "diagnostics"
            assert found.closed is False
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_get_sync_returns_none_for_an_unknown_id(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store)
            # Act / Assert
            assert store.get_sync("nope") is None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_get_sync_returns_none_for_an_empty_id(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store)
            # Act / Assert
            assert store.get_sync("") is None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_get_sync_returns_none_after_closure(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            permit = await _issue(store)
            await store.close_permit(permit.id, closed_by="captain")
            # Act / Assert
            assert store.get_sync(permit.id) is None
        finally:
            await store.stop()


class TestListOpenSync:
    @pytest.mark.asyncio
    async def test_list_open_sync_returns_every_live_permit_when_unfiltered(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, session_id="sess-1", holder_id="agent-a")
            await _issue(store, session_id="sess-2", holder_id="agent-b")
            # Act
            rows = store.list_open_sync()
            # Assert
            assert {p.holder_id for p in rows} == {"agent-a", "agent-b"}
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_list_open_sync_narrows_to_one_session(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, session_id="sess-1", holder_id="agent-a")
            await _issue(store, session_id="sess-2", holder_id="agent-b")
            # Act
            rows = store.list_open_sync("sess-1")
            # Assert
            assert [p.holder_id for p in rows] == ["agent-a"]
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_list_open_sync_on_an_empty_store_returns_an_empty_list(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            assert store.list_open_sync() == []
            assert store.list_open_sync("sess-1") == []
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_list_open_sync_for_an_unknown_session_returns_an_empty_list(
        self, tmp_path
    ):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, session_id="sess-1")
            # Act / Assert
            assert store.list_open_sync("sess-999") == []
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_list_open_sync_excludes_closed_and_expired_permits(
        self, tmp_path
    ):
        # Arrange
        clock = _FakeClock()
        store = await _store(tmp_path, clock=clock)
        try:
            live = await _issue(
                store, workstation_id="browser", holder_id="agent-a",
                ttl_seconds=3600.0,
            )
            closed = await _issue(
                store, workstation_id="monaco", holder_id="agent-b",
                ttl_seconds=3600.0,
            )
            await _issue(
                store, workstation_id="mcp-app", holder_id="agent-c",
                ttl_seconds=60.0,
            )
            assert len(store.list_open_sync()) == 3
            clock.advance(61.0)
            await store.close_permit(closed.id, closed_by="captain")
            # Act
            rows = store.list_open_sync()
            # Assert
            assert [p.id for p in rows] == [live.id]
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_list_open_sync_is_the_only_place_empty_means_unfiltered(
        self, tmp_path
    ):
        """Enumeration grants nothing; the no-wildcard rule governs authorization."""
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, session_id="sess-1", holder_id="agent-a")
            # Act / Assert
            assert len(store.list_open_sync("")) == 1
            assert store.holder_sync("", "browser") is None
            assert store.permitted_tier_sync("agent-a", "", "browser") == 0
        finally:
            await store.stop()


class TestHolderSync:
    @pytest.mark.asyncio
    async def test_holder_sync_returns_the_holder(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            await _issue(store, holder_id="agent-a")
            # Act / Assert
            assert store.holder_sync("sess-1", "browser") == "agent-a"
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_holder_sync_returns_none_for_an_unoccupied_space(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act / Assert
            assert store.holder_sync("sess-1", "browser") is None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_holder_sync_returns_none_after_closure(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            permit = await _issue(store, holder_id="agent-a")
            await store.close_permit(permit.id, closed_by="captain")
            # Act / Assert
            assert store.holder_sync("sess-1", "browser") is None
        finally:
            await store.stop()


class TestIssuePermitRecord:
    @pytest.mark.asyncio
    async def test_issue_permit_returns_a_fully_populated_record(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act
            permit = await _issue(
                store,
                session_id="sess-7",
                workstation_id="monaco",
                holder_id="agent-a",
                issued_by="captain",
                max_tier=1,
                ttl_seconds=60.0,
                reason="read the diff",
            )
            # Assert
            assert permit.id
            assert permit.session_id == "sess-7"
            assert permit.workstation_id == "monaco"
            assert permit.holder_id == "agent-a"
            assert permit.issued_by == "captain"
            assert permit.max_tier == 1
            assert permit.reason == "read the diff"
            assert permit.issued_at > 0
            assert permit.expires_at == pytest.approx(permit.issued_at + 60.0)
            assert permit.closed is False
            assert permit.closed_at is None
            assert permit.close_reason == ""
            assert permit.closed_by == ""
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_defaults_reason_to_empty(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act
            permit = await _issue(store)
            # Assert
            assert permit.reason == ""
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_issue_permit_ids_are_unique(self, tmp_path):
        # Arrange
        store = await _store(tmp_path)
        try:
            # Act
            a = await _issue(store, workstation_id="browser")
            b = await _issue(store, workstation_id="monaco")
            # Assert
            assert a.id != b.id
        finally:
            await store.stop()

    def test_issue_permit_takes_only_keyword_arguments(self):
        """Six near-identical string parameters positionally is a swap waiting to happen."""
        # Act
        signature = inspect.signature(WorkPermitStore.issue_permit)
        # Assert
        for name, parameter in signature.parameters.items():
            if name == "self":
                continue
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, name


class TestPublicApiIsFullyAnnotated:
    @pytest.mark.parametrize(
        "name",
        [
            "start",
            "stop",
            "issue_permit",
            "close_permit",
            "revoke_permit",
            "holder_sync",
            "permitted_tier_sync",
            "get_sync",
            "list_open_sync",
        ],
    )
    def test_every_public_method_annotates_parameters_and_return(self, name):
        # Act
        signature = inspect.signature(getattr(WorkPermitStore, name))
        # Assert
        assert signature.return_annotation is not inspect.Signature.empty, name
        for parameter_name, parameter in signature.parameters.items():
            if parameter_name == "self":
                continue
            assert (
                parameter.annotation is not inspect.Parameter.empty
            ), f"{name}.{parameter_name}"


# ---------------------------------------------------------------------------
# Config — default-OFF byte identity
# ---------------------------------------------------------------------------


class TestConfig:
    def test_work_permits_are_off_by_default(self):
        # Act
        config = ApprovalInboxConfig()
        # Assert
        assert config.work_permits_enabled is False

    def test_work_permits_are_off_by_default_on_the_system_config(self):
        # Act
        config = SystemConfig()
        # Assert
        assert config.approval_inbox.work_permits_enabled is False

    def test_default_ttl_is_one_hour(self):
        # Act
        config = ApprovalInboxConfig()
        # Assert
        assert config.work_permit_default_ttl_seconds == 3600.0

    def test_default_tier_ceiling_excludes_tier_three(self):
        """Tier 3 needs an explicit Captain issue, not an inherited default."""
        # Act
        config = ApprovalInboxConfig()
        # Assert
        assert config.work_permit_max_tier_ceiling == 2

    @pytest.mark.parametrize("value", [0.0, -1.0])
    def test_a_non_positive_default_ttl_is_rejected(self, value):
        # Act / Assert
        with pytest.raises(Exception):
            ApprovalInboxConfig(work_permit_default_ttl_seconds=value)

    @pytest.mark.parametrize("value", [0, 4])
    def test_a_tier_ceiling_outside_the_ladder_is_rejected(self, value):
        # Act / Assert
        with pytest.raises(Exception):
            ApprovalInboxConfig(work_permit_max_tier_ceiling=value)

    def test_the_three_fields_carry_descriptions(self):
        # Act
        fields = ApprovalInboxConfig.model_fields
        # Assert
        for name in (
            "work_permits_enabled",
            "work_permit_default_ttl_seconds",
            "work_permit_max_tier_ceiling",
        ):
            assert fields[name].description, name

    def test_existing_approval_inbox_defaults_are_unchanged(self):
        """Adding three fields must not perturb the AD-1154 surface."""
        # Act
        config = ApprovalInboxConfig()
        # Assert
        assert config.enabled is False
        assert config.standing_rules_enabled is False
        assert config.standing_rule_max_ttl_hours == 168
        assert config.standing_rule_default_ttl_hours == 24
        assert config.max_pending_per_agent == 20
        assert config.pending_ask_ttl_hours == 72


# ---------------------------------------------------------------------------
# Boundaries this AD must NOT cross
# ---------------------------------------------------------------------------


class TestUntouchedNeighbours:
    def test_browser_loop_actions_is_byte_identical(self):
        """A permit's tier ceiling and the loop allowlist are different axes."""
        # Assert
        assert _BROWSER_LOOP_ACTIONS == frozenset(
            {"goto", "state", "extract_text", "back", "forward", "wait"}
        )

    def test_browser_loop_actions_is_still_a_frozenset(self):
        # Assert
        assert isinstance(_BROWSER_LOOP_ACTIONS, frozenset)

    def test_classify_action_still_returns_the_three_tier_ladder(self):
        """This AD reads the tier vocabulary; it does not alter it."""
        # Arrange
        from probos.tools.browser.actions import classify_action

        # Act / Assert — one representative per tier. A ``None`` session is the
        # AD-1154 precedent: all three of these short-circuit before the
        # classifier reads ``session._config``.
        assert classify_action(None, "state", {}) == 1
        assert classify_action(None, "goto", {"url": "https://example.com"}) == 2
        assert classify_action(None, "eval_js", {}) == 3

    def test_the_store_has_no_transfer_method(self):
        """Agent-to-agent transfer is AD-1161."""
        # Assert
        assert not hasattr(WorkPermitStore, "transfer_permit")
