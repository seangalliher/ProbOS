"""AD-1340 S1 (M2): dream pruning and capacity eviction archive the episode; ``delete`` mode keeps today's behaviour.

A real ``EpisodicMemory`` (real ChromaDB, FTS5 sidecar, ``ActivationTracker``, ``ParticipantIndex`` and
``EvictionAuditLog``) on ``tmp_path``. Raw ``sqlite3`` connections of our own are the independent witness for the
archive, the audit and the sidecars; the live store is read back straight from ChromaDB through ``_raw``. Every test
states its premise first, so a pass cannot be vacuous. ``delete`` is the default until M4, so archive-mode tests pass
``"archive"`` explicitly.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
import re
import sqlite3
import time
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from probos.cognitive.activation_tracker import ActivationTracker
from probos.cognitive.episode_archive import ARCHIVE_FILENAME, ARCHIVE_REASONS, decode_payload
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.eviction_audit import EvictionAuditLog
from probos.cognitive.participant_index import ParticipantIndex
from probos.types import AnchorFrame, Episode, EpisodeStoreOutcome

# Long ago, so BF-039's last-hour rate limit and its content dedup never see these episodes.
_T0 = 1_700_000_000.0
_WORDS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot")
_ARCHIVE_COLUMNS = (
    "episode_id", "content_hash", "agent_id", "episode_timestamp", "reason", "archived_at", "payload_format", "payload",
)
_AUDIT_COLUMNS = (
    "id", "episode_id", "agent_id", "timestamp", "reason", "process", "details", "content_hash",
    "episode_timestamp", "disposition", "archive_ref",
)
# The eviction_audit table exactly as the pre-AD-1340 code created it: nine columns.
_LEGACY_AUDIT_DDL = """\
CREATE TABLE eviction_audit (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    reason TEXT NOT NULL,
    process TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    episode_timestamp REAL NOT NULL DEFAULT 0.0
);
"""


# --- helpers -------------------------------------------------------------------------------------------------


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


def _ids(count: int) -> list[str]:
    return [f"ep-{i:03d}" for i in range(count)]


@dataclasses.dataclass
class _Rig:
    em: EpisodicMemory
    root: Path
    activations: ActivationTracker


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
        await em.start()
        yield _Rig(em, root, activations)
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


def _archive_rows(root: Path) -> list[dict[str, Any]]:
    rows = _query(
        root / "chroma" / ARCHIVE_FILENAME,
        f"SELECT {', '.join(_ARCHIVE_COLUMNS)} FROM episode_archive ORDER BY episode_id",
    )
    return [dict(zip(_ARCHIVE_COLUMNS, row)) for row in rows]


def _audit_rows(root: Path) -> list[dict[str, Any]]:
    rows = _query(
        root / "eviction_audit.db", f"SELECT {', '.join(_AUDIT_COLUMNS)} FROM eviction_audit ORDER BY rowid",
    )
    return [dict(zip(_AUDIT_COLUMNS, row)) for row in rows]


def _column_names(path: Path) -> list[str]:
    return [row[1] for row in _query(path, "PRAGMA table_info(eviction_audit)")]


def _sidecar_counts(root: Path, episode_id: str) -> dict[str, int]:
    """Rows the FTS5, activation and participant sidecars hold for one episode."""

    def _count(path: Path, sql: str) -> int:
        return _query(path, sql, (episode_id,))[0][0]

    return {
        "fts": _count(root / "chroma" / "episode_fts.db", "SELECT count(*) FROM episode_fts WHERE episode_id = ?"),
        "activation": _count(root / "activation.db", "SELECT count(*) FROM episode_access_log WHERE episode_id = ?"),
        "participants": _count(
            root / "participant_index.db", "SELECT count(*) FROM episode_participants WHERE episode_id = ?",
        ),
    }


def _warnings(caplog: pytest.LogCaptureFixture, needle: str) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and needle in record.getMessage()
    ]


class _CollectionProxy:
    """Forwards to the real ChromaDB collection, records each call, and can fail ``delete`` once."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls: list[tuple[str, Any]] = []
        self.fail_next_delete = False

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self.inner, name)
        if not callable(attribute):
            return attribute

        def _forward(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, kwargs.get("include")))
            if name == "delete" and self.fail_next_delete:
                self.fail_next_delete = False
                raise RuntimeError("injected: delete failed")
            return attribute(*args, **kwargs)

        return _forward


def _record_collection(em: EpisodicMemory) -> _CollectionProxy:
    """Interpose a recording proxy on the live collection (test-only private access).

    Wrapping again replaces the previous proxy, so each measurement starts with an empty call list.
    """
    current = em._collection
    proxy = _CollectionProxy(current.inner if isinstance(current, _CollectionProxy) else current)
    em._collection = proxy
    return proxy


async def _read_surfaces(em: EpisodicMemory, ids: list[str], queries: Sequence[str]) -> dict[str, Any]:
    """Every read surface AD-1340 must leave untouched, as plain comparable data."""
    return {
        "recall": {q: [e.id for e in await em.recall(q, k=6)] for q in queries},
        "recall_for_agent": {q: [e.id for e in await em.recall_for_agent("agent-a", q, k=6)] for q in queries},
        "recent_for_agent": [e.id for e in await em.recent_for_agent("agent-a", k=10)],
        "keyword_search": {word: await em.keyword_search(word) for word in _WORDS},
        "get_by_ids": await em.get_by_ids(ids),
    }


# --- E1 ------------------------------------------------------------------------------------------------------


async def test_golden_recall_is_identical_under_archive_and_delete(tmp_path: Path) -> None:
    ids = _ids(6)
    evicted = [ids[1], ids[4]]  # the "bravo" and "echo" episodes
    survivors = [eid for eid in ids if eid not in evicted]
    queries = ("alpha coolant loop", "delta bravo section", "foxtrot reading")
    async with _memory(tmp_path / "A", "archive") as with_archive, _memory(tmp_path / "D", "delete") as with_delete:
        for rig in (with_archive, with_delete):
            for i in range(6):
                assert await rig.em.store(_episode(i)) is EpisodeStoreOutcome.STORED
            assert sorted(_raw(rig.em, ids)["ids"]) == ids  # premise: six live episodes in each memory
        assert await with_archive.em.evict_by_ids(evicted, reason="activation_decay") == 2
        assert await with_delete.em.evict_by_ids(evicted, reason="activation_decay") == 2
        # premise: only A kept the evicted pair, in its archive; D never made an archive file
        assert [row["episode_id"] for row in _archive_rows(with_archive.root)] == evicted
        assert not (with_delete.root / "chroma" / ARCHIVE_FILENAME).exists()
        for rig in (with_archive, with_delete):
            assert sorted(_raw(rig.em, ids)["ids"]) == survivors

        seen_a = await _read_surfaces(with_archive.em, ids, queries)
        seen_d = await _read_surfaces(with_delete.em, ids, queries)

    assert seen_a == seen_d
    # Equality of two empty results would prove nothing: each surface must return the survivors, and only them.
    for surface in ("recall", "recall_for_agent"):
        found = {eid for result in seen_a[surface].values() for eid in result}
        assert found and found <= set(survivors), surface
    assert set(seen_a["recent_for_agent"]) == set(survivors)
    assert [episode.id for episode in seen_a["get_by_ids"]] == survivors
    assert {word: [eid for eid, _ in hits] for word, hits in seen_a["keyword_search"].items()} == {
        word: ([eid] if eid in survivors else []) for word, eid in zip(_WORDS, ids)
    }


# --- E2 ------------------------------------------------------------------------------------------------------


async def test_dream_eviction_archives_then_deletes(tmp_path: Path) -> None:
    cases = (("ep-000", "activation_decay"), ("ep-001", "activation_decay_aggressive"))
    control = "ep-002"
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        for i in range(3):
            assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        assert em.archive_available
        before: dict[str, dict[str, Any]] = {}
        for eid in (*(case[0] for case in cases), control):
            await rig.activations.record_access(eid)
            before[eid] = _raw(em, [eid])
            # premise: live, in all three sidecars, and carrying a real content hash to compare against
            assert before[eid]["ids"] == [eid]
            assert _sidecar_counts(rig.root, eid) == {"fts": 1, "activation": 1, "participants": 2}
            assert before[eid]["metadatas"][0]["content_hash"]
        assert _archive_rows(rig.root) == [] and _audit_rows(rig.root) == []

        for eid, reason in cases:
            assert await em.evict_by_ids([eid], reason=reason) == 1

        archived = {row["episode_id"]: row for row in _archive_rows(rig.root)}
        audited = {row["episode_id"]: row for row in _audit_rows(rig.root)}
        assert set(archived) == set(audited) == {eid for eid, _ in cases}
        for eid, reason in cases:
            metadata = before[eid]["metadatas"][0]
            assert _raw(em, [eid])["ids"] == []
            row = archived[eid]
            decoded = decode_payload(row["episode_id"], row["content_hash"], row["payload_format"], row["payload"])
            assert dict(decoded.metadata) == metadata
            assert decoded.document == before[eid]["documents"][0]
            # Property 6: one hash, three places.
            assert row["content_hash"] == metadata["content_hash"] == audited[eid]["content_hash"]
            assert row["reason"] == reason
            audit = audited[eid]
            assert (audit["disposition"], audit["process"], audit["reason"]) == ("archived", "evict_by_ids", reason)
            assert audit["archive_ref"] == f"episode_archive:{eid}:{metadata['content_hash']}"
            assert _sidecar_counts(rig.root, eid) == {"fts": 0, "activation": 0, "participants": 0}

        # The cleanup is targeted: the episode nobody evicted is live, in its sidecars, and not archived.
        assert _raw(em, [control]) == before[control]
        assert _sidecar_counts(rig.root, control) == {"fts": 1, "activation": 1, "participants": 2}


# --- E3 ------------------------------------------------------------------------------------------------------


async def test_capacity_eviction_archives_the_oldest(tmp_path: Path) -> None:
    ids = _ids(3)
    async with _memory(tmp_path, "archive", max_episodes=2) as rig:
        em = rig.em
        assert em.archive_available
        for i in range(2):
            assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        # premise: two episodes fit the budget, so nothing has been evicted, archived or audited yet
        assert sorted(_raw(em, ids)["ids"]) == ids[:2]
        assert _archive_rows(rig.root) == [] and _audit_rows(rig.root) == []

        assert await em.store(_episode(2)) is EpisodeStoreOutcome.STORED

        assert sorted(_raw(em, ids)["ids"]) == ids[1:]  # the oldest left the live store
        assert [(row["episode_id"], row["reason"]) for row in _archive_rows(rig.root)] == [(ids[0], "capacity")]
        audit = _audit_rows(rig.root)
        assert [(r["episode_id"], r["process"], r["reason"], r["disposition"]) for r in audit] == [
            (ids[0], "_evict", "capacity", "archived"),
        ]
        assert audit[0]["details"] == "batch of 1, budget=2"


# --- E4 ------------------------------------------------------------------------------------------------------


async def test_unknown_reason_archives_and_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    cases = (("ep-000", "user_request"), ("ep-001", "qualification_test_cleanup"))
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        for i in range(2):
            assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        for eid, reason in cases:
            # premise: a reason outside the closed archive set, on an episode that is live
            assert reason not in ARCHIVE_REASONS
            assert _raw(em, [eid])["ids"] == [eid]
            caplog.clear()

            assert await em.evict_by_ids([eid], reason=reason) == 1  # no disposition passed

            assert _warnings(caplog, repr(reason))
            assert _raw(em, [eid])["ids"] == []
            # The reason alone never erases: the episode is archived, and audited as archived.
            assert [(r["episode_id"], r["reason"]) for r in _archive_rows(rig.root) if r["episode_id"] == eid] == [
                (eid, reason),
            ]
            assert [r["disposition"] for r in _audit_rows(rig.root) if r["episode_id"] == eid] == ["archived"]


# --- E5 ------------------------------------------------------------------------------------------------------


async def test_invalid_disposition_raises_before_any_change(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        before = _raw(em, ["ep-000"])
        # premise: live, nothing archived, nothing audited
        assert before["ids"] == ["ep-000"]
        assert _archive_rows(rig.root) == [] and _audit_rows(rig.root) == []

        with pytest.raises(TypeError, match="eviction_disposition_invalid"):
            await em.evict_by_ids(["ep-000"], disposition="erase")  # a plain string, not the enum

        assert _raw(em, ["ep-000"]) == before
        assert _archive_rows(rig.root) == [] and _audit_rows(rig.root) == []

    with pytest.raises(ValueError, match="eviction_disposition_invalid"):
        EpisodicMemory(db_path=str(tmp_path / "other" / "episodes.db"), eviction_disposition="purge")


# --- E6 ------------------------------------------------------------------------------------------------------


async def test_archive_write_failure_keeps_the_episode_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        before = _raw(em, ["ep-000"])
        # premise: live, the archive is open and empty, and nothing is audited
        assert before["ids"] == ["ep-000"] and em.archive_available
        assert _archive_rows(rig.root) == [] and _audit_rows(rig.root) == []

        async def _fail(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("injected: disk full")

        monkeypatch.setattr(em._episode_archive, "archive", _fail)

        assert await em.evict_by_ids(["ep-000"], reason="activation_decay") == 0

        assert _raw(em, ["ep-000"]) == before  # an equal document and equal metadata, still live
        assert _archive_rows(rig.root) == [] and _audit_rows(rig.root) == []
        assert _warnings(caplog, "archive write failed")


# --- E7 ------------------------------------------------------------------------------------------------------


async def test_crash_after_archive_commit_then_retry_is_idempotent(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        # premise: live, with nothing archived or audited yet
        assert _raw(em, ["ep-000"])["ids"] == ["ep-000"]
        assert _archive_rows(rig.root) == [] and _audit_rows(rig.root) == []
        proxy = _record_collection(em)
        proxy.fail_next_delete = True

        assert await em.evict_by_ids(["ep-000"], reason="activation_decay") == 0  # the crash: after the archive commit

        assert _raw(em, ["ep-000"])["ids"] == ["ep-000"]
        first = _archive_rows(rig.root)
        assert len(first) == 1

        assert await em.evict_by_ids(["ep-000"], reason="activation_decay") == 1  # the retry

        assert _raw(em, ["ep-000"])["ids"] == []
        assert _archive_rows(rig.root) == first  # conflict do-nothing: still the one row, unchanged
        assert [row["disposition"] for row in _audit_rows(rig.root)] == ["archived", "archived"]  # append-only


# --- E8 ------------------------------------------------------------------------------------------------------


async def test_unavailable_archive_deletes_nothing_and_warns_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    blocker = tmp_path / "chroma" / ARCHIVE_FILENAME
    blocker.mkdir(parents=True)
    assert blocker.is_dir()  # premise: a directory stands where the archive file would be created
    ids = _ids(3)
    async with _memory(tmp_path, "archive", max_episodes=2) as rig:
        em = rig.em
        assert em.archive_available is False
        assert _warnings(caplog, "failed to open")
        for i in range(2):
            assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        # premise: both live, within the budget, and nothing has warned about eviction yet
        assert sorted(_raw(em, ids)["ids"]) == ids[:2]
        assert not _warnings(caplog, "episode archive unavailable")

        assert await em.evict_by_ids([ids[0]], reason="activation_decay") == 0
        assert await em.evict_by_ids([ids[1]], reason="activation_decay") == 0

        assert sorted(_raw(em, ids)["ids"]) == ids[:2]
        assert _audit_rows(rig.root) == []
        assert len(_warnings(caplog, "episode archive unavailable")) == 1  # rate limited, not once per call

        # Capacity eviction is held to the same rule: the budget is exceeded rather than an episode lost.
        assert await em.store(_episode(2)) is EpisodeStoreOutcome.STORED
        assert sorted(_raw(em, ids)["ids"]) == ids
        assert _audit_rows(rig.root) == []
        assert len(_warnings(caplog, "episode archive unavailable")) == 1
    assert blocker.is_dir()  # nothing ever replaced the directory with a file


# --- E9 ------------------------------------------------------------------------------------------------------


async def test_delete_mode_is_todays_behaviour(tmp_path: Path) -> None:
    async with _memory(tmp_path, "delete") as rig:
        em = rig.em
        for i in range(4):
            assert await em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        # premise: delete mode, no archive anywhere, and real metadata to derive today's audit values from
        assert em.eviction_disposition_mode == "delete" and em.archive_available is False
        assert list(tmp_path.rglob(ARCHIVE_FILENAME)) == []
        metadata = {eid: _raw(em, [eid])["metadatas"][0] for eid in ("ep-001", "ep-000")}
        for meta in metadata.values():
            assert json.loads(meta["agent_ids_json"]) == ["agent-a"] and meta["content_hash"]

        proxy = _record_collection(em)
        started = time.time()
        assert await em.evict_by_ids(["ep-001"], reason="activation_decay") == 1
        dream_window = (started, time.time())
        assert proxy.calls == [("get", ["metadatas"]), ("delete", None)]

        em.max_episodes = 2  # three are live, so exactly the oldest goes
        proxy = _record_collection(em)
        started = time.time()
        await em._evict()
        capacity_window = (started, time.time())
        assert proxy.calls == [("count", None), ("get", ["metadatas"]), ("delete", None)]

        assert sorted(_raw(em, _ids(4))["ids"]) == ["ep-002", "ep-003"]
        assert list(tmp_path.rglob(ARCHIVE_FILENAME)) == []
        audit = _audit_rows(rig.root)
        expected = (
            ("ep-001", "activation_decay", "evict_by_ids", "batch of 1, reason=activation_decay", dream_window),
            ("ep-000", "capacity", "_evict", "batch of 1, budget=2", capacity_window),
        )
        assert len(audit) == len(expected)
        for row, (eid, reason, process, details, window) in zip(audit, expected):
            meta = metadata[eid]
            assert re.fullmatch(r"[0-9a-f]{32}", row["id"])
            assert isinstance(row["timestamp"], float) and window[0] <= row["timestamp"] <= window[1]
            assert row["episode_id"] == eid
            assert row["agent_id"] == json.loads(meta["agent_ids_json"])[0]
            assert (row["reason"], row["process"], row["details"]) == (reason, process, details)
            assert row["content_hash"] == meta["content_hash"]
            assert row["episode_timestamp"] == meta["timestamp"]
            assert (row["disposition"], row["archive_ref"]) == ("deleted", "")


# --- E10 -----------------------------------------------------------------------------------------------------


async def test_delete_mode_leaves_an_existing_archive_untouched_by_eviction(tmp_path: Path) -> None:
    async with _memory(tmp_path, "archive") as rig:
        for i in range(2):
            assert await rig.em.store(_episode(i)) is EpisodeStoreOutcome.STORED
        assert await rig.em.evict_by_ids(["ep-000"], reason="activation_decay") == 1
        archived = _archive_rows(rig.root)
        assert [row["episode_id"] for row in archived] == ["ep-000"]  # premise: X is archived, Y is still live

    async with _memory(tmp_path, "delete") as rig:
        em = rig.em
        assert em.eviction_disposition_mode == "delete"
        assert em.archive_available is True  # the file left by archive mode was opened, not created
        assert _raw(em, ["ep-001"])["ids"] == ["ep-001"]  # premise: Y survived the restart

        assert await em.evict_by_ids(["ep-001"], reason="activation_decay") == 1

        assert _raw(em, ["ep-001"])["ids"] == []
        assert _archive_rows(rig.root) == archived  # exactly one row, X, byte for byte
        deleted = [row for row in _audit_rows(rig.root) if row["episode_id"] == "ep-001"]
        assert [(row["disposition"], row["archive_ref"]) for row in deleted] == [("deleted", "")]


# --- E11 -----------------------------------------------------------------------------------------------------


async def test_audit_columns_migrate_an_old_file(tmp_path: Path) -> None:
    path = tmp_path / "eviction_audit.db"
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.executescript(_LEGACY_AUDIT_DDL)
        connection.execute(
            "INSERT INTO eviction_audit VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy-1", "ep-old", "agent-a", 1_700_000_100.0, "capacity", "_evict", "batch of 1, budget=2",
             "legacy-hash", 1_700_000_000.0),
        )
        connection.commit()
    assert _column_names(path) == list(_AUDIT_COLUMNS[:9])  # premise: a nine-column file from the old code

    audit = EvictionAuditLog()
    await audit.start(str(path))
    try:
        assert _column_names(path) == list(_AUDIT_COLUMNS)
        assert _query(path, "SELECT disposition, archive_ref FROM eviction_audit WHERE id = ?", ("legacy-1",)) == [
            ("deleted", ""),
        ]
        legacy = await audit.query_by_episode("ep-old")
        assert legacy is not None
        assert (legacy.id, legacy.content_hash, legacy.disposition, legacy.archive_ref) == (
            "legacy-1", "legacy-hash", "deleted", "",
        )

        await audit.record_eviction(
            "ep-single", "agent-a", "activation_decay", "evict_by_ids",
            disposition="archived", archive_ref="episode_archive:ep-single:h1",
        )
        await audit.record_batch_eviction(
            [{"episode_id": "ep-batch", "agent_id": "agent-a", "archive_ref": "episode_archive:ep-batch:h2"}],
            reason="capacity", process="_evict", disposition="archived",
        )
        # A caller that names no disposition (the reset insert, KnowledgeStore) reads as a plain delete.
        await audit.record_batch_eviction(
            [{"episode_id": "ep-plain", "agent_id": "agent-a"}], reason="capacity", process="_evict",
        )
        expected = {
            "ep-old": ("deleted", ""),
            "ep-single": ("archived", "episode_archive:ep-single:h1"),
            "ep-batch": ("archived", "episode_archive:ep-batch:h2"),
            "ep-plain": ("deleted", ""),
        }
        assert {r["episode_id"]: (r["disposition"], r["archive_ref"]) for r in _audit_rows(tmp_path)} == expected
        # The three SELECTs hand EvictionRecord the two new columns in the right positions.
        for records in (await audit.query_by_agent("agent-a"), await audit.query_recent()):
            assert {r.episode_id: (r.disposition, r.archive_ref) for r in records} == expected

        total = len(_audit_rows(tmp_path))
        with pytest.raises(ValueError, match="eviction_disposition_invalid"):
            await audit.record_eviction("ep-x", "agent-a", "capacity", "_evict", disposition="purged")
        with pytest.raises(ValueError, match="eviction_disposition_invalid"):
            await audit.record_batch_eviction(
                [{"episode_id": "ep-x", "agent_id": "agent-a"}], reason="capacity", process="_evict",
                disposition="purged",
            )
        assert len(_audit_rows(tmp_path)) == total
    finally:
        await audit.stop()

    again = EvictionAuditLog()
    await again.start(str(path))  # a second start on the migrated file changes nothing
    try:
        assert _column_names(path) == list(_AUDIT_COLUMNS)
        assert len(_audit_rows(tmp_path)) == total
    finally:
        await again.stop()
