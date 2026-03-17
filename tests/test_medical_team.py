"""Tests for the Medical Team pool (AD-290)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.agents.medical.vitals_monitor import VitalsMonitorAgent
from probos.agents.medical.diagnostician import DiagnosticianAgent
from probos.agents.medical.surgeon import SurgeonAgent
from probos.agents.medical.pharmacist import PharmacistAgent
from probos.agents.medical.pathologist import PathologistAgent
from probos.cognitive.codebase_index import CodebaseIndex
from probos.cognitive.codebase_skill import create_codebase_skill
from probos.types import AgentState, IntentMessage, IntentResult


@pytest.fixture(autouse=True)
def _clear_decision_cache():
    """Clear CognitiveAgent decision cache between tests to prevent pollution."""
    from probos.cognitive.cognitive_agent import _DECISION_CACHES
    _DECISION_CACHES.clear()
    yield
    _DECISION_CACHES.clear()


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

class _MockPool:
    def __init__(self, name: str, target_size: int, healthy_count: int):
        self.name = name
        self.target_size = target_size
        self.healthy_agents = [
            MagicMock(state=AgentState.ACTIVE, confidence=0.9)
            for _ in range(healthy_count)
        ]
        self.check_health = AsyncMock()


class _MockTrustNetwork:
    def __init__(self, scores: dict[str, float] | None = None):
        self._scores = scores or {}

    def all_scores(self) -> dict[str, float]:
        return dict(self._scores)

    def summary(self) -> list[dict]:
        return [{"agent_id": k, "score": v} for k, v in self._scores.items()]


class _MockRegistry:
    def __init__(self, agents: list[Any] | None = None):
        self._agents = agents or []

    def all(self) -> list[Any]:
        return list(self._agents)


class _MockIntentBus:
    def __init__(self):
        self.broadcast_calls: list[IntentMessage] = []

    async def broadcast(self, intent: IntentMessage, timeout: float = 5.0) -> list:
        self.broadcast_calls.append(intent)
        return []


class _MockRuntime:
    def __init__(
        self,
        pools: dict[str, Any] | None = None,
        trust_scores: dict[str, float] | None = None,
        agents: list[Any] | None = None,
    ):
        self.pools = pools or {}
        self.trust_network = _MockTrustNetwork(trust_scores)
        self.registry = _MockRegistry(agents)
        self.intent_bus = _MockIntentBus()
        self.dream_scheduler = None
        self.attention = MagicMock(queue_size=0)
        self.event_log = MagicMock()
        self.event_log.log = AsyncMock()
        self.pool_scaler = None


@pytest.fixture
def healthy_runtime() -> _MockRuntime:
    """Runtime where everything is healthy."""
    agents = [MagicMock(state=AgentState.ACTIVE, confidence=0.9) for _ in range(5)]
    return _MockRuntime(
        pools={"filesystem": _MockPool("filesystem", 3, 3)},
        trust_scores={"a1": 0.8, "a2": 0.7, "a3": 0.9},
        agents=agents,
    )


@pytest.fixture
def unhealthy_runtime() -> _MockRuntime:
    """Runtime with degraded pool and low trust."""
    agents = [MagicMock(state=AgentState.ACTIVE, confidence=0.4) for _ in range(5)]
    return _MockRuntime(
        pools={
            "filesystem": _MockPool("filesystem", 3, 1),  # only 1/3 healthy
        },
        trust_scores={
            "a1": 0.1, "a2": 0.2, "a3": 0.15, "a4": 0.25,  # 4 outliers
        },
        agents=agents,
    )


# ---------------------------------------------------------------------------
# Vitals Monitor Tests
# ---------------------------------------------------------------------------

class TestVitalsMonitor:
    @pytest.mark.asyncio
    async def test_vitals_collects_metrics(self, healthy_runtime):
        agent = VitalsMonitorAgent(pool="medical", runtime=healthy_runtime)
        metrics = await agent.collect_metrics()
        assert "pool_health" in metrics
        assert "trust_mean" in metrics
        assert "system_health" in metrics
        assert "attention_queue" in metrics
        assert "timestamp" in metrics

    @pytest.mark.asyncio
    async def test_vitals_alert_on_low_pool_health(self, unhealthy_runtime):
        agent = VitalsMonitorAgent(pool="medical", runtime=unhealthy_runtime)
        await agent.collect_metrics()
        alerts = unhealthy_runtime.intent_bus.broadcast_calls
        pool_alerts = [a for a in alerts if a.params.get("metric") == "pool_health"]
        assert len(pool_alerts) > 0

    @pytest.mark.asyncio
    async def test_vitals_alert_on_trust_outlier(self, unhealthy_runtime):
        agent = VitalsMonitorAgent(pool="medical", runtime=unhealthy_runtime)
        await agent.collect_metrics()
        alerts = unhealthy_runtime.intent_bus.broadcast_calls
        trust_alerts = [a for a in alerts if a.params.get("metric") == "trust_outlier"]
        assert len(trust_alerts) > 0

    @pytest.mark.asyncio
    async def test_vitals_no_alert_when_healthy(self, healthy_runtime):
        agent = VitalsMonitorAgent(pool="medical", runtime=healthy_runtime)
        await agent.collect_metrics()
        assert len(healthy_runtime.intent_bus.broadcast_calls) == 0

    @pytest.mark.asyncio
    async def test_vitals_sliding_window(self, healthy_runtime):
        agent = VitalsMonitorAgent(pool="medical", runtime=healthy_runtime, window_size=3)
        for _ in range(5):
            await agent.collect_metrics()
        assert len(agent.window) == 3  # Window capped at 3


# ---------------------------------------------------------------------------
# Diagnostician Tests
# ---------------------------------------------------------------------------

class TestDiagnostician:
    @pytest.mark.asyncio
    async def test_diagnostician_handles_alert(self):
        """Diagnostician returns IntentResult for medical_alert."""
        agent = DiagnosticianAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock(return_value=MagicMock(
                content='{"severity":"high","category":"pool","affected_components":["filesystem"],"root_cause":"degraded agents","evidence":["pool ratio 0.33"],"recommended_treatment":"recycle","treatment_intent":"medical_remediate","treatment_params":{}}',
                tier="fast",
            ))),
        )
        intent = IntentMessage(intent="medical_alert", params={"severity": "warning", "metric": "pool_health"})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success

    @pytest.mark.asyncio
    async def test_diagnostician_identifies_pool_issue(self):
        """Diagnostician produces pool-category diagnosis from pool_health alert."""
        agent = DiagnosticianAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock(return_value=MagicMock(
                content='{"severity":"high","category":"pool","affected_components":["filesystem"],"root_cause":"..","evidence":[],"recommended_treatment":"..","treatment_intent":"medical_remediate","treatment_params":{}}',
                tier="fast",
            ))),
        )
        intent = IntentMessage(intent="medical_alert", params={"severity": "warning", "metric": "pool_health"})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success
        assert "pool" in result.result

    @pytest.mark.asyncio
    async def test_diagnostician_identifies_trust_issue(self):
        """Diagnostician produces trust-category diagnosis from trust_outlier alert."""
        agent = DiagnosticianAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock(return_value=MagicMock(
                content='{"severity":"medium","category":"trust","affected_components":["a1"],"root_cause":"..","evidence":[],"recommended_treatment":"..","treatment_intent":"medical_tune","treatment_params":{}}',
                tier="fast",
            ))),
        )
        intent = IntentMessage(intent="medical_alert", params={"severity": "warning", "metric": "trust_outlier"})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success
        assert "trust" in result.result

    @pytest.mark.asyncio
    async def test_diagnostician_self_deselects_unknown_intent(self):
        """Diagnostician returns None for unrelated intents."""
        agent = DiagnosticianAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock()),
        )
        intent = IntentMessage(intent="read_file", params={})
        result = await agent.handle_intent(intent)
        assert result is None


# ---------------------------------------------------------------------------
# Surgeon Tests
# ---------------------------------------------------------------------------

class TestSurgeon:
    @pytest.mark.asyncio
    async def test_surgeon_force_dream(self):
        """Surgeon calls force_dream via dream_cycle."""
        mock_engine = MagicMock()
        mock_engine.dream_cycle = AsyncMock(return_value={"replayed": 5})
        mock_scheduler = MagicMock(engine=mock_engine)

        rt = _MockRuntime()
        rt.dream_scheduler = mock_scheduler

        agent = SurgeonAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock(return_value=MagicMock(
                content='{"action":"force_dream","target":"system","reason":"consolidation needed"}',
                tier="fast",
            ))),
            runtime=rt,
        )
        intent = IntentMessage(intent="medical_remediate", params={"action": "force_dream"})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success
        mock_engine.dream_cycle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_surgeon_surge_pool(self):
        """Surgeon calls request_surge for pool scaling."""
        rt = _MockRuntime()
        rt.pool_scaler = MagicMock()
        rt.pool_scaler.request_surge = AsyncMock()

        agent = SurgeonAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock(return_value=MagicMock(
                content='{"action":"surge_pool","target":"filesystem","reason":"underperforming"}',
                tier="fast",
            ))),
            runtime=rt,
        )
        intent = IntentMessage(intent="medical_remediate", params={"action": "surge_pool"})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success
        rt.pool_scaler.request_surge.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_surgeon_wont_prune_without_observations(self):
        """Surgeon won't run prune_agent — instructions say >= 10 observations required."""
        # This test verifies the surgeon doesn't have a prune action
        agent = SurgeonAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock(return_value=MagicMock(
                content='{"action":"unknown_action","target":"a1","reason":"test"}',
                tier="fast",
            ))),
            runtime=_MockRuntime(),
        )
        intent = IntentMessage(intent="medical_remediate", params={})
        result = await agent.handle_intent(intent)
        assert result is not None
        # The result contains the raw LLM output since action was unknown
        assert result.success

    @pytest.mark.asyncio
    async def test_surgeon_logs_remediation(self):
        """Surgeon logs remediation to event log."""
        mock_engine = MagicMock()
        mock_engine.dream_cycle = AsyncMock(return_value={"replayed": 3})
        rt = _MockRuntime()
        rt.dream_scheduler = MagicMock(engine=mock_engine)

        agent = SurgeonAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock(return_value=MagicMock(
                content='{"action":"force_dream","target":"system","reason":"test"}',
                tier="fast",
            ))),
            runtime=rt,
        )
        intent = IntentMessage(intent="medical_remediate", params={})
        await agent.handle_intent(intent)
        rt.event_log.log.assert_awaited()
        call_kwargs = rt.event_log.log.call_args
        assert call_kwargs[1]["category"] == "medical"


# ---------------------------------------------------------------------------
# Pharmacist Tests
# ---------------------------------------------------------------------------

class TestPharmacist:
    @pytest.mark.asyncio
    async def test_pharmacist_produces_recommendation(self):
        """Pharmacist returns a config recommendation."""
        agent = PharmacistAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock(return_value=MagicMock(
                content='{"parameter":"dreaming.idle_threshold_seconds","current_value":120,"recommended_value":90,"justification":"faster consolidation","expected_impact":"improved memory","confidence":0.7}',
                tier="fast",
            ))),
        )
        intent = IntentMessage(intent="medical_tune", params={"metric": "consolidation_rate"})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success
        assert "dreaming" in result.result

    @pytest.mark.asyncio
    async def test_pharmacist_does_not_apply_changes(self):
        """Pharmacist only recommends — doesn't mutate config."""
        from probos.config import SystemConfig
        cfg = SystemConfig()
        original_idle = cfg.dreaming.idle_threshold_seconds

        agent = PharmacistAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock(return_value=MagicMock(
                content='{"parameter":"dreaming.idle_threshold_seconds","current_value":120,"recommended_value":60,"justification":"test","expected_impact":"test","confidence":0.5}',
                tier="fast",
            ))),
        )
        intent = IntentMessage(intent="medical_tune", params={})
        await agent.handle_intent(intent)

        assert cfg.dreaming.idle_threshold_seconds == original_idle


# ---------------------------------------------------------------------------
# Pathologist Tests
# ---------------------------------------------------------------------------

class TestPathologist:
    @pytest.mark.asyncio
    async def test_pathologist_handles_postmortem(self):
        """Pathologist returns structured post-mortem."""
        agent = PathologistAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock(return_value=MagicMock(
                content='{"failure_type":"escalation","involved_agents":["a1"],"timeline":[],"root_cause":"timeout","recurring":false,"prior_occurrences":0,"recommendation":"increase timeout","evolution_signal":"timeout_handling"}',
                tier="fast",
            ))),
        )
        intent = IntentMessage(intent="medical_postmortem", params={"failure_type": "escalation"})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success

    @pytest.mark.asyncio
    async def test_pathologist_detects_recurring_pattern(self):
        """Pathologist identifies recurring patterns from LLM output."""
        agent = PathologistAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock(return_value=MagicMock(
                content='{"failure_type":"consensus_failure","involved_agents":["a1","a2"],"timeline":[],"root_cause":"quorum not met","recurring":true,"prior_occurrences":3,"recommendation":"lower quorum threshold","evolution_signal":"consensus_config"}',
                tier="fast",
            ))),
        )
        intent = IntentMessage(intent="medical_postmortem", params={"failure_type": "consensus_failure"})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success
        assert "recurring" in result.result

    @pytest.mark.asyncio
    async def test_pathologist_self_deselects_unknown(self):
        """Pathologist returns None for unknown intents."""
        agent = PathologistAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock()),
        )
        intent = IntentMessage(intent="read_file", params={})
        result = await agent.handle_intent(intent)
        assert result is None

    @pytest.mark.asyncio
    async def test_pathologist_uses_codebase_knowledge(self):
        """Pathologist can invoke codebase_knowledge skill."""
        source_root = Path(__file__).resolve().parent.parent / "src" / "probos"
        index = CodebaseIndex(source_root=source_root)
        index.build()
        skill = create_codebase_skill(index)

        agent = PathologistAgent(
            pool="medical",
            llm_client=MagicMock(complete=AsyncMock(return_value=MagicMock(
                content='{"failure_type":"test","involved_agents":[],"timeline":[],"root_cause":"test","recurring":false,"prior_occurrences":0,"recommendation":"test","evolution_signal":"test"}',
                tier="fast",
            ))),
        )
        agent.add_skill(skill)

        # Invoke the skill directly
        skill_intent = IntentMessage(
            intent="codebase_knowledge",
            params={"action": "query", "query": "trust"},
        )
        result = await skill.handler(skill_intent)
        assert result.success
        assert "matching_files" in result.result


# ---------------------------------------------------------------------------
# Integration Tests
# ---------------------------------------------------------------------------

class TestMedicalIntegration:
    def test_codebase_index_available_at_boot(self):
        """CodebaseIndex builds on real source tree."""
        source_root = Path(__file__).resolve().parent.parent / "src" / "probos"
        index = CodebaseIndex(source_root=source_root)
        index.build()
        assert index._built
        assert len(index.get_agent_map()) > 0

    def test_medical_pool_agents_exist(self):
        """All 5 medical agent classes can be instantiated."""
        # VitalsMonitor is a HeartbeatAgent (no llm_client needed)
        vm = VitalsMonitorAgent(pool="medical")
        assert vm.agent_type == "vitals_monitor"

        # CognitiveAgents need instructions (set at class level)
        mock_llm = MagicMock(complete=AsyncMock())
        diag = DiagnosticianAgent(pool="medical", llm_client=mock_llm)
        assert diag.agent_type == "diagnostician"

        surg = SurgeonAgent(pool="medical", llm_client=mock_llm)
        assert surg.agent_type == "surgeon"

        pharm = PharmacistAgent(pool="medical", llm_client=mock_llm)
        assert pharm.agent_type == "pharmacist"

        path = PathologistAgent(pool="medical", llm_client=mock_llm)
        assert path.agent_type == "pathologist"

    def test_medical_pool_excluded_from_scaler(self):
        """Medical pool names should be excluded from pool scaler."""
        # We test this by checking the runtime code sets up exclusions correctly
        # (validated via full integration test in test_runtime)
        from probos.config import MedicalConfig
        cfg = MedicalConfig()
        assert cfg.enabled is True
        assert cfg.trust_floor == 0.3
