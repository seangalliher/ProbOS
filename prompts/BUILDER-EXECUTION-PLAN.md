# Builder Execution Plan — Wave 1-4 (2026-04-29)

**Date:** 2026-04-29
**Author:** Architect
**Mode:** Continuous build (one prompt = one commit, no inter-prompt pause)
**Active prompts:** 19 buildable + 1 sequenced hold (AD-678 on AD-677)
**Estimated tests added:** ~150–200 across the wave

This plan supersedes `prompts/archive/BUILDER-EXECUTION-PLAN-bf247-bf246-ad680.md` (completed sweep).

## Current Performance Addendum (2026-07-24)

This addendum supersedes any conflicting test cadence below.

- **Plan and freeze first:** Architect completes verify-first review for the dependency group, records approved prompt hashes, and freezes prompt text before Builder dispatch.
- **Code with focused evidence:** after each logical coding slice, run only the exact changed tests and a small adjacent caller/importer gate. Do not run the full repository suite while the wave is still changing.
- **Review before broad testing:** once coding is complete, stop edits and run Architect/code-review validation across ownership, dependency direction, hostile wire types, duplicate events, restart idempotency, and worktree scope. Repair findings before spending the broad-gate budget.
- **One consolidated broad gate:** after review repairs land and source/tests/prompts are frozen, run full Python once with `-n 16 --dist=loadfile` on the Captain's 16-physical-core host. Run full Vitest + production build for UI changes and the required Playwright scenarios for user-facing workflows. A later shared-code or test change invalidates the relevant broad evidence.
- **Clean-checkout CI is distinct evidence:** local config, caches, skip-worktree files, and generated assets cannot be test oracles. Required remote CI checks must be green before closing the issue/epic.
- **Preserve unrelated work:** use explicit-path or partial-hunk staging, inspect `git diff --cached`, and never use `git add -A` in a dirty worktree.

---

## Inputs

Read these in full **before** writing any code:

1. `.github/copilot-instructions.md` — engineering principles, testing standards, logging standards, type-annotation rules. Every commit must comply.
2. `prompts/Reviews/README-wave-1-4-fourth-pass.md` — final wave verdicts and the false-positive resolution. **Do not re-flag the items listed there as buildable; their fixes are inside the prompts.**
3. The 20 wave 1-4 prompt files at `prompts/ad-*.md`.
4. The corresponding per-prompt review files at `prompts/Reviews/ad-*-review.md` — each has a "Re-review" section with non-blocking nits to apply at code-review time.

---

## Standing Rules (carry forward from prior sweep)

- **Working tree:** if you encounter tracked-file modifications you didn't make, surface them. Do NOT `git stash` / `git reset --hard`. If they are clearly architect-authored prompt/review/doc artifacts, commit them on the architect's behalf with a descriptive message and continue.
- **Test gate:** the **consolidated wave-close gate** uses `pytest tests/ -q -n 16 --dist=loadfile` (16 workers — the stable ceiling matching the Captain host's physical cores; `-n auto` maps to 32 logical processors and oversubscribes SQLite/Chroma). The **focused per-prompt gate** uses the exact changed nodes/files, with `-n 0` for deterministic diagnosis. Do not run the full gate per prompt. CI uses `-n auto` to match the hosted runner's assigned cores.
- **Wave-close gate failure interpretation:** failures under the consolidated parallel gate that do NOT reproduce under `-n 0` are environmental (heavy concurrent fixture boots) and accepted — document them and continue. The only blockers are real failures that reproduce serially in files you changed.
- **Triage step on full-gate red:** rerun the failing files at `-n 0`. If they pass, mark environmental, continue. If they fail, stop.
- **Quarantine threshold:** if you hit a pre-existing serial failure unrelated to your changes, file a BF, quarantine, and continue. Surface only if more than 3 quarantines accumulate during a single sweep.
- **Gate/build log location (2026-06-27):** write pytest / vitest / build gate captures to `logs/` (e.g. `logs/adNNN_gate.txt`, `logs/adNNN_vitest.txt`), **not** the repo root. `logs/` is gitignored except `.gitkeep`; the root `/*_gate.txt` etc. patterns in `.gitignore` remain a back-compat safety net. Keeps the repo root clean — the prior root-dump convention accumulated ~110 stray captures.
- **Pre-build SEARCH/REPLACE:** every prompt is its own delta. Do not assume `events.py`, `governance/`, or any file matches what the prompt asserts will exist *after* its SEARCH/REPLACE. The prompt IS the migration.
- **License policy (Captain rule, 2026-05-09):** ProbOS OSS is Apache 2.0 and free; **never absorb anything in the OSS repo that requires a paid license.** Users only bring their own LLM models. Strong preference: MIT. Acceptable: Apache 2.0 / BSD / CC0 / MPL-2.0 / CC-BY-4.0 (case-by-case for code/models). Avoid: AGPL / GPL (copyleft propagates into Apache 2.0 — even at subprocess level, prefer permissive alternatives). When the upstream is license-ambiguous, AGPL-tainted, or paid: **absorb the PATTERN, write our own code.** Cite upstream as research inspiration; don't import the code. Mixed-license repos: check every component (e.g. OmniParser repo is CC-BY-4.0 but `icon_detect` weights are AGPL — architecture only). Files with embedded licensing (VRM, GLB, etc.) never ship in OSS even if the file format is fine — operators bring files locally; gitignore the directory. Commercial-overlay (private repo): paid-license deps allowed but operator-facing — bring-your-own-license or pass-through pricing; default still pattern-absorption. **Architect must surface a license disposition for every external-absorption prompt before drafting deliverables.** Reviewer pass-1 must include a license-check tier; Builder must verify before adding any new dependency to `pyproject.toml` / `package.json`.
- **UI gate (BF-279, 2026-05-13):** any wave touching `ui/src/**` (or any file matched by `git diff --name-only origin/main..HEAD -- ui/src/`) runs changed Vitest files during coding, then MUST run BOTH full UI verification steps once after completed-build review and before push:
  1. `cd ui; npx vitest run` — logic correctness for the UI changes.
  2. `cd ui; npm run build` — TypeScript strict + Vite production bundle health.
  Vitest skips `tsc -b` strict checks. A test suite can be 100% green while `vite build` errors. BF-279 (commit `2d685bc5`) is the canonical case study: Wave 156's `MicPermissionHint.tsx` introduced `JSX.Element` (unresolved under React 19 + bundler-mode tsconfig), `vite build` errored, `ui/dist/` stayed frozen for ~32 hours, and three waves' user-visible work never reached the operator's browser despite all Vitest tests passing.
- **Refs-trailer for orphan sub-ADs (AD-738e-2 / #653, Wave 159).** When a wave includes a sub-AD spawned from a parent BF that has no GH issue (e.g., AD-738e-1 born out of BF-285 commentary), the commit message has no `Closes #N` trailer. To preserve audit-trail traceability, the commit MUST include EITHER:
  - A `Refs #N-of-parent-BF` trailer when the parent BF has a GH issue, OR
  - A `See DECISIONS.md AD-NNN` reference in the commit body when the parent BF is internal-only.

  Builder applies this rule automatically when drafting commit messages for sub-AD work — no architect approval at GATE 2 required when the trailer is present. Lineage: AD-738e-1 (`bb1ca160`) shipped with the DECISIONS reference in the body; this codifies that as the standard.
- **AD-722c-3 — Architect forward markers use TECHNICAL triggers, not business-language triggers.** Forward markers that describe when extension points might activate MUST use technical / capability-based phrasing. Examples: ❌ "premium deployment requires queryable backend" → ✅ "queryable-backend deployment requires SQL replacement". ❌ "paid extension can swap JSONL for SQL" → ✅ "deployments needing queryable analytics can swap JSONL for SQL via the Protocol." Boundary rule (AD-450 / Wave 154 retrospective): OSS repo describes WHAT extension points exist, not HOW they are monetized. The pre-commit boundary hook will fire on common business-oriented terms.

---

## Pre-flight Checklist

```pwsh
git status --short                                         # must be empty (or only untracked runtime artifacts)
d:/ProbOS/.venv/Scripts/pytest.exe <focused baseline files> -q -n 0  # changed-slice baseline
```

Record the focused baseline. Do not spend a full-suite run before coding unless the incoming baseline is already suspect or the Architect explicitly requires it to distinguish pre-existing failures.

## Wave-close pre-flight gate

Run this gate once after completed-build review at every wave close where the accumulated wave touches:

- `package.json` or `ui/package-lock.json`
- `pyproject.toml`
- any file in the AD-748 heavily-mocked list (`ui/src/audio/voice.ts`, `ui/src/audio/wakeWord.ts`, `ui/src/audio/speechInput.ts`, `ui/src/store/useStore.ts`, `ui/src/api.ts`)
- commits that add more than 20 tests

Command:

```pwsh
pwsh scripts/wave-close-precheck.ps1
```

Failure semantics:

- `FAIL` (script exit `1`): stop, fix the reported issue, and rerun until clean.
 - `WARN` with no `FAIL` (script exit `0`): wave may proceed; record the cleanup as a forward marker. Outside burn-down mode that is a BF for next-wave cleanup; in burn-down mode it is a checklist item on the wave's single follow-up issue.
- Do not bypass Check 1 (lock-file sync) or Check 5 (vitest exit-code gate).
- Check 3 (runtime budget) may be skipped temporarily via `WAVE_CLOSE_FAST=1` during iteration, but must run before push.

---

## Build Order and Dependency DAG

The wave sequences into 4 build groups. Each prompt produces exactly one commit. Prompts within a group can run in any order; prompts in later groups must wait for earlier groups to land.

### Group 1 — Independent foundations (8 prompts, parallel-safe within the group)

These have no in-wave dependencies. Build in any order.

1. **AD-447** — Phase Gates for PoolGroup
2. **AD-489** — Federation Code of Conduct
3. **AD-490** — Agent Wiring Security Logs
4. **AD-461** — Ship's Telemetry
5. **AD-465** — Containerized Deployment
6. **AD-566i** — Role Skill Template Expansion
7. **AD-566f** — Qualification → Skill Bridge
8. **AD-679** — Selective Disclosure Routing

### Group 2 — Governance substrate (3 prompts, sequenced)

`src/probos/governance/` does not yet exist. **AD-676 owns directory creation.**

1. **AD-676** — Action Risk Tiers — creates `src/probos/governance/__init__.py` (empty) before adding `governance/risk_tiers.py`. Verify the directory does not pre-exist; if AD-445 raced ahead, skip the `__init__.py` step.
2. **AD-445** — Decision Queue & Pause/Resume — references existing `governance/`.
3. **AD-446** — Compensation & Recovery Pattern — depends on AD-445's DecisionQueue wiring.

### Group 3 — Tool + Counselor + Routing (4 prompts, parallel-safe within the group)

1. **AD-438** — Ontology-Based Task Routing
2. **AD-448** — Wrapped Tool Executor
3. **AD-470** — IntentBus Enhancements
4. **AD-561** — Intervention Classification

### Group 4 — Northstar substrate + memory (5 prompts, sequenced where noted)

1. **AD-674** — Graduated Initiative Scale (must land first; introduces `InitiativeLevel` and `resolve_initiative_level()`)
2. **AD-675** — Uncertainty-Calibrated Initiative (depends on AD-674)
3. **AD-677** — Context Provenance Metadata
4. **AD-678** — Memory Transparency Mechanism (depends on AD-677's `ProvenanceTag`/`ProvenanceEnvelope`)
5. **AD-524** — Ship's Archive (independent within group)

---

## Per-Prompt Workflow

For each prompt, repeat:

1. **Read the prompt + its review file.** The review's Re-review section calls out small inline cleanups (e.g., redundant `import time` in AD-561, `hasattr(assessment, 'trigger')` removal). Apply those at the same time as the main edits.
2. **Verify-first.** Before editing, grep the live codebase for the prompt's named anchors (class names, method signatures, line ranges). Confirm SEARCH blocks match. If a SEARCH block doesn't match the live code, STOP and surface — do not improvise.
3. **Implement section by section** in the order the prompt specifies. Some prompts (notably AD-674, AD-470) have inter-section dependencies (the Section 2 enum/import must land before Section 3 code references it).
4. **Run the prompt's own tests** in serial: `pytest tests/test_<adNNN>_*.py -v -n 0`. All must pass before continuing.
5. **Run the focused gate** for nearby files (the prompt's adjacent test areas) in serial.
6. **Update trackers** as the prompt's Tracking section specifies (PROGRESS.md, roadmap.md, DECISIONS.md where called out).
7. **Write a build report** at `prompts/build-reports/<ad-NNN>-build.md` matching the format in `prompts/build-reports/archive/`.
8. **Commit** with format: `AD-NNN: <one-line summary>`.

After a Group completes, run Architect/code-review validation. Continue coding after focused repairs; reserve the full gate for the code-complete wave unless a group changes a shared contract needed to make later work trustworthy.

---

## Per-Commit Quality Gates

Every commit must pass:

- Its prompt-specific and adjacent focused tests exit 0.
- New/changed test counts match the prompt's acceptance criteria.
- No new files outside what the prompt specifies (especially: no test scaffolding committed under `data/` or `tools/`).
- No `print()` calls added (use `logger`).
- All new public methods have type annotations.
- All new log messages have context (what failed + what next).
- New `EventType` enum values are present in `events.py` exactly where the prompt's SEARCH/REPLACE places them — not duplicated, not in a different position.
- `git status` shows only the files the prompt's "Files Changed" anticipates (modulo PROGRESS.md / roadmap.md / DECISIONS.md updates).

### Pre-commit deletion sanity check (HARD RULE)

After `git add` and **before** every `git commit`:

```pwsh
git diff --cached --stat
```

Inspect the deletion column. If any single file shows **more than 200 deletions** that the prompt did not anticipate, **STOP**:

1. Do NOT commit.
2. Run `git diff --cached <file>` to see the actual deletion.
3. If the deletion is unintended (a file was truncated, an editor save-while-empty wiped content, a fixture cleared a tracker), restore via `git checkout HEAD -- <file>` and re-apply your intended edits.
4. Surface to architect if the deletion is intentional but unusual (>1000 lines).

This rule exists because of the AD-682 commit incident: `docs/development/roadmap.md` was silently emptied to 0 bytes during the build session and a blind `git add -A` staged the empty file. The commit had to be force-amended to restore the 7401-line file. **Always verify the diff stat before committing.**

The threshold (200 lines) is deliberately low — most legitimate deletions in this codebase are smaller. ProbOS's tracker files (`PROGRESS.md`, `roadmap.md`, `DECISIONS.md`) are append-mostly; large deletions there are almost always wrong.

---

## Hard-Stop Conditions

Stop and surface to the architect immediately if any of these occur:

1. **Phantom API in implementation** — a method/attribute the prompt references doesn't exist AND isn't introduced by the prompt itself. Do not invent it.
2. **Architectural change required** — work cannot proceed without modifying `BaseAgent`, `IntentMessage`, `RuntimeProtocol`, or any public protocol contract beyond what the prompt specifies.
3. **Test gate persistently red** on a file you didn't change, reproducible under `-n 0`. Re-run once at `-n 0`; if it still fails serially, stop.
4. **Working tree contains tracked-file modifications you didn't make and can't identify as architect artifacts.** Do not destroy.
5. **Existing test assertions need changes the prompt's "What This Does NOT Change" section didn't anticipate.** Spec gap — stop.
6. **More than 3 pre-existing test quarantines accumulate during the sweep.** That's a baseline hygiene issue; surface for triage.

---

## Wave-Specific Reminders

- **AD-465** uses `@model_validator(mode="after")`. That is valid Pydantic v2 — do NOT change it to `@field_validator` despite an early review note. Confirmed correct.
- **AD-524** Section 3 adds the `archive_store` parameter to `OracleService.__init__` itself; the SEARCH/REPLACE will insert the parameter, then wiring code uses it. The "phantom parameter" framing in early reviews was wrong direction.
- **AD-446 / AD-448** include their `EventType` additions in their own Section 2. Do not assume the events are missing — apply the prompt as-is.
- **AD-674 → AD-675:** AD-674 must land before AD-675 imports `InitiativeLevel`. Build order enforces this.
- **AD-677 → AD-678:** same pattern with `ProvenanceTag` / `ProvenanceEnvelope`.
- **`hasattr(runtime, 'emit_event')` guards in non-revised prompts** are dead code post-AD-680. Strip them when you encounter them in this wave's prompts. AD-561 also has a redundant `import time` instruction (already imported at counselor.py:14) — skip.
- **`governance/__init__.py`:** create only if it doesn't already exist. AD-676 owns this; AD-445 has fallback instructions.

---

## Build Reports

After each commit, write `prompts/build-reports/ad-NNN-build.md` with:

- Title, prompt path, builder identity, date, status
- Files Changed
- Sections Implemented (one bullet per `###` section in the prompt)
- Post-Build Section Audit
- Test results (commands run, pass/fail counts)
- Any deviations from the prompt and why

Match the existing format in `prompts/build-reports/archive/`.

---

## Post-Sweep

After the 19 prompts are committed:

1. Freeze prompt/source/test inputs after Architect review, then run the full gate once: `pytest tests/ -q -n 16 --dist=loadfile`. If any file fails under parallel, read the short summary and rerun the actual failing node with `-n 0`; do not mistake secondary aiosqlite `Event loop is closed` annotations for the root failure.
2. Confirm the test count grew by the documented total.
3. Move all 19 completed prompts to `prompts/archive/` (matches prior sweep convention).
4. Move per-prompt review files to `prompts/Reviews/archive/`.
5. Surface a final summary message: commit hashes, final test count vs baseline, any deferred nits, and confirmation that AD-678 remains on hold pending AD-677 (now buildable in this wave but tracked as the lone sequenced item).
6. **Forward-marker filing (HARD RULE, added 2026-05-08 after Wave 132; bounded 2026-08-24).** Before push, scan every shipped prompt's "Forward markers" / "Out of scope" / "Defer to AD-NNNx" lines and the corresponding build report's deferred section. **Deferred work must still be recorded** — forward markers in prompts alone are not sufficient tracking. Recurring lesson: Wave 132 had 6 unfiled deferrals (AD-706a..f); Captain backfilled them as #516-#521 the same day. Don't repeat.

   **A forward marker does NOT automatically become one GitHub issue.** Outside burn-down mode, file each with priority + verify-first anchor citations + cross-references to the parent AD, and add a row to the roadmap's deferred-AD table. **In Backlog Burn-Down Mode** (see `.github/copilot-instructions.md`), non-blocking forward markers are consolidated into **one wave follow-up issue**, each retained as its own checklist item with severity, evidence, reproduction detail and code anchors so it stays independently actionable. Separate issues stay reserved for security, data integrity, independently reachable production failures, and blockers. The roadmap row is still added either way.
7. Push: `git push`.

---

## Reference: Standing Lessons (carry forward)

- One prompt = one commit. No batched commits.
- Continuous-build mode works for batches up to ~20.
- xdist on the Captain's Windows host uses `-n 16 --dist=loadfile` for the single wave-close full gate. `-n auto` is forbidden locally because it maps to 32 logical processors and destabilizes SQLite/Chroma; CI uses `-n auto` to match its smaller assigned core count. Use `-n 0` for focused diagnosis. If `-n 16` regresses, fall back to `-n 8` or `-n 4 --dist=loadfile` and file a BF.
- Review the complete code stack before the full gate. Prompt/source/test changes after the gate invalidate the affected evidence.
- Tests must pass from clean HEAD. Never hard-code a digest from local `config/system.yaml`; snapshot and compare non-mutation instead.
- The "Verified Against Codebase" section in each prompt is binding — trust it for the post-build state.
- Minor architect-authored modifications under `prompts/` are routine; commit on the architect's behalf and continue.
- Do not re-litigate the false-positive items listed in `README-wave-1-4-fourth-pass.md` § "Final Status."
