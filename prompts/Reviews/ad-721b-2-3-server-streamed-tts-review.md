# Review: AD-738 — Server-streamed TTS via Piper (Wave 157, pass 1)

**Verdict:** ⚠️ Conditional
**Three Required findings: a phantom AttachmentStore API, a default-config behaviour regression, and a buggy code block in Section 2e that the Builder will copy-paste verbatim. All small, all surgical fixes.**

---

## Required (must fix before building)

1. **PHANTOM API: `AttachmentStore.put(...)` does not exist.** Section 3 endpoint:
   ```python
   attachment_id = await store.put(result.audio_bytes, mime=result.mime)
   ```
   The live Protocol at [src/probos/attachments/store.py](src/probos/attachments/store.py#L14-L41) declares only `write(content_hash, blob, mime) -> Path`, `read`, `exists`, `get_path`, `size`. There is no `put`. The caller is responsible for computing the sha256 — verified at [src/probos/routers/chat.py](src/probos/routers/chat.py#L665) (`actual_hash = hashlib.sha256(blob).hexdigest()`) and [chat.py#L692](src/probos/routers/chat.py#L692) (`await store.write(actual_hash, blob, declared_mime)`). The pre-flight checklist (WAVE-157-DISPATCH item 6) frames this as "verify mime is keyword-acceptable" — the real defect is that the method name itself is wrong. **Fix:** replace the call with the chat-router pattern:
   ```python
   import hashlib
   attachment_id = hashlib.sha256(result.audio_bytes).hexdigest()
   await store.write(attachment_id, result.audio_bytes, result.mime)
   ```
   This is the same hard-stop pattern called out in the WAVE-157-DISPATCH "Hard-stop conditions" → "Phantom API discovered." It must be fixed in the prompt before dispatch.

2. **DEFAULT-CONFIG REGRESSION: every `speakResponse()` now adds an HTTP round-trip even when `tts.backend = "browser"`.** Section 4a unconditionally calls `fetch('/api/avatars/tts', ...)` on every utterance, and only falls back to `SpeechSynthesisUtterance` after the server returns `{backend: "disabled"}`. Wave 156 had zero HTTP for TTS. The acceptance criterion ("operators who don't install Piper see ZERO change vs. Wave 156") is violated in spirit: every utterance pays a 50-200ms RTT before speech starts, plus a hard dependency on the runtime being reachable. The Hard-stop in WAVE-157-DISPATCH ("`tts.backend = "browser"` default does NOT preserve Wave 156 behaviour") fires. **Fix options (pick one):**
   - One-time feature probe at module-load (`GET /api/avatars/tts/status` or first-call cache the disabled response in a module-level `let _serverTtsEnabled: boolean | null = null`); when known-disabled, skip the fetch and call `_speakBrowserFallback` synchronously.
   - Read `window.__probos_tts_backend` populated at HXI bootstrap via the existing `/api/system/info` endpoint.

   The probe approach is preferred — it preserves the "speech must NEVER stop" invariant if the runtime later changes config. Add the cache invalidation contract (cache cleared on any non-200 response) so a runtime restart with `backend = "piper"` lights up without a browser refresh.

3. **CODE BUG IN SECTION 2e: the canonical `create_subprocess_exec` block is wrong; the corrected version lives only in subsequent prose.** Section 2e of the prompt contains:
   ```python
   proc = await asyncio.create_subprocess_exec(
       str(binary),
       "--model", str(model),
       "--output_raw", "-",
       ...
   )
   ```
   And then a paragraph below says: *"Builder action: drop the `--output_raw` argument from the `create_subprocess_exec` call above."* The Builder will copy the original block first (the prompt presents it as a complete module body), then read the prose, then have to mentally re-edit. This is exactly the BF-274 / BF-278 footgun-shape ("partial code in body, correction in prose"). **Fix:** inline the corrected block directly into the canonical module text and demote the explanation to a `# NOTE` comment inside the function body. Drop the duplicated invocation.

---

## Recommended (should fix)

1. **`agent_id` is sent in the request body but the endpoint never reads it.** Section 4a `body: JSON.stringify({ text, agent_id: agent_id ?? null })`; Section 3 only inspects `payload["text"]`. Either consume `agent_id` (forward marker for AD-738a per-agent voice selection — useful to log for telemetry now) or strip it from the request body. Today it's silently discarded, which becomes a maintenance trap when AD-738a builds the per-agent voice selector and assumes the field already round-trips.

2. **Implicit dual-fire on the existing `useLipSyncCapture` capture path.** When the server path succeeds and `injectLipSyncFrames(...)` is called, the new code ALSO fires `'start'` via `audio.addEventListener('play', ...)` against the synthetic `SpeechSynthesisUtterance`. The existing `useLipSyncCapture` `useEffect` subscribes to `onSpeechEvent('start')` (verified at [ui/src/audio/useLipSyncCapture.ts:62](ui/src/audio/useLipSyncCapture.ts#L62)) and will spawn `captureUtteranceAudio(syntheticUtterance)`. That call returns null bytes (today's behaviour), `setFrames` is never called, and there is no race — but a `MediaRecorder` is spun up and torn down on every utterance for nothing. Add a one-line guard: when injection has occurred for an utterance, stash a flag so the capture spawn is skipped. Or document explicitly in `useLipSyncCapture.ts` that the capture-path is intentionally a no-op when the server path is configured.

3. **No cancellation of an in-flight `<audio>` element when a new `speakResponse` arrives.** The new code calls `speechSynthesis.cancel()` synchronously at the top, but does not track or `pause()` a previously-started `Audio` element. A second `speakResponse` while the first audio is still playing will result in two overlapping audio streams (the second `<audio>` plays alongside the first). `speechSynthesis.cancel()` only stops browser TTS. **Fix:** keep a module-level `let _activeAudio: HTMLAudioElement | null = null;` and `_activeAudio?.pause()` at the top of every call.

4. **Section 1 / `select_backend` argument typing is loose (`config: object`).** The function reads `config.binary_path`, `config.voice_model`, `config.timeout_seconds` — those are concrete attributes of `TTSConfig`. Type as `TTSConfig` for an actual contract, or use `typing.Protocol` if the author wants structural typing. `object` defeats the type checker and Engineering Principles (`type annotation standards: full type annotations on public methods, exact signatures matching Protocols`).

5. **`_resolve_voice_model` hard-codes `tools/piper/voices` without going through any path-resolver helper.** AD-720 introduced `_resolve_attachments_dir` for the same problem class (path under platform data dir, traversal-safe). The piper resolver is operator-controlled and runs as the runtime user — low risk — but for parity with AD-721b-1 / AD-720, consider whether the voice directory should be (a) configurable, (b) resolved through the same `_platform_data_dir` pattern, or (c) explicitly documented as repo-rooted. Default `Path("tools/piper/voices").resolve()` resolves against the runtime's CWD, which is `D:\ProbOS\` in Captain's setup but undefined in service-style deployments. Add a `voice_model_dir: str = "tools/piper/voices"` field to `TTSConfig` so the operator controls the location.

6. **Missing test for the default-config no-op path on the SERVER side.** The Python test list covers `test_endpoint_tts_disabled_returns_disabled` and `test_endpoint_tts_browser_backend_returns_disabled` — good. But there is no test asserting the endpoint returns within ~10ms (no subprocess spawn, no AttachmentStore touch) when `backend = "browser"`. Add a "no-side-effect" assertion (mock `select_backend` and confirm it is NOT invoked when `backend = "browser"`).

---

## Nits (style / minor)

1. Call-site count drift in Section 4a "Surface preservation" paragraph: prompt says "4 production callers" pointing at 6 line numbers across 4 FILES. Reword as "4 production files / 6 call sites."

2. License Disposition section under "Verified Against Codebase" cites `src/probos/config.py:1140 "audio/wav"` for the MIME allow-list. Actual location is [src/probos/attachments/filesystem_store.py:38](src/probos/attachments/filesystem_store.py#L38). Cosmetic but flag-worthy under Code Accuracy.

3. `TTSConfig.binary_path` docstring mentions Windows `.exe` auto-append, but the Pydantic field defaults to the Linux/macOS shape (`tools/piper/piper`). Add a one-line note that Windows operators MUST still drop the binary at `tools/piper/piper.exe` — the auto-append is a runtime resolution convenience, not a config mutation.

4. `useLipSyncCapture.ts` injection registry uses a module-level `Set<...>` — that's fine for a single-mounted hook, but if a future tab/popup mounts a second `useLipSyncCapture` for a different agent, both will receive the injection. The agent-id filter inside `_subscribeInjection` handles this; no functional issue, but worth a `// TODO(AD-738a)` comment when per-agent selectors land.

5. Section 5a test `test_piper_backend_happy_path_returns_wav` says "stub binary writes a 44-byte minimal WAV header". 44 bytes is the canonical empty-data RIFF header — `_wav_duration_ms` on a 44-byte WAV returns 0 (no data chunk samples). The endpoint test `test_endpoint_tts_happy_path_returns_attachment_and_visemes` asserts "positive duration_ms" — make sure the stub WAV in THAT test has a non-zero data chunk, or drop the positivity assertion. Two different stubs needed.

6. `audio.preservesPitch = false` is well-supported on Chromium / Firefox / Safari modern, but is documented as an experimental MDN feature. Add a `// @ts-expect-error if needed for older lib.dom` comment if Vitest's TS lib lacks it. Otherwise harmless.

---

## Verified (looks good)

- **`src/probos/audio/` does not exist** — confirmed via list_dir (ENOENT). The AD creates the seam from scratch as claimed in Captain Decision #6.
- **`speakResponse` call-site enumeration** — 4 production files: `DecisionSurface.tsx:239`, `IntentSurface.tsx:265,289`, `ProfileChatTab.tsx:124`, `ProfileInfoTab.tsx:425,537`. Plus tests at `voice.test.ts`, `voice.speakResponse.modulation.test.ts`. Production surface is unchanged after Section 4a.
- **`generate_visemes(audio_path, binary_path, timeout_seconds)` signature** — verified at [src/probos/avatars/rhubarb_backend.py:147](src/probos/avatars/rhubarb_backend.py#L147). Endpoint reuse pattern matches AD-721b-1.
- **`<audio>` not currently used** — grep with `includeIgnoredFiles` confirms zero `new Audio(` and zero `HTMLAudioElement` references in `ui/src/`. Adding the `<audio>` path does not collide with anything.
- **`injectLipSyncFrames` symbol does not exist anywhere** — zero matches. No naming collision.
- **`_get_attachment_store(runtime)` accessor at [src/probos/routers/chat.py:599](src/probos/routers/chat.py#L599)** — already reused by AD-721b-1 in `routers/avatars.py:55`. Correct seam.
- **AD-731 ref-shape invariant preserved** — response carries `audio_attachment_id` only; no inline `audio_bytes` / `audio_base64` field. Test #16 (per Section 5a) asserts this explicitly.
- **AD-735 / AD-737 modulation preserved** — `_resolveEffectiveProfile` runs `applyEmotionalModulation` for BOTH paths.
- **`audio/wav` in MIME allow-list** — verified at [src/probos/attachments/filesystem_store.py:38](src/probos/attachments/filesystem_store.py#L38) (`"audio/wav": "wav"`). `store.write(hash, blob, "audio/wav")` will not raise the MIME guard.
- **`LipSyncConfig.enabled` field exists** — verified at [src/probos/config.py:1188](src/probos/config.py#L1188). The endpoint's `lipsync_cfg.enabled` read in Section 3 is sound.
- **`Literal` import in `config.py`** — already present (used by `LipSyncConfig.backend`). No new import needed.
- **Subprocess discipline** — `asyncio.create_subprocess_exec` (no `shell=True`), absolute resolved binary path, configurable timeout with `kill()` on timeout, stderr captured and truncated to 500 chars. Mirrors AD-721b-1 `rhubarb_backend.py` pattern. Sound.
- **License posture** — Piper MIT (verified by Architect via `gh api`), `en_US-amy-medium` MIT (verified at HuggingFace model card). No license-tainted dependency entering the repo. `/tools/` already gitignored at [.gitignore:3](.gitignore).
- **Highest AD verification** — `AD-737` is current (per Architect grep). Wave 157 advances to `AD-738`. Forward markers `AD-738a/b/c/d` are roadmap-only, no DECISIONS.md entries until built. Correct numbering.
- **Pitch-on-`<audio>` deferred** — explicit forward marker AD-738c (server-side modulation at synthesis). `audio.preservesPitch = false` is the documented stop-gap so playbackRate yields a pitch side-effect. Honest.
- **HXI principles** — no UI elements added (the `<audio>` is created in JS and never mounted). Compliant with HXI Design Principles 2-4 (no emoji, no DOM clutter).

---

## Per-criteria Summary (10 sections from review-criteria.md)

| # | Criterion | Status |
|---|-----------|--------|
| 1 | Boundary Enforcement | ⚠️ default-config regression at the speakResponse boundary (Required #2) |
| 2 | Silent Failure Audit | ✅ Tier-2 log-and-degrade applied consistently; no compounded swallows |
| 3 | Namespace & State Consistency | ✅ no NATS/subject changes; module location uncontested |
| 4 | Scope & Completeness | ✅ "What This Does NOT Change" present; existing-test impact noted; no operational cleanup needed |
| 5 | Engineering Principles | ⚠️ `select_backend(config: object)` loosens Protocol typing (Recommended #4) |
| 6 | Code Accuracy | ❌ phantom `store.put` (Required #1); buggy 2e block (Required #3); call-site / file-path nits |
| 7 | Test Coverage | ⚠️ default-config no-op test missing (Recommended #6); WAV stub size needs differentiation (Nit #5) |
| 8 | Design Choices | ✅ alternatives documented (Coqui CPL excluded, Tortoise latency, ElevenLabs commercial-only); rollback is config-flip |
| 9 | Prompt Structure | ⚠️ Section 2e canonical block + correction-in-prose splits the implementation (Required #3) |
| 10 | Startup Phase Ordering | ✅ no finalize-phase wiring; new endpoint reads config at request time |

---

## Verified Against Codebase (2026-05-13)

```
list_dir src/probos/audio/
  → ENOENT (module does not exist) ✅

grep "def put\(|def get_path\(|class.*Store" src/probos/attachments/
  src/probos/attachments/store.py:14   class AttachmentStore(Protocol):
  src/probos/attachments/store.py:34       async def get_path(...)
  src/probos/attachments/filesystem_store.py:59  class FilesystemAttachmentStore:
  src/probos/attachments/filesystem_store.py:113     async def get_path(...)
  → no `put` method anywhere; only `write`/`read`/`exists`/`get_path`/`size`

read store.py:14-41
  async def write(self, content_hash: str, blob: bytes, mime: str) -> Path
  async def read(self, content_hash: str) -> bytes
  async def exists(self, content_hash: str) -> bool
  async def get_path(self, content_hash: str) -> Path
  async def size(self, content_hash: str) -> int

grep "store\.write\(|store\.put\(|hashlib\.sha256" src/probos/routers/chat.py
  src/probos/routers/chat.py:665   actual_hash = hashlib.sha256(blob).hexdigest()
  src/probos/routers/chat.py:692       await store.write(actual_hash, blob, declared_mime)
  → caller computes the hash; canonical pattern

grep "speakResponse\(" ui/src/
  ui/src/audio/voice.ts:99               (definition)
  ui/src/components/DecisionSurface.tsx:239
  ui/src/components/IntentSurface.tsx:265, 289
  ui/src/components/profile/ProfileChatTab.tsx:124
  ui/src/components/profile/ProfileInfoTab.tsx:425, 537
  + tests in voice.test.ts, voice.speakResponse.modulation.test.ts

grep "async def generate_visemes" src/probos/avatars/rhubarb_backend.py
  src/probos/avatars/rhubarb_backend.py:147
  signature: (audio_path, binary_path, timeout_seconds=30.0) → list[VisemeFrame]

grep "new Audio\(|HTMLAudioElement" ui/src/ (includeIgnored=true)
  → No matches.

grep "injectLipSync|injectFrames" ui/src/ (includeIgnored=true)
  → No matches.

grep "_get_attachment_store" src/probos/routers/
  src/probos/routers/chat.py:599   def _get_attachment_store(runtime: Any) -> Any:
  src/probos/routers/avatars.py:55     store = _get_attachment_store(runtime)  (AD-721b-1 reuse)

grep "class LipSyncConfig|lipsync:|class TTSConfig" src/probos/config.py
  src/probos/config.py:1177   class LipSyncConfig(BaseModel):
  src/probos/config.py:3390       lipsync: LipSyncConfig = Field(default_factory=LipSyncConfig)
  → no TTSConfig today; Section 1a creates it

read src/probos/config.py:1177-1207  (LipSyncConfig)
  enabled: bool = True
  backend: Literal["heuristic", "rhubarb"] = "heuristic"
  binary_path: str = "tools/rhubarb/rhubarb"
  timeout_seconds: float = 30.0
  → TTSConfig insertion target verified; Literal already imported

grep "audio/wav|_MIME_TO_EXT" src/probos/attachments/filesystem_store.py
  filesystem_store.py:22   _MIME_TO_EXT: dict[str, str] = {
  filesystem_store.py:38       "audio/wav":         "wav",
  → audio/wav is allow-listed (the prompt's Verified-section cited the wrong path)

read src/probos/routers/avatars.py (88 lines, ends after generate_lipsync)
  → Section 3 endpoint inserted at end-of-file is correct.
```

---


---

## Re-review (pass-2, 2026-05-13)

**Verdict:** ✅ **Approved**
**All three Required findings from pass-1 are resolved. No new Required findings introduced. Recommended #1, #3, #4, #6 folded; #2 and #5 deferred with explicit rationale.**

### R1 — Phantom AttachmentStore.put → write(hash, blob, mime) ✅ RESOLVED

Verified against live Protocol at `src/probos/attachments/store.py:14-41`:

```
async def write(self, content_hash: str, blob: bytes, mime: str) -> Path
async def read(self, content_hash: str) -> bytes
async def exists(self, content_hash: str) -> bool
async def get_path(self, content_hash: str) -> Path
async def size(self, content_hash: str) -> int
```

Sweep of the prompt:

- `grep "store\.put\("` → **0 hits** in code or prose.
- `grep "store\.write\("` → 3 code-block hits, all matching the canonical signature:
  - L53 (Solution overview): `AttachmentStore.write(sha256, bytes, "audio/wav")`
  - L559 (Section 3 inline-comment template): `await store.write(actual_hash, blob, declared_mime)`
  - L564 (Section 3 implementation): `await store.write(attachment_id, result.audio_bytes, result.mime)` — preceded by `attachment_id = hashlib.sha256(result.audio_bytes).hexdigest()` at L563.
- L924 ("What this does NOT change") and L1088 (revision note) describe the invariant in prose using the correct `write(sha256, blob, mime)` shape.
- Section 8 verification command #2 now greps for `def write\(` in `store.py` (Protocol), not `put` in `filesystem_store.py`. Correct.

The endpoint mirrors the chat-router pattern verbatim. No phantom remains.

### R2 — Default-config zero-HTTP guarantee ✅ RESOLVED

Three pieces audited:

**Endpoint design (Section 3):** `GET /api/avatars/tts/status` returns `{enabled, backend}`; defensive against missing `tts` attr (returns `{enabled: False, backend: "browser"}`). Tier-2 log-and-degrade. Sound.

**Browser cache (Section 4a):** `_ttsStatus` module-level cache + `_ttsStatusInflight` in-flight de-dup + `_invalidateTtsStatus()` on POST failure. The probe is fetched at most once per HXI session on the happy path, and re-probed on the next call after any failure (so a runtime config flip from `browser` → `piper` lights up without browser refresh, per Captain decision #9). Cache invalidation contract documented inline.

**Critical Vitest assertion (Section 5b row 1):**

> *"`speakResponse makes ZERO POST to /api/avatars/tts when status reports backend=browser (default config)`. Mock `GET /api/avatars/tts/status` → `{enabled: true, backend: "browser"}`. Call `speakResponse` 3 times. Assert `fetch` was called exactly ONCE total (the GET probe), `speechSynthesis.speak` called 3 times, NO POST to `/api/avatars/tts`. **Load-bearing test for Captain decision #9 (zero-HTTP-per-utterance default-config guarantee).**"*

This is the load-bearing test that closes Required #2. The "exactly ONCE total" assertion is the right shape — it catches both the regression-restore (per-utterance POST) and a broken cache (multiple probes). The "called 3 times" pair-assertion proves the fallback path still fires. Both halves of the contract are tested.

The fetch + cache flow is also exercised by the next two Vitest rows (server flip → fallback + invalidate; POST reject → fallback + invalidate). Combined coverage is correct.

### R3 — Section 2e Piper invocation ✅ RESOLVED

Sweep of the prompt:

- `grep "--output_raw"` → 7 hits, all in **prose**: 1 in the PiperBackend class docstring (warning explaining why NOT to use it), 4 in the Revision section, 1 in the closing self-check, 1 in the README-citation note. **Zero hits in any code block.**
- Section 2e canonical `create_subprocess_exec` block (read at lines 421-427) now contains:
  ```python
  proc = await asyncio.create_subprocess_exec(
      str(binary),
      "--model", str(model),
      "--output_file", "-",  # WAV (with RIFF header) to stdout. See class docstring.
      ...
  )
  ```
- The duplicated "Builder action: drop the `--output_raw` argument..." paragraph and standalone corrected block are gone. Builder copy-paste of the canonical block now produces the correct invocation.
- The PiperBackend class docstring documents the `--output_file -` form, the `--output_raw` pitfall, and cites the rhasspy/piper README MIT-archive timestamp 2025-10-06.

Verified against the rhasspy/piper README pattern: `--output_file -` is the documented stdout-WAV sink. No further action needed.

### Recommended findings disposition (verified)

| # | Pass-1 Recommended | Disposition | Verified |
|---|--------------------|-------------|----------|
| 1 | `agent_id` unused in body | Folded — body is now `{text}` only; AD-738a will reintroduce | ✅ Section 4a body: `JSON.stringify({ text })` (L735) |
| 2 | `useLipSyncCapture` dual-fire on capture path | Deferred with rationale | ⚠️ Acceptable — capture path returns `null` today; no functional regression, only one wasted MediaRecorder spin per utterance in the OPT-IN piper path. Worth tracking but not blocking. |
| 3 | Cancel in-flight `<audio>` on second call | Folded — `_activeAudio` module ref + new Vitest test | ✅ L724-727 (`_activeAudio?.pause()`) and Section 5b row 6 |
| 4 | `select_backend(config: object)` loose typing | Folded — typed as `TTSConfig` via TYPE_CHECKING | ✅ Section 2b L240 (`config: "TTSConfig"` with `TYPE_CHECKING` import) |
| 5 | `voice_model_dir` configurable field | Deferred — repo-rooted default documented | ⚠️ Acceptable — adds a new Pydantic field; out-of-scope for this revision pass |
| 6 | Server-side default-config no-op test | Folded into tightened `test_endpoint_tts_browser_backend_returns_disabled` | ✅ Section 5a row 12 ("Also assert `select_backend` is NOT invoked AND no subprocess spawn occurred") |

### Internal consistency (Solution Overview / Files-to-Modify / Verification footer)

- **Solution overview (5 pieces)** lists endpoint at item 3 — Section 0 lists "ADD `GET /api/avatars/tts/status` AND `POST /api/avatars/tts`". ✅ Consistent.
- **Captain decision #5** says "A separate `GET /api/avatars/tts/status` endpoint exists for one-time feature detection (see Captain decision #9 + Section 4a)" — matches Section 3 implementation. ✅
- **Captain decision #9** load-bearing zero-HTTP guarantee — referenced by both Section 4a (`ZERO-HTTP guarantee for default config (Captain decision #9)`) and Acceptance criterion #1. ✅
- **Test count** header: "≥ 18 new (≥ 13 Python + ≥ 5 Vitest)". Section 5a lists 21 Python tests; 5b lists 6 Vitest; 5c lists 1 regression. Total 28 ≥ 18 floor. ✅
- **Verified Against Codebase footer** — line 1140 cite for `audio/wav` in `config.py` is still slightly off (actual is `filesystem_store.py:38` per pass-1 Nit #2). Carried forward; cosmetic, not Required.

### New findings: NONE

No new Required. No new Recommended. The 1140-citation Nit from pass-1 was not folded; non-blocking.

### Per-criteria Summary (re-review)

| # | Criterion | Pass-1 | Pass-2 |
|---|-----------|--------|--------|
| 1 | Boundary Enforcement | ⚠️ R2 | ✅ — probe + cache enforces zero-HTTP at the boundary |
| 2 | Silent Failure Audit | ✅ | ✅ |
| 3 | Namespace & State Consistency | ✅ | ✅ |
| 4 | Scope & Completeness | ✅ | ✅ |
| 5 | Engineering Principles | ⚠️ Rec #4 | ✅ — `select_backend` typed as `TTSConfig` |
| 6 | Code Accuracy | ❌ R1 + R3 + nits | ✅ — store.write verified, --output_file - verified |
| 7 | Test Coverage | ⚠️ Rec #6 | ✅ — load-bearing zero-POST test added; no-side-effect assertion folded |
| 8 | Design Choices | ✅ | ✅ — option (a) probe+cache rationale documented |
| 9 | Prompt Structure | ⚠️ R3 | ✅ — single canonical 2e block; duplicated paragraph removed |
| 10 | Startup Phase Ordering | ✅ | ✅ |

### Verified Against Codebase (pass-2, 2026-05-13)

```
read src/probos/attachments/store.py:1-50
  L22: async def write(self, content_hash: str, blob: bytes, mime: str) -> Path
  L26: async def read(self, content_hash: str) -> bytes
  L30: async def exists(self, content_hash: str) -> bool
  L34: async def get_path(self, content_hash: str) -> Path
  L38: async def size(self, content_hash: str) -> int
  → no `put` method anywhere in Protocol ✅

grep "store\.put\(" prompts/ad-721b-2-3-server-streamed-tts.md
  → 0 hits ✅

grep "store\.write\(" prompts/ad-721b-2-3-server-streamed-tts.md
  L53, L559, L564 — all match (content_hash, blob, mime) ✅

grep "--output_raw" prompts/ad-721b-2-3-server-streamed-tts.md
  L389, L1101, L1102, L1103, L1124 — all PROSE (warnings, revision notes) ✅
  → 0 occurrences in code blocks

grep "--output_file" prompts/ad-721b-2-3-server-streamed-tts.md
  Section 2e canonical block (L425): "--output_file", "-" ✅

grep "agent_id: agent_id" prompts/ad-721b-2-3-server-streamed-tts.md
  → 0 hits ✅ (Recommended #1 folded)

grep "_activeAudio" prompts/ad-721b-2-3-server-streamed-tts.md
  L719 (declaration), L724-727 (cancel logic), L780 (clear-on-end), Section 5b row 6 (test) ✅

grep "_fetchTtsStatus|_ttsStatus|_ttsStatusInflight|_invalidateTtsStatus" prompts/ad-721b-2-3-server-streamed-tts.md
  L688-720 (cache + probe + invalidate); L740, L758, L771 (callsites) ✅

grep 'ZERO POST' prompts/ad-721b-2-3-server-streamed-tts.md
  Section 5b row 1 (load-bearing Vitest) ✅

grep 'config: "TTSConfig"' prompts/ad-721b-2-3-server-streamed-tts.md
  Section 2b L240 + TYPE_CHECKING import L237 ✅
```

---

## Final pass-2 verdict

**✅ Approved — Ready for Builder dispatch.**

All three Required findings resolved with verified code-level fixes. Four of six Recommended folded; the two deferred items (useLipSyncCapture dual-fire on capture path; configurable voice_model_dir) are scoped, non-blocking, and explicitly tracked in the Revision section. No new findings.

The prompt is internally consistent, the verification footer is honest, and the load-bearing default-config zero-HTTP test is explicit and asserts the exact contract from Captain decision #9.
