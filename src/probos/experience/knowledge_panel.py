"""Knowledge store panels — Rich rendering for /knowledge and /rollback commands."""

from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def render_knowledge_panel(
    repo_path: str,
    artifact_counts: dict[str, int],
    commit_count: int,
    schema_version: int | None = None,
) -> Panel:
    """Render knowledge store overview panel."""
    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("Artifact Type", style="cyan")
    table.add_column("Count", justify="right")

    type_labels = {
        "episodes": "Episodes",
        "agents": "Agents",
        "skills": "Skills",
        "trust": "Trust",
        "routing": "Routing",
        "workflows": "Workflows",
        "qa": "QA Reports",
    }

    for key, label in type_labels.items():
        count = artifact_counts.get(key, 0)
        table.add_row(label, str(count))

    lines = [f"Repository: {repo_path}"]
    status = f"active ({commit_count} commits)" if commit_count > 0 else "initialized (no commits)"
    lines.append(f"Status:     {status}")
    if schema_version is not None:
        lines.append(f"Schema:     v{schema_version}")

    header = Text("\n".join(lines))

    content = Text()
    content.append("\n".join(lines))
    content.append("\n\n")

    return Panel(
        table,
        title=f"Knowledge Store \u2014 {repo_path}",
        subtitle=f"{status} | schema v{schema_version or '?'}",
        border_style="green",
    )


def render_knowledge_history(commits: list[dict]) -> Panel:
    """Render recent commit history."""
    if not commits:
        return Panel("[dim]No commit history.[/dim]", title="Knowledge History", border_style="green")

    table = Table(show_header=True, header_style="bold", box=None)
    table.add_column("Hash", style="yellow", width=8)
    table.add_column("Timestamp", style="dim")
    table.add_column("Message")

    for c in commits:
        table.add_row(
            c.get("commit_hash", "")[:8],
            c.get("timestamp", "")[:19],
            c.get("message", ""),
        )

    return Panel(table, title="Knowledge History (recent commits)", border_style="green")


def render_rollback_result(artifact_type: str, identifier: str, success: bool) -> Panel:
    """Render rollback result."""
    if success:
        msg = f"[green]\u2713[/green] Rolled back [bold]{artifact_type}/{identifier}[/bold] to previous version."
    else:
        msg = f"[red]\u2717[/red] Rollback failed for [bold]{artifact_type}/{identifier}[/bold]. No previous version found."
    return Panel(msg, title="Rollback", border_style="yellow" if not success else "green")
