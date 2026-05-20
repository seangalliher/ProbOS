# AD-752 - Proactive Scheduling + Work-Hours/Quiet-Hours Policy

Status: drafted (planning slate only)
Issue: #698
Parent: #486
Depends on: AD-750 (#696)
Related: #483

## Objective
Provide proactive assistant behavior with policy-safe heartbeat scans and schedule nudges.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Work-hours and quiet-hours policy model.
- Heartbeat/cron scan policy and suppression windows.
- Daily briefing trigger windows and reminder throttles.
- UX conventions for cron automation status and editability.

## Out of Scope
- Commercial enterprise policy orchestration products.
- Replacing existing task scheduler primitives.

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- Work-hours and quiet-hours configured locally by Captain.
- Cron-driven proactive scans during work hours.
- Daily briefing trigger windows and reminder throttles.

**Commercial Extension Point:**
- Org-wide work-hours policy distribution and enforcement.
- Incident routing during org quiet-hours (ROTA-based escalation).
- Cross-device proactive policy and time-zone handling for remote teams.

## File Targets
- `src/probos/proactive.py`
- `src/probos/duty_schedule.py`
- `src/probos/agents/operations/scheduler.py`
- `src/probos/config.py`
- `ui/src/components/wardroom/`

## Pre-Flight Anchors
- Verify scheduler behavior in `src/probos/agents/operations/scheduler.py`.
- Verify persistent scheduled-task APIs in `src/probos/routers/scheduled_tasks.py`.
- Verify proactive routing hooks in `src/probos/proactive.py`.

## Implementation Spec

### Section 1: Work-Hours & Quiet-Hours Policy Model

**File:** `src/probos/duty_schedule.py` (extend existing)

Add `DutySchedule` + `PolicyWindow` classes:
```python
@dataclass
class PolicyWindow:
    start_time: str  # "08:00" format
    end_time: str    # "18:00" format
    days: list[int]  # [0-6] = Mon-Sun (or [] for every day)
    
    def is_active(self, dt: datetime) -> bool:
        """Check if dt falls within this window."""

class DutySchedule:
    def __init__(self, config: DutyScheduleConfig):
        self.work_hours: PolicyWindow = config.work_hours
        self.quiet_hours: PolicyWindow = config.quiet_hours
        self.exceptions: dict[str, PolicyWindow] = {}  # date → override
    
    def should_scan(self, scan_type: str, dt: datetime | None = None) -> bool:
        """Is it OK to run a proactive scan right now?
        
        scan_type: "inbox" | "calendar" | "teams" (different rules per type)
        dt: defaults to now()
        """
    
    def next_scan_window(self, scan_type: str) -> datetime:
        """When is the next allowed scan window?"""
    
    def reason_code(self, scan_type: str, dt: datetime) -> str:
        """Return reason if scan is blocked (audit trail).
        
        Examples:
        - "outside_work_hours"
        - "quiet_hours_active"
        - "recent_scan_throttle" (too frequent)
        """
```

**Config (system.yaml):**
```yaml
duty_schedule:
  work_hours:
    start_time: "08:00"
    end_time: "18:00"
    days: [0, 1, 2, 3, 4]  # Mon-Fri
  quiet_hours:
    start_time: "19:00"
    end_time: "08:00"
    days: []  # Every day
  scan_throttle_sec:
    inbox: 300      # 5min between scans
    calendar: 600   # 10min
    teams: 900      # 15min
```

**Tests:** `tests/test_duty_schedule.py` (4 tests)
- Should-scan logic honors work-hours + quiet-hours
- Throttle prevents duplicate scans within window
- Reason-code audit trail for blocked scans
- Exception override (e.g. weekend override for urgent)

### Section 2: Proactive Scan Orchestration

**File:** `src/probos/proactive.py` (extend)

Create `ProactiveScanAgent` class (CognitiveAgent subclass):
```python
class ProactiveScanAgent(CognitiveAgent):
    """Periodic scans: inbox, calendar, Teams. Governed by duty schedule."""
    
    async def perceive(self) -> IntentMessage:
        schedule: DutySchedule = self._runtime.duty_schedule
        
        scans_to_run = []
        for scan_type in ["inbox", "calendar", "teams"]:
            if schedule.should_scan(scan_type):
                scans_to_run.append(scan_type)
            else:
                reason = schedule.reason_code(scan_type, datetime.now())
                logger.debug(f"Scan {scan_type} skipped: {reason}")
        
        return IntentMessage(
            intent="proactive_scan",
            params={"scan_types": scans_to_run, "tagged_as": "heartbeat"}
        )
```

The intent `proactive_scan` with `tagged_as="heartbeat"` ensures:
- Won't pollute episodic memory (heartbeat filter in dreaming)
- Won't increment trust scores (routine operation)
- Won't trigger red-team review (governance bypass for trusted ops)

**Tests:** `tests/test_proactive_scan_agent.py` (3 tests)
- Inbox scan only during work-hours
- Calendar + Teams suppressed during quiet-hours
- Heartbeat tagging prevents episodic pollution

### Section 3: Daily Briefing Trigger

**File:** `src/probos/proactive.py` (extend)

Create `DailyBriefingScheduler` class:
```python
class DailyBriefingScheduler:
    async def trigger_briefing_if_time(self) -> bool:
        """Check if it's time for daily briefing (e.g., 08:00 on weekdays).
        
        Returns: True if briefing was triggered, False if suppressed by policy.
        """
```

**Trigger Window:** First interaction after 08:00 AM (or configured time).
- Once per day per Captain
- Persisted in `data/briefing_state.json`

**Content:** LLM-synthesized summary of:
- Overnight changes (emails, meeting invites, messages)
- Overdue tasks
- Suggested actions (Hebbian-ranked from personal data)

**Tests:** `tests/test_daily_briefing_scheduler.py` (2 tests)
- Briefing triggered exactly once per day
- Suppressed if explicitly dismissed by Captain

### Section 4: Cron-Based Heartbeat

**File:** `src/probos/agents/operations/scheduler.py` (extend)

Extend scheduler to register heartbeat jobs:
```python
scheduler.add_job(
    proactive_scan_agent.perceive,
    trigger="cron",
    hour="8-18",  # 8am-6pm
    minute="*/15",  # every 15 minutes
    id="proactive_scan_inbox"
)
```

Use APScheduler (existing dependency) to persist scheduled tasks to disk/ChromaDB.

**Tests:** `tests/test_scheduler_heartbeat.py` (2 tests)
- Jobs registered + persisted across restarts
- No jobs execute outside work-hours window

### Section 5: Ward Room UX for Proactive Status

**File:** `ui/src/components/wardroom/ProactiveStatus.tsx` (new component)

Display:
- Next scheduled scan time
- Work-hours / quiet-hours indicators
- Last scan results (count of items found)
- "Disable proactive" toggle (soft-disable)

**Endpoint:** `GET /proactive/status` returns:
```json
{
  "next_inbox_scan": "2026-05-20T14:00:00Z",
  "next_calendar_scan": "2026-05-20T14:15:00Z",
  "work_hours_active": true,
  "quiet_hours_active": false,
  "last_scan_count": {"inbox": 3, "calendar": 0, "teams": 1}
}
```

### Section 6: Acceptance Criteria & Gate

**Test Expectations:**
- `test_duty_schedule.py`: 4 tests
- `test_proactive_scan_agent.py`: 3 tests
- `test_daily_briefing_scheduler.py`: 2 tests
- `test_scheduler_heartbeat.py`: 2 tests
- **Total: 11 new tests**

**Integration Gate:** Requires AD-750 (semantic work layer) to exist for scan-result processing + briefing synthesis.

**Type Annotations:** All public methods fully typed.

**Completion Signal:**
- All 11 tests passing
- Proactive scans don't run outside configured windows
- Daily briefing triggers exactly once per 24h
- Heartbeat jobs persist across restart
- Audit trail (reason-codes) available for every suppressed scan

## Acceptance Criteria
- Work-hours/quiet-hours policies are explicit, testable, and overridable.
- Proactive scans are auditable with clear reason codes.
- No duplicate scheduler subsystem is introduced.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
