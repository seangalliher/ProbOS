# AD-706b — Browser session video recording + retention policy

**Status:** Draft v1.
**Closes:** #517.
**Dependencies:** AD-706 BrowserSession. AD-706a (this wave — provides the frame-capture pattern, though recording uses Playwright `record_video_dir` directly, not MJPEG).
**Estimated tests:** +9 pytest. **0 new pip/npm deps.**

---

## Problem

Forward marker from AD-706 v1. No replay capability for incident triage. AD-454 EvidenceCollector training data has no browser-session source.

## Solution

Use Playwright's built-in `record_video_dir` context option. Sessions opt-in via `BrowserToolConfig.recording_enabled`. Recordings written to `data/browser-sessions/<session_id>/` as `.webm` (Playwright's native format — no transcoding in v1; ffmpeg conversion to MP4 is forward-marked AD-706b-1, uses the AD-721b-1a `_resolve_ffmpeg_binary` helper).

Background reaper deletes recordings older than the configured retention. No AttachmentStore involvement in v1 — recordings stay on disk (per-session bytes can be large; the AttachmentStore is for content-addressable refs, not video archives). AD-706b-2 forward marker covers AttachmentStore promotion.

### Section 0 — Event Types

Add to `event_log.py` after `BROWSER_STREAM_FRAME_DROPPED`:

- `BROWSER_RECORDING_STARTED` — session opened with recording on.
- `BROWSER_RECORDING_STOPPED` — file finalized.
- `BROWSER_RECORDING_EXPIRED` — reaper deleted a recording past retention.
- `BROWSER_RECORDING_FAILED` — Playwright recording errored at close (logged warning, never raised).

### Section 1 — Config

Extend `BrowserToolConfig`:

```python
recording_enabled: bool = False  # default-OFF transitional gate
recording_dir: str = "data/browser-sessions"
recording_retention_days: int = 7  # ge=1, le=365
recording_reaper_interval_seconds: int = 3600  # ge=60, le=86400
recording_max_size_mb_per_session: int = 500  # ge=10, le=5000
```

### Section 2 — Session lifecycle wire-up

`BrowserSession.start()` — when `cfg.recording_enabled`:

```python
recording_path = Path(cfg.recording_dir) / self.session_id
recording_path.mkdir(parents=True, exist_ok=True)
self._context = await self._browser.new_context(
    record_video_dir=str(recording_path),
)
self._recording_path = recording_path
# emit BROWSER_RECORDING_STARTED with session_id and path
```

When `cfg.recording_enabled is False`, `new_context()` called WITHOUT `record_video_dir` (current behavior, byte-identical).

`BrowserSession.stop()` — after `_context.close()` (which finalizes the webm), emit `BROWSER_RECORDING_STOPPED` with the resolved file path and size (via `path.stat().st_size`). On failure, emit `BROWSER_RECORDING_FAILED` and continue.

### Section 3 — Recording reaper

New file `src/probos/tools/browser/recording_reaper.py`:

```python
class RecordingReaper:
    def __init__(self, *, cfg: BrowserToolConfig, emit_event_fn): ...
    async def start(self) -> None: ...  # creates background task
    async def stop(self) -> None: ...   # cancels and awaits cleanup
    async def reap_once(self) -> int:   # returns count deleted; for tests
```

The background task loops on `await asyncio.sleep(cfg.recording_reaper_interval_seconds)`, calls `reap_once`, then loops again. Catches `CancelledError`, performs cleanup, re-raises (standing async discipline).

`reap_once()`:
1. Walks `recording_dir` for subdirectories.
2. For each subdir, finds `*.webm` files.
3. If `mtime` is older than `retention_days * 86400` seconds, deletes the file and emits `BROWSER_RECORDING_EXPIRED`.
4. If the parent subdirectory is empty after deletion, removes it.
5. Per-session size cap: if cumulative `*.webm` size > `recording_max_size_mb_per_session * 1024 * 1024`, deletes oldest until under.
6. Tier-2 throughout — file-not-found / permission errors logged at warning, never raised.

Holds task reference per async discipline (standing order):
```python
self._task: asyncio.Task | None = None
```

### Section 4 — Runtime wiring

`src/probos/startup/finalize.py` (verify location via grep before SEARCH/REPLACE):

Two-phase wiring (mirrors AD-722d):
1. Declare `runtime.recording_reaper = None` next to BrowserTool construction.
2. After config resolved, if `cfg.tools.browser.recording_enabled`, construct `RecordingReaper`, `await reaper.start()`, assign to `runtime.recording_reaper`.

`runtime.stop()` (verified at `src/probos/runtime.py:2227` — the public async shutdown hook; there is NO `runtime.shutdown()`) calls `await runtime.recording_reaper.stop()` if not None (defensive — the cancellation path is the standard async-cleanup pattern). Place the cleanup call in the same block as other reaper-class teardown (grep `_reaper_task` / `await .*stop()` inside `runtime.stop` for the canonical insertion point).

### Section 5 — Admin endpoints (Captain only)

New file `src/probos/routers/browser_recordings.py`:

- `GET /api/browser/recordings` — list all `<session_id>/*.webm` with size + mtime.
- `GET /api/browser/recordings/{session_id}/{filename}` — `FileResponse` (streams the file).
- `DELETE /api/browser/recordings/{session_id}` — wipes the subdir immediately.

All three behind `Depends(require_crew_scope)`. The GET routes also accept `?token=` per the AD-706a query-param extension.

### Tests (`tests/test_ad706b_session_recording.py`)

1. `test_recording_disabled_by_default`.
2. `test_recording_enabled_passes_record_video_dir_to_context` — assert `_FakeBrowser.new_context` called with `record_video_dir` set.
3. `test_recording_emits_started_and_stopped_events`.
4. `test_session_stop_emits_failed_event_when_close_raises` — Tier-2 contract.
5. `test_reaper_deletes_files_older_than_retention` — set mtime to retention+1d ago via `os.utime`, run `reap_once`, assert deleted.
6. `test_reaper_preserves_files_within_retention`.
7. `test_reaper_enforces_per_session_size_cap` — write 3 fake files; assert oldest deleted when cap exceeded.
8. `test_reaper_removes_empty_session_directory_after_cleanup`.
9. `test_recordings_router_returns_503_without_crew_scope_token`.

All tests use real `BrowserToolConfig()` + `tmp_path` for `recording_dir` + `_FakeBrowser`/`_FakeContext` for Playwright (BF-287). Reaper tests call `reap_once()` directly, bypassing the background task (test isolation).

## What This Does NOT Change

- `_action_screenshot` and AD-706a streaming are independent — recording captures everything, streaming is point-in-time observation.
- WebM is the v1 format (Playwright native). Transcoding to MP4 deferred.
- AttachmentStore NOT used for recordings in v1 — recordings live on disk under `recording_dir`.
- BrowserSession TTL / rate limiting unchanged.

## Tracking

- `PROGRESS.md` — Wave 166 entry.
- `docs/development/roadmap.md` — close #517.
- `DECISIONS.md` — append AD-706b. Note Playwright-native webm choice + AttachmentStore deferral rationale.

Forward markers (TECHNICAL triggers):
- AD-706b-1 — webm → MP4 transcoding via the AD-721b-1a `_resolve_ffmpeg_binary` helper. Trigger: ≥3 operator playback issues with webm OR commercial-overlay request.
- AD-706b-2 — Recording → AttachmentStore SHA-256 promotion (auto-write on close). Trigger: AD-720b chat-attach lands AND recordings need to surface as chat attachments.
- AD-706b-3 — Per-action timeline index (sidecar JSON mapping recording timestamp ranges to BrowserTool action events). Trigger: AD-454 EvidenceCollector needs frame-action correlation.
- AD-706b-4 — Operator-driven recording redaction (pause/resume on credential entry). Trigger: AD-706f credential vault lands and a credential-entry session is recorded.

## Acceptance Criteria

- 9 tests green under serial + parallel gates.
- Full pytest gate: previous +N → ≥+9.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- No new pip/npm deps.
- `data/browser-sessions/` added to `.gitignore` (recordings are operator data, not tracked).

## Verified Against Codebase (2026-05-16)

```
grep -n "async def start" src/probos/tools/browser/session.py
  77:    async def start(self) -> None:

grep -n "new_context" src/probos/tools/browser/session.py
  86:        self._context = await self._browser.new_context()

grep -n "class BrowserToolConfig" src/probos/config.py
  936: class BrowserToolConfig(BaseModel):

grep -n "require_crew_scope" src/probos/routers/auth.py
  40: async def require_crew_scope(
```

Playwright `BrowserContext(record_video_dir=...)` is the documented Playwright API — recordings are `.webm` per Playwright's default codec.
