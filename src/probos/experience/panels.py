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

from probos.types import AgentState, DreamReport, FocusSnapshot, WorkflowCacheEntry

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

    # Dreaming
    dreaming = status.get("dreaming", {})
    dream_state = dreaming.get("state", "disabled")
    lines.append("")
    lines.append("[bold]Dreaming[/bold]")
    lines.append(f"  State: {dream_state}")
    if dreaming.get("last_report"):
        lr = dreaming["last_report"]
        lines.append(f"  Last cycle: {lr.get('episodes_replayed', 0)} episodes, "
                     f"{lr.get('weights_strengthened', 0)} strengthened, "
                     f"{lr.get('weights_pruned', 0)} pruned")

    # Federation
    fed = status.get("federation", {})
    if fed.get("enabled") is not False:
        lines.append("")
        lines.append("[bold]Federation[/bold]")
        peers = fed.get("connected_peers", [])
        lines.append(f"  Node ID:   {fed.get('node_id', '?')}")
        lines.append(f"  Peers:     {len(peers)} ({', '.join(peers) if peers else 'none'})")
        lines.append(f"  Forwarded: {fed.get('intents_forwarded', 0)}  "
                     f"Received: {fed.get('intents_received', 0)}  "
                     f"Collected: {fed.get('results_collected', 0)}")
    else:
        lines.append("")
        lines.append("[bold]Federation[/bold]")
        lines.append("  [dim]disabled[/dim]")

    # Workflow Cache
    wc = status.get("workflow_cache", {})
    lines.append("")
    lines.append("[bold]Workflow Cache[/bold]")
    lines.append(f"  Cached patterns: {wc.get('size', 0)}")

    # Self-Modification
    sm = status.get("self_mod", {})
    lines.append("")
    lines.append("[bold]Self-Modification[/bold]")
    if sm.get("enabled") is False:
        lines.append("  [dim]disabled[/dim]")
    else:
        lines.append(f"  Designed agents: {sm.get('designed_agent_count', 0)}")
        lines.append(f"  Designed skills: {sm.get('designed_skill_count', 0)}")

    # QA
    qa = status.get("qa", {})
    lines.append("")
    lines.append("[bold]QA[/bold]")
    if qa.get("enabled"):
        lines.append(f"  Reports: {qa.get('report_count', 0)}")
    else:
        lines.append("  [dim]disabled[/dim]")

    # Knowledge
    kn = status.get("knowledge", {})
    lines.append("")
    lines.append("[bold]Knowledge[/bold]")
    if kn.get("enabled"):
        lines.append(f"  Repo: {kn.get('repo_path', '?')}")
    else:
        lines.append("  [dim]disabled[/dim]")

    # Scaling
    sc = status.get("scaling", {})
    lines.append("")
    lines.append("[bold]Scaling[/bold]")
    if sc.get("enabled") is False:
        lines.append("  [dim]disabled[/dim]")
    else:
        pool_count = len(sc)
        excluded = sum(1 for v in sc.values() if isinstance(v, dict) and v.get("excluded"))
        lines.append(f"  Pools: {pool_count} monitored, {excluded} excluded")

    # Episodic Memory
    ep = status.get("episodic_stats", {})
    if ep:
        lines.append("")
        lines.append("[bold]Episodic Memory[/bold]")
        lines.append(f"  Episodes: {ep.get('total_episodes', 0)}")
        lines.append(f"  Intents:  {ep.get('unique_intents', 0)}")

    return Panel("\n".join(lines), title="System Status", border_style="blue")


def render_agent_table(agents: list[Any], trust_scores: dict[str, float]) -> Table:
    """Rich Table of all agents.

    Columns: ID (8-char) | Type | Tier | Pool | State (coloured) | Confidence | Trust
    """
    table = Table(title="Agents", show_lines=False)
    table.add_column("ID", style="cyan", width=10)
    table.add_column("Type")
    table.add_column("Tier", style="dim")
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
            getattr(agent, "tier", "domain"),
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


def render_attention_panel(
    queue: list[Any],
    focus: dict[str, Any] | None = None,
    focus_history: list[FocusSnapshot] | None = None,
) -> Panel:
    """Rich Panel showing the attention queue with scores and current focus."""
    lines: list[str] = []

    if focus:
        keywords = focus.get("keywords", [])
        if keywords:
            lines.append(f"[bold]Focus:[/bold] {', '.join(keywords[:8])}")
        else:
            lines.append("[bold]Focus:[/bold] [dim]none[/dim]")
        lines.append("")

    if not queue:
        lines.append("[dim]Attention queue is empty.[/dim]")
    else:
        for entry in queue:
            bg_tag = " [dim](bg)[/dim]" if getattr(entry, "is_background", False) else ""
            lines.append(
                f"  [cyan]{entry.task_id[:8]}[/cyan] {entry.intent:16s} "
                f"urgency={entry.urgency:.2f} deadline={entry.deadline_factor:.2f} "
                f"depth={entry.dependency_depth} [bold]score={entry.score:.3f}[/bold]{bg_tag}"
            )

    # Focus history section
    if focus_history:
        lines.append("")
        lines.append("[bold]Focus History[/bold]")
        for snap in focus_history:
            ts = snap.timestamp.strftime("%H:%M:%S")
            kws = ", ".join(snap.keywords[:5])
            if len(snap.keywords) > 5:
                kws += f" (+{len(snap.keywords) - 5})"
            lines.append(f"  [{ts}] {kws}")

    return Panel("\n".join(lines), title="Attention Queue", border_style="yellow")


def _format_escalation(escalation: dict) -> list[str]:
    """Format an escalation result for display."""
    tier = escalation.get("tier", "?")
    resolved = escalation.get("resolved", False)
    reason = escalation.get("reason", "")

    colour = "green" if resolved else "red"
    status = "Resolved" if resolved else "Unresolved"

    lines = [f"    [yellow]\u2191 Escalated (Tier: {tier})[/yellow] \u2014 [{colour}]{status}[/{colour}]"]
    if reason:
        lines.append(f"      {reason}")
    return lines


def _format_result(data: Any, max_items: int = 30) -> list[str]:
    """Format an agent result for display, detecting common structures."""
    # Command output: dict with stdout/stderr/exit_code
    if isinstance(data, dict) and "stdout" in data:
        lines = []
        stdout = data["stdout"].strip()
        stderr = data.get("stderr", "").strip()
        if stdout:
            lines.append(f"      {stdout[:500]}")
        if stderr:
            lines.append(f"      [dim]{stderr[:200]}[/dim]")
        if not stdout and not stderr:
            lines.append("      [dim](no output)[/dim]")
        return lines

    # Directory listing: list of dicts with 'name' and 'type' keys
    if isinstance(data, list) and data and isinstance(data[0], dict) and "name" in data[0]:
        lines = []
        for entry in data[:max_items]:
            name = entry.get("name", "?")
            etype = entry.get("type", "")
            if etype == "dir":
                lines.append(f"      [bold blue]{name}/[/bold blue]")
            else:
                size = entry.get("size", 0)
                lines.append(f"      {name}  [dim]({size} bytes)[/dim]")
        if len(data) > max_items:
            lines.append(f"      [dim]... and {len(data) - max_items} more[/dim]")
        return lines

    # String result — show up to 500 chars
    if isinstance(data, str):
        preview = data[:500]
        if len(data) > 500:
            preview += "..."
        return [f"      {preview}"]

    # Fallback — generic preview
    preview = str(data)[:200]
    if len(str(data)) > 200:
        preview += "..."
    return [f"      {preview}"]


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
                            lines.extend(_format_result(ir.result))
                            break
            # Show escalation info if present
            esc = getattr(node, "escalation_result", None)
            if esc is not None:
                lines.extend(_format_escalation(esc))

    # Show reflection if present
    reflection = result.get("reflection", "")
    if reflection:
        lines.append("")
        lines.append(f"[cyan]{reflection}[/cyan]")

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


def render_dream_panel(report: DreamReport | None) -> Panel:
    """Render a dream cycle report as a Rich Panel."""
    lines: list[str] = []

    if report is None:
        lines.append("[dim]No dream cycles yet.[/dim]")
        lines.append("")
        lines.append("Use [bold]/dream now[/bold] to trigger an immediate dream cycle.")
        return Panel("\n".join(lines), title="Dream Report", border_style="magenta")

    lines.append(f"[bold]Episodes replayed:[/bold]    {report.episodes_replayed}")
    lines.append(f"[bold]Weights strengthened:[/bold] {report.weights_strengthened}")
    lines.append(f"[bold]Connections pruned:[/bold]   {report.weights_pruned}")
    lines.append(f"[bold]Trust adjustments:[/bold]    {report.trust_adjustments}")
    lines.append(f"[bold]Duration:[/bold]             {report.duration_ms:.1f}ms")

    if report.pre_warm_intents:
        lines.append("")
        lines.append("[bold]Pre-warm intents:[/bold]")
        for intent in report.pre_warm_intents:
            lines.append(f"  - {intent}")
    else:
        lines.append("")
        lines.append("[dim]No pre-warm intents identified.[/dim]")

    return Panel("\n".join(lines), title="Dream Report", border_style="magenta")


def render_workflow_cache_panel(
    entries: list[WorkflowCacheEntry], size: int
) -> Panel:
    """Render the workflow cache as a Rich Panel with a table."""
    if not entries:
        lines = [
            "[dim]Workflow cache is empty.[/dim]",
            "",
            "Cached workflows appear after successful NL requests.",
        ]
        return Panel(
            "\n".join(lines),
            title=f"Workflow Cache ({size} entries)",
            border_style="cyan",
        )

    table = Table(show_header=True, show_lines=False)
    table.add_column("Pattern", max_width=40)
    table.add_column("Intents")
    table.add_column("Hits", justify="right")
    table.add_column("Last Hit")

    for entry in entries:
        # Extract intents from stored DAG JSON
        try:
            import json as _json
            dag_data = _json.loads(entry.dag_json)
            intents = ", ".join(n.get("intent", "?") for n in dag_data.get("nodes", []))
        except Exception:
            intents = "?"

        pattern = entry.pattern[:40]
        last_hit = entry.last_hit.strftime("%H:%M:%S") if entry.last_hit else "-"
        table.add_row(pattern, intents, str(entry.hit_count), last_hit)

    return Panel(table, title=f"Workflow Cache ({size} entries)", border_style="cyan")


def render_scaling_panel(scaling_status: dict) -> Panel:
    """Render pool scaling status as a Rich Panel."""
    if not scaling_status or scaling_status.get("enabled") is False:
        return Panel("[dim]Pool scaling is disabled.[/dim]", title="Scaling", border_style="cyan")

    table = Table(show_header=True, show_lines=False)
    table.add_column("Pool")
    table.add_column("Size", justify="right")
    table.add_column("Range", justify="center")
    table.add_column("Target", justify="right")
    table.add_column("Demand", justify="right")
    table.add_column("Last Event")
    table.add_column("Cooldown", justify="right")

    for pool_name, info in scaling_status.items():
        if not isinstance(info, dict) or "current_size" not in info:
            continue

        excluded = " [dim](excl)[/dim]" if info.get("excluded") else ""
        size = str(info["current_size"])
        range_str = f"{info['min_size']}-{info['max_size']}"
        target = str(info["target_size"])
        demand = f"{info['demand_ratio']:.2f}"

        last = info.get("last_event")
        if last:
            arrow = "\u2191" if last["direction"] == "up" else "\u2193"
            event_str = f"{arrow} {last['reason']}"
        else:
            event_str = "[dim]-[/dim]"

        cd = info.get("cooldown_remaining", 0.0)
        cd_str = f"{cd:.0f}s" if cd > 0 else "[dim]-[/dim]"

        table.add_row(
            f"{pool_name}{excluded}", size, range_str, target,
            demand, event_str, cd_str,
        )

    return Panel(table, title="Pool Scaling", border_style="cyan")


def render_federation_panel(federation_status: dict) -> Panel:
    """Render federation status as a Rich Panel."""
    if not federation_status or federation_status.get("enabled") is False:
        return Panel("[dim]Federation is not enabled.[/dim]", title="Federation", border_style="cyan")

    lines: list[str] = []
    lines.append(f"[bold]Node ID:[/bold]         {federation_status.get('node_id', '?')}")
    lines.append(f"[bold]Bind address:[/bold]    {federation_status.get('bind_address', '?')}")
    peers = federation_status.get("connected_peers", [])
    lines.append(f"[bold]Connected peers:[/bold] {len(peers)} ({', '.join(peers) if peers else 'none'})")
    lines.append(f"[bold]Gossip interval:[/bold] {federation_status.get('gossip_interval', '?')}s")
    lines.append("")
    lines.append(f"[bold]Intents forwarded:[/bold] {federation_status.get('intents_forwarded', 0)}")
    lines.append(f"[bold]Intents received:[/bold]  {federation_status.get('intents_received', 0)}")
    lines.append(f"[bold]Results collected:[/bold] {federation_status.get('results_collected', 0)}")

    return Panel("\n".join(lines), title="Federation", border_style="cyan")


def render_peers_panel(peer_models: dict) -> Panel:
    """Render peer self-models as a Rich Panel with table."""
    if not peer_models:
        return Panel("[dim]No peer models received yet.[/dim]", title="Peers", border_style="cyan")

    table = Table(show_header=True, show_lines=False)
    table.add_column("Peer")
    table.add_column("Capabilities")
    table.add_column("Agents", justify="right")
    table.add_column("Health", justify="right")
    table.add_column("Uptime", justify="right")

    for peer_id, info in peer_models.items():
        caps = ", ".join(info.get("capabilities", [])[:5])
        if len(info.get("capabilities", [])) > 5:
            caps += f" (+{len(info['capabilities']) - 5})"

        health = info.get("health", 0.0)
        health_text = Text(f"{health:.2f}")
        if health >= _HEALTH_GREEN:
            health_text.stylize("green")
        elif health >= _HEALTH_YELLOW:
            health_text.stylize("yellow")
        else:
            health_text.stylize("red")

        uptime = info.get("uptime_seconds", 0.0)
        if uptime >= 3600:
            uptime_str = f"{uptime / 3600:.1f}h"
        elif uptime >= 60:
            uptime_str = f"{uptime / 60:.1f}m"
        else:
            uptime_str = f"{uptime:.0f}s"

        table.add_row(
            peer_id,
            caps,
            str(info.get("agent_count", 0)),
            health_text,
            uptime_str,
        )

    return Panel(table, title=f"Peers ({len(peer_models)})", border_style="cyan")


def render_designed_panel(status: dict[str, Any], qa_reports: dict[str, Any] | None = None) -> Panel:
    """Render self-designed agents as a Rich Panel with table."""
    agents = status.get("designed_agents", [])
    active = status.get("active_count", 0)
    max_agents = status.get("max_designed_agents", 5)

    if not agents:
        lines = [
            "[dim]No self-designed agents yet.[/dim]",
            "",
            f"Capacity: {active}/{max_agents} slots used.",
        ]
        return Panel("\n".join(lines), title="Designed Agents", border_style="yellow")

    table = Table(show_header=True, show_lines=False)
    table.add_column("Type")
    table.add_column("Class")
    table.add_column("Intent")
    table.add_column("Status")
    table.add_column("Sandbox", justify="right")

    if qa_reports is not None:
        table.add_column("QA")

    for a in agents:
        status_text = Text(a.get("status", "?"))
        if a.get("status") == "active":
            status_text.stylize("green")
        elif a.get("status") in ("failed_validation", "failed_sandbox"):
            status_text.stylize("red")
        elif a.get("status") == "rejected_by_user":
            status_text.stylize("yellow")

        sandbox_ms = a.get("sandbox_time_ms", 0)
        sandbox_str = f"{sandbox_ms:.0f}ms" if sandbox_ms else "-"

        row = [
            a.get("agent_type", "?"),
            a.get("class_name", "?"),
            a.get("intent_name", "?"),
            status_text,
            sandbox_str,
        ]

        if qa_reports is not None:
            agent_type = a.get("agent_type", "")
            report = qa_reports.get(agent_type)
            if report is not None:
                qa_text = Text(report.verdict.upper())
                if report.verdict == "passed":
                    qa_text.stylize("green")
                elif report.verdict == "failed":
                    qa_text.stylize("red")
                else:
                    qa_text.stylize("yellow")
                row.append(qa_text)
            else:
                row.append("\u2014")

        table.add_row(*row)

    # Behavioral alerts summary
    behavioral = status.get("behavioral", {})
    lines_after = []
    if behavioral:
        for agent_type, info in behavioral.items():
            alert_count = info.get("alert_count", 0)
            if alert_count > 0:
                lines_after.append(
                    f"[yellow]! {agent_type}: {alert_count} behavioral alert(s)[/yellow]"
                )

    title = f"Designed Agents ({active}/{max_agents})"
    if lines_after:
        return Panel(
            table.__rich_console__(None, None) if False else
            "\n".join([str(table)] + lines_after),
            title=title,
            border_style="yellow",
        )
    return Panel(table, title=title, border_style="yellow")
