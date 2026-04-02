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
    content_snapshot TEXT NOT NULL DEFAULT '{}',
    content_diff TEXT NOT NULL DEFAULT '',
    change_summary TEXT NOT NULL DEFAULT '',
    intent_types TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    origin_agent_ids TEXT NOT NULL DEFAULT '[]',
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
        db_path = str(self._data_dir / "procedures.db")
        self._db = await self._connection_factory.connect(db_path)
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        self._init_chroma()

    async def stop(self) -> None:
        """Close database connections."""
        if self._db:
            await self._db.close()
            self._db = None

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

    # ------------------------------------------------------------------
    # CRUD operations (Part 3)
    # ------------------------------------------------------------------

    async def save(
        self,
        procedure: "Any",
        *,
        content_diff: str = "",
        change_summary: str = "",
    ) -> str:
        """Persist a procedure to Ship's Records, SQLite index, and ChromaDB.

        Returns the procedure ID.
        """
        from probos.cognitive.procedures import Procedure

        if not isinstance(procedure, Procedure):
            raise TypeError(f"Expected Procedure, got {type(procedure).__name__}")

        now = time.time()
        await self._save_to_index(procedure, now, content_diff=content_diff, change_summary=change_summary)
        await self._save_to_records(procedure)
        self._save_to_chroma(procedure)
        return procedure.id

    async def _save_to_index(
        self, procedure: "Any", now: float,
        *, content_diff: str = "", change_summary: str = "",
    ) -> None:
        """Insert or replace procedure in SQLite index."""
        if not self._db:
            return
        content_snapshot = json.dumps(procedure.to_dict(), default=str)
        with self._write_lock:
            await self._db.execute(
                """INSERT OR REPLACE INTO procedure_records
                (id, name, description, origin_cluster_id, evolution_type,
                 compilation_level, is_active, is_negative, generation,
                 superseded_by, content_snapshot, content_diff, change_summary,
                 intent_types, tags,
                 origin_agent_ids, extraction_date, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    content_diff,
                    change_summary,
                    json.dumps(procedure.intent_types),
                    json.dumps(procedure.tags),
                    json.dumps(procedure.origin_agent_ids),
                    procedure.extraction_date,
                    now,
                    now,
                ),
            )
            for parent_id in procedure.parent_procedure_ids:
                await self._db.execute(
                    """INSERT OR IGNORE INTO procedure_lineage_parents
                    (procedure_id, parent_procedure_id) VALUES (?, ?)""",
                    (procedure.id, parent_id),
                )
            await self._db.commit()

    async def _save_to_records(self, procedure: "Any") -> None:
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

    def _save_to_chroma(self, procedure: "Any") -> None:
        """Add/update procedure in ChromaDB semantic index."""
        if not self._chroma_collection:
            return
        try:
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

    async def get(self, procedure_id: str) -> "Any | None":
        """Load a procedure from SQLite index by ID."""
        if not self._db:
            return None
        from probos.cognitive.procedures import Procedure

        cursor = await self._db.execute(
            "SELECT content_snapshot FROM procedure_records WHERE id = ?",
            (procedure_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        try:
            data = json.loads(row[0])
            return Procedure.from_dict(data)
        except Exception as e:
            logger.debug("Failed to deserialize procedure %s: %s", procedure_id, e)
            return None

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
        cursor = await self._db.execute(
            f"""SELECT id, name, evolution_type, compilation_level,
                intent_types, total_selections, total_applied,
                total_completions, total_fallbacks
            FROM procedure_records WHERE {where}
            ORDER BY total_completions DESC""",
            tuple(params),
        )
        rows = await cursor.fetchall()
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
            if intent_type and intent_type not in entry["intent_types"]:
                continue
            results.append(entry)
        return results

    async def has_cluster(self, cluster_id: str) -> bool:
        """Check if a procedure already exists for this origin cluster ID."""
        if not self._db:
            return False
        cursor = await self._db.execute(
            "SELECT 1 FROM procedure_records WHERE origin_cluster_id = ? LIMIT 1",
            (cluster_id,),
        )
        row = await cursor.fetchone()
        return row is not None

    async def delete(self, procedure_id: str) -> bool:
        """Remove a procedure from all backends. Returns True if found."""
        if not self._db:
            return False
        cursor = await self._db.execute(
            "SELECT 1 FROM procedure_records WHERE id = ?", (procedure_id,)
        )
        if not await cursor.fetchone():
            return False
        with self._write_lock:
            await self._db.execute(
                "DELETE FROM procedure_lineage_parents WHERE procedure_id = ? OR parent_procedure_id = ?",
                (procedure_id, procedure_id),
            )
            await self._db.execute(
                "DELETE FROM procedure_records WHERE id = ?", (procedure_id,)
            )
            await self._db.commit()
        if self._chroma_collection:
            try:
                self._chroma_collection.delete(ids=[procedure_id])
            except Exception:
                pass
        return True

    # ------------------------------------------------------------------
    # Semantic search (Part 4)
    # ------------------------------------------------------------------

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
                score = max(0.0, 1.0 - distance)
                matched.append({
                    "id": proc_id,
                    "score": score,
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                })

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

    async def _get_index_row(self, procedure_id: str) -> dict[str, Any] | None:
        """Load procedure metadata from SQLite index (no full content)."""
        if not self._db:
            return None
        cursor = await self._db.execute(
            """SELECT id, name, evolution_type, compilation_level,
                intent_types, total_selections, total_applied,
                total_completions, total_fallbacks, is_negative
            FROM procedure_records WHERE id = ?""",
            (procedure_id,),
        )
        row = await cursor.fetchone()
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

    # ------------------------------------------------------------------
    # Quality metrics (Part 5)
    # ------------------------------------------------------------------

    async def record_selection(self, procedure_id: str) -> None:
        """Record that a procedure was selected for potential replay."""
        await self._increment_counter(procedure_id, "total_selections")

    async def record_applied(self, procedure_id: str) -> None:
        """Record that a procedure replay was initiated."""
        await self._increment_counter(procedure_id, "total_applied")

    async def record_completion(self, procedure_id: str) -> None:
        """Record that a procedure replay completed successfully."""
        await self._increment_counter(procedure_id, "total_completions")

    async def record_fallback(self, procedure_id: str) -> None:
        """Record that a procedure replay failed and fell back to LLM."""
        await self._increment_counter(procedure_id, "total_fallbacks")

    async def get_quality_metrics(self, procedure_id: str) -> dict[str, Any] | None:
        """Get quality metrics for a procedure.

        Returns dict with four counters and four derived rates.
        """
        if not self._db:
            return None
        cursor = await self._db.execute(
            """SELECT total_selections, total_applied, total_completions, total_fallbacks
            FROM procedure_records WHERE id = ?""",
            (procedure_id,),
        )
        row = await cursor.fetchone()
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

    async def get_evolution_metadata(self, procedure_id: str) -> dict[str, str]:
        """Return content_diff and change_summary for a procedure."""
        if not self._db:
            return {"content_diff": "", "change_summary": ""}
        cursor = await self._db.execute(
            "SELECT content_diff, change_summary FROM procedure_records WHERE id = ?",
            (procedure_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return {"content_diff": "", "change_summary": ""}
        return {
            "content_diff": row[0] or "",
            "change_summary": row[1] or "",
        }

    async def _increment_counter(self, procedure_id: str, column: str) -> None:
        """Atomically increment a quality metric counter."""
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

    # ------------------------------------------------------------------
    # Version DAG traversal (Part 6)
    # ------------------------------------------------------------------

    async def get_lineage(self, procedure_id: str) -> list[str]:
        """Get ancestor procedure IDs via BFS upward through lineage DAG."""
        if not self._db:
            return []
        visited: list[str] = []
        queue = [procedure_id]
        while queue:
            current = queue.pop(0)
            cursor = await self._db.execute(
                "SELECT parent_procedure_id FROM procedure_lineage_parents WHERE procedure_id = ?",
                (current,),
            )
            rows = await cursor.fetchall()
            for row in rows:
                parent_id = row[0]
                if parent_id not in visited:
                    visited.append(parent_id)
                    queue.append(parent_id)
        return visited

    async def get_descendants(self, procedure_id: str) -> list[str]:
        """Get descendant procedure IDs via BFS downward through lineage DAG."""
        if not self._db:
            return []
        visited: list[str] = []
        queue = [procedure_id]
        while queue:
            current = queue.pop(0)
            cursor = await self._db.execute(
                "SELECT procedure_id FROM procedure_lineage_parents WHERE parent_procedure_id = ?",
                (current,),
            )
            rows = await cursor.fetchall()
            for row in rows:
                child_id = row[0]
                if child_id not in visited:
                    visited.append(child_id)
                    queue.append(child_id)
        return visited

    async def deactivate(self, procedure_id: str, superseded_by: str = "") -> None:
        """Mark a procedure as inactive. Used when a FIX replacement is created."""
        if not self._db:
            return
        with self._write_lock:
            # Update index columns
            await self._db.execute(
                "UPDATE procedure_records SET is_active = 0, superseded_by = ?, updated_at = ? WHERE id = ?",
                (superseded_by, time.time(), procedure_id),
            )
            # Also update the content_snapshot so get() returns the updated state
            cursor = await self._db.execute(
                "SELECT content_snapshot FROM procedure_records WHERE id = ?",
                (procedure_id,),
            )
            row = await cursor.fetchone()
            if row:
                try:
                    data = json.loads(row[0])
                    data["is_active"] = False
                    data["superseded_by"] = superseded_by
                    await self._db.execute(
                        "UPDATE procedure_records SET content_snapshot = ? WHERE id = ?",
                        (json.dumps(data, default=str), procedure_id),
                    )
                except Exception:
                    pass
            await self._db.commit()
        if self._chroma_collection:
            try:
                self._chroma_collection.update(
                    ids=[procedure_id],
                    metadatas=[{"is_active": False}],
                )
            except Exception:
                pass
