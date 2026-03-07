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
        "/status":  "Show system status overview",
        "/agents":  "List all agents with trust scores",
        "/weights": "Show Hebbian connection weights",
        "/gossip":  "Show gossip protocol view",
        "/log":     "Show recent event log entries (/log [category])",
        "/memory":  "Show working memory snapshot",
        "/history": "Show recent episodic memory entries",
        "/recall":  "Semantic recall from episodic memory (/recall <query>)",
        "/model":   "Show LLM client type, endpoint, and tier config",
        "/tier":    "Switch LLM tier (/tier fast|standard|deep)",
        "/debug":   "Toggle debug mode (/debug on|off)",
        "/help":    "Show this help message",
        "/quit":    "Exit ProbOS",
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
            "/log":     self._cmd_log,
            "/memory":  self._cmd_memory,
            "/history": self._cmd_history,
            "/recall":  self._cmd_recall,
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
