"""AD-815g: recurring TaskSession scheduler tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from probos.task_sessions import TaskSessionStore
from probos.task_sessions.scheduler import (
    CronExpr,
    CronParseError,
    find_due_sessions,
    is_due,
    parse_cron,
    tick,
)


# ---------------- parser ----------------


def test_parse_wildcard_every_minute():
    c = parse_cron("* * * * *")
    assert len(c.minute) == 60 and len(c.hour) == 24


def test_parse_specific_minute_hour():
    c = parse_cron("30 9 * * *")
    assert c.minute == frozenset({30})
    assert c.hour == frozenset({9})


def test_parse_range():
    c = parse_cron("0 9-11 * * *")
    assert c.hour == frozenset({9, 10, 11})


def test_parse_step():
    c = parse_cron("*/15 * * * *")
    assert c.minute == frozenset({0, 15, 30, 45})


def test_parse_list():
    c = parse_cron("0,30 9,17 * * *")
    assert c.minute == frozenset({0, 30})
    assert c.hour == frozenset({9, 17})


def test_parse_dow_7_is_sunday():
    c = parse_cron("0 0 * * 7")
    assert c.dow == frozenset({0})


def test_parse_rejects_bad_field_count():
    with pytest.raises(CronParseError):
        parse_cron("* * * *")


def test_parse_rejects_out_of_range():
    with pytest.raises(CronParseError):
        parse_cron("60 * * * *")
    with pytest.raises(CronParseError):
        parse_cron("* 24 * * *")


def test_parse_rejects_bad_step():
    with pytest.raises(CronParseError):
        parse_cron("*/abc * * * *")


# ---------------- matches ----------------


def test_matches_specific_time():
    c = parse_cron("30 9 * * *")
    assert c.matches(datetime(2026, 5, 22, 9, 30, tzinfo=timezone.utc))
    assert not c.matches(datetime(2026, 5, 22, 9, 31, tzinfo=timezone.utc))
    assert not c.matches(datetime(2026, 5, 22, 10, 30, tzinfo=timezone.utc))


def test_matches_dow_friday():
    # 2026-05-22 is a Friday → cron dow=5
    c = parse_cron("0 9 * * 5")
    assert c.matches(datetime(2026, 5, 22, 9, 0, tzinfo=timezone.utc))


def test_matches_posix_dom_or_dow_when_both_restricted():
    # POSIX: when both dom and dow restricted, fire when EITHER matches.
    c = parse_cron("0 9 1 * 5")  # 1st of month OR Friday
    # 2026-05-22 is Friday but not the 1st → should fire
    assert c.matches(datetime(2026, 5, 22, 9, 0, tzinfo=timezone.utc))
    # 2026-05-01 is Friday AND 1st → should fire
    assert c.matches(datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc))


# ---------------- is_due / tick ----------------


def _store(tmp_path):
    return TaskSessionStore(
        db_path=tmp_path / "ts.db", workspace_root=tmp_path / "ws"
    )


def test_is_due_only_when_recurring_and_terminal(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(
        thread_id="t1",
        title="daily",
        schedule_kind="recurring",
        schedule_cron="30 9 * * *",
    )
    # pending → not due
    assert is_due(sess, now=datetime(2026, 5, 22, 9, 30, tzinfo=timezone.utc)) is False
    # transition to completed
    run = s.start_run(sess.id)
    s.finish_run(run.id, exit_code=0, container_image_used="img")
    sess = s.get_session(sess.id)
    # Match the cron's minute boundary but a different minute from last_run
    far_future = datetime(2027, 5, 22, 9, 30, tzinfo=timezone.utc)
    assert is_due(sess, now=far_future) is True


def test_is_due_skips_same_minute_as_last_run(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(
        thread_id="t1",
        title="x",
        schedule_kind="recurring",
        schedule_cron="* * * * *",  # every minute
    )
    run = s.start_run(sess.id)
    s.finish_run(run.id, exit_code=0, container_image_used="img")
    sess = s.get_session(sess.id)
    last_dt = datetime.fromtimestamp(sess.last_run_at, tz=timezone.utc)
    assert is_due(sess, now=last_dt) is False


def test_is_due_false_for_one_shot(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(thread_id="t1", title="x")
    run = s.start_run(sess.id)
    s.finish_run(run.id, exit_code=0, container_image_used="img")
    sess = s.get_session(sess.id)
    assert is_due(sess, now=datetime(2026, 5, 22, 9, 30, tzinfo=timezone.utc)) is False


def test_tick_reuse_policy_rearms(tmp_path):
    clock = {"t": 1.0}
    s = TaskSessionStore(
        db_path=tmp_path / "ts.db",
        workspace_root=tmp_path / "ws",
        clock=lambda: clock["t"],
    )
    sess = s.create_session(
        thread_id="t1",
        title="x",
        schedule_kind="recurring",
        schedule_cron="* * * * *",
        recurrence_policy="reuse",
    )
    run = s.start_run(sess.id)
    s.finish_run(run.id, exit_code=0, container_image_used="img")
    # Advance one minute so the same-minute guard passes
    last_dt = datetime.fromtimestamp(s.get_session(sess.id).last_run_at, tz=timezone.utc)
    future = last_dt.replace(second=0) + (datetime(2030, 1, 1) - datetime(2030, 1, 1))
    # Use a clearly different minute
    far = datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc)
    ids = tick(s, now=far)
    assert sess.id in ids
    assert s.get_session(sess.id).status == "pending"


def test_tick_new_session_each_run_forks_child(tmp_path):
    s = _store(tmp_path)
    parent = s.create_session(
        thread_id="t1",
        title="daily",
        schedule_kind="recurring",
        schedule_cron="* * * * *",
        recurrence_policy="new_session_each_run",
    )
    run = s.start_run(parent.id)
    s.finish_run(run.id, exit_code=0, container_image_used="img")
    far = datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc)
    ids = tick(s, now=far)
    # Parent stays completed; a child is created in pending.
    assert s.get_session(parent.id).status == "completed"
    children = [s.get_session(i) for i in ids]
    assert len(children) == 1
    child = children[0]
    assert child.parent_session_id == parent.id
    assert child.thread_id == parent.id and False or child.thread_id == "t1"
    assert child.status == "pending"


def test_tick_respects_recurrence_max_runs(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(
        thread_id="t1",
        title="x",
        schedule_kind="recurring",
        schedule_cron="* * * * *",
        recurrence_max_runs=1,
    )
    run = s.start_run(sess.id)
    s.finish_run(run.id, exit_code=0, container_image_used="img")
    # Already ran once; cap of 1 → tick should NOT re-arm
    far = datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc)
    ids = tick(s, now=far)
    assert sess.id not in ids


def test_tick_ignores_malformed_cron(tmp_path):
    s = _store(tmp_path)
    sess = s.create_session(
        thread_id="t1",
        title="x",
        schedule_kind="recurring",
        schedule_cron="not a valid cron",
    )
    run = s.start_run(sess.id)
    s.finish_run(run.id, exit_code=0, container_image_used="img")
    far = datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc)
    assert tick(s, now=far) == []
