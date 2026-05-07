# AD-562 v1 — Ship's Records Knowledge Browser: Obsidian-Style HXI with 3D Knowledge Graph

**Status:** Ready to build (Wave 104).
**Dependencies:** AD-434 (Ship's Records, Complete), AD-551 (convergence reports, Complete), AD-555 (notebook quality engine, Complete), AD-611 + AD-520 (`react-force-graph-3d` adoption, in-tree). All at HEAD `d8b7c63`.
**Estimated tests:** ~28 pytest + ~32 vitest. Pytest baseline 12482 → target ≥12510. Vitest baseline 393 → target ≥425.
**Closes:** GH issue #9.

## Engineering Principles compliance

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`:
- SOLID single-responsibility per class/file. `KnowledgeBrowserService` co-located with helpers in `backlinks.py` (DLog #4) — file-level cohesion.
- Constructor injection (records_store, notebook_quality_engine passed in).
- Public properties only (`runtime.knowledge_browser`, no private-attr access from routers).
- Pydantic config with sensible defaults (default-False per AD-695 transitional precedent).
- Fail-fast log-and-degrade (tier-2) on every external boundary.
- DRY — reuses existing `RecordsStore.list_entries` / `read_entry` / `_parse_document` API; reuses `react-force-graph-3d` already in-tree; reuses `NotebooksPanel` color tokens.
- HXI Design Principle #3 (no emoji). Inline SVG glyphs only (`×` close, `↻` refresh — Unicode-character permitted).
- HXI fragility rule: `CognitiveCanvas.tsx`, `NotebooksPanel.tsx`, `SpatialExplorerPanel.tsx` UNTOUCHED.
- Zero new npm dependency.

## Problem

Ship's Records (AD-434) provides the Git-backed markdown knowledge store, and AD-551/AD-555 add convergence detection and quality metrics — but the HXI has no unified browsing surface. NotebooksPanel (AD-523b) is notebook-only; the rest of Ship's Records (Captain's Log, duty logs, convergence reports, procedures, manuals) has no HXI surface at all. There's no way to navigate cross-references, see the knowledge web spatially, or surface quality overlays. AD-562 is the unified browser — Obsidian-style, four views (List / Reader / 3D Graph / Timeline), backlinks rail, quality overlays.

## Solution overview

Single source-modifying additive wave:
1. New helper module `src/probos/knowledge/backlinks.py` — pure regex extraction + index builder + Jaccard suggester + `KnowledgeBrowserService` wrapper.
2. New `KnowledgeBrowserConfig` Pydantic model + `SystemConfig.knowledge_browser` field.
3. Four new GET endpoints appended to `routers/records.py`: `/browse`, `/backlinks/{path}`, `/graph`, `/timeline`.
4. New `_wire_knowledge_browser` finalize wirer + invocation site.
5. Eight new HXI components for the Knowledge Browser panel + four sub-views + filter rail + backlinks rail.
6. Store extension + `App.tsx` toggle + panel mount.
7. Tracker updates: roadmap status flip + decisions status flip + wave-plan entry.

Phase 5 (native desktop packaging) is explicit commercial scope from `roadmap.md:4253` — descriptor-only carve-out, no GH issue, no FF defer.

---

### Section 1: New helper module — `src/probos/knowledge/backlinks.py`

Create the file with the following content (~300 LOC total — helpers + service):

```python
"""AD-562: Ship's Records Knowledge Browser — backlink extraction + index + service.

Pure regex-based reference extraction. Builds bidirectional backlink index
across all Ship's Records entries. Jaccard-based cross-reference suggestion.
KnowledgeBrowserService wraps the helpers with TTL-cached graph + timeline.
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_WIKILINK_RE = re.compile(r"\[\[([^\]\n]+)\]\]")
# Callsign: @name preceded by start-of-string OR non-word char (avoids email-like @x suffix in foo@example).
_CALLSIGN_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z][A-Za-z0-9_-]{1,31})")


@dataclass(frozen=True)
class Reference:
    kind: str  # "wikilink" | "callsign" | "topic_slug" | "tag"
    target: str
    raw_match: str


@dataclass(frozen=True)
class BacklinkRecord:
    path: str
    references: tuple[Reference, ...]
    referenced_by: tuple[str, ...]


@dataclass(frozen=True)
class BacklinkIndex:
    records: dict[str, BacklinkRecord]
    path_by_callsign: dict[str, str]
    path_by_topic_slug: dict[str, str]
    built_at: float
    entry_count: int


def extract_references(
    content: str,
    frontmatter: dict,
    *,
    valid_callsigns: set[str],
    valid_topic_slugs: set[str],
) -> tuple[Reference, ...]:
    """Extract all references from a single entry. Pure, no I/O.

    Tier-2 log-and-degrade on regex failure: returns empty tuple + WARNING.
    """
    refs: list[Reference] = []
    try:
        for m in _WIKILINK_RE.finditer(content or ""):
            target = m.group(1).strip()
            if target:
                refs.append(Reference(kind="wikilink", target=target, raw_match=m.group(0)))
        for m in _CALLSIGN_RE.finditer(content or ""):
            cs = m.group(1).lower()
            if cs in valid_callsigns:
                refs.append(Reference(kind="callsign", target=cs, raw_match=m.group(0)))
        # Frontmatter contributions
        topic_slug = frontmatter.get("topic_slug") or frontmatter.get("topic")
        if topic_slug and isinstance(topic_slug, str):
            slug = topic_slug.strip().lower()
            if slug and slug in valid_topic_slugs:
                refs.append(Reference(kind="topic_slug", target=slug, raw_match=slug))
        for tag in frontmatter.get("tags", []) or []:
            if isinstance(tag, str) and tag.strip():
                refs.append(Reference(kind="tag", target=tag.strip().lower(), raw_match=tag))
    except Exception:
        logger.warning("AD-562: extract_references failed; returning empty tuple", exc_info=True)
        return ()
    # Dedup by (kind, target)
    seen: set[tuple[str, str]] = set()
    deduped: list[Reference] = []
    for r in refs:
        key = (r.kind, r.target)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return tuple(deduped)


def build_backlink_index(
    entries: list[dict],
    *,
    valid_callsigns: set[str],
) -> BacklinkIndex:
    """Build bidirectional backlink index across all entries.

    Each entry is a dict {"path": str, "frontmatter": dict, "content": str|None}.
    Empty input yields an empty index — never raises.
    """
    if not entries:
        return BacklinkIndex(
            records={}, path_by_callsign={}, path_by_topic_slug={},
            built_at=time.time(), entry_count=0,
        )
    path_by_callsign: dict[str, str] = {}
    path_by_topic_slug: dict[str, str] = {}
    for e in entries:
        fm = e.get("frontmatter") or {}
        author = fm.get("author")
        if author and isinstance(author, str):
            path_by_callsign.setdefault(author.lower(), e.get("path", ""))
        slug = fm.get("topic_slug") or fm.get("topic")
        if slug and isinstance(slug, str):
            path_by_topic_slug.setdefault(slug.strip().lower(), e.get("path", ""))
    valid_topic_slugs = set(path_by_topic_slug.keys())
    # First pass: extract references
    refs_by_path: dict[str, tuple[Reference, ...]] = {}
    for e in entries:
        path = e.get("path", "")
        content = e.get("content") or ""
        fm = e.get("frontmatter") or {}
        refs_by_path[path] = extract_references(
            content, fm,
            valid_callsigns=valid_callsigns,
            valid_topic_slugs=valid_topic_slugs,
        )
    # Second pass: build referenced_by reverse index
    referenced_by: dict[str, set[str]] = defaultdict(set)
    for src_path, refs in refs_by_path.items():
        for r in refs:
            target_path = ""
            if r.kind == "callsign":
                target_path = path_by_callsign.get(r.target, "")
            elif r.kind == "topic_slug":
                target_path = path_by_topic_slug.get(r.target, "")
            elif r.kind == "wikilink":
                # Try as callsign first, then topic_slug, then literal path
                target_path = (
                    path_by_callsign.get(r.target.lower(), "")
                    or path_by_topic_slug.get(r.target.lower(), "")
                )
                if not target_path and any(e.get("path") == r.target for e in entries):
                    target_path = r.target
            if target_path and target_path != src_path:
                referenced_by[target_path].add(src_path)
    # Materialize records
    records: dict[str, BacklinkRecord] = {}
    for e in entries:
        path = e.get("path", "")
        records[path] = BacklinkRecord(
            path=path,
            references=refs_by_path.get(path, ()),
            referenced_by=tuple(sorted(referenced_by.get(path, set()))),
        )
    return BacklinkIndex(
        records=records,
        path_by_callsign=path_by_callsign,
        path_by_topic_slug=path_by_topic_slug,
        built_at=time.time(),
        entry_count=len(entries),
    )


def suggest_cross_references(
    entries: list[dict],
    existing_index: BacklinkIndex,
    *,
    jaccard_threshold: float = 0.3,
    max_per_entry: int = 5,
) -> dict[str, list[dict]]:
    """For each entry, suggest candidate cross-references via Jaccard on tag+slug+author tokens.

    Excludes pairs already in the explicit references/referenced_by graph.
    """
    if not entries or jaccard_threshold <= 0.0 or max_per_entry <= 0:
        return {}

    def tokens(e: dict) -> set[str]:
        fm = e.get("frontmatter") or {}
        toks: set[str] = set()
        for tag in fm.get("tags", []) or []:
            if isinstance(tag, str) and tag.strip():
                toks.add(tag.strip().lower())
        slug = fm.get("topic_slug") or fm.get("topic")
        if slug and isinstance(slug, str):
            toks.add(slug.strip().lower())
        author = fm.get("author")
        if author and isinstance(author, str):
            toks.add(f"author:{author.lower()}")
        return toks

    by_path = {e.get("path", ""): tokens(e) for e in entries}
    suggestions: dict[str, list[dict]] = {}
    paths = list(by_path.keys())
    for i, p_a in enumerate(paths):
        toks_a = by_path[p_a]
        if not toks_a:
            continue
        rec_a = existing_index.records.get(p_a)
        excluded: set[str] = set(rec_a.referenced_by) if rec_a else set()
        if rec_a:
            for r in rec_a.references:
                if r.kind == "callsign":
                    excluded.add(existing_index.path_by_callsign.get(r.target, ""))
                elif r.kind == "topic_slug":
                    excluded.add(existing_index.path_by_topic_slug.get(r.target, ""))
        candidates: list[tuple[float, str]] = []
        for j, p_b in enumerate(paths):
            if i == j or p_b in excluded or not p_b:
                continue
            toks_b = by_path[p_b]
            if not toks_b:
                continue
            inter = len(toks_a & toks_b)
            if inter == 0:
                continue
            union = len(toks_a | toks_b)
            score = inter / union if union else 0.0
            if score >= jaccard_threshold:
                candidates.append((score, p_b))
        candidates.sort(reverse=True)
        if candidates:
            suggestions[p_a] = [
                {"path": p, "similarity": round(s, 3)}
                for s, p in candidates[:max_per_entry]
            ]
    return suggestions


class KnowledgeBrowserService:
    """AD-562: Ship's Records Knowledge Browser service.

    Wraps the pure helpers above with a TTL-cached index + graph payload + timeline.
    All boundaries are tier-2 log-and-degrade.
    """

    def __init__(
        self,
        records_store: Any,
        notebook_quality_engine: Any = None,
        *,
        max_graph_nodes: int = 500,
        max_graph_edges: int = 1000,
        jaccard_threshold: float = 0.3,
        max_suggestions_per_entry: int = 5,
        index_refresh_seconds: int = 300,
    ) -> None:
        self._store = records_store
        self._quality = notebook_quality_engine
        self._max_nodes = max_graph_nodes
        self._max_edges = max_graph_edges
        self._jaccard = jaccard_threshold
        self._max_sugg = max_suggestions_per_entry
        self._ttl = index_refresh_seconds
        self._index: BacklinkIndex | None = None
        self._entries_cache: list[dict] = []
        self._suggestions_cache: dict[str, list[dict]] = {}

    async def _load_entries(self) -> list[dict]:
        """Fetch + read all entries. Tier-2 log-and-degrade returns []."""
        try:
            listing = await self._store.list_entries()
        except Exception:
            logger.warning("AD-562: list_entries failed; returning empty", exc_info=True)
            return []
        out: list[dict] = []
        for stub in listing:
            path = stub.get("path", "")
            if not path:
                continue
            try:
                doc = await self._store.read_entry(path, reader_id="captain")
            except Exception:
                logger.debug("AD-562: read_entry failed for %s", path, exc_info=True)
                doc = None
            if doc is None:
                # Use stub frontmatter without content
                out.append({"path": path, "frontmatter": stub.get("frontmatter", {}), "content": ""})
            else:
                out.append({
                    "path": path,
                    "frontmatter": doc.get("frontmatter", {}),
                    "content": doc.get("content", ""),
                })
        return out

    async def get_index(self, *, force_refresh: bool = False) -> BacklinkIndex:
        now = time.time()
        if (
            not force_refresh
            and self._index is not None
            and (now - self._index.built_at) <= self._ttl
        ):
            return self._index
        entries = await self._load_entries()
        callsigns = {
            (e.get("frontmatter") or {}).get("author", "").lower()
            for e in entries
            if (e.get("frontmatter") or {}).get("author")
        }
        callsigns.discard("")
        index = build_backlink_index(entries, valid_callsigns=callsigns)
        self._entries_cache = entries
        self._index = index
        self._suggestions_cache = suggest_cross_references(
            entries, index,
            jaccard_threshold=self._jaccard,
            max_per_entry=self._max_sugg,
        )
        return index

    async def get_backlinks(self, path: str, *, include_suggested: bool = True) -> dict | None:
        index = await self.get_index()
        rec = index.records.get(path)
        if rec is None:
            return None
        out = {
            "path": path,
            "references": [
                {"kind": r.kind, "target": r.target, "raw_match": r.raw_match}
                for r in rec.references
            ],
            "referenced_by": list(rec.referenced_by),
            "suggested": (
                self._suggestions_cache.get(path, []) if include_suggested else []
            ),
        }
        return out

    async def get_graph(
        self,
        *,
        max_nodes: int | None = None,
        max_edges: int | None = None,
        include_suggested: bool = False,
        include_quality: bool = False,
        department_filter: str = "",
        classification_filter: str = "",
    ) -> dict:
        index = await self.get_index()
        node_cap = self._max_nodes if max_nodes is None else min(max_nodes, self._max_nodes)
        edge_cap = self._max_edges if max_edges is None else min(max_edges, self._max_edges)
        # Build nodes
        nodes: list[dict] = []
        node_index: dict[str, int] = {}
        quality_by_callsign: dict[str, dict] = {}
        if include_quality and self._quality is not None:
            for e in self._entries_cache:
                cs = (e.get("frontmatter") or {}).get("author", "").lower()
                if not cs or cs in quality_by_callsign:
                    continue
                try:
                    snap = await self._quality.get_agent_snapshot(cs)
                    if snap is not None:
                        quality_by_callsign[cs] = {
                            "novel_content_rate": getattr(snap, "novel_content_rate", None),
                            "repetition_alerts": getattr(snap, "repetition_alerts", None),
                            "stale_rate": getattr(snap, "stale_rate", None),
                        }
                except Exception:
                    logger.debug("AD-562: quality snapshot failed for %s", cs, exc_info=True)
        for e in self._entries_cache:
            if len(nodes) >= node_cap:
                break
            fm = e.get("frontmatter") or {}
            path = e.get("path", "")
            dept = (fm.get("department") or "").lower()
            cls = (fm.get("classification") or "ship").lower()
            if department_filter and dept != department_filter.lower():
                continue
            if classification_filter and cls != classification_filter.lower():
                continue
            author = (fm.get("author") or "").lower()
            is_hub = path.startswith("convergence-reports/")
            doc_type = path.split("/", 1)[0] if "/" in path else "root"
            quality_overlay = quality_by_callsign.get(author) if include_quality else None
            node = {
                "id": path,
                "label": fm.get("topic_slug") or fm.get("topic") or path.rsplit("/", 1)[-1].rsplit(".", 1)[0],
                "type": doc_type,
                "department": dept,
                "classification": cls,
                "author": author,
                "revision_count": int(fm.get("revision_count", 1) or 1),
                "is_convergence_hub": is_hub,
                "quality_overlay": quality_overlay,
            }
            node_index[path] = len(nodes)
            nodes.append(node)
        # Build edges
        edges: list[dict] = []
        # Explicit backlinks
        for src_path, rec in index.records.items():
            if src_path not in node_index:
                continue
            for r in rec.references:
                tgt_path = ""
                if r.kind == "callsign":
                    tgt_path = index.path_by_callsign.get(r.target, "")
                elif r.kind == "topic_slug":
                    tgt_path = index.path_by_topic_slug.get(r.target, "")
                elif r.kind == "wikilink":
                    tgt_path = (
                        index.path_by_callsign.get(r.target.lower(), "")
                        or index.path_by_topic_slug.get(r.target.lower(), "")
                    )
                if tgt_path and tgt_path in node_index and tgt_path != src_path:
                    edges.append({"source": src_path, "target": tgt_path, "kind": "backlink"})
                    if len(edges) >= edge_cap:
                        break
            if len(edges) >= edge_cap:
                break
        # Convergence-membership edges
        if len(edges) < edge_cap:
            for e in self._entries_cache:
                if len(edges) >= edge_cap:
                    break
                path = e.get("path", "")
                if not path.startswith("convergence-reports/") or path not in node_index:
                    continue
                for cs in (e.get("frontmatter") or {}).get("contributing_agents", []) or []:
                    if not isinstance(cs, str):
                        continue
                    src = index.path_by_callsign.get(cs.lower(), "")
                    if src and src in node_index:
                        edges.append({"source": src, "target": path, "kind": "convergence"})
                        if len(edges) >= edge_cap:
                            break
        # Suggested edges
        if include_suggested and len(edges) < edge_cap:
            for src_path, suggs in self._suggestions_cache.items():
                if src_path not in node_index:
                    continue
                for s in suggs:
                    tgt = s.get("path", "")
                    if tgt and tgt in node_index and tgt != src_path:
                        edges.append({
                            "source": src_path, "target": tgt,
                            "kind": "suggested", "similarity": s.get("similarity", 0.0),
                        })
                        if len(edges) >= edge_cap:
                            break
                if len(edges) >= edge_cap:
                    break
        return {
            "nodes": nodes,
            "edges": edges,
            "generated_at": time.time(),
            "node_count": len(nodes),
            "edge_count": len(edges),
        }

    async def get_timeline(
        self,
        *,
        bucket: str = "day",
        since: str = "",
        until: str = "",
    ) -> dict:
        if bucket != "day":
            raise ValueError(f"unsupported bucket: {bucket}")
        await self.get_index()  # populate cache
        from collections import Counter
        per_day: dict[str, int] = Counter()
        per_day_dept: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for e in self._entries_cache:
            fm = e.get("frontmatter") or {}
            created = fm.get("created", "")
            if not isinstance(created, str) or len(created) < 10:
                continue
            day = created[:10]
            if since and day < since:
                continue
            if until and day > until:
                continue
            per_day[day] += 1
            dept = (fm.get("department") or "unassigned").lower()
            per_day_dept[day][dept] += 1
        buckets = [
            {"date": d, "count": per_day[d], "by_department": dict(per_day_dept[d])}
            for d in sorted(per_day.keys())
        ]
        return {
            "buckets": buckets,
            "total": sum(per_day.values()),
            "bucket": bucket,
        }
```

### Section 2: New Pydantic config — `KnowledgeBrowserConfig`

In `src/probos/config.py`, insert the new model adjacent to `SpatialExplorerConfig` (which lives at `:821`). Use this SEARCH/REPLACE block:

```
===SEARCH===
class SpatialExplorerConfig(BaseModel):
===REPLACE===
class KnowledgeBrowserConfig(BaseModel):
    """AD-562: Ship's Records Knowledge Browser (Phases 1-4 OSS)."""
    enabled: bool = False
    max_graph_nodes: int = Field(default=500, ge=0, le=2000)
    max_graph_edges: int = Field(default=1000, ge=0, le=5000)
    jaccard_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    max_suggestions_per_entry: int = Field(default=5, ge=0, le=50)
    index_refresh_seconds: int = Field(default=300, ge=10, le=3600)


class SpatialExplorerConfig(BaseModel):
===END REPLACE===
```

Then wire `SystemConfig.knowledge_browser` adjacent to `spatial_explorer` (which lives at `:2918`). Use this SEARCH/REPLACE:

```
===SEARCH===
    spatial_explorer: SpatialExplorerConfig = Field(default_factory=SpatialExplorerConfig)  # AD-520
===REPLACE===
    spatial_explorer: SpatialExplorerConfig = Field(default_factory=SpatialExplorerConfig)  # AD-520
    knowledge_browser: KnowledgeBrowserConfig = Field(default_factory=KnowledgeBrowserConfig)  # AD-562
===END REPLACE===
```

### Section 3: New finalize wirer — `_wire_knowledge_browser`

In `src/probos/startup/finalize.py`, append `_wire_knowledge_browser` immediately after `_wire_spatial_explorer` (at `:863`). Use this SEARCH/REPLACE:

```
===SEARCH===
def _wire_spatial_explorer(*, runtime: Any, config: "SystemConfig") -> bool:
===REPLACE===
def _wire_knowledge_browser(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-562: Construct runtime.knowledge_browser if records_store available.

    Default-False per AD-695 transitional precedent. Pure sync wirer —
    no asyncio task creation. Returns False if records store unavailable
    (tier-2 WARNING).
    """
    cfg = getattr(config, "knowledge_browser", None)
    if cfg is None or not getattr(cfg, "enabled", False):
        return False
    store = getattr(runtime, "_records_store", None)
    if store is None:
        logger.warning("AD-562: knowledge_browser enabled but _records_store unavailable")
        return False
    from probos.knowledge.backlinks import KnowledgeBrowserService
    quality_engine = getattr(runtime, "_notebook_quality_engine", None)
    runtime.knowledge_browser = KnowledgeBrowserService(
        records_store=store,
        notebook_quality_engine=quality_engine,
        max_graph_nodes=cfg.max_graph_nodes,
        max_graph_edges=cfg.max_graph_edges,
        jaccard_threshold=cfg.jaccard_threshold,
        max_suggestions_per_entry=cfg.max_suggestions_per_entry,
        index_refresh_seconds=cfg.index_refresh_seconds,
    )
    return True


def _wire_spatial_explorer(*, runtime: Any, config: "SystemConfig") -> bool:
===END REPLACE===
```

Then add the invocation site immediately after `_wire_spatial_explorer` invocation at `:3046`. Use this SEARCH/REPLACE:

```
===SEARCH===
    # AD-520: Wire Spatial Knowledge Explorer (default-False; constructs runtime.spatial_layout)
    try:
        _wire_spatial_explorer(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-520: _wire_spatial_explorer failed", exc_info=True)
===REPLACE===
    # AD-520: Wire Spatial Knowledge Explorer (default-False; constructs runtime.spatial_layout)
    try:
        _wire_spatial_explorer(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-520: _wire_spatial_explorer failed", exc_info=True)

    # AD-562: Wire Knowledge Browser service (default-False; constructs runtime.knowledge_browser)
    try:
        _wire_knowledge_browser(runtime=runtime, config=config)
    except Exception:
        logger.warning("AD-562: _wire_knowledge_browser failed", exc_info=True)
===END REPLACE===
```

### Section 4: Four new endpoints in `routers/records.py`

Append four new GET routes immediately after the existing `get_record_history` endpoint at `:131`. Use this SEARCH/REPLACE:

```
===SEARCH===
@router.get("/history/{path:path}")
async def get_record_history(path: str, limit: int = 20, runtime: Any = Depends(get_runtime)) -> Any:
    """Get git history for a specific record."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    try:
        history = await runtime._records_store.get_history(path, limit=limit)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"path": path, "history": history}
===REPLACE===
@router.get("/history/{path:path}")
async def get_record_history(path: str, limit: int = 20, runtime: Any = Depends(get_runtime)) -> Any:
    """Get git history for a specific record."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    try:
        history = await runtime._records_store.get_history(path, limit=limit)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"path": path, "history": history}


# AD-562: Knowledge Browser endpoints (Phases 1-4 OSS)


@router.get("/browse")
async def browse_records(
    author: str = "",
    department: str = "",
    classification: str = "",
    directory: str = "",
    tags: str = "",
    since: str = "",
    until: str = "",
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-562 Phase 1: unified entry list across all Ship's Records sub-directories."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()] if tags else []
    try:
        entries = await runtime._records_store.list_entries(
            directory=directory,
            author=author,
            classification=classification,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception:
        logger.warning("AD-562: browse list_entries failed; returning empty", exc_info=True)
        entries = []
    filtered = []
    for e in entries:
        fm = e.get("frontmatter") or {}
        if department and (fm.get("department") or "").lower() != department.lower():
            continue
        if tag_list:
            entry_tags = {str(t).lower() for t in (fm.get("tags") or [])}
            if not set(tag_list).issubset(entry_tags):
                continue
        created = fm.get("created", "")
        if since and isinstance(created, str) and created and created[:10] < since:
            continue
        if until and isinstance(created, str) and created and created[:10] > until:
            continue
        filtered.append(e)
    return {
        "documents": filtered,
        "count": len(filtered),
        "filters_applied": {
            "author": author, "department": department, "classification": classification,
            "directory": directory, "tags": tag_list, "since": since, "until": until,
        },
    }


@router.get("/backlinks/{path:path}")
async def get_backlinks(
    path: str,
    include_suggested: bool = True,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-562 Phase 2: backlinks for a single entry."""
    service = getattr(runtime, "knowledge_browser", None)
    if service is None:
        return JSONResponse({"error": "Knowledge Browser not available"}, status_code=503)
    try:
        result = await service.get_backlinks(path, include_suggested=include_suggested)
    except Exception:
        logger.warning("AD-562: get_backlinks failed for %s", path, exc_info=True)
        return JSONResponse({"error": "backlink lookup failed"}, status_code=500)
    if result is None:
        return JSONResponse({"error": "Not found in index"}, status_code=404)
    return result


@router.get("/graph")
async def get_records_graph(
    max_nodes: int = 500,
    max_edges: int = 1000,
    include_suggested: bool = False,
    include_quality: bool = False,
    department: str = "",
    classification: str = "",
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-562 Phase 3+4: 3D force-directed knowledge graph payload."""
    service = getattr(runtime, "knowledge_browser", None)
    if service is None:
        return JSONResponse({"error": "Knowledge Browser not available"}, status_code=503)
    capped_nodes = max(0, min(max_nodes, 2000))
    capped_edges = max(0, min(max_edges, 5000))
    try:
        return await service.get_graph(
            max_nodes=capped_nodes,
            max_edges=capped_edges,
            include_suggested=include_suggested,
            include_quality=include_quality,
            department_filter=department,
            classification_filter=classification,
        )
    except Exception:
        logger.warning("AD-562: get_graph failed", exc_info=True)
        return JSONResponse({"error": "graph assembly failed"}, status_code=500)


@router.get("/timeline")
async def get_records_timeline(
    bucket: str = "day",
    since: str = "",
    until: str = "",
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-562 Phase 1: entry-creation timeline (day-buckets, dept-stacked)."""
    service = getattr(runtime, "knowledge_browser", None)
    if service is None:
        return JSONResponse({"error": "Knowledge Browser not available"}, status_code=503)
    try:
        return await service.get_timeline(bucket=bucket, since=since, until=until)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception:
        logger.warning("AD-562: get_timeline failed", exc_info=True)
        return JSONResponse({"error": "timeline assembly failed"}, status_code=500)
===END REPLACE===
```

### Section 5: HXI components

Create the following 8 files. The mount points/styling match `SpatialExplorerPanel.tsx` and `NotebooksPanel.tsx` precedents verbatim.

**5a. `ui/src/components/knowledge/types.ts`:**

```ts
export interface KnowledgeBrowserEntry {
  path: string;
  frontmatter: {
    author?: string;
    department?: string;
    classification?: string;
    created?: string;
    updated?: string;
    revision_count?: number;
    topic_slug?: string;
    tags?: string[];
  };
}

export interface KnowledgeBrowserDoc extends KnowledgeBrowserEntry {
  content: string;
}

export interface KnowledgeReference {
  kind: 'wikilink' | 'callsign' | 'topic_slug' | 'tag';
  target: string;
  raw_match: string;
}

export interface KnowledgeBrowserBacklinks {
  path: string;
  references: KnowledgeReference[];
  referenced_by: string[];
  suggested: { path: string; similarity: number }[];
}

export interface KnowledgeGraphNode {
  id: string;
  label: string;
  type: string;
  department: string;
  classification: string;
  author: string;
  revision_count: number;
  is_convergence_hub: boolean;
  quality_overlay: {
    novel_content_rate: number | null;
    repetition_alerts: number | null;
    stale_rate: number | null;
  } | null;
}

export interface KnowledgeGraphEdge {
  source: string;
  target: string;
  kind: 'backlink' | 'suggested' | 'convergence';
  similarity?: number;
}

export interface KnowledgeBrowserGraphData {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  generated_at: number;
  node_count: number;
  edge_count: number;
}

export interface KnowledgeBrowserTimelineBucket {
  date: string;
  count: number;
  by_department: Record<string, number>;
}

export interface KnowledgeBrowserTimeline {
  buckets: KnowledgeBrowserTimelineBucket[];
  total: number;
  bucket: string;
}

export interface KnowledgeBrowserFilters {
  author: string;
  department: string;
  classification: string;
  directory: string;
  tags: string;
  since: string;
  until: string;
}

export const DEFAULT_KNOWLEDGE_BROWSER_FILTERS: KnowledgeBrowserFilters = {
  author: '', department: '', classification: '',
  directory: '', tags: '', since: '', until: '',
};
```

**5b. Store extensions** — `ui/src/store/types.ts` and `ui/src/store/useStore.ts`. Append:
- New state fields (10): `knowledgeBrowserOpen`, `knowledgeBrowserView`, `knowledgeBrowserSelectedPath`, `knowledgeBrowserFilters`, `knowledgeBrowserEntries`, `knowledgeBrowserSelectedDoc`, `knowledgeBrowserBacklinks`, `knowledgeBrowserGraphData`, `knowledgeBrowserTimeline`, `knowledgeBrowserLoading`.
- New actions (6): `openKnowledgeBrowser()`, `closeKnowledgeBrowser()`, `setKnowledgeBrowserView(view)`, `setKnowledgeBrowserFilters(partial)`, `selectKnowledgeBrowserEntry(path)`, `refreshKnowledgeBrowser()`.
- Initial state matches defaults: `open=false`, `view='list'`, `selectedPath=null`, `filters=DEFAULT_KNOWLEDGE_BROWSER_FILTERS`, all data fields `null` or `[]`, `loading=false`.
- `openKnowledgeBrowser()` sets `open=true` then triggers `refreshKnowledgeBrowser()`.
- `refreshKnowledgeBrowser()` fetches `/api/records/browse?<filters>` AND `/api/records/graph?include_quality=true&include_suggested=true` AND `/api/records/timeline?bucket=day` in parallel, sets entries/graphData/timeline.
- `selectKnowledgeBrowserEntry(path)` fetches `/api/records/documents/{encodeURIComponent(path)}?reader=captain` AND `/api/records/backlinks/{encodeURIComponent(path)}?include_suggested=true` in parallel, then `setKnowledgeBrowserView('reader')`.

(Use the existing `fetchJson<T>` pattern from `SpatialExplorerPanel.tsx:16-23` if not already in store/utils.)

**5c. `ui/src/components/KnowledgeBrowserPanel.tsx`** (~280 LOC). Pattern matches `SpatialExplorerPanel.tsx` verbatim:
- 800×640 panel at `top:90 left:90`.
- Header: title `KNOWLEDGE BROWSER` (amber `#f0b060`), four tabs (LIST/READER/GRAPH/TIMELINE), refresh `↻`, close `×`.
- Body: 3-column grid with `gridTemplateColumns: '220px 1fr 240px'` when reader view + selection, else 2-column `'220px 1fr'`.
- Left: `<FilterRail />`. Center: dispatch on view-mode tab. Right: `<BacklinksRail />` only in reader view + selection.
- ESC closes (`useEffect` keydown handler matching SpatialExplorerPanel pattern).
- `data-testid="knowledge-browser-panel"`.

**5d. `ui/src/components/knowledge/EntryListView.tsx`, `EntryReader.tsx`, `RecordsGraphView.tsx`, `TimelineView.tsx`, `BacklinksRail.tsx`, `FilterRail.tsx`** — implement per the dispatch description. Reuse `DEPT_COLORS` and `CLASS_COLORS` from `NotebooksPanel.tsx:15-29` (lift to `ui/src/components/knowledge/colors.ts` to avoid duplication; update `NotebooksPanel.tsx` import only — no other change to NotebooksPanel).

**5e. `ui/src/App.tsx`** — append a new `KnowledgeBrowserToggle` component at `top:12 left:410`. Pattern matches `SpatialExplorerToggle` at `App.tsx:58-92` verbatim. Mount `<KnowledgeBrowserPanel />` adjacent `<SpatialExplorerPanel />`. Label `RECORDS`. `data-testid="knowledge-browser-toggle"`.

### Section 6: Tests

**6a. Pytest** — create the 6 new test files listed in the dispatch test plan. Cover: backlinks helpers (12 tests), browse endpoint (4), backlinks endpoint (4), graph endpoint (5), timeline endpoint (2), finalize wirer (3). Total ≥28. Use `tmp_path` fixtures for any file-backed RecordsStore stubs. Use `MagicMock(spec=[])` discipline for getattr-by-name dispatcher tests (lesson AD-686b).

**6b. Vitest** — create the 7 new test files listed in the dispatch test plan. Total ≥32. Mock `fetch` globally via `vi.stubGlobal('fetch', vi.fn(...))`. Mock `react-force-graph-3d` via `vi.mock('react-force-graph-3d', () => ({ default: () => <div data-testid="force-graph" /> }))` (same pattern as Wave 103 `Ad520KnowledgeGraphView.test.tsx`).

### Section 7: Tracker updates

**7a. `docs/development/roadmap.md:4225`** — flip `(planned, OSS+commercial, depends: AD-434, AD-551, AD-555)` to `(Complete v1, OSS+commercial, depends: AD-434, AD-551, AD-555)`.

**7b. `decisions-era-4-evolution.md:2356`** — flip `**Status:** Planned.` to `**Status:** v1 Complete (Wave 104, 2026-05-07). Phases 1+2+3+4 OSS shipped (knowledge browser + backlinks + 3D records graph + quality overlays); Phase 5 native packaging remains commercial-tag descriptor-only.`

**7c. `prompts/wave-plan.yaml`** — append:
```yaml
  - id: "104"
    title: "AD-562 v1 Ship's Records Knowledge Browser: Obsidian-Style HXI with 3D Knowledge Graph (closes #9)"
    kind: single
    depends_on: ["103"]
    dispatch_prompt: "prompts/WAVE-104-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-562-records-knowledge-browser-v1.md"
    builder_required: true
    issues_to_close: [9]
    status: pending
```

## What this AD does NOT change

- No modification of `RecordsStore` (`knowledge/records_store.py`) — read-only consumption only.
- No modification of `NotebooksPanel.tsx` (AD-523b), `SpatialExplorerPanel.tsx` (AD-520), or `CognitiveCanvas.tsx` (HXI fragility rule). The single touch on `NotebooksPanel.tsx` is an import path for the lifted `colors.ts` — no behavioral change.
- No modification of any existing endpoint in `routers/records.py` — strict-additive append only.
- No new EventType, no new module other than `knowledge/backlinks.py`, no write API.
- No federation cross-instance sync.
- No LLM-based reference extraction (regex v1).
- No native desktop packaging (commercial Phase 5, descriptor-only).
- No bucket value other than "day" in timeline (week/month/year defer if surfaced).
- No virtualization library, no markdown parser library — zero new npm dependency.

## Acceptance criteria

- ≥28 new pytest pass; full gate `pytest tests/ -q -n 4 --dist=loadfile` shows ≥12510 passing (baseline 12482 + 28).
- ≥32 new vitest pass; `cd ui && npx vitest run` shows ≥425 passing (baseline 393 + 32).
- HXI Design Principle compliance: zero emoji (only Unicode glyphs `×`, `↻`); SVG strokes `1.5` rounded; amber/teal/violet/green/gold trust spectrum reused.
- `CognitiveCanvas.tsx`, `NotebooksPanel.tsx` (except 1-line color import), `SpatialExplorerPanel.tsx` UNTOUCHED behaviorally.
- Zero new npm dependency in `ui/package.json`.
- Default-False guard on `KnowledgeBrowserConfig.enabled`; all four new endpoints return 503 when disabled.
- Tier-2 log-and-degrade on every external boundary (RecordsStore, NotebookQualityEngine, regex parsing).
- Roadmap status flipped to `Complete v1`; decisions status flipped to `v1 Complete (Wave 104, 2026-05-07)`.
- `prompts/wave-plan.yaml` has new `id: "104"` entry.
- Closes GH issue #9 cleanly; mints zero new ADs (AD-562 pre-allocated); mints zero new BFs.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-07, HEAD `d8b7c63`)

```
src/probos/knowledge/records_store.py:700: async def read_entry(self, path, reader_id, reader_department=""):
src/probos/knowledge/records_store.py:731: async def list_entries(self, directory="", *, author="", status="", tags=None, classification=""):
src/probos/knowledge/records_store.py:819: async def search(self, query, scope="ship"):
src/probos/knowledge/records_store.py:942: def _parse_document(self, raw):

src/probos/routers/records.py:15: router = APIRouter(prefix="/api/records", tags=["records"])
src/probos/routers/records.py:130-131: @router.get("/history/{path:path}")  + async def get_record_history (last endpoint, append site)
src/probos/routers/system.py:353: @router.get("/notebook-quality")
src/probos/routers/system.py:365: @router.get("/notebook-quality/history")
src/probos/routers/system.py:383: @router.get("/notebook-quality/agent/{callsign}")

src/probos/config.py:821: class SpatialExplorerConfig(BaseModel):  (insert KnowledgeBrowserConfig BEFORE this)
src/probos/config.py:2918: spatial_explorer: SpatialExplorerConfig = Field(default_factory=SpatialExplorerConfig)  # AD-520  (insert knowledge_browser AFTER)

src/probos/startup/finalize.py:863: def _wire_spatial_explorer(*, runtime: Any, config: "SystemConfig") -> bool:  (insert _wire_knowledge_browser BEFORE this)
src/probos/startup/finalize.py:3046: _wire_spatial_explorer(runtime=runtime, config=config)  (insert AD-562 invocation block AFTER existing AD-520 try/except)

ui/package.json:19: "react-force-graph-3d": "^1.29.1"  (zero new dep)
ui/src/App.tsx:22: import SpatialExplorerPanel from './components/SpatialExplorerPanel';  (append KnowledgeBrowserPanel import after)
ui/src/App.tsx:58-91: function SpatialExplorerToggle()  (mirror this pattern for KnowledgeBrowserToggle, top:12 left:410)
ui/src/App.tsx:70: top: 12, left: 340  (next slot 410 confirmed clear — verified no other toggle uses 410+)
ui/src/components/NotebooksPanel.tsx:15-29: DEPT_COLORS + CLASS_COLORS (lift to knowledge/colors.ts; reuse here)

decisions-era-4-evolution.md:2330: ### AD-562: Ship's Records Knowledge Browser *(2026-04-03)*
decisions-era-4-evolution.md:2356: **Status:** Planned.  (status flip site)
docs/development/roadmap.md:4223-4253: AD-562 spec block (status flip at :4225)
prompts/archive/WAVE-77-DISPATCH.md:19: AD-523c superseded by AD-562 (already closed in W77 — no further tracker work)
```

Current highest at HEAD `d8b7c63`: AD-696, BF-265. AD-562 is pre-allocated; W104 mints 0 new AD/BF/GH-issues. Closes #9.
