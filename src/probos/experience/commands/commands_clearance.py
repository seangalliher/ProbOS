"""AD-622: Clearance grant shell commands."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_grant(runtime: "ProbOSRuntime", console: Console, args: str) -> None:
    """Grant management commands: issue, revoke, list."""
    parts = args.split(maxsplit=1) if args else []
    sub = parts[0].lower() if parts else ""

    if sub == "issue":
        await _grant_issue(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "revoke":
        await _grant_revoke(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "list":
        await _grant_list(runtime, console, parts[1] if len(parts) > 1 else "")
    else:
        console.print("[yellow]Usage: /grant <issue|revoke|list> [...][/yellow]")
        console.print("  issue <callsign> <tier> [scope] [duration_hours] [reason...]")
        console.print("    tier: basic, enhanced, full, oracle")
        console.print("    scope: general (default), project:<name>, investigation:<id>")
        console.print("    duration_hours: 0 = until revoked (default)")
        console.print("  revoke <grant_id>")
        console.print("  list [--all]   — Show active grants (--all includes revoked/expired)")


async def _grant_issue(runtime: "ProbOSRuntime", console: Console, args: str) -> None:
    """Issue a clearance grant: <callsign> <tier> [scope] [duration_hours] [reason...]."""
    parts = args.split() if args else []
    if len(parts) < 2:
        console.print("[red]Usage: /grant issue <callsign> <tier> [scope] [duration_hours] [reason...][/red]")
        return

    callsign_input = parts[0]
    tier_str = parts[1].lower()
    scope = parts[2] if len(parts) > 2 else "general"
    duration_hours_str = parts[3] if len(parts) > 3 else "0"
    reason = " ".join(parts[4:]) if len(parts) > 4 else ""

    store = getattr(runtime, 'clearance_grant_store', None)
    if not store:
        console.print("[red]Clearance grant store not available.[/red]")
        return

    # Resolve callsign to agent
    resolved = runtime.callsign_registry.resolve(callsign_input)
    if resolved is None:
        console.print(f"[red]Unknown crew member: @{callsign_input}[/red]")
        return
    if resolved["agent_id"] is None:
        console.print(f"[yellow]{resolved['callsign']} is not currently on duty.[/yellow]")
        return

    # Resolve sovereign ID for grant target
    agent_id = resolved["agent_id"]
    identity_reg = getattr(runtime, 'identity_registry', None)
    if identity_reg:
        from probos.cognitive.episodic import resolve_sovereign_id_from_slot
        agent_id = resolve_sovereign_id_from_slot(agent_id, identity_reg)

    # Validate tier
    from probos.earned_agency import RecallTier
    try:
        recall_tier = RecallTier(tier_str)
    except ValueError:
        valid = ", ".join(t.value for t in RecallTier)
        console.print(f"[red]Invalid tier '{tier_str}'. Valid: {valid}[/red]")
        return

    # Parse duration
    try:
        duration_hours = float(duration_hours_str)
    except ValueError:
        console.print(f"[red]Invalid duration: {duration_hours_str}[/red]")
        return
    expires_at = (time.time() + duration_hours * 3600) if duration_hours > 0 else None

    grant = await store.issue_grant(
        target_agent_id=agent_id,
        recall_tier=recall_tier,
        scope=scope,
        reason=reason,
        issued_by="captain",
        expires_at=expires_at,
    )
    exp_str = f"{duration_hours:.0f}h" if expires_at else "until revoked"
    console.print(
        f"[green]Grant issued:[/green] {resolved['callsign']} → "
        f"[bold]{recall_tier.value}[/bold] (scope={scope}, expires={exp_str})"
    )
    console.print(f"  Grant ID: [dim]{grant.id}[/dim]")


async def _grant_revoke(runtime: "ProbOSRuntime", console: Console, args: str) -> None:
    """Revoke a grant by ID (prefix match)."""
    prefix = args.strip() if args else ""
    if not prefix:
        console.print("[red]Usage: /grant revoke <grant_id_prefix>[/red]")
        return

    store = getattr(runtime, 'clearance_grant_store', None)
    if not store:
        console.print("[red]Clearance grant store not available.[/red]")
        return

    # Prefix match — load all grants and find the one matching
    all_grants = await store.list_grants(active_only=False)
    matches = [g for g in all_grants if g.id.startswith(prefix)]

    if not matches:
        console.print(f"[red]No grant found matching '{prefix}'[/red]")
        return
    if len(matches) > 1:
        console.print(f"[red]Ambiguous prefix '{prefix}' — matches {len(matches)} grants. Be more specific.[/red]")
        return

    grant = matches[0]
    if grant.revoked:
        console.print(f"[yellow]Grant {grant.id[:8]} is already revoked.[/yellow]")
        return

    ok = await store.revoke_grant(grant.id)
    if ok:
        console.print(f"[green]Grant {grant.id[:8]} revoked.[/green] ({grant.target_agent_id[:12]} {grant.recall_tier.value})")
    else:
        console.print(f"[red]Failed to revoke grant {grant.id[:8]}.[/red]")


async def _grant_list(runtime: "ProbOSRuntime", console: Console, args: str) -> None:
    """List clearance grants."""
    show_all = "--all" in (args or "")

    store = getattr(runtime, 'clearance_grant_store', None)
    if not store:
        console.print("[red]Clearance grant store not available.[/red]")
        return

    grants = await store.list_grants(active_only=not show_all)
    if not grants:
        label = "grants" if show_all else "active grants"
        console.print(f"[dim]No {label}.[/dim]")
        return

    table = Table(title="Clearance Grants")
    table.add_column("ID", style="dim", width=8)
    table.add_column("Agent", style="cyan")
    table.add_column("Tier", style="bold")
    table.add_column("Scope")
    table.add_column("Issued By")
    table.add_column("Issued")
    table.add_column("Expires")
    table.add_column("Status")

    now = time.time()
    for g in grants:
        # Resolve callsign for display
        agent_display = g.target_agent_id[:12]
        if hasattr(runtime, 'callsign_registry'):
            for agent in runtime.callsign_registry.list_all():
                if agent.get("agent_id") == g.target_agent_id:
                    agent_display = agent.get("callsign", agent_display)
                    break

        issued_str = datetime.fromtimestamp(g.issued_at, tz=timezone.utc).strftime("%m-%d %H:%M")
        if g.expires_at:
            expires_str = datetime.fromtimestamp(g.expires_at, tz=timezone.utc).strftime("%m-%d %H:%M")
        else:
            expires_str = "—"

        if g.revoked:
            status = "[red]Revoked[/red]"
        elif g.expires_at and g.expires_at <= now:
            status = "[yellow]Expired[/yellow]"
        else:
            status = "[green]Active[/green]"

        table.add_row(
            g.id[:8], agent_display, g.recall_tier.value,
            g.scope, g.issued_by, issued_str, expires_str, status,
        )

    console.print(table)
