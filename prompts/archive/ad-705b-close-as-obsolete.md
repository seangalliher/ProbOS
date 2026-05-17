# AD-705b — Close as Obsolete (superseded by AD-738 + AD-718e)

**Status:** Doc-only. **Closes:** #556. **Tests:** +0. **Wave:** 168.

## Problem

Issue #556 (AD-705b) is a Wave 137 forward marker for "Offline TTS (Coqui / Piper)" with two stated triggers:

1. Per-agent voice characters the browser doesn't provide.
2. Airgapped / intranet-only deployment OR Edge cloud TTS unavailability.

Both triggers are **already satisfied** by shipped work:

- **AD-738 (Wave 157)** — Server-streamed TTS via Piper. Fully-offline TTS backend at `src/probos/audio/tts/piper_backend.py` (10,843 bytes, shipped 2026-05-13). Browser path falls back to `SpeechSynthesisUtterance` when backend=browser, but Piper is the offline-capable default once enabled in config. Reference: `DECISIONS.md` line 2420.
- **AD-718e (Wave 166)** — Multi-language voice selection with 27-voice catalog (BF-291). Reference: `DECISIONS.md` line 3688.
- **AD-738e-1 (Wave 158)** — Per-emotion Piper prosody overrides. Reference: `DECISIONS.md` line 2540.

Together these give the operator: (a) a fully-offline TTS engine, (b) per-agent voice selection from a 27-voice catalog, (c) emotional modulation. AD-705b's intent is satisfied without further code.

## Solution

Close #556 as obsolete. Append a one-paragraph supersede entry to `DECISIONS.md`. No code. No tests. No config changes.

## Implementation

### Section 1: DECISIONS.md supersede entry

Append at the end of `DECISIONS.md` (after the highest currently-shipped AD):

```markdown
### AD-705b — Offline TTS (Coqui / Piper) — SUPERSEDED (Wave 168)

**Date:** 2026-05-17. **Status:** SUPERSEDED — closed without separate implementation. **Wave:** 168. **Closes:** [#556](https://github.com/seangalliher/ProbOS/issues/556).

**Disposition.** The Wave 137 forward marker AD-705b ("replace browser SpeechSynthesis with an offline-capable engine such as Coqui or Piper, or expose multiple per-agent voice characters") is satisfied by three already-shipped ADs:

- **AD-738 (Wave 157)** — Server-streamed TTS via Piper. Fully-offline MIT-licensed engine at `src/probos/audio/tts/piper_backend.py`. Browser `SpeechSynthesisUtterance` remains as Tier-2 fallback when `backend=browser`.
- **AD-718e (Wave 166)** — Multi-language voice selection with 27-voice catalog (BF-291). Per-agent `voice_name` selection from server-resolved catalog.
- **AD-738e-1 (Wave 158)** — Per-emotion Piper prosody overrides. AD-718d emotional modulation hook is preserved end-to-end.

**Acceptance audit (per #556 body).**

- License posture clean: Piper is MIT — operator-friendly, no copyleft propagation. Coqui evaluation deferred to AD-718b (Wave 168 research-only audit).
- Operator-install pattern for model files: shipped via `scripts/piper-voice-fetch.ps1` (Wave 165 / BF-291 download script).
- AD-718d emotional modulation: preserved through AD-738e-1 prosody overrides.
- Browser-TTS Tier-2 fallback: preserved in `ui/src/audio/voice.ts` (`backend=browser` default + probe-based escalation).

**No code change required.** Closed for tracking hygiene; the AD number is retired and will not be reused. Coqui/Bark/ElevenLabs evaluation continues under AD-718b (Wave 168).
```

## Tests

None. Doc-only.

## What this does NOT change

- `src/probos/audio/tts/` — untouched.
- `ui/src/audio/voice.ts` — untouched.
- No new ADs, no new tests, no config keys.

## Tracking

- `DECISIONS.md` — append the supersede entry above.
- `PROGRESS.md` — bump highest-AD line if needed (AD-705b is older than highest; no bump).
- `docs/development/roadmap.md` — if AD-705b is listed as open, mark "Closed as obsolete (Wave 168)".
- GitHub: `gh issue close 556 --comment "Superseded by AD-738 (Piper TTS, Wave 157) + AD-718e (multi-language voice catalog, Wave 166) + AD-738e-1 (per-emotion prosody, Wave 158). See DECISIONS.md AD-705b entry. No separate implementation."`

## Acceptance Criteria

1. `DECISIONS.md` contains the AD-705b SUPERSEDED entry.
2. `#556` closed with the supersede comment.
3. If `roadmap.md` references AD-705b as open, mark closed.
4. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-17)

```
ls src/probos/audio/tts/
  -a---  5/15/2026  6:10 PM  10843  piper_backend.py     # AD-738 SHIPPED

grep "AD-738.*Piper" DECISIONS.md
  line 2420: ### AD-738 — Server-streamed TTS via Piper (Wave 157)

grep "AD-718e" DECISIONS.md
  line 3688: ### AD-718e - Multi-language voice selection (Wave 166)

grep "AD-738e-1" DECISIONS.md
  line 2540: ### AD-738e-1 — Per-emotion Piper prosody overrides (Wave 158)

grep "backend" ui/src/audio/voice.ts
  line 134: type TtsStatus = { enabled: boolean; backend: 'browser' | 'piper' | string };

ls scripts/piper-voice-fetch.ps1
  -a---  (BF-291 voice-download script)
```
