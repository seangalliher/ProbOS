"""Directive management commands for ProbOSShell."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_orders(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Show Standing Orders hierarchy and file summaries."""
    from probos.cognitive.standing_orders import _DEFAULT_ORDERS_DIR, _load_file

    orders_dir = Path(_DEFAULT_ORDERS_DIR)

    # Check if directory exists
    if not orders_dir.exists():
        console.print("[yellow]No standing orders directory found.[/yellow]")
        return

    # Find all .md files
    md_files = list(orders_dir.glob("*.md"))
    if not md_files:
        console.print("[dim]No standing orders configured.[/dim]")
        return

    # Create table
    table = Table(show_header=True, header_style="bold")
    table.add_column("Tier", style="", no_wrap=True)
    table.add_column("File", style="cyan", no_wrap=True)
    table.add_column("Summary", style="")
    table.add_column("Size", justify="right", style="dim")

    # Process each file
    for file_path in sorted(md_files):
        filename = file_path.name
        basename = file_path.stem

        # Determine tier and styling
        if filename == "federation.md":
            tier = "Federation Constitution"
            tier_style = "red"
        elif filename == "ship.md":
            tier = "Ship Standing Orders"
            tier_style = "blue"
        elif basename in ["engineering", "medical", "science", "security"]:
            tier = f"Department: {basename}"
            tier_style = "yellow"
        else:
            tier = f"Agent: {basename}"
            tier_style = "green"

        # Get file size
        try:
            file_size = len(file_path.read_text(encoding='utf-8'))
            size_str = str(file_size)
        except Exception:
            file_size = 0
            size_str = "0"

        # Read summary from file
        try:
            content = _load_file(file_path)
            # Find first non-empty line as summary
            summary = ""
            for line in content.split('\n'):
                line = line.strip()
                if line and not line.startswith('#'):
                    summary = line
                    break

            # Truncate if too long
            if len(summary) > 60:
                summary = summary[:57] + "..."

            if not summary:
                summary = "[dim](no summary)[/dim]"

        except Exception:
            summary = f"[red]Error: {filename}[/red]"

        # Add row to table
        tier_text = Text(tier, style=tier_style)
        table.add_row(tier_text, basename, summary, size_str)

    console.print(table)


async def cmd_order(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Issue a Captain's order to an agent type."""
    if not args:
        console.print("[yellow]Usage: /order <agent_type> <instruction text>[/yellow]")
        return
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        console.print("[yellow]Usage: /order <agent_type> <instruction text>[/yellow]")
        return
    target = parts[0]
    content = parts[1]
    store = runtime.directive_store
    if not store:
        console.print("[red]DirectiveStore not available[/red]")
        return
    from probos.directive_store import DirectiveType
    from probos.crew_profile import Rank
    from probos.cognitive.standing_orders import get_department, clear_cache
    # AD-429e: Prefer ontology, fall back to legacy dict
    ont = getattr(runtime, 'ontology', None) if hasattr(runtime, 'ontology') else None
    directive, reason = store.create_directive(
        issuer_type="captain",
        issuer_department=None,
        issuer_rank=Rank.SENIOR,  # Captain has highest authority
        target_agent_type=target,
        target_department=(ont.get_agent_department(target) if ont else None) or get_department(target),
        directive_type=DirectiveType.CAPTAIN_ORDER,
        content=content,
        authority=1.0,
        priority=5,  # Captain orders are highest priority
    )
    if directive:
        clear_cache()  # Invalidate composed instructions
        dept = (ont.get_agent_department(target) if ont else None) or get_department(target)
        scope = f"{target}" + (f" ({dept})" if dept else "") + (" [all agents]" if target == "*" else "")
        console.print(f"\n[bold green]Captain's Order Issued[/bold green]")
        console.print(f"  [green]Target:[/green]    {scope}")
        console.print(f"  [green]Directive:[/green] {content}")
        console.print(f"  [green]Priority:[/green]  {directive.priority}/5 (highest)")
        console.print(f"  [green]Status:[/green]    Active — composing into next LLM call")
        console.print(f"  [dim]ID: {directive.id} | /directives to verify[/dim]")
        # Crew acknowledgment — naval chain of command pattern
        console.print()
        if target == "*":
            # Broadcast: each department chief confirms for their crew
            dept_counts: dict[str, list[str]] = {}
            for pool in runtime.pools.values():
                d = (ont.get_agent_department(pool.agent_type) if ont else None) or get_department(pool.agent_type)
                if d:
                    count = len(pool.healthy_agents)
                    if count > 0:
                        dept_counts.setdefault(d, []).append(pool.agent_type)
            for d, agent_types in dept_counts.items():
                chief_type = agent_types[0]
                chief_callsign = get_callsign(chief_type)
                total = sum(
                    len(p.healthy_agents)
                    for p in runtime.pools.values()
                    if p.agent_type in agent_types
                )
                role = d.title()
                console.print(
                    f'  [bold cyan]{chief_callsign}[/bold cyan] [dim]({role}, {total} crew)[/dim]: '
                    f'[italic]"Aye Captain. Orders acknowledged, all {d} crew confirmed."[/italic]'
                )
        else:
            # Specific agent type
            agent_count = sum(
                len(p.healthy_agents)
                for p in runtime.pools.values()
                if p.agent_type == target
            )
            callsign = get_callsign(target)
            if agent_count <= 1:
                # Single crew member — personal acknowledgment
                console.print(
                    f'  [bold cyan]{callsign}:[/bold cyan] '
                    f'[italic]"Aye Captain. New standing orders acknowledged."[/italic]'
                )
            else:
                # Multiple instances — chief confirms for the group
                role = (dept or target).replace("_", " ").title()
                console.print(
                    f'  [bold cyan]{callsign}[/bold cyan] [dim](Chief {role}, {agent_count} crew)[/dim]: '
                    f'[italic]"Aye Captain. Orders passed down, {agent_count} crew confirmed."[/italic]'
                )
        console.print()  # trailing blank line
        # Warn if other active directives exist for this target
        existing = store.get_active_for_agent(target, dept)
        other = [d for d in existing if d.id != directive.id]
        if other:
            console.print(
                f"  [yellow]Note: {target} has {len(other)} other active directive(s). "
                f"Use /directives {target} to review.[/yellow]\n"
            )
    else:
        if "Duplicate" in reason:
            console.print(f"[yellow]{reason}[/yellow]")
        else:
            console.print(f"[red]Authorization failed: {reason}[/red]")


async def cmd_directives(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Show active directives, optionally filtered by agent type."""
    store = runtime.directive_store
    if not store:
        console.print("[red]DirectiveStore not available[/red]")
        return
    directives = store.all_directives(include_inactive=False)
    if args:
        from probos.cognitive.standing_orders import get_department
        # AD-429e: Prefer ontology, fall back to legacy dict
        ont = getattr(runtime, 'ontology', None) if hasattr(runtime, 'ontology') else None
        dept = (ont.get_agent_department(args) if ont else None) or get_department(args)
        directives = [
            d for d in directives
            if d.target_agent_type in (args, "*") and
               (d.target_department is None or d.target_department == dept)
        ]
    if not directives:
        console.print("[dim]No active directives[/dim]")
        return
    for d in directives:
        status_color = "green" if d.status.value == "active" else "yellow"
        dtype = d.directive_type.value.replace("_", " ").title()
        target = d.target_agent_type
        if d.target_department:
            target += f" ({d.target_department})"
        console.print(
            f"[{status_color}][{dtype}][/{status_color}] -> {target}: {d.content}"
        )
        console.print(f"  [dim]by {d.issued_by} | priority {d.priority} | {d.id[:8]}[/dim]")


async def cmd_revoke(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Revoke (countermand) a directive by ID."""
    if not args:
        console.print("[yellow]Usage: /revoke <directive_id>[/yellow]")
        return
    store = runtime.directive_store
    if not store:
        console.print("[red]DirectiveStore not available[/red]")
        return
    directive_id = args.strip()
    # Show what we're revoking
    directive = store.get(directive_id)
    if not directive:
        console.print(f"[red]Directive not found: {directive_id}[/red]")
        return
    if directive.status.value not in ("active", "pending_approval"):
        console.print(f"[yellow]Directive {directive_id[:8]} is already {directive.status.value}[/yellow]")
        return
    result = store.revoke(directive.id, "captain")
    if result:
        from probos.cognitive.standing_orders import clear_cache
        clear_cache()
        callsign = get_callsign(directive.target_agent_type)
        console.print(f"\n[bold yellow]Order Revoked[/bold yellow]")
        console.print(f"  [yellow]Target:[/yellow]    {directive.target_agent_type}")
        console.print(f"  [yellow]Was:[/yellow]       {directive.content}")
        console.print(f"  [dim]ID: {directive.id[:8]} | belayed by Captain[/dim]")
        console.print(
            f'\n  [bold cyan]{callsign}:[/bold cyan] '
            f'[italic]"Aye Captain. Previous orders belayed."[/italic]\n'
        )


async def cmd_amend(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Amend (FRAGO) an existing directive — replace its content."""
    if not args:
        console.print("[yellow]Usage: /amend <directive_id> <new instruction text>[/yellow]")
        return
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        console.print("[yellow]Usage: /amend <directive_id> <new instruction text>[/yellow]")
        return
    directive_id = parts[0]
    new_content = parts[1]
    store = runtime.directive_store
    if not store:
        console.print("[red]DirectiveStore not available[/red]")
        return
    # Show what we're amending
    old = store.get(directive_id)
    if not old:
        console.print(f"[red]Directive not found: {directive_id}[/red]")
        return
    amended = store.amend(directive_id, new_content, "captain")
    if amended:
        from probos.cognitive.standing_orders import clear_cache
        clear_cache()
        callsign = get_callsign(amended.target_agent_type)
        console.print(f"\n[bold green]Order Amended (FRAGO)[/bold green]")
        console.print(f"  [green]Target:[/green]    {amended.target_agent_type}")
        console.print(f"  [dim]Was:[/dim]       {old.content}")
        console.print(f"  [green]Now:[/green]       {new_content}")
        console.print(f"  [dim]ID: {amended.id[:8]} | amended by Captain[/dim]")
        console.print(
            f'\n  [bold cyan]{callsign}:[/bold cyan] '
            f'[italic]"Aye Captain. Amended orders acknowledged."[/italic]\n'
        )
    else:
        console.print(f"[red]Cannot amend — directive {directive_id[:8]} is not active[/red]")


async def cmd_imports(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """List, add, or remove allowed imports for self-mod."""
    config = runtime.config.self_mod
    parts = args.split(maxsplit=1)
    sub = parts[0].lower() if parts else ""

    if sub == "add" and len(parts) > 1:
        name = parts[1].strip()
        if name in config.allowed_imports:
            console.print(f"[dim]{name} is already in the whitelist[/dim]")
        else:
            config.allowed_imports.append(name)
            if runtime.self_mod_pipeline:
                runtime.self_mod_pipeline._validator._allowed_imports.add(name)
            console.print(f"[green]Added '{name}' to allowed imports[/green]")
    elif sub == "remove" and len(parts) > 1:
        name = parts[1].strip()
        if name not in config.allowed_imports:
            console.print(f"[dim]{name} is not in the whitelist[/dim]")
        else:
            config.allowed_imports.remove(name)
            if runtime.self_mod_pipeline:
                runtime.self_mod_pipeline._validator._allowed_imports.discard(name)
            console.print(f"[yellow]Removed '{name}' from allowed imports[/yellow]")
    else:
        # List current imports
        imports = sorted(config.allowed_imports)
        console.print(f"[bold]Allowed imports ({len(imports)}):[/bold]")
        # Group into lines of 6
        for i in range(0, len(imports), 6):
            chunk = ", ".join(imports[i:i + 6])
            console.print(f"  {chunk}")


def get_callsign(agent_type: str) -> str:
    """Look up an agent type's callsign from seed crew profile."""
    try:
        from probos.crew_profile import load_seed_profile
        seed = load_seed_profile(agent_type)
        if seed and seed.get("callsign"):
            return seed["callsign"]
    except Exception:
        pass
    return agent_type.replace("_", " ").title()
