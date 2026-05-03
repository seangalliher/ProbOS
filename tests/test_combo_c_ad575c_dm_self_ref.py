"""Combo C AD-575c: DM forwarding self-reference flag."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock


def _make_runtime(unread_dms: list[dict]) -> SimpleNamespace:
    """Build a minimal runtime that drives _check_unread_dms."""
    ward_room = SimpleNamespace()
    ward_room.get_unread_dms = AsyncMock(return_value=unread_dms)

    router = SimpleNamespace()
    router.route_event = AsyncMock()

    rt = SimpleNamespace()
    rt.ward_room = ward_room
    rt.ward_room_router = router
    # Minimal config shape
    rt.config = SimpleNamespace(
        ward_room=SimpleNamespace(
            dm_exchange_limit=6,
            dm_response_window_s=60.0,
            dm_response_max_total=99,
            dm_response_max_per_pair=99,
        ),
    )
    return rt


def _make_loop():
    from probos.proactive import ProactiveCognitiveLoop
    loop = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
    loop._notified_dm_threads = set()
    loop._notified_dm_threads_reset = 0.0
    loop._dm_response_counts = {}
    loop._dm_pair_counts = {}
    return loop


def _make_agent(callsign: str = "TestAgent") -> SimpleNamespace:
    return SimpleNamespace(
        id="agent-1",
        agent_type="science_officer",
        callsign=callsign,
    )


def test_self_reference_flag_set_when_callsign_in_body():
    rt = _make_runtime([{
        "thread_id": "t-1",
        "channel_id": "ch-dm",
        "author_id": "captain",
        "author_callsign": "Captain",
        "title": "fwd",
        "body": "Captain said about you: @Spock please review",
    }])
    rt._runtime = rt  # self-ref for proactive loop access pattern

    loop = _make_loop()
    loop._runtime = rt
    agent = _make_agent("Spock")

    asyncio.run(loop._check_unread_dms(agent, rt))

    assert rt.ward_room_router.route_event.await_count == 1
    _, event_data = rt.ward_room_router.route_event.call_args[0]
    assert event_data["self_referenced"] is True


def test_self_reference_flag_absent_when_no_mention():
    rt = _make_runtime([{
        "thread_id": "t-2",
        "channel_id": "ch-dm",
        "author_id": "captain",
        "author_callsign": "Captain",
        "title": "fwd",
        "body": "Captain said: meeting at 1500",
    }])

    loop = _make_loop()
    loop._runtime = rt
    agent = _make_agent("Spock")

    asyncio.run(loop._check_unread_dms(agent, rt))

    _, event_data = rt.ward_room_router.route_event.call_args[0]
    assert "self_referenced" not in event_data


def test_self_reference_match_is_case_insensitive():
    rt = _make_runtime([{
        "thread_id": "t-3",
        "channel_id": "ch-dm",
        "author_id": "captain",
        "author_callsign": "Captain",
        "title": "fwd",
        "body": "Captain mentioned @SPOCK in the briefing",
    }])

    loop = _make_loop()
    loop._runtime = rt
    agent = _make_agent("Spock")

    asyncio.run(loop._check_unread_dms(agent, rt))

    _, event_data = rt.ward_room_router.route_event.call_args[0]
    assert event_data["self_referenced"] is True
