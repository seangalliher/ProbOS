"""QA panel rendering for SystemQAAgent results (AD-157)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from probos.agents.system_qa import QAReport
    from probos.consensus.trust import TrustNetwork


def render_qa_panel(
    qa_reports: dict[str, QAReport],
    trust_network: Any | None = None,
) -> Panel:
    """Render QA status for all designed agents as a Rich Panel.

    Parameters
    ----------
    qa_reports:
        Mapping of agent_type -> QAReport from runtime._qa_reports.
    trust_network:
        Optional TrustNetwork for displaying current trust scores.
    """
    if not qa_reports:
        return Panel(
            "[dim]No QA results yet.[/dim]",
            title="System QA Status",
            border_style="blue",
        )

    table = Table(show_header=True, show_lines=False)
    table.add_column("Agent Type")
    table.add_column("Verdict")
    table.add_column("Score", justify="right")
    table.add_column("Duration", justify="right")

    if trust_network is not None:
        table.add_column("Trust", justify="right")

    for agent_type, report in qa_reports.items():
        verdict_text = Text(report.verdict.upper())
        if report.verdict == "passed":
            verdict_text.stylize("green")
        elif report.verdict == "failed":
            verdict_text.stylize("red")
        else:
            verdict_text.stylize("yellow")

        score_str = f"{report.passed}/{report.total_tests}"
        duration_str = f"{report.duration_ms:.0f}ms"

        if trust_network is not None:
            trust_score = trust_network.get_score(agent_type)
            trust_str = f"{trust_score:.2f}"
            table.add_row(agent_type, verdict_text, score_str, duration_str, trust_str)
        else:
            table.add_row(agent_type, verdict_text, score_str, duration_str)

    return Panel(table, title="System QA Status", border_style="blue")


def render_qa_detail(
    agent_type: str,
    report: QAReport,
    trust_network: Any | None = None,
) -> Panel:
    """Render detailed QA results for a single agent type."""
    lines: list[str] = []

    verdict_color = "green" if report.verdict == "passed" else "red"
    lines.append(f"[bold]Verdict:[/bold] [{verdict_color}]{report.verdict.upper()}[/{verdict_color}]")
    lines.append(f"[bold]Score:[/bold] {report.passed}/{report.total_tests} ({report.pass_rate:.0%})")
    lines.append(f"[bold]Duration:[/bold] {report.duration_ms:.0f}ms")
    lines.append(f"[bold]Intent:[/bold] {report.intent_name}")
    lines.append(f"[bold]Pool:[/bold] {report.pool_name}")
    lines.append("")

    if report.test_details:
        table = Table(show_header=True, show_lines=False)
        table.add_column("#", justify="right")
        table.add_column("Type")
        table.add_column("Result")
        table.add_column("Error")

        for i, detail in enumerate(report.test_details, 1):
            result_text = Text("PASS" if detail["passed"] else "FAIL")
            result_text.stylize("green" if detail["passed"] else "red")
            error_str = detail.get("error") or "-"
            table.add_row(str(i), detail.get("case_type", "?"), result_text, error_str)

        lines.append(str(table))

    return Panel(
        "\n".join(lines),
        title=f"QA Detail: {agent_type}",
        border_style="blue",
    )
