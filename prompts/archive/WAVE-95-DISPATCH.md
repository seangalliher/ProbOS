# WAVE 95 DISPATCH — AD-652 Cognitive Code-Switching Umbrella Close (no-build)

## Wave summary

**Umbrella AD:** AD-652 (Cognitive Code-Switching: Unified Pipeline with Contextual Modulation — design principle adopted 2026-04-20 at `DECISIONS.md:2253-2280`, indexed at `docs/development/roadmap.md:7105`).

**Wave kind:** Tracker-only reconciliation. **Zero source changes, zero test changes, zero pytest delta.** Structurally identical to W90 (#111 AD-462) and W94 (#37 AD-579) no-build umbrella closes.

**Reframe decision — no reframe needed (no-build close):**

AD-652 is an architectural design principle, not a discrete shippable module. It defines six rules governing how the cognitive chain handles different communication types: (1) Unified Pipeline, (2) Contextual Modulation (Halliday field/tenor/mode), (3) Structured Format Overlays, (4) Variable Chain Depth, (5) Character-Driven Self-Monitoring, (6) Process-Specific Chains. Every one of these six principles is fully realised at HEAD `b02a9a4` across already-shipped child ADs. The umbrella's "Design Principle (adopted)" status was correct on 2026-04-20 (date of adoption) but stale at HEAD after AD-647c, AD-651, AD-651a, and AD-653 shipped during the Meta-Harness Research Wave. There is genuinely nothing to defer because there is nothing to add — Captain rule "don't defer unless no choice" satisfied vacuously.

The realisation evidence is independently confirmed by the AD-658 archive prompt (`prompts/archive/ad-658-chain-harness-metrics-v1.md:11-19`), which explicitly documents:

> *AD-652 ("Cognitive Code-Switching: Unified Pipeline with Contextual Modulation") is a **DESIGN PRINCIPLE adopted in DECISIONS.md:1914**, not a discrete shipped module. It is realised across multiple ADs already in the tree:*
> *- AD-649 (`derive_communication_context` at `cognitive_agent.py:59`; sets `observation["_communication_context"]` at `cognitive_agent.py:2058–2064`) — channel/recipient → register inference.*
> *- AD-639 (chain-trust-band tuning; sets `observation["_trust_score"]` and `observation["_chain_trust_band"]`) — trust-adaptive personality modulation.*
> *- AD-638 (boot camp gate; sets `observation["_boot_camp_active"]`) — relaxed quality threshold for new agents.*
> *- AD-632a/h/f (`SubTaskExecutor` at `sub_task.py:172`) — the chain itself, the substrate AD-652 modulates.*
> *Implication for AD-658 v1: the dependency is satisfied. No changes to AD-649/639/638 wiring are required.*

That note was written on 2026-04-30 (Wave 28). Between then and Wave 95 (HEAD `b02a9a4`, 2026-05-07), additional principles were realised: AD-651 (Standing Order Decomposition / billet overlays), AD-651a (proposal + duty report compose billets), AD-650 (analytical_reasoning narrative field for depth modulation), AD-653 Layer 1 (speak-freely intended_action with trust-gated authorization, character-driven register shifting), AD-647 / AD-647c (process chains framework — variable depth + process-specific composition). The downstream consumer ADs AD-655 / AD-656 / AD-657 / AD-658 / AD-659 v1 / AD-660 all completed and reference AD-652 modulation parameters. The principle is now fully realised; only the trackers lag.

**Realisation map (the six principles → shipped children):**

| Principle | Realised by |
|---|---|
| 1. Unified Pipeline (one chain, identity continuity) | AD-632 — `SubTaskExecutor` at `cognitive/sub_task.py:172` is the unified-pipeline substrate. AD-632a/h/f/e all Complete. |
| 2. Contextual Modulation (Halliday field/tenor/mode) | AD-649 — `derive_communication_context` at `cognitive_agent.py:59`, sets `_communication_context` at `cognitive_agent.py:2223`, 5 registers (private_conversation, bridge_briefing, casual_social, ship_wide, department_discussion). AD-639 — chain trust band at `cognitive_agent.py:2055-2062`, tenor weighting. AD-650 — `analytical_reasoning` narrative field, depth modulation. |
| 3. Structured Format Overlays (billet instructions as cognitive scaffolding) | AD-651 — `StepInstructionRouter` slices composed standing orders by `<!-- category: ... -->` markers. AD-651a — `[PROPOSAL]` block syntax + Findings/Assessment/Recommendation duty report format injected directly into compose. |
| 4. Variable Chain Depth (different step compositions per task) | AD-647 — process chains define their own step types (QUERY/TRANSFORM/STORE/NOTIFY) distinct from communication chain. AD-647c — LLM-template + CALLABLE handlers + NATS dispatch. |
| 5. Character-Driven Self-Monitoring (code-switching range varies by personality) | AD-639 — chain personality tuning via trust band. AD-653 Layer 1 — `speak_freely` intended_action with trust-gated authorization (≥0.7 auto-granted, 0.4-0.7 flagged, <0.4 denied) + Counselor `REGISTER_SHIFT_GRANTED/DENIED` event subscription. |
| 6. Process-Specific Chains (different processes have different step compositions) | AD-647 / AD-647c — process chains framework, scout report (search→classify→store→notify) reference implementation. |

**Concrete v1 sub-AD letters built (zero):** AD-652 has no sub-AD letters because it is a principle, not a module. Wave 95 ships zero new code, zero new tests, zero new GH issues.

**Future sub-AD letters with explicit forcing functions (zero):** No realisation child of AD-652 is incomplete that would force a deferral. The principle is fully realised at HEAD.

**The private commercial-repo path token carve-outs (zero):** AD-652 is purely OSS cognitive-architecture work — Halliday/Levelt/Giles/Snyder/Weick-Sutcliffe research foundation, billet instructions as cognitive scaffolding pattern, trust-gated register shifting. Zero tier-noun phrase / pricing-token regex / SaaS-overlay descriptor surface anywhere.

## AD numbering

Highest stem at HEAD remains **AD-696** (verified 2026-05-07 by `Select-String -Path PROGRESS.md, DECISIONS.md, decisions-era-*.md, docs/development/roadmap.md -Pattern '\bAD-(\d{3})' -AllMatches` returning maximum 696 / 695 / 694 / 693 / 692). Wave 95 mints zero new AD numbers — AD-652 already exists, no sub-AD letters added. Highest BF at HEAD: **BF-596** (verified by same scan returning maximum 596). Wave 95 mints zero new BF numbers.

## Verify-first against HEAD `b02a9a4`

The four trackers Wave 95 reconciles all show the same stale `Design Principle (adopted)` status at HEAD; the realisation evidence is structurally present in the codebase and independently confirmed in roadmap.md and the AD-658 archive prompt:

- **`DECISIONS.md:2253-2280`** — AD-652 entry header: `**Date:** 2026-04-20`, `**Status:** Design Principle (adopted)`, six numbered Design Principles, Motivation paragraph, Key Insight, Research line. Verified by reading lines 2253-2280 directly. Next entry AD-653 starts at line 2282.
- **`docs/development/roadmap.md:7105`** — AD-652 bullet text begins `***AD-652: Cognitive Code-Switching — Unified Pipeline with Contextual Modulation** *(Design Principle, OSS, Issue #302)*` and ends with `*Related: AD-651 (Billet Instructions), AD-639 (Chain Personality Tuning), AD-647 (Process Chains), AD-632 (Chain Architecture).*`. Verified by `Select-String -Path docs/development/roadmap.md -Pattern 'AD-652' -SimpleMatch` returning hit at line 7105.
- **`PROGRESS.md:331`** — Status note begins `AD-652 DESIGN PRINCIPLE (adopted). Cognitive Code-Switching — unified pipeline with contextual modulation.` and ends with `Issue #302.`. Verified by grep returning hit at line 331.
- **`decisions-era-4-evolution.md`** — Zero AD-652 matches. Verified by `grep -c "AD-652" decisions-era-4-evolution.md` returning `0`. Wave 95 must NOT add an `### AD-652` section to era-4. The canonical decision record lives at `DECISIONS.md:2253-2280` only.
- **`prompts/archive/ad-658-chain-harness-metrics-v1.md:11-19`** — Independent confirmation of realisation status: `## AD-652 Status Note` heading at line 11, then `**AD-652** ("Cognitive Code-Switching: Unified Pipeline with Contextual Modulation") is a **DESIGN PRINCIPLE adopted in DECISIONS.md:1914**, not a discrete shipped module. It is realised across multiple ADs already in the tree:` at line 13, followed by AD-649 / AD-639 / AD-638 / AD-632a/h/f bullet list with `cognitive_agent.py:59` / `cognitive_agent.py:2058-2064` / `cognitive_agent.py:2073-2086` / `sub_task.py:172` anchors. This archive prompt was written on 2026-04-30 — the realised-not-shipped status of AD-652 has been documented in the tree for over a week before Wave 95.

The realisation evidence in the source code itself:

- **AD-649 communication context:** `grep -n "_communication_context" src/probos/cognitive/cognitive_agent.py` → `2223: observation["_communication_context"] = derive_communication_context(`. Channel/recipient → 5-register field/mode inference. Confirmed live at HEAD.
- **AD-639 chain trust band:** `grep -n "_chain_trust_band" src/probos/cognitive/cognitive_agent.py` → lines `2055-2062`, three branches (low / mid / high) setting `observation["_chain_trust_band"]`. Tenor weighting via personality block injection in EVALUATE / REFLECT. Confirmed live at HEAD.
- **AD-651 / AD-651a / AD-653 status:** `grep -n "AD-651 COMPLETE\|AD-651a CLOSED\|AD-653 COMPLETE" PROGRESS.md` → hits at lines 335 (AD-653), 337 (AD-651), 338 (AD-651a). All complete.
- **AD-647 / AD-647c status in roadmap.md:** Both marked Complete in the AD-647 / AD-647c bullets.
- **AD-650 status in roadmap.md:** Marked Complete in the AD-650 bullet at the Meta-Harness Research Wave section.
- **Downstream consumers AD-655 / AD-656 / AD-657 / AD-658 / AD-659 / AD-660:** All marked Complete or v1 complete in the roadmap.md Meta-Harness Research Wave section. AD-656 and AD-658 explicitly cite `*Depends on: AD-652*` — dependency satisfied as documented.

This wave is "flip the stale tracker labels to reflect what already shipped", not "ship the principle's implementation" — the implementation has already shipped across nine related ADs.

## Reframe decision — no reframe (no-build close)

**Zero concrete sub-AD letters built + zero future sub-AD letters parked + zero commercial carve-outs + zero hard-deferrals.** AD-652 is a principle, not a module. There is nothing to ship in v1 because every applicable principle is already realised across shipped children at HEAD. Captain rule "don't defer unless no choice" satisfied vacuously — there is genuinely nothing to defer because there is nothing to add.

Wave 95 is structurally identical to:
- **W71 (#415 AD-644b)** — no-build close, dependency satisfied by other shipped work
- **W76 (#285 AD-644)** — no-build close, scope already realised by parallel work
- **W90 (#111 AD-462)** — no-build close, all six pillars shipped before umbrella closure
- **W94 (#37 AD-579)** — no-build close, all three sub-ADs shipped before umbrella closure

In all four precedents, the umbrella was a tracking artefact for a multi-AD theme, the children shipped through their own waves, and the umbrella close was pure tracker reconciliation. Wave 95 follows the same pattern.

## Files

- `prompts/WAVE-95-DISPATCH.md` (this file)
- `prompts/ad-652-cognitive-code-switching-umbrella-close.md` (the per-AD prompt — 4 SEARCH/REPLACE pairs across 4 MODIFY blocks + tests + tracker updates + verification footer)
- `prompts/wave-plan.yaml` (W95 entry appended to W94 tail)

## Wave-95 baseline + targets

- **HEAD:** `b02a9a4` (Wave 94 archive: AD-579 memory architecture umbrella — closed #37). Captain reference HEAD `b02a9a4` matches `origin/main` exactly; no upstream BF commits between Captain HEAD and this draft HEAD.
- **Baseline pytest:** 12130 (verified `.venv/Scripts/pytest.exe --collect-only -q tests/` → `12130 tests collected`).
- **Target pytest:** **12130** (Δ = 0 — tracker-only reconciliation cannot move the test count). Any other pytest result means an unrelated regression entered between draft and build, and Builder must hard-stop and surface back to Architect.
- **Issue closed:** `#302 — AD-652: Cognitive Code-Switching — Unified Pipeline with Contextual Modulation` (single issue; no children minted by W95).

## Banned-pattern audit on this dispatch + the per-AD prompt + this audit prose itself

Eleven patterns checked, descriptor-only language used throughout: "the e-word + tier phrase", "the private commercial-repo path token", "the e-word overlay phrase", "the e-word-prefixed repo token", "monthly-price regex", "per-month abbreviation regex", "rev-proj phrase", "the recurring-revenue acronym", "outcome-style pricing phrase", "the GTM-pattern phrase", "the patterns-to-absorb phrase". The audit text itself does NOT contain literal forms of any banned pattern — descriptor-only references throughout. The pre-commit hook trips on literal "the e-word + tier phrase" and "the private commercial-repo path token" forms; this dispatch (and the per-AD prompt + the wave-plan.yaml notes block) avoids both literal forms via descriptor-only references. Pre-commit-hook simulation `Select-String -Path prompts/WAVE-95-DISPATCH.md, prompts/ad-652-cognitive-code-switching-umbrella-close.md -Pattern <pattern> -SimpleMatch` returns zero hits per pattern across all artefacts. Note: AD-652 is purely OSS cognitive-architecture work (Halliday/Levelt/Giles/Snyder/Weick-Sutcliffe research foundation, billet instructions as cognitive scaffolding, trust-gated register shifting via Counselor event subscription) — there is no commercial scope to leak. The audit is a hygiene check, not a defence against a real leak vector.

## Captain rule alignment

- **Don't defer unless no choice:** zero deferrals. AD-652 has no sub-AD letters because it is a principle, not a module. All six design principles are realised at HEAD across shipped children (AD-632 unified pipeline substrate, AD-649 communication context, AD-639 chain trust band, AD-650 analytical depth, AD-651 standing order decomposition, AD-651a compose billets, AD-647 / AD-647c process chains, AD-653 Layer 1 speak-freely register shifting). Reframe decision: no reframe needed — the principle is fully realised, only the trackers lag. Wave 95 is the canonical no-build umbrella close pattern (W71 / W76 / W90 / W94 precedent).
- **Verify-first:** every concrete claim in the per-AD prompt has an explicit grep-evidence line in the `## Verified Against Codebase (2026-05-07, HEAD b02a9a4)` footer. Eight grep-anchored claims confirm extension-point existence, file/line anchor accuracy, status of realisation children, and absence of AD-652 in era-4.
- **`.github/copilot-instructions.md` compliance:** trivially satisfied — Wave 95 ships zero source code changes, zero test changes, zero schema changes. The four tracker edits are documentation reconciliation. No SOLID review needed (no new classes), no exception handling tier review needed (no new error paths), no async hygiene review needed (no new tasks), no test coverage review needed (no new methods). Engineering Principles compliance is verified vacuously.
- **Close #302 cleanly:** issue closed at end of W95 with the canonical paragraph in Section 5 of the per-AD prompt; no children minted, no follow-up issues. Realisation children (AD-655 / AD-656 / AD-657 / AD-658 / AD-659 / AD-660) remain attached to the Meta-Harness Research Wave's own tracking; W95 cites them as evidence not as new deferrals.
- **No commercial leak:** descriptor-only audit, banned-pattern scan returns zero hits across all 11 patterns. AD-652 is purely OSS cognitive-architecture work — there is no commercial scope to leak.

## Build groups

Single MODIFY pass — no dependency DAG, no build group ordering. The four SEARCH/REPLACE pairs are independent and can be applied in any order:

1. `DECISIONS.md` — flip AD-652 status header + append `**Realised in:**` subsection (1 SEARCH/REPLACE pair)
2. `docs/development/roadmap.md` — flip AD-652 bullet status + append realisation list (1 SEARCH/REPLACE pair)
3. `PROGRESS.md` — flip line 331 status note (1 SEARCH/REPLACE pair)
4. `prompts/wave-plan.yaml` — append W95 entry to W94 tail (1 SEARCH/REPLACE pair)

Total: **4 SEARCH/REPLACE pairs across 4 MODIFY blocks.** Builder applies them top-to-bottom as written in the per-AD prompt. No code, no tests, no migrations.

## Hard-stops specific to W95

- **W95-1:** Any of the 4 SEARCH blocks fails to match (anchor drift since draft) → Builder surfaces back to Architect, do not improvise. Anchor verification footer in the per-AD prompt provides exact line numbers and grep evidence — drift means an unrelated commit landed between draft and build.
- **W95-2:** Pytest gate returns anything other than **12130 tests passing** → Builder hard-stops and surfaces back. Tracker-only changes cannot move the test count; any delta means an unrelated regression entered between draft and build.
- **W95-3:** Pre-commit hook flags banned literal in any of the modified surfaces → Builder hard-stops and surfaces back. AD-652 has no commercial scope so this should never trigger; if it does, something has gone wrong with the audit.
- **W95-4:** Builder elects to ship a fresh AD-652 sub-AD letter "while we're here" → out of scope. AD-652 has no sub-AD letters because it is a principle, not a discrete module. Hard-stop.
- **W95-5:** Builder elects to mint a new GH issue for any of the AD-652 realisation children → out of scope. Umbrella close cites them as evidence, does not re-track them. Hard-stop.
- **W95-6:** Builder elects to add a `### AD-652` paragraph to `decisions-era-4-evolution.md` → out of scope. Canonical decision record lives at `DECISIONS.md:2253-2280` only. Era-4 has zero AD-652 matches (verified) and W95 does not create one. Hard-stop.
- **W95-7:** Builder elects to flip the AD-655 / AD-656 / AD-657 / AD-658 / AD-659 / AD-660 entries at `roadmap.md:7117-7123` → already correct, all read complete or v1 complete with AD-652 dependency satisfied. Touching them is unnecessary churn. Hard-stop.

## Build report and post-sweep procedures

Builder execution sequence:

1. Read `prompts/ad-652-cognitive-code-switching-umbrella-close.md` top-to-bottom.
2. Apply 4 SEARCH/REPLACE pairs across 4 MODIFY blocks (1 on `DECISIONS.md`, 1 on `docs/development/roadmap.md`, 1 on `PROGRESS.md`, 1 on `prompts/wave-plan.yaml`).
3. Verify `git diff --stat` shows exactly 4 modified files plus the 2 new prompt files (`WAVE-95-DISPATCH.md` and `ad-652-cognitive-code-switching-umbrella-close.md`).
4. Verify `git diff decisions-era-4-evolution.md` shows zero changes.
5. Run full pytest gate: `.venv/Scripts/pytest.exe -q -n 4 --dist=loadfile tests/`. Expected: **12130 passed**. Any other result → hard-stop W95-2.
6. Pre-commit hook runs naturally on commit. Any banned-pattern hit → hard-stop W95-3.
7. Commit with message: `"AD-652: Cognitive Code-Switching umbrella close — tracker reconciliation (no-build, +0 tests)"`.
8. Archive both prompts to `prompts/archive/`:
   - `prompts/WAVE-95-DISPATCH.md` → `prompts/archive/WAVE-95-DISPATCH.md`
   - `prompts/ad-652-cognitive-code-switching-umbrella-close.md` → `prompts/archive/ad-652-cognitive-code-switching-umbrella-close.md`
9. Run `gh issue close 302` with the canonical close paragraph in Section 5 of the per-AD prompt. Replace `<SHA>` placeholder with the commit hash from `git rev-parse HEAD`.
10. Push to `origin/main`.

Post-sweep procedures: none required. Wave 95 is a single-AD wave with no follow-on work, no further reconciliation, no build dispatch. The next wave (W96) picks up from a clean slate.

## 4 review passes recorded in this draft session

- **P1 (initial draft against HEAD `b02a9a4`):** structure mirrored on W90 (#111 AD-462) and W94 (#37 AD-579) no-build umbrella close patterns. AD-652 `Realised in` mapping verified against the six numbered Design Principles in `DECISIONS.md:2253-2280`. Realisation children identified by reading `roadmap.md` Meta-Harness Research Wave section (lines 7105-7123) plus PROGRESS.md status notes. Independent confirmation found in `prompts/archive/ad-658-chain-harness-metrics-v1.md:11-19` AD-652 Status Note section.
- **P2 (verify-first sweep):** confirmed AD-652 DECISIONS.md entry at lines 2253-2280 (next entry AD-653 starts at 2282). Confirmed AD-652 roadmap.md bullet at line 7105 with `Design Principle, OSS, Issue #302` string. Confirmed PROGRESS.md AD-652 line 331 with `DESIGN PRINCIPLE adopted` prefix. Confirmed wave-plan.yaml W94 tail anchor with `archive both prompts. gh issue close 37` ending. Confirmed AD-649 `derive_communication_context` at `cognitive_agent.py:59` plus `observation _communication_context` set at `cognitive_agent.py:2223` via grep. Confirmed AD-639 `_chain_trust_band` assignments at `cognitive_agent.py:2055-2062` (three branches low / mid / high). Confirmed AD-651 + AD-651a + AD-653 + AD-647 + AD-647c + AD-650 all marked Complete in roadmap.md. Confirmed downstream consumers AD-655 / AD-656 / AD-657 / AD-658 / AD-659 / AD-660 all marked Complete or v1 complete in roadmap.md Meta-Harness Research Wave section. Confirmed zero AD-652 paragraph in decisions-era-4-evolution.md via `grep -c "AD-652" decisions-era-4-evolution.md` returning `0`. Confirmed AD-658 archive prompt explicit AD-652 status note at `prompts/archive/ad-658-chain-harness-metrics-v1.md:11-19`. Confirmed pytest baseline 12130 via `.venv/Scripts/pytest.exe --collect-only -q tests/`. Confirmed highest AD/BF (696 / 596) via Select-String scan.
- **P3 (reframe table):** confirmed no-build is the correct path. No sub-AD letter is mintable because AD-652 is a principle not a module. No consumer of AD-652 is incomplete that would force a deferral. All six principles are realised at HEAD. Captain rule "don't defer unless no choice" satisfied vacuously — there is genuinely nothing to defer because there is nothing to add. W95 structurally identical to W71 / W76 / W90 / W94 no-build closes. Reframe decision: no reframe.
- **P4 (banned-pattern audit + per-section consistency check):** banned-pattern audit on full text of WAVE-95-DISPATCH.md + ad-652-cognitive-code-switching-umbrella-close.md + the wave-plan.yaml notes block. Eleven patterns checked, zero literal hits per pattern. Per-section consistency check between dispatch + prompt + wave-plan.yaml entry — all three artefacts use the same realisation child list (AD-632 / AD-649 / AD-639 / AD-650 / AD-651 / AD-651a / AD-647 / AD-647c / AD-653), the same downstream consumer list (AD-655 / AD-656 / AD-657 / AD-658 / AD-659 / AD-660), the same baseline (12130) and target (12130), the same SEARCH/REPLACE pair count (4), the same MODIFY block count (4), the same era-4 anti-anchor (zero matches). AD numbering verified — AD-696 highest, BF-596 highest, no collision possible since W95 mints zero new AD/BF. SEARCH/REPLACE block uniqueness verified — DECISIONS.md SEARCH includes the metadata block down through `Related:` line which is unique in the file (only one AD-652 entry exists), roadmap.md SEARCH includes the full bullet text from `***AD-652:` through the closing `*Related:` italics which is unique to line 7105, PROGRESS.md SEARCH includes the AD-652 DESIGN PRINCIPLE line with full context which is unique to line 331, wave-plan.yaml SEARCH attaches to W94's `archive both prompts. gh issue close 37 with the canonical paragraph in Section 4 of the per-AD prompt.` tail which is unique. Audit prose itself uses descriptor-only language throughout — no literal banned-pattern forms anywhere in the wave artefacts.
