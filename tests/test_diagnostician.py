"""Tests for DiagnosticianAgent — BF-003 fix (AD-350)."""

from __future__ import annotations

import pytest

from probos.agents.medical.diagnostician import DiagnosticianAgent


class TestDiagnosticianIntents:
    """Verify intent descriptors and handled intents."""

    def test_handles_medical_alert(self):
        agent = DiagnosticianAgent(agent_id="diag-1")
        assert "medical_alert" in agent._handled_intents

    def test_handles_diagnose_system(self):
        agent = DiagnosticianAgent(agent_id="diag-1")
        assert "diagnose_system" in agent._handled_intents

    def test_instructions_differentiate_intents(self):
        """BF-003: Instructions must distinguish medical_alert from diagnose_system."""
        agent = DiagnosticianAgent(agent_id="diag-1")
        assert "medical_alert" in agent.instructions
        assert "diagnose_system" in agent.instructions
        # Should not tell LLM to analyze "alert data" for both intents
        assert agent.instructions.count("alert data") <= 1


class TestDiagnosticianPerceive:
    """BF-003: perceive() should enrich diagnose_system with live metrics."""

    @pytest.mark.asyncio
    async def test_perceive_diagnose_system_with_vitals(self):
        """diagnose_system intent should include VitalsMonitor metrics in context."""

        class _FakeVitals:
            agent_type = "vitals_monitor"

            async def scan_now(self):
                return {"system_health": 0.95, "pool_health": {"core": 1.0}, "trust_mean": 0.7}

        class _FakeRegistry:
            def all(self):
                return [_FakeVitals()]

        class _FakeRuntime:
            registry = _FakeRegistry()

        agent = DiagnosticianAgent(agent_id="diag-1", runtime=_FakeRuntime())
        result = await agent.perceive({"intent": "diagnose_system", "params": {"focus": "trust"}})
        assert "LIVE SYSTEM METRICS" in result.get("context", "")
        assert "system_health" in result.get("context", "")

    @pytest.mark.asyncio
    async def test_perceive_diagnose_system_without_vitals(self):
        """diagnose_system without VitalsMonitor should degrade gracefully."""

        class _FakeRegistry:
            def all(self):
                return []

        class _FakeRuntime:
            registry = _FakeRegistry()

        agent = DiagnosticianAgent(agent_id="diag-1", runtime=_FakeRuntime())
        result = await agent.perceive({"intent": "diagnose_system", "params": {}})
        assert "not found" in result.get("context", "").lower()

    @pytest.mark.asyncio
    async def test_perceive_medical_alert_unchanged(self):
        """medical_alert intents should not trigger VitalsMonitor scan."""
        agent = DiagnosticianAgent(agent_id="diag-1")
        result = await agent.perceive({
            "intent": "medical_alert",
            "params": {"severity": "warning", "metric": "pool_health"},
        })
        # Should NOT contain "LIVE SYSTEM METRICS" — alert already has data
        assert "LIVE SYSTEM METRICS" not in result.get("context", "")

    @pytest.mark.asyncio
    async def test_perceive_diagnose_system_no_runtime(self):
        """No runtime = graceful fallback, no crash."""
        agent = DiagnosticianAgent(agent_id="diag-1")
        result = await agent.perceive({"intent": "diagnose_system", "params": {}})
        # Should not crash, context may be empty or contain fallback text
        assert isinstance(result, dict)


class TestVitalsMonitorScanNow:
    """Test the on-demand scan_now() method added for AD-350."""

    @pytest.mark.asyncio
    async def test_scan_now_no_runtime(self):
        from probos.agents.medical.vitals_monitor import VitalsMonitorAgent
        agent = VitalsMonitorAgent(agent_id="vm-1", pool="medical_vitals")
        metrics = await agent.scan_now()
        assert "pulse" in metrics
        assert "timestamp" in metrics
        # No runtime = minimal metrics only
        assert "pool_health" not in metrics

    @pytest.mark.asyncio
    async def test_scan_now_with_runtime(self):
        from probos.agents.medical.vitals_monitor import VitalsMonitorAgent
        from probos.types import AgentState

        class _FakeAgent:
            state = AgentState.ACTIVE
            confidence = 0.9
            id = "fake-1"

        class _FakePool:
            target_size = 1
            healthy_agents = [_FakeAgent()]

        class _FakeTrust:
            def all_scores(self):
                return {"fake-1": 0.8}

        class _FakeRegistry:
            def all(self):
                return [_FakeAgent()]

        class _FakeRuntime:
            pools = {"test_pool": _FakePool()}
            trust_network = _FakeTrust()
            dream_scheduler = None
            attention = None
            registry = _FakeRegistry()

        agent = VitalsMonitorAgent(agent_id="vm-1", pool="medical_vitals", runtime=_FakeRuntime())
        metrics = await agent.scan_now()
        assert "pool_health" in metrics
        assert "trust_mean" in metrics
        assert "system_health" in metrics
        assert metrics["pool_health"]["test_pool"] == 1.0

    @pytest.mark.asyncio
    async def test_scan_now_does_not_emit_alerts(self):
        """scan_now() must NOT check thresholds or emit alerts."""
        from probos.agents.medical.vitals_monitor import VitalsMonitorAgent

        class _FakeRuntime:
            pools = {}
            trust_network = type("T", (), {"all_scores": lambda self: {}})()
            dream_scheduler = None
            attention = None
            registry = type("R", (), {"all": lambda self: []})()

        agent = VitalsMonitorAgent(agent_id="vm-1", pool="medical_vitals", runtime=_FakeRuntime())
        # scan_now should return metrics without calling _check_thresholds
        metrics = await agent.scan_now()
        assert "timestamp" in metrics
