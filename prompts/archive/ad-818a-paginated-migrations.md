# AD-818a — Paginated, cancellable episodic migrations

**Status:** Ready — Architect-reviewed (R1–R3 + Rec1–3 applied)
**Kind:** bf (per-migration surgery)
**Issue:** #751 (problems #2 and #3)
**Current highest shipped:** AD-839 (Wave 202). AD-818a is the pre-reserved sub-letter declared deferred in
the [AD-818 v1 prompt §5](./ad-818-schema-version-table.md). This prompt consumes it. Sub-letters AD-818b
(`probos migrate apply` CLI) and AD-818c (refuse-to-start gate) stay deferred. A second follow-on
**AD-818a-2** is reserved here for the three migrations this prompt deliberately does NOT convert (§5).

---

## 1. Problem

[Issue #751](../) names four structural problems with boot-time episodic migrations. v1 (AD-818, commit
`dcba2d48`) fixed problem #1 (the per-boot scan). This prompt fixes **problems #2 and #3** for the three
migrations where the fix is a clean, mechanical pagination:

> **Problem #2 — load-everything.** Each migration calls
> [`episodic_memory._collection.get(include=[...])`](../src/probos/cognitive/episodic.py#L113) with **no
> `limit`/`offset`** — loading the *entire* ChromaDB collection into Python memory in one call. On a large
> store the first run (the one that actually does work — v1's short-circuit cannot help the run that
> migrates) OOMs and bricks startup.
>
> **Problem #3 — async def with zero `await`.** These coroutines call only synchronous ChromaDB methods,
> so they never yield. [`asyncio.wait_for(coro_factory(), timeout_s)`](../src/probos/startup/cognitive_services.py#L79)
> can only cancel at an `await` boundary — so the BF-295 timeout is **non-functional**: a runaway migration
> runs to completion regardless of the timeout.

Both are fixed by the same change: read the collection **one bounded page at a time** through
`asyncio.to_thread`, processing and writing each page before fetching the next. `to_thread` (a) caps
resident memory at one page and (b) yields the event loop between pages so `wait_for` can actually cancel.

---

## 2. Design

### 2.1 New shared helper (one place — DRY)

Add to `src/probos/cognitive/episodic.py`, near `_MIGRATION_BATCH_SIZE`
([episodic.py:62](../src/probos/cognitive/episodic.py#L62)):

```python
async def _iter_collection_pages(
    collection: Any,  # ChromaDB Collection
    *,
    include: list[str],
    page_size: int | None = None,
) -> "AsyncIterator[dict[str, Any]]":
    """AD-818a: stream a ChromaDB collection one bounded page at a time.

    Each page is fetched via ``asyncio.to_thread`` so (1) only one page is
    resident in memory at a time (problem #2) and (2) the event loop yields
    between pages, letting ``asyncio.wait_for`` cancel a long migration at a
    page boundary (problem #3).

    Yields the raw ChromaDB ``get`` result dict for each non-empty page
    (keys: ``ids`` plus whatever was requested in ``include``). Stops when a
    page returns fewer than the effective page size ids (the last page) or
    zero ids.

    R1: ``page_size`` defaults to ``None`` and the module global
    ``_MIGRATION_BATCH_SIZE`` is read INSIDE the body (call time), NOT bound as
    a default-argument value (def time). This is what lets tests monkeypatch
    ``episodic._MIGRATION_BATCH_SIZE`` to a small value and actually force
    multi-page behavior. Do NOT write ``page_size: int = _MIGRATION_BATCH_SIZE``.

    Rec2 — OFFSET-STABILITY PRECONDITION: this design writes page k before
    reading page k+1 (the old code read everything first). That is only safe
    because the three callers either ``upsert`` existing ids IN PLACE (no add,
    no delete, no reorder of the row set being paginated) or write to a
    separate sidecar. ChromaDB does not formally contract ``.get()`` ordering,
    so any future caller that ADDS or DELETES collection rows mid-iteration
    would make ``offset`` skip/double-read and must NOT use this helper.
    """
    effective = page_size if page_size is not None else _MIGRATION_BATCH_SIZE
    offset = 0
    while True:
        page = await asyncio.to_thread(
            collection.get, include=include, limit=effective, offset=offset
        )
        ids = (page or {}).get("ids") or []
        if not ids:
            return
        yield page
        # Rec3: at an exact multiple (e.g. 2N rows, page_size N) this does one
        # final get(offset=2N) returning zero ids before the `if not ids`
        # return above — correct (no dup, no infinite loop). Do NOT "optimize"
        # this `len(ids) < effective` early-return away.
        if len(ids) < effective:
            return
        offset += effective
```

- **Imports (VERIFIED ABSENT — both must be added):** `episodic.py` currently imports only
  `dataclasses, hashlib, json, logging, math, time`, `from pathlib import Path`, `from typing import Any`.
  It does **not** import `asyncio` (the existing `async def` migrations' only `await` is on
  `record_episode_batch`, no `asyncio.` call). Add `import asyncio` to the stdlib import block and
  `from collections.abc import AsyncIterator` (module top). Do not assume either already exists.

### 2.2 Convert the three scan-and-rewrite migrations to per-page streaming

For each migration below: replace the single full `_collection.get(...)` + in-memory accumulation with an
`async for page in _iter_collection_pages(...)` loop. Process each page exactly as today, then **write that
page's batch before the next page** — wrapping the synchronous write in `await asyncio.to_thread(...)`.
Because `page_size == _MIGRATION_BATCH_SIZE` (2000) is already ≤ the BF-289 per-call cap, each page's write
is a single `upsert`/`record` call — the existing inner `for start in range(0, ..., _MIGRATION_BATCH_SIZE)`
chunk loop is removed (it is now redundant — one page = one chunk).

**(a) `migrate_episode_agent_ids` (BF-103)** —
[episodic.py:92](../src/probos/cognitive/episodic.py#L92), read @
[L113](../src/probos/cognitive/episodic.py#L113). Per page: build `batch_ids/batch_metas/batch_docs` from
the changed episodes (same resolve-sovereign-id logic), then if non-empty
`await asyncio.to_thread(episodic_memory._collection.upsert, ids=..., metadatas=..., documents=...)` and add
to the running `migrated` count. Per-page upsert failure is logged and the loop continues (preserve today's
per-chunk-failure-is-non-fatal behavior).

**(b) `migrate_anchor_metadata` (AD-570)** —
[episodic.py:187](../src/probos/cognitive/episodic.py#L187), read @
[L203](../src/probos/cognitive/episodic.py#L203). Same shape as (a): per page, build the promoted-anchor
batch (same `anchor_watch_section` skip + field-extraction logic), `to_thread`-upsert, accumulate count,
per-page failure non-fatal.

**(c) `migrate_participant_index` (AD-570b)** —
[episodic.py:371](../src/probos/cognitive/episodic.py#L371), read @
[L385](../src/probos/cognitive/episodic.py#L385). Per page (include `["metadatas"]`), build the
`(ep_id, agent_ids, participants)` batch, then
`await episodic_memory._participant_index.record_episode_batch(page_batch)` per page (already async — no
`to_thread`). **R3:** accumulate `len(page_batch)` summed across pages and return that total (the count of
participating episodes) — do **not** sum `record_episode_batch`'s return value (today this function returns
`len(batch)`; the gate test asserts `migrated == 2` at
[test_participant_index.py:404](../tests/test_participant_index.py#L404)).

### 2.3 Invariants to preserve (do NOT change)

- **Function signatures and return values are byte-identical.** Each still returns the total migrated count
  as an `int`. The existing test suites are the equivalence gate (§4).
- The top guards (`if not episodic_memory or not episodic_memory._collection: return 0`, BF-103's
  `if not identity_registry: return 0`) stay first.
- **Honest-degrade is PER-MIGRATION (R2 — do not apply one blanket rule):**
  - **BF-103 & AD-570** each keep their existing outer `try/except Exception: logger.warning(...,
    exc_info=True); return migrated` wrapper, **and** wrap each per-page `upsert` in its own
    `try/except Exception: logger.warning(...); continue` — equivalent to today's per-chunk
    failure-is-non-fatal handling.
  - **AD-570b** today has **no** `try/except` of its own — it relies entirely on the caller wrapper
    [`_run_one_migration`](../src/probos/startup/cognitive_services.py#L101) for honest-degrade. Do **NOT**
    add a swallow-and-continue `try/except` around its per-page `record_episode_batch`; let a failure
    propagate to `_run_one_migration` exactly as today. (Wrapping it would be a behavior change — hiding a
    failure that currently aborts the migration.)
- The elapsed-time `t0`/final summary log lines stay (info when `migrated > 0`, debug otherwise — keep each
  migration's existing message wording and id prefix).
- `_MIGRATION_BATCH_SIZE = 2000` is unchanged and is the effective page size (read at call time per R1).

---

## 3. Build scope (exact deliverables)

1. `episodic.py`: add `import asyncio` and `from collections.abc import AsyncIterator`; add the
   `_iter_collection_pages` async helper (§2.1) with call-time `page_size` resolution (R1).
2. `episodic.py`: convert `migrate_episode_agent_ids` to per-page streaming (§2.2a).
3. `episodic.py`: convert `migrate_anchor_metadata` to per-page streaming (§2.2b).
4. `episodic.py`: convert `migrate_participant_index` to per-page streaming (§2.2c).
5. `tests/test_ad818a_paginated_migrations.py` (new, §4).
6. No change to `cognitive_services.py`, `schema_versions.py`, config, runtime, or any other module.

---

## 4. Tests — `tests/test_ad818a_paginated_migrations.py` (~15)

Use **real in-memory ChromaDB** (mirror `test_participant_index.py` / `test_bf103_episode_id_mismatch.py`
fixtures — `EpisodicMemory` with a tmp client). **No MagicMock at the ChromaDB boundary.**

Helper `_iter_collection_pages`:
1. Empty collection → yields nothing (loop body never runs).
2. Single short page (fewer than `page_size`) → exactly one page, all ids present.
3. Exact multiple of `page_size` → stops correctly, no infinite loop, no duplicate/empty trailing page
   (boundary: seed `2*page_size` episodes with `page_size=N small`, assert every id seen exactly once).
4. Multiple pages with a partial last page → union of pages == full collection, no id seen twice.
5. Cancellability (Rec1 — make it DETERMINISTIC, not a timing race). Patch the per-page fetch so each page
   blocks measurably — e.g. monkeypatch `asyncio.to_thread` (or `collection.get`) to
   `await asyncio.sleep(d)` then return the real page. Seed `M` pages (small `page_size`) so `M*d > timeout`,
   wrap the migration in `asyncio.wait_for(..., timeout=t)` with `t < M*d`, and assert BOTH that
   `TimeoutError`/`CancelledError` is raised AND that a page-fetch counter shows it stopped EARLY (processed
   fewer than `M` pages). This proves problem #3 is fixed rather than relying on scheduler luck.

Per-migration equivalence (seed > 1 page using a small `page_size` where the migration accepts one, OR seed
enough episodes that `_MIGRATION_BATCH_SIZE` paginates — see note below):
6. `migrate_episode_agent_ids`: multi-page migration rewrites every slot id across the page boundary;
   result count == number actually changed; second run is idempotent (0).
7. `migrate_anchor_metadata`: multi-page backfill promotes anchors for every episode spanning ≥2 pages;
   re-run is a no-op.
8. `migrate_participant_index`: multi-page populates the sidecar for every participating episode spanning
   ≥2 pages; count == participating episodes.
9. Each migration with an empty collection → returns 0, no error.
10. Per-page write-failure is non-fatal for **BF-103 / AD-570** (R2): monkeypatch `_collection.upsert` to
    raise on one page, assert the migration logs a warning and still processes remaining pages (count
    reflects the surviving pages), and does not raise.
11. **AD-570b failure PROPAGATES** (R2): monkeypatch `_participant_index.record_episode_batch` to raise;
    assert `migrate_participant_index` raises (does NOT swallow) — proving no new try/except was added.

> **Page-size note for tests (R1 — this is why the helper resolves `page_size` at call time).** The three
> migrations call `_iter_collection_pages` with no `page_size`, so it reads the module global
> `_MIGRATION_BATCH_SIZE` (2000) **at call time**. To force multi-page behavior without seeding 2000+
> episodes, monkeypatch `probos.cognitive.episodic._MIGRATION_BATCH_SIZE` to a small value (e.g. 2) for the
> multi-page equivalence tests (#6–#8) and the cancellability test (#5). This works ONLY because of the R1
> call-time resolution — a `page_size=_MIGRATION_BATCH_SIZE` default argument would freeze 2000 at import
> and the monkeypatch would be silently ignored (false-green). Helper-direct tests (#1–#4) pass an explicit
> small `page_size` argument. State which approach each test uses.

**Regression gate (the real equivalence proof):** the existing suites must stay green unchanged —
`tests/test_bf103_episode_id_mismatch.py`, `tests/test_anchor_indexed_recall.py`,
`tests/test_participant_index.py`. Run these in the gate (§6).

---

## 5. NOT in scope (deferred — do NOT build)

These three migrations are deliberately **not** converted here because each needs a distinct strategy beyond
simple read pagination — reserve **AD-818a-2** for them:

- **`migrate_embedding_model` (AD-584)** — [episodic.py:285](../src/probos/cognitive/episodic.py#L285).
  Deletes and *recreates* the whole collection, so it needs a full snapshot before the delete. Paginating it
  requires staging to a temp store first — a separate design.
- **`migrate_enriched_embedding` (AD-605)** — [episodic.py:425](../src/probos/cognitive/episodic.py#L425).
  A **sync `def`** doing per-episode `collection.update()`; converting it needs an async conversion plus a
  re-embed redesign, not just pagination.
- **`sweep_hash_integrity` (BF-207)** — [episodic.py:518](../src/probos/cognitive/episodic.py#L518).
  Performs a **global timestamp sort to pick the most-recent `max_episodes` (200)**; ChromaDB `.get()` has
  no order-by, so it cannot be paginated without a different selection strategy.

Also out of scope: AD-818b (CLI), AD-818c (refuse-to-start), any `cognitive_services.py` change, any config
change, `_MIGRATION_BATCH_SIZE` value change, `ui/` changes.

---

## 6. Acceptance criteria

1. `_iter_collection_pages` exists, fully typed, uses `asyncio.to_thread`, resolves `page_size` at **call
   time** (R1 — `page_size: int | None = None`, read `_MIGRATION_BATCH_SIZE` in the body), and stops
   correctly on the short/empty last page (no infinite loop at exact-multiple boundaries).
2. `migrate_episode_agent_ids`, `migrate_anchor_metadata`, `migrate_participant_index` stream per page;
   their signatures and return semantics are **unchanged**; per-page write failures stay non-fatal; the
   honest-degrade outer wrapper and summary logs are preserved.
3. No memory growth proportional to collection size inside the three migrations — only one page is resident
   at a time (verifiable by the multi-page tests).
4. `tests/test_ad818a_paginated_migrations.py` passes (~14).
5. The existing equivalence suites pass unchanged: `test_bf103_episode_id_mismatch.py`,
   `test_anchor_indexed_recall.py`, `test_participant_index.py`.
6. Gate (`pytest tests/ -q -n 0`, or the AD-838 blast-radius subset — the new file + the three equivalence
   suites + `test_ad818_schema_versions.py` — if the full gate is impractically long) shows no regressions.
   Report which subset ran. Known pre-existing failures
   (`test_bf207_shutdown_episodic_integrity.py::test_dream_cycle_timeout_is_2s` /
   `::test_timeout_warning_says_2s`, stale AD-820 timeout assertions) are NOT caused by this work.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## 7. Verified against the live codebase (anchors — re-confirm before editing)

- ChromaDB **1.5.8** `Collection.get(self, ids, where, limit, offset, where_document, include)` — `limit`
  and `offset` confirmed present (`inspect.signature`).
- `episodic.py` imports (verified @L9-16): `dataclasses, hashlib, json, logging, math, time`, `Path`,
  `Any` only. **Neither `asyncio` nor `AsyncIterator` is imported** — both must be added by this build.
- `_MIGRATION_BATCH_SIZE = 2000` @[episodic.py:62](../src/probos/cognitive/episodic.py#L62) (BF-289 cap
  5461). It is the default `page_size`.
- Migrations + reads: BF-103 @[L92](../src/probos/cognitive/episodic.py#L92)/read
  [L113](../src/probos/cognitive/episodic.py#L113); AD-570 @[L187](../src/probos/cognitive/episodic.py#L187)/read
  [L203](../src/probos/cognitive/episodic.py#L203); AD-570b @[L371](../src/probos/cognitive/episodic.py#L371)/read
  [L385](../src/probos/cognitive/episodic.py#L385). All three are `async def`, return `int`, use the BF-289
  inner chunk loop (`for start in range(0, len(batch_ids), _MIGRATION_BATCH_SIZE)`) that this prompt removes.
- `_run_one_migration` wrapper (caller, unchanged here):
  [cognitive_services.py:37-103](../src/probos/startup/cognitive_services.py#L37), `wait_for` @
  [L79](../src/probos/startup/cognitive_services.py#L79).
- Existing equivalence tests: `test_bf103_episode_id_mismatch.py`,
  `test_anchor_indexed_recall.py` (migrate_anchor_metadata @L157+),
  `test_participant_index.py` (`TestMigrateParticipantIndex` @L372, real in-memory chroma fixtures).
