"""BF-238: Post-budget telemetry monitoring."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.ward_room_pipeline import (
    PostBudgetTelemetry,
    WardRoomPostPipeline,
)


# --- Test 1 -----------------------------------------------------------

def test_record_invocation_increments_counters():
    telemetry = PostBudgetTelemetry()

    for _ in range(3):
        telemetry.record_invocation("scout", "thread-A")

    assert telemetry.total_invocations == 3
    # Rate is 0.0 when invocations > 0 and exhaustions == 0.
    assert telemetry.exhaustion_rate() == 0.0
    assert telemetry.exhaustion_rate(agent_type="scout") == 0.0
    assert telemetry.exhaustion_rate(agent_type="missing") is None


# --- Test 2 -----------------------------------------------------------

def test_record_exhaustion_increments_counters_and_buffer():
    telemetry = PostBudgetTelemetry(recent_suppressions_max=100)

    telemetry.record_invocation("scout", "thread-A")
    telemetry.record_exhaustion("scout", "thread-A")

    assert telemetry.total_exhaustions == 1
    assert telemetry.exhaustion_rate(agent_type="scout") == 1.0
    assert telemetry.exhaustion_rate(thread_id="thread-A") == 1.0

    recent = telemetry.recent_suppressions(limit=10)
    assert len(recent) == 1
    ts, agent_type, thread_id = recent[0]
    assert agent_type == "scout"
    assert thread_id == "thread-A"
    assert ts > 0


# --- Test 3 -----------------------------------------------------------

def test_exhaustion_rate_returns_none_when_no_samples():
    telemetry = PostBudgetTelemetry()

    assert telemetry.exhaustion_rate() is None
    assert telemetry.exhaustion_rate(agent_type="scout") is None
    assert telemetry.exhaustion_rate(thread_id="thread-A") is None


# --- Test 4 -----------------------------------------------------------

def test_exhaustion_rate_per_agent_per_thread_overall():
    telemetry = PostBudgetTelemetry()

    # Invocations: scout x4 thread-A, scout x2 thread-B, greeter x4 thread-A.
    for _ in range(4):
        telemetry.record_invocation("scout", "thread-A")
    for _ in range(2):
        telemetry.record_invocation("scout", "thread-B")
    for _ in range(4):
        telemetry.record_invocation("greeter", "thread-A")

    # Exhaustions: scout x2 thread-A, greeter x1 thread-A.
    for _ in range(2):
        telemetry.record_exhaustion("scout", "thread-A")
    telemetry.record_exhaustion("greeter", "thread-A")

    assert telemetry.exhaustion_rate() == 3 / 10
    assert telemetry.exhaustion_rate(agent_type="scout") == 2 / 6
    assert telemetry.exhaustion_rate(agent_type="greeter") == 1 / 4
    assert telemetry.exhaustion_rate(thread_id="thread-A") == 3 / 8
    assert telemetry.exhaustion_rate(thread_id="thread-B") == 0.0


# --- Test 5 -----------------------------------------------------------

def test_threshold_alert_fires_once_when_rate_exceeds_threshold(caplog):
    telemetry = PostBudgetTelemetry(
        exhaustion_alert_threshold=0.5,
        min_samples_for_alert=10,
    )

    # 10 invocations + 6 exhaustions for scout: rate 0.6 > 0.5.
    for _ in range(10):
        telemetry.record_invocation("scout", "thread-A")
    with caplog.at_level(logging.WARNING, logger="probos.ward_room_pipeline"):
        for _ in range(6):
            telemetry.record_exhaustion("scout", "thread-A")

    matching = [
        r for r in caplog.records
        if "BF-238" in r.getMessage()
        and "scout" in r.getMessage()
        and "exceeds threshold" in r.getMessage()
    ]
    assert len(matching) >= 1
    alert_count = len(matching)

    # 7th exhaustion must NOT add another WARN.
    with caplog.at_level(logging.WARNING, logger="probos.ward_room_pipeline"):
        telemetry.record_exhaustion("scout", "thread-A")

    matching_after = [
        r for r in caplog.records
        if "BF-238" in r.getMessage()
        and "scout" in r.getMessage()
        and "exceeds threshold" in r.getMessage()
    ]
    assert len(matching_after) == alert_count


# --- Test 6 -----------------------------------------------------------

def test_threshold_alert_suppressed_below_min_samples(caplog):
    telemetry = PostBudgetTelemetry(
        exhaustion_alert_threshold=0.5,
        min_samples_for_alert=10,
    )

    with caplog.at_level(logging.WARNING, logger="probos.ward_room_pipeline"):
        # 5 invocations + 5 exhaustions for scout: rate 1.0 but below gate.
        for _ in range(5):
            telemetry.record_invocation("scout", "thread-A")
        for _ in range(5):
            telemetry.record_exhaustion("scout", "thread-A")

    matching = [
        r for r in caplog.records
        if "BF-238" in r.getMessage() and "scout" in r.getMessage()
    ]
    assert matching == []


# --- Test 7 -----------------------------------------------------------

def test_recent_suppressions_bound_respected():
    telemetry = PostBudgetTelemetry(recent_suppressions_max=3)

    for i in range(5):
        thread_id = f"thread-{i}"
        telemetry.record_invocation("scout", thread_id)
        telemetry.record_exhaustion("scout", thread_id)

    recent = telemetry.recent_suppressions(limit=10)
    assert len(recent) == 3
    thread_ids = [t for (_, _, t) in recent]
    assert thread_ids == ["thread-2", "thread-3", "thread-4"]
    assert telemetry.recent_suppressions(limit=0) == ()


# --- Test 8 -----------------------------------------------------------

def _make_router():
    router = MagicMock()
    router.record_agent_response = MagicMock()
    router.record_round_post = MagicMock()
    router.update_cooldown = MagicMock()
    router.extract_recreation_commands = AsyncMock(side_effect=lambda agent, text, cs: text)
    return router


def _make_proactive_loop_spending_budget():
    async def _fake_extract(agent, text, *, post_budget=None):
        if post_budget is not None:
            post_budget.spent = True
        return text, []

    loop = MagicMock()
    loop.extract_and_execute_actions = AsyncMock(side_effect=_fake_extract)
    loop.is_similar_to_recent_posts = AsyncMock(return_value=False)
    return loop


@pytest.mark.asyncio
async def test_pipeline_records_invocation_and_exhaustion():
    ward_room = AsyncMock()
    router = _make_router()
    proactive_loop = _make_proactive_loop_spending_budget()
    telemetry = PostBudgetTelemetry()

    pipeline = WardRoomPostPipeline(
        ward_room=ward_room,
        ward_room_router=router,
        proactive_loop=proactive_loop,
        trust_network=None,
        callsign_registry=None,
        config=MagicMock(),
        runtime=MagicMock(event_log=AsyncMock()),
        post_budget_telemetry=telemetry,
    )

    agent = MagicMock()
    agent.id = "a-1"
    agent.agent_type = "scout"

    await pipeline.process_and_post(
        agent=agent,
        response_text="hello",
        thread_id="thread-A",
        event_type="ward_room_thread_created",
    )

    assert telemetry.total_invocations == 1
    assert telemetry.total_exhaustions == 1
    assert telemetry.exhaustion_rate(agent_type="scout") == 1.0

    recent = telemetry.recent_suppressions()
    assert len(recent) == 1
    _, agent_type, thread_id = recent[0]
    assert agent_type == "scout"
    assert thread_id == "thread-A"
