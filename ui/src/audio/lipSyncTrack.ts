/** AD-721b v1: Heuristic phoneme/viseme lip-sync track.
 *
 *  Pure synchronous text → viseme schedule → per-frame vowel-weight sampler.
 *  Used by ``CrewVRM`` to drive the five VRoid vowel morphs
 *  (``Fcl_MTH_A/I/U/E/O``) across every face mesh that carries them — the
 *  AD-721 BF de4107b multi-mesh face-split fix generalised from a single
 *  ``aa`` axis to all five vowels.
 *
 *  v1 derives the schedule from the utterance text via a length × phoneme-
 *  duration heuristic. Better than amplitude-only; not real linguistic
 *  alignment. Real-audio capture (rhubarb, whisper.cpp, MediaStreamDestination)
 *  is firewalled OFF and re-filed as forward markers AD-721b-1 / AD-721b-2 /
 *  AD-721b-3.
 *
 *  Tier-2 log-and-degrade contract: ``buildHeuristicTrack`` returns ``null`` on
 *  empty / whitespace-only / unparseable text, or on any unexpected throw.
 *  ``CrewVRM`` MUST treat ``null`` as the signal to fall back to the AD-721 D5
 *  amplitude analyser path. Speech must NEVER stop animating because of a
 *  viseme failure.
 */

export type VowelKey = 'aa' | 'ih' | 'ou' | 'ee' | 'oh';

/** Oculus 15-set viseme keys (mirrors GH issue #529). */
export type VisemeKey =
  | 'sil' | 'PP' | 'FF' | 'TH' | 'DD' | 'kk' | 'CH' | 'SS' | 'nn' | 'RR'
  | 'aa' | 'E' | 'ih' | 'oh' | 'ou';

export interface VowelWeights {
  aa: number;
  ih: number;
  ou: number;
  ee: number;
  oh: number;
}

export interface LipSyncTrack {
  /** Returns per-vowel morph weights at time ``elapsedMs`` after speech started.
   *  Pure: deterministic for the same ``elapsedMs``. Out-of-range → all zeros. */
  sample(elapsedMs: number): VowelWeights;
  durationMs: number;
}

export interface BuildOpts {
  /** Speech rate factor — same semantics as ``SpeechSynthesisUtterance.rate``. */
  rate?: number;
}

export interface VisemeSegment {
  viseme: VisemeKey;
  startMs: number;
  durationMs: number;
}

// --- Compile-time constants (drafter-pinned per dispatch §3 / issue #529) ---

const ATTACK_TIME_MS = 50;     // Per-vowel rise to full-open.
const RELEASE_TIME_MS = 100;   // Per-vowel cross-blend / decay window.
const PHONEME_DURATION_MS = 80; // Mean per-phoneme dwell at rate=1.

// --- Letter / digraph → viseme mapping (issue #529 verbatim) ---

const ZERO_WEIGHTS: VowelWeights = Object.freeze({
  aa: 0, ih: 0, ou: 0, ee: 0, oh: 0,
}) as VowelWeights;

/** Per-viseme target vowel weights. Vowels go to 1.0 on their primary axis;
 *  consonants drive a small residual on the closest vowel so the mouth never
 *  snaps fully shut between phonemes. */
const VISEME_TARGETS: Record<VisemeKey, VowelWeights> = {
  sil: { aa: 0,    ih: 0,    ou: 0, ee: 0,    oh: 0    },
  // Vowel visemes:
  aa:  { aa: 1.0,  ih: 0,    ou: 0, ee: 0,    oh: 0    },
  ih:  { aa: 0,    ih: 1.0,  ou: 0, ee: 0,    oh: 0    },
  ou:  { aa: 0,    ih: 0,    ou: 1.0, ee: 0,  oh: 0    },
  E:   { aa: 0,    ih: 0,    ou: 0, ee: 1.0,  oh: 0    },
  oh:  { aa: 0,    ih: 0,    ou: 0, ee: 0,    oh: 1.0  },
  // Consonant visemes (small residual on closest vowel axis):
  // AD-738c (Wave 158): consonant residuals bumped from 0.15-0.20 -> 0.25-0.30
  // so stop consonants are visible in the morph blend instead of disappearing
  // into the sil baseline. Preserves relative ordering (RR strongest, CH
  // weakest). Captain feedback after AD-738/BF-279...285: "mouth shapes
  // don't perfectly match what's being said" — these residuals contribute
  // ~half of the visible mismatch (the rest is the inherent Preston-Blair
  // -> Oculus mapping loss, addressed by rhubarb_backend.py duration-aware B).
  PP:  { aa: 0.25, ih: 0,    ou: 0, ee: 0,    oh: 0    },
  FF:  { aa: 0.25, ih: 0,    ou: 0, ee: 0,    oh: 0    },
  TH:  { aa: 0.25, ih: 0,    ou: 0, ee: 0,    oh: 0    },
  DD:  { aa: 0,    ih: 0.25, ou: 0, ee: 0,    oh: 0    },
  kk:  { aa: 0,    ih: 0.25, ou: 0, ee: 0,    oh: 0    },
  SS:  { aa: 0,    ih: 0.25, ou: 0, ee: 0,    oh: 0    },
  nn:  { aa: 0,    ih: 0.25, ou: 0, ee: 0,    oh: 0    },
  RR:  { aa: 0,    ih: 0,    ou: 0, ee: 0,    oh: 0.30 },
  CH:  { aa: 0,    ih: 0,    ou: 0, ee: 0.20, oh: 0    },
};

/** Greedy-consumed digraphs (checked before single-letter map). */
const DIGRAPHS: ReadonlyArray<[string, VisemeKey]> = [
  ['th', 'CH'],
  ['ch', 'CH'],
  ['sh', 'CH'],
  ['aw', 'oh'],
  ['oo', 'ou'],
  ['ow', 'ou'],
  ['ae', 'E'],
];

/** Single-letter map. ``y`` in vowel position is approximated as ``ih``. */
const LETTER_VISEME: Record<string, VisemeKey> = {
  a: 'aa',
  o: 'oh',
  e: 'E',
  i: 'ih',
  y: 'ih',
  u: 'ou',
  p: 'PP', b: 'PP', m: 'PP',
  f: 'FF', v: 'FF',
  t: 'DD', d: 'DD', n: 'DD', l: 'DD',
  k: 'kk', g: 'kk',
  s: 'SS', z: 'SS', c: 'SS',
  r: 'RR',
  // h/w/j/q/x degrade to a near-silent shape so they don't pulse.
  h: 'sil', w: 'ou', j: 'CH', q: 'kk', x: 'SS',
};

function _cloneZero(): VowelWeights {
  return { aa: 0, ih: 0, ou: 0, ee: 0, oh: 0 };
}

function _lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function _clamp01(x: number): number {
  if (x < 0) return 0;
  if (x > 1) return 1;
  return x;
}

/** Pure text → viseme schedule. Greedy digraph consumption inside each word;
 *  whitespace and unknown punctuation push a ``sil`` segment. Per-segment
 *  duration scales as ``PHONEME_DURATION_MS / rate`` so faster rates produce
 *  proportionally shorter visemes (matches ``SpeechSynthesisUtterance.rate``).
 *
 *  Exported for testing only — ``CrewVRM`` should consume ``buildHeuristicTrack``. */
export function _textToVisemes(
  text: string,
  rate: number = 1.0,
): VisemeSegment[] {
  const out: VisemeSegment[] = [];
  if (!text || typeof text !== 'string') return out;
  const r = rate > 0 ? rate : 1.0;
  const dur = PHONEME_DURATION_MS / r;
  const lower = text.toLowerCase();
  let cursor = 0;

  let i = 0;
  while (i < lower.length) {
    const ch = lower[i];
    // Whitespace / punctuation → silence segment, then advance.
    if (/\s/.test(ch) || /[.,!?;:'"()\[\]{}\-—–]/.test(ch)) {
      out.push({ viseme: 'sil', startMs: cursor, durationMs: dur });
      cursor += dur;
      i += 1;
      continue;
    }
    // Greedy digraph match (two characters).
    let matched = false;
    if (i + 1 < lower.length) {
      const pair = ch + lower[i + 1];
      for (const [d, v] of DIGRAPHS) {
        if (pair === d) {
          out.push({ viseme: v, startMs: cursor, durationMs: dur });
          cursor += dur;
          i += 2;
          matched = true;
          break;
        }
      }
    }
    if (matched) continue;
    // Single-letter map. Unknown characters fall through to ``sil``.
    const v = LETTER_VISEME[ch];
    if (v !== undefined) {
      out.push({ viseme: v, startMs: cursor, durationMs: dur });
    } else {
      out.push({ viseme: 'sil', startMs: cursor, durationMs: dur });
    }
    cursor += dur;
    i += 1;
  }
  return out;
}

/** Find the active segment index at ``elapsedMs`` via linear scan
 *  (schedules are short; binary search is unnecessary overhead). */
function _findActiveIndex(schedule: VisemeSegment[], elapsedMs: number): number {
  if (schedule.length === 0) return -1;
  // Out-of-range left.
  if (elapsedMs < schedule[0].startMs) return -1;
  for (let i = 0; i < schedule.length; i++) {
    const seg = schedule[i];
    if (elapsedMs < seg.startMs + seg.durationMs) return i;
  }
  return -1;
}

/** Build a ``LipSyncTrack`` from utterance text. Returns ``null`` on empty,
 *  whitespace-only, or unparseable text. Tier-2: any thrown exception inside
 *  the body is caught, logged, and returns ``null`` so callers can fall back
 *  to the AD-721 D5 amplitude path. */
export function buildHeuristicTrack(
  text: string,
  opts?: BuildOpts,
): LipSyncTrack | null {
  try {
    if (typeof text !== 'string') return null;
    if (text.length === 0) return null;
    if (text.trim().length === 0) return null;
    const rate = opts?.rate ?? 1.0;
    const schedule = _textToVisemes(text, rate);
    if (schedule.length === 0) return null;
    const last = schedule[schedule.length - 1];
    const durationMs = last.startMs + last.durationMs;

    function sample(elapsedMs: number): VowelWeights {
      // Out-of-range → all zeros (mouth closed before/after speech).
      if (!Number.isFinite(elapsedMs)) return _cloneZero();
      if (elapsedMs < 0 || elapsedMs > durationMs) return _cloneZero();
      const idx = _findActiveIndex(schedule, elapsedMs);
      if (idx < 0) return _cloneZero();
      const active = schedule[idx];
      const activeTarget = VISEME_TARGETS[active.viseme] ?? ZERO_WEIGHTS;
      const prevTarget = idx > 0
        ? (VISEME_TARGETS[schedule[idx - 1].viseme] ?? ZERO_WEIGHTS)
        : ZERO_WEIGHTS;
      // Cross-blend over RELEASE_TIME_MS into the active segment so the
      // previous viseme decays smoothly while the new one rises. Once we're
      // beyond the cross-blend window, weights == active target.
      const dtInto = elapsedMs - active.startMs;
      const blend = _clamp01(dtInto / RELEASE_TIME_MS);
      return {
        aa: _lerp(prevTarget.aa, activeTarget.aa, blend),
        ih: _lerp(prevTarget.ih, activeTarget.ih, blend),
        ou: _lerp(prevTarget.ou, activeTarget.ou, blend),
        ee: _lerp(prevTarget.ee, activeTarget.ee, blend),
        oh: _lerp(prevTarget.oh, activeTarget.oh, blend),
      };
    }

    return { sample, durationMs };
  } catch (err) {
    // Tier-2 log-and-degrade: never throw out of buildHeuristicTrack —
    // CrewVRM falls back to the AD-721 D5 amplitude path on null.
    // eslint-disable-next-line no-console
    console.warn('[AD-721b lipSyncTrack] buildHeuristicTrack failed; falling back to amplitude path', err);
    return null;
  }
}

/** Compile-time constants exposed for testing only. */
export const _CONSTANTS = Object.freeze({
  ATTACK_TIME_MS,
  RELEASE_TIME_MS,
  PHONEME_DURATION_MS,
});

/** Per-viseme targets exposed for testing only. */
export const _VISEME_TARGETS = VISEME_TARGETS;
