"""Rich rendering functions for ProbOS system state.

Each function takes raw data (not runtime references) and returns a Rich
renderable.  This keeps panels testable in isolation — the shell calls
runtime APIs to gather data, then passes it here for display.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from probos.types import AgentState

# ---------------------------------------------------------------------------
# Colour constants
# ---------------------------------------------------------------------------

STATE_COLORS: dict[AgentState, str] = {
    AgentState.ACTIVE: "green",
    AgentState.DEGRADED: "yellow",
    AgentState.RECYCLING: "red",
    AgentState.SPAWNING: "blue",
}

_TRUST_GREEN = 0.6
_TRUST_YELLOW = 0.4
_HEALTH_GREEN = 0.7
_HEALTH_YELLOW = 0.4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate_id(agent_id: str, length: int = 8) -> str:
    return agent_id[:length]


def _score_color(score: float) -> str:
    if score >= _TRUST_GREEN:
        return "green"
    if score >= _TRUST_YELLOW:
        return "yellow"
    return "red"


def format_health(health: float) -> Text:
    """Format a health value with colour: green > 0.7, yellow 0.4-0.7, red < 0.4."""
    if health >= _HEALTH_GREEN:
        colour = "green"
    elif health >= _HEALTH_YELLOW:
        colour = "yellow"
    else:
        colour = "red"
    return Text(f"{health:.2f}", style=colour)


# ---------------------------------------------------------------------------
# Panel / table builders
# ---------------------------------------------------------------------------

def render_status_panel(status: dict[str, Any]) -> Panel:
    """Render ``runtime.status()`` as a Rich Panel."""
    sys = status.get("system", {})
    mesh = status.get("mesh", {})
    consensus = status.get("consensus", {})
    cognitive = status.get("cognitive", {})

    lines: list[str] = []
    lines.append(f"[bold]{sys.get('name', 'ProbOS')}[/bold] v{sys.get('version', '?')}")
    lines.append(f"  Started: {'[green]yes[/green]' if status.get('started') else '[red]no[/red]'}")
    lines.append(f"  Agents:  {status.get('total_agents', 0)}")

    # Pools
    pools = status.get("pools", {})
    if pools:
        lines.append("")
        lines.append("[bold]Pools[/bold]")
        for name, info in pools.items():
            lines.append(f"  {name}: {info.get('current_size', '?')}/{info.get('target_size', '?')} ({info.get('agent_type', '?')})")

    # Mesh
    lines.append("")
    lines.append("[bold]Mesh[/bold]")
    lines.append(f"  Intent subscribers: {mesh.get('intent_subscribers', 0)}")
    lines.append(f"  Capability agents:  {mesh.get('capability_agents', 0)}")
    lines.append(f"  Gossip view:        {mesh.get('gossip_view_size', 0)}")
    lines.append(f"  Hebbian weights:    {mesh.get('hebbian_weights', 0)}")
    lines.append(f"  Active signals:     {mesh.get('active_signals', 0)}")

    # Consensus
    qp = consensus.get("quorum_policy", {})
    lines.append("")
    lines.append("[bold]Consensus[/bold]")
    lines.append(f"  Trust network agents: {consensus.get('trust_network_agents', 0)}")
    lines.append(f"  Red team agents:      {consensus.get('red_team_agents', 0)}")
    lines.append(f"  Quorum: {qp.get('min_votes', '?')} votes, "
                 f"threshold {qp.get('approval_threshold', '?')}, "
                 f"weighted={qp.get('confidence_weighted', '?')}")

    # Cognitive
    lines.append("")
    lines.append("[bold]Cognitive[/bold]")
    lines.append(f"  LLM client:       {cognitive.get('llm_client', '?')}")
    lines.append(f"  Memory budget:    {cognitive.get('working_memory_budget', '?')} tokens")
    lines.append(f"  Decompose timeout: {cognitive.get('decomposition_timeout', '?')}s")
    lines.append(f"  DAG timeout:       {cognitive.get('dag_execution_timeout', '?')}s")

    return Panel("\n".join(lines), title="System Status", border_style="blue")


def render_agent_table(agents: list[Any], trust_scores: dict[str, float]) -> Table:
    """Rich Table of all agents.

    Columns: ID (8-char) | Type | Pool | State (coloured) | Confidence | Trust
    """
    table = Table(title="Agents", show_lines=False)
    table.add_column("ID", style="cyan", width=10)
    table.add_column("Type")
    table.add_column("Pool")
    table.add_column("State")
    table.add_column("Confidence", justify="right")
    table.add_column("Trust", justify="right")

    # Sort by pool then type
    sorted_agents = sorted(agents, key=lambda a: (a.pool, a.agent_type))

    for agent in sorted_agents:
        state_text = Text(agent.state.value)
        colour = STATE_COLORS.get(agent.state, "white")
        state_text.stylize(colour)

        trust = trust_scores.get(agent.id, 0.5)
        trust_text = Text(f"{trust:.2f}", style=_score_color(trust))

        table.add_row(
            _truncate_id(agent.id),
            agent.agent_type,
            agent.pool,
            state_text,
            f"{agent.confidence:.2f}",
            trust_text,
        )

    return table


def render_weight_table(weights: dict[tuple, float]) -> Table:
    """Rich Table of Hebbian weights.

    Expects keys as ``(source, target, rel_type)`` from
    ``hebbian_router.all_weights_typed()``.
    """
    table = Table(title="Hebbian Weights", show_lines=False)
    table.add_column("Source", style="cyan", width=10)
    table.add_column("Target", style="cyan", width=10)
    table.add_column("Rel")
    table.add_column("Weight", justify="right")

    # Sort by weight descending, skip tiny weights
    items = [(k, v) for k, v in weights.items() if v >= 0.001]
    items.sort(key=lambda x: x[1], reverse=True)

    for key, weight in items:
        src, tgt = _truncate_id(key[0]), _truncate_id(key[1])
        rel = key[2] if len(key) > 2 else "?"
        table.add_row(src, tgt, rel, f"{weight:.4f}")

    if not items:
        table.add_row("[dim]no weights[/dim]", "", "", "")

    return table


def render_trust_panel(trust_summary: list[dict[str, Any]]) -> Panel:
    """Rich Panel with trust network summary.

    Input is from ``trust_network.summary()`` — a list of dicts sorted by
    score descending.
    """
    table = Table(show_header=True, show_lines=False)
    table.add_column("Agent", style="cyan", width=10)
    table.add_column("Score", justify="right")
    table.add_column("Alpha", justify="right")
    table.add_column("Beta", justify="right")
    table.add_column("Obs", justify="right")
    table.add_column("Uncertainty", justify="right")

    for entry in trust_summary:
        score = entry.get("score", 0.5)
        score_text = Text(f"{score:.3f}", style=_score_color(score))
        table.add_row(
            _truncate_id(entry.get("agent_id", "?")),
            score_text,
            f"{entry.get('alpha', 0):.1f}",
            f"{entry.get('beta', 0):.1f}",
            f"{entry.get('observations', 0):.0f}",
            f"{entry.get('uncertainty', 0):.3f}",
        )

    return Panel(table, title="Trust Network", border_style="green")


def render_gossip_panel(gossip_view: dict[str, Any]) -> Panel:
    """Rich Panel showing the gossip protocol view."""
    table = Table(show_header=True, show_lines=False)
    table.add_column("Agent", style="cyan", width=10)
    table.add_column("Type")
    table.add_column("Pool")
    table.add_column("State")
    table.add_column("Confidence", justify="right")
    table.add_column("Capabilities")

    for agent_id, entry in sorted(gossip_view.items()):
        state_text = Text(entry.state.value)
        colour = STATE_COLORS.get(entry.state, "white")
        state_text.stylize(colour)

        caps = ", ".join(entry.capabilities[:3])
        if len(entry.capabilities) > 3:
            caps += f" (+{len(entry.capabilities) - 3})"

        table.add_row(
            _truncate_id(agent_id),
            entry.agent_type,
            entry.pool,
            state_text,
            f"{entry.confidence:.2f}",
            caps,
        )

    return Panel(table, title=f"Gossip View ({len(gossip_view)} agents)", border_style="cyan")


def render_event_log_table(events: list[dict[str, Any]]) -> Table:
    """Rich Table of event log entries."""
    table = Table(title="Event Log", show_lines=False)
    table.add_column("Time")
    table.add_column("Category", style="bold")
    table.add_column("Event")
    table.add_column("Agent", style="cyan", width=10)
    table.add_column("Detail")

    for ev in events:
        ts = ev.get("timestamp", "")
        if isinstance(ts, str) and len(ts) >= 19:
            ts = ts[11:19]  # HH:MM:SS
        elif isinstance(ts, datetime):
            ts = ts.strftime("%H:%M:%S")
        else:
            ts = str(ts)[:8]

        agent_id = ev.get("agent_id") or ""
        if agent_id:
            agent_id = _truncate_id(agent_id)

        detail = ev.get("detail") or ""
        if len(detail) > 60:
            detail = detail[:57] + "..."

        table.add_row(
            ts,
            ev.get("category", ""),
            ev.get("event", ""),
            agent_id,
            detail,
        )

    if not events:
        table.add_row("[dim]no events[/dim]", "", "", "", "")

    return table


def render_working_memory_panel(snapshot: Any) -> Panel:
    """Rich Panel showing a WorkingMemorySnapshot."""
    return Panel(
        snapshot.to_text(),
        title="Working Memory",
        border_style="magenta",
    )


def render_dag_result(result: dict[str, Any], debug: bool = False) -> Panel:
    """Render the result of ``process_natural_language()``."""
    lines: list[str] = []

    node_count = result.get("node_count", 0)
    completed = result.get("completed_count", 0)
    failed = result.get("failed_count", 0)

    if node_count == 0:
        response = result.get("response", "")
        if response:
            lines.append(f"[cyan]{response}[/cyan]")
        else:
            lines.append("[yellow]No intents were executed.[/yellow]")
    else:
        status_colour = "green" if failed == 0 else "yellow"
        lines.append(
            f"[{status_colour}]{completed}/{node_count} tasks completed[/{status_colour}]"
        )
        if failed:
            lines.append(f"[red]{failed} task(s) failed[/red]")

    # Per-node summary
    dag = result.get("dag")
    results = result.get("results", {})
    if dag and hasattr(dag, "nodes"):
        for node in dag.nodes:
            icon = "[green]\u2713[/green]" if node.status == "completed" else "[red]\u2717[/red]"
            lines.append(f"  {icon} {node.id}: {node.intent}")
            node_res = results.get(node.id, {})
            if isinstance(node_res, dict):
                if "error" in node_res:
                    lines.append(f"      [red]{node_res['error']}[/red]")
                elif node_res.get("success") and "results" in node_res:
                    # Show first successful agent result excerpt
                    for ir in node_res["results"]:
                        if hasattr(ir, "success") and ir.success and ir.result:
                            preview = str(ir.result)[:100]
                            lines.append(f"      {preview}")
                            break

    if debug:
        lines.append("")
        lines.append("[dim]--- DEBUG ---[/dim]")
        # Show raw results as JSON
        debug_results = {}
        for nid, nres in results.items():
            try:
                debug_results[nid] = str(nres)[:500]
            except Exception:
                debug_results[nid] = "<unserializable>"
        lines.append(json.dumps(debug_results, indent=2, default=str))

    return Panel("\n".join(lines), title="Results", border_style="green")
