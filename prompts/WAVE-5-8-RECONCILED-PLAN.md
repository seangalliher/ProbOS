# Wave 5-8 Build Plan — Reconciled

**Date:** 2026-04-30
**Author:** Architect
**Source documents:**
- [`AD-BACKLOG-AUDIT.md`](AD-BACKLOG-AUDIT.md) — corpus-level classification of all 90 genuinely-open ADs
- [`wave-5-8-ad-selection-plan.md`](wave-5-8-ad-selection-plan.md) — pre-audit selection of 20 buildable ADs

This document reconciles the two and is the canonical input to the next wave's BUILDER-EXECUTION-PLAN.

---

## Reconciliation Summary

| Source | Status |
|---|---|
| Wave-5-8 plan total | 20 ADs |
| Of which audit confirms buildable now | 17 |
| Of which audit flags as needing pre-flight action | 3 |
| Audit-flagged buildable ADs NOT in wave-5-8 plan | 8+ (combo candidates) |

The wave-5-8 plan was drafted before the audit and is still mostly correct. The audit caught three issues that need handling before any of those 20 ADs can build. After those land, the 20-AD selection plus the audit's combo recommendations form the next 4-6 weeks of work.

---

## Pre-Wave Hygiene Required (BLOCKERS)

These must be resolved before drafting the next wave's prompts. They are tracker drift and one numbering collision that would corrupt downstream work.

| Item | Action | Effort |
|---|---|---|
| **AD-460 status** | **RESOLVED 2026-04-30:** marked partial in roadmap; DECISIONS.md entry recorded the "reasoning replay does not save tokens; procedural learning (AD-464) is the actual path" decision. Wave 6 fifth slot swapped to AD-491. No further hygiene action needed. | Done |
| **AD-654 numbering collision** | **RESOLVED 2026-04-30:** issue #313 (Ship State Snapshot) renumbered to AD-683; #322 (UAAA) keeps AD-654. Roadmap header (line 7082) updated. GitHub issue title + body updated to reflect AD-683 with renumber rationale. | Done |
| **AD-557b/c (#11) empty body** | **RESOLVED 2026-04-30:** closed as won't-fix-now. Both sub-items are speculative deferrals; AD-557 parent preserves the history. If HXI dashboard or higher-order PID become urgent, file a fresh AD with current scope. | Done |
| **`src/probos/security/` doesn't exist** | AD-455 must own `__init__.py` creation (mirroring AD-676's `governance/` precedent). Annotation in the wave-5-8 plan. | 5 min plan note |
| **47 stale GitHub issues** | Trackers correctly mark these CLOSED but issue tracker is stuck open. Not blocking but worth a batch-close. | 15 min via `gh CLI` |

> **Audit false positive resolved:** the audit flagged a stale `cognitive_services.py` path reference in `.github/copilot-instructions.md`. Verified — that file does NOT contain any `cognitive_services` reference. The audit subagent overstated this finding; no doc fix needed.

**Total hygiene effort:** ~2 hours, single Builder commit.

A combined hygiene prompt is queued at [`prompts/hygiene-wave5-prereq.md`](hygiene-wave5-prereq.md) (drafted alongside this document).

---

## Reconciled 20-AD Wave Selection

### Wave 5: Independent Foundation (5 ADs, fully parallel)

| # | AD | Title | Audit Group | Audit Risk | Status |
|---|---|---|---|---|---|
| 1 | AD-439 | Emergent Leadership Detection | 3 | medium | ✅ Buildable |
| 2 | AD-440 | Chain of Command Delegation | 3 | high | ✅ Buildable. Audit flags trust/safety risk; full review pass before approval. |
| 3 | AD-443 | Agent Mobility Protocol | 4 | high | ⚠️ Audit puts in Group 4 (sequenced); wave-5-8 plan puts in Wave 5. Architect decision: build in Wave 5 only if AD-479 (Federation Hardening) is NOT a hard prerequisite. Audit suggests it is. **Defer to Wave 8 or block on AD-479.** |
| 4 | AD-455 | Security Team — Threat Detection & Trust Integrity | 2 | high | ✅ Buildable. Owns `security/__init__.py`. |
| 5 | AD-468 | Runtime Configuration Service | 3 | medium | ✅ Buildable |

**Reconciliation:** drop AD-443 from Wave 5 (audit dependency on AD-479 makes it unsafe in Wave 5). Replace with **AD-499 (Ship & Crew Naming Conventions)** — audit Group 1A, trivial, all deps closed (AD-441/441b/442). Keeps the wave size at 5.

**Updated Wave 5:** AD-439, AD-440, AD-455, AD-468, **AD-499**.

### Wave 6: Core Infrastructure (5 ADs, mostly parallel)

| # | AD | Title | Audit Group | Audit Risk | Status |
|---|---|---|---|---|---|
| 6 | AD-451 | Validation Framework Hardening | 2 | high | ✅ Buildable |
| 7 | AD-457 | Engineering Crew | 3 | medium | ✅ Buildable |
| 8 | AD-458 | Navigational Deflector — Pre-Flight | 3 | medium | ✅ Buildable |
| 9 | AD-459 | Saucer Separation — Graceful Degradation | 2 | high | ✅ Buildable. Cross-cutting; serialize within wave. |
| 10 | AD-491 | Infodynamic Reporting | 3 | low | ✅ Buildable. Replaces AD-460 (resolved partial-complete on 2026-04-30; see DECISIONS.md). |

**Reconciliation:** AD-460 was resolved on 2026-04-30 — marked partial-complete (token ledger landed, replay-UI scope closed, AD-464 designated as the actual token-savings path). Wave 6 fifth slot is **AD-491 (Infodynamic Reporting)** — audit Group 3, low risk, pure observability, no deps.

**Updated Wave 6:** AD-451, AD-457, AD-458, AD-459, AD-491.

### Wave 7: Infrastructure & Integration (5 ADs, dependency-ordered)

| # | AD | Title | Audit Group | Audit Risk | Status |
|---|---|---|---|---|---|
| 11 | AD-456 | Security Infrastructure | 2 | high | ✅ Buildable, depends on AD-455. |
| 12 | AD-463 | Model Diversity & Neural Routing | 4 | high | ⚠️ Audit verify-first: `ModelRegistry` symbol does NOT exist. Foundation work; legitimately HIGH risk. Architect approval gate before drafting. |
| 13 | AD-466 | Engineering Infrastructure | 3 | medium | ✅ Buildable |
| 14 | AD-467 | Operations Crew | 3 | medium | ✅ Buildable |
| 15 | AD-641 | Ship's Computer / Crew Integration | 4 | high | ⚠️ Audit marks as Northstar umbrella. **Split into 6 sub-ADs (641a–641f)** before scheduling; do NOT build as a single prompt. |

**Reconciliation:** drop AD-641 umbrella from Wave 7. Replace with **AD-528 (Ground-Truth Verification — Anti-Fabrication)** — audit Group 2, high-value safety feature, no deps. Schedule the AD-641 sub-ADs as a separate Wave 9 once split.

**Updated Wave 7:** AD-456, AD-463, AD-466, AD-467, **AD-528**.

### Wave 8: Chain Completions + Combo (5 ADs + Combo A)

| # | AD | Title | Audit Group | Audit Risk | Status |
|---|---|---|---|---|---|
| 16 | AD-469 | EPS — Compute/Token Distribution | 4 | high | ✅ Buildable; depends on AD-460/467. |
| 17 | AD-449 | MCP Bridge | 4 | high | ✅ Buildable. Commercial — keep marker in PROGRESS. |
| 18 | AD-472 | Channel Adapters | 3 | medium | ✅ Buildable |
| 19 | AD-484 | User Experience & Adoption Readiness | 3 | medium | ✅ Buildable. Mostly repo-level. |
| 20 | AD-475 | Captain's Ready Room | 3 | medium | ✅ Buildable |

**Add Combo A** (audit-recommended trivial-batch sweep) parallel-track with Wave 8:
- AD-538b, AD-572b, AD-573b, AD-575b, AD-576b, AD-526c, AD-655, AD-656

Combo A runs as ONE single-Builder commit covering 8 trivial extensions to already-closed parent ADs. Estimated ~1 day. Doesn't add to Wave 8's 20-prompt count; it's bonus throughput from the audit.

---

## Other Audit Combos (queued for Waves 9-10)

The audit identified three more combo candidates not in the wave-5-8 plan:

- **Combo B — Workforce Cleanup** (AD-500, AD-501, AD-499): if AD-499 is pulled into Wave 5 per the reconciliation above, drop it from Combo B; remaining Combo B is just AD-500 + AD-501.
- **Combo C — Behavioral Metrics Pack** (AD-569a, AD-557b): blocked on AD-557b clarification.
- **Combo D — UI Companion Sweep** (AD-473, AD-474, AD-574b): UI-heavy; can run independently from any code-side wave.

These can fill in between waves or provide low-risk warm-up work for new Builder sessions.

---

## Updated Build Order (canonical)

```
HYGIENE PRE-WAVE (1 commit, ~2h):
  AD-460 status check / flip
  AD-654 collision resolution
  AD-557b body fill OR drop
  copilot-instructions.md path fix
  47 stale GitHub issue closures

WAVE 5 (5 prompts, parallel-safe):
  AD-439, AD-440, AD-455, AD-468, AD-499

WAVE 6 (5 prompts, mostly parallel):
  AD-451, AD-457, AD-458, AD-459, [AD-460 OR AD-491]

WAVE 7 (5 prompts, sequenced on AD-460):
  AD-456 ← AD-455
  AD-463 (gate: ModelRegistry foundation review)
  AD-466
  AD-467
  AD-528

WAVE 8 (5 prompts, dependency-ordered) + COMBO A in parallel:
  AD-469 ← AD-460/467
  AD-449
  AD-472
  AD-484
  AD-475
  -- parallel: COMBO A (8 trivial extensions)
```

---

## Estimated Throughput

Calibrated against wave 1-4 actuals (19 prompts in ~24h, with 4 architect interventions):

| Wave | Prompts | Sequential est | Fleet est (3-way) | Notes |
|---|---|---|---|---|
| Hygiene | 1 | 2h | 2h (single Builder) | Blocking; do first |
| Wave 5 | 5 | ~5h | ~2h | Fully parallel |
| Wave 6 | 5 | ~6h | ~2.5h | Mostly parallel, AD-459 serialized |
| Wave 7 | 5 | ~8h | ~5h | Sequenced on AD-460/AD-455 |
| Wave 8 + Combo A | 5 + 1 combo | ~8h | ~4h | Wave 8 dependency-ordered, Combo A parallel |
| **Total** | **21 + Combo A** | **~29h** | **~16h** |

This is for the next wave only. The remaining ~70 ADs (audit's "buildable but not in wave-5-8 selection") are a 3-month cadence at this pace.

---

## Open Decisions for Architect

1. **AD-443 deferral** — confirm AD-479 is a hard prerequisite, or can AD-443 build standalone? (Audit says hard; wave-5-8 plan says deps-met. Verify by reading AD-443 body.)
2. **AD-641 split** — schedule the 6 sub-AD split as a meta-prompt before Wave 9, or absorb into Wave 9 prompts directly?

**Resolved:**
- AD-460 status (partial-complete; replay deferred; AD-464 takes the token-savings mantle; Wave 6 slot replaced with AD-491). See DECISIONS.md.
- AD-654 collision (#313 renumbered to AD-683; #322 keeps AD-654).
- AD-557b/c (#11 closed as won't-fix-now).

Architect should answer the remaining 2 before the hygiene commit lands.

---

## Notes for Future Audits

- Run an audit before every wave selection. The wave-5-8 plan caught most things, but audit found 3 blockers and 8 missed combo opportunities.
- The 47 stale issues finding suggests issue-tracker hygiene needs a cron job or a CI hook. AD candidate: "AD-684: Tracker Sync Automation."
- The "umbrella AD" pattern (AD-462, AD-633, AD-641) keeps appearing. Establish a rule: umbrella ADs must be split into sub-AD prompts before scheduling, never built directly.
