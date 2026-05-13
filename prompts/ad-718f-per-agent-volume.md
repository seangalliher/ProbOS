# AD-735 — Per-agent volume slider in the agent profile card

**Status:** Ready for Builder
**AD:** AD-735 (was drafted as "AD-718f"; promoted to top-level sequence — Wave 156 highest-AD audit assigned the next free number)
**GH issue:** [#527](https://github.com/seangalliher/ProbOS/issues/527) (closes)
**Parent AD:** AD-718 (per-agent voice profile, shipped). Extends the existing voice UI without changing the wire shape.
**Wave:** 156
**Estimated tests:** ~4-6 new in `ui/src/components/profile/__tests__/ProfileInfoTab.volumeSlider.test.tsx` (NEW file).

---

## Captain decisions baked in

1. **Backend is already complete.** The `volume: float = 0.8` field exists on `VoiceProfile` ([src/probos/crew_profile.py:108](src/probos/crew_profile.py#L108)), is accepted by `SetVoiceProfileRequest` ([src/probos/api_models.py:243](src/probos/api_models.py#L243)), is persisted by `PUT /api/agents/{agent_id}/voice-profile` ([src/probos/routers/agents.py:236](src/probos/routers/agents.py#L236)), is returned by the agent profile GET, is in the TS store type at [ui/src/store/types.ts:357](ui/src/store/types.ts#L357), and is applied to playback at [ui/src/audio/voice.ts:139](ui/src/audio/voice.ts#L139) (`utterance.volume = effective.volume ?? 0.8`). The UI never exposed a slider — this is **the gap**, and it is the entire scope of this AD.
2. **Mirror the existing Pitch/Rate slider pattern in `ProfileInfoTab.tsx`.** Pitch and Rate already have sliders at lines 333-360 with identical `onMouseUp` / `onTouchEnd` persistence semantics. Volume slides into the same block with the same shape.
3. **Inline SVG speaker icon, not emoji** (HXI Design Principle #3). Use stroke-based, `strokeWidth: 1.5`, dim/amber color per state, no fills. Match the existing icon family in `DecisionSurface.tsx:135-146` for the speaker glyph (a speaker cone + two sound arcs).
4. **Persistent (config) change, not transient.** Same `persistVoiceProfile()` call as Pitch/Rate. No volume override survives only a session.
5. **0.0–1.0 range, step 0.05, clamped at boundary.** Backend `VoiceProfile.__post_init__` already enforces `0.0 <= volume <= 1.0` ([src/probos/crew_profile.py:124](src/probos/crew_profile.py#L124)); the slider min/max/step match.
6. **No new dependencies.** Slider is a native `<input type="range">` matching the Pitch/Rate inputs. No npm package added.

---

## Problem

The Captain wants to lower one chatty agent (e.g. an overactive utility crew) without muting the entire bridge by toggling the global voice button. Today the only volume controls are:

- The global ambient-sound slider in `DecisionSurface.tsx:147-167` (volume of the soundEngine, NOT TTS).
- The "Propose voice" affordance in `ProfileInfoTab.tsx:404+` (heavyweight — invokes the LLM to draft a full voice proposal).

Neither lets the Captain say "Quark talks too loud" and immediately knock his playback down 30%. The backend already accepts the change; the UI just never exposed it.

---

## Solution

One file edit: add a Volume slider row in `ProfileInfoTab.tsx` between the Rate slider (ends ~line 360) and the Wake-phrase input (starts ~line 362). Match the Pitch/Rate slider shape exactly — same persistence semantics, same label width, same numeric display.

One new test file: `ui/src/components/profile/__tests__/ProfileInfoTab.volumeSlider.test.tsx` (NEW) with 4–6 Vitest component tests covering: render, default value, clamp at boundaries, persist on mouse-up, accessibility label.

No Python changes. No additional routes. No new state in `useStore`. No new dependencies.

---

## Section 0 — Files touched

| File | Change |
|---|---|
| `ui/src/components/profile/ProfileInfoTab.tsx` | Insert Volume slider row mirroring Pitch/Rate (between lines 360 and 362). |
| `ui/src/components/profile/__tests__/ProfileInfoTab.volumeSlider.test.tsx` | NEW — 4-6 Vitest tests. |
| `PROGRESS.md` | Wave 156 entry; +tests count delta. |
| `DECISIONS.md` | Append AD-735 closure block (referencing AD-718 parent and the existing backend chain). |
| `docs/development/roadmap.md` | Mark AD-735 shipped Wave 156; close [#527](https://github.com/seangalliher/ProbOS/issues/527). |

**Do NOT touch:**
- `src/probos/crew_profile.py` (VoiceProfile.volume already exists)
- `src/probos/api_models.py` (SetVoiceProfileRequest.volume already exists)
- `src/probos/routers/agents.py` (PUT endpoint already accepts volume)
- `ui/src/audio/voice.ts` (utterance.volume already applied)
- `ui/src/store/types.ts` (voiceProfile.volume already in the type)
- `ui/src/audio/voiceModulation.ts` (emotional modulation already multiplies onto the baseline volume)
- `ui/src/components/DecisionSurface.tsx` (ambient-sound slider unrelated; do NOT merge with per-agent volume)
- `pyproject.toml` / `package.json` (no new deps)

---

## Section 1 — Volume slider in `ProfileInfoTab.tsx`

The Pitch slider lives at [ui/src/components/profile/ProfileInfoTab.tsx:333-347](ui/src/components/profile/ProfileInfoTab.tsx#L333-L347). The Rate slider lives at [lines 348-360](ui/src/components/profile/ProfileInfoTab.tsx#L348-L360). Insert the Volume row immediately after Rate, before the wake-phrase label.

### 1a. Locate the insertion point

In `ProfileInfoTab.tsx`, find the SEARCH block:

```tsx
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ color: '#8888a0', minWidth: 50 }}>Rate</span>
              <input
                type="range"
                min={0.1} max={2} step={0.05}
                value={currentProfile.rate ?? 0.95}
                onChange={(e) => setCurrentProfile(p => ({ ...p, rate: parseFloat(e.target.value) }))}
                onMouseUp={() => persistVoiceProfile(currentProfile)}
                onTouchEnd={() => persistVoiceProfile(currentProfile)}
                aria-label="Rate"
                style={{ flex: 1 }}
              />
              <span style={{ color: '#c0bab0', minWidth: 32 }}>{(currentProfile.rate ?? 0.95).toFixed(2)}</span>
            </label>
            {/* AD-718c: per-agent wake phrase. Empty = no per-agent wake;
                system-wide "Computer" still routes to the agent via @callsign. */}
```

Insert the Volume row between the closing `</label>` of the Rate slider and the AD-718c comment.

### 1b. Volume slider row

Add this block (matches the Pitch/Rate shape exactly except for the inline speaker SVG glyph on the left, which replaces the plain "Volume" text-label to honour HXI Design Principle #3):

```tsx
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span
                style={{ color: '#8888a0', minWidth: 50, display: 'inline-flex', alignItems: 'center', gap: 4 }}
              >
                {/* AD-735: inline SVG speaker glyph (HXI Design Principle #3 — no emoji).
                    Matches the DecisionSurface speaker family at lines 135-146. */}
                <svg
                  width="11"
                  height="11"
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke={(currentProfile.volume ?? 0.8) > 0 ? '#f0b060' : '#666680'}
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  <path d="M2 6v4l3 3h1V3H5L2 6z" />
                  <path d="M9 5.5c.7.7 1 1.5 1 2.5s-.3 1.8-1 2.5" />
                </svg>
                <span>Volume</span>
              </span>
              <input
                type="range"
                min={0} max={1} step={0.05}
                value={currentProfile.volume ?? 0.8}
                onChange={(e) =>
                  setCurrentProfile(p => ({ ...p, volume: parseFloat(e.target.value) }))
                }
                onMouseUp={() => persistVoiceProfile(currentProfile)}
                onTouchEnd={() => persistVoiceProfile(currentProfile)}
                aria-label="Volume"
                data-testid="volume-slider"
                style={{ flex: 1 }}
              />
              <span style={{ color: '#c0bab0', minWidth: 32 }}>
                {Math.round((currentProfile.volume ?? 0.8) * 100)}%
              </span>
            </label>
```

Notes:
- Numeric display uses **percent** for the Captain-facing view (`Math.round(value * 100)%`). Pitch/Rate use raw 2-decimal numbers because those are physically meaningful (octave shift, time stretch); volume is a perceptual ratio where "70%" reads more naturally than "0.70".
- The SVG `stroke` colour swaps between amber (`#f0b060`) when audible and dim (`#666680`) when muted (volume === 0). This is the same active/inactive convention used by other HXI icon families.
- `data-testid="volume-slider"` is added so the Vitest test can locate the slider without ambiguity.

### 1c. No other edits in this file

Do NOT touch:
- The Pitch slider (lines 333-347) — it stays exactly as shipped.
- The Rate slider (lines 348-360) — same.
- The Wake-phrase input (lines 362+) — same.
- The Test button (line 387) — already calls `speakResponse('This is how I sound.', currentProfile, agent.id)`, which means the Test button **already plays back the new volume** because `currentProfile.volume` is now reachable. No edit needed.
- The Propose-voice flow (line 404+) — out of scope.

---

## Section 2 — Tests (`ui/src/components/profile/__tests__/ProfileInfoTab.volumeSlider.test.tsx`, NEW file)

Test count: **5 tests total** (one test contains two assertions for boundary coverage but is a single named test).

### Test plan

1. **`test_volume_slider_renders_with_default_value`** — Mount `<ProfileInfoTab agent={crewAgent} />` with a voiceProfile fetch that returns `{ volume: 0.8, ... }`. Assert the slider input with `data-testid="volume-slider"` has `value="0.8"` and the percent display reads `"80%"`.
2. **`test_volume_slider_renders_existing_persisted_value`** — Same setup but with the GET stub returning `{ volume: 0.35, ... }`. Assert the slider value is `0.35` and display reads `"35%"`.
3. **`test_volume_slider_persists_on_mouse_up`** — Mount, drag the slider via `fireEvent.change` to `0.5`, then `fireEvent.mouseUp`. Assert a `fetch` call was made to `PUT /api/agents/{agent_id}/voice-profile` with a body containing `"volume":0.5`. Verifies that the slider follows the SAME persistence pattern as Pitch/Rate.
4. **`test_volume_slider_round_trips_in_range_values`** — Boundary contract test (revised per pass-1 review: JSDOM does NOT enforce native HTML `min`/`max` constraint validation, so `fireEvent.change(input, { target: { value: '-0.5' } })` would yield `'-0.5'` verbatim, not the clamped `0`). Instead, assert the *UX contract* the slider relies on with two assertions in one test: (a) `fireEvent.change` with `value="0"` then `mouseUp` persists `volume=0` via `PUT`; (b) `fireEvent.change` with `value="1"` then `mouseUp` persists `volume=1`. Server-side clamp invariance is already covered by `VoiceProfile.__post_init__` ([src/probos/crew_profile.py:124](src/probos/crew_profile.py#L124)) and the existing AD-718 backend test suite.
5. **`test_volume_slider_has_accessible_label`** — Use `getByRole('slider', { name: 'Volume' })` to assert that screen readers can find it. Smoke test for the `aria-label="Volume"` attribute.

### Test boilerplate

Follow the structure of the existing `ProfileInfoTab` tests if any exist; otherwise model on `ui/src/audio/__tests__/voice.test.ts` for fetch stubbing patterns. Use `vi.mock('../../audio/voice', () => ({ speakResponse: vi.fn(), ... }))` to silence the TTS path during render.

---

## Section 3 — What this does NOT change

- **Wire shape unchanged.** `PUT /api/agents/{agent_id}/voice-profile` request body schema is identical. No new field, no new endpoint, no new event type.
- **VoiceProfile semantics unchanged.** Backend validators ([crew_profile.py:124](src/probos/crew_profile.py#L124)) still enforce `0.0 <= volume <= 1.0`. The slider's native HTML `min`/`max` is a UX courtesy; the server is still the source of truth.
- **Emotional modulation composition unchanged.** `applyEmotionalModulation` ([ui/src/audio/voiceModulation.ts:89](ui/src/audio/voiceModulation.ts#L89)) still multiplies onto the baseline volume; lowering the slider lowers BOTH the baseline AND every modulated outcome proportionally — this is the desired behaviour (Captain wants Quark quieter, period; not "Quark quieter except when excited").
- **AD-718a proposal flow untouched.** Captain can still ask the agent to propose a full voice profile; the slider is a Captain-side override that does NOT pre-empt or interfere with the proposal flow.
- **No Python tests added or modified.** Pure UI change; the backend has full test coverage for volume validation under AD-718's existing test suite.
- **No `package.json` edit.** No new npm dependency.
- **AD-731 attachment invariant respected.** This change does not touch the bus, RPC, or any attachment path.

---

## Section 4 — Verification commands

After build, before commit:

```powershell
# UI focused test gate
cd ui
npx vitest run src/components/profile/__tests__/ProfileInfoTab.volumeSlider.test.tsx

# UI full gate (must remain green)
npx vitest run

# Backend full gate (must remain green; no Python change but sanity)
cd ..
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
```

Live verification (operator-driven, post-commit):

1. Open the HXI, click an agent's profile card.
2. Scroll to the Voice section.
3. Confirm three sliders visible (Pitch, Rate, Volume) with the speaker SVG glyph next to "Volume".
4. Drag the Volume slider to ~30%; click "Test". Confirm the playback is noticeably quieter than at 80%.
5. Refresh the page; confirm the slider stays at 30% (persistence round-trip).

---

## Section 5 — Tracker updates

- **`PROGRESS.md`** — Wave 156 entry. Add tests count delta (+5 Vitest). Reference AD-735 + closure of [#527](https://github.com/seangalliher/ProbOS/issues/527).
- **`DECISIONS.md`** — Append AD-735 closure block. Cite: (a) backend was already complete (link AD-718 parent), (b) UI gap was the entire scope, (c) the slider follows the Pitch/Rate pattern verbatim, (d) HXI design principle #3 honoured with inline SVG glyph.
- **`docs/development/roadmap.md`** — Move AD-735 from "Wave 156 in-flight" to "shipped Wave 156"; mark issue #527 closed.

---

## Section 6 — License Disposition

| Item | License | Posture |
|---|---|---|
| ProbOS code added | Apache 2.0 (matches repo) | New file `ProfileInfoTab.volumeSlider.test.tsx` and edits to `ProfileInfoTab.tsx` carry the same license posture as the rest of the repo. |

- **No external code absorption.** No third-party module copied, no upstream pattern adapted, no model weights.
- **No new dependencies.** `package.json` is unchanged. The slider is a native `<input type="range">`; the SVG glyph is inline.
- **All-internal confirmed.** This is an HXI surface refinement on top of fully-shipped backend infrastructure.

---

## Forward markers

- **Stereo / panning controls** (left-channel-only for one agent, right-channel for another) — not in scope. Browser SpeechSynthesisUtterance has no panning property; would require Web Audio routing with a `MediaStreamAudioSourceNode`, which is a substantial change. File as a future AD if the Captain wants it.
- **Volume keyboard shortcut** (e.g. `Alt+↓` to lower the active speaker's volume by 5%) — out of scope; the slider is the v1 surface.
- **Volume audit log** (record every volume change as an episode for the agent's self-image) — not in scope; volume is a Captain-side UX preference, not an agent-observable signal.

---

## Acceptance criteria

- ✅ One file edited (`ProfileInfoTab.tsx`); one new test file (`ProfileInfoTab.volumeSlider.test.tsx`).
- ✅ Volume slider visible in the Voice section of the agent profile card.
- ✅ Inline SVG speaker glyph; no emoji used.
- ✅ Persistence round-trip works (drag → mouse-up → PUT → refresh shows persisted value).
- ✅ ≥ 4 new Vitest tests, all passing.
- ✅ Full UI gate green; full Python gate unchanged (no regression).
- ✅ `PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md` updated.
- ✅ GH issue [#527](https://github.com/seangalliher/ProbOS/issues/527) closed with the merge commit.
- ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-13)

```
Backend volume field already shipped:
  src/probos/crew_profile.py:108        volume: float = 0.8
  src/probos/crew_profile.py:124        if not 0.0 <= self.volume <= 1.0: raise ValueError(...)
  src/probos/api_models.py:243          volume: float = 0.8
  src/probos/routers/agents.py:236      @router.put("/{agent_id}/voice-profile")

UI volume field already shipped (but no slider):
  ui/src/audio/voice.ts:139             utterance.volume = effective.volume ?? 0.8
  ui/src/store/types.ts:357             voiceProfile?: { ..., volume: number, ... }

Existing slider pattern to mirror:
  ui/src/components/profile/ProfileInfoTab.tsx:333-347   Pitch slider
  ui/src/components/profile/ProfileInfoTab.tsx:348-360   Rate slider
  ui/src/components/profile/ProfileInfoTab.tsx:362+      Wake phrase (insertion-point boundary)

Inline SVG icon family to match:
  ui/src/components/DecisionSurface.tsx:135-146         Speaker SVG (stroke=#ffcc66 active, #8888aa inactive)
```

---

## Revision (2026-05-13)

Pass-1 review applied two minor cleanups (zero Required findings):

1. **Test 4 (`test_volume_slider_clamps_at_zero_and_one`)** renamed to **`test_volume_slider_round_trips_in_range_values`** and rewritten. JSDOM does NOT enforce HTML range `min`/`max` constraint validation, so the original spec would have failed in CI. New test asserts the UX contract directly (in-range values round-trip through `onChange` + `PUT`); server-side clamp invariance stays covered by the existing AD-718 backend suite ([src/probos/crew_profile.py:124](src/probos/crew_profile.py#L124)).
2. **Test-count phrasing** clarified: "5 tests total" with one test containing two assertions, instead of "5 tests (1 boundary test pair counts as 2)".

No scope change. Backend chain unchanged. SEARCH/REPLACE block in Section 1 unchanged.
