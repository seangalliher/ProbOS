# Phase 8: Adaptive Pool Sizing & Dynamic Scaling

**Goal:** Pools should dynamically grow and shrink based on demand, not stay fixed at `target_size` forever. When the system is under heavy load, pools scale up toward `max_pool_size`. When idle, pools scale down toward `min_pool_size`. This fulfils the original vision's "Graceful Degradation" substrate principle:

> *"If 3 of 5 memory agents die, the system slows but doesn't crash. New agents spawn from templates. There is no 'blue screen' — only reduced capability."*

And the "Attention Allocation" cognitive principle:

> *"Instead of a process scheduler with time slices, the cognitive layer operates an attention mechanism. Agents compete for compute resources by signaling urgency and relevance. Important, time-sensitive tasks get more agent-population bandwidth."*

---

## Context

Right now, `ResourcePool` maintains a static `target_size`. Health checks respawn agents that die or degrade, but the pool never grows or shrinks. The config already defines `max_pool_size: 7` and `min_pool_size: 2` in `PoolConfig`, but **neither is ever checked or enforced** — they're dead config. Similarly, `spawn_cooldown_ms: 500` exists but is never used.

This phase adds:
1. A `PoolScaler` that monitors demand metrics and adjusts pool `target_size` values
2. Per-pool demand tracking on `IntentBus` — throughput within observation windows
3. Scale-up when sustained demand exceeds capacity thresholds
4. Scale-down when demand drops below idle thresholds (connects to dreaming)
5. Cooldown periods to prevent thrashing
6. `min_pool_size` / `max_pool_size` enforcement on all pool operations
7. Surge capacity request from `EscalationManager` for Tier 1 retries
8. Trust-aware scale-down agent selection
9. Events, status, and panel rendering for scaling activity

---

## ⚠ AD Numbering: Start at AD-94

AD-90 through AD-93 already exist in PROGRESS.md (DAG plan debug-only, Tier 3 prompt enrichment, Rich Live → spinner, manually managed spinner). **All architectural decisions in this phase start at AD-94.** Do NOT reuse AD-90 through AD-93.

---

## ⚠ Pre-Build Audit: Existing Pool Behaviour

**Before writing any code**, search the test suite for every test that:
- Creates a `ResourcePool` with a specific `target_size` and asserts `current_size`
- Checks pool health and expects exact agent counts
- Calls `pool.start()` and asserts the number of spawned agents

These tests assume pools are static. The new scaling logic must NOT break these tests — pools that have no scaler attached must behave identically to today. Only pools with an active `PoolScaler` should exhibit dynamic sizing. Verify all existing pool tests still pass at every step.

---

## Deliverables

### 1. Add `ScalingConfig` to `src/probos/config.py`

Add a new config model for pool scaling parameters:

```python
class ScalingConfig(BaseModel):
    """Adaptive pool scaling configuration."""

    enabled: bool = True
    scale_up_threshold: float = 0.8       # Demand-to-capacity ratio that triggers scale-up
    scale_down_threshold: float = 0.2     # Demand-to-capacity ratio that triggers scale-down
    scale_up_step: int = 1                # Agents to add per scale-up event
    scale_down_step: int = 1              # Agents to remove per scale-down event
    cooldown_seconds: float = 30.0        # Minimum time between scaling events per pool
    observation_window_seconds: float = 60.0  # Window for computing demand metrics
    idle_scale_down_seconds: float = 120.0    # Time with zero demand before scaling to min
```

Add `scaling: ScalingConfig = ScalingConfig()` to `SystemConfig`.

Add `scaling:` section to `config/system.yaml` with defaults.

### 2. Add per-pool demand tracking to `IntentBus` — `src/probos/mesh/intent.py`

The intent bus is the natural place to track demand. Add lightweight tracking (NOT a separate class — augment `IntentBus` directly):

```python
# In IntentBus.__init__:
self._broadcast_timestamps: list[tuple[float, str]] = []  # (monotonic_time, intent_name)
self._window_seconds: float = 60.0  # configurable observation window

# New methods:
def record_broadcast(self, intent_name: str) -> None:
    """Record a broadcast event with its intent name. Called within broadcast()."""
    self._broadcast_timestamps.append((time.monotonic(), intent_name))

def demand_metrics(self) -> dict:
    """Return current demand snapshot (system-wide)."""
    now = time.monotonic()
    cutoff = now - self._window_seconds
    self._broadcast_timestamps = [(t, n) for t, n in self._broadcast_timestamps if t > cutoff]
    return {
        "broadcasts_in_window": len(self._broadcast_timestamps),
        "subscriber_count": len(self._subscribers),
    }

def per_pool_demand(self, pool_intents: dict[str, list[str]]) -> dict[str, int]:
    """Return broadcast counts per pool within the observation window.

    Args:
        pool_intents: mapping of pool_name → list of intent names that pool handles.
                      Example: {"filesystem": ["read_file", "stat_file"],
                                "filesystem_writers": ["write_file"]}

    Returns:
        dict of pool_name → number of broadcasts targeting that pool's intents.
    """
    now = time.monotonic()
    cutoff = now - self._window_seconds
    self._broadcast_timestamps = [(t, n) for t, n in self._broadcast_timestamps if t > cutoff]

    # Build reverse mapping: intent_name → pool_name
    intent_to_pool: dict[str, str] = {}
    for pool_name, intents in pool_intents.items():
        for intent in intents:
            intent_to_pool[intent] = pool_name

    counts: dict[str, int] = {name: 0 for name in pool_intents}
    for _, intent_name in self._broadcast_timestamps:
        pool = intent_to_pool.get(intent_name)
        if pool:
            counts[pool] += 1
    return counts
```

In `broadcast()`, call `self.record_broadcast(intent.intent)` at the start. This is one line added to the existing method — do NOT restructure it.

**Why per-pool demand matters:** The scaler needs to know which pools are hot and which are idle. A system-wide metric would scale all pools equally, which defeats the purpose. Per-pool demand maps broadcasts to the pools that handle those intents.

### 3. Build pool-intent mapping in runtime — `src/probos/runtime.py`

The runtime knows which agent types handle which intents (from `intent_descriptors`). Add a method that builds the mapping the scaler needs:

```python
def _build_pool_intent_map(self) -> dict[str, list[str]]:
    """Build mapping of pool_name → list of intent names for demand tracking.

    Uses intent_descriptors from registered agent templates.
    """
    pool_intents: dict[str, list[str]] = {}
    for type_name, template_cls in self.spawner._templates.items():
        descriptors = getattr(template_cls, 'intent_descriptors', [])
        if not descriptors:
            continue
        # Find which pool this agent type belongs to
        for pool_name, pool in self.pools.items():
            if pool.agent_type == type_name:
                pool_intents[pool_name] = [d.name for d in descriptors]
                break
    return pool_intents
```

Pass this to the `PoolScaler` at construction time.

### 4. Create `PoolScaler` — `src/probos/substrate/scaler.py`

New file. The `PoolScaler` is a background monitor that periodically evaluates demand and adjusts pool sizes.

```python
class PoolScaler:
    """Monitors demand and dynamically adjusts pool sizes.

    Runs a background loop that:
    1. Reads per-pool demand from IntentBus
    2. Computes demand-to-capacity ratio per pool
    3. Scales up pools that are consistently over-demanded
    4. Scales down pools that are consistently under-demanded
    5. Respects min_pool_size, max_pool_size, and cooldown periods
    """

    def __init__(
        self,
        pools: dict[str, ResourcePool],
        intent_bus: IntentBus,
        pool_config: PoolConfig,
        scaling_config: ScalingConfig,
        pool_intent_map: dict[str, list[str]],
        excluded_pools: set[str] | None = None,  # e.g. {"system"}
    ) -> None: ...

    async def start(self) -> None:
        """Start the background scaling loop."""

    async def stop(self) -> None:
        """Stop the scaling loop."""

    async def request_surge(self, pool_name: str, extra: int = 1) -> bool:
        """Request temporary scale-up for escalation retries.

        Called by EscalationManager during Tier 1 retries.
        Respects max_pool_size. Returns True if surge was granted.
        Bypasses cooldown (surges are emergency requests).
        Records a scaling event with reason='surge'.
        """

    async def scale_down_idle(self) -> None:
        """Scale each non-excluded pool down by one step, respecting min_pool_size.

        Called during dream cycles (system has been idle).
        Respects cooldown. Reason='idle'.
        """

    async def _scaling_loop(self) -> None:
        """Periodic evaluation loop (runs every observation_window_seconds / 2)."""

    async def _evaluate_and_scale(self) -> None:
        """Core scaling logic for one evaluation cycle.

        For each non-excluded pool:
        1. Compute demand ratio = broadcasts_in_window / pool_size
        2. Normalize: ratio / scale_up_threshold gives utilization in [0, 1+]
        3. If ratio > scale_up_threshold for sustained period → scale up
        4. If ratio < scale_down_threshold for sustained period → scale down
        """

    def _compute_demand_ratio(self, pool_name: str, pool: ResourcePool) -> float:
        """Compute demand-to-capacity ratio for a pool.

        demand_ratio = broadcasts targeting this pool in window / pool.current_size

        A pool with 3 agents that received 6 broadcasts in the window has
        demand_ratio = 2.0 (each agent handled ~2 requests — busy).
        A pool with 3 agents that received 0 broadcasts has demand_ratio = 0.0 (idle).
        """

    async def _scale_up(self, pool: ResourcePool, reason: str = "demand") -> bool:
        """Add one agent to pool via pool.add_agent(). Returns True if successful.

        - Must not exceed max_pool_size (enforced by pool.add_agent())
        - Must respect cooldown
        - Updates pool.target_size to new size
        """

    async def _scale_down(self, pool: ResourcePool, reason: str = "idle") -> bool:
        """Remove one agent from pool via pool.remove_agent(). Returns True if successful.

        - Must not go below min_pool_size (enforced by pool.remove_agent())
        - Must respect cooldown
        - Updates pool.target_size to new size
        """

    def scaling_status(self) -> dict:
        """Return current scaling state for each pool.

        Includes: pool_name, current_size, min/max, demand_ratio,
        last_scale_event (direction, time, reason), cooldown_remaining.
        """
```

**Important design constraints:**
- The scaler owns `target_size` adjustments. After `add_agent()` or `remove_agent()` succeeds, the scaler sets `pool.target_size = pool.current_size`. The `add_agent()` and `remove_agent()` methods on ResourcePool do NOT touch `target_size` — they only add/remove agents. This prevents the health check loop from fighting the scaler.
- Cooldown is tracked per-pool with monotonic timestamps.
- The `system` pool (heartbeat agents) is excluded via `excluded_pools` — heartbeats must stay fixed.
- The scaler logs scaling decisions at DEBUG level (AD-63/AD-84 pattern — don't stomp the shell prompt).

### 5. Trust-aware scale-down agent selection in `ResourcePool` — `src/probos/substrate/pool.py`

Scale-down should remove the agent the system trusts least, not blindly the newest.

```python
async def remove_agent(self, trust_network=None) -> str | None:
    """Stop and remove the lowest-trust agent. Returns removed ID, or None if at min.

    If trust_network is provided, removes the agent with the lowest trust score.
    If trust_network is None or all agents have equal trust, removes newest (last in list).
    """
    if self.current_size <= self.min_size:
        return None

    if trust_network:
        # Find agent with lowest trust
        worst_id = None
        worst_trust = float('inf')
        for aid in self._agent_ids:
            score = trust_network.score(aid)  # Returns prior (0.5) for unknown agents
            if score < worst_trust:
                worst_trust = score
                worst_id = aid
        if worst_id:
            self._agent_ids.remove(worst_id)
            agent = self.registry.get(worst_id)
            if agent:
                await agent.stop()
                await self.registry.unregister(worst_id)
            return worst_id

    # Fallback: remove newest
    aid = self._agent_ids.pop()
    agent = self.registry.get(aid)
    if agent:
        await agent.stop()
        await self.registry.unregister(aid)
    return aid
```

The `PoolScaler._scale_down()` passes the trust network when calling `pool.remove_agent()`.

### 6. Enforce `min_pool_size` / `max_pool_size` in `ResourcePool` — `src/probos/substrate/pool.py`

Currently `pool.py` never checks these bounds. Add enforcement:

```python
# In ResourcePool.__init__:
self.min_size = pool_config.min_pool_size  # Store for scaler access
self.max_size = pool_config.max_pool_size

# In check_health() — after respawn loop:
# Cap at max_pool_size (safety check — shouldn't happen normally)
while len(self._agent_ids) > self.max_size:
    excess_id = self._agent_ids.pop()
    agent = self.registry.get(excess_id)
    if agent:
        await agent.stop()
        await self.registry.unregister(excess_id)
```

Also add the `add_agent()` method the scaler needs:

```python
async def add_agent(self, **kwargs) -> str | None:
    """Spawn one additional agent. Returns new agent ID, or None if at max.

    Does NOT modify target_size — the scaler owns target_size adjustments.
    """
    if self.current_size >= self.max_size:
        return None
    agent = await self.spawner.spawn(self.agent_type, self.name, **self._spawn_kwargs, **kwargs)
    self._agent_ids.append(agent.id)
    return agent.id
```

**Do NOT change existing `start()`, `stop()`, or `check_health()` behavior** — only add the bounds enforcement and new methods. Existing tests must pass unchanged.

### 7. Wire `PoolScaler` into runtime — `src/probos/runtime.py`

```python
# In __init__:
self.pool_scaler: PoolScaler | None = None

# In start(), after all pools are created and before red team spawn:
if self.config.scaling.enabled:
    pool_intent_map = self._build_pool_intent_map()
    self.pool_scaler = PoolScaler(
        pools=self.pools,
        intent_bus=self.intent_bus,
        pool_config=self.config.pools,
        scaling_config=self.config.scaling,
        pool_intent_map=pool_intent_map,
        excluded_pools={"system"},
    )
    await self.pool_scaler.start()

# In stop():
if self.pool_scaler:
    await self.pool_scaler.stop()

# In status():
# Add "scaling" key to status dict with pool_scaler.scaling_status() or {"enabled": False}
```

### 8. Connect `EscalationManager` surge requests via injected callable

**Do NOT add a runtime reference to EscalationManager.** Instead, inject a surge function as an optional callable, same pattern as `user_callback`:

```python
# In EscalationManager.__init__:
def __init__(
    self,
    submit_fn: ...,
    llm_client: ...,
    user_callback: ... = None,
    surge_fn: Callable[[str, int], Awaitable[bool]] | None = None,
):
    self._surge_fn = surge_fn

# In _tier1_retry(), before the retry loop:
if self._surge_fn and pool_name:
    await self._surge_fn(pool_name, 1)
```

In `runtime.py`, when creating the `EscalationManager`, pass the surge function:

```python
surge_fn = self.pool_scaler.request_surge if self.pool_scaler else None
self.escalation_manager = EscalationManager(
    ...,
    surge_fn=surge_fn,
)
```

This keeps `EscalationManager` testable without a full runtime. Tests can pass `surge_fn=None` or a mock callable.

### 9. Connect dreaming to scale-down via injected callable

**Do NOT add a runtime reference to DreamingEngine.** Instead, inject a scale-down callback:

```python
# In DreamingEngine.__init__:
def __init__(
    self,
    ...,
    idle_scale_down_fn: Callable[[], Awaitable[None]] | None = None,
):
    self._idle_scale_down_fn = idle_scale_down_fn

# In dream_cycle(), at the start:
if self._idle_scale_down_fn:
    await self._idle_scale_down_fn()
```

In `runtime.py`, when creating the `DreamingEngine`, pass the callback:

```python
idle_scale_down_fn = self.pool_scaler.scale_down_idle if self.pool_scaler else None
self.dreaming_engine = DreamingEngine(
    ...,
    idle_scale_down_fn=idle_scale_down_fn,
)
```

### 10. Add `/scaling` command to shell — `src/probos/experience/shell.py`

```python
# In command dispatch:
elif cmd == "/scaling":
    if self.runtime.pool_scaler:
        from probos.experience.panels import render_scaling_panel
        self.console.print(render_scaling_panel(self.runtime.pool_scaler.scaling_status()))
    else:
        self.console.print("[yellow]Scaling not enabled[/yellow]")

# Add to /help listing
```

### 11. Add `render_scaling_panel()` to `src/probos/experience/panels.py`

Render scaling status as a Rich table showing:
- Pool name
- Current size / min / max
- Demand ratio
- Last scale event (up/down, when, reason)
- Cooldown remaining

### 12. Add scaling events to renderer — `src/probos/experience/renderer.py`

Handle `pool_scale_up` and `pool_scale_down` events in the `on_event` callback. Show brief status like: `"⬆ filesystem pool: 3 → 4 (demand)"` or `"⬇ shell pool: 4 → 3 (idle)"`.

---

## Test Plan — ~30 new tests in `tests/test_scaling.py`

### TestScalingConfig (2 tests)
1. Defaults load correctly from empty config
2. Custom values override defaults

### TestIntentBusDemandMetrics (4 tests)
3. `demand_metrics()` returns zeros when no broadcasts
4. `demand_metrics()` counts broadcasts within window
5. `demand_metrics()` prunes broadcasts outside window
6. `per_pool_demand()` counts broadcasts per pool correctly

### TestPoolBounds (4 tests)
7. `add_agent()` returns None when at `max_pool_size`
8. `add_agent()` spawns and returns agent ID when below max
9. `remove_agent()` returns None when at `min_pool_size`
10. `remove_agent()` stops agent and returns ID when above min

### TestPoolScalerScaleUp (3 tests)
11. Scale-up triggered when demand ratio exceeds threshold
12. Scale-up blocked by max_pool_size
13. Scale-up blocked by cooldown

### TestPoolScalerScaleDown (3 tests)
14. Scale-down triggered when demand ratio below threshold
15. Scale-down blocked by min_pool_size
16. Scale-down blocked by cooldown

### TestTrustAwareScaleDown (3 tests)
17. `remove_agent(trust_network=...)` removes lowest-trust agent
18. Equal trust falls back to newest-first removal
19. `remove_agent(trust_network=None)` removes newest (backward compat)

### TestPoolScalerSurge (3 tests)
20. `request_surge()` adds agent to named pool
21. `request_surge()` returns False when at max
22. `request_surge()` bypasses cooldown

### TestPoolScalerIdleScaleDown (2 tests)
23. `scale_down_idle()` reduces all non-excluded pools toward min
24. `scale_down_idle()` skips excluded pools (system)

### TestPoolScalerExclusions (2 tests)
25. System/heartbeat pools are excluded from automatic scaling
26. Pools with `min_pool_size == max_pool_size` (pinned) are excluded

### TestRuntimeScaling (3 tests)
27. Runtime creates `PoolScaler` when scaling enabled
28. Runtime does NOT create scaler when scaling disabled
29. `status()` includes scaling info

### TestEscalationSurge (2 tests)
30. `surge_fn` called during Tier 1 retry
31. `surge_fn=None` — escalation works without scaler (backward compat)

### TestScalingPanels (2 tests)
32. `render_scaling_panel()` shows pool sizes and demand ratios
33. `/scaling` command renders panel

---

## Build Order

Follow this sequence. Run `uv run pytest tests/ -v` after each step and confirm all tests pass before moving on.

1. **Pre-build audit**: Scan tests for pool size assertions. List affected tests. Verify none will break.
2. **ScalingConfig**: Add to `config.py` and `SystemConfig`. Add to `system.yaml`. Write tests 1–2.
3. **IntentBus demand metrics**: Add per-pool tracking to `IntentBus`. Write tests 3–6.
4. **Pool bounds enforcement**: Add `min_size`/`max_size` to `ResourcePool.__init__`, `add_agent()`, `remove_agent(trust_network=...)`. Write tests 7–10.
5. **Trust-aware scale-down**: Implement trust-based agent selection in `remove_agent()`. Write tests 17–19.
6. **PoolScaler core**: Create `src/probos/substrate/scaler.py` with `PoolScaler`. Write tests 11–16.
7. **PoolScaler surge & idle**: Add `request_surge()` and `scale_down_idle()`. Write tests 20–24.
8. **PoolScaler exclusions**: System pool exclusion logic. Write tests 25–26.
9. **Runtime wiring**: Wire `PoolScaler` creation/start/stop in runtime. Build `_build_pool_intent_map()`. Wire into `status()`. Write tests 27–29.
10. **Escalation integration**: Add `surge_fn` parameter to `EscalationManager.__init__`. Wire in runtime. Write tests 30–31. Verify all existing escalation tests still pass.
11. **Dreaming integration**: Add `idle_scale_down_fn` parameter to `DreamingEngine.__init__`. Wire in runtime. Verify all existing dreaming tests still pass.
12. **Shell and panels**: Add `/scaling` command, `render_scaling_panel()`, scaling event rendering. Write tests 32–33.
13. **`/help` update**: Add `/scaling` to help output.
14. **PROGRESS.md update**: Document Phase 8, all ADs (starting at AD-94), test counts.
15. **Final verification**: `uv run pytest tests/ -v` — all tests pass.

---

## Architectural Decisions to Document

- **AD-94**: PoolScaler adjusts `target_size`, doesn't bypass ResourcePool — the pool's own `check_health()` handles spawning to target. Scale-down directly stops excess agents via `remove_agent()`. The scaler is the single owner of `target_size` mutations — `add_agent()`/`remove_agent()` never touch it.
- **AD-95**: System/heartbeat pools excluded from auto-scaling — heartbeats must maintain fixed rhythm. Exclusion via `excluded_pools` set at construction, not agent type.
- **AD-96**: Demand-based utilization, not health-ratio — demand ratio = broadcasts targeting a pool's intents in the observation window / pool size. This measures actual work arriving, not agent availability. A pool of 3 agents that received 6 requests has demand_ratio=2.0 (overloaded). A pool that received 0 requests has demand_ratio=0.0 (idle).
- **AD-97**: Per-pool demand tracking on IntentBus — `per_pool_demand(pool_intents)` counts broadcasts per pool using a pool_name → intent_names mapping built by the runtime. This avoids a separate DemandTracker class and keeps demand data where broadcasts happen.
- **AD-98**: `min_pool_size`/`max_pool_size` were dead config since Phase 1 — now enforced. No behavior change for existing pools since all start within bounds.
- **AD-99**: Surge capacity from escalation is bounded — `request_surge()` respects `max_pool_size`. Escalation can't spawn unlimited agents. Surges bypass cooldown since they're emergency requests.
- **AD-100**: Trust-aware scale-down — when scaling down, remove the agent with the lowest trust score rather than blindly removing the newest. This preserves agents that the system has learned to rely on. Falls back to newest-first if trust is unavailable or equal.
- **AD-101**: Scaling integrations use injected callables, not runtime references — `EscalationManager` receives `surge_fn: Callable`, `DreamingEngine` receives `idle_scale_down_fn: Callable`. Same pattern as `user_callback`. Keeps both classes testable without a full runtime.

---

## Non-Goals

- **Auto-discovery of optimal pool sizes**: The scaler adjusts within configured bounds, it doesn't learn optimal sizes. That belongs to dreaming/habit formation.
- **Per-pool scaling configs**: All pools share the same `ScalingConfig`. Per-pool overrides would add complexity for minimal benefit at this stage.
- **Agent migration between pools**: Agents don't move between pools. Scaling spawns new agents of the pool's type.
- **Predictive scaling**: No forecasting based on historical patterns. Reactive only. Predictive could layer on top later via dreaming pre-warm.
- **Response-time scaling**: Demand ratio (throughput) is the primary signal. Response-time-based scaling is a natural evolution but requires instrumenting `broadcast()` with per-intent latency tracking, which is more invasive. Could layer on top in a future phase.
