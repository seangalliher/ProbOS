# AD-567d: Anchor-Preserving Dream Consolidation + Active Forgetting

**Absorbs:** AD-559 (Provenance Tracking, deferred from AD-557), AD-462b (Active Forgetting)
**Depends:** AD-567a (Episode Anchor Metadata — COMPLETE), AD-567b (Salience-Weighted Recall — COMPLETE), AD-551 (Notebook Consolidation — COMPLETE)
**Prior art:** SEEM RPE (Lu 2026) provenance composition, ACT-R base-level activation (Anderson 1983/2007), Ebbinghaus forgetting curve, Complementary Learning Systems (McClelland 1995)

---

## Context

Dream consolidation (Steps 6–11) transforms raw episodes into higher-order artifacts: EpisodeClusters, Procedures, convergence reports, notebook consolidations, gap reports. Currently every derivative artifact **strips anchor provenance** — a procedure extracted from 5 well-anchored episodes looks identical to one extracted from speculation. And episode eviction is purely capacity-based (FIFO) — a frequently-recalled high-value episode and an never-accessed noise episode are treated identically when the 100K cap is hit.

AD-567d delivers two capabilities:

1. **Provenance Composition** (AD-559 absorption) — Dream consolidation carries forward anchor metadata from source episodes into derivative artifacts. Don't MERGE provenance, COMPOSE it (SEEM RPE principle).

2. **Activation-Based Memory Lifecycle** (AD-462b absorption) — ACT-R activation model replaces FIFO eviction. Episodes that are recalled gain activation; unreinforced episodes decay. Dream Step 12 prunes low-activation episodes. Activation integrates with RecallScore (AD-567b).

---

## Scope

### 1. Provenance Composition — Cluster Anchor Summary

**File: `src/probos/cognitive/episode_clustering.py`** (MODIFY)

Add `anchor_summary: dict[str, Any]` field to `EpisodeCluster` dataclass:

```python
anchor_summary: dict[str, Any] = field(default_factory=dict)
# Computed by summarize_cluster_anchors() — shared and representative anchor data
```

**File: `src/probos/cognitive/anchor_provenance.py`** (NEW)

Create `summarize_cluster_anchors(episodes: list[Episode]) -> dict[str, Any]`:

Given a list of episodes from a cluster, compute:
```python
{
    "shared_channel": str,          # channel if all episodes share the same, else ""
    "shared_department": str,       # department if all share, else ""
    "channels": list[str],          # unique channels across episodes
    "departments": list[str],       # unique departments across episodes
    "participants": list[str],      # union of all participants
    "trigger_types": list[str],     # unique trigger types
    "time_span": tuple[float, float],  # (min_timestamp, max_timestamp)
    "thread_ids": list[str],        # unique thread IDs (non-empty)
    "episode_count": int,           # number of source episodes
    "episode_ids": list[str],       # source episode IDs for traceability
    "mean_anchor_confidence": float, # average anchor confidence if AD-567c is present, else 0.0
}
```

Rules:
- Only include non-empty values in the summary
- Use `compute_anchor_confidence()` from `anchor_quality.py` if available (graceful import — `try: from .anchor_quality import compute_anchor_confidence; except: compute_anchor_confidence = None`)
- This is a pure function, no I/O

Wire into `cluster_episodes()` — after clusters are formed, call `summarize_cluster_anchors()` for each cluster using the episode objects. The caller (`dream_cycle()` Step 6) already has the `episodes` list; pass them to the clustering function or compute summaries in dream_cycle after clusters are formed.

**Implementation choice:** Compute in `dream_cycle()` after Step 6, not inside `cluster_episodes()`, because `cluster_episodes()` only receives embeddings, not full Episode objects. The dream_cycle has both:

```python
# Step 6 (after existing code):
for cluster in clusters:
    matched_eps = [ep for ep in episodes if ep.id in cluster.episode_ids]
    cluster.anchor_summary = summarize_cluster_anchors(matched_eps)
```

This requires `EpisodeCluster` to NOT be frozen (it's already a regular dataclass, not frozen — verify).

### 2. Procedure Provenance

**File: `src/probos/cognitive/procedures.py`** (MODIFY)

Add field to `Procedure` dataclass:

```python
source_anchors: list[dict[str, Any]] = field(default_factory=list)
# Anchor summaries from source episodes/clusters (AD-567d)
```

**Modify `_format_episode_blocks()`** — include anchor context when available:

```python
def _format_episode_blocks(episodes: list[Any]) -> str:
    blocks = []
    for ep in episodes:
        anchor_line = ""
        if getattr(ep, "anchors", None):
            af = ep.anchors
            parts = []
            if af.channel: parts.append(f"channel={af.channel}")
            if af.department: parts.append(f"dept={af.department}")
            if af.trigger_type: parts.append(f"trigger={af.trigger_type}")
            if af.participants: parts.append(f"participants={af.participants}")
            if parts:
                anchor_line = f"Anchors: {', '.join(parts)}\n"
        block = (
            "=== READ-ONLY EPISODE (do not modify, summarize, or reinterpret) ===\n"
            f"Episode ID: {ep.id}\n"
            f"User Input: {ep.user_input}\n"
            f"Outcomes: {json.dumps(ep.outcomes, default=str)}\n"
            f"DAG Summary: {json.dumps(ep.dag_summary, default=str)}\n"
            f"Reflection: {ep.reflection or 'none'}\n"
            f"Agents: {ep.agent_ids}\n"
            f"{anchor_line}"
            "=== END READ-ONLY EPISODE ==="
        )
        blocks.append(block)
    return "\n\n".join(blocks)
```

**Modify procedure extraction** — after `extract_procedure_from_cluster()` and `extract_compound_procedure_from_cluster()` return a Procedure, populate `source_anchors`:

In `dream_cycle()` Step 7, after procedure extraction (around line 271–275):

```python
if procedure:
    # AD-567d: Attach provenance anchors from source episodes
    from probos.cognitive.anchor_provenance import build_procedure_provenance
    procedure.source_anchors = build_procedure_provenance(matched_episodes)
```

**In `anchor_provenance.py`**, add:

```python
def build_procedure_provenance(episodes: list[Episode]) -> list[dict[str, Any]]:
    """Build provenance anchor list from source episodes for a procedure."""
    provenance = []
    for ep in episodes:
        entry: dict[str, Any] = {"episode_id": ep.id, "timestamp": ep.timestamp}
        if ep.anchors:
            af = ep.anchors
            entry["channel"] = af.channel
            entry["department"] = af.department
            entry["trigger_type"] = af.trigger_type
            entry["participants"] = list(af.participants) if af.participants else []
            entry["thread_id"] = af.thread_id
        provenance.append(entry)
    return provenance
```

**Modify `Procedure.to_dict()`** — include `source_anchors` in serialization. It's already a list of dicts, so `"source_anchors": self.source_anchors` in the return dict.

**Modify `Procedure.from_dict()`** — deserialize: `source_anchors=data.get("source_anchors", [])`.

**Modify `procedure_store.py` schema** — add `source_anchors_json TEXT DEFAULT '[]'` column to the procedures table. Migration: `ALTER TABLE procedures ADD COLUMN source_anchors_json TEXT DEFAULT '[]'`. Serialize/deserialize as JSON in `_save()` and `_load()`.

### 3. Convergence Report Provenance

**File: `src/probos/cognitive/dreaming.py`** (MODIFY Step 7g)

The convergence report already captures `contributing_agents` and `departments`. Enrich with anchor provenance.

In the convergence report generation block (around line 632–648), add anchor provenance section:

```python
# AD-567d: Collect source anchors from contributing notebook entries
source_anchors_section = ""
for ce in cluster_entries:
    doc = ce.get("_doc", {})
    # Check if the notebook entry's metadata has anchor provenance
    meta = doc.get("metadata", {})
    anchor_info = meta.get("source_anchors", [])
    if anchor_info:
        source_anchors_section += f"\n- **{ce['agent']}**: {len(anchor_info)} sourced episodes"

report_content = (
    f"## Convergence Report\n\n"
    f"**Agents:** {', '.join(sorted(cluster_agents))}\n\n"
    f"**Departments:** {', '.join(sorted(cluster_depts))}\n\n"
    f"**Coherence:** {coherence:.3f}\n\n"
    f"## Contributing Perspectives\n{perspectives}\n"
    f"## Convergent Finding\n\n{shared_summary}\n"
    f"## Provenance\n{source_anchors_section or 'No anchor provenance available.'}\n"
)
```

Also add an `anchors` key to the `conv_data` dict passed into DreamReport:

```python
conv_data = {
    "agents": sorted(cluster_agents),
    "departments": sorted(cluster_depts),
    "coherence": coherence,
    "topic": topic,
    "report_path": report_path,
    "source_entry_count": len(cluster_entries),  # AD-567d
}
```

### 4. Activation Tracking — Access Log

**File: `src/probos/cognitive/activation_tracker.py`** (NEW)

The ACT-R base-level activation formula: `B_i = ln(Σ_{j=1}^{n} t_j^{-d})` where `t_j` is time (seconds) since the j-th access and `d` is the decay parameter (typically 0.5).

Create `ActivationTracker` class:

```python
@dataclass
class ActivationTracker:
    """ACT-R base-level activation tracking for episodic memory (AD-462b).

    Tracks recall events per episode. Computes base-level activation
    using Anderson's (1983) formula: B_i = ln(Σ t_j^{-d}).

    Storage: lightweight SQLite table — episode_id + access timestamps.
    """

    def __init__(self, data_dir: str | Path, connection_factory=None):
        self._data_dir = Path(data_dir)
        self._db: DatabaseConnection | None = None
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def start(self) -> None:
        db_path = str(self._data_dir / "activation.db")
        self._db = await self._connection_factory.connect(db_path)
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                episode_id TEXT NOT NULL,
                accessed_at REAL NOT NULL,
                access_type TEXT NOT NULL DEFAULT 'recall'
            );
            CREATE INDEX IF NOT EXISTS idx_access_episode
                ON access_log(episode_id);
            CREATE INDEX IF NOT EXISTS idx_access_time
                ON access_log(accessed_at);
        """)
        await self._db.commit()
        await self._db.execute("PRAGMA journal_mode=WAL")

    async def record_access(self, episode_id: str, access_type: str = "recall") -> None:
        """Record an episode access event (recall, dream replay, etc.)."""
        if not self._db:
            return
        await self._db.execute(
            "INSERT INTO access_log (episode_id, accessed_at, access_type) VALUES (?, ?, ?)",
            (episode_id, time.time(), access_type),
        )
        await self._db.commit()

    async def record_batch_access(self, episode_ids: list[str], access_type: str = "recall") -> None:
        """Record access for multiple episodes at once."""
        if not self._db or not episode_ids:
            return
        now = time.time()
        await self._db.executemany(
            "INSERT INTO access_log (episode_id, accessed_at, access_type) VALUES (?, ?, ?)",
            [(eid, now, access_type) for eid in episode_ids],
        )
        await self._db.commit()

    async def compute_activation(self, episode_id: str, decay: float = 0.5) -> float:
        """Compute ACT-R base-level activation for an episode.

        B_i = ln(Σ_{j=1}^{n} t_j^{-d})

        where t_j = seconds since j-th access, d = decay parameter.
        Returns -inf for never-accessed episodes (ln(0)).
        """
        if not self._db:
            return float("-inf")
        now = time.time()
        cursor = await self._db.execute(
            "SELECT accessed_at FROM access_log WHERE episode_id = ?",
            (episode_id,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return float("-inf")

        total = 0.0
        for (accessed_at,) in rows:
            t_j = max(now - accessed_at, 1.0)  # floor at 1 second to avoid division issues
            total += t_j ** (-decay)

        import math
        return math.log(total) if total > 0 else float("-inf")

    async def compute_batch_activation(
        self, episode_ids: list[str], decay: float = 0.5,
    ) -> dict[str, float]:
        """Compute activation for multiple episodes efficiently."""
        if not self._db or not episode_ids:
            return {}
        now = time.time()
        placeholders = ",".join("?" for _ in episode_ids)
        cursor = await self._db.execute(
            f"SELECT episode_id, accessed_at FROM access_log WHERE episode_id IN ({placeholders})",
            episode_ids,
        )
        rows = await cursor.fetchall()

        # Group by episode_id
        accesses: dict[str, list[float]] = {}
        for eid, accessed_at in rows:
            accesses.setdefault(eid, []).append(accessed_at)

        import math
        result: dict[str, float] = {}
        for eid in episode_ids:
            times = accesses.get(eid, [])
            if not times:
                result[eid] = float("-inf")
                continue
            total = sum(max(now - t, 1.0) ** (-decay) for t in times)
            result[eid] = math.log(total) if total > 0 else float("-inf")
        return result

    async def prune_old_accesses(self, max_age_days: int = 180) -> int:
        """Remove access records older than max_age_days to bound storage."""
        if not self._db:
            return 0
        cutoff = time.time() - (max_age_days * 86400)
        cursor = await self._db.execute(
            "DELETE FROM access_log WHERE accessed_at < ?", (cutoff,),
        )
        await self._db.commit()
        return cursor.rowcount or 0

    async def delete_episode(self, episode_id: str) -> None:
        """Remove all access records for an evicted episode."""
        if not self._db:
            return
        await self._db.execute(
            "DELETE FROM access_log WHERE episode_id = ?", (episode_id,),
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None
```

**Configuration** — add to `DreamingConfig` in `config.py`:

```python
# AD-567d / AD-462b: Active forgetting
activation_decay_d: float = 0.5           # ACT-R decay parameter
activation_prune_threshold: float = -2.0  # Episodes below this activation are prunable
activation_access_max_age_days: int = 180  # Prune access log entries older than this
activation_enabled: bool = True            # Master toggle for activation-based lifecycle
```

### 5. Recall Reinforcement — Access Recording on Recall

**File: `src/probos/cognitive/episodic.py`** (MODIFY)

Add `_activation_tracker: ActivationTracker | None = None` attribute to `EpisodicMemory.__init__()`.

Add setter:
```python
def set_activation_tracker(self, tracker: ActivationTracker) -> None:
    self._activation_tracker = tracker
```

**Modify `recall_for_agent()`** — after successful recall, record access:

```python
# At the end of recall_for_agent(), before return:
if self._activation_tracker and episodes:
    try:
        await self._activation_tracker.record_batch_access(
            [ep.id for ep in episodes], access_type="recall",
        )
    except Exception:
        logger.debug("Activation recording failed", exc_info=True)
```

**Modify `recall_weighted()`** — same pattern, record access after scoring:

```python
# At the end of recall_weighted(), before return:
if self._activation_tracker and results:
    try:
        await self._activation_tracker.record_batch_access(
            [rs.episode.id for rs in results], access_type="recall_weighted",
        )
    except Exception:
        logger.debug("Activation recording failed", exc_info=True)
```

**Modify `recall_for_agent_scored()`** — record access for scored recalls too.

**Do NOT record access for `recent_for_agent()`** — this is a fallback/scan, not a deliberate recall. Only deliberate semantic recall should reinforce activation.

**Modify `_evict()`** — on eviction, clean up activation records:

```python
# After deleting from ChromaDB:
if self._activation_tracker and ids_to_delete:
    try:
        for eid in ids_to_delete:
            await self._activation_tracker.delete_episode(eid)
    except Exception:
        logger.debug("Activation cleanup on eviction failed", exc_info=True)
```

### 6. Dream Step 12 — Activation-Based Pruning

**File: `src/probos/cognitive/dreaming.py`** (MODIFY)

Add new dream step after Step 11 (spaced retrieval therapy):

```python
# Step 12: Activation-based memory pruning (AD-462b)
episodes_pruned = 0
activation_stats: dict[str, Any] = {}
try:
    if self._activation_tracker and self.config.activation_enabled:
        # 1. Prune old access log entries
        old_pruned = await self._activation_tracker.prune_old_accesses(
            max_age_days=self.config.activation_access_max_age_days,
        )

        # 2. Compute activation for all episodes
        all_episode_ids = [ep.id for ep in episodes]
        activations = await self._activation_tracker.compute_batch_activation(
            all_episode_ids, decay=self.config.activation_decay_d,
        )

        # 3. Identify low-activation candidates
        threshold = self.config.activation_prune_threshold
        candidates = [
            eid for eid, act in activations.items()
            if act < threshold
        ]

        # 4. Guard: never prune episodes less than 24 hours old (consolidation window)
        now = time.time()
        episode_map = {ep.id: ep for ep in episodes}
        candidates = [
            eid for eid in candidates
            if (now - episode_map.get(eid, Episode()).timestamp) > 86400
        ]

        # 5. Guard: cap pruning at 10% of total per dream cycle (avoid mass eviction)
        max_prune = max(1, len(episodes) // 10)
        candidates.sort(key=lambda eid: activations.get(eid, float("-inf")))
        to_prune = candidates[:max_prune]

        # 6. Evict via public API (handles audit trail, ChromaDB, FTS5, activation cleanup)
        if to_prune:
            episodes_pruned = await self.episodic_memory.evict_by_ids(
                to_prune,
                reason="activation_decay",
                process="dream_step_12",
            )

        activation_stats = {
            "total_computed": len(activations),
            "below_threshold": len(candidates),
            "pruned": episodes_pruned,
            "access_log_cleaned": old_pruned,
        }
        if episodes_pruned > 0:
            logger.info(
                "Step 12: Pruned %d low-activation episodes (threshold=%.2f)",
                episodes_pruned, threshold,
            )
except Exception as e:
    logger.debug("Step 12 activation pruning failed: %s", e)
```

The key: use `evict_by_ids()` public API, not direct `_collection` / `_fts_db` access (Law of Demeter).

**File: `src/probos/cognitive/episodic.py`** (MODIFY)

```python
async def evict_by_ids(self, episode_ids: list[str], reason: str = "activation_decay", process: str = "dream") -> int:
    """Evict specific episodes by ID. Used by dream activation pruning (AD-462b).

    Records to eviction audit, removes from ChromaDB + FTS5 + activation tracker.
    Returns count of successfully evicted episodes.
    """
    if not self._collection or not episode_ids:
        return 0
    evicted = 0
    for eid in episode_ids:
        try:
            # Get metadata for audit
            result = self._collection.get(ids=[eid], include=["metadatas"])
            if not result or not result["ids"]:
                continue
            meta = result["metadatas"][0] if result["metadatas"] else {}
            agent_ids_raw = meta.get("agent_ids_json", "[]")
            try:
                agent_ids = json.loads(agent_ids_raw)
                agent_id = agent_ids[0] if agent_ids else "unknown"
            except (json.JSONDecodeError, TypeError):
                agent_id = "unknown"

            # Audit
            if self._eviction_audit:
                await self._eviction_audit.record_eviction(
                    episode_id=eid,
                    agent_id=agent_id,
                    reason=reason,
                    process=process,
                    details=f"evict_by_ids batch",
                    content_hash=meta.get("content_hash", ""),
                    episode_timestamp=meta.get("timestamp", 0.0),
                )

            # Delete ChromaDB
            self._collection.delete(ids=[eid])
            # Delete FTS5
            if self._fts_db:
                await self._fts_db.execute("DELETE FROM episode_fts WHERE episode_id = ?", (eid,))
            # Delete activation
            if self._activation_tracker:
                await self._activation_tracker.delete_episode(eid)
            evicted += 1
        except Exception as exc:
            logger.debug("evict_by_ids failed for %s: %s", eid, exc)
    if self._fts_db:
        await self._fts_db.commit()
    return evicted
```

### 7. DreamReport Enrichment

**File: `src/probos/cognitive/dreaming.py`** (MODIFY)

Add to `DreamReport` dataclass:

```python
# AD-567d: Provenance + activation
episodes_pruned_activation: int = 0       # episodes removed by activation decay
activation_stats: dict[str, Any] = field(default_factory=dict)
```

Wire into the return at the end of `dream_cycle()`.

### 8. Startup Wiring

**Three startup files involved:**

**File: `src/probos/startup/cognitive_services.py`** (MODIFY — where EpisodicMemory is initialized, around line 141)

After `episodic_memory.start()` and after the eviction audit wiring (line 143–149), add:

```python
# AD-567d: Activation tracker for episodic memory lifecycle
activation_tracker = None
if episodic_memory:
    try:
        from probos.cognitive.activation_tracker import ActivationTracker
        activation_tracker = ActivationTracker(
            data_dir=data_dir,
            connection_factory=connection_factory,
        )
        await activation_tracker.start()
        episodic_memory.set_activation_tracker(activation_tracker)
    except Exception:
        logger.warning("AD-567d: Activation tracker start failed (non-fatal)", exc_info=True)
```

Then pass `activation_tracker` out through `CognitiveServicesResult`. Add `activation_tracker: Any = None` field to the `CognitiveServicesResult` dataclass in `results.py`.

**File: `src/probos/startup/dreaming.py`** (MODIFY — where DreamingEngine is constructed, around line 92)

Add `activation_tracker: Any = None` to the `init_dreaming()` function signature. Pass to DreamingEngine constructor:

```python
dreaming_engine = DreamingEngine(
    router=hebbian_router,
    trust_network=trust_network,
    episodic_memory=episodic_memory,
    config=dream_cfg,
    # ... existing params ...
    activation_tracker=activation_tracker,  # AD-567d
)
```

**File: `src/probos/cognitive/dreaming.py`** (MODIFY) — add `activation_tracker: Any = None` to `DreamingEngine.__init__()` parameter list (follows existing pattern of `procedure_store`, `records_store`, etc.) and store as `self._activation_tracker = activation_tracker`.

**File: `src/probos/startup/shutdown.py`** (MODIFY) — add `activation_tracker.close()` alongside other cleanup.

**Caller wiring:** The module that calls both `init_cognitive_services()` and `init_dreaming()` (find by grepping for these function calls) must pass `activation_tracker` from the cognitive result into `init_dreaming(activation_tracker=cognitive_result.activation_tracker)`. Follow the existing pattern for how `episodic_memory`, `knowledge_store`, `records_store`, and other cross-phase dependencies are threaded through.

### 9. Micro-Dream Reinforcement

**File: `src/probos/cognitive/dreaming.py`** (MODIFY `micro_dream()`)

Micro-dream replays recent episodes to update Hebbian weights. This replay should also reinforce activation:

```python
# In micro_dream(), after episodic_memory.recent() returns episodes:
if self._activation_tracker and episodes:
    try:
        await self._activation_tracker.record_batch_access(
            [ep.id for ep in episodes], access_type="dream_replay",
        )
    except Exception:
        logger.debug("Activation recording in micro_dream failed", exc_info=True)
```

This parallels real neuroscience — sleep replay reinforces memories, it's not just passive storage.

---

## Constraints

- **Principle compliance:** Cloud-Ready Storage (use connection_factory, not raw aiosqlite), Law of Demeter (evict_by_ids public API, not reaching into _collection), Fail Fast (log-and-degrade for all activation operations), DRY (reuse existing eviction audit patterns).
- **Episode immutability:** DO NOT add fields to the `Episode` frozen dataclass. Activation is tracked externally in SQLite, not on the episode itself. This preserves AD-541b write-once semantics.
- **EpisodeCluster mutability:** `EpisodeCluster` IS mutated (anchor_summary set after construction). Verify it's not frozen. If frozen, change to non-frozen or use `object.__setattr__`.
- **Procedure schema migration:** The `ALTER TABLE` for `source_anchors_json` must be guarded with a column-existence check (same pattern as AD-535 `_ensure_consecutive_successes_column()`).
- **Graceful degradation:** If `ActivationTracker` is None (not wired), all activation-dependent code paths skip silently. Existing FIFO eviction continues to work as fallback.
- **Consolidation window:** Never prune episodes less than 24 hours old. New episodes need at least one dream cycle to be replayed and reinforced.
- **Prune cap:** Maximum 10% of episodes per dream cycle. Prevents catastrophic mass eviction from a low threshold.
- **Access log hygiene:** `prune_old_accesses()` removes records older than 180 days during Step 12. Bounds SQLite growth.

---

## Tests

**File: `tests/test_ad567d_dream_provenance.py`** (NEW, ~30 tests)

### Provenance Composition (Section 1-3)
1. `test_summarize_cluster_anchors_shared_channel` — all episodes same channel → shared_channel populated
2. `test_summarize_cluster_anchors_mixed` — mixed channels → shared_channel empty, channels list complete
3. `test_summarize_cluster_anchors_participants_union` — participants unioned across episodes
4. `test_summarize_cluster_anchors_empty_anchors` — episodes with no anchors → empty summary
5. `test_summarize_cluster_anchors_time_span` — min/max timestamps correct
6. `test_procedure_provenance_populated` — extracted procedure has source_anchors from episodes
7. `test_procedure_provenance_serialization` — source_anchors round-trips through to_dict / from_dict
8. `test_procedure_store_schema_migration` — source_anchors_json column added on upgrade
9. `test_format_episode_blocks_includes_anchors` — episode blocks include anchor context
10. `test_convergence_report_provenance_section` — convergence report markdown includes provenance

### Activation Tracker (Section 4)
11. `test_activation_tracker_start` — creates DB and table
12. `test_record_access` — inserts access log entry
13. `test_record_batch_access` — bulk insert
14. `test_compute_activation_single_access` — returns positive finite value
15. `test_compute_activation_multiple_accesses` — higher than single (reinforcement)
16. `test_compute_activation_no_accesses` — returns -inf
17. `test_compute_batch_activation` — computes for multiple episodes efficiently
18. `test_activation_decays_with_time` — older acccess → lower activation (mock time)
19. `test_prune_old_accesses` — removes records older than max_age
20. `test_delete_episode_cleanup` — removes all access records for evicted episode

### Recall Reinforcement (Section 5)
21. `test_recall_for_agent_records_access` — recall triggers activation recording
22. `test_recall_weighted_records_access` — weighted recall triggers activation recording
23. `test_recent_for_agent_no_access_recording` — recent (fallback) does NOT record access

### Dream Step 12 (Section 6)
24. `test_dream_step_12_prunes_low_activation` — low-activation episodes evicted
25. `test_dream_step_12_skips_young_episodes` — episodes < 24h old never pruned
26. `test_dream_step_12_respects_cap` — max 10% pruned per cycle
27. `test_dream_step_12_eviction_audit` — pruned episodes recorded in eviction audit
28. `test_dream_step_12_disabled` — activation_enabled=False → step skipped
29. `test_dream_step_12_no_tracker` — no tracker wired → step skipped gracefully

### Micro-Dream Reinforcement (Section 9)
30. `test_micro_dream_records_replay_access` — micro_dream reinforces episode activation

---

## DECISIONS.md Entry

```
### AD-567d: Anchor-Preserving Dream Consolidation + Active Forgetting (2026-04-0X)

**Decision:** Deliver provenance composition (AD-559) and ACT-R activation-based memory lifecycle (AD-462b) in a single build. Dream consolidation artifacts (procedures, convergence reports, cluster summaries) carry forward source episode anchor metadata. Episode eviction upgraded from FIFO to activation-based: recalled episodes gain activation, unreinforced episodes decay, low-activation episodes pruned during dream Step 12.

**Rationale:** Provenance without lifecycle creates unbounded growth; lifecycle without provenance loses the evidence chain. Together they form a complete memory-management pipeline: anchor-grounded memories are reinforced through recall, ungroundeded memories decay, and consolidated artifacts preserve the provenance of their sources. ACT-R's base-level activation (Anderson 1983) is the standard cognitive architecture for this: B_i = ln(Σ t_j^{-d}), proven effective across 40 years of cognitive modeling. Ebbinghaus forgetting curve already proven in ProbOS via procedure lifecycle (AD-538). Episode lifecycle completes the pattern.

**Absorbs:** AD-559 (Provenance Tracking), AD-462b (Active Forgetting)
**Connects:** AD-567a (anchors), AD-567b (recall scoring), AD-567c (anchor confidence), AD-538 (procedure Ebbinghaus), AD-541f (eviction audit)
```

---

## File Change Summary

| File | Action | What |
|------|--------|------|
| `src/probos/cognitive/anchor_provenance.py` | NEW | `summarize_cluster_anchors()`, `build_procedure_provenance()` |
| `src/probos/cognitive/activation_tracker.py` | NEW | `ActivationTracker` — ACT-R activation model with SQLite access log |
| `src/probos/cognitive/episode_clustering.py` | MODIFY | Add `anchor_summary` field to `EpisodeCluster` |
| `src/probos/cognitive/procedures.py` | MODIFY | Add `source_anchors` to `Procedure`, enrich `_format_episode_blocks()` with anchor context, update `to_dict()` / `from_dict()` |
| `src/probos/cognitive/procedure_store.py` | MODIFY | Schema migration for `source_anchors_json`, serialize/deserialize |
| `src/probos/cognitive/episodic.py` | MODIFY | Add `evict_by_ids()`, `set_activation_tracker()`, record access on `recall_for_agent()` / `recall_weighted()` / `recall_for_agent_scored()`, activation cleanup on `_evict()` |
| `src/probos/cognitive/dreaming.py` | MODIFY | Step 6 anchor summary, Step 7 procedure provenance, Step 7g convergence provenance, Step 12 activation pruning, micro_dream reinforcement, DreamReport new fields, `__init__` accepts `activation_tracker` |
| `src/probos/config.py` | MODIFY | Add activation config to `DreamingConfig` (4 new fields) |
| `src/probos/startup/cognitive_services.py` | MODIFY | Create + wire `ActivationTracker` |
| `src/probos/startup/dreaming.py` | MODIFY | Accept `activation_tracker`, pass to `DreamingEngine` |
| `src/probos/startup/results.py` | MODIFY | Add `activation_tracker` to `CognitiveServicesResult` |
| `src/probos/startup/shutdown.py` | MODIFY | Close `ActivationTracker` on shutdown |
| `tests/test_ad567d_dream_provenance.py` | NEW | 30 tests |

---

## Deferred Items (Consolidated — remaining after AD-567d)

| Prompt | Absorbs | Scope | Depends |
|--------|---------|-------|---------|
| **AD-567f** | AD-567f + AD-462d | **Social Memory** — social verification protocol + cross-agent episodic search + corroboration scoring | AD-567b |
| **AD-462c** | AD-462c + AD-462e | **Recall Depth & Oracle** — trust-gated variable recall tiers + Oracle Service cross-tier retrieval | AD-567b, AD-567c |
| **AD-567g** | standalone | **Cognitive Re-Localization** — onboarding anchor-frame establishment, O'Keefe cognitive map rebuilding | AD-567c, AD-567d |
| **AD-462f** | standalone | **Optimized Memory Representation** — structured metadata + concept graphs + retrieval-as-pointers | AD-567b, AD-462c |
