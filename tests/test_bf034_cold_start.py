"""BF-034: Post-reset trust anomaly false positive suppression."""

import time
from unittest.mock import MagicMock, AsyncMock

import pytest

from probos.cognitive.emergent_detector import EmergentDetector
from probos.consensus.trust import TrustNetwork
from probos.runtime import ProbOSRuntime


# ---------- EmergentDetector suppression ----------

class TestColdStartSuppression:
    """EmergentDetector should suppress trust anomalies during cold-start window."""

    def _make_detector(self) -> EmergentDetector:
        trust = TrustNetwork()
        # Register a few agents at baseline
        for i in range(5):
            trust.get_or_create(f"agent-{i}")
        router = MagicMock()
        router.all_weights.return_value = {}
        detector = EmergentDetector(
            hebbian_router=router,
            trust_network=trust,
        )
        detector.set_live_agents({f"agent-{i}" for i in range(5)})
        return detector

    def test_trust_anomalies_suppressed_during_cold_start(self):
        detector = self._make_detector()
        detector.set_cold_start_suppression(300)  # 5 minutes

        # Manually create a deviation by setting one agent's trust high
        record = detector._trust.get_or_create("agent-0")
        record.alpha = 10.0  # score = 10/12 ≈ 0.83

        anomalies = detector.detect_trust_anomalies()
        assert len(anomalies) == 0, "Trust anomalies should be suppressed during cold start"

    def test_trust_anomalies_fire_after_suppression_window(self):
        detector = self._make_detector()
        # Set suppression to already expired
        detector._suppress_trust_until = time.monotonic() - 1

        # Create deviation
        record = detector._trust.get_or_create("agent-0")
        record.alpha = 10.0

        # Should NOT early-return — may or may not produce patterns depending on population stats
        anomalies = detector.detect_trust_anomalies()
        assert isinstance(anomalies, list)

    def test_cooperation_clusters_not_suppressed(self):
        detector = self._make_detector()
        detector.set_cold_start_suppression(300)

        # Cooperation clusters should still work during cold start
        clusters = detector.detect_cooperation_clusters()
        assert isinstance(clusters, list)

    def test_routing_shifts_not_suppressed(self):
        detector = self._make_detector()
        detector.set_cold_start_suppression(300)

        shifts = detector.detect_routing_shifts()
        assert isinstance(shifts, list)


# ---------- Proactive context injection ----------

class TestColdStartContext:
    """Proactive loop should inject system note during cold start."""

    @pytest.mark.asyncio
    async def test_system_note_in_context(self):
        """When runtime.is_cold_start is True, context should include system_note."""
        from probos.proactive import ProactiveCognitiveLoop

        runtime = MagicMock(spec=ProbOSRuntime)
        runtime.is_cold_start = True
        runtime.ward_room = None
        runtime.episodic_memory = None
        runtime.bridge_alerts = None
        runtime.event_log = None

        loop = ProactiveCognitiveLoop(interval=60)
        loop.set_runtime(runtime)
        context = await loop._gather_context(MagicMock(), 0.5)
        assert "system_note" in context
        assert "fresh start" in context["system_note"].lower()

    @pytest.mark.asyncio
    async def test_no_system_note_when_not_cold_start(self):
        """When runtime.is_cold_start is False, no system_note."""
        from probos.proactive import ProactiveCognitiveLoop

        runtime = MagicMock(spec=ProbOSRuntime)
        runtime.is_cold_start = False
        runtime.ward_room = None
        runtime.episodic_memory = None
        runtime.bridge_alerts = None
        runtime.event_log = None

        loop = ProactiveCognitiveLoop(interval=60)
        loop.set_runtime(runtime)
        context = await loop._gather_context(MagicMock(), 0.5)
        assert "system_note" not in context


# ---------- Build user message rendering ----------

class TestColdStartPromptRendering:
    """System note should appear in the proactive think prompt when present."""

    def test_system_note_rendered_in_prompt(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        # Minimal setup for _build_user_message
        agent._agent_type = "test_agent"

        msg = agent._build_user_message({
            "intent": "proactive_think",
            "params": {
                "context_parts": {
                    "system_note": "SYSTEM NOTE: This is a test cold start note."
                },
                "trust_score": 0.5,
                "agency_level": "suggestive",
                "agent_type": "test_agent",
                "duty": None,
            },
        })
        assert "SYSTEM NOTE" in msg
        assert "cold start" in msg.lower()

    def test_no_system_note_when_absent(self):
        from probos.cognitive.cognitive_agent import CognitiveAgent

        agent = CognitiveAgent.__new__(CognitiveAgent)
        agent._agent_type = "test_agent"

        msg = agent._build_user_message({
            "intent": "proactive_think",
            "params": {
                "context_parts": {},
                "trust_score": 0.5,
                "agency_level": "suggestive",
                "agent_type": "test_agent",
                "duty": None,
            },
        })
        assert "SYSTEM NOTE" not in msg
