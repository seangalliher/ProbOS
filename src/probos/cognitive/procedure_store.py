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
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.cognitive.procedures import Procedure
    from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# AD-536: Procedure Criticality Classification
# ------------------------------------------------------------------

class ProcedureCriticality(str, Enum):
    LOW = "low"          # Read-only operations, reporting, analysis
    MEDIUM = "medium"    # Standard CRUD, routine operations
    HIGH = "high"        # Security changes, data mutations, cross-department
    CRITICAL = "critical"  # System configuration, destructive operations


def classify_criticality(procedure: "Procedure") -> ProcedureCriticality:
    """Classify procedure criticality from its metadata.

    Rules (first match wins):
    - If procedure.intent_pattern contains destructive keywords -> CRITICAL
    - If procedure has steps with agent_role containing "security" -> HIGH
    - If procedure is compound (multi-agent) -> HIGH (cross-department)
    - If procedure has >5 steps -> MEDIUM (complex procedure = more risk)
    - Default -> LOW
    """
    from probos.config import PROMOTION_DESTRUCTIVE_KEYWORDS

    # Check destructive keywords in intent types or name or description
    search_text = " ".join(procedure.intent_types + [procedure.name, procedure.description]).lower()
    for kw in PROMOTION_DESTRUCTIVE_KEYWORDS:
        if kw in search_text:
            return ProcedureCriticality.CRITICAL

    # Check for security roles in steps
    for step in procedure.steps:
        if "security" in (step.agent_role or "").lower():
            return ProcedureCriticality.HIGH

    # Check for compound (multi-agent) procedures
    distinct_roles = {s.agent_role for s in procedure.steps if s.agent_role}
    if len(distinct_roles) > 1:
        return ProcedureCriticality.HIGH

    # Complex procedures
    if len(procedure.steps) > 5:
        return ProcedureCriticality.MEDIUM

    return ProcedureCriticality.LOW

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
        # AD-535: Schema migration — add consecutive_successes column if missing
        await self._ensure_consecutive_successes_column()
        # AD-536: Schema migration — add promotion tracking columns
        await self._ensure_promotion_columns()
        # AD-537: Schema migration — add learned_via/learned_from columns
        await self._ensure_learned_via_columns()
        # AD-538: Schema migration — add lifecycle columns
        await self._ensure_lifecycle_columns()
        # AD-567d: Schema migration — add source_anchors_json column
        await self._ensure_source_anchors_column()
        self._init_chroma()
        # AD-535: Auto-promote qualifying Level 1 procedures to Level 2
        await self._migrate_qualifying_procedures()

    async def _ensure_consecutive_successes_column(self) -> None:
        """AD-535: Add consecutive_successes column if not present."""
        if not self._db:
            return
        try:
            cursor = await self._db.execute("PRAGMA table_info(procedure_records)")
            columns = [row[1] for row in await cursor.fetchall()]
            if "consecutive_successes" not in columns:
                await self._db.execute(
                    "ALTER TABLE procedure_records ADD COLUMN consecutive_successes INTEGER NOT NULL DEFAULT 0"
                )
                await self._db.commit()
                logger.info("AD-535: Added consecutive_successes column to procedure_records")
        except Exception as e:
            logger.debug("AD-535: Schema migration check failed: %s", e)

    async def _ensure_promotion_columns(self) -> None:
        """AD-536: Add promotion tracking columns if not present."""
        if not self._db:
            return
        try:
            cursor = await self._db.execute("PRAGMA table_info(procedure_records)")
            columns = {row[1] for row in await cursor.fetchall()}
            new_cols = [
                ("promotion_status", "TEXT DEFAULT 'private'"),
                ("promotion_requested_at", "TEXT"),
                ("promotion_decided_at", "TEXT"),
                ("promotion_decided_by", "TEXT"),
                ("promotion_rejection_reason", "TEXT"),
                ("promotion_directive_id", "TEXT"),
            ]
            added = 0
            for col_name, col_def in new_cols:
                if col_name not in columns:
                    await self._db.execute(
                        f"ALTER TABLE procedure_records ADD COLUMN {col_name} {col_def}"
                    )
                    added += 1
            if added:
                await self._db.commit()
                logger.info("AD-536: Added %d promotion columns to procedure_records", added)
        except Exception as e:
            logger.debug("AD-536: Promotion schema migration failed: %s", e)

    async def _ensure_learned_via_columns(self) -> None:
        """AD-537: Add learned_via and learned_from columns if not present."""
        if not self._db:
            return
        try:
            cursor = await self._db.execute("PRAGMA table_info(procedure_records)")
            columns = {row[1] for row in await cursor.fetchall()}
            new_cols = [
                ("learned_via", "TEXT DEFAULT 'direct'"),
                ("learned_from", "TEXT DEFAULT ''"),
            ]
            added = 0
            for col_name, col_def in new_cols:
                if col_name not in columns:
                    await self._db.execute(
                        f"ALTER TABLE procedure_records ADD COLUMN {col_name} {col_def}"
                    )
                    added += 1
            if added:
                await self._db.commit()
                logger.info("AD-537: Added %d learning provenance columns to procedure_records", added)
        except Exception as e:
            logger.debug("AD-537: Learning provenance migration failed: %s", e)

    async def _ensure_lifecycle_columns(self) -> None:
        """AD-538: Add last_used_at and is_archived columns if not present."""
        if not self._db:
            return
        try:
            cursor = await self._db.execute("PRAGMA table_info(procedure_records)")
            columns = {row[1] for row in await cursor.fetchall()}
            new_cols = [
                ("last_used_at", "REAL DEFAULT 0.0"),
                ("is_archived", "INTEGER DEFAULT 0"),
            ]
            added = 0
            for col_name, col_def in new_cols:
                if col_name not in columns:
                    await self._db.execute(
                        f"ALTER TABLE procedure_records ADD COLUMN {col_name} {col_def}"
                    )
                    added += 1
            if added:
                await self._db.commit()
                logger.info("AD-538: Added %d lifecycle columns to procedure_records", added)
        except Exception as e:
            logger.debug("AD-538: Lifecycle schema migration failed: %s", e)

    async def _ensure_source_anchors_column(self) -> None:
        """AD-567d: Add source_anchors_json column if not present."""
        if not self._db:
            return
        try:
            cursor = await self._db.execute("PRAGMA table_info(procedure_records)")
            columns = {row[1] for row in await cursor.fetchall()}
            if "source_anchors_json" not in columns:
                await self._db.execute(
                    "ALTER TABLE procedure_records ADD COLUMN source_anchors_json TEXT DEFAULT '[]'"
                )
                await self._db.commit()
                logger.info("AD-567d: Added source_anchors_json column to procedure_records")
        except Exception as e:
            logger.debug("AD-567d: Source anchors schema migration failed: %s", e)

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
                 origin_agent_ids, extraction_date, created_at, updated_at,
                 learned_via, learned_from, last_used_at, is_archived,
                 source_anchors_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    getattr(procedure, "learned_via", "direct"),
                    getattr(procedure, "learned_from", ""),
                    getattr(procedure, "last_used_at", 0.0) or procedure.extraction_date,
                    1 if getattr(procedure, "is_archived", False) else 0,
                    json.dumps(getattr(procedure, "source_anchors", [])),
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
        # AD-538: Update last_used_at — this resets the decay clock
        if self._db:
            with self._write_lock:
                await self._db.execute(
                    "UPDATE procedure_records SET last_used_at = ? WHERE id = ?",
                    (time.time(), procedure_id),
                )
                await self._db.commit()

    async def record_applied(self, procedure_id: str) -> None:
        """Record that a procedure replay was initiated."""
        await self._increment_counter(procedure_id, "total_applied")

    async def record_completion(self, procedure_id: str) -> None:
        """Record that a procedure replay completed successfully."""
        await self._increment_counter(procedure_id, "total_completions")

    async def record_fallback(self, procedure_id: str) -> None:
        """Record that a procedure replay failed and fell back to LLM."""
        await self._increment_counter(procedure_id, "total_fallbacks")

    async def record_consecutive_success(self, procedure_id: str) -> int:
        """AD-535: Increment consecutive_successes counter. Return new count."""
        if not self._db:
            return 0
        with self._write_lock:
            await self._db.execute(
                "UPDATE procedure_records SET consecutive_successes = consecutive_successes + 1, "
                "updated_at = ? WHERE id = ?",
                (time.time(), procedure_id),
            )
            await self._db.commit()
        cursor = await self._db.execute(
            "SELECT consecutive_successes FROM procedure_records WHERE id = ?",
            (procedure_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def reset_consecutive_successes(self, procedure_id: str) -> None:
        """AD-535: Reset consecutive_successes to 0 (on any failure)."""
        if not self._db:
            return
        with self._write_lock:
            await self._db.execute(
                "UPDATE procedure_records SET consecutive_successes = 0, updated_at = ? WHERE id = ?",
                (time.time(), procedure_id),
            )
            await self._db.commit()

    async def promote_compilation_level(self, procedure_id: str, new_level: int) -> None:
        """AD-535: Promote procedure to a higher compilation level. Reset consecutive_successes."""
        if not self._db:
            return
        with self._write_lock:
            await self._db.execute(
                "UPDATE procedure_records SET compilation_level = ?, consecutive_successes = 0, "
                "updated_at = ? WHERE id = ?",
                (new_level, time.time(), procedure_id),
            )
            await self._db.commit()
        proc = await self.get(procedure_id)
        if proc:
            logger.info("Procedure '%s' promoted to Level %d", proc.name, new_level)

    async def demote_compilation_level(self, procedure_id: str, new_level: int) -> None:
        """AD-535: Demote procedure to a lower compilation level. Reset consecutive_successes."""
        if not self._db:
            return
        with self._write_lock:
            await self._db.execute(
                "UPDATE procedure_records SET compilation_level = ?, consecutive_successes = 0, "
                "updated_at = ? WHERE id = ?",
                (new_level, time.time(), procedure_id),
            )
            await self._db.commit()
        proc = await self.get(procedure_id)
        if proc:
            logger.info("Procedure '%s' demoted to Level %d", proc.name, new_level)

    async def get_quality_metrics(self, procedure_id: str) -> dict[str, Any] | None:
        """Get quality metrics for a procedure.

        Returns dict with four counters, consecutive_successes, and four derived rates.
        """
        if not self._db:
            return None
        cursor = await self._db.execute(
            """SELECT total_selections, total_applied, total_completions, total_fallbacks,
                COALESCE(consecutive_successes, 0)
            FROM procedure_records WHERE id = ?""",
            (procedure_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        sel, app, comp, fall, consec = row
        return {
            "total_selections": sel,
            "total_applied": app,
            "total_completions": comp,
            "total_fallbacks": fall,
            "consecutive_successes": consec,
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

    async def _migrate_qualifying_procedures(self) -> None:
        """AD-535: One-time migration — promote Level 1 procedures that already have
        enough completions to Level 2 (Guided). Handles transition from
        pre-AD-535 binary replay to graduated compilation."""
        from probos.config import COMPILATION_PROMOTION_THRESHOLD

        if not self._db:
            return
        try:
            cursor = await self._db.execute(
                "UPDATE procedure_records SET compilation_level = 2 "
                "WHERE compilation_level = 1 AND total_completions >= ? AND is_active = 1",
                (COMPILATION_PROMOTION_THRESHOLD,),
            )
            if cursor.rowcount and cursor.rowcount > 0:
                logger.info(
                    "AD-535 migration: promoted %d procedures from Level 1 to Level 2",
                    cursor.rowcount,
                )
            await self._db.commit()
        except Exception as e:
            logger.debug("AD-535 migration failed: %s", e)

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

    # ------------------------------------------------------------------
    # AD-536: Procedure Promotion
    # ------------------------------------------------------------------

    async def request_promotion(self, procedure_id: str) -> dict[str, Any]:
        """Mark procedure as pending promotion. Returns promotion request summary.

        Validates eligibility:
        - compilation_level >= PROMOTION_MIN_COMPILATION_LEVEL
        - total_completions >= PROMOTION_MIN_TOTAL_COMPLETIONS
        - effective_rate >= PROMOTION_MIN_EFFECTIVE_RATE
        - promotion_status not 'pending'
        - Not within PROMOTION_REJECTION_COOLDOWN_HOURS of a rejection
        """
        from probos.config import (
            PROMOTION_MIN_COMPILATION_LEVEL, PROMOTION_MIN_TOTAL_COMPLETIONS,
            PROMOTION_MIN_EFFECTIVE_RATE, PROMOTION_REJECTION_COOLDOWN_HOURS,
        )

        if not self._db:
            return {"eligible": False, "reason": "Database not available"}

        # Get procedure metadata
        cursor = await self._db.execute(
            """SELECT compilation_level, total_completions, total_selections,
                COALESCE(promotion_status, 'private') as promotion_status,
                promotion_decided_at, promotion_rejection_reason,
                content_snapshot, evolution_type
            FROM procedure_records WHERE id = ?""",
            (procedure_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return {"eligible": False, "reason": "Procedure not found"}

        comp_level, total_comp, total_sel, promo_status = row[0], row[1], row[2], row[3]
        decided_at, rejection_reason = row[4], row[5]
        content_snapshot, evolution_type = row[6], row[7]

        # Already pending or approved
        if promo_status == "pending":
            return {"eligible": False, "reason": "Promotion already pending"}
        if promo_status == "approved":
            return {"eligible": False, "reason": "Procedure already promoted"}

        # Compilation level check
        if comp_level < PROMOTION_MIN_COMPILATION_LEVEL:
            return {
                "eligible": False,
                "reason": f"Compilation level {comp_level} < required {PROMOTION_MIN_COMPILATION_LEVEL}",
            }

        # Total completions check
        if total_comp < PROMOTION_MIN_TOTAL_COMPLETIONS:
            return {
                "eligible": False,
                "reason": f"Total completions {total_comp} < required {PROMOTION_MIN_TOTAL_COMPLETIONS}",
            }

        # Effective rate check
        effective_rate = total_comp / total_sel if total_sel > 0 else 0.0
        if effective_rate < PROMOTION_MIN_EFFECTIVE_RATE:
            return {
                "eligible": False,
                "reason": f"Effective rate {effective_rate:.2f} < required {PROMOTION_MIN_EFFECTIVE_RATE}",
            }

        # Rejection cooldown check
        if promo_status == "rejected" and decided_at:
            try:
                from datetime import datetime, timezone
                decided_dt = datetime.fromisoformat(decided_at)
                elapsed_hours = (datetime.now(timezone.utc) - decided_dt).total_seconds() / 3600
                if elapsed_hours < PROMOTION_REJECTION_COOLDOWN_HOURS:
                    remaining = PROMOTION_REJECTION_COOLDOWN_HOURS - elapsed_hours
                    return {
                        "eligible": False,
                        "reason": f"Within rejection cooldown ({remaining:.0f}h remaining). "
                                  f"Previous rejection: {rejection_reason or 'no reason given'}",
                    }
            except Exception:
                pass  # If timestamp parsing fails, allow re-request

        # All checks passed — mark as pending
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._write_lock:
            await self._db.execute(
                "UPDATE procedure_records SET promotion_status = 'pending', "
                "promotion_requested_at = ?, updated_at = ? WHERE id = ?",
                (now_iso, time.time(), procedure_id),
            )
            await self._db.commit()

        # Build procedure summary from content_snapshot
        proc_data = {}
        try:
            proc_data = json.loads(content_snapshot) if content_snapshot else {}
        except Exception:
            pass

        procedure = await self.get(procedure_id)
        criticality = classify_criticality(procedure) if procedure else ProcedureCriticality.LOW

        quality = await self.get_quality_metrics(procedure_id)

        return {
            "eligible": True,
            "procedure_id": procedure_id,
            "procedure_name": proc_data.get("name", ""),
            "procedure_description": proc_data.get("description", ""),
            "intent_types": proc_data.get("intent_types", []),
            "compilation_level": comp_level,
            "evolution_type": evolution_type,
            "quality_metrics": quality or {},
            "criticality": criticality.value,
        }

    async def approve_promotion(
        self, procedure_id: str, decided_by: str, directive_id: str
    ) -> None:
        """Mark procedure as approved. Link to the created directive."""
        if not self._db:
            return
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._write_lock:
            await self._db.execute(
                "UPDATE procedure_records SET promotion_status = 'approved', "
                "promotion_decided_at = ?, promotion_decided_by = ?, "
                "promotion_directive_id = ?, updated_at = ? WHERE id = ?",
                (now_iso, decided_by, directive_id, time.time(), procedure_id),
            )
            await self._db.commit()
        logger.info("AD-536: Procedure %s approved for promotion by %s", procedure_id, decided_by)

    async def reject_promotion(
        self, procedure_id: str, decided_by: str, reason: str
    ) -> None:
        """Mark procedure as rejected. Store rejection reason as institutional knowledge."""
        if not self._db:
            return
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._write_lock:
            await self._db.execute(
                "UPDATE procedure_records SET promotion_status = 'rejected', "
                "promotion_decided_at = ?, promotion_decided_by = ?, "
                "promotion_rejection_reason = ?, updated_at = ? WHERE id = ?",
                (now_iso, decided_by, reason, time.time(), procedure_id),
            )
            await self._db.commit()
        logger.info("AD-536: Procedure %s rejected by %s — %s", procedure_id, decided_by, reason)

    async def get_pending_promotions(
        self, department: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all procedures with promotion_status='pending'."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            """SELECT id, name, compilation_level, evolution_type,
                intent_types, total_completions, total_selections,
                promotion_requested_at, content_snapshot
            FROM procedure_records
            WHERE COALESCE(promotion_status, 'private') = 'pending'
            ORDER BY promotion_requested_at ASC""",
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            proc_id, name, comp_level = row[0], row[1], row[2]
            evo_type, intent_types_json = row[3], row[4]
            total_comp, total_sel = row[5], row[6]
            requested_at, content_snapshot = row[7], row[8]

            # Filter by department if specified
            if department:
                try:
                    data = json.loads(content_snapshot) if content_snapshot else {}
                    tags = data.get("tags", [])
                    if not any(department.lower() in t.lower() for t in tags):
                        origin_agents = data.get("origin_agent_ids", [])
                        if not any(department.lower() in a.lower() for a in origin_agents):
                            continue
                except Exception:
                    pass

            effective_rate = total_comp / total_sel if total_sel > 0 else 0.0
            procedure = await self.get(proc_id)
            criticality = classify_criticality(procedure) if procedure else ProcedureCriticality.LOW

            results.append({
                "procedure_id": proc_id,
                "name": name,
                "compilation_level": comp_level,
                "evolution_type": evo_type,
                "intent_types": json.loads(intent_types_json) if intent_types_json else [],
                "total_completions": total_comp,
                "effective_rate": effective_rate,
                "criticality": criticality.value,
                "requested_at": requested_at,
            })
        return results

    async def get_promotion_status(self, procedure_id: str) -> str:
        """Get current promotion status for a procedure."""
        if not self._db:
            return "private"
        cursor = await self._db.execute(
            "SELECT COALESCE(promotion_status, 'private') FROM procedure_records WHERE id = ?",
            (procedure_id,),
        )
        row = await cursor.fetchone()
        return row[0] if row else "private"

    async def get_promoted_procedures(self) -> list[dict[str, Any]]:
        """Get all procedures with promotion_status='approved'."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            """SELECT id, name, compilation_level, evolution_type,
                intent_types, total_completions, total_selections,
                promotion_decided_at, promotion_decided_by,
                promotion_directive_id
            FROM procedure_records
            WHERE COALESCE(promotion_status, 'private') = 'approved'
            ORDER BY promotion_decided_at DESC""",
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            total_comp, total_sel = row[5], row[6]
            effective_rate = total_comp / total_sel if total_sel > 0 else 0.0
            results.append({
                "procedure_id": row[0],
                "name": row[1],
                "compilation_level": row[2],
                "evolution_type": row[3],
                "intent_types": json.loads(row[4]) if row[4] else [],
                "total_completions": total_comp,
                "effective_rate": effective_rate,
                "decided_at": row[7],
                "decided_by": row[8],
                "directive_id": row[9],
            })
        return results

    async def get_observed_procedures(
        self, agent: str | None = None
    ) -> list[dict[str, Any]]:
        """AD-537: Get procedures learned via observation or teaching."""
        if not self._db:
            return []
        cursor = await self._db.execute(
            """SELECT id, name, compilation_level, evolution_type,
                COALESCE(learned_via, 'direct') as learned_via,
                COALESCE(learned_from, '') as learned_from,
                total_completions, total_selections,
                intent_types
            FROM procedure_records
            WHERE COALESCE(learned_via, 'direct') != 'direct' AND is_active = 1
            ORDER BY created_at DESC""",
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            proc_id, name, comp_level = row[0], row[1], row[2]
            evo_type, lv, lf = row[3], row[4], row[5]
            total_comp, total_sel = row[6], row[7]
            intent_types_json = row[8]

            if agent and lf != agent:
                continue

            effective_rate = total_comp / total_sel if total_sel > 0 else 0.0
            results.append({
                "procedure_id": proc_id,
                "name": name,
                "compilation_level": comp_level,
                "evolution_type": evo_type,
                "learned_via": lv,
                "learned_from": lf,
                "total_completions": total_comp,
                "effective_rate": effective_rate,
                "intent_types": json.loads(intent_types_json) if intent_types_json else [],
            })
        return results

    # ------------------------------------------------------------------
    # AD-538: Procedure Lifecycle — Decay, Archive, Dedup, Merge
    # ------------------------------------------------------------------

    async def decay_stale_procedures(self, now: float | None = None) -> list[dict]:
        """AD-538: Decay procedures unused for longer than LIFECYCLE_DECAY_DAYS.

        Returns list of dicts describing what was decayed:
        [{"id": str, "name": str, "old_level": int, "new_level": int}]
        """
        from probos.config import LIFECYCLE_DECAY_DAYS, LIFECYCLE_MIN_SELECTIONS_FOR_DECAY

        if not self._db:
            return []

        if now is None:
            now = time.time()

        cutoff = now - (LIFECYCLE_DECAY_DAYS * 86400)

        cursor = await self._db.execute(
            """SELECT id, name, compilation_level, content_snapshot
            FROM procedure_records
            WHERE is_active = 1
              AND COALESCE(is_archived, 0) = 0
              AND is_negative = 0
              AND COALESCE(last_used_at, 0.0) > 0
              AND COALESCE(last_used_at, 0.0) < ?
              AND compilation_level > 1
              AND total_selections >= ?""",
            (cutoff, LIFECYCLE_MIN_SELECTIONS_FOR_DECAY),
        )
        rows = await cursor.fetchall()
        decayed = []

        for row in rows:
            proc_id, name, old_level, snapshot_json = row[0], row[1], row[2], row[3]
            new_level = old_level - 1

            with self._write_lock:
                await self._db.execute(
                    "UPDATE procedure_records SET compilation_level = ?, "
                    "consecutive_successes = 0, updated_at = ? WHERE id = ?",
                    (new_level, now, proc_id),
                )
                # Update content_snapshot
                try:
                    data = json.loads(snapshot_json) if snapshot_json else {}
                    data["compilation_level"] = new_level
                    await self._db.execute(
                        "UPDATE procedure_records SET content_snapshot = ? WHERE id = ?",
                        (json.dumps(data, default=str), proc_id),
                    )
                except Exception:
                    pass
                await self._db.commit()

            # Update ChromaDB metadata
            if self._chroma_collection:
                try:
                    self._chroma_collection.update(
                        ids=[proc_id],
                        metadatas=[{"compilation_level": new_level}],
                    )
                except Exception:
                    pass

            logger.info(
                "Procedure '%s' decayed from Level %d to Level %d (unused for %d+ days)",
                name, old_level, new_level, LIFECYCLE_DECAY_DAYS,
            )
            decayed.append({
                "id": proc_id,
                "name": name,
                "old_level": old_level,
                "new_level": new_level,
            })

        return decayed

    async def archive_stale_procedures(self, now: float | None = None) -> list[dict]:
        """AD-538: Archive procedures at Level 1 unused for LIFECYCLE_ARCHIVE_DAYS.

        Returns list of dicts describing what was archived:
        [{"id": str, "name": str, "days_unused": int}]
        """
        from probos.config import LIFECYCLE_ARCHIVE_DAYS

        if not self._db:
            return []

        if now is None:
            now = time.time()

        cutoff = now - (LIFECYCLE_ARCHIVE_DAYS * 86400)

        cursor = await self._db.execute(
            """SELECT id, name, COALESCE(last_used_at, 0.0) as last_used
            FROM procedure_records
            WHERE is_active = 1
              AND COALESCE(is_archived, 0) = 0
              AND compilation_level = 1
              AND COALESCE(last_used_at, 0.0) > 0
              AND COALESCE(last_used_at, 0.0) < ?""",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        archived = []

        for row in rows:
            proc_id, name, last_used = row[0], row[1], row[2]
            days_unused = int((now - last_used) / 86400)

            with self._write_lock:
                await self._db.execute(
                    "UPDATE procedure_records SET is_active = 0, is_archived = 1, "
                    "updated_at = ? WHERE id = ?",
                    (now, proc_id),
                )
                # Update content_snapshot
                snap_cursor = await self._db.execute(
                    "SELECT content_snapshot FROM procedure_records WHERE id = ?",
                    (proc_id,),
                )
                snap_row = await snap_cursor.fetchone()
                if snap_row:
                    try:
                        data = json.loads(snap_row[0]) if snap_row[0] else {}
                        data["is_active"] = False
                        data["is_archived"] = True
                        await self._db.execute(
                            "UPDATE procedure_records SET content_snapshot = ? WHERE id = ?",
                            (json.dumps(data, default=str), proc_id),
                        )
                    except Exception:
                        pass
                await self._db.commit()

            # Write to Ship's Records _archived/ directory
            if self._records_store:
                try:
                    import yaml
                    proc = await self.get(proc_id)
                    if proc:
                        content = yaml.dump(proc.to_dict(), default_flow_style=False, sort_keys=False)
                        await self._records_store.write_entry(
                            author="system",
                            path=f"procedures/_archived/{proc_id}.yaml",
                            content=content,
                            message=f"Archived procedure: {name} (unused {days_unused} days)",
                            classification="ship",
                            topic="procedures",
                            tags=["archived"],
                        )
                except Exception as e:
                    logger.debug("Failed to archive procedure to Ship's Records: %s", e)

            # Remove from ChromaDB
            if self._chroma_collection:
                try:
                    self._chroma_collection.delete(ids=[proc_id])
                except Exception:
                    pass

            logger.info(
                "Procedure '%s' archived (unused at Level 1 for %d days)",
                name, days_unused,
            )
            archived.append({
                "id": proc_id,
                "name": name,
                "days_unused": days_unused,
            })

        return archived

    async def restore_procedure(self, procedure_id: str) -> bool:
        """AD-538: Restore an archived procedure to active status at Level 1."""
        if not self._db:
            return False

        cursor = await self._db.execute(
            "SELECT COALESCE(is_archived, 0), content_snapshot FROM procedure_records WHERE id = ?",
            (procedure_id,),
        )
        row = await cursor.fetchone()
        if not row or not row[0]:
            return False  # Not found or not archived

        now = time.time()
        with self._write_lock:
            await self._db.execute(
                "UPDATE procedure_records SET is_active = 1, is_archived = 0, "
                "compilation_level = 1, last_used_at = ?, consecutive_successes = 0, "
                "updated_at = ? WHERE id = ?",
                (now, now, procedure_id),
            )
            # Update content_snapshot
            try:
                data = json.loads(row[1]) if row[1] else {}
                data["is_active"] = True
                data["is_archived"] = False
                data["compilation_level"] = 1
                data["last_used_at"] = now
                await self._db.execute(
                    "UPDATE procedure_records SET content_snapshot = ? WHERE id = ?",
                    (json.dumps(data, default=str), procedure_id),
                )
            except Exception:
                pass
            await self._db.commit()

        # Re-add to ChromaDB
        proc = await self.get(procedure_id)
        if proc:
            self._save_to_chroma(proc)
            logger.info("Procedure '%s' restored to active Level 1", proc.name)

        return True

    async def get_stale_procedures(self, days: int | None = None) -> list[dict[str, Any]]:
        """AD-538: List procedures that would be affected by decay."""
        from probos.config import LIFECYCLE_DECAY_DAYS, LIFECYCLE_MIN_SELECTIONS_FOR_DECAY

        if not self._db:
            return []

        if days is None:
            days = LIFECYCLE_DECAY_DAYS

        now = time.time()
        cutoff = now - (days * 86400)

        cursor = await self._db.execute(
            """SELECT id, name, compilation_level, COALESCE(last_used_at, 0.0),
                total_completions, total_selections
            FROM procedure_records
            WHERE is_active = 1
              AND COALESCE(is_archived, 0) = 0
              AND is_negative = 0
              AND COALESCE(last_used_at, 0.0) > 0
              AND COALESCE(last_used_at, 0.0) < ?
              AND compilation_level > 1
              AND total_selections >= ?
            ORDER BY last_used_at ASC""",
            (cutoff, LIFECYCLE_MIN_SELECTIONS_FOR_DECAY),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            last_used = row[3]
            days_unused = int((now - last_used) / 86400)
            results.append({
                "id": row[0],
                "name": row[1],
                "compilation_level": row[2],
                "last_used_at": last_used,
                "days_unused": days_unused,
                "total_completions": row[4],
                "total_selections": row[5],
            })
        return results

    async def get_archived_procedures(self, limit: int = 20) -> list[dict[str, Any]]:
        """AD-538: List archived procedures."""
        if not self._db:
            return []

        cursor = await self._db.execute(
            """SELECT id, name, compilation_level, COALESCE(last_used_at, 0.0),
                total_completions, updated_at
            FROM procedure_records
            WHERE COALESCE(is_archived, 0) = 1
            ORDER BY updated_at DESC
            LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            results.append({
                "id": row[0],
                "name": row[1],
                "compilation_level": row[2],
                "last_used_at": row[3],
                "total_completions": row[4],
                "archived_at": row[5],
            })
        return results

    async def find_duplicate_candidates(self) -> list[dict]:
        """AD-538: Find procedure pairs with high semantic similarity.

        Returns list of candidate merge pairs:
        [{"primary_id": str, "primary_name": str, "duplicate_id": str,
          "duplicate_name": str, "similarity": float}]
        """
        from probos.config import (
            LIFECYCLE_DEDUP_SIMILARITY_THRESHOLD,
            LIFECYCLE_DEDUP_MAX_CANDIDATES,
        )

        if not self._chroma_collection or not self._db:
            return []

        # Load active, non-negative, non-archived procedures
        procedures = await self.list_active(min_compilation_level=0)
        procedures = procedures[:LIFECYCLE_DEDUP_MAX_CANDIDATES]

        seen_pairs: set[tuple[str, str]] = set()
        candidates = []

        for proc in procedures:
            proc_id = proc["id"]
            proc_obj = await self.get(proc_id)
            if not proc_obj:
                continue

            query_text = f"{proc_obj.name}. {proc_obj.description}"
            matches = await self.find_matching(
                query_text, n_results=5, min_compilation_level=0,
            )

            for match in matches:
                match_id = match["id"]
                if match_id == proc_id:
                    continue

                score = match.get("score", 0.0)
                if score < LIFECYCLE_DEDUP_SIMILARITY_THRESHOLD:
                    continue

                # Require shared intent_type
                proc_intents = set(proc.get("intent_types", []))
                match_intents = set(match.get("intent_types", []))
                if not proc_intents & match_intents:
                    continue

                # Normalize pair ordering to avoid duplicates
                pair = tuple(sorted([proc_id, match_id]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)

                # Determine primary vs duplicate
                proc_comp = proc.get("total_completions", 0)
                match_comp = match.get("total_completions", 0)
                match_obj = await self.get(match_id)

                if proc_comp > match_comp:
                    primary_id, primary_name = proc_id, proc_obj.name
                    dup_id, dup_name = match_id, match_obj.name if match_obj else match_id
                elif match_comp > proc_comp:
                    primary_id, primary_name = match_id, match_obj.name if match_obj else match_id
                    dup_id, dup_name = proc_id, proc_obj.name
                else:
                    # Tie-break by compilation level
                    p_level = proc.get("compilation_level", 1)
                    m_level = match.get("compilation_level", 1)
                    if p_level >= m_level:
                        primary_id, primary_name = proc_id, proc_obj.name
                        dup_id, dup_name = match_id, match_obj.name if match_obj else match_id
                    else:
                        primary_id, primary_name = match_id, match_obj.name if match_obj else match_id
                        dup_id, dup_name = proc_id, proc_obj.name

                candidates.append({
                    "primary_id": primary_id,
                    "primary_name": primary_name,
                    "duplicate_id": dup_id,
                    "duplicate_name": dup_name,
                    "similarity": round(score, 3),
                })

        candidates.sort(key=lambda x: x["similarity"], reverse=True)
        return candidates

    async def merge_procedures(self, primary_id: str, duplicate_id: str) -> bool:
        """AD-538: Merge duplicate into primary. Deactivates duplicate,
        transfers stats to primary."""
        if not self._db:
            return False

        primary = await self.get(primary_id)
        duplicate = await self.get(duplicate_id)
        if not primary or not duplicate:
            return False
        if not primary.is_active or not duplicate.is_active:
            return False

        # Get quality metrics for both
        d_metrics = await self.get_quality_metrics(duplicate_id) or {}

        # Transfer stats
        with self._write_lock:
            await self._db.execute(
                """UPDATE procedure_records SET
                    total_selections = total_selections + ?,
                    total_applied = total_applied + ?,
                    total_completions = total_completions + ?,
                    total_fallbacks = total_fallbacks + ?,
                    updated_at = ?
                WHERE id = ?""",
                (
                    d_metrics.get("total_selections", 0),
                    d_metrics.get("total_applied", 0),
                    d_metrics.get("total_completions", 0),
                    d_metrics.get("total_fallbacks", 0),
                    time.time(),
                    primary_id,
                ),
            )
            await self._db.commit()

        # Merge tags and intent_types
        merged_tags = list(set(primary.tags + duplicate.tags))
        merged_intents = list(set(primary.intent_types + duplicate.intent_types))

        # Preserve observational provenance
        if getattr(duplicate, "learned_via", "direct") != "direct":
            merged_tags.append(f"merged_from_observed:{duplicate.id}")

        # Update primary's content_snapshot with merged tags/intent_types
        cursor = await self._db.execute(
            "SELECT content_snapshot FROM procedure_records WHERE id = ?",
            (primary_id,),
        )
        row = await cursor.fetchone()
        if row:
            try:
                data = json.loads(row[0]) if row[0] else {}
                data["tags"] = merged_tags
                data["intent_types"] = merged_intents
                with self._write_lock:
                    await self._db.execute(
                        "UPDATE procedure_records SET content_snapshot = ?, "
                        "tags = ?, intent_types = ? WHERE id = ?",
                        (
                            json.dumps(data, default=str),
                            json.dumps(merged_tags),
                            json.dumps(merged_intents),
                            primary_id,
                        ),
                    )
                    await self._db.commit()
            except Exception:
                pass

        # Deactivate duplicate
        await self.deactivate(duplicate_id, superseded_by=primary_id)

        logger.info(
            "Merged procedure '%s' into '%s'",
            duplicate.name, primary.name,
        )
        return True
