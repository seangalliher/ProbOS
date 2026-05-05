"""AD-459b: tests for active-shedding hooks (subsystem pause/resume).

The tests cover:
  * EventType additions (SUBSYSTEM_PAUSED, SUBSYSTEM_RESUMED).
  * DegradationConfig.auto_pause_enabled default.
  * LifecycleAdapter sync/async dispatch + idempotency.
  * DegradationManager.register_subsystem / unregister_subsystem /
    registered_subsystems.
  * set_stress_level scheduling pause/resume tasks on tier-mask deltas.
  * Tier-2 log-and-degrade on pause failures.
  * No-op behavior when no subsystems registered or no running loop.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.config import DegradationConfig
from probos.degradation import LifecycleAdapter, SheddableSubsystem
from probos.degradation.manager import DegradationManager
from probos.degradation.policy import SheddingPolicy, StressLevel
from probos.degradation.registry import ServiceTier, ServiceTierRegistry
from probos.events import EventType


async def _drain(mgr: DegradationManager) -> None:
    pending = list(mgr._lifecycle_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _make_manager() -> tuple[DegradationManager, list[tuple[EventType, dict]]]:
    events: list[tuple[EventType, dict]] = []

    def emit(event_type: EventType, payload: dict) -> None:
        events.append((event_type, payload))

    mgr = DegradationManager(
        registry=ServiceTierRegistry(),
        policy=SheddingPolicy(),
        emit_event=emit,
    )
    return mgr, events


# --- Section 0: EventType additions ---------------------------------------


def test_event_type_subsystem_paused_exists() -> None:
    assert EventType.SUBSYSTEM_PAUSED.value == "subsystem_paused"


def test_event_type_subsystem_resumed_exists() -> None:
    assert EventType.SUBSYSTEM_RESUMED.value == "subsystem_resumed"


# --- Section 1: DegradationConfig.auto_pause_enabled ----------------------


def test_degradation_config_auto_pause_default_false() -> None:
    assert DegradationConfig().auto_pause_enabled is False


# --- Section 2: LifecycleAdapter ------------------------------------------


def test_lifecycle_adapter_async_callable_invoked() -> None:
    on_pause = AsyncMock()
    on_resume = AsyncMock()
    adapter = LifecycleAdapter("svc", on_pause=on_pause, on_resume=on_resume)

    asyncio.run(adapter.pause())

    on_pause.assert_awaited_once()
    assert adapter.is_paused is True
    # SheddableSubsystem structural conformance
    assert isinstance(adapter, SheddableSubsystem)


def test_lifecycle_adapter_sync_callable_invoked() -> None:
    on_pause = MagicMock()
    on_resume = MagicMock()
    adapter = LifecycleAdapter("svc", on_pause=on_pause, on_resume=on_resume)

    asyncio.run(adapter.pause())

    on_pause.assert_called_once()


def test_lifecycle_adapter_pause_idempotent() -> None:
    on_pause = AsyncMock()
    on_resume = AsyncMock()
    adapter = LifecycleAdapter("svc", on_pause=on_pause, on_resume=on_resume)

    async def _run() -> None:
        await adapter.pause()
        await adapter.pause()

    asyncio.run(_run())

    assert on_pause.await_count == 1
    assert adapter.is_paused is True


def test_lifecycle_adapter_resume_idempotent() -> None:
    on_pause = AsyncMock()
    on_resume = AsyncMock()
    adapter = LifecycleAdapter("svc", on_pause=on_pause, on_resume=on_resume)

    async def _run() -> None:
        await adapter.pause()
        await adapter.resume()
        await adapter.resume()

    asyncio.run(_run())

    assert on_resume.await_count == 1
    assert adapter.is_paused is False


# --- Section 3: DegradationManager.register / unregister ------------------


def test_register_subsystem_rejects_unknown_name() -> None:
    mgr, _ = _make_manager()
    adapter = LifecycleAdapter(
        "ghost", on_pause=MagicMock(), on_resume=MagicMock(),
    )

    with pytest.raises(ValueError, match="not classified"):
        mgr.register_subsystem("ghost_subsystem_xyz", adapter)


def test_register_subsystem_replaces_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    mgr, _ = _make_manager()
    a1 = LifecycleAdapter(
        "dream_scheduler", on_pause=MagicMock(), on_resume=MagicMock(),
    )
    a2 = LifecycleAdapter(
        "dream_scheduler", on_pause=MagicMock(), on_resume=MagicMock(),
    )

    mgr.register_subsystem("dream_scheduler", a1)
    with caplog.at_level(logging.WARNING, logger="probos.degradation.manager"):
        mgr.register_subsystem("dream_scheduler", a2)

    assert mgr.registered_subsystems() == ["dream_scheduler"]
    assert mgr._subsystems["dream_scheduler"] is a2
    assert any(
        "already registered" in rec.message for rec in caplog.records
    )


def test_unregister_subsystem_returns_true_when_present_else_false() -> None:
    mgr, _ = _make_manager()
    adapter = LifecycleAdapter(
        "dream_scheduler", on_pause=MagicMock(), on_resume=MagicMock(),
    )
    mgr.register_subsystem("dream_scheduler", adapter)

    assert mgr.unregister_subsystem("dream_scheduler") is True
    assert mgr.unregister_subsystem("dream_scheduler") is False


# --- Section 4: set_stress_level scheduling pause/resume ------------------


def test_set_stress_level_pauses_cognitive_subsystems_on_high() -> None:
    on_pause = MagicMock()
    on_resume = MagicMock()

    async def _run() -> tuple[DegradationManager, list[tuple[EventType, dict]]]:
        mgr, events = _make_manager()
        adapter = LifecycleAdapter(
            "dream_scheduler", on_pause=on_pause, on_resume=on_resume,
        )
        mgr.register_subsystem("dream_scheduler", adapter)
        mgr.set_stress_level(StressLevel.HIGH)
        await _drain(mgr)
        return mgr, events

    _mgr, events = asyncio.run(_run())

    assert on_pause.call_count == 1
    paused = [
        (et, p) for et, p in events if et == EventType.SUBSYSTEM_PAUSED
    ]
    assert len(paused) == 1
    assert paused[0][1]["service"] == "dream_scheduler"
    assert paused[0][1]["stress_level"] == StressLevel.HIGH.value


def test_set_stress_level_resumes_on_normal_after_high() -> None:
    on_pause = MagicMock()
    on_resume = MagicMock()

    async def _run() -> tuple[
        DegradationManager,
        list[tuple[EventType, dict]],
        LifecycleAdapter,
    ]:
        mgr, events = _make_manager()
        adapter = LifecycleAdapter(
            "dream_scheduler", on_pause=on_pause, on_resume=on_resume,
        )
        mgr.register_subsystem("dream_scheduler", adapter)
        mgr.set_stress_level(StressLevel.HIGH)
        await _drain(mgr)
        mgr.set_stress_level(StressLevel.NORMAL)
        await _drain(mgr)
        return mgr, events, adapter

    _mgr, events, adapter = asyncio.run(_run())

    assert on_resume.call_count == 1
    resumed = [
        (et, p) for et, p in events if et == EventType.SUBSYSTEM_RESUMED
    ]
    assert len(resumed) == 1
    assert resumed[0][1]["service"] == "dream_scheduler"
    assert adapter.is_paused is False


def test_pause_exception_logs_warning_and_skips_event(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom() -> None:
        raise RuntimeError("pause failure")

    async def _run() -> list[tuple[EventType, dict]]:
        mgr, events = _make_manager()
        adapter = LifecycleAdapter(
            "dream_scheduler", on_pause=boom, on_resume=MagicMock(),
        )
        mgr.register_subsystem("dream_scheduler", adapter)
        with caplog.at_level(
            logging.WARNING, logger="probos.degradation.manager",
        ):
            mgr.set_stress_level(StressLevel.HIGH)
            await _drain(mgr)
        return events

    events = asyncio.run(_run())

    assert any(
        "pause() failed" in rec.message for rec in caplog.records
    )
    paused_for_dream = [
        (et, p) for et, p in events
        if et == EventType.SUBSYSTEM_PAUSED
        and p.get("service") == "dream_scheduler"
    ]
    assert paused_for_dream == []


def test_no_subsystems_registered_set_stress_level_is_noop_for_subsystems() -> None:
    mgr, events = _make_manager()

    mgr.set_stress_level(StressLevel.HIGH)

    assert mgr._lifecycle_tasks == set()
    # AD-459 v1 tier-level events still emit normally.
    tier_events = [
        et for et, _ in events
        if et in (
            EventType.SERVICE_TIER_DEGRADED,
            EventType.SERVICE_TIER_RESTORED,
        )
    ]
    assert len(tier_events) > 0


def test_set_stress_level_skips_subsystem_tasks_outside_event_loop() -> None:
    mgr, _ = _make_manager()
    adapter = LifecycleAdapter(
        "dream_scheduler", on_pause=MagicMock(), on_resume=MagicMock(),
    )
    mgr.register_subsystem("dream_scheduler", adapter)

    # Sync context: no running event loop.
    mgr.set_stress_level(StressLevel.HIGH)

    assert mgr._lifecycle_tasks == set()
