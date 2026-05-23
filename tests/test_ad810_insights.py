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
    def __init__(
        self,
        *,
        episodic: Any = None,
        thread_store: Any = None,
        watch_bill: Any = None,
        consensus_manager: Any = None,
        self_mod_pipeline: Any = None,
        vision_budget: Any = None,
    ) -> None:
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
        thread_store=_FakeThreadStore(
            records=[
                {"callsign": "Tucker", "count": 18, "last_ts": now - 3600},
                {"callsign": "Ezri", "count": 11, "last_ts": now - 7200},
            ]
        ),
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
        thread_store=_FakeThreadStore(
            records=[{"callsign": "Tucker", "count": 5, "last_ts": time.time()}]
        ),
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

        async def complete(self, request, *, priority=None):
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
    """``/insights 14``, ``/insights --days 14``, ``/insights`` (default), invalid -> default."""
    from probos.experience.commands.commands_insights import _parse_days

    assert _parse_days("") == 7
    assert _parse_days("14") == 14
    assert _parse_days("--days 21") == 21
    assert _parse_days("garbage") == 7
    assert _parse_days("9999") == 90  # clamped to MAX
    assert _parse_days("0") == 1  # clamped to MIN


@pytest.mark.asyncio
async def test_api_endpoint_returns_json_shape():
    """GET /api/insights?days=N returns the to_json() shape; 503 when service is missing."""
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

    class _RuntimeWithSvc(_FakeRuntime):
        pass

    rt_ok = _RuntimeWithSvc()
    rt_ok.insight_service = _Svc()  # type: ignore[attr-defined]
    app_ok.state.runtime = rt_ok
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
