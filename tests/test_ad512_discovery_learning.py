"""AD-512 v1 — Discovery-Based Capability Building substrate."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.config import DiscoveryLearningConfig
from probos.crew_development.discovery import (
    CapabilityConfidence,
    CapabilityConfidenceScorer,
    CrossFunctionalSuggestion,
    DiscoveryScenario,
    DiscoveryScenarioRegistry,
    StrengthMap,
    StrengthRecord,
    ZPDBand,
    ZPDCalibrator,
    frame_as_discovery,
    frame_as_growth,
    suggest_routing,
)
from probos.events import EventType
from probos.startup.finalize import _wire_discovery_learning


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


class _FakeEmit:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    def __call__(self, event_type: Any, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


def _make_record(
    *,
    agent_id: str = "tau",
    scenario_id: str = "diagnose_simple_fault",
    capability_category: str = "diagnosis",
    success: bool = True,
    confidence_self_report: float = 0.5,
    timestamp: float = 1000.0,
    notes: str = "",
) -> StrengthRecord:
    return StrengthRecord(
        agent_id=agent_id,
        scenario_id=scenario_id,
        capability_category=capability_category,
        success=success,
        confidence_self_report=confidence_self_report,
        timestamp=timestamp,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# AD-512a — DiscoveryScenarioRegistry
# ---------------------------------------------------------------------------


class TestDiscoveryScenarioRegistry:
    def test_default_catalog_seeds_8_scenarios(self) -> None:
        reg = DiscoveryScenarioRegistry()
        scenarios = reg.list_scenarios()
        assert len(scenarios) == 8
        categories = {s.capability_category for s in scenarios}
        assert categories == {
            "analysis",
            "communication",
            "coordination",
            "construction",
            "diagnosis",
        }

    def test_get_scenario_emits_offered_event(self) -> None:
        reg = DiscoveryScenarioRegistry()
        emit = _FakeEmit()
        reg.emit_event = emit

        s = reg.get_scenario("diagnose_simple_fault")

        assert s is not None
        assert s.scenario_id == "diagnose_simple_fault"
        assert len(emit.events) == 1
        ev_type, payload = emit.events[0]
        assert ev_type is EventType.DISCOVERY_SCENARIO_OFFERED
        assert payload["scenario_id"] == "diagnose_simple_fault"
        assert payload["query_type"] == "by_id"

    def test_list_by_category_filters_correctly(self) -> None:
        reg = DiscoveryScenarioRegistry()
        diag = reg.list_by_category("diagnosis")
        assert len(diag) == 2
        assert {s.scenario_id for s in diag} == {
            "diagnose_simple_fault",
            "diagnose_cross_subsystem",
        }
        assert reg.list_by_category("nonexistent") == ()

    def test_list_by_difficulty_band_inclusive_bounds(self) -> None:
        reg = DiscoveryScenarioRegistry()
        # Band 0.30..0.45 should include diagnose_simple_fault (0.30),
        # compose_briefing (0.40), analyze_telemetry_window (0.45).
        out = reg.list_by_difficulty_band(0.30, 0.45)
        ids = {s.scenario_id for s in out}
        assert ids == {
            "diagnose_simple_fault",
            "compose_briefing",
            "analyze_telemetry_window",
        }
        # Inverted band returns empty.
        assert reg.list_by_difficulty_band(0.9, 0.1) == ()


# ---------------------------------------------------------------------------
# AD-512b — StrengthMap
# ---------------------------------------------------------------------------


class TestStrengthMap:
    def test_record_outcome_appends_record(self) -> None:
        sm = StrengthMap()
        rec = _make_record(agent_id="tau", success=True)
        sm.record_outcome(rec)

        records = sm.records_for("tau")
        assert len(records) == 1
        assert records[0] is rec
        assert sm.records_for("nobody") == ()

    def test_record_outcome_emits_outcome_and_map_updated(self) -> None:
        sm = StrengthMap()
        emit = _FakeEmit()
        sm.emit_event = emit

        sm.record_outcome(_make_record(agent_id="tau", success=True))

        types = [t for t, _ in emit.events]
        assert EventType.DISCOVERY_OUTCOME_RECORDED in types
        assert EventType.STRENGTH_MAP_UPDATED in types
        # MAP_UPDATED payload carries success_rate + total_attempts.
        map_payloads = [p for t, p in emit.events if t is EventType.STRENGTH_MAP_UPDATED]
        assert map_payloads[0]["agent_id"] == "tau"
        assert map_payloads[0]["total_attempts"] == 1
        assert map_payloads[0]["success_rate"] == 1.0

    def test_get_strengths_threshold_respected(self) -> None:
        sm = StrengthMap()
        # 3 successes out of 4 = 0.75 ≥ 0.70 → strength
        for i in range(3):
            sm.record_outcome(_make_record(agent_id="tau", success=True, timestamp=1000.0 + i))
        sm.record_outcome(_make_record(agent_id="tau", success=False, timestamp=1010.0))

        strengths = sm.get_strengths("tau")
        assert "diagnosis" in strengths
        # Higher threshold excludes it.
        assert sm.get_strengths("tau", threshold=0.80) == ()

    def test_get_struggles_threshold_respected(self) -> None:
        sm = StrengthMap()
        # 1 success out of 4 = 0.25 < 0.40 → struggle
        sm.record_outcome(_make_record(agent_id="tau", success=True, timestamp=1000.0))
        for i in range(3):
            sm.record_outcome(_make_record(agent_id="tau", success=False, timestamp=1001.0 + i))

        struggles = sm.get_struggles("tau")
        assert "diagnosis" in struggles
        assert sm.get_struggles("nobody") == ()

    def test_min_attempts_gate_excludes_low_attempts(self) -> None:
        sm = StrengthMap()
        # Single successful attempt — below default min_attempts=2.
        sm.record_outcome(_make_record(agent_id="tau", success=True))

        assert sm.get_strengths("tau") == ()
        assert sm.get_strengths("tau", min_attempts=1) == ("diagnosis",)
        assert sm.total_attempts("tau", "diagnosis") == 1
        assert sm.success_rate("tau", "diagnosis") == 1.0

    def test_to_episode_payload_has_importance_8_and_source(self) -> None:
        rec = _make_record(
            agent_id="tau",
            scenario_id="diagnose_simple_fault",
            capability_category="diagnosis",
            success=False,
            confidence_self_report=0.3,
            timestamp=1234.5,
            notes="hesitated",
        )
        payload = StrengthMap.to_episode_payload(rec)

        assert payload["importance"] == 8
        assert payload["source"] == "discovery_learning"
        assert payload["agent_ids"] == ["tau"]
        assert payload["timestamp"] == 1234.5
        assert payload["user_input"] == "discovery:diagnose_simple_fault"
        assert payload["outcomes"][0]["success"] is False
        assert payload["outcomes"][0]["self_confidence"] == 0.3
        assert payload["outcomes"][0]["notes"] == "hesitated"


# ---------------------------------------------------------------------------
# AD-512c — CrossFunctionalSuggestion
# ---------------------------------------------------------------------------


class TestCrossFunctionalSuggestion:
    def test_struggle_yields_strengthen_suggestion(self) -> None:
        rec = _make_record(agent_id="tau", success=False)
        sug = suggest_routing(struggling_record=rec, peer_expert_id="omega")

        assert isinstance(sug, CrossFunctionalSuggestion)
        assert sug.source == "tau"
        assert sug.target == "omega"
        assert sug.success is True  # strengthen edge to peer-expert
        assert sug.rel_type == "agent"

    def test_success_yields_no_strengthen_suggestion(self) -> None:
        rec = _make_record(agent_id="tau", success=True)
        sug = suggest_routing(struggling_record=rec, peer_expert_id="omega")

        # Source actually succeeded — no need to strengthen edge.
        assert sug.success is False

    def test_rationale_includes_agent_and_scenario(self) -> None:
        rec = _make_record(
            agent_id="tau",
            scenario_id="diagnose_cross_subsystem",
            capability_category="diagnosis",
            success=False,
        )
        sug = suggest_routing(struggling_record=rec, peer_expert_id="omega")

        assert "tau" in sug.rationale
        assert "diagnosis" in sug.rationale
        assert "diagnose_cross_subsystem" in sug.rationale
        assert "omega" in sug.rationale


# ---------------------------------------------------------------------------
# AD-512d — Growth-mindset framing
# ---------------------------------------------------------------------------


class TestGrowthMindsetFraming:
    def test_frame_as_growth_rewrites_cant(self) -> None:
        assert frame_as_growth("you can't diagnose cross-subsystem faults") == (
            "you have not yet developed diagnose cross-subsystem faults"
        )
        assert frame_as_growth("You Cannot route handoffs cleanly").startswith(
            "you have not yet developed "
        )
        assert "compose briefings" in frame_as_growth("you don't compose briefings")
        assert "improvise" in frame_as_growth("you are unable to improvise")

    def test_frame_as_growth_idempotent(self) -> None:
        once = frame_as_growth("you can't diagnose")
        twice = frame_as_growth(once)
        assert once == twice

    def test_frame_as_growth_unrecognized_prefix_unchanged(self) -> None:
        assert frame_as_growth("this analysis is incomplete") == (
            "this analysis is incomplete"
        )
        assert frame_as_growth("") == ""

    def test_frame_as_discovery_wraps_struggle(self) -> None:
        out = frame_as_discovery("the handoff stalled at the medical boundary")
        assert out.startswith("Through this experience you discovered: ")
        assert "handoff stalled at the medical boundary" in out
        assert frame_as_discovery("") == ""


# ---------------------------------------------------------------------------
# AD-512e — CapabilityConfidenceScorer
# ---------------------------------------------------------------------------


class TestCapabilityConfidenceScorer:
    def test_default_prior_returns_mean_half(self) -> None:
        scorer = CapabilityConfidenceScorer()
        conf = scorer.get_confidence("tau", "diagnosis")

        assert isinstance(conf, CapabilityConfidence)
        assert conf.alpha == 1.0
        assert conf.beta == 1.0
        assert conf.mean == 0.5
        assert conf.variance > 0.0

    def test_record_attempt_success_increments_alpha(self) -> None:
        scorer = CapabilityConfidenceScorer()
        c1 = scorer.record_attempt("tau", "diagnosis", success=True)
        c2 = scorer.record_attempt("tau", "diagnosis", success=True)

        assert c1.alpha == 2.0 and c1.beta == 1.0
        assert c2.alpha == 3.0 and c2.beta == 1.0
        assert c2.mean == 0.75
        # Persistence: get_confidence reads same state.
        assert scorer.get_confidence("tau", "diagnosis").alpha == 3.0
        # list_for_agent surfaces it.
        listed = scorer.list_for_agent("tau")
        assert len(listed) == 1 and listed[0].capability_category == "diagnosis"

    def test_record_attempt_failure_increments_beta(self) -> None:
        scorer = CapabilityConfidenceScorer()
        c = scorer.record_attempt("tau", "diagnosis", success=False)
        assert c.alpha == 1.0 and c.beta == 2.0
        assert c.mean == pytest.approx(1 / 3)

        scorer.reset("tau", "diagnosis")
        # After reset, confidence reverts to prior.
        post = scorer.get_confidence("tau", "diagnosis")
        assert post.alpha == 1.0 and post.beta == 1.0

    def test_emit_capability_confidence_updated(self) -> None:
        scorer = CapabilityConfidenceScorer()
        emit = _FakeEmit()
        scorer.emit_event = emit

        scorer.record_attempt("tau", "diagnosis", success=True)

        assert len(emit.events) == 1
        ev_type, payload = emit.events[0]
        assert ev_type is EventType.CAPABILITY_CONFIDENCE_UPDATED
        assert payload["agent_id"] == "tau"
        assert payload["capability_category"] == "diagnosis"
        assert payload["alpha"] == 2.0
        assert payload["beta"] == 1.0
        assert "mean" in payload and "variance" in payload

    def test_invalid_prior_raises(self) -> None:
        with pytest.raises(ValueError):
            CapabilityConfidenceScorer(prior_alpha=0.0, prior_beta=1.0)
        with pytest.raises(ValueError):
            CapabilityConfidenceScorer(prior_alpha=1.0, prior_beta=-0.5)


# ---------------------------------------------------------------------------
# AD-512f — ZPDCalibrator
# ---------------------------------------------------------------------------


class TestZPDCalibrator:
    def test_compute_band_low_confidence_yields_high_scaffolding(self) -> None:
        cal = ZPDCalibrator()
        # mean = 0.2 < 0.30 → "high" scaffolding hint.
        conf = CapabilityConfidence(
            agent_id="tau", capability_category="diagnosis", alpha=1.0, beta=4.0,
        )
        band = cal.compute_band(conf)

        assert isinstance(band, ZPDBand)
        assert band.scaffolding_hint == "high"
        assert band.agent_id == "tau"
        assert band.capability_category == "diagnosis"
        assert 0.0 <= band.difficulty_low <= band.difficulty_high <= 1.0

    def test_compute_band_high_confidence_yields_no_scaffolding(self) -> None:
        cal = ZPDCalibrator()
        # mean ≈ 0.95 → "none".
        conf = CapabilityConfidence(
            agent_id="tau", capability_category="diagnosis", alpha=19.0, beta=1.0,
        )
        band = cal.compute_band(conf)

        assert band.scaffolding_hint == "none"
        assert band.difficulty_high == pytest.approx(1.0)

    def test_select_scenarios_filters_by_difficulty_and_category(self) -> None:
        cal = ZPDCalibrator(lower_offset=0.40, upper_offset=0.75)
        reg = DiscoveryScenarioRegistry()
        all_scenarios = reg.list_scenarios()

        # Mean 0.5 → band [0.40, 0.75] (after +mean -0.5 offset = mean shift cancels).
        # Actually: difficulty_low = 0.5 + (0.40 - 0.5) = 0.40; high = 0.5 + (0.75 - 0.5) = 0.75.
        conf = CapabilityConfidence(
            agent_id="tau", capability_category="diagnosis", alpha=1.0, beta=1.0,
        )
        out = cal.select_scenarios(conf, all_scenarios)
        # Only diagnosis category scenarios with difficulty in [0.40, 0.75]:
        # diagnose_simple_fault (0.30) excluded, diagnose_cross_subsystem (0.65) included.
        ids = {s.scenario_id for s in out}
        assert ids == {"diagnose_cross_subsystem"}
        for s in out:
            assert s.capability_category == "diagnosis"

    def test_invalid_offsets_raise(self) -> None:
        with pytest.raises(ValueError):
            ZPDCalibrator(lower_offset=0.8, upper_offset=0.5)
        with pytest.raises(ValueError):
            ZPDCalibrator(lower_offset=-0.1, upper_offset=0.5)
        with pytest.raises(ValueError):
            ZPDCalibrator(lower_offset=0.4, upper_offset=1.5)


# ---------------------------------------------------------------------------
# DiscoveryLearningConfig
# ---------------------------------------------------------------------------


class TestDiscoveryLearningConfig:
    def test_default_enabled_true(self) -> None:
        cfg = DiscoveryLearningConfig()
        assert cfg.enabled is True
        assert cfg.confidence_prior_alpha == 1.0
        assert cfg.confidence_prior_beta == 1.0
        assert cfg.zpd_lower_bound == 0.40
        assert cfg.zpd_upper_bound == 0.75

    def test_zpd_band_validator_rejects_inverted(self) -> None:
        with pytest.raises(ValueError):
            DiscoveryLearningConfig(zpd_lower_bound=0.80, zpd_upper_bound=0.40)
        with pytest.raises(ValueError):
            # Equal bounds also rejected (must be strictly less).
            DiscoveryLearningConfig(zpd_lower_bound=0.50, zpd_upper_bound=0.50)

    def test_prior_alpha_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            DiscoveryLearningConfig(confidence_prior_alpha=0.0)
        with pytest.raises(ValueError):
            DiscoveryLearningConfig(confidence_prior_beta=0.0)


# ---------------------------------------------------------------------------
# Wiring integration — _wire_discovery_learning
# ---------------------------------------------------------------------------


class TestWiringIntegration:
    def test_wirer_disabled_returns_false(self) -> None:
        runtime = SimpleNamespace(emit_event=lambda *a, **k: None)
        config = SimpleNamespace(discovery_learning=DiscoveryLearningConfig(enabled=False))

        wired = _wire_discovery_learning(runtime=runtime, config=config)

        assert wired is False
        assert not hasattr(runtime, "discovery_scenario_registry")
        assert not hasattr(runtime, "strength_map")
        assert not hasattr(runtime, "capability_confidence_scorer")
        assert not hasattr(runtime, "zpd_calibrator")

    def test_wirer_enabled_attaches_four_attrs(self) -> None:
        emit = _FakeEmit()
        runtime = SimpleNamespace(emit_event=emit)
        config = SimpleNamespace(discovery_learning=DiscoveryLearningConfig(enabled=True))

        wired = _wire_discovery_learning(runtime=runtime, config=config)

        assert wired is True
        assert isinstance(runtime.discovery_scenario_registry, DiscoveryScenarioRegistry)
        assert isinstance(runtime.strength_map, StrengthMap)
        assert isinstance(runtime.capability_confidence_scorer, CapabilityConfidenceScorer)
        assert isinstance(runtime.zpd_calibrator, ZPDCalibrator)
        # All four substrates wired with the same emit hook.
        assert runtime.discovery_scenario_registry.emit_event is emit
        assert runtime.strength_map.emit_event is emit
        assert runtime.capability_confidence_scorer.emit_event is emit
        assert runtime.zpd_calibrator.emit_event is emit

    def test_wirer_passes_priors_into_scorer(self) -> None:
        runtime = SimpleNamespace(emit_event=lambda *a, **k: None)
        config = SimpleNamespace(discovery_learning=DiscoveryLearningConfig(
            enabled=True,
            confidence_prior_alpha=2.0,
            confidence_prior_beta=3.0,
            zpd_lower_bound=0.30,
            zpd_upper_bound=0.80,
        ))

        wired = _wire_discovery_learning(runtime=runtime, config=config)

        assert wired is True
        # Default prior reads back as (2.0, 3.0).
        conf = runtime.capability_confidence_scorer.get_confidence("alpha", "diagnosis")
        assert conf.alpha == 2.0 and conf.beta == 3.0
