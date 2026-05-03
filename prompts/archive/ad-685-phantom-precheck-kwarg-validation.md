# AD-685: Phantom-API Pre-Check Method-Kwarg Shape Validation

**Status:** Drafted (Wave 11)
**Risk:** low (tooling-only; no runtime code change; no test surface)
**Depends on:** none
**Closes:** N/A (tooling hygiene; no GH issue yet — file as Wave 11 closes if backlogged)

---

## Solution Overview

The phantom-API pre-check (`scripts/phantom-api-precheck.ps1`, AD per Wave 8 Retrospective Addendum convention #16) catches symbol-existence phantoms but NOT method-kwarg phantoms. Three waves of evidence:

| Wave | Phantom kwarg/method missed by current pre-check |
|---|---|
| 9B | `event_log.query(event_type=...)` (real: `query_structured(event=...)`) |
| 10 | `WorkItemStore.get_pending(...)` (real: `list_work_items(...)`) — caught by symbol check, but only because `get_pending` doesn't exist; `list_work_items(work_type=...)` would have passed |
| 10 | `WorkItem(payload=...)` field name (real: `metadata`) — passed pre-check entirely |
| 10 | `runtime.work_item_store.add(work_item)` (real: `create_work_item(**kwargs)`) — passed because `add` exists on other classes |

The Wave 9 + Wave 10 retrospectives both flagged this. Wave 10 architect's third recommendation: ship the extension before the next HIGH-risk migration drafts.

**v1 ships 2 capabilities** (per convention #14 aggressive pre-deferral):
1. AST-aware kwarg validation. For each `<obj>.<method>(<kwargs>)` call site in a prompt body, locate the live signature via `ast` walk of `src/probos/`. Validate kwarg names against the parameter list. Flag mismatches.
2. **Shared heuristic pre-filter** applied uniformly to BOTH the existing symbol-existence check AND the new kwarg check. Without this, the existing symbol check would continue to flag legitimate prose-table references to past phantoms (e.g., AD-685's own `WorkItemStore.get_pending` Wave 10 motivation cite). Resolves the recursive-validity gap surfaced in pass-1 review (Required #1, option (a)).

**Deferred:**
- AD-685b: Field-name validation for dataclass/Pydantic constructors (e.g., `WorkItem(payload=...)` → flag because field is `metadata`). Requires class-AST resolution beyond signatures; harder.
- AD-685c: Type-shape validation (e.g., flag if a kwarg expects `dict` but prompt passes `list`). Requires runtime semantics; hardest.
- AD-685d (potential): Receiver-class resolution for ambiguous method names (current v1 accepts kwarg if ANY same-named method matches; cannot resolve `runtime.work_item_store.add` to the specific class).


## Dependencies

- `scripts/phantom-api-precheck.ps1` — current implementation (PowerShell + regex-only).
- Python `ast` module — used via the existing `.venv/Scripts/python.exe`.
- `src/probos/**/*.py` — target tree for signature lookup.

## Sections

### Section 1 — Add Python AST helper script

Create `scripts/phantom_api_ast_helper.py` (Python; called from PowerShell). Responsibilities:

1. Receive a (pre-filtered) prompt-body string + a `src/probos/` root path on stdin (or args). The PowerShell wrapper applies the shared pre-filter (Section 2) before invoking; the helper trusts its input.
2. Parse the prompt body for `<obj>.<method>(<kwargs>)` patterns. Use a regex narrow enough to avoid false positives within the already-filtered body (skip stdlib calls, skip self/cls).
3. **AST-index caching is v1 (not a fallback).** Build a process-local module-level dict mapping method-name → list of `(file, line, [param_names])`. Cache key: `src/probos/` mtime tree fingerprint (sum of mtimes, or just "build once per process invocation"). A single orchestrator stage often scans ≥3 prompts in a row; rebuilding the index per prompt is wasteful and risks the <5s target on 403 Python files. Store the index in a module-level global and short-circuit on subsequent calls within the same process.
4. For each candidate signature, check that every kwarg in the prompt's call site matches a parameter name. Report mismatches.
5. Emit JSON to stdout, encoded as UTF-8 (use `sys.stdout.reconfigure(encoding='utf-8')` or write bytes directly to avoid Windows codepage surprises): `{"phantoms": [{"call_site": "...", "method": "...", "kwarg": "...", "candidates": [{"file": "...", "line": N, "params": [...]}]}, ...]}`.

Helper-internal heuristics (applied AFTER the wrapper's shared pre-filter):
- If a method name has multiple definitions across `src/`, accept the kwarg if ANY signature accepts it (not all). Reduces false positives on same-named methods across classes. Documented limitation: cannot resolve receiver-class without type inference; deferred to AD-685c/d.

### Section 2 — Wire into existing PowerShell pre-check (with shared pre-filter)

Update `scripts/phantom-api-precheck.ps1`. Per pass-1 review Required #1 (option (a)): the heuristics that suppress prose-references and audit-trail mentions must apply uniformly to BOTH the existing symbol check and the new kwarg check, otherwise the existing symbol check continues to flag the same prose patterns this AD is meant to fix.

1. **Add a shared body pre-filter step** that produces a `$filteredBody` from the raw prompt body. The pre-filter strips/masks (replaces with whitespace of equal length to preserve line numbers):
   - Fenced code blocks NOT tagged `python` (i.e., ` ```bash`, ` ```pwsh`, ` ```sh`, ` ```text`, ` ```json`, and bare ` ``` ` with no language tag). Only ` ```python ` and ` ```py ` blocks are scanned.
   - `## Revision` sections (and their content through the next `## ` heading or EOF) — audit trail, expected to mention deprecated names.
   - Markdown table cells whose content is a single backticked token followed by free prose (heuristic: pipe-delimited cell whose first non-whitespace char is `` ` `` and whose backticked content matches `<Word>.<word>` or `<Word>(...)`). This suppresses the Wave 10 motivation-table cite of `WorkItemStore.get_pending` without affecting real call expressions in code blocks.
2. **Symbol check (existing logic, preserved; now reads `$filteredBody`).** The existing CamelCase-class regex, the `runtime.X` regex, and the constructor regex all run against `$filteredBody` instead of the raw `$body`. Existing tunings (negative framing, `runtime.X` self-introduction) remain unchanged.
3. **Kwarg check (new).** After the symbol check completes, invoke `scripts/phantom_api_ast_helper.py` passing `$filteredBody` (NOT raw body) on stdin alongside the `src/probos` root.
4. Parse JSON output; merge into the existing `$phantomsHere` array with category `kwarg_mismatch`.
5. Display category in output (`runtime.X` / `<Class>.<method>` / `kwarg_mismatch`).
6. Exit code: 1 if ANY phantom (existing behavior); no change.

**Note on "preserved verbatim":** the existing symbol check's *logic* is preserved (regex patterns, tunings, exit semantics). What changes is its *input* — it now operates on the pre-filtered body. This is the minimum-risk way to deliver shared heuristics without rewriting the existing check.

### Section 3 — Calibration sweep

Run the extended pre-check against archived Wave 8/9/10 prompts. **Required corpus** (named to remove ambiguity for the Builder; map directly to test #2 / test #3 regression cases):
- `prompts/archive/ad-641c-*.md` — Wave 9B `event_log.query(event_type=...)` regression (test #2 corpus).
- `prompts/archive/ad-500-*.md` — Wave 10 `WorkItemStore.get_pending` / `WorkItem(payload=...)` regressions (test #3 corpus).
- Plus a sample of ≥3 other archived Wave 8/9/10 prompts (Builder picks; recent first).

Document:
- True positives the kwarg check catches.
- False positives requiring heuristic tuning.
- Performance cost (target: <5 seconds per prompt with AST-index cached across the sweep; Builder reports both first-prompt time and steady-state per-prompt time).

If false-positive rate is >2 per prompt, tune heuristics before merging. Acceptable: ≤1 false positive per prompt with clear documentation in summary output.

**Recursive-validity check (mandatory):** after the calibration sweep, run the extended pre-check against `prompts/ad-685-phantom-precheck-kwarg-validation.md` itself. Expected: 0 phantoms (the shared pre-filter suppresses the prose-table `WorkItemStore.get_pending` cite). If any phantom remains, the pre-filter is incomplete — tune before merging.

## What This Does NOT Change

- Existing symbol-existence check **logic** — regex patterns, tunings, exit semantics all preserved. Only its **input** changes (now reads pre-filtered body).
- Pre-check exit semantics — still 0 = clean, 1 = phantoms.
- Any wave-orchestrator integration — pre-check stage runs the same command; output format extended additively.
- Field-name validation (dataclass/Pydantic `Field(...)`) — deferred to AD-685b.
- Runtime/type-shape validation — deferred to AD-685c.
- Receiver-class resolution for same-named methods — deferred (AD-685c/d).

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_helper_runs_on_clean_prompt_returns_empty_phantoms` | No false positives on a hand-crafted clean prompt |
| 2 | `test_helper_catches_event_log_query_event_type_kwarg_mismatch` | Wave 9B regression — flags `query(event_type=...)` (real param: `event=`) |
| 3 | `test_helper_catches_work_item_store_get_pending` | Wave 10 regression — flags non-existent method |
| 4 | `test_helper_skips_kwargs_in_non_python_fenced_blocks` | Heuristic — verify pwsh + bash + sh + text + bare-fence (no language tag) all skipped; only ` ```python ` / ` ```py ` fences scanned |
| 5 | `test_helper_skips_kwargs_in_revision_section` | Audit trail mentions are not phantoms |
| 6 | `test_helper_accepts_kwarg_matching_any_definition` | Multiple definitions of same method name across classes — pass if any matches (limitation; receiver-class resolution deferred to AD-685c/d) |
| 7 | `test_powershell_wrapper_merges_kwarg_mismatches_with_symbol_phantoms` | Integration: combined output |
| 8 | `test_powershell_wrapper_exit_code_1_when_kwarg_phantom` | Exit semantics preserved |
| 9 | `test_powershell_wrapper_shared_prefilter_suppresses_prose_table_phantom` | Required #1 from pass-1 review — symbol check no longer flags `WorkItemStore.get_pending` when cited in a markdown prose table (AD-685's own recursive-validity case) |

Tests live at `tests/test_phantom_api_precheck_kwargs.py`. Use Python helper directly + invoke PowerShell wrapper via subprocess for integration tests.

## Tracking

1. **PROGRESS.md:** prepend AD-685 entry.
2. **DECISIONS.md:** add entry under Era V:

```markdown
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
```

3. **docs/development/roadmap.md:** add AD-685 entry under tooling/hygiene section.

## Verified Against Codebase (2026-05-03)

```
ls scripts/phantom-api-precheck.ps1
  scripts/phantom-api-precheck.ps1 exists (Wave 8 Addendum #16); 160 lines.

grep -n "phantomsHere\|Test-SymbolExists\|allSrc" scripts/phantom-api-precheck.ps1
  L84 $phantomsHere = [System.Collections.ArrayList]@()
  L67 function Test-SymbolExists
  L63 $allSrc = ($srcContent.Values -join "`n")
  (Existing structure preserved; pre-filter inserts before regex matching at ~L94)

grep -n 'matches.*Matches.*body' scripts/phantom-api-precheck.ps1
  L97  $matches = [regex]::Matches($body, 'runtime\.([a-z_][a-z0-9_]*)')
  L105 $matches = [regex]::Matches($body, '\b([A-Z][a-zA-Z0-9_]+)\.([a-z_][a-z0-9_]+)')
  L114 $matches = [regex]::Matches($body, '\b([A-Z][a-zA-Z0-9_]{3,})\(')
  (All three must change to $filteredBody after Section 2 lands)

ls .venv/Scripts/python.exe
  (Python available for AST helper)

Get-ChildItem src/probos -Recurse -Filter *.py | Measure-Object
  403 Python files (per pass-1 review verification; <5s with cached index achievable)

./scripts/phantom-api-precheck.ps1 prompts/ad-685-phantom-precheck-kwarg-validation.md
  Exit 1; 1 phantom: WorkItemStore.get_pending. Documented self-reference (Wave 10 motivation cite in markdown prose table). EXPECTED before AD-685 ships; the shared pre-filter MUST suppress this after Builder lands the change.
```

## Revision (2026-05-03)

Applied pass-1 review (`prompts/Reviews/ad-685-phantom-precheck-kwarg-validation-review.md`).

**Required #1 (resolved, option B/Option (a) chosen):** lift the prose-table + non-Python-fence + `## Revision`-section heuristics out of the AST helper and into a **shared pre-filter** in `scripts/phantom-api-precheck.ps1`, applied uniformly to BOTH the existing symbol check and the new kwarg check. Section 2 reworked from "existing symbol check preserved verbatim" to "existing symbol check logic preserved; input changed to pre-filtered body." Solution Overview now explicitly lists 2 capabilities (kwarg check + shared pre-filter) instead of 1. Acceptance Criteria + Hard-Stops both gate on the recursive-validity check. Decision rationale: option (a) over (b)/(c) because it generalizes a heuristic the prompt already needed for the new check, costs ~10 lines, and keeps the recursive-validity acceptance criterion honest without per-file allowlists or prose contortions.

**Recommended #1 (folded):** AST-index caching promoted from Hard-Stops fallback to v1 implementation note in Section 1 step 3. Process-local module-level dict; rebuild on first call per process invocation. Performance target restated as "<5s per prompt with cached index" with both first-prompt cold-build and steady-state times reported. Hard-Stop reworded to ">30s on cold first build".

**Recommended #2 (folded):** Test #4 expanded from "pwsh code block" to verify pwsh + bash + sh + text + bare-fence; only ` ```python ` / ` ```py ` fences scanned. Renamed to `test_helper_skips_kwargs_in_non_python_fenced_blocks`.

**Recommended #3 (folded):** Same-named-method limitation explicitly called out in DECISIONS.md entry as deferred to AD-685c/d, and in the v1 deferral list. "Accept kwarg if any overload matches" reframed as "any same-named definition matches" (avoids overloading the term "overload" — see Nit #3).

**Recommended #4 (folded):** Calibration corpus named explicitly in Section 3 — `ad-641c-*` (test #2 regression), `ad-500-*` (test #3 regression), plus ≥3 other recent archived prompts.

**Nits:**
- Nit #1 (folded): "preserved verbatim" replaced everywhere with "logic preserved; input changed to pre-filtered body" or equivalent.
- Nit #2 (folded): recursive-validity gate now appears in BOTH Acceptance Criteria and Hard-Stops.
- Nit #3 (folded): test #6 renamed `..._any_overload` → `..._any_definition`. DECISIONS.md text updated to match.
- Nit #4 (folded): Section 1 step 5 specifies UTF-8 stdout encoding with `sys.stdout.reconfigure(encoding='utf-8')`.

**No new Required findings surfaced during revision.** Test count grew 8 → 9 (added test #9 for the shared-pre-filter suppression of the prose-table phantom; covers the pass-1 Required #1 case directly).

**Recursive-validity expected behavior:** the existing pre-check (`./scripts/phantom-api-precheck.ps1 prompts/ad-685-phantom-precheck-kwarg-validation.md`) STILL flags `WorkItemStore.get_pending` as 1 phantom on this revised prompt — that is correct and expected. The whole point of AD-685's shared pre-filter is to suppress this class of false positive once Builder ships. The recursive-validity gate is a Builder-side acceptance check, not a pre-dispatch one. No regression beyond the documented self-reference.


## Acceptance Criteria

- `scripts/phantom_api_ast_helper.py` exists and runs against a prompt + src tree.
- `scripts/phantom-api-precheck.ps1` applies the shared pre-filter, then runs the symbol check on the filtered body, then invokes the AST helper on the filtered body, then merges output.
- Calibration sweep against named archived prompts (`ad-641c-*`, `ad-500-*`, ≥3 others) documents true/false positive rates.
- 9 tests pass.
- **Recursive-validity gate (also Hard-Stop):** `./scripts/phantom-api-precheck.ps1 prompts/ad-685-phantom-precheck-kwarg-validation.md` exits 0 with 0 phantoms after AD-685 ships. Currently exits 1 with the documented `WorkItemStore.get_pending` self-reference; the shared pre-filter must suppress it.
- Performance: <5s per prompt with cached AST index; first-prompt cold-build time also reported.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- DECISIONS.md entry under Era V.

## Hard-Stops

- AST parse of `src/probos/` takes >30s on cold first build — performance unacceptable even with caching; surface to architect (may need to scope index narrower than full `src/probos/`).
- Heuristics produce >5 false positives per archived prompt — architect must tune before merge.
- Helper conflicts with existing pre-check semantics (e.g., changes exit codes) — surface; integration must be additive.
- **Recursive-validity gate fails:** post-build `./scripts/phantom-api-precheck.ps1 prompts/ad-685-phantom-precheck-kwarg-validation.md` still flags any phantom — pre-filter is incomplete; tune before merge (do NOT special-case the AD-685 file by name).
- Shared pre-filter changes existing symbol check's behavior on a prompt that previously passed (regression) — surface; pre-filter must only suppress, never add new false positives to the symbol check.
