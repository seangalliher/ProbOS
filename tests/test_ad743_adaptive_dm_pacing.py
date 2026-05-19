"""AD-743 — Adaptive conversational pacing in 1:1 DMs.

Tests cover bracket-marker extraction/strip, scheduler lifecycle,
single-flight + Captain-interrupt cancellation, two-budget enforcement,
pipeline-step wiring, default-off behavior preservation, and AD-731
source-scan invariant.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.dm.pacing_scheduler import ConversationPacingScheduler
from probos.cognitive.dm.reply_pipeline import DmReplyPipeline
from probos.cognitive.dm_sanity_gate import DmSanityGate, DmSanityGateConfig
from probos.config import SystemConfig
from probos.types import IntentMessage


# ── Test 1: regex extract well-formed ──────────────────────────


def test_followup_regex_extracts_well_formed() -> None:
    gate = DmSanityGate(DmSanityGateConfig())
    result = gate.extract_followup("Hello [FOLLOW_UP 5 mid_thought] there")
    assert result == (5, "mid_thought")


# ── Test 2: regex rejects invalid delay/reason ─────────────────


def test_followup_regex_rejects_invalid_delay() -> None:
    gate = DmSanityGate(DmSanityGateConfig())
    # Delay 0 → out of range (1..300)
    assert gate.extract_followup("[FOLLOW_UP 0 reason]") is None
    # Delay 9999 → > 300 (also matches 3-digit cap on regex but 999 > 300)
    assert gate.extract_followup("[FOLLOW_UP 9999 reason]") is None
    # Non-numeric delay
    assert gate.extract_followup("[FOLLOW_UP abc reason]") is None
    # Empty reason → regex doesn't match
    assert gate.extract_followup("[FOLLOW_UP 5 ]") is None


# ── Test 3: strip removes well-formed + malformed ──────────────


def test_followup_strip_removes_both_forms() -> None:
    gate = DmSanityGate(DmSanityGateConfig())
    text = "hi [FOLLOW_UP 5 ok] mid [FOLLOW_UP broken] end"
    cleaned = gate.strip_followup(text)
    assert "[FOLLOW_UP" not in cleaned
    assert "hi" in cleaned and "end" in cleaned


# ── Test 4: scheduler delivers after delay ─────────────────────


class _FakeBus:
    def __init__(self) -> None:
        self.sent: list[IntentMessage] = []

    async def send(self, intent: IntentMessage) -> None:
        self.sent.append(intent)


class _FakeRuntime:
    def __init__(self, cfg: SystemConfig) -> None:
        self.config = cfg
        self.intent_bus = _FakeBus()


def _make_runtime(pacing_enabled: bool = True, **avatar_overrides: Any) -> _FakeRuntime:
    cfg = SystemConfig()
    cfg.avatars.pacing_enabled = pacing_enabled
    for k, v in avatar_overrides.items():
        setattr(cfg.avatars, k, v)
    return _FakeRuntime(cfg)


@pytest.mark.asyncio
async def test_scheduler_schedules_after_delay() -> None:
    runtime = _make_runtime()
    sched = ConversationPacingScheduler(runtime)  # type: ignore[arg-type]
    await sched.start()
    try:
        ok = sched.schedule_followup("e1", 1, "mid_thought")
        assert ok is True
        # Wait for delivery — generous timeout for CI.
        for _ in range(30):
            if runtime.intent_bus.sent:
                break
            await asyncio.sleep(0.1)
        assert len(runtime.intent_bus.sent) == 1
        intent = runtime.intent_bus.sent[0]
        assert intent.intent == "direct_message"
        assert intent.target_agent_id == "e1"
        assert "[CONVERSATION_FOLLOW_UP" in intent.params["text"]
        assert intent.params["from"] == "pacing_scheduler"
        assert intent.params["reason"] == "mid_thought"
    finally:
        await sched.stop()


# ── Test 5: Captain interruption cancels pending follow-up ─────


@pytest.mark.asyncio
async def test_scheduler_cancels_on_captain_interruption() -> None:
    runtime = _make_runtime()
    sched = ConversationPacingScheduler(runtime)  # type: ignore[arg-type]
    await sched.start()
    try:
        sched.schedule_followup("e1", 2, "mid_thought")
        await asyncio.sleep(0.1)  # let the task start its sleep
        cancelled = sched.cancel_for_conversation("e1")
        assert cancelled is True
        await asyncio.sleep(0.2)
        assert runtime.intent_bus.sent == []
    finally:
        await sched.stop()


# ── Test 6: per-conversation budget ────────────────────────────


@pytest.mark.asyncio
async def test_scheduler_per_conversation_budget() -> None:
    runtime = _make_runtime(
        pacing_max_followups_per_active_conversation=2,
        pacing_max_followups_per_hour_per_agent=60,
        # Use a large delay so the tasks don't fire during the test.
        pacing_min_delay_seconds=60,
        pacing_max_delay_seconds=900,
    )
    sched = ConversationPacingScheduler(runtime)  # type: ignore[arg-type]
    await sched.start()
    try:
        assert sched.schedule_followup("e1", 600, "r1") is True
        assert sched.schedule_followup("e1", 600, "r2") is True
        # Third within active window → refused.
        assert sched.schedule_followup("e1", 600, "r3") is False
    finally:
        await sched.stop()


# ── Test 7: per-agent hourly ceiling ───────────────────────────


@pytest.mark.asyncio
async def test_scheduler_hourly_budget_ceiling() -> None:
    runtime = _make_runtime(
        pacing_max_followups_per_active_conversation=10,
        pacing_max_followups_per_hour_per_agent=3,
        pacing_min_delay_seconds=60,
        pacing_max_delay_seconds=900,
    )
    sched = ConversationPacingScheduler(runtime)  # type: ignore[arg-type]
    await sched.start()
    try:
        for i in range(3):
            assert sched.schedule_followup(
                "e1", 600, f"r{i}", conversation_id=f"c{i}"
            ) is True
        # Fourth → hourly ceiling.
        assert sched.schedule_followup(
            "e1", 600, "r4", conversation_id="cX"
        ) is False
    finally:
        await sched.stop()


# ── Test 8: budgets are NOT additive (per-conv caps in-conv) ───


@pytest.mark.asyncio
async def test_scheduler_budgets_not_additive() -> None:
    runtime = _make_runtime(
        pacing_max_followups_per_active_conversation=2,
        pacing_max_followups_per_hour_per_agent=10,
        pacing_min_delay_seconds=60,
        pacing_max_delay_seconds=900,
    )
    sched = ConversationPacingScheduler(runtime)  # type: ignore[arg-type]
    await sched.start()
    try:
        assert sched.schedule_followup(
            "e1", 600, "r1", conversation_id="c1"
        ) is True
        assert sched.schedule_followup(
            "e1", 600, "r2", conversation_id="c1"
        ) is True
        assert sched.schedule_followup(
            "e1", 600, "r3", conversation_id="c1"
        ) is False
        # Different conversation succeeds (hourly room remains).
        assert sched.schedule_followup(
            "e1", 600, "r4", conversation_id="c2"
        ) is True
    finally:
        await sched.stop()


# ── Test 9: default-off → no scheduler wired (config gate) ─────


def test_pacing_disabled_default_no_scheduler() -> None:
    cfg = SystemConfig()
    # Default value.
    assert cfg.avatars.pacing_enabled is False


# ── Test 10: pipeline tuple includes step_4d at correct slot ───


def test_step_4d_in_pipeline_order() -> None:
    # Read the pipeline module source and assert the step ordering.
    import probos.cognitive.dm.reply_pipeline as rp

    src = Path(rp.__file__).read_text(encoding="utf-8")
    # The tuple definition keeps step_4d between step_4c and step_4b.
    idx_4c = src.find("step_4c_image_gen_parse,")
    idx_4d = src.find("step_4d_follow_up_parse,")
    idx_4b = src.find("step_4b_dm_outbound_parse,")
    assert 0 < idx_4c < idx_4d < idx_4b
    # And the method itself is defined on the class.
    assert hasattr(DmReplyPipeline, "step_4d_follow_up_parse")


# ── Test 11: synthesized followup carries from-marker ──────────


@pytest.mark.asyncio
async def test_synthesized_followup_carries_from_marker() -> None:
    runtime = _make_runtime()
    sched = ConversationPacingScheduler(runtime)  # type: ignore[arg-type]
    await sched.start()
    try:
        sched.schedule_followup("e1", 1, "mid_thought")
        for _ in range(30):
            if runtime.intent_bus.sent:
                break
            await asyncio.sleep(0.1)
        assert len(runtime.intent_bus.sent) == 1
        intent = runtime.intent_bus.sent[0]
        # Anchor distinguishability for AD-541b (synthesized vs Captain-authored).
        assert intent.params["from"] == "pacing_scheduler"
        assert intent.params["conversation_id"] == "default"
    finally:
        await sched.stop()


# ── Test 12: AD-731 invariant — no inline base64 in pacing module ──


def test_ad731_invariant_no_inline_base64_in_pacing_module() -> None:
    import probos.cognitive.dm.pacing_scheduler as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    # Detect forbidden literals that would indicate inline-blob shape.
    forbidden = ["b64encode", "base64.b64", "attachment_ref"]
    for needle in forbidden:
        assert needle not in src, (
            f"AD-731 invariant: pacing_scheduler.py must not contain {needle!r}"
        )
