"""AD-723a-1 (Wave 148) — DM consumer-side sensorium dispatch migration.

Tests cover:
1. Avatar block injected at AD-722 zone when enabled.
2. Avatar block absent when feature disabled.
3. Byte-parity between dispatched prompt and a manually-assembled reference.
4. New registered DM_ONESHOT entry surfaces via _DM_SELF_WRAPPED_KEYS.
5. Tier-2 degrade when dispatcher raises.
6. Single-call-site invariant: no direct method calls remain in
   _build_user_message.
"""
from __future__ import annotations

import inspect
import logging
import time
from types import SimpleNamespace
from typing import Any

import pytest

from probos.avatars.telemetry import (
    AgentSignalsSnapshot,
    AvatarTelemetrySnapshot,
    ModulationSnapshot,
)
from probos.cognitive.cognitive_agent import (
    CognitiveAgent,
    SensoriumEntry,
    SensoriumLayer,
    SensoriumPath,
)


# ── Stub helpers ────────────────────────────────────────────────────────


def _make_runtime(*, inject: bool, divergence: bool = False) -> SimpleNamespace:
    """Minimal runtime stub for DM _build_user_message rendering.

    Provides only attributes the DM path reads: ``config.avatar_telemetry``
    (AD-722 gate), and ``divergence_results`` (AD-722a divergence note).
    All other lookups (boot_camp, _introspective_telemetry, recreation_service)
    return None via SimpleNamespace default behaviour (attr missing).
    """
    rt = SimpleNamespace()
    rt.config = SimpleNamespace(
        avatar_telemetry=SimpleNamespace(
            inject_into_agent_context=inject,
            divergence_detection=divergence,
        ),
    )
    rt.divergence_results = {}
    rt.boot_camp = None
    rt.recreation_service = None
    rt._introspective_telemetry = None
    return rt


def _make_snapshot(agent_id: str) -> AvatarTelemetrySnapshot:
    signals = AgentSignalsSnapshot(
        trust_delta=0.0,
        load=0.0,
        working_state="idle",
        tier3_alert=False,
    )
    mod = ModulationSnapshot(
        pitch_factor=1.0,
        rate_factor=1.0,
        volume_factor=1.0,
        fired_rules=("high_trust_pitch",),
    )
    return AvatarTelemetrySnapshot(
        agent_id=agent_id,
        expression_resting="neutral",
        current_signals=signals,
        mouth_active=False,
        applied_modulation=mod,
        dsl_summary=None,
        last_observed_at=0.0,
        degraded_reasons=(),
        sampling_rate_ms=2000,
        sampling_tier="normal",
    )


def _make_agent(*, inject: bool, divergence: bool = False, with_snapshot: bool = True):
    """Build a CognitiveAgent stub via __new__ — bypass __init__ wiring."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.id = "agent-test-001"
    agent.callsign = "TestCaller"
    agent.agent_type = "scout"
    agent._runtime = _make_runtime(inject=inject, divergence=divergence)
    agent._working_memory = None
    agent._last_self_avatar_snap = _make_snapshot(agent.id) if with_snapshot else None
    return agent


def _make_dm_observation(text: str = "Hello, ship.") -> dict:
    return {
        "intent": "direct_message",
        "params": {"text": text},
        "timestamp": time.time(),
    }


# ── §1. Avatar block present when feature enabled ───────────────────────


@pytest.mark.asyncio
async def test_dm_dispatch_includes_avatar_block_when_enabled():
    """AD-723a-1: dispatcher surfaces the avatar block at the AD-722 zone.

    The block appears after working-memory rendering (none here, so just
    after temporal context) and before ``Captain says:``.
    """
    agent = _make_agent(inject=True)
    obs = _make_dm_observation("Status report?")

    result = await agent._build_user_message(obs)

    assert "Your current avatar state:" in result
    # Avatar zone is before Captain says line.
    avatar_idx = result.index("Your current avatar state:")
    captain_idx = result.index("Captain says:")
    assert avatar_idx < captain_idx, (
        "Avatar block must appear before the Captain-says line"
    )


# ── §2. Avatar block absent when feature disabled ───────────────────────


@pytest.mark.asyncio
async def test_dm_dispatch_omits_avatar_block_when_disabled():
    """Feature gate off → empty registered output → no zone content."""
    agent = _make_agent(inject=False)
    obs = _make_dm_observation("Status report?")

    result = await agent._build_user_message(obs)

    assert "Your current avatar state:" not in result
    assert "Captain says: Status report?" in result


# ── §3. Byte-parity with manual reference assembly ──────────────────────


@pytest.mark.asyncio
async def test_dm_dispatch_byte_parity_with_direct_method_call():
    """Dispatched output byte-equals a manual assembly through the same
    registered methods.

    Both renderings receive the same observation and same runtime stub.
    The dispatcher path appends ``_avatar_self_observation`` then
    ``_intent_self_tag``; the reference path mirrors that order via direct
    method calls. The AD-722 zone bytes must match exactly.
    """
    agent = _make_agent(inject=True, divergence=True)
    obs = _make_dm_observation("Ping.")

    dispatched = await agent._build_user_message(obs)

    # Manual reference: dispatch each registered method directly and
    # reconstruct the AD-722 zone with the same parts.append ordering.
    avatar_block = agent._build_avatar_self_observation(obs)
    tag_line = agent._build_intent_self_tag_instruction()

    # Both should produce non-empty output in this configuration.
    assert avatar_block, "avatar block expected with inject=True + snapshot"
    assert tag_line, "self-tag instruction expected with divergence_detection=True"

    # Each block ends with \n (because of the trailing parts.append("")
    # joined with '\n'). Concatenated zone — what the dispatcher will write.
    expected_zone = f"{avatar_block}\n\n{tag_line}\n"

    assert expected_zone in dispatched, (
        "Dispatched DM prompt must contain the byte-identical AD-722 zone "
        "produced by sequential direct method calls."
    )


# ── §4. New registered DM_ONESHOT entry surfaces via constant ───────────


@pytest.mark.asyncio
async def test_dm_dispatch_picks_up_new_registered_entry(monkeypatch):
    """A new DM_ONESHOT-tagged entry whose output_key is in
    _DM_SELF_WRAPPED_KEYS renders at the zone with no further wiring.
    """
    agent = _make_agent(inject=False)
    obs = _make_dm_observation("Ping.")

    # Add a stub method that the dispatcher will discover via getattr.
    def _sensorium_test_block(_observation: dict) -> str:
        return "STUB-OUTPUT"

    agent._sensorium_test_block = _sensorium_test_block  # type: ignore[attr-defined]

    # Extend the registry + the self-wrapped keys tuple (class-level patch).
    new_registry = dict(CognitiveAgent.SENSORIUM_REGISTRY)
    new_registry["_sensorium_test_block"] = SensoriumEntry(
        layer=SensoriumLayer.INTEROCEPTION,
        description="AD-723a-1 test stub",
        paths=(SensoriumPath.DM_ONESHOT,),
        output_key="_test_block",
    )
    monkeypatch.setattr(CognitiveAgent, "SENSORIUM_REGISTRY", new_registry)
    monkeypatch.setattr(
        CognitiveAgent,
        "_DM_SELF_WRAPPED_KEYS",
        ("_avatar_self_observation", "_intent_self_tag", "_test_block"),
    )

    result = await agent._build_user_message(obs)

    assert "STUB-OUTPUT" in result
    stub_idx = result.index("STUB-OUTPUT")
    captain_idx = result.index("Captain says:")
    assert stub_idx < captain_idx


# ── §5. Tier-2 degrade on dispatcher failure ────────────────────────────


@pytest.mark.asyncio
async def test_dm_dispatch_tier2_degrade_on_dispatcher_failure(monkeypatch, caplog):
    """Dispatcher exception is logged at DEBUG and swallowed; DM prompt
    still assembles cleanly through to ``Captain says:``.
    """
    agent = _make_agent(inject=True)
    obs = _make_dm_observation("Even on failure, this must render.")

    async def _boom(self, path, observation):
        raise RuntimeError("simulated dispatcher failure")

    monkeypatch.setattr(
        CognitiveAgent, "_dispatch_sensorium_async", _boom, raising=True,
    )

    with caplog.at_level(logging.DEBUG, logger="probos.cognitive.cognitive_agent"):
        result = await agent._build_user_message(obs)

    assert "Captain says: Even on failure, this must render." in result
    assert "Your current avatar state:" not in result, (
        "Degrade path must skip the injection zone, not raise into it."
    )
    assert any(
        "AD-723a-1: DM sensorium dispatch failed" in rec.message
        for rec in caplog.records
    ), "Expected Tier-2 degrade log line was not emitted"


# ── §6. Single-call-site invariant (regression gate) ────────────────────


def test_no_direct_avatar_method_call_remains_in_build_user_message():
    """Regression gate: prevent re-introducing the hand-rolled call site.

    The source of ``_build_user_message`` MUST NOT call
    ``_build_avatar_self_observation(`` or
    ``_build_intent_self_tag_instruction(`` directly. The only legitimate
    surface for these methods is the SENSORIUM_REGISTRY dispatch path.
    """
    src = inspect.getsource(CognitiveAgent._build_user_message)
    assert "_build_avatar_self_observation(" not in src, (
        "Direct call to _build_avatar_self_observation re-introduced in "
        "_build_user_message — must route through _dispatch_sensorium_async."
    )
    assert "_build_intent_self_tag_instruction(" not in src, (
        "Direct call to _build_intent_self_tag_instruction re-introduced in "
        "_build_user_message — must route through _dispatch_sensorium_async."
    )
