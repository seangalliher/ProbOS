"""AD-1019c: MCP consensus proposer — the voter population for ``mcp_invoke``.

DD-1 option A. A ``CONSENSUS``-tier MCP tool invocation is routed through the
existing quorum via ``runtime.submit_mcp_invoke_with_consensus`` (which mirrors
``submit_write_with_consensus``). That broadcasts an ``mcp_invoke`` intent and
collects votes — but no existing pool answers ``mcp_invoke`` (it is a new
intent), so a bare broadcast would yield **zero voters → INSUFFICIENT → always
blocked**. This minimal utility agent is the voting population: it responds to
``mcp_invoke`` with a **proposal only** — it validates the request shape and
sets ``requires_consensus=True`` on its result, and it **NEVER executes the
invoke**. The runtime performs the ``MCPBridge.invoke`` *commit* only on
``APPROVED`` (the era-4 / AD-362 guard).

Exact ``FileWriterAgent`` parity (propose-only + a runtime-side commit), one
pool, ``tier="utility"`` (it operates on the governance system, not for the
user).
"""

from __future__ import annotations

import logging
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)


class McpConsensusProposer(BaseAgent):
    """Propose-only voter for ``mcp_invoke`` consensus (AD-1019c).

    The invoke is NOT executed here. The agent proposes the invoke and sets
    ``requires_consensus=True`` on its result; the runtime's consensus layer
    must approve before ``MCPBridge.invoke`` commits. Mirrors
    :class:`~probos.agents.file_writer.FileWriterAgent`.

    Capabilities: ``mcp_invoke``.
    """

    agent_type: str = "mcp_consensus_proposer"
    tier = "utility"
    default_capabilities = [
        CapabilityDescriptor(
            can="mcp_invoke",
            detail="Propose a consensus-gated MCP tool invocation (does not execute)",
            formats=["json"],
        ),
    ]
    initial_confidence: float = 0.8
    intent_descriptors = [
        IntentDescriptor(
            name="mcp_invoke",
            params={
                "server_url": "<bridge_key>",
                "tool": "<tool_name>",
                "arguments": "{...}",
            },
            description="Invoke a tool on a registered MCP server (consensus-gated)",
            requires_consensus=True,
        ),
    ]

    _handled_intents = {"mcp_invoke"}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report.

        The act phase proposes the invoke but does NOT commit it. The runtime
        consensus layer calls ``MCPBridge.invoke`` only if approved.
        """
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
        """Validate the proposed invoke shape (no side effects)."""
        params = observation["params"]
        server_url = params.get("server_url")
        tool = params.get("tool")

        if not server_url:
            return {"action": "error", "error": "No server_url specified"}
        if not tool:
            return {"action": "error", "error": "No tool specified"}

        return {
            "action": "propose",
            "server_url": server_url,
            "tool": tool,
            "arguments": params.get("arguments") or {},
        }

    async def act(self, plan: Any) -> Any:
        """Return a proposal — the invoke is NEVER executed here.

        The actual ``MCPBridge.invoke`` happens in the runtime after consensus
        approval (``submit_mcp_invoke_with_consensus``).
        """
        action = plan.get("action")

        if action == "error":
            return {"success": False, "error": plan["error"]}

        if action == "propose":
            return {
                "success": True,
                "data": {
                    "server_url": plan["server_url"],
                    "tool": plan["tool"],
                    "arguments": plan["arguments"],
                    "requires_consensus": True,
                },
            }

        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package the result for the mesh."""
        return result
