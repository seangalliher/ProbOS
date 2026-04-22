"""Tests for AD-583f: Observable State Verification."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeRecreationService:
    def __init__(self, active_games=None, player_games=None):
        self._active = active_games or []
        self._player_games = player_games or {}

    def get_active_games(self):
        return list(self._active)

    def get_game_by_player(self, callsign):
        return self._player_games.get(callsign)


class FakeTrustNetwork:
    def __init__(self, scores=None, recent_events=None):
        self._scores = scores or {}
        self._recent = recent_events or []

    def all_scores(self):
        return dict(self._scores)

    def get_score(self, agent_id):
        return self._scores.get(agent_id, 0.5)

    def get_recent_events(self, n=50):
        return self._recent[:n]


class FakeVitalsMonitor:
    def __init__(self, vitals=None):
        self._vitals = vitals

    async def scan_now(self):
        return self._vitals

    @property
    def latest_vitals(self):
        return self._vitals


class FailingProvider:
    """A provider that always raises."""

    @property
    def name(self):
        return "failing"

    async def check(self, claim_text, context):
        raise RuntimeError("Intentional test failure")


# ---------------------------------------------------------------------------
# ObservableStateVerifier tests
# ---------------------------------------------------------------------------


class TestVerifierConstruction:
    def test_accepts_list_of_providers(self):
        from probos.cognitive.observable_state import ObservableStateVerifier
        verifier = ObservableStateVerifier([])
        assert verifier._providers == []

    def test_no_providers_empty_results(self):
        from probos.cognitive.observable_state import ObservableStateVerifier
        verifier = ObservableStateVerifier([])
        results = asyncio.run(
            verifier.verify_claims(["some claim"])
        )
        assert results == []


class TestObservableStateConfig:
    def test_config_exists(self):
        from probos.config import ObservableStateConfig
        cfg = ObservableStateConfig()
        assert cfg.verification_enabled is True
        assert cfg.max_claims_per_thread == 10

    def test_in_system_config(self):
        from probos.config import SystemConfig
        cfg = SystemConfig()
        assert hasattr(cfg, "observable_state")
        assert cfg.observable_state.verification_enabled is True


# ---------------------------------------------------------------------------
# RecreationStateProvider tests
# ---------------------------------------------------------------------------


class TestRecreationProvider:
    def test_detects_game_claim(self):
        from probos.cognitive.observable_state import RecreationStateProvider
        provider = RecreationStateProvider(FakeRecreationService())
        result = asyncio.run(
            provider.check("the game is stuck", {})
        )
        assert result is not None
        assert result.provider_name == "recreation"

    def test_verifies_active_game(self):
        from probos.cognitive.observable_state import RecreationStateProvider
        game = {"status": "active", "current_player": "Alice"}
        svc = FakeRecreationService(
            active_games=[game],
            player_games={"Alice": game},
        )
        provider = RecreationStateProvider(svc)
        result = asyncio.run(
            provider.check("the game board is active", {"agents": ["Alice"]})
        )
        assert result is not None
        assert "Game status" in result.ground_truth_summary

    def test_rejects_false_game_claim(self):
        from probos.cognitive.observable_state import RecreationStateProvider
        svc = FakeRecreationService(active_games=[], player_games={})
        provider = RecreationStateProvider(svc)
        result = asyncio.run(
            provider.check("the game is stuck waiting for a move", {})
        )
        assert result is not None
        assert result.verified is False
        assert "No active games" in result.ground_truth_summary

    def test_ignores_non_game_claim(self):
        from probos.cognitive.observable_state import RecreationStateProvider
        provider = RecreationStateProvider(FakeRecreationService())
        result = asyncio.run(
            provider.check("the database needs optimizing", {})
        )
        assert result is None


# ---------------------------------------------------------------------------
# TrustStateProvider tests
# ---------------------------------------------------------------------------


class TestTrustProvider:
    def test_detects_trust_claim(self):
        from probos.cognitive.observable_state import TrustStateProvider
        provider = TrustStateProvider(FakeTrustNetwork(scores={"a": 0.8}))
        result = asyncio.run(
            provider.check("trust anomaly detected in the network", {})
        )
        assert result is not None
        assert result.provider_name == "trust"

    def test_verifies_trust_score(self):
        from probos.cognitive.observable_state import TrustStateProvider
        provider = TrustStateProvider(FakeTrustNetwork(scores={"a": 0.9, "b": 0.85}))
        result = asyncio.run(
            provider.check("low trust detected among agents", {})
        )
        assert result is not None
        # No low scores → claim should be verified=False
        assert result.verified is False

    def test_rejects_false_trust_claim(self):
        from probos.cognitive.observable_state import TrustStateProvider
        provider = TrustStateProvider(FakeTrustNetwork(scores={"a": 0.1, "b": 0.2}))
        result = asyncio.run(
            provider.check("low trust detected among agents", {})
        )
        assert result is not None
        assert result.verified is True  # Actually has low scores


# ---------------------------------------------------------------------------
# SystemHealthProvider tests
# ---------------------------------------------------------------------------


class TestHealthProvider:
    def test_detects_health_claim(self):
        from probos.cognitive.observable_state import SystemHealthProvider
        provider = SystemHealthProvider(FakeVitalsMonitor({"system_health": "healthy"}))
        result = asyncio.run(
            provider.check("system health shows degraded status", {})
        )
        assert result is not None
        assert result.provider_name == "system_health"

    def test_verifies_system_health(self):
        from probos.cognitive.observable_state import SystemHealthProvider
        provider = SystemHealthProvider(FakeVitalsMonitor({"system_health": "healthy"}))
        result = asyncio.run(
            provider.check("critical system failure detected", {})
        )
        assert result is not None
        assert result.verified is False  # Healthy, not critical


# ---------------------------------------------------------------------------
# Provider exception handling
# ---------------------------------------------------------------------------


class TestProviderExceptionHandling:
    def test_graceful_skip(self):
        """Provider raises → skipped, other providers still run."""
        from probos.cognitive.observable_state import (
            ObservableStateVerifier,
            RecreationStateProvider,
        )
        failing = FailingProvider()
        working = RecreationStateProvider(
            FakeRecreationService(active_games=[], player_games={})
        )
        verifier = ObservableStateVerifier([failing, working])
        results = asyncio.run(
            verifier.verify_claims(["the game is stuck"])
        )
        # Failing provider skipped, RecreationProvider answered
        assert len(results) >= 1
        assert all(r.provider_name != "failing" for r in results)


# ---------------------------------------------------------------------------
# VerificationResult dataclass
# ---------------------------------------------------------------------------


class TestVerificationResult:
    def test_fields(self):
        from probos.cognitive.observable_state import VerificationResult
        vr = VerificationResult(
            provider_name="recreation",
            claim_text="game is stuck",
            verified=False,
            ground_truth_summary="No active games.",
            confidence=0.8,
        )
        assert vr.provider_name == "recreation"
        assert vr.claim_text == "game is stuck"
        assert vr.verified is False
        assert vr.ground_truth_summary == "No active games."
        assert vr.confidence == 0.8


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class TestObservableStateMismatchEvent:
    def test_event_type_exists(self):
        from probos.events import EventType
        assert hasattr(EventType, "OBSERVABLE_STATE_MISMATCH")
        assert EventType.OBSERVABLE_STATE_MISMATCH.value == "observable_state_mismatch"

    def test_event_serialization(self):
        from probos.events import ObservableStateMismatchEvent
        event = ObservableStateMismatchEvent(
            thread_id="t1",
            claims_checked=5,
            claims_failed=2,
            ground_truth_summary="No active games.",
            agents_involved=["Alice", "Bob"],
        )
        d = event.to_dict()
        assert d["claims_checked"] == 5
        assert d["claims_failed"] == 2
        assert d["agents_involved"] == ["Alice", "Bob"]
        assert d["source"] == "observable_state"


# ---------------------------------------------------------------------------
# Bridge alerts
# ---------------------------------------------------------------------------


class TestBridgeAlertMismatch:
    def _make_service(self):
        from probos.bridge_alerts import BridgeAlertService
        svc = BridgeAlertService.__new__(BridgeAlertService)
        svc._recent = {}
        svc._alert_log = []
        svc._max_log = 200
        svc._cooldown = 300.0
        svc._resolve_clean_period = 3600.0
        svc._default_dismiss_duration = 14400.0
        svc._dismissed = {}
        svc._resolved = {}
        svc._muted = set()
        svc._last_detected = {}
        return svc

    def test_fires_on_mismatch(self):
        svc = self._make_service()
        alerts = svc.check_observable_mismatch({
            "thread_id": "t1",
            "claims_failed": 2,
            "ground_truth_summary": "No active games. System healthy.",
        })
        assert len(alerts) == 1
        assert alerts[0].alert_type == "observable_state_mismatch"

    def test_severity_escalation(self):
        from probos.bridge_alerts import AlertSeverity
        svc = self._make_service()
        # 1 failed → ADVISORY
        alerts1 = svc.check_observable_mismatch({
            "thread_id": "t1",
            "claims_failed": 1,
            "ground_truth_summary": "Minor mismatch.",
        })
        assert alerts1[0].severity == AlertSeverity.ADVISORY

        # 2+ failed → ALERT
        svc2 = self._make_service()
        alerts2 = svc2.check_observable_mismatch({
            "thread_id": "t2",
            "claims_failed": 3,
            "ground_truth_summary": "Major mismatch.",
        })
        assert alerts2[0].severity == AlertSeverity.ALERT

    def test_dedup_mismatch(self):
        svc = self._make_service()
        data = {
            "thread_id": "t1",
            "claims_failed": 2,
            "ground_truth_summary": "Mismatch.",
        }
        svc.check_observable_mismatch(data)
        second = svc.check_observable_mismatch(data)
        assert len(second) == 0


# ---------------------------------------------------------------------------
# Behavioral Metrics Integration
# ---------------------------------------------------------------------------


class TestBehavioralMetricsCorrectness:
    def test_correctness_populated_with_verifier(self):
        """convergence_correctness_rate is not None when verifier is wired."""
        from probos.cognitive.observable_state import (
            ObservableStateVerifier,
            VerificationResult,
        )

        class AlwaysVerifyProvider:
            @property
            def name(self):
                return "test"

            async def check(self, claim_text, context):
                return VerificationResult(
                    provider_name="test",
                    claim_text=claim_text,
                    verified=True,
                    ground_truth_summary="Confirmed.",
                    confidence=1.0,
                )

        from probos.cognitive.behavioral_metrics import BehavioralMetricsEngine
        verifier = ObservableStateVerifier([AlwaysVerifyProvider()])
        engine = BehavioralMetricsEngine(observable_state_verifier=verifier)

        # Build threads with convergent posts
        threads = [{
            "posts": [
                {"author_id": "a1", "body": "system is healthy and running fine"},
                {"author_id": "a2", "body": "system is healthy and running fine"},
                {"author_id": "a3", "body": "system is healthy running fine"},
            ]
        }]

        result = asyncio.run(
            engine._compute_convergence_correctness(threads)
        )
        # Even if no convergence detected (embedding threshold), verifier
        # should have been called if events > 0. The test validates the
        # wiring path exists and doesn't crash.
        assert "total" in result
        assert "correct" in result
        assert "correctness_rate" in result
