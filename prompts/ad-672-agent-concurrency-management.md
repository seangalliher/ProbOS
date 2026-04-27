# AD-672: Agent Concurrency Management

**Status:** Ready for builder
**Scope:** New file + integration edits (~250 lines new, ~50 lines edits)
**Depends on:** AD-573 (AgentWorkingMemory), AD-527 (EventType registry)

## Summary

Per-agent concurrency control for thought threads. Today, agents have no ceiling on concurrent `handle_intent` executions — the only throttle is the global LLM semaphore and the per-DAG `AttentionManager`. Under load (e.g., multiple Ward Room threads firing simultaneously), a single agent can spawn unbounded concurrent cognitive lifecycles, starving its own context window and competing for LLM slots.

This AD adds:
1. A configurable per-agent concurrency ceiling (role-tuned defaults).
2. A capacity-approaching event so the system can observe saturation.
3. Priority arbitration when threads compete for the same resource.
4. A bounded queue for excess intents (priority-ordered, not dropped).

## Architecture

```
IntentMessage arrives at handle_intent()
    │
    ▼
ConcurrencyManager.acquire(intent, priority)
    ├── slot available → acquire semaphore, register ThreadEntry, return
    ├── at capacity_warning_ratio → emit AGENT_CAPACITY_APPROACHING, then acquire
    └── at ceiling → enqueue as QueuedIntent (priority-sorted), await future
            │
            ▼  (on release of another slot)
         dequeue highest-priority, resolve its future, register ThreadEntry

release() called in finally block
    ├── remove ThreadEntry
    └── if queue non-empty → pop highest-priority, resolve future
```

---

## File Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/concurrency_manager.py` | **NEW** — ConcurrencyManager class |
| `src/probos/events.py` | Add `AGENT_CAPACITY_APPROACHING` to EventType |
| `src/probos/config.py` | Add `ConcurrencyConfig` + wire into `SystemConfig` |
| `src/probos/cognitive/cognitive_agent.py` | Wire ConcurrencyManager into `handle_intent` |
| `tests/test_ad672_concurrency_manager.py` | **NEW** — 16+ tests |

---

## Implementation

### Section 1: EventType Addition

**File:** `src/probos/events.py`

Add to the EventType enum, in the "Agent lifecycle" group (after `AGENT_STATE = "agent_state"` on line 77):

```python
    AGENT_CAPACITY_APPROACHING = "agent_capacity_approaching"  # AD-672: nearing thread ceiling
```

### Section 2: ConcurrencyConfig

**File:** `src/probos/config.py`

Add a new Pydantic config model. Place it after `TraitAdaptiveConfig` (line ~895) or adjacent to other cognitive configs:

```python
class ConcurrencyConfig(BaseModel):
    """AD-672: Per-agent concurrency management."""

    enabled: bool = True
    default_max_concurrent: int = 4
    queue_max_size: int = 10
    capacity_warning_ratio: float = 0.75

    # Role-tuned overrides — keys are pool group names (lowercase).
    # Agents in these groups get the specified ceiling instead of the default.
    role_overrides: dict[str, int] = {
        "bridge": 3,
        "operations": 6,
        "engineering": 5,
        "science": 4,
        "medical": 3,
        "security": 3,
    }
```

Wire into `SystemConfig`:

```python
    concurrency: ConcurrencyConfig = ConcurrencyConfig()  # AD-672
```

### Section 3: ConcurrencyManager

**File:** `src/probos/cognitive/concurrency_manager.py` (NEW)

```python
"""AD-672: Per-agent concurrency management.

Enforces a configurable ceiling on concurrent thought threads per agent,
with priority-ordered queuing for excess intents and capacity-approaching
event emission.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)
```

#### Data Classes

```python
@dataclass
class ThreadEntry:
    """Metadata for an active thought thread."""

    thread_id: str
    intent_type: str
    priority: int  # 0 (lowest) to 10 (highest)
    started_at: float = field(default_factory=time.monotonic)
    resource_key: str | None = None  # optional, for arbitration
```

```python
@dataclass
class QueuedIntent:
    """An intent waiting for a concurrency slot."""

    intent_type: str
    priority: int
    resource_key: str | None
    queued_at: float = field(default_factory=time.monotonic)
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())
    thread_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
```

Note: `QueuedIntent.future` uses `asyncio.get_running_loop()` (not `get_event_loop()`).

#### ConcurrencyManager Class

```python
class ConcurrencyManager:
    """Per-agent concurrency ceiling with priority queue and arbitration.

    One instance per agent. Thread-safe via asyncio.Lock (single-threaded
    event loop, but guards against reentrant await gaps).
    """

    def __init__(
        self,
        agent_id: str,
        max_concurrent: int = 4,
        queue_max_size: int = 10,
        capacity_warning_ratio: float = 0.75,
        emit_event_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._max_concurrent = max(1, max_concurrent)
        self._queue_max_size = max(0, queue_max_size)
        self._capacity_warning_ratio = capacity_warning_ratio
        self._emit_event_fn = emit_event_fn

        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._active: dict[str, ThreadEntry] = {}
        self._queue: list[QueuedIntent] = []
        self._lock = asyncio.Lock()
```

##### Properties

```python
    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @property
    def at_capacity(self) -> bool:
        return self.active_count >= self._max_concurrent
```

##### acquire()

```python
    async def acquire(
        self,
        intent_type: str,
        priority: int = 5,
        resource_key: str | None = None,
    ) -> str:
        """Acquire a concurrency slot or queue the intent.

        Returns the thread_id once a slot is acquired. If all slots are
        occupied, the intent is queued (priority-sorted, highest first)
        and the caller awaits until a slot opens.

        Raises ValueError if the queue is full (queue_max_size exceeded).
        """
        async with self._lock:
            # Check capacity warning threshold
            threshold = int(self._max_concurrent * self._capacity_warning_ratio)
            if self.active_count >= threshold and self.active_count < self._max_concurrent:
                self._emit_capacity_warning()

            # Try immediate acquisition
            if not self.at_capacity:
                thread_id = uuid.uuid4().hex[:12]
                entry = ThreadEntry(
                    thread_id=thread_id,
                    intent_type=intent_type,
                    priority=priority,
                    resource_key=resource_key,
                )
                self._active[thread_id] = entry
                # Consume a semaphore slot (non-blocking since we checked capacity)
                self._semaphore.acquire_nowait()
                return thread_id

            # At capacity — queue the intent
            if len(self._queue) >= self._queue_max_size:
                raise ValueError(
                    f"AD-672: Concurrency queue full for agent {self._agent_id} "
                    f"({len(self._queue)}/{self._queue_max_size})"
                )

            queued = QueuedIntent(
                intent_type=intent_type,
                priority=priority,
                resource_key=resource_key,
            )
            self._queue.append(queued)
            # Sort descending by priority (highest first), then ascending by queued_at (FIFO within same priority)
            self._queue.sort(key=lambda q: (-q.priority, q.queued_at))

            logger.info(
                "AD-672: Intent '%s' (priority=%d) queued for %s — %d/%d active, queue depth %d",
                intent_type, priority, self._agent_id,
                self.active_count, self._max_concurrent, len(self._queue),
            )

        # Wait outside the lock — the future is resolved when release() dequeues this item
        thread_id = await queued.future
        return thread_id
```

##### release()

```python
    async def release(self, thread_id: str) -> None:
        """Release a concurrency slot and promote the next queued intent."""
        async with self._lock:
            entry = self._active.pop(thread_id, None)
            if entry is None:
                logger.warning(
                    "AD-672: release() called for unknown thread_id %s on agent %s",
                    thread_id, self._agent_id,
                )
                return

            self._semaphore.release()

            # Promote next queued intent if any
            if self._queue:
                next_item = self._queue.pop(0)
                promoted_entry = ThreadEntry(
                    thread_id=next_item.thread_id,
                    intent_type=next_item.intent_type,
                    priority=next_item.priority,
                    resource_key=next_item.resource_key,
                )
                self._active[next_item.thread_id] = promoted_entry
                self._semaphore.acquire_nowait()

                logger.info(
                    "AD-672: Promoted queued intent '%s' (priority=%d) to active for %s",
                    next_item.intent_type, next_item.priority, self._agent_id,
                )

                # Resolve the future so the awaiting caller proceeds
                if not next_item.future.done():
                    next_item.future.set_result(next_item.thread_id)
```

##### arbitrate()

```python
    async def arbitrate(self, resource_key: str) -> str | None:
        """Priority arbitration: if multiple threads claim the same resource,
        the lower-priority thread yields.

        Returns the thread_id of the yielding thread (the one that should
        be cancelled), or None if no conflict exists.
        """
        async with self._lock:
            contenders = [
                e for e in self._active.values()
                if e.resource_key == resource_key
            ]
            if len(contenders) < 2:
                return None

            # Sort ascending by priority — lowest yields
            contenders.sort(key=lambda e: (e.priority, e.started_at))
            yielding = contenders[0]

            logger.info(
                "AD-672: Arbitration on resource '%s' — thread %s (priority=%d) yields to %s (priority=%d)",
                resource_key, yielding.thread_id, yielding.priority,
                contenders[-1].thread_id, contenders[-1].priority,
            )
            return yielding.thread_id
```

##### Context Manager (slot)

```python
    @asynccontextmanager
    async def slot(
        self,
        intent_type: str,
        priority: int = 5,
        resource_key: str | None = None,
    ):
        """Async context manager for clean acquire/release lifecycle.

        Usage:
            async with concurrency_manager.slot("ward_room_notification", 5):
                await self._run_cognitive_lifecycle(intent)
        """
        thread_id = await self.acquire(intent_type, priority, resource_key)
        try:
            yield thread_id
        finally:
            await self.release(thread_id)
```

##### Event Emission

```python
    def _emit_capacity_warning(self) -> None:
        """Emit AGENT_CAPACITY_APPROACHING when nearing the ceiling."""
        if self._emit_event_fn is None:
            return
        try:
            self._emit_event_fn(EventType.AGENT_CAPACITY_APPROACHING, {
                "agent_id": self._agent_id,
                "active_count": self.active_count,
                "max_concurrent": self._max_concurrent,
                "queue_depth": self.queue_depth,
            })
        except Exception:
            logger.debug(
                "AD-672: Failed to emit AGENT_CAPACITY_APPROACHING for %s",
                self._agent_id,
                exc_info=True,
            )
```

##### Diagnostic snapshot

```python
    def snapshot(self) -> dict[str, Any]:
        """Return diagnostic snapshot for /api endpoints or VitalsMonitor."""
        return {
            "agent_id": self._agent_id,
            "max_concurrent": self._max_concurrent,
            "active_count": self.active_count,
            "queue_depth": self.queue_depth,
            "active_threads": [
                {
                    "thread_id": e.thread_id,
                    "intent_type": e.intent_type,
                    "priority": e.priority,
                    "age_s": round(time.monotonic() - e.started_at, 2),
                }
                for e in self._active.values()
            ],
        }
```

### Section 4: CognitiveAgent Integration

**File:** `src/probos/cognitive/cognitive_agent.py`

#### 4a: Import

Add to the imports at the top of the file (after the existing `from probos.events import EventType` on line 15):

```python
from probos.cognitive.concurrency_manager import ConcurrencyManager
```

#### 4b: Instance variable

In `__init__`, after the `self._qualification_standing_ttl` block (around line 111), add:

```python
        # AD-672: Per-agent concurrency management
        self._concurrency_manager: ConcurrencyManager | None = None
```

#### 4c: Public setter

After `set_sub_task_executor` (line 129), add:

```python
    def set_concurrency_manager(self, manager: ConcurrencyManager) -> None:
        """AD-672: Wire per-agent concurrency manager."""
        self._concurrency_manager = manager
```

#### 4d: Wrap handle_intent

In `handle_intent` (line 2665), wrap the existing `try/finally` block (lines 2766-2777) with the concurrency manager slot. The existing block is:

```python
        try:
            return await self._run_cognitive_lifecycle(
                intent, _cognitive_skill_instructions, _skill_entries,
            )
        finally:
            ...
```

Replace with:

```python
        # AD-672: Concurrency-managed cognitive lifecycle
        _cm = self._concurrency_manager
        if _cm:
            _priority = _classify_concurrency_priority(intent)
            try:
                async with _cm.slot(intent.intent, _priority):
                    return await self._run_cognitive_lifecycle(
                        intent, _cognitive_skill_instructions, _skill_entries,
                    )
            except ValueError:
                # Queue full — log-and-degrade, return a NO_RESPONSE
                logger.warning(
                    "AD-672: Concurrency queue full for %s on intent '%s', shedding",
                    getattr(self, 'callsign', '') or self.agent_type,
                    intent.intent,
                )
                return IntentResult(
                    intent_id=intent.id,
                    agent_id=self.id,
                    success=True,
                    result="[NO_RESPONSE]",
                    confidence=self.confidence,
                )
            finally:
                if _bf239_thread_id:
                    _wm = getattr(self, '_working_memory', None)
                    if _wm:
                        _wm.remove_engagement(f"ward_room:{_bf239_thread_id}")
        else:
            # No concurrency manager — original behavior
            try:
                return await self._run_cognitive_lifecycle(
                    intent, _cognitive_skill_instructions, _skill_entries,
                )
            finally:
                if _bf239_thread_id:
                    _wm = getattr(self, '_working_memory', None)
                    if _wm:
                        _wm.remove_engagement(f"ward_room:{_bf239_thread_id}")
```

**Important:** This replaces lines 2766-2777 (the existing `try/finally` block). Preserve the BF-239 engagement cleanup in both branches. Read the existing code at lines 2766-2781 to get the exact cleanup logic before editing.

#### 4e: Priority classifier helper

Add as a module-level function (before the class, after `derive_communication_context`):

```python
def _classify_concurrency_priority(intent: IntentMessage) -> int:
    """AD-672: Map intent to concurrency priority (0-10 scale).

    Higher = more important. Aligns with existing Priority enum but on
    a finer-grained numeric scale for queue ordering.
    """
    # Captain / @mention / DM → highest
    is_captain = intent.params.get("is_captain", False)
    was_mentioned = intent.params.get("was_mentioned", False)
    is_dm = intent.params.get("is_dm_channel", False) or intent.intent == "direct_message"

    if is_captain or was_mentioned:
        return 10
    if is_dm:
        return 8
    if intent.intent == "ward_room_notification":
        return 5
    if intent.intent == "proactive_think":
        return 2
    return 5  # default
```

### Section 5: Startup Wiring

**File:** `src/probos/startup/cognitive_services.py`

This section wires ConcurrencyManager to each CognitiveAgent during startup. However, the manager must be created per-agent, and agents are already registered at this point.

Add a utility function at the end of the module (or inline where agents are being configured). The wiring pattern follows `set_sub_task_executor` and `set_strategy_advisor` — iterate registered agents and call the setter.

Find where agents get their sub-task executor wired (search for `set_sub_task_executor` in `cognitive_services.py` or the calling module) and add adjacent wiring:

```python
from probos.cognitive.concurrency_manager import ConcurrencyManager
```

Then, in the agent wiring loop, add:

```python
        # AD-672: Per-agent concurrency management
        if config.concurrency.enabled:
            _role = getattr(agent, 'pool_group', '') or ''
            _max = config.concurrency.role_overrides.get(
                _role.lower(), config.concurrency.default_max_concurrent
            )
            _cm = ConcurrencyManager(
                agent_id=agent.id,
                max_concurrent=_max,
                queue_max_size=config.concurrency.queue_max_size,
                capacity_warning_ratio=config.concurrency.capacity_warning_ratio,
                emit_event_fn=emit_event_fn,
            )
            if hasattr(agent, 'set_concurrency_manager'):
                agent.set_concurrency_manager(_cm)
```

**Builder:** Search `cognitive_services.py` and adjacent startup modules for `set_sub_task_executor` to find the exact wiring location. If the wiring loop is in a different startup file (e.g., `finalize.py`), wire there instead. The pattern is: iterate `registry.all_agents()`, check `isinstance(agent, CognitiveAgent)`, call the setter. Match the existing pattern exactly.

If the agent wiring loop is not in `cognitive_services.py`, search for `set_sub_task_executor` across `src/probos/startup/` to find it.

---

## Tests

**File:** `tests/test_ad672_concurrency_manager.py` (NEW)

All tests use `pytest` + `pytest-asyncio`. Use `_Fake*` stubs, not complex mock chains. Each test is isolated with its own fixtures.

### Test List

| # | Test Name | What It Verifies |
|---|-----------|------------------|
| 1 | `test_acquire_returns_thread_id` | `acquire()` returns a non-empty string thread_id |
| 2 | `test_acquire_within_ceiling` | Can acquire up to `max_concurrent` slots without blocking |
| 3 | `test_release_frees_slot` | After `release()`, a new `acquire()` succeeds immediately |
| 4 | `test_queue_when_at_capacity` | Intent is queued (not dropped) when all slots occupied; dequeued on release |
| 5 | `test_queue_priority_ordering` | Higher-priority queued intents are dequeued before lower-priority ones |
| 6 | `test_queue_fifo_within_same_priority` | Same-priority intents dequeue in FIFO order |
| 7 | `test_queue_full_raises_valueerror` | `acquire()` raises `ValueError` when `queue_max_size` exceeded |
| 8 | `test_capacity_warning_event_emitted` | `AGENT_CAPACITY_APPROACHING` event fires when crossing `capacity_warning_ratio` threshold |
| 9 | `test_capacity_warning_not_emitted_below_threshold` | No event emitted when below ratio |
| 10 | `test_arbitrate_returns_lower_priority_thread` | `arbitrate()` returns the thread_id of the lower-priority contender |
| 11 | `test_arbitrate_no_conflict` | `arbitrate()` returns None when 0-1 threads on resource |
| 12 | `test_slot_context_manager` | `async with slot(...)` acquires on enter, releases on exit |
| 13 | `test_slot_releases_on_exception` | Slot is released even if the body raises an exception |
| 14 | `test_snapshot_diagnostic` | `snapshot()` returns correct structure with active thread info |
| 15 | `test_properties` | `active_count`, `queue_depth`, `max_concurrent`, `at_capacity` return correct values |
| 16 | `test_release_unknown_thread_id` | `release()` with unknown thread_id logs warning, does not crash |
| 17 | `test_classify_concurrency_priority` | Module-level `_classify_concurrency_priority()` maps captain/DM/ward_room/proactive correctly |
| 18 | `test_config_defaults` | `ConcurrencyConfig` has correct defaults and role overrides |

### Test Pattern

```python
import asyncio
import pytest
from probos.cognitive.concurrency_manager import ConcurrencyManager, ThreadEntry, QueuedIntent
from probos.events import EventType


class _FakeEventCollector:
    """Collects emitted events for assertion."""

    def __init__(self):
        self.events: list[tuple] = []

    def __call__(self, event_type, data):
        self.events.append((event_type, data))


@pytest.fixture
def manager():
    return ConcurrencyManager(
        agent_id="test-agent",
        max_concurrent=2,
        queue_max_size=3,
        capacity_warning_ratio=0.5,
    )


@pytest.fixture
def manager_with_events():
    collector = _FakeEventCollector()
    mgr = ConcurrencyManager(
        agent_id="test-agent",
        max_concurrent=2,
        queue_max_size=3,
        capacity_warning_ratio=0.5,
        emit_event_fn=collector,
    )
    return mgr, collector
```

Run after each section:
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad672_concurrency_manager.py -v
```

---

## Targeted Test Commands

After Section 1-2 (EventType + Config):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad672_concurrency_manager.py::test_config_defaults -v
```

After Section 3 (ConcurrencyManager):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad672_concurrency_manager.py -v
```

After Section 4 (CognitiveAgent integration):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad672_concurrency_manager.py -v
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_cognitive_agent.py -v -x
```

After Section 5 (Startup wiring):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad672_concurrency_manager.py -v
```

Full suite (after all sections complete):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

- **PROGRESS.md:** Add line `AD-672 Agent Concurrency Management — CLOSED`
- **docs/development/roadmap.md:** Update the AD-672 row status to `Complete`
- **DECISIONS.md:** Add entry:
  ```
  AD-672: Per-agent concurrency ceiling with priority queuing. ConcurrencyManager enforces
  max_concurrent threads per agent (role-tuned: bridge=3, operations=6, default=4). Excess
  intents queue with priority ordering rather than spawning unbounded threads. Queue-full
  degrades to [NO_RESPONSE] — log-and-degrade, not crash.
  ```

---

## Scope Boundaries

**DO:**
- Create `concurrency_manager.py` with the classes and methods described above.
- Add the event type, config model, and SystemConfig field.
- Wire into `cognitive_agent.py` handle_intent.
- Wire in startup.
- Write all 18 tests.

**DO NOT:**
- Modify AttentionManager, LLM semaphore, or SubTaskChain concurrency.
- Add API endpoints for concurrency (future AD).
- Add HXI/dashboard visualization (future AD).
- Modify any existing tests.
- Add docstrings/comments to code you did not change.
