# AD-687 v1 — Knowledge Edge Store

**Phase:** Unified Knowledge Graph + Oracle Unification — **Phase A (Foundation)**
**GitHub issue:** [#381](https://github.com/seangordon/probos/issues/381) (closes on merge)
**Layer:** OSS
**Predecessor:** AD-686 (Oracle Tier 5, Wave 36, commit `48db252`)
**Standalone:** no hard runtime dependencies (Oracle integration is the next AD's job)
**Research:** `docs/research/unified-knowledge-graph.md` §"Storage Layer: SQLite First, Kùzu Upgrade Path"

---

## v1 Scope (one line)

Greenfield: introduce `KnowledgeEdge` typed-triple store at `src/probos/knowledge/edges.py` with full CRUD, recursive-CTE bounded traversal (1–3 hops, with cycle protection), Pydantic config + startup wiring, and `runtime.knowledge_edges` public attribute. Cloud-Ready via the **existing** `protocols.ConnectionFactory` / `DatabaseConnection` pattern (no new connection protocol).

**Captain's "complete v1" standing convention (banked 2026-05-04) applies:** ship the full edge-store spec in one Builder cycle. The only legitimate v1 boundaries are the **separate ADs** that consume the store (AD-688 Oracle Tier 6 / AD-689 backfill / AD-690 Dream Step 10) — none of those are deferral of AD-687 scope, they are independent issues #382/#383/#384.

---

## Verify-First Findings (HEAD `227240f`)

| Item | Verified |
|---|---|
| `docs/research/unified-knowledge-graph.md` Phase-A SQL schema | lines 104–119 (table + 4 indexes); recursive-CTE example at lines 124–141 |
| Existing connection abstraction | `src/probos/protocols.py:186` `DatabaseConnection` Protocol; `:223` `ConnectionFactory` Protocol — **REUSE** these, do NOT define new ones |
| Default factory | `src/probos/storage/sqlite_factory.py:28` `default_factory = SQLiteConnectionFactory()` — **REUSE** |
| Sibling SQLite store to mirror | `src/probos/cognitive/journal.py:109–148` `CognitiveJournal` (`__init__(db_path, connection_factory)` → `start()` runs `executescript` → `stop()` closes; `aiosqlite.Row` row factory; `executemany` for batch) |
| Sibling startup wiring | `src/probos/startup/communication.py:307–315` (cognitive_journal block); adopt at `src/probos/runtime.py:1608` (`self.cognitive_journal = comm.cognitive_journal`); default-`None` slot at `runtime.py:425` |
| Sibling Pydantic config | `src/probos/config.py:1735` `CognitiveJournalConfig`; wired onto `SystemConfig` at `:2051` |
| Classification labels source | `src/probos/knowledge/records_store.py:27` `_CLASSIFICATION_LEVELS = {"private":0, "department":1, "ship":2, "fleet":3}` — REUSE these four labels (no new taxonomy) |
| `runtime.knowledge_edges` collision check | `grep -n "knowledge_edges\|KnowledgeEdge\|KnowledgeEntityType\|KnowledgeRelationType\|KnowledgeEdgeStorage" src/probos/ tests/` → **0 hits**. Fully greenfield. |
| `src/probos/knowledge/__init__.py` exports | line 3 exports only `KnowledgeStore` — append `KnowledgeEdgeStore` (Section 1d). |
| Wave-plan slot | id `"37"` at `prompts/wave-plan.yaml:398–408` already populated, status `pending`; do NOT touch in this draft commit. |

**Why a service-layer `KnowledgeEdgeStorage` Protocol is in v1 (not deferred).** Captain explicitly listed it. AD-688 (Oracle Tier 6) and AD-689 (backfill) are the two known consumers. A 6-method async Protocol declared in the same module costs ~25 lines and lets AD-688 depend on the abstract type, not the concrete class. This is Dependency Inversion done at the natural seam.

---

## Phantom-API Pre-Check

Run before commit:

```pwsh
./scripts/phantom-api-precheck.ps1 prompts/ad-687-knowledge-edge-store-v1.md
```

**Expected at draft time: 0 phantoms.** Every symbol referenced in this prompt either:
- exists at HEAD `227240f` (verified table above), or
- is introduced by this prompt (Section 1) — the precheck correctly flags these as intra-prompt.

If the precheck flags any other candidate, document it as an FP in the build report; do NOT fix without architect review.

---

## Section 0 — Naming-Collision Check (Wave 32 retrospective)

Builder MUST grep BEFORE writing Section 3 wiring:

```pwsh
git grep -n "def knowledge_edges\b\|knowledge_edges\s*=" src/probos/
```

**Expected: only the 2 sites this prompt introduces** (`runtime.py:425` slot, `runtime.py:1608` adoption). If any other hit appears, **HARD STOP** and surface to architect. `runtime.knowledge_edges` is the public attribute (Wave 5 #1 — no underscore).

---

## Section 1 — `src/probos/knowledge/edges.py` (NEW FILE)

Create the full module. This is the only source file for v1.

```python
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
```

### Section 1d — Update `src/probos/knowledge/__init__.py`

```python
# SEARCH
"""Persistent knowledge store — Git-backed artifact repository."""

from probos.knowledge.store import KnowledgeStore

__all__ = ["KnowledgeStore"]
# REPLACE
"""Persistent knowledge store — Git-backed artifact repository."""

from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEdgeStorage,
    KnowledgeEdgeStore,
    KnowledgeEntityType,
    KnowledgeRelationType,
    SQLiteKnowledgeEdgeStore,
)
from probos.knowledge.store import KnowledgeStore

__all__ = [
    "KnowledgeEdge",
    "KnowledgeEdgeStorage",
    "KnowledgeEdgeStore",
    "KnowledgeEntityType",
    "KnowledgeRelationType",
    "KnowledgeStore",
    "SQLiteKnowledgeEdgeStore",
]
# END REPLACE
```

---

## Section 2 — Pydantic config

### 2a — `src/probos/config.py` — new model

Insert IMMEDIATELY AFTER `class CognitiveJournalConfig` (currently config.py:1735–1742). Anchor SEARCH on the closing line of `CognitiveJournalConfig` followed by the next class header (`ClinicalTelemetryConfig`):

```python
# SEARCH
class CognitiveJournalConfig(BaseModel):
    """Cognitive Journal — append-only LLM reasoning trace store (AD-431)."""
    enabled: bool = True
    retention_days: int = 14         # Keep journal entries for N days (0 = keep forever)
    max_rows: int = 500_000          # Hard cap on total rows (0 = no cap)
    prune_interval_seconds: float = 3600.0


class ClinicalTelemetryConfig(BaseModel):
# REPLACE
class CognitiveJournalConfig(BaseModel):
    """Cognitive Journal — append-only LLM reasoning trace store (AD-431)."""
    enabled: bool = True
    retention_days: int = 14         # Keep journal entries for N days (0 = keep forever)
    max_rows: int = 500_000          # Hard cap on total rows (0 = no cap)
    prune_interval_seconds: float = 3600.0


class KnowledgeEdgesConfig(BaseModel):
    """Knowledge Edge Store — typed-triple graph (AD-687).

    Default ``enabled=True`` is intentional and DEVIATES from the Wave-10
    transitional-flag convention. Rationale: this v1 ships an empty,
    write-only-when-called-by-consumers SQLite table. Consumers (Oracle
    Tier 6, Hebbian backfill, Dream Step 10) arrive in AD-688/689/690. With
    no consumers the store costs one CREATE TABLE IF NOT EXISTS at boot —
    invisible at runtime. Same precedent: ``CognitiveJournalConfig`` (also
    enabled=True for an infrastructure store).
    """
    enabled: bool = True
    db_path: str = "data/knowledge_edges.sqlite"
    max_traverse_hops: int = 3

    @field_validator("max_traverse_hops")
    @classmethod
    def _cap_hops(cls, v: int) -> int:
        if v < 1 or v > 3:
            raise ValueError(
                "knowledge_edges.max_traverse_hops must be in [1, 3] "
                "(MAX_HOPS_CEILING; research §Phase 1)"
            )
        return v


class ClinicalTelemetryConfig(BaseModel):
# END REPLACE
```

**Builder:** if `field_validator` is not already imported in `config.py`, add it to the existing `from pydantic import ...` line. Verify with `grep -n "field_validator" src/probos/config.py` before editing — most likely already present (used by `DiagnosticContextConfig` per Wave 33).

### 2b — `src/probos/config.py` — wire onto `SystemConfig`

Anchor SEARCH on the existing `cognitive_journal` field at config.py:2051:

```python
# SEARCH
    cognitive_journal: CognitiveJournalConfig = CognitiveJournalConfig()
# REPLACE
    cognitive_journal: CognitiveJournalConfig = CognitiveJournalConfig()
    knowledge_edges: KnowledgeEdgesConfig = Field(default_factory=KnowledgeEdgesConfig)  # AD-687
# END REPLACE
```

**Note:** `Field` is already imported in `config.py` (used throughout). If `default_factory=` triggers a warning that `KnowledgeEdgesConfig()` would also work (no mutable defaults), the Builder MAY simplify to `= KnowledgeEdgesConfig()` mirroring the sibling. Either form is acceptable.

---

## Section 3 — Startup wiring

### 3a — `src/probos/startup/communication.py` — build the store

Insert IMMEDIATELY AFTER the Cognitive Journal block (currently lines 307–315). Anchor SEARCH on the journal-block tail + the next sibling header:

```python
# SEARCH
        cognitive_journal = CognitiveJournal(
            db_path=str(data_dir / "cognitive_journal.db"),
        )
        await cognitive_journal.start()
        asyncio.create_task(journal_prune_loop_fn())
        logger.info("cognitive-journal started")

    # --- Skill Framework (AD-428) ---
# REPLACE
        cognitive_journal = CognitiveJournal(
            db_path=str(data_dir / "cognitive_journal.db"),
        )
        await cognitive_journal.start()
        asyncio.create_task(journal_prune_loop_fn())
        logger.info("cognitive-journal started")

    # --- Knowledge Edge Store (AD-687) ---
    knowledge_edges = None
    if config.knowledge_edges.enabled:
        from probos.knowledge.edges import SQLiteKnowledgeEdgeStore

        knowledge_edges = SQLiteKnowledgeEdgeStore(
            db_path=str(data_dir / Path(config.knowledge_edges.db_path).name),
        )
        await knowledge_edges.start()
        logger.info("knowledge-edges started (db=%s)", knowledge_edges.db_path)

    # --- Skill Framework (AD-428) ---
# END REPLACE
```

**Note:** `data_dir` is already in scope (used by the journal block above). `Path` is already imported at the top of `communication.py`. Verify both with `grep -n "from pathlib import Path\|^data_dir" src/probos/startup/communication.py` before editing.

### 3b — `src/probos/startup/communication.py` — return the store

Builder MUST locate the function's return statement (the `CommunicationServices` dataclass return at the end of `init_communication_services`) and add `knowledge_edges=knowledge_edges,` to the field list. Also add `knowledge_edges: SQLiteKnowledgeEdgeStore | None = None` to the `CommunicationServices` dataclass definition (top of file). **Builder:** locate both via:

```pwsh
git grep -n "class CommunicationServices\|return CommunicationServices(" src/probos/startup/communication.py
```

Add the field next to `cognitive_journal: CognitiveJournal | None = None` in the dataclass and pass `knowledge_edges=knowledge_edges` adjacent to `cognitive_journal=cognitive_journal` in the return. Use `from probos.knowledge.edges import SQLiteKnowledgeEdgeStore` at the top of the file (or under TYPE_CHECKING if it's already there for similar types — mirror the journal import style).

### 3c — `src/probos/runtime.py` — default-`None` slot

Anchor SEARCH on the existing `cognitive_journal` slot at line 425:

```python
# SEARCH
        # --- Cognitive Journal (AD-431) ---
        self.cognitive_journal: CognitiveJournal | None = None

        # --- Counselor Profile Store (AD-503) ---
# REPLACE
        # --- Cognitive Journal (AD-431) ---
        self.cognitive_journal: CognitiveJournal | None = None

        # --- Knowledge Edge Store (AD-687) ---
        self.knowledge_edges: Any = None  # SQLiteKnowledgeEdgeStore | None — Any to avoid circular import

        # --- Counselor Profile Store (AD-503) ---
# END REPLACE
```

`Any` is already imported in runtime.py (verify with `grep -n "^from typing" src/probos/runtime.py`).

### 3d — `src/probos/runtime.py` — adopt from `comm`

Anchor SEARCH on the existing journal adoption at line 1608:

```python
# SEARCH
        self.cognitive_journal = comm.cognitive_journal
        self.skill_registry = comm.skill_registry
# REPLACE
        self.cognitive_journal = comm.cognitive_journal
        self.knowledge_edges = comm.knowledge_edges  # AD-687
        self.skill_registry = comm.skill_registry
# END REPLACE
```

---

## Section 4 — Tests

Create `tests/test_ad687_knowledge_edge_store.py`. **12 tests** — meets Captain's "complete v1" floor of 10 with 2-test margin for drift.

```python
"""Tests for AD-687 Knowledge Edge Store."""

from __future__ import annotations

import time
import pytest

from probos.knowledge.edges import (
    MAX_HOPS_CEILING,
    KnowledgeEdge,
    KnowledgeEdgeStorage,
    KnowledgeEntityType,
    KnowledgeRelationType,
    SQLiteKnowledgeEdgeStore,
)


@pytest.fixture
async def store(tmp_path):
    s = SQLiteKnowledgeEdgeStore(db_path=str(tmp_path / "edges.sqlite"))
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


def _edge(src, rel, tgt, **kw):
    return KnowledgeEdge(
        source_type=KnowledgeEntityType.AGENT,
        source_id=src,
        relation=rel,
        target_type=KnowledgeEntityType.AGENT,
        target_id=tgt,
        **kw,
    )


# 1. Schema/migration creates table + indexes
@pytest.mark.asyncio
async def test_schema_creates_table_and_indexes(tmp_path):
    s = SQLiteKnowledgeEdgeStore(db_path=str(tmp_path / "x.sqlite"))
    await s.start()
    try:
        cur = await s._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge_edges'"
        )
        assert (await cur.fetchone())["name"] == "knowledge_edges"
        cur = await s._db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_ke_%'"
        )
        idxs = {r["name"] for r in await cur.fetchall()}
        assert {"idx_ke_source", "idx_ke_target", "idx_ke_relation", "idx_ke_classification"} <= idxs
    finally:
        await s.stop()


# 2. add_edge happy path returns id and persists
@pytest.mark.asyncio
async def test_add_edge_returns_id_and_persists(store):
    e = _edge("a1", KnowledgeRelationType.REPORTS_TO, "a2", classification="ship")
    returned_id = await store.add_edge(e)
    assert returned_id == e.id
    fetched = await store.get_edge(e.id)
    assert fetched is not None
    assert fetched.source_id == "a1" and fetched.target_id == "a2"
    assert fetched.relation == KnowledgeRelationType.REPORTS_TO
    assert fetched.classification == "ship"


# 3. get_edge by id round-trips ALL 13 fields
@pytest.mark.asyncio
async def test_get_edge_round_trip_all_fields(store):
    now = time.time()
    e = KnowledgeEdge(
        id="custom-id-1",
        source_type=KnowledgeEntityType.DEPARTMENT,
        source_id="engineering",
        relation=KnowledgeRelationType.MEMBER_OF,
        target_type=KnowledgeEntityType.AGENT,
        target_id="ag-7",
        confidence=0.8,
        weight=0.6,
        classification="department",
        source_agent="agent-x",
        source_duty="duty-42",
        created_at=now,
        updated_at=now,
    )
    await store.add_edge(e)
    got = await store.get_edge("custom-id-1")
    assert got is not None
    assert got.to_dict() == e.to_dict()


# 4. find_edges filter by source_type + source_id
@pytest.mark.asyncio
async def test_find_edges_by_source(store):
    await store.add_edge(_edge("a1", KnowledgeRelationType.REPORTS_TO, "a2"))
    await store.add_edge(_edge("a1", KnowledgeRelationType.MEMBER_OF, "a3"))
    await store.add_edge(_edge("a9", KnowledgeRelationType.REPORTS_TO, "a2"))
    found = await store.find_edges(
        source_type=KnowledgeEntityType.AGENT, source_id="a1"
    )
    assert len(found) == 2
    assert {e.target_id for e in found} == {"a2", "a3"}


# 5. find_edges filter by relation
@pytest.mark.asyncio
async def test_find_edges_by_relation(store):
    await store.add_edge(_edge("a1", KnowledgeRelationType.REPORTS_TO, "a2"))
    await store.add_edge(_edge("a3", KnowledgeRelationType.REPORTS_TO, "a4"))
    await store.add_edge(_edge("a5", KnowledgeRelationType.MEMBER_OF, "a6"))
    found = await store.find_edges(relation=KnowledgeRelationType.REPORTS_TO)
    assert len(found) == 2
    assert all(e.relation == KnowledgeRelationType.REPORTS_TO for e in found)


# 6. update_edge changes confidence + weight + advances updated_at
@pytest.mark.asyncio
async def test_update_edge_advances_updated_at(store):
    e = _edge("a1", KnowledgeRelationType.COMPETENT_IN, "skill-x",
              confidence=0.5, weight=0.5)
    await store.add_edge(e)
    original_updated = (await store.get_edge(e.id)).updated_at
    time.sleep(0.01)  # ensure clock tick
    ok = await store.update_edge(e.id, confidence=0.9, weight=0.7)
    assert ok is True
    after = await store.get_edge(e.id)
    assert after.confidence == 0.9 and after.weight == 0.7
    assert after.updated_at > original_updated


# 7. delete_edge — verify gone
@pytest.mark.asyncio
async def test_delete_edge(store):
    e = _edge("a1", KnowledgeRelationType.REPORTS_TO, "a2")
    await store.add_edge(e)
    ok = await store.delete_edge(e.id)
    assert ok is True
    assert await store.get_edge(e.id) is None
    # Idempotent — second delete returns False
    assert await store.delete_edge(e.id) is False


# 8. traverse 1-hop returns single-edge paths
@pytest.mark.asyncio
async def test_traverse_one_hop(store):
    await store.add_edge(_edge("a1", KnowledgeRelationType.REPORTS_TO, "a2"))
    await store.add_edge(_edge("a1", KnowledgeRelationType.REPORTS_TO, "a3"))
    paths = await store.traverse(
        source_type=KnowledgeEntityType.AGENT,
        source_id="a1",
        max_hops=1,
    )
    assert len(paths) == 2
    assert all(len(p) == 1 for p in paths)
    assert {p[0].target_id for p in paths} == {"a2", "a3"}


# 9. traverse 2-hop with relation_filter
@pytest.mark.asyncio
async def test_traverse_two_hop_with_relation_filter(store):
    # Chain a1 -reports_to-> a2 -reports_to-> a3, and noise edge a2 -member_of-> dept
    await store.add_edge(_edge("a1", KnowledgeRelationType.REPORTS_TO, "a2"))
    await store.add_edge(_edge("a2", KnowledgeRelationType.REPORTS_TO, "a3"))
    await store.add_edge(_edge("a2", KnowledgeRelationType.MEMBER_OF, "dept-x"))
    paths = await store.traverse(
        source_type=KnowledgeEntityType.AGENT,
        source_id="a1",
        max_hops=2,
        relation_filter=[KnowledgeRelationType.REPORTS_TO],
    )
    # Expect: 1-hop a1->a2, 2-hop a1->a2->a3. NO member_of branch.
    assert len(paths) == 2
    by_len = {len(p): p for p in paths}
    assert by_len[1][0].target_id == "a2"
    assert by_len[2][1].target_id == "a3"
    # Confirm no member_of in any returned edge
    for p in paths:
        for edge in p:
            assert edge.relation == KnowledgeRelationType.REPORTS_TO


# 10. traverse caps at MAX_HOPS_CEILING when caller passes higher value
@pytest.mark.asyncio
async def test_traverse_caps_at_max_hops_ceiling(store):
    # 5-link chain a1 -> a2 -> a3 -> a4 -> a5 -> a6
    for i in range(1, 6):
        await store.add_edge(_edge(f"a{i}", KnowledgeRelationType.REPORTS_TO, f"a{i+1}"))
    paths = await store.traverse(
        source_type=KnowledgeEntityType.AGENT,
        source_id="a1",
        max_hops=5,  # exceeds ceiling
    )
    # Deepest path is bounded by MAX_HOPS_CEILING
    assert paths
    assert max(len(p) for p in paths) <= MAX_HOPS_CEILING == 3


# 11. cycle detection — A→B→A→B does NOT infinite-loop
@pytest.mark.asyncio
async def test_traverse_cycle_terminates(store):
    await store.add_edge(_edge("a1", KnowledgeRelationType.DEPENDS_ON, "a2"))
    await store.add_edge(_edge("a2", KnowledgeRelationType.DEPENDS_ON, "a1"))
    paths = await store.traverse(
        source_type=KnowledgeEntityType.AGENT,
        source_id="a1",
        max_hops=3,
    )
    # Walk: a1->a2 (depth 1); a2->a1 would re-add a1 to path → blocked.
    # Expect exactly one path of length 1.
    assert len(paths) == 1
    assert len(paths[0]) == 1
    assert paths[0][0].source_id == "a1" and paths[0][0].target_id == "a2"


# 12. confidence/weight bounds validation in dataclass
def test_edge_validation_rejects_out_of_bounds():
    with pytest.raises(ValueError, match="confidence"):
        KnowledgeEdge(
            source_type=KnowledgeEntityType.AGENT, source_id="a", relation=KnowledgeRelationType.REPORTS_TO,
            target_type=KnowledgeEntityType.AGENT, target_id="b", confidence=1.5,
        )
    with pytest.raises(ValueError, match="weight"):
        KnowledgeEdge(
            source_type=KnowledgeEntityType.AGENT, source_id="a", relation=KnowledgeRelationType.REPORTS_TO,
            target_type=KnowledgeEntityType.AGENT, target_id="b", weight=-0.1,
        )
    with pytest.raises(ValueError, match="classification"):
        KnowledgeEdge(
            source_type=KnowledgeEntityType.AGENT, source_id="a", relation=KnowledgeRelationType.REPORTS_TO,
            target_type=KnowledgeEntityType.AGENT, target_id="b", classification="top_secret",
        )
    # KnowledgeEdgeStorage Protocol acceptance smoke (runtime_checkable)
    s = SQLiteKnowledgeEdgeStore(db_path=None)
    assert isinstance(s, KnowledgeEdgeStorage)
```

---

## What This AD Does NOT Change

These are **out of scope by design** because they are the deliverable of separate, already-tracked GitHub issues — NOT deferral of AD-687 v1 scope:

| Out | Where it lives next |
|---|---|
| API endpoint (`/api/knowledge/edges/...`) | AD-688 wires the read paths via Oracle Tier 6 (issue #382) |
| Oracle Tier 6 graph integration / post-merge expansion | AD-688 (issue #382) |
| Edge population from existing data (Hebbian, ontology, episodes) | AD-689 (issue #383) |
| Dream Step 10 relationship inference | AD-690 (issue #384) |
| Classification enforcement on read/write paths | AD-692 (issue #386, **commercial**) |
| Federation cross-instance edge sync | AD-693 (issue #387, **commercial**) |
| Kùzu migration tooling | AD-694 (issue #388, **commercial**) |
| Pruning / retention policy on `knowledge_edges` | AD-687-followup if data warrants (no shipped consumer in v1 → no growth signal yet) |
| Shell command (`/edges`, `/graph`) | AD-688 or later, once consumers exist |
| HXI surface for graph visualisation | AD-690b or later |

---

## Standing Conventions

1. **Wave 5 #1 — public over private.** `runtime.knowledge_edges` (no underscore). Verified collision-free (Section 0 grep returns only this prompt's own sites).
2. **Wave 32 retrospective — property collision.** `SQLiteKnowledgeEdgeStore` is NOT a `CognitiveAgent` subclass; no `@property` shadowing risk.
3. **AD-680 / BF-254 — `iscoroutinefunction` over `hasattr`.** N/A here (no MagicMock-style runtime guards in v1; pure DI through `connection_factory`).
4. **Cloud-Ready — REUSE existing protocols.** `ConnectionFactory` + `DatabaseConnection` from `protocols.py` (lines 186/223). Do NOT define a new connection protocol.
5. **Captain's "complete v1" convention (banked 2026-05-04).** No deferral within AD-687 spec. Boundary deferrals to AD-688/689/690 are separate-issue scope, NOT v1 cuts.
6. **Default-`True` deviation rationale documented in config docstring** (mirrors `CognitiveJournalConfig`) — boot cost is one CREATE TABLE IF NOT EXISTS; runtime visibility is zero until consumers arrive.

---

## Acceptance Criteria

1. Full parallel gate green: `pytest tests/ -q -n 8 --dist=loadfile` (test count delta exactly +12 vs baseline 10994 → 11006; tolerated drift +10 if any test is dropped during build).
2. New module `src/probos/knowledge/edges.py` exists with `KnowledgeEntityType` (8 values), `KnowledgeRelationType` (10 values), `KnowledgeEdge` (frozen, validated), `KnowledgeEdgeStorage` Protocol, `SQLiteKnowledgeEdgeStore` (CRUD + traverse), `KnowledgeEdgeStore` alias.
3. `src/probos/knowledge/__init__.py` exports the 6 new names.
4. `KnowledgeEdgesConfig` defined in `config.py` and wired onto `SystemConfig.knowledge_edges` with `field_validator` ceiling at 3 hops.
5. `runtime.knowledge_edges` is the same instance built in `startup/communication.py` (verified by `id()` equality in any debug snippet — not required as a test).
6. Phantom-API pre-check returns 0 phantoms (matches draft-time expectation; document any FPs in build report).
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
8. PROGRESS.md flipped from `AD-687` planned → `AD-687 v1 CLOSED`.
9. `docs/development/roadmap.md` AD-687 entry status flipped to `complete`.
10. DECISIONS.md AD-687 entry appended (one-paragraph summary; cross-link AD-686, AD-688, AD-462e, research doc).
11. GH issue #381 closed on merge (or surfaced for manual close per EMU 403).

---

## Tracking

- **PROGRESS.md** — prepend `AD-687 v1 CLOSED.` entry with one-paragraph summary, gate count, test-count delta, deferral list (AD-688/689/690/692/693/694).
- **docs/development/roadmap.md** — flip the AD-687 entry status from `Scoped` → `complete`.
- **DECISIONS.md** — append AD-687 entry. Schema: Problem / Solution / Cross-links (AD-462e Oracle, AD-686 Tier 5, AD-688 future Tier 6, research doc, Wave-37).
- **wave-plan.yaml** — id `"37"` already populated (status: `pending`); flip to `done` post-build via `./scripts/wave-orchestrator.ps1 advance`.

---

## Verified Against Codebase (2026-05-04, HEAD `227240f`)

```
grep -n "DatabaseConnection\|ConnectionFactory" src/probos/protocols.py
  186: class DatabaseConnection(Protocol):
  223: class ConnectionFactory(Protocol):

grep -n "default_factory\|class SQLiteConnectionFactory" src/probos/storage/sqlite_factory.py
  10: class SQLiteConnectionFactory:
  28: default_factory = SQLiteConnectionFactory()

grep -n "class CognitiveJournal\|def __init__\|async def start\|connection_factory" src/probos/cognitive/journal.py
  109: class CognitiveJournal:
  112:     def __init__(self, db_path: str | None = None, connection_factory: ConnectionFactory | None = None) -> None:
  115:         self._connection_factory = connection_factory
  120:     async def start(self) -> None:
  126:         self._db = await self._connection_factory.connect(self.db_path)

grep -n "_CLASSIFICATION_LEVELS" src/probos/knowledge/records_store.py
  27: _CLASSIFICATION_LEVELS = {
  (lines 28-33: "private":0, "department":1, "ship":2, "fleet":3)

grep -n "cognitive_journal" src/probos/startup/communication.py
  309:         cognitive_journal = CognitiveJournal(

grep -n "self.cognitive_journal" src/probos/runtime.py
  425:         self.cognitive_journal: CognitiveJournal | None = None
  1608:         self.cognitive_journal = comm.cognitive_journal

grep -n "cognitive_journal\|class CognitiveJournalConfig" src/probos/config.py
  1735: class CognitiveJournalConfig(BaseModel):
  2051:     cognitive_journal: CognitiveJournalConfig = CognitiveJournalConfig()

grep -n "KnowledgeEdge\|knowledge_edges\|KnowledgeEntityType\|KnowledgeRelationType" src/probos/ tests/
  (zero hits — fully greenfield)

cat docs/research/unified-knowledge-graph.md | sed -n '104,141p'
  (knowledge_edges schema + recursive-CTE example as inlined in Section 1)

prompts/wave-plan.yaml id="37"
  title: "AD-687 v1 Knowledge Edge Store"
  prompt_paths: ["prompts/ad-687-knowledge-edge-store-v1.md"]
  issues_to_close: [381]
  status: pending  (do NOT touch in this draft commit)
```
