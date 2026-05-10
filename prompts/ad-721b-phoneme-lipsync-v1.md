# AD-721b — Phoneme-accurate lip-sync (visemes) v1

**Status:** READY FOR BUILDER
**Wave:** 138
**Dispatch:** [prompts/WAVE-138-DISPATCH.md](prompts/WAVE-138-DISPATCH.md)
**Depends on:** AD-721 D5 (amplitude-only mouth driver, SHIPPED Wave 133), AD-721 BF de4107b (multi-mesh face-split fix), Wave 137 ruling (Edge TTS unchanged)
**Pairs with:** none — single-prompt wave
**Issue:** [#529](https://github.com/seangalliher/ProbOS/issues/529)
**Risk:** **LOW** — UI-only, one new file (~250 LOC TS), one extended file (`CrewVRM.tsx`), zero new deps, zero Python touched. Tier-2 fallback to AD-721 amplitude path on any failure mode.
**Estimated tests:** ≥ 12 Vitest, 0 Python
**Build order:** Single-prompt wave; one commit.

> **Builder:** read `prompts/WAVE-138-DISPATCH.md` for cross-AD context, license posture, and the engineering-principles checklist. Read `prompts/BUILDER-EXECUTION-PLAN.md` for the standing test-gate command, hard-stop rules, and quarantine procedure. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 1. Goal

Counselor (Echo) testing on 2026-05-09 confirmed the AD-721 D5 amplitude-only mouth driver is "the 80% solution" — the mouth opens and closes but vowels are not visually distinguishable. Captain ruled the phoneme-lipsync arc the next definite step. AD-721b v1 ships the next 20%: a **viseme-weighted driver** that animates **all five VRoid vowel morphs** (`Fcl_MTH_A/I/U/E/O`) across **every face mesh** that carries them. The BF de4107b multi-mesh face-split fix applies to all five shapes, not just `aa`.

### Why now (Counselor 2026-05-09)

> "Mouth motion is there — but every vowel looks the same. A and O should not be the same shape."

v1 derives a **synthetic phoneme track from the utterance text** via a length × phoneme-duration heuristic. Better than amplitude-only; not real linguistic alignment. Real-audio capture (whisper.cpp WASM, oculus-lipsync-web) and server-side rhubarb-lip-sync are firewalled OFF and re-filed as forward markers AD-721b-1 / AD-721b-2.

### Backwards-compat guarantee (HARD CONSTRAINT)

When `buildHeuristicTrack(text)` returns `null`/empty (load failure, unparseable text), `CrewVRM` MUST fall back to the existing AD-721 D5 analyser path verbatim. **Speech must NEVER stop animating because of a viseme failure.** Tier-2 log-and-degrade.

---

## 2. Verified Against Codebase (2026-05-09 @ HEAD `8d52f96`)

```
git rev-parse HEAD
  8d52f967a26314c868397ce3c8929c7ede6a5c87

# speechAmplitude.ts — fallback analyser stays as the safety net
grep -n "_attachAnalyserOrSchedule\|FakeAnalyser" ui/src/audio/speechAmplitude.ts
  10: export interface FakeAnalyser {
  19: export function _attachAnalyserOrSchedule(
  21: ): AnalyserNode | FakeAnalyser {
  (file is 56 lines total; synthetic two-band envelope at lines 41-50)

# voice.ts — SpeechEvent shape (unchanged in this wave)
grep -n "SpeechEvent\|onSpeechEvent\|'boundary'" ui/src/audio/voice.ts
  24: export type SpeechEventType = 'start' | 'end' | 'boundary';
  25: export interface SpeechEvent {
  26:   type: SpeechEventType;
  30: type SpeechListener = (e: SpeechEvent) => void;
  35: export function onSpeechEvent(fn: SpeechListener): () => void {

# CrewVRM.tsx — refs + collection block + useFrame driver (the modification surface)
grep -n "directMouthMeshesRef\|mouthShapesRef\|smoothedMouthRef\|_attachAnalyserOrSchedule" \
     ui/src/components/profile/CrewVRM.tsx
   15: import { _attachAnalyserOrSchedule, type FakeAnalyser } from '../../audio/speechAmplitude';
  138: const speakingRef = useRef(false);
  141: const mouthShapesRef = useRef<string[]>([]);
  146: const directMouthMeshesRef = useRef<{ mesh: any; index: number }[]>([]);
  149: const smoothedMouthRef = useRef(0);
  209: mouthShapesRef.current = found;
  224: directMouthMeshesRef.current = direct;
  249: analyserRef.current = _attachAnalyserOrSchedule(e.utterance);
  256: if (em) for (const n of mouthShapesRef.current) em.setValue(n, 0);
  258: for (const { mesh, index } of directMouthMeshesRef.current) {
  291: if (speakingRef.current) {
  306: const k = target > smoothedMouthRef.current ? 0.30 : 0.18;
  321-325: direct-write loop after vrm.update()

# Mouth-shape detection block (single-vowel today)
grep -n "candidates = \['aa'\|morphCandidates" ui/src/components/profile/CrewVRM.tsx
  199: const candidates = ['aa', 'a', 'A', 'Fcl_MTH_A', 'mouth_a', 'M_A'];
  211: const morphCandidates = ['Fcl_MTH_A', 'A', 'a', 'mouth_a', 'M_A', 'aa'];

# No existing lipSyncTrack file (greenfield):
Test-Path ui/src/audio/lipSyncTrack.ts                                       → False
Test-Path ui/src/audio/__tests__/lipSyncTrack.test.ts                        → False
Test-Path ui/src/audio/__tests__/lipSyncTrack.crewVRM.test.tsx               → False

# Existing UI tests directory layout
ls ui/src/audio/__tests__
  voice.test.ts                                    (only one — Builder mirrors its harness style)
ls ui/src/components/profile/__tests__
  (does not exist; D6 lives under ui/src/audio/__tests__/ per dispatch §4 D6)

# UI build / test commands
cd ui && npx vitest run                              (test gate)
cd ui && npm run build                               (build gate)
```

**Dispatch corrections rolled into this prompt:**

1. Dispatch §2 row 1 cited `speechAmplitude.ts` lines 1–58; file is 56 lines. No semantic change — the FakeAnalyser export and `_attachAnalyserOrSchedule` are at the cited offsets.
2. Dispatch §2 row 2 cited `voice.ts` SpeechEvent at lines 23–30; HEAD has the type at line 24, interface at line 25, listener type at line 30. Off-by-one only. The `'boundary'` type member stays reserved.
3. Dispatch §4 D4 said "rewrite the speaking branch at HEAD lines 247–290". The TTS-event `useEffect` is at 244–263; the speaking branch inside `useFrame` is **lines 291–325**. This prompt's SEARCH/REPLACE blocks target the actual ranges (291–325 for the `useFrame` speaking branch; 244–263 for the `useEffect`).
4. Dispatch §2 row 3 said "per-frame write at line 323"; the direct-write loop is at lines 321–325 (`{ const v = smoothedMouthRef.current; for (...) { ... } }` block after `vrm.update(delta)`).

**Phantom-API false-positives** (will appear in pre-check; expected — these are introduced by this prompt):
`buildHeuristicTrack`, `LipSyncTrack`, `VowelWeights`, `VisemeKey`, `_textToVisemes`, `_collectMorphMeshes`, `vowelShapesRef`, `directVowelMeshesRef`, `currentTrackRef`, `smoothedVowelsRef`, `startedAtMs`.

---

## 3. License posture

Apache 2.0 OSS stays Apache 2.0. **Zero new JS dependencies in this wave. Zero new model weights. Zero new ONNX files. Zero new Python deps.**

| Component | License | Adopt? |
|---|---|---|
| Inline heuristic letter→viseme table (this prompt's `_textToVisemes`) | written in-repo | **Yes** — D2 |
| rhubarb-lip-sync (https://github.com/DanielSWolf/rhubarb-lip-sync) | MIT (clean) | **Defer** to **AD-721b-1** (forward marker). Edge TTS does not expose audio frames to JavaScript, so a server-side rhubarb pass would have to re-synthesize via a separate engine. Captain reviews the operator-installed-binary disposition when AD-721b-1 lands. |
| oculus-lipsync-web / openWakeWord-style WASM viseme estimator | mixed | **Defer** to **AD-721b-2** (forward marker). ~75 MB whisper.cpp tiny.en or similar; separate UX bundle decision. |
| `MediaStreamDestination` capture of `SpeechSynthesis` | browser-native | **Defer** to **AD-721b-2**. Browser TTS does not route to Web Audio in current Chromium / Firefox; same constraint AD-721 D5 documented. |

**No paid-license deps. No model weights. No new bundle MB.**

---

## 4. Scope (v1 only) — Deliverables

### D1. New module — `ui/src/audio/lipSyncTrack.ts`

**New file.** Pure TypeScript, no DOM, no `await`, no `import` from `voice.ts` (types are duplicated locally to avoid an audio→audio dep cycle if `voice.ts` ever needs `lipSyncTrack` types).

**Public exports (drafter-pinned API surface):**

```ts
export type VowelKey = 'aa' | 'ih' | 'ou' | 'ee' | 'oh';
export type VisemeKey =
  | 'sil' | 'PP' | 'FF' | 'TH' | 'DD' | 'kk' | 'CH' | 'SS' | 'nn' | 'RR'
  | 'aa' | 'E' | 'ih' | 'oh' | 'ou';   // Oculus 15-set, mirrors issue #529

export interface VowelWeights {
  aa: number; ih: number; ou: number; ee: number; oh: number;
}

export interface LipSyncTrack {
  /** Returns per-vowel morph weights at time `elapsedMs` after speech started.
   *  Pure: deterministic for the same `elapsedMs`. Out-of-range → all zeros. */
  sample(elapsedMs: number): VowelWeights;
  durationMs: number;
}

export interface BuildOpts {
  /** Speech rate factor — same semantics as SpeechSynthesisUtterance.rate. */
  rate?: number;
}

/** Pure synchronous text → viseme schedule → LipSyncTrack.
 *  Returns null on empty / unparseable text (Tier-2 fallback signal). */
export function buildHeuristicTrack(text: string, opts?: BuildOpts): LipSyncTrack | null;

/** Internal — exported only for testing; do NOT call from CrewVRM. */
export function _textToVisemes(
  text: string,
  rate?: number,
): { viseme: VisemeKey; startMs: number; durationMs: number }[];
```

**Compile-time constants** (drafter-pinned; values mirror issue #529):

```ts
const ATTACK_TIME_MS = 50;     // Per-vowel rise: ~50 ms to full-open.
const RELEASE_TIME_MS = 100;   // Per-vowel decay: ~100 ms to full-close.
const PHONEME_DURATION_MS = 80; // Mean per-phoneme dwell at rate=1.
const SYLLABLES_PER_WORD = 1.5; // English heuristic.
const PHONEMES_PER_SYLLABLE = 3;
```

**Letter→viseme table (verbatim mapping; drafter pins; D5 tests one row each):**

| Letter pattern | Viseme | Drives vowel weights |
|---|---|---|
| `a` | `aa` | `aa: 1.0` |
| `o`, `aw` | `oh` | `oh: 1.0` |
| `e`, `ae` | `E` | `ee: 1.0` |
| `i`, `y` (vowel-position) | `ih` | `ih: 1.0` |
| `u`, `oo`, `ow` | `ou` | `ou: 1.0` |
| `p`, `b`, `m` | `PP` | `aa: 0.20` (closed-tight) |
| `f`, `v` | `FF` | `aa: 0.15` |
| `t`, `d`, `n`, `l` | `DD` | `ih: 0.20` |
| `k`, `g` | `kk` | `ih: 0.15` |
| `s`, `z`, `c` (sibilant) | `SS` | `ih: 0.15` |
| `r` | `RR` | `oh: 0.20` |
| `th`, `ch`, `sh` (digraph) | `CH` | `ee: 0.10` |
| ` ` (whitespace), punctuation | `sil` | all 0 |

> The 5 vowel **weight rows** correspond to the 5 morph targets. Consonants drive a small residual weight (10–20 %) on the closest vowel so the mouth doesn't snap fully shut between every phoneme. Reviewer fails any row that flips a vowel weight to negative or > 1.0.

**`sample(elapsedMs)` algorithm (drafter-pinned):**

1. Find the active viseme at `elapsedMs` via binary search of the schedule (sorted by `startMs`).
2. If `elapsedMs < 0` or `elapsedMs > durationMs`, return `{aa:0,ih:0,ou:0,ee:0,oh:0}`.
3. Compute the **target weights** for the active viseme from the table above.
4. Apply per-vowel exponential blend with the **previous-viseme target** (cross-blend window = `RELEASE_TIME_MS`):

   ```
   for each vowel v in {aa, ih, ou, ee, oh}:
     dt_into = elapsedMs - active.startMs
     blend = clamp(dt_into / RELEASE_TIME_MS, 0, 1)
     weights[v] = lerp(prevTarget[v], activeTarget[v], blend)
   ```

5. The cross-blend gives the previous-viseme decay automatically — no separate state. **`sample` is pure** — deterministic for the same `elapsedMs`.

**Tier-2 fallback contract:** wrap the entire body in `try { ... } catch { logger.warn(...); return null }`-equivalent (TypeScript: `console.warn` since UI has no `logger` singleton). Empty text → `null`. Whitespace-only → `null`. Throw → caught, logs, returns `null`. Reviewer fails any uncaught throw.

### D2. Heuristic text → viseme schedule (`_textToVisemes`)

Same file, internal helper (test-exported). Pure function, no async, no DOM.

**Algorithm (drafter-pinned baseline):**

1. Lowercase the text.
2. Tokenize on whitespace.
3. Per character (left-to-right within each word):
   - Look up the letter → viseme map (D1 table). Digraphs (`th`, `ch`, `sh`, `aw`, `oo`, `ae`, `ow`) consumed greedily.
   - Push `{ viseme, startMs: cursor, durationMs: PHONEME_DURATION_MS / rate }`.
   - Advance `cursor += durationMs`.
4. After each word, push `{ viseme: 'sil', startMs: cursor, durationMs: PHONEME_DURATION_MS / rate }`.
5. Final `durationMs = cursor`.

**Rate handling:** divide every `durationMs` by `rate` (default 1.0). Lower rate → longer phonemes (matches `SpeechSynthesisUtterance.rate` semantics).

**Better than amplitude-only; not claiming linguistic accuracy.** Forward marker AD-721b-1 replaces this with rhubarb-derived alignment.

### D3. Multi-mesh vowel collection in `CrewVRM.tsx`

**Modify** `ui/src/components/profile/CrewVRM.tsx`. Extend the loader callback (current single-vowel collection at HEAD lines 196–224) to populate per-vowel mesh sets for ALL FIVE vowels.

**New refs (added beside `mouthShapesRef` at HEAD line 141, `directMouthMeshesRef` at line 146):**

```ts
type VowelKey = 'aa' | 'ih' | 'ou' | 'ee' | 'oh';

// Per-vowel expression-name candidates, cached at load time.
const vowelShapesRef = useRef<Record<VowelKey, string[]>>(
  { aa: [], ih: [], ou: [], ee: [], oh: [] }
);
// Per-vowel direct-mesh entries (BF de4107b multi-mesh fix, generalised).
const directVowelMeshesRef = useRef<Record<VowelKey, { mesh: any; index: number }[]>>(
  { aa: [], ih: [], ou: [], ee: [], oh: [] }
);
// Per-vowel smoothed weight, exponential-blended in useFrame.
const smoothedVowelsRef = useRef<Record<VowelKey, number>>(
  { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 }
);
// Active viseme track (null = fallback to amplitude path).
const currentTrackRef = useRef<import('../../audio/lipSyncTrack').LipSyncTrack | null>(null);
const startedAtMsRef = useRef<number>(0);
```

> **Reviewer flags any diff that removes `mouthShapesRef` or `directMouthMeshesRef`.** Both stay; the fallback amplitude path uses them verbatim.

**New helper** (added near the top of the file, beside `applyExpressionsFromSignals` and friends, NOT inside the component — TypeScript private function in the module scope):

```ts
/** AD-721b: collect every mesh whose morphTargetDictionary contains any of
 *  the candidate names. Refactor of the inline traverse block at HEAD lines
 *  213-224. Used for both the legacy single-vowel `aa` set and the new
 *  per-vowel sets. Behaviourally identical to the old block when called with
 *  the legacy candidate list. */
function _collectMorphMeshes(
  scene: any,
  candidates: string[],
): { mesh: any; index: number }[] {
  const out: { mesh: any; index: number }[] = [];
  scene.traverse((o: any) => {
    if (!o.isMesh || !o.morphTargetDictionary) return;
    for (const key of candidates) {
      if (key in o.morphTargetDictionary) {
        out.push({ mesh: o, index: o.morphTargetDictionary[key] });
        break;
      }
    }
  });
  return out;
}
```

**Per-vowel candidate lists** (drafter-pinned; mirrors VRM 1.0 preset names + VRoid 0.x `Fcl_MTH_*` + lowercase aliases):

```ts
const VOWEL_CANDIDATES: Record<VowelKey, string[]> = {
  aa: ['Fcl_MTH_A', 'A', 'a', 'mouth_a', 'M_A', 'aa'],
  ih: ['Fcl_MTH_I', 'I', 'i', 'mouth_i', 'M_I', 'ih'],
  ou: ['Fcl_MTH_U', 'U', 'u', 'mouth_u', 'M_U', 'ou'],
  ee: ['Fcl_MTH_E', 'E', 'e', 'mouth_e', 'M_E', 'ee'],
  oh: ['Fcl_MTH_O', 'O', 'o', 'mouth_o', 'M_O', 'oh'],
};
```

**SEARCH/REPLACE — refactor inline collection into helper + add per-vowel collection.** Apply in the loader callback. Drafter scope: replace the block whose anchor is `// Collect every mesh with a recognised mouth-open morph target` through `directMouthMeshesRef.current = direct;` (HEAD lines ~210–224).

```
===SEARCH===
        // Collect every mesh with a recognised mouth-open morph target so
        // we can drive them all directly (works around incomplete VRM
        // expression bindings on multi-material face meshes).
        const morphCandidates = ['Fcl_MTH_A', 'A', 'a', 'mouth_a', 'M_A', 'aa'];
        const direct: { mesh: any; index: number }[] = [];
        vrm.scene.traverse((o: any) => {
          if (!o.isMesh || !o.morphTargetDictionary) return;
          for (const key of morphCandidates) {
            if (key in o.morphTargetDictionary) {
              direct.push({ mesh: o, index: o.morphTargetDictionary[key] });
              break;
            }
          }
        });
        directMouthMeshesRef.current = direct;
===REPLACE===
        // Collect every mesh with a recognised mouth-open morph target so
        // we can drive them all directly (works around incomplete VRM
        // expression bindings on multi-material face meshes).
        // AD-721 BF de4107b: legacy single-vowel `aa` set — kept for the
        // fallback amplitude path when buildHeuristicTrack returns null.
        const morphCandidates = ['Fcl_MTH_A', 'A', 'a', 'mouth_a', 'M_A', 'aa'];
        directMouthMeshesRef.current = _collectMorphMeshes(vrm.scene, morphCandidates);

        // AD-721b: per-vowel mesh sets for the viseme-weighted driver.
        // Each vowel gets its own collection across ALL face meshes — the
        // BF de4107b multi-mesh guarantee generalised to all 5 vowels.
        const vowelKeys: VowelKey[] = ['aa', 'ih', 'ou', 'ee', 'oh'];
        for (const v of vowelKeys) {
          directVowelMeshesRef.current[v] = _collectMorphMeshes(
            vrm.scene, VOWEL_CANDIDATES[v]
          );
          // Cache per-vowel expression-manager names (for em.setValue path).
          const known = new Set<string>();
          (em?.expressions ?? []).forEach((x: any) => {
            if (x?.expressionName) known.add(x.expressionName);
          });
          (em?._expressionMap ? Object.keys(em._expressionMap) : [])
            .forEach((n: string) => known.add(n));
          vowelShapesRef.current[v] = VOWEL_CANDIDATES[v].filter(n => known.has(n));
        }
===END REPLACE===
```

> **Behavioural guarantee:** The legacy `aa` set produced by `_collectMorphMeshes(vrm.scene, morphCandidates)` is bit-for-bit identical to the inline-block output (same candidate order, same first-match semantics). D7 fallback test asserts this.

### D4. Viseme-weighted driver in `useFrame`

**Modify** `ui/src/components/profile/CrewVRM.tsx`. Two SEARCH/REPLACE blocks:

**(a) `useEffect` for TTS lifecycle (HEAD lines 244–263) — extend `'start'` and `'end'` for the viseme path:**

```
===SEARCH===
    const off = onSpeechEvent((e) => {
      if (e.agent_id !== agentId) return;
      if (e.type === 'start') {
        analyserRef.current = _attachAnalyserOrSchedule(e.utterance);
        speakingRef.current = true;
      } else if (e.type === 'end') {
        speakingRef.current = false;
        analyserRef.current = null;
        // Close all detected mouth shapes.
        const em = vrmRef.current?.expressionManager;
        if (em) for (const n of mouthShapesRef.current) em.setValue(n, 0);
        // And the direct morph-driven meshes.
        for (const { mesh, index } of directMouthMeshesRef.current) {
          if (mesh.morphTargetInfluences) mesh.morphTargetInfluences[index] = 0;
        }
      }
    });
===REPLACE===
    const off = onSpeechEvent((e) => {
      if (e.agent_id !== agentId) return;
      if (e.type === 'start') {
        // AD-721b: try the heuristic viseme track first; fall back to the
        // AD-721 D5 amplitude analyser path when the track is null/empty.
        const text = e.utterance.text ?? '';
        const rate = e.utterance.rate || 1.0;
        currentTrackRef.current = buildHeuristicTrack(text, { rate });
        startedAtMsRef.current = (typeof performance !== 'undefined'
          ? performance.now() : Date.now());
        // Always wire the analyser too — fallback path needs it AND it costs
        // nothing when the viseme track is active (we just don't read from it).
        analyserRef.current = _attachAnalyserOrSchedule(e.utterance);
        speakingRef.current = true;
      } else if (e.type === 'end') {
        speakingRef.current = false;
        analyserRef.current = null;
        currentTrackRef.current = null;
        // Close all detected mouth shapes (legacy single-vowel set).
        const em = vrmRef.current?.expressionManager;
        if (em) for (const n of mouthShapesRef.current) em.setValue(n, 0);
        for (const { mesh, index } of directMouthMeshesRef.current) {
          if (mesh.morphTargetInfluences) mesh.morphTargetInfluences[index] = 0;
        }
        // AD-721b: zero ALL 5 vowels across ALL meshes (generalises the
        // single-vowel zero above to the new per-vowel sets).
        const vowelKeys: VowelKey[] = ['aa', 'ih', 'ou', 'ee', 'oh'];
        for (const v of vowelKeys) {
          if (em) for (const n of vowelShapesRef.current[v]) em.setValue(n, 0);
          for (const { mesh, index } of directVowelMeshesRef.current[v]) {
            if (mesh.morphTargetInfluences) mesh.morphTargetInfluences[index] = 0;
          }
          smoothedVowelsRef.current[v] = 0;
        }
      }
    });
===END REPLACE===
```

**(b) `useFrame` speaking branch (HEAD lines 291–325) — replace the single-value driver with the viseme-weighted driver, keeping the analyser fallback verbatim when the track is null:**

```
===SEARCH===
    if (speakingRef.current) {
      // Read amplitude from the analyser (real audio when the browser
      // exposes it, otherwise the synthetic envelope from speechAmplitude.ts
      // which already provides word/syllable cadence + boundary gaps).
      let amp = 0;
      if (analyserRef.current) {
        const buf = new Uint8Array(analyserRef.current.frequencyBinCount);
        analyserRef.current.getByteFrequencyData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) sum += buf[i];
        amp = sum / buf.length / 255;
      }
      const target = Math.min(1.0, amp * 1.6);
      // Exponential smoothing so motion reads as natural rather than raw
      // analyser noise. Faster opening (k=0.30) than closing (k=0.18).
      const k = target > smoothedMouthRef.current ? 0.30 : 0.18;
      smoothedMouthRef.current += (target - smoothedMouthRef.current) * k;
      const value = smoothedMouthRef.current;
      const em = vrm.expressionManager;
      if (em) {
        const targets = mouthShapesRef.current.length > 0 ? mouthShapesRef.current : ['aa', 'a', 'A'];
        for (const n of targets) em.setValue(n, value);
      }
    } else if (smoothedMouthRef.current > 0.01) {
      smoothedMouthRef.current *= 0.6;
    }
    // Run expression manager + bone update first.
    vrm.update(delta);
    // Direct-write morph influences AFTER vrm.update() so the expression
    // manager doesn't clobber them on multi-mesh face splits.
    {
      const v = smoothedMouthRef.current;
      for (const { mesh, index } of directMouthMeshesRef.current) {
        if (mesh.morphTargetInfluences) mesh.morphTargetInfluences[index] = v;
      }
    }
===REPLACE===
    if (speakingRef.current) {
      const em = vrm.expressionManager;
      const track = currentTrackRef.current;
      if (track) {
        // AD-721b viseme-weighted path: sample the track at the current
        // elapsed time, smooth per-vowel (faster attack than release), and
        // write each vowel's smoothed weight to its expression name AND to
        // every direct mesh in directVowelMeshesRef.
        const now = (typeof performance !== 'undefined'
          ? performance.now() : Date.now());
        const elapsed = now - startedAtMsRef.current;
        const w = track.sample(elapsed);
        const vowelKeys: VowelKey[] = ['aa', 'ih', 'ou', 'ee', 'oh'];
        for (const v of vowelKeys) {
          const target = w[v];
          // 60-fps coefficients pinned per dispatch §3 (HXI Principle #4):
          // attack ~50 ms (k≈0.30), release ~100 ms (k≈0.18).
          const k = target > smoothedVowelsRef.current[v] ? 0.30 : 0.18;
          smoothedVowelsRef.current[v] +=
            (target - smoothedVowelsRef.current[v]) * k;
          const value = smoothedVowelsRef.current[v];
          if (em) for (const n of vowelShapesRef.current[v]) em.setValue(n, value);
        }
      } else {
        // Tier-2 fallback: AD-721 D5 amplitude path verbatim.
        let amp = 0;
        if (analyserRef.current) {
          const buf = new Uint8Array(analyserRef.current.frequencyBinCount);
          analyserRef.current.getByteFrequencyData(buf);
          let sum = 0;
          for (let i = 0; i < buf.length; i++) sum += buf[i];
          amp = sum / buf.length / 255;
        }
        const target = Math.min(1.0, amp * 1.6);
        const k = target > smoothedMouthRef.current ? 0.30 : 0.18;
        smoothedMouthRef.current += (target - smoothedMouthRef.current) * k;
        const value = smoothedMouthRef.current;
        if (em) {
          const targets = mouthShapesRef.current.length > 0
            ? mouthShapesRef.current : ['aa', 'a', 'A'];
          for (const n of targets) em.setValue(n, value);
        }
      }
    } else if (smoothedMouthRef.current > 0.01) {
      smoothedMouthRef.current *= 0.6;
    }
    // Run expression manager + bone update first.
    vrm.update(delta);
    // Direct-write morph influences AFTER vrm.update() so the expression
    // manager doesn't clobber them on multi-mesh face splits.
    if (currentTrackRef.current) {
      // AD-721b: per-vowel direct write across ALL meshes per vowel.
      const vowelKeys: VowelKey[] = ['aa', 'ih', 'ou', 'ee', 'oh'];
      for (const v of vowelKeys) {
        const value = smoothedVowelsRef.current[v];
        for (const { mesh, index } of directVowelMeshesRef.current[v]) {
          if (mesh.morphTargetInfluences) mesh.morphTargetInfluences[index] = value;
        }
      }
    } else {
      // Fallback: AD-721 BF de4107b legacy single-vowel direct write.
      const v = smoothedMouthRef.current;
      for (const { mesh, index } of directMouthMeshesRef.current) {
        if (mesh.morphTargetInfluences) mesh.morphTargetInfluences[index] = v;
      }
    }
===END REPLACE===
```

> **Two-path discipline:** when the viseme track is active, ONLY the per-vowel direct write runs. When it's null, ONLY the legacy single-vowel direct write runs. They never run together. Reviewer fails any diff that runs both paths in the same frame.

**Import line — add `buildHeuristicTrack` and types** (anchor: HEAD line 15 — the existing `_attachAnalyserOrSchedule` import):

```
===SEARCH===
import { _attachAnalyserOrSchedule, type FakeAnalyser } from '../../audio/speechAmplitude';
===REPLACE===
import { _attachAnalyserOrSchedule, type FakeAnalyser } from '../../audio/speechAmplitude';
import {
  buildHeuristicTrack,
  type LipSyncTrack,
  type VowelKey,
  type VowelWeights,
} from '../../audio/lipSyncTrack';
===END REPLACE===
```

### D5. Tests — `lipSyncTrack` (Vitest, ≥ 9 cases)

**New file:** `ui/src/audio/__tests__/lipSyncTrack.test.ts`. Mirror harness style of the existing `ui/src/audio/__tests__/voice.test.ts`.

| # | Case | Asserts |
|---|---|---|
| 1 | `_textToVisemes('a')` → single `aa` viseme. | weight `aa: 1.0`, others 0. |
| 2 | `_textToVisemes('o')` → single `oh` viseme. | weight `oh: 1.0`, others 0. |
| 3 | `_textToVisemes('e')` → single `E` viseme. | weight `ee: 1.0`, others 0. |
| 4 | `_textToVisemes('i')` → single `ih` viseme. | weight `ih: 1.0`, others 0. |
| 5 | `_textToVisemes('u')` → single `ou` viseme. | weight `ou: 1.0`, others 0. |
| 6 | `_textToVisemes('p')` → `PP` viseme; sampled mid-phoneme. | `aa: 0.20`, others 0. |
| 7 | `_textToVisemes('th')` → `CH` viseme (digraph greedy-consumed). | `ee: 0.10`, others 0. |
| 8 | `_textToVisemes('rr')` → two `RR` visemes back-to-back. | `oh: 0.20` at both timestamps. |
| 9 | `buildHeuristicTrack('')` → `null`. | strict equality. |
| 10 | `buildHeuristicTrack('   ')` (whitespace-only) → `null`. | strict equality. |
| 11 | `sample(-1)` and `sample(durationMs + 100)` → all zeros. | both directions. |
| 12 | Cross-blend: `'ao'` track sampled at the boundary (between `aa`-end and `oh`-start) shows `aa` decaying AND `oh` rising. | `0 < weights.aa < 1.0` AND `0 < weights.oh < 1.0` at boundary; `aa` larger immediately before, `oh` larger immediately after. |
| 13 | Attack faster than release: between two consecutive different-target samples, the rising vowel's k > the decaying vowel's k. | indirectly via observed slope: `(w_after_open - w_before_open) > (w_before_close - w_after_close)` for matched dt. |

**Tier-2 fallback test:** `buildHeuristicTrack` wrapped to throw via spy → test asserts return is `null`, no throw escapes. (Builder picks the spy seam — recommended: monkey-patch `_textToVisemes` via re-export in the test file.)

### D6. Multi-mesh face-split regression (Vitest, ≥ 3 cases)

**New file:** `ui/src/audio/__tests__/lipSyncTrack.crewVRM.test.tsx`. Synthetic VRM fixture — a plain object with a `scene.traverse(callback)` method that yields **7 mock meshes**:

- **Meshes A–E** (5): each carries ALL 5 vowel morphs in `morphTargetDictionary` (e.g. `Fcl_MTH_A: 0`, `Fcl_MTH_I: 1`, ..., `Fcl_MTH_O: 4`) plus a `morphTargetInfluences: [0,0,0,0,0]` array.
- **Meshes F–G** (2): each carries ONLY `Fcl_MTH_A` in `morphTargetDictionary` (the BF de4107b "face-split" pattern — meshes that lost the I/U/E/O bindings during VRoid export).

| # | Case | Asserts |
|---|---|---|
| 14 | `_collectMorphMeshes(scene, VOWEL_CANDIDATES.aa)` returns 7 entries (all meshes carry `Fcl_MTH_A`). | length = 7. |
| 15 | `_collectMorphMeshes(scene, VOWEL_CANDIDATES.ih)` returns 5 entries (only A–E carry `Fcl_MTH_I`). | length = 5; mesh F and G NOT in the result. |
| 16 | After driving `aa: 1.0, ih: 0.5, ou: 0, ee: 0, oh: 0` through the per-vowel direct-write loop (drafter exposes `_collectMorphMeshes` as a test-imported helper), every `aa`-bearing mesh has `morphTargetInfluences[index_aa] = 1.0` and every `ih`-bearing mesh has `morphTargetInfluences[index_ih] = 0.5`. | full per-mesh assertion across all 7 meshes for `aa`, all 5 meshes for `ih`. |

> **This is the BF de4107b regression guard for the new code path.** If `_collectMorphMeshes` ever stops touching every mesh per vowel, this test fails. Reviewer fails any diff that weakens or removes these three cases.

### D7. Fallback path regression (Vitest, ≥ 1 case)

**New file:** `ui/src/audio/__tests__/lipSyncTrack.fallback.test.ts` (or extend D5 if drafter prefers; reviewer agnostic).

| # | Case | Asserts |
|---|---|---|
| 17 | `buildHeuristicTrack` returns `null` for empty text → `_attachAnalyserOrSchedule` is the only animation source. | spy on `_attachAnalyserOrSchedule` (already exported) — assert called once with the same `SpeechSynthesisUtterance`. Assert the legacy single-vowel direct-write path runs (smoothed value > 0 after a few synthetic frames). |

> Total new tests across D5–D7: **17**. Floor: **≥ 12**. Reviewer fails any drop below 12.

### D8. Wiring

`lipSyncTrack` lives in `ui/src/audio/`. `CrewVRM.tsx` imports `buildHeuristicTrack` and the `LipSyncTrack` / `VowelWeights` / `VowelKey` types via the new import line in D4. The lifecycle is owned **end-to-end by `CrewVRM`'s existing `onSpeechEvent` subscription** — no new subscriber, no new module-level state, no changes to `voice.ts`.

> **Reviewer fails any diff that touches `voice.ts`** (including the reserved `'boundary'` type member — it stays reserved for AD-721b-1 / -2).

---

## 5. Non-goals (explicit forward markers)

| Out-of-scope | Forward AD | Reason |
|---|---|---|
| **Server-side rhubarb-lip-sync** producing pre-generated tracks | **AD-721b-1** | Edge TTS (Wave 137 ruling) does not expose its audio to the runtime. The Python side would have to re-synthesize via a separate engine to analyse — defer until Captain has a workflow in mind. **No Python source touched in this wave.** |
| **Real-audio capture** via `MediaStreamDestination` of `SpeechSynthesis` | **AD-721b-2** | Browser TTS does not route to Web Audio in current Chromium / Firefox; same constraint AD-721 D5 documented. Probably extension-only territory. |
| **whisper.cpp WASM tiny.en** for offline phoneme alignment of inbound audio | **AD-721b-3** (filed at first AD-721b-2 review) | ~75 MB model, separate UX bundle decision. |
| **Pitch-driven jaw motion**, eyebrow-from-prosody, secondary motion (tongue, etc.) | **AD-721c** | Issue #529 explicitly defers. |
| **Animation library** (idle / gesture clips) | **AD-721e** | Out of dispatch scope. |
| **Canvas avatar replacement** (move to non-VRM rendering pipeline) | **AD-721f** | Out of dispatch scope. |
| **Bilingual / non-English phoneme sets** | **AD-721d-locale (TBD)** | English-only first per issue #529. |
| **HXI debug visualisation of viseme weights** (mouth-shape inspector / viseme dial) | not filed | Captain decides if/when this is worth a separate AD. v1 ships ZERO new HXI surfaces. |
| **Voice profile changes, TTS engine swaps, Edge TTS replacements** | (Wave 137 ruling) | Edge TTS stays as v1 TTS. |

> **Reviewer fails the prompt if it touches `voice.ts` (other than reading types), Edge-TTS plumbing, any Python file, or any HXI surface beyond `CrewVRM.tsx`.**

---

## 6. Hard-stop conditions (verbatim from dispatch §8 + standing rules)

1. **Phantom API in implementation** (not just in the prompt's expected false-positives list). If `CrewVRM.tsx` references a method that does not exist on the imported module, halt and surface to Architect.
2. **Architectural change required** — modifying `BaseAgent` / `IntentMessage` / cross-layer protocol. Halt; this AD does not authorize architectural changes.
3. **Multi-mesh face-split regression** — if D6 fails OR if the Captain smoke test (acceptance #5) shows any face mesh that previously animated stops animating, the wave halts. **Do not "fix forward."** Revert and surface.
4. **Track generation throws** without being caught — speech must NEVER stop animating because of a viseme failure. The Tier-2 wrap in D1 is non-negotiable; if the test for it (D5 case wrapped via spy) fails, halt.
5. **Diff touches `voice.ts`** (other than reading types via `import type`). Halt; the `'boundary'` event stays reserved.
6. **Diff touches any Python file** under `src/probos/` or `tests/test_*.py`. Halt; this is a UI-only wave.
7. **Diff adds a new dependency** to `ui/package.json`. Halt; zero new deps in this wave.
8. **Diff adds an emoji literal** anywhere in the touched files. Halt (HXI Principle #3).
9. **Working tree integrity** — if `git status` before the build shows tracked-file modifications you did not author, halt and surface to Architect (per BUILDER-EXECUTION-PLAN.md). Do NOT analyze a wiped working tree.

---

## 7. Engineering principles compliance

Builder verifies each in the AD-721b acceptance section. Reviewer flags any miss as **Required**.

- **Tier-2 log-and-degrade** — D1 wraps track generation; D4 falls back to the analyser path on `null`. Tests (D5 #9–10, D7 #17) prove both directions.
- **Open/Closed** — `directVowelMeshesRef` is added alongside `directMouthMeshesRef`; the legacy ref is not mutated. `_collectMorphMeshes` is a refactor of existing behaviour, not a rewrite.
- **DRY** — single-vowel and per-vowel collection share `_collectMorphMeshes`. No copy-paste of the `traverse` block.
- **No private-attr access** — `lipSyncTrack` consumes only public exports; `CrewVRM` does not reach into `speechAmplitude.ts` private state.
- **Async discipline** — `lipSyncTrack` is fully synchronous. No `await`, no `new Promise`. If AD-721b-1 introduces async, that AD owns the change.
- **Configuration** — zero new Pydantic config. UI knobs are compile-time TypeScript constants.
- **No emoji in HXI** — zero emoji in the diff. Reviewer greps.
- **HXI Design Principle #4** — per-vowel exponential smoothing (attack 50 ms, release 100 ms); no pulse / gate / step-function discontinuities. Cross-blend across consecutive visemes.
- **Episodic completeness** — no new episode writes; speech events upstream already drive episodes.
- **Trust + Hebbian alignment** — read-only animation; no trust / Hebbian updates.
- **Test gates** — `cd ui && npx vitest run` green, ≥ 12 new tests; `pytest tests/ -q -n 4 --dist=loadfile` count unchanged.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 8. Tests required (summary)

| File | Min cases |
|---|---|
| `ui/src/audio/__tests__/lipSyncTrack.test.ts` (D5) | ≥ 9 |
| `ui/src/audio/__tests__/lipSyncTrack.crewVRM.test.tsx` (D6) | ≥ 3 |
| `ui/src/audio/__tests__/lipSyncTrack.fallback.test.ts` (D7) | ≥ 1 |
| **Total new Vitest cases** | **≥ 12** (this prompt enumerates 17) |
| New Python tests | **0** (zero Python touched) |

Test gates:

```
cd ui && npx vitest run                                    # MUST be green
cd ui && npm run build                                     # MUST be green
pytest tests/ -q -n 4 --dist=loadfile                      # count UNCHANGED
pwsh scripts/phantom-api-precheck.ps1 prompts/ad-721b-phoneme-lipsync-v1.md
                                                           # only the §2
                                                           # documented
                                                           # false-positives
```

---

## 9. Tracking (post-merge)

1. **`PROGRESS.md`** — flip the AD-721b row in the Wave 138 section to ✅; append one-line outcome ("phoneme-weighted 5-vowel driver across all face meshes, heuristic track v1, multi-mesh BF de4107b preserved").
2. **`docs/development/roadmap.md`** — close Wave 138 row; add forward-marker rows for AD-721b-1 (rhubarb backend) and AD-721b-2 (real-audio capture) under the Avatar / HXI section.
3. **`DECISIONS.md` / `decisions-era-4-evolution.md`** — append AD-721b entry citing the heuristic-only-for-v1 trade-off and the fallback-to-amplitude guarantee.
4. **GH issue #529** — close with a comment summarising what shipped vs what was deferred (link to AD-721b-1 / AD-721b-2 issue numbers if filed; otherwise reference them as "filed at AD-721b-1 / -2 forward markers").

---

## 10. Acceptance criteria (wave-level)

The Builder must, by the end of the wave:

1. ✅ `cd ui && npx vitest run` green; ≥ 12 new tests added per D5–D7 (this prompt enumerates 17).
2. ✅ `pytest tests/ -q -n 4 --dist=loadfile` green and **test count unchanged** (zero Python touched). If it changes, scope leaked outside this wave; reviewer fails.
3. ✅ `cd ui && npm run build` succeeds — no new TypeScript errors, no new ESLint errors.
4. ✅ `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-721b-phoneme-lipsync-v1.md` clean except for the §2-documented false-positives.
5. ✅ Manual smoke (Captain runs after merge): "Hello Captain. Say A. Say E. Say O." produces visibly different mouth shapes between vowels rather than uniform open/close on every avatar.
6. ✅ AD-721 BF de4107b multi-mesh face-split is preserved — D6 regression test enforces this in CI.
7. ✅ Fallback: when `buildHeuristicTrack` returns `null` (empty text, throw, etc.), the AD-721 D5 amplitude-only path is exercised end-to-end. D7 test enforces this in CI.
8. ✅ **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

> If the smoke test (#5) fails — vowels are still indistinguishable — the wave is **incomplete** and must be re-opened, not closed. Pass criterion is **Captain's eye**, not test count alone.

---

## 11. Forward markers (for the next architect)

- **AD-721b-1** — Server-side `rhubarb-lip-sync` integration. Replaces the heuristic `_textToVisemes` with rhubarb-derived per-frame phoneme alignment. Requires the Edge-TTS-or-equivalent re-synthesis decision; may introduce `src/probos/audio/lipsync.py` (or similar). License-clean (MIT). Pairs with operator-installed-binary disposition Captain reviews at filing.
- **AD-721b-2** — Browser-side real-audio capture via `MediaStreamDestination(SpeechSynthesis)` or `getUserMedia` + WASM viseme estimator (oculus-lipsync-web pattern, or whisper.cpp tiny.en — see AD-721b-3). Wires `'boundary'` events in `voice.ts` for the first time.
- **AD-721b-3** — whisper.cpp WASM tiny.en for offline phoneme alignment (~75 MB model). Bundle-size decision deferred.
- **AD-721c** — Pitch-driven jaw motion, eyebrow-from-prosody, secondary motion (tongue, etc.).
- **AD-721d-locale** — Bilingual / non-English phoneme sets.
- **AD-721e** — Animation library (idle / gesture clips).
- **AD-721f** — Canvas avatar replacement (non-VRM rendering pipeline).

---

**End of prompt.** Builder dispatches against this file. Reviewer audits against §6 hard-stop list.
