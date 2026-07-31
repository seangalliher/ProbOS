# AD-1142 — Crew-child context compaction + token budget (cognitive / crew / swe_harness)

**Issue: #1063 · Epic #1057 · lands after AD-1141 (#1062, shipped `668d0be3`), AD-1146/1147/1148 and AD-1151 (`b4e4fc93`).**
**Repo: OSS (`d:\ProbOS`). This AD = **AD-1142** (#1063). AD ceiling: AD-1151 shipped. BF ceiling: BF-679 (PROGRESS.md line 5 states "next free BF is **BF-680**"). Next free: AD-1152 / BF-680. No new AD, no new BF — the two pre-existing defects in §Defects land INSIDE this AD.**

Crew children run the `AgenticLoop` with **no compactor, no token budget, and no byte bound of any kind**. `max_iterations = 25` bounds *turns*, not *bytes*. Default-OFF.

**Read the three corrections before anything else. Issue #1063 is wrong in three places, and two of them are load-bearing for its own acceptance criteria.**

---

## ⛔ CORRECTION 1 — the §3.3 Transparency justification does NOT hold. Do not restate it.

Issue #1063's DD says:

> Compaction discards working context; the Nooplex requires observable traces of all operations. `_persist_tool_trace` already persists the durable trace, so: compact the working context, never the persisted trace.

**This is the third time this claim has propagated. It must not survive this prompt.** The honest position at HEAD `668d0be3`:

| What compaction can drop from `messages` | Recorded durably? | By what |
|---|---|---|
| `role:"tool"` content (tool outputs) | **Partially** | AD-1151 `_persist_tool_trace` (`agentic_dispatch.py:1046`), bounded by `tool_trace_output_max_chars = 8192` (`config.py:4465`) and `tool_trace_max_bytes = 262_144` (`config.py:4496`) |
| Assistant reasoning text | **No** | nothing |
| `assistant.tool_calls` correlation as the model saw it | id/name/arguments only | `ToolCallRequest` fields |
| The flattened prompt the model actually received | **No** | nothing |
| The compaction summary itself | **No** | nothing |
| The original user task after a *second* compaction pass | **No** — see Defect A | nothing |

And the AD-1151 ceiling is not a superset of the transcript: `tool_result_max_chars` **ships at 0 (unbounded transcript)**, and `resolve_tool_trace_bounds` (`agentic_loop.py:196`) only clamps the durable cap **up to a non-zero** context cap. On shipped defaults the durable trace records **less** than the model saw. AD-1151's own docstring says exactly this (`config.py:4479-4487`) — read it.

**Therefore AD-1142 stands on context-window economics, not on Transparency.** The justification, in full:

> A crew child's working context is unbounded. `max_iterations = 25` bounds turns; `tool_result_max_chars = 0` leaves each turn's tool output unbounded; AD-1147 lets one turn carry up to `max_parallel_tool_calls` results (default 3, ceiling 16). Twenty-four turns of unbounded `read_page` / `http_fetch` output exhaust any provider window, at which point `llm_client.complete()` raises and the loop returns `stopped_reason="error"` (`agentic_loop.py:700-710`) — the child fails, its dependents stay blocked, and the failure reads as an LLM error rather than as a design gap. Compaction bounds the working context. It is not a transparency mechanism and does not claim to be one.

Write it that way in the DECISIONS entry and in the module docstring. **Any wording implying the durable trace retains what compaction drops is a review blocker.**

---

## ⛔ CORRECTION 2 — compaction does NOT convert a `max_iterations` stop into a completion

Issue #1063 acceptance: *"A long-running child that previously stopped at `max_iterations` completes."* **False.** Compaction shrinks `messages`; it grants no additional iterations. A child needing 30 turns still stops at 25 with or without it. The two failure modes are distinct:

| Failure | Trigger | `stopped_reason` | Does compaction help? |
|---|---|---|---|
| Window exhaustion | provider rejects the request | `error` (`agentic_loop.py:708`) | **Yes** |
| Iteration exhaustion | loop reaches `self._max_iter` | `max_iterations` (`:791`) | **No** |

**Build against the first.** The acceptance test is *"a child whose history would exceed the window completes instead of returning `stopped_reason="error"`"* — not *"fewer `max_iterations` stops."*

---

## ⛔ CORRECTION 3 — "overflows the budget and shows the run completing" is self-contradicting

`token_budget` is a **hard stop**, not a shrink:

```
if self._budget is not None and result.total_tokens >= self._budget:
    result.stopped_reason = "token_budget"
    ... return result          # agentic_loop.py:714-724
```

and `token_budget` maps to `required_status = "failed"` (`crew_executor.py:491`). A run that overflows the budget **fails**; it cannot "complete". The two knobs are different mechanisms:

- **`compaction_threshold`** — working-context ceiling. Cross it ⇒ **shrink and continue**.
- **`token_budget`** — cumulative-spend ceiling. Cross it ⇒ **stop, mark `failed`**.

The acceptance test therefore overflows the **threshold** and asserts completion. A separate test overflows the **budget** and asserts `stopped_reason="token_budget"` + `status="failed"` + dependents not unblocked.

---

## Two pre-existing defects that AD-1142 must fix before wiring

Both are in code AD-1142 is about to point at crew children. Wiring the compactor without fixing them makes crew execution measurably worse.

### Defect A — re-compaction DROPS the original user task

`session_compactor.py:152-177`. First pass produces `[system, original_user, summary, *tail]`. When still over budget:

```python
tail_floor = len(compacted) - len(tail)                       # :166
start = max(tail_floor, align_to_group_start(compacted, len(compacted) - 2))   # :167
head = [compacted[0]] if compacted[0] is not summary_msg else []               # :174
compacted = head + [summary_msg] + compacted[start:]          # :177
```

`compacted[0]` is `system_msg`, so `head == [system_msg]` and **`original_user` at index 1 is silently discarded.** The child loses the task it was given.

`test_ad547_session_compactor.py:127` (`test_compact_preserves_original_user_task`) passes **no `budget_tokens`**, so it never reaches this branch. `test_compact_re_compacts_when_over_budget` (`:94`) asserts only `len(out) <= 5`. The defect is uncovered.

This is a direct contradiction of this AD's acceptance criterion "the original task survives compaction". **Fix it here** (DD-6). Issue #1063 says "no changes to `SessionCompactor` itself"; that fence is overruled by the Captain's acceptance list, which does not forbid it. Keep the fix to the identified splice — nothing else in the module.

### Defect B — the compaction trigger latches ON permanently

```python
and result.total_tokens >= self._compaction_threshold   # agentic_loop.py:645
```

`result.total_tokens` is **cumulative spend across every call**, incremented at `:712` and never reset. Once it crosses the threshold it is crossed forever, so **compaction runs on every remaining iteration** — one extra fast-tier LLM call per turn for the rest of the run, each summarising an already-summarised list.

It is also the wrong quantity. `NativeSWEHarnessConfig.compaction_threshold_pct = 0.8` (`config.py:4532`) is wired as `int(0.8 * 100_000) = 80_000` (`finalize.py:1548`) — plainly intended as *"80% of a 100K window"*, i.e. **occupancy**. It has been compared against cumulative spend since AD-547. **Fix it here** (DD-3).

---

## Three crew contracts that MUST NOT change

All three verified at HEAD; all three are load-bearing for AD-1127 recovery.

1. **`crew_execution` evidence is an EXACT 14-key set** (`crew_executor.py:868-882`). One extra key ⇒ `ValueError("crew_execution_evidence_invalid")` on every restart. Compaction metrics go to logs/events, **never** into this dict.
2. **`SubtaskResult`'s field set is frozen** (12 fields, `crew_executor.py:551-563`; exact-key check in `crew_finalizer.py`). Do not add a field.
3. **`description` is inside the plan-identity hash** (`crew_session.py`, `plan_seed_hash`). `task_text` is a runtime local (`crew_executor.py:1261`); this AD does not touch `description`.

Also unchanged: **the `stopped_reason` vocabulary.** `_STOPPED_REASONS` (`crew_executor.py:50-62`) already contains `token_budget`, and `_persist_terminal_result` already maps it to `failed` (`:491`). **No new reason.** Compaction changes the *distribution* of reasons; that is fine.

---

## Pinned design decisions

### DD-1 — Justification: context-window economics. Nothing else.

Per Correction 1. The module docstring, the config field descriptions and the DECISIONS entry all state the honest retention table. The AD claims exactly one thing: **the crew child's working context becomes bounded.** It claims nothing about what survives durably, because for everything except bounded tool outputs, nothing does.

### DD-2 — Per-child compactor, threaded as explicit kwargs. NOT shared with the SWE harness.

`SessionCompactor` at HEAD is **stateless** — no `__init__`, no instance attributes, one class constant (`SYSTEM_PROMPT`) and one method. Sharing the `NativeSWEHarness` instance (`finalize.py:1547`) would therefore be safe *today*. **Reject it anyway.**

- Crew children run concurrently under `asyncio.Semaphore(self._max_parallel)` (`crew_executor.py`), up to `max_parallel_subtasks` (default 3, ceiling 64). Any future instance state — a cache, a call counter, a rate limiter — becomes a silent cross-child race with no test to catch it.
- Statelessness is an accident of the current implementation, not a contract. Nothing declares it.
- Construction is free.

**Decision: `CrewTaskExecutor` constructs one `SessionCompactor()` per child invocation.** No sharing, no module singleton, no `runtime` attribute.

**Where the kwargs are threaded** — `crew_executor` → `WorkItemAgenticExecutor.run(...)` → `_loop_kwargs` (`agentic_dispatch.py:960-964`), exactly mirroring the existing `max_iterations` / `tier` pattern:

```python
_loop_kwargs: dict[str, Any] = {}
if max_iterations is not None: _loop_kwargs["max_iterations"] = max_iterations
if tier is not None:           _loop_kwargs["tier"] = tier
if compactor is not None:      _loop_kwargs["compactor"] = compactor
if compaction_threshold is not None: _loop_kwargs["compaction_threshold"] = compaction_threshold
if token_budget is not None:   _loop_kwargs["token_budget"] = token_budget
```

**Rejected: reading config inside `WorkItemAgenticExecutor.run`.** That method also serves the AD-839 conversational path and the AD-1072 delegation path. Reading config there changes non-crew behaviour — the same trap AD-1141 DD-1 identified for `task_text`. `WorkItemAgenticExecutor` stays a pure pass-through; the crew executor owns the policy.

**Rejected: a compactor on `runtime`.** Reaching `getattr(runtime, "compactor", None)` in the hot path violates DIP and repeats the wiring AD-1141 DD-12 explicitly moved to constructor injection.

### DD-3 — Trigger on working-context occupancy, not cumulative spend (fixes Defect B)

Replace the trigger expression at `agentic_loop.py:645`:

```python
and _estimate_context_tokens(messages) >= self._compaction_threshold
```

`_estimate_context_tokens` is a **new module-local function in `agentic_loop.py`**, not an import of `estimate_messages_tokens`:

```python
def _estimate_context_tokens(messages: list[dict]) -> int:
    """Approximate the tokens currently occupying the working context.

    Same len/4 approximation as ``session_compactor.estimate_tokens`` (AD-547b
    still owns the exact tokenizer), but ALSO counts the serialised
    ``tool_calls`` payload an AD-1146 assistant turn carries — which
    ``estimate_messages_tokens`` ignores, undercounting a structured history by
    the whole tool-call array.
    """
```

Three consequences, all wanted:

1. **The latch is gone.** After a successful compaction the occupancy drops below the threshold, so the next iteration does not re-fire. Compaction becomes O(number of times the context actually refills) instead of O(remaining iterations).
2. **`compaction_threshold_pct` finally means what its name says** on the SWE-harness path too.
3. `budget_tokens=self._compaction_threshold` (`:650`) is now *correct* — the compactor targets the same occupancy ceiling that triggered it. **Leave that line alone.**

**This changes `NativeSWEHarness` behaviour.** Accepted, and stated in the build report: `native_swe_harness.enabled` defaults to `False` (`config.py`), so no shipped behaviour changes; the SWE path gains the fix for free. Add a test that pins the new trigger on a synthetic loop with a *high cumulative* `total_tokens` and a *small* message list, asserting compaction does **not** fire.

**Honest limit, state it in the docstring:** the estimator is a character heuristic. AD-547b's forcing function (first false trip diverging >25% from real counting) still applies and this AD does not discharge it.

### DD-4 — Post-compaction guard: compaction is BEST-EFFORT, not a guarantee

`compact()` can legitimately return a list still over the threshold. `align_to_group_start` (`session_compactor.py:34`) walks the preserved tail **backwards** to a group boundary, so a single AD-1147 turn carrying up to 16 unbounded tool results is preserved **whole** — `preserve_count = 5` is not an upper bound on tail length once one group exceeds five messages. If that one group alone exceeds the threshold, no amount of compaction reaches it.

Therefore, after the `compact()` call:

1. **Boundary-validate the return.** The compactor is injected as `Any` — it is a module boundary, so Defense in Depth applies. If the returned value is not a non-empty `list`, log a contextual warning and **keep the previous `messages`**. Do not raise.
2. **If occupancy is still ≥ threshold, log once at WARNING** naming the estimated size, the threshold and the largest single group — then continue. The run proceeds and may still hit the provider limit; that is honest degradation, not a silent one.

**Do not add a retry loop, and do not raise.** Existing tier is log-and-degrade (`agentic_loop.py:653-658`); keep it.

### DD-5 — Group-boundary invariant, asserted directly

**Invariant (test this literally, do not paraphrase it in prose only):**

> In the list returned by `compact()`, every message with `role == "tool"` carries a `tool_call_id` present in the `tool_calls` array of the nearest preceding message whose `role != "tool"`, and that message has `role == "assistant"`.

Test helper, local to the test module:

```python
def _orphaned_tool_call_ids(messages: list[dict]) -> list[str]:
    owned: set[str] = set()
    orphans: list[str] = []
    for m in messages:
        role = m.get("role")
        if role == "tool":
            if m.get("tool_call_id") not in owned:
                orphans.append(m.get("tool_call_id"))
        elif role == "assistant":
            owned = {tc.get("id") for tc in (m.get("tool_calls") or [])}
        else:
            owned = set()
    return orphans
```

Cases that must all yield `[]`:

| Case | Why it is separate |
|---|---|
| First-pass compaction, tail starts mid-group | The `align_to_group_start` path at `:104` |
| Re-compaction over budget | The independent `max(tail_floor, align_to_group_start(...))` path at `:167` |
| **Summary is the first message** (`system_msg is None` **and** `original_user is None`) | `head = []` at `:174`; the summary must not be duplicated *and* must not precede an orphan |
| Only `system_msg` survives (no user turn in history) | `head = [system_msg]` with no `original_user` to splice |
| A single group of 16 `role:"tool"` entries (AD-1147 ceiling) | The tail grows past `preserve_count`; DD-4's still-over-threshold warning fires |
| `structured_tool_messages = False` (the shipped default) | No `role:"tool"` entries exist; the helper must return `[]` trivially and compaction must still be exercised |

The summary message is `{"role": "user", ...}` (`:143-146`) and is spliced immediately before the tail, so it never sits *inside* a group. Assert that too.

### DD-6 — What compaction preserves (fixes Defect A)

**Guaranteed to remain in the returned list, in this order:**

1. The `role:"system"` message, **by identity**, when the input had one at index 0.
2. The **first** `role:"user"` message after index 0 — the original task — **by identity**, when one exists and it is not already the system message.
3. Exactly one summary message, `role:"user"`, prefixed `[CONTEXT SUMMARY — earlier exchanges]`.
4. A group-aligned trailing slice.

**Nothing else is guaranteed.** Say so explicitly — intermediate reasoning turns and older tool outputs are exactly what is dropped, and per Correction 1 the reasoning turns are recorded nowhere.

**The fix** at `session_compactor.py:174-177` — preserve the head *pair* rather than `compacted[0]`:

```python
head = [m for m in (system_msg, original_user)
        if m is not None and m is not summary_msg]
# de-duplicate by identity in case system_msg is original_user
compacted = head + [summary_msg] + compacted[start:]
```

with `tail_floor` recomputed against the new head length so `start` cannot reach back into it. **Verify the arithmetic against the live `start` computation at `:167` before writing** — `tail_floor = len(compacted) - len(tail)` is computed on the *first-pass* list, and changing the head does not change that list, so it should be unaffected; confirm rather than assume.

Add the missing coverage as regression tests on the existing suite shape: `test_compact_preserves_original_user_task` **with** `budget_tokens` set low enough to force re-compaction.

### DD-7 — Threshold and budget defaults, and the AD-1147 interaction

New fields on **`AgenticDispatchConfig`** (`config.py:6303`), beside the other `crew_*` knobs at `:6316-6351`:

| Field | Default | Bounds | Notes |
|---|---|---|---|
| `crew_compaction_enabled` | `False` | — | **bool.** The single gate. |
| `crew_compaction_threshold_tokens` | `60_000` | `ge=1_000, le=1_000_000` | Working-context ceiling (DD-3 units). |
| `crew_token_budget` | `None` | `ge=1024` | Cumulative-spend ceiling. **Independent of the gate** — see below. |

**Why `AgenticDispatchConfig` and not `AgenticLoopConfig`:** `AgenticLoopConfig` is read by *both* loop construction sites (`agentic_dispatch.py:1000` and `finalize.py:1541`); a crew-only knob there would silently apply to the SWE harness, which already has its own `token_budget` and `compaction_threshold_pct` on `NativeSWEHarnessConfig` (`config.py:4531-4532`). Two sources of truth for the same harness is exactly the drift `AgenticLoopConfig`'s docstring exists to prevent.

**Why `60_000`:** the SWE harness compacts at `0.8 × 100_000 = 80_000`. Crew children run up to `max_parallel_subtasks` concurrently (default 3, ceiling 64), so N children each holding 80K is N×80K of simultaneous provider load, and an AD-1141 child additionally carries a Σ block plus an `expected_output` block ahead of the task. 60K at the default 3-way fan-out is 180K concurrent. **This is a starting value, not a derived one — say so in the field description** (AD-1141 DD-3 precedent). It is the first knob to tune if children still fail with `stopped_reason="error"`.

**AD-1147 interaction, stated arithmetically in the field description:** one turn can append up to `max_parallel_tool_calls` results (default 3, ceiling 16). With `tool_result_max_chars = 0` each is unbounded, so **a single turn can cross any threshold** and DD-4's best-effort warning is the honest outcome. With a non-zero `tool_result_max_chars` the per-turn ceiling is `max_parallel_tool_calls × tool_result_max_chars`; at the AD-1147 ceiling of 16 that is 16 × cap, which must stay comfortably under `crew_compaction_threshold_tokens × 4` characters or compaction cannot converge. **Do not add a validator relating them** (DD-8) — state the relation in the description and assert it in a test that documents the ceiling.

**`crew_token_budget` is NOT gated on `crew_compaction_enabled`.** They are independent: the budget is a Safety Budget ceiling that is useful with or without compaction, and it defaults to `None` (no budget) so enabling compaction does not silently introduce a new failure mode. Enabling the budget **does** change outcomes — a child that would have produced partial output now returns `stopped_reason="token_budget"` ⇒ `status="failed"` ⇒ **dependents stay blocked** (`crew_executor.py:491`). State that consequence in the field description and prove it in a test.

### DD-8 — Resolve-and-clamp, never a cross-field validator

Follow the AD-1151 precedent exactly (`resolve_tool_trace_bounds`, `agentic_loop.py:196`, and the `AgenticLoopConfig` docstring at `config.py:4380-4396`). `routers/config.py` writes config by `model_dump() → _deep_merge → SystemConfig(**merged)`, which marks every field explicitly set — so a `model_fields_set`-scoped raise turns an unrelated `POST /config` into a 422 and can then persist a combination that refuses to boot; `model_copy(update=...)` skips validators outright.

`AgenticDispatchConfig` **already carries** a `@model_validator(mode="after")` (`config.py:6353`). **Do not extend it.** Add instead:

```python
def resolve_crew_compaction_settings(cfg: Any) -> dict[str, Any]
```

in `crew_executor.py` (crew-scoped policy, crew-scoped module), returning exactly the `{compactor, compaction_threshold, token_budget}` keyword set, and `{}` when the gate is off. Degrade a missing / non-integer / negative / `bool` value to the module default rather than failing construction — `type(...) is int` also rejects `bool`, matching `resolve_tool_result_bounds` (`agentic_loop.py:155-179`).

### DD-9 — Default-OFF, byte-identical, and pinned in the ablation

**Gate off ⇒ `_loop_kwargs` is byte-identical to today** — the same dict with the same keys in the same order. Assert it against a recording double, not by inspection.

**Ablation surface.** The knobs go into **`PINNED_AGENTIC_LOOP`** (`tests/ablation/sigma_report.py:101`), **not** into `sigma_flags.py`:

- `PINNED_AGENTIC_LOOP` feeds `config_fingerprint` (`:139`), so the ablation artifact records the compaction posture. `sigma_flags.py` does not reach the fingerprint.
- `set_paths` accepts any type, so all three knobs pin together; `apply_flags` (`sigma_flags.py:124`) requires every path to resolve to a **`bool`**, which would force the int/`None` knobs out and split the pinning across two files.
- Compaction is not a Σ treatment. A key in `SIGMA_ON`/`SIGMA_OFF` with the **same** value in both arms would keep `set(SIGMA_ON) == set(SIGMA_OFF)` green but would misrepresent a non-Σ knob as an arm dimension.

Add `agentic_dispatch.crew_compaction_enabled: False`, `agentic_dispatch.crew_compaction_threshold_tokens: 60000`, `agentic_dispatch.crew_token_budget: None` to `PINNED_AGENTIC_LOOP`, update its docstring (`:99-100`, which currently names only AD-1146/1147/1148/1151), and **do not touch `sigma_flags.py`**. Its two structural guards must stay green unchanged — run them.

`crew_token_budget` is `None`; confirm `set_paths`' same-type check (`sigma_flags.py:110-118`) accepts `None` against a `None` default. **If it does not, pin only the two knobs that resolve and say so in the build report — do not loosen the type check.**

### DD-10 — Failure isolation: log-and-degrade, unchanged tier

Compaction failure is already absorbed inside the loop (`agentic_loop.py:653-658`) and must stay there. Additionally, **`resolve_crew_compaction_settings` must not raise** — a malformed config degrades to the gate being off, logged. A crew child must never fail because a compaction knob was mistyped.

`crew_executor.py:1271` wraps `self._executor.run(...)` in a `try` that persists `stopped_reason="execution_exception"`; the settings resolution happens **outside** that try, in `__init__`, so a config problem cannot fail every child of every session (AD-1141 DD-8 precedent).

### DD-11 — Strings that reach the model must be clean under the real gap regex

Compaction inserts `"[CONTEXT SUMMARY — earlier exchanges]"` (`session_compactor.py:145`) and, on LLM failure, `"[compaction summary unavailable]"` (`:126`) **into the crew child's prompt**. Neither has ever been checked against `_CAPABILITY_GAP_RE` (`decomposer.py:33-40`, `re.IGNORECASE`), because until this AD they never reached a crew child.

**Assert both against the REAL imported regex** — import it, do not re-type it. `lack` is a bare substring and `not available` is a phrase; `"unavailable"` is one word and should pass, but **prove it, do not reason about it** (this is the AD-1140 lesson). If either trips, reword the constant and re-run the check.

---

## Build

1. **`src/probos/cognitive/swe_harness/agentic_loop.py`**
   - New module-local `_estimate_context_tokens(messages) -> int` (DD-3), counting `content` plus serialised `tool_calls`.
   - Trigger at `:645` switches from `result.total_tokens` to `_estimate_context_tokens(messages)`.
   - Post-`compact()` boundary validation + still-over-threshold warning (DD-4). `budget_tokens=self._compaction_threshold` at `:650` is **unchanged**.
2. **`src/probos/cognitive/swe_harness/session_compactor.py`**
   - Defect A fix at `:174-177` only (DD-6). Nothing else in the module.
3. **`src/probos/cognitive/agentic_dispatch.py`**
   - `WorkItemAgenticExecutor.run` gains keyword-only `compactor: Any = None`, `compaction_threshold: int | None = None`, `token_budget: int | None = None`.
   - `_loop_kwargs` (`:960-964`) gains three `if … is not None` lines, in that order (DD-2). Pure pass-through — **no config read here**.
4. **`src/probos/cognitive/crew_executor.py`**
   - `resolve_crew_compaction_settings(cfg)` (DD-8).
   - `CrewTaskExecutor.__init__` gains keyword-only `crew_compaction_enabled: bool = False`, `crew_compaction_threshold_tokens: int = 60_000`, `crew_token_budget: int | None = None` (defaults matching config, so every existing construction site is unchanged).
   - At `:1271`, spread the resolved settings — a fresh `SessionCompactor()` **per child** (DD-2) — into `self._executor.run(...)`. `task_text` and `extra_context` untouched.
5. **`src/probos/startup/finalize.py`** — pass the three values into `CrewTaskExecutor(...)` at `:1881` from `config.agentic_dispatch`, beside the AD-1141 kwargs.
6. **`src/probos/config.py`** — three `AgenticDispatchConfig` fields (DD-7). **Do not extend the existing `@model_validator` at `:6353`.**
7. **`tests/ablation/sigma_report.py`** — three paths into `PINNED_AGENTIC_LOOP` + docstring (DD-9). `sigma_flags.py` untouched.
8. **`tests/test_ad1142_crew_child_compaction.py`** (NEW) — ≈30 tests.
9. **`tests/test_ad547_session_compactor.py`** — regression tests for Defect A (DD-6).

---

## Acceptance

### 1. Default-OFF byte-identity

- `crew_compaction_enabled=False` ⇒ `resolve_crew_compaction_settings` returns `{}`.
- The `_loop_kwargs` dict built in `agentic_dispatch.py` is byte-identical to today — same keys, same order — captured with a recording double over `AgenticLoop.__init__`.
- The constructed `AgenticLoop` has `_compactor is None`, `_compaction_threshold is None`, `_budget is None`.
- Zero `SessionCompactor` instantiations across a full crew run with the gate off.
- `task_text` and `extra_context` passed to `WorkItemAgenticExecutor.run` are unchanged from AD-1141 (re-assert; do not assume).

### 2. Crew contracts untouched

- The **exact 14-key** `crew_execution` set asserted as a literal; a real run with the gate ON produces exactly it. **No compaction metric appears in it.**
- The **frozen 12-field** `SubtaskResult` set asserted as a literal against `dataclasses.fields`.
- `set(_STOPPED_REASONS)` asserted as a literal and unchanged.
- Plan-identity hash stable across a gate-ON run; AD-1127 recovery green.

### 3. The headline — a child that would exhaust the window completes

> Build a synthetic child whose tool results accumulate past `crew_compaction_threshold_tokens`. With the gate **OFF**, the stub LLM raises once the assembled prompt exceeds a fixed size and the loop returns `stopped_reason="error"`. With the gate **ON** and nothing else changed, the same run returns `stopped_reason="complete"`.

Per Correction 2 the contrast is against `error`, **not** `max_iterations`. Assert both arms in one test so the delta is attributable.

### 4. Trigger semantics (Defect B)

- **No latch:** after compaction brings occupancy under the threshold, the next iteration does **not** compact. Count `compact()` invocations against a recording compactor across a ≥10-iteration run and assert the count matches the number of times occupancy actually re-crossed — not the iteration count.
- **Occupancy, not spend:** a loop with `total_tokens` far above the threshold but a 3-message history does **not** compact.
- **Spend, not occupancy:** a loop with a large history but small `total_tokens` **does** compact.

### 5. Best-effort, not a guarantee (DD-4)

- A single tool-call group larger than the threshold ⇒ compaction runs, occupancy stays over, a contextual WARNING naming size/threshold is emitted, and **the run continues**.
- A compactor returning `None`, `""`, `{}` or `[]` ⇒ the previous `messages` are kept, a contextual WARNING is emitted, and the run continues. **No raise.**

### 6. Group-boundary safety (DD-5)

- `_orphaned_tool_call_ids(...) == []` for **all six** cases in the DD-5 table, including the summary-is-first-message case and the 16-result AD-1147 group.
- The summary message never appears between an `assistant.tool_calls` and its `role:"tool"` replies.
- The summary appears **exactly once** in the re-compacted list (no duplicate when `head` is empty).

### 7. Preservation (DD-6 / Defect A)

- System prompt preserved **by identity** through both passes.
- **Original user task preserved by identity through the re-compaction pass** — the currently-failing case. Test it with `budget_tokens` low enough to force the second pass.
- Order asserted: system, original user, summary, tail.
- `system_msg is original_user` (degenerate input) ⇒ no duplicate entry.

### 8. Token budget (DD-7)

- `crew_token_budget` set and exceeded ⇒ `stopped_reason="token_budget"`, `status="failed"`, and a dependent child is **not** unblocked.
- `crew_token_budget=None` (default) ⇒ `AgenticLoop._budget is None`; unchanged from today.
- The budget is independent of the gate: budget set + gate off works; gate on + budget `None` works.
- `resolve_crew_compaction_settings` with a malformed / negative / `bool` value degrades to the default and **does not raise** (DD-10).

### 9. Framing (DD-11)

- `SessionCompactor.SYSTEM_PROMPT`, the `[CONTEXT SUMMARY — earlier exchanges]` prefix and `[compaction summary unavailable]` are all clean under the **real imported** `_CAPABILITY_GAP_RE`.

### 10. Ablation surface (DD-9)

- The three paths are present in `PINNED_AGENTIC_LOOP` and resolve on a live `SystemConfig()`.
- `config_fingerprint` changes when a pinned compaction value changes (proves it is actually in the fingerprint).
- `sigma_flags.py` is **unmodified** and both structural guards are green.

### 11. Honest documentation

- The DECISIONS entry, the `crew_compaction_*` field descriptions and the module docstring state the Correction-1 retention table: bounded tool outputs survive via AD-1151; **reasoning turns, assistant text, the flattened prompt and the summary itself survive nowhere.**
- Grep the diff for `Transparency`, `§3.3`, `durable trace keeps` and `3.3` — any surviving claim that the trace retains what compaction drops is a build failure.

- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Validation plan — targeted only

**The full suite takes ~21 minutes and must NOT be run.**

- **Focused:** `tests/test_ad1142_crew_child_compaction.py -q -n 0`
- **Loop + compactor, ONCE, after the focused gate is green:**
  `tests/test_ad547_session_compactor.py tests/test_ad1146_multiturn_messages.py tests/test_ad1147_parallel_tools.py tests/test_ad1148_tool_result_bounds.py tests/test_ad1151_durable_tool_outputs.py tests/test_ad549_harness_config_metadata.py -q -n 0`
- **Crew contracts, ONCE:**
  `tests/test_ad859_crew_executor.py tests/test_ad859a_agentic_executor.py tests/test_ad1141_crew_loop_sigma.py tests/test_ad1124_crew_session_contract.py tests/test_ad1125_room_bound_execution.py tests/test_ad1126_verified_finalization.py tests/test_ad1127_crew_session_lifecycle_recovery.py tests/test_ad867_crew_orchestrator.py tests/test_ad860_crew_verifier.py -q -n 0`
- **Ablation guard, ONCE:** `tests/ablation/test_sigma_harness_structural.py -q -n 0`

Before running, **grep for any other suite that touches the changed symbols** and add it to the second gate:

```
tests/  →  SessionCompactor · compaction_threshold · _loop_kwargs · token_budget
           · align_to_group_start · estimate_messages_tokens · PINNED_AGENTIC_LOOP
```

`test_ad547_session_compactor.py`, `test_ad1146_multiturn_messages.py`, `test_ad1147_parallel_tools.py`, `test_ad1148_tool_result_bounds.py`, `test_ad1151_durable_tool_outputs.py`, `test_ad1141_crew_loop_sigma.py`, `test_ad859_crew_executor.py`, `test_ad859a_agentic_executor.py` and `test_ad549_harness_config_metadata.py` were listed from `tests/` and exist. The crew-contract file names above follow the AD-1141 prompt's verified list — **confirm each exists before running.**

| Suite | What it pins |
|---|---|
| `test_ad547_session_compactor.py` | The compactor, including the Defect A splice. |
| `test_ad1146_multiturn_messages.py` | `align_to_group_start` and the structured message shape. |
| `test_ad1147_parallel_tools.py` | The group size the tail must preserve whole. |
| `test_ad1148_tool_result_bounds.py` | The per-result cap that bounds per-turn growth. |
| `test_ad1151_durable_tool_outputs.py` | The durable trace this AD must not touch. |
| `test_ad549_harness_config_metadata.py` | The SWE-harness config whose trigger semantics DD-3 changes. |
| `test_ad859a_agentic_executor.py` | `_loop_kwargs` byte-identity. |
| `test_ad1141_crew_loop_sigma.py` | `task_text` / `extra_context`, which must stay unchanged. |
| `test_ad1127_crew_session_lifecycle_recovery.py` | **The recovery path all three contracts protect.** |

**If `test_ad1127_crew_session_lifecycle_recovery.py` or `test_ad1124_crew_session_contract.py` goes red, STOP and surface it.** Red there means a crew contract moved. Do not attempt a fix.

---

## Do NOT build here

❌ Changing AD-1148 truncation (`truncate_tool_output`, `resolve_tool_result_bounds`, the head/tail split, or the `tool_result_max_chars` **default**). ❌ Changing AD-1151 trace persistence (`_persist_tool_trace`, `build_tool_trace_payload`, `resolve_tool_trace_bounds`, `_durable_head_tail`, or either trace bound). ❌ Any change to the 14-key `crew_execution` set, the 12-field `SubtaskResult`, `_STOPPED_REASONS`, the `required_status` map, `description`, or the plan projection. ❌ **New `stopped_reason` values.** ❌ Normalising Oracle tier scores (known defect — out of scope). ❌ AD-554 convergence wiring. ❌ Anything touching the episodic shard, `MemoryAccessPolicy`, or `OWN_SHARD_PLUS_PUBLIC`. ❌ The multi-turn `LLMRequest` refactor — the AD-1146 structured path already exists and is default-OFF; this AD does not flip it. ❌ Any change to `SessionCompactor` beyond the Defect A splice at `:174-177` — **not** `preserve_count`, **not** `SYSTEM_PROMPT` (except a reword if DD-11's regex check trips), **not** `align_to_group_start`, **not** `estimate_tokens`. ❌ Reading config inside `WorkItemAgenticExecutor.run`. ❌ A shared or `runtime`-held compactor instance. ❌ Extending the `AgenticDispatchConfig` `@model_validator` or adding any cross-field validator. ❌ Editing `tests/ablation/sigma_flags.py` or loosening `apply_flags`. ❌ Per-session (as opposed to per-child) budget ceilings. ❌ Compaction inside `NativeSWEHarness` wiring at `finalize.py:1547-1548` — the trigger fix reaches it through the loop; the wiring is unchanged. ❌ Federation transport or any import from `src/probos/federation/`. ❌ Editing `config/system.yaml` (skip-worktree `S`, Captain-local). ❌ A new AD or BF number.

---

## Files (verify each at build)

- `src/probos/cognitive/swe_harness/agentic_loop.py` — `_estimate_context_tokens`, the `:645` trigger, the DD-4 guards.
- `src/probos/cognitive/swe_harness/session_compactor.py` — the `:174-177` splice only.
- `src/probos/cognitive/agentic_dispatch.py` — `run(...)` kwargs, `_loop_kwargs` at `:960-964`.
- `src/probos/cognitive/crew_executor.py` — `resolve_crew_compaction_settings`, `__init__` kwargs, the `:1271` call site.
- `src/probos/startup/finalize.py` — `CrewTaskExecutor(...)` at `:1881`.
- `src/probos/config.py` — three `AgenticDispatchConfig` fields.
- `tests/ablation/sigma_report.py` — `PINNED_AGENTIC_LOOP` at `:101` + docstring at `:99`.
- `tests/test_ad1142_crew_child_compaction.py` (NEW).
- `tests/test_ad547_session_compactor.py` — Defect A regressions.

---

## Builder checks (unverifiable from the spec — confirm before relying on them)

1. **Import direction.** DD-3 keeps the estimator module-local in `agentic_loop.py` precisely to avoid an `agentic_loop → session_compactor` module-level import. Confirm no such import exists today and do not add one. If you judge reuse cleaner, prove there is no cycle (`session_compactor` imports `probos.types` and, under `TYPE_CHECKING`, `llm_client`) **and** show the undercount of `tool_calls` is handled.
2. **Does `tests/ablation/sigma_flags.set_paths` accept `None`?** `:110-118` does `type(current) is not type(value)`. `None` against a `None` default gives `NoneType is NoneType` — should pass. **Verify.** If it does not, pin only the two resolvable knobs and say so in the build report; **do not loosen the check.**
3. **`tail_floor` after the DD-6 head change.** `tail_floor` is computed on the first-pass list at `:166`, before the head splice, so it should be unaffected. Re-derive it against the live code rather than trusting this note.
4. **`response.tokens_used` semantics.** DD-3's "no latch" test needs to construct a loop whose cumulative `total_tokens` is high while `messages` is short. Confirm `tokens_used` is per-call (`agentic_loop.py:712` accumulates it) and that a stub LLM can drive it independently of message length.
5. **Recording-double shape for `AgenticLoop.__init__`.** The `_loop_kwargs` byte-identity assertion needs the exact kwargs as passed. Check what `tests/test_ad859a_agentic_executor.py` already uses and follow it (BF-287: real fixtures at the registry/permission boundary; a double at the *loop constructor* seam is fine because that is the thing under observation).
6. **Does the ablation runner rebuild `config_fingerprint` from `PINNED_AGENTIC_LOOP` alone?** Acceptance §10 asserts the fingerprint moves when a pinned compaction value changes. Confirm `config_fingerprint` (`sigma_report.py:139`) is fed the whole pinned dict and not a filtered subset.
7. **`crew_executor.py:1271` line drift.** AD-1141 shifted this file; re-locate `self._executor.run(` before editing rather than trusting the number.

---

## Tracking

`PROGRESS.md` · `docs/development/roadmap.md` · `DECISIONS.md`.

The AD-1142 entry must record: that the justification is **context-window economics, not §3.3 Transparency**, with the explicit retention table and the statement that reasoning turns, assistant text and the flattened prompt are recorded **nowhere** (correcting #1063 for the third time); that **compaction does not convert a `max_iterations` stop into a completion** (correcting #1063's headline acceptance); that **`token_budget` is a hard stop that marks the child `failed` and leaves dependents blocked**, which is why it defaults to `None`; that the compaction trigger was **latched on cumulative spend** since AD-547 and now measures **working-context occupancy**, which also makes `compaction_threshold_pct` mean what its name says on the SWE path; that re-compaction **dropped the original user task** and now preserves it; that compaction is **best-effort** and cannot converge when a single AD-1147 tool-call group exceeds the threshold; that the compactor is **per-child, never shared**, because statelessness is an accident and children run concurrently; and that `crew_compaction_threshold_tokens = 60_000` is a **starting value, not a derived one**.

---

## Done-when

Gate off ⇒ `_loop_kwargs` byte-identical, zero `SessionCompactor` instantiations, `task_text` and `extra_context` unchanged; the 14-key evidence set, the 12-field `SubtaskResult` and `_STOPPED_REASONS` asserted as literals and unchanged, AD-1127 recovery green; the headline test showing a window-exhausting child going from `stopped_reason="error"` to `"complete"` on the gate alone; the trigger proven occupancy-based and un-latched in all three directions; compaction proven best-effort with a contextual warning and no raise when it cannot converge or the compactor misbehaves; `_orphaned_tool_call_ids == []` across all six DD-5 cases including summary-first and a 16-result group; system prompt **and original user task** preserved by identity through the re-compaction pass; the token budget proven to fail the child and leave dependents blocked, and proven independent of the gate; every model-facing compaction string clean under the real `_CAPABILITY_GAP_RE`; the three knobs pinned in `PINNED_AGENTIC_LOOP` with the fingerprint moving and `sigma_flags.py` untouched with both guards green; the diff greppably free of any surviving Transparency claim; focused + loop/compactor + crew-contract + ablation gates green; **verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-07-25, HEAD `668d0be3`)

```
git log --oneline -1
  668d0be3 AD-1141: crew loop wired to Sigma - consult before, publish after

# Crew children get NO compaction — the issue's core premise, still true.
grep -n "_loop_kwargs" src/probos/cognitive/agentic_dispatch.py
  960:  _loop_kwargs: dict[str, Any] = {}
  962:      _loop_kwargs["max_iterations"] = max_iterations
  964:      _loop_kwargs["tier"] = tier
  988:      **_loop_kwargs,

grep -rn "compactor=" src/probos/
  src/probos/startup/finalize.py:1547:  compactor=SessionCompactor(),
  # sole wiring in the tree — NativeBuilderHarness only

grep -n "compaction_threshold=int" src/probos/startup/finalize.py
  1548:  compaction_threshold=int(cfg.compaction_threshold_pct * 100_000),

grep -n "self._executor.run(" src/probos/cognitive/crew_executor.py
  1271:  outcome = await self._executor.run(
  # call site passes NO max_iterations and NO tier => AGENTIC_MAX_ITERATIONS / AGENTIC_DEFAULT_TIER

grep -n "AGENTIC_MAX_ITERATIONS = " src/probos/cognitive/swe_harness/agentic_loop.py
  32:  AGENTIC_MAX_ITERATIONS = 25

# AgenticLoop accepts all three kwargs today.
grep -n "compactor\|compaction_threshold\|token_budget" src/probos/cognitive/swe_harness/agentic_loop.py
  560:  token_budget: int | None = None,
  563:  compactor: Any | None = None,
  564:  compaction_threshold: int | None = None,

# Defect B — trigger reads CUMULATIVE spend, never reset.
grep -n "total_tokens\|compaction_threshold" src/probos/cognitive/swe_harness/agentic_loop.py
  645:  and result.total_tokens >= self._compaction_threshold
  650:  budget_tokens=self._compaction_threshold,
  712:  result.total_tokens += int(response.tokens_used or 0)

# token_budget is a HARD STOP (Correction 3).
grep -n "stopped_reason = \"token_budget\"" src/probos/cognitive/swe_harness/agentic_loop.py
  715:  result.stopped_reason = "token_budget"
grep -n "\"token_budget\": " src/probos/cognitive/crew_executor.py
  492:  "token_budget": "failed",

# Correction 2 — window exhaustion is `error`, not `max_iterations`.
grep -n 'result.stopped_reason = "error"\|result.stopped_reason = "max_iterations"' \
     src/probos/cognitive/swe_harness/agentic_loop.py
  708:  result.stopped_reason = "error"
  791:  result.stopped_reason = "max_iterations"     # after the for-loop, not inside it

# Defect A — re-compaction splices compacted[0], dropping original_user.
grep -n "tail_floor\|start = max(\|head = (\|compacted = head" \
     src/probos/cognitive/swe_harness/session_compactor.py
  166:  tail_floor = len(compacted) - len(tail)
  167:  start = max(
  174:  head = (
  177:  compacted = head + [summary_msg] + compacted[start:]

grep -n "def test_compact" tests/test_ad547_session_compactor.py
  94:   test_compact_re_compacts_when_over_budget          # asserts only len(out) <= 5
  127:  test_compact_preserves_original_user_task          # no budget_tokens => first pass only

# AD-1146 group alignment still present.
grep -n "def align_to_group_start" src/probos/cognitive/swe_harness/session_compactor.py
  34:   def align_to_group_start(messages: list[dict], index: int) -> int:
grep -n "align_to_group_start(" src/probos/cognitive/swe_harness/session_compactor.py
  104:  tail = messages[align_to_group_start(messages, len(messages) - preserve_count):]
  167-169: start = max(tail_floor, align_to_group_start(compacted, len(compacted) - 2))

# AD-1151 records tool_calls + tool_results ONLY (Correction 1).
grep -n "build_tool_trace_payload" src/probos/cognitive/agentic_dispatch.py
  1091:  _entries, blob = build_tool_trace_payload(
  1092:      getattr(agentic_result, "tool_calls", []),
  1093:      getattr(agentic_result, "tool_results", []),
  # tool_calls + tool_results ONLY — no assistant text, no reasoning turns

grep -n "tool_result_max_chars: int = Field" src/probos/config.py
  4406:  tool_result_max_chars: int = Field(       # default=0 => UNBOUNDED transcript
grep -n "tool_trace_output_max_chars: int = Field\|tool_trace_max_bytes: int = Field" src/probos/config.py
  4465:  tool_trace_output_max_chars: int = Field(  # default=8192
  4496:  tool_trace_max_bytes: int = Field(         # default=262_144

# AD-1147 parallelism ceiling.
grep -n "PARALLEL_TOOL_CALLS_DEFAULT\|PARALLEL_TOOL_CALLS_MAX" src/probos/cognitive/swe_harness/agentic_loop.py
  87:   PARALLEL_TOOL_CALLS_DEFAULT = 3
  88:   PARALLEL_TOOL_CALLS_MAX = 16

# Config homes.
grep -n "class AgenticDispatchConfig\|class AgenticLoopConfig\|class NativeSWEHarnessConfig" src/probos/config.py
  4369: class AgenticLoopConfig(BaseModel)
  4513: class NativeSWEHarnessConfig(BaseModel)
  6303: class AgenticDispatchConfig(BaseModel)
grep -n "token_budget: int | None = Field\|compaction_threshold_pct: float" src/probos/config.py
  4531:  token_budget: int | None = Field(default=None, ge=1024)
  4532:  compaction_threshold_pct: float = Field(default=0.8, ge=0.1, le=0.95)
grep -n "model_validator(mode=\"after\")" src/probos/config.py   # AgenticDispatchConfig
  6353:  @model_validator(mode="after")   # do NOT extend

# Crew contracts.
grep -n "crew_execution_evidence_invalid" src/probos/cognitive/crew_executor.py
  882:  raise ValueError("crew_execution_evidence_invalid")   # exact 14-key set at :868-881
grep -n "_STOPPED_REASONS = frozenset" src/probos/cognitive/crew_executor.py
  50:   _STOPPED_REASONS = frozenset({... "token_budget" ...})

# Construction site.
grep -n "crew_executor = CrewTaskExecutor(" src/probos/startup/finalize.py
  1881:  crew_executor = CrewTaskExecutor(

# Ablation pinning target (DD-9).
grep -n "PINNED_AGENTIC_LOOP\|def config_fingerprint\|def apply_pinned_config" tests/ablation/sigma_report.py
  101:  PINNED_AGENTIC_LOOP: dict[str, Any] = { ... 8 agentic_loop.* paths ... }
  139:  def config_fingerprint(pinned: dict[str, Any]) -> str
  146:  def apply_pinned_config(config: SystemConfig) -> SystemConfig
grep -n "def apply_flags\|def set_paths" tests/ablation/sigma_flags.py
  100:  def set_paths(...)      # any type, same-type check
  124:  def apply_flags(...)    # requires bool

# Test files confirmed present.
ls tests/ | grep -E "ad547|ad1146|ad1147|ad1148|ad1151|ad1141|ad859|ad549"
  test_ad547_session_compactor.py   test_ad1141_crew_loop_sigma.py
  test_ad1146_multiturn_messages.py test_ad1147_parallel_tools.py
  test_ad1148_tool_result_bounds.py test_ad1151_durable_tool_outputs.py
  test_ad549_harness_config_metadata.py
  test_ad859_crew_executor.py       test_ad859a_agentic_executor.py

# AD / BF ceilings.
grep -o "AD-1[0-9]\{3\}" PROGRESS.md decisions-era-5-unification.md docs/development/roadmap.md | sort -u | tail -1
  AD-1151
grep -n "next free BF" PROGRESS.md
  5:  ... next free BF is **BF-680**.
```
