"""Knowledge Edge Store — typed entity→relation→entity triples (AD-687).

Phase A foundation of the Unified Knowledge Graph (research:
``docs/research/unified-knowledge-graph.md``). v1 ships the standalone
SQLite store with full CRUD + bounded recursive-CTE traversal. Consumers
arrive in AD-688 (Oracle Tier 6), AD-689 (backfill), AD-690 (Dream Step 10).

Cloud-Ready via the existing ``protocols.ConnectionFactory`` /
``DatabaseConnection`` Protocol pair (mirrors ``CognitiveJournal``,
``WorkforceMemoryStore``, etc. — see AD-542 / AD-680). Commercial overlays
swap the storage backend without touching this module.
"""

from __future__ import annotations

import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────

MAX_HOPS_CEILING = 3   # Hard upper bound on traversal depth (research §Phase 1).
MAX_TRAVERSE_ROWS = 5_000  # Safety cap on rows fetched from a single CTE walk.

_CLASSIFICATION_LABELS = {"private", "department", "ship", "fleet"}
"""Mirror of ``records_store._CLASSIFICATION_LEVELS`` keys (read-only)."""


# ── Enums ─────────────────────────────────────────────────────────


class KnowledgeEntityType(str, Enum):
    """The 8 v1 entity kinds tracked by the knowledge graph."""

    AGENT = "agent"
    DEPARTMENT = "department"
    INCIDENT = "incident"
    DECISION = "decision"
    DUTY = "duty"
    FINDING = "finding"
    CAPABILITY = "capability"
    STANDING_ORDER = "standing_order"


class KnowledgeRelationType(str, Enum):
    """The 10 v1 relation kinds. See research doc Phase-A relation table."""

    REPORTS_TO = "reports_to"
    MEMBER_OF = "member_of"
    COMPETENT_IN = "competent_in"
    RESOLVED_BY = "resolved_by"
    INVOLVED_IN = "involved_in"
    INFORMED_BY = "informed_by"
    DEPENDS_ON = "depends_on"
    PRODUCED_BY = "produced_by"
    CLASSIFIED_AS = "classified_as"
    ORIGINATED_ON = "originated_on"


# ── Edge dataclass ────────────────────────────────────────────────


@dataclass(frozen=True)
class KnowledgeEdge:
    """Immutable typed triple. ``id`` defaults to a fresh UUID4 hex.

    All defaulted fields appear AFTER the non-defaulted ones (Python
    frozen-dataclass rule). ``confidence`` and ``weight`` are validated in
    ``__post_init__`` to fall in [0.0, 1.0]. ``classification`` (when set)
    must be one of ``private/department/ship/fleet``.
    """

    source_type: KnowledgeEntityType
    source_id: str
    relation: KnowledgeRelationType
    target_type: KnowledgeEntityType
    target_id: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    confidence: float = 1.0
    weight: float = 1.0
    classification: str | None = None
    source_agent: str | None = None
    source_duty: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"AD-687: confidence must be in [0.0, 1.0], got {self.confidence!r}"
            )
        if not (0.0 <= self.weight <= 1.0):
            raise ValueError(
                f"AD-687: weight must be in [0.0, 1.0], got {self.weight!r}"
            )
        if self.classification is not None and self.classification not in _CLASSIFICATION_LABELS:
            raise ValueError(
                f"AD-687: classification must be one of {sorted(_CLASSIFICATION_LABELS)} "
                f"or None, got {self.classification!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serializable projection (enum values rendered as their string form)."""
        return {
            "id": self.id,
            "source_type": self.source_type.value,
            "source_id": self.source_id,
            "relation": self.relation.value,
            "target_type": self.target_type.value,
            "target_id": self.target_id,
            "confidence": self.confidence,
            "weight": self.weight,
            "classification": self.classification,
            "source_agent": self.source_agent,
            "source_duty": self.source_duty,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ── Service-layer Protocol (Dependency Inversion seam for AD-688/689) ──


@runtime_checkable
class KnowledgeEdgeStorage(Protocol):
    """Public CRUD + traversal surface that AD-688 (Oracle) and AD-689
    (backfill) will depend on. Implementations: ``SQLiteKnowledgeEdgeStore``
    in v1; commercial overlays may add Postgres/Kùzu (AD-694)."""

    async def add_edge(self, edge: KnowledgeEdge) -> str: ...
    async def get_edge(self, edge_id: str) -> KnowledgeEdge | None: ...
    async def update_edge(
        self,
        edge_id: str,
        *,
        confidence: float | None = None,
        weight: float | None = None,
        classification: str | None = None,
    ) -> bool: ...
    async def delete_edge(self, edge_id: str) -> bool: ...
    async def find_edges(
        self,
        *,
        source_type: KnowledgeEntityType | None = None,
        source_id: str | None = None,
        target_type: KnowledgeEntityType | None = None,
        target_id: str | None = None,
        relation: KnowledgeRelationType | None = None,
        limit: int = 100,
    ) -> list[KnowledgeEdge]: ...
    async def traverse(
        self,
        *,
        source_type: KnowledgeEntityType,
        source_id: str,
        max_hops: int = MAX_HOPS_CEILING,
        relation_filter: list[KnowledgeRelationType] | None = None,
    ) -> list[list[KnowledgeEdge]]: ...


# ── Schema ────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_edges (
    id              TEXT PRIMARY KEY,
    source_type     TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    relation        TEXT NOT NULL,
    target_type     TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 1.0,
    weight          REAL NOT NULL DEFAULT 1.0,
    classification  TEXT,
    source_agent    TEXT,
    source_duty     TEXT,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ke_source ON knowledge_edges(source_type, source_id, relation);
CREATE INDEX IF NOT EXISTS idx_ke_target ON knowledge_edges(target_type, target_id, relation);
CREATE INDEX IF NOT EXISTS idx_ke_relation ON knowledge_edges(relation);
CREATE INDEX IF NOT EXISTS idx_ke_classification ON knowledge_edges(classification);
"""


# ── Concrete store ────────────────────────────────────────────────


class SQLiteKnowledgeEdgeStore:
    """Default ``KnowledgeEdgeStorage`` implementation backed by SQLite.

    Mirrors ``CognitiveJournal`` shape (db_path + ConnectionFactory, async
    start/stop, idempotent schema). All write methods are fire-and-forget
    semantically — they NEVER raise to the caller; failures are logged
    and surface as ``return False`` (or empty list for queries).
    """

    def __init__(
        self,
        db_path: str | None = None,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.db_path = db_path
        self._db: DatabaseConnection | None = None
        if connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            connection_factory = default_factory
        self._connection_factory = connection_factory

    async def start(self) -> None:
        if not self.db_path:
            return
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await self._connection_factory.connect(self.db_path)
        # Row factory keeps column-name access in fetch helpers.
        self._db.row_factory = __import__("aiosqlite").Row  # type: ignore[attr-defined]
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        if self._db is not None:
            try:
                await self._db.close()
            except Exception:
                logger.debug("AD-687: edge store close failed", exc_info=True)
            self._db = None

    # ── CRUD ──────────────────────────────────────────────────

    async def add_edge(self, edge: KnowledgeEdge) -> str:
        if self._db is None:
            return edge.id
        try:
            await self._db.execute(
                """
                INSERT OR REPLACE INTO knowledge_edges
                  (id, source_type, source_id, relation, target_type, target_id,
                   confidence, weight, classification, source_agent, source_duty,
                   created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.id,
                    edge.source_type.value,
                    edge.source_id,
                    edge.relation.value,
                    edge.target_type.value,
                    edge.target_id,
                    edge.confidence,
                    edge.weight,
                    edge.classification,
                    edge.source_agent,
                    edge.source_duty,
                    edge.created_at,
                    edge.updated_at,
                ),
            )
            await self._db.commit()
        except sqlite3.Error:
            logger.warning("AD-687: add_edge failed for id=%s", edge.id, exc_info=True)
        return edge.id

    async def get_edge(self, edge_id: str) -> KnowledgeEdge | None:
        if self._db is None:
            return None
        try:
            cursor = await self._db.execute(
                "SELECT * FROM knowledge_edges WHERE id = ?", (edge_id,)
            )
            row = await cursor.fetchone()
        except sqlite3.Error:
            logger.warning("AD-687: get_edge failed for id=%s", edge_id, exc_info=True)
            return None
        if row is None:
            return None
        return self._row_to_edge(row)

    async def update_edge(
        self,
        edge_id: str,
        *,
        confidence: float | None = None,
        weight: float | None = None,
        classification: str | None = None,
    ) -> bool:
        if self._db is None:
            return False
        if confidence is None and weight is None and classification is None:
            return False
        # Validate at boundary — same rules as KnowledgeEdge.__post_init__.
        if confidence is not None and not (0.0 <= confidence <= 1.0):
            raise ValueError(f"AD-687: confidence must be in [0.0, 1.0], got {confidence!r}")
        if weight is not None and not (0.0 <= weight <= 1.0):
            raise ValueError(f"AD-687: weight must be in [0.0, 1.0], got {weight!r}")
        if classification is not None and classification not in _CLASSIFICATION_LABELS:
            raise ValueError(
                f"AD-687: classification must be one of {sorted(_CLASSIFICATION_LABELS)}, "
                f"got {classification!r}"
            )
        sets: list[str] = []
        params: list[Any] = []
        if confidence is not None:
            sets.append("confidence = ?")
            params.append(confidence)
        if weight is not None:
            sets.append("weight = ?")
            params.append(weight)
        if classification is not None:
            sets.append("classification = ?")
            params.append(classification)
        sets.append("updated_at = ?")
        params.append(time.time())
        params.append(edge_id)
        try:
            cursor = await self._db.execute(
                f"UPDATE knowledge_edges SET {', '.join(sets)} WHERE id = ?",
                tuple(params),
            )
            await self._db.commit()
            return (cursor.rowcount or 0) > 0
        except sqlite3.Error:
            logger.warning("AD-687: update_edge failed for id=%s", edge_id, exc_info=True)
            return False

    async def delete_edge(self, edge_id: str) -> bool:
        if self._db is None:
            return False
        try:
            cursor = await self._db.execute(
                "DELETE FROM knowledge_edges WHERE id = ?", (edge_id,)
            )
            await self._db.commit()
            return (cursor.rowcount or 0) > 0
        except sqlite3.Error:
            logger.warning("AD-687: delete_edge failed for id=%s", edge_id, exc_info=True)
            return False

    async def find_edges(
        self,
        *,
        source_type: KnowledgeEntityType | None = None,
        source_id: str | None = None,
        target_type: KnowledgeEntityType | None = None,
        target_id: str | None = None,
        relation: KnowledgeRelationType | None = None,
        limit: int = 100,
    ) -> list[KnowledgeEdge]:
        if self._db is None:
            return []
        clauses: list[str] = []
        params: list[Any] = []
        if source_type is not None:
            clauses.append("source_type = ?")
            params.append(source_type.value)
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if target_type is not None:
            clauses.append("target_type = ?")
            params.append(target_type.value)
        if target_id is not None:
            clauses.append("target_id = ?")
            params.append(target_id)
        if relation is not None:
            clauses.append("relation = ?")
            params.append(relation.value)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, min(limit, MAX_TRAVERSE_ROWS)))
        try:
            cursor = await self._db.execute(
                f"SELECT * FROM knowledge_edges{where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            )
            rows = await cursor.fetchall()
        except sqlite3.Error:
            logger.warning("AD-687: find_edges failed", exc_info=True)
            return []
        return [self._row_to_edge(r) for r in rows]

    # ── Traversal ─────────────────────────────────────────────

    async def traverse(
        self,
        *,
        source_type: KnowledgeEntityType,
        source_id: str,
        max_hops: int = MAX_HOPS_CEILING,
        relation_filter: list[KnowledgeRelationType] | None = None,
    ) -> list[list[KnowledgeEdge]]:
        """Bounded recursive-CTE walk. Returns paths (each path is a list of
        edges in walk order). Depth is hard-capped at ``MAX_HOPS_CEILING``
        regardless of caller-supplied ``max_hops``. Cycle protection is
        enforced in the CTE via a ``path`` column that accumulates visited
        ``(type:id)`` tokens; a candidate edge is excluded when its target
        already appears in the path. ``relation_filter`` restricts every hop
        to the listed relations.
        """
        if self._db is None:
            return []
        depth = max(1, min(int(max_hops), MAX_HOPS_CEILING))
        rel_clause = ""
        params: list[Any] = [source_type.value, source_id]
        if relation_filter:
            placeholders = ",".join(["?"] * len(relation_filter))
            rel_clause = f" AND relation IN ({placeholders})"
            params.extend(r.value for r in relation_filter)
        # Recursive bind also needs the same relation filter and the depth bound.
        params.append(depth)  # WHERE depth < ? in recursive arm
        if relation_filter:
            params.extend(r.value for r in relation_filter)

        sql = f"""
        WITH RECURSIVE walk(edge_id, src_type, src_id, rel, tgt_type, tgt_id,
                            confidence, weight, classification, source_agent,
                            source_duty, created_at, updated_at, depth, path) AS (
            SELECT id, source_type, source_id, relation, target_type, target_id,
                   confidence, weight, classification, source_agent, source_duty,
                   created_at, updated_at,
                   1 AS depth,
                   (source_type || ':' || source_id || '>' ||
                    target_type || ':' || target_id) AS path
            FROM knowledge_edges
            WHERE source_type = ? AND source_id = ?{rel_clause}
            UNION ALL
            SELECT ke.id, ke.source_type, ke.source_id, ke.relation,
                   ke.target_type, ke.target_id,
                   ke.confidence, ke.weight, ke.classification,
                   ke.source_agent, ke.source_duty,
                   ke.created_at, ke.updated_at,
                   walk.depth + 1,
                   walk.path || '>' || ke.target_type || ':' || ke.target_id
            FROM knowledge_edges ke
            JOIN walk ON ke.source_type = walk.tgt_type
                     AND ke.source_id   = walk.tgt_id
            WHERE walk.depth < ?{rel_clause}
              AND instr(walk.path, ke.target_type || ':' || ke.target_id) = 0
        )
        SELECT * FROM walk ORDER BY depth ASC, created_at DESC LIMIT ?
        """
        params.append(MAX_TRAVERSE_ROWS)
        try:
            cursor = await self._db.execute(sql, tuple(params))
            rows = await cursor.fetchall()
        except sqlite3.Error:
            logger.warning("AD-687: traverse failed", exc_info=True)
            return []

        # Group rows back into paths via the accumulated ``path`` column.
        # Each row's ``path`` ends at this edge's target; the parent path is
        # the prefix up to and including this edge's source token.
        paths_by_terminal: dict[str, list[KnowledgeEdge]] = {}
        for row in rows:
            edge = self._row_to_walk_edge(row)
            terminal = row["path"]
            # Locate parent path (path string up to but not including the
            # final ">target" segment).
            parent_terminal = terminal.rsplit(">", 1)[0]
            base = list(paths_by_terminal.get(parent_terminal, []))
            base.append(edge)
            paths_by_terminal[terminal] = base
        # Return paths ordered shortest-first then by insertion (CTE order).
        return sorted(paths_by_terminal.values(), key=lambda p: (len(p),))

    # ── Internal ──────────────────────────────────────────────

    @staticmethod
    def _row_to_edge(row: Any) -> KnowledgeEdge:
        return KnowledgeEdge(
            id=row["id"],
            source_type=KnowledgeEntityType(row["source_type"]),
            source_id=row["source_id"],
            relation=KnowledgeRelationType(row["relation"]),
            target_type=KnowledgeEntityType(row["target_type"]),
            target_id=row["target_id"],
            confidence=row["confidence"],
            weight=row["weight"],
            classification=row["classification"],
            source_agent=row["source_agent"],
            source_duty=row["source_duty"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_walk_edge(row: Any) -> KnowledgeEdge:
        return KnowledgeEdge(
            id=row["edge_id"],
            source_type=KnowledgeEntityType(row["src_type"]),
            source_id=row["src_id"],
            relation=KnowledgeRelationType(row["rel"]),
            target_type=KnowledgeEntityType(row["tgt_type"]),
            target_id=row["tgt_id"],
            confidence=row["confidence"],
            weight=row["weight"],
            classification=row["classification"],
            source_agent=row["source_agent"],
            source_duty=row["source_duty"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# Public alias for the default concrete store (consumed by AD-688/689).
KnowledgeEdgeStore = SQLiteKnowledgeEdgeStore
