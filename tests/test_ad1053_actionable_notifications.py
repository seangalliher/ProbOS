"""AD-1053: actionable accept->dispatch affordance on the notification surface.

OSS plumbing. A notification can carry an optional producer-authored
``suggested_action``; ``POST /api/notifications/{id}/accept`` dispatches the
carried intent into the mesh then acknowledges the notification. Additive +
default ``None`` -> byte-identical when unused.

BF-287: real fixtures only. Real ``NotificationQueue``, a real ``IntentBus``
(``IntentBus(SignalManager())``) with a capturing subscriber, and the real
``IntentMessage``. No ``MagicMock`` at the substrate boundary.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.notifications import AgentNotification, NotificationQueue
from probos.routers.deps import get_runtime
from probos.routers.system import router
from probos.types import IntentMessage, IntentResult


def _client_for(runtime: Any) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def _capturing_bus(captured: list[IntentMessage], agent_id: str = "a1") -> IntentBus:
    """A real IntentBus with a capturing subscriber under ``agent_id``.

    A targeted intent (``target_agent_id`` set) delegates to ``send()``, which
    invokes the handler registered under that id (intent.py).
    """
    bus = IntentBus(SignalManager())

    async def _capture(intent: IntentMessage) -> IntentResult:
        captured.append(intent)
        return IntentResult(
            intent_id=intent.id, agent_id=agent_id, success=True, confidence=1.0
        )

    bus.subscribe(agent_id, _capture, intent_names=["direct_message"])
    return bus


# --- 1. field default + serialization -------------------------------------

def test_suggested_action_defaults_none_and_serializes() -> None:
    n = AgentNotification(title="hi")

    assert n.suggested_action is None
    assert n.to_dict()["suggested_action"] is None


# --- 2. notify round-trips the field --------------------------------------

def test_notify_round_trips_suggested_action() -> None:
    nq = NotificationQueue()
    action = {
        "label": "Do it",
        "intent": "direct_message",
        "params": {"text": "x"},
        "target_agent_id": "a1",
    }

    n = nq.notify(
        agent_id="p",
        agent_type="producer",
        department="ops",
        title="t",
        notification_type="action_required",
        suggested_action=action,
    )

    assert nq.get(n.id).suggested_action == action
    assert nq.snapshot()[0]["suggested_action"] == action


# --- 3. get(id) hit + miss ------------------------------------------------

def test_get_returns_notification_and_none_for_missing() -> None:
    nq = NotificationQueue()
    n = nq.notify(agent_id="p", agent_type="producer", department="ops", title="t")

    assert nq.get(n.id) is n
    assert nq.get("missing") is None


# --- 4. accept happy path: dispatch the carried intent + ack --------------

def test_accept_dispatches_carried_intent_and_acks() -> None:
    nq = NotificationQueue()
    captured: list[IntentMessage] = []
    bus = _capturing_bus(captured)
    n = nq.notify(
        agent_id="p",
        agent_type="producer",
        department="ops",
        title="t",
        notification_type="action_required",
        suggested_action={
            "label": "Do it",
            "intent": "direct_message",
            "params": {"text": "x"},
            "target_agent_id": "a1",
        },
    )
    runtime = SimpleNamespace(notification_queue=nq, intent_bus=bus)
    client = _client_for(runtime)

    resp = client.post(f"/api/notifications/{n.id}/accept")

    assert resp.status_code == 200
    assert resp.json() == {
        "dispatched": True,
        "intent": "direct_message",
        "responders": 1,
    }
    # The producer-authored intent reached the real bus, verbatim.
    assert len(captured) == 1
    assert captured[0].intent == "direct_message"
    assert captured[0].target_agent_id == "a1"
    assert captured[0].params == {"text": "x"}
    # The notification is now acknowledged (resolved -> recedes).
    assert nq.get(n.id).acknowledged is True


# --- 5. accept with no suggested_action: ack-only, no broadcast -----------

def test_accept_no_suggested_action_acks_only() -> None:
    nq = NotificationQueue()
    captured: list[IntentMessage] = []
    bus = _capturing_bus(captured)
    n = nq.notify(agent_id="p", agent_type="producer", department="ops", title="t")
    runtime = SimpleNamespace(notification_queue=nq, intent_bus=bus)
    client = _client_for(runtime)

    resp = client.post(f"/api/notifications/{n.id}/accept")

    assert resp.status_code == 200
    assert resp.json() == {"dispatched": False, "reason": "no_action"}
    assert captured == []
    # Accept with nothing to dispatch still acknowledges the notification.
    assert nq.get(n.id).acknowledged is True


# --- 6. accept on a missing id --------------------------------------------

def test_accept_not_found_returns_reason() -> None:
    nq = NotificationQueue()
    runtime = SimpleNamespace(notification_queue=nq, intent_bus=_capturing_bus([]))
    client = _client_for(runtime)

    resp = client.post("/api/notifications/does-not-exist/accept")

    assert resp.status_code == 200
    assert resp.json() == {"dispatched": False, "reason": "not_found"}


# --- 7. accept with no intent_bus: honest-degrade, no raise ---------------

def test_accept_no_bus_honest_degrade() -> None:
    nq = NotificationQueue()
    n = nq.notify(
        agent_id="p",
        agent_type="producer",
        department="ops",
        title="t",
        notification_type="action_required",
        suggested_action={
            "label": "Do it",
            "intent": "direct_message",
            "params": {"text": "x"},
            "target_agent_id": "a1",
        },
    )
    # Runtime has a notification_queue but NO intent_bus attribute.
    runtime = SimpleNamespace(notification_queue=nq)
    client = _client_for(runtime)

    resp = client.post(f"/api/notifications/{n.id}/accept")

    assert resp.status_code == 200
    assert resp.json() == {"dispatched": False, "reason": "no_bus"}


# --- 8. default-None serializes byte-identical to pre-AD-1053 -------------

def test_default_none_serializes_byte_identical() -> None:
    nq = NotificationQueue()
    n = nq.notify(
        agent_id="p",
        agent_type="producer",
        department="ops",
        title="t",
        detail="d",
        notification_type="info",
        action_url="task-1",
    )

    d = n.to_dict()

    # Every pre-AD-1053 key is unchanged; the one added key is the default None.
    assert d == {
        "id": n.id,
        "agent_id": "p",
        "agent_type": "producer",
        "department": "ops",
        "notification_type": "info",
        "title": "t",
        "detail": "d",
        "action_url": "task-1",
        "suggested_action": None,
        "created_at": n.created_at,
        "acknowledged": False,
    }
    # The existing ack flow is unchanged.
    assert nq.acknowledge(n.id) is True
    assert nq.get(n.id).acknowledged is True
