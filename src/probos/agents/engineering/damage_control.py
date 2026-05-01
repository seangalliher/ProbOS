"""AD-457: Damage Control Agent — coordinated response to known failure modes."""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.events import EventType
from probos.substrate.heartbeat import HeartbeatAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)


# Recovery procedures: failure_signature -> recovery_action_name.
# Recovery actions are emitted as DAMAGE_CONTROL_ACTIVATED events; the
# corresponding subsystem handler is responsible for execution.
_RECOVERY_TABLE: dict[str, str] = {
    "llm_brownout": "llm_failover_to_secondary_tier",
    "nats_disconnect": "nats_reconnect_and_resync_streams",
    "chromadb_corruption": "chroma_replay_from_episodic_log",
    "pool_starvation": "pool_rebalance_and_promote_probationary",
}


class DamageControlAgent(HeartbeatAgent):
    agent_type = "damage_control"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="damage_control",
            detail="Coordinated recovery for known failure modes",
        ),
    ]
    intent_descriptors: list[IntentDescriptor] = [
        IntentDescriptor(
            name="damage_control_activate",
            params={
                "signature": "failure signature (llm_brownout, nats_disconnect, ...)",
                "recovery_action": "recovery action name",
            },
            description="Activate a damage-control recovery procedure",
        ),
    ]
    initial_confidence = 0.95

    def __init__(
        self,
        pool: str = "engineering_damage_control",
        interval: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(pool=pool, interval=interval, **kwargs)
        self._runtime = kwargs.get("runtime")
        self._recovery_table: dict[str, str] = dict(
            kwargs.get("recovery_table", _RECOVERY_TABLE),
        )
        self._recent_activations: dict[str, float] = {}
        self._cooldown_seconds: float = kwargs.get("cooldown_seconds", 60.0)

    async def collect_metrics(self) -> dict[str, Any]:
        # Damage control is event-driven, not poll-driven.
        # Heartbeat surface kept for parity with the engineering crew shape.
        return {"recent_activations": dict(self._recent_activations)}

    def activate(self, signature: str) -> bool:
        """Look up signature in recovery table, emit activation event.

        Returns True if a recovery was activated, False if no match or
        within cooldown.
        """
        recovery = self._recovery_table.get(signature)
        if recovery is None:
            return False
        now = time.time()
        last = self._recent_activations.get(signature, 0.0)
        if now - last < self._cooldown_seconds:
            return False
        self._recent_activations[signature] = now
        rt = self._runtime
        if rt is not None:
            try:
                rt.emit_event(
                    EventType.DAMAGE_CONTROL_ACTIVATED,
                    {
                        "signature": signature,
                        "recovery_action": recovery,
                        "agent_id": self.id,
                    },
                )
            except Exception:
                logger.warning(
                    "AD-457: DAMAGE_CONTROL_ACTIVATED emit failed", exc_info=True,
                )
        logger.info(
            "AD-457: damage control activated for '%s' -> %s", signature, recovery,
        )
        return True
