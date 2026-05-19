# AD-733-1 — AttachmentStore retention + perception-frame reaper

**Status:** Drafted 2026-05-18, awaiting GATE 1.
**Closes:** [#667](https://github.com/seangalliher/ProbOS/issues/667).
**Estimated tests:** +14 pytest.
**Depends on:** AD-720 (`FilesystemAttachmentStore`), AD-733 (camera ingestion endpoint), AD-733a (`VisionConsumer`).

## Problem

The 2026-05-18 disk-fill incident: with `perception.camera.enabled = True` and the operator's webcam streaming at 1 fps, ProbOS exhausted free space on both the Chromium HTTP cache (C:) AND the AttachmentStore root (D:), crashing `upload_camera_frame` with `OSError: [Errno 28] No space left on device`. Traceback (verbatim, captured 2026-05-18):

```
File "D:\ProbOS\src\probos\routers\perception.py", line 128, in upload_camera_frame
File "D:\ProbOS\src\probos\routers\chat.py", line 699, in _validate_and_store_attachment
File "D:\ProbOS\src\probos\attachments\filesystem_store.py", line 90, in write
    await asyncio.to_thread(path.write_bytes, blob)
OSError: [Errno 28] No space left on device
```

Two independent leaks contributed:

1. **Server-side (this AD's primary scope):** every webcam frame at 1 fps is content-addressed and written to `data/attachments/` via `_validate_and_store_attachment` → `FilesystemAttachmentStore.write`. Unique frames don't dedupe. There is no retention policy, no TTL, no size cap, and nothing distinguishes ephemeral perception frames (`vision_observation`) from operator-pasted attachments that should live forever. At ~30 KB/frame × 1 fps × 24 h = **~2.6 GB/day per session, forever.** Multi-day operation = inevitable disk exhaustion.

2. **Client-side (already triaged in working tree, codified here as Section 4):** `GET /api/browser/sessions/{id}/stream` returned a `multipart/x-mixed-replace` MJPEG with no `Cache-Control`. Chromium spools long-lived streaming responses to its on-disk HTTP cache; for an indefinite MJPEG the cache entry grows until the socket closes. A multi-hour Captain-watch session produced tens of GB of cache under `%LOCALAPPDATA%\Microsoft\Edge\User Data\Default\Cache`. The user-memory note `Chromium MJPEG cache-bloat without no-store` captures the pattern.

## Why both in one AD

The user-visible bug is identical ("camera streaming filled my disk"); the diagnosis is the same triage path; the two fixes share the perception subsystem as the affected feature. Splitting would lose the failure-mode-catalog value. The MJPEG `no-store` fix is one line and ships in Section 4; the substantial work (Sections 1-3) is the server-side retention substrate.

## Solution overview

1. **Tag attachments with an origin** at write time, so the AttachmentStore can distinguish `perception_frame` (ephemeral, sweep-eligible) from `chat_attachment` (operator intent, retain forever) without changing the content-addressed hash-keying.
2. **Sidecar JSON index** (`data/attachments/.index.json`) records `{sha → {origin, written_at, mime, size_bytes}}`. Updated on `write()` and `unlink()`. Loaded lazily, persisted atomically (write-temp + rename).
3. **Janitor task** (`AttachmentReaper`) runs every `perception.reaper_interval_seconds` (default 60s). Two policies, both honest-degrade on filesystem errors:
   - **Age TTL** for origin=`perception_frame`: delete entries whose `written_at` is older than `perception.frame_retention_seconds` (default 300s — five minutes of recent history is enough for VisionConsumer's working memory + the AD-733c-1 force-describe cache; older frames are dead weight).
   - **LRU size cap** for the whole store: if `data/attachments/` total size exceeds `attachments.max_store_bytes` (default 5 GiB), evict oldest by `written_at` until under cap. Operator attachments are preferred-retain (sorted last in the eviction list); perception frames are evicted first regardless of age. Safety net regardless of which producer leaks.
4. **MJPEG `no-store`** on `browser_stream.py` so Chromium doesn't disk-spool the Captain-watch viewport. (Already applied to the working tree on 2026-05-18; this section commits it.)
5. **EventTypes** for observability: `ATTACHMENT_REAPED` (per sweep summary: `{policy, removed_count, freed_bytes}`) and `ATTACHMENT_STORE_DISK_FULL` (raised when `write()` catches `OSError(28)` — replaces the current bare 500 with a logged warning + 503 + Retry-After).

### Section 1: Config knobs

`src/probos/config.py`

Extend `PerceptionConfig`:

```python
class PerceptionConfig(BaseModel):
    """AD-733: visual sensor input from operator-side capture devices."""

    enabled: bool = False
    """Master switch for the entire perception subsystem."""

    camera: CameraStreamConfig = Field(default_factory=CameraStreamConfig)

    camera_max_fps_server: int = Field(default=4, ge=1, le=10,
        description="Server-side hard cap on frame ingestion rate per session.",
    )

    frame_max_size_bytes: int = Field(default=512 * 1024, ge=4096, le=5 * 1024 * 1024,
        description="Reject frame uploads larger than this. Default 512 KB.",
    )

    # AD-733-1: ephemeral-frame retention. Perception frames are
    # content-addressed and written to the AttachmentStore for the
    # VisionConsumer's working-memory + force-describe cache, but they
    # are NOT operator intent — they expire shortly after capture. The
    # reaper sweeps origin=perception_frame entries older than this.
    frame_retention_seconds: int = Field(default=300, ge=30, le=86400,
        description=(
            "AD-733-1: TTL for perception-origin attachments. Default 5 min — "
            "covers VisionConsumer WM window + AD-733c-1 force-describe cache."
        ),
    )

    reaper_interval_seconds: int = Field(default=60, ge=10, le=3600,
        description=(
            "AD-733-1: how often the AttachmentReaper sweeps. Default 60s — "
            "produces at most one full directory scan per minute."
        ),
    )
```

Extend `AttachmentsConfig`:

```python
class AttachmentsConfig(BaseModel):
    """AD-720: chat attachments configuration."""

    enabled: bool = True
    attachments_dir: str = "data/attachments"
    max_attachment_bytes: int = 10 * 1024 * 1024
    # ... existing fields unchanged ...

    # AD-733-1: store-level LRU cap. Tier-2 safety net regardless of
    # which producer (chat paste, perception, browser tool, future
    # sensors) leaks. 0 disables the LRU pass; the age-TTL still runs.
    max_store_bytes: int = Field(default=5 * 1024 * 1024 * 1024, ge=0,
        description=(
            "AD-733-1: total bytes ceiling for attachments_dir. Reaper "
            "evicts oldest perception_frame entries first, then oldest "
            "chat_attachment entries, until under cap. 0 = disabled."
        ),
    )
```

### Section 2: AttachmentStore origin tagging + sidecar index

`src/probos/attachments/store.py` (Protocol) — extend `write` signature with `origin: str = "chat_attachment"`. Allowed values: `chat_attachment`, `perception_frame`, `browser_screenshot`, `avatar_render`. Unknown origins log WARNING and default to `chat_attachment` (safe — never sweeps).

`src/probos/attachments/filesystem_store.py` — `FilesystemAttachmentStore`:

- Add `_index_path = self._root / ".index.json"`.
- Add `_index: dict[str, dict[str, Any]]` loaded lazily in `__init__` via `_load_index_sync()`. Schema: `{sha: {origin: str, written_at: float, mime: str, size_bytes: int}}`. Corrupt index → log WARNING, start with `{}`, NEVER raise (the actual files on disk are the source of truth; the index is a hint).
- `write(content_hash, blob, mime, *, origin="chat_attachment")`: idempotent path-exists short-circuit still returns the path, BUT updates the index entry's `written_at` to `time.time()` (LRU touch) — only if origin is unchanged or upgrading from `perception_frame` to a more-durable origin. Pin-style upgrade prevents perception frames from being re-promoted to chat attachments by a hash collision.
- New `async unlink(content_hash) -> bool`: removes both the disk file and the index entry. Returns `False` if not found. Never raises on `FileNotFoundError` (concurrent reaper sweep).
- New `async list_by_origin(origin) -> list[tuple[str, float]]`: returns `[(sha, written_at)]` sorted ascending by `written_at`. Backed by index, not directory scan, so it's O(N) in index size.
- New `async total_size_bytes() -> int`: index-sum; falls back to disk scan if index is empty or stale.
- `write()` catches `OSError` with `errno == errno.ENOSPC`, emits `ATTACHMENT_STORE_DISK_FULL`, and re-raises as `AttachmentStoreFullError` (new exception). The current path-write call stays inside `asyncio.to_thread`.

### Section 3: AttachmentReaper janitor

New `src/probos/attachments/reaper.py`:

```python
"""AD-733-1: Attachment retention / LRU reaper.

Two policies, run in sequence each tick:
  1. Age TTL — origin=perception_frame older than frame_retention_seconds.
  2. LRU cap — if total > attachments.max_store_bytes, evict oldest
     perception_frame entries first, then oldest chat_attachment entries,
     until under cap.

Tier-2 honest-degrade: any filesystem error is logged at WARNING; the
sweep continues with the next candidate. Never raises out of the loop.
"""
```

Public surface:

- `AttachmentReaper(store, *, perception_cfg, attachments_cfg, event_emitter)`.
- `async start()` — creates `asyncio.Task` running `_loop()`.
- `async stop()` — cancels + awaits.
- `async sweep_once() -> dict[str, int]` — runs both policies once, returns `{age_ttl_removed, lru_removed, freed_bytes}`. Public for tests.

Wire-up in `src/probos/runtime/finalize.py` (or wherever the perception subsystem is finalized today; grep for `PerceptionConfig` consumers): construct `AttachmentReaper` when `perception.enabled or attachments.max_store_bytes > 0`, register `start()` in the runtime's startup tasks, register `stop()` in the shutdown hooks. Reaper MUST NOT prevent shutdown — `stop()` cancels the task with a 2s grace timeout.

`src/probos/routers/perception.py:upload_camera_frame` — pass `origin="perception_frame"` through `_validate_and_store_attachment` → `store.write`. This requires extending `_validate_and_store_attachment` in `chat.py` with an `origin: str = "chat_attachment"` keyword param (default preserves current chat behavior).

### Section 4: MJPEG `Cache-Control: no-store` (codifying the 2026-05-18 hotfix)

`src/probos/routers/browser_stream.py` — already patched in the working tree as part of triage. The committed change is:

```python
    return StreamingResponse(
        _generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            # AD-733-1: long-lived MJPEG without no-store causes Chromium
            # to buffer the response body into its on-disk HTTP cache,
            # which can grow to tens of GB during multi-hour Captain-watch
            # sessions and exhaust the system drive. no-store keeps the
            # stream memory-only.
            "Cache-Control": "no-store, no-transform",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

The Architect's review should confirm the comment cites AD-733-1 (currently cites a placeholder `BF:` from the hotfix turn). The Builder must re-run `Get-Content` on this file before committing — the working tree was edited 2026-05-18 by Captain's session; the diff in this AD's commit must equal "comment-only retitle" relative to HEAD if the hotfix landed cleanly, or full block insertion if it did not.

### Section 5: Tests

`tests/test_filesystem_store_origin.py` (+5):
- write with `origin="perception_frame"` then `list_by_origin("perception_frame")` returns the sha.
- write same hash twice with same origin → idempotent, `written_at` updated (LRU touch).
- write same hash with upgraded origin (perception_frame → chat_attachment) → origin upgrades.
- corrupt `.index.json` → loads as empty dict + WARNING log + no raise.
- `OSError(ENOSPC)` raises `AttachmentStoreFullError` and emits `ATTACHMENT_STORE_DISK_FULL`.

`tests/test_attachment_reaper.py` (+7):
- age TTL: write three perception_frame entries with `written_at` set to `now - 600`; `sweep_once()` removes all three; `chat_attachment` entries untouched.
- age TTL respects `frame_retention_seconds` config knob (parametrize 30/300/3600).
- LRU cap: write 10 entries totaling 10 MB with `max_store_bytes=5 MB`; sweep evicts perception_frame oldest first, chat_attachment last; stops once under cap.
- LRU `max_store_bytes=0` → policy disabled, no LRU evictions (age TTL still runs).
- reaper continues past `FileNotFoundError` (concurrent unlink) without raising.
- reaper continues past `PermissionError` (Windows file-in-use) with WARNING log.
- `start()` + `stop()` round-trip cancels the task within 2s.

`tests/test_camera_frame_origin.py` (+2):
- POST `/api/perception/camera/frame` writes the attachment with `origin="perception_frame"` (assert via `store._index[sha]["origin"] == "perception_frame"`).
- chat paste still writes with `origin="chat_attachment"` (regression guard).

## Acceptance criteria

- `data/attachments/` size stays bounded under sustained 1 fps webcam streaming. Stretch goal: integration test that runs a 60-second 1-fps simulated capture with `frame_retention_seconds=10` and asserts the store size never exceeds 11 frames' worth of bytes.
- `ATTACHMENT_REAPED` events appear in the journal during a perception session.
- Captain-watch MJPEG stream serves with `Cache-Control: no-store`; verified by `curl -I` capture in the test plan.
- No regression in chat-paste attachment durability — pasted images remain on disk indefinitely regardless of age (verified by `tests/test_attachment_reaper.py` LRU-disabled case).

## Refs

- 2026-05-18 user-memory note: *Chromium MJPEG cache-bloat without no-store on multipart/x-mixed-replace streams*.
- 2026-05-18 user-memory note: *Perception frames as durable attachments — wrong substrate; needs TTL + LRU reaper*.
- AD-720 (FilesystemAttachmentStore v1, content-addressed).
- AD-731 (refs not blobs on the bus — perception frames currently produce one new ref per second).
- AD-733 / AD-733a / AD-733b / AD-733c-1 (the camera ingestion + consumer + observer + force-describe stack that produces the frames).
- BF-265 / BF-267 reflex correction (refs not blobs, attached store is the right substrate — this AD makes the SUBSTRATE bounded).
