# AD-514: Service Protocols + Public APIs

## Context

ProbOS `runtime.py` accesses private members (`obj._attr`) on **15 different target objects** across **47 call sites**. This violates Open/Closed, Law of Demeter, and prevents decomposition because the runtime's coupling is invisible to the type system.

This AD adds public methods/properties to replace every private access, and defines `typing.Protocol` interfaces for the major service boundaries. **Zero behavior changes. Pure additions.** Existing private-access call sites in runtime.py are NOT changed in this AD — that happens in AD-515.

## Part A: Public APIs on Target Objects

For each target object, add the listed public methods. Implementations must be trivial wrappers around the existing private state — no logic changes.

---

### 1. `src/probos/substrate/spawner.py` — AgentSpawner (7 patches)

Current private access: `self.spawner._templates` (read dict, iterate items, get by key)

Add:

```python
def get_template(self, agent_type: str) -> type | None:
    """Return the registered agent class for the given type, or None."""
    return self._templates.get(agent_type)

def list_templates(self) -> dict[str, type]:
    """Return a copy of all registered templates {type_name: class}."""
    return dict(self._templates)

def iter_templates(self) -> Iterator[tuple[str, type]]:
    """Iterate over (type_name, class) pairs."""
    return iter(self._templates.items())
```

**Used at runtime.py lines:** 1197-1198 (read template class), 3206 (write template for hot-swap), 4261 (federation self-model), 4629/4642/4655 (intent collection), 4706 (tier info)

Also add for hot-swap support:

```python
def replace_template(self, agent_type: str, cls: type) -> None:
    """Replace the class for an existing agent type (self-mod hot-swap)."""
    if agent_type not in self._templates:
        raise KeyError(f"Unknown agent type: {agent_type}")
    self._templates[agent_type] = cls
```

---

### 2. `src/probos/mesh/routing.py` — HebbianRouter (6 patches)

Current private access: `self.hebbian_router._weights` and `._compat_weights` (read, write, delete)

Add:

```python
def get_all_weights(self) -> dict:
    """Return a copy of all Hebbian routing weights."""
    return dict(self._weights)

def set_weight(self, key: str, value: float) -> None:
    """Set a single routing weight."""
    self._weights[key] = value

def remove_weights_for_agent(self, agent_id: str) -> None:
    """Remove all routing weights involving the given agent."""
    keys_to_remove = [k for k in self._weights if agent_id in k]
    for k in keys_to_remove:
        del self._weights[k]

def get_all_compat_weights(self) -> dict:
    """Return a copy of all compatibility weights."""
    return dict(self._compat_weights)

def set_compat_weight(self, key: str, value: float) -> None:
    """Set a single compatibility weight."""
    self._compat_weights[key] = value

def remove_compat_weights_for_agent(self, agent_id: str) -> None:
    """Remove all compatibility weights involving the given agent."""
    keys_to_remove = [k for k in self._compat_weights if agent_id in k]
    for k in keys_to_remove:
        del self._compat_weights[k]
```

**Used at runtime.py lines:** 4760-4775 (prune_agent deletions), 4915-4917 (warm boot restoration)

---

### 3. `src/probos/ward_room.py` — WardRoomService (4 patches)

Current private access: `self.ward_room._db` (raw SQL execute), `._ontology` (set reference)

Add:

```python
def set_ontology(self, ontology) -> None:
    """Inject ontology reference for crew-aware channel management."""
    self._ontology = ontology

async def post_system_message(self, channel_name: str, content: str, author: str = "ship_computer") -> None:
    """Post a system-generated message to a named channel.

    Used for lifecycle announcements (System Online, Entering Stasis, etc.).
    Creates thread + post in the named channel. No-op if channel not found.
    """
    async with aiosqlite.connect(self._db_path) as db:
        # Find channel by name
        cursor = await db.execute(
            "SELECT id FROM channels WHERE name = ?", (channel_name,)
        )
        row = await cursor.fetchone()
        if not row:
            return
        channel_id = row[0]
        # Create thread + post
        thread_id = str(uuid.uuid4())
        post_id = str(uuid.uuid4())
        now = time.time()
        await db.execute(
            "INSERT INTO threads (id, channel_id, title, author_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (thread_id, channel_id, content[:80], author, now),
        )
        await db.execute(
            "INSERT INTO posts (id, thread_id, author_id, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (post_id, thread_id, author, content, now),
        )
        await db.commit()

@property
def is_started(self) -> bool:
    """Whether the Ward Room database has been initialized."""
    return self._db_path is not None and Path(self._db_path).exists()
```

**Used at runtime.py lines:** 1675 (set ontology), 1726/1808 (raw SQL for announcements), 1806 (check if DB exists)

---

### 4. `src/probos/substrate/pool.py` — ResourcePool (3 patches)

Current private access: `pool._agent_ids` (read list, remove item, check membership)

Add:

```python
def get_agent_ids(self) -> list[str]:
    """Return a copy of all agent IDs in this pool."""
    return list(self._agent_ids)

def contains_agent(self, agent_id: str) -> bool:
    """Check if an agent is in this pool."""
    return agent_id in self._agent_ids

def remove_agent(self, agent_id: str) -> None:
    """Remove an agent from this pool by ID."""
    self._agent_ids.remove(agent_id)
```

**Used at runtime.py lines:** 4708 (manifest build), 4745 (prune check), 4753 (prune remove)

---

### 5. `src/probos/consensus/trust.py` — TrustNetwork (2 patches)

Current private access: `self.trust_network._records` (delete entry)

Add:

```python
def remove_agent(self, agent_id: str) -> None:
    """Remove all trust records for the given agent."""
    if agent_id in self._records:
        del self._records[agent_id]
```

**Used at runtime.py lines:** 4760-4761 (prune_agent)

---

### 6. `src/probos/cognitive/dreaming.py` — DreamScheduler (3 patches)

Current private access: `._post_dream_fn`, `._pre_dream_fn`, `._post_micro_dream_fn` (callback injection)

Add:

```python
def set_callbacks(
    self,
    *,
    pre_dream: Callable | None = None,
    post_dream: Callable | None = None,
    post_micro_dream: Callable | None = None,
) -> None:
    """Set lifecycle callbacks for dream events."""
    if pre_dream is not None:
        self._pre_dream_fn = pre_dream
    if post_dream is not None:
        self._post_dream_fn = post_dream
    if post_micro_dream is not None:
        self._post_micro_dream_fn = post_micro_dream
```

**Used at runtime.py lines:** 1356-1358

---

### 7. `src/probos/proactive.py` — ProactiveCognitiveLoop (2 patches)

Current private access: `._knowledge_store` (set), `._agent_cooldowns` (read for persistence)

Add:

```python
def set_knowledge_store(self, store) -> None:
    """Inject knowledge store for cooldown persistence."""
    self._knowledge_store = store

def get_cooldowns(self) -> dict:
    """Return a copy of per-agent cooldown data for persistence."""
    return dict(self._agent_cooldowns)
```

**Used at runtime.py lines:** 1708 (inject KS), 1881 (read cooldowns at shutdown)

---

### 8. `src/probos/cognitive/self_mod.py` — SelfModificationPipeline (3 patches)

Current private access: `._validator`, `._sandbox`, `._records`

Add:

```python
@property
def validator(self):
    """The code validator used by this pipeline."""
    return self._validator

@property
def sandbox(self):
    """The execution sandbox used by this pipeline."""
    return self._sandbox

@property
def design_records(self) -> list:
    """All design records (DesignedAgentRecord) tracked by this pipeline."""
    return list(self._records)
```

**Used at runtime.py lines:** 1197-1198 (read validator/sandbox for AgentPatcher), 3266 (read records for find_designed_record)

---

### 9. `src/probos/cognitive/decomposer.py` — IntentDecomposer (2 patches)

Current private access: `._callsign_map` (set), `._intent_descriptors` (read length)

Add:

```python
def set_callsign_map(self, callsign_map: dict[str, str]) -> None:
    """Set the callsign→agent_type mapping for @mention resolution."""
    self._callsign_map = callsign_map

@property
def intent_descriptor_count(self) -> int:
    """Number of registered intent descriptors."""
    return len(self._intent_descriptors)
```

**Used at runtime.py lines:** 190 (set callsign map), 2413 (read count for self-model)

---

### 10. `src/probos/mesh/capability.py` — CapabilityRegistry (2 patches)

Current private access: `._capabilities` (read dict)

Add:

```python
def get_all_capabilities(self) -> dict:
    """Return a copy of all registered capabilities {agent_id: [capabilities]}."""
    return dict(self._capabilities)
```

**Used at runtime.py lines:** 2599, 2933 (read capabilities for working memory context)

---

### 11. `src/probos/consensus/escalation.py` — EscalationManager (1 patch)

Current private access: `._surge_fn` (set callback)

Add:

```python
def set_surge_callback(self, fn: Callable) -> None:
    """Set the pool surge callback for escalation-triggered scaling."""
    self._surge_fn = fn
```

**Used at runtime.py line:** 1062

---

### 12. `src/probos/mesh/intent.py` — IntentBus (1 patch)

Current private access: `._federation_fn` (set callback)

Add:

```python
def set_federation_handler(self, fn: Callable) -> None:
    """Set the federation forwarding handler for cross-realm intents."""
    self._federation_fn = fn
```

**Used at runtime.py line:** 1101

---

### 13. `src/probos/cognitive/workflow_cache.py` — WorkflowCache (1 patch)

Current private access: `._cache[key] = value` (write during warm boot)

Add:

```python
def restore_entry(self, key: str, value) -> None:
    """Restore a cached workflow entry during warm boot."""
    self._cache[key] = value
```

**Used at runtime.py line:** 5086

---

### 14. `src/probos/substrate/pool_group.py` — PoolGroupRegistry (2 patches)

Current private access: `._pool_to_group` (read mapping)

Add:

```python
def get_group_for_pool(self, pool_name: str) -> str | None:
    """Return the group name for a given pool, or None."""
    return self._pool_to_group.get(pool_name)
```

**Used at runtime.py lines:** 656 (HXI state), 710 (department lookup)

---

### 15. `src/probos/crew_profile.py` — CallsignRegistry (1 patch)

Current private access: `._type_to_profile` (read dict)

Add:

```python
def get_profile(self, agent_type: str) -> dict | None:
    """Return the crew profile for the given agent type, or None."""
    return self._type_to_profile.get(agent_type)
```

**Used at runtime.py line:** 591

---

### 16. Agent Base Class — `src/probos/substrate/agent.py` or equivalent (7 patches)

Current private access on agent instances: `._birth_timestamp`, `._system_start_time`, `._id`, `._llm_client`

Find the base Agent class (or CognitiveAgent if that's where these attributes live) and add:

```python
def set_temporal_context(self, birth_time: float, system_start_time: float) -> None:
    """Set temporal awareness for AD-502 lifecycle context."""
    self._birth_timestamp = birth_time
    self._system_start_time = system_start_time

@property
def has_llm_client(self) -> bool:
    """Whether this agent has an LLM client configured."""
    return hasattr(self, '_llm_client') and self._llm_client is not None

@property
def llm_client(self):
    """The agent's LLM client, or None."""
    return getattr(self, '_llm_client', None)
```

For the `_id` force-set at line 3218 (`new_agent._id = aid`), add to the base Agent class:

```python
def _replace_id(self, new_id: str) -> None:
    """Replace agent ID during hot-swap. Internal use only."""
    self._id = new_id
```

**Used at runtime.py lines:** 4374-4375, 4435-4436 (temporal context), 4378, 4554 (LLM client check), 3218 (ID force-set)

---

### 17. VitalsMonitor access (2 patches)

Current private access: `agent._window` (read vitals data)

Find VitalsMonitorAgent (in `src/probos/agents/heartbeat_monitor.py` or equivalent) and add:

```python
@property
def latest_vitals(self) -> dict | None:
    """Return the most recent vitals snapshot, or None."""
    if self._window:
        return self._window[-1]
    return None

@property
def vitals_window(self) -> list:
    """Return a copy of the vitals history window."""
    return list(self._window)
```

**Used at runtime.py lines:** 4094, 4097

---

## Part B: Protocol Definitions

Create a new file `src/probos/protocols.py` defining narrow interfaces for the major service boundaries. These are NOT used yet — they define the target interfaces for AD-515's decomposition.

```python
"""AD-514: Service boundary protocols for interface segregation.

These protocols define the narrow interfaces that consumers depend on,
enabling decomposition of ProbOSRuntime into focused modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from probos.types import Episode


@runtime_checkable
class EpisodicMemoryProtocol(Protocol):
    """What agents and services need from episodic memory."""

    async def store(self, episode: Episode) -> None: ...
    async def recall(self, query: str, k: int = 5) -> list: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


@runtime_checkable
class TrustNetworkProtocol(Protocol):
    """What services need from the trust network."""

    def get_trust_score(self, agent_id: str) -> float: ...
    def get_or_create(self, agent_id: str) -> object: ...
    async def record_outcome(self, agent_id: str, success: bool, weight: float = 1.0) -> None: ...
    def remove_agent(self, agent_id: str) -> None: ...


@runtime_checkable
class EventLogProtocol(Protocol):
    """What services need from event logging."""

    async def log(self, category: str, agent_id: str, data: dict | None = None) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


@runtime_checkable
class WardRoomProtocol(Protocol):
    """What services need from the Ward Room."""

    async def create_thread(self, channel_id: str, title: str, author_id: str, **kwargs) -> dict: ...
    async def create_post(self, thread_id: str, author_id: str, content: str) -> dict: ...
    async def get_thread(self, thread_id: str) -> dict | None: ...
    async def list_channels(self) -> list: ...
    async def post_system_message(self, channel_name: str, content: str, author: str = "ship_computer") -> None: ...
    def set_ontology(self, ontology) -> None: ...


@runtime_checkable
class KnowledgeStoreProtocol(Protocol):
    """What services need from the knowledge store."""

    async def store_agent(self, record, source_code: str) -> None: ...
    async def store_episode(self, episode) -> None: ...
    async def store_skill(self, name: str, source: str, descriptor: dict) -> None: ...
    async def store_trust_snapshot(self, data: dict) -> None: ...
    async def store_routing_snapshot(self, data: dict) -> None: ...


@runtime_checkable
class HebbianRouterProtocol(Protocol):
    """What services need from Hebbian routing."""

    def record_interaction(self, agent_id: str, intent: str, score: float) -> None: ...
    def get_all_weights(self) -> dict: ...
    def set_weight(self, key: str, value: float) -> None: ...
    def remove_weights_for_agent(self, agent_id: str) -> None: ...


@runtime_checkable
class EventEmitterProtocol(Protocol):
    """What modules need to emit HXI events."""

    def emit_event(self, event_type: str, data: dict) -> None: ...
    def add_event_listener(self, fn) -> None: ...
    def remove_event_listener(self, fn) -> None: ...
```

**Note:** Each protocol includes ONLY the methods that consumers actually use — not the full service API. This is Interface Segregation in action. Verify each protocol against actual usage in runtime.py before finalizing. If a method isn't called by anything outside the service itself, don't include it in the protocol.

---

## Part C: Tests

Create `tests/test_public_apis.py` with tests for all new public methods.

Group tests by target object. For each public method added, test:

1. **Basic functionality** — does it return/do what it should?
2. **Edge cases** — empty state, missing keys, None values
3. **Equivalence** — result matches direct private access (assert `obj.get_all_weights() == dict(obj._weights)`)

**Do NOT test Protocol definitions** — they are structural types, not implementations.

Test fixtures can construct the objects minimally (most constructors take simple args). Use mocks only where constructors require heavy runtime dependencies.

Minimum test count: **1 test per public method × 17 objects = ~40 tests**.

---

## Implementation Notes

- **Do NOT modify runtime.py** in this AD — the private access sites stay as-is. AD-515 migrates them.
- **Do NOT add type annotations referencing protocols** yet — that's AD-515.
- All public methods are **additive** — they don't break anything by existing.
- Keep method names consistent: `get_X()` for reads, `set_X()` for writes, `remove_X()` for deletes. Properties for simple state checks.
- For `set_callbacks()` style methods, use keyword-only arguments (`*,`) so callers are explicit about which callbacks they're setting.
- The `_replace_id()` method on the Agent base class keeps the underscore prefix to signal it's internal — but it's a method call rather than raw attribute mutation, which is the improvement.
- Some target files may need additional imports (e.g., `aiosqlite`, `uuid`, `time` for `ward_room.py`'s `post_system_message`). Check existing imports before adding duplicates.
- `protocols.py` uses `from __future__ import annotations` to avoid circular imports. All type references in Protocol bodies should be strings or use `TYPE_CHECKING` guard.

## Acceptance Criteria

- [ ] All 17 target objects have public methods replacing their private access patterns
- [ ] `src/probos/protocols.py` exists with 7 Protocol definitions
- [ ] ~40 tests in `tests/test_public_apis.py` all pass
- [ ] Existing test suite passes with zero regressions
- [ ] runtime.py is **NOT modified** (confirmed by git diff)
- [ ] No behavior changes — methods are trivial wrappers
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## SOLID Compliance

- **(S)** Each public method has a single purpose
- **(O)** Pure additions — no existing code modified
- **(L)** N/A — no inheritance changes
- **(I)** Protocol definitions enforce narrow interfaces
- **(D)** Protocols establish abstractions that AD-515 will wire up
