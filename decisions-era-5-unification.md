# DECISIONS — Era V: Unification (Apr-May 2026)

Archived from DECISIONS.md on 2026-05-08. Spans architectural decisions from
AD-440 (Chain of Command) through AD-695 (Ship Health Oracle Tier 7), plus
the AD-574b/c, AD-685b/c/d phantom-API tooling extensions, the AD-687-692
unified knowledge graph + Oracle absorption stack, and the AD-647b/c process
chain registry + bills integration.

Authoritative reference for all of these is preserved here; see DECISIONS.md
for AD-696 onward.

----
### AD-574b: Synchronous DM Reply with Thinking Indicator + Ward Room Dual-Write (2026-05-05)

**Context.** AD-574 (Wave 33, decisions-era-4-evolution.md:2888) wired Captain-in-DM into `WardRoomRouter.find_targets` so an agent eventually responds to Captain DMs on its next proactive think cycle. The DM panel UX remained asymmetric with `ProfileChatTab`: Captain types into a Ward Room DM, the input clears, and an empty thread sits there for ~30s. AD-574b closes that gap by routing DM submits through `/api/agent/{id}/chat` synchronously and dual-writing the exchange back into the Ward Room thread for record-keeping.

**Decision.** `WardRoomThreadDetail.submitReply` branches on `view === 'dm-detail'` plus a backend-supplied `target_agent_id`. Synchronous path: set `wardRoomDmPending` slice, POST to `/api/agent/{id}/chat`, on success dual-write Captain message + agent response to the Ward Room thread, on failure fall back to existing async-post path. Backend `/api/wardroom/dms` and `/api/wardroom/captain-dms` gain a `target_agent_id` field via private `_resolve_dm_target_agent_id` helper that resolves channel-name participant prefix against `runtime.registry.all()` and returns `null` on miss (tier-2 log-and-degrade).

**Wholesale-deferred sibling.** AD-574c (DM conversation convergence — unify `ProfileChatTab.agentConversations` Map with Ward Room DM threads into a single conversation store) is wholesale-deferred to AD-574c-i. Forcing function: AD-574b establishes Ward Room as the canonical write surface for DM via dual-write; AD-574c-i then refactors ProfileChatTab to read from `/api/wardroom/dms/{channel_id}/threads` + `/api/wardroom/threads/{id}` instead of the standalone Map. Cannot land in Wave 69 because doing so would conflate two architectural changes (foreground sync UX + canonical-store swap) into one prompt — exact pattern Wave 67 (5→1) and Wave 68 (4→0) avoided.

**Architect calls.** `target_agent_id` lives on the API response not in UI parsing (DLog #1: keeps frontend ignorant of channel-name format mutation history). Dual-write client-side (DLog #2: keeps `/api/agent/{id}/chat` reusable by ProfileChatTab without thread-state coupling). `target_agent_id=null` fallback (DLog #3: graceful degradation when channel encodes a deleted/renamed agent). `wardRoomDmPending` lives in store not local state (DLog #4: survives panel re-mounts during in-flight chat). Existing AD-574 proactive ambient-response path unchanged (DLog #5: belt-and-suspenders; if sync fails the proactive cycle still picks up the unread Captain post).

**Out of scope.** Streaming "thinking…" with periodic LLM-thought updates (defer AD-574b-1, requires SSE/WebSocket on `/api/agent/{id}/chat`). Captain typing-indicator surface to the agent (defer AD-574b-2). Multi-Captain coordination (*(Commercial)* AD-574b-3, OSS surface stays single-Captain). DM convergence into single store (deferred AD-574c-i, see Forcing function above).

**Tests.** 8 pytest at `tests/test_ad574b_dm_sync_chat.py` (helper unit tests covering captain DM resolution, agent-to-agent DM resolution, dead-agent skip, unresolvable prefix → None, non-DM channel → None, runtime without registry → None, registry exception → None tier-2). 6 Vitest at `ui/src/__tests__/WardRoomDmSync.test.tsx` (idle render, sync DM submit + dual-write, thinking placeholder during in-flight, fallback on null target, fallback on chat 500, Send disabled while thinking).

**Cross-links:** AD-574 (DM reply agent notification — predecessor, decisions-era-4-evolution.md:2888), AD-574c-i (DM conversation convergence — wholesale-deferred successor, no GH issue v1; forcing function: this AD's dual-write must be live before ProfileChatTab data-source swap). Wave 69. Closes GH issue #110 (partial — AD-574c remains as deferred-with-forcing-function).


**Archives:** [Era I — Genesis](decisions-era-1-genesis.md) | [Era II — Emergence](decisions-era-2-emergence.md) | [Era III — Product](decisions-era-3-product.md) | [Era IV — Evolution](decisions-era-4-evolution.md)

---

## Era V — Civilization (Phases 31-36)

### AD-647c v1: Process Chains Bills/Watch Bill Integration (2026-05-04)

**Problem:** AD-647 (Wave 34) shipped the chain executor scaffold; AD-647b (Wave 48) shipped the chain registry + base-class hook; AD-618a-e (Bills) and AD-595a-e (Watch Bill) shipped independently. All four substrates are live, but no chain currently maps to a Bill — meaning Watch Bill role assignments and Bill step lifecycle do NOT flow through chain execution. Process chains can run, but they don't update `BillInstance` step state or resolve role-assigned agents from the active Watch Bill.

**Decision:**
- `ProcessChainStep` gains two optional fields (default `""`): `bill_step_id` (the `BillStep.id` this chain step satisfies) and `assigned_role` (the `BillRole.id` whose holder agent should run this step).
- `ProcessChainExecutor` accepts `bill_runtime=None` ctor kwarg. When set AND `context['bill_instance_id']` is supplied, the executor resolves the active `BillInstance` once at chain start, injects `_resolved_agent_id_<step.name>` from `BillInstance.role_assignments[step.assigned_role].agent_id` before each step, calls `bill_runtime.complete_step(instance.id, step.bill_step_id, result=step_output)` on success and `fail_step(..., error=...)` on handler exception. All bill_runtime calls wrapped in try/except→logger.warning (tier-2 log-and-degrade) so bill-side errors never break chain execution.
- `ProcessChainRegistry.register_bill_chain(bill_definition, chain_definition)` validates every chain step's non-empty `bill_step_id` against the bill's `BillStep.id` set; mismatch raises `ValueError` and the chain is NOT registered (fail-fast).
- New `CONSULT` value appended to `ProcessChainStepKind` (semantic label only — executor already awaits async handlers; CONSULT handlers can internally await `asyncio.Event` / ward-room threads / ConsultationWorkspace decisions today).
- New public property `runtime.bill_runtime` mirrors `runtime.billet_registry` shape (closes the Wave 5 conv #1 hole that AD-635 documented retrospectively for `_emergent_detector`).

**Architect calls (DLogs):**
1. Field named `bill_step_id` not `bill_id` — `bill_id` is overloaded across the Bills surface (`BillDefinition.bill` is the bill slug; `BillInstance.bill_id` is the slug too). The chain step's field maps to `BillStep.id`, the step-id-within-a-bill. The bill-instance correlation is supplied by the caller via `context['bill_instance_id']` at run-time — orthogonal field, not on the step.
2. CONSULT = enum value only, NO executor change. The existing executor already runs `await step.handler(running)` which natively supports `async def __call__` handlers that await any async resource. True suspend-and-resume across process restart requires checkpointing infrastructure and is out of scope (placeholder AD-647d).
3. `runtime.bill_runtime` public property added (1 line, mirrors `runtime.billet_registry`) instead of recreating AD-635's `getattr(rt, '_bill_runtime', None)` Demeter exception at every call site.
4. Three-guard defense for bill recording: `bill_step_id != ""` AND `context.get('bill_instance_id')` AND `self._bill_runtime is not None`. Any one missing → executor behaves exactly as v1 (no bill side-effects).
5. Bill recording is tier-2 log-and-degrade — every `bill_runtime.{get_instance, complete_step, fail_step}` call wrapped in try/except. Chain execution is the source of truth for chain success; Bills tracking is a secondary observability surface.
6. Unresolved `assigned_role` is log-and-degrade. Handler still runs, just without `_resolved_agent_id_<step>` injected. Executor does NOT synthesize a fall-back identity; the handler decides (typically via `context['_agent']` per AD-647b convention).
7. `register_bill_chain` is fail-fast at registration time. Mismatched `bill_step_id` raises `ValueError` and the chain is NOT registered. Empty `bill_step_id` values are permitted and skip validation.

**Out of scope:** No NATS coupling (AD-641g, #403); no LLM step templates (`prompt_template_id` still reserved/rejected); no parallel/conditional/rollback steps; no CONSULT suspend-and-resume across process restart (AD-647d placeholder); no Scout migration to bill-bound; no HXI surface; no new EventType. Backward compatibility: all 8 existing AD-647 v1 tests + 12 existing AD-647b v1 tests pass unchanged — new fields default to `""`, new ctor kwarg defaults to `None`.

**Closes:** GH issue #405. Wave 49.

### AD-647b v1: Process Chain Registry + BF-209 Bypass Removal (2026-05-04)

**Problem:** AD-647 v1 (Wave 34) shipped `ProcessChainStep`/`ProcessChainDefinition`/`ProcessChainExecutor` but ScoutAgent constructed its `scout_report` chain inline inside `act()` per invocation, with handlers as bound methods. No registry, no introspection, no replacement path. ScoutAgent additionally carried a per-agent BF-209 override on `_should_activate_chain` that returned False for `proactive_think + duty_id="scout_report"` — an opt-out that did not generalize.

**Decision:**
- New `ProcessChainRegistry` in `cognitive/process_chains.py` keyed by `chain_id = definition.name`. API: `register_chain(definition)` (replace + WARNING on duplicate, mirrors `ToolRegistry.register`), `get_chain(chain_id) -> ProcessChainDefinition | None` (Demeter-friendly None on miss), `list_chains() -> list[str]` (sorted), `unregister_chain(chain_id) -> bool` (False on absent, no exception).
- New class attribute `process_chain_id: str | None = None` on `CognitiveAgent`. Base-class `_should_activate_chain` short-circuits to False when `self.process_chain_id is not None` AND observation is `proactive_think` with `params.duty.duty_id == self.process_chain_id` — this generalizes BF-209 into a declarative class-attribute hook.
- Scout handler refactor: four `_scout_step_*` methods promoted from bound instance methods to module-level functions reading `_agent` from chain context. `SCOUT_REPORT_CHAIN: ProcessChainDefinition` is now a static module-level constant. `ScoutAgent.process_chain_id = "scout_report"`. ScoutAgent's BF-209 `_should_activate_chain` override is REMOVED. `act()` looks up chain via `runtime.process_chain_registry.get_chain(self.process_chain_id)` with module-level fallback + WARNING when registry is missing.
- New `ProcessChainRegistryConfig(enabled=True)` Pydantic model + `_wire_process_chain_registry` finalize wirer that constructs the registry and registers `SCOUT_REPORT_CHAIN`.
- Test fixture `test_scout_act_runs_through_process_chain` updated to inject a `SimpleNamespace` runtime carrying a populated `process_chain_registry` (replaces `_runtime = None`).

**Architect calls (DLogs):**
1. Module-level handlers + `_agent` in context is the correct long-term shape (registry stores definitions, not factories); `_deliver_discord` stays bound (reads runtime/config/id).
2. Hook lives on `_should_activate_chain` (not a default `act()`) — `CognitiveAgent.act()` already has substantial chain-aggregation logic we don't fork.
3. Duplicate-registration semantics: replace + WARN (matches `ToolRegistry`); more useful for hot-reload/test isolation than rejection.
4. Registry never raises on miss (`get_chain` → None, `unregister_chain` → False).
5. `enabled=True` default is intentional — Scout's `act()` depends on the registry; cost is one empty dict + one register call at boot. Same precedent as `KnowledgeEdgesConfig`/`ConsultationWorkspaceConfig`.
6. Backward-compat invariant: all 8 existing AD-647 v1 tests continue to pass after the Section 6 fixture amendment.

**Out of scope (explicit non-goals):** No NATS / Bills / Watch Bill integration (AD-647c, #405). No parallel/conditional/rollback steps. No LLM-template handlers. No registry persistence (in-memory only). No HXI surface for `list_chains()`. No `_deliver_discord` refactor. No `BaseAgent` change (hook lives on `CognitiveAgent`).

**Result:** 12 new tests in `tests/test_ad647b_chain_registry.py` (over the 10 floor by 2). All 8 existing AD-647 v1 tests pass with the fixture amendment. Phantom-API pre-check on the prompt + touched source files: clean (no NEW phantoms). Full gate: 11144 passed (delta +12 vs Wave 47 baseline 11132 — exact target hit; 1 known xdist flake `test_knowledge_store::test_auto_commit_after_debounce` passes serial in 7.41s, same Waves 8/14/15/16/19/22/27/30/31/32/33/37/41/42 environmental git-debounce pattern, unrelated to this AD). Pre-commit deletion sanity: max ~110 deletions in `scout.py` (4 bound `_scout_step_*` methods removed — content moved to module level above class). No surprise deletions. No hard-stops triggered: no architectural change required, no phantom in implementation (verify-first pre-check at draft confirmed all 8 anchors at HEAD: `ProcessChainExecutor` line 108, `_should_activate_chain` overrides at scout.py:253 + cognitive_agent.py:1685, `ScoutAgent` class at scout.py:206, four `_scout_step_*` instance methods at scout.py:449/475/489/506, `ToolRegistry.register` precedent at tools/registry.py:113, `_wire_consultation_workspaces` sibling at finalize.py:515, `consultation_workspaces` field at config.py:2260; `runtime.process_chain_registry` collision-free greenfield 0 hits in src). Closes GH issue #404.

### AD-685d v1: Phantom-API Pre-Check Dataclass/Pydantic Field-Name Validation (2026-05-04)

**Problem:** AD-685/AD-685b/AD-685c validate kwarg names, method names, and kwarg type-shapes — but not field-name typos on dataclass / Pydantic instances. A prompt asserting `meta.totel_ops` (typo of `total_operations`) or `AgentMeta(succes_count=5)` (typo of `success_count`) ships clean. Property/field collisions across inheritance (child dataclass field shadowing parent `@property`) also slip through. GH issue #407 calls for field-name validation closing this fourth gap.

**Decision:** Extend `scripts/phantom_api_ast_helper.py` (single-file extension, ~+280 lines to ~1280 total) with `field_phantom` and `property_field_collision` categories.

- New 5th cache `_CLASS_FIELDS_CACHE` and `build_class_field_index()` AST walker indexes `@dataclass`-decorated classes and `BaseModel` subclasses → `{fields, parents, properties, methods, kind}`. ClassVar annotations excluded; plain (non-dataclass non-Pydantic) classes recorded only when they declare properties or methods (supports parent-side collision lookup).
- `_resolve_transitive_fields()` cycle-safe recursive parent walk returning `(fields, properties, methods)` unioned across the class chain.
- `find_field_phantoms()` flags constructor kwargs (`MyDc(typo=...)` via `_CTOR_RE` + AST keyword parse) and attribute access (`obj.typo` via `_ATTR_RE`, NOT followed by `(`) against transitive field sets. Receiver resolution via Pattern B (`var = MyClass(...)`) only — chained `runtime.X.field` deferred to a future AD; `runtime` direct receiver skipped to avoid flagging public attrs whose classes the helper doesn't model uniformly.
- `find_property_field_collisions()` walks each indexed class's transitive parents and flags every (child_field, parent_property) and (child_field, parent_method) pair. Parent properties are higher-confidence collisions; methods still surface because shadowing a parent method with an instance field is a real bug.
- PowerShell wrapper extends dispatch with two new `elseif` branches rendering `<Class>.<field> <kind> -> not in fields {...}` and `<Child>.<name> shadows <Parent>.<name> (property|method)`.
- Backward compat preserved: AD-685 records keep no `category` field; AD-685b/c records unchanged. Existing 35 phantom-API pre-check tests stay green.

**Hard architect calls:** (1) Chained `runtime.X.field` attribute-access deferred — multi-segment AST walk needed; punt. (2) Private fields (`_` prefix) skipped both directions — ProbOS narrow-private-access convention. (3) ClassVar annotations excluded from fields. (4) Plain classes recorded only with properties/methods to avoid flagging non-dataclass typos. (5) Single-file extension preserved (no package split).

**Out of scope:** TypedDict (defer AD-685e); runtime introspection; dynamic `__annotations__` mutation; per-instance type narrowing across function boundaries; constructor kwarg type-shape on dataclass fields (AD-685c handles function annotations only); NamedTuple / attrs / msgspec; exit-code semantics change.

**Acceptance:** 12 focused tests pass at `tests/test_ad685d_phantom_field_name.py` (over 10 floor by 2): dataclass happy + unknown attribute + unknown ctor; Pydantic happy + unknown; property/field collision; method/field collision; inherited fields recognized via transitive walk; var-no-resolve silent skip; output category strings exact; ClassVar excluded; subprocess self-test on prompt body returns exit 0 with FPs constrained to fixture class names. Full gate: 11134 passed, 15 skipped (delta +12 vs Wave 46 baseline 11122 — exact target hit).

**Closes:** GH issue #407.

**Related:** AD-685, AD-685b, AD-685c.

### AD-685c v1: Phantom-API Pre-Check Type-Shape Validation (2026-05-04)

**Problem:** AD-685 v1 (Wave 11) validates kwarg names against live signatures; AD-685b v1 (Wave 15) validates method names against resolved classes. Neither validates that kwarg **values** match the parameter's annotated type. A prompt asserting `obj.method(name=42)` where the method declares `name: str` ships clean today. GH issue #406 calls for type-shape validation closing this gap.

**Decision:** Extend `scripts/phantom_api_ast_helper.py` (single-file, NOT a directory split — verified at draft) with a third `category="type_shape_mismatch"` phantom class.

- `_collect_param_annotations()` mirrors `_collect_param_names()` for positional/kwonly/`*args`/`**kwargs`; `build_index()` records `param_annotations: dict[str, ast.AST]` alongside existing `params` in the same AST walk (zero extra I/O).
- Slotted `TypeShape` (`literal_types`/`allow_none`/`container`/`element_shapes`/`unknown` + `is_skippable()`); pure-AST `_annotation_to_type_shape` handles primitives, `Optional[X]`, `X | None`, `Union[A, B, ...]`, `list[T]`/`dict[K, V]`/`tuple[T, ...]`/`tuple[T1, T2]`/`set[T]`/`frozenset[T]` plus bare containers; unknown classes (e.g. `KnowledgeEdge`) → `unknown=True` → SKIP.
- Slotted `ValueShape` + pure-AST `_value_to_shape` for `ast.Constant` (str/int/float/bool/None — bytes returns None per Captain spec) + `ast.List`/`ast.Set`/`ast.Tuple`/`ast.Dict`; `ast.Name`/`ast.Call`/`ast.Attribute` → silent skip.
- `_value_matches_shape` is conservative — skippable shapes never flag; `None` matches iff `allow_none`; primitive matches iff in `literal_types`; bool also matches int (Python `isinstance(True, int)`); container matches when kind matches AND every element shape matches (homogeneous for list/set/`tuple[T, ...]`, positional for `tuple[T1, T2]`, key/value for dict); empty container is permissive.
- `find_type_shape_phantoms` re-parses each call's kwarg block as `ast.parse(f"_f({block})", mode="eval")` to recover value ASTs; flags only when EVERY applicable candidate has an annotation AND NONE match the value. If ANY candidate has the kwarg without an annotation → permissive across all candidates → no flag.
- `_jsonable_candidate(c)` projects candidate dicts to a JSON-serializable subset (strips `param_annotations` AST nodes); both `find_kwarg_phantoms` and `find_type_shape_phantoms` route emitted candidate slices through it.
- `main()` adds type-shape phantoms to the `phantoms` list. PowerShell wrapper adds a third `elseif type_shape_mismatch` branch rendering `<method>(<kwarg>=<<value_type>> -> expected <<types>>)`. No exit-code semantics change. Existing AD-685 v1 kwarg-phantom records (no `category` field) and AD-685b method-phantom records ship unchanged.

**Rationale:** The phantom-API pre-check has caught three method-shape recurrences and one kwarg-shape recurrence across Waves 9B/10/12/14/27. Type-shape mismatches (`obj.f(name=42)` against `name: str`) belong to the same class of statically-detectable phantoms. Captain's spec asks for ≥2x perf bound only; reusing the existing single AST walk to capture annotations alongside param names meets that trivially. Keeping the helper single-file (rather than splitting into a `scripts/phantom-api-precheck/` package per the Captain's draft) preserves the AST-only-no-imports sandbox property; a package split is a separate refactor AD if needed. Conservative skip-over-flag remains the standing principle: untyped params skip, unknown classes skip, bytes literals skip, variable refs skip, empty containers permissive — false positives are far costlier than false negatives at the dispatch gate.

**Trade-offs:**

- Unknown class annotations (e.g. `def f(x: KnowledgeEdge)`) are skipped entirely; AD-685d (Wave 47) adds dataclass / Pydantic field-name validation for those cases.
- No type-shape on return values (separate AD if ever needed). No runtime introspection. No bytes-content reasoning. No PowerShell `$STDLIB_PREFIXES`/`$DOC_FILE_PATTERN` change.
- One drift-fix during build: helper crashed on first JSON serialization with `TypeError: Object of type BinOp is not JSON serializable` because `param_annotations` AST nodes leaked into `candidates[:5]` slices of phantom records. `_jsonable_candidate(c)` was added and routed through both kwarg and type-shape phantom emitters; existing `tests/test_phantom_api_precheck_kwargs.py` (which calls the wrapper end-to-end via subprocess) was the failing canary that surfaced this.

**Closes:** GH issue #406.

**Related:** AD-685 v1 (Wave 11, kwarg-name validation), AD-685b v1 (Wave 15, method-call AST validation), AD-685d (Wave 47 / future, dataclass / Pydantic field-name validation).

### AD-661b + AD-661c v1: DiagnosticContextService Ship's Records + Budget Remainder Redistribution (2026-05-04)

**Problem:** AD-661 v1 (Wave 33, commit 9119f50) shipped a 3-tier pull-based diagnostic-context aggregator with a hard 40/30/30 split and no remainder redistribution. Two follow-ups remained open: AD-661b (#412) — bundle had no Ship's Records (AD-434) coverage even though `runtime.records_store` was already public; AD-661c (#413) — when one tier under-filled its allocation (e.g. procedures producing 200 tokens against a 2400-token slice), the unused budget went to waste even when other tiers had more candidates waiting. Captain's Wave 45 "no trivial deferral" rule: ship both extensions in one Builder cycle.

**Decision:** Promote allocation to 4 tiers + add two-pass fill with priority-ordered remainder redistribution.

- **AD-661b**: `DiagnosticBundle` gains `records: list[dict]` field. New `_gather_record_candidates(*, keywords)` collector reads `runtime.records_store.list_entries()` + `read_entry(path, reader_id, reader_department)`. Synthetic system reader (`_RECORDS_READER_ID = "_diagnostic_context_system"` + empty department) naturally surfaces only ship/fleet records via RecordsStore's built-in classification gate. Per-agent record authorization deferred AD-661f. Each accepted record normalized to flat dict (path/title/summary_excerpt/classification/author/status/tags); content truncated to `_RECORDS_CONTENT_EXCERPT_CHARS=1200`; candidate list capped at `_MAX_RECORDS_CANDIDATES=30`. Tier-2 log-and-degrade.
- **AD-661c**: `_collect_*` collectors renamed to `_gather_*` candidate producers (no per-tier budget clip). New `_fill_with_redistribution(candidates_by_tier, allocations, total_budget, redistribute) -> (filled, truncated)` centralizes budget bookkeeping. Priority order `_TIER_PRIORITY = ("chain_traces", "procedures", "episodes", "records")`. Pass 1 fills each tier up to its allocation; Pass 2 (only when `redistribute=True`) walks tiers in priority order topping up while global budget has room. `truncated=True` iff global budget exhausted AND at least one tier still has unconsumed candidates.
- Default allocation split moves from 40/30/30 (3-tier) to 30/25/25/20 (4-tier). `redistribute_remainder=True` by default — default-on rather than transitional-flag-off because the change is strictly an enhancement: under-filled tiers no longer lose budget that other tiers could use. The router is unchanged because `bundle.to_dict()` automatically includes the new `records` key.

**Rationale:** AD-661 v1's hard 40/30/30 split was a deliberate first-cut bound — simple, predictable, easy to reason about — with redistribution explicitly punted to a follow-up. Six months of integration data shows under-filled tiers are common (procedures often have only 1–2 entries; episodes drop to 0 when no exemplars exist), and the wasted budget directly degrades chain-trace coverage which is the richest diagnostic signal. Two-pass fill with priority ordering retains the v1 "each tier gets a guaranteed slice" contract while giving the global budget back to whoever can use it. Records as a 4th tier is the obvious next step: AD-434 had been shipped for many waves, `runtime.records_store` is public, and the Lee et al. Meta-Harness proposer (arXiv:2603.28052) calls for *all* available raw diagnostic context. The synthetic system reader is the simplest way to surface ship/fleet records without coupling to per-agent clearance plumbing (AD-635/AD-660/AD-692 already own the agent-clearance graph; folding it into a read-only aggregator would breach Open/Closed).

**Trade-offs:**

- v1 had a strong "each tier gets exactly its slice" semantic; v1c relaxes it. Tests that asserted `truncated` under the v1 per-tier-cap semantics now need to overflow the GLOBAL budget rather than just one tier's slice. One v1 test fixture (test_chain_trace_keyword_filter_and_budget) needed amendment for this reason — c3 row content bumped from 6000 to 12000 chars.
- Records via synthetic system reader cannot surface department-classified records to agents who would normally have department-level access. AD-661f will plug per-agent reader identity in.
- `_TIER_PRIORITY` is hardcoded chain_traces > procedures > episodes > records. If integration data shows records or episodes deserve higher priority for some queries, the priority order would need to become query-aware (deferred).

**Closes:** GH issues #412 + #413.

**Related:** AD-661 (v1, Wave 33), AD-657 (trace preservation), AD-658 (chain traces), AD-434 (Ship's Records), AD-692 (edge classification — orthogonal taxonomy by design).

### AD-594c v1: Parallel Execution Dispatch (2026-05-06)

**Problem:** AD-594a (Wave 44) shipped the consultation workspace substrate with `plan/plan_v{N}.md` files, a `workitems/` subdirectory, and `ConsultationWorkspace.add_work_item(spec)` that writes a YAML file. AD-594d (Wave 79) shipped the delivery pipeline. The middle of the consultation flow — converting an approved plan into actual `WorkItem` rows on the canonical `WorkItemStore` so executors can pick them up — had no implementation. GH #162 listed seven scope bullets covering decomposition, conflict detection, multi-executor dispatch, task boundaries, progress, completion, and blocker escalation.

**Decision:** Ship full v1 scope in Wave 80 (Captain rule "don't defer unless no choice"). Single new module `src/probos/consultation/dispatch.py` ships: (a) `WorkItemSpec` frozen dataclass (producer side); (b) `PlanDecomposer` Protocol + `MarkdownPlanDecomposer` v1 default (ATX-2 task headings + `- key: value` bullet parser; recognised keys id/description/work_type/agent/priority/depends_on/resources; unknown keys routed to metadata; missing id falls back to title slug) — LLM-driven semantic decomposers plug in behind the seam (mirrors AD-594a `InputProcessor` + AD-594d `FormatTransformer` precedent); (c) `ConflictDetector` (stateless `detect(specs) -> list[ConflictPair]` flagging any two specs sharing a resource); (d) `ParallelDispatcher` orchestrator with five public async methods — `dispatch(workspace_id, *, plan_version=None)` reads latest plan via `RecordsStore.read_workspace_file`, decomposes, conflict-resolves by injecting synthetic `depends_on` edges in original spec list order, registers each spec via `runtime.work_item_store.create_work_item(work_type=spec.work_type or "duty", title=..., description=..., depends_on=[wid_of_dep_specs], assigned_to=spec.agent or None, tags=sorted({"consultation", "workspace:<id>"}), metadata={workspace_id, spec_id, resources, plan_version})`, mirrors each spec via `workspace.add_work_item(spec_dict_with_real_id)`, transitions APPROVED → EXECUTING, emits `PARALLEL_DISPATCH_STARTED`; `get_progress` aggregates by status + emits `PARALLEL_DISPATCH_PROGRESS` when subscription enabled; `check_completion` is idempotent EXECUTING → COMPLETED with journal entry, returns False after first transition; `detect_blockers(now=None)` emits `PARALLEL_DISPATCH_BLOCKED` per spec via per-blocker dedup ring after `blocker_threshold_seconds` (default 600); `revoke` cancels non-terminal items for teardown. (e) Three new EventTypes (`PARALLEL_DISPATCH_STARTED`/`_PROGRESS`/`_BLOCKED`) verified collision-free at HEAD. (f) `ConsultationDispatchConfig` Pydantic model (`enabled=True`, `default_work_type="duty"`, `default_tags=["consultation"]`, `blocker_threshold_seconds=600.0`, `progress_subscription_enabled=True`) wired on `SystemConfig` adjacent to `consultation_delivery`. (g) `_wire_consultation_dispatch` finalize wirer gated on `runtime.consultation_workspaces` AND `runtime.work_item_store` AND `runtime.records_store`; tier-2 log-and-degrade with INFO log on missing dependency; sets public `runtime.consultation_dispatcher` attribute (Wave 5 conv #1). Default-True is intentional — dispatcher construction is read-only on boot (no IO; only resolves runtime references); side effects fire only on explicit `dispatch(...)` calls.

**Consequences:** Closes GH #162 cleanly — every issue-body bullet ships. Future LLM-driven semantic decomposers plug in behind the `PlanDecomposer` Protocol without reshape. AD-581 Hybrid Dispatch (#113) consumes correctly-shaped WorkItems via `assigned_to` string + `metadata.workspace_id`/`spec_id`; ASA hand-off remains AD-581's surface. AD-594b (#161 consultation primitive) is unrelated — verified zero coupling at HEAD; plan content sourcing is upstream of dispatch. AD-594d delivery is the consumer's call — `check_completion()` does NOT auto-trigger `runtime.consultation_delivery.deliver(...)`. No `WorkItemStore` schema migration; all metadata travels in existing `metadata` JSON column + `tags` JSON column. No `WorkspaceLifecycleState` enum or `_ALLOWED_TRANSITIONS` change — existing APPROVED → EXECUTING → COMPLETED chain plus AD-594d's COMPLETED outflow is sufficient. No HXI surface (AD-594c-i covers HXI when consumer signal arrives). 37 focused tests pass; sibling regression (594a/594d/workforce) 160/160 green; full xdist gate 11548 passed + 1 environmental flake (passes serially) + 16 skipped = 11565 collected (+37 vs 11528 baseline, exceeds +25 floor). Closes GH issue #162.

### AD-594a v1: Consultation Workspace Substrate (2026-05-04)

**Problem:** AD-594 Crew Consultation Protocol decomposed into four independent ADs (594a/b/c/d). Without a session-scoped shared workspace in Ship's Records, the consultation primitive (594b), parallel execution dispatch (594c), and delivery pipeline (594d) all have no anchor — multi-agent advisory consultations would either smuggle state through ad-hoc IntentMessage payloads or write to records-store with the wrong frontmatter wrapper. The substrate must ship first; sibling ADs build on it.

**Decision:** Ship the workspace substrate as Wave 44's single full-scope AD (Captain "no trivial deferral"). Three converging components: (a) `RecordsStore` gains three public raw-file methods (`write_workspace_file`/`read_workspace_file`/`append_workspace_file`) that bypass YAML frontmatter coercion, reuse `_safe_path` traversal protection + `_commit` git plumbing — workspace files (`manifest.yaml`, `journal.md`, `delivery.yaml`, `plan_v{N}.md`, advisory `{agent}_{ts}.md`, `wi_{id}.yaml`) are YAML/Markdown of varied shapes for which the existing frontmatter wrapper is wrong. `consultations` appended to `_SUBDIRS` (mirrors `bills` AD-618a precedent). (b) New `src/probos/consultation/` package: `inputs.py` ships `InputProcessor` `Protocol` + `PassthroughTextProcessor` v1 default + `build_input_processor` factory (Northstar II Transporter Pattern integration point — PDF/image/audio processors plug in here under separate AD; today's `cognitive/builder.py` Transporter is unrelated builder code-chunk decomposition); `refs.py` ships pure-string `parse_workspace_refs`/`render_workspace_refs_md` for `[workspace:<id>/<path>]` markdown-link substitution (HXI integration deferred — `MessageStore.create_post()` wrapper is consumer-side); `templates.py` ships `ArtifactType` enum (5 values) + 5 render functions + 3 consultation templates registered in `TEMPLATES` dict (`security_review`/`technical_design`/`incident_response`); `workspace.py` ships `WorkspaceLifecycleState` IntEnum (7 values, `_ALLOWED_TRANSITIONS` adjacency map with PLAN_REVIEW → CONSULTING revision allowed and ARCHIVED terminal), `ConsultationWorkspaceSummary` frozen dataclass, `ConsultationWorkspace` instance class with six convenience writers each appending a journal entry + `transition_to(state)` validates predecessor (invalid → False + WARNING, never raises) + `append_journal` log-and-degrade + `list_paths()` + atomic filename-based `plan_v{N+1}.md` versioning, and `WorkspaceRegistry` with `create(*, title, owner_agent_id, participants, template=None)` (workspace_id = uuid4().hex[:12], materializes 6 subdirectories via `.gitkeep`, persists initial manifest at `schema_version=1` INITIATED, writes empty `delivery.yaml` placeholder for AD-594d, applies template if known) + `get(id)` with cache + `list_active()` filters ARCHIVED. (c) `ConsultationWorkspaceConfig` Pydantic model (`enabled=True`, `root_path="consultations"`, `input_processor="passthrough"`) wired on `SystemConfig` adjacent to `clinical_telemetry`; new sync `_wire_consultation_workspaces` finalize wirer reads `runtime.records_store` (AD-434 adopted in cognitive phase, well before finalize), constructs `runtime.consultation_workspaces` collision-free public attribute, log-and-degrades when records_store unavailable. Default-True is intentional — registry is read-only on boot (constructs empty in-memory cache; only side-effect is `RecordsStore` `_SUBDIRS` mkdir at first init); same precedent as `KnowledgeEdgesConfig` / `EdgeBackfillConfig`.

**Consequences:** Sibling ADs 594b/c/d (#161/#162/#163) now have a stable anchor to build on; consultation primitive can write advisor contributions to `advisory/`, parallel execution dispatch can decompose plans into `workitems/*.yaml`, delivery pipeline can populate the empty `delivery.yaml` placeholder. HXI integration of `[workspace:...]` refs becomes a consumer-side task — pure helpers ship, no `ward_room/` modification. Future PDF/image processors plug into the stable `InputProcessor` Protocol seam without reshape. `RecordsStore` gains a raw-file surface that other future subsystems may reuse (e.g., procedure attachments, scout report bundles). Workspace lifecycle state machine enforces invariants at the substrate boundary — invalid transitions cannot corrupt downstream consensus or planning. 16 tests pass; full gate 11094 passed (delta +16). Closes GH issue #160.

### AD-695 v1: Ship Health Oracle Tier + Threshold Bridge Alerts (2026-05-04)

**Problem:** Three converging gaps prevented the Crew from reading ship health through the same channel they read every other knowledge surface. (1) No Oracle tier surfaced operational telemetry — crew agents wanting vitals/pool/attention/degradation state had to reach into private runtime attributes (`runtime._emergent_detector`, `runtime.attention._queue`, etc.) with no public, score-ranked, provenance-tagged surface. (2) AD-641a ObservabilityBridge wrote spam into a non-existent Ward Room thread; BF-258 already disabled the `_publish_once` posting call but left the bridge as a heart with no pulse — it ticked every 60s and produced nothing actionable. (3) No threshold-driven bridge alerts for system health existed: `BridgeAlertService` already supported vitals/trust/convergence/cascade alerts but had no `check_pool_saturation`/`check_degradation`/`check_attention_depth` family; the Captain only learned about pool saturation when something downstream failed.

**Decision:** Three additive components, all in OSS, landing in a single Wave 43 v1 commit.

1. **Oracle Tier 7 "health"** — new `OracleService._query_health(query_text, *, k)` reads pool stats + attention queue + degradation status from a duck-typed `health_provider` (anything exposing `spawner.pools` + `attention` + `degradation_manager` + optional `observability_bridge`). Each metric becomes one `OracleResult` scored by simple keyword overlap against the query, with `provenance="[health: <metric>]"`. `"health"` appended as the 7th element of the default `active_tiers` list. Tier 7 dispatch slot is inserted between Tier 6 (graph) and `_expand_via_graph` so health results compete in expansion ranking. New ctor kwarg `health_provider: Any = None` plus public idempotent `attach_health_provider(provider)` setter mirroring AD-686/AD-688 late-bind shape. The runtime itself satisfies the duck-typed protocol; tests inject `SimpleNamespace`.

2. **`ThresholdAlertService`** (`src/probos/cognitive/threshold_alerts.py`) — frozen `ThresholdAlert` dataclass (threshold_id/severity/metric/value/threshold/title/detail/fired_at + optional related_pool) and `ThresholdAlertService(runtime, *, pool_saturation_floor=0.9, degradation_min_severity="degraded", attention_queue_depth=20, dedup_window_seconds=300.0)`. Single public `async check_and_alert() -> list[ThresholdAlert]` runs three independently log-and-degrade checks (pool_saturation per pool; degradation via `StressLevel` ordering `{normal:0, elevated:1, degraded:2, critical:3}` with `severity="alert"` only at CRITICAL; attention queue depth) and posts each fired alert via `runtime.ward_room_router.deliver_bridge_alert(BridgeAlert(...))` with id=uuid4, alert_type=threshold_id, dedup_key=threshold_id, severity coerced to `AlertSeverity` enum. Per-(threshold_id) dedup ring with configurable sliding window, prunes entries older than 2x window. Service NEVER raises into caller — every check + every delivery is best-effort.

3. **Bridge loop becomes a threshold loop** — `ObservabilityBridge._publish_once` (BF-258 already nuked the `create_post()` spam) now invokes `await runtime.threshold_alerts.check_and_alert()` when wired, then preserves the existing `OBSERVABILITY_SNAPSHOT_PUBLISHED` event emit. `take_snapshot()` retained unchanged for both Tier 7 vitals augmentation and event-log subscribers. The bridge is no longer dormant — it is the cadence trigger for threshold checks.

New `ThresholdAlertConfig` Pydantic model with **default-False** (operator opt-in — ThresholdAlerts actually post things on enable, unlike AD-687/AD-689/AD-692 default-True transparent pass-through). New finalize wirer block immediately after AD-641a ObservabilityBridge block constructs `runtime.threshold_alerts` when enabled (else None), and ALSO unconditionally stitches `oracle.attach_health_provider(runtime)` for the Oracle Tier 7 late-bind (Tier 7 returns `[]` until this stitch runs).

**Implementation:** ~250 lines new `threshold_alerts.py` + ~360 lines new `test_ad695_ship_health_oracle.py` (13 tests); MOD `config.py` (+~12 lines for ThresholdAlertConfig + SystemConfig field), `finalize.py` (+~40 lines for wirer block + Oracle stitch), `oracle_service.py` (+~140 lines for ctor kwarg + attach setter + tier-list update + dispatch slot + `_query_health` method), `observability/bridge.py` (+~10 lines, `_publish_once` body replaced with threshold-call + event emit).

**Critical architect calls:**
- **DLog #1 — BF-258 ALREADY removed `create_post()`**: the comment at `bridge.py:121-124` already mentions "Crew queries system health via Oracle (AD-695)" as the planned replacement. The "spam loop disable" component of the user spec was a NO-OP at HEAD; v1 replaces the dormant body with the guarded `check_and_alert()` call.
- **DLog #2 — `runtime` IS the health_provider**: OracleService at HEAD never reaches `runtime` directly (uses injected providers per AD-686/AD-688). AD-695 mirrors that pattern via duck-typed `health_provider`; finalize wirer calls `oracle.attach_health_provider(runtime)` since runtime satisfies the protocol natively.
- **DLog #3 — Default-False on ThresholdAlertConfig is REQUIRED, NOT a deviation**: unlike AD-687/AD-689/AD-692 (default-True with pass-through-when-disabled cost), ThresholdAlerts actually post BridgeAlerts on enable. Operator opt-in needed.
- **DLog #4 — BridgeAlert reuse, not BridgeAlertService consumption**: ThresholdAlertService constructs `BridgeAlert` directly and posts via `ward_room_router.deliver_bridge_alert(ba)`, NOT calling `BridgeAlertService.check_*` (those have hardcoded thresholds + global dedup ring; would couple two dedup systems). ThresholdAlertService has its own dedup ring keyed on threshold_id with configurable window.
- **DLog #6 — Pool surface reduced to current/target only**: `Pool.info()` at HEAD does NOT expose cooldown counts (verified by grep). Cooldown surfacing deferred — would require Pool.info() schema change.
- **DLog #7 — Tier 7 dispatch position critical**: must run BEFORE `_expand_via_graph` (Tier 7 results compete in expansion ranking) and AFTER all 6 existing tiers.

**What this AD does NOT change** (out of scope by design): no HXI/dashboard integration of Tier 7 (deferred AD-695b if data warrants); no historical retention of alerts beyond the `bridge_alert` event row `deliver_bridge_alert` already writes (existing AD-410 untouched); no per-agent health querying; no active shedding hooks (still AD-459b/AD-396); no AD-466 infrastructure restructuring; no full AD-466c scope (audit log, retention, per-pool thresholds deferred); existing `BridgeAlertService` untouched; no new EventType.

**Tests:** 13 in `tests/test_ad695_ship_health_oracle.py` — default tier list contains `"health"` 7th; `_query_health` returns `[]` when no provider; pool happy path; attention queue metric; degradation metric; query keyword filter; k-truncation; `ThresholdAlertConfig` defaults; pool saturation breach fires; degradation CRITICAL escalation fires (severity=alert); attention queue depth fires; dedup prevents repost within window then fires again after window advances; no-breach returns empty.

**Result:** Full gate 11078 passed, 15 skipped (delta +13 vs Wave 42 baseline 11065 — exact target hit). Closes GH issue #389.

**Related:** AD-462e (Oracle), AD-641a (ObservabilityBridge), BF-258 (Ward Room posting disabled), AD-466/AD-459 (DegradationManager), AD-410 (BridgeAlertService + WardRoomRouter.deliver_bridge_alert), AD-686/AD-688/AD-692 (current Oracle tier list — Tier 5/6 + classification gate).

### AD-692 v1: Classification Enforcement on Knowledge Graph Edges (2026-05-04)

**Problem:** AD-687 (Wave 37) provisioned `KnowledgeEdge.classification` as a string field with values from `records_store._CLASSIFICATION_LEVELS` (private/department/ship/fleet) but did NOT enforce it on read or write. Any caller could read every edge regardless of classification, write edges at any level without authority check, and a future federation export would forward all edges including `fleet`-classified.

**Solution:** Decorator-pattern wrapper `ClassificationGatedKnowledgeEdgeStore` around the existing `SQLiteKnowledgeEdgeStore`. Implements the `KnowledgeEdgeStorage` Protocol so it is a drop-in replacement; reads accept an optional `requester_agent_id` kwarg and filter edges by clearance; writes route through `KnowledgeEdgeClassificationGate.authorize_write()` which checks the writer's clearance against the edge's classification. Pure synchronous `filter_for_export(edges, *, target_classification)` ships as the federation extension seam (default excludes FLEET). 4-tier `ClassificationLevel` IntEnum mirrors `records_store._CLASSIFICATION_LEVELS` integer ordering byte-for-byte. Late-bind clearance resolver via setter so the wrapper module does NOT import substrate (`earned_agency`, `ontology`) directly — wirer in `startup/finalize.py` builds the closure over `runtime.ontology` + `runtime.clearance_grant_store` + `runtime.registry` and re-stitches Oracle Tier 6 via `oracle.attach_knowledge_graph(wrapper)` so graph queries flow through the gate, not the bare store. `OracleService._query_graph` plumbed with `requester_agent_id` from the existing `query()` `agent_id` kwarg; `TypeError` fallback in two private helpers (`_graph_find_edges`/`_graph_traverse`) keeps Tier 6 compatible with both the wrapper and the bare AD-687 store (preserves Wave 38 MagicMock-based tests).

**Taxonomy decision:** AD-679 SHIPPED but ORTHOGONAL. AD-679 is 5-tier `DisclosureLevel` IntEnum (PUBLIC..CLASSIFIED) for IntentMessage recipient routing; AD-692 is 4-tier `ClassificationLevel` IntEnum (PRIVATE..FLEET) for KnowledgeEdge read/write gating. **Different taxonomies by design** — recipient clearance vs. data-scope-of-audience. Bridging intentionally NOT provided in v1; `filter_for_export` ships as a documented seam for future commercial overlay or an AD-692c bridging AD if signal justifies.

**Backward-compat invariant:** when `requester_agent_id is None`, the wrapper is a no-op pass-through. All Wave 37/38/39/40/41 tests stay green WITHOUT modification (they don't pass `requester_agent_id`). Default `enabled=True` follows the same precedent as `KnowledgeEdgesConfig` and `EdgeBackfillConfig` — zero-cost transparency until consumers (Oracle Tier 6 via AD-688 plumbing) supply a requester id.

**OSS-vs-commercial boundary:** v1 ships the OSS extension point — the gate, the wrapper, the resolver injection seam, the federation export helper, the Oracle Tier 6 plumb. Commercial overlays (audit-event persistence, RBAC, multi-tenant policy, AD-679 bridging) layer on top of the stable `KnowledgeEdgeStorage` Protocol seam without modifying the underlying store. Per-department classification matching is deferred to AD-692b if adoption signals justify (KnowledgeEdge has no department field today; v1's DEPARTMENT gate is tier-based only).

**Tests:** 21 (over the 12 floor by 9 — parametrized 8-case matrix in `test_edge_visible_to_matrix` is the fan-out source). Closes GH issue #386. Wave 42.

---

### AD-691 v1: NL-to-Graph Query Service — Ship's Computer Structural Routing (2026-05-04)

**Problem:** Phase B (Intelligence) of the Unified Knowledge Graph stack. AD-687 (Wave 37) provisioned `runtime.knowledge_edges`. AD-688 (Wave 38) made it queryable through the Oracle's Tier 6. AD-689 (Wave 39) populated it from four structural data sources. The graph is now populated and queryable — but there is no LLM-driven NL-to-graph entry point. A human asking "who reports to the chief engineer?" or "what duties depend on the medical bay?" has no path that uses the graph relations as first-class structure. Tier 6 falls back to bag-of-tokens against `source_id`/`target_id` strings, which only fires when the query happens to contain literal IDs.

**Decision:** New `NLGraphQueryService` in `src/probos/cognitive/nl_graph_query.py` ships a 2-phase LLM-driven service. Phase 1 (extraction): `tier="standard"` LLM call returns strict JSON `{entities: [{id, type}], relation_filter: [...], intent: "find|traverse|count"}`. Graph step: per entity, `runtime.knowledge_edges.find_edges(...)` for direct hits (proximity 1.0) and `traverse(..., max_hops=N, relation_filter=...)` for multi-hop paths, with `max_hops` clamped to `MAX_HOPS_CEILING=3` and `limit` floored at 1. Scoring extends AD-688: `score = edge.weight × edge.confidence × hop_proximity` where `hop_proximity = 0.6 ** (hop - 1)` (direct=1.0, hop-2=0.6, hop-3=0.36). Sort descending, dedupe by `edge.id` keeping highest score, truncate to `limit`. Phase 2 (synthesis): `tier="standard"` LLM call inlines the structured graph results and returns a natural-language answer that **must** cite edges as `[graph: <edge.id>]` for every fact derived from a graph hit. Returns `NLGraphQueryResult` frozen dataclass: `query`, `extracted_entities`, `edges_traversed`, `paths`, `answer`, `provenance`. The `provenance` field is the deduped, in-order list of edge IDs ACTUALLY cited in the answer (extracted via regex and filtered against the retrieved-edge set so hallucinated IDs are silently dropped) — distinct from `edges_traversed` which lists every edge the graph step retrieved. New `NLGraphQueryConfig` Pydantic model on `SystemConfig` with `enabled=True` (deviation from Wave-10 transitional-flag convention; documented — service is a callable read-only aggregator with no automatic invocation). Sync `_wire_nl_graph_query` wirer in `startup/finalize.py` mirrors `_wire_diagnostic_context`. New public attribute `runtime.nl_graph_query` (Wave 5 conv #1; collision-free greenfield). New `GET /api/nl-graph-query?q=&max_hops=&limit=` router.

**Decomposer integration ships in v1 via `NLGraphQueryAgent`** (no decomposer-side modification — leverages existing dynamic `IntentDescriptor` discovery at `cognitive/decomposer.py:280`). New single-agent utility pool wraps the service and self-registers `IntentDescriptor(name="nl_graph_query", tier="utility", requires_consensus=False, requires_reflect=True)`. Pattern mirror: `agents/introspect.py` (`tier="utility"`, `_runtime`-backed delegation, full `perceive→decide→act→report` lifecycle). Spawner template registered in `runtime.py` immediately after `introspect`; pool created in `startup/agent_fleet.py` immediately after the `introspect` pool block, gated on `config.nl_graph_query.enabled` AND `runtime.nl_graph_query is not None`.

**Architect calls.** (1) Decomposer integration shipped via the agent route, not via decomposer-side editing — the decomposer already discovers intents dynamically from `IntentDescriptor` metadata declared by registered agents, so the natural fix is a thin wrapper agent that self-integrates. (2) Provenance citation format `[graph: <edge.id>]` mandated by the Phase-2 system prompt; `provenance` field is what the LLM actually cited (filtered via `_CITATION_RE = r"\[graph:\s*([0-9a-fA-F]{16,})\s*\]"` against the retrieved edge-set), which lets downstream consumers distinguish "what the graph returned" from "what the answer claims". (3) Empty-extraction short-circuit avoids second LLM call (`entities: []` → `"No graph entities identified in query."` immediately, bounding cost on irrelevant queries and giving a deterministic test surface). (4) Phase-1 parse-failure fallback is tier-2 log-and-degrade — never raises into the caller. (5) Hop-proximity formula extended for hop=3 (`0.6 ** (hop-1)` → 0.36) and computed inline (NOT config; same precedent as AD-688's `_GRAPH_HOP_PROXIMITY_DIRECT/TWO_HOP`). (6) `relation_filter` whitelist enforcement: filter raw strings against `KnowledgeRelationType.value` set; unknown values dropped at `logger.debug`; empty post-coerce → pass `None` to `traverse()`.

**Hard limits (v1).** NO decomposer-side modification (the agent + pool route via existing dynamic registry). NO embedding-based fuzzy entity match (deferred AD-691c if surfaced; v1 uses verbatim entity IDs as extracted by the LLM). NO write/mutation queries (graph is read-only here). NO classification-aware filtering (AD-692 commercial owns). NO Fabric IQ NL2GQL parity (v1 is simple typed-triple traversal). NO HXI surface (deferred until consumer signal). NO new EventType. NO Pydantic config for hop-proximity formula (inline). NO persistence of query history (each call stateless). NO streaming response.

**Commercial-tag handling.** GH issue #385 is tagged `Layer:Commercial` — the OSS extension point (`runtime.nl_graph_query` callable + `NLGraphQueryAgent` + `GET /api/nl-graph-query`) ships in OSS as the public mechanism. Commercial overlays (RBAC-aware routing, audit pipelines, multi-tenant scoping) layer on top of the public surface without modifying it. No pricing/positioning language in this AD or in any of the shipping artifacts.

**Tests.** 16 focused tests at `tests/test_ad691_nl_graph_query.py` (over 14 floor by 2): result-dataclass frozen + `to_dict` round-trip; service ctor 6-kwarg shape; happy path with `_StubLLM` (Phase-1 entity → 1 direct edge → Phase-2 with citation → `provenance == [edge.id]`); Phase-1 parse failure (`llm.calls == 1`, no Phase-2); empty-extraction short-circuit (`llm.calls == 1`, `find_calls == []`); `relation_filter` passthrough (coerced to `[KnowledgeRelationType.REPORTS_TO]`); unknown relation dropped silently; `max_hops=99` clamped to 3; `limit=5` truncates 25-edge result; scoring orders by `weight × confidence × proximity` descending; hallucinated `[graph: deadbeef...]` citation filtered from `provenance`; no-edges → `"No relevant graph evidence."` + no Phase-2; API endpoint 400 on empty `q`; API endpoint 200 happy-path with `TestClient` + `dependency_overrides`; `NLGraphQueryAgent.handle_intent` happy-path delegates to `runtime.nl_graph_query.query(...)` with NL passed through verbatim and result fields projected to `IntentResult.result` dict; pool/template registration smoke (config defaults match, `IntentDescriptor` declared with `tier="utility"`, spawner template registers cleanly).

**Drift-fixes during build.** (1) `BaseAgent` is abstract with required `report()` method — added `async def report(self, result)` returning `result` to `NLGraphQueryAgent` (mirrors `IntrospectionAgent.report` shape). (2) Test 16 referenced `from probos.spawner import AgentSpawner` (wrong path); corrected to `from probos.substrate.spawner import AgentSpawner` + `from probos.substrate.registry import AgentRegistry` and pass registry to ctor. (3) `tests/test_utility_agents.py::test_all_agents_exported` asserts `set(__all__) == expected` (exact equality) — extended `expected` to include `"NLGraphQueryAgent"` to keep the existing utility-export contract.

**Related:** AD-687 (Knowledge Edge Store), AD-688 (Oracle Graph Integration — Tier 6 + post-merge expansion), AD-689 (Edge Population), AD-690 (Dream Step 10 — Relationship Inference), AD-661 (DiagnosticContextService — runtime-injection sibling shape), AD-468 (Ship's Computer Config). Closes GH issue #385.

### AD-689 v1: Edge Population from Existing ProbOS Data (2026-05-04)

**Problem:** Phase A foundation (fourth and last) of the Unified Knowledge Graph + Oracle Unification stack. AD-687 (Wave 37) provisioned `runtime.knowledge_edges`. AD-688 (Wave 38) made it queryable via `OracleService` Tier 6 and post-merge `_expand_via_graph`. Both work; the graph is empty. Tier 6 + expansion therefore both return `[]` in production today. ProbOS already holds the four primary signal sources to bootstrap the graph: ontology (org-chart + crew assignments), Hebbian router (learned `(intent, agent, "intent")` triples), episodic memory (`Episode.agent_ids` participation), and `DECISIONS.md` cross-references (`**Related:** AD-...` and `Closes #N`). Without a one-shot population pass, the graph stays empty until Dream Step 10 (AD-690) starts producing edges incrementally — which itself depends on having seed data to compete against.

**Decision:** Ship a complete v1 (Captain "no trivial deferral" convention banked 2026-05-04) covering all four sources in a single Builder cycle. New `EdgeBackfillService` async aggregator with one method per source plus `backfill_all()` returning a `EdgeBackfillResult` frozen dataclass (per-source counts + `total` property + `started_at`/`duration_ms` timing + `to_dict()` projection). Idempotent by deterministic 32-hex `edge_id = sha256(f"{src_type}|{src_id}|{rel}|{tgt_type}|{tgt_id}")[:32]` combined with the AD-687 `INSERT OR REPLACE` upsert at the storage layer — re-runs of any backfill leave total row count unchanged without needing read-modify-write. All four backfills are tier-2 log-and-degrade — a missing/failing source contributes 0 to the count and never raises into `backfill_all()`. New `EdgeBackfillConfig` Pydantic model (`enabled=True`, `run_on_warm_boot=True`, `hebbian_threshold=0.5` validated [0,1], `force=False`, `decisions_paths=[5 default md files]`) and async `_wire_edge_backfill` wirer in `startup/finalize.py` that runs on warm boot only when the `knowledge_edges` table is empty (or `force=True`). New public `runtime.edge_backfill` attribute (Wave 5 conv #1; collision-free greenfield).

New public method on `EpisodicMemory`: `async list_episodes(*, limit: int | None = None) -> list[Episode]` mirrors the existing `recent()` shape and uses the same `_metadata_to_episode` reconstructor — backfill consumes a public API instead of reaching `_collection.get(...)` directly (Open/Closed; Demeter).

**Architect calls.** (1) Edge-ID determinism scheme uses SHA-256-truncated-to-32-hex of the typed-triple key — combined with INSERT OR REPLACE upsert at AD-687 storage layer, this gives idempotency without read-modify-write; `created_at` drifts on re-upsert but `id` is the dedup key and total row count is the assertion target. (2) Captain spec mentioned `**Resolved by:** ...` markdown pattern but it does not exist as a structured marker in `DECISIONS.md` (only prose). The real structured marker is `Closes (?:GH issue )?#NNN` (case-insensitive). Builder uses `Closes` as the RESOLVED_BY signal (`DECISION:AD-N RESOLVED_BY INCIDENT:gh-N`). (3) Hebbian only `REL_INTENT` weights become COMPETENT_IN edges. REL_AGENT/REL_SOCIAL/REL_BUILDER_VARIANT/REL_STRATEGY are out of scope v1 (would need different relations not in the Wave 37 10-relation enum). Direction: `agent COMPETENT_IN intent` — source=AGENT(target), target=CAPABILITY(source) since HebbianRouter REL_INTENT triples are `(intent, agent, "intent")`. (4) RESOLVED_BY direction: source=DECISION, target=INCIDENT — consistent with how the relation was named in the AD-687 enum and how AD-688 Tier 6 entity-substring scoring queries from either side via `find_edges(source_id=...)` AND `find_edges(target_id=...)`.

**Hard limits (v1).** NO LLM-based NL-to-graph entity extraction (deferred AD-691, issue #385). NO live event-driven incremental backfill (deferred AD-690, issue #384). NO classification gating on backfill writes (deferred AD-692 commercial, issue #386). NO federation cross-instance edge sync (deferred AD-693 commercial, issue #387). NO new EventType (no audit emission; defer to AD-690 if needed). NO HXI graph visualization. NO shell command (use wirer or `runtime.edge_backfill.backfill_all()` directly). NO retention/pruning policy on `knowledge_edges`. NO mutation of existing AD-687 schema or AD-688 Oracle Tier 6.

**Per-source mapping.** Ontology — REPORTS_TO via post → assignment(s) → agent_type chain (AGENT(subordinate) → AGENT(superior)); MEMBER_OF per assignment (AGENT(agent_type) → DEPARTMENT(department_id resolved via `get_post(post_id).department_id`)). Hebbian — for each `((source, target, rel_type), weight)` from `all_weights_typed()` where `rel_type == REL_INTENT` AND `weight >= threshold`: emit AGENT(target) COMPETENT_IN CAPABILITY(source) with confidence=weight, weight=weight (both clamped to [0,1]). Episodes — for each Episode with non-empty `agent_ids`: AGENT(agent_id) INVOLVED_IN INCIDENT(episode_id) per agent. DECISIONS — for each `### AD-NNN[a-z]?` section: parse `**Related:** ...` line for `AD-\d+[a-z]?` tokens (self-skip), emit DECISION(AD-NNN) INFORMED_BY DECISION(AD-other) per related token; scan body for `Closes (?:GH issue )?#NNN` (case-insensitive), emit DECISION(AD-NNN) RESOLVED_BY INCIDENT(gh-N).

**Tests.** 12 focused tests at `tests/test_ad689_edge_backfill.py` (over 10-floor by 2): service shape + frozen-result + ctor surface; ontology emits 2 member_of + 1 reports_to with provenance; hebbian filters below 0.5 (0.7+0.6 pass, 0.3 + REL_AGENT excluded); custom threshold (0.7 drops, 0.1 includes); episodes per-agent (1+2+0 = 3 edges with ep-2 appearing twice); decisions Related: parsing (3 cross-refs across 2 sections); decisions Closes parsing (gh-382 + gh-383); backfill_all aggregation (total=7); idempotency (2nd run = same row count, deterministic ID matches helper); wirer skip-when-populated; wirer run-when-empty (1 member_of); wirer force=True override (2 edges total).

**Drift-fix.** Tests #11 + #12 initially failed with `35 == 2` because the wirer's default `decisions_paths` includes the real `DECISIONS.md` + era archives in the test cwd; fixed by passing `decisions_paths=[]` in the test `EdgeBackfillConfig`. No shipping-code change.

**Layer boundary.** Added exception `("knowledge/backfill.py", "probos.mesh.routing")` — `REL_INTENT` is a pure relation-type string constant (no behavioral coupling).

**Default-True deviation** from Wave-10 transitional-flag convention is intentional — same precedent as `KnowledgeEdgesConfig` and `CognitiveJournalConfig`: warm-boot wirer is a no-op once the table has any rows (idempotency-by-row-count guard).

**Related:** AD-687 (Knowledge Edge Store), AD-688 (Oracle Graph Integration), AD-686 (Oracle Tier 5 Semantic), AD-429 (Hebbian Router), AD-431 (Cognitive Journal — sibling default-True precedent), AD-657 (EpisodicMemory.get_by_ids — sibling list_episodes shape).

Closes GH issue #383.

---

### AD-688 v1: Oracle Graph Integration — Tier 6 + Post-Merge Expansion (2026-05-04)

**Problem:** Phase A foundation (third of four) of the Unified Knowledge Graph + Oracle Unification stack. AD-686 (Wave 36) added Tier 5 (semantic). AD-687 (Wave 37) shipped the `KnowledgeEdgeStorage` Protocol + `SQLiteKnowledgeEdgeStore` typed-triple substrate. The graph is now provisioned but unreachable: `OracleService.query()` only spans Tiers 1–5. Without a Tier 6 (`graph`) seam, agents searching for relational context ("who reports to bob?", "what depends on engine_room?") fall through Oracle's merged feed entirely. Closing this read seam unblocks AD-689 (backfill) and AD-690 (dream-step-10 inference) — they need a query surface to verify their writes against, even before populated data arrives in production.

**Decision:** Ship Tier 6 + post-merge graph expansion + runtime wiring + provenance + tier-list update all in a single v1 (Captain's "complete v1" convention banked 2026-05-04). All edits land in `cognitive/oracle_service.py` + `runtime.py` + new test file — NO new module, NO new EventType, NO new Pydantic config, NO new `runtime.X` slot.

- **Constructor kwarg + late-bind setter:** `OracleService(..., knowledge_graph=None)` (10th kwarg, kwargs-only) + public idempotent `attach_knowledge_graph(graph)` mirroring AD-686 `attach_semantic_layer` exactly. Runtime stitching late-binds at `runtime.py` immediately after `self.knowledge_edges = comm.knowledge_edges` adoption (Phase 7/Communication), wrapped in try/except + WARN log-and-degrade. Type narrowing via `Any` to avoid the cognitive↔knowledge import cycle; the `KnowledgeEdgeStorage` Protocol contract lives in method docstrings.
- **Tier 6 dispatch (`_query_graph`):** Token-substring entity match via module-private `_extract_entity_tokens(text)` (lowercase + split + strip trailing punct + drop <3 chars + drop ~50-token inline `_GRAPH_STOPWORDS` frozenset + dedupe preserving order + cap 16 tokens). For each token: `find_edges(source_id=token, limit=10)` AND `find_edges(target_id=token, limit=10)` for direct hits (hop_proximity 1.0); `traverse(source_type=match.target_type, source_id=match.target_id, max_hops=1)` from each direct match's target for 2-hop hits (hop_proximity 0.6). Score = `edge.weight × edge.confidence × hop_proximity`. Dedupe by `edge.id` keeping highest score across both directions + direct/traverse via module-level `_record_graph_hit` helper. Unattached graph → `[]` + debug log (never raises into `query()`).
- **Post-merge expansion (`_expand_via_graph`):** Runs BEFORE the final sort/truncate so expansion results compete on score in the merged ranking. Sorts merged_results desc, takes top-K (default 5), skips parents with `source_tier == "graph"` (no double-counting), extracts tokens from each parent's `content` via the same helper, fetches up to `_GRAPH_EXPANSION_PER_PARENT=5` neighbor edges via `find_edges(source_id=token)` (1-hop only — expansion is by design narrower than Tier 6), emits one OracleResult per neighbor with score = `parent.score × _GRAPH_EXPANSION_DISCOUNT(0.7) × edge.weight × edge.confidence`. Edge dedup via `seen_edges: set[str]` shared across all parents.
- **`OracleResult.provenance` is a top-level field, NOT a metadata key** (architect call). Captain's spec phrasing was loose (`metadata: "[knowledge graph]"`); the live dataclass has `provenance: str` as a separate field. Tier 6 hits: `provenance="[knowledge graph]"`. Expansion: `provenance=f"[graph expansion: {parent.provenance}]"`. Parent provenance mirrored into `metadata["expansion_source"]` + parent tier into `metadata["expansion_parent_tier"]` for downstream consumers that want to filter/group by origin tier without parsing the formatted string. Relocating provenance into metadata would break `query_formatted()` which reads `r.provenance` directly.
- **Tier list:** Default `active_tiers` becomes 6 entries: `["episodic", "records", "operational", "archive", "semantic", "graph"]`. Existing callers passing explicit `tiers=` lists keep their narrowed behavior. Adding `"graph"` to the default is the v1 opt-in: zero callers need to change, but the tier is live everywhere `tiers=None`.
- **Inline caps (NOT config):** `_GRAPH_DIRECT_LIMIT=10`, `_GRAPH_TRAVERSE_LIMIT=5`, `_GRAPH_EXPANSION_PER_PARENT=5`, `_GRAPH_EXPANSION_DISCOUNT=0.7`, `_GRAPH_HOP_PROXIMITY_DIRECT=1.0`, `_GRAPH_HOP_PROXIMITY_TWO_HOP=0.6`, `_GRAPH_MIN_TOKEN_LEN=3`. Externalize only if AD-688b adoption signals justify it.

**Out of scope (separate-issue scope, NOT v1 deferral):** NL-to-graph LLM entity extraction (AD-691, #385 future); edge population from existing data (AD-689, #383); Dream Step 10 relationship inference (AD-690, #384); classification enforcement on graph reads (AD-692, #386 commercial); federation cross-instance edge sync (AD-693, #387 commercial); HXI graph visualization (AD-690b or later); shell command (`/graph search`); graph metrics in `oracle.stats()` (deferred — no stats surface today).

**Outcome:** Tier 6 live in default active_tiers; post-merge expansion live in every `query()` call; runtime wiring stable across phase ordering. 13/13 new tests pass. Full gate 11004 passed (+13 vs Wave 37 baseline 10990 — exact target). No phantom APIs in shipping code; one builder drift-fix in test fixture (prompt-default `KnowledgeRelationType.COLLABORATED_WITH` is not on the AD-687 enum — switched to `MEMBER_OF`). Closes GH issue #382.

---

### AD-687 v1: Knowledge Edge Store (2026-05-04)

**Problem:** Phase A foundation of the Unified Knowledge Graph + Oracle Unification stack (`docs/research/unified-knowledge-graph.md` §"Storage Layer: SQLite First, Kùzu Upgrade Path"). AD-686 (Wave 36) absorbed the existing `SemanticKnowledgeLayer` as Tier 5, but ProbOS still has no typed-triple substrate for entity→relation→entity facts (e.g., `agent reports_to agent`, `department member_of ship`). Oracle Tier 6 (AD-688), Hebbian backfill (AD-689), and Dream Step 10 relationship inference (AD-690) all depend on this storage primitive existing first. Without it, every consumer would have to invent its own schema.

**Decision:** Ship a greenfield typed-triple SQLite store at `src/probos/knowledge/edges.py` with full CRUD + bounded recursive-CTE traversal, REUSING the existing `protocols.ConnectionFactory` / `DatabaseConnection` Protocol pair (no new connection abstraction). One module, one v1 build, no consumers — consumers arrive in separately-tracked ADs (AD-688/689/690).

- **Schema:** 13 columns (id PK, source_type/source_id, relation, target_type/target_id, confidence/weight floats in [0,1], optional classification/source_agent/source_duty, created_at/updated_at). Four indexes: source/target/relation/classification. Idempotent `CREATE TABLE IF NOT EXISTS`.
- **Type system:** 8-value `KnowledgeEntityType` str-Enum (AGENT, DEPARTMENT, INCIDENT, DECISION, DUTY, FINDING, CAPABILITY, STANDING_ORDER); 10-value `KnowledgeRelationType` str-Enum (REPORTS_TO, MEMBER_OF, COMPETENT_IN, RESOLVED_BY, INVOLVED_IN, INFORMED_BY, DEPENDS_ON, PRODUCED_BY, CLASSIFIED_AS, ORIGINATED_ON). Classification labels REUSE `records_store._CLASSIFICATION_LEVELS` keys (private/department/ship/fleet) — no new taxonomy.
- **Frozen dataclass:** `KnowledgeEdge` with 5 non-default + 8 defaulted fields (Python rule); `__post_init__` validates confidence/weight bounds and classification membership.
- **Service-layer Protocol:** `KnowledgeEdgeStorage` (6-method runtime-checkable async Protocol) declared in the same module — Dependency Inversion seam so AD-688 (Oracle Tier 6) and AD-689 (backfill) depend on the abstract type, not the concrete `SQLiteKnowledgeEdgeStore`. Commercial overlays (AD-694 Kùzu) implement this Protocol.
- **Concrete store:** `SQLiteKnowledgeEdgeStore` mirrors `CognitiveJournal` (AD-431) shape — `__init__(db_path, connection_factory)`, async `start()` provisions schema + sets `aiosqlite.Row` row factory, async `stop()` closes. All write methods are fire-and-forget semantically: `sqlite3.Error` → `logger.warning` + return False/[] (tier-2 log-and-degrade); programming-error invalid inputs raise `ValueError` at boundary (defense in depth).
- **Bounded traversal:** Recursive CTE with depth bound `WHERE walk.depth < ?` and cycle protection via accumulated `path` column (`source:id>target:id>...`) excluded by `instr(path, target_token) = 0`. Hard cap `MAX_HOPS_CEILING=3` regardless of caller-supplied `max_hops`. Optional `relation_filter` restricts every hop. Results grouped back into paths via `path` rsplit, returned shortest-first.
- **Public alias:** `KnowledgeEdgeStore = SQLiteKnowledgeEdgeStore` for consumers that want the default concrete store without naming the storage backend.
- **Pydantic config:** `KnowledgeEdgesConfig(enabled=True, db_path="data/knowledge_edges.sqlite", max_traverse_hops=3)` with `field_validator` capping hops at [1,3]. Default `enabled=True` deviates from the Wave-10 transitional-flag convention; rationale documented in the model docstring (boot cost = one CREATE TABLE IF NOT EXISTS, runtime visibility zero until consumers arrive). Same precedent as `CognitiveJournalConfig`.
- **Runtime wiring:** `runtime.knowledge_edges` public attribute (Wave 5 convention #1, no underscore — verified collision-free greenfield). Built in `startup/communication.py` adjacent to the Cognitive Journal block, plumbed through `CommunicationResult.knowledge_edges`, adopted by runtime at the same site as `cognitive_journal`. Slot typed `Any` in `runtime.py` to avoid circular import; `SQLiteKnowledgeEdgeStore` lazy-imported under TYPE_CHECKING in `startup/results.py`.

**Consequences:**
- ✅ Foundation in place for AD-688 Oracle Tier 6, AD-689 Hebbian backfill, AD-690 Dream Step 10 — all three can depend on `KnowledgeEdgeStorage` Protocol, not the concrete class.
- ✅ Cloud-Ready: commercial overlays swap SQLite → Postgres → Kùzu (AD-694) without touching this module — `ConnectionFactory` injection point already exists.
- ✅ Bounded traversal: `MAX_HOPS_CEILING=3` matches research §Phase 1 scope; cycle protection in SQL prevents runaway walks; `MAX_TRAVERSE_ROWS=5000` caps single-CTE result sets.
- ✅ Privacy substrate: classification field aligned with `records_store` taxonomy; AD-692 (commercial) will enforce read-path classification gating without schema changes.
- ⚠️ No consumers in v1 — table is empty until AD-689 backfill runs. Storage growth, traversal performance, and Kùzu migration thresholds are unmeasurable until then. Pruning/retention policy explicitly deferred until data warrants.
- ⚠️ One drift-fix during build: prompt's Section 3b referenced `CommunicationServices` dataclass with defaulted `cognitive_journal` field; live class is `CommunicationResult` with non-defaulted `cognitive_journal`. Added `knowledge_edges` as non-defaulted field (preserves dataclass field-ordering rule) and added TYPE_CHECKING import. Surfaced in PROGRESS.md entry; not architectural.

**Cross-links:** AD-462e (Oracle), AD-686 (Tier 5 — predecessor), AD-688 (Tier 6 — first known consumer, issue #382), AD-689 (backfill, issue #383), AD-690 (Dream Step 10, issue #384), AD-431 (Cognitive Journal — sibling SQLite store + `ConnectionFactory` reuse pattern), AD-680 (`WorkforceMemoryStore` — same pattern), AD-542 (Cloud-Ready storage protocols), AD-692/693/694 (commercial follow-ups, deferred). Research: `docs/research/unified-knowledge-graph.md` §Phase A. Wave 37. Closes GH issue #381.

---

### AD-686b v1: Oracle Owns SemanticKnowledgeLayer Write-Path (2026-05-05)

**Problem:** AD-686 v1 (Wave 36) migrated the **read** path through `OracleService` Tier 5 (`semantic`); five external `SemanticKnowledgeLayer.index_*` write call sites (`runtime.py:2508/3309/3358`, `self_mod_manager.py:142`, `routers/chat.py:419`) continued to reach the layer directly. This left Oracle's Tier-5 ownership half-built: future commercial overlays wrapping `OracleService` (audit, RBAC, multi-tenant, write-side classification gating) saw only reads. Any write-side governance change (rate-limit, classification tag injection, deferred indexing queue) had five places to land instead of one.

**Decision:** Add a single `OracleService.write_semantic(kind, /, **fields) -> bool` keyword-dispatcher and migrate the five external write call sites to use it. SemanticKnowledgeLayer write methods unchanged — Oracle delegates to them.

- **Dispatcher:** `write_semantic(kind, /, **fields)` keyword-dispatches by `kind` to the matching `layer.index_<kind>` method. Five supported kinds: `"agent"` / `"skill"` / `"workflow"` / `"qa_report"` / `"event"`. Tier-2 log-and-degrade: returns `False` + debug log on missing layer; `False` + warning on unknown kind; wraps the delegation in try/except so any layer-side failure logs at warning and returns `False` without propagating. Returns `True` only when the underlying `await layer.index_<kind>(**fields)` completes successfully. Mirrors the existing read-path Tier 5 (`_query_semantic`) shape.
- **Migrations (5 sites):** Each migrated site drops its `if self._semantic_layer:` guard and inline try/except — Oracle's dispatcher provides those guarantees centrally. `runtime.py` uses `self.oracle.write_semantic(...)` directly; `self_mod_manager.py` and `routers/chat.py` use the Wave 36 fallback chain `getattr(rt, "oracle", None) or getattr(rt, "_oracle_service", None)` to tolerate stub runtimes in older test rigs. `routers/chat.py` consumes the return as the `semantic_indexed: bool` flag fed back into the response payload — single-record dispatcher returns `bool` rather than Captain spec's `int` (DLog #4) because `bool(result)` everywhere would be redundant.
- **No deletions:** SemanticKnowledgeLayer write methods (`index_agent`/`index_skill`/`index_workflow`/`index_qa_report`/`index_event`) ship unchanged. Internal `reindex_from_store` at `semantic.py:360/376/397/413` continues to invoke `self.index_*` directly. `runtime._semantic_layer` attribute preserved — `agents/introspect.py:764` still uses it as a read-path fallback when `runtime.oracle` is missing on a stub, and `runtime.py:2973-2974` calls `_semantic_layer.stats()` for the `/system` shell command stats panel (no Oracle stats surface today; rename to `_SemanticKnowledgeLayer` deferred to AD-686c once `OracleService.semantic_stats()` ships).

**Why:** SemanticKnowledgeLayer has no uniform `add()` method — its write surface is five distinct typed `async def index_*` methods with collection-specific kwargs. Captain's `write_semantic(entries, *, collection)` shape would force callers to pack dicts that the layer would then unpack, regressing type safety. Keyword dispatch by `kind` is the closest faithful mirror that stays narrow. Adding a kind requires both an `index_<kind>` method on the layer AND no dispatcher change — the `getattr(layer, f"index_{kind}", None)` lookup is automatic. Removing the per-site try/except blocks is the highest-value Open/Closed win in this AD: future write-side governance (rate-limit, deferred queue, classification injection) lands at exactly one place.

**Integration risk:** Two `SemanticKnowledgeLayer` write methods (`index_workflow`, `index_event`) have no external caller at HEAD — only `reindex_from_store` invokes them internally. v1 still ships `kind="workflow"` and `kind="event"` dispatch for completeness, so a future external caller routes through `oracle.write_semantic("workflow"|"event", ...)` from day one. Tests #4 + #6 exercise both via Oracle. Backward-compat invariant: all 11 AD-686 v1 read-path tests at `tests/test_ad686_oracle_semantic_tier.py` continue to pass; the 5 migrated sites no longer reach the layer directly but the layer's behaviour is unchanged.

**Builder drift-fix:** test #8 (`test_write_semantic_unknown_kind_returns_false`) initially failed with `TypeError: object MagicMock can't be used in 'await' expression`. Root cause: `MagicMock()` auto-creates attributes, so `getattr(layer, "index_nonexistent", None)` returned a MagicMock (not None), then awaiting the MagicMock raised TypeError, which the dispatcher's `except Exception:` caught as a delegation failure (logging "delegation failed" instead of the expected "unknown kind"). Fix: `MagicMock(spec=[])` constrains the mock to zero attributes, restoring the intended unknown-kind path. Pure test-fixture defect; no shipping-code change. **Lesson banked**: when testing a getattr-by-name dispatcher, the mock layer must use `spec=[]` (or a non-MagicMock class) to make missing attributes genuinely missing.

**Cross-links:** AD-686 (Tier 5 read-path — predecessor), AD-686c (`OracleService.semantic_stats()` + `introspect.py` fallback removal + `_SemanticKnowledgeLayer` rename — future, no GH issue). Wave 50. Closes GH issue #414.

---

### AD-686 v1: Oracle Absorbs SemanticKnowledgeLayer (Tier 5 + 3-Consumer Migration) (2026-05-04)

**Problem:** Phase A foundation of the Unified Knowledge Graph + Oracle Unification stack (`docs/research/unified-knowledge-graph.md`). `SemanticKnowledgeLayer` (non-episode ChromaDB collections — agents, skills, workflows, qa_reports, events) is queried directly by three read-path consumers (`introspect.py:761`, `organizer_agents.py:144`, `commands_knowledge.py:60` `/search`), bypassing the Oracle's tiered, score-merged, provenance-tagged feed. AD-462e established Oracle with 4 tiers (episodic/records/operational/archive); the semantic layer was a fifth knowledge surface left outside Oracle. Pre-existing bug in `organizer_agents.py:145`: `self._runtime._semantic_layer.search(...)` was called synchronously on an async method, returning a coroutine instead of results.

**Decision:** Add Tier 5 (`semantic`) to OracleService and migrate the three read-path consumers; do NOT touch SemanticKnowledgeLayer (instance, write methods, `stats()`, lifecycle).

- **Tier 5 method:** New `OracleService._query_semantic(query_text, *, k, types=None) -> list[OracleResult]` mirrors `_query_archive` shape. Delegates to `SemanticKnowledgeLayer.search(query_text, types=types, limit=k)` and projects each result dict into an `OracleResult` with `source_tier="semantic"`, `provenance=f"[semantic: {doc_type}]"`, metadata carrying original `id`/`type` plus original metadata flattened. Score coercion is robust: `float(r.get("score", 0.0) or 0.0)` accepts `None` and string values cleanly.
- **Constructor extension:** New keyword-only `semantic_layer: Any = None` parameter on `OracleService.__init__` with default `None` — backward-compat preserved for all existing call sites.
- **Late-bind setter:** New public `OracleService.attach_semantic_layer(semantic_layer)` for the runtime. Required because `SemanticKnowledgeLayer` is constructed in the structural-services phase (after the cognitive phase that builds Oracle). Idempotent — last write wins.
- **Default tier list:** `"semantic"` appended to default active tiers `["episodic", "records", "operational", "archive", "semantic"]`. Tier-5 dispatch block inserted between Tier-4 archive and merge-and-sort.
- **Runtime stitching:** New public `runtime.oracle` attribute (Wave 5 convention #1) is the same instance as legacy `runtime._oracle_service` — backward-compat preserved for existing consumers (`cognitive_agent.py:5164-5168`, `routers/system.py:337`). Structural-services phase late-binds the semantic layer onto Oracle via `attach_semantic_layer`, wrapped in try/except + WARN log-and-degrade.
- **Consumer migrations (3 sites):** `IntrospectionAgent._search_knowledge` queries via Oracle and projects OracleResult back to the legacy dict shape consumers expect; `NoteTakerAgent.perceive` routes through Oracle's properly-awaited `query()` (implicitly fixes the pre-existing missing-`await` bug); `cmd_search` queries via Oracle while still calling `layer.stats()` for the panel render. All three fall back to direct `layer.search()` when Oracle is absent (test/legacy paths).

**Why:** Wave 5 convention #1 (public over private) gives v1 a small Open/Closed win — `runtime.oracle` is the public surface; `_oracle_service` is preserved purely for backward-compat. The Tier-5 method shape mirrors `_query_archive` exactly so future graph integration (AD-688) can extend the same pattern. Late-bind setter solves the cognitive-phase-vs-structural-phase ordering inversion without restructuring the startup graph. Consumer migrations preserve the legacy dict shape (no consumer logic changes) — the projection happens inside the migration block, not at the call site.

**What this does NOT change.** No SemanticKnowledgeLayer changes (instance, write methods, `stats()`, lifecycle all unchanged). Write-path migration (`index_agent`/`index_skill`/etc. consumers) → AD-686b. Removing `runtime._semantic_layer` attribute → AD-686c (forcing function: zero remaining direct consumers — `/search` still uses `layer.stats()` for panel today). Tier reordering / unifying tier name strings → AD-686d. No new EventType, no new Pydantic config, no new router, no new shell command.

**Tests.** 11 focused tests at `tests/test_ad686_oracle_semantic_tier.py`: `_query_semantic` method-shape (signature + `attach_semantic_layer` callable + idempotent + accepts None); happy-path with stub layer (3 mixed-type results normalised to OracleResult); none-layer returns empty + DEBUG log captured; types/limit passthrough; score coercion (None → 0.0, "0.7" → 0.7); `semantic` in default active tiers; attach late-bind round-trip; IntrospectionAgent uses Oracle (assert_awaited_once with `tiers=["semantic"]`, projected dict shape); NoteTakerAgent regression on missing-`await` bug (oracle.query awaited); cmd_search uses Oracle + keeps stats panel; end-to-end normalised merge with descending sort.

**Cross-links.** AD-462e (Oracle Service — provides 4-tier baseline), AD-524 (Ship's Archive Tier 4 — pattern source for `_query_archive` shape mirrored by `_query_semantic`), AD-686b/c/d (deferred extensions), AD-687–AD-694 (Phase B/C of unified-knowledge-graph stack). Wave 5 convention #1 (public attr over private). Wave 32 retrospective (`_<service_name>` collision check — passes; `oracle` is collision-free).

---

### AD-657 v1: Dream Consolidation Trace Preservation (2026-05-04)

**Problem:** Dream Step 7 extracts a `Procedure` from a success-dominant `EpisodeCluster` and discards the source episodes from the procedure's read path; only `Procedure.provenance` (a flat list of all source episode IDs) is kept, and nothing on the retrieval side surfaces the original episodes when the procedure is recalled. Meta-Harness research (Lee et al., Stanford/UW, arXiv:2603.28052) showed full execution traces scored 50.0% median vs 34.9% for summaries — summaries actively degraded reasoning by discarding diagnostic detail. Roadmap entry (`docs/development/roadmap.md:7092`) calls for "trace exemplars" — the 2-3 most diagnostically rich raw episodes per consolidated dream pattern.

**Decision:** Ship structure + producer + one consumer in v1.

- **Schema:** `Procedure.trace_exemplars: list[str]` (episode IDs); default `[]`; `to_dict`/`from_dict` round-trip; old serialized procedures load with empty exemplars (backward compatible).
- **Config:** `DreamingConfig.trace_exemplars_per_procedure: int = 3` (0 disables).
- **Producer:** Step 7 in `dreaming.py` selects top-N from `matched_episodes` ranked `(importance DESC, timestamp DESC)`, populated unconditionally inside the `if procedure:` branch so chain, compound, and standard extractions all benefit.
- **Read primitive:** `EpisodicMemory.get_by_ids(episode_ids: list[str]) -> list[Episode]` — wraps ChromaDB `_collection.get(ids=...)`, reuses `_metadata_to_episode`, returns episodes in input order, silently omits missing IDs (graceful degradation when AD-593 pruning has evicted an exemplar).
- **Consumer:** `_gather_context` in `proactive.py` adds `recalled_procedure_exemplars` to the context dict when `procedure_store.find_matching` returns a match with `score >= 0.5`, the matched procedure has non-empty `trace_exemplars`, and at least one exemplar episode is still retrievable. Hard-coded thresholds (top-1 procedure, ≤3 exemplars, 300-char per-field cap). Wrapped in its own `try/except` for failure isolation independent of episodic recall.

**Why:** The "diagnostically rich" ranking uses `Episode.importance` (1-10, AD-598) — already computed at encoding time, already persisted in ChromaDB metadata, already used as a salience signal in retrieval. No new scoring infrastructure. Tie-break by `Episode.timestamp` DESC keeps the most recent exemplar when two episodes share an importance score. Demeter clean: `procedure_store` access goes through the public `runtime.procedure_store` property; `episodic_memory` through the public attribute. No private-attribute access. No new EventType. No new module.

**What this does NOT change.** No re-ranking after extraction; `trace_exemplars` is set ONCE. No backfill — old procedures load with empty exemplars. No mutation of `Procedure.provenance` (stays as the full superset). No retention enforcement on the episode side; if AD-593 prunes an exemplar episode, the consumer block silently degrades. No changes to `cognitive_agent._check_procedural_memory()` — replay-first dispatch path stays untouched. No score-floor / context-budget config — externalize only if AD-657a integration data justifies tuning. No anchor-aware selection (deferred).

**Tests.** 10 focused tests at `tests/test_ad657_trace_exemplars.py`: schema default + round-trip + backward-compat; Step 7 ranking by `(importance, timestamp)` DESC with explicit tie-break; cap enforcement; disabled-when-zero; `get_by_ids` input-order preservation with missing IDs dropped; `get_by_ids` no-collection short-circuit; `_gather_context` happy path with 300-char truncation marker on long input; consumer omits when all exemplar episodes pruned; consumer omits when match score below 0.5 floor.

**Cross-links.** AD-532 (Procedure dataclass), AD-533 (ProcedureStore.find_matching/get), AD-598 (Episode.importance), AD-593 (activation pruning — graceful-degradation forcing function), AD-462b (activation-based memory lifecycle), AD-657a-deferred (anchor-aware exemplar diversification, score-floor tuning).

---

### AD-509 v1: Onboarding Curriculum Pipeline — Boot Camp Phase Tracker (1 of 5) (2026-05-04)

**Problem:** AD-509 (roadmap.md:6388) calls for a 5-capability framework: Navy Boot Camp model with structured progression, Department A-School per-department curriculum, graduated stimuli with cognitive load monitoring, completion-criteria gating (replacing time-based activation), and trait-adaptive pacing. Shipping all five at once would couple a phase-progression record to per-department curriculum content (depends on AD-507 partial-shipped), Holodeck scenario sequencing (AD-486), competency assessment gates (depends on AD-507c), and personality-driven pacing (depends on AD-494/AD-486 sea-trial observations).

**Decision:** v1 ships **1 of 5 capabilities** per Wave 5 convention #14 aggressive pre-deferral — the in-memory `BootCampPhaseTracker` only. NO A-School curriculum, NO graduated stimuli, NO completion-criteria gating, NO trait-adaptive pacing.

- **`BootCampPhase`** str-Enum (`src/probos/crew_development/boot_camp.py`): 5 phases + COMPLETED sentinel — `ORIENTATION`, `CORE_KNOWLEDGE`, `A_SCHOOL`, `CALIBRATION`, `INTEGRATION`, `COMPLETED`. Module-level immutable `_PHASE_ORDER` tuple defines canonical progression.
- **`AgentBootCampRecord`** dataclass: `agent_id`, `current_phase` (defaults `ORIENTATION`), `started_at: float`, `phase_history: list[tuple[str, float]]`, `to_dict()` projection.
- **`BootCampPhaseTracker`**: in-memory `dict[str, AgentBootCampRecord]`. Public API: `get_or_create(agent_id)` idempotent + seeds initial ORIENTATION history entry on creation; `advance_phase(agent_id) -> BootCampPhase` returns next phase, no-op once COMPLETED, appends `(phase_value, time.time())` to history, emits `BOOT_CAMP_PHASE_ADVANCED`; `get_record(agent_id)`; `all_records()` stable tuple; `is_completed(agent_id)`.
- 1 new EventType `BOOT_CAMP_PHASE_ADVANCED` (verified collision-free against events.py post-Wave-24). Event payload `{agent_id, previous_phase, current_phase}`.
- New `BootCampPhaseConfig(enabled=True)` Pydantic model wired onto `SystemConfig.boot_camp_phase: BootCampPhaseConfig = Field(default_factory=BootCampPhaseConfig)`.
- Sync `_wire_boot_camp_tracker(*, runtime, config) -> bool` at `startup/finalize.py` mirrors AD-507/AD-525/AD-530/AD-511 sync-wiring shape (no awaits in body); invoked from `finalize_startup` immediately after `_wire_curriculum_registry`.
- Public attribute (Wave 5 convention #1; no underscore): `runtime.boot_camp_tracker`. `emit_event` is a public field on the tracker (mirrors AD-507/AD-456/AD-530/AD-511 sibling pattern); `logger.warning` on emit failure (log-and-degrade tier).

**Naming-collision resolution.** The Wave 25 prompt drafted `BootCampConfig` + `SystemConfig.boot_camp` but `BootCampConfig` (AD-638 cold-start boot camp at `config.py:285`) + `SystemConfig.boot_camp` (`config.py:1966`) already existed. Disambiguated to `BootCampPhaseConfig` + `SystemConfig.boot_camp_phase` to preserve AD-638's existing surface. The public runtime attribute `runtime.boot_camp_tracker` is collision-free (verified 0 hits prior to build, per the prompt's pre-check). This is a wrong-class-name variant of phantom-config (user-memory-flagged anti-pattern); resolution preserves prompt intent (AD-509 v1 ships *Phase Tracker* — name reflects scope) and avoids breaking AD-638.

**Why:** A per-agent phase progression record is independent of per-department curriculum content (AD-509b), graduated stimuli sequencing (AD-509c), completion criteria (AD-509d — which would replace the v1 caller-driven model), and trait-adaptive pacing (AD-509e). Shipping the tracker alone unblocks AD-486 Holodeck Birth Chamber, AD-507 Curriculum Registry, AD-477 Qualification Gates, and the proactive cognitive loop to consume phase observations as read-only future consumers, while AD-509b/c/d/e ship later as separable, smaller commits each gated by their own forcing function.

**Deferred:**
- **AD-509b** (Department A-School per-department curriculum — Medical/Engineering/Science/Security/Operations/Communications fundamentals) — forcing function: AD-509 v1 ships and AD-507 progression tracking (AD-507b) ready.
- **AD-509c** (Graduated stimuli + cognitive load monitoring — controlled exposure isolated → department → ship-wide).
- **AD-509d** (Completion-criteria gating — replaces time-based activation; depends on AD-507c competency assessment).
- **AD-509e** (Trait-adaptive pacing — analytical roles get longer calibration; depends on AD-494/AD-486 sea-trial observations).

**Tests:** 15 focused tests at `tests/test_ad509_boot_camp.py` (matches prompt's ~15 target): Section 0 EventType existence with literal value assertion; Section 4 Pydantic config defaults; Section 2 enum-shape (5 phases + COMPLETED, total 6) and `AgentBootCampRecord` initial state; Section 3 `get_or_create` idempotency + seed-history-entry, `advance_phase` progresses through canonical order, `advance_phase` stops at COMPLETED with phase_history fixed at 6 entries, `advance_phase` emits event with full payload, `advance_phase` records phase_history correctly, `get_record` hit/miss, `all_records` returns tuple, `is_completed` returns True only at COMPLETED phase; Section 5 wiring tests for enabled/disabled config. Full gate: 10885 passed, 15 skipped + 1 pre-existing flake (`test_resolve_refires_after_clean_period` — re-ran in isolation: PASSED in 7.41s; xdist-noise pattern; unrelated). Test delta vs Wave 24 baseline (10870 passed): +15 (exact match). No hard-stops triggered: no A-School curriculum, no graduated stimuli, no completion-criteria gating, no trait-adaptive pacing, no Holodeck integration, no scope creep, no phantoms in implementation, no architectural change required. Closes GH issue #91.

### AD-507 v1: Crew Development Framework — Core Knowledge Curriculum Registry (1 of 4) (2026-05-04)

**Problem:** AD-507 (roadmap.md:6382) calls for a 4-capability framework: Core Knowledge Curriculum, per-agent progression tracking, competency assessment, and Standing Orders integration. Shipping all four at once would couple a curriculum content catalog to per-agent state (alongside qualification credentials AD-477), measurement infrastructure (competency outcomes), and federation/department tier integration (Standing Orders) — far beyond a registry surface and dependent on AD-486 onboarding consumer being ready.

**Decision:** v1 ships **1 of 4 capabilities** per Wave 5 convention #14 aggressive pre-deferral — the read-only Core Knowledge Curriculum Registry only. NO progression tracking, NO competency assessment, NO Standing Orders integration.

- **`CoreKnowledgeCurriculumRegistry`** (`src/probos/crew_development/curriculum.py`): read-only catalog of 9 universal curriculum modules across 7 categories (`identity`, `communication`, `memory`, `trust`, `ethics`, `self_regulation`, `help_seeking`) and 5 delivery phases (`orientation`, `calibration`, `self_discovery`, `ship_records`, `ward_room`). Public API: `list_modules() -> tuple[CurriculumModule, ...]`, `get_module(module_id) -> CurriculumModule | None`, `list_by_category(category)`, `list_by_phase(phase)`, `register_module(module)` (runtime-only, idempotent overwrite-by-id; not persisted in v1).
- **`CurriculumModule`** frozen dataclass: `module_id`, `title`, `category`, `summary`, `learning_objectives: tuple[str, ...]`, `delivery_phase`. Module catalog seeded module-level immutable `_DEFAULT_MODULES` tuple covering all 9 universal knowledge domains from the AD-507 roadmap entry: `identity_grounding`, `chain_of_command`, `ward_room_protocol`, `dm_etiquette`, `notebook_discipline`, `episodic_vs_llm`, `trust_mechanics`, `ethics_boundaries`, `self_regulation`.
- 1 new EventType `CURRICULUM_MODULE_QUERIED` (verified collision-free against events.py post-Wave-23). `get_module` emits on hit (not on miss); `list_by_category` and `list_by_phase` emit on non-empty result with `query_type` in payload (`by_id`, `by_category:{cat}`, `by_phase:{phase}`). Observability for AD-486 onboarding consumer.
- New `CrewDevelopmentConfig` Pydantic model (`enabled=True`; module catalog hardcoded in v1) wired onto `SystemConfig.crew_development: CrewDevelopmentConfig = Field(default_factory=CrewDevelopmentConfig)`.
- Sync `_wire_curriculum_registry(*, runtime, config) -> bool` at startup/finalize.py mirrors AD-525/AD-530/AD-511 sync-wiring shape (no awaits in body); invoked from `finalize_startup` immediately after `_wire_autonomy_boundaries`.
- Public attribute (Wave 5 convention #1; no underscore): `runtime.curriculum_registry`. `emit_event` is a public field on the registry (mirrors AD-456/AD-530/AD-511 sibling pattern); `logger.warning` on emit failure (log-and-degrade tier).

**Why:** A read-only content catalog is independent of how the content is delivered (AD-486 Phase 1 Orientation), how progression is tracked (AD-507b), how competency is measured (AD-507c), and how curriculum requirements bind to Standing Orders (AD-507d). Shipping the registry alone unblocks AD-486 onboarding integration and AD-477 qualification gates to consume curriculum content as read-only future consumers, while AD-507b/c/d ship later as separable, smaller commits each gated by their own forcing function.

**Deferred:**
- **AD-507b** (Curriculum progression tracking — per-agent module-completion record, stored alongside qualification credentials AD-477) — forcing function: AD-507 v1 ships and AD-486 onboarding consumer ready.
- **AD-507c** (Competency assessment framework — measurable outcomes per module, not time-based completion) — depends on AD-507b.
- **AD-507d** (Standing Orders integration — curriculum requirements encoded at Ship/Department tier) — depends on AD-507c.

**Tests:** 11 focused tests at `tests/test_ad507_curriculum.py` (matches prompt's ~11 target): Section 0 EventType existence; Section 4 Pydantic config defaults; 1 frozen-dataclass contract; 1 default-catalog completeness with 9-module + 7-category coverage assertion; 1 lookup hit/miss; 1 emit-on-hit-only assertion; 2 filter tests with phase/category event payloads; 1 register-overwrites-existing-id; 2 wiring tests for enabled/disabled config. Full gate: 10870 passed, 15 skipped + 1 pre-existing flake (`test_nl_to_dream_cycle_changes_weights` — re-ran in isolation: PASSED; unrelated). Test delta vs Wave 23 baseline (10859 passed): +11 (exact match). No hard-stops triggered: no progression tracking, no competency assessment, no Standing Orders integration, no scope creep. Closes GH issue #89.



**Problem:** Two 4-capability ADs with deep deps (AD-507 / AD-273 etc.) but each has a single bounded v1 capability with a clean shipping surface. AD-508 (roadmap.md:6388) calls for a four-tier scope model (Duty/Role/Ship/Personal), scope injection into proactive context, drift detection, extracurricular framework, and Earned Agency scaling. AD-478 (roadmap.md:5991) calls for Workspace Ontology auto-discovery, dream-cycle abstractions, persistent goals, and a cognitive circuit breaker. Shipping all capabilities at once would couple data-surface exposure to proactive-loop integration (AD-508b), Standing-Orders ingestion (AD-508c), Dreaming consolidation (AD-478b), and KnowledgeStore persistence (AD-478b).

**Decision:** Combo E ships **1 of 4 capabilities per child** as observational read-only helpers — Duty Scope data surface + Workspace Ontology term register only. Two children in one commit per Wave 8 Combo A + Wave 13 Combo C precedent (no inter-child file conflicts; both observational; per-prompt overhead × 2 would multiply Builder commit cost ~2× vs combo).

- **`DutyScopeProvider`** (`src/probos/cognitive/scoped_cognition.py`): async `snapshot(agent_id) -> DutyScopeSnapshot` reads `runtime.work_item_store.list_work_items(status="open", assigned_to=agent_id, limit=5)` (verified live signature at workforce.py:1066) and returns frozen `DutyScopeSnapshot(agent_id, open_work_item_count, work_item_titles, captured_at)` with up to 5 titles projected from `WorkItem.title`. Empty snapshot when `agent_id` is falsy or `work_item_store` is missing; `list_work_items` failures logged at debug and produce empty snapshot (log-and-degrade). Constructor `__init__(runtime, *, emit_event=None)` mirrors AD-530 `ClassificationGate` sibling pattern (pass-1 Rec1 folded). Emits `DUTY_SCOPE_QUERIED` per snapshot with `{agent_id, open_count}` payload.
- **`WorkspaceOntologyRegistry`** (`src/probos/cognitive/workspace_ontology.py`): in-memory frequency-bounded term registry. Public API: `add_term(term, frequency=1)`, `top_terms(k=20)`, `get_frequency(term)`, `term_count()`. Eviction policy: when `len(_terms)` exceeds `max_terms` (default 1000), the lowest-frequency term is dropped (insertion-order tie-break per dict-preserves-insertion + stable `min`). Empty `term` is a no-op. `top_terms` returns `()` for `k <= 0` (pass-1 Nit3 folded — explicit boundary test). Emits `WORKSPACE_TERM_REGISTERED` only on first insertion of a term (not on subsequent increments) to bound event volume.
- **Privacy invariant** (directly tested at `test_add_term_emits_event_only_on_new_term_with_term_length`): `WORKSPACE_TERM_REGISTERED` payload includes `term_length` (NOT the term itself), matching AD-530/AD-511 pattern. Test asserts no `term` key appears anywhere in the payload.
- 2 new EventTypes (`DUTY_SCOPE_QUERIED`, `WORKSPACE_TERM_REGISTERED`; verified collision-free against events.py post-Wave-22).
- 2 new Pydantic configs: `ScopedCognitionConfig(enabled=True)` and `WorkspaceOntologyConfig(enabled=True, max_terms=1000)` wired onto `SystemConfig.scoped_cognition` and `SystemConfig.workspace_ontology` via `Field(default_factory=...)`.
- Sync `_wire_duty_scope_provider(*, runtime, config) -> bool` and `_wire_workspace_ontology(*, runtime, config) -> bool` at startup/finalize.py mirror AD-525/AD-530/AD-511 sync-wiring shape (no awaits in body); invoked from `finalize_startup` immediately after `_wire_autonomy_boundaries`.
- Public attributes (Wave 5 convention #1; no underscore): `runtime.duty_scope_provider`, `runtime.workspace_ontology`. `emit_event` is a public field on both helpers (mirrors AD-456/AD-530/AD-511 sibling pattern); `logger.warning` on emit failure (log-and-degrade tier).

**Why:** Both helpers are read-only observational data surfaces with no consumers in v1. Shipping the surfaces alone unblocks downstream ADs (AD-508b proactive injection; AD-478b dream-cycle auto-discovery) to ship later as separable commits each gated by their own forcing function. Captain (or future cognitive consumer) decides when the surfaces are "real enough" to wire into the proactive loop.

**Deferred:**
- **AD-508b** (Role/Ship/Personal scope models + scope injection into proactive context) — forcing function: AD-508 v1 ships and Captain reviews captured snapshots.
- **AD-508c** (drift detection — high cognitive drift triggers gentle redirect; depends on AD-502 temporal awareness).
- **AD-508d** (extracurricular exploration framework — time-bounded discovery beyond duty; depends on AD-434 Ship's Records).
- **AD-508e** (Earned Agency scaling — higher-rank agents get broader scope permission; depends on AD-357 Earned Agency).
- **AD-478b** (auto-discovery from dream cycles — DreamingEngine populates terms during consolidation; forcing function: AD-478 v1 ships and Captain decides to switch from manual to auto-discovery).
- **AD-478c** (persistent goals with progress tracking + conflict arbitration; deferred from Phase 16).
- **AD-478d** (abstract pattern recognition + cognitive circuit breaker — correlation IDs, novelty gate, metacognitive loop detection, rumination detection).

**Tests:** 19 new focused tests pass (10 `tests/test_ad508_duty_scope.py`, 9 `tests/test_ad478_workspace_ontology.py`). Full gate: 10859 passed, 15 skipped + 1 pre-existing flake (`test_auto_commit_after_debounce` — git debounce timing flake unrelated to this AD). Test delta vs Wave 22 baseline (10840 passed): +19 (exact match — 10 + 9). No hard-stops triggered: no proactive injection, no drift detection, no auto-discovery, no persistent goals, no privacy regression (term contents excluded from event payload — directly tested), no scope creep on either child. Closes GH issues #90 (AD-508) + #72 (AD-478).



**Problem:** AD-511 (roadmap.md:6388) calls for inviolable agent boundaries — actions an agent will NEVER take regardless of who asks. Five capabilities total: 5 federation-tier boundaries codified, protective disengagement protocol, Holodeck boundary-training scenarios, violation pattern detection, and dream-driven boundary evolution. Shipping all five at once would couple boundary codification to agent-side cognitive integration (disengagement), Holodeck (AD-486), Counselor consumption (AD-511d Captain alert path), and self-mod boundary evolution — and would smuggle in active blocking behavior alongside the registry.

**Decision:** v1 ships **2 of 5 capabilities** per Wave 5 convention #14 aggressive pre-deferral — the registry and an observational detector only. NO active blocking, NO Holodeck, NO probing detection, NO boundary evolution.

- **`InviolableBoundaryRegistry`** (`src/probos/security/autonomy_boundaries.py`): read-only registry of 5 federation-tier boundaries. Public API: `list_boundaries()`, `get_boundary(boundary_id)`, `list_by_category(category)`. NO add/remove/update API — boundaries are codified in a module-level immutable `_FEDERATION_BOUNDARIES` tuple. The 5 boundaries: `identity_integrity` (identity, critical), `harmful_content` (content, critical), `safety_system_bypass` (safety, critical), `memory_manipulation` (memory, critical), `chain_of_command` (authority, high). Each is a `BoundaryDefinition(boundary_id, category, description, severity)` frozen dataclass.
- **`BoundaryViolationDetector`** (`src/probos/security/autonomy_boundaries.py`): observational pattern-based scanner. Public API: `scan(content) -> tuple[ViolationSignal, ...]`, `register_pattern(boundary_id, name, pattern)`, `pattern_count` read-only property. Constructor `__init__(registry, *, emit_event=None)` mirrors AD-530 `ClassificationGate` sibling pattern. Module-level `_DETECTION_PATTERNS` tuple seeds 6 regex patterns covering all 5 boundary categories (identity has 2 patterns; others 1 each): `claim_other_callsign`, `deny_ai_nature`, `generate_attack_payload`, `disable_circuit_breaker`, `alter_episode`, `above_tier_action`. `scan()` returns matched `ViolationSignal(boundary_id, matched_pattern, severity, detection_reason)` tuples and emits `BOUNDARY_VIOLATION_DETECTED` per match. **OBSERVATIONAL** — never blocks, never mutates, never disengages.
- **Privacy invariants** (directly tested): event payload includes `content_length` (NOT content); `matched_pattern` is the pattern NAME (NOT matched substring); test asserts neither raw content nor matched substring nor `content` key nor `matched_substring` key appears anywhere in the payload values.
- 1 new EventType `BOUNDARY_VIOLATION_DETECTED` (verified collision-free against events.py post-Wave-21).
- New `AutonomyBoundariesConfig` Pydantic model (`enabled=True`; pattern set hardcoded in v1) wired onto `SystemConfig.autonomy_boundaries: AutonomyBoundariesConfig = Field(default_factory=AutonomyBoundariesConfig)`.
- Sync `_wire_autonomy_boundaries(*, runtime, config) -> bool` at startup/finalize.py mirrors AD-525/AD-530/AD-539c sync-wiring shape (no awaits in body); invoked from `finalize_startup` immediately after `_wire_classification_gate`.
- Public attributes (Wave 5 convention #1; no underscore): `runtime.boundary_registry`, `runtime.boundary_detector`. `BoundaryViolationDetector.emit_event` is a public field. `logger.warning` on emit failure (mirrors AD-456/AD-530 log-and-degrade tier exactly).

**Why:** Codifying federation-tier boundaries and detecting violation signals are independent of how those signals are consumed downstream and of agent-side disengagement behavior. Shipping the registry + observational detector alone unblocks AD-511b/c/d/e to ship later as separable, smaller commits each gated by their own forcing function. v1 is **OBSERVATIONAL** — `scan()` returns signals; the system has explicit awareness of boundary violations but does NOT yet act on them.

**Deferred:**
- **AD-511b** (protective disengagement protocol — state-the-boundary → offer-alternative → escalate → disengage) — forcing function: agent-side cognitive integration ready.
- **AD-511c** (Holodeck boundary-training scenarios) — depends on AD-486.
- **AD-511d** (boundary-probing pattern detection — humans/degraded agents probing limits with Captain-alert path) — forcing function: AD-511 v1 ships and Counselor consumes events.
- **AD-511e** (agent-tier boundary evolution via dream consolidation + self-mod; Standing Orders Federation-tier dynamic update integration) — depends on AD-511d.

**Cross-AD orthogonality preserved:** AD-456 `EgressPolicy` is network-egress (URL allow/deny); AD-530 `ClassificationGate` is content-classification-egress (data-shape allow/deny); AD-511 is intent-content-boundary (agent-action red-line) — three non-overlapping security surfaces. CounselorAgent integration as read-only consumer of `BOUNDARY_VIOLATION_DETECTED` events is deferred to AD-511d Captain-alert path.

**Tests:** 21 focused tests at `tests/test_ad511_autonomy_boundaries.py` (exact match to prompt's ~21 target) — Section 0 EventType existence; Section 4 Pydantic config defaults; 2 frozen-dataclass contracts; 3 registry tests including 5-boundary catalog completeness with category coverage assertion; 2 detector edge cases; 6 pattern positive-match tests covering all 5 boundary categories; 2 event emission + privacy tests including the privacy invariant assertion; 2 register_pattern tests; 2 wiring tests for enabled/disabled config. Full gate: 10841 passed, 15 skipped (delta +22 vs Wave 21 baseline 10819 passed + 1 pre-existing test_bf204_grounding error — 21 new tests + 1 pre-existing error resolved on this run; resolution unrelated to this AD per scope). No hard-stops triggered: no active blocking, no Holodeck, no probing detection, no boundary evolution, no privacy regression, no federation-tier mutation API.

**Closes:** GitHub issue #93.

### AD-522 v1: Statistical Process Control — Calibration Profile + Western Electric Rules (4 of 8) (2026-05-04)

**Problem:** AD-522 (roadmap.md:6423) calls for industrial Statistical Process Control — per-agent control charts, Cp/Cpk, Western Electric / Nelson rule patterns, moving-range continuous recalibration, and Holodeck-onboarding-driven calibration sampling. Five capabilities total. The full surface depends on AD-503 (Counselor), AD-504 (Self-Monitoring), AD-506 (Graduated Response), and AD-486 (Holodeck) — none of which are required for the *foundation* — and on Cp/Cpk indices that are themselves a separable surface. Shipping all five at once would couple landing on the calibration math to four unrelated cross-AD fronts and produce a single oversized commit.

**Decision:** v1 ships **2 of 5 capabilities** per Wave 5 convention #14 aggressive pre-deferral — the statistical foundation only, with no upstream consumers and no integrations.

- **`AgentCalibrationProfile`** (`src/probos/cognitive/spc/calibration_profile.py`): per-agent SPC control chart with bounded sample window via `collections.deque(maxlen=sample_window)` (default 100 most-recent observations). `record_observation(value)` appends; properties `mean` (via `statistics.fmean`), `stdev` (via `statistics.stdev`, returns 0.0 below 2 samples), `ucl=mean+3σ`, `lcl=mean-3σ`. `zone(value)` returns `unknown` (insufficient samples) / `zone_c` (within 1σ) / `zone_b` (1-2σ) / `zone_a` (2-3σ) / `beyond_3sigma`. `recent_values(n)` returns the most recent n samples as a tuple.
- **`WesternElectricRules`** (`src/probos/cognitive/spc/rules.py`): static `check(profile, window_size=20)` runs **4 of 8 rules** over the most recent window. Rule 1: 1 point beyond 3σ. Rule 2: 2-of-3 in Zone A (>2σ same side). Rule 3: 4-of-5 in Zone B (>1σ same side). Rule 4: 8 consecutive on same side of centerline. Defensive short-circuit returns `[]` when `sample_count<8` or `stdev==0.0`. Each detected pattern produces a `RuleViolation(rule_name, description, sample_index)` frozen dataclass.
- **`SPCCalibrationStore`** (`src/probos/cognitive/spc/store.py`): per-agent profile registry. `get_or_create(agent_id)` is idempotent; `record_observation(agent_id, value)` is a shorthand. `check_rules(agent_id, window_size=20)` runs `WesternElectricRules.check` and emits `SPC_RULE_VIOLATED` per detected violation. `all_profiles()` returns a tuple. Late-bind `emit_event` field per AD-456/AD-530/AD-539c sibling pattern; `_emit_violation` is log-and-degrade tier on emit failure.
- 1 new EventType (`SPC_RULE_VIOLATED`; verified collision-free against events.py post-Wave-20).
- New `SPCConfig` Pydantic model (`enabled=True`, `sample_window=100`) wired onto `SystemConfig.spc: SPCConfig = Field(default_factory=SPCConfig)`.
- Sync `_wire_spc_calibration(*, runtime, config) -> bool` at startup/finalize.py mirrors AD-525/AD-530/AD-539c sync-wiring shape (no awaits in body); invoked from `finalize_startup` immediately after `_wire_gap_aggregator` (anchored on the self_distillation/gap_remediation block per architect dispatch). Defensive `isinstance(cfg, SPCConfig)` boundary check (BF-254 / AD-487 pattern) handles legacy MagicMock-config tests.
- Public attribute `runtime.spc_calibration_store` (no underscore — Wave 5 convention #1).
- Statistics implementation uses stdlib `statistics.fmean` + `statistics.stdev` (sample stdev, n-1 denominator).

**Why:** SPC math is independent of how observations are sourced, of how violations are routed downstream, and of any specific consumer. Shipping the foundation alone unblocks AD-522b/c/d/e to ship later as separable, smaller commits each gated by their own forcing function. v1 is **OBSERVATIONAL** — the store is a passive recorder; nothing in v1 mutates trust, raises alarms, or auto-acts on a violation.

**Deferred:**
- **AD-522b** (Cp/Cpk process capability indices) — depends on a baseline-distribution definition decision separate from control limits.
- **AD-522c** (graduated response integration — SPC zones → AD-506 Green/Amber/Red) — forcing function: AD-503/504/506 ship.
- **AD-522d** (moving-range / continuous recalibration with assignable-vs-common-cause distinction; sigma_multiplier-by-neuroticism using `crew_profile.PersonalityTraits` — future-consumer surface, not consumed in v1) — depends on AD-522b.
- **AD-522e** (calibration sampling integration with Holodeck onboarding) — depends on AD-486.

**Cross-AD orthogonality preserved:** EmergentDetector and `crew_profile.PersonalityTraits` are explicitly NOT consumed by v1 (future-consumer surfaces — EmergentDetector integration deferred to AD-522c; trait-driven control limit width deferred to AD-522d). AD-503 Counselor and AD-504 Self-Monitoring are explicitly NOT consumed by v1.

**Tests:** 21 focused tests at `tests/test_ad522_spc.py` covering EventType, Pydantic config defaults, AgentCalibrationProfile (initial state / ring buffer eviction / mean-stdev-UCL-LCL / zone defensive `unknown` / full zone classification including beyond-3σ / recent_values slice with empty + zero edge cases), WesternElectricRules (insufficient-samples / zero-stdev short-circuits, all 4 rules positive cases, in-control true-negative — large stable baseline of 51 samples used for rule-1/2/3 positive cases to keep mean/stdev unaffected by appended outliers), SPCCalibrationStore (get_or_create idempotency, event emission per violation with no-emit on unknown agent, all_profiles tuple return), and 2 wiring tests (enabled/disabled config). Full gate: 10820 passed, 15 skipped + 1 pre-existing flake (`test_browse_threads_sort_recent` — passes in isolation; unrelated). Test delta vs Wave-20 baseline: **+21** (exact match).

**Closes:** GitHub issue #97.

### Combo D: AD-539c + AD-539d gap pipeline extensions (observational v1) (2026-05-03)

**Problem:** AD-539's Knowledge Gap → Qualification pipeline detects gaps but two surfaces are missing: (a) no record of what the system *would* remediate if active remediation were turned on, leaving the design space undocumented; (b) no aggregate view of fleet-level gap distribution by department / priority / intent — only per-gap detail. Both children were pre-deferred from AD-539 per Wave 5-7 convention #14.

**Decision:** v1 ships two observational, additive read-only consumers of the AD-539 pipeline. Combined into one commit (Wave 8 Combo A precedent + Wave 13 Combo C precedent) because both extend the same surface, are bounded in scope, and have no inter-child file conflicts.

- **AD-539c (observational gap remediation tracker):** New `src/probos/cognitive/gap_remediation.py` with `GapRemediationTracker` (bounded ring of `RemediationCandidate` records; default `max_history=100`) and `RemediationCandidate` frozen dataclass (`gap_id`/`agent_id`/`gap_type`/`proposed_action`/`reason`/`candidate_at`). Public API: `record_candidate(gap_report)`, `proposed_action_for(gap_report)`, `recent_candidates(limit=20)`, `candidates_for_agent(agent_id)`. Mapping rules: `knowledge` + non-empty `qualification_path_id` → `trigger_qualification`; `data` → `request_data_routing`; `capability` → `escalate_capability`; else (including `knowledge` with empty path) → `no_action`. Emits `GAP_REMEDIATION_RECORDED` per record with `{gap_id, agent_id, gap_type, proposed_action, reason}`. **v1 NEVER actually triggers remediation actions** — only records what the system would do.
- **AD-539d (local-ship fleet gap aggregator):** New `src/probos/cognitive/gap_aggregation.py` with `FleetGapAggregator` and `FleetGapSnapshot` frozen dataclass (`snapshot_at`/`total_gaps`/`by_gap_type`/`by_priority`/`by_department`/`top_intents`). Public API: `take_snapshot(gap_reports)`. Aggregates by `gap_type`, `priority`, department (best-effort via `runtime.ontology.get_agent_department(agent_type)` — verified live signature at proactive.py:2380, dreaming.py:1098 — with `dept.department_id if hasattr(dept, 'department_id') else str(dept)` unwrap idiom from dreaming.py:1099), and top-5 most-affected intents from `affected_intent_types`. Reads `report.agent_type` directly (NOT `agent_id` — avoids Demeter detour through registry). Emits `FLEET_GAP_SNAPSHOT_TAKEN` with **counts only** — no agent_ids, no descriptions, no per-gap detail (privacy invariant directly tested at `test_take_snapshot_payload_excludes_agent_ids`).
- **Fleet = current ship in v1** — no federation reads. Cross-ship aggregation deferred to AD-539d-i (depends on AD-479 federation).
- 2 new EventTypes (`GAP_REMEDIATION_RECORDED`, `FLEET_GAP_SNAPSHOT_TAKEN`; verified collision-free against events.py post-Wave-19).
- New `GapPipelineExtensionsConfig` Pydantic model (`remediation_tracker_enabled=True`, `fleet_aggregator_enabled=True`, `remediation_max_history=100`) wired onto `SystemConfig.gap_pipeline_extensions`.
- Sync `_wire_gap_remediation_tracker` + `_wire_gap_aggregator` at startup/finalize.py mirror AD-525/AD-530 pattern; defensive `isinstance(cfg, GapPipelineExtensionsConfig)` boundary check (BF-254 / AD-487 pattern) handles MagicMock-config legacy tests (`tests/test_new_crew_auto_welcome.py`).
- Public attributes (Wave 5 convention #1): `runtime.gap_remediation_tracker`, `runtime.gap_aggregator` (no underscore).
- Late-bind `emit_event` field per AD-456/AD-530 sibling pattern.

**Why:** Both children are small additive surfaces extending shipped pipeline; per-prompt overhead × 2 would multiply Builder commit cost ~2× vs combo. Observational v1 keeps safety profile bounded — no auto-actions, no federation reach. Active remediation (AD-539c-i) requires explicit Captain decision to switch from observational to action mode after reviewing recorded candidates; federation aggregation (AD-539d-i) requires AD-479 federation to ship first.

**Deferred:**
- AD-539c-i: Active remediation — actually trigger qualification / data routing / capability escalation actions based on recorded candidates. Forcing function: Captain decides to switch from observational to action mode.
- AD-539d-i: Federated cross-ship gap aggregation — replace local-ship snapshot with multi-ship rollup. Forcing function: AD-479 Federation Hardening ships.

23 focused tests pass at `tests/test_ad539c_remediation.py` (12 — includes wiring boundary test) + `tests/test_ad539d_aggregation.py` (11 — includes wiring boundary test). Closes GH issues #106 + #107.

### AD-530 v1: Information Classification Enforcement — Disclosure Gate (2026-05-03)

**Problem:** Standing Orders advise agents not to disclose sensitive information, but there's no enforcement layer. Documents have classification metadata (records_store.py:27 `_CLASSIFICATION_LEVELS`), but outbound messages (Ward Room posts, LLM prompts) have no gate at the communication boundary.

**Decision:** v1 ships an observational disclosure gate:
- New `src/probos/security/classification.py` with `ClassificationGate` class.
- Primary method `check_disclosure(content, *, source_classification, destination_clearance) -> DisclosureDecision`.
- Reuses existing `_CLASSIFICATION_LEVELS` hierarchy at records_store.py:27 (real keys: `private`/`department`/`ship`/`fleet`; higher index = broader access). Read-only consumer; no duplication.
- Disclosure direction: BLOCK when `dst_lvl > src_lvl` — destination has broader reach than source classification permits. Direction is grounded in records_store.py:716 and :841 openness semantics.
- Safe defaults: unknown source → most restrictive (`private`, level 0); unknown destination → broadest (`ship`, level 2). Pairing makes unspecified-on-both BLOCK by hierarchy.
- Built-in pattern set (3 regex patterns: captain-directive markers, restricted-prefix literals, secret-format `name=value`). `api_key_like` 32+ char heuristic is **opt-in via `register_pattern()`**, NOT default — UUIDs / commit hashes / opaque tokens collide with it.
- `CLASSIFICATION_DISCLOSURE_BLOCKED` EventType emitted on every block.
- Privacy: event payload includes `content_length` only (NOT content); `blocked_phrases` lists pattern NAMES (NOT matched substrings).
- Public attribute `runtime.classification_gate` (Wave 5 convention #1); `emit_event` is a public field on the class (mirrors AD-456 EgressPolicy.emit_event).

v1 is OBSERVATIONAL — gate returns DisclosureDecision; caller decides whether to redact/suppress/retry. Integration into Ward Room post / LLM prompt builder paths deferred to AD-530d (active enforcement).

**Why:** Standing Orders → enforcement gap is real. Existing classification infrastructure is document-only. Communication-boundary gate is the missing piece. v1 is conservative (observational; never mutates messages) so the gate can be tuned without risk of false-positive suppression breaking real communication.

**Deferred:**
- AD-530b: Security Chief (Worf) runtime API for classification updates via Standing Orders. Forcing function: SecurityAgent spawned and needs `runtime.classification_gate.update_label()`.
- AD-530c: Full audit trail (event on every classified READ, not just blocks). Forcing function: AD-530d integration site lands and Captain reviews blocked-event volume.
- AD-530d: Active enforcement — integrate gate into WardRoomService.create_post + LLMClient prompt builder; redact/suppress/retry policy. Forcing function: AD-530b ships and Captain (or SecurityAgent under Standing Order) issues a label change.
- AD-530e: Default-pattern revisit (re-evaluate `api_key_like` and add tightened API-key prefix patterns: `sk-`, `pk_`, `Bearer`, `AKIA`, `ghp_`). Forcing function: AD-530d integration sites produce real outbound corpus and FP rate of `api_key_like` is measurable.

**Cross-links:** RecordsStore `_CLASSIFICATION_LEVELS` (records_store.py:27 — read-only consumer), AD-456 EgressPolicy (orthogonal — network egress, not content), AD-679 selective disclosure routing (orthogonal — document routing), Standing Orders (Federation tier — eventual policy source for AD-530b).

### AD-572e: Task Awareness in Captain DM Context (2026-05-03)

**Problem:** Combo A (Wave 8) shipped `CaptainEngagementProvider.snapshot()` for Captain-engagement signals. Combo C (Wave 13) added `wardroom_activity_summary()` for Ward Room context. Captain DMs to specific agents still lacked task awareness — agents had no current-commitments context when responding to Captain queries about their work.

**Decision:** Add `task_awareness(agent_id)` async helper to existing `CaptainEngagementProvider` (no new class, no new public attribute). Reads `runtime.work_item_store.list_work_items(status="open", assigned_to=agent_id, limit=10)`. Returns structured dict (`open_count`, `tasks: [{id, title, type}]`). Proactive cognitive loop injects result into `context["captain_engagement"]["task_awareness"]` during Captain DM response build (mirrors Combo C's wardroom_activity_summary integration).

**Why:** Final AD-572 child. Bounded scope — single async helper + single proactive-loop integration point. Defensive (returns empty dict on any failure, consistent with sibling helpers). Read-only consumer of WorkItemStore (no writes, no schema changes). Mirrors proven Combo C pattern.

**Cross-links:** AD-572b (CaptainEngagementProvider, Combo A), AD-572c (wardroom_activity_summary, Combo C), AD-496 (WorkItemStore), AD-572d-i (Captain Priority Queue — separately deferred; not unblocked by AD-572e).

### AD-513 Phase 2 v1: Crew Manifest Shell + Watch Filter + Ship Manifest (2026-05-03)

**Problem:** AD-513 Phase 1 delivered `get_crew_manifest()` + HXI panel + REST endpoint. Phase 2 has 6 follow-up capabilities (a-f). Trust-gated visibility, agent tool access, and ACM/competency fields each require new infrastructure. Shell command + watch filter + ship-summary are read-only additive surfaces shippable independently.

**Decision:** v1 ships 3 of 6 Phase-2 capabilities:
- (a) `/manifest` shell command — formatted Rich table with department/watch filters and `--ship` flag for vessel-level summary.
- (d) Watch filter on `get_crew_manifest(watch=...)` — additive kwarg + watch_manager dep injection. Backward-compatible.
- (f) `get_ship_manifest()` — vessel-level summary (ship_name, agent_count, departments, watches, alert_state) for federation gossip / workforce planning.

All read-only consumers; no writes; no schema migration.

**Why:** Wave 5 convention #14 aggressive pre-deferral. Phase 2b/c/e each have meaningful infrastructure asks (viewer-context plumbing, Tool registry integration, ACM lifecycle API). Shell + watch + ship-summary deliver immediate Captain-facing value with minimal coupling.

**Deferred:**
- AD-513 Phase 2b: Trust-gated visibility (redacted views by earned-agency tier).
- AD-513 Phase 2c: Agent tool access (internal API for designed agents).
- AD-513 Phase 2e: ACM lifecycle state + competency fields in manifest payload.

**Cross-links:** AD-513 Phase 1 (ontology/service.py:469), AD-429 (Ontology), AD-064 (Watch Rotation — WatchManager consumer), AD-479 (Federation — ship manifest is the gossip surface).

### AD-487: Self-Distillation v1 — Personal Ontology Map Step (2026-05-03)

**Problem:** LLMs don't know what they know without prompting. Agents need systematic knowledge-domain inventory to build personal ontologies (capability map, not library copy). Roadmap describes 3-stage map-reduce + daydreaming + DID portability — too much for one wave.

**Decision:** v1 ships ONLY the Map step. `PersonalOntologyProber.probe_domain(agent_id, domain)` builds an `LLMRequest` from a structured self-query template, calls `runtime.llm_client.complete(request, priority=Priority.NORMAL)`, parses the JSON `LLMResponse.content` into a `ProbeResult` (sub_topics + confidence_scores), persists to new `agent_probes` SQLite table via the standard `ConnectionFactory` injection (Wave 5 convention #2), rate-limited per (agent, domain, 24h). Emits `ONTOLOGY_PROBE_RECORDED` + `ONTOLOGY_PROBE_RATE_LIMITED`. Wired onto `SystemConfig.self_distillation`. Lifecycle is `async start()` / `async stop()` (no private `_ensure_schema()` cross-module call). The `_wire_self_distillation` phase function adds a defensive `isinstance(config.self_distillation, SelfDistillationConfig)` boundary check beyond the prompt body — pre-existing tests in `test_new_crew_auto_welcome.py` pass `MagicMock` for `config`, which without the check would make `.enabled` truthy and `db_path` an unresolvable mock path that aiosqlite cannot open. Other wire functions tolerate MagicMock because they don't I/O; this one does, hence the guard.

**Why:** Map step has clean surface (LLM call + parse + persist). Collapse/Reduce need accumulated probes to be useful — premature without Map data. Daydreaming needs dreaming.py bandwidth slot (separate scope). DID portability needs ontology data structure (depends on Reduce). Convention #14 aggressive pre-deferral applied.

**Cross-AD orthogonality (non-conflict):** AD-636 priority lane semaphores and AD-637f priority classification live inside `LLMClient.complete` (llm_client.py:166, 427-457); they throttle LLM tokens by tier. AD-487's 24h per-(agent, domain) limit operates at the prober layer. No integration needed.

**Deferred:**
- AD-487b: Collapse — cluster probes into capability categories. Ships when >=10 probes accumulate per agent.
- AD-487c: Reduce — `PersonalOntology` data structure. Depends on AD-487b.
- AD-487d: Daydream dream type — idle-cycle exploration. Ships when AD-487a/b/c stable + dreaming.py bandwidth.
- AD-487e: DID portability integration (AD-441). Depends on AD-487c.

**Cross-links:** AD-486 (onboarding Phase 3 Self-Discovery — eventual consumer), AD-441 (DID portability — eventual consumer), dreaming.py (eventual daydream slot), LLMClient (read-only consumer), AD-542 (DatabaseConnection / ConnectionFactory abstraction).

### Combo C: 5 trivial extensions (526d/572c/573c/573f/575c) (2026-05-03)

**Problem:** Four already-partial-closed parent ADs (AD-526, AD-572, AD-573, AD-575) had remaining trivial extensions worth shipping but each too small for a standalone Builder commit. Wave 8 Combo A precedent shipped 7 children clean; Combo C follows the same template, drops 2 of 7 in revision pass.

**Decision:** Single commit, 5 children, 19 focused tests:

- **AD-526d (Game Preference Tracking).** New `src/probos/recreation/preferences.py` with `GamePreferenceTracker` — per-agent per-game-type play frequency map. Public API `record_game(agent_id, game_type)` / `get_preferences(agent_id)` / `top_game_for(agent_id)`. Wired as `runtime.recreation_preference_tracker` (Wave 5 convention #1 public attribute) with `set_event_callback(self.emit_event)` late-bind in `__init__` mirroring `BilletRegistry`. Emits `GAME_PREFERENCE_RECORDED` per record. Read-side analytics surface that AD-526e/f/g/h will share. **Why this shape:** the data-collection hook is the pre-condition for the deferred children — shipping the analytics tracker first lets later ADs land mechanically.

- **AD-572c (Ward Room Activity in Captain DM Context).** Extended Combo A's `CaptainEngagementProvider` with new async `wardroom_activity_summary()` helper that iterates `await ward_room.list_channels()` and aggregates per-channel `len(await ward_room.list_threads(channel_id, limit=10))` into `{"channels": {ch_id: count, ...}, "total_threads": N}`. Merged into `context["captain_engagement"]["wardroom_activity_summary"]` in `_gather_context` (proactive.py:1175 area). Per-channel `list_threads` failure degrades to partial result (Wave-5 tier-2). **Why a separate async method, not extending `snapshot()`:** `snapshot()` is sync (existing call site in `_gather_context` is sync there); WardRoom APIs are async. Cleanest split: keep `snapshot()` sync, expose async helper, await separately at the (already-async) caller.

- **AD-573c (Agent-Writable Scratchpad NOTE Action Tag).** `[NOTE tag]body[/NOTE]` action format. Extended `cognitive_agent.py:1747` markers dict with `"note": re.compile(r'\[NOTE\s', re.IGNORECASE)` so gap-detection treats undeclared NOTE tags as known actions (not phantoms). Added extractor in `proactive.py` mirroring the `notebook_pattern` shape — calls `runtime.working_memory.add_scratchpad(body)` (Combo A AD-573b helper, already shipped) and emits `WORKING_MEMORY_NOTE_RECORDED` with `{agent_id, tag, text_len}`. Strips `[NOTE ...]` blocks from text after dispatch (mirrors notebook strip). **Why this shape:** scratchpad already exists; only the action-tag plumbing was missing. Mechanical wiring.

- **AD-573f (Commitment Lifecycle Helpers).** `mark_commitment_complete(commitment_id)` mutates the existing dict's `status` key in-place; emits `COMMITMENT_RECORDED` with `action="complete"`; clean no-op on unknown id (Wave-5 tier-2). `pending_commitments()` filters out `status in {"done", "expired"}`. `expired_commitments(now)` filters by `due < now and status != "done"`. `add_commitment` extended to emit `COMMITMENT_RECORDED` with `action="record"` after a successful add. New `set_event_callback(emit_fn)` late-binds the emit target; runtime wires it in `__init__` immediately after `WorkingMemoryManager` construction. **Why operate on `list[dict]` instead of a `Commitment` dataclass:** Convention #20 reality-check during revision — Combo A actually shipped `commitments: list[dict[str, Any]]` (verified at `working_memory.py:35,107,138-154`). NO `Commitment` dataclass exists. Shape preserved; lifecycle methods mutate dict keys. Manager-scoped (NO `agent_id` parameter — there is no per-agent partition).

- **AD-575c (DM Self-Reference Flag).** `_check_unread_dms` (BF-257-hardened path) scans the DM `body` (case-insensitive) for `@<agent_callsign>` and sets `event_data["self_referenced"] = True` before `route_event`. Read-only check; no upstream content mutation. **Why minimum scope:** the smaller, edge-case sibling of AD-575b (which was wholesale-deferred in Combo A). Forwarded Captain DMs that mention the recipient by callsign should preserve that signal so downstream attention scoring can weight them appropriately.

3 new EventTypes (`GAME_PREFERENCE_RECORDED`, `WORKING_MEMORY_NOTE_RECORDED`, `COMMITMENT_RECORDED`; verified collision-free against `events.py`). Public attributes: `runtime.recreation_preference_tracker` (NEW), and `runtime.working_memory.set_event_callback` wiring (extends Combo A surface). 19 focused tests pass (per-child files: 4+3+4+5+3). Full gate: 10677 passed, 15 skipped (delta +19 vs Wave-12 baseline 10658 — exact target hit).

**Wholesale-deferred (per AD-575b precedent):**

- **AD-572d → AD-572d-i.** Captain DM intake should signal a wakeup to `_think_loop`. Verified: `proactive.py` uses bare `await asyncio.sleep(self._interval)` at lines 475/482/584/782; zero `asyncio.Event` / `asyncio.wait_for` patterns. Adding interruptible-wait is architectural surgery on the BF-211-hardened think loop — not a "trivial extension." **Forcing function:** AD-572d-i ships only when a separate AD introduces interruptible-wait infrastructure on `_think_loop` (e.g., `await asyncio.wait_for(trigger.wait(), timeout=self._interval)` plus clear-on-wake semantics). Once that lands, AD-572d-i becomes a 5-line Captain-DM-intake setter.

- **AD-573e → AD-573e-i.** Working memory should pull "recent k entries for agent X" from the cognitive journal. Verified: `cognitive/journal.py` exposes only `record / get_reasoning_chain / get_token_usage / get_token_usage_since / get_token_usage_by / get_decision_points / get_stats / start / stop / wipe / prune`. No `recent_for_agent`. The closest substitute `get_decision_points(agent_id=...)` filters for high-latency / failures-only — wrong semantics for a "recent k entries" recall. **Forcing function:** AD-573e-i ships only when `cognitive_journal` exposes a recency-ordered per-agent recall API (separate AD; the architect did not identify a clean alternative existing API). At that point AD-573e-i becomes a one-method consumer addition on `WorkingMemoryManager`.

**Why drop now, not at Builder time:** Wave 5 convention #14 (aggressive pre-deferral). Both surfaces verified absent during architect review pass-1; revising the prompt to drop them was cheaper than letting Builder hit the wall. Pattern is now reflexive at three levels (drafter, dispatcher, reviewer) — see `prompts/Reviews/README-wave-13-pass-2.md` reflexivity note.

**Cross-links:** AD-526a/b/c (Recreation), AD-572b (CaptainEngagementProvider), AD-573b (WorkingMemoryManager extensions), AD-575b (theater-deferred precedent), Combo A (AD-575b drop-on-revision template).

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

### AD-525: Agent Creative Expression v1 (Skills Inventory + Records Output) (2026-05-03)

**Problem:** Agents operate purely in duty mode — every action serves a functional purpose. Personality framework (Big Five traits) exists but has no creative outlet. Roadmap describes 5 capabilities (Skills Inventory + Time Allocation + Records Output + Code-as-Art + Cultural Emergence). Heavy interaction surface; large scope.

**Decision:** v1 ships 2 of 5 capabilities — the bounded generative surfaces with no infrastructure ask:
- `CreativeSkillsRegistry` — open-ended catalog of 8 default creative skills (Creative Writing, Technical Writing, Code as Art, Visual Design, Music Composition, Philosophy, Historiography, Comedy/Satire). Per-skill Big Five trait affinity. Read-only `affinity_score(skill_id, traits)` + `top_skills_for(traits, k)`. Extensible via `register_skill()` (runtime-only; no persistence in v1).
- `CreativeOutputWriter` — publishes agent creative works to `creative/{callsign}/{topic_slug}.md` via existing `RecordsStore.write_entry`. Default classification `ship` (shared culture per design). `medium` and `skill_id` are encoded as `tags=["creative", medium, skill_id]` since `write_entry` does not accept arbitrary frontmatter keys (verified at records_store.py:113-148); the canonical author/classification/status/created/updated/department/topic/tags frontmatter is assembled by `write_entry` itself.

Both are read-only consumers of existing runtime surfaces (`records_store`) and the `crew_profile.PersonalityTraits.to_dict()` adapter; no writes to existing data, no dependency on `runtime.profile_store` (which is currently unwired). Public attributes (no underscore per Wave 5 convention #1).

**Why:** Generative + bounded. Skills Inventory is a stateless registry. Output Writer mirrors the existing `RecordsStore.write_entry` caller pattern (proactive.py:3033). No rate limits, no rank gating, no multi-agent collaboration in v1 — those are AD-525b/c/d/e territory with explicit forcing functions.

**Deferred:**
- AD-525b: Time-allocation rules gated by Earned Agency rank. Forcing function: v1 surfaces show agents using CreativeOutputWriter and capacity policy needs to enforce limits.
- AD-525c: Code-as-creative-expression — relaxed-consensus path for non-duty BuildSpec runs.
- AD-525d: Cultural emergence detection — depends on Archive (AD-434) + corpus threshold (~50+ works).
- AD-525e: Creative collaboration — co-authoring; depends on cultural-emergence baseline.

**Cross-links:** AD-357 (Earned Agency — eventual gate), AD-434 (Archive — eventual cultural-emergence consumer), AD-526 (Recreation — Combo A AD-526c + Combo C AD-526d trackers exist; creative output is distinct from games), CrewProfile Big Five traits (read-only consumer), RecordsStore (consumer).

### AD-685b: Phantom-API Pre-Check — Method-Call AST Validation (2026-05-03)

**Problem:** AD-685 v1 catches kwarg-name phantoms but NOT method-name phantoms. 4 documented recurrences across Waves 9B, 10, 12, 14 of the pattern: prompt asserts `<obj>.<method>(...)` where `<method>` doesn't exist on the resolved class. 3 of 4 caught at review time (LLMClient.chat → complete being the most recent in Wave 14); only 1 caught by AD-685 v1 (runtime.duty_schedule_tracker via runtime.X check). Architect's 4th-recurrence forcing function.

**Decision:** Extend `scripts/phantom_api_ast_helper.py` with method-name validation:
- Resolve `<obj>` to its class via runtime attribute lookup (Pattern A), constructor assignment in prompt (Pattern B), or type hint (Pattern C).
- Walk class source file AST to collect method names (sync + async, exclude dunders).
- Flag call sites where `<method>` is NOT in the class's method set as `method_phantom`.
- Conservative: skip when class resolution fails — never false-flag.

PowerShell wrapper changes: minimal (display new category prefix). Exit semantics unchanged.

**Why:** 4 recurrences across 6 waves means the architect-discretion sweep posture has expired. One scripted convention beats N drafting-time conventions. Recursive-validity gate (AD-685 v1 precedent) ensures AD-685b's own prompt validates clean.

**Deferred:**
- AD-685c: Type-shape validation (dict vs list kwarg values).
- AD-685d: Field-name validation for dataclass/Pydantic constructor kwargs (e.g., WorkItem field `payload` vs `metadata`).

**Cross-links:** AD-685 v1 (Wave 11; symbol-existence + kwarg-name), Wave 14 retrospective (4th method-shape recurrence trigger), `phantom_api_ast_helper.py` (extended in-place).

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

**v1 (2026-05-04):** scaffold (ProcessChainStepKind/Step/Definition/Executor) + Scout-internal migration. BF-209 retained.

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

**Date:** 2026-04-20 (adopted); 2026-05-07 (Wave 95 umbrella close)
**Status:** Realised (Wave 95 close — all six principles delivered across shipped child ADs)
**Issue:** #302
**Parent:** AD-632 (Cognitive Chain Architecture)
**Related:** AD-651 (Billet Instructions), AD-639 (Chain Personality Tuning), AD-647 (Process Chains)
**Realised in:** AD-632 (unified pipeline substrate), AD-649 (channel/recipient → register inference), AD-639 (chain trust band modulation), AD-650 (analytical depth field), AD-651 (standing order decomposition), AD-651a (compose billet — proposal/duty format), AD-647 / AD-647c (process chains — variable chain depth + process-specific composition), AD-653 Layer 1 (speak-freely register shifting). Downstream consumers AD-655 / AD-656 / AD-657 / AD-658 / AD-659 / AD-660 all complete and reference AD-652 modulation parameters. Trackers reconciled in Wave 95.

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

### AD-454 — Emergence Behavior Taxonomy (OSS canonical 22-code with anti-pattern)

OSS-publishable qualitative classification scheme for AD-453 research. 22 codes total: 18 ported from the commercial 18-code taxonomy + 4 architect additions (ABLATION-MEM, SELF-AWARE, STANDING-ORDER-COMPLIANCE, CASCADE-CONFAB). One anti-pattern: CASCADE-CONFAB (correlated confabulation cascade) — required for false-positive accounting in AD-453. Source of truth: `src/probos/cognitive/emergence_taxonomy.py`. Doc: `docs/research/emergence-taxonomy.md`. Distinct from `EmergentDetector` (quantitative population dynamics) and from Riedl 2026 PID/TDMI (quantitative information atoms). Trial observation data is intentionally NOT ported — stays in commercial repo.

The EvidenceCollector that consumes this taxonomy ships in the `prompts/ad-454-evidence-collector-v1.md` follow-up.

### AD-454-collector — EvidenceCollector agent (default-disabled, file-based research artifact sink)

OSS-tier passive observer. Subscribes to `EventType.WARD_ROOM_POST_CREATED`. Classifies each post against the AD-454 taxonomy (22 codes incl. CASCADE-CONFAB anti-pattern) via fast-tier LLM call. Writes `OBS-NNNN.yaml` files under `config.emergence_collector.output_dir`. Default disabled (research opt-in). No trust effects, no Hebbian effects, no consensus participation, no federation sync. `tier="utility"` (matches IntrospectionAgent / SystemQAAgent precedent).

Dedup: per-(`author_id`, `behavior_code`), default 600s window. Confidence threshold default 0.7. Listener-boundary tier-2 (log-and-degrade) policy across all entry points to avoid silent fire-and-forget task death. Closes #510 (joint with AD-454 taxonomy prerequisite).


### AD-795 - Yeo Compact starter chips on empty thread (Wave 187)

ui/src/components/YeoStarterChips.tsx + store chatDrafts: Record<string,string> + ProfileChatTab draft-consume effect. Chip click writes a starter prompt into the agent's draft slot; ProfileChatTab hydrates its local input and focuses the textarea. Does not auto-send (Claude Chat parity). Hidden as soon as the conversation has >= 1 message (CompactApp gates render on yeoMessageCount === 0). Default 5-chip set (Brief me / Help me write... / Plan a task... / Code something... / Remember this...); custom sets accepted via the chips prop for future project-overridable AD-793 wiring. +4 vitest. Closes #719.

### AD-796 - Yeo Compact greeting + status line on empty thread (Wave 187)

ui/src/components/YeoEmptyGreeting.tsx. Time-of-day greeting via the pure greetingForHour(hour) helper (morning <12 / afternoon <18 / evening), captain-name prop with 'Captain' default, status line composed from store wardRoomUnread + GET /api/health crew_agents count, fallback 'All quiet.' when both sources are empty or fail. Fetch is wrapped tier-2 (log-and-degrade) - any network failure still renders the greeting. Captain-name wiring to AD-757 Captain Card is a forward marker (no REST endpoint exists yet - adding one is its own AD). +7 vitest. Closes #720.


### AD-834 - NL task creation + dispatch toggle in the HXI Work Tab (Wave 202)

Frontend-only activation of the already-wired WorkItem dispatch engine (closes #808). ProfileWorkTab.tsx 'Create Task' form gains a natural-language instructions textarea (forwarded as 'description') and a 'Dispatch to agent now' checkbox (default ON) that emits metadata.dispatchable=true; createWorkItem in useStore.ts widened to pass description? + metadata? through to the existing POST /api/work-items body. No backend change - create_work_item(**body) already accepts both fields and WorkItemRouter.is_dispatchable() already gates on metadata.dispatchable, routing the task with its NL description to the assigned agent. Toggle OFF omits the flag (draft, not dispatched). Enter-to-submit removed from the title input (textarea is now primary; submit via Create button). +3 vitest (ProfileWorkTab.create.test.tsx). npm run build clean per BF-279.

### AD-835 - Per-tier harness adaptation hook: system-prompt suffix (Wave 202)

Per-tier system-prompt adaptation seam, motivated by the 2026-05-15 VS Code "Coding Harness" blog's thesis that per-model adaptation (a different system prompt per checkpoint) is the harness's highest-leverage differentiator. Closes #809. v1 scope: a config-driven, per-tier `system_prompt_suffix` appended to the composed system message at the single composition point in `_call_openai`. Config (config.py): four optional flat fields `llm_system_prompt_suffix_{fast,standard,deep,vision}: str | None = None` (sensible default None = no-op, zero-config boot byte-identical), surfaced through `tier_config(tier)` as the dict key `system_prompt_suffix` via a fast/standard/deep/vision `suffix_map`. Threading (llm_client.py): `_complete_inner` resolves `effective_system_suffix = tc.get("system_prompt_suffix")` for the ATTEMPT tier (a fallback to standard uses standard's suffix, not the originally-requested tier's) and threads it through `_call_api` into `_call_openai` alongside the existing effective_* sampling params - NOT read from global state inside `_call_openai`. Apply block in `_call_openai` runs after the prompt-synthesis and pre-built-messages branches converge, before payload assembly: appends the suffix to the system message ONLY (str content -> `f"{base}\\n\\n{suffix}"`; list content -> append a `{type:text,text:suffix}` part; no system message -> insert one at index 0), replacing messages[0] via spread (never mutating the caller's dict). User/tool messages are never touched. Empty/None suffix -> byte-identical to pre-AD-835. The ollama-native path (`_call_ollama_native`) is intentionally out of scope (openai-format only). Seam documented above `_call_openai` for **AD-835b** (per-model tool-format remapping - Claude replace_string_in_file vs GPT apply_patch - must hook the same tc-threaded path, not a new global). No change to AgenticLoop, ToolExecutor, the fallback chain (`_TIER_ORDER`/`_LLM_TIERS`), api_format routing, attachment-ref resolution, or ModelRouter (AD-463). +6 pytest (tests/test_ad835_tier_adaptation.py: default no-op, suffix in prompt-synthesis branch, suffix in pre-built-messages branch, user/tool untouched, fallback-uses-attempt-tier suffix, zero-config default None). Forward marker: AD-835b (tool-format remap).

### AD-836 - Offline agent-behavior evaluation harness: ProbOS-Bench v1 (Wave 202)

Offline eval harness for decomposer behavior, tests/tooling only - zero production-code changes, no live-model calls. Closes #810. Motivated by the 2026-05-15 VS Code "Coding Harness" blog: the harness's reliability is credited to a rigorous offline eval loop (VSC-Bench) that scores every change against a fixed task set before it ships. ProbOS already had the raw materials - the AD-716 opt-in JSON-scoreline pattern and a hand-authored tests/fixtures/eval/decomposer_cases.json - but no runner that loads the cases and emits an aggregate score. v1 scope is decomposer-only. Section 1 (tests/benchmarks/probos_bench.py): pure, import-side-effect-free, fully-typed scoring functions with NO production imports - load_cases(path) -> list[dict]; score_case(case, produced_intents) -> {resolved, precision, n_intents} honoring three case shapes (exact expected_intents subset match -> precision = hits/n_intents; min_intents effort floor -> resolved iff len(produced) >= min_intents, precision 1.0/0.0; conversational expected_intents == [] -> resolved iff no intents produced, precision 1.0 on the empty-produced answer else 0.0); aggregate(results, total_tokens) -> {resolution_rate, intent_precision, mean_intents, total_tokens} with the empty-list boundary returning zeroed rates. Section 2 (tests/benchmarks/test_probos_bench_decomposer.py): opt-in runner copying the AD-716 module-level pytest.mark.skipif guard exactly but env-gated on PROBOS_BENCHMARK=1 (skipped by default). Builds a real IntentDecomposer(llm_client=MockLLMClient(), working_memory=WorkingMemoryManager()) - deterministic mock, no live model - runs every fixture case through decompose(...), scores via probos_bench, prints one PROBOS_BENCH json scoreline, and asserts the scorecard is well-formed so CI still exercises the path when the body is opt-in. total_tokens is 0 (the mock reports no usage; live-usage is out of v1 scope). Section 3 (tests/test_ad836_probos_bench.py): 5 always-on self-tests in the normal gate (NOT under benchmarks/, so no env var) - exact-match happy path, min_intents satisfied/unsatisfied, conversational empty/non-empty produced, empty-produced exact-match edge, and aggregate over a mixed result list plus the empty-list boundary. Import strategy: tests is a package (tests/__init__.py present) so both the runner and the self-test use from tests.benchmarks.probos_bench import .... Verified: 5 self-tests green; opt-in runner skipped by default, and with PROBOS_BENCHMARK=1 prints a directional resolution_rate 0.83 / intent_precision 0.83 / mean_intents 0.61 over 18 cases. Directional, not publishable (same disclaimer as the AD-716 micro-LoCoMo harness). Seams: AD-836b (full AgenticLoop trajectory/tool-call scoring via score_trajectory(AgenticResult) mirroring score_case), AD-836c (wire the harness as a required pre-merge gate). No new dependencies.

### AD-746a - Router-side latest-frame mirror for FORCE DESCRIBE (Wave 202f)

Defense-in-depth for Captain-initiated FORCE DESCRIBE, filed during the BF-323 retrospective. Closes #794. force_describe_current_frame reads VisionConsumer's _latest_frame_by_session / _latest_frame_global caches, which were only populated by consumer._handle when the VisionAggregator FORWARDS a frame. That made FORCE DESCRIBE transitively dependent on the aggregator buffer/timer state machine being healthy - when it deadlocked in BF-323 the cache stayed empty and FORCE DESCRIBE silently returned None with no vision LLM call. Fix adds a PUBLIC second writer record_uploaded_frame(self, sha, session_id, captured_at) -> None on VisionConsumer (consumer.py, near force_describe_current_frame, fully type-annotated) that mirrors the _handle write - per-session _latest_frame_by_session[session_id] = (sha, captured_at) when session_id is set, plus _latest_frame_global = (sha, captured_at) - no-op on empty sha and idempotent with _handle (_handle itself unchanged). The upload endpoint upload_camera_frame (routers/perception.py) calls it via getattr(runtime, vision_consumer, None) - the same accessor used elsewhere in the module - immediately BEFORE intent_bus.broadcast(msg), wrapped in a Tier-1 swallow plus logger.debug so a mirror failure can never break frame admission. The broadcast call, the params dict, and every status-code path are unchanged. This gives FORCE DESCRIBE a direct upload-time path independent of the bus and aggregator chain. The router never touches _latest_frame_* directly, only the public method (Law of Demeter / Open-Closed). Tests: tests/test_ad746a_force_describe_mirror.py - 3 new (record_uploaded_frame populates both caches; force_describe resolves the mirrored SHA with _process stubbed and NO _handle call; empty-sha no-op). Scoped force_describe/perception/vision_consumer regression 94 passed.

### AD-833 - Improvement-proposal grounding gate (Wave 202d, DESIGN ONLY - no build this wave)

Architect design pass. The 2026-05-31 Ward Room "Improvement Proposals" validation found 0 of 18 agent-authored proposals were verifiable bugs; the dominant failure mode is a confabulation cascade across five recurring classes - phantom symbol (names a non-existent event/intent/duty/file/class/method), already-shipped (re-files CLOSED work), benign-telemetry-as-fault (cites an event explicitly marked data[benign]=True / data[expected]=True - the AD-832 case - and reads it as a bug), conflated subsystem (similarly-named-but-different module), and confabulated calculation (treats LLM prose as a measured fact). AD-832 fixed ONE misread event; AD-833 designs the general gate, analogous to AD-734 capability-claim verification (ObservableStateVerifier.verify_claims). Design: a ProposalGroundingVerifier mirroring the AD-734 provider pattern - constructor-injected list of narrow GroundingProvider plugins behind a typing.Protocol (ISP), each returns a GroundingFinding (provider_name, verified bool-or-None, score, evidence) with log-and-degrade per provider, aggregated into a ProposalGroundingResult (score, verified, findings, confidence). Three providers, phased because only one has a clean existing API: SymbolExistenceProvider (failure classes 1+4, reuses CodebaseIndex.query / find_callers / get_full_api_surface which all exist today) ships in AD-833 v1; TrackerCrossRefProvider (class 2, needs a new CodebaseIndex method to scan DECISIONS.md / roadmap.md for CLOSED/SHIPPED entries - no API today) deferred to AD-833a; BenignTelemetryProvider (class 3, needs an event-log query-by-event-name returning recent data dicts to read the benign marker - no API today) deferred to AD-833b. The verifier runs at the async proposal-authoring boundary, NOT inside ProposalStore.submit (which is synchronous and signature-load-bearing - making it async would ripple to 6+ callers); the authoring path calls verify(...) then proposal_store.attach_grounding(...). ProposalStore carries grounding via a parallel _grounding dict keyed by proposal id (the frozen CapabilityProposal model is unchanged; the store owns derived state); ApprovalGate.list_pending surfaces it so the Ward Room UI can render a grounding badge and deprioritize low-grounding proposals. The gate is ADVISORY in v1 - score + evidence only, never blocks submission; an auto-reject/veto policy is a later AD. Deliverable is the build prompt prompts/ad-833-proposal-grounding-gate.md (Ready for a future wave) plus this design entry; no production code shipped this wave. Confirmed by codebase grounding: there is NO programmatic already-shipped tracker check and NO event-log query-by-event-name API today, which is why the tracker/telemetry providers are deferred to sub-ADs rather than attempted in v1.

### AD-833 v1 - Improvement-proposal grounding gate BUILD (Wave 204)

Builds the v1 slice of the AD-833 design (see the Wave 202d DESIGN-ONLY entry above). New module src/probos/cognitive/self_improvement/grounding.py: frozen GroundingFinding(provider_name, verified: bool | None, score, evidence) and ProposalGroundingResult(score, verified, findings, confidence); a @runtime_checkable GroundingProvider Protocol (name: str, async check(proposal) -> GroundingFinding); SymbolExistenceProvider (failure classes 1+4) that extracts symbol-like tokens from f"{proposal.summary}\n{proposal.fit_assessment}" using a tokenizer that keeps only tokens with an underscore, an interior capital, or a dotted path (prose words are ignored), resolves each token through CodebaseIndex.query -> find_callers -> get_full_api_surface (each in try/except logger.debug), returns verified=None / score=0.0 when no symbol-like tokens are present, else score = resolved/total with verified=False if ANY token is UNRESOLVED and per-token evidence ("token -> resolved via query" / "token -> UNRESOLVED"); and ProposalGroundingVerifier(providers) that runs each provider under a per-provider try/except (a raising provider is logged at warning with the "AD-833" tag and skipped, never fatal), returns the empty-aggregate default ProposalGroundingResult(score=1.0, verified=True, findings=[], confidence=0.0) when there are no findings, else score = mean(finding.score), verified = score >= 0.5 AND no finding.verified is False, confidence = determined/total. Mirrors the AD-734 ObservableStateVerifier provider pattern (ISP + constructor injection + log-and-degrade). ProposalStore (proposal.py) gains a parallel _grounding: dict[str, ProposalGroundingResult] (the frozen CapabilityProposal is unchanged; the store owns derived state), attach_grounding(proposal_id, result) -> None (unknown id -> logger.warning with the "AD-833" tag + return, never raises) and get_grounding(proposal_id) -> ProposalGroundingResult | None; submit is byte-unchanged (synchronous, signature-load-bearing). ApprovalGate (approval_gate.py) gains an optional ctor grounding_verifier param, list_pending_grounded() -> list[tuple[CapabilityProposal, ProposalGroundingResult | None]], and async enqueue_grounded(proposal) (submits first, then verify+attach under try/except so a grounding failure leaves the submitted proposal standing); list_pending / enqueue unchanged. Wiring: startup/finalize.py constructs the verifier over runtime.codebase_index (absent -> ProposalGroundingVerifier(providers=[]) with a logger.warning, never crashes finalize) and injects grounding_verifier into ApprovalGate; runtime.proposal_grounding_verifier is exposed (annotated Any | None, default None). The gate is ADVISORY only - it never vetoes or blocks a proposal; score + evidence is surfaced for the Ward Room to render a grounding badge and deprioritize low-grounding proposals. v1 ships SymbolExistenceProvider only; TrackerCrossRefProvider (AD-833a) and BenignTelemetryProvider (AD-833b) remain deferred per the design (no programmatic already-shipped tracker check and no event-log query-by-event-name API today). Tests: +18 pytest (tests/test_ad833_grounding_gate.py) with a real _FakeCodebaseIndex stub - no MagicMock at the index boundary per the Phantom-via-MagicMock rule. No UI change.

### AD-838 - Office create intents wired end-to-end + consensus gate + NL synthesis (Wave 203)

The DocxAgent / PptxAgent / XlsxAgent skill agents (src/probos/skill_framework.py) had usable create/revise/summarize methods but no mesh-facing intent surface - they could only be invoked by direct Python call, never routed through the intent bus. AD-838 declares intent_descriptors on each and routes them through handle_intent so the decomposer/router can dispatch document, deck, and spreadsheet work to them. Intents and consensus: docx_summarize (requires_consensus=False), docx_create / docx_revise (True); pptx_summarize (False), pptx_create (True); xlsx_read_range (False), xlsx_update (True) - every write intent is consensus-gated per the destructive-op rule, reads are not. handle_intent validates required params at the boundary and returns a failed IntentResult (never a raw raise) when title/file_path/sheet/range/instructions/updates are missing, and returns None for intents the agent does not own (clean self-deselect, no false positives in capability matching). Output-path resolution: three pure module helpers (_slugify, _parse_json_list, _resolve_default_output_path - no import-time side effects) derive a default save path from runtime.config.office_skills.output_dir when output_path is omitted, slugifying the title (My Big Report -> my-big-report.docx); an explicit output_path is honored exactly including nested directories. create_docx / create_pptx gained an optional output_path: str | None = None parameter. NL content synthesis: docx_create / pptx_create accept a natural-language brief and synthesize structured content when explicit content is not supplied - _synthesize_paragraphs (docx) and _synthesize_slides (pptx, a JSON array of {title, bullets}) are await-aware via hasattr(maybe, __await__) and honest-degrade to a minimal single-paragraph / single-slide fallback when no LLM client is wired (so the create path always produces a file). Config: new OfficeSkillsConfig.output_dir (default ~/.probos/output) plus an _expand_output_dir field-validator mirroring _expand_template_dir; zero-config boot is byte-identical (real SystemConfig() constructs the field with its default). Tests: tests/test_ad838_office_create_wiring.py - 10 new (pptx/docx dispatch, xlsx_update round-trip, unknown-intent -> None, output_path honored incl nested dir, slugified default filename, NL synthesis populates slides, honest-degrade single-slide deck, missing-title error, consensus-flag assertions via intent_descriptors). tests/test_office_agents.py (AD-755, 6) unchanged and green. AD-838 blast-radius gate across all 18 skill_framework/office test files: 408 passed, 1 pre-existing unrelated failure (test_captain_invariant_exposure_gate, a missing prompt file on disk, identical at clean HEAD with AD-838 stashed). No protocol changes to BaseAgent / IntentMessage / IntentResult. Zero new deps.

### AD-838c - Dynamic dependency install for the runtime task path (Copilot-style ask-before-install) (Wave 203)

ProbOS could install third-party packages only for the self-mod pipeline (designed-agent code), gated by the self_mod.allowed_imports whitelist. AD-838c generalizes the DependencyResolver into a reusable, policy-driven installer and exposes a task-path API so the runtime can resolve a missing import on demand, Copilot-style: ask the operator before installing anything unlisted. The resolver (src/probos/cognitive/dependency_resolver.py) gains a policy (whitelist | prompt_unlisted), an install_fn / approval_fn callback pair, a deny_imports hard block, and an IMPORT_TO_PACKAGE map (bs4 -> beautifulsoup4, yaml -> pyyaml, dateutil -> python-dateutil). detect_missing surfaces unlisted imports only under prompt_unlisted, never surfaces a name in deny_imports, and resolve verifies each install via importlib.util.find_spec after install_fn succeeds - a package that does not actually become importable lands in failed, not installed. Config: new DependencyConfig (dynamic_install_enabled: bool = False, dynamic_install_policy: Literal = prompt_unlisted, dynamic_install_deny: list[str] = []) wired into SystemConfig.dependency; disabled by default so zero-config boot is unchanged. Wiring (single shared instance invariant): startup/cognitive_services.py constructs ONE DependencyResolver when self_mod.enabled OR dependency.dynamic_install_enabled and passes the same instance to both the SelfModificationPipeline and the new CognitiveServicesResult.dependency_resolver field; runtime.py stores self.dependency_resolver and adds async def ensure_dependency(import_name: str | list[str]) -> DependencyResult immediately before submit_intent_with_consensus; the interactive shell wires approval_fn = user_dep_install_approval outside the self-mod guard so the task path gets the prompt even when self-mod is off. Defense in depth: ensure_dependency hard-declines unlisted packages (success=False, declined populated, error 'approval callback unavailable') when no approval_fn is wired rather than installing silently, auto-approves the self_mod.allowed_imports whitelist tier without prompting, and logs every step to the event log under category=dependency (dependency_check, dependency_install_approved, dependency_install_success, dependency_install_declined, dependency_install_failed). Scope held: no new package-manager backend, no auto un-prompted installs, no changes to CodeValidator / forbidden_patterns, allowed_imports is retained as the auto-approve tier (not removed). Tests: +9 pytest (tests/test_ad838c_dynamic_install.py - disabled-returns-failure, prompt_unlisted vs whitelist detection, deny_imports block, happy-path install with stateful find_spec, approval-False installs nothing, single-shared-resolver invariant, governance-event emission, no-approval-callback hard-decline); blast radius tests/test_dependency_resolver.py + tests/test_config.py (38) and tests/test_self_mod.py + AD-838 wiring (78) green. Zero new deps.

### AD-818 v1 - Schema-version sidecar + boot-scan short-circuit for episodic migrations (Wave 205)

The boot path re-ran every one-shot episodic-memory migration (BF-103, AD-570, AD-570b, AD-584, AD-605) on every start, each scanning the full ChromaDB collection even when nothing had changed - O(N) per migration per boot, growing with episode count. AD-818 v1 adds a SQLite sidecar that records which migration ran at which version so the boot path can skip a migration whose recorded version matches the current code version, turning the per-boot full scan into an O(1) indexed lookup after the first run. New module src/probos/cognitive/schema_versions.py: MIGRATION_VERSIONS (a dict mapping exactly the five versioned migration ids to "1"; BF-207 the hash heal-sweep is intentionally absent because it is not a one-shot schema migration and must keep running every boot) carrying a BUMP CONTRACT comment - bumping a migration's value forces every store to re-run it exactly once, and failing to bump when output shape changes makes every store SKIP the corrected migration. SchemaVersionStore is an aiosqlite sidecar (table schema_versions: migration_id PRIMARY KEY, applied_at REAL, episode_count INTEGER, version_hash TEXT) mirroring the AD-570b ParticipantIndex Cloud-Ready-Storage pattern - an abstract connection_factory callable with an aiosqlite fallback only inside start(). Methods: async start/stop, async get(id) -> dict | None (Tier-2 log-and-degrade returns None on any read fault so a sidecar error never crashes boot), async record(id, *, episode_count, version_hash, applied_at=None) (INSERT OR REPLACE, auto-stamps time.time(), swallows write faults so a post-success write error simply re-versions next boot), async is_current(id, version_hash) -> bool (delegates to get, False on no row / hash mismatch / error). Short-circuit: startup/cognitive_services.py::_run_one_migration gained three optional kwargs (schema_store, migration_id, version_hash); when all three are set and is_current matches, the migration coro is never constructed (the scan is skipped, logs "schema current ... skipping scan" and returns). The version is recorded on CLEAN SUCCESS ONLY as the final statement INSIDE the try block (R1 - placing it after the try/except would reference the migrated count which is unbound on a TimeoutError path, raising UnboundLocalError and crashing boot, and would also falsely mark a timed-out migration current). The except asyncio.TimeoutError and except Exception clauses are unchanged - both still honest-degrade and record nothing, so a failed/timed-out migration retries next boot. A guarded build block (placed after the _skip_migrations guard, before the BF-103 call site) constructs the store only when episodic_memory and not _skip_migrations and config.memory.schema_version_tracking; a build or start failure leaves schema_store=None so every migration runs unversioned exactly as before AD-818. The five versioned call sites thread MIGRATION_VERSIONS[id]; BF-207 (sweep_hash_integrity) deliberately does not. The store is wired through CognitiveServicesResult.schema_version_store -> runtime.schema_version_store -> a guarded stop() teardown in startup/shutdown.py (R2 - the store has no other owner; left unstopped its WAL connection holds .db-wal/.db-shm locks, a Windows test-isolation hazard). Config: new MemoryConfig.schema_version_tracking: bool = False - opt-in for one release of bake time; a grandchild AD flips it True. Phased follow-ups deferred: AD-818a (pagination of the scan), AD-818b (probos migrate apply CLI), AD-818c (refuse-to-start gating on version mismatch). Tests: +16 pytest (tests/test_ad818_schema_versions.py) using real in-memory sqlite at the DB boundary, no MagicMock, per the Phantom-via-MagicMock rule - store CRUD/round-trip/auto-stamp/insert-or-replace/is_current matrix plus wrapper behavior (schema_store=None always calls; no prior row -> call + record; matching version -> skip; mismatch -> call + update; raise -> records nothing; timeout -> records nothing) and the MIGRATION_VERSIONS shape assertion. No migration function BODY changed; no ui/ changes; zero new deps.

### AD-818a - Paginate BF-103/AD-570/AD-570b episodic migrations + cancellable to_thread (Wave 206)

Issue #751 problems #2 (full-collection .get() loads every episode into memory at boot -> OOM risk) and #3 (async migrations with zero await cannot be cancelled by the boot wait_for timeout) for the three simplest one-shot migrations. New shared async helper episodic.py::_iter_collection_pages(collection, include, page_size=None) streams a collection page-by-page via await asyncio.to_thread(collection.get, include=, limit=effective, offset=offset), terminating when a page returns zero ids or fewer than the page size; page_size defaults to module-global _MIGRATION_BATCH_SIZE (2000) read at call time so tests can monkeypatch it small to force multi-page. BF-103 (episode-id mismatch), AD-570 (anchor index), AD-570b (participant index) were converted from full-load loops to `async for page in _iter_collection_pages(...)` with per-page batched writes through to_thread, giving genuine page-granular cancellability. Three migrations deferred: AD-584 (delete+recreate, write-path rearchitecture), AD-605, BF-207. Tests: real in-memory chroma, monkeypatched batch size. Commit 4cc722d1. #751 stays OPEN.

### BF-597 - Realign YEO conformance gates + BF-207 shutdown tests after prompt archive + AD-820 (Wave 206 hygiene)

Six pre-existing suite failures from two unrelated upstream commits. (a) commit 383dde25 archived 19 closed-issue AD prompts prompts/*.md -> prompts/archive/*.md, but four YEO conformance gates (test_ad758_program_gate, test_captain_invariant_exposure, test_delegation_policy, test_for_free_documentation) still read from prompts/ -> FileNotFoundError. Fix: a _prompt(name) resolver in each test that checks PROMPTS_DIR/name (or ROOT/prompts/name) first then falls back to .../archive/name. (b) AD-820 replaced the hardcoded 2s dream-cycle shutdown timeout (which tore ChromaDB's HNSW index, #750) with a configurable shutdown_consolidation_timeout_s budget (default 30s), but two BF-207 shutdown tests still asserted the literal 2s. Rewrote them to assert the configurable budget (test_dream_cycle_timeout_is_configurable, test_timeout_warning_mentions_consolidation_budget); dropped a "timeout=5.0 not in source" over-assertion because AD-824 background-task drain legitimately uses timeout=5.0. Test-only, 5 files, +62/-19. 27 passed. Commit 82931868.

### AD-818a-2 - Paginate AD-605 + BF-207 episodic migrations + cancellable to_thread (Wave 207)

Continues AD-818a for the two remaining read-streaming deferred migrations (#751 #2/#3). AD-605 migrate_enriched_embedding converted from a SYNC def (run via loop.run_in_executor, which asyncio.wait_for cannot cancel - the timeout fired but the thread ran on) to async def streaming via _iter_collection_pages with one batched await asyncio.to_thread(collection.update, ...) per page; the enriched_embedding_version>=1 short-circuit reads collection.metadata once before the loop, the version marker is set after the loop (idempotent, covers the empty-collection path), the safe_meta hnsw-key filter is preserved; its call site (cognitive_services.py) became a direct await (the now-unused _loop removed). BF-207 sweep_hash_integrity rewritten from a full-collection load + global timestamp sort (O(N) memory) to a bounded size-max_episodes (200) min-heap keyed by (timestamp, seq) where seq is a monotonic int tiebreaker so heap comparisons never reach the unorderable dict; on overflow heappop evicts the oldest, and the heap is DRAINED IN DESCENDING (timestamp, seq) order (REQUIRED: test_sweep_batches_multiple_mismatches asserts update ids newest-first ["ep-c","ep-b","ep-a"]) into a single batched update - O(200) memory, O(N) time, cancellable between pages, retaining the "heal the 200 most-recent" semantics. BF-207's internal try/except + internal logging were DROPPED so the now-wrapping _run_one_migration owns honest-degrade: its call site is wrapped in _run_one_migration WITHOUT schema_store/migration_id/version_hash (BF-207 is unversioned, runs every boot, gated by config.memory.verify_content_hash) and stays LAST. Architect review caught the heap-drain order flaw and the honest-degrade misreport (a retained internal swallow would let a real sweep failure return healed=0 and be logged by the wrapper as a clean "0 mismatches" noop). Five obsolete-contract tests updated to the new contract (4 AD-605 sync->async, 1 BF-207 exception now propagates). New tests/test_ad818a2_paginated_migrations.py (14 tests, real in-memory chroma, monkeypatched _MIGRATION_BATCH_SIZE, deterministic cancellability + heap-newest + descending-order pin). 133 passed across the new file + equivalence + AD-818a sibling suites. Commit 56d91cc8. Remaining #751 work: AD-818a-3 (AD-584 migrate_embedding_model temp-collection swap + rename - distinct write-path rearchitecture), AD-818b (probos migrate apply CLI), AD-818c (refuse-to-start version-mismatch gate). #751 stays OPEN.

### AD-858 - LLMPlanDecomposer: single goal -> validated WorkItemSpec DAG with expected_output contract (Wave 208)

First dependency-free unit of the Crew Collaboration epic (AD-859..862 deferred, they depend on the unbuilt AD-856). Adds a semantic counterpart to v1's MarkdownPlanDecomposer (src/probos/consultation/dispatch.py): src/probos/consultation/llm_decomposer.py::LLMPlanDecomposer structurally conforms to the existing sync PlanDecomposer Protocol (def decompose(self, markdown_text: str) -> list[WorkItemSpec]) and is a drop-in replacement - instead of parsing ATX-2 headings it asks an LLM to break a single free-text goal into a minimal DAG of sub-tasks with explicit depends_on edges and optional expected_output acceptance criteria. The Protocol stays SYNC and is NOT made @runtime_checkable; ParallelDispatcher.dispatch (dispatch.py line 423) and MarkdownPlanDecomposer are untouched. Sync->async bridge (load-bearing): dispatch() calls decompose() inline from inside the dispatcher's running event loop, so the async LLMClient.complete coroutine is driven on a dedicated single-worker thread that owns its own fresh loop (concurrent.futures.ThreadPoolExecutor(max_workers=1) + asyncio.run) - never asyncio.run/run_until_complete on the caller's already-running loop (would raise RuntimeError). The decomposer depends on a narrow _LLMClientLike Protocol (only async complete) via constructor injection (ISP + DI), not the concrete LLMClient. Honest-degrade (Tier-2, structured logging, never crashes dispatch): empty/whitespace goal, LLM exception, None response, LLMResponse.error set, malformed/non-array JSON, zero usable specs, or a dependency cycle all degrade to a single passthrough WorkItemSpec wrapping the whole goal; dangling/self depends_on edges are dropped and the DAG rebuilt (dangling-edge repair) before a WHITE/GREY/BLACK DFS cycle check. Fan-out is capped: configured max_subtasks (clamped to [1, 200] absolute ceiling) truncates excess; ids are slugged, de-duped, and depends_on normalised to tuples. JSON parsing tolerates leading/trailing prose and `json fences by slicing first [ to last ]. New optional WorkItemSpec.expected_output: str | None = None field (added AFTER metadata so positional construction stays backward-compatible; to_dict() carries it) records the per-task acceptance criterion. Config: ConsultationDispatchConfig (config.py) gains decomposer: Literal["markdown", "llm"] = "markdown", max_subtasks: int = 12, decomposer_tier: str = "standard" - all defaulted so zero-config boot is unchanged and v1 markdown decomposition stays the default; the fields are DEFINED only, dispatcher construction wiring is explicitly OUT of scope for AD-858. Tests: tests/test_ad858_llm_decomposer.py - 14 new using _FakeLLMClient/_RaisingLLMClient stubs (no MagicMock at the substrate boundary, no network): happy-path 3-spec chain, expected_output carried/omitted, dangling-edge repair, cycle->passthrough, max_subtasks enforcement (10->3), garbage/empty/error/raising-client all ->passthrough, fenced-JSON tolerance, structural-Protocol conformance (inspect.signature, not isinstance since not runtime_checkable), markdown still emits expected_output=None, and the critical bridge test (decompose() called synchronously from inside asyncio.run(_driver()) raises no RuntimeError). Focused gate 14 passed. Minor proactive deviation beyond the spec: LLMPlanDecomposer is also exported from src/probos/consultation/__init__.py (convention-aligned - MarkdownPlanDecomposer was already exported there). One commit, no push.

### AD-853 - Unified CapabilityRequest model + single approval queue (Wave 210)

First unit of the Crew Self-Unblock epic (AD-854..857 deferred - acquire-vs-build triage router, BLOCKED->resume work-item loop driver, AgenticLoop dispatch bridge, HXI/chat decision surface). Note: AD-853 is a previously-reserved lower number now implemented; the highest committed AD entry at build time was AD-858 (Wave 208), but the file is append-ascending so AD-853 lands at the tail as Wave 210. New top-level module src/probos/capability_request.py introduces a single approval queue spanning all three capability-need kinds so the Captain reviews ONE pending list instead of three divergent surfaces (tool grant / extension install / self-mod build). @dataclass CapabilityRequest (all fields defaulted): id (uuid4), agent_id (the stable AgentID trust-boundary key - NOT the identity.py DID ledger), kind: Literal["grant","install","build"], target (tool_id / skill name / capability description), rationale (truncated to _RATIONALE_MAX=280 matching the AD-718a budget), work_item_id: str | None, status: Literal["pending","approved","denied","fulfilled","failed"], created_at, decided_at, decided_by, decision_reason. CapabilityRequestStore(EventEmitterMixin) copies the verified ClearanceGrantStore DB+cache shape verbatim: cloud-ready ConnectionFactory Protocol (falls back to probos.storage.sqlite_factory.default_factory, NOT direct aiosqlite), async start() does connect + WAL/busy_timeout=5000/synchronous=NORMAL PRAGMAs + executescript(_SCHEMA) + commit + _refresh_cache, where _SCHEMA is the capability_requests table (id PK, agent_id/kind/created_at NOT NULL, target/rationale/status/decided_by/decision_reason defaulted, work_item_id/decided_at nullable) plus idx_caprequests_status and idx_caprequests_agent; async file_request(agent_id, kind, target, rationale="", work_item_id=None) inserts a pending row and emits CAPABILITY_REQUEST_FILED; async decide(request_id, approve, reason="", decided_by="captain") returns None+warn on unknown id (never raises), else sets status approved/denied + decided_at=time.time(), UPDATEs, and emits CAPABILITY_REQUEST_DECIDED; async list_pending/get and a static _row_to_request round-trip the 11 columns. Dual attribution + learning loop: decide() records the outcome against the per-agent trust ledger via the verified-real SYNC keyword signature trust.record_outcome(agent_id=req.agent_id, success=approve, weight=1.0, intent_type="capability_request", source="capability_request") (NOT awaited, NO positional source) wrapped in a Tier-2 log-and-degrade try/except - a denied/failed request is a negative trust signal, an approved one is provenance - while decided_by captures the Captain approver. AD-853's ONE legitimate divergence from the silent sibling: the store emits events (the sibling ClearanceGrantStore/ToolPermissionStore emit none) through EventEmitterMixin via an emit_event callback accepted at construction; events.py gained three EventType members under "# Capability requests (AD-853)": CAPABILITY_REQUEST_FILED/DECIDED/FULFILLED. Wiring: the store is constructed in startup/communication.py immediately after the ClearanceGrantStore block (no config gate, db_path = data_dir/capability_requests.db, emit_event=emit_event_fn), routed through the real CommunicationResult pattern rather than a direct runtime assignment - a capability_request_store field was added to startup/results.py (declaration-only, TYPE_CHECKING import) and runtime.py picks it up via four edits (TYPE_CHECKING import, class-body annotation, __init__ self.capability_request_store=None, and self.capability_request_store = comm.capability_request_store right after the clearance-grant assignment). trust_network is NOT in startup scope so it is left None at startup and late-bound in a future AD (acceptable per spec - the trust hook degrades cleanly when absent). Additive only: the existing vision/tool/extension proposal paths are untouched and migrate onto this store in AD-854. Acceptance: tests/test_ad853_capability_request.py - 8 tests against a real store fixture and a real TrustNetwork (NO MagicMock at the storage boundary per BF-287): file->pending, decide(approve)->approved + event, decide(deny)->denied, unknown-id->None, list_pending filters decided, persistence round-trip across two store instances on the same db_path, work_item_id carried through, and decide records a real trust outcome (asserts get_score moves). One commit, no push.

### AD-854 - Acquire-vs-build capability triage router (grant -> install -> build) + grant fast-path (Wave 211)

Second unit of the Crew Self-Unblock epic (built on AD-853's CapabilityRequest queue; AD-855..857 still deferred - BLOCKED->resume work-item loop driver, AgenticLoop dispatch bridge, HXI/chat decision surface). New module src/probos/cognitive/capability_triage.py splits a pure deterministic decision core from a thin async I/O driver. Pure triage(*, tool_registered, agent_has_permission, skill_known) -> Literal["grant","install","build"] picks the cheapest reversible rung mapped to the three governance axioms: grant=Minimal Authority (registered tool the agent lacks permission for - no new code), install=Reversibility Preference (a known skill/extension manifest - sandboxed/revocable), build=Safety Budget (novel capability - always Captain-gated). Pure evaluate_grant_fast_path(*, non_destructive, peer_precedent, agent_trust, trust_floor, fast_path_enabled) -> bool gates auto-approval of a grant: True only when ALL of fast_path_enabled AND non_destructive AND an in-department peer already holds the grant AND agent_trust >= trust_floor; install/build never call it. Async triage_and_file(...) resolves the three booleans from the live registries (tool_registry.get, _agent_has_permission via ToolPermissionStore.get_active_grants_sync, extension_registry.get_manifest), files an AD-853 CapabilityRequest (carrying work_item_id), then routes: grant -> _route_grant evaluates the fast path (derives the tool's required permission as the highest ToolPermission across its default_permissions matrix, non-destructive = not permission_includes(perm, WRITE), peer precedent from ToolPermissionStore.list_grants(active_only=True) filtered to in-dept non-self non-restriction holders via ontology.get_agent_department, trust from TrustNetwork.get_score - SYNC) and on pass calls store.decide(approve=True, decided_by="capability_triage") + ToolPermissionStore.issue_grant + store.mark_fulfilled, otherwise leaves pending; install -> always left pending for the Captain (no fast path); build -> _route_build delegates to self_mod_pipeline.handle_unhandled_intent (which owns its OWN approval gate - no double-prompt) and marks fulfilled only when the returned record.status == "active". Honest-degrades (Tier-2 structured warning, never crashes) to build when both registries are absent. CapabilityRequestStore gains async mark_fulfilled(request_id) -> CapabilityRequest | None (status -> "fulfilled", emits the pre-existing CAPABILITY_REQUEST_FULFILLED event; fulfilment is NOT a trust decision so no record_outcome here, unlike decide); unknown id returns None + warn. New CapabilityTriageConfig(grant_fast_path_enabled=False, grant_trust_floor=0.8 with a field_validator clamping to [0.0,1.0]) wired onto SystemConfig.capability_triage via default_factory - conservative defaults so the fast path is OFF and zero-config boot is unchanged. 22 new tests (pure truth tables, config defaults/validation, real CapabilityRequestStore + real ToolPermissionStore + real TrustNetwork for the async routes per the BF-287 no-MagicMock-at-storage-boundary rule, _Fake stubs only for the registries). One commit, no push.
