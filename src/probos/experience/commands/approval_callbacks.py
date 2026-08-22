"""User approval callback functions for ProbOSShell."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from rich.console import Console

from probos.types import EscalationTier

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

    # Show what was already tried.
    #
    # BF-831: the tier being consulted RIGHT NOW is appended to
    # ``tiers_attempted`` before the callback runs, so listing it verbatim told
    # the Captain that the prompt they are standing in had already been tried.
    tiers_tried = context.get('tiers_attempted', [])
    tried_names = [
        t.value if hasattr(t, 'value') else str(t) for t in tiers_tried
    ]
    # Drop only the LAST entry, and only when it is the tier being consulted.
    # Filtering every ``user`` by value would hide an EARLIER, legitimate user
    # consultation -- measured with ``["user", "retry", "user"]``, which
    # rendered only ``retry``. The cascade appends USER once today, so that is
    # not reachable yet; the value rule would simply be wrong if it were.
    if tried_names and tried_names[-1] == EscalationTier.USER.value:
        tried_names = tried_names[:-1]
    if tried_names:
        console.print(f"  [bold]Already tried:[/bold] [dim]{' \u2192 '.join(tried_names)}[/dim]")

    # BF-831: and what was deliberately NOT tried, with the reason. The Captain
    # is being asked to approve an act the crew declined (BF-830), so why the
    # retry was skipped is part of that decision -- and its absence from
    # "Already tried" cannot say whether it was skipped or simply not reached.
    tiers_skipped = context.get('tiers_skipped') or {}
    if isinstance(tiers_skipped, dict):
        from rich.markup import escape as _escape

        for tier_name, why in tiers_skipped.items():
            # BF-831: ESCAPED. These are interpolated into Rich markup, and an
            # unmatched closing tag raises MarkupError -- measured, a reason of
            # "[/dim]BROKEN" raised here BEFORE ``input()`` ran, so the Captain
            # was never asked at all. That is the opposite of this block's
            # purpose: the decision matters more than the annotation.
            console.print(
                f"  [bold]Not tried ({_escape(str(tier_name))}):[/bold] "
                f"[dim]{_escape(str(why))}[/dim]"
            )

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
