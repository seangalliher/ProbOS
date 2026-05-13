# Wave 154 — Pass-1 Review Summary

**Reviewer:** Architect. **Date:** 2026-05-12. **Pass:** 1.
**Scope:** 4 prompts (AD-722b-1 deferred from this wave per dispatch scope-reduction note).

## Verdict matrix

| # | Prompt | Verdict | Required findings | One-line justification |
|---|---|---|---|---|
| 1 | [ad-724-dm-hardening.md](../ad-724-dm-hardening.md) | ⚠️ Conditional | 1 | Duplicate `DmSanityGateConfig` class (one in `dm_sanity_gate.py:49`, one in `config.py:3236`) — prompt only edits the config.py copy; existing tests construct from the dm_sanity_gate.py copy and will `AttributeError` on the new field reads inside `process()` / `check_repetition`. |
| 2 | [ad-730-1-1-drag-paste-image.md](../ad-730-1-1-drag-paste-image.md) | ✅ Approved | 0 | Small UI-only addition; mirrors a verified IntentSurface paste pattern; existing `uploadAttachment` helper reused intact. |
| 3 | [ad-720d-1-multi-image-batch.md](../ad-720d-1-multi-image-batch.md) | ⚠️ Conditional | 2 | (a) Phantom config class name `AttachmentConfig` — actual class is `AttachmentsConfig` (plural) at `config.py:1112`; (b) third caller `routers/agents.py:914` of `build_multimodal_messages` missing from verification footer and Section 2 — first vision DM after commit raises `ValueError: too many values to unpack`. |
| 4 | [ad-719-718-hxi-polish.md](../ad-719-718-hxi-polish.md) | ✅ Approved | 0 | Two small UI polish items; both upstream signals (`pickerIndex` state machine, `onSpeechEvent` global registry) verified stable; HXI Design Principles compliant. |

**Total Required findings across the wave: 3** (1 in AD-724, 2 in AD-720d-1, 0 in the two ✅ prompts).

## Highest-risk identification

**AD-720d-1** is highest-risk and must be the focus of the revision pass:

1. It changes the **return arity** of `build_multimodal_messages` — a function the wave-153 vision arc has touched 9 times in 48 hours (BF-268 through BF-277). Any signature drift across the 3 callers regresses the entire vision pipeline.
2. The verification footer **undercounted** callers (2 of 3) — the same class of defect that produced the BF-274 → BF-278 vision regression chain (prompt assertions drifting from HEAD).
3. The phantom config class name (`AttachmentConfig` vs actual `AttachmentsConfig`) is the third recurrence of phantom-API class-name-shape defects in this codebase (`DutyConfig`/`DutyScheduleConfig` precedent in user-memory). Pre-check script does not yet validate Pydantic class names against config.py grep — known gap.
4. AD-734 wire-shape contract test is acknowledged-by-design to NOT catch signature drift. The Builder must update all 3 callers in the same commit; without the verification footer fix, this is left to Builder vigilance.

AD-724 is also ⚠️ but lower risk — its defect (duplicate class) is a unit-test surface that fails fast and loud on the focused gate; AD-720d-1's defect surfaces only on the first multi-image DM after the commit lands, which may be hours after the green test gate.

**Wave 5-7 convention #15** allows 1 ⚠️ on the highest-risk prompt only. We have 2 ⚠️. Both must be revised before Builder dispatch.

## Cross-prompt concerns

1. **`routers/agents.py` shared by AD-724 and AD-720d-1.** AD-724 modifies the DM sanity-gate region (lines 1106-1145). AD-720d-1 modifies the vision-branch destructure (line 914) and an unspecified episodic-write site in the ~1100-1220 range. The dispatch claim "no two prompts touch the same lines" is unverified for AD-720d-1's episodic-write site. **Action for revision:** AD-720d-1 must pin the episodic-write line range (and explicitly skip lines 1106-1145 if it falls in that span).

2. **`config.py` shared by AD-724 and AD-720d-1.** Different classes (`DmSanityGateConfig` vs `AttachmentsConfig`), no line collision. Safe to land in either order.

3. **No UI-prompt collisions.** AD-730-1-1 touches `WardRoomThreadDetail.tsx`; AD-719/718 touches `IntentSurface.tsx` + new files. Independent.

4. **No collisions with the in-flight vision-pipeline files** (`vision_dispatch.py`, `llm_client.py`) outside what AD-720d-1 owns. The AD-734 pre-commit hook will fire on AD-720d-1's commit and verify the wire-shape invariant survives the signature change.

## Phase ordering audit (review-criteria #10)

None of the four prompts add finalize-phase services or fields to startup `Result` dataclasses. AD-724-5's `apply_dm_sanity` reads `getattr(runtime, "dm_sanity_gate", None)`, where the gate is wired in `RuntimeOS.__init__` at runtime.py:567-570 (constructor-time, before any startup phase consumes it). AD-720d-1 reads `runtime.config.attachments` (Pydantic-loaded config, available pre-Phase-2). UI prompts have no Python startup surface. **No phase-order traps.**

## Recommendation

**PROCEED to revision stage** (apply Required findings).

No architectural problems found. All Required findings are spec-fix corrections — the prompts revise to ~10-20 lines of changed text each:

- **AD-724:** add the same three new fields to the `dm_sanity_gate.py` `DmSanityGateConfig`, OR delete the duplicate and have it import from `probos.config`. Update Files-to-Modify table to reflect the chosen path.
- **AD-720d-1:** (a) rename `AttachmentConfig` → `AttachmentsConfig` everywhere (Files-to-Modify, Section 3, verification footer); (b) add `routers/agents.py:914` as an explicit destructure site in Section 2; (c) update the verification footer's `build_multimodal_messages` grep block to list all 3 callers; (d) pin the agents.py episodic-write line range and explicitly skip the AD-724 sanity-gate region.

After revision, run pass-2 review and confirm both ⚠️ become ✅. Builder dispatch follows.

## Standing-rule reminders for the Builder (post-revision)

- Test gate full: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`.
- AD-734 pre-commit hook will fire on the AD-720d-1 commit — **do not bypass with `--no-verify`**.
- Working tree: surface unidentified tracked-file modifications; do not `git stash` / `git reset --hard`.
- Inline-blob anti-pattern: per-attachment timing fields stay small; no base64 in `IntentMessage.params`.
- One commit per AD; commit-message format `AD-NNN(x): <summary> (Wave 154)` with `Closes #NNN`.

