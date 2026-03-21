# AD-316: AgentTask Data Model + TaskTracker Service

## Goal

Create the foundational `TaskTracker` service that gives every agent task a trackable lifecycle. Today, build and design progress events are ad-hoc — hardcoded step labels emitted from `api.py` endpoints. TaskTracker replaces this with a unified model: any agent activity (build, design, diagnostic, assessment, query) registers as an `AgentTask` with real `TaskStep` progress, and the `MissionControlTask` interface in the frontend is populated from this authoritative source instead of being derived only from `BuildQueueItem`.

## Architecture

**Pattern:** Follow the existing service patterns — SIF (AD-370), BuildQueue/BuildDispatcher (AD-375).

## Files to Create

### `src/probos/task_tracker.py` (~200 lines)

```python
"""AD-316: AgentTask Data Model + TaskTracker Service."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class TaskType(str, Enum):
    BUILD = "build"
    DESIGN = "design"
    DIAGNOSTIC = "diagnostic"
    ASSESSMENT = "assessment"
    QUERY = "query"


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    WORKING = "working"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"


@dataclass
class TaskStep:
    """A single step in an agent task."""
    label: str
    status: StepStatus = StepStatus.PENDING
    started_at: float = 0.0
    duration_ms: float = 0.0

    def start(self) -> None:
        self.status = StepStatus.IN_PROGRESS
        self.started_at = time.time()

    def complete(self) -> None:
        self.status = StepStatus.DONE
        if self.started_at > 0:
            self.duration_ms = (time.time() - self.started_at) * 1000

    def fail(self) -> None:
        self.status = StepStatus.FAILED
        if self.started_at > 0:
            self.duration_ms = (time.time() - self.started_at) * 1000

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "status": self.status.value,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
        }


@dataclass
class AgentTask:
    """A trackable unit of agent work."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent_id: str = ""
    agent_type: str = ""
    department: str = ""
    task_type: TaskType = TaskType.QUERY
    title: str = ""
    status: TaskStatus = TaskStatus.QUEUED
    steps: list[TaskStep] = field(default_factory=list)
    requires_action: bool = False
    action_type: str = ""  # "approve", "review", "respond", or ""
    started_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""
    priority: int = 3
    ad_number: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def start(self) -> None:
        self.status = TaskStatus.WORKING
        self.started_at = time.time()

    def set_review(self, action_type: str = "approve") -> None:
        self.status = TaskStatus.REVIEW
        self.requires_action = True
        self.action_type = action_type

    def complete(self) -> None:
        self.status = TaskStatus.DONE
        self.completed_at = time.time()
        self.requires_action = False
        self.action_type = ""

    def fail(self, error: str = "") -> None:
        self.status = TaskStatus.FAILED
        self.completed_at = time.time()
        self.error = error
        self.requires_action = False

    def add_step(self, label: str) -> TaskStep:
        step = TaskStep(label=label)
        self.steps.append(step)
        return step

    def current_step(self) -> TaskStep | None:
        for step in self.steps:
            if step.status == StepStatus.IN_PROGRESS:
                return step
        return None

    def step_progress(self) -> tuple[int, int]:
        done = sum(1 for s in self.steps if s.status in (StepStatus.DONE, StepStatus.FAILED))
        return done, len(self.steps)

    def to_dict(self) -> dict[str, Any]:
        current, total = self.step_progress()
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "department": self.department,
            "type": self.task_type.value,
            "title": self.title,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "requires_action": self.requires_action,
            "action_type": self.action_type,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "priority": self.priority,
            "ad_number": self.ad_number,
            "metadata": self.metadata,
            "step_current": current,
            "step_total": total,
        }


class TaskTracker:
    """Central registry of active and recent agent tasks (AD-316).

    Agents register tasks, emit step updates, and mark completion.
    The tracker emits events via a callback for WebSocket broadcasting.
    """

    def __init__(self, on_event: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self._tasks: dict[str, AgentTask] = {}
        self._on_event = on_event
        self._max_done: int = 50  # keep last N completed tasks

    # --- Task lifecycle ---

    def create_task(
        self,
        *,
        agent_id: str = "",
        agent_type: str = "",
        department: str = "",
        task_type: TaskType = TaskType.QUERY,
        title: str = "",
        priority: int = 3,
        ad_number: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> AgentTask:
        task = AgentTask(
            agent_id=agent_id,
            agent_type=agent_type,
            department=department,
            task_type=task_type,
            title=title,
            priority=priority,
            ad_number=ad_number,
            metadata=metadata or {},
        )
        self._tasks[task.id] = task
        self._emit("task_created", task)
        return task

    def start_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            task.start()
            self._emit("task_updated", task)

    def advance_step(self, task_id: str, step_label: str) -> TaskStep | None:
        """Complete the current step (if any) and start a new one."""
        task = self._tasks.get(task_id)
        if not task:
            return None
        # Complete current in-progress step
        current = task.current_step()
        if current:
            current.complete()
        # Start new step
        step = task.add_step(step_label)
        step.start()
        self._emit("task_updated", task)
        return step

    def complete_step(self, task_id: str) -> None:
        """Complete the current in-progress step without starting a new one."""
        task = self._tasks.get(task_id)
        if task:
            current = task.current_step()
            if current:
                current.complete()
            self._emit("task_updated", task)

    def set_review(self, task_id: str, action_type: str = "approve") -> None:
        task = self._tasks.get(task_id)
        if task:
            task.set_review(action_type)
            self._emit("task_updated", task)

    def complete_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task:
            # Complete any remaining in-progress step
            current = task.current_step()
            if current:
                current.complete()
            task.complete()
            self._emit("task_updated", task)
            self._prune_done()

    def fail_task(self, task_id: str, error: str = "") -> None:
        task = self._tasks.get(task_id)
        if task:
            current = task.current_step()
            if current:
                current.fail()
            task.fail(error)
            self._emit("task_updated", task)

    # --- Queries ---

    def get_task(self, task_id: str) -> AgentTask | None:
        return self._tasks.get(task_id)

    def active_tasks(self) -> list[AgentTask]:
        return [t for t in self._tasks.values()
                if t.status in (TaskStatus.QUEUED, TaskStatus.WORKING, TaskStatus.REVIEW)]

    def needs_attention(self) -> list[AgentTask]:
        return [t for t in self._tasks.values() if t.requires_action]

    def all_tasks(self) -> list[AgentTask]:
        return list(self._tasks.values())

    def snapshot(self) -> list[dict[str, Any]]:
        """Return all tasks as dicts for WebSocket broadcast."""
        return [t.to_dict() for t in self._tasks.values()]

    # --- Internal ---

    def _emit(self, event_type: str, task: AgentTask) -> None:
        if self._on_event:
            self._on_event(event_type, {"task": task.to_dict(), "tasks": self.snapshot()})

    def _prune_done(self) -> None:
        done = [t for t in self._tasks.values()
                if t.status in (TaskStatus.DONE, TaskStatus.FAILED)]
        if len(done) > self._max_done:
            done.sort(key=lambda t: t.completed_at)
            for t in done[: len(done) - self._max_done]:
                del self._tasks[t.id]
```

## Files to Modify

### `src/probos/runtime.py`

**1. Add import** near the existing build_queue imports (around line 44-47):

```python
from probos.task_tracker import TaskTracker
```

**2. Add field** in `__init__()` after `self.build_dispatcher` (around line 238):

```python
# --- Task Tracker (AD-316) ---
self.task_tracker: TaskTracker | None = None
```

**3. Initialize in `start()`** after the build dispatcher block (around line 922):

```python
# --- Task Tracker (AD-316) ---
self.task_tracker = TaskTracker(on_event=self._emit_event)
logger.info("task-tracker started")
```

**4. Cleanup in `stop()`** after the build dispatcher cleanup (around line 958):

```python
if self.task_tracker:
    self.task_tracker = None
```

**5. Add to `build_state_snapshot()`** — find the existing method (search for `def build_state_snapshot`) and add the task_tracker snapshot to the returned dict:

```python
if self.task_tracker:
    snapshot["tasks"] = self.task_tracker.snapshot()
```

### `ui/src/store/types.ts`

**Add `AgentTaskView` interface** after the `MissionControlTask` interface (around line 141):

```typescript
export interface TaskStepView {
  label: string;
  status: 'pending' | 'in_progress' | 'done' | 'failed';
  started_at: number;
  duration_ms: number;
}

export interface AgentTaskView {
  id: string;
  agent_id: string;
  agent_type: string;
  department: string;
  type: 'build' | 'design' | 'diagnostic' | 'assessment' | 'query';
  title: string;
  status: 'queued' | 'working' | 'review' | 'done' | 'failed';
  steps: TaskStepView[];
  requires_action: boolean;
  action_type: string;
  started_at: number;
  completed_at: number;
  error: string;
  priority: number;
  ad_number: number;
  metadata: Record<string, unknown>;
  step_current: number;
  step_total: number;
}
```

### `ui/src/store/useStore.ts`

**1. Add import** — add `AgentTaskView` to the import from `./types`.

**2. Add state fields** to `HXIState` interface (near `missionControlTasks`):

```typescript
agentTasks: AgentTaskView[] | null;
```

**3. Initialize** in the state object:

```typescript
agentTasks: null,
```

**4. Add event handler cases** in `handleEvent` switch:

```typescript
case 'task_created':
case 'task_updated': {
  const tasks = (data.tasks || []) as AgentTaskView[];
  // Also derive missionControlTasks from agentTasks
  const mcTasks: MissionControlTask[] = tasks.map(t => ({
    id: t.id,
    type: t.type as MissionControlTask['type'],
    title: t.title,
    department: t.department,
    status: t.status as MissionControlTask['status'],
    agent_type: t.agent_type,
    agent_id: t.agent_id,
    started_at: t.started_at,
    completed_at: t.completed_at,
    priority: t.priority,
    ad_number: t.ad_number,
    error: t.error,
    metadata: t.metadata,
  }));
  set({
    agentTasks: tasks.length > 0 ? tasks : null,
    missionControlTasks: mcTasks.length > 0 ? mcTasks : null,
  });
  break;
}
```

**5. Update `state_snapshot` handler** — in the `case 'state_snapshot':` block, add after existing state hydration:

```typescript
if (data.tasks) {
  const tasks = data.tasks as AgentTaskView[];
  const mcTasks: MissionControlTask[] = tasks.map(t => ({
    id: t.id,
    type: t.type as MissionControlTask['type'],
    title: t.title,
    department: t.department,
    status: t.status as MissionControlTask['status'],
    agent_type: t.agent_type,
    agent_id: t.agent_id,
    started_at: t.started_at,
    completed_at: t.completed_at,
    priority: t.priority,
    ad_number: t.ad_number,
    error: t.error,
    metadata: t.metadata,
  }));
  set({
    agentTasks: tasks.length > 0 ? tasks : null,
    missionControlTasks: mcTasks.length > 0 ? mcTasks : null,
  });
}
```

## Files to Create — Tests

### `tests/test_task_tracker.py`

Test these behaviors:
1. `TaskTracker()` creates with empty state
2. `create_task()` returns an `AgentTask` with correct fields and emits `task_created`
3. `start_task()` sets status to WORKING and `started_at`
4. `advance_step()` completes current step and starts new one
5. `advance_step()` on first call starts step without completing any
6. `complete_step()` completes current in-progress step
7. `complete_task()` sets status to DONE and `completed_at`, completes lingering step
8. `fail_task()` sets status to FAILED with error message, fails lingering step
9. `set_review()` sets requires_action=True and action_type
10. `active_tasks()` returns only QUEUED/WORKING/REVIEW tasks
11. `needs_attention()` returns only tasks with requires_action=True
12. `snapshot()` returns list of task dicts
13. `_prune_done()` removes oldest completed when exceeding _max_done
14. `step_progress()` returns (done_count, total_count)
15. `to_dict()` includes all fields including step_current/step_total
16. Event callback receives both the individual task dict and full snapshot
17. `AgentTask.add_step()` adds and returns a TaskStep
18. `TaskStep.start()`/`complete()`/`fail()` set status and timing correctly

Use `unittest.TestCase`. Pattern:

```python
import unittest
from probos.task_tracker import TaskTracker, TaskType, TaskStatus, StepStatus, AgentTask, TaskStep

class TestTaskStep(unittest.TestCase):
    ...

class TestAgentTask(unittest.TestCase):
    ...

class TestTaskTracker(unittest.TestCase):
    def setUp(self):
        self.events: list[tuple[str, dict]] = []
        def on_event(event_type, data):
            self.events.append((event_type, data))
        self.tracker = TaskTracker(on_event=on_event)
    ...
```

## Verification

```bash
cd d:\ProbOS
.venv/Scripts/python.exe -m pytest tests/test_task_tracker.py -v
```

All tests must pass. Do NOT modify any files not listed above.
