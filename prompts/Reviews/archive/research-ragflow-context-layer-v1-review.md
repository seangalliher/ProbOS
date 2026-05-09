# Review: RESEARCH — RAGFlow Context-Layer Absorption
**Verdict:** ✅ Approved
**Well-bounded research-tier prompt; doc + 1 of 3 artifact options; opt-in test default keeps the gate fast.**

## Required (must fix before building)
_None._

## Recommended
1. Add the working-tree integrity reminder (convention #20).
2. D2's choice criterion ("Builder picks (a) unless ... then (b) ... then (c). Default = (a)") is good, but the doc must record the decision. Add a one-line rule: "Section 6 of the absorption doc MUST state which artifact was chosen and why."
3. The four "absorbable" patterns (DeepDoc, template chunking, fused re-rank, grounded citation) are pre-named by Architect. Builder's section 4 (Absorption Candidates) should be free to add or drop candidates based on what they find in the upstream source — the prompt currently reads as if the four are mandatory. Soften: "at least these four; Builder may add more."
4. The artifact-(b) benchmark stub measures "RAGFlow's published template_chunking boundary heuristics" — but Architect hasn't fetched those heuristics. Either drop (b) as an option or instruct the Builder that picking (b) requires an additional upstream fetch beyond what Architect did.

## Nits
- 80k★ is high — repository-quality risk is low, but worth checking the most-recent commit date in the absorption doc.
- "ragflow-followup-stubs.md" name in (c) is fine; mirror the doc-stem convention used elsewhere if there's a house style.

## Verified
- `src/probos/cognitive/episodic.py:2509` `recall_weighted` — confirmed.
- `src/probos/cognitive/episodic.py:1755` `recall_by_anchor_scored` — confirmed.
- `src/probos/types.py:391–395` source-provenance anchor fields — confirmed (within the verified `AnchorFrame` block at `:358`).
- No existing `deepdoc/`, `chunking/`, `parsing/`, `ingest/` modules — gap confirmed.
- Doc deliverable + 1 concrete artifact (a/b/c) + opt-in default → satisfies the dispatch's research-tier rules.
- "grep before asserting any equivalence" hard-constraint correctly cites Wave 5 convention #4.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved
**Pass-1 had 0 Required; pass-2 confirms cross-cutting items landed.**

### Required
None.

### Recommended
None new.

### Nits
None new.

### Verified Improvements (pass-2)
- ✅ Working-tree integrity reminder added to Acceptance. No config.py touch — no Build Ordering Note required.
- ✅ No phantom-API regressions introduced.
- ✅ All previously-verified symbols still match HEAD.

### Pass-2 outcome
Held at ✅. Cleared for Builder dispatch.
