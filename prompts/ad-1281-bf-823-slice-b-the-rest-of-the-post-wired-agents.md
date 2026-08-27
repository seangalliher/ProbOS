# AD-1281 / BF-823 Slice B: the rest of the post-wired agents

**Issue:** BF-823 (#1287, OPEN) · **Repo:** OSS `d:\ProbOS`, branch `main`
**AD:** AD-1281 — newly minted. Ceiling was AD-1280 (`git log --all` + `prompts/ad-*.md`, both enumerated
2026-08-27; see *Verified Against Codebase*). **BF:** BF-823 — already allocated, do not mint a new one.
**Depends on:** AD-1273 Slice A, shipped as `9c7874eb` (gate 25,096). The rehydrator mechanism exists.
**Status:** ready to build · **Estimated tests:** 22–30 across nine commits

---

## What Slice A left behind

Slice A built the mechanism and used it once. `AgentOnboardingService.register_rehydrator(agent_type,
name, fn)` (`agent_onboarding.py:94`) stores into `self._rehydrators` (`:88`), and `_run_rehydrators`
(`:124`) is called at the end of `wire_agent` (`:599`). Exactly one rehydrator is registered today —
the crew cognitive queue, built by module-level `make_cognitive_queue_rehydrator(runtime, intent_bus)`
(`startup/finalize.py:3243`) and registered under the `"*"` wildcard at `finalize.py:4811-4813`.

Every other post-construction wiring pass still mutates a live agent behind onboarding's back. That is
Slice B, and it is what keeps #1287 open.

---

## The premise — and the correction you must make before you trust it

The Captain measured, driving `AgentSpawner.recycle`:

```
CONTROL constructor kwarg (_runtime) survived : True
BF-808 guard would report a loss              : False
_reconciler / _store / _router / _episodic / _skill_profile : ALL LOST
```

**That reproduction over-reports, and the last name proves it.** `_skill_profile` is not written by
startup at all — it is written inside `wire_agent` itself:

```
src/probos/agent_onboarding.py:238    _profile = await self._skill_bridge._service.get_profile(agent.id)
                            :239      agent._skill_profile = _profile
                            :241      agent._skill_profile = None     # except branch
```

A raw `AgentSpawner.recycle` drive never reaches `wire_agent`. The **real** recycle path does:
`ResourcePool._recycle_registered_agent_inner` (`pool.py:177`) → `_notify_agent_spawned`
(`pool.py:209` → `pool.py:61`) → `onboarding.wire_agent`. So on the path a live vessel actually takes,
`_skill_bridge`, `_skill_profile` and (since Slice A) the cognitive queue are **already restored**.

**Before writing a line of Slice B, re-run the premise through `ResourcePool`, not the spawner, and
paste the result.** The reproduction must carry two controls or it discriminates nothing:

| Control | Must show | Why |
|---|---|---|
| Positive | `_skill_profile` **survives** the pool-path recycle | proves the harness really went through `wire_agent`; if this is `False` you are still driving the spawner and every other reading is noise |
| Negative | `_reconciler` / `_store` / `_router` **still lost** | proves the defect is real on the path a vessel takes, not an artefact of the shortcut |

If the positive control fails, stop and fix the harness. A loss list gathered off the spawner path will
send you building rehydrators for state that already works — which is a worse outcome than the bug.

The static count stands regardless: **56** distinct post-construction attribute writes across
`startup/finalize.py`, `startup/agent_fleet.py` and `agent_onboarding.py`, against the **2** names
`_RECYCLE_CRITICAL_DEPS` guards (`spawner.py:78`).

**Do not widen `_RECYCLE_CRITICAL_DEPS`.** Slice A's prompt argues this and is right.

---

## Decision 1 — collaborators are built once at startup and captured by the rehydrator closure

Recorded here so it is not re-opened per commit.

The tension: a rehydrator receives only `agent`, but the collaborators these agents need are built inside
functions that early-return. `_wire_board_reconciler` (`finalize.py:2572`) has five gates; four are
**capability** gates (`cfg.enabled` `:2581`, `router` `:2584`, `store` `:2591`, `registry` `:2597`) and
one is a **timing** gate:

```
finalize.py:2613    agents = registry.get_by_pool("quartermaster")
           :2614    if not agents:
           :2615        logger.info(
           :2616            "AD-876: no quartermaster agent in pool; board reconciler skipped"
           :2617        )
           :2618        return False
```

**Ruling: hoist the registration above the timing gate and delete that gate. Keep the four capability
gates exactly as they are.** The collaborators are constructed once, at startup, and captured by the
closure — the shape Slice A already shipped for the queue.

Three reasons, in order of weight:

1. **The tree gets one pattern, not two.** `make_cognitive_queue_rehydrator(runtime, intent_bus)` is a
   module-level factory taking long-lived collaborators and returning a closure. A second, lazily
   self-constructing shape would mean the next reader has to work out which kind each rehydrator is.
2. **The timing gate is the only thing a rehydrator makes obsolete, and it is already in the wrong
   place.** `WorkItemReconciler` is constructed at `:2606-2609`, *above* the gate. So the reconciler
   already survives "no quartermaster yet". Only the assignment (`:2620-2637`) and the ticker (`:2640`)
   sit below it. Deleting the gate requires **no reordering of the reconciler construction at all** —
   it requires the ticker to stop needing an agent, which is Decision 2.
3. **It generalises where lazy construction does not.** Building a collaborator inside the rehydrator
   means a *new* collaborator per birth. For `WorkItemReconciler` specifically that would be harmless —
   it is stateless (`work_reconciler.py:38-40`: `registry` and `identity_registry`, nothing else) — and
   you should say so rather than claim a benefit this class does not provide. But the Counselor's
   `GuidedReminiscenceEngine` and the `ConcurrencyManager` are **not** stateless, and a per-birth rebuild
   would silently reset accumulated state on every recycle. One rule for all of them is cheaper than a
   per-collaborator judgement call.

**Reject** the third option (build unconditionally, no factory): it flips the meaning of
`_wire_board_reconciler`'s `bool` return, which `finalize.py:4876` consumes as a wiring signal.

---

## Decision 2 — the `BoardReconcilerTicker` constructor change is REQUIRED

**Ruling: required, and mandated by AD-1273's own standing rule, not a convenience.**

AD-1273 Half 2: *"any owner that outlives an agent instance holds the agent id, never the agent."*
The ticker holds the object:

```
src/probos/mesh/board_reconciler_ticker.py:29    agent: Any,
                                          :32    self._agent = agent
                                          :83    await self._agent.reconcile()
```

Slice A did not touch it. Two consequences, either one sufficient:

- After a recycle the ticker calls `reconcile()` on the stopped predecessor. That is not a degraded
  agent — it is a *second* agent, unregistered, doing board work nobody can see.
- With the timing gate deleted (Decision 1) there is no agent to hand the constructor at startup on a
  vessel whose quartermaster arrives later. Keeping `agent=` reintroduces the gate one layer down.

**Take `registry` + `pool`, not `agent_id`.** The agent id is no more knowable at startup than the agent
is, so `agent_id=` does not actually solve the second consequence. The board's owner is the quartermaster
*billet*, and `pool` is the stable handle for a billet:

```python
def __init__(
    self,
    *,
    registry: Any,
    pool: str,
    interval_seconds: int,
    warm_boot: bool,
    startup_delay: float = 10.0,
) -> None:
```

`_safe_reconcile` resolves `registry.get_by_pool(self._pool)` per tick and **logs-and-skips on a miss**
(Tier 2 — a missing quartermaster is a degraded sweep, not a dead cadence loop). Keep the existing
`except Exception` sweep guard at `:84-90` unchanged.

### Named tests that must be UPDATED, not softened

All in `tests/test_ad876_reconciler_wiring.py`. Record the old assertion inline as a comment naming
AD-1281 and why it changed. Deleting any of these is a review blocker.

| Line | Test | Change required |
|---|---|---|
| `:204-205` | `test_ticker_start_holds_task_reference` | constructor kwargs |
| `:220-221` | `test_ticker_warm_boot_reconciles_once` | constructor kwargs; needs a stub registry resolving to the agent |
| `:234-235` | `test_ticker_stop_cancels_cleanly` | constructor kwargs |
| `:269-270` | `test_warm_boot_integration_redispatches_stranded` | constructor kwargs |
| `:186` | `test_wire_missing_agent_returns_false` | **inverts.** This test pins the deleted timing gate as the contract. It must now assert `_wire_board_reconciler` returns `True` and that the rehydrator is registered, with the old `False` expectation recorded inline. |
| `:161` | `test_wire_enabled_injects_and_sets_ticker` | assert injection happens via the rehydrator, not inline |

**`:213` is NOT affected.** `src = inspect.getsource(BoardReconcilerTicker.start)` scans `.start`, which
this change does not touch. Do not "fix" it. Slice A's builder flagged this file as source-scanning
`.start` and that flag is correct but narrower than it sounds.

---

## Decision 3 — one **rehydrator** per commit (the rule is kept, and restated)

Slice A's prompt said "one agent class per commit". Keep the constraint, restate the unit: **one
rehydrator per commit**. "Agent class" does not cover the three cross-class passes below, and those are
the ones most likely to be skipped.

The value of the rule is attribution: a mutation that survives must point at one commit. Build in this
order — the first commit is the only one that changes a public constructor and deletes a gate, so it goes
while the tree is otherwise quiet.

| # | Rehydrator | Sites | Notes |
|---|---|---|---|
| 1 | `quartermaster_board_wiring` | `finalize.py:2613-2664` | ticker constructor + gate deletion + reactive-reclaim closure `:2653` |
| 2 | `counselor_activation` | `finalize.py:5367-5408`, alert closure `finalize.py:5456-5459` | `initialize` `:5372` + reminiscence `:5400` + Half 2 closure |
| 3 | `yeoman_captain_card` | `agent_fleet.py:217-240` | `await yeoman.initialize(...)` at `:219` |
| 4 | `concurrency_manager` | `finalize.py:5191-5208` | cross-class, crew-gated |
| 5 | `consultation_protocol` | `finalize.py:5173-5178` | cross-class, crew-gated. **Not in the brief — found during verification.** |
| 6 | `strategy_advisor` | `agent_fleet.py:404-410` | cross-class. **Not in the brief — found during verification.** |
| 7 | `cognitive_skill_catalog` | `finalize.py:4990-4992` | `_agent._cognitive_skill_catalog = ...`. **Not in the brief.** Note the existing `if not getattr(...)` guard — it is already idempotent, carry it over verbatim. |
| 8 | `sub_task_executor` | `finalize.py:5135-5137` | `_agent.set_sub_task_executor(executor)`, crew-gated. **Not in the brief.** |
| 9 | `codebase_skills` | `agent_fleet.py:385-387`, `:396-398` | two `agent.add_skill(...)` passes over `pool.healthy_agents`. **Not in the brief.** Confirm `add_skill` is idempotent for a repeated skill before registering; if it is not, guard by skill name inside the rehydrator rather than changing `add_skill`. |

The brief named two cross-class passes. Verification found **seven**. That is the classification lesson
landing in real time: a pass skipped because it looked one-time is exactly the shape of this bug. Assume
the table above is still incomplete and run the enumeration below.

`finalize.py:5556` (`agent._working_memory = restored_wm`, AD-573) is **deliberately excluded** — see
the classification table. Justify or overturn that call in the commit message.

Each commit: rehydrator + its own test file + focused gate + scoped `Diff Reviewer` pass. Accumulate
locally; one consolidated full gate for the frozen batch.

---

## Re-verify the classification before trusting it

Slice A's builder classified several registry passes as one-time/type-level. **Every line number in that
classification has drifted** — Slice A's own commit inserted `make_cognitive_queue_rehydrator` at
`finalize.py:3243` and pushed everything below it down ~18 lines. Re-derive, do not trust:

| Claimed | Live | Content | Ruling |
|---|---|---|---|
| `:4916` | **`:4934`** | `runtime._comm_profiles[agent.id] = profile` | **one-time.** Keyed by `agent.id` on `runtime`, and a recycle preserves the id (`pool.py:186` respawns `agent_id`). Survives. |
| `:5268` | **`:5286`** | `_on_game_completed` iterates `registry.all()` | **one-time.** Inside an event handler — resolved at event time. |
| `:5556` | **`:5556`** | `agent._working_memory = restored_wm` | **gated, not per-instance.** The whole block is `if runtime._lifecycle_state == "stasis_recovery"` (`:5525`). A recycle mid-session is not a stasis resume, and re-restoring a frozen snapshot over live working memory would *lose* work. Leave alone; say this in the commit. |
| `:5582` | **`:5574`** | `CognitiveAgent.evict_cache_for_type(agent.agent_type)` | **type-level.** Per-*type* cache. |
| — | **`:5600`** | warm-boot orientation loop | **read-only briefing.** |
| `:5705` | **`:5723`** | `consumer.register_observer(agent.id)` | **already the target pattern.** Registers an id. |
| — | **`:5854`** | `PerceptionModeController(agent_id=_agent.id)` → `_registry.register(_agent.id, _per_ctrl)` (`:5884`, `:5888`) | **already the target pattern.** Holds the id, not the agent. |

Run both of these yourself and paste them, then classify anything the table misses — the `_agent` spelling
is a separate loop variable and the second command searches a different collection entirely:

```
rg -n "for agent in runtime\.registry\.all\(\)|for _agent in runtime\.registry\.all\(\)" src/probos/startup/
rg -n "for agent in pool\.healthy_agents" src/probos/startup/
```

---

## Required tests

New files, one per commit: `tests/test_ad1281_quartermaster_rehydration.py`,
`tests/test_ad1281_counselor_rehydration.py`, `tests/test_ad1281_yeoman_rehydration.py`,
`tests/test_ad1281_cross_class_rehydration.py`.

1. **Capability, not attribute presence.** For each migrated class, assert the capability the wiring
   provides survives a pool-path recycle — Quartermaster: a `reconcile()` that actually routes and is
   **not** degraded. Counselor: `agents_at_alert("yellow")` (`counselor.py:743`) non-empty for an agent
   at yellow. Yeoman: a proactive scan that respects quiet hours. `hasattr(agent, "_reconciler")` passes
   against a corpse and proves nothing.
2. **The ticker resolves the replacement.** After a recycle, the ticker's resolved agent `is` the
   registry's current instance and `is not` the stopped predecessor. **Identity**, not equality.
3. **The deleted gate.** `_wire_board_reconciler` with an empty quartermaster pool returns `True`,
   registers the rehydrator, and the agent is fully wired when it is born later. This is the test that
   replaces `:186`.
4. **Ticker miss degrades.** With no agent in the pool, one tick logs and the loop survives to the next.
5. **All three producing paths agree.** Initial startup, recycle, and `add_agent` produce the same
   rehydrated attribute set. Compare the **sets**; do not spot-check.
6. **Cross-class gating holds.** A non-crew agent gets no `ConcurrencyManager`, no
   `ConsultationProtocol` and no `SubTaskExecutor` after rehydration — the `is_crew_agent` guard must
   move with the code, not be dropped in transit.
7. **Idempotence.** `wire_agent` twice on one instance yields one ticker, one manager, one subscription.
8. **The positive control from the premise section, as a permanent test.** `_skill_profile` survives a
   pool-path recycle. This is the assertion that stops a future harness from silently reverting to the
   spawner path.

### Mutation check (required) — with a null control

Revert independently and confirm a **named** test reddens for each: (a) the rehydrator registration in
each of the nine commits, (b) the per-tick resolution in `BoardReconcilerTicker._safe_reconcile`, (c) the
`is_crew_agent` guard in commits 4, 5 and 8.

**Include a semantically neutral NULL CONTROL that must SURVIVE.** Without one, "all killed" cannot be
distinguished from a harness whose anchors never applied. Suggested: rename a local variable inside a
rehydrator body, or reorder two independent assignments.

Harness rules for this CRLF tree:

- **Single-line anchors, binary I/O.** Detect `\r\n` vs `\n` from the file bytes.
- **Build the anchor as `EOL + line + EOL`.** An indented anchor is also a *suffix* of any more-indented
  line with the same tail — an 8-space anchor matches inside a 16-space line. This has produced a false
  INERT in this repo already.
- **An anchor matching 0 or 2+ times is INERT, not killed.** Report it as INERT and say so.
- **Run the unmutated baseline FIRST.** Abort if it is already red.
- **Mutate in place** with a `.mutbak` sibling, restore in `finally`. A copied tree is inert under an
  editable install.
- **A timeout banner is INVALID, never SURVIVED.**
- **A surviving mutant may mean the MUTANT is wrong, not the test.** Check the mutant actually reaches
  the behaviour it claims to break before concluding a test is weak.

### Test-double sweep (required, before the broad gate)

Both of these cost a full 21-minute gate this week. Do them *before* spending one.

- **After adding any `__init__` state** (e.g. `BoardReconcilerTicker._registry` / `._pool`):
  `grep -rn '__new__(BoardReconcilerTicker)' tests/` and the same for every class you touch. A double
  built via `__new__` bypasses `__init__` and will not have the new attribute. **Fix the double, not
  production** — making production `getattr`-defensive lets an incomplete double hide real defects.
- **After renaming a method on a faked interface:** grep the whole test tree for classes defining the
  **old** name that do not define the new one. A double *less* capable than production hides defects
  exactly as reliably as one that is *more* capable.

---

## Do not build

- **Do not widen `_RECYCLE_CRITICAL_DEPS`** (`spawner.py:78`). Leave BF-808's reporting as is.
- **Do not make `AgentSpawner` aware of startup wiring.** The fix belongs on the onboarding service,
  which already sits on all three producing paths.
- **Do not build a dependency-injection container or service locator.** A reviewer proposing one is the
  signal to file it, not to build it here.
- **Do not change `ResourcePool`'s lifecycle-lock, rollback, or cancellation-shielding structure**
  (`pool.py:71-104`, `:177-244`). Load-bearing and deliberately hardened.
- **Do not touch the BF-824 health-loop boundary** or its documented residual.
- **Do not migrate `finalize.py:5556`** (AD-573 working-memory restore). Stasis-gated; re-running it on a
  recycle would overwrite live working memory with a frozen snapshot.
- **Do not touch `tests/test_ad876_reconciler_wiring.py:213`** — it scans `.start`, not `__init__`.
- **Do not change the Slice A queue rehydrator** (`finalize.py:3243`, registration `:4811`). It shipped
  and is gated.
- **Do not fix `finalize.py:2325`** (`spawner.spawn("system_qa")` — a fourth producing path that bypasses
  pools and onboarding entirely). Verify, note it in the commit, file it separately.
- **Do not combine commits.** One rehydrator per commit, in the order above.
- **Do not regenerate** `docs/development/ad-ledger-snapshot.json` or `open-ads-report.md`. Both were
  regenerated and committed on 2026-08-27.

---

## Tracking

- `PROGRESS.md` — AD-1281 entry; **BF-823 CLOSED** once all nine commits land (Slice B completes #1287).
- `docs/development/roadmap.md` Bug Tracker — BF-823 row. **This file has uncommitted hand edits from
  another session — do not stage it as part of a source commit.**
- `DECISIONS.md` — AD-1281: Decisions 1 and 2 above. Decision 2 is a standing constraint on every future
  cadence ticker: a ticker holds a billet, never an instance.

---

## Acceptance criteria

- The premise reproduction runs through `ResourcePool`, its positive control (`_skill_profile` survives)
  passes, and its result is pasted into the first commit message.
- All nine rehydrators registered; each in its own commit with its own test file.
- `_wire_board_reconciler` returns `True` with an empty quartermaster pool, and the agent is fully wired
  when born later.
- `BoardReconcilerTicker` takes `registry` + `pool` and resolves per tick; all six affected tests in
  `test_ad876_reconciler_wiring.py` updated with the old assertion recorded inline.
- Every registry/pool pass in `startup/` is either migrated or classified in a commit message with its
  reason and its **live** line number.
- Mutation run includes a null control that SURVIVED; every INERT anchor reported as INERT.
- Test-double sweep run and its output pasted, before the broad gate.
- Focused gate per commit: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1281_*.py tests/test_ad1273_*.py tests/test_ad876_*.py tests/test_ad766_*.py tests/test_ad503_*.py tests/test_bf808_*.py -q -n 0`
- One consolidated gate for the frozen batch, run synchronously with no timeout (~15–19 min; it sits at
  `[ 99%]` for several of them — that is normal):
  ```
  cd d:\ProbOS
  $env:PROBOS_DATA_DIR="$env:TEMP\probos_gate_ad1281"
  d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile
  ```
  Baseline: **25,096 passed, 27 skipped**. Any source or test edit after the gate invalidates it — rerun.
- Run the `Diff Reviewer` subagent on each staged diff with a **different model than wrote the code**.
  Tell it the consumer that must accept the change is *a recycled agent's next intent*, and point it at
  the live log (`%LOCALAPPDATA%\ProbOS\data`, **not** `d:\ProbOS\data` — that path is a stale decoy).
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

### Commit hygiene

- `git add <explicit path>` only. **Never `git add -A`.**
- **Never stage:** `README.md`, `docs/architecture/federation.md`, `docs/development/roadmap.md` — hand
  edits from another session. `docs/development/ad-ledger-snapshot.json` and `open-ads-report.md` were
  just regenerated and committed; leave them alone.
- Commit messages must **not** contain `close`/`closes`/`fixes`/`resolves` next to `#1287`. Reference it
  as `BF-823 (#1287)`.

---

## Verified Against Codebase (2026-08-27)

Every line number below was read at HEAD today. Slice A's commit shifted `finalize.py` by ~18 lines
below `:3243`; the brief's numbers were pre-shift and have been corrected throughout.

```
AD ceiling — two independent enumerations, both give 1280
  git log --all --format='%s' | Select-String 'AD-1(2[5-9][0-9])'
    -> highest: "AD-1280 / BF-787: the mesh path leaves a record too"
  Get-ChildItem prompts -Filter 'ad-12*'
    -> highest: ad-1280-bf-787-the-mesh-path-leaves-a-record-too.md
  => next is AD-1281

Slice A shipped — the mechanism exists
src/probos/agent_onboarding.py
   88: self._rehydrators: dict[tuple[str, str], Callable[[Any], Awaitable[None]]] = {}
   94: def register_rehydrator(
  118: self._rehydrators[(agent_type, name)] = fn
  124: async def _run_rehydrators(self, agent: Any) -> None:
  178: async def wire_agent(self, agent: Any) -> None:
  238: _profile = await self._skill_bridge._service.get_profile(agent.id)
  239: agent._skill_profile = _profile          <-- premise correction: written HERE, not in startup
  241: agent._skill_profile = None
  599: await self._run_rehydrators(agent)
  601: async def unwire_agent(self, agent_id: str) -> None:

src/probos/startup/finalize.py
 2572: def _wire_board_reconciler(*, runtime: Any, config: "SystemConfig") -> bool:
 2606: reconciler = WorkItemReconciler(              <-- ABOVE the timing gate already
 2613: agents = registry.get_by_pool("quartermaster")
 2614: if not agents:
 2618:     return False                              <-- the timing gate to delete
 2620: agent._reconciler = reconciler                <-- 12 private attrs, :2620-2637
 2640: ticker = BoardReconcilerTicker(
 2641:     agent=agent,
 2653: async def _on_agent_removed(event: Any) -> None:   <-- Half 2 closure over `agent`
 2657:     await agent.reconcile_for_agent(agent_id)      <-- the corpse call
 3243: def make_cognitive_queue_rehydrator(          <-- Slice A, module level
 4808: _rehydrate_cognitive_queue = make_cognitive_queue_rehydrator(
 4811: runtime.onboarding.register_rehydrator("*", "ad654b_cognitive_queue", ...)
 4876: if _wire_board_reconciler(runtime=runtime, config=config):   <-- consumes the bool
 4934: runtime._comm_profiles[agent.id] = profile    (was cited :4916)
 4990: for _agent in runtime.registry.all():         <-- AD-596b catalog, NOT in brief
 4991:     if not getattr(_agent, '_cognitive_skill_catalog', None):
 4992:         _agent._cognitive_skill_catalog = runtime.cognitive_skill_catalog
 5135: for _agent in runtime.registry.all():         <-- AD-632e sub-task, NOT in brief
 5136:     if is_crew_agent(_agent, runtime.ontology):
 5137:         _agent.set_sub_task_executor(executor)
 5173: for _agent in runtime.registry.all():         <-- AD-594 consultation, NOT in brief
 5177:     _agent.set_consultation_protocol(consultation_protocol)
 5191: for agent in runtime.registry.all():          <-- AD-672 concurrency
 5194:     if not hasattr(agent, "set_concurrency_manager"):
 5208:     agent.set_concurrency_manager(manager)
 5286: for agent in runtime.registry.all():          <-- _on_game_completed (was cited :5268)
 5372: await counselor_agent.initialize(
 5400: counselor_agent.set_reminiscence_engine(reminiscence_engine)
 5456: def _counselor_alert_fn() -> list:            <-- Half 2 closure over counselor_agent
 5525: if (runtime._lifecycle_state == "stasis_recovery"   <-- gates the :5556 block
 5556: agent._working_memory = restored_wm
 5574: _evicted = CognitiveAgent.evict_cache_for_type(agent.agent_type)   (was :5582)
 5600: for agent in runtime.registry.all():          <-- warm-boot orientation, read-only
 5723: consumer.register_observer(agent.id)          (was cited :5705)
 5854: for _agent in runtime.registry.all():         <-- AD-733c-5 perception controller
 5884:     agent_id=_agent.id,
 5888:     _registry.register(_agent.id, _per_ctrl)  <-- id-keyed; already target pattern

src/probos/startup/agent_fleet.py
  217: yeoman = yeo_agents[0]
  219: await yeoman.initialize(
  385: for agent in pool.healthy_agents:             <-- AD-307 codebase skill, NOT in brief
  387:     agent.add_skill(codebase_skill)
  396: for agent in pool.healthy_agents:             <-- architect codebase skill, NOT in brief
  398:     agent.add_skill(_cb_skill)
  404: if strategy_advisor:                          <-- AD-384 strategy advisor, NOT in brief
  407:     for pool in pools.values():
  410:         agent.set_strategy_advisor(strategy_advisor)

src/probos/mesh/board_reconciler_ticker.py
   24: def __init__(
   29:     agent: Any,
   32: self._agent = agent
   40: def start(self) -> None:
   80: async def _safe_reconcile(self) -> None:
   83:     await self._agent.reconcile()

src/probos/cognitive/work_reconciler.py
   38: def __init__(self, *, registry: Any, identity_registry: Any | None = None) -> None:
   39: self._registry = registry
   40: self._identity_registry = identity_registry    <-- stateless; see Decision 1 reason 3

src/probos/substrate/pool.py
   61: async def _notify_agent_spawned(self, agent: BaseAgent) -> None:
   94: async def _adopt_dynamic_agent(self, agent: BaseAgent) -> None:
  177: async def _recycle_registered_agent_inner(self, agent_id: AgentID) -> None:
  209: await self._notify_agent_spawned(new_agent)    <-- the REAL recycle path reaches wire_agent

src/probos/cognitive/cognitive_agent.py
 1443: def set_strategy_advisor(self, advisor) -> None:
 1464: def set_consultation_protocol(self, protocol: Any) -> None:
 1470: def set_concurrency_manager(self, manager: ConcurrencyManager) -> None:

src/probos/cognitive/counselor.py
  637: async def initialize(
  743: def agents_at_alert(self, level: str = "yellow") -> list[CognitiveProfile]:
 2546: def set_reminiscence_engine(self, engine: Any) -> None:

src/probos/cognitive/yeoman.py
  199: async def initialize(

tests/test_ad876_reconciler_wiring.py — the ONLY file referencing BoardReconcilerTicker
  161: async def test_wire_enabled_injects_and_sets_ticker(store)
  186: async def test_wire_missing_agent_returns_false(store)   <-- INVERTS
  204: ticker = BoardReconcilerTicker(agent=agent, ...)
  213: src = inspect.getsource(BoardReconcilerTicker.start)     <-- NOT affected
  220: ticker = BoardReconcilerTicker(agent=agent, ...)
  234: ticker = BoardReconcilerTicker(agent=agent, ...)
  269: ticker = BoardReconcilerTicker(agent=qm, ...)
```

### Absence verified (2026-08-27)

```
CLAIM: BoardReconcilerTicker is referenced by exactly one test file
RUN:   Get-ChildItem tests -Filter '*.py' -Recurse | Select-String 'BoardReconcilerTicker' -List
FOUND: tests/test_ad876_reconciler_wiring.py  (only)
HOLDS: yes — the constructor change's test blast radius is one file

CLAIM: _skill_profile is written only inside agent_onboarding, never by startup
RUN:   Select-String -Path src\probos\startup\*.py,src\probos\agent_onboarding.py -Pattern '_skill_profile'
FOUND: agent_onboarding.py:239, agent_onboarding.py:241  (zero hits in startup/)
HOLDS: yes — this is what invalidates the raw-spawner reproduction

CLAIM: exactly one rehydrator is registered today
RUN:   Select-String -Path src\probos\startup\finalize.py -Pattern 'register_rehydrator'
FOUND: finalize.py:4811  (only)
HOLDS: yes — Slice B is all nine remaining

CLAIM: the brief's list of cross-class passes was complete
RUN:   Select-String src\probos\startup\finalize.py -Pattern 'for _?agent in runtime\.registry\.all\(\)'
       Select-String src\probos\startup\agent_fleet.py -Pattern 'for agent in pool\.healthy_agents'
FOUND: finalize.py 4817, 4823, 4934, 4990, 5135, 5173, 5191, 5286, 5534, 5574, 5600, 5723, 5854
       agent_fleet.py 385, 396, 408
HOLDS: NO — the brief named 2 cross-class passes; the enumeration found 7. This is why the
       classification table above must be re-derived rather than inherited.
```
