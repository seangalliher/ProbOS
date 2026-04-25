# AD-471: Autonomous Operations — The Conn, Night Orders, Watch Bill

**Priority:** High
**Scope:** 1 new source file, 5 modified source files, 1 new test file
**Estimated tests:** 28
**Rewritten:** 2026-03-28 (corrected line references, added AD-496/502 awareness)

## Context

ProbOS has no structured delegation when the Captain (human) goes offline. The ship either waits for human input or operates without oversight. Three naval protocols fix this:

1. **The Conn** — formal authority delegation to a bridge officer
2. **Night Orders** — time-bounded Captain directives with TTL
3. **Watch Bill** — structured duty rotation with cognitive health benefits

All three are modeled on US Navy protocols (OOD, CO Night Orders, Watch Bill) and build on existing `watch_rotation.py` (AD-377) infrastructure that is **defined and tested but not wired into anything**.

### Relationship to AD-496 (Workforce Scheduling)

AD-496 added `workforce.py` with `WorkItemStore`, `BookableResource`, `AgentCalendar`, and `CalendarEntry`. These are **complementary**, not overlapping:

- **WatchManager** (AD-377/471) = **availability** — who is on duty, who is off
- **WorkItemStore** (AD-496) = **assignment** — what work is assigned to available agents

AD-471's watch rotation determines which agents are available. AD-496's workforce scheduling assigns specific work items to available agents. The two should not conflict. Do NOT modify `workforce.py`.

---

## Existing Infrastructure (BUILD ON, don't recreate)

| Component | Location | What it has | Gap |
|---|---|---|---|
| `WatchManager` | `watch_rotation.py:78-253` | WatchType enum, CaptainOrder, DutyShift, StandingTask, duty roster, dispatch loop | Not wired into runtime.py; no wall-clock awareness; CaptainOrder has no TTL; no conn delegation |
| `DutyScheduleTracker` | `duty_schedule.py` | cron/interval scheduling, priority dispatch | Stateless across restarts; no watch section awareness |
| `DirectiveStore` | `directive_store.py` | 6-tier constitution, `/order` `/amend` `/revoke` commands | No `night_order` directive type; no auto-expiry TTL |
| Ontology chain of command | `ontology.py:691-703` | `get_chain_of_command()`, `authority_over`, `reports_to` | Determines who CAN hold the conn |
| Shell commands | `shell.py:33-77` (COMMANDS), `195-239` (handlers) | `/order`, `/amend`, `/revoke`, `/directives` | No `/conn`, `/night-orders`, `/watch` |
| Proactive loop | `proactive.py:161-224` (`_run_cycle`), `465-661` (`_gather_context`) | Crew gating, cooldown, circuit breaker, agency checks, temporal context (AD-502) | No watch section filtering, no conn context injection |
| Rank system | `crew_profile.py:29-45` | `Rank(Enum)`: ENSIGN (<0.5), LIEUTENANT (0.5-0.7), COMMANDER (0.7-0.85), SENIOR (0.85+). `Rank.from_trust(trust_score)` classmethod. | Used for conn qualification |
| Earned agency | `earned_agency.py` | `AgencyLevel`, `agency_from_rank()`, `can_think_proactively()`, `can_perform_action()` | Uses `Rank` from `crew_profile` |

---

## Part 1: The Conn — Temporary Authority Delegation

### New file: `src/probos/conn.py`

```python
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
        self._trust_floor: float = 0.6              # Default escalation threshold

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
```

---

## Part 2: Night Orders — Captain-Offline Guidance

### Extend `CaptainOrder` in `watch_rotation.py`

Add TTL and Night Order classification to the existing `CaptainOrder` dataclass (currently at line 49):

```python
@dataclass
class CaptainOrder:
    """A persistent directive from the Captain to an agent or department."""
    id: str = ""
    target: str = ""
    target_type: str = "agent"      # "agent", "agent_type", or "department"
    description: str = ""
    intent_type: str = ""
    intent_params: dict[str, Any] = field(default_factory=dict)
    one_shot: bool = False
    created_at: float = 0.0
    executed_count: int = 0
    active: bool = True
    # --- AD-471 additions ---
    is_night_order: bool = False        # True = time-bounded Night Order
    ttl_seconds: float = 28800.0        # Default 8 hours for Night Orders
    expires_at: float = 0.0             # Set on creation: created_at + ttl_seconds
    template: str = ""                  # Preset template name (if any)

    def is_expired(self) -> bool:
        """Check if this Night Order has expired."""
        if not self.is_night_order:
            return False
        if self.expires_at <= 0:
            return False
        return time.time() > self.expires_at
```

Make sure to add `import time` at the top of watch_rotation.py if not already present.

### Add `NightOrdersManager` to `watch_rotation.py`

Add after the `WatchManager` class (after line 253):

```python
# Night Order preset templates
NIGHT_ORDER_TEMPLATES: dict[str, dict[str, Any]] = {
    "maintenance": {
        "name": "Maintenance Watch",
        "description": "Routine operations only. No builds, no deployments. Monitor and report.",
        "can_approve_builds": False,
        "escalation_triggers": ["build_failure", "security_alert", "trust_drop"],
        "alert_boundary": "yellow",  # Max alert level allowed
    },
    "build": {
        "name": "Build Watch",
        "description": "Approve builds from approved queue. Reject unknown builds. Standard diagnostics.",
        "can_approve_builds": True,
        "escalation_triggers": ["security_alert", "trust_drop"],
        "alert_boundary": "yellow",
    },
    "quiet": {
        "name": "Quiet Watch",
        "description": "Logging only. No autonomous actions. Observe and record.",
        "can_approve_builds": False,
        "escalation_triggers": ["red_alert", "security_alert"],
        "alert_boundary": "green",  # Don't even change to Yellow
    },
}


@dataclass
class NightOrders:
    """Captain's Night Orders — time-bounded guidance for the conn-holder.

    Structured conditional instructions: 'If X happens, do Y. If Z, wake me.'
    Expires when: TTL lapses, Captain returns, or Captain rescinds.
    """
    active: bool = False
    created_at: float = 0.0
    ttl_seconds: float = 28800.0        # 8 hours default
    expires_at: float = 0.0
    template: str = ""                   # Preset template name
    template_config: dict[str, Any] = field(default_factory=dict)

    # Custom instructions (free-form, from Captain)
    instructions: list[str] = field(default_factory=list)

    # Escalation triggers — conditions that override Night Orders
    escalation_triggers: list[str] = field(default_factory=list)

    # Decision boundaries
    can_approve_builds: bool = False
    alert_boundary: str = "yellow"      # Max alert level without escalation

    # Tracking
    invocations: list[dict[str, Any]] = field(default_factory=list)

    def is_expired(self) -> bool:
        if not self.active:
            return True
        if self.expires_at <= 0:
            return False
        return time.time() > self.expires_at

    def invoke(self, instruction_index: int, details: dict[str, Any]) -> None:
        """Record that a Night Order instruction was invoked."""
        self.invocations.append({
            "instruction_index": instruction_index,
            "timestamp": time.time(),
            **details,
        })


class NightOrdersManager:
    """Manages Night Orders lifecycle."""

    def __init__(self) -> None:
        self._orders: NightOrders | None = None

    @property
    def active(self) -> bool:
        if not self._orders:
            return False
        if self._orders.is_expired():
            self._orders.active = False
            return False
        return self._orders.active

    @property
    def orders(self) -> NightOrders | None:
        return self._orders

    def set_night_orders(
        self,
        instructions: list[str],
        ttl_hours: float = 8.0,
        template: str = "",
        escalation_triggers: list[str] | None = None,
        can_approve_builds: bool = False,
        alert_boundary: str = "yellow",
    ) -> NightOrders:
        """Captain sets Night Orders before going offline.

        Args:
            instructions: List of conditional instructions
            ttl_hours: Hours until auto-expiry (default 8)
            template: Preset template name (maintenance/build/quiet)
            escalation_triggers: Custom escalation conditions
            can_approve_builds: Whether conn-holder can approve builds
            alert_boundary: Max alert level without Captain

        Returns:
            NightOrders dataclass
        """
        now = time.time()
        ttl_seconds = ttl_hours * 3600

        # Apply template defaults if specified
        config: dict[str, Any] = {}
        if template and template in NIGHT_ORDER_TEMPLATES:
            config = dict(NIGHT_ORDER_TEMPLATES[template])
            can_approve_builds = config.get("can_approve_builds", can_approve_builds)
            alert_boundary = config.get("alert_boundary", alert_boundary)
            if escalation_triggers is None:
                escalation_triggers = config.get("escalation_triggers", [])

        self._orders = NightOrders(
            active=True,
            created_at=now,
            ttl_seconds=ttl_seconds,
            expires_at=now + ttl_seconds,
            template=template,
            template_config=config,
            instructions=instructions,
            escalation_triggers=escalation_triggers or [],
            can_approve_builds=can_approve_builds,
            alert_boundary=alert_boundary,
        )
        logger.info(
            "Night Orders set (template=%s, ttl=%.1fh, triggers=%s)",
            template or "custom", ttl_hours, escalation_triggers or [],
        )
        return self._orders

    def expire(self) -> dict[str, Any]:
        """Expire Night Orders (Captain returns or TTL lapses).

        Returns:
            Summary of Night Orders activity
        """
        if not self._orders:
            return {"status": "no_active_orders"}

        result = {
            "duration_seconds": time.time() - self._orders.created_at,
            "template": self._orders.template,
            "instructions_count": len(self._orders.instructions),
            "invocations": list(self._orders.invocations),
            "invoked_count": len(self._orders.invocations),
        }
        self._orders.active = False
        self._orders = None
        logger.info("Night Orders expired")
        return result

    def get_status(self) -> dict[str, Any]:
        """Get current Night Orders status."""
        if not self._orders or not self.active:
            return {"active": False}
        remaining = max(0, self._orders.expires_at - time.time())
        return {
            "active": True,
            "template": self._orders.template,
            "created_at": self._orders.created_at,
            "expires_at": self._orders.expires_at,
            "remaining_seconds": remaining,
            "remaining_hours": round(remaining / 3600, 1),
            "instructions_count": len(self._orders.instructions),
            "invoked_count": len(self._orders.invocations),
            "can_approve_builds": self._orders.can_approve_builds,
            "alert_boundary": self._orders.alert_boundary,
            "escalation_triggers": self._orders.escalation_triggers,
        }

    def check_escalation(self, trigger: str) -> bool:
        """Check if trigger is in Night Orders escalation list."""
        if not self._orders or not self.active:
            return False
        return trigger in self._orders.escalation_triggers
```

---

## Part 3: Watch Bill — Structured Duty Rotation

### Extend `WatchManager` in `watch_rotation.py`

Add wall-clock time awareness and watch section rotation. Add these methods to the existing `WatchManager` class (currently ends at line 253):

```python
    # --- AD-471: Watch Bill extensions ---

    def _get_current_watch_by_time(self) -> WatchType:
        """Determine watch type by wall-clock hour.

        Standard three-watch rotation:
        - ALPHA: 0800-1600 (full operations)
        - BETA:  1600-0000 (reduced operations)
        - GAMMA: 0000-0800 (maintenance / background)
        """
        from datetime import datetime
        hour = datetime.now().hour
        if 8 <= hour < 16:
            return WatchType.ALPHA
        elif 16 <= hour < 24:
            return WatchType.BETA
        else:  # 0-8
            return WatchType.GAMMA

    def auto_rotate(self) -> WatchType | None:
        """Check wall-clock and rotate watch if needed.

        Returns:
            New WatchType if rotation occurred, None otherwise.
            Called from dispatch loop on each cycle.
        """
        time_watch = self._get_current_watch_by_time()
        if time_watch != self._current_watch:
            old = self._current_watch
            self.set_current_watch(time_watch)
            logger.info(
                "Watch auto-rotation: %s -> %s",
                old.value, time_watch.value,
            )
            return time_watch
        return None

    def get_watch_status(self) -> dict[str, Any]:
        """Return full watch bill status for API/shell display."""
        return {
            "current_watch": self._current_watch.value,
            "time_appropriate_watch": self._get_current_watch_by_time().value,
            "on_duty": self.get_on_duty(),
            "roster": self.get_roster(),
            "standing_tasks_count": len([t for t in self._standing_tasks if t.enabled]),
            "active_orders_count": len(self.get_active_orders()),
        }
```

Update the `_dispatch_loop` (currently at line 204) to include auto-rotation and Night Orders expiry:

```python
    async def _dispatch_loop(self) -> None:
        """Periodic loop that dispatches due standing tasks and orders."""
        while not self._stop_event.is_set():
            try:
                # AD-471: Auto-rotate watch based on wall-clock time
                self.auto_rotate()
                # Expire Night Orders on Captain's orders in the WatchManager
                self._expire_night_orders()
                await self._dispatch_due_tasks()
                await self._dispatch_due_orders()
            except Exception as e:
                logger.warning("watch-dispatch error: %s", e)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._check_interval,
                )
                break
            except asyncio.TimeoutError:
                pass

    def _expire_night_orders(self) -> None:
        """Deactivate expired CaptainOrders that are Night Orders."""
        for order in self._captain_orders:
            if order.active and order.is_night_order and order.is_expired():
                order.active = False
                logger.info("Night order expired: %s", order.id)
```

---

## Part 4: Runtime Integration

### Modify `runtime.py`

**Important:** Line numbers shift as code is added. Use the landmark descriptions to find insertion points, not absolute line numbers.

At initialization (in `__init__`, near line 130, where other service attributes are set):

```python
from probos.conn import ConnManager

# In __init__:
self.conn_manager: ConnManager | None = None
```

At startup (in `start()`, near line 1573 where the proactive loop starts):

```python
# AD-471: Initialize conn manager and watch manager
from probos.conn import ConnManager
self.conn_manager = ConnManager()

# Wire watch manager into runtime
from probos.watch_rotation import WatchManager
self.watch_manager = WatchManager(
    dispatch_fn=self._dispatch_watch_intent,
    check_interval=30.0,
)
# Populate roster from ontology
if self.ontology:
    self._populate_watch_roster()
await self.watch_manager.start()
```

Add helper methods (near the other private methods in runtime.py):

```python
async def _dispatch_watch_intent(self, intent_type: str, params: dict) -> Any:
    """Bridge between WatchManager and intent bus."""
    from probos.intent import IntentMessage
    intent = IntentMessage(intent=intent_type, **params)
    return await self.intent_bus.publish(intent)

def _populate_watch_roster(self) -> None:
    """Populate watch roster from ontology assignments.

    Default: all crew on ALPHA watch (full ops). Future: configurable
    watch sections per department from organization.yaml.
    """
    if not self.ontology:
        return
    from probos.watch_rotation import WatchType
    crew_types = self.ontology.get_crew_agent_types()
    for agent_type in crew_types:
        assignment = self.ontology.get_assignment_for_agent(agent_type)
        if assignment:
            for agent in self.registry.all():
                if agent.agent_type == agent_type:
                    self.watch_manager.assign_to_watch(
                        agent.id, WatchType.ALPHA,
                    )
```

At shutdown (in `stop()`, near line 1701 where proactive loop stops):

```python
# AD-471: Stop watch manager
if hasattr(self, 'watch_manager') and self.watch_manager:
    await self.watch_manager.stop()
```

Add conn qualification checking:

```python
def is_conn_qualified(self, agent_id: str) -> bool:
    """Check if an agent is qualified to hold the conn.

    Requirements:
    - COMMANDER+ rank (trust >= 0.7)
    - Bridge officer or department chief
    """
    agent = self.registry.get(agent_id)
    if not agent:
        return False

    # Check rank — Rank is in crew_profile, not earned_agency
    trust = 0.5
    if self.trust_network:
        trust = self.trust_network.get_trust_score(agent.id)
    from probos.crew_profile import Rank
    rank = Rank.from_trust(trust)
    if rank.value < Rank.COMMANDER.value:
        return False

    # Check role — bridge officers and department chiefs
    if not self.ontology:
        return False
    post = self.ontology.get_post_for_agent(agent.agent_type)
    if not post:
        return False
    # Bridge officers (report directly to captain) or department chiefs
    CONN_ELIGIBLE_POSTS = {
        "first_officer", "counselor",
        "chief_engineer", "chief_science", "chief_medical",
        "chief_security", "chief_operations",
    }
    return post.id in CONN_ELIGIBLE_POSTS
```

---

## Part 4b: Night Orders Execution Path

Night Orders are useless without three execution mechanisms: context injection (so the conn-holder knows what the Captain wants), event-driven escalation (so conditions trigger Captain notification), and the `NightOrdersManager` wired into runtime. Without these, Night Orders are stored but never read or acted upon.

### A. Initialize NightOrdersManager in runtime.py

At startup, alongside `ConnManager`:

```python
from probos.watch_rotation import NightOrdersManager

self._night_orders_mgr = NightOrdersManager()
```

At shutdown:

```python
if hasattr(self, '_night_orders_mgr') and self._night_orders_mgr:
    if self._night_orders_mgr.active:
        self._night_orders_mgr.expire()
```

### B. Night Orders context injection in proactive.py `_gather_context()`

When the conn is active, inject Night Orders instructions into the conn-holder's proactive context so they can follow them during reasoning. The `_gather_context()` method spans lines 465-661. Add after the circuit breaker redirect section (around line 659), before `return context` at line 661:

```python
# AD-471: Night Orders context for conn-holder
if hasattr(rt, 'conn_manager') and rt.conn_manager and rt.conn_manager.is_active:
    conn_state = rt.conn_manager.state
    if conn_state.holder_agent_id == agent.id:
        # This agent holds the conn — inject Night Orders
        night_ctx: dict[str, Any] = {
            "role": "You currently hold the conn (temporary command authority).",
            "conn_scope": {
                "can_approve_builds": conn_state.can_approve_builds,
                "can_change_alert_yellow": conn_state.can_change_alert_yellow,
                "can_issue_orders": conn_state.can_issue_orders,
            },
        }
        if hasattr(rt, '_night_orders_mgr') and rt._night_orders_mgr and rt._night_orders_mgr.active:
            orders = rt._night_orders_mgr.orders
            night_ctx["night_orders"] = {
                "template": orders.template or "custom",
                "instructions": orders.instructions,
                "alert_boundary": orders.alert_boundary,
                "escalation_triggers": orders.escalation_triggers,
                "remaining_hours": round(max(0, orders.expires_at - time.time()) / 3600, 1),
            }
        context["conn_authority"] = night_ctx
```

This ensures the conn-holder sees Night Orders instructions in every proactive think cycle and can reason about them. Note: `_gather_context` already has AD-502 temporal context injection at lines 470-476 — the conn context goes after, near the end.

### C. Event-driven escalation wiring in runtime.py

The runtime's event pipeline (bridge alerts, trust changes) needs to check Night Orders escalation triggers. Add a method to runtime.py:

```python
def _check_night_order_escalation(self, event_type: str, details: dict[str, Any] | None = None) -> None:
    """Check if a runtime event should trigger Night Orders escalation.

    Called from event emission points (trust changes, alert changes,
    build results). If the event matches a Night Orders escalation trigger,
    fires a bridge alert to wake the Captain.
    """
    if not hasattr(self, '_night_orders_mgr') or not self._night_orders_mgr:
        return
    if not self._night_orders_mgr.active:
        return

    # Map runtime events to Night Orders trigger names
    trigger_map = {
        "trust_change": "trust_drop",
        "alert_condition_change": "red_alert",
        "build_failure": "build_failure",
        "security_alert": "security_alert",
    }
    trigger = trigger_map.get(event_type)
    if not trigger:
        return

    # Additional condition checks
    if trigger == "trust_drop" and details:
        # Only escalate if trust dropped below floor
        new_trust = details.get("new_trust", 1.0)
        if new_trust >= 0.6:  # Not below floor
            return
    if trigger == "red_alert" and details:
        new_level = details.get("new_level", "")
        if new_level.lower() != "red":
            return

    # Check against Night Orders escalation triggers
    if self._night_orders_mgr.check_escalation(trigger):
        # Also notify conn manager
        if self.conn_manager:
            self.conn_manager.check_escalation(trigger, details)
        # Fire bridge alert
        if hasattr(self, 'bridge_alerts') and self.bridge_alerts:
            self.bridge_alerts.add_alert(
                severity="critical",
                title=f"Night Orders escalation: {trigger}",
                source="night_orders",
                details=details or {},
            )
        logger.warning("Night Orders escalation triggered: %s", trigger)
```

Wire this into `_emit_event()` — find where the runtime emits events and add a call:

```python
# In _emit_event or wherever trust/alert/build events are fired:
self._check_night_order_escalation(event_type, details)
```

### D. Tests for execution path (add to test file)

25. **test_night_orders_context_injection** — Mock conn active + Night Orders active. Call `_gather_context()` for the conn-holder agent. Verify `context["conn_authority"]` contains Night Orders instructions.

26. **test_night_orders_context_not_injected_for_non_holder** — Mock conn active. Call `_gather_context()` for a different agent. Verify `conn_authority` NOT in context.

27. **test_night_orders_escalation_trust_drop** — Set Night Orders with `escalation_triggers=["trust_drop"]`. Call `_check_night_order_escalation("trust_change", {"new_trust": 0.4})`. Verify bridge alert fired.

28. **test_night_orders_escalation_ignored_above_floor** — Same setup but `new_trust=0.8`. Verify NO bridge alert.

---

## Part 5: Shell Commands

### Modify `shell.py`

Add to `COMMANDS` dict (lines 33-77, between `/directives` and `/scout`):

```python
"/conn":        "Manage the conn (/conn <callsign> | /conn return | /conn status | /conn log)",
"/night-orders": "Set Night Orders (/night-orders <template> [ttl_hours] | /night-orders expire | /night-orders status)",
"/watch":       "Show watch bill status (/watch)",
```

Add to `handlers` dict in `_dispatch_slash` (lines 195-239):

```python
"/conn":    self._cmd_conn,
"/night-orders": self._cmd_night_orders,
"/watch":   self._cmd_watch,
```

Implement the command handlers:

```python
async def _cmd_conn(self, arg: str) -> None:
    """Manage the conn — temporary authority delegation."""
    rt = self.runtime
    if not rt.conn_manager:
        self.console.print("[red]Conn manager not initialized[/red]")
        return

    parts = arg.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else "status"

    if subcmd == "status":
        status = rt.conn_manager.get_status()
        if not status["active"]:
            self.console.print("[dim]No one has the conn. Captain has command.[/dim]")
        else:
            self.console.print(f"[bold cyan]{status['holder']}[/bold cyan] has the conn")
            self.console.print(f"  Duration: {status['duration_seconds']:.0f}s")
            self.console.print(f"  Actions: {status['actions_taken']}")
            self.console.print(f"  Escalations: {status['escalation_count']}")
            self.console.print(f"  Can approve builds: {status['can_approve_builds']}")

    elif subcmd == "return":
        if not rt.conn_manager.is_active:
            self.console.print("[dim]No active conn to return.[/dim]")
            return
        result = rt.conn_manager.return_conn()
        # Expire Night Orders when Captain returns
        if hasattr(rt, '_night_orders_mgr') and rt._night_orders_mgr:
            rt._night_orders_mgr.expire()
        # Ward Room announcement
        if rt.ward_room:
            await rt.ward_room.post_message(
                channel_id="all-hands",
                author_id="system",
                author_callsign="Bridge",
                content=f"Captain on the bridge. The conn has been returned from {result['holder']}. {result['actions_taken']} action(s) taken, {result['escalation_count']} escalation(s).",
            )
        self.console.print(f"[bold green]Conn returned from {result['holder']}[/bold green]")
        self.console.print(f"  Duration: {result['duration_seconds']:.0f}s")
        self.console.print(f"  Actions taken: {result['actions_taken']}")

    elif subcmd == "log":
        log = rt.conn_manager.get_conn_log()
        if not log:
            self.console.print("[dim]No conn log entries.[/dim]")
            return
        for entry in log[-20:]:  # Last 20 entries
            ts = time.strftime("%H:%M:%S", time.localtime(entry.get("timestamp", 0)))
            self.console.print(f"  [{ts}] {entry.get('action', '?')}: {entry}")

    else:
        # Interpret as callsign — grant conn
        callsign = arg.strip()
        if not callsign:
            self.console.print("[red]Usage: /conn <callsign> | /conn return | /conn status | /conn log[/red]")
            return

        # Find agent by callsign
        target_agent = None
        for agent in rt.registry.all():
            if hasattr(agent, 'callsign') and agent.callsign and agent.callsign.lower() == callsign.lower():
                target_agent = agent
                break

        if not target_agent:
            self.console.print(f"[red]No agent found with callsign '{callsign}'[/red]")
            return

        # Check qualification
        if not rt.is_conn_qualified(target_agent.id):
            self.console.print(f"[red]{callsign} is not qualified for the conn (requires COMMANDER+ rank, bridge/chief post)[/red]")
            return

        # Grant conn
        state = rt.conn_manager.grant_conn(
            agent_id=target_agent.id,
            agent_type=target_agent.agent_type,
            callsign=target_agent.callsign,
            reason="Captain delegation",
        )

        # Ward Room announcement
        if rt.ward_room:
            await rt.ward_room.post_message(
                channel_id="all-hands",
                author_id="system",
                author_callsign="Bridge",
                content=f"{target_agent.callsign}, you have the conn. Captain is going offline.",
            )
        self.console.print(f"[bold cyan]{target_agent.callsign}[/bold cyan] has the conn.")


async def _cmd_night_orders(self, arg: str) -> None:
    """Set Night Orders — Captain-offline guidance."""
    rt = self.runtime
    if not hasattr(rt, '_night_orders_mgr') or not rt._night_orders_mgr:
        self.console.print("[red]Night Orders manager not initialized[/red]")
        return

    parts = arg.strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else "status"

    if subcmd == "status":
        status = rt._night_orders_mgr.get_status()
        if not status["active"]:
            self.console.print("[dim]No active Night Orders.[/dim]")
        else:
            self.console.print("[bold]Night Orders active[/bold]")
            self.console.print(f"  Template: {status['template'] or 'custom'}")
            self.console.print(f"  Remaining: {status['remaining_hours']}h")
            self.console.print(f"  Instructions: {status['instructions_count']}")
            self.console.print(f"  Invoked: {status['invoked_count']} times")
            self.console.print(f"  Builds: {'allowed' if status['can_approve_builds'] else 'not allowed'}")
            self.console.print(f"  Alert boundary: {status['alert_boundary']}")

    elif subcmd == "expire":
        result = rt._night_orders_mgr.expire()
        self.console.print("[green]Night Orders expired.[/green]")
        if result.get("invoked_count", 0) > 0:
            self.console.print(f"  {result['invoked_count']} instruction(s) were invoked.")

    elif subcmd in NIGHT_ORDER_TEMPLATES:
        # Template-based Night Orders
        template = subcmd
        ttl = 8.0
        if len(parts) > 1:
            try:
                ttl = float(parts[1])
            except ValueError:
                pass
        orders = rt._night_orders_mgr.set_night_orders(
            instructions=[],
            ttl_hours=ttl,
            template=template,
        )
        # Apply to conn manager if active
        if rt.conn_manager and rt.conn_manager.is_active:
            rt.conn_manager.state.can_approve_builds = orders.can_approve_builds
        tpl = NIGHT_ORDER_TEMPLATES[template]
        self.console.print(f"[bold]Night Orders set: {tpl['name']}[/bold]")
        self.console.print(f"  {tpl['description']}")
        self.console.print(f"  TTL: {ttl}h")

    else:
        # Custom Night Orders — treat entire arg as instruction
        if not arg.strip():
            self.console.print("[red]Usage: /night-orders <template>|expire|status[/red]")
            self.console.print("  Templates: maintenance, build, quiet")
            return
        orders = rt._night_orders_mgr.set_night_orders(
            instructions=[arg.strip()],
            ttl_hours=8.0,
        )
        self.console.print("[bold]Night Orders set (custom, 8h TTL)[/bold]")


async def _cmd_watch(self, arg: str) -> None:
    """Show watch bill status."""
    rt = self.runtime
    if not hasattr(rt, 'watch_manager') or not rt.watch_manager:
        self.console.print("[dim]Watch manager not initialized.[/dim]")
        return
    status = rt.watch_manager.get_watch_status()
    self.console.print(f"[bold]Current Watch:[/bold] {status['current_watch'].upper()}")
    self.console.print(f"  Time-appropriate: {status['time_appropriate_watch'].upper()}")
    self.console.print(f"  On duty: {len(status['on_duty'])} agent(s)")
    self.console.print(f"  Standing tasks: {status['standing_tasks_count']}")
    self.console.print(f"  Active orders: {status['active_orders_count']}")
    self.console.print()
    for watch, agents in status['roster'].items():
        count = len(agents)
        marker = " ◄" if watch == status['current_watch'] else ""
        self.console.print(f"  {watch.upper()}: {count} agent(s){marker}")
```

Note: You will need to import `NIGHT_ORDER_TEMPLATES` from `watch_rotation` in `shell.py`, or move the template name check to a method call.

---

## Part 6: API Endpoints

### Modify `api.py`

Add three endpoints (near other system endpoints):

```python
@router.get("/api/system/conn")
async def get_conn_status(request: Request) -> JSONResponse:
    """Get current conn delegation status."""
    rt = request.app.state.runtime
    if not rt.conn_manager:
        return JSONResponse({"active": False, "holder": None})
    return JSONResponse(rt.conn_manager.get_status())


@router.get("/api/system/night-orders")
async def get_night_orders_status(request: Request) -> JSONResponse:
    """Get current Night Orders status."""
    rt = request.app.state.runtime
    if not hasattr(rt, '_night_orders_mgr') or not rt._night_orders_mgr:
        return JSONResponse({"active": False})
    return JSONResponse(rt._night_orders_mgr.get_status())


@router.get("/api/system/watch")
async def get_watch_status(request: Request) -> JSONResponse:
    """Get watch bill status."""
    rt = request.app.state.runtime
    if not hasattr(rt, 'watch_manager') or not rt.watch_manager:
        return JSONResponse({"error": "Watch manager not initialized"}, status_code=404)
    return JSONResponse(rt.watch_manager.get_watch_status())
```

---

## Part 7: Ward Room Announcements

The conn and Night Orders state changes should be announced on the All Hands channel. The shell commands above already include the key announcements:

1. **Conn granted**: `"{callsign}, you have the conn. Captain is going offline."`
2. **Conn returned**: `"Captain on the bridge. The conn has been returned from {holder}."`
3. **Watch rotation** (automatic): Add a Ward Room post from `auto_rotate()` when wired to runtime.

For watch rotation, add the announcement callback. In the `WatchManager.__init__`, add:

```python
self._rotation_callback: Callable[[str, str], Awaitable[Any]] | None = None
```

And in `auto_rotate()`, after the `set_current_watch` call:

```python
if self._rotation_callback:
    try:
        await self._rotation_callback(old.value, time_watch.value)
    except Exception:
        pass  # Non-critical
```

Then make `auto_rotate` async and wire the callback in runtime.py to post to Ward Room.

---

## Tests

Create `tests/test_autonomous_operations.py`:

### Conn tests (7):

1. **test_conn_grant_and_return** — Grant conn, verify active + holder. Return, verify inactive + summary.
2. **test_conn_qualification_commander_required** — Agent with LIEUTENANT rank fails `is_conn_qualified()`.
3. **test_conn_qualification_post_required** — COMMANDER-rank agent not on bridge/chief post fails qualification.
4. **test_conn_escalation_triggers** — Each trigger in `ESCALATION_TRIGGERS` returns True from `check_escalation()`.
5. **test_conn_captain_only_actions** — `is_authorized("modify_standing_orders")` returns False. `is_authorized("issue_order")` returns True.
6. **test_conn_action_logging** — `record_action()` appends to both `actions_taken` and `_conn_log`.
7. **test_conn_transfer** — Grant to Agent A, then grant to Agent B. Verify log shows transfer.

### Night Orders tests (7):

8. **test_night_orders_set_and_expire** — Set orders, verify active. Expire, verify inactive + summary.
9. **test_night_orders_ttl_expiry** — Set order with 0.001h TTL (3.6s). After mocked time, verify `is_expired()` returns True.
10. **test_night_orders_template_maintenance** — Set "maintenance" template. Verify `can_approve_builds=False`, specific escalation triggers.
11. **test_night_orders_template_build** — Set "build" template. Verify `can_approve_builds=True`.
12. **test_night_orders_template_quiet** — Set "quiet" template. Verify `alert_boundary="green"`.
13. **test_night_orders_invocation_tracking** — Call `invoke()`. Verify invocation recorded with timestamp.
14. **test_night_orders_escalation_check** — Set escalation_triggers=["trust_drop"]. Verify `check_escalation("trust_drop")` returns True, `check_escalation("other")` returns False.

### Watch Bill tests (7):

15. **test_watch_auto_rotate_morning** — Mock `datetime.now().hour = 10`. Verify `_get_current_watch_by_time()` returns ALPHA.
16. **test_watch_auto_rotate_evening** — Mock `datetime.now().hour = 20`. Verify returns BETA.
17. **test_watch_auto_rotate_night** — Mock `datetime.now().hour = 3`. Verify returns GAMMA.
18. **test_watch_rotation_triggers_change** — Set current watch to ALPHA. Mock hour=20. Call `auto_rotate()`. Verify watch changed to BETA.
19. **test_watch_no_rotation_same_period** — Set current watch to ALPHA. Mock hour=10. Call `auto_rotate()`. Verify returns None (no change).
20. **test_night_order_expiry_in_dispatch** — Create an expired Night Order CaptainOrder. Call `_expire_night_orders()`. Verify `active=False`.
21. **test_watch_status_report** — Populate roster, add standing tasks. Verify `get_watch_status()` returns correct counts.

### Integration tests (3):

22. **test_conn_night_orders_integration** — Set Night Orders with `can_approve_builds=True`, grant conn. Verify conn holder inherits Night Orders build permission.
23. **test_captain_return_expires_night_orders** — Set Night Orders, grant conn. Return conn. Verify Night Orders also expired.
24. **test_captain_order_night_order_ttl** — Create CaptainOrder with `is_night_order=True, ttl_seconds=0.001`. Verify `is_expired()` after brief wait.

### Execution path tests (4):

25. **test_night_orders_context_injection** — Mock conn active + Night Orders active. Call `_gather_context()` for the conn-holder agent. Verify `context["conn_authority"]` contains Night Orders instructions.
26. **test_night_orders_context_not_injected_for_non_holder** — Mock conn active. Call `_gather_context()` for a different agent. Verify `conn_authority` NOT in context.
27. **test_night_orders_escalation_trust_drop** — Set Night Orders with `escalation_triggers=["trust_drop"]`. Call `_check_night_order_escalation("trust_change", {"new_trust": 0.4})`. Verify bridge alert fired.
28. **test_night_orders_escalation_ignored_above_floor** — Same setup but `new_trust=0.8`. Verify NO bridge alert.

---

## Verification

1. **Conn**: `uv run pytest tests/test_autonomous_operations.py -k "conn" -v`
2. **Night Orders**: `uv run pytest tests/test_autonomous_operations.py -k "night" -v`
3. **Watch Bill**: `uv run pytest tests/test_autonomous_operations.py -k "watch" -v`
4. **Full**: `uv run pytest tests/test_autonomous_operations.py -v`
5. **Existing watch tests still pass**: `uv run pytest tests/test_watch_rotation.py -v`
6. **Shell**: Boot ProbOS, run `/conn Number One`, `/conn status`, `/night-orders maintenance`, `/watch`, `/conn return`

---

## Important

- **DO NOT** create watch_rotation.py from scratch — it already exists (AD-377). EXTEND it.
- **DO NOT** modify `ward_room.py`, `intent.py`, `workforce.py`, or any frontend files
- **DO NOT** change the proactive loop gating logic — the watch-based filtering is future work (noted as enhancement, not required for this AD)
- **DO NOT** change earned_agency.py or the Rank system
- **DO NOT** modify the existing shell command implementations — only add new ones
- **Rank** is in `crew_profile.py`, NOT `earned_agency.py`. Import `from probos.crew_profile import Rank`.
- The `conn` reserved callsign handling in runtime.py is already present — don't change it
- Keep CaptainOrder backward-compatible: new fields have defaults, existing tests must pass
- NightOrdersManager and ConnManager are pure in-memory — no persistence needed for v1
- `auto_rotate` uses wall-clock `datetime.now()` intentionally (not monotonic) — watch rotation should follow real-world time
- Run existing watch rotation tests after extending: `uv run pytest tests/test_watch_rotation.py -v`
- AD-496 `workforce.py` is complementary — WatchManager handles availability, WorkItemStore handles assignment. Don't merge or conflict them.
- AD-502 temporal context is already injected in `_gather_context()` at lines 470-476. Conn context injection goes near the end (after circuit breaker, before return).
