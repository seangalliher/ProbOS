> **Status (2026-10-20).** This review was requested by the Captain and written read-only against `main` at `45058ae7`. The Captain has since decided its open questions. **D3:** AD-1343 S1 finishes as it stands, and S2 and S3 are built on work tickets. **D2:** shadow mode first. M0, M3 (shadow mode only) and the refactors M1, M2, M5, M6, M8 and M10 are authorized now. M4 (enforcement) waits for the Captain's ruling on the shadow-mode evidence, and M7 and M9 stay paused. The plan is tracked in the epic **AD-1346, work-ticket admission ([#1601](https://github.com/seangalliher/ProbOS/issues/1601))**, which also records the ticket's lineage in object capabilities and the lessons from Kerberos as a prior system. Counts and line anchors are as of the review date.

# ProbOS Architecture Review: current state, target state, migration path

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20 (UTC; local date 2026-10-19)
**Requested by:** the Captain, 2026-10-20. Read-only review: nothing committed, no tracked file edited, no issue touched, `config/system.yaml` not modified (read only as committed, via `git show origin/main:`).
**Tree:** `D:\ProbOS` at `main` = `origin/main` = `45058ae7` (verified after `git fetch`). AD-1343 S1 read from its worktree `D:\ProbOS-worktrees\ad1343-45058ae7` (branch `feat/ad1343-20261019-45058ae7`, `04100dab`): contract plus Amendments A2 and A3. No throwaway worktree was needed, so none was created.
**Live vessel:** in stasis. `http://127.0.0.1:18900/api/health` refused the connection (curl exit 7); `shutdown_status.json` reads `"status": "clean"`. Live facts below come read-only from `%LOCALAPPDATA%\ProbOS\data` (SQLite opened `mode=ro`).

---

## 1. Executive summary

**Verdict.** The diagnosis behind the request is right, and the code shows it. ProbOS has good controls, but each one is enforced **where the work starts**, and work starts in many places. There are at least 10 dispatch seams by AD-1343's count, there is model work outside them, and every new control has to rediscover them. The fix is not one big gate in the middle. It has two parts:

1. **One admission decision per unit of work.** An in-process, I/O-free `AdmissionService.decide()` checks stop, lifecycle, identity, earned agency, scope, budget and the AD-698 policy hooks once, in a fixed order, and returns a **work ticket**.
2. **The ticket is required at the few sinks where work has an effect or a cost.** Those sinks are the model call, the tool registry, the effect broker, subprocess and egress. A sink does not decide policy again. It does an O(1) liveness check of the ticket (has it been revoked, has it expired, is the budget exhausted).

**Why both parts.** Sources are an open set and keep growing: AD-1343 round 1 missed three of them. Sinks are a small, closed set. The tool sink is already a single chokepoint, with 3 direct `invoke` calls in all of `src/`. A guard test can prove "every sink requires a ticket" structurally. It cannot prove "every source checks", because there are 1,089 `getattr(runtime, "...")` sites that a static census cannot follow. This is the internal form of the vessel pattern: the ticket is minted by the enclosing vessel and checked at the hull, so no harness, native or external, can skip it.

**Keep as is.** `ToolRegistry.check_and_invoke` as the single tool sink. AD-1316's permit model. AD-1328's command judging at `run_command`. AD-698's fail-closed `authorize_intent`. AD-1343's in-memory, no-I/O stop view. The AD-1270 decomposition plan (c1/c2/c3, d1/d2/d3). The rule in `overview.md:43-46` that agents decide what to work on and services decide only whether and when it may run.

**Migration.** The plan is 11 ordered steps (section 6). Steps M0 to M3, plus M6 and M8, are behaviour-preserving refactors or shadow-mode additions. Under my reading of the pause they are allowed, but M3 needs the Captain to classify it, because it is a new service. Enforcement (M4) is a safety control with the same standing as AD-1343's exemption. Arming dormant hard controls (M7) and the harness slot (M9) need the pause lifted. **The highest-value sequencing decision:** finish AD-1343 S1 as it stands, then build S2 (in-flight ownership and cancellation) and S3 (vessel-wide stop) **as the first users of the ticket**, not as a second round of seam patches.

**Cost and risk, roughly.** About 25 to 35 reviewed builds over the whole path. M0 to M4, the part that ends the "seam census per control" loop, is about 8 to 12 builds. Making the gate a single point of failure is avoidable by construction: it is a library, not a service, with no I/O on the hot path and fail-closed only for safety checks. The Captain's stop and lift routes, and the Ship's Computer's own maintenance work, stay outside admission, the same way Kubernetes excludes a webhook from its own admission path.

---

## 2. Current state (evidence)

### 2.1 Dispatch and admission

**Seams where agent work starts.** These come from AD-1343's census (S1 §10, A2, A3). On `main` none of them checks a stop, because the stop is not merged yet. I confirmed every function exists on `main` (§9).

| # | Seam (AD-1343 constant) | Entry function on `main` | Other controls checked there today |
|---|---|---|---|
| 1 | `SEAM_INTENT` | `CognitiveAgent.handle_intent` `cognitive_agent.py:7741` | AD-698 when reached through the bus or Dispatcher (`intent.py:1126`, `dispatcher.py:135,198`); **not** when called directly. There are 18 direct `.handle_intent(` call sites in 15 files, e.g. `proactive.py:1307,1319`, `commands_diagnostic.py:65`, `qualification_tests.py:58`, `sandbox.py:122`, `system_qa.py:328` |
| 2 | `SEAM_CONSULTATION` | `handle_consultation_request` `:8435` | none found |
| 3 | `SEAM_TOOL` | `ToolRegistry.check_and_invoke` `tools/registry.py:341` | rank/tool permission (`:261-336`); AD-1316 permit when armed (`:360-457`) |
| 4 | `SEAM_PROACTIVE` | `ProactiveCognitiveLoop._run_cycle` `proactive.py:1002` | earned agency `can_think_proactively` `:1044`; `ProactiveBudget` |
| 5 | `SEAM_WARD_ROOM` | `WardRoomRouter._route_to_agents` `ward_room_router.py:575` | earned agency `can_respond_ambient` `:909,937,1012`; `PostBudget` `ward_room_pipeline.py:290` |
| 6 | `SEAM_DM_ROUTE` | `_agent_chat_impl` `routers/agents.py:2940` | not established |
| 7 | `SEAM_GROUP_FANOUT` | `_fan_one_round._send_one_impl` `routers/thread_fanout.py:635` | not established |
| 8 | `SEAM_BROWSER_ACTION` | `ack_action` `routers/agent_actions.py:40` | Captain ack |
| 9 | `SEAM_AGENTIC_RUN` (A2) | `WorkItemAgenticExecutor.run` `agentic_dispatch.py:2591`; the crew verifier, synth and finalizer (A3) | `TurnCostBudget`, AD-1324 tier policy |
| 10 | `SEAM_DELEGATION` (A2) | `DelegateTaskTool.invoke` `delegate_task_tool.py:286` | `DelegationTreeBudget` `delegation_budget.py:167` |

S1 also lists named exceptions: `propose_appearance` and `propose_voice_profile` (Captain persona), `recover_promoted_turn` and `resume_promoted_turn` (S2 scope), and `stop`. Its scan **cannot see** an entry reached through an alias or `getattr`, a tool held under a name that does not end in `tool`, or a synchronous method that starts work (S1 §10 docstring). After A3 the census needs about 15 stop-check sites, 6 verifier check sites and 2 standing-stop sites (A3 §32).

**Model work outside the seams.** 82 `.complete(` calls on an LLM client, in 50 files. Among them: `dreaming.py`, `counselor.py`, `guided_reminiscence.py`, `procedures.py`, `skill_forge.py`, `builder.py`, `swe_harness/agentic_loop.py` and `agent_onboarding.py`. A3 had to classify, one by one, the model calls in four crew modules (`_CREW_MODEL_CALLS`). No such classification exists for the other modules. `LLMRequest.agent_id` exists, but it is "armed-only routing correlation (AD-1324)" and defaults to `None` (`types.py:324-327`). I did not measure how many of the 85 `LLMRequest(` constructions set it. **This is the largest unenforced surface**: it is where cost is spent and thinking happens, and a stop or budget at the seams does not reach it unless the caller happens to sit inside an admitted turn.

**Controls today: where each one lives, and its default.**

| Control | Where it is enforced | Default | Shape |
|---|---|---|---|
| Captain's stop (AD-1343) | 10 seams, about 15 sites (branch only) | n/a | point-of-use, census-guarded |
| Pre-intent policy (AD-698, BF-789) | IntentBus plus Dispatcher (`pre_intent_auth.py:93`; 35 bus call seams per `:76`) | on, fail closed | central for **intents only** |
| Tool permission (rank, grants) | `check_and_invoke` | on | **single sink** (3 direct invokes in `src/`) |
| Effect broker (AD-1316) | inside `check_and_invoke`, armed at `finalize.py:5597-5598` | **off**: `config.py:3812,3819`; committed `system.yaml:108-110` `enabled: false`, `profile: ordinary` | permit per effect |
| Command policy (AD-1328) | every `run_command`, `ShellCommandAgent`, red team (`command_gate.py:1-11`) | on (no rules means `NO_POLICY`) | at the sink |
| Earned agency | proactive and Ward Room only. `can_perform_action` (`earned_agency.py:401`) has **no production caller** (§9) | on | point-of-use |
| Budgets | at least 7 independent objects: `PostBudget`, `ProactiveBudget`, `DepartmentBudgetTable` (`finalize.py:4730`), `SpeculationBudget` (`:2715`), `DelegationTreeBudget`, `TurnCostBudget` (`turn_cost.py:124`), the LLM token bucket (`llm_client.py:1113`) | mixed | per surface, no common account |
| Scope and clearance | `ClearanceGrantStore`, plus separate grant stores. Live data has 6: `clearance_grants.db`, `department_tool_grants.db`, `intent_grants.db`, `skill_grants.db`, `tool_permissions.db`, `action_approvals.db` | on | fragmented |
| Egress (AD-456) | consumer opt-in: `http_fetch.py:200-311`, `a2a/client.py:79,131`, `mcp_bridge/bridge.py:46`. v1 is "consult only… does NOT actually intercept" (`egress.py:1-13`) | consult | not a boundary |
| Sandbox | `ContainerSandbox` has 2 consumers (`doctor`, `task_sessions/browser`). 31 files spawn subprocesses | n/a | not a boundary |
| Visiting builder policy | its own deny-by-default handler, BF-896 (`copilot_adapter.py:259`) | on | a second policy implementation |

**The repo already has five things named "admission" that are not one concept:** `DispatchAdmission` (substrate accepted, `types.py:105`), `AdmissionRequest/Decision` (protected execution, `execution/authority.py:481-495`), `PassAdmission` (`turn_promotion.py:272`), `CrewSessionAdmissionPort` (`workforce.py:1125`) and `PeerAdmission` (`federation/admission.py:51`). Any new gate has to name its relation to each of them. It should not add a sixth.

**A lesson the gate must inherit (AD-1276, `intent.py:1994-2022`).** Three adversarial reviews in a row broke an "already authorized" ledger in three different ways. The code concluded that "suppression is an optimization; enforcement is the fix", and accepted that a rate limiter is charged twice on a loopback. Applied to the gate: **stateful charges (budget reservations) happen once, at admission, keyed by a ticket id the peer cannot influence.** Sinks only read state.

### 2.2 Identity resolution

| Form | Example or source | Keyed on it |
|---|---|---|
| slot id (deployment) | `counselor_counselor_0_67c601cb` (`identity.py:790-791`) | trust (BF-907), ACM, the agent registry |
| sovereign UUID (birth certificate) | `get_by_uuid` `identity.py:773` | episodes (`episodic.py:463,472` `resolve_sovereign_id*`) |
| DID `did:probos:…` | parsed in `resolve_slot_id` `:816-820` | federation, visiting officers |
| asset-tag UUID | `_asset_slot_by_uuid` `:827` | assets |
| callsign | 43 files reference `callsign_registry` | UI, Ward Room, commands |
| agent_type | `get_by_agent_type` `:800` | pools, ontology |

- BF-907 added one resolution point, `AgentIdentityRegistry.resolve_slot_id` (`identity.py:804`), and injected it into `TrustNetwork` (`trust.py:281`). This is the right primitive, but only trust uses it.
- There are at least 18 other local resolvers: `agentic_dispatch.py:427,471`, `counselor.py:1610,2536`, `cognitive_agent.py:7941`, `commands_tool_access.py:282`, `commands_qualification.py:21`, `memory_probes.py:147`, `recreation/service.py:86`, `thread_fanout.py:362`, `standing_interests.py:360`, `fault_report.py:809`, `publish_finding_tool.py:500`, `billet_registry.py:124,129`, `clinical_telemetry.py:343`, `introspective_telemetry.py:55`, `runtime.py:2512`.
- 37 files use `sovereign_id`.
- **An inversion to note.** The durable self, the identity that carries over in a transfer or another embodiment (AD-443, AD-1342), is the sovereign UUID. The trust key is the deployment slot. BF-907 chose this deliberately for now. AD-1342's `embodiment` axis will reopen it (decision D4).

### 2.3 Startup and lifecycle

- **Phases.** `ProbOSRuntime.start` (`runtime.py:2677`, about 1,400 lines) runs Phase 1 infrastructure `:2742`, Phase 2 fleet `:2796`, Phase 3 organisation `:2825`, Phase 4 cognitive `:2853`, Phase 5 dreaming `:3064`, Phase 6 structural `:3113`, Phase 7 communication `:3157` (ACM assigned `:3299`), and Phase 8 finalize `:3461`. Agents are wired in Phase 2, five phases before ACM exists. That was BF-906's root cause, and it is now repaired by the level-triggered crew enroller (`startup/crew_enrollment.py:18`, `runtime.py:3450-3452`).
- **Things that can be None at a given phase.** 139 attributes are initialised to `None` in `ProbOSRuntime.__init__`. Whether each one is set is known only by reading phase code. There is no declared provides/requires.
- **Service locator.** 1,089 `getattr(runtime, "…")` sites in 144 files: `finalize.py` 222, `routers/agents.py` 65, `shutdown.py` 58, `cognitive_agent.py` 50, `agentic_dispatch.py` 45, `routers/crew.py` 44, `routers/system.py` 42. 224 `runtime._private` reads in 26 files outside `runtime.py`.
- **Late binding through private attributes.** 82 `x._attr = …` assignments in `startup/`, 55 of them in `finalize.py`. The comment "PATCH(AD-517)" survives at `finalize.py:5551-5558` (`onboarding._ontology`, `._ward_room`, `._start_time_wall`). Each one is a place where a service works only if a later phase remembers to patch it. That is BF-906's shape, and it is still open in general.

### 2.4 Modules and ownership

| Module | Lines | Size |
|---|---|---|
| `cognitive/cognitive_agent.py` | 12,651 | 630 KB |
| `workforce.py` | 11,979 | 550 KB |
| `cognitive/crew_session.py` | 7,119 | 297 KB |
| `runtime.py` | 6,874 | 319 KB |
| `startup/finalize.py` | 6,645 | 298 KB |
| `cognitive/episodic.py` | 5,267 | 247 KB |
| `proactive.py` | 5,093 | 259 KB |
| `cognitive/agentic_dispatch.py` | 4,440 | 206 KB |
| `config.py` | 4,113 | 199 KB |
| `cognitive/builder.py` | 3,750 | 173 KB |

22 modules are over 120 KB. The package has 1,043 `.py` files and the suite has 1,680 test files. The architecture checker passes with frozen debt: `srp-size=92, layer-import=0, db-connect=30, unowned-task=14` (run read-only with `--check` today). Layer imports are clean. Size and ownership are the debt.

**Duplicated paths (the BF-755 "two assemblies that drift" shape).** These are the instances visible in this review:
- AD-698's check existed only in the bus until BF-789 found the Dispatcher bypassing it.
- The tool offer had to be rebuilt by the same gate mid-turn (`agentic_dispatch.py:2932,3444,3532`).
- The visiting builder carries its own permission policy (BF-896) beside `ToolRegistry`/AD-1328.
- Trust lived in two stores: `trust.db` plus `knowledge/trust/snapshot.json` force-set on warm boot (BF-907 commit `e1d3c395`).

**Dormant capabilities.** AD-1270a's shadow inventory is unbuilt: 1 of 26 AD-1270 checklist items is done (#1324). There are 56 default-off `enabled: bool = False` flags against 104 default-on. The dormant controls named in this review are the effect broker, egress interception and `can_perform_action`.

### 2.5 Records and evidence

- **Live `events.db`:** 564 rows from 2026-10-12 to 2026-10-19, in 9 categories and 19 event names. Live `audit_log.db`: 17 rows. The code defines 394 `EventType` values. 37 are classified DURABLE (`event_persistence.py`; AD-1195), and 359 emit sites exist. **Most agent work leaves no service-captured durable record.** The durable record is what AD-1195 chose to persist, not a record of admission and effect.
- **Persistence only on shutdown.** `TrustNetwork.record_outcome` (`trust.py:372`) mutates memory. It is persisted by `stop()` → `_save_to_db()` (`trust.py:336-345`) or a manual `save()` (`:1216`), and `src/` has no periodic caller (§9). A crash loses every trust delta since start. Crew-session outcomes are the exception: they are durable once (`record_outcome_once` `:680`).
- **Storage sprawl.** 46 top-level `.db` files in the live data directory. 61 distinct `"*.db"` literals in `src/`. AD-1256 owns this.
- **Service-written vs agent-written.** Tool records (AD-1224) are written by `ToolExecutor`, which is service-captured. Episodes are written from inside the agent's own turn path, with `AnchorFrame` source anchors (`types.py:473-479`). AD-1342 child 6 names service-written memory as the target for harness crew. Native crew do not have it either.

### 2.6 The harness boundary

| Body | Policy it runs under | Identity | Record |
|---|---|---|---|
| Native (`CognitiveAgent`, `swe_harness`) | `ToolRegistry`, AD-1328; AD-1316 only if armed | slot id | tool records; agent-written episodes |
| Visiting builder (Copilot SDK, `CopilotBuilderAdapter` `copilot_adapter.py:322`) | its own BF-896 handler (`:259`) | not crew | log only |
| AD-701 visiting officers | scopes declared, **never enforced** (BF-903 #1581); off (`system.yaml:932-933` per #1582) | visiting DID | in-memory sessions |
| Inbound MCP (`federation/mcp_server.py`) | one shared bearer token bound to no DID (#1582) | none | none |
| Outbound MCP bridge (`integrations/mcp_bridge/`) | `ToolRegistry` | the caller's | tool records |

**What AD-1342 would need from this review:**
- a ticket the harness adapter receives and must present back through the MCP or tool sink (child 1: a credential bound to a DID);
- one policy path shared by native and harness bodies, with BF-896 becoming an adapter that maps SDK permission requests onto it;
- a service-written capture path (child 6).

Without the gate, each harness adapter becomes another set of seams for the census.

### 2.7 Why the recurring shape recurs

The controls are local and the obligations are global. Each control that "must hold everywhere" re-derives "everywhere":
- the stop, through AD-1343's census, three rounds;
- trust identity, BF-907 (three key forms);
- wiring, BF-906 (phase order);
- the pre-intent policy, BF-789 (Dispatcher bypass);
- egress, still consult-only.

The time profile (38% of orchestrator wall clock in review→repair loops, concentrated in these changes) is the cost of that re-derivation. A reviewer's job on such a change is to find the seam the author missed, and there is always one more.

---

## 3. Target state

### 3.1 Principles

1. **Controls live in the enclosing vessel** (vessel of vessels). Ship controls sit outside every crew member's harness. The crew member's own vessel holds its identity, memory and record. The federation's controls sit outside the ship.
2. **Decide once, check liveness at the sinks.** Stateful charges happen at admission only (the AD-1276 lesson).
3. **Enforce at the narrow side.** Sinks form a closed set and sources an open one. Guard tests prove properties of the closed set.
4. **Services decide whether and when; agents decide what and how** (`overview.md:43-46`). The gate never routes and never picks an agent.
5. **Behaviour-preserving first** (AD-1270): facades, shadow mode, parity, then enforcement.

### 3.2 Layers and the spine

```
                       Captain / people (approve, amend, stop, lift)
                                    |  (Captain routes: never admission-gated)
+-----------------------------------v------------------------------------------+
| FIXED SPINE (Ship's Computer; outside every harness; agents cannot change it) |
|                                                                              |
|  IdentityService ---- one IdentityRef per principal (slot|sovereign|DID|     |
|        |              callsign|embodiment), resolved once                   |
|        v                                                                     |
|  AdmissionService.decide(AdmissionRequest) -> WorkTicket | Denial           |
|    fixed order: vessel stop > agent stop > lifecycle (ACM) > identity >      |
|    earned agency (rank x work kind) > scope/clearance > budget reserve >     |
|    AD-698 policy hooks (overlay)            [in-process, sync, no I/O]       |
|        |                                                                     |
|  TicketRegistry -- live tickets, parent/child (delegation), revocation      |
|        |           generation; stop = revoke; expiry; budget accounts        |
|        |                                                                     |
|  SINKS (closed set, ticket required, O(1) liveness, no policy re-decision): |
|    LLM gateway (model calls) | ToolRegistry.check_and_invoke (+AD-1316 permit|
|    when armed, AD-1328 at run_command) | process spawn | egress | memory     |
|    write (episodes) | Ward Room/DM post                                      |
|        |                                                                     |
|  RECORD: service-captured, append-only: admission decisions, ticket         |
|    lifecycle, sink refusals, effects (AD-1195 DURABLE), trust write-through  |
|  EVALUATOR out of reach: AD-1338 fixed evaluator, AD-1336 verified closure,  |
|    gates and receipts run in the spine, never in the harness                 |
|  LIFECYCLE GRAPH: typed start/stop registrations with requires/provides     |
|    (AD-1270c2), level-triggered wiring (BF-906 pattern), no PATCH privates   |
+------------------------------------------------------------------------------+
        ^ ticket in                                     ^ ticket in
+-------+-----------------+   +-----------------+   +---+---------------------+
| Harness slot: NATIVE    |   | Harness slot:   |   | Harness slot: VISITING  |
| CognitiveAgent turn     |   | EXTERNAL (AD-   |   | (AD-701 / Copilot SDK)  |
| pipeline (AD-1270d3)    |   | 1342 adapter)   |   | adapter maps SDK perms  |
| hands: tools via sink   |   | hands via MCP   |   | onto the same sinks     |
+-------------------------+   +-----------------+   +-------------------------+
   portable hands = tools/skills (AD-1338), always invoked through the sinks
```

### 3.3 Admission contract (sketch for the future AD)

**`AdmissionRequest`** (frozen):
- `principal: IdentityRef`
- `work_kind`: a closed enum of turn, intent, consultation, proactive cycle, Ward Room reply, DM, fan-out, agentic run, correction round, delegation, crew subtask/verify/synth, dream, counselor session, build run, harness session, browser action, and Ship's Computer system work
- `origin`: Captain, agent (with parent ticket), schedule, federation peer (AD-1297 result), system
- `parent: TicketId | None`
- `scope`: requested tool and effect classes, data classification
- `budget_account` and an estimate
- `work_item_id`

**`decide()` returns** `WorkTicket` or `Denial(reason_code, check, detail)`, using one reason-code taxonomy shared with AD-1316 and AD-1343.
- **The ticket** is an unforgeable object, a capability: `id`, `principal`, `kind`, `scope`, `budget_account`, `parent`, `expires_at` and `revocation_generation`. A child ticket's scope and budget are a subset of its parent's (delegation narrows, never widens).
- **Escalate** is a third outcome: a request that needs the Captain's approval is filed in the AD-1154 inbox, as AD-1328 S2b does today.

**Enforcement by construction:**
- the LLM gateway's `complete()`, `ToolRegistry.check_and_invoke`, the process-spawn adapter and the egress adapter take a ticket;
- a guard test (the evolved census) asserts that every call to those primitives in `src/` passes one or holds a `system` principal from an allowlist that is itself pinned;
- a sink without a live ticket refuses, after a shadow period that counts instead.

**Revocation.** A stop increments the principal's revocation generation. Every sink check compares generations, so an in-flight run stops at its next model or tool call. That is AD-1343 S2's "in-flight ownership" without per-seam code.

**Failure modes:**
- stop, identity and scope fail closed;
- budget denies new work when an account is exhausted, but never cancels work in flight, and the Captain can override;
- AD-698 hooks keep their existing fail-closed rule (`pre_intent_auth.py:104-111`).

### 3.4 Not a bottleneck or a single point of failure, by construction

- **A library, not a service.** It runs on the dispatch loop with dict lookups and no awaits in `decide()`, so it needs no lock, like AgentStopService's design (S1 §1: "reads memory only").
- **Persistence is asynchronous and write-behind**, from memory views loaded at start. Budget reservations go to a small journal flushed on a timer and at stop. That avoids trust's shutdown-only mistake without putting I/O on the hot path.
- **Excluded from admission:** the Captain's stop and lift routes, health and status routes, and the gate's own startup. If the gate fails to construct, agent work is refused, but the Captain keeps control. This is the Kubernetes "exclude the webhook from its own admission" rule.
- **Risk: the stop record is a single point of truth.** If its in-memory view is wrong, every check is wrong at once. Mitigation: the views are rebuilt from durable records at start, and a crossing test proves record → view → sink.
- **Risk: shared fate.** One defect in `decide()` affects every kind of work. Mitigation: the decision order is a pinned table, every check is a small pure function with its own tests, there is a mutation campaign per check, and shadow mode measures disagreement before enforcement.

### 3.5 Where not to centralize

- **Routing and agent choice.** Agents decide (`overview.md:43`).
- **Command text judging.** It stays at `run_command` (AD-1328), because it needs the exact command and dialect. The gate passes scope, and the sink judges arguments.
- **Content and quality gates** (DM sanity gate, referent gate, crew verifier). These are cognition, not admission.
- **Domain SQL.** AD-1256's principle: storage registration does not centralize queries.
- **Federation peer admission** (AD-1297, `PeerAdmission`). It is a different trust boundary. Its result is an input (`origin`), not something the gate re-decides.
- **The five existing "admission" types.** `DispatchAdmission` (substrate acceptance), protected-execution admission and `PassAdmission` stay as they are. The gate sits above them and names the relationship.

### 3.6 One identity service

- `IdentityRef` is resolved once by an `IdentityService`, a facade over `AgentIdentityRegistry` plus the callsign registry plus the DID parser.
- It carries `slot_id`, `sovereign_id`, `did`, `callsign`, `agent_type` and later `embodiment`.
- Stores take an `IdentityRef` and choose their key through the service. The 18 local resolvers retire one family at a time.
- An architecture-checker rule, with a frozen baseline, forbids new raw-string identity parsing outside the service.

### 3.7 Explicit dependency graph (not a locator)

This is AD-1270c2's `startup/lifecycle.py`: typed registrations that declare `requires` and `provides`, started topologically and stopped in reverse. Late dependencies are wired level-triggered: a service that arrives later is pushed to its registered consumers, as BF-906's enroller does. That replaces the 82 private-attribute writes in `startup/`.

AD-1270c's **Do Not Build** stays: "a new global service locator, dependency-injection framework". Constructor injection remains, the graph is only the composition root, and `getattr(runtime, …)` reads shrink behind typed accessors one family at a time.

### 3.8 Records

- Admission decisions, ticket issue and revoke, and sink refusals become DURABLE `EventType`s, written by the spine and never by the agent.
- Trust becomes write-through (journalled per outcome, the same shape as `record_outcome_once`).
- Native episodes gain a service-captured source label, the same contract AD-1342 child 6 sets for harness crew. One contract covers every body.

---

## 4. What to keep

| Keep | Why |
|---|---|
| `ToolRegistry.check_and_invoke` as the only tool sink | It is already narrow: 3 direct `invoke` calls in all of `src/`. It becomes a ticket sink without moving |
| AD-1316 permit model; AD-1328 gate at `run_command`; AD-698 fail-closed evaluator | Sound designs. The gate composes them and does not replace them |
| AD-1343's `AgentStopService` record and in-memory view | It becomes the stop check inside `decide()` and the revocation source |
| AD-1343's AST census technique | It evolves into the sink-ticket guard test |
| BF-906 level-triggered enrolment | The model for every late binding |
| BF-907 `resolve_slot_id` | The seed of `IdentityService` |
| AD-1270 plan (c1/c2/c3, d1/d2/d3, a, b, e) | Already the right decomposition. This review adds the gate and identity work to it and does not fork it |
| Five-layer model and the "who decides what" boundary | The gate fits inside it |

---

## 5. Gap analysis

| Gap | Today | Target | Closed by |
|---|---|---|---|
| Work-start controls | about 10 seams, each checking separately; census by hand plus AST, three review rounds | one `decide()`; seams become thin callers | M0, M3, M4 |
| Model calls | 82 sites in 50 files, attribution optional | ticket required at the LLM gateway | M6 |
| In-flight stop | S2 open | ticket revocation | M4 (AD-1343 S2) |
| Vessel-wide stop | S3 open | first check in `decide()` | M4 (AD-1343 S3) |
| Budgets | 7 or more unrelated objects | accounts on the ticket; reservation at admission | M5 |
| Earned agency | 2 seams; `can_perform_action` dormant | one table of rank × work kind | M3 |
| Identity | about 19 resolvers, 6 forms | `IdentityRef` plus one service | M1 |
| Wiring | 82 private patches; 139 None-at-init attributes | lifecycle graph | M2 (AD-1270c2) |
| Hard effect controls | broker off, egress consult-only, sandbox unused by `run_command` | armed in the supported profile | M7 (pause, Captain) |
| Records | 37 of 394 events durable; trust saved only at shutdown | admission and effect record; write-through trust | M8 |
| Harness parity | BF-896 separate policy; MCP token bound to no DID | one sink path for every body | M9 (AD-1342, BF-903) |

---

## 6. Migration path

Pause classification is my reading of the evidence. The Captain's new-capability pause is cited on #1582:1 ("PAUSED… until the Captain lifts the new-capability pause") and #1595:1 ("Captain exemption from the new-capability pause, 2026-10-18: safety control"). I found no written definition of the pause in `PROGRESS.md`, `DECISIONS.md` or the orchestrator file (absence in §9), so the classifications below rest on those two issues.

| Step | What (behaviour-preserving unless stated) | Maps to | Unblocks | Size | Risk | Verify | Pause |
|---|---|---|---|---|---|---|---|
| **M0** | **Seam registry plus guard test** (the Captain's 2026-10-20 request): a machine-readable registry of every dispatch seam and its guard, and a structural scan for the agent-run entry primitives (`handle_intent` and the other public coroutines, `WorkItemAgenticExecutor.run`, `DelegateTaskTool.invoke`, `CrewTaskExecutor` run entry, crew verifier/synth/finalizer, direct tool `invoke`). It fails on a new or unguarded seam. **Add a second, report-only table: the classification of every `.complete(` site outside the crew modules**, so the model-call surface is visible before M6 | AD-1343 later slice (#1595, comment 2026-10-20T02:39Z) | makes bypasses visible; seeds M3's seam list | S, 1 build | false confidence from the scan's stated blind spots (alias, `getattr`) | mutation: delete a guard → fails; add a seam → fails | exempt (#1595) |
| **M1** | `IdentityRef` plus an `IdentityService` facade; migrate local resolvers one family per slice (telemetry, commands, counselor, Ward Room and fan-out, dispatch); checker rule against new ad-hoc resolution | BF-907 follow-ups on #1523; AD-1270c3 (one service family) | identity input for M3; AD-1342 embodiment | M, 3 to 5 builds | silently picking a different key form | parity tests per family: same key before and after, measured against the live stores read-only | refactor: allowed |
| **M2** | Lifecycle graph: `startup/lifecycle.py` with requires/provides; replace `PATCH(AD-517)` and the other private patches with level-triggered wiring, one phase per build | AD-1270c2, AD-1270c1 (#1324) | removes the BF-906 class; gives the gate a declared place in startup | L, 6 to 10 builds | startup order drift | startup event order parity; cancellation unwinds only started owners (c2 acceptance) | refactor: allowed |
| **M3** | **`AdmissionService` in shadow mode.** `decide()` is composed from the existing checks (stop view, ACM state, earned agency, clearance, budget readers, AD-698). It is called at every M0 seam **alongside** the current checks. It records disagreement and changes nothing | new AD, filed after AD-1343 S1 merges | measured parity before enforcement | M, 2 builds | shadow cost on hot paths (should be about microseconds; measure) | disagreement counter = 0 over a Ship Trial run (AD-1186); per-check unit and mutation | **Captain to classify (D2).** My recommendation: covered as a safety control, like AD-1343 |
| **M4** | **Work tickets and enforcement.** Seams call `decide()` in place of their own checks; tickets are threaded to the tool sink and agentic loop; stop = revoke. **AD-1343 S2 (in-flight) and S3 (vessel-wide) are built here** | AD-1343 S2, S3 (#1595) plus the M3 AD | ends the "census per control" loop | L, 4 to 6 builds | over-refusal of legitimate work; ticket threading misses a path | crossing tests: Captain stop → in-flight agentic run refuses at its next tool call; delegation child is revoked with its parent | safety control: AD-1343 exemption |
| **M5** | Budgets as accounts on the ticket: reservation at admission, metering at sinks; existing budget objects become account policies behind facades | M4 AD follow-on; AD-1324 tier policy | one place for cost limits; AD-1336 campaign budgets | M, 3 builds | double charge (AD-1276 lesson) | a ticket id the peer cannot influence; charge-once test across loopback | consolidation: allowed |
| **M6** | LLM gateway takes a ticket or a pinned `system` principal; shadow count, then refuse; attribution becomes complete (`LLMRequest.agent_id` always set) | M0 table; AD-1270d1/d3 | the stop and budget reach dreaming, counselor, builder and procedures | M, 2 to 4 builds | breaking Ship's Computer jobs that have no principal | per-module classification; zero unticketed calls in a Ship Trial | refactor plus safety: allowed |
| **M7** | Arm the hard controls in the supported profile: AD-1316 broker, AD-456b egress interception, sandboxed process spawn for `run_command` and code execution | AD-1185 supported profile; AD-1316 (#1383); AD-456b | the "sandbox/network" spine element becomes real | M each | regressions in agent capability; Windows sandbox limits | Ship Trials before and after | **needs pause lifted plus Captain (default change)** |
| **M8** | Records: admission, ticket and sink-refusal events DURABLE; trust write-through; service-captured source on native episodes | AD-1195 extension; AD-1270d2 (turn effects); trust as a BF at filing | an evidence record a harness cannot write | M, 3 builds | events.db volume | count producer vs consumer markers on the live vessel (empirical) | data integrity: allowed |
| **M9** | Harness slot: one adapter contract per body; BF-896 handler becomes the Copilot adapter over the sinks; MCP credential bound to a DID that carries a ticket | AD-1342 children 1, 6 and 9 (#1582); BF-903 (#1581) | crew in any harness under the same spine | L | identity spoofing at the boundary | AD-1342 child-1 retire test | **paused** (BF-903 is a bug and could go earlier under the safety framing) |
| **M10** | Continue the decomposition: `CognitiveAgent` turn pipeline (d3) is where the turn takes its ticket; runtime services (c3) | AD-1270c3, d1 to d3 (#1324) | smaller blast radius per change | L | prompt-byte drift | d-series acceptance (byte parity, call count) | refactor: allowed |
| **M11** | Self-maintenance runs under the gate: AD-1336 queue work and AD-1299 campaigns get tickets with Captain-approved scope; the AD-1338 evaluator runs in the spine | AD-1336 (#1558), AD-1299 (#1352), AD-1338 (#1565) | the "evaluator out of reach" spine element | M | evaluator access from the harness | evaluator unreachable through any sink by an agent principal | follows those issues' own status |

**Critical path:** M0 → M1 → M3 → M4, then M6. M2 runs in parallel with M1 if WIP allows, but it touches `finalize.py`, so it does not run concurrently with M3's wiring. M5 and M8 follow M4. M7, M9 and M11 wait for their decisions.

**Numbering.** The current highest is **AD-1344** (GitHub titles, `scripts/ad_ceiling.py`, run today), and the tool says next is AD-1345. **AD-1345 is already used by an unfiled draft** (`logs/drafts/ad-1345-harness-conformance-suite.md`, deferred by the Captain on 2026-10-19). The M3 AD should therefore be allocated at filing by rerunning `ad_ceiling.py` and skipping 1345 unless that draft is abandoned. No BF is proposed here. Trust write-through gets its number at filing.

---

## 7. Prior art (bounded)

`docs/research/reference-projects.md` checked first. OpenAI Agents SDK is listed as "never" reviewed, so it is overdue as of 2026-10-19. I used one search and one fetch on it. Kubernetes, OPA and object-capability security are not in the table.

| Source | What it shows | Decision |
|---|---|---|
| [OpenAI Agents SDK guardrails](https://openai.github.io/openai-agents-python/guardrails/) | Input guardrails run only for the first agent in a chain. Tool guardrails "do not apply to the handoff call itself". Hosted tools and built-in execution tools (`ComputerTool`, `ShellTool`) "do not use this guardrail pipeline". `Agent.as_tool()` does not expose them | **Reject as the model; absorb as the warning.** Guardrails inside the harness have exactly ProbOS's seam gaps. Enforcement belongs at the substrate sinks, outside the harness |
| [Kubernetes admission webhook good practices](https://kubernetes.io/docs/concepts/cluster-administration/admission-webhooks-good-practices); [failurePolicy](https://oneuptime.com/blog/post/2026-02-09-webhook-failure-policy-timeout/view), [death spiral](https://www.netdata.cloud/guides/kubernetes/kubernetes-webhook-death-spiral/) | One admission chain on the single write path (API server); `Fail` vs `Ignore` per webhook; exclude the webhook from its own admission or it deadlocks on recovery; stacked timeouts exceed deadlines | **Absorb:** fail mode per check (§3.3); Captain and gate routes excluded (§3.4). **Reject:** an out-of-process webhook (latency and network failure) |
| [OPA deployment](https://openpolicyagent.org/docs/deploy); [microservice authz survey, arXiv 2009.02114](https://arxiv.org/pdf/2009.02114); [OPA on Kubernetes](https://docs.styra.com/opa/deploy/k8s); [ONAP SDK vs sidecar](https://lf-onap.atlassian.net/wiki/x/zgBKBg) | PDP/PEP split; put the PDP as close to the PEP as possible (library or sidecar); a cluster-level PDP adds latency and is a single point of failure; cached decisions can go stale | **Absorb:** in-process PDP (`decide()`), PEPs at the sinks; staleness handled by the revocation generation in place of decision caching. **Reject:** Rego or OPA as a dependency (no need; Python checks with a pinned order) |
| Object capabilities ([Joe Duffy](https://joeduffyblog.com/2015/11/10/objects-as-secure-capabilities/), [confused deputy for agents](https://auth0.com/blog/confused-deputy-the-old-bug-that-ai-agents-keep-reintroducing), [MCP ambient authority](https://tianpan.co/blog/2026/05/07/mcp-ambient-authority-tool-chaining), [Semgrep](https://semgrep.dev/blog/2026/security-like-its-1977-capabilities-for-the-modern-agentic-web)) | Authority passed explicitly with the request, unforgeable and scoped; avoids ambient authority (an MCP session token covering every tool is the agent example); revocation and rotation are the cost | **Absorb:** the work ticket is a capability, child tickets attenuate, revocation via generation. This also answers BF-903 (inbound MCP's shared token is ambient authority) |
| Internal: AD-698/BF-789, AD-1276, AD-1316, AD-1328, AD-1343, AD-1270 plan, `overview.md` coordination model | §2 | **Reuse.** The gate composes them |

**Blind spots the request does not mention:**
1. Synchronous work starters and thread-origin emits (`_emit_from_any_thread` `runtime.py:1976`): the ticket needs a thread-safe liveness read.
2. Work started by federation peers: the origin must carry the AD-1297 result, and the ticket's principal is the peer's DID, not a local slot.
3. Scheduled and timer work has no human or agent parent, so it needs a defined principal.
4. Test doubles: `active_stop` accepts "whatever the seam holds" and only a real service answers (S1 §441-451). The ticket must not create a "no ticket means allowed" test path that leaks into production. Use an explicit `TestTicket` type, with production refusing it.
5. Holodeck and qualification runs (`qualification_tests.py:58`, `communication_benchmarks.py:218`) call `handle_intent` directly and need a `work_kind`.
6. Each new Denial is a new user-visible failure. AD-1248 disclosure and the AD-1257 defect counting must not count gate refusals as tool defects (the AD-1189 R2 lesson).

**Reference-projects row updates** (not applied, because tracked files are read-only here): set OpenAI Agents SDK to `2026-10-19 | checked | architecture review 2026-10-20 (guardrail coverage limits: first-agent input, handoffs, hosted and built-in tools)`. Consider adding rows for Kubernetes admission control and OPA (security and policy; interval 365 days).

---

## 8. Open decisions for the Captain

| # | Decision | Options (ranked) | Recommendation |
|---|---|---|---|
| D1 | Target shape | (1) one admission decision plus tickets required at sinks; (2) one gate at sources only; (3) keep per-control censuses | **(1).** (2) repeats the open-set problem; (3) is today's 38% |
| D2 | Pause standing of M3 (shadow) and M4 (enforcement) | (1) exempt as a safety control under AD-1343's framing; (2) M3 only now (shadow, no behaviour change), M4 after the pause; (3) wait | **(1).** M4 is how S2 and S3 get built. If not, **(2)** |
| D3 | AD-1343 sequencing | (1) S1 finishes as is; S2 and S3 built on M3/M4; (2) S2 and S3 as more seam patches, the gate later | **(1).** S2 (in-flight ownership) *is* ticket revocation. Cost: S2 lands about 3 to 5 builds later |
| D4 | Canonical durable identity key | (1) no store rekey now; `IdentityRef` everywhere; decide rekey when AD-1342 unpauses; (2) rekey trust to the sovereign id now | **(1).** BF-907 just settled trust on the slot id |
| D5 | Budget failure mode | (1) deny new work and never cancel in-flight, Captain override; (2) degrade open | **(1)** |
| D6 | Dependency graph form | (1) AD-1270c2 typed lifecycle registrations, no locator (as the AD-1270 plan already says); (2) a DI container | **(1).** Keep the AD-1270c Do Not Build |
| D7 | Arming hard controls by default (M7) | needs the pause lifted and AD-1185 | **The Captain's decision.** It changes defaults and can reduce capability. I recommend doing it after M4, so the arming is measured by Ship Trials |

**Required actions (not choices):** none.

---

## 9. Verified against codebase (2026-10-20, `main` 45058ae7)

```
git rev-parse HEAD origin/main          -> 45058ae7… (both)
wc -l (largest modules)                 -> table §2.4
grep -c getattr(runtime, "…") src/probos -> 1089 in 144 files (finalize.py 222, shutdown.py 58, cognitive_agent.py 50)
grep runtime\._[a-z] (excluding runtime.py) -> 224 in 26 files
grep "^\s+x._attr = " src/probos/startup -> 82 (finalize.py 55)
grep "self.x = None" runtime.py __init__ -> 139
runtime.py:2742,2796,2825,2853,3064,3113,3157,3299,3461   phase markers; ACM assigned :3299
finalize.py:5551-5558  PATCH(AD-517) onboarding._ontology/_ward_room/_start_time_wall
finalize.py:5597-5598  arm_effect_broker only if runtime.effect_broker is not None
config.py:3812,3819    ProtectedExecutionConfig enabled=False, effect_broker_enabled=False
git show origin/main:config/system.yaml :108-110  protected_execution enabled: false, profile: ordinary
tools/registry.py:341,360-457  check_and_invoke; broker permit
grep "[a-z_]*tool[a-z_]*\.invoke(" src/  -> 3
mesh/pre_intent_auth.py:93,104-111; intent.py:1126,2030; activation/dispatcher.py:135,198
intent.py:1994-2022    AD-1276 "suppression is an OPTIMIZATION; enforcement is the fix"
grep "\.handle_intent(" (excl. def) -> 18 sites in 15 files
grep "(llm_client|_llm|llm)\.complete(" -> 82 sites in 50 files; LLMRequest( -> 85
types.py:324-327       LLMRequest.agent_id/work_item_id, AD-1324 armed-only, default None
types.py:105; execution/authority.py:481,491; turn_promotion.py:272; workforce.py:1125; federation/admission.py:51  the five "admission" types
earned_agency.py:392,401; proactive.py:1044; ward_room_router.py:909,937,1012
security/egress.py:1-13 (consult-only); http_fetch.py:200-311; a2a/client.py:79,131; mcp_bridge/bridge.py:46
security/container_sandbox.py consumers: doctor/__init__.py, task_sessions/browser.py; subprocess-spawning files: 31
copilot_adapter.py:259,322 BF-896 handler; CopilotBuilderAdapter
identity.py:773,787,800,804-827 resolve_slot_id (BF-907); trust.py:281 _resolve_identity
trust.py:336-345 stop() saves; :372 record_outcome; :680 record_outcome_once; :1216 save()
event_persistence.py: 37 _DURABLE of 41 classified; events.py: 394 EventType values; 359 emit sites
check_architecture_principles.py --check -> passed (srp-size=92, layer-import=0, db-connect=30, unowned-task=14)
AD-1343 seam functions on main: cognitive_agent.py:5352,5370,7741,8435; proactive.py:1002; ward_room_router.py:575;
  routers/agents.py:2940; thread_fanout.py:635; agent_actions.py:40; agentic_dispatch.py:2343,2591;
  delegate_task_tool.py:88,286; crew_executor.py:1133,1885
scripts/ad_ceiling.py -> CEILING AD-1344 (GitHub titles), NEXT AD-1345 (but logs/drafts/ad-1345-* exists)
Live (read-only): events.db 564 rows, 2026-10-12..2026-10-19, 9 categories, 19 names; audit_log.db 17 rows; 46 top-level .db
```

## Absence verified (2026-10-20)

```
CLAIM: can_perform_action has no production caller
RUN:   grep -rnE "can_perform_action\(|can_think_proactively\(|can_respond_ambient\(" src/probos | grep -v "def can_"
FOUND: proactive.py:1044 (can_think_proactively); ward_room_router.py:909,937,1012 (can_respond_ambient)
HOLDS: yes, no can_perform_action call

CLAIM: nothing periodically persists general trust outcomes
RUN:   grep -rnE "trust_network\.save\(\)|_save_to_db\(\)" src/probos ; grep -rnE "trust_network\.save\b|trust\.save\(" src/probos
FOUND: trust.py:341 (stop), trust.py:1218 (save itself), mesh/routing.py:173,402 (routing's own store); second grep empty
HOLDS: yes, within these name forms; a caller holding the network under another name would not be seen

CLAIM: no written definition of the new-capability pause in the trackers
RUN:   grep -rniE "new.capability (work )?(is )?pause|capability pause|pause (on|of) new" PROGRESS.md DECISIONS.md docs/development/*.md
       and Grep "(?i)pause" .github/agents/orchestrator.agent.md
FOUND: none in the trackers; orchestrator.agent.md:106 is unrelated ("without an approval pause")
HOLDS: yes; the pause is known from #1582:1 and #1595:1 only

CLAIM: the stop is not on main
RUN:   git diff --stat 45058ae7 feat/ad1343-20261019-45058ae7
FOUND: only three prompts/ad-1343-*.md files differ (the source is staged in the worktree, not committed to main)
HOLDS: yes
```

**Uncertainty, stated:**
- Gate overhead is unmeasured. The design keeps it to dict lookups, and M3's shadow mode measures it.
- Build counts are rough, from the size of comparable ADs (AD-1343 S1 is 1 slice and 3 review rounds; BF-906 and BF-907 are 1 build plus 2 to 3 amendments each).
- I did not measure how many LLM calls are attributed, or how many of the 82 model call sites run outside an admitted turn. M0's report-only table produces that number.
- The seam list depends on AD-1343's census and its stated blind spots.
