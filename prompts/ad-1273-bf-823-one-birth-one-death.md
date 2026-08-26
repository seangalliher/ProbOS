# AD-1273 / BF-823: an agent is born once, wired once, and torn down once

**Issue:** #1287 (OPEN) · **Repo:** OSS `d:\ProbOS`, branch `main`
**AD:** AD-1273 — newly minted, ceiling was AD-1272. **BF:** BF-823 — already allocated, do not mint a new one.
**Related:** BF-808 (#1272, shipped) restored *constructor* dependencies on recycle. This is the other half.
**Status:** ready to build · **Estimated tests:** 14–18 across two slices

---

## The defect, verified at HEAD (2026-08-26)

An agent is not finished when its constructor returns. Startup wires substantial per-instance state
onto it *afterwards*, in functions the spawner cannot see. Recycling replaces the object and
reapplies none of it.

BF-808's own docstring already says so, in the source, unprompted:

```
src/probos/substrate/spawner.py:78    _RECYCLE_CRITICAL_DEPS = ("_runtime", "_llm_client")
                            :100-105  "...a recycled Quartermaster keeps ``_runtime``, passes this
                                       check, and is still degraded because its store, router and
                                       reconciler are wired after construction in ``finalize`` and
                                       are not constructor kwargs at all. Making recycle whole needs
                                       a runtime-owned rehydration hook, tracked separately."
```

This is that hook. The Captain measured the consequence on a real `QuartermasterAgent`: `state:
active`, `runtime_preserved: True` (BF-808's guard passes), `reconciler_preserved: False`,
`store_preserved: False`, `router_preserved: False`, `reconcile_result: {..., degraded: True}`.

**Do not re-litigate the premise. Do not widen `_RECYCLE_CRITICAL_DEPS`.** A longer name list makes
the check fail *louder* on the two names it knows and stays silent on the twelve it does not, and it
cannot touch the second half of the defect at all — external owners still holding the dead object.

---

## What the codebase already gives you — read this before designing anything

**A convergence point already exists.** All three agent-producing paths already funnel through
`AgentOnboardingService.wire_agent`:

| Path | Route to `wire_agent` | Verified |
|---|---|---|
| Initial startup | `runtime.create_pool` → `await pool.start()` → explicit loop | `runtime.py:2360-2362` |
| Recycle | `pool._recycle_registered_agent_inner` → `_notify_agent_spawned` | `pool.py:209` → `pool.py:61-64` |
| Dynamic scale-up | `_add_agent_inner` / health refill → `_adopt_dynamic_agent` → `_notify_agent_spawned` | `pool.py:443`, `pool.py:367` → `pool.py:93-97` |

The callbacks are bound at `runtime.py:2343-2352` (`on_agent_spawned=self.onboarding.wire_agent`,
`on_agent_removing=self.onboarding.unwire_agent`).

**So the structural answer is not "build a new component."** It is: `wire_agent` / `unwire_agent`
are the pair, they are already wired to all three paths, and they are **incomplete**. Complete them,
and invert the dependency so startup can no longer wire an agent behind their back.

---

## The design

### The rule

> **Any per-instance state that outlives the constructor is applied by a registered rehydrator, and
> any owner that outlives an agent instance holds the agent *id*, never the agent.**

Two halves, two failure modes, both required.

### Half 1 — rehydrators (replaces "startup mutates the live agent")

Add to `AgentOnboardingService` (`src/probos/agent_onboarding.py:40`):

```python
def register_rehydrator(
    self,
    agent_type: str,
    name: str,
    fn: Callable[[Any], Awaitable[None]],
) -> None:
```

- Keyed by `(agent_type, name)`; re-registering the same key **replaces**, so a second startup pass
  cannot double-register.
- `wire_agent` runs every rehydrator matching `agent.agent_type`, in registration order, **after**
  the existing intent-bus subscription (a rehydrator may legitimately depend on the subscription).
- Each rehydrator is **idempotent** — it must be safe to run against an agent that already has the
  state. This is what lets a migration land without removing the old startup call in the same
  breath, and what makes a double-wire harmless.
- Tier-2 log-and-degrade per rehydrator: one failing rehydrator must not abort onboarding for the
  rest, and must not take out the pool health loop (`pool.py:_health_loop`, BF-824's boundary is
  upstream of this and must stay effective). Log at **ERROR** with the rehydrator name and agent id —
  a silently skipped rehydrator is the exact defect this AD exists to close.

Startup functions then *register* instead of *mutate*. `_wire_board_reconciler` stops doing
`agent._reconciler = reconciler` against `registry.get_by_pool("quartermaster")[0]` and instead
registers a rehydrator that performs those assignments against whatever instance it is handed.

### Half 2 — owners hold ids

An owner that survives a recycle must resolve the agent at call time:

| Owner | Today | Required |
|---|---|---|
| `BoardReconcilerTicker` | `self._agent = agent` (`mesh/board_reconciler_ticker.py:32`), `await self._agent.reconcile()` (`:83`) | take `agent_id` + `registry`; resolve per tick; log-and-skip on a miss |
| `_on_agent_removed` reactive-reclaim closure | closes over `agent` (`finalize.py:2611-2620`), held at `finalize.py:2627` | resolve via registry inside the handler |
| `_counselor_alert_fn` | closes over `counselor_agent` (`finalize.py:5339-5340`) | resolve via `registry.get_by_pool("counselor")` inside the closure |

A ticker calling `reconcile()` on a stopped predecessor is not a degraded agent — it is a *second*
agent, unregistered, doing board work nobody can see. That is why this half is not optional.

### Teardown — the queue leak

`unwire_agent` (`agent_onboarding.py:543-547`) → `IntentBus.unsubscribe_and_wait` →
`_unsubscribe_local` (`mesh/intent.py:768`) → `unregister_queue` (`:772`).

`unregister_queue` (`intent.py:1362-1364`) **pops the dict and nothing else.** It never calls
`AgentCognitiveQueue.shutdown()` (`cognitive/queue.py:227`). So the predecessor's processor loop
(`queue.py:272`) stays alive, bound to the stopped object, for the life of the process.

And nothing recreates the queue: `AgentCognitiveQueue(...)` is constructed at exactly one site,
`finalize.py:4711`, inside a one-time startup pass over `runtime.registry.all()` (`:4707`).

Verified absence — run this yourself before building, and paste the result:

```
rg -n "AgentCognitiveQueue\(|register_queue" src/
```

Consequence, as the issue states: after a recycle the replacement is subscribed but queueless, so
**priority, backpressure and the dequeue-time circuit breaker are bypassed for that agent**. That is
a governance control silently disabled by a health check — which is why Slice A below leads with it.

---

## Slice A — the queue, end to end (shippable on its own)

Smallest change that closes a real, currently-bypassed control.

1. Add `register_rehydrator` + the `wire_agent` application loop.
2. Move the queue construction from `finalize.py:4707-4720` into a rehydrator registered for every
   crew agent type — or, if a per-type registration is awkward for the crew predicate, a single
   `register_rehydrator("*", ...)` wildcard whose body keeps the existing
   `is_crew_agent(agent, self._ontology)` guard. **Pick one and say why in the docstring.**
   - `_make_should_process`'s lazy `runtime.proactive_loop` lookup (`finalize.py:4694-4696`,
     comment: *"resolved at dequeue time, not construction time. Safe against wiring-order
     changes"*) is the evidence that moving this earlier is safe. Cite it; do not assume it.
   - The rehydrator must be idempotent: if `_intent_bus._get_agent_queue(agent.id)` already returns
     a live queue, do nothing.
3. Make `unregister_queue` shut the queue down before popping. It is currently sync
   (`intent.py:1362`) and `shutdown()` is async; `_unsubscribe_local` is sync but its caller
   `unsubscribe_and_wait` is async. **Move the shutdown to the async side** — do not create a task
   and walk away, or the drain races the replacement's first dispatch.
4. Delete the `finalize.py:4707-4720` loop and replace it with a count assertion log, so a
   regression that stops registering rehydrators is visible at boot rather than at the first
   recycle.

**Slice A does not close #1287.** Say so in the commit. It closes the crew-queue variant only.

---

## Slice B — the post-wired agents

Migrate, one agent class per commit, each with its own test:

| Agent | Wiring site | What a replacement loses today |
|---|---|---|
| Quartermaster | `finalize.py:2578-2596` (12 private attrs), ticker `:2598-2604`, reclaim closure `:2611-2627` | store, router, reconciler, emitter, episodic, 6 config values, node scope; ticker points at the corpse |
| Yeoman | `agent_fleet.py:217-241` (`await yeoman.initialize(...)` at `:219`) | Captain Card persona, duty schedule, digest window |
| Counselor | `finalize.py:5250-5269` (`initialize`), `:5271-5289` (reminiscence), `:5338-5341` (alert closure) | collaborators, reminiscence engine, Initiative wiring |

**Enumerate the rest yourself — do not trust this table as complete.** There are further
post-construction passes over `registry.all()` at `finalize.py:5074` (`set_concurrency_manager`) and
`finalize.py:5413` (working-memory restore) that are also per-instance. Run:

```
rg -n "for agent in runtime\.registry\.all\(\)" src/probos/startup/finalize.py
```

and classify each hit as **per-instance** (must become a rehydrator) or **one-time/type-level**
(leave alone — e.g. `:5453` evicts a per-*type* decision cache, `:5479` writes a boot briefing).
Put the classification in the commit message. A pass you skipped because it looked one-time is
exactly the shape of this bug.

---

## Required tests

New files: `tests/test_ad1273_agent_rehydration.py`, `tests/test_ad1273_owner_holds_id.py`.

1. **The headline, per the issue's acceptance:** recycle a `QuartermasterAgent` through the real
   `ResourcePool` path and assert `reconcile()` returns **not** degraded. Assert the positive
   premise beside it — that the predecessor *was* degraded-free before the recycle — or the test
   passes against a reconciler that is degraded in both directions.
2. **No owner references the corpse.** After a recycle, assert the ticker's resolved agent
   `is` the registry's current instance, and `is not` the stopped predecessor. Identity comparison,
   not equality.
3. **Queue survives a recycle.** `_get_agent_queue(agent_id)` returns a live queue whose handler is
   bound to the *replacement*. Assert the handler's `__self__` identity.
4. **The predecessor's queue task is done.** Not "a queue was popped" — assert the processor task
   reaches `done()`. This is the leak assertion and it is the one a naive fix survives.
5. **The control is actually enforced after a recycle.** Enqueue past the backpressure bound on the
   replacement and assert rejection. A queue that exists but is not consulted passes tests 3 and 4.
6. **All three paths, one parameterised test.** Initial startup, recycle, and `add_agent` must each
   produce an agent with the same rehydrated attribute set. Compare the sets, do not spot-check.
7. **A failing rehydrator degrades, and says so.** One rehydrator raises; assert the others still
   ran, the agent is still onboarded, and an ERROR naming the rehydrator was logged.
8. **Idempotence.** Running `wire_agent` twice on the same instance produces one queue, one
   subscription, and no duplicate ticker.
9. **Per-class capability tests (Slice B).** One per post-wired class, exercising the capability the
   later wiring provides — not the presence of the attribute. Quartermaster: a reconcile that
   actually routes. Yeoman: a proactive scan that respects quiet hours. Counselor: an alert list
   that is non-empty for an agent at yellow.

### Mutation check (required)

Revert independently: (a) the rehydrator application loop in `wire_agent`, (b) the `shutdown()` in
`unregister_queue`, (c) the id-resolution in `BoardReconcilerTicker`. Confirm a **named** test
reddens for each. A test asserting on `hasattr(agent, "_reconciler")` will survive (c) — if a mutant
survives, suspect the test before congratulating the fix. Re-derive anchors after each repair round;
an anchor that no longer matches is an INERT mutant, not a kill.

---

## Do not build

- **Do not widen `_RECYCLE_CRITICAL_DEPS`.** The issue argues this at length and it is correct.
  Leave BF-808's reporting exactly as it is; it is honest about what it checks.
- **Do not make `AgentSpawner` aware of startup wiring.** The spawner's ignorance is the correct
  boundary — it builds agents, it does not know what the ship does with them. The fix belongs on the
  onboarding service, which already sits on all three paths.
- **Do not build a generic dependency-injection container or a service locator.** A reviewer
  proposing one is the signal to file it, not to build it inside this AD.
- **Do not change `ResourcePool`'s lifecycle-lock, rollback, or cancellation-shielding structure**
  (`pool.py:71-104`, `:200-244`). It is load-bearing and was hardened deliberately.
- **Do not touch the BF-824 health-loop boundary** (`pool.py:_health_loop`) or its residual. That
  residual is documented and filed separately.
- **Do not fix `finalize.py:2325`** (`agent = spawner.spawn("system_qa")` — a *fourth* producing
  path that bypasses pools and therefore bypasses onboarding entirely, and which does not `await`
  an async `spawn`). Verify the claim, note it in the commit, and **file it separately**. It is a
  different defect and this AD is already two slices.
- **Do not convert `ChatThreadStore` or any other store to async** as part of this.
- **Do not migrate more than one agent class per commit in Slice B.**

---

## Tracking

- `PROGRESS.md` — AD-1273 entry; BF-823 CLOSED only when Slice B lands.
- `docs/development/roadmap.md` Bug Tracker — BF-823 row.
- `DECISIONS.md` — AD-1273: the rehydrator rule and the owners-hold-ids rule. This one earns an
  entry; it is a standing constraint on every future startup wiring function.

---

## Acceptance criteria

- Recycling a `QuartermasterAgent` yields one whose `reconcile()` is not degraded.
- After a recycle, no external owner (ticker, closure, queue task) still references the stopped
  predecessor — asserted by identity.
- The cognitive queue exists, is bound to the replacement, and its bounds are **enforced** after a
  recycle; the predecessor's processor task is `done()`.
- All three producing paths yield the same rehydrated attribute set, proven by set comparison.
- Every per-instance startup wiring pass is either migrated to a rehydrator or classified in the
  commit message as one-time/type-level with its reason.
- One test per post-wired agent class, exercising the *capability* the later wiring provides.
- A failing rehydrator degrades with an ERROR naming it, and does not abort onboarding or kill the
  pool health task.
- Focused gate: `pytest tests/test_ad1273_*.py tests/test_bf808_*.py tests/test_ad876_*.py tests/test_ad654b_*.py tests/test_ad766_*.py tests/test_ad503_*.py -q -n 0`
- Then one consolidated gate for the frozen slice: `pytest tests/ -q -n 16 --dist=loadfile`
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
- Run the `Diff Reviewer` subagent on the staged diff with a different model than wrote the code.
  Tell it the consumer that must accept the change is *a recycled agent's next intent*, and point it
  at the live log.

---

## Verified Against Codebase (2026-08-26)

```
grep -n "_RECYCLE_CRITICAL_DEPS\|rehydration hook" src/probos/substrate/spawner.py
   78: _RECYCLE_CRITICAL_DEPS = ("_runtime", "_llm_client")
  105: "Making recycle whole needs a runtime-owned rehydration hook, tracked separately."
  116: for name in self._RECYCLE_CRITICAL_DEPS

grep -n "_notify_agent_spawned\|_spawn_kwargs\|_adopt_dynamic_agent" src/probos/substrate/pool.py
   61: async def _notify_agent_spawned(self, agent: BaseAgent) -> None:
   93: async def _adopt_dynamic_agent(self, agent: BaseAgent) -> None:
   97:     await self._notify_agent_spawned(agent)          # dynamic birth
  186:     agent_id, respawn=True, **self._spawn_kwargs     # BF-808
  209:     await self._notify_agent_spawned(new_agent)      # recycle
  279:     agent = await self.spawner.spawn(...)            # _start_inner: NO notify (see runtime:2358)
  367:     agent = await self.spawner.spawn(...)            # health refill -> _adopt_dynamic_agent
  443:     agent = await self.spawner.spawn(...)            # add_agent   -> _adopt_dynamic_agent

grep -n "on_agent_spawned\|onboarding.wire_agent" src/probos/runtime.py
 2343: on_agent_spawned=(self.onboarding.wire_agent ...)
 2348: on_agent_removing=(self.onboarding.unwire_agent ...)
 2357: await pool.start()
 2360: for agent in self.registry.get_by_pool(name):        # initial startup path
 2362:     await self.onboarding.wire_agent(agent)

grep -n "def wire_agent\|def unwire_agent" src/probos/agent_onboarding.py
  124: async def wire_agent(self, agent: Any) -> None:
  543: async def unwire_agent(self, agent_id: str) -> None:
  545:     await self._intent_bus.unsubscribe_and_wait(agent_id)

grep -n "unregister_queue\|def register_queue\|AgentCognitiveQueue(" src/ -r
  mesh/intent.py:772          self.unregister_queue(agent_id)   # in _unsubscribe_local
  mesh/intent.py:1358         def register_queue(...)
  mesh/intent.py:1362-1364    def unregister_queue(...): self._agent_queues.pop(agent_id, None)   # pop ONLY
  startup/finalize.py:4711    queue = AgentCognitiveQueue(      # the ONLY construction site
  startup/finalize.py:4717    _intent_bus.register_queue(agent.id, queue)
  -> no shutdown() anywhere; cognitive/queue.py:227 defines it, nothing calls it on unregister

grep -n "self._agent" src/probos/mesh/board_reconciler_ticker.py
   32: self._agent = agent            # holds the OBJECT
   83: await self._agent.reconcile()

grep -n "agent\._reconciler\|BoardReconcilerTicker(\|_on_agent_removed\|_counselor_alert_fn" src/probos/startup/finalize.py
 2578: agent._reconciler = reconciler          # ... through :2596, 12 private attrs
 2598: ticker = BoardReconcilerTicker(
 2611: async def _on_agent_removed(event)      # closes over `agent`
 2627: runtime.board_reactive_reclaim_handler = _on_agent_removed
 5255: await counselor_agent.initialize(
 5339: def _counselor_alert_fn()               # closes over `counselor_agent`

grep -n "await yeoman.initialize" src/probos/startup/agent_fleet.py
  219: await yeoman.initialize(                # post-construction, outside finalize entirely
```
