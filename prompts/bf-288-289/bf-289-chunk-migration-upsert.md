# BF-289 — Chunk BF-103 (and sibling) episode migrations under Chroma's max batch size

**Issue:** https://github.com/seangalliher/ProbOS/issues/762
**Status:** Ready to build
**Dependencies:** none
**Estimated tests:** +2 in `tests/test_bf103_episode_id_mismatch.py`
**Bundling:** Ships as its own commit. Pair commit is BF-288 (`prompts/bf-288-289/bf-288-reset-shutdown-marker.md`). Independent files, independent test files — two commits, clean bisect.

## Problem

After today's AD-819 rebuild restored 11,539 episodes, BF-103's `migrate_episode_agent_ids` collected a batch of 9,514 episodes that needed slot→sovereign ID conversion and called `_collection.upsert(ids=[9514 items], ...)`. ChromaDB 1.5.8 rejected it:

> `Batch size of 9514 is greater than max batch size of 5461`

The migration's `try/except Exception` logged WARNING and boot continued, but 9,514 episodes remain in the legacy slot-ID format. They'll never auto-heal on a future boot — the same batch will fail again.

Chroma's max batch limit is per-call. The fix is to chunk the upsert. The same shape exists in multiple migrations in `src/probos/cognitive/episodic.py`; we fix all the unsafe ones in one pass.

## Solution

Introduce a module-level constant `_MIGRATION_BATCH_SIZE = 2000` (safe margin below the 5461 limit) and split full-collection writes into chunked upserts/updates. Failure within one chunk is logged and the remaining chunks still proceed — partial migration beats no migration.

## Section 0: Audit of `_collection.{add,update,upsert,delete}` sites in `episodic.py`

Grep output:

```
147: episodic_memory._collection.upsert(   # BF-103 migrate_episode_agent_ids — UNSAFE
234: episodic_memory._collection.upsert(   # AD-570 migrate_anchor_metadata — UNSAFE
323: episodic_memory._collection.add(      # AD-584 migrate_embedding_model — ALREADY chunked (batch_size=100 at line 320)
546: episodic_memory._collection.update(   # BF-207 sweep_hash_integrity — bounded by max_episodes=200, SAFE
978: self._collection.add(                 # live-path add — single episode, SAFE
1218: self._collection.add(                # live-path add — single episode, SAFE
1381: self._collection.update(ids=[episode_id], ...)  # single, SAFE
1413: self._collection.update(ids=[episode_id], ...)  # single, SAFE
1441: self._collection.upsert(             # live-path upsert — single episode, SAFE
1488: self._collection.delete(ids=ids_to_delete)  # garbage collector — needs verification
1558: self._collection.delete(ids=valid_ids)      # live-path delete — needs verification
```

The AD-570b `migrate_participant_index` (around line 470) does NOT touch ChromaDB — it goes through `_participant_index.record_episode_batch`, so it's not in scope here.

The AD-605 `migrate_enriched_embedding` already iterates `batch_size = 100` (search around line 525) and calls `update` one row at a time inside the loop, so it's per-row, SAFE.

**In scope for chunking:** BF-103 (line 147), AD-570 (line 234).

**Out of scope (already safe):** AD-584 (already chunked), AD-605 (per-row), BF-207 (capped at 200), all live-path single-episode writes.

**Verify on the way through:** `_collection.delete` at lines 1488 and 1558. If `ids_to_delete` / `valid_ids` can exceed 5461 in any code path that triggers them, chunk them too. If they're naturally bounded (single-episode delete, fixed-size GC sweep, etc.), leave them and note why in a one-line comment.

## Section 1: Module-level constant + helper

### File: `src/probos/cognitive/episodic.py`

Add the constant near the top of the file, after the existing imports / `_AnchorQueryView` block (around line 60, just before the BF-103 comment block). One source of truth.

```
### SEARCH
# ---------------------------------------------------------------------------
# BF-103: Sovereign ID resolution helpers (DRY — one place for all callers)
# ---------------------------------------------------------------------------

def resolve_sovereign_id(agent: Any) -> str:
### REPLACE
# BF-289: ChromaDB 1.5.8 caps single-call batch size at 5461. All
# full-collection migration writes MUST chunk through this constant.
# 2000 keeps a generous safety margin and survives Chroma version
# bumps that might lower the cap further.
_MIGRATION_BATCH_SIZE = 2000


# ---------------------------------------------------------------------------
# BF-103: Sovereign ID resolution helpers (DRY — one place for all callers)
# ---------------------------------------------------------------------------

def resolve_sovereign_id(agent: Any) -> str:
### END REPLACE
```

## Section 2: Chunk BF-103's upsert at line 147

The block around line 147 is:

```python
        # Single batched upsert instead of N individual calls
        if batch_ids:
            episodic_memory._collection.upsert(
                ids=batch_ids,
                metadatas=batch_metas,
                documents=batch_docs,
            )
        migrated = len(batch_ids)
```

Replace with chunked writes. On per-chunk failure, log and continue (so a partial-success migration is preserved across boots — operator can re-run to mop up the rest).

```
### SEARCH
        # Single batched upsert instead of N individual calls
        if batch_ids:
            episodic_memory._collection.upsert(
                ids=batch_ids,
                metadatas=batch_metas,
                documents=batch_docs,
            )
        migrated = len(batch_ids)

        elapsed = time.time() - t0
        if migrated > 0:
            logger.info(
                "BF-103: Migrated %d episodes from slot IDs to sovereign IDs (%.1fs)",
                migrated, elapsed,
            )
        else:
            logger.debug("BF-103: No episodes needed migration (%.1fs)", elapsed)
    except Exception:
        logger.warning("BF-103: Episode ID migration failed", exc_info=True)

    return migrated
### REPLACE
        # BF-289: chunk under ChromaDB's per-call batch cap (5461 in
        # 1.5.8). Per-chunk failure is logged but does NOT abort the
        # migration — committed chunks persist so a re-run only needs
        # to redo the failed slice.
        for start in range(0, len(batch_ids), _MIGRATION_BATCH_SIZE):
            end = start + _MIGRATION_BATCH_SIZE
            try:
                episodic_memory._collection.upsert(
                    ids=batch_ids[start:end],
                    metadatas=batch_metas[start:end],
                    documents=batch_docs[start:end],
                )
                migrated += (end - start) if end <= len(batch_ids) else (len(batch_ids) - start)
            except Exception:
                logger.warning(
                    "BF-103: chunk %d..%d failed during sovereign-ID migration "
                    "(%d total candidates); continuing with remaining chunks",
                    start, min(end, len(batch_ids)), len(batch_ids),
                    exc_info=True,
                )

        elapsed = time.time() - t0
        if migrated > 0:
            logger.info(
                "BF-103: Migrated %d episodes from slot IDs to sovereign IDs (%.1fs)",
                migrated, elapsed,
            )
        else:
            logger.debug("BF-103: No episodes needed migration (%.1fs)", elapsed)
    except Exception:
        logger.warning("BF-103: Episode ID migration failed", exc_info=True)

    return migrated
### END REPLACE
```

Note: the existing `migrated = len(batch_ids)` is replaced by incrementing `migrated` per successful chunk so the returned count reflects what actually landed in ChromaDB, not what was planned. Initialize `migrated = 0` is already done at line 105 (`migrated = 0` near the top of the function body), so no separate init is needed.

## Section 3: Chunk AD-570's upsert at line 234

The block around line 234 (same shape as BF-103):

```python
        # Single batched upsert instead of N individual calls
        if batch_ids:
            episodic_memory._collection.upsert(
                ids=batch_ids,
                metadatas=batch_metas,
                documents=[d or "" for d in batch_docs],
            )
        migrated = len(batch_ids)
```

```
### SEARCH
        # Single batched upsert instead of N individual calls
        if batch_ids:
            episodic_memory._collection.upsert(
                ids=batch_ids,
                metadatas=batch_metas,
                documents=[d or "" for d in batch_docs],
            )
        migrated = len(batch_ids)

        elapsed = time.time() - t0
        if migrated > 0:
            logger.info(
                "AD-570: Promoted anchor metadata for %d episodes (%.1fs)",
                migrated, elapsed,
            )
        else:
            logger.debug("AD-570: No episodes needed anchor metadata migration (%.1fs)", elapsed)
    except Exception:
        logger.warning("AD-570: Anchor metadata migration failed", exc_info=True)

    return migrated
### REPLACE
        # BF-289: chunk under ChromaDB's per-call batch cap (5461 in
        # 1.5.8). Per-chunk failure is logged but does NOT abort.
        docs_clean = [d or "" for d in batch_docs]
        for start in range(0, len(batch_ids), _MIGRATION_BATCH_SIZE):
            end = start + _MIGRATION_BATCH_SIZE
            try:
                episodic_memory._collection.upsert(
                    ids=batch_ids[start:end],
                    metadatas=batch_metas[start:end],
                    documents=docs_clean[start:end],
                )
                migrated += (end - start) if end <= len(batch_ids) else (len(batch_ids) - start)
            except Exception:
                logger.warning(
                    "AD-570: chunk %d..%d failed during anchor metadata migration "
                    "(%d total candidates); continuing with remaining chunks",
                    start, min(end, len(batch_ids)), len(batch_ids),
                    exc_info=True,
                )

        elapsed = time.time() - t0
        if migrated > 0:
            logger.info(
                "AD-570: Promoted anchor metadata for %d episodes (%.1fs)",
                migrated, elapsed,
            )
        else:
            logger.debug("AD-570: No episodes needed anchor metadata migration (%.1fs)", elapsed)
    except Exception:
        logger.warning("AD-570: Anchor metadata migration failed", exc_info=True)

    return migrated
### END REPLACE
```

Same `migrated = 0` initialization already present near the top of `migrate_anchor_metadata` (around line 195 — verify before edit).

## Section 4: Tests

### File: `tests/test_bf103_episode_id_mismatch.py`

Append a new test class `TestMigrationChunking` (after the existing `TestMigration` class around line 200). Two tests:

1. **`test_migration_chunks_large_batches`** — synthesize a collection of 6000 episodes (just above the 5461 limit), all needing migration. Verify the migration completes (returned count == 6000), the upsert was called multiple times, and post-migration the count is preserved.
2. **`test_migration_continues_after_chunk_failure`** — same shape, but inject one failing chunk via a side-effect mock. Verify a WARNING is logged, the other chunks still persist, and the returned count reflects the successful chunks only.

```python
class TestMigrationChunking:
    """BF-289: BF-103 must chunk upserts under ChromaDB's max batch size."""

    @pytest.mark.asyncio
    async def test_migration_chunks_large_batches(self):
        """6000-episode migration must complete (chunked under 5461 cap)."""
        from unittest.mock import MagicMock
        from probos.cognitive.episodic import migrate_episode_agent_ids, _MIGRATION_BATCH_SIZE

        # Build a fake collection with 6000 episodes whose agent_ids are slot IDs.
        n = 6000
        ids = [f"ep-{i:05d}" for i in range(n)]
        metas = [
            {"agent_ids_json": '["slot-A"]', "timestamp": float(i)}
            for i in range(n)
        ]
        docs = [f"doc {i}" for i in range(n)]

        coll = MagicMock()
        coll.get.return_value = {"ids": ids, "metadatas": metas, "documents": docs}
        upsert_calls: list[int] = []

        def _record_upsert(*, ids, metadatas, documents):  # noqa: A002
            upsert_calls.append(len(ids))

        coll.upsert.side_effect = _record_upsert

        em = MagicMock()
        em._collection = coll

        registry = MagicMock()
        cert = MagicMock()
        cert.agent_uuid = "sovereign-A"
        registry.get_by_slot.return_value = cert

        migrated = await migrate_episode_agent_ids(em, registry)

        # All 6000 should land.
        assert migrated == n
        # Must have been split into at least ceil(6000/2000) = 3 chunks,
        # and every chunk must be ≤ _MIGRATION_BATCH_SIZE.
        assert len(upsert_calls) >= 3
        assert all(c <= _MIGRATION_BATCH_SIZE for c in upsert_calls)
        assert sum(upsert_calls) == n

    @pytest.mark.asyncio
    async def test_migration_continues_after_chunk_failure(self, caplog):
        """A failed chunk must not abort the migration; surviving chunks persist."""
        import logging
        from unittest.mock import MagicMock
        from probos.cognitive.episodic import migrate_episode_agent_ids, _MIGRATION_BATCH_SIZE

        n = _MIGRATION_BATCH_SIZE * 3  # exactly 3 chunks
        ids = [f"ep-{i:05d}" for i in range(n)]
        metas = [
            {"agent_ids_json": '["slot-A"]', "timestamp": float(i)}
            for i in range(n)
        ]
        docs = [f"doc {i}" for i in range(n)]

        coll = MagicMock()
        coll.get.return_value = {"ids": ids, "metadatas": metas, "documents": docs}

        call_count = {"n": 0}

        def _maybe_fail(*, ids, metadatas, documents):  # noqa: A002
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("simulated chroma blip on chunk 2")

        coll.upsert.side_effect = _maybe_fail

        em = MagicMock()
        em._collection = coll

        registry = MagicMock()
        cert = MagicMock()
        cert.agent_uuid = "sovereign-A"
        registry.get_by_slot.return_value = cert

        with caplog.at_level(logging.WARNING, logger="probos.cognitive.episodic"):
            migrated = await migrate_episode_agent_ids(em, registry)

        # Two of three chunks landed.
        assert migrated == _MIGRATION_BATCH_SIZE * 2
        # The failure was logged at WARNING.
        assert any("chunk" in rec.message.lower() and "failed" in rec.message.lower()
                   for rec in caplog.records)
```

Notes for the Builder:

- `migrate_episode_agent_ids` calls `EpisodicMemory._metadata_to_episode` + `compute_episode_hash`. With slot IDs in the JSON list, the resolver path will mark `changed=True` and populate `batch_ids`. Confirm at lines 117–146 of `episodic.py` that the code path doesn't depend on `em.start()` having been called; the function only reads `em._collection`. The `MagicMock()` for `em` plus a real-shaped `_collection.get` return value should be sufficient.
- If `_metadata_to_episode` / `compute_episode_hash` choke on the minimal metadata above, extend the test metadata with whatever fields they require. Read the error and add the minimum to make it pass — don't hide failures with broader try/except.
- `caplog.at_level` is the pytest builtin; no extra import needed beyond `logging`.

## What This Does NOT Change

- AD-570b `migrate_participant_index` (no ChromaDB write).
- AD-584 `migrate_embedding_model` (already chunked at 100 per add).
- AD-605 `migrate_enriched_embedding` (already per-row updates inside a batch loop).
- BF-207 `sweep_hash_integrity` (capped at `max_episodes=200`).
- Live-path single-episode `add` / `update` / `upsert` calls.
- `_collection.delete` call sites at lines 1488 and 1558 — verify in-passing during edit. If they're bounded, leave a one-line comment noting the bound. If unbounded, file a follow-up forward marker (e.g., add `# BF-289-followup: audit delete chunking` near the call) but do NOT chunk in this commit.

## Tracking

- `PROGRESS.md` — add BF-289 entry under the bug list.
- `docs/development/roadmap.md` Bug Tracker — add row.
- Do NOT touch `DECISIONS.md` (bugfix, not architectural decision).

## Acceptance Criteria

- `_MIGRATION_BATCH_SIZE = 2000` constant in `episodic.py`, used at every chunked migration site.
- BF-103 and AD-570 migration upserts chunk under the limit.
- Per-chunk failure logs a WARNING but does NOT abort the migration; committed chunks persist.
- Returned `migrated` count reflects successful chunks only.
- Both new tests pass: `D:\ProbOS\.venv\Scripts\pytest.exe -n 0 --timeout=60 tests/test_bf103_episode_id_mismatch.py`
- Then: `D:\ProbOS\.venv\Scripts\pytest.exe -q -n 4 --dist=loadfile` returns the same pre/post test count delta as the new tests (+2).
- Verify all changes comply with Engineering Principles in `.github/copilot-instructions.md`.

## Standing Constraint

- Do NOT touch the live runtime (PID at `C:\Users\seang\AppData\Local\ProbOS\data\probos.pid`).
- Do NOT touch anything under `C:\Users\seang\AppData\Local\ProbOS\`.

## Commit Message

```
BF-289: chunk episode-migration upserts under ChromaDB max batch size

ChromaDB 1.5.8 rejects single-call upserts above 5461 ids. After today's
AD-819 rebuild produced 11,539 episodes, BF-103's sovereign-ID migration
tried to upsert 9,514 at once and failed, leaving the episodes in legacy
format. Introduces _MIGRATION_BATCH_SIZE=2000 and chunks BF-103 and
AD-570 migration writes. Per-chunk failure is logged and skipped; the
migration completes what it can so a re-run only mops up the rest.

Closes #762
```

## Verified Against Codebase (2026-05-22)

```
grep -n "_collection\.\(upsert\|add\|update\|delete\)" src/probos/cognitive/episodic.py
  147: episodic_memory._collection.upsert(   # BF-103 — UNSAFE (target)
  234: episodic_memory._collection.upsert(   # AD-570 — UNSAFE (target)
  323: episodic_memory._collection.add(      # AD-584 — already chunked (batch_size=100 nearby)
  546: episodic_memory._collection.update(   # BF-207 — bounded max_episodes=200
  978: self._collection.add(                 # live single-episode
 1218: self._collection.add(                 # live single-episode
 1381: self._collection.update(ids=[episode_id], ...)  # single
 1413: self._collection.update(ids=[episode_id], ...)  # single
 1441: self._collection.upsert(              # live single-episode
 1488: self._collection.delete(...)          # verify bound
 1558: self._collection.delete(...)          # verify bound

grep -n "async def migrate_episode_agent_ids" src/probos/cognitive/episodic.py
  88: async def migrate_episode_agent_ids(

grep -n "async def migrate_anchor_metadata" src/probos/cognitive/episodic.py
  171: async def migrate_anchor_metadata(

ls tests/test_bf103_episode_id_mismatch.py
  exists; TestMigration class at line 200 — append new TestMigrationChunking after it
```
