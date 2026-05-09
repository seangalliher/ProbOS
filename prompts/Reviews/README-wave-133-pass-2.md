# Wave 133 — Review Pass-2 Summary

**Date:** 2026-05-08
**Reviewer:** Architect (pass-2)
**Tolerance budget (convention #15, relaxed):** 1 ⚠️ permitted on highest-risk prompt — **unused**.

## Per-prompt verdicts

| Prompt | Pass-1 | Pass-2 | Required | Recommended | Nits |
|---|---|---|---|---|---|
| [ad-718-profile-voice-chat-v1](./ad-718-profile-voice-chat-v1-review.md) | ✅ Approved | ✅ Approved (ratified) | 0 | 0 | 0 |
| [ad-721-3d-crew-avatars-v1](./ad-721-3d-crew-avatars-v1-review.md) | ⚠️ Conditional | ✅ Approved (upgraded) | 0 | 0 | 0 |

**Wave status:** ✅ **APPROVED for Builder dispatch (gate-1).** Zero Required, zero Recommended, zero Nits across both prompts. The 1-⚠️ tolerance is unused.

## Pass-2 bar

Wave 130 lesson: Pass-1 fixes can land in the Revision Notes section of a prompt without a corresponding body edit, leaving the normative spec stale. Pass-2 must verify each Pass-1 finding maps to a **body** location, not just the Revision summary.

| Pass-1 finding | Body location | Verified |
|---|---|---|
| AD-718 Rec #1 (line drift, "around line N") | Top + bottom grep blocks, Verified bullets | ✅ |
| AD-718 Rec #2 (D4 wiring) | D4 closing paragraph (~L218–L221) | ✅ |
| AD-718 Rec #3 (D7 `currentProfile`) | D7 React state snippet (~L358–L368) | ✅ |
| AD-718 Nit #1 (`pulse-mic` keyframe) | D6 (~L334) + Verified bullet (~L42) | ✅ |
| AD-721 Rec #1 (FakeAnalyser sketch) | D5 TypeScript sketch (~L267–L307) | ✅ |
| AD-721 Rec #2 (D8 enabled-flag fork) | D8 closing paragraph (~L359) | ✅ |
| AD-721 Rec #3 (line drift on `AgentProfilePanel.tsx`) | Verified bullets (~L34, L36) + bottom grep (~L444–L449) | ✅ |
| AD-721 Rec #4 (D6 `system.py:590` reference) | D6 Builder-note (~L325) | ✅ |

## Three grep self-checks (requested in dispatch)

| Check | Expected | Actual at HEAD | Status |
|---|---|---|---|
| AD-718 line drift (`1466-1521` should NOT be in normative content; should be `1467-1522`) | Stale ranges absent from normative body | `1466-1521` appears only inside the Revision Notes section (legacy reference at L542); normative content (L42, L334) uses `1467-1522`. | ✅ |
| AD-718 line drift (`188-202` should be `196-207`) | Stale range absent from normative body | `188-202` appears only inside the Revision Notes section (L542); normative content (L41, L159, L179) uses `196-207`. | ✅ |
| AD-721 line drift (`DEPT_COLORS 21` → `~20`; `isCrew 97` → `~92`) | Updated to "around line 20" / "around line 92" | L34 reads "around line 20"; L36 reads "around line 92"; bottom grep block (L444–L449) shows actual HEAD lines 20, 91, 92, 95, 206. | ✅ |

## Phantom-API spot-check (HEAD 2026-05-08)

| Asserted | HEAD | Status |
|---|---|---|
| `CrewProfile` at `crew_profile.py:116` | line 116 | ✅ |
| `speakResponse` at `audio/voice.ts:49` | line 49 | ✅ |
| `IntentSurface.tsx` mic JSX 1467–1522 | confirmed | ✅ |
| `@react-three/fiber` in `ui/package.json` | line 15 | ✅ |
| `@pixiv/three-vrm` in `ui/package.json` | absent — **correct**, D1 introduces it | ✅ |

No phantom APIs. No new defects surfaced in pass-2.

## Cross-prompt ordering reminder (unchanged from Pass-1)

1. **AD-718 must merge before AD-721 tests run.** AD-721 D5 imports `onSpeechEvent` from AD-718 D1. AD-721 D2 inserts `AppearanceProfile` immediately after `VoiceProfile` added by AD-718 D3. Both prompts spell this out in Acceptance.
2. **`routers/agents.py:profile_data` dict** — AD-718 D5 adds `"voiceProfile"`; AD-721 D5 adds `"appearance"`. AD-721's SEARCH/REPLACE blocks must be written against post-AD-718 state.
3. **`crew_profile.py:CrewProfile` dataclass** — AD-718 lands first; AD-721 amends `to_dict`/`from_dict` after AD-718's edits land.

## Recommended Builder pre-flight

Before starting AD-718:

1. **Working-tree integrity check.** Run `git diff --numstat | sort -k2nr | head -5`. If anything other than expected staged work appears, stop and surface to user (2026-05-08 lesson).
2. **AD numbering re-verification.** Confirm AD-718 and AD-721 are still the next sequential slots tied to issues #512 and #515. If a hotfix wave consumed them, reassign before commit.
3. **Confirm `voiceEnabled` initial state in `useStore.ts`** is still `false` (AD-718 piggybacks rather than introducing a new flag).

Before starting AD-721:

1. **Confirm AD-718 has merged** (`git log --oneline | grep "AD-718"`); abort if not.
2. **D6 `ui://` resource handler grep.** `grep -n "ui://" src/probos/routers/system.py` to find the existing pattern and mirror its auth/middleware path. The prompt no longer asserts a line number — the grep IS the spec input.
3. **D8 enabled-flag fork resolution.** `grep -rn "/api/config\|/api/flags\|/api/system/config" src/probos/routers/`. If a config-flag GET endpoint exists, append `avatars_enabled: bool` to its response shape. If none exists, add the dedicated `GET /api/config/avatars-enabled` route per D8. Do NOT design new generic config-API surface.
4. **`@pixiv/three-vrm` install.** Confirmed absent from `ui/package.json` at HEAD — D1 must add it (`@pixiv/three-vrm@^2`, MIT). Run `cd ui && npm install` after the package.json edit lands.
5. **`data/avatars/` directory.** Does not exist at HEAD — D2 creates it with `.gitkeep`. Confirm `.vrm` glob is added to `.gitignore`. v1 ships **no** `.vrm` binaries.

## Wave dispatch decision

**APPROVED.** Both prompts pass Pass-2 with zero open findings. Builder may proceed in the order:
1. AD-718 (commit, gate-2 tests, merge).
2. AD-721 (commit, gate-2 tests, merge).
3. Gate-3 forward-marker GH issues filed for both per BUILDER-EXECUTION-PLAN Post-Sweep step 6.

If Builder hits a hard-stop, surface immediately per the standard hard-stop conditions in `BUILDER-EXECUTION-PLAN.md`. The 1-⚠️ tolerance budget remains unused and is available for the next prompt the wave-orchestrator dispatches.
