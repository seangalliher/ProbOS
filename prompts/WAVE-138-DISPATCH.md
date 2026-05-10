# WAVE 138 DISPATCH — Phoneme-accurate lip-sync (visemes) — AD-721b v1

**Wave:** 138
**Mode:** main
**Depends on:** 133 (AD-721 D5 amplitude-only mouth driver), 137 (Wave 137 Edge TTS unchanged ruling)
**Builder required:** yes
**Issues to close:** [#529](https://github.com/seangalliher/ProbOS/issues/529)
**Date:** 2026-05-09

---

## 1. Goal

Counselor (Echo) testing on 2026-05-09 confirmed the AD-721 amplitude-only mouth driver is "the 80% solution" — the mouth opens and closes but vowels are not visually distinguishable. Captain ruled the phoneme-lipsync arc a definite next-step. AD-721b v1 ships the next 20%: a viseme-weighted driver that animates **all five VRoid vowel morphs** (`Fcl_MTH_A/I/U/E/O`) across **every face mesh** (multi-mesh face-split fix from AD-721 BF de4107b applies to all five shapes, not just `aa`).

**Scope:** UI-only. Track-based pipeline only. v1 derives a synthetic phoneme track from the utterance text via a length × phoneme-duration heuristic — better than amplitude-only but not real audio analysis. Real-audio capture (whisper.cpp WASM, rhubarb backend, oculus-lipsync-web) is firewalled OFF and re-filed as forward markers AD-721b-1 / AD-721b-2.

Backwards compatibility: when `lipSyncTrack` returns null/empty (load failure, unknown utterance), `CrewVRM` falls back to the existing amplitude-driven path. Tier-2 log-and-degrade — speech must NEVER stop animating because of a viseme failure.

---

## 2. Prior-work + license disposition

| Prior work / candidate | What we found at HEAD | Disposition |
|---|---|---|
| `ui/src/audio/speechAmplitude.ts` `_attachAnalyserOrSchedule(utterance)` | Verified at HEAD lines 1–58. Returns `AnalyserNode \| FakeAnalyser`. Synthetic envelope = two-band (slow 2.5 Hz word rhythm + fast 6 Hz syllable cadence) + random gate. No phoneme awareness. | **Keep as the fallback.** AD-721b v1 supersedes this for utterances with a generated viseme track; if the track is empty the analyser path runs as today. **Do NOT delete `_attachAnalyserOrSchedule`.** Reviewer fails any diff that removes the FakeAnalyser export — it's the safety net. |
| `ui/src/audio/voice.ts` `SpeechEvent { type: 'start' \| 'end' \| 'boundary'; agent_id?; utterance }` | Verified at HEAD lines 23–30. `'boundary'` reserved for AD-721b; not wired in v1 of voice.ts. `_fire` private. | **Reuse `'start'` / `'end'` only.** v1 of AD-721b does NOT need `'boundary'` (Edge / browser TTS doesn't expose audio frames anyway — Wave 137 ruling kept browser TTS as-is). The `'boundary'` event remains reserved for AD-721b-1/AD-721b-2 when real-audio capture lands. Drafter confirms `'boundary'` is NOT subscribed in this wave. |
| `ui/src/components/profile/CrewVRM.tsx` `directMouthMeshesRef` | Verified at HEAD lines 146 (declaration), 213–224 (collection), 258 (end-of-speech zero), 323 (per-frame write). Currently collects ONLY meshes carrying `Fcl_MTH_A` / `A` / `a` / `mouth_a` / `M_A` / `aa` (the `aa` morph). Multi-mesh face-split fix from BF de4107b. | **Extend the pattern to all 5 vowel morphs.** New ref `directVowelMeshesRef: { aa: { mesh, index }[]; ih: ...; ou: ...; ee: ...; oh: ...[] }` (drafter picks exact shape — recommended: `Map<VowelKey, { mesh, index }[]>`). Collection runs alongside the existing one in the same `loader.load` callback. **Old `directMouthMeshesRef` stays for backwards compatibility** — when the viseme track is empty (fallback path) it still drives the `aa` slice as today. Reviewer fails any diff that breaks the BF de4107b multi-mesh guarantee. |
| `ui/src/components/profile/CrewVRM.tsx` `useFrame` mouth driver | Verified at HEAD lines 254–328. Reads amplitude → smoothed value → writes to `em.setValue(name, value)` for every detected mouth shape AND `morphTargetInfluences[index] = v` for every direct mesh. Single-value (one `aa`-axis only). | **Replace the speaking branch with a viseme-weighted driver.** New driver reads `lipSyncTrack.sample(elapsedMs)` → `{ aa, ih, ou, ee, oh }` weights, applies per-vowel exponential smoothing (~50 ms attack / ~100 ms release per the issue body), writes EACH weight to its corresponding morph across ALL meshes in `directVowelMeshesRef`. Falls back to amplitude path when `track == null`. |
| `ui/src/components/profile/CrewVRM.tsx` mouth-shape detection (lines 196–211) | Verified at HEAD: scans `expressionManager` for `aa / a / A / Fcl_MTH_A / mouth_a / M_A`. Cached in `mouthShapesRef`. | **Generalise.** New `vowelShapesRef: Record<VowelKey, string[]>` cached at load; per-vowel candidate lists drawn from the issue mapping (`Fcl_MTH_A` → `aa`, `Fcl_MTH_I` → `ih`, `Fcl_MTH_U` → `ou`, `Fcl_MTH_E` → `ee`, `Fcl_MTH_O` → `oh`, plus VRM 1.0 preset names `aa / ih / ou / ee / oh`, plus VRoid alt names). Each per-vowel list works the same way `mouthShapesRef` does today. |
| Rhubarb-lip-sync (https://github.com/DanielSWolf/rhubarb-lip-sync) | MIT. Native binary. Produces per-frame phoneme output for a WAV file. | **Defer to AD-721b-1 (forward marker).** Edge TTS (Wave 137 ruling) does NOT expose audio frames to JavaScript, so a server-side rhubarb pass would have to re-synthesize the text in a separate engine to analyse — out of scope for v1. License-clean if/when AD-721b-1 lands; Captain's call whether the operator-installed binary path is acceptable. **No Python source touched in this wave.** |
| oculus-lipsync-web / openWakeWord-style WASM phoneme detector | Various licenses. Most production-grade phoneme alignment requires either a WASM viseme estimator over `MediaStreamDestination` (blocked: browser TTS doesn't route to Web Audio in Chromium / Firefox today, same constraint AD-721 D5 hit) or whisper.cpp tiny.en (~75 MB model). | **Defer to AD-721b-2 (forward marker).** v1 does not adopt any new WASM dep. Bundle size impact: zero new MB. |

**Top-level license posture:** Apache 2.0 stays Apache 2.0. **Zero new JS dependencies** in this wave. Zero new model weights. Zero new ONNX files. Zero new Python deps.

---

## 3. Engineering-principles checklist

Builder must verify each in the AD-721b prompt acceptance criteria. Reviewer flags any miss as **Required**.

| Principle (`.github/copilot-instructions.md`) | Where it applies | Verifying deliverable |
|---|---|---|
| **Tier-2 log-and-degrade** | D2 (track generation), D4 (CrewVRM driver) | Track generation runs in `try { ... } catch { logger.warn(...); return null }`. CrewVRM checks for null/empty track and falls back to the existing amplitude path. Tests verify both: (a) a successful generation drives all 5 vowels; (b) a thrown / null track preserves the amplitude-only behaviour. **Speech must never stop animating because of a viseme failure.** |
| **Multi-mesh face-split regression (HARD CONSTRAINT)** | D3 (CrewVRM mesh collection) + D5 tests | Every face mesh that carries any of `Fcl_MTH_A / I / U / E / O` (or the VRM-1.0 preset names) must be in `directVowelMeshesRef` and must receive its per-frame morph-target write. Test fixture: a synthetic VRM with 7 face meshes, 5 of them carrying all 5 vowel morphs, 2 of them carrying only `Fcl_MTH_A` — assert that the multi-mesh write hits all 5 of the first set across all 5 vowels AND still hits both of the second set on the `aa` axis. **If this regresses, the wave halts.** |
| **No emoji in HXI** (HXI Design Principle #3) | Any future viseme indicator (out of scope v1; flagged as forward marker) | v1 ships zero new HXI surfaces. No mouth-shape inspector, no viseme dial. If Captain wants debug visualisation later, file as a separate AD. Reviewer fails the prompt on any emoji literal. |
| **HXI Design Principle #4 (motion communicates state)** | D4 (per-vowel decay/blend) | Per-vowel exponential smoothing: ~50 ms attack (k ≈ 0.30 at 60 fps for a single-frame target = `1 - exp(-dt/50ms)`), ~100 ms release (k ≈ 0.18). Cross-blend consecutive visemes — when the track moves from `aa` to `oh` in one sample, the previous vowel decays via the release coefficient while the new one rises via attack. Reviewer fails on any pulse / gate / step-function discontinuity. |
| **No private-attr access** | D2, D4 | `lipSyncTrack` consumes only public exports of `voice.ts` (the `SpeechEvent` type and `onSpeechEvent` if needed for lifecycle — but recommended: lifecycle owned by CrewVRM via the same `'start'`/`'end'` flow already wired there). No reaching into `speechAmplitude.ts` private state. The synthetic-envelope code stays as today; AD-721b sits beside it, not inside it. |
| **Async discipline** | D2 (track generation) | Track generation is **synchronous** in v1 — pure text → viseme schedule, no `await`. No fire-and-forget. No `new Promise(...)` anti-patterns. If a future AD-721b-1 introduces async (rhubarb subprocess), drafter file a follow-up. |
| **Open/Closed** | D3 (CrewVRM extension) | The new vowel-collection logic is added alongside the existing single-vowel collection, not by mutating `directMouthMeshesRef`. The fallback path still uses `directMouthMeshesRef` exactly as today. The new path uses `directVowelMeshesRef`. Two refs, two responsibilities. |
| **DRY** | D3 (collection) | The single-vowel and multi-vowel collection loops share a helper `_collectMorphMeshes(scene, candidates)` (drafter picks exact name; private to `CrewVRM.tsx`). The current inline collection block at HEAD lines 213–224 is refactored into the helper, and called once per vowel. **No copy-paste of the `traverse` block five times.** |
| **Configuration** | None | v1 introduces ZERO new Pydantic config. UI knobs (`ATTACK_TIME_MS = 50`, `RELEASE_TIME_MS = 100`, average `PHONEME_DURATION_MS ≈ 80`, etc.) are compile-time constants in `lipSyncTrack.ts`. Drafter pins values; Captain reviews. |
| **Episodic completeness** | None | No new episode writes. Speech events already drive episode storage upstream. |
| **Trust + Hebbian alignment** | None | Read-only animation pipeline. No trust updates, no Hebbian updates. |
| **Test gates** | All deliverables | Per-prompt: `cd ui && npx vitest run` MUST be green and add ≥ 12 new tests (see D5). Full Python gate `pytest tests/ -q -n 4 --dist=loadfile` MUST stay green — but **AD-721b touches zero Python**, so the count should not change. If it does, something leaked outside scope; reviewer fails. |

---

## 4. AD-721b v1 scope

**Issue:** [#529](https://github.com/seangalliher/ProbOS/issues/529). Issue body is the source of truth for the viseme→morph mapping, the driver pipeline, and the per-viseme decay constants. Drafter mirrors the issue verbatim where it pins values.

### Deliverables

| ID | Deliverable | File(s) | Verification |
|---|---|---|---|
| **D1** | Viseme-track API | New `ui/src/audio/lipSyncTrack.ts` | Public exports: `type VowelWeights = { aa: number; ih: number; ou: number; ee: number; oh: number }`; `type VisemeKey = 'sil'\|'PP'\|'FF'\|'TH'\|'DD'\|'kk'\|'CH'\|'SS'\|'nn'\|'RR'\|'aa'\|'E'\|'ih'\|'oh'\|'ou'` (Oculus 15 set per issue); `interface LipSyncTrack { sample(elapsedMs: number): VowelWeights; durationMs: number }`; `function buildHeuristicTrack(text: string, opts?: { rate?: number }): LipSyncTrack \| null`. The track is **immutable + pure** once built. `sample(t)` returns the per-vowel weights at time `t` after applying exponential attack/release blending across the active and previous viseme. Tier-2 fallback: returns `null` on empty / unparseable text. |
| **D2** | Heuristic text → viseme schedule | Inside `lipSyncTrack.ts` | `_textToVisemes(text: string): { viseme: VisemeKey; startMs: number; durationMs: number }[]`. Pure function, no async, no DOM. Approach (drafter picks exact algorithm; recommended baseline): split into words → estimate ~3 phonemes / syllable, ~1.5 syllables / word for English, mean phoneme duration ~80 ms × `1 / rate` → assign each phoneme to its viseme via a lowercase letter → viseme map (vowels `a/o/e/i/u` → `aa/oh/E/ih/ou`; common consonant clusters → `PP / FF / TH / DD / kk / CH / SS / nn / RR / sil`). Drafter pins the letter→viseme table verbatim in the prompt. **Better than amplitude-only, not claiming linguistic accuracy.** Forward marker AD-721b-1 replaces this with rhubarb-derived alignment. |
| **D3** | Multi-mesh vowel collection | `ui/src/components/profile/CrewVRM.tsx` (extend the loader callback at HEAD lines 196–224) | New `vowelShapesRef: Record<VowelKey, string[]>` and `directVowelMeshesRef: Record<VowelKey, { mesh, index }[]>`. Helper `_collectMorphMeshes(scene, candidates: string[]): { mesh, index }[]` extracted from the existing inline traverse block at HEAD lines 213–224. Loader callback calls the helper once per vowel with that vowel's candidate list. **Old `directMouthMeshesRef` and `mouthShapesRef` are NOT removed** — the fallback amplitude path uses them. Reviewer fails any diff that removes either. |
| **D4** | Viseme-weighted driver in `useFrame` | `ui/src/components/profile/CrewVRM.tsx` (rewrite the speaking branch at HEAD lines 247–290) | On `'start'`: build `currentTrackRef = buildHeuristicTrack(e.utterance.text, { rate: e.utterance.rate })`. If `currentTrackRef == null`: keep the existing analyser path verbatim. Otherwise: each frame, call `currentTrackRef.sample(performance.now() - startedAtMs)` → `VowelWeights`. Apply per-vowel exponential smoothing (`smoothedVowelsRef: VowelWeights`, attack k ≈ 0.30 / release k ≈ 0.18 — drafter pins exact constants from `dt`). Write each smoothed weight to its `vowelShapesRef[v]` via `em.setValue` AND to every entry of `directVowelMeshesRef[v]` via `mesh.morphTargetInfluences[index]`. On `'end'`: zero all 5 vowels across ALL meshes (the existing zero-on-end logic at HEAD lines 256–263 must be extended to all 5 vowels — currently zeros only `mouthShapesRef`). |
| **D5** | Tests (Vitest) | New `ui/src/audio/__tests__/lipSyncTrack.test.ts` | ≥ 12 tests covering: (a) viseme→morph mapping for each of the 8 distinct shapes per the issue table (8 tests); (b) `buildHeuristicTrack('')` returns `null` (1 test); (c) `buildHeuristicTrack(invalidText)` Tier-2 fallback returns `null` rather than throwing (1 test); (d) `sample(0) → all-zero` and `sample(durationMs + 100) → all-zero` (1 test, two assertions); (e) cross-blend: between two consecutive visemes the previous decays while the new rises (1 test); (f) attack/release coefficients are different (faster open than close — 1 test). |
| **D6** | Tests (Vitest) — multi-mesh face-split regression | New `ui/src/audio/__tests__/lipSyncTrack.crewVRM.test.tsx` (or extend an existing CrewVRM test if one exists at HEAD; drafter verifies before writing) | Synthetic VRM fixture (mock object with `scene.traverse` exposing 7 mock meshes — 5 of them carrying all 5 vowel morphs in their `morphTargetDictionary`, 2 of them carrying only `Fcl_MTH_A`). Assert `_collectMorphMeshes` returns the correct mesh sets per vowel. Assert that the per-frame write touches every mesh in each per-vowel set. **This is the BF de4107b regression guard for the new code path.** |
| **D7** | Tests (Vitest) — fallback path | Same file as D5 or new `lipSyncTrack.fallback.test.ts` (drafter picks) | When `buildHeuristicTrack` returns `null`, the synthetic-envelope analyser path is exercised. Mock `_attachAnalyserOrSchedule` (it's already exported); assert it's called with the original utterance. Verify the existing AD-721 D5 amplitude path is still wired (regression guard). |

### Wiring

`lipSyncTrack` lives in `ui/src/audio/`. `CrewVRM.tsx` imports `buildHeuristicTrack` and the `VowelWeights` / `VisemeKey` / `LipSyncTrack` types. The lifecycle is owned end-to-end by `CrewVRM`'s existing `onSpeechEvent` subscription — no new subscriber, no new module-level state. `voice.ts` is **unchanged** in this wave; the reserved `'boundary'` event stays reserved.

---

## 5. What this wave does NOT change

| Out-of-scope (forward markers) | AD | Reason |
|---|---|---|
| Real-audio capture via `MediaStreamDestination` of `SpeechSynthesis` | AD-721b-2 | Browser TTS does not route to Web Audio in current Chromium / Firefox; same constraint AD-721 D5 documented. Probably extension-only territory. |
| Server-side rhubarb-lip-sync invocation (`src/probos/audio/lipsync.py`) producing pre-generated tracks | AD-721b-1 | Edge TTS (Wave 137 ruling) does not expose its audio to the runtime. The Python side would have to re-synthesize via a separate engine to analyse — defer until Captain has a workflow in mind. **No Python source touched in this wave.** |
| whisper.cpp WASM tiny.en for offline phoneme alignment of inbound audio | AD-721b-3 | ~75 MB model, separate UX bundle decision. |
| Pitch-driven jaw motion, eyebrow-from-prosody, secondary motion (tongue, etc.) | AD-721c | Issue #529 explicitly defers. |
| Bilingual / non-English phoneme sets | AD-721d-locale (TBD) | English-only first per issue #529. |
| HXI debug visualisation of viseme weights | (not filed) | Captain decides if/when this is worth a separate AD. |
| Voice profile changes, TTS engine swaps, Edge TTS replacements | (Wave 137 ruling) | Edge TTS stays as v1 TTS. |

Reviewer fails the prompt if it touches `voice.ts` (other than reading types), Edge-TTS plumbing, any Python file, or any HXI surface beyond `CrewVRM.tsx`.

---

## 6. Tracking

After AD-721b v1 ships:

1. **PROGRESS.md** — flip the AD-721b row in the Wave 138 section to ✅, append a one-line outcome ("phoneme-weighted 5-vowel driver across all face meshes, heuristic track v1, multi-mesh BF preserved").
2. **docs/development/roadmap.md** — close Wave 138 row; add forward-marker rows for AD-721b-1 (rhubarb backend) and AD-721b-2 (real-audio capture) under the Avatar / HXI section.
3. **DECISIONS.md / decisions-era-4-evolution.md** — append AD-721b entry citing the heuristic-only-for-v1 trade-off and the fallback-to-amplitude guarantee.
4. **GH issue #529** — close with a comment summarising what shipped vs what was deferred (link to AD-721b-1 / AD-721b-2 issue numbers if filed; if not filed in this wave, reference them as "filed at AD-721b-1 / -2 forward markers").

---

## 7. Acceptance criteria (wave-level)

The Builder must, by the end of the wave:

1. ✅ `cd ui && npx vitest run` green, ≥ 12 new tests added per D5–D7.
2. ✅ `pytest tests/ -q -n 4 --dist=loadfile` green and **test count unchanged** (zero Python touched).
3. ✅ `npm run build` (or the project's UI build command) succeeds — no new TypeScript errors, no new ESLint errors.
4. ✅ `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-721b-phoneme-lipsync-v1.md` clean.
5. ✅ Manual smoke (Captain runs after merge): "Hello Captain. Say A. Say E. Say O." produces visibly different mouth shapes between vowels rather than uniform open/close on every avatar.
6. ✅ AD-721 BF de4107b multi-mesh face-split is preserved — D6 regression test enforces this in CI.
7. ✅ Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

If the smoke test (#5) fails — i.e. vowels are still indistinguishable — the wave is incomplete and must be re-opened, not closed. Pass criterion is **Captain's eye**, not the test count.

---

## 8. Risk classification

**LOW** — UI-only, single new file (~250 lines TypeScript), one extended file (`CrewVRM.tsx`), zero new dependencies, zero new model weights, zero new server protocols, zero Python touched. Tier-2 fallback to the AD-721 amplitude path on any failure mode. The only architectural concern is the BF de4107b multi-mesh regression, which D6 tests guard explicitly.

**Risk subcategories:**
- **Bundle size:** zero new MB.
- **Browser compatibility:** unchanged from AD-721 D5 — no new browser APIs.
- **Backend impact:** zero — Python tree untouched, no new endpoints, no migrations.
- **Regression surface:** narrow — `CrewVRM.tsx` mouth animation only. Existing fallback path means a viseme-track failure cannot break speech.

---

## 9. Wave-specific reminders for the prompt drafter

1. **Issue #529 is the source of truth** for the viseme→morph mapping table. Mirror it verbatim in the prompt; do not re-derive.
2. **The 8-row mapping table covers 15 visemes** — the consonant clusters compress to fewer distinct mouth shapes (`PP, FF, TH` → tiny `aa`; `DD, kk, CH, SS, nn, RR` → `ih`). Tests cover one example per row, not all 15 visemes.
3. **`_collectMorphMeshes` is a refactor** of HEAD lines 213–224 — the prompt must keep the existing single-vowel collection behaviourally identical (so the fallback amplitude path stays bit-for-bit compatible). The refactor goes into the prompt as a SEARCH/REPLACE; reviewer verifies.
4. **The `'boundary'` event in `voice.ts` stays reserved.** Do NOT add `utterance.onboundary = ...` in this wave. Forward marker AD-721b-1 / -2 owns boundary wiring.
5. **No emoji in HXI.** Reviewer fails on any emoji literal in the diff (this wave has zero new HXI surfaces, so the rule is trivially satisfied — but flagged for completeness).
6. **Heuristic v1 is the floor, not the ceiling.** The prompt must include the forward-marker section pointing at AD-721b-1 (rhubarb) and AD-721b-2 (real-audio capture). The drafter does NOT need to file those issues in this wave; just leave the markers.
7. **Verify-first.** Before any concrete file/line/method citation in the prompt body, drafter greps HEAD and pastes the result in the prompt's `## Verified Against Codebase (YYYY-MM-DD)` footer. Especially: every line number cited from `CrewVRM.tsx` and `speechAmplitude.ts` MUST have a grep hit shown.

---

## 10. Build groups

Single-prompt wave. No sub-groups, no parallelisable splits. Builder executes `prompts/ad-721b-phoneme-lipsync-v1.md` end-to-end.

**Drafter deliverable:** `prompts/ad-721b-phoneme-lipsync-v1.md` (single file, mirror standard 10-section AD-prompt structure with SEARCH/REPLACE blocks for `CrewVRM.tsx` and full-file content for `lipSyncTrack.ts` + tests).
