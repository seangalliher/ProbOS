"""AD-1214 (#1171): the decision pre-clearance store, the exact key, and its scope text.

A pre-clearance stops the Captain's notification for one exact class of
delegated decision and confers no authority. These tests cover the data half:
the eight-field key that makes a wildcard unrepresentable, the store that keeps
pre-clearances expiring and revocable (a real SQLite database wherever the
claim is about persistence), the in-memory offers, the text the Captain
consents to, and the three config fields.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
import math
import secrets
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.config import SystemConfig
from probos.config_models.experience import ApprovalInboxConfig
from probos.decision_pre_clearance import (
    _CLASSES,
    _ROLES,
    MAX_OFFERS,
    OFFER_ID_RE,
    PRE_CLEAR_ACTION_PREFIX,
    DecisionPreClearanceStore,
    PreClearance,
    PreClearanceKey,
    PreClearanceUnavailable,
    confirm_pre_clearance,
    describe_scope,
    make_offer,
    offer_sentence,
    pre_clearance_key,
)
from probos.delegated_approvals import DeciderRole, RequestClass

_NOW = 1_000_000.0
_DAY = 24 * 3600


class _Clock:
    def __init__(self, t: float) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


_BASE: dict[str, str] = {
    "queue": "capability",
    "kind": "grant",
    "target": "calc_tool",
    "request_class": "non_destructive",
    "requester_department": "engineering",
    "decider_post": "chief_engineer",
    "decider_role": "department_chief",
    "decision": "approve",
}


def _key(**overrides: str) -> PreClearanceKey:
    """A chief engineer approving an engineering crew member's read grant, with overrides."""
    return PreClearanceKey(**{**_BASE, **overrides})


@contextlib.asynccontextmanager
async def _running(
    path: Path | None, clock: _Clock, **kwargs: Any,
) -> AsyncIterator[DecisionPreClearanceStore]:
    store = DecisionPreClearanceStore(db_path=str(path) if path is not None else "", clock=clock, **kwargs)
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


def _rows(path: Path) -> list[tuple[Any, ...]]:
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT id, revoked, revoked_by, expires_at FROM decision_pre_clearances ORDER BY issued_at"
        ).fetchall()
    finally:
        conn.close()


_OMIT = object()
_ROW: dict[str, Any] = {
    **_BASE,
    "issued_by": "captain",
    "reason": "",
    "issued_at": _NOW,
    "expires_at": _NOW + 60,
}


def _insert(path: Path, row_id: str, **overrides: Any) -> None:
    """A raw INSERT through sqlite3, bypassing the store (what only the schema can refuse)."""
    row = {"id": row_id, **_ROW, **overrides}
    row = {column: value for column, value in row.items() if value is not _OMIT}
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            f"INSERT INTO decision_pre_clearances ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})",
            tuple(row.values()),
        )
        conn.commit()
    finally:
        conn.close()


class _NoConnect:
    """A connection factory that must never be asked (cache-only mode)."""

    async def connect(self, db_path: str) -> Any:
        raise AssertionError(f"AD-1214 test: a cache-only store opened {db_path!r}")


class _RecordingFactory:
    """The default SQLite factory, recording every connect."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    async def connect(self, db_path: str) -> Any:
        from probos.storage.sqlite_factory import default_factory

        self.paths.append(db_path)
        return await default_factory.connect(db_path)


class _CommitGate:
    """A real connection whose commit raises while its factory's ``fail`` is set."""

    def __init__(self, inner: Any, factory: _FailingCommitFactory) -> None:
        self._inner = inner
        self._factory = factory

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def commit(self) -> None:
        if self._factory.fail:
            raise sqlite3.OperationalError("AD-1214 test: the commit failed")
        await self._inner.commit()


class _FailingCommitFactory:
    def __init__(self) -> None:
        self.fail = False

    async def connect(self, db_path: str) -> Any:
        from probos.storage.sqlite_factory import default_factory

        return _CommitGate(await default_factory.connect(db_path), self)


# ===========================================================================
# The store
# ===========================================================================

# Each variant differs from the base key in the named field. A queue cannot
# differ alone -- a kind belongs to one queue -- so that variant moves both.
_VARIANTS: dict[str, dict[str, str]] = {
    "queue": {"queue": "skill", "kind": "skill"},
    "kind": {"kind": "install"},
    "target": {"target": "scan_tool"},
    "request_class": {"request_class": "destructive"},
    "requester_department": {"requester_department": "medical"},
    "decider_post": {"decider_post": "first_officer"},
    "decider_role": {"decider_role": "first_officer"},
    "decision": {"decision": "deny"},
}


@pytest.mark.parametrize("field", sorted(_VARIANTS))
async def test_lookup_matches_only_the_exact_eight_field_key(tmp_path: Path, field: str) -> None:
    async with _running(tmp_path / "dpc.db", _Clock(_NOW)) as store:
        record = await store.issue(_key(), ttl_seconds=3600, issued_by="captain")
        variant = _key(**_VARIANTS[field])
        assert getattr(variant, field) != getattr(_key(), field)  # premise: the variant moves this field

        assert store.lookup(variant) is None
        assert store.lookup(_key()) == record  # an equal key, a distinct instance
        assert store.lookup(record.key) is record


async def test_a_pre_clearance_survives_restart_on_a_real_database(tmp_path: Path) -> None:
    path = tmp_path / "dpc.db"
    clock = _Clock(_NOW)
    async with _running(path, clock) as first:
        record = await first.issue(_key(), ttl_seconds=3600, issued_by="captain", reason="Routine reads.")

    async with _running(path, clock) as second:
        reloaded = second.lookup(_key())

    assert reloaded == record
    assert (reloaded.issued_by, reloaded.reason, reloaded.revoked) == ("captain", "Routine reads.", False)
    assert reloaded.expires_at == pytest.approx(_NOW + 3600)


async def test_an_expired_pre_clearance_reads_as_absent_and_is_not_reloaded(tmp_path: Path) -> None:
    path = tmp_path / "dpc.db"
    clock = _Clock(_NOW)
    async with _running(path, clock) as store:
        record = await store.issue(_key(), ttl_seconds=60, issued_by="captain")
        clock.t = _NOW + 59
        assert store.lookup(_key()) == record  # premise: live until its expiry
        clock.t = _NOW + 60
        assert store.lookup(_key()) is None
        assert store.live() == []

    async with _running(path, clock) as restarted:
        assert restarted.lookup(_key()) is None
    assert [row[0] for row in _rows(path)] == [record.id]  # the row stays on the record


async def test_revoke_ends_the_match_keeps_the_row_and_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "dpc.db"
    clock = _Clock(_NOW)
    async with _running(path, clock) as store:
        record = await store.issue(_key(), ttl_seconds=3600, issued_by="captain")
        other = await store.issue(_key(target="scan_tool"), ttl_seconds=3600, issued_by="captain")
        assert store.lookup(_key()) == record  # premise

        assert await store.revoke(record.id, revoked_by="captain") == 1

        assert store.lookup(_key()) is None
        assert store.lookup(_key(target="scan_tool")) == other
        assert await store.revoke(record.id, revoked_by="captain") == 0

    assert _rows(path) == [(record.id, 1, "captain", record.expires_at), (other.id, 0, "", other.expires_at)]
    async with _running(path, clock) as restarted:
        assert restarted.lookup(_key()) is None
        assert restarted.lookup(_key(target="scan_tool")) == other


async def test_issue_supersedes_the_live_record_for_the_same_key(tmp_path: Path) -> None:
    path = tmp_path / "dpc.db"
    clock = _Clock(_NOW)
    async with _running(path, clock) as store:
        first = await store.issue(_key(), ttl_seconds=3600, issued_by="captain")
        unrelated = await store.issue(_key(decision="deny"), ttl_seconds=3600, issued_by="captain")
        clock.t = _NOW + 1
        second = await store.issue(_key(), ttl_seconds=7200, issued_by="captain")

        assert store.lookup(_key()) == second != first
        assert store.lookup(_key(decision="deny")) == unrelated
        assert store.live() == [unrelated, second]

    rows = {row[0]: row for row in _rows(path)}
    assert set(rows) == {first.id, unrelated.id, second.id}
    assert rows[first.id][1:3] == (1, "captain")  # superseded, not deleted
    assert rows[second.id][1] == 0 and rows[unrelated.id][1] == 0
    async with _running(path, clock) as restarted:
        assert restarted.lookup(_key()) == second


async def test_the_schema_refuses_a_row_without_expiry_or_with_a_value_outside_the_allowlist(
    tmp_path: Path,
) -> None:
    path = tmp_path / "dpc.db"
    async with _running(path, _Clock(_NOW)):
        pass
    _insert(path, "row-valid")  # premise: the base row is accepted

    for index, overrides in enumerate((
        {"expires_at": _OMIT},
        {"expires_at": None},
        {"decision": "any"},
        {"kind": "build"},
        {"target": "*"},
        {"target": ""},
        {"target": "calc tool"},
        {"requester_department": "Engineering"},
        {"decider_post": "chief-engineer"},
        {"decider_role": "captain"},
        {"request_class": "captain_reserved"},
        {"queue": "action"},
    )):
        with pytest.raises(sqlite3.IntegrityError):
            _insert(path, f"row-{index}", **overrides)
    assert [row[0] for row in _rows(path)] == ["row-valid"]


async def test_issue_and_revoke_refuse_invalid_arguments(tmp_path: Path) -> None:
    async with _running(tmp_path / "dpc.db", _Clock(_NOW)) as store:
        for ttl in (True, False, 0, -1, math.nan, math.inf, -math.inf, "60", None):
            with pytest.raises(ValueError):
                await store.issue(_key(), ttl_seconds=ttl, issued_by="captain")
        for issuer in ("", "  ", None, 7):
            with pytest.raises(ValueError):
                await store.issue(_key(), ttl_seconds=60, issued_by=issuer)
        for reason in ("x" * 501, None, 7):
            with pytest.raises(ValueError):
                await store.issue(_key(), ttl_seconds=60, issued_by="captain", reason=reason)
        for key in (dataclasses.asdict(_key()), tuple(_BASE.values()), None, "calc_tool"):
            with pytest.raises(ValueError):
                await store.issue(key, ttl_seconds=60, issued_by="captain")
        assert store.live() == []

        record = await store.issue(_key(), ttl_seconds=60, issued_by="captain", reason="x" * 500)  # control
        for record_id in ("", "  ", None, 7, "x" * 65):
            with pytest.raises(ValueError):
                await store.revoke(record_id, revoked_by="captain")
        for revoker in ("", "  ", None):
            with pytest.raises(ValueError):
                await store.revoke(record.id, revoked_by=revoker)
        assert store.lookup(_key()) == record


async def test_the_store_is_unavailable_before_start_after_stop_and_on_a_bad_clock(tmp_path: Path) -> None:
    clock = _Clock(_NOW)
    store = DecisionPreClearanceStore(db_path=str(tmp_path / "dpc.db"), clock=clock)

    async def assert_unavailable() -> None:
        for read in (lambda: store.lookup(_key()), store.live, lambda: store.offered("a" * 32)):
            with pytest.raises(PreClearanceUnavailable):
                read()
        with pytest.raises(PreClearanceUnavailable):
            await store.issue(_key(), ttl_seconds=60, issued_by="captain")
        with pytest.raises(PreClearanceUnavailable):
            await store.revoke("a" * 12, revoked_by="captain")
        assert store.offer(_key(), ttl_hours=24) is None

    await assert_unavailable()
    await store.start()
    try:
        record = await store.issue(_key(), ttl_seconds=60, issued_by="captain")
        assert store.lookup(_key()) == record and store.live() == [record]  # premise: running
        for bad in (math.nan, math.inf, "now", None):
            clock.t = bad
            with pytest.raises(PreClearanceUnavailable):
                store.lookup(_key())
            with pytest.raises(PreClearanceUnavailable):
                store.live()
            with pytest.raises(PreClearanceUnavailable):
                await store.issue(_key(target="scan_tool"), ttl_seconds=60, issued_by="captain")
        clock.t = _NOW
        assert store.lookup(_key()) == record  # a bad clock changed nothing
    finally:
        await store.stop()
    await assert_unavailable()


async def test_a_failed_commit_leaves_the_cache_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "dpc.db"
    clock = _Clock(_NOW)
    factory = _FailingCommitFactory()
    async with _running(path, clock, connection_factory=factory) as store:
        first = await store.issue(_key(), ttl_seconds=3600, issued_by="captain")
        factory.fail = True

        with pytest.raises(sqlite3.OperationalError):
            await store.issue(_key(), ttl_seconds=7200, issued_by="captain")
        assert store.lookup(_key()) == first
        with pytest.raises(sqlite3.OperationalError):
            await store.revoke(first.id, revoked_by="captain")
        assert store.lookup(_key()) == first
        with pytest.raises(sqlite3.OperationalError):
            await store.issue(_key(target="scan_tool"), ttl_seconds=60, issued_by="captain")
        assert store.lookup(_key(target="scan_tool")) is None
        factory.fail = False

    assert _rows(path) == [(first.id, 0, "", first.expires_at)]  # every failed write rolled back
    async with _running(path, clock) as restarted:
        assert restarted.lookup(_key()) == first


async def test_ambiguous_live_rows_for_one_key_load_as_no_pre_clearance(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "dpc.db"
    clock = _Clock(_NOW)
    async with _running(path, clock) as store:
        record = await store.issue(_key(), ttl_seconds=3600, issued_by="captain")
    async with _running(path, clock) as reloaded:
        assert reloaded.lookup(_key()) == record  # premise: one live row loads
    twin_id = "f" * 36
    _insert(path, twin_id, issued_at=_NOW + 1, expires_at=_NOW + 3600)
    junk_id = "e" * 36  # passes every CHECK, but numpy:extra is not one import name
    _insert(path, junk_id, kind="install", target="numpy:extra", issued_at=_NOW + 1, expires_at=_NOW + 3600)
    skill_id = "d" * 36  # control: a skill row is accepted (revoked, so it never loads)
    _insert(path, skill_id, queue="skill", kind="skill", target="damage_control", revoked=1)
    for queue, kind in (("skill", "grant"), ("capability", "skill")):  # A-4: a kind belongs to one queue
        with pytest.raises(sqlite3.IntegrityError):
            _insert(path, "c" * 36, queue=queue, kind=kind, issued_at=_NOW + 1, expires_at=_NOW + 3600)

    with caplog.at_level(logging.WARNING, logger="probos.decision_pre_clearance"):
        async with _running(path, clock) as ambiguous:
            assert ambiguous.lookup(_key()) is None
            assert ambiguous.live() == []
            clock.t = _NOW + 2
            reissued = await ambiguous.issue(_key(), ttl_seconds=3600, issued_by="captain")
            assert ambiguous.lookup(_key()) == reissued

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(record.id[:12] in text and twin_id[:12] in text for text in warnings), warnings
    assert any(junk_id[:12] in text and "exact class" in text for text in warnings), warnings
    rows = {row[0]: row[1] for row in _rows(path)}
    assert rows == {record.id: 1, twin_id: 1, junk_id: 0, skill_id: 1, reissued.id: 0}  # the re-issue superseded both
    async with _running(path, clock) as restarted:
        assert restarted.lookup(_key()) == reissued


async def test_offers_are_bounded_forgotten_on_restart_and_32_hex(tmp_path: Path) -> None:
    path = tmp_path / "dpc.db"
    idle = DecisionPreClearanceStore(db_path=str(path), clock=_Clock(_NOW))
    assert idle.offer(_key(), ttl_hours=24) is None  # not running: no offer

    async with _running(path, _Clock(_NOW)) as store:
        ids = [store.offer(_key(target=f"tool_{index}"), ttl_hours=24) for index in range(MAX_OFFERS + 1)]
        assert all(type(offer_id) is str and OFFER_ID_RE.fullmatch(offer_id) for offer_id in ids)
        assert len(set(ids)) == MAX_OFFERS + 1
        assert store.offered(ids[0]) is None  # the oldest is evicted
        assert store.offered(ids[1]) == (_key(target="tool_1"), 24)
        assert store.offered(ids[-1]) == (_key(target=f"tool_{MAX_OFFERS}"), 24)

        for hours in (0, 721, True, "24", 24.0, None):
            assert store.offer(_key(), ttl_hours=hours) is None, hours
        assert store.offer(dataclasses.asdict(_key()), ttl_hours=24) is None
        assert store.offer(_key(), ttl_hours=720) is not None  # control: the ceiling itself
        for junk in ("", "A" * 32, "g" * 32, ids[-1][:31], ids[-1] + "0", 7, None, secrets.token_hex(16)):
            assert store.offered(junk) is None, junk
        last = ids[-1]

    async with _running(path, _Clock(_NOW)) as restarted:
        assert restarted.offered(last) is None


async def test_live_lists_only_unexpired_unrevoked_records(tmp_path: Path) -> None:
    clock = _Clock(_NOW)
    async with _running(tmp_path / "dpc.db", clock) as store:
        a = await store.issue(_key(), ttl_seconds=3600, issued_by="captain")
        clock.t = _NOW + 1
        b = await store.issue(_key(target="scan_tool"), ttl_seconds=10, issued_by="captain")
        clock.t = _NOW + 2
        c = await store.issue(_key(decision="deny"), ttl_seconds=3600, issued_by="captain")
        assert store.live() == [a, b, c]  # premise: ordered by issue time
        assert await store.revoke(c.id, revoked_by="captain") == 1

        clock.t = _NOW + 11
        assert store.live() == [a]
        clock.t = _NOW + 12
        d = await store.issue(_key(target="probe_tool"), ttl_seconds=60, issued_by="captain")
        assert store.live() == [a, d]


async def test_a_cache_only_store_needs_no_database(tmp_path: Path) -> None:
    clock = _Clock(_NOW)
    async with _running(None, clock, connection_factory=_NoConnect()) as store:
        record = await store.issue(_key(), ttl_seconds=60, issued_by="captain")
        assert store.lookup(_key()) == record and store.live() == [record]
        offer_id = store.offer(_key(), ttl_hours=24)
        assert store.offered(offer_id) == (_key(), 24)

        assert await store.revoke(record.id, revoked_by="captain") == 1
        assert await store.revoke(record.id, revoked_by="captain") == 0
        assert store.lookup(_key()) is None
        expiring = await store.issue(_key(), ttl_seconds=60, issued_by="captain")
        clock.t = _NOW + 60
        assert await store.revoke(expiring.id, revoked_by="captain") == 0  # already expired
    assert list(tmp_path.iterdir()) == []


async def test_the_connection_factory_is_injected(tmp_path: Path) -> None:
    path = tmp_path / "dpc.db"
    factory = _RecordingFactory()
    async with _running(path, _Clock(_NOW), connection_factory=factory) as store:
        record = await store.issue(_key(), ttl_seconds=3600, issued_by="captain")
    async with _running(path, _Clock(_NOW), connection_factory=factory) as restarted:
        assert restarted.lookup(_key()) == record

    assert factory.paths == [str(path), str(path)]


# ===========================================================================
# The key
# ===========================================================================


def _build(**overrides: Any) -> PreClearanceKey | None:
    fields: dict[str, Any] = {
        "queue": "capability", "kind": "grant", "target": "calc_tool", "install_payload": None,
        "request_class": "non_destructive", "requester_department": "engineering",
        "decider_post": "chief_engineer", "decider_role": "department_chief", "approve": True,
    }
    fields.update(overrides)
    return pre_clearance_key(**fields)


def test_a_key_is_built_only_for_grants_python_installs_and_skills() -> None:
    assert _build() == _key()
    assert _build(approve=False) == _key(decision="deny")
    python = {"install_kind": "python"}
    fo = {"request_class": "destructive", "decider_post": "first_officer", "decider_role": "first_officer"}
    assert _build(kind="install", target="xml.etree", install_payload=python, **fo) == _key(
        kind="install", target="xml.etree", **fo,
    )
    assert _build(queue="skill", kind="skill", target="damage_control") == _key(
        queue="skill", kind="skill", target="damage_control",
    )

    for kind, target in (("build", "new_agent"), ("action", "browser"), ("continue", "dm_agentic")):
        assert _build(kind=kind, target=target) is None, kind
    assert _build(kind="install", target="github", install_payload={"install_kind": "mcp", "mcp_server_id": "github"}, **fo) is None
    assert _build(kind="install", target="feedparser", install_payload=None, **fo) is None  # legacy: no provenance
    for payload in ({"install_kind": "python", "extra": 1}, {"install_kind": "Python"}, "python", {}):
        assert _build(kind="install", target="feedparser", install_payload=payload, **fo) is None, payload
    assert _build(kind="install", target="xml..etree", install_payload=python, **fo) is None
    assert _build(queue="skill", kind="grant") is None and _build(queue="capability", kind="skill") is None


def test_a_key_refuses_blank_hostile_overlong_and_unknown_fields() -> None:
    assert _build(target="a" * 200) is not None  # control: the longest target
    for target in ("*", "%", "?", "calc tool", "calc'tool", 'calc"tool', "calc\ntool", "", "a" * 201,
                   ".calc", "-calc", "calc/tool", "../etc", "calc`tool", 7, None):
        assert _build(target=target) is None, target
    for department in ("Engineering", "chief engineer", "", "a" * 65, "*", "eng%", "1st", "chief-engineer"):
        assert _build(requester_department=department) is None, department
        assert _build(decider_post=department) is None, department
    for request_class in ("captain_reserved", "unclassifiable", "", "NON_DESTRUCTIVE", None):
        assert _build(request_class=request_class) is None, request_class
    for role in ("captain", "", "chief", None):
        assert _build(decider_role=role) is None, role
    for approve in (1, 0, "yes", None, "true"):
        assert _build(approve=approve) is None, approve

    class _Sneaky(str):
        pass

    for field, value in (
        ("decision", "any"), ("decision", "approves"), ("queue", "action"), ("kind", "build"),
        ("target", "*"), ("target", _Sneaky("calc_tool")), ("decider_role", "captain"),
        ("requester_department", "Engineering"), ("queue", "skill"),
    ):
        with pytest.raises(ValueError):
            _key(**{field: value})
    assert set(_CLASSES) == {RequestClass.NON_DESTRUCTIVE.value, RequestClass.DESTRUCTIVE.value}
    assert set(_ROLES) == {DeciderRole.DEPARTMENT_CHIEF.value, DeciderRole.FIRST_OFFICER.value}


def test_the_scope_text_states_every_field_exactly() -> None:
    assert describe_scope(_key()) == (
        "when the chief_engineer post, acting as department chief, approves a request from the "
        "engineering department to grant tool 'calc_tool' (class non_destructive)"
    )
    assert offer_sentence(_key(), hours=24) == (
        "Pre-clear offer (AD-1214): for 24 hours after you accept, you will not be notified when "
        "the chief_engineer post, acting as department chief, approves a request from the "
        "engineering department to grant tool 'calc_tool' (class non_destructive). Each such "
        "decision is still audited, and nothing else is pre-cleared."
    )
    fo = {"decider_post": "first_officer", "decider_role": "first_officer"}
    cases = {
        _key(kind="install", target="xml.etree", request_class="destructive", **fo): (
            "when the first_officer post, acting as First Officer, approves a request from the "
            "engineering department to install Python package 'xml.etree' (class destructive)"
        ),
        _key(queue="skill", kind="skill", target="damage_control", requester_department="medical",
             decider_post="chief_medical"): (
            "when the chief_medical post, acting as department chief, approves a request from the "
            "medical department to train skill 'damage_control' (class non_destructive)"
        ),
        _key(decision="deny", target="scan_tool"): (
            "when the chief_engineer post, acting as department chief, denies a request from the "
            "engineering department to grant tool 'scan_tool' (class non_destructive)"
        ),
        _key(requester_department="security", **fo): (
            "when the first_officer post, acting as First Officer, approves a request from the "
            "security department to grant tool 'calc_tool' (class non_destructive)"
        ),
    }
    for key, text in cases.items():
        assert describe_scope(key) == text
        for field in dataclasses.fields(key):
            if field.name not in ("queue", "decider_role", "decision", "kind"):
                assert getattr(key, field.name) in text, (field.name, text)


class _Book:
    """A pre-clearance book whose offer is scripted."""

    def __init__(self, answer: Any = None, *, raises: bool = False) -> None:
        self.answer = answer
        self.raises = raises
        self.calls: list[tuple[PreClearanceKey, int]] = []

    def lookup(self, key: PreClearanceKey) -> PreClearance | None:
        return None

    def offer(self, key: PreClearanceKey, *, ttl_hours: int) -> str | None:
        self.calls.append((key, ttl_hours))
        if self.raises:
            raise RuntimeError("AD-1214 test: the offer book failed")
        return self.answer


def test_the_offer_sentence_states_hours_audit_and_nothing_else(caplog: pytest.LogCaptureFixture) -> None:
    assert _CAPABILITY_GAP_RE.search("I am unable to decide that") is not None  # premise: the pattern fires
    one = offer_sentence(_key(), hours=1)
    assert one.startswith("Pre-clear offer (AD-1214): for 1 hour after you accept, ")
    assert "hours" not in one
    assert offer_sentence(_key(), hours=168).startswith("Pre-clear offer (AD-1214): for 168 hours after ")
    keys = [
        _key(), _key(decision="deny"), _key(queue="skill", kind="skill", target="damage_control"),
        _key(kind="install", target="numpy", request_class="destructive", decider_post="first_officer",
             decider_role="first_officer"),
    ]
    for key in keys:
        sentence = offer_sentence(key, hours=24)
        assert sentence.endswith(". Each such decision is still audited, and nothing else is pre-cleared.")
        assert describe_scope(key) in sentence
        for text in (describe_scope(key), sentence):
            assert _CAPABILITY_GAP_RE.search(text) is None, text

    offer_id = secrets.token_hex(16)
    book = _Book(offer_id)
    assert make_offer(book, _key(), hours=24) == (PRE_CLEAR_ACTION_PREFIX + offer_id, offer_sentence(_key(), hours=24))
    assert book.calls == [(_key(), 24)]
    for answer in (None, 7, "A" * 32, offer_id[:31], offer_id + "0", "", f" {offer_id}"):
        assert make_offer(_Book(answer), _key(), hours=24) is None, answer
    for hours in (0, -1, True, "24", 24.0, None):
        refused = _Book(offer_id)
        assert make_offer(refused, _key(), hours=hours) is None, hours
        assert refused.calls == []
    assert make_offer(_Book(offer_id), dataclasses.asdict(_key()), hours=24) is None
    with caplog.at_level(logging.WARNING, logger="probos.decision_pre_clearance"):
        assert make_offer(_Book(raises=True), _key(), hours=24) is None
    assert any("could not be recorded" in record.getMessage() for record in caplog.records)


class _RaisingBook:
    """A pre-clearance book whose lookup raises."""

    def lookup(self, key: PreClearanceKey) -> PreClearance | None:
        raise RuntimeError("AD-1214 test: the pre-clearance cache failed")

    def offer(self, key: PreClearanceKey, *, ttl_hours: int) -> str | None:
        return None


async def test_confirm_pre_clearance_keeps_only_the_record_the_book_still_holds(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    clock = _Clock(_NOW)
    async with _running(tmp_path / "dpc.db", clock) as store:
        first = await store.issue(_key(), ttl_seconds=60, issued_by="captain")
        other = await store.issue(_key(target="scan_tool"), ttl_seconds=60, issued_by="captain")
        assert confirm_pre_clearance(store, _key(), first) is first  # premise: the book still holds it
        for book, key, match in ((store, _key(), None), (None, _key(), first), (store, None, first)):
            assert confirm_pre_clearance(book, key, match) is None

        assert await store.revoke(other.id, revoked_by="captain") == 1
        assert confirm_pre_clearance(store, _key(target="scan_tool"), other) is None  # revoked
        clock.t = _NOW + 1
        second = await store.issue(_key(), ttl_seconds=60, issued_by="captain")
        assert confirm_pre_clearance(store, _key(), first) is None  # superseded by another record
        assert confirm_pre_clearance(store, _key(), second) is second
        clock.t = second.expires_at
        assert confirm_pre_clearance(store, _key(), second) is None  # expired

    with caplog.at_level(logging.WARNING, logger="probos.decision_pre_clearance"):
        assert confirm_pre_clearance(store, _key(), second) is None  # stopped: unreadable
        assert confirm_pre_clearance(_RaisingBook(), _key(), second) is None
    warned = [r.getMessage() for r in caplog.records if "could not be re-read" in r.getMessage()]
    assert len(warned) == 2 and all(second.id[:12] in text for text in warned)


# ===========================================================================
# Config
# ===========================================================================


def test_the_pre_clearance_config_fields_default_off_and_validate_bounds() -> None:
    config = ApprovalInboxConfig()

    assert (
        config.decision_pre_clearance_enabled, config.decision_pre_clearance_default_ttl_hours,
        config.decision_pre_clearance_max_ttl_hours,
    ) == (False, 24, 168)
    assert SystemConfig().approval_inbox.decision_pre_clearance_enabled is False
    names = list(ApprovalInboxConfig.model_fields)
    start = names.index("delegated_approvals_enabled")
    new = [
        "decision_pre_clearance_enabled", "decision_pre_clearance_default_ttl_hours",
        "decision_pre_clearance_max_ttl_hours",
    ]
    assert names[start:start + 7] == [
        "delegated_approvals_enabled", "approval_grace_seconds",
        "first_officer_delegation_max_ttl_hours", "captain_unavailable_max_ttl_hours", *new,
    ]
    for name in new:
        assert (ApprovalInboxConfig.model_fields[name].description or "").startswith("AD-1214:"), name
    for name in new[1:]:
        for value in (0, 721, -1):
            with pytest.raises(ValidationError):
                ApprovalInboxConfig(**{name: value})
        assert getattr(ApprovalInboxConfig(**{name: 720}), name) == 720  # control
        assert getattr(ApprovalInboxConfig(**{name: 1}), name) == 1
