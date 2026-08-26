# AD-1254: one runtime-owned rehydration pair for every path that produces an agent

**Issue:** #1287 (BF-823) · **Follows:** BF-808 (#1272) · **Repo:** OSS, branch `main`, base `b4acdbfe`

## The gap, measured

BF-808 restores an agent's **constructor** dependencies on recycle. Agents are not finished when
their constructor returns. On a real `QuartermasterAgent`:

```
replacement_is_new         : True
runtime_preserved          : True     <- BF-808's guard passes
reconciler_preserved       : False
store_preserved            : False
router_preserved           : False
state                      : active
reconcile_result           : {..., degraded: True}
```

Reports `active`, satisfies the BF-808 check, and is degraded. The ticker still holds the
**stopped predecessor**.

`spawner.py:104-104` already names this in its own docstring — *"a recycled Quartermaster keeps
`_runtime`, passes this check, and is still degraded because its store, router and reconciler are
wired after construction in `finalize` and are not constructor kwargs at all. Making recycle whole
needs a runtime-owned rehydration hook, tracked separately."* This is that hook.

## The seam already exists — use it, do not invent one

BF-676 built the lifecycle-owned wire/unwire pair, and `ResourcePool` already calls it at **every**
agent-producing site:

```
runtime.py:2341-2349    on_agent_spawned=self.onboarding.wire_agent
                        on_agent_removing=self.onboarding.unwire_agent
pool.py:97              initial start
pool.py:145             refill / scale-up
pool.py:194             recycle rollback (predecessor retained)
pool.py:209             recycle success (replacement)
agent_onboarding.py:124 async def wire_agent(self, agent)
agent_onboarding.py:543 async def unwire_agent(self, agent_id)
```

All three paths #1287 names — initial startup, recycle, dynamic scale-up — already converge here.
The fix is a **rehydrator registry on `AgentOnboardingService`**, not a fourth mechanism.

## Required change

### 1. A rehydrator registry keyed by agent type

`AgentOnboardingService` gains a registration method in the same style as its existing
`set_billet_registry` / `set_tool_registry` / `set_skill_bridge` setters
(`agent_onboarding.py:104-122`). A rehydrator is an async callable taking the agent and applying the
post-construction wiring. `wire_agent` invokes the registered rehydrator, if any, as its final step.

Constructor injection, narrow `typing.Protocol` for the rehydrator signature, no `runtime`
back-reference on the service beyond what it already holds.

### 2. `finalize.py` registers rather than mutates

`_wire_board_reconciler` (`startup/finalize.py:2530-2645`) currently resolves the live agent once
and assigns fifteen private attributes to it:

```
finalize.py:2571   agents = registry.get_by_pool("quartermaster")
finalize.py:2578-2597   agent._reconciler / _store / _router / _emit / _episodic / _scan_limit /
                        _max_reconcile_attempts / _reconcile_backoff_seconds / _min_item_age_seconds /
                        _stall_timeout_seconds / _strand_timeout_seconds / _local_node_id /
                        _federation_enabled
```

Extract that assignment block into a rehydrator closure over the already-built collaborators, call
it once for the current agent (preserving today's startup behaviour exactly), and register it. The
collaborators are constructed once at startup and are safe to share; the *binding* is what must be
re-applied.

### 3. Rebind the external owners — this is the half a longer attribute list cannot reach

Two owners capture the agent object itself and survive its death:

- `BoardReconcilerTicker(agent=agent, ...)` — `finalize.py:2598-2604`. `runtime.board_reconciler_ticker`
  keeps pointing at a ticker bound to the stopped predecessor.
- `_on_agent_removed` — `finalize.py:2612-2623`, a closure capturing `agent`, registered as an event
  listener and held at `runtime.board_reactive_reclaim_handler`.

Both must resolve the agent **at call time** from the registry, or be re-bound by the rehydrator.
Resolving late is preferable — it removes the class of bug rather than adding a second place that
has to remember.

### 4. The crew-queue variant

`IntentBus` unregister pops the agent's queue (`mesh/intent.py`), and onboarding does not recreate
the one-time queue built during finalization. Measured: the replacement subscriber was correct but
had **no queue**, while the predecessor's queue task remained alive and bound to the old object.

Consequence: priority, backpressure and the dequeue-time circuit breaker are all bypassed for that
agent after a recycle. `unwire_agent` must shut the queue task down; `wire_agent` must recreate it.
BF-670 already established that same-ID re-subscription must replace memberships exactly rather
than leaving stale routes — the queue is the piece that was left out.

### 5. Extend BF-808's report honestly

`_RECYCLE_CRITICAL_DEPS` (`spawner.py:78`) stays `("_runtime", "_llm_client")`. **Do not widen it.**
The issue is explicit: a longer name list makes the check pass more loudly while the agent stays
broken. Update the `recycle` docstring (`spawner.py:93-105`) to point at this AD as the thing that
closed the gap it describes.

## The other two classes named in #1287

`Yeoman` (post-construction proactive subscription and persona) and `Counselor`
(`initialize()` collaborators, event listener, Initiative closure) have the same shape **by
reading**. Build the Quartermaster rehydrator first because it is the one measured. Then, for each
of the other two: **grep the actual wiring before writing a rehydrator for it**, and if the reading
turns out to be wrong, say so in the report rather than building a rehydrator for wiring that is
not there.

## Do not build

- **Do not widen `_RECYCLE_CRITICAL_DEPS`.** Named above; it is the trap.
- **Do not make `recycle` refuse on a lost dependency.** BF-808 recorded why: the raise escaped
  `check_health` before its refill loop and killed the pool's health task outright, and there is no
  supervisor to restart it. Report, do not refuse. (**#1288 / BF-824** is the adjacent issue that a
  recycle failure kills the health loop — do not fix it here, and do not make it worse.)
- **Do not give `AgentSpawner` a runtime handle.** The whole point is that the wiring lives in a
  startup function the spawner cannot see. Keep it that way; the *runtime* owns rehydration.
- **Do not build a generic "re-run all of finalize on this agent" hook.** `finalize.py` has 40+
  `_wire_*` functions; re-running them is not idempotent and would re-register listeners.
  Per-type rehydrators, explicitly registered.
- **Do not change `ResourcePool`'s scale/recycle transition ordering.** BF-676 serialised those
  deliberately.
- **Do not touch `NightOrdersManager`, `OrderManager`, or the watch roster** — unrelated.

## Tests

1. **The headline, and it must fail before the fix:** recycle a `QuartermasterAgent`, then call
   `reconcile` and assert `degraded` is **False**. Today it is True.
2. After a recycle, no external owner references the stopped predecessor — assert on the ticker's
   bound agent and on the event-listener closure, by identity, not by `is not None`.
3. The replacement has a live crew queue, and the predecessor's queue task is not still running.
   Assert the task is *done*, not merely that a new one exists.
4. Initial startup behaviour is **unchanged**: the rehydrator produces the same fifteen attribute
   values that the inline block did. Pin them by explicit comparison; this is the regression that a
   careless extraction causes.
5. Dynamic scale-up (`pool.py:145`) produces a rehydrated agent, not just a wired one.
6. A rehydrator that raises does not kill the pool — log-and-degrade, agent still registered, and
   the failure is visible.
7. One test per additional post-wired class actually built, exercising **the capability the later
   wiring provides** — not the presence of an attribute. An attribute check is what BF-808 already
   has and is exactly what this issue proves insufficient.

## Tracking

- Close **#1287** when the Quartermaster arm and the queue arm land; note which of Yeoman/Counselor
  were verified and which were deferred.
- `PROGRESS.md`, `DECISIONS.md`, roadmap.

## Report back

- The `degraded` value before and after, from a real recycle.
- Whether Yeoman and Counselor matched the reading, or did not.
- **Anything in this prompt that turned out to be untrue** — in particular, whether the fifteen
  attributes at `finalize.py:2578-2597` are the complete set.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
