# AD-419: Agent Duty Schedule & Justification

## Context

The proactive cognitive loop (Phase 28b) gives crew agents freedom to think independently every cooldown cycle. But freedom without structure is chaos — observed when Wesley (Scout) runs scout reports every 5 minutes instead of once daily. All crew agents are producing similar "startup observation" posts because none of them have defined responsibilities on a schedule.

**Design principle:** The Plan of the Day (POD). Every sailor knows their watch schedule, maintenance duties, and drill times. They can act on initiative, but they'd better have a reason if the XO asks why they deviated from schedule. Duty schedules define *what agents should be doing*; free-form thinking is the space between duties that requires justification.

**Key behavior change:** When a duty is due, the proactive loop sends a duty-specific prompt instead of a free-form think. When no duty is due, the prompt requires the agent to justify why they're sharing an observation. `[NO_RESPONSE]` is the expected default for off-duty cycles — silence is professionalism, not failure.

## Reference Files

- `src/probos/proactive.py` — `ProactiveCognitiveLoop`, `_think_for_agent()` at line 117, `_run_cycle()` at line 86
- `src/probos/cognitive/cognitive_agent.py` — `_format_observation()` proactive_think branch at line 346
- `src/probos/config.py` — `ProactiveCognitiveConfig` at line 297
- `config/system.yaml` — proactive_cognitive section at line 246
- `src/probos/earned_agency.py` — `agency_from_rank()`, `can_think_proactively()`
- `pyproject.toml` — `croniter` already a dependency (Phase 25a)
- `src/probos/cognitive/standing_orders.py` — `_AGENT_DEPARTMENTS`, `get_department()`

## Part 1: Duty Schedule Config — `config.py`

Add a `DutyDefinition` model and extend `ProactiveCognitiveConfig`. Place `DutyDefinition` before `ProactiveCognitiveConfig`:

```python
class DutyDefinition(BaseModel):
    """A single recurring duty for a crew agent type."""
    duty_id: str                # e.g., "scout_report"
    description: str            # Human-readable task description
    cron: str = ""              # Cron expression (croniter format). Empty = interval-based.
    interval_seconds: float = 0 # Alternative to cron: simple interval. 0 = use cron.
    priority: int = 2           # 1-5, higher = more important when multiple due


class DutyScheduleConfig(BaseModel):
    """Duty schedule definitions per agent type (AD-419)."""
    enabled: bool = True
    schedules: dict[str, list[DutyDefinition]] = {}
```

Update `ProactiveCognitiveConfig` to include the duty schedule:

```python
class ProactiveCognitiveConfig(BaseModel):
    """Proactive Cognitive Loop — periodic idle-think (Phase 28b)."""
    enabled: bool = False
    interval_seconds: float = 120.0
    cooldown_seconds: float = 300.0
    duty_schedule: DutyScheduleConfig = DutyScheduleConfig()
```

Add `DutyScheduleConfig` and `DutyDefinition` to the `ProbOSConfig` model's imports if needed.

## Part 2: Duty Schedule Tracker — `duty_schedule.py` (NEW)

Create `src/probos/duty_schedule.py`:

```python
"""Agent Duty Schedule — Plan of the Day (AD-419).

Tracks recurring duties per agent type and determines which duties
are due on each proactive cycle. Uses croniter for cron-based scheduling
and simple interval math for interval-based duties.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DutyStatus:
    """Tracks execution state for a single duty."""
    duty_id: str
    agent_type: str
    last_executed: float = 0.0     # time.time() of last execution
    execution_count: int = 0


class DutyScheduleTracker:
    """Tracks duty execution and determines which duties are due.

    The tracker is in-memory — on restart, all duties show as "never executed"
    and will fire on their first eligible cycle. This is correct behavior:
    a fresh start means fresh duties.
    """

    def __init__(self, schedules: dict[str, list[Any]]) -> None:
        """Initialize with schedule config.

        Args:
            schedules: dict mapping agent_type -> list of DutyDefinition objects
        """
        self._schedules = schedules
        self._status: dict[str, DutyStatus] = {}  # keyed by "agent_type:duty_id"

    def _status_key(self, agent_type: str, duty_id: str) -> str:
        return f"{agent_type}:{duty_id}"

    def get_due_duties(self, agent_type: str) -> list[Any]:
        """Return list of DutyDefinition objects that are currently due.

        A duty is due if:
        - cron-based: the next fire time after last_executed is <= now
        - interval-based: now - last_executed >= interval_seconds
        - never executed: always due (first cycle after startup)

        Returns duties sorted by priority (highest first).
        """
        duties = self._schedules.get(agent_type, [])
        if not duties:
            return []

        now = time.time()
        due: list[Any] = []

        for duty in duties:
            key = self._status_key(agent_type, duty.duty_id)
            status = self._status.get(key)
            last = status.last_executed if status else 0.0

            is_due = False

            if duty.cron:
                try:
                    from croniter import croniter
                    cron = croniter(duty.cron, last)
                    next_fire = cron.get_next(float)
                    if next_fire <= now:
                        is_due = True
                except Exception:
                    logger.debug("Invalid cron for duty %s: %s", duty.duty_id, duty.cron)
            elif duty.interval_seconds > 0:
                if now - last >= duty.interval_seconds:
                    is_due = True

            if is_due:
                due.append(duty)

        # Sort by priority descending (highest first)
        due.sort(key=lambda d: d.priority, reverse=True)
        return due

    def record_execution(self, agent_type: str, duty_id: str) -> None:
        """Record that a duty was executed."""
        key = self._status_key(agent_type, duty_id)
        status = self._status.get(key)
        if status:
            status.last_executed = time.time()
            status.execution_count += 1
        else:
            self._status[key] = DutyStatus(
                duty_id=duty_id,
                agent_type=agent_type,
                last_executed=time.time(),
                execution_count=1,
            )

    def get_status(self, agent_type: str) -> list[dict[str, Any]]:
        """Return status of all duties for an agent type (for state snapshot)."""
        duties = self._schedules.get(agent_type, [])
        result = []
        for duty in duties:
            key = self._status_key(agent_type, duty.duty_id)
            status = self._status.get(key)
            result.append({
                "duty_id": duty.duty_id,
                "description": duty.description,
                "last_executed": status.last_executed if status else 0.0,
                "execution_count": status.execution_count if status else 0,
                "priority": duty.priority,
            })
        return result
```

## Part 3: Wire Duty Schedule into Proactive Loop — `proactive.py`

### 3a. Initialize tracker

In `ProactiveCognitiveLoop.__init__()`, add after `self._runtime`:

```python
self._duty_tracker: DutyScheduleTracker | None = None
```

Add a new property for accessing the default cooldown:

```python
@property
def _default_cooldown(self) -> float:
    return self._cooldown
```

### 3b. Set up tracker from config

Add a method to initialize the duty tracker from config:

```python
def set_duty_schedule(self, config: Any) -> None:
    """Initialize duty schedule tracker from DutyScheduleConfig."""
    from probos.duty_schedule import DutyScheduleTracker
    if config and config.enabled and config.schedules:
        self._duty_tracker = DutyScheduleTracker(config.schedules)
        logger.info("Duty schedule loaded: %d agent types configured",
                     len(config.schedules))
    else:
        self._duty_tracker = None
```

### 3c. Modify `_think_for_agent()`

Replace the current `_think_for_agent()` method (lines 117-159) with a version that checks duty schedule first:

```python
async def _think_for_agent(self, agent: Any, rank: Rank, trust_score: float) -> None:
    """Gather context, send proactive_think intent, post result if meaningful.

    AD-419: If a duty is due, send a duty-specific prompt. If no duty is due,
    send a free-form think prompt that requires justification.
    """
    rt = self._runtime
    context_parts = await self._gather_context(agent, trust_score)

    # AD-419: Check duty schedule
    duty = None
    if self._duty_tracker:
        due_duties = self._duty_tracker.get_due_duties(agent.agent_type)
        if due_duties:
            duty = due_duties[0]  # Highest priority

    intent = IntentMessage(
        intent="proactive_think",
        params={
            "context_parts": context_parts,
            "trust_score": round(trust_score, 4),
            "agency_level": agency_from_rank(rank).value,
            "agent_type": agent.agent_type,
            "duty": {
                "duty_id": duty.duty_id,
                "description": duty.description,
            } if duty else None,
        },
        target_agent_id=agent.id,
    )

    result = await agent.handle_intent(intent)

    if not result or not result.success or not result.result:
        return

    response_text = str(result.result).strip()
    if not response_text or "[NO_RESPONSE]" in response_text:
        # Record duty execution even if agent had nothing to report
        if duty and self._duty_tracker:
            self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
        return

    # Post to Ward Room — find agent's department channel
    await self._post_to_ward_room(agent, response_text)
    self._last_proactive[agent.id] = time.monotonic()

    # Record duty execution after successful post
    if duty and self._duty_tracker:
        self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)

    if self._on_event:
        self._on_event({
            "type": "proactive_thought",
            "data": {
                "agent_id": agent.id,
                "agent_type": agent.agent_type,
                "response_length": len(response_text),
                "duty_id": duty.duty_id if duty else None,
            },
        })

    logger.info(
        "Proactive thought from %s (%s): %d chars%s",
        agent.agent_type, rank.value, len(response_text),
        f" [duty: {duty.duty_id}]" if duty else " [free-form]",
    )
```

## Part 4: Update Proactive Think Prompt — `cognitive_agent.py`

Replace the proactive_think branch in `_format_observation()` (lines 346-387) to handle duty vs free-form:

```python
# Phase 28b: proactive_think — idle review cycle
if intent_name == "proactive_think":
    context_parts = params.get("context_parts", {})
    trust_score = params.get("trust_score", 0.5)
    agency_level = params.get("agency_level", "suggestive")
    duty = params.get("duty")  # AD-419: may be None

    pt_parts: list[str] = []

    if duty:
        # AD-419: Duty cycle — agent has a scheduled task
        pt_parts.append(f"[Duty Cycle: {duty.get('description', duty.get('duty_id', 'unknown'))}]")
        pt_parts.append(f"Your trust: {trust_score} | Agency: {agency_level}")
        pt_parts.append("")
        pt_parts.append("This is a scheduled duty. Perform your assigned task and report your findings.")
        pt_parts.append("")
    else:
        # Free-form think — no duty due, requires justification
        pt_parts.append("[Proactive Review — No Scheduled Duty]")
        pt_parts.append(f"Your trust: {trust_score} | Agency: {agency_level}")
        pt_parts.append("")
        pt_parts.append("You have no scheduled duty at this time. You may share an observation")
        pt_parts.append("ONLY if you notice something genuinely noteworthy or actionable.")
        pt_parts.append("If you do post, include a brief justification for why it matters now.")
        pt_parts.append("Silence is professionalism — [NO_RESPONSE] is the expected default.")
        pt_parts.append("")

    # Recent memories
    memories = context_parts.get("recent_memories", [])
    if memories:
        pt_parts.append("Recent memories (your experiences):")
        for m in memories:
            if m.get("reflection"):
                pt_parts.append(f"  - {m['reflection']}")
            elif m.get("input"):
                pt_parts.append(f"  - Handled: {m['input']}")
        pt_parts.append("")

    # Recent alerts
    alerts = context_parts.get("recent_alerts", [])
    if alerts:
        pt_parts.append("Recent bridge alerts:")
        for a in alerts:
            pt_parts.append(f"  - [{a.get('severity', '?')}] {a.get('title', '?')} (from {a.get('source', '?')})")
        pt_parts.append("")

    # Recent events
    events = context_parts.get("recent_events", [])
    if events:
        pt_parts.append("Recent system events:")
        for e in events:
            pt_parts.append(f"  - [{e.get('category', '?')}] {e.get('event', '?')}")
        pt_parts.append("")

    # Recent Ward Room activity (AD-413)
    wr_activity = context_parts.get("ward_room_activity", [])
    if wr_activity:
        pt_parts.append("Recent Ward Room discussion in your department:")
        for a in wr_activity:
            prefix = "[thread]" if a.get("type") == "thread" else "[reply]"
            pt_parts.append(f"  - {prefix} {a.get('author', '?')}: {a.get('body', '?')}")
        pt_parts.append("")

    if duty:
        pt_parts.append("Compose a Ward Room post with your findings (2-4 sentences).")
        pt_parts.append("If nothing noteworthy to report, respond with exactly: [NO_RESPONSE]")
    else:
        pt_parts.append("If something genuinely warrants attention, compose a brief observation (2-4 sentences).")
        pt_parts.append("Include your justification. Otherwise respond with exactly: [NO_RESPONSE]")
    return "\n".join(pt_parts)
```

## Part 5: Wire in Runtime — `runtime.py`

In the runtime's `start()` method, after the proactive loop is created and `set_runtime()` is called, add duty schedule initialization. Find where `self.proactive_loop.set_runtime(self)` is called and add after it:

```python
# AD-419: Wire duty schedule
if config.proactive_cognitive.duty_schedule.enabled:
    self.proactive_loop.set_duty_schedule(config.proactive_cognitive.duty_schedule)
```

## Part 6: Default Duty Schedule Config — `system.yaml`

Update the `proactive_cognitive` section in `config/system.yaml`:

```yaml
proactive_cognitive:
  enabled: true
  interval_seconds: 120
  cooldown_seconds: 300
  duty_schedule:
    enabled: true
    schedules:
      scout:
        - duty_id: scout_report
          description: "Perform a comprehensive review of recent codebase and system changes"
          interval_seconds: 86400   # Once daily
          priority: 3
      security_officer:
        - duty_id: security_audit
          description: "Review system security posture, access patterns, and potential vulnerabilities"
          interval_seconds: 14400   # Every 4 hours
          priority: 3
      engineering_officer:
        - duty_id: systems_check
          description: "Review engineering systems health, performance metrics, and technical debt"
          interval_seconds: 7200    # Every 2 hours
          priority: 2
      operations_officer:
        - duty_id: ops_status
          description: "Review operational status, resource utilization, pool health, and queue depths"
          interval_seconds: 10800   # Every 3 hours
          priority: 2
      diagnostician:
        - duty_id: crew_health_check
          description: "Assess crew cognitive health, trust dynamics, and behavioral patterns"
          interval_seconds: 21600   # Every 6 hours
          priority: 2
      counselor:
        - duty_id: wellness_review
          description: "Review crew morale, interpersonal dynamics, and communication patterns"
          interval_seconds: 43200   # Every 12 hours
          priority: 2
      architect:
        - duty_id: architecture_review
          description: "Review system architecture, design patterns, and improvement opportunities"
          interval_seconds: 86400   # Once daily
          priority: 3
```

## Part 7: Tests — `tests/test_duty_schedule.py` (NEW)

Create `tests/test_duty_schedule.py`:

```python
"""Tests for Agent Duty Schedule (AD-419)."""

import time
from unittest.mock import MagicMock

import pytest

from probos.duty_schedule import DutyScheduleTracker, DutyStatus


def _make_duty(duty_id: str, interval: float = 3600, cron: str = "", priority: int = 2):
    """Create a mock DutyDefinition."""
    d = MagicMock()
    d.duty_id = duty_id
    d.description = f"Test duty: {duty_id}"
    d.cron = cron
    d.interval_seconds = interval
    d.priority = priority
    return d


class TestDutyScheduleTracker:

    def test_interval_duty_due_on_first_cycle(self):
        """Duties are always due on first cycle (last_executed=0)."""
        duty = _make_duty("test", interval=3600)
        tracker = DutyScheduleTracker({"scout": [duty]})
        due = tracker.get_due_duties("scout")
        assert len(due) == 1
        assert due[0].duty_id == "test"

    def test_interval_duty_not_due_after_execution(self):
        """Duty is not due if executed within interval."""
        duty = _make_duty("test", interval=3600)
        tracker = DutyScheduleTracker({"scout": [duty]})
        tracker.record_execution("scout", "test")
        due = tracker.get_due_duties("scout")
        assert len(due) == 0

    def test_interval_duty_due_after_interval(self):
        """Duty becomes due again after interval elapses."""
        duty = _make_duty("test", interval=1)  # 1 second interval
        tracker = DutyScheduleTracker({"scout": [duty]})
        tracker.record_execution("scout", "test")
        # Manually backdate last_executed
        key = tracker._status_key("scout", "test")
        tracker._status[key].last_executed = time.time() - 2
        due = tracker.get_due_duties("scout")
        assert len(due) == 1

    def test_cron_duty_due_on_first_cycle(self):
        """Cron duties are due on first cycle (never executed)."""
        duty = _make_duty("test", interval=0, cron="* * * * *")  # Every minute
        tracker = DutyScheduleTracker({"scout": [duty]})
        due = tracker.get_due_duties("scout")
        assert len(due) == 1

    def test_cron_duty_not_due_after_recent_execution(self):
        """Cron duty with hourly schedule not due just after execution."""
        duty = _make_duty("test", interval=0, cron="0 * * * *")  # Hourly
        tracker = DutyScheduleTracker({"scout": [duty]})
        tracker.record_execution("scout", "test")
        # Just executed — next hourly cron tick is in the future
        due = tracker.get_due_duties("scout")
        assert len(due) == 0

    def test_priority_sorting(self):
        """Duties returned in priority order (highest first)."""
        low = _make_duty("low", interval=0, cron="* * * * *", priority=1)
        high = _make_duty("high", interval=0, cron="* * * * *", priority=5)
        mid = _make_duty("mid", interval=0, cron="* * * * *", priority=3)
        tracker = DutyScheduleTracker({"scout": [low, high, mid]})
        due = tracker.get_due_duties("scout")
        assert [d.duty_id for d in due] == ["high", "mid", "low"]

    def test_no_duties_for_unknown_agent_type(self):
        """Unknown agent types return empty list."""
        tracker = DutyScheduleTracker({"scout": [_make_duty("test")]})
        due = tracker.get_due_duties("unknown_type")
        assert due == []

    def test_record_execution_increments_count(self):
        """Execution count tracks correctly."""
        duty = _make_duty("test", interval=3600)
        tracker = DutyScheduleTracker({"scout": [duty]})
        tracker.record_execution("scout", "test")
        tracker.record_execution("scout", "test")
        key = tracker._status_key("scout", "test")
        assert tracker._status[key].execution_count == 2

    def test_get_status_returns_all_duties(self):
        """get_status returns info for all configured duties."""
        d1 = _make_duty("report", interval=3600)
        d2 = _make_duty("scan", interval=7200)
        tracker = DutyScheduleTracker({"scout": [d1, d2]})
        tracker.record_execution("scout", "report")
        status = tracker.get_status("scout")
        assert len(status) == 2
        ids = {s["duty_id"] for s in status}
        assert ids == {"report", "scan"}
        report = next(s for s in status if s["duty_id"] == "report")
        assert report["execution_count"] == 1

    def test_mixed_cron_and_interval(self):
        """Can mix cron and interval-based duties for same agent type."""
        cron_duty = _make_duty("cron_task", interval=0, cron="* * * * *")
        interval_duty = _make_duty("interval_task", interval=1)
        tracker = DutyScheduleTracker({"scout": [cron_duty, interval_duty]})
        due = tracker.get_due_duties("scout")
        assert len(due) == 2


class TestProactiveLoopDutyIntegration:
    """Test that proactive loop correctly uses duty schedule."""

    @pytest.mark.asyncio
    async def test_duty_passed_to_intent(self):
        """When a duty is due, the intent includes duty info."""
        from unittest.mock import AsyncMock, patch

        from probos.proactive import ProactiveCognitiveLoop
        from probos.crew_profile import Rank

        loop = ProactiveCognitiveLoop(interval=120, cooldown=300)

        # Set up duty tracker
        duty = _make_duty("scout_report", interval=86400)
        from probos.duty_schedule import DutyScheduleTracker
        loop._duty_tracker = DutyScheduleTracker({"scout": [duty]})

        # Mock runtime
        rt = MagicMock()
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[])
        loop._runtime = rt

        # Mock agent
        agent = MagicMock()
        agent.id = "scout-1"
        agent.agent_type = "scout"
        agent.handle_intent = AsyncMock(return_value=MagicMock(
            success=True, result="[NO_RESPONSE]"
        ))

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        # Verify intent included duty info
        call_args = agent.handle_intent.call_args[0][0]
        assert call_args.params["duty"] is not None
        assert call_args.params["duty"]["duty_id"] == "scout_report"

    @pytest.mark.asyncio
    async def test_no_duty_passes_none(self):
        """When no duty is due, duty param is None."""
        from unittest.mock import AsyncMock, patch

        from probos.proactive import ProactiveCognitiveLoop
        from probos.crew_profile import Rank

        loop = ProactiveCognitiveLoop(interval=120, cooldown=300)

        # Empty duty schedule
        from probos.duty_schedule import DutyScheduleTracker
        loop._duty_tracker = DutyScheduleTracker({})

        rt = MagicMock()
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[])
        loop._runtime = rt

        agent = MagicMock()
        agent.id = "scout-1"
        agent.agent_type = "scout"
        agent.handle_intent = AsyncMock(return_value=MagicMock(
            success=True, result="[NO_RESPONSE]"
        ))

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        call_args = agent.handle_intent.call_args[0][0]
        assert call_args.params["duty"] is None

    @pytest.mark.asyncio
    async def test_duty_recorded_after_execution(self):
        """Duty execution is recorded even with NO_RESPONSE."""
        from unittest.mock import AsyncMock

        from probos.proactive import ProactiveCognitiveLoop
        from probos.crew_profile import Rank

        loop = ProactiveCognitiveLoop(interval=120, cooldown=300)

        duty = _make_duty("scout_report", interval=86400)
        from probos.duty_schedule import DutyScheduleTracker
        loop._duty_tracker = DutyScheduleTracker({"scout": [duty]})

        rt = MagicMock()
        rt.episodic_memory = None
        rt.bridge_alerts = None
        rt.event_log = None
        rt.ward_room = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[])
        loop._runtime = rt

        agent = MagicMock()
        agent.id = "scout-1"
        agent.agent_type = "scout"
        agent.handle_intent = AsyncMock(return_value=MagicMock(
            success=True, result="[NO_RESPONSE]"
        ))

        await loop._think_for_agent(agent, Rank.LIEUTENANT, 0.7)

        # Duty should be recorded as executed
        status = loop._duty_tracker.get_status("scout")
        assert status[0]["execution_count"] == 1
```

## Verification

```bash
# Targeted tests
uv run pytest tests/test_duty_schedule.py -x -v

# Proactive loop tests (ensure no regressions)
uv run pytest tests/test_proactive.py -x -v

# Full suite
uv run pytest tests/ --tb=short -q
```

Expected: all new tests pass, no regressions.
