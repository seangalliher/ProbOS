"""Real-time execution display — spinners, live progress, debug output.

The ``ExecutionRenderer`` orchestrates the cognitive pipeline stages itself
(working memory assembly, decompose, execute, record results) so it can
insert different Rich display modes (spinner vs Live) between stages.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TYPE_CHECKING

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from probos.experience.panels import render_dag_result
from probos.types import TaskDAG, TaskNode

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)

# Status icons
_ICON_PENDING = "[dim]\u2022[/dim]"        # dimmed bullet
_ICON_RUNNING = "[bold blue]\u25b6[/bold blue]"  # play triangle
_ICON_DONE = "[green]\u2713[/green]"        # check
_ICON_FAIL = "[red]\u2717[/red]"            # cross


class ExecutionRenderer:
    """Real-time visual feedback during NL -> DAG -> execution pipeline."""

    def __init__(
        self,
        console: Console,
        runtime: ProbOSRuntime,
        debug: bool = False,
    ) -> None:
        self.console = console
        self.runtime = runtime
        self.debug = debug
        self._live: Live | None = None
        self._current_dag: TaskDAG | None = None
        self._node_statuses: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process_with_feedback(self, text: str) -> dict[str, Any]:
        """Process NL input with real-time visual feedback.

        Returns the same dict as ``runtime.process_natural_language()``.
        """
        self.console.print(f"\n[bold]> {text}[/bold]")

        # Phase 1: Decompose with spinner
        with self.console.status(
            "[bold blue]Decomposing intent...[/bold blue]",
            spinner="dots",
        ):
            context = self.runtime.working_memory.assemble(
                registry=self.runtime.registry,
                trust_network=self.runtime.trust_network,
                hebbian_router=self.runtime.hebbian_router,
                capability_list=self._get_capability_list(),
            )
            dag = await self.runtime.decomposer.decompose(text, context=context)

        if self.debug:
            raw = self.runtime.decomposer.last_raw_response
            self.console.print(Panel(
                raw or "[dim]<empty>[/dim]",
                title="DEBUG: Raw LLM Response",
                style="dim",
            ))

        if not dag.nodes:
            if dag.response:
                self.console.print(f"[cyan]{dag.response}[/cyan]")
            else:
                self.console.print("[yellow]No actionable intents recognized.[/yellow]")
            return self._empty_result(text, dag)

        # Show DAG plan
        self._render_dag_plan(dag)

        if self.debug:
            self._render_debug_dag(dag)

        # Phase 2: Execute with Live display
        self._current_dag = dag
        self._node_statuses = {n.id: "pending" for n in dag.nodes}

        # Record intents in working memory
        for node in dag.nodes:
            self.runtime.working_memory.record_intent(node.intent, node.params)

        with Live(
            self._build_progress_table(),
            console=self.console,
            refresh_per_second=4,
            transient=True,
        ) as live:
            self._live = live
            execution_result = await self.runtime.dag_executor.execute(
                dag, on_event=self._on_execution_event
            )
            self._live = None

        # Record results in working memory
        for node in dag.nodes:
            node_result = execution_result["results"].get(node.id, {})
            success = node.status == "completed"
            self.runtime.working_memory.record_result(
                intent=node.intent,
                success=success,
                result_count=1,
                detail=str(node_result)[:200],
            )

        execution_result["input"] = text

        # Phase 3: Reflect (if requested by the decomposer)
        if dag.reflect and dag.nodes:
            with self.console.status(
                "[bold blue]Reflecting on results...[/bold blue]",
                spinner="dots",
            ):
                try:
                    reflect_timeout = self.runtime.config.cognitive.decomposition_timeout_seconds
                    import asyncio
                    reflection = await asyncio.wait_for(
                        self.runtime.decomposer.reflect(
                            text, execution_result
                        ),
                        timeout=reflect_timeout,
                    )
                    execution_result["reflection"] = reflection
                except Exception:
                    execution_result["reflection"] = (
                        "(Reflection unavailable — results shown above)"
                    )

        # Phase 4: Show results
        self.console.print(render_dag_result(execution_result, debug=self.debug))

        if self.debug:
            self._render_debug_results(execution_result)

        return execution_result

    # ------------------------------------------------------------------
    # Event callback
    # ------------------------------------------------------------------

    async def _on_execution_event(
        self, event: str, data: dict[str, Any]
    ) -> None:
        """Handle execution events and update the Live display."""
        node = data.get("node")
        if not node:
            return

        if event == "node_start":
            self._node_statuses[node.id] = "running"
        elif event == "node_complete":
            self._node_statuses[node.id] = "completed"
        elif event == "node_failed":
            self._node_statuses[node.id] = "failed"

        if self._live:
            self._live.update(self._build_progress_table())

    # ------------------------------------------------------------------
    # Display builders
    # ------------------------------------------------------------------

    def _build_progress_table(self) -> Table:
        """Build a progress table showing each DAG node's status."""
        table = Table(show_header=True, show_lines=False, title="Executing")
        table.add_column("Node", width=6)
        table.add_column("Intent")
        table.add_column("Status")
        table.add_column("Dependencies")

        if self._current_dag is None:
            return table

        for node in self._current_dag.nodes:
            status = self._node_statuses.get(node.id, "pending")
            if status == "pending":
                icon = _ICON_PENDING
                label = "[dim]pending[/dim]"
            elif status == "running":
                icon = _ICON_RUNNING
                label = "[bold blue]running[/bold blue]"
            elif status == "completed":
                icon = _ICON_DONE
                label = "[green]done[/green]"
            else:
                icon = _ICON_FAIL
                label = "[red]FAILED[/red]"

            deps = ", ".join(node.depends_on) if node.depends_on else "-"
            table.add_row(node.id, node.intent, f"{icon} {label}", deps)

        return table

    def _render_dag_plan(self, dag: TaskDAG) -> None:
        """Print the DAG structure before execution."""
        self.console.print(f"  [bold]Plan: {len(dag.nodes)} task(s)[/bold]")
        for node in dag.nodes:
            params_str = " ".join(f"{k}={v}" for k, v in node.params.items())
            consensus = " [yellow](consensus)[/yellow]" if node.use_consensus else ""
            deps = f" [dim]depends: {', '.join(node.depends_on)}[/dim]" if node.depends_on else ""
            self.console.print(f"    {node.id}: {node.intent} ({params_str}){consensus}{deps}")

    def _render_final_results(self, result: dict[str, Any]) -> None:
        """Print the final summary after DAG execution."""
        self.console.print(render_dag_result(result, debug=False))

    def _render_debug_dag(self, dag: TaskDAG) -> None:
        """Debug mode: print raw TaskDAG as formatted JSON."""
        dag_data = {
            "id": dag.id,
            "source_text": dag.source_text,
            "nodes": [
                {
                    "id": n.id,
                    "intent": n.intent,
                    "params": n.params,
                    "depends_on": n.depends_on,
                    "use_consensus": n.use_consensus,
                }
                for n in dag.nodes
            ],
        }
        self.console.print(Panel(
            json.dumps(dag_data, indent=2, default=str),
            title="DEBUG: TaskDAG",
            style="dim",
        ))

    def _render_debug_results(self, result: dict[str, Any]) -> None:
        """Debug mode: print individual agent responses and details."""
        lines: list[str] = []
        dag = result.get("dag")
        results = result.get("results", {})

        if dag and hasattr(dag, "nodes"):
            for node in dag.nodes:
                lines.append(f"[bold]Node {node.id}: {node.intent}[/bold]")

                node_res = results.get(node.id, {})
                if isinstance(node_res, dict):
                    # Show individual agent results
                    if "results" in node_res:
                        for ir in node_res["results"]:
                            if hasattr(ir, "agent_id"):
                                lines.append(
                                    f"  Agent {ir.agent_id[:8]}: "
                                    f"success={ir.success} "
                                    f"confidence={ir.confidence:.2f}"
                                )
                                if ir.result:
                                    preview = str(ir.result)[:120]
                                    lines.append(f"    result: {preview}")

                    # Show consensus details
                    if "consensus" in node_res:
                        c = node_res["consensus"]
                        if hasattr(c, "outcome"):
                            lines.append(
                                f"  Consensus: {c.outcome.value} "
                                f"(approval={c.approval_ratio:.2f})"
                            )
                    if "verifications" in node_res:
                        for v in node_res["verifications"]:
                            if hasattr(v, "verifier_id"):
                                lines.append(
                                    f"  Verification: "
                                    f"{v.verifier_id[:8]} -> {v.target_agent_id[:8]} "
                                    f"verified={v.verified}"
                                )
                else:
                    lines.append(f"  {str(node_res)[:200]}")

                lines.append("")

        if lines:
            self.console.print(Panel(
                "\n".join(lines),
                title="DEBUG: Agent Responses",
                style="dim",
            ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_capability_list(self) -> list[str]:
        """Extract capability strings from the runtime's capability registry."""
        if hasattr(self.runtime.capability_registry, "_capabilities"):
            return [
                cap.can
                for caps in self.runtime.capability_registry._capabilities.values()
                for cap in caps
            ]
        return []

    def _empty_result(self, text: str, dag: TaskDAG) -> dict[str, Any]:
        """Build an empty result dict for no-intent cases."""
        return {
            "input": text,
            "dag": dag,
            "results": {},
            "complete": True,
            "node_count": 0,
            "completed_count": 0,
            "failed_count": 0,
            "response": dag.response,
        }
