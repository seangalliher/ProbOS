# Wave 45 Dispatch — AD-661b + AD-661c Combo (DiagnosticContextService Extensions)

**Wave id:** 45
**Kind:** combo (single prompt, two ADs)
**Prompt:** `prompts/ad-661bc-diagnostic-context-extensions.md`
**Closes:** GH issues #412 (AD-661b) + #413 (AD-661c) — both close together on a single commit.
**Depends on:** Wave 44 (AD-594a, commit 3c44903) — for `runtime.records_store` adoption only; no consultation surface touched.
**Test floor:** 10. **Plan:** 12 tests. **Baseline:** 11109 → expected 11121.

---

## Why combo

Captain's "no trivial deferral" rule. AD-661b (Ship's Records consumption) and AD-661c (budget remainder redistribution) both sit on the same surface (`DiagnosticContextService.assemble`). Shipping them separately would mean two near-identical drift checks plus a stranded intermediate state where records exist in the bundle but can't redistribute. One Builder cycle clears both.

---

## Standing reminders

- **Test gate:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile`. Triage parallel-failure-only suspects with `-n 0`.
- **Pre-commit deletion sanity:** any single file with > 200 lines deleted halts the wave for triage.
- **`-x` is forbidden under xdist.**
- **No prompt-section edits during build** unless an architectural blocker surfaces; revise via revision review and re-build.
- **Commit message convention:** `Wave 45 build: AD-661b + AD-661c combo (Ship's Records + remainder redistribution) — closes #412 + #413`.

---

## Build-time hard-stops

1. **Existing AD-661 v1 tests fail** (`tests/test_ad661_diagnostic_context.py`). The back-compat invariant is the most important assertion in this wave. If a v1 test fails after build, it's a real regression — surface to architect, do **not** modify the v1 test file.
2. **Phantom API in implementation** that wasn't in the prompt (e.g. assuming a `RecordsStore.search()` method exists — it does not; only `list_entries` + `read_entry`).
3. **Wave 14 lesson — async vs sync collector mix:** `_gather_record_candidates` is async (calls `await store.list_entries`), `_gather_episode_candidates` stays sync (no awaitable). The new `assemble` body must `await` records but not episodes. If a test mocks records as sync and the build awaits it, it'll silently produce a coroutine in the bundle — fix the mock, not the source.

---

## Architect Decision Log (DLog)

### DLog #1 — RecordsStore read API confirmed: `list_entries` + `read_entry`
HEAD `3c44903` shows two read entry points:
- `list_entries(directory="", *, author="", status="", tags=None, classification="")` returns `list[{"path", "frontmatter"}]`.
- `read_entry(path, reader_id, reader_department="")` returns `{"frontmatter", "content", "path"}` or `None` with classification gate enforcement.

The prompt's `_gather_record_candidates` uses both. **No new RecordsStore surface is introduced.** This is verify-first clean.

### DLog #2 — Synthetic system reader, not per-agent authorization
`reader_id="_diagnostic_context_system"` + empty department. RecordsStore's classification gate (`read_entry` private/department branches) naturally yields only `ship`/`fleet` records to this reader. v1 deliberately does **not** thread `agent_id` through to the records reader — different semantics from chain_trace `agent_id` (which is a filter, not an authorization principal). Per-agent records authorization is a future AD (AD-661f). Documented in module docstring + config docstring + prompt.

### DLog #3 — Allocation defaults 30/25/25/20
Captain spec exact. Sum = 1.0. The Pydantic `model_validator` is updated from 3 ratios to 4. Reviewers should not flag the validator change as scope creep — it's required by the new field.

### DLog #4 — Two-pass redistribution algorithm with stable priority order
`_TIER_PRIORITY = ("chain_traces", "procedures", "episodes", "records")`. Pass 1 fills each tier up to its allocation. Pass 2 walks priority order again, topping up tiers with leftover candidates while global budget remains. `truncated` is True iff at least one tier still has unconsumed candidates after both passes. **Implementation is centralized in `_fill_with_redistribution(candidates_by_tier, allocations, total_budget, redistribute) -> (filled, truncated)`** — collectors no longer carry budget logic.

### DLog #5 — `_collect_*` collectors RENAMED to `_gather_*` candidate producers
The old names had per-tier budget clipping baked in. The new contract gathers all keyword-matching candidates and lets the central helper handle budgets. This is a rename + signature change — no callers outside `assemble()` exist (private methods). Builder must rewrite the three existing collectors and add the new records gatherer; v1 tests reach in via `assemble()` only, so they remain untouched.

### DLog #6 — Router needs no edit
`routers/diagnostic_context.py` returns `bundle.to_dict()`. `to_dict()` now includes `records`. The endpoint surface evolves transparently. Verify with a smoke assertion if drift suspected; explicit API test deferred unless build surfaces a regression.

### DLog #7 — Conftest already exercises the None-records-store path
`tests/conftest.py:236` sets `rt._records_store = None`. Existing fixtures will hit the empty-records branch automatically; that's why Test #4 just asserts the explicit shape rather than introducing a new fixture flavor.

### DLog #8 — Backward-compat invariant on existing AD-661 v1 tests
`tests/test_ad661_diagnostic_context.py` (8 tests, including `test_procedure_exemplar_resolution`, `test_chain_trace_keyword_filter_and_budget`, `test_budget_truncation_sets_flag`, `test_episode_dedup_across_procedures`) **must continue to pass unmodified.** The internal `_collect_*` → `_gather_*` rename is invisible to those tests because they invoke `assemble()`. The new 4th tier defaults to records=[] when `runtime.records_store` is None — same shape v1 fixtures already use. This is the single most important non-functional acceptance gate.

---

## Phantom-API pre-check expectation

Run before build (or rely on prompt's verify-first block):

```
pwsh ./scripts/phantom-api-precheck.ps1 -PromptPath prompts/ad-661bc-diagnostic-context-extensions.md
```

Expected results:
- 0 NEW phantoms.
- FPs (acceptable): `class:DiagnosticBundle`/`class:DiagnosticContextService` (intro by prompt, already in HEAD); `class:SimpleNamespace` (stdlib); `runtime.records_store` (already adopted at HEAD); `_fill_with_redistribution`/`_gather_record_candidates`/`_read_record_excerpt`/`_TIER_PRIORITY` (intro by prompt).
- Same FP class as Waves 27-44.

If the script reports a kwarg-mismatch on `RecordsStore.read_entry` or `RecordsStore.list_entries`, **stop** — the codebase has shifted since draft and the prompt needs revision. (Verified at HEAD `3c44903`; signatures confirmed.)

---

## Files affected

| File | Change |
|------|--------|
| `src/probos/cognitive/diagnostic_context.py` | Sections 0, 2, 3, 4, 5, 6, 7 — module constants, bundle field, ctor, assemble rewrite, collector rename, records gatherer, redistribution helper. ~+260 lines, ~−110 lines (rename + rewrite). |
| `src/probos/config.py` | Section 1 — `DiagnosticContextConfig` 4-ratio update. ~+30/−15. |
| `src/probos/startup/finalize.py` | Section 8 — wirer adds 2 kwargs. ~+2/0. |
| `tests/test_ad661bc_records_redistribution.py` | NEW — 12 tests. ~+360 lines. |
| `PROGRESS.md` | Prepend AD-661b + AD-661c CLOSED entry. |
| `docs/development/roadmap.md` | Flip AD-661b + AD-661c rows Scoped→Complete. |
| `DECISIONS.md` | Single combined Era V entry. |

`tests/test_ad661_diagnostic_context.py` is **NOT** modified. `routers/diagnostic_context.py` is **NOT** modified. `runtime.py` is **NOT** modified.

---

## Issue close

Both #412 and #413 close on the same commit. Recommended close comment template:

> AD-661b + AD-661c v1 closed in Wave 45 (commit ${SHA}). Combo wave shipped together per Captain's "no trivial deferral" rule. **AD-661b** — `DiagnosticBundle.records: list[dict]` field; `_gather_record_candidates` reads `runtime.records_store.list_entries()` + `read_entry()` with synthetic system reader (`_diagnostic_context_system`, surfaces ship/fleet records only); per-agent record auth deferred AD-661f. **AD-661c** — `_fill_with_redistribution` two-pass fill in priority order (chain_traces > procedures > episodes > records); `redistribute_remainder` config flag (default True). New 4-tier defaults: 30/25/25/20. +12 tests. Existing v1 tests pass unmodified.

If GitHub MCP `gh issue close` returns EMU 403 (same as Waves 31-44), Captain closes manually.

---

## Wave-orchestrator state

`prompts/wave-plan.yaml` id="45" already pre-populated with `prompt_paths: [prompts/ad-661bc-diagnostic-context-extensions.md]`, `dispatch_prompt: prompts/WAVE-45-DISPATCH.md`, `issues_to_close: [412, 413]`, `status: pending`. Architect drafts the prompt + dispatch in this single commit; Builder picks up next wave invocation.
