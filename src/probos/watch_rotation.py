"""Watch Rotation — scheduled duty shifts for ProbOS agents (AD-377).

Implements a naval-style watch system where agents have scheduled duty periods.
During their watch, agents execute standing tasks and carry out Captain's orders.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class WatchType(Enum):
    """Standard watch types."""
    ALPHA = "alpha"     # Full operations
    BETA = "beta"       # Reduced operations
    GAMMA = "gamma"     # Maintenance / background


@dataclass
class StandingTask:
    """A recurring task executed during a duty shift.

    Standing tasks are department-level orders that agents perform routinely
    during their watch. They do not require explicit Captain intents.
    """
    id: str = ""
    department: str = ""
    description: str = ""
    intent_type: str = ""           # The intent to publish, e.g., "run_diagnostics"
    intent_params: dict[str, Any] = field(default_factory=dict)
    interval_seconds: float = 300   # How often to execute (default 5 min)
    priority: float = 0.5           # 0.0–1.0
    enabled: bool = True
    last_executed: float = 0.0

    def is_due(self) -> bool:
        """Check if enough time has passed since last execution."""
        return (time.time() - self.last_executed) >= self.interval_seconds


@dataclass
class CaptainOrder:
    """A persistent directive from the Captain to an agent or department.

    Captain's orders persist until explicitly rescinded. They are executed
    during the assigned agent's next duty shift.
    """
    id: str = ""
    target: str = ""                # agent_id, agent_type, or department name
    target_type: str = "agent"      # "agent", "agent_type", or "department"
    description: str = ""
    intent_type: str = ""
    intent_params: dict[str, Any] = field(default_factory=dict)
    one_shot: bool = False          # If true, removed after first execution
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


@dataclass
class DutyShift:
    """A scheduled block of time with assigned agents and tasks."""
    watch: WatchType = WatchType.ALPHA
    agent_ids: list[str] = field(default_factory=list)
    department: str = ""
    standing_tasks: list[StandingTask] = field(default_factory=list)
    start_hour: int = 0             # 24-hour clock (0–23)
    duration_hours: int = 8         # Standard 8-hour shift


class WatchManager:
    """Manages watch rotations, duty assignments, and standing task dispatch.

    The WatchManager:
    1. Maintains the duty roster (which agents are on which watch)
    2. Tracks standing tasks per department
    3. Maintains Captain's orders
    4. Runs a periodic loop that dispatches due tasks to on-duty agents
    """

    def __init__(
        self,
        dispatch_fn: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
        check_interval: float = 30.0,
    ) -> None:
        """
        Args:
            dispatch_fn: async function to publish intents (e.g., intent_bus.publish)
            check_interval: seconds between task dispatch checks
        """
        self._dispatch_fn = dispatch_fn
        self._check_interval = check_interval
        self._standing_tasks: list[StandingTask] = []
        self._captain_orders: list[CaptainOrder] = []
        self._duty_roster: dict[WatchType, list[str]] = {
            WatchType.ALPHA: [],
            WatchType.BETA: [],
            WatchType.GAMMA: [],
        }
        self._current_watch: WatchType = WatchType.ALPHA
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    # -- Watch management --

    def set_current_watch(self, watch: WatchType) -> None:
        """Set the active watch (manual override or time-based)."""
        self._current_watch = watch
        logger.info("watch-change watch=%s", watch.value)

    @property
    def current_watch(self) -> WatchType:
        return self._current_watch

    def assign_to_watch(self, agent_id: str, watch: WatchType) -> None:
        """Assign an agent to a watch rotation."""
        if agent_id not in self._duty_roster[watch]:
            self._duty_roster[watch].append(agent_id)

    def remove_from_watch(self, agent_id: str, watch: WatchType) -> None:
        """Remove an agent from a watch."""
        if agent_id in self._duty_roster[watch]:
            self._duty_roster[watch].remove(agent_id)

    def get_on_duty(self) -> list[str]:
        """Get agent IDs currently on duty."""
        return list(self._duty_roster.get(self._current_watch, []))

    def get_roster(self) -> dict[str, list[str]]:
        """Get full duty roster."""
        return {w.value: ids for w, ids in self._duty_roster.items()}

    # -- Standing tasks --

    def add_standing_task(self, task: StandingTask) -> None:
        """Register a standing department task."""
        self._standing_tasks.append(task)

    def remove_standing_task(self, task_id: str) -> bool:
        """Remove a standing task by ID."""
        before = len(self._standing_tasks)
        self._standing_tasks = [t for t in self._standing_tasks if t.id != task_id]
        return len(self._standing_tasks) < before

    def get_standing_tasks(self, department: str = "") -> list[StandingTask]:
        """Get standing tasks, optionally filtered by department."""
        if department:
            return [t for t in self._standing_tasks
                    if t.department == department and t.enabled]
        return [t for t in self._standing_tasks if t.enabled]

    # -- Captain's orders --

    def issue_order(self, order: CaptainOrder) -> None:
        """Captain issues a persistent order."""
        if not order.created_at:
            order.created_at = time.time()
        self._captain_orders.append(order)
        logger.info("captain-order issued target=%s desc=%s",
                     order.target, order.description[:60])

    def rescind_order(self, order_id: str) -> bool:
        """Rescind (deactivate) a Captain's order."""
        for order in self._captain_orders:
            if order.id == order_id:
                order.active = False
                return True
        return False

    def get_active_orders(self, target: str = "") -> list[CaptainOrder]:
        """Get active Captain's orders, optionally filtered by target."""
        orders = [o for o in self._captain_orders if o.active]
        if target:
            orders = [o for o in orders
                      if o.target == target]
        return orders

    # -- Dispatch loop --

    async def start(self) -> None:
        """Start the watch manager dispatch loop."""
        self._stop_event.clear()
        self._task = asyncio.create_task(self._dispatch_loop(), name="watch-manager")
        logger.info("watch-manager started, watch=%s", self._current_watch.value)

    async def stop(self) -> None:
        """Stop the watch manager."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

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

    async def _dispatch_due_tasks(self) -> None:
        """Execute standing tasks that are due."""
        if self._dispatch_fn is None:
            return
        on_duty = set(self.get_on_duty())
        if not on_duty:
            return
        for task in self._standing_tasks:
            if task.enabled and task.is_due():
                try:
                    await self._dispatch_fn(task.intent_type, task.intent_params)
                    task.last_executed = time.time()
                except Exception as e:
                    logger.warning("standing-task failed id=%s: %s", task.id, e)

    async def _dispatch_due_orders(self) -> None:
        """Execute Captain's orders for on-duty agents."""
        if self._dispatch_fn is None:
            return
        on_duty = set(self.get_on_duty())
        for order in self._captain_orders:
            if not order.active:
                continue
            # Check if target agent is on duty
            if order.target_type == "agent" and order.target not in on_duty:
                continue
            try:
                await self._dispatch_fn(order.intent_type, order.intent_params)
                order.executed_count += 1
                if order.one_shot:
                    order.active = False
            except Exception as e:
                logger.warning("captain-order failed id=%s: %s", order.id, e)

    # --- AD-471: Watch Bill extensions ---

    def _get_current_watch_by_time(self) -> WatchType:
        """Determine watch type by wall-clock hour.

        Standard three-watch rotation:
        - ALPHA: 0800-1600 (full operations)
        - BETA:  1600-0000 (reduced operations)
        - GAMMA: 0000-0800 (maintenance / background)
        """
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

    def _expire_night_orders(self) -> None:
        """Deactivate expired CaptainOrders that are Night Orders."""
        for order in self._captain_orders:
            if order.active and order.is_night_order and order.is_expired():
                order.active = False
                logger.info("Night order expired: %s", order.id)


# --- AD-471: Night Orders ---

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
