"""Status and informational commands for ProbOSShell."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_status(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /status command."""
    from probos.experience import panels

    status = runtime.status()
    # Augment with episodic stats if available
    if runtime.episodic_memory:
        try:
            status["episodic_stats"] = await runtime.episodic_memory.get_stats()
        except Exception:
            logger.debug("Status command context failed", exc_info=True)
    console.print(panels.render_status_panel(status))


async def cmd_agents(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /agents command."""
    from probos.experience import panels

    trust_scores = runtime.trust_network.all_scores()
    console.print(panels.render_agent_roster(
        runtime.pools,
        runtime.pool_groups,
        runtime.registry,
        trust_scores,
        callsign_registry=runtime.callsign_registry,
    ))


async def cmd_ping(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /ping command — show system uptime and basic health metrics (AD-337)."""
    from probos.types import AgentState

    status = runtime.status()

    # Extract uptime from system model (via mesh -> self_model)
    mesh = status.get("mesh", {})
    self_model = mesh.get("self_model", {})
    uptime = self_model.get("uptime_seconds")

    # Get agent counts and health
    from probos.crew_utils import is_crew_agent

    total_agents = status.get("total_agents", 0)
    agents = runtime.registry.all()
    active_agents = [a for a in agents if a.state == AgentState.ACTIVE]
    active_count = len(active_agents)
    crew_active = len([a for a in active_agents if is_crew_agent(a)])
    crew_total = runtime.registry.crew_count()
    health_score = _compute_health(runtime)

    # Build status display
    if uptime is not None:
        uptime_text = format_uptime(uptime)
        status_line = "[green]●[/green] System Status: ACTIVE"
    else:
        uptime_text = "unavailable"
        status_line = "[yellow]●[/yellow] System Status: UNKNOWN"

    # Display system information
    console.print(status_line)
    console.print(f"Uptime: {uptime_text}")
    console.print(f"Crew: {crew_active} active / {crew_total} crew (health: {health_score:.2f})")

    # Show connectivity status if available
    cognitive = status.get("cognitive", {})
    if cognitive:
        llm_status = cognitive.get("llm_client_ready", False)
        if llm_status:
            console.print("[green]LLM Client: Connected[/green]")
        else:
            console.print("[yellow]LLM Client: Disconnected[/yellow]")


async def cmd_scaling(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /scaling command."""
    from probos.experience import panels

    scaler = runtime.pool_scaler
    if not scaler:
        console.print("[yellow]Pool scaling is disabled.[/yellow]")
        return
    console.print(panels.render_scaling_panel(scaler.scaling_status()))


async def cmd_federation(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /federation command."""
    from probos.experience import panels

    bridge = runtime.federation_bridge
    if not bridge:
        console.print("[yellow]Federation is not enabled.[/yellow]")
        return
    console.print(panels.render_federation_panel(bridge.federation_status()))


async def cmd_peers(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /peers command."""
    from probos.experience import panels

    bridge = runtime.federation_bridge
    if not bridge:
        console.print("[yellow]Federation is not enabled.[/yellow]")
        return
    status = bridge.federation_status()
    console.print(panels.render_peers_panel(status.get("peer_models", {})))


async def cmd_credentials(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /credentials command."""
    store = getattr(runtime, "credential_store", None)
    if not store:
        console.print("[yellow]CredentialStore not available[/yellow]")
        return
    for cred in store.list_credentials():
        status = "[green]available[/green]" if cred["available"] else "[red]unavailable[/red]"
        console.print(f"  {cred['name']}: {status} — {cred['description']}")


async def cmd_debug(runtime: ProbOSRuntime, console: Console, args: str, *, shell: Any) -> None:
    """Handle /debug command. Needs shell reference for debug toggle."""
    if args.lower() == "on":
        shell.debug = True
    elif args.lower() == "off":
        shell.debug = False
    else:
        shell.debug = not shell.debug
    shell.renderer.debug = shell.debug
    state = "on" if shell.debug else "off"
    console.print(f"Debug mode: [bold]{state}[/bold]")


async def cmd_help(console: Console, commands_dict: dict[str, str]) -> None:
    """Handle /help command."""
    table = Table(title="Commands", show_header=False)
    table.add_column("Command", style="bold cyan")
    table.add_column("Description")
    for cmd, desc in commands_dict.items():
        table.add_row(cmd, desc)
    console.print(table)


def format_uptime(seconds: float) -> str:
    """Convert seconds to human-readable uptime format."""
    total_seconds = int(seconds)

    if total_seconds < 60:
        return f"{total_seconds} seconds"

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    remaining_seconds = total_seconds % 60

    if days > 0:
        return f"{days} days, {hours} hours, {minutes} minutes"
    elif hours > 0:
        return f"{hours} hours, {minutes} minutes, {remaining_seconds} seconds"
    else:
        return f"{minutes} minutes, {remaining_seconds} seconds"


def _compute_health(runtime: ProbOSRuntime) -> float:
    """Average confidence of all ACTIVE agents."""
    from probos.types import AgentState

    agents = runtime.registry.all()
    active = [a for a in agents if a.state == AgentState.ACTIVE]
    if not active:
        return 0.0
    return sum(a.confidence for a in active) / len(active)
