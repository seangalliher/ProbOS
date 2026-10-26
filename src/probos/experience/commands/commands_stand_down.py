"""AD-1341 S4 (#1569): ``/stand-down``, the Captain's order giving each crew agent one bounded turn to leave exit notes.

Console only (``probos.api._BLOCKED_COMMANDS``). Typed before the vessel is stopped for ``probos reset``; the reset
neither needs it nor waits for it.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markup import escape


async def cmd_stand_down(runtime: Any, console: Console, arg: str) -> None:
    """Run the stand-down, then report each crew agent's turn and the Captain's next steps (D13)."""
    from probos.stand_down import (
        STAND_DOWN_TURN_SECONDS,
        STAND_DOWN_WINDOW_SECONDS,
        StandDownRefused,
        TurnOutcome,
        stand_down_vessel,
    )

    if arg.strip():
        console.print("Usage: /stand-down  (no arguments)")
        return
    console.print(
        f"Standing down: each crew agent gets one turn of at most {STAND_DOWN_TURN_SECONDS:.0f} s to leave exit notes "
        f"for its successor; the window closes after {STAND_DOWN_WINDOW_SECONDS:.0f} s. Writing is optional."
    )
    try:
        report = await stand_down_vessel(runtime)
    except StandDownRefused as exc:
        console.print(f"[yellow]Stand-down refused: {escape(str(exc))}[/yellow]")
        return
    for turn in report.turns:
        where = f" -> {turn.path}" if turn.path else ""
        console.print(f"  {escape(turn.callsign or turn.agent_type)}: {turn.outcome.value}{escape(where)}")
    left = sum(1 for turn in report.turns if turn.path and turn.outcome in (TurnOutcome.FAILED, TurnOutcome.TIMED_OUT))
    if left:  # A5 (round 3 M2-2): a write that did not complete may still have published its note
        console.print(
            f"{left} write(s) did not complete and may have left a document at the path shown; "
            "probos archive pending lists any the next reset would archive."
        )
    console.print(
        f"{report.count(TurnOutcome.WRITTEN)} exit note(s) written for timeline {escape(report.timeline_id)}. "
        "Review: probos archive pending. Veto one: probos archive veto PATH --reason TEXT. "
        "Then stop the vessel and run probos reset."
    )
