"""AD-1328 S2b (#1530) M1: the command approval store and the approval-request parser.

Target: ``probos.execution.command_approvals``; contract ``prompts/ad-1328-s2b-command-policy-escalation.md``
("Tests", M1 #1-11). Real SQLite in ``tmp_path``; the clock is injected; the only raw SQL is stdlib ``sqlite3`` on
the store's own file, and only while the store is stopped. Every test asserts its premise and a negative control.
No real shell, no path separators, no host-specific behaviour (CI is Linux, the author's machine Windows).

Mutants of the campaign of record this file is meant to kill (the orchestrator runs the campaign, not this file):

* St1 -- the single-use guard dropped from the compare-and-set in ``use``: ``test_single_use_scopes_admit_one_run``.
* St2 -- every admitted run recorded as a ``reuse``: ``test_work_item_scope_reuses``.
* St3 -- no rollback after a failed use record: ``test_failed_use_rolls_back``.

Tests beyond the numbered list (marked "beyond M1 #n" in their docstrings) cover the other branches of the same
public methods; they are additions, not replacements.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import sqlite3
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from probos import workforce
from probos.capability_request import THREAD_ID_MAX_CHARS, CapabilityRequest, validate_action_payload
from probos.execution.command_approvals import (
    APPROVER_AUTHORITY,
    CAPTAIN,
    ENDED_WORK_ITEM_STATUSES,
    REUSABLE_APPROVAL_TTL_SECONDS,
    SINGLE_USE_APPROVAL_TTL_SECONDS,
    CommandApproval,
    CommandApprovalAsk,
    CommandApprovalUse,
    SqliteCommandApprovalStore,
    approval_ttl_seconds,
    command_approval_request,
    scope_work_item_id,
    valid_scope_key,
)
from probos.storage.sqlite_factory import default_factory

T0 = 1_000_000.0
AGENT = "agent-a"
OTHER_AGENT = "agent-b"
WORK_ITEM_ID = "wi-1"
WORK_SCOPE = "work_item:wi-1"
OTHER_WORK_SCOPE = "work_item:wi-2"
THREAD_SCOPE = "thread:th-1"
KEY = "ab" * 32
OTHER_KEY = "cd" * 32
DIGEST = "digest-0001"
OTHER_DIGEST = "digest-0002"

_INSERT_APPROVAL = (
    "INSERT INTO command_approvals (request_id, agent_id, scope_key, canonical_key, policy_digest, state, "
    "approver, approver_authority, decided_at, expires_at, uses) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)"
)
_INSERT_USE = (
    "INSERT INTO command_approval_uses (use_id, request_id, agent_id, scope_key, use_kind, used_at) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)


# --------------------------------------------------------------------------------------------------------------
# Stand-ins and helpers
# --------------------------------------------------------------------------------------------------------------


class _Clock:
    """The injected time source. A test moves ``now`` by hand and may set it to a bad value on purpose."""

    def __init__(self, now: Any = T0) -> None:
        self.now = now

    def __call__(self) -> Any:
        return self.now


class _Boom(Exception):
    """The storage failure a test injects."""


class _FailTheUseInsert:
    """One aiosqlite connection behind a wrapper whose ``execute`` raises on ``INSERT INTO command_approval_uses``
    while ``armed``. Every other statement goes to the real connection, and its result is handed back untouched,
    so both ``await db.execute(...)`` and ``async with db.execute(...)`` keep working in the store."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.armed = True
        self.statements: list[str] = []
        self.refused: list[str] = []

    def execute(self, sql: str, parameters: Any = None) -> Any:
        self.statements.append(sql)
        if self.armed and "INSERT INTO command_approval_uses" in sql:
            self.refused.append(sql)
            raise _Boom("the use record could not be written")
        return self._real.execute(sql) if parameters is None else self._real.execute(sql, parameters)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class _Factory:
    """A ``ConnectionFactory`` over the default aiosqlite one, optionally wrapping each connection. It keeps every
    connection it opened so a test can close what a second ``start`` leaves behind."""

    def __init__(self, wrap: Callable[[Any], Any] | None = None) -> None:
        self.opened: list[Any] = []
        self.wrapped: list[Any] = []
        self._wrap = wrap

    async def connect(self, db_path: str) -> Any:
        connection = await default_factory.connect(db_path)
        self.opened.append(connection)
        if self._wrap is None:
            return connection
        wrapper = self._wrap(connection)
        self.wrapped.append(wrapper)
        return wrapper

    async def close_all(self) -> None:
        for connection in self.opened:
            await connection.close()  # a connection that is already closed returns at once


@dataclasses.dataclass
class _Env:
    path: Path
    clock: _Clock
    factory: _Factory
    store: SqliteCommandApprovalStore

    def new_store(self) -> SqliteCommandApprovalStore:
        """Another store object on the same file (what a process restart makes)."""
        return SqliteCommandApprovalStore(str(self.path), connection_factory=self.factory, clock=self.clock)


@contextlib.asynccontextmanager
async def _running(tmp_path: Path, *, wrap: Callable[[Any], Any] | None = None) -> AsyncIterator[_Env]:
    path = tmp_path / "command_approvals.db"
    factory = _Factory(wrap)
    clock = _Clock()
    store = SqliteCommandApprovalStore(str(path), connection_factory=factory, clock=clock)
    environment = _Env(path, clock, factory, store)
    try:
        await store.start()
        yield environment
    finally:
        await store.stop()
        await factory.close_all()


@pytest_asyncio.fixture
async def env(tmp_path: Path) -> AsyncIterator[_Env]:
    async with _running(tmp_path) as environment:
        yield environment


@contextlib.contextmanager
def _raw(path: Path) -> Iterator[sqlite3.Connection]:
    """The stdlib view of the store's file; a test opens it only while the store is stopped."""
    connection = sqlite3.connect(str(path))
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


@contextlib.asynccontextmanager
async def _stopped_raw(environment: _Env) -> AsyncIterator[sqlite3.Connection]:
    """Stop the store, hand out the stdlib connection on its file, then start the store again."""
    await environment.store.stop()
    with pytest.raises(RuntimeError, match="not running"):  # the premise: nothing else holds the file open
        await environment.store.get("req-any")
    try:
        with _raw(environment.path) as connection:
            yield connection
    finally:
        await environment.store.start()


def _decision(**changes: Any) -> dict[str, Any]:
    """The keyword arguments of one well-formed ``record_decision`` (the Captain approving in a work item)."""
    fields: dict[str, Any] = {
        "request_id": "req-1",
        "agent_id": AGENT,
        "scope_key": WORK_SCOPE,
        "canonical_key": KEY,
        "policy_digest": DIGEST,
        "state": "active",
        "approver": "captain",
        "ttl_seconds": 600.0,
    }
    fields.update(changes)
    return fields


async def _use(store: SqliteCommandApprovalStore, row: CommandApproval) -> CommandApprovalUse | None:
    return await store.use(row.request_id, agent_id=row.agent_id, scope_key=row.scope_key)


async def _find(
    store: SqliteCommandApprovalStore, row: CommandApproval, *, state: Any = "active",
) -> CommandApproval | None:
    return await store.find(row.agent_id, row.scope_key, row.canonical_key, row.policy_digest, state=state)


# --------------------------------------------------------------------------------------------------------------
# M1 #1-#3: schema, decisions, lookups
# --------------------------------------------------------------------------------------------------------------


async def test_schema_and_restart(tmp_path: Path) -> None:
    """M1 #1: a decision and the runs it admitted survive a stop and a start on the same file; a second ``start``
    on a running store changes nothing."""
    path = tmp_path / "command_approvals.db"
    clock = _Clock()
    factory = _Factory()
    try:
        first = SqliteCommandApprovalStore(str(path), connection_factory=factory, clock=clock)
        await first.start()
        recorded = await first.record_decision(**_decision())
        assert recorded is not None and recorded.state == "active" and recorded.uses == 0
        run = await _use(first, recorded)
        clock.now += 5.0
        reuse = await _use(first, recorded)
        assert run is not None and reuse is not None  # premise: two runs were admitted before the stop
        assert (run.use_kind, reuse.use_kind) == ("approved_run", "reuse")
        before = await first.get("req-1")
        assert before == dataclasses.replace(recorded, uses=2)
        await first.stop()

        with _raw(path) as raw:  # the store is stopped: the schema is in the file
            names = {name for (name,) in raw.execute("SELECT name FROM sqlite_master")}
        assert {
            "command_approvals",
            "command_approval_uses",
            "idx_command_approvals_identity",
            "ux_command_approval_first_use",
            "idx_command_approval_uses_request",
        } <= names

        second = SqliteCommandApprovalStore(str(path), connection_factory=factory, clock=clock)
        await second.start()
        assert await second.get("req-1") == before
        assert await second.list_uses("req-1") == [run, reuse]

        await second.start()  # a second start on a running store is harmless
        assert await second.get("req-1") == before
        assert await second.list_uses("req-1") == [run, reuse]
        third = await _use(second, recorded)  # ...and the counter carried over: the next run is a reuse, the third
        assert third is not None and third.use_kind == "reuse"
        after = await second.get("req-1")
        assert after is not None and after.uses == 3
        await second.stop()

        # negative control: what persisted is per file, not a property of the store class
        other = SqliteCommandApprovalStore(str(tmp_path / "another.db"), connection_factory=factory, clock=clock)
        await other.start()
        assert await other.get("req-1") is None
        assert await other.list_uses("req-1") == []
        await other.stop()
    finally:
        await factory.close_all()


_REJECTED_DECISIONS: tuple[tuple[str, dict[str, Any], str], ...] = (
    ("empty_agent", {"agent_id": ""}, "command_approval_agent_id_invalid"),
    ("empty_request_id", {"request_id": ""}, "command_approval_request_id_invalid"),
    ("empty_digest", {"policy_digest": ""}, "command_approval_policy_digest_invalid"),
    ("long_digest", {"policy_digest": "d" * 129}, "command_approval_policy_digest_invalid"),
    ("short_key", {"canonical_key": "a" * 63}, "command_approval_canonical_key_invalid"),
    ("long_key", {"canonical_key": "a" * 65}, "command_approval_canonical_key_invalid"),
    ("non_hex_key", {"canonical_key": "g" * 64}, "command_approval_canonical_key_invalid"),
    ("other_scope", {"scope_key": "other:x"}, "command_approval_scope_invalid"),
    ("empty_thread_scope", {"scope_key": "thread:"}, "command_approval_scope_invalid"),
    ("zero_ttl", {"ttl_seconds": 0}, "command_approval_ttl_invalid"),
    ("nan_ttl", {"ttl_seconds": float("nan")}, "command_approval_ttl_invalid"),
    ("negative_ttl", {"ttl_seconds": -1.0}, "command_approval_ttl_invalid"),
    ("infinite_ttl", {"ttl_seconds": float("inf")}, "command_approval_ttl_invalid"),
    ("unknown_state", {"state": "x"}, "command_approval_state_invalid"),
    ("blank_approver", {"approver": "   "}, "command_approval_approver_invalid"),
    ("missing_approver", {"approver": None}, "command_approval_approver_invalid"),
)


async def _assert_rejected(
    store: SqliteCommandApprovalStore, case: str, fields: dict[str, Any], code: str,
) -> None:
    try:
        await store.record_decision(**fields)
    except ValueError as exc:
        assert code in str(exc), f"{case}: rejected for the wrong reason: {exc}"
    else:
        pytest.fail(f"{case}: a malformed decision was accepted")


async def test_record_decision_first_wins_and_validates(env: _Env) -> None:
    """M1 #2: the first decision on a request is the decision; a replay with another state, approver or ttl returns
    the first row unchanged. A malformed identity, state, approver or ttl raises ``ValueError`` and writes nothing."""
    store, clock = env.store, env.clock

    first = await store.record_decision(**_decision())
    assert first == CommandApproval(
        request_id="req-1", agent_id=AGENT, scope_key=WORK_SCOPE, canonical_key=KEY, policy_digest=DIGEST,
        state="active", approver="captain", approver_authority="captain",
        decided_at=T0, expires_at=T0 + 600.0, uses=0,
    )
    assert (first.approver_authority, APPROVER_AUTHORITY, CAPTAIN) == ("captain", "captain", "captain")

    clock.now = T0 + 30.0
    replay = await store.record_decision(**_decision(state="denied", approver="someone-else", ttl_seconds=60.0))
    assert replay == first  # the replay changed nothing and returned the first row
    assert await store.get("req-1") == first
    assert await store.find(AGENT, WORK_SCOPE, KEY, DIGEST, state="denied") is None  # it wrote no denial

    denied = await store.record_decision(**_decision(request_id="req-2", state="denied"))
    assert denied is not None and denied.state == "denied"
    assert await store.record_decision(**_decision(request_id="req-2", state="active")) == denied  # either way round
    assert await _use(store, denied) is None  # a denial admits nothing
    assert (await store.get("req-1")) == first  # negative control: the replays of req-2 left req-1 alone

    for case, changes, code in _REJECTED_DECISIONS:
        fields = _decision(**{"request_id": f"req-{case}", **changes})
        await _assert_rejected(store, case, fields, code)
        assert await store.get(fields["request_id"]) is None, f"{case}: a rejected decision wrote a row"
        # AD-1328 S2b repair r1: the identity (KEY) was denied by req-2 above, so an ``active`` decision there is
        # refused by design; the control is recorded in an identity nothing has denied.
        accepted = await store.record_decision(
            **_decision(request_id=f"req-ok-{case}", canonical_key=OTHER_KEY),
        )  # the same call, no defect
        assert accepted is not None and accepted.request_id == f"req-ok-{case}", case


def _identity_of(**changes: Any) -> tuple[str, str, str, str]:
    fields = _decision(**changes)
    return fields["agent_id"], fields["scope_key"], fields["canonical_key"], fields["policy_digest"]


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param({"agent_id": OTHER_AGENT}, id="agent"),
        pytest.param({"scope_key": OTHER_WORK_SCOPE}, id="scope"),
        pytest.param({"canonical_key": OTHER_KEY}, id="key"),
        pytest.param({"policy_digest": OTHER_DIGEST}, id="digest"),
    ],
)
async def test_find_matches_the_exact_identity(env: _Env, changed: dict[str, Any]) -> None:
    """M1 #3: a row is found for exactly its agent, scope, canonical key and policy digest; changing any one finds
    nothing (never across agents)."""
    store = env.store
    base = await store.record_decision(**_decision())
    identity = _identity_of()
    other_identity = _identity_of(**changed)
    assert base is not None
    assert await store.find(*identity, state="active") == base  # premise: the exact identity finds the row
    assert other_identity != identity and len([a for a, b in zip(identity, other_identity) if a != b]) == 1

    assert await store.find(*other_identity, state="active") is None

    # negative control: a row decided for the changed identity is found by that identity alone
    other = await store.record_decision(**_decision(request_id="req-2", **changed))
    assert other is not None
    assert await store.find(*other_identity, state="active") == other
    assert await store.find(*identity, state="active") == base


@pytest.mark.parametrize("state", ["active", "denied"])
async def test_find_ignores_an_expired_row(env: _Env, state: str) -> None:
    """Beyond M1 #3 (its expiry clause): a row is found until ``expires_at`` and never at or after it."""
    store, clock = env.store, env.clock
    row = await store.record_decision(**_decision(state=state, ttl_seconds=100.0))
    assert row is not None and row.expires_at == T0 + 100.0

    clock.now = row.expires_at - 0.5
    assert await _find(store, row, state=state) == row  # premise: usable until it expires
    clock.now = row.expires_at
    assert await _find(store, row, state=state) is None  # at expires_at it is expired
    clock.now = row.expires_at + 3600.0
    assert await _find(store, row, state=state) is None

    later = await store.record_decision(**_decision(request_id="req-2", state=state, ttl_seconds=100.0))
    assert later is not None and later.expires_at > clock.now
    assert await _find(store, later, state=state) == later  # negative control: the expiry is per row


async def test_find_never_mixes_active_and_denied(env: _Env) -> None:
    """Beyond M1 #3 (its state clause): ``state="active"`` and ``state="denied"`` never see each other's rows."""
    store = env.store
    active = await store.record_decision(**_decision(request_id="req-active"))
    assert active is not None
    assert await _find(store, active, state="active") == active  # premise
    assert await _find(store, active, state="denied") is None  # an approval is not a denial

    env.clock.now += 1.0
    denied = await store.record_decision(**_decision(request_id="req-denied", state="denied"))
    assert denied is not None
    assert await _find(store, denied, state="denied") == denied
    assert await _find(store, denied, state="active") == active  # the denial did not displace the approval

    only_denied = await store.record_decision(**_decision(request_id="req-solo", agent_id=OTHER_AGENT, state="denied"))
    assert only_denied is not None
    assert await _find(store, only_denied, state="denied") == only_denied  # negative control
    assert await _find(store, only_denied, state="active") is None


async def test_find_returns_the_newest_unexpired_row(env: _Env) -> None:
    """Beyond M1 #3: of two rows for one identity, ``find`` answers the newest unexpired one."""
    store, clock = env.store, env.clock
    older = await store.record_decision(**_decision(request_id="req-old", ttl_seconds=1000.0))
    clock.now = T0 + 10.0
    newer = await store.record_decision(**_decision(request_id="req-new", ttl_seconds=100.0))
    assert older is not None and newer is not None and older.decided_at < newer.decided_at

    assert await _find(store, older) == newer  # the newest of the two
    clock.now = T0 + 200.0  # the newer row has expired (T0 + 110), the older has not (T0 + 1000)
    assert await _find(store, older) == older  # negative control: the answer is the newest *unexpired* row


# --------------------------------------------------------------------------------------------------------------
# M1 #4-#8: use
# --------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("scope", [THREAD_SCOPE, ""], ids=["thread", "none"])
async def test_single_use_scopes_admit_one_run(env: _Env, scope: str) -> None:
    """M1 #4: outside a work item an approval admits one run: the first ``use`` is the ``approved_run``, the second
    admits nothing, and the row is no longer found. Kills St1 (the single-use guard dropped from ``use``)."""
    store, clock = env.store, env.clock
    row = await store.record_decision(**_decision(scope_key=scope))
    assert row is not None and row.state == "active" and row.uses == 0 and row.scope_key == scope
    assert await _find(store, row) == row  # premise: an unused approval is found

    first = await _use(store, row)
    assert first is not None
    assert first == CommandApprovalUse(
        use_id=first.use_id, request_id=row.request_id, agent_id=AGENT,
        scope_key=scope, use_kind="approved_run", used_at=clock.now,
    )
    assert len(first.use_id) == 32  # the store's uuid4().hex

    assert await _use(store, row) is None  # the single-use guard: no second run (St1 admits it as a reuse)
    after = await store.get(row.request_id)
    assert after == dataclasses.replace(row, uses=1)  # the refused use left no increment
    assert await store.list_uses(row.request_id) == [first]
    assert await _find(store, row) is None  # a used single-use approval is no longer found

    fresh = await store.record_decision(**_decision(request_id="req-2", scope_key=scope))
    assert fresh is not None
    assert await _find(store, row) == fresh  # negative control: the guard is per approval, not per identity
    second_approval = await _use(store, fresh)
    assert second_approval is not None and second_approval.use_kind == "approved_run"
    assert second_approval.request_id == "req-2"
    assert await _use(store, fresh) is None


@pytest.mark.parametrize("tick", [1.0, 0.0], ids=["ticking_clock", "frozen_clock"])
async def test_work_item_scope_reuses(env: _Env, tick: float) -> None:
    """M1 #5: inside a work item one approval admits every later run: the first is the ``approved_run``, the rest
    are ``reuse``, each naming the original request, and ``list_uses`` returns them oldest first. Kills St2 (every
    run recorded as a ``reuse``)."""
    store, clock = env.store, env.clock
    row = await store.record_decision(**_decision())
    assert row is not None and row.scope_key == WORK_SCOPE and row.uses == 0
    assert await store.list_uses(row.request_id) == []  # premise: no run yet

    admitted: list[CommandApprovalUse] = []
    for _ in range(3):
        use = await _use(store, row)
        assert use is not None
        admitted.append(use)
        clock.now += tick

    assert [use.use_kind for use in admitted] == ["approved_run", "reuse", "reuse"]  # St2 makes the first a reuse
    assert {use.request_id for use in admitted} == {row.request_id}  # each names the original request
    assert {use.agent_id for use in admitted} == {AGENT} and {use.scope_key for use in admitted} == {WORK_SCOPE}
    assert len({use.use_id for use in admitted}) == 3
    assert [use.used_at for use in admitted] == [T0, T0 + tick, T0 + 2 * tick]
    assert await store.list_uses(row.request_id) == admitted  # oldest first (a frozen clock ties; insertion order)
    assert await store.get(row.request_id) == dataclasses.replace(row, uses=3)
    assert await _find(store, row) == dataclasses.replace(row, uses=3)  # a work-item approval stays findable

    # negative control: runs are counted per approval; another approval has its own approved run
    other = await store.record_decision(**_decision(request_id="req-2"))
    assert other is not None and await store.list_uses("req-2") == []
    first_of_other = await _use(store, other)
    assert first_of_other is not None and first_of_other.use_kind == "approved_run"
    assert await store.list_uses(row.request_id) == admitted


@pytest.mark.parametrize(
    ("approver", "authority"),
    [("agent-x", "captain"), ("captain", "first_officer")],
    ids=["approver_not_captain", "authority_not_captain"],
)
async def test_use_requires_the_captain_and_authority(env: _Env, approver: str, authority: str) -> None:
    """M1 #6: a row approved by anyone but the Captain, or under any other authority, admits nothing. The rows are
    written by raw SQL while the store is stopped (``record_decision`` always writes the Captain's authority)."""
    store, clock = env.store, env.clock
    captains = await store.record_decision(**_decision(request_id="req-captain"))
    assert captains is not None and (captains.approver, captains.approver_authority) == ("captain", "captain")

    async with _stopped_raw(env) as raw:
        raw.execute(
            _INSERT_APPROVAL,
            ("req-raw", AGENT, WORK_SCOPE, KEY, DIGEST, "active", approver, authority, clock.now, clock.now + 600.0),
        )

    row = await store.get("req-raw")
    assert row is not None  # premise: a live, unused, unexpired approval of this agent in this scope...
    assert (row.approver, row.approver_authority) == (approver, authority)
    assert (row.state, row.uses, row.agent_id, row.scope_key) == ("active", 0, AGENT, WORK_SCOPE)
    assert row.expires_at > clock.now

    assert await _use(store, row) is None  # ...whose only defect is who approved it
    assert await store.get("req-raw") == row  # no increment
    assert await store.list_uses("req-raw") == []

    run = await _use(store, captains)  # negative control: the same shape, approved by the Captain, runs
    assert run is not None and run.use_kind == "approved_run"


async def test_a_decision_recorded_for_another_approver_admits_nothing(env: _Env) -> None:
    """Beyond M1 #6, through the public API only: ``record_decision`` always writes the Captain's authority but keeps
    the approver it was given, and a row whose approver is not the Captain admits nothing."""
    store = env.store
    other = await store.record_decision(**_decision(request_id="req-other-approver", approver="agent-x"))
    assert other is not None  # premise: stored, active, with the approver that was named and the Captain's authority
    assert (other.state, other.approver, other.approver_authority, other.uses) == ("active", "agent-x", "captain", 0)

    assert await _use(store, other) is None
    assert await store.get("req-other-approver") == other  # no increment
    assert await store.list_uses("req-other-approver") == []

    captains = await store.record_decision(**_decision(request_id="req-captain"))  # negative control
    assert captains is not None and captains.approver == "captain"
    run = await _use(store, captains)
    assert run is not None and run.use_kind == "approved_run"


async def test_second_approved_run_is_impossible(env: _Env) -> None:
    """M1 #7: a second ``approved_run`` use row for one request is refused by the partial unique index, even by raw
    SQL; a ``reuse`` row for the same request and an ``approved_run`` for another request are not."""
    store, clock = env.store, env.clock
    row = await store.record_decision(**_decision())
    assert row is not None
    first = await _use(store, row)
    assert first is not None and first.use_kind == "approved_run"  # premise: the one approved run exists

    async with _stopped_raw(env) as raw:
        with pytest.raises(sqlite3.IntegrityError) as refused:
            raw.execute(_INSERT_USE, ("raw-second-run", row.request_id, AGENT, WORK_SCOPE, "approved_run", clock.now))
        assert "UNIQUE constraint failed" in str(refused.value)  # the index, not another constraint

        raw.execute(_INSERT_USE, ("raw-reuse", row.request_id, AGENT, WORK_SCOPE, "reuse", clock.now + 1.0))
        raw.execute(_INSERT_USE, ("raw-other-run", "req-other", AGENT, WORK_SCOPE, "approved_run", clock.now))
        (approved_runs,) = raw.execute(
            "SELECT count(*) FROM command_approval_uses WHERE request_id = ? AND use_kind = 'approved_run'",
            (row.request_id,),
        ).fetchone()
        assert approved_runs == 1  # the refused row left nothing behind

    assert [use.use_kind for use in await store.list_uses(row.request_id)] == ["approved_run", "reuse"]
    assert [use.use_kind for use in await store.list_uses("req-other")] == ["approved_run"]


@pytest.mark.parametrize("scope", [THREAD_SCOPE, WORK_SCOPE], ids=["thread", "work_item"])
async def test_failed_use_rolls_back(tmp_path: Path, scope: str) -> None:
    """M1 #8: when the use record cannot be written, ``use`` raises and the counter it had incremented is rolled
    back (the next ``use`` is the ``approved_run``). Kills St3 (no rollback after a failed use record): the
    increment stays on the open connection and ``get`` reads it."""
    async with _running(tmp_path, wrap=_FailTheUseInsert) as env:
        store = env.store
        wrapper = env.factory.wrapped[-1]
        assert wrapper.armed
        row = await store.record_decision(**_decision(scope_key=scope))
        assert row is not None and row.uses == 0

        with pytest.raises(_Boom):
            await _use(store, row)

        statements = wrapper.statements  # premise: the failure came after the compare-and-set had run
        assert len(wrapper.refused) == 1
        update_at = next(i for i, sql in enumerate(statements) if sql.startswith("UPDATE command_approvals SET uses"))
        insert_at = next(i for i, sql in enumerate(statements) if "INSERT INTO command_approval_uses" in sql)
        assert update_at < insert_at

        after = await store.get(row.request_id)
        assert after is not None and after.uses == 0  # the increment was undone (St3 leaves uses == 1)
        assert after == row
        assert await store.list_uses(row.request_id) == []
        assert await _find(store, row) == row

        wrapper.armed = False  # negative control: with a normal connection the next use is the approved run
        run = await _use(store, row)
        assert run is not None and run.use_kind == "approved_run"
        assert (await store.get(row.request_id)) == dataclasses.replace(row, uses=1)
        assert await store.list_uses(row.request_id) == [run]


@pytest.mark.parametrize(
    "case", ["unknown_request", "other_agent", "other_scope", "denied_row", "expired", "at_expiry"],
)
async def test_use_admits_nothing_outside_the_approval(env: _Env, case: str) -> None:
    """Beyond M1 #4-#8: ``use`` admits a run only for the approval's own request, agent and scope, only while the
    row is ``active`` and before ``expires_at``; a refusal writes nothing."""
    store, clock = env.store, env.clock
    approved = await store.record_decision(**_decision(ttl_seconds=100.0))
    # AD-1328 S2b repair r1: a live denial of the approval's own identity now makes ``use`` refuse it, so the
    # ``denied`` fixture row lives in another identity (OTHER_KEY); the ``denied_row`` case still returns None
    # because the row it names is itself ``denied``.
    denied = await store.record_decision(
        **_decision(request_id="req-denied", state="denied", ttl_seconds=100.0, canonical_key=OTHER_KEY),
    )
    assert approved is not None and denied is not None
    assert (approved.state, denied.state) == ("active", "denied")  # premise

    request_id, agent_id, scope_key = approved.request_id, AGENT, WORK_SCOPE
    if case == "unknown_request":
        request_id = "req-unknown"
        assert await store.get(request_id) is None
    elif case == "other_agent":
        agent_id = OTHER_AGENT
    elif case == "other_scope":
        scope_key = OTHER_WORK_SCOPE
    elif case == "denied_row":
        request_id = denied.request_id
    elif case == "expired":
        clock.now = approved.expires_at + 1.0
    else:  # at_expiry: the instant of expiry is already expired
        clock.now = approved.expires_at

    assert await store.use(request_id, agent_id=agent_id, scope_key=scope_key) is None
    assert await store.get(approved.request_id) == approved  # nothing was written
    assert await store.get(denied.request_id) == denied
    assert await store.list_uses(approved.request_id) == []
    assert await store.list_uses(denied.request_id) == []

    clock.now = approved.decided_at + 1.0  # negative control: the exact identity, inside its window, is admitted
    run = await _use(store, approved)
    assert run is not None and run.use_kind == "approved_run"


@pytest.mark.parametrize("scope", [WORK_SCOPE, THREAD_SCOPE], ids=["work_item", "thread"])
async def test_live_denial_blocks_use_across_requests(env: _Env, scope: str) -> None:
    """AD-1328 S2b repair r1 (approve-then-deny): a live ``denied`` row of the same identity under ANOTHER request
    id makes ``use`` admit no run and write nothing; ``find`` is untouched. Once the denial has expired the same
    approval is admitted. Kills St4 (the denial clause can never match) and St9 (the denial never expires)."""
    store, clock = env.store, env.clock
    approved = await store.record_decision(**_decision(request_id="req-a", scope_key=scope, ttl_seconds=600.0))
    denied = await store.record_decision(
        **_decision(request_id="req-d", scope_key=scope, state="denied", ttl_seconds=100.0),
    )
    assert approved is not None and denied is not None
    assert (approved.state, denied.state) == ("active", "denied")  # premise: both rows exist
    assert approved.request_id != denied.request_id
    assert (approved.agent_id, approved.scope_key, approved.canonical_key, approved.policy_digest) == (
        denied.agent_id, denied.scope_key, denied.canonical_key, denied.policy_digest,
    )  # premise: one identity
    assert await _find(store, approved) == approved  # premise: find(active) still sees the approval
    assert await _find(store, approved, state="denied") == denied
    assert approved.uses == 0

    assert await _use(store, approved) is None  # the denial stands, so the approval admits no run
    assert await store.get("req-a") == approved  # nothing was written
    assert await store.get("req-d") == denied
    assert await store.list_uses("req-a") == []
    assert await _find(store, approved) == approved  # find is unchanged by the refusal

    clock.now = denied.expires_at  # control (expiry): the denial ends at its expiry; the approval is still live
    assert clock.now < approved.expires_at
    assert await _find(store, approved, state="denied") is None
    run = await _use(store, approved)
    assert run is not None and run.use_kind == "approved_run" and run.request_id == "req-a"
    assert await store.list_uses("req-a") == [run]


@pytest.mark.parametrize(
    "changes",
    [
        {"agent_id": OTHER_AGENT},
        {"scope_key": OTHER_WORK_SCOPE},
        {"canonical_key": OTHER_KEY},
        {"policy_digest": OTHER_DIGEST},
    ],
    ids=["agent", "scope", "key", "digest"],
)
async def test_denial_of_another_identity_does_not_block(env: _Env, changes: dict[str, Any]) -> None:
    """AD-1328 S2b repair r1: a live denial differing in exactly one of agent, scope, canonical key or policy digest
    is another identity and does not block ``use``. The control: a denial of the approval's own identity does.
    Kills St5 (agent not compared), St6 (scope), St7 (canonical key) and St8 (digest)."""
    store = env.store
    approved = await store.record_decision(**_decision(request_id="req-a", ttl_seconds=600.0))
    denied = await store.record_decision(
        **_decision(request_id="req-d", state="denied", ttl_seconds=100.0, **changes),
    )
    assert approved is not None and denied is not None
    assert (approved.state, denied.state) == ("active", "denied")
    identity = (denied.agent_id, denied.scope_key, denied.canonical_key, denied.policy_digest)
    assert await store.find(*identity, state="denied") == denied  # premise: the denial is live and findable
    assert identity != (approved.agent_id, approved.scope_key, approved.canonical_key, approved.policy_digest)
    assert sum(
        left != right
        for left, right in zip(identity, (approved.agent_id, approved.scope_key, approved.canonical_key,
                                          approved.policy_digest))
    ) == 1  # premise: it differs in exactly one field
    assert await _find(store, approved, state="denied") is None  # premise: nothing denies the approval's identity

    run = await _use(store, approved)
    assert run is not None and run.use_kind == "approved_run" and run.request_id == "req-a"
    assert await store.list_uses("req-a") == [run]

    own_denial = await store.record_decision(**_decision(request_id="req-d-own", state="denied", ttl_seconds=100.0))
    assert own_denial is not None and own_denial.state == "denied"  # control: the same identity does block
    assert await _use(store, approved) is None
    assert await store.list_uses("req-a") == [run]


async def test_denial_between_find_and_use_and_after_a_run(env: _Env) -> None:
    """AD-1328 S2b repair r1 (the race, enacted deterministically in a work item): an approval found and used once is
    stopped by a denial that lands afterwards; the run already admitted stands, and a second approval of another
    command is unaffected. Kills St4 (the denial clause can never match)."""
    store = env.store
    approved = await store.record_decision(**_decision(request_id="req-a", ttl_seconds=600.0))
    assert approved is not None and approved.scope_key == WORK_SCOPE
    found = await _find(store, approved)
    assert found == approved  # premise: find hands back the approval
    first = await _use(store, found)
    assert first is not None and first.use_kind == "approved_run"  # premise: the first run is admitted

    denied = await store.record_decision(**_decision(request_id="req-d", state="denied", ttl_seconds=100.0))
    assert denied is not None and denied.state == "denied"  # the denial lands after find and after a run
    assert await _find(store, approved) is not None  # find still shows the approval: `use` is the authority

    assert await _use(store, found) is None  # a reuse is refused
    after = await store.get("req-a")
    assert after is not None and after.uses == 1  # the counter did not move
    assert await store.list_uses("req-a") == [first]  # the admitted run stands; nothing was added

    other = await store.record_decision(**_decision(request_id="req-b", canonical_key=OTHER_KEY))
    assert other is not None
    control = await _use(store, other)  # control: another command's approval is admitted after the denial
    assert control is not None and control.use_kind == "approved_run" and control.request_id == "req-b"
    assert await store.list_uses("req-a") == [first]


async def test_activation_refused_while_a_denial_stands(env: _Env) -> None:
    """AD-1328 S2b repair r1 (deny-then-approve): ``record_decision(state="active")`` records nothing (returns None)
    while a live denial of the same identity stands, a further denial is still recorded, another identity is
    unaffected, and once the denials have expired the retry records and is admitted (the BF-722 retry). Kills St10
    (the activation is never refused), St11 (a denial is gated too) and St12 (the denial never expires)."""
    store, clock = env.store, env.clock
    denied = await store.record_decision(**_decision(request_id="req-d", state="denied", ttl_seconds=100.0))
    assert denied is not None and denied.state == "denied"  # premise: a live denial
    identity = (denied.agent_id, denied.scope_key, denied.canonical_key, denied.policy_digest)
    assert await store.find(*identity, state="denied") == denied

    refused = await store.record_decision(**_decision(request_id="req-a", state="active", ttl_seconds=600.0))
    assert refused is None  # activation refused
    assert await store.get("req-a") is None  # no row
    assert await store.find(*identity, state="active") is None

    clock.now = T0 + 10.0
    second = await store.record_decision(**_decision(request_id="req-d2", state="denied", ttl_seconds=100.0))
    assert second is not None and second.state == "denied"  # a denial is never gated
    assert await store.get("req-d2") == second
    assert await store.record_decision(**_decision(request_id="req-a", state="active")) is None  # still refused

    control = await store.record_decision(**_decision(request_id="req-k", canonical_key=OTHER_KEY))
    assert control is not None and control.state == "active"  # control: another identity records

    clock.now = second.expires_at  # both denials have ended
    assert await store.find(*identity, state="denied") is None
    retried = await store.record_decision(**_decision(request_id="req-a", state="active", ttl_seconds=600.0))
    assert retried is not None and retried.state == "active" and retried.request_id == "req-a"
    assert await store.get("req-a") == retried
    run = await _use(store, retried)
    assert run is not None and run.use_kind == "approved_run" and run.request_id == "req-a"


@pytest.mark.parametrize(
    ("scope", "expected_kinds"),
    [
        (THREAD_SCOPE, ["approved_run"]),
        (WORK_SCOPE, ["approved_run", "reuse", "reuse", "reuse", "reuse"]),
    ],
    ids=["thread", "work_item"],
)
async def test_concurrent_uses_admit_exactly_one_approved_run(
    env: _Env, scope: str, expected_kinds: list[str],
) -> None:
    """Beyond M1 #4-#5: five concurrent ``use`` calls on one approval admit exactly one ``approved_run``; outside
    a work item the other four admit nothing, inside one they are ``reuse``."""
    store = env.store
    row = await store.record_decision(**_decision(scope_key=scope))
    assert row is not None and row.uses == 0

    results = await asyncio.gather(*(_use(store, row) for _ in range(5)))
    admitted = [use for use in results if use is not None]
    assert sorted(use.use_kind for use in admitted) == sorted(expected_kinds)
    assert sum(use.use_kind == "approved_run" for use in admitted) == 1
    assert {use.use_id for use in await store.list_uses(row.request_id)} == {use.use_id for use in admitted}
    after = await store.get(row.request_id)
    assert after is not None and after.uses == len(expected_kinds)  # negative control: the counter agrees


async def test_schema_refuses_a_malformed_row(env: _Env) -> None:
    """Beyond M1 #7: the schema itself refuses a row without an expiry, with an unknown state, a short canonical
    key, an empty agent or digest, or a use row of an unknown kind."""
    good = ("req-raw-0", AGENT, WORK_SCOPE, KEY, DIGEST, "active", "captain", "captain", T0, T0 + 600.0)
    cases = (
        ("no_expiry", 9, None, "NOT NULL constraint failed"),
        ("unknown_state", 5, "x", "CHECK constraint failed"),
        ("short_key", 3, KEY[:63], "CHECK constraint failed"),
        ("empty_agent", 1, "", "CHECK constraint failed"),
        ("empty_digest", 4, "", "CHECK constraint failed"),
    )
    async with _stopped_raw(env) as raw:
        raw.execute(_INSERT_APPROVAL, good)  # the control: the well-formed row goes in
        for number, (_label, column, value, message) in enumerate(cases, start=1):
            row = list(good)
            row[0] = f"req-raw-{number}"  # a fresh primary key, so only the named constraint can refuse it
            row[column] = value
            with pytest.raises(sqlite3.IntegrityError, match=message):
                raw.execute(_INSERT_APPROVAL, tuple(row))
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            raw.execute(_INSERT_USE, ("raw-use-bad", "req-raw-0", AGENT, WORK_SCOPE, "replay", T0))
        raw.execute(_INSERT_USE, ("raw-use-good", "req-raw-0", AGENT, WORK_SCOPE, "reuse", T0))

    assert await env.store.get("req-raw-0") is not None
    assert [await env.store.get(f"req-raw-{number}") for number in range(1, len(cases) + 1)] == [None] * len(cases)
    assert [use.use_id for use in await env.store.list_uses("req-raw-0")] == ["raw-use-good"]


# --------------------------------------------------------------------------------------------------------------
# M1 #9: fail closed
# --------------------------------------------------------------------------------------------------------------


def _store_calls() -> dict[str, Callable[[SqliteCommandApprovalStore], Any]]:
    """One call per public method, each against the approval ``_seed_one_run`` leaves."""
    return {
        "record_decision": lambda target: target.record_decision(**_decision(request_id="req-late")),
        "find": lambda target: target.find(AGENT, WORK_SCOPE, KEY, DIGEST, state="active"),
        "use": lambda target: target.use("req-1", agent_id=AGENT, scope_key=WORK_SCOPE),
        "get": lambda target: target.get("req-1"),
        "list_uses": lambda target: target.list_uses("req-1"),
    }


async def _seed_one_run(env: _Env) -> tuple[CommandApproval, CommandApprovalUse]:
    """The premise of every fail-closed case: the running store, with a good clock, works."""
    row = await env.store.record_decision(**_decision())
    assert row is not None
    run = await _use(env.store, row)
    assert run is not None and run.use_kind == "approved_run"
    assert await env.store.get("req-1") == dataclasses.replace(row, uses=1)
    assert await _find(env.store, row) is not None
    assert await env.store.list_uses("req-1") == [run]
    return row, run


async def _check_fails_closed_when_not_running(env: _Env, mode: str) -> None:
    target = env.store if mode == "after_stop" else env.new_store()
    if mode == "after_stop":
        await env.store.stop()
        await env.store.stop()  # a second stop is harmless
    for name, call in _store_calls().items():
        try:
            await call(target)
        except RuntimeError as exc:
            assert "not running" in str(exc), f"{name}: failed for the wrong reason: {exc}"
        else:
            pytest.fail(f"{name} did not fail closed on a store that is not running")
    await target.start()  # negative control: started, every method works again
    for call in _store_calls().values():
        await call(target)
    assert await target.get("req-late") is not None


async def _check_fails_closed_on_a_bad_clock(
    env: _Env, mode: str, row: CommandApproval, run: CommandApprovalUse,
) -> None:
    bad = {
        "nan_clock": float("nan"), "infinite_clock": float("inf"), "negative_infinite_clock": float("-inf"),
        "none_clock": None, "string_clock": "1000000", "bool_clock": True,
    }[mode]
    store, calls = env.store, _store_calls()
    env.clock.now = bad
    for name in ("record_decision", "find", "use"):  # the methods that read the clock
        try:
            await calls[name](store)
        except RuntimeError as exc:
            assert "clock" in str(exc), f"{name}: failed for the wrong reason: {exc}"
        else:
            pytest.fail(f"{name} accepted a clock that is not a finite real: {bad!r}")
    env.clock.now = T0 + 10.0  # negative control: the clock is the only difference
    assert await store.get("req-late") is None  # the refused record_decision wrote nothing
    assert await store.get("req-1") == dataclasses.replace(row, uses=1)  # the refused use wrote nothing
    assert await store.list_uses("req-1") == [run]
    late = await calls["record_decision"](store)
    assert late is not None and late.request_id == "req-late"
    assert await calls["find"](store) is not None
    reuse = await calls["use"](store)
    assert reuse is not None and reuse.use_kind == "reuse"


@pytest.mark.parametrize(
    "mode",
    ["after_stop", "before_start", "nan_clock", "infinite_clock", "negative_infinite_clock", "none_clock",
     "string_clock", "bool_clock"],
)
async def test_fails_closed_when_stopped_or_clock_bad(tmp_path: Path, mode: str) -> None:
    """M1 #9: after ``stop`` (or before ``start``) every method raises ``RuntimeError``; with a clock that is not a
    finite real, the methods that read the clock raise and write nothing."""
    async with _running(tmp_path) as env:
        row, run = await _seed_one_run(env)
        if mode in ("after_stop", "before_start"):
            await _check_fails_closed_when_not_running(env, mode)
        else:
            await _check_fails_closed_on_a_bad_clock(env, mode, row, run)


# --------------------------------------------------------------------------------------------------------------
# M1 #10-#11: the request parser and the scope helpers
# --------------------------------------------------------------------------------------------------------------

ASK_REQUEST_ID = "7b1d6a52-2f4e-4d0e-9c1a-3b5f2a9d8e01"
ASK_KEY = "1f" * 32
ASK_DIGEST = "policy-digest-0001"


def _ask_params(**changes: Any) -> dict[str, Any]:
    params: dict[str, Any] = {"command": "git push origin main", "canonical_key": ASK_KEY, "policy_digest": ASK_DIGEST}
    params.update(changes)
    return params


def _action_payload(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool_id": "run_command",
        "action": "execute",
        "params": _ask_params(),
        "scope_key": WORK_SCOPE,
        "session_id": None,
        "thread_id": "th-1",
    }
    payload.update(changes)
    return payload


def _ask_request(**changes: Any) -> CapabilityRequest:
    fields: dict[str, Any] = {
        "id": ASK_REQUEST_ID,
        "agent_id": AGENT,
        "kind": "action",
        "target": "run_command",
        "rationale": "AD-1328 command policy escalation (rule-a)",
        "work_item_id": WORK_ITEM_ID,
        "status": "pending",
        "created_at": T0,
        "payload": _action_payload(),
    }
    fields.update(changes)
    return CapabilityRequest(**fields)


def _without_thread_id() -> CapabilityRequest:
    payload = _action_payload()
    del payload["thread_id"]
    return _ask_request(payload=payload)


_ASK_CASES: dict[str, Callable[[], CapabilityRequest]] = {
    "valid": lambda: _ask_request(),
    "wrong_kind": lambda: _ask_request(kind="grant"),
    "wrong_tool": lambda: _ask_request(payload=_action_payload(tool_id="other_tool")),
    "wrong_action": lambda: _ask_request(payload=_action_payload(action="dispatch")),
    "bad_key": lambda: _ask_request(payload=_action_payload(params=_ask_params(canonical_key=ASK_KEY[:-1]))),
    "long_digest": lambda: _ask_request(payload=_action_payload(params=_ask_params(policy_digest="d" * 129))),
    "bad_scope": lambda: _ask_request(payload=_action_payload(scope_key="other:x")),
    "scope_names_other_item": lambda: _ask_request(payload=_action_payload(scope_key=OTHER_WORK_SCOPE)),
    "missing_id": lambda: _ask_request(id=""),
    "missing_agent": lambda: _ask_request(agent_id=""),
    "invalid_payload": _without_thread_id,
}


@pytest.mark.parametrize("case", list(_ASK_CASES))
def test_command_approval_request(case: str) -> None:
    """M1 #10: only a well-formed ``action`` / ``run_command`` / ``execute`` request is an ask, and its fields are
    the payload's; every other case differs from the valid request in one thing and is refused."""
    valid = _ask_request()
    expected = CommandApprovalAsk(
        request_id=ASK_REQUEST_ID, agent_id=AGENT, scope_key=WORK_SCOPE, work_item_id=WORK_ITEM_ID,
        canonical_key=ASK_KEY, policy_digest=ASK_DIGEST,
    )
    assert command_approval_request(valid) == expected  # the negative control of every case: the baseline is an ask

    request = _ASK_CASES[case]()
    ask = command_approval_request(request)
    if case == "valid":
        assert request == valid
        assert ask == expected
        assert ask is not None and request.payload is not None
        assert ask.request_id == request.id and ask.agent_id == request.agent_id
        assert ask.scope_key == request.payload["scope_key"]
        assert ask.canonical_key == request.payload["params"]["canonical_key"]
        assert ask.policy_digest == request.payload["params"]["policy_digest"]
        assert ask.work_item_id == WORK_ITEM_ID == request.work_item_id
    else:
        assert request != valid  # premise: the case is a different request...
        # ...and where the AD-1154 payload is still valid, the refusal is this parser's own rule
        assert (validate_action_payload(request.payload) is None) == (case == "invalid_payload")
        assert ask is None


@pytest.mark.parametrize("scope", [THREAD_SCOPE, ""], ids=["thread", "none"])
def test_command_approval_request_accepts_a_thread_or_no_scope(scope: str) -> None:
    """Beyond M1 #10: a ``thread:<id>`` or empty scope is an ask with no work item; a work-item scope needs its
    item on the request."""
    ask = command_approval_request(_ask_request(work_item_id=None, payload=_action_payload(scope_key=scope)))
    assert ask == CommandApprovalAsk(
        request_id=ASK_REQUEST_ID, agent_id=AGENT, scope_key=scope, work_item_id=None,
        canonical_key=ASK_KEY, policy_digest=ASK_DIGEST,
    )
    assert command_approval_request(_ask_request(work_item_id=None)) is None  # negative control: work-item scope


@pytest.mark.parametrize("field", ["request_id", "agent_id", "policy_digest"])
def test_command_approval_request_text_bounds(field: str) -> None:
    """Beyond M1 #10: the request id, agent id and policy digest are non-empty and at most 128 characters."""
    builders: dict[str, Callable[[str], CapabilityRequest]] = {
        "request_id": lambda text: _ask_request(id=text),
        "agent_id": lambda text: _ask_request(agent_id=text),
        "policy_digest": lambda text: _ask_request(payload=_action_payload(params=_ask_params(policy_digest=text))),
    }
    build = builders[field]
    longest = "x" * 128
    ask = command_approval_request(build(longest))
    assert ask is not None and getattr(ask, field) == longest  # premise: 128 is accepted
    assert command_approval_request(build(longest + "x")) is None
    assert command_approval_request(build("")) is None


def test_command_approval_request_refuses_what_is_not_a_request() -> None:
    """Beyond M1 #10: a missing request, a bare object, a missing payload and a non-string id are not asks."""
    assert command_approval_request(_ask_request()) is not None  # negative control
    assert command_approval_request(None) is None
    assert command_approval_request(object()) is None
    assert command_approval_request(_ask_request(payload=None)) is None
    assert command_approval_request(_ask_request(id=None)) is None


class _TextSubclass(str):
    """A ``str`` that is not exactly a ``str``: the helpers accept only the real type."""


def test_scope_helpers() -> None:
    """M1 #11: ``scope_work_item_id``, ``valid_scope_key`` (a 64-character thread id is ok, 65 is not) and
    ``approval_ttl_seconds`` (a work item is reusable for 7 days, anything else is single-use for an hour), and the
    ended-work-item set is exactly the workforce's terminal set (a drift guard)."""
    assert scope_work_item_id(WORK_SCOPE) == WORK_ITEM_ID
    assert scope_work_item_id("work_item:" + "a" * 128) == "a" * 128  # premise: the id bound is 128
    for not_a_work_item in (
        "", THREAD_SCOPE, "work_item:", "work_item:" + "a" * 129, "work_item:-x", "work_item:a b", "Work_item:wi-1",
        None, 5, b"work_item:wi-1", _TextSubclass(WORK_SCOPE),
    ):
        assert scope_work_item_id(not_a_work_item) is None, repr(not_a_work_item)

    assert THREAD_ID_MAX_CHARS == 64  # drift guard for the bound the next lines pin
    assert valid_scope_key("")
    assert valid_scope_key(WORK_SCOPE)
    assert valid_scope_key("thread:" + "t" * 64)
    assert not valid_scope_key("thread:" + "t" * 65)  # the boundary: 65 is one too many
    for not_a_scope in ("thread:", "work_item:", "other:x", "work_item:a b", " ", None, 5, _TextSubclass(WORK_SCOPE)):
        assert not valid_scope_key(not_a_scope), repr(not_a_scope)

    assert approval_ttl_seconds(WORK_SCOPE) == REUSABLE_APPROVAL_TTL_SECONDS == 7 * 86400.0
    assert approval_ttl_seconds(THREAD_SCOPE) == SINGLE_USE_APPROVAL_TTL_SECONDS == 3600.0
    assert approval_ttl_seconds("") == SINGLE_USE_APPROVAL_TTL_SECONDS
    assert approval_ttl_seconds("work_item:") == SINGLE_USE_APPROVAL_TTL_SECONDS  # a malformed item earns no 7 days
    assert all(type(approval_ttl_seconds(scope)) is float for scope in (WORK_SCOPE, THREAD_SCOPE, ""))

    assert ENDED_WORK_ITEM_STATUSES == workforce._TERMINAL_STATUSES  # drift guard
    assert ENDED_WORK_ITEM_STATUSES == frozenset({"done", "cancelled", "failed"})
    live = {status.value for status in workforce.WorkItemStatus} - workforce._TERMINAL_STATUSES
    assert live and not live & ENDED_WORK_ITEM_STATUSES  # negative control: no live status ends a scope
