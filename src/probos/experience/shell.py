"""Async REPL for ProbOS — slash commands and natural language input."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.experience import panels
from probos.experience.panels import format_health
from probos.experience.renderer import ExecutionRenderer
from probos.runtime import ProbOSRuntime
from probos.types import AgentState

logger = logging.getLogger(__name__)


class ProbOSShell:
    """Interactive shell for ProbOS.

    Slash commands (``/status``, ``/agents``, etc.) inspect system state.
    Plain text is routed through the cognitive pipeline via
    ``ExecutionRenderer.process_with_feedback()``.
    """

    COMMANDS: dict[str, str] = {
        "/status":    "Show system status overview",
        "/agents":    "List all agents with trust scores",
        "/weights":   "Show Hebbian connection weights",
        "/gossip":    "Show gossip protocol view",
        "/log":       "Show recent event log entries (/log [category])",
        "/memory":    "Show working memory snapshot",
        "/attention": "Show attention queue and current focus",
        "/history":   "Show recent episodic memory entries",
        "/recall":    "Semantic recall from episodic memory (/recall <query>)",
        "/dream":     "Show last dream report (/dream now to trigger cycle)",
        "/cache":     "Show workflow cache entries",
        "/scaling":   "Show pool scaling status",
        "/federation": "Show federation status",
        "/peers":     "Show peer node models",
        "/designed":  "Show self-designed agent status",
        "/qa":        "Show QA status for designed agents (/qa [agent_type])",
        "/knowledge": "Show knowledge store status and history",
        "/rollback":  "Rollback a knowledge artifact (/rollback <type> <id>)",
        "/plan":      "Propose a plan (/plan <text> | /plan remove N | /plan)",
        "/approve":   "Execute pending proposal",
        "/reject":    "Discard pending proposal",
        "/feedback":  "Rate last execution (/feedback good|bad)",
        "/correct":   "Correct the last execution (/correct <what to fix>)",
        "/anomalies": "Show emergent behavior detection and system anomalies",
        "/search":    "Search across all knowledge (/search [--type agents,skills] <query>)",
        "/explain":   "Explain what happened in the last NL request",
        "/model":     "Show LLM client type, endpoint, and tier config",
        "/tier":      "Switch LLM tier (/tier fast|standard|deep)",
        "/prune":     "Permanently remove an agent (/prune <agent_id>)",
        "/imports":   "Manage allowed imports (/imports | /imports add <pkg> | /imports remove <pkg>)",
        "/ping":      "Show system uptime",
        "/debug":     "Toggle debug mode (/debug on|off)",
        "/help":      "Show this help message",
        "/quit":      "Exit ProbOS",
    }

    def __init__(
        self,
        runtime: ProbOSRuntime,
        console: Console | None = None,
    ) -> None:
        self.runtime = runtime
        self.console = console or Console()
        self.debug = False
        self.renderer = ExecutionRenderer(self.console, runtime, debug=self.debug)
        self._running = False

        # Wire user escalation callback
        if hasattr(self.runtime, "escalation_manager") and self.runtime.escalation_manager:
            self.runtime.escalation_manager.set_user_callback(
                self._user_escalation_callback
            )

        # Wire self-mod user approval callback
        if self.runtime.self_mod_pipeline:
            self.runtime.self_mod_pipeline._user_approval_fn = (
                self._user_self_mod_approval
            )
            self.runtime.self_mod_pipeline._import_approval_fn = (
                self._user_import_approval
            )

            # Wire dependency resolver approval callback (AD-214)
            if self.runtime.self_mod_pipeline._dependency_resolver:
                self.runtime.self_mod_pipeline._dependency_resolver._approval_fn = (
                    self._user_dep_install_approval
                )

    # ------------------------------------------------------------------
    # Health and prompt
    # ------------------------------------------------------------------

    def _compute_health(self) -> float:
        """Average confidence of all ACTIVE agents."""
        agents = self.runtime.registry.all()
        active = [a for a in agents if a.state == AgentState.ACTIVE]
        if not active:
            return 0.0
        return sum(a.confidence for a in active) / len(active)

    def _build_prompt(self) -> str:
        """Build the prompt string: [N agents | health: 0.XX] probos> """
        count = self.runtime.registry.count
        health = self._compute_health()
        return f"[{count} agents | health: {health:.2f}] probos> "

    # ------------------------------------------------------------------
    # REPL loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main REPL loop.  Reads input, dispatches to commands or NL."""
        self._running = True
        while self._running:
            try:
                prompt = self._build_prompt()
                loop = asyncio.get_event_loop()
                line = await loop.run_in_executor(None, lambda: input(prompt))
                await self.execute_command(line)
            except (EOFError, KeyboardInterrupt):
                self._running = False
                self.console.print("\n[dim]Goodbye.[/dim]")
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------

    async def execute_command(self, line: str) -> None:
        """Process a single input line.  Public API for testing."""
        line = line.strip()
        if not line:
            return

        if line.startswith("/"):
            await self._dispatch_slash(line)
        else:
            await self._handle_nl(line)

    async def _dispatch_slash(self, line: str) -> None:
        """Route slash commands to their handlers."""
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        handlers: dict[str, Any] = {
            "/status":  self._cmd_status,
            "/agents":  self._cmd_agents,
            "/weights": self._cmd_weights,
            "/gossip":  self._cmd_gossip,
            "/log":       self._cmd_log,
            "/memory":    self._cmd_memory,
            "/attention": self._cmd_attention,
            "/history":   self._cmd_history,
            "/recall":    self._cmd_recall,
            "/dream":     self._cmd_dream,
            "/cache":     self._cmd_cache,
            "/scaling":   self._cmd_scaling,
            "/federation": self._cmd_federation,
            "/peers":     self._cmd_peers,
            "/designed":  self._cmd_designed,
            "/qa":        self._cmd_qa,
            "/knowledge": self._cmd_knowledge,
            "/rollback":  self._cmd_rollback,
            "/plan":      self._cmd_plan,
            "/approve":   self._cmd_approve,
            "/reject":    self._cmd_reject,
            "/feedback":  self._cmd_feedback,
            "/correct":   self._cmd_correct,
            "/anomalies": self._cmd_anomalies,
            "/search":    self._cmd_search,
            "/explain":   self._cmd_explain,
            "/model":   self._cmd_model,
            "/tier":    self._cmd_tier,
            "/ping":    self._cmd_ping,
            "/prune":   self._cmd_prune,
            "/imports": self._cmd_imports,
            "/debug":   self._cmd_debug,
            "/help":    self._cmd_help,
            "/quit":    self._cmd_quit,
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                await handler(arg)
            except Exception as e:
                self.console.print(f"[red]Command error: {e}[/red]")
        else:
            self.console.print(f"[red]Unknown command: {cmd}[/red]")
            self.console.print("Type /help for available commands.")

    # ------------------------------------------------------------------
    # Slash command implementations
    # ------------------------------------------------------------------

    async def _cmd_status(self, arg: str) -> None:
        status = self.runtime.status()
        # Augment with episodic stats if available
        if self.runtime.episodic_memory:
            try:
                status["episodic_stats"] = await self.runtime.episodic_memory.get_stats()
            except Exception:
                pass
        self.console.print(panels.render_status_panel(status))

    async def _cmd_agents(self, arg: str) -> None:
        trust_scores = self.runtime.trust_network.all_scores()
        self.console.print(panels.render_agent_roster(
            self.runtime.pools,
            self.runtime.pool_groups,
            self.runtime.registry,
            trust_scores,
        ))

    async def _cmd_weights(self, arg: str) -> None:
        weights = self.runtime.hebbian_router.all_weights_typed()
        self.console.print(panels.render_weight_table(weights))

    async def _cmd_gossip(self, arg: str) -> None:
        view = self.runtime.gossip.get_view()
        self.console.print(panels.render_gossip_panel(view))

    async def _cmd_log(self, arg: str) -> None:
        category = arg if arg else None
        events = await self.runtime.event_log.query(category=category, limit=20)
        self.console.print(panels.render_event_log_table(events))

    async def _cmd_memory(self, arg: str) -> None:
        snapshot = self.runtime.working_memory.assemble(
            registry=self.runtime.registry,
            trust_network=self.runtime.trust_network,
            hebbian_router=self.runtime.hebbian_router,
        )
        self.console.print(panels.render_working_memory_panel(snapshot))

    async def _cmd_attention(self, arg: str) -> None:
        queue = self.runtime.attention.get_queue_snapshot()
        focus = self.runtime.attention.current_focus
        self.console.print(panels.render_attention_panel(
            queue, focus, focus_history=self.runtime.attention.focus_history,
        ))

    async def _cmd_history(self, arg: str) -> None:
        mem = self.runtime.episodic_memory
        if not mem:
            self.console.print("[yellow]Episodic memory is not enabled.[/yellow]")
            return
        episodes = await mem.recent(k=10)
        if not episodes:
            self.console.print("[dim]No episodes recorded yet.[/dim]")
            return
        from datetime import datetime
        table = Table(title="Recent Episodes")
        table.add_column("Time", style="dim")
        table.add_column("Input")
        table.add_column("Intents", justify="right")
        table.add_column("Success", justify="right")
        for ep in episodes:
            ts = datetime.fromtimestamp(ep.timestamp).strftime("%H:%M:%S") if ep.timestamp else "?"
            total = len(ep.outcomes)
            ok = sum(1 for o in ep.outcomes if o.get("success"))
            rate = f"{ok}/{total}" if total else "-"
            intents = ", ".join(o.get("intent", "?") for o in ep.outcomes) or "-"
            table.add_row(ts, ep.user_input[:60], intents, rate)
        self.console.print(table)

    async def _cmd_recall(self, arg: str) -> None:
        mem = self.runtime.episodic_memory
        if not mem:
            self.console.print("[yellow]Episodic memory is not enabled.[/yellow]")
            return
        if not arg:
            self.console.print("[yellow]Usage: /recall <query>[/yellow]")
            return
        episodes = await mem.recall(arg, k=3)
        if not episodes:
            self.console.print("[dim]No similar episodes found.[/dim]")
            return
        from datetime import datetime
        table = Table(title=f"Recall: {arg}")
        table.add_column("Time", style="dim")
        table.add_column("Input")
        table.add_column("Intents")
        table.add_column("Success", justify="right")
        for ep in episodes:
            ts = datetime.fromtimestamp(ep.timestamp).strftime("%H:%M:%S") if ep.timestamp else "?"
            total = len(ep.outcomes)
            ok = sum(1 for o in ep.outcomes if o.get("success"))
            rate = f"{ok}/{total}" if total else "-"
            intents = ", ".join(o.get("intent", "?") for o in ep.outcomes) or "-"
            table.add_row(ts, ep.user_input[:60], intents, rate)
        self.console.print(table)

    async def _cmd_dream(self, arg: str) -> None:
        scheduler = self.runtime.dream_scheduler
        if not scheduler:
            self.console.print("[yellow]Dreaming is not enabled (no episodic memory).[/yellow]")
            return
        if arg.strip().lower() == "now":
            self.console.print("[dim]Triggering dream cycle...[/dim]")
            report = await scheduler.force_dream()
            self.console.print(panels.render_dream_panel(report))
        else:
            self.console.print(panels.render_dream_panel(scheduler.last_dream_report))

    async def _cmd_cache(self, arg: str) -> None:
        cache = self.runtime.workflow_cache
        self.console.print(panels.render_workflow_cache_panel(
            cache.entries, cache.size,
        ))

    async def _cmd_scaling(self, arg: str) -> None:
        scaler = self.runtime.pool_scaler
        if not scaler:
            self.console.print("[yellow]Pool scaling is disabled.[/yellow]")
            return
        self.console.print(panels.render_scaling_panel(scaler.scaling_status()))

    async def _cmd_federation(self, arg: str) -> None:
        bridge = self.runtime.federation_bridge
        if not bridge:
            self.console.print("[yellow]Federation is not enabled.[/yellow]")
            return
        self.console.print(panels.render_federation_panel(bridge.federation_status()))

    async def _cmd_peers(self, arg: str) -> None:
        bridge = self.runtime.federation_bridge
        if not bridge:
            self.console.print("[yellow]Federation is not enabled.[/yellow]")
            return
        status = bridge.federation_status()
        self.console.print(panels.render_peers_panel(status.get("peer_models", {})))

    async def _cmd_designed(self, arg: str) -> None:
        if self.runtime.self_mod_pipeline:
            status = self.runtime.self_mod_pipeline.designed_agent_status()
            if self.runtime.behavioral_monitor:
                status["behavioral"] = self.runtime.behavioral_monitor.get_status()
            qa_reports = getattr(self.runtime, "_qa_reports", None) or None
            self.console.print(panels.render_designed_panel(status, qa_reports=qa_reports))
        else:
            self.console.print("[yellow]Self-modification not enabled[/yellow]")

    async def _cmd_qa(self, arg: str) -> None:
        from probos.experience.qa_panel import render_qa_panel, render_qa_detail

        qa_reports = getattr(self.runtime, "_qa_reports", {})
        if not qa_reports:
            self.console.print("[dim]No QA results yet.[/dim]")
            return

        if arg:
            report = qa_reports.get(arg)
            if report is None:
                self.console.print(f"[red]No QA report for agent type: {arg}[/red]")
                return
            self.console.print(render_qa_detail(arg, report, self.runtime.trust_network))
        else:
            self.console.print(render_qa_panel(qa_reports, self.runtime.trust_network))

    async def _cmd_knowledge(self, arg: str) -> None:
        from probos.experience.knowledge_panel import render_knowledge_panel, render_knowledge_history

        ks = getattr(self.runtime, "_knowledge_store", None)
        if ks is None:
            self.console.print("[dim]Knowledge store is not enabled.[/dim]")
            return

        if arg == "history":
            commits = await ks.recent_commits(20)
            self.console.print(render_knowledge_history(commits))
        else:
            counts = ks.artifact_counts()
            commit_count = await ks.commit_count()
            meta = await ks.meta_info()
            schema_version = meta.get("schema_version") if meta else None
            self.console.print(render_knowledge_panel(
                str(ks.repo_path), counts, commit_count, schema_version,
            ))

    async def _cmd_rollback(self, arg: str) -> None:
        from probos.experience.knowledge_panel import render_rollback_result

        ks = getattr(self.runtime, "_knowledge_store", None)
        if ks is None:
            self.console.print("[dim]Knowledge store is not enabled.[/dim]")
            return

        parts = arg.split(maxsplit=1)
        if len(parts) < 2:
            self.console.print("[yellow]Usage: /rollback <artifact_type> <identifier>[/yellow]")
            self.console.print("[dim]Example: /rollback trust snapshot[/dim]")
            return

        artifact_type, identifier = parts[0], parts[1]
        success = await ks.rollback_artifact(artifact_type, identifier)
        self.console.print(render_rollback_result(artifact_type, identifier, success))

    async def _cmd_plan(self, arg: str) -> None:
        """Handle /plan command: propose, re-display, or remove nodes."""
        from probos.cognitive.decomposer import is_capability_gap
        from probos.experience.panels import render_dag_proposal

        # /plan remove N
        if arg.startswith("remove "):
            remainder = arg[len("remove "):].strip()
            if not remainder:
                self.console.print("[yellow]Usage: /plan remove <N>[/yellow]")
                return
            if self.runtime._pending_proposal is None:
                self.console.print("[yellow]No pending proposal.[/yellow]")
                return
            try:
                idx = int(remainder)
            except ValueError:
                self.console.print(
                    "[red]Invalid node index. Use /plan to see current proposal.[/red]"
                )
                return
            removed = await self.runtime.remove_proposal_node(idx)
            if removed is None:
                self.console.print(
                    "[red]Invalid node index. Use /plan to see current proposal.[/red]"
                )
                return
            self.console.print(f"[dim]Removed step {idx}: {removed.intent}[/dim]")
            # Re-display updated proposal
            dag = self.runtime._pending_proposal
            if dag and dag.nodes:
                self.console.print(render_dag_proposal(dag))
            else:
                self.console.print("[dim]Proposal is now empty.[/dim]")
            return

        # /plan (no args) — re-display pending proposal
        if not arg:
            if self.runtime._pending_proposal is not None and self.runtime._pending_proposal.nodes:
                self.console.print(render_dag_proposal(self.runtime._pending_proposal))
            elif self.runtime._pending_proposal is not None:
                self.console.print("[dim]Pending proposal is empty (all steps removed).[/dim]")
            else:
                self.console.print("[yellow]Usage: /plan <text> to propose a plan[/yellow]")
            return

        # /plan <text> — propose a new plan
        self.console.print(f"\n[bold]> /plan {arg}[/bold]")
        with self.console.status(
            "[bold blue]Decomposing intent...[/bold blue]",
            spinner="dots",
        ):
            dag = await self.runtime.propose(arg)

        if not dag.nodes:
            is_gap = dag.capability_gap or (dag.response and is_capability_gap(dag.response))
            if dag.response and not is_gap:
                self.console.print(f"[cyan]{dag.response}[/cyan]")
                return

            # Capability gap — trigger self-mod flow same as normal NL
            if dag.response:
                self.console.print(f"[dim]{dag.response}[/dim]")

            if self.runtime.self_mod_pipeline:
                with self.console.status(
                    "[bold yellow]Analyzing unhandled request...[/bold yellow]",
                    spinner="dots",
                ):
                    intent_meta = await self.runtime._extract_unhandled_intent(arg)
                if intent_meta:
                    self.console.print(
                        f"[yellow]Capability gap detected: {intent_meta['name']}[/yellow]"
                    )
            else:
                self.console.print("[yellow]No actionable intents recognized.[/yellow]")
            return

        # Display proposed plan
        self.console.print(render_dag_proposal(dag))
        self.console.print(
            "[dim]Use /approve to execute, /reject to discard, "
            "or /plan remove N to remove a step[/dim]"
        )

    async def _cmd_approve(self, arg: str) -> None:
        """Execute the pending proposal."""
        if self.runtime._pending_proposal is None:
            self.console.print(
                "[yellow]No pending proposal. Use /plan <text> to create one.[/yellow]"
            )
            return

        if not self.runtime._pending_proposal.nodes:
            self.console.print("[yellow]Proposal is empty — nothing to execute.[/yellow]")
            await self.runtime.reject_proposal()
            return

        dag = self.runtime._pending_proposal
        node_count = len(dag.nodes)
        self.console.print(f"[bold]Executing {node_count} task(s)...[/bold]")

        # Execute through the renderer's event tracking
        self.renderer._current_dag = dag
        self.renderer._node_statuses = {n.id: "pending" for n in dag.nodes}

        self.renderer._status = self.console.status(
            f"[bold blue]Executing {node_count} task(s)...[/bold blue]",
            spinner="dots",
        )
        self.renderer._status.start()
        try:
            execution_result = await self.runtime.execute_proposal(
                on_event=self.renderer._on_execution_event,
            )
        finally:
            if self.renderer._status is not None:
                self.renderer._status.stop()
                self.renderer._status = None

        if execution_result is None:
            self.console.print("[yellow]No pending proposal.[/yellow]")
            return

        # Print progress table
        self.console.print(self.renderer._build_progress_table())

        # Force reflect for intents whose descriptors say requires_reflect
        if not dag.reflect and dag.nodes:
            reflect_intents: set[str] = set()
            for desc in self.runtime._collect_intent_descriptors():
                if desc.requires_reflect:
                    reflect_intents.add(desc.name)
            if self.runtime.self_mod_pipeline:
                for r in self.runtime.self_mod_pipeline._records:
                    if r.status == "active":
                        reflect_intents.add(r.intent_name)
            if any(n.intent in reflect_intents for n in dag.nodes):
                dag.reflect = True

        # Reflect if needed (already done in _execute_dag for the runtime path)
        # But we need to check if it wasn't done there
        if "reflection" not in execution_result and dag.reflect and dag.nodes:
            with self.console.status(
                "[bold blue]Reflecting on results...[/bold blue]",
                spinner="dots",
            ):
                try:
                    reflect_timeout = self.runtime.config.cognitive.decomposition_timeout_seconds
                    reflection = await asyncio.wait_for(
                        self.runtime.decomposer.reflect(
                            execution_result.get("input", ""),
                            execution_result,
                        ),
                        timeout=reflect_timeout,
                    )
                    execution_result["reflection"] = reflection
                except Exception:
                    execution_result["reflection"] = (
                        "(Reflection unavailable -- results shown above)"
                    )

        # Show results
        from probos.experience.panels import render_dag_result
        self.console.print(render_dag_result(execution_result, debug=self.debug))

        # Store execution result for introspection
        self.runtime._last_execution = execution_result

    async def _cmd_reject(self, arg: str) -> None:
        """Discard the pending proposal."""
        if await self.runtime.reject_proposal():
            self.console.print("[dim]Proposal discarded. Feedback recorded for future planning.[/dim]")
        else:
            self.console.print("[yellow]No pending proposal.[/yellow]")

    async def _cmd_feedback(self, arg: str) -> None:
        """Rate the last execution: /feedback good|bad."""
        arg = arg.strip().lower()
        if arg not in ("good", "bad"):
            self.console.print(
                "[dim]Usage: /feedback good|bad — rate the last execution[/dim]"
            )
            return

        if not hasattr(self.runtime, '_last_execution') or self.runtime._last_execution is None:
            self.console.print("[yellow]No recent execution to rate.[/yellow]")
            return

        if getattr(self.runtime, '_last_feedback_applied', False):
            self.console.print("[yellow]Feedback already recorded for this execution.[/yellow]")
            return

        positive = arg == "good"
        result = await self.runtime.record_feedback(positive)
        if result is None:
            self.console.print("[yellow]Could not record feedback.[/yellow]")
            return

        label = "positive" if positive else "negative"
        agents = result.agents_updated
        if agents:
            self.console.print(
                f"[dim]Feedback ({label}) applied to {len(agents)} agent(s). "
                f"Trust and routing weights updated.[/dim]"
            )
        else:
            self.console.print(f"[dim]Feedback ({label}) recorded.[/dim]")

    async def _cmd_correct(self, arg: str) -> None:
        """Explicit correction command: /correct <what to fix>."""
        if not arg:
            self.console.print(
                "[dim]Usage: /correct <what to fix> — correct the last execution's behavior[/dim]"
            )
            return

        if self.runtime._last_execution is None:
            self.console.print("[yellow]No recent execution to correct.[/yellow]")
            return

        if not self.runtime._correction_detector:
            self.console.print("[yellow]Correction detection is not enabled.[/yellow]")
            return

        # Detect correction signal
        correction = await self.runtime._correction_detector.detect(
            user_text=arg,
            last_execution_text=self.runtime._last_execution_text,
            last_execution_dag=self.runtime._last_execution,
            last_execution_success=self.runtime._was_last_execution_successful(),
        )

        if correction is None:
            self.console.print(
                "[yellow]Could not interpret correction. "
                "Try being more specific about what to change.[/yellow]"
            )
            return

        # Find designed agent record
        record = self.runtime._find_designed_record(correction.target_agent_type)
        if record is None:
            self.console.print(
                f"[yellow]No designed agent found for '{correction.target_agent_type}'. "
                f"Only self-designed agents can be corrected.[/yellow]"
            )
            return

        if not self.runtime._agent_patcher:
            self.console.print("[yellow]Agent patching is not enabled.[/yellow]")
            return

        # Patch the agent
        self.console.print("[dim]Generating patched agent...[/dim]")
        patch_result = await self.runtime._agent_patcher.patch(
            record, correction, self.runtime._last_execution_text or arg,
        )

        if not patch_result.success:
            self.console.print(
                f"[red]Correction failed: patched code did not pass validation[/red]"
            )
            if patch_result.error:
                self.console.print(f"  [red]Error: {patch_result.error}[/red]")
            self.console.print(
                "  [dim]You can try /feedback bad to mark this execution as negative.[/dim]"
            )
            return

        # Apply correction (hot-reload + retry)
        result = await self.runtime.apply_correction(
            correction, patch_result, record,
        )

        if result.success:
            self.console.print(
                f"[green]Correction applied to {result.agent_type} agent[/green]"
            )
            if result.changes_description:
                self.console.print(f"  [dim]Changed: {result.changes_description}[/dim]")
            if result.retried:
                if result.retry_result and result.retry_result.get("success"):
                    total = result.retry_result.get("total", 0)
                    ok = result.retry_result.get("completed", 0)
                    self.console.print(
                        f"  [dim]Retrying original request...[/dim]"
                    )
                    self.console.print(
                        f"  [green]Retry successful — {ok}/{total} tasks completed[/green]"
                    )
                else:
                    self.console.print(
                        "  [yellow]Retry did not fully succeed.[/yellow]"
                    )
        else:
            self.console.print(
                f"[red]Correction could not be applied to {result.agent_type}[/red]"
            )
            self.console.print(
                "  [dim]You can try /feedback bad to mark this execution as negative.[/dim]"
            )

    async def _cmd_search(self, arg: str) -> None:
        layer = getattr(self.runtime, "_semantic_layer", None)
        if layer is None:
            self.console.print("[yellow]Semantic knowledge layer not available[/yellow]")
            return

        # Parse optional --type filter
        query = arg.strip()
        types: list[str] | None = None
        if query.startswith("--type "):
            parts = query.split(maxsplit=2)
            if len(parts) >= 3:
                types = [t.strip() for t in parts[1].split(",") if t.strip()]
                query = parts[2]
            else:
                self.console.print("[yellow]Usage: /search [--type agents,skills] <query>[/yellow]")
                return

        if not query:
            self.console.print("[yellow]Usage: /search [--type agents,skills] <query>[/yellow]")
            return

        results = await layer.search(query, types=types, limit=10)
        stats = layer.stats()
        self.console.print(panels.render_search_panel(query, results, stats))

    async def _cmd_anomalies(self, arg: str) -> None:
        detector = getattr(self.runtime, "_emergent_detector", None)
        if detector is None:
            self.console.print("[yellow]Emergent detection not available[/yellow]")
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
        self.console.print(panels.render_anomalies_panel(summary, pattern_dicts))

    async def _cmd_explain(self, arg: str) -> None:
        await self._handle_nl("what just happened?")

    async def _cmd_model(self, arg: str) -> None:
        client = self.runtime.llm_client
        client_type = type(client).__name__

        lines: list[str] = []
        lines.append(f"[bold]LLM Client:[/bold] {client_type}")

        if isinstance(client, OpenAICompatibleClient):
            lines.append(f"[bold]Default tier:[/bold] {client.default_tier}")
            lines.append("")

            info = client.tier_info()
            # Track which URLs we've seen to note shared endpoints
            seen_urls: dict[str, str] = {}
            for tier in ("fast", "standard", "deep"):
                ti = info[tier]
                marker = " [dim](active)[/dim]" if tier == client.default_tier else ""
                reachable = ti.get("reachable")
                if reachable is True:
                    status = "[green]connected[/green]"
                elif reachable is False:
                    status = "[red]unreachable[/red]"
                else:
                    status = "[dim]unknown[/dim]"

                shared_note = ""
                if ti["base_url"] in seen_urls:
                    shared_note = f" [dim](shared with {seen_urls[ti['base_url']]})[/dim]"
                else:
                    seen_urls[ti["base_url"]] = tier

                lines.append(f"  [bold]{tier}:[/bold]{marker}")
                lines.append(f"    Endpoint: {ti['base_url']}{shared_note}")
                lines.append(f"    Model:    {ti['model']}")
                lines.append(f"    Status:   {status}")
                lines.append("")
        else:
            lines.append("[dim]Using pattern-matched mock responses (no live LLM).[/dim]")

        from rich.panel import Panel
        self.console.print(Panel("\n".join(lines), title="LLM Configuration", border_style="cyan"))

    async def _cmd_tier(self, arg: str) -> None:
        client = self.runtime.llm_client
        if not isinstance(client, OpenAICompatibleClient):
            self.console.print(
                "[yellow]Tier switching is only available with a live LLM endpoint. "
                "Currently using MockLLMClient.[/yellow]"
            )
            return

        valid_tiers = list(client.models.keys())
        if not arg:
            self.console.print(
                f"Current tier: [bold]{client.default_tier}[/bold] "
                f"(model: {client.models.get(client.default_tier, '?')})"
            )
            self.console.print(f"Available tiers: {', '.join(valid_tiers)}")
            return

        tier = arg.lower()
        if tier not in valid_tiers:
            self.console.print(
                f"[red]Unknown tier: {tier}[/red]. "
                f"Available: {', '.join(valid_tiers)}"
            )
            return

        client.default_tier = tier
        info = client.tier_info()
        ti = info[tier]
        self.console.print(
            f"Switched to [bold]{tier}[/bold] tier: "
            f"{ti['model']} at {ti['base_url']}"
        )

    async def _cmd_imports(self, arg: str) -> None:
        """List, add, or remove allowed imports for self-mod."""
        config = self.runtime.config.self_mod
        parts = arg.split(maxsplit=1)
        sub = parts[0].lower() if parts else ""

        if sub == "add" and len(parts) > 1:
            name = parts[1].strip()
            if name in config.allowed_imports:
                self.console.print(f"[dim]{name} is already in the whitelist[/dim]")
            else:
                config.allowed_imports.append(name)
                if self.runtime.self_mod_pipeline:
                    self.runtime.self_mod_pipeline._validator._allowed_imports.add(name)
                self.console.print(f"[green]Added '{name}' to allowed imports[/green]")
        elif sub == "remove" and len(parts) > 1:
            name = parts[1].strip()
            if name not in config.allowed_imports:
                self.console.print(f"[dim]{name} is not in the whitelist[/dim]")
            else:
                config.allowed_imports.remove(name)
                if self.runtime.self_mod_pipeline:
                    self.runtime.self_mod_pipeline._validator._allowed_imports.discard(name)
                self.console.print(f"[yellow]Removed '{name}' from allowed imports[/yellow]")
        else:
            # List current imports
            imports = sorted(config.allowed_imports)
            self.console.print(f"[bold]Allowed imports ({len(imports)}):[/bold]")
            # Group into lines of 6
            for i in range(0, len(imports), 6):
                chunk = ", ".join(imports[i:i + 6])
                self.console.print(f"  {chunk}")

    async def _cmd_debug(self, arg: str) -> None:
        if arg.lower() == "on":
            self.debug = True
        elif arg.lower() == "off":
            self.debug = False
        else:
            self.debug = not self.debug
        self.renderer.debug = self.debug
        state = "on" if self.debug else "off"
        self.console.print(f"Debug mode: [bold]{state}[/bold]")

    async def _cmd_prune(self, arg: str) -> None:
        if not arg:
            self.console.print("[yellow]Usage: /prune <agent_id>[/yellow]")
            return

        agent_id = arg.strip()
        agent = self.runtime.registry.get(agent_id)
        if agent is None:
            self.console.print(f"[red]Agent not found: {agent_id}[/red]")
            return

        self.console.print(
            f"[bold yellow]Remove agent {agent_id} permanently? "
            f"This cannot be undone. [y/n][/bold yellow]"
        )
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: input("  Confirm: ").strip().lower()
        )
        if response not in ("y", "yes"):
            self.console.print("[dim]Prune cancelled.[/dim]")
            return

        removed = await self.runtime.prune_agent(agent_id)
        if removed:
            self.console.print(f"[green]Agent {agent_id} pruned.[/green]")
        else:
            self.console.print(f"[red]Failed to prune agent {agent_id}.[/red]")

    async def _cmd_ping(self, arg: str) -> None:
        """Show system uptime and basic health metrics (AD-337)."""
        status = self.runtime.status()
        
        # Extract uptime from system model (via mesh -> self_model)
        mesh = status.get("mesh", {})
        self_model = mesh.get("self_model", {})
        uptime = self_model.get("uptime_seconds")
        
        # Get agent counts and health
        total_agents = status.get("total_agents", 0)
        agents = self.runtime.registry.all()
        active_agents = [a for a in agents if a.state == AgentState.ACTIVE]
        active_count = len(active_agents)
        health_score = self._compute_health()
        
        # Build status display
        if uptime is not None:
            uptime_text = self._format_uptime(uptime)
            status_line = f"[green]●[/green] System Status: ACTIVE"
        else:
            uptime_text = "unavailable"
            status_line = f"[yellow]●[/yellow] System Status: UNKNOWN"
        
        # Display system information
        self.console.print(status_line)
        self.console.print(f"Uptime: {uptime_text}")
        self.console.print(f"Agents: {active_count} active / {total_agents} total (health: {health_score:.2f})")
        
        # Show connectivity status if available
        cognitive = status.get("cognitive", {})
        if cognitive:
            llm_status = cognitive.get("llm_client_ready", False)
            if llm_status:
                self.console.print("[green]LLM Client: Connected[/green]")
            else:
                self.console.print("[yellow]LLM Client: Disconnected[/yellow]")

    def _format_uptime(self, seconds: float) -> str:
        """Convert seconds to human-readable uptime format."""
        total_seconds = int(seconds)
        
        if total_seconds < 60:
            return f"{total_seconds} seconds"
        
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        remaining_seconds = total_seconds % 60
        
        if days > 0:
            return f"{days} days, {hours} hours, {minutes} minutes"
        elif hours > 0:
            return f"{hours} hours, {minutes} minutes, {remaining_seconds} seconds"
        else:
            return f"{minutes} minutes, {remaining_seconds} seconds"

    async def _cmd_help(self, arg: str) -> None:
        table = Table(title="Commands", show_header=False)
        table.add_column("Command", style="bold cyan")
        table.add_column("Description")
        for cmd, desc in self.COMMANDS.items():
            table.add_row(cmd, desc)
        self.console.print(table)

    async def _cmd_quit(self, arg: str) -> None:
        self._running = False
        self.console.print("[dim]Shutting down...[/dim]")

    # ------------------------------------------------------------------
    # Natural language handler
    # ------------------------------------------------------------------

    async def _handle_nl(self, text: str) -> None:
        """Process natural language input through the renderer."""
        try:
            await self.renderer.process_with_feedback(text)
        except Exception as e:
            self.console.print(f"[red]Processing error: {e}[/red]")

    # ------------------------------------------------------------------
    # Escalation user callback
    # ------------------------------------------------------------------

    async def _user_escalation_callback(
        self, description: str, context: dict
    ) -> bool | None:
        """Prompt the user for escalation decision."""
        intent = context.get('intent', '?')
        params = context.get('params', {})
        error = context.get('error', '')

        self.console.print(
            f"\n[yellow bold]⚠ Escalation — your decision needed:[/yellow bold]"
        )
        self.console.print(f"  [bold]Intent:[/bold] [cyan]{intent}[/cyan]")

        # Show params so user knows what the operation is trying to do
        if params:
            for k, v in params.items():
                val = str(v)
                if len(val) > 120:
                    val = val[:120] + "..."
                self.console.print(f"  [bold]{k}:[/bold] {val}")

        self.console.print(f"  [bold]Error:[/bold] [red]{error}[/red]")

        # Show what was already tried
        tiers_tried = context.get('tiers_attempted', [])
        if tiers_tried:
            tried_names = [t.value if hasattr(t, 'value') else str(t) for t in tiers_tried]
            self.console.print(f"  [bold]Already tried:[/bold] [dim]{' → '.join(tried_names)}[/dim]")

        self.console.print(
            f"\n  [dim]'y' = force approve  |  'n' = reject  |  Enter = skip[/dim]"
        )

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("  Decision [y/n/skip]: ").strip().lower()
            )
            if response in ("y", "yes"):
                return True
            elif response in ("n", "no"):
                return False
            else:
                return None  # Skip
        except (EOFError, KeyboardInterrupt):
            return None

    # ------------------------------------------------------------------
    # Self-mod approval callback
    # ------------------------------------------------------------------

    async def _user_self_mod_approval(self, description: str) -> bool:
        """Prompt the user to approve or reject a self-designed agent."""
        self.console.print(
            "\n[yellow bold]🔧 Self-Modification — approval needed:[/yellow bold]"
        )
        self.console.print(f"  {description}")
        self.console.print(
            "  [dim]'y' = approve  |  'n' = reject[/dim]"
        )

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("  Approve? [y/n]: ").strip().lower()
            )
            return response in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    # ------------------------------------------------------------------
    # Import whitelist approval callback
    # ------------------------------------------------------------------

    async def _user_import_approval(self, import_names: list[str]) -> bool:
        """Prompt the user to approve adding imports to the whitelist."""
        if self.renderer._status is not None:
            self.renderer._status.stop()
            self.renderer._status = None

        self.console.print(
            "\n[yellow bold]This agent uses imports not on the whitelist:[/yellow bold]"
        )
        for name in import_names:
            self.console.print(f"  [bold]\u2022[/bold] {name}")
        self.console.print(
            "  [dim]'y' = allow (adds to whitelist)  |  'n' = block[/dim]"
        )

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("  Allow? [y/n]: ").strip().lower()
            )
            return response in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False
    # ------------------------------------------------------------------
    # Dependency install approval callback (AD-214)
    # ------------------------------------------------------------------

    async def _user_dep_install_approval(self, packages: list[str]) -> bool:
        """Prompt the user to approve package installation."""
        # Stop any active spinner so the user can interact with stdin
        if self.renderer._status is not None:
            self.renderer._status.stop()
            self.renderer._status = None

        self.console.print(
            "\n[yellow bold]This agent requires packages that are not installed:[/yellow bold]"
        )
        for pkg in packages:
            self.console.print(f"  [bold]\u2022[/bold] {pkg}")
        self.console.print()

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("Install with uv add? [y/n]: ").strip().lower()
            )
            return response in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False
