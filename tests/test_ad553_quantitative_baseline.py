"""AD-553: Quantitative Baseline Auto-Capture tests.

Tests metric collection, baseline delta computation, RecordsStore integration,
write-path wiring, and config knob.
"""

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from probos.config import RecordsConfig
from probos.proactive import collect_notebook_metrics, compute_metrics_delta


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_vitals_agent(vitals: dict[str, Any] | None = None):
    """Create a fake VitalsMonitor agent."""
    agent = SimpleNamespace(agent_type="vitals_monitor", latest_vitals=vitals or {})
    return agent


def _make_runtime(
    *,
    vitals: dict[str, Any] | None = None,
    trust_score: float | None = None,
    agents: list | None = None,
):
    """Build a fake runtime with optional VitalsMonitor, TrustNetwork, registry."""
    if agents is None:
        agents = []
        if vitals is not None:
            agents.append(_make_vitals_agent(vitals))

    registry = SimpleNamespace(all=lambda: agents)

    trust_network = None
    if trust_score is not None:
        trust_network = SimpleNamespace(get_score=lambda aid: trust_score)

    rt = SimpleNamespace(registry=registry, trust_network=trust_network)
    return rt


def _make_records_config(tmp_path: Path, **overrides):
    """Create a RecordsConfig pointing at tmp_path."""
    defaults = {
        "repo_path": str(tmp_path / "ship-records"),
        "enabled": True,
        "auto_commit": True,
        "commit_debounce_seconds": 5.0,
        "max_episodes_per_hour": 20,
    }
    defaults.update(overrides)
    return RecordsConfig(**defaults)


async def _make_store(tmp_path: Path, **config_overrides):
    """Create and initialize a RecordsStore."""
    from probos.knowledge.records_store import RecordsStore
    config = _make_records_config(tmp_path, **config_overrides)
    rs = RecordsStore(config)
    await rs.initialize()
    return rs


# ===========================================================================
# TestCollectNotebookMetrics
# ===========================================================================

class TestCollectNotebookMetrics:
    """Test collect_notebook_metrics() function."""

    def test_returns_empty_dict_when_runtime_is_none(self):
        result = collect_notebook_metrics(None)
        assert result == {}

    def test_returns_empty_dict_when_no_vitals_monitor(self):
        rt = _make_runtime(agents=[SimpleNamespace(agent_type="other")])
        result = collect_notebook_metrics(rt)
        # Should only have active_agents
        assert result.get("trust_mean") is None
        assert result.get("active_agents") == 1

    def test_returns_core_metrics_from_vitals(self):
        vitals = {
            "trust_mean": 0.72345,
            "trust_min": 0.41234,
            "system_health": 0.89156,
        }
        rt = _make_runtime(vitals=vitals)
        result = collect_notebook_metrics(rt)
        assert result["trust_mean"] == 0.723
        assert result["trust_min"] == 0.412
        assert result["system_health"] == 0.892

    def test_computes_pool_health_mean(self):
        vitals = {"pool_health": {"medical": 0.9, "engineering": 0.8, "science": 0.7}}
        rt = _make_runtime(vitals=vitals)
        result = collect_notebook_metrics(rt)
        assert result["pool_health_mean"] == 0.8

    def test_includes_emergence_metrics_when_present(self):
        vitals = {
            "emergence_capacity": 0.65432,
            "coordination_balance": 0.78901,
        }
        rt = _make_runtime(vitals=vitals)
        result = collect_notebook_metrics(rt)
        assert result["emergence_capacity"] == 0.654
        assert result["coordination_balance"] == 0.789

    def test_includes_llm_health_string(self):
        vitals = {"llm_health": {"overall": "operational", "details": {}}}
        rt = _make_runtime(vitals=vitals)
        result = collect_notebook_metrics(rt)
        assert result["llm_health"] == "operational"

    def test_includes_agent_trust_from_trust_network(self):
        rt = _make_runtime(vitals={}, trust_score=0.85678)
        result = collect_notebook_metrics(rt, agent_id="agent-1")
        assert result["agent_trust"] == 0.857

    def test_includes_active_agents_count(self):
        agents = [
            _make_vitals_agent({}),
            SimpleNamespace(agent_type="medical"),
            SimpleNamespace(agent_type="engineering"),
        ]
        rt = _make_runtime(agents=agents, vitals={})
        result = collect_notebook_metrics(rt)
        assert result["active_agents"] == 3

    def test_omits_none_values(self):
        vitals = {"trust_mean": None, "trust_min": 0.5, "system_health": None}
        rt = _make_runtime(vitals=vitals)
        result = collect_notebook_metrics(rt)
        assert "trust_mean" not in result
        assert "system_health" not in result
        assert result["trust_min"] == 0.5

    def test_all_floats_rounded_to_3_decimals(self):
        vitals = {
            "trust_mean": 0.123456789,
            "trust_min": 0.987654321,
            "system_health": 0.555555555,
        }
        rt = _make_runtime(vitals=vitals, trust_score=0.111111111)
        result = collect_notebook_metrics(rt, agent_id="a1")
        for key in ("trust_mean", "trust_min", "system_health", "agent_trust"):
            val = result[key]
            # Check decimal places: multiply by 1000 should be integer
            assert val == round(val, 3), f"{key} not rounded to 3 decimals"


# ===========================================================================
# TestComputeMetricsDelta
# ===========================================================================

class TestComputeMetricsDelta:
    """Test compute_metrics_delta() function."""

    def test_returns_empty_when_no_meaningful_changes(self):
        old = {"trust_mean": 0.5, "trust_min": 0.3}
        new = {"trust_mean": 0.505, "trust_min": 0.305}  # < 0.01 delta
        result = compute_metrics_delta(old, new)
        assert result == {}

    def test_returns_numeric_deltas_above_threshold(self):
        old = {"trust_mean": 0.5, "system_health": 0.9}
        new = {"trust_mean": 0.6, "system_health": 0.85}
        result = compute_metrics_delta(old, new)
        assert result["trust_mean"] == 0.1
        assert result["system_health"] == -0.05

    def test_returns_string_transition_for_changed_strings(self):
        old = {"llm_health": "operational"}
        new = {"llm_health": "degraded"}
        result = compute_metrics_delta(old, new)
        assert result["llm_health"] == "operational \u2192 degraded"

    def test_omits_keys_present_in_only_one_side(self):
        old = {"trust_mean": 0.5}
        new = {"trust_min": 0.3}
        result = compute_metrics_delta(old, new)
        assert result == {}

    def test_respects_custom_min_numeric_delta(self):
        old = {"trust_mean": 0.5}
        new = {"trust_mean": 0.504}  # 0.004 delta
        # Default threshold (0.01) — should NOT appear
        assert compute_metrics_delta(old, new) == {}
        # Custom threshold (0.001) — should appear
        result = compute_metrics_delta(old, new, min_numeric_delta=0.001)
        assert "trust_mean" in result


# ===========================================================================
# TestWritePathIntegration
# ===========================================================================

class TestWritePathIntegration:
    """Test metrics integration in the proactive write path."""

    @pytest.mark.asyncio
    async def test_metrics_attached_on_new_write(self, tmp_path):
        """Metrics snapshot attached to frontmatter on new notebook write."""
        rs = await _make_store(tmp_path)

        metrics = {"trust_mean": 0.723, "system_health": 0.891}
        path = await rs.write_notebook(
            "Chapel", "test-topic", "Some content",
            department="medical", metrics=metrics,
        )

        # Read back and check frontmatter
        full_path = rs.repo_path / path
        import yaml
        raw = full_path.read_text(encoding="utf-8")
        parts = raw.split("---")
        fm = yaml.safe_load(parts[1])
        assert fm["metrics"]["trust_mean"] == 0.723
        assert fm["metrics"]["system_health"] == 0.891

    @pytest.mark.asyncio
    async def test_metrics_delta_in_frontmatter_on_update(self, tmp_path):
        """metrics_delta stored inside metrics dict when updating."""
        rs = await _make_store(tmp_path)

        # First write
        old_metrics = {"trust_mean": 0.5, "system_health": 0.9}
        await rs.write_notebook(
            "Chapel", "test-topic", "Initial content",
            department="medical", metrics=old_metrics,
        )

        # Second write with new metrics + delta
        new_metrics = {
            "trust_mean": 0.6,
            "system_health": 0.85,
            "metrics_delta": {"trust_mean": 0.1, "system_health": -0.05},
        }
        path = await rs.write_notebook(
            "Chapel", "test-topic", "Updated content",
            department="medical", metrics=new_metrics,
        )

        import yaml
        raw = (rs.repo_path / path).read_text(encoding="utf-8")
        parts = raw.split("---")
        fm = yaml.safe_load(parts[1])
        assert fm["metrics"]["metrics_delta"]["trust_mean"] == 0.1
        assert fm["metrics"]["metrics_delta"]["system_health"] == -0.05

    @pytest.mark.asyncio
    async def test_no_metrics_when_disabled(self, tmp_path):
        """No metrics attached when notebook_metrics_enabled=False."""
        rs = await _make_store(tmp_path)

        # Write without metrics (simulating disabled)
        path = await rs.write_notebook(
            "Chapel", "test-topic", "Some content",
            department="medical", metrics=None,
        )

        import yaml
        raw = (rs.repo_path / path).read_text(encoding="utf-8")
        parts = raw.split("---")
        fm = yaml.safe_load(parts[1])
        assert "metrics" not in fm

    def test_metric_collection_failure_degrades_gracefully(self):
        """Failure in collect_notebook_metrics returns empty dict, not exception."""
        # Broken runtime with registry that throws
        rt = SimpleNamespace()
        rt.registry = SimpleNamespace(all=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        rt.trust_network = None
        result = collect_notebook_metrics(rt)
        assert result == {}

    @pytest.mark.asyncio
    async def test_existing_metrics_returned_in_dedup_result(self, tmp_path):
        """check_notebook_similarity returns existing_metrics from frontmatter."""
        rs = await _make_store(tmp_path)

        # Write entry with metrics
        metrics = {"trust_mean": 0.7, "agent_trust": 0.85}
        await rs.write_notebook(
            "Chapel", "test-topic", "Baseline observation",
            department="medical", metrics=metrics,
        )

        # Check similarity — should return existing_metrics
        result = await rs.check_notebook_similarity(
            "Chapel", "test-topic", "Some different content"
        )
        assert "existing_metrics" in result
        assert result["existing_metrics"]["trust_mean"] == 0.7


# ===========================================================================
# TestRecordsStoreMetrics
# ===========================================================================

class TestRecordsStoreMetrics:
    """Test RecordsStore metrics parameter handling."""

    @pytest.mark.asyncio
    async def test_write_entry_includes_metrics_in_frontmatter(self, tmp_path):
        rs = await _make_store(tmp_path)

        metrics = {"trust_mean": 0.8, "active_agents": 42}
        path = await rs.write_entry(
            "Chapel", "test/entry.md", "Content",
            "test commit", metrics=metrics,
        )

        import yaml
        raw = (rs.repo_path / path).read_text(encoding="utf-8")
        parts = raw.split("---")
        fm = yaml.safe_load(parts[1])
        assert fm["metrics"]["trust_mean"] == 0.8
        assert fm["metrics"]["active_agents"] == 42

    @pytest.mark.asyncio
    async def test_write_notebook_passes_metrics_through(self, tmp_path):
        rs = await _make_store(tmp_path)

        metrics = {"system_health": 0.95}
        path = await rs.write_notebook(
            "LaForge", "system-check", "All good",
            department="engineering", metrics=metrics,
        )

        import yaml
        raw = (rs.repo_path / path).read_text(encoding="utf-8")
        parts = raw.split("---")
        fm = yaml.safe_load(parts[1])
        assert fm["metrics"]["system_health"] == 0.95

    @pytest.mark.asyncio
    async def test_check_notebook_similarity_returns_existing_metrics(self, tmp_path):
        rs = await _make_store(tmp_path)

        metrics = {"pool_health_mean": 0.88, "llm_health": "operational"}
        await rs.write_notebook(
            "Dax", "analysis", "Initial analysis",
            department="science", metrics=metrics,
        )

        result = await rs.check_notebook_similarity(
            "Dax", "analysis", "Different analysis content"
        )
        assert result["existing_metrics"]["pool_health_mean"] == 0.88
        assert result["existing_metrics"]["llm_health"] == "operational"


# ===========================================================================
# TestFrontmatterPersistence
# ===========================================================================

class TestFrontmatterPersistence:
    """Test metrics survive write/read cycles."""

    @pytest.mark.asyncio
    async def test_metrics_survive_write_read_cycle(self, tmp_path):
        rs = await _make_store(tmp_path)

        metrics = {
            "trust_mean": 0.723,
            "trust_min": 0.412,
            "system_health": 0.891,
            "pool_health_mean": 0.875,
            "agent_trust": 0.756,
            "active_agents": 42,
            "llm_health": "operational",
        }
        path = await rs.write_notebook(
            "Chapel", "full-metrics", "Content with all metrics",
            department="medical", metrics=metrics,
        )

        import yaml
        raw = (rs.repo_path / path).read_text(encoding="utf-8")
        parts = raw.split("---")
        fm = yaml.safe_load(parts[1])

        assert fm["metrics"]["trust_mean"] == 0.723
        assert fm["metrics"]["trust_min"] == 0.412
        assert fm["metrics"]["system_health"] == 0.891
        assert fm["metrics"]["pool_health_mean"] == 0.875
        assert fm["metrics"]["agent_trust"] == 0.756
        assert fm["metrics"]["active_agents"] == 42
        assert fm["metrics"]["llm_health"] == "operational"

    @pytest.mark.asyncio
    async def test_metrics_delta_stored_inside_metrics_dict(self, tmp_path):
        rs = await _make_store(tmp_path)

        metrics = {
            "trust_mean": 0.6,
            "metrics_delta": {"trust_mean": 0.1},
        }
        path = await rs.write_notebook(
            "Chapel", "delta-test", "Content",
            department="medical", metrics=metrics,
        )

        import yaml
        raw = (rs.repo_path / path).read_text(encoding="utf-8")
        parts = raw.split("---")
        fm = yaml.safe_load(parts[1])

        # metrics_delta is nested inside metrics
        assert "metrics_delta" in fm["metrics"]
        assert fm["metrics"]["metrics_delta"]["trust_mean"] == 0.1
        # metrics_delta is NOT a top-level frontmatter key
        assert "metrics_delta" not in fm


# ===========================================================================
# TestConfigKnob
# ===========================================================================

class TestConfigKnob:
    """Test RecordsConfig notebook_metrics_enabled knob."""

    def test_default_value_is_true(self):
        config = RecordsConfig()
        assert config.notebook_metrics_enabled is True

    def test_can_be_disabled(self):
        config = RecordsConfig(notebook_metrics_enabled=False)
        assert config.notebook_metrics_enabled is False
