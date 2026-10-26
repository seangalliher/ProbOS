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


from probos.bridge_alerts import AlertSeverity, BridgeAlert
from probos.capability_request import CapabilityRequest

# BF-925 (#1655): these fakes used to define ``cluster_recall_counts`` and ``recent_threads_by_crew``,
# which no production class defines, so the tests passed while the report was always empty. They now
# stand for the real stores by the real method names; tests/test_bf925_silent_guards.py pins each
# signature to its class, and the alert and request objects are the real dataclasses.


@dataclass
class _FakeAlerts:
    alerts: list[Any]

    def get_recent_alerts(self, limit: int = 50) -> list[Any]:
        return self.alerts[-limit:]


@dataclass
class _FakeRequests:
    requests: list[Any]

    async def list_pending(self) -> list[Any]:
        return list(self.requests)


def _alert(source: str, title: str, timestamp: float, severity: AlertSeverity) -> BridgeAlert:
    return BridgeAlert(
        id="alert-1", severity=severity, source=source, alert_type="test", title=title,
        detail="", department=None, dedup_key="test", timestamp=timestamp,
    )


def _request(target: str, created_at: float, kind: str = "grant") -> CapabilityRequest:
    return CapabilityRequest(id=f"req-{target}", agent_id="agent-1", kind=kind, target=target, created_at=created_at)


class _FakeRuntime:
    """The four runtime attributes InsightService reads (ProbOSRuntime declares each, default None)."""

    def __init__(
        self,
        *,
        bridge_alerts: Any = None,
        capability_request_store: Any = None,
        skill_request_store: Any = None,
        persistent_task_store: Any = None,
    ) -> None:
        self.bridge_alerts = bridge_alerts
        self.capability_request_store = capability_request_store
        self.skill_request_store = skill_request_store
        self.persistent_task_store = persistent_task_store


@pytest.mark.asyncio
async def test_build_report_happy_path_aggregates_all_sources():
    """Anomalies (Bridge alerts) and pending decisions (capability requests) aggregate in one report.

    BF-925 (#1655): topics and crew have no source and say so; this test used to pin both from fakes
    of methods nothing defines.
    """
    now = time.time()
    runtime = _FakeRuntime(
        bridge_alerts=_FakeAlerts(alerts=[_alert("trust_network", "Trust Drop", now - 60, AlertSeverity.ALERT)]),
        capability_request_store=_FakeRequests(requests=[_request("shell", now - 7200)]),
    )
    service = InsightService(runtime=runtime, llm_client=None)
    report = await service.build_report(days=7)
    assert report.window_days == 7
    assert [(a.label, a.severity) for a in report.anomaly_windows] == [("trust_network: Trust Drop", "critical")]
    assert [(d.source, d.summary) for d in report.pending_decisions] == [("capability_request", "grant shell")]
    assert report.pending_decisions[0].age_hours == pytest.approx(2.0, abs=0.01)
    assert set(report.unavailable) == {"top_topics", "top_crew", "scheduled_tasks_completed"}
    assert report.narrative_summary == ""  # honest-degrade without llm_client


@pytest.mark.asyncio
async def test_build_report_empty_state_renders_no_activity_marker():
    """No source running: the report is empty and names each section that is not available."""
    runtime = _FakeRuntime()
    service = InsightService(runtime=runtime, llm_client=None)
    report = await service.build_report(days=14)
    assert report.is_empty()
    md = report.to_markdown()
    assert "last 14 day(s)" in md
    assert "No activity recorded" in md
    assert "Not available: top topics (no store records recall frequency by topic)" in md  # BF-925
    assert "anomaly windows (service not running)" in md


@pytest.mark.asyncio
async def test_build_report_failing_source_does_not_blank_other_sources():
    """One section raising is reported not available; the others stay intact (log-and-degrade)."""

    class _BrokenAlerts:
        def get_recent_alerts(self, limit: int = 50):
            raise RuntimeError("boom")

    runtime = _FakeRuntime(
        bridge_alerts=_BrokenAlerts(),
        capability_request_store=_FakeRequests(requests=[_request("shell", time.time())]),
    )
    service = InsightService(runtime=runtime, llm_client=None)
    report = await service.build_report(days=7)
    assert report.anomaly_windows == []
    assert report.unavailable["anomaly_windows"] == "failed (RuntimeError)"  # BF-925: not silently empty
    assert len(report.pending_decisions) == 1


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
        capability_request_store=_FakeRequests(requests=[_request("weather tool", time.time(), kind="build")]),
    )
    service = InsightService(runtime=runtime, llm_client=_FakeLLM())
    report = await service.build_report(days=7)
    assert report.narrative_summary == "Operator activity was steady this week."
    assert _FakeLLM.captured["tier"] == "fast"
    assert "Pending decisions: 1" in _FakeLLM.captured["prompt"]


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
