"""AD-730-5 (Wave 154): per-agent_type vision tier override.

A future Imaging Officer / Diagnostician variant may want a specialized
vision model (medical imaging, satellite imagery). v1 ships the config
plumbing + helper; no second LLM endpoint is wired (separate AD when a
real model lands).

These tests pin the helper's contract. The router/agent call sites
exercise it indirectly via AD-720d-2 / AD-732 fixtures.
"""

from __future__ import annotations

from types import SimpleNamespace

from probos.cognitive.vision_dispatch import resolve_vision_tier_for_agent
from probos.config import AttachmentsConfig


def test_resolve_vision_tier_no_override_returns_default():
    """Empty overrides dict → helper returns default unchanged."""
    cfg = AttachmentsConfig()
    assert cfg.vision_tier_overrides == {}
    assert resolve_vision_tier_for_agent(cfg, "Counselor", "vision") == "vision"
    # Empty agent_type also short-circuits to default.
    assert resolve_vision_tier_for_agent(cfg, "", "vision") == "vision"


def test_resolve_vision_tier_override_hits():
    """vision_tier_overrides hit returns the configured override tier."""
    cfg = AttachmentsConfig(vision_tier_overrides={"Diagnostician": "vision_medical"})
    assert (
        resolve_vision_tier_for_agent(cfg, "Diagnostician", "vision")
        == "vision_medical"
    )


def test_resolve_vision_tier_override_for_unmapped_agent_type():
    """Override map has Counselor but not Diagnostician → Diagnostician → default."""
    cfg = AttachmentsConfig(vision_tier_overrides={"Counselor": "vision_b"})
    assert (
        resolve_vision_tier_for_agent(cfg, "Diagnostician", "vision")
        == "vision"
    )
    # Sanity: Counselor still gets the override
    assert (
        resolve_vision_tier_for_agent(cfg, "Counselor", "vision")
        == "vision_b"
    )
    # SimpleNamespace shaped config (router call site) also works
    ns_cfg = SimpleNamespace(vision_tier_overrides={"Counselor": "vision_b"})
    assert resolve_vision_tier_for_agent(ns_cfg, "Counselor", "vision") == "vision_b"
