# AD-605: Enhanced Embedding — Content + Anchor Metadata Concatenation

## Issue

GitHub Issue #181. Roadmap entry in `docs/development/roadmap.md`.

## Problem

ProbOS stores episodes in ChromaDB with `documents=[episode.user_input]` — only the raw interaction text gets embedded. Anchor metadata (department, channel, watch_section, trigger_type) is stored in ChromaDB's `metadatas` dict but is **never part of the embedding vector**. This means:

1. An episode from Science department's first watch about pool thresholds has the **same embedding** as an identical episode from Engineering department's second watch.
2. Semantic retrieval cannot distinguish episodes by structural context — it relies entirely on post-retrieval metadata filtering (AD-570 anchor where-clauses) or post-retrieval composite scoring.
3. Query-time context (department, watch) has no effect on the embedding comparison, only on post-retrieval filters.

## Research

- **A-MEM** (Xu et al., NeurIPS 2025): Concatenates `content + context + keywords + tags` before embedding. Yields better semantic search than content-only embeddings.
- **Craik & Tulving (1975)**: Elaborative encoding — deeper processing at encoding time produces more retrievable traces.
- **ProbOS research**: `docs/research/memory-retrieval-research.md` Section 7.2-7.3 (elaborative encoding), Section 8.4 (enriched encoding proposal).
- **Gap analysis**: `docs/research/agent-memory-survey-absorption.md` Section 1.

## Fix — 4 Changes

### Change 1: `_prepare_document()` static method

**File:** `src/probos/cognitive/episodic.py`
**Location:** After `_episode_to_metadata()` (after line ~1370)

Add a new static method that builds the enriched document text:

```python
    @staticmethod
    def _prepare_document(episode: "Episode") -> str:
        """AD-605: Build enriched document text for ChromaDB embedding.

        Concatenates anchor metadata into the document text so the embedding
        captures structural context (department, channel, watch_section) in
        addition to raw content. Improves semantic separation between episodes
        from different contexts.
        """
        parts: list[str] = []
        if episode.anchors:
            if episode.anchors.department:
                parts.append(f"[{episode.anchors.department}]")
            if episode.anchors.channel:
                parts.append(f"[{episode.anchors.channel}]")
            if episode.anchors.watch_section:
                parts.append(f"[{episode.anchors.watch_section}]")
            if episode.anchors.trigger_type:
                parts.append(f"[{episode.anchors.trigger_type}]")
        parts.append(episode.user_input or "")
        return " ".join(parts)
```

**Logic:**
- Only non-empty anchor fields are prepended (no empty brackets).
- Bracket-wrapped format `[field]` creates distinct tokens the embedding model can learn from.
- Order: department → channel → watch_section → trigger_type → user_input.
- Episodes with `anchors=None` get just `user_input` (backward-compatible).
- Minimal token overhead (~4-8 tokens per episode).

### Change 2: Update all 3 ChromaDB write sites

**File:** `src/probos/cognitive/episodic.py`

**2a — `store()` method (line 736-740):**

Replace:
```python
        self._collection.add(
            ids=[episode.id],
            documents=[episode.user_input],
            metadatas=[metadata],
        )
```

With:
```python
        self._collection.add(
            ids=[episode.id],
            documents=[self._prepare_document(episode)],
            metadatas=[metadata],
        )
```

**2b — `seed()` method (line 606):**

Replace:
```python
            batch_docs.append(ep.user_input)
```

With:
```python
            batch_docs.append(self._prepare_document(ep))
```

**2c — `_force_update()` method (line 789-793):**

Replace:
```python
        self._collection.upsert(
            ids=[episode.id],
            documents=[episode.user_input],
            metadatas=[metadata],
        )
```

With:
```python
        self._collection.upsert(
            ids=[episode.id],
            documents=[self._prepare_document(episode)],
            metadatas=[metadata],
        )
```

### Change 3: Store original `user_input` in metadata and strip on recall

Since `_metadata_to_episode()` reconstructs episodes with `user_input=document` (line 1382), and the document text now includes anchor prefixes, we need to preserve the original `user_input` in metadata to avoid polluting the reconstructed Episode.

**3a — Add `user_input` to metadata in `_episode_to_metadata()` (line ~1342-1356):**

After the `"content_hash"` line (line 1354), add:
```python
            "user_input": episode.user_input or "",  # AD-605: preserve original for recall
```

Full line goes after:
```python
            "content_hash": compute_episode_hash(normalized),
```

And before:
```python
            "_hash_v": 2,
```

**3b — Update `_metadata_to_episode()` to use stored `user_input` (line 1382):**

Replace:
```python
            user_input=document,
```

With:
```python
            user_input=metadata.get("user_input", document),  # AD-605: prefer stored original
```

**Logic:**
- New episodes have `user_input` in metadata → use it (original, no anchor prefix).
- Old episodes (pre-migration) don't have `user_input` in metadata → fall back to `document` (backward-compatible).
- The `document` field in ChromaDB is now "embedding text" (enriched), not "user input" (raw). Clean separation.

### Change 4: Migration — re-embed existing episodes with enriched text

**File:** `src/probos/cognitive/episodic.py`
**Location:** After the existing `migrate_embedding_model()` function (after line ~300)

Add a new migration function:

```python
def migrate_enriched_embedding(
    episodic_memory: "EpisodicMemory",
) -> int:
    """AD-605: Re-embed all episodes with enriched document text.

    Reads all episodes, rebuilds documents via _prepare_document(), and
    re-adds with enriched text. Also populates the user_input metadata
    field for backward compatibility.

    Must run AFTER collection creation, BEFORE any queries.
    Returns count of re-embedded episodes (0 if no migration needed).
    """
    if not episodic_memory or not episodic_memory._collection:
        return 0

    collection = episodic_memory._collection
    meta = collection.metadata or {}
    version = meta.get("enriched_embedding_version", 0)

    if version >= 1:
        logger.debug("AD-605: Enriched embedding already applied (v%d), skipping", version)
        return 0

    t0 = time.time()
    migrated = 0

    try:
        existing = collection.get(include=["documents", "metadatas"])
        ids = existing.get("ids") or []
        documents = existing.get("documents") or []
        metadatas = existing.get("metadatas") or []

        if not ids:
            collection.modify(metadata={**meta, "enriched_embedding_version": 1})
            logger.info("AD-605: No episodes to re-embed, updated metadata")
            return 0

        # Rebuild enriched documents from metadata (reconstruct Episode enough for _prepare_document)
        batch_size = 100
        for start in range(0, len(ids), batch_size):
            end = min(start + batch_size, len(ids))
            for i in range(start, end):
                ep_meta = metadatas[i] or {}
                original_doc = documents[i] or ""

                # Store original user_input if not already present
                if "user_input" not in ep_meta:
                    ep_meta["user_input"] = original_doc

                # Reconstruct minimal Episode for _prepare_document
                anchors_raw = ep_meta.get("anchors_json", "")
                anchors = AnchorFrame(**json.loads(anchors_raw)) if anchors_raw else None
                enriched_doc = EpisodicMemory._prepare_document(
                    Episode(
                        id=ids[i],
                        timestamp=float(ep_meta.get("timestamp", 0.0)),
                        user_input=original_doc,
                        dag_summary={},
                        outcomes=[],
                        agent_ids=[],
                        duration_ms=0.0,
                        anchors=anchors,
                    )
                )

                # Update in place
                collection.update(
                    ids=[ids[i]],
                    documents=[enriched_doc],
                    metadatas=[ep_meta],
                )
                migrated += 1

        # Mark migration complete
        collection.modify(metadata={**meta, "enriched_embedding_version": 1})
        elapsed = time.time() - t0
        logger.info("AD-605: Re-embedded %d episodes with enriched text (%.1fs)", migrated, elapsed)
    except Exception:
        logger.warning("AD-605: Enriched embedding migration failed (non-fatal)", exc_info=True)

    return migrated
```

**Wire into startup:** The migration must be called in `src/probos/startup/cognitive_services.py` after the existing `migrate_embedding_model()` call at line 216. Add after line 220:

```python
    # AD-605: Re-embed with enriched anchor metadata
    if episodic_memory:
        try:
            from probos.cognitive.episodic import migrate_enriched_embedding
            migrated = migrate_enriched_embedding(episodic_memory)
            if migrated > 0:
                logger.info("AD-605: Re-embedded %d episodes with enriched anchor text", migrated)
        except Exception:
            logger.warning("AD-605: Enriched embedding migration failed (non-fatal)", exc_info=True)
```

Note: `migrate_enriched_embedding()` is a sync function (not async) because it uses ChromaDB's sync API. No `await` needed.

### Change 5 (optional optimization): Query enrichment

**File:** `src/probos/cognitive/episodic.py`
**Location:** `recall_for_agent_scored()` at line ~1430-1432

When the caller provides anchor context (via the recall chain), prepend matching context to the query text before embedding. This ensures query embeddings are closer to episodes from the same context.

**This is NOT required for the core feature** — the enriched storage alone improves retrieval. Query enrichment is an optional second step that can be deferred. If implemented now:

Find where `recall_weighted()` is called from `cognitive_agent.py` and check if `_query_watch_section` or department context is available at the call site. If so, add an optional `query_context` parameter to `recall_for_agent_scored()` that prepends context brackets to the query before reformulation.

**Defer this to a follow-up** if the storage-side enrichment alone shows measurable improvement in qualification probes.

## Tests

**New file:** `tests/test_ad605_enhanced_embedding.py`

Use existing test patterns from `tests/test_ad584c_scoring_rebalance.py` and `tests/test_bf155_temporal_merge.py` for fixture patterns.

### TestPrepareDocument (5 tests)

1. **`test_full_anchor_prepended`** — Episode with all anchor fields populated. Verify document starts with `[department] [channel] [watch_section] [trigger_type]` followed by user_input.

2. **`test_empty_fields_omitted`** — Episode with `department="science"`, `channel=""`, `watch_section="first"`, `trigger_type=""`. Verify only non-empty fields appear: `[science] [first] user_input_text`.

3. **`test_no_anchors_returns_user_input`** — Episode with `anchors=None`. Verify returns `user_input` unchanged.

4. **`test_empty_user_input`** — Episode with anchors but empty user_input. Verify document is just the anchor brackets.

5. **`test_format_consistency`** — Verify brackets and spacing are consistent across multiple calls (idempotent).

### TestStoreUsesEnrichedDocument (3 tests)

6. **`test_store_uses_prepare_document`** — Mock `_collection.add()`, call `store()`, verify `documents=` contains enriched text (not raw user_input).

7. **`test_seed_uses_prepare_document`** — Mock `_collection.add()`, call `seed()`, verify batch_docs contain enriched text.

8. **`test_force_update_uses_prepare_document`** — Mock `_collection.upsert()`, call `_force_update()`, verify documents contain enriched text.

### TestMetadataPreservation (3 tests)

9. **`test_original_user_input_in_metadata`** — After `store()`, verify metadata dict contains `"user_input"` key with the original (non-enriched) text.

10. **`test_metadata_to_episode_uses_stored_user_input`** — Call `_metadata_to_episode()` with metadata containing `"user_input"` key. Verify the Episode's `user_input` is the stored original, not the enriched document.

11. **`test_metadata_to_episode_fallback_to_document`** — Call `_metadata_to_episode()` with metadata lacking `"user_input"` key (pre-migration episode). Verify the Episode's `user_input` falls back to the document text.

### TestMigration (4 tests)

12. **`test_migration_enriches_existing_episodes`** — Pre-populate collection with old-format episodes (raw user_input as document, no user_input in metadata). Run `migrate_enriched_embedding()`. Verify documents are now enriched and metadata has `user_input` field.

13. **`test_migration_skips_if_already_done`** — Set `enriched_embedding_version=1` in collection metadata. Run migration. Verify returns 0 and no episodes modified.

14. **`test_migration_handles_empty_collection`** — Empty collection. Run migration. Verify returns 0, metadata gets version marker.

15. **`test_migration_preserves_original_user_input`** — Pre-populate, migrate, then reconstruct episodes via `_metadata_to_episode()`. Verify `user_input` is the original text (not enriched).

### Fixtures

Use `EpisodicMemory.__new__()` pattern from `test_ad584c_scoring_rebalance.py` to create minimal instances. Create `Episode` instances with `AnchorFrame(department=..., channel=..., watch_section=..., trigger_type=...)`. Import from `probos.types` (Episode, AnchorFrame) and `probos.cognitive.episodic` (EpisodicMemory).

## Verification

```bash
python -m pytest tests/test_ad605_enhanced_embedding.py -v
```

Then run the memory-related regression suite:
```bash
python -m pytest tests/test_bf155_temporal_merge.py tests/test_bf147_temporal_probe.py tests/test_bf152_temporal_keyword.py tests/test_ad584c_scoring_rebalance.py -v
```

After deployment, run a full qualification probe to compare scores:
```
/qualify run systems_analyst
```

Expected improvement: better semantic separation between episodes from different departments/watches, reducing the reliance on post-retrieval composite scoring for disambiguation.

## Files Modified

| File | Changes |
|------|---------|
| `src/probos/cognitive/episodic.py` | `_prepare_document()` static method, 3 write site updates (store/seed/_force_update), `_episode_to_metadata()` adds `user_input` field, `_metadata_to_episode()` uses stored `user_input`, new `migrate_enriched_embedding()` function |
| `src/probos/startup/cognitive_services.py` | Wire `migrate_enriched_embedding()` after `migrate_embedding_model()` (line 220) |
| `tests/test_ad605_enhanced_embedding.py` | **NEW** — 15 tests across 4 classes |

## Engineering Principles

- **Elaborative Encoding:** Richer document text → better retrieval. Cognitive science validated (Craik & Tulving 1975).
- **Open/Closed:** New static method, no changes to existing method signatures. All callers unaffected.
- **DRY:** Single `_prepare_document()` method used at all 3 write sites.
- **Defense in Depth:** Enriched embedding improves retrieval at the vector similarity level, complementing post-retrieval anchor filters (AD-570) and composite scoring (AD-584c).
- **Backward Compatible:** Pre-migration episodes work via `metadata.get("user_input", document)` fallback. Migration is one-time, idempotent, and non-fatal.
- **No new imports required** — all files already import the needed modules.
