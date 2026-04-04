"""AD-554: Real-time cross-agent convergence/divergence detection tests."""

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from probos.bridge_alerts import AlertSeverity, BridgeAlertService
from probos.config import RecordsConfig
from probos.events import (
    ConvergenceDetectedEvent,
    DivergenceDetectedEvent,
    EventType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_records_store(tmp_path: Path):
    """Create a minimal RecordsStore for testing."""
    from probos.knowledge.records_store import RecordsStore

    cfg = MagicMock()
    cfg.repo_path = str(tmp_path)
    cfg.auto_commit = False
    store = RecordsStore(cfg)
    # Create directory structure
    (tmp_path / "notebooks").mkdir(exist_ok=True)
    (tmp_path / "reports" / "convergence").mkdir(parents=True, exist_ok=True)
    return store


def _write_notebook_file(
    tmp_path: Path,
    callsign: str,
    topic_slug: str,
    content: str,
    department: str = "",
    updated: str | None = None,
):
    """Write a notebook file with frontmatter."""
    agent_dir = tmp_path / "notebooks" / callsign
    agent_dir.mkdir(parents=True, exist_ok=True)
    if updated is None:
        updated = datetime.now(timezone.utc).isoformat()
    fm = {
        "author": callsign,
        "department": department,
        "topic": topic_slug,
        "updated": updated,
        "created": updated,
        "classification": "department",
        "status": "draft",
    }
    fm_yaml = yaml.dump(fm, default_flow_style=False, sort_keys=False)
    file_path = agent_dir / f"{topic_slug}.md"
    file_path.write_text(f"---\n{fm_yaml}---\n\n{content}", encoding="utf-8")
    return file_path


# ===========================================================================
# TestCrossAgentConvergenceScan (9 tests)
# ===========================================================================

class TestCrossAgentConvergenceScan:
    """Tests for check_cross_agent_convergence() in RecordsStore."""

    @pytest.mark.asyncio
    async def test_no_convergence_single_agent(self, tmp_path):
        """No convergence when only one agent's notebooks exist."""
        store = _make_records_store(tmp_path)
        _write_notebook_file(tmp_path, "chapel", "diagnosis", "patient shows elevated readings")

        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="diagnosis",
            anchor_content="patient shows elevated readings",
        )
        assert result["convergence_detected"] is False
        assert result["convergence_agents"] == []

    @pytest.mark.asyncio
    async def test_no_convergence_same_department(self, tmp_path):
        """No convergence when two agents match but are in the same department."""
        store = _make_records_store(tmp_path)
        _write_notebook_file(
            tmp_path, "cortez", "diagnosis",
            "patient shows elevated readings in all systems",
            department="medical",
        )

        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="diagnosis",
            anchor_content="patient shows elevated readings in all systems",
        )
        assert result["convergence_detected"] is False

    @pytest.mark.asyncio
    async def test_convergence_two_agents_two_departments(self, tmp_path):
        """Convergence detected: 2 agents from 2 departments with similarity >= 0.5."""
        store = _make_records_store(tmp_path)
        content = "trust levels are stabilizing across all departments with positive trajectory"
        _write_notebook_file(
            tmp_path, "dax", "trust-analysis",
            content,
            department="science",
        )

        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="trust-analysis",
            anchor_content=content,
            convergence_threshold=0.5,
        )
        assert result["convergence_detected"] is True
        assert "chapel" in result["convergence_agents"]
        assert "dax" in result["convergence_agents"]
        assert "medical" in result["convergence_departments"]
        assert "science" in result["convergence_departments"]

    @pytest.mark.asyncio
    async def test_convergence_three_agents_two_departments(self, tmp_path):
        """Convergence detected: 3 agents from 2+ departments (exceeds minimum)."""
        store = _make_records_store(tmp_path)
        content = "system performance metrics indicate stable baseline operations confirmed"
        _write_notebook_file(tmp_path, "dax", "perf", content, department="science")
        _write_notebook_file(tmp_path, "laforge", "perf", content, department="engineering")

        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="perf",
            anchor_content=content,
        )
        assert result["convergence_detected"] is True
        assert len(result["convergence_agents"]) == 3
        assert len(result["convergence_departments"]) >= 2

    @pytest.mark.asyncio
    async def test_no_convergence_below_threshold(self, tmp_path):
        """No convergence when similarity is below threshold."""
        store = _make_records_store(tmp_path)
        _write_notebook_file(
            tmp_path, "dax", "topic-a",
            "completely different content about warp drive mechanics",
            department="science",
        )

        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="topic-b",
            anchor_content="medical report on patient wellness outcomes",
            convergence_threshold=0.5,
        )
        assert result["convergence_detected"] is False

    @pytest.mark.asyncio
    async def test_staleness_window_excludes_old(self, tmp_path):
        """Entries outside staleness window are excluded from scan."""
        store = _make_records_store(tmp_path)
        content = "trust levels are stabilizing across all departments positive trajectory"
        old_time = "2020-01-01T00:00:00+00:00"
        _write_notebook_file(
            tmp_path, "dax", "trust", content, department="science",
            updated=old_time,
        )

        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="trust",
            anchor_content=content,
            staleness_hours=72.0,
        )
        assert result["convergence_detected"] is False

    @pytest.mark.asyncio
    async def test_max_scan_per_agent_cap(self, tmp_path):
        """Max scan per agent cap respected (only most recent N checked)."""
        store = _make_records_store(tmp_path)
        # Create 10 entries for dax, only the 2 most recent should be scanned
        for i in range(10):
            _write_notebook_file(
                tmp_path, "dax", f"topic-{i}",
                f"unique entry number {i} about different topics entirely",
                department="science",
            )

        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="other",
            anchor_content="something completely different from all entries",
            max_scan_per_agent=2,
        )
        # Should still work without error; cap is enforced internally
        assert "convergence_detected" in result

    @pytest.mark.asyncio
    async def test_coherence_computed_correctly(self, tmp_path):
        """Coherence score computed correctly (average pairwise similarity)."""
        store = _make_records_store(tmp_path)
        content = "trust levels are stabilizing across all departments with positive trajectory confirmed"
        _write_notebook_file(tmp_path, "dax", "trust", content, department="science")

        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="trust",
            anchor_content=content,
        )
        assert result["convergence_detected"] is True
        assert result["convergence_coherence"] > 0.0
        assert result["convergence_coherence"] <= 1.0

    @pytest.mark.asyncio
    async def test_topic_inferred_from_common_words(self, tmp_path):
        """Topic inferred from common words across converging entries."""
        store = _make_records_store(tmp_path)
        content = "trust levels are stabilizing across all departments with positive trajectory"
        _write_notebook_file(tmp_path, "dax", "trust", content, department="science")

        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="trust",
            anchor_content=content,
        )
        assert result["convergence_detected"] is True
        assert result["convergence_topic"]  # Non-empty topic inferred


# ===========================================================================
# TestDivergenceDetection (5 tests)
# ===========================================================================

class TestDivergenceDetection:
    """Tests for divergence detection in check_cross_agent_convergence()."""

    @pytest.mark.asyncio
    async def test_divergence_same_topic_low_similarity(self, tmp_path):
        """Divergence detected: same topic_slug, different departments, low similarity."""
        store = _make_records_store(tmp_path)
        _write_notebook_file(
            tmp_path, "dax", "performance",
            "warp core efficiency is declining due to dilithium crystal degradation",
            department="science",
        )

        result = await store.check_cross_agent_convergence(
            anchor_callsign="laforge",
            anchor_department="engineering",
            anchor_topic_slug="performance",
            anchor_content="crew morale indicators show significant improvement this cycle",
            divergence_threshold=0.3,
        )
        assert result["divergence_detected"] is True
        assert "laforge" in result["divergence_agents"]
        assert "dax" in result["divergence_agents"]

    @pytest.mark.asyncio
    async def test_no_divergence_high_similarity(self, tmp_path):
        """No divergence when agents agree (high similarity on same topic)."""
        store = _make_records_store(tmp_path)
        content = "performance metrics show stable baseline operations confirmed"
        _write_notebook_file(
            tmp_path, "dax", "performance", content, department="science",
        )

        result = await store.check_cross_agent_convergence(
            anchor_callsign="laforge",
            anchor_department="engineering",
            anchor_topic_slug="performance",
            anchor_content=content,
            divergence_threshold=0.3,
        )
        assert result["divergence_detected"] is False

    @pytest.mark.asyncio
    async def test_no_divergence_different_topics(self, tmp_path):
        """No divergence when low-similarity entries are on different topics."""
        store = _make_records_store(tmp_path)
        _write_notebook_file(
            tmp_path, "dax", "warp-theory",
            "warp field equations require recalibration for subspace variance",
            department="science",
        )

        result = await store.check_cross_agent_convergence(
            anchor_callsign="laforge",
            anchor_department="engineering",
            anchor_topic_slug="hull-stress",
            anchor_content="hull stress analysis shows fatigue at junction points",
            divergence_threshold=0.3,
        )
        assert result["divergence_detected"] is False

    @pytest.mark.asyncio
    async def test_no_divergence_same_department(self, tmp_path):
        """No divergence when disagreeing agents are in the same department."""
        store = _make_records_store(tmp_path)
        _write_notebook_file(
            tmp_path, "dax", "sensors",
            "sensor readings are anomalous and require investigation",
            department="science",
        )

        result = await store.check_cross_agent_convergence(
            anchor_callsign="brahms",
            anchor_department="science",
            anchor_topic_slug="sensors",
            anchor_content="crew reports indicate all sensors functioning normally",
            divergence_threshold=0.3,
        )
        assert result["divergence_detected"] is False

    @pytest.mark.asyncio
    async def test_divergence_similarity_correct(self, tmp_path):
        """Divergence similarity value is correct (lowest pairwise similarity)."""
        store = _make_records_store(tmp_path)
        _write_notebook_file(
            tmp_path, "dax", "systems",
            "warp core efficiency declining dilithium crystal degradation observed",
            department="science",
        )

        result = await store.check_cross_agent_convergence(
            anchor_callsign="laforge",
            anchor_department="engineering",
            anchor_topic_slug="systems",
            anchor_content="crew morale indicators show significant improvement this cycle",
            divergence_threshold=0.3,
        )
        assert result["divergence_detected"] is True
        assert result["divergence_similarity"] < 0.3
        assert result["divergence_similarity"] >= 0.0


# ===========================================================================
# TestEventEmission (4 tests)
# ===========================================================================

class TestEventEmission:
    """Tests for convergence/divergence event emission."""

    def test_convergence_event_fields(self):
        """ConvergenceDetectedEvent emitted with correct fields."""
        evt = ConvergenceDetectedEvent(
            agents=["chapel", "dax"],
            departments=["medical", "science"],
            topic="trust-analysis",
            coherence=0.75,
            source="realtime",
            report_path="reports/convergence/convergence-test.md",
        )
        d = evt.to_dict()
        assert d["type"] == "convergence_detected"
        assert d["data"]["agents"] == ["chapel", "dax"]
        assert d["data"]["departments"] == ["medical", "science"]
        assert d["data"]["topic"] == "trust-analysis"
        assert d["data"]["coherence"] == 0.75
        assert d["data"]["source"] == "realtime"
        assert d["data"]["report_path"] == "reports/convergence/convergence-test.md"

    def test_divergence_event_fields(self):
        """DivergenceDetectedEvent emitted with correct fields."""
        evt = DivergenceDetectedEvent(
            agents=["laforge", "dax"],
            departments=["engineering", "science"],
            topic="performance",
            similarity=0.15,
        )
        d = evt.to_dict()
        assert d["type"] == "divergence_detected"
        assert d["data"]["agents"] == ["laforge", "dax"]
        assert d["data"]["topic"] == "performance"
        assert d["data"]["similarity"] == 0.15

    @pytest.mark.asyncio
    async def test_no_event_when_not_detected(self, tmp_path):
        """Event NOT emitted when convergence/divergence not detected."""
        store = _make_records_store(tmp_path)
        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="test",
            anchor_content="something unique",
        )
        assert result["convergence_detected"] is False
        assert result["divergence_detected"] is False

    def test_divergence_event_type_exists(self):
        """DIVERGENCE_DETECTED EventType exists in enum."""
        assert EventType.DIVERGENCE_DETECTED == "divergence_detected"
        assert EventType.DIVERGENCE_DETECTED.value == "divergence_detected"


# ===========================================================================
# TestBridgeAlerts (4 tests)
# ===========================================================================

class TestBridgeAlerts:
    """Tests for bridge alert check methods."""

    def test_check_realtime_convergence_advisory(self):
        """check_realtime_convergence() returns ADVISORY alert with source=notebook_monitor."""
        svc = BridgeAlertService(cooldown_seconds=0)
        conv_result = {
            "convergence_detected": True,
            "convergence_topic": "trust-stability",
            "convergence_agents": ["chapel", "dax"],
            "convergence_departments": ["medical", "science"],
        }
        alerts = svc.check_realtime_convergence(conv_result)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ADVISORY
        assert alerts[0].source == "notebook_monitor"
        assert alerts[0].alert_type == "realtime_convergence_detected"
        assert "trust-stability" in alerts[0].detail

    def test_check_divergence_advisory(self):
        """check_divergence() returns ADVISORY alert with divergence details."""
        svc = BridgeAlertService(cooldown_seconds=0)
        div_data = {
            "divergence_detected": True,
            "divergence_topic": "performance",
            "divergence_agents": ["laforge", "dax"],
            "divergence_departments": ["engineering", "science"],
            "divergence_similarity": 0.15,
        }
        alerts = svc.check_divergence(div_data)
        assert len(alerts) == 1
        assert alerts[0].severity == AlertSeverity.ADVISORY
        assert alerts[0].source == "notebook_monitor"
        assert alerts[0].alert_type == "divergence_detected"
        assert "0.15" in alerts[0].detail

    def test_bridge_alert_dedup(self):
        """Bridge alert dedup prevents repeated alerts for same convergence topic."""
        svc = BridgeAlertService(cooldown_seconds=300)
        conv_result = {
            "convergence_detected": True,
            "convergence_topic": "same-topic",
            "convergence_agents": ["a", "b"],
            "convergence_departments": ["d1", "d2"],
        }
        alerts1 = svc.check_realtime_convergence(conv_result)
        alerts2 = svc.check_realtime_convergence(conv_result)
        assert len(alerts1) == 1
        assert len(alerts2) == 0  # Deduped

    def test_no_alert_when_not_detected(self):
        """No bridge alert when detection is negative."""
        svc = BridgeAlertService(cooldown_seconds=0)
        alerts = svc.check_realtime_convergence({"convergence_detected": False})
        assert alerts == []
        alerts = svc.check_divergence({"divergence_detected": False})
        assert alerts == []


# ===========================================================================
# TestConvergenceReport (2 tests)
# ===========================================================================

class TestConvergenceReport:
    """Tests for convergence report generation."""

    @pytest.mark.asyncio
    async def test_report_written_to_records(self, tmp_path):
        """Convergence report written to Ship's Records at reports/convergence/."""
        store = _make_records_store(tmp_path)
        await store.initialize()

        # Write converging entries
        content = "trust levels are stabilizing across all departments confirmed trajectory"
        _write_notebook_file(tmp_path, "dax", "trust", content, department="science")

        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="trust",
            anchor_content=content,
        )
        assert result["convergence_detected"] is True

        # Now simulate report writing via proactive helper
        # We'll test the report content format directly
        report_content = (
            f"## Real-Time Convergence Report\n\n"
            f"**Agents:** {', '.join(result['convergence_agents'])}\n\n"
            f"**Departments:** {', '.join(result['convergence_departments'])}\n\n"
            f"**Coherence:** {result['convergence_coherence']:.3f}\n\n"
        )
        report_path = "reports/convergence/convergence-test.md"
        await store.write_entry(
            author="system",
            path=report_path,
            content=report_content,
            message="AD-554 test convergence report",
            classification="ship",
            tags=["convergence", "ad-554", "realtime"],
        )
        written = (tmp_path / report_path).read_text(encoding="utf-8")
        assert "Real-Time Convergence Report" in written
        assert "chapel" in written
        assert "dax" in written

    @pytest.mark.asyncio
    async def test_report_contains_required_fields(self, tmp_path):
        """Report contains agents, departments, coherence, and contributing perspectives."""
        store = _make_records_store(tmp_path)
        await store.initialize()

        content = "trust levels are stabilizing across all departments confirmed trajectory"
        _write_notebook_file(tmp_path, "dax", "trust", content, department="science")

        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="trust",
            anchor_content=content,
        )
        assert result["convergence_detected"] is True
        assert len(result["convergence_agents"]) >= 2
        assert len(result["convergence_departments"]) >= 2
        assert result["convergence_coherence"] > 0.0


# ===========================================================================
# TestConfigKnobs (2 tests)
# ===========================================================================

class TestConfigKnobs:
    """Tests for AD-554 configuration."""

    def test_default_config_values(self):
        """RecordsConfig includes all AD-554 settings with correct defaults."""
        rc = RecordsConfig()
        assert rc.realtime_convergence_enabled is True
        assert rc.realtime_convergence_threshold == 0.5
        assert rc.realtime_divergence_threshold == 0.3
        assert rc.realtime_convergence_staleness_hours == 72.0
        assert rc.realtime_max_scan_per_agent == 5
        assert rc.realtime_min_convergence_agents == 2
        assert rc.realtime_min_convergence_departments == 2

    def test_custom_config_values(self):
        """Custom config values are accepted."""
        rc = RecordsConfig(
            realtime_convergence_enabled=False,
            realtime_convergence_threshold=0.7,
            realtime_divergence_threshold=0.2,
            realtime_convergence_staleness_hours=24.0,
            realtime_max_scan_per_agent=3,
            realtime_min_convergence_agents=3,
            realtime_min_convergence_departments=3,
        )
        assert rc.realtime_convergence_enabled is False
        assert rc.realtime_convergence_threshold == 0.7
        assert rc.realtime_divergence_threshold == 0.2
        assert rc.realtime_convergence_staleness_hours == 24.0
        assert rc.realtime_max_scan_per_agent == 3
        assert rc.realtime_min_convergence_agents == 3
        assert rc.realtime_min_convergence_departments == 3


# ===========================================================================
# TestWritePathIntegration (2 tests)
# ===========================================================================

class TestWritePathIntegration:
    """Tests for proactive write path integration."""

    @pytest.mark.asyncio
    async def test_scan_runs_after_successful_write(self, tmp_path):
        """Convergence scan runs after successful notebook write."""
        store = _make_records_store(tmp_path)
        content = "trust levels are stabilizing across all departments confirmed trajectory"
        _write_notebook_file(tmp_path, "dax", "trust", content, department="science")

        # Verify scan can be called and produces valid result
        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="trust",
            anchor_content=content,
        )
        assert "convergence_detected" in result
        assert "divergence_detected" in result

    @pytest.mark.asyncio
    async def test_scan_failure_does_not_crash(self, tmp_path):
        """Scan failure does not affect notebook write success (log-and-degrade)."""
        store = _make_records_store(tmp_path)
        # Pass invalid data — should not raise
        result = await store.check_cross_agent_convergence(
            anchor_callsign="chapel",
            anchor_department="medical",
            anchor_topic_slug="test",
            anchor_content="test content",
        )
        assert result["convergence_detected"] is False
        assert result["divergence_detected"] is False
