"""Crew Manifest shell command (AD-513 Phase 2 v1).

Provides the ``/manifest`` slash command for the interactive shell. Renders a
Rich table of crew entries with optional ``<department>`` and ``watch:<name>``
filter args, plus a ``--ship`` flag for the vessel-level summary surface used
by federation gossip / workforce planning.
"""
from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table


async def cmd_manifest(runtime: Any, console: Console, arg: str) -> None:
    """Print the formatted crew manifest.

    Usage:
        /manifest                      — full ship roster
        /manifest <department>         — department filter
        /manifest watch:<watch>        — watch filter (case-insensitive)
        /manifest <dept> watch:<w>     — combined
        /manifest --ship               — ship-level summary
    """
    ontology = getattr(runtime, "ontology", None)
    if ontology is None:
        console.print("[red]No ontology service available[/red]")
        return

    department: str | None = None
    watch: str | None = None
    show_ship = False
    for token in arg.split():
        if token == "--ship":
            show_ship = True
        elif token.startswith("watch:"):
            watch = token.split(":", 1)[1].lower()
        elif department is None:
            department = token

    if show_ship:
        summary = ontology.get_ship_manifest(
            trust_network=getattr(runtime, "trust_network", None),
            watch_manager=getattr(runtime, "watch_manager", None),
        )
        table = Table(title="Ship Manifest")
        table.add_column("Field")
        table.add_column("Value")
        table.add_row("Ship Name", str(summary.get("ship_name", "")))
        table.add_row("Agent Count", str(summary.get("agent_count", 0)))
        table.add_row("Alert State", str(summary.get("alert_state", "")))
        table.add_row("Departments", ", ".join(summary.get("departments", []) or []))
        table.add_row("Watches", ", ".join(summary.get("watches", []) or []))
        console.print(table)
        return

    manifest = ontology.get_crew_manifest(
        department=department,
        watch=watch,
        trust_network=getattr(runtime, "trust_network", None),
        callsign_registry=getattr(runtime, "callsign_registry", None),
        watch_manager=getattr(runtime, "watch_manager", None),
    )
    if not manifest:
        console.print("[yellow]No crew matched[/yellow]")
        return

    table = Table(title="Ship's Crew Manifest")
    for col in ("Callsign", "Department", "Post", "Rank", "Trust", "Watch"):
        table.add_column(col)
    for entry in manifest:
        try:
            trust_text = f"{float(entry.get('trust_score', 0.0)):.2f}"
        except (TypeError, ValueError):
            trust_text = "0.00"
        table.add_row(
            str(entry.get("callsign", "")),
            str(entry.get("department", "")),
            str(entry.get("post", "")),
            str(entry.get("rank", "")),
            trust_text,
            str(entry.get("watch", "")),
        )
    console.print(table)
