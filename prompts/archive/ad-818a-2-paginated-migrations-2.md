# AD-818a-2 — Paginate the two read-streaming startup migrations (AD-605 + BF-207)

**Status:** Draft — pending Architect review
**Issue:** #751 (continuation; follows AD-818 schema table + AD-818a BF-103/AD-570/AD-570b pagination)
**Target repo:** OSS (`d:\ProbOS`)
**One commit** titled: `feat(episodic): AD-818a-2 paginate AD-605 + BF-207 migrations + cancellable to_thread (#751)`

---

## 1. Problem

Issue #751 problems #2 (full-collection `.get()` loads every episode into memory → OOM risk) and #3
(`async def` migrations with zero `await` cannot be cancelled by the boot `wait_for` timeout) were fixed
for BF-103/AD-570/AD-570b in **AD-818a** (commit `4cc722d1`) via the shared `_iter_collection_pages`
async helper. Three migrations were explicitly deferred. This wave fixes **two** of them:

- **AD-605 `migrate_enriched_embedding`** (`episodic.py` @487): a **synchronous** function that calls
  `collection.get(include=["documents","metadatas"])` to load **all** episodes, then re-embeds each
  in place via `collection.update`. Two defects: (a) loads everything into memory (#2); (b) it is run via
  `loop.run_in_executor(None, ...)` at the call site, so `asyncio.wait_for` cancellation never reaches the
  executor thread (#3 in a subtler form — the timeout fires but the thread keeps running).

- **BF-207 `sweep_hash_integrity`** (`episodic.py` @575): loads **all** episodes, globally sorts by
  timestamp descending, and heals the most-recent `max_episodes` (default 200). Defects: (a) loads
  everything to sort (#2); (b) at the call site it is `await`ed **directly with no `_run_one_migration`
  wrapper and no timeout** (`cognitive_services.py` @449) — the one migration with zero cancellation/timeout
  protection.

The third deferred migration — **AD-584 `migrate_embedding_model`** (delete + recreate collection) —
requires a distinct write-path rearchitecture (stream old → temp collection → rename) and is **out of
scope**; it is reserved as **AD-818a-3**.

---

## 2. Design

### 2.1 AD-605 — `migrate_enriched_embedding`: sync → async + paginated read

Convert the function from `def` to `async def` and stream the read through the existing
`_iter_collection_pages` helper. In-place `collection.update` does not add/delete rows, so `offset`
remains stable across pages (the same precondition AD-818a relies on; it is already documented in the
helper docstring).

- Keep the early guards: `if not episodic_memory or not episodic_memory._collection: return 0`, and the
  `enriched_embedding_version >= 1` short-circuit (read `collection.metadata` once, before the loop).
- Replace `existing = collection.get(...)` + the `for start in range(0, len(ids), batch_size)` loop with a
  **per-page batched** update (consistent with the AD-818a sibling, which does one write per page — do NOT
  do a separate `update` per episode, that forces N single-doc embedding passes and fights the
  `_migration_timeout_s` budget):
  ```python
  async for page in _iter_collection_pages(
      collection, include=["documents", "metadatas"]
  ):
      ids = page.get("ids") or []
      documents = page.get("documents") or []
      metadatas = page.get("metadatas") or []
      page_ids: list[str] = []
      page_docs: list[str] = []
      page_metas: list[dict] = []
      for i, ep_id in enumerate(ids):
          # ... existing per-episode reconstruct + _prepare_document logic ...
          page_ids.append(ep_id)
          page_docs.append(enriched_doc)
          page_metas.append(ep_meta)
      if page_ids:
          await asyncio.to_thread(
              collection.update,
              ids=page_ids,
              documents=page_docs,
              metadatas=page_metas,
          )
          migrated += len(page_ids)
  ```
  One `await asyncio.to_thread(...)` per page yields to the event loop at page granularity — matching
  AD-818a's cancellation model (page_size 2000 is well under the BF-289 5461 cap).
- The **empty-collection path** (no episodes at all) must still set the version marker. Because
  `_iter_collection_pages` yields nothing for an empty collection, detect emptiness by tracking whether any
  page was seen, OR simply set the version marker **unconditionally after the loop** (the marker write is
  idempotent and correct whether or not episodes were migrated). Preserve the existing `safe_meta` filter
  (`{k: v for k, v in meta.items() if not k.startswith("hnsw:")}`) to avoid the "Changing the distance
  function" `ValueError`.
- Keep the outer `try/except Exception: logger.warning("AD-605: ... (non-fatal)", exc_info=True)`.
- Return total `migrated`.

### 2.2 AD-605 call site (`cognitive_services.py` @435)

Change from the executor wrapper to a direct async call:
```python
lambda: migrate_enriched_embedding(episodic_memory),
```
Remove the now-unused `_loop = asyncio.get_running_loop()` line (@432) — it is used **only** for this
`run_in_executor` call in this block, confirmed by inspection. Leave the `_run_one_migration` wrapper,
templates, and schema-version args (`migration_id="AD-605"`, `MIGRATION_VERSIONS["AD-605"]`) unchanged.

### 2.3 BF-207 — `sweep_hash_integrity`: bounded top-K heap streaming

The sweep must heal the `max_episodes` **newest** episodes. ChromaDB `.get(limit=, offset=)` returns rows
in **insertion order, not timestamp order**, so we cannot simply take the first page — a bounded
**min-heap keyed by timestamp** is required to retain the newest K with O(K) memory.

- Stream pages via `_iter_collection_pages(collection, include=["metadatas", "documents"])`.
- Maintain `heap: list[tuple[float, int, str, dict, str]]` via `heapq`, where the tuple is
  `(timestamp, seq, ep_id, meta, doc)`. `seq` is a monotonically incrementing `int` tiebreaker so heap
  comparisons never reach the `dict` (dicts are unorderable). For each episode:
  ```python
  heapq.heappush(heap, (ts, seq, ep_id, meta, doc)); seq += 1
  if len(heap) > max_episodes:
      heapq.heappop(heap)   # evict the oldest (smallest timestamp)
  ```
- After streaming, the heap holds the ≤ `max_episodes` newest episodes. **Drain in descending
  `(timestamp, seq)` order** — this is REQUIRED, not cosmetic: `test_sweep_batches_multiple_mismatches`
  asserts `update(ids=["ep-c", "ep-b", "ep-a"])` i.e. timestamp-desc order (the current code achieves this
  via `paired.sort(..., reverse=True)`). A raw heap iteration / `heappop` drain yields ASCENDING order and
  breaks that test. Use:
  ```python
  for ts, seq, ep_id, meta, doc in sorted(heap, key=lambda t: (t[0], t[1]), reverse=True):
      # recompute hash exactly as today; on mismatch append to batch_ids / batch_metas
  ```
  Then issue a **single** `collection.update(ids=batch_ids, metadatas=batch_metas)` (preserve the
  single-batch behavior `test_sweep_batches_multiple_mismatches` asserts).
- Keep the early guards, the `content_hash`/legacy skips, `_HASH_VERSION` stamping, and the return of
  `healed`. **Drop** the function's internal `try/except Exception` and its internal heal/clean logging —
  the `_run_one_migration` wrapper (§2.4) now owns honest-degrade and logging; keeping an internal swallow
  would cause a real failure to return `healed=0` and be misreported by the wrapper as a clean "0
  mismatches" noop (this mirrors the AD-818a sibling, which dropped its internal try/except for the same
  reason).
- Reuse the helper's `to_thread` page reads for cancellability; no manual `to_thread` needed inside the
  hashing loop (pure CPU, bounded to ≤ 200 episodes).

### 2.4 BF-207 call site (`cognitive_services.py` @445–456) — add timeout protection

BF-207 currently has **no** timeout. Wrap it so the boot cannot hang. It is **not** a versioned migration
(it must run every boot), so do **not** pass `schema_store`/`migration_id`/`version_hash`. Use
`_run_one_migration` with the existing `_migration_timeout_s` budget:
```python
await _run_one_migration(
    "BF-207",
    lambda: sweep_hash_integrity(episodic_memory),
    _migration_timeout_s,
    "BF-207: Healed %d hash mismatches in startup sweep in %.1fs",
    "BF-207: hash integrity sweep completed in %.1fs (0 mismatches)",
)
```
Keep BF-207 as the **LAST** migration (the existing "new migrations go ABOVE this block" comment must
remain accurate — place nothing below it). Remove the old bespoke `try/except` + `if healed > 0` logging
block it replaces (the wrapper now owns logging).

---

## 3. Build scope

Touch only:
- `src/probos/cognitive/episodic.py` — convert AD-605 to async + paginated; rewrite BF-207 with heap stream.
  `import heapq` (add near the existing stdlib imports). `asyncio` is already imported (AD-818a).
- `src/probos/startup/cognitive_services.py` — AD-605 call site (direct await), BF-207 call site (wrap in
  `_run_one_migration`).
- `tests/test_ad818a2_paginated_migrations.py` — NEW (see §4).

Do **not** touch `_iter_collection_pages`, the AD-818a migrations, AD-584, schema_versions, or any other
module. Do not change `_prepare_document`, `compute_episode_hash`, or `_metadata_to_episode`.

---

## 4. Tests — `tests/test_ad818a2_paginated_migrations.py` (~12–15)

Use a **real in-memory ChromaDB** collection (mirror the AD-818a test fixtures). Monkeypatch
`episodic._MIGRATION_BATCH_SIZE` to a small value (e.g. 2 or 3) to force multi-page behavior.

**AD-605:**
1. Multi-page re-embed: seed N episodes (N > page_size) with `anchors_json`; run migration; assert every
   document is the enriched form (`_prepare_document` output) and `user_input` metadata is populated.
2. Version marker set: after a successful run, `collection.metadata["enriched_embedding_version"] == 1`.
3. Idempotent: a second run short-circuits (returns 0, no re-write) because version ≥ 1.
4. Empty collection: returns 0 and still sets the version marker.
5. Return count equals number of episodes migrated across pages.
6. Cancellability (deterministic): monkeypatch `asyncio.to_thread` to an `asyncio.sleep`-based stub that
   counts page reads; wrap the migration in `asyncio.wait_for(..., timeout=tiny)`; assert it raises
   `TimeoutError` and stopped before processing all pages.

**BF-207:**
7. Heap picks the K **newest**: seed > `max_episodes` episodes with known ascending timestamps, all with
   stale hashes; run `sweep_hash_integrity(em, max_episodes=K)`; assert exactly the K newest (highest
   timestamps) were healed and the older ones were not.
8. Heal across pages: with small page_size, mismatches spread over multiple pages are all detected (subject
   to the top-K bound).
9. Single batched update: multiple mismatches → `collection.update` called exactly once (real collection:
   assert healed count + post-state hashes match `compute_episode_hash`).
9a. **Descending order pin** (regression guard for the live mock suite): with a small `MagicMock`
    collection returning 3 stale episodes (ts 1000/1001/1002), assert the single `update` call receives
    `ids` in timestamp-**descending** order (newest first) — mirrors
    `test_sweep_batches_multiple_mismatches`. This pins the heap-drain order inside the new suite too, so a
    future refactor can't regress it silently.
10. Skips matching + legacy (no `content_hash`) episodes.
11. Empty / no-collection → 0.
12. Cancellability: same `to_thread` stub pattern; assert early stop under `wait_for`.

**Equivalence guard:** the existing `tests/test_bf207_shutdown_episodic_integrity.py` sweep tests use
`mock_collection.get.return_value` with 1–3 episodes (< page_size) — they terminate on page 0 and must stay
green unchanged. The shutdown-ordering and configurable-timeout tests (fixed in BF-597) are unaffected.

---

## 5. NOT in scope (defer)

- **AD-818a-3** — `migrate_embedding_model` (AD-584): stream old → temp collection → `delete_collection` →
  `collection.modify(name="episodes")` swap. Distinct write-path rearchitecture; separate wave.
- **AD-818b** (CLI), **AD-818c** (maintenance gate). Keep #751 **OPEN**.

---

## 6. Acceptance criteria

1. AD-605 is `async def`, streams via `_iter_collection_pages`, sets the version marker, and is cancellable
   (its call site is a direct `await`, no `run_in_executor`).
2. BF-207 uses a bounded ≤ `max_episodes` heap (O(K) memory), heals the K newest, issues a single batched
   `update`, and its call site is wrapped in `_run_one_migration` with a timeout; BF-207 remains the last
   migration.
3. New `tests/test_ad818a2_paginated_migrations.py` passes (real in-memory chroma, multi-page via
   monkeypatched `_MIGRATION_BATCH_SIZE`, deterministic cancellability).
4. Existing equivalence suites stay green unchanged:
   `tests/test_bf207_shutdown_episodic_integrity.py`, `tests/test_ad605_enhanced_embedding.py`,
   plus the AD-818a gate (`test_bf103_episode_id_mismatch.py`, `test_anchor_indexed_recall.py`,
   `test_participant_index.py`, `test_ad818_schema_versions.py`).
5. `episodic.py` passes `ast.parse`. Only the three listed files change.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## 7. Verified anchors (live codebase, June 2026)

- `_iter_collection_pages` (episodic.py @67): async, `page_size: int | None = None` reads
  `_MIGRATION_BATCH_SIZE` (=2000) in body; `collection.get(include=, limit=, offset=)` via
  `asyncio.to_thread`; terminates on empty page or `len(ids) < effective`.
- `migrate_enriched_embedding` @487 (SYNC), `sweep_hash_integrity` @575 (async) in episodic.py.
- Call sites: AD-605 `cognitive_services.py` @435 (`run_in_executor`, `_loop` @432 used only here);
  BF-207 @451 (direct await, no wrapper, gated by `config.memory.verify_content_hash`).
  `_run_one_migration` @37; `_migration_timeout_s` defined @315 (`config.memory.migration_timeout_s`).
- chromadb 1.5.8: `Collection.update` is in-place (no row add/delete → offset stable). `heapq` is stdlib.
- `migrate_enriched_embedding` has no existing migration-level test (only `_prepare_document` unit tests in
  `test_ad605_enhanced_embedding.py`) — new coverage is additive, breaks nothing.
