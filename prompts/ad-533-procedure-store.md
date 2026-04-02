# AD-533: Procedure Store (Hybrid Persistence — Ship's Records + SQLite Index)

**Context:** AD-532 (CLOSED) extracts `Procedure` objects from success-dominant episode clusters during dream consolidation. Currently these procedures live only in memory (`DreamingEngine._last_procedures`) and are discarded when the dream cycle ends. AD-533 persists them so AD-534 (Replay-First Dispatch) can query and replay procedures across sessions.

**Problem:** Dream cycles invest LLM tokens extracting procedures, but the results vanish at restart. AD-534 needs a persistent, queryable procedure store with semantic search (match incoming intents to stored procedures), version lineage (DAG for FIX/DERIVED evolution, AD-532b), and quality metrics (track procedure effectiveness over time).

**Scope:** This AD covers:
- **Hybrid storage** — Ship's Records (Git-backed YAML, authoritative) + SQLite index (fast queries, DAG, metrics).
- **Semantic index** — ChromaDB collection for embedding-based matching of procedure names + preconditions.
- **Quality metrics schema** — Four atomic counters per procedure in SQLite (consumed by AD-534).
- **Version DAG schema** — `procedure_records` + `procedure_lineage_parents` tables (consumed by AD-532b).
- **Dream cycle integration** — `DreamingEngine` persists procedures immediately after extraction.
- **Cross-session cluster dedup** — Persistent `origin_cluster_id` lookup replaces in-memory set.
- **Procedure dataclass extension** — Add fields needed by the store (backward-compatible defaults).

**Deferred (consumed by later ADs):**
- AD-532b: FIX/DERIVED evolution *logic* (AD-533 provides the schema and DAG traversal)
- AD-534: Replay dispatch *queries* (AD-533 provides `find_matching()` and quality metric reads)
- AD-532c: Negative procedure *population* (AD-533 creates the anti-pattern directory and `is_negative` field)

**Dependencies (all COMPLETE):**
- AD-532 ✅ — `Procedure`/`ProcedureStep` in `src/probos/cognitive/procedures.py`
- AD-434 ✅ — `RecordsStore` in `src/probos/knowledge/records_store.py`
- AD-542 ✅ — `ConnectionFactory`/`DatabaseConnection` protocols in `src/probos/protocols.py`, `SQLiteConnectionFactory` in `src/probos/storage/sqlite_factory.py`

**Principles:** SOLID (ProcedureStore = single responsibility — persistence), DRY (reuse RecordsStore for Git writes, ConnectionFactory for SQLite, existing embedding infra), Law of Demeter (store exposes clean query API, callers don't touch SQLite/Git internals), Fail Fast (log-and-degrade — store failures don't break dream cycles), Cloud-Ready Storage (ConnectionFactory injection, never direct `aiosqlite.connect()`), Defense in Depth (validate at store boundary before persisting).

---

## Part 0: Extend `Procedure` Dataclass

### File: `src/probos/cognitive/procedures.py`

Add fields to `Procedure` needed by the store and future ADs. All have defaults — fully backward-compatible with existing AD-532 tests.

**Add these fields** after `failure_count` (currently line 186):

```python
    # AD-533: Store and evolution support
    is_active: bool = True  # False when superseded by FIX (AD-532b)
    generation: int = 0  # distance from root in version DAG (AD-532b)
    parent_procedure_ids: list[str] = field(default_factory=list)  # FIX/DERIVED parents (AD-532b)
    is_negative: bool = False  # anti-pattern flag (AD-532c)
    superseded_by: str = ""  # ID of procedure that replaced this one (AD-532b)
    tags: list[str] = field(default_factory=list)  # domain, agent_type, etc.
```

**Update `to_dict()`** to include the new fields:

```python
    "is_active": self.is_active,
    "generation": self.generation,
    "parent_procedure_ids": self.parent_procedure_ids,
    "is_negative": self.is_negative,
    "superseded_by": self.superseded_by,
    "tags": self.tags,
```

**Add a `from_dict()` classmethod** to reconstruct from persisted YAML/JSON:

```python
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Procedure":
        """Reconstruct a Procedure from a serialized dict."""
        steps = [ProcedureStep(**s) for s in data.get("steps", [])]
        return cls(
            id=data.get("id", uuid.uuid4().hex),
            name=data.get("name", ""),
            description=data.get("description", ""),
            steps=steps,
            preconditions=data.get("preconditions", []),
            postconditions=data.get("postconditions", []),
            intent_types=data.get("intent_types", []),
            origin_cluster_id=data.get("origin_cluster_id", ""),
            origin_agent_ids=data.get("origin_agent_ids", []),
            provenance=data.get("provenance", []),
            extraction_date=data.get("extraction_date", 0.0),
            evolution_type=data.get("evolution_type", "CAPTURED"),
            compilation_level=data.get("compilation_level", 1),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            is_active=data.get("is_active", True),
            generation=data.get("generation", 0),
            parent_procedure_ids=data.get("parent_procedure_ids", []),
            is_negative=data.get("is_negative", False),
            superseded_by=data.get("superseded_by", ""),
            tags=data.get("tags", []),
        )
```

### Tests (~5 tests)

- `test_procedure_new_fields_defaults` — new fields have correct defaults (`is_active=True`, `generation=0`, etc.)
- `test_procedure_to_dict_includes_new_fields` — all 6 new fields present in `to_dict()` output
- `test_procedure_from_dict_roundtrip` — `Procedure.from_dict(p.to_dict())` produces equivalent object
- `test_procedure_from_dict_missing_fields_uses_defaults` — partial dict reconstructs with safe defaults
- `test_procedure_from_dict_with_steps` — nested ProcedureStep objects reconstructed correctly

---

## Part 1: `ProcedureStore` — Core Class Structure

### New file: `src/probos/cognitive/procedure_store.py`

Create the store module. Follow the `CounselorProfileStore` pattern for lifecycle and the `EpisodicMemory` pattern for ChromaDB.

```python
"""AD-533: Procedure Store — hybrid persistence for compiled procedures.

Authoritative storage: Ship's Records (Git-backed YAML) in records/procedures/.
Fast query index: SQLite (DAG traversal, quality metrics, filtering).
Semantic index: ChromaDB collection for intent-to-procedure matching.

Consumed by:
- AD-534: Replay-First Dispatch (find_matching, quality metric reads)
- AD-532b: Procedure Evolution (DAG traversal, FIX/DERIVED writes)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)
```

**Class definition:**

```python
class ProcedureStore:
    """Hybrid procedure persistence — Ship's Records + SQLite index + ChromaDB."""

    def __init__(
        self,
        data_dir: str | Path,
        records_store: Any = None,  # RecordsStore (AD-434)
        connection_factory: "ConnectionFactory | None" = None,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._records_store = records_store
        self._db: DatabaseConnection | None = None
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
        self._write_lock = threading.Lock()
        self._chroma_collection: Any = None

    async def start(self) -> None:
        """Initialize SQLite index and ChromaDB collection."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        # SQLite
        db_path = str(self._data_dir / "procedures.db")
        self._db = await self._connection_factory.connect(db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        # ChromaDB
        self._init_chroma()

    async def stop(self) -> None:
        """Close database connections."""
        if self._db:
            await self._db.close()
            self._db = None
```

**ChromaDB initialization** — follow EpisodicMemory pattern:

```python
    def _init_chroma(self) -> None:
        """Initialize ChromaDB collection for semantic procedure search."""
        try:
            import chromadb
            from probos.knowledge.embeddings import get_embedding_function

            client = chromadb.PersistentClient(
                path=str(self._data_dir / "chroma")
            )
            ef = get_embedding_function()
            self._chroma_collection = client.get_or_create_collection(
                name="procedures",
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            logger.warning(
                "ChromaDB unavailable for procedure semantic index: %s", e
            )
            self._chroma_collection = None
```

### Tests (~4 tests)

- `test_procedure_store_init_accepts_connection_factory` — custom factory injected and used
- `test_procedure_store_start_creates_db` — `start()` creates `procedures.db` in data_dir
- `test_procedure_store_start_creates_schema` — tables exist after start (`procedure_records`, `procedure_lineage_parents`)
- `test_procedure_store_stop_closes_db` — `stop()` closes connection cleanly

---

## Part 2: SQLite Schema

### File: `src/probos/cognitive/procedure_store.py`

Define the schema as a module-level constant (follow `CounselorProfileStore` pattern):

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS procedure_records (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    origin_cluster_id TEXT NOT NULL DEFAULT '',
    evolution_type TEXT NOT NULL DEFAULT 'CAPTURED',
    compilation_level INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_negative INTEGER NOT NULL DEFAULT 0,
    generation INTEGER NOT NULL DEFAULT 0,
    superseded_by TEXT NOT NULL DEFAULT '',
    content_snapshot TEXT NOT NULL DEFAULT '{}',  -- full Procedure.to_dict() as JSON
    content_diff TEXT NOT NULL DEFAULT '',  -- unified diff for FIX/DERIVED (AD-532b)
    change_summary TEXT NOT NULL DEFAULT '',  -- human-readable summary (AD-532b)
    intent_types TEXT NOT NULL DEFAULT '[]',  -- JSON array
    tags TEXT NOT NULL DEFAULT '[]',  -- JSON array
    origin_agent_ids TEXT NOT NULL DEFAULT '[]',  -- JSON array
    extraction_date REAL NOT NULL DEFAULT 0.0,
    created_at REAL NOT NULL DEFAULT 0.0,
    updated_at REAL NOT NULL DEFAULT 0.0,

    -- Quality metrics (AD-534 updates these)
    total_selections INTEGER NOT NULL DEFAULT 0,
    total_applied INTEGER NOT NULL DEFAULT 0,
    total_completions INTEGER NOT NULL DEFAULT 0,
    total_fallbacks INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS procedure_lineage_parents (
    procedure_id TEXT NOT NULL,
    parent_procedure_id TEXT NOT NULL,
    PRIMARY KEY (procedure_id, parent_procedure_id),
    FOREIGN KEY (procedure_id) REFERENCES procedure_records(id),
    FOREIGN KEY (parent_procedure_id) REFERENCES procedure_records(id)
);

CREATE INDEX IF NOT EXISTS idx_procedure_active ON procedure_records(is_active);
CREATE INDEX IF NOT EXISTS idx_procedure_evolution ON procedure_records(evolution_type);
CREATE INDEX IF NOT EXISTS idx_procedure_cluster ON procedure_records(origin_cluster_id);
CREATE INDEX IF NOT EXISTS idx_procedure_negative ON procedure_records(is_negative);
"""
```

### Tests (~3 tests)

- `test_schema_creates_procedure_records_table` — verify columns exist via `PRAGMA table_info`
- `test_schema_creates_lineage_table` — verify `procedure_lineage_parents` table and composite PK
- `test_schema_creates_indexes` — verify the 4 indexes exist via `PRAGMA index_list`

---

## Part 3: Core CRUD Operations

### File: `src/probos/cognitive/procedure_store.py`

**`save()`** — Persist a Procedure to all three backends:

```python
    async def save(self, procedure: "Procedure") -> str:
        """Persist a procedure to Ship's Records, SQLite index, and ChromaDB.

        Returns the procedure ID.
        """
        from probos.cognitive.procedures import Procedure

        if not isinstance(procedure, Procedure):
            raise TypeError(f"Expected Procedure, got {type(procedure).__name__}")

        now = time.time()

        # 1. SQLite index
        await self._save_to_index(procedure, now)

        # 2. Ship's Records (Git-backed YAML) — best-effort
        await self._save_to_records(procedure)

        # 3. ChromaDB semantic index — best-effort
        self._save_to_chroma(procedure)

        return procedure.id
```

**`_save_to_index()`** — SQLite insert:

```python
    async def _save_to_index(
        self, procedure: "Procedure", now: float
    ) -> None:
        """Insert or replace procedure in SQLite index."""
        if not self._db:
            return
        content_snapshot = json.dumps(procedure.to_dict(), default=str)
        await self._db.execute(
            """INSERT OR REPLACE INTO procedure_records
            (id, name, description, origin_cluster_id, evolution_type,
             compilation_level, is_active, is_negative, generation,
             superseded_by, content_snapshot, intent_types, tags,
             origin_agent_ids, extraction_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                procedure.id,
                procedure.name,
                procedure.description,
                procedure.origin_cluster_id,
                procedure.evolution_type,
                procedure.compilation_level,
                1 if procedure.is_active else 0,
                1 if procedure.is_negative else 0,
                procedure.generation,
                procedure.superseded_by,
                content_snapshot,
                json.dumps(procedure.intent_types),
                json.dumps(procedure.tags),
                json.dumps(procedure.origin_agent_ids),
                procedure.extraction_date,
                now,
                now,
            ),
        )
        # Insert lineage edges
        for parent_id in procedure.parent_procedure_ids:
            await self._db.execute(
                """INSERT OR IGNORE INTO procedure_lineage_parents
                (procedure_id, parent_procedure_id) VALUES (?, ?)""",
                (procedure.id, parent_id),
            )
        await self._db.commit()
```

**`_save_to_records()`** — Ship's Records YAML:

```python
    async def _save_to_records(self, procedure: "Procedure") -> None:
        """Write procedure as YAML document to Ship's Records."""
        if not self._records_store:
            return
        try:
            import yaml

            subdir = "anti-patterns" if procedure.is_negative else ""
            path = f"procedures/{subdir}/{procedure.id}.yaml" if subdir else f"procedures/{procedure.id}.yaml"
            content = yaml.dump(
                procedure.to_dict(),
                default_flow_style=False,
                sort_keys=False,
            )
            await self._records_store.write_entry(
                author="system",
                path=path,
                content=content,
                message=f"Procedure {procedure.evolution_type}: {procedure.name}",
                classification="ship",
                topic="procedures",
                tags=procedure.intent_types + procedure.tags,
            )
        except Exception as e:
            logger.debug("Failed to write procedure to Ship's Records: %s", e)
```

**`_save_to_chroma()`** — Semantic index:

```python
    def _save_to_chroma(self, procedure: "Procedure") -> None:
        """Add/update procedure in ChromaDB semantic index."""
        if not self._chroma_collection:
            return
        try:
            # Combine name + description + preconditions for embedding
            text = f"{procedure.name}. {procedure.description}. Preconditions: {', '.join(procedure.preconditions)}"
            self._chroma_collection.upsert(
                ids=[procedure.id],
                documents=[text],
                metadatas=[{
                    "evolution_type": procedure.evolution_type,
                    "is_active": procedure.is_active,
                    "is_negative": procedure.is_negative,
                    "compilation_level": procedure.compilation_level,
                    "intent_types": json.dumps(procedure.intent_types),
                }],
            )
        except Exception as e:
            logger.debug("Failed to index procedure in ChromaDB: %s", e)
```

**`get()`** — Load a single procedure by ID:

```python
    async def get(self, procedure_id: str) -> "Procedure | None":
        """Load a procedure from SQLite index by ID."""
        if not self._db:
            return None
        from probos.cognitive.procedures import Procedure

        await self._db.execute(
            "SELECT content_snapshot FROM procedure_records WHERE id = ?",
            (procedure_id,),
        )
        row = await self._db.fetchone()
        if not row:
            return None
        try:
            data = json.loads(row[0])
            return Procedure.from_dict(data)
        except Exception as e:
            logger.debug("Failed to deserialize procedure %s: %s", procedure_id, e)
            return None
```

**`list_active()`** — List all active procedures with optional filters:

```python
    async def list_active(
        self,
        *,
        evolution_type: str = "",
        intent_type: str = "",
        is_negative: bool = False,
        min_compilation_level: int = 0,
    ) -> list[dict[str, Any]]:
        """List active procedures from SQLite index.

        Returns lightweight dicts (id, name, evolution_type, compilation_level,
        intent_types, quality metrics) — NOT full Procedure objects.
        """
        if not self._db:
            return []
        conditions = ["is_active = 1", f"is_negative = {1 if is_negative else 0}"]
        params: list[Any] = []
        if evolution_type:
            conditions.append("evolution_type = ?")
            params.append(evolution_type)
        if min_compilation_level > 0:
            conditions.append("compilation_level >= ?")
            params.append(min_compilation_level)
        where = " AND ".join(conditions)
        await self._db.execute(
            f"""SELECT id, name, evolution_type, compilation_level,
                intent_types, total_selections, total_applied,
                total_completions, total_fallbacks
            FROM procedure_records WHERE {where}
            ORDER BY total_completions DESC""",
            tuple(params),
        )
        rows = await self._db.fetchall()
        results = []
        for row in rows:
            entry = {
                "id": row[0],
                "name": row[1],
                "evolution_type": row[2],
                "compilation_level": row[3],
                "intent_types": json.loads(row[4]) if row[4] else [],
                "total_selections": row[5],
                "total_applied": row[6],
                "total_completions": row[7],
                "total_fallbacks": row[8],
            }
            # Filter by intent_type in application layer (JSON array in SQLite)
            if intent_type and intent_type not in entry["intent_types"]:
                continue
            results.append(entry)
        return results
```

**`has_cluster()`** — Cross-session dedup check:

```python
    async def has_cluster(self, cluster_id: str) -> bool:
        """Check if a procedure already exists for this origin cluster ID."""
        if not self._db:
            return False
        await self._db.execute(
            "SELECT 1 FROM procedure_records WHERE origin_cluster_id = ? LIMIT 1",
            (cluster_id,),
        )
        row = await self._db.fetchone()
        return row is not None
```

**`delete()`** — Remove a procedure (all three backends):

```python
    async def delete(self, procedure_id: str) -> bool:
        """Remove a procedure from all backends. Returns True if found."""
        if not self._db:
            return False
        # Check existence
        await self._db.execute(
            "SELECT 1 FROM procedure_records WHERE id = ?", (procedure_id,)
        )
        if not await self._db.fetchone():
            return False
        # SQLite
        await self._db.execute(
            "DELETE FROM procedure_lineage_parents WHERE procedure_id = ? OR parent_procedure_id = ?",
            (procedure_id, procedure_id),
        )
        await self._db.execute(
            "DELETE FROM procedure_records WHERE id = ?", (procedure_id,)
        )
        await self._db.commit()
        # ChromaDB
        if self._chroma_collection:
            try:
                self._chroma_collection.delete(ids=[procedure_id])
            except Exception:
                pass
        return True
```

### Tests (~12 tests)

- `test_save_procedure_returns_id` — `save()` returns the procedure ID
- `test_save_procedure_persists_to_sqlite` — procedure retrievable via `get()` after save
- `test_save_procedure_writes_to_records` — `records_store.write_entry` called with correct path
- `test_save_procedure_indexes_in_chroma` — `chroma_collection.upsert` called
- `test_save_negative_procedure_uses_anti_patterns_path` — path includes `anti-patterns/`
- `test_get_procedure_returns_procedure_object` — `get()` returns a `Procedure` with correct fields
- `test_get_procedure_not_found_returns_none` — unknown ID returns None
- `test_list_active_returns_active_only` — deactivated procedures excluded
- `test_list_active_filters_by_evolution_type` — filter works
- `test_list_active_filters_by_intent_type` — intent matching works
- `test_has_cluster_returns_true_for_existing` — dedup check positive
- `test_has_cluster_returns_false_for_missing` — dedup check negative
- `test_delete_removes_from_all_backends` — SQLite row gone, chroma delete called

---

## Part 4: Semantic Search (AD-534 Foundation)

### File: `src/probos/cognitive/procedure_store.py`

**`find_matching()`** — Semantic search for procedures matching an intent/context:

```python
    async def find_matching(
        self,
        query: str,
        *,
        n_results: int = 5,
        min_compilation_level: int = 0,
        exclude_negative: bool = True,
    ) -> list[dict[str, Any]]:
        """Find procedures semantically matching a query string.

        Returns list of dicts with 'id', 'name', 'score', 'compilation_level',
        'intent_types', and quality metrics. Sorted by relevance (highest first).

        Used by AD-534 Replay-First Dispatch to match incoming intents to
        stored procedures.
        """
        if not self._chroma_collection:
            return []

        try:
            where_filter: dict[str, Any] = {"is_active": True}
            if exclude_negative:
                where_filter["is_negative"] = False
            if min_compilation_level > 0:
                where_filter["compilation_level"] = {"$gte": min_compilation_level}

            results = self._chroma_collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_filter if len(where_filter) > 1 else {"is_active": True},
            )

            if not results or not results.get("ids") or not results["ids"][0]:
                return []

            matched = []
            for i, proc_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i] if results.get("distances") else 1.0
                score = max(0.0, 1.0 - distance)  # cosine distance → similarity
                matched.append({
                    "id": proc_id,
                    "score": score,
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                })

            # Enrich with SQLite data (quality metrics, name, compilation_level)
            enriched = []
            for match in matched:
                proc_data = await self._get_index_row(match["id"])
                if proc_data:
                    proc_data["score"] = match["score"]
                    enriched.append(proc_data)

            enriched.sort(key=lambda x: x["score"], reverse=True)
            return enriched

        except Exception as e:
            logger.debug("Semantic procedure search failed: %s", e)
            return []
```

**`_get_index_row()`** — Helper to load lightweight metadata from SQLite:

```python
    async def _get_index_row(self, procedure_id: str) -> dict[str, Any] | None:
        """Load procedure metadata from SQLite index (no full content)."""
        if not self._db:
            return None
        await self._db.execute(
            """SELECT id, name, evolution_type, compilation_level,
                intent_types, total_selections, total_applied,
                total_completions, total_fallbacks, is_negative
            FROM procedure_records WHERE id = ?""",
            (procedure_id,),
        )
        row = await self._db.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "name": row[1],
            "evolution_type": row[2],
            "compilation_level": row[3],
            "intent_types": json.loads(row[4]) if row[4] else [],
            "total_selections": row[5],
            "total_applied": row[6],
            "total_completions": row[7],
            "total_fallbacks": row[8],
            "is_negative": bool(row[9]),
        }
```

### Tests (~4 tests)

- `test_find_matching_returns_results` — save a procedure, query with similar text, verify non-empty results
- `test_find_matching_returns_score` — each result has a `score` between 0 and 1
- `test_find_matching_excludes_negative_by_default` — negative procedures not returned unless `exclude_negative=False`
- `test_find_matching_empty_on_no_chroma` — graceful empty list when ChromaDB unavailable

---

## Part 5: Quality Metrics (AD-534 Foundation)

### File: `src/probos/cognitive/procedure_store.py`

**`record_selection()`** — Increment `total_selections` when AD-534 picks a procedure:

```python
    async def record_selection(self, procedure_id: str) -> None:
        """Record that a procedure was selected for potential replay."""
        await self._increment_counter(procedure_id, "total_selections")
```

**`record_applied()`** — Increment when replay starts:

```python
    async def record_applied(self, procedure_id: str) -> None:
        """Record that a procedure replay was initiated."""
        await self._increment_counter(procedure_id, "total_applied")
```

**`record_completion()`** — Increment on successful replay:

```python
    async def record_completion(self, procedure_id: str) -> None:
        """Record that a procedure replay completed successfully."""
        await self._increment_counter(procedure_id, "total_completions")
```

**`record_fallback()`** — Increment when replay fails and falls back to LLM:

```python
    async def record_fallback(self, procedure_id: str) -> None:
        """Record that a procedure replay failed and fell back to LLM."""
        await self._increment_counter(procedure_id, "total_fallbacks")
```

**`get_quality_metrics()`** — Read metrics for a procedure:

```python
    async def get_quality_metrics(self, procedure_id: str) -> dict[str, Any] | None:
        """Get quality metrics for a procedure.

        Returns dict with four counters and four derived rates:
        - applied_rate: applied / selected
        - completion_rate: completed / applied
        - effective_rate: completed / selected
        - fallback_rate: fallbacks / selected
        """
        if not self._db:
            return None
        await self._db.execute(
            """SELECT total_selections, total_applied, total_completions, total_fallbacks
            FROM procedure_records WHERE id = ?""",
            (procedure_id,),
        )
        row = await self._db.fetchone()
        if not row:
            return None
        sel, app, comp, fall = row
        return {
            "total_selections": sel,
            "total_applied": app,
            "total_completions": comp,
            "total_fallbacks": fall,
            "applied_rate": app / sel if sel > 0 else 0.0,
            "completion_rate": comp / app if app > 0 else 0.0,
            "effective_rate": comp / sel if sel > 0 else 0.0,
            "fallback_rate": fall / sel if sel > 0 else 0.0,
        }
```

**`_increment_counter()`** — Atomic counter update:

```python
    async def _increment_counter(self, procedure_id: str, column: str) -> None:
        """Atomically increment a quality metric counter."""
        if not self._db:
            return
        allowed = {"total_selections", "total_applied", "total_completions", "total_fallbacks"}
        if column not in allowed:
            raise ValueError(f"Invalid counter column: {column}")
        await self._db.execute(
            f"UPDATE procedure_records SET {column} = {column} + 1, updated_at = ? WHERE id = ?",
            (time.time(), procedure_id),
        )
        await self._db.commit()
```

### Tests (~6 tests)

- `test_record_selection_increments_counter` — verify `total_selections` goes from 0 to 1
- `test_record_completion_increments_counter` — verify `total_completions` goes from 0 to 1
- `test_record_fallback_increments_counter` — verify `total_fallbacks` goes from 0 to 1
- `test_get_quality_metrics_returns_counters_and_rates` — verify all 8 fields present
- `test_get_quality_metrics_derived_rates_correct` — set specific counters, verify rate math
- `test_get_quality_metrics_not_found_returns_none` — unknown ID returns None

---

## Part 6: Version DAG Traversal (AD-532b Foundation)

### File: `src/probos/cognitive/procedure_store.py`

**`get_lineage()`** — BFS upward to find ancestors:

```python
    async def get_lineage(self, procedure_id: str) -> list[str]:
        """Get ancestor procedure IDs via BFS upward through lineage DAG.

        Returns list of IDs from direct parents to root, breadth-first.
        Used by AD-532b for understanding procedure evolution history.
        """
        if not self._db:
            return []
        visited: list[str] = []
        queue = [procedure_id]
        while queue:
            current = queue.pop(0)
            await self._db.execute(
                "SELECT parent_procedure_id FROM procedure_lineage_parents WHERE procedure_id = ?",
                (current,),
            )
            rows = await self._db.fetchall()
            for row in rows:
                parent_id = row[0]
                if parent_id not in visited:
                    visited.append(parent_id)
                    queue.append(parent_id)
        return visited
```

**`get_descendants()`** — BFS downward to find children:

```python
    async def get_descendants(self, procedure_id: str) -> list[str]:
        """Get descendant procedure IDs via BFS downward through lineage DAG.

        Returns list of IDs from direct children outward, breadth-first.
        """
        if not self._db:
            return []
        visited: list[str] = []
        queue = [procedure_id]
        while queue:
            current = queue.pop(0)
            await self._db.execute(
                "SELECT procedure_id FROM procedure_lineage_parents WHERE parent_procedure_id = ?",
                (current,),
            )
            rows = await self._db.fetchall()
            for row in rows:
                child_id = row[0]
                if child_id not in visited:
                    visited.append(child_id)
                    queue.append(child_id)
        return visited
```

**`deactivate()`** — Mark a procedure as inactive (used by FIX evolution in AD-532b):

```python
    async def deactivate(self, procedure_id: str, superseded_by: str = "") -> None:
        """Mark a procedure as inactive. Used when a FIX replacement is created."""
        if not self._db:
            return
        await self._db.execute(
            "UPDATE procedure_records SET is_active = 0, superseded_by = ?, updated_at = ? WHERE id = ?",
            (superseded_by, time.time(), procedure_id),
        )
        await self._db.commit()
        # Update ChromaDB metadata
        if self._chroma_collection:
            try:
                self._chroma_collection.update(
                    ids=[procedure_id],
                    metadatas=[{"is_active": False}],
                )
            except Exception:
                pass
```

### Tests (~5 tests)

- `test_get_lineage_single_parent` — save parent + child with lineage, verify parent in lineage
- `test_get_lineage_multi_generation` — A -> B -> C, verify C's lineage = [B, A]
- `test_get_descendants_single_child` — verify child in descendants
- `test_get_descendants_multi_generation` — A -> B -> C, verify A's descendants = [B, C]
- `test_deactivate_sets_inactive_and_superseded` — verify `is_active=0` and `superseded_by` set

---

## Part 7: Dream Cycle Integration

### File: `src/probos/cognitive/dreaming.py`

**Add `procedure_store` parameter to `DreamingEngine.__init__()`:**

After the `llm_client` parameter (currently line 39):
```python
    procedure_store: Any = None,  # AD-533: persistent procedure storage
```

Store it:
```python
self._procedure_store = procedure_store  # AD-533
```

**Modify Step 7 (Procedure Extraction)** — add persistence after extraction:

Find the block (currently around line 200) where `self._extracted_cluster_ids.add(cluster.cluster_id)` happens. After `procedures.append(procedure)`, add:

```python
                    if procedure:
                        procedures.append(procedure)
                        procedures_extracted += 1
                        self._extracted_cluster_ids.add(cluster.cluster_id)
                        # AD-533: Persist to store
                        if self._procedure_store:
                            try:
                                await self._procedure_store.save(procedure)
                            except Exception as e:
                                logger.debug(
                                    "Procedure persistence failed (non-critical): %s", e
                                )
```

**Add cross-session dedup** — before the in-memory dedup check, add a store query:

```python
                # Skip clusters we've already processed (in-memory)
                if cluster.cluster_id in self._extracted_cluster_ids:
                    continue
                # Skip clusters already persisted (cross-session, AD-533)
                if self._procedure_store:
                    try:
                        if await self._procedure_store.has_cluster(cluster.cluster_id):
                            self._extracted_cluster_ids.add(cluster.cluster_id)  # warm cache
                            continue
                    except Exception:
                        pass  # fall through to in-memory check only
```

### File: `src/probos/startup/dreaming.py`

**Add `procedure_store` parameter to `init_dreaming()`:**

After `llm_client` parameter:
```python
procedure_store: Any = None,  # AD-533: persistent procedure storage
```

Pass to `DreamingEngine(...)`:
```python
procedure_store=procedure_store,
```

### File: `src/probos/runtime.py`

Find the `init_dreaming(...)` call and add:
```python
procedure_store=self.procedure_store,
```

Note: `self.procedure_store` may not exist yet on the Runtime. If not, this wiring will be done in the startup module. Search for how `llm_client` was wired — follow the same pattern. If `procedure_store` needs to be created during startup, add it alongside the existing store initialization sequence (after RecordsStore, before DreamingEngine):

```python
# AD-533: Procedure Store
from probos.cognitive.procedure_store import ProcedureStore
procedure_store = ProcedureStore(
    data_dir=data_dir / "procedures",
    records_store=records_store,  # AD-434 RecordsStore instance
)
await procedure_store.start()
```

Store it on the runtime so `stop()` can call `await procedure_store.stop()`. Follow the pattern of how other stores are initialized and stopped.

### Tests (~5 tests)

- `test_dreaming_engine_accepts_procedure_store` — `__init__` stores `_procedure_store`
- `test_dream_cycle_persists_procedures_to_store` — mock store, verify `save()` called for each extracted procedure
- `test_dream_cycle_cross_session_dedup` — mock store `has_cluster()` returns True, verify cluster skipped
- `test_dream_cycle_store_failure_non_critical` — store `save()` raises, dream cycle still completes
- `test_dream_cycle_works_without_store` — `procedure_store=None`, no errors

---

## Part 8: Thread Safety

### File: `src/probos/cognitive/procedure_store.py`

The `_write_lock` is already declared in `__init__`. Apply it to all write operations. The pattern: acquire lock before SQLite writes, release after commit.

**Update `_save_to_index()`** — wrap in lock:

```python
    async def _save_to_index(self, procedure: "Procedure", now: float) -> None:
        with self._write_lock:
            # ... existing insert logic ...
```

**Update `_increment_counter()`** — wrap in lock:

```python
    async def _increment_counter(self, procedure_id: str, column: str) -> None:
        if not self._db:
            return
        allowed = {"total_selections", "total_applied", "total_completions", "total_fallbacks"}
        if column not in allowed:
            raise ValueError(f"Invalid counter column: {column}")
        with self._write_lock:
            await self._db.execute(
                f"UPDATE procedure_records SET {column} = {column} + 1, updated_at = ? WHERE id = ?",
                (time.time(), procedure_id),
            )
            await self._db.commit()
```

**Update `deactivate()`** — wrap in lock:

```python
    async def deactivate(self, procedure_id: str, superseded_by: str = "") -> None:
        if not self._db:
            return
        with self._write_lock:
            await self._db.execute(...)
            await self._db.commit()
```

**Update `delete()`** — wrap in lock.

**Enable WAL mode** — add to `start()` after schema creation:

```python
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
```

**Note on read path:** Read operations (`get()`, `list_active()`, `find_matching()`, `get_quality_metrics()`, `get_lineage()`, `get_descendants()`, `has_cluster()`) use the same connection without lock. This is safe in WAL mode — SQLite supports concurrent readers with a single writer. If the builder observes contention in testing, the design allows upgrading to dedicated read-only connections later, but start simple.

### Tests (~2 tests)

- `test_wal_mode_enabled` — verify `PRAGMA journal_mode` returns `wal` after start
- `test_foreign_keys_enabled` — verify `PRAGMA foreign_keys` returns `1` after start

---

## Validation Checklist

After building, verify:

1. **Part 0 — Dataclass extension:**
   - [ ] `Procedure` has `is_active`, `generation`, `parent_procedure_ids`, `is_negative`, `superseded_by`, `tags`
   - [ ] All new fields have backward-compatible defaults
   - [ ] `to_dict()` includes all new fields
   - [ ] `from_dict()` classmethod reconstructs a Procedure from a dict
   - [ ] `from_dict()` handles missing fields gracefully (uses defaults)
   - [ ] Existing AD-532 tests still pass (no regressions)

2. **Part 1 — Class structure:**
   - [ ] `ProcedureStore.__init__` accepts `data_dir`, `records_store`, `connection_factory`
   - [ ] Falls back to `default_factory` singleton if `connection_factory` is None
   - [ ] `start()` creates SQLite DB and ChromaDB collection
   - [ ] `stop()` closes DB connection
   - [ ] ChromaDB failure is non-fatal (warning logged, `_chroma_collection = None`)

3. **Part 2 — SQLite schema:**
   - [ ] `procedure_records` table with all columns (id, name, metrics, DAG fields, content_snapshot)
   - [ ] `procedure_lineage_parents` table with composite PK
   - [ ] 4 indexes created (active, evolution, cluster, negative)
   - [ ] Schema is idempotent (`CREATE TABLE IF NOT EXISTS`)

4. **Part 3 — CRUD operations:**
   - [ ] `save()` writes to all three backends (SQLite, Ship's Records, ChromaDB)
   - [ ] `save()` handles each backend failure independently (log-and-continue)
   - [ ] `get()` reconstructs a `Procedure` from SQLite `content_snapshot`
   - [ ] `list_active()` filters by active, evolution_type, intent_type, compilation_level
   - [ ] `has_cluster()` returns True/False for origin_cluster_id lookup
   - [ ] `delete()` removes from SQLite and ChromaDB
   - [ ] Negative procedures saved to `records/procedures/anti-patterns/` path

5. **Part 4 — Semantic search:**
   - [ ] `find_matching()` queries ChromaDB and enriches with SQLite metrics
   - [ ] Results sorted by relevance score (highest first)
   - [ ] Negative procedures excluded by default
   - [ ] Returns empty list (not error) when ChromaDB unavailable

6. **Part 5 — Quality metrics:**
   - [ ] `record_selection/applied/completion/fallback()` each increment correct counter
   - [ ] `get_quality_metrics()` returns 4 counters + 4 derived rates
   - [ ] Derived rates handle division by zero (return 0.0)
   - [ ] `_increment_counter()` validates column name (defense in depth)

7. **Part 6 — Version DAG:**
   - [ ] `get_lineage()` BFS upward returns ancestors breadth-first
   - [ ] `get_descendants()` BFS downward returns children breadth-first
   - [ ] `deactivate()` sets `is_active=0` and `superseded_by` in both SQLite and ChromaDB

8. **Part 7 — Dream cycle integration:**
   - [ ] `DreamingEngine.__init__` accepts `procedure_store`
   - [ ] `_procedure_store` stored on instance
   - [ ] Step 7 calls `store.save()` after successful extraction
   - [ ] Cross-session dedup via `store.has_cluster()` before in-memory check
   - [ ] Store failure is non-critical (log-and-degrade)
   - [ ] `init_dreaming()` accepts and passes `procedure_store`
   - [ ] Runtime wires `procedure_store` into dreaming startup
   - [ ] `procedure_store.stop()` called during runtime shutdown

9. **Part 8 — Thread safety:**
   - [ ] `_write_lock` acquired for all SQLite write operations
   - [ ] WAL mode enabled after schema creation
   - [ ] Foreign keys enabled
   - [ ] Read operations do NOT acquire lock

10. **Cross-cutting:**
    - [ ] No import cycles
    - [ ] All existing tests still pass (AD-532's 29 tests, full suite)
    - [ ] ~46 new tests total
    - [ ] Pre-commit hook passes (no commercial content)
    - [ ] `ConnectionFactory` protocol used (never direct `aiosqlite.connect()`)
    - [ ] Ship's Records writes use `RecordsStore.write_entry()` (never direct file I/O)
