# AD-748 — Wave-close CI hygiene checklist

**Status:** Filed (2026-05-20). Awaiting Builder pickup in a future wave.
**Dependencies:** None — pure tooling.
**Estimated tests:** +6 pytest (script unit tests), +0 vitest. No production code changes.
**Priority:** 2 (caught five real CI breaks in one night; cheap to land).

---

## Problem

Tonight's 5-BF CI-rescue arc (commits `37f1c922` → `0b507670`) revealed a recurring class of dependency-add discipline failures that are invisible to per-prompt review and per-commit gates but blow up the next CI push. They all share one shape: a local change that passes locally because the local environment was *already* in a different state than CI's clean checkout.

| BF | SHA | Trap | Why local was green |
|---|---|---|---|
| BF-319 | `37f1c922` | `package.json` changed without `npm install` regenerating `ui/package-lock.json` | Local `node_modules/` already had the new dep from a manual `npm install` |
| BF-320 | `d56aeeb7` | Per-test 90s `pytest-timeout` too tight for GHA runners | Dev box runs heavy-fixture tests ~2-3× faster than the GHA runner |
| BF-321 | `c21f19d3` | AD-718e added `getServerPiperVoices` to `audio/voice.ts` but only updated 1 of 17 `vi.mock('../audio/voice', ...)` blocks. 13 vitests leaked unhandled async errors → exit code 1 even with 839/839 passing | Vitest counts test pass/fail, not unhandled-promise warnings — local run "looked green" |
| BF-322 | `34278346` | Workflow `timeout-minutes: 15` exceeded as suite grew; `-x` with xdist violated user-memory rule (one flake killed full signal) | No local CI-budget tracking; `-x` was the original wave-1 default |
| BF-323 | `0b507670` | Per-class `@pytest.mark.timeout(60)` override tighter than the new 180s global | Pre-dated decomposer+LLM-client wiring that made the path slower; not visible until decomposer landed |

Final-state recovery: 14304 pytest + 23 skipped, ui-tests 839 + 1 skipped, both green in ~24min total wallclock. But the recovery cost five force-pushes against a noisy CI signal and ~2 hours of operator time that should have been zero.

**Captain quote** (from BF-322 commit body):
> "worth a hygiene AD eventually"

This is that AD.

---

## Solution

A pre-flight checklist that Builder runs at every **wave-close** (or every commit that touches `package.json`, `pyproject.toml`, heavily-mocked TS modules, or adds >20 tests). Cheapest implementation is:

1. A new `scripts/wave-close-precheck.ps1` script.
2. A new section in `prompts/BUILDER-EXECUTION-PLAN.md` referencing it as a gate.

No CI changes in v1 — the script runs locally before push, so the existing CI signal stays canonical. The forward-marker AD-748-2 adds a GHA workflow that runs the same script as a separate fast job (~30s) so the operator can't bypass it.

---

## v1 scope — the script

`scripts/wave-close-precheck.ps1` must run all five checks. Each check is independent; the script reports all failures, not just the first.

### Check 1: Lock-file sync

```powershell
cd ui
npm install --package-lock-only --dry-run
# If exit code != 0 OR if --dry-run output indicates package-lock.json would change → FAIL
```

**Catches:** BF-319-class (`package.json` modified without regenerating lock). CI's `npm ci` is strict and refuses to install if `package-lock.json` doesn't satisfy `package.json`.

### Check 2: Mock parity

Grep new exports from documented heavily-mocked modules against all `vi.mock('.../<module>', ...)` blocks. Fail if any mock block lacks any export the real module surfaces.

**Heavily-mocked module list (v1):**

- `ui/src/audio/voice.ts`
- `ui/src/audio/wakeWord.ts`
- `ui/src/audio/speechInput.ts`
- `ui/src/store/useStore.ts`
- `ui/src/api.ts`

Algorithm per module:

1. Extract exported symbols (regex on `^export (const|function|async function|class|let|var) (\w+)` plus `^export \{ ... \}` re-exports).
2. For every `vi.mock('<module-path>', () => ({ ... }))` block in `ui/src/**/*.test.tsx`, parse the returned object's keys.
3. If any export from step 1 is missing from any mock block in step 2 → FAIL with the specific test file + missing symbol.

**Catches:** BF-321-class (new export, partial mock update, unhandled-promise leak).

### Check 3: Test-runtime budget

Run full pytest suite (no xdist — measure single-core wall) and warn if total wall > 22min (10min headroom below the 30min CI ceiling).

```powershell
$start = Get-Date
pytest tests/ -q -n 0 --tb=no
$elapsed = (Get-Date) - $start
if ($elapsed.TotalMinutes -gt 22) { Write-Warning "..." }
```

Optional: skip if `$env:WAVE_CLOSE_FAST -eq "1"` for iteration. Document the override.

**Catches:** Drift toward the BF-322-class wall — the moment the suite crosses 22min on a clean local run, the GHA runner is already crossing 30min on bad days and the operator should bump the workflow ceiling AND start budget-cutting tests in the next wave.

### Check 4: Local-tight pytest-timeout audit

Grep for `@pytest.mark.timeout(N)` in `tests/**/*.py` where N < the global timeout (180s as of BF-320). Report any tighter overrides as INFO so the operator can review whether each one is still justified.

```powershell
$global = 180  # read from pyproject.toml [tool.pytest.ini_options] timeout
Select-String -Path tests/**/*.py -Pattern '@pytest\.mark\.timeout\((\d+)\)' |
    Where-Object { [int]($_.Matches[0].Groups[1].Value) -lt $global }
```

**Catches:** BF-323-class (per-class override tighter than new global, surfaces only when the path under test gets slower).

### Check 5: Vitest unhandled-error check

```powershell
cd ui
npx vitest run
# Exit code MUST be 0 — not just "all tests passed"
```

The BF-321 failure mode is invisible to a "839/839 passed" summary. Vitest exits non-zero when an unhandled promise rejection leaks even if every assertion passed. The check is just "did vitest exit 0?"

**Catches:** BF-321-class at the runtime check layer (defense-in-depth — Check 2 catches the static cause; Check 5 catches the dynamic symptom).

---

## v1 scope — Builder protocol

Add a new section to `prompts/BUILDER-EXECUTION-PLAN.md` titled **"Wave-close pre-flight gate"** with:

- When to run (every wave-close commit; every commit touching `package.json` / `pyproject.toml` / files in the heavily-mocked list / commits adding >20 tests).
- Command: `pwsh scripts/wave-close-precheck.ps1`.
- Failure handling: FAIL → fix and re-run; WARNING → file a forward-marker BF for the next wave to address.
- Forbidden overrides: never `--skip` past Check 1 or Check 5. Check 3 may be skipped via `WAVE_CLOSE_FAST=1` during iteration but MUST be re-run before push.

---

## Heavily-mocked module list maintenance (the second hidden trap)

The list itself is a moving target. Three failure modes:

1. **A new heavily-mocked module joins the codebase** and Check 2 doesn't know about it (false negative — BF-321 recurs for a different module).
2. **A module loses its heavily-mocked status** (e.g. tests refactored to use a real fixture) and the script keeps grepping it (false positive — operator ignores Check 2 warnings and learns to ignore real ones).
3. **The list lives in one place** (the script) and Reviewers don't know to flag "this PR added a new `audio/foo.ts` that's mocked by 12 tests."

**v1 mitigation:** the list lives in a single dict at the top of `wave-close-precheck.ps1` with a comment pointing at this AD. The Architect adds a review-flag candidate for prompts that introduce a new TS module with >5 `vi.mock` references — those PRs MUST update the list in the same commit.

**Forward marker AD-748-3** (added below) auto-discovers heavily-mocked modules by counting `vi.mock` references across the test tree and surfacing any module with >5 mocks as a candidate.

---

## Forward markers

- **AD-748-1** — Pre-commit hook integration. `.husky/pre-commit` or `.git/hooks/pre-commit` shim that runs `wave-close-precheck.ps1` on commits touching the trigger files. Advances when the operator decides the script's runtime is acceptable inside the commit loop (~30s for checks 1+2+4+5 without Check 3 budget run).
- **AD-748-2** — GHA workflow that runs the same script as a separate fast job (Lock+Mock+Vitest parity, no full pytest budget). Advances when operator confirms v1 script is stable and the local gate has caught real issues for two consecutive waves.
- **AD-748-3** — Auto-discover heavily-mocked modules. Replace the static list in `wave-close-precheck.ps1` with a dynamic scan that surfaces any `ui/src/**/*.ts` module with >5 `vi.mock` references. Advances when the static list has been wrong twice (operator-judged).

---

## What this does NOT change

- No production code.
- No test code (except the script's own self-tests in `tests/test_wave_close_precheck.py`).
- No CI workflow changes in v1 (deferred to AD-748-2).
- No DECISIONS.md entry — tooling AD, no architectural commitment.
- No `wave-plan.yaml` change — this AD is filed, not slotted into Wave 181.

---

## Acceptance criteria

1. `scripts/wave-close-precheck.ps1` exists and runs all five checks.
2. Each check produces actionable output (file path + line number + missing symbol where applicable).
3. Exit code: 0 on all-pass, 1 on any FAIL, 0 on WARN-only (operator's call to address).
4. Builder protocol section added to `prompts/BUILDER-EXECUTION-PLAN.md`.
5. Self-tests in `tests/test_wave_close_precheck.py` (~6 pytest) cover: lock-file detection, mock-parity detection (using a temp fixture file with intentional gap), tight-timeout grep, and exit-code semantics.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Tracking

- **Roadmap:** AD-748 row + 3 forward marker rows (-1, -2, -3).
- **DECISIONS.md:** no entry (tooling AD).
- **`wave-plan.yaml`:** no entry (filed, not slotted).
- **GitHub issue:** filed at issue creation time.

---

## Verified Against Codebase (2026-05-20)

Pre-flight verification grepped for the asserted recurring patterns:

```
git log --oneline -10
  37f1c922 BF-319: regenerate ui/package-lock.json to match package.json
  d56aeeb7 BF-320: bump pytest-timeout 90s -> 180s for CI runner slowness
  c21f19d3 BF-321: add missing getServerPiperVoices mock to 16 vitest files
  34278346 BF-322: bump CI job timeouts + drop -x for xdist resilience
  0b507670 BF-323: bump TestShellNLInput class timeout 60s -> 180s
```

```
grep -E "^AD-7[4-9]" docs/development/roadmap.md | sort | tail -3
  AD-747-6 — forward marker
  AD-747-7 — forward marker
  AD-742a / AD-742a-1 — Wave 174 SHIPPED rows (note: 742 < 747; 748 is the next free)
```

Highest AD in roadmap: **AD-747** (with -7 sub). AD-748 assigned.
