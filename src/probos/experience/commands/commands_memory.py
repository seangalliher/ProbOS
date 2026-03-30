"""Memory and episodic recall commands for ProbOSShell."""
from __future__ import annotations

import logging
from typing import Any

from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)


async def cmd_memory(runtime: Any, console: Console, args: str) -> None:
    """Handle /memory command."""
    from probos.experience import panels

    snapshot = runtime.working_memory.assemble(
        registry=runtime.registry,
        trust_network=runtime.trust_network,
        hebbian_router=runtime.hebbian_router,
    )
    console.print(panels.render_working_memory_panel(snapshot))


async def cmd_history(runtime: Any, console: Console, args: str) -> None:
    """Handle /history command."""
    mem = runtime.episodic_memory
    if not mem:
        console.print("[yellow]Episodic memory is not enabled.[/yellow]")
        return
    episodes = await mem.recent(k=10)
    if not episodes:
        console.print("[dim]No episodes recorded yet.[/dim]")
        return
    from datetime import datetime
    table = Table(title="Recent Episodes")
    table.add_column("Time", style="dim")
    table.add_column("Input")
    table.add_column("Intents", justify="right")
    table.add_column("Success", justify="right")
    for ep in episodes:
        ts = datetime.fromtimestamp(ep.timestamp).strftime("%H:%M:%S") if ep.timestamp else "?"
        total = len(ep.outcomes)
        ok = sum(1 for o in ep.outcomes if o.get("success"))
        rate = f"{ok}/{total}" if total else "-"
        intents = ", ".join(o.get("intent", "?") for o in ep.outcomes) or "-"
        table.add_row(ts, ep.user_input[:60], intents, rate)
    console.print(table)


async def cmd_recall(runtime: Any, console: Console, args: str) -> None:
    """Handle /recall command."""
    mem = runtime.episodic_memory
    if not mem:
        console.print("[yellow]Episodic memory is not enabled.[/yellow]")
        return
    if not args:
        console.print("[yellow]Usage: /recall <query>[/yellow]")
        return
    episodes = await mem.recall(args, k=3)
    if not episodes:
        console.print("[dim]No similar episodes found.[/dim]")
        return
    from datetime import datetime
    table = Table(title=f"Recall: {args}")
    table.add_column("Time", style="dim")
    table.add_column("Input")
    table.add_column("Intents")
    table.add_column("Success", justify="right")
    for ep in episodes:
        ts = datetime.fromtimestamp(ep.timestamp).strftime("%H:%M:%S") if ep.timestamp else "?"
        total = len(ep.outcomes)
        ok = sum(1 for o in ep.outcomes if o.get("success"))
        rate = f"{ok}/{total}" if total else "-"
        intents = ", ".join(o.get("intent", "?") for o in ep.outcomes) or "-"
        table.add_row(ts, ep.user_input[:60], intents, rate)
    console.print(table)


async def cmd_dream(runtime: Any, console: Console, args: str) -> None:
    """Handle /dream command."""
    from probos.experience import panels

    scheduler = runtime.dream_scheduler
    if not scheduler:
        console.print("[yellow]Dreaming is not enabled (no episodic memory).[/yellow]")
        return
    if args.strip().lower() == "now":
        console.print("[dim]Triggering dream cycle...[/dim]")
        report = await scheduler.force_dream()
        console.print(panels.render_dream_panel(report))
    else:
        console.print(panels.render_dream_panel(scheduler.last_dream_report))
