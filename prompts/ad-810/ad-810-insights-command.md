# AD-810 — `/insights [--days N]` operator-facing recent-activity summary

**Status:** Ready for Builder
**Dependencies:** AD-432 (CognitiveJournal), AD-579 (memory architecture), AD-794 (auto-named threads), AD-742e (vision budget telemetry), dreaming consolidation (`DreamScheduler._last_dream_report`)
**Estimated tests:** +6 pytest in `tests/test_ad810_insights.py`
**Closes:** #734
**Out of scope (defer to follow-ups):** per-channel rich formatting (Slack mrkdwn, Discord embeds, Telegram MarkdownV2) → AD-810a; HXI button/popover surface → AD-810b.

---

## Problem

GitHub #734 requests an operator-facing summary surface. Today, the dreaming consolidation pipeline (AD-432 + AD-579) produces structured insights internally (top recalled clusters, anomaly windows, procedure evolutions, gap reports), and AD-794 names threads automatically, and AD-742e tracks vision budget telemetry — but no single operator-visible surface stitches these together. The Captain has to run `/dream`, `/memory`, `/recall`, plus inspect logs to assemble a weekly view.

Per the issue:

> Hermes ships this; ProbOS dreaming consolidation does the work internally already - missing piece is the operator-facing surface.

Output sections (verbatim from issue):
- Top topics by recall frequency
- Top crew interactions
- Scheduled tasks completed
- Pending decisions still open
- Anomaly windows triggered

Default window: 7 days. Form: `/insights` (default 7) or `/insights 14` or `/insights --days 14`.

The slash-command surface MUST work in HXI chat AND CLI terminal AND through every paired channel adapter, because `src/probos/api.py:68 _handle_slash_command` already routes channel/HXI slash commands through the same `ProbOSShell.execute_command` path. A single handler wired into `experience/shell.py` covers all three surfaces with zero adapter changes.

---

## Solution

1. New `src/probos/cognitive/insights.py` exposing `InsightService` that aggregates from existing stores. Pure read-side service; no new persistence.
2. New `tests/test_ad810_insights.py` covering source aggregation, summarizer prompt, empty-state fallback, slash-command parsing, and API endpoint shape.
3. New slash command handler `src/probos/experience/commands/commands_insights.py` (`cmd_insights`), wired from `experience/shell.py` `COMMANDS` dict + `_dispatch_slash` `handlers` dict.
4. New API route `GET /api/insights?days=N` in `src/probos/routers/insights.py` (registered like the other domain routers).
5. Fast-tier LLM summarization on the same working-memory budget shape AD-794 thread-naming uses (`tier="fast"`, token-capped prompt). Honest-degrade when LLM unavailable: return the structured report without the narrative summary.

---

## Section 0: Source-of-truth verification (Builder must verify before edits)

Run these greps and confirm before any code change. Stop and report if any line is missing:

```
grep -n "class CognitiveJournal" src/probos/cognitive/journal.py
  178: class CognitiveJournal:

grep -n "async def recent_for_agent" src/probos/cognitive/journal.py
  799: async def recent_for_agent(

grep -n "class DreamReport" src/probos/types.py
  512: class DreamReport:

grep -n "_last_dream_report" src/probos/cognitive/dreaming.py
  2856: self._last_dream_report: DreamReport | None = None
  2868: def last_dream_report(self) -> DreamReport | None:

grep -n "async def _handle_slash_command" src/probos/api.py
  68: async def _handle_slash_command(text: str, runtime: Any) -> dict[str, Any]:

grep -n '"/help":' src/probos/experience/shell.py
  114:        "/help":      "Show this help message",
  253:            "/help":       lambda: commands_status.cmd_help(con, self.COMMANDS),
```

If `CognitiveJournal` does NOT already expose a `recent_entries(since_ts: float, limit: int)` method (it currently has `recent_for_agent`, `get_token_usage_since`, `get_recent_chain_traces` but no generic time-window scan), add it in Section 2.

---

## Section 1: `InsightService`

Create `src/probos/cognitive/insights.py`:

```python
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
    from probos.runtime import ProbOSRuntime
    from probos.cognitive.llm_client import LLMClient

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
            self.top_topics or self.top_crew or self.scheduled_tasks_completed
            or self.pending_decisions or self.anomaly_windows
        )

    def to_markdown(self) -> str:
        """Render as channel-agnostic Markdown."""
        # Implementation in Section 1b.
        ...

    def to_json(self) -> dict[str, Any]:
        """Render as JSON-serializable dict for /api/insights."""
        # Implementation in Section 1c.
        ...


class InsightService:
    """Aggregate recent-activity insights from existing stores."""

    # Working-memory budget for the fast-tier summarizer (same shape AD-794
    # uses for thread naming). Conservative to keep summaries snappy.
    SUMMARY_TOKEN_BUDGET: int = 1024

    def __init__(
        self,
        runtime: ProbOSRuntime,
        *,
        llm_client: LLMClient | None = None,
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
            logger.warning("Insights: top_topics failed (%s); section will be empty", exc)

        try:
            report.top_crew = await self._top_crew(since)
        except Exception as exc:
            logger.warning("Insights: top_crew failed (%s); section will be empty", exc)

        try:
            report.scheduled_tasks_completed = await self._scheduled_tasks_completed(since)
        except Exception as exc:
            logger.warning("Insights: scheduled_tasks_completed failed (%s); section will be empty", exc)

        try:
            report.pending_decisions = await self._pending_decisions(now)
        except Exception as exc:
            logger.warning("Insights: pending_decisions failed (%s); section will be empty", exc)

        try:
            report.anomaly_windows = await self._anomaly_windows(since)
        except Exception as exc:
            logger.warning("Insights: anomaly_windows failed (%s); section will be empty", exc)

        # Fast-tier narrative summary — honest-degrade on missing client.
        if self._llm_client is not None and not report.is_empty():
            try:
                report.narrative_summary = await self._summarize(report)
            except Exception as exc:
                logger.warning("Insights: narrative summarization failed (%s); falling back to structured-only output", exc)

        return report

    async def _top_topics(self, since: float) -> list[TopicCount]:
        """Top topics by episodic recall frequency in the window."""
        episodic = getattr(self._runtime, "episodic_memory", None)
        if episodic is None:
            return []
        # Episodic memory exposes a recall counter per cluster (AD-531).
        # Read the most-recalled clusters in the window via the store's
        # public API and group by cluster label.
        # Concrete shape: rely on the EpisodicMemory's existing
        # `recent_recalls(since)` or `cluster_recall_counts(since)` method.
        # Builder: verify which is present and use it; if neither is
        # present, fall back to scanning episodes since `since` and counting
        # `cluster_label` occurrences.
        candidates = await episodic.cluster_recall_counts(since=since) \
            if hasattr(episodic, "cluster_recall_counts") else []
        return [TopicCount(label=label, count=count) for label, count in candidates[:10]]

    async def _top_crew(self, since: float) -> list[CrewInteraction]:
        """Most-active crew callsigns by DM/session message volume in window."""
        # Pull from runtime's channel/session conversation histories if
        # the SessionManager exposes a per-callsign aggregate; otherwise
        # scan the threads namer's recent named-thread records (AD-794).
        threads_store = getattr(self._runtime, "thread_store", None)
        if threads_store is None or not hasattr(threads_store, "recent_threads_by_crew"):
            return []
        records = await threads_store.recent_threads_by_crew(since=since)
        return [
            CrewInteraction(callsign=r["callsign"], message_count=r["count"], last_active_ts=r["last_ts"])
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
        """Cross-source pending operator decisions (unresolved at `now`)."""
        out: list[PendingDecision] = []
        # Consensus pending votes
        consensus = getattr(self._runtime, "consensus_manager", None)
        if consensus is not None and hasattr(consensus, "pending_votes"):
            for v in await consensus.pending_votes():
                out.append(PendingDecision(
                    summary=v["summary"],
                    age_hours=(now - v["created_at"]) / 3600.0,
                    source="consensus",
                ))
        # Self-mod proposals awaiting approval
        self_mod = getattr(self._runtime, "self_mod_pipeline", None)
        if self_mod is not None and hasattr(self_mod, "pending_proposals"):
            for p in await self_mod.pending_proposals():
                out.append(PendingDecision(
                    summary=p["title"],
                    age_hours=(now - p["created_at"]) / 3600.0,
                    source="self_mod",
                ))
        return out

    async def _anomaly_windows(self, since: float) -> list[AnomalyWindow]:
        """Anomaly-detector triggers (vision-budget breaches, gap reports, etc.)."""
        out: list[AnomalyWindow] = []
        # AD-742e vision budget telemetry
        vision_budget = getattr(self._runtime, "vision_budget", None)
        if vision_budget is not None and hasattr(vision_budget, "recent_breaches"):
            for b in await vision_budget.recent_breaches(since=since):
                out.append(AnomalyWindow(
                    label=f"vision budget: {b['kind']}",
                    triggered_at=b["ts"],
                    severity=b.get("severity", "warning"),
                ))
        return out

    async def _summarize(self, report: InsightsReport) -> str:
        """Fast-tier LLM narrative — one paragraph, plain Markdown."""
        if self._llm_client is None:
            return ""
        from probos.cognitive.llm_client import LLMRequest

        # Build a compact context bounded by SUMMARY_TOKEN_BUDGET. Use the
        # same shape AD-794 uses (one terse user turn, system identity in
        # the prompt prefix).
        sections: list[str] = []
        if report.top_topics:
            sections.append("Top topics: " + ", ".join(f"{t.label}({t.count})" for t in report.top_topics[:5]))
        if report.top_crew:
            sections.append("Top crew: " + ", ".join(f"{c.callsign}({c.message_count})" for c in report.top_crew[:5]))
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
        return result.text.strip()
```

### Section 1b: `InsightsReport.to_markdown`

Inside the `InsightsReport.to_markdown` method:

```python
def to_markdown(self) -> str:
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
```

### Section 1c: `InsightsReport.to_json`

```python
def to_json(self) -> dict[str, Any]:
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
```

---

## Section 2: Hook `InsightService` onto the runtime

In `src/probos/runtime.py`, find where other cognitive services are constructed (search for `self.dream_scheduler` or `self.self_mod_pipeline`) and wire `InsightService` similarly:

```
SEARCH:
# (paste 3+ lines of unchanged context Builder will locate, e.g. the line
#  that assigns self.dream_scheduler or another cognitive service)

REPLACE:
# (same lines + new line constructing self.insight_service)
```

Builder: locate the cognitive-service wiring block and insert:

```python
# AD-810: operator-facing recent-activity summary
from probos.cognitive.insights import InsightService
self.insight_service = InsightService(
    runtime=self,
    llm_client=self.llm_client,  # fast tier honest-degrades if not configured
)
```

If `self.llm_client` is constructed AFTER the cognitive-service block, defer the `InsightService` construction until after the LLM client exists. The constructor accepts `llm_client=None`, so a late assignment via `self.insight_service._llm_client = self.llm_client` after the LLM client is built is acceptable — but the cleaner pattern (used by other late-bound services) is to construct `InsightService` immediately after the LLM client. Pick the cleaner option.

---

## Section 3: Slash command — `commands_insights.py`

Create `src/probos/experience/commands/commands_insights.py`:

```python
"""AD-810: /insights slash command."""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown

from probos.runtime import ProbOSRuntime


_DEFAULT_DAYS = 7
_MAX_DAYS = 90


def _parse_days(args: str) -> int:
    """Parse `/insights`, `/insights 14`, or `/insights --days 14`."""
    args = args.strip()
    if not args:
        return _DEFAULT_DAYS
    tokens = args.split()
    if tokens[0] == "--days" and len(tokens) >= 2:
        candidate = tokens[1]
    else:
        candidate = tokens[0]
    try:
        days = int(candidate)
    except ValueError:
        return _DEFAULT_DAYS
    return max(1, min(_MAX_DAYS, days))


async def cmd_insights(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /insights [--days N]."""
    service = getattr(runtime, "insight_service", None)
    if service is None:
        console.print("[yellow]Insights service not available on this runtime.[/yellow]")
        return
    days = _parse_days(args)
    report = await service.build_report(days=days)
    console.print(Markdown(report.to_markdown()))
```

---

## Section 4: Wire into `experience/shell.py`

Two edits in `src/probos/experience/shell.py`:

### 4a: import

Search for the existing `commands_*` imports near the top of the file. Add:

```
SEARCH:
from probos.experience.commands import commands_status

REPLACE:
from probos.experience.commands import commands_status
from probos.experience.commands import commands_insights
```

(Use whatever `commands_status` import already exists as the anchor; the new import line goes adjacent. If imports are aggregated differently, follow the existing pattern.)

### 4b: COMMANDS help entry

Search for `"/help":      "Show this help message",` in the `COMMANDS` dict. Insert a new line **before** it:

```
SEARCH:
        "/diagnostic": "Run a multi-level system diagnostic (/diagnostic [<level>] [<focus>]) — AD-700a",
        "/debug":     "Toggle debug mode (/debug on|off)",
        "/help":      "Show this help message",

REPLACE:
        "/diagnostic": "Run a multi-level system diagnostic (/diagnostic [<level>] [<focus>]) — AD-700a",
        "/debug":     "Toggle debug mode (/debug on|off)",
        "/insights":  "Show recent-activity summary (/insights [--days N], default 7)",
        "/help":      "Show this help message",
```

### 4c: dispatch handler

Search for `"/help":       lambda: commands_status.cmd_help(con, self.COMMANDS),` in `_dispatch_slash`. Insert a new entry near the other `commands_status` entries:

```
SEARCH:
            "/debug":      lambda: commands_status.cmd_debug(rt, con, arg, shell=self),

REPLACE:
            "/debug":      lambda: commands_status.cmd_debug(rt, con, arg, shell=self),
            "/insights":   lambda: commands_insights.cmd_insights(rt, con, arg),
```

---

## Section 5: API route `GET /api/insights`

Create `src/probos/routers/insights.py`:

```python
"""AD-810: GET /api/insights operator-facing recent-activity summary."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["insights"])


@router.get("/insights")
async def get_insights(request: Request, days: int = Query(default=7, ge=1, le=90)) -> dict[str, Any]:
    """Return aggregated recent-activity insights as JSON."""
    runtime = request.app.state.runtime
    service = getattr(runtime, "insight_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Insights service not available")
    report = await service.build_report(days=days)
    return report.to_json()
```

Register the router in `src/probos/api.py`. Search for an adjacent router registration (e.g. the threads or voice router) and add:

```
SEARCH:
# (the line that does `app.include_router(<existing_router>)` for any cognitive
#  domain router — Builder picks the cleanest insertion point alongside peers)

REPLACE:
# (existing line + new line that includes the insights router)
```

Concrete addition:

```python
from probos.routers.insights import router as insights_router
app.include_router(insights_router)
```

---

## Section 6: Tests — `tests/test_ad810_insights.py`

Create exactly 6 tests covering the acceptance surface. Use real `InsightService` + `InsightsReport` with hand-built fake runtime stubs (NOT `MagicMock` at the runtime boundary — per the user-memory rule, MagicMock at substrate APIs auto-creates phantom attributes). Hand-write a minimal `_FakeRuntime` class with the attributes the service inspects:

```python
"""AD-810 — InsightService aggregation + /insights surface + API."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pytest

from probos.cognitive.insights import (
    AnomalyWindow,
    CrewInteraction,
    InsightService,
    InsightsReport,
    PendingDecision,
    ScheduledTask,
    TopicCount,
)


@dataclass
class _FakeEpisodic:
    counts: list[tuple[str, int]]
    async def cluster_recall_counts(self, since: float) -> list[tuple[str, int]]:
        return self.counts


@dataclass
class _FakeThreadStore:
    records: list[dict[str, Any]]
    async def recent_threads_by_crew(self, since: float) -> list[dict[str, Any]]:
        return self.records


class _FakeRuntime:
    def __init__(self, *, episodic=None, thread_store=None, watch_bill=None,
                 consensus_manager=None, self_mod_pipeline=None, vision_budget=None):
        self.episodic_memory = episodic
        self.thread_store = thread_store
        self.watch_bill = watch_bill
        self.consensus_manager = consensus_manager
        self.self_mod_pipeline = self_mod_pipeline
        self.vision_budget = vision_budget


@pytest.mark.asyncio
async def test_build_report_happy_path_aggregates_all_sources():
    """Top topics + top crew + pending decisions all aggregate in one report."""
    now = time.time()
    runtime = _FakeRuntime(
        episodic=_FakeEpisodic(counts=[("memory-architecture", 12), ("vision-pipeline", 7)]),
        thread_store=_FakeThreadStore(records=[
            {"callsign": "Tucker", "count": 18, "last_ts": now - 3600},
            {"callsign": "Ezri", "count": 11, "last_ts": now - 7200},
        ]),
    )
    service = InsightService(runtime=runtime, llm_client=None)
    report = await service.build_report(days=7)
    assert report.window_days == 7
    assert [t.label for t in report.top_topics] == ["memory-architecture", "vision-pipeline"]
    assert [c.callsign for c in report.top_crew] == ["Tucker", "Ezri"]
    assert report.narrative_summary == ""  # honest-degrade without llm_client


@pytest.mark.asyncio
async def test_build_report_empty_state_renders_no_activity_marker():
    """Empty runtime returns empty report; Markdown indicates the empty window."""
    runtime = _FakeRuntime()
    service = InsightService(runtime=runtime, llm_client=None)
    report = await service.build_report(days=14)
    assert report.is_empty()
    md = report.to_markdown()
    assert "last 14 day(s)" in md
    assert "No activity recorded" in md


@pytest.mark.asyncio
async def test_build_report_failing_source_does_not_blank_other_sources():
    """One section raising leaves the others intact (log-and-degrade)."""
    class _BrokenEpisodic:
        async def cluster_recall_counts(self, since: float):
            raise RuntimeError("boom")
    runtime = _FakeRuntime(
        episodic=_BrokenEpisodic(),
        thread_store=_FakeThreadStore(records=[{"callsign": "Tucker", "count": 5, "last_ts": time.time()}]),
    )
    service = InsightService(runtime=runtime, llm_client=None)
    report = await service.build_report(days=7)
    assert report.top_topics == []
    assert len(report.top_crew) == 1
    assert report.top_crew[0].callsign == "Tucker"


@pytest.mark.asyncio
async def test_narrative_summary_uses_fast_tier_llm():
    """When an LLM client is wired, narrative_summary is populated via fast tier."""
    class _FakeLLM:
        captured: dict[str, Any] = {}
        async def complete(self, request):
            _FakeLLM.captured["tier"] = request.tier
            _FakeLLM.captured["prompt"] = request.prompt
            class _Res:
                text = "Operator activity was steady this week."
            return _Res()
    runtime = _FakeRuntime(
        episodic=_FakeEpisodic(counts=[("memory-architecture", 12)]),
    )
    service = InsightService(runtime=runtime, llm_client=_FakeLLM())
    report = await service.build_report(days=7)
    assert report.narrative_summary == "Operator activity was steady this week."
    assert _FakeLLM.captured["tier"] == "fast"
    assert "memory-architecture" in _FakeLLM.captured["prompt"]


def test_parse_days_accepts_bare_int_and_flag_form():
    """`/insights 14`, `/insights --days 14`, `/insights` (default), invalid -> default."""
    from probos.experience.commands.commands_insights import _parse_days
    assert _parse_days("") == 7
    assert _parse_days("14") == 14
    assert _parse_days("--days 21") == 21
    assert _parse_days("garbage") == 7
    assert _parse_days("9999") == 90  # clamped to MAX
    assert _parse_days("0") == 1      # clamped to MIN


@pytest.mark.asyncio
async def test_api_endpoint_returns_json_shape():
    """GET /api/insights?days=N returns the to_json() shape, 503 when service is missing."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from probos.routers.insights import router

    # Service-present case
    app_ok = FastAPI()
    app_ok.include_router(router)
    class _Svc:
        async def build_report(self, days: int):
            return InsightsReport(
                window_days=days,
                generated_at=time.time(),
                top_topics=[TopicCount(label="x", count=3)],
            )
    app_ok.state.runtime = _FakeRuntime()
    app_ok.state.runtime.insight_service = _Svc()  # type: ignore[attr-defined]
    with TestClient(app_ok) as client:
        resp = client.get("/api/insights?days=3")
        assert resp.status_code == 200
        data = resp.json()
        assert data["window_days"] == 3
        assert data["top_topics"] == [{"label": "x", "count": 3}]
        assert "pending_decisions" in data

    # Service-absent case (503)
    app_missing = FastAPI()
    app_missing.include_router(router)
    app_missing.state.runtime = _FakeRuntime()  # no insight_service attribute
    with TestClient(app_missing) as client:
        resp = client.get("/api/insights")
        assert resp.status_code == 503
```

---

## What This Does NOT Change

- **No per-channel rich formatting.** Slack mrkdwn / Discord embed / Telegram MarkdownV2 variants are deferred to **AD-810a**. Channel adapters already route slash commands through `_handle_slash_command` in `src/probos/api.py:68`, which produces plain text via the shared shell handler. Markdown bullets render acceptably in all three channels today (verified pattern: every other slash command output uses the same path). Channel-specific embed shapes are an optimization that requires per-adapter wiring and is out of scope.
- **No new persistence.** `InsightService` is pure read-side. No new DB tables, no new ChromaDB collections, no new files under `data/`.
- **No HXI button / popover surface.** Deferred to **AD-810b**. The HXI chat already executes `/insights` via the existing slash-command path; a dedicated UI affordance is a follow-up.
- **No changes to `CognitiveJournal`, `DreamScheduler`, threads naming, or vision telemetry.** This AD only READS from them via their existing public methods. If a method the service expects is missing on the live store (verified by Section 0 greps), file a follow-up AD rather than extending the upstream store inside this prompt.
- **No introduction of `electron-store`-style deps.** Standard library + existing fast-tier LLM client only. Zero new dependencies.
- **No removal of `/dream`, `/recall`, `/memory`, or any existing slash command.** This is additive.
- **Do NOT modify any tracker (PROGRESS.md, DECISIONS.md, roadmap.md) in this commit.** Captain owns tracker updates and the working tree may carry tracker drift. Source code + tests only.

---

## Operational Constraints (Standing)

- **Do NOT touch the live runtime** under `C:\Users\seang\AppData\Local\ProbOS\`.
- **Do NOT broad-kill Python processes by path or name.** Use `scripts/kill-stale-pytest.ps1` (PID-aware) or specific `-Id` kills.
- Builder uses `pytest tests/ -q -n 4 --dist=loadfile` for the full gate; `pytest tests/test_ad810_insights.py -v -n 0` for the focused gate.

---

## Acceptance Criteria

1. `src/probos/cognitive/insights.py` exists with `InsightService`, `InsightsReport`, and the five dataclasses defined in Section 1. All public methods have full type annotations.
2. `src/probos/experience/commands/commands_insights.py` exists with `cmd_insights` + `_parse_days`.
3. `src/probos/experience/shell.py` has `"/insights"` in `COMMANDS` and a handler entry in `_dispatch_slash`.
4. `src/probos/routers/insights.py` exists with `GET /api/insights?days=N` and is registered in `src/probos/api.py`.
5. `InsightService` is constructed on the runtime alongside other cognitive services.
6. `tests/test_ad810_insights.py` exists with the 6 tests in Section 6 and all 6 pass under `pytest -n 0`.
7. Full regression gate: AD-820..AD-826 suite (69 tests per PROGRESS line 17) + BF-295 stays green under `pytest -n 4 --dist=loadfile`.
8. One commit titled `AD-810: /insights operator-facing recent-activity summary` with `Closes #734` in the body.
9. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-05-23)

```
grep -n "class CognitiveJournal" src/probos/cognitive/journal.py
  178: class CognitiveJournal:

grep -n "class DreamReport" src/probos/types.py
  512: class DreamReport:

grep -n "_last_dream_report" src/probos/cognitive/dreaming.py
  2856: self._last_dream_report: DreamReport | None = None
  2868: def last_dream_report(self) -> DreamReport | None:
  2935: async def force_dream(self) -> DreamReport:

grep -n "async def _handle_slash_command" src/probos/api.py
  68: async def _handle_slash_command(text: str, runtime: Any) -> dict[str, Any]:

grep -n '"/help":      "Show this help message"' src/probos/experience/shell.py
  114: "/help":      "Show this help message",

grep -n '"/help":       lambda: commands_status' src/probos/experience/shell.py
  253: "/help":       lambda: commands_status.cmd_help(con, self.COMMANDS),

grep -n "ChannelAdapter" src/probos/channels/base.py
  39: class ChannelAdapter(ABC):

grep -n "AD-794" src/probos/threads/naming.py
  5: AD-794 — auto-name

grep -n "tier=\"fast\"" src/probos/cognitive/dreaming.py
  2517: tier="fast",

gh issue view 734 (title)
  "AD-810: /insights slash command - operator-facing summary of recent activity (forward marker)"
```

Section 0's runtime-side greps (episodic recall counts API, threads store API, watch_bill API, consensus pending votes, self-mod pending proposals, vision_budget recent_breaches) are NOT pre-verified here; the spec uses `hasattr()` guards and honest-degrade so the Builder can confirm each source method exists and, if any are missing, leave that section empty rather than block the AD. This is the deliberate "operator-visible surface, structured-degrade" shape called out by the issue ("forward marker — no urgency").
