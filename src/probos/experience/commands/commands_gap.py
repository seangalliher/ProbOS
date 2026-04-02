"""AD-539: Gap report shell commands."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import yaml
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


async def cmd_gap(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Gap report commands: list, detail, check, summary."""
    parts = args.split(maxsplit=2) if args else []
    sub = parts[0].lower() if parts else ""

    if sub == "list":
        remainder = args[len("list"):].strip() if len(args) > 4 else ""
        await _gap_list(runtime, console, remainder)
    elif sub == "detail":
        if len(parts) < 2:
            console.print("[yellow]Usage: /gap detail <gap_id>[/yellow]")
            return
        await _gap_detail(runtime, console, parts[1])
    elif sub == "check":
        gap_id = parts[1] if len(parts) > 1 else ""
        await _gap_check(runtime, console, gap_id)
    elif sub == "summary":
        await _gap_summary(runtime, console)
    else:
        console.print(
            "[yellow]Usage: /gap <list|detail|check|summary>\n"
            "  list  [--agent <callsign>] [--type <knowledge|capability|data>] [--priority <low|medium|high|critical>]\n"
            "  detail <gap_id>\n"
            "  check [<gap_id>]     Run gap closure check\n"
            "  summary              Aggregate view[/yellow]"
        )


async def _load_gap_reports(runtime: ProbOSRuntime) -> list[dict]:
    """Load gap reports from Ship's Records."""
    records = runtime.records_store
    if not records:
        return []
    try:
        entries = await records.list_entries(
            directory="reports/gap-reports",
            tags=["ad-539"],
        )
        results = []
        for entry in entries:
            fm = entry.get("frontmatter", {})
            path = entry.get("path", "")
            # Read full content to get YAML body
            doc = await records.read_entry(path, reader_id="system")
            if doc:
                content = doc.get("content", "")
                try:
                    data = yaml.safe_load(content) or {}
                except Exception:
                    data = {}
                data["_path"] = path
                # Merge frontmatter
                for k, v in fm.items():
                    if k not in data:
                        data[k] = v
                results.append(data)
        return results
    except Exception:
        return []


async def _gap_list(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """List open gap reports with optional filters."""
    reports = await _load_gap_reports(runtime)

    # Parse filters
    agent_filter = ""
    type_filter = ""
    priority_filter = ""
    parts = args.split()
    i = 0
    while i < len(parts):
        if parts[i] == "--agent" and i + 1 < len(parts):
            agent_filter = parts[i + 1].lower()
            i += 2
        elif parts[i] == "--type" and i + 1 < len(parts):
            type_filter = parts[i + 1].lower()
            i += 2
        elif parts[i] == "--priority" and i + 1 < len(parts):
            priority_filter = parts[i + 1].lower()
            i += 2
        else:
            i += 1

    # Filter
    filtered = []
    for r in reports:
        if r.get("resolved", False):
            continue
        if agent_filter and agent_filter not in r.get("agent_id", "").lower() and agent_filter not in r.get("agent_type", "").lower():
            continue
        if type_filter and r.get("gap_type", "") != type_filter:
            continue
        if priority_filter and r.get("priority", "") != priority_filter:
            continue
        filtered.append(r)

    if not filtered:
        console.print("[dim]No open gap reports found.[/dim]")
        return

    table = Table(title=f"Open Gap Reports ({len(filtered)})")
    table.add_column("ID", style="cyan", max_width=12)
    table.add_column("Agent", style="green", max_width=12)
    table.add_column("Type", style="yellow")
    table.add_column("Priority", style="magenta")
    table.add_column("Description", max_width=40)
    table.add_column("Skill", style="blue")
    table.add_column("Prof", style="dim")

    for r in filtered:
        gap_id = r.get("id", "?")[:12]
        agent = r.get("agent_type", r.get("agent_id", "?")[:8])
        gap_type = r.get("gap_type", "?")
        priority = r.get("priority", "?")
        desc = r.get("description", "")[:40]
        skill = r.get("mapped_skill_id", "")
        current = r.get("current_proficiency", 0)
        target = r.get("target_proficiency", 0)
        prof = f"{current}/{target}" if skill else ""
        table.add_row(gap_id, agent, gap_type, priority, desc, skill, prof)

    console.print(table)


async def _gap_detail(runtime: ProbOSRuntime, console: Console, gap_id: str) -> None:
    """Show full detail for a specific gap report."""
    reports = await _load_gap_reports(runtime)
    match = None
    for r in reports:
        if r.get("id", "").startswith(gap_id):
            match = r
            break

    if not match:
        console.print(f"[red]Gap report '{gap_id}' not found.[/red]")
        return

    console.print(f"\n[bold cyan]Gap Report: {match.get('id', '?')}[/bold cyan]")
    console.print(f"  Agent:       {match.get('agent_type', '')} ({match.get('agent_id', '')[:8]})")
    console.print(f"  Type:        {match.get('gap_type', '')}")
    console.print(f"  Priority:    {match.get('priority', '')}")
    console.print(f"  Description: {match.get('description', '')}")
    console.print(f"  Resolved:    {match.get('resolved', False)}")

    intents = match.get("affected_intent_types", [])
    if intents:
        console.print(f"  Intents:     {', '.join(intents)}")

    evidence = match.get("evidence_sources", [])
    if evidence:
        console.print(f"  Evidence:    {', '.join(evidence)}")

    skill = match.get("mapped_skill_id", "")
    if skill:
        console.print(f"  Skill:       {skill}")
        console.print(f"  Proficiency: {match.get('current_proficiency', 0)} / {match.get('target_proficiency', 0)}")

    qual = match.get("qualification_path_id", "")
    if qual:
        console.print(f"  Qual Path:   {qual}")

    console.print(f"  Failure Rate: {match.get('failure_rate', 0):.1%}")
    console.print(f"  Episodes:    {match.get('episode_count', 0)}")
    console.print(f"  Created:     {match.get('created_at', '')}")
    console.print()


async def _gap_check(runtime: ProbOSRuntime, console: Console, gap_id: str) -> None:
    """Run gap closure check on specific or all open gaps."""
    from probos.cognitive.gap_predictor import check_gap_closure, GapReport

    reports = await _load_gap_reports(runtime)
    open_reports = [r for r in reports if not r.get("resolved", False)]

    if gap_id:
        open_reports = [r for r in open_reports if r.get("id", "").startswith(gap_id)]
        if not open_reports:
            console.print(f"[red]No open gap '{gap_id}' found.[/red]")
            return

    if not open_reports:
        console.print("[dim]No open gaps to check.[/dim]")
        return

    # Get services
    skill_service = None
    procedure_store = None
    for agent in runtime.registry.all():
        ps = getattr(agent, "_procedure_store", None)
        if ps:
            procedure_store = ps
            skill_service = getattr(ps, "_skill_service", None)
            break

    checked = 0
    resolved = 0
    for r in open_reports:
        gap = GapReport(
            id=r.get("id", ""),
            agent_id=r.get("agent_id", ""),
            agent_type=r.get("agent_type", ""),
            gap_type=r.get("gap_type", "knowledge"),
            description=r.get("description", ""),
            affected_intent_types=r.get("affected_intent_types", []),
            failure_rate=r.get("failure_rate", 0.0),
            episode_count=r.get("episode_count", 0),
            mapped_skill_id=r.get("mapped_skill_id", ""),
            current_proficiency=r.get("current_proficiency", 0),
            target_proficiency=r.get("target_proficiency", 0),
        )
        closed = await check_gap_closure(gap, skill_service, procedure_store)
        checked += 1
        if closed:
            resolved += 1
            console.print(
                f"[green]Gap '{gap.description[:40]}' RESOLVED — "
                f"{gap.agent_type} reached proficiency {gap.target_proficiency}[/green]"
            )
            # Update Ship's Records
            records = runtime.records_store
            if records:
                try:
                    import time
                    gap.resolved = True
                    gap.resolved_at = time.time()
                    content = yaml.dump(gap.to_dict(), default_flow_style=False, sort_keys=False)
                    await records.write_entry(
                        author="system",
                        path=f"reports/gap-reports/{gap.id}.md",
                        content=content,
                        message=f"Gap resolved: {gap.description}",
                        classification="ship",
                        topic="gap_analysis",
                        tags=["ad-539", "resolved"],
                    )
                except Exception:
                    pass
        else:
            console.print(
                f"[yellow]Gap '{gap.description[:40]}' still open — "
                f"proficiency {gap.current_proficiency}/{gap.target_proficiency}[/yellow]"
            )

    console.print(f"\n[dim]Checked {checked} gaps, resolved {resolved}.[/dim]")


async def _gap_summary(runtime: ProbOSRuntime, console: Console) -> None:
    """Aggregate view of gap reports."""
    reports = await _load_gap_reports(runtime)
    open_reports = [r for r in reports if not r.get("resolved", False)]
    resolved_reports = [r for r in reports if r.get("resolved", False)]

    console.print(f"\n[bold]Gap Report Summary[/bold]")
    console.print(f"  Total:    {len(reports)}")
    console.print(f"  Open:     {len(open_reports)}")
    console.print(f"  Resolved: {len(resolved_reports)}")

    if not open_reports:
        console.print("[dim]  No open gaps.[/dim]\n")
        return

    # By type
    by_type: dict[str, int] = {}
    by_priority: dict[str, int] = {}
    by_agent: dict[str, int] = {}
    by_skill: dict[str, int] = {}

    for r in open_reports:
        t = r.get("gap_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        p = r.get("priority", "unknown")
        by_priority[p] = by_priority.get(p, 0) + 1
        a = r.get("agent_type", r.get("agent_id", "unknown")[:8])
        by_agent[a] = by_agent.get(a, 0) + 1
        s = r.get("mapped_skill_id", "")
        if s:
            by_skill[s] = by_skill.get(s, 0) + 1

    console.print("\n  [bold]By Type:[/bold]")
    for t, c in sorted(by_type.items()):
        console.print(f"    {t}: {c}")

    console.print("  [bold]By Priority:[/bold]")
    for p, c in sorted(by_priority.items(), key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x[0], 4)):
        console.print(f"    {p}: {c}")

    if by_agent:
        console.print("  [bold]By Agent (top 5):[/bold]")
        for a, c in sorted(by_agent.items(), key=lambda x: -x[1])[:5]:
            console.print(f"    {a}: {c}")

    if by_skill:
        console.print("  [bold]By Skill (top 5):[/bold]")
        for s, c in sorted(by_skill.items(), key=lambda x: -x[1])[:5]:
            console.print(f"    {s}: {c}")

    console.print()
