"""AD-722e (Wave 154): deterministic structured self-perception v1.

Six tests:

1. ``test_projection_returns_dataclass_with_pipeline_version`` — happy path.
2. ``test_projection_returns_none_when_telemetry_disabled`` — config gate.
3. ``test_projection_returns_none_when_no_snapshot`` — snapshot gate.
4. ``test_projection_fields_match_snapshot`` — round-trip of every field.
5. ``test_projection_function_does_not_import_llm_client`` — AD-727 rule #4
   double-guard at module import time.
6. ``test_cognitive_agent_self_observation_includes_pipeline_version_line``
   — wiring into ``CognitiveAgent._build_avatar_self_observation``.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def fake_snapshot():
    """Stub AvatarTelemetrySnapshot — duck-typed for the projector."""
    return SimpleNamespace(
        agent_id="agent-1",
        expression_resting="calm",
        current_signals=SimpleNamespace(working_state="responding"),
        mouth_active=True,
        applied_modulation=SimpleNamespace(rate_factor=1.2, pitch_factor=0.9),
        dsl_summary=SimpleNamespace(
            body_type="slender",
            hair_style="short",
            primary_color="amber",
            outfit_style="duty",
        ),
    )


@pytest.fixture
def patch_snapshot_builder(monkeypatch, fake_snapshot):
    """Patch build_telemetry_snapshot at the self_perception module."""
    from probos.cognitive import self_perception as sp_mod

    async def _build(agent_id, runtime, intent_emotion=None):
        return fake_snapshot

    monkeypatch.setattr(sp_mod, "build_telemetry_snapshot", _build)
    return fake_snapshot


@pytest.mark.asyncio
async def test_projection_returns_dataclass_with_pipeline_version(
    patch_snapshot_builder,
):
    """Telemetry-enabled + snapshot present → SelfPerceptionProjection with version."""
    from probos.cognitive.self_perception import (
        PIPELINE_VERSION,
        SelfPerceptionProjection,
        project_self_perception,
    )
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            avatar_telemetry=SimpleNamespace(enabled=True),
        ),
    )
    projection = await project_self_perception("agent-1", runtime)
    assert isinstance(projection, SelfPerceptionProjection)
    assert projection.pipeline_version == PIPELINE_VERSION == "1.0.0"


@pytest.mark.asyncio
async def test_projection_returns_none_when_telemetry_disabled(
    patch_snapshot_builder,
):
    """Telemetry disabled → returns None, no exception."""
    from probos.cognitive.self_perception import project_self_perception
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            avatar_telemetry=SimpleNamespace(enabled=False),
        ),
    )
    assert await project_self_perception("agent-1", runtime) is None


@pytest.mark.asyncio
async def test_projection_returns_none_when_no_snapshot(monkeypatch):
    """build_telemetry_snapshot returns None → projector returns None."""
    from probos.cognitive import self_perception as sp_mod

    async def _build_none(agent_id, runtime, intent_emotion=None):
        return None

    monkeypatch.setattr(sp_mod, "build_telemetry_snapshot", _build_none)

    runtime = SimpleNamespace(
        config=SimpleNamespace(
            avatar_telemetry=SimpleNamespace(enabled=True),
        ),
    )
    assert await sp_mod.project_self_perception("agent-1", runtime) is None


@pytest.mark.asyncio
async def test_projection_fields_match_snapshot(patch_snapshot_builder):
    """Every projection field mirrors the corresponding snapshot field."""
    from probos.cognitive.self_perception import project_self_perception
    runtime = SimpleNamespace(
        config=SimpleNamespace(
            avatar_telemetry=SimpleNamespace(enabled=True),
        ),
    )
    p = await project_self_perception("agent-1", runtime)
    assert p is not None
    assert p.agent_id == "agent-1"
    assert p.dsl_body_type == "slender"
    assert p.dsl_hair_style == "short"
    assert p.dsl_outfit_style == "duty"
    assert p.dsl_primary_color == "amber"
    assert p.working_state == "responding"
    assert p.expression_resting == "calm"
    assert p.mouth_active is True
    assert p.modulation_rate_factor == pytest.approx(1.2)
    assert p.modulation_pitch_factor == pytest.approx(0.9)


def test_projection_function_does_not_import_llm_client():
    """AD-727 rule #4 double-guard: the module's own namespace must not
    carry any LLM-client symbol after import.
    """
    # Force reimport to make sure the module-level namespace is fresh.
    sys.modules.pop("probos.cognitive.self_perception", None)
    import probos.cognitive.self_perception as sp_mod  # noqa: E402

    forbidden = {
        "OpenAICompatibleClient",
        "LLMRequest",
        "LLMResponse",
        "MockLLMClient",
        "llm_client",
    }
    overlap = forbidden & set(vars(sp_mod))
    assert not overlap, (
        f"AD-727 rule #4: self_perception module namespace must not carry "
        f"LLM-client symbols, found: {sorted(overlap)}"
    )


def test_cognitive_agent_self_observation_includes_pipeline_version_line(
    fake_snapshot,
):
    """_build_avatar_self_observation injects a ``pipeline_version: X`` line."""
    from probos.cognitive.cognitive_agent import CognitiveAgent

    runtime = SimpleNamespace(
        config=SimpleNamespace(
            avatar_telemetry=SimpleNamespace(inject_into_agent_context=True),
        ),
    )

    # Construct a minimal CognitiveAgent via __new__ to avoid the full
    # __init__ chain (we only need the method under test + a few attrs).
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent._runtime = runtime
    agent._last_self_avatar_snap = fake_snapshot
    agent.id = "agent-1"

    rendered = agent._build_avatar_self_observation({})
    assert "pipeline_version" in rendered
    assert "1.0.0" in rendered
