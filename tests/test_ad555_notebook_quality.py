"""Tests for AD-555: Notebook Quality Metrics & Dashboarding."""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.knowledge.notebook_quality import (
    AgentNotebookQuality,
    NotebookQualityEngine,
    NotebookQualitySnapshot,
    _compute_agent_quality,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(
    author: str = "Chapel",
    topic: str = "trust-analysis",
    department: str = "Medical",
    revision: int = 1,
    updated: str | None = None,
    path: str = "notebooks/Chapel/trust-analysis.md",
) -> dict:
    if updated is None:
        updated = datetime.utcnow().isoformat()
    return {
        "path": path,
        "frontmatter": {
            "author": author,
            "topic": topic,
            "department": department,
            "revision": revision,
            "updated": updated,
        },
    }


def _make_stale_entry(author: str = "Chapel", topic: str = "old-observation", department: str = "Medical") -> dict:
    stale_time = (datetime.utcnow() - timedelta(hours=100)).isoformat()
    return _make_entry(author=author, topic=topic, department=department, updated=stale_time)


# ---------------------------------------------------------------------------
# TestAgentNotebookQuality
# ---------------------------------------------------------------------------


class TestAgentNotebookQuality:
    """Tests for _compute_agent_quality()."""

    def test_empty_entries_returns_zero_quality(self):
        aq = _compute_agent_quality("Chapel", [], 0.0)
        assert aq.quality_score == 0.0
        assert aq.callsign == "Chapel"
        assert aq.total_entries == 0

    def test_topic_diversity_computed(self):
        entries = [
            _make_entry(topic="topic-a"),
            _make_entry(topic="topic-b"),
            _make_entry(topic="topic-c"),
            _make_entry(topic="topic-a"),
            _make_entry(topic="topic-b"),
        ]
        aq = _compute_agent_quality("Chapel", entries, 0.0)
        assert aq.unique_topics == 3
        assert aq.total_entries == 5
        assert aq.entries_per_topic_avg == 1.7  # 5 / 3 rounded

    def test_stale_rate_computed(self):
        now = time.time()
        cutoff = now - (72 * 3600)
        stale_time = (datetime.utcnow() - timedelta(hours=100)).isoformat()
        fresh_time = datetime.utcnow().isoformat()
        entries = [
            _make_entry(topic="t1", updated=stale_time),
            _make_entry(topic="t2", updated=stale_time),
            _make_entry(topic="t3", updated=fresh_time),
        ]
        aq = _compute_agent_quality("Chapel", entries, cutoff)
        assert aq.stale_rate == round(2 / 3, 3)

    def test_novel_content_rate_counts_revision_1(self):
        entries = [
            _make_entry(topic="t1", revision=1),
            _make_entry(topic="t2", revision=3),
            _make_entry(topic="t3", revision=1),
            _make_entry(topic="t4", revision=2),
        ]
        aq = _compute_agent_quality("Chapel", entries, 0.0)
        assert aq.novel_content_rate == 0.5  # 2 out of 4

    def test_quality_score_formula(self):
        entries = [
            _make_entry(topic="t1", revision=1),
            _make_entry(topic="t2", revision=1),
        ]
        aq = _compute_agent_quality(
            "Chapel", entries, 0.0,
            convergence_contributions=0,
            repetition_alerts=0,
        )
        # topic_diversity = min(2/2, 1.0) = 1.0
        # freshness = 1.0 (no stale)
        # novelty = 1.0 (all revision 1)
        # convergence = 0/3 = 0.0
        # low_rep = 1.0 (no alerts)
        expected = round(0.30 * 1.0 + 0.25 * 1.0 + 0.25 * 1.0 + 0.10 * 0.0 + 0.10 * 1.0, 3)
        assert aq.quality_score == expected  # 0.9


# ---------------------------------------------------------------------------
# TestNotebookQualityEngine
# ---------------------------------------------------------------------------


class TestNotebookQualityEngine:
    """Tests for NotebookQualityEngine."""

    def test_engine_starts_empty(self):
        engine = NotebookQualityEngine()
        assert engine.latest_snapshot is None
        assert engine.snapshots == []

    def test_latest_snapshot_none_before_compute(self):
        engine = NotebookQualityEngine()
        assert engine.latest_snapshot is None

    @pytest.mark.asyncio
    async def test_compute_returns_valid_snapshot(self):
        engine = NotebookQualityEngine()
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[
            _make_entry(author="Chapel", topic="trust"),
            _make_entry(author="Dax", topic="analysis", department="Science"),
        ])
        snapshot = await engine.compute_quality_metrics(store)
        assert snapshot.total_entries == 2
        assert snapshot.total_agents == 2
        assert len(snapshot.per_agent) == 2

    @pytest.mark.asyncio
    async def test_compute_groups_by_author(self):
        engine = NotebookQualityEngine()
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[
            _make_entry(author="Chapel", topic="t1"),
            _make_entry(author="Chapel", topic="t2"),
            _make_entry(author="Dax", topic="t3", department="Science"),
        ])
        snapshot = await engine.compute_quality_metrics(store)
        callsigns = [a.callsign for a in snapshot.per_agent]
        assert "Chapel" in callsigns
        assert "Dax" in callsigns
        chapel = next(a for a in snapshot.per_agent if a.callsign == "Chapel")
        assert chapel.total_entries == 2

    @pytest.mark.asyncio
    async def test_system_quality_score_is_mean(self):
        engine = NotebookQualityEngine()
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[
            _make_entry(author="Chapel", topic="t1"),
            _make_entry(author="Dax", topic="t2", department="Science"),
        ])
        snapshot = await engine.compute_quality_metrics(store)
        expected = round(
            sum(a.quality_score for a in snapshot.per_agent) / len(snapshot.per_agent), 3
        )
        assert snapshot.system_quality_score == expected

    @pytest.mark.asyncio
    async def test_stale_entry_rate_computed(self):
        engine = NotebookQualityEngine(staleness_hours=72.0)
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[
            _make_stale_entry(author="Chapel"),
            _make_stale_entry(author="Dax", department="Science"),
            _make_entry(author="Cortez", department="Medical"),
        ])
        snapshot = await engine.compute_quality_metrics(store)
        assert snapshot.stale_entry_rate == round(2 / 3, 3)

    @pytest.mark.asyncio
    async def test_multiple_snapshots_accumulate(self):
        engine = NotebookQualityEngine()
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[_make_entry()])
        await engine.compute_quality_metrics(store)
        await engine.compute_quality_metrics(store)
        assert len(engine.snapshots) == 2

    @pytest.mark.asyncio
    async def test_graceful_degradation_on_list_failure(self):
        engine = NotebookQualityEngine()
        store = AsyncMock()
        store.list_entries = AsyncMock(side_effect=RuntimeError("IO error"))
        snapshot = await engine.compute_quality_metrics(store)
        assert snapshot.total_entries == 0
        assert snapshot.system_quality_score == 0.0


# ---------------------------------------------------------------------------
# TestEventRecording
# ---------------------------------------------------------------------------


class TestEventRecording:
    """Tests for record_event()."""

    def test_dedup_suppression_counter(self):
        engine = NotebookQualityEngine()
        engine.record_event("dedup_suppression")
        engine.record_event("dedup_suppression")
        assert engine._dedup_suppressions == 2

    def test_dedup_write_counter(self):
        engine = NotebookQualityEngine()
        engine.record_event("dedup_write")
        assert engine._dedup_writes == 1

    def test_repetition_alert_per_agent(self):
        engine = NotebookQualityEngine()
        engine.record_event("repetition_alert", callsign="Chapel")
        engine.record_event("repetition_alert", callsign="Chapel")
        engine.record_event("repetition_alert", callsign="Dax")
        assert engine._repetition_alerts == 3
        assert engine._agent_repetitions["Chapel"] == 2
        assert engine._agent_repetitions["Dax"] == 1

    def test_convergence_per_agent(self):
        engine = NotebookQualityEngine()
        engine.record_event("convergence", agents=["Chapel", "Cortez"])
        assert engine._convergence_events == 1
        assert engine._agent_convergences["Chapel"] == 1
        assert engine._agent_convergences["Cortez"] == 1

    @pytest.mark.asyncio
    async def test_counters_reset_after_compute(self):
        engine = NotebookQualityEngine()
        engine.record_event("dedup_suppression")
        engine.record_event("dedup_write")
        engine.record_event("repetition_alert", callsign="Chapel")
        engine.record_event("convergence", agents=["Dax"])
        engine.record_event("divergence")

        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[_make_entry()])
        snapshot = await engine.compute_quality_metrics(store)

        # Per-snapshot counters reset
        assert engine._dedup_suppressions == 0
        assert engine._dedup_writes == 0
        assert engine._repetition_alerts == 0
        assert engine._convergence_events == 0
        assert engine._divergence_events == 0

        # Per-agent cumulative remains
        assert engine._agent_repetitions["Chapel"] == 1
        assert engine._agent_convergences["Dax"] == 1

        # Snapshot captured the values
        assert snapshot.convergence_count == 1
        assert snapshot.divergence_count == 1


# ---------------------------------------------------------------------------
# TestDedupAndRepetitionRates
# ---------------------------------------------------------------------------


class TestDedupAndRepetitionRates:
    """Tests for dedup/repetition rate computation."""

    @pytest.mark.asyncio
    async def test_dedup_suppression_rate(self):
        engine = NotebookQualityEngine()
        engine.record_event("dedup_write")
        engine.record_event("dedup_write")
        engine.record_event("dedup_suppression")

        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[_make_entry()])
        snapshot = await engine.compute_quality_metrics(store)
        assert snapshot.dedup_suppression_rate == round(1 / 3, 3)

    @pytest.mark.asyncio
    async def test_zero_writes_no_division_error(self):
        engine = NotebookQualityEngine()
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[_make_entry()])
        snapshot = await engine.compute_quality_metrics(store)
        assert snapshot.dedup_suppression_rate == 0.0
        assert snapshot.repetition_alert_rate == 0.0

    @pytest.mark.asyncio
    async def test_rates_from_current_cycle_only(self):
        engine = NotebookQualityEngine()
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[_make_entry()])

        # First cycle: record events
        engine.record_event("dedup_suppression")
        s1 = await engine.compute_quality_metrics(store)
        assert s1.dedup_suppression_rate > 0

        # Second cycle: no events
        s2 = await engine.compute_quality_metrics(store)
        assert s2.dedup_suppression_rate == 0.0


# ---------------------------------------------------------------------------
# TestQualityScore
# ---------------------------------------------------------------------------


class TestQualityScore:
    """Tests for quality score computation."""

    @pytest.mark.asyncio
    async def test_perfect_agent_scores_high(self):
        engine = NotebookQualityEngine()
        engine.record_event("convergence", agents=["Chapel"])
        engine.record_event("convergence", agents=["Chapel"])
        engine.record_event("convergence", agents=["Chapel"])
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[
            _make_entry(author="Chapel", topic=f"topic-{i}", revision=1)
            for i in range(5)
        ])
        snapshot = await engine.compute_quality_metrics(store)
        chapel = snapshot.per_agent[0]
        # High diversity, all fresh, all novel, convergence=3, no repetition
        assert chapel.quality_score >= 0.9

    @pytest.mark.asyncio
    async def test_poor_agent_scores_low(self):
        engine = NotebookQualityEngine()
        for _ in range(5):
            engine.record_event("repetition_alert", callsign="Bad")
        store = AsyncMock()
        stale = (datetime.utcnow() - timedelta(hours=200)).isoformat()
        store.list_entries = AsyncMock(return_value=[
            _make_entry(author="Bad", topic="same-topic", revision=10, updated=stale, department="Ops"),
            _make_entry(author="Bad", topic="same-topic", revision=8, updated=stale, department="Ops"),
            _make_entry(author="Bad", topic="same-topic", revision=5, updated=stale, department="Ops"),
        ])
        snapshot = await engine.compute_quality_metrics(store)
        bad = snapshot.per_agent[0]
        # One topic, all stale, no novel (rev>1), no convergence, many repetitions
        assert bad.quality_score < 0.2

    @pytest.mark.asyncio
    async def test_system_score_is_mean_of_agents(self):
        engine = NotebookQualityEngine()
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[
            _make_entry(author="A", topic="t1", department="D1"),
            _make_entry(author="B", topic="t2", department="D2"),
        ])
        snapshot = await engine.compute_quality_metrics(store)
        expected = round(sum(a.quality_score for a in snapshot.per_agent) / 2, 3)
        assert snapshot.system_quality_score == expected

    @pytest.mark.asyncio
    async def test_per_department_scores(self):
        engine = NotebookQualityEngine()
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[
            _make_entry(author="Chapel", topic="t1", department="Medical"),
            _make_entry(author="Cortez", topic="t2", department="Medical"),
            _make_entry(author="Dax", topic="t3", department="Science"),
        ])
        snapshot = await engine.compute_quality_metrics(store)
        assert "Medical" in snapshot.per_department
        assert "Science" in snapshot.per_department
        # Medical is avg of Chapel+Cortez scores
        chapel = next(a for a in snapshot.per_agent if a.callsign == "Chapel")
        cortez = next(a for a in snapshot.per_agent if a.callsign == "Cortez")
        expected_med = round((chapel.quality_score + cortez.quality_score) / 2, 3)
        assert snapshot.per_department["Medical"] == expected_med


# ---------------------------------------------------------------------------
# TestBridgeAlerts
# ---------------------------------------------------------------------------


class TestBridgeAlerts:
    """Tests for check_notebook_quality() on BridgeAlertService."""

    def _make_service(self):
        from probos.bridge_alerts import BridgeAlertService
        return BridgeAlertService()

    def test_alert_when_system_score_below_low(self):
        svc = self._make_service()
        alerts = svc.check_notebook_quality({
            "system_quality_score": 0.2,
            "stale_entry_rate": 0.1,
            "per_agent": [],
            "_low_threshold": 0.3,
            "_warn_threshold": 0.5,
            "_staleness_alert_rate": 0.7,
        })
        assert len(alerts) == 1
        assert alerts[0].severity.name == "ALERT"
        assert alerts[0].alert_type == "notebook_quality_low"

    def test_advisory_when_system_score_below_warn(self):
        svc = self._make_service()
        alerts = svc.check_notebook_quality({
            "system_quality_score": 0.4,
            "stale_entry_rate": 0.1,
            "per_agent": [],
            "_low_threshold": 0.3,
            "_warn_threshold": 0.5,
            "_staleness_alert_rate": 0.7,
        })
        assert len(alerts) == 1
        assert alerts[0].severity.name == "ADVISORY"

    def test_info_for_agent_below_quarter(self):
        svc = self._make_service()
        alerts = svc.check_notebook_quality({
            "system_quality_score": 0.7,
            "stale_entry_rate": 0.1,
            "per_agent": [{"callsign": "Bad", "quality_score": 0.15}],
            "_low_threshold": 0.3,
            "_warn_threshold": 0.5,
            "_staleness_alert_rate": 0.7,
        })
        assert any(a.alert_type == "agent_quality_low" for a in alerts)
        assert any(a.severity.name == "INFO" for a in alerts)


# ---------------------------------------------------------------------------
# TestAPIEndpoints
# ---------------------------------------------------------------------------


class TestAPIEndpoints:
    """Tests for /api/notebook-quality endpoints."""

    @pytest.mark.asyncio
    async def test_no_data_when_no_snapshot(self):
        from probos.routers.system import get_notebook_quality
        runtime = MagicMock()
        engine = NotebookQualityEngine()
        runtime._notebook_quality_engine = engine
        result = await get_notebook_quality(runtime)
        assert result["status"] == "no_data"

    @pytest.mark.asyncio
    async def test_returns_snapshot_dict(self):
        from probos.routers.system import get_notebook_quality
        engine = NotebookQualityEngine()
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[_make_entry()])
        await engine.compute_quality_metrics(store)

        runtime = MagicMock()
        runtime._notebook_quality_engine = engine
        result = await get_notebook_quality(runtime)
        assert result["status"] == "ok"
        assert "system_quality_score" in result
        assert "per_agent" in result

    @pytest.mark.asyncio
    async def test_agent_endpoint_returns_data(self):
        from probos.routers.system import get_agent_notebook_quality
        engine = NotebookQualityEngine()
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[
            _make_entry(author="Chapel", topic="trust"),
        ])
        await engine.compute_quality_metrics(store)

        runtime = MagicMock()
        runtime._notebook_quality_engine = engine
        result = await get_agent_notebook_quality("Chapel", runtime)
        assert result["status"] == "ok"
        assert result["callsign"] == "Chapel"

    @pytest.mark.asyncio
    async def test_agent_endpoint_not_found(self):
        from probos.routers.system import get_agent_notebook_quality
        engine = NotebookQualityEngine()
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[_make_entry()])
        await engine.compute_quality_metrics(store)

        runtime = MagicMock()
        runtime._notebook_quality_engine = engine
        result = await get_agent_notebook_quality("Nobody", runtime)
        assert result["status"] == "not_found"


# ---------------------------------------------------------------------------
# TestVitalsIntegration
# ---------------------------------------------------------------------------


class TestVitalsIntegration:
    """Tests for VitalsMonitor notebook quality surfacing."""

    def test_quality_in_metrics_when_engine_available(self):
        """VitalsMonitor includes notebook_quality when engine has snapshot."""
        rt = MagicMock()
        engine = NotebookQualityEngine()
        # Manually push a snapshot
        snap = NotebookQualitySnapshot(
            timestamp=time.time(),
            system_quality_score=0.85,
            total_entries=42,
            stale_entry_rate=0.1,
        )
        engine._snapshots.append(snap)
        rt._notebook_quality_engine = engine
        assert engine.latest_snapshot is not None
        assert engine.latest_snapshot.system_quality_score == 0.85

    def test_no_quality_when_engine_unavailable(self):
        """No notebook_quality keys when engine not present."""
        rt = MagicMock(spec=[])  # no attributes
        engine = getattr(rt, "_notebook_quality_engine", None)
        assert engine is None


# ---------------------------------------------------------------------------
# TestDreamReport
# ---------------------------------------------------------------------------


class TestDreamReport:
    """Tests for DreamReport AD-555 fields."""

    def test_dream_report_has_quality_fields(self):
        from probos.types import DreamReport
        report = DreamReport()
        assert hasattr(report, "notebook_quality_score")
        assert hasattr(report, "notebook_quality_agents")
        assert report.notebook_quality_score is None
        assert report.notebook_quality_agents == 0


# ---------------------------------------------------------------------------
# TestConfigKnobs
# ---------------------------------------------------------------------------


class TestConfigKnobs:
    """Tests for RecordsConfig AD-555 settings."""

    def test_default_values(self):
        from probos.config import RecordsConfig
        rc = RecordsConfig()
        assert rc.notebook_quality_enabled is True
        assert rc.notebook_quality_low_threshold == 0.3
        assert rc.notebook_quality_warn_threshold == 0.5
        assert rc.notebook_staleness_alert_rate == 0.7

    def test_custom_values(self):
        from probos.config import RecordsConfig
        rc = RecordsConfig(
            notebook_quality_low_threshold=0.2,
            notebook_quality_warn_threshold=0.4,
            notebook_staleness_alert_rate=0.6,
        )
        assert rc.notebook_quality_low_threshold == 0.2
        assert rc.notebook_quality_warn_threshold == 0.4
        assert rc.notebook_staleness_alert_rate == 0.6


# ---------------------------------------------------------------------------
# TestEventType
# ---------------------------------------------------------------------------


class TestEventType:
    """Tests for NOTEBOOK_QUALITY_UPDATED event type."""

    def test_event_type_exists(self):
        from probos.events import EventType
        assert hasattr(EventType, "NOTEBOOK_QUALITY_UPDATED")
        assert EventType.NOTEBOOK_QUALITY_UPDATED.value == "notebook_quality_updated"


# ---------------------------------------------------------------------------
# TestToDict
# ---------------------------------------------------------------------------


class TestToDict:
    """Tests for serialization."""

    def test_agent_quality_to_dict(self):
        aq = AgentNotebookQuality(callsign="Chapel", quality_score=0.85)
        d = aq.to_dict()
        assert d["callsign"] == "Chapel"
        assert d["quality_score"] == 0.85

    @pytest.mark.asyncio
    async def test_snapshot_to_dict_json_serializable(self):
        import json
        engine = NotebookQualityEngine()
        store = AsyncMock()
        store.list_entries = AsyncMock(return_value=[
            _make_entry(author="Chapel", topic="t1"),
            _make_entry(author="Dax", topic="t2", department="Science"),
        ])
        snapshot = await engine.compute_quality_metrics(store)
        d = snapshot.to_dict()
        # Should not raise
        serialized = json.dumps(d)
        assert '"system_quality_score"' in serialized

    def test_snapshot_per_agent_serialized(self):
        aq = AgentNotebookQuality(callsign="Chapel", quality_score=0.9)
        snap = NotebookQualitySnapshot(per_agent=[aq])
        d = snap.to_dict()
        assert isinstance(d["per_agent"], list)
        assert d["per_agent"][0]["callsign"] == "Chapel"
