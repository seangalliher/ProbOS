# AD-570b: Participant Array Filtering — Episode Participant Index

## Context

AD-570 promoted scalar AnchorFrame fields (department, channel, trigger_type, trigger_agent) to top-level ChromaDB metadata for native `where`-clause filtering. The `participants` field (`list[str]` of callsigns) was explicitly deferred because ChromaDB does not support list-type metadata values. Currently, there is **no way to query episodes by participant** — not even post-retrieval filtering. The `agent_id` post-retrieval filter in `recall_by_anchor()` checks episode **ownership** (`agent_ids_json`), not social **presence** (`participants`).

Additionally, `agent_ids_json` filtering is repeated 10 times across `episodic.py` as O(N) full-collection scans with JSON parsing per episode. Two of these (lines 719 and 739) use a fragile string `in` check instead of proper JSON parsing, working only by accident because UUIDs don't substring-match.

## Objective

Create a **SQLite sidecar junction table** (`episode_participants`) that indexes both `agent_ids` (sovereign IDs, role=author) and `participants` (callsigns, role=participant) per episode. This enables O(1) indexed lookups for "find all episodes involving agent X" — replacing 10 O(N) Python post-retrieval filter paths.

## Architecture Decision

**SQLite sidecar junction table** was chosen over two alternatives:
- **Metadata explosion** (one boolean key per agent): doesn't scale with 55+ agents, requires schema evolution
- **String substring matching**: ChromaDB doesn't support `$contains`, fragile with short IDs

SQLite sidecar is ProbOS's **established pattern** — `activation_tracker.db` (AD-567d) and `eviction_audit.db` (AD-541f) both follow this exact model.

## File Changes

### 1. NEW: `src/probos/cognitive/participant_index.py`

Create a new `ParticipantIndex` class following the `ActivationTracker` pattern exactly (see `src/probos/cognitive/activation_tracker.py`).

**Constructor signature:**
```python
class ParticipantIndex:
    def __init__(
        self,
        *,
        connection_factory: Callable[..., Any] | None = None,
        db_path: str = "",
    ) -> None:
```

**Schema:**
```sql
CREATE TABLE IF NOT EXISTS episode_participants (
    episode_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    callsign TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'author',
    PRIMARY KEY (episode_id, agent_id, role)
);
CREATE INDEX IF NOT EXISTS idx_ep_part_agent ON episode_participants(agent_id);
CREATE INDEX IF NOT EXISTS idx_ep_part_callsign ON episode_participants(callsign);
CREATE INDEX IF NOT EXISTS idx_ep_part_role ON episode_participants(role);
```

Column semantics:
- `episode_id`: ChromaDB episode ID (foreign key by convention)
- `agent_id`: Sovereign ID (durable key, from `Episode.agent_ids` or resolved from callsign)
- `callsign`: Human-readable name (from `AnchorFrame.participants`). May be empty for author rows where only sovereign ID is known.
- `role`: `'author'` (from `agent_ids`) or `'participant'` (from `anchors.participants`)

**Methods:**

```python
async def start(self) -> None:
    """Initialize SQLite connection and create schema."""
    # Follow ActivationTracker.start() pattern exactly:
    # if self._connection_factory → use it, else import aiosqlite and connect

async def stop(self) -> None:
    """Close the database connection."""

async def record_episode(
    self,
    episode_id: str,
    agent_ids: list[str],
    participants: list[str],
) -> None:
    """Index all agents and participants for a single episode.

    - For each agent_id in agent_ids: INSERT OR IGNORE with role='author', callsign=''
    - For each participant in participants: INSERT OR IGNORE with role='participant', agent_id=participant, callsign=participant

    Note: participant entries use the callsign as both agent_id and callsign
    because AnchorFrame.participants contains callsigns, not sovereign IDs.
    The callsign column enables direct callsign lookups.
    """

async def record_episode_batch(
    self,
    records: list[tuple[str, list[str], list[str]]],
) -> None:
    """Bulk insert for seed/migration. Each tuple is (episode_id, agent_ids, participants)."""

async def get_episode_ids_for_agent(self, agent_id: str) -> list[str]:
    """Return all episode IDs where this sovereign ID appears (any role)."""
    # SELECT DISTINCT episode_id FROM episode_participants WHERE agent_id = ?

async def get_episode_ids_for_callsign(self, callsign: str) -> list[str]:
    """Return all episode IDs where this callsign appears as participant."""
    # SELECT DISTINCT episode_id FROM episode_participants WHERE callsign = ?

async def get_episode_ids_for_participants(
    self,
    participants: list[str],
    require_all: bool = False,
) -> list[str]:
    """Return episode IDs matching any (or all) of the given callsigns.

    If require_all=False (default): OR semantics — any participant present.
    If require_all=True: AND semantics — all participants must be present.

    AND query pattern:
        SELECT episode_id FROM episode_participants
        WHERE callsign IN (?, ?, ...)
        GROUP BY episode_id
        HAVING COUNT(DISTINCT callsign) = ?
    """

async def count_for_agent(self, agent_id: str) -> int:
    """Return count of episodes for this agent. Replaces O(N) full-collection scan."""
    # SELECT COUNT(DISTINCT episode_id) FROM episode_participants WHERE agent_id = ?

async def delete_episodes(self, episode_ids: list[str]) -> None:
    """Remove all participant records for the given episode IDs. For eviction cleanup."""
    # DELETE FROM episode_participants WHERE episode_id IN (?, ?, ...)
    # Process in batches of 500 to avoid SQLite variable limit
```

### 2. MODIFY: `src/probos/cognitive/episodic.py`

#### 2a. Add participant index field and setter

After line 303 (`self._activation_tracker: Any = None`), add:
```python
self._participant_index: Any = None  # AD-570b: Participant index sidecar
```

After the `set_activation_tracker` method (line 305-307), add:
```python
def set_participant_index(self, index: Any) -> None:
    """AD-570b: Wire the participant index after construction."""
    self._participant_index = index
```

#### 2b. Dual-write in `store()`

After the FTS5 dual-write block (after line 518), add:
```python
# AD-570b: Participant index dual-write
if self._participant_index is not None:
    try:
        participants = episode.anchors.participants if episode.anchors else []
        await self._participant_index.record_episode(
            episode.id, episode.agent_ids, participants,
        )
    except Exception:
        logger.debug("AD-570b: Participant index insert failed for %s", episode.id[:8], exc_info=True)
```

#### 2c. Dual-write in `seed()`

After the FTS5 seed block (after line 414), add a similar batch insert:
```python
# AD-570b: Populate participant index for seeded episodes
if seeded > 0 and self._participant_index is not None:
    try:
        batch = []
        for ep in episodes:
            if ep.id in existing_ids:
                continue
            participants = ep.anchors.participants if ep.anchors else []
            batch.append((ep.id, ep.agent_ids, participants))
        if batch:
            await self._participant_index.record_episode_batch(batch)
    except Exception:
        logger.debug("AD-570b: Participant index seed failed", exc_info=True)
```

#### 2d. Eviction cleanup in `_evict()`

After the activation tracker cleanup block (after line 608), add:
```python
# AD-570b: Participant index cleanup on eviction
if self._participant_index:
    try:
        await self._participant_index.delete_episodes(ids_to_delete)
    except Exception:
        logger.debug("AD-570b: Participant index eviction cleanup failed", exc_info=True)
```

#### 2e. Eviction cleanup in `evict_by_ids()`

After the activation cleanup block (after line 675), add:
```python
# AD-570b: Participant index cleanup
if self._participant_index:
    try:
        await self._participant_index.delete_episodes(valid_ids)
    except Exception:
        logger.debug("AD-570b: Participant index eviction cleanup failed", exc_info=True)
```

#### 2f. Fix string-contains bugs at lines 719 and 739

**Line 719** — replace:
```python
if agent_id in meta.get("agent_ids_json", "[]"):
```
with:
```python
try:
    _ids = json.loads(meta.get("agent_ids_json", "[]"))
except (json.JSONDecodeError, TypeError):
    _ids = []
if agent_id in _ids:
```

**Line 739** — replace:
```python
if agent_id not in meta.get("agent_ids_json", "[]"):
```
with:
```python
try:
    _ids = json.loads(meta.get("agent_ids_json", "[]"))
except (json.JSONDecodeError, TypeError):
    _ids = []
if agent_id not in _ids:
```

#### 2g. Add `participants` parameter to `recall_by_anchor()`

Add `participants: list[str] | None = None` to the method signature. Before the ChromaDB query, if participants is provided and `self._participant_index` is available:

```python
# AD-570b: Pre-filter by participant using sidecar index
candidate_ids: list[str] | None = None
if participants and self._participant_index:
    try:
        candidate_ids = await self._participant_index.get_episode_ids_for_participants(
            participants, require_all=True,
        )
        if not candidate_ids:
            return []  # No episodes match the participant filter
    except Exception:
        logger.debug("AD-570b: Participant index query failed, falling back", exc_info=True)
        candidate_ids = None
```

Then, in the ChromaDB `get()` call, if `candidate_ids` is not None, use `ids=candidate_ids` to constrain the retrieval instead of fetching the entire collection. The existing `where` filter still applies for department/channel/trigger_type/trigger_agent. If both `ids` and `where` are provided, ChromaDB intersects them.

For the enumeration path (no semantic_query), replace:
```python
result = self._collection.get(where=where_filter, ...)
```
with:
```python
get_kwargs: dict[str, Any] = {"include": ["metadatas", "documents"]}
if candidate_ids is not None:
    get_kwargs["ids"] = candidate_ids
if where_filter:
    get_kwargs["where"] = where_filter
result = self._collection.get(**get_kwargs)
```

For the semantic path (with semantic_query), if `candidate_ids` is not None, post-filter the query results to only include episodes whose IDs are in `candidate_ids`.

#### 2h. New migration function

Add a new top-level migration function (after `migrate_anchor_metadata`):

```python
async def migrate_participant_index(
    episodic_memory: "EpisodicMemory",
) -> int:
    """AD-570b: Backfill participant index from existing episodes.

    Reads agent_ids_json and anchors_json from all episodes,
    populates the participant index sidecar.
    """
    if not episodic_memory or not episodic_memory._collection:
        return 0
    if not episodic_memory._participant_index:
        return 0

    t0 = time.time()
    result = episodic_memory._collection.get(include=["metadatas"])
    ids = result.get("ids") or []
    metas = result.get("metadatas") or []

    batch = []
    for ep_id, meta in zip(ids, metas):
        # Parse agent_ids
        try:
            agent_ids = json.loads(meta.get("agent_ids_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            agent_ids = []

        # Parse participants from anchors
        participants = []
        anchors_raw = meta.get("anchors_json", "")
        if anchors_raw:
            try:
                anchors_dict = json.loads(anchors_raw)
                participants = anchors_dict.get("participants", [])
            except (json.JSONDecodeError, TypeError):
                pass

        if agent_ids or participants:
            batch.append((ep_id, agent_ids, participants))

    if batch:
        await episodic_memory._participant_index.record_episode_batch(batch)

    elapsed = time.time() - t0
    logger.info("AD-570b: Participant index populated for %d episodes in %.1fs", len(batch), elapsed)
    return len(batch)
```

### 3. MODIFY: `src/probos/startup/cognitive_services.py`

After the AD-570 migration block (after line 189), add:

```python
# AD-570b: Create and wire participant index
if episodic_memory:
    try:
        from probos.cognitive.participant_index import ParticipantIndex

        participant_index = ParticipantIndex(
            db_path=str(data_dir / "participant_index.db"),
        )
        await participant_index.start()
        episodic_memory.set_participant_index(participant_index)
        logger.info("AD-570b: Participant index started")

        # One-time migration: backfill from existing episodes
        from probos.cognitive.episodic import migrate_participant_index
        migrated = await migrate_participant_index(episodic_memory)
        if migrated > 0:
            logger.info("AD-570b: Indexed participants for %d episodes", migrated)
    except Exception:
        logger.warning("AD-570b: Participant index start failed (non-fatal)", exc_info=True)
```

### 4. MODIFY: `src/probos/cognitive/episodic.py` — `stop()` method

After the FTS5 close block (after line 345), add:
```python
# AD-570b: Close participant index
if self._participant_index is not None:
    try:
        await self._participant_index.stop()
    except Exception:
        pass
    self._participant_index = None
```

### 5. NEW: Tests in `tests/test_participant_index.py`

Create a dedicated test file. Follow the patterns in `tests/test_anchor_indexed_recall.py`.

**Test classes:**

#### `TestParticipantIndex` (unit tests for the sidecar)
1. `test_record_and_query_by_agent_id` — store episode with agent_ids, query by sovereign ID
2. `test_record_and_query_by_callsign` — store episode with participants, query by callsign
3. `test_query_participants_any` — OR semantics: any of [A, B] present
4. `test_query_participants_all` — AND semantics: both A and B must be present
5. `test_count_for_agent` — verify count matches expected
6. `test_delete_episodes` — verify cleanup removes all rows for deleted episode IDs
7. `test_record_episode_batch` — bulk insert, verify all queryable
8. `test_duplicate_insert_ignored` — INSERT OR IGNORE doesn't error on re-insert
9. `test_empty_participants` — episode with no participants, only agent_ids

#### `TestParticipantIndexIntegration` (wired to EpisodicMemory)
10. `test_store_populates_index` — store() dual-writes to participant index
11. `test_seed_populates_index` — seed() batch-writes to participant index
12. `test_evict_cleans_index` — eviction removes participant records
13. `test_evict_by_ids_cleans_index` — explicit eviction removes participant records
14. `test_recall_by_anchor_with_participants` — recall_by_anchor(participants=["worf"]) returns correct episodes
15. `test_recall_by_anchor_participants_and_department` — combined filter: participants AND department

#### `TestMigration`
16. `test_migrate_participant_index` — migration backfills from existing episodes
17. `test_migrate_empty_collection` — migration with no episodes returns 0
18. `test_migrate_no_index` — migration without participant_index wired returns 0

#### `TestStringContainsBugFix`
19. `test_is_rate_limited_uses_json_parse` — verify line 719 fix uses proper JSON parsing
20. `test_is_duplicate_content_uses_json_parse` — verify line 739 fix uses proper JSON parsing

**Fixture pattern** (from existing tests):
```python
@pytest.fixture
def tmp_episodic(tmp_path):
    em = EpisodicMemory(db_path=str(tmp_path / "chroma" / "episodes.db"), max_episodes=100)
    return em
```

For participant index unit tests:
```python
@pytest.fixture
async def participant_index(tmp_path):
    from probos.cognitive.participant_index import ParticipantIndex
    idx = ParticipantIndex(db_path=str(tmp_path / "participant_index.db"))
    await idx.start()
    yield idx
    await idx.stop()
```

## Engineering Principles Compliance

| Principle | How This Build Complies |
|-----------|------------------------|
| **SOLID/S** | ParticipantIndex is a single-responsibility class — participant lookup only |
| **SOLID/D** | Constructor injection via `connection_factory` callable, not direct `aiosqlite.connect()` |
| **Cloud-Ready Storage** | Same abstract connection interface as ActivationTracker — commercial overlay can swap SQLite → Postgres |
| **DRY** | Unifies agent_ids + participants into one index. Replaces 10 copy-pasted JSON parse+filter blocks with indexed queries |
| **Law of Demeter** | New class with public API, wired via `set_participant_index()` setter — no private attribute patching |
| **Fail Fast** | Migration logs warnings on parse failures. All sidecar operations wrapped in try/except with `logger.debug()` (non-critical, log-and-degrade) |
| **Defense in Depth** | Validates at write time (INSERT OR IGNORE). Participant index is additive — if it fails, existing ChromaDB queries still work |

## Scope Boundary

**In scope:**
- ParticipantIndex class with full CRUD
- Dual-write on store(), seed(), eviction
- recall_by_anchor() participant filter parameter
- Migration function for existing episodes
- Startup wiring in cognitive_services.py
- Fix string-contains bugs at lines 719/739
- 20 tests

**Out of scope (deferred):**
- Replacing ALL 10 `agent_ids_json` post-retrieval filters with sidecar queries (future optimization — the sidecar is wired and queryable, but converting `recall_for_agent()`, `recall_for_agent_recent()`, `recall_weighted()`, etc. to use it is a separate pass)
- AD-570c (Natural Language Anchor Query Routing)
- Callsign-to-sovereign-ID resolution (would require identity_registry access in the index — keep simple for now, store both independently)

## Verification

After building, run:
```bash
python -m pytest tests/test_participant_index.py -v
python -m pytest tests/test_anchor_indexed_recall.py -v
python -m pytest tests/test_episodic_memory.py -v
```

All three must pass. No regressions in existing episodic memory tests.
