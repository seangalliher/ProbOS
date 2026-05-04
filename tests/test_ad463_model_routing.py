"""AD-463 Model Diversity & Neural Routing tests."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.model_registry import (
    ModelCapability,
    ModelDescriptor,
    ModelRegistry,
)
from probos.cognitive.model_router import ModelRouter, RoutingDecision
from probos.config import ModelRoutingConfig
from probos.events import EventType


# ----- EventTypes -----


def test_event_type_model_routed_exists():
    assert EventType.MODEL_ROUTED.value == "model_routed"


def test_event_type_model_fallback_exists():
    assert EventType.MODEL_FALLBACK.value == "model_fallback"


# ----- Config -----


def test_model_routing_config_defaults():
    cfg = ModelRoutingConfig()
    assert cfg.enabled is True
    assert cfg.cost_ceiling_per_million_output_tokens is None


# ----- ModelDescriptor / Registry -----


def test_model_descriptor_immutable():
    d = ModelDescriptor(name="m", provider="x", tier="fast", available=True)
    d2 = replace(d, available=False)
    assert d.available is True  # original unchanged
    assert d2.available is False


def test_model_registry_default_seed_includes_three_tiers():
    reg = ModelRegistry()
    assert len(reg.by_tier("fast")) >= 1
    assert len(reg.by_tier("standard")) >= 1
    assert len(reg.by_tier("deep")) >= 1


def test_model_registry_register_overwrites_by_name():
    reg = ModelRegistry()
    new_d = ModelDescriptor(
        name="claude-sonnet-4-6-fast",  # overwrites seed
        provider="anthropic",
        tier="fast",
        cost_per_million_output_tokens=0.99,
    )
    reg.register(new_d)
    got = reg.get("claude-sonnet-4-6-fast")
    assert got is not None
    assert got.cost_per_million_output_tokens == 0.99
    # Other seeds preserved
    assert reg.get("claude-sonnet-4-6") is not None


def test_model_registry_mark_unavailable_excludes_from_by_tier():
    reg = ModelRegistry()
    assert any(d.name == "claude-sonnet-4-6-fast" for d in reg.by_tier("fast"))
    assert reg.mark_unavailable("claude-sonnet-4-6-fast") is True
    assert not any(d.name == "claude-sonnet-4-6-fast" for d in reg.by_tier("fast"))


# ----- Router -----


def test_router_single_candidate_returns_it():
    reg = ModelRegistry()
    # Mark all but one fast model unavailable - default seed has only 1 fast
    emit = MagicMock()
    router = ModelRouter(registry=reg, emit_event=emit)
    decision = router.choose(tier="fast")
    assert decision.chosen_model == "claude-sonnet-4-6-fast"
    assert decision.reason == "single candidate"
    assert decision.fallback is False
    et, _ = emit.call_args[0]
    assert et == EventType.MODEL_ROUTED


def test_router_picks_cheapest_among_tier():
    reg = ModelRegistry()
    # Add a more expensive fast model
    reg.register(ModelDescriptor(
        name="expensive-fast",
        provider="openai",
        tier="fast",
        cost_per_million_output_tokens=100.0,
    ))
    emit = MagicMock()
    router = ModelRouter(registry=reg, emit_event=emit)
    decision = router.choose(tier="fast")
    # claude-sonnet-4-6-fast at $15.0 < expensive-fast at $100.0
    assert decision.chosen_model == "claude-sonnet-4-6-fast"
    assert decision.reason == "cheapest-by-output-cost"


def test_router_cost_ceiling_filters_candidates():
    reg = ModelRegistry()
    emit = MagicMock()
    router = ModelRouter(registry=reg, emit_event=emit)
    # Standard tier has claude-sonnet at $15/M; ceiling=1.0 should exclude
    decision = router.choose(tier="standard", cost_ceiling=1.0)
    # No candidates left in standard under ceiling -> fallback
    assert decision.fallback is True


def test_router_no_candidates_emits_fallback():
    reg = ModelRegistry()
    # Mark all fast models unavailable
    for d in reg.by_tier("fast"):
        reg.mark_unavailable(d.name)
    emit = MagicMock()
    router = ModelRouter(registry=reg, emit_event=emit)
    decision = router.choose(tier="fast")
    assert decision.fallback is True
    assert decision.chosen_model != ""  # picked something from another tier
    et, _ = emit.call_args[0]
    assert et == EventType.MODEL_FALLBACK


def test_router_no_models_at_all_returns_empty_decision():
    reg = ModelRegistry()
    for d in reg.all():
        reg.mark_unavailable(d.name)
    emit = MagicMock()
    router = ModelRouter(registry=reg, emit_event=emit)
    decision = router.choose(tier="fast")
    assert decision.chosen_model == ""
    assert decision.fallback is True
    et, _ = emit.call_args[0]
    assert et == EventType.MODEL_FALLBACK


# ----- LLM client integration -----


def test_llm_client_resolve_model_for_tier_when_router_absent_returns_none():
    client = OpenAICompatibleClient(model_router=None)
    assert client._resolve_model_for_tier("fast") is None


def test_llm_client_resolve_model_for_tier_with_router_returns_chosen():
    reg = ModelRegistry()
    router = ModelRouter(registry=reg)
    client = OpenAICompatibleClient(model_router=router)
    chosen = client._resolve_model_for_tier("fast")
    assert chosen == "claude-sonnet-4-6-fast"


def test_llm_client_resolve_model_for_tier_with_failing_router_falls_back():
    bad_router = MagicMock()
    bad_router.choose = MagicMock(side_effect=RuntimeError("boom"))
    client = OpenAICompatibleClient(model_router=bad_router)
    assert client._resolve_model_for_tier("fast") is None


def test_llm_client_resolve_model_for_tier_empty_string_returns_none():
    """Empty chosen_model from router converts to None so existing path runs."""
    reg = ModelRegistry()
    for d in reg.all():
        reg.mark_unavailable(d.name)  # forces empty fallback
    router = ModelRouter(registry=reg)
    client = OpenAICompatibleClient(model_router=router)
    assert client._resolve_model_for_tier("fast") is None
