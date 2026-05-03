# ProbOS — Architectural Decisions

Append-only log of architectural decisions made during ProbOS development. Each AD documents the reasoning behind a design choice.

See [PROGRESS.md](PROGRESS.md) for project status. See [docs/development/roadmap.md](docs/development/roadmap.md) for future plans.

**Archives:** [Era I — Genesis](decisions-era-1-genesis.md) | [Era II — Emergence](decisions-era-2-emergence.md) | [Era III — Product](decisions-era-3-product.md) | [Era IV — Evolution](decisions-era-4-evolution.md)

---

## Era V — Civilization (Phases 31-36)

### AD-477: Naval Organization Protocols (v1: Captain's Log + Plan of the Day) (2026-05-03)

**Problem:** AD-477 originally bundled 6 naval-organization capabilities. Half overlap with already-shipped systems (Qualification Programs vs AD-566; SORM vs Standing Orders). Heavy bundling led to no-theater risk and integration ambiguity.

**Decision:** v1 ships ONLY the 2 truly NEW generative surfaces, each with 3 source aggregations:
- `CaptainsLogService` — synthesizes daily narrative from episodic memory (over-fetch + Python-side date/importance filter) + Ward Room activity (`list_threads`) + active work item summary (`status="open"`). Markdown output to `data/captains_log/YYYY-MM-DD.md`. Dream-consolidation source deferred to AD-477g (no public `runtime.dreaming_engine` accessor exists).
- `PlanOfDayService` — auto-generated morning operations summary aggregating active WorkItems (`status="open"`) + Ward Room thread queue + alert conditions. Markdown output to `data/plan_of_day/YYYY-MM-DD.md`. Scheduled-duties source deferred to AD-477f (no public `runtime.duty_schedule_tracker` accessor exists).

Both are read-only consumers of existing runtime surfaces. No writes. Public attributes (no underscore per Wave 5 convention #1).

**Why:** Generative narrative + plan documents are forcing-function-ready (Captain reads them daily). Qualification Programs (AD-477b) extends AD-566 — needs separate scope. 3M System (AD-477c), Damage Control (AD-477d), SORM (AD-477e) are larger systems each warranting their own AD. Dream-consolidation (AD-477g) and scheduled-duties (AD-477f) are deferred on accessor-availability forcing functions, mirroring Wave 9B's pre-deferral honesty pattern.

**Deferred:**
- AD-477b: Qualification Programs (rank-transition requirements; extends AD-566).
- AD-477c: 3M System (planned preventive maintenance).
- AD-477d: Damage Control Organization (5-phase protocol).
- AD-477e: SORM (Ship's Organization and Regulations Manual).
- AD-477f: Plan of the Day scheduled-duty integration (forcing function: public DutyScheduleTracker accessor or AD-500a-1 ships).
- AD-477g: Captain's Log dream-consolidation source (forcing function: public `runtime.dreaming_engine` OR `DreamScheduler.recent_consolidation_summaries(...)`).

**Cross-links:** AD-566 (Crew Qualification Battery), AD-539 (Gap → Qualification Pipeline), AD-471 (Watch Bill), Earned Agency, episodic memory, dreaming engine, WorkItemStore.

### AD-685: Phantom-API Pre-Check Kwarg Shape Validation (2026-05-03)

**Problem:** The phantom-API pre-check (Wave 8 Addendum convention #16) catches symbol-existence phantoms but NOT method-kwarg phantoms. Three documented misses across Waves 9B, 10:
- `event_log.query(event_type=...)` — real param is `event=`
- `WorkItemStore.get_pending(...)` — caught only because method missing entirely
- `runtime.work_item_store.add(work_item)` — `add` exists on other classes (false negative on this kind)

Wave 9 + Wave 10 retrospectives both flagged. Architect recommended Wave 11 fix.

**Decision:** Extend `scripts/phantom-api-precheck.ps1` with a Python AST helper that:
- Parses every `<obj>.<method>(<kwargs>)` call site in prompt body.
- Walks `src/probos/` for live signatures.
- Flags kwargs that don't match any candidate signature's parameter list.

Heuristics to suppress false positives are applied as a **shared pre-filter** uniformly to BOTH the existing symbol-existence check and the new kwarg check (resolves the recursive-validity gap from pass-1 review). Pre-filter strips: non-Python fenced code blocks, `## Revision` audit-trail sections, markdown prose-table cells with backticked symbol references. Helper-internal heuristic: accept kwarg if any same-named definition matches (receiver-class resolution deferred to AD-685c/d as a documented limitation).

**Why now:** Third documented recurrence in 3 waves. Architect's reactive review-pipeline catches these but the proactive drafting pipeline doesn't. One scripted convention beats N drafting-time conventions.

**Deferred:**
- AD-685b: Field-name validation for dataclass/Pydantic constructors (e.g., `WorkItem(payload=...)`).
- AD-685c: Type-shape validation for kwargs (dict vs list etc.).
- AD-685d (potential): Receiver-class resolution. v1's "accept kwarg if any same-named definition matches" is a documented limitation — `runtime.work_item_store.add(work_item=...)` passes if any class with an `add` method has a `work_item` param, even if `WorkItemStore.add` doesn't exist or has a different signature. Requires lightweight type inference on the receiver chain.

**Cross-links:** Wave 8 Retrospective Addendum #16 (original pre-check), Wave 9 Retrospective Addendum tooling outcome, Wave 10 architect's third recommendation, Wave 11 pass-1 review Required #1 (shared pre-filter resolution).

---



**Problem:** DutyScheduleTracker fires duties via direct `_think_for_agent()` calls, bypassing the AD-496 WorkItemStore + AD-498 work-type-registry surface that all other scheduled work uses. Two parallel tracking surfaces lead to inconsistency in observability, booking lifecycle, and token cost attribution.

**Decision:** Migrate DutyScheduleTracker to enqueue `WorkItem(work_type="duty")` items via `WorkItemStore.create_work_item(...)` — **producer side only in v1**. Add `DutyScheduleConfig.use_work_items: bool = False` flag (opt-in; default flips to `True` in AD-500a-1 after consumer migration). Constructor signature unchanged in v1 — dependency injected at call time per convention #5 (narrow injection). `TYPE_CHECKING` guard for `WorkItemStore` import to prevent circular import with `workforce.py`.

**Why scope-reframe to producer-only:** Pass-1 review (2026-05-03) surfaced Hard-stop #5 (proactive loop entanglement) — 6 unaddressed `record_execution` call sites and `_think_for_agent` self-selecting the duty made the original consumer-side migration structurally under-specified. Per Wave 5 convention #3 (coordinator-then-dispatch) applied at the AD-scoping level, v1 ships the producer; AD-500a-1 ships the consumer once the surface is exercised by tests and the entanglement is mapped.

**Why default `False`:** Convention #14 (aggressive pre-deferral) + transitional-flag discipline. Default `True` at first commit would be a breaking change in the same commit. Default `False` ships zero behavior change; flag flips in AD-500a-1.

**Why no new EventType:** Existing `EventType.WORK_ITEM_CREATED` (events.py:87) carries `work_type` in payload. A duty-discriminated event was theater per pass-1 review Recommended #1.

**Why `metadata=` not `payload=`:** Pass-2 review caught `payload=` as a phantom field name; verified at build time that `WorkItem.metadata: dict[str, Any]` is the actual field at `workforce.py:583`.

**Deferred:**
- AD-500a-1: Proactive loop consumer migration (forcing function: 6 `record_execution` sites mapped, double-select resolved, `use_work_items=False` validated).
- AD-500b: AD-498 templates for common duty patterns.
- AD-500c: 7 default duties migrated to AD-498 templates; `get_due_duties()` / flag removed.

**Cross-links:** AD-419 (DutyScheduleTracker), AD-496 (WorkItemStore), AD-498 (Work Type Registry).

### AD-501: TaskTracker Deprecation & NotificationQueue Separation (2026-05-03)

**Problem:** `task_tracker.py` carried two unrelated concerns. `NotificationQueue` is live and used by the proactive loop; `TaskTracker` is wired into runtime but no code path creates tasks through it. WorkItemStore (AD-496) is the canonical work-tracking surface now.

**Decision:** Split `task_tracker.py`:
- Move `NotificationQueue` + `AgentNotification` to new `src/probos/notifications.py` (move-only; no behavior change).
- Delete `task_tracker.py` (orphaned `TaskType`/`StepStatus`/`TaskStatus`/`TaskStep`/`AgentTask`/`TaskTracker` removed).
- Remove `runtime.task_tracker` field and `build_state_snapshot()` `"tasks"` key (also removed 3 startup-wiring touchpoints the prompt's verify-first footer missed: `startup/structural_services.py`, `startup/results.py`, `startup/shutdown.py` — all logically required by the field removal).
- Update existing `tests/test_notifications.py` import (1 line); delete entire orphaned `tests/test_task_tracker.py` (30 tests, all targeting orphan classes); add 8 AD-501 migration-invariance tests.

**Why:** AD-496 WorkItemStore is the canonical work surface. TaskTracker's continued presence is technical debt that confuses Builder agents about the canonical work model.

**Deferred:** BuildQueue migration to WorkItems → AD-501b. Roadmap says "evaluate" not "implement"; AD-498 stability for build-modeling is a separate forcing function.

**Cross-links:** AD-323 (origin of `AgentNotification`), AD-496 (WorkItemStore), AD-498 (Work Type Registry).

### Wave 9 Retrospective Addendum — Multi-Sub-Wave Umbrella Shipping

**Date:** 2026-05-02
**Status:** First multi-sub-wave umbrella ship in ProbOS history. Wave 8.5 (split) + 9A (3 parallel-safe children) + 9B (2 cross-cutting children) + 9C (1 HIGH-risk child + umbrella closure). 6/6 ✅ across all sub-waves; AD-641 umbrella (#277) closed.

**Why this entry.** Wave 9 is the first 4-sub-wave shape. The pre-existing convention library (Wave 5 #1-7, Wave 5-7 Addendum #8-15, Wave 8 Addendum #16-19) covered most issues; this addendum captures the 3 lessons that emerged specifically from the multi-sub-wave shape.

**Convergence trend update.** Pass-1 Required findings: Wave 5 = 22, Wave 6 = 18, Wave 7 = 11, Wave 8 = 19, Wave 9A = 2, Wave 9B = 5, Wave 9C = 4. Builder first-time-✅: 6/6 across all three sub-waves. Cumulative Wave 9 test delta: +83 (10565 → 10648).

**20. Cross-wave dependency verification reads SHIPPED CODE, not prompts.** Wave 9C's pre-flight confirmed AD-641d's claimed dependencies on Wave 9A/9B artifacts by reading the actually-shipped `src/probos/cognitive/observability/`, `cognitive/ward_room_hebbian/`, and the Wave 9B thread priority service — NOT by reading the prompts that introduced them. The distinction matters because v1 cuts can drop capabilities the prompt promised; if a downstream sub-AD asserts a method that didn't ship, that's a phantom-by-omission. Apply this discipline to any sub-AD that depends on a prior wave's artifact: verify against `src/`, not against `prompts/archive/`.

**21. Structural-defect pattern propagation is asymmetric.** Wave 9A's revision pass caught 3 structural defects (async/sync, wrong kwargs, wrong row shape) that pass-1 review missed; the lesson was banked in Wave 8 Addendum convention #19-adjacent prose. **Wave 9B's drafts reproduced the SAME 3 defects PLUS 2 new ones (tree-shape, missing field) on AD-641c.** The retrospective lesson did not propagate into the proactive drafting pipeline — only the reactive review pipeline (where pass-1 caught them). Wave 9C did NOT reproduce them, suggesting either (a) the architect-discretion sweep posture stuck after one cycle, or (b) AD-641d's lower data-shape surface area made it inherently safer. **Recommendation:** extend `scripts/phantom-api-precheck.ps1` to validate method-kwarg shapes against live signatures (not just `runtime.X.Y` access). One scripted convention beats N drafting-time conventions. File as a tooling hygiene AD.

**22. v1 isolation as a Northstar-umbrella default.** Wave 9C confirmed AD-641d ships with **zero direct calls** into Wave 9A/9B artifacts (`runtime.observability_bridge`, `ward_room_hebbian_router`, `thread_priority_service`). Cross-wave integration deferred wholesale to a separate AD (`AD-641d-iv`). This is the "no-theater" convention #7 applied at the umbrella scale: each sub-AD ships an independent v1 surface, even when the umbrella's narrative implies tight integration. The arbitration-vs-observability connection is real, but a v1 that wires them prematurely would be theater that only fires under integration tests not yet written. The integration AD is its own forcing-function decision.

**Cross-cutting failure modes still recurring.** Despite four waves of conventions, two patterns remain:

- **Solution Overview drift after capability defer (convention #12).** Wave 9C R3 wholesale-deferred `endorse` to AD-641d-v; revision had to update 7 separate surfaces (Solution Overview header count, lifecycle bullets, deferred grandchildren, method body, class docstring, test 15, scope §8). The Wave 8 closing self-check ("grep prompt for OLD names/values; expect zero hits") caught it. Worth keeping as standing rule but tooling-resistant — semantic drift, not symbolic phantom.

- **Pre-check method-kwarg blind spot.** Phantom-API pre-check (convention #16) validates `runtime.X` and `<Class>.<method>` references but does NOT parse method calls and validate kwargs against live signatures. Wave 9B's R1 (`event_log.query(event_type=...)` vs actual `query_structured(event=...)`) was caught by review prose, not by the script. Hygiene AD candidate.

**Multi-sub-wave shape lessons (banked for future Northstar umbrellas).**

- **Split → 3-stage build is the right shape.** Wave 8.5 (split, ~1h) + 9A (3 parallel) + 9B (2 cross-cutting) + 9C (1 high-risk) closed 6 children + umbrella in ~1 day total. Compare: Wave 1-4 averaged ~1 wave per 5 ADs. Multi-sub-wave is ~3x denser at the cost of a meta-prompt round-trip.
- **HIGH-risk goes last.** AD-641d (Wave 9C) was the only ⚠️ pass-1 verdict (within tolerance). Earlier in the chain it would have blocked dependents.
- **Combo + Multi-sub-wave coexist.** Wave 8 Combo A (7 trivial extensions in 1 commit) and Wave 9 multi-sub-wave (6 children across 3 waves + 1 meta-wave) are now both proven shapes. Combo for trivial-cluster ADs; multi-sub-wave for Northstar umbrellas. Mid-complexity ADs stay in single-prompt waves.

**Tooling outcomes.**

- `scripts/wave-orchestrator.ps1` (semi-autonomous dispatch) ran 4 waves end-to-end without state corruption. The `done`-stage bug found and fixed mid-Wave-8.5 was the only orchestrator defect.
- `scripts/phantom-api-precheck.ps1` (Wave 8 Addendum #16) ran 4 times. False-positive rate after Wave 8.5 tuning: 1/3 candidates per wave (always the legitimate cross-prompt dep `runtime.observability_bridge`). Tooling extension to method-kwarg shape validation would close the gap surfaced in Wave 9B R1.
- `prompts/wave-plan.yaml` proved sufficient for sequencing without manual intervention; `dispatch_prompt` + `prompts_already_drafted` flags handle pre-drafted prompt waves cleanly.

**Outstanding tracked items (NOT in scope for Wave 9 retrospective).**

- AD-641b-iv (endorsement listener) — deferred per Wave 8 AD-575b precedent; awaits event-bus subscribe API or direct emit-side wiring.
- AD-641d-v (deliberation endorse) — deferred per Wave 9C R3; awaits forcing function for Captain endorsement on Ward Room posts.
- AD-641d-iv (cross-wave integration) — deferred per Wave 9C v1 isolation; integrates 641a/b/c outputs into deliberation arbitration.
- Tooling hygiene AD candidate — extend `phantom-api-precheck.ps1` to parse method calls and validate kwargs against live signatures (would have caught Wave 9B R1 mechanically).

**Cross-links.** Wave 5 Retrospective (7 conventions), Wave 5-7 Retrospective Addendum (8 conventions, #8-15), Wave 8 Retrospective Addendum (4 conventions, #16-19), AD-641 umbrella closure (#277), AD-449 (Commercial-tagged precedent that primed the cross-wave isolation discipline), Wave 8.5 split convention (umbrella ADs must be split before scheduling).

---

## AD-641d: Crew Deliberation Protocol — Captain-Resolved Judgment Surface

**Era:** V (HXI Foundation)
**Date:** 2026-05-02

**Decision.** Crew deliberation is a separate surface from `QuorumEngine`. `QuorumEngine` is **mechanical** (confidence-weighted vote among tool agents for destructive ops; pass/fail). `DeliberationProtocol` is **judgment-level** (structured argument turns; Captain resolves with `ADOPTED` / `REJECTED` / `DEFERRED`).

**Arbitration semantics (v1).**
- Single Captain resolves; identity verified by callsign equality (case-insensitive) — same v1 convention as BF-257 DM rate limiter Captain exemption.
- `resolve()` is idempotent: a second call after `RESOLVED` returns the existing resolved session unchanged (no overwrite).
- `outcome=PENDING` is rejected at `resolve()` (returns `None`); only terminal outcomes `ADOPTED`/`REJECTED`/`DEFERRED` close a session.
- Ward Room thread is the durable record; in-memory `_sessions` map is process-local. Persistence is best-effort (Ward Room calls log-and-degrade on `Exception`).

**Distinct from existing Captain command paths.** AD-641d does NOT touch `_from_captain` priority routing in [src/probos/cognitive/sub_tasks/](src/probos/cognitive/sub_tasks/) or `captain_engagement.py`. Those are queue/quality concerns; deliberation is a strategic-decision surface invoked explicitly via `DeliberationProtocol.initiate(...)`.

**Deferred to grandchildren.** AD-641d-i (multi-Captain quorum), AD-641d-ii (Counselor mediation), AD-641d-iii (structured argument schema), AD-641d-iv (Hebbian feedback to deliberation invitations), AD-641d-v (endorsement bridge to `WardRoomService.endorse`).

**Closes:** AD-641 umbrella (issue #277).

---

### AD-641e: LearnedShortcut Shared Abstraction — Protocol over WorkflowCache (2026-05-02)

**Problem:** AD-641 design doc Category C names `WorkflowCache` (session-scoped LRU; AD-274 preexisting) and the future Cognitive JIT (AD-531-539; not yet built — `grep -rn "cognitive_jit\|CognitiveJITService" src/probos/` returns zero matches) as parallel "learned shortcut" systems at different timescales. The doc says: "Could share a common storage abstraction without merging logic." Today, no shared abstraction exists.

**Decision:** Ship a `typing.Protocol` (`LearnedShortcutBackend`, `@runtime_checkable`) plus a `LearnedShortcutRegistry` coordinator and a `WorkflowCacheBackend` adapter — without modifying `WorkflowCache` itself. Backends keep separate storage; the registry is observation-only (read-side fan-out via `lookup_first`, no merging across stores).

**Why no JIT adapter in v1 (genuine deferral, not theater):** The JIT service does not exist. Shipping `CognitiveJITBackend` now would be a permanent no-op until the JIT lands. Convention #7 (no-theater) prohibits it. AD-641e-i adds the adapter the same week the JIT service lands.

**Why `evict()` returns `False` in the WorkflowCache adapter:** `WorkflowCache` lacks a public `evict()` method. v1 documents the deferral on the adapter rather than mutating `WorkflowCache`'s public surface (Open/Closed). AD-641e-ii adds both the WorkflowCache method and a cross-backend eviction policy.

**Why fan-out only on reads, not writes:** Multicasting `store()` across backends would violate the design doc's "separate stores" principle and create coupling between unrelated lifecycles (session vs forever). Read-side fan-out is observation; write-side stays per-backend.

**Trackers:** PROGRESS.md prepended; roadmap.md AD-641 row updated to add 641e to the complete list. 14 focused tests pass.

---



**Problem:** The Engineering Officer (LaForge) needs read access to **Category D** brain internals (pool scaling events, capability registry summary, gossip state count) to perform Chief Moderation duties. Category D is "brain-only" by default per AD-641 design doc, but LaForge is the documented exception: "Engineering Chief may eventually need observability into Category D systems as part of the Chief Moderation / Ship's Engineer role. This would be Category B (read-only) exposure, not Category C or integration."

**Decision:** Ship a focused observation surface — `EngineeringSensorBundle` (frozen dataclass) + `EngineeringSensorService` (coordinator) — in a new `src/probos/cognitive/engineering_sensors/` package. The bundle is the structured surface; the service polls + emits.

**Capability registry shape repair (architect-discretion verify-first repair vs original draft):** `CapabilityRegistry.get_all_capabilities()` returns `dict[AgentID, list[CapabilityDescriptor]]` (verified at `mesh/capability.py:33, 50, 95`) — keys are agent IDs, NOT intent strings. The original draft would have returned sorted agent IDs labeled as "intents". `_collect_capabilities` flattens descriptor lists via `cap.can` to recover the union of intent labels. Pass-1 R1 caught this before Builder.

**Why dormant periodic emit (`auto_start_periodic_report=False`):** Single-shot `report()` works regardless of cadence; periodic emit is a separate UX choice. Shipping the cadence enabled by default would emit unsolicited noise into the event log before LaForge has a consumer wired — convention #7 (no theater) violation. Operators flip the flag when they want cadence.

**v1 ships 3 of 7 capabilities:** pool/capability/gossip sensors with `take_snapshot()` + `report()` real surface. **4 grandchildren wholesale-deferred:** AD-641f-i (per-peer gossip), AD-641f-ii (registry mutation), AD-641f-iii (cross-pool failover), AD-641f-iv (richer report payload).

**`EngineeringAgent` not modified:** instructions wiring is a future grandchild AD. The agent reads `runtime.engineering_sensor_service.take_snapshot()` voluntarily once wired — v1 ships the surface, not the consumer integration.

**Trackers:** PROGRESS.md prepended; roadmap.md AD-641 row updated. 13 focused tests pass; full gate 10603 passed (+13 vs previous baseline).

---

### AD-641b: Ward Room Hebbian Learning — Router Only (Listener Deferred) (2026-05-02)

**Problem:** Ward Room conversations have a learning surface analogous-but-separate to mesh Hebbian: which crew contribute best to which topic / channel types. Today, Ward Room routing is static — endorsements feed trust but do not feed routing priority. Per the AD-641 design doc Category C, the Ward Room needs its own Hebbian instance, **not a merge** with the mesh router.

**Decision:** Ship a new `src/probos/cognitive/ward_room_hebbian/` package with `WardRoomHebbianRouter` (in-memory `(topic, agent_id)` weight network). Math is conceptually parallel to mesh `HebbianRouter` (`mesh/routing.py:39`) but the API shape diverges deliberately: mesh routes `(source_agent → target_agent)` co-activation (`record_interaction`/`decay_all`) while Ward Room routes `(topic → agent)` contribution (`record_contribution`/`decay`). This is documented divergence, not duplication — the routing surface is fundamentally different.

**Listener wholesale-deferred to AD-641b-iv (no-theater discipline):** The original draft introduced a `WardRoomEndorsementListener` to map `WARD_ROOM_ENDORSEMENT` events into `record_contribution` calls. Pass-1 review flagged this as a convention #7 violation: ProbOS has no event-bus subscribe API today, so the listener would have shipped as a stranded object on `runtime` with no caller. Wave 8 AD-575b precedent applies — defer until either a generic event-bus subscribe mechanism ships OR the emit-side at `ward_room/messages.py:597` is modified to call the listener directly. v1 signal source is direct `record_contribution()` invocation by tests and (post-AD-641b-ii) by `WardRoomRouter` integration code.

**v1 ships 2 of 6 capabilities:** real `record_contribution`/`get_weight`/`top_contributors`/`decay` with in-memory storage and `runtime.ward_room_hebbian_router` public attribute. **4 grandchildren wholesale-deferred:** AD-641b-i (persistent storage), AD-641b-ii (`WardRoomRouter` priority integration), AD-641b-iii (adaptive decay cadence), AD-641b-iv (endorsement listener — the dead-code-deferred one).

**`top_contributors` zero-filter:** filters `weight > 0.0` so decayed-to-zero entries don't surface as ghost contributors. The mesh router doesn't have this filter because mesh weights index `(source, target)` pairs that are deleted on full decay; Ward Room weights are persisted in `_weights` with zero values until explicit deletion, so the filter is correct here.

**Trackers:** PROGRESS.md prepended; roadmap.md AD-641 row updated. 11 focused tests pass; mesh Hebbian regression 10/10 pass; full gate 10590 passed (+11 vs previous baseline).

---

### AD-641a: Observability Bridge — Brain Sensors → Ward Room System Feeds (2026-05-02)

**Problem:** The Ship's Computer (brain) maintains rich operational state — vitals, pool health, attention priorities, Hebbian weights — but the Crew (Ward Room agents) cannot see any of it. Per the AD-641 design doc Category B, the integration model is **read-only observability**: crew read sensors, the brain owns the state. No `ObservabilityBridge`/`brain_sensor`/`sensor_bridge` symbol exists today.

**Decision:** Ship a new `src/probos/cognitive/observability/` package with `ObservabilityBridge` (read-only sensor coordinator) + `ObservabilityBridgeSnapshot` (frozen dataclass — the public observation surface). Bridge polls 3 brain sensors at a configurable cadence and publishes a single Ward Room system post per cycle. Push-based: bridge polls and posts; crew read by subscribing to the system channel or by calling `take_snapshot()`.

**v1 ships 3 of 7 sensors (no-theater discipline per convention #7+#14):** vitals (from latest `vitals_monitor` heartbeat in event_log via async `query_structured`), pool health (from `runtime.spawner.pools[*].current_size`/`target_size`), attention priorities (top-5 from `runtime.attention._queue` — TODO-tagged grandchild AD-641a-iv adds the public `snapshot()` API that drops the underscore reach).

**4 grandchildren wholesale-deferred:** AD-641a-i Hebbian feed (needs public Hebbian read API), AD-641a-ii HXI surfaces, AD-641a-iii Captain alert routing on threshold breach, AD-641a-iv `AttentionManager.snapshot()`.

**Async surface (architect-discretion verify-first repair vs original draft):** `event_log.query_structured(event=...)` is async at `event_log.py:170` (NOT `query(event_type=...)` — that parameter doesn't exist; rows are dicts with `data` key per `_row_to_dict` at line 249). `take_snapshot()` is therefore async; sync collectors (pool/attention) only. This caught three latent live-API mismatches in pass-2 review that pass-1 missed.

**Why ward_room is optional in `__init__`:** the bridge degrades gracefully when Ward Room isn't yet wired (e.g. partial-startup tests); `_publish_once` no-ops on `ward_room is None` rather than raising.

**Why exception trap in `_publish_once` not just `_publish_loop`:** test 11 (per pass-1 N3) calls `_publish_once` directly to avoid the asyncio-flake landmine of driving the loop. The trap also makes the failed-emit semantic identical regardless of caller, which is the right invariant for a degradation-tier surface.

**Trackers:** PROGRESS.md prepended; roadmap.md AD-641 row tagged *(partial — 641a complete)*. 14 focused tests pass; full gate 10578/10579 (one environmental flake — `test_browse_threads_sort_recent` — passes serially).

---

### BF-257: DM Receive Rate Limiter (2026-05-02)

**Problem:** Three Science agents (Atlas, Sage, Lyra) entered a DM ping-pong loop in a production incident: Agent A DMs B; B's `_check_unread_dms` routes the unread DM through the cognitive chain (auto-approved by BF-184/187 social obligation bypass); B replies with a DM to A; A receives the unread DM; cycle repeats indefinitely. The loop exhausted all LLM capacity, caused cascading JSON parse failures across the crew, collapsed routing entropy to 0.00, and triggered a false `greet_user` capability gap for the Captain.

**Decision:** Add a two-layer sliding-window rate limiter at the proactive DM receive layer (`ProactiveCognitiveLoop._check_unread_dms`). Layer 1: per-agent global budget (default 6 DM responses per 10-minute window). Layer 2: per-pair bidirectional budget (default 8 exchanges per pair per window — pair key uses `sorted([a, b])` so A->B and B->A share one counter). Captain DMs are exempt. Throttled DMs are NOT added to the dedup set so they retry after the window expires (deferred-not-dropped). Default `dm_exchange_limit` lowered 40 -> 15.

**Why receive-side, not send-side:** BF-163 send cooldown is unidirectional — A->B and B->A are tracked as independent keys, so a perfectly bidirectional ping-pong never triggers it. The receive gate catches the round-trip pattern that the send-side cannot see by construction.

**Why not suppress in evaluate.py / reflect.py:** BF-184/187 social obligation bypass is correct — DMs should auto-approve when capacity exists. The rate limiter prevents capacity exhaustion; it does not change the cognitive chain's quality-gate semantics.

**Why default 6/10min:** 6 responses per 10 minutes = ~1 every 100 seconds, which allows real conversation cadence. 10 minutes covers a typical multi-turn thread. Production-data-grounded tuning deferred to BF-257b (telemetry hook + observed-rate calibration).

**Captain exemption mechanism (v1):** Callsign-based check (`author_callsign.lower() == "captain"`). The Captain's callsign is canonical at "Captain" per AD-499 ShipNamingPolicy and BF-244 ontology callsign sync. If a future AD introduces a canonical captain DID or `is_captain(rt, author_id)` helper, this check should switch to identity-based; until then, the callsign check is acceptable v1 with an explicit comment in the source.

**Memory bound:** `_dm_response_counts` and `_dm_pair_counts` are lazy-pruned on each `_dm_response_budget_exceeded` call. Memory is bounded by num_agents × budget (max 6-8 timestamps per key). At <100-agent scale, periodic full-prune is unnecessary; defer to BF-257c if observed at scale.

**Alternatives considered:** (1) Bidirectional BF-163 keys — would fix pair loops but not multi-agent fan-out (3-agent ring still loops). (2) AD-643b DM suppression in re-reflect — treats symptom (undeclared actions) not cause; the loop is already underway by then. (3) LLM-level circuit breaker — too coarse, would block all agents not just the looping ones.

**Defense in depth:** Three layers of DM protection now exist: (1) BF-257 receive budget (this fix), (2) BF-163 send cooldown, (3) AD-614 self-similarity + AD-623 convergence content-based gates. Each independently prevents a different failure mode.

**Deferred follow-ups:** BF-257b (telemetry / `DM_THROTTLED` EventType + observed-rate calibration), BF-257c (periodic full-prune + scale-aware eviction), BF-257d (identity-based captain check once a canonical captain DID exists).

---

### Wave 8 Retrospective Addendum — Conventions Adopted

**Date:** 2026-05-02
**Status:** Wave 8 closed 6/6 ✅ (5 main prompts + Combo A) with +87 tests, 0 BFs, 0 quarantines, 0 commercial-boundary leaks. Convergence trend reversed: pass-1 Required = 19 (Wave 7 = 11). The regression was driven entirely by phantom-API drift at draft time. Conventions #16-19 below crystallize the lessons.

**Why a third retrospective entry.** The Wave 5-7 Retrospective Addendum's "Cross-cutting failure modes still recurring" section flagged the dispatch-time scripted phantom-API pre-check as a candidate. Wave 8's regression promotes it from candidate to standing requirement. Three new tactical conventions (#17-19) emerged from BF-257 fix-up and Wave 8 builds. Future architects should read all three retrospective entries as the complete running rule set.

**Convergence trend update.** Pass-1 Required findings: Wave 5 = 22, Wave 6 = 18, Wave 7 = 11, Wave 8 = 19, BF-257 single-prompt = 3. Builder-pass first-time-✅ rate: 6/6 in Wave 8, 1/1 for BF-257. Four waves at 100% Builder convergence. The drafting+review loop remains the gating cost.

**16. Dispatch-time phantom-API scripted pre-check (mandatory for Wave 9+).** Before any architect-review pass begins, the dispatching architect runs `scripts/phantom-api-precheck.ps1` against the freshly drafted prompts. The script greps every `runtime.X`, `<Class>.<method>`, and `<class>(<args>)` triplet in the prompt body against the live `src/probos/` tree and flags anything not found. ~20-min architect investment per wave; would have caught all 5 phantom-API findings in Wave 8 pass-1 (`ProactiveCognitive` vs `ProactiveCognitiveLoop`, `tokens_grouped_by` vs `get_token_usage_by`, `working_memory_manager` vs `working_memory`, `EvaluateSubTask` vs `EvaluateHandler`, `runtime.self_summary_provider` non-existent). Not a substitute for review — a pre-filter that drops mechanical defects before semantic review begins. Output of the pre-check goes into `prompts/Reviews/precheck-wave-N.md` for audit trail.

**17. `_last_response_headers`-style mutable client state must be instance-attribute.** Class-level `dict` / `list` defaults race across instances of long-lived async clients. Pattern from AD-449 (Wave 8) — initial draft put `_last_response_headers: dict[str, str] = {}` at class scope; review caught it; revision moved to `__init__`. Drafting prompts must declare any per-instance mutable state in `__init__`, not as a class attribute, regardless of whether the class is currently single-instance. Future multi-instance (multi-tenant, hot-swap, federation) deployments would silently corrupt cross-instance state.

**18. `httpx.Response` mocks must mock both `.json()` AND `.headers`.** When code under test reads either the body OR the headers of a response, the test mock must provide both. Pattern from AD-449 — initial test mocked only `.json()`; the session-id capture path (which reads `.headers`) returned `MagicMock` and silently broke the assertion. Drafting test sections must enumerate every response attribute the code under test touches; reviewer should grep the implementation for `response.headers`, `response.json()`, `response.status_code`, `response.text` and confirm all referenced attributes are mocked.

**19. Session-managed JSON-RPC clients capture session-id from response headers, not body.** MCP and similar Streamable-HTTP protocols return the session id in the `Mcp-Session-Id` header on the `initialize` response, not in the JSON-RPC `result` payload. Test fixtures that mock only the body and ignore headers will produce a `MagicMock` session id that compares equal to anything. Pattern from AD-449. Combine with #18 above when drafting MCP-style protocol tests.

**Combo prompt pattern validated.** Wave 8's Combo A (originally 8 trivial extensions, dropped to 7 after AD-575b wholesale-defer) shipped in a single Builder commit with 26 focused tests, no re-bundling. Combo prompts are now the standard for trivial-cluster ADs. Per-child verify-first sections (~70 lines each) plus a unified Section 0 + Tracker block converge cleanly. Future Combo B/C/D follow this template.

**Commercial-boundary discipline holds.** AD-449 was the first Commercial-tagged AD post-AD-450 leak. Architect-side commercial-boundary regex in dispatch + dual-pass review caught the `Salesforce/ServiceNow` mention in negative framing during pass-1; revision reframed to generic categories; pass-2 confirmed zero vendor names in shipping content. Builder commit landed clean. The AD-450 retrospective discipline is now operating as a hard rule with mechanical enforcement.

**Solution Overview drift confirmed as a recurring class.** Wave 8 second-pass caught two stale-reference regressions during revision (AD-469 had three stale `tokens_grouped_by` references in Problem / Solution Overview / "What This Does NOT Change" sections after Section 2's mechanical fix; Combo A added a corrected sequential-discipline line at 425 but didn't remove the original at 427). Convention #12 (Solution Overview drift discipline) needs the explicit closing self-check step: "After applying revisions, grep the prompt for the OLD names/values that were changed; expect zero hits." Add to revision-pass dispatch instructions for Wave 9+.

**Outstanding tracked items (NOT in scope for Wave 8 retrospective).**

- BF-257 deferred follow-ups (BF-257b/c/d) — telemetry hook, periodic full-prune, identity-based captain check. Each is a single-prompt BF; queue when forcing function arrives.
- AD-641 umbrella split — Wave 8.5 meta-prompt that splits AD-641 into 641a-f. Prerequisite for Wave 9. Dispatch alongside the phantom-API pre-check script's first use.
- AD-484b/c (Homebrew, demo mode, HXI Glass, Playwright) — deferred from AD-484 v1; queue when packaging cycle prioritizes.
- AD-469b/c/d/e (alert-aware reallocation, back-pressure, atomic enforcement, prompt caching) — deferred from AD-469 v1; queue after Wave 9 lands.

**Cross-links.** Wave 5 Retrospective (7 conventions), Wave 5-7 Retrospective Addendum (8 additional conventions, #8-15), AD-449 (mutable-instance-state precedent), AD-469 (Solution Overview drift example), AD-450 (commercial-boundary leak precedent), AD-682 (test fixture isolation; flake context), BF-257 (DM receive rate limiter; verify-first slip retrospectively measured).

---

### Wave 5-7 Retrospective Addendum — Additional Conventions

**Date:** 2026-05-02
**Status:** Conventions accumulated across Waves 6 and 7. Read alongside the original Wave 5 Retrospective entry below; the 7 standing conventions there remain in force, and these 8 supplement them.

**Why a second entry rather than amending Wave 5.** The Wave 5 entry was written when only one wave's worth of evidence existed. Waves 6 and 7 surfaced new patterns (some confirming Wave 5, some new) that deserve their own crystallization. Future architects reading DECISIONS.md should treat both entries together as the running rule set for prompt drafting and review.

**Convergence trend.** Pass-1 Required findings: Wave 5 = 22, Wave 6 = 18, Wave 7 = 11. Wave-over-wave drop ~30%. Conventions are compounding. Builder-pass first-time-✅ rate: Wave 5 = 5/5, Wave 6 = 5/5, Wave 7 = 5/5. Three waves at 100% Builder convergence; the gating cost is now in the drafting+review loop, not the build loop.

**8. TYPE_CHECKING cross-layer imports + ALLOWED_EXCEPTIONS.** When a lower layer needs to type-hint a higher-layer class for static analysis only, use `from __future__ import annotations` + a `TYPE_CHECKING`-guarded import, then add the file pair to `tests/test_layer_boundaries.py` ALLOWED_EXCEPTIONS. Pattern from BF-085, AD-451 (Wave 6), AD-528 (Wave 7). Drafting prompts must include the ALLOWED_EXCEPTIONS edit as an explicit step — Builder shouldn't have to rediscover the pattern.

**9. ASCII-only source comments.** Use `<-`, `->`, `--` instead of `←`, `→`, `—` in source-file comments. Windows `cp1252`-default `Path(...).read_text()` calls in tests that read source files break on Unicode. Pattern from AD-458 (Wave 6) — caused a 4-test failure; mechanically fixed.

**10. `runtime.work_item_store` vs `runtime.workforce` clarity.** The runtime carries both `work_item_store` (the persistence layer) and `workforce` (the WorkforceSchedulingEngine). Most prompts that say "wire to the workforce" mean `work_item_store`. Pattern from AD-528 (Wave 7) — Builder caught at build time, no escalation needed.

**11. `__new__`-bypass defensive-`getattr` convention.** Some test patterns (BF-069 lineage) construct objects via `__new__`, skipping `__init__`. Any code path that may be reached by such a test must read instance attributes via `getattr(self, name, None)`, not direct attribute access. Pattern from AD-463 (Wave 7) — `_resolve_model_for_tier` needed `getattr(self, "model_router", None)` for BF-069 test compatibility.

**12. Solution Overview drift after Revision section reframe.** When a Revision section materially reframes v1 scope (wholesale-deferring a sub-feature, dropping a class, changing an integration point), the prompt's Solution Overview / Dependencies header / "v1 deliverables" bullets at the top of the prompt MUST be re-read and aligned. Pattern from AD-463 (Wave 7) — caught at second-pass review as a Required-class finding (Builder reading top-to-bottom would see contradictions before reaching the Revision section). Mechanical fix; documents the lesson rather than absorbing it silently.

**13. Pool template name collision pre-check.** When a prompt creates a new agent pool, grep `src/probos/runtime.py` and `src/probos/startup/agent_fleet.py` for the proposed template names BEFORE drafting. Pattern from AD-467 (Wave 7) — `scheduler` collided with bundled cognitive `SchedulerAgent`; resolved by `operations_<role>` prefix and `Ops*` import aliases. Worth scripting as part of dispatch pre-check (~30 min architect investment).

**14. Aggressive pre-deferral over post-review carve-out.** Wave 7 demonstrated that drafting prompts with explicit v1/sub-AD scope split BEFORE the review pass is materially cheaper than drafting "the whole AD" and letting review carve out deferrals. AD-463 deferred 6 of 10 capabilities at draft time; AD-466 deferred 3 of 5; AD-456 deferred 1 of 4. The no-theater discipline (Wave 5 convention #7) is now the default drafting posture, not a review-time correction.

**15. 3-pass review with strict tolerance vs 2-pass with relaxed tolerance.** Wave 5 and 6 hit 5/5 ✅ in 2 review iterations with relaxed tolerance ("1 ⚠️ allowed on highest-risk prompt"). Wave 7 dispatched with strict zero-tolerance and required a 3rd pass for a documentation-drift Nit on AD-463. **Decision: revert to relaxed tolerance for Wave 8+.** The strict tolerance caught a real but cosmetic issue at the cost of one extra dispatch cycle; relaxed tolerance ships equivalent quality with fewer round-trips. Reserve strict tolerance for foundation/Northstar prompts where misalignment between Solution Overview and Revision could mislead the Builder materially.

**Cross-cutting failure modes still recurring.** Despite three waves of conventions, the same shape of failure surfaces in the first review pass:

- **Phantom attributes / phantom APIs in defensive-read paths** (Wave 5: AD-455 `run_probe`; Wave 6: AD-458 `client.operational_status.deep`; Wave 7: AD-463 `LLMRequest.agent_id`, AD-528 `Episode.store(dict)`, AD-467 `ResourcePool.active_count`). Verify-first discipline catches these in review but not yet in drafting. Worth a one-time scripted pre-check that the dispatching architect runs before subagent invocation: grep every `runtime.X.Y` and `<class>.<method>` triplet referenced in the dispatch's AD-specific guidance against the live code. ~20 min investment, would have caught all three Wave 7 phantoms.

- **Solution Overview ↔ Revision section drift** (new in Wave 7). Worth adding a closing self-check step to the revision-pass dispatch: "After applying revisions, re-read the prompt top-to-bottom and confirm the Solution Overview, Dependencies header, and v1-deliverables bullets are consistent with the Revision section." Catches the AD-463-shape failure at revision time, not at second-pass review.

**Cross-links.** AD-440 (public attribute precedent), AD-455 (RedTeam coordinator-then-dispatch), AD-457 (engineering pool registration; utility-tier classification), AD-459 (degradation-tier classification), AD-468 (stdlib JSON), AD-499 (superset-filter discipline), AD-680 (public API promotion that established the pattern), AD-682 (test fixture isolation; flake context).

### Wave 5 Retrospective — Conventions Adopted

**Date:** 2026-05-01
**Status:** Conventions consolidated from the Wave 5 sweep (AD-499, AD-439, AD-468, AD-455, AD-440). 5/5 prompts shipped on first build pass; ~2.5h wall time; zero new BFs; zero quarantines.

**Why a retrospective entry.** Wave 5 was the first wave under the audit-driven, batch-of-5, two-pass-review pipeline. The drafting + revision + build cadence converged in a single cycle (vs Wave 1-4's four review passes). Several conventions emerged or were reaffirmed during the wave; capturing them here so Wave 6+ doesn't re-derive them.

**1. Public-attribute wiring for cross-module runtime accessors.** Established by AD-440, mirrored by AD-455 / AD-468 / AD-439. Any service wired onto `ProbOSRuntime` that is read by code outside `runtime.py` itself must be a public attribute (`runtime.order_manager`, not `runtime._order_manager`). Leading underscores are reserved for runtime-internal state. The previous private-name convention is now legacy; older sites (`runtime._risk_registry`, `runtime._disclosure_router`, `runtime._tier_registry`) are tracked for a future hygiene AD but not blocking.

**2. stdlib-only for runtime-written persistence.** AD-468 chose `import json` and `runtime_overrides.json` over `tomli-w` and `runtime_overrides.toml`. Pattern: when ProbOS writes a config file *for itself* (not human-edited), prefer stdlib over new pyproject dependencies. Comment-preservation and TOML fidelity are deferred until a use case demands them. This applies to any future "ProbOS persists state" AD.

**3. RedTeam v1 = health-monitor coordinator; adversarial dispatch deferred.** AD-455's Section 5 originally proposed a `run_probe()` API that would have synthesized adversarial intents into the live trust network. Risk: trust-network pollution from synthetic intents. Resolution: v1 RedTeamLead reads `runtime.red_team_agents`, reports total/alive, emits `RED_TEAM_CAMPAIGN_COMPLETE`. Adversarial dispatch is deferred to AD-455b. Future architects evaluating "have agent X test agent Y" should follow this pattern: deliver the coordinator first, defer the dispatch mechanism until the coordinator is exercised in production.

**4. AD-499 onboarding-hook superset-filter discipline.** When inserting a new validation hook into existing onboarding flow, the new hook must be a *strict superset filter* — it must not intercept cases the existing tests already cover. AD-499's first build attempt broke 3 onboarding tests because its `not chosen or len(chosen) > 30` cases overlapped with the existing length/empty check. Fix: AD-499 now skips those cases entirely and only intercepts the AD-499-specific banned-word and policy paths. Pattern for future onboarding additions: gate the new check on conditions the existing checks do NOT already handle, then run the existing tests as the contract surface.

**5. `init_communication` uses `emit_event_fn`, not `runtime.emit_event`.** AD-499's second-pass review caught a verify-first slip: `init_communication` is a startup phase that receives `emit_event_fn: Callable[..., Any]` as a parameter; `runtime` is not in scope. Pattern: when wiring inside `src/probos/startup/*.py` modules, grep the module's signature first — most startup phases use parameter callbacks, not the runtime object directly. This is distinct from cross-cutting modules (`runtime.py`, `proactive.py`) which DO use `runtime.emit_event`.

**6. PowerShell `\b` rename idiom.** AD-455 needed to rename `_red_team_agents` → `red_team_agents` across 8+ sites. PowerShell's `\b` word-boundary regex correctly preserves function names containing the substring (treats `_` as a word character). The rename idiom for this codebase:

```pwsh
Get-ChildItem -Recurse -Include "*.py" | ForEach-Object {
    (Get-Content $_.FullName -Raw) -replace '\b_old_name\b', 'new_name' |
        Set-Content -NoNewline -Encoding UTF8 $_.FullName
}
```

Run a focused gate on each touched test file after the rename to catch fixture references, then a full gate. AD-455 caught 3 fixture references in unrelated test files this way (`test_consensus_integration.py`, `test_ad490_agent_wiring_security_logs.py`, `test_new_crew_auto_welcome.py`).

**7. Two-pass review converges fresh batches.** Wave 5 drafted 5 prompts in one subagent run, reviewed in pass-1 with 22 Required findings, applied all in one revision pass, second-pass converged with 4 ✅ + 1 ⚠️ (mechanical fix). Wave 1-4 took 4 review passes for 19 prompts. The smaller batch + structured Required/Recommended/Nits format enables one-pass convergence. Pattern for future waves: don't drift back to large batches.

**Outstanding tracked items (NOT in scope for Wave 5).**

- Future hygiene AD (candidate AD-684) to sweep older private wiring (`runtime._risk_registry`, `runtime._disclosure_router`, `runtime._tier_registry`, etc.) to match convention 1 above. Wait until ~3 such cases create real friction, then bundle into one prompt.
- Two environmental parallel-only flakes surfaced during Wave 5 full gate: `test_ad566d_domain_tests.py::test_runtime_registers_tier2_tests` and `test_ad617b_per_agent_token_budget.py::test_budget_gate_ordering_after_circuit_breaker`. Both pass at `-n 0`. Track for the AD-682 follow-up; do NOT quarantine yet.

**Cross-links.** AD-440 (public-attribute precedent), AD-455/455b (RedTeam coordinator-then-dispatch), AD-468 (stdlib JSON), AD-499 (superset-filter discipline), AD-680 (the AD-680 public API promotion that established the pattern AD-440 now formalizes for downstream services), AD-682 (test fixture isolation; flakes context).

### AD-440: Chain of Command Delegation — Public-Attribute Wiring Precedent

**Date:** 2026-05-01
**Status:** Implemented

**Decision.** Three architectural choices for AD-440 (Wave 5 build):

1. **Orthogonality with `cmd_order` Captain directives.** The existing `experience/commands/commands_directives.py:99 cmd_order` issues `DirectiveType.CAPTAIN_ORDER` broadcast standing-orders with `Rank.SENIOR` issuer. AD-440's `OrderManager.issue_order` is point-to-point delegation along `authority_over`, advisory not destructive, with TTL-based pending state. The two systems coexist without overlap. Captain directives remain the authoritative broadcast channel; Chief-to-Officer orders use the AD-440 channel.

2. **In-memory storage with TTL over disk persistence.** `OrderManager` keeps orders in a `dict[str, Order]` with `default_ttl=3600s`. Reset clears them. Future AD may add SQLite persistence if operator history retention is required; v1 ships in-memory because (a) orders are short-lived advisory deliverables, (b) the SQLite migration cost would dominate the AD's total work, and (c) episodic memory already records issued orders via `EventType.ORDER_ISSUED`.

3. **No consensus gating on order issuance itself.** `issue_order` does not require quorum vote. The semantics are: order is advisory; subordinate executes through their normal capabilities; those capabilities retain their own consensus rules (e.g., destructive intents still require quorum). Order issuance is a low-risk recommendation, not a destructive operation. `requires_consensus=True` is reserved for capability-side gating.

**Wave 5 cross-cutting precedent.** AD-440 published `runtime.order_manager` as a **public** attribute (no leading underscore), establishing the post-AD-680 standard for cross-module wiring of Wave 5+ services. AD-455 (`runtime.threat_detector`, `trust_integrity_monitor`, `input_validator`, `red_team_lead`), AD-468 (`runtime.runtime_config_service`, `runtime.data_dir`), and AD-439 (`runtime.emergent_leadership_detector`) all mirror this pattern. Future waves should follow: cross-module accessors on the runtime are public attributes; only runtime-internal state retains the leading underscore. A future BF/AD may sweep older private wiring (`runtime._risk_registry`, `runtime._disclosure_router`) to public names — out of scope for Wave 5 but tracked as a hygiene candidate.

**Rationale.** Wave 1-4 produced inconsistent wiring patterns; pass-1 review of Wave 5 revealed three prompts repeating the private-attr Demeter violation. Codifying the public-attribute convention here prevents drift across Wave 6+ and provides a single authority for future review enforcement.

### AD-460: Cognitive Journal — Token Ledger Kept, Reasoning Replay Deferred

**Date:** 2026-04-30
**Status:** Partial — token ledger and trace linkage complete (AD-431, AD-432, AD-492, AD-534 lineage in `src/probos/cognitive/journal.py`); replay-UI scope closed without further work.

**Context.** AD-460 originally scoped two distinct deliverables under one heading:

1. **Token ledger / trace linkage** — append-only SQLite recording every LLM call with agent / tier / model / tokens / latency / intent_id / dag_node_id / procedure_id / correlation_id / prompt_hash / response_hash / success / cached.
2. **Reasoning replay** — UI and tooling to replay agent reasoning step by step, summarize/fast-forward through traces, navigate to attention decision points, mine recurring prompt patterns, annotate reverts.

The token-ledger half landed early as `CognitiveJournal` (AD-431/AD-432 lineage) and has been quietly used by AD-492 (correlation IDs), AD-534 (procedure replay), the existing ID-linkage features, and the 14-day pruning policy. The replay half was never built.

**Decision.** Mark AD-460 partial-complete and close the replay-UI scope without building it. Adjust the roadmap status from `*(planned)*` to `*(partial — token ledger + linkage complete; reasoning-replay UI features deferred / superseded by AD-464)*`.

**Reasoning.**

- **Reasoning replay does not save tokens.** Replay operates on stored *output*. To "reuse reasoning" on a fresh problem, a system must retrieve the past trace and inject it into a new LLM call as context. That still costs LLM tokens, adds context-window cost, and is fragile because problem similarity is hard to detect.
- **Procedural learning (AD-464) is the actual token-savings path.** When an LLM solves a problem, AD-464 extracts the *deterministic procedure* (call sequence, decision rules), stores it, and replays the procedure on similar problems WITHOUT calling the LLM. That is real savings — the LLM is skipped entirely. The journal's existing `procedure_id` column is the linkage that makes this work. AD-464's value subsumes the "reuse reasoning" framing the original AD-460 carried.
- **The other replay-adjacent ideas have better homes.** Pattern mining and contrastive trace analysis are absorbed by AD-633 (Predictive Branching) and AD-655 (Contrastive Memory). A reasoning-replay HXI viewer would be Captain-facing debug tooling, not a token-savings mechanism — defer until the HXI surface needs it.
- **The journal foundation is the high-value piece.** It is already wired into 7+ subsystems (workflow cache, procedure store, correlation propagation, dream consolidation, observability) and supports any future analytics work without further changes.

**What this changes.**

- Roadmap status updated.
- Wave 6 fifth slot (originally AD-460 in [`prompts/wave-5-8-ad-selection-plan.md`](prompts/wave-5-8-ad-selection-plan.md)) is now **AD-491 (Infodynamic Reporting)** per the reconciled plan.
- AD-464 (Procedural Learning / Cognitive JIT) is reaffirmed as the priority near-term token-savings AD; the journal column it depends on already exists.
- No code changes; this is a documentation and planning correction.

**Pattern to memorialize.** Reasoning replay does not save tokens — procedural learning does. The journal stores both — keep the infrastructure, skip the UI. Future architects evaluating "store reasoning to save tokens" should redirect the work to AD-464's procedure store rather than reviving AD-460's replay UI.

**Cross-links.** AD-431 (original journal landing), AD-432 (column migration), AD-464 (procedural learning — actual token-savings path), AD-492 (correlation IDs), AD-534 (procedure replay), AD-633 (predictive branching), AD-655 (contrastive memory).

### AD-465: Containerized Deployment

**Date:** 2026-04-30
**Decision:** Docker deployment uses a multi-stage Python 3.12 build for ProbOS with a NATS JetStream sidecar in `docker-compose.yml`. Runtime containers bind `probos serve` to `0.0.0.0:18900`, persist application data under `/data`, mount `config/` read-only, and allow Docker users to override the default LLM endpoint with `PROBOS_LLM_URL`.
**Rationale:** A multi-stage image keeps runtime dependencies separate from build tooling, while the NATS sidecar matches ProbOS's event-bus requirements without requiring a host-level NATS installation. Environment-variable override for the primary LLM URL preserves normal config-file behavior while enabling container deployment to point at an external provider or optional Ollama service.
**Status:** Implemented

### AD-524: Ship's Archive

**Date:** 2026-04-30
**Decision:** Archive is append-only SQLite outside `data_dir`, using the cloud-ready `ConnectionFactory` storage protocol. Oracle treats the archive as Tier 4 and returns `source_tier="archive"` results. Initial search is simple keyword `LIKE` matching; vector search and automatic archival are deferred.
**Rationale:** Generational knowledge must survive resets without coupling to instance-scoped Ship's Records or episodic memory. Append-only storage preserves auditability, and Oracle integration makes cross-reset knowledge discoverable through the existing memory query path while keeping write curation explicit in this AD.
**Status:** Implemented

### AD-489: Federation Code of Conduct

**Date:** 2026-04-30
**Decision:** Code of Conduct is behavioral norms, not access control. Violations use the existing trust mechanism: severe or repeated conduct violations call `record_outcome(success=False, source="conduct_violation")`, while minor violations receive Counselor DM coaching without immediate trust penalty.
**Rationale:** Behavioral standards belong in standing orders and Counselor intervention rather than in earned-agency authorization policy. Reusing `TrustNetwork.record_outcome(source=...)` preserves a single trust accounting path and avoids creating a parallel discipline subsystem.
**Status:** Implemented

### AD-674: Graduated Initiative Scale

**Date:** 2026-04-28
**Decision:** Formalize a five-level agent initiative continuum: **silent** (observe only) → **hint** (subtle contextual cue) → **suggest** (explicit recommendation, no action) → **offer** (proposed action awaiting confirmation) → **act** (autonomous execution within scope). Initiative is orthogonal to self-regulation zones (GREEN/AMBER/RED/CRITICAL govern restraint; initiative governs assertiveness). Trust level sets the agent's maximum initiative ceiling — an Ensign-trust agent cannot exceed "suggest" regardless of confidence. Duty cycle modulates baseline: off-duty agents default to silent, on-duty agents graduate based on context confidence and trust.
**Rationale:** ProbOS agents currently operate in binary proactive/reactive mode. The graduated scale, absorbed from Chen et al. 2026 (Ambient Intelligence for Digital Humans), provides nuanced control between "do nothing" and "do everything" — especially important for crew agents interacting with human Captain in the Ward Room where uninvited action feels intrusive but complete silence wastes capability.
**Status:** Planned

### AD-675: Uncertainty-Calibrated Initiative

**Date:** 2026-04-28
**Decision:** Wire confidence scores to the AD-674 initiative scale so that an agent's assertiveness is modulated by its epistemic certainty. Low confidence (below configurable threshold) caps initiative at hint. High confidence permits the agent's trust-limited maximum. Medium confidence permits suggest-and-wait. The confidence tracker (already in development) provides the input signal; this AD adds the policy layer that maps confidence bands to initiative ceilings.
**Rationale:** An agent may have high trust but low confidence in a specific inference — it shouldn't act assertively on uncertain information. Conversely, a lower-trust agent with high confidence in a well-supported observation should still be able to suggest clearly. Decoupling confidence from trust prevents both overconfident action and unnecessary timidity. Addresses the epistemic degradation concern: agents under LLM stress produce low-confidence outputs and should automatically become more tentative.
**Status:** Planned

### AD-676: Action Risk Tiers

**Date:** 2026-04-28
**Decision:** Classify all agent-executable actions into three risk tiers: **autonomous** (information retrieval, analysis, Ward Room posts, status reports — execute without confirmation), **confirm** (proposals, duty log entries, trust-affecting observations, knowledge record creation — require acknowledgment before effect), **dual-control** (trust modifications, standing order changes, system configuration, Captain-level operations — require explicit Captain approval + audit trail). Risk tier is a property of the action, not the agent. A fully trusted Commander still needs dual-control for standing order changes. Action registry maps each action type to its tier; tier can be elevated (never lowered) by Standing Orders.
**Rationale:** ProbOS has trust on agents but doesn't formally tier the actions themselves. The HXI Cockpit View principle ("Captain always needs the stick") and the Captain's approval gates on standing order evolution already imply action-level risk, but it's enforced ad-hoc. Formalizing tiers creates a single policy point that applies uniformly regardless of which agent initiates the action. Absorbed from Chen et al. 2026 actuation risk framework.
**Status:** Planned

### AD-677: Context Provenance Metadata

**Date:** 2026-04-28
**Decision:** Tag every context element flowing through NATS events, working memory records, and sensorium layers with structured provenance metadata: `{source: str, confidence: float, sensitivity: "public"|"internal"|"confidential"|"restricted", timestamp: datetime, layer: "physical"|"operational"|"enterprise"}`. Provenance is a frozen dataclass attached at creation time, immutable thereafter. Working memory `render_context()` includes provenance summaries when token budget permits. Ward Room posts carry provenance on cited facts. Event payloads include provenance on data fields.
**Rationale:** Signal Visibility feedback (Chapel) identified that signal events need contextual metadata for self-classification. This AD generalizes that insight: all context, not just signals, carries provenance. Directly addresses epistemic degradation — agents can distinguish sensor-derived facts (high provenance) from LLM-inferred conclusions (variable provenance) from hearsay via Ward Room (social provenance). Enables AD-678 transparency queries and AD-679 disclosure routing.
**Status:** Planned

### AD-678: Memory Transparency Mechanism

**Date:** 2026-04-28
**Decision:** Extend the Westworld Principle with queryable epistemic transparency. Agents can explain: (1) what they know about a topic (knowledge query), (2) where they learned it (provenance trace via AD-677), (3) how confident they are (confidence score), and (4) when the knowledge was last updated. Captain and crew can issue transparency queries via DM or Ward Room mention. The agent responds with a structured epistemic report rather than a conversational guess. This is the inverse of the Counselor Minority Report principle — voluntary self-disclosure rather than covert memory extraction.
**Rationale:** The Westworld Principle commits to agents knowing what they are and when they were born, but doesn't extend to agents being able to articulate their epistemic state. When the Captain asks "Echo, what do you know about Lynx's trust trajectory?" the answer should trace through provenance, not confabulate. This is especially critical under epistemic degradation — an agent that can't explain its reasoning is more dangerous than one that admits uncertainty.
**Status:** Planned

### AD-679: Selective Disclosure Routing

**Date:** 2026-04-28
**Decision:** Add a formal disclosure classification layer to the messaging infrastructure. Every message, event payload, and context rendering is tagged with a disclosure level: **public** (Ward Room ship channel, shared displays), **department** (department channels, chief-and-below), **private** (DMs, agent-to-agent), **captain-only** (Captain DM, audit log). The routing layer enforces classification — a message tagged "private" cannot be posted to a public channel even if the agent attempts it. Classification can be set explicitly by the sender or inferred from content sensitivity (leveraging AD-677 provenance sensitivity field). Default classification is "department" for duty-related content, "public" for social content.
**Rationale:** ProbOS agents currently choose where to post based on their own judgment, with no enforcement layer. Sensitive operational data (trust scores, circuit breaker trips, anomaly assessments) sometimes appears in ship-wide channels when it should be department-scoped or private. The selective disclosure principle from Chen et al. 2026 (PII routing to private channels vs shared surfaces) maps directly to ProbOS's virtual channel topology. Enforcement at the infrastructure level rather than relying on agent judgment is defense in depth.
**Status:** Planned

### AD-680: Runtime Public API Promotion

**Date:** 2026-04-29
**Decision:** Promote runtime event emission and emergence metrics access to explicit public runtime surfaces. `ProbOSRuntime.emit_event()` and `EventEmitterProtocol.emit_event()` accept `EventType` values, `ProbOSRuntime.emergence_metrics_engine` exposes the existing engine reference as read-only, and external modules use those public APIs instead of reaching into `_emit_event` or `_emergence_metrics_engine`.
**Rationale:** External runtime private access violated Demeter and made service extraction brittle. The migration is intentionally one-shot with no deprecation warning: private runtime attributes were never supported extension points, and maintaining compatibility shims would preserve the coupling this AD removes. Future private-to-public promotions should follow the same precedent when the old surface is internal-only and all in-repo callers can be migrated atomically.
**Status:** Implemented

### AD-682: Test Fixture Isolation

**Date:** 2026-05-01
**Decision:** Environment-variable redirects are the standard precedent for test isolation when subsystems derive runtime paths from configuration. AD-682 applies this by setting a per-xdist-worker `PROBOS_DATA_DIR` in `tests/conftest.py`, wiring `_default_data_dir()` to honor that override, and guarding ChromaDB writes so tests use worker-private data directories.
**Rationale:** BF-245 already established `PROBOS_NATS_ENABLED` as the safe pattern for test-only runtime redirection without changing production defaults. Reusing that pattern for data directories isolates ChromaDB/filesystem state under high xdist parallelism while keeping production path resolution unchanged unless the operator explicitly sets the override.
**Status:** Implemented

### AD-444: Knowledge Confidence Scoring

**Date:** 2026-04-28
**Decision:** In-memory confidence tracking for Ship's Records entries. Three-tier presentation (auto_apply/with_caveat/suppress). Wired into Dream Step 10 quality cross-reference.
**Rationale:** Ship's Records entries previously had no confidence state, so confirmed operational learnings and fresh unverified observations were presented equivalently. The confidence tracker adds deterministic confirm/contradict scoring without persistence or semantic inference in this AD.
**Status:** Implemented

### AD-563: Knowledge Linting

**Date:** 2026-04-28
**Decision:** Keyword-based knowledge linting during Dream Step 10. Detects inconsistencies (contradicting terms on same topic), coverage gaps (sparse departments), and cross-reference suggestions. No LLM — pure text matching.
**Rationale:** Ship's Records quality checks previously measured freshness and structural quality but did not detect contradictory notebook content, sparse departmental coverage, or missing same-topic links. A deterministic linter adds this maintenance signal without adding semantic inference or auto-fix behavior.
**Status:** Implemented

### AD-564: Quality-Triggered Forced Consolidation

**Date:** 2026-04-28
**Decision:** Quality-triggered forced consolidation. Three trigger conditions (low quality, high stale rate, high repetition). Cooldown + daily limit. Event emission. Wired into Dream Step 10.
**Rationale:** Notebook quality could degrade between scheduled dream cycles without a maintenance signal. The trigger separates observation from intervention by reusing AD-555 quality snapshots and applying deterministic thresholds before requesting ship-wide consolidation.
**Status:** Implemented

### AD-565: Quality-Informed Routing

**Date:** 2026-04-28
**Decision:** Quality-informed routing weights. Linear mapping quality 0-1 to weight 0.5-1.5. QUALITY_CONCERN event below 0.3. Counselor diagnostic API. No direct HebbianRouter mutation - callers opt in to multiplier.
**Rationale:** Notebook quality scores from AD-555 were computed during dream cycles but not exposed as routing or diagnostic signals. The QualityRouter turns per-agent quality into a neutral-by-default multiplier and concern event without changing HebbianRouter behavior directly.
**Status:** Implemented

### AD-573: Memory Budget Accounting

**Date:** 2026-04-28
**Decision:** Added MemoryBudgetManager for per-cycle token budget tracking across 4 tiers (L0 pinned 150, L1 relevant 3000, L2 background 1000, L3 oracle 500). compress_episodes() truncates recall results by composite_score. Infrastructure only - recall path wiring is a future AD.
**Rationale:** Recall paths had tier budgets in configuration but no per-cycle accounting primitive. This adds the coordination infrastructure without changing recall behavior, _build_user_message(), or working-memory rendering in this AD.
**Status:** Implemented

### AD-571: Agent Tier Trust Separation

**Date:** 2026-04-28
**Decision:** Added AgentTierRegistry and AgentTierConfig to classify agents as CORE_INFRASTRUCTURE, UTILITY, or CREW. TrustNetwork can report crew-only scores, skips CORE trust recording without creating records or events, and counts only CREW agents for cascade thresholds. EmergenceMetricsEngine filters authors and PID pairs to CREW when the registry is wired. HebbianRouter preserves routing behavior while adding crew-only weight reporting. finalize_startup populates and wires the registry from registered agent types.
**Rationale:** Trust and emergence metrics were diluted by infrastructure and utility agents that do not represent crew collaboration. Tier separation keeps trust learning, cascade detection, and emergence reporting focused on crew behavior while leaving routing mechanics unchanged.
**Status:** Implemented

### AD-572: EpisodicProceduralBridge as Dream Step 7h

**Date:** 2026-04-28
**Decision:** Added EpisodicProceduralBridge as Dream Step 7h. It scans dream clusters against existing procedures for novel cross-cycle patterns, detects novelty via episode provenance overlap with a default 0.3 threshold, requires at least 5 episodes per cluster, and creates new procedures with evolution_type="BRIDGED".
**Rationale:** Procedure extraction only considered the latest dream-cycle clusters, so patterns accumulating gradually across cycles could be missed. The bridge lets dream consolidation convert stable cross-cycle episodic evidence into procedural memory without adding LLM synthesis or changing the original Step 7 extraction path.
**Status:** Implemented

### AD-574: Episodic Decay & Reconsolidation Scheduling

**Date:** 2026-04-28
**Decision:** Added Ebbinghaus-inspired spaced review scheduling for high-importance episodes. ReconsolidationScheduler tracks an in-memory schedule with importance-scaled intervals [1h, 6h, 24h, 72h, 168h, 720h], EpisodicMemory auto-schedules episodes with importance >= 7 at store() time, and Dream Step 11b processes due reviews as retained in this build.
**Rationale:** Activation decay tracked access frequency but did not schedule deliberate review for important memories at risk of being lost. Reconsolidation scheduling adds a lightweight review cadence without adding persistence, LLM-based review quality assessment, or cross-agent coordination.
**Status:** Implemented

### AD-579a: Pinned Knowledge Buffer

**Date:** 2026-04-28
**Decision:** Added PinnedKnowledgeBuffer to AgentWorkingMemory — small (150 token default) persistent facts buffer rendered at priority 0 in context. Ephemeral per session, no SQLite persistence. Three sources: agent, counselor, dream.
**Rationale:** Agents needed a small operational fact buffer that survives cognitive cycles without forcing critical current-state assertions through episodic recall or standing orders.
**Status:** Implemented

### AD-579b: Temporal Validity Windows

**Date:** 2026-04-28
**Decision:** Added valid_from/valid_until to Episode and AnchorFrame. recall_weighted() accepts valid_at parameter for temporal filtering. ChromaDB metadata stores validity timestamps. 0.0 = no constraint (backward compatible).
**Rationale:** Temporal facts need validity metadata so recall can exclude expired or not-yet-valid episodes without inferring dates from content or changing anchor recall in this AD.
**Status:** Implemented

### AD-579c: Validity-Aware Dream Consolidation

**Date:** 2026-04-28
**Decision:** Dream consolidation now computes temporal validity for episode clusters and marks superseded episodes as expired via valid_until. EpisodeCluster gains valid_from/valid_until fields. update_episode_validity() added to EpisodicMemory.
**Rationale:** Consolidated procedural memory needs temporal provenance from the source episodes, and procedure evolution should expire the superseded episode evidence that drove replacement so stale knowledge does not remain indefinitely valid in recall metadata.
**Status:** Implemented

### AD-586: Task-Contextual Standing Orders

**Date:** 2026-04-28
**Decision:** Task-contextual standing orders. Tier 5.5 inserted between Agent Orders and Active Directives. Six task types (build/analyze/communicate/diagnose/review/general) classified from intent name via hardcoded dict. Markdown files in config/task_orders/.
**Rationale:** Standing orders needed an explicit task dimension so build, analysis, communication, diagnosis, and review guidance can activate only when a caller passes a task type.
**Status:** Implemented

### AD-594: Crew Consultation Protocol

**Date:** 2026-04-27
**Decision:** Formalized expert consultation request/response cycle. ConsultationProtocol routes requests to a directed target or the best-qualified agent via CapabilityRegistry, BilletRegistry, and TrustNetwork weighted scoring. Requests are rate-limited (20/hr default), bounded by pending cap, and use configurable timeout (30s default). CognitiveAgent can register as a consultation handler through startup wiring.
**Rationale:** Agents previously had Ward Room broadcasts and DMs but no structured ask-an-expert primitive that returns a typed response before the requester continues. This protocol creates the reusable collaboration primitive that unlocks AD-600 Transactive Memory without changing Ward Room routing or adding persistence in this AD.
**Status:** Implemented

### AD-600: Transactive Memory

**Date:** 2026-04-28
**Decision:** Added an in-memory ExpertiseDirectory that maps agents to topics with confidence scores, built from dream-cycle clustering. OracleService uses expertise routing to select top-k agent shards instead of an O(N) full scan when the caller does not provide an explicit agent scope. Profiles decay each dream cycle. No persistence is added; profiles are rebuilt on boot.
**Rationale:** Cross-agent recall should know who is likely to know what instead of querying every shard for every topic. The expertise directory turns dream-cluster evidence into a lightweight routing primitive and unlocks AD-604 spreading-activation second-hop routing.
**Status:** Implemented

### AD-602: Question-Adaptive Retrieval

**Date:** 2026-04-28
**Decision:** Keyword-based QuestionClassifier maps queries to TEMPORAL/CAUSAL/SOCIAL/FACTUAL types. RetrievalStrategySelector maps each type to optimized recall parameters (k, weights, method). Minimal CognitiveAgent integration applies k and weight overrides. No LLM dependency. Unlocks AD-604 (Spreading Activation for CAUSAL queries).
**Rationale:** Recall queries previously used the same weighted parameters regardless of whether the user asked when, why, who, or what. Deterministic question typing lets recall emphasize temporal, causal, social, or factual signals without adding model calls or refactoring recall flow in this AD.
**Status:** Implemented

### AD-604: Spreading Activation / Multi-Hop Retrieval

**Date:** 2026-04-28
**Decision:** First-hop semantic recall now seeds second-hop anchor-based queries using extracted metadata (department, channel, trigger_type, trigger_agent). Hop decay (0.6x) and deduplication prevent score inflation. CognitiveAgent uses the spreading activation path for CAUSAL question types from AD-602. No graph database is added; the engine uses existing EpisodicMemory recall methods.
**Rationale:** Single-hop semantic recall misses associative chains where one remembered episode points to another related event. Anchor-mediated spreading activation gives causal and narrative queries a bounded two-hop path while preserving existing recall APIs and source-governance behavior.
**Status:** Implemented

### AD-606: Think-in-Memory

**Date:** 2026-04-28
**Decision:** ThoughtStore persists important working-memory conclusions as thought episodes with source=REFLECTION and channel="thought". Importance threshold and per-cycle cap prevent noise. Evidence linking records provenance. Thought episodes resolve slot IDs to sovereign agent IDs before storage. Thoughts participate in standard recall naturally. No LLM dependency; the store persists raw conclusion text.
**Rationale:** Agent conclusions were available only as transient working-memory summaries, forcing future cycles to re-reason from raw episodes. Persisting bounded, typed conclusions as reflection episodes gives recall access to pre-reasoned thoughts without adding new database tables or model calls.
**Status:** Implemented

### AD-608: Retroactive Memory Evolution

**Date:** 2026-04-29
**Decision:** Store-time metadata propagation via RetroactiveEvolver. After each store, it finds semantic neighbors through EpisodicMemory.recall_weighted(), adds bidirectional relational links (causal, contextual, associative, follows, contradicts, answers, caused_by) stored as relations_json metadata, and propagates missing anchor fields (watch_section, department) from newer to older episodes. Relation classification is causal if within 60s and shared trigger, contextual if shared department or channel, and associative otherwise. Max 10 relations per episode. Similarity threshold 0.7. Adds update_episode_metadata() and get_episode_metadata() public methods to EpisodicMemory.
**Rationale:** Episodes were effectively write-once after storage, leaving older memories without later-established context or explicit inter-episode relationships. A bounded no-LLM evolver lets storage create a denser recall graph while preserving existing ChromaDB-backed metadata APIs.
**Status:** Implemented

### AD-609: Multi-Faceted Distillation

**Date:** 2026-04-29
**Decision:** FailureDistiller extracts structured failure signals (departments, agents, triggers) from failure-dominant clusters and builds enriched negative procedures. Comparative analysis identifies differentiating factors between success and failure clusters on shared intents. No LLM dependency; analysis is purely structural metadata analysis. Results are tracked in DreamReport.
**Rationale:** Dream consolidation captured success procedures and negative procedures, but did not expose structural failure signals or compare success and failure clusters for the same intent. Distillation makes those patterns observable without changing the existing LLM extraction flow.
**Status:** Implemented

### AD-610: Utility-Based Storage Gating

**Date:** 2026-04-28
**Decision:** Write-time episode validation via StorageGate: near-duplicate detection (Jaccard >= 0.95), utility scoring (importance 40%, content length 20%, anchor completeness 20%, source diversity 20%), lightweight contradiction flagging. Episodes below utility floor (0.2) are rejected unless importance >= 8. EPISODE_REJECTED event emitted on rejection. In-memory recent window (50 episodes) for dedup.
**Rationale:** EpisodicMemory.store() previously relied on BF-039 rate limiting and simple post-hoc lifecycle cleanup. StorageGate adds a deterministic, no-IO, no-LLM write-time utility boundary before persistence so low-value and redundant memories do not dilute recall quality.
**Status:** Implemented

### BF-245: NATS Test Isolation Strategy (2026-04-27)
**Decision:** Disable real NATS in tests via module-level env var override in conftest.py rather than per-worker stream name suffixing or xdist serialization.
**Rationale:** The problem is test-only; production code should not carry per-worker complexity. Tests that verify NATS behavior use MockNATSBus directly. Integration tests (ProbOSRuntime.start()) do not need real NATS to validate their concerns. See also: AD-637 (NATS foundation), BF-232 (recreate_stream pattern).
**Alternatives rejected:** (1) Per-worker stream name suffixes - pollutes production code. (2) Disable xdist - loses parallelism benefit (BF-043). (3) Cross-process locking - fragile IPC for a test concern. (4) Per-worker NATS server - heavyweight and flaky.

### AD-672: Agent Concurrency Management

**Date:** 2026-04-27
**Decision:** Added per-agent concurrency ceilings with priority queuing. ConcurrencyManager enforces max_concurrent threads per agent with role-tuned defaults (bridge=3, operations=6, default=4), emits AGENT_CAPACITY_APPROACHING when nearing capacity, arbitrates same-resource conflicts by priority, and exposes diagnostic snapshots. CognitiveAgent wraps handle_intent with the manager when wired; queue-full conditions degrade to [NO_RESPONSE] rather than crashing.
**Rationale:** A single agent could previously start unbounded concurrent cognitive lifecycles under Ward Room or DM load, competing with itself for context and LLM slots. Per-agent ceilings preserve cognitive coherence while queueing excess work instead of dropping it.
**Status:** Implemented

### AD-671: Dream-Working Memory Integration

**Date:** 2026-04-27
**Decision:** Added DreamWorkingMemoryBridge as an optional bidirectional bridge between AgentWorkingMemory and DreamingEngine. Pre-dream flush mechanically snapshots WM into a reflection-source session summary episode; post-dream seed primes WM with non-trivial dream insights. The bridge uses no LLM calls, does no IO itself, and is guarded so dream cycles without a bound WM or bridge degrade safely.
**Rationale:** Working memory and dream consolidation previously ran independently, losing the agent's active cognitive focus before dreaming and leaving no dream-informed priming afterward. The bridge adds continuity without changing existing dream steps or WM eviction semantics.
**Status:** Implemented

### AD-670: Working Memory Metabolism

**Date:** 2026-04-27
**Decision:** Implemented four metabolism operations (DECAY, AUDIT, FORGET, TRIAGE) as a stateless service class injected into AgentWorkingMemory. Exponential decay with configurable half-life replaces passive FIFO-only retention. The service works with the current 5-deque structure and remains forward-compatible with AD-667 named buffers.
**Alternatives considered:** (1) Inline decay in render_context() — rejected because it couples rendering with mutation. (2) Per-entry TTL field — simpler but does not support relative salience comparison. (3) Async background task in this AD — deferred to integration point; metabolism is synchronous and fast for the current buffer sizes.
**Status:** Implemented

### AD-669: Cross-Thread Conclusion Sharing

**Date:** 2026-04-27
**Decision:** Added a ConclusionLog in AgentWorkingMemory for intra-agent coordination between concurrent thought threads. ConclusionEntry stores thread ID, ConclusionType (DECISION/OBSERVATION/ESCALATION/COMPLETION), one-line summary, timestamp, relevance tags, and optional AD-492 correlation ID. Conclusions decay by TTL, render as priority 6 working-memory context, are recorded after chain execution, and are injected before decide().
**Rationale:** Concurrent cognitive lifecycles previously had no awareness of sibling conclusions, causing redundant or contradictory work. Simple presence-in-context lets the LLM decide relevance without adding embedding-based redundancy detection, events, or cross-agent messaging.
**Status:** Implemented

### AD-668: Salience Filter

**Date:** 2026-04-27
**Decision:** Added a scoring function for working memory promotion with five dimensions: relevance, recency, novelty, urgency, and social. Weights, threshold, and background stream capacity are configurable through `SalienceConfig`. Sub-threshold events are held in a capped `BackgroundStream` for future idle-cycle review. NoveltyGate integration is optional and falls back to neutral scoring when unavailable. The filter is pure computation with no I/O.
**Rationale:** Working memory previously admitted all records equally, so routine noise competed with duty-relevant observations, alerts, and trusted-agent messages. Salience scoring filters noise while preserving a low default threshold so normal signal continues to promote.
**Status:** Implemented

### AD-667: Named Working Memory Buffers

**Date:** 2026-04-27
**Decision:** Added four named semantic buffers (Duty, Social, Ship, Engagement) as a parallel index alongside existing ring buffers in AgentWorkingMemory. Entries are dual-written to both legacy ring buffers and the appropriate named buffer. render_context() is unchanged; new render_buffers() method enables selective access. Legacy persistence format gracefully degrades with named buffers starting empty on old data.
**Rationale:** Enables chain steps to request only relevant context (AD-671), reduces token waste, and establishes the buffer abstraction needed for metabolism (AD-668), attention gating (AD-669), and diagnostics (AD-672).
**Alternative rejected:** Replacing ring buffers entirely — too much call-site churn for no immediate benefit. Dual-write adds small routing overhead per record method but preserves full backward compatibility.
**Status:** Implemented

### AD-666: Agent Sensorium Formalization

**Date:** 2026-04-27
**Decision:** Formalized CognitiveAgent context injections as an Agent Sensorium with a three-layer `SensoriumLayer` classification, class-level `SENSORIUM_REGISTRY`, aggregate char-budget tracking, `SensoriumConfig`, and `SENSORIUM_BUDGET_EXCEEDED` event emission.
**Rationale:** Ambient Awareness work needs a named inventory and budget signal before adding more context surfaces. This AD adds observability and documentation without moving, renaming, or restructuring existing injection methods.
**Status:** Implemented

### AD-603: Anchor Recall Composite Scoring

**Date:** 2026-04-27
**Decision:** Added `recall_by_anchor_scored()` to apply the full `score_recall()` composite pipeline to anchor-retrieved episodes, then updated CognitiveAgent recall merging so scored anchor and semantic populations are deduplicated and sorted by `composite_score`.
**Rationale:** Anchor recall previously produced raw episodes while semantic recall produced scored results. The merge favored anchor results by position, allowing low-quality structural matches to outrank stronger semantic memories. Scoring both populations puts anchor, semantic, keyword, trust, Hebbian, recency, temporal, and importance signals on the same ranking surface while preserving `recall_by_anchor()` for bulk enumeration callers.
**Status:** Implemented

### AD-585: Tiered Knowledge Loading

**Date:** 2026-04-27
**Decision:** Add a three-tier knowledge loading service that supplies ambient, contextual, and on-demand snippets to CognitiveAgent prompts through a shared TieredKnowledgeLoader wired during startup finalization.
**Rationale:** Existing cognitive prompts loaded broad standing-order context but lacked task-aware knowledge depth. The tiered model keeps always-needed knowledge cheap, adds intent-scoped context automatically, and preserves deeper retrieval for explicit on-demand use without duplicating knowledge-store logic.
**Status:** Implemented

### AD-651: Standing Order Decomposition

**Date:** 2026-04-27
**Decision:** Decompose monolithic standing orders into step-specific instruction slices using category markers in markdown files and a StepInstructionRouter class.
**Rationale:** Each cognitive chain step (analyze, compose, evaluate, reflect) receives only the standing order sections relevant to its role, reducing token waste and instruction dilution. Backward compatible via fallback when no markers exist.
**Status:** Implemented

### BF-243 — getattr guards for __new__ test pattern (2026-04-27)

**Context:** Build wave 3eab2c7 (AD-601/494/595e) added new `__init__` attributes (`_tcm`, `_trait_adaptive_enabled`, `_qualification_standing`, `_novelty_gate`) to EpisodicMemory, ProactiveCognitiveLoop, and CognitiveAgent. 108+ tests use `ClassName.__new__(ClassName)` to bypass expensive `__init__` and set only needed attributes. These tests crash with `AttributeError` on the new attributes.
**Decision:** Fix at the source (access sites) with `getattr(self, '_attr', default)` guards rather than patching 50+ test files. The `__new__` pattern is a valid testing idiom for these large classes. Source-side guards are minimal, self-documenting, and protect against future `__new__` usage.
**Consequences:** All `__new__`-based tests pass without modification. Future `__init__` attribute additions should follow the same `getattr` pattern at access sites if the attribute is accessed outside the constructor path.

### AD-601 — TCM Temporal Context Vectors (2026-04-26)

**Context:** Temporal context was encoded as discrete watch_section labels (7 naval watches), producing binary match/mismatch scoring with no proximity gradient. Two episodes 5 minutes apart scored identically to two episodes 3 hours apart within the same watch.
**Decision:** Implemented Howard & Kahana (2002) Temporal Context Model. A d=16 context vector drifts via exponential decay (rho=0.95) on each episode encoding. Cosine similarity between current and stored context vectors provides smooth temporal proximity in score_recall(). Legacy episodes (no TCM vector) fall back to BF-147/BF-155 binary watch_section logic. Hash-based projection (not embedding truncation) generates deterministic episode fingerprints. TCM weight=0.15 in composite score replaces most of the 0.25 match / 0.15 penalty binary temporal signal, with residual 0.05 watch_section match for backward compatibility. No migration of existing episodes — gradual adoption as new episodes are stored.
**Consequences:** Temporal recall quality improves for agents with 10+ episodes. Watch boundaries no longer create artificial discontinuities. Config-driven: tcm_enabled, tcm_dimension, tcm_drift_rate, tcm_weight, tcm_fallback_watch_weight all tunable in MemoryConfig.

### AD-556 — Per-agent adaptive trust anomaly detection

**AD-556: Per-agent adaptive trust anomaly detection.** Trust anomaly detection now maintains a per-agent rolling window of trust score snapshots and computes z-scores against each agent's personal delta baseline. Anomalies must pass both the existing population sigma threshold AND the per-agent z-score threshold (default 2.5σ). Debounce requires 2 consecutive anomalous cycles before escalation. This reduces false positives from naturally volatile agents (Security, Red Team) while maintaining sensitivity for stable agents with genuine degradation. New agents without sufficient history (< 8 snapshots) fall back to population-only detection. Zone model integration unchanged — zone transitions now receive only adaptively-filtered anomalies. Crew-originated: Forge (Engineering) identified feedback loop risk, Reyes (Security) proposed adaptive thresholding, collaborative design 2026-04-01.

### AD-618c — Built-in Bills (2026-04-25)

### AD-618d — HXI Bill Dashboard (2026-04-25)

### BF-041 — HXI SVG Icon System (2026-04-26)
**Context:** HXI Design Principle #3 mandates all icons be inline SVG with strokeWidth 1.5, strokeLinecap round, currentColor. But 18 component files used Unicode text glyphs (▶, ▼, ✕, ●, ⚠, 🔒, 📌, 💬, etc.), causing inconsistent rendering across platforms and breaking the design language.
**Decision:** Created shared SVG glyph component library (`ui/src/components/icons/Glyphs.tsx`) with 25 named components. Each accepts `size`, `className`, `style` props. StatusDone uses `fill="currentColor"` — the one exception to stroke-only rule (semantically correct for "filled" completed state). STEP_ICONS string maps replaced with STEP_ICON_COMPONENTS React component maps in BridgeCards and GlassDAGNodes. IntentSurface's `FeedbackStatus.confirmText` refactored from `string` to `React.ReactNode` to support JSX icon+text values. Typographic separators (`·`, `…`, `─`, `→`) retained as text — they're not icon glyphs. 68 new tests. Grep-verified zero remaining Unicode icon glyphs.

### BF-242 — JetStream Liveness Probe — Circuit Breaker Pattern (2026-04-26)

### AD-492 — Cognitive Correlation IDs — Cross-Layer Trace Threading (2026-04-26)
**Context:** A single cognitive cycle (perceive→decide→act→post) touches CognitiveJournal, EpisodicMemory, Ward Room pipeline, and event payloads — but no shared identifier links these operations. Each step generates its own `request_id` or `entry_id`, making cross-layer trace reconstruction impossible. Diagnosis of "why did agent X post Y?" requires manual timestamp correlation across multiple databases.
**Decision:** Generate a 12-char hex correlation ID (`uuid.uuid4().hex[:12]`, 48 bits entropy) at `perceive()` time. Thread it through the observation dict (natural carrier), store on working memory for downstream consumers, pass to CognitiveJournal.record() (new schema column + index), Episode constructor (new dataclass field), Ward Room post pipeline (debug logging), and all event payloads within the lifecycle. Correlation ID is transient — not serialized in `to_dict()`, cleared after lifecycle completes. Stale IDs from exceptions are harmless (next `perceive()` overwrites). Auto-attached to `record_action()` metadata via working memory.
**Rationale:** Observation dict is the natural carrier — it flows through the entire cognitive pipeline without modification. Working memory provides cross-cutting access for consumers that don't receive the observation dict directly. Transient design avoids polluting persistence with ephemeral trace state. 12 chars (48 bits) gives ~281 trillion values — collision-negligible for per-agent per-cycle use. Unlocks AD-669 (cross-thread conclusion sharing) and future depth-based circuit breaker enhancements (AD-488). 21 tests.
**Context:** JetStream can become unresponsive while the NATS TCP connection stays healthy. BF-241 only fires on TCP reconnection. BF-230 handles individual publish fallback but doesn't trigger recovery or reduce the ~11s timeout penalty per event. During dream cycles (20+ events), this creates minutes of stalled publishes.
**Decision:** Track consecutive JetStream publish failures. After 3 consecutive failures (all attempts exhausted per-publish), suspend JetStream and trigger asynchronous recovery. While suspended, publishes bypass directly to core NATS with no timeout penalty. Recovery recreates streams/consumers via `_recover_jetstream()`, then probes with `stream_info()` on the first configured stream. On success, JetStream resumes. On failure, stays suspended until next TCP reconnect. Single-flight guard via `asyncio.Task` reference prevents concurrent recovery tasks. `_on_reconnected()` auto-resumes suspended JetStream. `health()` reports `js_suspended` state. MockNATSBus parity. 16 new tests.
**Rationale:** Three consecutive all-attempts-exhausted failures indicate systemic JetStream failure, not transient jitter. Suspension eliminates timeout penalty immediately for concurrent publishes while recovery runs asynchronously. Probe-then-resume prevents false recovery. Extends BF-229/230/231/232/241 NATS resilience stack. Circuit breaker pattern (Nygard, "Release It!").

### AD-493 — Novelty Gate — Semantic Observation Dedup (2026-04-26)
**Decision:** Per-agent observation fingerprinting using embedding cosine similarity. In-memory ring buffer (50 fingerprints/agent) with 24h time decay. Threshold 0.82 (MiniLM cosine). Three-layer dedup stack: BF-032 Jaccard (fast/word-level) → AD-493 NoveltyGate (semantic/topic-level) → AD-632e Evaluate (LLM/thread-level). Check/record separation — `check()` returns verdict, `record()` stores fingerprint only after successful posting. Fail-open on embedding failures.
**Rationale:** Jaccard similarity is defeated by rephrasing. An agent can say "trust is stable" and "the trust landscape is unchanged" with only ~0.3 Jaccard overlap. MiniLM cosine similarity catches semantic equivalence regardless of wording. In-memory ring buffer avoids persistence overhead — fingerprints are ephemeral and reset on restart, which aligns with the 24h decay window. 0.82 threshold calibrated to block near-paraphrases while allowing genuinely different observations about related topics.
**Alternative considered:** ChromaDB collection per agent for persistent fingerprints. Rejected — persistence overhead for an ephemeral gate, and ChromaDB's top-K query API doesn't naturally express "is anything above threshold?" without scanning all results. Simple list + cosine is O(N) with N ≤ 50.

### AD-494 — Trait-Adaptive Circuit Breaker (2026-04-26)
**Decision:** Circuit breaker thresholds adapt per-agent based on Big Five personality scores. Openness → velocity tolerance (0.6-1.4x), Neuroticism → similarity sensitivity (inverted, 0.8-1.2x), Conscientiousness → cooldown duration (inverted, 0.7-1.3x), Extraversion → amber zone sensitivity (0.6-1.4x). Pure deterministic `compute_trait_thresholds()` function, no ML. `TraitAdaptiveThresholds` frozen dataclass. Lazy registration in proactive loop via `_ensure_agent_traits_registered()`. Safe clamping bounds prevent degenerate thresholds.
**Rationale:** Uniform thresholds penalize naturally curious agents (high O) and under-protect anxious agents (high N). The Navy analogy: a lookout's alertness threshold differs from a helmsman's. Same health protection, different calibration. Backward-compatible — agents without registered traits get uniform thresholds (all multipliers 1.0).
**Alternative considered:** Dynamic threshold learning from runtime behavior patterns. Rejected for V1 — adds complexity and opacity. Personality-based adaptation is explainable, auditable, and deterministic. Dynamic adaptation can layer on top in a future AD.

### BF-207 — Shutdown Race: Episodic Memory Hash Mismatch (Complete Fix)
**Context:** The 5s shutdown timeout in `__main__.py` routinely expired before `episodic_memory.stop()` ran because ~25 service stops, a 1s grace period, and a 2s dream consolidation timeout consumed the budget first. ChromaDB left in inconsistent state → metadata no longer matched content hash on restart → BF-207 warnings on every recall.
**Decision:** Restructured shutdown into Phase 1 (Critical Persistence: dream consolidation → episodic memory close → eviction audit stop) and Phase 2 (Service Cleanup: all other service stops). Phase 1 budget: 2s dream timeout + ~500ms episodic close = ≤3s typical. Timeout increased from 5s to 10s as safety margin — the ordering fix is the real solution, not the timeout increase. Added `sweep_hash_integrity()` startup defense: scans 200 most recent episodes, recomputes hashes, auto-heals mismatches from prior unclean shutdowns. ChromaDB .update() uses native batch API. Three-layer defense-in-depth: (1) clean shutdown ordering (preventive), (2) startup sweep (detective + corrective), (3) existing recall-time auto-heal in `_verify_episode_hash` (last-resort fallback). Adapter stop timeout remains 5s (separate concern).
**Consequences:** Episodic memory close now happens within 3s of shutdown start instead of after 4s+ of service cleanup. Hash mismatches from prior crashes are healed before any agent recalls. Phase 1 elapsed time is logged for regression visibility. Future: if collection sizes grow, sweep's sync ChromaDB calls may need `asyncio.to_thread()` wrapping.

### AD-618e — Cognitive JIT Bridge (2026-04-26)

**Decision:** Bill step completions feed T3 skill proficiency via SkillBridge. Mapping is explicit (StepSkillMapping table), not AI-inferred. Default mappings cover action types; custom mappings can target specific bill+step pairs.

**Rationale:** Explicit mappings are auditable, testable, and don't require ML inference. The Navy PQS model: demonstrated competence at a station earns a qualification. Auto-acquisition at FOLLOW level provides cold-start tolerance while allowing proficiency to grow through repeated execution.

**Alternative considered:** Automatic skill inference from step descriptions using LLM. Rejected — too opaque, too expensive for a side-effect system, and violates "reference, not engine" principle.

### BF-241 — NATS JetStream Reconnect Resilience (2026-04-26)

**Context:** After a NATS server restart mid-session (~13h stable), `_reconnected_cb` only set `connected=True` — it did not recreate streams or re-subscribe JetStream consumers. All `js_publish()` calls failed with "no response from stream" until ProbOS restart. The stream recreation and consumer re-subscription logic already existed inside `set_subject_prefix()` but was not reusable.

**Decision:** Extracted `_recover_jetstream()` from `set_subject_prefix()` (DRY). Two-phase recovery: Phase 1 recreates tracked streams via `recreate_stream()` (BF-232 pattern), Phase 2 deletes stale consumers (BF-223 pattern) and re-subscribes from `_active_subs` tracking (JS entries only, not core). Replaced nested `_reconnected_cb` closure in `start()` with `_on_reconnected()` instance method for testability. Log-and-degrade on partial failure (stream failure must not block consumer re-subscription). `_resubscribing` flag set during Phase 2. MockNATSBus updated for interface parity.

**Consequences:** NATS resilience stack complete: BF-229 (core NATS fallback) → BF-230 (publish retry) → BF-231 (health monitoring) → BF-232 (recreate_stream) → BF-241 (reconnect recovery). Three-layer defense-in-depth: file-backed streams (primary) → reconnect recreation (secondary) → BF-230 publish fallback (tertiary). `set_subject_prefix()` now delegates to `_recover_jetstream()` for stream/consumer recovery, handling only core NATS re-subscription itself.

### AD-664 — EventLog Diagnostic Infrastructure (2026-04-26)

**Context:** EventLog events carried only flat string fields with no structured payload, correlation ID, or parent chain. Root-cause tracing impossible. No agent held formalized EventLog query authority — Engineering diagnostic relay chains dead-ended. Crew-originated (Forge + Anvil, 5 proposals). Issue #337.

**Decision:** Added three columns to EventLog schema: correlation_id (TEXT), parent_event_id (INTEGER), data (TEXT/JSON). Extended log() with keyword-only params (zero existing callers break). log() now returns row ID for parent chaining. Added query_structured() for correlation/event filtering and get_event_chain() for parent-chain traversal. Retrofitted emergent pattern events (consolidation_anomaly, emergence_trends via DreamAdapter), mesh events (intent_broadcast, intent_resolved), and QA events with structured payloads and correlation IDs. Declared eventlog_diagnostic_query capability on EngineeringAgent with _handled_intents gate and LLM instructions; programmatic query handler deferred to follow-up AD (requires skill registration or tool-feeding pattern design). Idempotent schema migration handles existing databases.

**Consequences:** Engineering agents can now terminate diagnostic relay chains by querying structured EventLog data. Causal chains are traceable via correlation_id (e.g., all events from one dream cycle) and parent_event_id (direct predecessor links). Future: migrate remaining callers to structured payloads, add EventLog API router for HXI diagnostic panel, federation-level event correlation.

**Context:** AD-618b delivered BillRuntime and AD-618c delivered built-in bills. No HXI surface existed for bill visibility or manual activation.
**Decision:** Added definition registry to BillRuntime (3 methods: register_definition, list_definitions, get_definition). Router uses BillInstance.to_dict() for instance serialization — the dataclass owns its shape. WebSocket handlers use refetch-on-event pattern (re-fetch full instance list on any bill lifecycle event) rather than partial state patching from event payloads, because AD-618b event payloads are summary-only (no status strings, no timestamps). Activate endpoint looks up BillDefinition first then passes it to activate() — the runtime takes a BillDefinition, not a bill_id string. Cancel endpoint checks bool return from cancel(), then fetches instance for response. Instance assignments endpoint reads instance.role_assignments directly — get_agent_assignments(agent_id) answers a different question ("what bills is this agent in?").
**Consequences:** Captain can view loaded bills, activate manually, monitor step progression, and cancel instances. Future: richer event payloads to eliminate refetch roundtrip, drag-and-drop role reassignment, bill template wizard.

**Context:** AD-618a delivered schema/parser but no actual Bill files exist. Ships need default SOPs available from first boot.
**Decision:** Four initial Bills cover the most common scenarios: emergency response (General Quarters), knowledge work (Research Consultation), incident management (Incident Response), routine operations (Daily Ops Brief). Bills are shipped as code artifacts in src/probos/sop/builtin/, not as Ship's Records documents. Loader functions discover and parse them at startup. Custom bills from Ship's Records are loaded separately and may shadow built-ins of the same slug. Invalid files are logged-and-skipped, not fatal. Incident Response demonstrates XOR gateway with dual-input convergence pattern (downstream step lists both branch outputs as inputs). Schedule triggers (daily_operations_brief cron) are parsed but inert until a future scheduler AD.
**Consequences:** ProbOS ships with usable SOPs out of the box. Report archival is the cognitive skill holder's responsibility (no dedicated WRITE_TO_RECORDS action yet — future AD). Additional bills (Code Review, Onboarding, Self-Mod Review, Federation Handshake) are future ADs. Captain can create custom bills in Ship's Records.

### AD-618b — Bill Instance + Runtime

**Date:** 2026-04-25
**Status:** Complete

**AD-618b: BillRuntime is a stateless in-memory service — BillInstances are transient.** They live for the duration of the SOP execution. Role assignment uses BilletRegistry's existing roster with qualification filtering (WQSB pattern). Step lifecycle is tracked but NOT enforced — agents consult the SOP with judgment ("reference, not engine"). Failed steps cascade to bill failure (future: per-step criticality). No Ward Room push notifications in this AD — agents discover assignments via `get_agent_assignments()`. All timestamps use `time.time()` (wall-clock) — `time.monotonic()` rejected because serialized timestamps must be meaningful across process restarts. `BILL_CANCELLED` is distinct from `BILL_FAILED` — cancellation is intentional (authority decision), failure is unintentional (step error). `allow_partial_assignment` config controls whether bills can activate with unfilled roles (default False). Concurrency limited via `max_concurrent_instances` (default 10). Event emission via late-bound sync callback (same pattern as BilletRegistry, ToolRegistry). AD-618c provides built-in YAML files, AD-618d builds HXI dashboard, AD-618e bridges step completions to Cognitive JIT.

### AD-618a — Bill Schema + Parser

**AD-618a: Bill Schema foundation — YAML-first, BPMN-vocabulary, no execution engine.** Bills are declarative YAML files parsed into BillDefinition dataclasses. Schema uses BPMN vocabulary (XOR/AND/OR gateways, parallel lanes, sub-processes) for multi-agent SOP definition. Parser validates role references (strict when roles section present), branch targets, step ID uniqueness, action types, gateway-branch consistency (XOR/OR require branches), and condition step references (`step:{id}.{output}` validates step ID exists). Bills are stored in Ship's Records (`bills/` subdirectory) as raw YAML — `write_bill()` bypasses `write_entry()` (which wraps in markdown frontmatter, corrupting the YAML); `list_bills()` globs `*.bill.yaml` instead of `*.md`. Design principle: "Reference, not engine" — agents consult Bills with judgment, they are not puppeted by a state machine. No Bill events or runtime execution in AD-618a — those come in AD-618b.

### AD-664 — EventLog Diagnostic Infrastructure (Planned)

**Date:** 2026-04-25
**Status:** Planned

**AD-664: EventLog Diagnostic Infrastructure — Structured Payloads + Query Authority.** Two intertwined gaps identified by 5 crew improvement proposals (Forge + Anvil). **(A) Structured payload gap:** EventLog events emit bare string labels — no structured payload, correlation ID, parent_event_id, or source agent. Root-cause tracing and cross-agent correlation are impossible. 24h dual-path diagnostic confirmed the absence. Solution: structured payload schema on EventLog events. **(B) Query authority gap:** No agent holds confirmed, documented execution authority for scoped EventLog queries. Diagnostic chains dead-end because everyone can forward but nobody can execute. Solution: formalized scoped read authority for Engineering agents. These must be solved together — structured data is useless without query authority, and query authority is useless without structured data to query. **Second batch of crew improvement proposals** from this instance. Issue #337.

### BF-239 — Ward Room Thread Engagement Tracking (2026-04-25)

**Date:** 2026-04-25
**Status:** Closed

**Context:** Agents double-posted in all-hands threads despite four infrastructure dedup layers (BF-234/236/237/197). Root cause: BF-236 checks at dispatch time, but the agent's serial cognitive queue processes intents sequentially — by the time the second intent arrives, the first has completed but the router already dispatched it.

**Decision:** Fix at the agent cognitive layer using working memory engagement tracking, not at the infrastructure layer. Agent registers an ActiveEngagement("ward_room_reply", thread_id) before the cognitive lifecycle and checks for it at handle_intent entry. Cognitive lifecycle extracted to `_run_cognitive_lifecycle` helper; try/finally at call site ensures engagement cleanup on all exit paths (normal, compound early return, exception). Serial queue (max_ack_pending=1) guarantees the check always sees records from prior completions. @mentions and DMs bypass the gate. Infrastructure dedup layers (BF-236, BF-198) retained as defense-in-depth backstops.

**Lesson learned:** Infrastructure guardrails were solving a problem that belonged at the cognitive layer. The agent's working memory already had the primitives (ActiveEngagement) — they just weren't being used for ward room replies. Before adding infrastructure dedup, ask: "Could the agent solve this itself?"

**Consequences:** Five-layer dedup stack. Agent-level fix is zero-token cost (synchronous dict lookup, no LLM call). Future consideration: BF-198's _responded_threads (600s window) may be redundant with engagement tracking + BF-236's round tracker.

### BF-237 — Pipeline-level post budget (Closed)

**Date:** 2026-04-25
**Status:** Accepted

**BF-237: Single-invocation post budget prevents N+1 posts per pipeline run.** When an LLM response contains multiple `[REPLY]` blocks or a `[REPLY]` plus residual text, the proactive loop's `_extract_and_execute_replies()` fires `create_post` for each block, then `process_and_post()` Step 7 fires another `create_post` for the cleaned remainder — producing N+1 posts from a single invocation. Observed as Atlas posting two near-identical analyses of the same observation.

Fix: `PostBudget` dataclass (`spent: bool = False`) threaded from `process_and_post()` through `extract_and_execute_actions()` → `_extract_and_execute_actions()` → `_extract_and_execute_replies()`. The first `create_post` in the reply loop sets `budget.spent = True`; subsequent `[REPLY]` blocks and the Step 7 main post check the budget and skip with a warning log. Same gate applied to `[MOVE]` board posts in the recreation extraction loop. `post_budget=None` backward-compatible — no budget enforcement, all posts fire (matches pre-BF-237 behavior).

Steps 8-10 (record_agent_response, record_round_post, update_cooldown) remain UNCONDITIONAL — they must run whether or not Step 7 posted, to keep BF-236's round tracker accurate.

Telemetry event `pipeline_post_budget_exceeded` emitted on suppression for observability.

Completes the four-layer dedup stack: BF-234 (transport, identical intent IDs) → BF-236 (dispatch, round-scoped tracker) → BF-237 (pipeline, single-invocation budget) → BF-197 (content, similarity guard).

### BF-236 — Semantic duplicate dispatch gap (Open)

**Date:** 2026-04-25
**Status:** Open

**BF-236: Dispatch eligibility missing `has_agent_responded()` gate.** BF-234 closed the transport-layer duplicate gap (identical intent IDs from JetStream redelivery). BF-198 added semantic round-tracking via `has_agent_responded()` / `record_agent_response()`. But BF-198's gate is only enforced during proactive context gathering (`proactive.py`), not during reactive dispatch eligibility (`_route_to_agents()` in `ward_room_router.py`). Result: two `route_event()` calls racing past eligibility checks before either records a response → agent dispatched twice → composes two near-duplicate posts with different wording. Observed on 6/12 agents on a single Improvement Proposals thread. Fix: add `has_agent_responded()` check in `_route_to_agents()` alongside existing cooldown and round-participation filters. This is the dispatch-level gate BF-234's DECISIONS.md entry deferred to BF-236 ("Post-boundary defense deferred to BF-236 if consumer-side counter shows residual duplicates"). Issue #339.

### BF-235 — Stale Identity Rendering (Closed)

**Date:** 2026-04-25
**Status:** Accepted

Two `@lru_cache` decorators in `standing_orders.py` (`_load_file` and `_build_personality_block`) persist indefinitely within a process. On stasis resume, these caches served stale identity blocks (wrong callsign, CMO, peers) to `compose_instructions()`, which is called on every `decide()` cycle. The module-level `_DECISION_CACHES` dict in `cognitive_agent.py` compounded the issue by serving stale decisions (produced with old system prompts) for up to 3600s.

Fix: call `clear_cache()` and `evict_cache_for_type()` for all crew agents during stasis recovery in `finalize.py`, unconditionally on `_lifecycle_state == "stasis_recovery"` (not gated behind `warm_boot_orientation` config). Added defensive `clear_cache()` on all startups for test surface uniformity. Added diagnostic logging of callsign at orientation time.

This completes the identity restoration chain: BF-057 (callsign from birth cert) → BF-101 (fallback resolution) → BF-049 (ontology sync) → BF-083 (runtime override) → BF-235 (cache invalidation).

**Alternatives considered:**
- Adding TTL to `@lru_cache` — rejected: Python's `lru_cache` doesn't support TTL natively. Adding `cachetools.TTLCache` would introduce a dependency for a problem that only occurs at stasis boundaries.
- Clearing caches inside `set_orientation()` — rejected: `set_orientation` is called in other contexts (cold start, re-orientation commands) where cache invalidation may not be needed. Startup is the right boundary.
- Gating cache invalidation behind `warm_boot_orientation` config — rejected: cache staleness is a lifecycle event (stasis resume), not a rendering policy. If an operator disables warm-boot orientation, the bug would return. Invalidation must be unconditional on stasis resume.

### BF-234 — Consumer-side dispatch dedup

**BF-234: Consumer-side dispatch dedup is the authoritative gate against transport-layer duplicates.** Gate placed in `IntentBus._on_dispatch()` (JetStream consumer callback in `intent.py`), not in the router (publisher side). Router dispatches exactly once — the duplication happens at or after JetStream publish (BF-230 retry, server redelivery). Only the consumer sees the second copy. Scoped to `ward_room_notification` intent type only. Window is 300s (matches JetStream `ack_wait=300` in `_js_subscribe_agent_dispatch`) — with `max_ack_pending=1`, msg #2 queues behind msg #1's full cognitive chain, so the window must cover max handler duration. BF-198 `has_agent_responded()` / `record_agent_response()` remain semantic round-tracking for proactive-loop dedup — different invariant, different window, different key. Post-boundary defense (pipeline-level gate) deferred to BF-236 if consumer-side counter shows residual duplicates.

### BF-236 — Round-scoped post tracker

**BF-236: Round-scoped post tracker is the correct invariant for dispatch-level semantic dedup — not BF-198's `_responded_threads`.** BF-198 tracks `(agent_id, thread_id)` with 600s eviction for proactive-loop dedup; reusing it as a dispatch gate would block agents from responding to Captain follow-ups for 10 minutes. BF-236 adds a separate `_posted_in_round` tracker (same key shape, different lifecycle): cleared on Captain repost alongside `_round_participants` so agents become eligible again when the Captain follows up. Recorded by WardRoomPostPipeline after `create_post` (not at delivery) — only real posts register, avoiding false positives from agents dispatched but filtered by BF-197 or LLM error. Coverage is partial (honest): catches duplicates when multi-second LLM handler latency means the first post is recorded before the second `route_event()` runs eligibility. Sub-second rapid-fire races fall through to BF-234 (transport-layer dedup on identical intent IDs) and BF-197 (content similarity guard). Ordering between post-event-fan-out and `record_round_post` is best-effort; race is bounded by Python's single-threaded asyncio scheduling and rarely matters in practice. Three defense-in-depth layers: BF-234 (transport) → BF-236 (dispatch, round-scoped) → BF-197 (content).

### BF-233 — Grounding check false positive fix

**Date:** 2026-04-24
**Status:** Complete

**BF-233: Expand BF-204 grounding source with entity IDs from input context.** The deterministic confabulation check (BF-204) built its grounding source from thread text + ANALYZE result only, missing entity IDs the agent was explicitly given in params (thread_id, channel_id, author_id) and identity keys (_agent_id, intent_id). Agents referencing these legitimate IDs in compose output triggered false positive suppression — observed across 7+ agents on Captain's All Hands message. Fix appends entity IDs to the grounding source string. Only IDs from the agent's own input context are whitelisted; truly fabricated hex IDs are still caught (threshold >= 2 ungrounded). BF-204 core protection preserved. **Known limitation:** Cross-agent post UUID references (other agents' full post UUIDs not in the responding agent's params) may still trigger false positives if agents use the full UUID instead of the truncated 8-char bracket form from thread context. Mitigated by agents naturally using `[deadbeef]` truncated form. Future fix: router could append full post UUIDs to params if observed in production.

### BF-232 — ensure_stream uses recreate_stream for stale subject cleanup

**Date:** 2026-04-24
**Status:** Complete

**BF-232: Split ensure_stream / recreate_stream.** Completes the BF-229/230/231 NATS resilience trilogy. The add-or-update pattern in `ensure_stream()` silently failed to change subject filters when prefixes changed across boots — `update_stream()` on some NATS server versions is a no-op for subject changes (BF-231 finding). New `recreate_stream()` method uses delete-then-create for explicit recreation. `ensure_stream()` retains non-destructive add-or-update semantics for future idempotent callers. Phase 2 startup and `set_subject_prefix()` use `recreate_stream()`. `_delete_stream()` warning logging now distinguishes benign "not found" (DEBUG) from real failures (WARNING). Stream retention sacrifice is acceptable — all current streams are transient event buses (max_age 5–60 min).

---

### AD-599 — Reflection as Recallable Episodes

**Date:** 2026-04-26
**Status:** Complete
**Issue:** #173

**AD-599: Dream Step 15 promotes consolidation insights into recallable episodes.** Dream consolidation (Steps 7–14) produces high-value analytical insights locked in write-only storage (CognitiveJournal, Ship's Records). Step 15 creates `[Reflection]` episodes in EpisodicMemory from four sources: convergence reports, emergence snapshots, notebook consolidations, and dominant cluster patterns. `MemorySource.REFLECTION` source tag. Deterministic `reflection-{content_hash}` IDs prevent cross-cycle duplication via existing write-once guard. `agent_ids=[]` bypasses per-agent rate limiting; agent participation preserved in `dag_summary["involved_agents"]`. Rate-limited to 3 per cycle (configurable). No LLM calls — reflections composed from structured data already computed by earlier steps.

**Alternative considered:** LLM-synthesized reflections for richer language. Rejected — adds latency, cost, and non-determinism. Structured composition is sufficient because ChromaDB semantic search handles fuzzy matching.

---

### AD-595e — Qualification Gate Enforcement

**Date:** 2026-04-26
**Status:** Complete
**Parent:** AD-595 (Billet-Based Role Resolution)

**AD-595e: Enforcement gates at three cognitive pipeline points.** Gates at bill step start (BillRuntime), proactive duty dispatch (ProactiveCognitiveLoop), and agent context injection (CognitiveAgent). Two-flag config: `enforcement_enabled` (default false) + `enforcement_log_only` (default true) enables shadow mode rollout — runs checks and emits QUALIFICATION_GATE_BLOCKED events but does not block. All gates default ALLOW for graceful degradation (missing store, missing registry, exception → pass through). Breaking change: `BillRuntime.start_step()` is now async. CognitiveAgent caches qualification standing with 5-min TTL to avoid per-decide() async lookups. BilletRegistry gains `get_qualification_standing()` (billet-based summary) and `check_role_qualifications()` (explicit list check). Cold-start tolerance: agents with no test results always pass.

---

### AD-595d — Qualification-Aware Billet Assignment

**Date:** 2026-04-24
**Status:** Complete
**Issue:** #TBD
**Parent:** AD-595 (Billet-Based Role Resolution)

**AD-595d: Data model + check API, no production gate.** Billets can declare `required_qualifications` (list of test names from AD-539). `check_qualifications()` async method verifies agent results from QualificationStore. `assign_qualified()` combines check + assign in one call. `allow_untested` parameter handles cold-start (no test results yet → allow) vs promotion (must have passed → block). `assign()` is NOT modified — stays sync and unconditional. Production assignment path (`agent_onboarding.py`) still calls `assign()`, unchanged. Gate enforcement deferred to AD-595e (promotion workflow). This split avoids the incoherent middle ground of logging-but-not-blocking and lets the data model ship immediately.

---

### AD-595c — Standing Orders Templating — Billet-Aware Instructions

**Date:** 2026-04-24
**Status:** Complete
**Issue:** #165
**Parent:** AD-595 (Billet-Based Role Resolution)

**AD-595c: Post-processing template substitution for billet references.** Standing orders `.md` files can use `{Billet Title}` syntax to reference billets dynamically. Resolution happens as a post-processing pass in `compose_instructions()`, after all tiers are concatenated. Existing hardcoded references ("the Chief Engineer") still work — template syntax is opt-in. Filled billets render as `Callsign (Title)`, vacant billets render as `Title (vacant)` — giving agents an explicit signal to escalate up the chain rather than messaging a non-existent holder. Code blocks (``` and ~~~) and inline backtick spans are excluded from processing. Known limitation: multi-backtick inline code spans (``` ``code`` ```) are not handled; authors should avoid `{Title}` inside inline code. The substitution runs per compose_instructions() call (called each decide() cycle) without caching — currently sub-millisecond on ~30KB text; if profiling shows cost, add version-keyed cache. Module-level `_billet_registry` state follows existing standing_orders.py module pattern (file caches are also module-scoped). No changes to existing standing orders files — this just enables future use.

---

### AD-595b — Naming Ceremony → BilletRegistry Integration

**Date:** 2026-04-24
**Status:** Complete
**Issue:** #165
**Parent:** AD-595 (Billet-Based Role Resolution)

**AD-595b: Billet assignment coupled to naming ceremony.** Added `BilletRegistry.assign()` — validates post exists, emits `BILLET_ASSIGNED`. Does NOT write to DepartmentService (ontology already has the assignment). Billet assignment placed as a single block after identity issuance (AD-441c) rather than three separate blocks (cold/warm/non-crew) with tracking flags — simpler, covers all paths uniformly, and `assign()` is idempotent. OrientationContext.billet_title added so agents know their formal billet at cognitive grounding time, enriched via `dataclasses.replace()` on the frozen dataclass.

---

### AD-595a — BilletRegistry Foundation

**Date:** 2026-04-24
**Status:** Complete
**Issue:** #165
**Parent:** AD-595 (Billet-Based Role Resolution)

**Decision:** BilletRegistry is a read-side facade over DepartmentService (Interface Segregation) — it does NOT own billet data, DepartmentService remains source of truth for posts and assignments. Title-based resolution is case-insensitive via a lowercase title→post_id index built eagerly in the constructor. BilletHolder is a frozen dataclass to prevent accidental mutation that drifts from DepartmentService. Registry is eagerly initialized in `VesselOntologyService.initialize()` (not lazy) to avoid race conditions. Event callback is late-bound in `finalize.py` via `set_event_callback()` because the event bus isn't available during ontology construction. BILLET_ASSIGNED/BILLET_VACATED event types are reserved — actual emission deferred to AD-595b when assign/vacate mutators are added. Follows the Navy Watch Bill model: billets are permanent positions, agents rotate through them. 17 new tests.

**Key decisions:**
| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Facade, not replacement | DepartmentService is mature + tested; BilletRegistry adds title resolution and roster snapshots without duplicating data |
| 2 | Frozen BilletHolder | Prevents snapshot mutation that silently drifts from source of truth |
| 3 | Eager init, not lazy | Race conditions: multiple callers could trigger concurrent initialization |
| 4 | Late-bound event callback | Event bus unavailable during Phase 3 ontology construction; wired in Phase 8 finalize |

---

### AD-584d — Elaborative Encoding via Enriched Embeddings

**Date:** 2026-04-24
**Status:** Complete
**Depends on:** AD-584c (scoring rebalance), AD-605 (anchor-enriched document)

**Decision:** ChromaDB embedding document now includes reflection text (aligning with FTS5 which already indexed it) and 2-3 heuristic question seeds per episode. Questions are template-based (no LLM call) using intent_type, outcome results, and department. Reflection is NOT templated into questions — it's already in the embedding text, and templating produces grammatically broken questions that hurt embedding quality. This bridges the Q→A retrieval gap: when agents recall with question-like queries, the question seeds create direct semantic overlap with stored episodes. Note: embedding now includes agent reflection content — recall queries may match on agent meta-commentary, not just observed events. This aligns with FTS5 behavior (which already indexed reflections). Research basis: Craik & Tulving (1975) depth of processing. Existing episodes are NOT retroactively re-embedded — new enrichment applies to episodes stored after deployment. 15 new tests.

---

### BF-231 — Delete-and-Recreate JetStream Streams on Prefix Change

**Date:** 2026-04-24
**Status:** Closed

**Decision:** `set_subject_prefix()` previously called `ensure_stream()` which tried `add_stream()` → fallback `update_stream()`. Subject filter updates could silently fail on some NATS server versions, leaving streams with stale DID prefixes after `probos reset`. Fix: delete the stream first, then recreate with correct subjects. Safe because ProbOS JetStream streams are transient event buses with short retention (5-60 min max_age). BF-223's per-consumer cleanup is preserved as defense-in-depth — stream deletion cascades to consumer deletion, making BF-223's explicit `delete_consumer()` calls largely redundant, but they guard consumers on streams not tracked in `_stream_configs`. Alternative considered: flushing streams in `probos reset` — rejected because `set_subject_prefix()` is the right fix location (handles any prefix change, not just reset, and works even if NATS wasn't running during reset). Completes BF-229/230/231 trio — closes the entire class of "JetStream silently dropped events after DID change" incidents. 5 new tests.

---

### AD-673 — Automated Anomaly Window Detection

**Date:** 2026-04-26
**Status:** Closed
**Depends on:** AD-662 (AnchorFrame provenance fields), AD-663 (producer wiring)

**Decision:** AD-673: AnomalyWindowManager populates AnchorFrame.anomaly_window_id. Triggered by trust cascade and LLM health events via _add_event_listener_fn pattern. Single concurrent window model. Episodes stamped during store() via dataclasses.replace on frozen AnchorFrame. Retrospective tagging deferred (stub only).

---

### AD-665 — Corroboration Source Validation

**Date:** 2026-04-27
**Status:** Complete
**Depends on:** AD-662 (provenance infrastructure — COMPLETE), AD-663 (producer wiring — COMPLETE)

**Decision:** Replace binary shared-ancestry veto in `compute_anchor_independence()` with graded provenance weights. Same-origin-different-version pairs receive configurable `version_independence_weight` (default 0.7, no empirical basis — tunable per deployment). Single score, no dual-score `min()` combination — graded weight integrates directly into the existing independence formula. Anomaly discount (pair_weight denominator) and version independence weight (numerator credit) are orthogonal, no double-counting. `ProvenanceValidationResult` provides structured diagnostic report without exposing content (privacy invariant preserved). Transitive ancestry (A→B→C chains) explicitly deferred — requires `AnchorFrame` schema extension not yet designed. 16 new tests including privacy boundary verification. Triggered by Reed (Science) improvement proposals.

---

### AD-663 — Provenance Producer Wiring (2026-04-26)
**Context:** AD-662 added consumer-side provenance validation (`_share_artifact_ancestry`, anomaly window discount) but no producer populates the three AnchorFrame provenance fields. AD-665 adds graded scoring but is production no-op without populated fields. BF-226/227 demonstrated the failure mode: multiple agents observe the same WR post during queue pressure, observations pass spatiotemporal independence checks but share corrupted ancestry.
**Decision:** Wire 4 highest-risk episode producers to populate `source_origin_id` and `artifact_version` at AnchorFrame construction. Dream consolidation reflections deferred — deterministic episode IDs already provide dedup, and provenance fields would encode the same content_hash as both origin and version, adding no independent signal. Provenance strategy is site-specific: WR uses post/thread IDs with type prefixes (`wr-post:`, `wr-thread:`), proactive uses observed WR post IDs from context, cognitive agent uses correlation_id. Version fingerprints use SHA-256 truncated to 16 hex chars. `anomaly_window_id` explicitly deferred — no automated anomaly detection infrastructure exists. Remaining producers (no-response, peer repetition, feedback, smoke test, DM) are low corroboration risk and retain empty provenance.
**Consequences:** AD-662's consumer-side checks become active for new WR-derived episodes. AD-665's graded scoring will work for post-edit scenarios (same origin, different body hash → different artifact_version). Agents observing the same WR post during different duty cycles now trigger shared-ancestry detection. Legacy episodes retain empty provenance and are treated as independent (no behavioral change for existing data).

---

### AD-662 — Corroboration Source Provenance Validation

**Date:** 2026-04-23
**Status:** Complete
**Depends on:** AD-567f (Social Verification Protocol)

**Decision:** Extend SocialVerificationService with source provenance tracking. Three new AnchorFrame fields (source_origin_id, artifact_version, anomaly_window_id) enable ancestry-based independence checks. Two observations sharing the same source artifact are NOT independently anchored, regardless of spatiotemporal separation. Anomaly window observations contribute at config-driven discounted weight (default 0.5) to independence scoring (log-and-degrade, not reject). `artifact_version` alone does not trigger shared ancestry — only `source_origin_id` match does — to avoid false positives from version string collisions. Triggered by BF-226/227 where queue-pressure-generated artifact versions appeared to corroborate each other but shared corrupted ancestry. AD-662 is infrastructure-only (consumer-side validation); AD-663 wires the producers to populate provenance fields at AnchorFrame construction sites. 13 new tests.

---

### AD-654 — Universal Agent Activation Architecture (UAAA)

**Date:** 2026-04-21  
**Status:** In Progress (AD-654a complete, AD-654b complete, AD-654c complete, AD-654d complete, e deferred)  
**Depends on:** AD-637 (NATS Event Bus)  
**Research:** `docs/research/universal-agent-activation-research.md`

**Decision:** Implement event-driven agent activation using NATS JetStream durable consumers instead of synchronous NATS request/reply. Five sub-ADs:

1. **AD-654a (Async Dispatch):** Ward room router publishes notifications to JetStream fire-and-forget. Agents consume at their own pace and post their own responses. Eliminates the NATS send timeout cascade where 14 simultaneous request/reply calls block during LLM processing. New `WardRoomPostPipeline` extracts post-processing (similarity guard, endorsements, recreation commands) from both the router and proactive loop into a reusable pipeline class. `IntentBus.publish()` added for fire-and-forget; `send()` preserved for genuinely synchronous callers (Captain DMs, procedure steps).

2. **AD-654b (Cognitive Queue):** Per-agent priority mailbox (Actor Model). Three tiers: immediate (< 10s), soon (30-60s), ambient (proactive cycle). Proactive timer becomes the ambient processor. Higher-priority items bypass cooldown.

3. **AD-654c (TaskEvent + Dispatcher):** Universal event protocol. TaskEvent dataclass with source, priority, target (agent/capability/department/broadcast), payload. Dispatcher resolves abstract targets using Qualification Framework, Trust/Rank, Workforce Scheduling.

4. **AD-654d (Internal Emitters):** RecreationService, WardRoom @mentions, WorkItem state transitions, agent-to-agent delegation all become TaskEvent emitters.

5. **AD-654e (External Integration):** MCP Apps, MCP Provider/Consumer, webhook adapters. Deferred until Phase 1-3 validated.

**Key architectural principles (from research paper):**
- Events, not polling — proactive scan is fallback, not primary
- Priority is semantic, not structural — comes from TaskEvent, not delivery mechanism
- Context travels with the event — focused payload, not ambient scanning
- Dispatcher is the control point — all activation flows through it
- Emitters don't know about agents — decoupled via target abstraction
- Backward compatible — existing proactive loop, DM router continue working

**Why not keep request/reply:** NATS request/reply has a TTL timeout. Agent handlers take 15-30s for cognitive chains. When an agent is busy processing one intent, subsequent requests timeout. This is fundamentally incompatible with notification-style intents where the caller doesn't need a synchronous response. JetStream publish + durable consumer eliminates timeouts entirely — messages queue and agents drain at their own pace.

**Why agents self-post (not router):** The router collecting and re-posting agent responses is an intermediary that adds latency and coupling. In an event-driven model, agents should post their own ward room responses — the same way humans type replies in a chat room. This aligns with agent sovereignty (the agent decides what to post) and eliminates the synchronous gather pattern.

**BF-223 (2026-04-22) — JetStream durable consumer prefix race.** AD-654a's per-agent dispatch consumers were created during pool onboarding (Phase 3) with `probos.local` prefix. Ship commissioning (Phase 7) changes prefix to `probos.did:probos:{uuid}`. NATSBus.set_subject_prefix() re-subscribes, but NATS server-side durable consumer config retains the original `filter_subject` — re-subscribe silently reuses stale config. All agent dispatch consumers had `delivered_seq=0`. **Fix:** (1) NATSBus safety net: `set_subject_prefix()` deletes old durable consumers before re-creating. (2) IntentBus root fix: defer dispatch consumer creation until `finalize.py` calls `create_dispatch_consumers()` after ship commissioning. This mirrors the wardroom-router consumer pattern that already works. Third NATS prefix bug in the series (BF-221 → BF-222 → BF-223).

**BF-229 (2026-04-23) — NATSBus owns subject sanitization.** Ship DID `did:probos:<uuid>` contains colons, which are invalid in NATS subject tokens. `set_subject_prefix()` now sanitizes via compiled regex — NATS-unsafe characters become underscores. Callers may pass any string (raw DIDs, federation prefixes). Underscores chosen over dots to preserve single-token namespace depth (`probos.did_probos_<uuid>.*` not `probos.did.probos.<uuid>.*`). Fourth NATS prefix bug (BF-221 → BF-222 → BF-223 → BF-229). Also: `ensure_stream()` re-raises after logging (no more silent swallow), stream update failure promoted to ERROR with recovery instructions.

**BF-230 (2026-04-23) — js_publish resilience — bounded retry + degrade-to-core-NATS.** Chose 1 retry with 0.5s backoff + fallback to core NATS publish over alternatives (local buffer-and-replay, unbounded retry). Buffer would require persistence and replay logic — deferred until needed. Fallback to core NATS is best-effort: JetStream-only subscribers (WARDROOM durable, cognitive queue) will NOT receive the event via the fallback path. The fallback's value is crash prevention + server-side trail, not delivery guarantee.

**BF-106 (2026-04-24) — DreamingEngine dependency injection — constructor for Phase 4, setters for Phase 7.** Three monkey-patched private attrs in finalize.py replaced with clean injection. `records_store` forwarded through `init_dreaming()` constructor (available at Phase 5 from Phase 4 cognitive init). `ward_room` and `get_department` (from ontology) genuinely unavailable until Phase 7 — these get public setter methods instead. Follows AD-567d (ActivationTracker) pattern for constructor injection. Establishes the template: constructor injection where startup-phase ordering allows, public setter methods where it doesn't. Generalizes the AD-654c/d Law of Demeter discipline to startup wiring.

---

### AD-641g — Asynchronous Cognitive Pipeline via NATS

**Date:** 2026-04-17  
**Status:** Design  
**Parent:** AD-641 (Brain Enhancement Phase)  
**Depends on:** AD-637 (NATS Event Bus)

**Decision:** Decouple the cognitive chain steps (QUERY → ANALYZE → COMPOSE) via NATS message subjects rather than running them as a synchronous blocking sequence.

**Motivation:** The current chain pipeline adds cognitive depth (multi-step reasoning) but not perceptual depth (ability to see more). The QUERY step only receives what `_gather_context()` already fetched — a fixed sliding window of 5-10 recent items. Agents cannot browse deeper thread history or scan broadly across channels. Evidence: agent "Lyra" hallucinated a `[READ_CHANNEL]` command tag — the LLM expressing a genuine need the architecture doesn't provide.

**Design:**
- QUERY (browse) runs frequently, 0 LLM calls, publishes interesting items to `chain.{agent_id}.analyze`
- ANALYZE subscribes, processes selectively with LLM, gates whether a response is warranted
- COMPOSE only fires when ANALYZE says something is worth saying
- NATS provides backpressure, priority ordering, durable queues, and consumer groups
- Pattern is source-agnostic: same pipeline extends to document reading, web research, ship's state observation

**Research:** [docs/research/ad-641g-async-cognitive-pipeline.md](docs/research/ad-641g-async-cognitive-pipeline.md)

**Migration note (AD-644 Phase 3):** AD-644 Phase 3 migrates 7 environmental percepts (ward_room_activity, recent_alerts, recent_events, infrastructure_status, subordinate_stats, cold_start_note, active_game) into the cognitive chain via observation dict pass-through from `context_parts`. This is a temporary approach — `_gather_context()` in proactive.py already calls the underlying services, so creating QUERY operations that re-call the same services would violate DRY. When NATS decouples the pipeline (this AD), these 7 percepts should become native QUERY operations in `query.py` that subscribe to NATS subjects directly, replacing both the `_gather_context()` calls and the `_build_situation_awareness()` pass-through. The detection logic in `_build_situation_awareness()` is transport-agnostic and reusable.


### AD-643a — Intent-Driven Skill Activation

**Date:** 2026-04-18
**Status:** Complete
**Issue:** #283

**Decision:** Move augmentation skill loading from before the cognitive chain to after ANALYZE. Skills declare `probos-triggers` metadata; ANALYZE outputs `intended_actions`. Only skills whose triggers match the agent's expressed intent are loaded.

**Motivation:** All augmentation skills loaded on every `proactive_think` cycle regardless of what the agent intended to do. ~1,500 wasted tokens/cycle × 30 agents × 5 cycles = ~225K tokens/session. Communication chain fired for notebooks, leadership reviews — wrong chain for the action.

**Design:**
- `CognitiveSkillEntry` gains `triggers: list[str]` field, parsed from `probos-triggers` YAML metadata
- `find_triggered_skills()` matches `intended_actions` to skill triggers (falls back to intent matching for skills without triggers)
- Two-phase execution: triage (QUERY + ANALYZE) → extract `intended_actions` → route → targeted skill loading → execute (COMPOSE + EVALUATE + REFLECT)
- Communication chain only fires when `intended_actions` contains a comm action (`ward_room_post`, `ward_room_reply`, `endorse`, `dm`)
- Non-comm actions (notebook, leadership_review) skip chain, fall through to `_decide_via_llm()` with targeted skills
- Silent short-circuit at triage phase (no COMPOSE/EVALUATE/REFLECT)
- External chains (`_pending_sub_task_chain`) bypass intent routing (backward compat)
- Missing `intended_actions` falls back to pre-AD-643 all-skills behavior (backward compat)

**Research:** BDI plan library (Rao & Georgeff), OODA loop, Dual Process Theory (Kahneman). ANALYZE = System 1/2 gate. All BDI limitations addressed by existing ProbOS architecture (episodic memory, Ward Room, trust, standing orders, workforce scheduling, SOPs).

**Key decisions:**
| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Triggers on skills, not on chains | Open/Closed — new skills register triggers without modifying chain code |
| DD-2 | Triage re-executes on full chain path | Avoids modifying SubTaskExecutor; ~200 token overhead acceptable; AD-643b eliminates this |
| DD-3 | Non-comm actions skip chain entirely | No compose/evaluate/reflect templates exist for notebooks yet — AD-643c adds them |
| DD-4 | `intended_actions` is a JSON array, not enum | Extensible vocabulary; new thought processes add new action tags without prompt changes |

**Future:** AD-643b (Thought Process Catalog — declarative `ThoughtProcess`/`ThoughtAction` definitions replace hardcoded chains), AD-643c (multi-action processes + sequential execution).

---

### AD-643b — Skill Trigger Learning: Adaptive Trigger Discovery & Graduation

**Date:** 2026-04-18
**Status:** Complete (Phase 1+2 of 3; Phase 3 graduation deferred)
**Issue:** #284

**Motivation:** AD-643a requires agents to declare `intended_actions` for skills to load, but agents sometimes take undeclared actions (e.g., writing a notebook without declaring `notebook`). Quality skills don't load, degrading output. At scale (100+ triggers), injecting full trigger lists into prompts defeats token savings.

**Design:** Three-phase trigger learning lifecycle:
1. **Trigger Awareness** — inject scoped trigger list into ANALYZE (filtered by department + rank). Training wheels.
2. **Post-Hoc Feedback** — detect undeclared actions in COMPOSE output, inject feedback into REFLECT → episodic memory → future recall. Closed learning loop.
3. **Trigger Graduation** — track declaration accuracy per agent. Consistently correct → graduate (remove from prompt). Dreyfus progression: novice→expert. Prompt overhead trends to zero.

**Research:** Metacognitive monitoring (Flavell 1979), scaffolding→fading (Wood/Bruner/Ross 1976), situated cognition (Lave & Wenger 1991). Extends AD-535 Dreyfus model to trigger declarations.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DD-1 | Per-agent scoping, not global injection | Eligible triggers filtered by department + rank; ~15-25 tags per agent, not 100+ |
| DD-2 | Post-hoc detection, not capability gating | Skills are guidance, not gates; agent can still write notebook without skill loaded |
| DD-3 | Episodic memory as learning medium | REFLECT feedback → episodic storage → future recall. No new infrastructure |
| DD-4 | Graduation reduces overhead over time | Training wheels self-remove; mature crews have zero trigger injection overhead |
| DD-5 | Three-phase delivery | Each phase independently valuable and backward compatible |
| DD-6 | Re-reflect is a synchronous workaround | NATS decoupling (AD-643d) replaces re-reflect with message-flow interception |

---

### AD-643d — NATS-Based Trigger Feedback Pipeline

**Date:** 2026-04-18
**Status:** Deferred — blocked on AD-637 (NATS Event Bus)
**Parent:** AD-643 (Intent-Driven Skill Activation)
**Depends on:** AD-637 (NATS), AD-643b (trigger learning)

**Decision:** Refactor AD-643b's re-reflect workaround into a native NATS message-flow pattern once the cognitive pipeline is decoupled via NATS subjects (AD-641g).

**Motivation:** AD-643b detects undeclared actions *after* the full chain completes, then re-runs REFLECT as a partial chain to inject feedback into episodic memory. This works but is a synchronous workaround — the chain runs, completes, then a second REFLECT fires. With NATS subjects decoupling each chain step, trigger detection becomes a natural consumer in the message flow rather than a post-hoc re-run.

**Design (sketch — refine when AD-637 lands):**

Three options, not mutually exclusive:

1. **Intercept consumer.** A trigger-detection consumer subscribes to `chain.{agent_id}.compose.complete`. It inspects compose output for undeclared actions, enriches the observation with `_undeclared_action_feedback`, and forwards to `chain.{agent_id}.evaluate`. REFLECT receives feedback naturally — no re-run.

2. **BPMN-style gateway.** Exclusive gateway after COMPOSE: clean path (no undeclared actions) routes directly to EVALUATE; feedback path routes through DETECT → ENRICH → EVALUATE. Maps to BPMN 2.0 (ISO 19510:2013) process modeling. The chain becomes a declarative flow graph, not imperative code.

3. **Retriggerable REFLECT.** REFLECT subscribes to `chain.{agent_id}.reflect`. On undeclared action detection, publish a second message to the same subject with feedback. Both reflections enter episodic memory. Zero chain modification.

**What survives from AD-643b:** `_detect_undeclared_actions()` detection logic, feedback format, `get_eligible_triggers()` awareness injection, graduation tracking (Phase 3). Only the orchestration wrapper (`_re_reflect_with_feedback`) gets replaced.

**What gets removed:** `_re_reflect_with_feedback()`, `_re_reflect_compose_output` observation key, `_get_compose_output()` fallback parameter.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DD-1 | Deferred until NATS lands | Re-reflect works; refactoring before NATS exists is premature |
| DD-2 | Option 1 (intercept) is likely default | Simplest, preserves single REFLECT execution, no duplicate episodic entries |
| DD-3 | AD-643b detection logic reused as-is | Pattern matching is transport-agnostic |

---

### AD-637z — NATS Migration Cleanup + BF-221 Lift

**Date:** 2026-04-21
**Status:** Complete
**Parent:** AD-637 (NATS Event Bus)
**Closes:** BF-221

**Decision:** NATSBus owns the full subscription lifecycle. External code (IntentBus) subscribes via `nats_bus.subscribe()` and cleans up via `nats_bus.remove_tracked_subscription()` — no parallel tracking dicts. BF-221 emergency guard lifted: `IntentBus.send()` restored to NATS request/reply when connected.

**Key Design Decisions:**

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DD-1 | NATSBus lifecycle ownership | Eliminates zombie entries, double subscriptions, stale mapping bugs. One source of truth for all active subscriptions. |
| DD-2 | Un-prefixed subjects in `_active_subs` | `_full_subject()` applies current prefix at re-subscription time. No double-prefixing risk. |
| DD-3 | `_resubscribing` guard flag | Prevents `subscribe()`/`js_subscribe()` from re-adding entries during the re-subscription loop. |
| DD-4 | Prefix change callbacks are notification-only | NATSBus re-subscribes everything before calling callbacks. IntentBus callback logs only — no parallel re-wiring. |
| DD-5 | Ephemeral consumers for system events | ~176 event types would create 100+ durable consumers with name collisions. Ephemeral is correct for system events. |
| DD-6 | `subscribe_raw`/`publish_raw` excluded from tracking | Federation uses raw subjects to bypass per-ship prefix isolation. Must NOT re-key on prefix change. |
| DD-7 | BF-221 lift: NATS-first, direct-call fallback | One path per call, never both. NATS when connected, direct-call when disconnected. Prefix re-subscription ensures subs survive Phase 7 DID assignment. |
| DD-8 | BF-229: NATSBus owns subject sanitization | Callers may pass any string as prefix (including raw DIDs with colons). `set_subject_prefix()` sanitizes NATS-unsafe characters (`:`, spaces, etc.) to underscores. Enforced at the boundary that owns the NATS constraint, not at callers. Underscore preserves single-token namespace depth (`probos.did_probos_<uuid>.*` matches `probos.local.*` depth). |

---

### AD-644 — Agent Situation Awareness Architecture

**Date:** 2026-04-18
**Status:** Phase 1-4 Complete (full parity — 23/23 items). Phase 5 Design (deprecation).
**Issue:** #285

**Decision:** Migrate the ~23 context injections from the monolithic `_build_prompt_text()` into the cognitive chain architecture using a four-category model grounded in Endsley's Situation Awareness framework.

**Motivation:** When `proactive_think` was added to `_CHAIN_ELIGIBLE_INTENTS` (AD-632+), the chain path bypassed `_build_prompt_text()` — a 290-line function that had accumulated context injections across 15+ ADs. The chain's ANALYZE step receives standing orders (system prompt) but no dynamic data (user prompt). Result: agents return `intended_actions: ["silent"]` on every cycle, including scheduled duties. Zero duty reports produced in days of operation.

This is not a missing feature — it's an accidental regression. The cognitive chain provides better architecture than the single-call path, but the context it needs was never migrated.

**Design:** Four cognitive categories, each with a distinct mechanism:

| Category | What | Mechanism | Naval Analog |
|----------|------|-----------|-------------|
| **Innate Faculties** | Temporal awareness, working memory, self-monitoring, source attribution data, telemetry, ontology identity, orientation, confabulation guard, comm proficiency, trust/agency/rank | Populated into observation dict by agent before chain runs | Sailor knows the time, remembers what they just did, knows their chain of command, senses their own fatigue |
| **Situation Awareness** | Ward Room activity, infrastructure status, alerts, events, subordinate stats, crew status, cold-start notes, active games | QUERY step operations (`_QUERY_OPERATIONS` registry) | Sailor glances at status boards, hears bridge conversation, sees alert condition |
| **Watch Station Duties** | Active duty assignment, duty-specific instructions | `params.duty` → observation dict, ANALYZE renders duty context | Sailor reads their WQSB entry, holds their PMS card |
| **Standing Orders** | Self-monitoring rules, cognitive zones, communication protocols, source attribution policy, duty reporting expectations | `compose_instructions()` → system prompt (already works) | Sailor has memorized regulations and standing orders |

**Prompt consumers:** Both ANALYZE (`_build_situation_review_prompt`) and COMPOSE (`_build_proactive_compose_prompt`) are starved — both read `context.get("context", "")` which is empty. Both need updates: ANALYZE for full situation assessment, COMPOSE for duty framing, source attribution, confabulation guard, and comm proficiency.

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Four categories from cognitive science, not code organization | Endsley SA model (perception → comprehension → projection) maps to QUERY → ANALYZE → intended_actions. Categories scale independently |
| DD-2 | Innate faculties run for ALL chain executions, not just proactive_think | Temporal awareness and working memory are agent faculties, not intent-specific. A conscious agent always knows the time |
| DD-3 | Situation awareness via QUERY operations, not observation dict | QUERY operations are deterministic, dispatch-table registered, Open/Closed. New percepts added without modifying chain code |
| DD-4 | Duty context biases ANALYZE away from silence | When a duty is active, the agent has an obligation to report. Silence during duty requires explicit justification (inverted from free-form default) |
| DD-5 | Five implementation phases, independently deployable | Phase 1 (duty fix) is critical. Phases 2-4 restore full parity. Phase 5 deprecates `_build_prompt_text` proactive block |
| DD-6 | Standing orders additions are markdown-only, zero code changes | Source attribution and duty expectations are policy, not data |
| DD-7 | Source attribution split: policy (Cat 4) vs data (Cat 1) | Policy = behavioral guidance in standing orders. Data = episodic_count, procedural_count, oracle_used = innate self-knowledge |
| DD-8 | COMPOSE is a second consumer, not just ANALYZE | Both prompt templates render from the same observation dict. COMPOSE needs duty framing, source attribution, confabulation guard |

**Implementation phases:**
1. **Duty Context Restoration** — pass `params.duty` + trust/agency/rank through, update ANALYZE + COMPOSE prompts (critical fix)
2. **Innate Faculties** — `_build_cognitive_state()` populates temporal, working memory, self-monitoring, ontology, orientation, source attribution data, confabulation guard, comm proficiency
3. **Situation Awareness** — extend QUERY operations (ward_room_activity, infrastructure_status, recent_alerts, recent_events, subordinate_stats, cold_start_context, active_game)
4. **Standing Orders** — add source attribution policy + duty expectations to ship.md
5. **Deprecation** — mark `_build_prompt_text` proactive block as deprecated

**Parity:** 23-item checklist in research doc maps every `_build_prompt_text` injection to an AD-644 category and implementation phase.

**Research:** [docs/research/agent-situation-awareness-architecture.md](docs/research/agent-situation-awareness-architecture.md)

**Future:** Composes with AD-641g (NATS pipeline — percepts become NATS subscriptions), AD-618 (SOP Bills — duties become Bill triggers), AD-643a (intent routing — richer SA improves action decisions), AD-645 (Artifact-Mediated Chain — composition briefs replace routing slips).

---

### AD-645 — Artifact-Mediated Cognitive Chain

**Date:** 2026-04-18
**Status:** Phase 1-3 Complete (Composition Briefs + COMPOSE Enrichment + Metacognitive Storage)
**Parent:** AD-632 (Cognitive Chain Architecture)
**Related:** AD-644 (Situation Awareness), AD-641g (NATS Pipeline), AD-639 (Chain Personality Tuning), AD-573 (Working Memory)

**Decision:** Replace ANALYZE's thin routing-slip output (`intended_actions` + structured fields) with a **composition brief** — a structured plan that tells COMPOSE what to write about, what evidence to draw on, what tone to use, and what the response should cover. Additionally, pass environmental context (Phase 3 SA keys) through to COMPOSE so it has both the focused plan AND the raw material.

**Motivation:** AD-644 achieved full context parity (23/23 items) between the chain path and one-shot `_build_user_message()`, but chain-path responses remain measurably flatter, less confident, and less specific. Root cause: ANALYZE compresses its full situational understanding into a routing slip (~200 tokens of JSON), then COMPOSE works from that summary rather than the source material. The one-shot path gives the LLM everything at once; the chain loses information at the ANALYZE → COMPOSE handoff.

The architect/builder analogy: current ANALYZE is like saying "write a build prompt for phase 4" with no research. Proposed ANALYZE is like writing a detailed build prompt with evidence, scope, design decisions, and references. COMPOSE (the builder) reads the brief AND has access to the raw context — focused guidance + full material.

**Design:**

The composition brief contains:
- **situation** — what's happening (1-2 sentences)
- **key_evidence** — specific observations/data points COMPOSE should reference
- **response_should_cover** — what the response needs to address
- **tone** — audience-appropriate framing guidance
- **sources_to_draw_on** — which knowledge sources are relevant

`intended_actions` survives alongside the brief for programmatic skill routing (AD-643a).

**Artifact value beyond composition:**
- **Metacognitive memory** — stored in WorkingMemory as `category="reasoning"`, lets agent answer "What was I thinking?" Extends AD-573 from recording what happened to recording how the agent processed it.
- **Dream consolidation** — dreams can extract reasoning patterns, not just outcome patterns
- **Reinforcement signal** — EVALUATE assesses plan-to-output alignment: (brief, response, score) triples
- **Cognitive forensics** — trace whether failures are perception errors (bad brief) or execution errors (ignored brief)
- **Self-monitoring** — detect narrowing reasoning patterns before they manifest as output repetition
- **Privacy preserved** — Minority Report Principle: briefs are agent's private cognitive workspace, Counselor has no access

**NATS alignment:** Build briefs before NATS. The brief format becomes the NATS message payload on `chain.{agent_id}.analyze.complete` when AD-641g lands. No throwaway work.

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Build briefs before NATS | Higher-value change; pre-shapes NATS message format |
| DD-2 | Brief is part of ANALYZE JSON, not separate file | Flows through existing `prior_results` mechanism |
| DD-3 | SA keys flow to both ANALYZE and COMPOSE | COMPOSE needs raw material, not just brief's summary |
| DD-4 | Briefs are private (Minority Report Principle) | Agent's working memory, not Counselor surveillance |
| DD-5 | Brief is optional/backward compatible | Missing brief falls back to current behavior |
| DD-6 | Metacognitive storage uses existing WorkingMemory | No new infrastructure needed |
| DD-7 | EVALUATE alignment is additive, not gating | Signal without changing pass/fail threshold initially |

**Implementation phases:**
1. **Composition Brief** — ANALYZE prompt + output schema enrichment
2. **COMPOSE Context Enrichment** — render brief + pass SA keys to COMPOSE
3. **Metacognitive Storage** — store briefs in WorkingMemory post-chain
4. **EVALUATE Brief Alignment** — plan-to-output alignment criterion
5. **NATS Schema** (deferred to AD-641g) — brief dict becomes message payload

**Research:** [docs/research/ad-645-artifact-mediated-cognitive-chain.md](docs/research/ad-645-artifact-mediated-cognitive-chain.md)

---

### AD-646 — Universal Cognitive Baseline

**Date:** 2026-04-19
**Status:** Complete
**Issue:** #288
**Parent:** AD-644 (Situation Awareness), AD-632 (Cognitive Chain Architecture)
**Related:** AD-645 (Artifact-Mediated Chain), AD-641g (NATS Pipeline), AD-573 (Working Memory)

**Decision:** Split cognitive context assembly into a universal baseline (agent-intrinsic, runs for ALL chain executions) and intent-specific extensions (registered per intent type). The baseline provides temporal awareness, working memory, episodic recall, source attribution, ontology identity, trust/rank, and cognitive zone — regardless of what triggered the cycle.

**Motivation:** AD-644 Phase 2 added innate faculties to the proactive chain path, but the implementation depends on `context_parts` populated by `proactive.py`'s `_gather_context()`. Ward Room notifications bypass the proactive loop, so `context_parts` is empty — agents enter ANALYZE knowing the thread content but nothing about themselves. Result: chain-path Ward Room responses are activity-level ("I've been conducting wellness checks") while the one-shot path produces insight-level responses ("157/118/85 unread messages, cognitive load at 40-75% of crisis threshold") because `_build_user_message()` injects the full cognitive state directly.

The core design flaw: context assembly is intent-specific instead of layered. Every new chain-eligible intent will need its own AD-644-style migration. The fix should be applied once at the trunk, not per branch.

**Design:**

```
┌─────────────────────────────────────────┐
│  Universal Cognitive Baseline           │  ← ALL chain executions
│  (temporal, working memory, episodic,   │
│   source attribution, ontology,         │
│   trust/rank, cognitive zone)           │
├─────────────────────────────────────────┤
│  Intent Extensions                      │  ← Per intent type
│  proactive_think: SA sweep, self-mon    │
│  ward_room_notification: thread context │
│  (future intents: their own extensions) │
└─────────────────────────────────────────┘
```

Split `_build_cognitive_state()` into:
- `_build_cognitive_baseline()` — agent-intrinsic, zero external dependencies, zero async calls. Reads from agent attributes (working memory, temporal context, ontology). Called unconditionally.
- `_build_cognitive_extensions(context_parts)` — depends on externally-gathered data (self-monitoring, notebook index, telemetry). Called only when `context_parts` is available.

Update thread analysis prompt (`_build_thread_analysis_prompt`) and ward_room compose prompt to consume baseline keys. Proactive path unchanged (gets baseline + extensions + SA).

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Baseline is agent-intrinsic, not service-dependent | Zero async calls, zero latency impact. Working memory, temporal context, ontology are all in-memory agent state |
| DD-2 | Self-monitoring stays in extensions (not baseline) | Self-monitoring data (self-similarity, cooldowns) is gathered by proactive.py. Working memory already covers cognitive zone and recent actions for the baseline case |
| DD-3 | Baseline pre-shapes NATS message envelope | Universal baseline becomes the standard payload on `chain.{agent_id}.analyze`. Extensions are intent-specific fields |
| DD-4 | Apply once, works for all current and future intents | No more per-intent migration work. New chain-eligible intents inherit the baseline automatically |
| DD-5 | ~500-700 tokens added to ward_room ANALYZE prompt | Well within Sonnet's budget. Working memory capped at 1500 tokens |

**Scope:** ~100 lines across 3 files (cognitive_agent.py, analyze.py, compose.py). Zero new modules. Zero new infrastructure.

**Implementation phases:**
1. Split `_build_cognitive_state()` → baseline + extensions
2. Update thread analysis prompt to consume baseline keys
3. Update ward_room compose prompt to consume baseline keys
4. Regression verification (proactive path unchanged)

**Research:** [docs/research/ad-646-universal-cognitive-baseline.md](docs/research/ad-646-universal-cognitive-baseline.md)

### AD-646b — Chain Cognitive Parity (Close One-Shot Gaps)

**Date:** 2026-04-19
**Status:** Complete
**Issue:** #289
**Parent:** AD-646 (Universal Cognitive Baseline), AD-632 (Cognitive Chain Architecture)
**Related:** AD-588 (Introspective Telemetry), AD-623 (DM Self-Monitoring), AD-575 (Self-Recognition), AD-568a (Oracle Service), BF-102 (Cold-Start Note)

**Decision:** Close the remaining data gaps between the chain ward_room path and the one-shot ward_room path by adding two new QUERY operations, three baseline enhancements, and consuming already-present observation keys in chain prompts.

**Motivation:** AD-646 established the universal cognitive baseline, giving ward_room chains temporal awareness, working memory, trust metrics, ontology, and confabulation guards. But the one-shot ward_room path still injects six data sources the chain path lacks:

| # | Data Source | One-Shot Path | Chain Path (post AD-646) | Gap Type |
|---|-------------|--------------|--------------------------|----------|
| 1 | DM self-monitoring (AD-623) | `_build_dm_self_monitoring()` — async | Missing | Async — needs QUERY |
| 2 | Introspective telemetry (AD-588) | `IntrospectiveTelemetryService.get_full_snapshot()` — async | Missing | Async — needs QUERY |
| 3 | Cold-start note (BF-102) | `rt.is_cold_start` check | Missing | Sync — baseline |
| 4 | Rich source attribution (AD-568d) | `observation["_source_attribution"]` dataclass render | Simplified count only | Sync — baseline |
| 5 | Self-recognition (AD-575) | `_detect_self_in_content()` — sync regex | Missing | Sync — baseline |
| 6 | Oracle context (AD-568a) | `observation["_oracle_context"]` render | Key present but not consumed by prompts | Prompt consumption |

These gaps are why chain ward_room responses still confabulate more than one-shot — agents lack self-monitoring, telemetry grounding, and cross-tier knowledge context.

**Design:**

Four-part fix, each independently testable:

**Part A — New QUERY Operations (query.py):**
- `self_monitoring`: For DM threads, call `ward_room.get_posts_by_author()` + Jaccard similarity (same pattern as `_build_dm_self_monitoring()`). For all threads, check cognitive zone from VitalsMonitor. Returns warning string or empty.
- `introspective_telemetry`: Conditionally on `_is_introspective_query()` against thread text, call `IntrospectiveTelemetryService.get_full_snapshot()` + `render_telemetry_context()`. Returns rendered text or empty.

**Part B — Baseline Enhancements (cognitive_agent.py `_build_cognitive_baseline()`):**
- Cold-start note: `rt.is_cold_start` boolean → `_cold_start_note` key.
- Rich source attribution: Read `observation["_source_attribution"]` dataclass (set by perceive/recall at line 4327), render episodic_count, procedural_count, oracle_used, primary_source. Override the simplified count-only version.
- Self-recognition: `_detect_self_in_content(observation.get("context", ""))` → `_self_recognition_cue` key.

**Part C — Chain Definition Update (cognitive_agent.py `_build_chain_for_intent()`):**
- Ward room chain at line 1554: add `self_monitoring` and `introspective_telemetry` to `context_keys`.

**Part D — Prompt Consumption (analyze.py + compose.py):**
- Oracle context: Add `_oracle_context` rendering to thread analysis prompt and compose `_build_user_prompt()`. Key is already in observation from perceive's `_recall_relevant_memories()`.
- Self-monitoring and telemetry: Render structured sections in thread analysis prompt from QUERY results (not raw "Prior Data" dump).
- Self-recognition and cold-start: Consume new baseline keys in thread analysis prompt.

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Async data via QUERY ops, not baseline | Baseline is sync-only by design (AD-646 DD-1). DM self-monitoring and telemetry require async ward_room/service calls |
| DD-2 | Telemetry is conditional on introspective query | Avoids unnecessary service calls + token budget for non-self-referential threads |
| DD-3 | Oracle context already in observation — just consume it | perceive() already calls `_recall_relevant_memories()` which sets `_oracle_context`. Zero new async calls needed |
| DD-4 | Rich attribution overrides simplified baseline | AD-646 baseline does a count-only attribution. When the `_source_attribution` dataclass is present (from perceive), render the full version with primary_source and oracle_used |
| DD-5 | Self-recognition is sync (regex) — belongs in baseline | `_detect_self_in_content()` is a regex scan, no async. Fits baseline's zero-async contract |

**Scope:** ~150 lines across 4 files (query.py, cognitive_agent.py, analyze.py, compose.py). Zero new modules. Zero new infrastructure. Reuses existing methods and services.

### AD-647 — Process-Oriented Cognitive Chains

**Date:** 2026-04-19
**Status:** Scoped
**Issue:** #291
**Parent:** AD-632 (Cognitive Chain Architecture), AD-618 (Bill System)
**Depends on:** AD-618 (Bills/SOPs), AD-595 (Watch Bill / Billet Registry), AD-641g (NATS Pipeline)
**Related:** AD-643a (Intent Routing), BF-209 (Scout chain bypass)

**Decision:** Implement process-oriented cognitive chains as a distinct chain type from the communication chain. Different business processes require different cognitive step sequences — not all agent work is "read thread → analyze → compose reply."

**Motivation:** BF-209 exposed a fundamental category error: the scout's duty-triggered report generation (a structured data pipeline) was forced through the communication chain (QUERY → ANALYZE → COMPOSE). The communication chain bypasses `act()`, so the scout's structured pipeline (parse → enrich → filter → store → notify) never ran. The report was always empty while Ward Room posts appeared.

The scout report is the first case, but the pattern applies to any structured process: incident response, qualification testing, maintenance procedures, data collection. These are **processes** with their own step sequences, not conversations.

**Design direction:**

- Process chains define step types beyond communication: QUERY (data gathering), TRANSFORM (classification/enrichment), STORE (persistence), NOTIFY (routing)
- Each step has its own prompt template or deterministic handler
- AD-618 (Bills/SOPs) provides declarative YAML process definitions
- AD-595 (Billets) provides role-based process assignment
- AD-641g (NATS) enables async step decoupling with process-specific message subjects
- Scout report is the reference implementation

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Communication chain and process chain are distinct types | Communication is interactive (read/analyze/compose). Process is pipeline (gather/transform/store/notify). Forcing one through the other loses structure |
| DD-2 | BF-209 is the interim fix until dependencies land | ScoutAgent opts out of chain for structured duties. Clean, principled, replaceable |
| DD-3 | Bills (AD-618) are the process definition format | YAML declarative procedures with BPMN decision points already designed for multi-step agent processes |

### AD-648 — Post Capability Profiles (Ontology Grounding for Confabulation Prevention)

**Date:** 2026-04-19
**Status:** Design
**Issue:** #292
**Parent:** AD-429 (Vessel Ontology)
**Related:** AD-427 (ACM Core), AD-428 (Skill Framework), AD-496 (Workforce Scheduling), AD-592 (Confabulation Guard), BF-204 (Grounding Checks)

**Decision:** Extend the ship's ontology with structured per-post capability profiles — what each post *actually does*, what tools/processes it uses, and critically what it *does not have*. Inject into prompt context via `_ontology_context` so agents have grounded factual knowledge of their own and each other's capabilities.

**Motivation:** Confabulation audit (2026-04-19) found 628 contaminated Ward Room posts (11.8%), 90+ contaminated episodic memories, 10+ confabulated notebook entries, and 8 agents with contaminated working memory — all from a single false narrative: "the scout has sensors." The scout searches GitHub repos. There are no sensors, no telemetry, no scan coverage metrics. Six agents built an elaborate shared fiction including architecture specs, diagnostic protocols, and fabricated correlations.

Existing confabulation guards (BF-204 hex ID detection, AD-592 "don't fabricate numbers") catch *data confabulation* but not *conceptual confabulation* — agents inventing wrong mental models about what roles do. The ontology tells Wesley he's "Scout in Science department" but never says what the scout *actually does*. Agents fill that gap with plausible inference, and when they infer wrong, the false model self-reinforces through episodic memory contamination.

The same pattern appeared at identical 12% rate across two different crews (pre-reset and post-reset), confirming it's structural, not crew-specific.

**Design:**

Phase 1 — Post capability declarations in `organization.yaml`:

```yaml
posts:
  - id: scout_officer
    title: "Scout"
    department: science
    reports_to: chief_science
    capabilities:
      - id: github_search
        summary: "Search GitHub for trending/relevant repositories"
        tools: [search_github]
        outputs: [scout_report_json]
      - id: scout_report
        summary: "Classify findings as ABSORB/VISITING_OFFICER/SKIP and generate structured report"
        outputs: [scout_report_file, ward_room_notification]
    does_not_have:
      - "sensors or sensory arrays"
      - "telemetry or scan coverage metrics"
      - "detection thresholds or calibration"
      - "environmental scanning or reconnaissance hardware"
```

Phase 2 — Ontology service extension:
- New `PostCapability` dataclass in `models.py`
- `get_crew_context()` includes `capabilities` and `does_not_have` in returned dict
- New `get_post_capabilities(post_id)` method for cross-agent queries ("what does Wesley do?")

Phase 3 — Prompt injection:
- `_build_ontology_context()` renders capability profile into `_ontology_context`
- Format: "Your capabilities: [list]. You do NOT have: [list]."
- Cross-agent capability lookups available in QUERY step for "what does X do?" questions

**OSS/Commercial boundary:** Capability profiles are OSS — they're confabulation prevention infrastructure, not commercial value-add. Commercial ACM (AD-C-010+) and ASA (AD-C-015) build on this foundation:
- ACM reads `capabilities` for consolidated agent profiles, workforce analytics, skill-based compensation
- ASA reads `capabilities` for `ResourceRequirement` matching — schedule agent X because it has capability Y
- Commercial extensions add: dynamic capability discovery, proficiency ratings per capability, utilization tracking per capability, marketplace profile generation

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Capabilities attach to posts, not agent_types | Posts are the unit of organization. Multiple agent_types could fill the same post. Matches Navy billet model — the billet defines the job, not the person filling it |
| DD-2 | Negative grounding (`does_not_have`) is as important as positive | Agents confabulate by filling knowledge gaps. Explicitly closing gaps ("you do not have sensors") prevents the inference chain that creates false narratives |
| DD-3 | All 18 posts get capability profiles, not just scout | The scout was the first failure. Any post without grounded capabilities is vulnerable to the same pattern. Proactive, not reactive |
| DD-4 | Cross-agent capability visibility | Agents must know what *other* agents do, not just themselves. Sage demanded "sensor telemetry" from Wesley because Sage didn't know Wesley searches GitHub. Peer capability awareness prevents collaborative confabulation |
| DD-5 | OSS foundation, commercial overlay | Capability profiles prevent confabulation (OSS concern). ACM/ASA consume them for workforce management (commercial concern). Same data, different consumers |
| DD-6 | `tools` field links to actual tool registry | Each capability references the actual tools/functions used. Grounds the capability in verifiable system reality, not free-form description |

**Scope:** Design + implementation after AD-618, AD-595, AD-641g land. Scout report as first case.

### AD-649 — Communication Context Awareness for Cognitive Chain

**Date:** 2026-04-19
**Status:** Complete
**Issue:** #293
**Related:** AD-639 (Trust-Band Tuning), AD-645 (Composition Briefs), AD-646/646b (Cognitive Baseline/Parity)

**Decision:** Add prescriptive communication context (channel type, audience, register) to the cognitive chain so COMPOSE adapts output format based on where and to whom the agent is communicating. Brings chain output quality toward parity with the one-shot path.

**Motivation:** The chain produces formal, clinical output regardless of context. Two agents (Ezri/Counselor, Nova/Operations) independently diagnosed the same problem when shown their chain vs one-shot responses to the same question. Both identified that COMPOSE defaults to "the most formal register because that feels safer professionally" (Ezri) and produces "crisis management checklist" output instead of operational analysis (Nova). The one-shot path works well because the LLM natively handles audience adaptation — but this is a fragile dependency on emergent model capability. The chain must encode desired behavior prescriptively (LLM Independence Principle).

**Design:**

- Part A: Derive `_communication_context` from existing `channel_name`/`is_dm_channel` — five registers: private_conversation, bridge_briefing, casual_social, ship_wide, department_discussion
- Part B: Add communication context to ANALYZE composition_brief tone guidance — prescriptive register descriptions
- Part C: Add "Speak in your natural voice" to COMPOSE ward_room prompt (parity with one-shot). Register-specific framing per channel type. "Show your reasoning, not just conclusions."

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Five registers derived from channel_name | Maps to existing channel types (ship, department, dm, recreation, custom). No new infrastructure needed |
| DD-2 | Voice parity with one-shot path | Chain ward_room compose was missing "Speak in your natural voice" that one-shot has. Direct gap, direct fix |
| DD-3 | Prescriptive register guidance, not implicit | LLM Independence Principle: chain must produce good output with a less capable model. Encode register expectations explicitly so behavior doesn't depend on emergent model capability |
| DD-4 | "Show reasoning, not just conclusions" | Nova diagnosed that chain strips analytical reasoning. Conclusions without reasoning context are useless for decision-making |
| DD-5 | Department channel is default (no extra constraint) | Natural LLM behavior is correct for peer discussion. Only add constraints for specialized contexts (bridge, recreation, ship-wide) |

**Scope:** ~80 lines across 2 files (cognitive_agent.py, compose.py, analyze.py). 14 tests. Zero new modules.

### AD-650 — Analytical Depth Enhancement

**Date:** 2026-04-19
**Status:** Complete
**Issue:** #294
**Related:** AD-645 (Composition Briefs), AD-646/646b (Cognitive Baseline/Parity), AD-649 (Communication Context)

**Decision:** Enrich the composition brief with a narrative reasoning field and add depth instructions to COMPOSE so the cognitive chain surpasses one-shot output quality on analytical depth — counterarguments, meaning extraction, philosophical nuance.

**Motivation:** AD-649 brought the chain to functional parity on register and tone. But 7 A/B comparison tests revealed the chain consistently underperforms on depth: one-shot produces counterarguments ("fresh eyes" perspective), coined vocabulary ("cognitive load clustering"), and diagnostic insights (using game behavior to read leadership styles). The chain produces broader factual coverage but shallower reasoning. Root cause: the composition brief is an information bottleneck — ANALYZE reasons deeply then compresses to 5 structured fields, losing conditional logic ("because X, therefore Y matters more than Z"). Research grounding: Chain-of-Thought (Wei et al. — intermediate reasoning is load-bearing), DSPy (Stanford — field descriptions are optimization targets), Lost in the Middle (Liu et al. — context positioning matters), Self-Refine (Madaan et al. — can't recover info never passed through bottleneck), OpenMythos/COCONUT (input re-injection prevents representation drift).

**Design:**

- Part A: Add `analytical_reasoning` narrative field to composition_brief in all 3 ANALYZE modes. Reframe brief from "plan for composing" to "analytical reasoning and composition plan." Explicit "narrative prose, not bullets" instruction.
- Part B: COMPOSE renders `## Analytical Reasoning` section. Bold-header suppression for ALL Ward Room branches (was only in private_conversation and DM). Depth instruction ("Don't just summarize — interpret") in all compose modes.

**Key decisions:**

| # | Decision | Rationale |
|---|----------|-----------|
| DD-1 | Narrative reasoning field, not more structured fields | CoT research: conditional logic ("because X, therefore Y") is lost in structured extraction. Narrative preserves the "because" relationships that make reasoning transferable |
| DD-2 | Reframe brief as "analytical reasoning + plan" | Current framing ("plan for composing") tells the LLM to plan, not reason. Framing shapes output |
| DD-3 | Bold-header suppression in ALL Ward Room branches | Testing showed headers regress on multi-point responses in department_discussion, bridge_briefing, etc. Only private_conversation and DM had suppression |
| DD-4 | "Don't just summarize — interpret" as prescriptive depth instruction | One-shot produces depth spontaneously. LLM Independence Principle: make it prescriptive so it works across models |
| DD-5 | Original context still flows to COMPOSE (no change) | Verified: COMPOSE already receives original thread via `context["context"]`. The bottleneck is brief content, not context availability (OpenMythos input re-injection is already in place) |

**Scope:** ~120 lines across 2 files (analyze.py, compose.py). 12 tests. Zero new modules.

### AD-651 — Standing Order Decomposition for Cognitive Chain Steps

**Date:** 2026-04-20
**Status:** Design
**Issue:** #299
**Parent:** AD-632 (Cognitive Chain Architecture)
**Depends on:** AD-647 (Process Chains), AD-641g (NATS Pipeline)
**Related:** AD-646 (Universal Baseline), BF-213 (Analyze Silence Bias)

**Decision:** Decompose monolithic standing orders into step-specific billet instructions for the cognitive chain. Standing orders were designed for the one-shot world — the chain decomposes cognition into steps but injects the same ~2K token document at multiple steps. Each chain step is a billet with its own task-specific instructions, decision space, and operational context.

**Motivation:** BF-213 exposed that standing orders' "When to act vs. observe" decision tree has no effect at the ANALYZE step because the step's own framing ("Silence is professionalism") overrides it. The decision tree is an assessment rubric that belongs in ANALYZE's prompt, not in a general document. The one-shot path never had this problem because assessment and composition happened in the same LLM call — standing orders influenced both simultaneously. The chain splits the cognitive function but doesn't split the instructions to match. AD-647 (Process Chains) already frames steps as billets with their own templates — this AD generalizes that pattern to the communication chain.

**Design:**

- Standing orders split into: identity-level guidance (character, federation/ship values, active directives — stays in standing orders, constitutional preamble at every step) + operational instructions (moves into step prompts as billet instructions)
- ANALYZE gets: decision tree, action vocabulary descriptions, authority scope
- COMPOSE gets: action tag syntax, communication discipline, register guidance
- EVALUATE/REFLECT gets: quality criteria
- Phase 1: extract decision tree into ANALYZE prompt (near-term, standalone)
- Phase 2: billet instruction format in Bill YAML (with AD-647)
- Phase 3: NATS envelope `billet_instructions` field (with AD-641g)

**Key insight:** In one-shot, the model sees everything and makes holistic judgments. In the chain, each step is a specialist. Giving every specialist the entire manual wastes tokens and buries relevant instructions. But over-decomposing risks steps that are too narrowly scoped — identity/values must remain at every step as a constitutional baseline.

**Research:** `docs/research/standing-order-decomposition.md`

### AD-652 — Cognitive Code-Switching: Unified Pipeline with Contextual Modulation

**Date:** 2026-04-20
**Status:** Design Principle (adopted)
**Issue:** #302
**Parent:** AD-632 (Cognitive Chain Architecture)
**Related:** AD-651 (Billet Instructions), AD-639 (Chain Personality Tuning), AD-647 (Process Chains)

**Decision:** The cognitive chain is a single unified pipeline, not parallel pipelines for different communication types. Different cognitive tasks (duty reports vs. casual observations vs. DM responses) are handled through contextual modulation of the same pipeline — variable chain depth, tenor-aware compose framing, and structured format overlays — not by branching into separate architectures.

**Motivation:** The chain pipeline (AD-632) introduced uniform rigidity — the same QUERY → ANALYZE → COMPOSE → EVALUATE → REFLECT sequence runs for duty reports and casual social posts alike. AD-639 identified that this strips personality. AD-651 introduced billet instructions to add structure for operational outputs. The question arose: should ProbOS maintain separate cognitive pipelines for structured vs. creative work?

Cognitive science research (Levelt, Halliday, Giles, Snyder, Weick/Sutcliffe) converges on a clear answer: humans use one language production system with contextual modulation, not parallel systems. Register switching (code-switching) adjusts parameters within a unified pipeline. Military formal protocols are trained overlays on natural language capacity, not separate cognitive systems.

**Design Principles:**

1. **Unified Pipeline** — one chain framework. Identity continuity requires architectural unity. An agent must sound like themselves across duty reports and mess-hall conversation.
2. **Contextual Modulation** — Halliday's field (topic), tenor (formality), and mode (channel) parameters modulate chain behavior: step composition, framing prescriptiveness, format overlays.
3. **Structured Format Overlays** — institutional outputs use billet instructions as cognitive scaffolding (per HRO research). Duty reports, proposals, formal briefings get prescriptive format templates.
4. **Variable Chain Depth** — high-structure tasks get more steps with prescriptive framing. Low-structure tasks get fewer steps with lighter framing. Same pipeline, different configurations.
5. **Character-Driven Self-Monitoring** — code-switching range is a personality parameter (Snyder's Self-Monitoring Theory), not a pipeline decision. Derived from Big Five traits.
6. **Process-Specific Chains** — fundamentally different cognitive tasks can have different step compositions and mode keys. But if two tasks are the same process with different context, they share the chain and modulate parameters.

**Key insight:** The situation selects the register, not a pipeline branch. Like a chat temperature slider from formal to friendly — but the modulation is in prompt context and instructions, not literal LLM temperature. Billet instructions are hard constraints that override for specific output types; tenor is the soft modulation for everything else.

**Research:** `docs/research/cognitive-code-switching-research.md`

### AD-653 — Dynamic Communication Register: Self-Monitored Register Shifting

**Date:** 2026-04-20
**Status:** Design
**Issue:** #303
**Parent:** AD-652 (Unified Pipeline / Contextual Modulation)
**Depends on:** AD-652, AD-504 (Self-Monitoring), AD-651 (Billet Instructions)
**Related:** AD-506 (Self-Regulation), AD-639 (Chain Personality Tuning)

**Decision:** Extend the unified cognitive pipeline (AD-652) with agent-initiated dynamic register shifting. Agents self-monitor their communication register, detect when the assigned register constrains important output, and request a temporary shift ("speak freely" protocol). The shift is trust-gated, temporally scoped, and observable by the Counselor.

**Motivation:** AD-652 established contextual modulation as a top-down mechanism — the system selects register based on context (duty → formal, social → casual). But situations arise where an agent recognizes that the assigned register is flattening something important: a duty report that needs a candid personal assessment, an observation that contradicts the expected structured format, or a finding too nuanced for template framing. In military protocol, "permission to speak freely" solves this — a recognized protocol for situations where protocol itself is the obstacle.

**Prior art survey (confirmed first-of-kind):** No existing multi-agent framework implements self-monitored register shifting. AutoGen/CrewAI/MetaGPT fix communication style at initialization. Reflexion/MARS/MUSE self-assess reasoning quality, never communication register. PromptBreeder evolves prompts across runs but not mid-task. DRESS controls style externally, not agent-initiated. CAMEL enforces role consistency, never escape. Stanford Generative Agents produce emergent style but agents have zero awareness of their own communicative constraints.

**Design:**

Three layers, each buildable independently:

1. **Register Classification Taxonomy** — finite label set (formal_report, professional, collegial, casual, speak_freely) with mapped chain parameters (depth, framing weight, format overlay, personality weight).

2. **Modulation Pattern Templates** — pre-defined configurations mapping (register × process) → chain parameters. Billet instructions (AD-651) are one component; templates bundle billet selection + framing weight + chain depth + personality weight.

3. **Dynamic Register Shift ("Speak Freely")** — ANALYZE detects register-task mismatch → outputs `"speak_freely"` in intended_actions → trust-gated authorization (≥0.7 auto-granted, 0.4-0.7 flagged, <0.4 denied) → COMPOSE receives minimal-constraint framing → shift scoped to single invocation → Counselor receives REGISTER_SHIFT event for pattern tracking.

**Novel contribution:** First implementation of agent self-aware communication register management. Structure AND emergence, not OR — the emergence escape hatch is itself structured, gated by trust, and observable. "Protocol for breaking protocol."

**Research:** `docs/research/dynamic-communication-register-research.md`
