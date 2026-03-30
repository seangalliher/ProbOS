"""Autonomous operations commands for ProbOSShell (AD-471)."""
from __future__ import annotations

import logging
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)


async def cmd_conn(runtime: Any, console: Console, args: str) -> None:
    """Manage the conn — temporary authority delegation."""
    rt = runtime
    if not rt.conn_manager:
        console.print("[red]Conn manager not initialized[/red]")
        return

    parts = args.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else "status"

    if subcmd == "status":
        status = rt.conn_manager.get_status()
        if not status["active"]:
            console.print("[dim]No one has the conn. Captain has command.[/dim]")
        else:
            console.print(f"[bold cyan]{status['holder']}[/bold cyan] has the conn")
            console.print(f"  Duration: {status['duration_seconds']:.0f}s")
            console.print(f"  Actions: {status['actions_taken']}")
            console.print(f"  Escalations: {status['escalation_count']}")
            console.print(f"  Can approve builds: {status['can_approve_builds']}")

    elif subcmd == "return":
        if not rt.conn_manager.is_active:
            console.print("[dim]No active conn to return.[/dim]")
            return
        result = rt.conn_manager.return_conn()
        # Expire Night Orders when Captain returns
        if hasattr(rt, '_night_orders_mgr') and rt._night_orders_mgr:
            rt._night_orders_mgr.expire()
        # Ward Room announcement
        if rt.ward_room:
            await rt.ward_room.post_message(
                channel_id="all-hands",
                author_id="system",
                author_callsign="Bridge",
                content=f"Captain on the bridge. The conn has been returned from {result['holder']}. {result['actions_taken']} action(s) taken, {result['escalation_count']} escalation(s).",
            )
        console.print(f"[bold green]Conn returned from {result['holder']}[/bold green]")
        console.print(f"  Duration: {result['duration_seconds']:.0f}s")
        console.print(f"  Actions taken: {result['actions_taken']}")

    elif subcmd == "log":
        log = rt.conn_manager.get_conn_log()
        if not log:
            console.print("[dim]No conn log entries.[/dim]")
            return
        import time as _time
        for entry in log[-20:]:  # Last 20 entries
            ts = _time.strftime("%H:%M:%S", _time.localtime(entry.get("timestamp", 0)))
            console.print(f"  [{ts}] {entry.get('action', '?')}: {entry}")

    else:
        # Interpret as callsign — grant conn
        callsign = args.strip()
        if not callsign:
            console.print("[red]Usage: /conn <callsign> | /conn return | /conn status | /conn log[/red]")
            return

        # Find agent by callsign
        target_agent = None
        for agent in rt.registry.all():
            if hasattr(agent, 'callsign') and agent.callsign and agent.callsign.lower() == callsign.lower():
                target_agent = agent
                break

        if not target_agent:
            console.print(f"[red]No agent found with callsign '{callsign}'[/red]")
            return

        # Check qualification
        if not rt.is_conn_qualified(target_agent.id):
            console.print(f"[red]{callsign} is not qualified for the conn (requires COMMANDER+ rank, bridge/chief post)[/red]")
            return

        # Grant conn
        rt.conn_manager.grant_conn(
            agent_id=target_agent.id,
            agent_type=target_agent.agent_type,
            callsign=target_agent.callsign,
            reason="Captain delegation",
        )

        # Ward Room announcement
        if rt.ward_room:
            await rt.ward_room.post_message(
                channel_id="all-hands",
                author_id="system",
                author_callsign="Bridge",
                content=f"{target_agent.callsign}, you have the conn. Captain is going offline.",
            )
        console.print(f"[bold cyan]{target_agent.callsign}[/bold cyan] has the conn.")


async def cmd_night_orders(runtime: Any, console: Console, args: str) -> None:
    """Set Night Orders — Captain-offline guidance."""
    rt = runtime
    if not hasattr(rt, '_night_orders_mgr') or not rt._night_orders_mgr:
        console.print("[red]Night Orders manager not initialized[/red]")
        return

    from probos.watch_rotation import NIGHT_ORDER_TEMPLATES

    parts = args.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else "status"

    if subcmd == "status":
        status = rt._night_orders_mgr.get_status()
        if not status["active"]:
            console.print("[dim]No active Night Orders.[/dim]")
        else:
            console.print("[bold]Night Orders active[/bold]")
            console.print(f"  Template: {status['template'] or 'custom'}")
            console.print(f"  Remaining: {status['remaining_hours']}h")
            console.print(f"  Instructions: {status['instructions_count']}")
            console.print(f"  Invoked: {status['invoked_count']} times")
            console.print(f"  Builds: {'allowed' if status['can_approve_builds'] else 'not allowed'}")
            console.print(f"  Alert boundary: {status['alert_boundary']}")

    elif subcmd == "expire":
        result = rt._night_orders_mgr.expire()
        console.print("[green]Night Orders expired.[/green]")
        if result.get("invoked_count", 0) > 0:
            console.print(f"  {result['invoked_count']} instruction(s) were invoked.")

    elif subcmd in NIGHT_ORDER_TEMPLATES:
        # Template-based Night Orders
        template = subcmd
        ttl = 8.0
        if len(parts) > 1:
            try:
                ttl = float(parts[1])
            except ValueError:
                pass
        orders = rt._night_orders_mgr.set_night_orders(
            instructions=[],
            ttl_hours=ttl,
            template=template,
        )
        # Apply to conn manager if active
        if rt.conn_manager and rt.conn_manager.is_active:
            rt.conn_manager.state.can_approve_builds = orders.can_approve_builds
        tpl = NIGHT_ORDER_TEMPLATES[template]
        console.print(f"[bold]Night Orders set: {tpl['name']}[/bold]")
        console.print(f"  {tpl['description']}")
        console.print(f"  TTL: {ttl}h")

    else:
        # Custom Night Orders — treat entire arg as instruction
        if not args.strip():
            console.print("[red]Usage: /night-orders <template>|expire|status[/red]")
            console.print("  Templates: maintenance, build, quiet")
            return
        rt._night_orders_mgr.set_night_orders(
            instructions=[args.strip()],
            ttl_hours=8.0,
        )
        console.print("[bold]Night Orders set (custom, 8h TTL)[/bold]")


async def cmd_watch(runtime: Any, console: Console, args: str) -> None:
    """Show watch bill status."""
    rt = runtime
    if not hasattr(rt, 'watch_manager') or not rt.watch_manager:
        console.print("[dim]Watch manager not initialized.[/dim]")
        return
    status = rt.watch_manager.get_watch_status()
    console.print(f"[bold]Current Watch:[/bold] {status['current_watch'].upper()}")
    console.print(f"  Time-appropriate: {status['time_appropriate_watch'].upper()}")
    console.print(f"  On duty: {len(status['on_duty'])} agent(s)")
    console.print(f"  Standing tasks: {status['standing_tasks_count']}")
    console.print(f"  Active orders: {status['active_orders_count']}")
    console.print()
    for watch, agents in status['roster'].items():
        count = len(agents)
        marker = " ◄" if watch == status['current_watch'] else ""
        console.print(f"  {watch.upper()}: {count} agent(s){marker}")
