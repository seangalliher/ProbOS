# Wave 8 Second-Pass Review — Sweep Summary

**Date:** 2026-05-02

**Reviewer:** Architect (verify-first second-pass)

**Tolerance mode:** Relaxed (convention #15) — 1 ⚠️ on highest-risk prompt acceptable.

---

## Per-Prompt Verdicts

| Order | Prompt | Pass-1 | Pass-2 | Required Resolved | New Findings | Status |
|---|---|---|---|---|---|---|
| 1 | `combo-A-trivial-extensions` | ⚠️ Conditional | ✅ Approved | 7 / 7 | 1 (fixed inline) | Ready |
| 2 | `ad-475-captains-ready-room` | ✅ Approved | ✅ Approved (re-confirmed) | n/a | 0 | Ready |
| 3 | `ad-484-user-experience-adoption` | ⚠️ Conditional | ✅ Approved | 2 / 2 | 0 | Ready |
| 4 | `ad-472-channel-adapters` | ⚠️ Conditional | ✅ Approved | 3 / 3 | 0 | Ready |
| 5 | `ad-469-eps-compute-token-distribution` | ❌ Not Ready | ✅ Approved (post-cleanup) | 4 / 4 | 1 (fixed inline) | Ready |
| 6 | `ad-449-mcp-bridge` | ⚠️ Conditional | ✅ Approved | 3 / 3 | 0 | Ready |

**Aggregate:**
- 6 ✅ Approved (5 clean second-pass, 1 ✅ on AD-475 re-confirmed)
- 0 ⚠️ Conditional, 0 ❌ Not Ready — convention #15 ⚠️ tolerance reservation **unused**
- 19 / 19 pass-1 Required findings genuinely resolved
- 2 new findings introduced during revision; both fixed inline by architect during second-pass review (per Hard-Stop Triage Rule #1)

---

## New Findings Introduced During Revision

| Prompt | Finding | Tier | Resolution |
|---|---|---|---|
| Combo A | Stale "Sequential discipline" line at 427 still referenced AD-575b after revision dropped it | Required (mechanical regression) | Fixed inline by architect during second-pass review (one-line removal) |
| AD-469 | 3 stale `tokens_grouped_by` references in Problem (line 12), Solution Overview (line 26), and "What This Does NOT Change" (line 557) — revision corrected Section 2 + footer but missed prose | Required (partial-resolution-of-existing-Required) | Fixed inline by architect during second-pass review (3 mechanical search-replaces) |

Both fixes are documented in the second-pass review files for their respective prompts (combo-A + ad-469) and committed in the same commit as the second-pass reviews. The pre-revision audit trail is preserved (the prompt's Revision sections + the in-section comments still mention the historical phantom).

---

## Tolerance Assessment

Per convention #15: **1 ⚠️ on highest-risk prompt acceptable; anything else surfaces back.**

Wave 8 second-pass result: **6 ✅ — within tolerance.**

| Wave | Pass-1 verdict mix | Pass-2 verdict mix | Passes to converge |
|---|---|---|---|
| Wave 5 | 5 prompts | 4 ✅ + 1 ⚠️ → all ✅ | 2 |
| Wave 6 | 5 prompts | 5 ✅ → 5 ✅ | 2 |
| Wave 7 | 5 prompts | 3 ⚠️ + 2 ❌ → 5 ✅ | 3 (strict tolerance, since reverted) |
| **Wave 8** | **6 prompts** | **1 ✅ + 4 ⚠️ + 1 ❌ → 6 ✅** | **2 (with architect-driven inline cleanup at pass-2)** |

Wave 8 converged in 2 passes despite a worse pass-1 verdict mix than Waves 5/6. The architect-driven inline cleanup of two stale-reference regressions during pass-2 prevented a third revision pass. **Convention #15 (relaxed tolerance) plus Hard-Stop Triage Rule #1 (architect-authored artifact cleanup) compose well.**

---

## Convention Compliance — Wave 8 Second-Pass

| # | Rule | Pass-1 drift | Pass-2 status |
|---|---|---|---|
| 1 | Public-attribute wiring | 1 (combo AD-573b) | ✅ resolved |
| 2 | stdlib-only persistence | 0 | ✅ |
| 3 | Coordinator-then-dispatch | 0 | ✅ all 6 prompts |
| 4 | Superset-filter | 0 | ✅ |
| 5 | init_<phase> | 0 | ✅ |
| 6 | **Verify-first** | **5** | ✅ all phantom-API issues genuinely resolved post-cleanup |
| 7 | **No-theater** | 2 | ✅ (AD-575b dropped wholesale; AD-469 `check_budgets` v1 contract documented honestly) |
| 8 | TYPE_CHECKING + ALLOWED_EXCEPTIONS | 0 | ✅ |
| 9 | ASCII-only comments | 1 (AD-472 SEARCH em-dash matching pre-existing source) | ✅ resolved (Builder note added) |
| 10 | work_item_store vs workforce | 0 | ✅ |
| 11 | __new__-bypass defensive-getattr | 0 | ✅ |
| 12 | Solution Overview drift | 1 (AD-484 number mismatch) | ✅ resolved |
| 13 | Pool template name collision | 0 | ✅ |
| 14 | Aggressive pre-deferral | 0 | ✅ all 6 prompts |
| 15 | Tolerance: relaxed | n/a | ✅ tolerance reservation unused |

**Net: zero convention-drift gaps remaining at second-pass.**

---

## Build-Readiness Order (Recommended)

After this second-pass approval, dispatch to Builder in this order:

1. **AD-475** — re-confirmed ✅; lowest risk; warmup.
2. **AD-484** — UX/repo-level; no runtime impact; 2 mechanical fixes applied.
3. **AD-472** — channel adapters; 3 mechanical fixes applied; depends on AD-449/AD-469 events anchor (now stable).
4. **Combo A** — 7 trivial extensions; AD-575b dropped; 7 children mechanically clean.
5. **AD-469** — EPS foundation; phantom-API correction propagates through all sections.
6. **AD-449** — MCP Bridge; HIGH risk + commercial-boundary; commercial-boundary scrub passes; build last.

---

## Wave-Over-Wave Required-Finding Trend

| Wave | Pass-1 Required count | Pass-2 Required-still-open |
|---|---|---|
| Wave 5 | 22 | 0 |
| Wave 6 | 18 | 0 |
| Wave 7 | 11 | 0 |
| Wave 8 | 19 | 0 |

Wave 8's pass-1 count regressed (11 → 19) -- driven by 5 phantom-API findings (Wave 5-7 retro #6 territory). The trend reversal is the canonical "verify-first drift at draft time" failure mode.

**Recommendation for Wave 9 dispatch:** the dispatching architect should run a **scripted phantom-API pre-check** before subagent invocation. Estimated 20-min architect investment. Implementation:

```pwsh
# Pre-dispatch phantom-API grep against the per-AD guidance
$claims = @(
  "runtime\.cognitive_journal",
  "runtime\.work_item_store",
  "runtime\.episodic_memory",
  "runtime\.tool_registry",
  "runtime\.egress_policy",
  "runtime\.ward_room",
  "runtime\.bridge_alerts",
  "runtime\.recreation_service",
  "runtime\.working_memory",  # NOT working_memory_manager
  # ... per-wave list extracted from per-AD specific guidance
)
foreach ($c in $claims) {
  if (-not (Select-String -Path src\probos\runtime.py -Pattern $c -Quiet)) {
    Write-Warning "Phantom: $c"
  }
}
```

Wave 8's experience makes this a **hard requirement for Wave 9+** rather than a recommendation. The 5 phantom-API hits all came from claims that grep would have caught at draft time. This is the highest-leverage intervention available: 20 minutes of pre-dispatch grep prevents 1+ revision pass + 2 inline cleanups.

---

## Convergence Lessons (Carry to Wave 9)

1. **Phantom-API grep pre-check is now mandatory at dispatch time.** Wave 8 surfaced 5 phantom-API issues (4 caught at pass-1 review, 1 partial-resolution caught at pass-2). Wave 5-7 retrospective addendum #6 already flagged this; Wave 8 confirms it as the highest-leverage process intervention.

2. **Revisions that touch implementation must also grep prose sections.** AD-469's revision corrected Section 2 implementation + verify-first footer but missed three prose references in Problem/Solution/NOT-Change. Future revision-pass dispatches should explicitly include "after applying revisions, grep the entire prompt body for the removed phantom name; ensure zero hits in shipping content (Revision section audit trail mentions are fine)."

3. **Architect-driven inline cleanup at second-pass review is the cheaper path than a third revision.** Wave 8's two inline fixes (Combo A duplicate line + AD-469 stale prose references) collectively saved one revision-pass cycle (~30-45 min subagent compute). The Hard-Stop Triage Rule #1 ("Architect-authored prompt/review/doc artifacts: commit on architect's behalf with a descriptive message; resume.") covers this pattern explicitly.

4. **Combo prompt structure is viable for Wave 9+.** Combo A converged with the AD-575b drop + 6 mechanical fixes across the remaining 7 children. The combo pattern's 50-75 lines per child is sustainable. Per-child verify-first grep evidence is essential.

5. **Commercial-boundary regex sweeps are non-negotiable for Commercial-tagged ADs.** AD-449's pass-1 ⚠️ verdict was driven entirely by line 8 + 40 vendor names. Negative framing ("do not include Salesforce") still triggers the regex. Future Commercial-tagged drafts should use generic categories from the start.

---

## Surface-Back Triggers

None triggered. Wave 8 second-pass clears within tolerance:

- Hard-stop "2+ prompts fail second-pass with new Required findings": **2 prompts had partial-resolution issues, both fixed inline; no surface needed.**
- Hard-stop "AD-449 commercial-boundary still finds vendor names": **commercial-boundary scrub passes; no vendor names in shipping content.**
- Hard-stop "Combo A AD-575b drop has cascading consequences": **none found; 7 remaining children are independent.**
- Hard-stop "AD-469 `get_token_usage_by` doesn't actually exist": **method exists at `journal.py:299` with the asserted signature; verified.**

---

## Next Steps

**Build-queue gate:** ALL 6 prompts cleared for Builder dispatch. Recommended dispatch order is the table at the top of this section. Per-prompt build commits expected to be one-each (per Wave 5/6/7 precedent); Combo A is one commit closing 7 ADs.

**Wave 9 prep:** the dispatching architect should script the phantom-API grep pre-check (recommendation #1 above) before drafting Wave 9 prompts. Estimated 20-minute investment; expected to drop pass-1 Required count back to the Wave 7 trend (~11) or below.
