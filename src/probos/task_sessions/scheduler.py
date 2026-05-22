"""AD-815g: recurring TaskSession scheduler — minimal 5-field cron.

Supports the standard 5-field cron syntax (minute, hour, day-of-month,
month, day-of-week) with:

* numbers: ``0-59`` minute, ``0-23`` hour, ``1-31`` dom, ``1-12`` mon,
  ``0-7`` dow (both 0 and 7 = Sunday)
* wildcards: ``*``
* ranges: ``1-5``
* lists: ``1,3,5``
* steps: ``*/15``, ``0-30/5``

What v1 deliberately does NOT support: named months/days (``JAN``,
``MON``), ``@yearly``/``@daily`` macros, seconds field, quartz-style
"L" / "W" qualifiers. Operators who need those can install a richer
parser as a follow-up (AD-815g-a).

The tick engine ``run_due_sessions`` polls
``task_session_store`` for recurring sessions in a terminal state,
asks the cron whether the session is due, and re-arms (or forks) per
the session's ``recurrence_policy``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from probos.task_sessions import TaskSession, TaskSessionStore

logger = logging.getLogger(__name__)


class CronParseError(ValueError):
    """Raised for malformed cron expressions."""


@dataclass(frozen=True)
class CronExpr:
    minute: frozenset[int]
    hour: frozenset[int]
    dom: frozenset[int]
    month: frozenset[int]
    dow: frozenset[int]  # 0-6, Sunday=0; "7" normalizes to 0

    def matches(self, dt: datetime) -> bool:
        """Match the *minute boundary* of ``dt`` (seconds ignored)."""
        # POSIX cron-style: if BOTH dom and dow are restricted (not full
        # sets), match when EITHER hits. If only one is restricted, only
        # that one constrains.
        full_dom = self.dom == frozenset(range(1, 32))
        full_dow = self.dow == frozenset(range(0, 7))
        # weekday(): Monday=0..Sunday=6 → convert to cron Sunday=0..Saturday=6
        cron_dow = (dt.weekday() + 1) % 7
        dom_ok = dt.day in self.dom
        dow_ok = cron_dow in self.dow
        if full_dom and full_dow:
            date_ok = True
        elif full_dom:
            date_ok = dow_ok
        elif full_dow:
            date_ok = dom_ok
        else:
            date_ok = dom_ok or dow_ok
        return (
            dt.minute in self.minute
            and dt.hour in self.hour
            and dt.month in self.month
            and date_ok
        )


def _parse_field(spec: str, *, lo: int, hi: int) -> frozenset[int]:
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            raise CronParseError(f"empty subfield in {spec!r}")
        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            try:
                step = int(step_s)
            except ValueError as exc:
                raise CronParseError(f"bad step in {part!r}") from exc
            if step <= 0:
                raise CronParseError(f"step must be positive in {part!r}")
        else:
            base = part
        if base == "*":
            start, end = lo, hi
        elif "-" in base:
            try:
                start_s, end_s = base.split("-", 1)
                start, end = int(start_s), int(end_s)
            except ValueError as exc:
                raise CronParseError(f"bad range in {part!r}") from exc
        else:
            try:
                start = end = int(base)
            except ValueError as exc:
                raise CronParseError(f"bad number in {part!r}") from exc
        if start < lo or end > hi or start > end:
            raise CronParseError(
                f"value out of range [{lo},{hi}] in {part!r}"
            )
        out.update(range(start, end + 1, step))
    return frozenset(out)


def parse_cron(expr: str) -> CronExpr:
    """Parse a 5-field cron expression."""
    fields = expr.strip().split()
    if len(fields) != 5:
        raise CronParseError(
            f"cron must have 5 fields (minute hour dom month dow); got {len(fields)}"
        )
    minute = _parse_field(fields[0], lo=0, hi=59)
    hour = _parse_field(fields[1], lo=0, hi=23)
    dom = _parse_field(fields[2], lo=1, hi=31)
    month = _parse_field(fields[3], lo=1, hi=12)
    dow_raw = _parse_field(fields[4], lo=0, hi=7)
    # Normalize 7 → 0 (Sunday).
    dow = frozenset({0 if d == 7 else d for d in dow_raw})
    return CronExpr(minute=minute, hour=hour, dom=dom, month=month, dow=dow)


def is_due(
    session: TaskSession, *, now: datetime
) -> bool:
    """Return True if a recurring session is due to re-fire at ``now``.

    A session is due when:
    * ``schedule_kind == "recurring"``
    * ``status`` is in ``{completed, failed}`` (not running, not pending)
    * the cron expression matches the current minute
    * the recurrence_max_runs cap (if set) hasn't been reached
    * the last_run_at is strictly before the matching minute boundary
      (prevents double-fires within the same minute)
    """
    if session.schedule_kind != "recurring" or not session.schedule_cron:
        return False
    if session.status not in {"completed", "failed"}:
        return False
    try:
        cron = parse_cron(session.schedule_cron)
    except CronParseError:
        logger.warning(
            "AD-815g: malformed cron on session %s: %s",
            session.id, session.schedule_cron,
        )
        return False
    if not cron.matches(now):
        return False
    if session.last_run_at is not None:
        last_dt = datetime.fromtimestamp(session.last_run_at, tz=timezone.utc)
        if (
            last_dt.year == now.year
            and last_dt.month == now.month
            and last_dt.day == now.day
            and last_dt.hour == now.hour
            and last_dt.minute == now.minute
        ):
            return False
    # Note: recurrence_max_runs cap is enforced by the caller via run count
    # lookup against task_session_runs; CronExpr.matches() does the time
    # check, the caller does the budget check.
    return True


def find_due_sessions(
    store: TaskSessionStore, *, now: datetime
) -> list[TaskSession]:
    """Return all sessions in (completed|failed) that are due to re-fire.

    Recurrence cap is checked here using ``len(list_runs(session.id))``.
    """
    candidates: list[TaskSession] = []
    for status in ("completed", "failed"):
        candidates.extend(store.list_sessions(status=status, limit=500))
    due: list[TaskSession] = []
    for s in candidates:
        if not is_due(s, now=now):
            continue
        if s.recurrence_max_runs is not None:
            runs = store.list_runs(s.id, limit=s.recurrence_max_runs + 1)
            if len(runs) >= s.recurrence_max_runs:
                continue
        due.append(s)
    return due


def tick(
    store: TaskSessionStore, *, now: datetime | None = None
) -> list[str]:
    """One scheduler tick.

    For each due session, applies its recurrence_policy:

    * ``reuse``                  — re-arm the existing session (pending).
    * ``new_session_each_run``   — fork a clean child session pointing at
                                   the same thread; parent stays in its
                                   terminal status. Child carries
                                   parent_session_id for provenance.

    Returns the IDs of sessions transitioned to ``pending``.
    """
    now = now or datetime.now(timezone.utc)
    due = find_due_sessions(store, now=now)
    transitioned: list[str] = []
    for s in due:
        if s.recurrence_policy == "new_session_each_run":
            child = store.create_session(
                thread_id=s.thread_id,
                title=s.title,
                schedule_kind=s.schedule_kind,
                schedule_cron=s.schedule_cron,
                schedule_timezone=s.schedule_timezone,
                recurrence_policy=s.recurrence_policy,
                recurrence_max_runs=s.recurrence_max_runs,
                parent_session_id=s.id,
                container_image=s.container_image,
                egress_policy=s.egress_policy,
            )
            transitioned.append(child.id)
        else:
            rearmed = store.rearm(s.id)
            if rearmed is not None and rearmed.status == "pending":
                transitioned.append(rearmed.id)
    return transitioned
