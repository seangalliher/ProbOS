# AD-1155 — Loop-until-done: an outer completion evaluator over the crew child's agentic run

**Issue: #1082 · Epic #1068 (agentic harness parity). Depends on nothing; AD-1146/1147/1148/1151/1142/1153 and BF-680 are all in-tree at HEAD `ed3f9f52`.**
**Repo: OSS (`d:\ProbOS`). This AD = **AD-1155** (#1082). AD ceiling: **AD-1155** (assigned by this issue); next free **AD-1156**. BF ceiling: **BF-682** (minted by AD-1153/DD-8); next free **BF-683** — `BF-681` is an unallocated gap, do not use it. No new AD. One new BF is authorised: **BF-683** (DD-9), file-only, do not fix.**

Re-invoke a crew child that stopped without finishing, with a fresh, independently governed run each time, bounded by its own cap, and stop early when an iteration achieves nothing. Default-OFF.

**Read the corrections section before the DDs.** Three of issue #1082's load-bearing premises are false at HEAD, and one of them — *"a `todos_remaining`-equivalent is a read over state that already exists"* — is false in a way that would make the shipped default re-invoke **every crew child, always, up to the cap**. The DDs are built on the corrected picture, not on the issue.

---

## Corrections to #1082, read off the live tree at HEAD `ed3f9f52`

### C-1 — An outer loop already exists, and it is LIVE

`SubtaskVerifier.converge_for_session` (`crew_verifier.py:1301`) is a complete, governed, bounded outer loop over `WorkItemAgenticExecutor.run`. It is called from `crew_finalizer.py:1329` and `:2106` on the live crew-session path. It already does every structural thing the issue asks for:

| #1082 asks for | `converge_for_session` at HEAD |
|---|---|
| Re-invoke until a condition is satisfied | `for attempt_index in range(1, max_rounds + 1)` (`:1361`) |
| A hard outer cap | `max_rounds = min(self._max_rounds, 8)` (`:1360`), from `AgenticDispatchConfig.max_convergence_rounds` (default 2, `config.py:6367`) |
| Each iteration a complete independent run | a fresh `self._executor.run(...)` (`:1391`) with `department`, `rank`, `thread_id`, `extra_context` |
| `loop_next_message` | `critiqued_task = f"{normalized_task}\n\nCRITIQUE:\n{verdict.critique}"` (`:1362-1364`) |
| Never persist the enriched text | composed into `task_text` only — the AD-1141 pattern, already followed |
| Per-iteration provenance | `SessionVerificationRound` with `result_revision`, `correction_tokens`, `tool_trace_ref`, `artifact_refs` (`:170-183`) |

`SubtaskVerifier.converge` (`:1139`) — the non-session sibling — has **zero callers in `src/`**; grep confirms it is exercised only by `tests/test_ad860_crew_verifier.py`. It is dead on the live path. Do not build on it and do not delete it here.

**So the gap is not "there is no outer loop." The gap is that the only predicate is an LLM judge, and the loop it drives treats `max_iterations` as terminal.** `_classify_correction_terminal` (`:1863-1890`) returns `None` (continue) **only** for `stopped_reason == "complete"` with non-empty text; `token_budget` maps to `correction_budget_exhausted` and everything else — including `max_iterations` — falls to `else: failure = "correction_execution_defect"` and stops. A child that ran out of iterations is classified as a defect, not as unfinished work.

This reframes the AD. It is not "add looping"; it is **"add a cheap deterministic predicate and a `max_iterations` continuation, at the fan-out seam, without touching the judge."**

### C-2 — `todos_remaining` is NOT a clean read over existing state on the loop being wrapped

The state machine exists exactly as the issue describes. `workforce.py:1795-1810`:

```
STEP_STATUSES = {"pending", "in_progress", "submitted", "done", "rejected"}
"submitted": frozenset({"done", "rejected", "in_progress"})
```

and `_all_steps_done` at `:1822`. But six facts make it unusable as a crew-child predicate:

1. **The crew path never writes `steps`.** `grep -n '\bsteps\b' src/probos/cognitive/crew_executor.py src/probos/cognitive/crew_session.py` returns **nothing** except an unrelated docstring in `crew_verifier.py`. The only crew-adjacent reader is `crew_session_live.py:344`, a read-only UI progress projection over the **parent**.
2. **`_all_steps_done([]) is False.**` It is `bool(steps) and all(...)`. So `not _all_steps_done(child.steps)` — the literal `todos_remaining` — is **True for every crew child that has never had a checklist**, which is all of them. Shipping that as the default predicate re-invokes every child to the cap. This is the single most dangerous line in the issue.
3. **The crew fan-out has no way to close a step.** Steps move through `[TODOS]` / `[TODO_DONE n]` / `[TODO_CONFIRM n]` tags parsed by `reply_pipeline.step_4l_extract_todos` (`:1313`) — a step of the **DM reply pipeline**. A crew child running through `AgenticLoop` via `WorkItemAgenticExecutor.run` never enters that pipeline. It cannot emit a todo transition.
4. **The tag path is itself default-OFF.** `communications.room_todos_enabled` (`config.py:5568`) ships `False`, and `step_4l_extract_todos` returns immediately when it is off.
5. **`submitted` is an open todo the agent cannot close.** `_apply_room_todos` (`reply_pipeline.py:1426`) gates `submitted → done` on `can_validate = is_senior or actor == facilitator`, where `is_senior` needs rank ≥ `room_todos_min_rank` (default `"commander"`, `config.py:5572` ⇒ trust ≥ 0.7, `config.py:21`). Built-in agents seed at Beta(2,2) = 0.50 ⇒ **lieutenant**. So the modal crew agent is structurally incapable of closing its own submitted step. **Re-invoking it is guaranteed-futile work.** This answers the question the issue leaves open: for a completion predicate, `submitted` must count as **not actionable**, which is not the same as *done* and not the same as *open*.
6. **Steps live on the parent, not the child.** `_run_child` receives `parent_id: str`, not the parent row (`crew_executor.py:1263`), so any todo read costs a store round-trip per outer iteration and races the DM path, which can rewrite the same list concurrently.

**Consequence for DD-2:** todos-remaining ships as a **non-default, opt-in** predicate with a hard inapplicability guard, never as the shipped default. The default is `stopped_reason`.

### C-3 — `token_budget` resets on every re-invocation unless the caller carries it

`AgenticLoop` enforces `if self._budget is not None and result.total_tokens >= self._budget` (`agentic_loop.py:914`) against `result.total_tokens`, a counter local to **one `AgenticResult`**. `WorkItemAgenticExecutor.run` constructs a **new `AgenticLoop` per call** (`agentic_dispatch.py:1232`). So a naive outer loop that passes the same `token_budget` to each iteration multiplies the operator's spend ceiling by the outer cap. `converge_for_session` already has this defect in a milder form: its re-run at `crew_verifier.py:1391` passes **no** `compactor` and **no** `token_budget` at all, so every correction round is unbudgeted. That is pre-existing — **DD-9 files it, this AD does not fix it.**

### C-4 — Confirmed as stated in the issue

- `AGENTIC_MAX_ITERATIONS = 25` (`agentic_loop.py:32`).
- `stopped_reason` set is exactly `complete|max_iterations|token_budget|error` (`agentic_loop.py:697`).
- `max_parallel_tool_calls` is `ge=1, le=16`, default 3 (`config.py:4452-4456`).
- `description` is inside the plan-identity projection — `_PROVISIONING_SPEC_KEYS` (`crew_session.py:1037-1049`) includes `"description"`, and `_final_plan_hash` (`:1133`) / `plan_seed_hash` (`:1174`) are computed over it.
- The `crew_execution` record is exactly 14 keys (`crew_executor.py:634-648`): `version, parent_id, work_item_id, thread_id, assigned_to, status, stopped_reason, output_summary, tool_trace_ref, artifact_refs, tokens_used, started_at, finished_at, blocked_dependency_ids`.
- `SubtaskResult` is 13 fields, frozen (`crew_executor.py:667-681`).
- BF-680 landed: `token_source` rides on `WorkItemAgenticOutcome` (`agentic_dispatch.py:806`) because the 14-key record has nowhere to put it.

---

## Pinned design decisions

### DD-1 — Wraps `CrewTaskExecutor._run_child`, not `WorkItemAgenticExecutor.run`

`WorkItemAgenticExecutor.run` has **six** call sites:

| Caller | Path |
|---|---|
| `cognitive_agent.py:1499` | AD-839 conversational |
| `cognitive_agent.py:3517` | AD-1065 chat |
| `crew_executor.py:1407` | **crew fan-out child — the target** |
| `crew_verifier.py:1168` | `converge()` — dead on the live path |
| `crew_verifier.py:1391` | `converge_for_session()` — LIVE, already an outer loop |
| `delegate_task_tool.py:184` | AD-1072 delegation |

Wrapping inside `.run` would nest this loop **inside** `converge_for_session`'s correction rounds, producing a four-way multiplication (convergence × outer × inner × parallel) and a second outer loop the finalizer's evidence model knows nothing about. It would also change the AD-839 and AD-1072 paths — precisely the trap AD-1141/DD-1 caught for `task_text` and AD-1142/DD-2 caught for compactor construction.

**Wrap at `crew_executor.py:1407`.** Extract the existing `try: outcome = await self._executor.run(...) except Exception:` block into a private `_run_agentic_with_outer_loop(...)` that performs iteration 1 exactly as today and then, only when the gate is on and the predicate says continue, performs further iterations. The five other callers are byte-identical **by construction, not by flag** — the strongest form of the AD-1142/DD-1 guarantee, and it is what makes the OFF-path test cheap to write.

**Consequence, stated because it is a real cost:** the AD-839 conversational path and the AD-1072 delegation path get nothing from this AD. That is correct scoping — a conversational turn that hits `max_iterations` has a human present who can say "keep going"; an unattended crew child does not. If delegation later wants it, `delegate_task_tool` calls the same executor and can adopt the same helper.

### DD-2 — Two shipped predicates. `stopped_reason` is the default. Todos is opt-in with an inapplicability guard. No AI judge

A predicate is a pure function of `(outcome, iteration_state)` returning `continue` / `stop`, plus a reason string for the log. Module constants in `crew_executor.py`, selected by a config **enum string**, not a callable — an operator-supplied callable would be an arbitrary-code seam on the crew hot path.

```python
_LOOP_PREDICATE_STOP_REASON = "stopped_reason"      # default
_LOOP_PREDICATE_COMPLETION_MARKER = "completion_marker"
_LOOP_PREDICATE_OPEN_TODOS = "open_todos"           # opt-in, guarded
_LOOP_PREDICATES = frozenset({...})                  # fail-safe membership set
```

**`stopped_reason` (default).** Continue iff `outcome.stopped_reason == "max_iterations"`. See DD-6 for why the other three are all `stop`. This is the only predicate whose signal is unambiguous: `max_iterations` means the loop was cut off mid-work by a counter, which is exactly the failure the epic is named for.

**`completion_marker`.** Continue iff the trailing 200 characters of `outcome.final_text` do not contain the configured marker, AND `stopped_reason` is re-invokable per DD-6. Marker is a config string, default `"TASK COMPLETE"`. **State its weakness in the docstring:** it requires the agent to have been told to emit it, and nothing in this AD teaches it — the continuation block in DD-4 does when the marker predicate is armed, but iteration 1 does not, so a single-iteration run can never satisfy it. That asymmetry is why it is not the default.

**`open_todos` (opt-in).** Three-part guard, in this order:
1. Load the **parent** row once per outer iteration. If `type(parent.steps) is not list` or `len(parent.steps) == 0` ⇒ **inapplicable ⇒ stop**. Never "not all done ⇒ continue"; see C-2 #2.
2. Compute `actionable = [s for s in steps if str(s.get("status", "pending")) in {"pending", "in_progress", "rejected"}]`. `submitted` is **excluded** — it is blocked on a validator the child cannot be (C-2 #5). `done` is excluded.
3. Continue iff `actionable` is non-empty **and** `stopped_reason` is re-invokable per DD-6.

Reuse `workforce.STEP_STATUSES` for validation rather than re-typing the vocabulary; do **not** import or extend `_all_steps_done`, whose empty-list semantics are wrong here and whose single existing caller (`workforce.py:3102`) must not change.

**No AI-judge predicate.** `converge_for_session` already is one, it is already live on the same children, and it already charges an LLM call per round. Adding a second judge would double that cost for a strictly weaker signal (this one has no `expected_output` and no independence requirement). If a future AD wants judge-driven continuation, the correct move is to fix `_classify_correction_terminal`'s `max_iterations` branch, not to build a parallel judge. Record that as the alternative considered and rejected.

### DD-3 — One outer cap, one shared budget carried forward, and the worst case stated in the config docstring

**Cap.** `crew_loop_until_done_max_iterations: int = Field(default=2, ge=1, le=5)` on `AgenticDispatchConfig`, placed after `crew_token_budget` (`config.py:6489`). `1` means *no re-invocation*, identical to today; the gate flag is what turns the feature on, so the cap is a bound, never an enable.

**The worst case belongs in the description, verbatim and un-softened.** Per child, per outer iteration: `AGENTIC_MAX_ITERATIONS` (25) turns, each turn up to `agentic_loop.max_parallel_tool_calls` (ceiling 16) concurrent tool calls. At the outer ceiling of 5 that is **5 × 25 × 16 = 2 000 tool invocations for one crew child**, before `max_parallel_subtasks` (default 3, ceiling 64) multiplies it across siblings and before `converge_for_session` adds up to 8 correction rounds on the finalizer path. State the four-way product. Do not add a cross-field validator — the AD-1142 precedent (`crew_compaction_threshold_tokens`) is that the relation is documented and asserted in tests, not enforced by Pydantic, because a validator here would turn an unrelated `POST /config` into a 422.

**Budget: shared across iterations, carried forward as a remainder. Never reset.**

```
remaining = token_budget - sum(outcome.total_tokens for prior iterations)
```

Pass `token_budget=remaining` to iteration *n*. Stop before iteration *n* if `remaining < _MIN_CREW_TOKEN_BUDGET` (1024, already defined at `crew_executor.py:194`) — re-invoking with a sub-floor remainder just burns one LLM call to hit the budget immediately. Resetting per iteration would turn an operator's spend ceiling into a per-iteration ceiling and silently multiply it by the cap; nobody setting `crew_token_budget=50000` expects 250 000.

**Consequence, stated because it is the honest cost:** with a budget set, iterations 2+ run with a *smaller* budget than iteration 1, so a child that legitimately needs more room is more likely to stop at `token_budget` on the continuation than on the first pass. That is the correct trade — the budget is a ceiling, not an allowance — but it means `crew_token_budget` and this feature interact, and the docstring must say so on both fields.

`compactor` is threaded per iteration exactly as today: a **fresh** `SessionCompactor` per iteration via `resolve_crew_compaction_settings`, per AD-1142/DD-2, with the `token_budget` key overwritten by the remainder when a budget is configured. When no budget is configured, the resolved dict is passed through untouched.

### DD-4 — The continuation block is composed at runtime into `task_text`, following `_augment_task_text`

Iteration 1 uses `task_text` exactly as AD-1141 produced it. Iteration *n* > 1 uses `task_text + _render_continuation(...)`. **Never `description`. Never persisted. Never into `crew_execution`.**

The block carries three things, bounded:

| Part | Bound | Why |
|---|---|---|
| Why it is being re-run | fixed string per stop reason | "you were cut off after N turns" is actionable; a bare repeat of the prompt is not |
| What it produced last time | `_MAX_CONTINUATION_OUTPUT_CHARS = 2000`, head-truncated with a visible marker | Below AD-1141's `_MAX_EXPECTED_OUTPUT_CHARS` (1000) × 2 and well under `_MAX_OUTPUT_SUMMARY_CHARS` (4096). Without it the agent restarts from zero and repeats the work — the failure mode the issue names |
| Open todos, **only** when the `open_todos` predicate is armed and applicable | 20 labels × 120 chars | Costs a parent round-trip; do not pay it for the other predicates |

Total continuation block bounded at `_MAX_CONTINUATION_CHARS = 3000`. Compose with a helper mirroring `_augment_task_text`'s shape (`crew_executor.py:1137`): returns `base` **by identity** when inapplicable, absorbs its own exceptions, and is called **outside** the `try` that persists `stopped_reason="execution_exception"` — the AD-1141/DD-8 rule. A continuation-composition failure must degrade to "no continuation, stop the outer loop", never to a failed child.

**Gap-regex constraint.** Every authored string must be clean under the **real imported** `decomposer._CAPABILITY_GAP_RE` (`decomposer.py:33-41`, `re.IGNORECASE`). Forbidden substrings include the bare `lack` / `lacks` / `lacking`, `can't`, `cannot`, `unable to`, `not available`, `no way`. The natural English for "you didn't finish" is a minefield here — "you were unable to complete" trips it twice. Suggested wording, to be re-run against the imported regex, not a re-typed copy:

- stop-reason continuation — `"You reached this task's turn limit before finishing. Continue from where you stopped. Your previous output is below — build on it, do not start over."`
- prior-output header — `"## What you produced on the previous pass"`
- output elision — `"\n... [truncated: {omitted} characters elided from your previous output.] ...\n"`
- open-todo header — `"## Checklist items still open"`
- marker instruction (only when the marker predicate is armed) — `"When the task is genuinely finished, end your final message with the exact line: {marker}"`

**Assert plan-identity hash stability**: compute `_final_plan_hash` / `plan_seed_hash` over the child's projection before and after a multi-iteration run and require byte equality.

### DD-5 — No-progress detection, measured only from state that exists

Everything below is readable from `WorkItemAgenticOutcome` (`agentic_dispatch.py:768-806`) plus, for the todos predicate, the parent row already loaded by DD-2.

An iteration made **no progress** iff all of:
- `outcome.artifact_refs` is empty, **and**
- `sha256(outcome.final_text)` equals the previous iteration's, **and**
- when `open_todos` is armed and applicable: the count of non-`pending` steps did not increase.

Two **consecutive** no-progress iterations ⇒ stop with reason `no_progress`. One is not enough: an agent can spend a whole pass on a long tool investigation whose payoff lands on the next.

**Be honest about the strength of this signal.** Byte-identical `final_text` across two LLM calls at non-zero temperature is rare, so in practice the artifact clause carries almost all the weight, and a task whose output is prose rather than a file will rarely trip it. This is a **backstop against the pathological case, not a general early-exit.** The cap in DD-3 is the real bound. Say so in the docstring rather than implying the detector is load-bearing.

Do not add a semantic-similarity check — that is an LLM call per iteration, which is DD-2's rejected AI-judge cost wearing a different hat.

### DD-6 — Re-invokability of each of the four `stopped_reason` values, decided explicitly

| `stopped_reason` | Re-invoke? | Why |
|---|---|---|
| `max_iterations` | **YES** | The only unambiguous "cut off mid-work" signal. A counter, not a judgement. This is the whole feature. |
| `token_budget` | **NO** | A hard spend ceiling the operator set. Re-invoking after it defeats its purpose, and `crew_executor.py:1449` already maps it to `status="failed"` so dependents stay blocked — deliberately (`config.py:6477-6481`). Overriding that here would silently reverse an AD-1142 decision. |
| `error` | **NO** | Set at `agentic_loop.py:877` when `llm_client.complete()` raises — most often provider-window exhaustion, which is exactly what AD-1142 exists to address. The continuation block makes `task_text` **longer**, so re-invoking after a window error is strictly counterproductive. Compaction, not looping, is the mechanism for this reason. |
| `complete` | **NO** under `stopped_reason`; **predicate-dependent** under `completion_marker` / `open_todos` | The model chose to stop. Treating that as unfinished is exactly the "burn tokens re-running an agent that already gave up" failure. Only an explicit external signal — a missing marker, or an open actionable checklist item — may override it, and both are opt-in. |

Implement as a module frozenset `_REINVOKABLE_STOPPED_REASONS = frozenset({"max_iterations"})`, consulted by **every** predicate as a precondition. Fail-safe membership, same direction as `PARALLEL_SAFE_TOOL_IDS` and `_BROWSER_LOOP_ACTIONS`: an unknown or newly added stop reason is not re-invoked. Assert the set against the live `_STOPPED_REASONS` (`crew_executor.py:51`) so a future reason cannot be silently admitted.

### DD-7 — Default-OFF, byte-identical when off

`crew_loop_until_done_enabled: bool = False` on `AgenticDispatchConfig`, threaded through `CrewTaskExecutor.__init__` as a keyword with a `False` default and normalised there — **outside** the `_run_child` try, per AD-1142/DD-10 (`crew_executor.py:730-742`). Extend the existing `self._compaction_config` `SimpleNamespace` rather than adding a second config object, or add a sibling namespace; either is fine, but the normalisation must not be able to raise.

Off ⇒ `_run_agentic_with_outer_loop` performs exactly one iteration, calls `self._executor.run(...)` with a byte-identical kwarg dict, and returns its outcome unchanged. Not a Σ flag; **do not touch `tests/ablation/sigma_flags.py`.**

### DD-8 — Every iteration is an independently governed run, and that has a consequence worth asserting

This is free — it falls out of DD-1's seam. Each `WorkItemAgenticExecutor.run` call independently:
- constructs a fresh `DispatchToolExecutor` (`agentic_dispatch.py:895`),
- re-resolves `department` / `rank` through `_resolve_agentic_identity` (`:187`), which reads **live** `trust_network.get_score(agent_id)`,
- re-runs every `registry.check_permission` offer gate (`:1077`, `:1102`, `:1123`, `:1139`, `:1171`),
- re-arms the AD-1153 browser action guard,
- persists its **own** AD-1151 tool trace via `_persist_tool_trace` (`:1246`).

**The consequence:** an agent whose trust drops between iterations loses tools on the next one. `Rank.from_trust` (`crew_profile.py:38-47`) crosses `TRUST_LIEUTENANT = 0.5` and the browser offer (`ensign: none`) disappears. That is Minimal Authority working correctly and it must be asserted, not merely allowed — it is the cheapest available proof that iterations are genuinely independent rather than a resumed session.

Each iteration produces a distinct `tool_trace_ref`. Only the **final** iteration's ref reaches the 14-key `crew_execution` record — the set is frozen and cannot carry a list. Log the discarded refs at INFO with the iteration index so the trace chain is recoverable from the log, and say plainly in the docstring that intermediate traces are **not** durably linked from the evidence record. Do not invent a companion metadata key; that is exactly the "one extra breaks recovery" hazard AD-1141 names at `crew_executor.py:1184`.

### DD-9 — `converge_for_session`'s correction re-runs are unbudgeted and uncompacted. File **BF-683**; do not fix here

`crew_verifier.py:1391` calls `self._executor.run(...)` with `agent_id`, `instructions`, `task_text`, `runtime`, `department`, `rank`, `thread_id`, `extra_context` — and **no** `compactor`, **no** `compaction_threshold`, **no** `token_budget`. So up to `min(max_convergence_rounds, 8)` correction rounds per child run entirely outside the AD-1142 ceilings that the first pass respects. An operator who sets `crew_token_budget=50000` gets it honoured on the fan-out pass and ignored on every correction round.

This is pre-existing, it is not caused by this AD, and fixing it touches the session-correction evidence model (`SessionCorrectionTerminalAttempt`, `correction_budget_exhausted` at `crew_verifier.py:1874`) and its suite. **File BF-683 and add a comment at the DD-3 budget code naming it.** Do not fix it here — but do make sure this AD's own budget arithmetic does not depend on the correction rounds being budgeted, because they are not.

---

## Build

1. **`src/probos/cognitive/crew_executor.py`**
   - Module constants near `_STOPPED_REASONS` (`:51`): `_REINVOKABLE_STOPPED_REASONS`, `_LOOP_PREDICATE_*`, `_LOOP_PREDICATES`, `_LOOP_UNTIL_DONE_MAX_ITERATIONS` (2), `_MAX_CONTINUATION_CHARS`, `_MAX_CONTINUATION_OUTPUT_CHARS`, `_MAX_CONTINUATION_TODOS`, and the DD-4 framing strings. Comment block explaining the fail-safe direction, citing AD-1147/DD-1 and AD-1153/DD-1 as precedent, and stating C-1 (an outer loop already exists in `converge_for_session`) so the next reader does not build a third one.
   - `_normalize_loop_until_done(...)` clamp helpers alongside `_normalize_compaction_threshold` (`:196`) / `_normalize_token_budget` (`:211`). **Must not raise** — same reasoning, same docstring convention.
   - `CrewTaskExecutor.__init__` (`:688`): new keyword-only `crew_loop_until_done_enabled: bool = False`, `crew_loop_until_done_max_iterations: int = _LOOP_UNTIL_DONE_MAX_ITERATIONS`, `crew_loop_until_done_predicate: str = _LOOP_PREDICATE_STOP_REASON`, `crew_loop_until_done_completion_marker: str = "TASK COMPLETE"`. Normalised in `__init__`.
   - `_render_continuation(...)` — pure, bounded, returns `""` when inapplicable.
   - `_should_continue(...)` — pure predicate dispatch; takes the outcome, the iteration index, the previous `final_text` hash, the no-progress streak, and the optional parent steps; returns `(bool, reason)`.
   - `_run_agentic_with_outer_loop(...)` — owns the iteration, the budget remainder, the no-progress streak, and the INFO logging. Called from `_run_child` in place of the current inline `self._executor.run(...)`; the existing `except Exception` handler stays where it is and keeps its `execution_exception` semantics.
2. **`src/probos/config.py`** — the four fields on `AgenticDispatchConfig` after `crew_token_budget` (`:6489`), before the `@model_validator` at `:6491`. Descriptions must carry: the DD-3 four-way worst case, the DD-3 budget-sharing consequence, the DD-2 statement that `open_todos` is inapplicable to crew children that have no checklist, and a cross-reference on `crew_token_budget` back to this feature.
3. **`docs/development/config-reference.md`** — regenerate with `python scripts/gen_config_reference.py`. Do not hand-edit.
4. **`src/probos/startup/finalize.py`** — four `getattr(cfg, ..., <default>)` kwargs on the `CrewTaskExecutor(...)` construction at `:1881`, following the AD-1142 block at `:1897-1903` exactly.
5. **Tests** — `tests/test_ad1155_loop_until_done.py` (NEW), ≈34 tests. Reuse the `_FakeAgent` / `_FakeRegistry` doubles and the `WorkItemStore` fixture shape from `tests/test_ad1142_crew_child_compaction.py:100-140`. Import the **real** `_CAPABILITY_GAP_RE` from `probos.cognitive.decomposer`, per that file's own header note.

No new files under `src/`. **No edit to** `src/probos/cognitive/agentic_dispatch.py`, `src/probos/cognitive/crew_verifier.py`, `src/probos/cognitive/crew_finalizer.py`, `src/probos/cognitive/swe_harness/agentic_loop.py`, `src/probos/workforce.py`, or `src/probos/cognitive/dm/reply_pipeline.py`.

---

## Acceptance

**Headline — a child that stops at `max_iterations` with work left is re-invoked and completes. It must fail without the outer loop.**

> A crew child's `WorkItemAgenticExecutor.run` is stubbed to return `stopped_reason="max_iterations"` with partial output on call 1 and `stopped_reason="complete"` with the finished output on call 2. With `crew_loop_until_done_enabled=True` the child's persisted `crew_execution` record carries `status="done"`, `stopped_reason="complete"`, and the second call's `final_text`. With the flag off — **the same test body, one flag flipped** — it carries `status="failed"`, `stopped_reason="max_iterations"`, and the first call's output. Assert the executor was called exactly twice ON and exactly once OFF.

**Seam (DD-1):**
- Flag OFF ⇒ `self._executor.run` is called exactly once per child, and the kwarg dict is asserted **key-for-key and value-for-value** against a literal recomputation of the AD-1142 set (`agent_id, instructions, task_text, runtime, thread_id, extra_context` + the resolved compaction spread). This is the AD-1142 Section 1 pattern; reuse it.
- `WorkItemAgenticExecutor.run`'s signature is unchanged — assert via `inspect.signature`, the AD-1142 drift-guard shape.
- `crew_verifier.py` and `crew_finalizer.py` are untouched: assert `SubtaskVerifier.converge_for_session` still calls the executor with no `token_budget` kwarg, pinning DD-9 as a **known** gap rather than an accident.

**Predicates (DD-2):**
- `stopped_reason`: continues on `max_iterations`; stops on each of `complete`, `token_budget`, `error` — one test per value, asserting the call count is 1.
- `completion_marker`: with `stopped_reason="max_iterations"`, stops when the marker is in the trailing text, continues when it is absent. A `complete` stop with no marker still stops (DD-6 precondition binds first).
- `open_todos` **with `parent.steps == []`** ⇒ **stops**, call count 1. This is the C-2 #2 regression and the most important single test in the file — a naive `not _all_steps_done(...)` implementation fails it.
- `open_todos` with steps `[done, submitted]` ⇒ **stops** (nothing actionable; `submitted` is blocked on a validator the child cannot be — C-2 #5).
- `open_todos` with steps `[done, pending]` ⇒ continues.
- `open_todos` with steps `[done, rejected]` ⇒ continues.
- A malformed `steps` value (`None`, a dict, a list of non-dicts, a step whose `status` is not in `STEP_STATUSES`) ⇒ stops, no raise, WARNING logged.
- An unknown predicate string in config ⇒ normalises to the default, no raise.
- `_REINVOKABLE_STOPPED_REASONS <= _STOPPED_REASONS` and `_REINVOKABLE_STOPPED_REASONS == {"max_iterations"}` — the drift guard.

**Caps and budget (DD-3):**
- `crew_loop_until_done_max_iterations=3` with a predicate that never satisfies ⇒ exactly 3 calls, and the persisted record carries the **last** iteration's `stopped_reason`.
- `=1` ⇒ exactly 1 call even with the flag on.
- With `crew_token_budget=10_000` and iteration 1 reporting `total_tokens=7_000`, iteration 2 receives `token_budget=3_000`. Assert the kwarg value, not just that a budget was passed.
- With iteration 1 reporting `total_tokens=9_500`, the remainder (500) is below `_MIN_CREW_TOKEN_BUDGET` ⇒ **no second call**, stop reason `budget_exhausted`.
- With no budget configured, no `token_budget` key appears in any iteration's kwargs — assert `"token_budget" not in kwargs` for every call.
- A **fresh** `SessionCompactor` per iteration when compaction is on: assert the instantiation count equals the iteration count, and that no two iterations received the same object (`is not`).
- Out-of-range config (`0`, `99`, `"3"`, `True`, `None`) clamps to the default and never raises.

**Continuation text (DD-4):**
- Iteration 1 receives `task_text` **by identity** — the exact object AD-1141 produced (`assert kwargs["task_text"] is base_text`).
- Iteration 2's `task_text` starts with iteration 1's `task_text` and is strictly longer.
- The child's persisted `description` is byte-identical before and after a 3-iteration run.
- **Plan-identity hash stability**: `plan_seed_hash` and `_final_plan_hash` over the child's projection are byte-identical before and after.
- The `crew_execution` record has exactly the 14 keys — assert against a literal frozenset, not a length check.
- A 50 000-char prior output is head-truncated to `_MAX_CONTINUATION_OUTPUT_CHARS` with a visible marker reporting the elided count; the whole block stays under `_MAX_CONTINUATION_CHARS`.
- Open-todo labels appear **only** when the `open_todos` predicate is armed and applicable; the parent is loaded **zero** times under the other two predicates.
- `_render_continuation` raising internally ⇒ the outer loop stops cleanly with reason `continuation_failed`, the child persists the last real outcome, and `stopped_reason` is **never** `execution_exception`.
- Every authored string is clean under the **real imported** `_CAPABILITY_GAP_RE`, and so is a rendered continuation block for each stop reason.

**No-progress (DD-5):**
- Two consecutive iterations with no artifacts and identical `final_text` ⇒ stop before the cap, reason `no_progress`.
- **One** no-progress iteration followed by one that produces an `artifact_ref` ⇒ continues, and the streak resets — assert a third call happens.
- A no-progress iteration that nonetheless closes a todo (`open_todos` armed) ⇒ counts as progress.

**Governance per iteration (DD-8):**
- Two iterations ⇒ two distinct `DispatchToolExecutor` instances and two `_persist_tool_trace` calls with **distinct** refs.
- Trust demotion between iterations changes the offered tool set: seed `trust_network.get_score` to return `0.55` on the first resolve and `0.30` on the second, arm `agentic_tools.browser_enabled=True` with a registered `browser`, and assert `"browser"` is offered on iteration 1 and absent on iteration 2. Real `ToolRegistry` + real `ToolPermissionStore` (BF-287) — a mock at that boundary would paper over exactly the thing being proved.
- The 14-key record carries the **final** iteration's `tool_trace_ref`; the discarded ones appear in the INFO log with their iteration index.

**Config (DD-3, DD-7):**
- `AgenticDispatchConfig()` with no arguments has `crew_loop_until_done_enabled is False` and the documented defaults.
- The four field descriptions in the regenerated `config-reference.md` contain the worst-case product and the budget-sharing consequence — a doc-grep test, following the AD-1142 Section 11 precedent.
- `SystemConfig()` still constructs with zero configuration.

---

## Testing

**Do NOT run the full suite.** Run exactly these, serially:

```powershell
d:/ProbOS/.venv/Scripts/pytest.exe `
  tests/test_ad1155_loop_until_done.py `
  tests/test_ad859_crew_executor.py `
  tests/test_ad859a_agentic_executor.py `
  tests/test_ad1141_crew_loop_sigma.py `
  tests/test_ad1142_crew_child_compaction.py `
  tests/test_ad860_crew_verifier.py `
  tests/test_ad1080_work_item_steps.py `
  tests/test_ad1081_room_todo_tags.py `
  -q -n 0
```

`test_ad1141_crew_loop_sigma.py` and `test_ad1142_crew_child_compaction.py` are the byte-identity guards on the exact call site being modified — if either moves, the OFF path is not byte-identical. `test_ad860_crew_verifier.py` proves the convergence loop is untouched. `test_ad1080` / `test_ad1081` prove the todo state machine and its tag driver are untouched.

---

## What this does NOT change

`AgenticLoop`'s internal iteration, its `stopped_reason` set, or any of its message construction · checkpointing or suspension of any kind · `WorkItemAgenticExecutor.run`'s signature or body · `SubtaskVerifier.converge` / `converge_for_session` / `_classify_correction_terminal` · `crew_finalizer.py` · the AD-1080/1081 step state machine, `validate_step_transition`, `_all_steps_done`, `set_steps`, `update_step`, or the `[TODO_*]` tag parser · `communications.room_todos_enabled` and its rank gates · the approval inbox (#1081 / AD-1154) · plan/execute modes · AD-1142 compaction semantics · AD-1153 browser semantics or `_BROWSER_LOOP_ACTIONS` · `PARALLEL_SAFE_TOOL_IDS` · the 14-key `crew_execution` set · the `SubtaskResult` field set · `WorkItem.description` or the plan-identity hash · `tests/ablation/sigma_flags.py`.

---

## Tracking

- **`PROGRESS.md`** — AD-1155 shipped, one line. AD ceiling → **AD-1155**; next free **AD-1156**. BF ceiling → **BF-683**; next free **BF-684**.
- **`docs/development/roadmap.md`** — Bug Tracker row for **BF-683** (`converge_for_session` correction re-runs bypass `crew_token_budget` and the AD-1142 compactor), OPEN.
- **`DECISIONS.md`** (era 5) — AD-1155 entry. It must record C-1 and C-2 explicitly: *an outer loop already exists in `converge_for_session`, and `todos_remaining` is not a valid crew-child predicate because the crew path never writes `WorkItem.steps` and `_all_steps_done([])` is `False`.* Those two facts are what a future AD will otherwise rediscover the hard way.
- **`docs/development/config-reference.md`** — regenerated, not hand-edited.

## Acceptance criteria

- The headline test fails with the flag off and passes with it on, in the same test body.
- The outer cap binds, and the four-way worst case is in the config description.
- Every iteration is an independently governed run, proved by the trust-demotion test.
- No iteration persists enriched task text; plan-identity hash stability asserted.
- No-progress detection stops before the cap, and its weakness is documented rather than overstated.
- Default-OFF is byte-identical, asserted key-for-key against a literal recomputation.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-07-26, HEAD `ed3f9f52`)

```
git log --oneline -1
  ed3f9f52 AD-1153: offer the browser tool to the agentic loop (read-only v1)
git status --short
  (clean)

grep -n "class WorkItemAgenticExecutor" src/probos/cognitive/agentic_dispatch.py
  802: class WorkItemAgenticExecutor:
grep -n "outcome = await self._executor.run(" src/probos/cognitive/crew_executor.py
  1407:            outcome = await self._executor.run(
grep -rn "_executor\.run(\|executor\.run(" src/probos/
  cognitive/cognitive_agent.py:1499   cognitive/cognitive_agent.py:3517
  cognitive/crew_executor.py:1407     cognitive/crew_verifier.py:1168
  cognitive/crew_verifier.py:1391     tools/delegate_task_tool.py:184

grep -n "STEP_STATUSES\|_STEP_TRANSITIONS\|def _all_steps_done" src/probos/workforce.py
  1800: STEP_STATUSES: frozenset[str] = frozenset(
  1804: _STEP_TRANSITIONS: dict[str, frozenset[str]] = {
  1822: def _all_steps_done(steps: list[dict[str, Any]]) -> bool:
  1823:     return bool(steps) and all(... == "done" ...)
grep -rn "_all_steps_done\|set_steps\|update_step" src/probos/
  workforce.py:3020 (def set_steps)  workforce.py:3062 (def update_step)
  workforce.py:3102 (sole _all_steps_done reader)
  cognitive/dm/reply_pipeline.py:1354,1437,1440,1443,1445
  routers/workforce.py:308,327
grep -n "\bsteps\b" src/probos/cognitive/crew_executor.py src/probos/cognitive/crew_session.py
  (no matches)
grep -n "parent.steps" src/probos/crew_session_live.py
  344:        steps = loaded.parent.steps      # read-only UI projection

grep -n "room_todos_enabled\|room_todos_min_rank" src/probos/config.py
  5568: room_todos_enabled: bool = Field(       (default False)
  5572: room_todos_min_rank: str = Field(       (default "commander")
grep -n "can_validate = is_senior" src/probos/cognitive/dm/reply_pipeline.py
  1435:        can_validate = is_senior or actor == facilitator
grep -n "^TRUST_LIEUTENANT\|^TRUST_COMMANDER" src/probos/config.py
  21: TRUST_COMMANDER = 0.7
  22: TRUST_LIEUTENANT = 0.5

grep -n "async def converge_for_session\|max_rounds = min\|critiqued_task = (" src/probos/cognitive/crew_verifier.py
  1301: async def converge_for_session(
  1360:        max_rounds = min(self._max_rounds, 8)
  1362:            critiqued_task = (
grep -n "converge_for_session" src/probos/cognitive/crew_finalizer.py
  1329:        outcome = await self._verifier.converge_for_session(
  2106:                outcome = await self._verifier.converge_for_session(
grep -rn "\.converge(" src/probos/
  (no matches — dead on the live path)
grep -n "_classify_correction_terminal" -A 18 src/probos/cognitive/crew_verifier.py
  1874:  elif outcome.stopped_reason == "token_budget": failure = "correction_budget_exhausted"
  1876:  elif outcome.stopped_reason == "complete" and outcome.result_text: return None
  1878:  else: failure = "correction_execution_defect"     # max_iterations lands HERE

grep -n "AGENTIC_MAX_ITERATIONS = \|stopped_reason: str = \|self._budget is not None" src/probos/cognitive/swe_harness/agentic_loop.py
  32:  AGENTIC_MAX_ITERATIONS = 25
  697: stopped_reason: str = "complete"  # complete|max_iterations|token_budget|error
  914:     if self._budget is not None and result.total_tokens >= self._budget:
grep -n "max_parallel_tool_calls: int = Field" -A 3 src/probos/config.py
  4452: max_parallel_tool_calls: int = Field(default=3, ge=1, le=16,

grep -n "_STOPPED_REASONS = frozenset\|_MIN_CREW_TOKEN_BUDGET = \|def _normalize_token_budget\|async def _augment_task_text\|def __init__" src/probos/cognitive/crew_executor.py
  51:   _STOPPED_REASONS = frozenset({complete, error, max_iterations, token_budget, ...})
  194:  _MIN_CREW_TOKEN_BUDGET = 1024
  211:  def _normalize_token_budget(...)
  688:  def __init__(...)            (CrewTaskExecutor)
  1137: async def _augment_task_text(...)
sed -n '634,648p' src/probos/cognitive/crew_executor.py
  record = { version, parent_id, work_item_id, thread_id, assigned_to, status,
             stopped_reason, output_summary, tool_trace_ref, artifact_refs,
             tokens_used, started_at, finished_at, blocked_dependency_ids }   # 14

grep -n "_PROVISIONING_SPEC_KEYS" -A 13 src/probos/cognitive/crew_session.py
  1037: _PROVISIONING_SPEC_KEYS = frozenset({... "description" (1040) ...})
grep -n "def _final_plan_hash\|plan_seed_hash = hashlib" src/probos/cognitive/crew_session.py
  1133: def _final_plan_hash(   1174: plan_seed_hash = hashlib.sha256(...)

grep -n "crew_token_budget: int | None = Field\|max_convergence_rounds\|class AgenticDispatchConfig" src/probos/config.py
  6348: class AgenticDispatchConfig(BaseModel):
  6367: max_convergence_rounds: int = 2
  6471: crew_token_budget: int | None = Field(   6489: )   6491: @model_validator
grep -n "crew_executor = CrewTaskExecutor(" -A 22 src/probos/startup/finalize.py
  1881: crew_executor = CrewTaskExecutor(  ... 1897-1903: the AD-1142 kwargs block

grep -n "_CAPABILITY_GAP_RE = re.compile" -A 7 src/probos/cognitive/decomposer.py
  33: (pattern includes bare `lack(?:s|ing)?`, `can['\u2019]?t`, `cannot`, `unable to`)
```
