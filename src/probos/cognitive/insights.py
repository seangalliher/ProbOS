"""AD-810: operator-facing recent-activity summary.

Pure aggregation service. Reads from existing stores (journal, dream
scheduler, thread namer, vision telemetry). No new persistence.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.cognitive.llm_client import BaseLLMClient
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TopicCount:
    label: str
    count: int


@dataclass(frozen=True)
class CrewInteraction:
    callsign: str
    message_count: int
    last_active_ts: float


@dataclass(frozen=True)
class ScheduledTask:
    description: str
    completed_at: float


@dataclass(frozen=True)
class PendingDecision:
    summary: str
    age_hours: float
    source: str  # "consensus" | "self_mod" | "qualification" | "gap"


@dataclass(frozen=True)
class AnomalyWindow:
    label: str
    triggered_at: float
    severity: str  # "info" | "warning" | "critical"


@dataclass
class InsightsReport:
    """Structured aggregation. Renderable as Markdown or JSON."""

    window_days: int
    generated_at: float
    top_topics: list[TopicCount] = field(default_factory=list)
    top_crew: list[CrewInteraction] = field(default_factory=list)
    scheduled_tasks_completed: list[ScheduledTask] = field(default_factory=list)
    pending_decisions: list[PendingDecision] = field(default_factory=list)
    anomaly_windows: list[AnomalyWindow] = field(default_factory=list)
    narrative_summary: str = ""  # Fast-tier LLM rendering; empty on honest-degrade.

    def is_empty(self) -> bool:
        return not (
            self.top_topics
            or self.top_crew
            or self.scheduled_tasks_completed
            or self.pending_decisions
            or self.anomaly_windows
        )

    def to_markdown(self) -> str:
        """Render as channel-agnostic Markdown."""
        if self.is_empty():
            return f"## Insights — last {self.window_days} day(s)\n\n_No activity recorded in this window._\n"

        lines: list[str] = [f"## Insights — last {self.window_days} day(s)\n"]

        if self.narrative_summary:
            lines.append(self.narrative_summary)
            lines.append("")

        if self.top_topics:
            lines.append("**Top topics**")
            for t in self.top_topics:
                lines.append(f"- {t.label} ({t.count} recalls)")
            lines.append("")

        if self.top_crew:
            lines.append("**Top crew interactions**")
            for c in self.top_crew:
                lines.append(f"- {c.callsign}: {c.message_count} message(s)")
            lines.append("")

        if self.scheduled_tasks_completed:
            lines.append(f"**Scheduled tasks completed:** {len(self.scheduled_tasks_completed)}")
            lines.append("")

        if self.pending_decisions:
            lines.append("**Pending decisions**")
            for d in self.pending_decisions:
                lines.append(f"- [{d.source}] {d.summary} ({d.age_hours:.1f}h)")
            lines.append("")

        if self.anomaly_windows:
            lines.append("**Anomaly windows**")
            for a in self.anomaly_windows:
                lines.append(f"- [{a.severity}] {a.label}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def to_json(self) -> dict[str, Any]:
        """Render as JSON-serializable dict for /api/insights."""
        return {
            "window_days": self.window_days,
            "generated_at": self.generated_at,
            "top_topics": [{"label": t.label, "count": t.count} for t in self.top_topics],
            "top_crew": [
                {"callsign": c.callsign, "message_count": c.message_count, "last_active_ts": c.last_active_ts}
                for c in self.top_crew
            ],
            "scheduled_tasks_completed": [
                {"description": s.description, "completed_at": s.completed_at}
                for s in self.scheduled_tasks_completed
            ],
            "pending_decisions": [
                {"summary": d.summary, "age_hours": d.age_hours, "source": d.source}
                for d in self.pending_decisions
            ],
            "anomaly_windows": [
                {"label": a.label, "triggered_at": a.triggered_at, "severity": a.severity}
                for a in self.anomaly_windows
            ],
            "narrative_summary": self.narrative_summary,
        }


class InsightService:
    """Aggregate recent-activity insights from existing stores.

    Pure read-side; uses ``hasattr`` guards on every source so missing
    upstream APIs honest-degrade to an empty section rather than blank
    the whole report.
    """

    # Working-memory budget for the fast-tier summarizer (same shape AD-794
    # uses for thread naming). Conservative to keep summaries snappy.
    SUMMARY_TOKEN_BUDGET: int = 1024

    def __init__(
        self,
        runtime: "ProbOSRuntime",
        *,
        llm_client: "BaseLLMClient | None" = None,
    ) -> None:
        self._runtime = runtime
        # Honest-degrade: if no fast-tier client, narrative_summary stays "".
        self._llm_client = llm_client

    async def build_report(self, days: int = 7) -> InsightsReport:
        """Aggregate insights for the given window."""
        now = time.time()
        since = now - (days * 86400.0)
        report = InsightsReport(window_days=days, generated_at=now)

        # Each section uses log-and-degrade per the engineering principles —
        # one missing store should not blank the whole report.
        try:
            report.top_topics = await self._top_topics(since)
        except Exception as exc:
            logger.warning(
                "Insights: top_topics aggregation failed (%s); section will be empty in report", exc
            )

        try:
            report.top_crew = await self._top_crew(since)
        except Exception as exc:
            logger.warning(
                "Insights: top_crew aggregation failed (%s); section will be empty in report", exc
            )

        try:
            report.scheduled_tasks_completed = await self._scheduled_tasks_completed(since)
        except Exception as exc:
            logger.warning(
                "Insights: scheduled_tasks_completed aggregation failed (%s); section will be empty in report",
                exc,
            )

        try:
            report.pending_decisions = await self._pending_decisions(now)
        except Exception as exc:
            logger.warning(
                "Insights: pending_decisions aggregation failed (%s); section will be empty in report",
                exc,
            )

        try:
            report.anomaly_windows = await self._anomaly_windows(since)
        except Exception as exc:
            logger.warning(
                "Insights: anomaly_windows aggregation failed (%s); section will be empty in report",
                exc,
            )

        # Fast-tier narrative summary — honest-degrade on missing client.
        if self._llm_client is not None and not report.is_empty():
            try:
                report.narrative_summary = await self._summarize(report)
            except Exception as exc:
                logger.warning(
                    "Insights: narrative summarization failed (%s); falling back to structured-only output",
                    exc,
                )

        return report

    async def _top_topics(self, since: float) -> list[TopicCount]:
        """Top topics by episodic recall frequency in the window."""
        episodic = getattr(self._runtime, "episodic_memory", None)
        if episodic is None or not hasattr(episodic, "cluster_recall_counts"):
            return []
        candidates = await episodic.cluster_recall_counts(since=since)
        return [TopicCount(label=label, count=count) for label, count in candidates[:10]]

    async def _top_crew(self, since: float) -> list[CrewInteraction]:
        """Most-active crew callsigns by DM/session message volume in window."""
        threads_store = getattr(self._runtime, "thread_store", None)
        if threads_store is None or not hasattr(threads_store, "recent_threads_by_crew"):
            return []
        records = await threads_store.recent_threads_by_crew(since=since)
        return [
            CrewInteraction(
                callsign=r["callsign"],
                message_count=r["count"],
                last_active_ts=r["last_ts"],
            )
            for r in records[:10]
        ]

    async def _scheduled_tasks_completed(self, since: float) -> list[ScheduledTask]:
        """Watch-bill / scheduled-task completions in window."""
        watch = getattr(self._runtime, "watch_bill", None)
        if watch is None or not hasattr(watch, "completed_since"):
            return []
        records = await watch.completed_since(since)
        return [ScheduledTask(description=r["description"], completed_at=r["ts"]) for r in records]

    async def _pending_decisions(self, now: float) -> list[PendingDecision]:
        """Cross-source pending operator decisions (unresolved at ``now``)."""
        out: list[PendingDecision] = []
        consensus = getattr(self._runtime, "consensus_manager", None)
        if consensus is not None and hasattr(consensus, "pending_votes"):
            for v in await consensus.pending_votes():
                out.append(
                    PendingDecision(
                        summary=v["summary"],
                        age_hours=(now - v["created_at"]) / 3600.0,
                        source="consensus",
                    )
                )
        self_mod = getattr(self._runtime, "self_mod_pipeline", None)
        if self_mod is not None and hasattr(self_mod, "pending_proposals"):
            for p in await self_mod.pending_proposals():
                out.append(
                    PendingDecision(
                        summary=p["title"],
                        age_hours=(now - p["created_at"]) / 3600.0,
                        source="self_mod",
                    )
                )
        return out

    async def _anomaly_windows(self, since: float) -> list[AnomalyWindow]:
        """Anomaly-detector triggers (vision-budget breaches, gap reports, etc.)."""
        out: list[AnomalyWindow] = []
        vision_budget = getattr(self._runtime, "vision_budget", None)
        if vision_budget is not None and hasattr(vision_budget, "recent_breaches"):
            for b in await vision_budget.recent_breaches(since=since):
                out.append(
                    AnomalyWindow(
                        label=f"vision budget: {b['kind']}",
                        triggered_at=b["ts"],
                        severity=b.get("severity", "warning"),
                    )
                )
        return out

    async def _summarize(self, report: InsightsReport) -> str:
        """Fast-tier LLM narrative — one paragraph, plain Markdown."""
        if self._llm_client is None:
            return ""
        from probos.types import LLMRequest

        sections: list[str] = []
        if report.top_topics:
            sections.append(
                "Top topics: " + ", ".join(f"{t.label}({t.count})" for t in report.top_topics[:5])
            )
        if report.top_crew:
            sections.append(
                "Top crew: " + ", ".join(f"{c.callsign}({c.message_count})" for c in report.top_crew[:5])
            )
        if report.scheduled_tasks_completed:
            sections.append(f"Tasks completed: {len(report.scheduled_tasks_completed)}")
        if report.pending_decisions:
            sections.append(f"Pending decisions: {len(report.pending_decisions)}")
        if report.anomaly_windows:
            sections.append("Anomalies: " + ", ".join(a.label for a in report.anomaly_windows[:3]))

        prompt = (
            f"Summarize the last {report.window_days} days of ProbOS operator activity "
            f"in 2-3 sentences of plain Markdown. Source data:\n"
            + "\n".join(sections)
        )

        result = await self._llm_client.complete(
            LLMRequest(prompt=prompt, tier="fast", max_tokens=self.SUMMARY_TOKEN_BUDGET),
        )
        # LLMResponse uses `.content`; test fakes use `.text`. Support both.
        text = getattr(result, "content", None)
        if not text:
            text = getattr(result, "text", "")
        return (text or "").strip()
