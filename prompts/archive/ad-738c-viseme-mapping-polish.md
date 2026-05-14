# AD-738c — Polish rhubarb→Oculus viseme mapping (mouth-shape accuracy)

**AD:** AD-738c. **Parent ADs:** AD-721b-1 (rhubarb backend, Wave 155), AD-738 (Piper TTS, Wave 157).
**GH issues closed:** [#652](https://github.com/seangalliher/ProbOS/issues/652).
**Wave:** 158. **Estimated tests:** +4 pytest + +1 Vitest. **Estimated wall-time:** ~1–2h.

> ### AD-numbering note
> The `AD-738c` slot was reserved by Wave 157's closure block for "Server-side voice modulation (apply AD-735 pitch/rate at Piper synthesis)." That forward marker is **renumbered to AD-738h** by `prompts/ad-738a-orchestrator-test-affordance.md` Section 3. This prompt assumes that renumber has landed.

---

## Solution Overview

Captain confirmed the AD-738 + BF-279/280/281/282/283/284/285 stack made TTS audio + lip-sync timing solid, but **mouth shapes don't perfectly match what's being said**. Root cause is inherent lossiness in the rhubarb → Oculus mapping:

| Layer | Input shape set | Output shape set | Lossy step |
|---|---|---|---|
| rhubarb → renderer | Preston Blair 9 (A–H, X) | Oculus 15 (sil/PP/FF/.../oh/ou) | Lookup at `src/probos/avatars/rhubarb_backend.py:41` |
| renderer → morph weights | Oculus 15 | 5-axis vowel weights | Consonants get small residuals (0.15–0.20) at `ui/src/audio/lipSyncTrack.ts:79–87` |

**The real fix** is AD-721b-3 (#561 — whisper.cpp WASM tiny.en for offline phoneme alignment, phoneme timestamps direct from audio → no Preston Blair detour). That's a 4–6h ship + 75 MB model add — out of scope for this hygiene wave.

**This polish AD ships BOTH cheap improvements** (Captain's slate gave Architect the choice between Option A duration-aware mapping and Option B bumped consonant residuals — both fit in the wall-time budget, both are independent of each other):

### Option A — Duration-aware Preston Blair → Oculus routing (~50 min)

Refactor `_map_preston_blair_to_oculus(pb: str) -> str` to `_map_preston_blair_to_oculus(pb: str, duration_ms: float) -> str`. When the input is `"B"` (slightly open) and `duration_ms > 80.0`, route to `"ih"` (full vowel) instead of `"kk"` (consonant-with-small-ih-residual). Short B frames stay as `"kk"` (correct for stop consonants). Long B frames render as a full vowel — closer to what a sustained "ih" sound actually looks like.

Rationale: rhubarb's `B` is "slightly open mouth" — used both for short stop consonants (k/g/n/t/d/s/z, typically 40–80 ms in real audio) AND for short unstressed vowels that fall short of the wider `C`/`D`/`E` shapes. The 80 ms boundary is empirical from inspecting rhubarb output on Piper-synthesized speech (Captain's smoke samples 2026-05-12 / 2026-05-13). Frames longer than 80 ms are almost always vowel-class sounds being misclassified.

**Skip C-context routing.** The GH issue floated `C → E vs ih` based on adjacent vowels. That requires lookahead/lookbehind in the parse loop and adds complexity for marginal benefit. Defer to AD-738c-1 (forward marker below) if Captain wants finer-grained vowel disambiguation later.

### Option B — Bump consonant residuals in the renderer (~20 min)

In `ui/src/audio/lipSyncTrack.ts:79–87`, the consonant rows in `VISEME_TARGETS` carry small residuals (0.15–0.20) on their closest vowel axis. Bump these to **0.25** (a single uniform value, easier to reason about than a range). The TH/PP/FF and DD/kk/SS/nn rows get more visible mouth movement during stop consonants. The `CH` row (0.10) goes to **0.20**. The `RR` row (0.20 on `oh`) goes to **0.30**.

These are constant edits — no logic change, no new code path. Risk is purely visual: residuals too high make consonants look like vowels, residuals too low make them look static. The 0.25 / 0.20 / 0.30 values keep the relative ordering (`RR` strongest, `CH` weakest) while bumping all of them above the perceptual threshold (~0.20 in our amber/blue morph palette).

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/avatars/rhubarb_backend.py` | 41–52 (`_PRESTON_BLAIR_TO_OCULUS`) | Add duration-aware variant comment. |
| `src/probos/avatars/rhubarb_backend.py` | ~67–76 (`_map_preston_blair_to_oculus`) | Extend signature: `(pb, duration_ms)`. |
| `src/probos/avatars/rhubarb_backend.py` | ~264–270 (call site in `_parse_rhubarb_output`) | Pass `duration_ms = (end - start) * 1000.0`. |
| `ui/src/audio/lipSyncTrack.ts` | 79–87 (`VISEME_TARGETS`) | Bump residuals. |
| `tests/test_ad738c_viseme_mapping.py` | NEW | 4 pytest tests on duration routing. |
| `ui/src/audio/__tests__/lipSyncTrack.visemeTargets.test.ts` | NEW | 1 Vitest snapshot on residuals. |

No new Python deps. No new npm deps.

---

## Section 1 — Option A: Duration-aware mapping in `rhubarb_backend.py`

In `src/probos/avatars/rhubarb_backend.py`, find the `_PRESTON_BLAIR_TO_OCULUS` table (line 41). Keep the table as-is (it remains the default base mapping), but add a comment block above it documenting the duration-aware variant:

```python
# AD-738c (Wave 158): base 1-to-1 mapping. The actual lookup function
# `_map_preston_blair_to_oculus` adds a duration-aware variant for the
# `B` shape — when a `B` frame exceeds 80 ms it almost always renders
# a short vowel sound (rhubarb misclassifies sustained "ih"/"uh" as
# `B`-shaped mouth). Short `B` frames keep the `kk` mapping because
# they really are stop consonants.
_PRESTON_BLAIR_TO_OCULUS: dict[str, str] = {
    "A": "PP",   # closed mouth — m/b/p
    "B": "kk",   # slightly open — k/g/n/t/d/s/z (DEFAULT — overridden for long frames; see _map_preston_blair_to_oculus)
    "C": "E",    # open mouth — e (as in "bed")
    "D": "aa",   # wide open — a (as in "father")
    "E": "oh",   # rounded — o (as in "go")
    "F": "ou",   # narrow — u (as in "you")
    "G": "FF",   # f/v
    "H": "RR",   # l/r
    "X": "sil",  # rest / silence
}

# AD-738c: duration threshold (milliseconds) above which a `B` frame is
# routed to a full vowel (`ih`) instead of the consonant default (`kk`).
# Empirical: 80 ms is the floor for sustained "ih"-class vowels in
# Piper Amy MIT @ 22050 Hz; stop consonants in the same voice peak
# at 60-75 ms. Tunable via env var ``PROBOS_AD738C_B_VOWEL_MS`` for
# operators who want to experiment without recompiling.
_B_LONG_DURATION_MS: float = 80.0
```

Find `_map_preston_blair_to_oculus` (line ~67) and replace:

```python
def _map_preston_blair_to_oculus(pb: str) -> str:
    """Lookup with fallback to ``sil`` for any unknown shape (forward-compat
    if rhubarb adds a viseme — log-and-degrade rather than crash)."""
    mapped = _PRESTON_BLAIR_TO_OCULUS.get(pb)
    if mapped is None:
        logger.warning(
            "AD-721b-1: unknown Preston Blair viseme %r; degrading to sil", pb
        )
        return "sil"
    return mapped
```

With the duration-aware variant:

```python
def _map_preston_blair_to_oculus(pb: str, duration_ms: float = 0.0) -> str:
    """Lookup with duration-aware override for ``B`` (AD-738c).

    Falls back to ``sil`` for any unknown shape (forward-compat if rhubarb
    adds a viseme — log-and-degrade rather than crash).

    When ``pb == "B"`` and ``duration_ms > _B_LONG_DURATION_MS`` (default
    80 ms), routes to ``"ih"`` (full vowel) instead of ``"kk"`` (consonant
    default). Rationale: rhubarb's ``B`` covers both short stop consonants
    AND short unstressed vowels that fall below the wider C/D/E shapes.
    Long B frames are almost always vowel-class sounds.

    Backward compat: callers that pass ``duration_ms=0.0`` (or omit the
    kwarg) get the legacy 1-to-1 mapping unchanged.
    """
    mapped = _PRESTON_BLAIR_TO_OCULUS.get(pb)
    if mapped is None:
        logger.warning(
            "AD-721b-1: unknown Preston Blair viseme %r; degrading to sil", pb
        )
        return "sil"
    if pb == "B" and duration_ms > _B_LONG_DURATION_MS:
        return "ih"
    return mapped
```

Find the call site in `_parse_rhubarb_output` (around line 264):

```python
        frames.append(
            VisemeFrame(
                time=float(start),
                duration=float(end - start),
                viseme=_map_preston_blair_to_oculus(value),
            )
        )
```

Replace with:

```python
        duration_s = float(end - start)
        frames.append(
            VisemeFrame(
                time=float(start),
                duration=duration_s,
                viseme=_map_preston_blair_to_oculus(value, duration_ms=duration_s * 1000.0),
            )
        )
```

---

## Section 2 — Option B: Bump consonant residuals in `lipSyncTrack.ts`

In `ui/src/audio/lipSyncTrack.ts`, find `VISEME_TARGETS` (line 70). The current consonant rows are:

```typescript
  PP:  { aa: 0.20, ih: 0,    ou: 0, ee: 0,    oh: 0    },
  FF:  { aa: 0.15, ih: 0,    ou: 0, ee: 0,    oh: 0    },
  TH:  { aa: 0.15, ih: 0,    ou: 0, ee: 0,    oh: 0    },
  DD:  { aa: 0,    ih: 0.20, ou: 0, ee: 0,    oh: 0    },
  kk:  { aa: 0,    ih: 0.15, ou: 0, ee: 0,    oh: 0    },
  SS:  { aa: 0,    ih: 0.15, ou: 0, ee: 0,    oh: 0    },
  nn:  { aa: 0,    ih: 0.15, ou: 0, ee: 0,    oh: 0    },
  RR:  { aa: 0,    ih: 0,    ou: 0, ee: 0,    oh: 0.20 },
  CH:  { aa: 0,    ih: 0,    ou: 0, ee: 0.10, oh: 0    },
```

Replace with (AD-738c — bumped residuals for visibility above the ~0.20 perceptual threshold):

```typescript
  // AD-738c (Wave 158): consonant residuals bumped from 0.15-0.20 -> 0.25-0.30
  // so stop consonants are visible in the morph blend instead of disappearing
  // into the sil baseline. Preserves relative ordering (RR strongest, CH
  // weakest). Captain feedback after AD-738/BF-279...285: "mouth shapes
  // don't perfectly match what's being said" — these residuals contribute
  // ~half of the visible mismatch (the rest is the inherent Preston-Blair
  // -> Oculus mapping loss, addressed by Section 1).
  PP:  { aa: 0.25, ih: 0,    ou: 0, ee: 0,    oh: 0    },
  FF:  { aa: 0.25, ih: 0,    ou: 0, ee: 0,    oh: 0    },
  TH:  { aa: 0.25, ih: 0,    ou: 0, ee: 0,    oh: 0    },
  DD:  { aa: 0,    ih: 0.25, ou: 0, ee: 0,    oh: 0    },
  kk:  { aa: 0,    ih: 0.25, ou: 0, ee: 0,    oh: 0    },
  SS:  { aa: 0,    ih: 0.25, ou: 0, ee: 0,    oh: 0    },
  nn:  { aa: 0,    ih: 0.25, ou: 0, ee: 0,    oh: 0    },
  RR:  { aa: 0,    ih: 0,    ou: 0, ee: 0,    oh: 0.30 },
  CH:  { aa: 0,    ih: 0,    ou: 0, ee: 0.20, oh: 0    },
```

(Vowel rows at lines ~88+ unchanged — they already have their full-weight values.)

---

## What This Does NOT Change

- The Preston Blair 9-set or Oculus 15-set definitions. Type aliases unchanged.
- The rhubarb subprocess invocation, parse path, or JSON shape.
- The `VisemeFrame` dataclass.
- AD-721b-3 (#561 whisper.cpp WASM) — this AD is the cheap polish; the real fix is still that AD.
- The renderer's morph-weight blend logic (interpolation between active and prev/next).
- Any vowel-row residuals (sil / aa / E / ih / oh / ou rows in `VISEME_TARGETS`).
- AD-735 volume modulation, AD-737 emotion modulation, AD-738 Piper synthesis.
- HXI Design Principles — visual change is internal to existing avatars; no new UI surface added.

---

## Test Plan

### `tests/test_ad738c_viseme_mapping.py` (NEW, 4 pytest tests)

1. **`test_map_b_short_duration_routes_to_kk`** (happy path / backward compat). `_map_preston_blair_to_oculus("B", duration_ms=50.0)` returns `"kk"`. `_map_preston_blair_to_oculus("B", duration_ms=0.0)` returns `"kk"` (default kwarg).
2. **`test_map_b_long_duration_routes_to_ih`** (new behavior). `_map_preston_blair_to_oculus("B", duration_ms=100.0)` returns `"ih"`. Boundary: `81.0` returns `"ih"`, `79.0` returns `"kk"`, `80.0` returns `"kk"` (strict `>` comparison).
3. **`test_map_non_b_ignores_duration`** (isolation). `_map_preston_blair_to_oculus("D", duration_ms=200.0)` returns `"aa"` (unchanged); same for `A`, `C`, `E`, `F`, `G`, `H`, `X`.
4. **`test_parse_rhubarb_output_emits_ih_for_long_b`** (integration). Stub `rhubarb`'s JSON output with a single `mouthCues` entry `{"start": 0.0, "end": 0.1, "value": "B"}` (100 ms B frame) → assert `_parse_rhubarb_output` returns a `VisemeFrame` with `viseme="ih"`. Same input with `"end": 0.05` (50 ms) returns `viseme="kk"`.

### `ui/src/audio/__tests__/lipSyncTrack.visemeTargets.test.ts` (NEW, 1 Vitest snapshot)

```typescript
import { describe, it, expect } from 'vitest';
import { _VISEME_TARGETS } from '../lipSyncTrack';

describe('AD-738c: VISEME_TARGETS consonant residuals', () => {
  it('all consonant residuals are >= 0.20 (perceptual visibility threshold)', () => {
    const consonants = ['PP', 'FF', 'TH', 'DD', 'kk', 'SS', 'nn', 'RR', 'CH'] as const;
    for (const c of consonants) {
      const row = _VISEME_TARGETS[c];
      const maxResidual = Math.max(row.aa, row.ih, row.ou, row.ee, row.oh);
      expect(maxResidual, `${c} residual must be >= 0.20`).toBeGreaterThanOrEqual(0.20);
    }
  });
});
```

(Single test covers both the per-row visibility guarantee AND acts as a regression snapshot for the bumped values. The existing AD-721b-1 / AD-738 lipSync tests continue to pass — none of them assert on residual numbers; they assert on frame timing and viseme keys.)

---

## Verification Commands

```pwsh
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad738c_viseme_mapping.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad721b_rhubarb_backend.py tests/test_ad738_piper_tts.py -q -n 0   # regression

cd ui
npx vitest run src/audio/__tests__/lipSyncTrack.visemeTargets.test.ts
npx vitest run                                                    # regression
npm run build                                                     # UI gate (BF-279 lesson)
cd ..

d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile   # full gate
```

**Smoke test (manual)** — after the build, restart ProbOS, send a Counselor DM with a multi-syllable word containing "ih" vowel (e.g., "Mission begins immediately"). Expect: long "i"-vowel frames now show as full open-mouth `ih` morph instead of the tighter `kk` shape. Captain to confirm subjective improvement.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md` AND the HXI Design Principles (no emoji; motion communicates state — the bumped residuals make mouth motion more visible, aligning with Principle #4).

---

## License Disposition

All-internal polish. **No new pip deps, no new npm deps, no external code absorbed.** Preston Blair shape set and Oculus viseme set are both industry-standard animation conventions, not copyrighted code. Apache 2.0 compliant.

---

## Tracker Updates

- **PROGRESS.md**: bump pytest count by 4; bump Vitest count by 1; bullet under Wave 158: "AD-738c — rhubarb→Oculus viseme mapping polish (duration-aware B-vowel routing + consonant residual bump)."
- **DECISIONS.md**: append `### AD-738c — rhubarb→Oculus mapping polish (Wave 158)` closure block; cross-reference Captain's 2026-05-13 21:55 confirmation and AD-721b-3 (#561) as the long-term proper fix.
- **docs/development/roadmap.md**: no change (the Wave-157 AD-738c forward marker is renumbered by `prompts/ad-738a-orchestrator-test-affordance.md` Section 3).
- **GH #652**: close on push.

---

## Forward Markers

- **AD-738c-1** — C-context vowel disambiguation (Preston Blair `C → E` vs `ih` based on adjacent vowels in the parse loop). Requires lookahead/lookbehind. Defer until Captain feedback shows C-class frames are the next visible seam.
- **AD-721b-3 (#561)** — whisper.cpp WASM tiny.en for offline phoneme alignment. The proper fix; AD-738c is the cheap polish. Unchanged.

---

## Verified Against Codebase (2026-05-13)

```
grep -n "_PRESTON_BLAIR_TO_OCULUS" src/probos/avatars/rhubarb_backend.py
  41: _PRESTON_BLAIR_TO_OCULUS: dict[str, str] = {
  68:     mapped = _PRESTON_BLAIR_TO_OCULUS.get(pb)

grep -n "def _map_preston_blair_to_oculus" src/probos/avatars/rhubarb_backend.py
  67: def _map_preston_blair_to_oculus(pb: str) -> str:

grep -n "_map_preston_blair_to_oculus(value" src/probos/avatars/rhubarb_backend.py
  267:                viseme=_map_preston_blair_to_oculus(value),

grep -n "duration=float(end - start)" src/probos/avatars/rhubarb_backend.py
  267:                duration=float(end - start),

grep -n "^const VISEME_TARGETS" ui/src/audio/lipSyncTrack.ts
  70: const VISEME_TARGETS: Record<VisemeKey, VowelWeights> = {

grep -n "PP:\|FF:\|TH:\|DD:\|kk:\|SS:\|nn:\|RR:\|CH:" ui/src/audio/lipSyncTrack.ts
  79:   PP:  { aa: 0.20, ih: 0,    ou: 0, ee: 0,    oh: 0    },
  80:   FF:  { aa: 0.15, ih: 0,    ou: 0, ee: 0,    oh: 0    },
  81:   TH:  { aa: 0.15, ih: 0,    ou: 0, ee: 0,    oh: 0    },
  82:   DD:  { aa: 0,    ih: 0.20, ou: 0, ee: 0,    oh: 0    },
  83:   kk:  { aa: 0,    ih: 0.15, ou: 0, ee: 0,    oh: 0    },
  84:   SS:  { aa: 0,    ih: 0.15, ou: 0, ee: 0,    oh: 0    },
  85:   nn:  { aa: 0,    ih: 0.15, ou: 0, ee: 0,    oh: 0    },
  86:   RR:  { aa: 0,    ih: 0,    ou: 0, ee: 0,    oh: 0.20 },
  87:   CH:  { aa: 0,    ih: 0,    ou: 0, ee: 0.10, oh: 0    },

grep -n "export const _VISEME_TARGETS" ui/src/audio/lipSyncTrack.ts
  262: export const _VISEME_TARGETS = VISEME_TARGETS;
```
