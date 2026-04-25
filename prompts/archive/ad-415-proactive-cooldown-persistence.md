# AD-415: Proactive Cooldown Persistence

## Context

When the Captain adjusts an agent's proactive think interval via the HXI Health tab slider (60s–1800s), the value is stored in-memory on `ProactiveCognitiveLoop._agent_cooldowns` (a `dict[str, float]`). After a restart, all custom cooldowns reset to the global default (300s from config). The Captain's tuning is lost.

**Design choice:** Persist to KnowledgeStore. On `probos reset`, KnowledgeStore is wiped — cooldowns reset with it. This is correct: if you reset the crew's memory, resetting their duty tempo is consistent.

**Architecture:** KnowledgeStore uses typed store/load pairs (e.g., `store_trust_snapshot`/`load_trust_snapshot`). Follow the same pattern for cooldowns. The store writes JSON to a subdirectory under the knowledge repo path.

## Changes

### Step 1: KnowledgeStore — Add cooldown persistence methods

**File:** `src/probos/knowledge/store.py`

Add `"proactive"` to the `_SUBDIRS` tuple (line 28):

```python
_SUBDIRS = ("episodes", "agents", "skills", "trust", "routing", "workflows", "qa", "proactive")
```

Add two new methods to the `KnowledgeStore` class. Place them near the other store/load pairs (e.g., after `load_routing_weights` / before `store_workflows`, or at the end of the store/load section):

```python
async def store_cooldowns(self, cooldowns: dict[str, float]) -> None:
    """Persist per-agent proactive cooldown overrides."""
    if not cooldowns:
        return
    path = self._repo_path / "proactive" / "cooldowns.json"
    await self._write_json(path, cooldowns)

async def load_cooldowns(self) -> dict[str, float] | None:
    """Load per-agent proactive cooldown overrides."""
    path = self._repo_path / "proactive" / "cooldowns.json"
    data = await self._read_json(path)
    if isinstance(data, dict):
        return {k: float(v) for k, v in data.items()}
    return None
```

### Step 2: ProactiveCognitiveLoop — Write-through on set + restore on start

**File:** `src/probos/proactive.py`

**2a. Add a `_knowledge_store` reference.**

In `__init__()` (after line 43, `self._agent_cooldowns`), add:

```python
self._knowledge_store: Any = None  # AD-415: Set by runtime for persistence
```

**2b. Modify `set_agent_cooldown()` (lines 74-77) to write-through:**

Replace the current method:

```python
def set_agent_cooldown(self, agent_id: str, cooldown: float) -> None:
    """Set per-agent proactive cooldown override. Clamp to [60, 1800]."""
    cooldown = max(60.0, min(1800.0, cooldown))
    self._agent_cooldowns[agent_id] = cooldown
    # AD-415: Write-through to KnowledgeStore
    self._persist_cooldowns()
```

**2c. Add `_persist_cooldowns()` helper** (near `set_agent_cooldown`):

```python
def _persist_cooldowns(self) -> None:
    """AD-415: Fire-and-forget persistence of cooldown overrides."""
    if not self._knowledge_store:
        return
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(self._knowledge_store.store_cooldowns(self._agent_cooldowns.copy()))
    except RuntimeError:
        pass  # No event loop — skip persistence (e.g., during shutdown)
```

**2d. Add `restore_cooldowns()` method** (near `_persist_cooldowns`):

```python
async def restore_cooldowns(self) -> None:
    """AD-415: Restore per-agent cooldowns from KnowledgeStore on boot."""
    if not self._knowledge_store:
        return
    try:
        saved = await self._knowledge_store.load_cooldowns()
        if saved:
            for agent_id, cooldown in saved.items():
                # Apply same clamping as set_agent_cooldown
                self._agent_cooldowns[agent_id] = max(60.0, min(1800.0, cooldown))
    except Exception:
        pass  # Non-critical — boot proceeds with defaults
```

### Step 3: Runtime — Wire KnowledgeStore into ProactiveCognitiveLoop

**File:** `src/probos/runtime.py`

**3a. Pass knowledge_store when initializing proactive loop.**

Find the proactive loop initialization block (lines 1273-1288). After `self.proactive_loop.set_config(...)` and before `await self.proactive_loop.start()`, add:

```python
# AD-415: Wire knowledge store for cooldown persistence
if self._knowledge_store:
    self.proactive_loop._knowledge_store = self._knowledge_store
    await self.proactive_loop.restore_cooldowns()
```

**3b. Persist cooldowns during shutdown.**

Find the shutdown knowledge persistence block (around lines 1390-1412, where trust/routing/workflows/manifest are stored). Add cooldown persistence in the same block:

```python
# AD-415: Persist proactive cooldown overrides
if self.proactive_loop and self.proactive_loop._agent_cooldowns:
    await self._knowledge_store.store_cooldowns(self.proactive_loop._agent_cooldowns.copy())
```

Place this BEFORE the proactive loop is stopped (which happens at lines 1326-1328). The shutdown sequence should persist cooldowns while the proactive loop is still alive, then stop the loop after.

**Important:** Check the current shutdown order. If the proactive loop is stopped (lines 1326-1328) BEFORE the knowledge store flush (lines 1390-1412), you'll need to move the cooldown persist earlier — or add it just before `await self.proactive_loop.stop()`.

### Step 4: API — Write-through already handled

**File:** `src/probos/api.py`

No changes needed. The API endpoint (line 1164) already calls `runtime.proactive_loop.set_agent_cooldown(agent_id, cooldown)`, which now write-throughs via Step 2b.

## Tests

**File:** `tests/test_proactive.py` — Add to existing test file.

### Test 1: set_agent_cooldown persists to KnowledgeStore
```
Create a ProactiveCognitiveLoop with a mock _knowledge_store.
Call set_agent_cooldown("agent-1", 600).
Assert _knowledge_store.store_cooldowns() was called with {"agent-1": 600.0}.
```

### Test 2: restore_cooldowns loads from KnowledgeStore
```
Create a ProactiveCognitiveLoop with a mock _knowledge_store.
Mock load_cooldowns() to return {"agent-1": 450.0, "agent-2": 120.0}.
Call await restore_cooldowns().
Assert get_agent_cooldown("agent-1") == 450.0.
Assert get_agent_cooldown("agent-2") == 120.0.
```

### Test 3: restore_cooldowns clamps values
```
Mock load_cooldowns() to return {"agent-1": 30.0, "agent-2": 5000.0}.
Call await restore_cooldowns().
Assert get_agent_cooldown("agent-1") == 60.0 (clamped to min).
Assert get_agent_cooldown("agent-2") == 1800.0 (clamped to max).
```

### Test 4: restore_cooldowns with no KnowledgeStore doesn't crash
```
Create a ProactiveCognitiveLoop with _knowledge_store = None.
Call await restore_cooldowns().
Assert no exception, _agent_cooldowns remains empty.
```

### Test 5: restore_cooldowns with load failure doesn't crash
```
Mock load_cooldowns() to raise an exception.
Call await restore_cooldowns().
Assert no exception, _agent_cooldowns remains empty.
```

### Test 6: _persist_cooldowns with no KnowledgeStore is a no-op
```
Create a ProactiveCognitiveLoop with _knowledge_store = None.
Call set_agent_cooldown("agent-1", 600).
Assert _agent_cooldowns["agent-1"] == 600.0 (still works in-memory).
```

### Test 7: store_cooldowns writes JSON file
```
Create a real KnowledgeStore (temp directory).
Call await store_cooldowns({"agent-1": 600.0}).
Assert the file proactive/cooldowns.json exists with correct content.
```

### Test 8: load_cooldowns reads JSON file
```
Create a real KnowledgeStore with an existing proactive/cooldowns.json.
Call await load_cooldowns().
Assert returned dict matches stored data.
```

### Test 9: load_cooldowns returns None when no file exists
```
Create a real KnowledgeStore (empty temp directory).
Call await load_cooldowns().
Assert returns None.
```

### Test 10: store_cooldowns skips empty dict
```
Create a real KnowledgeStore (temp directory).
Call await store_cooldowns({}).
Assert no file was written.
```

## Constraints

- All persistence operations are non-critical — wrapped in try/except, never block the proactive loop or shutdown.
- Cooldown values are clamped to [60, 1800] on both set and restore — prevents stale invalid data.
- `_persist_cooldowns()` uses fire-and-forget `create_task()` — `set_agent_cooldown()` stays synchronous (consistent with current API contract).
- KnowledgeStore uses its existing `_write_json`/`_read_json` helpers — no new I/O patterns.
- On `probos reset`, KnowledgeStore is wiped → cooldowns.json is deleted → restart uses defaults. This is the intended behavior.
- `_last_proactive` timestamps are NOT persisted — they're monotonic-clock-relative and meaningless across restarts. On restart, all agents are immediately eligible for their first think.
- The `proactive` subdirectory is added to `_SUBDIRS` so it's auto-created on initialize.

## Run

```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_proactive.py -x -v -k "cooldown" 2>&1 | tail -30
```

If broader validation needed:
```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_proactive.py tests/test_knowledge_store.py -x -v 2>&1 | tail -40
```
