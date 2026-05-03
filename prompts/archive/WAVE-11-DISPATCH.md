# Wave 11 — Tooling Hygiene: Phantom-API Pre-Check Kwarg Validation

**Date:** 2026-05-03
**Mode:** Architect first (review), then Builder (build).
**Inputs:** 1 single-AD prompt drafted directly (`prompts/ad-685-phantom-precheck-kwarg-validation.md`).
**Outputs:** 1 review file + sweep summary + revisions + 1 source commit.
**Estimated time:** ~1.5 hours total subagent compute.

---

## Wave 11 scope

| AD | Title | Risk |
|---|---|---|
| AD-685 | Phantom-API Pre-Check Method-Kwarg Shape Validation | low (tooling-only) |

Architect's recommendation across Wave 9 and Wave 10 retrospectives: extend `scripts/phantom-api-precheck.ps1` to validate method kwargs against live AST signatures. Three documented recurrences of the kwarg-phantom pattern; one scripted convention beats N drafting-time conventions.

**Closes GH issues:** None directly. Hygiene/tooling AD; benefit is reduced future-wave revision cost.

---

## Stage 1 — Architect: Review Pass 1

Dispatch to Architect subagent:

```
Wave 11 Review Pass 1 — verify-first review of AD-685 (tooling hygiene; low-risk single-prompt wave).

Read first:
1. prompts/review-criteria.md
2. DECISIONS.md "Wave 5/5-7/8/9 retrospective" entries — 23 standing conventions
3. prompts/WAVE-11-DISPATCH.md (Stage 1 = your task)
4. prompts/ad-685-phantom-precheck-kwarg-validation.md
5. scripts/phantom-api-precheck.ps1 (the existing pre-check that AD-685 extends)
6. .claude/agents/architect.md

Output one review file at prompts/Reviews/ad-685-phantom-precheck-kwarg-validation-review.md plus a sweep summary at prompts/Reviews/README-wave-11.md.

Apply the 3-tier format. Audit against all 23 standing conventions. Tolerance per convention #15 (relaxed): 1 ⚠️ allowed if architectural concern surfaces; expected verdict is ✅.

Five high-priority verification points:

1. **Recursive validity.** AD-685's own prompt MUST itself pass the existing pre-check. Run:
   ./scripts/phantom-api-precheck.ps1 prompts/ad-685-phantom-precheck-kwarg-validation.md
   Expected: clean. If the AD-685 prompt itself contains phantoms, that's a Required finding (and an embarrassing self-reference).

2. **Performance estimate.** AD-685 claims <5s per prompt for AST walk + match. Verify by counting `find src/probos -name "*.py" | wc -l` and estimating walk time. If >100 Python files, may need an index cache (mentioned in Hard-Stops).

3. **Heuristic completeness.** AD-685's heuristics list:
   - Skip non-Python fenced code blocks (pwsh, bash, etc.)
   - Skip backticked prose call expressions
   - Skip `## Revision` audit-trail sections
   - Accept kwarg if any overloaded signature matches

   Verify each heuristic addresses a real false-positive class observed in Waves 8/9/10. If a heuristic isn't motivated by observed patterns, flag as scope creep.

4. **Test plan completeness.** 8 tests cover happy path + 5 specific regression cases (Wave 9B query phantom, Wave 10 get_pending phantom, fenced-code skip, revision skip, overload acceptance) + 2 integration tests (PowerShell wrapper + exit code). Confirm each test maps to a real failure case.

5. **Aggressive pre-deferral applied (convention #14).** AD-685 ships 1 of 3 capabilities (kwarg validation only); AD-685b (field-name validation) and AD-685c (type-shape validation) deferred. Confirm the v1 boundary is honest — no field-name validation accidentally smuggled in.

Hard-stops:
1. Phantom API in the prompt body itself (recursive validity check).
2. AD-685's AST helper would conflict with existing PowerShell pre-check semantics in non-additive way (e.g., changes exit codes for symbol-only phantoms).
3. Heuristics list has gaps — known false-positive class from Waves 8/9/10 not addressed.
4. Performance estimate clearly wrong (e.g., >30s per prompt at current `src/probos/` size).

After review + sweep summary:
- Single commit: `Wave 11 review pass 1: AD-685 reviewed, N findings (M Required)`
- Push to origin/main.

Return:
- Verdict
- Total Required, Recommended, Nits counts
- Recursive validity: does AD-685's own prompt pass the current pre-check?
- Performance estimate validation
- Heuristic completeness assessment
- Top failure modes if any
- Commit hash
```

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 2 — Architect: Revision Pass

Standard revision pattern. Apply Required, fold Recommended, judgment-call Nits. Append `## Revision (2026-05-03)` section.

Closing self-check + phantom-API pre-check (mandatory).

Single commit: `Wave 11 revision: apply review findings to AD-685`. Push.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 3 — Architect: Review Pass 2

Append `## Second-Pass Review (2026-05-03)`. Sweep at `prompts/Reviews/README-wave-11-pass-2.md`. Convergence target: 1 ✅.

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stage 4 — GATE 1 (Architect approval)

Inspect sweep summary. Approve via convention #15 verdict criteria.

`./scripts/wave-orchestrator.ps1 advance` (approve) or `reset 11` (reject).

---

## Stage 5 — Builder: Continuous Build (single commit)

Dispatch to Builder:

```
Build Wave 11 — AD-685 Phantom-API Pre-Check Kwarg Validation (single-prompt wave; tooling hygiene).

Read first:
1. prompts/BUILDER-EXECUTION-PLAN.md
2. .github/copilot-instructions.md
3. DECISIONS.md (Wave 5/5-7/8/9 retrospective entries — 23 standing conventions)
4. prompts/Reviews/README-wave-11-pass-2.md
5. prompts/ad-685-phantom-precheck-kwarg-validation.md
6. scripts/phantom-api-precheck.ps1 (the file AD-685 extends)

Pre-flight:
git pull
git status --short
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile

Expected baseline: ~10635 passed, 15 skipped (post-Wave-10 state).

Single commit: AD-685 ships in one commit.

Sections to implement (per prompt):
1. `scripts/phantom_api_ast_helper.py` — Python AST helper. Heuristics per prompt's Section 1.
2. PowerShell wrapper integration — additive only; preserve exit semantics.
3. Calibration sweep — run extended pre-check against archived Wave 8/9/10 prompts; document true/false positive rates in commit message or build report.

Per-prompt: read prompt + review, verify-first, implement, focused gate at -n 0, update trackers, build report, commit `AD-685: <one-line>`.

Per-commit gate: full pytest passes, test count non-decreasing, deletion sanity check.

Wave 11 specific reminders:
- v1 ships kwarg validation ONLY. Do NOT implement field-name validation (AD-685b) or type-shape validation (AD-685c).
- Recursive validity: the AD-685 prompt itself must pass the extended pre-check (regression guard).
- Performance target: <5s per prompt. If exceeded, surface; consider caching the AST index across calls.
- Calibration must sweep prompts/archive/ad-641c-*.md (Wave 9B query phantom) and prompts/archive/ad-500-*.md (Wave 10 get_pending phantom) — both should be flagged.

Hard-stops (per BUILDER-EXECUTION-PLAN):
1. Phantom API
2. Architectural change beyond scope
3. Persistent serial test failure on unchanged file
4. Existing test breaks unanticipated by "What This Does NOT Change"
5. >5 sweep-introduced quarantines
6. Performance >30s per prompt — surface; need caching or sub-tree filtering
7. False-positive rate >5 per prompt on calibration sweep — surface; architect must tune heuristics

Test target: ~8 new tests at tests/test_phantom_api_precheck_kwargs.py.

Tracker updates:
- PROGRESS.md: prepend AD-685 entry
- DECISIONS.md: full entry under Era V (verbatim from prompt's Tracking section)
- docs/development/roadmap.md: add AD-685 entry under tooling/hygiene section

Return:
- Commit hash
- Test count + delta
- Lines +/-
- Full gate status
- Hard-stops triggered (target: 0)
- Calibration sweep results (true positives caught, false positives, performance)
- Any deferred nits not folded into commit

Begin.
```

When subagent reports: `./scripts/wave-orchestrator.ps1 advance`

---

## Stages 6-13 — verify_build → GATE 2 → push → GATE 3 → close → retrospective → done

Standard close-out. **GATE 3:** no GH issues to close (tooling/hygiene). Skip close action.

Retrospective: optional. Heuristic — write only if calibration sweep reveals new failure modes worth banking, or the heuristics needed material tuning during Builder pass.

---

## Acceptance Criteria

- 1 review file (pass-1 + pass-2 sections)
- README-wave-11.md and README-wave-11-pass-2.md
- 1 source commit (AD-685)
- Full gate green; +8 tests
- 0 hard-stops
- Calibration sweep documented (true/false positive rates on archived prompts)
- DECISIONS.md entry for AD-685 under Era V
- Pre-check still passes on AD-685 prompt itself (recursive validity)
