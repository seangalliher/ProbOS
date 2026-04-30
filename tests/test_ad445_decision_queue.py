from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.events import EventType
from probos.governance.decision_queue import DecisionQueue, DecisionState, QueuedDecision
from probos.routers.deps import get_runtime
from probos.routers.system import router


class _FakeRuntime:
    def __init__(self, decision_queue: DecisionQueue | None = None) -> None:
        if decision_queue is not None:
            self._decision_queue = decision_queue


def _client_for(runtime: _FakeRuntime) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def test_decision_state_enum() -> None:
    assert DecisionState.PENDING.value == "pending"
    assert DecisionState.APPROVED.value == "approved"
    assert DecisionState.REJECTED.value == "rejected"
    assert DecisionState.DEFERRED.value == "deferred"
    assert DecisionState.EXPIRED.value == "expired"


def test_queued_decision_creation() -> None:
    decision = QueuedDecision(
        id="d1",
        category="remediation",
        priority=7,
        summary="Approve fix",
        detail="A proposed remediation requires approval.",
        source_agent_id="agent-1",
        metadata={"proposal": "p1"},
    )

    assert decision.id == "d1"
    assert decision.category == "remediation"
    assert decision.priority == 7
    assert decision.state is DecisionState.PENDING
    assert decision.source_agent_id == "agent-1"
    assert decision.metadata == {"proposal": "p1"}


def test_queued_decision_expiry() -> None:
    decision = QueuedDecision(
        id="d1",
        category="governance",
        priority=1,
        summary="Expired",
        detail="Expired decision.",
        ttl_seconds=0,
    )

    assert decision.is_expired is True


def test_enqueue_and_next_pending() -> None:
    queue = DecisionQueue()
    low = QueuedDecision("low", "operational", 1, "Low", "Low priority")
    high = QueuedDecision("high", "operational", 9, "High", "High priority")

    assert queue.enqueue(low) is True
    assert queue.enqueue(high) is True

    assert queue.next_pending() is high


def test_enqueue_full_queue() -> None:
    queue = DecisionQueue(max_size=1)
    first = QueuedDecision("first", "operational", 1, "First", "First decision")
    second = QueuedDecision("second", "operational", 1, "Second", "Second decision")

    assert queue.enqueue(first) is True
    assert queue.enqueue(second) is False


def test_pause_blocks_next_pending() -> None:
    queue = DecisionQueue()
    decision = QueuedDecision("d1", "operational", 1, "Pending", "Pending decision")
    queue.enqueue(decision)

    queue.pause("maintenance")

    assert queue.paused is True
    assert queue.pause_reason == "maintenance"
    assert queue.next_pending() is None


def test_resume_unblocks() -> None:
    queue = DecisionQueue()
    decision = QueuedDecision("d1", "operational", 1, "Pending", "Pending decision")
    queue.enqueue(decision)
    queue.pause("maintenance")

    queue.resume()

    assert queue.paused is False
    assert queue.next_pending() is decision


def test_resolve_decision() -> None:
    queue = DecisionQueue()
    decision = QueuedDecision("d1", "governance", 3, "Resolve", "Resolve decision")
    queue.enqueue(decision)

    assert queue.resolve("d1", DecisionState.APPROVED) is True

    assert decision.state is DecisionState.APPROVED
    assert decision.resolved_at is not None
    assert queue.get_summary()["resolved_total"] == 1


def test_expire_stale_decisions() -> None:
    queue = DecisionQueue()
    decision = QueuedDecision(
        "d1",
        "governance",
        3,
        "Expire",
        "Expire decision",
        ttl_seconds=0,
    )
    queue.enqueue(decision)

    assert queue.get_all() == []

    assert decision.state is DecisionState.EXPIRED
    assert decision.resolved_at is not None


def test_decision_queue_paused_event() -> None:
    emitted: list[tuple[Any, dict[str, Any]]] = []
    queue = DecisionQueue(
        emit_fn=lambda event_type, payload: emitted.append((event_type, payload)),
    )
    queue.enqueue(QueuedDecision("d1", "governance", 3, "Pause", "Pause decision"))

    queue.pause("incident")

    assert emitted[0][0] is EventType.DECISION_QUEUE_PAUSED
    assert emitted[0][1]["reason"] == "incident"
    assert emitted[0][1]["pending_count"] == 1


def test_decision_queue_event_type_exists() -> None:
    assert EventType.DECISION_QUEUE_PAUSED.value == "decision_queue_paused"


def test_get_decision_queue_enabled_returns_summary_and_decisions() -> None:
    queue = DecisionQueue()
    queue.enqueue(QueuedDecision("d1", "governance", 3, "Review", "Review decision"))
    client = _client_for(_FakeRuntime(queue))

    response = client.get("/api/decision-queue")
    payload = response.json()

    assert response.status_code == 200
    assert payload["paused"] is False
    assert payload["pending"] == 1
    assert payload["decisions"][0]["id"] == "d1"


def test_get_decision_queue_disabled_returns_status() -> None:
    client = _client_for(_FakeRuntime())

    response = client.get("/api/decision-queue")

    assert response.status_code == 200
    assert response.json() == {"status": "disabled"}


def test_pause_decision_queue_endpoint_pauses_queue() -> None:
    queue = DecisionQueue()
    client = _client_for(_FakeRuntime(queue))

    response = client.post("/api/decision-queue/pause", json={"reason": "incident"})

    assert response.status_code == 200
    assert response.json() == {"status": "paused", "reason": "incident"}
    assert queue.paused is True
    assert queue.pause_reason == "incident"


def test_resume_decision_queue_endpoint_resumes_queue() -> None:
    queue = DecisionQueue()
    queue.pause("incident")
    client = _client_for(_FakeRuntime(queue))

    response = client.post("/api/decision-queue/resume")

    assert response.status_code == 200
    assert response.json() == {"status": "resumed"}
    assert queue.paused is False
