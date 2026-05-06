# WAVE 81 DISPATCH — AD-581 v1 Hybrid Dispatch (OSS sub-ADs in one build)

**Wave id:** 81
**Umbrella AD:** AD-581 (Hybrid Dispatch — Chain-of-Command Direct Tasking & ASA Work Order Assignment)
**OSS sub-ADs in scope:** AD-581a (DepartmentDispatcher), AD-581b (Agent Order Protocol), AD-581d (Routing Confidence Threshold)
**Commercial sub-ADs out of scope (extension-point only):** AD-581c (ASA↔Dispatch Bridge), AD-581e (Project Team Dispatch)
**Closes:** GH issue #113
**HEAD at draft:** `7dee646` (post-Wave-80)
**Baseline test count:** 11565 → expected **≥ 11595** pytest (Δ ≥ +30)
**Builder required:** true (one focused build prompt)
**AD numbering:** Highest stem in trackers at draft is **AD-696** (Wave 72). AD-581 is the planned umbrella AD assigned at GH #113 creation; sub-ADs 581a/b/d are pre-allocated. No new AD number is minted by this wave.

## Verdict

Verify-first against HEAD `7dee646` confirms the substrate AD-581 v1 needs is in place:

- AD-654c activation: `AgentTarget`, `task_event_for_agent`, `task_event_for_department`, `task_event_broadcast`, `Dispatcher.dispatch()` — target resolution is solved; AD-581 is the **policy layer above it**, not a re-implementation.
- AD-440 Chain-of-Command: `Order` dataclass (frozen), `OrderState` enum (`PENDING`/`ACKNOWLEDGED`/`EXPIRED`), `OrderManager.issue_order()`/`.acknowledge()` with ontology authority validation, `EventType.ORDER_ISSUED`/`ORDER_REJECTED`/`ORDER_ACKNOWLEDGED`. AD-581b extends with `DECLINED`/`REFUSED` semantics.
- AD-594c parallel dispatch: `ParallelDispatcher.dispatch()` writes `WorkItem` rows with `assigned_to=spec.agent or None`, `tags=[default_tags..., workspace_id]`, `metadata={"workspace_id":..., "spec_id":..., "resources":[...]}`. Wave 80 explicitly deferred AD-581 wiring; this wave consumes those WorkItems.
- HebbianRouter: `get_weight(source, target, rel_type=None)`, `get_preferred_targets(source, candidates, rel_type=None, hint=None)`, `record_interaction(source, target, success, rel_type=...)`. Public API; no private-attr access required.
- Ontology: `runtime.ontology.get_agent_department(agent_type) -> str | None`, `.get_post_for_agent(agent_type) -> Post | None`, `.get_assignment_for_agent(agent_type) -> Assignment | None`, `.get_posts(department_id)`, `.get_chain_of_command(post_id)`. `BilletRegistry.get_department_roster(department_id) -> list[BilletHolder]` is the chief→crew lookup.
- WorkItemStore lifecycle: `create_work_item()` emits `WORK_ITEM_CREATED` only — does NOT emit `WORK_ITEM_ASSIGNED` even when `assigned_to` is non-None. **This is the activation gap AD-581 closes.** `assign_work_item()` (which DOES emit and dispatch via AD-654d) is booking-driven, not used by AD-594c's path.
- Standing Orders: `cognitive/standing_orders.py` exposes `_AGENT_DEPARTMENTS` and `get_department(agent_type)`. Federation-tier directives are loaded by `compose_instructions()`. AD-581b Standing-Order-violation refusal hooks against an injected predicate; v1 ships an in-process predicate Protocol seam, not a hard-wire to the directive store.

AD-581 v1 (OSS sub-ADs) is **fully buildable in one wave**. Captain rule "don't defer unless no choice" is honored: every OSS sub-AD ships. Commercial sub-ADs (581c, 581e) are explicitly tagged commercial in `docs/development/roadmap.md:4664-4666` — they live in the private commercial repo by design and are **not** an OSS deferral.

| GH #113 scope bullet | Wave 81 action |
|---|---|
| Department Chief Dispatch (organic work) | **BUILD (581a).** `DepartmentDispatcher.route(*, intent, work_item=None, candidates=None) -> RoutingDecision`. Uses `HebbianRouter.get_weight()` + ontology department membership + `BilletRegistry.get_department_roster()` to pick mode. `DIRECT(agent_id, confidence)` when max-weight agent in the resolved department crosses `confidence_threshold` AND beats the runner-up by `confidence_margin`. `BROADCAST` otherwise. Pure decision layer — no I/O, no emit. |
| ASA Central Dispatcher (Work Orders) | **OUT OF SCOPE (commercial 581c).** OSS DepartmentDispatcher exposes a stable public API the commercial bridge subscribes to; no commercial-tier code or pricing language ships in this wave. |
| WorkItem→agent activation gap | **BUILD (581a wiring).** New `WorkItemRouter` subscribes to `WORK_ITEM_CREATED`. For items with `tags` ∋ default consultation tag (or `metadata["dispatchable"] == True`), invokes `DepartmentDispatcher.route(...)` and dispatches via the existing AD-654c `Dispatcher`. Honors a non-None `WorkItem.assigned_to` as a forced-direct hint (skip Hebbian — direct-assign to that agent_id). Tier-2 log-and-degrade: any router error logs at warning and never raises into the emitter. |
| Agent Order Protocol — accept | **EXISTING (AD-440).** `OrderManager.acknowledge()`. Unchanged. |
| Agent Order Protocol — decline (with reason) | **BUILD (581b).** New `OrderState.DECLINED` value. New `OrderManager.decline(order_id, by_agent_id, *, reason) -> bool`. New `EventType.ORDER_DECLINED` payload includes `reason`. Optional `reassignment_callback` registered per-order is invoked on decline (tier-2 log-and-degrade — failures don't propagate). |
| Agent Order Protocol — refuse (Standing Orders violation) | **BUILD (581b).** New `OrderState.REFUSED` value. New `OrderManager.refuse(order_id, by_agent_id, *, violation) -> bool`. New `EventType.ORDER_REFUSED` payload includes `violation` text. `StandingOrderPredicate` Protocol seam (callable returning `(violates: bool, reason: str)`) injected via constructor; default predicate returns `(False, "")` — wire-up to the directive store is a separate AD. |
| Routing Confidence Threshold | **BUILD (581d).** `HybridDispatchConfig` Pydantic model: `enabled`, `confidence_threshold`, `confidence_margin`, `min_hebbian_weight` (cold-start floor), `success_rate_window`, `min_samples_for_routing`. Per-`(intent_type, agent_id)` rolling success-rate ring buffer on `DepartmentDispatcher` exposes `record_outcome(intent, agent_id, *, success)`. `get_success_rate(intent, agent_id)` returns `(rate, sample_count)` for dream-cycle inspection. Live threshold mutation is operator-driven (config reload); auto-tuning by dream consolidation is a hook stub. |
| Cold-start mode (always broadcast under min weight) | **BUILD (581d).** `DepartmentDispatcher.route()` returns `BROADCAST` whenever the max Hebbian weight across candidates < `min_hebbian_weight`, regardless of confidence_threshold. |
| Project Team Dispatch (cross-dept temporary CoC) | **OUT OF SCOPE (commercial 581e).** No OSS surface; commercial repo extends DepartmentDispatcher.route() with project-team scope. |
| Pydantic config | **BUILD (581d).** `HybridDispatchConfig` + new field on `SystemConfig`. Default-enabled (read-only construction; side effects gated on `WORK_ITEM_CREATED` subscription). |
| Finalize wirer | **BUILD.** `_wire_hybrid_dispatch(*, runtime, config) -> bool` mirrors `_wire_consultation_dispatch` shape. Gated on `runtime.hebbian_router` AND `runtime.ontology` AND `runtime.work_item_store` AND `runtime.dispatcher` (AD-654c). Skips with INFO log when any dependency missing. Sets `runtime.department_dispatcher` (public attribute, Wave 5 conv #1) and `runtime.work_item_router`. |

## Reframe decision (Captain rule applied)

**Full OSS-scope v1 in one wave. No deferral within OSS scope.**

Three things that LOOK like deferrals but aren't:

1. **AD-581c (ASA Bridge) and AD-581e (Project Team) excluded** — these are explicitly tagged `*(planned, Commercial)*` in `docs/development/roadmap.md:4664,4666`. They are NOT OSS scope — they live in the private commercial repo by design. Per `.github/copilot-instructions.md`: *"`*(Commercial)*` tag means 'see commercial repo for full scope' — it is NOT permission to include commercial details inline."* Including them here would be commercial-leak. Excluding them is contractually correct.

2. **Standing Orders predicate is a Protocol seam, not a hardwire** — AD-581b exposes `StandingOrderPredicate` as an injectable callable. The default returns "no violation"; v1 ships that default. Wiring to `cognitive/standing_orders.py` Federation-tier directives is a follow-on AD (no GH issue today; documented in module docstring as forcing function on first refusal-by-violation requirement). This is the same pattern AD-594c used for `PlanDecomposer` and AD-594d for `FormatTransformer` — Protocol seam ships in v1, default impl ships in v1, sophisticated impl ships when consumer signal arrives.

3. **Auto-tuning by dream consolidation is a hook, not an integration** — the `record_outcome` API + `get_success_rate` getter ship; the dream-cycle subscriber that feeds outcomes back doesn't. The roadmap's "Dream consolidation adjusts thresholds based on outcomes" requires a dream-step hook that has no consumer at HEAD; same Protocol-seam pattern. v1 ships the surface; dreaming integration follows when AD-581d's success-rate signal is ready to drive a tuning policy.

GH #113 closure note: "Closed by Wave 81 (OSS sub-ADs 581a/b/d). Commercial sub-ADs 581c/e tracked in private commercial repo as extension points on top of OSS DepartmentDispatcher + OrderProtocol primitives. Standing-Order-violation predicate and dream-tuning hook ship as Protocol seams; concrete implementations follow when consumer signal arrives."

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  7dee646

# AD-654c activation substrate (verified shipped):
src/probos/activation/task_event.py:18-43    # AgentTarget frozen dataclass with exactly-one validation
src/probos/activation/task_event.py:75-94    # task_event_for_agent(*, agent_id, source_type, source_id, event_type, priority, payload, thread_id, deadline)
src/probos/activation/task_event.py:97-115   # task_event_for_department
src/probos/activation/task_event.py:117-?    # task_event_broadcast (continues past line 120)
src/probos/activation/dispatcher.py:40-65    # class Dispatcher; ctor (registry, ontology, get_queue, dispatch_async_fn, emit_event)
src/probos/activation/dispatcher.py:67-181   # async def dispatch(event) -> DispatchResult; resolves target; enqueues; 3-tier fallback
src/probos/activation/dispatcher.py:200-225  # _resolve_target: agent_id / capability / department_id / broadcast
src/probos/runtime.py: runtime.dispatcher    # AD-654c adoption (verify finalize.py wiring)

# AD-440 chain-of-command (verified shipped):
src/probos/cognitive/orders.py:28-32     # OrderState(PENDING|ACKNOWLEDGED|EXPIRED)
src/probos/cognitive/orders.py:35-49     # @dataclass(frozen=True) Order(id, from_agent_id, from_post_id, to_post_id, directive, issued_at, expires_at, state, acknowledged_by, acknowledged_at, metadata)
src/probos/cognitive/orders.py:51-75     # OrderManager(*, ontology, registry, emit_event, max_active_per_post, default_ttl); DEFAULT_TTL_SECONDS=3600.0
src/probos/cognitive/orders.py:77-156    # issue_order(*, from_agent_id, to_post_id, directive, ttl_seconds, metadata) -> Order | None
src/probos/cognitive/orders.py:157-184   # acknowledge(order_id, by_agent_id) -> bool
src/probos/cognitive/orders.py:185-205   # list_active_for_post / list_active_for_agent / all_orders
src/probos/cognitive/orders.py:213-218   # _prune_expired (mutates state PENDING -> EXPIRED on TTL)
src/probos/cognitive/orders.py:219-234   # _emit_rejection
src/probos/events.py:171-173             # ORDER_ISSUED / ORDER_REJECTED / ORDER_ACKNOWLEDGED
src/probos/startup/finalize.py:1247-1257 # _wire OrderManager when config.orders.enabled and runtime.ontology
src/probos/runtime.py: runtime.order_manager  # adopted (line 1257 sets it)

# AD-594c consumer side (verified shipped Wave 80):
src/probos/consultation/dispatch.py:46-69    # WorkItemSpec(spec_id, title, description, work_type, agent, priority, depends_on, resources, metadata)
src/probos/consultation/dispatch.py:283-310  # ParallelDispatcher; uses runtime.work_item_store
src/probos/consultation/dispatch.py:457      # create_work_item(..., assigned_to=spec.agent or None, ...)
src/probos/consultation/__init__.py:62,89    # ParallelDispatcher exported

# WorkItemStore (verified shipped):
src/probos/workforce.py:559-585        # WorkItem(id, ..., depends_on, assigned_to, tags, metadata, ...)
src/probos/workforce.py:1004           # async def create_work_item(**kwargs) -> WorkItem
src/probos/workforce.py:1052           # emits EventType.WORK_ITEM_CREATED only — NO WORK_ITEM_ASSIGNED on create_work_item path
src/probos/workforce.py:1066-1106      # async def list_work_items(status, assigned_to, work_type, parent_id, priority, tags, limit, offset)
src/probos/workforce.py:1108           # async def update_work_item(work_item_id, **updates) -> WorkItem | None
src/probos/workforce.py:1214-1303      # async def assign_work_item(work_item_id, resource_id, source) -> Booking — emits WORK_ITEM_ASSIGNED + AD-654d TaskEvent (booking-driven; NOT used by AD-594c create_work_item path)

# HebbianRouter (verified shipped):
src/probos/mesh/routing.py:39-50       # class HebbianRouter
src/probos/mesh/routing.py:251-260     # def get_weight(source, target, rel_type=None) -> float
src/probos/mesh/routing.py:262-289     # def get_preferred_targets(source, candidates, rel_type=None, hint=None) -> list[AgentID]
src/probos/mesh/routing.py: record_interaction / record_verification  # public outcome surfaces
src/probos/runtime.py:181              # ProbOSRuntime.hebbian_router: HebbianRouter (typed attribute)
src/probos/runtime.py:304              # self.hebbian_router = HebbianRouter(...)

# Ontology (verified shipped):
src/probos/ontology/departments.py:25-27   # get_department(dept_id) -> Department | None
src/probos/ontology/departments.py:65-72   # get_agent_department(agent_type) -> str | None
src/probos/ontology/departments.py:85-90   # get_post_for_agent(agent_type) -> Post | None
src/probos/ontology/departments.py:42-53   # get_chain_of_command(post_id) -> list[Post]
src/probos/ontology/billet_registry.py:154 # get_department_roster(department_id) -> list[BilletHolder]
src/probos/runtime.py:481              # self.ontology: VesselOntologyService | None = None
src/probos/runtime.py:1674             # self.ontology = comm.ontology (adoption)

# Standing Orders (verified shipped):
src/probos/cognitive/standing_orders.py:40-67  # _AGENT_DEPARTMENTS dict
src/probos/cognitive/standing_orders.py:70-72  # def get_department(agent_type) -> str | None

# Event surface (verified collision-free):
src/probos/events.py:171  ORDER_ISSUED         # AD-440 reused
src/probos/events.py:172  ORDER_REJECTED       # AD-440 reused (issue-time validation; orthogonal to runtime decline/refuse)
src/probos/events.py:173  ORDER_ACKNOWLEDGED   # AD-440 reused
# ORDER_DECLINED / ORDER_REFUSED / HYBRID_DISPATCH_* / WORK_ITEM_ROUTED — 0 hits at HEAD; all greenfield names safe to add.

# Config insertion anchor:
src/probos/config.py:1242 # class OrdersConfig(BaseModel) — AD-440
src/probos/config.py:2110 # class ConsultationDispatchConfig — AD-594c (Wave 80)
src/probos/config.py:2496-2498 # consultation_dispatch field on SystemConfig
# AD-581 inserts HybridDispatchConfig after ConsultationDispatchConfig (~2130) and the field on SystemConfig adjacent to consultation_dispatch (~2498).

# Finalize wiring anchor:
src/probos/startup/finalize.py:715-758  # _wire_consultation_dispatch — exact precedent shape for _wire_hybrid_dispatch
src/probos/startup/finalize.py:2207-2230 # AD-654c Dispatcher creation (line 2218: runtime.dispatcher = dispatcher) + AD-654d attach block; AD-581 wirer invocation goes IMMEDIATELY AFTER this block (around line 2231)
src/probos/startup/finalize.py:1078-1085 # early-phase consultation invocation — NOT where AD-581 invocation belongs (runtime.dispatcher is None at this point)
```

## Files this wave produces

- `prompts/WAVE-81-DISPATCH.md` (this file)
- `prompts/ad-581-hybrid-dispatch-v1.md` (single build prompt; sections 0–7)
- `prompts/wave-plan.yaml` (append id `"81"` entry, depends_on `["80"]`, status `pending`)

## Builder will modify

| File | Change |
|---|---|
| `src/probos/events.py` | +2 EventType values (ORDER_DECLINED, ORDER_REFUSED) + 2 routing events (HYBRID_DISPATCH_DIRECT, HYBRID_DISPATCH_BROADCAST) |
| `src/probos/cognitive/orders.py` | +DECLINED/REFUSED OrderState values; +decline()/refuse() methods; +StandingOrderPredicate Protocol; +reassignment_callback hook |
| `src/probos/mesh/department_dispatcher.py` | NEW — DepartmentDispatcher, RoutingDecision, RoutingMode |
| `src/probos/mesh/work_item_router.py` | NEW — WorkItemRouter (WORK_ITEM_CREATED subscriber → AD-654c Dispatcher) |
| `src/probos/config.py` | +HybridDispatchConfig + SystemConfig field |
| `src/probos/startup/finalize.py` | +_wire_hybrid_dispatch + invocation in finalize() |
| `src/probos/runtime.py` | +typed attribute declarations: department_dispatcher, work_item_router (set by wirer) |
| `tests/test_ad581_hybrid_dispatch.py` | NEW — ~30 tests across DepartmentDispatcher, WorkItemRouter, decline/refuse, config, wiring |

## Acceptance criteria (delegated to ad-581 prompt)

See `prompts/ad-581-hybrid-dispatch-v1.md`. Highlights:

- 30 focused tests pass (over 28 floor by 2; matches AD-440 + AD-594c precedent for sub-AD bundles).
- Full pytest gate: `pytest tests/ -q -n 4 --dist=loadfile` reports ≥ 11595 passed (Δ ≥ +30).
- Phantom-API pre-check on the prompt body: 0 NEW phantoms (intra-prompt-introduction FPs excluded).
- No commercial language anywhere — no pricing, no premium-feature specs, no third-party-product positioning, no `*(Commercial)*` AD body content.
- All changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- GH #113 closes with the closure note in the Reframe decision section above.

## Hard-stops (real, narrow)

1. `runtime.dispatcher` (AD-654c) not adopted at HEAD `7dee646` → escalate. (Verified present at finalize.py wiring; this should not fire.)
2. `runtime.ontology` is None in the test rig → finalize wirer logs INFO and skips; tests construct DepartmentDispatcher directly with stubbed ontology, no wiring required.
3. `WorkItemStore.create_work_item()` schema migration required for Hebbian routing → it isn't; v1 reads existing `metadata` JSON column for routing hints.
4. AD-440 OrderState non-extensible → it's a `str, Enum` — adding values is forward-compatible; existing tests don't assert exhaustive enum membership.

## Out of scope (do NOT build in this wave)

- AD-581c ASA↔Dispatch Bridge (commercial; lives in private repo)
- AD-581e Project Team Dispatch (commercial; lives in private repo)
- LLM-driven routing (no LLM call in DepartmentDispatcher.route() — pure structural decision)
- Dream-cycle auto-tuning of confidence_threshold (hook stub only; no dream-step subscriber)
- Standing Orders directive-store integration (Protocol seam only; default predicate returns no-violation)
- HXI surface for routing decisions (no router endpoint, no UI; observability is via EventType)
- Federation-tier order replication (orders are local-process; federation is a separate AD)
- WorkItem→agent dispatch for non-consultation tags (router only fires on default consultation tag OR explicit `metadata["dispatchable"]=True`; broader auto-routing is a follow-on)
