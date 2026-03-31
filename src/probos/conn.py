"""The Conn — Temporary Authority Delegation (AD-471).

Naval protocol: when the CO leaves the bridge, they formally delegate
command authority to a qualified Officer of the Deck (OOD). The OOD
operates within the CO's standing parameters and escalates for
situations exceeding those parameters.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConnState:
    """State of the conn."""
    holder_agent_id: str | None = None      # Who has the conn
    holder_agent_type: str | None = None
    holder_callsign: str | None = None
    granted_at: float = 0.0                 # time.time()
    granted_by: str = "captain"             # Always captain for now
    reason: str = ""                        # Why delegation happened
    active: bool = False

    # Scope limitations — what the conn holder CAN do
    can_approve_builds: bool = False        # Approve builds from approved queue
    can_approve_diagnostics: bool = True    # Approve routine diagnostics
    can_change_alert_yellow: bool = True    # Can go Green ↔ Yellow
    can_issue_orders: bool = True           # Can issue department-level orders

    # Escalation record
    escalation_count: int = 0
    actions_taken: list[dict[str, Any]] = field(default_factory=list)


class ConnManager:
    """Manages temporary command authority delegation.

    Only one officer holds the conn at a time. The conn-holder gets
    temporary captain_order authority within defined scope. All actions
    are logged with authorized_by='conn' for audit trail.

    Qualification: COMMANDER+ rank, bridge officer or department chief.
    """

    # Escalation conditions that return conn to Captain regardless
    ESCALATION_TRIGGERS = {
        "trust_drop",           # Any agent trust drops below threshold
        "red_alert",            # Alert condition changes to Red
        "build_failure",        # Build fails after retry
        "security_alert",       # Security agent raises alert
        "captain_auth_required", # Action requires Captain rank
    }

    def __init__(self) -> None:
        self._state = ConnState()
        self._conn_log: list[dict[str, Any]] = []  # Audit trail
        from probos.config import TRUST_FLOOR_CONN
        self._trust_floor: float = TRUST_FLOOR_CONN  # Default escalation threshold

    @property
    def is_active(self) -> bool:
        return self._state.active

    @property
    def holder(self) -> str | None:
        return self._state.holder_callsign

    @property
    def state(self) -> ConnState:
        return self._state

    def grant_conn(
        self,
        agent_id: str,
        agent_type: str,
        callsign: str,
        reason: str = "",
        can_approve_builds: bool = False,
    ) -> ConnState:
        """Grant the conn to a qualified officer.

        Args:
            agent_id: Agent's unique ID
            agent_type: Agent's type (e.g., 'architect')
            callsign: Agent's callsign (e.g., 'Number One')
            reason: Why authority is being delegated
            can_approve_builds: Whether conn holder can approve builds

        Returns:
            ConnState with updated delegation
        """
        if self._state.active:
            # Transfer conn — log the handoff
            self._log_action("conn_transfer", {
                "from": self._state.holder_callsign,
                "to": callsign,
            })

        self._state = ConnState(
            holder_agent_id=agent_id,
            holder_agent_type=agent_type,
            holder_callsign=callsign,
            granted_at=time.time(),
            reason=reason,
            active=True,
            can_approve_builds=can_approve_builds,
        )
        self._log_action("conn_granted", {
            "holder": callsign,
            "reason": reason,
        })
        logger.info("Conn granted to %s: %s", callsign, reason)
        return self._state

    def return_conn(self, summary: str = "") -> dict[str, Any]:
        """Return the conn to the Captain.

        Returns:
            Summary dict with actions taken, duration, escalations
        """
        if not self._state.active:
            return {"status": "no_active_conn"}

        duration = time.time() - self._state.granted_at
        result = {
            "holder": self._state.holder_callsign,
            "duration_seconds": duration,
            "actions_taken": len(self._state.actions_taken),
            "escalation_count": self._state.escalation_count,
            "summary": summary,
            "log": list(self._state.actions_taken),
        }
        self._log_action("conn_returned", {
            "holder": self._state.holder_callsign,
            "duration": duration,
            "actions": len(self._state.actions_taken),
        })
        logger.info(
            "Conn returned from %s (%.0fs, %d actions)",
            self._state.holder_callsign, duration, len(self._state.actions_taken),
        )
        self._state = ConnState()
        return result

    def record_action(self, action_type: str, details: dict[str, Any]) -> None:
        """Record an action taken under conn authority."""
        if not self._state.active:
            return
        entry = {
            "type": action_type,
            "timestamp": time.time(),
            "authorized_by": "conn",
            "holder": self._state.holder_callsign,
            **details,
        }
        self._state.actions_taken.append(entry)
        self._log_action(action_type, details)

    def check_escalation(self, trigger: str, details: dict[str, Any] | None = None) -> bool:
        """Check if a condition should escalate to Captain.

        Returns:
            True if this trigger requires Captain attention
        """
        if not self._state.active:
            return False
        if trigger in self.ESCALATION_TRIGGERS:
            self._state.escalation_count += 1
            self._log_action("escalation", {
                "trigger": trigger,
                "details": details or {},
            })
            logger.warning(
                "Conn escalation: %s (holder: %s)",
                trigger, self._state.holder_callsign,
            )
            return True
        return False

    def is_authorized(self, action: str) -> bool:
        """Check if the conn-holder is authorized for an action.

        Actions always requiring Captain:
        - modify_standing_orders
        - approve_self_mod
        - red_alert
        - destructive_action
        - prune_agent
        """
        if not self._state.active:
            return False

        CAPTAIN_ONLY = {
            "modify_standing_orders",
            "approve_self_mod",
            "red_alert",
            "destructive_action",
            "prune_agent",
        }
        if action in CAPTAIN_ONLY:
            return False

        if action == "approve_build":
            return self._state.can_approve_builds
        if action == "change_alert_yellow":
            return self._state.can_change_alert_yellow
        if action == "issue_order":
            return self._state.can_issue_orders

        # Default: allow routine operations
        return True

    def get_conn_log(self) -> list[dict[str, Any]]:
        """Get the full audit trail."""
        return list(self._conn_log)

    def get_status(self) -> dict[str, Any]:
        """Get current conn status for API/shell display."""
        if not self._state.active:
            return {"active": False, "holder": None}
        return {
            "active": True,
            "holder": self._state.holder_callsign,
            "holder_agent_type": self._state.holder_agent_type,
            "granted_at": self._state.granted_at,
            "duration_seconds": time.time() - self._state.granted_at,
            "reason": self._state.reason,
            "actions_taken": len(self._state.actions_taken),
            "escalation_count": self._state.escalation_count,
            "can_approve_builds": self._state.can_approve_builds,
        }

    def _log_action(self, action: str, details: dict[str, Any]) -> None:
        """Append to the persistent conn log."""
        self._conn_log.append({
            "action": action,
            "timestamp": time.time(),
            **details,
        })
