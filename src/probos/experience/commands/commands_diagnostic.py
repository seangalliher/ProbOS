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
from typing import TYPE_CHECKING, Any

from rich.console import Console

from probos.agents.medical.diagnostic_levels import parse_level
from probos.experience import panels
from probos.types import IntentMessage
from probos.utils.json_extract import extract_json

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)

_USAGE = (
    "Usage: /diagnostic [<level>] [<focus>]\n"
    "  level: L5..L1 (or 1..5); default L3 if omitted/unknown\n"
    "  focus: optional subsystem (e.g. trust_network, hebbian_router)\n"
    "Examples: /diagnostic | /diagnostic L2 | /diagnostic L1 trust_network"
)


def _diagnosis_from_result(result: Any) -> tuple[dict[str, Any], str]:
    """BF-991: the diagnosis dict in an IntentResult's ``result``, and any text that is not one.

    ``CognitiveAgent.act`` returns the LLM's text, so ``result`` is a str: the JSON
    the Diagnostician was told to write at L3..L1, and "" at L4/L5, which make no
    LLM call (AD-700c). A dict passes through unchanged. Returns
    ``(diagnosis, unparsed_text)``; the second item is "" unless the text holds no
    JSON object.
    """
    if isinstance(result, dict):
        return result, ""
    text = "" if result is None else str(result)
    if not text.strip():
        return {}, ""
    try:
        parsed = extract_json(text)
    except ValueError:
        return {}, text
    if not isinstance(parsed, dict):
        return {}, text
    return parsed, ""


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
        if intent_result is not None and not intent_result.success:
            console.print(
                f"Diagnostic failed: {intent_result.error or 'no error given'}",
                style="red",
                markup=False,
                emoji=False,
                highlight=False,
            )
            return
        diagnosis, unparsed = _diagnosis_from_result(
            intent_result.result if intent_result else None
        )
        panel = panels.render_diagnostic_result(diagnosis, level=level)
        console.print(panel)
        if unparsed:
            # The LLM's own words, shown as received: no markup, emoji codes or highlighting.
            console.print("The Diagnostician's reply is not a JSON diagnosis:", style="yellow")
            console.print(unparsed, markup=False, emoji=False, highlight=False)
        if level.llm_tier is None:
            console.print(
                f"No LLM analysis at this depth (AD-700c): {level.value} makes no LLM call.",
                style="dim",
                markup=False,
            )
    except Exception as e:  # noqa: BLE001 — slash commands must not propagate
        logger.warning(
            "Diagnostic command failed (level=%s focus=%s): %s",
            level.value,
            focus,
            e,
        )
        # BF-991: the error text is foreign text, printed as received; as markup, a "[/x]" in it raises again here.
        console.print(f"Diagnostic error: {e}", style="red", markup=False, emoji=False, highlight=False)
