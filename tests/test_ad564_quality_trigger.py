"""AD-564: Quality-triggered forced consolidation tests."""

from __future__ import annotations

from probos.config import QualityTriggerConfig
from probos.knowledge.quality_trigger import QualityConsolidationTrigger
from probos.types import DreamReport


class _FakeSnapshot:
    def __init__(self, quality: float = 0.8, stale: float = 0.1, repetition: float = 0.05) -> None:
        self.system_quality_score = quality
        self.stale_entry_rate = stale
        self.repetition_alert_rate = repetition


class _FakeEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def __call__(self, event_type: str, data: dict) -> None:
        self.events.append((event_type, data))


def test_trigger_on_low_quality() -> None:
    trigger = QualityConsolidationTrigger(QualityTriggerConfig(cooldown_seconds=0))

    fired = trigger.check_and_trigger(_FakeSnapshot(quality=0.2))

    assert fired is True


def test_trigger_on_high_stale_rate() -> None:
    trigger = QualityConsolidationTrigger(QualityTriggerConfig(cooldown_seconds=0))

    fired = trigger.check_and_trigger(_FakeSnapshot(stale=0.5))

    assert fired is True


def test_trigger_on_high_repetition() -> None:
    trigger = QualityConsolidationTrigger(QualityTriggerConfig(cooldown_seconds=0))

    fired = trigger.check_and_trigger(_FakeSnapshot(repetition=0.5))

    assert fired is True


def test_no_trigger_good_quality() -> None:
    trigger = QualityConsolidationTrigger(QualityTriggerConfig())

    fired = trigger.check_and_trigger(_FakeSnapshot())

    assert fired is False


def test_cooldown_prevents_rapid() -> None:
    trigger = QualityConsolidationTrigger(QualityTriggerConfig(cooldown_seconds=1800))

    first = trigger.check_and_trigger(_FakeSnapshot(quality=0.2))
    second = trigger.check_and_trigger(_FakeSnapshot(quality=0.2))

    assert first is True
    assert second is False


def test_max_per_day_limit() -> None:
    trigger = QualityConsolidationTrigger(
        QualityTriggerConfig(cooldown_seconds=0, max_forced_per_day=5)
    )

    results = [trigger.check_and_trigger(_FakeSnapshot(quality=0.2)) for _ in range(6)]

    assert results == [True, True, True, True, True, False]


def test_config_disabled() -> None:
    trigger = QualityConsolidationTrigger(QualityTriggerConfig(enabled=False))

    fired = trigger.check_and_trigger(_FakeSnapshot(quality=0.2, stale=0.9, repetition=0.9))

    assert fired is False


def test_event_emitted() -> None:
    emitter = _FakeEmitter()
    trigger = QualityConsolidationTrigger(
        QualityTriggerConfig(cooldown_seconds=0),
        emit_event_fn=emitter,
    )

    trigger.check_and_trigger(_FakeSnapshot(quality=0.2, stale=0.4, repetition=0.3))

    assert len(emitter.events) == 1
    event_type, data = emitter.events[0]
    assert event_type == "forced_consolidation_triggered"
    assert data["quality_score"] == 0.2
    assert data["stale_rate"] == 0.4
    assert data["repetition_rate"] == 0.3
    assert "quality_score" in data["reason"]


def test_dream_report_field() -> None:
    default_report = DreamReport()
    populated_report = DreamReport(forced_consolidations=2)

    assert default_report.forced_consolidations == 0
    assert populated_report.forced_consolidations == 2


def test_reason_string() -> None:
    trigger = QualityConsolidationTrigger(QualityTriggerConfig())

    should_trigger, reason = trigger._should_trigger(_FakeSnapshot(quality=0.2))

    assert should_trigger is True
    assert "quality_score" in reason
    assert "0.200" in reason
    assert "0.4" in reason