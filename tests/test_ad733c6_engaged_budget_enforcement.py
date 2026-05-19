"""AD-733c-6: engaged-mode vision call budget enforcement tests.

Real PerceptionModeController + real SystemConfig (no MagicMock at the
substrate boundary, per BF-287).
"""
from __future__ import annotations

import logging

import pytest

from probos.config import SystemConfig
from probos.perception.consumer import VisionConsumer
from probos.perception.mode_controller import Mode, PerceptionModeController


class _FakeRuntime:
    def __init__(self) -> None:
        self.config = SystemConfig()
        self.llm_client = None
        # AD-733c-6 reads runtime.perception_mode_controller.
        self.perception_mode_controller = None  # set after consumer constructed


def _make_pair(*, cap_session: int = 1000, cap_day: int = 10000,
               enforcement: bool = True, initial_mode: Mode = Mode.ENGAGED):
    runtime = _FakeRuntime()
    cfg = runtime.config.perception
    cfg.engaged_call_cap_per_session = cap_session
    cfg.engaged_call_cap_per_day = cap_day
    cfg.engaged_budget_enforcement = enforcement
    consumer = VisionConsumer(runtime)
    controller = PerceptionModeController(consumer, initial_mode=initial_mode)
    runtime.perception_mode_controller = controller
    return runtime, consumer, controller


def test_under_cap_no_transition(caplog) -> None:
    _r, consumer, controller = _make_pair(cap_session=100, cap_day=1000)
    with caplog.at_level(logging.WARNING):
        for _ in range(50):
            consumer._record_vision_call("vision", "sess1")
    assert controller.current_mode is Mode.ENGAGED
    assert not any("AD-733c-6" in r.message for r in caplog.records)


def test_session_cap_hit_drops_to_ambient() -> None:
    _r, consumer, controller = _make_pair(cap_session=5, cap_day=1000)
    for _ in range(5):
        consumer._record_vision_call("vision", "sess1")
    assert controller.current_mode is Mode.AMBIENT
    # Newest transition entry trigger is budget_exhausted.
    recent = controller.recent_transitions(limit=8)
    assert recent[0].trigger == "budget_exhausted"


def test_day_cap_hit_drops_to_ambient() -> None:
    _r, consumer, controller = _make_pair(cap_session=999, cap_day=3)
    for _ in range(3):
        consumer._record_vision_call("vision", "sess1")
    assert controller.current_mode is Mode.AMBIENT
    assert controller.recent_transitions(limit=8)[0].trigger == "budget_exhausted"


def test_enforcement_disabled_no_transition() -> None:
    _r, consumer, controller = _make_pair(
        cap_session=5, cap_day=1000, enforcement=False
    )
    for _ in range(10):
        consumer._record_vision_call("vision", "sess1")
    assert controller.current_mode is Mode.ENGAGED


def test_ambient_mode_no_transition() -> None:
    _r, consumer, controller = _make_pair(
        cap_session=2, cap_day=10, initial_mode=Mode.AMBIENT
    )
    # Cap is past, but current mode is AMBIENT — no transition should fire.
    for _ in range(10):
        consumer._record_vision_call("vision", "sess1")
    assert controller.current_mode is Mode.AMBIENT
    # No "budget_exhausted" trigger in history (init may be present).
    assert all(t.trigger != "budget_exhausted"
               for t in controller.recent_transitions(limit=16))


def test_cap_notification_rate_limited_per_session(caplog) -> None:
    _r, consumer, controller = _make_pair(cap_session=2, cap_day=1000)
    with caplog.at_level(logging.WARNING):
        for _ in range(5):
            consumer._record_vision_call("vision", "sess1")
    matches = [r for r in caplog.records if "AD-733c-6" in r.message
               and "cap reached" in r.message]
    assert len(matches) == 1


def test_session_change_resets_notification_flag(caplog) -> None:
    _r, consumer, controller = _make_pair(cap_session=2, cap_day=1000)
    with caplog.at_level(logging.WARNING):
        # Session A: 2 calls hit cap.
        consumer._record_vision_call("vision", "sessA")
        consumer._record_vision_call("vision", "sessA")
        # Reset mode back to ENGAGED so session B can hit cap again.
        controller.transition_to(Mode.ENGAGED, trigger="manual")
        # Session B: 2 fresh calls hit cap.
        consumer._record_vision_call("vision", "sessB")
        consumer._record_vision_call("vision", "sessB")
    matches = [r for r in caplog.records if "AD-733c-6" in r.message
               and "cap reached" in r.message]
    assert len(matches) == 2


def test_snapshot_exposes_caps_and_cap_reached() -> None:
    _r, consumer, _c = _make_pair(cap_session=10, cap_day=100, enforcement=True)
    snap = consumer.get_budget_snapshot()
    assert snap["cap_per_session"] == 10
    assert snap["cap_per_day"] == 100
    assert snap["enforcement_enabled"] is True
    assert snap["cap_reached_session"] is False
    assert snap["cap_reached_day"] is False


def test_hot_reload_cap_change_takes_effect() -> None:
    runtime, consumer, controller = _make_pair(cap_session=100, cap_day=1000)
    cfg = runtime.config.perception
    for _ in range(50):
        consumer._record_vision_call("vision", "sess1")
    assert controller.current_mode is Mode.ENGAGED
    # Hot-reload the cap to a lower value.
    cfg.engaged_call_cap_per_session = 10
    # The next call should now trip the cap (50 > 10).
    consumer._record_vision_call("vision", "sess1")
    assert controller.current_mode is Mode.AMBIENT
