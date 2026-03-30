"""Knowledge store, search, anomalies, and scout commands for ProbOSShell."""
from __future__ import annotations

import logging
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)


async def cmd_knowledge(runtime: Any, console: Console, args: str) -> None:
    """Handle /knowledge command."""
    from probos.experience.knowledge_panel import render_knowledge_panel, render_knowledge_history

    ks = getattr(runtime, "_knowledge_store", None)
    if ks is None:
        console.print("[dim]Knowledge store is not enabled.[/dim]")
        return

    if args == "history":
        commits = await ks.recent_commits(20)
        console.print(render_knowledge_history(commits))
    else:
        counts = ks.artifact_counts()
        commit_count = await ks.commit_count()
        meta = await ks.meta_info()
        schema_version = meta.get("schema_version") if meta else None
        console.print(render_knowledge_panel(
            str(ks.repo_path), counts, commit_count, schema_version,
        ))


async def cmd_rollback(runtime: Any, console: Console, args: str) -> None:
    """Handle /rollback command."""
    from probos.experience.knowledge_panel import render_rollback_result

    ks = getattr(runtime, "_knowledge_store", None)
    if ks is None:
        console.print("[dim]Knowledge store is not enabled.[/dim]")
        return

    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        console.print("[yellow]Usage: /rollback <artifact_type> <identifier>[/yellow]")
        console.print("[dim]Example: /rollback trust snapshot[/dim]")
        return

    artifact_type, identifier = parts[0], parts[1]
    success = await ks.rollback_artifact(artifact_type, identifier)
    console.print(render_rollback_result(artifact_type, identifier, success))


async def cmd_search(runtime: Any, console: Console, args: str) -> None:
    """Handle /search command."""
    from probos.experience import panels

    layer = getattr(runtime, "_semantic_layer", None)
    if layer is None:
        console.print("[yellow]Semantic knowledge layer not available[/yellow]")
        return

    # Parse optional --type filter
    query = args.strip()
    types: list[str] | None = None
    if query.startswith("--type "):
        parts = query.split(maxsplit=2)
        if len(parts) >= 3:
            types = [t.strip() for t in parts[1].split(",") if t.strip()]
            query = parts[2]
        else:
            console.print("[yellow]Usage: /search [--type agents,skills] <query>[/yellow]")
            return

    if not query:
        console.print("[yellow]Usage: /search [--type agents,skills] <query>[/yellow]")
        return

    results = await layer.search(query, types=types, limit=10)
    stats = layer.stats()
    console.print(panels.render_search_panel(query, results, stats))


async def cmd_anomalies(runtime: Any, console: Console, args: str) -> None:
    """Handle /anomalies command."""
    from probos.experience import panels

    detector = getattr(runtime, "_emergent_detector", None)
    if detector is None:
        console.print("[yellow]Emergent detection not available[/yellow]")
        return
    patterns = detector.analyze()
    summary = detector.summary()
    pattern_dicts = [
        {
            "pattern_type": p.pattern_type,
            "description": p.description,
            "confidence": p.confidence,
            "severity": p.severity,
        }
        for p in patterns
    ]
    console.print(panels.render_anomalies_panel(summary, pattern_dicts))


async def cmd_scout(runtime: Any, console: Console, args: str) -> None:
    """Handle /scout command."""
    from probos.types import IntentMessage

    intent_name = "scout_report" if args.strip() == "report" else "scout_search"
    pool = runtime.pools.get("scout")
    if not pool or not pool.healthy_agents:
        console.print("[yellow]Scout agent not available[/yellow]")
        return
    agent_id = pool.healthy_agents[0]
    agent = pool.registry.get(agent_id)
    if not agent:
        console.print("[yellow]Scout agent not found in registry[/yellow]")
        return
    console.print(f"[dim]Running scout {intent_name}...[/dim]")
    try:
        result = await agent.handle_intent(IntentMessage(
            intent=intent_name,
            params={},
            context=args or "scout for new projects",
        ))
        output = result.result if result else "No output"
        console.print(output)
    except Exception as e:
        console.print(f"[red]Scout error: {e}[/red]")
