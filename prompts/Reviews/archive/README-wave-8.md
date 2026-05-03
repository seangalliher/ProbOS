# Wave 8 Review Pass — Sweep Summary

**Date:** 2026-05-02

**Reviewer:** Architect (verify-first 3-pass mode)

**Tolerance mode:** Relaxed (convention #15) — 1 ⚠️ on highest-risk prompt acceptable.

---

## Per-Prompt Verdicts

| Order | Prompt | Verdict | Required | Recommended | Status |
|---|---|---|---|---|---|
| 1 | `combo-A-trivial-extensions` | ⚠️ Conditional | 7 | 6 | Revise — phantom APIs in 3 of 8 children + DRY conflict in AD-526c |
| 2 | `ad-484-user-experience-adoption` | ⚠️ Conditional | 2 | 6 | Revise — provider-detection bug + license-classifier conflict |
| 3 | `ad-472-channel-adapters` | ⚠️ Conditional | 3 | 6 | Revise — config class duplication + em-dash SEARCH miss |
| 4 | `ad-475-captains-ready-room` | ✅ Approved | 0 | 7 | Ship — Recommendeds are tightening only |
| 5 | `ad-469-eps-compute-token-distribution` | ❌ Not Ready | 4 | 6 | Revise — phantom `tokens_grouped_by` API; would not run on first invocation |
| 6 | `ad-449-mcp-bridge` | ⚠️ Conditional | 3 | 6 | Revise — commercial-connector names in shipping content + class-attribute mutable default |

**Aggregate:** 19 Required findings, 37 Recommended findings across 6 prompts. 1 ✅, 4 ⚠️, 1 ❌.

---

## Tolerance Assessment

Per convention #15: **1 ⚠️ on highest-risk prompt acceptable; anything else surfaces back.**

Wave 8 first-pass result: **4 ⚠️ + 1 ❌ — outside tolerance.** Surface back for revision.

**Pattern recognition (vs Wave 5/6/7 retrospective):**

- Wave 5 first pass: 22 Required findings, 5 ⚠️ (within batch tolerance); converged in 2 passes.
- Wave 6 first pass: 18 Required findings, 5 ⚠️ → converged in 2 passes.
- Wave 7 first pass: 11 Required findings, 5 verdicts split (3 ⚠️ / 2 ❌) → required 3 passes.
- **Wave 8 first pass: 19 Required findings, 4 ⚠️ + 1 ❌.**

The Required-finding count crept up vs Wave 7 (11 → 19). Hypothesis: AD-575b and AD-573b drove a chunk via phantom interfaces that weren't grep-checked at draft time; AD-469's `tokens_grouped_by` was a single hallucinated method name in the dispatching architect's draft. Both are convention #6 (verify-first) drift caught at review.

---

## Required-Finding Categories

| Category | Count | Examples |
|---|---|---|
| **Phantom API / phantom attribute** | 7 | AD-573b `working_memory_manager`; AD-575b `self_summary_provider`; AD-655 `EvaluateSubTask`; AD-469 `tokens_grouped_by`, dict-key `"calls"` |
| **Verify-first line-number drift** | 2 | AD-573b line 78 (real: 22); AD-469 footer hallucinates line 300 |
| **No-theater violation** | 2 | AD-575b ships zero real work in v1 source; (Combo A wholesale assessment) |
| **DRY / duplicate name** | 2 | AD-526c `register_game` duplicates `register_engine`; AD-472 `SlackConfig` defined twice |
| **SEARCH/REPLACE mismatch** | 1 | AD-472 em-dash vs ASCII hyphen in Discord block |
| **Pydantic typing** | 1 | AD-472 `slack: "SlackConfig" = None` not Optional |
| **Class-attribute mutable default** | 1 | AD-449 `_last_response_headers` |
| **Commercial-boundary leak** | 1 | AD-449 lines 8 + 40 (specific connector names in shipping content) |
| **Logic bug** | 1 | AD-484 `__class__.__name__` substring check |
| **License-classifier conflict** | 1 | AD-484 SPDX vs PEP-639 |

---

## Build-Readiness Order (Recommended)

**After revisions land:**

1. **AD-475** — already ✅; lowest risk; can be built first as a warmup.
2. **AD-484** — UX/repo-level; no runtime impact; 2 mechanical fixes.
3. **AD-472** — channel adapters; 3 mechanical fixes; depends on AD-449/AD-469 events anchor.
4. **Combo A** — 8 trivial extensions; 7 mechanical fixes; AD-575b should be wholesale-deferred (drop to 7 children).
5. **AD-469** — EPS foundation; 4 mechanical fixes; phantom-API correction is the hard one.
6. **AD-449** — MCP Bridge; 3 mechanical fixes; HIGH risk + commercial-boundary; build last.

---

## Refinement Lessons (carry to Wave 9)

1. **The dispatch's "scripted pre-check" for phantom APIs (Wave 5-7 retro #6) wasn't run.** Three of seven phantom-API issues would have been caught by greping each `runtime.X.Y` triplet against live source before the architect drafted. Future dispatches should script this and run before subagent invocation. **20-min architect investment, would have caught Wave 8's 7 phantom hits.**

2. **AD-575b's "extension of closed parent" assumption needs grep-verification.** AD-575 (closed) was assumed to ship `runtime.self_summary_provider`. It didn't. Future combos must grep the parent's actual public surface BEFORE drafting child-AD extensions. Combo A would have lost AD-575b at draft time, dropping to 7 children — cleaner Wave 8 state.

3. **AD-526c "register_game" vs existing "register_engine" is the canonical DRY trap for combo prompts.** The combo pattern's 50-75 lines per child doesn't leave room for thorough API-surface comparison. Future combo prompts should include a 1-line "checked against existing X.method_list" verification per child.

4. **Em-dash vs ASCII-hyphen in SEARCH blocks (AD-472 #2)** is exactly convention #9's territory but for a different reason — convention #9 says "ASCII for new comments" but the SEARCH block is matching pre-existing source where em-dashes were the original choice. Drafters need to read the live source character-by-character, not transcribe loosely.

5. **AD-469's `tokens_grouped_by` phantom is the single largest correctness regression in Wave 8.** The dispatch named the method in its AD-specific guidance ("verify the journal's existing schema supports per-agent token cost aggregation"); the architect drafter chose a method name that's similar-but-wrong. Pattern: when a dispatch hints at "verify X works", grep for the exact method name X resolves to before naming it.

---

## Convention Drift Summary

Standing rules from DECISIONS.md "Wave 5 Retrospective" + "Wave 5-7 Retrospective Addendum" — drift status across Wave 8:

| # | Rule | Drift Count | Notes |
|---|---|---|---|
| 1 | Public-attribute wiring | 1 | AD-573b phantom name |
| 2 | stdlib-only | 0 | ✅ |
| 3 | Coordinator-then-dispatch | 0 | ✅ all 6 prompts |
| 4 | Superset-filter | 0 | ✅ |
| 5 | init_<phase> | 0 | ✅ |
| 6 | **Verify-first** | **5** | Largest drift category — phantom APIs |
| 7 | **No-theater** | **2** | AD-575b wholesale; AD-469 `check_budgets` borderline |
| 8 | TYPE_CHECKING + ALLOWED_EXCEPTIONS | 0 | N/A this wave |
| 9 | ASCII-only comments | 1 | AD-472 SEARCH-block edge case (matching pre-existing source) |
| 10 | work_item_store vs workforce | 0 | N/A this wave |
| 11 | __new__-bypass defensive-getattr | 0 | ✅ all defensive reads applied |
| 12 | Solution Overview drift | 1 | AD-484 number mismatch |
| 13 | Pool template name collision | 0 | N/A this wave |
| 14 | Aggressive pre-deferral | 0 | ✅ all 6 prompts pre-defer |
| 15 | Tolerance: relaxed | n/a | review-tier setting |

**#6 (verify-first) drift dominates Wave 8.** Five of 19 Required findings are phantom-API or line-number issues that grep would have caught at draft time. This is the convention with the highest enforcement leverage; future dispatches should script the grep checks.

---

## Next Steps

1. **Surface back to dispatching architect.** Wave 8 first-pass tolerance violated (4 ⚠️ + 1 ❌). Revision pass needed.
2. **Revision-pass dispatch should include:** (a) phantom-API grep pre-check script; (b) AD-575b wholesale-deferral decision; (c) AD-526c register-game DRY resolution; (d) explicit em-dash ASCII discipline for SEARCH blocks against live source.
3. **Expected convergence:** under relaxed tolerance and with the phantom-API fixes (mostly mechanical), second-pass review should converge to 5 ✅ + 1 ⚠️ on AD-449 (HIGH-risk slot reservation).

**Build-queue gate:** none of these prompts should be dispatched to Builder until revision-pass review passes.
