# Wave: voice-stack triage (BF-320 + BF-321 + BF-322)

Execute the three Builder-Fixes in this order. Each is independent and small. Ship one commit per BF. Run full vitest + pytest gate before each commit.

---

## BF-320 (GH #789) — keep whisper worker warm across PTT clicks

**File:** `ui/src/audio/transformersStt.ts`

**Current behavior:** `armTransformersStt()` spawns a worker + sends `init`. `disarmTransformersStt()` posts `shutdown`, nullifies state, terminates worker. Every PTT click pays the full re-init cost (~2-4s on whisper-medium.en).

**Target behavior:**
- The Worker + whisper pipeline lives for the page lifetime once initialized.
- `armTransformersStt()` is split internally:
  - First call: spawns Worker, sends `init`, registers PCM tap.
  - Subsequent calls: re-registers PCM tap if previously disengaged. Idempotent on the worker side.
- `disarmTransformersStt()` ONLY unsubscribes the PCM tap. The worker + model stay resident.
- New `terminateTransformersStt()` (exported) actually shuts down the worker — wire it to module-level `_resetTransformersStt` for tests, and to a `beforeunload` listener for production.

**Refactor plan:**

1. Split `_state` into two pieces:
   - `_worker: Worker | null` — survives across arm/disarm cycles.
   - `_engaged: { unsubscribe: () => void; ringBuffers: Float32Array[]; ringSampleCount: number; preroll: Float32Array[]; prerollCount: number } | null` — exists only while armed.

2. `armTransformersStt`:
   - If `_worker === null`: create Worker via factory, wire message handler, send `init`. Set `_worker`.
   - If `_engaged !== null`: return `disarmTransformersStt` (already armed).
   - Subscribe PCM tap (`subscribePcm(_buildTapHandler())`) and store in `_engaged`.
   - Return `disarmTransformersStt`.

3. `disarmTransformersStt`:
   - If `_engaged === null`: no-op.
   - Call `_engaged.unsubscribe()` to detach the PCM tap.
   - Set `_engaged = null`.
   - DO NOT post shutdown. DO NOT terminate worker.

4. New `terminateTransformersStt()`:
   - If `_engaged`: disarm first.
   - If `_worker`: postMessage `{type:'shutdown'}`, terminate after 250ms grace.
   - Set `_worker = null`.

5. `_resetTransformersStt()` (test seam): calls `terminateTransformersStt()` synchronously (skip the 250ms grace in tests).

6. `_isArmed()` returns `_engaged !== null` (unchanged semantics from caller perspective).

7. Worker-side (`transformersWorker.ts`): no changes needed. The worker already idles waiting for `transcribe` messages between utterances.

**Tests:**

- Update `ui/src/audio/__tests__/whisperStt.test.ts` (the existing alias-route tests) so that:
  - Arm → speak → disarm → arm again does NOT call the worker factory twice.
  - Add a new test: `armTransformersStt(); disarmTransformersStt(); armTransformersStt();` — assert `_setTransformersWorkerOverride` factory called exactly ONCE.
  - Existing transcribe-on-VAD-speech-end test continues passing (BF-316's 700ms hangover handling already in place).
- All BF-301, BF-309, BF-310, BF-311, BF-314, BF-316, BF-319 tests must still pass.

**Acceptance:**
- 957+ vitest passing.
- `npm run build` clean.
- Browser console after first PTT click on a fresh page load: subsequent clicks show ZERO `from_pretrained` / `dtype not specified` lines.

**Do not touch:** `voiceActivity.ts`, `pcmCaptureWorklet.js`, `ConversationController`, `BargeInDetector`, `ProfileChatTab` (it uses the public `armWhisperStt` / `disarmWhisperStt` aliases — no call-site changes needed). `IntentSurface` same — no call-site changes.

---

## BF-321 (GH #790) — stub `/api/system/extensions` endpoint

**File:** likely `src/probos/routers/system.py` (or wherever `/api/system/*` lives — grep for existing `/api/system/health` to find).

**Implementation:**

1. Grep for existing `/api/system/*` routes to find the right router file:
   ```
   grep -rn "api/system" src/probos/routers/
   ```

2. Add a new `Pydantic` response model `SystemExtensionsResponse` with one field `extensions: list[dict[str, Any]] = []`.

3. Add the endpoint:
   ```python
   @router.get("/api/system/extensions", response_model=SystemExtensionsResponse)
   async def list_system_extensions() -> SystemExtensionsResponse:
       """Stub for the UI's extensions poller. Empty list until extension
       infrastructure lands (see roadmap #788 absorption + future
       mcp-dynamic-registration AD)."""
       return SystemExtensionsResponse(extensions=[])
   ```

4. Test in the appropriate test file (likely `tests/test_distribution.py` based on existing patterns):
   ```python
   def test_system_extensions_returns_empty_list(client):
       resp = client.get("/api/system/extensions")
       assert resp.status_code == 200
       assert resp.json() == {"extensions": []}
   ```

**Acceptance:**
- pytest gate clean.
- The endpoint exists at `/api/system/extensions` returning 200 with `{"extensions": []}`.

**Do not build:** the actual extensions registry, plugin host, mcp dynamic loading — just the stub endpoint.

---

## BF-322 (GH #791) — remove legacy whisperLoader call from CameraLiveIndicator

**File:** `ui/src/components/perception/CameraLiveIndicator.tsx`

**Current state:** the file imports `loadWhisperModel` from `../../audio/whisperLoader` and uses it inside a `useEffect` (gated on `sttEnabled`) to set `sttModelLoaded`. That fetches `/data/whisper/whisper.js` which no longer exists post-BF-301.

**Fix:**

1. Remove the import: `import { loadWhisperModel } from '../../audio/whisperLoader';`

2. Remove the related `useEffect` block. The relevant block is something like:
   ```ts
   useEffect(() => {
     if (!sttEnabled) return;
     let cancelled = false;
     void loadWhisperModel().then((handle) => {
       if (!cancelled) setSttModelLoaded(handle !== null);
     });
     ...
   }, [sttEnabled]);
   ```

3. Replace the `sttModelLoaded` derivation with a fetch to `/api/voice/health`:
   ```ts
   useEffect(() => {
     if (!sttEnabled) return;
     let cancelled = false;
     fetch('/api/voice/health')
       .then((r) => r.json())
       .then((j) => {
         if (!cancelled) setSttModelLoaded(Boolean(j?.healthy && j?.backend_available));
       })
       .catch(() => {
         if (!cancelled) setSttModelLoaded(false);
       });
     return () => { cancelled = true; };
   }, [sttEnabled]);
   ```

4. Keep the `onTranscribing` subscription unchanged — it's still needed for the `sttTranscribing` flag.

5. Verify no other files import from whisperLoader:
   ```
   grep -rn "from.*whisperLoader" ui/src
   ```
   Only `whisperLoader.ts` itself and its `__tests__` folder should remain.

**Acceptance:**
- Browser console shows zero `/data/whisper/whisper.js` 404s.
- CameraLiveIndicator's STT badge behavior unchanged from operator perspective.
- 957+ vitest passing.

**Do not:**
- Delete `whisperLoader.ts` or `whisperStt.ts` files (deferred to #788).
- Touch the transformers.js path.

---

## Execution

For each BF, in order (320 → 321 → 322):

1. Read the existing file(s) before editing.
2. Make the changes.
3. Run the full gate: `npx vitest run` in `ui/` AND `pytest -n 0 --timeout=60` in repo root.
4. `npm run build` in `ui/` for any frontend BF.
5. Commit with the message format used in BF-319 (subject + multi-paragraph -m body, no markdown headings).
6. `git push`.
7. `gh issue close <#> --comment "Shipped in <commit-hash>. <one-line acceptance summary>."`

Stop the wave and report back if:
- Vitest fails on a test you didn't expect to touch.
- pytest fails on a test that already passed before.
- A grep reveals a hidden caller of `whisperLoader` that the prompt didn't anticipate.
- `npm run build` errors out.

All three BFs combined should be ~150 lines of net diff. If you're exceeding that, stop and report.

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
