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
2. Demand tracking on `IntentBus` — throughput, response times, queue depth
3. Scale-up when sustained demand exceeds capacity thresholds
4. Scale-down when demand drops below idle thresholds (connects to dreaming)
5. Cooldown periods to prevent thrashing
6. `min_pool_size` / `max_pool_size` enforcement on all pool operations
7. Surge capacity request from `EscalationManager` for Tier 1 retries
8. Events, status, and panel rendering for scaling activity

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
    scale_up_threshold: float = 0.8       # Utilization ratio that triggers scale-up
    scale_down_threshold: float = 0.2     # Utilization ratio that triggers scale-down
    scale_up_step: int = 1                # Agents to add per scale-up event
    scale_down_step: int = 1              # Agents to remove per scale-down event
    cooldown_seconds: float = 30.0        # Minimum time between scaling events per pool
    observation_window_seconds: float = 60.0  # Window for computing average utilization
    idle_scale_down_seconds: float = 120.0    # Time with zero demand before scaling to min
```

Add `scaling: ScalingConfig = ScalingConfig()` to `SystemConfig`.

Add `scaling:` section to `config/system.yaml` with defaults.

### 2. Add demand metrics to `IntentBus` — `src/probos/mesh/intent.py`

The intent bus is the natural place to track demand. Add lightweight tracking (NOT a separate class — augment `IntentBus` directly):

```python
# In IntentBus.__init__:
self._broadcast_count: int = 0
self._total_response_time: float = 0.0
self._recent_broadcasts: list[float] = []  # timestamps of recent broadcasts
self._window_seconds: float = 60.0  # configurable observation window

# New methods:
def demand_metrics(self) -> dict:
    """Return current demand snapshot."""
    now = time.monotonic()
    # Prune old entries outside window
    cutoff = now - self._window_seconds
    self._recent_broadcasts = [t for t in self._recent_broadcasts if t > cutoff]
    return {
        "broadcasts_in_window": len(self._recent_broadcasts),
        "total_broadcasts": self._broadcast_count,
        "subscriber_count": len(self._subscribers),
        "avg_response_time": (self._total_response_time / self._broadcast_count) if self._broadcast_count > 0 else 0.0,
    }
```

In `broadcast()`, record timestamps and measure response times. This is just a few lines added to the existing method — do NOT restructure it.

### 3. Create `PoolScaler` — `src/probos/substrate/scaler.py`

New file. The `PoolScaler` is a background monitor that periodically evaluates demand and adjusts pool sizes.

```python
class PoolScaler:
    """Monitors demand and dynamically adjusts pool sizes.

    Runs a background loop that:
    1. Reads demand metrics from the IntentBus
    2. Computes per-pool utilization (active agents / pool size)
    3. Scales up pools that are consistently over-utilized
    4. Scales down pools that are consistently under-utilized
    5. Respects min_pool_size, max_pool_size, and cooldown periods
    """

    def __init__(
        self,
        pools: dict[str, ResourcePool],
        intent_bus: IntentBus,
        pool_config: PoolConfig,
        scaling_config: ScalingConfig,
        event_log: EventLog,
    ) -> None: ...

    async def start(self) -> None:
        """Start the background scaling loop."""

    async def stop(self) -> None:
        """Stop the scaling loop."""

    async def request_surge(self, pool_name: str, extra: int = 1) -> bool:
        """Request temporary scale-up for escalation retries.

        Called by EscalationManager during Tier 1 retries.
        Respects max_pool_size. Returns True if surge was granted.
        Records a scaling event but with reason='surge'.
        """

    async def _scaling_loop(self) -> None:
        """Periodic evaluation loop."""

    async def _evaluate_and_scale(self) -> None:
        """Core scaling logic for one evaluation cycle."""

    def _compute_utilization(self, pool: ResourcePool) -> float:
        """Compute pool utilization as ratio of busy agents to pool size.

        A 'busy' agent is one that's ACTIVE and currently handling an intent.
        For simplicity, use pool health ratio: healthy_agents / current_size.
        An overloaded pool has all agents busy → utilization near 1.0.
        An idle pool has most agents waiting → utilization based on demand metrics.
        """

    async def _scale_up(self, pool: ResourcePool, reason: str = "demand") -> bool:
        """Add one agent to pool. Returns True if successful.

        - Must not exceed max_pool_size
        - Must respect cooldown
        - Logs scaling event
        """

    async def _scale_down(self, pool: ResourcePool, reason: str = "idle") -> bool:
        """Remove one agent from pool. Returns True if successful.

        - Must not go below min_pool_size
        - Must respect cooldown
        - Stops and unregisters the removed agent
        - Logs scaling event
        """

    def scaling_status(self) -> dict:
        """Return current scaling state for each pool."""
```

**Important design constraints:**
- The scaler does NOT own the pools. It adjusts their `target_size` and calls `check_health()` (which handles spawning to target). For scale-down, it directly stops excess agents.
- Cooldown is tracked per-pool with timestamps.
- The `system` pool (heartbeat agents) should be excluded from scaling — heartbeats must stay fixed.
- Scale-down removes agents starting from the end of the pool's agent list (newest first).
- The scaler should be event-silent (like EscalationManager, AD-87). The caller (runtime) logs events.

### 4. Enforce `min_pool_size` / `max_pool_size` in `ResourcePool` — `src/probos/substrate/pool.py`

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

Also add methods the scaler needs:

```python
async def add_agent(self) -> AgentID | None:
    """Spawn one additional agent. Returns new agent ID, or None if at max."""
    if self.current_size >= self.max_size:
        return None
    agent = await self.spawner.spawn(self.agent_type, self.name, **self._spawn_kwargs)
    self._agent_ids.append(agent.id)
    self.target_size = max(self.target_size, self.current_size)
    return agent.id

async def remove_agent(self) -> AgentID | None:
    """Stop and remove one agent (newest). Returns removed ID, or None if at min."""
    if self.current_size <= self.min_size:
        return None
    aid = self._agent_ids.pop()  # Remove newest
    agent = self.registry.get(aid)
    if agent:
        await agent.stop()
        await self.registry.unregister(aid)
    self.target_size = min(self.target_size, self.current_size)
    return aid
```

**Do NOT change existing `start()`, `stop()`, or `check_health()` behavior** — only add the bounds enforcement and new methods. Existing tests must pass unchanged.

### 5. Wire `PoolScaler` into runtime — `src/probos/runtime.py`

```python
# In __init__:
self.pool_scaler: PoolScaler | None = None

# In start(), after all pools are created and before red team spawn:
if self.config.scaling.enabled:
    self.pool_scaler = PoolScaler(
        pools=self.pools,
        intent_bus=self.intent_bus,
        pool_config=self.config.pools,
        scaling_config=self.config.scaling,
        event_log=self.event_log,
    )
    await self.pool_scaler.start()

# In stop():
if self.pool_scaler:
    await self.pool_scaler.stop()

# In status():
# Add "scaling" key to status dict
```

### 6. Connect `EscalationManager` surge requests — `src/probos/consensus/escalation.py`

In `_tier1_retry()`, before retrying, check if the runtime has a `pool_scaler` and request surge capacity:

```python
# In _tier1_retry(), before the retry loop:
# If pool_scaler available, request surge capacity for the pool
pool_scaler = getattr(self._runtime, 'pool_scaler', None)
if pool_scaler and pool_name:
    await pool_scaler.request_surge(pool_name)
```

This is minimal — just 3 lines. The scaler handles bounds checking internally.

### 7. Connect dreaming to scale-down — `src/probos/cognitive/dreaming.py`

When a dream cycle starts (system is idle), signal the scaler to consider scaling down:

```python
# In DreamingEngine.dream(), at the start:
# Signal scaler that system is idle
pool_scaler = getattr(self._runtime, 'pool_scaler', None) if hasattr(self, '_runtime') else None
if pool_scaler:
    await pool_scaler.scale_down_idle()
```

Add `scale_down_idle()` to `PoolScaler` — scales each non-system pool down by one step, respecting min_pool_size. This is called during dream cycles (system has been idle).

### 8. Add `/scaling` command to shell — `src/probos/experience/shell.py`

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

### 9. Add `render_scaling_panel()` to `src/probos/experience/panels.py`

Render scaling status as a Rich table showing:
- Pool name
- Current size / min / max
- Utilization %
- Last scale event (up/down, when, reason)
- Cooldown remaining

### 10. Add scaling events to renderer — `src/probos/experience/renderer.py`

Handle `pool_scale_up` and `pool_scale_down` events in the `on_event` callback. Show brief status like: `"⬆ filesystem pool: 3 → 4 (demand)"` or `"⬇ shell pool: 4 → 3 (idle)"`.

---

## Test Plan — ~25 new tests in `tests/test_scaling.py`

### TestScalingConfig (2 tests)
1. Defaults load correctly from empty config
2. Custom values override defaults

### TestIntentBusDemandMetrics (3 tests)
3. `demand_metrics()` returns zeros when no broadcasts
4. `demand_metrics()` counts broadcasts within window
5. `demand_metrics()` prunes broadcasts outside window

### TestPoolBounds (4 tests)
6. `add_agent()` returns None when at `max_pool_size`
7. `add_agent()` spawns and returns agent ID when below max
8. `remove_agent()` returns None when at `min_pool_size`
9. `remove_agent()` stops agent and returns ID when above min

### TestPoolScalerScaleUp (3 tests)
10. Scale-up triggered when utilization exceeds threshold
11. Scale-up blocked by max_pool_size
12. Scale-up blocked by cooldown

### TestPoolScalerScaleDown (3 tests)
13. Scale-down triggered when utilization below threshold
14. Scale-down blocked by min_pool_size
15. Scale-down blocked by cooldown

### TestPoolScalerSurge (3 tests)
16. `request_surge()` adds agent to named pool
17. `request_surge()` returns False when at max
18. `request_surge()` resets cooldown

### TestPoolScalerIdleScaleDown (2 tests)
19. `scale_down_idle()` reduces all non-system pools toward min
20. `scale_down_idle()` skips "system" pool

### TestPoolScalerExclusions (2 tests)
21. System/heartbeat pools are excluded from automatic scaling
22. Pools with `min_pool_size == max_pool_size` (pinned) are excluded

### TestRuntimeScaling (3 tests)
23. Runtime creates `PoolScaler` when scaling enabled
24. Runtime does NOT create scaler when scaling disabled
25. `status()` includes scaling info

### TestScalingPanels (2 tests)
26. `render_scaling_panel()` shows pool sizes and utilization
27. `/scaling` command renders panel

---

## Build Order

Follow this sequence. Run `uv run pytest tests/ -v` after each step and confirm all tests pass before moving on.

1. **Pre-build audit**: Scan tests for pool size assertions. List affected tests. Verify none will break.
2. **ScalingConfig**: Add to `config.py` and `SystemConfig`. Add to `system.yaml`. Write tests 1–2.
3. **IntentBus demand metrics**: Add tracking to `IntentBus`. Write tests 3–5.
4. **Pool bounds enforcement**: Add `min_size`/`max_size` to `ResourcePool.__init__`, `add_agent()`, `remove_agent()`. Write tests 6–9.
5. **PoolScaler core**: Create `src/probos/substrate/scaler.py` with `PoolScaler`. Write tests 10–15.
6. **PoolScaler surge & idle**: Add `request_surge()` and `scale_down_idle()`. Write tests 16–20.
7. **PoolScaler exclusions**: System pool exclusion logic. Write tests 21–22.
8. **Runtime wiring**: Wire `PoolScaler` creation/start/stop in runtime. Wire into `status()`. Write tests 23–25.
9. **Escalation integration**: Add surge request to `_tier1_retry()`. Verify escalation tests still pass.
10. **Dreaming integration**: Add idle scale-down call in `DreamingEngine.dream()`. Verify dreaming tests still pass.
11. **Shell and panels**: Add `/scaling` command, `render_scaling_panel()`, scaling event rendering. Write tests 26–27.
12. **`/help` update**: Add `/scaling` to help output.
13. **PROGRESS.md update**: Document Phase 8, all ADs, test counts.
14. **Final verification**: `uv run pytest tests/ -v` — all tests pass.

---

## Architectural Decisions to Document

- **AD-90**: PoolScaler adjusts `target_size`, doesn't bypass ResourcePool — the pool's own `check_health()` handles spawning to target. Scale-down directly stops excess agents via `remove_agent()`.
- **AD-91**: System/heartbeat pools excluded from auto-scaling — heartbeats must maintain fixed rhythm. Exclusion by pool name, not agent type.
- **AD-92**: PoolScaler is event-silent (same pattern as AD-87 EscalationManager). Returns status dicts; the runtime logs scaling events.
- **AD-93**: Demand metrics on IntentBus, not a separate DemandTracker — the bus already knows broadcast count, subscriber count, and response times. Adding a separate tracker would duplicate state.
- **AD-94**: `min_pool_size`/`max_pool_size` were dead config since Phase 1 — now enforced. No behavior change for existing pools since all start within bounds.
- **AD-95**: Surge capacity from escalation is bounded — `request_surge()` respects `max_pool_size`. Escalation can't spawn unlimited agents.

---

## Non-Goals

- **Auto-discovery of optimal pool sizes**: The scaler adjusts within configured bounds, it doesn't learn optimal sizes. That belongs to dreaming/habit formation.
- **Per-pool scaling configs**: All pools share the same `ScalingConfig`. Per-pool overrides would add complexity for minimal benefit at this stage.
- **Agent migration between pools**: Agents don't move between pools. Scaling spawns new agents of the pool's type.
- **Predictive scaling**: No forecasting based on historical patterns. Reactive only. Predictive could layer on top later via dreaming pre-warm.
