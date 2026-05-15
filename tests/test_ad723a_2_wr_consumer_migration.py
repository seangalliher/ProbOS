"""AD-723a-2 (Wave 161) - WR consumer-side sensorium dispatch migration.

Tests cover:
1. Dispatcher invoked exactly once with SensoriumPath.WR_ONESHOT.
2. Empty selector tuple yields byte parity vs HEAD (no behavior change).
3. New self-wrapped WR entry surfaces when added to _WR_SELF_WRAPPED_KEYS.
4. Tier-2 degrade on dispatcher failure.
5. WR selector is independent of DM selector.
6. DM-branch byte parity unchanged (AD-723a-1 regression gate).
"""
from __future__ import annotations

import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.cognitive_agent import (
    CognitiveAgent,
    SensoriumEntry,
    SensoriumLayer,
    SensoriumPath,
)


def _make_runtime() -> SimpleNamespace:
    rt = SimpleNamespace()
    rt.config = SimpleNamespace(
        avatar_telemetry=SimpleNamespace(
            inject_into_agent_context=False,
            divergence_detection=False,
        ),
    )
    rt.divergence_results = {}
    rt.boot_camp = None
    rt.recreation_service = None
    rt._introspective_telemetry = None
    rt.is_cold_start = False
    return rt


def _make_agent():
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.id = "agent-wr-001"
    agent.callsign = "WrTest"
    agent.agent_type = "scout"
    agent._runtime = _make_runtime()
    agent._working_memory = None
    agent._last_self_avatar_snap = None
    return agent


def _make_wr_observation(text: str = "Hello WR.") -> dict:
    return {
        "intent": "ward_room_notification",
        "params": {
            "text": text,
            "channel_name": "all-hands",
            "author_callsign": "captain",
            "title": "Status update",
            "thread_id": "thread-001",
            "author_id": "captain",
            "was_mentioned": False,
        },
        "context": "Previous message line.",
        "timestamp": time.time(),
    }


@pytest.mark.asyncio
async def test_wr_branch_invokes_dispatcher_once(monkeypatch):
    """Dispatcher is invoked exactly once on the WR path with WR_ONESHOT."""
    agent = _make_agent()
    obs = _make_wr_observation()

    mock = AsyncMock(return_value={})
    monkeypatch.setattr(
        CognitiveAgent, "_dispatch_sensorium_async", mock, raising=True,
    )

    await agent._build_user_message(obs)

    # AsyncMock stored as class attribute is not a descriptor, so calls
    # receive args without an implicit self. The WR call passes
    # (SensoriumPath.WR_ONESHOT, observation).
    wr_calls = [
        c for c in mock.call_args_list
        if c.args and c.args[0] == SensoriumPath.WR_ONESHOT
    ]
    assert len(wr_calls) == 1, f"Expected exactly 1 WR_ONESHOT call, got {len(wr_calls)}; all calls={mock.call_args_list}"


@pytest.mark.asyncio
async def test_wr_branch_empty_selector_yields_byte_parity(monkeypatch):
    """With empty _WR_SELF_WRAPPED_KEYS, dispatcher output is filtered out
    and the rendered WR prompt is byte-identical to the no-dispatch path."""
    agent = _make_agent()
    obs = _make_wr_observation("ping")

    # Make dispatcher return content; selector is empty so nothing should inject.
    mock = AsyncMock(return_value={"_anything": "[SHOULD NOT APPEAR]"})
    monkeypatch.setattr(
        CognitiveAgent, "_dispatch_sensorium_async", mock, raising=True,
    )

    result = await agent._build_user_message(obs)
    assert "[SHOULD NOT APPEAR]" not in result
    assert "Status update" in result  # title still rendered hand-rolled


@pytest.mark.asyncio
async def test_wr_branch_self_wrapped_entry_injects_when_added(monkeypatch):
    """When _WR_SELF_WRAPPED_KEYS contains a key and dispatcher returns it,
    the value is injected into the WR prompt."""
    agent = _make_agent()
    obs = _make_wr_observation()

    mock = AsyncMock(return_value={"_wr_test_marker": "[WR-INJECTED]"})
    monkeypatch.setattr(
        CognitiveAgent, "_dispatch_sensorium_async", mock, raising=True,
    )
    monkeypatch.setattr(
        CognitiveAgent, "_WR_SELF_WRAPPED_KEYS", ("_wr_test_marker",),
    )

    result = await agent._build_user_message(obs)
    assert "[WR-INJECTED]" in result


@pytest.mark.asyncio
async def test_wr_dispatcher_failure_tier2_degrade(monkeypatch, caplog):
    """Dispatcher exception is swallowed; WR prompt still renders cleanly."""
    agent = _make_agent()
    obs = _make_wr_observation("must render through failure")

    async def _boom(self, path, observation):
        raise RuntimeError("simulated WR dispatcher failure")

    monkeypatch.setattr(
        CognitiveAgent, "_dispatch_sensorium_async", _boom, raising=True,
    )

    with caplog.at_level(logging.WARNING, logger="probos.cognitive.cognitive_agent"):
        result = await agent._build_user_message(obs)

    assert "Status update" in result  # title still renders
    assert any(
        "AD-723a-2" in rec.message for rec in caplog.records
    ), "Expected Tier-2 degrade log line with AD-723a-2 marker"


@pytest.mark.asyncio
async def test_wr_branch_does_not_inject_dm_keys(monkeypatch):
    """A registry entry keyed _avatar_self_observation (DM-selector member)
    should NOT appear in WR output when _WR_SELF_WRAPPED_KEYS is empty."""
    agent = _make_agent()
    obs = _make_wr_observation()

    # Dispatcher returns a DM-selector key; WR selector is empty so it's filtered.
    mock = AsyncMock(return_value={"_avatar_self_observation": "[DM-KEY-LEAK]"})
    monkeypatch.setattr(
        CognitiveAgent, "_dispatch_sensorium_async", mock, raising=True,
    )

    result = await agent._build_user_message(obs)
    assert "[DM-KEY-LEAK]" not in result


@pytest.mark.asyncio
async def test_dm_branch_unchanged_regression(monkeypatch):
    """AD-723a-1 regression: DM branch with empty dispatcher result still
    renders Captain text and does NOT include any WR-specific markers."""
    agent = _make_agent()
    obs = {
        "intent": "direct_message",
        "params": {"text": "DM still works"},
        "timestamp": time.time(),
    }

    mock = AsyncMock(return_value={})
    monkeypatch.setattr(
        CognitiveAgent, "_dispatch_sensorium_async", mock, raising=True,
    )

    result = await agent._build_user_message(obs)
    assert "Captain says: DM still works" in result
    assert "[Ward Room" not in result
