"""AD-622: Clearance grant shell commands."""
from __future__ import annotations

import logging
import math
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


def _grant_time(timestamp: float) -> str | None:
    """BF-924 (#1654): a grant time as ``MM-DD HH:MM`` (UTC), or None when the platform cannot represent it.

    ``datetime.fromtimestamp`` raises OverflowError for an infinity and OSError (Windows) or ValueError for a
    finite time outside the platform's range; one such row made ``/grant list`` raise and hide every grant.
    """
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%m-%d %H:%M")
    except (OverflowError, OSError, ValueError):
        return None


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

    # Parse duration (BF-924: a duration that is not finite, or whose expiry cannot be shown as a date, is refused;
    # "nan" became a grant until revoked, and "inf" or a huge number stored an expiry that made /grant list raise)
    try:
        duration_hours = float(duration_hours_str)
    except ValueError:
        console.print(f"[red]Invalid duration: {duration_hours_str}[/red]")
        return
    expires_at = (time.time() + duration_hours * 3600) if duration_hours > 0 else None
    if not math.isfinite(duration_hours) or (expires_at is not None and _grant_time(expires_at) is None):
        console.print(f"[red]Invalid duration: {duration_hours_str}[/red]")
        return

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


def _grant_target_callsign(runtime: "ProbOSRuntime", target_agent_id: str) -> str:
    """BF-924 (#1654): the live callsign of a grant's target, or "" when it cannot be named.

    ``_grant_issue`` stores the sovereign id, or the slot id when no identity registry is bound, so
    the target is found by its birth certificate either way. It is named by the callsign registry's
    live callsign for its agent type (a naming ceremony can replace the birth callsign).
    """
    identity_reg = getattr(runtime, "identity_registry", None)
    if identity_reg is None:
        return ""
    cert = identity_reg.get_by_uuid(target_agent_id) or identity_reg.get_by_slot(target_agent_id)
    if cert is None:
        return ""
    return runtime.callsign_registry.get_callsign(cert.agent_type) or cert.callsign


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
        # Resolve callsign for display (BF-924: no CallsignRegistry has list_all; every grant raised)
        agent_display = _grant_target_callsign(runtime, g.target_agent_id) or g.target_agent_id[:12]

        # BF-924: a time the platform cannot show degrades in its own row; the status still reads the raw value
        issued_str = _grant_time(g.issued_at) or "out of range"
        if g.expires_at:
            expires_str = _grant_time(g.expires_at) or "out of range"
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
