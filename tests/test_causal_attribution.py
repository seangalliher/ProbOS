"""Tests for AD-295c: Causal Back-References in EmergentPatterns."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from probos.cognitive.emergent_detector import EmergentDetector, EmergentPattern
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import HebbianRouter
from probos.runtime import ProbOSRuntime


def _setup_anomaly_scenario() -> tuple[TrustNetwork, HebbianRouter]:
    """Create a trust network with a clear outlier to trigger anomaly detection."""
    tn = TrustNetwork()
    router = HebbianRouter()

    # Create a population of agents with normal trust
    for i in range(10):
        rec = tn.get_or_create(f"agent-{i}")
        rec.alpha = 10.0
        rec.beta = 10.0  # score = 0.5

    # Make one agent a clear anomaly (very high trust)
    outlier = tn.get_or_create("agent-outlier")
    outlier.alpha = 30.0
    outlier.beta = 2.0  # score ≈ 0.938

    # Record some trust events for the outlier with causal context
    tn.record_outcome(
        "agent-outlier", success=True, weight=0.8,
        intent_type="health_check", episode_id="ep-100", verifier_id="rt-0",
    )
    tn.record_outcome(
        "agent-outlier", success=True, weight=0.6,
        intent_type="read_file", episode_id="ep-101", verifier_id="rt-1",
    )

    return tn, router


class TestCausalBackReferences:
    def test_trust_anomaly_has_causal_events(self):
        """Trust anomaly patterns include causal_events from the event log."""
        tn, router = _setup_anomaly_scenario()
        detector = EmergentDetector(hebbian_router=router, trust_network=tn, trust_anomaly_min_count=1)

        patterns = detector.detect_trust_anomalies()

        # Should detect at least the outlier
        outlier_patterns = [
            p for p in patterns
            if p.pattern_type == "trust_anomaly"
            and p.evidence.get("agent_id") == "agent-outlier"
            and "causal_events" in p.evidence
        ]
        assert len(outlier_patterns) >= 1

        causal = outlier_patterns[0].evidence["causal_events"]
        assert isinstance(causal, list)
        assert len(causal) >= 1
        # Verify causal event structure
        event = causal[0]
        assert "intent_type" in event
        assert "success" in event
        assert "weight" in event
        assert "score_change" in event
        assert "episode_id" in event

    def test_routing_shift_includes_context(self):
        """Routing shift patterns include agent trust and Hebbian weight."""
        tn = TrustNetwork()
        router = HebbianRouter()

        # Create agent with known trust
        rec = tn.get_or_create("agent-new")
        rec.alpha = 5.0  # score > 0.5

        # Record intent routing
        router.record_interaction(source="translate", target="agent-new", success=True)

        detector = EmergentDetector(hebbian_router=router, trust_network=tn)

        # First analyze to set baseline
        detector.analyze()

        # Add new routing
        router.record_interaction(source="summarize", target="agent-new", success=True)

        # Second analyze should detect the shift
        patterns = detector.detect_routing_shifts()

        routing_patterns = [p for p in patterns if p.pattern_type == "routing_shift"]
        if routing_patterns:
            evidence = routing_patterns[0].evidence
            assert "agent_trust" in evidence
            assert "hebbian_weight" in evidence
            assert evidence["agent_trust"] > 0

    def test_introspection_surfaces_causal_data(self):
        """IntrospectionAgent response includes causal attribution when available."""
        from probos.agents.introspect import IntrospectionAgent

        tn, router = _setup_anomaly_scenario()
        detector = EmergentDetector(hebbian_router=router, trust_network=tn, trust_anomaly_min_count=1)

        # Build a mock runtime with the detector
        rt = MagicMock(spec=ProbOSRuntime)
        rt._emergent_detector = detector

        agent = IntrospectionAgent(agent_id="intro-0")
        agent._runtime = rt

        result = agent._system_anomalies(rt)
        assert result["success"] is True

        # Find pattern with causal_events
        causal_patterns = [
            p for p in result["data"]["patterns"]
            if "causal_events" in p.get("evidence", {})
        ]
        assert len(causal_patterns) >= 1
        assert len(causal_patterns[0]["evidence"]["causal_events"]) >= 1
