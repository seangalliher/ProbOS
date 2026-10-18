"""AD-1340 S2a (M2): the memory pass-throughs and the route ``POST /api/security/archive/lookup``.

A real ``EpisodicMemory`` (real ChromaDB, FTS5 sidecar, ``ActivationTracker``, ``ParticipantIndex`` and
``EvictionAuditLog``) on ``tmp_path``, built like S1's rig. A raw read-only ``sqlite3`` connection of our own is the
independent witness for the archive and its access rows. Episodes leave the live store through Step 12's own call,
``evict_by_ids(ids, reason="activation_decay")``.

The route tests go through the REAL app: ``create_app`` with a ``MagicMock`` runtime that carries a real
``SystemConfig``, the real memory, ``attachment_store = None`` and ``data_dir = tmp_path``. Requests use
``httpx.AsyncClient`` over ``ASGITransport`` in the test's OWN event loop, never ``TestClient``: the memory's aiosqlite
connections and locks belong to this loop. Nothing mocks the lookup, the archive or the erasure. Every test states its
premise first, so a pass cannot be vacuous, and every wait that could hang is bounded.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import math
import sqlite3
from collections.abc import AsyncIterator, Awaitable, Sequence
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import ValidationError

from probos.api import create_app
from probos.cognitive.activation_tracker import ActivationTracker
from probos.cognitive.episode_archive import ARCHIVE_FILENAME, EpisodeArchiveUnavailable
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.eviction_audit import EvictionAuditLog
from probos.cognitive.participant_index import ParticipantIndex
from probos.config import SystemConfig
from probos.routers.security import ArchiveLookupRequest
from probos.types import AnchorFrame, Episode, EpisodeStoreOutcome

# Long ago, so BF-039's last-hour rate limit and its content dedup never see these episodes.
_T0 = 1_700_000_000.0
_WORDS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot")
_LOOKUP = "/api/security/archive/lookup"
_FORGET = "/api/security/forget"
_ACCESSOR = "captain:/api/security/archive/lookup"
_TOKEN = "s2a-test-crew-scope-token"
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}
_WAIT = 10.0  # the bound on every wait that could hang: a lookup, a request, a task
# Each way the archive can be unavailable, and the typed error (the route's 503 detail) it must give.
_UNAVAILABLE = (
    ("absent", "episode_archive_not_open"),  # delete mode, no archive file
    ("failed", "episode_archive_failed_to_open"),  # a file the archive refuses to open
    ("stopped", "episode_archive_not_open"),  # opened, then stopped
)


# --- helpers (copied from tests/test_ad1340_s1_eviction.py, test-local) --------------------------------------------


def _episode(i: int) -> Episode:
    word = _WORDS[i]
    return Episode(
        id=f"ep-{i:03d}",
        timestamp=_T0 + 600.0 * i,
        user_input=f"{word} section reported the {word} coolant loop reading",
        agent_ids=["agent-a"],
        source="direct",
        anchors=AnchorFrame(participants=["worf"]),
        outcomes=[{"intent": "report", "success": True}],
    )


@dataclasses.dataclass
class _Rig:
    em: EpisodicMemory
    root: Path
    activations: ActivationTracker
    participants: ParticipantIndex


@contextlib.asynccontextmanager
async def _memory(root: Path, mode: str, *, max_episodes: int = 100) -> AsyncIterator[_Rig]:
    """A started memory with every real sidecar wired; everything is stopped on the way out."""
    root.mkdir(parents=True, exist_ok=True)
    audit = EvictionAuditLog()
    await audit.start(str(root / "eviction_audit.db"))
    participants = ParticipantIndex(db_path=str(root / "participant_index.db"))
    activations = ActivationTracker(db_path=str(root / "activation.db"))
    em = EpisodicMemory(
        db_path=str(root / "chroma" / "episodes.db"),
        max_episodes=max_episodes,
        relevance_threshold=0.0,
        eviction_audit=audit,
        eviction_disposition=mode,
    )
    try:
        await participants.start()
        await activations.start()
        em.set_participant_index(participants)
        em.set_activation_tracker(activations)
        # AD-1340 R1: the rig's sidecar files, as startup declares them (ERASE reaches an unwired store through these).
        em.set_erasure_sidecar_paths(
            activation_db_path=str(root / "activation.db"),
            participant_index_db_path=str(root / "participant_index.db"),
        )
        await em.start()
        yield _Rig(em, root, activations, participants)
    finally:
        await em.stop()
        await participants.stop()
        await activations.stop()
        await audit.stop()


def _raw(em: EpisodicMemory, ids: Sequence[str]) -> dict[str, Any]:
    """What the live ChromaDB collection holds for these ids (test-only private access)."""
    return em._collection.get(ids=list(ids), include=["documents", "metadatas"])


def _query(path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """Read through a connection of our own. Read-only, so a missing file is an error and is never created."""
    with contextlib.closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)) as connection:
        return connection.execute(sql, params).fetchall()


# --- helpers (S2a) -------------------------------------------------------------------------------------------------


def _archive_path(root: Path) -> Path:
    return root / "chroma" / ARCHIVE_FILENAME


def _count(root: Path, table: str, episode_id: str) -> int:
    return _query(_archive_path(root), f"SELECT count(*) FROM {table} WHERE episode_id = ?", (episode_id,))[0][0]


def _access_rows(root: Path, episode_id: str) -> list[tuple[Any, ...]]:
    return _query(
        _archive_path(root),
        "SELECT accessor, purpose FROM archive_access WHERE episode_id = ? ORDER BY id",
        (episode_id,),
    )


async def _bounded(awaitable: Awaitable[Any], *, timeout: float = _WAIT) -> Any:
    return await asyncio.wait_for(awaitable, timeout=timeout)


async def _store_and_evict(em: EpisodicMemory, indexes: Sequence[int]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Store episodes, take each raw live record, then evict them as Step 12 does; return the records by id."""
    ids = [f"ep-{i:03d}" for i in indexes]
    for i in indexes:
        assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
    live = _raw(em, ids)
    assert sorted(live["ids"]) == sorted(ids)  # premise: every episode is live, and its raw record is taken now
    snapshot = {eid: (doc, dict(meta)) for eid, doc, meta in zip(live["ids"], live["documents"], live["metadatas"])}
    assert await em.evict_by_ids(ids, reason="activation_decay") == len(ids)  # Step 12's own call
    assert _raw(em, ids)["ids"] == []  # premise: none of them is live any more
    return snapshot


@contextlib.asynccontextmanager
async def _memory_without_archive(root: Path, state: str) -> AsyncIterator[EpisodicMemory]:
    """A started memory whose archive is unavailable in the named way (``_UNAVAILABLE``); each premise is asserted."""
    path = _archive_path(root)
    if state == "failed":
        path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(sqlite3.connect(path, timeout=5)) as connection:
            connection.execute("PRAGMA user_version = 7")  # a schema version the archive does not know
            connection.commit()
        assert _query(path, "PRAGMA user_version") == [(7,)]  # premise: a real file at that version exists
    async with _memory(root, "delete" if state == "absent" else "archive") as rig:
        if state == "absent":
            assert not path.exists()  # premise: delete mode never made an archive file
        elif state == "stopped":
            assert rig.em.archive_available  # premise: the archive was open before the stop
            await rig.em.stop()
        assert not rig.em.archive_available  # premise: there is no open archive
        yield rig.em


def _tripwire() -> tuple[Any, list[str]]:
    """A stand-in for the live collection: ANY attribute access raises, and is recorded (a swallowed error still shows)."""
    touched: list[str] = []

    class _Tripwire:
        def __getattribute__(self, name: str) -> Any:
            touched.append(name)
            raise AssertionError(f"the live store was touched through .{name}")

    return _Tripwire(), touched


async def _take(lock: asyncio.Lock) -> None:
    async with lock:
        pass


def _runtime(root: Path, memory: EpisodicMemory | None, *, token: str = "") -> MagicMock:
    """The route's runtime: a real ``SystemConfig`` (the token set on it), the real memory, no attachment store."""
    runtime = MagicMock()
    config = SystemConfig()
    config.auth.crew_scope_token = token
    runtime.config = config
    runtime.episodic_memory = memory
    runtime.attachment_store = None
    runtime.data_dir = root
    runtime._data_dir = root  # create_app prefers this; left a MagicMock it makes a stray MagicMock/ dir in the repo
    return runtime


@contextlib.asynccontextmanager
async def _client(runtime: MagicMock) -> AsyncIterator[httpx.AsyncClient]:
    """The real app, called in this test's own event loop (never ``TestClient``, which runs the app in another)."""
    app = create_app(runtime)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _post(
    client: httpx.AsyncClient,
    path: str,
    body: Any = None,
    *,
    headers: dict[str, str] | None = None,
    content: bytes | None = None,
) -> httpx.Response:
    if content is not None:
        request = client.post(path, content=content, headers=headers)
    else:
        request = client.post(path, json=body, headers=headers)
    return await _bounded(request)


def _episode_ids(body: dict[str, Any]) -> list[str]:
    return [episode["episode_id"] for episode in body["episodes"]]


# --- E: the memory pass-throughs ---------------------------------------------------------------------------------


async def test_memory_lookup_finds_an_evicted_episode_byte_equal(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        snapshot = await _store_and_evict(em, [0])  # the raw record is taken before the eviction
        eid = "ep-000"
        document, metadata = snapshot[eid]
        assert _count(tmp_path, "episode_archive", eid) == 1  # premise: archived (and no longer live: see above)
        assert _count(tmp_path, "archive_access", eid) == 0  # premise: nothing has read it yet

        by_id = await _bounded(em.lookup_archived_by_id(eid, accessor="test"))
        by_agent = await _bounded(em.lookup_archived_by_agent("agent-a", accessor="test"))

        # each pass-through handed the caller's accessor on, and each lookup was audited once
        assert _access_rows(tmp_path, eid) == [("test", "lookup"), ("test", "lookup")]

    for result in (by_id, by_agent):
        assert [item.record.episode_id for item in result.episodes] == [eid]
        record = result.episodes[0].record
        assert record.document == document
        assert dict(record.metadata) == metadata
        assert (result.undecodable, result.withdrawn, result.truncated) == (0, 0, False)


async def test_memory_lookup_never_touches_the_live_store(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        await _store_and_evict(em, [0])
        assert _count(tmp_path, "episode_archive", "ep-000") == 1  # premise: archived
        live_collection = em._collection
        assert live_collection is not None  # premise: there is a live store to leave alone
        tripwire, touched = _tripwire()
        em._collection = tripwire  # test-only private access; restored in the finally below
        try:
            with pytest.raises(AssertionError, match="the live store was touched"):
                _ = tripwire.get  # premise: the tripwire fires on any access
            touched.clear()

            by_id = await _bounded(em.lookup_archived_by_id("ep-000", accessor="test"))
            by_agent = await _bounded(em.lookup_archived_by_agent("agent-a", accessor="test"))
        finally:
            em._collection = live_collection
        assert em._collection is live_collection

    assert touched == []  # nothing reached for the live store, not even in a way that was swallowed
    for result in (by_id, by_agent):
        assert [item.record.episode_id for item in result.episodes] == ["ep-000"]


async def test_memory_lookup_takes_no_store_lock(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        await _store_and_evict(em, [0])
        assert _count(tmp_path, "episode_archive", "ep-000") == 1  # premise: archived
        lock = em._get_store_write_lock()  # test-only private access
        taker: asyncio.Task[None] | None = None
        try:
            async with lock:
                assert lock.locked()  # premise: this test holds the store write lock
                taker = asyncio.create_task(_take(lock))
                done, _ = await asyncio.wait({taker}, timeout=0.3)
                assert not done  # premise: anything that takes the lock waits behind us

                by_id = await asyncio.wait_for(em.lookup_archived_by_id("ep-000", accessor="test"), timeout=2)
                by_agent = await asyncio.wait_for(em.lookup_archived_by_agent("agent-a", accessor="test"), timeout=2)
                assert not taker.done()  # the lock was held throughout, so neither lookup needed it
            await asyncio.wait_for(taker, timeout=2)  # released: the waiting taker proceeds
        finally:
            if taker is not None:
                if not taker.done():
                    taker.cancel()
                await asyncio.gather(taker, return_exceptions=True)

    for result in (by_id, by_agent):
        assert [item.record.episode_id for item in result.episodes] == ["ep-000"]


async def test_memory_lookup_without_an_archive_raises(tmp_path: Path) -> None:
    for state, detail in _UNAVAILABLE:
        async with _memory_without_archive(tmp_path / state, state) as em:
            with pytest.raises(EpisodeArchiveUnavailable, match=rf"^{detail}$"):
                await _bounded(em.lookup_archived_by_id("ep-000", accessor="test"))
            with pytest.raises(EpisodeArchiveUnavailable, match=rf"^{detail}$"):
                await _bounded(em.lookup_archived_by_agent("agent-a", accessor="test"))


# --- RT: the route, through the real app -------------------------------------------------------------------------


async def test_route_refuses_without_a_configured_token_before_any_read(tmp_path: Path) -> None:
    refusal = (403, {"detail": "episode_archive_lookup_requires_token"})
    async with _memory(tmp_path / "open", "archive") as rig:
        await _store_and_evict(rig.em, [0])
        root = tmp_path / "open"
        assert _count(root, "episode_archive", "ep-000") == 1  # premise: there is something to read
        assert _count(root, "archive_access", "ep-000") == 0  # premise: nothing has read it yet
        runtime = _runtime(root, rig.em, token="")
        assert runtime.config.auth.crew_scope_token == ""  # premise: no token is configured

        async with _client(runtime) as client:
            for body in ({"episode_id": "ep-000"}, {"agent_id": "agent-a"}):
                response = await _post(client, _LOOKUP, body)
                assert (response.status_code, response.json()) == refusal
                response = await _post(client, _LOOKUP, body, headers=_AUTH)  # a presented token changes nothing
                assert (response.status_code, response.json()) == refusal
        assert _count(root, "archive_access", "ep-000") == 0  # nothing was read, so nothing was audited

    # With the archive in the "failed" state the answer is still 403, not 503: the token check comes first.
    async with _memory_without_archive(tmp_path / "failed", "failed") as em:
        with pytest.raises(EpisodeArchiveUnavailable, match=r"^episode_archive_failed_to_open$"):
            await _bounded(em.lookup_archived_by_id("ep-000", accessor="test"))  # premise: a read would give 503
        async with _client(_runtime(tmp_path / "failed", em, token="")) as client:
            for body in ({"episode_id": "ep-000"}, {"agent_id": "agent-a"}):
                response = await _post(client, _LOOKUP, body)
                assert (response.status_code, response.json()) == refusal


async def test_route_rejects_a_missing_or_wrong_token(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        await _store_and_evict(rig.em, [0])
        assert _count(tmp_path, "episode_archive", "ep-000") == 1  # premise: there is something to read
        assert _count(tmp_path, "archive_access", "ep-000") == 0  # premise: nothing has read it yet
        runtime = _runtime(tmp_path, rig.em, token=_TOKEN)
        assert runtime.config.auth.crew_scope_token == _TOKEN  # premise: a token is configured

        async with _client(runtime) as client:
            for body in ({"episode_id": "ep-000"}, {"agent_id": "agent-a"}):
                response = await _post(client, _LOOKUP, body)  # no Authorization header
                assert (response.status_code, response.json()) == (
                    401, {"detail": "missing_or_malformed_authorization"},
                )
                response = await _post(client, _LOOKUP, body, headers={"Authorization": f"Basic {_TOKEN}"})
                assert (response.status_code, response.json()) == (
                    401, {"detail": "missing_or_malformed_authorization"},
                )
                response = await _post(client, _LOOKUP, body, headers={"Authorization": "Bearer not-the-token"})
                assert (response.status_code, response.json()) == (401, {"detail": "invalid_token"})
            # Authentication is checked before the non-finite-number guard (A2): a NaN body without a header is 401.
            response = await _post(
                client, _LOOKUP, content=b'{"agent_id":"agent-a","since":NaN}',
                headers={"Content-Type": "application/json"},
            )
            assert (response.status_code, response.json()) == (
                401, {"detail": "missing_or_malformed_authorization"},
            )
        assert _count(tmp_path, "archive_access", "ep-000") == 0  # nothing was read, so nothing was audited


async def test_route_returns_the_archived_record_by_id_and_records_one_access(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        snapshot = await _store_and_evict(rig.em, [0])  # the raw record is taken before the eviction
        eid = "ep-000"
        document, metadata = snapshot[eid]
        assert _count(tmp_path, "episode_archive", eid) == 1  # premise: archived
        assert _count(tmp_path, "archive_access", eid) == 0  # premise: nothing has read it yet

        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            response = await _post(client, _LOOKUP, {"episode_id": eid}, headers=_AUTH)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["lookup"] == "episode_id"
        assert "agent_match" not in body
        assert (body["count"], body["truncated"], body["undecodable"], body["withdrawn"]) == (1, False, 0, 0)
        [episode] = body["episodes"]
        assert set(episode) == {
            "episode_id", "content_hash", "agent_id", "episode_timestamp", "archived_at", "reason", "document",
            "metadata",
        }
        assert episode["episode_id"] == eid
        assert episode["document"] == document  # the raw record, as the live store held it
        assert episode["metadata"] == metadata
        assert episode["content_hash"] == metadata["content_hash"]
        assert (episode["agent_id"], episode["episode_timestamp"], episode["reason"]) == (
            "agent-a", _T0, "activation_decay",
        )
        assert _access_rows(tmp_path, eid) == [(_ACCESSOR, "lookup")]  # exactly one raw row, written by the route


async def test_route_by_agent_is_newest_first_and_states_the_primary_agent_rule(tmp_path: Path) -> None:
    ids = ["ep-000", "ep-001", "ep-002"]  # stored oldest first: timestamps _T0, _T0 + 600, _T0 + 1200
    async with _memory(tmp_path, "archive") as rig:
        await _store_and_evict(rig.em, [0, 1, 2])
        for eid in ids:
            assert _count(tmp_path, "episode_archive", eid) == 1  # premise: archived
            assert _count(tmp_path, "archive_access", eid) == 0  # premise: nothing has read it yet

        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            everything = await _post(client, _LOOKUP, {"agent_id": "agent-a"}, headers=_AUTH)
            limited = await _post(client, _LOOKUP, {"agent_id": "agent-a", "limit": 2}, headers=_AUTH)
            window = await _post(
                client, _LOOKUP, {"agent_id": "agent-a", "since": _T0 + 300.0, "until": _T0 + 900.0}, headers=_AUTH,
            )

        for response in (everything, limited, window):
            assert response.status_code == 200, response.text
            assert response.json()["lookup"] == "agent"
            assert response.json()["agent_match"] == "primary_agent_only"
        assert _episode_ids(everything.json()) == ["ep-002", "ep-001", "ep-000"]  # newest first
        assert (everything.json()["count"], everything.json()["truncated"]) == (3, False)
        assert _episode_ids(limited.json()) == ["ep-002", "ep-001"]
        assert (limited.json()["count"], limited.json()["truncated"]) == (2, True)
        assert _episode_ids(window.json()) == ["ep-001"]  # the middle one only
        assert (window.json()["count"], window.json()["truncated"]) == (1, False)
        # every episode that was returned was audited, once per call that returned it, and nothing else was
        assert [len(_access_rows(tmp_path, eid)) for eid in ids] == [1, 3, 2]


async def test_route_validates_the_request(tmp_path: Path) -> None:
    invalid: list[tuple[str, dict[str, Any], str]] = [
        ("both ids", {"episode_id": "ep-000", "agent_id": "agent-a"}, "exactly one of episode_id/agent_id"),
        ("neither id", {}, "exactly one of episode_id/agent_id"),
        ("since with episode_id", {"episode_id": "ep-000", "since": 1.0}, "apply only to an agent_id lookup"),
        ("until with episode_id", {"episode_id": "ep-000", "until": 2.0}, "apply only to an agent_id lookup"),
        ("limit with episode_id", {"episode_id": "ep-000", "limit": 5}, "apply only to an agent_id lookup"),
        ("since after until", {"agent_id": "agent-a", "since": 20.0, "until": 10.0}, "since must be earlier"),
        ("since equal to until", {"agent_id": "agent-a", "since": 10.0, "until": 10.0}, "since must be earlier"),
        ("limit 0", {"agent_id": "agent-a", "limit": 0}, "greater_than_equal"),
        ("limit 201", {"agent_id": "agent-a", "limit": 201}, "less_than_equal"),
        ("unknown field", {"agent_id": "agent-a", "episode": "ep-000"}, "extra_forbidden"),
        ("empty episode_id", {"episode_id": ""}, "string_too_short"),
        ("episode_id of 257 characters", {"episode_id": "e" * 257}, "string_too_long"),
        ("agent_id of 257 characters", {"agent_id": "a" * 257}, "string_too_long"),
    ]
    raw_invalid: list[tuple[str, bytes]] = [  # the JSON parser accepts these; the route-local guard must refuse them (A2)
        ("since NaN", b'{"agent_id":"agent-a","since":NaN}'),
        ("until Infinity", b'{"agent_id":"agent-a","until":Infinity}'),
        ("until -Infinity", b'{"agent_id":"agent-a","until":-Infinity}'),
        ("since 1e999 (overflow)", b'{"agent_id":"agent-a","since":1e999}'),
        ("episode_id with since NaN", b'{"episode_id":"ep-000","since":NaN}'),
        ("limit NaN", b'{"agent_id":"agent-a","limit":NaN}'),
        ("unknown field NaN", b'{"agent_id":"agent-a","zzz":NaN}'),
    ]
    async with _memory(tmp_path, "archive") as rig:
        await _store_and_evict(rig.em, [0])
        assert _count(tmp_path, "episode_archive", "ep-000") == 1  # premise: a wrongly accepted request would read it
        assert _count(tmp_path, "archive_access", "ep-000") == 0  # premise: nothing has read it yet

        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            for label, body, why in invalid:
                response = await _post(client, _LOOKUP, body, headers=_AUTH)
                assert response.status_code == 422, f"{label}: {response.status_code} {response.text}"
                assert why in response.text, f"{label}: refused for another reason: {response.text}"
            assert _count(tmp_path, "archive_access", "ep-000") == 0  # no refused request wrote an access row

            # The boundaries of the same rules are accepted (an agent with nothing archived, so no row is written).
            for body in (
                {"agent_id": "nobody", "limit": 1},
                {"agent_id": "nobody", "limit": 200},
                {"agent_id": "nobody", "since": 1.0, "until": 2.0},
                {"agent_id": "a" * 256},
                {"episode_id": "e" * 256},
            ):
                response = await _post(client, _LOOKUP, body, headers=_AUTH)
                assert response.status_code == 200, f"{body}: {response.status_code} {response.text}"
                assert response.json()["episodes"] == []

            # The bodies the JSON parser accepts but no finite range can hold (sent raw: `json=` cannot encode them).
            # The framework would answer 500 here (its 422 handler cannot encode NaN); the route-local guard gives 422.
            for label, content in raw_invalid:
                response = await _post(
                    client, _LOOKUP, content=content, headers={"Content-Type": "application/json", **_AUTH},
                )
                assert (response.status_code, response.json()) == (
                    422, {"detail": "non_finite_number_in_body"},
                ), f"{label}: {response.status_code} {response.text}"
        assert _count(tmp_path, "archive_access", "ep-000") == 0

    # The model's own finiteness check stays as defence in depth: reached directly, it still refuses NaN.
    with pytest.raises(ValidationError, match="since/until must be finite"):
        ArchiveLookupRequest.model_validate({"agent_id": "agent-a", "since": math.nan})


async def test_route_maps_an_unavailable_archive_to_503(tmp_path: Path) -> None:
    bodies = ({"episode_id": "ep-000"}, {"agent_id": "agent-a"})
    async with _client(_runtime(tmp_path / "none", None, token=_TOKEN)) as client:  # no episodic memory at all
        for body in bodies:
            response = await _post(client, _LOOKUP, body, headers=_AUTH)
            assert (response.status_code, response.json()) == (503, {"detail": "episodic_memory_unavailable"})

    for state, detail in _UNAVAILABLE:
        async with _memory_without_archive(tmp_path / state, state) as em:
            async with _client(_runtime(tmp_path / state, em, token=_TOKEN)) as client:
                for body in bodies:
                    response = await _post(client, _LOOKUP, body, headers=_AUTH)
                    assert (response.status_code, response.json()) == (503, {"detail": detail}), state


async def test_seam_evict_lookup_forget_leaves_nothing(tmp_path: Path) -> None:
    eid = "ep-000"
    async with _memory(tmp_path, "archive") as rig:
        await _store_and_evict(rig.em, [0])  # Step 12's own eviction call archives it
        assert _count(tmp_path, "episode_archive", eid) == 1  # premise: archived
        assert _count(tmp_path, "archive_access", eid) == 0  # premise: nothing has read it yet

        async with _client(_runtime(tmp_path, rig.em, token=_TOKEN)) as client:
            looked_up = await _post(client, _LOOKUP, {"episode_id": eid}, headers=_AUTH)
            assert looked_up.status_code == 200, looked_up.text
            assert _episode_ids(looked_up.json()) == [eid]
            assert _count(tmp_path, "archive_access", eid) == 1  # premise: the lookup left its access row

            forgotten = await _post(client, _FORGET, {"episode_id": eid})  # the AD-754 route
            assert forgotten.status_code == 200, forgotten.text
            assert forgotten.json()["deleted_episode_ids"] == [eid]

            assert _count(tmp_path, "episode_archive", eid) == 0  # the archived record is gone
            assert _count(tmp_path, "archive_access", eid) == 0  # and so is every trace of the lookup
            for body in ({"episode_id": eid}, {"agent_id": "agent-a"}):
                after = await _post(client, _LOOKUP, body, headers=_AUTH)
                assert after.status_code == 200, after.text
                assert (after.json()["episodes"], after.json()["count"], after.json()["withdrawn"]) == ([], 0, 0)
            assert _count(tmp_path, "archive_access", eid) == 0  # looking up an erased id leaves nothing behind
