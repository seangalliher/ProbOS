# Wave 148 — AD-723a-1 DM Consumer-Side Sensorium Dispatch Migration

**GH issue:** [#617](https://github.com/seangalliher/seangalliher/ProbOS/issues/617)
**Predecessor:** Wave 144 / AD-723 (producer-side dispatch, shipped commit 73cbd95)
**Successors filed at retrospective:**
- AD-723a-2 — WR branch consumer migration (deferred; Wave-10 entanglement rule applied — 15 fragments, exceeds 8 threshold)
- AD-723a-3 — position + wrapper metadata on `SensoriumEntry` (forcing function for full migration)

## One-line summary

Migrate the DM branch of `_build_user_message` so that AD-722's avatar self-observation and AD-722a's intent self-tag flow through the `SENSORIUM_REGISTRY` dispatch table instead of two hand-rolled method calls.

## Why this wave is small (Wave-10 entanglement applied)

Pre-flight grep against HEAD confirms:
- **DM branch:** 13 hand-rolled fragments. Only 2 entries produce self-wrapped output suitable for v1 migration (`_build_avatar_self_observation`, `_build_intent_self_tag_instruction`).
- **WR branch:** 15 hand-rolled fragments, 0 self-wrapped entries. **Deferred entirely to AD-723a-2.**

Other DM-tagged entries (`_sensorium_temporal_context`, `_sensorium_working_memory`, `_sensorium_self_recognition`) need DM-side framing markers that the registered methods don't emit — they migrate when AD-723a-3 lands position + wrapper metadata.

v1 ships the smallest viable consumer surface that proves the dispatch table is consumable end-to-end on DM path.

## Pre-flight gate

1. `git status` clean; HEAD at `bcc3209` (Wave 147) or later.
2. Full parallel gate green: `pytest tests/ -q -n 4 --dist=loadfile`. Baseline 13254/4-flake.
3. UI tests green.

## Per-prompt workflow

Single prompt. Execute `prompts/ad-723a-1-consumer-migration.md` end-to-end. Test gate after each section.

## Hard-stop conditions

- AD-722 prompt byte-parity breaks (any test in `test_ad722*` regresses).
- `_dispatch_sensorium_async` doesn't exist or doesn't have the expected signature — surface the grep and propose a fix.
- The single-call-site invariant test fails because `_build_avatar_self_observation(` or `_build_intent_self_tag_instruction(` is found in `_build_user_message` source after migration.

## Commit message format

```
AD-723a-1 (Wave 148): DM consumer-side sensorium dispatch migration

Closes #617. Migrates the DM branch of _build_user_message so AD-722's avatar
self-observation and AD-722a's intent self-tag flow through SENSORIUM_REGISTRY
dispatch instead of hand-rolled method calls. Defers WR branch to AD-723a-2
per Wave-10 entanglement rule (15 fragments, 0 self-wrapped entries).
```

## Tracking

- `PROGRESS.md` — close #617, update test count.
- `docs/development/roadmap.md` — mark AD-723a-1 row shipped, add AD-723a-2 + AD-723a-3 rows.
- `prompts/wave-plan.yaml` — Wave 148 entry status `shipped`.
- GH issue #617 — close with commit reference.
- File new GH issues for AD-723a-2 and AD-723a-3 at retrospective.
