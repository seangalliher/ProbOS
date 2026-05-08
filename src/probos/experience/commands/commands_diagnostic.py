"""AD-700a: `/diagnostic` slash command surface.

Captain entry point for AD-700 multi-level diagnostics. Parses the
``<level>`` argument via the canonical ``parse_level()`` helper from
``probos.agents.medical.diagnostic_levels``; issues a ``diagnose_system``
intent (kwargs: ``level``, ``focus``); renders the structured diagnosis
result in a panel via ``panels.render_diagnostic_result``.

Subcommands:
  /diagnostic                  Help / usage
  /diagnostic <level>          Ship-wide diagnose at depth (L5..L1 or 1..5)
  /diagnostic <level> <focus>  Focused diagnose (e.g. ``/diagnostic L2 trust_network``)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.console import Console

from probos.agents.medical.diagnostic_levels import parse_level
from probos.experience import panels
from probos.types import IntentMessage

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)

_USAGE = (
    "Usage: /diagnostic [<level>] [<focus>]\n"
    "  level: L5..L1 (or 1..5); default L3 if omitted/unknown\n"
    "  focus: optional subsystem (e.g. trust_network, hebbian_router)\n"
    "Examples: /diagnostic | /diagnostic L2 | /diagnostic L1 trust_network"
)


async def cmd_diagnostic(
    runtime: "ProbOSRuntime", console: Console, args: str
) -> None:
    """Handle `/diagnostic [<level>] [<focus>]`."""
    args = (args or "").strip()
    if not args:
        console.print(_USAGE)
        return

    parts = args.split(maxsplit=1)
    level_token = parts[0]
    focus = parts[1].strip() if len(parts) > 1 else ""

    level = parse_level(level_token)

    try:
        pool = runtime.pools.get("medical_diagnostician")
        if not pool or not pool.healthy_agents:
            console.print("[yellow]Diagnostician agent not available[/yellow]")
            return
        agent_id = pool.healthy_agents[0]
        agent = pool.registry.get(agent_id)
        if not agent:
            console.print("[yellow]Diagnostician agent not found in registry[/yellow]")
            return

        intent_result = await agent.handle_intent(
            IntentMessage(
                intent="diagnose_system",
                params={"level": level.value, "focus": focus},
            )
        )
        result = intent_result.result if intent_result else None
        panel = panels.render_diagnostic_result(result or {}, level=level)
        console.print(panel)
    except Exception as e:  # noqa: BLE001 — slash commands must not propagate
        logger.warning(
            "Diagnostic command failed (level=%s focus=%s): %s",
            level.value,
            focus,
            e,
        )
        console.print(f"[red]Diagnostic error: {e}[/red]")
