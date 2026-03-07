"""Shell command agent — executes shell commands, gated by consensus."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentMessage, IntentResult

logger = logging.getLogger(__name__)


class ShellCommandAgent(BaseAgent):
    """Concrete agent that executes shell commands.

    HIGH-RISK: All commands go through consensus (enforced at
    the DAG level via use_consensus=true).

    Capabilities: run_command.
    """

    agent_type: str = "shell_command"
    default_capabilities = [
        CapabilityDescriptor(
            can="run_command",
            detail="Execute a shell command and return output",
        ),
    ]
    initial_confidence: float = 0.8

    _handled_intents = {"run_command"}

    # Security constants
    DEFAULT_TIMEOUT: float = 30.0
    MAX_OUTPUT_BYTES: int = 64 * 1024  # 64KB cap on stdout/stderr

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report."""
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None

        plan = await self.decide(observation)
        if plan is None:
            return None

        result = await self.act(plan)
        report = await self.report(result)

        success = report.get("success", False)
        self.update_confidence(success)

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("data"),
            error=report.get("error"),
            confidence=self.confidence,
        )

    async def perceive(self, intent: dict[str, Any]) -> Any:
        """Check if this intent is something we handle."""
        intent_name = intent.get("intent", "")
        if intent_name not in self._handled_intents:
            return None
        return {
            "intent": intent_name,
            "params": intent.get("params", {}),
        }

    async def decide(self, observation: Any) -> Any:
        """Plan what to do based on the perceived intent."""
        params = observation["params"]
        command = params.get("command", "")

        if not command or not command.strip():
            return {"action": "error", "error": "No command specified"}

        return {"action": "run", "command": command}

    async def act(self, plan: Any) -> Any:
        """Execute the planned operation."""
        action = plan.get("action")

        if action == "error":
            return {"success": False, "error": plan["error"]}

        if action == "run":
            return await self._run_command(plan["command"])

        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package the result for the mesh."""
        return result

    async def _run_command(self, command: str) -> dict[str, Any]:
        """Execute a shell command with timeout and output capping."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.DEFAULT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {
                    "success": False,
                    "error": f"Command timed out after {self.DEFAULT_TIMEOUT}s",
                }

            stdout = stdout_bytes[:self.MAX_OUTPUT_BYTES].decode(
                "utf-8", errors="replace"
            )
            stderr = stderr_bytes[:self.MAX_OUTPUT_BYTES].decode(
                "utf-8", errors="replace"
            )

            return {
                "success": True,
                "data": {
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": proc.returncode,
                    "command": command,
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
