# BF-902: The FTS keyword index goes with the episodes it indexes (Tier 2 reset, start-up reconciliation, counted eviction warning)

**One line.** `episode_fts.db` and the two other per-episode index files are added to the Tier 2 reset. A bounded start-up reconciliation deletes FTS rows whose id is not in the live ChromaDB collection, which repairs the vessel's 4,167 stale rows at its next start. A failed FTS delete during eviction is reported at WARNING with a count.

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-17
**Status:** Ready to build. One milestone.
**Issue:** #1579 (label `bug`). The issue title allocates BF-902. This contract allocates no new AD or BF number.
**Base:** the AD-1340 S1 head `c1353655` (PR #1583), which is what `main` holds once #1583 merges. Every anchor below was re-taken on this tree. The issue's anchors were taken on `f89d72a9` and many have moved (see **Anchors moved since the issue**).
**Dependencies:** AD-1340 S1 (#1568) must be merged first. This change edits S1's `_delete_fts_rows`, S1's reset pin test and the store write lock that S1 introduced (Amendments R1 to R3).
**Estimated tests:** 15 new tests in `tests/test_bf902_fts_reconciliation.py`, plus one deliberate edit to S1's T5 pin in `tests/test_ad1340_s1_restore_reset.py`.
**Files changed:** `src/probos/cognitive/episodic.py`, `src/probos/__main__.py`, `tests/test_ad1340_s1_restore_reset.py`, `tests/test_bf902_fts_reconciliation.py` (new), and the trackers `PROGRESS.md`, `docs/development/roadmap.md` and `DECISIONS.md`.

---

## Problem

The FTS5 keyword sidecar `episode_fts.db` is derived from the `episodes` ChromaDB collection, but nothing keeps the two in step:

1. **No reset tier clears it.** `RESET_TIERS` (`src/probos/__main__.py:2603-2637`) has Tier 2 delete `chroma.sqlite3`, and since S1 also `episode_archive.db` (`:2620`). No tier lists `episode_fts.db`, `participant_index.db` or `activation_tracker.db` (Absence 1). After a Tier 2 reset ("New ship, new crew", `:2615`), the previous crew's indexed text (`user_input + " " + reflection`, `episodic.py:2060`) stays on disk.
2. **Eviction cleanup reports failures only at DEBUG.** S1's Amendment R1 already fixed the "one failure spares the rest" half: `_delete_fts_rows` (`episodic.py:1211-1225`) deletes each id independently and keeps sweeping. But a failure is logged only at DEBUG (`:1218`, `:1223`). In the non-strict path (`_cleanup_sidecars`, `:2595-2597`), `failures` is collected and then discarded unless `strict` (`:2618`). An operator never learns that rows were left behind.
3. **Nothing reconciles the index at start** (Absence 2). The live index holds 4,725 rows and 4,714 distinct ids, against 547 live episodes. 4,167 ids name no episode and 0 live episodes are missing (the issue's read-only counts, 2026-10-15 and 2026-10-16). `keyword_search` (`episodic.py:4270-4301`) applies `LIMIT` before any check against the collection. Its callers (`:3271`, `:3483`, `:3746`, `:4542`) take `k*3` hits, and the AD-979c hybrid fuser cuts to `k` (`:3279`) before hydrating, then drops the missing ids (`:3286`). So a stale id that wins a slot both displaces a live hit and shortens the result. The issue's probe found 71.7% of top-30 keyword hits stale.

## Solution

| # | Change | Where |
|---|---|---|
| 1 | Add `episode_fts.db`, `participant_index.db` and `activation_tracker.db` to Tier 2 `files` (Tier 3 includes them, because tiers run cumulatively, `__main__.py:2920`). Add their `_file_purpose` labels. | `__main__.py` |
| 2 | Add `EpisodicMemory._reconcile_fts_index()`: keyset-paged over FTS rowids, with one collection read and one commit per page. Each page runs inside the store write lock, and each delete matches the row's `(rowid, episode_id)` pair. It never raises, deletes nothing once the collection cannot be read, and never reads the archive. | `episodic.py` |
| 3 | Call it once at the end of `EpisodicMemory.start()`, after the FTS sidecar and the archive are open. This is before warm-boot seed and before any `store()`. | `episodic.py` |
| 4 | `_delete_fts_rows` logs one WARNING with the count of ids it could not clean. Its boolean contract for the strict (ERASE) callers is unchanged. | `episodic.py` |
| 5 | Invert S1's T5 pin (`== []` becomes `== [2]`) deliberately, with the reason inline. | `tests/test_ad1340_s1_restore_reset.py` |

### Decided by the Architect (the orchestrator records each on #1579)

**D1. Reset tiers: `episode_fts.db` is in Tier 2 only (so Tier 3 too, cumulatively). Tier 1 is not.** An index must live exactly as long as the store it indexes. `chroma.sqlite3` is Tier 2 (`:2618`), and Tier 1 keeps it ("timeline intact", `:2607`). Clearing the FTS index at Tier 1 would leave live episodes with no keyword index and no rebuild path: the only repopulation is `seed()` for ids not already in the collection (`:1722-1735`), and the store declaration says so (`storage_declarations.py:108-114`). That would be a recall loss. Under the nature, culture and nurture decision (2026-10-16, applied by S1's D7, `DECISIONS.md:61`), episodes are nurture and reset with the crew, and an index of nurture is nurture. Ranked options: (a) **Tier 2 (chosen)**; (b) Tier 1 and up: rejected, recall loss with no rebuild; (c) Tier 3 only: rejected, because a new crew at Tier 2 would inherit the old crew's indexed text, which is the privacy defect itself.

**D2. The start-up reconciliation.** Ranked options:
- (a) **Chosen.** It runs inline at the end of `start()`, keyset-paged by FTS `rowid` (`_FTS_RECONCILE_PAGE = 500`). For each page, inside `self._get_store_write_lock()`, it reads ≤500 `(rowid, episode_id)` rows, asks the collection which of their distinct ids are live (`get(ids=..., include=[])`, which the existing caller already uses at `:2833`), and deletes only the non-live pairs with `executemany("DELETE FROM episode_fts WHERE rowid = ? AND episode_id = ?")`. Then it commits once for that page.
- (b) Filter stale ids inside `keyword_search`: rejected as the fix. It repairs recall but leaves the rows, and the old crew's text, on disk, and it costs a collection read on every query. Considered, not built.
- (c) A background task after `start()`: rejected. It adds a task that must be stored and cancelled, and makes test order non-deterministic, for no gain: the work is milliseconds at today's 4,725 rows and about 200 pages at 100,000.
- (d) Rebuild the index from the collection: rejected. FTS content is `user_input + " " + reflection`, not the Chroma document (`_prepare_document`), so a rebuild would rewrite live rows and put the golden test at risk.
- (e) One anti-join SQL statement that attaches `chroma.sqlite3`: rejected. It couples to Chroma's private schema.

The decisions inside option (a):
- **Where.** At the end of `start()`, after `_start_episode_archive` (`:1640-1641`). `init_cognitive_services` awaits `start()` at `cognitive_services.py:292`, before the activation tracker (`:296-307`), the participant index (`:449-457`), the AD-584 embedding migration (`:476-478`) and warm boot (`:553-569`, which calls `seed()` from `warm_boot.py:222`). So the reconciliation finishes before any seed or `store()`. An episode that warm boot re-seeds after a reset gets its FTS row from `seed()` itself (`:1723-1733`). The AD-584 migration deletes and re-creates the collection (`episodic.py:736`) after `start()` returns, so it never runs during the reconciliation.
- **How it reads live ids at scale.** It never reads the whole collection. It asks about the ids of one FTS page at a time (≤500 per `get`). So memory and each call are bounded by the page size, and the total work is linear in the FTS row count, not the collection size.
- **How it deletes.** Chunked, with one commit per page. A failure in page *n* leaves pages 1 to *n-1* committed and deletes nothing more. The next start resumes, because the operation is idempotent. It never calls `rollback()`: the FTS connection is shared with `store()` tails, and S1's F-133 records that this connection relies on not rolling back another coroutine's work.
- **Collection unavailable.** If `self._collection is None`, or `get` raises, or the answer is not a `Mapping` holding a `list` under `"ids"`, it deletes nothing from that page on and logs a WARNING. A degraded answer is never read as "no live ids".
- **Staying off the `store()` tail window.** `store()` adds to the collection inside the store write lock (`:2044-2052`) and inserts the FTS row after releasing it (`:2054-2079`, BF-669). `restore_from_archive` adds and inserts both inside the lock (`:2827-2859`). Because each page's live check and delete run under the same lock, no `store()` or restore can make an id live between the check and the delete. An FTS row from a pending tail belongs to an id that was already added before the page took the lock. So the id is either still live (the check keeps it) or has been evicted or erased since (the row is stale, and deleting it is correct; ERASE's own tail wait, R3, sweeps it as well). S1's R3 tail registry (`_get_store_tails`, `:1821`) therefore needs no separate check. The `(rowid, episode_id)` predicate adds a second guarantee: a row inserted after the page was read, even one that reuses a freed rowid, is never matched.
- **The archive is never read.** An id that exists only in the AD-1340 archive is stale for this index. S1's eviction removes its FTS row (`_remove_from_live`, `:2672`), and S2's archive text index will be a different file. So the reconciliation never consults `_archive_or_none()`.
- **Logging.** Every start writes one INFO line with the counts (`removed N of M row(s)`). A failure writes one WARNING with `exc_info`. An unavailable collection writes one WARNING saying nothing was deleted.
- **Rows with a non-string or empty id** are left alone and not counted. No writer produces them, and Chroma rejects empty ids in `get`.
- **No empty-collection guard.** A readable empty collection is the truth. That is exactly the vessel's first start after a Tier 2 reset under the old table. The FTS rows cannot restore an episode, and backup coverage includes the file (`storage_declarations.py:101`, `backup="included"`).

**D3. Eviction cleanup reporting.** S1's R1 already implemented "one failing id does not leave the rest un-cleaned" (`_delete_fts_rows`, `:1213-1219`). What remains is the WARNING with a count. It goes inside `_delete_fts_rows`, the single owner shared by the non-strict and strict paths (callers `:2571` and `:2596`, Absence 4). Each per-id failure adds one to `uncleaned`. A failed commit sets `uncleaned = len(ids)`, because nothing from the sweep is durable. A non-zero count writes one WARNING, and the function still returns `uncleaned == 0`. The strict path keeps its ERROR and its raise (`:2618-2622`), so an ERASE failure logs both, which is intended.

**D4. The sibling sidecars `participant_index.db` and `activation_tracker.db`.**
- *Is it in a reset tier?* Not today (Absence 1). **Decided: both join Tier 2 in this fix.** Reason: after Tier 2 every row in both files names an episode the same tier just deleted (`chroma.sqlite3`), so they are stale by construction. The participant index keeps the previous crew's callsigns per episode, which is the same breach of the reset contract as the FTS text. The activation log measured 986 MB on the vessel. Each file's own `start()` re-creates its schema (`participant_index.py:34`, `activation_tracker.py:45-52`, both `CREATE ... IF NOT EXISTS`). It is a one-line change to the table this fix already edits. Their retention (the 180-day activation log) is not changed.
- *Does anything reconcile it?* No. The only deletes are per-id cleanup on eviction (`participant_index.py:202`, `activation_tracker.py:309`) and the activation age prune (`activation_tracker.py:297`) (Absence 5). **Decided: not in this fix; recorded as a follow-up under the filing policy.** Reasons: (1) neither takes recall slots. The participant index only filters a ChromaDB `where` query (`episodic.py:4786-4792`), so a stale id matches nothing, and activation only ranks ids that were already retrieved. (2) Neither holds episode text. (3) Both have a different lifecycle owner: they are wired after `start()` by `init_cognitive_services` (`cognitive_services.py:296-307`, `:449-457`), so this reconciliation cannot reach them from `start()`. Severity of the follow-up: Low (disk and hygiene; privacy at reset is closed by Tier 2 above). One more fact for the follow-up: `participant_index.db` has no `StoreDeclaration` (Absence 6).

**D5. The golden test.** Keyword results for live episodes are recorded before any stale row exists. Stale rows that out-rank them are then injected, and the test proves they take slots. After a restart (which runs the reconciliation), the same queries must return the same ids in the same order with equal ranks. The corpus after reconciliation equals the corpus before injection, so FTS5's bm25 inputs are equal too (see Absence-not-confirmed (a)).

---

## Implementation

The Builder applies the sections in order. Each SEARCH block is unique in its file.

### Section 1: reset tiers (`src/probos/__main__.py`)

SEARCH:
```python
            # AD-1340: archived episodes are nurture; a new crew must not inherit them
            "episode_archive.db",
            "hebbian_weights.db", "trust.db", "service_profiles.db",
```
REPLACE:
```python
            # AD-1340: archived episodes are nurture; a new crew must not inherit them
            "episode_archive.db",
            # BF-902: the per-episode indexes go with the episodes they index (chroma.sqlite3 above)
            "episode_fts.db", "participant_index.db", "activation_tracker.db",
            "hebbian_weights.db", "trust.db", "service_profiles.db",
```

SEARCH:
```python
        "chroma.sqlite3": "Episodic memory",
        "episode_archive.db": "Episode archive",
        "cognitive_journal.db": "Cognitive journal",
```
REPLACE:
```python
        "chroma.sqlite3": "Episodic memory",
        "episode_archive.db": "Episode archive",
        "episode_fts.db": "Episode keyword index",
        "participant_index.db": "Episode participant index",
        "activation_tracker.db": "Episode activation log",
        "cognitive_journal.db": "Cognitive journal",
```

`_cmd_reset` itself is not edited.

### Section 2: S1's pin, inverted deliberately (`tests/test_ad1340_s1_restore_reset.py`)

This is the reviewed decision that S1's docstring anticipated (`:264-267`). Update it and keep it; never delete it.

SEARCH:
```python
    The last assertions pin what the reset does NOT list: ``episode_fts.db`` and the other sidecars survive every tier
    today, and BF-902 (#1579) owns changing that (D8). **BF-902 inverts the ``episode_fts.db`` assertion
    deliberately**, in the change that adds the sidecar to the table; it is that reviewed decision, not an edit to
    get past a failure here.
```
REPLACE:
```python
    The last assertions pin where the FTS5 sidecar sits. Until BF-902 it survived every tier (D8); **BF-902 (#1579)
    inverted that assertion deliberately**: ``episode_fts.db`` now goes with ``chroma.sqlite3`` in Tier 2 and no other
    tier. That is the reviewed decision recorded on #1579, not an edit to get past a failure here.
```

SEARCH:
```python
    # D8: BF-902 owns the FTS5 sidecar and the others. The loop sees the real table: it lists the archive above.
    assert [tier for tier, tier_def in RESET_TIERS.items() if "episode_fts.db" in tier_def.get("files", [])] == []
```
REPLACE:
```python
    # D8, inverted by BF-902 (#1579): the FTS5 sidecar goes with the episodes it indexes, in Tier 2 only.
    assert [tier for tier, tier_def in RESET_TIERS.items() if "episode_fts.db" in tier_def.get("files", [])] == [2]
```

### Section 3: the page constant and `Mapping` import (`src/probos/cognitive/episodic.py`)

SEARCH:
```python
from collections.abc import AsyncIterator
```
REPLACE:
```python
from collections.abc import AsyncIterator, Mapping
```
(Verified: `Mapping` appears nowhere in `episodic.py` today (Grep `Mapping`, no hit), so this import is needed. Mutation M3 depends on the name.)

SEARCH:
```python
# AD-1340 R1: the FTS5 sidecar file, beside ``db_path``; ERASE reaches it by this name.
_FTS_FILENAME = "episode_fts.db"
```
REPLACE:
```python
# AD-1340 R1: the FTS5 sidecar file, beside ``db_path``; ERASE reaches it by this name.
_FTS_FILENAME = "episode_fts.db"
# BF-902: rows the start-up FTS reconciliation reads, checks against the live collection and deletes per page.
_FTS_RECONCILE_PAGE = 500
```

### Section 4: the counted warning (`_delete_fts_rows`, `episodic.py:1211-1225`)

SEARCH:
```python
async def _delete_fts_rows(db: Any, ids: list[str]) -> bool:
    """AD-1340 R1: delete each id's FTS row independently; True only if every one and the commit succeeded."""
    cleared = True
    for eid in ids:
        try:
            await db.execute("DELETE FROM episode_fts WHERE episode_id = ?", (eid,))
        except Exception:
            logger.debug("AD-567b: FTS5 cleanup failed for %s", eid[:8], exc_info=True)
            cleared = False  # keep sweeping the remaining ids
    try:
        await db.commit()
    except Exception:
        logger.debug("AD-567b: FTS5 cleanup commit failed", exc_info=True)
        return False
    return cleared
```
REPLACE:
```python
async def _delete_fts_rows(db: Any, ids: list[str]) -> bool:
    """AD-1340 R1: delete each id's FTS row independently; True only if every one and the commit succeeded.

    BF-902: a failure is reported once at WARNING with the count of ids left uncleaned; the start-up
    FTS reconciliation removes rows that name no live episode.
    """
    uncleaned = 0
    for eid in ids:
        try:
            await db.execute("DELETE FROM episode_fts WHERE episode_id = ?", (eid,))
        except Exception:
            logger.debug("AD-567b: FTS5 cleanup failed for %s", eid[:8], exc_info=True)
            uncleaned += 1  # keep sweeping the remaining ids
    try:
        await db.commit()
    except Exception:
        logger.debug("AD-567b: FTS5 cleanup commit failed", exc_info=True)
        uncleaned = len(ids)  # nothing this sweep deleted is durable
    if uncleaned:
        logger.warning(
            "BF-902: FTS5 cleanup could not clear %d of %d episode id(s); "
            "the start-up FTS reconciliation removes rows that name no live episode",
            uncleaned, len(ids),
        )
    return uncleaned == 0
```

### Section 5: the reconciliation and its call in `start()` (`episodic.py`)

SEARCH (end of `start()`, `:1640-1643`):
```python
        # AD-1340: episode archive (cold, never read by recall)
        await self._start_episode_archive(db_dir)

    async def stop(self) -> None:
```
REPLACE:
```python
        # AD-1340: episode archive (cold, never read by recall)
        await self._start_episode_archive(db_dir)

        await self._reconcile_fts_index()  # BF-902: before any seed or store(); warm boot seeds after start returns

    async def stop(self) -> None:
```

SEARCH (end of `stop()`, `:1672-1675`):
```python
        self._collection = None
        self._client = None

    # ---- seeding (warm boot) -----------------------------------------
```
REPLACE:
```python
        self._collection = None
        self._client = None

    async def _reconcile_fts_index(self) -> int:
        """BF-902: delete FTS rows whose episode id is not in the live collection; returns the rows deleted.

        Runs once from start(), before warm boot seeds and before any store(). The
        collection is the source of truth. An id that is only in the AD-1340 archive
        is stale here too (eviction removed its FTS row; S2's archive text index is
        another file), so the archive is never read.

        Bounded: keyset pages of ``_FTS_RECONCILE_PAGE`` rows by rowid, one collection
        read of at most that many ids and one commit per page. Each page runs inside
        the store write lock, so no store() add or restore can make an id live between
        the live check and the delete. A row is deleted only by its (rowid, episode_id)
        pair, so a row written after the page was read is never matched. A missing
        collection, a failing read, or an answer without an id list deletes nothing
        from that page on (WARNING). Pages already committed stay deleted, and the next
        start resumes (idempotent). Never rolls back: the FTS connection is shared with
        store() tails (F-133). Never raises (log-and-degrade: the index is derived).
        """
        db = self._fts_db
        if db is None:
            return 0  # BF-902: no FTS sidecar is open, so there is nothing to reconcile
        lock = self._get_store_write_lock()
        removed = 0
        checked = 0
        last_rowid = -(2**63)
        try:
            while True:
                async with lock:  # BF-902: no store() or restore add lands between the live check and the delete
                    collection = self._collection
                    if collection is None:
                        logger.warning(
                            "BF-902: FTS reconciliation skipped: the episode collection is unavailable; "
                            "nothing was deleted"
                        )
                        return removed
                    cursor = await db.execute(
                        "SELECT rowid, episode_id FROM episode_fts WHERE rowid > ? ORDER BY rowid LIMIT ?",
                        (last_rowid, _FTS_RECONCILE_PAGE),
                    )
                    rows = list(await cursor.fetchall())
                    if not rows:
                        break
                    last_rowid = rows[-1][0]
                    checked += len(rows)
                    candidates = dict.fromkeys(eid for _rowid, eid in rows if isinstance(eid, str) and eid)
                    result = collection.get(ids=list(candidates), include=[]) if candidates else {"ids": []}
                    found = result.get("ids") if isinstance(result, Mapping) else None
                    if not isinstance(found, list):
                        raise TypeError("BF-902: the episode collection answered without an id list")
                    live = set(found)
                    stale = [(rowid, eid) for rowid, eid in rows if eid in candidates and eid not in live]
                    if stale:
                        await db.executemany("DELETE FROM episode_fts WHERE rowid = ? AND episode_id = ?", stale)
                        await db.commit()  # BF-902: one commit per page
                        removed += len(stale)
                    if len(rows) < _FTS_RECONCILE_PAGE:
                        break
        except Exception:
            logger.warning(
                "BF-902: FTS reconciliation stopped after removing %d row(s); "
                "the remaining rows are kept and the next start resumes",
                removed, exc_info=True,
            )
            return removed
        logger.info(
            "BF-902: FTS reconciliation removed %d of %d row(s) that named no live episode", removed, checked,
        )
        return removed

    # ---- seeding (warm boot) -----------------------------------------
```

Notes for the Builder:
- `removed` counts the pairs the page asked to delete. Under the start-time ordering above nothing writes concurrently, so this equals the rows deleted. Do not replace it with `cursor.rowcount`: FTS5 virtual-table change counting is not verified here.
- `except Exception` does not catch `asyncio.CancelledError` (a `BaseException`), so cancellation propagates. That is intended.
- Do not add `hasattr`/`getattr` guards around `self._collection.get`. A test double without the method should fail into the WARNING branch, and it does.

---

## Tests: `tests/test_bf902_fts_reconciliation.py` (new)

Use real stores on `tmp_path`, and reuse S1's rig and readers rather than copying them:

```python
from tests.test_ad1340_s1_eviction import _archive_rows, _episode, _ids, _memory, _query, _raw, _warnings
from tests.test_reset_integration import _run_reset
from probos.cognitive.episodic import _FTS_FILENAME
from probos.startup.cognitive_services import ACTIVATION_TRACKER_DB, PARTICIPANT_INDEX_DB
```
`_memory(root, mode)` (`test_ad1340_s1_eviction.py:87-118`) puts the FTS file at `root / "chroma" / "episode_fts.db"`. `_run_reset` (`test_reset_integration.py:44-57`) patches `_load_config_with_fallback` so `knowledge.repo_path` is `tmp_path / "knowledge"`, and patches `_default_data_dir`. That is the temporary knowledge path the issue requires, because `_cmd_reset` clears the knowledge subdirectories (`__main__.py:2985-2994`).

Test-local helpers (write them once):
- `_fts(root) -> Path`: `root / "chroma" / _FTS_FILENAME`.
- `_inject(path, rows: list[tuple[str, str]])`: writes `INSERT INTO episode_fts(episode_id, content) VALUES (?, ?)` through its own `sqlite3.connect(str(path), timeout=5)`, commits and closes. This reproduces the vessel's stale rows. It is safe while the memory is open, because the aiosqlite handle holds no open transaction between operations.
- `_rows(path) -> list[tuple[int, str]]`: `_query(path, "SELECT rowid, episode_id FROM episode_fts ORDER BY rowid")`.
- `_count(path, eid) -> int`, and `_content(path, eid) -> list[str]`.
- `_stale(i) -> tuple[str, str]`: `(f"gone-{i:03d}", "gone crew coolant loop reading section archived text")`.
- `_GetProxy(inner, *, fail_on_call: int | None = None, answer: Any = _UNSET)`: forwards `get` and records each call's `ids` list in `self.calls`. It raises `RuntimeError("injected")` on call number `fail_on_call`, or returns `answer` when set. Everything else goes through `__getattr__`.
- `_FtsProxy(inner, *, before_delete=None, fail_delete_id=None, fail_commit=False)`: forwards to the real FTS connection, in the pattern of S1's `_FtsTailProxy` (`test_ad1340_s1_restore_reset.py:545-560`).
  - `executemany`: on the first SQL that starts with `"DELETE FROM episode_fts WHERE rowid"`, awaits `before_delete()` first.
  - `execute`: raises `sqlite3.OperationalError("injected")` for `DELETE FROM episode_fts WHERE episode_id` when `params[0] == fail_delete_id`.
  - `commit`: raises once while `fail_commit` is armed.
  - Each test that installs a proxy as `em._fts_db` puts `proxy.inner` back before the rig exits.
- Logs: `caplog.set_level(logging.INFO, logger="probos.cognitive.episodic")`. Warnings go through S1's `_warnings(caplog, needle)`. Info lines use the same filter at `logging.INFO`.

Every test asserts its premise first. Tests are `async def` with no marker, like S1's.

| # | Test | Steps and assertions |
|---|---|---|
| T1 | `test_tier2_reset_deletes_every_episode_index` | Build a real `EpisodicMemory(db_path=str(data_dir / "episodic.db"), relevance_threshold=0.0, eviction_disposition="delete")`, so the files sit at the data-directory root as in production, plus `ParticipantIndex(db_path=str(data_dir / PARTICIPANT_INDEX_DB))` and `ActivationTracker(db_path=str(data_dir / ACTIVATION_TRACKER_DB))`, wired as in the S1 rig. Start them, store `_episode(0)` and `_episode(1)`, and call `await activations.record_access("ep-000")`. **Stop all three** in a `finally`, so no handle is open. Create the sentinel `tmp_path / "knowledge" / "episodes" / "old.json"`. Premise: `chroma.sqlite3` exists, the FTS file has 2 rows, `episode_participants` > 0 and `episode_access_log` > 0. Run `_run_reset(data_dir, tmp_path)`. Then: `chroma.sqlite3`, `episode_fts.db`, `participant_index.db` and `activation_tracker.db` all do not exist, and the sentinel is gone (proof that the reset used the temporary knowledge path). If an `unlink` fails with `PermissionError` on Windows, that is a hard stop for Architect triage. Do not weaken the test. |
| T2 | `test_tier1_reset_keeps_every_episode_index` | Same setup, then `_run_reset(data_dir, tmp_path, soft=True)`. Premise: `events.db` planted and gone afterwards (so Tier 1 ran). All four files still exist, and the FTS file still has 2 rows. |
| T3 | `test_reset_table_lists_the_indexes_in_tier2_only` | The three names equal the production constants (`_FTS_FILENAME`, `PARTICIPANT_INDEX_DB`, `ACTIVATION_TRACKER_DB`). Each is in `RESET_TIERS[2]["files"]` and in no other tier's `files`. `_file_purpose` returns `"Episode keyword index"`, `"Episode participant index"` and `"Episode activation log"`. |
| T4 | `test_start_removes_rows_that_name_no_live_episode` | First rig: store `_episode(0..2)`, then exit. Inject `_stale(0)`, `_stale(1)` twice, `_stale(2)`, and a duplicate row for live `ep-000`. Premise: the distinct FTS ids are `{ep-000, ep-001, ep-002, gone-000, gone-001, gone-002}`, there are 8 rows, and `ep-000` has 2 rows. Re-enter the rig on the same root (its `start()` reconciles). Then: the distinct ids equal the 3 live ids exactly, live rows are unchanged (`ep-000` has 2, the others 1, total 4), and exactly one INFO line contains `"BF-902: FTS reconciliation removed 4 of 8"`. |
| T5 | `test_reconciliation_is_idempotent` | After the T4 flow inside the second rig: `await em._reconcile_fts_index() == 0`, `_rows` is unchanged, and an INFO line contains `"removed 0 of 4"`. |
| T6 | `test_unreadable_collection_deletes_nothing` | Rig started, `ep-000` stored, two stale rows injected. Install `_GetProxy(em._collection, fail_on_call=1)`. The call returns 0, `_rows` is identical before and after, and exactly one WARNING contains `"stopped after removing 0"`. |
| T7 | `test_missing_collection_deletes_nothing` | Set `em._collection = None` temporarily (restore it before exit). The call returns 0, rows are unchanged, and one WARNING contains `"the episode collection is unavailable"`. |
| T8 | `test_answer_without_an_id_list_deletes_nothing` | `_GetProxy(..., answer={"ids": None})`. The call returns 0, rows are unchanged, and one WARNING contains `"stopped after removing 0"`. |
| T9 | `test_pages_are_bounded_and_a_failed_page_keeps_what_came_before` | `monkeypatch.setattr("probos.cognitive.episodic._FTS_RECONCILE_PAGE", 2)`. Start the rig, inject `gone-000` and `gone-001` (rowids 1 and 2), store `_episode(0..2)` (rowids 3 to 5), then inject `gone-002` (rowid 6). Premise: `[eid for _, eid in _rows]` is in exactly that order. Call 1 with `_GetProxy(fail_on_call=2)`: returns 2, `gone-000` and `gone-001` are gone, `gone-002` and all live rows remain, one WARNING. Call 2 with `_GetProxy()` (healthy): returns 1, and the distinct ids equal the live ids. Every recorded `calls` entry has `len(ids) <= 2`. |
| T10 | `test_store_of_a_stale_id_during_a_page_waits_for_the_page_and_keeps_its_new_row` | Rig started. Store `_episode(0)`, then inject `_stale(0)` (id `gone-000`, not live). `z = dataclasses.replace(_episode(5), id="gone-000", user_input="zulu fresh report of a returning id")`. In `before_delete`, record `held["lock_held"] = em._get_store_write_lock().locked()` and start `task = asyncio.create_task(em.store(z))`. Run `await em._reconcile_fts_index()`, then `await asyncio.wait_for(task, 10)`. Assertions: the call returned 1, `held["lock_held"] is True`, the task outcome is `EpisodeStoreOutcome.STORED`, `_raw(em, ["gone-000"])["ids"] == ["gone-000"]`, `gone-000` has exactly one FTS row, its content contains `"zulu"` and does not contain `"archived"`. |
| T11 | `test_a_row_that_reuses_a_freed_rowid_is_never_deleted` | Rig started, `ep-000` stored, `_stale(0)` injected. In `before_delete`, through `proxy.inner`, find `gone-000`'s rowid R, `DELETE ... WHERE rowid = ?`, then `INSERT INTO episode_fts(rowid, episode_id, content) VALUES (R, 'ep-000', 'alpha reused rowid live row')` and commit. After the call: `ep-000` has 2 FTS rows (its stored row and the one at R), and `gone-000` has 0. Do not assert the return value (see the Section 5 note). |
| T12 | `test_failed_fts_delete_in_eviction_warns_with_a_count_and_the_next_start_repairs_it` | Rig `"delete"`. Store `_episode(0..2)`, then install `_FtsProxy(fail_delete_id="ep-001")`. `await em.evict_by_ids(_ids(3), reason="activation_pruning") == 3`. Premise: `_raw` shows none of the three live. FTS counts: `ep-000` 0, `ep-001` 1, `ep-002` 0. Exactly one WARNING contains `"could not clear 1 of 3"`. Put the inner connection back and exit. Re-enter the rig on the same root: `ep-001` has 0 FTS rows. This one test crosses the seam: failed cleanup, then restart, then repaired. |
| T13 | `test_failed_fts_commit_in_eviction_warns_with_the_full_count` | Rig `"delete"`. Store `_episode(0..1)`, then arm `_FtsProxy(fail_commit=True)`. `evict_by_ids(_ids(2), reason="activation_pruning")`. Exactly one WARNING contains `"could not clear 2 of 2"`. |
| T14 | `test_an_archive_only_id_is_stale_for_the_fts_index` | Rig `"archive"`. Store `_episode(0..1)`. `await em.evict_by_ids(["ep-000"], reason="activation_decay") == 1`. Premise: `_archive_rows(root)` holds `ep-000`, `_raw` shows `ep-000` is not live, and its FTS count is 0. Inject a leftover row `("ep-000", "alpha archived leftover text")`. Snapshot `_archive_rows`. The call returns 1, the `ep-000` FTS count is 0, `_archive_rows` equals the snapshot, and the `ep-001` FTS count is 1. |
| T15 | `test_keyword_recall_for_live_episodes_is_unchanged` (golden) | Rig `"delete"`, store `_episode(0..5)`. Three queries, for example `"coolant reading alpha"`, `"bravo section coolant"` and `"loop reading charlie"`, with `k=3`. Record `R0 = [await em.keyword_search(q, k=3) for q in queries]`. Inject 4 stale rows whose content repeats the query words, for example `"coolant reading loop section alpha bravo charlie " * 2`. Record `R1`. Premise: for at least one query, `R1` contains a `gone-` id and lacks an id that is in `R0` (a live hit was displaced). Exit, then re-enter on the same root and record `R2`. For each query, `[e for e, _ in R2] == [e for e, _ in R0]`, and each rank equals R0's within `pytest.approx(rel=1e-9, abs=1e-12)`. If the ids match but a rank differs, that is a hard stop for Architect triage. Do not loosen the comparison. |

## Focused test commands

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf902_fts_reconciliation.py tests/test_ad1340_s1_restore_reset.py tests/test_ad1340_s1_erasure.py tests/test_ad1340_s1_eviction.py tests/test_ad541b_reconsolidation.py tests/test_reset_integration.py -n 0 -q
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_distribution.py tests/test_identity_deterministic.py tests/test_proactive.py tests/test_quality_hardening.py -k "reset or Reset" -n 0 -q
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad567b_anchor_recall.py tests/test_bf630_keyword_search_nl.py tests/test_ad979c_hybrid_retrieval.py tests/test_ad981c_sovereign_hybrid.py tests/test_ad590_composite_score_floor.py tests/test_ad591_quality_aware_budget.py tests/test_ad1293_turn_record_reaches_episode.py tests/test_ad1037_affect_capture.py tests/test_ad584c_scoring_rebalance.py tests/test_ad579b_temporal_validity.py tests/test_ad598_importance_scoring.py tests/test_ad603_anchor_recall_composite_scoring.py tests/test_ad605_enhanced_embedding.py tests/test_ad610_storage_gating.py tests/test_bf155_temporal_merge.py tests/test_ad1265_backup_coverage.py -q
```
The first command covers the changed slice: S1's three files (`_delete_fts_rows`, the lock, the T5 pin), the BF-669 lock tests in `test_ad541b_reconsolidation.py`, and the `RESET_TIERS` consumers. The second runs the `_cmd_reset` consumers (Grep `_cmd_reset` in `tests/`). The third runs every test file that touches `_fts_db`, `keyword_search` or `episode_fts` (Grep count across `tests/`, 2026-10-17), because each one may run `start()`, which now reconciles. The broad gate runs once, from the main session, per `.github/agents/orchestrator.agent.md`. The Builder does not run it.

**Milestone.** One milestone (Sections 1-5 plus the test file). If the Builder approaches about 150 tool calls, cut after Section 2 plus T1 to T3 (reset only, committed and green on the first two commands), and finish Sections 3-5 plus T4 to T15 as the second half.

## Diff Reviewer brief: properties to verify

The Diff Reviewer is the GPT-6.1 Sol reviewer. This is a data-integrity change: it deletes rows from a store at start on the vessel's live data.

1. A row whose id is live is never deleted, including when an episode is stored or restored while the reconciliation runs. The check and the delete of each page happen inside `_get_store_write_lock()`, and the delete matches `(rowid, episode_id)`.
2. Nothing is deleted when the collection is `None`, when `get` raises, or when its answer lacks a `list` of ids. Pages committed earlier stay committed. There is no `rollback()` on the shared FTS connection.
3. It is idempotent: a second run deletes nothing and leaves every row as it was.
4. It is bounded: each page reads at most `_FTS_RECONCILE_PAGE` rows, sends at most that many ids per collection `get`, and commits once. The collection is never read whole.
5. The archive is never read, and `restore_from_archive`, `_erase_ids` and `_remove_from_live` are unchanged.
6. `start()` cannot raise from the reconciliation, except on cancellation. It runs before `start()` returns, so before warm-boot `seed()` and the AD-584 migration (`cognitive_services.py:292` versus `:478` and `:569`).
7. Lock order and re-entry: the reconciliation takes only the store write lock, never the archive lock, and nothing under it calls `store`, `restore_from_archive` or `_erase_ids`. `store()`'s BF-669 lock window is untouched.
8. `_delete_fts_rows` keeps its return contract (True if and only if every delete and the commit succeeded) for both callers (`:2571`, `:2596`), and adds exactly one WARNING with the uncleaned count.
9. Keyword recall for live episodes is unchanged (T15). Tier 2 lists the three files, Tier 1 lists none of them, and `_cmd_reset` is unedited.

Consumer that must accept it: `init_cognitive_services()` booting a real data directory whose FTS index is 88% stale. On a copy of the live data (never the live directory), the expected first-start result is `removed 4167 of 4725` and the 547 live ids kept. The orchestrator may take that figure from a copy as post-build evidence. The Builder must not.

## Mutation table (campaign of record: none yet; the Builder or Reviewer that runs it records the base tree and the sha256 of each pinned file)

Every SEARCH is the stripped post-build line, with exactly one match in the named file.

| ID | File | SEARCH | REPLACE | Killed by |
|---|---|---|---|---|
| M1 | `src/probos/cognitive/episodic.py` | `async with lock:  # BF-902: no store() or restore add lands between the live check and the delete` | `if True:  # BF-902 mutant M1` | T10 |
| M2 | `src/probos/cognitive/episodic.py` | `await db.executemany("DELETE FROM episode_fts WHERE rowid = ? AND episode_id = ?", stale)` | `await db.executemany("DELETE FROM episode_fts WHERE rowid = ?", [(rowid,) for rowid, _eid in stale])` | T11 |
| M3 | `src/probos/cognitive/episodic.py` | `found = result.get("ids") if isinstance(result, Mapping) else None` | `found = (result.get("ids") if isinstance(result, Mapping) else None) or []` | T8 |
| M4 | `src/probos/cognitive/episodic.py` | `stale = [(rowid, eid) for rowid, eid in rows if eid in candidates and eid not in live]` | `stale = [(rowid, eid) for rowid, eid in rows if eid in candidates]` | T4, T15 |
| M5 | `src/probos/cognitive/episodic.py` | `if len(rows) < _FTS_RECONCILE_PAGE:` | `if True:` | T9 |
| M6 | `src/probos/cognitive/episodic.py` | `await db.commit()  # BF-902: one commit per page` | `pass  # BF-902 mutant M6` | T4 |
| M7 | `src/probos/cognitive/episodic.py` | `uncleaned += 1  # keep sweeping the remaining ids` | `pass  # BF-902 mutant M7` | T12 |
| M8 | `src/probos/cognitive/episodic.py` | `uncleaned = len(ids)  # nothing this sweep deleted is durable` | `pass  # BF-902 mutant M8` | T13 |
| M9 | `src/probos/cognitive/episodic.py` | `if uncleaned:` | `if False:` | T12, T13 |
| M10 | `src/probos/cognitive/episodic.py` | `await self._reconcile_fts_index()  # BF-902: before any seed or store(); warm boot seeds after start returns` | `pass  # BF-902 mutant M10` | T4, T12 |
| M11 | `src/probos/cognitive/episodic.py` | `if collection is None:` | `if False:` | T7 |
| M12 | `src/probos/__main__.py` | `"episode_fts.db", "participant_index.db", "activation_tracker.db",` | `# BF-902 mutant M12` | T1, T3 |

Considered and left out as equivalent: `last_rowid = rows[0][0]` (slower, same result) and removing `isinstance(found, list)` (`set(None)` raises into the same WARNING).

## What this does not change

- Recall scoring, the FTS tokenizer, `fts_or_query`, `keyword_search` and the hybrid fuser.
- The eviction audit (`eviction_audit.db` stays the record), S1's archive, `restore_from_archive`, `_erase_ids`, and the strict ERASE semantics.
- Retention and pruning thresholds (the 180-day activation log, `max_prune_fraction`), and `config/system.yaml`.
- `store()` and its BF-669 lock window (the four BF-669 lock tests in `test_ad541b_reconsolidation.py` are not edited).
- FTS5's own `secure-delete` option. S1 deferred it to S2 (`DECISIONS.md:67`, item 3). Rows deleted by the reconciliation are gone from the table, but their bytes may remain in free pages until reuse. The reset path deletes the whole file.
- Reconciliation of `participant_index.db` and `activation_tracker.db` (D4, follow-up), and that store's missing `StoreDeclaration`.
- `storage_declarations.py` and `backup_inventory.py` (their notes stay accurate).
- No live data directory is opened, reset or written.

## Tracking

- `PROGRESS.md`: add the CLOSED line `BF-902 (#1579): the FTS keyword index is cleared at Tier 2 with the episodes it indexes, and reconciled against the live collection at every start; eviction reports uncleaned FTS ids at WARNING.`
- `docs/development/roadmap.md` Bug Tracker: add the BF-902 row (Medium, data integrity and privacy, #1579).
- `DECISIONS.md`: add `### BF-902 -- The FTS keyword index goes with the episodes it indexes (2026-10-17, #1579)` with D1 to D5 condensed, plus: "The store write lock gains a fourth holder (`_reconcile_fts_index`, per page; it takes no other lock); this amends AD-1340 S1 R2's list of holders."
- The follow-up from D4 is recorded on #1579 by the orchestrator under the filing policy.

## Acceptance criteria

- [ ] After a Tier 2 reset of a data directory holding real episodes (temporary data directory and temporary knowledge path), `episode_fts.db`, `participant_index.db` and `activation_tracker.db` are gone, and so is `chroma.sqlite3`. A Tier 1 reset keeps all four (T1, T2, T3).
- [ ] Start-up deletes exactly the FTS rows whose id is not live, with one INFO line carrying the count. It is idempotent and bounded, deletes nothing when the collection cannot be read, never deletes a live row (T4 to T11), and never consults the archive (T14).
- [ ] A failed FTS delete during eviction writes one WARNING with the uncleaned count, spares no other id, and is repaired by the next start (T12, T13).
- [ ] Keyword recall for live episodes is unchanged (T15).
- [ ] S1's T5 pin is inverted with its reason inline, not deleted.
- [ ] Every row of the mutation table is killed by its named test.
- [ ] The sibling sidecars' two questions are answered in the PR body from D4.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Anchors moved since the issue (`f89d72a9` to `c1353655`)

| Issue anchor | Now |
|---|---|
| `__main__.py:2601-2634` `RESET_TIERS` | `:2603-2637` (S1 added `episode_archive.db` at `:2620`) |
| `__main__.py:2959-2993` deletion loop | `:2959-2994` |
| `__main__.py:616` `fts_keyword_floor` | `:616` (unchanged) |
| `episodic.py:1498` `db_dir / "episode_fts.db"` | `:1629` via `_FTS_FILENAME` (`:65`) |
| `episodic.py:1588` seed writer | `:1729-1732` |
| `episodic.py:1896` store writer | `:2061-2064` (plus S1's restore writer, `:2842-2845`) |
| `episodic.py:2362` / `:2434` per-id deleters | one helper, `_delete_fts_rows` `:1211-1225`, called from `_cleanup_sidecars` `:2596` and `_erase_fts_file` `:2571`. It no longer stops at the first failure (S1 R1). |
| `episodic.py:3794-3822` `keyword_search` | `:4270-4301` |
| callers `:2795`, `:3007`, `:3270`, `:4066` | `:3271`, `:3483`, `:3746`, `:4542` |
| hybrid fuser `:2795-2820` | `:3267-3286` (cut `:3279`, drop `:3286`) |
| `storage_declarations.py:97` | `:97` (unchanged) |
| `backup_inventory.py:136` | `:136` (unchanged) |

## Verified Against Codebase (2026-10-17, tree `c1353655`)

```
Grep "episode_fts|_FTS_FILENAME|_erase_fts_file|_cleanup_sidecars|def keyword_search|def start\(|..." src/probos/cognitive/episodic.py
  65: _FTS_FILENAME = "episode_fts.db"
  1211: async def _delete_fts_rows(db: Any, ids: list[str]) -> bool:
  1216: await db.execute("DELETE FROM episode_fts WHERE episode_id = ?", (eid,))
  1228: async def _store_tails_finished(events: list[asyncio.Event]) -> bool:
  1564: async def start(self) -> None:
  1629: fts_path = str(db_dir / _FTS_FILENAME)
  1641: await self._start_episode_archive(db_dir)
  1677: async def seed(self, episodes: list[Episode]) -> int:
  1730: "INSERT OR IGNORE INTO episode_fts(episode_id, content) VALUES (?, ?)",
  1821: def _get_store_tails(self) -> dict[str, list[asyncio.Event]]:
  1840: async def store(
  2052: self._get_store_tails().setdefault(episode.id, []).append(tail_done)
  2062: "INSERT INTO episode_fts(episode_id, content) VALUES (?, ?)",
  2554: async def _erase_fts_file(self, ids: list[str]) -> bool:
  2585: async def _cleanup_sidecars(self, ids: list[str], *, strict: bool = False) -> None:
  2596: if not await _delete_fts_rows(self._fts_db, ids):
  2624: async def _remove_from_live(
  2672: await self._cleanup_sidecars(ids)
  2752: await self._cleanup_sidecars(requested, strict=True)
  2808: async def restore_from_archive(self, episode_id: str) -> Episode:
  2843: "INSERT INTO episode_fts(episode_id, content) VALUES (?, ?)",
  2862: async def _evict(self) -> None:
  2888: async def evict_by_ids(
  4270: async def keyword_search(self, query: str, k: int = 10) -> list[tuple[str, float]]:
  4294: "SELECT episode_id, rank FROM episode_fts WHERE episode_fts MATCH ? ORDER BY rank LIMIT ?",
Grep "def _get_store_write_lock|_store_write_lock|async def get_by_ids" episodic.py
  1811: def _get_store_write_lock(self) -> asyncio.Lock:
  1856: write_lock = self._get_store_write_lock()
  2698: async with self._get_store_write_lock():  # AD-1340 R2: ...
  2827: async with self._get_store_write_lock():  # AD-1340 R2: ...
Read episodic.py:2833  live = self._collection.get(ids=[record.episode_id], include=[])  (include=[] + .get("ids") in use)
Read episodic.py:2044-2079  collection.add inside the lock; FTS insert after release; _finish_store_tail in finally
Read episodic.py:736  episodic_memory._client.delete_collection("episodes")   (AD-584 migration)
Read episodic.py:19   from collections.abc import AsyncIterator
Read episodic.py:56   logger = logging.getLogger(__name__)
Grep "keyword_search\(|fused_ids if eid in have" episodic.py
  3271, 3279 (cut), 3286 (drop), 3483, 3746, 4542
Read episodic.py:4786-4792  participant index pre-filter feeds a ChromaDB where filter
Grep "RESET_TIERS|episode_archive\.db|..." src/probos/__main__.py
  2598: _RESET_SUBDIRS = (...)   2603: RESET_TIERS = {   2620: "episode_archive.db",
  2719: "episode_archive.db": "Episode archive",   2861: def _cmd_reset(   2871: repo_path = ...
  2920: for t in range(1, tier + 1):   2960: for fname in tier_def.get("files", []):   2985: elif special == "knowledge_subdirs":
Grep "await episodic_memory.start|migrate_embedding_model\(|warm_boot" src/probos/startup/cognitive_services.py
  38: ACTIVATION_TRACKER_DB = "activation_tracker.db"   39: PARTICIPANT_INDEX_DB = "participant_index.db"
  149: lambda: migrate_embedding_model(   292: await episodic_memory.start()   306: await activation_tracker.start()
  456: await participant_index.start()   478: await _run_embedding_migration(   569: await warm_boot_service.restore()
Read src/probos/warm_boot.py:217-225  seeded = await self._episodic_memory.seed(episodes)
Grep "CREATE TABLE IF NOT EXISTS|DELETE FROM" activation_tracker.py / participant_index.py
  activation_tracker.py:45, 297 (age prune), 309 (per-id)   participant_index.py:34, 202 (per-id)
Read storage_declarations.py:92-116  cognitive.episode-fts, backup="included", restore="unknown"
Read d:/ProbOS/.venv/Lib/site-packages/aiosqlite/core.py:245  async def executemany(   (chromadb 1.5.8: api/client.py:590 def close releases the system)
Grep tests: test_ad1340_s1_restore_reset.py:264-267 (docstring), :294 (pin == []), :545 (_FtsTailProxy)
            test_ad1340_s1_eviction.py:87 (_memory), :121 (_raw), :126 (_query), :132 (_archive_rows), :166 (_warnings)
            test_reset_integration.py:44 (_run_reset; temp knowledge dir via mocked config)
DECISIONS.md:61 (S1 D7, nature/culture/nurture, 2026-10-16), :62 (D8), :65 (R2 lock holders), :66 (R3 tails), :67 (F-133, FTS5 secure-delete deferred)
```

## Absence Verified (2026-10-17)

```
1. CLAIM: no reset tier lists episode_fts.db, participant_index.db or activation_tracker.db
   RUN:   Grep -i "fts|participant_index|activation_tracker" src/probos/__main__.py
   FOUND: 616 (fts_keyword_floor) only
   HOLDS: yes
2. CLAIM: nothing reconciles the FTS index, the participant index or the activation log against the collection
   RUN:   Grep -i "reconcil" src/probos/cognitive
   FOUND: hits only in unrelated modules (crew_*, turn_promotion, work_reconciler, procedure_*, ...); none in
          episodic.py, participant_index.py or activation_tracker.py
   HOLDS: yes
3. CLAIM: the store write lock is held only by store, _erase_ids and restore_from_archive today
   RUN:   Grep "_get_store_write_lock|_store_write_lock" src/probos/cognitive/episodic.py
   FOUND: 1386 (init), 1811-1818 (def), 1856 (store), 2698 (_erase_ids), 2827 (restore_from_archive)
   HOLDS: yes
4. CLAIM: _delete_fts_rows has exactly two callers and no direct test
   RUN:   Grep "_delete_fts_rows|_cleanup_sidecars|_erase_fts_file" src/ tests/
   FOUND: episodic.py:1211 (def), 2571, 2596; no test hit
   HOLDS: yes
5. CLAIM: the siblings' only deletes are per-id eviction cleanup and the activation age prune
   RUN:   Grep "DELETE FROM|async def (delete|prune|cleanup|start)" activation_tracker.py, participant_index.py
   FOUND: activation_tracker.py:297 (access_time <), :309 (episode_id IN); participant_index.py:202 (episode_id IN)
   HOLDS: yes
6. CLAIM: participant_index.db has no StoreDeclaration
   RUN:   Grep "participant_index|PARTICIPANT_INDEX_DB" src/probos (files); Grep "canonical_path=" storage_declarations.py
   FOUND: cognitive_services.py, perception/backfill.py, episodic_mock.py, episodic.py; canonical paths list it nowhere
   HOLDS: yes
7. CLAIM: no test enumerates a tier's files exhaustively or counts dry-run rows
   RUN:   Grep "_collect_tier_targets|_show_dry_run|_show_confirmation_prompt|item\(s\) cleared|len\(RESET_TIERS" tests/
          Grep '\["files"\]|get\("files"' tests/
   FOUND: none; and only membership asserts (test_reset_integration.py:226, S1 T5 :291-294)
   HOLDS: yes
8. CLAIM: no BF-902 test or prompt exists yet
   RUN:   Glob {tests/test_bf902*,prompts/bf-902*}
   FOUND: none
   HOLDS: yes
```

**Not confirmed (pinned by tests instead):**
- (a) That FTS5 bm25 inputs (row count, average length, per-term document count) reflect deletes exactly, so ranks are equal. The SQLite FTS5 page defines N and avgdl over the current table but does not say how deletes are accounted. T15 pins the result empirically.
- (b) That Chroma's `get` returns a `Mapping` at runtime. The existing caller at `:2833` uses `.get("ids")`, and T4 fails loudly if it does not.

## Prior Art and Blind Spots

This is a bug fix, so the full prior-art review does not apply. A bounded check was still done because the reconciliation is a design choice.
- **Internal.** AD-567b (the sidecar), AD-1265 and `storage_declarations.py:108-114` (no rebuild entry point, so D2(d) is rejected), S1's D8, R1, R2, R3 and F-133 (`DECISIONS.md:62-67`). Absorbed: the lock, the tail ordering and the no-rollback rule.
- **External.** SQLite FTS5 documentation (https://www.sqlite.org/fts5.html): ordinary FTS5 tables accept `DELETE` like any table, and `'rebuild'` and `'integrity-check'` exist. `integrity-check` checks the index against the table's own content, not against another store, so it does not cover this case. Rejected for this fix. `secure-delete` is considered and deferred (S1 already deferred it to S2). No `docs/research/reference-projects.md` row is relevant: the problem is ProbOS-specific index hygiene, so no overdue project review was spent. Date used: 2026-10-17.
- **Blind spots named:**
  1. An AD-584 migration that crashed mid-way leaves fewer live ids. The reconciliation then removes their rows, and warm boot's `seed()` re-creates rows for any episode it restores.
  2. Text bytes of deleted rows can remain in SQLite free pages (secure-delete, deferred).
  3. A degraded collection answer must never read as "no live ids" (M3 and T8).
  4. A freed rowid can be reused (T11).
  5. Rows with a NULL or empty id are left alone.
  6. Every start writes one INFO line, the evidence that the reconciliation ran.
