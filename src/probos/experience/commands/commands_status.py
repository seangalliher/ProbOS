"""Status and informational commands for ProbOSShell."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from rich.box import ROUNDED
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


async def cmd_readiness(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /readiness command — render ship readiness report (AD-628h)."""
    reporter = getattr(runtime, "readiness_reporter", None)
    if reporter is None:
        console.print("[yellow]ReadinessReporter not wired on runtime[/yellow]")
        return
    try:
        report = await reporter.compute_ship_readiness()
    except Exception:
        logger.warning("AD-628h: readiness report failed", exc_info=True)
        console.print("[red]Readiness report unavailable[/red]")
        return
    table = Table(
        title=f"Ship Readiness — {report.c_rating} (composite {report.composite_score:.2f})",
        box=ROUNDED,
        expand=False,
    )
    table.add_column("Department")
    table.add_column("Members", justify="right")
    table.add_column("Coverage", justify="right")
    table.add_column("Proficiency", justify="right")
    table.add_column("Regressions 24h", justify="right")
    table.add_column("Decay 24h", justify="right")
    for dept in report.departments:
        table.add_row(
            dept.department,
            str(dept.member_count),
            f"{dept.qualified_skill_coverage:.2f}",
            f"{dept.proficiency_mean:.2f}",
            str(dept.regression_count_24h),
            str(dept.decay_count_24h),
        )
    console.print(table)


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
    """Handle /federation command.

    AD-480i + AD-479i: subcommand dispatch.
    - ``""`` (no arg) → existing federation panel.
    - ``"peers"`` → cross-protocol peer list with trust scores (AD-480i).
    - ``"routing"`` → ZeroMQ routing breakdown (AD-479i).
    """
    from probos.experience import panels

    sub = (args or "").strip().split(maxsplit=1)
    subcommand = sub[0].lower() if sub else ""

    if subcommand == "peers":
        registry = runtime.federation_peer_registry
        trust_network = runtime.trust_network
        console.print(panels.render_federation_peers_panel(
            registry.list_peers(), trust_network,
        ))
        return

    if subcommand == "routing":
        bridge = runtime.federation_bridge
        if not bridge:
            console.print("[yellow]Federation is not enabled.[/yellow]")
            return
        console.print(panels.render_federation_routing_panel(
            bridge=bridge,
            trust_network=runtime.trust_network,
            hebbian_map=getattr(runtime, "federation_hebbian_map", None),
            cluster_monitor=getattr(runtime, "federation_cluster_monitor", None),
        ))
        return

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


async def cmd_security(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /security command.

    AD-607j: subcommand dispatch.
    - ``"memory"`` → memory-security event counters over a 24h window.
    - ``""`` (no arg) → usage hint.
    """
    sub = (args or "").strip().split(maxsplit=1)
    subcommand = sub[0].lower() if sub else ""

    if subcommand == "memory":
        registry = getattr(runtime, "memory_security_registry", None)
        if registry is None:
            console.print(
                "[yellow]Memory security registry not available.[/yellow]"
            )
            return
        counts = registry.counts()
        # Render the seven AD-607 EventTypes; show 0 for those unseen.
        ordered = [
            "memory_recall_anomaly",
            "memory_provenance_gap",
            "memory_anchor_mismatch",
            "memory_leak_suspected",
            "memory_injection_suspected",
            "federation_episode_rejected",
            "federation_recall_dp_redacted",
        ]
        table = Table(title="Memory Security (24h)", show_header=True)
        table.add_column("Event", style="bold cyan")
        table.add_column("Count", style="bold")
        for name in ordered:
            table.add_row(name, str(counts.get(name, 0)))
        console.print(table)
        return

    console.print("Usage: /security memory")


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
