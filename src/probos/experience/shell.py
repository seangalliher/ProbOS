"""Async REPL for ProbOS — slash commands and natural language input."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from rich.console import Console

from probos.experience.commands import (
    commands_status,
    commands_plan,
    commands_directives,
    commands_procedure,
    commands_gap,
    commands_qualification,
    commands_autonomous,
    commands_memory,
    commands_knowledge,
    commands_llm,
    commands_introspection,
)
from probos.experience.commands.approval_callbacks import (
    user_escalation_callback,
    user_self_mod_approval,
    user_import_approval,
    user_dep_install_approval,
)
from probos.experience.commands.session import SessionManager
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
        "/models":    "Show active LLM tier configuration (endpoints, models, status)",
        "/registry":  "Show all available models across all sources (tiers, Copilot SDK, local)",
        "/orders":    "Show Standing Orders hierarchy and summaries",
        "/procedure": "Procedure governance (list-pending, approve, reject, list-promoted)",
        "/gap":       "Gap reports (list, detail, check, summary)",
        "/qualify":   "Run qualification tests or view results (/qualify [run|status|agent <id>|baselines])",
        "/tier":      "Switch LLM tier (/tier fast|standard|deep)",
        "/ping":      "Show system uptime",
        "/prune":     "Permanently remove an agent (/prune <agent_id>)",
        "/imports":   "Manage allowed imports (/imports | /imports add <pkg> | /imports remove <pkg>)",
        "/order":      "Issue a directive (/order <agent_type> <text>)",
        "/amend":      "Amend an existing directive (/amend <id> <new text>)",
        "/revoke":     "Revoke a directive (/revoke <id>)",
        "/directives": "Show active directives (/directives [agent_type])",
        "/conn":        "Manage the conn (/conn <callsign> | /conn return | /conn status | /conn log)",
        "/night-orders": "Set Night Orders (/night-orders <template> [ttl_hours] | /night-orders expire | /night-orders status)",
        "/watch":       "Show watch bill status (/watch)",
        "/scout":     "Run scout intelligence scan (/scout) or view report (/scout report)",
        "/credentials": "List registered credentials and their status (/credentials)",
        "/bridge":    "Return to bridge (exit 1:1 crew session)",
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
        self._start_time: float | None = None

        # AD-397: 1:1 session manager
        self.session = SessionManager()

        # Wire user escalation callback
        if hasattr(self.runtime, "escalation_manager") and self.runtime.escalation_manager:
            self.runtime.escalation_manager.set_user_callback(
                lambda desc, ctx: user_escalation_callback(self.console, desc, ctx)
            )

        # Wire self-mod user approval callback
        if self.runtime.self_mod_pipeline:
            self.runtime.self_mod_pipeline._user_approval_fn = (
                lambda desc: user_self_mod_approval(self.console, desc)
            )
            self.runtime.self_mod_pipeline._import_approval_fn = (
                lambda names: user_import_approval(self.console, self.renderer, names)
            )

            # Wire dependency resolver approval callback (AD-214)
            if self.runtime.self_mod_pipeline._dependency_resolver:
                self.runtime.self_mod_pipeline._dependency_resolver._approval_fn = (
                    lambda pkgs: user_dep_install_approval(self.console, self.renderer, pkgs)
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
        """Build the prompt string: session mode or normal bridge mode."""
        if self.session.active:
            return f"{self.session.callsign} \u25b8 "
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
                loop = asyncio.get_running_loop()
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

        # 1:1 session mode — route to session agent (AD-397)
        if self.session.active and not line.startswith("/"):
            # BF-009: detect @callsign anywhere for session-switching
            from probos.crew_profile import extract_callsign_mention
            mention = extract_callsign_mention(line)
            if mention:
                # Allow switching sessions via @callsign during a session
                await self.session.handle_at_parsed(
                    mention[0], mention[1], self.runtime, self.console,
                )
            else:
                await self.session.handle_message(line, self.runtime, self.console)
            return

        # BF-009: detect @callsign anywhere in the line
        from probos.crew_profile import extract_callsign_mention as _ecm
        mention = _ecm(line)
        if mention:
            await self.session.handle_at_parsed(
                mention[0], mention[1], self.runtime, self.console,
            )
        elif line.startswith("/"):
            await self._dispatch_slash(line)
        else:
            await self._handle_nl(line)

    async def _dispatch_slash(self, line: str) -> None:
        """Route slash commands to their handlers."""
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        rt, con, rnd = self.runtime, self.console, self.renderer

        handlers: dict[str, Any] = {
            "/status":     lambda: commands_status.cmd_status(rt, con, arg),
            "/agents":     lambda: commands_status.cmd_agents(rt, con, arg),
            "/ping":       lambda: commands_status.cmd_ping(rt, con, arg),
            "/scaling":    lambda: commands_status.cmd_scaling(rt, con, arg),
            "/federation": lambda: commands_status.cmd_federation(rt, con, arg),
            "/peers":      lambda: commands_status.cmd_peers(rt, con, arg),
            "/credentials": lambda: commands_status.cmd_credentials(rt, con, arg),
            "/debug":      lambda: commands_status.cmd_debug(rt, con, arg, shell=self),
            "/help":       lambda: commands_status.cmd_help(con, self.COMMANDS),

            "/plan":       lambda: commands_plan.cmd_plan(rt, con, rnd, arg),
            "/approve":    lambda: commands_plan.cmd_approve(rt, con, rnd, arg),
            "/reject":     lambda: commands_plan.cmd_reject(rt, con, arg),
            "/feedback":   lambda: commands_plan.cmd_feedback(rt, con, arg),
            "/correct":    lambda: commands_plan.cmd_correct(rt, con, arg),

            "/orders":     lambda: commands_directives.cmd_orders(rt, con, arg),
            "/order":      lambda: commands_directives.cmd_order(rt, con, arg),
            "/directives": lambda: commands_directives.cmd_directives(rt, con, arg),
            "/revoke":     lambda: commands_directives.cmd_revoke(rt, con, arg),
            "/amend":      lambda: commands_directives.cmd_amend(rt, con, arg),
            "/imports":    lambda: commands_directives.cmd_imports(rt, con, arg),

            "/procedure":  lambda: commands_procedure.cmd_procedure(rt, con, arg),
            "/gap":        lambda: commands_gap.cmd_gap(rt, con, arg),
            "/qualify":    lambda: commands_qualification.cmd_qualify(rt, con, arg),

            "/conn":         lambda: commands_autonomous.cmd_conn(rt, con, arg),
            "/night-orders": lambda: commands_autonomous.cmd_night_orders(rt, con, arg),
            "/watch":        lambda: commands_autonomous.cmd_watch(rt, con, arg),

            "/memory":     lambda: commands_memory.cmd_memory(rt, con, arg),
            "/history":    lambda: commands_memory.cmd_history(rt, con, arg),
            "/recall":     lambda: commands_memory.cmd_recall(rt, con, arg),
            "/dream":      lambda: commands_memory.cmd_dream(rt, con, arg),

            "/knowledge":  lambda: commands_knowledge.cmd_knowledge(rt, con, arg),
            "/rollback":   lambda: commands_knowledge.cmd_rollback(rt, con, arg),
            "/search":     lambda: commands_knowledge.cmd_search(rt, con, arg),
            "/anomalies":  lambda: commands_knowledge.cmd_anomalies(rt, con, arg),
            "/scout":      lambda: commands_knowledge.cmd_scout(rt, con, arg),

            "/models":     lambda: commands_llm.cmd_models(rt, con, arg),
            "/registry":   lambda: commands_llm.cmd_registry(rt, con, arg),
            "/tier":       lambda: commands_llm.cmd_tier(rt, con, arg),

            "/weights":    lambda: commands_introspection.cmd_weights(rt, con, arg),
            "/gossip":     lambda: commands_introspection.cmd_gossip(rt, con, arg),
            "/designed":   lambda: commands_introspection.cmd_designed(rt, con, arg),
            "/qa":         lambda: commands_introspection.cmd_qa(rt, con, arg),
            "/prune":      lambda: commands_introspection.cmd_prune(rt, con, arg),
            "/log":        lambda: commands_introspection.cmd_log(rt, con, arg),
            "/attention":  lambda: commands_introspection.cmd_attention(rt, con, arg),
            "/cache":      lambda: commands_introspection.cmd_cache(rt, con, arg),

            "/explain":    lambda: self._handle_nl("what just happened?"),
            "/bridge":     lambda: self._cmd_bridge(),
            "/quit":       lambda: self._cmd_quit(arg),
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                await handler()
            except Exception as e:
                self.console.print(f"[red]Command error: {e}[/red]")
        else:
            self.console.print(f"[red]Unknown command: {cmd}[/red]")
            self.console.print("Type /help for available commands.")

    # ------------------------------------------------------------------
    # Natural language handler
    # ------------------------------------------------------------------

    async def _handle_nl(self, text: str) -> None:
        """Process natural language input through the renderer."""
        try:
            await self.renderer.process_with_feedback(text)
        except Exception as e:
            self.console.print(f"[red]Processing error: {e}[/red]")

    async def _cmd_bridge(self) -> None:
        """Exit 1:1 session — delegates to SessionManager."""
        self.session.exit_session(self.console)

    # ------------------------------------------------------------------
    # Quit (stays in shell — controls REPL loop)
    # ------------------------------------------------------------------

    async def _cmd_quit(self, arg: str) -> None:
        self._quit_reason = arg.strip() if arg else ""
        self._running = False
        self.console.print("[dim]Shutting down...[/dim]")

    # ------------------------------------------------------------------
    # Backward-compatible session state properties (AD-519)
    # Tests reference shell._session_* fields; proxy to SessionManager.
    # ------------------------------------------------------------------

    @property
    def _session_callsign(self) -> str | None:
        return self.session.callsign

    @_session_callsign.setter
    def _session_callsign(self, value: str | None) -> None:
        self.session.callsign = value

    @property
    def _session_agent_id(self) -> str | None:
        return self.session.agent_id

    @_session_agent_id.setter
    def _session_agent_id(self, value: str | None) -> None:
        self.session.agent_id = value

    @property
    def _session_agent_type(self) -> str | None:
        return self.session.agent_type

    @_session_agent_type.setter
    def _session_agent_type(self, value: str | None) -> None:
        self.session.agent_type = value

    @property
    def _session_department(self) -> str | None:
        return self.session.department

    @_session_department.setter
    def _session_department(self, value: str | None) -> None:
        self.session.department = value

    @property
    def _session_history(self) -> list[dict[str, str]]:
        return self.session.history

    @_session_history.setter
    def _session_history(self, value: list[dict[str, str]]) -> None:
        self.session.history = value

    # ------------------------------------------------------------------
    # Backward-compatible command proxies (AD-519)
    # Tests call shell._cmd_* directly; delegate to extracted modules.
    # ------------------------------------------------------------------

    async def _cmd_status(self, arg: str) -> None:
        await commands_status.cmd_status(self.runtime, self.console, arg)

    async def _cmd_agents(self, arg: str) -> None:
        await commands_status.cmd_agents(self.runtime, self.console, arg)

    async def _cmd_ping(self, arg: str) -> None:
        await commands_status.cmd_ping(self.runtime, self.console, arg)

    async def _cmd_scaling(self, arg: str) -> None:
        await commands_status.cmd_scaling(self.runtime, self.console, arg)

    async def _cmd_federation(self, arg: str) -> None:
        await commands_status.cmd_federation(self.runtime, self.console, arg)

    async def _cmd_peers(self, arg: str) -> None:
        await commands_status.cmd_peers(self.runtime, self.console, arg)

    async def _cmd_credentials(self, arg: str) -> None:
        await commands_status.cmd_credentials(self.runtime, self.console, arg)

    async def _cmd_debug(self, arg: str) -> None:
        await commands_status.cmd_debug(self.runtime, self.console, arg, shell=self)

    async def _cmd_help(self, arg: str) -> None:
        await commands_status.cmd_help(self.console, self.COMMANDS)

    async def _cmd_plan(self, arg: str) -> None:
        await commands_plan.cmd_plan(self.runtime, self.console, self.renderer, arg)

    async def _cmd_approve(self, arg: str) -> None:
        await commands_plan.cmd_approve(self.runtime, self.console, self.renderer, arg)

    async def _cmd_reject(self, arg: str) -> None:
        await commands_plan.cmd_reject(self.runtime, self.console, arg)

    async def _cmd_feedback(self, arg: str) -> None:
        await commands_plan.cmd_feedback(self.runtime, self.console, arg)

    async def _cmd_correct(self, arg: str) -> None:
        await commands_plan.cmd_correct(self.runtime, self.console, arg)

    async def _cmd_orders(self, arg: str) -> None:
        await commands_directives.cmd_orders(self.runtime, self.console, arg)

    async def _cmd_order(self, arg: str) -> None:
        await commands_directives.cmd_order(self.runtime, self.console, arg)

    async def _cmd_directives(self, arg: str) -> None:
        await commands_directives.cmd_directives(self.runtime, self.console, arg)

    async def _cmd_revoke(self, arg: str) -> None:
        await commands_directives.cmd_revoke(self.runtime, self.console, arg)

    async def _cmd_amend(self, arg: str) -> None:
        await commands_directives.cmd_amend(self.runtime, self.console, arg)

    async def _cmd_imports(self, arg: str) -> None:
        await commands_directives.cmd_imports(self.runtime, self.console, arg)

    async def _cmd_conn(self, arg: str) -> None:
        await commands_autonomous.cmd_conn(self.runtime, self.console, arg)

    async def _cmd_night_orders(self, arg: str) -> None:
        await commands_autonomous.cmd_night_orders(self.runtime, self.console, arg)

    async def _cmd_watch(self, arg: str) -> None:
        await commands_autonomous.cmd_watch(self.runtime, self.console, arg)

    async def _cmd_memory(self, arg: str) -> None:
        await commands_memory.cmd_memory(self.runtime, self.console, arg)

    async def _cmd_history(self, arg: str) -> None:
        await commands_memory.cmd_history(self.runtime, self.console, arg)

    async def _cmd_recall(self, arg: str) -> None:
        await commands_memory.cmd_recall(self.runtime, self.console, arg)

    async def _cmd_dream(self, arg: str) -> None:
        await commands_memory.cmd_dream(self.runtime, self.console, arg)

    async def _cmd_knowledge(self, arg: str) -> None:
        await commands_knowledge.cmd_knowledge(self.runtime, self.console, arg)

    async def _cmd_rollback(self, arg: str) -> None:
        await commands_knowledge.cmd_rollback(self.runtime, self.console, arg)

    async def _cmd_search(self, arg: str) -> None:
        await commands_knowledge.cmd_search(self.runtime, self.console, arg)

    async def _cmd_anomalies(self, arg: str) -> None:
        await commands_knowledge.cmd_anomalies(self.runtime, self.console, arg)

    async def _cmd_scout(self, arg: str) -> None:
        await commands_knowledge.cmd_scout(self.runtime, self.console, arg)

    async def _cmd_models(self, arg: str) -> None:
        await commands_llm.cmd_models(self.runtime, self.console, arg)

    async def _cmd_registry(self, arg: str) -> None:
        await commands_llm.cmd_registry(self.runtime, self.console, arg)

    async def _cmd_tier(self, arg: str) -> None:
        await commands_llm.cmd_tier(self.runtime, self.console, arg)

    async def _cmd_weights(self, arg: str) -> None:
        await commands_introspection.cmd_weights(self.runtime, self.console, arg)

    async def _cmd_gossip(self, arg: str) -> None:
        await commands_introspection.cmd_gossip(self.runtime, self.console, arg)

    async def _cmd_designed(self, arg: str) -> None:
        await commands_introspection.cmd_designed(self.runtime, self.console, arg)

    async def _cmd_qa(self, arg: str) -> None:
        await commands_introspection.cmd_qa(self.runtime, self.console, arg)

    async def _cmd_prune(self, arg: str) -> None:
        await commands_introspection.cmd_prune(self.runtime, self.console, arg)

    async def _cmd_log(self, arg: str) -> None:
        await commands_introspection.cmd_log(self.runtime, self.console, arg)

    async def _cmd_attention(self, arg: str) -> None:
        await commands_introspection.cmd_attention(self.runtime, self.console, arg)

    async def _cmd_cache(self, arg: str) -> None:
        await commands_introspection.cmd_cache(self.runtime, self.console, arg)

    async def _cmd_explain(self, arg: str) -> None:
        await self._handle_nl("what just happened?")

    # ------------------------------------------------------------------
    # Backward-compatible helper proxies (AD-519)
    # ------------------------------------------------------------------

    def _format_uptime(self, seconds: float) -> str:
        return commands_status.format_uptime(seconds)

    def _get_callsign(self, agent_type: str) -> str:
        return commands_directives.get_callsign(agent_type)

    async def _user_escalation_callback(
        self, description: str, context: dict
    ) -> bool | None:
        return await user_escalation_callback(self.console, description, context)

    async def _user_self_mod_approval(self, description: str) -> bool:
        return await user_self_mod_approval(self.console, description)

    async def _user_import_approval(self, import_names: list[str]) -> bool:
        return await user_import_approval(self.console, self.renderer, import_names)

    async def _user_dep_install_approval(self, packages: list[str]) -> bool:
        return await user_dep_install_approval(self.console, self.renderer, packages)
