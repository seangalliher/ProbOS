# AD-652 Cognitive Code-Switching — Umbrella Close (no-build, tracker reconciliation)

**Status:** Ready for Builder
**Dependencies:** None — all AD-652 design principles are realised across already-shipped child ADs at HEAD `b02a9a4`
**Estimated tests:** **0** (no source/test changes — tracker-only close, zero pytest delta)
**Issue closed:** GH #302
**Baseline pytest:** 12130 → target 12130 (Δ = 0)

## Problem

GH #302 ("AD-652: Cognitive Code-Switching — Unified Pipeline with Contextual Modulation") tracks an **architectural design principle** adopted on 2026-04-20 (`DECISIONS.md:2253-2280`). The principle defines six rules governing how the cognitive chain handles different communication types: (1) Unified Pipeline, (2) Contextual Modulation (Halliday field/tenor/mode), (3) Structured Format Overlays, (4) Variable Chain Depth, (5) Character-Driven Self-Monitoring, (6) Process-Specific Chains.

Unlike a typical AD that scopes a discrete module, AD-652 is a **principle that governs other ADs**. Every one of its six rules is fully realised at HEAD across already-shipped child ADs:

| Principle | Realised by |
|---|---|
| 1. Unified Pipeline (one chain, identity continuity) | AD-632 (Cognitive Chain Architecture) — `SubTaskExecutor` at `src/probos/cognitive/sub_task.py:172` is THE unified pipeline; AD-632a/h/f/e all Complete |
| 2. Contextual Modulation (field/tenor/mode → chain behavior) | AD-649 — `derive_communication_context()` at `cognitive_agent.py:59`; sets `observation["_communication_context"]` at `cognitive_agent.py:2223`; 5 registers (private_conversation, bridge_briefing, casual_social, ship_wide, department_discussion). AD-639 — chain trust band sets `observation["_chain_trust_band"]` at `cognitive_agent.py:2055-2062`; trust band → personality weighting. AD-650 — analytical depth via `analytical_reasoning` narrative field. |
| 3. Structured Format Overlays (billet instructions as cognitive scaffolding) | AD-651 — `StepInstructionRouter` slices composed standing orders by `<!-- category: ... -->` markers, ANALYZE/COMPOSE call `get_step_instructions()`. AD-651a — `[PROPOSAL]` block syntax + structured Findings/Assessment/Recommendation duty report format injected directly into compose prompt. |
| 4. Variable Chain Depth (different step compositions per task) | AD-647 (Process Chains) — process chains define their own step types (QUERY/TRANSFORM/STORE/NOTIFY) distinct from communication chain. AD-647c — LLM-template + CALLABLE handlers + NATS dispatch. SubTaskExecutor's per-intent chain selection is the substrate. |
| 5. Character-Driven Self-Monitoring (code-switching range varies by personality) | AD-639 — chain personality tuning via trust band. AD-653 Layer 1 — `speak_freely` intended_action with trust-gated authorization (≥0.7 auto-granted, 0.4-0.7 flagged, <0.4 denied), Counselor receives `REGISTER_SHIFT_GRANTED/DENIED` events for pattern tracking. |
| 6. Process-Specific Chains (different processes can have different step compositions) | AD-647 / AD-647c — process chains framework distinct from communication chain; scout report (search→classify→store→notify) is reference implementation. |

Downstream consumers AD-655 (Contrastive Memory Retrieval), AD-656 (Department-Specific Cognitive Profiles), AD-657 (Dream Trace Preservation), AD-658 (Chain Harness Metrics), AD-659 (Chain Self-Optimization Loop v1), and AD-660 (Causal Reasoning) all reference AD-652 modulation parameters and are themselves Complete. The AD-658 archive prompt (`prompts/archive/ad-658-chain-harness-metrics-v1.md:11-19`) explicitly documents this status: *"AD-652 (`Cognitive Code-Switching: Unified Pipeline with Contextual Modulation`) is a **DESIGN PRINCIPLE adopted in DECISIONS.md:1914**, not a discrete shipped module. It is realised across multiple ADs already in the tree."*

**The defect this AD closes:** the trackers still describe AD-652 as `Design Principle (adopted)` rather than reflecting that all six principles are now realised across shipped children. The umbrella status was correct at adoption (2026-04-20) but stale at HEAD (`b02a9a4`, 2026-05-07) after AD-647c, AD-651, AD-651a, and AD-653 shipped.

## Solution

**No code, no tests.** Single tracker reconciliation pass mirroring W90 (#111 AD-462 umbrella) and W94 (#37 AD-579 umbrella) precedent — both structurally identical no-build umbrella closes:

1. Flip `DECISIONS.md` AD-652 entry status from `Design Principle (adopted)` to `Realised (Wave 95 close)` and append a `**Realised in:**` subsection mapping each of the six principles to its concrete child AD plus file/line anchors. (1 SEARCH/REPLACE pair on `DECISIONS.md`.)
2. Flip `docs/development/roadmap.md` AD-652 bullet from `*(Design Principle, OSS, Issue #302)*` to `*(Realised, OSS, Issue #302)*` and replace the trailing prose with the realisation list. (1 SEARCH/REPLACE pair on `docs/development/roadmap.md`.)
3. Flip `PROGRESS.md` line 331 status note from `AD-652 DESIGN PRINCIPLE (adopted).` to `AD-652 REALISED.` with a one-line summary of the realisation children. (1 SEARCH/REPLACE pair on `PROGRESS.md`.)
4. Append a Wave 95 entry to `prompts/wave-plan.yaml`. (1 SEARCH/REPLACE pair attaching to the W94 tail.)

Total: **4 SEARCH/REPLACE pairs across 4 MODIFY blocks.**

There is **no AD-652 paragraph in `decisions-era-4-evolution.md`** (`grep -c "AD-652" decisions-era-4-evolution.md` = 0) — Wave 95 does NOT add or modify era-4 content. The canonical decision record lives at `DECISIONS.md:2253-2280`.

Wave 95 mints zero new GH issues. The downstream consumer ADs (AD-655 through AD-660) remain attached to the Meta-Harness Research Wave's own tracking; AD-652's umbrella close cites them as realisation evidence, not as new deferrals.

### Section 1 — Update `DECISIONS.md`

Single SEARCH/REPLACE pair on the AD-652 entry. Anchors verified at HEAD `b02a9a4` (line 2253-2280).

```
===MODIFY: DECISIONS.md===
===SEARCH===
### AD-652 — Cognitive Code-Switching: Unified Pipeline with Contextual Modulation

**Date:** 2026-04-20
**Status:** Design Principle (adopted)
**Issue:** #302
**Parent:** AD-632 (Cognitive Chain Architecture)
**Related:** AD-651 (Billet Instructions), AD-639 (Chain Personality Tuning), AD-647 (Process Chains)
===REPLACE===
### AD-652 — Cognitive Code-Switching: Unified Pipeline with Contextual Modulation

**Date:** 2026-04-20 (adopted); 2026-05-07 (Wave 95 umbrella close)
**Status:** Realised (Wave 95 close — all six principles delivered across shipped child ADs)
**Issue:** #302
**Parent:** AD-632 (Cognitive Chain Architecture)
**Related:** AD-651 (Billet Instructions), AD-639 (Chain Personality Tuning), AD-647 (Process Chains)
**Realised in:** AD-632 (unified pipeline substrate), AD-649 (channel/recipient → register inference), AD-639 (chain trust band modulation), AD-650 (analytical depth field), AD-651 (standing order decomposition), AD-651a (compose billet — proposal/duty format), AD-647 / AD-647c (process chains — variable chain depth + process-specific composition), AD-653 Layer 1 (speak-freely register shifting). Downstream consumers AD-655 / AD-656 / AD-657 / AD-658 / AD-659 / AD-660 all complete and reference AD-652 modulation parameters. Trackers reconciled in Wave 95.
===END REPLACE===
===END MODIFY===
```

The six numbered Design Principles, the Motivation paragraph, the Key Insight, and the Research line all remain unchanged — only the metadata block at the top of the entry is rewritten.

### Section 2 — Update `docs/development/roadmap.md`

Single SEARCH/REPLACE pair on the AD-652 bullet. Anchor verified at HEAD `b02a9a4` (line 7105).

```
===MODIFY: docs/development/roadmap.md===
===SEARCH===
***AD-652: Cognitive Code-Switching — Unified Pipeline with Contextual Modulation** *(Design Principle, OSS, Issue #302)* — Architectural principle adopted based on cognitive science research (Levelt, Halliday, Giles, Snyder, Weick/Sutcliffe). The cognitive chain is a single unified pipeline, not parallel pipelines for different communication types. Different cognitive tasks are handled through contextual modulation: variable chain depth, tenor-aware compose framing, and structured format overlays (billet instructions). Six principles: (1) Unified Pipeline — one chain framework, identity continuity; (2) Contextual Modulation — field/tenor/mode parameters (Halliday) modulate chain behavior; (3) Structured Format Overlays — institutional outputs get prescriptive billet instructions as cognitive scaffolding (HRO research); (4) Variable Chain Depth — high-structure tasks get more steps, low-structure tasks fewer; (5) Character-Driven Self-Monitoring — code-switching range varies by Big Five personality (Snyder); (6) Process-Specific Chains — different tasks can have different step compositions, but same-process tasks share the chain and modulate parameters. Analogy: like a chat temperature slider from formal to friendly, but modulation is in prompt context, not literal LLM temperature. Research: `docs/research/cognitive-code-switching-research.md`. *Related: AD-651 (Billet Instructions), AD-639 (Chain Personality Tuning), AD-647 (Process Chains), AD-632 (Chain Architecture).*
===REPLACE===
***AD-652: Cognitive Code-Switching — Unified Pipeline with Contextual Modulation** *(Realised, OSS, Issue #302)* — Architectural principle adopted 2026-04-20 based on cognitive science research (Levelt, Halliday, Giles, Snyder, Weick/Sutcliffe). The cognitive chain is a single unified pipeline, not parallel pipelines for different communication types. Different cognitive tasks are handled through contextual modulation: variable chain depth, tenor-aware compose framing, and structured format overlays (billet instructions). Six principles: (1) Unified Pipeline — one chain framework, identity continuity; (2) Contextual Modulation — field/tenor/mode parameters (Halliday) modulate chain behavior; (3) Structured Format Overlays — institutional outputs get prescriptive billet instructions as cognitive scaffolding (HRO research); (4) Variable Chain Depth — high-structure tasks get more steps, low-structure tasks fewer; (5) Character-Driven Self-Monitoring — code-switching range varies by Big Five personality (Snyder); (6) Process-Specific Chains — different tasks can have different step compositions, but same-process tasks share the chain and modulate parameters. **Realised in (Wave 95 close, 2026-05-07):** AD-632 (`SubTaskExecutor` unified-pipeline substrate at `cognitive/sub_task.py:172`); AD-649 (`derive_communication_context` at `cognitive_agent.py:59`, sets `_communication_context` at `cognitive_agent.py:2223` — channel/recipient → 5-register field/mode inference); AD-639 (chain trust band at `cognitive_agent.py:2055-2062` — tenor weighting); AD-650 (`analytical_reasoning` narrative field — depth modulation); AD-651 (`StepInstructionRouter` — billet instructions as structured format overlays); AD-651a (`[PROPOSAL]` block + Findings/Assessment/Recommendation duty format — first practical billet application); AD-647 / AD-647c (process chains framework — variable depth + process-specific composition, distinct from communication chain); AD-653 Layer 1 (speak-freely intended_action with trust-gated authorization — character-driven register shifting). Downstream consumers AD-655 / AD-656 / AD-657 / AD-658 / AD-659 v1 / AD-660 all complete and reference AD-652 modulation parameters. Research: `docs/research/cognitive-code-switching-research.md`. *Related: AD-651 (Billet Instructions), AD-639 (Chain Personality Tuning), AD-647 (Process Chains), AD-632 (Chain Architecture).*
===END REPLACE===
===END MODIFY===
```

### Section 3 — Update `PROGRESS.md`

Single SEARCH/REPLACE pair on line 331. Anchor verified at HEAD `b02a9a4`.

```
===MODIFY: PROGRESS.md===
===SEARCH===
AD-652 DESIGN PRINCIPLE (adopted). Cognitive Code-Switching — unified pipeline with contextual modulation. One chain, not parallel pipelines. Field/tenor/mode parameters modulate behavior. Structured format overlays for institutional outputs. Variable chain depth. Character-driven self-monitoring range. Research: cognitive-code-switching-research.md. Issue #302.
===REPLACE===
AD-652 REALISED (Wave 95 close, 2026-05-07). Cognitive Code-Switching — unified pipeline with contextual modulation. All six principles delivered across shipped children: AD-632 (unified pipeline substrate), AD-649 (channel→register inference, 5 registers), AD-639 (chain trust band tenor weighting), AD-650 (analytical_reasoning depth field), AD-651 (StepInstructionRouter billet overlays), AD-651a (proposal + duty report compose billets), AD-647/AD-647c (process chains — variable depth + process-specific composition), AD-653 Layer 1 (speak-freely register shifting, trust-gated). Downstream consumers AD-655/AD-656/AD-657/AD-658/AD-659/AD-660 all complete. Tracker reconciliation only — no code, no tests. Research: cognitive-code-switching-research.md. Issue #302 closed.
===END REPLACE===
===END MODIFY===
```

### Section 4 — Append `prompts/wave-plan.yaml`

Append at the end of file by attaching to the W94 entry's tail. Anchor verified at HEAD `b02a9a4` (file tail).

```
===MODIFY: prompts/wave-plan.yaml===
===SEARCH===
      "AD-579: Memory Architecture umbrella close — tracker reconciliation
      (no-build, +0 tests)". Archive both prompts. gh issue close 37 with
      the canonical paragraph in Section 4 of the per-AD prompt.
===REPLACE===
      "AD-579: Memory Architecture umbrella close — tracker reconciliation
      (no-build, +0 tests)". Archive both prompts. gh issue close 37 with
      the canonical paragraph in Section 4 of the per-AD prompt.
  - id: "95"
    title: "AD-652 Cognitive Code-Switching — Umbrella Close (no-build, tracker reconciliation)"
    kind: single
    depends_on: ["94"]
    dispatch_prompt: "prompts/WAVE-95-DISPATCH.md"
    prompts_already_drafted: true
    prompt_paths:
      - "prompts/ad-652-cognitive-code-switching-umbrella-close.md"
    builder_required: true
    issues_to_close: [302]
    status: pending
    notes: |
      No-build close of GH #302 (AD-652 umbrella). AD-652 is an
      architectural design principle adopted 2026-04-20 (DECISIONS.md:
      2253-2280) that governs the cognitive chain pipeline — six rules:
      unified pipeline, contextual modulation (Halliday field/tenor/mode),
      structured format overlays (billet instructions), variable chain
      depth, character-driven self-monitoring, process-specific chains.
      Unlike a typical AD that scopes a discrete module, AD-652 is a
      principle that governs OTHER ADs. All six principles are fully
      realised at HEAD b02a9a4 across already-shipped child ADs:
      AD-632 SubTaskExecutor unified-pipeline substrate at cognitive/
      sub_task.py:172; AD-649 derive_communication_context at
      cognitive_agent.py:59 with 5 channel registers (private_conversation,
      bridge_briefing, casual_social, ship_wide, department_discussion)
      setting observation _communication_context at cognitive_agent.py:
      2223 — channel/recipient → field/mode register inference; AD-639
      chain trust band at cognitive_agent.py:2055-2062 — tenor weighting
      of personality block in EVALUATE/REFLECT; AD-650 analytical_reasoning
      narrative field on ANALYZE composition brief — depth modulation;
      AD-651 StepInstructionRouter slicing composed standing orders by
      category markers — billet instructions as cognitive scaffolding;
      AD-651a [PROPOSAL] block syntax injected into compose + Findings/
      Assessment/Recommendation duty report format — first practical
      billet application; AD-647 / AD-647c process chains framework
      (QUERY/TRANSFORM/STORE/NOTIFY step types) distinct from
      communication chain — variable depth + process-specific composition;
      AD-653 Layer 1 speak_freely intended_action with trust-gated
      authorization (≥0.7 auto-granted, 0.4-0.7 flagged, <0.4 denied)
      and Counselor REGISTER_SHIFT_GRANTED/DENIED event subscription —
      character-driven register shifting. Downstream consumers AD-655
      contrastive memory, AD-656 department cognitive profiles, AD-657
      dream trace preservation, AD-658 chain harness metrics, AD-659 v1
      chain self-optimization, AD-660 causal reasoning all complete and
      reference AD-652 modulation parameters. The AD-658 archive prompt
      itself (prompts/archive/ad-658-chain-harness-metrics-v1.md:11-19)
      documents the realised-not-shipped status: AD-652 dependency
      satisfied as-is, no wiring changes. Wave 95 reconciles four
      trackers: DECISIONS.md:2253-2280 (status: Design Principle adopted
      → Realised, append Realised in subsection), docs/development/
      roadmap.md:7105 (bullet: Design Principle, OSS, Issue #302 →
      Realised, OSS, Issue #302 with realisation list), PROGRESS.md:331
      (DESIGN PRINCIPLE adopted → REALISED with one-line realisation
      summary), prompts/wave-plan.yaml (this entry). Total: 4 SEARCH/
      REPLACE pairs across 4 MODIFY blocks. There is no AD-652 paragraph
      in decisions-era-4-evolution.md (grep returns zero matches) — W95
      does NOT touch era-4 content; canonical decision record lives at
      DECISIONS.md:2253-2280. No code touched, no tests added, no pytest
      delta (target 12130 → 12130). No source changes, no test changes,
      no notebook/qualification/journal changes. No new GH issues
      minted — downstream consumer ADs remain attached to the
      Meta-Harness Research Wave's own tracking; W95 cites them as
      realisation evidence not as new deferrals. No commercial leak —
      AD-652 is purely OSS cognitive-architecture work (cognitive
      science research foundation: Levelt, Halliday, Giles, Snyder,
      Weick/Sutcliffe; HRO research; cognitive chain pipeline modulation
      via field/tenor/mode parameters; structured format overlays via
      billet instructions; trust-gated register shifting). Zero
      tier-noun phrase / pricing-token regex / SaaS-overlay descriptor
      surface anywhere in the umbrella. Banned-pattern audit on
      WAVE-95-DISPATCH.md + ad-652-cognitive-code-switching-umbrella-
      close.md + this notes block: 11 patterns checked, 0 literal hits
      per pattern. Placeholder forms used throughout: the e-word + tier
      phrase, the private commercial-repo path token, the e-word
      overlay phrase, the e-word-prefixed repo token, monthly-price
      regex, per-month abbreviation regex, rev-proj phrase, the
      recurring-revenue acronym, outcome-style pricing phrase, the
      GTM-pattern phrase, the patterns-to-absorb phrase. Pre-commit-hook
      simulation Select-String -SimpleMatch returns zero per pattern
      across all three artefacts. Hard-stops specific to W95: W95-1 any
      of the 4 SEARCH blocks fails to match (anchor drift since draft)
      → Builder surfaces back to Architect, do not improvise; W95-2
      pytest gate returns anything other than 12130 (tracker-only
      changes cannot move count; any delta means unrelated regression
      entered between draft and build); W95-3 pre-commit hook flags
      banned literal in any of the modified surfaces; W95-4 Builder
      elects to ship a fresh AD-652 sub-AD letter while we are here →
      out of scope, AD-652 has no sub-AD letters (it is a principle,
      not a discrete module); W95-5 Builder elects to mint a new GH
      issue for any of the AD-652 realisation children → out of scope,
      umbrella close cites them not re-tracks them; W95-6 Builder
      elects to add a ### AD-652 paragraph to decisions-era-4-
      evolution.md → out of scope, canonical decision record lives at
      DECISIONS.md:2253-2280, era-4 has no AD-652 entry (verified
      grep zero matches) and W95 does not create one; W95-7 Builder
      elects to flip the AD-655 / AD-656 / AD-657 / AD-658 / AD-659
      / AD-660 entries at roadmap.md:7117-7123 → already correct, all
      read complete or v1 complete with AD-652 dependency satisfied,
      touching them is unnecessary churn. 4 review passes recorded in
      this draft session: P1 (initial draft against HEAD b02a9a4 —
      structure mirrored on W90 / W94 no-build umbrella close pattern;
      AD-652 Realised in mapping verified against DECISIONS.md
      principles 1-6); P2 (verify-first sweep — confirmed AD-652
      DECISIONS.md entry at lines 2253-2280, confirmed AD-652
      roadmap.md bullet at line 7105 with Design Principle, OSS,
      Issue #302 string, confirmed PROGRESS.md AD-652 line 331 with
      DESIGN PRINCIPLE adopted prefix, confirmed wave-plan.yaml W94
      tail anchor with archive both prompts. gh issue close 37 ending,
      confirmed AD-649 derive_communication_context at cognitive_agent.
      py:59 + observation _communication_context set at cognitive_
      agent.py:2223, confirmed AD-639 _chain_trust_band assignments
      at cognitive_agent.py:2055-2062, confirmed AD-651 + AD-651a +
      AD-653 + AD-647 + AD-647c + AD-650 all marked Complete in
      roadmap.md, confirmed AD-655 / AD-656 / AD-657 / AD-658 /
      AD-659 / AD-660 all marked Complete or v1 complete in roadmap.md
      Meta-Harness Research Wave section, confirmed zero AD-652
      paragraph in decisions-era-4-evolution.md via grep zero matches,
      confirmed AD-658 archive prompt explicit AD-652 status note at
      prompts/archive/ad-658-chain-harness-metrics-v1.md:11-19);
      P3 (reframe table — confirmed no-build is correct path, no
      sub-AD letter mintable because AD-652 is a principle not a
      module, no consumer of AD-652 is incomplete that would force
      a deferral, all six principles realised at HEAD; Captain rule
      "don't defer unless no choice" satisfied vacuously — there is
      genuinely nothing to defer because there is nothing to add; W95
      structurally identical to W71 / W76 / W90 / W94 no-build
      closes); P4 (banned-pattern audit on full text + per-section
      consistency check between dispatch + prompt + this entry; AD
      numbering verified AD-696 highest, BF-596 highest, no collision
      possible since W95 mints zero new AD/BF; SEARCH/REPLACE block
      uniqueness verified — DECISIONS.md SEARCH includes the metadata
      block down through Related: line which is unique in the file,
      roadmap.md SEARCH includes the full bullet text which is unique,
      PROGRESS.md SEARCH includes the AD-652 DESIGN PRINCIPLE line
      with full context which is unique to line 331, wave-plan.yaml
      SEARCH attaches to W94 archive both prompts. gh issue close 37
      tail which is unique). Builder execution: read prompt
      top-to-bottom, apply 4 SEARCH/REPLACE pairs across 4 MODIFY
      blocks (1 on DECISIONS.md, 1 on docs/development/roadmap.md, 1
      on PROGRESS.md, 1 on prompts/wave-plan.yaml). Verify git diff
      --stat shows exactly 4 modified trackers plus the 2 new prompt
      files. Pre-commit hook runs naturally on commit. Full pytest
      gate belt-and-braces (expected 12130 passed). Commit with
      "AD-652: Cognitive Code-Switching umbrella close — tracker
      reconciliation (no-build, +0 tests)". Archive both prompts.
      gh issue close 302 with the canonical paragraph in Section 5
      of the per-AD prompt.
===END REPLACE===
===END MODIFY===
```

## Verified Against Codebase (2026-05-07, HEAD b02a9a4)

**DECISIONS.md AD-652 entry:**
```
grep -n "AD-652" DECISIONS.md
  2253: ### AD-652 — Cognitive Code-Switching: Unified Pipeline with Contextual Modulation
  2285: **Parent:** AD-652 (Unified Pipeline / Contextual Modulation)  [from AD-653 child entry]
  2286: **Depends on:** AD-652, AD-504 (Self-Monitoring), AD-651 (Billet Instructions)
  2289: **Decision:** Extend the unified cognitive pipeline (AD-652) ...
  2291: **Motivation:** AD-652 established contextual modulation as a top-down mechanism ...
```
AD-652 entry occupies lines 2253-2280 (next entry AD-653 starts at 2282 with `### AD-653 — Dynamic Communication Register: Self-Monitored Register Shifting`).

**roadmap.md AD-652 bullet:**
```
grep -n "AD-652" docs/development/roadmap.md
  7105: ***AD-652: Cognitive Code-Switching — Unified Pipeline with Contextual Modulation** *(Design Principle, OSS, Issue #302)* ...
  7107: ***AD-653: Dynamic Communication Register — Self-Monitored Register Shifting** *(Complete, OSS, Issue #303)* ...
  7117: **AD-656: Department-Specific Cognitive Profiles** ... consumed by AD-652 code-switching field/tenor/mode parameters ...
  7121: **AD-658: Cognitive Chain Harness Metrics** ... *Depends on: AD-652 (Code-Switching gives modulation parameters to measure against) ...*
  7123: **AD-659: Cognitive Chain Self-Optimization Loop** ... It's parameter tuning within the Code-Switching modulation space (AD-652) ...
```

**PROGRESS.md AD-652 status note:**
```
grep -n "AD-652" PROGRESS.md
  45: AD-652 dependency satisfied as-is (design principle adopted in DECISIONS.md:1914; realised across AD-649/AD-639/AD-638 — no wiring changes).  [from AD-658 closure paragraph]
  331: AD-652 DESIGN PRINCIPLE (adopted). Cognitive Code-Switching — unified pipeline with contextual modulation. ...
```

**decisions-era-4-evolution.md AD-652 absence (anti-anchor):**
```
grep -c "AD-652" decisions-era-4-evolution.md
  0
```
Zero matches — Wave 95 must NOT add an `### AD-652` section to era-4. The canonical record lives at `DECISIONS.md:2253-2280` only.

**Realisation child verification (DECISIONS.md AD-652 principle 2 → AD-649 / AD-639):**
```
grep -n "_communication_context\|_chain_trust_band" src/probos/cognitive/cognitive_agent.py | head -10
  2055:                    observation["_chain_trust_band"] = "low"
  2057:                    observation["_chain_trust_band"] = "high"
  2059:                    observation["_chain_trust_band"] = "mid"
  2062:                    _agent_type, _trust, observation["_chain_trust_band"],
  2223:        observation["_communication_context"] = derive_communication_context(
```
Confirms AD-649 communication context inference and AD-639 chain trust band modulation are live at HEAD `b02a9a4`.

**Realisation child verification (DECISIONS.md AD-652 principle 1 → AD-632):**
The chain executor file exists at `src/probos/cognitive/sub_task.py` and is referenced extensively across the codebase. AD-632a/h/f/e and AD-647/AD-647c are documented as complete in `roadmap.md` and `PROGRESS.md`.

**Realisation child verification (AD-651, AD-651a, AD-653 status):**
```
grep -n "AD-651 COMPLETE\|AD-651a CLOSED\|AD-653 COMPLETE" PROGRESS.md
  335: AD-653 COMPLETE. Dynamic Communication Register — "speak freely" protocol (Layer 1) ...
  337: AD-651 CLOSED. Standing Order Decomposition — step-specific instruction routing for cognitive chain ...
  338: AD-651a CLOSED. Compose billet instructions — proposal format injected when analyze requests "proposal" ...
```

**AD-658 archive prompt explicit AD-652 status note:**
```
grep -n "AD-652" prompts/archive/ad-658-chain-harness-metrics-v1.md
  11: ## AD-652 Status Note
  13: **AD-652** ("Cognitive Code-Switching: Unified Pipeline with Contextual Modulation") is a **DESIGN PRINCIPLE adopted in DECISIONS.md:1914**, not a discrete shipped module. It is realised across multiple ADs already in the tree:
```
The AD-658 archive prompt itself documents that AD-652 is realised across child ADs and treats AD-652 as a satisfied dependency for AD-658's chain harness metrics work — independent confirmation of the realised-not-shipped status that Wave 95 reconciles.

**Highest AD/BF at HEAD:**
```
Select-String -Path PROGRESS.md, DECISIONS.md, decisions-era-*.md, docs/development/roadmap.md -Pattern '\bAD-(\d{3})' -AllMatches → max 696
Select-String -Path PROGRESS.md, DECISIONS.md, decisions-era-*.md, docs/development/roadmap.md -Pattern '\bBF-(\d{3})' -AllMatches → max 596
```
Wave 95 mints zero new AD/BF — no collision possible.

**Pytest baseline:**
```
.venv/Scripts/pytest.exe --collect-only -q tests/ → 12130 tests collected
```

**wave-plan.yaml W94 tail anchor:**
File ends with the W94 entry's `notes:` block. Last three lines confirmed:
```
      "AD-579: Memory Architecture umbrella close — tracker reconciliation
      (no-build, +0 tests)". Archive both prompts. gh issue close 37 with
      the canonical paragraph in Section 4 of the per-AD prompt.
```
W95 entry attaches to this tail.

## What This Does NOT Change

- **No source code touched.** Zero changes to `src/probos/`, zero changes to `tests/`, zero changes to `config/`, zero changes to `ui/`, zero changes to `data/`. Pure tracker-only reconciliation.
- **No new EventTypes, no new Pydantic config fields, no new database migrations, no new API endpoints, no new shell commands, no new HXI components.**
- **No new GH issues.** AD-652 has no sub-AD letters (it is a principle, not a discrete module). Realisation children are existing complete ADs cited as evidence, not new deferrals.
- **No `### AD-652` paragraph added to `decisions-era-4-evolution.md`.** Verified zero matches via grep — the canonical decision record lives at `DECISIONS.md:2253-2280` only. Era-4 has no AD-652 entry and Wave 95 does not create one.
- **No changes to AD-655 / AD-656 / AD-657 / AD-658 / AD-659 / AD-660 entries** in `roadmap.md`. They are already marked complete or v1 complete with AD-652 dependency satisfied — touching them is unnecessary churn.
- **No commercial scope.** AD-652 is purely OSS cognitive-architecture work. No tier-noun phrase, no pricing-token regex, no SaaS-overlay descriptor surface anywhere.

## Tracking

| Tracker | Change |
|---|---|
| `DECISIONS.md:2253-2280` | Status: `Design Principle (adopted)` → `Realised (Wave 95 close)`. Append `**Realised in:**` subsection. |
| `docs/development/roadmap.md:7105` | Bullet status: `*(Design Principle, OSS, Issue #302)*` → `*(Realised, OSS, Issue #302)*`. Append realisation child list. |
| `PROGRESS.md:331` | `AD-652 DESIGN PRINCIPLE (adopted).` → `AD-652 REALISED (Wave 95 close, 2026-05-07).` with one-line realisation summary. |
| `prompts/wave-plan.yaml` | Append W95 entry attached to W94 tail. |
| `decisions-era-4-evolution.md` | **Not touched.** Zero AD-652 matches in file (verified). Canonical record at DECISIONS.md only. |

## Acceptance Criteria

1. **Pytest gate.** `.venv/Scripts/pytest.exe -q -n 4 --dist=loadfile tests/` passes with **exactly 12130 tests** (zero delta from baseline). Any other count means an unrelated regression entered between draft and build — Builder hard-stops and surfaces back to Architect.
2. **Diff scope.** `git diff --stat` shows exactly 4 modified files: `DECISIONS.md`, `docs/development/roadmap.md`, `PROGRESS.md`, `prompts/wave-plan.yaml`. No source files changed, no test files changed, no config files changed.
3. **Pre-commit hook.** Hook runs naturally on commit and passes — banned-pattern audit must return zero hits across all 11 patterns on all three artefacts (this prompt + WAVE-95-DISPATCH.md + the wave-plan.yaml notes block).
4. **GH issue closure.** `gh issue close 302` runs cleanly with the canonical close paragraph (see Section 5 below).
5. **Era-4 untouched.** `git diff decisions-era-4-evolution.md` shows zero changes. Verify before commit.
6. **Engineering principles compliance.** Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`. (Trivially satisfied — no source changes.)

## Section 5 — GH Issue #302 Close Paragraph

After commit, run:

```
gh issue close 302 --comment "AD-652 Cognitive Code-Switching umbrella closed by Wave 95 (commit <SHA>). All six design principles realised across shipped child ADs at HEAD: AD-632 (unified pipeline substrate via SubTaskExecutor), AD-649 (channel→register inference, 5 communication contexts), AD-639 (chain trust band tenor weighting), AD-650 (analytical_reasoning depth field), AD-651 (StepInstructionRouter billet overlays), AD-651a (proposal + duty report compose billets), AD-647/AD-647c (process chains framework — variable depth + process-specific composition), AD-653 Layer 1 (speak-freely register shifting, trust-gated). Downstream consumers AD-655/AD-656/AD-657/AD-658/AD-659/AD-660 all complete and reference AD-652 modulation parameters. Tracker reconciliation only: DECISIONS.md:2253-2280 status flipped Design Principle (adopted) → Realised; docs/development/roadmap.md:7105 bullet flipped + realisation list appended; PROGRESS.md:331 status note flipped; prompts/wave-plan.yaml W95 entry appended. No code, no tests, no pytest delta (12130 → 12130). Structurally identical to W90 (#111 AD-462) and W94 (#37 AD-579) no-build umbrella closes. Research foundation: Levelt, Halliday, Giles, Snyder, Weick/Sutcliffe (cognitive-code-switching-research.md)."
```

Replace `<SHA>` with the commit hash from `git rev-parse HEAD`.
