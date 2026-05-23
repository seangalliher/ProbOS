# AD-826 — Whisper-first STT priority for cross-browser voice reliability

**Status:** Ready for Builder
**Closes:** https://github.com/seangalliher/ProbOS/issues/767
**Depends on:** AD-705a (`cognitive.offline_stt_enabled` + `whisperStt.ts`), AD-721b-3 (`whisper_model_path` + `resolve_whisper_model_path`), AD-760 (current empty-counter whisper fallback in `ProfileChatTab.tsx`)
**Estimated tests:** 6 backend + 5 frontend
**Risk:** Medium — inverts the default STT path. Default-OFF transitional gate per Wave 10 convention #14 is NOT viable here; the goal IS to flip the default to whisper. Mitigation: operator can revert with one config line (`cognitive.primary_stt: browser`).

---

## ⚠️ Read before drafting any code

The issue body assumes a backend-subprocess whisper architecture. **It is wrong.** Verified facts from the live codebase (2026-05-22):

1. **Whisper is browser-side WASM, not a backend subprocess.** `ui/src/audio/whisperLoader.ts:110` `loadWhisperModel()` fetches `ggml-tiny.en.bin` + the whisper.cpp WASM glue and runs inference inside the browser. Audio bytes NEVER reach the runtime — privacy invariant documented at `ui/src/audio/whisperStt.ts:12-15`.
2. **There is no `VoiceConfig` class.** Voice/STT settings live under `CognitiveConfig` (`src/probos/config.py`). Existing siblings: `cognitive.whisper_model_path` (line 253), `cognitive.offline_stt_enabled` (line 270). AD-826 must extend `CognitiveConfig`, NOT create a new `VoiceConfig`.
3. **BF-280 (`_run_sync` subprocess pattern) and BF-282 (tempfile-not-stdout) DO NOT apply.** No new subprocess is created by this prompt.
4. **The existing `/api/voice` router lives at `src/probos/routers/voice.py`.** It currently serves only wake-word training endpoints. The new `/api/voice/health` endpoint hangs off this router.
5. **Health is artifact + config availability, not a subprocess probe.** The endpoint checks: (a) `cognitive.offline_stt_enabled == True`, (b) `resolve_whisper_model_path(...)` returns a non-None Path. No model invocation, no caching needed (filesystem stat is microsecond-cheap; cache only if profiling shows hot-path overhead).
6. **Frontend reads config via `s.snapshot?.config?.cognitive?.*`** — see `ui/src/components/IntentSurface.tsx:92` and `ui/src/components/perception/CameraLiveIndicator.tsx:78` for the canonical pattern. No new `/api/config` work needed. AD-826 adds `s.snapshot?.config?.cognitive?.primary_stt`.

---

## Problem

Today's voice testing (2026-05-22) revealed Edge's Web Speech API is significantly less reliable than Chrome's — sessions silently die, results return empty, no errors fire. The current PTT handler in `ProfileChatTab.tsx:770-880` arms browser SpeechRecognition first; whisperStt is reached only after two consecutive empty transcripts via the AD-760 empty-counter fallback. Operators on Edge / Firefox / Safari hit the empty-counter ceiling repeatedly before voice works.

The local whisper.cpp WASM path works consistently across every browser that ships SharedArrayBuffer + WebAssembly (all major browsers, current versions). Inverting the order — whisper primary, browser SR fallback — makes voice reliable everywhere AND aligns with ProbOS's local-first philosophy (audio never leaves the device).

## Solution overview

1. New `cognitive.primary_stt: Literal["whisper", "browser"]` field, default `"whisper"`.
2. New `cognitive.fallback_stt_enabled: bool` field, default `True` (whisper-primary mode falls back to browser SR after 2 empty whisper transcripts; mirror image of AD-760).
3. New `GET /api/voice/health` endpoint returning `{healthy, engine, backend_available, primary_stt}`. No subprocess; pure artifact + config check.
4. Section-registry entries for both new fields (hot-reload where appropriate).
5. Frontend `ProfileChatTab.tsx` PTT handler routes by `cognitive.primary_stt` + health endpoint result.
6. Per-engine empty-transcript counters (separate `emptyWhisperCountRef` from existing `emptyTranscriptCountRef` for browser SR).

---

## Section 1: `CognitiveConfig` fields (`src/probos/config.py`)

Insert AFTER the existing `offline_stt_enabled` field at line 270 and BEFORE `conversation_mode_enabled` at line 274.

### SEARCH/REPLACE

```python
===SEARCH===
    # When False (default) OR artifacts absent, the browser-native
    # ``SpeechRecognition`` path remains primary (AD-705 v1 fallback —
    # cloud-routed on Chrome; privacy-conscious operators set this to
    # True AND disable the wake-word loop to go fully offline).
    # Hot-reload via the BF-308 settings watcher.
    offline_stt_enabled: bool = False

    # AD-747 — Always-on conversation mode (LiveKit VoicePipelineAgent
===REPLACE===
    # When False (default) OR artifacts absent, the browser-native
    # ``SpeechRecognition`` path remains primary (AD-705 v1 fallback —
    # cloud-routed on Chrome; privacy-conscious operators set this to
    # True AND disable the wake-word loop to go fully offline).
    # Hot-reload via the BF-308 settings watcher.
    offline_stt_enabled: bool = False

    # AD-826 — Primary STT engine. ``whisper`` (default) routes PTT and
    # conversation-mode utterances through the AD-705a browser-side
    # whisper.cpp WASM path first; browser ``SpeechRecognition`` is the
    # fallback (mirror image of AD-760's empty-counter logic). Set to
    # ``browser`` to preserve pre-AD-826 behavior (browser SR primary,
    # whisper after 2 empty transcripts). Hot-reload.
    primary_stt: Literal["whisper", "browser"] = Field(
        default="whisper",
        description=(
            "AD-826: which STT engine the UI PTT handler arms first. "
            "whisper = local whisper.cpp WASM (cross-browser, privacy-"
            "aligned). browser = Web Speech API (Chrome-only reliable; "
            "flaky on Edge/Firefox/Safari). When whisper is selected "
            "AND artifacts/config are unavailable, the UI honest-"
            "degrades to the browser engine. Hot-reload."
        ),
    )
    # AD-826: enable the cross-engine fallback (whisper→browser when
    # primary=whisper, browser→whisper when primary=browser). Defaults
    # to True; set False to lock the primary engine with no cross-over.
    fallback_stt_enabled: bool = Field(
        default=True,
        description=(
            "AD-826: when True, two consecutive empty transcripts from "
            "the primary STT engine fall through to the other engine "
            "for the next press. When False, the primary engine is the "
            "only path and empty transcripts are surfaced as-is. "
            "Hot-reload."
        ),
    )

    # AD-747 — Always-on conversation mode (LiveKit VoicePipelineAgent
===END REPLACE===
```

**`Literal` import:** `src/probos/config.py` already imports `Literal` (used elsewhere in the file). Builder: confirm with `grep -n "from typing import" src/probos/config.py`. If `Literal` is absent from the import line, extend the existing `from typing import ...` statement; do NOT add a new import line.

---

## Section 2: Section-registry entries (`src/probos/settings/section_registry.py`)

Insert AFTER the existing `cognitive.offline_stt_enabled` `FieldDescriptor` (which ends at the closing parenthesis of its block, currently at line 137).

### SEARCH/REPLACE

```python
===SEARCH===
            FieldDescriptor(
                "cognitive.offline_stt_enabled",
                "Offline STT (whisper.cpp WASM)",
                "bool",
                description=(
                    "AD-705a: when enabled, the VAD-bounded utterance "
                    "is transcribed locally via the operator-pulled "
                    "whisper.cpp WASM artifacts. When disabled (default) "
                    "or artifacts absent, the browser-native "
                    "SpeechRecognition path remains primary."
                ),
                hot_reload=True,
            ),
            # AD-747 — Always-on conversation mode.
===REPLACE===
            FieldDescriptor(
                "cognitive.offline_stt_enabled",
                "Offline STT (whisper.cpp WASM)",
                "bool",
                description=(
                    "AD-705a: when enabled, the VAD-bounded utterance "
                    "is transcribed locally via the operator-pulled "
                    "whisper.cpp WASM artifacts. When disabled (default) "
                    "or artifacts absent, the browser-native "
                    "SpeechRecognition path remains primary."
                ),
                hot_reload=True,
            ),
            # AD-826 — Whisper-first STT priority.
            FieldDescriptor(
                "cognitive.primary_stt",
                "Primary STT engine",
                "text",
                description=(
                    "AD-826: which STT engine PTT arms first. "
                    "'whisper' (default) = local whisper.cpp WASM, "
                    "cross-browser reliable. 'browser' = Web Speech "
                    "API (Chrome-only reliable). Hot-reload."
                ),
                hot_reload=True,
            ),
            FieldDescriptor(
                "cognitive.fallback_stt_enabled",
                "Cross-engine STT fallback",
                "bool",
                description=(
                    "AD-826: when True, two consecutive empty "
                    "transcripts from the primary engine route the "
                    "next press through the other engine. Hot-reload."
                ),
                hot_reload=True,
            ),
            # AD-747 — Always-on conversation mode.
===END REPLACE===
```

---

## Section 3: `GET /api/voice/health` (`src/probos/routers/voice.py`)

Append a new endpoint to the existing `router` defined at line 37. Imports already present: `APIRouter`, `Depends`, `HTTPException`, `Request`, `get_runtime`. New import needed: `resolve_whisper_model_path`.

### SEARCH/REPLACE

```python
===SEARCH===
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
from probos.voice.wake_word_trainer import WakeWordTrainer, WakeWordTrainingReport

logger = logging.getLogger("probos.routers.voice")

router = APIRouter(prefix="/api/voice", tags=["voice"])
===REPLACE===
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
from probos.voice.wake_word_trainer import WakeWordTrainer, WakeWordTrainingReport
from probos.voice.whisper_model import resolve_whisper_model_path

logger = logging.getLogger("probos.routers.voice")

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.get("/health")
async def get_voice_health(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """AD-826 — STT engine availability for the UI PTT handler.

    Returns the operator's ``cognitive.primary_stt`` selection plus an
    honest health probe for the whisper engine. Probe is filesystem-
    only: confirms ``cognitive.offline_stt_enabled`` is True AND the
    operator-pulled GGML model file exists. NO subprocess, NO model
    invocation — whisper inference runs in the browser per AD-705a.

    Response shape::

        {
          "primary_stt": "whisper" | "browser",
          "engine": "whisper" | "browser",      # primary_stt mirror
          "backend_available": bool,             # whisper artifact present
          "healthy": bool,                       # primary engine usable
        }

    ``healthy`` semantics:
    * ``primary_stt == "whisper"``: True iff ``backend_available``.
    * ``primary_stt == "browser"``: always True (the UI knows whether
      Web Speech API is supported in the current browser; backend
      cannot probe that).
    """
    config = runtime.config
    primary = config.cognitive.primary_stt
    offline_enabled = bool(config.cognitive.offline_stt_enabled)
    model_path = resolve_whisper_model_path(config, runtime.data_dir)
    backend_available = offline_enabled and model_path is not None
    if primary == "whisper":
        healthy = backend_available
    else:
        healthy = True
    return {
        "primary_stt": primary,
        "engine": primary,
        "backend_available": backend_available,
        "healthy": healthy,
    }
===END REPLACE===
```

**Note:** This endpoint is intentionally NOT gated by `require_crew_scope`. The HXI fetches it on every chat-tab mount; gating would force a no-op auth check on every operator session. The response contains no secrets — only public config selectors and a filesystem-presence boolean. If review disagrees, move it under the dependency.

---

## Section 4: Frontend PTT handler (`ui/src/components/profile/ProfileChatTab.tsx`)

### 4a. New imports + state

Add the voice-health fetch and state hook near the top of the component, alongside the existing config-snapshot reads.

### SEARCH/REPLACE (Builder: locate the imports block at the top of the file)

```typescript
===SEARCH===
import { startListening, stopListening, isSpeechRecognitionSupported } from '../../audio/speechInput';
===REPLACE===
import { startListening, stopListening, isSpeechRecognitionSupported } from '../../audio/speechInput';
// AD-826 — voice-health response shape (mirror of /api/voice/health).
interface VoiceHealth {
  primary_stt: 'whisper' | 'browser';
  engine: 'whisper' | 'browser';
  backend_available: boolean;
  healthy: boolean;
}
===END REPLACE===
```

### 4b. Voice-health useEffect

Inside the `ProfileChatTab` component body, AFTER the existing `useState` declarations and BEFORE the first `useEffect`. Builder: locate `const [listening, setListening] = useState(false);` (search for `setListening(false)`); insert immediately AFTER the last `useState` in that cluster.

```typescript
// AD-826 — fetch voice-health on mount. The health endpoint is cheap
// (filesystem stat); we refetch when the agent changes so a swap to
// a tab with different STT settings honors the new config.
const [voiceHealth, setVoiceHealth] = useState<VoiceHealth | null>(null);
useEffect(() => {
  let cancelled = false;
  (async () => {
    try {
      const res = await fetch('/api/voice/health');
      if (!res.ok) return;
      const data = (await res.json()) as VoiceHealth;
      if (!cancelled) setVoiceHealth(data);
    } catch {
      // Tier-2 honest-degrade — without health data, the PTT handler
      // falls through to the AD-760 browser-primary path. The console
      // already logs network errors via the browser; no extra log here.
    }
  })();
  return () => { cancelled = true; };
}, [agentId]);
```

### 4c. Per-engine empty-transcript counter

The existing `emptyTranscriptCountRef` (search the file) counts browser SR empties only. Add a parallel counter for whisper empties.

Builder: locate the existing `emptyTranscriptCountRef` declaration and insert directly after it:

```typescript
// AD-826 — separate counter for whisper-empty transcripts so that the
// whisper→browser fallback in primary=whisper mode is independent of
// the browser→whisper fallback in primary=browser mode (AD-760).
const emptyWhisperCountRef = useRef<number>(0);
```

### 4d. Invert the PTT click handler

The current click handler at `ProfileChatTab.tsx:810-870` is browser-SR-primary. AD-826 wraps it in a `primary_stt` switch. The structure becomes:

```text
onClick:
  if (listening) { stopListening + disarmWhisperStt; return }
  primary = voiceHealth?.primary_stt ?? "browser"   // honest-degrade default
  healthy = voiceHealth?.healthy ?? false
  fallbackEnabled = voiceHealth?.primary_stt is set (mirrors backend's fallback_stt_enabled; UI doesn't currently read it — see Section 4e note)
  if (primary == "whisper" && healthy):
    use whisper-primary block (below) — falls through to browser SR after 2 whisper empties
  elif (primary == "whisper" && !healthy):
    log to console and use browser SR (no whisper attempt — backend unavailable)
  else (primary == "browser"):
    keep the existing AD-760 logic verbatim — browser SR primary, whisper fallback after 2 empties
```

**Critical:** preserve the existing AD-760 block verbatim for the `primary == "browser"` branch. Do not refactor it. The AD-826 changes ADD a new branch above it; the old branch stays at the bottom as the `else`.

Builder: full replacement for the click handler body. The SEARCH block below must match the live file exactly — Builder: read `ProfileChatTab.tsx` around line 810-870, copy the verbatim current handler into the SEARCH, then replace with the AD-826 version below. (We don't pre-stage the SEARCH because the file has minor whitespace evolution between commits; verify-by-grep before writing.)

The REPLACE block (template):

```typescript
onClick={() => {
  if (micMode === 'conversation') {
    // In conversation mode, left-click is press-to-talk preemption
    // (PRIORITY_PRESS_TO_TALK wins per BF-318); we still drive it
    // through the standard PTT path below — the ConversationController
    // will see the preempt and re-arm on release. The mode-switching
    // logic stays in the popover.
  }
  if (listening) {
    stopListening();
    // BF-290: also disarm whisper fallback in case the previous
    // press armed it but the operator never spoke. stopListening
    // only stops the browser SpeechRecognition; whisperStt is a
    // separate subsystem that needs explicit teardown.
    try { disarmWhisperStt(); } catch { /* Tier-2 */ }
    setListening(false);
    setProcessing(false); // BF-294: cancel any pending processing visual
    return;
  }
  setListening(true);
  // AD-826 — branch by primary_stt.
  const primary = voiceHealth?.primary_stt ?? 'browser';
  const whisperHealthy = voiceHealth?.healthy === true && voiceHealth?.backend_available === true;

  if (primary === 'whisper' && whisperHealthy) {
    // AD-826 — whisper-primary path. Mirror of AD-760's structure with
    // engines swapped: arm whisperStt first; after 2 empty whisper
    // transcripts, fall through to browser SR for the next press.
    if (emptyWhisperCountRef.current >= 2) {
      emptyWhisperCountRef.current = 0;
      console.info(`AD-826: browser-SR fallback for agent ${agentId} after 2 empty whisper transcripts`);
      let gotResult = false;
      startListening(
        (text) => {
          gotResult = true;
          setInput(text);
          setListening(false);
          setTimeout(() => { void sendText(text); }, 100);
        },
        () => {
          if (!gotResult) {
            // BF-293 mirror: empty browser SR in whisper-primary mode
            // does NOT increment the whisper counter; the operator
            // already paid the whisper-empty price to get here.
          }
          setListening(false);
        },
        () => setListening(false),
        { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
      );
      return;
    }
    let gotWhisperResult = false;
    const unsub = onWhisperTranscript((text: string) => {
      try { unsub(); } catch { /* Tier-2 */ }
      try { disarmWhisperStt(); } catch { /* Tier-2 */ }
      if (text && text.trim().length > 0) {
        gotWhisperResult = true;
        emptyWhisperCountRef.current = 0;
        setInput(text);
        setListening(false);
        setTimeout(() => { void sendText(text); }, 100);
      } else {
        emptyWhisperCountRef.current += 1;
        setListening(false);
      }
    });
    // Surface processing state via the BF-294 onTranscribing tap.
    armWhisperStt();
    return;
  }

  if (primary === 'whisper' && !whisperHealthy) {
    // Honest-degrade: operator asked for whisper but artifacts are
    // missing or offline_stt_enabled is False. Fall through to browser
    // SR for THIS press without consuming any counter.
    console.info(
      `AD-826: whisper primary but unhealthy (backend_available=${voiceHealth?.backend_available}); ` +
        `using browser SR for agent ${agentId}`,
    );
    let gotResult = false;
    startListening(
      (text) => {
        gotResult = true;
        setInput(text);
        setListening(false);
        setTimeout(() => { void sendText(text); }, 100);
      },
      () => { setListening(false); },
      () => setListening(false),
      { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
    );
    return;
  }

  // primary === 'browser' — AD-760 legacy path preserved verbatim.
  if (emptyTranscriptCountRef.current >= 2) {
    emptyTranscriptCountRef.current = 0;
    console.info(`AD-760: whisperStt fallback for agent ${agentId} after 2 empty transcripts`);
    const unsub = onWhisperTranscript((text: string) => {
      try { unsub(); } catch { /* Tier-2 */ }
      try { disarmWhisperStt(); } catch { /* Tier-2 */ }
      setInput(text);
      setListening(false);
      setTimeout(() => { void sendText(text); }, 100);
    });
    armWhisperStt();
    setListening(false);
    return;
  }
  let gotResult = false;
  startListening(
    (text) => {
      gotResult = true;
      emptyTranscriptCountRef.current = 0;
      setInput(text);
      setListening(false);
      setTimeout(() => { void sendText(text); }, 100);
    },
    () => {
      if (!gotResult) {
        emptyTranscriptCountRef.current += 1;
      }
      setListening(false);
    },
    () => setListening(false),
    { continuous: true, interimResults: true, endOfSpeechGapMs: 1500 },
  );
}}
```

### 4e. Note on `fallback_stt_enabled`

The backend field is exposed for future use (per-engine isolation testing, deterministic operator workflows). The UI in this AD does NOT read it — the two-empties fallback is always active when `voiceHealth` reports `healthy`. Filing as a forward-marker improvement (BF-294-style — handler reads the field) is out of scope for this prompt; the field exists in config + section registry for operator visibility only.

### 4f. Mic tooltip engine cue

Builder: the existing `<button>` for the mic has a `title=...` or `aria-label=...` somewhere on or near it. If absent, add `title={voiceHealth?.engine === 'whisper' ? 'Voice input (whisper)' : 'Voice input (browser)'}` to the button. Do NOT add emoji per HXI #3. Do NOT change the icon color based on engine — color is reserved for state (idle/listening/processing) per BF-294.

If the button already has a `title`, append the engine cue in parentheses; do not delete existing context.

---

## Section 5: Tests

### 5a. Backend (`tests/test_ad826_voice_config.py`)

Mirror the shape of `tests/test_ad705a_offline_stt_config.py`. Use real `SystemConfig` instances; no MagicMock (user-memory `Phantom-via-MagicMock` rule).

```python
"""AD-826 — whisper-first STT priority config + health endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from probos.config import CognitiveConfig, SystemConfig
from probos.settings.section_registry import get_section


def test_primary_stt_default_whisper() -> None:
    config = SystemConfig()
    assert config.cognitive.primary_stt == "whisper"


def test_primary_stt_accepts_browser() -> None:
    cfg = CognitiveConfig(primary_stt="browser")
    assert cfg.primary_stt == "browser"


def test_primary_stt_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        CognitiveConfig(primary_stt="azure")  # type: ignore[arg-type]


def test_fallback_stt_enabled_default_true() -> None:
    assert SystemConfig().cognitive.fallback_stt_enabled is True


def test_primary_stt_registered_in_section_registry() -> None:
    section = get_section("cognitive")
    assert section is not None
    ids = {f.field_id for f in section.fields}
    assert "cognitive.primary_stt" in ids
    assert "cognitive.fallback_stt_enabled" in ids


def test_voice_health_endpoint_whisper_primary_unhealthy(tmp_path: Path) -> None:
    """Default config: whisper primary, no model on disk → unhealthy."""
    from probos.runtime import ProbOSRuntime
    cfg = SystemConfig()
    cfg.runtime.data_dir = str(tmp_path)
    # offline_stt_enabled defaults to False → unhealthy path.
    rt = ProbOSRuntime(cfg)
    # Builder: use the same test-client bootstrap as existing voice-router
    # tests (search for ``test_voice`` or ``test_ad705c_voice``). The
    # exact ``TestClient`` construction depends on the FastAPI app
    # factory in ``probos.api.app`` — verify via grep before writing.
    # ... TestClient(app).get('/api/voice/health') ...
    # Assert: response.status_code == 200
    # Assert: data == {"primary_stt": "whisper", "engine": "whisper",
    #                  "backend_available": False, "healthy": False}


def test_voice_health_endpoint_whisper_primary_healthy(tmp_path: Path) -> None:
    """offline_stt_enabled + model file present → healthy."""
    cfg = SystemConfig()
    cfg.runtime.data_dir = str(tmp_path)
    cfg.cognitive.offline_stt_enabled = True
    model_path = tmp_path / "whisper" / "ggml-tiny.en.bin"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"fake ggml weights")
    # ... TestClient ...
    # Assert: healthy == True, backend_available == True


def test_voice_health_endpoint_browser_primary_always_healthy(tmp_path: Path) -> None:
    """primary_stt=browser → healthy regardless of artifact state."""
    cfg = SystemConfig()
    cfg.runtime.data_dir = str(tmp_path)
    cfg.cognitive.primary_stt = "browser"
    # offline_stt_enabled is False, no model file.
    # ... TestClient ...
    # Assert: healthy == True, backend_available == False, engine == "browser"
```

**Builder: TestClient bootstrap.** Before writing the three endpoint tests, grep for existing voice-router tests:

```
grep -rn "/api/voice/wake-word" tests/
```

Use the same FastAPI test-client construction. If no existing voice-router endpoint test exists, mirror a test from `tests/test_ad820_*` or `tests/test_ad821_*` that hits `/api/...` via `TestClient` — those waves shipped similar pattern.

### 5b. Backend regression suites

Builder: confirm these still pass without modification:

- `tests/test_ad705a_offline_stt_config.py` — must remain green; AD-826 additions are non-breaking new fields.
- `tests/test_ad760_*.py` — if it exists, must remain green (browser-primary path preserved verbatim).
- `tests/test_ad747_conversation_config.py` — sibling slot; AD-826 inserts BEFORE `conversation_mode_enabled`, so field ordering for this test must be confirmed.

### 5c. Frontend (`ui/src/__tests__/ProfileChatTab.ad826.test.tsx`)

Mirror the shape of any existing `ProfileChatTab.*.test.tsx` (e.g., the BF-292 / BF-293 / BF-294 tests). 5 tests:

1. **whisper-primary + healthy** — PTT click invokes `armWhisperStt`, does NOT invoke `startListening`. Fetch returns `{primary_stt: "whisper", healthy: true, backend_available: true}`.
2. **whisper-primary + unhealthy** — PTT click invokes `startListening` (browser SR), does NOT invoke `armWhisperStt`. Fetch returns `{primary_stt: "whisper", healthy: false, backend_available: false}`. Console.info called with `AD-826: whisper primary but unhealthy`.
3. **browser-primary (regression)** — PTT click invokes `startListening`, does NOT invoke `armWhisperStt`. Fetch returns `{primary_stt: "browser", healthy: true, backend_available: false}`. Behavior identical to pre-AD-826 (AD-760 first-press path).
4. **whisper-primary: 2 consecutive whisper empties → browser SR on 3rd press** — first two presses arm whisperStt, transcript callbacks fire with empty string. Third press invokes `startListening` (browser SR fallback). `emptyWhisperCountRef.current` reset to 0 after fallback fires.
5. **browser-primary: 2 consecutive browser SR empties → whisperStt on 3rd press (regression)** — preserves AD-760 verbatim.

Use the existing `_setWhisperLoaderOverride` and `_resetWhisperStt` seams (whisperStt.ts:56, 205). Mock `fetch` to return the desired voice-health payload. Mock `armWhisperStt` / `startListening` to record invocations.

---

## Section 6: Tracking

### 6a. PROGRESS.md

Append a new shipped block at the top of PROGRESS.md (above the BF-291 entry) after the Builder finishes:

```markdown
**AD-826 shipped (YYYY-MM-DD).** Whisper-first STT priority for cross-browser voice reliability. New `cognitive.primary_stt: Literal["whisper", "browser"]` (default `whisper`) + `cognitive.fallback_stt_enabled: bool` (default True). New `GET /api/voice/health` returns `{primary_stt, engine, backend_available, healthy}` — filesystem-only probe, no subprocess. `ProfileChatTab.tsx` PTT handler inverted: whisper-primary arms whisperStt first; browser-SR fallback after 2 empty whisper transcripts (mirror of AD-760). Honest-degrade when whisper artifacts absent — falls through to browser SR for the press without consuming any counter. Section-registry entries hot-reload. Edge / Firefox / Safari operators get reliable voice without changing the default. Closes #767. +6 backend pytest, +5 frontend vitest. `npm run build` clean.
```

### 6b. docs/development/roadmap.md

If a "Voice / STT" or "Voice infrastructure" section exists, append a one-line entry referencing AD-826 + closes #767. Builder: grep first; do NOT create a new section if none exists.

### 6c. DECISIONS.md

Append:

```markdown
**AD-826 (2026-05-DD)** — Whisper-first STT priority. The browser Web Speech API is reliable in Chrome but flaky in Edge/Firefox/Safari (silent session death, empty results, no errors). The AD-705a whisper.cpp WASM path works in every browser that ships WebAssembly + SharedArrayBuffer. Inverting the default — whisper primary, browser SR fallback — eliminates the cross-browser reliability gap without changing the underlying privacy invariant (audio still stays in the browser). Operators on a single-browser deployment can revert with `cognitive.primary_stt: browser`. The new `/api/voice/health` endpoint is filesystem-only — no subprocess is created — because whisper inference runs in the browser, not the runtime.
```

---

## Acceptance criteria

- **Backend test gate** (BF-279): `D:\ProbOS\.venv\Scripts\pytest.exe -n 0 --timeout=60 tests/test_ad826_voice_config.py` — all 6 tests pass.
- **Backend regression**: `pytest -n 0 --timeout=60 tests/test_ad705a_offline_stt_config.py tests/test_ad747_conversation_config.py tests/test_ad820_*.py tests/test_ad821_*.py tests/test_ad822_*.py tests/test_ad823_*.py tests/test_ad824_*.py tests/test_ad825_*.py` — all green.
- **Frontend test gate**: `cd ui; npx vitest run` — all green; the 5 new AD-826 tests pass.
- **Frontend build gate** (BF-279 hard rule): `cd ui; npm run build` — must succeed. `vitest run` alone is insufficient (it skips `tsc -b`).
- **No new subprocess call sites** (BF-280): grep `asyncio.create_subprocess_*` in the diff; must be empty.
- **No new `getUserMedia` call sites** — reuse existing whisperStt PCM tap.
- **HXI #3**: no emoji in the UI changes. Engine cue via text only.
- **One commit**, message: `AD-826: whisper-first STT priority (closes #767)`.
- **Push to origin/main** when all gates green.
- **Engineering Principles** per `.github/copilot-instructions.md` (especially: Pydantic `Field` with `description`; defaults; type annotations on all new public methods; structured log messages with context; async tasks in tests use real fixtures over MagicMock).

## What this prompt does NOT change

- The whisperStt → IntentSurface pipeline (AD-705a) — only the PTT handler in ProfileChatTab.tsx.
- The wake-word path (`AD-705c`) — unaffected.
- AD-760's browser-primary empty-counter logic — preserved verbatim as the `primary === 'browser'` branch.
- AD-747 conversation mode — unaffected; the conversation controller uses its own arming path.
- BF-294 visual indicators (`MicIndicator`) — unaffected; the new branches still call `setProcessing` via the existing `onTranscribing` subscription that's already wired in BF-294.
- No new dependencies. No new env vars. No new model artifacts. No new permissions prompts.

## Out of scope (deferred)

- Streaming partial whisper transcripts (currently batch-only).
- VAD tuning for whisper utterance boundaries.
- Multi-language model selection.
- Whisper model variant selection (tiny/base/large).
- BF-294b real-audio-meter integration (separate issue, already filed).
- UI exposure of `fallback_stt_enabled` (backend field only in this AD).

## Standing constraints

- **DO NOT touch the live runtime.** Operator's runtime is currently running. Builder MUST NOT restart it or `kill -9` any python process. Use `D:\ProbOS\.venv\Scripts\pytest.exe` directly; do NOT invoke `probos serve`.
- **DO NOT touch anything under `C:\Users\seang\AppData\Local\ProbOS\`** — that's the operator's live data directory.
- **DO NOT use `Get-Process python | Stop-Process`** or any broad python-by-path kill (user-memory standing rule). Pytest-only kill: `scripts/kill-stale-pytest.ps1`.
- **DO NOT use `asyncio.create_subprocess_*`** — none needed in this AD, but the rule is standing for the codebase (BF-280).

---

## Verified Against Codebase (2026-05-22)

```
grep -n "whisper_model_path" src/probos/config.py
  253:    whisper_model_path: str = "whisper/ggml-tiny.en.bin"

grep -n "offline_stt_enabled" src/probos/config.py
  270:    offline_stt_enabled: bool = False

grep -n "cognitive.offline_stt_enabled" src/probos/settings/section_registry.py
  124:                "cognitive.offline_stt_enabled",

grep -n "router = APIRouter" src/probos/routers/voice.py
  37:router = APIRouter(prefix="/api/voice", tags=["voice"])

grep -n "resolve_whisper_model_path" src/probos/voice/whisper_model.py
  24:def resolve_whisper_model_path(

grep -n "armWhisperStt\|disarmWhisperStt\|onWhisperTranscript" ui/src/audio/whisperStt.ts
  154:export function armWhisperStt(): () => void {
  168:export function disarmWhisperStt(): void {
  184:export function onTranscript(listener: TranscriptListener): () => void {

grep -n "emptyTranscriptCountRef\|armWhisperStt\|startListening" ui/src/components/profile/ProfileChatTab.tsx
  834-848: AD-760 fallback block (browser SR primary → whisper after 2 empties)
  858:                startListening(

grep -n "offline_stt_enabled" ui/src/components/IntentSurface.tsx
  92:    Boolean(s.snapshot?.config?.cognitive?.offline_stt_enabled),

grep -n "loadWhisperModel" ui/src/audio/whisperLoader.ts
  110:export async function loadWhisperModel(): Promise<WhisperHandle | null> {

# Confirms: whisper inference is browser-side WASM. No backend subprocess.
# Confirms: voice config lives under CognitiveConfig, not VoiceConfig.
# Confirms: frontend reads config via snapshot.config.cognitive.*
# Confirms: /api/voice router already exists; new endpoint hangs off it.
```

**Current highest AD: AD-825** (shipped 2026-05-22 per PROGRESS.md line 11). AD-826 is the next sequential.

**Current highest BF: BF-294** (in flight per session memory; BF-294b filed as forward marker). AD-826 may discover sub-bugs during build; assign BF-295 onward as needed.
