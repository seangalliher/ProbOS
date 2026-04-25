# BF-076: AD-514 Quality Fixes — Type Annotations, Logging, Bug Fixes, Test Gaps

## Context

AD-514 added public APIs on 17 target objects and 7 protocols in `protocols.py`. An engineering principles audit found:

1. **Runtime bug** in `ward_room.py:post_system_message` — wrong column names, will crash at runtime
2. **Type annotations universally weak** — bare `dict`, `list`, `tuple`, `object` throughout protocols and public APIs
3. **No logging on any mutation method** — all new state-changing methods are silent
4. **Duplicate methods** — `trust.py:remove_agent` duplicates existing `remove`; `routing.py` getters duplicate existing methods
5. **Test gaps** — missing boundary/edge tests, one test combines two behaviors
6. **`routing.py` setter desync risk** — `set_weight`/`set_compat_weight` can silently desync internal dicts

This BF targets zero behavior changes where possible. Fixes are type tightening, logging additions, bug fixes, and test additions.

---

## Part A: Fix `ward_room.py:post_system_message` Bug (CRITICAL)

**File:** `src/probos/ward_room.py`

The `post_system_message` method (line 1518) has three bugs:

### Bug 1: Wrong column name in posts INSERT (line 1542)
The INSERT uses column `content` but the schema (line 144) defines the column as `body`.

**Fix:** Change `content` to `body` in the INSERT statement:
```python
# BEFORE (line 1542)
"INSERT INTO posts (id, thread_id, author_id, content, created_at) VALUES (?, ?, ?, ?, ?)",

# AFTER
"INSERT INTO posts (id, thread_id, author_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
```

### Bug 2: Missing required `body` column in threads INSERT (line 1538)
The `threads` table has `body TEXT NOT NULL` (line 125) with no DEFAULT. The INSERT omits it.

**Fix:** Add `body` column to the threads INSERT. Use the full `content` string as the body (the `title` already uses `content[:80]`):
```python
# BEFORE (line 1538)
"INSERT INTO threads (id, channel_id, title, author_id, created_at, last_activity) VALUES (?, ?, ?, ?, ?, ?)",
(thread_id, channel_id, content[:80], author, now, now),

# AFTER
"INSERT INTO threads (id, channel_id, title, body, author_id, created_at, last_activity) VALUES (?, ?, ?, ?, ?, ?, ?)",
(thread_id, channel_id, content[:80], content, author, now, now),
```

### Bug 3: Opens a second DB connection (line 1526)
Uses `aiosqlite.connect(self.db_path)` instead of the existing `self._db`. This bypasses the service's connection and can cause write contention.

**Fix:** Use `self._db` instead, with a guard for the started state:
```python
# BEFORE
async def post_system_message(self, channel_name: str, content: str, author: str = "ship_computer") -> None:
    if not self.db_path:
        return
    async with aiosqlite.connect(self.db_path) as db:
        cursor = await db.execute(...)
        ...
        await db.commit()

# AFTER
async def post_system_message(self, channel_name: str, content: str, author: str = "ship_computer") -> None:
    if self._db is None:
        return
    cursor = await self._db.execute(
        "SELECT id FROM channels WHERE name = ?", (channel_name,)
    )
    row = await cursor.fetchone()
    if not row:
        return
    channel_id = row[0]
    thread_id = str(uuid.uuid4())
    post_id = str(uuid.uuid4())
    now = time.time()
    await self._db.execute(
        "INSERT INTO threads (id, channel_id, title, body, author_id, created_at, last_activity) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (thread_id, channel_id, content[:80], content, author, now, now),
    )
    await self._db.execute(
        "INSERT INTO posts (id, thread_id, author_id, body, created_at) VALUES (?, ?, ?, ?, ?)",
        (post_id, thread_id, author, content, now),
    )
    await self._db.commit()
```

Also type the `set_ontology` parameter (line 1514):
```python
# BEFORE
def set_ontology(self, ontology) -> None:

# AFTER
def set_ontology(self, ontology: Any) -> None:
```
Add `from typing import Any` if not already imported.

---

## Part B: Tighten Type Annotations

### B1: `src/probos/protocols.py`

Fix every bare type. Use `Any` where the actual type varies or is complex. Use concrete types where known. Add `from typing import Any, Callable` at the top if not present.

| Line | Current | Fix To |
|------|---------|--------|
| 20 | `-> list:` | `-> list[Any]:` |
| 30 | `-> object:` | `-> Any:` |
| 39 | `data: dict \| None` | `data: dict[str, Any] \| None` |
| 48 | `**kwargs) -> dict:` | `**kwargs: Any) -> dict[str, Any]:` |
| 49 | `-> dict:` | `-> dict[str, Any]:` |
| 50 | `-> dict \| None:` | `-> dict[str, Any] \| None:` |
| 51 | `-> list:` | `-> list[dict[str, Any]]:` |
| 53 | `ontology) -> None:` | `ontology: Any) -> None:` |
| 60 | `record, source_code` | `record: Any, source_code: str` |
| 61 | `episode)` | `episode: Any)` |
| 62 | `descriptor: dict` | `descriptor: dict[str, Any]` |
| 63 | `data: dict` | `data: dict[str, Any]` |
| 64 | `data: dict` | `data: dict[str, Any]` |
| 72 | `-> dict:` | `-> dict[tuple[str, str, str], float]:` |
| 73 | `key: tuple` | `key: tuple[str, str, str]` |
| 81 | `data: dict` | `data: dict[str, Any]` |
| 82 | `fn)` | `fn: Callable[..., Any])` |
| 83 | `fn)` | `fn: Callable[..., Any])` |

### B2: `src/probos/substrate/spawner.py`

Use `type[BaseAgent]` to match the internal `_templates` typing (line 23).

| Line | Current | Fix To |
|------|---------|--------|
| 79 | `-> type \| None:` | `-> type[BaseAgent] \| None:` |
| 83 | `-> dict[str, type]:` | `-> dict[str, type[BaseAgent]]:` |
| 87 | `-> Iterator[tuple[str, type]]:` | `-> Iterator[tuple[str, type[BaseAgent]]]:` |
| 91 | `cls: type` | `cls: type[BaseAgent]` |

### B3: `src/probos/substrate/pool.py`

Use `AgentID` (already imported at line 11) to match `_agent_ids: list[AgentID]` (line 45).

| Line | Current | Fix To |
|------|---------|--------|
| 253 | `-> list[str]:` | `-> list[AgentID]:` |
| 257 | `agent_id: str` | `agent_id: AgentID` |
| 261 | `agent_id: str` | `agent_id: AgentID` |

### B4: `src/probos/mesh/routing.py`

Use the existing `_FullKey` (line 36) and `_WeightKey` (line 35) type aliases.

| Line | Current | Fix To |
|------|---------|--------|
| 271 | `-> dict:` | `-> dict[_FullKey, float]:` |
| 275 | `key: tuple` | `key: _FullKey` |
| 279 | `agent_id: str` | `agent_id: AgentID` |
| 285 | `-> dict:` | `-> dict[_WeightKey, float]:` |
| 289 | `key: tuple` | `key: _WeightKey` |
| 293 | `agent_id: str` | `agent_id: AgentID` |

Ensure `AgentID` is imported from `probos.types` (check existing imports).

---

## Part C: Add Structured Logging on Mutations

Add `logger.info()` or `logger.debug()` calls to all mutation methods. Follow the standard: include **what** happened, **key context**, and **outcome**.

### C1: `src/probos/substrate/spawner.py`
```python
def replace_template(self, agent_type: str, cls: type[BaseAgent]) -> None:
    """Hot-swap an agent class template."""
    logger.info("Template replaced: %s -> %s", agent_type, cls.__name__)
    self._templates[agent_type] = cls
```
Ensure `logger = logging.getLogger(__name__)` exists at module top.

### C2: `src/probos/substrate/pool.py`
```python
def remove_agent_by_id(self, agent_id: AgentID) -> None:
    """Remove an agent ID from the pool's tracking list."""
    if agent_id in self._agent_ids:
        self._agent_ids.remove(agent_id)
        logger.debug("Agent %s removed from pool %s tracking", agent_id, self.name)
    else:
        logger.debug("Agent %s not found in pool %s tracking; no-op", agent_id, self.name)
```
This also fixes the potential `ValueError` from calling `list.remove()` on a non-existent ID.

### C3: `src/probos/mesh/routing.py`
```python
def set_weight(self, key: _FullKey, value: float) -> None:
    """Set a specific Hebbian weight."""
    self._weights[key] = value
    logger.debug("Hebbian weight set: %s = %.4f", key, value)

def remove_weights_for_agent(self, agent_id: AgentID) -> None:
    """Remove all Hebbian weight entries involving an agent."""
    before = len(self._weights)
    self._weights = {k: v for k, v in self._weights.items() if agent_id not in k[:2]}
    removed = before - len(self._weights)
    if removed:
        logger.info("Removed %d Hebbian weights for agent %s", removed, agent_id)

def set_compat_weight(self, key: _WeightKey, value: float) -> None:
    """Set a specific compatibility weight."""
    self._compat_weights[key] = value
    logger.debug("Compat weight set: %s = %.4f", key, value)

def remove_compat_weights_for_agent(self, agent_id: AgentID) -> None:
    """Remove all compatibility weight entries involving an agent."""
    before = len(self._compat_weights)
    self._compat_weights = {k: v for k, v in self._compat_weights.items() if agent_id not in k}
    removed = before - len(self._compat_weights)
    if removed:
        logger.info("Removed %d compat weights for agent %s", removed, agent_id)
```

### C4: `src/probos/consensus/trust.py`
```python
def remove_agent(self, agent_id: AgentID) -> None:
    """Remove an agent's trust record."""
    if agent_id in self._records:
        del self._records[agent_id]
        logger.info("Trust record removed for agent %s", agent_id)
```

### C5: `src/probos/ward_room.py`
```python
# In post_system_message, after the db.commit():
logger.info("System message posted to channel %s: %s", channel_name, content[:80])
```

---

## Part D: Resolve Duplicate Methods

### D1: `src/probos/consensus/trust.py` — `remove` vs `remove_agent`

Both do the same thing (line 228 `remove` and line 232 `remove_agent`). Make `remove_agent` the canonical public API and delegate `remove` to it:

```python
def remove_agent(self, agent_id: AgentID) -> None:
    """Remove an agent's trust record. Public API for AD-514."""
    if agent_id in self._records:
        del self._records[agent_id]
        logger.info("Trust record removed for agent %s", agent_id)

def remove(self, agent_id: AgentID) -> None:
    """Remove an agent's trust record. Delegates to remove_agent."""
    self.remove_agent(agent_id)
```

### D2: `src/probos/mesh/routing.py` — getter duplication

`get_all_weights()` (line 271) duplicates `all_weights_typed()` (line ~229). `get_all_compat_weights()` (line 285) duplicates `all_weights()` (line ~225).

Make the new API methods delegate to the existing implementations (with copies):

```python
def get_all_weights(self) -> dict[_FullKey, float]:
    """Public API: get all Hebbian weights (copy)."""
    return dict(self.all_weights_typed())

def get_all_compat_weights(self) -> dict[_WeightKey, float]:
    """Public API: get all compatibility weights (copy)."""
    return dict(self.all_weights())
```

---

## Part E: Add Missing Boundary Tests

**File:** `tests/test_public_apis.py`

### E1: Split `test_contains_agent` (line 160) into two tests:
```python
def test_contains_agent_present(self):
    pool = self._make_pool()
    pool._agent_ids = ["agent_1"]
    assert pool.contains_agent("agent_1") is True

def test_contains_agent_absent(self):
    pool = self._make_pool()
    pool._agent_ids = ["agent_1"]
    assert pool.contains_agent("agent_2") is False
```

### E2: Add `test_remove_agent_by_id_missing` — verify no-op on non-existent ID:
```python
def test_remove_agent_by_id_missing(self):
    pool = self._make_pool()
    pool._agent_ids = ["agent_1"]
    pool.remove_agent_by_id("agent_99")  # should not raise
    assert pool.get_agent_ids() == ["agent_1"]
```

### E3: Add empty-state tests:
```python
# In TestAgentSpawnerPublicAPI
def test_list_templates_empty(self):
    spawner = self._make_spawner()
    spawner._templates = {}
    assert spawner.list_templates() == {}

def test_iter_templates_empty(self):
    spawner = self._make_spawner()
    spawner._templates = {}
    assert list(spawner.iter_templates()) == []

# In TestHebbianRouterPublicAPI
def test_get_all_weights_empty(self):
    router = self._make_router()
    assert router.get_all_weights() == {}

def test_get_all_compat_weights_empty(self):
    router = self._make_router()
    assert router.get_all_compat_weights() == {}

# In TestProactiveLoopPublicAPI
def test_get_cooldowns_empty(self):
    loop = self._make_loop()
    assert loop.get_cooldowns() == {}
```

### E4: Add `test_is_started_true` for WardRoomService:
```python
def test_is_started_true(self):
    svc = self._make_ward_room()
    svc._db = MagicMock()  # simulate active connection
    assert svc.is_started is True
```

### E5: Add `test_remove_weights_for_absent_agent` — no-op edge:
```python
def test_remove_weights_for_absent_agent(self):
    router = self._make_router()
    router._weights = {("a", "b", "intent"): 1.0}
    router.remove_weights_for_agent("z")  # not in any key
    assert len(router.get_all_weights()) == 1
```

---

## Scope Constraints

- **Do NOT modify `runtime.py`** — that's AD-515's job
- **Do NOT change method behavior** beyond the `post_system_message` bug fixes and the `remove_agent_by_id` safety guard
- **Do NOT add new methods** — only fix existing AD-514 methods
- **Do NOT rename methods** — keep `remove_agent_by_id`, `get_all_weights`, etc. as-is
- **Do NOT split protocols** (e.g., WardRoomProtocol) — that's a design decision for a future AD

## Acceptance Criteria

- [ ] `ward_room.py:post_system_message` uses correct column names (`body` not `content`) and uses `self._db` not a new connection
- [ ] All protocols in `protocols.py` have fully typed parameters and return types (no bare `dict`, `list`, `tuple`, `object`)
- [ ] All public API methods in spawner, pool, routing, trust, ward_room have types matching their internal state types
- [ ] All mutation methods log with structured context
- [ ] `trust.py:remove` delegates to `remove_agent`
- [ ] `routing.py:get_all_weights` delegates to `all_weights_typed()`
- [ ] `routing.py:get_all_compat_weights` delegates to `all_weights()`
- [ ] `pool.py:remove_agent_by_id` handles missing agent gracefully (no `ValueError`)
- [ ] ~10 new tests added for boundary/edge cases
- [ ] Existing test suite passes with zero regressions
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`
