"""Clinical telemetry shell command for ProbOSShell (AD-635e).

`/clinical` surfaces the AD-635 / AD-635b / AD-635c / AD-635d clinical data
domains directly in the Captain's shell. Captain bypasses the clearance gate
via `captain_override=True`; every query is stamped `by_captain=True` on the
service's in-memory audit ring (and persisted via AD-635b when configured).

Subcommands:
  /clinical                       Help / overview
  /clinical dreams [N]            Recent dream-cycle reports (default 20)
  /clinical traces <id> [N]       Recent cognitive-chain traces for one agent
  /clinical breakers [<id>] [N]   Circuit-breaker history (per-agent or fleet)
  /clinical audit [N]             Service audit-ring snapshot (default 200)

When `runtime.clinical_telemetry is None` (the default `enabled=False`
config), prints an explanatory message and returns. Mirrors `cmd_dream`
behavior for the analogous `dream_scheduler is None` case.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.console import Console

from probos.experience import panels

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)

# AD-635e DLog #12 — canonical Captain identity (matches ward_room_router.py:325,
# clearance_grants.py:111, acm.py:250).
_CAPTAIN_ID = "captain"

_USAGE = (
    "[bold]/clinical[/bold] — clinical telemetry (Captain authority)\n\n"
    "  /clinical dreams [N]            Recent dream-cycle reports\n"
    "  /clinical traces <agent> [N]    Recent chain traces for one agent\n"
    "  /clinical breakers [<agent>] [N]  Circuit-breaker history\n"
    "  /clinical audit [N]             Audit-ring snapshot\n"
)


def _parse_limit(token: str, default: int) -> int | None:
    """Parse a positional integer arg. Returns None on malformed input."""
    if not token:
        return default
    try:
        n = int(token)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else default


async def cmd_clinical(
    runtime: "ProbOSRuntime", console: Console, args: str
) -> None:
    """Handle `/clinical [subcommand] [args...]`."""
    service = getattr(runtime, "clinical_telemetry", None)
    if service is None:
        console.print(
            "[yellow]Clinical telemetry is not enabled. "
            "Set `clinical_telemetry.enabled: true` in config to activate.[/yellow]"
        )
        return

    parts = args.split()
    if not parts:
        console.print(_USAGE)
        return

    sub = parts[0].lower()
    rest = parts[1:]

    if sub == "dreams":
        await _sub_dreams(service, console, rest)
    elif sub == "traces":
        await _sub_traces(service, console, rest)
    elif sub == "breakers":
        await _sub_breakers(service, console, rest)
    elif sub == "audit":
        await _sub_audit(service, console, rest)
    else:
        console.print(f"[red]Unknown subcommand: {sub}[/red]")
        console.print(_USAGE)


async def _sub_dreams(service, console: Console, rest: list[str]) -> None:
    limit_token = rest[0] if rest else ""
    limit = _parse_limit(limit_token, default=20)
    if limit is None:
        console.print(f"[red]Usage: /clinical dreams [N]; got '{limit_token}'.[/red]")
        return
    rows = await service.query_dream_history(
        requester_agent_id=_CAPTAIN_ID,
        limit=limit,
        captain_override=True,
    )
    console.print(panels.render_clinical_dreams_panel(rows))


async def _sub_traces(service, console: Console, rest: list[str]) -> None:
    if not rest:
        console.print("[yellow]Usage: /clinical traces <agent_id> [N][/yellow]")
        return
    target = rest[0]
    limit_token = rest[1] if len(rest) > 1 else ""
    limit = _parse_limit(limit_token, default=20)
    if limit is None:
        console.print(
            f"[red]Usage: /clinical traces <agent_id> [N]; got '{limit_token}'.[/red]"
        )
        return
    rows = await service.query_agent_chain_traces(
        requester_agent_id=_CAPTAIN_ID,
        target_agent_id=target,
        limit=limit,
        captain_override=True,
    )
    console.print(panels.render_clinical_traces_panel(rows, target_agent_id=target))


async def _sub_breakers(service, console: Console, rest: list[str]) -> None:
    target: str | None = None
    limit_token = ""
    if rest:
        # First token is either an agent_id or a numeric limit (fleet-wide).
        if rest[0].lstrip("-").isdigit():
            limit_token = rest[0]
        else:
            target = rest[0]
            if len(rest) > 1:
                limit_token = rest[1]
    limit = _parse_limit(limit_token, default=50)
    if limit is None:
        console.print(
            f"[red]Usage: /clinical breakers [<agent_id>] [N]; got '{limit_token}'.[/red]"
        )
        return
    rows = await service.query_circuit_breaker_history(
        requester_agent_id=_CAPTAIN_ID,
        target_agent_id=target,
        limit=limit,
        captain_override=True,
    )
    console.print(
        panels.render_clinical_breakers_panel(rows, target_agent_id=target)
    )


async def _sub_audit(service, console: Console, rest: list[str]) -> None:
    limit_token = rest[0] if rest else ""
    limit = _parse_limit(limit_token, default=200)
    if limit is None:
        console.print(f"[red]Usage: /clinical audit [N]; got '{limit_token}'.[/red]")
        return
    # AD-635e DLog #10: audit_log is a public no-gate property; slice in-shell.
    snapshot = service.audit_log
    rows = list(snapshot[-limit:]) if limit > 0 else []
    console.print(panels.render_clinical_audit_panel(rows))
