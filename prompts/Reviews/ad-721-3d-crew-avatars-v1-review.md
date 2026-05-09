# Review: AD-721 v1 — 3D Crew Avatars (VRM popout)
**Verdict:** ✅ Approved (Pass 2 — upgraded from ⚠️ Conditional)
**Pass 1: ⚠️ with 4 Recommended + 2 Nits. Pass 2: all 6 resolved in body. Ready for Builder dispatch.**

## Required (must fix before building)

_None._

## Recommended (should fix)

1. **D5 `_attachAnalyserOrSchedule` is a stub, not a spec.** The helper is named, its location asserted (`ui/src/audio/speechAmplitude.ts`), and the Tier-2 degradation contract is clear ("returns a fake `AnalyserNode`-shaped object that synthesises a plausible amplitude curve"). But the actual fake-AnalyserNode shape (`frequencyBinCount`, `getByteFrequencyData(buf)`) and the synth curve (sine-modulated random over duration estimate from `text.length / rate`) are left for the Builder. Given this is the single most novel piece of v1 and the `useFrame` consumer in D5 calls `analyser.frequencyBinCount` and `getByteFrequencyData(buf)` directly, the spec should sketch the fake's interface explicitly so the Builder doesn't reinvent. **Real-audio capture is correctly deferred to AD-721b.**

2. **D8 enabled-flag plumbing is soft-specced.** "exposed via the existing config-to-UI flag path (Builder confirms in pre-flight; if no such path exists, surface via a one-line `/api/config/flags` route — but keep it minimal)." This conflates two outcomes: (a) reusing an existing path, (b) creating a new endpoint. Pre-flight should pick one and commit. Suggest: name the existing flag route in pre-flight and have the prompt fall back to a defined `GET /api/config/avatars-enabled` if not found, so Builder isn't designing API surface mid-build.

3. **Line-number drift on `AgentProfilePanel.tsx`.** Prompt asserts `DEPT_COLORS` at "21" and `isCrew` at "97". Actual HEAD: `DEPT_COLORS` line 20, `isCrew` line 92. Strict reading of the grep block in §Verified shows `21:  const DEPT_COLORS` — that's wrong. Apply "around line N" convention per `review-criteria.md` §6.

4. **D6 static-file route — Builder note instructs reuse of `routers/system.py:590` `ui://` pattern, but the line number is unverified at HEAD in this prompt.** Cross-referenced from AD-706 review per the prompt itself. The Builder note already says "follow that pattern" rather than asserting line 590, so the pre-flight grep will catch it — but explicitly say "Builder greps for the `ui://` resource handler in `routers/system.py` and mirrors its auth/middleware path." The path-traversal defense (`Path.resolve().is_relative_to(...)`) is correctly called out. ✅

## Nits

1. D2 `AppearanceProfile.from_dict` does explicit `data.get(...)` for each field instead of the kwargs-spread pattern AD-718's `VoiceProfile.from_dict` uses. Inconsistent across the same wave. Cosmetic only — both work.

2. D3 popout style block uses raw inline `style={...}` for the modal chrome (320×480 fixed). Matches existing HXI patterns elsewhere; no CSS-module abstraction needed for v1. Forward marker AD-721a (avatar editor UI) is the right place to centralise.

## Verified

- `@react-three/fiber` (line 15), `@react-three/drei` (14), `@react-three/postprocessing` (16), `three` (21) all present in `ui/package.json`. `@pixiv/three-vrm` correctly absent — D1 adds it.
- VRM library decision (adopt `@pixiv/three-vrm` v2 MIT, reject `@readyplayerme/visage`) is reasoned and aligned with forward marker AD-721d (agent-authored appearance).
- `AgentProfilePanel.tsx` imports + `DEPT_COLORS` mapping + `isCrew` guard + tab list confirmed (modulo line-number drift in Recommended #3). `isCrew=true` default per BF-017 noted.
- `crew_profile.py` `CrewProfile` dataclass + nested `to_dict/from_dict` precedent correct; D2 mirrors AD-718's `VoiceProfile` pattern. ✅
- `routers/agents.py:40` `@router.get("/{agent_id}/profile")` confirmed; D5 adds `"appearance"` next to AD-718's `"voiceProfile"` — both edits are at one site.
- Contradiction #3 (`data/avatars/` doesn't exist + can't ship third-party VRMs) documented in body and resolved via parametric fallback in D7.
- Contradiction #6 (`McpAppFrame` phantom from AD-706 review) documented; v1 correctly renders directly in React tree.
- Cross-AD synergy: AD-721 D5 imports `onSpeechEvent` from AD-718 D1; Acceptance line "AD-718 must be merged before AD-721's tests run; if not, surface and stop" present. Source-layout dependency (`AppearanceProfile` "immediately after `VoiceProfile`") enforces ordering. ✅
- License hygiene: `data/avatars/.gitkeep` only; `data/avatars/*.vrm` to `.gitignore`; "v1 ships NO `.vrm` binaries" stated; operators bring own VRMs. ✅
- Default-False: `AvatarsConfig.enabled: bool = False` per Wave 10 convention #14. ✅
- TTS amplitude limitation: D5 explicitly degrades to synthesised amplitude curve and labels real-audio-capture as AD-721b forward marker. ✅ (Even with Recommended #1, the contract is honest.)
- Forward markers AD-721a–h present with gate-3 issue-filing instruction.
- Working-tree integrity bullet present in Acceptance.
- AD-numbering re-verification line present.
- HXI design-principle compliance: no emoji, amber/blue/violet palette, motion-encodes-state — all called out.
- Cognitive canvas (`ui/src/canvas/agents.tsx`) explicitly out of scope; AD-721f is the forward marker for canvas avatars.
- "Captain-watch streaming for the avatar (it's local-only) — out of scope; no relation to AD-706a" — clean boundary statement.


## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved — ready for Builder dispatch (upgraded from ⚠️ Conditional).
**Required: 0. Recommended: 0. Nits: 0.**

Pass-2 bar (Wave 130 lesson): every Pass-1 finding must land in the prompt **body**, not just the Revision Notes section. Spot-checked all 6 below.

### Pass-1 findings — body landings verified

| # | Pass-1 finding | Body landing | Verified |
|---|---|---|---|
| Rec #1 | D5 `_attachAnalyserOrSchedule` was a stub | D5 (body L267–L307) now defines the `FakeAnalyser` interface (`frequencyBinCount`, `getByteFrequencyData(buf)`), a duration heuristic from `text.length / rate`, and a sine-envelope synth at ~6 Hz with mild noise. The `useFrame` consumer at body L241–L242 reads exactly these two members. Real-audio capture explicitly deferred to AD-721b. | ✅ |
| Rec #2 | D8 enabled-flag plumbing was soft-specced | D8 (body L359) commits to a deterministic fork at pre-flight: (a) if `routers/system.py` or `routers/config.py` already serves a config-flag GET endpoint, append `avatars_enabled: bool` to its response shape; (b) otherwise add `GET /api/config/avatars-enabled` returning `{"enabled": runtime.config.avatars.enabled}` — single endpoint, no new generic config-API surface. | ✅ |
| Rec #3 | Line drift on `AgentProfilePanel.tsx` | Verified bullets (body L34, L36) now read "around line 20" for `DEPT_COLORS` and "around line 92" for `isCrew`. Bottom grep block (body L444–L449) shows actual HEAD line numbers (20, 91, 92, 95, 206). | ✅ |
| Rec #4 | D6 `routers/system.py:590` line citation unverified | D6 Builder-note (body L325) now reads "Pre-flight: Builder greps `src/probos/routers/system.py` for the existing `ui://` resource handler and mirrors its auth/middleware path." The unverified `:590` line citation is removed. Path-traversal defense (`Path.resolve().is_relative_to(...)`) preserved. | ✅ |
| Nit #1 | `AppearanceProfile.from_dict` data.get vs kwargs-spread | Cosmetic — both work. No body change required. | ✅ |
| Nit #2 | D3 popout uses raw inline style | Forward marker AD-721a is the right place to centralise. No body change required. | ✅ |

### Grep self-check

```
=== AD-721 D5 FakeAnalyser body hits ===
  L241: const buf = new Uint8Array(analyser.frequencyBinCount);
  L242: analyser.getByteFrequencyData(buf);
  L273: export interface FakeAnalyser {
  L274:   frequencyBinCount: number;
  L275:   getByteFrequencyData(buf: Uint8Array): void;
  L282:   ): AnalyserNode | FakeAnalyser {
  L295:     frequencyBinCount: binCount,
  L296:     getByteFrequencyData(buf: Uint8Array): void {

=== AD-721 D8 enabled-flag — single committed path ===
  L359: Pre-flight Builder check ... If one exists, append avatars_enabled: bool
        ... If no such endpoint exists, add GET /api/config/avatars-enabled
        ... Do NOT design new generic config-API surface in this AD.

=== AD-721 line drift (DEPT_COLORS / isCrew) ===
  L34:  AgentProfilePanel.tsx around line 20 — DEPT_COLORS mapping              ✅
  L36:  AgentProfilePanel.tsx around line 92 — isCrew = ... ?? true             ✅
  L445: 20: const DEPT_COLORS: Record<string, string> = { (HEAD verified)       ✅
  L447: 92: const isCrew = profileData?.isCrew ?? true; (HEAD verified)         ✅

=== AD-721 stale-line stragglers (should be empty) ===
  AgentProfilePanel.tsx:21 — NOT in normative content                           ✅
  AgentProfilePanel.tsx:97 — NOT in normative content                           ✅
  crew_profile.py:130 — NOT in normative content (only in Revision Notes)       ✅
  agents.py:117 — NOT in normative content (only in Revision Notes)             ✅
  system.py:590 — NOT in normative content (only in Revision Notes)             ✅
  registry.py:42 — NOT in normative content (only in Revision Notes)            ✅
```

### Phantom-API spot-check (HEAD 2026-05-08)

| Asserted | HEAD | Status |
|---|---|---|
| `CrewProfile` at `crew_profile.py` ~116 | line 116 | ✅ |
| `PersonalityTraits` at `crew_profile.py` ~51 | line 51 | ✅ |
| `ProfileStore` at `crew_profile.py` ~215 | line 215 | ✅ |
| `DEPT_COLORS` at `AgentProfilePanel.tsx` ~20 | line 20 | ✅ |
| `isCrew` at `AgentProfilePanel.tsx` ~92 | line 92 | ✅ |
| `@react-three/fiber`, `three` in `ui/package.json` | lines 15, 21 | ✅ |
| `@pixiv/three-vrm` absent from `ui/package.json` (D1 adds) | absent | ✅ (correct — D1 introduces it) |
| `routers/agents.py:40` `GET /{agent_id}/profile` | line 40 | ✅ |

### Residual concerns

None. Both AD-718 and AD-721 are now structurally identical in pass-2 quality: every Pass-1 finding has a verifiable body location.

### Pass-2 verdict rationale

Pass-1 ⚠️ Conditional was awarded for two soft-specced areas (D5 fake AnalyserNode interface and D8 enabled-flag fork). Both are now committed in body — D5 includes a complete TypeScript sketch the Builder can lift verbatim; D8 commits the API surface with a pre-flight grep that picks one of two deterministic paths. The 1 ⚠️ wave budget (convention #15) is preserved unused — Wave 133 enters Builder dispatch with both prompts at ✅.
