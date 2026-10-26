"""AD-810: operator-facing recent-activity summary.

Pure aggregation service. No new persistence. BF-925 (#1655): every section
named a method no production class defines, so the report was always empty.
Three sections read real sources (Bridge alerts, the Captain's capability and
skill request queues, completed persistent tasks); topics and crew have no
source, and the report says "not available" for them.
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

# BF-925 (#1655): the sections with no source. Each named a method no production class defines
# (an episodic ``cluster_recall_counts``; a runtime ``thread_store`` with ``recent_threads_by_crew``).
_NO_SOURCE: dict[str, str] = {
    "top_topics": "no store records recall frequency by topic",
    "top_crew": "no store counts DM or session messages per crew member",
}
_SECTION_LABELS: dict[str, str] = {
    "top_topics": "top topics",
    "top_crew": "top crew interactions",
    "scheduled_tasks_completed": "scheduled tasks",
    "pending_decisions": "pending decisions",
    "anomaly_windows": "anomaly windows",
}
_SEVERITY: dict[str, str] = {"info": "info", "advisory": "warning", "alert": "critical"}  # AlertSeverity values
_MAX_COMPLETED_TASKS = 200
_MAX_PER_QUEUE = 20
_ALERT_LOG_READ = 200  # BridgeAlertService keeps its newest 200 alerts
_MAX_ANOMALIES = 20


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
    source: str  # "capability_request" | "skill_request" (BF-925)


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
    top_topics: list[TopicCount] = field(default_factory=list)  # BF-925: no source; always empty
    top_crew: list[CrewInteraction] = field(default_factory=list)  # BF-925: no source; always empty
    scheduled_tasks_completed: list[ScheduledTask] = field(default_factory=list)
    pending_decisions: list[PendingDecision] = field(default_factory=list)
    anomaly_windows: list[AnomalyWindow] = field(default_factory=list)
    narrative_summary: str = ""  # Fast-tier LLM rendering; empty on honest-degrade.
    # BF-925 (#1655): section name -> why it is not available (no source, not running, failed).
    unavailable: dict[str, str] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (
            self.top_topics
            or self.top_crew
            or self.scheduled_tasks_completed
            or self.pending_decisions
            or self.anomaly_windows
        )

    def _not_available_line(self) -> str:
        """BF-925 (#1655): one line naming each section that is not available, with its reason."""
        if not self.unavailable:
            return ""
        parts = "; ".join(f"{_SECTION_LABELS[name]} ({reason})" for name, reason in self.unavailable.items())
        return f"_Not available: {parts}._\n"

    def to_markdown(self) -> str:
        """Render as channel-agnostic Markdown."""
        if self.is_empty():
            empty = f"## Insights — last {self.window_days} day(s)\n\n_No activity recorded in this window._\n"
            not_available = self._not_available_line()
            return empty + ("\n" + not_available if not_available else "")

        lines: list[str] = [f"## Insights — last {self.window_days} day(s)\n"]

        if self.narrative_summary:
            lines.append(self.narrative_summary)
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

        if self.unavailable:
            lines.append(self._not_available_line())

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
            "unavailable": dict(self.unavailable),  # BF-925 (#1655): additive; every other key is unchanged
        }


class InsightService:
    """Aggregate recent-activity insights from existing stores.

    Pure read-side. BF-925 (#1655): the ``hasattr`` guards this used named
    methods nothing defines, so every section was silently empty. Sources are
    read directly; one that is down or fails is reported as not available in
    its own section and never blanks the report.
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
        # one missing store should not blank the whole report. BF-925 (#1655): a section
        # whose source is down or fails says so in ``unavailable`` instead of reading empty.
        report.unavailable.update(_NO_SOURCE)
        for name, gather, bound in (
            ("scheduled_tasks_completed", self._scheduled_tasks_completed, since),
            ("pending_decisions", self._pending_decisions, now),
            ("anomaly_windows", self._anomaly_windows, since),
        ):
            try:
                rows = await gather(bound)
            except Exception as exc:
                logger.warning(
                    "Insights: %s aggregation failed (%s); the report shows it as not available", name, exc,
                )
                report.unavailable[name] = f"failed ({type(exc).__name__})"
                continue
            if rows is None:
                report.unavailable[name] = "service not running"
            else:
                setattr(report, name, rows)

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

    async def _scheduled_tasks_completed(self, since: float) -> list[ScheduledTask] | None:
        """Persistent tasks that completed in the window; ``None`` when the store is not running.

        BF-925 (#1655): ``watch_bill.completed_since`` never existed. A task completes on its final
        run (``once``, or ``max_runs`` reached); a recurring task stays pending and is not counted.
        Reads the newest ``_MAX_COMPLETED_TASKS`` completed tasks by creation time.
        """
        store = self._runtime.persistent_task_store
        if store is None:
            return None
        tasks = await store.list_tasks(status="completed", limit=_MAX_COMPLETED_TASKS)
        return [
            ScheduledTask(description=t.name, completed_at=t.last_run_at)
            for t in tasks
            if t.last_run_at is not None and t.last_run_at >= since
        ]

    async def _pending_decisions(self, now: float) -> list[PendingDecision] | None:
        """Requests awaiting the Captain: capability and skill requests, oldest first.

        BF-925 (#1655): ``consensus_manager.pending_votes`` and ``self_mod_pipeline.pending_proposals``
        never existed. At most ``_MAX_PER_QUEUE`` per queue; ``None`` when neither queue is running.
        """
        capability = self._runtime.capability_request_store
        skills = self._runtime.skill_request_store
        if capability is None and skills is None:
            return None
        out: list[PendingDecision] = []
        if capability is not None:
            for req in sorted(await capability.list_pending(), key=lambda r: r.created_at)[:_MAX_PER_QUEUE]:
                out.append(PendingDecision(
                    summary=f"{req.kind} {req.target}",
                    age_hours=(now - req.created_at) / 3600.0,
                    source="capability_request",
                ))
        if skills is not None:
            for req in sorted(await skills.list_pending(), key=lambda r: r.created_at)[:_MAX_PER_QUEUE]:
                out.append(PendingDecision(
                    summary=f"skill {req.skill_label or req.skill_id}",
                    age_hours=(now - req.created_at) / 3600.0,
                    source="skill_request",
                ))
        return out

    async def _anomaly_windows(self, since: float) -> list[AnomalyWindow] | None:
        """Bridge alerts raised in the window, newest first; ``None`` when the service is not running.

        BF-925 (#1655): ``vision_budget.recent_breaches`` never existed. The alert log is in memory
        (the newest 200 since boot), so a window that reaches before boot shows this session's
        alerts. At most ``_MAX_ANOMALIES``.
        """
        alerts = self._runtime.bridge_alerts
        if alerts is None:
            return None
        recent = [a for a in alerts.get_recent_alerts(limit=_ALERT_LOG_READ) if a.timestamp >= since]
        return [
            AnomalyWindow(label=f"{a.source}: {a.title}", triggered_at=a.timestamp, severity=_SEVERITY[a.severity.value])
            for a in reversed(recent[-_MAX_ANOMALIES:])
        ]

    async def _summarize(self, report: InsightsReport) -> str:
        """Fast-tier LLM narrative — one paragraph, plain Markdown."""
        if self._llm_client is None:
            return ""
        from probos.types import LLMRequest

        sections: list[str] = []  # BF-925 (#1655): topics and crew have no source, so no line
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
