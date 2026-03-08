"""Real-time execution display — spinners, live progress, debug output.

The ``ExecutionRenderer`` orchestrates the cognitive pipeline stages itself
(working memory assembly, decompose, execute, record results) so it can
insert different Rich display modes (spinner vs Live) between stages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.strategy import StrategyOption, StrategyRecommender
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
        self._current_dag: TaskDAG | None = None
        self._node_statuses: dict[str, str] = {}
        self._status = None

        # Wire pre-user hook so Tier 3 escalation stops Live before prompting
        if hasattr(runtime, 'escalation_manager') and runtime.escalation_manager:
            runtime.escalation_manager.set_pre_user_hook(self._stop_live_for_user)

    def _stop_live_for_user(self) -> None:
        """Stop the spinner so the user can interact with the escalation prompt."""
        if self._status is not None:
            self._status.stop()
            self._status = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process_with_feedback(self, text: str) -> dict[str, Any]:
        """Process NL input with real-time visual feedback.

        Returns the same dict as ``runtime.process_natural_language()``.
        """
        self.console.print(f"\n[bold]> {text}[/bold]")
        t_start = time.monotonic()

        # Snapshot previous execution for introspection (AD-34 duplication)
        self.runtime._previous_execution = self.runtime._last_execution

        # Update attention focus with current request
        self.runtime.attention.update_focus(intent=text, context=text)

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
            # Recall similar past episodes if episodic memory is available
            similar_episodes = None
            if self.runtime.episodic_memory:
                try:
                    similar_episodes = await self.runtime.episodic_memory.recall(text, k=3)
                except Exception as e:
                    logger.warning("Episode recall failed: %s", e)

            # Sync pre-warm intents from dreaming engine to decomposer
            if self.runtime.dream_scheduler and self.runtime.dream_scheduler.last_dream_report:
                self.runtime.decomposer.pre_warm_intents = (
                    self.runtime.dream_scheduler.engine.pre_warm_intents
                )

            dag = await self.runtime.decomposer.decompose(
                text, context=context, similar_episodes=similar_episodes or None,
            )

        if self.debug:
            raw = self.runtime.decomposer.last_raw_response
            tier = self.runtime.decomposer.last_tier or "?"
            model = self.runtime.decomposer.last_model or "?"
            self.console.print(Panel(
                raw or "[dim]<empty>[/dim]",
                title=f"DEBUG: Raw LLM Response  [bold]{tier}[/bold] / {model}",
                style="dim",
            ))

        if not dag.nodes:
            # If the decomposer returned a genuine conversational response
            # (greeting, help text, etc.), show it and skip self-mod.
            # But if the response indicates a *capability gap* ("I don't
            # have X"), still let self-mod try to create the agent.
            if dag.response and not is_capability_gap(dag.response):
                self.console.print(f"[cyan]{dag.response}[/cyan]")
                return self._empty_result(text, dag)

            # Show the capability-gap response before self-mod kicks in
            if dag.response:
                self.console.print(f"[dim]{dag.response}[/dim]")

            # Self-modification: try to design an agent for this unhandled intent
            if self.runtime.self_mod_pipeline:
                with self.console.status(
                    "[bold yellow]Analyzing unhandled request...[/bold yellow]",
                    spinner="dots",
                ):
                    intent_meta = await self.runtime._extract_unhandled_intent(text)
                if intent_meta:
                    # Check if this intent already exists (LLM extracted
                    # an existing capability the decomposer didn't route to)
                    existing_names = {
                        d.name for d in self.runtime._collect_intent_descriptors()
                    }
                    if intent_meta["name"] in existing_names:
                        actual = intent_meta.get(
                            "actual_values", intent_meta.get("parameters", {})
                        )
                        dag = TaskDAG(
                            nodes=[TaskNode(
                                id="t1",
                                intent=intent_meta["name"],
                                params=actual,
                                use_consensus=intent_meta.get(
                                    "requires_consensus", False
                                ),
                            )],
                            source_text=text,
                            reflect=True,
                        )
                        intent_meta = None  # skip self-mod flow below

                if intent_meta:
                    # Phase A: Strategy proposal
                    recommender = StrategyRecommender(
                        intent_descriptors=self.runtime._collect_intent_descriptors(),
                        llm_equipped_types=self.runtime._get_llm_equipped_types()
                        if hasattr(self.runtime, "_get_llm_equipped_types")
                        else set(),
                    )
                    proposal = recommender.propose(
                        intent_name=intent_meta["name"],
                        intent_description=intent_meta["description"],
                        parameters=intent_meta.get("parameters", {}),
                    )

                    # Display strategy options
                    self.console.print(
                        "\n[yellow bold]\U0001f527 Self-Modification Proposal:[/yellow bold]"
                    )
                    self.console.print(
                        f"  [bold]Unhandled intent:[/bold] [cyan]{intent_meta['name']}[/cyan]"
                    )
                    self.console.print(
                        f"  [bold]Purpose:[/bold] {intent_meta['description']}"
                    )
                    self.console.print()

                    if len(proposal.options) == 1:
                        # Single option — simpler prompt
                        opt = proposal.options[0]
                        self.console.print(
                            f"  [bold]Strategy:[/bold] {opt.label} "
                            f"(confidence: {opt.confidence})"
                        )
                        self.console.print(f"  [dim]{opt.reason}[/dim]")
                        prompt_text = "  Approve? [y/n]: "
                    else:
                        # Multiple options — numbered menu
                        for i, opt in enumerate(proposal.options, 1):
                            star = "\u2605 " if opt.is_recommended else "  "
                            self.console.print(
                                f"  [{i}] {star}{opt.label}  "
                                f"(confidence: {opt.confidence})"
                            )
                            if opt.target_agent_type:
                                self.console.print(
                                    f"      Target: {opt.target_agent_type} (has LLM access)"
                                )
                            self.console.print(f"      [dim]{opt.reason}[/dim]")
                        prompt_text = f"  Choose strategy [1-{len(proposal.options)}] or [n] to cancel: "

                    try:
                        resp = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: input(prompt_text).strip().lower()
                        )
                    except (EOFError, KeyboardInterrupt, OSError):
                        resp = "n"

                    # Determine chosen strategy
                    chosen_option: StrategyOption | None = None
                    if len(proposal.options) == 1:
                        if resp in ("y", "yes"):
                            chosen_option = proposal.options[0]
                    elif resp.isdigit():
                        idx = int(resp) - 1
                        if 0 <= idx < len(proposal.options):
                            chosen_option = proposal.options[idx]

                    if chosen_option is None:
                        self.console.print("[dim]Self-modification rejected by user.[/dim]")
                    else:
                        # Phase B: Execute chosen strategy
                        orig_approval = self.runtime.self_mod_pipeline._user_approval_fn
                        self.runtime.self_mod_pipeline._user_approval_fn = None
                        try:
                            if chosen_option.strategy == "add_skill" and hasattr(
                                self.runtime.self_mod_pipeline, "handle_add_skill"
                            ):
                                with self.console.status(
                                    "[bold yellow]Designing skill...[/bold yellow]",
                                    spinner="dots",
                                ):
                                    record = await self.runtime.self_mod_pipeline.handle_add_skill(
                                        intent_name=intent_meta["name"],
                                        intent_description=intent_meta["description"],
                                        parameters=intent_meta.get("parameters", {}),
                                        target_agent_type=chosen_option.target_agent_type or "skill_agent",
                                    )
                            else:
                                with self.console.status(
                                    "[bold yellow]Designing agent...[/bold yellow]",
                                    spinner="dots",
                                ):
                                    record = await self.runtime.self_mod_pipeline.handle_unhandled_intent(
                                        intent_name=intent_meta["name"],
                                        intent_description=intent_meta["description"],
                                        parameters=intent_meta.get("parameters", {}),
                                        requires_consensus=intent_meta.get("requires_consensus", False),
                                    )
                        finally:
                            self.runtime.self_mod_pipeline._user_approval_fn = orig_approval

                        if record and record.status == "active":
                            strategy_label = "Skill" if chosen_option.strategy == "add_skill" else "Agent"
                            self.console.print(
                                f"  [green bold]\u2713 {strategy_label} '{record.agent_type}' "
                                f"designed and registered[/green bold]"
                            )
                            # Phase C: Execute directly with the new intent
                            actual = intent_meta.get("actual_values", intent_meta.get("parameters", {}))
                            dag = TaskDAG(
                                nodes=[TaskNode(
                                    id="t1",
                                    intent=intent_meta["name"],
                                    params=actual,
                                    use_consensus=intent_meta.get("requires_consensus", False),
                                )],
                                source_text=text,
                                reflect=True,
                            )
                        elif record:
                            self.console.print(
                                f"  [yellow]\u2717 Design failed: "
                                f"{record.status.replace('_', ' ')}[/yellow]"
                            )
                        else:
                            self.console.print(
                                "  [yellow]\u2717 Agent design failed.[/yellow]"
                            )

        if not dag.nodes:
            self.console.print("[yellow]No actionable intents recognized.[/yellow]")
            return self._empty_result(text, dag)

        if self.debug:
            # Show DAG plan only in debug mode (Live table shows same info)
            self._render_dag_plan(dag)

        if self.debug:
            self._render_debug_dag(dag)

        # Phase 2: Execute with Live display
        self._current_dag = dag
        self._node_statuses = {n.id: "pending" for n in dag.nodes}

        # Record intents in working memory
        for node in dag.nodes:
            self.runtime.working_memory.record_intent(node.intent, node.params)

        node_count = len(dag.nodes)
        self._status = self.console.status(
            f"[bold blue]Executing {node_count} task(s)...[/bold blue]",
            spinner="dots",
        )
        self._status.start()
        try:
            execution_result = await self.runtime.dag_executor.execute(
                dag, on_event=self._on_execution_event
            )
        finally:
            if self._status is not None:
                self._status.stop()
                self._status = None
        # Print final table with completed statuses
        self.console.print(self._build_progress_table())

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

        # Force reflect for intents whose descriptors say requires_reflect
        # (the LLM often ignores the reflect rule).  This covers both
        # built-in agents (run_command, introspect, etc.) and designed ones.
        if not dag.reflect and dag.nodes:
            reflect_intents: set[str] = set()
            # Built-in intent descriptors
            for desc in self.runtime._collect_intent_descriptors():
                if desc.requires_reflect:
                    reflect_intents.add(desc.name)
            # Designed agent intents
            if self.runtime.self_mod_pipeline:
                for r in self.runtime.self_mod_pipeline._records:
                    if r.status == "active":
                        reflect_intents.add(r.intent_name)
            if any(n.intent in reflect_intents for n in dag.nodes):
                dag.reflect = True

        # Phase 3: Reflect (if requested by the decomposer)
        if dag.reflect and dag.nodes:
            with self.console.status(
                "[bold blue]Reflecting on results...[/bold blue]",
                spinner="dots",
            ):
                try:
                    reflect_timeout = self.runtime.config.cognitive.decomposition_timeout_seconds
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

        # Store episode in episodic memory (fire-and-forget)
        if self.runtime.episodic_memory and dag.nodes:
            try:
                t_end = time.monotonic()
                episode = self.runtime._build_episode(
                    text, execution_result, t_start, t_end,
                )
                await self.runtime.episodic_memory.store(episode)
            except Exception as e:
                logger.warning("Episode storage failed: %s: %s", type(e).__name__, e)

        # Store successful workflows in cache
        if self.runtime.workflow_cache and dag.nodes:
            all_success = all(n.status == "completed" for n in dag.nodes)
            if all_success:
                self.runtime.workflow_cache.store(text, dag)

        # Phase 4: Show results
        self.console.print(render_dag_result(execution_result, debug=self.debug))

        if self.debug:
            self._render_debug_results(execution_result)

        # Store execution result for introspection (AD-34 duplication)
        self.runtime._last_execution = execution_result

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
        elif event == "escalation_start":
            self._node_statuses[node.id] = "escalating"
        elif event == "escalation_resolved":
            self._node_statuses[node.id] = "completed"
        elif event == "escalation_exhausted":
            self._node_statuses[node.id] = "failed"
        elif event == "scale_up":
            pass  # Logged by scaler; no node status change needed
        elif event == "scale_down":
            pass  # Logged by scaler; no node status change needed
        elif event == "federation_forward":
            pass  # Logged by bridge; no node status change needed
        elif event == "federation_receive":
            pass  # Logged by bridge; no node status change needed
        elif event == "self_mod_design":
            pass  # Logged by pipeline
        elif event == "self_mod_success":
            pass  # Logged by pipeline
        elif event == "self_mod_failure":
            pass  # Logged by pipeline



    # ------------------------------------------------------------------
    # Display builders
    # ------------------------------------------------------------------

    def _build_progress_table(self) -> Table:
        """Build a progress table showing each DAG node's status."""
        node_count = len(self._current_dag.nodes) if self._current_dag else 0
        table = Table(show_header=True, show_lines=False, title=f"Executing {node_count} task(s)")
        table.add_column("Node", width=6)
        table.add_column("Intent")
        table.add_column("Params", max_width=40)
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
            elif status == "escalating":
                icon = _ICON_RUNNING
                label = "[bold yellow]escalating[/bold yellow]"
            elif status == "completed":
                icon = _ICON_DONE
                label = "[green]done[/green]"
            else:
                icon = _ICON_FAIL
                label = "[red]FAILED[/red]"

            params_str = " ".join(f"{k}={v}" for k, v in node.params.items()) if node.params else "-"
            deps = ", ".join(node.depends_on) if node.depends_on else "-"
            table.add_row(node.id, node.intent, f"[dim]{params_str}[/dim]", f"{icon} {label}", deps)

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
