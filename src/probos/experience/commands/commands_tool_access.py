"""AD-423b: /tool-access shell command — Captain tool permission management.

Subcommands:
  /tool-access grant <callsign> <tool_id> <permission> [duration_hours] [reason]
  /tool-access restrict <callsign> <tool_id> <permission> [reason]
  /tool-access revoke <grant_id>
  /tool-access break-lock <tool_id> [reason]
  /tool-access list [--grants | --locks | --all]
  /tool-access check <callsign> <tool_id>
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

COMMANDS = {
    "grant": "Grant elevated tool access to an agent",
    "restrict": "Restrict tool access for an agent",
    "revoke": "Revoke a tool access grant/restriction",
    "break-lock": "Force-release a LOTO lock (Captain override)",
    "list": "List active grants and/or locks",
    "check": "Check an agent's effective permission on a tool",
}


async def cmd_tool_access(runtime: Any, console: Any, args: str) -> None:
    """Dispatch /tool-access subcommands."""
    parts = args.strip().split(None, 1)
    sub = parts[0] if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    dispatch = {
        "grant": _cmd_grant,
        "restrict": _cmd_restrict,
        "revoke": _cmd_revoke,
        "break-lock": _cmd_break_lock,
        "list": _cmd_list,
        "check": _cmd_check,
    }

    handler = dispatch.get(sub)
    if not handler:
        console.print("[bold]Usage:[/bold] /tool-access <grant|restrict|revoke|break-lock|list|check>")
        for sub_name, desc in COMMANDS.items():
            console.print(f"  {sub_name:12s} — {desc}")
        return

    await handler(runtime, console, rest)


async def _cmd_grant(runtime: Any, console: Any, args: str) -> None:
    """Grant elevated tool access: /tool-access grant <callsign> <tool_id> <permission> [hours] [reason]."""
    parts = args.strip().split()
    if len(parts) < 3:
        console.print("[red]Usage: /tool-access grant <callsign> <tool_id> <permission> [duration_hours] [reason][/red]")
        return

    callsign, tool_id, perm_str = parts[0], parts[1], parts[2]
    duration_hours = None
    reason = ""

    if len(parts) > 3:
        try:
            duration_hours = float(parts[3])
            reason = " ".join(parts[4:])
        except ValueError:
            reason = " ".join(parts[3:])

    # Resolve callsign to agent ID
    agent_id = _resolve_callsign(runtime, callsign)
    if not agent_id:
        console.print(f"[red]Unknown callsign: {callsign}[/red]")
        return

    # Validate permission
    from probos.tools.protocol import ToolPermission

    try:
        permission = ToolPermission(perm_str.lower())
    except ValueError:
        valid = ", ".join(p.value for p in ToolPermission)
        console.print(f"[red]Invalid permission: {perm_str}. Valid: {valid}[/red]")
        return

    # Validate tool exists
    store = getattr(runtime, "tool_permission_store", None)
    registry = getattr(runtime, "tool_registry", None)
    if not store or not registry:
        console.print("[red]Tool permission system not available[/red]")
        return

    if not registry.get(tool_id):
        console.print(f"[red]Unknown tool: {tool_id}[/red]")
        return

    import time

    expires_at = (time.time() + duration_hours * 3600) if duration_hours else None

    grant = await store.issue_grant(
        agent_id=agent_id,
        tool_id=tool_id,
        permission=permission,
        reason=reason or "Captain grant via /tool-access",
        expires_at=expires_at,
    )
    dur_str = f" ({duration_hours}h)" if duration_hours else " (permanent)"
    console.print(f"[green]Granted {perm_str} on {tool_id} to {callsign}{dur_str}[/green]")
    console.print(f"  Grant ID: {grant.id[:12]}...")


async def _cmd_restrict(runtime: Any, console: Any, args: str) -> None:
    """Restrict tool access: /tool-access restrict <callsign> <tool_id> <permission> [reason]."""
    parts = args.strip().split()
    if len(parts) < 3:
        console.print("[red]Usage: /tool-access restrict <callsign> <tool_id> <max_permission> [reason][/red]")
        return

    callsign, tool_id, perm_str = parts[0], parts[1], parts[2]
    reason = " ".join(parts[3:])

    agent_id = _resolve_callsign(runtime, callsign)
    if not agent_id:
        console.print(f"[red]Unknown callsign: {callsign}[/red]")
        return

    from probos.tools.protocol import ToolPermission

    try:
        permission = ToolPermission(perm_str.lower())
    except ValueError:
        valid = ", ".join(p.value for p in ToolPermission)
        console.print(f"[red]Invalid permission: {perm_str}. Valid: {valid}[/red]")
        return

    store = getattr(runtime, "tool_permission_store", None)
    if not store:
        console.print("[red]Tool permission system not available[/red]")
        return

    grant = await store.issue_grant(
        agent_id=agent_id,
        tool_id=tool_id,
        permission=permission,
        is_restriction=True,
        reason=reason or "Captain restriction via /tool-access",
    )
    console.print(f"[yellow]Restricted {callsign} to max {perm_str} on {tool_id}[/yellow]")
    console.print(f"  Grant ID: {grant.id[:12]}...")


async def _cmd_revoke(runtime: Any, console: Any, args: str) -> None:
    """Revoke a grant: /tool-access revoke <grant_id>."""
    grant_id = args.strip()
    if not grant_id:
        console.print("[red]Usage: /tool-access revoke <grant_id>[/red]")
        return

    store = getattr(runtime, "tool_permission_store", None)
    if not store:
        console.print("[red]Tool permission system not available[/red]")
        return

    # Support partial ID match
    grants = await store.list_grants(active_only=True)
    matches = [g for g in grants if g.id.startswith(grant_id)]
    if not matches:
        console.print(f"[red]No active grant matching: {grant_id}[/red]")
        return
    if len(matches) > 1:
        console.print(f"[red]Ambiguous ID, {len(matches)} matches. Provide more characters.[/red]")
        return

    ok = await store.revoke_grant(matches[0].id)
    if ok:
        console.print(f"[green]Grant {matches[0].id[:12]}... revoked[/green]")
    else:
        console.print("[red]Failed to revoke grant[/red]")


async def _cmd_break_lock(runtime: Any, console: Any, args: str) -> None:
    """Break a LOTO lock: /tool-access break-lock <tool_id> [reason]."""
    parts = args.strip().split(None, 1)
    if not parts:
        console.print("[red]Usage: /tool-access break-lock <tool_id> [reason][/red]")
        return

    tool_id = parts[0]
    reason = parts[1] if len(parts) > 1 else "Captain break-lock"

    registry = getattr(runtime, "tool_registry", None)
    if not registry:
        console.print("[red]Tool registry not available[/red]")
        return

    ok = registry.break_lock(tool_id, reason)
    if ok:
        console.print(f"[green]Lock on {tool_id} broken[/green]")
    else:
        console.print(f"[yellow]No active lock on {tool_id}[/yellow]")


async def _cmd_list(runtime: Any, console: Any, args: str) -> None:
    """List grants and/or locks: /tool-access list [--grants|--locks|--all]."""
    flag = args.strip()
    show_grants = flag in ("", "--grants", "--all")
    show_locks = flag in ("", "--locks", "--all")

    registry = getattr(runtime, "tool_registry", None)
    store = getattr(runtime, "tool_permission_store", None)

    if show_grants and store:
        grants = await store.list_grants(active_only=True)
        if grants:
            console.print(f"[bold]Active grants/restrictions ({len(grants)}):[/bold]")
            for g in grants:
                kind = "RESTRICT" if g.is_restriction else "GRANT"
                exp = f" expires {g.expires_at:.0f}" if g.expires_at else " permanent"
                console.print(
                    f"  {g.id[:12]}  {kind:8s} {g.agent_id[:16]:16s} → {g.tool_id:20s} = {g.permission.value}{exp}"
                )
        else:
            console.print("[dim]No active grants[/dim]")

    if show_locks and registry:
        locks = registry.list_locks()
        if locks:
            console.print(f"[bold]Active LOTO locks ({len(locks)}):[/bold]")
            for lk in locks:
                console.print(f"  {lk['tool_id']:20s} held by {lk['holder']} ({lk.get('reason', '')})")
        else:
            console.print("[dim]No active locks[/dim]")


async def _cmd_check(runtime: Any, console: Any, args: str) -> None:
    """Check effective permission: /tool-access check <callsign> <tool_id>."""
    parts = args.strip().split()
    if len(parts) < 2:
        console.print("[red]Usage: /tool-access check <callsign> <tool_id>[/red]")
        return

    callsign, tool_id = parts[0], parts[1]
    agent_id = _resolve_callsign(runtime, callsign)
    if not agent_id:
        console.print(f"[red]Unknown callsign: {callsign}[/red]")
        return

    registry = getattr(runtime, "tool_registry", None)
    if not registry:
        console.print("[red]Tool registry not available[/red]")
        return

    # Get agent context — resolve agent_type for department lookup
    dept = None
    agent = runtime.registry.get(agent_id) if hasattr(runtime, "registry") else None
    if agent:
        from probos.cognitive.standing_orders import get_department

        dept = get_department(agent.agent_type)

    trust = 0.5
    if agent and hasattr(runtime, "trust_network"):
        trust = runtime.trust_network.get_trust(agent_id)

    from probos.crew_profile import Rank

    rank = Rank.from_trust(trust)

    perm = registry.resolve_permission(
        agent_id,
        tool_id,
        agent_department=dept,
        agent_rank=rank.value,
        agent_types=[agent.agent_type] if agent else None,
    )
    console.print(f"[bold]{callsign}[/bold] on [bold]{tool_id}[/bold]: {perm.value}")


def _resolve_callsign(runtime: Any, callsign: str) -> str | None:
    """Resolve a callsign to agent ID."""
    cr = getattr(runtime, "callsign_registry", None)
    if cr:
        agent_id = cr.resolve(callsign)
        if agent_id:
            return agent_id
    # Fallback: try as direct agent_type
    if hasattr(runtime, "registry"):
        agent = runtime.registry.get(callsign)
        if agent:
            return agent.id
    return None
