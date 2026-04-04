# AD-541f: Episode Eviction Audit Trail

**Status:** Ready for builder
**Lineage:** AD-541 (Consolidation Integrity) → AD-541b (Prevention) → AD-541c (Strengthening) → AD-541d (Detection/Treatment) → AD-541e (Verification) → **AD-541f (Accountability)**
**Depends:** AD-541b (write-once guard, frozen Episode)
**Branch:** `ad-541f-eviction-audit`

---

## Context

The Memory Consolidation Integrity lineage protects episodic memory quality through
layered defenses:

| Pillar | AD | Role | Status |
|--------|----|------|--------|
| Prevention | AD-541b | Frozen Episode, write-once ChromaDB, READ-ONLY framing | Complete |
| Strengthening | AD-541c | Spaced retrieval therapy reinforces genuine traces | Complete |
| Detection/Treatment | AD-541d | Guided reminiscence classifies recall accuracy | Complete |
| Verification | AD-541e | SHA-256 content hash detects storage-layer tampering | Complete |
| **Accountability** | **AD-541f** | **Append-only eviction log enables forensic analysis** | **This AD** |

AD-541f is the **final pillar** — closing out the AD-541 series.

### The Problem

Three paths silently destroy stored episodes with zero logging:

| Path | Location | Mechanism | Volume |
|------|----------|-----------|--------|
| ChromaDB capacity eviction | `episodic.py:366` `_evict()` | Deletes oldest when count > 100,000 | Batch (excess count) |
| KnowledgeStore file eviction | `store.py:121` `_evict_episodes()` | Unlinks oldest JSON files when count > 1,000 | Batch (excess count) |
| `probos reset` (Tier 2+) | `__main__.py:856` | Wipes entire ChromaDB + episode directory | Total |

Additionally, `_force_update()` (episodic.py:355) can silently overwrite episode
content — a mutation path with no before/after record.

When an agent can't recall a past event, there's currently no way to determine
whether the episode was never stored, was evicted for capacity, was wiped by reset,
or was silently overwritten. "Why doesn't the agent remember X?" is unanswerable.

### Existing Audit Pattern to Follow

The **ACM lifecycle_transitions** table (`acm.py:72-80`) is the right model:

```sql
CREATE TABLE IF NOT EXISTS lifecycle_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason TEXT,
    initiated_by TEXT,
    timestamp TEXT NOT NULL
);
```

Append-only. Structured. Queryable. No hash-chain (episodes are independent events,
not sequential blocks — same reasoning as AD-541e's per-episode hash decision).

---

## Principles Compliance

- **SOLID (S):** `EvictionAuditLog` is a single-responsibility class — only audit records
- **SOLID (O):** New eviction reasons added by inserting rows, not changing schema
- **SOLID (D):** Uses ConnectionFactory protocol for cloud-ready storage
- **Law of Demeter:** Eviction callers call `audit_log.record_eviction()` — no internal reaching
- **Fail Fast:** Audit log failure does NOT block eviction — log-and-degrade. Eviction must succeed even if audit fails; losing the audit record is better than blocking capacity management
- **DRY:** Single `record_eviction()` method called from all eviction paths
- **Cloud-Ready:** SQLite via ConnectionFactory — commercial overlay can swap backend

---

## Deliverables

### D1 — EvictionAuditLog Class (cognitive/eviction_audit.py)

New file `src/probos/cognitive/eviction_audit.py`:

```python
class EvictionRecord:
    """A single eviction audit entry."""
    # frozen=True — immutable once created

@dataclass(frozen=True)
class EvictionRecord:
    id: str                    # UUID
    episode_id: str            # The evicted episode's ID
    agent_id: str              # Owning agent's sovereign ID (from episode metadata)
    timestamp: float           # When eviction occurred (time.time())
    reason: str                # "capacity" | "reset" | "force_update" | "manual"
    process: str               # What triggered it: "_evict", "probos_reset", "_force_update"
    details: str = ""          # Optional: batch context, e.g. "batch of 42, budget=100000"
    content_hash: str = ""     # AD-541e hash of evicted episode (if available)
    episode_timestamp: float = 0.0  # The episode's original timestamp (for forensics)
```

**Reason enum values:**
- `"capacity"` — normal capacity eviction from `_evict()` or `_evict_episodes()`
- `"reset"` — `probos reset` total wipe
- `"force_update"` — `_force_update()` overwrote content (before-state logged)
- `"manual"` — reserved for future explicit deletion commands

```python
class EvictionAuditLog:
    """Append-only audit trail for episode evictions.

    Follows the ACM lifecycle_transitions pattern (acm.py:72).
    """

    def __init__(self, connection_factory: ConnectionFactory | None = None):
        self._connection_factory = connection_factory or default_factory
        self._db: DatabaseConnection | None = None

    async def start(self, db_path: str = "eviction_audit.db") -> None:
        """Initialize DB connection and create schema."""

    async def stop(self) -> None:
        """Close DB connection."""

    async def record_eviction(
        self,
        episode_id: str,
        agent_id: str,
        reason: str,
        process: str,
        *,
        details: str = "",
        content_hash: str = "",
        episode_timestamp: float = 0.0,
    ) -> None:
        """Record a single eviction event. Append-only INSERT.

        Failure is caught and logged as WARNING — never blocks the
        eviction itself.
        """

    async def record_batch_eviction(
        self,
        records: list[dict],
        reason: str,
        process: str,
        *,
        details: str = "",
    ) -> None:
        """Record multiple evictions in a single transaction.

        Each dict in records must have: episode_id, agent_id.
        Optional: content_hash, episode_timestamp.

        Uses executemany() for efficiency on large batches.
        """

    async def query_by_agent(
        self, agent_id: str, *, limit: int = 50
    ) -> list[EvictionRecord]:
        """Get eviction history for a specific agent. Newest first."""

    async def query_by_episode(
        self, episode_id: str
    ) -> EvictionRecord | None:
        """Look up whether a specific episode was evicted."""

    async def query_recent(
        self, *, limit: int = 100
    ) -> list[EvictionRecord]:
        """Get most recent evictions across all agents."""

    async def count_by_reason(self) -> dict[str, int]:
        """Aggregate eviction counts by reason. For SIF/VitalsMonitor."""

    async def count_by_agent(self, agent_id: str) -> int:
        """Total evictions for an agent."""
```

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS eviction_audit (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    reason TEXT NOT NULL,
    process TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    episode_timestamp REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_eviction_agent
    ON eviction_audit(agent_id);

CREATE INDEX IF NOT EXISTS idx_eviction_episode
    ON eviction_audit(episode_id);

CREATE INDEX IF NOT EXISTS idx_eviction_timestamp
    ON eviction_audit(timestamp);
```

**Append-only enforcement:** No `UPDATE` or `DELETE` methods on EvictionAuditLog.
The table is write-once-read-many. The `probos reset` Tier 2+ wipe can delete the
audit DB file itself (fresh start), but within a running instance the table only grows.

### D2 — Wire into `_evict()` (episodic.py)

Modify `EpisodicMemory._evict()` (line 366) to log evictions:

```python
async def _evict(self) -> None:
    count = self._collection.count()
    if count <= self.max_episodes:
        return
    excess = count - self.max_episodes

    # Get episodes to evict (oldest first)
    result = self._collection.get(
        include=["metadatas"],
        limit=count,
    )
    # ... existing sort by timestamp ...

    ids_to_delete = [...]  # existing logic

    # AD-541f: Record evictions before deletion
    if self._eviction_audit:
        records = []
        for eid in ids_to_delete:
            meta = ...  # metadata for this episode from the get() result
            records.append({
                "episode_id": eid,
                "agent_id": meta.get("agent_ids_json", "[]"),  # parse first agent
                "content_hash": meta.get("content_hash", ""),
                "episode_timestamp": meta.get("timestamp", 0.0),
            })
        try:
            await self._eviction_audit.record_batch_eviction(
                records,
                reason="capacity",
                process="_evict",
                details=f"batch of {len(ids_to_delete)}, budget={self.max_episodes}",
            )
        except Exception as exc:
            logger.warning("Eviction audit failed: %s", exc)

    self._collection.delete(ids=ids_to_delete)
```

**Key:** The `agent_id` in the metadata is stored as JSON array (`agent_ids_json`).
Parse the first element. If unparseable, use `"unknown"`.

**Constructor change:** `EpisodicMemory.__init__()` accepts an optional
`eviction_audit: EvictionAuditLog | None = None` parameter. Stored as
`self._eviction_audit`.

### D3 — Wire into `_force_update()` (episodic.py)

Modify `_force_update()` (line 355) to log overwrites:

```python
def _force_update(self, episode: Episode) -> None:
    """Bypass write-once for migration only."""
    # AD-541f: Log the overwrite
    if self._eviction_audit:
        import json as _json
        agent_id = episode.agent_ids[0] if episode.agent_ids else "unknown"
        try:
            # Fire-and-forget since _force_update is sync
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._eviction_audit.record_eviction(
                    episode_id=episode.id,
                    agent_id=agent_id,
                    reason="force_update",
                    process="_force_update",
                    details="migration overwrite",
                    content_hash=episode.id,  # pre-overwrite hash not available
                    episode_timestamp=episode.timestamp,
                ))
        except Exception:
            pass  # Best-effort audit for sync path

    self._collection.upsert(
        ids=[episode.id],
        documents=[...],
        metadatas=[self._episode_to_metadata(episode)],
    )
```

**Note:** `_force_update()` is synchronous. The audit call uses `create_task()`
for fire-and-forget async recording. If no event loop is running (test context),
silently skip. This is best-effort — the overwrite must succeed regardless.

### D4 — Wire into KnowledgeStore `_evict_episodes()` (store.py)

Modify `KnowledgeStore._evict_episodes()` (line 121) to log evictions:

```python
async def _evict_episodes(self) -> None:
    episode_dir = self._root / "episodes"
    if not episode_dir.exists():
        return
    files = sorted(episode_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
    excess = len(files) - self._config.max_episodes
    if excess <= 0:
        return

    to_delete = files[:excess]

    # AD-541f: Record evictions before deletion
    if self._eviction_audit:
        import json as _json
        records = []
        for fp in to_delete:
            try:
                data = _json.loads(fp.read_text())
                records.append({
                    "episode_id": fp.stem,
                    "agent_id": data.get("agent_ids", ["unknown"])[0],
                    "episode_timestamp": data.get("timestamp", 0.0),
                })
            except Exception:
                records.append({
                    "episode_id": fp.stem,
                    "agent_id": "unknown",
                })
        try:
            await self._eviction_audit.record_batch_eviction(
                records,
                reason="capacity",
                process="_evict_episodes",
                details=f"batch of {len(to_delete)}, budget={self._config.max_episodes}",
            )
        except Exception as exc:
            logger.warning("Eviction audit failed: %s", exc)

    for fp in to_delete:
        fp.unlink(missing_ok=True)
```

**Constructor change:** `KnowledgeStore.__init__()` accepts an optional
`eviction_audit: EvictionAuditLog | None = None` parameter.

### D5 — Wire into `probos reset` (__main__.py)

In the Tier 2+ reset path (line 856 area), before deleting ChromaDB files:

```python
# AD-541f: Record reset eviction (summary record, not per-episode)
if eviction_audit:
    try:
        await eviction_audit.record_eviction(
            episode_id="*",  # wildcard — total wipe
            agent_id="*",
            reason="reset",
            process="probos_reset",
            details=f"Tier 2 reset — total episodic memory wipe",
        )
    except Exception:
        pass  # Best-effort — reset must proceed
```

**Note:** For `probos reset`, we do NOT enumerate every episode. The reset path
already destroys the ChromaDB database file — we can't query it for episode IDs.
A single summary record with `episode_id="*"` is sufficient. The audit DB itself
is separate and survives reset (unless the user explicitly deletes it).

**Decision: Audit DB survives reset.** The `eviction_audit.db` file should NOT be
included in the reset cleanup list. This preserves the forensic trail across resets.
The identity ledger DB also survives Tier 2 reset (ship identity persists). Follow
the same pattern.

### D6 — SIF Integration (sif.py)

Add a new SIF check: `check_eviction_health()`. This is lightweight — doesn't
sample episodes, just queries the audit log.

```python
def check_eviction_health(self) -> SIFCheckResult:
    """AD-541f: Monitor eviction patterns for anomalies."""
    if self._eviction_audit is None:
        return SIFCheckResult(
            name="eviction_health", passed=True, details="not configured"
        )
    issues: list[str] = []
    try:
        counts = await self._eviction_audit.count_by_reason()
        total = sum(counts.values())
        # No threshold checks in AD-541f — just expose the data.
        # AD-566c drift pipeline can add threshold alerts.
    except Exception as exc:
        issues.append(f"Eviction audit query failed: {exc}")

    return SIFCheckResult(
        name="eviction_health",
        passed=len(issues) == 0,
        details=f"total_evictions={total}" if not issues else "; ".join(issues),
    )
```

**Wire into SIF:** Add `self._eviction_audit` parameter to `StructuralIntegrityField`
constructor. Add `self.check_eviction_health` to the `check_fn` list in
`run_all_checks()`.

**Note:** `check_eviction_health()` needs to be async because it queries SQLite.
SIF's `run_all_checks()` runs checks via a list — verify whether the existing
pattern supports async check functions. If all checks are currently sync, wrap
the audit query with `asyncio.get_event_loop().run_until_complete()` or make the
check pattern support both sync and async. Follow whatever pattern exists.

### D7 — Configuration (config.py)

Add to `MemoryConfig`:

```python
eviction_audit_enabled: bool = True
```

This gates whether eviction audit records are created. When `False`, eviction
operates silently as before (backwards-compatible default behavior for instances
that don't want audit overhead).

### D8 — Startup Wiring (startup/cognitive_services.py, startup/shutdown.py)

In cognitive_services.py:

```python
# AD-541f: Eviction Audit Log
from probos.cognitive.eviction_audit import EvictionAuditLog

eviction_audit = None
if rt.config.memory.eviction_audit_enabled:
    eviction_audit = EvictionAuditLog(connection_factory=connection_factory)
    await eviction_audit.start(db_path=str(data_dir / "eviction_audit.db"))
    rt._eviction_audit = eviction_audit

# Pass to EpisodicMemory (modify existing construction)
# episodic_memory = EpisodicMemory(..., eviction_audit=eviction_audit)

# Pass to SIF (modify existing construction if SIF is created here)
```

In shutdown.py:

```python
# AD-541f: Eviction Audit Log
eviction_audit = getattr(rt, "_eviction_audit", None)
if eviction_audit is not None:
    await eviction_audit.stop()
```

---

## Test Spec

**New file:** `tests/test_ad541f_eviction_audit.py`

### D1 — EvictionAuditLog Core (6 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_record_eviction_persists` | Record an eviction, query_by_episode returns it with matching fields |
| 2 | `test_record_batch_eviction` | Record 5 evictions in one call, query_recent returns all 5 |
| 3 | `test_query_by_agent` | Record evictions for 2 agents, query_by_agent returns only matching agent's records |
| 4 | `test_query_by_episode_not_found` | Query non-existent episode_id → returns None |
| 5 | `test_count_by_reason` | Record capacity + reset + force_update → counts match each reason |
| 6 | `test_eviction_record_frozen` | EvictionRecord is frozen — cannot mutate |

### D2 — EpisodicMemory `_evict()` Integration (3 tests)

| # | Test | Asserts |
|---|------|---------|
| 7 | `test_evict_logs_to_audit` | Store episodes over budget, trigger eviction → audit records created for evicted episodes |
| 8 | `test_evict_succeeds_when_audit_fails` | Audit log raises exception → eviction still succeeds (log-and-degrade) |
| 9 | `test_evict_captures_metadata` | Evicted episode audit record contains content_hash and episode_timestamp from metadata |

### D3 — `_force_update()` Integration (1 test)

| # | Test | Asserts |
|---|------|---------|
| 10 | `test_force_update_logs_overwrite` | Call `_force_update()` → audit record with reason="force_update" |

### D4 — KnowledgeStore Integration (2 tests)

| # | Test | Asserts |
|---|------|---------|
| 11 | `test_knowledge_store_evict_logs` | Store episodes over budget → audit records created |
| 12 | `test_knowledge_store_evict_survives_audit_failure` | Audit failure → eviction still proceeds |

### D5 — Reset Integration (1 test)

| # | Test | Asserts |
|---|------|---------|
| 13 | `test_reset_logs_wildcard_eviction` | Simulate reset eviction recording → record with episode_id="*", reason="reset" |

### D6 — SIF Integration (2 tests)

| # | Test | Asserts |
|---|------|---------|
| 14 | `test_sif_eviction_health_passes` | Empty audit log → SIF passes |
| 15 | `test_sif_eviction_health_reports_total` | Records in audit → details contains "total_evictions=N" |

### D7 — Config (1 test)

| # | Test | Asserts |
|---|------|---------|
| 16 | `test_eviction_audit_disabled` | `eviction_audit_enabled=False` → no audit records created on eviction |

**Total: 16 tests** in 1 new test file.

---

## Files to Modify

| File | Action | Changes |
|------|--------|---------|
| `src/probos/cognitive/eviction_audit.py` | **Create** | D1: EvictionRecord, EvictionAuditLog |
| `src/probos/cognitive/episodic.py` | Edit | D2: `_evict()` audit logging, D3: `_force_update()` audit logging, constructor `eviction_audit` param |
| `src/probos/knowledge/store.py` | Edit | D4: `_evict_episodes()` audit logging, constructor `eviction_audit` param |
| `src/probos/__main__.py` | Edit | D5: Reset audit record |
| `src/probos/sif.py` | Edit | D6: `check_eviction_health()` + constructor param + check list |
| `src/probos/config.py` | Edit | D7: `MemoryConfig.eviction_audit_enabled` |
| `src/probos/startup/cognitive_services.py` | Edit | D8: Startup wiring |
| `src/probos/startup/shutdown.py` | Edit | D8: Shutdown |
| `tests/test_ad541f_eviction_audit.py` | **Create** | 16 tests |

**9 files** (2 new, 7 edits). No dataclass changes to Episode. No migration.
No new dependencies.

---

## Scope Exclusions

| Excluded | Reason | Future |
|----------|--------|--------|
| Per-episode audit for `probos reset` | Reset destroys ChromaDB before querying — can't enumerate | N/A (wildcard record sufficient) |
| Eviction threshold alerts (e.g., "too many evictions per hour") | AD-566c drift pipeline | AD-566c |
| Composite `memory_integrity_score` aggregation | Requires ALL 541a-f pillars + aggregation logic | Post-541f AD |
| Counselor integration (eviction → wellness concern) | Counselor subscribes to events in AD-566c | AD-566c |
| Audit log compaction / rotation | Append-only log will grow — address when it matters | Future BF |
| Hash-chain linking audit records | Records are independent events, not sequential | N/A |
| CognitiveJournal / EventLog prune audit | Different subsystem, same gap — separate BF | Future BF |

---

## Builder Instructions

1. Read existing patterns: `acm.py:72-80` (lifecycle_transitions schema),
   `storage/sqlite_factory.py` (ConnectionFactory), `identity.py:753`
   (append-only ledger pattern)
2. Create `cognitive/eviction_audit.py` — single file for EvictionRecord +
   EvictionAuditLog
3. **Append-only:** No `UPDATE` or `DELETE` SQL in EvictionAuditLog. The only
   mutation is `INSERT`.
4. **Log-and-degrade:** Audit failures MUST NOT block eviction. Wrap every audit
   call in try/except. Eviction succeeding > audit record surviving.
5. **`_force_update()` is sync** — use `asyncio.create_task()` for fire-and-forget
   or make audit call sync (direct SQLite execute without await). Choose whichever
   is cleaner. If unsure, use sync SQLite call since `_force_update()` is rarely
   called.
6. **SIF check may need async support** — check whether `run_all_checks()` already
   handles async check functions. If not, make `check_eviction_health()` sync with
   a cached count (set by the audit log after each write) rather than querying SQLite
   in the SIF loop.
7. **Audit DB survives reset** — do NOT add `eviction_audit.db` to the reset
   cleanup file list.
8. Run: `python -m pytest tests/test_ad541f_eviction_audit.py -x -v`
9. Run: `python -m pytest tests/test_ad541e_content_hashing.py tests/test_ad541b_reconsolidation.py -x -q` (regression)
10. Run: `python -m pytest tests/ -k "sif or evict" -x -q` (SIF + eviction regression)
11. Update tracking files: `PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md`
    — mark AD-541f complete and note that the full AD-541 lineage (6 pillars) is now CLOSED.
