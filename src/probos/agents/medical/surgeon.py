"""SurgeonAgent — acute remediation actions for the medical pool (AD-290)."""

from __future__ import annotations

import logging
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)

_INSTRUCTIONS = (
    "You are the ProbOS Surgeon.  You receive remediation orders from the Diagnostician "
    "and execute the safest corrective action.\n\n"
    "Available actions (pick one based on diagnosis):\n"
    "- recycle_agent: Trigger pool health check to recycle a degraded agent\n"
    "- force_dream: Trigger immediate dream consolidation cycle\n"
    "- surge_pool: Scale up an underperforming pool temporarily\n\n"
    "NEVER prune an agent with fewer than 10 trust observations.\n\n"
    'Respond with JSON: {"action": "recycle_agent|force_dream|surge_pool", "target": "...", "reason": "..."}'
)


class SurgeonAgent(CognitiveAgent):
    agent_type = "surgeon"
    tier = "domain"
    instructions = _INSTRUCTIONS
    default_capabilities = [
        CapabilityDescriptor(can="remediate", detail="Acute system remediation actions"),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="medical_remediate",
            params={
                "action": "recycle_agent|force_dream|surge_pool",
                "target": "pool name or agent ID",
                "diagnosis": "diagnosis object from Diagnostician",
            },
            description="Execute a remediation action based on diagnosis",
        ),
    ]
    _handled_intents = {"medical_remediate"}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("pool", "medical")
        super().__init__(**kwargs)

    async def act(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Execute the remediation action via runtime."""
        # AD-398/BF-024: pass through conversational responses for 1:1, ward room, and proactive
        if decision.get("intent") in ("direct_message", "ward_room_notification", "proactive_think"):
            return {"success": True, "result": decision.get("llm_output", "")}
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}

        rt = self._runtime
        if not rt:
            return {"success": False, "error": "No runtime reference"}

        llm_output = decision.get("llm_output", "")
        action = decision.get("action", "execute")

        # Parse the LLM output for action
        import json as _json
        try:
            parsed = _json.loads(llm_output) if isinstance(llm_output, str) else {}
        except (ValueError, TypeError):
            parsed = {}

        remediation_action = parsed.get("action", "")
        target = parsed.get("target", "")

        try:
            if remediation_action == "force_dream":
                if rt.dream_scheduler and hasattr(rt.dream_scheduler, "engine"):
                    report = await rt.dream_scheduler.engine.dream_cycle()
                    await self._log_remediation(rt, remediation_action, target, True)
                    return {"success": True, "result": f"Dream cycle completed: {report}"}
                return {"success": False, "error": "Dream scheduler not available"}

            elif remediation_action == "surge_pool":
                if rt.pool_scaler:
                    await rt.pool_scaler.request_surge(target, extra=1)
                    await self._log_remediation(rt, remediation_action, target, True)
                    return {"success": True, "result": f"Surge requested for pool {target}"}
                return {"success": False, "error": "Pool scaler not available"}

            elif remediation_action == "recycle_agent":
                pool = rt.pools.get(target)
                if pool:
                    await pool.check_health()
                    await self._log_remediation(rt, remediation_action, target, True)
                    return {"success": True, "result": f"Health check triggered for pool {target}"}
                return {"success": False, "error": f"Pool {target} not found"}

            else:
                return {"success": True, "result": llm_output}

        except Exception as e:
            logger.warning("Surgeon action %s failed: %s", remediation_action, e)
            await self._log_remediation(rt, remediation_action, target, False)
            return {"success": False, "error": str(e)}

    async def _log_remediation(
        self, rt: Any, action: str, target: str, success: bool
    ) -> None:
        """Log a remediation action to the event log."""
        if hasattr(rt, "event_log") and rt.event_log:
            await rt.event_log.log(
                category="medical",
                event="remediation",
                agent_id=self.id,
                detail=f"action={action} target={target} success={success}",
            )
