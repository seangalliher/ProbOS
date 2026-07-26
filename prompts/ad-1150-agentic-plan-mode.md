# AD-1150 — Agentic plan mode: plan → approve → execute (cognitive / swe_harness / hooks / workforce)

**Issue: #1075 · Epic #1068 (harness parity) · explicitly "lowest priority in the epic".**
**Repo: OSS (`d:\ProbOS`). This AD = **AD-1150** (#1075, pre-allocated by the issue — no new number needed). HEAD at investigation: `b766254e`. AD ceiling: **AD-1151**. BF ceiling: **BF-680**. Next free: **AD-1152 / BF-681**. AD-1150 has zero references in `PROGRESS.md`, `DECISIONS.md`, or `docs/development/roadmap.md`.**

---

## ⛔ VERDICT — **DEFER. Do not build.** Close #1075 as not-planned.

**AD-1150 as specified is a sixth approval surface wearing the costume of a reuse.** Issue #1075's central claim — *"the state machine, the UI, and the gate mechanism all exist; what is missing is a mode"* — is **two-thirds true and one-third false**, and the false third is the entire load-bearing part.

| #1075 claims | Status at `b766254e` | Consequence |
|---|---|---|
| The step **state machine** exists | ✅ **True.** `STEP_STATUSES` (`workforce.py:1800`), `validate_step_transition` (`:1812`) | Reusable. Nothing to build. |
| The step **UI** exists | ✅ **True.** `TodosList.tsx`, seeded via `set_steps` (`:3020`) | Reusable. Nothing to build. |
| The **gate mechanism** exists — *"`ask` is already a supported verdict"* | ❌ **FALSE.** `ask` is an enum member and an integer rank. **Zero** production code resolves it. | **The gate is the whole AD.** Building it *is* the sixth surface. |
| Plan representation should reuse `WorkItem.steps` | ✅ Correct, and already does — `gate_completion=True` (`reply_pipeline.py:1354`, `:1437`) | Already shipped. |
| Rejection must not add a `stopped_reason` value | ❌ **Impossible.** No existing value is correct. | Acceptance criteria are **self-contradicting** (see Correction 3). |

Three findings, each independently sufficient to defer. Together they are decisive.

---

## The six existing surfaces — reuse / extend / bypass, stated explicitly

The Captain asked for a per-surface verdict. Here it is, verified.

| # | Surface | Evidence | AD-1150 verdict |
|---|---|---|---|
| 1 | **`/design` → `ArchitectProposal` → Captain approve → `BuilderAgent`** (AD-306/308/311+) | `routers/chat.py:69` (`/design`), `cognitive/architect.py:30` (`ArchitectProposal`), `routers/design.py:47` (*"Approve architect proposal — forwards embedded BuildSpec to builder"*), `routers/build.py:43` (`POST /approve`) | **Already is plan→approve→execute.** Scoped to *builds*. AD-1150 would **duplicate its shape** for arbitrary work. |
| 2 | **CrewSession plan seeding + `plan_seed_hash`** | `crew_session.py:432` (field), `:1133` (`_final_plan_hash`), `:1174` (seed hash), `:1574`/`:1590` (recovery re-derivation) | Plans are **already persisted, hash-identified objects with a recovery contract.** AD-1150 must **not touch** this (`description` is inside the identity hash). |
| 3 | **Consensus / quorum gating** | `consensus/quorum.py`, `requires_consensus` on destructive intents | **Deliberately bypassed** — per-call safety, not plan-level intent. Orthogonal, correctly so. |
| 4 | **`AgentNotification.suggested_action` + `POST /api/notifications/{id}/accept`** (AD-1053) | `notifications.py:33-44`, `routers/system.py:427` (`accept_notification`) | **The only correct approval affordance for this**, and the one #1075 does not mention. It dispatches a **pre-authored** action — exactly the "approve a plan" shape. |
| 5 | **AD-1080/1081/1085a step checklist** | `workforce.py:1800`/`:1812`/`:3020`/`:3062`/`:3101`, `todo_extractor.py:35-42`, `:113` (`derive_prose_plan`), `reply_pipeline.py:1345`/`:1350`/`:1354`/`:1437` | **Already plan-gated execution**, at the *completion* boundary: `gate_completion=True` ⇒ the item cannot reach `done` until every step is senior-confirmed. |
| 6 | **AD-855 `CapabilityGapDriver`** — `BLOCKED → request → approve → resume` | `cognitive/capability_gap_driver.py:1-18` | **The pause/approve/resume architecture already exists**, event-driven, wired to work items. #1075 does not mention it. A seventh variant is indefensible. |

Bonus: `governance/decision_queue.py:19-25` (AD-445) is a `PENDING/APPROVED/REJECTED/DEFERRED/EXPIRED` queue with pause/resume. That is **seven**.

**Conclusion:** every component AD-1150 needs exists — but **assembled around a different execution model** (work items and builds, which are durable, resumable, event-driven). `AgenticLoop` is none of those things. See Correction 2.

---

## ⛔ CORRECTION 1 — `HookBus.ask` is an enum value with **zero** resolution machinery. Reusing it means building it.

#1075: *"**Reuse `HookBus`** for the approval gate rather than a new mechanism; `ask` is already a supported verdict."*

`ask` is a supported **verdict**. It is not a supported **gate**. Verified:

```
hooks/bus.py:66-68     ALLOW / ASK / DENY enum members
hooks/bus.py:71-75     _DECISION_ORDER — ASK ranks 1, between allow(0) and deny(2)
hooks/bus.py:108       AggregateDecision.asked property
hooks/bus.py:176-201   fire() → returns AggregateDecision. Synchronous aggregation, returns immediately.
```

`fire()` runs handlers, ranks their verdicts, returns. It **cannot suspend, cannot persist a pending question, cannot notify a human, cannot wait, cannot resume.** There is no store, no correlation id, no timeout, no resolution API.

The **only** production consumer of `fire()` in the entire tree:

```
reply_pipeline.py:964-976
    decision = await hook_bus.fire(HookEvent.PRE_DISPATCH, {...})
    blocked = decision.denied          # ← reads .denied ONLY
```

`AggregateDecision.asked` has **zero production consumers**. At HEAD, an `ask` verdict is behaviourally **identical to `allow`** — it does not block anything.

Two further facts:

* `AgenticLoop` **has no `HookBus` wiring at all.** `hook_bus` appears in `runtime.py:2898`, `startup/communication.py`, `startup/finalize.py:3768`, `startup/results.py:179`, `startup/shutdown.py:920`, `reply_pipeline.py:964` — and **nowhere** in `swe_harness/`. `PRE_TOOL_USE` (`bus.py:48`) is declared and **never fired.**
* Hooks are **default-OFF and the bus is `None`**: `startup/communication.py:585-596` — *"Off by default (`config.hooks.enabled=False`) -> hook_bus stays None"*.

So "reuse `HookBus`" resolves to: **build an ask-resolution mechanism (pending store + human surface + wait + resume), fire `PRE_TOOL_USE` for the first time, and gate it behind a second default-OFF flag.** That mechanism *is* the new approval surface the Captain forbade — it just inherits an enum.

---

## ⛔ CORRECTION 2 — `AgenticLoop.run()` cannot suspend, and #1075 forbids the only sound way to make it

`AgenticLoop.run()` (`agentic_loop.py:765`) is a single in-memory async call. Every piece of loop state is a **local**:

```
agentic_loop.py:789    result   = AgenticResult()
agentic_loop.py:790    messages = [ {system}, {user} ]
agentic_loop.py:795    tool_id_history: list[str] = []
agentic_loop.py:799    token_sources: set[str] = set()
agentic_loop.py:803    for iteration in range(1, self._max_iter + 1):
```

Nothing is persisted, nothing is keyed, nothing is reconstructable. There are exactly two ways to insert a human between plan and execution:

**(a) Suspend inside `run()` and await the human.** This holds a live `asyncio` task — with an open LLM client, a populated `self._tasks` set (`:764`), and, on the crew path, **a fan-out semaphore permit** — across arbitrary human latency (minutes to days). #1075's own acceptance says *"Crew fan-out is not stalled by per-child approval gates."* Approval at the **parent** stalls it just as hard: the parent holds the session while every child waits on a plan nobody has looked at.

**(b) Terminate after the plan, start a fresh `run()` after approval.** Sound — and it makes AD-1150 **unnecessary**, because that is a *caller* concern, not a loop concern. It is precisely what surface #1 (`/design` → approve → `execute_approved_build`) already does, and what surface #6 (`CapabilityGapDriver`) already does event-driven.

(b) needs the loop to hand back enough state to resume ⇒ **checkpointing.** #1075's own *Do NOT build* list ends with: *"streaming or **checkpointing**."*

**The issue forbids the only sound implementation of the thing it asks for.** That is not a scoping detail; it is the AD contradicting itself.

---

## ⛔ CORRECTION 3 — "a distinct outcome that does not introduce a new `stopped_reason`" is impossible. No correct value exists.

#1075 acceptance: *"rejection terminates cleanly with a distinct outcome that does **not** introduce a new `stopped_reason` value (the evidence builder maps them exactly, `crew_executor.py:258`)."*

The frozen set (`crew_executor.py:51-63`) and the success rule (`:49-50`):

```
_SUCCESS_STOPPED_REASON = "complete"
_STOPPED_REASONS = { complete, error, max_iterations, token_budget,
                     execution_exception, unassigned, agent_unresolvable,
                     dependency_blocked, ... }
crew_executor.py:605, :1628   reason if reason in _STOPPED_REASONS else "error"
```

Enumerate the candidates for *"the Captain read the plan and said no"*:

| Candidate | Result | Verdict |
|---|---|---|
| `complete` | `_SUCCESS_STOPPED_REASON` ⇒ subtask `done` ⇒ **dependents unblock** on work that never ran | ❌ Corrupts the DAG |
| `error` | A correct human decision is recorded as a **failure**; poisons trust/Hebbian/evidence | ❌ Lies in the record |
| `max_iterations` / `token_budget` | Factually false | ❌ |
| `execution_exception` | Nothing was thrown | ❌ |
| `dependency_blocked` | No dependency involved | ❌ |
| *(fall-through)* | `:605`/`:1628` coerce unknown → `"error"` | ❌ Same as `error` |

There is **no correct existing value**, and the acceptance criteria forbid adding one. A rejected plan is a *fourth* terminal class — neither success, nor failure, nor resource exhaustion — and the frozen 14-key `crew_execution` evidence contract has no room for it.

Resolving this requires either amending `_STOPPED_REASONS` (which #1075 forbids and which the AD-1142 contract freeze protects) **or** keeping rejection entirely outside the loop's result type — i.e. **at the caller**, i.e. Correction 2(b), i.e. AD-1150 is not a loop AD.

---

## Correction 4 (secondary) — the two highest-value cases are already covered, and neither is `AgenticLoop`

#1075 concedes its own scope: *"plan mode is most valuable for **1:1 conversational** work and for the crew **parent** plan, not for every child."* Both are already handled, and neither lives in `AgenticLoop`:

**1:1 conversational (`dm_agentic`).** `_maybe_run_conversational_agentic` runs **inside a single `direct_message` turn** (`cognitive_agent.py:3325-3341`). The Captain sent the message and is blocked on the reply. **The human is already at every turn boundary.** The Captain can already write *"plan first, don't execute"*; the agent already has `[TODOS]` (`todo_extractor.py:35`) which lands as `set_steps(..., gate_completion=True)` (`reply_pipeline.py:1354`, `:1437`), and AD-1085a `derive_prose_plan` (`:113`) even recovers a plan when the agent narrated steps without tagging them. Adding an approval round-trip inside a turn that is *already* a round-trip is a null gain.

**Crew parent plan.** Built in `crew_session.py` — decomposition, `plan_seed_hash` (`:1174`), `_final_plan_hash` (`:1133`). That is **not** `AgenticLoop`. An AD that adds "a plan phase to `AgenticLoop`" cannot reach its own stated highest-value case.

---

## Pinned design decisions — for whenever this is unblocked

These are the decisions the Captain asked for. They are recorded so a future build does not re-litigate them, **not** because a build is authorised.

### DD-1 — Gating: the gate mechanism does not exist, the loop cannot suspend, and rejection has no representable outcome ⇒ **defer**
Any one of Corrections 1–3 defers it. All three hold at `b766254e`. This DD is the verdict; DD-2…DD-10 are conditional on §Unblock.

### DD-2 — Which loop: **none of the three.** Plan-approval belongs at the **caller**, not in `AgenticLoop`
- **SWE harness** (`native_builder.py:99`): already behind `/design` → approve → `execute_approved_build`. Covered by surface #1. **Excluded.**
- **Crew child** (`crew_executor.py:1407` → `agentic_dispatch.py:1006`): #1075 itself excludes it (fan-out stall). **Excluded.**
- **Crew parent**: real gap — but `crew_session.py`, not `AgenticLoop`. **Different AD.**
- **`dm_agentic`** (`cognitive_agent.py:3325`): human already turn-gated. **Excluded** (Correction 4).

⇒ `AgenticLoop` gets **no plan phase**. If anything is ever built, it is a `CrewSession` pre-execution gate.

### DD-3 — What a "plan" is: `WorkItem.steps`, unchanged
`set_steps(work_item_id, [...], gate_completion=True, facilitator=...)` (`workforce.py:3020-3059`). Normalised `{label, status}` dicts, `pending` by default, `steps_gate_completion` in metadata (`:3055`, enforced `:3101`). **No new structure. No new model. This is already shipped and already correct** — #1075 is right about this and it costs zero.

### DD-4 — Where approval is surfaced: **AD-1053 notification + accept. Not a new endpoint, not `HookBus`.**
`AgentNotification.suggested_action` (`notifications.py:44`) carries a pre-authored action; `POST /api/notifications/{id}/accept` (`routers/system.py:427`) dispatches it. That is a plan-approval affordance with a shipped HXI button. `HookBus` is explicitly **rejected** as the surface (Correction 1): it can neither wait nor resume, and pressing it into service means writing the sixth gate.

### DD-5 — On rejection: the plan is **abandoned**, the loop **never started**, and no `stopped_reason` is produced
Rejection must be represented **before** any `AgenticResult` exists — as a work-item transition (`rejected` is already in `STEP_STATUSES`, `workforce.py:1800`; `submitted → rejected` is already a legal transition, `:1806`). **No re-plan.** A re-plan loop is an unbounded LLM spend with a human in the critical path and no convergence proof; if the Captain wants a different plan they ask for one, which is a new turn. This is the only formulation that satisfies #1075's "no new `stopped_reason`" — by never reaching the loop at all.

### DD-6 — The three frozen crew contracts are untouched, and this is why persistence is hard
`plan_seed_hash` is `sha256` over a canonical projection that **includes `description`** (`crew_session.py:1174`, re-derived on recovery at `:1574`). A plan that is *edited* during approval changes `description` ⇒ changes `plan_seed_hash` ⇒ **breaks the AD-1124/AD-1127 recovery contract** and orphans `_derived_child_id` (`:1121`). ⇒ **Approval is accept/reject only. Editing a plan is out of scope permanently**, not merely deferred. The 14-key `crew_execution` set and the frozen 12-field `SubtaskResult` gain nothing.

### DD-7 — Approver rank: reuse `room_todos_min_rank`, do not invent a policy
`config.py:5572` (`room_todos_min_rank`, default `"commander"`) + the AD-1082 split at `:5578` (**seeding** open to any crew so the asked agent can plan; **confirm/reject** at `room_todos_min_rank`), resolved by `_todo_actor_meets` (`reply_pipeline.py:1368`). Captain-plus-senior-delegable, already configured, already tested. **Zero new config for the approver question.**

### DD-8 — Default posture: not applicable, because nothing ships
Were it built: default-OFF, byte-identical when off, pinned in `PINNED_AGENTIC_LOOP` (which feeds `config_fingerprint`) and **not** in `sigma_flags.py` — per the AD-1142 precedent. Note the compounding cost: `HookBus` is *already* default-OFF (`config.hooks.enabled=False`, `startup/communication.py:585`), so a HookBus-based AD-1150 would be **two default-OFF flags deep** — the AD-1149 DD-5 objection, verbatim.

### DD-9 — Interaction with AD-1146/1147/1148/1151/1142: **none, by construction**
Because DD-2 puts the gate at the caller and DD-5 keeps rejection out of `AgenticResult`, no shipped loop semantics move. Any design that instead pauses *inside* `run()` collides with all five: it would suspend mid-AD-1147-group (breaking the `align_to_group_start` whole-group invariant AD-1142 depends on), strand an AD-1151 partial trace, and hold an AD-1146 structured history open indefinitely.

### DD-10 — Consensus stays orthogonal
Plan approval is **intent-level and advisory**; consensus is **per-call and safety-critical** (`requires_consensus=True`). A plan approved by the Captain does **not** pre-authorise the destructive calls inside it — each still faces quorum. No consensus-layer change, ever, in this AD.

---

## Unblock — exactly what must change before AD-1150 is worth revisiting

**All four. Any one unmet ⇒ still deferred.**

1. **A resolvable `ask` exists.** Something in the tree suspends on `HookDecision.ASK`, persists the pending question with a correlation id, surfaces it, and resumes on a human answer — with a timeout and a default. Today: **zero consumers of `.asked`**. Until this exists, "reuse `HookBus`" is a category error.
2. **`AgenticLoop` can resume from persisted state** — i.e. checkpointing lands (currently on #1075's own *do-not-build* list), **or** the design is restated as a `CrewSession` pre-execution gate that never enters the loop (DD-2), in which case the AD needs a new title and a new issue.
3. **The `stopped_reason` contradiction is resolved** — either an explicit amendment to `_STOPPED_REASONS` with the 14-key `crew_execution` consequence costed, **or** written acceptance of DD-5 (rejection is a work-item transition and produces no `AgenticResult`).
4. **A demonstrated failure the existing surfaces do not catch.** Concretely: a crew parent plan that was *wrong at seed time*, that `gate_completion=True` did not stop, that `/design` approval did not cover, and that a Captain reading the AD-1053 notification would have rejected. **Zero such incidents in `PROGRESS.md` at `b766254e`.** #1075's stated motivation — *"an agent confidently doing the wrong thing for 25 iterations"* — is a **budget** problem, and AD-1142 (per-child compaction + `crew_token_budget`) and AD-1147/1148 (bounding) already address the cost half. The *correctness* half is what senior validation (AD-1080) exists for.

---

## What to build IF and ONLY IF §Unblock is satisfied

Not this AD. File a **new** AD against `CrewSession`, scoped as:

> Before `CrewSession` dispatches its first child, emit an `AgentNotification` whose `suggested_action` carries the plan (`plan_seed_hash` + step labels). Hold dispatch. `POST /api/notifications/{id}/accept` releases it; rejection transitions the parent work item and dispatches nothing. Accept/reject only — **no editing** (DD-6). Approver rank from `room_todos_min_rank` (DD-7). Default-OFF.

That touches `crew_session.py`, `notifications.py`, and `routers/system.py` — and **not** `agentic_loop.py`, **not** `hooks/bus.py`, **not** `_STOPPED_REASONS`. It is a different AD with a different title, and it must still clear §Unblock item 4 (a real incident) before it is worth the flag.

---

## Do NOT build here

A sixth approval surface when six exist (`/design` approve · `CrewSession` plan hash · consensus · AD-1053 accept · AD-1080 `gate_completion` · AD-855 gap driver — plus AD-445 `DecisionQueue`) · an ask-resolution mechanism inside `HookBus` · a new todo/step data model · a new approval endpoint · a new approval UI · plan approval inside any crew child · any change to `_STOPPED_REASONS` · any change to the three frozen crew contracts (14-key `crew_execution`, frozen `SubtaskResult`, `description` inside `plan_seed_hash`) · any change to AD-1146/1147/1148/1151/1142 semantics · consensus-layer changes · checkpointing or streaming · **any production source edit, any test file, and any test run** — this document is a spec-review artefact only.

---

## Files (verify each at build — none are modified by this AD)

| Path | Why it matters |
|---|---|
| `src/probos/hooks/bus.py` | `ask` has no resolver (Correction 1) |
| `src/probos/cognitive/dm/reply_pipeline.py` | The only `fire()` consumer, reads `.denied` only; also the `set_steps` call sites |
| `src/probos/startup/communication.py` | Hooks default-OFF, bus is `None` |
| `src/probos/cognitive/swe_harness/agentic_loop.py` | `run()` state is local; no suspend |
| `src/probos/cognitive/crew_executor.py` | Frozen `_STOPPED_REASONS` (Correction 3) |
| `src/probos/cognitive/crew_session.py` | `plan_seed_hash` recovery contract (DD-6) |
| `src/probos/workforce.py` | `STEP_STATUSES`, `set_steps`, `gate_completion` (DD-3) |
| `src/probos/cognitive/dm/todo_extractor.py` | `[TODOS]` / `derive_prose_plan` (Correction 4) |
| `src/probos/notifications.py`, `src/probos/routers/system.py` | AD-1053 accept (DD-4) |
| `src/probos/routers/design.py`, `src/probos/routers/build.py` | Surface #1 (already plan→approve→execute) |
| `src/probos/cognitive/capability_gap_driver.py` | Surface #6 (already pause→approve→resume) |
| `src/probos/config.py` | `HooksConfig:3244`, `AgenticLoopConfig:4369`, `DmAgenticConfig:6022`, `room_todos_min_rank:5572` |

---

## Validation plan — **no tests. No test run.**

**The full suite must NOT be run, and neither must any subset.** This AD produces **zero source and zero test changes**, so there is nothing to validate. The only artefact is this document.

Were §Unblock ever satisfied, the targeted files would be — named here so a future build does not have to rediscover them, **not to be run now**:

| File | Exists at HEAD | Would cover |
|---|---|---|
| `tests/test_ad1004_hook_bus.py` | verify | `ask` resolution semantics |
| `tests/test_ad1080_work_item_steps.py` | verify | step machine / `gate_completion` |
| `tests/test_ad1081_todo_tags.py` | verify | `[TODOS]` parse/apply |
| `tests/test_ad1053_notifications.py` | verify | `suggested_action` accept dispatch |
| `tests/test_ad1142_crew_child_compaction.py` | ✅ (AD-1142) | crew-contract byte-identity |
| `tests/test_ad545_agentic_loop.py` | ✅ (touched at HEAD) | loop default-OFF identity |

Builder must confirm existence and exact names before relying on any row (see Builder checks).

---

## Builder checks (unverifiable from this spec — confirm before relying on them)

1. **Test-file names in the table above are unverified.** They were inferred from AD numbers, not globbed. Confirm with `Get-ChildItem tests -Filter 'test_ad1004*','test_ad1080*','test_ad1081*','test_ad1053*'` before citing them.
2. **`TodosList.tsx` / `WorkspaceFilesRail` were not opened.** #1075 cites them (AD-1083); their existence and shape are taken on the issue's word. Confirm before claiming UI reuse.
3. **`crew_executor.py:258`** (cited by #1075 as the evidence-builder mapping) resolves to `_build_crew_loop_settings` / `_format_consult_age` at HEAD, **not** a `stopped_reason` map. The real mapping is **`:51`** (`_STOPPED_REASONS`), **`:605`** and **`:1628`** (coerce-unknown-to-`error`). **#1075's line reference is stale** — cite `:51` / `:605` / `:1628`.
4. **`workforce.py:1800` / `:1812` / `:3020` / `:3062`** (cited by #1075) all **verified exact** at `b766254e`. That part of the issue is accurate.
5. **`hooks/bus.py` wiring at `startup/communication.py:451`** (cited by #1075) is **stale** — the registration block is at **`:585-597`**, with `hook_bus=hook_bus` passed at **`:777`**.
6. **`AGENTIC_MAX_ITERATIONS = 25`** (`agentic_loop.py:32`) bounds *turns*, not correctness. #1075's "25 iterations" framing is a **cost** argument; AD-1142/1147/1148 already own cost. Do not let it be re-read as a safety argument.

---

## Tracking

- **`PROGRESS.md`** — record AD-1150 **DEFERRED**, with the one-line reason: *"`HookBus.ask` has zero resolution machinery, `AgenticLoop.run()` cannot suspend, and plan rejection has no representable `stopped_reason`; six approval surfaces already exist."* AD ceiling stays **AD-1151**; BF ceiling stays **BF-680**; next free stays **AD-1152 / BF-681**.
- **`docs/development/roadmap.md`** — mark #1075 deferred under epic #1068. Epic #1068 is otherwise complete (AD-1138/1139/1140/1141/1143/1146/1147/1148/1151/1142, BF-675/679/680); AD-1149 and AD-1150 are its two deferrals.
- **`DECISIONS.md`** — **no entry.** No architectural decision was made; a proposal was declined. (AD-1149 precedent.)
- **GitHub** — close **#1075** as *not planned*, linking Corrections 1–3 and §Unblock. Second deferral in epic #1068 after #1074/AD-1149.

---

## Done-when

- [ ] Verdict accepted: **#1075 closed as not-planned.**
- [ ] `PROGRESS.md` records AD-1150 deferred with the one-line reason.
- [ ] Roadmap marks #1075 deferred under #1068.
- [ ] **Zero** files changed under `src/` or `tests/`.
- [ ] **No test run of any scope.**
- [ ] This document is the only artefact.

---

## Verified Against Codebase (2026-07-26, HEAD `b766254e`)

```
# --- Correction 1: `ask` is an enum member with no resolver -------------------
hooks/bus.py:48        PRE_TOOL_USE = "pre_tool_use"        # gate: before a tool invocation
hooks/bus.py:50        PRE_DISPATCH = "pre_dispatch"        # gate: before a mesh intent is dispatched
hooks/bus.py:60        _GATE_EVENTS = frozenset({HookEvent.PRE_TOOL_USE, HookEvent.PRE_DISPATCH})
hooks/bus.py:67            ASK = "ask"      # surface to the human (Captain) for approval
hooks/bus.py:74            HookDecision.ASK: 1,
hooks/bus.py:108           return self.decision == HookDecision.ASK        # ← zero production consumers
hooks/bus.py:176           For gate events, returns the aggregated most-restrictive verdict.
#   fire() aggregates and RETURNS. No suspend / persist / notify / wait / resume anywhere.

# The ONLY production consumer of fire() in the whole tree — reads .denied only:
reply_pipeline.py:964      decision = await hook_bus.fire(
reply_pipeline.py:976      blocked = decision.denied

# Hooks are default-OFF and the bus is None:
startup/communication.py:585   # Off by default (config.hooks.enabled=False) -> hook_bus stays None and the
startup/communication.py:591   hook_bus = None
startup/communication.py:596       hook_bus = HookBus()
startup/communication.py:777       hook_bus=hook_bus,
#   ⇒ #1075's cited ":451" is stale.

# AgenticLoop has NO HookBus wiring. `hook_bus` matches, whole tree:
#   runtime.py:2898 · startup/communication.py:{585,591,596,777} · startup/finalize.py:3768
#   startup/results.py:179 · startup/shutdown.py:920 · reply_pipeline.py:964
#   ⇒ nothing under swe_harness/. PRE_TOOL_USE is declared and NEVER fired.

# --- Correction 2: run() cannot suspend — all state is local -----------------
agentic_loop.py:716    class AgenticLoop:
agentic_loop.py:719        def __init__(
agentic_loop.py:765        async def run(
agentic_loop.py:789            result = AgenticResult()
agentic_loop.py:790            messages: list[dict] = [
agentic_loop.py:795            tool_id_history: list[str] = []
agentic_loop.py:799            token_sources: set[str] = set()
agentic_loop.py:803            for iteration in range(1, self._max_iter + 1):
agentic_loop.py:32     AGENTIC_MAX_ITERATIONS = 25
agentic_loop.py:764            self._tasks: set[asyncio.Task] = set()
#   Two construction sites, both single-shot:
agentic_dispatch.py:1006       loop = AgenticLoop(
agentic_dispatch.py:1035       agentic_result = await loop.run(
native_builder.py:99           loop = AgenticLoop(

# --- Correction 3: no representable rejection outcome ------------------------
crew_executor.py:49    _SUCCESS_STOPPED_REASON = "complete"
crew_executor.py:51    _STOPPED_REASONS = frozenset(
crew_executor.py:52-60     complete, error, max_iterations, token_budget,
                           execution_exception, unassigned, agent_unresolvable,
                           dependency_blocked, ...
crew_executor.py:605       reason = stopped_reason if stopped_reason in _STOPPED_REASONS else "error"
crew_executor.py:1628      stopped_reason if stopped_reason in _STOPPED_REASONS else "error"
agentic_loop.py:697        stopped_reason: str = "complete"  # complete|max_iterations|token_budget|error
#   ⇒ #1075's cited ":258" is stale (that line is _build_crew_loop_settings / _format_consult_age).

# --- Correction 4 + DD-3/DD-7: the step machine already gates completion -----
workforce.py:1800      STEP_STATUSES: frozenset[str] = frozenset(
workforce.py:1801          {"pending", "in_progress", "submitted", "done", "rejected"}
workforce.py:1806          "submitted": frozenset({"done", "rejected", "in_progress"}),
workforce.py:1812      def validate_step_transition(old: str, new: str) -> bool:
workforce.py:3020      async def set_steps(
workforce.py:3026          step. ``gate_completion`` marks the item so it cannot transition to 'done'
workforce.py:3056              md["steps_gate_completion"] = True
workforce.py:3062      async def update_step(
workforce.py:3101          and (item.metadata or {}).get("steps_gate_completion")
todo_extractor.py:35   _TODOS_RE   = re.compile(r"\[TODOS\](.*?)\[/TODOS\]", ...)
todo_extractor.py:36   _PLAN_RE    = re.compile(r"\[PLAN\](.*?)\[/PLAN\]", ...)
todo_extractor.py:37-39 _DONE_RE / _CONFIRM_RE / _REJECT_RE
todo_extractor.py:113  def derive_prose_plan(text: str, *, max_items: int = _MAX_TODOS) -> list[str]:
reply_pipeline.py:1345     await self._apply_room_todos(store, task_id, parse_todo_tags(text))
reply_pipeline.py:1354     await store.set_steps(task_id, plan, gate_completion=True, facilitator=...)
reply_pipeline.py:1437     await store.set_steps(task_id, parsed.plan, gate_completion=True, facilitator=actor)
config.py:5572         room_todos_min_rank: str = Field(
config.py:5578             description="AD-1082: min rank to SEED the plan ([TODOS]) ... confirm/reject stay at room_todos_min_rank.",
reply_pipeline.py:1368     return self._todo_actor_meets(agent_id, "room_todos_min_rank", "commander")
cognitive_agent.py:3325-3341   AD-1065 conversational agentic turn (human already turn-gated)

# --- The six existing approval surfaces --------------------------------------
routers/chat.py:69         elif parts[0].lower() == "/design":
cognitive/architect.py:30  class ArchitectProposal:
routers/design.py:47       """Approve architect proposal — forwards embedded BuildSpec to builder."""
routers/build.py:43        @router.post("/approve")
crew_session.py:432        plan_seed_hash: str
crew_session.py:1133       def _final_plan_hash(
crew_session.py:1174       plan_seed_hash = hashlib.sha256(projection_bytes).hexdigest()
crew_session.py:1574       if hashlib.sha256(projection_bytes).hexdigest() != candidate.plan_seed_hash:
notifications.py:33-34     # AD-1053: optional actionable affordance. When present, the HXI renders an
                           # "Accept" button; POST /api/notifications/{id}/accept dispatches the carried
notifications.py:44        suggested_action: dict[str, Any] | None = None
routers/system.py:427      @router.post("/notifications/{notification_id}/accept")
routers/system.py:428      async def accept_notification(
capability_gap_driver.py:1 """AD-855: BLOCKED -> request -> approve -> resume work-item gap driver.
governance/decision_queue.py:19-25   PENDING / APPROVED / REJECTED / DEFERRED / EXPIRED  (AD-445)

# --- Config homes ------------------------------------------------------------
config.py:3244         class HooksConfig(BaseModel):
config.py:4369         class AgenticLoopConfig(BaseModel):
config.py:6022         class DmAgenticConfig(BaseModel):  # AD-1065

# --- AD / BF ceilings --------------------------------------------------------
git log -1 --oneline
  b766254e  BF-680: fall back to a client-side token estimate when the provider reports none
#   Highest AD in trackers: AD-1151. Highest BF: BF-680. AD-1150 has zero tracker
#   references (reserved by #1075). Next free: AD-1152 / BF-681.
```
