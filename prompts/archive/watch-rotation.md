# Build Prompt: Watch Rotation + Duty Shifts (AD-377)

## File Footprint
- `src/probos/watch_rotation.py` (NEW) — WatchSchedule, DutyShift, WatchManager
- `tests/test_watch_rotation.py` (NEW) — tests

## Context

A starship operates on a watch rotation — crew members have scheduled shifts where they
perform standing department tasks and carry out the Captain's orders. ProbOS agents currently
only activate when an intent arrives. This AD creates the **Watch Rotation** system —
scheduled shifts where agents proactively perform department duties.

### Design

**Three watches** (inspired by naval tradition):
- **Alpha Watch** — primary operations (full crew)
- **Beta Watch** — reduced operations (skeleton crew)
- **Gamma Watch** — maintenance window (minimal, background tasks)

Each watch defines which agents are "on duty" and what standing tasks they perform.
Standing tasks are department-specific orders that agents execute during their shift
without needing explicit intents from the Captain.

### Key concepts:

1. **DutyShift** — a time block with assigned agents and standing tasks
2. **StandingTask** — a recurring task tied to a department (e.g., "run diagnostics",
   "check trust network health", "index new files")
3. **WatchManager** — manages the rotation schedule, activates/deactivates shifts,
   dispatches standing tasks to on-duty agents
4. **Captain's Orders** — persistent directives the Captain gives to specific agents
   or departments, executed during their next shift

### Existing systems this integrates with:
- `standing_orders.py` — department assignments (which department each agent belongs to)
- `BaseAgent` — agents have `start()`, `stop()`, `state` (ACTIVE/DEGRADED)
- `IntentBus` — standing tasks can be published as intents
- `CrewProfile` (AD-376) — rank may influence shift assignment (seniors get Alpha)

---

## Changes

### File: `src/probos/watch_rotation.py` (NEW)

```python
"""Watch Rotation — scheduled duty shifts for ProbOS agents (AD-377).

Implements a naval-style watch system where agents have scheduled duty periods.
During their watch, agents execute standing tasks and carry out Captain's orders.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
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
```

---

### File: `tests/test_watch_rotation.py` (NEW)

```python
"""Tests for Watch Rotation + Duty Shifts (AD-377)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest


class TestWatchType:
    def test_alpha_value(self) -> None:
        from probos.watch_rotation import WatchType
        assert WatchType.ALPHA.value == "alpha"


class TestStandingTask:
    def test_is_due_initially(self) -> None:
        from probos.watch_rotation import StandingTask
        task = StandingTask(interval_seconds=60, last_executed=0.0)
        assert task.is_due()

    def test_not_due_if_recent(self) -> None:
        import time
        from probos.watch_rotation import StandingTask
        task = StandingTask(interval_seconds=3600, last_executed=time.time())
        assert not task.is_due()


class TestWatchManager:
    def test_default_watch_is_alpha(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType
        mgr = WatchManager()
        assert mgr.current_watch == WatchType.ALPHA

    def test_set_current_watch(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType
        mgr = WatchManager()
        mgr.set_current_watch(WatchType.BETA)
        assert mgr.current_watch == WatchType.BETA

    def test_assign_and_get_on_duty(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType
        mgr = WatchManager()
        mgr.assign_to_watch("agent-1", WatchType.ALPHA)
        mgr.assign_to_watch("agent-2", WatchType.ALPHA)
        assert len(mgr.get_on_duty()) == 2

    def test_on_duty_changes_with_watch(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType
        mgr = WatchManager()
        mgr.assign_to_watch("agent-1", WatchType.ALPHA)
        mgr.assign_to_watch("agent-2", WatchType.BETA)
        assert "agent-1" in mgr.get_on_duty()
        assert "agent-2" not in mgr.get_on_duty()
        mgr.set_current_watch(WatchType.BETA)
        assert "agent-2" in mgr.get_on_duty()
        assert "agent-1" not in mgr.get_on_duty()

    def test_remove_from_watch(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType
        mgr = WatchManager()
        mgr.assign_to_watch("agent-1", WatchType.ALPHA)
        mgr.remove_from_watch("agent-1", WatchType.ALPHA)
        assert mgr.get_on_duty() == []

    def test_get_roster(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType
        mgr = WatchManager()
        mgr.assign_to_watch("a1", WatchType.ALPHA)
        mgr.assign_to_watch("a2", WatchType.GAMMA)
        roster = mgr.get_roster()
        assert "a1" in roster["alpha"]
        assert "a2" in roster["gamma"]

    def test_add_standing_task(self) -> None:
        from probos.watch_rotation import WatchManager, StandingTask
        mgr = WatchManager()
        mgr.add_standing_task(StandingTask(id="t1", department="medical"))
        assert len(mgr.get_standing_tasks()) == 1

    def test_remove_standing_task(self) -> None:
        from probos.watch_rotation import WatchManager, StandingTask
        mgr = WatchManager()
        mgr.add_standing_task(StandingTask(id="t1"))
        assert mgr.remove_standing_task("t1")
        assert len(mgr.get_standing_tasks()) == 0

    def test_filter_tasks_by_department(self) -> None:
        from probos.watch_rotation import WatchManager, StandingTask
        mgr = WatchManager()
        mgr.add_standing_task(StandingTask(id="t1", department="medical"))
        mgr.add_standing_task(StandingTask(id="t2", department="engineering"))
        assert len(mgr.get_standing_tasks("medical")) == 1

    def test_issue_captain_order(self) -> None:
        from probos.watch_rotation import WatchManager, CaptainOrder
        mgr = WatchManager()
        mgr.issue_order(CaptainOrder(id="o1", target="builder", description="Build module"))
        assert len(mgr.get_active_orders()) == 1

    def test_rescind_captain_order(self) -> None:
        from probos.watch_rotation import WatchManager, CaptainOrder
        mgr = WatchManager()
        mgr.issue_order(CaptainOrder(id="o1", target="builder", description="Build"))
        assert mgr.rescind_order("o1")
        assert len(mgr.get_active_orders()) == 0

    def test_filter_orders_by_target(self) -> None:
        from probos.watch_rotation import WatchManager, CaptainOrder
        mgr = WatchManager()
        mgr.issue_order(CaptainOrder(id="o1", target="builder"))
        mgr.issue_order(CaptainOrder(id="o2", target="architect"))
        assert len(mgr.get_active_orders("builder")) == 1

    @pytest.mark.asyncio
    async def test_dispatch_standing_task(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType, StandingTask
        mock_dispatch = AsyncMock()
        mgr = WatchManager(dispatch_fn=mock_dispatch)
        mgr.assign_to_watch("agent-1", WatchType.ALPHA)
        mgr.add_standing_task(StandingTask(
            id="t1", intent_type="run_diagnostics",
            interval_seconds=0,  # always due
        ))
        await mgr._dispatch_due_tasks()
        mock_dispatch.assert_awaited_once_with("run_diagnostics", {})

    @pytest.mark.asyncio
    async def test_one_shot_order_deactivates(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType, CaptainOrder
        mock_dispatch = AsyncMock()
        mgr = WatchManager(dispatch_fn=mock_dispatch)
        mgr.assign_to_watch("agent-1", WatchType.ALPHA)
        mgr.issue_order(CaptainOrder(
            id="o1", target="agent-1", target_type="agent",
            intent_type="special_task", one_shot=True,
        ))
        await mgr._dispatch_due_orders()
        assert not mgr.get_active_orders()[0].active if mgr._captain_orders else True
        # one_shot order should now be inactive
        assert len(mgr.get_active_orders()) == 0

    @pytest.mark.asyncio
    async def test_dispatch_skips_off_duty(self) -> None:
        from probos.watch_rotation import WatchManager, WatchType, CaptainOrder
        mock_dispatch = AsyncMock()
        mgr = WatchManager(dispatch_fn=mock_dispatch)
        # agent-1 on Beta, but we're on Alpha
        mgr.assign_to_watch("agent-1", WatchType.BETA)
        mgr.issue_order(CaptainOrder(
            id="o1", target="agent-1", target_type="agent",
            intent_type="task",
        ))
        await mgr._dispatch_due_orders()
        mock_dispatch.assert_not_awaited()
```

---

## Constraints

- Do NOT modify any existing files — this is a standalone new module
- Do NOT wire into `runtime.py` — runtime integration will be a separate AD
- `dispatch_fn` follows the same callback pattern as BuildDispatcher's `on_build_complete`
- The watch system is time-aware (via `is_due()`) but does NOT auto-rotate watches based
  on clock time — watch changes are either manual (`set_current_watch`) or will be
  automated in a future AD
- Captain's orders with `one_shot=True` are automatically deactivated after first execution
- Standing tasks track their own `last_executed` timestamp for interval-based scheduling
