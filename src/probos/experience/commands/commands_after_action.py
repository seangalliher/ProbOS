"""AD-1341 S5 (#1569): ``/after-action CALLSIGN: SUBJECT``, the Captain's order for one after-action report.

Console only (``probos.api._BLOCKED_COMMANDS``). The named agent gets one bounded turn; its chain of command then
reviews the report (D5). The report reaches the Ship's Archive only if the chain endorsed it, and the Captain can still
veto it.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markup import escape


async def cmd_after_action(runtime: Any, console: Console, arg: str) -> None:
    """Run one report and its review, then report each stage and the Captain's next steps (D14)."""
    from probos.after_action import (
        AFTER_ACTION_TURN_SECONDS,
        AFTER_ACTION_WINDOW_SECONDS,
        AfterActionOutcome,
        AfterActionRefused,
        after_action_vessel,
    )

    callsign, _separator, subject = arg.partition(":")
    if not callsign.strip() or not subject.strip():
        console.print("Usage: /after-action CALLSIGN: SUBJECT  (the event to review, in one line)")
        return
    console.print(
        f"After-action report: {escape(callsign.strip())} gets one turn of at most {AFTER_ACTION_TURN_SECONDS:.0f} s, "
        f"then the chain of command reviews it; the window closes after {AFTER_ACTION_WINDOW_SECONDS:.0f} s."
    )
    try:
        report = await after_action_vessel(runtime, callsign, subject)
    except AfterActionRefused as exc:
        console.print(f"[yellow]After-action report refused: {escape(str(exc))}[/yellow]")
        return
    where = f" -> {report.path}" if report.path else ""
    console.print(f"  {escape(report.callsign or report.agent_type)}: {report.outcome.value}{escape(where)}")
    for review in report.reviews:
        who = f" ({review.callsign})" if review.callsign else ""
        console.print(f"  review {review.stage}: {review.outcome}{escape(who)}")
    if report.outcome is AfterActionOutcome.WRITTEN:
        verdict = (
            "endorsed by the chain of command; it may be archived" if report.endorsed
            else "not endorsed; it stays in Ship's Records and is never archived"
        )
        console.print(
            f"Report {verdict}. Review: probos archive pending. Veto one: probos archive veto PATH --reason TEXT."
        )
