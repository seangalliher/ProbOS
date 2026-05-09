# Review: RESEARCH — Warm-Boot Fragmentation (Design)
**Verdict:** ⚠️ Conditional
**Solid design content; AD-numbering hardcoded throughout the prompt body conflicts with the verify-first instruction.**

## Required (must fix before building)
1. **AD-713 is hardcoded in 5+ places** ("Implementation tracked as AD-713", "AD-713 — Warm-Boot...", "AD-713-1", "AD-713-2", "AD-713-3", `data/recovery/fragments-{timestamp}.json` mention is fine but the document body says "AD-713" as the assigned number). The prompt also instructs the Builder: "Builder verifies the actual highest AD number before assigning. The dispatch suggested AD-711; the actual number depends on..." — this contradicts the hardcoded body. Fix one of:
   - **Replace every literal `AD-713` / `AD-713-1/2/3` in the prompt body with `AD-NNN` / `AD-NNN-1/2/3` placeholders** and add a single explicit substitution rule at the top: "Builder runs `grep -r 'AD-' PROGRESS.md DECISIONS.md docs/development/roadmap.md prompts/ | grep -oE 'AD-[0-9]+' | sort -u | tail` to find the highest, assigns the next, and substitutes throughout the deliverables."
   - **Or pre-compute the next AD number now** (Architect runs the grep, pins the number, removes the verify instruction).
   The current state — both a verify rule AND a hardcoded number — is the AD-collision anti-pattern this convention exists to prevent.

## Recommended
1. Add the working-tree integrity reminder (convention #20). Even though this is a design-only prompt, the Builder still touches `DECISIONS.md` and a new doc file; a fragmented working tree could silently overwrite something.
2. `enabled: true` for the warm-boot config block is the documented exception (safety mechanism). Call out the exception **explicitly** in the prompt body — "this is the only `enabled: true` default in Wave 130; convention #14 is intentionally violated for safety-mechanism semantics." Otherwise a future Builder will copy the pattern as precedent.
3. H1's 30-day window threshold is conservative; H4's 60-second hash-chain drift threshold is aggressive. Document the reasoning gap so the implementation AD doesn't bikeshed both numbers from scratch.
4. "Recursive detection — bounded by checkpoint size, max one level" for `DreamCheckpoint` self-hash is good; spell out the bound formally (e.g., "the checkpoint's own SHA-256 is its only fragmentation witness; if it fails, the checkpoint is discarded as if it had never been written").

## Nits
- Section "Triage rules" mixes prose and lists — readable, but a 4-row table (fragment kind | classification | action) would scan faster.
- Sentinel and Reed lab-note attributions are nice flavor but not load-bearing — keep or drop consistently.
- DECISIONS.md entry text is paraphrasable; the prompt's exact wording is fine but the Builder may rephrase for grammar.

## Verified
- `src/probos/security/audit.py` AuditLog hash chain — claimed; not re-verified in this review pass (Architect cited at AD-456).
- `src/probos/substrate/event_log.py` EventLog hash chain — claimed shipped Wave 129 at `:14–32 _SCHEMA`, `:99–131 log()`. Trust Architect's prior pass.
- `src/probos/consensus/trust.py:91` `_event_log: deque[TrustEvent]` — actual line is `:128`. Same drift as AD-702. Tighten.
- `src/probos/types.py:580–593` `DreamCycleStats` — confirmed.
- `src/probos/types.py:358` `class AnchorFrame` — confirmed.
- No existing `recovery/`, `warm_boot/`, `fragmentation/` module — gap confirmed.
- Pure design AD; D3 explicitly says "no tests" — boundary correct.
- Out-of-scope list (cold-boot, federation-side, HXI surface) correctly defers each to its own future AD.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved
**Required #1 (AD-numbering self-conflict) landed; placeholder substitution rule pinned at top.**

### Required
None.

### Recommended
None new.

### Nits
None new.

### Verified Improvements (pass-2)
- ✅ **Required #1 (AD-numbering):** Zero AD-713 literals in normative content. The single residual AD-713 hit (line 165) is in the Revision Notes describing what was replaced. All forward references now use <AD-NNN>, <AD-NNN>-1, <AD-NNN>-2, <AD-NNN>-3 placeholders (12 placeholder hits).
- ✅ Explicit AD-numbering substitution rule pinned at the top of the prompt (lines 9–18) with grep instruction (grep -rE 'AD-[0-9]+' PROGRESS.md DECISIONS.md docs/development/roadmap.md prompts/), commit-message format, and substitution discipline.
- ✅ Working-tree integrity reminder in Acceptance section.
- ✅ All cited symbols (AD-456 audit hash chain, AD-490 EventLog hash chain, `TrustEvent` deque at 	rust.py:128, `DreamCycleStats`, `AnchorFrame`) verified at HEAD.

### Pass-2 outcome
Promoted from ⚠️ to ✅. Cleared for Builder dispatch (note: this is a design-only AD with no source code — the Builder commits the design doc + DECISIONS.md entry).
