"""User approval callback functions for ProbOSShell."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)


async def user_escalation_callback(
    console: Console, description: str, context: dict
) -> bool | None:
    """Prompt the user for escalation decision."""
    intent = context.get('intent', '?')
    params = context.get('params', {})
    error = context.get('error', '')

    console.print(
        f"\n[yellow bold]\u26a0 Escalation \u2014 your decision needed:[/yellow bold]"
    )
    console.print(f"  [bold]Intent:[/bold] [cyan]{intent}[/cyan]")

    # Show params so user knows what the operation is trying to do
    if params:
        for k, v in params.items():
            val = str(v)
            if len(val) > 120:
                val = val[:120] + "..."
            console.print(f"  [bold]{k}:[/bold] {val}")

    console.print(f"  [bold]Error:[/bold] [red]{error}[/red]")

    # Show what was already tried
    tiers_tried = context.get('tiers_attempted', [])
    if tiers_tried:
        tried_names = [t.value if hasattr(t, 'value') else str(t) for t in tiers_tried]
        console.print(f"  [bold]Already tried:[/bold] [dim]{' \u2192 '.join(tried_names)}[/dim]")

    console.print(
        f"\n  [dim]'y' = force approve  |  'n' = reject  |  Enter = skip[/dim]"
    )

    try:
        response = await asyncio.get_running_loop().run_in_executor(
            None, lambda: input("  Decision [y/n/skip]: ").strip().lower()
        )
        if response in ("y", "yes"):
            return True
        elif response in ("n", "no"):
            return False
        else:
            return None  # Skip
    except (EOFError, KeyboardInterrupt):
        return None


async def user_self_mod_approval(console: Console, description: str) -> bool:
    """Prompt the user to approve or reject a self-designed agent."""
    console.print(
        "\n[yellow bold]\U0001f527 Self-Modification \u2014 approval needed:[/yellow bold]"
    )
    console.print(f"  {description}")
    console.print(
        "  [dim]'y' = approve  |  'n' = reject[/dim]"
    )

    try:
        response = await asyncio.get_running_loop().run_in_executor(
            None, lambda: input("  Approve? [y/n]: ").strip().lower()
        )
        return response in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


async def user_import_approval(
    console: Console, renderer: Any, import_names: list[str]
) -> bool:
    """Prompt the user to approve adding imports to the whitelist."""
    if renderer._status is not None:
        renderer._status.stop()
        renderer._status = None

    console.print(
        "\n[yellow bold]This agent uses imports not on the whitelist:[/yellow bold]"
    )
    for name in import_names:
        console.print(f"  [bold]\u2022[/bold] {name}")
    console.print(
        "  [dim]'y' = allow (adds to whitelist)  |  'n' = block[/dim]"
    )

    try:
        response = await asyncio.get_running_loop().run_in_executor(
            None, lambda: input("  Allow? [y/n]: ").strip().lower()
        )
        return response in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


async def user_dep_install_approval(
    console: Console, renderer: Any, packages: list[str]
) -> bool:
    """Prompt the user to approve package installation."""
    # Stop any active spinner so the user can interact with stdin
    if renderer._status is not None:
        renderer._status.stop()
        renderer._status = None

    console.print(
        "\n[yellow bold]This agent requires packages that are not installed:[/yellow bold]"
    )
    for pkg in packages:
        console.print(f"  [bold]\u2022[/bold] {pkg}")
    console.print()

    try:
        response = await asyncio.get_running_loop().run_in_executor(
            None, lambda: input("Install with uv add? [y/n]: ").strip().lower()
        )
        return response in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False
