"""AD-468: /config slash command - runtime override management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_config(runtime: "ProbOSRuntime", console: Console, args: str) -> None:
    rcs = getattr(runtime, "runtime_config_service", None)
    if rcs is None:
        console.print("[yellow]Runtime config service disabled.[/yellow]")
        return

    parts = args.split(maxsplit=2)
    if not parts:
        _show(rcs, console)
        return

    sub = parts[0].lower()
    if sub == "set" and len(parts) == 3:
        ok, reason = rcs.set(parts[1], parts[2])
        if ok:
            console.print(f"[green]Set[/green] {parts[1]} = {parts[2]}")
        else:
            console.print(f"[red]Rejected:[/red] {reason}")
    elif sub == "clear" and len(parts) == 2:
        if rcs.clear(parts[1]):
            console.print(f"[green]Cleared[/green] {parts[1]}")
        else:
            console.print(f"[yellow]Not set:[/yellow] {parts[1]}")
    else:
        console.print("[red]Usage:[/red] /config [set <field> <value>|clear <field>]")
        _show(rcs, console)


def _show(rcs: Any, console: Console) -> None:
    table = Table(show_header=True, header_style="bold")
    table.add_column("Field")
    table.add_column("Type")
    table.add_column("Range")
    table.add_column("Override")
    table.add_column("Description")
    overrides = rcs.all()
    for spec in rcs.known_fields():
        rng = "-"
        if spec.min_value is not None or spec.max_value is not None:
            lo = spec.min_value if spec.min_value is not None else "*"
            hi = spec.max_value if spec.max_value is not None else "*"
            rng = f"{lo}-{hi}"
        cur = overrides.get(spec.field_id, "-")
        table.add_row(spec.field_id, spec.typ, rng, str(cur), spec.description)
    console.print(table)
