"""AD-1228 (#1201): the standing-interest store and its five config fields.

A standing interest is an agent's registration to be told when one declared
condition becomes true. These tests cover the data half: the store keeps live
registrations only -- bounded per agent, each with a NOT NULL expiry, deleted on
revoke or expiry -- on a real SQLite database wherever the claim is about
persistence, and the config that turns the feature on (default OFF).
"""

from __future__ import annotations

import contextlib
import inspect
import math
import re
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from probos.cognitive.standing_interest_store import (
    _SCHEMA,
    CROSS_AGENT_KINDS,
    KINDS,
    SELF_SIMILARITY_HIGH,
    TRUST_FALLING,
    WORK_ITEM_FINISHED,
    StandingInterest,
    StandingInterestLimitReached,
    StandingInterestStore,
    StandingInterestUnavailable,
)
from probos.config import ProactiveCognitiveConfig, SystemConfig

_NOW = 1_000_000.0
_HOUR = 3600.0
TROI = "counselor_counselor_0_aa"
WORF = "security_officer_0_bb"
DATA = "science_officer_0_cc"
ITEM = "c071280fc286"


class _Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@contextlib.asynccontextmanager
async def _running(
    path: Path | None, clock: _Clock, **kwargs: Any,
) -> AsyncIterator[StandingInterestStore]:
    store = StandingInterestStore(db_path=str(path) if path is not None else "", clock=clock, **kwargs)
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


def _rows(path: Path) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT id, agent_id, kind, subject_id, created_at, expires_at FROM standing_interests "
            "ORDER BY created_at, id"
        ).fetchall()
    finally:
        conn.close()


_OMIT = object()


def _insert(path: Path, **row: Any) -> None:
    """A raw INSERT through sqlite3, bypassing the store (what only the schema can refuse)."""
    row = {column: value for column, value in row.items() if value is not _OMIT}
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            f"INSERT INTO standing_interests ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
            tuple(row.values()),
        )
        conn.commit()
    finally:
        conn.close()


class _NoConnect:
    """A connection factory that must never be asked (cache-only mode)."""

    async def connect(self, db_path: str) -> Any:
        raise AssertionError(f"AD-1228 test: a cache-only store opened {db_path!r}")


class _RecordingFactory:
    """The default SQLite factory, recording every connect."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    async def connect(self, db_path: str) -> Any:
        from probos.storage.sqlite_factory import default_factory

        self.paths.append(db_path)
        return await default_factory.connect(db_path)


class _Gate:
    """A real connection whose commit, every statement, or statements with one prefix raise when asked."""

    def __init__(self, inner: Any, factory: _GateFactory) -> None:
        self._inner = inner
        self._factory = factory

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        prefix = self._factory.fail_prefix
        if self._factory.fail_execute or (prefix and str(args[0]).startswith(prefix)):
            raise sqlite3.OperationalError("AD-1228 test: the database is unreachable")
        return self._inner.execute(*args, **kwargs)

    async def commit(self) -> None:
        if self._factory.fail_commit:
            raise sqlite3.OperationalError("AD-1228 test: the commit failed")
        await self._inner.commit()

    async def close(self) -> None:
        self._factory.closed += 1
        await self._inner.close()


class _GateFactory:
    def __init__(self) -> None:
        self.fail_commit = False
        self.fail_execute = False
        self.fail_prefix = ""
        self.connected = 0
        self.closed = 0

    async def connect(self, db_path: str) -> Any:
        from probos.storage.sqlite_factory import default_factory

        self.connected += 1
        return _Gate(await default_factory.connect(db_path), self)


# ===========================================================================
# The store
# ===========================================================================


async def test_register_persists_and_survives_restart_on_a_real_database(tmp_path: Path) -> None:
    path = tmp_path / "si.db"
    clock = _Clock(_NOW)
    async with _running(path, clock) as first:
        record, renewed = await first.register(
            agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=24 * _HOUR, max_live=12,
        )
        assert renewed is False
        assert re.fullmatch(r"[0-9a-f]{32}", record.id)

    async with _running(path, clock) as second:
        reloaded = second.live()

    assert reloaded == [record]
    assert (record.agent_id, record.kind, record.subject_id) == (TROI, TRUST_FALLING, WORF)
    assert record.created_at == pytest.approx(_NOW)
    assert record.expires_at == pytest.approx(_NOW + 24 * _HOUR)
    assert _rows(path) == [(record.id, TROI, TRUST_FALLING, WORF, _NOW, _NOW + 24 * _HOUR)]


async def test_register_renews_a_live_key_in_place_without_a_new_row(tmp_path: Path) -> None:
    path = tmp_path / "si.db"
    clock = _Clock(_NOW)
    async with _running(path, clock) as store:
        first, first_renewed = await store.register(
            agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=_HOUR, max_live=12,
        )
        clock.t = _NOW + 60
        second, renewed = await store.register(
            agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=2 * _HOUR, max_live=12,
        )
        assert (first_renewed, renewed) == (False, True)
        assert second.id == first.id
        assert second.expires_at == pytest.approx(_NOW + 60 + 2 * _HOUR)
        assert second.expires_at > first.expires_at
        assert store.live() == [second]

    assert _rows(path) == [(first.id, TROI, TRUST_FALLING, WORF, _NOW, _NOW + 60 + 2 * _HOUR)]


async def test_the_per_agent_cap_refuses_a_new_key_but_allows_renewal(tmp_path: Path) -> None:
    clock = _Clock(_NOW)
    async with _running(tmp_path / "si.db", clock) as store:
        a, _ = await store.register(agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=_HOUR, max_live=2)
        b, _ = await store.register(agent_id=TROI, kind=TRUST_FALLING, subject_id=DATA, ttl_seconds=_HOUR, max_live=2)

        with pytest.raises(StandingInterestLimitReached) as refused:
            await store.register(agent_id=TROI, kind=SELF_SIMILARITY_HIGH, subject_id=WORF, ttl_seconds=_HOUR, max_live=2)
        assert refused.value.limit == 2
        renewed_a, renewed = await store.register(
            agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=2 * _HOUR, max_live=2,
        )
        assert renewed is True and renewed_a.id == a.id  # renewal costs no slot
        other, _ = await store.register(  # the cap is per holder
            agent_id=DATA, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=_HOUR, max_live=2,
        )

        assert sorted(r.id for r in store.live_for_holder(TROI)) == sorted([a.id, b.id])
        assert store.live_for_holder(DATA) == [other]


async def test_an_expired_registration_reads_as_absent_and_start_purges_it(tmp_path: Path) -> None:
    path = tmp_path / "si.db"
    clock = _Clock(_NOW)
    async with _running(path, clock) as store:
        record, _ = await store.register(agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=60, max_live=12)
        clock.t = _NOW + 59
        assert store.live() == [record]  # premise: live until its expiry
        clock.t = _NOW + 60
        assert store.live() == []
        assert store.live(TRUST_FALLING) == []
        assert store.live_for_holder(TROI) == []
        assert store.live_for_subject(TRUST_FALLING, WORF) == []
        assert store.live_naming(WORF) == []

    assert [row[0] for row in _rows(path)] == [record.id]  # premise: the row is still on disk
    async with _running(path, clock) as restarted:
        assert restarted.live() == []
    assert _rows(path) == []  # start() deleted it


async def test_revoke_deletes_only_the_holders_own_row(tmp_path: Path) -> None:
    path = tmp_path / "si.db"
    clock = _Clock(_NOW)
    async with _running(path, clock) as store:
        mine, _ = await store.register(agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=_HOUR, max_live=12)
        theirs, _ = await store.register(agent_id=DATA, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=_HOUR, max_live=12)

        assert await store.revoke(mine.id, agent_id=DATA) is False  # not the holder
        assert store.live_for_holder(TROI) == [mine]
        for junk in ("", "abc", mine.id.upper(), mine.id + "0", 7, None):
            assert await store.revoke(junk, agent_id=TROI) is False, junk
        assert await store.revoke(mine.id, agent_id="") is False

        assert await store.revoke(mine.id, agent_id=TROI) is True
        assert await store.revoke(mine.id, agent_id=TROI) is False
        assert store.live() == [theirs]

    assert [row[0] for row in _rows(path)] == [theirs.id]


_VALID_ROW: dict[str, Any] = {
    "id": "a" * 32,
    "agent_id": TROI,
    "kind": TRUST_FALLING,
    "subject_id": WORF,
    "created_at": _NOW,
    "expires_at": _NOW + 60,
}
_BAD_ROWS: dict[str, dict[str, Any]] = {
    "no_expires_at": {"expires_at": _OMIT},
    "expiry_not_after_creation": {"expires_at": _NOW},
    "unknown_kind": {"kind": "anything_at_all"},
    "empty_agent": {"agent_id": ""},
    "short_id": {"id": "b" * 31},
}


@pytest.mark.parametrize("case", sorted(_BAD_ROWS))
async def test_the_schema_refuses_rows_without_expiry_or_outside_the_vocabulary(
    tmp_path: Path, case: str,
) -> None:
    path = tmp_path / "si.db"
    async with _running(path, _Clock(_NOW)):
        pass
    _insert(path, **_VALID_ROW)  # premise: the base row is accepted

    with pytest.raises(sqlite3.IntegrityError):
        _insert(path, **{**_VALID_ROW, "id": "c" * 32, "subject_id": DATA, **_BAD_ROWS[case]})
    assert [row[0] for row in _rows(path)] == ["a" * 32]


_BAD_ARGUMENTS: dict[str, dict[str, Any]] = {
    "ttl_true": {"ttl_seconds": True},
    "ttl_zero": {"ttl_seconds": 0},
    "ttl_negative": {"ttl_seconds": -1.0},
    "ttl_nan": {"ttl_seconds": math.nan},
    "ttl_inf": {"ttl_seconds": math.inf},
    "blank_agent": {"agent_id": "  "},
    "blank_subject": {"subject_id": ""},
    "unknown_kind": {"kind": "trust_rising"},
    "long_subject": {"subject_id": "x" * 129},
}


@pytest.mark.parametrize("case", sorted(_BAD_ARGUMENTS))
async def test_register_refuses_invalid_arguments(tmp_path: Path, case: str) -> None:
    async with _running(tmp_path / "si.db", _Clock(_NOW)) as store:
        arguments: dict[str, Any] = {
            "agent_id": TROI, "kind": TRUST_FALLING, "subject_id": WORF, "ttl_seconds": 60.0, "max_live": 12,
        }
        with pytest.raises(ValueError, match="AD-1228"):
            await store.register(**{**arguments, **_BAD_ARGUMENTS[case]})
        assert store.live() == []
        control, _ = await store.register(**arguments)
        assert store.live() == [control]


async def test_the_store_is_unavailable_before_start_after_stop_and_on_a_bad_clock(tmp_path: Path) -> None:
    clock = _Clock(_NOW)
    store = StandingInterestStore(db_path=str(tmp_path / "si.db"), clock=clock)

    async def assert_unavailable() -> None:
        for read in (
            store.live, lambda: store.live_for_holder(TROI),
            lambda: store.live_for_subject(TRUST_FALLING, WORF), lambda: store.live_naming(WORF),
        ):
            with pytest.raises(StandingInterestUnavailable):
                read()
        with pytest.raises(StandingInterestUnavailable):
            await store.register(agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=60, max_live=12)
        with pytest.raises(StandingInterestUnavailable):
            await store.revoke("a" * 32, agent_id=TROI)

    await assert_unavailable()
    await store.start()
    try:
        record, _ = await store.register(agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=60, max_live=12)
        assert store.live() == [record]  # premise: running
        for bad in (math.nan, math.inf, "now", None):
            clock.t = bad
            with pytest.raises(StandingInterestUnavailable):
                store.live()
            with pytest.raises(StandingInterestUnavailable):
                await store.register(agent_id=TROI, kind=TRUST_FALLING, subject_id=DATA, ttl_seconds=60, max_live=12)
        clock.t = _NOW
        assert store.live() == [record]  # a bad clock changed nothing
    finally:
        await store.stop()
    await assert_unavailable()


async def test_a_failed_commit_leaves_the_cache_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "si.db"
    clock = _Clock(_NOW)
    factory = _GateFactory()
    async with _running(path, clock, connection_factory=factory) as store:
        first, _ = await store.register(agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=_HOUR, max_live=12)
        factory.fail_commit = True
        clock.t = _NOW + 10

        with pytest.raises(sqlite3.OperationalError):  # a new key
            await store.register(agent_id=TROI, kind=TRUST_FALLING, subject_id=DATA, ttl_seconds=_HOUR, max_live=12)
        assert store.live() == [first]
        with pytest.raises(sqlite3.OperationalError):  # a renewal
            await store.register(agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=5 * _HOUR, max_live=12)
        assert store.live() == [first] and store.live()[0].expires_at == first.expires_at
        with pytest.raises(sqlite3.OperationalError):  # a revoke
            await store.revoke(first.id, agent_id=TROI)
        assert store.live() == [first]
        factory.fail_commit = False

    assert _rows(path) == [(first.id, TROI, TRUST_FALLING, WORF, _NOW, _NOW + _HOUR)]  # every failed write rolled back
    async with _running(path, clock) as restarted:
        assert restarted.live() == [first]


async def test_lookups_are_synchronous_cache_reads_by_holder_subject_and_naming(tmp_path: Path) -> None:
    clock = _Clock(_NOW)
    factory = _GateFactory()
    async with _running(tmp_path / "si.db", clock, connection_factory=factory) as store:
        a_worf, _ = await store.register(agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=_HOUR, max_live=12)
        clock.t = _NOW + 1
        d_worf, _ = await store.register(agent_id=DATA, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=_HOUR, max_live=12)
        clock.t = _NOW + 2
        a_data, _ = await store.register(agent_id=TROI, kind=SELF_SIMILARITY_HIGH, subject_id=DATA, ttl_seconds=_HOUR, max_live=12)
        clock.t = _NOW + 3
        w_item, _ = await store.register(agent_id=WORF, kind=WORK_ITEM_FINISHED, subject_id=ITEM, ttl_seconds=_HOUR, max_live=12)
        clock.t = _NOW + 4
        w_self, _ = await store.register(agent_id=WORF, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=_HOUR, max_live=12)
        factory.fail_execute = True  # from here on, any database access would raise

        for name in ("live", "live_for_holder", "live_for_subject", "live_naming"):
            assert not inspect.iscoroutinefunction(getattr(StandingInterestStore, name)), name
        assert store.live() == [a_worf, d_worf, a_data, w_item, w_self]
        assert store.live(WORK_ITEM_FINISHED) == [w_item]
        assert store.live_for_holder(TROI) == [a_worf, a_data]
        assert store.live_for_subject(TRUST_FALLING, WORF) == [a_worf, d_worf, w_self]
        # Cross-agent kinds naming WORF held by someone else: not WORF's own work item, not WORF's own row.
        assert store.live_naming(WORF) == [a_worf, d_worf]
        assert store.live_naming(ITEM) == []
        factory.fail_execute = False


async def test_the_schema_kind_list_equals_the_vocabulary() -> None:
    match = re.search(r"kind IN \(([^)]*)\)", _SCHEMA)
    assert match is not None, "the schema has no kind CHECK"
    literal = [token.strip().strip("'") for token in match.group(1).split(",")]
    assert literal == sorted(KINDS)
    assert KINDS == {WORK_ITEM_FINISHED, TRUST_FALLING, SELF_SIMILARITY_HIGH}
    assert CROSS_AGENT_KINDS == {TRUST_FALLING, SELF_SIMILARITY_HIGH}
    assert "expires_at REAL NOT NULL" in _SCHEMA


async def test_the_connection_factory_is_injected_and_cache_only_needs_no_database(tmp_path: Path) -> None:
    path = tmp_path / "si.db"
    factory = _RecordingFactory()
    async with _running(path, _Clock(_NOW), connection_factory=factory) as store:
        record, _ = await store.register(agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=_HOUR, max_live=12)
    async with _running(path, _Clock(_NOW), connection_factory=factory) as restarted:
        assert restarted.live() == [record]
    assert factory.paths == [str(path), str(path)]

    before = sorted(p.name for p in tmp_path.iterdir())
    clock = _Clock(_NOW)
    async with _running(None, clock, connection_factory=_NoConnect()) as cache_only:
        kept, _ = await cache_only.register(agent_id=TROI, kind=TRUST_FALLING, subject_id=WORF, ttl_seconds=60, max_live=12)
        assert cache_only.live() == [kept] and isinstance(kept, StandingInterest)
        assert await cache_only.revoke(kept.id, agent_id=DATA) is False
        assert await cache_only.revoke(kept.id, agent_id=TROI) is True
        assert cache_only.live() == []
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # no file was created


_START_FAILURES = {"pragma_rejected": "PRAGMA"}


@pytest.mark.parametrize("case", sorted(_START_FAILURES))
async def test_a_start_that_fails_after_connecting_closes_the_injected_connection(
    tmp_path: Path, case: str,
) -> None:
    factory = _GateFactory()
    factory.fail_prefix = _START_FAILURES[case]
    store = StandingInterestStore(db_path=str(tmp_path / "si.db"), clock=_Clock(_NOW), connection_factory=factory)

    with pytest.raises(sqlite3.OperationalError):
        await store.start()

    assert (factory.connected, factory.closed) == (1, 1)  # the injected connection was opened, then closed
    with pytest.raises(StandingInterestUnavailable):
        store.live()  # it stays stopped
    factory.fail_prefix = ""
    await store.start()  # control: the same store starts cleanly once the statement is accepted
    try:
        assert store.live() == []
    finally:
        await store.stop()
    assert (factory.connected, factory.closed) == (2, 2)


# ===========================================================================
# Config
# ===========================================================================


def test_the_standing_interest_config_fields_default_off_and_validate_bounds() -> None:
    config = ProactiveCognitiveConfig()

    assert (
        config.standing_interests_enabled, config.standing_interest_max_per_agent,
        config.standing_interest_default_ttl_hours, config.standing_interest_max_ttl_hours,
        config.standing_interest_min_fire_interval_seconds,
    ) == (False, 12, 24, 168, 3600)
    assert SystemConfig().proactive_cognitive.standing_interests_enabled is False
    bounds = {
        "standing_interest_max_per_agent": (1, 32),
        "standing_interest_default_ttl_hours": (1, 720),
        "standing_interest_max_ttl_hours": (1, 720),
        "standing_interest_min_fire_interval_seconds": (60, 86_400),
    }
    for name in ("standing_interests_enabled", *bounds):
        assert "AD-1228" in (ProactiveCognitiveConfig.model_fields[name].description or ""), name
    for name, (low, high) in bounds.items():
        for value in (low - 1, high + 1):
            with pytest.raises(ValidationError):
                ProactiveCognitiveConfig(**{name: value})
        assert getattr(ProactiveCognitiveConfig(**{name: low}), name) == low  # control
        assert getattr(ProactiveCognitiveConfig(**{name: high}), name) == high
