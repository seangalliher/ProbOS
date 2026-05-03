# Wave 9A — AD-641 Children Review & Build (Architect + Builder Subagent Dispatch)

**Date:** 2026-05-02
**Mode:** Architect subagent first (review), then Builder subagent (build).
**Wave kind:** Standard main wave (12 stages per main wave; orchestrator-driven).
**Inputs:** 3 sub-AD prompts already drafted in Wave 8.5 (`prompts/ad-641{a,b,f}-*.md`).
**Outputs:**
- 3 review files at `prompts/Reviews/ad-641{a,b,f}-*-review.md`
- 1 sweep summary at `prompts/Reviews/README-wave-9A.md`
- Revisions applied to the 3 prompts
- 3 source commits (one per sub-AD) on Builder pass
- Tracker updates per prompt
**Estimated time:** ~3-4 hours total subagent compute (review + revision + review-2 + build).

---

## Wave 9A scope

| Sub-AD | Title | Risk | Builder order |
|---|---|---|---|
| AD-641a | Observability Bridge | medium | 1st (sets `runtime.observability_bridge` foundation) |
| AD-641b | Ward Room Hebbian | medium | 2nd (consumes `runtime.observability_bridge` from 641a) |
| AD-641f | Engineering Chief Observability | medium | 3rd (independent observability surface) |

**Key cross-prompt dependency:** AD-641b reads `runtime.observability_bridge` introduced by AD-641a. Builder must land 641a before 641b.

---

## Stage 1 — Architect: Review Pass 1

Dispatch this to the Architect subagent (`runSubagent agentName='Architect'`):

```
Wave 9A Review Pass 1 — verify-first review of 3 sub-AD prompts.

Read first:
1. prompts/review-criteria.md — 3-tier format (Required / Recommended / Nits / Verified)
2. DECISIONS.md "Wave 5 Retrospective" + "Wave 5-7 Retrospective Addendum" + "Wave 8 Retrospective Addendum" — 19 standing conventions
3. prompts/WAVE-8.5-SPLIT-SUMMARY.md — Wave 8.5 split rationale; AD-641a-f scope decisions
4. The 3 sub-AD prompts:
   - prompts/ad-641a-observability-bridge.md
   - prompts/ad-641b-ward-room-hebbian.md
   - prompts/ad-641f-engineering-chief-observability.md
5. .claude/agents/architect.md — standing rules

Verify-first against the live codebase at d:/ProbOS for every concrete claim. Output one review file per prompt at prompts/Reviews/<stem>-review.md (use the prompt's stem) plus a sweep summary at prompts/Reviews/README-wave-9A.md.

Apply the 3-tier format per review-criteria.md. Audit each prompt against all 19 standing conventions. Tolerance per convention #15 (relaxed): 1 ⚠️ allowed on the highest-risk prompt only.

Five high-priority verification points:

1. **Cross-prompt dependency: AD-641b consumes runtime.observability_bridge from AD-641a.**
   - Confirm AD-641a's prompt INTRODUCES `runtime.observability_bridge` as a public attribute (per Wave 5 convention #1: no leading underscore).
   - Confirm AD-641b's prompt READS `runtime.observability_bridge` and does NOT also try to introduce it.
   - Confirm Builder order in the dispatch is 641a → 641b (not parallel within a single Builder commit).

2. **Standard verify-first per prompt.** Each prompt's "Verified Against Codebase" footer must have grep evidence for every concrete API/file/line/method claim. If a claim isn't grep-confirmed, that's a Required finding.

3. **Section 0 EventTypes do not collide with events.py or with each other.** Run grep against src/probos/events.py (or wherever EventType enum lives) for each new EventType in each prompt's Section 0. Also grep across the 3 prompts for EventType collisions.

4. **Aggressive pre-deferral applied (convention #14).** Each prompt should ship 2-4 v1 capabilities with explicit grandchildren (641X-i, 641X-ii, etc.) listed in the deferred section. If a prompt absorbs >5 capabilities into v1, flag as a no-theater risk.

5. **Wave 8 conventions #17-19 applied.**
   - #17: any per-instance mutable state lives in __init__, not class scope
   - #18: httpx.Response mocks (if any test uses httpx) cover both .json() and .headers
   - #19: session-managed JSON-RPC clients capture session-id from headers, not body

Output format per review file (matches Wave 8 reviews):

```markdown
# Review: AD-641X — <title>

**Reviewer:** Architect
**Date:** 2026-05-02
**Verdict:** ✅ Approved / ⚠️ Conditional / ❌ Not Ready

## Required (must fix before building)
1. ...

## Recommended
R1. ...

## Nits
- ...

## Verified Against Codebase (2026-05-02)
[grep evidence]

## Disposition
[1-paragraph summary]
```

Sweep summary (prompts/Reviews/README-wave-9A.md):

| # | Prompt | Verdict | Required | Recommended |
| ... |

Plus a "Top failure modes" section if any pattern emerges.

Hard-stops:

1. Phantom API in a prompt body that the prompt does NOT itself introduce — surface immediately.
2. Cross-prompt source-file conflicts the dispatch didn't identify — surface to dispatching architect.
3. Section 0 EventType collisions across Wave 9A prompts — surface, propose alternatives.
4. AD-641b assumes runtime.observability_bridge exists today (i.e., not introduced by AD-641a) — surface; the dependency direction may be inverted.

After all 3 reviews + sweep summary are written:

- Single commit: `Wave 9A review pass 1: 3 prompts reviewed, N findings (M Required)`
- Push to origin/main.

Begin with AD-641f (smallest blast radius, no cross-prompt deps). Proceed: 641f → 641a → 641b.
```

When the subagent reports complete:
```pwsh
./scripts/wave-orchestrator.ps1 advance
```

---

## Stage 2 — Architect: Revision Pass

Dispatch this to the Architect subagent:

```
Wave 9A Revision Pass — apply review findings to all 3 prompts.

You drafted these prompts in Wave 8.5. Now apply the Wave 9A review findings.

Read first:
1. The 3 review files in prompts/Reviews/ (the pass-1 reviews you just produced).
2. prompts/Reviews/README-wave-9A.md — sweep summary.
3. DECISIONS.md "Wave 8 Retrospective Addendum" — closing self-check step (after applying revisions, grep the prompt for the OLD names/values that were changed; expect zero hits).

Goal: every Required finding addressed, Recommended findings folded in unless they expand scope, Nits judgment-called.

Per-prompt revision pattern (same as Wave 5/6/7/8):

1. Read the prompt + its review file.
2. Apply every Required finding directly to the prompt body.
3. Apply Recommended findings unless they expand scope or contradict another prompt.
4. Apply Nits at your judgment.
5. Append a `## Revision (2026-05-02)` section listing what changed and which review findings it addresses.
6. Update the `## Verified Against Codebase` footer with new grep evidence the revision generated.

Closing self-check (per Wave 8 retrospective convention #12 + addendum):

After applying revisions, for each prompt:
- Grep for the OLD names/values that were changed in this revision. Expect zero hits.
- Re-read the Solution Overview / Dependencies header / v1-deliverables bullets at the top of the prompt and confirm consistency with the Revision section.

Phantom-API pre-check (mandatory per convention #16):

After all revisions are applied, run:
```pwsh
./scripts/phantom-api-precheck.ps1 prompts/ad-641a-observability-bridge.md prompts/ad-641b-ward-room-hebbian.md prompts/ad-641f-engineering-chief-observability.md
```

The expected one-flag false positive is `runtime.observability_bridge` in 641b (legitimate cross-prompt dep). Any other phantoms must be fixed before commit.

Single commit covering all 3: `Wave 9A revision: apply review findings to AD-641{a,b,f}`. Pre-commit deletion sanity check before commit. Push to origin/main.

Hard-stops:

- Any Required finding that cannot be addressed without expanding scope or making an architectural decision the architect (you) shouldn't make alone — surface to the dispatching architect.
- The cross-prompt dependency (641a→641b on observability_bridge) needs structural changes (e.g., 641b reframes to introduce it instead) — surface for architectural review.
- The phantom-API pre-check finds >2 phantoms beyond the expected 641b cross-dep — verify-first drift is worse than review caught.

Begin.
```

When the subagent reports complete:
```pwsh
./scripts/wave-orchestrator.ps1 advance
```

---

## Stage 3 — Architect: Review Pass 2

Same shape as Stage 1 but appends `## Second-Pass Review (2026-05-02)` to each existing review file (do not overwrite pass-1 content). Sweep summary at `prompts/Reviews/README-wave-9A-pass-2.md`.

Dispatch this to the Architect subagent:

```
Wave 9A Second-Pass Review — confirm revisions move all 3 prompts to ✅ Approved (with 1 ⚠️ tolerance on highest-risk).

Read first:
1. The 3 revised prompts at prompts/ad-641{a,b,f}-*.md. Each now has a `## Revision (2026-05-02)` section appended.
2. The 3 first-pass review files in prompts/Reviews/.
3. prompts/Reviews/README-wave-9A.md — first-pass sweep summary.

Format (append to existing review files; do not overwrite pass-1):

```markdown
## Second-Pass Review (2026-05-02)

**Verdict:** ✅ Approved / ⚠️ Conditional / ❌ Not Ready

### Resolution Audit
| Pass-1 Required | Status | Evidence in revised prompt |
| ... | ✅ Resolved / ⚠️ Partial / ❌ Not addressed | Section N reference + grep confirmation |

### New Findings (introduced during revision)
1. ... (or "None")
```

Per-prompt verification:

1. Every Required finding from pass-1 has explicit evidence of resolution in the revised prompt.
2. The closing self-check ran: grep the prompt for OLD names/values changed; expect zero hits.
3. Phantom-API pre-check ran post-revision: only the expected 641b cross-dep flagged.
4. Solution Overview / Dependencies / v1-deliverables headers are consistent with Revision section.

Verdict criteria (per convention #15 relaxed tolerance):

- ✅ Approved: all Required resolved, no new phantom APIs, no regressions.
- ⚠️ Conditional: Required resolved but new minor issues introduced. Acceptable on the highest-risk prompt only (641b — has the cross-prompt dep).
- ❌ Not Ready: at least one Required not actually addressed, OR a new Required-class issue was introduced.

Sweep summary at prompts/Reviews/README-wave-9A-pass-2.md with:
- Per-prompt verdicts table
- Total Required-still-open count (target: 0)
- Total new findings count (target: 0)
- Recommended Builder order (should be 641a → 641b → 641f per cross-dep)

Hard-stops:

1. If 2+ prompts fail second-pass with new Required findings, surface to dispatching architect.
2. If AD-641a doesn't actually introduce runtime.observability_bridge as expected, surface — Builder will hit a phantom on 641b.
3. If the cross-prompt dep is still ambiguous, surface for re-bundling (could become Combo-style commit).

Single commit: `Wave 9A second-pass review: 3 prompts re-evaluated against revisions`. Push.

Begin with 641f → 641a → 641b. Convergence target: 3 ✅ + 0 ⚠️ (cross-prompt dep is well-understood; tolerance reservation likely unused).
```

When the subagent reports complete:
```pwsh
./scripts/wave-orchestrator.ps1 advance
```

---

## Stage 4 — GATE 1 (Architect approval to dispatch Builder)

Inspect `prompts/Reviews/README-wave-9A-pass-2.md`. Apply convention #15 verdict criteria. If approved:

```pwsh
./scripts/wave-orchestrator.ps1 advance
```

If rejected (third revision needed):

```pwsh
./scripts/wave-orchestrator.ps1 reset 9A
```

---

## Stage 5 — Builder: Continuous Build

Dispatch this to the Builder subagent (`runSubagent agentName='Builder'`):

```
Build Wave 9A — 3 prompts (AD-641a/b/f), continuous-build mode.

Read first:
1. prompts/BUILDER-EXECUTION-PLAN.md — standing rules
2. .github/copilot-instructions.md — engineering principles + § Repository Boundary
3. DECISIONS.md "Wave 5/5-7/8 retrospective" entries — 19 standing conventions
4. prompts/Reviews/README-wave-9A-pass-2.md — second-pass summary
5. The 3 build prompts (in this build order):
   - prompts/ad-641a-observability-bridge.md  (1st — introduces runtime.observability_bridge)
   - prompts/ad-641b-ward-room-hebbian.md     (2nd — consumes runtime.observability_bridge)
   - prompts/ad-641f-engineering-chief-observability.md (3rd — independent)

Mode: Continuous build. One prompt = one commit. No inter-prompt pause unless a hard-stop triggers.

Pre-flight:

```pwsh
git pull
git status --short                                                # must be clean
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile  # green baseline; record count
```

Expected baseline: ~10565 passed, 15 skipped (post-Wave-8 + BF-257 state).

Build order (strict):

1. **AD-641a** — Observability Bridge. INTRODUCES `runtime.observability_bridge` as public attribute. Must land before 641b.
2. **AD-641b** — Ward Room Hebbian. CONSUMES `runtime.observability_bridge` from 641a (which is now landed). Verify by grep at build time.
3. **AD-641f** — Engineering Chief Observability. Independent of 641a/b but uses similar patterns; safe to build last.

Per-prompt workflow:

1. Read the prompt + its review file. Each review's Second-Pass Review section flags non-blocking nits to apply at code-review time.
2. Verify-first per the prompt's "Verified Against Codebase" footer.
3. Implement section by section per the 19 standing conventions.
4. Run focused gate at -n 0. All must pass.
5. Update trackers per the prompt's Tracking section.
6. Write build report at prompts/build-reports/<stem>-build.md.
7. Commit: `AD-641X: <one-line summary>`.

Per-commit gate:

- pytest tests/ -q -n 8 --dist=loadfile exits 0 (real failures only — environmental flakes acceptable per standing rule)
- Test count non-decreasing
- Pre-commit deletion sanity check: git diff --cached --stat — STOP if any file shows >200 deletions
- Commit message format as above

Wave 9A specific reminders (false positives — don't re-flag):

- **AD-641a creates runtime.observability_bridge.** Wire as public attribute (no underscore) per convention #1.
- **AD-641b reads runtime.observability_bridge.** It does NOT introduce it; if you find it doesn't exist, AD-641a was incomplete — STOP and surface.
- **Section 0 EventTypes** — each prompt's Section 0 lists new event names. Add them to events.py (or wherever the EventType enum lives) without collision.
- **All three sub-ADs ship 3-4 v1 capabilities each.** Each has a deferred-grandchildren section (641X-i, 641X-ii, etc.). Don't try to build the deferred ones.

Hard-stops (per BUILDER-EXECUTION-PLAN):

1. Phantom API not introduced by the prompt itself
2. Architectural change required beyond stated scope
3. Persistent serial test failure on a file you didn't change
4. Existing test assertions break in ways "What This Does NOT Change" didn't anticipate
5. >5 sweep-introduced quarantines accumulate
6. **AD-641b finds runtime.observability_bridge missing after AD-641a's commit landed** — order violation; STOP and surface.

Inter-group full gate after all 3 land: pytest tests/ -q -n 8 --dist=loadfile. Test count delta should be ~+30-50 (3 prompts × 10-16 tests each).

When all 3 commits land + full gate passes, report back with commit hashes, test count delta, any deferred nits.

Begin with AD-641a.
```

When the subagent reports complete:
```pwsh
./scripts/wave-orchestrator.ps1 advance
```

---

## Stage 6 — verify_build (run full gate)

```pwsh
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile
```

Expected: 0 failures. Test count delta ~+30-50 from baseline.

```pwsh
./scripts/wave-orchestrator.ps1 advance
```

---

## Stage 7 — GATE 2 (architect approval to push)

```pwsh
git log --oneline origin/main..HEAD
git diff origin/main..HEAD --stat
```

Inspect for unintended drift, commit message format, no large deletions. If approved:

```pwsh
./scripts/wave-orchestrator.ps1 advance
```

---

## Stage 8 — push

```pwsh
git push
./scripts/wave-orchestrator.ps1 advance
```

---

## Stage 9 — GATE 3 + close (issues to close)

Wave 9A doesn't close any GitHub issues directly (AD-641 umbrella #277 closes when Wave 9C lands per the plan).

Confirm no issues to close, then advance through `close` and `retrospective` stages.

---

## Stage 10 — Retrospective (optional)

Heuristic: write a Wave 9A retrospective entry in DECISIONS.md only if:

- Pass-1 Required count is materially different from Wave 8 (19) — either much lower (conventions stabilized) or much higher (new failure mode)
- The cross-prompt dep pattern (641a→641b) reveals a new convention worth banking
- The phantom-API pre-check tuning (Wave 8.5 close) needs further refinement

Otherwise skip — three retrospective entries already cover the recurring patterns.

---

## Hard-Stops (whole-wave)

Stop and surface to the dispatching architect (NOT the user) if:

1. Builder hits a hard-stop on AD-641a — Wave 9A blocks; AD-641b cannot proceed without 641a.
2. The cross-prompt dep (641a→641b on observability_bridge) reveals scope incompatibility at build time — may need structural fix.
3. Phantom-API pre-check post-revision finds >2 phantoms beyond the expected 641b cross-dep.
4. Test count drops more than expected (small drops from quarantine acceptable; large drops indicate regressions).

---

## Acceptance Criteria

- 3 review files written (pass-1 + pass-2 sections each).
- README-wave-9A.md and README-wave-9A-pass-2.md sweep summaries written.
- 3 source commits landed (one per AD, in order: 641a → 641b → 641f).
- Full gate green; test count delta ~+30-50.
- All 19 standing conventions applied consistently.
- Phantom-API pre-check post-revision: only the expected 641b cross-dep flagged.
- Single push covering review + revision + build commits, OR multiple pushes per wave-orchestrator stages — both acceptable.
- AD-641 umbrella issue (#277) NOT closed (waits for Wave 9C).
