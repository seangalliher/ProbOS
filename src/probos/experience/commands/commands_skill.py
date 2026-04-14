"""AD-596d: /skill shell command — cognitive skill management."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_skill(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """/skill — cognitive skill catalog management.

    Subcommands: list, discover, import, info, enrich, remove, validate.
    """
    parts = args.split(maxsplit=1) if args else []
    sub = parts[0].lower() if parts else ""

    if sub == "list":
        await _skill_list(runtime, console)
    elif sub == "discover":
        await _skill_discover(runtime, console)
    elif sub == "import":
        await _skill_import(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "info":
        await _skill_info(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "enrich":
        await _skill_enrich(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "remove":
        await _skill_remove(runtime, console, parts[1] if len(parts) > 1 else "")
    elif sub == "validate":
        await _skill_validate(runtime, console, parts[1] if len(parts) > 1 else "")
    else:
        console.print("[yellow]Usage: /skill <list|discover|import|info|enrich|remove|validate>[/yellow]")
        console.print("  list                               — List all cognitive skills")
        console.print("  discover                           — Show pip-installed skills available for import")
        console.print("  import <path>                      — Import a skill from a directory path")
        console.print("  info <name>                        — Show full skill details")
        console.print("  enrich <name> --dept <d> --intents <i1 i2>  — Add ProbOS metadata")
        console.print("  remove <name>                      — Remove an external skill")
        console.print("  validate [name]                    — Validate skills (all or specific)")


async def _skill_list(runtime: ProbOSRuntime, console: Console) -> None:
    catalog = getattr(runtime, "cognitive_skill_catalog", None)
    if not catalog:
        console.print("[red]Cognitive skill catalog not available.[/red]")
        return

    entries = catalog.list_entries()
    if not entries:
        console.print("[dim]No cognitive skills registered.[/dim]")
        return

    table = Table(title="Cognitive Skills")
    table.add_column("Name", style="cyan")
    table.add_column("Department", style="bold")
    table.add_column("Origin")
    table.add_column("Skill ID")
    table.add_column("Description")

    for e in entries:
        table.add_row(
            e.name,
            e.department,
            e.origin,
            e.skill_id or "-",
            e.description[:60] + ("..." if len(e.description) > 60 else ""),
        )

    console.print(table)


async def _skill_discover(runtime: ProbOSRuntime, console: Console) -> None:
    catalog = getattr(runtime, "cognitive_skill_catalog", None)
    if not catalog:
        console.print("[red]Cognitive skill catalog not available.[/red]")
        return

    results = catalog.discover_package_skills()
    if not results:
        console.print("[dim]No pip-installed skills found.[/dim]")
        return

    table = Table(title="Discovered Package Skills")
    table.add_column("Package", style="cyan")
    table.add_column("Skill", style="bold")
    table.add_column("ProbOS Metadata")
    table.add_column("Source Path")

    for r in results:
        table.add_row(
            r["package"],
            r["skill_name"],
            "Yes" if r["has_probos_metadata"] else "No",
            r["source_path"],
        )

    console.print(table)


async def _skill_import(
    runtime: ProbOSRuntime, console: Console, args: str,
) -> None:
    catalog = getattr(runtime, "cognitive_skill_catalog", None)
    if not catalog:
        console.print("[red]Cognitive skill catalog not available.[/red]")
        return

    source = args.strip()
    if not source:
        console.print("[yellow]Usage: /skill import <path>[/yellow]")
        return

    try:
        entry = await catalog.import_skill(Path(source))
        console.print(f"[green]Imported:[/green] {entry.name} (origin={entry.origin})")
    except ValueError as e:
        console.print(f"[red]Import failed: {e}[/red]")


async def _skill_info(
    runtime: ProbOSRuntime, console: Console, args: str,
) -> None:
    catalog = getattr(runtime, "cognitive_skill_catalog", None)
    if not catalog:
        console.print("[red]Cognitive skill catalog not available.[/red]")
        return

    name = args.strip()
    if not name:
        console.print("[yellow]Usage: /skill info <name>[/yellow]")
        return

    entry = catalog.get_entry(name)
    if not entry:
        console.print(f"[red]Skill not found: {name}[/red]")
        return

    console.print(f"[bold cyan]{entry.name}[/bold cyan]")
    console.print(f"  Description:     {entry.description}")
    console.print(f"  Department:      {entry.department}")
    console.print(f"  Origin:          {entry.origin}")
    console.print(f"  Skill ID:        {entry.skill_id or '-'}")
    console.print(f"  Min Proficiency: {entry.min_proficiency}")
    console.print(f"  Min Rank:        {entry.min_rank}")
    console.print(f"  Intents:         {', '.join(entry.intents) or '-'}")
    console.print(f"  License:         {entry.license or '-'}")
    console.print(f"  Compatibility:   {entry.compatibility or '-'}")
    console.print(f"  Skill Dir:       {entry.skill_dir}")


async def _skill_enrich(
    runtime: ProbOSRuntime, console: Console, args: str,
) -> None:
    catalog = getattr(runtime, "cognitive_skill_catalog", None)
    if not catalog:
        console.print("[red]Cognitive skill catalog not available.[/red]")
        return

    if not args.strip():
        console.print("[yellow]Usage: /skill enrich <name> [--dept <d>] [--intents <i1 i2>] "
                       "[--skill-id <id>] [--min-prof <n>] [--min-rank <r>][/yellow]")
        return

    # Parse: first token is name, rest are --key value pairs
    tokens = args.split()
    name = tokens[0]
    metadata: dict = {}

    i = 1
    while i < len(tokens):
        flag = tokens[i]
        if flag == "--dept" and i + 1 < len(tokens):
            metadata["department"] = tokens[i + 1]
            i += 2
        elif flag == "--skill-id" and i + 1 < len(tokens):
            metadata["skill_id"] = tokens[i + 1]
            i += 2
        elif flag == "--min-prof" and i + 1 < len(tokens):
            metadata["min_proficiency"] = int(tokens[i + 1])
            i += 2
        elif flag == "--min-rank" and i + 1 < len(tokens):
            metadata["min_rank"] = tokens[i + 1]
            i += 2
        elif flag == "--intents":
            # Collect all remaining tokens until next -- flag
            intents = []
            i += 1
            while i < len(tokens) and not tokens[i].startswith("--"):
                intents.append(tokens[i])
                i += 1
            metadata["intents"] = intents
        else:
            i += 1

    if not metadata:
        console.print("[yellow]No metadata flags provided. Use --dept, --intents, --skill-id, "
                       "--min-prof, --min-rank[/yellow]")
        return

    try:
        entry = await catalog.enrich_skill(name, metadata)
        console.print(f"[green]Enriched:[/green] {entry.name} — {list(metadata.keys())}")
    except ValueError as e:
        console.print(f"[red]Enrich failed: {e}[/red]")


async def _skill_remove(
    runtime: ProbOSRuntime, console: Console, args: str,
) -> None:
    catalog = getattr(runtime, "cognitive_skill_catalog", None)
    if not catalog:
        console.print("[red]Cognitive skill catalog not available.[/red]")
        return

    name = args.strip()
    if not name:
        console.print("[yellow]Usage: /skill remove <name>[/yellow]")
        return

    try:
        await catalog.remove_skill(name)
        console.print(f"[green]Removed:[/green] {name}")
    except ValueError as e:
        console.print(f"[red]Remove failed: {e}[/red]")


def _build_shell_validation_context(runtime: ProbOSRuntime) -> dict:
    """Build validation cross-reference context from runtime for shell commands."""
    ctx: dict = {}

    from probos.cognitive.standing_orders import _AGENT_DEPARTMENTS
    from probos.cognitive.skill_catalog import _RANK_ORDER

    ctx["valid_departments"] = set(_AGENT_DEPARTMENTS.values()) | {"*"}
    ctx["valid_ranks"] = set(_RANK_ORDER.keys())

    if getattr(runtime, "skill_registry", None):
        ctx["valid_skill_ids"] = {s.skill_id for s in runtime.skill_registry.list_skills()}

    if getattr(runtime, "callsign_registry", None):
        ctx["known_callsigns"] = set(runtime.callsign_registry.all_callsigns().values())

    return ctx


async def _skill_validate(
    runtime: ProbOSRuntime, console: Console, args: str,
) -> None:
    catalog = getattr(runtime, "cognitive_skill_catalog", None)
    if not catalog:
        console.print("[red]Cognitive skill catalog not available.[/red]")
        return

    ctx = _build_shell_validation_context(runtime)
    name = args.strip()

    if name:
        # Validate a single skill
        result = await catalog.validate_skill(name, ctx)
        results = [result]
    else:
        # Validate all skills
        results = await catalog.validate_all(ctx)

    if not results:
        console.print("[dim]No cognitive skills to validate.[/dim]")
        return

    table = Table(title="Skill Validation Results")
    table.add_column("Skill", style="cyan")
    table.add_column("Status")
    table.add_column("Errors", style="red")
    table.add_column("Warnings", style="yellow")

    valid_count = 0
    for r in results:
        if r.valid:
            status = "[green]valid[/green]"
            valid_count += 1
        else:
            status = "[red]invalid[/red]"
        table.add_row(
            r.skill_name,
            status,
            "; ".join(r.errors) if r.errors else "-",
            "; ".join(r.warnings) if r.warnings else "-",
        )

    console.print(table)
    total = len(results)
    invalid = total - valid_count
    console.print(f"\n[bold]Summary:[/bold] {total} total, "
                  f"[green]{valid_count} valid[/green], "
                  f"[red]{invalid} invalid[/red]")
