# Review: AD-718 v1 — Voice in 1:1 Profile Chat
**Verdict:** ✅ Approved (Pass 2 — ratified)
**Pass 1: ✅ Approved with 3 Recommended + 2 Nits. Pass 2: all 5 resolved in body (not just Revision Notes). Ready for Builder dispatch.**

## Required (must fix before building)

_None._

## Recommended (should fix)

1. **Line-number drift in `Verified Against Codebase` and body prose.** The trailing grep-evidence block claims `speakResponse` at `voice.ts:53` and `findPreferredVoice` at `:35`; actual HEAD is `speakResponse` at `voice.ts:49` and `findPreferredVoice` at `voice.ts:6`. Body prose elsewhere claims hardcoded `rate/pitch/volume` at "lines 60–62" (actual 57–59) and `cachedVoice` at "lines 30,82" (actual 4/7/18/37/44/78). The `IntentSurface.tsx` strip pipeline is asserted at "188–202" but actually runs `196–207` (cleanText assignment through `speakResponse(cleanText)`). Mic JSX range `1466–1521` is correct (verified ~1467–1522). Per `review-criteria.md` §6, switch to "around line N". This is drift, not phantom — Builder will adapt, but the grep block presents itself as ground truth and isn't.

2. **D4 wiring story is fuzzy and points at the wrong layer.** D4 says "Wire the seed in `crew_profile.py`'s `load_seed_profile_async` (or the closest equivalent that hydrates `CrewProfile` from YAML)." Verified at HEAD: `load_seed_profile_async` (`crew_profile.py:434`) returns a raw `dict[str, Any]`; there is **no** central CrewProfile-from-YAML hydration path. The personality field is read by consumers directly (`routers/agents.py:67`, `cognitive/qualification_tests.py:251`). The clean wiring point is **D5 itself** (`routers/agents.py:117` → call `default_voice_for(agent.agent_type)` when no live `runtime.profile_store` entry exists). Tighten D4 to say "the helper is consumed in D5 below and at any future ProfileStore-creation site; no edit to `load_seed_profile_async` is needed in v1."

3. **D7 voice picker — `currentProfile` is undefined in the snippet.** "Test" button calls `speakResponse("This is how I sound.", currentProfile)` but `currentProfile` is never declared. Builder will trivially thread the local state, but the snippet should show the source — minor spec gap.

## Nits

1. The `pulse-mic` keyframe lives at `IntentSurface.tsx:1631` (a single `@keyframes` block at the bottom of the file). D6 says "copy the JSX verbatim" but doesn't remind Builder to also copy the keyframe into a shared CSS module or `ProfileChatTab`'s style block. Without it, the listening pulse silently no-ops.

2. The 15 default-voice mappings reference `agent_type` stems — verified all 15 exist in `config/standing_orders/crew_profiles/` (counselor, security_officer, diagnostician, pathologist, surgeon, pharmacist, architect, data_analyst, research_specialist, systems_analyst, scout, builder, engineering_officer, operations_officer, training_officer). The flavor comments ("Troi", "Worf", "Wesley") are personal taste — fine.

## Verified

- `voice.ts:speakResponse` exists with the asserted signature; v0 hardcodes pitch/rate/volume — D1 extension preserves source compatibility.
- `voice.ts:findPreferredVoice`, `cachedVoice`, `setPreferredVoiceName` exist; D1's `_resolveVoiceByName` correctly avoids cache pollution.
- `speechInput.ts:isSpeechRecognitionSupported`, `startListening`, `stopListening` exist at the asserted symbols; live in `ui/src/audio/`, not `ui/src/voice/` (contradiction #2 documented).
- `IntentSurface.tsx` imports + voiceEnabled wiring + mic JSX surface confirmed at HEAD.
- `crew_profile.py`: `class CrewProfile` (line 116, prompt says 130 — drift), `class PersonalityTraits` (line 51, prompt says 53 — close), `class ProfileStore` (line 215 ✅), `to_dict`/`from_dict` (lines 169/190). Dataclass+nested+to_dict/from_dict pattern is the right precedent.
- `ProfileStore.get_or_create(agent_id, agent_type, pool, **defaults)` and `update(profile)` exist with matching signatures — D8 is structurally sound.
- `routers/agents.py:43`, `:153`, `:169` use `runtime.registry.get(agent_id)` — D8 phantom-API check passes.
- `routers/agents.py:67` reads `seed.get("personality", {})` — D5 fallback pattern matches.
- `useStore.ts`: `voiceEnabled: false` initial; no store changes needed (default-False piggyback is honest).
- `ProfileChatTab.tsx:58` — `addAgentMessage(agentId, 'agent', data.response || '(no response)')` confirmed; `'(communication error)'` at :60 confirms the `startsWith('(')` TTS filter.
- Cross-AD: D1 introduces `onSpeechEvent`/`SpeechEvent`/`SpeechEventType` exports that AD-721 D5 consumes. Listener registration is Tier-2 log-and-degrade (try/except per listener) — correct.
- Forward markers AD-718a–f present with gate-3 issue-filing instruction.
- Working-tree integrity bullet present in Acceptance.
- AD-numbering re-verification line present.
- All four contradictions involving AD-718 (#1 profile_store→crew_profile, #2 audio path, #4 hardcoded values, #5 IntentSurface ranges as "approximate") are documented in the body.
- License hygiene: N/A for AD-718.
- Default-False: piggybacks on existing `voiceEnabled=false`. ✅


## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved — ready for Builder dispatch.
**Required: 0. Recommended: 0. Nits: 0.**

Pass-2 bar (Wave 130 lesson): every Pass-1 finding must land in the prompt **body**, not just the Revision Notes section. Spot-checked all 5 below.

### Pass-1 findings — body landings verified

| # | Pass-1 finding | Body landing | Verified |
|---|---|---|---|
| Rec #1 | Line-number drift / "around line N" notation | Top grep block (body L13–L20), Verified bullets (body L23–L46), bottom grep block (body L468–L513). All references are now `speakResponse` ~49, `findPreferredVoice` ~6, hardcoded utterance fields ~56–58, `cleanText` strip ~196–207, mic JSX ~1467–1522, `@keyframes pulse-mic` ~1631, `CrewProfile` ~116, `PersonalityTraits` ~51, `profile_data = {` ~110, `set_agent_proactive_cooldown` ~151. | ✅ |
| Rec #2 | D4 wiring fuzzy (`load_seed_profile_async`) | D4 closing paragraph (body L218–L221) explicitly states `load_seed_profile_async` returns a raw dict, no central CrewProfile-from-YAML hydration path exists at HEAD, and **no edit to it is needed in v1**. Helper is consumed at the D5 site. | ✅ |
| Rec #3 | D7 `currentProfile` undeclared | D7 (body L358–L368) declares `const [currentProfile, setCurrentProfile] = useState<VoiceProfile>(...)` initialised from `profileData?.voiceProfile`; sliders/dropdown call `setCurrentProfile`; Test button calls `speakResponse(`This is how I sound.`, currentProfile)`. | ✅ |
| Nit #1 | `@keyframes pulse-mic` reminder | D6 (body L334) and Verified bullet (body L42) both instruct copying the keyframe block into `ProfileChatTab.tsx` (inline `<style>` or shared CSS module) — without it the listening pulse silently no-ops. | ✅ |
| Nit #2 | 15 voice mappings verified | No body change required (verification noted in Pass 1). | ✅ |

### Grep self-check

```
=== AD-718 line drift checks (stale ranges should NOT appear in normative content) ===
  L41:  cleanText pipeline at "around lines 196–207"          (was 188–202 — drift fixed)
  L42:  mic JSX at "around lines 1467–1522"                   (was 1466–1521 — drift fixed)
  L159: cleanText pipeline at "around lines 196–207"          ✅
  L179: cleanText pipeline at "around lines 196–207"          ✅
  L334: mic JSX at "around lines 1467–1522"                   ✅
  L542: appears only inside the Revision Notes section        ✅ (legacy ranges historical)

=== AD-718 D7 currentProfile body hits ===
  L358: "Test" button — calls speakResponse(..., currentProfile)
  L361: const [currentProfile, setCurrentProfile] = useState<VoiceProfile>({
  L367: // sliders/dropdown call setCurrentProfile(p => ({ ...p, pitch: newValue }))
  L368: // Test button: speakResponse("This is how I sound.", currentProfile)
```

All body hits confirm Pass-1 fixes landed structurally, not just in Revision Notes.

### Phantom-API spot-check (HEAD 2026-05-08)

| Asserted | HEAD | Status |
|---|---|---|
| `CrewProfile` at `crew_profile.py` ~116 | line 116 | ✅ |
| `ProfileStore` at `crew_profile.py` ~215 | line 215 | ✅ |
| `speakResponse` at `audio/voice.ts` ~49 | line 49 | ✅ |
| `IntentSurface.tsx` mic JSX ~1467–1522 | confirmed | ✅ |
| `ui/src/audio/speechInput.ts` (NOT `ui/src/voice/`) | confirmed | ✅ |

### Residual concerns

None. The remaining drift surface (`MagicMock/` test fixtures, `ui/src/audio/__tests__/` paths) is introduced by D9 and is not pre-existing.

### Pass-2 verdict rationale

Wave 130's lesson — "fixes in Revision Notes section without corresponding body edits" — does not apply here. Every Pass-1 finding maps to a verifiable body location, not just the Revision summary. Verdict upgraded from "approved with carry-forward" to "ratified."
