# AD-721h — Browser-based VRM upload UI

**Status:** ready-to-build
**Closes:** #535
**Estimated tests:** +8 pytest +4 vitest
**Depends on:** AD-720a (multipart upload), AD-721 D6 (avatar serve route)
**Independent of:** AD-721d-3, AD-721g, AD-721i-2, AD-720b

---

## Problem

Today the Captain installs custom VRM files by manually copying them to `<platform_data_dir>/avatars/<agent_id>.vrm` and (optionally) editing the seed profile. There is no browser surface. Forward marker #535 closes the gap: Captain drags a `.vrm` into the HXI avatar editor → backend validates type/size → file lands at `<avatars_dir>/<agent_id>.vrm` → existing serve route surfaces it.

AD-720a (`POST /api/chat/attachments/multipart`, `routers/chat.py:763`) is the multipart pattern to reuse. AttachmentStore is content-addressed (AD-731 invariant) — we **do** want the bytes in AttachmentStore (for traceability + dedup) **AND** we want a named copy at `<avatars_dir>/<agent_id>.vrm` (because the avatar-serve route is keyed by filename, not by sha256).

## Solution

A **new multipart endpoint** that:

1. Validates type (`.vrm` magic bytes — glTF binary), size cap (reuse `cfg.avatars.max_vrm_size_bytes`), MIME (`application/octet-stream`).
2. Writes content-addressed copy to `AttachmentStore` (preserves AD-731 invariant + dedup + audit).
3. Atomically `os.replace`s the bytes into `<avatars_dir>/<agent_id>.vrm` (matches the existing AD-721i renderer cache contract — overwrite is the cache-invalidation pattern).
4. Updates `crew.appearance.vrm_url = f"{agent_id}.vrm"` via `ProfileStore` (mirrors the AD-721i E4 post-render persistence).
5. Emits `appearance_vrm_uploaded` audit event.
6. Returns `{"agent_id", "attachment_id", "vrm_url", "bytes"}`.

The HXI surfaces this in `AgentProfilePanel.tsx` as an "Upload VRM" button + drag/drop zone next to the existing "Design avatar" button. Re-uses the existing `IntentSurface.tsx:525` multipart pattern.

---

## Section 1 — Config

No new config. Reuse:
- `cfg.avatars.enabled` (feature gate — endpoint returns 503 when off)
- `cfg.avatars.max_vrm_size_bytes` (size cap)
- `cfg.avatars.avatars_dir` (resolution via existing `_resolve_avatars_dir`)

## Section 2 — Endpoint

New endpoint in `src/probos/routers/agents.py` after `set_agent_appearance`:

```python
@router.post("/{agent_id}/appearance/vrm")
async def upload_agent_vrm(
    agent_id: str,
    file: UploadFile = File(...),
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-721h: Captain-driven VRM upload for an existing agent.

    Multipart. The bytes are stored content-addressably via AttachmentStore
    (AD-731 invariant) AND copied to the named avatar cache so the existing
    /system/avatars/{filename} serve route can dispatch.
    """
    _avatars_feature_check(runtime)
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    avatars_cfg = runtime.config.avatars
    max_bytes = int(avatars_cfg.max_vrm_size_bytes)
    blob = await file.read()
    if len(blob) > max_bytes:
        raise HTTPException(status_code=413, detail={"reason": "too_large", "size": len(blob), "max": max_bytes})
    if len(blob) < 12:
        raise HTTPException(status_code=400, detail={"reason": "too_small"})

    # glTF binary magic = b"glTF" at offset 0 (VRM 1.0 = glTF binary container).
    if blob[:4] != b"glTF":
        raise HTTPException(status_code=415, detail={"reason": "not_a_vrm", "detail": "missing glTF magic bytes"})

    # AD-731: content-addressed write first.
    import hashlib
    sha = hashlib.sha256(blob).hexdigest()
    from probos.routers.chat import _get_attachment_store
    store = _get_attachment_store(runtime)
    await store.write(sha, blob, "application/octet-stream")

    # Atomic named copy → <avatars_dir>/<agent_id>.vrm.
    from probos.routers.system import _resolve_avatars_dir
    avatars_dir = _resolve_avatars_dir(avatars_cfg.avatars_dir)
    avatars_dir.mkdir(parents=True, exist_ok=True)
    target = avatars_dir / f"{agent_id}.vrm"
    # Defense-in-depth path-traversal guard (agent_id is operator-controlled
    # but registry.get already constrained it to a known agent — still check).
    try:
        target.resolve().relative_to(avatars_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid agent_id")
    import os
    tmp = target.with_suffix(".vrm.tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, target)

    # Persist vrm_url on the profile so the read path picks it up.
    if hasattr(runtime, "profile_store") and runtime.profile_store is not None:
        crew = runtime.profile_store.get_or_create(
            agent.id, agent_type=agent.agent_type, pool=agent.pool,
        )
        crew.appearance.vrm_url = f"{agent_id}.vrm"
        runtime.profile_store.update(crew)

    try:
        runtime.emit_event(
            "appearance_vrm_uploaded",
            {"agent_id": agent_id, "attachment_id": sha, "bytes": len(blob)},
        )
    except Exception:
        logger.warning("AD-721h: emit_event('appearance_vrm_uploaded') failed", exc_info=True)

    return {
        "agent_id": agent_id,
        "attachment_id": sha,
        "vrm_url": f"{agent_id}.vrm",
        "bytes": len(blob),
    }
```

Add `UploadFile, File` to the existing FastAPI imports in `routers/agents.py` (grep — they may already be imported via the same `from fastapi import ...` line; check before adding).

## Section 3 — HXI surface

In `ui/src/components/profile/AgentProfilePanel.tsx`, next to the existing "Design avatar" button (line ~218), add an "Upload VRM" button + hidden `<input type="file" accept=".vrm,application/octet-stream">`. On change:

```ts
const fd = new FormData();
fd.append('file', file);
const r = await fetch(`/api/agent/${agentId}/appearance/vrm`, { method: 'POST', body: fd });
```

Mirror the existing `IntentSurface.tsx:525` pattern. On success, refresh the appearance state (re-fetch `/api/agent/{id}/appearance`) so `CrewVRM.tsx` re-loads with the new URL. On 413/415: inline error message (no toast spam). Add drag/drop zone wrapping the modal preview pane (drop accepted only when no other file is in-flight).

## Section 4 — Tests

Pytest (`tests/test_ad721h_vrm_upload.py`, +8):
1. happy path — valid glTF-magic blob ≤ size cap → 200, named file exists, `vrm_url` updated, attachment_id matches sha256
2. avatars disabled → 503
3. agent missing → 404
4. blob >max → 413 `too_large`
5. blob <12 bytes → 400 `too_small`
6. blob without `glTF` magic → 415 `not_a_vrm`
7. AttachmentStore + named-cache parity — bytes at both locations are identical
8. concurrent upload (two requests in flight for same agent) — last-write-wins, no half-written file (verify `os.replace` atomicity by reading the file at random points; or just verify final bytes match second upload)

Use real `FilesystemAttachmentStore` (BF-287) and real `tmp_path`-rooted avatars_dir. Real `Config()`.

Vitest (`ui/src/__tests__/AgentProfilePanel.uploadVRM.test.tsx`, +4):
1. clicks "Upload VRM" → file selected → POSTs multipart to `/appearance/vrm` with `file` field
2. 413 response → inline "too large" error
3. 415 response → inline "not a VRM file" error
4. successful upload → re-fetches `/appearance` → `CrewVRM` mounts with new `vrm_url`

Per AD-738b: `cd ui; npm run build` must succeed and bundle hash must change.

## Section 5 — Drag-and-drop

Reuse the AD-730-1-1 pattern from `ui/src/components/WardRoomThreadDetail.tsx` (Wave 161 grep `drag/drop + paste-image attachment`). Same pattern: `onDragOver`/`onDrop` on a div, single-file accept, max size enforced client-side BEFORE POST to give faster feedback.

---

## What This Does NOT Change

- AttachmentStore protocol (`src/probos/attachments/store.py`) — VRM bytes use the same `write(sha, blob, mime)` contract.
- Avatar-serve route (`routers/system.py:639`) — unchanged; still filename-keyed.
- AvatarRendererAgent — uploads are operator-provided VRMs; the renderer is unaffected.
- AD-720a `/chat/attachments/multipart` endpoint — unchanged. AD-721h is a sibling endpoint, not an extension.
- Validation depth — v1 checks magic bytes only. Full VRM 1.0 schema validation (e.g. saturday06 add-on roundtrip) is **deferred**; file a forward marker AD-721h-2 if Captain wants it.

## Tracking

- PROGRESS.md: append AD-721h, increment test count.
- DECISIONS.md: append AD-721h record (multipart upload reuses AD-720a pattern; AD-731 invariant honored via dual-write — content-addressed + named cache; v1 validates glTF magic only).
- Close #535 on merge.

## Acceptance Criteria

- 8 new pytest + 4 new vitest tests pass under `-n 4 --dist=loadfile` AND `-n 0`.
- `cd ui; npm run build` succeeds — bundle hash changes (per AD-738b).
- No `.vrm` bytes added to the repo tree.
- A 27 MB file (over the 25 MB default cap) is rejected with structured 413 — not silently truncated.
- Path traversal via `agent_id` parameter is impossible (already gated by `registry.get`, but the explicit `target.resolve().relative_to(avatars_dir.resolve())` check provides defense in depth).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-17)

```
grep -n "/chat/attachments/multipart" src/probos/routers/chat.py
  763: @router.post("/chat/attachments/multipart")
  764: async def upload_chat_attachment_multipart(

grep -n "UploadFile" src/probos/routers/chat.py
  10: from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

grep -n "max_vrm_size_bytes" src/probos/config.py
  1171:    max_vrm_size_bytes: int = 25 * 1024 * 1024

grep -n "/system/avatars" src/probos/routers/system.py
  639: @router.get("/system/avatars/{filename}")

grep -n "_resolve_avatars_dir" src/probos/routers/system.py
  669: def _resolve_avatars_dir(configured: str) -> Path:

grep -n "vrm_url" src/probos/crew_profile.py
  266:    vrm_url: str = ""

grep -n "FilesystemAttachmentStore" src/probos/attachments/filesystem_store.py
  59: class FilesystemAttachmentStore:

grep -n "/chat/attachments/multipart" ui/src/components/IntentSurface.tsx
  525:    const res = await fetch('/api/chat/attachments/multipart', { method: 'POST', body: fd });
```
