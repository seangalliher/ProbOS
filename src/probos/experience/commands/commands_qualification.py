"""AD-566f: /qualify shell command — manual trigger and inspection."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from probos.cognitive.qualification import CREW_AGENT_ID

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


def _resolve_agent(runtime: Any, identifier: str) -> Any | None:
    """Resolve callsign, agent_type, or raw agent_id to an agent object."""
    registry = getattr(runtime, "registry", None)
    if registry is None:
        return None
    needle = identifier.lower()
    for agent in registry.all():
        if hasattr(agent, "callsign") and agent.callsign and agent.callsign.lower() == needle:
            return agent
    for agent in registry.all():
        if agent.agent_type.lower() == needle:
            return agent
    for agent in registry.all():
        if agent.id == identifier:
            return agent
    return None


def _fmt_ts(ts: float) -> str:
    """Format unix timestamp to human-readable."""
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def cmd_qualify(runtime: Any, console: Console, args: str) -> None:
    """Qualification battery commands: status, run, agent, baselines."""
    harness = getattr(runtime, "_qualification_harness", None)
    store = getattr(runtime, "_qualification_store", None)

    if harness is None or store is None:
        console.print("[red]Qualification harness not available — system may still be starting.[/red]")
        return

    parts = args.strip().split(maxsplit=1) if args and args.strip() else []
    sub = parts[0].lower() if parts else "status"
    rest = parts[1].strip() if len(parts) > 1 else ""

    if sub == "status":
        await _status(runtime, console, harness)
    elif sub == "run":
        await _run(runtime, console, harness, store, rest)
    elif sub == "agent":
        if not rest:
            console.print("[yellow]Usage: /qualify agent <callsign|agent_type|agent_id>[/yellow]")
            return
        await _agent_summary(runtime, console, store, rest)
    elif sub == "baselines":
        await _baselines(runtime, console, harness, store)
    else:
        console.print(
            "[yellow]Usage: /qualify [status|run [callsign]|agent <id>|baselines][/yellow]"
        )


async def _status(runtime: Any, console: Console, harness: Any) -> None:
    """Show qualification battery overview."""
    tests = harness.registered_tests
    tiers: dict[int, list[str]] = {}
    for name, test in tests.items():
        tiers.setdefault(test.tier, []).append(name)

    table = Table(title="Qualification Battery — Registered Tests")
    table.add_column("Tier", style="cyan", width=6)
    table.add_column("Tests", style="white")
    table.add_column("Count", style="green", justify="right", width=6)

    for tier in sorted(tiers):
        table.add_row(str(tier), ", ".join(sorted(tiers[tier])), str(len(tiers[tier])))

    console.print(table)

    # Crew agent count + drift scheduler status
    scheduler = getattr(runtime, "_drift_scheduler", None)
    if scheduler:
        crew_ids = scheduler._get_crew_agent_ids()
        last_run = scheduler._last_run_time
        running = scheduler._running
        console.print(
            f"  Crew agents: [cyan]{len(crew_ids)}[/cyan]  |  "
            f"Drift scheduler: [{'green' if running else 'dim'}]"
            f"{'running' if running else 'stopped'}[/{'green' if running else 'dim'}]  |  "
            f"Last run: [dim]{_fmt_ts(last_run)}[/dim]"
        )
    else:
        console.print("  [dim]Drift scheduler not initialized.[/dim]")

    console.print(f"  Total registered tests: [cyan]{len(tests)}[/cyan]")


async def _run(runtime: Any, console: Console, harness: Any, store: Any, target: str) -> None:
    """Run qualification tests."""
    if target:
        # Run for specific agent
        agent = _resolve_agent(runtime, target)
        if agent is None:
            console.print(f"[red]Agent not found: {target}[/red]")
            return
        callsign = getattr(agent, "callsign", agent.agent_type)
        console.print(f"[dim]Running qualification battery for {callsign}...[/dim]")
        results = await harness.run_all(agent.id, runtime)
    else:
        # Run for all crew via drift scheduler
        scheduler = getattr(runtime, "_drift_scheduler", None)
        if scheduler is None:
            console.print("[red]Drift scheduler not available — cannot run crew-wide battery.[/red]")
            return
        console.print("[dim]Running qualification battery...[/dim]")
        reports = await scheduler.run_now()

        # Gather latest results from store for display (includes collective)
        crew_ids = scheduler._get_crew_agent_ids()
        all_ids = crew_ids + [CREW_AGENT_ID]
        results = []
        for cid in all_ids:
            for test_name in harness.registered_tests:
                r = await store.get_latest(cid, test_name)
                if r:
                    results.append(r)

    if not results:
        console.print("[dim]No results.[/dim]")
        return

    # BF-107: Pre-fetch baseline existence per agent+test pair.
    # r.is_baseline only reflects whether *this* result was the auto-captured
    # baseline — on subsequent runs it will be False even if a baseline exists.
    baseline_exists: dict[str, bool] = {}
    for r in results:
        key = f"{r.agent_id}:{r.test_name}"
        if key not in baseline_exists:
            bl = await store.get_baseline(r.agent_id, r.test_name)
            baseline_exists[key] = bl is not None

    table = Table(title="Qualification Results")
    table.add_column("Agent", style="cyan", width=16)
    table.add_column("Test", style="white")
    table.add_column("Tier", justify="center", width=5)
    table.add_column("Score", justify="right", width=8)
    table.add_column("Pass", justify="center", width=5)
    table.add_column("Baseline", justify="center", width=9)

    passed_count = 0
    baseline_count = 0
    agent_ids = set()
    for r in results:
        agent_label = r.agent_id[:12] if r.agent_id != "__crew__" else "[bold]CREW[/bold]"
        score_style = "green" if r.passed else "red"
        has_baseline = baseline_exists.get(f"{r.agent_id}:{r.test_name}", False)
        table.add_row(
            agent_label,
            r.test_name,
            str(r.tier),
            f"[{score_style}]{r.score:.3f}[/{score_style}]",
            "[green]Y[/green]" if r.passed else "[red]N[/red]",
            "[green]Y[/green]" if has_baseline else "-",
        )
        if r.passed:
            passed_count += 1
        if has_baseline:
            baseline_count += 1
        agent_ids.add(r.agent_id)

    console.print(table)
    console.print(
        f"  [dim]{len(agent_ids)} agents, {len(results)} tests, "
        f"{passed_count} passed, {baseline_count} baselines established[/dim]"
    )


async def _agent_summary(runtime: Any, console: Console, store: Any, identifier: str) -> None:
    """Show summary for a specific agent."""
    agent = _resolve_agent(runtime, identifier)
    if agent is None:
        console.print(f"[red]Agent not found: {identifier}[/red]")
        return

    summary = await store.get_agent_summary(agent.id)
    callsign = getattr(agent, "callsign", agent.agent_type)

    console.print(Panel(
        f"Agent: [cyan]{callsign}[/cyan] ({agent.id[:12]})\n"
        f"Tests run: {summary['tests_run']}  |  "
        f"Passed: {summary['tests_passed']}  |  "
        f"Pass rate: {summary['pass_rate']:.1%}  |  "
        f"Baseline: {'[green]set[/green]' if summary['baseline_set'] else '[dim]not set[/dim]'}",
        title="Agent Qualification Summary",
    ))

    latest = summary.get("latest_results", {})
    if latest:
        table = Table(title="Latest Results")
        table.add_column("Test", style="white")
        table.add_column("Score", justify="right", width=8)
        table.add_column("Pass", justify="center", width=5)
        table.add_column("Timestamp", style="dim")

        for test_name, info in sorted(latest.items()):
            score_style = "green" if info["passed"] else "red"
            table.add_row(
                test_name,
                f"[{score_style}]{info['score']:.3f}[/{score_style}]",
                "[green]Y[/green]" if info["passed"] else "[red]N[/red]",
                _fmt_ts(info["timestamp"]),
            )
        console.print(table)
    else:
        console.print("[dim]No test results recorded yet.[/dim]")


async def _baselines(runtime: Any, console: Console, harness: Any, store: Any) -> None:
    """Show all established baselines."""
    scheduler = getattr(runtime, "_drift_scheduler", None)
    if scheduler:
        crew_ids = scheduler._get_crew_agent_ids()
    else:
        crew_ids = []

    # Include __crew__ for collective tests
    all_ids = crew_ids + ["__crew__"]
    test_names = list(harness.registered_tests.keys())

    table = Table(title="Established Baselines")
    table.add_column("Agent", style="cyan", width=16)
    table.add_column("Test", style="white")
    table.add_column("Score", justify="right", width=8)
    table.add_column("Date", style="dim")

    found = 0
    for aid in all_ids:
        for tn in test_names:
            baseline = await store.get_baseline(aid, tn)
            if baseline:
                agent_label = aid[:12] if aid != "__crew__" else "[bold]CREW[/bold]"
                table.add_row(
                    agent_label,
                    tn,
                    f"{baseline.score:.3f}",
                    _fmt_ts(baseline.timestamp),
                )
                found += 1

    if found:
        console.print(table)
        console.print(f"  [dim]{found} baselines total[/dim]")
    else:
        console.print("[dim]No baselines established yet. Run /qualify run to create them.[/dim]")
