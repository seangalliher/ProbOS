# AD-1340 S2a (#1568): the Captain's audited lookup of archived episodes, by id and by primary agent and time

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-17

**Orchestrator edit (2026-10-18, before the first commit):** Section 4a's anchor now stops before the existing `router` line, and the request model's `model_config` is a plain dict, so this file carries no third-party constructor text that `scripts/phantom-api-precheck.ps1` flags when the file is re-staged by a later amendment. Behaviour is unchanged; all 12 SEARCH blocks were re-counted (exactly one match each) after the edit.

**Status:** ready to build. **Base:** `origin/main` at `76c9507405fd04d47da48df7f70ee072fe006754` (after BF-902). **AD:** AD-1340, slice S2a; no new AD or BF number. **Depends on:** S1 (merged) and BF-902 (merged). **Estimated tests:** 29 new in two files. **Milestones:** M1 the archive, M2 the memory pass-throughs and the route, M3 the trackers.

One-line summary: an archived episode can be read back deliberately, by its id or by its primary agent and a time range, through one crew-scope Captain route that refuses while no token is configured; every episode returned has exactly one committed `archive_access` row, written in one transaction before anything is returned.

---

## Problem

S1 made eviction archive the episode (`src/probos/cognitive/episode_archive.py`), but nothing outside erasure and the internal restore can read the archive. #1568's acceptance asks that "a deliberate archive lookup by id, by agent and time, and by cue finds the episode, and every lookup is recorded" (issue body, acceptance). S2 is split into four slices (consult `f77cf59d`, recorded on #1568, comment 6244376956): **S2a** lookup by id and by agent plus time, read from a Captain route; S2b the first restore caller and S1's prerequisites (a) to (c); S2c the cue index; S2d the agent-facing consumers. This contract is S2a only.

What exists today, verified on this tree:

- `episode_archive` already has `agent_id TEXT NOT NULL` and `episode_timestamp REAL NOT NULL` (`episode_archive.py:70-71`). `archive()` fills them on every row with `primary_agent_id(record.metadata)` and `_episode_timestamp(record.metadata)` (`:317-320`, rules at `:138-151`). There is no index on them (`_SCHEMA`, `:66-89`).
- `record_access()` takes `_write_lock` and commits one row per call (`:450-462`). `erase()` deletes every archive row and every access row for the requested ids in one transaction (`:464-479`; access rows at `:474`).
- The read methods (`get_records`, `archived_keys`, `get_versions`, `iter_records`) take no lock (`:356-448`). `get_records` and `get_versions` raise on the first undecodable row (`decode_payload`, `:369`, `:411`); `iter_records` skips it and reports a count at the end (`:436-448`).
- `EpisodicMemory` exposes no lookup. Its archive state is `"absent" | "open" | "failed"` (`episodic.py:1367`); `_archive_or_none()` returns `None` for `"absent"` (`:2593-2599`), which a lookup must not turn into an empty success.
- AD-754's `POST /api/security/forget` (`routers/security.py:60-64`) has no authorization dependency (`Depends(get_runtime)` only), and the app has no authentication middleware: the only middleware is CORS (`api.py:184-189`). The Captain's other controls use `Depends(require_crew_scope)` (`routers/approval_authority.py:145`), which passes every caller through when `auth.crew_scope_token` is empty (`routers/auth.py:57-59`). `config/system.yaml:987-988` ships an empty token.

## Solution overview

1. **Schema (M1):** one index, `idx_episode_archive_agent_time ON episode_archive(agent_id, episode_timestamp)`, created with `CREATE INDEX IF NOT EXISTS` in `_SCHEMA`. No column and no backfill (Decision D1). `ARCHIVE_SCHEMA_VERSION` stays 1 (D2).
2. **Lookup (M1):** `EpisodeArchive.lookup_by_id` and `lookup_by_agent` read without a lock, decode row by row (a bad row is counted and skipped), then write one access row per decoded record in **one** transaction under `_write_lock`. The INSERT carries its own condition: the exact row the lookup read (key and payload bytes) must still be stored. They return only the records whose access row committed (D3 to D6).
3. **Pass-throughs (M2):** `EpisodicMemory.lookup_archived_by_id` and `lookup_archived_by_agent`. They take no lock, read no live store, and raise `EpisodeArchiveUnavailable` when there is no open archive (D7).
4. **Route (M2):** `POST /api/security/archive/lookup` in `routers/security.py`, protected by `require_crew_scope`, refusing 403 while no token is configured, before anything is read (D8 to D11).
5. **Trackers (M3).**

## Decisions (decided by the Architect; the Captain may overrule any of them afterwards)

### D1. An index, no new column, no backfill
The consult's "add `episode_ts` and `primary_agent` columns and backfill them" is **withdrawn**. The orchestrator corrected it and I re-verified the correction: both values are already columns, populated by every `archive()` since S1 (`episode_archive.py:70-71`, `:317-320`). M1 therefore has no backfill step. The index sits on the same rows, so ERASE's existing `DELETE FROM episode_archive WHERE episode_id IN (...)` (`:473`) removes its entries. There is no new erase surface.

### D2. No schema-version change; the rollback path
An index-only change needs no version bump. With the version left at 1, an S1 binary opening an S2a file passes its own check (`:269-273` accepts 0 and 1), finds the index harmless, runs its `_SCHEMA` (all `IF NOT EXISTS`, so nothing happens), and maintains the index on every insert and delete, because SQLite maintains every index whatever code created it. If the version were bumped to 2, a rollback to S1 would make `start()` raise `episode_archive_schema_unknown`. The archive would then go `"failed"` (`episodic.py:2588`): eviction would keep every episode live and ERASE would refuse. That is a worse failure than any benefit a version bump gives. Rejected: a version bump with a migration.

### D3. "By agent" means the primary agent only, and the response says so
The key is the AD-541f audit rule that `archive()` already stores: the first entry of `agent_ids_json`, else `"unknown"`. An episode whose first participant is another agent is **not** found by the second agent's id. S2a accepts and documents this. The agent response carries `"agent_match": "primary_agent_only"`. `"unknown"` is an ordinary query value and returns the unattributed rows. Matching is exact (SQLite `=` with BINARY collation) on the stored id, which is the sovereign id, not a callsign. Deferred: a per-agent side table, which would match every participant (consult option 3: a new store that ERASE must clear).

### D4. One row per episode id: its latest archived version
If an id has more than one archived version (different `content_hash`), a lookup returns only the one with the greatest `archived_at`; an exact tie keeps the smallest `content_hash`. This is the version `get_records` gives restore (`:371`: the greatest `archived_at` wins). Its tie order is unspecified but in practice is primary-key order, i.e. the smallest hash. So what the Captain reviews is what S2b's restore would put back. The rule is applied in SQL (`NOT EXISTS` over the same id), so a limit counts episodes, not versions. When the latest version has a different agent or timestamp, the older version is not found by its own values. The latest version decides. Reach in S2a is about zero, because a second hash needs a restore and a content change, and S2a has no restore caller.

### D5. Order, bounds and partial failure: no unaudited read
1. **Read, without a lock** (S1 R3: reads take none). The SQL is limited to `limit + 1` rows, so `truncated` is known without decoding more than `limit` rows.
2. **Decode each row on its own.** An undecodable row is counted in `undecodable`, logged at WARNING with its id, and skipped. It gets no access row, because it is not returned. One bad row never hides the rest (F-129's class: a corrupt payload must not block the other rows).
3. **Record the access rows: one transaction under `_write_lock`.** One `INSERT ... SELECT ... WHERE EXISTS (row with this id, hash and payload bytes)` per decoded record, then one `COMMIT`. Any exception rolls the whole batch back and raises `EpisodeArchiveError("episode_archive_access_not_recorded")`, and nothing is returned. `rowcount == 1` marks the records whose row was still there.
4. **Return** only the records whose access row committed. Records whose row was erased or replaced since the read are counted in `withdrawn` and not returned.

Why the re-check is inside the INSERT and not left to the read: the unlocked read runs on the archive's single shared connection, so it can see another writer's **uncommitted** statements (S1 R3 F2's class). One example is an `archive()` insert that later rolls back. The locked, conditional INSERT is the authority, so no unlocked read decides anything. This is what (d) requires, kept by construction.

A batched private method is warranted rather than a loop over `record_access`. Up to 200 commits per lookup would be slow, and a failure part-way would leave some rows audited and some not. One transaction is all or nothing. `record_access` itself is unchanged (restore still uses it, `episodic.py:2922`).

**Limit:** default 50, maximum 200, minimum 1. Enforced in the route (422) and again in the archive (`ValueError`), and never clamped. **Order:** newest first (`episode_timestamp DESC, episode_id DESC`). **Range:** `since <= episode_timestamp < until` on the episode's own time. A `None` bound is open. Non-finite or empty ranges are refused. No pagination cursor in S2a: `truncated: true` tells the Captain to narrow the range.

**Cancellation:** a lookup cancelled inside its transaction can leave pending access-row inserts that the next writer's commit makes durable. That is an over-record, never an under-record, which is the outcome S1 R3 accepted when it deferred BF-891's shielded rollback.

### D6. Erasure and linearisation
A lookup takes effect when its access transaction commits. If an ERASE committed first, the row is gone, the conditional INSERT writes nothing, and the id is not returned. If the ERASE commits later, it deletes that id's access rows as well (`:474`, unchanged). The access rows of a cancelled lookup are still pending on the shared connection, so they fall inside the ERASE's own transaction and are deleted too. Both orders end with no access row for an erased id. "An erased id is never returned" means exactly this: never after its ERASE committed.

### D7. Pass-throughs: typed unavailability, no lock, no live store
`_archive_for_lookup()` returns the open archive. Otherwise it raises `EpisodeArchiveUnavailable` with `episode_archive_failed_to_open` (state `"failed"`) or `episode_archive_not_open` (never started, delete mode with no file, or stopped). It never returns an empty result. Inside the archive, `_require_open()` covers a `stop()` during a lookup (`episode_archive_not_open`). The pass-throughs touch no `_collection`, no sidecar and no `_get_store_write_lock()`.

### D8. The route and its protection
`POST /api/security/archive/lookup`, next to `/forget`. It is a POST because the call writes audit rows, so it is neither safe nor idempotent in HTTP terms, and ids stay out of URLs and access logs. Its protection is `dependencies=[Depends(require_crew_scope)]` **and** a 403 `episode_archive_lookup_requires_token` while `auth.crew_scope_token` is empty. That check is the handler's first statement, before episodic memory or the archive is touched. This follows the repository's rule for sensitive surfaces: identity keys refuse 403 `identity_keys_require_token` (`routers/identity.py:163-164`), and federation attachments "must never serve bytes through an open gate" (`routers/federation_attachments.py:10-12`, `:110`).

**What still has access (stated honestly):** with a token configured, anyone holding the single shared crew-scope token (AD-722b-1 v1: one secret, no per-person identity) can read. With no token configured, nobody can use the route, the Captain included. He has to set `auth.crew_scope_token` first. That is an **action** only he can take, not a decision. In both cases, a process running as the Captain's own OS user can read `episode_archive.db` directly, because the file is not encrypted. S2a adds no protection against that, and the AD-1240 reasoning applies: the route must be no weaker than the file. Live episodes already have weaker protection: `GET /api/agents/{agent_id}/chat/history` returns live episode text with no crew scope (`routers/agents.py:3853-3876`). That route is not changed here.

**No config flag:** a closed default, the 403 without a token, already makes the route safe. A second flag would add a config field and its tests and protect nothing more. Rejected.

### D9. Request and response
Request (JSON body, `extra="forbid"`): exactly one of `episode_id` and `agent_id` (each 1 to 256 characters). `since`, `until` and `limit` are allowed only with `agent_id`, and are refused with `episode_id` (422), because they would otherwise be silently ignored. `since` and `until` must be finite, because the JSON parser accepts `NaN` and `Infinity`, and `since < until`. `limit` must be 1 to 200 (default 50).

Response 200:

```json
{"lookup": "episode_id" | "agent",
 "agent_match": "primary_agent_only",          // agent lookups only
 "episodes": [{"episode_id", "content_hash", "agent_id", "episode_timestamp",
               "archived_at", "reason", "document", "metadata"}],
 "count": 0, "truncated": false, "undecodable": 0, "withdrawn": 0}
```

**Nothing is redacted.** The payload is the raw record the live store held, with no embedding (S1 D2). It is the Captain's own ship data, which his erasure right already covers. The review has to show exactly what a restore would bring back. Redacting would make it less faithful without protecting anyone who could not already read the file (D8). An id that is not archived returns 200 with `episodes: []`; that is the truth when the archive is open.

### D10. Error mapping (every error is `{"detail": code}`)
| Status | Detail | When |
|---|---|---|
| 401 | `missing_or_malformed_authorization` / `invalid_token` | A token is configured and the request's token is missing or wrong (`require_crew_scope`, unchanged) |
| 403 | `episode_archive_lookup_requires_token` | No token is configured. Nothing is read. |
| 422 | Pydantic | Invalid request (D9) |
| 503 | `episodic_memory_unavailable` | `runtime.episodic_memory` is `None` |
| 503 | `episode_archive_not_open` / `episode_archive_failed_to_open` | `EpisodeArchiveUnavailable` |
| 500 | `episode_archive_access_not_recorded` | The access transaction failed and was rolled back. Logged at ERROR. Nothing is returned. |

### D11. Audit: `archive_access` is the only audit owner
There is no `AuditLog` entry. The access row is the record of the lookup, and ERASE must remove every trace a lookup left (D6). `AuditLog` (`assistant_audit.db`, retention-based) cannot be erased by episode. The accessor is the fixed string `captain:/api/security/archive/lookup` and the purpose is `lookup` (`LOOKUP_PURPOSE`). The route logs one INFO line with the counts and never logs content.

### D12. Compatibility
The new route is additive and sits under the existing `/api/security` prefix, with no existing route at that path (Absence Verified 2). `/forget`, its request model and its response are unchanged. No HXI or CLI code calls `/api/security/*` today (Absence Verified 1). The Captain calls the new route with `Authorization: Bearer <token>`, and a console view is later work. The OpenAPI document gains one operation, and no existing schema changes.

---

## Section 0: Event types
None. S2a adds no `EventType`.

## Section 1 (M1): `src/probos/cognitive/episode_archive.py`

### 1a. Imports

SEARCH:
```python
import asyncio
import json
import logging
import time
import zlib
```
REPLACE:
```python
import asyncio
import json
import logging
import math
import time
import zlib
```

### 1b. `__all__`

SEARCH:
```python
__all__ = [
    "ARCHIVE_FILENAME",
    "ARCHIVE_REASONS",
    "EVICTION_MODES",
    "ArchiveRecord",
    "EpisodeArchive",
```
REPLACE:
```python
__all__ = [
    "ARCHIVE_FILENAME",
    "ARCHIVE_REASONS",
    "EVICTION_MODES",
    "LOOKUP_DEFAULT_LIMIT",
    "LOOKUP_MAX_LIMIT",
    "LOOKUP_PURPOSE",
    "ArchiveLookupResult",
    "ArchiveRecord",
    "ArchivedEpisode",
    "EpisodeArchive",
```

### 1c. Constants

SEARCH:
```python
#: ``memory.eviction_disposition`` values.
EVICTION_MODES: frozenset[str] = frozenset({"archive", "delete"})
_SQL_CHUNK = 500
```
REPLACE:
```python
#: ``memory.eviction_disposition`` values.
EVICTION_MODES: frozenset[str] = frozenset({"archive", "delete"})
_SQL_CHUNK = 500
#: AD-1340 S2a: lookup bounds, and the access purpose every lookup records.
LOOKUP_DEFAULT_LIMIT = 50
LOOKUP_MAX_LIMIT = 200
LOOKUP_PURPOSE = "lookup"
```

### 1d. The index and the lookup SQL

SEARCH:
```python
CREATE INDEX IF NOT EXISTS idx_archive_access_episode
    ON archive_access(episode_id);
"""
```
REPLACE:
```python
CREATE INDEX IF NOT EXISTS idx_archive_access_episode
    ON archive_access(episode_id);

CREATE INDEX IF NOT EXISTS idx_episode_archive_agent_time
    ON episode_archive(agent_id, episode_timestamp);
"""

_LOOKUP_COLUMNS = (
    "a.episode_id, a.content_hash, a.agent_id, a.episode_timestamp, a.archived_at, a.reason, "
    "a.payload_format, a.payload"
)
#: AD-1340 S2a D4: one row per episode id, its latest archived version (the version get_records restores);
#: an exact tie on archived_at keeps the smallest content_hash.
_LATEST_VERSION = (
    "NOT EXISTS (SELECT 1 FROM episode_archive b WHERE b.episode_id = a.episode_id AND "
    "(b.archived_at > a.archived_at OR (b.archived_at = a.archived_at AND b.content_hash < a.content_hash)))"
)
_LOOKUP_BY_ID_SQL = f"SELECT {_LOOKUP_COLUMNS} FROM episode_archive a WHERE a.episode_id = ? AND {_LATEST_VERSION}"
_LOOKUP_BY_AGENT_SQL = (
    f"SELECT {_LOOKUP_COLUMNS} FROM episode_archive a "
    "WHERE a.agent_id = ? AND a.episode_timestamp >= ? AND a.episode_timestamp < ? "
    f"AND {_LATEST_VERSION} "
    "ORDER BY a.episode_timestamp DESC, a.episode_id DESC LIMIT ?"
)
#: AD-1340 S2a D5: an access row is written only while the exact row the lookup read (key and bytes) is stored.
_RECORD_LOOKUP_ACCESS_SQL = (
    "INSERT INTO archive_access (episode_id, accessed_at, accessor, purpose) SELECT ?, ?, ?, ? "
    "WHERE EXISTS (SELECT 1 FROM episode_archive WHERE episode_id = ? AND content_hash = ? AND payload = ?)"
)
```

### 1e. Accessor helper (after `_chunks`)

SEARCH:
```python
def _chunks(items: Sequence[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield list(items[start:start + size])
```
REPLACE:
```python
def _chunks(items: Sequence[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield list(items[start:start + size])


def _require_accessor(accessor: str) -> None:
    if not isinstance(accessor, str) or not accessor.strip():
        raise ValueError("episode_archive_lookup_accessor_invalid")
```

### 1f. Result types (after `ArchiveRecord`)

SEARCH:
```python
    @property
    def archive_ref(self) -> str:
        return f"episode_archive:{self.episode_id}:{self.content_hash}"


def encode_payload(record: ArchiveRecord) -> bytes:
```
REPLACE:
```python
    @property
    def archive_ref(self) -> str:
        return f"episode_archive:{self.episode_id}:{self.content_hash}"


@dataclass(frozen=True)
class ArchivedEpisode:
    """AD-1340 S2a: one archived record a lookup returned, with the key columns it was found by."""

    record: ArchiveRecord
    agent_id: str
    episode_timestamp: float
    archived_at: float
    reason: str


@dataclass(frozen=True)
class ArchiveLookupResult:
    """AD-1340 S2a: what a lookup returned. Every episode here has exactly one committed access row.

    ``undecodable``: matching rows whose payload could not be decoded (not returned, no access row).
    ``withdrawn``: decoded rows erased or replaced before their access row was written (not returned).
    ``truncated``: more rows matched than the limit allowed.
    """

    episodes: tuple[ArchivedEpisode, ...] = ()
    undecodable: int = 0
    withdrawn: int = 0
    truncated: bool = False


def encode_payload(record: ArchiveRecord) -> bytes:
```

### 1g. Class docstring

SEARCH:
```python
    Not a recall surface: nothing on the default recall paths calls it.
    S2 adds the recorded lookups (by agent and time, by cue).
    AD-1340 R3: mutations are serialised by `_write_lock`; reads are not.
```
REPLACE:
```python
    Not a recall surface: nothing on the default recall paths calls it.
    S2a adds the recorded lookups by id and by primary agent and time (S2c adds cue).
    AD-1340 R3: mutations are serialised by `_write_lock`; reads are not.
```

### 1h. The lookup methods (before `record_access`)

SEARCH:
```python
        if undecodable:
            raise EpisodeArchiveIntegrityError(f"episode_archive_rows_undecodable:{undecodable}")

    async def record_access(self, episode_id: str, *, accessor: str, purpose: str) -> None:
```
REPLACE:
```python
        if undecodable:
            raise EpisodeArchiveIntegrityError(f"episode_archive_rows_undecodable:{undecodable}")

    async def lookup_by_id(self, episode_id: str, *, accessor: str) -> ArchiveLookupResult:
        """AD-1340 S2a: the latest archived version of one episode, recorded as one access row.

        A deliberate, audited read, never a recall surface. The read takes no lock; the access row is
        written under ``_write_lock`` and committed before anything is returned.
        """
        if not isinstance(episode_id, str) or not episode_id:
            raise ValueError("episode_archive_lookup_id_invalid")
        _require_accessor(accessor)
        return await self._lookup(_LOOKUP_BY_ID_SQL, (episode_id,), limit=1, accessor=accessor)

    async def lookup_by_agent(
        self,
        agent_id: str,
        *,
        since: float | None = None,
        until: float | None = None,
        limit: int = LOOKUP_DEFAULT_LIMIT,
        accessor: str,
    ) -> ArchiveLookupResult:
        """AD-1340 S2a: archived episodes whose PRIMARY agent is ``agent_id``, ``since <= timestamp < until``.

        Newest first, at most ``limit`` (1..LOOKUP_MAX_LIMIT). The primary agent is the first entry of
        ``agent_ids_json``, else ``"unknown"`` (the AD-541f rule ``archive()`` stores in ``agent_id``): an
        episode whose first participant is another agent is not found by this agent's id. ``None`` is open.
        """
        if not isinstance(agent_id, str) or not agent_id:
            raise ValueError("episode_archive_lookup_agent_invalid")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= LOOKUP_MAX_LIMIT:
            raise ValueError("episode_archive_lookup_limit_invalid")
        lower = -math.inf if since is None else float(since)
        upper = math.inf if until is None else float(until)
        if math.isnan(lower) or math.isnan(upper) or lower >= upper:
            raise ValueError("episode_archive_lookup_range_invalid")
        _require_accessor(accessor)
        return await self._lookup(
            _LOOKUP_BY_AGENT_SQL, (agent_id, lower, upper, limit + 1), limit=limit, accessor=accessor,
        )

    async def _lookup(
        self, sql: str, params: tuple[Any, ...], *, limit: int, accessor: str,
    ) -> ArchiveLookupResult:
        db = self._require_open()
        cursor = await db.execute(sql, params)  # a read: no lock (R3); the locked INSERT below decides
        rows = await cursor.fetchall()
        truncated = len(rows) > limit
        decoded: list[tuple[ArchivedEpisode, bytes]] = []
        undecodable = 0
        for row in rows[:limit]:
            episode_id, content_hash, agent_id, episode_timestamp, archived_at, reason, payload_format, payload = row
            try:
                record = decode_payload(episode_id, content_hash, payload_format, payload)
            except EpisodeArchiveIntegrityError:
                undecodable += 1
                logger.warning(
                    "AD-1340 S2a: archived row %s could not be decoded; the lookup returns the others",
                    episode_id, exc_info=True,
                )
                continue  # AD-1340 S2a: one bad row never hides the others in a lookup
            item = ArchivedEpisode(record, str(agent_id), float(episode_timestamp), float(archived_at), str(reason))
            decoded.append((item, bytes(payload)))
        recorded = await self._record_lookup_access(decoded, accessor=accessor) if decoded else frozenset()
        episodes = tuple(item for item, _ in decoded if (item.record.episode_id, item.record.content_hash) in recorded)
        return ArchiveLookupResult(
            episodes=episodes,
            undecodable=undecodable,
            withdrawn=len(decoded) - len(episodes),
            truncated=truncated,
        )

    async def _record_lookup_access(
        self, decoded: Sequence[tuple[ArchivedEpisode, bytes]], *, accessor: str,
    ) -> frozenset[tuple[str, str]]:
        """One access row per decoded record whose exact row (key and bytes) is still stored, in ONE transaction.

        The INSERT evaluates its own condition inside the lock, so a row erased or replaced since the unlocked
        read gets no access row and is not returned. Any failure rolls the whole batch back and raises: a
        lookup never returns a record whose access row was not committed. Returns the committed keys.
        """
        async with self._write_lock:  # AD-1340 S2a: a lookup's access rows commit alone, after their rows are re-checked
            db = self._require_open()
            now = time.time()
            recorded: set[tuple[str, str]] = set()
            try:
                for item, payload in decoded:
                    eid, chash = item.record.episode_id, item.record.content_hash
                    cursor = await db.execute(_RECORD_LOOKUP_ACCESS_SQL, (eid, now, accessor, LOOKUP_PURPOSE, eid, chash, payload))
                    if cursor.rowcount == 1:
                        recorded.add((eid, chash))
                await db.commit()  # AD-1340 S2a: no lookup returns a record before its access row is committed
            except Exception as exc:
                await _rollback_quietly(db)  # AD-1340 S2a: no access row of a failed lookup survives
                raise EpisodeArchiveError("episode_archive_access_not_recorded") from exc
            return frozenset(recorded)

    async def record_access(self, episode_id: str, *, accessor: str, purpose: str) -> None:
```

Notes for the Builder: `_record_lookup_access` holds `_write_lock` for its whole transaction and calls no other lock-taking method. `archive()`, `_present()`, `record_access()`, `erase()`, `stop()`, `get_records()`, `archived_keys()`, `get_versions()` and `iter_records()` are **not edited**. If `cursor.rowcount` does not report 1 or 0 for `INSERT ... SELECT` on the venv's sqlite3, stop and report. Do not replace it with a read-back outside the lock.

## Section 2 (M1): `tests/test_ad1340_s2a_archive_lookup.py` (new)

Real `EpisodeArchive` on `tmp_path`. A raw `sqlite3` connection is the independent witness, as in `tests/test_ad1340_s1_archive_store.py:61-76`; copy its `_record`, `_rows`, `_write`, `_count` and `_started` helpers locally (`:51-85`, small, test-local). Do not import from another test module. Every test asserts its premise first. To pause a lookup between its read and its access transaction, the test holds `archive._write_lock` (test-only private access, as S1's tests use `archive._db`), starts the lookup as a task, asserts after `asyncio.wait({task}, timeout=0.3)` that the task is **not** done, changes the file through the raw connection (the archive's connection holds no open transaction while the test holds the lock), then releases the lock. A real SQLite failure is injected with a TEMP trigger on the archive's own connection, as in `_arm_failing_write` (`:750-756`).

| # | Test | Asserts |
|---|---|---|
| A-1 | `test_schema_adds_only_the_agent_time_index_and_keeps_version_1` | After `start()`: `PRAGMA index_list(episode_archive)` names `idx_episode_archive_agent_time` on `(agent_id, episode_timestamp)`. `PRAGMA table_info` gives S1's eight columns in order. `user_version == 1`. |
| A-2 | `test_an_s1_file_gains_the_index_and_stays_openable_by_s1` | A file created with S1's DDL (the two tables and `idx_archive_access_episode` only, typed in the test), `user_version` 1, and one row inserted raw with S1's column list (premise: no agent index). After S2a `start()` the index exists, `user_version` is still 1, and `lookup_by_agent` finds the row. A second raw insert with S1's column list after `stop()` is found by the next lookup (SQLite maintains the index for S1-shaped writers). |
| A-3 | `test_lookup_by_id_returns_the_record_and_one_committed_access_row` | `record == _record(i)` (document and metadata equal). The raw witness, read right after the call returns, sees exactly one `archive_access` row for the id, with `accessor` equal to the given accessor and `purpose == "lookup"`. The counts are zero and `truncated` is False. |
| A-4 | `test_lookup_of_an_unknown_id_is_empty_and_records_nothing` | `episodes == ()`, and the raw `archive_access` count is unchanged. |
| A-5 | `test_lookup_returns_only_the_latest_version_of_an_id` | Two hashes of one id; `archived_at` set by raw UPDATE to 1000 and 2000, so the newer hash is returned for both lookup forms. Then both are set to 1000, and the smaller hash is returned. One access row per lookup. |
| A-6 | `test_lookup_by_agent_range_is_half_open_and_newest_first` | Rows at t = 10, 20, 30. `since=10, until=30` returns [20, 10] (t = 10 is included, t = 30 is excluded). With `since=None, until=None` all three come back newest first. |
| A-7 | `test_lookup_by_agent_limit_and_truncation` | 51 rows: the default returns 50 with `truncated` True. The returned rows are the 50 newest. `limit=51` returns 51 with `truncated` False. `limit=0`, `201` and `True` raise `ValueError("episode_archive_lookup_limit_invalid")`. `limit=200` is accepted. |
| A-8 | `test_lookup_by_agent_matches_the_primary_agent_only` | An episode with `agent_ids_json='["agent-b", "agent-a"]'` is found by `agent-b` and not by `agent-a`. One with no `agent_ids_json` is found by `"unknown"`. |
| A-9 | `test_one_undecodable_row_never_hides_the_others` | Three rows, one payload corrupted by raw UPDATE (premise: `decode_payload` raises on it). The lookup returns the other two with `undecodable == 1` and writes no access row for the corrupt id. One WARNING names that id. |
| A-10 | `test_a_row_erased_after_the_read_is_withdrawn_and_leaves_no_access_row` | The lock is held and the lookup task is blocked (premise: not done). The row is deleted raw, then the lock is released. Result: `episodes == ()`, `withdrawn == 1`, and the raw `archive_access` count is 0. |
| A-11 | `test_a_row_replaced_after_the_read_is_withdrawn` | The same pause, but the row's payload is replaced raw with a valid, different payload under the same key. Result: `withdrawn == 1` and no access row. |
| A-12 | `test_a_failed_access_write_returns_nothing_and_leaves_no_access_row` | A TEMP trigger aborts the access INSERT for the second of three ids, and the call raises `EpisodeArchiveError` matching `^episode_archive_access_not_recorded$`. The test then calls `archive.record_access("ep-other", accessor="test", purpose="after")` (a later commit on the same connection). The raw `archive_access` count for the three ids is 0. |
| A-13 | `test_erase_removes_the_access_rows_a_lookup_wrote` | (a) Lookup, then `erase([id])`: archive and access counts are 0. (b) With the lock held, the lookup task is started and shown blocked (premise: not done after 0.3 s, so its read is complete and it waits on the lock). Only then is the `erase` task started, and then the lock is released. The FIFO order gives the lookup first, which returns the record. After both finish, the archive and access counts are 0. |
| A-14 | `test_lookup_on_a_closed_archive_raises_unavailable` | Before `start()` and after `stop()`, both lookups raise `EpisodeArchiveUnavailable` matching `^episode_archive_not_open$`. |
| A-15 | `test_lookup_validates_its_arguments` | Each of these raises the named `ValueError`: an empty id, an empty agent, an empty or blank accessor, a NaN `since`, `since == until`, and `since > until`. |
| A-16 | `test_lookups_change_no_archive_row` | `SELECT * FROM episode_archive ORDER BY episode_id, content_hash` is taken raw before and after a mixed batch: by id, by agent, an unknown id, a withdrawn lookup and a failed lookup (A-12's trigger). The two are equal, and `archive_access` grew by exactly the number of episodes returned. |
| A-17 | `test_erase_leaves_no_agent_trace_in_the_file` | Agent id `agent-s2a-marker-7f3a9c`. Premise: its UTF-8 bytes are in `path.read_bytes()` (in the table row and in the agent index). After `erase`, they are not (`secure_delete`, `:264-268`, covers the index pages too). |
| A-18 | `test_the_agent_lookup_uses_the_index` | The raw `EXPLAIN QUERY PLAN` of `episode_archive._LOOKUP_BY_AGENT_SQL` (test-only private access), with sample parameters, names `idx_episode_archive_agent_time`. |

## Section 3 (M2): `src/probos/cognitive/episodic.py`

### 3a. Import

SEARCH:
```python
from probos.cognitive.episode_archive import (
    ARCHIVE_FILENAME,
    EVICTION_MODES,
    ArchiveRecord,
    EpisodeArchive,
```
REPLACE:
```python
from probos.cognitive.episode_archive import (
    ARCHIVE_FILENAME,
    EVICTION_MODES,
    LOOKUP_DEFAULT_LIMIT,
    ArchiveLookupResult,
    ArchiveRecord,
    EpisodeArchive,
```

### 3b. Pass-throughs (between `iter_archived_episodes` and `restore_from_archive`)

SEARCH:
```python
        if unrehydrated:
            raise EpisodeArchiveIntegrityError(f"episode_archive_rows_unrehydratable:{unrehydrated}")

    async def restore_from_archive(self, episode_id: str) -> Episode:
```
REPLACE:
```python
        if unrehydrated:
            raise EpisodeArchiveIntegrityError(f"episode_archive_rows_unrehydratable:{unrehydrated}")

    def _archive_for_lookup(self) -> EpisodeArchive:
        """AD-1340 S2a: the open archive for a deliberate lookup, else a typed error (never an empty result)."""
        archive = self._episode_archive
        if self._archive_state == "open" and archive is not None:
            return archive
        if self._archive_state == "failed":
            raise EpisodeArchiveUnavailable("episode_archive_failed_to_open")
        raise EpisodeArchiveUnavailable("episode_archive_not_open")  # AD-1340 S2a: no archive is never an empty result

    async def lookup_archived_by_id(self, episode_id: str, *, accessor: str) -> ArchiveLookupResult:
        """AD-1340 S2a: the Captain's audited read of one archived episode (``EpisodeArchive.lookup_by_id``).

        Not a recall surface. Takes no lock and never reads the live store or any sidecar.
        """
        return await self._archive_for_lookup().lookup_by_id(episode_id, accessor=accessor)

    async def lookup_archived_by_agent(
        self,
        agent_id: str,
        *,
        since: float | None = None,
        until: float | None = None,
        limit: int = LOOKUP_DEFAULT_LIMIT,
        accessor: str,
    ) -> ArchiveLookupResult:
        """AD-1340 S2a: the Captain's audited read by primary agent and time (``EpisodeArchive.lookup_by_agent``).

        Not a recall surface. Takes no lock and never reads the live store or any sidecar.
        """
        return await self._archive_for_lookup().lookup_by_agent(
            agent_id, since=since, until=until, limit=limit, accessor=accessor,
        )

    async def restore_from_archive(self, episode_id: str) -> Episode:
```

No other line of `episodic.py` changes. In particular `_archive_records` (`:2612-2637`), `_erase_ids`, `restore_from_archive`, `get_by_ids` (`:2293`) and every recall method stay as they are.

## Section 4 (M2): `src/probos/routers/security.py`

### 4a. Imports and logger

SEARCH:
```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, model_validator

from probos.knowledge.erasure import ErasureManager
from probos.routers.deps import get_runtime
from probos.security.audit_log import AuditLog
```
REPLACE:
```python
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from probos.cognitive.episode_archive import (
    LOOKUP_DEFAULT_LIMIT,
    LOOKUP_MAX_LIMIT,
    ArchivedEpisode,
    EpisodeArchiveError,
    EpisodeArchiveUnavailable,
)
from probos.knowledge.erasure import ErasureManager
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
from probos.security.audit_log import AuditLog

logger = logging.getLogger(__name__)
```

The existing `router` object line that follows is untouched (the anchor stops before it, so this block stays free of constructor text).

### 4b. The route (append after `request_erasure`; the file ends at `:89`)

SEARCH:
```python
    return {
        "deleted_count": result.count,
        "timestamps": result.timestamps,
        "deleted_episode_ids": result.deleted_episode_ids,
        "deleted_attachment_ids": result.deleted_attachment_ids,
    }
```
REPLACE:
```python
    return {
        "deleted_count": result.count,
        "timestamps": result.timestamps,
        "deleted_episode_ids": result.deleted_episode_ids,
        "deleted_attachment_ids": result.deleted_attachment_ids,
    }


_ARCHIVE_LOOKUP_ACCESSOR = "captain:/api/security/archive/lookup"
_ARCHIVE_LOOKUP_TOKEN_REQUIRED = "episode_archive_lookup_requires_token"


class ArchiveLookupRequest(BaseModel):
    """AD-1340 S2a: exactly one of ``episode_id`` or ``agent_id``; ``since``/``until``/``limit`` go with ``agent_id``."""

    model_config = {"extra": "forbid"}

    episode_id: str | None = Field(default=None, min_length=1, max_length=256)
    agent_id: str | None = Field(default=None, min_length=1, max_length=256)
    since: float | None = None
    until: float | None = None
    limit: int = Field(default=LOOKUP_DEFAULT_LIMIT, ge=1, le=LOOKUP_MAX_LIMIT)

    @model_validator(mode="after")
    def _validate_lookup(self) -> "ArchiveLookupRequest":
        if bool(self.episode_id) == bool(self.agent_id):
            raise ValueError("exactly one of episode_id/agent_id is required")
        if self.episode_id and self.model_fields_set & {"since", "until", "limit"}:
            raise ValueError("since/until/limit apply only to an agent_id lookup")
        for bound in (self.since, self.until):
            if bound is not None and not math.isfinite(bound):
                raise ValueError("since/until must be finite")
        if self.since is not None and self.until is not None and self.since >= self.until:
            raise ValueError("since must be earlier than until")
        return self


def _archived_episode_body(item: ArchivedEpisode) -> dict[str, Any]:
    return {
        "episode_id": item.record.episode_id,
        "content_hash": item.record.content_hash,
        "agent_id": item.agent_id,
        "episode_timestamp": item.episode_timestamp,
        "archived_at": item.archived_at,
        "reason": item.reason,
        "document": item.record.document,
        "metadata": dict(item.record.metadata),
    }


@router.post("/archive/lookup", dependencies=[Depends(require_crew_scope)])
async def lookup_archived_episodes(
    request: ArchiveLookupRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-1340 S2a: the Captain's audited read of archived episodes, by id or by primary agent and time.

    Refused (403) while no crew-scope token is configured, before anything is read: ``require_crew_scope``
    passes every caller through when the token is empty, and decoded episodes are never served through an
    open gate (the AD-1196 / AD-731a-1 rule). Every returned episode has one committed ``archive_access`` row.
    """
    if not runtime.config.auth.crew_scope_token:  # AD-1340 S2a: never serve archived episodes through an open gate
        raise HTTPException(status_code=403, detail=_ARCHIVE_LOOKUP_TOKEN_REQUIRED)
    memory = getattr(runtime, "episodic_memory", None)
    if memory is None:
        raise HTTPException(status_code=503, detail="episodic_memory_unavailable")
    try:
        if request.episode_id:
            result = await memory.lookup_archived_by_id(request.episode_id, accessor=_ARCHIVE_LOOKUP_ACCESSOR)
        else:
            result = await memory.lookup_archived_by_agent(
                request.agent_id, since=request.since, until=request.until, limit=request.limit,
                accessor=_ARCHIVE_LOOKUP_ACCESSOR,
            )
    except EpisodeArchiveUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EpisodeArchiveError as exc:
        logger.error("AD-1340 S2a: archive lookup failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    kind = "episode_id" if request.episode_id else "agent"
    logger.info(
        "AD-1340 S2a: archive lookup by %s returned %d (undecodable %d, withdrawn %d, truncated %s)",
        kind, len(result.episodes), result.undecodable, result.withdrawn, result.truncated,
    )
    body: dict[str, Any] = {
        "lookup": kind,
        "episodes": [_archived_episode_body(item) for item in result.episodes],
        "count": len(result.episodes),
        "truncated": result.truncated,
        "undecodable": result.undecodable,
        "withdrawn": result.withdrawn,
    }
    if request.agent_id:
        body["agent_match"] = "primary_agent_only"
    return body
```

`/forget`, `ForgetRequest`, `_install_root` and `_get_audit_log` are unchanged (`tests/test_ad1025b_path_anchoring.py` pins the last two).

## Section 5 (M2): `tests/test_ad1340_s2a_lookup_route.py` (new)

Real `EpisodicMemory` on `tmp_path`, built like S1's `_memory` rig (`tests/test_ad1340_s1_eviction.py:88-113`; copy it locally). Episodes are built like S1's `_episode` (`:62-72`). Eviction goes through Step 12's own call, `em.evict_by_ids(ids, reason="activation_decay")`. The archive file is `root / "chroma" / ARCHIVE_FILENAME` (`:134`; `db_dir = Path(self.db_path).parent`, `episodic.py:1586`).

**Route tests go through the real app.** `create_app(runtime)` from `probos.api`, as `tests/test_camera_frame_origin.py:33-50,64` does, with a `MagicMock` runtime whose `config` is a real `SystemConfig()`, `episodic_memory` the real memory, `attachment_store = None` and `data_dir = tmp_path`. Requests go through `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")` **in the test's own event loop**, because the memory's aiosqlite connections and locks belong to that loop. Do not use `TestClient`, which runs the app in another loop. Nothing mocks the lookup, the archive or the erasure. Each test asserts its premise first (the episode is archived: `_count(archive, "episode_archive", id) == 1`, and no access row exists yet).

| # | Test | Asserts |
|---|---|---|
| E-1 | `test_memory_lookup_finds_an_evicted_episode_byte_equal` | The raw `em._collection.get(ids=[id], include=["documents","metadatas"])` is taken before eviction. After `evict_by_ids(..., reason="activation_decay")` the id is no longer live (premise). `lookup_archived_by_id` returns a document and metadata equal to the snapshot, and `lookup_archived_by_agent("agent-a")` returns it too. |
| E-2 | `test_memory_lookup_never_touches_the_live_store` | `em._collection` is replaced by an object whose every attribute access raises `AssertionError` (restored in `finally`). Both lookups succeed and return the archived record. |
| E-3 | `test_memory_lookup_takes_no_store_lock` | While the test holds `em._get_store_write_lock()`, both lookups finish within 2 s. |
| E-4 | `test_memory_lookup_without_an_archive_raises` | Delete mode with no archive file (premise: file absent): `EpisodeArchiveUnavailable` matching `^episode_archive_not_open$`. A file pre-created raw with `PRAGMA user_version = 7` (premise: `archive_available` is False after `start()`): `^episode_archive_failed_to_open$`. After `em.stop()`: `^episode_archive_not_open$`. |
| RT-a | `test_route_refuses_without_a_configured_token_before_any_read` | With an empty token: 403 `{"detail": "episode_archive_lookup_requires_token"}` for both forms, and the access count is still 0. Also with the archive in the `"failed"` state the answer is 403, not 503, which proves the token check comes first. |
| RT-b | `test_route_rejects_a_missing_or_wrong_token` | With a token configured: no header gives 401 and `Bearer wrong` gives 401, and the access count is still 0. |
| RT-c | `test_route_returns_the_archived_record_by_id_and_records_one_access` | `Bearer <token>` gives 200, `lookup == "episode_id"`, and no `agent_match`. The returned `document` and `metadata` equal E-1's pre-eviction snapshot. `count == 1`. There is exactly one raw access row, with accessor `captain:/api/security/archive/lookup` and purpose `lookup`. |
| RT-d | `test_route_by_agent_is_newest_first_and_states_the_primary_agent_rule` | Three evicted episodes give newest-first order and `agent_match == "primary_agent_only"`. `limit=2` gives `count == 2` with `truncated` True. A `since`/`until` window returns the middle one only. |
| RT-e | `test_route_validates_the_request` | 422 for each of: both ids; neither; `since` with `episode_id`; `limit` with `episode_id`; `since >= until`; `limit` 0 and 201; an unknown field; and raw bodies `{"agent_id":"agent-a","since":NaN}` and `{"agent_id":"agent-a","until":Infinity}` (sent as `content=` with a JSON content type). No access row is written. |
| RT-f | `test_route_maps_an_unavailable_archive_to_503` | `episodic_memory = None` gives 503 `episodic_memory_unavailable`. The E-4 states give 503 with the matching detail. |
| RT-g | `test_seam_evict_lookup_forget_leaves_nothing` | **One test crosses the seam:** Step 12's eviction call, then the lookup route (200, one access row), then the AD-754 route `POST /api/security/forget {"episode_id": id}` (200, `deleted_episode_ids == [id]`), then the raw archive and access counts for the id are 0 and the lookup route returns `episodes == []` with `withdrawn == 0`. |

## Tests summary

29 tests: A-1 to A-18 in `tests/test_ad1340_s2a_archive_lookup.py`, and E-1 to E-4 and RT-a to RT-g in `tests/test_ad1340_s2a_lookup_route.py`. Boundaries covered: happy path (A-3, A-6, RT-c, RT-d), empty (A-4), errors (A-12, A-14, A-15, E-4, RT-e, RT-f), concurrency (A-10, A-11, A-13), privacy (A-17, RT-a, RT-b, RT-g).

## Focused gates (per milestone; `-n 0 -p no:randomly`; confirm `probos.__file__` resolves inside this worktree's `src`)

- **M1:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1340_s2a_archive_lookup.py tests/test_ad1340_s1_archive_store.py -q -n 0 -p no:randomly`
- **M2:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1340_s2a_lookup_route.py tests/test_ad1340_s2a_archive_lookup.py tests/test_ad1340_s1_archive_store.py tests/test_ad1340_s1_eviction.py tests/test_ad1340_s1_erasure.py tests/test_ad1340_s1_restore_reset.py tests/test_bf902_fts_reconciliation.py tests/test_ad1025b_path_anchoring.py -q -n 0 -p no:randomly`
- **M2 checks:** `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check` and `d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check`, both exiting 0. S2a adds no store and no config field, so the config facade and reference checks are not affected.
- **M3:** `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py`, then `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py --check` and `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1184_ad_ledger.py -q -n 0`.

**Consumer tests of the changed files (enumerated, Absence Verified 5 to 7):** `episode_archive.py`: the four `tests/test_ad1340_s1_*.py` files. `episodic.py`: the same four plus `tests/test_bf902_fts_reconciliation.py`. The many other `test_episodic*` and recall tests are left to the broad gate, because S2a changes no existing line of `episodic.py`. `routers/security.py`: `tests/test_ad1025b_path_anchoring.py`. The broad gate is run once by the orchestrator, never by the Builder.

## Milestones and cut points (Builder milestones of at most about 150 tool calls)

| Milestone | Sections | Estimate | Cut if past about 150 calls |
|---|---|---|---|
| M1 | 1, 2 | 60 to 80 | Stop after Section 1 plus A-1 to A-9 green (commit). A-10 to A-18 become M1b. |
| M2 | 3, 4, 5 | 60 to 80 | Stop after Section 3 plus E-1 to E-4 green (commit). Section 4 plus RT-a to RT-g become M2b. |
| M3 | Tracking | 15 to 25 | Not split. |

Each milestone commits locally by explicit path (`git add <path>`; never `git add -A`). Run the pre-commit check (`git diff --cached --stat`) and stop on any unexpected file with more than 200 deletions. `PROGRESS.md` and `DECISIONS.md` may hold unrelated work by the Captain: stage only the hunks this contract names.

## Diff Reviewer properties (verify each; privacy-sensitive read path)

1. **Only access rows change.** No statement reachable from `lookup_by_id`, `lookup_by_agent`, `_lookup`, `_record_lookup_access` or the two pass-throughs writes `episode_archive` or any table other than `archive_access`. The only write is `_RECORD_LOOKUP_ACCESS_SQL`. A-16 compares the table before and after.
2. **The live store is never reached.** The pass-throughs and the route reference no `_collection`, `_fts_db`, participant index, activation tracker, eviction audit or `_get_store_write_lock()` (E-2, E-3).
3. **No unaudited read.** Every record returned is one whose access row was inserted by the same `_record_lookup_access` transaction, and that transaction committed before the method returned. On any exception the transaction is rolled back and nothing is returned. Each returned record has exactly one access row: one INSERT per decoded record, with ids unique by D4.
4. **Erased or replaced rows are withdrawn.** The INSERT's `EXISTS` names the id, the hash **and** the payload bytes the lookup decoded. A row deleted or replaced after the read gets no access row and is not returned. ERASE still deletes the access rows by requested id (`erase()` unchanged, `:474`).
5. **Bounded.** The limit is 1 to 200, enforced by the route (422) and by the archive (`ValueError`), never clamped. The SQL has `LIMIT limit + 1`. At most `limit` rows are decoded.
6. **Unavailability is typed.** No archive (absent, failed or stopped) raises `EpisodeArchiveUnavailable` and the route answers 503. No path returns an empty 200 for an archive that is not open.
7. **Authorization.** The route carries `Depends(require_crew_scope)`. Its first statement refuses 403 when `auth.crew_scope_token` is empty, before `episodic_memory` is read. It is the only new route. `/forget` is byte-for-byte unchanged.
8. **(d) by contract.** Lookup reads take no lock. `_record_lookup_access` holds `_write_lock` for its whole transaction, calls no other lock-taking method and never references `EpisodicMemory` or the store lock. `_archive_records` (`episodic.py:2612-2637`: no await is added between `collection.get` at `:2619` and `archive.archive` at `:2631`), `archive()`, `_present()`, `record_access()`, `erase()`, `stop()` and every existing read method are unchanged. There is no second connection or pool. A lookup that holds `_write_lock` only queues an eviction's `archive()` and an ERASE's `erase()` behind it in FIFO order, so S1's argument (an eviction that read a live row first reaches the archive lock first) still holds. S1 rows AL1 to AL4, E9m and X1 must stay killed.
9. **Schema.** The only schema change is one `CREATE INDEX IF NOT EXISTS`. `ARCHIVE_SCHEMA_VERSION` stays 1. No column, backfill or migration is added.
10. **Default recall is unchanged.** S1 property 1's recall methods still never touch the archive. The only callers of `lookup_archived_*` are in `routers/security.py` (grep), and the only callers of `lookup_by_*` are the two pass-throughs. S1's `test_golden_recall_is_identical_under_archive_and_delete` and its RC mutant stay green and killed.
11. **No agent-facing surface.** No tool, agent, Counselor, guided reminiscence or dream code references `lookup_archived_*`, `lookup_by_*` or `/archive/lookup`.
12. **The response carries only the matched archived rows.** It carries the fields in D9 for the rows the lookup recorded and nothing else: no live data and no other episode.
13. **The logs carry no content.** No log line in the new code contains `document` or `metadata` values. Ids and counts are allowed.
14. **Nothing else changes.** `config/system.yaml`, `config.py`, `knowledge/erasure.py`, `dreaming.py` and `startup/` are unchanged.

**Consumer that must accept the change:** the Captain's HTTP client calling `POST /api/security/archive/lookup` with `Authorization: Bearer <crew_scope_token>` on a ship whose archive holds S1-era rows (the file S1 created, `user_version` 1, no agent index until the first S2a start). The AD-754 route `POST /api/security/forget` must then erase the episode **and** the lookup's access rows (RT-g).

## Mutation table (campaign of record: none yet; whoever runs it records the base tree and the sha256 of each pinned file and of both new test files)

Every SEARCH is the stripped post-build line, with exactly one match in the named file (count it first: zero or more than one is INERT, not killed). Run the unmodified baseline first, mutate in place with a `.mutbak` sibling, restore in `finally`, and treat a timeout as INVALID. Run each row against the test file that holds its killer.

| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| N1 | `src/probos/cognitive/episode_archive.py` | `ON episode_archive(agent_id, episode_timestamp);` | `ON episode_archive(reason);` | A-1, A-18 |
| N2 | `src/probos/cognitive/episode_archive.py` | `"(b.archived_at > a.archived_at OR (b.archived_at = a.archived_at AND b.content_hash < a.content_hash)))"` | `"(0))"` | A-5 |
| N3 | `src/probos/cognitive/episode_archive.py` | `"(b.archived_at > a.archived_at OR (b.archived_at = a.archived_at AND b.content_hash < a.content_hash)))"` | `"(b.archived_at < a.archived_at OR (b.archived_at = a.archived_at AND b.content_hash < a.content_hash)))"` | A-5 |
| N4 | `src/probos/cognitive/episode_archive.py` | `"WHERE a.agent_id = ? AND a.episode_timestamp >= ? AND a.episode_timestamp < ? "` | `"WHERE a.agent_id = ? AND a.episode_timestamp > ? AND a.episode_timestamp <= ? "` | A-6 |
| N5 | `src/probos/cognitive/episode_archive.py` | `"ORDER BY a.episode_timestamp DESC, a.episode_id DESC LIMIT ?"` | `"ORDER BY a.episode_timestamp ASC, a.episode_id ASC LIMIT ?"` | A-6, A-7 |
| N6 | `src/probos/cognitive/episode_archive.py` | `"WHERE EXISTS (SELECT 1 FROM episode_archive WHERE episode_id = ? AND content_hash = ? AND payload = ?)"` | `"WHERE 1 OR EXISTS (SELECT 1 FROM episode_archive WHERE episode_id = ? AND content_hash = ? AND payload = ?)"` | A-10 |
| N7 | `src/probos/cognitive/episode_archive.py` | `"WHERE EXISTS (SELECT 1 FROM episode_archive WHERE episode_id = ? AND content_hash = ? AND payload = ?)"` | `"WHERE EXISTS (SELECT 1 FROM episode_archive WHERE episode_id = ? AND content_hash = ? AND (payload = ? OR 1))"` | A-11 |
| N8 | `src/probos/cognitive/episode_archive.py` | `if cursor.rowcount == 1:` | `if True:` | A-10, A-11 |
| N9 | `src/probos/cognitive/episode_archive.py` | `await db.commit()  # AD-1340 S2a: no lookup returns a record before its access row is committed` | `pass` | A-3 |
| N10 | `src/probos/cognitive/episode_archive.py` | `await _rollback_quietly(db)  # AD-1340 S2a: no access row of a failed lookup survives` | `pass` | A-12 |
| N11 | `src/probos/cognitive/episode_archive.py` | `async with self._write_lock:  # AD-1340 S2a: a lookup's access rows commit alone, after their rows are re-checked` | `async with asyncio.Lock():  # AD-1340 S2a mutant N11` | A-10, A-11, A-19 |
| N12 | `src/probos/cognitive/episode_archive.py` | `continue  # AD-1340 S2a: one bad row never hides the others in a lookup` | `raise` | A-9 |
| N13 | `src/probos/cognitive/episode_archive.py` | `undecodable=undecodable,` | `undecodable=0,` | A-9 |
| N14 | `src/probos/cognitive/episode_archive.py` | `truncated = len(rows) > limit` | `truncated = False` | A-7 |
| N15 | `src/probos/cognitive/episode_archive.py` | `for row in rows[:limit]:` | `for row in rows:` | A-7 |
| N16 | `src/probos/cognitive/episode_archive.py` | `if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= LOOKUP_MAX_LIMIT:` | `if False:` | A-7 |
| N17 | `src/probos/cognitive/episode_archive.py` | `LOOKUP_PURPOSE = "lookup"` | `LOOKUP_PURPOSE = "restore"` | A-3 |
| N18 | `src/probos/cognitive/episode_archive.py` | `withdrawn=len(decoded) - len(episodes),` | `withdrawn=0,` | A-10 |
| N19 | `src/probos/cognitive/episode_archive.py` | `cursor = await db.execute(_RECORD_LOOKUP_ACCESS_SQL, (eid, now, accessor, LOOKUP_PURPOSE, eid, chash, payload))` | `cursor = await db.execute(_RECORD_LOOKUP_ACCESS_SQL, (eid, now, "unknown", LOOKUP_PURPOSE, eid, chash, payload))` | A-3, RT-c |
| N20 | `src/probos/cognitive/episodic.py` | `raise EpisodeArchiveUnavailable("episode_archive_failed_to_open")` | `pass` | E-4 |
| N21 | `src/probos/cognitive/episodic.py` | `raise EpisodeArchiveUnavailable("episode_archive_not_open")  # AD-1340 S2a: no archive is never an empty result` | `return None` | E-4 |
| N22 | `src/probos/cognitive/episodic.py` | `return await self._archive_for_lookup().lookup_by_id(episode_id, accessor=accessor)` | `return self._collection.get(ids=[episode_id]) and await self._archive_for_lookup().lookup_by_id(episode_id, accessor=accessor)` | E-2 |
| N23 | `src/probos/routers/security.py` | `if not runtime.config.auth.crew_scope_token:  # AD-1340 S2a: never serve archived episodes through an open gate` | `if False:` | RT-a |
| N24 | `src/probos/routers/security.py` | `@router.post("/archive/lookup", dependencies=[Depends(require_crew_scope)])` | `@router.post("/archive/lookup")` | RT-b |
| N25 | `src/probos/routers/security.py` | `except EpisodeArchiveUnavailable as exc:` | `except LookupError as exc:` | RT-f |
| N26 | `src/probos/cognitive/episode_archive.py` | `self.lookups = EpisodeArchiveLookups(self._require_open, self._write_lock)` | `self.lookups = EpisodeArchiveLookups(self._require_open, asyncio.Lock())` | A-10, A-11, A-19 |
| N27 | `src/probos/cognitive/episode_archive.py` | `self.lookups = EpisodeArchiveLookups(self._require_open, self._write_lock)` | `self.lookups = EpisodeArchiveLookups(lambda: self._db, self._write_lock)` | A-14 |

**Checked by hand, like S1's WH rows.** **WH6** moves the `_record_lookup_access(...)` call and the `episodes = ...` filter **below** a `return` of all decoded records, so the lookup returns before auditing; A-3 and A-12 must fail. **WH7** dedents the `for item, payload in decoded:` loop and the commit out of `async with self._write_lock:`; **A-19** must fail (A-10 cannot: Amendment A1.1). **WH7b** dedents only `await db.commit()` out of the lock; A-19 must fail as well.

**S1 rows to re-run on the S2a tree.** S2a edits `episode_archive.py`, so all 17 S1 rows pinned to it are re-run against `tests/test_ad1340_s1_archive_store.py`: P1, P2, P3, C1, H1, S1, S2 (two anchors, by hand), X1, I2, I3, Q1, Q2, Q3 and AL1 to AL4. From `episodic.py`, RC and O1 are re-run against `test_ad1340_s1_eviction.py`, E1m against `test_ad1340_s1_erasure.py` and E9m against `test_ad1340_s1_restore_reset.py`; these are the default-recall, erase and (d) rows. The other S1 `episodic.py` rows are carried forward with their recorded kills. S2a only adds lines there (one import block and three methods), so an appended method cannot revive a killed mutant. The runner's count step must still find exactly one match for each of their anchors. A new line that duplicated an S1 anchor would make it INERT, so the S2a code above was written with distinct comments. S1 rows pinned to `erasure.py`, `memory_probes.py`, `__main__.py` and `startup/cognitive_services.py` are unaffected, because those files are unchanged.

## What this does NOT change

- No restore caller, no change to `restore_from_archive`, and none of S1's prerequisites (a) to (c) (S2b).
- No cue index, no FTS5 table in the archive and no cue lookup (S2c).
- No agent-facing consumer: no tool, no guided reminiscence, no Counselor and no dream step (S2d).
- No doctor or SIF figures (S3), no consolidation gate (S4) and no expiry (S5).
- `/api/security/forget`, `ErasureManager`, `_erase_ids`, `erase()` and F-129 / F-130 (recorded on #1523). The lookup reports a corrupt row as `undecodable`, which is the Captain's diagnostic for F-129. It does not repair erase-by-id of such a row.
- `get_records`, `get_versions`, `archived_keys`, `iter_records` and `record_access`.
- `config/system.yaml`, `config.py` and `AuthConfig` (no new field; the token stays the Captain's to set).
- The live-episode routes (`routers/agents.py:3853-3876`) and the HXI.

## Tracking (M3)

- `DECISIONS.md`: add `### AD-1340 S2a -- The Captain's audited lookup of archived episodes, by id and by primary agent and time (2026-10-17, #1568)` **directly after** the AD-1340 S1 entry's last line (`- Contract \`prompts/ad-1340-s1-archive-and-erase.md\`.`). Write one bullet each for: the scope (slice S2a of S2a to S2d; no new number); D1 and D2 (the index, no column, no backfill, version 1, the rollback path); D3 and D4 (primary agent only; latest version); D5 and D6 (read, decode, then one conditional transaction; withdrawn and undecodable; linearisation with ERASE); D7 to D11 (the route, the token refusal and the residual, no flag, shapes, errors, `archive_access` as the only audit); the mutation campaign of record (base tree, sha256s, a result and killer for each mutant, and the S1 rows re-run); and the contract path.
- `PROGRESS.md`: one paragraph at the top, above the BF-902 entry, in the format of `PROGRESS.md:3-5`: AD-1340 S2a built, the route path, the token requirement, the test count, and "#1568 stays open".
- AD ledger: `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py`, then `--check` (`tests/test_ad1184_ad_ledger.py`).
- No roadmap edit (as S1: `docs/development/` carries no AD-1340 line).

## Acceptance criteria

1. M1 and M2 focused gates are green with `-n 0 -p no:randomly`, and `probos.__file__` resolves inside this worktree.
2. The four `tests/test_ad1340_s1_*.py` files, `tests/test_bf902_fts_reconciliation.py` and `tests/test_ad1025b_path_anchoring.py` are green, with no assertion edited or weakened.
3. `scripts/check_architecture_principles.py --check` and `scripts/check_store_registry.py --check` exit 0 with the files staged.
4. Every N row and both WH rows are KILLED, and the 21 S1 rows re-run are KILLED, in one campaign of record copied into `DECISIONS.md`. None is INERT or INVALID.
5. RT-g crosses Step 12's call, then the archive, then the lookup route, then the AD-754 route, then nothing left, in ONE test through the real app with real stores.
6. With no crew-scope token configured, the route answers 403 and writes nothing (RT-a).
7. `config/system.yaml` is untouched and no new config field exists.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Prior Art and Blind Spots (2026-10-17)

**Internal.**
- AD-1339's decision (optimize, never delete) and #1568's acceptance line define the lookup as deliberate and recorded.
- S1 D1 to D9 and Amendments R2 and R3 (`prompts/ad-1340-s1-archive-and-erase.md:1342-1378`) supply the lock order, "reads take no lock" and the (d) argument; this contract keeps all three.
- The AD-1196 A-0 / AD-731a-1 rule (`routers/identity.py:10-12`, `routers/federation_attachments.py:10-12`) supplies the 403 without a token.
- AD-722b-1 (`routers/auth.py:1-14`) supplies the single-secret limit stated in D8.
- BF-868's under-erase rule is why D11 keeps the lookup's trace inside the erasable store.
- `docs/research/` has no note on audited reads of an archive. I searched it for `archival|access log|read audit`, and the hits are about Letta's self-editing memory and activation-log sizes.

**External (four searches; date used 2026-10-17).**
- Letta's archival-memory listing pages per agent with `limit`, `before`/`after` id cursors and an `asc`/`desc` order ([Letta archival export](https://docs.letta.com/guides/agents/archival-export), [list_passages schema](https://glama.ai/mcp/servers/oculairmedia/Letta-MCP-server/tools/list_passages)). **Adopted:** a bounded limit and newest first. **Deferred:** a cursor, since `truncated` plus a narrower range is enough for a Captain's review.
- SQLite `secure_delete=ON` (not `FAST`) zeroes deleted cell content, including freelist pages, and its WAL caveat does not apply to a rollback-journal file ([antonz.org](https://antonz.org/sqlite-secure-delete/), [sqlite.org check-in](https://www.sqlite.org/src/info/38978ce65b280bb7)). **Adopted:** A-17 proves empirically that no index entry is left in the file bytes, because no source spells out index pages.
- Read-access logging and NIST AU-5 leave the response to an audit failure as a policy choice, and one design guide recommends asynchronous audit writes ([NIST AU-5 summary](https://www.upguard.com/compliance/nist-sp-800-53/au/au-5.md), [read access logging](https://patents.google.com/patent/US8788533)). **Rejected for this path:** asynchronous audit. A privacy-sensitive read fails closed, so the audit commit comes before the data is released (D5).

**Reference projects.** Overdue on 2026-10-17 and relevant to memory: Memvid (last reviewed 2026-04-05) and the AI Meets Brain memory survey (2026-04-12). I considered both and deferred them, because neither addresses audited operator reads. Letta (2026-10-17) was already current and was checked again here. Its row could add "AD-1340 S2a, `prompts/ad-1340-s2a-archive-lookup.md` (paged archival listing; limit and order adopted)". This contract does not edit `reference-projects.md`, and the orchestrator may apply that row in its next docs change.

**Blind spots named (in scope unless marked deferred).**
- Unlocked reads can see another writer's uncommitted rows on the shared connection (handled: D5's conditional INSERT).
- A callsign is not an agent id, so a Captain who types "Worf" gets nothing. Deferred: resolving callsigns. The response's `agent_match` and D3's documentation state the rule.
- Filtering on `archived_at` ("what was pruned last night") is deferred to S3's visibility work. Each record carries `archived_at`.
- A metadata value that JSON cannot serialise (NaN) would fail the response after the access row committed. That is an over-audit, never an under-audit, so it is accepted and recorded here.
- A cancelled lookup can leave pending access rows that the next writer commits. That is an over-record, as S1 R3 accepted.
- A newer version archived concurrently under a new hash leaves the older version still valid, so the lookup returns it. Reach is none in S2a, which has no restore caller.

## Verified Against Codebase (2026-10-17, base `76c9507405fd04d47da48df7f70ee072fe006754`)

```
git rev-parse HEAD
  76c9507405fd04d47da48df7f70ee072fe006754
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py
  git log --all subjects AD-1340; GitHub issue titles (all states) AD-1342; prompts/ad-*.md AD-1340
  CEILING: AD-1342 (from: GitHub issue titles (all states)); NEXT: AD-1343  -- no number allocated by S2a
Read src/probos/cognitive/episode_archive.py (whole, 479 lines)
  17-21: import asyncio / json / logging / time / zlib     (no math)
  33-49: __all__
  54: ARCHIVE_SCHEMA_VERSION = 1
  62: _SQL_CHUNK = 500
  66-89: _SCHEMA; 70: agent_id TEXT NOT NULL; 71: episode_timestamp REAL NOT NULL; 87-88: idx_archive_access_episode
  138-144: primary_agent_id -- first of agent_ids_json, else "unknown"
  147-151: _episode_timestamp
  172-174: archive_ref property (insertion point for the result types)
  236-237: class docstring "S2 adds the recorded lookups (by agent and time, by cue)."
  252: self._write_lock = asyncio.Lock()
  264-268: PRAGMA secure_delete=ON, verified == 1
  269-275: user_version in (0, ARCHIVE_SCHEMA_VERSION), executescript(_SCHEMA)
  288-291: _require_open -> EpisodeArchiveUnavailable("episode_archive_not_open")
  317-320: row tuple writes primary_agent_id(record.metadata), _episode_timestamp(record.metadata)
  356-373: get_records -- no lock; 371: archived_at > current[0]
  436-448: iter_records -- skip undecodable, 444: "continue  # one bad row never hides the rows after it"
  450-462: record_access -- async with self._write_lock, one INSERT, one commit
  464-479: erase -- 473: DELETE FROM episode_archive; 474: DELETE FROM archive_access
grep -n "_archive_state" src/probos/cognitive/episodic.py
  1367: self._archive_state = "absent"  # "absent" | "open" | "failed"
  1682: self._archive_state = "absent"   (stop)
  2588: self._archive_state = "failed"
grep -n "from probos.cognitive.episode_archive import" src/probos/cognitive/episodic.py
  27-38: ARCHIVE_FILENAME, EVICTION_MODES, ArchiveRecord, EpisodeArchive, ... resolve_disposition
Read src/probos/cognitive/episodic.py 1528-1539, 1648-1683, 2560-2639, 2845-2933
  1534-1536: archive_available
  1586 (grep "db_dir = "): db_dir = Path(self.db_path).parent
  1655: await self._start_episode_archive(db_dir)
  2593-2599: _archive_or_none -- None for "absent", raises for "failed"
  2612-2637: _archive_records; 2619: self._collection.get(...); 2631: committed = await archive.archive(...)
  2849-2865: get_archived_metadata_versions
  2867-2891: iter_archived_episodes; 2891: raise EpisodeArchiveIntegrityError(f"episode_archive_rows_unrehydratable:...")
  2893: async def restore_from_archive; 2912: store write lock; 2922: archive.record_access(..., purpose="restore")
grep -n "ordered = \[by_id" src/probos/cognitive/episodic.py
  2293: ordered = [by_id[eid] for eid in episode_ids if eid in by_id]     (S1 RC anchor, unchanged)
Read src/probos/routers/security.py (whole, 89 lines)
  8-16: imports and the `router` object (prefix `/api/security`)
  60-64: @router.post("/forget") ... runtime: Any = Depends(get_runtime)   -- no auth dependency
  84-89: the forget response dict (SEARCH anchor of 4b)
Read src/probos/routers/auth.py (whole, 111 lines)
  41-75: require_crew_scope; 57-59: empty token -> return (pass-through); 401 details at 71, 75
grep -n "add_middleware|@app\.middleware" src/probos/api.py
  184: app.add_middleware(   (185-189: CORSMiddleware, HXI origins only)
grep -n "security|include_router" src/probos/api.py
  256, 301: security router included; 329: app.include_router(r.router)
grep -n "^def create_app" src/probos/api.py
  111: def create_app(runtime: Any) -> FastAPI:
grep -n "def get_runtime" src/probos/routers/deps.py
  15-17: return request.app.state.runtime
grep -n "require_crew_scope" src/probos/routers   (selection)
  approval_authority.py:145: @router.get("/state", dependencies=[Depends(require_crew_scope)])
grep -n "identity_keys_require_token|crew_scope_token" src/probos/routers
  identity.py:163-164: if not runtime.config.auth.crew_scope_token: raise HTTPException(status_code=403, detail=_TOKEN_REQUIRED)
  federation_attachments.py:10-12 (docstring rule), 110: if not runtime.config.auth.crew_scope_token:
Read src/probos/config.py 2926-2939
  AuthConfig.crew_scope_token default ""
grep -n "crew_scope_token|^auth:" config/
  system.yaml:987-988: auth: crew_scope_token: ''
Read src/probos/routers/agents.py 3853-3876
  GET /{agent_id}/chat/history returns live episode user_input with Depends(get_runtime) only
grep -n "journal_mode|WAL|def connect" src/probos/storage/sqlite_factory.py
  16: async def connect(...)   (no journal_mode)
Read tests/test_ad1340_s1_archive_store.py 1-133, grep 727-756, 802-827
  51-85 helpers; 99-143 _FaultyConnection/_FaultyFactory; 727-744 _GatedCommit; 750-756 _arm_failing_write (TEMP trigger)
  603-604: "EvictionDisposition" in __all__; all(hasattr(...)) -- membership only
Read tests/test_ad1340_s1_eviction.py 40-114; grep ARCHIVE_FILENAME
  62-72 _episode; 88-113 _memory rig; 134: root / "chroma" / ARCHIVE_FILENAME
grep -n test names in tests/
  test_ad1340_s1_eviction.py:222 test_golden_recall_is_identical_under_archive_and_delete
  test_ad1340_s1_restore_reset.py:708 test_an_archive_eviction_inside_an_erase_is_erased_too
  test_ad1340_s1_archive_store.py:802, 836; test_ad1340_s1_erasure.py:237
Read tests/test_camera_frame_origin.py 20-59  -- create_app(MagicMock runtime with real SystemConfig)
grep -l "ASGITransport" tests/   -- 5 files (httpx available)
grep -n "--check|_OUTPUT|_SNAPSHOT" scripts/gen_ad_ledger.py
  28, 72-73: docs/development/open-ads-report.md, ad-ledger-snapshot.json
Read prompts/ad-1340-s1-archive-and-erase.md 1342-1521 (R2, R3, mutation table, Diff Reviewer properties)
Read DECISIONS.md 54-86 (BF-902, AD-1340 S1); PROGRESS.md 1-12
```

## Absence Verified (2026-10-17)

```
1. CLAIM: nothing outside routers/security.py calls /api/security/* (no HXI, no CLI)
   RUN:   Grep "security/forget|api/security" over the repository (node_modules excluded)
   FOUND: DECISIONS.md:82 (prose), src/probos/routers/security.py:16, prompts/archive/ad-754-yeo-data-hardening-baseline.md:215
   HOLDS: yes

2. CLAIM: no route at /archive/lookup and none of S2a's new symbols exist
   RUN:   Grep "ArchivedEpisode|ArchiveLookupResult|LOOKUP_MAX_LIMIT|idx_episode_archive_agent_time|_record_lookup_access|_archive_for_lookup" (repo)
          Grep "forget_episode\(|archive/lookup|lookup_archived|lookup_by_agent|lookup_by_id" src/
   FOUND: none; erasure.py:98, 183 and security.py:73 (forget_episode only)
   HOLDS: yes

3. CLAIM: the app has no authentication middleware
   RUN:   Grep "add_middleware|@app\.middleware" src/probos/api.py
   FOUND: api.py:184 only (CORSMiddleware, 185-189)
   HOLDS: yes

4. CLAIM: the archive connection is not in WAL mode
   RUN:   Grep "journal_mode|WAL" src/probos/storage/sqlite_factory.py; Read episode_archive.py whole
   FOUND: none in either
   HOLDS: yes

5. CLAIM: only the four S1 test files reference the archive
   RUN:   Grep -l "episode_archive|EpisodeArchive|archive_available|_archive_state" tests/
   FOUND: test_ad1340_s1_erasure.py, test_ad1340_s1_eviction.py, test_ad1340_s1_restore_reset.py, test_ad1340_s1_archive_store.py
   HOLDS: yes (test_bf902_fts_reconciliation.py: 0 occurrences of episode_archive|archive_access)

6. CLAIM: no test pins the archive's index set or its __all__ exactly
   RUN:   Grep "sqlite_master|index_list|_SCHEMA|idx_archive_access_episode" tests/test_ad1340*.py; Read archive_store 603-604
   FOUND: test_ad1340_s1_erasure.py:207 (type = 'table' only); 603-604 membership and hasattr only
   HOLDS: yes

7. CLAIM: only test_ad1025b imports routers.security
   RUN:   Grep -l "from probos.routers import security|routers\.security|probos\.routers\.security" (repo)
   FOUND: tests/test_ad1025b_path_anchoring.py; src/probos/security/storage_declarations.py:22 (a lifecycle_owner string)
   HOLDS: yes
```

## Not verified

- Live row counts: none needed. No live database was opened.
- `cursor.rowcount` for `INSERT ... SELECT ... WHERE EXISTS`, binding `math.inf`, and the exact `EXPLAIN QUERY PLAN` text on the venv's SQLite. These are standard sqlite3 behaviour. A-3, A-6 and A-18 check them, and if any differs the Builder stops and reports.
- The full route inventory of other tests (`tests/test_ad1198_peer_http_routes.py:49-54` builds its map by path, and adding a route should not affect it). The broad gate covers it.

## Builder briefs

### Brief M1 (archive; effort high)
Build Sections 1 and 2 exactly. Run the M1 focused gate. Do not edit any existing method of `EpisodeArchive`. Commit `src/probos/cognitive/episode_archive.py` and `tests/test_ad1340_s2a_archive_lookup.py` by path. If you pass about 150 calls, cut as the milestone table says.

### Brief M2 (pass-throughs and route; effort high)
Build Sections 3 to 5 exactly. Route tests use the real app through `httpx.ASGITransport` in the test's loop, a real `EpisodicMemory` and the real `/forget`. Nothing mocks the lookup. Run the M2 focused gate and the two checks. Commit `src/probos/cognitive/episodic.py`, `src/probos/routers/security.py` and `tests/test_ad1340_s2a_lookup_route.py` by path.

### Brief M3 (trackers; effort medium)
Edit `DECISIONS.md` and `PROGRESS.md` as Tracking says, staging only those hunks. Regenerate the ledger and run `--check` and `tests/test_ad1184_ad_ledger.py`. The mutation campaign of record is run on the frozen candidate by the orchestrator or reviewer, and its result goes into the DECISIONS entry before the gate.

---

## Amendment A1 (Architect, after M1; recorded by the orchestrator, 2026-10-18)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-17, consult session `37bf6694`.

**Why.** The M1 Builder stopped on a hard stop: mutant WH7 survived all 18 tests. It also found that `scripts/check_architecture_principles.py --check` exits 1 (17 direct methods on `EpisodeArchive`, limit 15) and that N13's anchor matched twice. The orchestrator replicated the WH7 survival independently on a scratch tree (18 passed). The Architect decided all three. The mutation-table rows N11 and N13 and the WH7 sentence above were edited in place to match, and N26 and N27 are new (A1.5). **Where this amendment and Sections 1 to 5 differ, this amendment wins.**

### A1.1 WH7 is a real gap. Add A-19.
**Reason:** under WH7 (the 11 lines of `_record_lookup_access` dedented out of the lock), A-10 cannot see the change. Its lookup still waits at the `async with` line, so the timeline matches the pristine code. The property that breaks is "another writer's rollback never takes the lookup's pending access rows" (Diff Reviewer property 3). Only a writer that runs while the access INSERT is still uncommitted can show that.

Copy S1's helpers into `tests/test_ad1340_s2a_archive_lookup.py` verbatim (local copies, no cross-module import): `_GatedCommit` (`tests/test_ad1340_s1_archive_store.py:727-744`), `_MARKED` (`:747`) and `_arm_failing_write` (`:750-756`). `_cancel_pending` is already local. Then append:

```python
# --- A-19: a failing archive() never rolls back a lookup's access row ---------------------------------------------


async def test_a_failing_archive_write_never_rolls_back_a_lookups_access_row(tmp_path: Path) -> None:
    path = tmp_path / "episode_archive.db"
    subject = _record(1)
    tasks: list[asyncio.Task[Any]] = []
    archive = EpisodeArchive(str(path))
    async with _started(archive):
        assert await archive.archive([subject], reason="capacity") == frozenset({subject.episode_id})
        assert _count(path, "archive_access", subject.episode_id) == 0  # premise: no access row yet
        await _arm_failing_write(archive)
        real = archive._db  # test-only private access
        archive._db = gate = _GatedCommit(real)
        try:
            lookup_task = asyncio.create_task(archive.lookups.lookup_by_id(subject.episode_id, accessor="test"))
            tasks.append(lookup_task)
            await asyncio.wait_for(gate.entered.wait(), timeout=5)  # the access row is inserted, not committed
            archive_task = asyncio.create_task(archive.archive([_MARKED], reason="capacity"))
            tasks.append(archive_task)
            done, _ = await asyncio.wait({archive_task}, timeout=0.3)
            assert not done  # the archive waits for the lookup's transaction
            gate.release.set()
            finished, _ = await asyncio.wait({lookup_task, archive_task}, timeout=5)
            assert finished == {lookup_task, archive_task}, "a task never finished after the release"

            result = lookup_task.result()
            assert _ids(result) == [subject.episode_id]
            assert (result.undecodable, result.withdrawn, result.truncated) == (0, 0, False)
            with pytest.raises(sqlite3.IntegrityError, match="injected write failure"):
                archive_task.result()
            assert _rows(
                path, "SELECT purpose FROM archive_access WHERE episode_id = ?", (subject.episode_id,),
            ) == [("lookup",)]  # exactly one committed row: the returned record was audited
            assert _count(path, "episode_archive", _MARKED.episode_id) == 0
        finally:
            gate.release.set()
            archive._db = real
            await _cancel_pending(tasks)
```

- **The by-agent form needs no separate test.** Both forms reach the lock through the one shared call in `_lookup`, and the lock is taken only in `_record_lookup_access`. A mutant cannot drop the lock for one form only.
- **Hand-check rows.** WH7's killer changes from A-10 to **A-19**. Add **WH7b**: dedent only `await db.commit()` out of the lock. A-19 must also fail; A-10 cannot catch WH7b either.
- **Killers.** N11's killers become A-10, A-11 and A-19.
- **Tests summary.** 30 tests: A-1 to A-19 in the archive file, plus E-1 to E-4 and RT-a to RT-g in the route file. Add A-19 to the concurrency list.

### A1.2 SRP: a same-module companion class `EpisodeArchiveLookups` (option D)
| Option | Correct | Safe | Compatible | Architectural fit | Reversible | Validation cost | Survives S2c and S2d |
|---|---|---|---|---|---|---|---|
| **D (chosen)** | yes | yes | yes | a real split: storage and mutations vs the audited query surface | yes | low: method bodies byte-identical, no N-row anchor changes | yes: the class is back to 13 methods; S2c's cue lookup joins the companion |
| A (a baseline row) | yes | yes | yes | poor: a new class enters debt, and the baseline freezes triggers, not magnitude, so S2c could grow it ungated | yes | lowest | no: the check is blind to this class from then on |
| B (module functions) | yes | yes | yes | poor: methods in disguise, the same family as the checker's stated bound 7 | yes | low | no: every S2c lookup repeats the dodge |
| C (a new module) | yes | yes | yes | needs a public lock-and-connection API on `EpisodeArchive` (methods back on the class) or private access across modules | yes | medium | partly |

**Reason:** every one of the 92 baseline rows was frozen debt from `AD-1270h` when the checker shipped, and DECISIONS records the design as "new violations fail immediately". A new class should fix the cause, not join the baseline. D injects the archive's own bound `_require_open` and its `_write_lock` object, under the same attribute names, so the moved bodies do not change by one byte, and A-10's `archive._write_lock` (and the `_GatedCommit` swap of `archive._db`) still reach the lookup.

**Code (Section 1, applied to the built file):**
1. Imports: `from collections.abc import AsyncIterator, Callable, Iterable, Iterator, Mapping, Sequence`.
2. Add `"EpisodeArchiveLookups",` to `__all__`, after `"EpisodeArchiveIntegrityError",`. S1's `__all__` membership check stays true.
3. Insert this class after `_close_quietly`, before `class EpisodeArchive`:
```python
class EpisodeArchiveLookups:
    """AD-1340 S2a: the audited lookup surface of one ``EpisodeArchive`` (``archive.lookups``); S2c adds cue.

    Holds no connection and no lock of its own: it uses the archive's ``_require_open`` and the SAME
    ``_write_lock`` object, so every lookup's access transaction is serialised with the archive's writers.
    Constructed only by ``EpisodeArchive.__init__``.
    """

    def __init__(self, require_open: Callable[[], Any], write_lock: asyncio.Lock) -> None:
        self._require_open = require_open
        self._write_lock = write_lock
```
   Then **cut** the four methods `lookup_by_id`, `lookup_by_agent`, `_lookup` and `_record_lookup_access` out of `EpisodeArchive` and paste them **verbatim** into this class body. Both are at class level, so the indentation does not change.
4. In `EpisodeArchive.__init__`, add a line after `self._write_lock = asyncio.Lock()`: `self.lookups = EpisodeArchiveLookups(self._require_open, self._write_lock)  # AD-1340 S2a: the audited read surface`.
5. Change the `EpisodeArchive` class docstring line that says "S2a adds the recorded lookups by id and by primary agent and time (S2c adds cue)." to: "S2a's recorded lookups live on ``lookups`` (``EpisodeArchiveLookups``); S2c adds cue."

**Section 3:**
- 3a: add `EpisodeArchiveLookups,` to the import, in sorted position.
- 3b: `_archive_for_lookup` becomes `-> EpisodeArchiveLookups`, and its `return archive` becomes `return archive.lookups`. The two pass-through lines `return await self._archive_for_lookup().lookup_by_...` are **unchanged**, so N20, N21 and N22 stay valid.
- 3b docstrings: `EpisodeArchive.lookup_by_id` and `.lookup_by_agent` become `EpisodeArchiveLookups.lookup_by_id` and `.lookup_by_agent`.

**Tests:** replace every `archive.lookup_by_` with `archive.lookups.lookup_by_` in the S2a archive test file (all call sites are on a variable named `archive`). Change A-2, A-3, A-6, A-7 and A-8 in the Section 2 table to say `lookups.lookup_by_*`.

**Mutation table:** no SEARCH text changes for N1 to N19 other than N13 (A1.3), because every body is byte-identical, and N11's `async with self._write_lock:  # AD-1340 S2a: ...` is still unique. WH6 and WH7 now refer to the methods on `EpisodeArchiveLookups`.

**Gate:** `scripts/check_architecture_principles.py --check` (exit 0, `docs/development/architecture-baseline.yaml` unchanged) is part of the **M1** checks as well as M2.

### A1.3 N13: change the mutant's target; no source edit
**Reason:** changing the target leaves Section 1 byte-identical. A-9's `undecodable == 1` kills it just as it killed the original mutant. **Table:** N13's SEARCH is `undecodable=undecodable,` and its REPLACE is `undecodable=0,`, killed by A-9 (that text has one match: the result construction in `_lookup`; S1's `iter_records` never builds a result). Other anchors, all unique after the build: `ON episode_archive(agent_id, episode_timestamp);`, `truncated = len(rows) > limit`, `for row in rows[:limit]:`, `if cursor.rowcount == 1:`. S1's AL1 to AL4 each carry their own R3 comment, and S1's I3 `if undecodable:` stays single. Anyone running the campaign must still count every anchor before mutating, as the table header says.

### A1.4 Diff Reviewer properties
- **1 and 10:** read `EpisodeArchiveLookups.lookup_by_id`, `.lookup_by_agent`, `._lookup`, `._record_lookup_access`.
- **8 (add):** `EpisodeArchiveLookups` holds the archive's own `_write_lock` object and its bound `_require_open`, and nothing else. It opens no connection, creates no lock, and is constructed only in `EpisodeArchive.__init__`. A-10 (the lookup blocks on `archive._write_lock`) and A-19 prove the lock is shared.
- **3 (add):** no other writer's rollback can remove a lookup's uncommitted access rows (A-19).
- **15 (new):** `EpisodeArchive` keeps S1's 13 direct methods. `check_architecture_principles.py --check` exits 0, and `architecture-baseline.yaml` is unchanged.

### A1.5 Orchestrator additions (decided inside the Architect's amendment, not new design)
- **N26 and N27** are new table rows for the constructor wiring that D introduces: N26 gives the companion its own lock (A-10, A-11 and A-19 must fail), N27 gives it a `require_open` that never raises (A-14 must fail, because a closed archive would then surface as an `AttributeError` instead of `EpisodeArchiveUnavailable`). Both SEARCH texts occur once in `EpisodeArchive.__init__`.
- **M1b (the repair milestone):** apply A1.2 to the built `episode_archive.py`, rename the test call sites, add A-19 with its three copied helpers, run the M1 gate and both checks. Expected: 19 passed in the new file, the architecture check at exit 0. Verify the moved method bodies are byte-identical to Section 1h's text (a script compares them).
- **The orchestrator runs the campaign of record** on the frozen candidate: N1 to N27 (the table), WH6, WH7 and WH7b by hand, and the 21 S1 rows.

