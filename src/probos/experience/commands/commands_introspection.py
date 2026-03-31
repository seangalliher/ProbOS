"""Introspection and diagnostic commands for ProbOSShell."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from rich.console import Console

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_weights(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /weights command."""
    from probos.experience import panels

    weights = runtime.hebbian_router.all_weights_typed()
    console.print(panels.render_weight_table(weights))


async def cmd_gossip(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /gossip command."""
    from probos.experience import panels

    view = runtime.gossip.get_view()
    console.print(panels.render_gossip_panel(view))


async def cmd_designed(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /designed command."""
    from probos.experience import panels

    if runtime.self_mod_pipeline:
        status = runtime.self_mod_pipeline.designed_agent_status()
        if runtime.behavioral_monitor:
            status["behavioral"] = runtime.behavioral_monitor.get_status()
        qa_reports = getattr(runtime, "_qa_reports", None) or None
        console.print(panels.render_designed_panel(status, qa_reports=qa_reports))
    else:
        console.print("[yellow]Self-modification not enabled[/yellow]")


async def cmd_qa(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /qa command."""
    from probos.experience.qa_panel import render_qa_panel, render_qa_detail

    qa_reports = getattr(runtime, "_qa_reports", {})
    if not qa_reports:
        console.print("[dim]No QA results yet.[/dim]")
        return

    if args:
        report = qa_reports.get(args)
        if report is None:
            console.print(f"[red]No QA report for agent type: {args}[/red]")
            return
        console.print(render_qa_detail(args, report, runtime.trust_network))
    else:
        console.print(render_qa_panel(qa_reports, runtime.trust_network))


async def cmd_prune(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /prune command."""
    if not args:
        console.print("[yellow]Usage: /prune <agent_id>[/yellow]")
        return

    agent_id = args.strip()
    agent = runtime.registry.get(agent_id)
    if agent is None:
        console.print(f"[red]Agent not found: {agent_id}[/red]")
        return

    console.print(
        f"[bold yellow]Remove agent {agent_id} permanently? "
        f"This cannot be undone. [y/n][/bold yellow]"
    )
    response = await asyncio.get_running_loop().run_in_executor(
        None, lambda: input("  Confirm: ").strip().lower()
    )
    if response not in ("y", "yes"):
        console.print("[dim]Prune cancelled.[/dim]")
        return

    removed = await runtime.prune_agent(agent_id)
    if removed:
        console.print(f"[green]Agent {agent_id} pruned.[/green]")
    else:
        console.print(f"[red]Failed to prune agent {agent_id}.[/red]")


async def cmd_log(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /log command."""
    from probos.experience import panels

    category = args if args else None
    events = await runtime.event_log.query(category=category, limit=20)
    console.print(panels.render_event_log_table(events))


async def cmd_attention(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /attention command."""
    from probos.experience import panels

    queue = runtime.attention.get_queue_snapshot()
    focus = runtime.attention.current_focus
    console.print(panels.render_attention_panel(
        queue, focus, focus_history=runtime.attention.focus_history,
    ))


async def cmd_cache(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /cache command."""
    from probos.experience import panels

    cache = runtime.workflow_cache
    console.print(panels.render_workflow_cache_panel(
        cache.entries, cache.size,
    ))
