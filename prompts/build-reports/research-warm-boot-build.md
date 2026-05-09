# Research warm-boot-fragmentation build report

**Prompt:** `prompts/research-warm-boot-fragmentation-design-v1.md`
**Builder:** Wave 130 builder
**Date:** 2026-05-08
**Status:** SHIPPED (DESIGN ONLY)
**Issue closed:** #501
**Wave:** 130 (10 of 10)
**AD assigned:** AD-717

## Files Changed

- `docs/research/warm-boot-fragmentation-design.md` (new) — full design doc.
- `DECISIONS.md` — AD-717 entry appended.

## Sections Implemented

- **D1.** Design doc with all required sections (Background / The design / Configuration shape / Event taxonomy / Out of scope / Status). Convention #14 carve-out callout for `warm_boot.enabled=true`. SHA-256 self-hash bound spelled out for checkpoint-resume.
- **D2.** DECISIONS.md entry with AD-717 assignment and forward markers AD-717-1/2/3.
- **D3.** No tests (per prompt).

## AD-numbering

Per the prompt's hard rule:
1. `Select-String "AD-7\d\d" PROGRESS.md DECISIONS.md docs/development/roadmap.md prompts/` showed highest existing AD = AD-716 (LoCoMo, just shipped this wave).
2. Warm-boot assigned AD-717.
3. Substituted every `<AD-NNN>` placeholder with AD-717 (and AD-717-1/2/3 for forward markers).

## Tests

No code; no new tests. Full gate runs unchanged.

## Hard Constraints Honored

- ✅ Zero production code.
- ✅ No HXI surface.
- ✅ No federation-side fragmentation.
- ✅ No cold-boot recovery.
- ✅ Convention #14 carve-out documented and bounded.
