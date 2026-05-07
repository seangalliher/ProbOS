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
from dataclasses import dataclass
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
