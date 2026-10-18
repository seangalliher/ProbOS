# AD-1340 S2b (#1568): restore's prerequisites, then the Captain's restore route

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-18

**Status:** ready to build. **Base:** `origin/main` at `cf9dc8cd` (PR #1590: AD-1340 S2a #1589 and BF-905 #1587 merged). **AD:** AD-1340, slice S2b; no new AD or BF number. **Depends on:** S1, BF-902, S2a (all merged). **Ships as two PRs** (Decision D1): **Part 1** (M1 to M4) settles S1's prerequisites (a) to (c), F-140 and restore's own stop race, with no Captain-facing caller; **Part 2** (M5, M6) adds `POST /api/security/archive/restore`. Each part has its own milestones, focused gates, mutation partition and broad gate, and each is mergeable alone. **Estimated tests:** Part 1: 21 new test functions in three files, one S1 test replaced and one S1 helper amended; Part 2: 12 new test functions in one file.

One-line summary: eviction holds the store write lock per chunk and never deletes a record that changed after its archive snapshot, every unlocked archive read is typed under a `stop()`, restore puts back exactly the version a lookup shows, refuses at capacity and is all or nothing; then one crew-scope Captain route calls it.

---

## Problem

S1 left restore internal and named four prerequisites for its first caller (`DECISIONS.md`, "AD-1340 S1", Amendment R2, "S2 prerequisites"); S2a settled (d) by contract. The sequencing decision on #1568 (comment 6244376956) makes S2b the first restore caller and the slice that settles (a) to (c). The post-S2a consult adds F-140 (#1523, comment 6246177530) and restore's own `stop()` race. Verified on this tree:

- **(a) Eviction takes no store lock.** `_get_store_write_lock()` is referenced only by `_reconcile_fts_index` (`episodic.py:1719`), `store()` (`:1944`), `_erase_ids` (`:2826`) and `restore_from_archive` (`:2988`). `_evict` (`:3023-3047`), the non-ERASE branch of `evict_by_ids` (`:3073-3094`), `_remove_from_live` (`:2752-2801`) and `_archive_records` (`:2655-2680`) take none (Absence Verified 2). So an eviction can delete a live row and clean its sidecars between a restore's awaits, or run inside a `store()` tail (BF-669 releases the lock before the FTS and participant inserts, `:2142-2167`) and leave index rows for an archived id.
- **(b) Restore ignores capacity.** `restore_from_archive` (`:2969-3021`) never reads `count()`; a restored episode keeps its original timestamp, so it is the oldest live episode.
- **(c) A metadata update between the snapshot and the delete is lost.** `_archive_records` snapshots the live record (`:2662`), awaits `archive()` (`:2674`), and `_remove_from_live` then awaits the audit (`:2789`) and deletes (`:2798`) without re-reading. Metadata updaters do not take the store lock (for example the `upsert` at `:2605`).
- **F-140.** `get_records` (`episode_archive.py:543-560`), `archived_keys` (`:562-578`), `get_versions` (`:580-599`) and `iter_records` (`:601-635`) await an unlocked read with no openness re-check; only S2a's `_lookup` has the guard (`:354-363`, `:380-381`). `EpisodicMemory.stop()` clears `_collection` first (`episodic.py:1663`), takes no store lock, and closes the archive at `:1681`.
- **Restore's own race.** `restore_from_archive` re-reads `self._collection` after awaits (`:2994`, `:2999`), so a `stop()` mid-restore is an `AttributeError` on `None`, and its FTS, participant and activation inserts (`:3000-3020`) run after the live add and are swallowed at DEBUG: a stop or a failing insert leaves a live episode missing from its indexes.
- **Tie order.** `get_records` keeps the first row on an `archived_at` tie (`:558`, "unspecified"); S2a's lookup applies `_LATEST_VERSION` (`:111-114`: greatest `archived_at`, then smallest `content_hash`).
- **No caller.** `restore_from_archive` has no production caller (Absence Verified 1).

## Solution overview

1. **M1 (Part 1), archive reads.** One module helper, `_guarded_read`, in `episode_archive.py`; every unlocked archive read goes through it (the four service reads and S2a's lookup). `get_records` applies `_LATEST_VERSION` in SQL and decodes only the latest row.
2. **M2 (Part 1), eviction.** `_evict` and the non-ERASE `evict_by_ids` hold the store lock per chunk of at most 100 ids, from the archive snapshot to the sidecar cleanup; `_remove_from_live` skips ids whose `store()` tail is pending, re-reads just before the delete (no await between), never deletes an empty id list, and types a `stop()`. S1's archive-eviction-inside-an-erase test is replaced (it would now deadlock by design).
3. **M3 (Part 1), restore.** Capacity refusal inside the lock; an `accessor` keyword; `EpisodeArchiveNotFound`; sidecar rows written BEFORE the live add, the add last with no await after the final `stop()` check; any failure, stop or cancellation undoes the rows (reaching closed stores through their files).
4. **M4 (Part 1), trackers.**
5. **M5 (Part 2), the route.** `POST /api/security/archive/restore`, S2a's D8 protection and A2 guard copied exactly.
6. **M6 (Part 2), trackers.**

## Decisions (decided by the Architect under Delegated AD Execution Mode; the orchestrator records each on #1568; the Captain may overrule any afterwards)

### D1. Two PRs, the prerequisites first
Part 1 (M1 to M4) changes `episode_archive.py`, `episodic.py` and tests, and adds no caller. Part 2 (M5, M6) adds the route and its tests. **Reason:** no Captain-facing restore exists before every prerequisite is merged and gated, and each part's mutation campaign stays in one partition set (Part 1 about 60 rows, Part 2 about 10). Rejected: one PR (one review would carry two unrelated risk classes; a round-three brake on the route would hold the lock fixes back); three PRs (M1 alone has no consumer change worth a gate run).

### D2. Prerequisite (a): where the store lock goes, and chunking
- `_evict` chooses its victims outside the lock (as today: `count()` and one `get`, both synchronous), then removes them in chunks of `_EVICTION_LOCK_CHUNK = 100`, each inside `async with lock:` around the whole `_remove_from_live` call: archive snapshot, `archive()`, audit, re-read, delete, sidecar cleanup. The non-ERASE branch of `evict_by_ids` does the same per chunk of the requested ids, with its `get` inside the lock.
- Not inside `_remove_from_live`: `_erase_ids` calls it while holding the lock (`:2826`, `:2833`), and the lock is non-reentrant.
- **No deadlock with `store()`:** `store()`'s locked section ends at `:2140`; `_evict()` is called at `:2192`, outside it (Absence Verified 3). `_evict` takes the lock only when `count > max_episodes`, so the existing tests that hold the lock while stores run under budget (`test_episodic.py:331`, `test_ad541b_reconsolidation.py:648`, `:1028`, `:1114`) are unaffected.
- **Store tails.** For archive and delete, `_remove_from_live` first drops every id with a pending `store()` tail (`_get_store_tails()`, registered inside the lock at `:2140`): it stays live this round and the next eviction takes it. Without this the lock alone cannot stop an eviction from cleaning the sidecars before a BF-669 tail writes them. ERASE is unchanged: it already waits for tails (R3).
- **Chunk size 100:** a chunk is one archive transaction, one audit batch, two synchronous ChromaDB calls and three sidecar deletes; a `store()` waits for one chunk at most. Rejected: one lock for the whole batch (a 25 % aggressive prune of 100,000 holds every `store()` for the whole prune); per-id locking (one archive commit per id).

**One lock order: the store lock, then the archive `_write_lock`.** Every holder, enumerated:

| Holder | Store lock | Archive `_write_lock`, taken inside |
|---|---|---|
| `store()` (`:1945`) | primary decision and add | never |
| `_reconcile_fts_index` (BF-902, `:1719-1721`) | per page | never (it never reads the archive) |
| `_erase_ids` (`:2826`) | live and archive phases | `archive.erase()` (`archived_keys` runs inside it) |
| `restore_from_archive` (`:2988`) | the whole restore | `record_access()` |
| `_evict` (S2b) | per chunk | `archive()` through `_archive_records` |
| `evict_by_ids`, non-ERASE (S2b) | per chunk | the same |
| S2a lookups | never | `_record_lookup_access` |
| `EpisodeArchive.stop()` / `EpisodicMemory.stop()` | never | `archive.stop()` |

`episode_archive.py` never references the store lock or `EpisodicMemory` except in two docstrings (Absence Verified 5), so no archive-lock holder can wait on the store lock. No store-lock holder calls a function that takes the store lock: `_remove_from_live`, `_archive_records`, `_cleanup_sidecars` and the new `_write_restore_sidecars` take none, and the production callers of `evict_by_ids` hold nothing (`dreaming.py:1602`, `:1638`; the ERASE callers `erasure.py:125`, `memory_probes.py:81`).

### D3. S1 condition (d) holds by construction
With eviction under the store lock, no ERASE, restore or `store()` add can run between `_archive_records`' snapshot and `archive()` acquiring the archive lock, whatever is awaited there. S1's FIFO argument is no longer load-bearing. Consequence: S1's `test_an_archive_eviction_inside_an_erase_is_erased_too` (`test_ad1340_s1_restore_reset.py:708-735`) awaits an eviction inside the erase's locked section and would now deadlock; it is **replaced** (Section 4) by a test that starts the eviction there, proves it waits on the store lock, and then finds nothing to evict.

### D4. Prerequisite (c): re-read just before the delete
In archive mode, after `archive()` and the audit, `_remove_from_live` re-reads the ids (`documents`, `metadatas`) and keeps for deletion only those whose live record still encodes, by `encode_payload`, to exactly the bytes of the snapshot it archived; the re-read is synchronous and the delete is its next statement, so no await separates them. A changed id stays live, is counted at WARNING, and its next eviction archives the current payload (S1 R1's upsert). A failed re-read keeps every id live (growth, never loss). **The audit stays before the delete** (S1 D3 order; `test_crash_after_archive_commit_then_retry_is_idempotent` pins two audit rows for a failed delete and its retry): an audit row is the record of an eviction attempt, as it already is when the delete fails. Rejected: re-reading before the audit (the audit's await reopens the window); moving the audit after the delete (changes S1 D3 and that test for no protection gain); making every metadata updater take the store lock (touches recall-adjacent writers).

Delete mode and ERASE do not re-read: delete mode keeps no copy whose fidelity matters, and ERASE removes every version anyway. Both keep today's call sequence (`test_delete_mode_is_todays_behaviour` pins it).

### D5. Prerequisite (b): restore at capacity, and the next Step 12
Inside the lock, after the live-id check and before the access row, restore refuses with `EpisodeArchiveConflict("episode_archive_restore_over_capacity")` when `collection.count() >= max_episodes`; a refusal writes nothing. Live reach about zero (`max_episodes` 100,000, `config.py:833`).

**Measured, by the code (test R-7 pins it):** a restored episode has one activation access (`archive_restore`); ACT-R activation is `ln(age^-0.5)` (`activation_tracker.py:126-147`, `decay_d` 0.5 at `config/system.yaml:252`), which falls below the aggressive threshold 0.0 one second after the restore and below the standard −2.0 after about 55 s. Its timestamp is the original one, so it is past both age cutoffs. **The next Step 12 prunes it again, and it is re-archived byte-equal under the same key: never lost.** Decided: **by design, documented, not prevented.** Restore puts an episode back under the same rules as every other live episode; if the crew recalls it, its activation rises; if not, it decays back to the archive, which is the Captain's "forgetting is recall decay, never deletion" decision (2026-10-16). The route docstring and the DECISIONS entry say so. Rejected: a restore grace period or pin (new state that Step 12, the doctor and ERASE must all know); synthetic activation accesses (falsifies the activation log); a fresh timestamp (breaks byte-equal, rejected in the sequencing decision). Likewise, a restore at `count == max_episodes - 1` makes the next over-budget `store()` evict the oldest live episode, which is usually the restored one; re-archived, never lost.

### D6. F-140: one guard for every unlocked archive read
A module function `_guarded_read(require_open, sql, params)` in `episode_archive.py` (not a method: `EpisodeArchive` stays at 13 direct methods, and the lookups companion, which holds only `require_open`, can use it too). It reads, re-checks openness when the read fails (closed: `EpisodeArchiveUnavailable` chained to the driver error; open: the original error keeps its type), and re-checks once more after a successful read, with no await after it, so rows read across a `stop()` are never answered. `get_records`, `archived_keys`, `get_versions`, `iter_records` and `EpisodeArchiveLookups._lookup` all use it; `_lookup`'s own A3 block and its empty-answer re-check are folded in (the post-read re-check covers the empty path, and decoding is synchronous). Reads stay unlocked (R3). `_present` and `erase()`'s `archived_keys` run under `_write_lock`, which `stop()` also takes, so no stop can interleave them. S2a rows N33 to N37 are retired with the lines they named; H1 to H5 replace them, and S2a's own A-20, A-21, A-22 and RT-h stay their killers.

### D7. `get_records` takes the lookup's version
`get_records` adds `AND {_LATEST_VERSION}` to its SQL (aliasing the table `a`), so the version a restore puts back and the version a lookup shows come from one predicate, and it decodes only that row (an undecodable OLDER version no longer blocks the restore of a good latest one; an undecodable latest still raises `EpisodeArchiveIntegrityError`). The S1 pins on `get_records` (input order, folding, absent and empty ids, a corrupt single version raising: `test_ad1340_s1_archive_store.py:486-510`) hold unchanged.

### D8. Restore is all or nothing, and a `stop()` is typed
- **Bind once:** `collection = self._collection` at entry; the state check is `self._archive_state != "open" or archive is None or collection is None` → `EpisodeArchiveUnavailable("episode_archive_unavailable")` (S1's code, now also for a failed archive, which used to surface `episode_archive_unavailable_for_erase` through `_archive_or_none`).
- **Order inside the lock:** `get_records` → re-check the collection → not found → live-id check → capacity → `record_access(accessor=...)` (audit before action, unchanged) → `_write_restore_sidecars` (clear any stale rows for the id, which is not live, then FTS, participant and activation rows; its LAST statement re-checks the collection) → `collection.add` on the very next statement. The live add is the commit point, so no interleaving leaves an episode live without its index rows.
- **On a failed insert, a `stop()` or a cancellation** the writer clears the rows it wrote with `_cleanup_sidecars(ids, strict=True)` (which reaches a store whose handle `stop()` closed through its declared file, S1 R1), logs at WARNING if even that fails (an ERASE of the id clears the remainder), and raises: a cancellation re-raises; a `stop()` (the collection was replaced) raises `EpisodeArchiveUnavailable("episode_restore_interrupted_by_stop")`; any other failure raises `EpisodeArchiveError("episode_archive_restore_incomplete:<store>")`, `<store>` one of `episode_fts`, `participant_index`, `activation`. Nothing is live in any case. The `archive_access` row of an attempt that passed the refusals stays: it records that the archive was read for a restore, and ERASE removes it.
- **A store with no open handle** (feature off, failed start) is skipped, as `store()` skips it.
- **Rejected:** add first, then roll back the add on failure (a `stop()` between the add and the rollback leaves the live episode without its rows, and the rollback itself can fail); complete and report the missing rows (a live episode the keyword and participant channels cannot find, which BF-902's start-up pass does not repair: it removes orphans, it never adds rows).
- **Accessor:** `restore_from_archive(episode_id, *, accessor="episodic_memory")`; a blank accessor raises `ValueError("episode_archive_restore_accessor_invalid")` before anything. The default keeps S1's recorded accessor for internal and test callers (`test_ad1340_s1_restore_reset.py:127`, `:370`); the route passes `captain:/api/security/archive/restore`. Restore keeps its per-call `record_access(purpose="restore")` and never uses the lookups' batched path; restore is not added to `EpisodeArchiveLookups`.
- **Not found:** `EpisodeArchiveNotFound(EpisodeArchiveError, LookupError)`, new in `episode_archive.py`, so S1's `pytest.raises(LookupError, match="^episode_archive_not_found$")` (`:182`, `:487`) still holds and the route can map it without catching every `LookupError` (a `KeyError` bug must not become a 404).

### D9. A `stop()` inside eviction or ERASE is typed too
`_remove_from_live` re-reads `self._collection` after its awaits: `None` under ERASE raises `EpisodeErasureIncomplete("erasure_live_store_unavailable")` (the code `_erase_ids` already uses at `:2829`; today it is an `AttributeError` appended to its errors); `None` under archive or delete logs a WARNING and returns `[]` (archived ids stay live: a duplicate, never a loss, S1 D3). `_evict` returns at once on a stopped memory (today `assert self._collection`, `:3024`, can fire from `store()` after a stop during its tail). It never calls `delete` with an empty id list.

### D10. The route (Part 2)
- `POST /api/security/archive/restore`, next to `/archive/lookup`. A POST: it writes the live store and an audit row. The id stays out of the URL.
- **Protection, copied from S2a D8 and A2:** `dependencies=[Depends(require_crew_scope), Depends(_refuse_non_finite_numbers)]` (401 first, then the non-finite guard), and the handler's first statement refuses 403 `episode_archive_restore_requires_token` while `auth.crew_scope_token` is empty, before `episodic_memory` is read. No config flag (the closed default protects; S2a D8's reasoning).
- **Request:** `{"episode_id": str}` (1 to 256 characters), `extra="forbid"`.
- **Response 200:** `{"episode_id": "<id>", "restored": true}`. A 200 means the episode is live with every wired index row (D8); the version is the one the lookup route shows (D7). Nothing about sidecars is reported because nothing partial can exist.
- **Audit:** the `archive_access` row (accessor `captain:/api/security/archive/restore`, purpose `restore`) is the only audit owner, as S2a D11; no `AuditLog` entry (ERASE could not remove it). The route logs the id and the outcome at INFO or ERROR, never content.
- **Residual (stated as S2a D8 does):** with a token configured, anyone holding the one shared crew-scope token can restore; restore is a write, but every write it makes is undoable by ERASE or the next eviction, and it never deletes.

### D11. Error mapping (every error is `{"detail": code}`)
| Status | Detail | When |
|---|---|---|
| 401 | `require_crew_scope`'s codes | a token is configured and the request's is missing or wrong |
| 403 | `episode_archive_restore_requires_token` | no token configured; nothing is read |
| 422 | pydantic / `non_finite_number_in_body` | invalid body / a non-finite number anywhere in it (A2) |
| 404 | `episode_archive_not_found` | the id is not archived (`EpisodeArchiveNotFound`) |
| 409 | `episode_archive_restore_live_id` | the id is already live |
| 409 | `episode_archive_restore_over_capacity` | the live store is at `max_episodes` |
| 503 | `episodic_memory_unavailable` | `runtime.episodic_memory` is `None` |
| 503 | `episode_archive_unavailable` / `episode_archive_not_open` / `episode_restore_interrupted_by_stop` | no open archive or live store, or a `stop()` during the restore (`EpisodeArchiveUnavailable`) |
| 500 | `episode_archive_restore_incomplete:<store>` | a sidecar insert failed; undone, nothing live (ERROR log) |
| 500 | `episode_archive_payload_undecodable` (or another integrity code) | the latest archived row does not decode |
| 500 | `episode_archive_restore_failed` | any other exception (for example the access row could not be written); nothing live (ERROR log) |

---

## Section 0: Event types
None. S2b adds no `EventType`.

## Section 1 (M1): `src/probos/cognitive/episode_archive.py`

### 1a. `__all__`
SEARCH:
```python
    "EpisodeArchiveIntegrityError",
    "EpisodeArchiveLookups",
    "EpisodeArchiveUnavailable",
```
REPLACE:
```python
    "EpisodeArchiveIntegrityError",
    "EpisodeArchiveLookups",
    "EpisodeArchiveNotFound",
    "EpisodeArchiveUnavailable",
```

### 1b. The not-found type (after `EpisodeErasureIncomplete`)
SEARCH:
```python
class EpisodeErasureIncomplete(EpisodeArchiveError):
    """Erasure could not clear every copy of an episode."""
```
REPLACE:
```python
class EpisodeErasureIncomplete(EpisodeArchiveError):
    """Erasure could not clear every copy of an episode."""


class EpisodeArchiveNotFound(EpisodeArchiveError, LookupError):
    """AD-1340 S2b: a restore named an id the archive does not hold (still a ``LookupError``, as S1 raised)."""
```

### 1c. The guard (after `_close_quietly`)
SEARCH:
```python
async def _close_quietly(db: Any) -> None:
    try:
        await db.close()
    except Exception:
        logger.debug("AD-1340: archive close failed", exc_info=True)
```
REPLACE:
```python
async def _close_quietly(db: Any) -> None:
    try:
        await db.close()
    except Exception:
        logger.debug("AD-1340: archive close failed", exc_info=True)


async def _guarded_read(require_open: Callable[[], Any], sql: str, params: Sequence[Any]) -> list[Any]:
    """AD-1340 S2b (F-140): one unlocked archive read, typed if a stop() closed the archive under it.

    ``stop()`` clears the handle under ``_write_lock`` before it closes the connection, so a read that fails
    while the handle is gone failed because of that stop: it becomes ``EpisodeArchiveUnavailable``, chained to
    the driver error. A failure on an open archive keeps its own type. Rows read across a stop are never
    answered: the re-check after the read is the last statement, so no await follows it. Every unlocked
    archive read goes through here: the four service reads and the S2a lookups.
    """
    db = require_open()
    try:
        cursor = await db.execute(sql, params)  # AD-1340 S2b: an archive read takes no lock (R3)
        rows = list(await cursor.fetchall())
    except Exception as exc:  # AD-1340 S2b: did a stop() close the connection under the read?
        try:
            require_open()  # AD-1340 S2b: a stop() during the read is unavailability (F-140)
        except EpisodeArchiveUnavailable as closed:
            raise closed from exc
        raise  # AD-1340 S2b: any other read failure keeps its own type
    require_open()  # AD-1340 S2b: rows read across a stop() are never answered; no await follows
    return rows
```

### 1d. The lookup uses the guard (`EpisodeArchiveLookups._lookup`)
SEARCH:
```python
        db = self._require_open()
        try:
            cursor = await db.execute(sql, params)  # a read: no lock (R3); the locked INSERT below decides
            rows = await cursor.fetchall()
        except Exception as exc:  # AD-1340 S2a A3: did a stop() close the connection under the read?
            try:
                self._require_open()  # AD-1340 S2a A3: a stop() during the read is unavailability (D7)
            except EpisodeArchiveUnavailable as closed:
                raise closed from exc
            raise  # AD-1340 S2a A3: any other read failure keeps its own type
        truncated = len(rows) > limit
```
REPLACE:
```python
        rows = await _guarded_read(self._require_open, sql, params)  # a read: no lock (R3); the locked INSERT below decides
        truncated = len(rows) > limit
```
SEARCH:
```python
            decoded.append((item, bytes(payload)))
        if not decoded:
            self._require_open()  # AD-1340 S2a A3: an empty answer is given only while open; no await follows
        recorded = await self._record_lookup_access(decoded, accessor=accessor) if decoded else frozenset()
```
REPLACE:
```python
            decoded.append((item, bytes(payload)))
        recorded = await self._record_lookup_access(decoded, accessor=accessor) if decoded else frozenset()
```

### 1e. `get_records`: the lookup's version, through the guard
SEARCH:
```python
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
```
REPLACE:
```python
    async def get_records(self, episode_ids: Sequence[str]) -> list[ArchiveRecord]:
        """Service read (restore): the latest archived record per id, in input order.

        AD-1340 S2b: "latest" is the S2a lookup's own rule (``_LATEST_VERSION``: the greatest ``archived_at``; an
        exact tie keeps the smallest ``content_hash``), applied in SQL, so a restore puts back exactly the version
        a lookup showed. Only that row is decoded; an undecodable latest row raises ``EpisodeArchiveIntegrityError``.
        A stop() during the read raises ``EpisodeArchiveUnavailable``.
        """
        self._require_open()  # AD-1340 S2b: closed is unavailable, even for an empty request
        wanted = list(dict.fromkeys(eid for eid in episode_ids if eid))
        latest: dict[str, ArchiveRecord] = {}
        for chunk in _chunks(wanted, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            rows = await _guarded_read(
                self._require_open,  # AD-1340 S2b: get_records reads through the stop guard
                "SELECT a.episode_id, a.content_hash, a.payload_format, a.payload FROM episode_archive a "
                f"WHERE a.episode_id IN ({marks}) AND {_LATEST_VERSION}",
                chunk,
            )
            for episode_id, content_hash, payload_format, payload in rows:
                latest[episode_id] = decode_payload(episode_id, content_hash, payload_format, payload)
        return [latest[eid] for eid in wanted if eid in latest]
```

### 1f. `archived_keys` and `get_versions` through the guard
SEARCH:
```python
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
```
REPLACE:
```python
        Erasure audits from these columns, so a corrupt payload never blocks an erase.
        AD-1340 S2b: a stop() during the read raises ``EpisodeArchiveUnavailable``.
        """
        self._require_open()  # AD-1340 S2b: closed is unavailable, even for an empty request
        wanted = list(dict.fromkeys(eid for eid in episode_ids if eid))
        keys: list[tuple[str, str, Any, float]] = []
        for chunk in _chunks(wanted, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            rows = await _guarded_read(
                self._require_open,  # AD-1340 S2b: archived_keys reads through the stop guard
                "SELECT episode_id, content_hash, agent_id, episode_timestamp "
                f"FROM episode_archive WHERE episode_id IN ({marks})",
                chunk,
            )
            keys.extend(tuple(row) for row in rows)
        return keys
```
SEARCH:
```python
        Ordered by ``episode_id, archived_at, content_hash``. A row that cannot be
        decoded raises ``EpisodeArchiveIntegrityError``.
        """
        db = self._require_open()
        wanted = list(dict.fromkeys(eid for eid in episode_ids if eid))
        versions: list[ArchiveRecord] = []
        for chunk in _chunks(wanted, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            cursor = await db.execute(
                "SELECT episode_id, content_hash, payload_format, payload "
                f"FROM episode_archive WHERE episode_id IN ({marks}) "
                "ORDER BY episode_id, archived_at, content_hash",
                chunk,
            )
            for episode_id, content_hash, payload_format, payload in await cursor.fetchall():
                versions.append(decode_payload(episode_id, content_hash, payload_format, payload))
        return versions
```
REPLACE:
```python
        Ordered by ``episode_id, archived_at, content_hash``. A row that cannot be
        decoded raises ``EpisodeArchiveIntegrityError``. AD-1340 S2b: a stop() during
        the read raises ``EpisodeArchiveUnavailable``.
        """
        self._require_open()  # AD-1340 S2b: closed is unavailable, even for an empty request
        wanted = list(dict.fromkeys(eid for eid in episode_ids if eid))
        versions: list[ArchiveRecord] = []
        for chunk in _chunks(wanted, _SQL_CHUNK):
            marks = ",".join("?" * len(chunk))
            rows = await _guarded_read(
                self._require_open,  # AD-1340 S2b: get_versions reads through the stop guard
                "SELECT episode_id, content_hash, payload_format, payload "
                f"FROM episode_archive WHERE episode_id IN ({marks}) "
                "ORDER BY episode_id, archived_at, content_hash",
                chunk,
            )
            for episode_id, content_hash, payload_format, payload in rows:
                versions.append(decode_payload(episode_id, content_hash, payload_format, payload))
        return versions
```

### 1g. `iter_records` through the guard
SEARCH:
```python
        while True:
            db = self._require_open()
            cursor = await db.execute(
                "SELECT episode_id, content_hash, payload_format, payload FROM episode_archive "
                "WHERE (episode_id, content_hash) > (?, ?) ORDER BY episode_id, content_hash LIMIT ?",
                (last[0], last[1], page_size),
            )
            rows = await cursor.fetchall()
            if not rows:
```
REPLACE:
```python
        while True:
            rows = await _guarded_read(
                self._require_open,  # AD-1340 S2b: iter_records reads through the stop guard
                "SELECT episode_id, content_hash, payload_format, payload FROM episode_archive "
                "WHERE (episode_id, content_hash) > (?, ?) ORDER BY episode_id, content_hash LIMIT ?",
                (last[0], last[1], page_size),
            )
            if not rows:
```
**Counts after M1:** `EpisodeArchive` keeps 13 direct methods, `EpisodeArchiveLookups` 5; one module function added. `_present`, `archive()`, `record_access()`, `erase()`, `stop()` and `start()` are byte-identical.

## Section 2 (M1): `tests/test_ad1340_s2b_archive_reads.py` (new)

Real `EpisodeArchive` on `tmp_path`. Import `_record`, `_rows`, `_write`, `_count`, `_started`, `_GatedRead`, `_stop_at`, `_cancel_pending` and `NOT_OPEN` from `tests.test_ad1340_s2a_archive_lookup` (helpers only). Every test asserts its premise first; every wait is bounded (`asyncio.wait_for(..., 5)`).

- **B-1** `test_get_records_takes_the_lookup_version_on_a_tie_and_on_a_newer_row`: archive `_record(0, content_hash="1" * 64, marker="small")` and `_record(0, content_hash="2" * 64, marker="large")` (the `content_hash` key overrides the default); `_write` sets both `archived_at = 5000.0`. Premise: two rows for `ep-000`, equal `archived_at` (`_rows`). Assert `get_records(["ep-000"])` returns the `"1" * 64` record and `archive.lookups.lookup_by_id("ep-000", accessor="test")` returns the same `content_hash`. Then `_write` sets the `"2" * 64` row to `5001.0`: both now return `"2" * 64`. The ties are forced, never left to the clock.
- **B-2** `test_get_records_decodes_only_the_latest_version`: plant (raw `_write` INSERT, as `test_ad1340_s1_archive_store.py:500-505` does) a corrupt payload for `ep-000` under hash `"0" * 64` with `archived_at = 1.0`, beside a good row at `archived_at = 2.0`. Premise: `decode_payload` refuses the planted row. `get_records(["ep-000"])` returns the good record; after `_write` sets the corrupt row to `3.0`, it raises `EpisodeArchiveIntegrityError`.
- **B-3** `test_a_stop_during_each_service_read_raises_unavailable`, parametrized over `read` in `("get_records", "archived_keys", "get_versions", "iter_records")` and `point` in `("before_fetchall", "after_fetchall")` (8 cases): archive `_record(0)`; gate `archive._db` with `_GatedRead(archive._db, point)` (test-only); run the read as a task (`iter_records` drained in a comprehension); `_stop_at(archive, gate, task)`; expect `EpisodeArchiveUnavailable` matching `NOT_OPEN`. `before_fetchall`: premise `gate.raised` is an `Exception` and not an `EpisodeArchiveError`, then `caught.value.__cause__ is gate.raised`. `after_fetchall`: premise `gate.raised is None` and `len(gate.rows) == 1` (the read itself succeeded).
- **B-4** `test_a_service_read_failure_on_an_open_archive_keeps_its_type`: `_write(path, "DROP TABLE episode_archive")`; premise `archive.is_open`; each of the four reads raises `sqlite3.OperationalError` matching `no such table`; `archive.is_open` afterwards.
- **B-5** `test_service_reads_of_nothing_on_a_closed_archive_are_unavailable`: on a never-started archive, `get_records([])`, `archived_keys([])` and `get_versions([])` raise `EpisodeArchiveUnavailable` matching `NOT_OPEN`.

## Section 3 (M2): `src/probos/cognitive/episodic.py` (eviction)

### 3a. Import
SEARCH:
```python
    EpisodeArchiveUnavailable,
    EpisodeErasureIncomplete,
    primary_agent_id,
    resolve_disposition,
)
```
REPLACE:
```python
    EpisodeArchiveUnavailable,
    EpisodeErasureIncomplete,
    encode_payload,
    primary_agent_id,
    resolve_disposition,
)
```

### 3b. Constant
SEARCH:
```python
# BF-902: rows the start-up FTS reconciliation reads, checks against the live collection and deletes per page.
_FTS_RECONCILE_PAGE = 500
```
REPLACE:
```python
# BF-902: rows the start-up FTS reconciliation reads, checks against the live collection and deletes per page.
_FTS_RECONCILE_PAGE = 500
# AD-1340 S2b (a): the most ids one capacity or dream eviction removes inside one hold of the store write lock, so a
# large eviction never holds the lock across the whole batch and a store() waits for one chunk at most.
_EVICTION_LOCK_CHUNK = 100
```

### 3c. The pre-delete re-read (module function, before `_erase_store_file`)
SEARCH:
```python
async def _erase_store_file(kind: str, path: str | None, ids: list[str]) -> bool:
    """AD-1340 R1: ERASE through the sidecar's own class when no open handle is wired.
```
REPLACE:
```python
def _unchanged_since_archived(
    collection: Any, ids: list[str], archived: Mapping[str, ArchiveRecord],
) -> list[str]:
    """AD-1340 S2b (c): the ids whose live record still encodes to exactly the payload just archived.

    Synchronous on purpose: the caller deletes on its next statement, with no await in between, so no metadata
    update can land between this re-read and the delete. An id whose document or metadata changed after the
    archive snapshot stays live, and its next eviction archives the current payload (the R1 upsert). An id no
    longer live is not deleted again. A failed re-read keeps every id live: growth, never loss.
    """
    try:
        current = collection.get(ids=list(ids), include=["documents", "metadatas"])
    except Exception:
        logger.warning(
            "AD-1340 S2b: the re-read before an eviction delete failed; %d archived episode(s) stay live",
            len(ids), exc_info=True,
        )
        return []
    got_ids = list((current or {}).get("ids") or [])
    docs = list((current or {}).get("documents") or [])
    metas = _metadata_by_id(got_ids, (current or {}).get("metadatas"))
    unchanged: set[str] = set()
    for i, eid in enumerate(got_ids):
        snapshot = archived.get(eid)
        live = ArchiveRecord(episode_id=eid, document=(docs[i] if i < len(docs) else "") or "", metadata=metas[eid])
        try:
            same = snapshot is not None and encode_payload(live) == encode_payload(snapshot)
        except (TypeError, ValueError):
            same = False  # AD-1340 S2b (c): a record that no longer encodes is not the one archived
        if same:
            unchanged.add(eid)
    changed = len(set(got_ids) - unchanged)
    if changed:
        logger.warning(
            "AD-1340 S2b: %d episode(s) changed after their archive snapshot and stay live; "
            "their next eviction archives the change", changed,
        )
    return [eid for eid in ids if eid in unchanged]


async def _erase_store_file(kind: str, path: str | None, ids: list[str]) -> bool:
    """AD-1340 R1: ERASE through the sidecar's own class when no open handle is wired.
```

### 3d. `_archive_records` returns the snapshot it archived
SEARCH:
```python
    async def _archive_records(self, ids: list[str], reason: str) -> dict[str, str]:
        """Archive these live ids; return ``{id: archive_ref}`` for the committed ones."""
        archive = self._episode_archive
```
REPLACE:
```python
    async def _archive_records(self, ids: list[str], reason: str) -> dict[str, ArchiveRecord]:
        """Archive these live ids; return ``{id: the record archived}`` for the committed ones.

        AD-1340 S2b: every caller holds the store write lock, so no ERASE, restore or store() add runs between this
        live snapshot and ``archive()`` (S1 R3 condition (d) by construction), and ``_remove_from_live`` compares the
        live record with the returned snapshot just before it deletes (prerequisite (c)).
        """
        archive = self._episode_archive
```
SEARCH:
```python
        return {record.episode_id: record.archive_ref for record in records if record.episode_id in committed}
```
REPLACE:
```python
        return {record.episode_id: record for record in records if record.episode_id in committed}
```

### 3e. `_remove_from_live`: tails, the re-read, a typed stop
SEARCH:
```python
        Delete and erase: the same sequence without the archive step. Erase
        leaves the sidecars to ``_erase_ids``, which sweeps every requested id.
        """
        ids = list(candidate_ids)
        archive_refs: dict[str, str] = {}
        if outcome == DISPOSITION_ARCHIVED:
            committed = await self._archive_records(ids, reason)
            ids = [eid for eid in ids if eid in committed]
            if not ids:
                return []
            archive_refs = committed
```
REPLACE:
```python
        Delete and erase: the same sequence without the archive step. Erase
        leaves the sidecars to ``_erase_ids``, which sweeps every requested id.
        AD-1340 S2b: every caller holds the store write lock. Archive and delete
        skip an id whose store() tail is still writing its index rows (it stays
        live this round). Archive mode re-reads the records just before the
        delete and deletes only those still equal to the payload archived
        (prerequisite (c)). A stop() inside the sequence keeps the ids live;
        under ERASE it raises.
        """
        ids = list(candidate_ids)
        archive_refs: dict[str, str] = {}
        committed: dict[str, ArchiveRecord] = {}
        if outcome != DISPOSITION_ERASED:  # AD-1340 S2b (a): ERASE waits for store tails itself (R3)
            pending_tails = self._get_store_tails()
            ids = [eid for eid in ids if eid not in pending_tails]  # AD-1340 S2b (a): a store() still indexing an id keeps it live
            if not ids:
                return []
        if outcome == DISPOSITION_ARCHIVED:
            committed = await self._archive_records(ids, reason)
            ids = [eid for eid in ids if eid in committed]
            if not ids:
                return []
            archive_refs = {eid: record.archive_ref for eid, record in committed.items()}
```
SEARCH:
```python
            except Exception as exc:
                logger.warning("Eviction audit failed: %s", exc)
        self._collection.delete(ids=list(ids))
        if outcome != DISPOSITION_ERASED:  # ERASE: _erase_ids sweeps every requested id, strictly
```
REPLACE:
```python
            except Exception as exc:
                logger.warning("Eviction audit failed: %s", exc)
        collection = self._collection  # AD-1340 S2b: re-read after the awaits above; a stop() clears it
        if collection is None:  # AD-1340 S2b: a stop() inside an eviction or an erase
            if outcome == DISPOSITION_ERASED:
                raise EpisodeErasureIncomplete("erasure_live_store_unavailable")  # AD-1340 S2b: a stop() inside the erase
            logger.warning(
                "AD-1340 S2b: the live store stopped during eviction; %d episode(s) stay live", len(ids),
            )
            return []
        if outcome == DISPOSITION_ARCHIVED:
            ids = _unchanged_since_archived(collection, ids, committed)  # AD-1340 S2b (c): no await between this re-read and the delete
            if not ids:
                return []  # AD-1340 S2b (c): never a delete with no ids
        collection.delete(ids=list(ids))
        if outcome != DISPOSITION_ERASED:  # ERASE: _erase_ids sweeps every requested id, strictly
```
(The first SEARCH's `except Exception as exc:` / `logger.warning("Eviction audit failed: %s", exc)` pair occurs twice in the file, in `_remove_from_live` and `_erase_ids`; the four-line block with `self._collection.delete(ids=list(ids))` occurs once. Count the whole block.)

### 3f. `_evict` per chunk under the lock
SEARCH:
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
REPLACE:
```python
    async def _evict(self) -> None:
        """Capacity eviction: archive (or delete) the oldest live episodes beyond ``max_episodes``.

        AD-1340 S2b (a): the victims are chosen outside the store write lock, then removed in chunks of at most
        ``_EVICTION_LOCK_CHUNK`` ids, each inside the lock from its archive snapshot to its sidecar cleanup, so no
        restore, ERASE or store() add interleaves a chunk and a store() waits for one chunk at most. store() calls
        this after its own locked section, so the non-reentrant lock is free here. A victim that left the live
        store before its chunk ran is not found again.
        """
        collection = self._collection
        if collection is None:  # AD-1340 S2b: a stopped memory evicts nothing
            return
        count = collection.count()
        if count > self.max_episodes:
            excess = count - self.max_episodes
            # Get oldest episodes by timestamp
            result = collection.get(
                include=["metadatas"],
            )
            if result and result["ids"] and result["metadatas"]:
                # Sort by timestamp ascending (oldest first)
                paired = list(zip(result["ids"], result["metadatas"]))
                paired.sort(key=lambda x: x[1].get("timestamp", 0))
                to_evict = paired[:excess]
                ids_to_delete = [p[0] for p in to_evict]
                metadata_by_id = {eid: dict(meta or {}) for eid, meta in to_evict}
                outcome = resolve_disposition("capacity", None, self._eviction_disposition_mode)
                lock = self._get_store_write_lock()
                for start in range(0, len(ids_to_delete), _EVICTION_LOCK_CHUNK):
                    chunk = ids_to_delete[start:start + _EVICTION_LOCK_CHUNK]
                    async with lock:  # AD-1340 S2b (a): capacity eviction holds the store lock for one chunk
                        # AD-1340: archive (or delete) through the one removal sequence.
                        await self._remove_from_live(
                            chunk,
                            {eid: metadata_by_id[eid] for eid in chunk},
                            reason="capacity",
                            process="_evict",
                            details=f"batch of {len(chunk)}, budget={self.max_episodes}",
                            outcome=outcome,
                        )
```

### 3g. The non-ERASE `evict_by_ids` per chunk under the lock
SEARCH:
```python
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
```
REPLACE:
```python
        evicted = 0
        ids = list(episode_ids)
        lock = self._get_store_write_lock()
        try:
            for start in range(0, len(ids), _EVICTION_LOCK_CHUNK):
                chunk = ids[start:start + _EVICTION_LOCK_CHUNK]
                async with lock:  # AD-1340 S2b (a): a dream eviction holds the store lock for one chunk
                    result = self._collection.get(ids=chunk, include=["metadatas"])
                    if not result or not result["ids"]:
                        continue
                    valid_ids = result["ids"]
                    removed = await self._remove_from_live(
                        valid_ids,
                        _metadata_by_id(valid_ids, result["metadatas"]),
                        reason=reason,
                        process="evict_by_ids",
                        details=f"batch of {len(valid_ids)}, reason={reason}",
                        outcome=outcome,
                    )
                    evicted += len(removed)
        except Exception as e:
            logger.debug("evict_by_ids failed: %s", e)
```
A `stop()` between chunks makes the next `self._collection.get` fail; the existing broad `except` returns what was evicted so far (log-and-degrade, as today). The docstring of `evict_by_ids` gains one line: "AD-1340 S2b: the non-ERASE path holds the store write lock per chunk of `_EVICTION_LOCK_CHUNK` ids; never call it while holding that lock."

## Section 4 (M2): tests for eviction

### 4a. `tests/test_ad1340_s1_restore_reset.py`: replace S1 R3's T17 (deliberate; D3)
The old body awaits `em.evict_by_ids` inside the erase's locked section; with D2 that deadlocks by design. Its intent (S1 condition (d)) now holds by construction, and this replacement pins the new contract. E9m keeps its recorded first killer, `test_restore_then_erase_clears_every_copy`.

SEARCH (`:708-735`, to the end of the file):
```python
async def test_an_archive_eviction_inside_an_erase_is_erased_too(tmp_path: Path) -> None:
    """AD-1340 R3: an archive row written after the erase read the archive keys is still deleted (S2 prerequisite d)."""
    tasks: list[asyncio.Task[Any]] = []
    held: dict[str, Any] = {}
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        original = em._eviction_audit.record_batch_eviction  # test-only private access

        async def _archive_inside_the_erase(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("disposition") == DISPOSITION_ERASED and "evicted" not in held:
                held["evicted"] = await em.evict_by_ids([_SUBJECT], reason="activation_decay")
                held["archive_rows_inside_erase"] = len(_archive_rows(rig.root))
            return await original(*args, **kwargs)

        em._eviction_audit.record_batch_eviction = _archive_inside_the_erase
        erase_task = _start_erase(em, tasks)
        try:
            finished, _ = await asyncio.wait({erase_task}, timeout=10)
            assert finished, "the erase never finished"
            assert held["evicted"] == 1  # premise: the archive eviction ran inside the erase
            assert held["archive_rows_inside_erase"] == 1  # premise: it wrote an archive row
            assert await erase_task == 1
            assert await _traces(em, rig.root, _SUBJECT) == _GONE
            assert _archive_rows(rig.root) == []
        finally:
            del em._eviction_audit.record_batch_eviction  # back to the class method
            await _cancel_all(tasks)
```

REPLACE:
```python
class _ObservedLock(asyncio.Lock):
    """AD-1340 S2b: the store write lock, observed. Counts acquisitions; ``contended`` resolves when an acquire finds it held."""

    def __init__(self) -> None:
        super().__init__()
        self.acquisitions = 0
        self.contended = asyncio.get_running_loop().create_future()

    async def acquire(self) -> bool:
        if self.locked() and not self.contended.done():
            self.contended.set_result(None)
        acquired = await super().acquire()
        self.acquisitions += 1
        return acquired


async def test_an_eviction_started_inside_an_erase_waits_then_finds_nothing(tmp_path: Path) -> None:
    """AD-1340 S2b (a): an eviction started inside an erase waits for the store lock, then finds the id gone.

    Replaces S1 R3's archive-eviction-inside-an-erase test. Eviction now holds the store write lock, so it can no
    longer run inside an erase's locked phases (awaiting it there would deadlock): S1's condition (d) holds by
    construction instead of by the archive lock's FIFO order.
    """
    tasks: list[asyncio.Task[Any]] = []
    held: dict[str, Any] = {}
    async with _memory(tmp_path, "archive") as rig:
        em = rig.em
        observed = _ObservedLock()
        em._store_write_lock = observed  # test-only private access: the store write lock, observed
        assert await em.store(_episode(0)) is EpisodeStoreOutcome.STORED
        original = em._eviction_audit.record_batch_eviction  # test-only private access

        async def _evict_inside_the_erase(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("disposition") == DISPOSITION_ERASED and "evict_task" not in held:
                evict_task = asyncio.create_task(em.evict_by_ids([_SUBJECT], reason="activation_decay"))
                tasks.append(evict_task)
                held["evict_task"] = evict_task
                await asyncio.wait_for(asyncio.shield(observed.contended), timeout=5)  # it reached the store lock
                held["blocked_inside_erase"] = not evict_task.done()
                held["archive_rows_inside_erase"] = len(_archive_rows(rig.root))
            return await original(*args, **kwargs)

        em._eviction_audit.record_batch_eviction = _evict_inside_the_erase
        erase_task = _start_erase(em, tasks)
        try:
            finished, _ = await asyncio.wait({erase_task}, timeout=10)
            assert finished, "the erase never finished"
            assert held["blocked_inside_erase"] is True  # premise: the eviction waited on the store lock inside the erase
            assert held["archive_rows_inside_erase"] == 0  # and archived nothing there
            assert await erase_task == 1
            assert await asyncio.wait_for(held["evict_task"], timeout=5) == 0  # then it found nothing live to evict
            assert await _traces(em, rig.root, _SUBJECT) == _GONE
            assert _archive_rows(rig.root) == []
        finally:
            del em._eviction_audit.record_batch_eviction  # back to the class method
            await _cancel_all(tasks)
```

### 4b. `tests/test_ad1340_s2b_eviction_locking.py` (new)
The real rig of S1: import `_memory`, `_episode`, `_ids`, `_raw`, `_query`, `_archive_rows`, `_audit_rows`, `_sidecar_counts`, `_record_collection` from `tests.test_ad1340_s1_eviction`; `_ObservedLock`, `_FtsTailProxy`, `_canonical`, `_SUBJECT`, `_cancel_all` from `tests.test_ad1340_s1_restore_reset`; `_traces`, `_GONE` from `tests.test_ad1340_s1_erasure`. Monkeypatch the chunk with `monkeypatch.setattr("probos.cognitive.episodic._EVICTION_LOCK_CHUNK", 2)` where named. Install `_ObservedLock` as `em._store_write_lock` (test-only) before the measured call. Interleavings use gates (a future or an event each test creates and resolves), never sleeps; every wait is bounded.

- **L-1** `test_capacity_eviction_holds_the_store_lock_per_chunk` (archive mode, chunk 2): store `_episode(0..5)` under `max_episodes=100`, then set `em.max_episodes = 1` (test-only). Wrap `em._episode_archive.archive` and `rig.participants.delete_episodes` so each records `observed.locked()` when called. (i) The test acquires `observed` itself, starts `em._evict()` as a task, awaits `observed.contended` (bounded); premise: the task is not done and `_archive_rows` is empty; then it releases. (ii) The task completes; assert 5 archived, `ep-005` live; acquisitions by the eviction (the counter minus the test's own) `== 3`; audit `details` in rowid order `["batch of 2, budget=1", "batch of 2, budget=1", "batch of 1, budget=1"]`; every recorded `locked()` is `True`.
- **L-2** `test_dream_eviction_holds_the_store_lock_per_chunk`: the same for `em.evict_by_ids(_ids(5), reason="activation_decay")` (returns 5; 3 acquisitions; every archive and participant cleanup call made under the lock).
- **L-4** `test_eviction_keeps_an_episode_whose_metadata_changed_after_its_snapshot`, parametrized `hook` in `("archive", "audit")`: store `ep-000` and `ep-001`; take `before = dict(_raw(em, ["ep-000"])["metadatas"][0])`; build `changed = {**before, "valid_until": 1234567890.0}`; wrap `em._episode_archive.archive` (hook "archive", after the original returns) or assign `em._eviction_audit.record_batch_eviction` (hook "audit", before calling the original; `del` it in `finally`) to apply `em._collection.update(ids=["ep-000"], metadatas=[changed])` once (the gated stand-in for an unlocked metadata updater). Premise: the hook ran once. `evict_by_ids(["ep-000", "ep-001"], reason="activation_decay") == 1`; `ep-001` gone and archived; `ep-000` live with `valid_until == 1234567890.0`; its archive row decodes to `before` (the snapshot); a WARNING contains "changed after their archive snapshot". Second `evict_by_ids(["ep-000"]) == 1`; still one archive row for `ep-000`, now decoding to `changed`; `restore_from_archive("ep-000")` brings back `changed` (`_canonical` compare).
- **L-4b** `test_an_eviction_whose_every_id_changed_deletes_nothing`: one id, hook "archive"; install `_record_collection(em)` before the call; `evict_by_ids == 0`; `"delete"` is not among `proxy.calls`; live with the change.
- **L-6** `test_eviction_keeps_an_id_whose_store_tail_is_pending`, parametrized `mode` in `("archive", "delete")`: wrap `em._fts_db` in `_FtsTailProxy` whose `before_insert` resolves an "entered" future and awaits a "release" future; start `em.store(_episode(0))`; await "entered". Premise: `ep-000` is live and `"ep-000" in em._get_store_tails()` (test-only). `evict_by_ids(["ep-000"], reason="activation_decay") == 0`; still live; no archive or audit row. Release; the store returns `STORED`; then `evict_by_ids == 1`, `_sidecar_counts == {"fts": 0, "activation": 0, "participants": 0}`, and (archive mode) one archive row.
- **L-7** `test_a_stop_during_capacity_eviction_keeps_the_rest_live` (archive mode, chunk 1): store 4 episodes, `em.max_episodes = 1`; assign `em._eviction_audit.record_batch_eviction` so its first call awaits `em.stop()` and then the original. `await em._evict()` returns without raising; premise: the hook ran. Then `await em._evict()` again on the stopped memory returns `None`. Leave the rig; reopen `_memory(tmp_path, "archive")`: all 4 ids live, exactly one archive row (the first victim: a duplicate, never a loss).
- **L-8** `test_a_stop_during_an_erase_live_phase_is_typed`: store `ep-000`; the audit hook stops the memory on its first call with `disposition == DISPOSITION_ERASED`; `evict_by_ids([_SUBJECT], reason="erasure", disposition=EvictionDisposition.ERASE)` raises `EpisodeErasureIncomplete` matching `^erasure_live_store_unavailable$` (not `AttributeError`). Reopen: a retry erases; `_traces == _GONE`.

## Section 5 (M3): `src/probos/cognitive/episodic.py` (restore)

### 5a. Import
SEARCH:
```python
    EpisodeArchiveConflict,
    EpisodeArchiveIntegrityError,
    EpisodeArchiveLookups,
    EpisodeArchiveUnavailable,
```
REPLACE:
```python
    EpisodeArchiveConflict,
    EpisodeArchiveError,
    EpisodeArchiveIntegrityError,
    EpisodeArchiveLookups,
    EpisodeArchiveNotFound,
    EpisodeArchiveUnavailable,
```

### 5b. Constant
SEARCH:
```python
# large eviction never holds the lock across the whole batch and a store() waits for one chunk at most.
_EVICTION_LOCK_CHUNK = 100
```
REPLACE:
```python
# large eviction never holds the lock across the whole batch and a store() waits for one chunk at most.
_EVICTION_LOCK_CHUNK = 100
# AD-1340 S2b: the accessor a restore records when its caller names none (internal and test callers).
_RESTORE_DEFAULT_ACCESSOR = "episodic_memory"
```

### 5c. The stop check (module function, before `_erase_store_file`)
SEARCH:
```python
async def _erase_store_file(kind: str, path: str | None, ids: list[str]) -> bool:
    """AD-1340 R1: ERASE through the sidecar's own class when no open handle is wired.
```
REPLACE:
```python
def _require_same_collection(current: Any, bound: Any) -> None:
    """AD-1340 S2b: a restore bound to one live collection stops, typed, once stop() (or a restart) replaced it."""
    if current is not bound:
        raise EpisodeArchiveUnavailable("episode_restore_interrupted_by_stop")


async def _erase_store_file(kind: str, path: str | None, ids: list[str]) -> bool:
    """AD-1340 R1: ERASE through the sidecar's own class when no open handle is wired.
```

### 5d. Restore, and its sidecar writer (replaces `:2969-3021`)
SEARCH:
```python
    async def restore_from_archive(self, episode_id: str) -> Episode:
        """AD-1340: put one archived episode back in the live store, byte-equal.

        Internal service API (no agent-facing caller in S1). Never goes through
        store(): the rate limits, dedup and write-once guard would refuse or
        alter it. Refuses an id that is already live. The archive row is kept;
        re-eviction stores the current payload when metadata changed after the
        restore. Activation restarts
        from this one access, because the old access rows were deleted at eviction.
        Restore does not trigger capacity eviction; the next store() does.
        AD-1340 R2: the store write lock is held from the archive read to the last
        sidecar insert, so a concurrent ERASE of the id is wholly before or wholly after.
        """
        archive = self._archive_or_none()
        if archive is None or not self._collection:
            raise EpisodeArchiveUnavailable("episode_archive_unavailable")
        # AD-1340 R2: ERASE holds this lock across its live and archive phases. The archive read, the live-id check,
        # the access row, the add and the sidecar inserts are one critical section (unlike store(), BF-669), so an
        # erase of this id is wholly before the restore (no record) or wholly after it (every copy removed).
        async with self._get_store_write_lock():  # AD-1340 R2: read, check, add and index in one critical section with ERASE
            records = await archive.get_records([episode_id])
            if not records:
                raise LookupError("episode_archive_not_found")
            record = records[0]
            episode = self._metadata_to_episode(record.episode_id, record.document, dict(record.metadata))
            live = self._collection.get(ids=[record.episode_id], include=[])
            if live and live.get("ids"):
                raise EpisodeArchiveConflict("episode_archive_restore_live_id")
            # Audit before action: an access that cannot be recorded stops the restore before anything changed.
            await archive.record_access(record.episode_id, accessor="episodic_memory", purpose="restore")
            self._collection.add(ids=[record.episode_id], documents=[record.document], metadatas=[dict(record.metadata)])
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

REPLACE:
```python
    async def restore_from_archive(
        self, episode_id: str, *, accessor: str = _RESTORE_DEFAULT_ACCESSOR,
    ) -> Episode:
        """AD-1340: put one archived episode back in the live store, byte-equal.

        Never goes through store(): the rate limits, dedup and write-once guard would refuse or alter it.
        Restores the latest archived version, the one an S2a lookup shows (``get_records``). Refuses an id that
        is already live and, AD-1340 S2b (b), a live store already at ``max_episodes``. The archive row is kept;
        re-eviction stores the current payload when metadata changed after the restore. Activation restarts from
        this one access, so the next Step 12 may prune the episode again (re-archived, never lost).
        ``accessor`` names the caller in the ``archive_access`` row.
        AD-1340 R2: the store write lock is held from the archive read to the live add, so a concurrent ERASE of
        the id is wholly before or wholly after.
        AD-1340 S2b: all or nothing. The access row, then every sidecar row, then the live add LAST, with no await
        between the final stop() check and the add. A failed sidecar insert raises
        ``episode_archive_restore_incomplete:<store>``; a stop() at any await raises ``EpisodeArchiveUnavailable``.
        Either way the sidecar rows are undone and nothing is live.
        """
        if not isinstance(accessor, str) or not accessor.strip():
            raise ValueError("episode_archive_restore_accessor_invalid")
        archive = self._episode_archive
        collection = self._collection  # AD-1340 S2b: bound once; a stop() replaces self._collection, never this
        if self._archive_state != "open" or archive is None or collection is None:
            raise EpisodeArchiveUnavailable("episode_archive_unavailable")
        # AD-1340 R2: ERASE holds this lock across its live and archive phases. The archive read, the live-id check,
        # the access row, the add and the sidecar inserts are one critical section (unlike store(), BF-669), so an
        # erase of this id is wholly before the restore (no record) or wholly after it (every copy removed).
        async with self._get_store_write_lock():  # AD-1340 R2: read, check, add and index in one critical section with ERASE
            records = await archive.get_records([episode_id])
            _require_same_collection(self._collection, collection)  # AD-1340 S2b: a stop() during the archive read
            if not records:
                raise EpisodeArchiveNotFound("episode_archive_not_found")
            record = records[0]
            episode = self._metadata_to_episode(record.episode_id, record.document, dict(record.metadata))
            live = collection.get(ids=[record.episode_id], include=[])
            if live and live.get("ids"):
                raise EpisodeArchiveConflict("episode_archive_restore_live_id")
            if collection.count() >= self.max_episodes:  # AD-1340 S2b (b): a restore never takes the store over budget
                raise EpisodeArchiveConflict("episode_archive_restore_over_capacity")
            # Audit before action: an access that cannot be recorded stops the restore before anything changed.
            await archive.record_access(record.episode_id, accessor=accessor, purpose="restore")
            await self._write_restore_sidecars(collection, episode)  # AD-1340 S2b: ends with the stop() check
            collection.add(ids=[record.episode_id], documents=[record.document], metadatas=[dict(record.metadata)])
        return episode

    async def _write_restore_sidecars(self, collection: Any, episode: Episode) -> None:
        """AD-1340 S2b: the restored id's FTS, participant and activation rows, all written before it is live.

        ``restore_from_archive`` calls this inside the store write lock and adds the id to the live store on its next
        statement. Stale rows for the id (it is not live, so any row is stale) are cleared first; a store with no
        open handle is skipped, as store() skips it. The LAST statement re-checks that no stop() replaced
        ``collection``, so nothing is awaited between that check and the live add. On a failed insert, a stop() or a
        cancellation the rows written are cleared, reaching a store stop() closed through its file, and the error
        propagates: a stop() as ``EpisodeArchiveUnavailable``, a failed insert as
        ``episode_archive_restore_incomplete:<store>``, a cancellation as itself.
        """
        ids = [episode.id]
        await self._cleanup_sidecars(ids)  # AD-1340 S2b: no stale row is carried into the restored episode
        stage = "episode_fts"
        try:
            fts_db = self._fts_db
            if fts_db is not None:
                fts_content = (episode.user_input or "") + " " + (episode.reflection or "")
                await fts_db.execute(
                    "INSERT INTO episode_fts(episode_id, content) VALUES (?, ?)", (episode.id, fts_content),
                )
                await fts_db.commit()
            stage = "participant_index"
            index = self._participant_index
            if index is not None:
                participants = episode.anchors.participants if episode.anchors else []
                await index.record_episode(episode.id, episode.agent_ids, participants)
            stage = "activation"
            tracker = self._activation_tracker
            if tracker is not None:
                await tracker.record_access(episode.id, access_type="archive_restore")
            _require_same_collection(self._collection, collection)  # AD-1340 S2b: the last check; the live add follows with no await
        except BaseException as exc:
            try:
                await self._cleanup_sidecars(ids, strict=True)  # AD-1340 S2b: undo, reaching a store stop() closed through its file
            except EpisodeErasureIncomplete:
                logger.warning(
                    "AD-1340 S2b: a failed restore of %s left index rows it could not clear; an ERASE of the id "
                    "clears them", episode.id[:8],
                )
            if not isinstance(exc, Exception):  # AD-1340 S2b: a cancellation is undone, then keeps its type
                raise
            _require_same_collection(self._collection, collection)  # AD-1340 S2b: a stop() caused the failure
            logger.warning(
                "AD-1340 S2b: restore of %s could not write its %s row; nothing was made live",
                episode.id[:8], stage, exc_info=True,
            )
            raise EpisodeArchiveError(f"episode_archive_restore_incomplete:{stage}") from exc
```
**Counts:** `EpisodicMemory` gains one method (`_write_restore_sidecars`); its `srp-size` row in `docs/development/architecture-baseline.yaml:537-545` is already frozen on `[lines, methods]` with no count, so `check_architecture_principles.py --check` must still exit 0 (verify; if it does not, stop and report, do not edit the baseline). Two module functions added in M2 and M3.

### 5e. `tests/test_ad1340_s1_restore_reset.py`: the round trip makes room (deliberate; D5)
`_prove_round_trip("capacity")` runs at `max_episodes=2` with two live episodes, so the new capacity refusal would fire. The amendment raises the budget before the restore and asserts why.

SEARCH:
```python
        proxy = _record_collection(em)
        restored = await em.restore_from_archive(_SUBJECT)
```
REPLACE:
```python
        if capacity:
            assert em._collection.count() == em.max_episodes  # premise: the store is at its budget (test-only)
            em.max_episodes = 3  # AD-1340 S2b (b): a restore refuses at capacity, so the round trip makes room first
        proxy = _record_collection(em)
        restored = await em.restore_from_archive(_SUBJECT)
```

## Section 6 (M3): `tests/test_ad1340_s2b_restore.py` (new)

Same imports as Section 4b, plus `EpisodeArchiveError`, `EpisodeArchiveNotFound`, `EpisodeArchiveConflict`, `EpisodeArchiveUnavailable` and `ArchiveRecord` from `probos.cognitive.episode_archive`, `_GatedRead` from `tests.test_ad1340_s2a_archive_lookup`, `_memory_without_archive` from `tests.test_ad1340_s2a_lookup_route`, `DreamingConfig` from `probos.config_models.cognition`, and `_activation_types` and `_archive_accesses` from `tests.test_ad1340_s1_restore_reset`. Each test archives its subject through Step 12's call (`evict_by_ids([id], reason="activation_decay")`) and asserts the premise (archived, not live, sidecars zero) first.

- **R-1** `test_restore_refuses_at_capacity_and_writes_nothing` (`max_episodes=2`): store `ep-000`, `ep-001`; evict `ep-000`; store `ep-002` (live count 2). Premise: `em._collection.count() == 2`. Restore raises `EpisodeArchiveConflict` matching `^episode_archive_restore_over_capacity$`; no `archive_access` row, sidecars zero, not live. Evict `ep-001` (count 1 = max − 1): the restore succeeds and the count is 2.
- **R-2** `test_restore_writes_every_index_row_before_the_live_add_and_clears_stale_rows`: after the eviction, plant a stale FTS row (`INSERT INTO episode_fts(episode_id, content) VALUES (?, 'stale')`) and one stale participant row through raw `sqlite3` connections of the test's own; premise: both counted. Hooks on the FTS insert (`_FtsTailProxy`), `rig.participants.record_episode` and `rig.activations.record_access` record `_raw(em, [id])["ids"]` when called: each is `[]`. After: `_sidecar_counts == {"fts": 1, "activation": 1, "participants": 2}`; the FTS row's content is not `'stale'`; `keyword_search("alpha")` finds the id.
- **R-3** `test_a_failed_sidecar_insert_undoes_the_restore`, parametrized `store` in `("episode_fts", "participant_index", "activation")`: make that insert raise `RuntimeError` (`_FtsTailProxy` whose `before_insert` raises; or a monkeypatched `record_episode` / `record_access`). Restore raises `EpisodeArchiveError` matching `^episode_archive_restore_incomplete:{store}$`, chained to the `RuntimeError`; not live; sidecars zero; one archive row kept; `_archive_accesses == [("episodic_memory", "restore")]`. Remove the fault; the retry succeeds with sidecars `{1, 1, 2}` and two access rows.
- **R-4** `test_a_stop_at_each_await_of_restore_is_typed_and_leaves_nothing_live`, parametrized `point`:
  - `archive_read`: `_GatedRead(archive._db, "before_fetchall")`; while paused, `await em.stop()`; release. Expect `^episode_archive_not_open$`; no access row.
  - `replaced`: `_GatedRead(archive._db, "after_fetchall")`; while paused, save `original = em._collection` and set `em._collection` to a fresh `object()` (a restart's new collection, test-only); release. Expect `^episode_restore_interrupted_by_stop$`; no access row; `original.get(ids=[id])["ids"] == []`; then put `original` back.
  - `fts_insert`, `participant_insert`, `activation_insert`: pause inside that insert (`_FtsTailProxy` / wrapped `record_episode` / wrapped `record_access`, each awaiting a release future after resolving an entered future); `await em.stop()` while paused; release. Expect `^episode_restore_interrupted_by_stop$`; one access row.
  - Every case: premise that the pause was reached and `em.stop()` completed while the restore was pending; then `_sidecar_counts == {"fts": 0, "activation": 0, "participants": 0}` read from the files, and one archive row. Leave the rig, reopen `_memory(tmp_path, "archive")`: not live; a retry restore succeeds.
- **R-4b** `test_a_cancelled_restore_is_undone`: pause inside the participant insert; cancel the restore task; expect `asyncio.CancelledError`; not live (the memory still runs); sidecars zero.
- **R-5** `test_restore_names_its_accessor_and_types_its_refusals`: `restore_from_archive(id, accessor="captain:/api/security/archive/restore")` writes that accessor; on a second archived id, `accessor=" "` raises `ValueError` matching `^episode_archive_restore_accessor_invalid$` and writes no access row; an unknown id raises `EpisodeArchiveNotFound` (also an instance of `LookupError`); on `_memory_without_archive(tmp_path / "failed", "failed")` restore raises `EpisodeArchiveUnavailable` matching `^episode_archive_unavailable$`.
- **R-6** `test_restore_puts_back_the_version_a_lookup_shows`: after `ep-000` is archived, take its archived metadata `m`; archive two crafted versions through `em._episode_archive.archive` (test-only): `ArchiveRecord` instances for `ep-000` with `{**m, "content_hash": "0" * 64, "valid_until": 1.0}` and `{**m, "content_hash": "f" * 64, "valid_until": 2.0}`; delete the original row with `_write` so exactly these two exist, and force both `archived_at = 7000.0`. `lookup_archived_by_id("ep-000", accessor="test")` shows hash `"0" * 64`; restore; the live metadata equals that version's (`_canonical`). On `ep-001`, the same with the `"f" * 64` row forced newer (`7001.0`): lookup and restore both give `"f" * 64`.
- **R-7** `test_the_next_aggressive_step12_prunes_a_restored_episode_again_without_loss` (D5): restore `ep-000`; read its one activation `access_time` `t` from `activation.db`; `cfg = DreamingConfig()`; premise: `cfg.aggressive_prune_enabled`, `cfg.aggressive_prune_threshold == 0.0`, and the episode's timestamp is older than `time.time() - cfg.aggressive_prune_min_age_hours * 3600`. Freeze the activation module's clock with `monkeypatch.setattr("probos.cognitive.activation_tracker.time", SimpleNamespace(time=lambda: frozen))` (a stand-in module, so ChromaDB and SQLite keep the real clock): at `frozen = t`, `find_low_activation_episodes(all_episode_ids=candidates, threshold=cfg.aggressive_prune_threshold, max_prune_fraction=cfg.aggressive_prune_max_fraction)` returns `[]`; at `frozen = t + 3600` both it and `find_low_activation_episodes_with_importance(..., importance_map={id: 5}, ...)` return `[id]` (`candidates` from `em.get_episode_ids_older_than(...)`, Step 12's own read). `evict_by_ids([id], reason="activation_decay_aggressive") == 1`; `_archive_rows` equals the rows before (same key, same bytes, not rewritten); a second restore is byte-equal.
- **R-8** `test_restore_eviction_erase_and_lookup_together_finish_and_stay_consistent` (`max_episodes=4`): store `ep-000..ep-005`; evict `ep-000`, `ep-001`, `ep-002`. Run together under one `asyncio.wait_for(asyncio.gather(..., return_exceptions=True), 10)`: restore `ep-000`; ERASE `ep-001`; `evict_by_ids(["ep-003"], reason="activation_decay")`; `lookup_archived_by_id("ep-002", accessor="test")`; `em._evict()`. Each result is a success or `EpisodeArchiveConflict` `episode_archive_restore_over_capacity` (the order decides); nothing else. After: `_traces(em, root, "ep-001") == _GONE`; for every id `ep-000..ep-005`: live implies `{"fts": 1, "participants": 2}` and not live implies `{"fts": 0, "participants": 0}`; the lookup returned `ep-002`.

## Section 7 (M5, Part 2): `src/probos/routers/security.py`

### 7a. Imports
SEARCH:
```python
from probos.cognitive.episode_archive import (
    LOOKUP_DEFAULT_LIMIT,
    LOOKUP_MAX_LIMIT,
    ArchivedEpisode,
    EpisodeArchiveError,
    EpisodeArchiveUnavailable,
)
```
REPLACE:
```python
from probos.cognitive.episode_archive import (
    LOOKUP_DEFAULT_LIMIT,
    LOOKUP_MAX_LIMIT,
    ArchivedEpisode,
    EpisodeArchiveConflict,
    EpisodeArchiveError,
    EpisodeArchiveNotFound,
    EpisodeArchiveUnavailable,
)
```

### 7b. The route (append after `lookup_archived_episodes`; the file ends at `:224`)
SEARCH:
```python
    if request.agent_id:
        body["agent_match"] = "primary_agent_only"
    return body
```
REPLACE:
```python
    if request.agent_id:
        body["agent_match"] = "primary_agent_only"
    return body


_ARCHIVE_RESTORE_ACCESSOR = "captain:/api/security/archive/restore"
_ARCHIVE_RESTORE_TOKEN_REQUIRED = "episode_archive_restore_requires_token"


class ArchiveRestoreRequest(BaseModel):
    """AD-1340 S2b: the id of one archived episode to put back in the live store."""

    model_config = {"extra": "forbid"}

    episode_id: str = Field(min_length=1, max_length=256)


@router.post(
    "/archive/restore",
    dependencies=[Depends(require_crew_scope), Depends(_refuse_non_finite_numbers)],  # AD-1340 S2b: D8, then A2
)
async def restore_archived_episode(
    request: ArchiveRestoreRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-1340 S2b: the Captain's restore of one archived episode into the live store.

    Refused (403) while no crew-scope token is configured, before anything is read (S2a D8). All or nothing
    (``EpisodicMemory.restore_from_archive``): a 200 means the episode is live with every wired index row, in the
    version the lookup route shows. One ``archive_access`` row names this route. A restored episode decays under
    the ordinary rules, so an unrecalled one returns to the archive at a later Step 12. Logs ids, never content.
    """
    if not runtime.config.auth.crew_scope_token:  # AD-1340 S2b: never restore through an open gate
        raise HTTPException(status_code=403, detail=_ARCHIVE_RESTORE_TOKEN_REQUIRED)
    memory = getattr(runtime, "episodic_memory", None)
    if memory is None:
        raise HTTPException(status_code=503, detail="episodic_memory_unavailable")
    try:
        episode = await memory.restore_from_archive(request.episode_id, accessor=_ARCHIVE_RESTORE_ACCESSOR)
    except EpisodeArchiveUnavailable as exc:  # AD-1340 S2b: an archive or memory that is absent, failed or stopped
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EpisodeArchiveNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EpisodeArchiveConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EpisodeArchiveError as exc:
        logger.error("AD-1340 S2b: archive restore of %r failed: %s", request.episode_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("AD-1340 S2b: archive restore of %r failed unexpectedly", request.episode_id, exc_info=True)
        raise HTTPException(status_code=500, detail="episode_archive_restore_failed") from exc
    logger.info("AD-1340 S2b: archive restore of %r completed", episode.id)
    return {"episode_id": episode.id, "restored": True}
```

## Section 8 (M5): `tests/test_ad1340_s2b_restore_route.py` (new)

The REAL app through S2a's rig: import `_memory`, `_runtime`, `_client`, `_post`, `_store_and_evict`, `_memory_without_archive`, `_access_rows`, `_archive_path`, `_count`, `_raw`, `_TOKEN`, `_AUTH`, `_UNAVAILABLE`, `_GatedRead` and `_LOOKUP` from `tests.test_ad1340_s2a_lookup_route`; `_traces`, `_GONE` from `tests.test_ad1340_s1_erasure`; `_sidecar_counts` from `tests.test_ad1340_s1_eviction`; `_canonical` from `tests.test_ad1340_s1_restore_reset`. Requests go through `httpx.AsyncClient` over `ASGITransport` in the test's own loop (`_client`); where a test needs the 500 a client sees from an unhandled error, build the transport with `raise_app_exceptions=False`. `_RESTORE = "/api/security/archive/restore"`.

- **RR-a** `test_restore_route_refuses_without_a_configured_token_before_anything`: token `""` (premise asserted); with and without an `Authorization` header: 403 `episode_archive_restore_requires_token`; not live; `_access_rows` empty.
- **RR-b** `test_restore_route_rejects_a_missing_or_wrong_token`: token set; missing header and wrong token → 401; a body holding `NaN` with no token → still 401 (dependency order); nothing written.
- **RR-c** `test_restore_route_restores_and_records_one_access`: 200 `{"episode_id": id, "restored": True}`; `_raw` equals the record taken before eviction (`_store_and_evict`'s snapshot, `_canonical` compare); sidecars `{1, 1, 2}`; `_access_rows == [("captain:/api/security/archive/restore", "restore")]`.
- **RR-d** `test_restore_route_maps_each_refusal`, parametrized: never archived → 404 `episode_archive_not_found`; already live → 409 `episode_archive_restore_live_id`; at capacity (a rig with `max_episodes` equal to the live count) → 409 `episode_archive_restore_over_capacity`. Each writes no access row and changes no live record.
- **RR-e** `test_restore_route_maps_unavailability_to_503`: each `_UNAVAILABLE` state → 503 `episode_archive_unavailable`; `runtime.episodic_memory = None` → 503 `episodic_memory_unavailable`.
- **RR-f** `test_restore_route_maps_a_stop_during_the_restore_to_503`, parametrized: the archive read gated (`before_fetchall`) and `await em.stop()` while paused → 503 `episode_archive_not_open`; the participant insert paused and `await em.stop()` → 503 `episode_restore_interrupted_by_stop`. Premise each time: the pause was reached and the stop completed while the request was pending. Reopen: not live, sidecars zero.
- **RR-g** `test_restore_route_reports_a_failed_index_insert_as_500_with_nothing_live`: `record_episode` raises → 500 `episode_archive_restore_incomplete:participant_index`; not live; sidecars zero.
- **RR-h** `test_restore_route_validates_the_request`: `{}`, `{"episode_id": ""}`, 257 characters, `{"episode_id": "x", "extra": 1}` → 422; `{"episode_id": "x", "extra": NaN}` sent as raw content → 422 `non_finite_number_in_body`; a non-object body → 422. Nothing written.
- **RR-i** `test_restore_route_maps_an_unexpected_failure_to_a_typed_500`: `em._episode_archive.record_access` raises `RuntimeError` (test-only) → 500 `episode_archive_restore_failed`; an ERROR log names the id; not live.
- **RR-j** `test_restore_route_returns_the_version_the_lookup_route_showed`: two crafted versions of one id with a forced `archived_at` tie (as R-6); the lookup route's `episodes[0]["metadata"]` equals the live metadata after the restore route (`_canonical`).
- **RR-k** `test_seam_step12_lookup_restore_recall_forget` (the cross-seam chain, one test, real stores, real app): store two episodes; Step 12's call archives both; the lookup route by id returns the record; the restore route returns 200; `keyword_search` and `recall_for_agent` find it; `_access_rows` is `[(lookup accessor, "lookup"), (restore accessor, "restore")]` in id order; `POST /api/security/forget` with the id returns `deleted_count == 1`; `_traces(..., id) == _GONE` (live, FTS, activation, participants, archive, access); the other episode stays archived.
- **RR-l** `test_only_the_route_restores_and_only_restore_reads_get_records`: parse every `src/probos/**/*.py` with `ast`; the calls whose attribute is `restore_from_archive` are exactly one, inside `restore_archived_episode` in `routers/security.py`; the calls whose attribute is `get_records` are exactly one, inside `restore_from_archive` in `cognitive/episodic.py`. Premise: more than 500 files parsed.

---

## Tests summary

Part 1: B-1 to B-5 (5 functions, 14 cases), L-1, L-2, L-4, L-4b, L-6, L-7, L-8 (7 functions, 10 cases), R-1 to R-8 with R-4b (9 functions, 15 cases), the replaced T17 and the amended `_prove_round_trip`. Part 2: RR-a to RR-l (12 functions). Boundaries: happy path (B-1, L-1, R-2, RR-c), empty (B-5, L-4b), errors (B-4, R-3, R-5, RR-d, RR-g, RR-i), concurrency and stop (B-3, L-1, L-6, L-7, L-8, R-4, R-4b, R-8, T17', RR-f), privacy and protection (RR-a, RR-b, RR-k, RR-l).

## Focused gates (per milestone; `-n 0 -p no:randomly`; first confirm `probos.__file__` resolves inside this worktree's `src`)

Consumer tests of the changed files, enumerated (Absence Verified 7): tests referencing `evict_by_ids`, `_evict`, `restore_from_archive`, the archive, the store lock or `/api/security`: the four `test_ad1340_s1_*.py`, the two `test_ad1340_s2a_*.py`, `test_bf902_fts_reconciliation.py`, `test_bf905_erasure_live_scan.py`, `test_bf868_erasure_declared_fields.py`, `test_bf869_fused_frame_refs.py`, `test_ad541f_eviction_audit.py`, `test_ad541b_reconsolidation.py`, `test_ad567d_dream_provenance.py`, `test_ad582_memory_probes.py`, `test_ad598_importance_scoring.py`, `test_participant_index.py`, `test_erasure_manager.py`, `test_episodic.py`, `test_episodic_chromadb.py`, and for the router `test_ad1025b_path_anchoring.py`. Call this list CONSUMERS.

- **M1:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1340_s2b_archive_reads.py tests/test_ad1340_s1_archive_store.py tests/test_ad1340_s2a_archive_lookup.py tests/test_ad1340_s2a_lookup_route.py -q -n 0 -p no:randomly`
- **M2:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1340_s2b_eviction_locking.py tests/test_ad1340_s2b_archive_reads.py <CONSUMERS without test_ad1025b> -q -n 0 -p no:randomly`
- **M3:** the M2 command plus `tests/test_ad1340_s2b_restore.py`.
- **M3, forced coarse clock (twice):** the three `test_ad1340_s2b_*.py` files plus `tests/test_ad1340_s1_restore_reset.py` and `tests/test_ad1340_s2a_archive_lookup.py`, with `PYTHONPATH=C:/Users/seang/.copilot/session-state/9ccf7828-c33c-47be-9b75-9f5fac92b832/files` and `-p coarse_clock_plugin`, once with `COARSE_CLOCK_QUANTUM=1.0` and once with `0.015625`. Every order-in-time dependency in this contract is forced (B-1, R-6, R-7, RR-j) or by id (access rows), so both runs must pass unchanged.
- **M5:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1340_s2b_restore_route.py tests/test_ad1340_s2b_restore.py <CONSUMERS> -q -n 0 -p no:randomly`, then the coarse-clock pair on the route file.
- **Checks (M2, M3, M5):** `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check` and `scripts/check_store_registry.py --check`, both exit 0. No config field, so the config checks are unaffected.
- **M4, M6:** `scripts/gen_ad_ledger.py`, then `--check`, then `tests/test_ad1184_ad_ledger.py -q -n 0`.
- The broad gate runs once per part, by the orchestrator, never the Builder.

## Milestones and cut points (Builder milestones of at most about 150 tool calls)

| Part | Milestone | Sections | Estimate | Cut if past about 150 calls |
|---|---|---|---|---|
| 1 | M1 | 1, 2 | 50 to 70 | Not split. |
| 1 | M2 | 3, 4 | 90 to 120 | Commit after Section 3 + 4a + L-1, L-2 green; L-4 to L-8 become M2b. |
| 1 | M3 | 5, 6 | 100 to 130 | Commit after Section 5 + R-1 to R-3, R-5 green; R-4, R-4b, R-6 to R-8 become M3b. |
| 1 | M4 | Tracking (Part 1) | 15 to 25 | Not split. |
| 2 | M5 | 7, 8 | 80 to 110 | Commit after Section 7 + RR-a to RR-e green; the rest become M5b. |
| 2 | M6 | Tracking (Part 2) | 10 to 20 | Not split. |

Commit by explicit path (never `git add -A`); run `git diff --cached --stat` and stop on any unexpected file with more than 200 deletions. `PROGRESS.md` and `DECISIONS.md` may hold unrelated Captain work: stage only the named hunks. Part 2 starts from `origin/main` after Part 1 merges.

## Diff Reviewer properties (verify each; data integrity and privacy)

**Part 1**
1. **No live episode without its index rows.** In `restore_from_archive` the live `collection.add` is the last statement in the lock, follows `_write_restore_sidecars` with no await between, and `_write_restore_sidecars` ends with the stop check. No path makes the id live before every wired FTS, participant and activation row is written.
2. **No index rows for an id a failed restore did not make live.** Every exit of `_write_restore_sidecars` other than a normal return, including a cancellation, runs the strict undo before propagating.
3. **ERASE is wholly before or after restore, an eviction chunk and a lookup.** Restore and every eviction chunk hold the store lock across their awaits; ERASE holds it across its live and archive phases; lookups are linearised by S2a D6, unchanged. No interleaving of restore and ERASE ends with the id live, or live without its archive row.
4. **Eviction never deletes a live row whose payload changed after its snapshot.** In archive mode `_unchanged_since_archived` runs after the last await of `_remove_from_live` and immediately before `collection.delete`, compares `encode_payload` bytes, and a changed id stays live. No `delete` is ever called with an empty id list.
5. **Eviction never deletes an id whose `store()` tail is pending** (archive and delete); ERASE is unchanged (it waits, R3).
6. **One lock order.** Store lock, then archive lock, for every holder in the D2 table; no archive-lock holder references the store lock; no store-lock holder calls a function that takes it. `_evict` is reached only from `store()` after its locked section.
7. **A `stop()` at any await of any archive read or of restore is typed** (`EpisodeArchiveUnavailable`), never a raw driver error, an `AttributeError` on `None` or an empty answer; a read failure on an open archive keeps its type. A stop inside an eviction keeps ids live; inside an ERASE it raises `erasure_live_store_unavailable`.
8. **Restore takes the lookup's version:** `get_records` uses `_LATEST_VERSION`, the same constant as `_LOOKUP_BY_ID_SQL`.
9. **Audit:** restore writes exactly one `archive_access` row per attempt that passed the refusals, through `record_access`, with the caller's accessor; a refused restore writes none; restore is not on `EpisodeArchiveLookups`.
10. **Capacity:** the refusal is inside the lock, before the access row, at `count() >= max_episodes`.
11. **Default recall is unchanged and nothing on a recall path reads the archive.** S1's golden recall test and its RC row stay green and killed.
12. **Nothing else changes:** `store()`, BF-669's four lock tests, `config/system.yaml`, `config.py`, `dreaming.py`, `knowledge/erasure.py`, `memory_probes.py`, `startup/`; `archive()`, `_present`, `record_access()`, `erase()`, `start()`, `stop()` byte-identical.

**Part 2**
13. **The restore route is never reachable without the crew-scope token and the configured-token check:** `Depends(require_crew_scope)` first, the A2 guard second, and the 403 as the handler's first statement before `episodic_memory` is read.
14. **Only the route calls restore, and only restore calls `get_records`** (RR-l).
15. **Errors are typed per D11; the logs carry ids and codes, never document or metadata values.**
16. `/forget` and `/archive/lookup` are byte-identical.

**Consumers that must accept the change.** Part 1: Step 12's `evict_by_ids(ids, reason="activation_decay")` and `"activation_decay_aggressive"` (`dreaming.py:1602`, `:1638`), `store()`'s `_evict()`, AD-754's `forget_*` (ERASE) and the S2a lookup route on a ship whose archive holds S1 and S2a rows. Part 2: the Captain's HTTP client calling `POST /api/security/archive/restore` with `Authorization: Bearer <crew_scope_token>`, after which `POST /api/security/forget` must erase the restored episode and both access rows (RR-k).

## Mutation table (campaign of record: the AD-1340 S2b entry in `DECISIONS.md` records the base tree, each pinned file's sha256, each result and its killer)

**Row ids are S2b's own namespace.** S1 and S2a already used H1, C1, G1 to G8, K1 to K10, P1 to P3 and V1 for other mutants; record every row below in `DECISIONS.md` with the prefix `S2b-` (for example `S2b-H1`), and the earlier rows re-run with their own `S1-` or `S2a-` prefix. The labels inside REPLACE cells are only comments.

Every SEARCH is the stripped post-build line, including any trailing comment, with exactly one match in the named file (count it against the built file first: zero or more than one is INERT). Run the unmodified baseline first, mutate in place with a `.mutbak` sibling, restore in `finally`, treat a timeout as INVALID, and run each row against the test file that holds its killer.

**Partition P1, `tests/test_ad1340_s2b_archive_reads.py`** (Part 1)

| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| H1 | `src/probos/cognitive/episode_archive.py` | `except Exception as exc:  # AD-1340 S2b: did a stop() close the connection under the read?` | `except EpisodeArchiveError as exc:  # AD-1340 S2b mutant H1` | B-3 |
| H2 | `src/probos/cognitive/episode_archive.py` | `raise closed from exc` | `raise closed` | B-3 |
| H3 | `src/probos/cognitive/episode_archive.py` | `raise  # AD-1340 S2b: any other read failure keeps its own type` | `raise EpisodeArchiveUnavailable("episode_archive_not_open") from exc` | B-4 |
| H4 | `src/probos/cognitive/episode_archive.py` | `require_open()  # AD-1340 S2b: a stop() during the read is unavailability (F-140)` | `pass` | B-3 |
| H5 | `src/probos/cognitive/episode_archive.py` | `require_open()  # AD-1340 S2b: rows read across a stop() are never answered; no await follows` | `pass` | B-3 |
| G1 | `src/probos/cognitive/episode_archive.py` | `self._require_open,  # AD-1340 S2b: get_records reads through the stop guard` | `lambda: self._db,  # AD-1340 S2b mutant G1` | B-3 |
| G2 | `src/probos/cognitive/episode_archive.py` | `self._require_open,  # AD-1340 S2b: archived_keys reads through the stop guard` | `lambda: self._db,  # AD-1340 S2b mutant G2` | B-3 |
| G3 | `src/probos/cognitive/episode_archive.py` | `self._require_open,  # AD-1340 S2b: get_versions reads through the stop guard` | `lambda: self._db,  # AD-1340 S2b mutant G3` | B-3 |
| G4 | `src/probos/cognitive/episode_archive.py` | `self._require_open,  # AD-1340 S2b: iter_records reads through the stop guard` | `lambda: self._db,  # AD-1340 S2b mutant G4` | B-3 |
| T1 | `src/probos/cognitive/episode_archive.py` | `f"WHERE a.episode_id IN ({marks}) AND {_LATEST_VERSION}",` | `f"WHERE a.episode_id IN ({marks})",` | B-1, B-2 |
| T2 | `src/probos/cognitive/episode_archive.py` | `"(b.archived_at > a.archived_at OR (b.archived_at = a.archived_at AND b.content_hash < a.content_hash)))"` | `"(b.archived_at > a.archived_at OR (b.archived_at = a.archived_at AND b.content_hash > a.content_hash)))"` | B-1 |

**Partition P2, `tests/test_ad1340_s2b_eviction_locking.py`** (Part 1)

| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| E1 | `src/probos/cognitive/episodic.py` | `async with lock:  # AD-1340 S2b (a): capacity eviction holds the store lock for one chunk` | `if True:  # AD-1340 S2b mutant E1` | L-1 |
| E2 | `src/probos/cognitive/episodic.py` | `for start in range(0, len(ids_to_delete), _EVICTION_LOCK_CHUNK):` | `for start in range(0, len(ids_to_delete), len(ids_to_delete)):` | L-1 |
| E3 | `src/probos/cognitive/episodic.py` | `if collection is None:  # AD-1340 S2b: a stopped memory evicts nothing` | `if False:` | L-7 |
| V1 | `src/probos/cognitive/episodic.py` | `async with lock:  # AD-1340 S2b (a): a dream eviction holds the store lock for one chunk` | `if True:  # AD-1340 S2b mutant V1` | L-2 (and T17' in P4) |
| V2 | `src/probos/cognitive/episodic.py` | `for start in range(0, len(ids), _EVICTION_LOCK_CHUNK):` | `for start in range(0, len(ids), max(1, len(ids))):` | L-2 |
| P1 | `src/probos/cognitive/episodic.py` | `ids = [eid for eid in ids if eid not in pending_tails]  # AD-1340 S2b (a): a store() still indexing an id keeps it live` | `pass` | L-6 |
| C1 | `src/probos/cognitive/episodic.py` | `ids = _unchanged_since_archived(collection, ids, committed)  # AD-1340 S2b (c): no await between this re-read and the delete` | `pass` | L-4 |
| C2 | `src/probos/cognitive/episodic.py` | `same = snapshot is not None and encode_payload(live) == encode_payload(snapshot)` | `same = snapshot is not None` | L-4 |
| C3 | `src/probos/cognitive/episodic.py` | `return [eid for eid in ids if eid in unchanged]` | `return list(ids)` | L-4 |
| C4 | `src/probos/cognitive/episodic.py` | `return []  # AD-1340 S2b (c): never a delete with no ids` | `pass` | L-4b |
| K1 | `src/probos/cognitive/episodic.py` | `raise EpisodeErasureIncomplete("erasure_live_store_unavailable")  # AD-1340 S2b: a stop() inside the erase` | `pass` | L-8 |
| K2 | `src/probos/cognitive/episodic.py` | `if collection is None:  # AD-1340 S2b: a stop() inside an eviction or an erase` | `if False:` | L-7, L-8 |

**Partition P3, `tests/test_ad1340_s2b_restore.py`** (Part 1)

| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| RS2 | `src/probos/cognitive/episodic.py` | `await archive.record_access(record.episode_id, accessor=accessor, purpose="restore")` | `pass` | R-5 |
| RS3 | `src/probos/cognitive/episodic.py` | `await archive.record_access(record.episode_id, accessor=accessor, purpose="restore")` | `await archive.record_access(record.episode_id, accessor="episodic_memory", purpose="restore")` | R-5 |
| RS4 | `src/probos/cognitive/episodic.py` | `if collection.count() >= self.max_episodes:  # AD-1340 S2b (b): a restore never takes the store over budget` | `if False:` | R-1 |
| RS5 | `src/probos/cognitive/episodic.py` | `if collection.count() >= self.max_episodes:  # AD-1340 S2b (b): a restore never takes the store over budget` | `if collection.count() > self.max_episodes:  # AD-1340 S2b mutant RS5` | R-1 |
| RS6 | `src/probos/cognitive/episodic.py` | `raise EpisodeArchiveNotFound("episode_archive_not_found")` | `raise LookupError("episode_archive_not_found")` | R-5 |
| RS7 | `src/probos/cognitive/episodic.py` | `_require_same_collection(self._collection, collection)  # AD-1340 S2b: a stop() during the archive read` | `pass` | R-4[replaced] |
| RS8 | `src/probos/cognitive/episodic.py` | `await self._write_restore_sidecars(collection, episode)  # AD-1340 S2b: ends with the stop() check` | `pass` | R-2 |
| RS9 | `src/probos/cognitive/episodic.py` | `_require_same_collection(self._collection, collection)  # AD-1340 S2b: the last check; the live add follows with no await` | `pass` | R-4[participant_insert] |
| RS10 | `src/probos/cognitive/episodic.py` | `_require_same_collection(self._collection, collection)  # AD-1340 S2b: a stop() caused the failure` | `pass` | R-4[fts_insert] |
| RS11 | `src/probos/cognitive/episodic.py` | `await self._cleanup_sidecars(ids, strict=True)  # AD-1340 S2b: undo, reaching a store stop() closed through its file` | `await self._cleanup_sidecars(ids)  # AD-1340 S2b mutant RS11` | R-4[participant_insert] |
| RS12 | `src/probos/cognitive/episodic.py` | `await self._cleanup_sidecars(ids, strict=True)  # AD-1340 S2b: undo, reaching a store stop() closed through its file` | `pass` | R-3 |
| RS13 | `src/probos/cognitive/episodic.py` | `raise EpisodeArchiveError(f"episode_archive_restore_incomplete:{stage}") from exc` | `raise` | R-3 |
| RS14 | `src/probos/cognitive/episodic.py` | `stage = "participant_index"` | `stage = "episode_fts"` | R-3[participant_index] |
| RS18 | `src/probos/cognitive/episodic.py` | `stage = "activation"` | `stage = "participant_index"` | R-3[activation] |
| RS15 | `src/probos/cognitive/episodic.py` | `await self._cleanup_sidecars(ids)  # AD-1340 S2b: no stale row is carried into the restored episode` | `pass` | R-2 |
| RS16 | `src/probos/cognitive/episodic.py` | `if not isinstance(exc, Exception):  # AD-1340 S2b: a cancellation is undone, then keeps its type` | `if False:` | R-4b |
| RS17 | `src/probos/cognitive/episodic.py` | `if not isinstance(accessor, str) or not accessor.strip():` | `if False:` | R-5 |

**Partition P4, `tests/test_ad1340_s1_restore_reset.py`** (Part 1)

| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| RS1 | `src/probos/cognitive/episodic.py` | `collection.add(ids=[record.episode_id], documents=[record.document], metadatas=[dict(record.metadata)])` | `collection.upsert(ids=[record.episode_id], documents=[record.document], metadatas=[dict(record.metadata)])` | `test_byte_equal_round_trip_through_step12` |
| V1b | `src/probos/cognitive/episodic.py` | `async with lock:  # AD-1340 S2b (a): a dream eviction holds the store lock for one chunk` | `if True:  # AD-1340 S2b mutant V1b` | `test_an_eviction_started_inside_an_erase_waits_then_finds_nothing` |

**Partition P1-S1, `tests/test_ad1340_s1_eviction.py`** (Part 1)

| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| A1 | `src/probos/cognitive/episodic.py` | `archive_refs = {eid: record.archive_ref for eid, record in committed.items()}` | `archive_refs = {}` | `test_dream_eviction_archives_then_deletes` (`:294`) |

**Partition P5, `tests/test_ad1340_s2b_restore_route.py`** (Part 2)

| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| RT1 | `src/probos/routers/security.py` | `if not runtime.config.auth.crew_scope_token:  # AD-1340 S2b: never restore through an open gate` | `if False:` | RR-a |
| RT2 | `src/probos/routers/security.py` | `dependencies=[Depends(require_crew_scope), Depends(_refuse_non_finite_numbers)],  # AD-1340 S2b: D8, then A2` | `dependencies=[Depends(_refuse_non_finite_numbers)],  # AD-1340 S2b mutant RT2` | RR-b |
| RT2b | `src/probos/routers/security.py` | `dependencies=[Depends(require_crew_scope), Depends(_refuse_non_finite_numbers)],  # AD-1340 S2b: D8, then A2` | `dependencies=[Depends(_refuse_non_finite_numbers), Depends(require_crew_scope)],  # AD-1340 S2b mutant RT2b` | RR-b |
| RT2c | `src/probos/routers/security.py` | `dependencies=[Depends(require_crew_scope), Depends(_refuse_non_finite_numbers)],  # AD-1340 S2b: D8, then A2` | `dependencies=[Depends(require_crew_scope)],  # AD-1340 S2b mutant RT2c` | RR-h |
| RT3 | `src/probos/routers/security.py` | `except EpisodeArchiveNotFound as exc:` | `except EpisodeArchiveConflict as exc:` | RR-d |
| RT4 | `src/probos/routers/security.py` | `except EpisodeArchiveConflict as exc:` | `except EpisodeArchiveNotFound as exc:` | RR-d |
| RT5 | `src/probos/routers/security.py` | `except EpisodeArchiveUnavailable as exc:  # AD-1340 S2b: an archive or memory that is absent, failed or stopped` | `except EpisodeArchiveNotFound as exc:  # AD-1340 S2b mutant RT5` | RR-e |
| RT6 | `src/probos/routers/security.py` | `episode = await memory.restore_from_archive(request.episode_id, accessor=_ARCHIVE_RESTORE_ACCESSOR)` | `episode = await memory.restore_from_archive(request.episode_id)` | RR-c |
| RT7 | `src/probos/routers/security.py` | `_ARCHIVE_RESTORE_ACCESSOR = "captain:/api/security/archive/restore"` | `_ARCHIVE_RESTORE_ACCESSOR = "captain:/api/security/archive/lookup"` | RR-c |
| RT8 | `src/probos/routers/security.py` | `raise HTTPException(status_code=500, detail="episode_archive_restore_failed") from exc` | `raise` | RR-i |

**Checked by hand (each after its test passed unmutated; restore the file and re-check its hash).** **WH-c** (Part 1): move the C1 line and its `if not ids:` / `return []` pair above the `if self._eviction_audit:` block; L-4[audit] must fail. **WH-a** (Part 1): dedent the `await self._remove_from_live(...)` call in `_evict` out of `async with lock:` (leave `pass` inside); L-1's `locked()` witness must fail. **WH-r** (Part 1): move `collection.add(...)` above `await self._write_restore_sidecars(...)`; R-2 must fail. **WH-s** (Part 1): move the RS9 line above the activation insert; R-4[activation_insert] must fail.

**Rows retired with the lines they named** (do not run; record them as retired): S1 R2m and R3m (restore's add and access lines, replaced by RS1 and RS2/RS3); S2a N33 to N37 (`_lookup`'s A3 block and empty-answer re-check, replaced by H1 to H5; S2a's A-20, A-21, A-22 and RT-h must still pass, and the orchestrator runs H1, H2, H4 and H5 once more against `tests/test_ad1340_s2a_archive_lookup.py` to show the lookup path is guarded by the same lines).

**Earlier rows to re-run on the Part 1 tree** (their files changed): every S1 row pinned to `episode_archive.py` (P1 to P3, C1, H1, S1, X1, I2, I3, Q1 to Q3, AL1 to AL4, and the two-anchor S2 by hand) against `tests/test_ad1340_s1_archive_store.py`; every S1 row pinned to `episodic.py` other than R2m and R3m (O1, O2, U1, D1, D2, RC, E1m to E9m, R1m, W1, W2, TW1 to TW5) against the file of its recorded killer (`DECISIONS.md`, AD-1340 S1 campaign); S2a's N1 to N19, N26, N27 and N38 against `tests/test_ad1340_s2a_archive_lookup.py`, and N20 to N22 against `tests/test_ad1340_s2a_lookup_route.py`. On the Part 2 tree: S2a's N23 to N25 and N28 to N32 against `tests/test_ad1340_s2a_lookup_route.py` (`routers/security.py` changed). Each anchor's count must still be exactly one; the S2b lines were given distinct comments for this.

## What this does NOT change

- `store()` and BF-669's release before its tail; the tail registry and ERASE's bounded wait (R3).
- `archive()`, `_present`, `record_access()`, `erase()`, `start()`, `stop()` of `EpisodeArchive`; the schema and `ARCHIVE_SCHEMA_VERSION` (1).
- `_erase_ids`, `forget_*`, `/api/security/forget`, `/api/security/archive/lookup`, `EpisodeArchiveLookups`' public surface and its access transaction.
- Step 12 (`dreaming.py`), the activation tracker, the participant index, the eviction audit, BF-902's reconciliation.
- No cue index (S2c), no agent-facing consumer (S2d), no doctor figures (S3), no consolidation gate (S4), no expiry (S5).
- `config/system.yaml`, `config.py`, `AuthConfig` (no new field), the HXI and the CLI.

## Tracking

**Part 1 (M4).** `DECISIONS.md`: add `### AD-1340 S2b -- Restore's prerequisites and the Captain's restore route (2026-10-18, #1568)` directly after the S2a entry's last line (`- Contract \`prompts/ad-1340-s2a-archive-lookup.md\`.`), before the BF-905 heading, with one bullet each for: the scope (slice S2b, two PRs, no new number); D2 and D3 (the lock per chunk, the tail skip, the one lock order and its holders, (d) by construction, T17 replaced); D4 (the re-read and the audit order); D5 (capacity refusal and the measured re-prune, by design); D6 and D7 (the guard, F-140 closed, N33 to N37 retired; `get_records` on `_LATEST_VERSION`); D8 and D9 (all-or-nothing restore, typed stops, the accessor, `EpisodeArchiveNotFound`); the Part 1 campaign of record (tree, sha256s, each result and killer, the earlier rows re-run); the contract path. `PROGRESS.md`: one paragraph at the top in the format of `PROGRESS.md:3-5`: AD-1340 S2b Part 1 built, no caller yet, the test count, "#1568 stays open". Regenerate the AD ledger. The orchestrator posts on #1523 that F-140 is fixed by Part 1.

**Part 2 (M6).** Append to the S2b entry: D10 and D11 (the route, protection, shapes, errors, audit, residual) and the Part 2 campaign of record. `PROGRESS.md`: one paragraph: the route path, the token requirement, the test count, "#1568 stays open". Regenerate the ledger. No roadmap edit (as S1 and S2a).

## Acceptance criteria

1. Every milestone's focused gate is green with `-n 0 -p no:randomly`, `probos.__file__` resolving inside this worktree, and the coarse-clock pair is green at both quanta.
2. The CONSUMERS list is green; the only edits to existing tests are Section 4a (T17 replaced) and Section 5e (`_prove_round_trip` makes room); no other assertion is edited or weakened.
3. `check_architecture_principles.py --check` and `check_store_registry.py --check` exit 0 with the files staged; `architecture-baseline.yaml` is unchanged.
4. Every row of the part's partitions and its hand rows is KILLED, the earlier rows re-run are KILLED, and the retired rows are recorded as retired, in one campaign of record per part copied into `DECISIONS.md`. None is INERT, INVALID or SURVIVED.
5. RR-k crosses Step 12, the archive, the lookup route, the restore route, recall and the AD-754 route in ONE test through the real app with real stores.
6. With no crew-scope token configured, the restore route answers 403 and writes nothing (RR-a).
7. `config/system.yaml` is untouched and no config field exists.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Prior Art and Blind Spots (2026-10-18)

**Internal.** S1 R2 (restore and ERASE under the store lock) and R3 (the archive lock, condition (d), the store-tail registry) are the base this builds on; S2a D4 (`_LATEST_VERSION`), D6 (linearisation), D8 (route protection), A2 (non-finite guard) and A3 (the guard D6 generalises) are reused verbatim; BF-669 fixes `store()`'s tail outside the lock, which is why D2 needs the tail skip; BF-902 (`DECISIONS.md:78`: 4,167 of 4,725 FTS ids named no live episode on a copy of the live data) shows the keyword channel already tolerates an FTS row whose id is not live, which D8's index-before-add order relies on during the restore's lock window. The Captain's "memory: optimize, never delete" decision (forgetting is recall decay) decides D5.

**External.** None searched: lock placement, commit-point ordering and typed shutdown inside this module are ProbOS-specific plumbing. The design is the ordinary "make the primary record visible last" ordering (index entries first, the visible add as the commit point), applied because the live add is the only step ProbOS cannot undo cheaply after a stop. `docs/research/reference-projects.md` (date used 2026-10-18): Letta (reviewed 2026-10-17, its archival tier already compared in S1) is current; RAGFlow, LoCoMo and Memvid were considered, deferred (no restore or lock-order analogue). No row examined, so no row update.

**Blind spots, each decided.** (1) A restored episode is re-pruned by the next Step 12 (D5: by design, pinned by R-7). (2) A restore at `max_episodes - 1` is the next capacity victim (D5, recorded). (3) Eviction inside a `store()` tail (D2: fixed by the tail skip). (4) A stop or a cancellation mid-restore (D8: undone, strict, typed). (5) ChromaDB `delete` with an empty list (D9: never called). (6) An eviction audit row can name an id that (c) kept live, as it already can for a failed delete (D4: recorded, the audit records attempts). (7) A capacity eviction whose victims were chosen before a restore can evict the restored episode in a later chunk; it is the oldest live episode, which (b) already accepts, and it is re-archived, never lost (recorded). (8) The single shared crew-scope token (S2a D8 residual) now also gates a write (D10, stated).

## Verified Against Codebase (2026-10-18, base `cf9dc8cd`)

Commands are the Grep and Read calls run in this worktree, written as `rg -n`.

```
rg -n "_get_store_write_lock\(\)" src/probos/cognitive/episodic.py
  1719:            lock = self._get_store_write_lock()
  1944:        write_lock = self._get_store_write_lock()
  2826:        async with self._get_store_write_lock():  # AD-1340 R2: restore cannot interleave the live and archive phases
  2988:        async with self._get_store_write_lock():  # AD-1340 R2: read, check, add and index in one critical section with ERASE
rg -n "def (restore_from_archive|_evict|evict_by_ids|_remove_from_live|_archive_records|_erase_ids|stop|_reconcile_fts_index|_cleanup_sidecars)" src/probos/cognitive/episodic.py
  1662 stop; 1694 _reconcile_fts_index; 2655 _archive_records; 2713 _cleanup_sidecars(self, ids, *, strict=False);
  2752 _remove_from_live; 2803 _erase_ids; 2969 restore_from_archive; 3023 _evict; 3049 evict_by_ids
Read episodic.py:1662-1692   1663: self._collection = None (first statement); 1681: await self._episode_archive.stop()
Read episodic.py:1944-2192   1945: async with write_lock:; 2132: self._collection.add(...); 2140: tail registered inside the lock;
                             2142-2167: FTS and participant tail outside the lock; 2192: await self._evict()
Read episodic.py:2655-2680   2662: result = self._collection.get(...); 2674: committed = await archive.archive(...); 2680: return {...archive_ref...}
Read episodic.py:2752-2801   2772: committed = await self._archive_records(ids, reason); 2776: archive_refs = committed;
                             2789: await self._eviction_audit.record_batch_eviction(...); 2798: self._collection.delete(ids=list(ids))
Read episodic.py:2826-2833   _erase_ids holds the lock and calls _remove_from_live (2833); 2829: "erasure_live_store_unavailable"
Read episodic.py:2969-3021   2989: get_records; 2994: self._collection.get; 2996: "episode_archive_restore_live_id";
                             2998: record_access(..., accessor="episodic_memory", purpose="restore"); 2999: self._collection.add;
                             3000-3020: FTS, participant, activation inserts swallowed at DEBUG
Read episodic.py:3023-3094   3024: assert self._collection; 3040: _remove_from_live; 3078: self._collection.get(ids=episode_ids, ...)
rg -n "^from probos.cognitive.episode_archive import" src/probos/cognitive/episodic.py   27 (block 27-41; no EpisodeArchiveError, no encode_payload)
rg -n "^_FTS_RECONCILE_PAGE|^def _metadata_by_id|^async def _store_tails_finished|^async def _erase_store_file" src/probos/cognitive/episodic.py
  70 / 1211 / 1245 / 1260
rg -n "Mapping" src/probos/cognitive/episodic.py   19: from collections.abc import AsyncIterator, Mapping
Read episode_archive.py:111-114   _LATEST_VERSION; 115: _LOOKUP_BY_ID_SQL uses it
Read episode_archive.py:129-146   EpisodeArchiveError, ...Unavailable, ...IntegrityError, ...Conflict, EpisodeErasureIncomplete
Read episode_archive.py:285-296   _rollback_quietly, _close_quietly
Read episode_archive.py:351-389   _lookup: 354 db = self._require_open(); 355-363 the A3 try; 380-381 the empty re-check
Read episode_archive.py:417-479   13 direct methods; 438 _write_lock; 469-473 stop() under _write_lock; 475 _require_open
Read episode_archive.py:543-635   get_records (558: archived_at > current[0]), archived_keys, get_versions, iter_records: no re-check after await
Read episode_archive.py:651-666   erase(): archived_keys at 656 inside _write_lock
rg -n "def record_episode|def delete_episodes|def is_open" src/probos/cognitive/participant_index.py   80 (returns if not self._db) / 192 / 57
rg -n "def record_access|def compute_activation|def find_low_activation_episodes" src/probos/cognitive/activation_tracker.py   93 / 126 / 221, 255
rg -n "^import time" src/probos/cognitive/activation_tracker.py   22
rg -n "aggressive_prune_(min_age_hours|threshold|max_fraction)" src/probos/config_models/cognition.py   151 / 152 / 153 (class DreamingConfig at 90)
rg -n "activation_decay_d|activation_prune_threshold|aggressive_prune" config/system.yaml   252: 0.5; 253: -2.0; 261-264
rg -n "max_episodes: int = 100000" src/probos/config.py   833
rg -n "evict_by_ids\(" src/probos   erasure.py:125 (ERASE), dreaming.py:1602, 1638, memory_probes.py:81 (ERASE), episodic.py:3049 (def)
Read routers/security.py:1-224   imports 15-21; 105-107 S2a constants; 163-174 _refuse_non_finite_numbers; 177-180 the S2a decorator;
                                 191-192 the 403 first statement; 204-205 except EpisodeArchiveUnavailable -> 503; 222-224 file end
Read tests/test_ad1340_s1_restore_reset.py   87 max_episodes=2 if capacity; 115-116 proxy then restore; 127, 370 ("episodic_memory", "restore");
                                             182, 487 LookupError match; 544-559 _FtsTailProxy; 708-735 T17
Read tests/test_ad1340_s1_eviction.py   88-118 _memory; 174-205 _CollectionProxy/_record_collection; 294 archive_ref; 406-426 audit before delete;
                                        484, 491 delete-mode call sequences
Read tests/test_ad1340_s2a_lookup_route.py   44-55 constants; 164-180 _memory_without_archive; 200-234 _runtime/_client/_post; 241-316 gates
Read tests/test_ad1340_s2a_archive_lookup.py   78-112 _record/_rows/_write/_count/_started; 37 NOT_OPEN
Read docs/development/architecture-baseline.yaml:537-545   EpisodicMemory srp-size, triggers [lines, methods], no count
Read scripts/check_architecture_principles.py:187-188   SRP_MAX_BODY_LINES 500, SRP_MAX_DIRECT_METHODS 15
Read scripts/phantom-api-precheck.ps1:58-71, 113-185, 227-234   only python fences are scanned; CamelCase "Name(" outside backticks is a candidate
```

## Absence Verified (2026-10-18)

1. CLAIM: `restore_from_archive` has no production caller. RUN: `rg -n "restore_from_archive" src/`. FOUND: `episodic.py:2823` (comment), `:2969` (def). HOLDS: yes.
2. CLAIM: `_evict`, the non-ERASE `evict_by_ids`, `_remove_from_live` and `_archive_records` take no store lock. RUN: `rg -n "_get_store_write_lock|_store_write_lock" src/probos`. FOUND: `episodic.py:1403` (init), `:1719`, `:1899-1906` (getter), `:1944`, `:2826`, `:2988`; `episodic_mock.py:50, 111-130` (its own class). HOLDS: yes.
3. CLAIM: nothing calls `_evict` while holding the store lock. RUN: `rg -n "_evict\(" src/probos/cognitive/episodic.py`. FOUND: `:2192` (in `store()`, after the `async with write_lock:` block that ends at `:2140`), `:3023` (def). HOLDS: yes.
4. CLAIM: the four S1 service reads have no openness re-check after their await. RUN: Read `episode_archive.py:543-635`. FOUND: one `_require_open()` before each read, none after. HOLDS: yes.
5. CLAIM: `episode_archive.py` never reaches the store lock or `EpisodicMemory`. RUN: `rg -n "restore_from_archive|EpisodicMemory|store_write_lock" src/probos/cognitive/episode_archive.py`. FOUND: `:418`, `:436` (docstring and comment only). HOLDS: yes.
6. CLAIM: the new names are free. RUN: `rg -n "_guarded_read|EpisodeArchiveNotFound|_EVICTION_LOCK_CHUNK|_RESTORE_DEFAULT_ACCESSOR|_unchanged_since_archived|_require_same_collection|_write_restore_sidecars|ArchiveRestoreRequest|restore_archived_episode|archive/restore|episode_restore_interrupted_by_stop|episode_archive_restore_" src tests`. FOUND: only `episode_archive_restore_live_id` (`episodic.py:2996`, `test_ad1340_s1_restore_reset.py:173`), which is reused, not new. HOLDS: yes.
7. CLAIM: the CONSUMERS list is every test referencing the changed surfaces. RUN: `rg -l "evict_by_ids|\._evict\(|restore_from_archive|EpisodeArchive|episode_archive|/api/security|routers\.security|_store_write_lock|_reconcile_fts_index" tests` and `rg -l "routers\.security|/api/security/" tests`, plus `tests/test_episodic*.py`. FOUND: the 18 files listed plus `test_ad1025b_path_anchoring.py`, `test_episodic_chromadb.py`. HOLDS: yes.
8. CLAIM: no UI or CLI calls `/api/security`. RUN: `rg -l "api/security"` excluding `prompts/`, `docs/`, `tests/`, `Reviews/`. FOUND: `routers/security.py`, `DECISIONS.md`, `PROGRESS.md`. HOLDS: yes.
9. CLAIM: no existing test awaits an eviction while holding the store lock, other than T17. RUN: `rg -n -A4 "async with (lock|em\._get_store_write_lock\(\))|lock\.acquire\(\)" tests`. FOUND: `test_episodic.py:331`, `test_ad541b_reconsolidation.py:648, 1028, 1114` (stores under budget, so `_evict` takes no lock), `test_ad1340_s2a_lookup_route.py:378` (a lookup). HOLDS: yes.

## Not verified (stated, not assumed)

- No test, check or script was run: the bridge allows only `pytest` and `ad_ceiling.py`, and this drafting call ran neither. The Builder's M1 run is the first execution; stop and report if a gate does not pause where its premise says.
- `scripts/phantom-api-precheck.ps1` was read, not run. Every python fence here uses only CamelCase names that exist in `src/` or are defined in the fence itself.
- ChromaDB's behaviour for `delete(ids=[])` and for `add` after `client.close()`: D9 never calls the first, and RS9 is killed either way the second behaves.
- The architecture check's verdict on one more `EpisodicMemory` method is inferred from the baseline row (no frozen count); M3 runs it.

---

## Amendment A1 (2026-10-18): the live add is inside the undo

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-18. Raised by the orchestrator's pre-build read of Section 5d, decided by the Architect in a read-only consult, and appended here by the orchestrator so that no line number above it moved. It supersedes the contract lines named in A1.4 and A1.6; Section 5d's own text stays as the base the A1 blocks are written against. Decision recorded on #1568.

**Gap.** Section 5d left `collection.add` one statement after `_write_restore_sidecars`, outside its `except`. When the add raised (an embedding failure, or a Chroma error), the FTS, participant and activation rows stayed behind for an id that was not live. `keyword_search` returns FTS ids with no live join, and `participant_index.count_for_agent` counts rows directly (consumers: `acm.py:338`, `boot_camp.py:207`, `holodeck/gates.py:79`, `qualification_tests.py:383`). BF-902's start-up pass removes only the FTS orphans.

**Fix.** `_write_restore_sidecars` takes the `ArchiveRecord` and makes the live add its last statement, as stage `live_add`, inside the same `try`. A failed add is undone like a failed insert, unless the live store may already hold the id. Chroma can raise after its log write committed (the repository pins `chromadb>=1.0`). When the id is found, or the check itself fails, the rows are kept: a live id is never left without them (D8 Rejected) and the error is `episode_archive_restore_unconfirmed`. No new method on `EpisodicMemory`; one module function.

### 5f. `src/probos/cognitive/episodic.py`: the add-landed check (module function, placed after `_require_same_collection`)
SEARCH:
```python
    if current is not bound:
        raise EpisodeArchiveUnavailable("episode_restore_interrupted_by_stop")
```
REPLACE:
```python
    if current is not bound:
        raise EpisodeArchiveUnavailable("episode_restore_interrupted_by_stop")


def _restore_add_may_have_landed(collection: Any, episode_id: str) -> bool:
    """AD-1340 S2b A1: after a live add raised, whether the id may be live; a store that cannot answer counts as may."""
    try:
        found = collection.get(ids=[episode_id], include=[])
    except Exception:
        return True
    return bool(found and found.get("ids"))
```

### 5g. `src/probos/cognitive/episodic.py`: the call site and the restore docstring (against Section 5d's own REPLACE text)
SEARCH:
```python
            await archive.record_access(record.episode_id, accessor=accessor, purpose="restore")
            await self._write_restore_sidecars(collection, episode)  # AD-1340 S2b: ends with the stop() check
            collection.add(ids=[record.episode_id], documents=[record.document], metadatas=[dict(record.metadata)])
        return episode
```
REPLACE:
```python
            await archive.record_access(record.episode_id, accessor=accessor, purpose="restore")
            await self._write_restore_sidecars(collection, episode, record)  # AD-1340 S2b A1: ends with the live add
        return episode
```
SEARCH:
```python
        ``episode_archive_restore_incomplete:<store>``; a stop() at any await raises ``EpisodeArchiveUnavailable``.
        Either way the sidecar rows are undone and nothing is live.
```
REPLACE:
```python
        ``episode_archive_restore_incomplete:<store>`` (``live_add`` for the add itself); a stop() at any await raises
        ``EpisodeArchiveUnavailable``. Either way the sidecar rows are undone and nothing is live, except after an add
        that raised while the live store may hold the id: its rows are kept (``episode_archive_restore_unconfirmed``).
```

### 5h. `src/probos/cognitive/episodic.py`: the helper (against Section 5d's own REPLACE text)
SEARCH:
```python
    async def _write_restore_sidecars(self, collection: Any, episode: Episode) -> None:
        """AD-1340 S2b: the restored id's FTS, participant and activation rows, all written before it is live.

        ``restore_from_archive`` calls this inside the store write lock and adds the id to the live store on its next
        statement. Stale rows for the id (it is not live, so any row is stale) are cleared first; a store with no
        open handle is skipped, as store() skips it. The LAST statement re-checks that no stop() replaced
        ``collection``, so nothing is awaited between that check and the live add. On a failed insert, a stop() or a
        cancellation the rows written are cleared, reaching a store stop() closed through its file, and the error
        propagates: a stop() as ``EpisodeArchiveUnavailable``, a failed insert as
        ``episode_archive_restore_incomplete:<store>``, a cancellation as itself.
        """
```
REPLACE:
```python
    async def _write_restore_sidecars(self, collection: Any, episode: Episode, record: ArchiveRecord) -> None:
        """AD-1340 S2b: the restored id's FTS, participant and activation rows, then the live add as the commit point.

        ``restore_from_archive`` calls this inside the store write lock. Stale rows for the id (it is not live, so
        any row is stale) are cleared first; a store with no open handle is skipped, as store() skips it. A re-check
        that no stop() replaced ``collection`` is followed by the live add with no await between. On a failed insert,
        a failed add, a stop() or a cancellation the rows written are cleared, reaching a store stop() closed through
        its file, and the error propagates: a stop() as ``EpisodeArchiveUnavailable``, a failed insert or add as
        ``episode_archive_restore_incomplete:<store>``, a cancellation as itself. AD-1340 S2b A1: an add that raised
        while the live store may hold the id keeps the rows and raises ``episode_archive_restore_unconfirmed``.
        """
```
SEARCH:
```python
            _require_same_collection(self._collection, collection)  # AD-1340 S2b: the last check; the live add follows with no await
        except BaseException as exc:
            try:
                await self._cleanup_sidecars(ids, strict=True)  # AD-1340 S2b: undo, reaching a store stop() closed through its file
            except EpisodeErasureIncomplete:
                logger.warning(
                    "AD-1340 S2b: a failed restore of %s left index rows it could not clear; an ERASE of the id "
                    "clears them", episode.id[:8],
                )
            if not isinstance(exc, Exception):  # AD-1340 S2b: a cancellation is undone, then keeps its type
                raise
            _require_same_collection(self._collection, collection)  # AD-1340 S2b: a stop() caused the failure
```
REPLACE:
```python
            _require_same_collection(self._collection, collection)  # AD-1340 S2b: the last check; the live add follows with no await
            stage = "live_add"
            collection.add(ids=[record.episode_id], documents=[record.document], metadatas=[dict(record.metadata)])
        except BaseException as exc:
            kept = stage == "live_add" and _restore_add_may_have_landed(collection, episode.id)
            if kept:  # AD-1340 S2b A1: never clear the rows of an id the live store may hold
                logger.warning(
                    "AD-1340 S2b: the live add of %s raised but the id may be live; its index rows are kept",
                    episode.id[:8], exc_info=True,
                )
            else:
                try:
                    await self._cleanup_sidecars(ids, strict=True)  # AD-1340 S2b: undo, reaching a store stop() closed through its file
                except EpisodeErasureIncomplete:
                    logger.warning(
                        "AD-1340 S2b: a failed restore of %s left index rows it could not clear; an ERASE of the id "
                        "clears them", episode.id[:8],
                    )
            if not isinstance(exc, Exception):  # AD-1340 S2b: a cancellation is undone, then keeps its type
                raise
            if kept:
                raise EpisodeArchiveError("episode_archive_restore_unconfirmed") from exc
            _require_same_collection(self._collection, collection)  # AD-1340 S2b: a stop() caused the failure
```
(The `logger.warning(... could not write its %s row ...)` and the `raise EpisodeArchiveError(f"episode_archive_restore_incomplete:{stage}") from exc` lines after it are unchanged. The add line keeps its exact text, so RS1's anchor holds and is still unique in the file; the add in `store()` is `self._collection.add(`.)

**Counts:** `EpisodicMemory` still gains one method (`_write_restore_sidecars`). Module functions added in M2 and M3 rise from two to three. `check_architecture_principles.py --check` must still exit 0 (stop and report if it does not; do not edit the baseline).

### A1.4 Supersessions (D8, D10, D11 and the Diff Reviewer properties; the original lines stay where they are)
- **D8, "Order inside the lock":** read "→ `collection.add` on the very next statement" as "→ inside the helper, after that re-check and with no await between, `collection.add` (stage `live_add`)".
- **D8, the failure bullet:** it covers "a failed insert, a failed live add, a `stop()` or a cancellation"; `<store>` is one of `episode_fts`, `participant_index`, `activation`, `live_add`; "Nothing is live in any of these cases", with one exception: a live add that raised while the live store reports the id, or cannot be asked. Its rows are kept, never cleared under a possibly live id, and it raises `EpisodeArchiveError("episode_archive_restore_unconfirmed")`. A retry then answers 409 `episode_archive_restore_live_id`, and an ERASE clears everything.
- **D10, Response:** "Nothing about sidecars is reported because no restore leaves an id live without its rows, or leaves rows for an id it confirmed is not live."
- **D11:** the 500 `episode_archive_restore_incomplete:<store>` row's When is "a sidecar insert or the live add failed; undone, nothing live (ERROR log)". New row after it: `| 500 | episode_archive_restore_unconfirmed | the live add raised but the store reports the id, or cannot be asked; its index rows kept (ERROR log) |`. No route code change: `except EpisodeArchiveError` already returns `str(exc)`, and the route logs it at ERROR.
- **Diff Reviewer property 1** reads: "**No live episode without its index rows.** In `_write_restore_sidecars` the live `collection.add` is the last statement in the `try`. It follows the stop check with no await between, and every FTS, participant and activation write comes before it. If the add raises, the rows are cleared only when the bound collection confirms the id is absent."
- **Diff Reviewer property 2** reads: "**No index rows for an id a failed restore did not make live.** Every exit of `_write_restore_sidecars` other than a normal return runs the strict undo before propagating, including a failed live add and a cancellation. The only exception is a failed add whose id the live store reports, or cannot be asked about; that one keeps the rows and raises `episode_archive_restore_unconfirmed`."

### A1.5 Section 6 addition: R-3b (`tests/test_ad1340_s2b_restore.py`)
Import `_CollectionProxy` from `tests.test_ad1340_s1_eviction`. Test-local `_FailingAddProxy(_CollectionProxy)` with `armed = True` and `land: bool`. Its `add(**kwargs)`, while armed: disarm; if `land`, call `self.inner.add(**kwargs)`; then raise `RuntimeError("injected: live add failed")`. Once disarmed, it forwards.

- **R-3b** `test_a_failed_live_add_undoes_the_restore_unless_the_id_landed`, parametrized `landed` in `(False, True)`. Install the proxy as `em._collection` before the restore; the restore binds it at entry. Premise: archived, not live, sidecars zero; after the call, `proxy.armed is False`.
  - `landed=False`: raises `EpisodeArchiveError` matching `^episode_archive_restore_incomplete:live_add$`, with `__cause__` the `RuntimeError`. `_raw(em, [id])["ids"] == []`. `_sidecar_counts == {"fts": 0, "activation": 0, "participants": 0}`. One archive row. `_archive_accesses == [("episodic_memory", "restore")]`. The retry (proxy disarmed) succeeds: live, sidecars `{"fts": 1, "activation": 1, "participants": 2}`, two access rows.
  - `landed=True`: raises `EpisodeArchiveError` matching `^episode_archive_restore_unconfirmed$`. `_raw(em, [id])["ids"] == [id]`. Sidecars `{1, 1, 2}`. The retry raises `EpisodeArchiveConflict` matching `^episode_archive_restore_live_id$`, and the sidecars are unchanged.
- Test count: R-1 to R-8 with R-3b and R-4b becomes 10 functions and 17 cases. R-3b joins the error boundaries and the M3 commit set (with R-1 to R-3 and R-5).

### A1.6 Mutation rows and hand rows
| ID | File | SEARCH (built file) | REPLACE | Killed by |
|---|---|---|---|---|
| RS8a | `src/probos/cognitive/episodic.py` | `await self._write_restore_sidecars(collection, episode, record)  # AD-1340 S2b A1: ends with the live add` | `pass` | R-2 |
| RS19 | `src/probos/cognitive/episodic.py` | `kept = stage == "live_add" and _restore_add_may_have_landed(collection, episode.id)` | `kept = stage == "live_add"  # AD-1340 S2b mutant RS19` | R-3b[False] |
| RS20 | `src/probos/cognitive/episodic.py` | `kept = stage == "live_add" and _restore_add_may_have_landed(collection, episode.id)` | `kept = False  # AD-1340 S2b mutant RS20` | R-3b[True] |

RS8 in the Part 1 table (partition P3) is superseded by RS8a: its anchor line no longer exists once A1 is applied, so run RS8a in its place. RS19 is the gap itself: the undo is skipped after a failed add. RS9 to RS14 keep their anchor texts (the undo line is only indented one level deeper). **WH-r** now reads: in `_write_restore_sidecars`, move the `stage = "live_add"` line and the `collection.add(...)` line above `fts_db = self._fts_db`; R-2 must fail (its hooks see the id live at the first insert).

### A1.7 Every exit of restore after A1 (the Architect's enumeration, kept for the Diff Reviewer)
| Exit | Rows left for an id that is not live? | Live without its rows? |
|---|---|---|
| `restore_from_archive`: accessor `ValueError`; state check; lock-acquire cancel; `get_records` raise or cancel; stop re-check; not found; `_metadata_to_episode` raise; `collection.get` raise; live id; `count()` raise or over capacity | No (nothing written yet) | No |
| `record_access` raise or cancel | Only the `archive_access` row, by design (D8) | No |
| Helper: stale clear (non-strict, outside the `try`) cancelled or stopped | No new rows; at worst stale rows only partly cleared (they were already orphans) | No |
| Helper: FTS, participant or activation insert fails; final stop check; cancellation | Undone (strict) | No |
| Helper: live add raises, id absent | Undone | No |
| Helper: live add raises, id may be live | Rows kept, by design | No (rows kept) |
| Strict undo fails (`EpisodeErasureIncomplete`) | **Yes.** Accepted residual: WARNING logged, ERASE or a retry clears it (D8) | No |
| A second cancellation during the undo's awaits | **Yes, with no WARNING.** Accepted: it needs two `cancel()` calls on one task; a retry or ERASE clears it. `asyncio.shield` was considered and deferred | No |
| A store with no open handle (feature off, failed start) | n/a | That store's rows are absent by design (D8, same as `store()`) |
| Normal return | n/a | No (`asyncio.Lock` release does not await) |

**One path left unamended (the Architect's decision):** the stale clear at the start of the helper is non-strict (`_cleanup_sidecars` swallows tracker and index failures, and `_delete_fts_rows` returns a bool). A stale row whose delete fails, followed by a successful insert on the same handle, leaves a live id with a duplicate row (`count_for_agent` inflated by one). Making that clear strict would push it to a failed-start store through its file, and a corrupt sidecar file would then block every restore. It needs an earlier undo failure plus a later delete failure; the next eviction's cleanup and an ERASE delete every row for the id. Recorded on #1523 by the orchestrator.

**Absence Verified (A1):** CLAIM: the three new names are free. RUN: `rg -n "_restore_add_may_have_landed|episode_archive_restore_unconfirmed|_FailingAddProxy|restore_incomplete:live_add" src tests scripts docs`. FOUND: no match. HOLDS: yes (re-run by the orchestrator, 2026-10-18).

### A1.8 Build corrections to this contract (found while building; each verified by the orchestrator; the contract text above stays as drafted)
- **L-1 and L-2: one audit row per episode.** `EvictionAudit.record_batch_eviction` writes one row per episode with `executemany`, each carrying its chunk's `details`. Five episodes in chunks of 2, 2 and 1 therefore give `["batch of 2, budget=1"] * 4 + ["batch of 1, budget=1"]` (L-2: `reason=activation_decay` in place of `budget=1`), not three strings. The 2, 2, 1 chunking is still pinned by the three lock acquisitions and the three archive and three cleanup calls made under the lock.
- **L-7 has one extra assertion:** the typed-stop WARNING ("the live store stopped during eviction") appears exactly once. Without it L-7 alone survives mutant K2, because `_unchanged_since_archived`'s own `try` absorbs a cleared collection; with it L-7 and L-8 kill K2.
- **Two tests the contract left out, added in M2b** for decision D4's guarantee that a failed re-read keeps every id live and for the `(TypeError, ValueError)` fallback of the re-read: **L-4c** `test_a_failed_re_read_keeps_every_archived_id_live` (the next `collection.get` after `archive()` raises once; nothing is deleted, both ids stay live with their index rows, both were archived, a WARNING is logged, and the next eviction completes the job) and **L-4d** `test_an_id_whose_live_record_cannot_be_encoded_stays_live` (`TypeError` and `ValueError`; patching `probos.cognitive.episodic.encode_payload`, used only by the re-read in that module). Mutation row **C5** (`same = False  # AD-1340 S2b (c): a record that no longer encodes is not the one archived` replaced by `same = True`) is killed by L-4d; hand row **WH-f** (the `return []` that follows the "re-read ... failed" warning in `_unchanged_since_archived` replaced by `return list(ids)`) is killed by L-4c.
- **R-4 `archive_read` releases the failed read's references before it reopens the archive.** The read is paused between `execute()` and `fetchall()`, so its SQLite cursor is unfinished and holds the file's read lock until it is collected; the failed read's exception chain (the Task that raised it, and the list holding the Task) keeps that cursor alive until the test function ends, so the reopen failed with `database is locked`. A probe showed the archive reopens at every gate point as soon as those references are dropped. This is a reference the TEST holds, not a product defect (in production the references are dropped when the error is handled, and a restart releases the lock anyway). The contract's R-4 text (reopen, not live, a retry restore succeeds) is unchanged.
- **R-5** also tries `""` and `None` as the accessor, besides `" "`. **R-8:** with `max_episodes=4` the fifth and sixth stores already archive `ep-000` and `ep-001` by capacity, so the setup evicts only `ep-002` by hand; the test asserts the end state (archived `ep-000` to `ep-002`, live `ep-003` to `ep-005`) and the interleaving's outcomes as written.
- **The docstring line** that Section 3g specifies in prose for `evict_by_ids` ("AD-1340 S2b: the non-ERASE path holds the store write lock per chunk ...") was added; a rebuild of the file from the SEARCH/REPLACE blocks equals the working tree once that one line is ignored.

### A1.9 Review round 1 (GPT-6.1 Sol, staged tree `5f515e28`): the outcome, recorded after the build
- **F1 (P2, injected-only reach, a regression in log confidentiality; FIXED in this PR).** Three new WARNINGs passed `exc_info=True`: the failed re-read in `_unchanged_since_archived`, the "live add raised but the id may be live" warning, and the "could not write its <store> row" warning in `_write_restore_sidecars`. `exc_info=True` appends the exception text, and Chroma's text can contain a stored metadata value (the reviewer restored a record whose archived metadata held a dict value and the real `collection.add` failed with the value in the message; the production `LogRedactionFormatter` masks emails, phones, URLs, document ids and tokens, so it did not remove it). The archive exists so that ERASE can remove every copy, so stored content must not be copied into logs. The A1 block 5h text above, whose REPLACE kept `exc_info=True` on two of those warnings, is superseded: all three now log the stage, the exception TYPE NAME, the truncated id and counts, never the exception text, and tests R-3c, R-3d and L-4e pin it (R-3d is the reviewer's real-Chroma case). **Part 2 inherits this:** Section 7b's route code logs `exc_info=True` in two places (the `EpisodeArchiveError` branch and the generic branch); the route must log the exception type only, because the chained `__cause__` carries the same text.
- **F2 (P2 as rated, injected-only reach, not a regression; RECORDED as #1523 F-148, not fixed).** `_guarded_read` binds `db = require_open()` but its two re-checks establish only that SOME connection is open, so a same-instance `stop()` followed by `start()` during a read gives either a raw `ValueError` or the rows read before the stop. HEAD behaves the same. Decision D6's "rows read across a stop are never answered" therefore holds for a stop of the archive instance and not for a same-instance restart; production never restarts an archive instance in place (the memory builds a new `EpisodeArchive` at every start), so it has no ordinary reach. The smallest fix (compare the current connection with the bound `db` in both re-checks, plus two same-instance tests) is recorded on #1523.
- **D2's cost description is inaccurate** (measured by the reviewer on five ids in one default chunk, HEAD against the candidate: Chroma `get` calls 2 to 3 (selection, snapshot and re-read), deletes 1 to 1, comparison payload encodes 0 to 10, store-lock acquisitions 0 to 1; the sidecars issue one FTS DELETE per id plus one activation and one participant DELETE with three commits, not "three sidecar deletes"). The reviewer inferred no latency regression.
- **R-8 is a mixed-operation smoke test, not capacity-contention evidence** (recorded as #1523 F-149, test-only): its concurrent phase runs at live count 3 against a budget of 4, so `_evict` returns before it takes the lock and the test passes with mutant E1 applied; L-1 is the killer of E1.


## Amendment A2 (2026-10-18): the route logs codes and type names, never exception text

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-18. A read-only consult after Part 1's review round 1 (A1.9 F1), appended by the orchestrator so that no line number above it moves. It supersedes the contract lines named in A2.7. Sections 7a and 7b stay as the base the A2 blocks are written against. Decision recorded on #1568.

**Gap.** Section 7b's two `logger.error(..., exc_info=True)` calls (contract lines 1126 and 1129) copy the exception text and its whole `__cause__` chain into the log. `Formatter.format` appends the traceback whenever `record.exc_info` is set. `episode_archive_restore_incomplete:live_add` is raised `from` the Chroma error (`episodic.py:3164`), and Chroma's text can quote a stored metadata value (A1.9 F1, R-3d). `LogRedactionFormatter` (`security/pii_redaction.py:76-81`) masks PII and tokens, not arbitrary stored values. The archive exists so that ERASE can remove every copy, so stored content must not reach a log. The S2a lookup route's ERROR line (`security.py:207`) has the same `exc_info=True`. Its reachable causes today (SQLite errors from the access insert, decode errors) carry no stored values, but it is the same defect class in the same file, so A2 fixes it too and leaves the lookup's response unchanged.

### A2.1 `src/probos/routers/security.py`: import `re` (against the current file; Section 7a does not touch these lines)
SEARCH:
```python
import json
import logging
import math
from pathlib import Path
```
REPLACE:
```python
import json
import logging
import math
import re
from pathlib import Path
```

### A2.2 The error-code guard (against Section 7b's own REPLACE text)
SEARCH:
```python
_ARCHIVE_RESTORE_ACCESSOR = "captain:/api/security/archive/restore"
_ARCHIVE_RESTORE_TOKEN_REQUIRED = "episode_archive_restore_requires_token"
```
REPLACE:
```python
_ARCHIVE_RESTORE_ACCESSOR = "captain:/api/security/archive/restore"
_ARCHIVE_RESTORE_TOKEN_REQUIRED = "episode_archive_restore_requires_token"
# AD-1340 S2b A2: the shape of an archive error code ("name" or "name:qualifier"); anything else is free text.
_ARCHIVE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,95}(?::[a-z0-9_]{1,32})?")


def _archive_error_code(exc: BaseException, fallback: str) -> str:
    """AD-1340 S2b A2: the exception's text when the whole of it is an error code, else ``fallback``.

    A 500 detail and its log line carry a code, never free text: an exception text can quote a stored value
    (A1.9 F1). Every archive raise site passes a constant code today; this keeps a future one honest.
    """
    text = str(exc)
    return text if _ARCHIVE_ERROR_CODE.fullmatch(text) else fallback
```

### A2.3 The route's docstring and its two 500 branches (against Section 7b's own REPLACE text)
SEARCH:
```python
    the ordinary rules, so an unrecalled one returns to the archive at a later Step 12. Logs ids, never content.
    """
```
REPLACE:
```python
    the ordinary rules, so an unrecalled one returns to the archive at a later Step 12. A 500
    ``episode_archive_restore_unconfirmed`` may have made the episode live: a retry then answers 409
    ``episode_archive_restore_live_id``. AD-1340 S2b A2: an error is logged as the id's first 8 characters, the
    error code and an exception type name, never an exception's text or its cause's.
    """
```
SEARCH:
```python
    except EpisodeArchiveError as exc:
        logger.error("AD-1340 S2b: archive restore of %r failed: %s", request.episode_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("AD-1340 S2b: archive restore of %r failed unexpectedly", request.episode_id, exc_info=True)
        raise HTTPException(status_code=500, detail="episode_archive_restore_failed") from exc
```
REPLACE:
```python
    except EpisodeArchiveError as exc:
        code = _archive_error_code(exc, "episode_archive_restore_failed")  # AD-1340 S2b A2: a code, never the text
        logger.error("AD-1340 S2b: archive restore of %s failed: %s (%s)", request.episode_id[:8], code, type(exc.__cause__ or exc).__name__)
        raise HTTPException(status_code=500, detail=code) from exc
    except Exception as exc:
        logger.error("AD-1340 S2b: archive restore of %s failed unexpectedly (%s)", request.episode_id[:8], type(exc).__name__)
        raise HTTPException(status_code=500, detail="episode_archive_restore_failed") from exc
```
(`from exc` stays: FastAPI's `HTTPException` handler builds the response and logs nothing. RT8's anchor line is unchanged and still unique. The success INFO line keeps the full `episode.id`: it is a verified archived id, never caller text.)

### A2.4 The S2a lookup route's ERROR line (against the current file, `security.py:206-209`)
SEARCH:
```python
    except EpisodeArchiveError as exc:
        logger.error("AD-1340 S2a: archive lookup failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    kind = "episode_id" if request.episode_id else "agent"
```
REPLACE:
```python
    except EpisodeArchiveError as exc:
        code = _archive_error_code(exc, "episode_archive_lookup_failed")  # AD-1340 S2b A2: the lookup logs a code too
        logger.error("AD-1340 S2a: archive lookup failed: %s (%s)", code, type(exc.__cause__ or exc).__name__)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    kind = "episode_id" if request.episode_id else "agent"
```
(The lookup's response is unchanged: its detail stays `str(exc)`. `_archive_error_code` is a module function defined further down; it resolves at call time.)

### A2.5 Section 8 corrections and additions (`tests/test_ad1340_s2b_restore_route.py`)
**Imports, in addition to Section 8's list:** from `tests.test_ad1340_s2b_restore` import `_pause_in`, `_fail_insert`, `_archive_one`, `_two_crafted_versions`, `_STORED_VALUE_MARKER`, `_NO_SIDECARS`, `_LIVE_SIDECARS` and `_CAPTAIN`. From `tests.test_ad1340_s1_eviction` import `_archive_rows`. From `tests.test_ad1340_s2a_archive_lookup` import `_write`. Also import `decode_payload`, `ArchiveRecord`, `EpisodeArchiveError` and `LogRedactionFormatter`. These helpers take the lookup-route rig unchanged: both `_Rig` classes carry `em`, `root`, `activations` and `participants` over the same file layout. `_GatedRead` is no longer imported directly. Drop the `raise_app_exceptions=False` sentence: the route catches `Exception`, so `_client` as built is right everywhere.

**Test-local helpers.**
- `_arm_marked_access_failure(archive, episode_id)`: S2a's `_arm_failing_access` (`test_ad1340_s2a_archive_lookup.py:191-197`) with the RAISE message `'injected access failure on <_STORED_VALUE_MARKER>'`. It is a real SQLite failure on the archive's own connection, so both `record_access` and the lookups' access insert hit it.
- `_marked_driver_error_premise(archive, episode_id) -> str`: `with pytest.raises(sqlite3.Error, match=_STORED_VALUE_MARKER) as raised: await archive.record_access(episode_id, accessor="premise", purpose="restore")`. Assert no `archive_access` row was written. Return `type(raised.value).__name__`, the driver's type name, which the log must show.
- `_probos_texts(caplog)`: every captured record whose `name` starts with `"probos"` and `levelno >= logging.INFO`, rendered with `LogRedactionFormatter("%(message)s")`. Call `caplog.set_level(logging.INFO)` before the request.
- `_route_errors(caplog)`: the records with `name == "probos.routers.security"` and `levelno == logging.ERROR`.

**Corrections to the existing items.**
- **RR-d, already live:** a live id that was never archived answers 404 (`episodic.py:3092-3093`). Archive the id, restore it once (200), then send the second request: 409 `episode_archive_restore_live_id`, with **no further** access row (exactly one, from the first restore) and the live record unchanged. **At capacity:** R-1's setup exactly (`max_episodes=2`: store `ep-000` and `ep-001`, archive `ep-000` with Step 12's call, store `ep-002`). Never store past the budget during setup: `store()` would evict by itself (A1.8 R-8).
- **RR-e:** iterate `[state for state, _ in _UNAVAILABLE]`. Every state answers 503 `episode_archive_unavailable`, restore's own state check (`episodic.py:3084-3085`). The second element of each tuple is the LOOKUP's code and is not used.
- **RR-f:** pause with `_pause_in(rig, monkeypatch, "archive_read")` and `_pause_in(rig, monkeypatch, "participant_insert")`. Send the request as `asyncio.create_task(_post(client, _RESTORE, {"episode_id": id}, headers=_AUTH))`. Premise: the pause was reached, and `await em.stop()` completed while the task was still pending. Before the reopen, drop every reference the test holds to the request task, the response and the events, then call `gc.collect()`, as R-4 does (A1.8). If the reopen still raises `database is locked`, stop and report; do not add a sleep or a retry.
- **RR-g:** `_fail_insert(rig, monkeypatch, "participant_index")`.
- **RR-i (reworked)** `test_restore_route_maps_an_unexpected_failure_to_a_typed_500_and_logs_no_text`: archive the subject; `_arm_marked_access_failure`; `name = _marked_driver_error_premise(...)`. Then: 500 `{"detail": "episode_archive_restore_failed"}`. Exactly one `_route_errors` record, whose `getMessage()` contains `subject[:8]`, `"failed unexpectedly"` and `name`, and whose `exc_info is None`. `_STORED_VALUE_MARKER` is in none of `_probos_texts`. Not live, `_NO_SIDECARS`, `_access_rows == []`.
- **RR-j:** use `_two_crafted_versions(rig, id, {"0" * 64: 7000.0, "f" * 64: 7000.0})`.
- **RR-k:** `await _traces(em, root, id)` (it is `async def`, `test_ad1340_s1_erasure.py:146`).

**New tests.**
- **RR-m** `test_restore_route_reports_a_real_chroma_rejection_without_copying_stored_metadata_into_the_log` (the reviewer's case, no injection): archive the subject; take its one archived row; decode it. Archive the crafted version `{**metadata, "content_hash": "f" * 64, _STORED_VALUE_MARKER: {_STORED_VALUE_MARKER: "x"}}`. A different `content_hash` matters, because the same key would upsert onto the original row. Delete the original row with `_write`; premise: only the crafted version remains. Premise probe: `with pytest.raises(Exception) as rejected: em._collection.add(ids=["rr-m-probe"], documents=[document], metadatas=[crafted])` (test-only). The marker is in `str(rejected.value)`, and `_raw(em, ["rr-m-probe"])["ids"] == []`. Record `name = type(rejected.value).__name__`, then `del rejected`. Request: 500 `{"detail": "episode_archive_restore_incomplete:live_add"}`. Exactly one `_route_errors` record: its message contains `subject[:8]`, `episode_archive_restore_incomplete:live_add` and `name`, and its `exc_info is None`. The marker is in none of `_probos_texts`, which covers the episodic WARNING too. Not live, `_NO_SIDECARS`, `_access_rows == [(_CAPTAIN, "restore")]`.
- **RR-n** `test_restore_route_never_answers_or_logs_free_text_as_a_code`: test-only `monkeypatch.setattr(rig.em, "restore_from_archive", raiser)`, whose `raiser` raises `EpisodeArchiveError(f"restore failed on {_STORED_VALUE_MARKER}: {{'k': 'v'}}")`. This is the route's own guard; every real raise site is a code (A2 Absence Verified). Expect 500 `{"detail": "episode_archive_restore_failed"}` and the marker absent from `response.text`. One `_route_errors` record, whose message contains `episode_archive_restore_failed` and `EpisodeArchiveError`. The marker is in none of `_probos_texts`.
- **RR-o** `test_lookup_route_logs_no_exception_text`: archive the subject; `_arm_marked_access_failure`; `name = _marked_driver_error_premise(...)`. Lookup by id: 500 `{"detail": "episode_archive_access_not_recorded"}`. One `_route_errors` record: its message contains `episode_archive_access_not_recorded` and `name`, and its `exc_info is None`. The marker is in none of `_probos_texts`.

Part 2 now has 15 test functions (RR-a to RR-o). RR-m, RR-n and RR-o join the error and privacy boundaries. M5's first commit set is unchanged (Section 7 plus A2.1 to A2.4, with RR-a to RR-e green). RR-f to RR-o are M5b.

### A2.6 Partition P5 additions (whole stripped lines, each unique in the built `security.py`; count first)
| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| RT9 | `src/probos/routers/security.py` | `logger.error("AD-1340 S2b: archive restore of %s failed: %s (%s)", request.episode_id[:8], code, type(exc.__cause__ or exc).__name__)` | `logger.error("AD-1340 S2b: archive restore of %s failed: %s (%s)", request.episode_id[:8], code, type(exc.__cause__ or exc).__name__, exc_info=True)` | RR-m |
| RT10 | `src/probos/routers/security.py` | `logger.error("AD-1340 S2b: archive restore of %s failed unexpectedly (%s)", request.episode_id[:8], type(exc).__name__)` | `logger.error("AD-1340 S2b: archive restore of %s failed unexpectedly (%s)", request.episode_id[:8], type(exc).__name__, exc_info=True)` | RR-i |
| RT11 | `src/probos/routers/security.py` | `logger.error("AD-1340 S2b: archive restore of %s failed unexpectedly (%s)", request.episode_id[:8], type(exc).__name__)` | `logger.error("AD-1340 S2b: archive restore of %s failed unexpectedly (%s)", request.episode_id[:8], exc)` | RR-i |
| RT12 | `src/probos/routers/security.py` | `return text if _ARCHIVE_ERROR_CODE.fullmatch(text) else fallback` | `return text  # AD-1340 S2b mutant RT12` | RR-n |
| RT13 | `src/probos/routers/security.py` | `raise HTTPException(status_code=500, detail=code) from exc` | `raise HTTPException(status_code=500, detail=str(exc)) from exc` | RR-n |
| RT14 | `src/probos/routers/security.py` | `logger.error("AD-1340 S2a: archive lookup failed: %s (%s)", code, type(exc.__cause__ or exc).__name__)` | `logger.error("AD-1340 S2a: archive lookup failed: %s (%s)", code, type(exc.__cause__ or exc).__name__, exc_info=True)` | RR-o |

RT8 (`raise HTTPException(status_code=500, detail="episode_archive_restore_failed") from exc` replaced by `raise`) is still killed by RR-i: the raw driver error reaches the test's client. On the Part 2 tree, S2a's N23 to N25 and N28 to N32 re-run unchanged. None of them anchors the lookup lines A2.4 changes. N25's `except EpisodeArchiveUnavailable as exc:` stays unique as a whole line because the route's copy carries a comment.

### A2.7 Supersessions (the original lines stay where they are)
- **Line 5:** Part 2 has 15 new test functions.
- **D10, Audit (line 95):** "The route logs at ERROR the id's first 8 characters, the error code and an exception type name, and at INFO the restored id. It never logs content, an exception's text or a cause's text (A2)."
- **D11 (lines 109-111, and A1.4's D11 bullet):** every 500 detail is `_archive_error_code(exc, "episode_archive_restore_failed")`. Rows: 500 `episode_archive_restore_incomplete:<store>`, where `<store>` is one of `episode_fts`, `participant_index`, `activation` or `live_add`: undone, nothing live. 500 `episode_archive_restore_unconfirmed`: the add raised and the store reports the id or cannot be asked; rows kept; a retry answers 409 `episode_archive_restore_live_id` if it landed, or 200 if it did not. 500 integrity codes. 500 `episode_archive_restore_failed`: any other exception, or an `EpisodeArchiveError` whose text is not a code. Every 500 is logged at ERROR as in D10.
- **Line 1110, lines 1126-1127, line 1129:** replaced by A2.3.
- **Line 1137:** imports per A2.5; the `raise_app_exceptions` sentence is withdrawn.
- **Lines 1142-1144, 1147, 1149:** per A2.5. **Line 1156:** Part 2 is RR-a to RR-o (15 functions).
- **Property 15:** "...the logs carry an id prefix, codes and exception type names, never document or metadata values, exception text or `exc_info` (RR-i, RR-m, RR-n, RR-o)."
- **Property 16:** "`/forget` is byte-identical. `/archive/lookup` is byte-identical except its ERROR log (A2.4); its responses are unchanged."

### A2.8 What Part 1 taught that Part 2 absorbs
1. **Windows clock ties:** no Part 2 assertion may order by `archived_at` or `accessed_at` unless the times are forced. RR-j forces them (`_two_crafted_versions`). RR-k orders access rows by `id`.
2. **A failed read pins its cursor** (A1.8 R-4): RR-f clears references and calls `gc.collect()` before the reopen. `caplog` records with `exc_info` would hold the same references; A2 removes them.
3. **A budget-exceeding setup auto-evicts** (A1.8 R-8): RR-d uses `max_episodes=2` exactly.
4. **The phantom-API precheck** flags `restore_from_archive(accessor=...)` in this contract's own fences. Commit the contract with A2 before staging any build files, so the preflight scans committed text only.
5. **The coarse-clock plugin path** (`C:/Users/seang/.copilot/session-state/9ccf7828-.../files`) lives in a Copilot session directory and was not verified here. Confirm it exists before M5's coarse-clock pair; if it does not, stop and report.

**Absence Verified (A2, 2026-10-18).**
- CLAIM: every `EpisodeArchiveError`-family raise that restore or lookup can reach passes a code-shaped text. RUN: `rg -n "raise (EpisodeArchive\w*|EpisodeErasureIncomplete)\(" src/probos/cognitive/episode_archive.py`, plus Read of `episodic.py:3080-3164`. FOUND: `episode_archive.py:270, 274, 281, 286, 430, 472, 477, 494` (constants), `:659` (`rows_undecodable:{n}`, in `iter_records`, not on either route); `episodic.py:3085, 3093, 3098, 3100, 3158, 3164` (`:{stage}`, one of four literals) and `_require_same_collection` (`episode_restore_interrupted_by_stop`). HOLDS: yes.
- CLAIM: `re`, `_ARCHIVE_ERROR_CODE` and `_archive_error_code` are absent from `security.py`. RUN: Grep of `security.py` for `^import|^from` and for the names. FOUND: imports `json`, `logging`, `math`, `pathlib`, `typing` (`:5-9`); no match for the names. HOLDS: yes.
- CLAIM: nothing in `src/probos` disables log propagation or installs a 5xx exception logger that would bypass A2. RUN: `rg -n "propagate\s*=|dictConfig|basicConfig" src/probos`; `rg -n "exception_handler|exc_info" src/probos/api.py src/probos/routers/{deps,auth}.py`. FOUND: no match. HOLDS: yes.

## Amendment A3 (2026-10-18): unpaired surrogates, escaped log prefixes, and a code in every 500 log line

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-18. A read-only consult after Part 2's review round 1 (GPT-6.1 Sol: F1 P2, F2 P2, F3 P3) and the orchestrator's mutation pass (XR8 and XR9 survived). The orchestrator appends it, so no line number above moves. It supersedes the contract lines named in A3.7. Every SEARCH is against the BUILT `src/probos/routers/security.py` (sha256 `7F179FF0…4C1D4F1E`, tree `ba87d6a8`). Decision recorded on #1568.

**Gaps.**
- **F1 (ordinary reach).** An unpaired surrogate gets through `json.loads`, either as a `\ud800` escape or as raw CESU-8 bytes (`json.loads` decodes bytes with `surrogatepass`). Pydantic refuses it (`string_unicode`, or it echoes it in an `extra_forbidden`/`model_attributes_type` error). The framework's 422 renderer then cannot encode that error as UTF-8, and the reply is a 500 `text/plain` with no route log and no access row. Measured by the orchestrator on both archive routes (`/archive/restore`, `/archive/lookup`) for a value, a longer value, an object key and a nested list. The S2a body guard (`security.py:166-177`) covers only non-finite numbers. This is the same class as #1523 F-139.
- **F2 (injected only, a regression introduced by A2).** Both 500 log lines (`security.py:288`, `:291`) interpolate `request.episode_id[:8]` with `%s`, so a line break in caller text splits the log record. Cutting the id to 8 characters limits its length but does not sanitise it.
- **F3 (injected only).** The unexpected-failure line (`:291`) carries no error code, which contradicts A2's D10.
- **XR8 / XR9.** No test pins the 8-character prefix, because every test id is `ep-000`.

### A3.1 `src/probos/routers/security.py`: the refusal code (against `security.py:108-110`)
SEARCH:
```python
_ARCHIVE_LOOKUP_ACCESSOR = "captain:/api/security/archive/lookup"
_ARCHIVE_LOOKUP_TOKEN_REQUIRED = "episode_archive_lookup_requires_token"
_NON_FINITE_NUMBER_IN_BODY = "non_finite_number_in_body"
```
REPLACE:
```python
_ARCHIVE_LOOKUP_ACCESSOR = "captain:/api/security/archive/lookup"
_ARCHIVE_LOOKUP_TOKEN_REQUIRED = "episode_archive_lookup_requires_token"
_NON_FINITE_NUMBER_IN_BODY = "non_finite_number_in_body"
_UNPAIRED_SURROGATE_IN_BODY = "unpaired_surrogate_in_body"  # AD-1340 S2b A3
```

### A3.2 The shared body guard (against `security.py:159-177`; the name stays, so S2a's `dependencies=` anchors hold)
SEARCH:
```python
def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise _NonFiniteNumberInBody(text)
    return value


async def _refuse_non_finite_numbers(request: Request) -> None:
    """AD-1340 S2a: 422 for a body holding a non-finite number, before validation runs.

    The framework's 422 handler echoes the offending input, cannot JSON-encode NaN or Infinity, and answers 500
    (follow-up on #1523). Re-reads the body the framework already cached; reads no runtime state, writes nothing.
    """
    try:
        json.loads(await request.body(), parse_constant=_refuse_constant, parse_float=_finite_float)
    except _NonFiniteNumberInBody as exc:
        raise HTTPException(status_code=422, detail=_NON_FINITE_NUMBER_IN_BODY) from exc
    except ValueError:
        return  # AD-1340 S2a: malformed JSON is the framework's to refuse (it parses first)
```
REPLACE:
```python
def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise _NonFiniteNumberInBody(text)
    return value


def _holds_unpaired_surrogate(parsed: Any) -> bool:
    """AD-1340 S2b A3: whether a parsed JSON body holds, in any key or value at any depth, an unpaired surrogate.

    ``json`` joins an escaped surrogate pair into one character and decodes raw bytes with ``surrogatepass``, so an
    unpaired one, escaped or raw, survives parsing. Strict UTF-8, which the framework's 422 renderer uses, cannot
    encode it. Iterative, so a body nested as deep as the parser allows cannot exhaust the stack.
    """
    pending: list[Any] = [parsed]
    while pending:
        value = pending.pop()
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                return True
        elif isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return False


async def _refuse_non_finite_numbers(request: Request) -> None:
    """AD-1340 S2a: 422 for a body holding a non-finite number, before validation runs.

    The framework's 422 handler echoes the offending input, cannot JSON-encode NaN or Infinity, and answers 500
    (follow-up on #1523). Re-reads the body the framework already cached; reads no runtime state, writes nothing.
    AD-1340 S2b A3: the same for an unpaired surrogate, which that handler cannot encode as UTF-8. A non-finite
    number is refused first (while parsing). Neither answer echoes the body. The name is kept for S2a's anchors.
    """
    try:
        parsed = json.loads(await request.body(), parse_constant=_refuse_constant, parse_float=_finite_float)
    except _NonFiniteNumberInBody as exc:
        raise HTTPException(status_code=422, detail=_NON_FINITE_NUMBER_IN_BODY) from exc
    except ValueError:
        return  # AD-1340 S2a: malformed JSON is the framework's to refuse (it parses first)
    # AD-1340 S2b A3: outside the try, and a bool rather than a raise: UnicodeEncodeError is a ValueError.
    if _holds_unpaired_surrogate(parsed):
        raise HTTPException(status_code=422, detail=_UNPAIRED_SURROGATE_IN_BODY)
```

### A3.3 The restore route's docstring and its two 500 log lines (against `security.py:270-271` and `:286-292`)
SEARCH:
```python
    ``episode_archive_restore_live_id``. AD-1340 S2b A2: an error is logged as the id's first 8 characters, the
    error code and an exception type name, never an exception's text or its cause's.
    """
```
REPLACE:
```python
    ``episode_archive_restore_live_id``. AD-1340 S2b A2/A3: an error is logged as the ``repr`` of the id's first 8
    characters, the error code and an exception type name, never an exception's text or its cause's.
    """
```
SEARCH:
```python
    except EpisodeArchiveError as exc:
        code = _archive_error_code(exc, "episode_archive_restore_failed")  # AD-1340 S2b A2: a code, never the text
        logger.error("AD-1340 S2b: archive restore of %s failed: %s (%s)", request.episode_id[:8], code, type(exc.__cause__ or exc).__name__)
        raise HTTPException(status_code=500, detail=code) from exc
    except Exception as exc:
        logger.error("AD-1340 S2b: archive restore of %s failed unexpectedly (%s)", request.episode_id[:8], type(exc).__name__)
        raise HTTPException(status_code=500, detail="episode_archive_restore_failed") from exc
```
REPLACE:
```python
    except EpisodeArchiveError as exc:
        code = _archive_error_code(exc, "episode_archive_restore_failed")  # AD-1340 S2b A2: a code, never the text
        # AD-1340 S2b A3: %r escapes a line break or ESC in caller text; the 8-character cut is a bound, not a sanitiser.
        logger.error("AD-1340 S2b: archive restore of %r failed: %s (%s)", request.episode_id[:8], code, type(exc.__cause__ or exc).__name__)
        raise HTTPException(status_code=500, detail=code) from exc
    except Exception as exc:
        logger.error("AD-1340 S2b: archive restore of %r failed unexpectedly: episode_archive_restore_failed (%s)", request.episode_id[:8], type(exc).__name__)
        raise HTTPException(status_code=500, detail="episode_archive_restore_failed") from exc
```
These lines stay unchanged: RT8's anchor (`raise HTTPException(status_code=500, detail="episode_archive_restore_failed") from exc`), RT12, RT13, RT14 (the lookup's ERROR line) and the success INFO line.

### A3.4 Test corrections (`tests/test_ad1340_s2b_restore_route.py`)
- **RR-i:** the message assertion becomes `repr(eid[:8]) in message and "failed unexpectedly" in message and "episode_archive_restore_failed" in message and name in message` (F3).
- **RR-m:** `repr(subject[:8]) in message` replaces `subject[:8] in message`.
- **RR-n:** add `repr(eid[:8]) in message`.
- **RR-o:** unchanged (RT14 is unchanged).
- **Imports:** add `from probos.routers.security import _holds_unpaired_surrogate` (test-only private import, for RR-r).

### A3.5 New tests
- **RR-p** `test_restore_route_logs_only_an_escaped_prefix_of_the_requested_id`. Parametrized `(raised, code, type_name)` over branch 1 `(EpisodeArchiveError("episode_archive_restore_incomplete:live_add"), "episode_archive_restore_incomplete:live_add", "EpisodeArchiveError")` and branch 2 `(RuntimeError("boom"), "episode_archive_restore_failed", "RuntimeError")`.
  - Setup: `caplog.set_level(logging.INFO)`, then `requested = "ab\ncd\x1bf\r" + "ijklmnop" * 4` (40 characters; the first 8 hold LF, ESC and CR).
  - Inside `_memory(tmp_path, "archive")`: `monkeypatch.setattr(rig.em, "restore_from_archive", raiser)` (test-only), where `raiser(episode_id, **kwargs)` appends to `asked` and raises `raised`.
  - Premise: `_route_errors(caplog) == []`.
  - Request: `_post(client, _RESTORE, {"episode_id": requested}, headers=_AUTH)`.
  - Assert:
    - `asked == [requested]` (validation passed the whole id through);
    - `(status, json) == (500, {"detail": code})`;
    - `[record] = _route_errors(caplog)`;
    - `message = record.getMessage()` contains `repr(requested[:8])`, `code` and `type_name`, and does not contain `"ijklmnop"`;
    - `record.exc_info is None`;
    - `rendered = LogRedactionFormatter("%(message)s").format(record)` contains none of `"\n"`, `"\r"`, `"\x1b"`, and does contain `repr(requested[:8])`;
    - no entry of `_probos_texts(caplog)` contains `"ijklmnop"`.
  - Kills XR8 and XR9 (as RT15 and RT16), RT17, RT18 and RT19.
- **RR-q** `test_archive_routes_refuse_an_unpaired_surrogate_without_echoing_it`. HTTP level, real app, through `_client` (an unfixed tree raises the framework's `UnicodeEncodeError` into the test, which counts as a failure). Parametrized over `path in (_RESTORE, _LOOKUP)` × the cases below. Every body is raw bytes, sent with `_post(client, path, content=..., headers=_JSON_HEADERS)`.

  | id | content | restore expects | lookup expects |
  |---|---|---|---|
  | `value` | `b'{"episode_id": "\\ud800"}'` | 422 `unpaired_surrogate_in_body` | same |
  | `inside_a_longer_value` | `b'{"episode_id": "ep-\\ud800-000"}'` | 422 `unpaired_surrogate_in_body` | same |
  | `low_surrogate_alone` | `b'{"episode_id": "\\udc00"}'` | 422 `unpaired_surrogate_in_body` | same |
  | `reversed_pair` | `b'{"episode_id": "\\ude00\\ud83d"}'` | 422 `unpaired_surrogate_in_body` | same |
  | `object_key` | `b'{"episode_id": "ep-000", "\\ud800": 1}'` | 422 `unpaired_surrogate_in_body` | same |
  | `nested_list` | `b'{"episode_id": "ep-000", "extra": [["\\ud800"]]}'` | 422 `unpaired_surrogate_in_body` | same |
  | `top_level_string` | `b'"\\ud800"'` | 422 `unpaired_surrogate_in_body` | same |
  | `raw_cesu_bytes` | `b'{"episode_id": "\xed\xa0\x80"}'` | 422 `unpaired_surrogate_in_body` | same |
  | `nan_first` | `b'{"episode_id": "\\ud800", "extra": NaN}'` | 422 `non_finite_number_in_body` | same |
  | `paired_surrogates` (premise) | `b'{"episode_id": "\\ud83d\\ude00"}'` | 404 `episode_archive_not_found` | 200, `episodes == []` |
  | `control_characters` (premise) | `b'{"episode_id": "ep\\n000\\u001b"}'` | 404 `episode_archive_not_found` | 200, `episodes == []` |

  - Setup: `eid = await _archive_one(rig, 0)`, with `eid == "ep-000"` as a premise.
  - Every 422 row asserts `(status, response.json()) == (422, {"detail": <code>})` and that `response.headers["content-type"]` starts with `application/json`.
  - Every row asserts: `_raw(rig.em, [eid])["ids"] == []`, `_access_rows(tmp_path, eid) == []`, `_count(tmp_path, "episode_archive", eid) == 1`, and `_route_errors(caplog) == []`.
  - The two premise rows prove that valid Unicode, including escaped control characters, still reaches the handler.
  - The `raw_cesu_bytes` row rests on `json.loads` decoding bytes with `surrogatepass` (CPython `json/__init__.py`), which the framework's body parse also uses. If it answers anything else on the fixed tree, stop and report; do not drop it.
- **RR-r** `test_unpaired_surrogate_walk_is_exact_and_iterative`. A direct call (no I/O). Note that a Python literal `"\ud83d\ude00"` is two unpaired code points; a joined pair is written `"\U0001f600"`.
  - True for: `"\ud800"`, `"\udc00"`, `"\ud83d\ude00"`, `{"k\ud800": 1}`, `{"k": ["a", {"b": "\udfff"}]}`.
  - False for: `"\U0001f600"`, `"ep\n000\x1b"`, `[1, 2.5, None, True, "ok", {"a": "é"}]`, `{}`, `[]`.
  - Depth: build `deep = "\ud800"`, then `for _ in range(10_000): deep = [deep]`; assert True. The same built around `"ok"` gives False. The same built through dict keys, `deep = {deep_key: 0}` with the surrogate in the innermost key, gives True. A recursive walk raises `RecursionError` here.

Part 2 now has 18 test functions (RR-a to RR-r). RR-p to RR-r join M5b.

### A3.6 Partition P5 rows (whole stripped lines, each unique in the A3-built `security.py`; count each before mutating). RT9 to RT11 replace A2.6's rows.
| ID | SEARCH | REPLACE | Killed by |
|---|---|---|---|
| RT9 | `logger.error("AD-1340 S2b: archive restore of %r failed: %s (%s)", request.episode_id[:8], code, type(exc.__cause__ or exc).__name__)` | same + `, exc_info=True` before `)` | RR-m |
| RT10 | `logger.error("AD-1340 S2b: archive restore of %r failed unexpectedly: episode_archive_restore_failed (%s)", request.episode_id[:8], type(exc).__name__)` | same + `, exc_info=True` before `)` | RR-i |
| RT11 | (RT10's line) | `logger.error("AD-1340 S2b: archive restore of %r failed unexpectedly: episode_archive_restore_failed (%s)", request.episode_id[:8], exc)` | RR-i |
| RT15 (XR8) | (RT9's line) | `request.episode_id[:8]` → `request.episode_id` | RR-p[branch 1] |
| RT16 (XR9) | (RT10's line) | `request.episode_id[:8]` → `request.episode_id` | RR-p[branch 2] |
| RT17 | (RT9's line) | `%r` → `%s` | RR-p[branch 1] |
| RT18 | (RT10's line) | `%r` → `%s` | RR-p[branch 2] |
| RT19 | (RT10's line) | `failed unexpectedly: episode_archive_restore_failed (%s)` → `failed unexpectedly (%s)` | RR-i, RR-p[branch 2] |
| RT20 | `if _holds_unpaired_surrogate(parsed):` | `if False:` | RR-q |
| RT21 | `value.encode("utf-8")` | `value.encode("utf-8", "surrogatepass")` | RR-q, RR-r |
| RT22 | `pending.extend(value.keys())` | `pass  # AD-1340 S2b mutant RT22` | RR-q[object_key], RR-r |
| RT23 | `pending.extend(value.values())` | `pass  # AD-1340 S2b mutant RT23` | RR-q[value], RR-r |
| RT24 | `pending.extend(value)` | `pass  # AD-1340 S2b mutant RT24` | RR-q[nested_list], RR-r |
| RT25 | `raise HTTPException(status_code=422, detail=_UNPAIRED_SURROGATE_IN_BODY)` | `return` | RR-q |
| N30a (replaces S2a N30 on this tree) | `parsed = json.loads(await request.body(), parse_constant=_refuse_constant, parse_float=_finite_float)` | `parsed = json.loads(await request.body(), parse_float=_finite_float)` | S2a RT-e, RR-h[unknown_field_with_nan], RR-q[nan_first] |

Also re-run, with unchanged anchors:
- RT8, RT12, RT13, RT14 and the rest of P5 (`security.py` has a new sha256);
- S2a's N23, N24, N25, N28, N29, N31, N32 (the shared guard changed). N24, N28 and N29 stay whole-line unique: the restore route's `dependencies=` copy carries a comment.

Mark the result the campaign of record against the A3-built `security.py` sha256 and the test file's sha256.

### A3.7 Supersessions (the original lines stay)
- **Line 5 / A2.7:** Part 2 has 18 test functions (RR-a to RR-r).
- **D10 / A2.7's D10:** "The route logs at ERROR the `repr` of the id's first 8 characters, the error code (the unexpected branch logs `episode_archive_restore_failed`) and an exception type name, and at INFO the restored id. It never logs content, an exception's text or a cause's text (A2, A3)."
- **Validation:** a body holding an unpaired surrogate, in any key or value at any depth, answers 422 `{"detail": "unpaired_surrogate_in_body"}` on both archive routes, before validation and without echoing the body. A body that also holds a non-finite number answers `non_finite_number_in_body`.
- **Property 15:** add RR-p ("the id prefix is escaped and cut to 8 characters").
- **Property 16:** "`/forget` is byte-identical. `/archive/lookup` is byte-identical except its ERROR log (A2.4) and its shared body guard (A3.2): a body with an unpaired surrogate now answers a typed 422 where it answered 500. Its other responses are unchanged."
- **A2.6 RT9 to RT11:** replaced by A3.6. **S2a N30:** re-anchored as N30a on this tree (the S2a contract text stays as merged).

### A3.8 Considered, deferred
- **An app-wide `RequestValidationError` handler** (`api.py`; today only `IntentAuthorizationDenied` has one, at `api.py:165`). It would fix this class for every route, but it changes every route's 422 wire shape. It goes to the consolidated #1523 follow-up F-151, together with `/forget`.
- **Reusing BF-875's `_encodes_as_utf8`** (`federation/mcp_server.py:107-113`, re-serialise and encode). Same principle, but it is a private function in another layer and needs a `RecursionError` branch. Adapted, not imported.
- **`config_models/operations.py:65` `_has_surrogate`.** A private function in another layer, and a range test is less exact than the encoder the renderer uses.

**Absence Verified (A3, 2026-10-18).**
- CLAIM: `_UNPAIRED_SURROGATE_IN_BODY` and `_holds_unpaired_surrogate` are absent from `src/`. RUN: Grep `_refuse_non_finite_numbers|_holds_unpaired_surrogate|unpaired_surrogate|\.encode\(|pending` over `src/**/routers/*.py`. FOUND: `security.py:166, 182, 257` (the guard and its two uses) and no `.encode(` or `pending` in `security.py`. HOLDS: yes, so RT21 to RT24's anchors will be unique.
- CLAIM: no test pins the log lines or the guard's `json.loads` line as source text. RUN: Grep `archive restore of|parse_constant=_refuse_constant|episode_id\[:8\]` and `_refuse_non_finite_numbers` over `tests/`. FOUND: only `test_ad1340_s2b_restore_route.py:673` (a substring that A3 keeps). HOLDS: yes.
- CLAIM: nothing outside `security.py` uses the guard. RUN: the same Grep over `src/`. FOUND: only `security.py`. HOLDS: yes.
- CLAIM: no app-level validation or exception handler would intercept first. RUN: Grep `exception_handler|RequestValidationError` over `src/probos`. FOUND: only `api.py:165` (`IntentAuthorizationDenied`). HOLDS: yes.
- CLAIM: no test id is longer than 8 characters before RR-p. Evidence: the orchestrator's mutation pass (XR8 and XR9 survived all 26 cases). HOLDS: yes.
