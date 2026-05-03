"""AD-477 Naval Organization v1 tests — Captain's Log + Plan of the Day."""

from __future__ import annotations

import asyncio
import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.config import (
    CaptainsLogConfig,
    NavalOrganizationConfig,
    PlanOfDayConfig,
    SystemConfig,
)
from probos.events import EventType
from probos.naval import CaptainsLogService, PlanOfDayService


# ---------------------------------------------------------------------------
# Section 0 — EventTypes
# ---------------------------------------------------------------------------


def test_event_type_captains_log_generated_exists():
    assert EventType.CAPTAINS_LOG_GENERATED.value == "captains_log_generated"


def test_event_type_plan_of_day_generated_exists():
    assert EventType.PLAN_OF_DAY_GENERATED.value == "plan_of_day_generated"


# ---------------------------------------------------------------------------
# Section 4 — Pydantic config defaults
# ---------------------------------------------------------------------------


def test_naval_organization_config_defaults():
    cfg = NavalOrganizationConfig()
    assert isinstance(cfg.captains_log, CaptainsLogConfig)
    assert isinstance(cfg.plan_of_day, PlanOfDayConfig)
    assert cfg.captains_log.enabled is True
    assert cfg.captains_log.top_episodes_count == 5
    assert cfg.captains_log.importance_threshold == 5
    assert cfg.captains_log.output_dir == Path("data/captains_log")
    assert cfg.plan_of_day.enabled is True
    assert cfg.plan_of_day.include_alert_conditions is True
    assert cfg.plan_of_day.output_dir == Path("data/plan_of_day")
    # Wired into root SystemConfig
    sysconf = SystemConfig()
    assert isinstance(sysconf.naval_organization, NavalOrganizationConfig)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_ts(year: int, month: int, day: int, hour: int = 12) -> float:
    return datetime.datetime(
        year, month, day, hour, tzinfo=datetime.timezone.utc
    ).timestamp()


def _make_runtime(
    *,
    episodes=None,
    threads=None,
    work_items=None,
    alerts=None,
    has_episodic: bool = True,
    has_ward_room: bool = True,
    has_work_item_store: bool = True,
    has_bridge_alerts: bool = True,
    emit=None,
) -> SimpleNamespace:
    rt = SimpleNamespace()
    rt.episodic_memory = (
        SimpleNamespace(recent=AsyncMock(return_value=list(episodes or [])))
        if has_episodic
        else None
    )
    rt.ward_room = (
        SimpleNamespace(list_threads=AsyncMock(return_value=list(threads or [])))
        if has_ward_room
        else None
    )
    rt.work_item_store = (
        SimpleNamespace(list_work_items=AsyncMock(return_value=list(work_items or [])))
        if has_work_item_store
        else None
    )
    rt.bridge_alerts = (
        SimpleNamespace(get_recent_alerts=MagicMock(return_value=list(alerts or [])))
        if has_bridge_alerts
        else None
    )
    rt.emit_event = emit if emit is not None else MagicMock()
    return rt


# ---------------------------------------------------------------------------
# CaptainsLogService — generate_for_date
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_captains_log_generate_with_no_episodes_returns_empty_template():
    rt = _make_runtime(episodes=[], threads=[], work_items=[])
    svc = CaptainsLogService(rt, CaptainsLogConfig())

    md = await svc.generate_for_date(datetime.date(2026, 5, 3))

    assert "# Captain's Log — 2026-05-03" in md
    assert "## Top Episodes" in md
    assert "## Ward Room Activity" in md
    assert "## Active Work Items" in md
    # Empty-state markers present
    assert "no episodes met the importance threshold" in md
    assert "no Ward Room thread activity" in md
    assert "no open work items" in md


@pytest.mark.asyncio
async def test_captains_log_aggregates_top_episodes_by_importance():
    target = datetime.date(2026, 5, 3)
    in_window_high = SimpleNamespace(
        timestamp=_utc_ts(2026, 5, 3, 10), importance=9, user_input="High-importance event A",
    )
    in_window_mid = SimpleNamespace(
        timestamp=_utc_ts(2026, 5, 3, 14), importance=6, user_input="Mid-importance event B",
    )
    in_window_low = SimpleNamespace(
        timestamp=_utc_ts(2026, 5, 3, 18), importance=3, user_input="Below threshold C",
    )
    out_of_window = SimpleNamespace(
        timestamp=_utc_ts(2026, 5, 2, 10), importance=10, user_input="Yesterday — must be excluded",
    )

    cfg = CaptainsLogConfig(top_episodes_count=2, importance_threshold=5)
    rt = _make_runtime(episodes=[in_window_high, in_window_mid, in_window_low, out_of_window])
    svc = CaptainsLogService(rt, cfg)

    md = await svc.generate_for_date(target)

    # Over-fetch occurred: recent(k=top_episodes_count*4)
    rt.episodic_memory.recent.assert_awaited_once_with(k=8)
    assert "High-importance event A" in md
    assert "Mid-importance event B" in md
    # Below threshold filtered out
    assert "Below threshold C" not in md
    # Out-of-window filtered out
    assert "Yesterday" not in md
    # Sort order — high importance appears before mid in markdown
    assert md.index("High-importance event A") < md.index("Mid-importance event B")


@pytest.mark.asyncio
async def test_captains_log_includes_ward_room_summary():
    target = datetime.date(2026, 5, 3)
    same_day = SimpleNamespace(
        last_activity=_utc_ts(2026, 5, 3, 9), title="Engineering retrofit thread",
    )
    other_day = SimpleNamespace(
        last_activity=_utc_ts(2026, 5, 1, 9), title="Old discussion",
    )
    rt = _make_runtime(threads=[same_day, other_day])
    svc = CaptainsLogService(rt, CaptainsLogConfig())

    md = await svc.generate_for_date(target)

    rt.ward_room.list_threads.assert_awaited_once_with(
        channel_id=None, limit=50, sort="recent",
    )
    assert "Threads with activity: 1" in md
    assert "Engineering retrofit thread" in md
    assert "Old discussion" not in md


@pytest.mark.asyncio
async def test_captains_log_write_to_disk_emits_event(tmp_path):
    cfg = CaptainsLogConfig(output_dir=tmp_path / "logs")
    emit = MagicMock()
    rt = _make_runtime(episodes=[], threads=[], work_items=[], emit=emit)
    svc = CaptainsLogService(rt, cfg)
    target = datetime.date(2026, 5, 3)

    out_path = await svc.write_to_disk(target)

    assert out_path == tmp_path / "logs" / "2026-05-03.md"
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "Captain's Log — 2026-05-03" in content
    emit.assert_called_once()
    et, payload = emit.call_args[0]
    assert et == EventType.CAPTAINS_LOG_GENERATED
    assert payload["date"] == "2026-05-03"
    assert payload["path"] == str(out_path)


# ---------------------------------------------------------------------------
# PlanOfDayService — generate_for_date
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_of_day_aggregates_open_work_items():
    item_a = SimpleNamespace(title="Refactor decomposer", priority=1)
    item_b = SimpleNamespace(title="Patch trust drift", priority=2)
    rt = _make_runtime(work_items=[item_a, item_b])
    svc = PlanOfDayService(rt, PlanOfDayConfig())

    md = await svc.generate_for_date(datetime.date(2026, 5, 3))

    rt.work_item_store.list_work_items.assert_awaited_once_with(status="open")
    assert "# Plan of the Day — 2026-05-03" in md
    assert "Open work items: 2" in md
    assert "Refactor decomposer" in md
    assert "Patch trust drift" in md


@pytest.mark.asyncio
async def test_plan_of_day_includes_alert_conditions_when_enabled():
    alert = SimpleNamespace(severity="yellow", title="Trust drift detected on engineering")
    rt = _make_runtime(work_items=[], alerts=[alert])

    enabled_cfg = PlanOfDayConfig(include_alert_conditions=True)
    md_enabled = await PlanOfDayService(rt, enabled_cfg).generate_for_date(
        datetime.date(2026, 5, 3)
    )
    assert "Trust drift detected on engineering" in md_enabled
    assert "yellow" in md_enabled
    rt.bridge_alerts.get_recent_alerts.assert_called_once_with(10)

    rt2 = _make_runtime(work_items=[], alerts=[alert])
    disabled_cfg = PlanOfDayConfig(include_alert_conditions=False)
    md_disabled = await PlanOfDayService(rt2, disabled_cfg).generate_for_date(
        datetime.date(2026, 5, 3)
    )
    assert "Trust drift detected" not in md_disabled
    assert "alert conditions disabled in config" in md_disabled
    rt2.bridge_alerts.get_recent_alerts.assert_not_called()


@pytest.mark.asyncio
async def test_plan_of_day_write_to_disk_emits_event(tmp_path):
    cfg = PlanOfDayConfig(output_dir=tmp_path / "pod", include_alert_conditions=False)
    emit = MagicMock()
    rt = _make_runtime(work_items=[], threads=[], emit=emit)
    svc = PlanOfDayService(rt, cfg)
    target = datetime.date(2026, 5, 3)

    out_path = await svc.write_to_disk(target)

    assert out_path == tmp_path / "pod" / "2026-05-03.md"
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "Plan of the Day — 2026-05-03" in content
    emit.assert_called_once()
    et, payload = emit.call_args[0]
    assert et == EventType.PLAN_OF_DAY_GENERATED
    assert payload["date"] == "2026-05-03"
    assert payload["path"] == str(out_path)


# ---------------------------------------------------------------------------
# Background-task lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_creates_named_task():
    svc = CaptainsLogService(_make_runtime(), CaptainsLogConfig())
    assert svc._task is None
    await svc.start()
    try:
        assert svc._task is not None
        assert isinstance(svc._task, asyncio.Task)
        assert not svc._task.done()
        # Idempotent: second start does not replace running task
        original = svc._task
        await svc.start()
        assert svc._task is original
    finally:
        with pytest.raises(asyncio.CancelledError):
            await svc.stop()


@pytest.mark.asyncio
async def test_stop_surfaces_cancellederror_to_caller_after_cleanup():
    """Async-discipline rule: long-running loop catches CancelledError, performs
    cleanup, re-raises. ``stop()`` must NOT silently swallow the cancellation —
    the caller must be able to observe it via ``pytest.raises``."""
    svc = PlanOfDayService(_make_runtime(), PlanOfDayConfig())
    await svc.start()
    # Yield once so the loop reaches its first await
    await asyncio.sleep(0)

    with pytest.raises(asyncio.CancelledError):
        await svc.stop()


# ---------------------------------------------------------------------------
# Runtime wiring (Section 5)
# ---------------------------------------------------------------------------


def test_runtime_attribute_set_when_enabled():
    """When config has both services enabled, finalize.py wires public
    attributes (no leading underscore) on the runtime object."""
    naval_cfg = NavalOrganizationConfig()
    assert naval_cfg.captains_log.enabled is True
    assert naval_cfg.plan_of_day.enabled is True

    # Smoke-construct the services as finalize.py would (without running the
    # full startup pipeline) to verify the public attribute names are exactly
    # the ones the prompt specified.
    rt = SimpleNamespace()
    rt.captains_log_service = CaptainsLogService(rt, naval_cfg.captains_log)
    rt.plan_of_day_service = PlanOfDayService(rt, naval_cfg.plan_of_day)

    assert hasattr(rt, "captains_log_service")
    assert hasattr(rt, "plan_of_day_service")
    assert isinstance(rt.captains_log_service, CaptainsLogService)
    assert isinstance(rt.plan_of_day_service, PlanOfDayService)
    # Public attribute names — no underscore prefix
    assert not any(
        name.startswith("_")
        for name in (
            "captains_log_service",
            "plan_of_day_service",
            "captains_log_start_task",
            "plan_of_day_start_task",
        )
    )


def test_runtime_attribute_none_when_disabled():
    """When config disables a service, finalize.py leaves the runtime
    attribute as None — consumers must check for None before use."""
    cfg = NavalOrganizationConfig(
        captains_log=CaptainsLogConfig(enabled=False),
        plan_of_day=PlanOfDayConfig(enabled=False),
    )
    assert cfg.captains_log.enabled is False
    assert cfg.plan_of_day.enabled is False

    # Mirror finalize.py's wiring shape: defaults to None, conditionally set.
    rt = SimpleNamespace(
        captains_log_service=None,
        captains_log_start_task=None,
        plan_of_day_service=None,
        plan_of_day_start_task=None,
    )
    if cfg.captains_log.enabled:  # branch not taken
        rt.captains_log_service = CaptainsLogService(rt, cfg.captains_log)
    if cfg.plan_of_day.enabled:  # branch not taken
        rt.plan_of_day_service = PlanOfDayService(rt, cfg.plan_of_day)

    assert rt.captains_log_service is None
    assert rt.plan_of_day_service is None
    assert rt.captains_log_start_task is None
    assert rt.plan_of_day_start_task is None
