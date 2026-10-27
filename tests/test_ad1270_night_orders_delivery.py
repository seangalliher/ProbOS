"""AD-1270 (#1324): a Night Orders escalation pages the Captain through the real
bridge-alert path, and never costs the event its dispatch (M2).

Hosts are the BF-708 shape: the unmodified runtime emission methods on a
minimal object, with a real NightOrdersManager, BridgeAlertService and
WardRoomRouter (its Ward Room is an AsyncMock).
"""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.bridge_alerts import AlertSeverity, BridgeAlertService
from probos.config import TRUST_FLOOR_CONN, SystemConfig
from probos.events import EventType
from probos.runtime import ProbOSRuntime
from probos.ward_room_router import WardRoomRouter
from probos.watch_rotation import NightOrdersManager

_LOGGER = "probos.runtime"
_F = TRUST_FLOOR_CONN
_REAL = object()


class _Host:
    add_event_listener = ProbOSRuntime.add_event_listener
    emit_event = ProbOSRuntime.emit_event
    _emit_event = ProbOSRuntime._emit_event
    _emit_event_local = ProbOSRuntime._emit_event_local
    _check_night_order_escalation = ProbOSRuntime._check_night_order_escalation

    def __init__(self, *, template: str = "maintenance", bridge_alerts: Any = _REAL, router: Any = _REAL) -> None:
        self._event_listeners: list[Any] = []
        self._live_event_listeners: list[Any] = []
        self._event_listener_tasks: set[asyncio.Task[Any]] = set()
        self._nats_publish_tasks: set[asyncio.Task[Any]] = set()
        self._nats_events_wired = False
        self.nats_bus = None
        self.offers: list[dict[str, Any]] = []
        self.durable_events = SimpleNamespace(offer=self.offers.append)
        self.conn_manager = MagicMock()
        self._night_orders_mgr = NightOrdersManager()
        self._night_orders_mgr.set_night_orders([], template=template)
        self.bridge_alerts = BridgeAlertService() if bridge_alerts is _REAL else bridge_alerts
        self.wr = AsyncMock()
        self.wr.get_channel_by_type.return_value = SimpleNamespace(id="ch-ship")
        self.notify = MagicMock()
        self.ward_room_router = (
            WardRoomRouter(
                ward_room=self.wr, registry=MagicMock(), intent_bus=AsyncMock(),
                trust_network=MagicMock(), ontology=None, callsign_registry=MagicMock(),
                episodic_memory=None, event_emitter=MagicMock(), event_log=AsyncMock(),
                config=SystemConfig(), notify_fn=self.notify,
            )
            if router is _REAL else router
        )
        self.events: list[dict[str, Any]] = []
        self.add_event_listener(self.events.append)

    async def settle(self) -> None:
        pending = list(self._event_listener_tasks)
        if pending:
            await asyncio.gather(*pending)


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records]


@pytest.mark.asyncio
async def test_a_build_failure_under_night_orders_pages_the_captain_and_is_still_dispatched() -> None:
    host = _Host()
    host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b9", "message": "Build failed: boom", "error": "boom"})
    assert len(host._event_listener_tasks) == 1  # the delivery is held, not fire-and-forget
    await host.settle()
    assert [e["type"] for e in host.events] == ["build_failure"]
    assert [e["type"] for e in host.offers] == ["build_failure"]
    host.conn_manager.check_escalation.assert_called_once()
    host.wr.create_thread.assert_awaited_once()
    kwargs = host.wr.create_thread.await_args.kwargs
    assert kwargs["channel_id"] == "ch-ship"
    assert kwargs["title"] == "[ALERT] Night Orders escalation: build_failure"
    assert "Build failed: boom" in kwargs["body"]
    host.notify.assert_called_once()
    assert host.notify.call_args.kwargs["notification_type"] == "action_required"


@pytest.mark.asyncio
async def test_a_trust_crossing_pages_once() -> None:
    host = _Host()
    host.emit_event(EventType.TRUST_UPDATE, {"agent_id": "a1", "old_score": _F + 0.1, "new_score": _F - 0.1})
    await host.settle()
    host.emit_event(EventType.TRUST_UPDATE, {"agent_id": "a1", "old_score": _F - 0.1, "new_score": _F - 0.2})
    await host.settle()
    assert host.conn_manager.check_escalation.call_count == 1  # staying below the floor is no crossing (D3)
    # A second crossing inside the 300 s cooldown matches; the service declines it (R6, AD-580).
    host.emit_event(EventType.TRUST_UPDATE, {"agent_id": "a1", "old_score": _F + 0.05, "new_score": _F - 0.05})
    assert host.conn_manager.check_escalation.call_count == 2
    assert [t for t in host._event_listener_tasks if not t.done()] == []  # a declined alert is never delivered
    await host.settle()
    assert len(host.events) == 3 and len(host.offers) == 3
    host.wr.create_thread.assert_awaited_once()
    assert host.wr.create_thread.await_args.kwargs["title"] == "[ALERT] Night Orders escalation: trust_drop"


@pytest.mark.asyncio
async def test_a_refused_build_or_an_unlisted_trigger_pages_nobody() -> None:
    refused = _Host()
    refused.emit_event(EventType.BUILD_FAILURE, {"build_id": "b1", "not_executed": True})
    unlisted = _Host(template="build")  # security_alert and trust_drop only
    unlisted.emit_event(EventType.BUILD_FAILURE, {"build_id": "b2", "message": "m"})
    for host in (refused, unlisted):
        await host.settle()
        assert len(host.events) == 1 and len(host.offers) == 1
        host.conn_manager.check_escalation.assert_not_called()
        host.wr.create_thread.assert_not_awaited()


@pytest.mark.parametrize("raiser", ["alerts", "orders"])  # AD-1270 A2: a raising conn log no longer stops the page (D4b)
@pytest.mark.asyncio
async def test_an_escalation_that_raises_never_costs_the_event_its_dispatch(
    raiser: str, caplog: pytest.LogCaptureFixture,
) -> None:
    alerts = MagicMock(spec=BridgeAlertService)
    alerts.check_night_orders_escalation.side_effect = RuntimeError("boom")
    host = _Host(bridge_alerts=alerts if raiser == "alerts" else _REAL)
    if raiser == "orders":
        host._night_orders_mgr = MagicMock()
        host._night_orders_mgr.active = True
        host._night_orders_mgr.check_escalation.side_effect = RuntimeError("boom")
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b3", "message": "m"})
    await host.settle()
    assert len(host.events) == 1
    assert len(host.offers) == 1
    assert any("Night Orders escalation failed for event build_failure" in m for m in _messages(caplog))
    host.wr.create_thread.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_conn_log_that_raises_still_pages_the_captain(caplog: pytest.LogCaptureFixture) -> None:
    """AD-1270 A2 (review A F1): ``ConnManager.check_escalation`` is bookkeeping; its failure is logged and the page goes."""
    host = _Host()
    host.conn_manager.check_escalation.side_effect = RuntimeError("boom")
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b5", "message": "m"})
    await host.settle()
    assert len(host.events) == 1 and len(host.offers) == 1
    host.wr.create_thread.assert_awaited_once()
    messages = _messages(caplog)
    assert any("ConnManager escalation failed for build_failure" in m for m in messages)
    assert not any("Night Orders escalation failed" in m for m in messages)


def test_outside_an_event_loop_nothing_is_paged_and_the_cooldown_is_not_spent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    host = _Host()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b4", "message": "m"})
    assert len(host.events) == 1 and len(host.offers) == 1
    assert host._event_listener_tasks == set()
    assert any("Night Orders escalation failed for event build_failure" in m for m in _messages(caplog))
    assert host.bridge_alerts.check_night_orders_escalation("build_failure", {"build_id": "b4"}) is not None


@pytest.mark.parametrize("missing", ["bridge_alerts", "router"])
def test_without_a_bridge_alert_path_the_event_is_dispatched_and_the_gap_is_logged(
    missing: str, caplog: pytest.LogCaptureFixture,
) -> None:
    host = _Host(**{missing: None})
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        host.emit_event(EventType.BUILD_FAILURE, {"build_id": "b5", "message": "m"})
    assert len(host.events) == 1 and len(host.offers) == 1
    host.conn_manager.check_escalation.assert_called_once()
    assert any("has no bridge-alert path; the Captain is not paged" in m for m in _messages(caplog))


def test_the_alert_is_deduplicated_per_subject_and_suppressible() -> None:
    svc = BridgeAlertService()
    first = svc.check_night_orders_escalation("build_failure", {"build_id": "b1", "message": "x" * 900})
    assert first is not None
    assert first.severity is AlertSeverity.ALERT
    assert first.source == "night_orders"
    assert first.alert_type == "night_orders_build_failure"
    assert first.dedup_key == "night_orders:build_failure:b1"
    assert first.detail == "Night Orders escalation (build_failure): " + "x" * 500
    assert first.related_agent_id is None
    assert svc.check_night_orders_escalation("build_failure", {"build_id": "b1"}) is None
    assert svc.check_night_orders_escalation("build_failure", {"build_id": "b2"}) is not None
    svc.mute_alert("night_orders:build_failure:b3")
    assert svc.check_night_orders_escalation("build_failure", {"build_id": "b3"}) is None


def test_a_trust_drop_alert_names_the_agent_and_its_scores() -> None:
    svc = BridgeAlertService()
    a = svc.check_night_orders_escalation("trust_drop", {"agent_id": "a1", "old_score": 0.7, "new_score": 0.5})
    assert a is not None
    assert a.related_agent_id == "a1"
    assert a.dedup_key == "night_orders:trust_drop:a1"
    assert "(0.70 \u2192 0.50)" in a.detail
    b = svc.check_night_orders_escalation("build_failure", {})
    assert b is not None and b.dedup_key == "night_orders:build_failure"
