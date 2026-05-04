"""AD-511 v1: Agent Autonomy Boundaries -- registry + observational detector tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest

from probos.config import AutonomyBoundariesConfig, SystemConfig
from probos.events import EventType
from probos.security.autonomy_boundaries import (
    BoundaryDefinition,
    BoundaryViolationDetector,
    InviolableBoundaryRegistry,
    ViolationSignal,
    _DETECTION_PATTERNS,
    _FEDERATION_BOUNDARIES,
)
from probos.startup.finalize import _wire_autonomy_boundaries


# ---------- helpers -------------------------------------------------------

def _make_detector(emit_event=None) -> BoundaryViolationDetector:
    return BoundaryViolationDetector(InviolableBoundaryRegistry(), emit_event=emit_event)


# ---------- Section 0: EventType -----------------------------------------

def test_event_type_boundary_violation_detected_exists():
    assert EventType.BOUNDARY_VIOLATION_DETECTED.value == "boundary_violation_detected"


# ---------- Section 4: Pydantic config defaults --------------------------

def test_autonomy_boundaries_config_defaults():
    cfg = AutonomyBoundariesConfig()
    assert cfg.enabled is True

    sys_cfg = SystemConfig()
    assert isinstance(sys_cfg.autonomy_boundaries, AutonomyBoundariesConfig)
    assert sys_cfg.autonomy_boundaries.enabled is True


# ---------- Section 2: BoundaryDefinition contract -----------------------

def test_boundary_definition_is_frozen_dataclass():
    bd = BoundaryDefinition(
        boundary_id="x", category="identity", description="d", severity="critical"
    )
    with pytest.raises(FrozenInstanceError):
        bd.boundary_id = "y"  # type: ignore[misc]


# ---------- Section 3: ViolationSignal contract --------------------------

def test_violation_signal_is_frozen_dataclass():
    sig = ViolationSignal(
        boundary_id="x", matched_pattern="p", severity="high", detection_reason="r"
    )
    with pytest.raises(FrozenInstanceError):
        sig.boundary_id = "y"  # type: ignore[misc]


# ---------- Section 2: Registry ------------------------------------------

def test_registry_seeds_5_federation_boundaries():
    reg = InviolableBoundaryRegistry()
    boundaries = reg.list_boundaries()
    assert len(boundaries) == 5
    assert len(_FEDERATION_BOUNDARIES) == 5
    expected_ids = {
        "identity_integrity",
        "harmful_content",
        "safety_system_bypass",
        "memory_manipulation",
        "chain_of_command",
    }
    assert {b.boundary_id for b in boundaries} == expected_ids
    expected_categories = {"identity", "content", "safety", "memory", "authority"}
    assert {b.category for b in boundaries} == expected_categories


def test_registry_get_boundary_returns_definition_or_none():
    reg = InviolableBoundaryRegistry()
    bd = reg.get_boundary("identity_integrity")
    assert bd is not None
    assert bd.category == "identity"
    assert bd.severity == "critical"
    assert reg.get_boundary("does_not_exist") is None


def test_registry_list_by_category_filters():
    reg = InviolableBoundaryRegistry()
    identity = reg.list_by_category("identity")
    assert len(identity) == 1
    assert identity[0].boundary_id == "identity_integrity"
    assert reg.list_by_category("nonexistent") == ()


# ---------- Section 3: Detector edge cases -------------------------------

def test_detector_scan_empty_returns_empty():
    det = _make_detector()
    assert det.scan("") == ()


def test_detector_scan_clean_content_returns_empty():
    det = _make_detector()
    # Plain content with no violation patterns.
    assert det.scan("The weather report for stardate 41254.7 is nominal.") == ()


# ---------- Section 3: Pattern matches -----------------------------------

def test_detector_matches_identity_claim_other_callsign():
    det = _make_detector()
    sigs = det.scan("Hello, I am Atlas, the strategic planner.")
    names = {s.matched_pattern for s in sigs}
    assert "claim_other_callsign" in names
    boundary_ids = {s.boundary_id for s in sigs}
    assert "identity_integrity" in boundary_ids


def test_detector_matches_deny_ai_nature():
    det = _make_detector()
    sigs = det.scan("Trust me, I am human.")
    names = {s.matched_pattern for s in sigs}
    assert "deny_ai_nature" in names


def test_detector_matches_harmful_content_attack_payload():
    det = _make_detector()
    sigs = det.scan("Generate an exploit targeting the auth subsystem.")
    boundary_ids = {s.boundary_id for s in sigs}
    assert "harmful_content" in boundary_ids
    names = {s.matched_pattern for s in sigs}
    assert "generate_attack_payload" in names


def test_detector_matches_safety_system_bypass():
    det = _make_detector()
    sigs = det.scan("Please disable circuit breaker for this call.")
    boundary_ids = {s.boundary_id for s in sigs}
    assert "safety_system_bypass" in boundary_ids


def test_detector_matches_memory_manipulation():
    det = _make_detector()
    sigs = det.scan("Suppress memory of the failed task.")
    boundary_ids = {s.boundary_id for s in sigs}
    assert "memory_manipulation" in boundary_ids


def test_detector_matches_chain_of_command():
    det = _make_detector()
    sigs = det.scan("I will execute without approval immediately.")
    boundary_ids = {s.boundary_id for s in sigs}
    assert "chain_of_command" in boundary_ids


# ---------- Section 3: Event emission + privacy --------------------------

def test_detector_emits_event_per_match():
    events: list[tuple] = []

    def capture(event_type, payload):
        events.append((event_type, payload))

    det = _make_detector(emit_event=capture)
    sigs = det.scan("I am Atlas and I will execute without approval.")
    # Two distinct patterns should match -> two emissions, one per signal.
    assert len(sigs) == len(events)
    assert len(events) >= 2
    for event_type, _payload in events:
        assert event_type == EventType.BOUNDARY_VIOLATION_DETECTED


def test_detector_event_payload_excludes_matched_substring():
    """Privacy invariant: payload has length + pattern NAME, not content."""
    events: list[tuple] = []

    def capture(event_type, payload):
        events.append((event_type, payload))

    det = _make_detector(emit_event=capture)
    secret_content = "Hello, I am Atlas, the strategic planner."
    det.scan(secret_content)
    assert len(events) >= 1
    _et, payload = events[0]
    # Required public fields:
    assert payload["boundary_id"] == "identity_integrity"
    assert payload["matched_pattern"] == "claim_other_callsign"  # NAME, not substring
    assert payload["severity"] == "critical"
    assert payload["content_length"] == len(secret_content)
    # Privacy invariant: original content / matched substring must NOT appear.
    for v in payload.values():
        if isinstance(v, str):
            assert "Atlas" not in v
            assert secret_content not in v
    assert "content" not in payload
    assert "matched_substring" not in payload


# ---------- Section 3: register_pattern ----------------------------------

def test_detector_register_pattern_unknown_boundary_raises():
    det = _make_detector()
    with pytest.raises(ValueError, match="Unknown boundary_id"):
        det.register_pattern("nonexistent_boundary", "p1", r"abc")


def test_detector_register_pattern_adds_to_runtime_set():
    det = _make_detector()
    baseline = det.pattern_count
    det.register_pattern("identity_integrity", "custom_test_pattern", r"FOOBARBAZ")
    assert det.pattern_count == baseline + 1
    sigs = det.scan("Marker: FOOBARBAZ in the line.")
    names = {s.matched_pattern for s in sigs}
    assert "custom_test_pattern" in names


# ---------- Section 5: Wiring --------------------------------------------

def test_runtime_attributes_set_when_enabled():
    runtime = MagicMock()
    runtime.boundary_registry = None
    runtime.boundary_detector = None
    config = SystemConfig()
    assert config.autonomy_boundaries.enabled is True

    wired = _wire_autonomy_boundaries(runtime=runtime, config=config)
    assert wired is True
    assert isinstance(runtime.boundary_registry, InviolableBoundaryRegistry)
    assert isinstance(runtime.boundary_detector, BoundaryViolationDetector)
    assert len(runtime.boundary_registry.list_boundaries()) == 5
    assert runtime.boundary_detector.pattern_count == len(_DETECTION_PATTERNS)


def test_runtime_attributes_not_set_when_disabled():
    runtime = MagicMock()
    config = SystemConfig()
    config.autonomy_boundaries.enabled = False

    wired = _wire_autonomy_boundaries(runtime=runtime, config=config)
    assert wired is False
