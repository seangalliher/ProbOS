# Epic AD-874 → AD-876: Work-Board Reconciliation — the Quartermaster utility agent

**Status:** Architect-drafted, verify-first. Ready for per-AD review → Builder.
**Repo:** OSS (`d:\ProbOS`). This describes *how the product works* (board self-healing), not how it makes money.
**Highest committed AD at draft time: AD-873.** This epic reserves **AD-874 → AD-876** sequentially.
**GitHub issue:** [#846](https://github.com/seangalliher/ProbOS/issues/846).

---

## Why this epic exists

The work board has **no process that reviews what is on it and (re)assigns/(re)dispatches a task.**
The AD-581a [`WorkItemRouter`](../src/probos/mesh/work_item_router.py) dispatches **exactly once**, on
`WORK_ITEM_CREATED` — its own docstring scopes out *"TaskEvent on WORK_ITEM_UPDATED (only
WORK_ITEM_CREATED)"* and *"Cross-process / federation routing [out of scope]."* If that single dispatch
does not land on a **live** agent — restart, boot race, a capability-gap `blocked → in_progress` resume,
or the assignee's slot not being re-spawned that boot — the item sits on the board forever. There are
reapers for attachments, sessions, and recordings, but **nothing for the work board.**

This produced two Captain-reported stuck tasks in two days (`1e0ffcdb7b57`, `91de77938fd1`), each
requiring manual out-of-band cancellation via the live API. BF-606/607/608 closed the *write-side*
contradictions (a task can no longer enter `in_progress` while `Unassigned`), but nothing **heals** an
already-stranded item.

### The identity nuance that makes this tractable

`WorkItem.assigned_to` stores the **deterministic slot ID** (AD-177, e.g.
`counselor_counselor_0_67c601cb` = `{type}_{pool}_{index}_{sha256(type:pool:index)[:8]}`). That ID is
**stable by formula across restarts** — the 404 we observed was a *liveness* miss (the agent was not in
`runtime.registry` that boot), **not** identity churn. Meanwhile AD-441 gave every agent a permanent
**sovereign DID** (`did:probos:{instance_id}:{agent_uuid}`) and an `AgentIdentityRegistry` with a
`slot_mappings` table (slot_id ↔ agent_uuid) explicitly *"for restart persistence."* So the durable
anchor already exists — it was just never wired into the assignment/dispatch subsystem (AD-441 deferred
the `sovereign_id` migration to *"future ADs"* and the workforce subsystem was never migrated).

**The design:** a deterministic resolver that, given a stranded item's `assigned_to`, decides whether a
**live** agent can serve it (slot → sovereign DID via the identity registry → live agent; or re-resolve a
same-role/department peer), and a **Utility-tier agent** — the **Quartermaster** — that periodically (and
once at warm boot) reviews the board and re-dispatches or re-binds stranded work through the existing
`WorkItemRouter` path.

```
warm boot / interval tick ─▶ reconcile_board intent ─▶ Quartermaster (utility agent)
   perceive:  scan board for stranded items (dispatchable, not-terminal, assignee-not-live)   ← AD-875
   decide:    WorkItemReconciler.classify(item) → {live_redispatch | rebind | clear_reroute}  ← AD-874
   act:       re-dispatch via WorkItemRouter.dispatch_work_item(...) / unassign + re-route     ← AD-875
   report:    episode + event log                                                              ← AD-875
trigger + wiring (config-gated ticker, pool, finalize.py)                                       ← AD-876
```

---

## Tier & architecture rationale (binding for the whole epic)

- **Utility tier, deterministic.** The Quartermaster is a plain `BaseAgent` (mirror
  [`IntrospectionAgent`](../src/probos/agents/introspect.py) / `SystemQAAgent`), `tier = "utility"`.
  **No LLM in the reconcile path** — re-dispatch is a safety-critical liveness lookup, not a reasoning
  task. It must be deterministic and cheap. (Do **not** subclass `CognitiveAgent`.)
- **The agent is the action surface; the decision is a pure service.** Resolution/classification lives in
  a focused, side-effect-free `WorkItemReconciler` (AD-874) with constructor injection (Dependency
  Inversion). The agent (AD-875) composes it.
- **Re-dispatch reuses the create path (Open/Closed).** Do not fork dispatch logic. AD-874 refactors a
  reusable `WorkItemRouter.dispatch_work_item(work_item_dict)` out of `on_work_item_created` so both the
  create-listener and the Quartermaster drive the **identical** route → TaskEvent → dispatcher flow.
  **Hard dependency:** `runtime.work_item_router` is only built inside `_wire_hybrid_dispatch` when
  `config.hybrid_dispatch.enabled` is true (`finalize.py:1835`). The reconciler therefore **requires
  `hybrid_dispatch` enabled** — AD-876's gate must treat `getattr(runtime,"work_item_router",None)` as a
  hard, skip-and-log dependency, and the config docstring must say so.
- **The agent stays intent-driven (no rogue loop).** The cadence is a tiny config-gated ticker (AD-876)
  that emits the `reconcile_board` intent — the agent reacts to a tick like every other agent reacts to
  intents. No `while True` inside the agent (async-hygiene; the ticker holds its own task ref).
- **Fail Fast → log-and-degrade everywhere.** A reconcile pass must NEVER raise into the ticker, the
  intent bus, or startup. Missing dependency → INFO log + no-op. A single un-resolvable item must not
  abort the sweep.
- **Minimal Authority / Safety Budget.** The Quartermaster only re-dispatches **dispatchable,
  non-terminal** items, and only **clears** an assignee that resolves to no live agent. It never assigns a
  destructive/consensus-gated item to a new owner without going through the normal router decision. It
  never touches `done`/`failed`/`cancelled` items.
- **No MagicMock at substrate/storage boundaries (BF-287).** Tests use a **real** `WorkItemStore`
  (`tmp_path`), **real** `AgentRegistry`, **real** `AgentIdentityRegistry`. Fakes only for the
  dispatcher/router collaborator where needed.

Every build prompt in this epic must include in its acceptance criteria:
> **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified collaborator APIs (confirmed against HEAD — grep before quoting if drifted)

- `WorkItemStore.list_work_items(status=None, assigned_to=None, work_type=None, parent_id=None, priority=None, tags=None, limit=50, offset=0) -> list[WorkItem]` (`src/probos/workforce.py:1088`).
- `WorkItemStore.get_work_item(id) -> WorkItem | None` (workforce.py:1076).
- `WorkItemStore.update_work_item(id, **updates) -> WorkItem | None` — `assigned_to` is mutable (not in `_IMMUTABLE_FIELDS = {"id","created_at","created_by"}`).
- `WorkItemStore.unassign_work_item(id, reason="") -> bool` — resets `assigned_to` to NULL, cancels active bookings (workforce.py:1398).
- `WorkItem.to_dict()` (workforce.py:610+) — the dict shape the router consumes (`id`, `title`, `description`, `work_type`, `status`, `assigned_to`, `priority`, `tags`, `metadata`, …).
- `WorkItemRouter.on_work_item_created(event: dict) -> None` (mesh/work_item_router.py) — envelope shape `{"data": {"work_item": item.to_dict()}}`. `is_dispatchable(work_item_dict) -> bool` reads `dispatchable_tags`/`metadata["dispatchable"]`.
- `AgentRegistry.get(id) -> BaseAgent | None`, `.all() -> list[BaseAgent]`, `.get_by_pool(pool) -> list[BaseAgent]` (substrate/registry.py:51/64/54). `BaseAgent.id`, `.agent_type`, `.pool`.
- `AgentIdentityRegistry.get_by_slot(slot_id) -> AgentBirthCertificate | None` (identity.py:668); cert has `.agent_uuid`, `.did`. `slot_mappings` table maps slot_id ↔ agent_uuid.
- `runtime.identity_registry`, `runtime.work_item_store`, `runtime.work_item_router`, `runtime.registry`, `runtime.emit_event`, `runtime.add_event_listener` (all public attrs wired in `startup/finalize.py` / `startup/communication.py`).
- Utility-agent precedent: `IntrospectionAgent` (`tier="utility"`, deterministic `handle_intent` → `perceive/decide/act/report`); pool created in `startup/agent_fleet.py:58-60` via `generate_pool_ids` + `create_pool_fn`.
- Reaper-task precedent (ticker pattern): `AttachmentReaper` (`src/probos/attachments/reaper.py`) — `start()` spins one named task holding its ref, `_loop()` does `while`-`asyncio.sleep(interval)`, `stop()` cancels. Config gate beside `HybridDispatchConfig` (config.py:4493) / `_wire_hybrid_dispatch` (finalize.py:1792).

---

## AD-874 — `WorkItemReconciler`: deterministic stranded-item classifier + reusable re-dispatch

**Goal:** A pure, side-effect-free service that (a) resolves an item's `assigned_to` to a **live** agent
(slot → sovereign DID → live agent), and (b) classifies a board item into a reconcile action. Plus a
small Open/Closed refactor so re-dispatch reuses the create path.

**Files:**
- `src/probos/mesh/work_item_router.py` — extract `dispatch_work_item(work_item_dict: dict) -> None` from `on_work_item_created` (the existing body minus the envelope unwrap); `on_work_item_created` becomes `unwrap envelope → self.dispatch_work_item(wi)`. **No behavior change** for the create path.
- `src/probos/cognitive/work_reconciler.py` — **new** module (Cognitive layer; pure decision).

**Design (constructor injection):**
```python
@dataclass(frozen=True)
class ReconcileDecision:
    work_item_id: str
    action: str          # "live_redispatch" | "clear_and_reroute" | "skip"
    assignee: str | None # current assigned_to
    resolved_agent_id: str | None  # live agent the assignee maps to, else None
    reason: str          # "assignee_live" | "assignee_not_live" | "unassigned_dispatchable"
                         # | "terminal" | "not_dispatchable" | "in_progress_live_owner" | ...

class WorkItemReconciler:
    def __init__(self, *, registry, identity_registry=None) -> None: ...
    def resolve_live_agent(self, assigned_to: str | None) -> str | None: ...
    def classify(self, work_item_dict: dict, *, is_dispatchable: bool) -> ReconcileDecision: ...
```

**`resolve_live_agent(assigned_to)` (pure):**
1. `None`/empty → `None`.
2. `registry.get(assigned_to) is not None` → return `assigned_to` (the slot ID is itself live — common case).
3. Else, if `identity_registry` is wired: `cert = identity_registry.get_by_slot(assigned_to)`; if a cert exists, scan `registry.all()` for a live agent whose own `get_by_slot(agent.id).agent_uuid == cert.agent_uuid` (same sovereign identity, possibly a re-spawned slot) → return that `agent.id`.
4. No live match → `None`. (Honest-degrade; never raise — wrap in try/except, log Tier-2, return `None`.)
   **Note (forward-proofing, not hot-path):** under the current deterministic slot formula (AD-177,
   `generate_agent_id` excludes `instance_id`) a re-spawned same-role agent keeps the **same** slot ID, so
   step 2 already resolves the common case. Step 3 (sovereign-DID re-resolution) only fires when the same
   sovereign identity moves to a *different* slot ID — which cannot happen until the AD-441 `sovereign_id`
   migration lands. Keep it, **explicitly labelled as the AD-441 seam**, because it is the exact hook that
   migration will use; it is cheap (O(N) only on the dead-assignee branch) and harmless today.

**`classify(work_item_dict, *, is_dispatchable)` (pure):**
- `status in {"done","failed","cancelled"}` → `action="skip"`, reason `"terminal"`.
- `not is_dispatchable` → `action="skip"`, reason `"not_dispatchable"`.
- `assigned_to` empty AND status `open` → `action="live_redispatch"`, reason `"unassigned_dispatchable"` (router will pick a live agent).
- `assigned_to` set → `resolved = resolve_live_agent(assigned_to)`:
  - resolved is not None AND status `in_progress` → `action="skip"`, reason `"in_progress_live_owner"` (owner is alive and working; don't disturb).
  - resolved is not None AND status `open` → `action="live_redispatch"`, reason `"assignee_live"`.
  - resolved is None → `action="clear_and_reroute"`, reason `"assignee_not_live"` (stale binding; unassign + re-dispatch).
- Anything else → `action="skip"`, reason `"no_action"`.

**Acceptance criteria:**
- `tests/test_ad874_work_reconciler.py` (≥12): real `AgentRegistry` + real `AgentIdentityRegistry` (BF-287). Cover: assignee-is-live slot returns itself; assignee dead but sovereign DID maps to a re-spawned live slot → returns the new id; assignee dead, no cert → None; unassigned open → `live_redispatch`; live owner in_progress → `skip`; dead assignee → `clear_and_reroute`; terminal → `skip`; non-dispatchable → `skip`; `identity_registry=None` degrades to step-2-only; collaborator raising → degrades to `None`/`skip`, never raises; reason strings exact.
- `tests/test_ad839_work_item_dispatch.py` (existing) stays green — assert `on_work_item_created` still dispatches identically (the refactor is behavior-preserving). Add 1 test that `dispatch_work_item` can be called directly with a `to_dict()` payload and routes.
- **Do not build:** the Quartermaster agent (AD-875) or the ticker (AD-876). No board scanning, no `update_work_item`/`unassign` calls here — `WorkItemReconciler` is a pure decision.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## AD-875 — `QuartermasterAgent`: Utility-tier board reconciler (deterministic, no LLM)

**Goal:** A utility agent that reviews the board and acts on AD-874 decisions — re-dispatching live work
and clearing/re-routing stale bindings — through the existing router. Deterministic; no LLM.

**New module:** `src/probos/agents/quartermaster.py` (mirror `IntrospectionAgent` structure).

**Design:**
```python
class QuartermasterAgent(BaseAgent):
    agent_type = "quartermaster"
    tier = "utility"
    initial_confidence = 0.9
    intent_descriptors = [IntentDescriptor(name="reconcile_board", params={}, description="Review the work board and re-dispatch / re-bind stranded work items")]
    _handled_intents = {"reconcile_board"}

    def __init__(self, *, reconciler=None, work_item_store=None, work_item_router=None, emit_fn=None, scan_limit=200, **kwargs): ...
    async def handle_intent(self, intent) -> IntentResult | None: ...   # perceive→decide→act→report
    async def reconcile(self) -> dict:                                  # the core sweep, callable by the ticker
```

**`reconcile()` (the sweep, fully honest-degrade):**
1. Guard: `work_item_store`/`work_item_router`/`reconciler` missing → log INFO, return `{"scanned":0,"redispatched":0,"cleared":0,"skipped":0,"degraded":true}`.
2. Scan **non-terminal** items: `await store.list_work_items(status="open", limit=scan_limit)` + `status="in_progress"` (two calls; merge). (Do not scan terminal statuses.)
3. Per item: `wi = item.to_dict()`; `is_disp = work_item_router.is_dispatchable(wi)`; `decision = reconciler.classify(wi, is_dispatchable=is_disp)`.
4. Act on `decision.action`:
   - `"live_redispatch"` → `await work_item_router.dispatch_work_item(wi)` (AD-874 reuse).
   - `"clear_and_reroute"` → `await store.unassign_work_item(item.id, reason="quartermaster: assignee not live")` then re-read and `await work_item_router.dispatch_work_item(updated.to_dict())`.
   - `"skip"` → count + continue.
   - Each item wrapped in try/except (Tier-2): one failure logs and continues the sweep.
5. Emit one summary event (`runtime.emit_event` — a **sync** method, do NOT `await`) using a real enum
   member `EventType.WORK_ITEM_RECONCILED` (AD-875 adds it to `src/probos/events.py` in the `WORK_ITEM_*`
   cluster; **no raw-string fallback** — mirror the `if self._emit is not None: self._emit(EventType.X, {...})`
   guard at `work_item_router.py:124`). Store an episode via the existing episodic seam if available
   (honest-degrade if not). Return the counts dict.

`handle_intent(reconcile_board)` runs the lifecycle and returns an `IntentResult` whose `result` is the
counts dict. `perceive` accepts only `reconcile_board`; `decide`→`{"action":"reconcile"}`; `act`→
`await self.reconcile()`; `report` passes the counts through.

**Acceptance criteria:**
- `tests/test_ad875_quartermaster.py` (≥12): real `WorkItemStore` (`tmp_path`), real `AgentRegistry`, real `WorkItemReconciler`; a `_FakeRouter` capturing `dispatch_work_item` calls + a real-ish `is_dispatchable`. Cover: stranded dispatchable open item (live assignee) → re-dispatched; dead-assignee item → unassigned + re-dispatched; live in_progress owner → untouched; terminal item → never scanned/touched; non-dispatchable → skipped; empty board → zero counts; one item raising → sweep continues and counts the rest; missing collaborators → degraded summary, no raise; `reconcile_board` intent returns the counts dict; non-`reconcile_board` intent → `None`; `tier == "utility"`; gap-regex clean (assert no `_CAPABILITY_GAP_RE`-matching text in any descriptor/return string).
- **Do not build:** the ticker / startup wiring / pool creation (AD-876). Do not add an internal loop. Do not call the LLM. Do not scan terminal statuses.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## AD-876 — Warm-boot + periodic trigger, config gate, pool + finalize wiring

**Goal:** Run the Quartermaster once at warm boot and on an interval, behind a config gate, and create its
pool. The agent stays intent-driven; the cadence is a tiny ticker that holds its own task ref.

**Files:**
- `src/probos/config.py` — new `WorkBoardReconcilerConfig(BaseModel)` near `HybridDispatchConfig` (config.py:4493): `enabled: bool = False` (transitional flag default False — convention #14), `interval_seconds: int = Field(default=300, ge=30, le=3600)`, `warm_boot: bool = True`, `scan_limit: int = Field(default=200, ge=1, le=2000)`. Add `work_board_reconciler: WorkBoardReconcilerConfig = Field(default_factory=WorkBoardReconcilerConfig)` to the `SystemConfig` (sibling of `hybrid_dispatch`, config.py:5246).
- `src/probos/startup/agent_fleet.py` — create the `quartermaster` pool (size 1) mirroring the introspect block (`generate_pool_ids("quartermaster","quartermaster",1)` → `create_pool_fn(..., runtime=runtime)` so the agent gets its collaborators). Gate on `config.work_board_reconciler.enabled`.
- `src/probos/startup/finalize.py` — new `_wire_board_reconciler(*, runtime, config) -> bool` (mirror `_wire_hybrid_dispatch` shape + `AttachmentReaper.start()` task pattern): gated on `config.work_board_reconciler.enabled` AND `runtime.work_item_router`/`work_item_store`/`registry` present; build the `WorkItemReconciler(registry=..., identity_registry=getattr(runtime,"identity_registry",None))`, inject it into the live quartermaster agent, and start a `BoardReconcilerTicker` task: on warm boot (if `warm_boot`) await one `reconcile()` after a short startup delay, then loop `asyncio.sleep(interval_seconds)` → emit `reconcile_board` to the quartermaster (or call `agent.reconcile()` directly). Hold the task ref; provide a `stop()` that cancels (wire into shutdown alongside the existing reaper stops). Register the call in the finalize sequence next to `_wire_hybrid_dispatch`.

**Acceptance criteria:**
- `tests/test_ad876_reconciler_wiring.py` (≥9): `WorkBoardReconcilerConfig` defaults (`enabled is False`, interval/scan bounds enforced by Pydantic — assert a too-small/too-large value raises `ValidationError`); `_wire_board_reconciler` returns `False` and no-ops when disabled / when a dependency is missing (INFO log, no raise); when enabled + wired, it injects the reconciler into the agent and starts a ticker task (assert the task ref is held); warm-boot one-shot calls `reconcile()` once; the ticker `stop()` cancels cleanly (no unretrieved-task-exception); source-scan assertion that the ticker holds its task ref (no fire-and-forget `create_task`). Use a real `SystemConfig` (BF-287 — no MagicMock at the config boundary).
- Integration: with `enabled=True` and a stranded item seeded in a real `WorkItemStore`, one warm-boot `reconcile()` re-dispatches it (assert the `_FakeRouter`/dispatcher saw the call).
- Regression: `tests/test_runtime.py` startup path stays green with the feature **disabled by default** (zero behavior change out of the box).
- **Do not build:** any default-True enablement (flip stays a future grandchild AD/operator config). Do not change `WorkItemRouter` create-path behavior. Do not add a loop inside the agent.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Out of scope for the whole epic (do NOT build)

- Cross-process / federation re-dispatch (the AD-581a boundary stands).
- Any LLM-driven reconcile decision — the path is deterministic by design.
- Migrating the rest of the workforce subsystem to `sovereign_id` (AD-441 deferral) — AD-874 only
  *reads* the slot↔DID mapping for liveness resolution; it does not change what `assigned_to` stores.
- Auto-cancelling genuinely abandoned items (a TTL reaper for stale work) — separate future AD.
- Default-True enablement — ships disabled; the operator/grandchild AD flips it.

## AD numbering

Current highest committed AD at draft time: **AD-873**. This epic is **AD-874 → AD-876**, one AD = one
commit, additive-only, corruption pre-check (`git diff --numstat | sort -k2nr | head`) before each.
Update PROGRESS.md top banner (`Wave NNN`) + DECISIONS.md (under `## Era V — Civilization`, above the
prior entry) per AD. No standalone markdown docs.
