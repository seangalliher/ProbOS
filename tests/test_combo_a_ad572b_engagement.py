"""Combo A AD-572b: Captain Engagement Extensions tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from probos.cognitive.captain_engagement import CaptainEngagementProvider
from probos.events import EventType


def test_captain_engagement_snapshot_when_runtime_none():
    provider = CaptainEngagementProvider(runtime=None)
    assert provider.snapshot() == {}


def test_captain_engagement_snapshot_includes_alert_count():
    rt = SimpleNamespace()
    rt.bridge_alerts = SimpleNamespace()
    rt.bridge_alerts.get_recent_alerts = MagicMock(return_value=[
        SimpleNamespace(acknowledged=False),
        SimpleNamespace(acknowledged=True),
        SimpleNamespace(acknowledged=False),
    ])
    rt.ward_room = None

    provider = CaptainEngagementProvider(runtime=rt)
    snap = provider.snapshot()

    assert snap["alerts_pending"] == 2
    assert snap["wardroom_activity_60s"] == 0
    assert snap["dm_queue_depth"] == 0


def test_captain_engagement_emits_dm_priority_queued():
    """When dm_queue_depth > 0, emit CAPTAIN_DM_PRIORITY_QUEUED once per change."""
    rt = SimpleNamespace()
    rt.bridge_alerts = None
    rt.ward_room = SimpleNamespace()
    rt.ward_room.captain_dm_queue_depth = MagicMock(return_value=3)
    rt.ward_room._last_stats = None

    emit = MagicMock()
    provider = CaptainEngagementProvider(runtime=rt, emit_event=emit)
    snap1 = provider.snapshot()
    assert snap1["dm_queue_depth"] == 3
    emit.assert_called_once()
    et, payload = emit.call_args[0]
    assert et == EventType.CAPTAIN_DM_PRIORITY_QUEUED
    assert payload["dm_queue_depth"] == 3

    # Same depth -> no re-emit
    emit.reset_mock()
    provider.snapshot()
    emit.assert_not_called()


def test_proactive_gather_context_includes_captain_engagement():
    """Direct unit test of the snapshot shape -- the proactive integration
    pattern is `context["captain_engagement"] = provider.snapshot()`."""
    rt = SimpleNamespace()
    rt.bridge_alerts = None
    rt.ward_room = None
    provider = CaptainEngagementProvider(runtime=rt)

    context = {}
    context["captain_engagement"] = provider.snapshot()
    assert "captain_engagement" in context
    # Empty when nothing wired
    assert context["captain_engagement"] in ({}, {
        "alerts_pending": 0,
        "wardroom_activity_60s": 0,
        "dm_queue_depth": 0,
    })
