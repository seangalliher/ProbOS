"""AD-843c-2: device consensus proposer — the voter population for ``device_actuate``.

A ``CONSENSUS``-tier sensitive device actuation (``device.location`` /
``device.camera`` / ``device.screen``) is routed through the existing quorum via
``runtime.submit_device_actuate_with_consensus`` (which mirrors
``submit_mcp_invoke_with_consensus``). That broadcasts the internal
``device_actuate`` proposal intent and collects votes — but no existing pool
answers ``device_actuate`` (it is a new intent), so a bare broadcast would yield
**zero voters → INSUFFICIENT → always blocked**. This minimal utility agent is
the voting population: it responds to ``device_actuate`` with a **proposal only**
— it validates the request shape and sets ``requires_consensus=True`` on its
result, and it **NEVER actuates the device**. The runtime performs the
``DeviceNodeAdapter.actuate`` *commit* only on ``APPROVED`` (the era-4 / AD-362
guard).

Exact ``McpConsensusProposer`` parity (propose-only + a runtime-side commit),
one pool, ``tier="utility"`` (it operates on the governance system, not for the
user).

Layer discipline: imports ONLY ``probos.substrate.agent`` + ``probos.types``.
NO consensus/mesh/cognitive/runtime imports — the commit gate is the runtime's.
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


class DeviceConsensusProposer(BaseAgent):
    """Propose-only voter for ``device_actuate`` consensus (AD-843c-2).

    The actuation is NOT executed here. The agent proposes the actuation and sets
    ``requires_consensus=True`` on its result; the runtime's consensus layer must
    approve before ``DeviceNodeAdapter.actuate`` commits. Mirrors
    :class:`~probos.agents.mcp_consensus_proposer.McpConsensusProposer`.

    Capabilities: ``device_actuate``.
    """

    agent_type: str = "device_consensus_proposer"
    tier = "utility"
    default_capabilities = [
        CapabilityDescriptor(
            can="device_actuate",
            detail="Propose a consensus-gated sensitive device actuation (does not execute)",
            formats=["json"],
        ),
    ]
    initial_confidence: float = 0.8
    intent_descriptors = [
        IntentDescriptor(
            name="device_actuate",
            params={
                "device_id": "<paired device id>",
                "intent_name": "device.location|device.camera|device.screen",
                "params": "{...}",
            },
            description="Actuate a sensitive intent on a paired device (consensus-gated)",
            requires_consensus=True,
        ),
    ]

    _handled_intents = {"device_actuate"}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Full lifecycle: perceive -> decide -> act -> report.

        The act phase proposes the actuation but does NOT commit it. The runtime
        consensus layer calls ``DeviceNodeAdapter.actuate`` only if approved.
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
        """Validate the proposed actuation shape (no side effects)."""
        params = observation["params"]
        device_id = params.get("device_id")
        target_intent = params.get("intent_name")

        if not device_id:
            return {"action": "error", "error": "No device_id specified"}
        if not target_intent:
            return {"action": "error", "error": "No intent_name specified"}

        return {
            "action": "propose",
            "device_id": device_id,
            "intent_name": target_intent,
            "params": params.get("params") or {},
        }

    async def act(self, plan: Any) -> Any:
        """Return a proposal — the actuation is NEVER executed here.

        The actual ``DeviceNodeAdapter.actuate`` happens in the runtime after
        consensus approval (``submit_device_actuate_with_consensus``).
        """
        action = plan.get("action")

        if action == "error":
            return {"success": False, "error": plan["error"]}

        if action == "propose":
            return {
                "success": True,
                "data": {
                    "device_id": plan["device_id"],
                    "intent_name": plan["intent_name"],
                    "params": plan["params"],
                    "requires_consensus": True,
                },
            }

        return {"success": False, "error": f"Unknown action: {action}"}

    async def report(self, result: Any) -> dict[str, Any]:
        """Package the result for the mesh."""
        return result
