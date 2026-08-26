 AD-1257 — defect detection follows the tool failure, not the step limit

**Status:** ready to build
**Closes:** BF-793 (#1257)
**Dependencies:** AD-1169 (fault store), AD-1170 (the detector), AD-1248 (`ToolFailures`, per-pass accumulation)
**Estimated tests:** 15–18 new, one existing file amended

---

## Numbering

`python scripts/gen_ad_ledger.py --check` → `AD/BF ledger is current`
(snapshot pinned 2026-08-23T03:43:12+00:00 at `927bae11`; online layer 1301 issues).

| Authority | AD ceiling | BF ceiling |
|---|---|---|
| Ledger (`docs/development/open-ads-report.md`) | **AD-1250** allocated, AD-1251 "next free" — STALE | **BF-836** allocated — STALE |
| GitHub, all states (authoritative) | **AD-1256** filed (#1302) + AD-1251-1255 held by untracked prompts => next free **AD-1257** | **BF-840** filed (#1306) => next free **BF-841** |
| Untracked in-flight prompts | **AD-1251 … AD-1255** claimed (`prompts/ad-125{1,2,3,4,5}-*.md`) | max `bf-833-*` |

The five in-flight prompts have no issues yet, so the ledger's issue layer cannot see
them and its "next free AD-1251" is **wrong at this moment**. Taking it would collide.

- **This work is AD-1257.** Next free AD after this one: AD-1258.
- **Next free BF: BF-841** (see *Adjacent, do not build* below — one is recommended).
- **BF-793 (#1257)** is allocated, open, no code. It is the defect this closes, not a
  second number to mint.

**Why an AD and not just the BF.** BF-793 as filed describes a gating problem.
Verification (below) shows the detector cannot fire *at all* on its only production
path, and that fixing it requires a new evidence carrier, a new hook site, and an owner
for turn-level dedup. Filing faults on turns that completed normally is behaviour that
has never existed. That is a design decision. The BF closes as a consequence.

---

## Problem

### What BF-793 said

`detect_tool_defect` sits behind two gates — the `continue_or_ask_enabled` flag and a
`stopped_reason` in the re-invokable set — so a tool defect is only ever noticed when it
happens to coincide with burning the whole step budget.

That is true, and the flag half is confirmed live rather than latent:

```
config/system.yaml:515    max_iterations: 25
config/system.yaml:532    continue_or_ask_enabled: true
```

### What is actually wrong — verified by execution, not by reading

The detector is handed an object that **cannot carry the evidence it reads**.

```
$ .venv/Scripts/python.exe -c "..."
OUTCOME FIELDS: ['final_text', 'stopped_reason', 'denied_tools', 'tool_trace_ref',
                 'total_tokens', 'artifact_refs', 'token_source', 'tool_failures']
has tool_calls   : False
has tool_results : False
detect_tool_defect(outcome) -> None
AGENTICRESULT FIELDS: ['final_text', 'tool_calls', 'iterations', 'total_tokens',
                       'stopped_reason', 'error', 'tool_results', 'token_source']
```

`detect_tool_defect` reads `outcome.tool_calls` / `outcome.tool_results`
(`continue_or_ask.py:216-225`). Its only production caller passes a
`WorkItemAgenticOutcome`, which has neither. `getattr(..., None) or []` yields `[]`, the
`if not calls or not results` guard returns `None`, and it returns `None`
**unconditionally** — even with both gates wide open.

The source says so itself, at the construction site:

```
src/probos/cognitive/agentic_dispatch.py:2281
    # AD-1248: correlated HERE because this is the only scope holding
    # the raw call/result pairs -- ``WorkItemAgenticOutcome`` is the
    # projection callers see, and the pairs do not survive it.
```

`git log -S "tool_calls: list" -- src/probos/cognitive/agentic_dispatch.py` returns
nothing: the field never existed. **AD-1170 has never fired in production and could
not have.** It shipped in `d5939203` ("Phase 1: AD-1168 + AD-1169 + AD-1170").

### Why the tests did not catch it

`tests/test_ad1169_fault_reports.py:32` — *"fakes shaped like the real loop output"*.
`_Outcome` (`:47`) is a local class carrying `tool_calls` / `tool_results`. It is shaped
like `AgenticResult`, which is the **loop** output. Production hands the detector
`WorkItemAgenticOutcome`, which is the **executor** projection. Every AD-1170 test proves
the function; none crosses the seam to the object production actually supplies.

This is the repo's dominant defect shape: built, tested, inert.

### The correction to the issue's premise

> *"the repeated-identical-error signal it looks for is expressible over `ToolFailures`
> entries"*

**It is not.** Verified against `src/probos/dm_reply.py`:

| What the detector needs | What `ToolFailures` carries |
|---|---|
| `error_text` (for `file_fault_from_turn`, and for `error_signature`) | nothing — entries are `key -> display name` (`:212-234`) |
| a count of the *same error* repeating | nothing — the key is `{root}.{scope}:{signature}` where `signature = call_signature(name, arguments)` (`:165`), so it groups by **call identity**, not by error identity |
| ≥ 2 identical failures | identical name+args collapse to **one** entry — `state[key] = ...` in `correlate_tool_outcomes` (`dm/reply_value.py:126`) is a dict assignment |

`ToolFailures` answers *"which calls failed"*. `detect_tool_defect` asks *"which tool
answered the same way twice"*. Different questions over the same pairs.

So AD-1248 does **not** make this cheap by supplying the evidence. It makes it cheap by
having already established **where** the evidence has to be read: in
`WorkItemAgenticExecutor.run`, beside `correlate_tool_outcomes`, the one scope that holds
the raw pairs.

---

## The two open questions, settled

### Q1 — Is `file_fault_from_turn` safe to call on a COMPLETED turn?

**Yes.** Verified against `continue_or_ask.py:270-300` and `fault_report.py:238-300`.

- `file_fault_from_turn` takes `tool_id`, `error_text`, `attempted`, `agent_id`,
  `thread_id`. It reads no stop reason, and never has.
- It reads `runtime.fault_report_store` (`:284`), returns `""` when absent, and wraps the
  call in `except Exception` (`:292`) — "a turn must finish even when the reporting
  channel is missing".
- `FaultReportStore.file_fault` is likewise stop-reason agnostic and documented
  "Never raises" (`:246-250`).

Nothing about a completed turn changes any of that. **The design holds.**

### Q2 — Would per-turn firing produce duplicate fault reports across passes?

**Not duplicate *reports*. Yes, duplicate *occurrences* — and that is the thing to fix.**

`file_fault` coalesces on `error_signature(tool_id, error_text)`
(`fault_report.py:109`, `:253`):

```
fault_report.py:257    existing = self._cache.get(signature)
fault_report.py:260    if existing is not None and existing.status in ("open", "diagnosing"):
fault_report.py:261        existing.occurrences += 1
fault_report.py:264        return existing          # same id, no new row
```

So a second filing of the same defect **cannot** create a second report. But it
**does** increment `occurrences`, and `occurrences` is a Captain-facing claim:

```
repair_dispatch.py:167    f"The {brief.tool_id} tool has failed the same way "
repair_dispatch.py:168    f"{brief.occurrences} times. Approving dispatches a repair "
```

One turn must contribute at most one occurrence per signature, or that sentence lies.
**Dedup is required, and this AD must say who owns it** (see *Ownership* below).

**Blast radius is smaller than it looks, and this is why.** `FAULT_REPORTED` is emitted
at exactly one place — `fault_report.py:287` — on the **new-report** branch only. The
occurrence-increment branch returns at `:264` without emitting. So every emitted event
carries `occurrences=1`, while `RepairDispatcher.on_fault_event` requires
`occurrences >= propose_after_occurrences` (`repair_dispatch.py:92-96`, default `2`,
`config/system.yaml:615`). More faults filed therefore produce **no additional repair
proposals** on the event path today, even with `repair.enabled: true`
(`config/system.yaml:611`). `RepairDispatcher.propose()` remains directly callable, so
this is a bound on the event path, not a proof of total inertness.

That silence is itself a defect. It is **not** in scope — see *Adjacent*.

---

## Solution

Three moves, in dependency order. Each section is independently buildable and each
leaves the tree green.

**A. Detect where the pairs live.** `WorkItemAgenticExecutor.run` computes the defect
beside `correlate_tool_outcomes` and carries a **bounded value** — never the raw pairs —
out on the outcome. Pure data, no side effect. All five callers of `run()` receive it;
none is forced to act on it.

**B. File where the turn lives.** `_run_pass` in `cognitive_agent.py`, immediately after
`_accumulate_pass_failures`, files the fault. That is already the fold point for
per-pass failure evidence, on the same object, one line away. Detection is attached to
**tool failure**, and runs on every pass whatever the stop reason.

**C. Keep exhaustion's message, drop its second filing.** `resolve_exhausted_turn` keeps
its detection-shaped branch and its Captain-facing `_DEFECT_*` text — "I stopped here
because the same call kept coming back the same way" is a true sentence only about an
exhausted turn — but is told which signatures this turn already filed, so it reuses the
fault id instead of re-filing.

### Ownership of dedup

**The arming site owns turn-level dedup; the store owns cross-turn coalescing.**

- Within one turn: a closure-captured `dict[str, str]` (signature → fault id) beside the
  existing `_last_stop` and `_promoted` cells in `_maybe_run_conversational_agentic`.
  That is the established convention at this exact site (`cognitive_agent.py:4199`,
  `:4211`) and it is the only object that spans every pass **and** is visible to
  `_agentic_turn`. The observation cannot own it: `resolve_exhausted_turn` never receives
  the observation (verify its signature at `continue_or_ask.py:610-621`).
- Across turns: unchanged. A second turn hitting the same signature increments
  `occurrences` — correct, the tool is still broken.

### Why not the alternatives

| Rejected | Why |
|---|---|
| Put `tool_calls` / `tool_results` on `WorkItemAgenticOutcome` | Re-exposes unbounded blobs on an object that reaches the crew record. AD-731 (refs on the bus, bytes in the store). The AD-1248 comment at `:2281` is a deliberate decision, not an oversight. |
| Read the pairs back from `tool_trace_ref` | Async store round-trip on every turn; lossy — BF-760 records the *rendering* not the tool output, and AD-1151/DD-5 elides outputs at the byte cap. Detection over elided evidence is detection over noise. |
| Derive the defect from `ToolFailures` | Carries neither the error text nor a same-error count; identical calls collapse to one entry. See the table above. |
| Fire only at the end of `_agentic_turn` | Misses nothing today but re-attaches detection to a turn boundary rather than to the failure, which is the exact mistake being corrected. |

---

## Implementation

### Section 1 — `ToolDefect`, and the detector moves to foundation

`detect_tool_defect` currently lives in `continue_or_ask.py:209` and lazily imports
`normalise_error` from `probos.fault_report` (`:220`). Section 2 needs it from
`agentic_dispatch.py`, which does not import `continue_or_ask` today (verified: zero
hits) and should not start — `continue_or_ask` imports `crew_executor` at module level
(`:63-66`), and while `crew_executor` imports `agentic_dispatch` only under
`TYPE_CHECKING` (`crew_executor.py:37-39`), building a new runtime edge into that triangle
is not worth the saving.

**In `src/probos/fault_report.py`** (stdlib-only imports today — verified `:34-43`):

- Add a frozen value beside `error_signature` (`:109`):

```python
@dataclass(frozen=True)
class ToolDefect:
    """AD-1257: one tool answering the same way more than once, in a bounded form.

    Carries what a fault report needs and nothing else. The raw call/result pairs
    stay in the loop's scope (AD-731); this crosses the executor boundary in their
    place.
    """

    tool_id: str = ""
    error_text: str = ""
    count: int = 0
```

  `tool_id` truncated to `_TOOL_ID_MAX` (`:54`), `error_text` to `_ERROR_MAX` (`:55`) at
  construction, so the value can never be larger than the row it becomes.

- Move `detect_tool_defect` here verbatim except: return `ToolDefect | None` instead of
  `tuple[str, str, int] | None`, and drop the now-redundant function-local import of
  `normalise_error`. `_DEFECT_MIN_OCCURRENCES` (`continue_or_ask.py:198`) moves with it.

**In `src/probos/cognitive/continue_or_ask.py`**: re-export `detect_tool_defect`,
`ToolDefect` and `_DEFECT_MIN_OCCURRENCES` as a namespace alias — **not** a second
definition. This is the BF-801 / `dm/reply_value.py:1-11` precedent, already in the tree.
Existing importers (`tests/test_ad1169_fault_reports.py:18-22`) keep working unchanged.

Update `resolve_exhausted_turn`'s unpacking at `:735` from the tuple to the value's
fields.

> Do not add `fault_report` to `FOUNDATION_MODULES` in
> `tests/test_layer_boundaries.py:35`. `continue_or_ask.py:220` already imports it from
> cognitive, so the direction is proven legal. Run that test to confirm.

### Section 2 — the carrier

**`src/probos/cognitive/agentic_dispatch.py`**

SEARCH anchor — the last field of the dataclass (`:1462-1467`):

```
    # AD-1248: which tool calls failed, keyed by ``{root}.{scope}:{signature}``
    # so a later pass can supersede its own calls without erasing a sibling's.
    # Merge-open here -- it still carries the success tombstones, which are
    # dropped only when it crosses a serialization boundary. Appended last and
    # defaulted, so every existing construction site is untouched.
    tool_failures: ToolFailures = field(default_factory=ToolFailures)
```

Append **after** it — last and defaulted, so every existing construction site is
untouched:

```python
    # AD-1257: the AD-1170 defect this run's own results describe, or None.
    # Detected HERE for the same reason ``tool_failures`` is correlated here --
    # this is the only scope holding the raw call/result pairs, and they do not
    # survive onto this projection. Bounded by construction; the pairs stay put.
    tool_defect: ToolDefect | None = None
```

SEARCH anchor — the construction site (`:2285-2292`):

```
            tool_failures=correlate_tool_outcomes(
                agentic_result,
                root=_failure_scope,
                scope=_failure_scope,
                known_tools=offered_names,
                excluded_tools=executor.denied_tools,
            ),
        )
```

Add `tool_defect=detect_tool_defect(agentic_result),` as the next keyword. `agentic_result`
is in scope (`:2220`) and carries both lists (verified: `AgenticResult` fields above).

Import `ToolDefect` and `detect_tool_defect` from `probos.fault_report` at module level,
beside the AD-1248 import at `:31`.

`detect_tool_defect` already swallows every exception and returns `None`
(`continue_or_ask.py:264-269`), so a malformed result cannot fail a dispatch. Keep that.

### Section 3 — the hook

**`src/probos/cognitive/cognitive_agent.py`**

SEARCH anchor, inside `_run_pass` (`:4277-4280`):

```
                _ref = str(getattr(outcome, "tool_trace_ref", "") or "")
                if _ref:
                    observation["_tool_trace_ref"] = _ref
                _accumulate_pass_failures(observation, outcome)
                return outcome
```

Between `_accumulate_pass_failures` and `return outcome`, file the defect:

- Read `getattr(outcome, "tool_defect", None)`; `None` → do nothing.
- Compute `error_signature(tool_id=..., error_text=...)`. Already in `_filed_faults`
  (the new closure dict, declared beside `_promoted` at `:4211`) → do nothing.
- Otherwise `await file_fault_from_turn(...)` with `agent_id=self.id`,
  `thread_id=thread_id` (in scope, `:4155`), and
  `attempted=_promotion_request_text(observation, user_message)` — the same
  Captain-facing value BF-709 established for this surface (`:4305`).
- Record `_filed_faults[signature] = fault_id` **whether or not** the id came back
  non-empty. An unwired store must not cause a second attempt on the next pass.
- Wrap the whole block so nothing here can fail a turn — log-and-degrade tier.

**No stop-reason condition.** That is the entire point of this AD.

**No reply-text change.** Filing is silent. The AD-1248 disclosure already tells the
Captain a tool failed on a completed turn.

Add a small helper next to `_accumulate_pass_failures` (`:90`) rather than inlining a
block into an already-long closure. It takes the outcome, the dict, and the filing
context; it returns `None`.

### Section 4 — exhaustion reuses rather than re-files

**`src/probos/cognitive/continue_or_ask.py`**

Add one keyword-only parameter to `resolve_exhausted_turn` (`:610`):

```python
    already_filed: Mapping[str, str] | None = None,
```

Defaulted, so the 30+ existing call sites in `tests/test_ad1164_continue_or_ask.py`,
`tests/test_ad1204_approval_resumes_the_turn.py` and `tests/test_bf717_stop_notice_leads.py`
are **byte-identical by construction**. Document that in the docstring gate list.

At the defect branch (`:734-741`), compute the signature and:

- present in `already_filed` → reuse that fault id, **skip** `file_fault_from_turn`;
- absent or `already_filed is None` → today's path exactly.

The `_DEFECT_LEAD_*` / `_DEFECT_DETAIL` / `_DEFECT_TAIL*` composition is unchanged either
way — the Captain still reads the same sentence naming the same fault.

Pass `already_filed=_filed_faults` from the arming site (`cognitive_agent.py:4292`).

---

## What this does NOT change — do not build

1. **Do not add `tool_calls` / `tool_results` to `WorkItemAgenticOutcome`.** AD-731. The
   comment at `agentic_dispatch.py:2281` is the decision; honour it.
2. **Do not add `tool_defect` to `CREW_EXECUTION_KEYS`** (`crew_utils.py:38`). The crew
   record shape is frozen and censused by `tests/test_ad1248_slice_c_one_shape.py`.
3. **Do not make `WorkItemAgenticExecutor.run` file anything.** It serves five callers
   (crew fan-out, delegation, AD-839 dispatch, the DM path, loop-until-done). It computes
   evidence; the turn owner decides.
4. **Do not change the reply text on completed turns.** No `_DEFECT_*` string reaches a
   turn that stopped `complete`. If you find yourself editing a Captain-facing string,
   you have left this AD.
5. **Do not add a config flag.** `dm_agentic.enabled` already gates this path. A
   default-OFF flag is precisely what made AD-1170 inert (AD-1180's lesson).
6. **Do not touch `ToolFailures`, `correlate_tool_outcomes`, or the AD-1248 disclosure.**
7. **Do not touch `RepairDispatcher`, `_emit_fault`, or `propose_after_occurrences`.**
8. **Do not touch `crew_executor`, the delegation path, or the AD-839 handler.**
9. **Do not delete any AD-1170 test.** They are correct about the function. See below.

### Adjacent — file, do not build

`_emit_fault("FAULT_REPORTED", ...)` fires only on the new-report branch
(`fault_report.py:287`), so every emitted event carries `occurrences=1`, while
`RepairDispatcher.on_fault_event` requires `>= 2` (`repair_dispatch.py:92-96`, default 2).
No repair proposal can follow a filed fault on the event path — with `repair.enabled:
true` on the vessel. Recommend filing as **BF-841** (next free). Do not fix it here: it
would change what the Captain is asked to approve, which is its own decision.

---

## Tests

New file: `tests/test_ad1256_defect_follows_failure.py`.

### The seam test — the one that would have caught this

```
test_a_completed_turn_with_a_repeated_tool_failure_files_a_fault
```

Drive the **real** arming site — `_maybe_run_conversational_agentic` with
`dm_agentic.enabled` on — with a stub executor whose `run()` returns a real
`WorkItemAgenticOutcome` carrying `stopped_reason="complete"` and a populated
`tool_defect`. Assert `runtime.fault_report_store` received exactly one `file_fault`,
with the right `tool_id` and `error_text`.

**A narrower test passes on today's broken wiring.** `detect_tool_defect` works fine in
isolation; that is why five green tests hid a function that has never run. This test must
span *completed turn → outcome → hook → store*, and it must fail if Section 3 is reverted.

Assert on a `records` list the fake store exposes, **never** inside its `file_fault` —
`file_fault_from_turn` wraps the call in `except Exception` (`continue_or_ask.py:292`),
which swallows `AssertionError`.

### Section A — the carrier

| Test | Asserts |
|---|---|
| `test_the_outcome_carries_the_defect_the_loop_saw` | BF-701 shape through `run()` → `outcome.tool_defect.tool_id == "browser"`, `count == 2` |
| `test_a_completed_run_still_carries_the_defect` | `stopped_reason="complete"` → defect still present |
| `test_a_single_failure_leaves_the_outcome_clean` | one failure → `tool_defect is None` |
| `test_malformed_results_do_not_fail_the_run` | junk in `tool_results` → `tool_defect is None`, `run()` returns normally |
| `test_the_carried_error_text_is_bounded` | 10 000-char error → `len(...) <= _ERROR_MAX` |

### Section B — filing

| Test | Asserts |
|---|---|
| `test_a_clean_outcome_files_nothing` | zero `file_fault` calls |
| `test_a_missing_fault_store_does_not_break_the_turn` | store `None` → turn returns its text |
| `test_a_raising_fault_store_does_not_break_the_turn` | `file_fault` raises → turn returns its text |

### Section C — dedup

| Test | Asserts |
|---|---|
| `test_two_passes_of_one_turn_file_one_occurrence` | same signature across two passes → exactly **one** `file_fault` |
| `test_two_distinct_defects_in_one_turn_both_file` | two signatures → two calls |
| `test_an_unwired_store_is_not_retried_next_pass` | empty fault id still recorded → one attempt |
| `test_the_exhaustion_path_reuses_the_id_the_pass_filed` | `already_filed` populated → no second `file_fault`; reply still names the id |
| `test_resolve_exhausted_turn_without_already_filed_is_unchanged` | omitted → today's behaviour, guarding the 30+ existing call sites |
| `test_a_later_turn_files_again_and_increments` | second turn, same signature → `file_fault` called; `occurrences == 2` |

### Section D — structural

| Test | Asserts |
|---|---|
| `test_the_outcome_still_does_not_carry_raw_call_pairs` | `tool_calls` / `tool_results` absent from `dataclasses.fields(WorkItemAgenticOutcome)` — pins boundary 1 |
| `test_the_crew_execution_record_shape_is_unchanged` | `"tool_defect" not in CREW_EXECUTION_KEYS` |
| `test_the_detector_is_one_definition` | `continue_or_ask.detect_tool_defect is fault_report.detect_tool_defect` — the alias is an alias |

### Existing file to amend, not delete

`tests/test_ad1169_fault_reports.py` — the AD-1170 tests stay. They are correct about
the function, and after Section 2 the shape they fake (`AgenticResult`) **is** the
production input. Update the module docstring (`:1-12`) and the `_Outcome` comment
(`:32`) to say so, and record inline that the shape became correct at AD-1257 rather than
having always been. Do not weaken any assertion.

### Running

Focused, serial:

```
.venv/Scripts/pytest.exe tests/test_ad1256_defect_follows_failure.py tests/test_ad1169_fault_reports.py tests/test_ad1164_continue_or_ask.py tests/test_layer_boundaries.py tests/test_ad1248_slice_c_one_shape.py -v -n 0
```

Full parallel gate before commit:

```
.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
```

---

## Acceptance criteria

1. `detect_tool_defect` returns a `ToolDefect` from a real `AgenticResult` inside
   `WorkItemAgenticExecutor.run`, and the bounded value reaches the caller on
   `WorkItemAgenticOutcome.tool_defect`.
2. A DM turn that stops `complete` with a tool that failed the same way twice **files a
   fault report**, verified through the arming site — not through the detector alone.
3. One turn contributes at most one `occurrences` increment per signature, across any
   number of AD-1164 passes and the exhaustion path combined.
4. `resolve_exhausted_turn` called without `already_filed` behaves exactly as it does at
   HEAD; the existing 30+ call sites are unmodified.
5. `WorkItemAgenticOutcome` still carries no raw call/result pairs, and
   `CREW_EXECUTION_KEYS` is unchanged.
6. No Captain-facing string changes on a turn that completed normally.
7. No new configuration field.
8. `tests/test_layer_boundaries.py` passes with `FOUNDATION_MODULES` unmodified.
9. Full suite green at `-n 4 --dist=loadfile`; any pre-existing failure triaged at `-n 0`
   before it is attributed to this change.
10. Run the `Diff Reviewer` subagent on the staged diff, with a different model than the
    one that wrote the code, before committing. Name the consumer that has to accept the
    change: the fault store, and through it the Captain-facing occurrence count.
11. **Verify all changes comply with the Engineering Principles in
    `.github/copilot-instructions.md`.**

---

## Tracking

| File | Entry |
|---|---|
| `PROGRESS.md` | AD-1257 shipped; BF-793 CLOSED — "detector could not read the object it was given; moved detection to the executor scope and the trigger to tool failure" |
| `docs/development/roadmap.md` | Bug Tracker row for BF-793 → closed by AD-1257 |
| `DECISIONS.md` | AD-1257 — the trigger relocation, the `ToolDefect` carrier, and the dedup owner |
| GitHub | close #1257 citing the empirical finding; open BF-841 for the `_emit_fault` occurrence gap |

---

## Verified Against Codebase (2026-08-23, HEAD `28b9995c`)

```
rg -n "detect_tool_defect|file_fault_from_turn|resolve_exhausted_turn" src/
  cognitive/continue_or_ask.py:209  def detect_tool_defect(outcome: Any) -> tuple[str, str, int] | None:
  cognitive/continue_or_ask.py:270  async def file_fault_from_turn(
  cognitive/continue_or_ask.py:284      store = getattr(runtime, "fault_report_store", None)
  cognitive/continue_or_ask.py:610  async def resolve_exhausted_turn(
  cognitive/continue_or_ask.py:734      defect = detect_tool_defect(current)
  cognitive/continue_or_ask.py:737          fault_id = await file_fault_from_turn(
  cognitive/cognitive_agent.py:4290     from probos.cognitive.continue_or_ask import resolve_exhausted_turn
  cognitive/cognitive_agent.py:4292     turn_text = await resolve_exhausted_turn(
  -> exactly one production call site for each

rg -n "_accumulate_pass_failures" src/
  cognitive/cognitive_agent.py:90    def _accumulate_pass_failures(observation: dict, outcome: Any) -> None:
  cognitive/cognitive_agent.py:4279      _accumulate_pass_failures(observation, outcome)

rg -n "thread_id = _conversational_thread_id\(|_last_stop: dict|_promoted: dict|display_task_text=_promotion_request_text\(" src/probos/cognitive/cognitive_agent.py
  4155:             thread_id = _conversational_thread_id(
  4199:             _last_stop: dict[str, str] = {"reason": ""}
  4211:             _promoted: dict[str, str] = {"work_item_id": ""}
  4305:                         display_task_text=_promotion_request_text(

rg -n "^class WorkItemAgenticOutcome|^    tool_failures: ToolFailures|^        return WorkItemAgenticOutcome\(" src/probos/cognitive/agentic_dispatch.py
  1430: class WorkItemAgenticOutcome:
  1467:     tool_failures: ToolFailures = field(default_factory=ToolFailures)
  2274:         return WorkItemAgenticOutcome(

rg -n "^def error_signature|^_ERROR_MAX|^_TOOL_ID_MAX|^    async def file_fault|^    def _emit_fault" src/probos/fault_report.py
  54:  _TOOL_ID_MAX = 128
  55:  _ERROR_MAX = 2000
  109: def error_signature(*, tool_id: Any, error_text: Any) -> str:
  238:     async def file_fault(
  387:     def _emit_fault(self, event_name: str, report: FaultReport) -> None:

rg -n "fault_report_store" src/probos/runtime.py
  2977:         self.fault_report_store = comm.fault_report_store

rg -n "continue_or_ask_enabled|max_iterations|propose_after_occurrences" config/system.yaml
  515:   max_iterations: 25
  532:   continue_or_ask_enabled: true
  615:   propose_after_occurrences: 2
config/system.yaml:611  enabled: true          (repair)
```

### Absence verified

```
CLAIM: WorkItemAgenticOutcome cannot carry tool_calls / tool_results
RUN:   python -c "import dataclasses; from probos.cognitive.agentic_dispatch import WorkItemAgenticOutcome; print([f.name for f in dataclasses.fields(WorkItemAgenticOutcome)])"
FOUND: ['final_text','stopped_reason','denied_tools','tool_trace_ref','total_tokens','artifact_refs','token_source','tool_failures']
HOLDS: yes — neither name present

CLAIM: detect_tool_defect returns None on that object regardless of stop reason
RUN:   python -c "... detect_tool_defect(WorkItemAgenticOutcome(final_text='x', stopped_reason='max_iterations')) ..."
FOUND: None
HOLDS: yes — empirical, not inferred

CLAIM: the field never existed
RUN:   git log --oneline -S "tool_calls: list" -- src/probos/cognitive/agentic_dispatch.py
FOUND: (no commits)
HOLDS: yes

CLAIM: agentic_dispatch does not import continue_or_ask
RUN:   rg -n "continue_or_ask" src/probos/cognitive/agentic_dispatch.py
FOUND: (no matches)
HOLDS: yes — and crew_executor.py:37-39 imports agentic_dispatch under TYPE_CHECKING only

CLAIM: FAULT_REPORTED is emitted only on the new-report branch
RUN:   rg -n "_emit_fault|FAULT_REPORTED|fault_reported" src/
FOUND: fault_report.py:287 (FAULT_REPORTED), :365 (FAULT_RESOLVED), :387 (def);
       repair_dispatch.py:87,214 (listener); events.py:239 (enum)
HOLDS: yes — no emitter on the occurrence-increment branch (:260-264)

CLAIM: ToolFailures carries no error text
RUN:   read src/probos/dm_reply.py:212-234, dm/reply_value.py:100-130
FOUND: entries are tuple[tuple[key, display_name]]; value is "" or a display name
HOLDS: yes — no error text, and identical name+args collapse to one key
```
