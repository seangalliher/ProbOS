# Wave 146 Dispatch — AD-722a-7 Intent-Driven Voice Modulation Rules

**Status:** Ready for Builder
**Single AD in wave:** AD-722a-7 ([#624](https://github.com/seangalliher/ProbOS/issues/624))
**Spec:** `prompts/ad-722a-7-intent-modulation-rules.md`
**Priority:** Clinical-correctness (Counselor flagged 2026-05-10) — jumps ahead of other AD-722a sub-markers.
**Estimated new tests:** +14 net (≥10 happy paths per the spec + 4 layering/clamp/parity/unknown-fallback). 31 existing AD-722a tests migrate to new taxonomy in-place.
**Estimated commits:** 1 (single AD, no sub-ADs).

## What this wave does

Closes the loop AD-722a (Wave 143) opened. AD-722a installed the **detector** that compares the LLM's `<intent emotion=NAME>` self-tag against `apply_voice_modulation`'s `fired_rules`. The detector immediately surfaced a real divergence: idle, trust-stable replies declared `warm` but came back as `no_rules_fired`. The detector was correct — there are no modulation rules keyed off intent, only off operational state. AD-722a-7 ships the missing **actuator**.

Captain rulings 2026-05-10 (incorporated into the spec):
- **Taxonomy migration accepted.** AD-722a-7 supersedes the AD-722a v1 taxonomy (`warm/firm/warm_concern/alert/neutral/playful/thoughtful/apologetic`) with a clinical-correctness-focused 8 (`warm/concerned/excited/apologetic/formal/playful/reassuring/neutral`).
- **`INTENT_EXPECTED_RULES` retires operational mappings.** Match score is computed against the `intent_*` namespace only. Operational rules become informational.

## What this wave does NOT do

- Per-agent custom emotion taxonomy ([#612 AD-722a-3](https://github.com/seangalliher/ProbOS/issues/612))
- Multi-emotion blending (`intent=warm+concerned`)
- Auto-recalibration from Counselor's divergence corpus (forward marker — v1 ships hard-coded table values)
- Updating agent prompts to *prefer* declaring intent — encouragement is separate AD-489 work
- Vision-LLM intent-divergence ([#610 AD-722a-1](https://github.com/seangalliher/ProbOS/issues/610))
- Chain-path divergence ([#611 AD-722a-2](https://github.com/seangalliher/ProbOS/issues/611))

## Pre-flight gate

1. `git status` clean; `git log -1 --oneline` reads `a3d5320 wave-plan: queue Waves 146-150 ...` (or later main HEAD).
2. Full parallel gate green: `pytest tests/ -q -n 4 --dist=loadfile`. Capture baseline test count.
3. UI tests green: `cd ui && npx vitest run` (Vitest available; the cluster's modulation manifest tests live here).

## Per-prompt workflow

Single prompt. Execute `prompts/ad-722a-7-intent-modulation-rules.md` end-to-end. Standard test gate after each section.

## Hard-stop conditions

- Manifest schema validator (`_load_modulation_manifest()` at telemetry.py L106-L150) rejects the new `intent_rules` key. **This is the precondition — the spec explicitly extends the validator. If the Builder skips Section 1, all later sections crash at import.**
- 31 existing AD-722a tests cannot be migrated cleanly to the new taxonomy. The spec lists the exact edits; if a test resists migration, surface to Architect.
- Byte-parity contract between Python and TS readers breaks. Both consumers MUST produce identical `fired_rules` orderings and identical clamped factors for the same intent.

## Verified-against-codebase footer

See spec footer. Pre-flight grep evidence captured 2026-05-10.

## Commit message format

```
AD-722a-7 (Wave 146): intent-driven voice modulation actuator + 8-emotion taxonomy migration

Closes #624. Adds intent_rules section to ui/src/audio/modulation_manifest.json
(8 emotions: warm/concerned/excited/apologetic/formal/playful/reassuring/neutral).
Layers intent factors on top of operational rules; clamps to PITCH/RATE/VOLUME
bounds; ModulationSnapshot.fired_rules carries both rule families. Migrates
AD-722a EmotionalIntent enum + INTENT_EXPECTED_RULES + INTENT_DIRECTION +
system-prompt vocabulary to new 8-emotion set. Tests: +N (gate: <count>).
```

## Tracking

- `PROGRESS.md` — mark #624 closed.
- `docs/development/roadmap.md` Counselor / AD-722 cluster — note actuator shipped.
- `DECISIONS.md` — append AD-722a-7 closure status block; cross-reference the "what agents do under constraint becomes the template" principle from the 2026-05-10 retrospective.
- GH issue #624 — close with commit reference.
- Forward markers preserved: #610, #611, #612, #613, #614, #615 stay open.
