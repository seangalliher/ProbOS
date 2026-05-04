# AD-689 v1 — Edge Population from Existing ProbOS Data

**Status:** ready-to-build
**Wave:** 39
**Closes:** GH issue #383
**Phase:** Unified Knowledge Graph — Phase A (4-of-4)
**Dependencies:** AD-687 (Wave 37 — `KnowledgeEdgeStorage` + `SQLiteKnowledgeEdgeStore`), AD-688 (Wave 38 — Tier 6 Oracle reads, useful for verification but NOT a hard runtime dep)
**Estimated tests:** 12 new (≥10 floor)

---

## 1. Problem

`runtime.knowledge_edges` was provisioned in Wave 37 (AD-687) and made queryable via `OracleService` Tier 6 in Wave 38 (AD-688). The store works; the graph is empty. Tier 6 + post-merge `_expand_via_graph` therefore both return `[]` in production today. ProbOS already holds the four primary signal sources to bootstrap the graph:

1. **Ontology** — `runtime.ontology` carries the org-chart and crew assignments. Every `Post.reports_to` is a `REPORTS_TO` edge waiting to be materialized; every `Assignment` is a `MEMBER_OF` edge from agent to department.
2. **Hebbian** — `runtime.hebbian_router._weights` carries learned `(intent, agent, "intent")` triples for every successful intent-routing. A weight above some threshold is a `COMPETENT_IN` signal.
3. **Episodes** — `Episode.agent_ids` (cf. `types.py:411`) records who participated. Each entry is an `INVOLVED_IN` edge from agent to incident (using episode id as incident id).
4. **DECISIONS.md cross-references** — every `### AD-NNN` section in `DECISIONS.md` (and the four `decisions-era-*.md` archives) carries `**Related:** AD-X, AD-Y, ...` markdown anchors and `Closes GH issue #NNN` markers. These are `INFORMED_BY` and `RESOLVED_BY` edges between Decision nodes (and Decision→Incident for GH issues).

Without a one-shot population pass, the graph stays empty until Dream Step 10 (AD-690) starts producing edges incrementally — which itself depends on having seed data to compete against.

## 2. Decision

Ship a complete v1 (Captain "no trivial deferral" convention banked 2026-05-04, `/memories/repo/probos-notes.md`) covering all four sources in a single Builder cycle. Deliver:

- `EdgeBackfillService` async aggregator with one method per source plus `backfill_all()`.
- A new public read primitive on `EpisodicMemory` — `list_episodes(*, limit=None)` — so the backfill consumes a public API instead of `_collection.get(...)` (Open/Closed; Wave 5 conv #1).
- Deterministic `edge_id` per (source, source_id, relation, target, target_id) tuple via SHA-256 truncated to 32 hex chars. Combined with the AD-687 `INSERT OR REPLACE` upsert, re-runs are idempotent.
- `EdgeBackfillConfig` Pydantic model + `_wire_edge_backfill` async wirer in `startup/finalize.py` that runs on warm boot only when the table is empty (or `force=True`).
- `runtime.edge_backfill` public attribute (Wave 5 conv #1; collision-free greenfield).

Hard limit: NO LLM entity extraction, NO live event-driven incremental backfill, NO classification gating, NO federation sync. These are AD-690/691/692/693.

---

## 3. Verified Against Codebase (HEAD `46fa2cd`, 2026-05-04)

| Claim | Evidence |
|---|---|
| `KnowledgeEdgeStorage.add_edge` is INSERT OR REPLACE upsert keyed on `id` | `src/probos/knowledge/edges.py:240` (impl) + `:139` (Protocol). `INSERT OR REPLACE` at `:248`. |
| `KnowledgeEntityType` has AGENT, DEPARTMENT, INCIDENT, DECISION, CAPABILITY values | `src/probos/knowledge/edges.py:41–51`. |
| `KnowledgeRelationType` has REPORTS_TO, MEMBER_OF, COMPETENT_IN, INVOLVED_IN, INFORMED_BY, RESOLVED_BY values | `src/probos/knowledge/edges.py:54–66`. |
| `runtime.knowledge_edges` is a public attribute set in adoption phase | `src/probos/runtime.py:428` (slot) + `:1612` (assignment from `comm.knowledge_edges`). |
| `runtime.ontology.get_departments() / get_crew_agent_types() / get_post_for_agent() / get_all_assignments() / get_assignment_for_agent()` are public | `src/probos/ontology/service.py:114, 162, 165, 156, 174`. |
| `Post.reports_to: str \| None` and `Post.id: str` and `Post.department_id: str` exist | `src/probos/ontology/models.py:35–43`. |
| `Assignment.agent_type: str` + `Assignment.post_id: str` exist | `src/probos/ontology/models.py:46–51`. |
| `runtime.hebbian_router.all_weights_typed() -> dict[(source, target, rel_type), float]` is the public iterator | `src/probos/mesh/routing.py:248`. |
| `REL_INTENT = "intent"` constant for intent-→-agent weights | `src/probos/mesh/routing.py:28`. |
| `Episode` is a frozen dataclass with `id: str`, `agent_ids: list[str]`, `timestamp: float` | `src/probos/types.py:411–434`. |
| `EpisodicMemory._collection.get(include=["metadatas","documents"])` is the bulk read pattern reused for all-episodes; `_metadata_to_episode` reconstructs Episode from row | `src/probos/cognitive/episodic.py:1846` (existing `recall_by_intent` fallback uses the exact pattern). `_metadata_to_episode` referenced from `:1132/:2083`. |
| `DECISIONS.md` uses `**Related:** AD-X, AD-Y, BF-N, ...` pattern | `DECISIONS.md:1635, 1693, 1749, 1806, 1839, 1907, 1936, 1966, 1992, 2020` — 10 explicit hits. |
| `DECISIONS.md` and current era archive use `Closes GH issue #NNN` / `Closes #NNN` markers | `DECISIONS.md:28, 56, 129, 151, 178, 258`. |
| `### AD-NNN` section header pattern | `DECISIONS.md:13, 32, 60, 83, 105, 131, 208, 260, 287, 297, 317`. |
| Era archive files exist | workspace root has `decisions-era-1-genesis.md` … `decisions-era-4-evolution.md`. |
| Config gets `KnowledgeEdgesConfig` field at `SystemConfig` level | `src/probos/config.py:1743` (model) + `:2078` (field). |
| `_wire_self_distillation` is the async-wirer precedent in `finalize.py` | `src/probos/startup/finalize.py:384` (`async def _wire_self_distillation`) + `:585` (`if await _wire_self_distillation(runtime=runtime, config=config):`). |
| `_wire_chain_optimizer` is the kwarg-passthrough sync-wirer precedent | `src/probos/startup/finalize.py:214–237`. |
| **NO** `runtime.edge_backfill` attribute, **NO** `EdgeBackfillService`, **NO** `EdgeBackfillConfig` exist anywhere | `grep -nr "edge_backfill\|EdgeBackfillService\|EdgeBackfillConfig" src/ tests/` returns zero hits. Greenfield greenlit. |
| **DECISIONS pattern caveat:** Captain's spec mentioned `**Resolved by:** ...`. The actual structured marker in DECISIONS.md is **`Closes GH issue #NNN` / `Closes #NNN`** — `Resolved by:` is prose, not structured. Builder uses `Closes` as the RESOLVED_BY signal (Decision → Incident:gh-NNN). Documented in §6.3 below. |

---

## 4. Architecture

### 4.1 Module Layout

```
src/probos/knowledge/
├── __init__.py            # MODIFY — re-export EdgeBackfillService + EdgeBackfillResult
├── edges.py               # untouched (Wave 37)
└── backfill.py            # NEW — EdgeBackfillService + helpers
```

### 4.2 Public Surface (NEW `knowledge/backfill.py`)

```python
@dataclass(frozen=True)
class EdgeBackfillResult:
    """Counts of edges produced per source plus aggregate (AD-689)."""
    ontology: int = 0
    hebbian: int = 0
    episodes: int = 0
    decisions: int = 0
    started_at: float = 0.0
    duration_ms: float = 0.0

    @property
    def total(self) -> int:
        return self.ontology + self.hebbian + self.episodes + self.decisions

    def to_dict(self) -> dict[str, Any]: ...


class EdgeBackfillService:
    """One-shot + on-demand backfill of `knowledge_edges` from existing ProbOS data.

    Each backfill method is idempotent (deterministic edge IDs + INSERT OR REPLACE
    upserts at the storage layer). All four backfills are tier-2 log-and-degrade —
    a missing/failing source contributes 0 to the count and never raises into
    `backfill_all()`.
    """

    def __init__(
        self,
        *,
        knowledge_edges: KnowledgeEdgeStorage,
        ontology: Any,                     # ontology service (duck-typed)
        hebbian_router: Any,               # HebbianRouter (duck-typed)
        episodic_memory: Any | None,       # EpisodicMemory | None
        decisions_paths: list[Path],
        hebbian_threshold: float = 0.5,
    ) -> None: ...

    async def backfill_all(self) -> EdgeBackfillResult: ...
    async def backfill_ontology(self) -> int: ...
    async def backfill_hebbian(self, *, threshold: float | None = None) -> int: ...
    async def backfill_episodes(self, *, limit: int | None = None) -> int: ...
    async def backfill_decisions(self, *, paths: list[Path] | None = None) -> int: ...
```

### 4.3 Edge-ID Determinism Scheme

```python
import hashlib

def _deterministic_edge_id(
    source_type: KnowledgeEntityType,
    source_id: str,
    relation: KnowledgeRelationType,
    target_type: KnowledgeEntityType,
    target_id: str,
) -> str:
    payload = f"{source_type.value}|{source_id}|{relation.value}|{target_type.value}|{target_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
```

Combined with `SQLiteKnowledgeEdgeStore.add_edge` (`INSERT OR REPLACE` at `edges.py:248`), re-running any backfill emits the same `edge.id` for the same logical triple — the second insert overwrites the first row, leaving total row count unchanged. `created_at` is preserved by the dataclass default factory at the moment the `KnowledgeEdge` was constructed; on re-insert the new instance gets a fresh `updated_at`. (For perfect created_at preservation we would need to read-then-write; v1 accepts the small drift in `created_at` since `id` is the dedup key and total row count is what tests assert.)

All four backfills construct edges with `id=_deterministic_edge_id(...)` and `source_agent="edge_backfill"`, `source_duty=` one of `"ontology" | "hebbian" | "episodes" | "decisions"`.

### 4.4 Per-Source Mapping

| Source | Source entity / id | Relation | Target entity / id | Provenance |
|---|---|---|---|---|
| **Ontology — reports_to** | DECISION? no — POSITION mapped to DEPARTMENT entity? Use `AGENT` typed by `agent_type` of the assignee, OR the Post itself. **v1 choice:** edges are between `agent_type` strings — `AGENT:<subordinate_agent_type>` `REPORTS_TO` `AGENT:<superior_agent_type>`. Resolved by walking each Post's `reports_to` chain and mapping post → assignment(s) → agent_type via `ontology.get_agents_for_post(post_id)` (mirrors AD-630 pattern at `service.py:178`). Posts with no assignment are skipped. | `REPORTS_TO` | as left | `source_duty="ontology"` |
| **Ontology — member_of** | `AGENT:<agent_type>` for each `assignment` in `ontology.get_all_assignments()` | `MEMBER_OF` | `DEPARTMENT:<department_id>` (resolved via `ontology.get_post(assignment.post_id).department_id`) | `source_duty="ontology"` |
| **Hebbian — competent_in** | Walk `hebbian_router.all_weights_typed().items()`. For each `((source, target, rel_type), weight)` where `rel_type == REL_INTENT` AND `weight >= threshold`: emit `AGENT:<target>` `COMPETENT_IN` `CAPABILITY:<source>` (intent name as capability id). Skip below-threshold and skip non-intent rel_types (REL_AGENT/REL_SOCIAL/etc are out of scope for v1). | `COMPETENT_IN` | as left | `source_duty="hebbian"`, `confidence=min(weight, 1.0)`, `weight=min(weight, 1.0)` |
| **Episodes — involved_in** | For each Episode E (via the new `EpisodicMemory.list_episodes`): for each `agent_id` in `E.agent_ids`, emit `AGENT:<agent_id>` `INVOLVED_IN` `INCIDENT:<E.id>`. Empty `agent_ids` skipped. | `INVOLVED_IN` | as left | `source_duty="episodes"` |
| **DECISIONS — informed_by** | For each AD section `### AD-NNN[a-z]*` in any markdown path, parse `**Related:** ...` line. Extract every `AD-\d+[a-z]*` token (regex `r"AD-\d+[a-z]?"`). Emit `DECISION:AD-<src>` `INFORMED_BY` `DECISION:AD-<other>` per related token. Self-references skipped. | `INFORMED_BY` | as left | `source_duty="decisions"` |
| **DECISIONS — resolved_by** | Within the same AD section, scan body for `Closes GH issue #(\d+)` and `Closes #(\d+)` (case-insensitive). Emit `DECISION:AD-<src>` `RESOLVED_BY` `INCIDENT:gh-<n>`. Direction: a Decision *resolves* an Incident — semantically the Incident is *resolved by* the Decision, but the AD-687 enum reads `RESOLVED_BY` from the Decision side, so source=DECISION, target=INCIDENT, relation=RESOLVED_BY is consistent with how the relation was named in the Wave 37 enum (10-relation list). | `RESOLVED_BY` | as left | `source_duty="decisions"` |

> **Naming note (architect call):** `KnowledgeRelationType.RESOLVED_BY` is the only relation in the Wave 37 enum that reads naturally with the *target* as the resolver. We pick the source-DECISION, target-INCIDENT direction here because (a) DECISIONS.md anchors the marker on the Decision side, (b) the AD-688 Tier 6 entity-substring scoring works equally well from either direction (`find_edges(source_id=...)` and `find_edges(target_id=...)` both consulted), and (c) reversing later is one ALTER statement on `source_type`/`target_id` columns rather than a schema change. Documented here so the Builder doesn't second-guess.

### 4.5 New Public Method on `EpisodicMemory`

The backfill MUST NOT reach `_collection` directly (Open/Closed; Demeter). Add a small public read primitive that mirrors the existing `recent()` pattern (`episodic.py:1869-`):

```python
async def list_episodes(self, *, limit: int | None = None) -> list[Episode]:
    """AD-689: Return episodes ordered by timestamp DESC.

    Used by EdgeBackfillService.backfill_episodes to walk the full collection
    once. Returns [] if the collection is unavailable. ``limit=None`` returns
    all rows; pass an int to cap the slice.
    """
    if not self._collection:
        return []
    try:
        result = self._collection.get(include=["metadatas", "documents"])
    except Exception:
        logger.debug("AD-689: list_episodes ChromaDB query failed", exc_info=True)
        return []
    if not result or not result.get("ids"):
        return []
    paired = list(zip(
        result["ids"],
        result.get("metadatas") or [{}] * len(result["ids"]),
        result.get("documents") or [""] * len(result["ids"]),
    ))
    paired.sort(key=lambda x: (x[1] or {}).get("timestamp", 0), reverse=True)
    if limit is not None and limit >= 0:
        paired = paired[:limit]
    out: list[Episode] = []
    for ep_id, meta, doc in paired:
        try:
            out.append(self._metadata_to_episode(ep_id, doc or "", meta or {}))
        except Exception:
            logger.debug("AD-689: failed to reconstruct episode %s", ep_id, exc_info=True)
            continue
    return out
```

### 4.6 Pydantic Config (`config.py`)

Adjacent to `KnowledgeEdgesConfig` (currently at `config.py:1743`), introduce:

```python
class EdgeBackfillConfig(BaseModel):
    """AD-689: One-shot backfill of `knowledge_edges` from existing ProbOS data.

    Default ``enabled=True`` mirrors `KnowledgeEdgesConfig` rationale — the
    backfill is a no-op once the table has any rows (idempotency-by-row-count
    guard at warm boot). The first cold boot after AD-689 lands will populate
    the graph; subsequent boots see ``len > 0`` and skip.
    """
    enabled: bool = True
    run_on_warm_boot: bool = True
    hebbian_threshold: float = 0.5
    force: bool = False
    decisions_paths: list[str] = Field(
        default_factory=lambda: [
            "DECISIONS.md",
            "decisions-era-1-genesis.md",
            "decisions-era-2-emergence.md",
            "decisions-era-3-product.md",
            "decisions-era-4-evolution.md",
        ]
    )

    @field_validator("hebbian_threshold")
    @classmethod
    def _check_threshold(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("edge_backfill.hebbian_threshold must be in [0.0, 1.0]")
        return v
```

Add field to `SystemConfig` immediately after `knowledge_edges` (currently at `config.py:2078`):

```python
edge_backfill: EdgeBackfillConfig = Field(default_factory=EdgeBackfillConfig)  # AD-689
```

### 4.7 Wirer (`startup/finalize.py`)

Async wirer (mirrors `_wire_self_distillation` at `:384`):

```python
async def _wire_edge_backfill(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-689: Wire EdgeBackfillService and run a one-shot backfill on warm boot
    if the knowledge_edges table is empty (or force=True).
    """
    cfg = getattr(config, "edge_backfill", None)
    if not cfg or not cfg.enabled:
        return False

    knowledge_edges = getattr(runtime, "knowledge_edges", None)
    if knowledge_edges is None:
        logger.debug("AD-689: knowledge_edges unavailable; skipping backfill")
        return False

    from pathlib import Path
    from probos.knowledge.backfill import EdgeBackfillService

    service = EdgeBackfillService(
        knowledge_edges=knowledge_edges,
        ontology=getattr(runtime, "ontology", None),
        hebbian_router=getattr(runtime, "hebbian_router", None),
        episodic_memory=getattr(runtime, "episodic_memory", None),
        decisions_paths=[Path(p) for p in cfg.decisions_paths],
        hebbian_threshold=cfg.hebbian_threshold,
    )
    runtime.edge_backfill = service  # public attribute (Wave 5 conv #1)

    if not cfg.run_on_warm_boot:
        logger.info("AD-689: EdgeBackfillService wired; warm-boot run disabled by config")
        return True

    # Idempotency guard: skip if rows already exist (unless forced).
    if not cfg.force:
        try:
            existing = await knowledge_edges.find_edges(limit=1)
        except Exception:
            existing = []
            logger.debug("AD-689: find_edges probe failed; will run backfill", exc_info=True)
        if existing:
            logger.info(
                "AD-689: knowledge_edges already populated; skipping warm-boot backfill "
                "(use edge_backfill.force=true to override)"
            )
            return True

    try:
        result = await service.backfill_all()
        logger.info(
            "AD-689: backfill complete (ontology=%d hebbian=%d episodes=%d decisions=%d total=%d duration=%.0fms)",
            result.ontology, result.hebbian, result.episodes, result.decisions,
            result.total, result.duration_ms,
        )
    except Exception:
        logger.warning("AD-689: warm-boot backfill failed", exc_info=True)
    return True
```

Call site inside `finalize_startup` immediately after the `_wire_chain_optimizer` block (around `finalize.py:585`, alongside the other infrastructure wirers — ordering: knowledge_edges adoption happens in communication phase BEFORE finalize, ontology/hebbian/episodic_memory all attached on runtime by the time finalize runs):

```python
if await _wire_edge_backfill(runtime=runtime, config=config):
    logger.info("AD-689: EdgeBackfillService v1 wired during finalization")
```

### 4.8 Runtime Slot Declaration (`runtime.py`)

Add in the late-init block (currently `runtime.py:425–432` neighborhood, immediately after `self.knowledge_edges`):

```python
# --- Edge Backfill Service (AD-689) ---
self.edge_backfill: Any = None  # EdgeBackfillService | None — wired in finalize phase
```

### 4.9 Re-exports (`knowledge/__init__.py`)

Append `EdgeBackfillResult`, `EdgeBackfillService` to the import list and `__all__`.

---

## 5. Implementation — SEARCH/REPLACE Blocks

### Section 1 — `src/probos/knowledge/backfill.py` (NEW FILE, ~330 lines)

Full file content. (Builder: write as-is; no SEARCH/REPLACE — it's greenfield.)

```python
"""Edge population from existing ProbOS data (AD-689).

One-shot + on-demand backfill of ``runtime.knowledge_edges`` from four
existing data sources: ontology (reports_to + member_of), Hebbian router
(competent_in above threshold), episodic memory (involved_in), and
DECISIONS markdown cross-references (informed_by + resolved_by).

Idempotent by deterministic edge IDs (SHA-256 of the typed-triple key) +
``KnowledgeEdgeStorage.add_edge`` INSERT OR REPLACE upsert at the storage
layer. Re-running any backfill leaves total row count unchanged.

All four backfills are tier-2 log-and-degrade — a missing/failing source
contributes 0 to the count and never raises into ``backfill_all()``.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEdgeStorage,
    KnowledgeEntityType,
    KnowledgeRelationType,
)
from probos.mesh.routing import REL_INTENT

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────

_RELATED_AD_PATTERN = re.compile(r"\bAD-(\d+[a-z]?)\b")
_RELATED_LINE_PATTERN = re.compile(r"^\s*\*\*Related:\*\*\s*(.+)$", re.MULTILINE)
_AD_SECTION_PATTERN = re.compile(
    r"^###\s+AD-(\d+[a-z]?)[^\n]*$",  # captures the AD ID at section header
    re.MULTILINE,
)
_CLOSES_PATTERN = re.compile(r"\bCloses\s+(?:GH\s+issue\s+)?#(\d+)\b", re.IGNORECASE)


def _deterministic_edge_id(
    source_type: KnowledgeEntityType,
    source_id: str,
    relation: KnowledgeRelationType,
    target_type: KnowledgeEntityType,
    target_id: str,
) -> str:
    """Stable 32-hex-char ID from the typed-triple key (AD-689)."""
    payload = f"{source_type.value}|{source_id}|{relation.value}|{target_type.value}|{target_id}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _make_edge(
    *,
    source_type: KnowledgeEntityType,
    source_id: str,
    relation: KnowledgeRelationType,
    target_type: KnowledgeEntityType,
    target_id: str,
    source_duty: str,
    confidence: float = 1.0,
    weight: float = 1.0,
) -> KnowledgeEdge:
    return KnowledgeEdge(
        source_type=source_type,
        source_id=source_id,
        relation=relation,
        target_type=target_type,
        target_id=target_id,
        id=_deterministic_edge_id(source_type, source_id, relation, target_type, target_id),
        confidence=max(0.0, min(1.0, confidence)),
        weight=max(0.0, min(1.0, weight)),
        source_agent="edge_backfill",
        source_duty=source_duty,
    )


# ── Result dataclass ──────────────────────────────────────────────


@dataclass(frozen=True)
class EdgeBackfillResult:
    """Counts of edges produced per source plus aggregate (AD-689)."""

    ontology: int = 0
    hebbian: int = 0
    episodes: int = 0
    decisions: int = 0
    started_at: float = 0.0
    duration_ms: float = 0.0

    @property
    def total(self) -> int:
        return self.ontology + self.hebbian + self.episodes + self.decisions

    def to_dict(self) -> dict[str, Any]:
        return {
            "ontology": self.ontology,
            "hebbian": self.hebbian,
            "episodes": self.episodes,
            "decisions": self.decisions,
            "total": self.total,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
        }


# ── Service ───────────────────────────────────────────────────────


class EdgeBackfillService:
    """One-shot + on-demand backfill of ``knowledge_edges`` (AD-689)."""

    def __init__(
        self,
        *,
        knowledge_edges: KnowledgeEdgeStorage,
        ontology: Any,
        hebbian_router: Any,
        episodic_memory: Any | None,
        decisions_paths: list[Path],
        hebbian_threshold: float = 0.5,
    ) -> None:
        self._edges = knowledge_edges
        self._ontology = ontology
        self._hebbian = hebbian_router
        self._episodic = episodic_memory
        self._decisions_paths = list(decisions_paths)
        self._hebbian_threshold = hebbian_threshold

    # ── Aggregator ────────────────────────────────────────────

    async def backfill_all(self) -> EdgeBackfillResult:
        started_at = time.time()
        ontology_n = await self.backfill_ontology()
        hebbian_n = await self.backfill_hebbian()
        episodes_n = await self.backfill_episodes()
        decisions_n = await self.backfill_decisions()
        return EdgeBackfillResult(
            ontology=ontology_n,
            hebbian=hebbian_n,
            episodes=episodes_n,
            decisions=decisions_n,
            started_at=started_at,
            duration_ms=(time.time() - started_at) * 1000.0,
        )

    # ── Source 1: Ontology ────────────────────────────────────

    async def backfill_ontology(self) -> int:
        if self._ontology is None:
            return 0
        count = 0
        try:
            assignments = list(self._ontology.get_all_assignments())
        except Exception:
            logger.warning("AD-689: ontology.get_all_assignments failed", exc_info=True)
            return 0

        # Build agent_type → post_id map for reports_to resolution.
        agent_by_post: dict[str, list[str]] = {}
        for a in assignments:
            agent_by_post.setdefault(a.post_id, []).append(a.agent_type)

        # member_of edges: agent_type → department
        for a in assignments:
            try:
                post = self._ontology.get_post(a.post_id)
            except Exception:
                continue
            if post is None or not post.department_id:
                continue
            count += await self._add(
                _make_edge(
                    source_type=KnowledgeEntityType.AGENT,
                    source_id=a.agent_type,
                    relation=KnowledgeRelationType.MEMBER_OF,
                    target_type=KnowledgeEntityType.DEPARTMENT,
                    target_id=post.department_id,
                    source_duty="ontology",
                )
            )

        # reports_to edges: agent_type(subordinate) → agent_type(superior)
        try:
            posts = self._ontology.get_posts()
        except Exception:
            posts = []
        for post in posts:
            if not post.reports_to:
                continue
            sub_agents = agent_by_post.get(post.id, [])
            sup_agents = agent_by_post.get(post.reports_to, [])
            for sub in sub_agents:
                for sup in sup_agents:
                    if sub == sup:
                        continue
                    count += await self._add(
                        _make_edge(
                            source_type=KnowledgeEntityType.AGENT,
                            source_id=sub,
                            relation=KnowledgeRelationType.REPORTS_TO,
                            target_type=KnowledgeEntityType.AGENT,
                            target_id=sup,
                            source_duty="ontology",
                        )
                    )
        return count

    # ── Source 2: Hebbian ─────────────────────────────────────

    async def backfill_hebbian(self, *, threshold: float | None = None) -> int:
        if self._hebbian is None:
            return 0
        thr = threshold if threshold is not None else self._hebbian_threshold
        try:
            weights = self._hebbian.all_weights_typed()
        except Exception:
            logger.warning("AD-689: hebbian.all_weights_typed failed", exc_info=True)
            return 0
        count = 0
        for (source, target, rel_type), weight in weights.items():
            if rel_type != REL_INTENT:
                continue
            if weight < thr:
                continue
            # source = intent name, target = agent_id
            count += await self._add(
                _make_edge(
                    source_type=KnowledgeEntityType.AGENT,
                    source_id=str(target),
                    relation=KnowledgeRelationType.COMPETENT_IN,
                    target_type=KnowledgeEntityType.CAPABILITY,
                    target_id=str(source),
                    source_duty="hebbian",
                    confidence=float(weight),
                    weight=float(weight),
                )
            )
        return count

    # ── Source 3: Episodes ────────────────────────────────────

    async def backfill_episodes(self, *, limit: int | None = None) -> int:
        if self._episodic is None:
            return 0
        try:
            episodes = await self._episodic.list_episodes(limit=limit)
        except Exception:
            logger.warning("AD-689: episodic.list_episodes failed", exc_info=True)
            return 0
        count = 0
        for ep in episodes:
            agent_ids = list(getattr(ep, "agent_ids", []) or [])
            ep_id = getattr(ep, "id", None)
            if not ep_id or not agent_ids:
                continue
            for aid in agent_ids:
                if not aid:
                    continue
                count += await self._add(
                    _make_edge(
                        source_type=KnowledgeEntityType.AGENT,
                        source_id=str(aid),
                        relation=KnowledgeRelationType.INVOLVED_IN,
                        target_type=KnowledgeEntityType.INCIDENT,
                        target_id=str(ep_id),
                        source_duty="episodes",
                    )
                )
        return count

    # ── Source 4: DECISIONS ───────────────────────────────────

    async def backfill_decisions(self, *, paths: list[Path] | None = None) -> int:
        targets = paths if paths is not None else self._decisions_paths
        count = 0
        for path in targets:
            try:
                if not path.exists():
                    continue
                text = path.read_text(encoding="utf-8")
            except Exception:
                logger.debug("AD-689: failed reading %s", path, exc_info=True)
                continue
            count += await self._scan_decisions_text(text)
        return count

    async def _scan_decisions_text(self, text: str) -> int:
        # Split into AD sections by section-header lines.
        matches = list(_AD_SECTION_PATTERN.finditer(text))
        if not matches:
            return 0
        count = 0
        for i, m in enumerate(matches):
            ad_id = m.group(1)
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end]
            # informed_by from **Related:** lines
            for related_line in _RELATED_LINE_PATTERN.findall(body):
                for other in _RELATED_AD_PATTERN.findall(related_line):
                    if other == ad_id:
                        continue
                    count += await self._add(
                        _make_edge(
                            source_type=KnowledgeEntityType.DECISION,
                            source_id=f"AD-{ad_id}",
                            relation=KnowledgeRelationType.INFORMED_BY,
                            target_type=KnowledgeEntityType.DECISION,
                            target_id=f"AD-{other}",
                            source_duty="decisions",
                        )
                    )
            # resolved_by from Closes #N / Closes GH issue #N
            for issue_num in _CLOSES_PATTERN.findall(body):
                count += await self._add(
                    _make_edge(
                        source_type=KnowledgeEntityType.DECISION,
                        source_id=f"AD-{ad_id}",
                        relation=KnowledgeRelationType.RESOLVED_BY,
                        target_type=KnowledgeEntityType.INCIDENT,
                        target_id=f"gh-{issue_num}",
                        source_duty="decisions",
                    )
                )
        return count

    # ── Internal ──────────────────────────────────────────────

    async def _add(self, edge: KnowledgeEdge) -> int:
        try:
            await self._edges.add_edge(edge)
            return 1
        except Exception:
            logger.debug("AD-689: add_edge failed for id=%s", edge.id, exc_info=True)
            return 0
```

### Section 2 — `src/probos/knowledge/__init__.py` MODIFY

```
===SEARCH===
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
===REPLACE===
from probos.knowledge.backfill import EdgeBackfillResult, EdgeBackfillService
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
    "EdgeBackfillResult",
    "EdgeBackfillService",
    "KnowledgeEdge",
    "KnowledgeEdgeStorage",
    "KnowledgeEdgeStore",
    "KnowledgeEntityType",
    "KnowledgeRelationType",
    "KnowledgeStore",
    "SQLiteKnowledgeEdgeStore",
]
===END REPLACE===
```

### Section 3 — `src/probos/cognitive/episodic.py` MODIFY (add `list_episodes`)

Insert immediately AFTER the existing `get_by_ids` method (currently at `episodic.py:1132–1166`). Use the existing `recent()` method at `:1869` as the structural sibling.

```
===SEARCH===
    async def get_by_ids(self, episode_ids: list[str]) -> list[Episode]:
        """AD-657: Fetch full Episode objects by ID, preserving input order.

        Missing IDs (e.g., evicted by AD-593 activation pruning) are silently
        omitted — caller treats absence as graceful degradation, not error.
        """
===REPLACE===
    async def list_episodes(self, *, limit: int | None = None) -> list[Episode]:
        """AD-689: Return episodes ordered by timestamp DESC.

        Used by EdgeBackfillService.backfill_episodes to walk the full
        collection once. Returns [] if the collection is unavailable.
        ``limit=None`` returns all rows; pass a non-negative int to cap
        the slice. Missing/malformed rows are silently skipped.
        """
        if not self._collection:
            return []
        try:
            result = self._collection.get(include=["metadatas", "documents"])
        except Exception:
            logger.debug("AD-689: list_episodes ChromaDB query failed", exc_info=True)
            return []
        if not result or not result.get("ids"):
            return []
        ids = result["ids"]
        metas = result.get("metadatas") or [{} for _ in ids]
        docs = result.get("documents") or ["" for _ in ids]
        paired = list(zip(ids, metas, docs))
        paired.sort(key=lambda x: (x[1] or {}).get("timestamp", 0), reverse=True)
        if limit is not None and limit >= 0:
            paired = paired[:limit]
        out: list[Episode] = []
        for ep_id, meta, doc in paired:
            try:
                out.append(self._metadata_to_episode(ep_id, doc or "", meta or {}))
            except Exception:
                logger.debug("AD-689: failed to reconstruct episode %s", ep_id, exc_info=True)
                continue
        return out

    async def get_by_ids(self, episode_ids: list[str]) -> list[Episode]:
        """AD-657: Fetch full Episode objects by ID, preserving input order.

        Missing IDs (e.g., evicted by AD-593 activation pruning) are silently
        omitted — caller treats absence as graceful degradation, not error.
        """
===END REPLACE===
```

### Section 4 — `src/probos/config.py` MODIFY (add `EdgeBackfillConfig`)

```
===SEARCH===
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
===REPLACE===
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


class EdgeBackfillConfig(BaseModel):
    """AD-689: One-shot backfill of ``knowledge_edges`` from existing data.

    Default ``enabled=True`` follows the same precedent as
    ``KnowledgeEdgesConfig`` — the warm-boot wirer is a no-op once the table
    has any rows (idempotency-by-row-count guard). The first cold boot after
    AD-689 lands populates the graph from ontology/Hebbian/episodes/DECISIONS;
    subsequent boots see ``find_edges(limit=1) != []`` and skip.
    """
    enabled: bool = True
    run_on_warm_boot: bool = True
    hebbian_threshold: float = 0.5
    force: bool = False
    decisions_paths: list[str] = Field(
        default_factory=lambda: [
            "DECISIONS.md",
            "decisions-era-1-genesis.md",
            "decisions-era-2-emergence.md",
            "decisions-era-3-product.md",
            "decisions-era-4-evolution.md",
        ]
    )

    @field_validator("hebbian_threshold")
    @classmethod
    def _check_threshold(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("edge_backfill.hebbian_threshold must be in [0.0, 1.0]")
        return v
===END REPLACE===
```

Then add the field to `SystemConfig` immediately after `knowledge_edges` (currently `config.py:2078`):

```
===SEARCH===
    knowledge_edges: KnowledgeEdgesConfig = Field(default_factory=KnowledgeEdgesConfig)  # AD-687
===REPLACE===
    knowledge_edges: KnowledgeEdgesConfig = Field(default_factory=KnowledgeEdgesConfig)  # AD-687
    edge_backfill: EdgeBackfillConfig = Field(default_factory=EdgeBackfillConfig)  # AD-689
===END REPLACE===
```

### Section 5 — `src/probos/runtime.py` MODIFY (add slot)

```
===SEARCH===
        # --- Knowledge Edge Store (AD-687) ---
        self.knowledge_edges: Any = None  # SQLiteKnowledgeEdgeStore | None — Any to avoid circular import

        # --- Counselor Profile Store (AD-503) ---
===REPLACE===
        # --- Knowledge Edge Store (AD-687) ---
        self.knowledge_edges: Any = None  # SQLiteKnowledgeEdgeStore | None — Any to avoid circular import

        # --- Edge Backfill Service (AD-689) ---
        self.edge_backfill: Any = None  # EdgeBackfillService | None — wired in finalize phase

        # --- Counselor Profile Store (AD-503) ---
===END REPLACE===
```

### Section 6 — `src/probos/startup/finalize.py` MODIFY

Add the wirer function. Place immediately after `_wire_chain_optimizer` (currently ends at `:237`):

```
===SEARCH===
def _wire_causal_reasoner(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-660 v1: Wire CausalReasoner template-fill service."""
===REPLACE===
async def _wire_edge_backfill(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-689: Wire EdgeBackfillService and run a one-shot backfill on warm boot
    if the knowledge_edges table is empty (or force=True)."""
    cfg = getattr(config, "edge_backfill", None)
    if not cfg or not cfg.enabled:
        return False

    knowledge_edges = getattr(runtime, "knowledge_edges", None)
    if knowledge_edges is None:
        logger.debug("AD-689: knowledge_edges unavailable; skipping backfill")
        return False

    from pathlib import Path
    from probos.knowledge.backfill import EdgeBackfillService

    service = EdgeBackfillService(
        knowledge_edges=knowledge_edges,
        ontology=getattr(runtime, "ontology", None),
        hebbian_router=getattr(runtime, "hebbian_router", None),
        episodic_memory=getattr(runtime, "episodic_memory", None),
        decisions_paths=[Path(p) for p in cfg.decisions_paths],
        hebbian_threshold=cfg.hebbian_threshold,
    )
    runtime.edge_backfill = service  # public attribute (Wave 5 conv #1)

    if not cfg.run_on_warm_boot:
        logger.info("AD-689: EdgeBackfillService wired; warm-boot run disabled by config")
        return True

    if not cfg.force:
        try:
            existing = await knowledge_edges.find_edges(limit=1)
        except Exception:
            existing = []
            logger.debug("AD-689: find_edges probe failed; will run backfill", exc_info=True)
        if existing:
            logger.info(
                "AD-689: knowledge_edges already populated; skipping warm-boot backfill "
                "(use edge_backfill.force=true to override)"
            )
            return True

    try:
        result = await service.backfill_all()
        logger.info(
            "AD-689: backfill complete (ontology=%d hebbian=%d episodes=%d "
            "decisions=%d total=%d duration=%.0fms)",
            result.ontology, result.hebbian, result.episodes, result.decisions,
            result.total, result.duration_ms,
        )
    except Exception:
        logger.warning("AD-689: warm-boot backfill failed", exc_info=True)
    return True


def _wire_causal_reasoner(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-660 v1: Wire CausalReasoner template-fill service."""
===END REPLACE===
```

Then call the wirer inside `finalize_startup`. Insert immediately after the `_wire_chain_optimizer` call site:

```
===SEARCH===
    if _wire_chain_optimizer(runtime=runtime, config=config):
        logger.info("AD-659: ChainOptimizer v1 wired during finalization")

    if _wire_causal_reasoner(runtime=runtime, config=config):
        logger.info("AD-660: CausalReasoner v1 wired during finalization")
===REPLACE===
    if _wire_chain_optimizer(runtime=runtime, config=config):
        logger.info("AD-659: ChainOptimizer v1 wired during finalization")

    if await _wire_edge_backfill(runtime=runtime, config=config):
        logger.info("AD-689: EdgeBackfillService v1 wired during finalization")

    if _wire_causal_reasoner(runtime=runtime, config=config):
        logger.info("AD-660: CausalReasoner v1 wired during finalization")
===END REPLACE===
```

### Section 7 — `tests/test_ad689_edge_backfill.py` (NEW FILE)

12 focused tests. Builder writes the file from this skeleton (full bodies — no placeholders).

```python
"""AD-689 v1: Edge population from existing data — Wave 39."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.knowledge.backfill import (
    EdgeBackfillResult,
    EdgeBackfillService,
    _deterministic_edge_id,
)
from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEntityType,
    KnowledgeRelationType,
    SQLiteKnowledgeEdgeStore,
)
from probos.mesh.routing import REL_INTENT, REL_AGENT
from probos.types import Episode


# ── Fixtures ─────────────────────────────────────────────────────


def _stub_ontology(
    *,
    assignments: list[SimpleNamespace],
    posts: list[SimpleNamespace],
) -> MagicMock:
    ont = MagicMock()
    ont.get_all_assignments.return_value = assignments
    ont.get_posts.return_value = posts
    by_id = {p.id: p for p in posts}
    ont.get_post.side_effect = lambda pid: by_id.get(pid)
    return ont


@pytest.fixture
async def edge_store(tmp_path: Path):
    store = SQLiteKnowledgeEdgeStore(db_path=str(tmp_path / "edges.sqlite"))
    await store.start()
    yield store
    await store.stop()


# ── Test 1: Service shape ────────────────────────────────────────


def test_service_shape_and_result_dataclass():
    res = EdgeBackfillResult(ontology=1, hebbian=2, episodes=3, decisions=4)
    assert res.total == 10
    d = res.to_dict()
    assert d["total"] == 10 and d["ontology"] == 1
    # Frozen — re-assignment forbidden.
    with pytest.raises(Exception):
        res.ontology = 99  # type: ignore[misc]
    # Constructor surface — kw-only construction works with stubs.
    svc = EdgeBackfillService(
        knowledge_edges=MagicMock(),
        ontology=None,
        hebbian_router=None,
        episodic_memory=None,
        decisions_paths=[],
        hebbian_threshold=0.7,
    )
    assert svc._hebbian_threshold == 0.7


# ── Test 2: backfill_ontology ────────────────────────────────────


@pytest.mark.asyncio
async def test_backfill_ontology_emits_reports_to_and_member_of(edge_store):
    captain_post = SimpleNamespace(
        id="captain", department_id="bridge", reports_to=None,
    )
    chief_eng_post = SimpleNamespace(
        id="chief_engineer", department_id="engineering", reports_to="captain",
    )
    captain_assign = SimpleNamespace(agent_type="captain", post_id="captain")
    chief_assign = SimpleNamespace(agent_type="engineering_officer", post_id="chief_engineer")
    ont = _stub_ontology(
        assignments=[captain_assign, chief_assign],
        posts=[captain_post, chief_eng_post],
    )
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=ont,
        hebbian_router=None,
        episodic_memory=None,
        decisions_paths=[],
    )
    n = await svc.backfill_ontology()
    # 2 member_of (one per assignment) + 1 reports_to (engineering_officer→captain)
    assert n == 3
    edges = await edge_store.find_edges(limit=100)
    relations = sorted(e.relation.value for e in edges)
    assert relations == ["member_of", "member_of", "reports_to"]
    rep = next(e for e in edges if e.relation == KnowledgeRelationType.REPORTS_TO)
    assert rep.source_id == "engineering_officer" and rep.target_id == "captain"
    assert rep.source_agent == "edge_backfill" and rep.source_duty == "ontology"


# ── Test 3: backfill_hebbian respects threshold ──────────────────


@pytest.mark.asyncio
async def test_backfill_hebbian_filters_below_threshold(edge_store):
    router = MagicMock()
    router.all_weights_typed.return_value = {
        ("ship.scan", "agent_alpha", REL_INTENT): 0.7,
        ("ship.scan", "agent_beta", REL_INTENT): 0.3,   # below default 0.5
        ("ship.report", "agent_alpha", REL_INTENT): 0.6,
        ("agent_alpha", "agent_beta", REL_AGENT): 0.9,  # non-intent — skipped
    }
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=router,
        episodic_memory=None,
        decisions_paths=[],
    )
    n = await svc.backfill_hebbian()
    assert n == 2  # 0.7 + 0.6, the 0.3 and REL_AGENT excluded
    edges = await edge_store.find_edges(limit=100)
    assert all(e.relation == KnowledgeRelationType.COMPETENT_IN for e in edges)
    capabilities = sorted(e.target_id for e in edges)
    assert capabilities == ["ship.report", "ship.scan"]


# ── Test 4: backfill_hebbian custom threshold ────────────────────


@pytest.mark.asyncio
async def test_backfill_hebbian_custom_threshold(edge_store):
    router = MagicMock()
    router.all_weights_typed.return_value = {
        ("a", "x", REL_INTENT): 0.4,
        ("b", "x", REL_INTENT): 0.6,
    }
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=router,
        episodic_memory=None,
        decisions_paths=[],
        hebbian_threshold=0.5,
    )
    # Override at call site — tighter threshold drops both.
    n = await svc.backfill_hebbian(threshold=0.7)
    assert n == 0
    # Looser threshold catches both.
    n = await svc.backfill_hebbian(threshold=0.1)
    assert n == 2


# ── Test 5: backfill_episodes ────────────────────────────────────


@pytest.mark.asyncio
async def test_backfill_episodes_emits_involved_in_per_agent(edge_store):
    ep1 = Episode(id="ep-1", timestamp=time.time(), user_input="x", agent_ids=["alpha"])
    ep2 = Episode(id="ep-2", timestamp=time.time(), user_input="y", agent_ids=["alpha", "beta"])
    ep3 = Episode(id="ep-3", timestamp=time.time(), user_input="z", agent_ids=[])
    em = MagicMock()
    em.list_episodes = AsyncMock(return_value=[ep1, ep2, ep3])
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=None,
        episodic_memory=em,
        decisions_paths=[],
    )
    n = await svc.backfill_episodes()
    assert n == 3  # 1 + 2 + 0
    edges = await edge_store.find_edges(limit=100)
    assert all(e.relation == KnowledgeRelationType.INVOLVED_IN for e in edges)
    incidents = sorted(e.target_id for e in edges)
    assert incidents == ["ep-1", "ep-2", "ep-2"]


# ── Test 6: backfill_decisions — Related: ────────────────────────


@pytest.mark.asyncio
async def test_backfill_decisions_parses_related_lines(tmp_path, edge_store):
    md = tmp_path / "decisions.md"
    md.write_text(
        "# Header\n\n"
        "### AD-688 v1: Oracle Graph Integration (2026-05-04)\n\n"
        "Some prose.\n\n"
        "**Related:** AD-686 (Tier 5), AD-687 (Edge Store), BF-100 (noise)\n\n"
        "More prose.\n\n"
        "### AD-687 v1: Knowledge Edge Store (2026-05-04)\n\n"
        "**Related:** AD-688\n",
        encoding="utf-8",
    )
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=None,
        episodic_memory=None,
        decisions_paths=[md],
    )
    n = await svc.backfill_decisions()
    assert n == 3  # 688→686, 688→687, 687→688
    edges = await edge_store.find_edges(
        relation=KnowledgeRelationType.INFORMED_BY, limit=100,
    )
    pairs = sorted((e.source_id, e.target_id) for e in edges)
    assert pairs == [("AD-687", "AD-688"), ("AD-688", "AD-686"), ("AD-688", "AD-687")]


# ── Test 7: backfill_decisions — Closes #N ───────────────────────


@pytest.mark.asyncio
async def test_backfill_decisions_parses_closes_markers(tmp_path, edge_store):
    md = tmp_path / "decisions.md"
    md.write_text(
        "### AD-688 v1: Oracle Graph (2026-05-04)\n\n"
        "Some prose. Closes GH issue #382.\n\n"
        "### AD-689 v1: Edge Population (2026-05-04)\n\n"
        "Closes #383.\n",
        encoding="utf-8",
    )
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=None,
        episodic_memory=None,
        decisions_paths=[md],
    )
    n = await svc.backfill_decisions()
    assert n == 2
    edges = await edge_store.find_edges(
        relation=KnowledgeRelationType.RESOLVED_BY, limit=100,
    )
    pairs = sorted((e.source_id, e.target_id) for e in edges)
    assert pairs == [("AD-688", "gh-382"), ("AD-689", "gh-383")]


# ── Test 8: backfill_all aggregates ──────────────────────────────


@pytest.mark.asyncio
async def test_backfill_all_aggregates_counts(tmp_path, edge_store):
    md = tmp_path / "d.md"
    md.write_text(
        "### AD-1 v1: x\n\n**Related:** AD-2\n\n### AD-2 v1: y\n\nCloses #99\n",
        encoding="utf-8",
    )
    captain = SimpleNamespace(id="captain", department_id="bridge", reports_to=None)
    eng = SimpleNamespace(id="eng", department_id="engineering", reports_to="captain")
    a1 = SimpleNamespace(agent_type="captain", post_id="captain")
    a2 = SimpleNamespace(agent_type="engineer", post_id="eng")
    ont = _stub_ontology(assignments=[a1, a2], posts=[captain, eng])

    router = MagicMock()
    router.all_weights_typed.return_value = {("intent.a", "engineer", REL_INTENT): 0.8}

    em = MagicMock()
    em.list_episodes = AsyncMock(return_value=[
        Episode(id="ep-1", timestamp=1.0, user_input="q", agent_ids=["captain"])
    ])

    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=ont,
        hebbian_router=router,
        episodic_memory=em,
        decisions_paths=[md],
    )
    res = await svc.backfill_all()
    # ontology: 2 member_of + 1 reports_to = 3
    # hebbian: 1
    # episodes: 1
    # decisions: 1 informed_by + 1 resolved_by = 2
    assert res.ontology == 3
    assert res.hebbian == 1
    assert res.episodes == 1
    assert res.decisions == 2
    assert res.total == 7
    assert res.duration_ms >= 0.0


# ── Test 9: idempotency ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_backfill_all_is_idempotent(tmp_path, edge_store):
    md = tmp_path / "d.md"
    md.write_text("### AD-1 v1: x\n\n**Related:** AD-2\n", encoding="utf-8")
    svc = EdgeBackfillService(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=None,
        episodic_memory=None,
        decisions_paths=[md],
    )
    res1 = await svc.backfill_all()
    edges_after_first = await edge_store.find_edges(limit=1000)
    res2 = await svc.backfill_all()
    edges_after_second = await edge_store.find_edges(limit=1000)
    assert res1.total == res2.total == 1
    assert len(edges_after_first) == len(edges_after_second) == 1
    # Same deterministic ID
    assert edges_after_first[0].id == edges_after_second[0].id
    # Validate determinism helper directly.
    expected = _deterministic_edge_id(
        KnowledgeEntityType.DECISION, "AD-1",
        KnowledgeRelationType.INFORMED_BY,
        KnowledgeEntityType.DECISION, "AD-2",
    )
    assert edges_after_first[0].id == expected


# ── Test 10: warm-boot wirer skips on populated store ────────────


@pytest.mark.asyncio
async def test_wirer_skips_when_rows_exist(tmp_path, edge_store):
    # Pre-populate.
    pre = KnowledgeEdge(
        source_type=KnowledgeEntityType.AGENT,
        source_id="x",
        relation=KnowledgeRelationType.MEMBER_OF,
        target_type=KnowledgeEntityType.DEPARTMENT,
        target_id="y",
    )
    await edge_store.add_edge(pre)
    from probos.config import EdgeBackfillConfig
    from probos.startup.finalize import _wire_edge_backfill

    cfg = EdgeBackfillConfig(enabled=True, run_on_warm_boot=True, force=False)
    sys_cfg = SimpleNamespace(edge_backfill=cfg)
    rt = SimpleNamespace(
        knowledge_edges=edge_store,
        ontology=None,
        hebbian_router=None,
        episodic_memory=None,
        edge_backfill=None,
    )
    ok = await _wire_edge_backfill(runtime=rt, config=sys_cfg)
    assert ok is True
    assert rt.edge_backfill is not None
    # Row count unchanged — wirer detected populated store and skipped.
    edges = await edge_store.find_edges(limit=100)
    assert len(edges) == 1


# ── Test 11: warm-boot wirer runs on empty store ─────────────────


@pytest.mark.asyncio
async def test_wirer_runs_when_empty(tmp_path, edge_store):
    captain = SimpleNamespace(id="captain", department_id="bridge", reports_to=None)
    a = SimpleNamespace(agent_type="captain", post_id="captain")
    ont = _stub_ontology(assignments=[a], posts=[captain])
    from probos.config import EdgeBackfillConfig
    from probos.startup.finalize import _wire_edge_backfill

    cfg = EdgeBackfillConfig(enabled=True, run_on_warm_boot=True, force=False)
    sys_cfg = SimpleNamespace(edge_backfill=cfg)
    rt = SimpleNamespace(
        knowledge_edges=edge_store,
        ontology=ont,
        hebbian_router=None,
        episodic_memory=None,
        edge_backfill=None,
    )
    ok = await _wire_edge_backfill(runtime=rt, config=sys_cfg)
    assert ok is True
    edges = await edge_store.find_edges(limit=100)
    # 1 member_of edge from the single assignment.
    assert len(edges) == 1
    assert edges[0].relation == KnowledgeRelationType.MEMBER_OF


# ── Test 12: force=True overrides skip ───────────────────────────


@pytest.mark.asyncio
async def test_wirer_force_overrides_populated_skip(tmp_path, edge_store):
    pre = KnowledgeEdge(
        source_type=KnowledgeEntityType.AGENT,
        source_id="x",
        relation=KnowledgeRelationType.MEMBER_OF,
        target_type=KnowledgeEntityType.DEPARTMENT,
        target_id="y",
    )
    await edge_store.add_edge(pre)
    captain = SimpleNamespace(id="captain", department_id="bridge", reports_to=None)
    a = SimpleNamespace(agent_type="captain", post_id="captain")
    ont = _stub_ontology(assignments=[a], posts=[captain])
    from probos.config import EdgeBackfillConfig
    from probos.startup.finalize import _wire_edge_backfill

    cfg = EdgeBackfillConfig(enabled=True, run_on_warm_boot=True, force=True)
    sys_cfg = SimpleNamespace(edge_backfill=cfg)
    rt = SimpleNamespace(
        knowledge_edges=edge_store,
        ontology=ont,
        hebbian_router=None,
        episodic_memory=None,
        edge_backfill=None,
    )
    ok = await _wire_edge_backfill(runtime=rt, config=sys_cfg)
    assert ok is True
    edges = await edge_store.find_edges(limit=100)
    # Original pre-populated edge + new ontology member_of edge = 2
    assert len(edges) == 2
```

---

## 6. Standing Conventions & Captain "No Trivial Deferral"

- Wave 5 conv #1 — public attribute over private. `runtime.edge_backfill` is public; verified collision-free against grep.
- Wave 5 conv #5 — late-bind emit fns. Not applicable here; the service does not emit events in v1 (deferred to AD-690 if event audit signals demand).
- Wave 10 transitional-flag default: deviation documented in `EdgeBackfillConfig` docstring (mirrors `KnowledgeEdgesConfig` and `CognitiveJournalConfig` precedent — infrastructure store with idempotency-by-row-count guard).
- Captain "no trivial deferral" (banked 2026-05-04, `/memories/repo/probos-notes.md`): all 4 sources land in v1. The deferred items (live event-driven backfill, classification gating, federation sync, LLM entity extraction) are in distinct ADs (AD-690/691/692/693) — not a-b-c child issues.
- Property-collision: `edge_backfill` is unique greenfield; no Pydantic field, runtime attribute, EventType, RecallTier, or KnowledgeSource collides.
- `**Resolved by:**` ↔ `Closes #N` resolution: documented in §4.4 — the Wave 37 enum has `RESOLVED_BY`, the structured marker in markdown is `Closes`. Builder uses `Closes` and does not invent a `Resolved by:` parser.

## 7. Phantom-API Pre-Check

Run `scripts/phantom-api-precheck.ps1 -PromptPaths prompts/ad-689-edge-population-v1.md` after draft commits. Symbols introduced by THIS prompt that pre-check may flag (all FPs — symbols defined in this prompt, not yet on disk):

- `EdgeBackfillService`, `EdgeBackfillResult`, `EdgeBackfillConfig` — introduced by Sections 1, 4.
- `_deterministic_edge_id`, `_make_edge` — module-private helpers in `backfill.py`.
- `_wire_edge_backfill` — introduced by Section 6.
- `EpisodicMemory.list_episodes` — introduced by Section 3.
- `runtime.edge_backfill` — introduced by Section 5.
- `SimpleNamespace` — `types.SimpleNamespace`, stdlib (FP class — same as Waves 27–35).

No NEW kwarg phantoms expected (all signatures verified against live `KnowledgeEdgeStorage` Protocol, `Episode` dataclass, `HebbianRouter.all_weights_typed()`, ontology service methods).

## 8. What This Does NOT Change

- No new EventType (no audit emission v1; defer to AD-690 if needed).
- No federation sync of edges (AD-693 commercial).
- No classification gating on backfill writes (AD-692 commercial).
- No NL-to-graph LLM entity extraction (AD-691).
- No Dream Step 10 inference (AD-690).
- No live event-driven incremental backfill (separate AD if proposed).
- No HXI graph visualization.
- No shell command (`/graph backfill`) — use the wirer or invoke `runtime.edge_backfill.backfill_all()` directly.
- No retention / pruning policy on `knowledge_edges` (deferred until data warrants).
- No mutation of existing AD-687 schema, AD-688 Oracle Tier 6, or any other shipped surface.

## 9. Test-Count Budget

- Baseline: 11004 (Wave 38 commit `24c9db4`).
- Expected: 11016 (+12). Drop targets if drift forces it: tests #4 (custom threshold — overlaps test #3 logically) and #12 (force override — overlaps test #11). Floor 10/12 retained.
- Known xdist flake `test_auto_commit_after_debounce` may absorb one numeric delta — same Wave 8/14/15/16/19/22/27/37 pattern. Net delta ≥ +10 still satisfies the test-count-non-decreasing rule.

## 10. Tracking

- **PROGRESS.md** — prepend AD-689 v1 entry under Era V.
- **DECISIONS.md** — prepend full AD-689 entry at top of Era V (above AD-688).
- **docs/development/roadmap.md** — flip AD-689 row from Scoped → Complete.
- **GH issue #383** — close with summary + commit SHA.

## 11. Acceptance Criteria

1. `EdgeBackfillService` exposes `backfill_all`, `backfill_ontology`, `backfill_hebbian`, `backfill_episodes`, `backfill_decisions` — all async, all return `int` (or `EdgeBackfillResult` for `backfill_all`).
2. `runtime.edge_backfill` is set after `finalize_startup` runs (when config enabled).
3. Warm-boot wirer skips when `find_edges(limit=1)` returns at least one row, unless `force=True`.
4. Warm-boot wirer runs `backfill_all()` once when the store is empty.
5. `EpisodicMemory.list_episodes(limit=None)` returns episodes ordered by timestamp DESC.
6. Re-running `backfill_all()` against an unchanged source set produces no net row count change (deterministic edge IDs + INSERT OR REPLACE).
7. ≥ 10 new tests in `tests/test_ad689_edge_backfill.py` pass.
8. Full pytest gate (`pytest tests/ -q -n 8 --dist=loadfile`) net delta ≥ +10 over Wave 38 baseline (11004); known xdist flakes acceptable.
9. Phantom-API pre-check returns 0 NEW phantom candidates (intra-prompt-introduced FPs documented, not flagged).
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
