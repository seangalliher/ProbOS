"""AD-733: vision_observation IntentDescriptor registration."""
from __future__ import annotations

from probos.perception import VISION_OBSERVATION_DESCRIPTOR


def test_descriptor_does_not_require_consensus() -> None:
    """Sensor stream is read-only and non-destructive."""
    assert VISION_OBSERVATION_DESCRIPTOR.requires_consensus is False


def test_descriptor_metadata_matches_wire_shape() -> None:
    assert VISION_OBSERVATION_DESCRIPTOR.name == "vision_observation"
    assert VISION_OBSERVATION_DESCRIPTOR.tier == "domain"
    assert "attachment_ref" in VISION_OBSERVATION_DESCRIPTOR.params
