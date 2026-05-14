# AD-738e-1 — Per-emotion Piper prosody overrides

**AD:** AD-738e-1. **Parent ADs:** AD-738 (Piper TTS, Wave 157), AD-738e (BF-285 prosody knob exposure), AD-737 (custom emotion taxonomy, Wave 156), AD-722a (emotional intent self-tag).
**GH issues closed:** none (this AD was filed as a forward marker in the BF-285 summary; tracking begins here).
**Wave:** 158. **Estimated tests:** +6 pytest + +2 Vitest. **Estimated wall-time:** ~2–3h.

---

## Solution Overview

`TTSConfig` (`src/probos/config.py`) currently has 4 global prosody knobs (`noise_scale`, `length_scale`, `noise_w`, `sentence_silence`) applied uniformly across every utterance. Every Counselor reply sounds the same prosodic shape regardless of whether the agent's parsed intent was `concerned` or `excited`.

Wire AD-737's `EmotionalIntent` taxonomy into per-emotion prosody overrides at synthesis time. Architecture:

1. **`src/probos/audio/tts/prosody.py` (NEW)** — module-level constant `_EMOTION_PROSODY_OVERRIDES: dict[str, dict[str, float]]` mapping each v1 emotion to a partial override dict. Helper `resolve_prosody_overrides(emotion: str | None) -> dict[str, float]` returns `{}` for unknown / missing / `"neutral"` so the backend keeps current defaults (additive — emotions without explicit overrides keep current behaviour).
2. **`TTSBackend` Protocol** — `synthesize(text, emotion: str | None = None)`. Optional kwarg, defaults to `None` for backward compat.
3. **`NullBackend` / `PiperBackend`** — accept the new kwarg; `PiperBackend` consults `resolve_prosody_overrides(emotion)` and merges overrides on top of its constructor defaults for THIS synthesis call only (no instance mutation; the override is per-call).
4. **`routers/avatars.py` (`/api/avatars/tts`)** — POST body accepts optional `"emotion"` field (string); passes to `backend.synthesize(text, emotion=emotion)`. Tier-2 log-and-degrade: bad emotion → ignored.
5. **`routers/agents.py` (chat endpoint)** — after `apply_divergence_check` runs, include the resolved-v1 emotion in the chat response so the browser knows what to pass back to the TTS endpoint.
6. **`ui/src/audio/voice.ts`** — `speakResponse(text, profile, agent_id, emotion?: string)` adds optional `emotion` parameter; passes through to the POST body. Existing callers omit it (backward compat).
7. **Callers of `speakResponse`** — `ProfileChatTab.tsx` (and any other call sites) read the new `emotion` field from chat response and pass it. Tier-2: missing field → omit, server falls back to defaults.

### Override values (Captain's slate)

| Emotion | `noise_scale` | `length_scale` | Rationale |
|---|---|---|---|
| `concerned` | 0.95 | 1.05 | More expression, slightly slower |
| `excited` | 0.95 | 0.92 | Faster, more variation |
| `formal` | 0.70 | 1.0 | Drier, more measured |
| `neutral` | (no override) | (no override) | Keep current defaults — required to satisfy the "additive only" constraint |
| `warm` / `apologetic` / `playful` / `reassuring` | (no override) | (no override) | No Captain-specified values; safe defaults |

`noise_w` and `sentence_silence` are NOT overridden in this AD — keep PiperBackend's current values. Future tuning can add them as forward marker AD-738e-2.

### Custom emotion resolution

AD-737 `custom_emotions` (e.g., `professional_concern → inherits: concerned`) resolve to v1 parent server-side **before** the chat response includes the emotion field. The browser only ever sees v1 names; the TTS endpoint only ever sees v1 names. A new public alias `resolve_emotion_to_v1` is exported from `divergence_detector.py` (wrapping the existing private `_resolve_intent_name`); the chat router imports the alias and reads `runtime.divergence_results[agent_id].intent_emotion`, then applies one extra resolve step to flatten custom→v1.

### Per-emotion vs `applyEmotionalModulation` (existing AD-737 path)

The browser already has `applyEmotionalModulation` in `voice.ts:264-291` that modulates `pitch` / `rate` / `volume` based on agent **signals** (tier-derived, not intent-derived). Per-emotion prosody is **complementary**: signals → browser-side audio post-processing; emotion → server-side Piper subprocess args. The two layers compose without conflict (browser modulation still applies to the served audio via `audio.volume` / `audio.playbackRate`).

---

## Files to Modify

| File | Lines | Why |
|---|---|---|
| `src/probos/audio/tts/prosody.py` | NEW (~50 LOC) | Module-level override table + resolver helper. |
| `src/probos/audio/tts/backends.py` | 33–35 (Protocol) | Add `emotion` kwarg. |
| `src/probos/audio/tts/null_backend.py` | ~18 | Accept and ignore the kwarg. |
| `src/probos/audio/tts/piper_backend.py` | 88 (signature) + ~140-145 (subprocess args) | Apply override at synthesis. |
| `src/probos/routers/avatars.py` | 165–175 (POST endpoint) | Accept `emotion` from body. |
| `src/probos/routers/agents.py` | ~1369–1373 (response dict) | Add `emotion` field. |
| `ui/src/audio/voice.ts` | 167 (signature), ~205-215 (POST body) | Add `emotion` kwarg, include in POST. |
| `ui/src/components/profile/ProfileChatTab.tsx` | ~123 (speakResponse call) | Forward emotion from chat response. |
| `tests/test_ad738e_1_per_emotion_prosody.py` | NEW | 6 pytest tests. |
| `ui/src/audio/__tests__/voice.perEmotion.test.tsx` | NEW | 2 Vitest tests. |

No new pip deps. No new npm deps.

---

## Section 1 — New module: `src/probos/audio/tts/prosody.py`

```python
"""AD-738e-1 — Per-emotion Piper prosody overrides (Wave 158).

Bridges the AD-737 emotion taxonomy into AD-738e's prosody knobs. The
override table is partial — emotions not present get NO override and
PiperBackend keeps its constructor defaults (additive guarantee: no
regression of existing behaviour for utterances without an emotion).

Custom emotions (AD-737) are resolved to v1 parents BEFORE reaching this
module — see ``routers/agents.py`` chat-response wiring.
"""

from __future__ import annotations

from typing import Final


# AD-738e-1 partial override table. Keys are ``EmotionalIntent`` string
# values (lowercase). Values are partial dicts: only the prosody knobs
# that DIFFER from PiperBackend constructor defaults are listed.
# Captain Decision (2026-05-13): bias toward expressiveness for warm-
# class emotions, brevity for excited, dryness for formal.
_EMOTION_PROSODY_OVERRIDES: Final[dict[str, dict[str, float]]] = {
    "concerned": {"noise_scale": 0.95, "length_scale": 1.05},
    "excited":   {"noise_scale": 0.95, "length_scale": 0.92},
    "formal":    {"noise_scale": 0.70, "length_scale": 1.0},
    # ``neutral`` is intentionally absent — keep PiperBackend defaults.
    # Future tuning: ``warm`` / ``apologetic`` / ``playful`` / ``reassuring``
    # may add entries; tracked as forward marker AD-738e-2.
}


def resolve_prosody_overrides(emotion: str | None) -> dict[str, float]:
    """Return per-emotion prosody overrides, or ``{}`` for no override.

    Tier-2 log-and-degrade: unknown / ``None`` / empty string returns
    ``{}`` (no override). Callers merge the result on top of their
    defaults — the empty case preserves current behaviour exactly.

    Custom AD-737 emotions MUST be resolved to v1 parents before
    calling this helper. The helper itself only knows v1 names.
    """
    if not emotion:
        return {}
    return dict(_EMOTION_PROSODY_OVERRIDES.get(emotion, {}))
```

---

## Section 2 — `TTSBackend` Protocol gains `emotion` kwarg

In `src/probos/audio/tts/backends.py` around line 33:

```python
class TTSBackend(Protocol):
    # ...existing docstring...
    name: str

    async def synthesize(self, text: str) -> TTSResult | None:
        """Synthesize ``text`` to audio bytes. Return ``None`` on any failure."""
        ...
```

Replace with:

```python
class TTSBackend(Protocol):
    # ...existing docstring...
    name: str

    async def synthesize(
        self, text: str, emotion: str | None = None
    ) -> TTSResult | None:
        """Synthesize ``text`` to audio bytes. Return ``None`` on any failure.

        AD-738e-1: ``emotion`` is an optional v1 ``EmotionalIntent`` name
        (lowercase) used to apply per-emotion prosody overrides. ``None``
        or unknown names keep backend defaults (additive guarantee).
        """
        ...
```

---

## Section 3 — `NullBackend` accepts and ignores the kwarg

In `src/probos/audio/tts/null_backend.py`, find the existing `synthesize`:

```python
    async def synthesize(self, text: str) -> TTSResult | None:
```

Replace with:

```python
    async def synthesize(
        self, text: str, emotion: str | None = None
    ) -> TTSResult | None:
        # AD-738e-1: ``emotion`` ignored — null backend produces no audio.
        del emotion
```

---

## Section 4 — `PiperBackend` applies overrides per-call

In `src/probos/audio/tts/piper_backend.py` around line 88:

```python
    async def synthesize(self, text: str) -> TTSResult | None:
        """Run piper, return WAV bytes or ``None`` on any failure.
        ...
        """
```

Replace with:

```python
    async def synthesize(
        self, text: str, emotion: str | None = None
    ) -> TTSResult | None:
        """Run piper, return WAV bytes or ``None`` on any failure.

        AD-738e-1: ``emotion`` is an optional v1 ``EmotionalIntent`` name.
        When provided and known, applies per-emotion prosody overrides
        for THIS call only (no instance mutation). Unknown / ``None`` /
        ``"neutral"`` falls through to constructor defaults — additive
        guarantee, no regression for existing call paths.
        """
```

Find the subprocess args block around line 140:

```python
                            "--noise_scale", str(self._noise_scale),
                            "--length_scale", str(self._length_scale),
                            "--noise_w", str(self._noise_w),
                            "--sentence_silence", str(self._sentence_silence),
```

Replace with (compute the merged values just above, then use them):

First, add a module-top import to `src/probos/audio/tts/piper_backend.py` (NOT inside the method body — repo convention is module-top imports; no circular dep here, both modules live under `src/probos/audio/tts/`). In the existing import block at the top of the file, add:

```python
from probos.audio.tts.prosody import resolve_prosody_overrides
```

Then insert ABOVE the `def _run_sync() -> tuple[int, bytes, bytes]:` line (~line 124):

```python
        # AD-738e-1: resolve per-emotion prosody overrides for THIS call.
        # Tier-2 log-and-degrade: bad / unknown emotion falls back to
        # constructor defaults silently.
        _ov = resolve_prosody_overrides(emotion)
        _noise_scale     = _ov.get("noise_scale",     self._noise_scale)
        _length_scale    = _ov.get("length_scale",    self._length_scale)
        _noise_w         = _ov.get("noise_w",         self._noise_w)
        _sentence_silence = _ov.get("sentence_silence", self._sentence_silence)
```

Then replace the four `--noise_scale`/`--length_scale`/`--noise_w`/`--sentence_silence` lines to use the local variables (not `self._*`):

```python
                            "--noise_scale", str(_noise_scale),
                            "--length_scale", str(_length_scale),
                            "--noise_w", str(_noise_w),
                            "--sentence_silence", str(_sentence_silence),
```

(Per-call locals, not instance mutation — preserves backend-instance reuse and concurrency safety.)

---

## Section 5 — `routers/avatars.py` accepts `emotion` from POST body

In `src/probos/routers/avatars.py` around line 165 (`_synthesize_tts_impl`), the current text-extract block is:

```python
    payload = await req.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_body")
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="invalid_text")
    if len(text) > 4096:
        # Defense-in-depth: cap text length at the boundary. ...
        raise HTTPException(status_code=413, detail="text_too_long")

    from probos.audio.tts import select_backend
    backend = select_backend(cfg.backend, cfg)
    result = await backend.synthesize(text)
```

Replace with:

```python
    payload = await req.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_body")
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="invalid_text")
    if len(text) > 4096:
        # Defense-in-depth: cap text length at the boundary. ...
        raise HTTPException(status_code=413, detail="text_too_long")

    # AD-738e-1: optional ``emotion`` is a v1 EmotionalIntent name.
    # Tier-1 boundary validation: non-string / overlong values are
    # silently treated as None (no override). PiperBackend itself
    # validates the name against the override table.
    emotion = payload.get("emotion")
    if not isinstance(emotion, str) or len(emotion) > 64 or not emotion.strip():
        emotion = None

    from probos.audio.tts import select_backend
    backend = select_backend(cfg.backend, cfg)
    result = await backend.synthesize(text, emotion=emotion)
```

---

## Section 5b — Public alias for v1 emotion resolution (`divergence_detector.py`)

In `src/probos/avatars/divergence_detector.py`, immediately below the `_resolve_intent_name` function definition (which ends around line 121, before the `_TAG_STRIP_RE` block), add a public alias so cross-module consumers do NOT import the underscore-prefixed helper:

```python
# AD-738e-1: public alias so cross-module consumers (e.g. ``routers/agents.py``)
# can resolve custom emotion names to their v1 ``EmotionalIntent`` parent
# without reaching into the underscore-prefixed private helper. Same signature,
# same return contract: returns the v1 name, or ``None`` if unresolvable.
resolve_emotion_to_v1 = _resolve_intent_name
```

This is a 3-line additive change in `divergence_detector.py` only. The private `_resolve_intent_name` continues to exist and is still used internally by `compute_divergence` and `apply_divergence_check`; the alias is for external callers.

---

## Section 6 — `routers/agents.py` exposes resolved-v1 emotion

First, add the import to the existing `from probos.avatars` import block near the top of `src/probos/routers/agents.py` (Builder: locate the existing `divergence_detector` import; if none, add a new import line in the standard third-party-then-local order):

```python
from probos.avatars.divergence_detector import resolve_emotion_to_v1
```

Then in `src/probos/routers/agents.py` around line 1369:

```python
    response = {
        "response": response_text,
        "callsign": callsign,
        "agentId": agent_id,
    }
```

Replace with:

```python
    # AD-738e-1: expose the parsed + v1-resolved emotion so the browser
    # can pass it to /api/avatars/tts for per-emotion prosody. Tier-2
    # log-and-degrade: missing divergence result or unresolvable name
    # falls through to ``None`` (browser then omits the field; server
    # applies default prosody). Uses the public ``resolve_emotion_to_v1``
    # alias (AD-738e-1 Section 5b) — no cross-module private access.
    _emotion: str | None = None
    try:
        _dr = getattr(runtime, "divergence_results", None)
        if _dr is not None:
            _result = _dr.get(agent_id)
            if _result is not None:
                _raw = getattr(_result, "intent_emotion", None)
                if isinstance(_raw, str) and _raw:
                    _store = getattr(runtime, "profile_store", None)
                    _custom = None
                    if _store is not None and hasattr(_store, "get"):
                        try:
                            _crew = _store.get(agent_id)
                            _custom = getattr(_crew, "custom_emotions", None) if _crew else None
                        except Exception:
                            _custom = None
                    _emotion = resolve_emotion_to_v1(_raw, _custom) or _raw
    except Exception:
        logger.debug(
            "AD-738e-1: emotion resolution failed for agent=%s", agent_id, exc_info=True,
        )

    response = {
        "response": response_text,
        "callsign": callsign,
        "agentId": agent_id,
        "emotion": _emotion,
    }
```

---

## Section 7 — `ui/src/audio/voice.ts` accepts and forwards emotion

In `ui/src/audio/voice.ts` around line 167, find `speakResponse`:

```typescript
export function speakResponse(
  text: string,
  profile?: VoiceProfile,
  agent_id?: string,
): void {
```

Replace with:

```typescript
export function speakResponse(
  text: string,
  profile?: VoiceProfile,
  agent_id?: string,
  emotion?: string,
): void {
```

In the POST body construction around line 207, find:

```typescript
      const resp = await fetch('/api/avatars/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
```

Replace with:

```typescript
      // AD-738e-1: pass v1 emotion name (resolved server-side) so the
      // TTS endpoint can apply per-emotion prosody. Omit the field when
      // emotion is undefined — server falls back to defaults.
      const _body: { text: string; emotion?: string } = { text };
      if (typeof emotion === 'string' && emotion.length > 0) {
        _body.emotion = emotion;
      }
      const resp = await fetch('/api/avatars/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(_body),
      });
```

---

## Section 8 — Forward emotion from chat response to `speakResponse`

In `ui/src/components/profile/ProfileChatTab.tsx` around line 123, the existing call is:

```typescript
        speakResponse(stripMarkdownForSpeech(reply), voiceProfile ?? undefined, agentId);
```

This is inside the chat-response handler. The chat response is already parsed as a JSON object (search for `await resp.json()` or `setChat(...)` in the file). Find the chat-response object and read `emotion`. The exact handler may have local variables for the response — locate the variable carrying the parsed reply (commonly `data` or `result` near the `await fetch('/api/agents/...')` block) and read `data.emotion`.

Replace the speakResponse call with:

```typescript
        // AD-738e-1: forward parsed emotion (v1 name) so the TTS endpoint
        // applies per-emotion prosody. ``data.emotion`` may be null on
        // older responses or when divergence detection is OFF — pass
        // ``undefined`` so the speakResponse helper omits the field.
        const _emotion = typeof data?.emotion === 'string' && data.emotion.length > 0
          ? data.emotion
          : undefined;
        speakResponse(stripMarkdownForSpeech(reply), voiceProfile ?? undefined, agentId, _emotion);
```

(Builder: if the chat-response variable name is not `data` in this file, substitute the actual name. Grep `await.*\.json\(\)` in `ProfileChatTab.tsx` to find it.)

---

## What This Does NOT Change

- `TTSConfig` Pydantic model. The 4 global prosody knobs stay. Per-emotion overrides ride on top, never replace.
- `NullBackend` audio output (still `None`).
- PiperBackend constructor defaults. The 4 fields and their defaults are unchanged.
- The AD-731 attachment invariant. Audio bytes still flow through AttachmentStore as SHA-256 refs.
- The AD-735 volume / AD-737 emotion-signal browser-side modulation (`applyEmotionalModulation` in `voice.ts:277`). That layer still applies to the served `<audio>` element; per-emotion prosody is a separate server-side layer that composes additively.
- The AD-722a divergence detection self-tag parse path. The chat router reads `runtime.divergence_results[agent_id]` (already populated by `apply_divergence_check`) — no new parse.
- Custom-emotion semantics. Custom names resolve to v1 parents in `routers/agents.py` BEFORE the chat response includes the emotion field; browser never sees custom names.
- HXI Design Principles — no new UI surface added. Audio-only change.
- Backward compat for existing `speakResponse` callers that omit the new `emotion` kwarg. They keep working unchanged.
- AD-738e BF-285 (constructor defaults for `noise_scale` / `length_scale` / `noise_w` / `sentence_silence`). These ARE the fallback baseline — unchanged.
- The shipping `EmotionalIntent` v1 enum and `INTENT_EXPECTED_RULES`. No new emotions added.

---

## Test Plan

### `tests/test_ad738e_1_per_emotion_prosody.py` (NEW, 7 pytest tests)

1. **`test_resolve_prosody_overrides_concerned`** (happy path / per-emotion). `resolve_prosody_overrides("concerned") == {"noise_scale": 0.95, "length_scale": 1.05}`.
2. **`test_resolve_prosody_overrides_neutral_returns_empty`** (additive guarantee). `resolve_prosody_overrides("neutral") == {}`. `resolve_prosody_overrides(None) == {}`. `resolve_prosody_overrides("") == {}`.
3. **`test_resolve_prosody_overrides_unknown_returns_empty`** (error path). `resolve_prosody_overrides("not_an_emotion") == {}`. `resolve_prosody_overrides("FORMAL") == {}` (case sensitivity — table keys are lowercase).
4. **`test_piper_backend_applies_override_at_synthesis`** (integration). Construct `PiperBackend(...)` with explicit defaults. Patch `subprocess.Popen` to capture args. Call `await backend.synthesize("hi", emotion="excited")` → assert args list contains `"--noise_scale", "0.95"` AND `"--length_scale", "0.92"` AND that `--noise_w` / `--sentence_silence` retain the constructor defaults.
5. **`test_piper_backend_no_emotion_uses_defaults`** (backward compat). `await backend.synthesize("hi")` → assert args list contains `"--noise_scale", str(default_noise_scale)` (constructor value, no override applied).
6. **`test_tts_endpoint_forwards_emotion_to_backend`** (boundary — endpoint layer). Use a FastAPI test client + mock backend. POST `/api/avatars/tts` with body `{"text": "hi", "emotion": "concerned"}` → assert the mock backend's `synthesize` was called with `emotion="concerned"`. POST without emotion → assert called with `emotion=None`.
7. **`test_chat_response_includes_resolved_v1_emotion_for_custom_name`** (Section 6 boundary — custom→v1 collapse end-to-end through the chat router). Build a fake runtime with `runtime.divergence_results = {"counselor": DivergenceResult(intent_emotion="professional_concern", applied_fired_rules=(), match_score=1.0, signed_divergence=0.0, magnitude=0.0)}` and a `runtime.profile_store` whose `.get("counselor")` returns an object with `custom_emotions={"professional_concern": EmotionProfile(inherits="concerned", ...)}`. Drive a single chat turn through the agents router (or call the response-assembly path directly if exposed). Assert the response dict's `"emotion"` field equals `"concerned"` (v1, post-resolve) — NOT `"professional_concern"`.

### `ui/src/audio/__tests__/voice.perEmotion.test.tsx` (NEW, 2 Vitest tests)

1. **`speakResponse passes emotion in POST body when provided`** (happy path).
   ```typescript
   // Mock fetch, stub _fetchTtsStatus to return {enabled:true, backend:'piper'}.
   await speakResponseInTestHarness('hello', undefined, 'counselor', 'concerned');
   const postCall = fetchMock.mock.calls.find(c => c[0] === '/api/avatars/tts');
   expect(JSON.parse(postCall[1].body)).toEqual({ text: 'hello', emotion: 'concerned' });
   ```
2. **`speakResponse omits emotion when undefined`** (backward compat).
   ```typescript
   await speakResponseInTestHarness('hello', undefined, 'counselor');
   const postCall = fetchMock.mock.calls.find(c => c[0] === '/api/avatars/tts');
   expect(JSON.parse(postCall[1].body)).toEqual({ text: 'hello' });
   ```

(Both tests should mirror the shape of the existing `voice.serverTts.test.tsx` mocks. Include `voiceMod._resetTtsStatusForTests()` setup since these prime the same module cache.)

---

## Verification Commands

```pwsh
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad738e_1_per_emotion_prosody.py -v -n 0
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad738_piper_tts.py tests/test_ad737_emotion_taxonomy.py tests/test_ad722a_divergence_detector.py -q -n 0   # regression

cd ui
npx vitest run src/audio/__tests__/voice.perEmotion.test.tsx
npx vitest run src/audio/__tests__/voice.serverTts.test.tsx   # regression
npx vitest run                                                # full vitest
npm run build                                                 # UI gate (BF-279 lesson)
cd ..

d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 16 --dist=loadfile   # full pytest gate
```

**Smoke test (manual)** — after restart, send 3 DMs to the Counselor with different emotion triggers (e.g., a casual prompt for `warm`, a worry prompt for `concerned`, a celebratory prompt for `excited`). Confirm:
- The 3 utterances sound *prosodically different* (different speed for excited vs concerned; warm stays at baseline).
- `neutral` / unknown intents preserve today's baseline exactly (regression check).

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## License Disposition

All-internal feature work. **No new pip deps, no new npm deps, no external code absorbed.** Reuses Piper subprocess args already exposed by AD-738e (BF-285). Apache 2.0 compliant.

---

## Tracker Updates

- **PROGRESS.md**: bump pytest count by 7, Vitest count by 2; bullet under Wave 158: "AD-738e-1 — Per-emotion Piper prosody overrides (concerned / excited / formal); additive on top of AD-738e global defaults; custom emotions resolve to v1 parent server-side via the public ``resolve_emotion_to_v1`` alias."
- **DECISIONS.md**: append `### AD-738e-1 — Per-emotion Piper prosody overrides (Wave 158)` closure block. Document the override table verbatim, the additive guarantee, the custom-emotion resolution path, and the AD-738e-2 forward marker.
- **docs/development/roadmap.md**: no change (no prior forward marker for this AD).
- **GH issues**: none to close.

---

## Forward Markers

- **AD-738e-2** — Per-emotion `noise_w` and `sentence_silence` overrides. Captain's slate did not specify values for these; safe to ship later once concerned/excited/formal land and Captain has subjective feedback on what additional axes to tune.
- **AD-738e-3** — Per-agent emotion overrides (Counselor's "concerned" vs Engineer's "concerned" may want different prosody). Today the table is global per emotion. Trigger: operator with > 1 voice-distinct agent reports the same emotion sounds wrong on a different crew member.
- **AD-738e-4** — UI surface to tune the override table from the avatar editor (Captain decision: not now — table edits via code commit are fast enough for the current operator).

---

## Verified Against Codebase (2026-05-13)

```
grep -n "class TTSBackend" src/probos/audio/tts/backends.py
  23: class TTSBackend(Protocol):
grep -n "async def synthesize" src/probos/audio/tts/backends.py src/probos/audio/tts/null_backend.py src/probos/audio/tts/piper_backend.py
  backends.py:33:    async def synthesize(self, text: str) -> TTSResult | None:
  null_backend.py:18:    async def synthesize(self, text: str) -> TTSResult | None:
  piper_backend.py:88:    async def synthesize(self, text: str) -> TTSResult | None:

grep -n "noise_scale\|length_scale\|noise_w\|sentence_silence" src/probos/audio/tts/piper_backend.py
  75:        noise_scale: float = 0.85,
  76:        length_scale: float = 1.0,
  77:        noise_w: float = 1.0,
  78:        sentence_silence: float = 0.35,
  83:        self._noise_scale = noise_scale
  84:        self._length_scale = length_scale
  85:        self._noise_w = noise_w
  86:        self._sentence_silence = sentence_silence
  141:                            "--noise_scale", str(self._noise_scale),
  142:                            "--length_scale", str(self._length_scale),
  143:                            "--noise_w", str(self._noise_w),
  144:                            "--sentence_silence", str(self._sentence_silence),

grep -n "_synthesize_tts_impl\|backend.synthesize(text)" src/probos/routers/avatars.py
  143: async def _synthesize_tts_impl(req: Request, runtime: Any) -> dict[str, Any]:
  167:     result = await backend.synthesize(text)

grep -n "^def _resolve_intent_name\|class EmotionalIntent" src/probos/avatars/divergence_detector.py
  39: class EmotionalIntent(str, Enum):
  94: def _resolve_intent_name(

grep -n "divergence_results\[agent_id\] = result" src/probos/avatars/divergence_detector.py
  454:        div_results[agent_id] = result

grep -n "\"response\": response_text" src/probos/routers/agents.py
  1370:        "response": response_text,

grep -n "export function speakResponse" ui/src/audio/voice.ts
  167: export function speakResponse(

grep -n "speakResponse(stripMarkdown" ui/src/components/profile/ProfileChatTab.tsx
  123:        speakResponse(stripMarkdownForSpeech(reply), voiceProfile ?? undefined, agentId);

grep -n "JSON.stringify({ text })" ui/src/audio/voice.ts
  209:        body: JSON.stringify({ text }),
```
---

## Revision (2026-05-13)

Pass-1 review (`prompts/Reviews/ad-738e-1-per-emotion-prosody-review.md`) flagged one Required finding and three Recommended findings. All folded in.

**Required R1 \u2014 cross-module private import + fabricated authorization claim.** Reviewer offered two fix options: (a) cross-prompt synergy with AD-737a adding `resolved_v1_emotion: str | None` to `DivergenceResult`, or (b) public alias in `divergence_detector.py`. **Chose option (b)** \u2014 single-prompt, additive 3-line alias, no frozen-dataclass field-ordering surgery, no AD-737a coordination required for an overnight wave. Option (a) would have touched three surfaces (frozen dataclass + constructor at line 320 + `apply_divergence_check` `dataclasses.replace`) for one derived value. AD-737a is NOT modified by this revision.

Changes:
- **New Section 5b** adds `resolve_emotion_to_v1 = _resolve_intent_name` as a public alias in `divergence_detector.py` immediately below the private helper (around line 121). Same signature, same return contract; alias is for external callers; private `_resolve_intent_name` continues to be used internally by `compute_divergence` / `apply_divergence_check`.
- **Section 6 rewritten** to import `resolve_emotion_to_v1` at module-top in `routers/agents.py` and call the alias instead of the underscore helper. Removed the fabricated "AD-737a doc-contract section explicitly authorizes import for v1 resolution" parenthetical.
- **Goals/blurb updated** to reference the public alias rather than the private name.

**Recommended #1 \u2014 missing chat-router boundary test.** Folded in as Test 7 (`test_chat_response_includes_resolved_v1_emotion_for_custom_name`). Test count bumped 6 \u2192 7; PROGRESS.md tracker line updated accordingly.

**Recommended #2 \u2014 inline import smell in Section 4.** Folded in. Section 4 now instructs Builder to add `from probos.audio.tts.prosody import resolve_prosody_overrides` to the module-top import block of `piper_backend.py`, and removes the inline import from the synthesize-body insertion.

**Recommended #3 \u2014 32-char emotion cap unjustified.** Folded in. Section 5 bumped `len(emotion) > 32` \u2192 `len(emotion) > 64` to comfortably cover custom emotion name pass-through while preserving defense-in-depth.

**Nits 1\u20135 from pass-1.** All deferred \u2014 either resolved naturally by the Required fix (Nit 1: 18-line Section 6 stays at 18 lines but no longer reaches into private; the value here is correctness, not LOC) or non-blocking style preferences (Nit 2 `_body` naming; Nit 3 confirmed-correct `data` variable; Nits 4\u20135 already-verified).

**Scope guard.** Revision touches AD-738e-1 only. AD-737a is unchanged. No new sections beyond 5b. No expansion to forward markers (AD-738e-2/-3/-4 unchanged).