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
        "/explain":   "Explain what happened in the last NL request",
        "/model":     "Show LLM client type, endpoint, and tier config",
        "/tier":      "Switch LLM tier (/tier fast|standard|deep)",
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
            "/explain":   self._cmd_explain,
            "/model":   self._cmd_model,
            "/tier":    self._cmd_tier,
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
        agents = self.runtime.registry.all()
        trust_scores = self.runtime.trust_network.all_scores()
        self.console.print(panels.render_agent_table(agents, trust_scores))

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
            self.console.print(panels.render_designed_panel(status))
        else:
            self.console.print("[yellow]Self-modification not enabled[/yellow]")

    async def _cmd_explain(self, arg: str) -> None:
        await self._handle_nl("what just happened?")

    async def _cmd_model(self, arg: str) -> None:
        client = self.runtime.llm_client
        client_type = type(client).__name__

        lines: list[str] = []
        lines.append(f"[bold]LLM Client:[/bold] {client_type}")

        if isinstance(client, OpenAICompatibleClient):
            lines.append(f"[bold]Endpoint:[/bold]   {client.base_url}")
            lines.append(f"[bold]Timeout:[/bold]    {client.timeout}s")
            lines.append(f"[bold]Default tier:[/bold] {client.default_tier}")
            lines.append("")
            lines.append("[bold]Tier model mapping:[/bold]")
            for tier, model in sorted(client.models.items()):
                marker = " [dim](active)[/dim]" if tier == client.default_tier else ""
                lines.append(f"  {tier:10s} {model}{marker}")
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
        self.console.print(
            f"Tier switched to [bold]{tier}[/bold] "
            f"(model: {client.models[tier]})"
        )

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
