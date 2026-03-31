"""LLM configuration and model registry commands for ProbOSShell."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from rich.console import Console

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_models(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /models command."""
    from probos.cognitive.llm_client import OpenAICompatibleClient
    from rich.panel import Panel

    client = runtime.llm_client
    client_type = type(client).__name__

    lines: list[str] = []
    lines.append(f"[bold]LLM Client:[/bold] {client_type}")

    if isinstance(client, OpenAICompatibleClient):
        lines.append(f"[bold]Default tier:[/bold] {client.default_tier}")
        lines.append("")

        info = client.tier_info()
        # Track which URLs we've seen to note shared endpoints
        seen_urls: dict[str, str] = {}
        for tier in ("fast", "standard", "deep"):
            ti = info[tier]
            marker = " [dim](active)[/dim]" if tier == client.default_tier else ""
            reachable = ti.get("reachable")
            if reachable is True:
                status = "[green]connected[/green]"
            elif reachable is False:
                status = "[red]unreachable[/red]"
            else:
                status = "[dim]unknown[/dim]"

            shared_note = ""
            if ti["base_url"] in seen_urls:
                shared_note = f" [dim](shared with {seen_urls[ti['base_url']]})[/dim]"
            else:
                seen_urls[ti["base_url"]] = tier

            lines.append(f"  [bold]{tier}:[/bold]{marker}")
            lines.append(f"    Endpoint: {ti['base_url']}{shared_note}")
            lines.append(f"    Model:    {ti['model']}")
            lines.append(f"    Status:   {status}")
            lines.append("")
    else:
        lines.append("[dim]Using pattern-matched mock responses (no live LLM).[/dim]")

    console.print(Panel("\n".join(lines), title="LLM Configuration", border_style="cyan"))


async def cmd_registry(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Show all available models across all sources."""
    from rich.panel import Panel
    from rich.table import Table
    from probos.cognitive.llm_client import OpenAICompatibleClient
    from probos.cognitive.copilot_adapter import CopilotBuilderAdapter, _classify_provider

    # Section 1: Active tier models
    client = runtime.llm_client
    tier_table = Table(title="Active Models (Tier System)", show_header=True, header_style="bold cyan")
    tier_table.add_column("Tier", style="bold")
    tier_table.add_column("Model")
    tier_table.add_column("Provider")
    tier_table.add_column("Endpoint")
    tier_table.add_column("Status")

    if isinstance(client, OpenAICompatibleClient):
        info = client.tier_info()
        for tier in ("fast", "standard", "deep"):
            ti = info[tier]
            reachable = ti.get("reachable")
            if reachable is True:
                status = "[green]connected[/green]"
            elif reachable is False:
                status = "[red]unreachable[/red]"
            else:
                status = "[dim]unknown[/dim]"
            tier_table.add_row(
                tier,
                ti["model"],
                _classify_provider(ti["model"]),
                ti["base_url"],
                status,
            )
    else:
        tier_table.add_row("--", "MockLLMClient", "--", "--", "[dim]mock[/dim]")

    console.print(tier_table)
    console.print("")

    # Section 2: Copilot SDK models
    if CopilotBuilderAdapter.is_available():
        sdk_table = Table(title="Available Models (Copilot SDK)", show_header=True, header_style="bold yellow")
        sdk_table.add_column("Model")
        sdk_table.add_column("Provider")
        sdk_table.add_column("Source")
        sdk_table.add_column("Hosting")

        try:
            adapter = CopilotBuilderAdapter()
            await adapter.start()
            try:
                models = await adapter.list_available_models()
            finally:
                try:
                    await adapter.stop()
                except Exception:
                    pass

            if models:
                for m in models:
                    sdk_table.add_row(m["id"], m["provider"], m["source"], m["hosting"])
            else:
                sdk_table.add_row("[dim]No models found[/dim]", "--", "--", "--")
        except Exception as e:
            sdk_table.add_row(f"[red]Error: {e}[/red]", "--", "--", "--")

        console.print(sdk_table)
    else:
        console.print("[dim]Copilot SDK not installed -- no external models available[/dim]")


async def cmd_tier(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /tier command."""
    from probos.cognitive.llm_client import OpenAICompatibleClient

    client = runtime.llm_client
    if not isinstance(client, OpenAICompatibleClient):
        console.print(
            "[yellow]Tier switching is only available with a live LLM endpoint. "
            "Currently using MockLLMClient.[/yellow]"
        )
        return

    valid_tiers = list(client.models.keys())
    if not args:
        console.print(
            f"Current tier: [bold]{client.default_tier}[/bold] "
            f"(model: {client.models.get(client.default_tier, '?')})"
        )
        console.print(f"Available tiers: {', '.join(valid_tiers)}")
        return

    tier = args.lower()
    if tier not in valid_tiers:
        console.print(
            f"[red]Unknown tier: {tier}[/red]. "
            f"Available: {', '.join(valid_tiers)}"
        )
        return

    client.default_tier = tier
    info = client.tier_info()
    ti = info[tier]
    console.print(
        f"Switched to [bold]{tier}[/bold] tier: "
        f"{ti['model']} at {ti['base_url']}"
    )
