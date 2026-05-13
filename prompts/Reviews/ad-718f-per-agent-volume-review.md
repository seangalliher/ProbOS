# Review: AD-735 — Per-agent volume slider in the agent profile card
**Verdict:** ✅ Approved (with one nit)
**The backend chain is fully shipped at HEAD; the slider insertion mirrors the Pitch/Rate pattern verbatim and is safe to build.**

Reviewer: Architect (Pass 1, 2026-05-13). Prompt file: `prompts/ad-718f-per-agent-volume.md`.

---

## Required (must fix before building)

_None._ The prompt is correctly scoped, the SEARCH block matches the live file, and the backend chain is fully shipped as claimed.

## Recommended

1. **Test 4 boundary semantics under JSDOM (Section 2, test_volume_slider_clamps_at_zero_and_one).**
   The test plan relies on the native `<input type="range">` min/max clamping `value="-0.5"` → `0` and `value="1.5"` → `1`. JSDOM (Vitest's default DOM) does NOT enforce HTML constraint validation the way Chromium does — `fireEvent.change(input, { target: { value: "-0.5" } })` in JSDOM typically passes the string through as-is, and the test will read back `"-0.5"`, not `"0"`. Recommend rewording the test to assert the *contract* the UI relies on: drag to a valid in-range value and verify the `onChange` payload + persistence. Boundary enforcement is the SERVER's job (already covered by `VoiceProfile.__post_init__` at [src/probos/crew_profile.py:124](src/probos/crew_profile.py#L124)). Alternative: keep the test but use `userEvent.type` / `pointer` on the slider track, which more faithfully simulates browser clamping. Either way, the current spec is fragile.

2. **Test count statement is internally inconsistent.**
   Section 2 lead-in says "Test count: **5 tests** (1 boundary test pair counts as 2)" but lists 5 named tests where test #4 contains two assertions in one `test_*` function. Either declare it 5 tests total with one having two asserts, or split test #4 into two named tests. Same outcome either way; just align the language.

## Nits

1. **Numeric display convention divergence is intentional but worth documenting in the closure note.** Pitch/Rate render `(value).toFixed(2)`; Volume renders `Math.round(value * 100) + '%'`. The prompt explains this in Section 1b ("perceptual ratio reads more naturally as 70%") — good. Append a one-liner to the `DECISIONS.md` closure block citing this choice so future maintainers don't "fix" the inconsistency.

2. **`data-testid="volume-slider"` is new for this row.** Pitch and Rate don't have testids (their tests, if any, presumably use `getByRole('slider', { name: 'Pitch' })`). Either accept the asymmetry (justified by test 5 using `getByRole`) or skip the testid and use role-based queries throughout. Minor.

3. **The `__tests__/` subdirectory under `ui/src/components/profile/` does not exist yet.** Confirmed via `file_search ui/src/components/profile/__tests__/*` → no files. Builder will create the directory; no problem, but worth noting in the file table.

## Verified

- **Backend chain shipped as claimed.** Verified line-by-line:
  - `VoiceProfile.volume: float = 0.8` at [src/probos/crew_profile.py:108](src/probos/crew_profile.py#L108) ✓
  - `__post_init__` enforces `0.0 <= volume <= 1.0` at line 124 ✓
  - `PUT /api/agents/{agent_id}/voice-profile` at [src/probos/routers/agents.py:237](src/probos/routers/agents.py#L237) ✓ (prompt says 236; off-by-one due to decorator vs `async def` line — acceptable)
  - `utterance.volume = effective.volume ?? 0.8` at [ui/src/audio/voice.ts:139](ui/src/audio/voice.ts#L139) ✓
- **Pitch/Rate slider pattern matches SEARCH block exactly.** [ui/src/components/profile/ProfileInfoTab.tsx:333-360](ui/src/components/profile/ProfileInfoTab.tsx) — same `onMouseUp`/`onTouchEnd` persistence, same label width, same `step={0.05}`. The AD-718c comment immediately follows, so the insertion-point boundary is unambiguous.
- **HXI Design Principle #3 honoured.** Inline SVG speaker glyph with stroke-based, `strokeWidth: 1.5`, dim/amber colour by state. No emoji. Matches the convention.
- **AD-731 invariant preserved.** No bus / RPC / attachment changes.
- **Wire shape unchanged.** `SetVoiceProfileRequest.volume` already exists and the request body is unmodified.
- **Scope hygiene.** Section 3 "What this does NOT change" is comprehensive and lists every adjacent system (manifest, voiceModulation, AmbientSlider, AD-718a proposal flow) explicitly.
- **Boundary tests per copilot-instructions standard.** Tests 1+2 (happy path / persisted value), test 3 (persistence side-effect), test 4 (boundary), test 5 (accessibility). Tier coverage adequate.
- **One-file-edit scope.** Single source mod (`ProfileInfoTab.tsx`) + single test file. Low blast radius.
- **License posture clean.** Apache 2.0, no external absorption, no new deps.
- **Tracking updates correctly enumerated.** PROGRESS.md, DECISIONS.md, roadmap.md all listed.

---

## Re-review pass record

_None yet — first pass approved._

---

### Re-review (pass-2, 2026-05-13)

**Verdict:** ✅ Approved
**Both pass-1 Recommended cleanups applied; ready for build.**

#### Required
_None._

#### Recommended
_None new._

#### Nits
1. **Duplicate Revision section.** The prompt contains TWO `## Revision (2026-05-13)` blocks (lines 279 and 290). The second is a corrupted copy (literal tab characters where backticks should be, e.g. ` st_volume_slider_* ` instead of ` 	est_volume_slider_* `). The first block at line 279 is canonical and correct. Recommend the Builder delete lines 290-296 (the second block) before commit — purely cosmetic, no effect on the implementation.

#### Verified
- **Test 4 rewrite landed.** Renamed to `test_volume_slider_round_trips_in_range_values` at line 165; new spec asserts in-range round-trip through `onChange` + `PUT` rather than relying on JSDOM HTML-constraint enforcement. Server-side clamp invariance correctly noted as covered by AD-718 backend suite.
- **Test-count phrasing aligned.** Section 2 lead-in now reads `5 tests total` (one with two assertions). Internally consistent.
- **No scope change.** Section 1 SEARCH/REPLACE block, backend chain references, and the file table are byte-identical to pass-1.
- **No new findings.** All pass-1 Verified items still hold.
