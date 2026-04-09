"""AD-580: Alert resolution feedback shell commands."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_alert(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Alert management commands: dismiss, resolve, mute, unmute, list."""
    parts = args.split(maxsplit=1) if args else []
    sub = parts[0].lower() if parts else ""

    if sub == "dismiss":
        await _alert_dismiss(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "resolve":
        await _alert_resolve(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "mute":
        await _alert_mute(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "unmute":
        await _alert_unmute(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "list":
        await _alert_list(runtime, console)
    else:
        console.print("[yellow]Usage: /alert <dismiss|resolve|mute|unmute|list> [pattern] [duration][/yellow]")
        console.print("  dismiss <pattern> [seconds]  — Suppress for duration (default 4h)")
        console.print("  resolve <pattern>            — Suppress until clean period elapses")
        console.print("  mute <pattern>               — Suppress indefinitely")
        console.print("  unmute <pattern>              — Remove indefinite suppression")
        console.print("  list                          — Show all suppressed alerts")


async def _alert_dismiss(
    runtime: ProbOSRuntime, console: Console, args: str,
) -> None:
    bas = getattr(runtime, "bridge_alerts", None)
    if not bas:
        console.print("[red]Bridge alerts not enabled.[/red]")
        return

    parts = args.split()
    if not parts:
        console.print("[yellow]Usage: /alert dismiss <pattern> [duration_seconds][/yellow]")
        return

    pattern = parts[0]
    duration = float(parts[1]) if len(parts) > 1 else None

    keys = bas.find_matching_keys(pattern)
    if not keys:
        # No existing key — dismiss the pattern as-is (pre-emptive dismiss)
        bas.dismiss_alert(pattern, duration)
        console.print(f"[green]Dismissed:[/green] {pattern}")
        await _post_ack(runtime, f"alert dismissed: {pattern}")
        return

    if len(keys) == 1:
        bas.dismiss_alert(keys[0], duration)
        console.print(f"[green]Dismissed:[/green] {keys[0]}")
        await _post_ack(runtime, f"alert dismissed: {keys[0]}")
    else:
        console.print(f"[yellow]Ambiguous pattern '{pattern}' matches {len(keys)} keys:[/yellow]")
        for k in keys:
            console.print(f"  {k}")
        console.print("[yellow]Use the exact key to dismiss.[/yellow]")


async def _alert_resolve(
    runtime: ProbOSRuntime, console: Console, args: str,
) -> None:
    bas = getattr(runtime, "bridge_alerts", None)
    if not bas:
        console.print("[red]Bridge alerts not enabled.[/red]")
        return

    pattern = args.strip()
    if not pattern:
        console.print("[yellow]Usage: /alert resolve <pattern>[/yellow]")
        return

    keys = bas.find_matching_keys(pattern)
    if not keys:
        bas.resolve_alert(pattern)
        console.print(f"[green]Resolved:[/green] {pattern}")
        await _post_ack(runtime, f"alert resolved: {pattern}")
        return

    if len(keys) == 1:
        bas.resolve_alert(keys[0])
        console.print(f"[green]Resolved:[/green] {keys[0]}")
        await _post_ack(runtime, f"alert resolved: {keys[0]}")
    else:
        console.print(f"[yellow]Ambiguous pattern '{pattern}' matches {len(keys)} keys:[/yellow]")
        for k in keys:
            console.print(f"  {k}")
        console.print("[yellow]Use the exact key to resolve.[/yellow]")


async def _alert_mute(
    runtime: ProbOSRuntime, console: Console, args: str,
) -> None:
    bas = getattr(runtime, "bridge_alerts", None)
    if not bas:
        console.print("[red]Bridge alerts not enabled.[/red]")
        return

    pattern = args.strip()
    if not pattern:
        console.print("[yellow]Usage: /alert mute <pattern>[/yellow]")
        return

    keys = bas.find_matching_keys(pattern)
    if not keys:
        bas.mute_alert(pattern)
        console.print(f"[green]Muted:[/green] {pattern}")
        await _post_ack(runtime, f"alert muted: {pattern}")
        return

    if len(keys) == 1:
        bas.mute_alert(keys[0])
        console.print(f"[green]Muted:[/green] {keys[0]}")
        await _post_ack(runtime, f"alert muted: {keys[0]}")
    else:
        console.print(f"[yellow]Ambiguous pattern '{pattern}' matches {len(keys)} keys:[/yellow]")
        for k in keys:
            console.print(f"  {k}")
        console.print("[yellow]Use the exact key to mute.[/yellow]")


async def _alert_unmute(
    runtime: ProbOSRuntime, console: Console, args: str,
) -> None:
    bas = getattr(runtime, "bridge_alerts", None)
    if not bas:
        console.print("[red]Bridge alerts not enabled.[/red]")
        return

    pattern = args.strip()
    if not pattern:
        console.print("[yellow]Usage: /alert unmute <pattern>[/yellow]")
        return

    keys = bas.find_matching_keys(pattern)
    if not keys:
        bas.unmute_alert(pattern)
        console.print(f"[green]Unmuted:[/green] {pattern}")
        await _post_ack(runtime, f"alert unmuted: {pattern}")
        return

    if len(keys) == 1:
        bas.unmute_alert(keys[0])
        console.print(f"[green]Unmuted:[/green] {keys[0]}")
        await _post_ack(runtime, f"alert unmuted: {keys[0]}")
    else:
        console.print(f"[yellow]Ambiguous pattern '{pattern}' matches {len(keys)} keys:[/yellow]")
        for k in keys:
            console.print(f"  {k}")
        console.print("[yellow]Use the exact key to unmute.[/yellow]")


async def _alert_list(runtime: ProbOSRuntime, console: Console) -> None:
    bas = getattr(runtime, "bridge_alerts", None)
    if not bas:
        console.print("[red]Bridge alerts not enabled.[/red]")
        return

    suppressed = bas.list_suppressed()
    if not suppressed:
        console.print("[dim]No suppressed alerts.[/dim]")
        return

    table = Table(title="Suppressed Alerts")
    table.add_column("Dedup Key", style="cyan")
    table.add_column("Mode", style="bold")
    table.add_column("Detail")

    for entry in suppressed:
        mode = entry["mode"]
        if mode == "dismissed":
            detail = f"{entry['remaining_seconds']:.0f}s remaining"
        elif mode == "resolved":
            detail = f"clean gap {entry['clean_gap_seconds']:.0f}s / {entry['clean_period_needed']:.0f}s needed"
        else:
            detail = "indefinite"
        table.add_row(entry["dedup_key"], mode, detail)

    console.print(table)


async def _post_ack(runtime: ProbOSRuntime, message: str) -> None:
    """Post acknowledgment to Ward Room if available."""
    wr = getattr(runtime, "ward_room", None)
    if not wr:
        return
    try:
        wr.create_post(
            channel="all hands",
            author="Ship's Computer",
            content=f"[Ship's Computer] Alert acknowledged — {message} by Captain.",
        )
    except Exception:
        logger.debug("Ward Room ack post failed (non-critical)")
