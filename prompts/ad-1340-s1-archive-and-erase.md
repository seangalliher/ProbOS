# AD-1340 S1 (#1568): dream pruning and capacity eviction archive the episode; erasure erases every copy

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-17

**Amended by:** the orchestrator, 2026-10-17, spelling only. The phantom-API precheck (a heuristic that runs on any touched `prompts/*.md`) reads a ChromaDB `delete` call that passes an `ids` keyword as an unknown keyword of the repository's other `delete` methods, so the code in 7d and the O1 mutant spell that call with `ids=list(ids)` (an equal copy of an id list, same keyword style, so the existing call-sequence assertions are unaffected), and the quoted source lines in Verified Against Codebase elide that call's argument. The precheck also lists five keywords this slice introduces (`disposition` on `evict_by_ids` and `record_batch_eviction`, `accessor` and `purpose` on `EpisodeArchive.record_access`); they resolve once the build adds them, and the first preflight of the built candidate confirms it.

**One line.** Dream Step 12 (both tiers) and capacity eviction move each evicted episode, as its raw ChromaDB record, into a new cold store `episode_archive.db` and commit it before removing the episode from the live indexes. Only ids whose archive row committed leave the live store. Erasure (AD-754) and qualification-test cleanup pass an explicit `EvictionDisposition.ERASE`, and erasure now removes every copy, including the archive copy, archive-only episodes, cascade matches and attachments. A flag (`memory.eviction_disposition: delete`) restores today's hard delete.

| | |
|---|---|
| Status | Build-ready (split workflow: the Copilot orchestrator builds). |
| Issue / AD | #1568 / AD-1340, slice **S1** of S1-S5 (consult session `eaf93fed`, 2026-10-17). **No new AD or BF number.** AD ceiling **AD-1341** (source: GitHub issue titles, all states; `scripts/ad_ceiling.py`, 2026-10-17); this contract allocates nothing. |
| Base | `origin/main` `b8849e34` (the consult read `f89d72a9`; the only change since is `ui/src/components/mcp/McpServersPanel.test.tsx`, so no `src/` anchor moved). |
| Depends on | Nothing. Overlaps BF-902 (#1579); see D8. |
| Live-ship effect | **Yes.** After M4 the code default is `archive`, so the standard tier (still hard-deleting on the live ship today) and the aggressive tier archive instead. `config/system.yaml` is not touched. |
| Estimated tests | planned about 34 new tests in four files; built 68 test functions in four files (A1-A15, E1-E12, R1-R29, T1-T12; A11-A15, R16-R29 and T9 came with Amendment R1, T10-T12 with Amendment R2), signature edits to five test fakes, one config-test pop and one field-count pin bump |
| Milestones | M1 store and policy · M2 eviction paths, flag, audit · M3 erasure · M4 restore, reset, declaration, wiring, **default flip** · M5 trackers. Cut point S1a/S1b: see "Builder briefs". |
| CRLF | Every existing file this contract edits is LF in the index and CRLF in the working tree (`git ls-files --eol`). Edit with anchored replacements and never rewrite a whole existing file. |

---

## Problem

- `cognitive/episodic.py:2380-2457` `evict_by_ids` records the audit row and then deletes from ChromaDB with `self._collection.delete`, passing `ids=valid_ids` (`:2426`). It also deletes the FTS5 row (`:2430-2438`), the activation records (`:2441-2445`) and the participant-index rows (`:2448-2452`). The experience is gone; the audit keeps an id, an agent, a reason and a hash.
- `episodic.py:2315-2378` `_evict` does the same for capacity (`reason="capacity"`, `:2349`) on every `store()` (`:1936`).
- Dream Step 12 calls `evict_by_ids(low_activation, reason="activation_decay")` (`dreaming.py:1602-1604`) and `evict_by_ids(aggressive_pruned, reason="activation_decay_aggressive")` (`:1638-1640`).
- Erasure: `ErasureManager.forget_episode` passes the caller's `reason` (`knowledge/erasure.py:77-84`), and `routers/security.py:23` lets the HTTP caller choose that reason (`ForgetRequest.reason: str = "user_request"`, passed at `:73`). The cascades enumerate **live** episodes only (`erasure.py:153-156`), and attachment ids come from live rows only (`:183-193`).
- `memory_probes.py:81` cleans up qualification probes with `reason="qualification_test_cleanup"`.

So today forgetting is deletion. Once eviction archives, three privacy holes open unless erasure changes in the same slice: (1) an erasure whose free-text reason is not in a table would archive instead of erase; (2) erasing an archive-only id would do nothing, because `evict_by_ids` returns 0 when no live row exists (`episodic.py:2392-2394`); (3) cascades and attachment resolution would miss archived episodes.

## Solution overview

1. **Contract in the foundation tier.** `EvictionDisposition(StrEnum)` with `ARCHIVE` and `ERASE` goes in `probos/types.py`. The knowledge layer may import only `substrate` and the foundation modules (`tests/test_layer_boundaries.py:35-37,49`), and `erasure.py` must name it.
2. **New store** `src/probos/cognitive/episode_archive.py`: `EpisodeArchive` (SQLite through `ConnectionFactory`, `PRAGMA secure_delete=ON` verified on open, the payload is canonical JSON of the raw `{id, document, metadata}` compressed with zlib, and an `archive_access` table). The module also holds the **one** policy function `resolve_disposition(reason, explicit, mode)`.
3. **One removal sequence** in `EpisodicMemory`, `_remove_from_live`, used by `_evict`, `evict_by_ids` and erasure: in archive mode it archives and commits, then writes the audit, then deletes from ChromaDB **only the ids whose archive row committed**, then cleans the sidecars. In delete mode it runs the same sequence without the archive.
4. **ERASE path** `_erase_ids`: deletes the live rows, the sidecars, the archive rows and the archive access rows. It covers archive-only ids and raises if any copy could not be cleared.
5. **Audit** gains `disposition` (`archived` / `erased` / `deleted`) and `archive_ref`, added with `ALTER TABLE ADD COLUMN` and defaults.
6. **Erasure** passes `disposition=EvictionDisposition.ERASE`, and its cascades and attachment lookup also read the archive.
7. **Restore** `restore_from_archive(id)` is internal and never goes through `store()`: it refuses a live id, re-adds the raw record, re-inserts the FTS and participant rows, and records one activation access.
8. **Reset** Tier 2 deletes `episode_archive.db`. A **store declaration** is added. The **flag** `MemoryConfig.eviction_disposition` is wired at both `EpisodicMemory(...)` constructions in `__main__.py`.

Ordinary recall never reads the archive. Lookup surfaces (by agent and time, by cue, the archive text index) are S2; doctor and SIF visibility are S3; the consolidation gate is S4; expiry is S5.

---

## Decisions

### D1. Where the archive lives, and who owns its lifecycle
- `data_dir/episode_archive.db`, at the data-directory root, beside `episode_fts.db`: `Path(EpisodicMemory.db_path).parent / "episode_archive.db"`, the same rule as the FTS sidecar at `episodic.py:1441,1498`. It is **not** under `archives/`, because `_ALWAYS_PRESERVED = ["archives/"]` (`__main__.py:2636`) survives every reset, and the name would also collide with the Ship's Archive (`archive.db`).
- **Lifecycle owner: `EpisodicMemory.start()` / `stop()`**, exactly as for the FTS sidecar (`:1495-1507`, `:1511-1517`). This differs from the consult's suggestion to wire it in `startup/cognitive_services.py`. With an owned sidecar, every existing test that starts a real `EpisodicMemory` on `tmp_path` gets a working archive without new wiring. That covers the capacity tests and `test_participant_index.py:281-295`. Otherwise every archive-mode eviction in those tests would keep the episode live.
- The connection comes from `archive_connection_factory` (constructor injection; default `probos.storage.sqlite_factory.default_factory`), never from `aiosqlite.connect()`.
- **Rejected:** a table in `eviction_audit.db`, because the eviction audit is declared to contain no `DELETE FROM` (`storage_declarations.py:59-66`) and erasure needs `DELETE`. Also rejected: a second ChromaDB collection (it re-embeds, lives in a file Tier 2 deletes, and never reclaims space) and JSONL files (not atomic).

### D2. Payload and byte-equal restore
- The record is exactly what `collection.get(ids=..., include=["documents", "metadatas"])` returns per id: `{id, document, metadata}`. It is serialised with `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` and compressed with `zlib.compress(..., 6)`. No embedding is stored. Restore calls `collection.add` with the same document and metadata, so the collection's embedding function re-embeds the document, as `store()` does at `:1883-1887`. Metadata, including `content_hash` and `tcm_vector_json`, is unchanged, so AD-541e hash verification still passes.
- Primary key `(episode_id, content_hash)`; one row per key. Re-archiving a byte-identical record changes nothing (`reason` and `archived_at` are kept), so a retried archive is idempotent. **(R1)** Re-archiving the same key with a different payload (metadata changed after a restore; the content hash excludes mutable metadata) replaces the payload, `reason`, `archived_at`, agent and timestamp, and `secure_delete` overwrites the old bytes. `archive_ref` names the slot, not a payload revision, so the audit's `archive_ref` and `content_hash` are unchanged and resolve to the newest payload. On read, the decoded `id` and `metadata.content_hash` must equal the key columns, or the read raises `EpisodeArchiveIntegrityError`.
- **A restored episode keeps its archive row.** Removing it would be a delete path outside erasure. Re-evicting the episode stores its current payload (R1), and erasure removes both copies.
- `archive_ref` is `episode_archive:<episode_id>:<content_hash>`.

### D3. Ordering and failure windows (archive first)
Archive mode, per batch: (1) read the full records; (2) write the archive rows in one transaction, commit, then read back which ids hold **exactly the payload just written (key and bytes)** (R1); (3) write the audit rows (best-effort, as today); (4) `collection.delete` **only** the ids from (2); (5) clean FTS5, activation and the participant index (best-effort, as today).

| Window | Effect |
|---|---|
| Archive write or commit raises | Rolled back. Nothing is deleted, the batch stays live, and a WARNING is logged |
| Archive unavailable (failed to open, or never started) | Nothing is deleted. A WARNING is logged at most once per 300 s. Capacity can exceed `max_episodes`: degradation by growth, never by loss |
| Crash after (2), before (4) | The episode is both live and archived: a duplicate, never a loss. The retry writes nothing new for an identical record, then deletes |
| Audit write fails | The archive row is self-describing (reason, `archived_at`, `content_hash`, agent, episode timestamp) |
| Record cannot be encoded | That record is skipped with a WARNING and stays live; the rest of the batch proceeds |
| Reverse order (delete first) | **Rejected**: this is the loss window |

### D4. One policy owner; the issue's Decision 4 amended
**Amendment of #1568 Decision 4, in this contract's words:** *Erasure is never derived from a reason.* `routers/security.py:23,73` passes a free-text reason chosen by the caller, so under the issue's rule ("decided by the caller's reason; unknown reason → archive") a Captain's erasure with a custom reason would be archived instead of erased. That is a privacy defect. Therefore:
- ERASE comes **only** from an explicit `disposition=EvictionDisposition.ERASE`, which only `ErasureManager.forget_episode` and `memory_probes._cleanup_test_episodes` pass.
- **No reason string produces ERASE**, `"qualification_test_cleanup"` and `"user_request"` included.
- A reason outside the closed set `{activation_decay, activation_decay_aggressive, capacity, activation_pruning}` logs a WARNING and **archives**.
- A non-enum `disposition` (for example the plain string `"erase"`) raises `TypeError("eviction_disposition_invalid")`.

`resolve_disposition(reason, explicit, mode)` in `episode_archive.py` is the only place this rule exists. The Step 12 call sites in `dreaming.py` are **not edited**. The reason literals stay where the `?raw` tests require them (`test_ad593_pruning_acceleration.py:134-198,282-283`), and `test_ad567d_dream_provenance.py:486` (`assert_called_once_with(["ep-1"], reason="activation_decay")`) stays green.

### D5. `delete` mode (the flag)
`MemoryConfig.eviction_disposition: Literal["archive", "delete"] = "archive"`, placed beside `eviction_audit_enabled` (`config.py:856`). Literal validation happens at parse time.

`delete` restores exactly this behaviour:
- the **same live-store call sequence** as today: `_evict` calls `count`, `get(include=["metadatas"])`, `delete`; `evict_by_ids` calls `get(ids=..., include=["metadatas"])`, `delete`;
- **no archive write**, and the archive is **not opened for eviction**: `start()` opens it only if an `episode_archive.db` file left over from earlier archive mode already exists, and never creates one;
- **erasure still clears** that left-over archive file;
- in the audit, the **nine legacy columns** are written by the same expressions as today (`id` a fresh uuid4 hex, `timestamp` the wall clock, the other seven equal today's values), and the **two new columns** read `deleted` and an empty `archive_ref`.

Do not describe `delete` mode as making "the schema byte-identical": the table gains two columns in every mode.

### D6. ERASE semantics
- ERASE removes: the ChromaDB row, the `episode_fts` row, the activation records, the participant-index rows, every `episode_archive` row for the id (whatever its content hash), and its `archive_access` rows. The eviction-audit row (a hash, not content) is the only trace left. This holds whether the episode was live, archived or both.
- ERASE works for **archive-only** ids. It writes one audit row each, with `disposition = 'erased'`, and they count towards the return value, so `ErasureResult.deleted_episode_ids` names them.
- ERASE **propagates** failures, unlike archive and delete eviction. It raises `EpisodeArchiveUnavailable` if the archive failed to open (it may hold copies), after deleting the live rows. It raises `EpisodeErasureIncomplete` if a sidecar cleanup failed. An erasure that silently leaves a copy behind is the worse failure (BF-868). In `delete` mode with no archive file, ERASE skips the archive. **(M3r)** Every phase is attempted before the first failure is raised; the sidecar sweep is keyed on the requested ids; `forget_episode` unlinks attachments before erasing the episode; the cascades attempt every match and then raise one `ErasureCascadeIncomplete` (see "Amendment M3r"). **(R1)** A sidecar with no open handle is cleared through its declared file; only a missing file means there is nothing to clear. ERASE on a stopped memory raises. Every version of the id (live and archived) is matched, and every version's attachments are unlinked before the erase (see "Amendment R1"). **(R2)** An erase that overlaps a restore of the same id either erases the restored copy or makes the restore fail with `episode_archive_not_found` (see "Amendment R2").
- `secure_delete` overwrites erased rows in the archive. Backup snapshots taken earlier keep erased content until they age out, as ChromaDB's do today. That is out of scope.

### D7. Reset Tier 2 deletes the archive (decided in envelope; the Captain may overrule)
`episode_archive.db` joins `RESET_TIERS[2]["files"]` (`__main__.py:2614-2621`). Tier 2 is "New ship, new crew", and its recorded audit row says "total episodic memory wipe" (`:2946`). Keeping the archive would let a new crew be restored with an old crew's memories, against the Captain's nature, culture and nurture decision (2026-10-16: episodes are nurture and reset). **Rejected alternative, recorded:** keep the archive across Tier 2 as provenance for AD-1341. If the Captain prefers it, it is a one-line removal from `files`, plus a new home outside the data-directory root.

### D8. BF-902 (#1579) overlaps and is not part of S1
`episode_fts.db` (and the sibling sidecars) survive every reset tier, and stale FTS rows can outlive eviction. **BF-902 owns that.** S1 adds only `"episode_archive.db"` to Tier 2's `files` list and must not add `episode_fts.db` or any other sidecar. The two changes touch the same `RESET_TIERS` table, and whichever merges first does not matter to the other: each adds its own list entries, and a textual conflict, if one arises, is a list merge. S1's erasure tests still prove that an erased episode's FTS row is gone, through the existing per-id `DELETE FROM episode_fts` cleanup.

### D9. Milestone staging of the default
M2 adds the flag and the constructor parameter with default **`"delete"`**; M4 flips both to **`"archive"`**. Every intermediate commit is therefore safe to run, because before M4 there is no reset deletion, no declaration and no restore, and live behaviour stays as it is today. It is also why S1b (if the cut is taken) is "M4 plus the default flip". Archive-mode tests in M2 and M3 pass `eviction_disposition="archive"` explicitly.

---

## Section 0: Event types

None. S1 adds no `EventType` value.

---

## Section 1 (M1): `EvictionDisposition` in `src/probos/types.py`

Insert after the end of `class Priority(StrEnum)`, which is NOT its last member: `Priority.classify` follows `LOW = "low"` and ends with `return Priority.NORMAL` (`:176` on the base; the drafted "ends at `:150`" was wrong, found by the M1 Builder). Insert between that line and `@dataclass class GossipEntry`, with two blank lines before and after:

```python
class EvictionDisposition(StrEnum):
    """AD-1340: what an episode eviction does with the episode.

    ARCHIVE moves it to the episode archive (or, with
    ``memory.eviction_disposition: delete``, deletes it as before AD-1340).
    ERASE removes every copy, the archive included. ERASE is never derived
    from a reason string: only the AD-754 erasure manager and the
    qualification-test cleanup pass it. Defined in the foundation tier
    because ``knowledge/erasure.py`` must name it and the knowledge layer may
    not import ``probos.cognitive``.
    """

    ARCHIVE = "archive"
    ERASE = "erase"
```

`from enum import Enum, StrEnum` already exists at `types.py:9`.

## Section 2 (M1): audit vocabulary constants in `src/probos/cognitive/eviction_audit.py`

Insert after `logger = logging.getLogger(__name__)` (`:19`):

```python

# AD-1340: the eviction audit owns its ``disposition`` vocabulary.
DISPOSITION_ARCHIVED = "archived"
DISPOSITION_ERASED = "erased"
DISPOSITION_DELETED = "deleted"
DISPOSITIONS: frozenset[str] = frozenset(
    {DISPOSITION_ARCHIVED, DISPOSITION_ERASED, DISPOSITION_DELETED}
)
```

(The schema and record changes to this file are M2, Section 5.)

## Section 3 (M1): `src/probos/cognitive/episode_archive.py` (new, full file)

```python
"""AD-1340 S1: the episode archive -- cold, text-only storage for evicted episodes.

Dream pruning (Step 12) and capacity eviction move an episode here, in full,
before removing it from the live retrieval indexes (ChromaDB, FTS5, the
participant index, the activation log). Ordinary recall never reads this
store. Erasure (AD-754) is the only path that removes an archived episode.

The payload is the raw ChromaDB record ``{id, document, metadata}`` exactly as
``collection.get(include=["documents", "metadatas"])`` returned it, serialised
as canonical JSON and zlib-compressed, so a restore is byte-equal. Every
connection sets ``PRAGMA secure_delete=ON`` and verifies it, so an erased
row's bytes are overwritten rather than left in free pages.
"""

from __future__ import annotations

import json
import logging
import time
import zlib
from collections.abc import AsyncIterator, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from probos.cognitive.eviction_audit import (
    DISPOSITION_ARCHIVED,
    DISPOSITION_DELETED,
    DISPOSITION_ERASED,
)
from probos.types import EvictionDisposition

__all__ = [
    "ARCHIVE_FILENAME",
    "ARCHIVE_REASONS",
    "EVICTION_MODES",
    "ArchiveRecord",
    "EpisodeArchive",
    "EpisodeArchiveConflict",
    "EpisodeArchiveError",
    "EpisodeArchiveIntegrityError",
    "EpisodeArchiveUnavailable",
    "EpisodeErasureIncomplete",
    "EvictionDisposition",
    "decode_payload",
    "encode_payload",
    "primary_agent_id",
    "resolve_disposition",
]

logger = logging.getLogger(__name__)

ARCHIVE_FILENAME = "episode_archive.db"
ARCHIVE_SCHEMA_VERSION = 1
PAYLOAD_FORMAT_ZLIB_JSON = 1
#: The closed set of reasons that archive without a warning.
ARCHIVE_REASONS: frozenset[str] = frozenset(
    {"activation_decay", "activation_decay_aggressive", "capacity", "activation_pruning"}
)
#: ``memory.eviction_disposition`` values.
EVICTION_MODES: frozenset[str] = frozenset({"archive", "delete"})
_SQL_CHUNK = 500

AuditDisposition = Literal["archived", "erased", "deleted"]

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS episode_archive (
    episode_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    episode_timestamp REAL NOT NULL,
    reason TEXT NOT NULL,
    archived_at REAL NOT NULL,
    payload_format INTEGER NOT NULL,
    payload BLOB NOT NULL,
    PRIMARY KEY (episode_id, content_hash)
);

CREATE TABLE IF NOT EXISTS archive_access (
    id INTEGER PRIMARY KEY,
    episode_id TEXT NOT NULL,
    accessed_at REAL NOT NULL,
    accessor TEXT NOT NULL,
    purpose TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_archive_access_episode
    ON archive_access(episode_id);
"""


class EpisodeArchiveError(Exception):
    """Base class for episode-archive failures."""


class EpisodeArchiveUnavailable(EpisodeArchiveError):
    """The archive is not open (never started, failed to open, or stopped)."""


class EpisodeArchiveIntegrityError(EpisodeArchiveError):
    """A stored row does not decode to the record its key columns name."""


class EpisodeArchiveConflict(EpisodeArchiveError):
    """A restore named an id that is already live."""


class EpisodeErasureIncomplete(EpisodeArchiveError):
    """Erasure could not clear every copy of an episode."""


def resolve_disposition(
    reason: str,
    explicit: EvictionDisposition | None,
    mode: str,
) -> AuditDisposition:
    """The one owner of the eviction policy (AD-1340 Decision 4, as amended).

    ERASE comes only from an explicit ``EvictionDisposition.ERASE``; no reason
    string produces it, because the AD-754 erasure route passes a caller-chosen
    free-text reason. Any other eviction archives (``mode="archive"``) or
    deletes (``mode="delete"``). A reason outside :data:`ARCHIVE_REASONS` is
    logged and still archives: losing data is the worse failure.
    """
    if mode not in EVICTION_MODES:
        raise ValueError("eviction_disposition_mode_invalid")
    if explicit is EvictionDisposition.ERASE:
        return DISPOSITION_ERASED
    if explicit is not None and explicit is not EvictionDisposition.ARCHIVE:
        raise TypeError("eviction_disposition_invalid")
    if reason not in ARCHIVE_REASONS:
        logger.warning("AD-1340: unknown eviction reason %r; archiving, never erasing", reason)
    if mode == "delete":
        return DISPOSITION_DELETED
    return DISPOSITION_ARCHIVED


def primary_agent_id(metadata: Mapping[str, Any]) -> Any:
    """First entry of ``agent_ids_json``, else ``"unknown"`` -- the AD-541f audit rule."""
    try:
        agent_ids = json.loads(metadata.get("agent_ids_json", "[]"))
        return agent_ids[0] if agent_ids else "unknown"
    except (json.JSONDecodeError, TypeError, KeyError, IndexError):
        return "unknown"


def _episode_timestamp(metadata: Mapping[str, Any]) -> float:
    try:
        return float(metadata.get("timestamp", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _chunks(items: Sequence[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield list(items[start:start + size])


@dataclass(frozen=True)
class ArchiveRecord:
    """One raw ChromaDB record, exactly as the live store held it."""

    episode_id: str
    document: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        value = self.metadata.get("content_hash", "")
        return value if isinstance(value, str) else ""

    @property
    def archive_ref(self) -> str:
        return f"episode_archive:{self.episode_id}:{self.content_hash}"


def encode_payload(record: ArchiveRecord) -> bytes:
    """Canonical JSON of ``{id, document, metadata}``, then zlib."""
    payload_metadata = dict(record.metadata)
    canonical = json.dumps(
        {"document": record.document, "id": record.episode_id, "metadata": payload_metadata},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return zlib.compress(canonical.encode("utf-8"), 6)


def decode_payload(
    episode_id: str,
    content_hash: str,
    payload_format: int,
    payload: bytes,
) -> ArchiveRecord:
    """Decode one stored payload and prove it is the record its key names."""
    if payload_format != PAYLOAD_FORMAT_ZLIB_JSON:
        raise EpisodeArchiveIntegrityError("episode_archive_payload_format_unknown")
    try:
        data = json.loads(zlib.decompress(payload).decode("utf-8"))
    except (zlib.error, UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise EpisodeArchiveIntegrityError("episode_archive_payload_undecodable") from exc
    if (
        not isinstance(data, dict)
        or set(data) != {"document", "id", "metadata"}
        or not isinstance(data["document"], str)
        or not isinstance(data["metadata"], dict)
    ):
        raise EpisodeArchiveIntegrityError("episode_archive_payload_shape")
    record = ArchiveRecord(
        episode_id=data["id"], document=data["document"], metadata=data["metadata"],
    )
    if record.episode_id != episode_id or record.content_hash != content_hash:
        raise EpisodeArchiveIntegrityError("episode_archive_payload_key_mismatch")
    return record


async def _rollback_quietly(db: Any) -> None:
    try:
        await db.execute("ROLLBACK")
    except Exception:
        logger.debug("AD-1340: archive rollback failed (no open transaction?)", exc_info=True)


async def _close_quietly(db: Any) -> None:
    try:
        await db.close()
    except Exception:
        logger.debug("AD-1340: archive close failed", exc_info=True)


class EpisodeArchive:
    """Cold store for evicted episodes. Owned and started by ``EpisodicMemory``.

    Not a recall surface: nothing on the default recall paths calls it.
    S2 adds the recorded lookups (by agent and time, by cue).
    """

    def __init__(self, db_path: str, connection_factory: Any = None) -> None:
        if not isinstance(db_path, str) or not db_path.strip():
            raise ValueError("episode_archive_path_invalid")
        if connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            connection_factory = default_factory
        self._db_path = db_path
        self._factory = connection_factory
        self._db: Any = None

    @property
    def is_open(self) -> bool:
        return self._db is not None

    async def start(self) -> None:
        """Open, enable and verify ``secure_delete``, then create the schema."""
        if self._db is not None:
            return
        db = await self._factory.connect(self._db_path)
        try:
            await db.execute("PRAGMA secure_delete=ON")
            cursor = await db.execute("PRAGMA secure_delete")
            row = await cursor.fetchone()
            if not row or int(row[0]) != 1:
                raise EpisodeArchiveUnavailable("episode_archive_secure_delete_unavailable")
            cursor = await db.execute("PRAGMA user_version")
            row = await cursor.fetchone()
            version = int(row[0]) if row else 0
            if version not in (0, ARCHIVE_SCHEMA_VERSION):
                raise EpisodeArchiveUnavailable("episode_archive_schema_unknown")
            await db.executescript(_SCHEMA)
            await db.execute(f"PRAGMA user_version = {ARCHIVE_SCHEMA_VERSION}")
            await db.commit()
        except BaseException:  # close on every exit, cancellation included, then re-raise
            await _close_quietly(db)
            raise
        self._db = db

    async def stop(self) -> None:
        db, self._db = self._db, None
        if db is not None:
            await _close_quietly(db)

    def _require_open(self) -> Any:
        if self._db is None:
            raise EpisodeArchiveUnavailable("episode_archive_not_open")
        return self._db

    async def archive(self, records: Iterable[ArchiveRecord], *, reason: str) -> frozenset[str]:
        """Insert each record once per ``(episode_id, content_hash)`` and commit.

        Returns the ids whose row is present after the commit (read back): the
        only ids the caller may delete from the live store. A record that cannot
        be encoded is skipped with a warning and stays live. A failed write is
        rolled back and raises.
        """
        db = self._require_open()
        now = time.time()
        rows: list[tuple[Any, ...]] = []
        for record in records:
            try:
                payload = encode_payload(record)
            except (TypeError, ValueError):
                logger.warning(
                    "AD-1340: episode %s could not be encoded for the archive; it stays live",
                    record.episode_id, exc_info=True,
                )
                continue
            rows.append((
                record.episode_id, record.content_hash, primary_agent_id(record.metadata),
                _episode_timestamp(record.metadata), reason, now, PAYLOAD_FORMAT_ZLIB_JSON, payload,
            ))
        if not rows:
            return frozenset()
        try:
            await db.executemany(
                "INSERT INTO episode_archive (episode_id, content_hash, agent_id, episode_timestamp, "
                "reason, archived_at, payload_format, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(episode_id, content_hash) DO NOTHING",
                rows,
            )
            await db.commit()  # the archive commit: nothing leaves the live store before this returns
        except Exception:
            await _rollback_quietly(db)
            raise
        return await self._present([(row[0], row[1]) for row in rows])

    async def _present(self, pairs: list[tuple[str, str]]) -> frozenset[str]:
        db = self._require_open()
        wanted = set(pairs)
        found: set[str] = set()
        ids = list(dict.fromkeys(pair[0] for pair in pairs))
        for chunk in _chunks(ids, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            cursor = await db.execute(
                f"SELECT episode_id, content_hash FROM episode_archive WHERE episode_id IN ({marks})",
                chunk,
            )
            for episode_id, content_hash in await cursor.fetchall():
                if (episode_id, content_hash) in wanted:
                    found.add(episode_id)
        return frozenset(found)

    async def get_records(self, episode_ids: Sequence[str]) -> list[ArchiveRecord]:
        """Service read (restore, erasure): the latest archived record per id, in input order."""
        db = self._require_open()
        wanted = list(dict.fromkeys(eid for eid in episode_ids if eid))
        best: dict[str, tuple[float, ArchiveRecord]] = {}
        for chunk in _chunks(wanted, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            cursor = await db.execute(
                "SELECT episode_id, content_hash, archived_at, payload_format, payload "
                f"FROM episode_archive WHERE episode_id IN ({marks})",
                chunk,
            )
            for episode_id, content_hash, archived_at, payload_format, payload in await cursor.fetchall():
                record = decode_payload(episode_id, content_hash, payload_format, payload)
                current = best.get(episode_id)
                if current is None or archived_at > current[0]:
                    best[episode_id] = (archived_at, record)
        return [best[eid][1] for eid in wanted if eid in best]

    async def archived_keys(self, episode_ids: Sequence[str]) -> list[tuple[str, str, Any, float]]:
        """``(episode_id, content_hash, agent_id, episode_timestamp)`` per row, no decode.

        Erasure audits from these columns, so a corrupt payload never blocks an erase.
        """
        db = self._require_open()
        wanted = list(dict.fromkeys(eid for eid in episode_ids if eid))
        keys: list[tuple[str, str, Any, float]] = []
        for chunk in _chunks(wanted, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            cursor = await db.execute(
                "SELECT episode_id, content_hash, agent_id, episode_timestamp "
                f"FROM episode_archive WHERE episode_id IN ({marks})",
                chunk,
            )
            keys.extend(tuple(row) for row in await cursor.fetchall())
        return keys

    async def iter_records(self, *, page_size: int = 500) -> AsyncIterator[ArchiveRecord]:
        """Every archived row, paged by key (erasure cascades)."""
        if page_size < 1:
            raise ValueError("episode_archive_page_size_invalid")
        last = ("", "")
        while True:
            db = self._require_open()
            cursor = await db.execute(
                "SELECT episode_id, content_hash, payload_format, payload FROM episode_archive "
                "WHERE (episode_id, content_hash) > (?, ?) ORDER BY episode_id, content_hash LIMIT ?",
                (last[0], last[1], page_size),
            )
            rows = await cursor.fetchall()
            if not rows:
                return
            for episode_id, content_hash, payload_format, payload in rows:
                yield decode_payload(episode_id, content_hash, payload_format, payload)
            last = (rows[-1][0], rows[-1][1])

    async def record_access(self, episode_id: str, *, accessor: str, purpose: str) -> None:
        db = self._require_open()
        try:
            await db.execute(
                "INSERT INTO archive_access (episode_id, accessed_at, accessor, purpose) "
                "VALUES (?, ?, ?, ?)",
                (episode_id, time.time(), accessor, purpose),
            )
            await db.commit()
        except Exception:
            await _rollback_quietly(db)
            raise

    async def erase(self, episode_ids: Sequence[str]) -> frozenset[str]:
        """Delete every archive row and access row for these ids; return the ids that had rows."""
        db = self._require_open()
        wanted = list(dict.fromkeys(eid for eid in episode_ids if eid))
        present = {key[0] for key in await self.archived_keys(wanted)}
        try:
            for chunk in _chunks(wanted, _SQL_CHUNK):
                marks = ",".join("?" * len(chunk))
                await db.execute(f"DELETE FROM episode_archive WHERE episode_id IN ({marks})", chunk)
                await db.execute(f"DELETE FROM archive_access WHERE episode_id IN ({marks})", chunk)
            await db.commit()
        except Exception:
            await _rollback_quietly(db)
            raise
        return frozenset(present)
```

## Section 4 (M1): `tests/test_ad1340_s1_archive_store.py` (new)

Real SQLite on `tmp_path / "episode_archive.db"`. Direct `sqlite3` is allowed in tests. `_record(i, **meta)` builds an `ArchiveRecord` with `content_hash = f"{i:064x}"`, an `agent_ids_json` of `'["agent-a"]'`, and a `timestamp`. `_FaultyFactory` wraps `SQLiteConnectionFactory`; it returns a proxy that delegates `execute`, `executemany`, `executescript`, `commit` and `close`, raises on `executemany` when armed, and records every SQL string it was given.

| # | Test | Asserts |
|---|---|---|
| A1 | `test_resolve_disposition_table` (parametrize) | Each known reason with `None`: `archive` → `"archived"`, `delete` → `"deleted"`, no WARNING. `EvictionDisposition.ERASE` with every reason (`"activation_decay"`, `"capacity"`, `"user_request"`, `""`, `"Captain: forget it"`) in both modes → `"erased"`. Each unknown reason (`"user_request"`, `"qualification_test_cleanup"`, `"forget this"`, `""`) with `None` → `"archived"` in `archive` and `"deleted"` in `delete`, never `"erased"`, plus one WARNING whose message contains `repr(reason)`. Explicit `ARCHIVE` → same as `None`. Plain string `"erase"` → `TypeError("eviction_disposition_invalid")`. Mode `"purge"` → `ValueError("eviction_disposition_mode_invalid")` |
| A2 | `test_payload_round_trip_and_integrity` | Metadata with `str`, `int`, `float` (`0.1`, `1e-300`), `bool`, `""` and a unicode document: `decode_payload(id, hash, 1, encode_payload(r)) == r`, the decoded metadata dict equals the original key for key with the same types, and `encode_payload(r)` is byte-equal across two calls. Re-encoded with a different id → `EpisodeArchiveIntegrityError("episode_archive_payload_key_mismatch")`. Format 2 → `..._format_unknown`. Garbage bytes → `..._undecodable` |
| A3 | `test_start_enables_and_verifies_secure_delete` | Through `_FaultyFactory` (unarmed): the first SQL is `PRAGMA secure_delete=ON`. A factory whose connection answers `PRAGMA secure_delete` with `(0,)` → `start()` raises `EpisodeArchiveUnavailable("episode_archive_secure_delete_unavailable")`, the connection is closed, and `is_open` is False |
| A4 | `test_archive_commits_and_is_idempotent` | `archive([r1, r2], reason="activation_decay")` returns `{r1.id, r2.id}`. **Immediately**, a separate `sqlite3.connect(path)` counts 2 rows, which proves the commit. Archiving `r1` again returns `{r1.id}`, and the count is still 2. The columns `agent_id = "agent-a"`, `reason`, `content_hash` and `payload_format = 1` hold the expected values |
| A5 | `test_failed_write_commits_nothing` | Armed `_FaultyFactory`: `archive` raises, and a second connection counts 0 rows. Disarmed, the same call returns the id |
| A6 | `test_erase_overwrites_the_bytes` | The document is `secrets.token_hex(2048)` (incompressible). `blob = encode_payload(r)`. Archive it, then `record_access`, then `stop()`. **Premise:** `blob in path.read_bytes()`. Then `start()`, `erase([r.id])` → `{r.id}`, `stop()`. `blob not in path.read_bytes()`, and both tables count 0 rows for the id. `erase` of an absent id → `frozenset()` |
| A7 | `test_unknown_schema_version_is_refused_unchanged` | Pre-create the file with `PRAGMA user_version = 2`; record its sha256. `start()` raises `EpisodeArchiveUnavailable("episode_archive_schema_unknown")`, and the sha256 is unchanged |
| A8 | `test_reads` | `get_records` returns the latest `archived_at` per id, in input order, and skips absent ids. `archived_keys` returns the four columns without decoding: with a corrupt payload planted by raw `sqlite3`, `archived_keys` still returns it, while `get_records` raises `EpisodeArchiveIntegrityError`. `iter_records(page_size=3)` over 7 records yields each exactly once, in key order. `page_size=0` → `ValueError` |
| A9 | `test_unstarted_or_stopped_raises_unavailable` | Before `start()` and after `stop()`, every public method raises `EpisodeArchiveUnavailable("episode_archive_not_open")`. `start()` is idempotent. `EpisodeArchive("")` → `ValueError("episode_archive_path_invalid")` |
| A10 | `test_eviction_disposition_lives_in_the_foundation_tier` | `probos.cognitive.episode_archive.EvictionDisposition is probos.types.EvictionDisposition`. `DISPOSITIONS == {"archived", "erased", "deleted"}` |

---

## Section 5 (M2): eviction audit columns (`src/probos/cognitive/eviction_audit.py`)

1. Below `_SCHEMA` (`:23-44`), add:
```python

# AD-1340: two columns added to existing and new files alike (one path). The
# nine legacy columns are untouched; a row written by code that does not name
# the new columns (the reset insert at __main__.py:2939-2947, KnowledgeStore)
# reads disposition='deleted', archive_ref=''.
_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("disposition", "ALTER TABLE eviction_audit ADD COLUMN disposition TEXT NOT NULL DEFAULT 'deleted'"),
    ("archive_ref", "ALTER TABLE eviction_audit ADD COLUMN archive_ref TEXT NOT NULL DEFAULT ''"),
)
```
2. `EvictionRecord` (`:49-61`): append two defaulted fields after `episode_timestamp: float = 0.0`:
```python
    disposition: str = DISPOSITION_DELETED
    archive_ref: str = ""
```
3. `start()` (`:81-87`): between `await self._db.executescript(_SCHEMA)` and `await self._db.commit()`, insert `await self._migrate_columns()`, and add the method:
```python
    async def _migrate_columns(self) -> None:
        cursor = await self._db.execute("PRAGMA table_info(eviction_audit)")
        present = {row[1] for row in await cursor.fetchall()}
        for name, ddl in _ADDED_COLUMNS:
            if name not in present:
                await self._db.execute(ddl)
```
4. `record_eviction` (`:112-147`): add keyword-only `disposition: str = DISPOSITION_DELETED, archive_ref: str = ""`. Before the `try`, add `if disposition not in DISPOSITIONS: raise ValueError("eviction_disposition_invalid")`. The INSERT names 11 columns, `... episode_timestamp, disposition, archive_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`, and appends `disposition, archive_ref`.
5. `record_batch_eviction` (`:149-192`): add keyword-only `disposition: str = DISPOSITION_DELETED`, with the same validation before the `try`. Each row appends `disposition, r.get("archive_ref", "")`, and the INSERT names the same 11 columns.
6. The three SELECTs (`:201-203`, `:217-219`, `:232-234`) add `, disposition, archive_ref` after `episode_timestamp`, so `EvictionRecord(*r)` still matches positionally.

`knowledge/store.py:234-239` calls `record_batch_eviction` without `disposition` and keeps working. Its rows read `deleted`, which is accurate: it unlinks files.

## Section 6 (M2): the flag

1. `src/probos/config.py`: after `eviction_audit_enabled: bool = True  # AD-541f: Append-only eviction audit trail` (`:856`), insert:
```python
    # AD-1340: what dream pruning and capacity eviction do with an evicted
    # episode. "archive" moves it to episode_archive.db, out of recall;
    # "delete" restores the pre-AD-1340 hard delete. Erasure (AD-754) always
    # erases every copy, whatever this says.
    eviction_disposition: Literal["archive", "delete"] = "delete"
```
(`Literal` is already imported at `:9`. **M4 changes the default to `"archive"`.**)
2. `tests/test_ad1152_agentic_correlation.py`: after `assert config["memory"].pop("shutdown_dispatch_grace_s") == 2.0` (`:277`), insert:
```python
    # AD-1340's eviction-disposition flag was added after this capture too. The
    # default archives (data-preserving); this agentic-loop observation never evicts.
    assert config["memory"].pop("eviction_disposition") == "delete"
```
(M4 changes the literal to `"archive"`.)
3. Regenerate the derived config artefacts, and stage them with M2: `d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline` (`docs/development/config-facade-baseline.yaml`, `memory` block near `:2369`) and `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py` (`docs/development/config-reference.md`, near `:184`). M4 regenerates both after the flip.

## Section 7 (M2): `EpisodicMemory` (`src/probos/cognitive/episodic.py`)

### 7a. Imports
Add `EvictionDisposition` to the `from probos.types import (` block at `:27`, and add after `:26`:
```python
from probos.cognitive.episode_archive import (
    ARCHIVE_FILENAME,
    EVICTION_MODES,
    ArchiveRecord,
    EpisodeArchive,
    EpisodeArchiveUnavailable,
    EpisodeErasureIncomplete,
    primary_agent_id,
    resolve_disposition,
)
from probos.cognitive.eviction_audit import (
    DISPOSITION_ARCHIVED,
    DISPOSITION_ERASED,
)
```
(M4 adds `EpisodeArchiveConflict` to this import, with `restore_from_archive`.)
Add a module constant near the other module constants: `_ARCHIVE_WARN_INTERVAL_S = 300.0`. Add a module function (beside the other module helpers, before `class EpisodicMemory`):
```python
def _metadata_by_id(ids: list[str], metadatas: Any) -> dict[str, dict]:
    metas = list(metadatas or [])
    return {eid: (dict(metas[i] or {}) if i < len(metas) else {}) for i, eid in enumerate(ids)}
```

### 7b. Constructor (`:1188-1210`, body after `:1245`)
Add two parameters after `self_contradiction_recall_enabled: bool = True,`:
```python
        eviction_disposition: str = "delete",  # AD-1340 (M4 flips the default to "archive")
        archive_connection_factory: Any = None,  # AD-1340: ConnectionFactory for episode_archive.db
```
In the body, after `self._eviction_audit = eviction_audit` (`:1245`):
```python
        # AD-1340: archive-or-delete for dream and capacity eviction; erasure
        # always erases. The archive is an owned sidecar, opened in start().
        if eviction_disposition not in EVICTION_MODES:
            raise ValueError("eviction_disposition_invalid")
        self._eviction_disposition_mode = eviction_disposition
        self._archive_connection_factory = archive_connection_factory
        self._episode_archive: EpisodeArchive | None = None
        self._archive_state = "absent"  # "absent" | "open" | "failed"
        self._archive_warned_at = float("-inf")
```
Add two read-only properties beside `set_participant_index` (`:1389`):
```python
    @property
    def eviction_disposition_mode(self) -> str:
        """AD-1340: ``"archive"`` or ``"delete"``."""
        return self._eviction_disposition_mode

    @property
    def archive_available(self) -> bool:
        """AD-1340: True when the episode archive is open."""
        return self._archive_state == "open" and self._episode_archive is not None
```

### 7c. `start()` / `stop()`
In `start()`, after the FTS block (it ends `            self._fts_db = None` at `:1507`, before `    async def stop`), insert:
```python

        # AD-1340: episode archive (cold, never read by recall)
        await self._start_episode_archive(db_dir)
```
In `stop()`, after the participant-index block (it ends `            self._participant_index = None` at `:1524`), insert:
```python
        # AD-1340: close the episode archive
        if self._episode_archive is not None:
            try:
                await self._episode_archive.stop()
            except Exception:
                logger.debug("AD-1340: episode archive close failed", exc_info=True)
            self._episode_archive = None
        self._archive_state = "absent"
```
New methods (place them immediately before `async def _evict`):
```python
    async def _start_episode_archive(self, db_dir: Path) -> None:
        """AD-1340: open the archive. Delete mode never creates the file.

        In delete mode the archive is opened only if a file from earlier
        archive mode exists, so that erasure can still clear it; eviction
        never writes to it in that mode.
        """
        path = db_dir / ARCHIVE_FILENAME
        if self._eviction_disposition_mode == "delete" and not path.exists():
            self._archive_state = "absent"
            return
        archive = EpisodeArchive(str(path), connection_factory=self._archive_connection_factory)
        try:
            await archive.start()
        except Exception:
            logger.warning(
                "AD-1340: episode archive failed to open at %s; archive-mode eviction keeps "
                "episodes live and erasure refuses until it opens",
                path, exc_info=True,
            )
            self._archive_state = "failed"
            return
        self._episode_archive = archive
        self._archive_state = "open"

    def _archive_or_none(self) -> EpisodeArchive | None:
        """The open archive; None if there is none to read; raise if it failed to open."""
        if self._archive_state == "open" and self._episode_archive is not None:
            return self._episode_archive
        if self._archive_state == "failed":
            raise EpisodeArchiveUnavailable("episode_archive_unavailable_for_erase")
        return None

    def _warn_archive_unavailable(self, count: int) -> None:
        now = time.monotonic()
        if now - self._archive_warned_at < _ARCHIVE_WARN_INTERVAL_S:
            return
        self._archive_warned_at = now
        logger.warning(
            "AD-1340: episode archive unavailable; %d episode(s) kept live instead of archived "
            "(the store may exceed max_episodes until the archive opens)",
            count,
        )

    async def _archive_records(self, ids: list[str], reason: str) -> dict[str, str]:
        """Archive these live ids; return ``{id: archive_ref}`` for the committed ones."""
        archive = self._episode_archive
        if self._archive_state != "open" or archive is None:
            self._warn_archive_unavailable(len(ids))
            return {}
        try:
            result = self._collection.get(ids=list(ids), include=["documents", "metadatas"])
            got_ids = list((result or {}).get("ids") or [])
            docs = list((result or {}).get("documents") or [])
            metas = _metadata_by_id(got_ids, (result or {}).get("metadatas"))
            records = [
                ArchiveRecord(
                    episode_id=eid,
                    document=(docs[i] if i < len(docs) else "") or "",
                    metadata=metas[eid],
                )
                for i, eid in enumerate(got_ids)
            ]
            committed = await archive.archive(records, reason=reason)
        except Exception:
            logger.warning(
                "AD-1340: archive write failed; %d episode(s) stay live", len(ids), exc_info=True,
            )
            return {}
        return {record.episode_id: record.archive_ref for record in records if record.episode_id in committed}

    async def _cleanup_sidecars(self, ids: list[str], *, strict: bool = False) -> None:
        """FTS5, activation and participant cleanup (AD-567b/d, AD-570b).

        Best-effort for archive/delete eviction, as before AD-1340. With
        ``strict`` (ERASE) a failure raises after every cleanup was attempted.
        """
        failures: list[str] = []
        if self._fts_db is not None:
            try:
                for eid in ids:
                    await self._fts_db.execute(
                        "DELETE FROM episode_fts WHERE episode_id = ?", (eid,)
                    )
                await self._fts_db.commit()
            except Exception:
                logger.debug("AD-567b: FTS5 eviction cleanup failed", exc_info=True)
                failures.append("episode_fts")
        if self._activation_tracker:
            try:
                await self._activation_tracker.delete_episode_accesses(ids)
            except Exception:
                logger.debug("AD-567d: Activation cleanup failed", exc_info=True)
                failures.append("activation")
        if self._participant_index:
            try:
                await self._participant_index.delete_episodes(ids)
            except Exception:
                logger.debug("AD-570b: Participant index eviction cleanup failed", exc_info=True)
                failures.append("participant_index")
        if strict and failures:
            logger.error(
                "AD-1340: erasure could not clear %s for %d episode(s)", ", ".join(failures), len(ids),
            )
            raise EpisodeErasureIncomplete("erasure_sidecar_cleanup_failed:" + ",".join(failures))

    async def _remove_from_live(
        self,
        candidate_ids: list[str],
        metadata_by_id: dict[str, dict],
        *,
        reason: str,
        process: str,
        details: str,
        outcome: str,
    ) -> list[str]:
        """AD-1340: the one removal sequence for capacity, dream and erase evictions.

        Archive mode: archive and commit, then audit, then delete from ChromaDB
        ONLY the ids whose archive row committed, then clean the sidecars.
        Delete and erase: the same sequence without the archive step.
        """
        ids = list(candidate_ids)
        archive_refs: dict[str, str] = {}
        if outcome == DISPOSITION_ARCHIVED:
            committed = await self._archive_records(ids, reason)
            ids = [eid for eid in ids if eid in committed]
            if not ids:
                return []
            archive_refs = committed
        if self._eviction_audit:
            records = []
            for eid in ids:
                meta = metadata_by_id.get(eid) or {}
                records.append({
                    "episode_id": eid,
                    "agent_id": primary_agent_id(meta),
                    "content_hash": meta.get("content_hash", ""),
                    "episode_timestamp": meta.get("timestamp", 0.0),
                    "archive_ref": archive_refs.get(eid, ""),
                })
            try:
                await self._eviction_audit.record_batch_eviction(
                    records,
                    reason=reason,
                    process=process,
                    details=details,
                    disposition=outcome,
                )
            except Exception as exc:
                logger.warning("Eviction audit failed: %s", exc)
        self._collection.delete(ids=list(ids))
        await self._cleanup_sidecars(ids, strict=(outcome == DISPOSITION_ERASED))
        return ids
```

### 7d. `_evict` (replace `:2315-2378` entirely)
```python
    async def _evict(self) -> None:
        assert self._collection
        count = self._collection.count()
        if count > self.max_episodes:
            excess = count - self.max_episodes
            # Get oldest episodes by timestamp
            result = self._collection.get(
                include=["metadatas"],
            )
            if result and result["ids"] and result["metadatas"]:
                # Sort by timestamp ascending (oldest first)
                paired = list(zip(result["ids"], result["metadatas"]))
                paired.sort(key=lambda x: x[1].get("timestamp", 0))
                to_evict = paired[:excess]
                ids_to_delete = [p[0] for p in to_evict]
                if ids_to_delete:
                    # AD-1340: archive (or delete) through the one removal sequence.
                    await self._remove_from_live(
                        ids_to_delete,
                        {eid: dict(meta or {}) for eid, meta in to_evict},
                        reason="capacity",
                        process="_evict",
                        details=f"batch of {len(ids_to_delete)}, budget={self.max_episodes}",
                        outcome=resolve_disposition("capacity", None, self._eviction_disposition_mode),
                    )
```

### 7e. `evict_by_ids` (replace `:2380-2457` entirely)
```python
    async def evict_by_ids(
        self,
        episode_ids: list[str],
        reason: str = "activation_pruning",
        *,
        disposition: EvictionDisposition | None = None,
    ) -> int:
        """AD-567d / AD-1340: evict specific episodes by id.

        Dream Step 12, erasure and test cleanup call this. The disposition is
        decided once, by :func:`resolve_disposition`: an explicit
        ``EvictionDisposition.ERASE`` erases every copy (only the AD-754
        erasure manager and qualification-test cleanup pass it); anything else
        archives (``memory.eviction_disposition: archive``) or deletes
        (``delete``). No reason string ever erases.

        Returns the count of episodes removed from the live store; for ERASE,
        removed from the live store or the archive. ERASE propagates failures.
        """
        outcome = resolve_disposition(reason, disposition, self._eviction_disposition_mode)
        if not episode_ids:
            return 0
        if outcome == DISPOSITION_ERASED:
            return await self._erase_ids(list(episode_ids), reason)
        if not self._collection:
            return 0

        evicted = 0
        try:
            result = self._collection.get(ids=episode_ids, include=["metadatas"])
            if not result or not result["ids"]:
                return 0
            valid_ids = result["ids"]
            removed = await self._remove_from_live(
                valid_ids,
                _metadata_by_id(valid_ids, result["metadatas"]),
                reason=reason,
                process="evict_by_ids",
                details=f"batch of {len(valid_ids)}, reason={reason}",
                outcome=outcome,
            )
            evicted = len(removed)
        except Exception as e:
            logger.debug("evict_by_ids failed: %s", e)

        return evicted
```

`_erase_ids` is added in M3. In M2, use a stub that raises `NotImplementedError("AD-1340 M3")`, which M3 replaces. No M2 caller passes ERASE, because erasure is edited in M3.

## Section 8 (M2): `tests/test_ad1340_s1_eviction.py` (new)

Fixture `_memory(tmp_path, mode, *, max_episodes=100)`: `EpisodicMemory(db_path=str(tmp_path / "chroma" / "episodes.db"), max_episodes=max_episodes, relevance_threshold=0.0, eviction_audit=EvictionAuditLog(), eviction_disposition=mode)`, with the audit started at `tmp_path / "eviction_audit.db"`. A real `ParticipantIndex(db_path=...)` and a real `ActivationTracker(db_path=...)` are started and wired with `set_participant_index` and `set_activation_tracker`, then `await em.start()`; everything stops in `finally`. Follow `tests/test_participant_index.py:70-80`. Episodes are real `Episode` objects with distinct `timestamp`, `agent_ids=["agent-a"]`, `anchors=AnchorFrame(participants=["worf"])` and a distinctive `user_input` word, all written through `store()`. `_raw(em, ids)` = `em._collection.get(ids=ids, include=["documents", "metadatas"])` (test-only private access, kept to these helpers). `_archive_rows(tmp_path)` counts rows through raw `sqlite3` on `tmp_path / "chroma" / "episode_archive.db"`. `_audit_rows(tmp_path)` reads all 11 columns.

| # | Test (consult Q7 number) | Asserts |
|---|---|---|
| E1 | `test_golden_recall_is_identical_under_archive_and_delete` (Q7-1) | Two memories, A (`archive`) and D (`delete`), in separate `tmp_path` subdirectories, each store the same six episodes with the same ids. Each evicts the same two ids with `evict_by_ids(ids, reason="activation_decay")`. For three queries, `[e.id for e in await X.recall(q, k=6)]` is equal for A and D, and so are `recall_for_agent("agent-a", q, k=6)`, `recent_for_agent("agent-a", k=10)`, `keyword_search(word)` and `get_by_ids(all_six)`. The evicted ids appear in none of A's results. **Premise:** A's archive holds 2 rows and D has no archive file |
| E2 | `test_dream_eviction_archives_then_deletes` | Archive mode, `evict_by_ids([id], reason="activation_decay")` → 1. `_raw` returns no id. One archive row whose decoded `metadata` equals the pre-eviction raw metadata **and** whose `content_hash` equals both that metadata's `content_hash` and the audit row's (property 6). Audit: `disposition = 'archived'`, `archive_ref = f"episode_archive:{id}:{hash}"`, `process = 'evict_by_ids'`. The FTS, activation and participant rows for the id are gone. The same for `reason="activation_decay_aggressive"` |
| E3 | `test_capacity_eviction_archives_the_oldest` | `max_episodes=2`, archive mode, store 3: the oldest is not live, has one archive row with `reason = 'capacity'`, and has an audit row with `process = '_evict'` and `disposition = 'archived'` |
| E4 | `test_unknown_reason_archives_and_warns` (Q7-6) | `evict_by_ids([id], reason="user_request")` and, separately, `reason="qualification_test_cleanup"`, both without `disposition`: each archives (archive row present, live gone, audit `'archived'`), and `caplog` holds a WARNING containing the reason's repr. **The reason alone never erases** |
| E5 | `test_invalid_disposition_raises_before_any_change` | `evict_by_ids([id], disposition="erase")` (plain string) → `TypeError`; the live row, the archive row count and the audit row count are all unchanged. `EpisodicMemory(..., eviction_disposition="purge")` → `ValueError("eviction_disposition_invalid")` |
| E6 | `test_archive_write_failure_keeps_the_episode_live` (Q7-7a) | Monkeypatch `em._episode_archive.archive` to raise `RuntimeError`: `evict_by_ids` → 0. `_raw` still returns the id with an equal document and metadata, there are no archive rows and no audit row, and a WARNING `"archive write failed"` is logged |
| E7 | `test_crash_after_archive_commit_then_retry_is_idempotent` (Q7-7b) | Wrap `em._collection` in a proxy whose `delete` raises once: the first `evict_by_ids` → 0, the id is still live, and there is exactly 1 archive row. The retry → 1, the id is not live, and there is still exactly 1 archive row. There are 2 audit rows with `'archived'` (append-only) |
| E8 | `test_unavailable_archive_deletes_nothing_and_warns_once` | Create a **directory** at `tmp_path/"chroma"/"episode_archive.db"` before `start()`. Then `archive_available is False` and a WARNING `"failed to open"` is logged. Two `evict_by_ids` calls → 0 each, both ids still live, no audit rows, and exactly one `"episode archive unavailable"` WARNING across both calls (rate limit). With `max_episodes=2`, storing 3 leaves 3 live |
| E9 | `test_delete_mode_is_todays_behaviour` (Q7-8) | `delete` mode with a recording proxy on `_collection` (it records method names and the `include` argument), installed just before each measured call. `evict_by_ids([id], reason="activation_decay")`: calls `[("get", ["metadatas"]), ("delete", None)]`. Capacity: store 3 with `max_episodes=100`, set `em.max_episodes = 2`, install the proxy, `await em._evict()`: calls `count`, `get(["metadatas"])`, `delete`. There is **no** `episode_archive.db` in the directory. Audit: the seven deterministic legacy columns equal today's expressions (`agent_id` from `agent_ids_json`, `reason`, `process`, `details == f"batch of 1, reason=activation_decay"` / `f"batch of 1, budget=2"`, `content_hash`, `episode_timestamp`, `episode_id`), `id` is 32 hex characters, `timestamp` is a float, `disposition = 'deleted'` and `archive_ref = ''` |
| E10 | `test_delete_mode_leaves_an_existing_archive_untouched_by_eviction` | Archive mode archives episode X, then `stop()`. The same directory is reopened in `delete` mode: `archive_available is True` (the file existed). Evicting Y deletes Y, and the archive still holds exactly 1 row (X). (Clearing X through ERASE is M3 test R8) |
| E11 | `test_audit_columns_migrate_an_old_file` | Create `eviction_audit.db` with the legacy 9-column DDL and one row by raw `sqlite3`. `EvictionAuditLog().start()` adds `disposition` and `archive_ref`; the old row reads `('deleted', '')`. A second `start()` is a no-op (the column count stays 11). `record_eviction(..., disposition="purged")` → `ValueError` |
| E12 | `test_step12_call_sites_are_unchanged` | Use AST, not raw text. In `dreaming.py`, the two `evict_by_ids` calls pass exactly one positional argument and the keyword `reason` only, with the constant values `"activation_decay"` and `"activation_decay_aggressive"`. The docstring states that D4 keeps the policy in `resolve_disposition` and the literals where `test_ad593_pruning_acceleration.py` reads them |

---

## Section 9 (M3): erasure

### 9a. `EpisodicMemory._erase_ids` (replace the M2 stub) and the archive reads
```python
    async def _erase_ids(self, episode_ids: list[str], reason: str) -> int:
        """AD-1340: ERASE removes every copy -- live row, sidecars, archive rows.

        Unlike archive/delete eviction this propagates: an erasure that
        silently leaves a copy behind is the worse failure (BF-868).
        """
        requested = list(dict.fromkeys(eid for eid in episode_ids if eid))
        if not requested:
            return 0
        live_ids: list[str] = []
        if self._collection:
            result = self._collection.get(ids=requested, include=["metadatas"])
            if result and result["ids"]:
                live_ids = list(result["ids"])
                await self._remove_from_live(
                    live_ids,
                    _metadata_by_id(live_ids, result["metadatas"]),
                    reason=reason,
                    process="evict_by_ids",
                    details=f"batch of {len(live_ids)}, reason={reason}",
                    outcome=DISPOSITION_ERASED,
                )
        live_set = set(live_ids)
        archive = self._archive_or_none()
        if archive is None:
            return len(live_set)
        archived_keys = await archive.archived_keys(requested)
        archive_only = [key for key in archived_keys if key[0] not in live_set]
        only_ids = list(dict.fromkeys(key[0] for key in archive_only))
        if only_ids:
            if self._eviction_audit:
                records = [
                    {"episode_id": eid, "agent_id": agent_id, "content_hash": content_hash,
                     "episode_timestamp": episode_ts, "archive_ref": ""}
                    for eid, content_hash, agent_id, episode_ts in archive_only
                ]
                try:
                    await self._eviction_audit.record_batch_eviction(
                        records,
                        reason=reason,
                        process="evict_by_ids",
                        details=f"archive-only batch of {len(only_ids)}, reason={reason}",
                        disposition=DISPOSITION_ERASED,
                    )
                except Exception as exc:
                    logger.warning("Eviction audit failed: %s", exc)
            await self._cleanup_sidecars(only_ids, strict=True)
        await archive.erase(requested)
        return len(live_set | set(only_ids))

    async def get_archived_metadata(self, episode_id: str) -> dict[str, Any] | None:
        """AD-1340: raw metadata of an archived episode (erasure's attachment lookup).

        A service read, not a recall surface. Raises if the archive failed to open.
        """
        archive = self._archive_or_none()
        if archive is None:
            return None
        records = await archive.get_records([episode_id])
        return dict(records[0].metadata) if records else None

    async def iter_archived_episodes(self, *, page_size: int = 500) -> AsyncIterator[Episode]:
        """AD-1340: every archived episode, rehydrated (erasure cascades).

        A service read, not a recall surface. Raises if the archive failed to open.
        """
        archive = self._archive_or_none()
        if archive is None:
            return
        async for record in archive.iter_records(page_size=page_size):
            try:
                yield self._metadata_to_episode(record.episode_id, record.document, dict(record.metadata))
            except Exception:
                logger.warning(
                    "AD-1340: archived episode %s could not be rehydrated; erasure cascades cannot match it",
                    record.episode_id, exc_info=True,
                )
```
(`AsyncIterator` is already imported at `episodic.py:19`.)

### 9b. `src/probos/knowledge/erasure.py`
1. Imports: add `from collections.abc import AsyncIterator` and `from probos.types import EvictionDisposition`.
2. `forget_episode` (`:81-84`): replace
```python
            deleted_episodes = int(
                await self._episodic_memory.evict_by_ids([episode_id], reason=reason)
            )
```
with
```python
            # AD-1340: erasure is explicit, never derived from the caller's
            # free-text reason (routers/security.py:23,73).
            deleted_episodes = int(
                await self._episodic_memory.evict_by_ids(
                    [episode_id], reason=reason, disposition=EvictionDisposition.ERASE,
                )
            )
```
3. `forget_resource` (`:100-103`): replace
```python
        episodes = await self._list_episodes()
        matching_ids: list[str] = []
        needle = resource_path.lower()
        for episode in episodes:
```
with
```python
        matching_ids: list[str] = []
        needle = resource_path.lower()
        async for episode in self._candidate_episodes():
```
4. `forget_agent_memory` (`:128-133`): replace
```python
        episodes = await self._list_episodes()
        matching_ids = [
            str(getattr(ep, "id", ""))
            for ep in episodes
            if agent_id in list(getattr(ep, "agent_ids", []) or [])
        ]
```
with
```python
        matching_ids = [
            str(getattr(ep, "id", ""))
            async for ep in self._candidate_episodes()
            if agent_id in list(getattr(ep, "agent_ids", []) or [])
        ]
```
5. After `_list_episodes` (`:153-156`), add:
```python
    async def _candidate_episodes(self) -> AsyncIterator[Any]:
        """Live episodes, then archived episodes not also live (AD-1340).

        Under-erasing is the worse failure (BF-868): a cascade that skipped the
        archive would leave the Captain's forgotten episode recoverable.
        """
        seen: set[str] = set()
        for episode in await self._list_episodes():
            seen.add(str(getattr(episode, "id", "")))
            yield episode
        if self._episodic_memory is None or not hasattr(self._episodic_memory, "iter_archived_episodes"):
            return
        async for episode in self._episodic_memory.iter_archived_episodes():
            if str(getattr(episode, "id", "")) not in seen:
                yield episode
```
6. `_attachment_ids_for_episode` (`:188-193`): after the `get_episode_metadata` fallback block and before `return self._extract_attachment_ids(episode_payload)`, insert:
```python
        # AD-1340: an archived (not live) episode's attachments come from the
        # archived raw metadata -- the same flat shape _normalize_payload decodes.
        if not episode_payload and hasattr(self._episodic_memory, "get_archived_metadata"):
            archived_meta = await self._episodic_memory.get_archived_metadata(episode_id)
            if isinstance(archived_meta, dict):
                episode_payload = archived_meta
```
Add one sentence to that method's docstring: "AD-1340: when the episode is not live, the archived raw metadata is the last fallback."

The `hasattr` guards follow the module's existing duck-typing (`:81`, `:154`, `:184`, `:188`), so the existing test fakes, which have no archive, keep working. The real `EpisodicMemory` always has these methods, and M3 tests R1-R4 pin that against a real one.

### 9c. `src/probos/cognitive/memory_probes.py`
Add `from probos.types import EvictionDisposition` to the imports, and replace `:81`:
```python
        await episodic_memory.evict_by_ids(episode_ids, reason="qualification_test_cleanup")
```
with
```python
        await episodic_memory.evict_by_ids(
            episode_ids, reason="qualification_test_cleanup", disposition=EvictionDisposition.ERASE,
        )
```

### 9d. Test fakes must accept the keyword (signature edits only)
Add `*, disposition: object = None` after the `reason` parameter in each:
- `tests/test_erasure_manager.py:33`
- `tests/test_bf868_erasure_declared_fields.py:66` and `:87`
- `tests/test_bf869_fused_frame_refs.py:50`
- `tests/test_ad582_memory_probes.py:93`

## Section 10 (M3): `tests/test_ad1340_s1_erasure.py` (new)

The fixture is Section 8's `_memory`, in `archive` mode unless stated otherwise. `_Attachments` is a fake with `async unlink(h) -> bool` that records the ids it was given. `manager = ErasureManager(episodic_memory=em, attachment_store=_Attachments(), audit_log=None)`. `_traces(em, tmp_path, eid)` returns a dict of counts for: ChromaDB (`_raw`), `episode_fts` (raw `sqlite3` on `tmp_path/"chroma"/"episode_fts.db"`, `SELECT count(*) FROM episode_fts WHERE episode_id=?`), activation (raw `sqlite3`), participant (`get_episode_ids_for_agent("agent-a")` contains the id), `episode_archive` rows and `archive_access` rows. "Gone" means every count is 0.

| # | Test (Q7 number) | Asserts |
|---|---|---|
| R1 | `test_erase_live_and_archived` (Q7-4) | Two episodes: L live only; A archived only (evicted with `"activation_decay"`). Each `forget_episode(id)` returns `deleted_episode_ids == [id]`, all traces are gone, and the audit holds an `'erased'` row for it whose `content_hash` is the episode's. (The live-**and**-archived case needs `restore_from_archive` and is M4 T3.) |
| R2 | `test_cascades_reach_the_archive` (Q7-4) | `forget_agent_memory("agent-b")` with one live and one archived episode of `agent-b` (plus an `agent-a` control) erases both and leaves the control. `forget_resource("/srv/reactor.log")`, where only an archived episode's `user_input` names that path, erases it. All traces are gone, and the control episode is untouched |
| R3 | `test_attachment_of_an_archived_episode_is_unlinked` (Q7-4) | An episode with `outcomes=[{"attachment_ids": [h]}]` (`h` = 64 hex) is archived, then `forget_episode` runs: `h in attachments.unlinked` and `h in result.deleted_attachment_ids` |
| R4 | `test_erasure_leaves_only_the_audit_row` | After R1, R2 and R3, the only rows naming those ids in any of the six stores are in `eviction_audit` |
| R5 | `test_custom_reason_from_the_erasure_api_still_erases` (Q7-5) | `forget_episode(id, reason="Captain: forget the reactor incident")` for a live id and for an archived id: both are gone everywhere, and the audit row is `'erased'` with that reason |
| R6 | `test_probe_cleanup_erases` | Seed two episodes into a real archive-mode memory, then `await _cleanup_test_episodes(em, ids)`: no live row, **0 archive rows**, audit `'erased'` with `reason = 'qualification_test_cleanup'` |
| R7 | `test_erase_with_a_failed_archive_deletes_live_then_raises` | A directory sits at the archive path (state `failed`). `evict_by_ids([live_id], disposition=EvictionDisposition.ERASE)` raises `EpisodeArchiveUnavailable`; the live row and its FTS row are already gone; the audit holds `'erased'`. `forget_resource("x")` raises `EpisodeArchiveUnavailable` too (the cascade cannot read the archive) |
| R8 | `test_delete_mode_erase_clears_a_leftover_archive` | Continuing E10's layout (X archived earlier, now in `delete` mode): `forget_episode(X)` → `deleted_episode_ids == [X]`, and the archive holds 0 rows. In `delete` mode with **no** archive file, erasing a live id works, and no archive file is created |
| R9 | `test_sidecar_failure_on_erase_raises` | Monkeypatch `participant_index.delete_episodes` to raise: ERASE raises `EpisodeErasureIncomplete` matching `participant_index`, after the ChromaDB row is gone. The same fault under `"activation_decay"` archive eviction does **not** raise (best-effort, as today) |
| R10 | `test_only_declared_callers_name_erase` | AST scan of `src/probos/**/*.py`: every `EvictionDisposition.ERASE` attribute reference sits in `cognitive/episode_archive.py`, `knowledge/erasure.py` or `cognitive/memory_probes.py`. The docstring states the property (no agent-facing path reaches ERASE; AD-1339) and that adding a caller is a reviewed decision, not a test edit to get past |

---

## Section 11 (M4): restore

Add to `EpisodicMemory` after `iter_archived_episodes`:
```python
    async def restore_from_archive(self, episode_id: str) -> Episode:
        """AD-1340: put one archived episode back in the live store, byte-equal.

        Internal service API (no agent-facing caller in S1). Never goes through
        store(): the rate limits, dedup and write-once guard would refuse or
        alter it. Refuses an id that is already live. The archive row is kept;
        a later eviction of the same content is idempotent. Activation restarts
        from this one access, because the old access rows were deleted at eviction.
        Restore does not trigger capacity eviction; the next store() does.
        """
        archive = self._archive_or_none()
        if archive is None or not self._collection:
            raise EpisodeArchiveUnavailable("episode_archive_unavailable")
        records = await archive.get_records([episode_id])
        if not records:
            raise LookupError("episode_archive_not_found")
        record = records[0]
        episode = self._metadata_to_episode(record.episode_id, record.document, dict(record.metadata))
        async with self._get_store_write_lock():
            live = self._collection.get(ids=[record.episode_id], include=[])
            if live and live.get("ids"):
                raise EpisodeArchiveConflict("episode_archive_restore_live_id")
            self._collection.add(ids=[record.episode_id], documents=[record.document], metadatas=[dict(record.metadata)])
        await archive.record_access(record.episode_id, accessor="episodic_memory", purpose="restore")
        if self._fts_db is not None:
            try:
                fts_content = (episode.user_input or "") + " " + (episode.reflection or "")
                await self._fts_db.execute(
                    "INSERT INTO episode_fts(episode_id, content) VALUES (?, ?)",
                    (episode.id, fts_content),
                )
                await self._fts_db.commit()
            except Exception:
                logger.debug("AD-1340: FTS5 restore insert failed for %s", episode.id[:8], exc_info=True)
        if self._participant_index is not None:
            try:
                participants = episode.anchors.participants if episode.anchors else []
                await self._participant_index.record_episode(episode.id, episode.agent_ids, participants)
            except Exception:
                logger.debug("AD-1340: participant restore insert failed for %s", episode.id[:8], exc_info=True)
        if self._activation_tracker:
            try:
                await self._activation_tracker.record_access(episode.id, access_type="archive_restore")
            except Exception:
                logger.debug("AD-1340: activation restore access failed for %s", episode.id[:8], exc_info=True)
        return episode
```
(The FTS content rule is the one at `:1894`, and the participant call matches `:1906-1909`.)

## Section 12 (M4): reset, declaration, wiring, default flip

1. **Reset** (`__main__.py:2614-2621`): in `RESET_TIERS[2]["files"]`, after the Cognition line (`"session_last.json", "chroma.sqlite3", "cognitive_journal.db",`), insert two lines at the same indentation: the comment `# AD-1340: archived episodes are nurture; a new crew must not inherit them`, then `"episode_archive.db",` alone on its line (no trailing comment: mutant T5m anchors on it). In `_file_purpose` (`:2709-2728`), add `"episode_archive.db": "Episode archive",` after the `"chroma.sqlite3"` entry. Do **not** add `episode_fts.db` or any other sidecar (BF-902).
2. **Declaration** (`storage_declarations.py`): append inside `STORE_DECLARATIONS`, after the `cognitive.procedure-challenges` entry (its closing `    ),` at `:262`, before `)` at `:263`):
```python
    StoreDeclaration(
        id="cognitive.episode-archive",
        title="Episode archive: evicted episodes kept out of recall (AD-1340)",
        owner_module="probos.cognitive.episode_archive",
        owner_symbol="EpisodeArchive",
        canonical_path="episode_archive.db",
        criticality=StoreCriticality.FEATURE_GATED,
        lifecycle_owner="probos.cognitive.episodic.EpisodicMemory",
        retention=StoreRetention.UNBOUNDED,
        backup="included",
        restore="point-in-time",
        retention_note=(
            "Unbounded by design (AD-1340): dream pruning and capacity eviction move episodes here "
            "instead of deleting them, and nothing in the loop drops archived content. Rows leave only "
            "by the Captain's erasure (AD-754), which overwrites them (PRAGMA secure_delete=ON), and by "
            "a Tier 2 reset, which deletes the file. A retention window is the Captain's policy (AD-1340 "
            "S5) and the default is none. Estimated at about 150 MB compressed if every episode pruned to "
            "date had been archived (an estimate, not a measurement); S3 surfaces the real size."
        ),
        notes=(
            "Opened and closed by EpisodicMemory.start/stop beside episode_fts.db, through an injected "
            "ConnectionFactory. Gated on memory.eviction_disposition: in 'delete' mode the file is "
            "opened only if it already exists (so erasure can clear it) and is never created. Backed up "
            "as INCLUDED; erased content persists in earlier snapshots until they age out, as ChromaDB's "
            "does. Never read by default recall."
        ),
    ),
```
3. **Wiring** (`__main__.py`): in the runtime construction (`:609-630`), after `self_contradiction_recall_enabled=config.self_contradiction_recall.enabled,  # AD-1293 (#1200)`, add `eviction_disposition=config.memory.eviction_disposition,  # AD-1340`. In the rebuild CLI construction (`:2243-2251`), after `hnsw_batch_size=cfg.memory.hnsw_batch_size,  # AD-821`, add `eviction_disposition=cfg.memory.eviction_disposition,  # AD-1340`. No `startup/` change is needed: `EpisodicMemory` owns the archive's lifecycle (D1).
4. **Default flip:** `config.py` `eviction_disposition: Literal["archive", "delete"] = "archive"`. `EpisodicMemory.__init__` `eviction_disposition: str = "archive",  # AD-1340`. `test_ad1152_agentic_correlation.py`: change the pop literal to `== "archive"`. Rerun `check_config_facade.py --update-baseline` and `gen_config_reference.py`.

## Section 13 (M4): `tests/test_ad1340_s1_restore_reset.py` (new)

| # | Test (Q7 number) | Asserts |
|---|---|---|
| T1 | `test_byte_equal_round_trip_through_step12` (Q7-2, crosses the seam) | Archive mode with real stores. `store(ep)`, then capture `before_raw = _raw(em, [id])` and `before_ep = (await em.get_by_ids([id]))[0]`. Run `evict_by_ids([id], reason="activation_decay")`, the exact call Step 12 makes (`dreaming.py:1602-1604`), which returns 1. Then wrap `_collection` in a recording proxy and call `restore_from_archive(id)`. The proxy saw `add` and **never** `upsert`. `_raw` document and metadata equal `before_raw`, and the canonical JSON bytes of the metadata are equal. `get_by_ids([id])[0] == before_ep`. `keyword_search(word)` contains `id`. `get_episode_ids_for_agent("agent-a")` contains `id`. The activation log for `id` holds exactly 1 row, with `access_type = 'archive_restore'`. `archive_access` holds 1 row with `purpose = 'restore'`. The archive row is still present. **Capacity variant:** the same assertions for an episode evicted by `max_episodes=2` |
| T2 | `test_restore_refuses_a_live_id` (Q7-3) | Archive, then restore (premise: it succeeds). A second `restore_from_archive(id)` raises `EpisodeArchiveConflict("episode_archive_restore_live_id")`, and the live document and metadata are unchanged. Not archived → `LookupError("episode_archive_not_found")`. Archive closed (after `stop()`) → `EpisodeArchiveUnavailable` |
| T3 | `test_restore_then_erase_clears_every_copy` | Restore (the episode is now live **and** archived), then `forget_episode(id)`: `deleted_episode_ids == [id]`, `archive_access` and `episode_archive` hold 0 rows for the id, every Section 10 trace is gone, and the audit holds `'erased'` |
| T4 | `test_restore_then_re_evict_is_idempotent` | Restore, then `evict_by_ids([id], reason="activation_decay")`: 1 archive row (same key), not live |
| T5 | `test_tier2_reset_removes_the_archive` (Q7-9) | Import `_create_sqlite_db` and `_run_reset` from `tests.test_reset_integration`. Plant `episode_archive.db`. `_run_reset(data_dir, tmp_path)` (Tier 2) → gone. Plant again; `_run_reset(data_dir, tmp_path, soft=True)` (Tier 1) → still present. `"episode_archive.db" in RESET_TIERS[2]["files"]`, `"episode_fts.db" not in` any tier's `files` (D8: BF-902 owns it; **BF-902 inverts this line deliberately**, and the docstring says so), and `_file_purpose("episode_archive.db") == "Episode archive"` |
| T6 | `test_archive_is_declared_and_backed_up` (Q7-10) | `load_default_store_registry().get("cognitive.episode-archive")` has `owner_symbol == "EpisodeArchive"`, `canonical_path == "episode_archive.db"`, `backup == "included"` and `lifecycle_owner == "probos.cognitive.episodic.EpisodicMemory"`. `classify(PurePosixPath("episode_archive.db")) is BackupTier.INCLUDED`, and `is_excluded(PurePosixPath("episode_archive.db")) is None` |
| T7 | `test_default_is_archive_and_the_flag_reaches_both_constructions` | `MemoryConfig().eviction_disposition == "archive"`. `MemoryConfig(eviction_disposition="purge")` → `ValidationError`. `EpisodicMemory(db_path=str(tmp_path / "e.db")).eviction_disposition_mode == "archive"`. AST of `probos/__main__.py`: every `EpisodicMemory(...)` call has an `eviction_disposition=` keyword whose value is an attribute chain ending in `.memory.eviction_disposition` (2 calls) |

---

## Amendment M3r (2026-10-17): the erasure failure path and the restore order

**Revised by:** the orchestrator, 2026-10-17, on the Architect's decision (read-only consult `f63f663c`, #1568 comment 6236685149) and one orchestrator decision inside the envelope (the restore order). The Captain may overrule either. M3 built Sections 9a and 9b as drafted; milestone M3r then changed them as below, so where Section 9 and this amendment differ, **this amendment is what the code does**.

**The gap.** M3's `ErasureManager.forget_episode` read the attachment ids from the live row, then ERASE deleted that row and raised (D6), so the attachment unlink never ran and a retry could not find the ids; the cascades stopped at the first failure, and a failed archive scan erased nothing. The Architect found two more places with the same shape in `_erase_ids`: the strict sidecar cleanup ran only for the ids a retry could still find, so a retry after a partial erase of an episode that was never archived swept nothing and left its FTS text; and a live-delete or sidecar failure raised before the archive copy was erased.

**Decisions.** (1) `forget_episode` unlinks the attachments BEFORE the erase (delete what a record names before the record; `unlink` is idempotent; no exception masking; `mark_deleted` still runs only after a successful erase). Rejected: try/finally, attachment ids in the audit row, accepting the gap. (2) The cascades attempt every match, and the live matches when the archive scan fails, then raise one `ErasureCascadeIncomplete` (defined in `knowledge/erasure.py`; `.result`, `.failures`, `.enumeration_error`, `__cause__` the first failure). (3) `_erase_ids` attempts every phase (the live removal, the archive, the sidecar sweep), raises the first failure last, and sweeps the sidecars by the REQUESTED ids; `_remove_from_live` no longer runs the sidecar cleanup for ERASE. (4) The `'erased'` audit row stays written before the delete (append-only, a retry writes another, D3). (5) Deferred, not S1: `unlink` returns False on `OSError` as well as "not found" (the AD-733 store contract), so erasure cannot tell "already gone" from "failed".

**D6 gains:** every phase is attempted before the first failure is raised; the sidecar sweep is keyed on the requested ids; `forget_episode` unlinks attachments before erasing the episode; the cascades attempt every match and then raise one `ErasureCascadeIncomplete`.

**The restore order (orchestrator, in envelope).** The M4 Builder noted that Section 11's `restore_from_archive` recorded the archive access after the live add and unguarded: a failure there left the episode live without its FTS, participant and activation rows, and a retry hit the live-id refusal. The access is now recorded INSIDE the store write lock, after the live-id check and BEFORE the add (audit before action: an access that cannot be recorded stops the restore before anything changed, and a refused restore records nothing).

**New and changed tests.** R7's last block expects `ErasureCascadeIncomplete` with `enumeration_error` an `EpisodeArchiveUnavailable`. R11 `test_failed_erase_still_unlinks_the_attachments` (the live row existed when unlink ran), R12 `test_cascade_continues_past_a_failing_episode`, R13 `test_cascade_erases_the_live_matches_when_the_archive_scan_fails`, R14 `test_a_failed_live_delete_still_erases_the_archive_copy`, R15 `test_retry_after_a_partial_erase_sweeps_what_was_left`, and T8 `test_restore_fails_closed_when_the_access_cannot_be_recorded`.

**Mutation table.** E4m is re-anchored on the sweep line, and E5m to E8m, K5 to K8 and the restore row R3m are added (see the table).

**Diff Reviewer properties 3, 5 and 15** carry the matching sentences (below).

---

## Amendment R1 (2026-10-17): review round 1 (F1-F4, S1, S2)

**Revised by:** the orchestrator, 2026-10-17, on the Architect's decision (read-only consult `5418932c`, answering round 1 of the Diff Reviewer on `gpt-6.1-sol`). The Captain may overrule. Where Sections 7-11 or Amendment M3r differ, **this amendment is what the code does**. D2, D3 and D6 above carry the matching "(R1)" sentences.

**The gaps.** (F1) The strict sidecar sweep treated a store with no open handle as cleaned. That covers `activation_enabled: false`, a non-fatal start failure and a stopped handle, so ERASE could return success with activation or participant rows left. (F2) Cascades skipped an archived version whose id was also live before applying the predicate. (F3) Attachments came from the live episode or the latest archived version, while ERASE deletes every version. (F4) A re-archive under an existing `(episode_id, content_hash)` kept the old payload, and the read-back checked only the key, so a record whose metadata changed after a restore was deleted from the live store without being archived. (S1) One failing FTS delete stopped the sweep for every later id. (S2) A cascade silently skipped an archived record that could not be rehydrated, and a row that could not be decoded stopped the scan. All four ordinary-reach findings were reproduced by the orchestrator with probes that assert their own premise before this amendment was written.

**Decisions.**
1. Startup (`wire_erasure_sidecar_paths`, unconditional, right after `episodic_memory.start()`) declares the activation and participant-index files to `EpisodicMemory` through `set_erasure_sidecar_paths`. Under ERASE, a store with no open handle is cleared through its own class opened on that file, and the FTS file through the `ConnectionFactory`. Only a missing file means there is nothing to clear. A file that cannot be opened or cleared raises `EpisodeErasureIncomplete`. ERASE on a stopped memory raises `erasure_live_store_unavailable`, after the archive and the sweep have been attempted. Rejected: failing closed on an absent handle (every erase would raise when the flag is off), wiring the stores regardless of the flag (re-enables the feature), reporting without raising (breaks D6), and a constructor parameter (it would copy the file names into `__main__.py`).
2. Cascades apply the predicate to every live and every archived version, then remove duplicate ids. The unit of erasure stays the episode id: a match on any version erases every version.
3. The attachments to unlink are the live episode's plus those of every archived version (`EpisodeArchive.get_versions`, `EpisodicMemory.get_archived_metadata_versions`, which replaces `get_archived_metadata`).
4. The archive upserts, and an update applies only when the stored payload differs (D2, D3). Rejected: a new row per payload (a new row on every restore cycle, and "latest" gets harder to define) and keeping the old payload while keeping the live record (a restored episode could never be evicted again).
5. The FTS sweep clears each id independently. Archive scans continue past bad rows and then raise `EpisodeArchiveIntegrityError`, which the cascade reports as `enumeration_error`.
6. (Orchestrator, in envelope, found by the R1 build: the Architect's spec said it raises.) `EpisodicMemory.get_archived_metadata_versions` returns no versions, with a WARNING, when the archive failed to open. The attachment lookup now runs for every episode, and M3r's rule (tests R11 and R13) is that a live episode is still erased and its attachments still unlinked when the archive is unavailable; ERASE raises `episode_archive_unavailable_for_erase` from its archive phase after every other phase, so the failure is still reported and a retry finds the archived versions once the archive opens. A row that cannot be decoded still raises (follow-up (a)). Mutation row U2.

**Follow-ups (#1523, not S1).** (a) A corrupt archived payload blocks erase by id, because the attachment lookup raises first (it fails closed and visibly; reached only by disk corruption); the decision to take later is "erase anyway, and report the attachment ids that could not be read". (b) `forget_episode` calls `mark_deleted` when no episodic memory is wired (existing at the base).

**Tests (20 added; 65 in all).** R16 `test_erase_clears_activation_rows_when_the_tracker_is_not_wired`, R17 `test_erase_clears_participant_rows_after_a_failed_index_start`, R18 `test_erase_raises_when_an_unwired_store_cannot_be_opened`, R19 `test_erase_with_no_sidecar_file_is_complete_and_creates_none`, R20 `test_erase_clears_fts_text_when_the_fts_handle_is_closed`, R21 `test_erase_clears_stores_whose_handles_were_stopped`, R22 `test_one_failing_fts_delete_does_not_spare_the_other_ids`, R23 `test_erase_on_a_stopped_memory_raises`, R24 `test_cascade_matches_an_archived_version_shadowed_by_a_live_one`, R25 `test_forget_episode_unlinks_attachments_of_every_archived_version`, R26 `test_forget_episode_unions_live_and_archived_attachments`, R27 `test_cascade_reports_an_archived_record_that_cannot_rehydrate`, R28 `test_cascade_scans_past_an_undecodable_archived_row`, R29 `test_startup_sidecar_paths_reach_erase` (production layout: it crosses the seam between startup and erasure); A11 `test_rearchive_with_changed_metadata_replaces_the_payload`, A12 `test_archive_returns_only_ids_whose_stored_payload_matches` (a `BEFORE UPDATE` trigger with `RAISE(IGNORE)` on a second connection), A13 `test_rearchive_of_an_identical_record_is_a_no_op` (`reason` and `archived_at` unchanged), A14 `test_iter_records_continues_past_an_undecodable_row_then_raises`, A15 `test_get_versions_returns_every_row_for_the_id`; T9 `test_reevicting_a_restored_episode_archives_its_current_metadata`. The `_memory` rig declares its sidecar paths and exposes `participants`.

**Mutation table.** G1-G8, L1, I1-I3, Q1-Q3, U2, V1, K9 and K10 are added, K3 is re-anchored, the `_present` exclusion is removed, and the whole campaign is re-run once on the final tree (53 rows; S2 by hand).

**Diff Reviewer properties** 1, 2, 3, 5 and 8 are edited and 16 is added (below).

---

## Amendment R2 (2026-10-17): the restore and erase race

**Revised by:** the orchestrator, 2026-10-17, on the Architect's decision (read-only consult `69fc243d`, answering the orchestrator's own finding: round 1 of the Diff Reviewer had listed concurrent erasure and restore under what it did not check). The Captain may overrule. Where Section 11, Amendment M3r or Amendment R1 differ, **this amendment is what the code does**.

**The gap.** `restore_from_archive` read the archived record before taking the store write lock and inserted the sidecar rows after releasing it, and `_erase_ids` took no lock. An ERASE of the same id that ran inside restore's awaits left the episode live, with its FTS, participant and activation rows and no archive row, after reporting success (reproduced by the orchestrator with a deterministic probe that runs the ERASE inside the awaited `archive.record_access`, premise asserted first). There is no caller in S1; it violated D6 as an API property. Severity High (privacy and data integrity), reach none in S1, a regression of S1's own new code.

**Decisions.** (1) Restore holds `_get_store_write_lock()` from the archive read to the last sidecar insert. This deliberately departs from `store()`'s BF-669 rule, because ERASE must not run between the add and the inserts. (2) `_erase_ids` holds the same lock across its live and archive phases. The strict sweep runs after release: on success no restore can re-create a copy for these ids, and keeping the sweep outside keeps `store()` from waiting on the unwired-store file fallback. (3) Archive and delete eviction take no lock (see the S2 prerequisites). Rejected: locking the whole of `_erase_ids` (`store()` would wait on the file fallback for no gain), and a per-id tombstone set (new state for the same result). The lock is referenced only by `store`, `restore_from_archive` and `_erase_ids`; ERASE has two callers (`knowledge/erasure.py`, `memory_probes.py`) and neither can hold it, so the non-reentrant lock cannot deadlock.

**D6 gains:** an erase that overlaps a restore of the same id either erases the restored copy or makes the restore fail with `episode_archive_not_found`.

**Tests (3 added; 68 in all).** T10 `test_erase_during_restore_waits_then_erases_every_copy`, T11 `test_restore_during_erase_finds_no_record`, T12 `test_erase_during_the_restore_sidecar_tail_leaves_no_index_row`.

**Mutation table.** W1 and W2 are added, and WH1 (move `get_records` and the not-found check above the lock) and WH2 (dedent the three sidecar blocks out of the lock) are checked by hand like S2. The rows pinned to `episodic.py` are re-run on the R2 tree; the other rows keep their kills from the R1 tree, because R2 changes no other source file and only appends tests (an appended test cannot revive a killed mutant). **Diff Reviewer property 17** is added.

**S2 prerequisites (not S1; S2 is the first slice with a restore caller).** (a) Eviction (capacity or Step 12) takes no lock, so it can run during a restore's sidecar tail and leave index rows for an archived id: decide whether `_remove_from_live` takes the store lock. (b) A restored episode keeps its original timestamp, so it is the first capacity victim of the next over-budget `store()`: decide the restore-capacity policy. (c) A metadata update that lands between `_archive_records`' snapshot and the live delete is acknowledged and then lost, because the archive keeps the version from just before the update (the F4 class, concurrent form; reachable in production, but it affects restore fidelity only, and at the base the whole episode vanished): before restore fidelity is relied on, re-read synchronously just before the delete and keep live any id whose payload differs. (d) ERASE against eviction relies on the archive having ONE aiosqlite connection that runs statements in submission order; re-check it if the archive gains a pool or a second connection.

**Recorded on #1523 (not S1).** F-132: `EpisodicMemory.store()` releases the write lock before its FTS and participant inserts (BF-669's design), so an ERASE that lists and erases an episode in that window can leave an index row for an erased id (narrow; Low-Medium; pre-existing).

---

## Mutation table (one campaign of record, after the last repair)

**Tooling rules.** Every anchor below is the line's text with **leading indentation stripped**. The tool must find exactly one line in the named file whose `strip()` equals the anchor, replace it with the mutant, and keep that line's indentation. Count the matches first: zero or more than one means INERT, not killed. Run the unmodified baseline first. Mutate in place with a `.mutbak` sibling and restore in `finally`. A timeout is INVALID. Run each mutant against the M1-M4 test files plus the consumer list in the M4 brief. Record the base tree, the sha256 of each file in the "File" column and of the four `test_ad1340_s1_*.py` files, and KILLED / INERT / INVALID with the first failing test id. A later edit to a file invalidates only the mutants pinned to it. S2 is a two-anchor mutant: replace both lines in one run.

| Id | File | Anchor (stripped) -> mutant | Expected killer |
|---|---|---|---|
| P1 | `cognitive/episode_archive.py` | `logger.warning("AD-1340: unknown eviction reason %r; archiving, never erasing", reason)` -> `return DISPOSITION_ERASED` | A1, E4 |
| P2 | `cognitive/episode_archive.py` | `if explicit is EvictionDisposition.ERASE:` -> `if explicit is EvictionDisposition.ERASE or reason not in ARCHIVE_REASONS:` | A1, E4 |
| P3 | `cognitive/episode_archive.py` | `if explicit is not None and explicit is not EvictionDisposition.ARCHIVE:` -> `if False:` | A1 (plain `"erase"`), E5 |
| C1 | `cognitive/episode_archive.py` | `await db.commit()  # the archive commit: nothing leaves the live store before this returns` -> `pass  # the archive commit: nothing leaves the live store before this returns` | A4 (second connection) |
| H1 | `cognitive/episode_archive.py` | `payload_metadata = dict(record.metadata)` -> `payload_metadata = {k: v for k, v in record.metadata.items() if k != "content_hash"}` | A2, E2, T1 |
| S1 | `cognitive/episode_archive.py` | `await db.execute("PRAGMA secure_delete=ON")` -> `await db.execute("PRAGMA secure_delete=OFF")` | A3 (start refuses), E2 |
| S2 | `cognitive/episode_archive.py` | TWO anchors: S1's anchor -> S1's mutant AND `if not row or int(row[0]) != 1:` -> `if False:` | A6 (`blob not in` file bytes) |
| X1 | `cognitive/episode_archive.py` | `await db.execute(f"DELETE FROM archive_access WHERE episode_id IN ({marks})", chunk)` -> `pass` | A6, T3 |
| O1 | `cognitive/episodic.py` | `committed = await self._archive_records(ids, reason)` -> `committed = self._collection.delete(ids=list(ids)) or await self._archive_records(ids, reason)` | E6, T1 |
| O2 | `cognitive/episodic.py` | `ids = [eid for eid in ids if eid in committed]` -> `ids = list(ids)` | E6, E8 |
| U1 | `cognitive/episodic.py` | `if now - self._archive_warned_at < _ARCHIVE_WARN_INTERVAL_S:` -> `if False:` | E8 (one WARNING) |
| D1 | `cognitive/episodic.py` | `if self._eviction_disposition_mode == "delete" and not path.exists():` -> `if False:` | E9 (no archive file), R8 |
| D2 | `cognitive/episodic.py` | `disposition=outcome,` -> `disposition="deleted",` | E2, E3 (`'archived'`) |
| RC | `cognitive/episodic.py` | `ordered = [by_id[eid] for eid in episode_ids if eid in by_id]` -> `ordered = [by_id[eid] for eid in episode_ids if eid in by_id] + [self._metadata_to_episode(r.episode_id, r.document, dict(r.metadata)) for r in await self._episode_archive.get_records([eid for eid in episode_ids if eid not in by_id])]` | E1 (recall reads the archive) |
| E1m | `cognitive/episodic.py` | `await archive.erase(requested)` -> `pass` | R1, R4, R8 |
| E2m | `cognitive/episodic.py` | `archive_only = [key for key in archived_keys if key[0] not in live_set]` -> `archive_only = []` | R1 (archive-only `deleted_episode_ids`, `'erased'` audit) |
| E3m | `cognitive/episodic.py` | `raise EpisodeArchiveUnavailable("episode_archive_unavailable_for_erase")` -> `return None` | R7 |
| E4m | `cognitive/episodic.py` | `await self._cleanup_sidecars(requested, strict=True)` -> `await self._cleanup_sidecars(requested, strict=False)` | R9 |
| E5m | `cognitive/episodic.py` | `await self._cleanup_sidecars(requested, strict=True)` -> `await self._cleanup_sidecars(live_ids + only_ids, strict=True)` | R15 |
| E6m | `cognitive/episodic.py` | `errors.append(exc)  # archive phase: raised after the sweep` -> `raise` | R7 (`fts == 0`) |
| E7m | `cognitive/episodic.py` | `errors.append(exc)  # live phase: the archive and the sweep still run` -> `raise` | R14 |
| E8m | `cognitive/episodic.py` | `if outcome != DISPOSITION_ERASED:  # ERASE: _erase_ids sweeps every requested id, strictly` -> `if False:` | E2, E3, R9 |
| R1m | `cognitive/episodic.py` | `if live and live.get("ids"):` -> `if False:` | T2 |
| R2m | `cognitive/episodic.py` | `self._collection.add(ids=[record.episode_id], documents=[record.document], metadatas=[dict(record.metadata)])` -> `self._collection.upsert(ids=[record.episode_id], documents=[record.document], metadatas=[dict(record.metadata)])` | T1 (proxy saw `upsert`) |
| K1 | `knowledge/erasure.py` | `[episode_id], reason=reason, disposition=EvictionDisposition.ERASE,` -> `[episode_id], reason=reason,` | R5, R1 |
| K2 | `knowledge/erasure.py` | `if self._episodic_memory is None or not hasattr(self._episodic_memory, "iter_archived_episodes"):` -> `if True:` | R2 |
| K3 | `knowledge/erasure.py` | `if hasattr(self._episodic_memory, "get_archived_metadata_versions"):` -> `if False:` | R3, R25 |
| K4 | `cognitive/memory_probes.py` | `episode_ids, reason="qualification_test_cleanup", disposition=EvictionDisposition.ERASE,` -> `episode_ids, reason="qualification_test_cleanup",` | R6 |
| K5 | `knowledge/erasure.py` | `unlinked = await self._delete_attachments(attachment_ids)` -> `unlinked = []` | R11, R3 |
| K6 | `knowledge/erasure.py` | `failures[episode_id] = exc  # erase the rest, then raise one error naming every failure` -> `raise` | R12 |
| K7 | `knowledge/erasure.py` | `enumeration_error = exc  # the archive scan failed: erase the matches found, then raise` -> `raise` | R13 |
| K8 | `knowledge/erasure.py` | `if failures or enumeration_error is not None:` -> `if failures:` | R7 |
| R3m | `cognitive/episodic.py` | `await archive.record_access(record.episode_id, accessor="episodic_memory", purpose="restore")` -> `pass` | T1 (`archive_access` holds 1 row) |
| T5m | `__main__.py` | `"episode_archive.db",` -> `"episode_archive_kept.db",` | T5 |
| G1 | `cognitive/episodic.py` | `elif strict and not await self._erase_fts_file(ids):` -> `elif False:` | R20 |
| G2 | `cognitive/episodic.py` | `elif strict and not await _erase_store_file("activation", self._activation_db_path, ids):` -> `elif False:` | R16, R29 |
| G3 | `cognitive/episodic.py` | `elif strict and not await _erase_store_file("participant_index", self._participant_index_db_path, ids):` -> `elif False:` | R17, R29 |
| G4 | `cognitive/episodic.py` | `if tracker is not None and (not strict or tracker.is_open):` -> `if tracker is not None:` | R21 |
| G5 | `cognitive/episodic.py` | `if index is not None and (not strict or index.is_open):` -> `if index is not None:` | R21 |
| G6 | `cognitive/episodic.py` | `return False  # the store file holds rows ERASE could not clear` -> `return True` | R18 |
| G7 | `cognitive/episodic.py` | `if not path or not Path(path).exists():` -> `if not path:` | R19 (a file is created) |
| G8 | `cognitive/episodic.py` | `cleared = False  # keep sweeping the remaining ids` -> `return False` | R22 |
| L1 | `cognitive/episodic.py` | `raise EpisodeErasureIncomplete("erasure_live_store_unavailable")  # stopped or never started` -> `pass` | R23 (type and match) |
| I1 | `cognitive/episodic.py` | `if unrehydrated:` -> `if False:` | R27 |
| I2 | `cognitive/episode_archive.py` | `continue  # one bad row never hides the rows after it` -> `raise` | A14, R28 |
| I3 | `cognitive/episode_archive.py` | `if undecodable:` -> `if False:` | A14, R28 |
| Q1 | `cognitive/episode_archive.py` | `"payload = excluded.payload WHERE episode_archive.payload IS NOT excluded.payload",` -> `"payload = episode_archive.payload WHERE episode_archive.payload IS NOT excluded.payload",` | A11, T9 |
| Q2 | `cognitive/episode_archive.py` | `if (episode_id, content_hash) in wanted and bytes(payload) == wanted[(episode_id, content_hash)]:` -> `if (episode_id, content_hash) in wanted:` | A12 |
| Q3 | `cognitive/episode_archive.py` | `"payload = excluded.payload WHERE episode_archive.payload IS NOT excluded.payload",` -> `"payload = excluded.payload",` | A13 |
| V1 | `knowledge/erasure.py` | `yield episode  # every archived version: the predicate decides, _matching_ids deduplicates` -> `if str(getattr(episode, "id", "")) not in {str(getattr(e, "id", "")) for e in await self._list_episodes()}: yield episode` | R24 |
| K9 | `knowledge/erasure.py` | `for archived_meta in await self._episodic_memory.get_archived_metadata_versions(episode_id):` -> `for archived_meta in (await self._episodic_memory.get_archived_metadata_versions(episode_id))[-1:]:` | R25 |
| K10 | `knowledge/erasure.py` | `if hasattr(self._episodic_memory, "get_archived_metadata_versions"):` -> `if not episode_payload and hasattr(self._episodic_memory, "get_archived_metadata_versions"):` | R26 |
| U2 | `cognitive/episodic.py` | `return []  # the archive failed to open: ERASE reports it after every other phase` -> `raise` | R11, R13 |
| W1 | `cognitive/episodic.py` | `async with self._get_store_write_lock():  # AD-1340 R2: restore cannot interleave the live and archive phases` -> `async with asyncio.Lock():  # AD-1340 R2: restore cannot interleave the live and archive phases` | T10 |
| W2 | `cognitive/episodic.py` | `async with self._get_store_write_lock():  # AD-1340 R2: read, check, add and index in one critical section with ERASE` -> `async with asyncio.Lock():  # AD-1340 R2: read, check, add and index in one critical section with ERASE` | T10, T11, T12 |

Not mutated, by design: the `delete`-mode call sequence (E9 pins it directly), the `wire_erasure_sidecar_paths` call site (one unconditional line; property 16) and the FTS no-table branch. Two R2 mutants are checked by hand, like S2: **WH1** moves `get_records` and the not-found check of `restore_from_archive` above the lock (the pre-R2 shape; T11 must fail), and **WH2** dedents the three sidecar blocks of `restore_from_archive` out of the lock (T12 must fail).

---

## Diff Reviewer properties (verify each; data integrity and privacy)

1. Default recall (`recall`, `recall_for_agent`, `recall_weighted`, `keyword_search`, the participant-index lookup, `recent_for_agent`, `get_by_ids`) never reads `episode_archive.db`; only `restore_from_archive`, `get_archived_metadata_versions` (through `EpisodeArchive.get_versions`), `iter_archived_episodes` and `_erase_ids` touch the archive's read methods.
2. In archive mode, no `collection.delete` runs for an id whose archive row was not committed and read back with stored payload bytes equal to the record removed (R1); an unavailable or failing archive deletes nothing.
3. ERASE leaves the episode's content in none of ChromaDB, `episode_fts`, the activation log, the participant index, `episode_archive` and `archive_access`, whether the episode was live, archived or both; only the eviction-audit row (a hash) remains. Any failure to clear a copy raises. (M3r) Every phase is attempted before the first failure is raised, and the sidecar sweep covers every requested id, so a retry after a partial erasure clears what the first attempt left. (R1) A store with no open handle (flag off, failed start, stopped) is cleared through its declared file; only a missing file counts as clean; a file that cannot be opened raises; ERASE on a stopped memory raises; one failing FTS id never spares the others.
4. ERASE is reachable only through an explicit `EvictionDisposition.ERASE`; no reason string, default or unknown value produces it; a plain string `"erase"` raises.
5. `forget_resource` and `forget_agent_memory` match archived episodes, and an archived episode's attachment ids come from its archived metadata. (M3r) `forget_episode` unlinks attachments before erasing the episode and calls `mark_deleted` only on success; the cascades attempt every match, including the live matches when the archive scan fails, and raise one `ErasureCascadeIncomplete` with the first failure as `__cause__`. (R1) Every archived version is matched, even when the id is live; the attachments are the union over the live episode and every archived version; a scan continues past an undecodable or unrehydratable row and the cascade raises `ErasureCascadeIncomplete`.
6. An archive payload's `metadata.content_hash` equals the audit row's `content_hash` and the pre-eviction live metadata.
7. Restore never replaces a live id (checked under the store write lock, `add` not `upsert`, never `store()`), and the restored document, metadata and `Episode` equal the pre-eviction values.
8. The archive keeps one row per `(episode_id, content_hash)`; a byte-identical re-archive changes nothing; a changed payload replaces the stored one (R1); a crash between the archive commit and the live delete yields a duplicate, never a loss.
9. `delete` mode never creates `episode_archive.db`, issues the same live-store calls as today, and writes `disposition='deleted'`, `archive_ref=''`.
10. Every archive connection sets `PRAGMA secure_delete=ON` and refuses to open if it does not read back 1.
11. No agent-facing tool reaches ERASE: the only `EvictionDisposition.ERASE` references are in `episode_archive.py`, `erasure.py` and `memory_probes.py`, and `forget_*` is still called only from `routers/security.py:73-77` and `erasure.py`'s own cascades.
12. Reset Tier 2 removes `episode_archive.db`, and S1 adds no other file to any reset tier (BF-902).
13. `knowledge/erasure.py` imports nothing from `probos.cognitive` (layer rule; the enum is in `probos.types`).
14. `dreaming.py` is unchanged, and so are its Step 12 calls.
15. (M3r) `restore_from_archive` records the archive access inside the store write lock, after the live-id check and before the add, so an access that cannot be recorded stops the restore before anything changed and a refused restore records nothing.
16. (R1) `wire_erasure_sidecar_paths` runs unconditionally after `episodic_memory.start()`. The creation sites and the declaration use the same constants. No new direct `aiosqlite.connect` (the `db-connect` gate). `EpisodicMemory` reaches other stores only through their own classes, opened briefly.
17. (R2) ERASE's live and archive phases, and restore's whole body from `get_records` to the activation insert, run inside `_get_store_write_lock()`. Neither span calls `store()`, `restore_from_archive` or `_erase_ids`, because `asyncio.Lock` is not reentrant. The strict sweep runs after release. The lock is still referenced only by `store`, `restore_from_archive` and `_erase_ids`.

Consumer that must accept the change: the dream cycle's Step 12 on the live ship (it calls `evict_by_ids(ids, reason=...)` unchanged) and the AD-754 route `POST` in `routers/security.py` (it calls `forget_*` unchanged).

## What this does NOT change

- Pruning thresholds, fractions, importance-aware selection, `dreaming.py` (AD-567d, AD-593, AD-598).
- `config/system.yaml` (the Captain may re-enable `aggressive_prune_enabled` after merge; that is his action, not this build's).
- `episode_fts.db` or any other sidecar's reset coverage (BF-902, #1579).
- KnowledgeStore `_evict_episodes` (`knowledge/store.py:234-243`), which unlinks mirror episode JSON files in the Git-backed knowledge repo; it is not a recall store. Its audit rows now read `disposition='deleted'`, which is accurate.
- `_force_update` (`episodic.py:2287`) and the embedding-conflict migration (`:710`); neither is an eviction.
- Working-memory FORGET (AD-670), activation-tracker retention, `chroma.sqlite3` compaction.
- The eviction audit stays insert-only (no `DELETE FROM`); the SIF's cached counts are unchanged.

## Do not build

- No archive lookup by agent, time or cue, no archive FTS index, no route, no agent tool, no Counselor or reminiscence caller (S2).
- No doctor or SIF figures (S3); no consolidation gate or dream-cycle marker (S4); no expiry or retention window (S5).
- No agent-facing erase or restore surface (AD-1339).
- No retroactive recovery of already-evicted episodes.
- No edit to `config/system.yaml`, `dreaming.py`, `startup/`, `routers/`.
- No `git add -A`; stage by explicit path. No broad gate by the Builder.

## Tracking (M5)

- `DECISIONS.md`: append `## AD-1340 S1 (2026-10-17), #1568 -- dream pruning and capacity eviction archive; erasure erases every copy` at the end, in the format of the last section (`:11302` onward): D1-D9 one line each; the Decision 4 amendment verbatim from D4; the rejected Tier 2 alternative (D7); the BF-902 boundary (D8); and the mutation campaign of record (base tree, file sha256s, per-mutant result and killer).
- `PROGRESS.md`: add one status line at the top of the recent-work block (lines 5-15 hold the newest AD lines; match their format): AD-1340 S1 built, the files, test counts, default `archive`.
- Regenerate the AD ledger: `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py`, then `--check` (`tests/test_ad1184_ad_ledger.py` runs it).
- No roadmap edit: `docs/development/` has no AD-1340 or AD-1339 line (grep below).

## Acceptance criteria

1. M1-M4 focused runs green with `-n 0 -p no:randomly`, with `probos.__file__` resolving inside this worktree's `src`.
2. Every consumer test in the M4 brief is green after the default flip, without weakening an assertion; the five fakes changed only by the added keyword.
3. `scripts/check_store_registry.py --check`, `scripts/check_architecture_principles.py --check`, `scripts/check_config_facade.py --check` and `scripts/gen_config_reference.py --check` exit 0 with the files staged.
4. Every mutant in the table is KILLED, none INERT or INVALID, in one campaign of record copied into `DECISIONS.md`.
5. T1 crosses Step 12's exact call → archive → restore → recall surfaces in ONE test, with real stores.
6. The archive appears in the store registry and classifies INCLUDED for backup; Tier 2 reset removes it.
7. With `eviction_disposition: delete`, E9's live-store call sequence and audit legacy columns match today's.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Prior Art and Blind Spots (2026-10-17)

**Internal.** The Captain's 2026-10-15 decision in AD-1339 (#1566) (optimize, never delete; forgetting is fading from recall); the nature/culture/nurture decision (2026-10-16; episodes are nurture, hence D7); `docs/research/darwin-godel-machine-absorption.md` (a system that removes its own evidence cannot audit itself); BF-868's under-erase rule (`knowledge/erasure.py:18-22`), which D6 extends to the archive; AD-1265's "INCLUDED is never inferred away" backup rule (`backup_inventory.py:192-202`), which covers the new file with no exclusion edit.

**External (the consult's searches, session `eaf93fed`; not repeated).**
- SQLite `secure_delete` overwrites deleted content; in WAL mode the old content survives until checkpoint. **Adopted** with the default rollback journal (the factory sets no journal mode, `sqlite_factory.py:16-24`) and a verified pragma (D6, Section 3). FTS5's own `secure-delete` option (3.42+) is **deferred to S2** with the archive text index. Sources: https://antonz.org/sqlite-secure-delete/ , https://www.phoronix.com/news/SQLite-3.42
- Letta (MemGPT) keeps evicted conversation history in a searchable out-of-context recall/archival tier rather than discarding it: the same shape as this AD; **nothing further to adopt** beyond the tiering already decided. Source: https://docs.letta.com/guides/agents/architectures/memgpt

**Reference-projects check (date used: 2026-10-17).** AD-1340 S1 prior art, nothing new. Row updates for `docs/research/reference-projects.md` (not edited by this contract; for the orchestrator or M5 to apply): Letta (MemGPT) — *Last reviewed* 2026-10-17, depth stays *passing*, where recorded "`prompts/ad-1340-s1-archive-and-erase.md` (archival tier, same shape; nothing new)". Memvid (2026-04-05) and the AI Meets Brain survey (2026-04-12) are overdue at a 180-day interval: considered, deferred (neither bears on archive-and-erase semantics).

**Blind spots found in drafting (absorbed or recorded).**
- **Layering:** the consult placed `EvictionDisposition` in the archive module; `knowledge` may not import `cognitive` (`test_layer_boundaries.py:49`). Absorbed: the enum is in `probos/types.py` (Section 1).
- **Wiring:** the archive is an owned sidecar of `EpisodicMemory` (D1), not a `startup/cognitive_services.py` service; otherwise every started test memory would keep archive-mode evictions live.
- **Second construction:** the rebuild CLI builds its own `EpisodicMemory` (`__main__.py:2243-2251`); wired too (Section 12).
- **Config artefacts:** two generated docs pin config defaults; regenerated in M2 and M4.
- **Tests that bypass `__init__`:** 26 tests build `EpisodicMemory.__new__(...)` (grep below). None calls eviction today; if one does after the flip, set the needed attributes in that test as it already does for others. Do not add class-level defaults or `getattr` guards.
- **KnowledgeStore mirror eviction** (`knowledge/store.py:234-243`) also removes episode copies; out of scope (What this does NOT change), recorded so it is not rediscovered.
- **Erasure with a corrupt archive payload:** erasure audits from key columns (`archived_keys`), never from the payload, so a corrupt row cannot block an erase.
- **Overlay backends:** a non-SQLite `ConnectionFactory` cannot honour `PRAGMA secure_delete`; the archive then refuses to open and archive-mode eviction keeps episodes live (growth, not loss). Considered, deferred to the overlay.

## Verified Against Codebase (2026-10-17, base `b8849e34`)

Searches ran with the Grep tool (ripgrep) over this worktree; equivalent `rg -n` commands shown.

```
git diff --stat f89d72a9 b8849e34
  ui/src/components/mcp/McpServersPanel.test.tsx | 43 ++++  (only change since the consult)

rg -n "def evict_by_ids|def _evict\b|self\._evict\(|_collection\.delete\(" src/probos/cognitive/episodic.py
  1936:        await self._evict()
  2315:    async def _evict(self) -> None:
  2356:                    self._collection.delete(...)   [the argument is ids_to_delete]
  2380:    async def evict_by_ids(self, episode_ids: list[str], reason: str = "activation_pruning") -> int:
  2426:            self._collection.delete(...)   [the argument is valid_ids]
rg -n "reason=\"capacity\"|if not result or not result\[\"ids\"\]" src/probos/cognitive/episodic.py
  2349:                            reason="capacity",
  2393:            if not result or not result["ids"]:
rg -n "db_dir = Path|episode_fts.db|self._collection.add\(|fts_content =|record_episode\(" src/probos/cognitive/episodic.py
  1441:        db_dir = Path(self.db_path).parent
  1498:            fts_path = str(db_dir / "episode_fts.db")
  1883:            self._collection.add(
  1894:                fts_content = (episode.user_input or "") + " " + (episode.reflection or "")
  1907:                await self._participant_index.record_episode(
rg -n "delete_episode_accesses|delete_episodes\(" src/probos/cognitive/episodic.py
  2370 / 2443: delete_episode_accesses ; 2376 / 2450: delete_episodes
rg -n "_store_write_lock|def set_participant_index|def set_activation_tracker|AsyncIterator" src/probos/cognitive/episodic.py
  19:from collections.abc import AsyncIterator
  1273:        self._store_write_lock = asyncio.Lock()
  1280:    def set_activation_tracker(self, tracker: Any) -> None:
  1389:    def set_participant_index(self, index: Any) -> None:
  1669:    def _get_store_write_lock(self) -> asyncio.Lock:
rg -n "eviction_audit: Any = None|self._eviction_audit = eviction_audit|self_contradiction_recall_enabled: bool = True" src/probos/cognitive/episodic.py
  1194 / 1245 / 1209
rg -n "def _metadata_to_episode|ordered = \[by_id" src/probos/cognitive/episodic.py
  3696:    def _metadata_to_episode(
  2040:        ordered = [by_id[eid] for eid in episode_ids if eid in by_id]
rg -n "async def (recall|recall_for_agent|recent_for_agent|keyword_search|recall_weighted)\b" src/probos/cognitive/episodic.py
  2614, 3074, 3308, 3794, 4007

rg -n "evict_by_ids\(" src/probos/cognitive/dreaming.py
  1602:                        await self.episodic_memory.evict_by_ids(
  1638:                            await self.episodic_memory.evict_by_ids(
rg -n "activation_decay" tests/test_ad593_pruning_acceleration.py
  134/142/157/187/197: read_text(dreaming.py) ; 198: assert "activation_decay_aggressive" in src ; 282-283: assert '"activation_decay"' in src
rg -n "assert_called_once_with\(\[" tests/test_ad567d_dream_provenance.py
  486:        mock_em.evict_by_ids.assert_called_once_with(["ep-1"], reason="activation_decay")

rg -n "^_SCHEMA|class EvictionRecord|class EvictionAuditLog|async def start|async def record_eviction|async def record_batch_eviction|FROM eviction_audit" src/probos/cognitive/eviction_audit.py
  23:_SCHEMA = """\
  50:class EvictionRecord:
  66:class EvictionAuditLog:
  81:    async def start(self, db_path: str = "eviction_audit.db") -> None:
  112:    async def record_eviction(
  149:    async def record_batch_eviction(
  203 / 219 / 234: SELECT ... FROM eviction_audit ...
rg -n "record_batch_eviction" src/probos/knowledge/store.py
  234:                    await self._eviction_audit.record_batch_eviction(

rg -n "async def forget_episode|evict_by_ids|async def forget_resource|async def forget_agent_memory|async def _list_episodes|get_by_ids|get_episode_metadata" src/probos/knowledge/erasure.py
  77:    async def forget_episode(self, episode_id: str, reason: str = "user_request") -> ErasureResult:
  81:        if self._episodic_memory is not None and hasattr(self._episodic_memory, "evict_by_ids"):
  83:                await self._episodic_memory.evict_by_ids([episode_id], reason=reason)
  98:    async def forget_resource(self, resource_path: str) -> ErasureResult:
  126:    async def forget_agent_memory(self, agent_id: str) -> ErasureResult:
  153:    async def _list_episodes(self) -> list[Any]:
  184/185: get_by_ids ; 188/189: get_episode_metadata
rg -n "reason|forget_" src/probos/routers/security.py
  23:    reason: str = "user_request"
  73:        result = await manager.forget_episode(request.episode_id, reason=request.reason)
  75 / 77: forget_resource / forget_agent_memory
rg -n "evict_by_ids" src/probos/cognitive/memory_probes.py
  81:        await episodic_memory.evict_by_ids(episode_ids, reason="qualification_test_cleanup")

rg -n "class MemoryConfig|max_episodes: int|eviction_audit_enabled|^from typing" src/probos/config.py
  9:from typing import Any, Literal
  829:class MemoryConfig(BaseModel):
  833:    max_episodes: int = 100000          (consult: moved from the issue's :831)
  856:    eviction_audit_enabled: bool = True  # AD-541f: Append-only eviction audit trail
rg -n "shutdown_dispatch_grace_s|shutdown_write_grace_s" tests/test_ad1152_agentic_correlation.py
  276:    assert config["memory"].pop("shutdown_write_grace_s") == 1.0
  277:    assert config["memory"].pop("shutdown_dispatch_grace_s") == 2.0
rg -n "eviction_audit_enabled" docs/development
  config-facade-baseline.yaml:2369 ; config-reference.md:184
rg -n "update-baseline|--check" scripts/check_config_facade.py scripts/gen_config_reference.py
  check_config_facade.py:136-137 ; gen_config_reference.py:10

rg -n "RESET_TIERS|_ALWAYS_PRESERVED|chroma.sqlite3|INSERT INTO eviction_audit" src/probos/__main__.py
  2601:RESET_TIERS = {
  2616:            "session_last.json", "chroma.sqlite3", "cognitive_journal.db",
  2636:_ALWAYS_PRESERVED = ["archives/"]
  2714:        "chroma.sqlite3": "Episodic memory",
  2940:                        "INSERT INTO eviction_audit "   (names its 9 columns, 2941-2943)
  2955-2960: per-tier file delete loop ; 2975-2979: chromadb_uuid_dirs
rg -n "EpisodicMemory\(" src
  __main__.py:609 (runtime) ; __main__.py:2243 (rebuild CLI) ; episodic_health.py:362 (docstring only)
rg -n "eviction_audit|set_participant_index|set_activation_tracker" src/probos/startup
  cognitive_services.py:289, 349-354, 439 ; shutdown.py:1260-1264 ; structural_services.py:88

rg -n "class SQLiteConnectionFactory|async def connect|aiosqlite.connect" src/probos/storage/sqlite_factory.py
  10 / 16 / 23   (no journal-mode pragma)
rg -n "class ConnectionFactory|class DatabaseConnection|async def (fetchone|fetchall|commit|close|executescript)" src/probos/protocols.py
  325 / 362 ; 340 / 344 / 348 / 352 / 356  (no rollback method: hence execute("ROLLBACK"))
rg -n "def classify|return BackupTier.INCLUDED" src/probos/infrastructure/backup_inventory.py
  192:def classify(relative_path: PurePosixPath) -> BackupTier:
  202:    return BackupTier.INCLUDED
rg -n "cognitive.eviction-audit|DELETE FROM|cognitive.episode-fts|cognitive.procedure-challenges|^\)$" src/probos/cognitive/storage_declarations.py
  48 ; 59 / 66 ; 93 ; 225 ; 263
rg -n "FEATURE_GATED|UNBOUNDED" src/probos/storage/declarations.py
  75 / 89
rg -n "def load_default_store_registry|def get\(" src/probos/storage/registry.py
  119 / 105

rg -n "FOUNDATION_MODULES|\"knowledge\": \{" tests/test_layer_boundaries.py
  35:FOUNDATION_MODULES = {   36: "types", "config", ...
  49:    "knowledge": {"substrate"},
rg -n "^from enum|class Priority|LOW = \"low\"" src/probos/types.py
  9:from enum import Enum, StrEnum ; 139:class Priority(StrEnum): ; 150:    LOW = "low"

rg -n "async def evict_by_ids" tests/test_erasure_manager.py tests/test_bf868_erasure_declared_fields.py tests/test_bf869_fused_frame_refs.py tests/test_ad582_memory_probes.py
  test_erasure_manager.py:33 ; test_bf868...:66, 87 ; test_bf869...:50 ; test_ad582...:93
rg -n "^def _create_sqlite_db|^def _run_reset|^def _reset_args" tests/test_reset_integration.py
  11 / 44 / 35   (soft=False default at 37)
rg -n "def tmp_episodic|ParticipantIndex\(db_path" tests/test_participant_index.py
  71 / 78-80
rg -n "def __init__|async def record_access|access_type" src/probos/cognitive/activation_tracker.py
  55 (db_path kw) ; 88-101 record_access(episode_id, access_type="recall")
rg -n "async def (record_episode|get_episode_ids_for_agent|delete_episodes)" src/probos/cognitive/participant_index.py
  75 / 124 / 187
rg -n "async def unlink" src/probos/attachments
  store.py:74 ; filesystem_store.py:294
rg -n "EpisodicMemory\.__new__" tests        (26 hits; e.g. test_ad1037_affect_capture.py:73)

git ls-files --eol <each edited file>   ->  i/lf  w/crlf  (all of them)
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py
  git log subjects AD-1333 ; GitHub issue titles AD-1341 ; prompts/ad-*.md AD-1328
  CEILING: AD-1341 (from: GitHub issue titles (all states))   NEXT: AD-1342
```

## Absence Verified (2026-10-17)

```
CLAIM: no archive store, disposition enum, restore or flag exists yet
RUN:   rg -n "episode_archive|EpisodeArchive|EvictionDisposition|restore_from_archive|eviction_disposition" --glob "*.{py,yaml,ts,tsx}" .
FOUND: nothing
HOLDS: yes

CLAIM: no secure_delete anywhere in src
RUN:   rg -n "secure_delete|secure-delete" src
FOUND: nothing
HOLDS: yes

CLAIM: no durable dream-cycle completion marker (S4's concern; S1 depends on none)
RUN:   rg -n "last_dream|_last_cycle|dream_cycle_count|cycles_completed|dream_complete" src
FOUND: dreaming.py:3115,3122,3134-3135,3213-3214,3296-3313 (in-memory monotonic state and last report);
       events.py:176 DREAM_COMPLETE (event, in events.db, Tier 1); counselor.py:1021,1065 (handler);
       importance_scorer.py:33; introspect.py:585; renderer.py:104; commands_memory.py:96; runtime.py:5585,5971,6242 (readers of last_dream_report)
HOLDS: yes -- none is a persisted completion record

CLAIM: no citation index ("knowledge cites this episode"; S5's concern)
RUN:   rg -n "episode_citation|citation_index|cited_episode|cites_episode" src
FOUND: nothing
HOLDS: yes

CLAIM: episode_fts.db (and the other sidecars) are in no reset tier
RUN:   rg -n "episode_fts|activation_tracker|participant" src/probos/__main__.py
FOUND: nothing
HOLDS: yes (BF-902 owns it)

CLAIM: no evict_by_ids caller other than Step 12 (x2), memory_probes and erasure
RUN:   rg -n "evict_by_ids" src
FOUND: dreaming.py:1602,1638 ; episodic.py:2380 (def), 2419, 2455 (self) ; memory_probes.py:81 ; erasure.py:81,83
HOLDS: yes

CLAIM: forget_* is reached only from the security router and erasure's own cascades
RUN:   rg -n "ErasureManager\(|\.forget_episode\(|\.forget_resource\(|\.forget_agent_memory\(" src
FOUND: erasure.py:114,141 ; routers/security.py:66,73,75,77
HOLDS: yes

CLAIM: no test calls eviction on a real EpisodicMemory outside the files this contract lists
RUN:   rg -n "\.evict_by_ids\(|\._evict\(\)" tests
FOUND: test_ad541f_eviction_audit.py:170 (docstring) ; test_participant_index.py:295
HOLDS: yes for direct calls; capacity eviction via store() with small max_episodes runs in
       test_ad541f_eviction_audit.py:182,210,234, test_episodic_chromadb.py:244, test_ad567b_anchor_recall.py:258,
       test_participant_index.py:254, test_ad608_retroactive_evolution.py:327, test_episodic.py:431 (all in the M4 consumer list)

CLAIM: no roadmap line for AD-1339/AD-1340
RUN:   rg -n "AD-1340|AD-1339" docs/development
FOUND: nothing
HOLDS: yes
```

## Not verified

- No interpreter ran SQLite here (bridge). A6's "blob not in file bytes" after `secure_delete` erase, the `(a, b) > (?, ?)` row-value paging, and `ALTER TABLE ... NOT NULL DEFAULT` on the existing file are standard SQLite behaviour and are asserted by A6, A8 and E11. If a premise fails, stop and report rather than weaken the assertion.
- That ChromaDB returns metadata which survives a canonical JSON round trip type for type (`int` stays `int`, `bool` stays `bool`) is asserted by T1 and A2, not checked here. If T1 fails only on a type, stop and report: it is a design question (D2), not a test to loosen.
- Live-ship figures (330,030 audit rows, 547 live episodes, sizes) are the issue's 2026-10-15 read-only measurements; not re-measured.

---

=== BUILDER BRIEFS ===

General rules for every milestone: set `PYTHONPATH` to this worktree's `src` and confirm `probos.__file__` resolves inside it. Use ranged reads and single-line or anchored edits (CRLF tree). Stage by explicit path. Keep `pytest-xdist` addopts unchanged except `-n 0` on focused runs. Stop and report on any anchor not found exactly once.

### Brief M1 — store and policy (effort: max)
**Sections:** 1, 2, 3, 4. **May touch:** `src/probos/types.py`, `src/probos/cognitive/eviction_audit.py` (Section 2 constants only), new `src/probos/cognitive/episode_archive.py` (copy Section 3 verbatim), new `tests/test_ad1340_s1_archive_store.py`.
**Focused run:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1340_s1_archive_store.py tests/test_ad541f_eviction_audit.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`
**Stop if:** A3 or A6's premise fails on this SQLite build; a layer test fails.

### Brief M2 — eviction paths, flag, audit (effort: max)
**Sections:** 5, 6, 7, 8. **May touch:** `eviction_audit.py`, `config.py`, `episodic.py`, `tests/test_ad1152_agentic_correlation.py` (one pop), the two regenerated config docs, new `tests/test_ad1340_s1_eviction.py`. Defaults stay `"delete"` (D9).
**Focused run:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1340_s1_eviction.py tests/test_ad1340_s1_archive_store.py tests/test_ad541f_eviction_audit.py tests/test_ad567d_dream_provenance.py tests/test_ad593_pruning_acceleration.py tests/test_participant_index.py tests/test_ad541b_reconsolidation.py tests/test_ad1152_agentic_correlation.py tests/test_ad1270e2b_cognition_models.py tests/test_config_reference_current.py tests/test_ad1270e1_config_facade.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`
**Stop if:** E1 recall differs between modes; E9's call sequence differs from today's; any `dreaming.py` edit seems needed.

### Brief M3 — erasure (effort: max)
**Sections:** 9, 10. **May touch:** `episodic.py` (`_erase_ids`, `get_archived_metadata`, `iter_archived_episodes`), `knowledge/erasure.py`, `cognitive/memory_probes.py`, the five fakes (Section 9d, signature only), new `tests/test_ad1340_s1_erasure.py`.
**Focused run:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1340_s1_erasure.py tests/test_ad1340_s1_eviction.py tests/test_erasure_manager.py tests/test_bf868_erasure_declared_fields.py tests/test_bf869_fused_frame_refs.py tests/test_ad582_memory_probes.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`
**Stop if:** any erasure consumer test needs more than the keyword; R4 finds content in any store.

**S1a / S1b cut.** If the Builder has used about 150 tool calls by the end of M3, cut here. M1-M3 are committed locally as **S1a**, with defaults still `"delete"` (so the live ship's behaviour is unchanged by S1a alone). A fresh Builder session runs M4 and M5 as **S1b**, which includes the default flip. Both slices go in the **same batch and the same receipted gate**, and S1a is never pushed alone. The S1b Builder reads only Sections 11-13, the mutation table and the M4/M5 briefs.

### Brief M4 — restore, reset, declaration, wiring, default flip (effort: max)
**Sections:** 11, 12, 13. **May touch:** `episodic.py` (restore and the default), `__main__.py` (one tier entry, one purpose entry, two keywords), `storage_declarations.py`, `config.py` (default), `tests/test_ad1152_agentic_correlation.py` (literal), the two regenerated config docs, new `tests/test_ad1340_s1_restore_reset.py`.
**Focused run (includes the post-flip consumers):** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1340_s1_restore_reset.py tests/test_ad1340_s1_erasure.py tests/test_ad1340_s1_eviction.py tests/test_ad1340_s1_archive_store.py tests/test_reset_integration.py tests/test_ad1256_store_registry.py tests/test_ad1265_backup_coverage.py tests/test_ad541f_eviction_audit.py tests/test_ad567d_dream_provenance.py tests/test_ad593_pruning_acceleration.py tests/test_ad582_memory_probes.py tests/test_participant_index.py tests/test_ad541b_reconsolidation.py tests/test_ad1270e2b_cognition_models.py tests/test_erasure_manager.py tests/test_bf868_erasure_declared_fields.py tests/test_bf869_fused_frame_refs.py tests/test_episodic_chromadb.py tests/test_ad567b_anchor_recall.py tests/test_ad608_retroactive_evolution.py tests/test_episodic.py tests/test_ad1152_agentic_correlation.py tests/test_config_reference_current.py tests/test_ad1270e1_config_facade.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`, then the four checkers in Acceptance 3 with the files staged.
**Then:** the mutation campaign of record (table above), once, after the last repair.
**Stop if:** T1 fails on a metadata type (design question, D2); a consumer test fails after the flip for any reason other than an `__new__`-built memory missing the new attributes (that one is fixed in the test, see Blind spots); a mutant survives (first check that it reaches the behaviour).

### Brief M5 — trackers (effort: high)
**Section:** Tracking (M5). **May touch:** `DECISIONS.md` (append), `PROGRESS.md` (one line), the regenerated AD ledger. Copy the campaign of record into the `DECISIONS.md` entry after recomputing the file sha256s on disk; if any differs from the campaign report, stop (the campaign is stale). **Run:** `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py`, then `--check`, then `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad1340-s1` on the staged candidate, and repair any cheap failure it reports. No broad gate.

### Brief R1 — review round 1 repair (effort: high)
**Sections:** Amendment R1, D2, D3, D6, the mutation rows G1-G8, L1, I1-I3, Q1-Q3, U2, V1, K3, K9 and K10, and Diff Reviewer properties 1, 2, 3, 5, 8 and 16. **May touch:** `src/probos/cognitive/episodic.py`, `episode_archive.py`, `activation_tracker.py` and `participant_index.py` (an `is_open` property each), `episodic_mock.py` (a no-op `set_erasure_sidecar_paths`), `src/probos/knowledge/erasure.py`, `src/probos/startup/cognitive_services.py` (two file-name constants, `wire_erasure_sidecar_paths`, one unconditional call), and the four `tests/test_ad1340_s1_*.py` files (the `_memory` rig declares its sidecar paths and exposes `participants`). Write every anchor line of the new mutation rows VERBATIM, comment included, so that each occurs exactly once in its file. **Run:** the M4 focused command plus `tests/test_participant_index.py` and `tests/test_activation_tracker*.py`, then `scripts/check_store_registry.py --check` and `scripts/check_architecture_principles.py --check` (no new `db-connect`). **Stop if:** a pre-existing test fails for a reason other than a fake missing `is_open` (add the attribute to the fake and list it); a premise in the Architect's spec does not hold in the tree; any new test needs a weaker assertion than the table states. No broad gate and no staging.

### Brief R2 — the restore and erase race (effort: high)
**Sections:** Amendment R2, D6, the mutation rows W1 and W2 (and WH1, WH2 by hand), Diff Reviewer property 17. **May touch:** `src/probos/cognitive/episodic.py` (`restore_from_archive`, `_erase_ids`) and `tests/test_ad1340_s1_restore_reset.py`, APPEND ONLY: do not edit an existing test or helper. Write each anchor line of W1 and W2 verbatim, comment included, so that each occurs exactly once in `episodic.py`. **Run:** the M4 focused command plus the R1 extras, then `scripts/check_architecture_principles.py --check`. **Stop if:** T1-T9 or any R test needs a change; a premise does not hold; any of T10-T12 passes with W1 or W2 applied by hand. No broad gate and no staging.
