# AD-718b — Extra TTS Backends Audit (Coqui / Bark / ElevenLabs)

**Status:** Research-only. **Closes:** #523. **Tests:** +0. **Wave:** 168.

## Problem

Issue #523 (AD-718b) is a Wave 133 forward marker asking us to "replace browser SpeechSynthesis with a server-side TTS pipeline" while preserving the `VoiceProfile` shape (extending with `backend: str` + backend-specific kwargs).

**Status update.** AD-738 (Wave 157) already shipped server-side Piper as the primary offline backend, with the `backend: str` extension point in place (`type TtsStatus = { enabled: boolean; backend: 'browser' | 'piper' | string }` — `voice.ts:134`). AD-718b is no longer "build a new backend" — it is "audit the remaining candidate backends and document a verdict per candidate."

This prompt is a license + capability audit. Pattern from AD-721i-1 (Wave 166 license whitelist) and AD-721i-2 (Wave 167 VRoid evaluation): produce a research doc, file forward markers for any candidates that survive, REJECT any that don't.

## Solution

Produce `docs/research/tts-backends-evaluation.md`. For each of Coqui, Bark, ElevenLabs:

1. License posture (whitelist match per `.github/copilot-instructions.md` Captain rule 2026-05-09).
2. Install footprint (pip deps, model weights size, runtime overhead).
3. Voice quality vs Piper (subjective; cite community benchmarks).
4. Cross-platform support (Windows / Linux / macOS).
5. Verdict: **ABSORB** / **DEFER (forward marker)** / **REJECT**.

NO code. NO pip installs. NO model downloads. Research-only.

## Implementation

### Section 1: Create `docs/research/tts-backends-evaluation.md`

Structure the doc with these sections:

```markdown
# TTS Backends Evaluation (AD-718b, Wave 168)

**Status:** Research audit. **Parent:** AD-738 (Piper, Wave 157). **Closes:** #523.

## Scope

Audit Coqui-TTS, Bark, and ElevenLabs as candidate TTS backends to slot
alongside the AD-738 Piper backend via the `backend: str` extension point
in `ui/src/audio/voice.ts:134` and `src/probos/audio/tts/backends.py`.

License whitelist per `.github/copilot-instructions.md` Captain rule 2026-05-09:
MIT > Apache > BSD > CC0 > MPL-2.0 > CC-BY-4.0. AGPL/GPL rejected.
Paid-license deps rejected for OSS.

## Verdict Summary

| Backend | License | Install footprint | Quality vs Piper | Verdict |
|---------|---------|-------------------|------------------|---------|
| Coqui TTS | MPL-2.0 (lib) — varies per model | ~2 GB models, torch dep | Higher (XTTS v2) | DEFER (forward marker AD-718b-1) |
| Bark | MIT | ~4 GB models, torch dep | Comparable, slower | DEFER (forward marker AD-718b-2) |
| ElevenLabs | Paid commercial API | ~0 (HTTP only) | Higher | REJECT |

## Coqui TTS

(license analysis: lib MPL-2.0 acceptable; some XTTS models are CPML
non-commercial — REJECT those specific weights; document the operator-
visible model whitelist; install footprint; benchmark notes)

## Bark

(license analysis: MIT acceptable; heavy install; quality notes)

## ElevenLabs

(license analysis: paid commercial API; OSS rule rejects)

## Forward markers

- AD-718b-1 (Coqui XTTS v2 backend, MPL-2.0 lib only, CPML weights rejected).
  Trigger: operator demand + community demonstrating an MPL-licensed voice
  set with quality competitive with Piper.
- AD-718b-2 (Bark backend, MIT). Trigger: operator demand + acceptable
  runtime overhead on commodity hardware.
- AD-718b (ElevenLabs branch): NOT FILED. Paid-license; rejected per OSS rule.
  Commercial overlay (private repo) may revisit.
```

The doc must include:
- The verdict-summary table at the top.
- One subsection per backend with: License analysis, Install footprint, Quality, Cross-platform support, Verdict + rationale.
- A forward-marker section listing any AD-718b-N children to file as GitHub issues (one per deferred candidate).

### Section 2: File forward-marker GitHub issues

For each backend with verdict DEFER, file an issue:

```
gh issue create \
  --title "AD-718b-1: Coqui XTTS v2 backend (MPL-2.0 lib, CPML weights rejected)" \
  --body "Forward marker filed by Wave 168 AD-718b audit. ..."
```

For ElevenLabs (REJECT), no issue filed. Document the rejection in the eval doc only.

### Section 3: DECISIONS.md entry

Append:

```markdown
### AD-718b — Extra TTS Backends Audit (Wave 168)

**Date:** 2026-05-17. **Status:** RESEARCH AUDIT — code deferred. **Wave:** 168. **Closes:** [#523](https://github.com/seangalliher/ProbOS/issues/523). **Parent:** AD-738 (Piper TTS, Wave 157).

**Audit deliverable.** `docs/research/tts-backends-evaluation.md` documents license posture, install footprint, voice quality, and verdict for each of Coqui-TTS, Bark, ElevenLabs.

**Verdicts.**

- Coqui-TTS: **DEFER** to AD-718b-1 (MPL-2.0 lib OK; XTTS CPML weights rejected). Heavy install. Quality is higher than Piper for English; multilingual coverage strong. Forward marker filed at #NNN.
- Bark: **DEFER** to AD-718b-2 (MIT). ~4 GB model footprint + torch runtime overhead is the friction; quality is comparable to Piper at higher cost. Forward marker filed at #NNN.
- ElevenLabs: **REJECT.** Paid commercial API conflicts with OSS rule (`.github/copilot-instructions.md` Captain rule 2026-05-09: "never absorb anything requiring a paid license"). Commercial overlay may revisit privately; OSS tree does not integrate.

**No code shipped.** Extension point in `ui/src/audio/voice.ts:134` (`backend: 'browser' | 'piper' | string`) and `src/probos/audio/tts/backends.py` remains open for AD-718b-N implementations when forward-marker triggers fire.
```

## Tests

None. Research-only.

## What this does NOT change

- `src/probos/audio/tts/` — no new backend files.
- `pyproject.toml` — no new pip deps.
- `ui/src/audio/voice.ts` — no new client-side branches.

## Tracking

- New file: `docs/research/tts-backends-evaluation.md`.
- `DECISIONS.md` — append entry above.
- `docs/development/roadmap.md` — update AD-718b row to "Audit shipped Wave 168; forward markers AD-718b-1, AD-718b-2 filed".
- File 2 GitHub issues (Coqui, Bark forward markers). Close #523 with audit-link comment.

## Acceptance Criteria

1. `docs/research/tts-backends-evaluation.md` exists with all 3 candidates evaluated.
2. Verdict summary table at the top of the doc.
3. Forward-marker issues filed for Coqui + Bark (NOT ElevenLabs).
4. `DECISIONS.md` AD-718b entry shipped.
5. `#523` closed with link to the audit doc.
6. Zero new pip deps. Zero new npm deps.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-17)

```
grep "backend" ui/src/audio/voice.ts
  line 134: type TtsStatus = { enabled: boolean; backend: 'browser' | 'piper' | string };

ls src/probos/audio/tts/
  backends.py   1758 bytes  # extension point (registry of backends)
  piper_backend.py  10843 bytes  # AD-738

grep "AD-721i-1" DECISIONS.md  # license whitelist parent
grep "Captain rule 2026-05-09" .github/copilot-instructions.md  # license policy
```
