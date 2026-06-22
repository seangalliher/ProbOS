"""AD-904: tests for the confidential clinical notes store + gated endpoints (#867).

Two layers, both BF-287 (no MagicMock at the store/auth boundary):

* Store-level persistence (real ``ClinicalNotesStore`` on ``tmp_path``, single
  event loop via ``@pytest.mark.asyncio``): write→list→get round-trip,
  ``DisclosureLevel.CONFIDENTIAL`` (=3) stamping, idempotent schema (double
  ``start()``).
* REST gating (real ``TestClient`` over the real counselor router, real
  ``ClinicalNotesStore(db_path="")`` + real ``ClearanceGrantStore(db_path="")`` +
  real ``deque`` audit ring): subject-never-reads-own (incl. a counselor reading
  their OWN record), non-counselor deny, counselor/grantee/Captain allow, an
  audit row on every read AND write (allow+deny), 503 when the store is absent,
  and fail-closed (store error AND audit-append error) with no body leak.

Fault injection uses thin REAL ``ClinicalNotesStore`` subclasses (not
MagicMock), so the store/auth boundary stays real.

asyncio_mode="auto".

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad904_clinical_notes.py -q -n 0
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.clearance_grants import ClearanceGrantStore
from probos.cognitive.clinical_notes_store import ClinicalNote, ClinicalNotesStore
from probos.config import SystemConfig
from probos.earned_agency import RecallTier
from probos.mesh.disclosure import DisclosureLevel


# --------------------------------------------------------------------------- #
# Real-attribute runtime stub (mirrors tests/test_ad903_clinical_trends.py)
# --------------------------------------------------------------------------- #


class _Agent:
    def __init__(self, agent_id: str, agent_type: str) -> None:
        self.id = agent_id
        self.agent_type = agent_type


class _Registry:
    def __init__(self, agent_types: dict[str, str]) -> None:
        self._agent_types = agent_types

    def get(self, agent_id: str) -> _Agent | None:
        agent_type = self._agent_types.get(agent_id)
        if agent_type is None:
            return None
        return _Agent(agent_id, agent_type)

    def get_by_pool(self, pool: str) -> list[Any]:
        return []


class _Runtime:
    """Real-attribute stub exposing exactly what the notes endpoints read."""

    def __init__(
        self,
        *,
        agent_types: dict[str, str] | None = None,
        grant_store: Any = None,
        notes_store: Any = None,
        audit: Any = None,
    ) -> None:
        self.config = SystemConfig()
        self.registry = _Registry(agent_types or {})
        self.pools: dict[str, Any] = {}
        self.clearance_grant_store = grant_store
        self.clinical_notes_store = notes_store
        self.clinical_access_audit: Any = (
            audit if audit is not None else deque(maxlen=1000)
        )


_AGENT_TYPES = {
    "crewman": "science",
    "counselor-1": "counselor",
    "chief": "engineering",
    "officer": "operations",
}


def _client(runtime: _Runtime) -> TestClient:
    from probos.routers.counselor import router

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    return TestClient(app)


def _seed_grant(store: ClearanceGrantStore, grantee: str, scope: str) -> None:
    asyncio.run(store.issue_grant(grantee, RecallTier.BASIC, scope=scope))


# --------------------------------------------------------------------------- #
# Fault-injection stores (REAL subclasses — not MagicMock)
# --------------------------------------------------------------------------- #


class _BoomStore(ClinicalNotesStore):
    """A real store whose every operation raises — exercises fail-closed 503."""

    async def write_note(self, **kwargs: Any) -> ClinicalNote:
        raise RuntimeError("boom write")

    async def list_notes(self, target_agent_id: str, *, limit: int = 50) -> Any:
        raise RuntimeError("boom list")

    async def get_note(self, note_id: str) -> Any:
        raise RuntimeError("boom get")


class _SentinelStore(ClinicalNotesStore):
    """A real store that WOULD return a secret body if its reads were reached.

    Used to prove that an audit-append failure denies BEFORE any body is served
    (the gate fails closed and the store is never touched).
    """

    SECRET = "SENTINEL_SECRET_BODY"

    async def list_notes(self, target_agent_id: str, *, limit: int = 50) -> Any:
        return [
            ClinicalNote(
                id="n1",
                target_agent_id=target_agent_id,
                author_agent_id="counselor-1",
                body=self.SECRET,
                disclosure_level=3,
                created_at=0.0,
            )
        ]

    async def get_note(self, note_id: str) -> Any:
        return ClinicalNote(
            id=note_id,
            target_agent_id="crewman",
            author_agent_id="counselor-1",
            body=self.SECRET,
            disclosure_level=3,
            created_at=0.0,
        )


class _MismatchStore(ClinicalNotesStore):
    """A real store returning a note whose target differs from the path agent."""

    async def get_note(self, note_id: str) -> Any:
        return ClinicalNote(
            id=note_id,
            target_agent_id="other-crewman",
            author_agent_id="counselor-1",
            body="not-yours",
            disclosure_level=3,
            created_at=0.0,
        )


class _BoomDeque:
    """A real audit ring whose append raises — exercises fail-closed audit."""

    def append(self, _entry: Any) -> None:
        raise RuntimeError("boom append")


# --------------------------------------------------------------------------- #
# Store-level persistence (real ClinicalNotesStore on tmp_path)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_write_list_get_round_trip(tmp_path) -> None:
    store = ClinicalNotesStore(db_path=str(tmp_path / "notes.db"))
    await store.start()
    try:
        n1 = await store.write_note(
            target_agent_id="crewman", author_agent_id="counselor-1", body="first"
        )
        n2 = await store.write_note(
            target_agent_id="crewman", author_agent_id="counselor-1", body="second"
        )
        # list_notes is newest-first.
        notes = await store.list_notes("crewman")
        assert [n.body for n in notes] == ["second", "first"]
        assert {n.id for n in notes} == {n1.id, n2.id}
        # get_note round-trips one record with every field intact.
        got = await store.get_note(n1.id)
        assert got is not None
        assert got.id == n1.id
        assert got.target_agent_id == "crewman"
        assert got.author_agent_id == "counselor-1"
        assert got.body == "first"
        # A note for a different target is isolated.
        assert await store.list_notes("other") == []
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_disclosure_level_defaults_to_confidential(tmp_path) -> None:
    store = ClinicalNotesStore(db_path=str(tmp_path / "notes.db"))
    await store.start()
    try:
        note = await store.write_note(
            target_agent_id="crewman", author_agent_id="counselor-1", body="x"
        )
        assert note.disclosure_level == 3
        assert note.disclosure_level == int(DisclosureLevel.CONFIDENTIAL)
        reloaded = await store.get_note(note.id)
        assert reloaded is not None and reloaded.disclosure_level == 3
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_idempotent_schema_double_start(tmp_path) -> None:
    db = str(tmp_path / "notes.db")
    store = ClinicalNotesStore(db_path=db)
    await store.start()
    note = await store.write_note(
        target_agent_id="crewman", author_agent_id="counselor-1", body="persist"
    )
    # A second start() over the same DB re-applies CREATE TABLE IF NOT EXISTS
    # without error and the prior row survives.
    await store.start()
    try:
        notes = await store.list_notes("crewman")
        assert any(n.id == note.id for n in notes)
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_persists_across_fresh_store(tmp_path) -> None:
    db = str(tmp_path / "notes.db")
    store = ClinicalNotesStore(db_path=db)
    await store.start()
    note = await store.write_note(
        target_agent_id="crewman", author_agent_id="counselor-1", body="durable"
    )
    await store.stop()

    store2 = ClinicalNotesStore(db_path=db)
    await store2.start()
    try:
        got = await store2.get_note(note.id)
        assert got is not None and got.body == "durable"
    finally:
        await store2.stop()


@pytest.mark.asyncio
async def test_empty_store_honest_degrades(tmp_path) -> None:
    # db_path="" → no connection; reads honest-degrade to []/None.
    store = ClinicalNotesStore(db_path="")
    await store.start()
    assert await store.list_notes("crewman") == []
    assert await store.get_note("nope") is None
    # write_note still returns a stamped record (no persistence).
    note = await store.write_note(
        target_agent_id="crewman", author_agent_id="captain", body="x"
    )
    assert note.disclosure_level == 3
    await store.stop()


# --------------------------------------------------------------------------- #
# REST gating — allow / deny ladder
# --------------------------------------------------------------------------- #


def _runtime(**kw: Any) -> _Runtime:
    kw.setdefault("agent_types", _AGENT_TYPES)
    kw.setdefault("notes_store", ClinicalNotesStore(db_path=""))
    return _Runtime(**kw)


def test_captain_write_then_list_allows() -> None:
    client = _client(_runtime())
    w = client.post("/api/counselor/notes/crewman", json={"body": "hello"})
    assert w.status_code == 200
    assert "id" in w.json()
    r = client.get("/api/counselor/notes/crewman")
    assert r.status_code == 200
    assert "notes" in r.json()


def test_counselor_as_agent_allows() -> None:
    client = _client(_runtime())
    r = client.get("/api/counselor/notes/crewman?as_agent_id=counselor-1")
    assert r.status_code == 200
    w = client.post(
        "/api/counselor/notes/crewman?as_agent_id=counselor-1", json={"body": "n"}
    )
    assert w.status_code == 200


def test_subject_cannot_read_own_notes() -> None:
    # A plain crewman asserting their own id is the subject → denied.
    client = _client(_runtime())
    r = client.get("/api/counselor/notes/crewman?as_agent_id=crewman")
    assert r.status_code == 403
    assert r.json()["detail"] == "clinical_access_denied"


def test_counselor_cannot_read_own_notes_even_with_role() -> None:
    # The subject-denied rung outranks the counselor-role rung: a counselor
    # reading THEIR OWN record is denied, even though the same counselor may
    # read another crewman's record.
    client = _client(_runtime())
    own = client.get("/api/counselor/notes/counselor-1?as_agent_id=counselor-1")
    assert own.status_code == 403
    other = client.get("/api/counselor/notes/crewman?as_agent_id=counselor-1")
    assert other.status_code == 200


def test_non_counselor_denied() -> None:
    client = _client(_runtime())
    r = client.get("/api/counselor/notes/crewman?as_agent_id=officer")
    assert r.status_code == 403
    w = client.post(
        "/api/counselor/notes/crewman?as_agent_id=officer", json={"body": "n"}
    )
    assert w.status_code == 403


def test_grantee_chief_allows_per_target_only() -> None:
    store = ClearanceGrantStore(db_path="")
    _seed_grant(store, "chief", "clinical:crewman")
    client = _client(_runtime(grant_store=store))
    ok = client.get("/api/counselor/notes/crewman?as_agent_id=chief")
    assert ok.status_code == 200
    # The same chief is NOT unlocked for a different crewman (per-target grant).
    other = client.get("/api/counselor/notes/crewman-2?as_agent_id=chief")
    assert other.status_code == 403


def test_get_single_note_target_mismatch_404() -> None:
    # A note that exists but belongs to a different target → 404 (a caller gated
    # for `crewman` cannot read another crewman's note by id).
    client = _client(_runtime(notes_store=_MismatchStore(db_path="")))
    r = client.get("/api/counselor/notes/crewman/some-note-id")
    assert r.status_code == 404
    assert r.json()["detail"] == "clinical_note_not_found"
    assert "not-yours" not in r.text


# --------------------------------------------------------------------------- #
# Audit — a row on every read AND write (allow + deny)
# --------------------------------------------------------------------------- #


def test_audit_row_on_every_read_and_write() -> None:
    runtime = _runtime()
    client = _client(runtime)

    w = client.post("/api/counselor/notes/crewman", json={"body": "x"})  # write allow
    r = client.get("/api/counselor/notes/crewman")  # read allow
    d = client.get("/api/counselor/notes/crewman?as_agent_id=officer")  # read deny
    assert w.status_code == 200
    assert r.status_code == 200
    assert d.status_code == 403

    rows = list(runtime.clinical_access_audit)
    assert len(rows) == 3
    assert {row["query_type"] for row in rows} == {"notes_write", "notes_read"}
    # Allow rows for write+read, one deny row for the officer read.
    assert sorted(row["granted"] for row in rows) == [False, True, True]
    for row in rows:
        assert row["target_agent_id"] == "crewman"
        assert row["requester_agent_id"]  # captain or officer, never empty


# --------------------------------------------------------------------------- #
# Honest-degrade + fail-closed (never leak a note body)
# --------------------------------------------------------------------------- #


def test_store_none_returns_503() -> None:
    runtime = _Runtime(agent_types=_AGENT_TYPES, notes_store=None)
    client = _client(runtime)
    r = client.get("/api/counselor/notes/crewman")  # captain passes gate → 503
    assert r.status_code == 503
    w = client.post("/api/counselor/notes/crewman", json={"body": "x"})
    assert w.status_code == 503


def test_fail_closed_store_error_no_body_leak() -> None:
    # A store whose read raises → 503, and the boom text never reaches the body.
    client = _client(_runtime(notes_store=_BoomStore(db_path="")))
    r = client.get("/api/counselor/notes/crewman")
    assert r.status_code == 503
    assert r.json()["detail"] == "clinical_notes_unavailable"
    assert "boom" not in r.text
    w = client.post("/api/counselor/notes/crewman", json={"body": "x"})
    assert w.status_code == 503


def test_fail_closed_audit_append_error_no_body_leak() -> None:
    # The audit ring's append raises on an ALLOW path. The CONFIDENTIAL gate
    # fails closed (503) BEFORE the store is read, so the sentinel body that the
    # store WOULD have returned is never served.
    runtime = _runtime(notes_store=_SentinelStore(db_path=""), audit=_BoomDeque())
    client = _client(runtime)
    r = client.get("/api/counselor/notes/crewman")  # captain → allow, but audit booms
    assert r.status_code == 503
    assert r.json()["detail"] == "clinical_notes_unavailable"
    assert _SentinelStore.SECRET not in r.text


def test_fail_closed_audit_ring_absent_denies() -> None:
    # No audit ring at all → a CONFIDENTIAL access that cannot be recorded is
    # denied (503), never served.
    runtime = _Runtime(
        agent_types=_AGENT_TYPES,
        notes_store=_SentinelStore(db_path=""),
        audit=None,
    )
    runtime.clinical_access_audit = None  # explicitly strip the ring
    client = _client(runtime)
    r = client.get("/api/counselor/notes/crewman")
    assert r.status_code == 503
    assert _SentinelStore.SECRET not in r.text
