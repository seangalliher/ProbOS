# Wave 133 — Review Pass-1 Summary

**Date:** 2026-05-08
**Reviewer:** Architect (pass-1)
**Tolerance budget (convention #15, relaxed):** 1 ⚠️ permitted on highest-risk prompt.

## Per-prompt verdicts

| Prompt | Verdict | Required | Recommended | Nits |
|---|---|---|---|---|
| [ad-718-profile-voice-chat-v1](./ad-718-profile-voice-chat-v1-review.md) | ✅ Approved | 0 | 3 | 2 |
| [ad-721-3d-crew-avatars-v1](./ad-721-3d-crew-avatars-v1-review.md) | ⚠️ Conditional | 0 | 4 | 2 |

**Wave status:** ✅ **On track for review pass-2 after one revision cycle.** AD-721's ⚠️ is within the 1-allowed budget for the wave's highest-risk prompt (MEDIUM per the drafting report). Zero Required findings on either prompt.

## Cross-prompt concerns

1. **AD-718 → AD-721 ordering (headline).** AD-721 D5 imports `onSpeechEvent` from AD-718 D1; AD-721 D2 inserts `AppearanceProfile` "immediately after `VoiceProfile`" added by AD-718 D3. Both prompts spell this out:
   - AD-718 Acceptance: "AD-721's `CrewAvatarPopout` (next AD in the wave) can subscribe via `onSpeechEvent` and receive `start`/`end` events keyed on `agent_id`."
   - AD-721 Acceptance: "AD-718 must be merged before AD-721's tests run; if not, surface and stop."
   - Source-layout dependency in AD-721 D2 enforces ordering at the file level.
   ✅ No revision needed; Builder will land AD-718 first.

2. **Both prompts edit `routers/agents.py`'s `profile_data` dict at the same site** (AD-718 D5 adds `"voiceProfile"`, AD-721 D5 adds `"appearance"`). Builder must apply AD-718's edit first; AD-721's diff will show both keys when generated — confirm SEARCH/REPLACE blocks are written against the post-AD-718 state.

3. **Both prompts edit `crew_profile.py`'s `CrewProfile` dataclass at the same site** (`to_dict`, `from_dict`, `field(...)` declaration). Same ordering principle. AD-718 lands first.

4. **Working-tree integrity check** present in both Acceptance sections. Pre-flight `git diff --numstat | sort -k2nr` is the canonical first action per the 2026-05-08 lesson; both prompts honour it.

5. **AD-numbering re-verification at commit time** present in both. Wave 132 closed at AD-706a..f forward markers; AD-718 and AD-721 occupy slots tied to issues #512 and #515. Both Acceptance sections instruct re-verification.

## Phantom-API spot-check (HEAD verified 2026-05-08)

| Asserted | Actual at HEAD | Status |
|---|---|---|
| `CrewProfile` at `crew_profile.py:130` | line 116 | Drift (Recommended) |
| `ProfileStore` at `crew_profile.py:215` | line 215 | ✅ |
| `ProfileStore.get_or_create(agent_id, agent_type, pool, **defaults)` | line 251, signature matches | ✅ |
| `ProfileStore.update(profile)` | line 269 | ✅ |
| `voice.ts:speakResponse` at line 53 | line 49 | Drift (Recommended) |
| `voice.ts:findPreferredVoice` at line 35 | line 6 | Drift (Recommended) |
| `voice.ts:getAvailableVoices` at line 72 | line 72 | ✅ |
| `voice.ts:setPreferredVoiceName` at line 77 | line 77 | ✅ |
| `IntentSurface.tsx` strip pipeline `188–202` | lines 196–207 | Drift (Recommended) |
| `IntentSurface.tsx` mic JSX `1466–1521` | lines 1467–1522 | ✅ |
| `IntentSurface.tsx:7,8` voice/speechInput imports | lines 7,8 | ✅ |
| `useStore.ts:597` `voiceEnabled: false` initial | confirmed | ✅ |
| `routers/agents.py:40` `GET /{agent_id}/profile` | line 40 | ✅ |
| `routers/agents.py` `profile_data` dict | line 110 (prompt says 117) | Drift (Recommended) |
| `routers/agents.py:166` `POST /{agent_id}/chat` | line 166 | ✅ |
| `runtime.registry.get(agent_id)` | confirmed at lines 43, 153, 169, 369, 408 | ✅ |
| `agent.id`, `agent.agent_type`, `agent.pool` | `substrate/agent.py:33,34,35` | ✅ |
| `@react-three/fiber`, `three` in `ui/package.json` | lines 15, 21 | ✅ |
| `@pixiv/three-vrm` absent from package.json (must be added) | absent | ✅ |
| `AgentProfilePanel.tsx:21` `DEPT_COLORS` | line 20 | Drift (Recommended) |
| `AgentProfilePanel.tsx:97` `isCrew` | line 92 | Drift (Recommended) |
| `data/avatars/` directory | does not exist; D2 creates with `.gitkeep` | ✅ |
| `McpAppFrame` (AD-706 phantom) | does not exist; popout renders directly in React tree | ✅ |
| 15 `agent_type` stems in `config/standing_orders/crew_profiles/` | all 15 confirmed | ✅ |

**No phantom APIs.** All non-✅ rows are line-number drift, not missing entities. Per `review-criteria.md` §6 ("Line numbers are approximate: state 'around line N'"), drift is Recommended-tier.

## Six surfaced contradictions — disposition

| # | Contradiction | Documented in body | Resolution shipped |
|---|---|---|---|
| 1 | `profile_store.py` doesn't exist; schema is `CrewProfile` in `crew_profile.py:130` | ✅ AD-718 §Verified + AD-721 §Verified | ✅ Both prompts edit `crew_profile.py` |
| 2 | `speechInput.ts` lives at `ui/src/audio/`, not `ui/src/voice/` | ✅ AD-718 §Verified | ✅ Imports use `'../../audio/speechInput'` |
| 3 | `data/avatars/` doesn't exist + OSS can't ship VRMs | ✅ AD-721 §Verified + Dispatch contradictions | ✅ Parametric Three.js fallback in `ParametricAvatar.tsx` |
| 4 | `voice.ts:speakResponse` hardcodes pitch/rate/volume | ✅ AD-718 §Verified | ✅ D1 extends signature with optional profile (preserves v0 callers) |
| 5 | IntentSurface line ranges (188-202 strip, 1466-1521 mic) | ✅ AD-718 §Verified | ⚠️ Strip range still drifts ~10 lines (Recommended in AD-718 review) |
| 6 | `McpAppFrame` phantom from AD-706 | ✅ AD-721 §Verified | ✅ Direct React-tree rendering, no iframe |

## Recommended next step

Forward both reviews to drafting Architect for one revision cycle. Expected revisions are mechanical:
- Replace asserted line numbers with "around line N" in both prompts' body and grep blocks (or refresh the greps against current HEAD).
- Tighten AD-718 D4 wiring to point at D5's `routers/agents.py` consumption instead of `load_seed_profile_async`.
- Sketch the `_attachAnalyserOrSchedule` fake-AnalyserNode interface in AD-721 D5.
- Pre-flight-resolve AD-721 D8's enabled-flag plumbing path before build.

Pass-2 should converge.
