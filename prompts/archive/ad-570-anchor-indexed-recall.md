# AD-570: Anchor-Indexed Episodic Recall — Structured AnchorFrame Queries

## Priority: High | Scope: Medium | Type: Infrastructure Enhancement

## Context

ProbOS episodic memory (AD-567a) attaches rich AnchorFrame metadata to every episode — temporal, spatial, social, causal, and evidential dimensions. However, recall is semantic-only. You cannot query BY anchor fields. No way to ask "find all episodes from Engineering department" or "find all episodes triggered by Worf."

The root cause: `_episode_to_metadata()` packs all anchor fields into a single `anchors_json` blob. ChromaDB `where` filters only work on top-level scalar metadata fields (str, int, float, bool), NOT on values inside JSON-serialized strings.

### What This AD Delivers

1. **Metadata promotion** — Promote 4 key anchor fields to top-level ChromaDB metadata for native `where` clause filtering
2. **One-time migration** — Backfill promoted fields from existing `anchors_json` blobs (following BF-103 pattern)
3. **`recall_by_anchor()` API** — Two retrieval modes: top-k with semantic re-ranking, and enumeration without embedding
4. **Integration** — Wire migration into startup, expose via existing EpisodicMemory interface

### Deferred (NOT in this AD)

- **AD-570b:** Participant array filtering (multi-value, needs sidecar index)
- **AD-570c:** Natural language anchor query routing (NL intent → structured query)
- SQLite anchor sidecar: NOT needed — ChromaDB metadata promotion covers all cases

## Design

### 1. Metadata Promotion — `_episode_to_metadata()` changes

**File:** `src/probos/cognitive/episodic.py`, method `_episode_to_metadata()` (line ~980)

Add 4 promoted fields to the metadata dict ALONGSIDE the existing `anchors_json` blob. `anchors_json` stays for backward compatibility and for fields NOT promoted (duty_cycle_id, watch_section, channel_id, participants, thread_id, event_log_window).

**Promoted fields** (all strings, ChromaDB scalar-compatible):

| Promoted Key | Source | Why |
|---|---|---|
| `anchor_department` | `ep.anchors.department` | Most common filter: "episodes from Engineering" |
| `anchor_channel` | `ep.anchors.channel` | "episodes from ward_room" vs "dm" vs "duty_report" |
| `anchor_trigger_type` | `ep.anchors.trigger_type` | "episodes from proactive_think" vs "direct_message" |
| `anchor_trigger_agent` | `ep.anchors.trigger_agent` | "episodes triggered by Worf" |

**Implementation — add after `anchors_json` assignment (line ~1015):**

```python
# AD-570: Promote key anchor fields for ChromaDB where-clause filtering
if ep.anchors:
    metadata["anchor_department"] = ep.anchors.department or ""
    metadata["anchor_channel"] = ep.anchors.channel or ""
    metadata["anchor_trigger_type"] = ep.anchors.trigger_type or ""
    metadata["anchor_trigger_agent"] = ep.anchors.trigger_agent or ""
else:
    metadata["anchor_department"] = ""
    metadata["anchor_channel"] = ""
    metadata["anchor_trigger_type"] = ""
    metadata["anchor_trigger_agent"] = ""
```

**IMPORTANT:** `_episode_to_metadata()` is called from both `store()` (line ~418) and `seed()` (line ~314). Both paths automatically pick up the promoted fields. No changes needed to `store()` or `seed()`.

**`_metadata_to_episode()` — no changes needed.** It already reads `anchors_json` and constructs AnchorFrame. The promoted fields are write-only metadata for query filtering; they are never read back to reconstruct an Episode.

### 2. One-Time Migration — Backfill Promoted Fields

**File:** `src/probos/cognitive/episodic.py` — new function at module level (near `migrate_episode_agent_ids`)

```python
async def migrate_anchor_metadata(episodic_memory: "EpisodicMemory") -> int:
    """AD-570: Promote anchor fields to top-level metadata for ChromaDB filtering.

    One-time startup migration. Scans all episodes. For each episode that has
    anchors_json but is missing anchor_department, extracts key anchor fields
    and writes them as top-level metadata via upsert.

    Follows BF-103 migration pattern. Returns count of episodes updated.
    """
```

**Pattern:** Follow `migrate_episode_agent_ids()` exactly (lines 52-115):
1. `episodic_memory._collection.get(include=["metadatas", "documents"])` — fetch all
2. For each episode, check if `anchor_department` key is missing from metadata (migration guard)
3. If missing AND `anchors_json` is non-empty, parse anchors_json, extract the 4 fields, add to metadata dict
4. `episodic_memory._collection.upsert(ids=[ep_id], metadatas=[meta], documents=[doc])` — write back
5. Return count of migrated episodes
6. Wrap all in try/except, log total and elapsed time

**Migration guard:** Check `"anchor_department" not in meta` — if the key already exists, the episode was stored or migrated after AD-570, so skip it.

### 3. Startup Wiring

**File:** `src/probos/startup/cognitive_services.py` (after BF-103 migration, line ~177)

```python
# AD-570: Promote anchor fields to top-level ChromaDB metadata
if episodic_memory:
    try:
        from probos.cognitive.episodic import migrate_anchor_metadata
        migrated = await migrate_anchor_metadata(episodic_memory)
        if migrated > 0:
            logger.info("AD-570: Promoted anchor metadata for %d episodes", migrated)
    except Exception:
        logger.warning("AD-570: Anchor metadata migration failed (non-fatal)", exc_info=True)
```

### 4. `recall_by_anchor()` API

**File:** `src/probos/cognitive/episodic.py` — new method on `EpisodicMemory` class

Add after `recall_weighted()` method (after line ~1270).

```python
async def recall_by_anchor(
    self,
    *,
    department: str = "",
    channel: str = "",
    trigger_type: str = "",
    trigger_agent: str = "",
    agent_id: str = "",
    time_range: tuple[float, float] | None = None,
    semantic_query: str = "",
    limit: int = 50,
) -> list[Episode]:
    """AD-570: Structured anchor-field recall with optional semantic re-ranking.

    Two retrieval modes:
    1. **Enumeration** (no semantic_query): Uses ChromaDB .get() with where
       filters. Returns ALL matching episodes up to limit. No embedding needed.
    2. **Top-k with re-ranking** (semantic_query provided): Uses ChromaDB
       .query() with where filters + semantic similarity. Returns top-k
       matches that satisfy BOTH structural constraints and semantic relevance.

    Args:
        department: Filter by anchor_department (exact match).
        channel: Filter by anchor_channel (exact match).
        trigger_type: Filter by anchor_trigger_type (exact match).
        trigger_agent: Filter by anchor_trigger_agent (exact match).
        agent_id: Filter by agent_ids_json (post-retrieval Python filter).
        time_range: Filter by timestamp range (start, end) inclusive.
        semantic_query: If provided, uses .query() for semantic re-ranking.
            If empty, uses .get() for pure structured enumeration.
        limit: Max results to return.

    Returns:
        List of Episode objects matching the filters, sorted by:
        - Semantic similarity (descending) if semantic_query provided
        - Timestamp (descending) if enumeration mode
    """
```

**Implementation details:**

#### Build the `where` filter dict

Construct a ChromaDB `where` clause from non-empty filter params:

```python
conditions: list[dict] = []
if department:
    conditions.append({"anchor_department": department})
if channel:
    conditions.append({"anchor_channel": channel})
if trigger_type:
    conditions.append({"anchor_trigger_type": trigger_type})
if trigger_agent:
    conditions.append({"anchor_trigger_agent": trigger_agent})
if time_range:
    conditions.append({"timestamp": {"$gte": time_range[0]}})
    conditions.append({"timestamp": {"$lte": time_range[1]}})

where: dict | None = None
if len(conditions) == 1:
    where = conditions[0]
elif len(conditions) > 1:
    where = {"$and": conditions}
```

**IMPORTANT:** If no filter conditions are provided AND no semantic_query is provided, return an empty list (refuse to enumerate the entire collection).

#### Mode 1: Enumeration (no `semantic_query`)

```python
if not semantic_query:
    if not where:
        return []  # No filters + no query = refuse to dump all
    result = self._collection.get(
        where=where,
        include=["metadatas", "documents"],
        limit=limit,
    )
    # ... convert to Episodes via _metadata_to_episode
    # ... post-filter by agent_id if provided (check agent_ids_json)
    # ... sort by timestamp descending
    return episodes[:limit]
```

**Note on ChromaDB `.get()` limit:** ChromaDB's `.get()` method does NOT take a `limit` parameter directly when combined with `where`. If this causes issues, fetch all matching and slice in Python.

#### Mode 2: Top-k with semantic re-ranking (`semantic_query` provided)

```python
if semantic_query:
    count = self._collection.count()
    if count == 0:
        return []
    n_results = min(limit * 3, count)  # Over-fetch for re-ranking
    kwargs = {"query_texts": [semantic_query], "n_results": n_results,
              "include": ["metadatas", "documents", "distances"]}
    if where:
        kwargs["where"] = where
    result = self._collection.query(**kwargs)
    # ... convert to Episodes via _metadata_to_episode
    # ... post-filter by agent_id if provided
    # ... already sorted by semantic similarity (ChromaDB default)
    return episodes[:limit]
```

#### Post-retrieval agent_id filtering

Both modes must filter by `agent_id` in Python (not ChromaDB) because agent_ids are stored as a JSON array string. Same pattern as `recall_for_agent_scored()` lines 1094-1100:

```python
if agent_id:
    agent_ids_json = metadata.get("agent_ids_json", "[]")
    try:
        agent_ids = json.loads(agent_ids_json)
    except (json.JSONDecodeError, TypeError):
        agent_ids = []
    if agent_id not in agent_ids:
        continue  # Skip this episode
```

#### Activation tracking

Record deliberate recall access for activation tracking (same pattern as `recall_for_agent_scored()` lines 1110-1117):

```python
if episodes and self._activation_tracker:
    try:
        await self._activation_tracker.record_batch_access(
            [ep.id for ep in episodes], access_type="recall"
        )
    except Exception:
        pass
```

#### Hash verification

If `self._verify_on_recall` is True, verify content hash for each episode (same pattern as `recall_for_agent_scored()` lines 1103-1105):

```python
if self._verify_on_recall:
    stored_hash = metadata.get("content_hash", "")
    _verify_episode_hash(ep, stored_hash, metadata, self._collection)
```

## Files Modified

| File | Change |
|---|---|
| `src/probos/cognitive/episodic.py` | `_episode_to_metadata()` — add 4 promoted fields. New `migrate_anchor_metadata()` function. New `recall_by_anchor()` method. |
| `src/probos/startup/cognitive_services.py` | Wire `migrate_anchor_metadata()` after BF-103 migration |

**Total: 2 files.**

## Test Requirements

### File: `tests/test_anchor_indexed_recall.py`

Create a new test file. All tests async with `@pytest.mark.asyncio`.

### Metadata Promotion Tests (5 tests)

1. **test_episode_to_metadata_promotes_anchor_fields** — Create Episode with AnchorFrame(department="medical", channel="ward_room", trigger_type="proactive_think", trigger_agent="echo"). Call `_episode_to_metadata()`. Assert `anchor_department == "medical"`, `anchor_channel == "ward_room"`, etc.

2. **test_episode_to_metadata_empty_anchors** — Episode with `anchors=None`. Assert all 4 promoted fields are empty string `""`.

3. **test_episode_to_metadata_partial_anchors** — AnchorFrame with only department set, rest defaults. Assert `anchor_department == "engineering"`, other 3 are `""`.

4. **test_episode_to_metadata_preserves_anchors_json** — Promoted fields exist AND `anchors_json` blob still present with full data. Both co-exist.

5. **test_store_writes_promoted_fields_to_chromadb** — `store()` an episode, then `.get()` it back, verify promoted fields are in metadata.

### Migration Tests (5 tests)

6. **test_migrate_anchor_metadata_backfills_existing** — Manually insert episode into ChromaDB with `anchors_json` but WITHOUT promoted fields. Run `migrate_anchor_metadata()`. Verify promoted fields now present.

7. **test_migrate_anchor_metadata_skips_already_migrated** — Insert episode with promoted fields already present. Run migration. Assert `migrated == 0`.

8. **test_migrate_anchor_metadata_handles_empty_anchors** — Episode with `anchors_json == ""`. Should not crash, should set promoted fields to `""`.

9. **test_migrate_anchor_metadata_count** — Insert 3 episodes: 1 already migrated, 2 needing migration. Assert `migrated == 2`.

10. **test_migrate_anchor_metadata_empty_collection** — Empty collection. Assert `migrated == 0`, no crash.

### recall_by_anchor() Tests — Enumeration Mode (6 tests)

11. **test_recall_by_anchor_department_filter** — Store 3 episodes: 2 Engineering, 1 Medical. `recall_by_anchor(department="engineering")`. Assert 2 results.

12. **test_recall_by_anchor_channel_filter** — Store episodes with different channels. Filter by `channel="ward_room"`. Assert correct subset.

13. **test_recall_by_anchor_trigger_type_filter** — Filter by `trigger_type="proactive_think"`. Assert only proactive_think episodes returned.

14. **test_recall_by_anchor_combined_filters** — `recall_by_anchor(department="medical", channel="dm")`. Assert AND logic — only episodes matching BOTH.

15. **test_recall_by_anchor_time_range** — Store episodes at different timestamps. `recall_by_anchor(time_range=(t1, t2))`. Assert only episodes within range.

16. **test_recall_by_anchor_no_filters_returns_empty** — No filters, no semantic_query. Assert returns `[]`.

### recall_by_anchor() Tests — Semantic Mode (4 tests)

17. **test_recall_by_anchor_semantic_reranking** — Store episodes, `recall_by_anchor(department="engineering", semantic_query="warp core diagnostics")`. Assert results match department AND are semantically relevant.

18. **test_recall_by_anchor_semantic_no_filter** — `recall_by_anchor(semantic_query="some query")`. Assert works (pure semantic, no structural filter).

19. **test_recall_by_anchor_agent_id_filter** — Filter by `agent_id`. Assert post-retrieval Python filtering works correctly.

20. **test_recall_by_anchor_limit** — Store 10 matching episodes. `limit=3`. Assert at most 3 returned.

### Edge Cases (3 tests)

21. **test_recall_by_anchor_no_collection** — `_collection is None`. Assert returns `[]`, no crash.

22. **test_recall_by_anchor_trigger_agent_filter** — `recall_by_anchor(trigger_agent="worf")`. Assert correct subset.

23. **test_recall_by_anchor_activation_tracking** — Mock `_activation_tracker`, verify `record_batch_access` called with correct episode IDs after recall.

**Total: 23 tests.**

## Verification

After building:

```bash
uv run pytest tests/test_anchor_indexed_recall.py -v
```

Then run the full existing episodic test suite to ensure no regressions:

```bash
uv run pytest tests/test_episodic*.py tests/test_anchor*.py -v
```

## Principles Compliance

- **SOLID (S):** EpisodicMemory gets no new responsibilities — `recall_by_anchor()` is a query method like `recall_weighted()`. Migration is a module-level function like BF-103.
- **SOLID (O):** Extends metadata format without breaking existing consumers. `anchors_json` preserved.
- **DRY:** Follows established patterns — BF-103 migration, recall_for_agent_scored() filtering, _episode_to_metadata() field layout.
- **Fail Fast:** Migration logs and continues (non-fatal). `recall_by_anchor()` returns empty list on None collection.
- **Cloud-Ready:** No new SQLite tables. ChromaDB metadata is the sole storage — abstract connection interface preserved.
- **Law of Demeter:** No private member access in new code. Uses existing public/internal APIs.
