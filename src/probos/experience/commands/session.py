"""1:1 session management for ProbOSShell (AD-397)."""
from __future__ import annotations

import logging
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages 1:1 @callsign agent sessions."""

    def __init__(self) -> None:
        self.callsign: str | None = None
        self.agent_id: str | None = None
        self.agent_type: str | None = None
        self.department: str | None = None
        self.history: list[dict[str, str]] = []

    @property
    def active(self) -> bool:
        return bool(self.callsign)

    async def handle_at(self, line: str, runtime: Any, console: Console) -> None:
        """Parse @callsign and enter 1:1 session mode."""
        from probos.crew_profile import extract_callsign_mention
        mention = extract_callsign_mention(line)
        if not mention:
            console.print("[red]Usage: @callsign [message][/red]")
            return
        await self.handle_at_parsed(mention[0], mention[1], runtime, console)

    async def handle_at_parsed(
        self, callsign: str, message: str, runtime: Any, console: Console
    ) -> None:
        """Resolve callsign and enter 1:1 session mode (BF-009)."""
        if not callsign:
            console.print("[red]Usage: @callsign [message][/red]")
            return

        resolved = runtime.callsign_registry.resolve(callsign)
        if resolved is None:
            console.print(
                f"[red]Unknown crew member: @{callsign}. Use /agents to see available crew.[/red]"
            )
            return

        if resolved["agent_id"] is None:
            console.print(
                f"[yellow]{resolved['callsign']} is not currently on duty.[/yellow]"
            )
            return

        # Enter 1:1 session
        self.callsign = resolved["callsign"]
        self.agent_id = resolved["agent_id"]
        self.agent_type = resolved["agent_type"]
        self.department = resolved["department"]
        self.history = []

        # Cross-session recall — seed with agent's own past memories
        if runtime.episodic_memory and hasattr(runtime.episodic_memory, "recall_for_agent"):
            try:
                past = await runtime.episodic_memory.recall_for_agent(
                    agent_id=resolved["agent_id"],
                    query=f"1:1 with {resolved['callsign']}",
                    k=3,
                )
                # BF-028: Fallback to recent episodes when semantic recall misses
                if not past and hasattr(runtime.episodic_memory, 'recent_for_agent'):
                    past = await runtime.episodic_memory.recent_for_agent(
                        resolved["agent_id"], k=3
                    )
                for ep in past:
                    self.history.append({
                        "role": "system",
                        "text": f"[Your memory of a previous conversation] {ep.user_input}",
                    })
            except Exception:
                pass

        if message:
            await self.handle_message(message, runtime, console)
        else:
            dept = resolved["department"] or "unknown"
            console.print(
                f"[cyan][1:1 with {resolved['callsign']} ({dept})] "
                f"Type /bridge to return to the bridge.[/cyan]"
            )

    async def handle_message(
        self, text: str, runtime: Any, console: Console
    ) -> None:
        """Dispatch a message to the current 1:1 session agent."""
        if not self.agent_id or not self.callsign:
            return

        from probos.types import IntentMessage, Episode

        intent = IntentMessage(
            intent="direct_message",
            params={
                "text": text,
                "from": "captain",
                "session": True,
                "session_history": self.history,
            },
            target_agent_id=self.agent_id,
        )

        result = await runtime.intent_bus.send(intent)
        response_text = ""
        if result and result.result:
            response_text = str(result.result)

        if not response_text:
            response_text = "(no response)"

        # Display with callsign
        dept = self.department or ""
        dept_colors = {
            "science": "blue",
            "engineering": "yellow",
            "medical": "green",
            "security": "red",
        }
        color = dept_colors.get(dept, "white")
        console.print(f"[{color}]{self.callsign}[/{color}]: {response_text}")

        # Accumulate session history
        self.history.append({"role": "captain", "text": text})
        self.history.append({"role": self.callsign, "text": response_text})

        # Store episodic memory
        if runtime.episodic_memory:
            try:
                import time as _time
                episode = Episode(
                    user_input=f"[1:1 with {self.callsign}] Captain: {text}",
                    timestamp=_time.time(),
                    agent_ids=[self.agent_id],
                    outcomes=[{
                        "intent": "direct_message",
                        "success": True,
                        "response": response_text,
                        "session_type": "1:1",
                        "callsign": self.callsign,
                        "agent_type": self.agent_type,
                    }],
                    reflection=f"Captain had a 1:1 conversation with {self.callsign}.",
                )
                await runtime.episodic_memory.store(episode)
            except Exception:
                pass

    def exit_session(self, console: Console) -> None:
        """Return to bridge — exit 1:1 session (/bridge)."""
        if self.callsign:
            console.print("[cyan]Returned to bridge.[/cyan]")
            self.callsign = None
            self.agent_id = None
            self.agent_type = None
            self.department = None
            self.history = []
        else:
            console.print("[dim]You're already on the bridge.[/dim]")
