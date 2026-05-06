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
    r"^###\s+AD-(\d+[a-z]?)[^\n]*$",
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

        agent_by_post: dict[str, list[str]] = {}
        for a in assignments:
            agent_by_post.setdefault(a.post_id, []).append(a.agent_type)

        for a in assignments:
            try:
                post = self._ontology.get_post(a.post_id)
            except Exception:
                continue
            if post is None or not getattr(post, "department_id", None):
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

        try:
            posts = list(self._ontology.get_posts())
        except Exception:
            posts = []
        # BF-264: Build post lookup for chain traversal
        post_by_id: dict[str, Any] = {}
        for p in posts:
            post_by_id[p.id] = p
        for post in posts:
            if not getattr(post, "reports_to", None):
                continue
            sub_agents = agent_by_post.get(post.id, [])
            # BF-264: If the reports_to target post has no agent assigned,
            # traverse up the chain until we find one. This handles dual-hat
            # gaps (e.g., chief_science has no assignment but reports_to
            # first_officer which does).
            sup_agents: list[str] = []
            target_post_id = post.reports_to
            seen_posts: set[str] = set()
            while target_post_id and target_post_id not in seen_posts:
                sup_agents = agent_by_post.get(target_post_id, [])
                if sup_agents:
                    break
                seen_posts.add(target_post_id)
                target_post = post_by_id.get(target_post_id)
                if target_post is None:
                    break
                target_post_id = getattr(target_post, "reports_to", None)
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
        matches = list(_AD_SECTION_PATTERN.finditer(text))
        if not matches:
            return 0
        count = 0
        for i, m in enumerate(matches):
            ad_id = m.group(1)
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end]
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
