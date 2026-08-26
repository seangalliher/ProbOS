# AD-1257 + AD-1269 — the defect trigger, and the identity of the row it writes

**Status:** ready to build
**Supersedes:** `prompts/ad-1257-defect-detection-follows-tool-failure.md` (do not build that file)
**Closes:** BF-793 (#1257)
**Dependencies:** AD-1169 (fault store), AD-1170 (the detector), AD-1173 (repair verification),
AD-1248 (`ToolFailures`, per-pass accumulation), BF-754/BF-757 (the provider alias and its resolver)
**Executed against:** `.git/AD1257_ATTEMPT.patch` — reuse, do not rewrite. See *Working from the preserved patch*.
**Estimated tests:** the preserved 45, plus 12–15 new

---

## Numbering

Enumerated, not recalled (2026-08-25). `scripts/gen_ad_ledger.py --check` reports
"ledger is current", but its issue and git layers are pinned at
2026-08-07T20:06:19+00:00 / `aff79cae`, so `docs/development/open-ads-report.md`
states **AD-1218 / BF-726** — 51 ADs stale. Do not take a number from it.

| Authority | AD ceiling | BF ceiling | How |
|---|---|---|---|
| `docs/development/open-ads-report.md` | AD-1218 | BF-726 | **STALE — pinned 2026-08-07** |
| `git log` subjects (last 400) | AD-1248 | BF-854 | highest with code |
| GitHub issues, all states (200 most recent) | AD-1261 | BF-854 (#1323) | highest filed |
| Untracked in-flight prompts | **AD-1268** | — | `prompts/ad-1268-a-decision-is-a-standing-answer.md` |

**Current highest allocated across every authority: AD-1268. Highest BF: BF-854.**

- **AD-1257** is retained. It was allocated to this work, nothing shipped under it,
  and its decision — *relocate the trigger from step-limit exhaustion to tool failure* —
  is unchanged and was confirmed by two review rounds. This is not a reuse.
- **AD-1269 is newly minted here** for the decision AD-1257 never made: what a fault
  row's durable identity and provenance are.
- Next free after this prompt: **AD-1270**, **BF-855**.

Two ADs, one commit. Precedent: `d5939203` shipped AD-1168 + AD-1169 + AD-1170 together.

---

## The decision, and why it is one build

### Why AD-1269 exists at all

AD-1170 has never fired in production and could not have: `detect_tool_defect` joins
`tool_calls` to `tool_results`, and the DM path's `WorkItemAgenticOutcome` carries
neither. That is BF-793 and it is settled by execution.

The consequence nobody had reason to look at until the attempt made the detector fire:
**`FaultReportStore.file_fault` has exactly one production caller, and that caller could
never reach it.** Enumerated:

```
CLAIM: nothing else in production writes a fault row
RUN:   grep -rn "\.file_fault\(|file_fault_from_turn\(" (whole repo)
FOUND: src/probos/cognitive/continue_or_ask.py:289   store.file_fault(...)   <- inside file_fault_from_turn
       src/probos/cognitive/continue_or_ask.py:738   file_fault_from_turn()  <- inside resolve_exhausted_turn
       tests/test_ad1169_fault_reports.py x12, tests/test_ad1173_repair_verification.py x2
HOLDS: yes — one production chain, and its head is the dead detector
```

Confirmed against the running vessel rather than inferred from the repo layout
(`%LOCALAPPDATA%\ProbOS\data`, **not** `d:\ProbOS\data`):

```
C:\Users\seang\AppData\Local\ProbOS\data\fault_reports.db
tables: ['fault_reports']
rows, distinct signatures: (0, 0)
```

**The table exists and is empty.** Every property of a fault row is therefore still a
free choice, and this is the only moment at which that will be true.

### The three findings are one question

| # | Finding | Reproduced here |
|---|---|---|
| 1 | The row's `tool_id` is the provider alias, not a registered tool id | `llm_function_name("mcp:docs:search")` → `mcp_docs_search_38c53abe80026e47`; `resolve_llm_function_name(alias, ["mcp:docs:search"])` → `mcp:docs:search` |
| 2 | The signature is derived from already-truncated text, so one defect splits into two rows | `error_signature(raw) == error_signature(raw[:_ERROR_MAX])` → **False** for a 3 046-char digit-run error |
| 3 | Coalescing discards a usable trace ref | `_persist_occurrence` (`fault_report.py:321-336`) updates `occurrences` and `last_seen_at` only |

All three ask: *what does a fault row durably mean, and where does that meaning come from?*

### D1 — `tool_id` is the canonical registered tool id

Decided by enumerating the consumers, not by preference:

| Consumer | Site | Needs |
|---|---|---|
| Repair rationale shown to the Captain | `repair_dispatch.py:169` | canonical — the Captain cannot read `mcp_docs_search_38c53abe80026e47` |
| `scope_key` on the repair approval | `repair_dispatch.py:165` | canonical — a standing grant keyed on a hash-suffixed alias grants nothing |
| `FaultReportStore.get_by_tool` | `fault_report.py:376` | canonical |
| `idx_faults_tool` | `fault_report.py:81` | canonical |
| `FAULT_REPORTED` payload → `RepairDispatcher` | `fault_report.py:394` | canonical |
| Retry invocation | `repair_verification.py:149` | indifferent — `ToolExecutor._resolve_tool_id` maps either |
| Trace argument recovery | `repair_verification.py:82` | the **observed** name — the trace records `ToolCallRequest.name` |

Five require canonical, one is indifferent, one requires the observed name. So `tool_id`
is canonical and the observed name gets its own field (D3).

**Blast radius is bounded and measured.** `llm_function_name("browser") == "browser"` —
aliasing only bites ids the provider's `^[A-Za-z0-9_-]{1,64}$` rejects, which today is
only `mcp:{server}:{tool}`. Every non-MCP row is byte-identical to what the attempt wrote.

### D2 — canonicalisation happens at detection, through an injected resolver

`WorkItemAgenticExecutor.run` spans `agentic_dispatch.py:1509-2295` (verified: the next
`def` at that indent is `_persist_tool_trace` at `:2296`). `registry` is bound at `:1575`;
the outcome is constructed at `:2274`. **Same scope** — the detection site already holds
everything canonicalisation needs.

Use `llm_function_name_claimants` (`cognitive/swe_harness/tool_call.py:67`) against
`registry.list_ids()` (`tools/registry.py:166`) — **the same helper against the same
authority** `ToolExecutor._resolve_tool_id` uses (`tools/executor.py:102-105`). Not a
reimplementation, and not the offered subset: a name ambiguous over the whole registry
can be unambiguous over the offer, and a detector that disagreed with the executor about
which tool ran would file against a tool that never executed.

**`fault_report.py` must not import it.** That module is stdlib-only (verified `:34-43`,
plus a `TYPE_CHECKING` import of `storage.sqlite_factory`) and `swe_harness` is cognitive.
Foundation importing cognitive is a layer regression. So `detect_tool_defect` takes an
injected `resolve_tool_id: Callable[[str], str] | None = None` and stays pure — dependency
inversion, and it keeps the detector unit-testable with no registry.

Degradation matches `_resolve_tool_id` exactly: 1 claimant → canonical; 0 claimants →
observed name verbatim; **≥2 claimants → observed name verbatim and a `logger.warning`**.
BF-757's rule holds — we do not guess which of two tools the model was shown.

### D3 — the row carries both; trace matching uses provenance

`tool_id` is identity. A new `observed_as` is provenance — the name the model actually
used — and is `""` when it equals `tool_id`, so every non-MCP row and every existing test
is byte-identical.

`find_failing_arguments` (`repair_verification.py:68`) matches the trace entry's `name`
against `observed_as or tool_id`. The trace records `asdict(ToolCallRequest)` — verified
at `agentic_loop.py:341` (`entry = asdict(call)`) — so `name` is the alias.

**A guarded `ALTER TABLE` is mandatory, not optional.** The live vessel's
`fault_reports.db` already exists with today's 15 columns, so `CREATE TABLE IF NOT EXISTS`
is a no-op and `_load_cache`'s SELECT would fail with `no such column: observed_as` on the
next boot. Follow the `PRAGMA table_info` precedent at `capability_request.py:286-306` —
same tier, same store shape, idempotent across restarts.

### D4 — the signature is computed once at detection and threaded

Over the **canonical** `tool_id` and the **untruncated** error text.

Three measurements force this:

1. `normalise_error` collapses `<n>`/`<id>` runs and *then* truncates
   (`fault_report.py:101-106`), so collapsing frees room the raw cut already spent.
   Reproduced: a 3 046-char digit-run error gives `sig(raw) != sig(raw[:2000])`.
   *(Whitespace does **not** reproduce this — a whitespace regression test passes without
   the fix. The attempt's first test made exactly that mistake.)*
2. The window is reachable on shipped config: `_ERROR_MAX = 2000`, and the loop's
   `result.output` is bounded by `agentic_loop.tool_result_max_chars`, which
   **defaults to 0 (unbounded)** and is `6000` at `config/system.yaml:2422`.
3. The only other recompute site is `repair_verification.py:86`, which recomputes from the
   **trace's** output. `tool_trace_output_max_chars: 8192` (`config/system.yaml:2430`) is
   larger than `tool_result_max_chars: 6000`, so on the live vessel the trace output
   **equals** the detector's raw text. Computing over raw is the only choice that leaves
   AD-1173's argument recovery able to match.

The carrier must still be bounded (AD-731) — `tool_result_max_chars` defaults to
unbounded, so the raw text cannot ride on `WorkItemAgenticOutcome`. Bounded display text
plus a threaded signature is the only shape that satisfies both constraints.

`file_fault` gains `signature: str | None = None`, validated as 64 lowercase hex,
falling back to today's recompute when absent or malformed. Every existing caller is
unchanged by construction.

> The attempt already got the hard half right: `ToolDefect.__post_init__` derives the
> signature **before** truncating, and says so. What it missed is that `file_fault`
> recomputes (`fault_report.py:255`, `:459` post-patch) and throws that work away.

### D5 — coalescing upgrades a missing trace ref, never overwrites one

On the coalescing branch (`fault_report.py:259-265`), adopt `tool_trace_ref` when the
existing row has none and the new occurrence carries one. Provenance may go from absent
to present; never the reverse, never overwrite. `_persist_occurrence` writes it in the
same UPDATE.

### D6 — the discriminator is provenance, not shape

`hasattr(outcome, "tool_calls") or hasattr(outcome, "tool_results")` asks *what shape is
this?* The question is *what does this object know?* Replace with:

```
if calls and results:                                   -> join them
elif getattr(obj, "tool_defect_evaluated", False) is True:
                                                        -> the carried verdict, incl. None
else:                                                   -> None
```

This kills both hazards at once. A future projection with empty-default pair fields *and*
a real verdict now reads the verdict (BF-793 is not recreated), and an object holding real
pairs never defers to a verdict a later pass superseded (no fabricated Captain-facing
claim — which is why the attempt made raw pairs authoritative in the first place).

`WorkItemAgenticOutcome.tool_defect_evaluated: bool = False`, set `True` at the one
construction site.

### Why one build, not two commits

The identity contract has **no production exerciser other than the detector** — that is
the enumeration above. Shipping AD-1257 alone would put a schema change behind a path
nothing reaches, which is this repo's dominant defect shape and the exact reason AD-1170
rotted for months.

Worse, it manufactures the only migration that does not otherwise exist. AD-1257 is what
writes the first durable row. Ship it first and rows land with alias `tool_id`s and
store-recomputed signatures; AD-1269 then has to migrate them — and because the signature
*is* the coalescing key, pre- and post-migration rows for the same fault would stop
coalescing. Measured today: **0 rows.** Ship them together and there is nothing to migrate,
ever.

---

## Working from the preserved patch

`.git/AD1257_ATTEMPT.patch` (32.6 KB, +354/−103) applies cleanly at `fd16e806` and passed
two review rounds: 45 tests, 457 passing across the file and its consumers, mutation 8/8
killed. **Apply it first, then make the deltas below.** Do not rewrite it.

```powershell
git apply .git\AD1257_ATTEMPT.patch
Copy-Item .git\AD1257_tests.py tests\test_ad1257_defect_follows_failure.py
```

> The old spec's Tests section names `test_ad1256_*`. AD-1256 is a different allocated AD
> (#1302). The file is `tests/test_ad1257_defect_follows_failure.py`.

### Reuse verbatim — do not re-derive

| From the patch | Why it stands |
|---|---|
| `fault_report.py`: the AD-1170 comment block, `_DEFECT_MIN_OCCURRENCES`, `_DEFECT_COUNT_MAX` | `_DEFECT_COUNT_MAX` exists because review measured `"%d" % 10**5000` raising `ValueError` on the Captain-facing path |
| `ToolDefect.__post_init__` ordering: derive signature, **then** bound | D4's correct half, already implemented and commented |
| `detect_tool_defect` body — the id-join, tally, `max`, threshold | unchanged behaviour, mutation-tested |
| `continue_or_ask.py`: the re-export alias, `already_filed` on `resolve_exhausted_turn`, `tool_trace_ref` on `file_fault_from_turn` | `already_filed` verified compatible with all 45 existing call sites (keyword-only, defaulted) |
| `cognitive_agent.py`: `_file_pass_defect` whole, the `_filed_faults` cell, the `_run_pass` hook, the `already_filed=` pass-through | `_filed_faults` verified genuinely per-turn — occurrence 1 after turn one, 2 on the same row after turn two |
| `agentic_dispatch.py`: the `tool_defect` field and its comment | |
| `tests/test_ad1169_fault_reports.py` docstring amendments | records that the faked shape *became* correct at AD-1257 |
| All 45 preserved tests | keep every assertion; add to them |

### Change

| # | Where | Delta |
|---|---|---|
| C1 | `ToolDefect` | add `observed_as: str = ""`; bound it in `__post_init__` like `tool_id`. Signature material stays `(tool_id, error_text)` — canonical id, untruncated text |
| C2 | `detect_tool_defect` | add `*, resolve_tool_id: Callable[[str], str] | None = None`. Apply per D2; set `observed_as` only when the resolved id differs from the observed name |
| C3 | `resolve_tool_defect` | replace the `hasattr` discriminator with D6. Keep every validation the attempt added (count coercion, threshold, empty `tool_id`, empty `signature`, non-`ToolDefect` reject) — review verified all four reject correctly |
| C4 | `agentic_dispatch.py` construction site (`:2274`) | pass a resolver closure over `registry`; add `tool_defect_evaluated=True` |
| C5 | `fault_report.py` `FaultReport` + `_SCHEMA` + `_load_cache` + `_row_to_report` | add `observed_as` |
| C6 | `fault_report.py` `FaultReportStore.start` | guarded `PRAGMA table_info` / `ALTER TABLE` per D3 |
| C7 | `fault_report.py` `file_fault` | add `signature: str | None = None` and `observed_as: str = ""`; use the supplied signature when it is 64 lowercase hex |
| C8 | `fault_report.py` coalescing branch + `_persist_occurrence` | D5 |
| C9 | `continue_or_ask.py` `file_fault_from_turn` | add `signature` and `observed_as` keywords, forwarded |
| C10 | `cognitive_agent.py` `_file_pass_defect` | forward `signature=defect.signature`, `observed_as=defect.observed_as` |
| C11 | `repair_verification.py` `find_failing_arguments` | add `observed_as: str = ""`; match `name` against `observed_as or tool_id`. Pass it from the `:130` call site |

### Drop

Nothing structural. Two textual corrections only:

- the `hasattr` precedence paragraph in `resolve_tool_defect`'s docstring — rewrite for D6;
- the test filename, `test_ad1256_*` → `test_ad1257_*`.

---

## Tests

### The two that would have caught each half

```
test_a_completed_turn_with_a_repeated_tool_failure_files_a_fault      (AD-1257 seam)
test_an_mcp_fault_is_filed_against_the_canonical_id_and_recovers_args (AD-1269 seam)
```

The second must span **alias observed → canonical row → trace lookup by the alias →
arguments recovered**. Register a tool whose id the provider regex rejects, drive the real
arming site, and assert:

- `row.tool_id == "mcp:docs:search"`;
- `row.observed_as == "mcp_docs_search_38c53abe80026e47"`;
- `registry.get(row.tool_id) is not None`;
- `find_failing_arguments(trace_entries, tool_id=row.tool_id, signature=row.signature, observed_as=row.observed_as)` returns the arguments.

A test that stops at the row proves half a chain. That is the shape that let AD-1170 rot.

### New, beyond the preserved 45

| Test | Asserts |
|---|---|
| `test_a_plain_tool_id_is_unchanged_by_canonicalisation` | `browser` → `tool_id="browser"`, `observed_as=""` |
| `test_an_ambiguous_name_is_filed_verbatim_and_warned` | two claimants → observed name kept, `WARNING` logged, row still filed |
| `test_an_unregistered_name_is_filed_verbatim` | zero claimants → observed name kept |
| `test_the_detector_needs_no_resolver` | `resolve_tool_id=None` → today's behaviour exactly |
| `test_a_long_digit_run_error_coalesces_across_turns` | **real SQLite, close and reopen**; 3 046-char digit-run error twice → **1 row, `occurrences == 2`**. This is the regression test for finding 2 — it MUST use a digit or hex run; whitespace passes without the fix |
| `test_file_fault_rejects_a_malformed_supplied_signature` | `signature="nonsense"` → recomputed, not stored |
| `test_file_fault_without_a_signature_is_unchanged` | guards the 14 existing call sites |
| `test_coalescing_adopts_a_trace_ref_the_first_occurrence_lacked` | row `None` → later ref adopted **and persisted** (reopen to prove) |
| `test_coalescing_never_overwrites_an_existing_trace_ref` | the converse |
| `test_an_existing_db_migrates_to_the_new_column` | create at the 15-column schema, insert a row, reopen through `start()` → loads, and `observed_as == ""` |
| `test_migration_is_idempotent_across_restarts` | `start()` twice → no error |
| `test_an_empty_pair_projection_with_a_marked_verdict_uses_it` | D6 — the BF-793 recurrence guard |
| `test_real_pairs_beat_a_stale_carried_verdict` | D6 — the fabrication guard |
| `test_the_row_tool_id_is_a_registered_tool_id` | structural: for every filed row, `registry.get(row.tool_id) is not None` |

### Running

```powershell
# focused, serial
.venv\Scripts\pytest.exe tests\test_ad1257_defect_follows_failure.py tests\test_ad1169_fault_reports.py `
  tests\test_ad1173_repair_verification.py tests\test_ad1164_continue_or_ask.py `
  tests\test_bf754_mcp_callable_definitions.py tests\test_layer_boundaries.py `
  tests\test_ad1248_slice_c_one_shape.py -v -n 0

# broad gate, ONCE, after the wave is frozen and review findings are repaired
.venv\Scripts\pytest.exe tests\ -q -n 4 --dist=loadfile
```

---

## What this does NOT change — do not build

1. **Do not add `tool_calls` / `tool_results` to `WorkItemAgenticOutcome`.** AD-731. The
   comment at `agentic_dispatch.py:2281` is the decision.
2. **Do not add `tool_defect` or `tool_defect_evaluated` to `CREW_EXECUTION_KEYS`**
   (`crew_utils.py:38`). Censused by `tests/test_ad1248_slice_c_one_shape.py`.
3. **Do not make `WorkItemAgenticExecutor.run` file anything.** It serves five callers. It
   computes evidence; the turn owner decides.
4. **Do not import `swe_harness`, `tools`, or anything under `cognitive/` into
   `fault_report.py`.** That is why D2 injects a callable. Run
   `tests/test_layer_boundaries.py` with `FOUNDATION_MODULES` **unmodified**.
5. **Do not change `llm_function_name`, `llm_function_name_claimants`,
   `resolve_llm_function_name`, or `ToolExecutor._resolve_tool_id`.** Reuse them. BF-757
   settled their semantics against the live proxy; re-deriving the matcher is how a
   narrower rule ships looking cleaner.
6. **Do not backfill or rewrite existing fault rows.** There are none. The migration adds
   a column with a default and stops.
7. **Do not change the reply text on completed turns.** No `_DEFECT_*` string reaches a
   turn that stopped `complete`.
8. **Do not add a config flag.** `dm_agentic.enabled` already gates this path. A
   default-OFF flag is what made AD-1170 inert (AD-1180's lesson).
9. **Do not touch `ToolFailures`, `correlate_tool_outcomes`, or the AD-1248 disclosure.**
10. **Do not touch `RepairDispatcher`, `_emit_fault`, or `propose_after_occurrences`.**
11. **Do not touch `crew_executor`, the delegation path, or the AD-839 handler.**
12. **Do not change the persisted trace shape.** `build_tool_trace_payload` keeps writing
    `asdict(ToolCallRequest)`. D3 teaches the *reader* about the alias; adding a second
    name to the writer would fork provenance across trace generations.
13. **Do not delete any AD-1170 test.** They are correct about the function.

### Adjacent — file, do not build

Two BFs. Consolidate into **one** issue per the burn-down filing policy if the Captain is
in that mode; otherwise file separately as **BF-855** and **BF-856**.

- **`_emit_fault` never reaches the repair threshold.** `FAULT_REPORTED` is emitted only on
  the new-report branch (`fault_report.py:287`), so every emitted event carries
  `occurrences == 1`, while `RepairDispatcher.on_fault_event` requires
  `>= propose_after_occurrences` (`repair_dispatch.py:92-96`; `config/system.yaml:615` is 2).
  No repair proposal can follow a filed fault on the event path, with `repair.enabled: true`
  on the vessel. Fixing it changes what the Captain is asked to approve — its own decision.
- **AD-1173's argument recovery is silently sensitive to trace truncation.**
  `find_failing_arguments` recomputes the signature from `entry["output"]`, which
  `build_tool_trace_payload` head+tail truncates at `tool_trace_output_max_chars`. Safe on
  the shipped vessel only because `8192 > 6000`; invert those and every verification returns
  "inconclusive" with no diagnostic. Latent, config-dependent, not reachable by this change.

---

## Acceptance criteria

1. A DM turn that stops `complete` with a tool that failed the same way twice **files a
   fault report**, verified through the arming site — not through the detector alone.
2. An MCP tool's fault row carries a `tool_id` that `registry.get()` resolves, and its
   arguments are still recoverable from the trace via `observed_as`.
3. Two occurrences of one long (> `_ERROR_MAX`) digit-run error in different turns produce
   **one row with `occurrences == 2`**, proven across a real SQLite close and reopen.
4. One turn contributes at most one `occurrences` increment per signature, across any
   number of AD-1164 passes and the exhaustion path combined.
5. An existing `fault_reports.db` at the 15-column schema opens through `start()` without
   error, and `start()` is idempotent across restarts.
6. `resolve_exhausted_turn` called without `already_filed`, and `file_fault` called without
   `signature`, behave exactly as at HEAD. The existing call sites are unmodified.
7. `WorkItemAgenticOutcome` still carries no raw call/result pairs, and
   `CREW_EXECUTION_KEYS` is unchanged.
8. `tests/test_layer_boundaries.py` passes with `FOUNDATION_MODULES` unmodified.
9. No Captain-facing string changes on a turn that completed normally. No new config field.
10. Full suite green at `-n 4 --dist=loadfile`, run **once, after the wave is frozen** and
    after review findings are repaired. Any pre-existing failure triaged at `-n 0` before it
    is attributed to this change.
11. Run the `Diff Reviewer` subagent on the staged diff, with a different model than the one
    that wrote the code, **before committing**. Name the consumers that must accept the
    change: the fault store, `repair_verification.find_failing_arguments`, and the
    Captain-facing occurrence count in `repair_dispatch`. Point it at the live
    `fault_reports.db` — it can probe the migration directly.
12. **Verify all changes comply with the Engineering Principles in
    `.github/copilot-instructions.md`.**

---

## Tracking

| File | Entry |
|---|---|
| `PROGRESS.md` | AD-1257 + AD-1269 shipped; BF-793 CLOSED — "the detector could not read the object it was given; moved detection into the executor scope, the trigger onto tool failure, and settled what the row it writes durably means" |
| `docs/development/roadmap.md` | Bug Tracker row for BF-793 → closed by AD-1257/AD-1269 |
| `DECISIONS.md` | AD-1257 — trigger relocation, the `ToolDefect` carrier, the dedup owner. AD-1269 — canonical `tool_id`, `observed_as` provenance, signature computed once at detection, trace-ref upgrade on coalesce |
| GitHub | close #1257 citing the zero-row measurement; file BF-855 / BF-856 per *Adjacent* |

---

## Verified Against Codebase (2026-08-25, HEAD `fd16e806`, tree clean)

```
grep -n "def detect_tool_defect|_DEFECT_MIN_OCCURRENCES: int|async def file_fault_from_turn|async def resolve_exhausted_turn" src/probos/cognitive/continue_or_ask.py
  186: _DEFECT_MIN_OCCURRENCES: int = 2
  210: def detect_tool_defect(outcome: Any) -> tuple[str, str, int] | None:
  271: async def file_fault_from_turn(
  611: async def resolve_exhausted_turn(
  734: defect = detect_tool_defect(current)      <- the only production call site
  738: fault_id = await file_fault_from_turn(

grep -n "^_SCHEMA|^def error_signature|^class FaultReport|async def start|async def _load_cache|async def _persist_occurrence|def get_by_tool" src/probos/fault_report.py
  61:  _SCHEMA = """
  71:      tool_trace_ref TEXT,
  81:  CREATE INDEX IF NOT EXISTS idx_faults_tool ON fault_reports(tool_id);
  101: def normalise_error(text: Any) -> str:        (collapse <id>/<n>, THEN [:_ERROR_MAX])
  109: def error_signature(*, tool_id, error_text)
  124: class FaultReport:
  190:     async def start(self)
  205:     async def _load_cache(self)               <- SELECT names every column
  218:     def _row_to_report(row)                   <- signature=row[1], read not recomputed
  238:     async def file_fault(
  255:         signature = error_signature(...)      <- :459 post-patch (+204 from @@ -120,6 +120,210 @@)
  259-265:   coalescing branch: occurrences += 1, last_seen_at, return
  271:         error_text=str(error_text or "")[:_ERROR_MAX]
  321:     async def _persist_occurrence(...)        <- UPDATE occurrences, last_seen_at ONLY
  376:     def get_by_tool(self, tool_id)
  54:  _TOOL_ID_MAX = 128     55: _ERROR_MAX = 2000     59: _TRACE_REF_MAX = 128

grep -n "def llm_function_name|def llm_function_name_claimants|def resolve_llm_function_name" src/probos/cognitive/swe_harness/tool_call.py
  57:  def llm_function_name(tool_id: str) -> str:
  67:  def llm_function_name_claimants(name, tool_ids) -> list[str]:
  80:  def resolve_llm_function_name(name, tool_ids) -> str | None:

grep -n "llm_function_name_claimants|def list_ids|def _resolve_tool_id" src/probos/tools/*.py
  executor.py:82   def _resolve_tool_id(self, tool_id: str) -> str | None:
  executor.py:102  from ...tool_call import llm_function_name_claimants
  executor.py:105  claimants = llm_function_name_claimants(tool_id, registry.list_ids())
  registry.py:166  def list_ids(self) -> list[str]:

grep -n "^    (async )?def |^class " src/probos/cognitive/agentic_dispatch.py   (1500..2300)
  1509:     async def run(          <- registry bound :1575, offered_names :2029,
  2296:     async def _persist_tool_trace(     outcome built :2274 — ONE scope
  1467:     tool_failures: ToolFailures = field(default_factory=ToolFailures)
  1232:     return f"mcp:{self._server_name}:{self._tool_name}"
  2075:     offered_names.add(_offered)        <- the ALIAS, post-dedupe

grep -n "def find_failing_arguments|entry.get\(.name.\)|error_signature" src/probos/cognitive/repair_verification.py
  68:  def find_failing_arguments(entries, *, tool_id: str, signature: str) -> dict | None:
  82:      if str(entry.get("name") or entry.get("tool") or "") != tool_id: continue
  86:      if error_signature(tool_id=tool_id, error_text=raw_text) != signature: continue
  130:     args = find_failing_arguments(entries, tool_id=tool_id, signature=signature)
  149:     result = await executor.invoke(agent_id="system-qa", tool_id=tool_id, params=args)
  163:     if error_signature(tool_id=tool_id, error_text=str(error)) == signature:

grep -n "entry = asdict|\"name\": b.tool_call.name|def build_tool_trace_payload" src/probos/cognitive/swe_harness/agentic_loop.py
  260: def build_tool_trace_payload(
  341:     entry: dict[str, Any] = asdict(call)     <- trace 'name' IS the alias
  693:     "name": b.tool_call.name,

grep -n "scope_key.*brief.tool_id|brief.tool_id. tool has failed" src/probos/cognitive/repair_dispatch.py
  165:     "scope_key": brief.tool_id,
  169:     f"The {brief.tool_id} tool has failed the same way "

grep -n "PRAGMA table_info|ALTER TABLE capability_requests" src/probos/capability_request.py
  294-306:  the guarded additive-column migration precedent

grep -n "tool_result_max_chars|tool_trace_output_max_chars|propose_after_occurrences|continue_or_ask_enabled" config/system.yaml
  532:  continue_or_ask_enabled: true      615:  propose_after_occurrences: 2
  2422: tool_result_max_chars: 6000        2430: tool_trace_output_max_chars: 8192
```

### Measured, not read

```
RUN:  llm_function_name("mcp:docs:search")
      resolve_llm_function_name(alias, ["mcp:docs:search"])
      llm_function_name("browser")
OUT:  alias  = mcp_docs_search_38c53abe80026e47
      resolve(alias) = mcp:docs:search
      browser -> browser              <- canonicalisation is a NO-OP for non-MCP ids

RUN:  raw = "HTTPError " + "1234567890"*300 + " backend schema mismatch at the tail"  (3046 chars)
      error_signature(tool_id="t", error_text=raw) == error_signature(tool_id="t", error_text=raw[:2000])
OUT:  False
      normalise_error(raw)[-40:]       = "<id> backend schema mismatch at the tail"
      normalise_error(raw[:2000])[-40:] = "httperror <id>"
      -> collapsing frees room the raw cut already spent. Finding 2 reproduced.

RUN:  sqlite3 read-only on %LOCALAPPDATA%\ProbOS\data\fault_reports.db
OUT:  tables: ['fault_reports']   rows, distinct signatures: (0, 0)
      -> the table exists, has never been written, and CREATE TABLE IF NOT EXISTS
         will not add a column to it.
```

### Absence verified

```
CLAIM: nothing but the dead detector chain writes a fault row in production
RUN:   grep -rn "\.file_fault\(|file_fault_from_turn\(" (repo, excluding prompts)
FOUND: continue_or_ask.py:289 and :738 only; 14 hits in two test files
HOLDS: yes

CLAIM: resolve_llm_function_name has no production caller
RUN:   grep -rn "resolve_llm_function_name|llm_function_name_claimants" (whole repo)
FOUND: tool_call.py:67,80,85,92 (definitions); executor.py:102,105 (claimants ONLY);
       tests/test_bf754_mcp_callable_definitions.py x7
HOLDS: yes — `resolve_llm_function_name` is test-only; `_claimants` is the production
       surface, which is why D2 uses it rather than the tidier-looking wrapper

CLAIM: registry and the outcome construction share one function scope
RUN:   grep -n "^    (async )?def |^class " src/probos/cognitive/agentic_dispatch.py, 1500..2300
FOUND: 1509 (run), 2296 (_persist_tool_trace) — nothing between
HOLDS: yes

CLAIM: fault_report.py imports nothing above foundation
RUN:   read src/probos/fault_report.py:34-46
FOUND: hashlib, json, logging, re, time, uuid, dataclasses, typing;
       TYPE_CHECKING-only probos.storage.sqlite_factory
HOLDS: yes — an injected resolver is required, not merely preferred

CLAIM: the ledger's stated ceiling is stale
RUN:   read docs/development/open-ads-report.md:29-31, :36-41
FOUND: AD-1218 / BF-726, from layers pinned 2026-08-07T20:06:19+00:00 at aff79cae
HOLDS: yes — 51 ADs behind the prompt directory
```
