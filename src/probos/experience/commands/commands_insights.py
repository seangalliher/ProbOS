"""AD-810: /insights slash command."""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown

from probos.runtime import ProbOSRuntime


_DEFAULT_DAYS = 7
_MAX_DAYS = 90


def _parse_days(args: str) -> int:
    """Parse ``/insights``, ``/insights 14``, or ``/insights --days 14``."""
    args = args.strip()
    if not args:
        return _DEFAULT_DAYS
    tokens = args.split()
    if tokens[0] == "--days" and len(tokens) >= 2:
        candidate = tokens[1]
    else:
        candidate = tokens[0]
    try:
        days = int(candidate)
    except ValueError:
        return _DEFAULT_DAYS
    return max(1, min(_MAX_DAYS, days))


async def cmd_insights(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle ``/insights [--days N]``."""
    service = getattr(runtime, "insight_service", None)
    if service is None:
        console.print("[yellow]Insights service not available on this runtime.[/yellow]")
        return
    days = _parse_days(args)
    report = await service.build_report(days=days)
    console.print(Markdown(report.to_markdown()))
