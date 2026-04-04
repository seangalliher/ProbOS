"""AD-555: Notebook Quality Metrics & Dashboarding.

Aggregates notebook quality data from RecordsStore, producing per-agent
and system-wide quality snapshots.  Follows the EmergenceMetricsEngine
pattern (snapshot deque + properties + compute method).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class AgentNotebookQuality:
    """Quality metrics for a single agent's notebook corpus."""

    callsign: str = ""
    department: str = ""
    total_entries: int = 0
    unique_topics: int = 0
    entries_per_topic_avg: float = 0.0
    entries_per_topic_max: int = 0
    mean_revision: float = 0.0
    max_revision: int = 0
    novel_content_rate: float = 0.0
    stale_rate: float = 0.0
    convergence_contributions: int = 0
    repetition_alerts: int = 0
    quality_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NotebookQualitySnapshot:
    """Ship-level notebook quality metrics at a point in time."""

    timestamp: float = 0.0
    total_entries: int = 0
    total_agents: int = 0
    total_topics: int = 0
    system_quality_score: float = 0.0
    dedup_suppression_rate: float = 0.0
    repetition_alert_rate: float = 0.0
    convergence_count: int = 0
    divergence_count: int = 0
    stale_entry_rate: float = 0.0
    per_agent: list[AgentNotebookQuality] = field(default_factory=list)
    per_department: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["per_agent"] = [a.to_dict() if hasattr(a, "to_dict") else a for a in self.per_agent]
        return d


# ---------------------------------------------------------------------------
# Per-agent quality computation
# ---------------------------------------------------------------------------


def _compute_agent_quality(
    callsign: str,
    entries: list[dict],
    staleness_cutoff: float,
    *,
    convergence_contributions: int = 0,
    repetition_alerts: int = 0,
) -> AgentNotebookQuality:
    """Compute quality metrics for a single agent's notebook entries."""
    total = len(entries)
    if total == 0:
        return AgentNotebookQuality(callsign=callsign, quality_score=0.0)

    department = ""
    topics: dict[str, int] = defaultdict(int)
    revisions: list[int] = []
    stale = 0
    novel = 0  # entries with revision == 1

    for entry in entries:
        fm = entry.get("frontmatter", {})
        if not department:
            department = fm.get("department", "")
        topic = fm.get("topic", entry.get("path", "unknown").split("/")[-1].replace(".md", ""))
        topics[topic] += 1
        rev = fm.get("revision", 1)
        revisions.append(rev)
        if rev == 1:
            novel += 1
        updated_str = fm.get("updated", "")
        if updated_str:
            try:
                ts = datetime.fromisoformat(updated_str).timestamp()
                if ts < staleness_cutoff:
                    stale += 1
            except (ValueError, OSError):
                pass

    unique_topics = len(topics)
    entries_per_topic_max = max(topics.values()) if topics else 0
    stale_rate = stale / total
    novel_content_rate = novel / total

    # Quality score (weighted composite)
    topic_diversity = min(unique_topics / max(total, 1), 1.0)
    freshness = 1.0 - stale_rate
    convergence_score_val = min(convergence_contributions / 3, 1.0)
    low_rep = max(0.0, 1.0 - repetition_alerts * 0.2) if repetition_alerts > 0 else 1.0

    quality = round(
        0.30 * topic_diversity
        + 0.25 * freshness
        + 0.25 * novel_content_rate
        + 0.10 * convergence_score_val
        + 0.10 * low_rep,
        3,
    )

    return AgentNotebookQuality(
        callsign=callsign,
        department=department,
        total_entries=total,
        unique_topics=unique_topics,
        entries_per_topic_avg=round(total / max(unique_topics, 1), 1),
        entries_per_topic_max=entries_per_topic_max,
        mean_revision=round(sum(revisions) / total, 1),
        max_revision=max(revisions) if revisions else 0,
        novel_content_rate=round(novel_content_rate, 3),
        stale_rate=round(stale_rate, 3),
        convergence_contributions=convergence_contributions,
        repetition_alerts=repetition_alerts,
        quality_score=quality,
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class NotebookQualityEngine:
    """Aggregates notebook quality metrics from RecordsStore data.

    Follows EmergenceMetricsEngine pattern: snapshot deque + properties
    + compute method.
    """

    def __init__(self, staleness_hours: float = 72.0) -> None:
        self._snapshots: deque[NotebookQualitySnapshot] = deque(maxlen=100)
        self._staleness_hours = staleness_hours
        # Event counters (reset each compute cycle)
        self._dedup_suppressions: int = 0
        self._dedup_writes: int = 0
        self._repetition_alerts: int = 0
        self._convergence_events: int = 0
        self._divergence_events: int = 0
        # Per-agent event tracking (cumulative across snapshots)
        self._agent_convergences: dict[str, int] = defaultdict(int)
        self._agent_repetitions: dict[str, int] = defaultdict(int)

    @property
    def latest_snapshot(self) -> NotebookQualitySnapshot | None:
        return self._snapshots[-1] if self._snapshots else None

    @property
    def snapshots(self) -> list[NotebookQualitySnapshot]:
        return list(self._snapshots)

    def record_event(self, event_type: str, **kwargs: Any) -> None:
        """Record a notebook pipeline event for quality metrics."""
        if event_type == "dedup_suppression":
            self._dedup_suppressions += 1
        elif event_type == "dedup_write":
            self._dedup_writes += 1
        elif event_type == "repetition_alert":
            self._repetition_alerts += 1
            agent = kwargs.get("callsign", "")
            if agent:
                self._agent_repetitions[agent] += 1
        elif event_type == "convergence":
            self._convergence_events += 1
            for agent in kwargs.get("agents", []):
                self._agent_convergences[agent] += 1
        elif event_type == "divergence":
            self._divergence_events += 1

    async def compute_quality_metrics(
        self,
        records_store: Any,
        staleness_hours: float | None = None,
    ) -> NotebookQualitySnapshot:
        """Compute full quality snapshot from RecordsStore notebook data.

        Called during dream cycle.  Scans all notebook entries, computes
        per-agent quality scores, and produces a system-wide snapshot.
        """
        staleness = staleness_hours or self._staleness_hours
        now = time.time()
        staleness_cutoff = now - (staleness * 3600)

        # Scan all notebook entries
        try:
            entries = await records_store.list_entries("notebooks")
        except Exception:
            logger.debug("AD-555: Failed to list notebook entries", exc_info=True)
            return NotebookQualitySnapshot(timestamp=now)

        # Group by author
        by_author: dict[str, list[dict]] = defaultdict(list)
        all_topics: set[str] = set()
        stale_count = 0

        for entry in entries:
            fm = entry.get("frontmatter", {})
            author = fm.get("author", "unknown")
            topic = fm.get("topic", entry.get("path", "unknown").split("/")[-1].replace(".md", ""))
            by_author[author].append(entry)
            all_topics.add(topic)

            updated_str = fm.get("updated", "")
            if updated_str:
                try:
                    entry_ts = datetime.fromisoformat(updated_str).timestamp()
                    if entry_ts < staleness_cutoff:
                        stale_count += 1
                except (ValueError, OSError):
                    pass

        # Per-agent quality
        per_agent: list[AgentNotebookQuality] = []
        for callsign, agent_entries in sorted(by_author.items()):
            aq = _compute_agent_quality(
                callsign,
                agent_entries,
                staleness_cutoff,
                convergence_contributions=self._agent_convergences.get(callsign, 0),
                repetition_alerts=self._agent_repetitions.get(callsign, 0),
            )
            per_agent.append(aq)

        # Per-department aggregation
        dept_buckets: dict[str, list[float]] = defaultdict(list)
        for aq in per_agent:
            if aq.department:
                dept_buckets[aq.department].append(aq.quality_score)
        dept_scores = {
            dept: round(sum(scores) / len(scores), 3)
            for dept, scores in dept_buckets.items()
            if scores
        }

        # System-wide
        total_writes = self._dedup_writes + self._dedup_suppressions
        snapshot = NotebookQualitySnapshot(
            timestamp=now,
            total_entries=len(entries),
            total_agents=len(by_author),
            total_topics=len(all_topics),
            system_quality_score=round(
                sum(a.quality_score for a in per_agent) / max(len(per_agent), 1), 3
            ),
            dedup_suppression_rate=round(
                self._dedup_suppressions / max(total_writes, 1), 3
            ),
            repetition_alert_rate=round(
                self._repetition_alerts / max(total_writes, 1), 3
            ),
            convergence_count=self._convergence_events,
            divergence_count=self._divergence_events,
            stale_entry_rate=round(stale_count / max(len(entries), 1), 3),
            per_agent=per_agent,
            per_department=dept_scores,
        )

        self._snapshots.append(snapshot)
        self._reset_counters()
        return snapshot

    def _reset_counters(self) -> None:
        """Reset event counters after snapshot.  Preserves per-agent cumulative counts."""
        self._dedup_suppressions = 0
        self._dedup_writes = 0
        self._repetition_alerts = 0
        self._convergence_events = 0
        self._divergence_events = 0
