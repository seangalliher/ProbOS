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

**v1 ships 1 of 3 capabilities** (per convention #14 aggressive pre-deferral):
1. AST-aware kwarg validation. For each `<obj>.<method>(<kwargs>)` call site in a prompt body, locate the live signature via `ast` walk of `src/probos/`. Validate kwarg names against the parameter list. Flag mismatches.

**Deferred:**
- AD-685b: Field-name validation for dataclass/Pydantic constructors (e.g., `WorkItem(payload=...)` → flag because field is `metadata`). Requires class-AST resolution beyond signatures; harder.
- AD-685c: Type-shape validation (e.g., flag if a kwarg expects `dict` but prompt passes `list`). Requires runtime semantics; hardest.

## Dependencies

- `scripts/phantom-api-precheck.ps1` — current implementation (PowerShell + regex-only).
- Python `ast` module — used via the existing `.venv/Scripts/python.exe`.
- `src/probos/**/*.py` — target tree for signature lookup.

## Sections

### Section 1 — Add Python AST helper script

Create `scripts/phantom_api_ast_helper.py` (Python; called from PowerShell). Responsibilities:

1. Receive a prompt-body string + a `src/probos/` root path on stdin (or args).
2. Parse the prompt body for `<obj>.<method>(<kwargs>)` patterns. Use a regex narrow enough to avoid false positives (skip code blocks marked as prose, skip stdlib calls, skip self/cls).
3. For each match, walk `src/probos/` building an `ast` index of `def method(...)` signatures keyed by method name (multiple matches allowed; report all candidates).
4. For each candidate signature, check that every kwarg in the prompt's call site matches a parameter name. Report mismatches.
5. Emit JSON to stdout: `{"phantoms": [{"call_site": "...", "method": "...", "kwarg": "...", "candidates": [{"file": "...", "line": N, "params": [...]}]}, ...]}`.

Heuristics to avoid false positives:
- Skip method calls in fenced markdown code blocks marked as `bash`, `pwsh`, or non-Python languages.
- Skip method calls inside backticks within prose ("the `frobnicate(foo=)` API" — these are documentation references; flag only when in a call expression).
- If a method name has multiple definitions across `src/`, accept the kwarg if ANY signature accepts it (not all). Reduces false positives on overloaded names.
- Skip if the call site appears inside a `## Revision` section (audit trail, expected to mention old names).

### Section 2 — Wire into existing PowerShell pre-check

Update `scripts/phantom-api-precheck.ps1`:

1. After the existing symbol-existence checks complete, run the AST helper for each prompt.
2. Parse JSON output; merge into the existing `$phantomsHere` array with category `kwarg_mismatch`.
3. Display category in output (`runtime.X` / `<Class>.<method>` / `kwarg_mismatch`).
4. Exit code: 1 if ANY phantom (existing behavior); no change.

### Section 3 — Calibration sweep

Run the extended pre-check against archived Wave 8/9/10 prompts. Document:
- True positives the kwarg check catches.
- False positives requiring heuristic tuning.
- Performance cost (target: <5 seconds per prompt; the AST parse dominates).

If false-positive rate is >2 per prompt, tune heuristics before merging. Acceptable: ≤1 false positive per prompt with clear documentation in summary output.

## What This Does NOT Change

- Existing symbol-existence check — preserved verbatim.
- Pre-check exit semantics — still 0 = clean, 1 = phantoms.
- Any wave-orchestrator integration — pre-check stage runs the same command; output format extended additively.
- Field-name validation (dataclass/Pydantic `Field(...)`) — deferred to AD-685b.
- Runtime/type-shape validation — deferred to AD-685c.

## Test Plan

| # | Test | Purpose |
|---|---|---|
| 1 | `test_helper_runs_on_clean_prompt_returns_empty_phantoms` | No false positives on a hand-crafted clean prompt |
| 2 | `test_helper_catches_event_log_query_event_type_kwarg_mismatch` | Wave 9B regression — flags `query(event_type=...)` (real param: `event=`) |
| 3 | `test_helper_catches_work_item_store_get_pending` | Wave 10 regression — flags non-existent method |
| 4 | `test_helper_skips_kwargs_in_fenced_pwsh_code_block` | Heuristic — pwsh code blocks are not Python |
| 5 | `test_helper_skips_kwargs_in_revision_section` | Audit trail mentions are not phantoms |
| 6 | `test_helper_accepts_kwarg_matching_any_overload` | Multiple definitions of same method name — pass if any matches |
| 7 | `test_powershell_wrapper_merges_kwarg_mismatches_with_symbol_phantoms` | Integration: combined output |
| 8 | `test_powershell_wrapper_exit_code_1_when_kwarg_phantom` | Exit semantics preserved |

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

Heuristics to suppress false positives: skip non-Python fenced code blocks, skip backticked prose references that aren't call expressions, skip `## Revision` audit-trail sections, accept kwarg if any overloaded definition matches.

**Why now:** Third documented recurrence in 3 waves. Architect's reactive review-pipeline catches these but the proactive drafting pipeline doesn't. One scripted convention beats N drafting-time conventions.

**Deferred:**
- AD-685b: Field-name validation for dataclass/Pydantic constructors (e.g., `WorkItem(payload=...)`).
- AD-685c: Type-shape validation for kwargs (dict vs list etc.).

**Cross-links:** Wave 8 Retrospective Addendum #16 (original pre-check), Wave 9 Retrospective Addendum tooling outcome, Wave 10 architect's third recommendation.
```

3. **docs/development/roadmap.md:** add AD-685 entry under tooling/hygiene section.

## Verified Against Codebase (2026-05-03)

```
ls scripts/phantom-api-precheck.ps1
  scripts/phantom-api-precheck.ps1 exists (Wave 8 Addendum #16)

grep -n "phantoms" scripts/phantom-api-precheck.ps1 | head -5
  (Builder reads existing structure)

ls .venv/Scripts/python.exe
  (Python available for AST helper)

ls src/probos/**/*.py | wc -l  # Builder verifies file count for performance estimate
```

## Acceptance Criteria

- `scripts/phantom_api_ast_helper.py` exists and runs against a prompt + src tree.
- `scripts/phantom-api-precheck.ps1` invokes it after symbol checks; merges output.
- Calibration sweep against archived Wave 8/9/10 prompts documents true/false positive rates.
- 8 tests pass.
- Pre-check still passes on the AD-685 prompt itself (recursive validity).
- Performance: <5s per prompt.
- DECISIONS.md entry under Era V.

## Hard-Stops

- AST parse of `src/probos/` takes >30s — performance unacceptable; consider caching index across calls.
- Heuristics produce >5 false positives per archived prompt — architect must tune before merge.
- Helper conflicts with existing pre-check semantics (e.g., changes exit codes) — surface; integration must be additive.
