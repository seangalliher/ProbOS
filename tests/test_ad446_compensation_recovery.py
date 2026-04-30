from __future__ import annotations

from typing import Any

from probos.events import EventType
from probos.governance.compensation import (
    CompensationHandler,
    CompensationRecord,
    RecoveryStrategy,
)


def test_recovery_strategy_enum() -> None:
    assert RecoveryStrategy.RETRY.value == "retry"
    assert RecoveryStrategy.ESCALATE.value == "escalate"
    assert RecoveryStrategy.ROLLBACK.value == "rollback"
    assert RecoveryStrategy.ABANDON.value == "abandon"


def test_compensation_record_creation() -> None:
    record = CompensationRecord(
        decision_id="d1",
        strategy=RecoveryStrategy.RETRY,
        attempt_number=1,
        error="resource limit",
        metadata={"category": "operational"},
    )

    assert record.decision_id == "d1"
    assert record.strategy is RecoveryStrategy.RETRY
    assert record.attempt_number == 1
    assert record.success is False
    assert record.error == "resource limit"
    assert record.metadata == {"category": "operational"}


def test_handle_failure_retry() -> None:
    handler = CompensationHandler(max_retries=3)

    record = handler.handle_failure("d1", "resource limit", attempt=1)

    assert record.strategy is RecoveryStrategy.RETRY
    assert record.attempt_number == 1
    assert handler.get_summary()["by_strategy"]["retry"] == 1


def test_handle_failure_escalate() -> None:
    handler = CompensationHandler(max_retries=3)

    record = handler.handle_failure("d1", "resource limit", attempt=3)

    assert record.strategy is RecoveryStrategy.ESCALATE
    assert handler.get_summary()["by_strategy"]["escalate"] == 1


def test_handle_failure_abandon() -> None:
    handler = CompensationHandler(max_retries=3)

    record = handler.handle_failure("d1", "resource limit", attempt=4)

    assert record.strategy is RecoveryStrategy.ABANDON
    assert handler.get_summary()["by_strategy"]["abandon"] == 1


def test_escalation_fn_called() -> None:
    escalated: list[str] = []
    handler = CompensationHandler(
        max_retries=3,
        escalation_fn=lambda decision_id: escalated.append(decision_id),
    )

    handler.handle_failure("d1", "resource limit", attempt=3)

    assert escalated == ["d1"]


def test_record_rollback() -> None:
    handler = CompensationHandler()

    record = handler.record_rollback("d1", success=False, error="rollback failed")

    assert record.strategy is RecoveryStrategy.ROLLBACK
    assert record.attempt_number == 0
    assert record.success is False
    assert record.error == "rollback failed"
    assert handler.get_summary()["by_strategy"]["rollback"] == 1


def test_compensation_triggered_event() -> None:
    emitted: list[tuple[Any, dict[str, Any]]] = []
    handler = CompensationHandler(
        emit_fn=lambda event_type, payload: emitted.append((event_type, payload)),
    )

    handler.handle_failure("d1", "resource limit", attempt=1)

    assert emitted[0][0] is EventType.COMPENSATION_TRIGGERED
    assert emitted[0][1]["decision_id"] == "d1"
    assert emitted[0][1]["strategy"] == "retry"
    assert emitted[0][1]["attempt"] == 1
    assert emitted[0][1]["error"] == "resource limit"


def test_compensation_triggered_event_type_exists() -> None:
    assert EventType.COMPENSATION_TRIGGERED.value == "compensation_triggered"


def test_get_history_filters_by_decision_id_and_limit() -> None:
    handler = CompensationHandler()
    handler.handle_failure("d1", "first", attempt=1)
    handler.handle_failure("d2", "second", attempt=1)
    handler.handle_failure("d1", "third", attempt=2)

    history = handler.get_history(decision_id="d1", limit=1)

    assert len(history) == 1
    assert history[0].decision_id == "d1"
    assert history[0].error == "third"
