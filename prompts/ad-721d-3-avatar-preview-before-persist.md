# AD-721d-3 — Visual avatar preview before DSL persistence

**Status:** ready-to-build
**Closes:** #619
**Estimated tests:** +8 pytest +3 vitest
**Depends on:** AD-721d-1 (propose path), AD-721d-2 (Counselor mediation), AD-721i (Blender renderer), AD-720 (AttachmentStore), AD-731 (refs-not-blobs)
**Independent of:** AD-721g, AD-721h, AD-721i-2, AD-720b

---

## Problem

AD-721d-1 returns the proposed `AvatarDSL` as JSON. `AgentProfilePanel.tsx:225` renders it via a **parametric (capsule)** fallback inside the approval modal. The Captain never sees the 3D VRM until **after** approval, because the canonical `<avatars_dir>/<agent_id>.vrm` is only regenerated post-`PUT /appearance` (via the `AvatarRendererAgent` `regenerate_avatar` intent). At that point the Captain has already committed.

Forward marker (#619) waited on AD-721i. Wave 134 shipped the renderer (`src/probos/avatars/blender_renderer.py:113 BlenderRenderer.render() -> Path`). The wiring is now tractable.

## Solution

Add a non-persistent **preview render** path:

1. **New endpoint** `POST /api/agent/{agent_id}/appearance/preview` — accepts the *unpersisted* `AvatarDSL` dict (from the propose response), invokes `BlenderRenderer.render(dsl, agent_id)` directly (NOT via the `regenerate_avatar` intent — that path moves the result into the canonical cache via `os.replace`). The renderer already writes to `<dsl_drafts_dir>/<agent_id>_<ts>.vrm`. The endpoint reads those bytes, stores them in `AttachmentStore` (sha256-addressed), and returns `{"attachment_id": "<sha256>", "preview_iteration": N}`.
2. **HXI**: `AgentProfilePanel.tsx` approval modal renders the proposed DSL with a **new "Render preview" button**. Clicking POSTs to `/appearance/preview`, then loads `/api/chat/attachments/{sha256}` into the existing `CrewVRM.tsx` three.js loader inside the modal. Approve → existing `PUT /appearance` flow (which clears proposal history and triggers the canonical re-render via the renderer agent). Reject → discard.
3. **Honest degrade**: when `cfg.avatars.renderer_enabled=False` or `BlenderNotFoundError`, the endpoint returns HTTP 503 with structured `{"reason": "renderer_unavailable", "detail": "..."}` and the HXI shows "preview unavailable; parametric fallback shown" — the modal still renders the parametric capsule. The Captain can still approve.

The renderer already invokes `asyncio.create_subprocess_exec` (known latent BF-280 risk under SelectorEventLoop — out of scope for this AD; tracked separately. This wave does **not** introduce a new subprocess call site.).

---

## Section 1 — Config

No new config. Reuse:
- `cfg.avatars.enabled` (gate)
- `cfg.avatars.renderer_enabled` (preview-availability gate)
- `cfg.avatars.dsl_drafts_dir` (renderer output dir — already created)
- `cfg.avatars.max_vrm_size_bytes` (size cap mirrored by AttachmentStore)

## Section 2 — Pydantic model

In `src/probos/api_models.py` after `ProposeAppearanceRequest`:

```python
class PreviewAppearanceRequest(BaseModel):
    """AD-721d-3: render an unpersisted AvatarDSL to a draft VRM for Captain preview."""
    dsl: dict[str, Any] = Field(...)
```

Response payload returned as `dict` (no new response model — small surface).

## Section 3 — Endpoint

New endpoint in `src/probos/routers/agents.py` between `propose_agent_appearance` and `set_agent_appearance`:

```python
@router.post("/{agent_id}/appearance/preview")
async def preview_agent_appearance(
    agent_id: str,
    req: PreviewAppearanceRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-721d-3: render unpersisted AvatarDSL → draft VRM → AttachmentStore ref.

    Does NOT persist. Does NOT consume an iteration slot. Does NOT touch
    the canonical <avatars_dir>/<agent_id>.vrm cache. Pure preview.
    """
    _avatars_feature_check(runtime)
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    avatars_cfg = runtime.config.avatars
    if not getattr(avatars_cfg, "renderer_enabled", False):
        raise HTTPException(
            status_code=503,
            detail={"reason": "renderer_unavailable", "detail": "renderer_enabled=False"},
        )

    from probos.avatars.dsl import AvatarDSL
    try:
        dsl = AvatarDSL.model_validate(req.dsl)
    except Exception as exc:
        raise HTTPException(status_code=422, detail={"reason": "schema_violation", "detail": str(exc)})

    from probos.avatars.blender_renderer import (
        BlenderNotFoundError,
        BlenderRenderError,
        BlenderRenderer,
    )
    renderer = BlenderRenderer(
        blender_path=avatars_cfg.blender_path or None,
        timeout_s=int(avatars_cfg.blender_render_timeout_s),
        drafts_dir=_resolve_drafts_dir(avatars_cfg.dsl_drafts_dir),
        max_vrm_size_bytes=int(avatars_cfg.max_vrm_size_bytes),
        avatars_dir=_resolve_avatars_dir(avatars_cfg.avatars_dir),
        procedural_fallback=bool(avatars_cfg.procedural_base_mesh_fallback),
    )
    try:
        vrm_path = await renderer.render(dsl, agent_id)
    except BlenderNotFoundError as exc:
        raise HTTPException(status_code=503, detail={"reason": "blender_not_found", "detail": str(exc)})
    except BlenderRenderError as exc:
        raise HTTPException(status_code=502, detail={"reason": "render_failed", "detail": str(exc)})

    # AD-731 invariant: bytes through AttachmentStore SHA-256 refs, never inlined.
    import hashlib
    blob = vrm_path.read_bytes()
    if len(blob) > int(avatars_cfg.max_vrm_size_bytes):
        raise HTTPException(status_code=413, detail="preview_too_large")
    sha = hashlib.sha256(blob).hexdigest()
    from probos.routers.chat import _get_attachment_store
    store = _get_attachment_store(runtime)
    await store.write(sha, blob, "application/octet-stream")

    try:
        runtime.emit_event(
            "appearance_preview_rendered",
            {"agent_id": agent_id, "attachment_id": sha, "bytes": len(blob)},
        )
    except Exception:
        logger.warning("AD-721d-3: emit_event('appearance_preview_rendered') failed", exc_info=True)

    return {"agent_id": agent_id, "attachment_id": sha, "size_bytes": len(blob)}
```

`_resolve_drafts_dir` / `_resolve_avatars_dir` must be imported from `routers/system.py` (the existing platform-data-dir resolver). Mirror the pattern used by `avatar_agents.py` decide/act split — but the endpoint is the simpler container.

## Section 4 — HXI surface

In `ui/src/components/profile/AgentProfilePanel.tsx`:

- After the propose-response state sets `proposedDsl`, add a "Render preview" button next to the existing Approve/Reject row.
- On click: `POST /api/agent/{agentId}/appearance/preview` with `{ dsl: proposedDsl }`.
- On success: set state `previewAttachmentId` and render `<CrewVRM vrmUrl={`/api/chat/attachments/${previewAttachmentId}`} ... />` in the modal preview pane, replacing the parametric capsule.
- On 503/502: show inline "preview unavailable — parametric fallback shown" (no toast spam); modal stays usable.

`CrewVRM.tsx:250` already resolves bare filenames against the avatar API; add a sibling code path that takes a full URL through as-is (the existing component already supports this for `vrm_url` with a leading `/`).

## Section 5 — Tests

Pytest (`tests/test_ad721d_3_avatar_preview.py`):
1. happy path — valid DSL → 200 with sha256 hex
2. avatars disabled → 503 avatars_feature_check
3. agent missing → 404
4. invalid DSL schema → 422 `schema_violation`
5. `renderer_enabled=False` → 503 `renderer_unavailable`
6. `BlenderNotFoundError` → 503 `blender_not_found` (fake renderer)
7. `BlenderRenderError` → 502 `render_failed`
8. AttachmentStore contract — written blob's sha256 matches the returned `attachment_id` (use real `FilesystemAttachmentStore` per BF-287; no MagicMock for the store)

Vitest (`ui/src/__tests__/AgentProfilePanel.previewAvatar.test.tsx`):
1. clicks "Render preview" → POSTs `/appearance/preview` → swaps preview pane to `CrewVRM` with the attachment URL
2. 503 response → shows "preview unavailable" inline + parametric pane retained
3. respects in-flight disable (no double-click)

Use real `Config()` / real `AgentRegistry` in pytest fixtures per BF-280/282/286/287 lessons. Per AD-738b: this AD ships UI; full gate must include `cd ui; npx vitest run` AND `cd ui; npm run build`.

## Section 6 — Events

New event-type string (not enum) — `"appearance_preview_rendered"`. Matches the existing AD-721d-1 / AD-721d-2 pattern (`appearance_proposal`, `appearance_approved`, `appearance_revision_mediated`).

---

## What This Does NOT Change

- `/appearance/propose` (AD-721d-1) — proposal_history.append still owns iteration counting.
- `/appearance` PUT (AD-721d D7) — approval flow unchanged.
- `AvatarRendererAgent.regenerate_avatar` intent (AD-721i) — canonical-cache renderer unchanged.
- `BlenderRenderer.render()` body — still writes to drafts_dir as before. **Do not** add a PNG output path; v1 reuses the existing VRM output and three.js renders it client-side.
- `asyncio.create_subprocess_exec` in `blender_renderer.py` — known latent risk under SelectorEventLoop (BF-280 family). Out of scope. File a forward marker if you want; do not "fix" it here.

## Tracking

- PROGRESS.md: append AD-721d-3 line, increment test count.
- DECISIONS.md: append AD-721d-3 record (visual preview wires renderer to UI; refs through AttachmentStore per AD-731 invariant; no PNG path; client-side three.js renders VRM).
- Close #619 on merge.

## Acceptance Criteria

- 8 new pytest + 3 new vitest tests, all green under `pytest -n 4 --dist=loadfile` AND `pytest -n 0` (serial sanity).
- `cd ui; npm run build` succeeds — bundle hash changes (per AD-738b).
- Renderer is invoked at most once per preview click (no double-render).
- AD-731 invariant honored: preview bytes through `AttachmentStore.write(sha, blob, mime)`, never inlined in IntentMessage.params or HTTP response body.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-17)

```
grep -n "class BlenderRenderer" src/probos/avatars/blender_renderer.py
  68: class BlenderRenderer:
  113:    async def render(self, dsl: "AvatarDSL", agent_id: str) -> Path:

grep -n "/appearance/propose" src/probos/routers/agents.py
  394: @router.post("/{agent_id}/appearance/propose", response_model=ProposeAppearanceResponse)

grep -n "/appearance" src/probos/routers/agents.py
  499: @router.put("/{agent_id}/appearance")  # PUT persist (existing)

grep -n "_get_attachment_store" src/probos/routers/chat.py
  606: def _get_attachment_store(runtime: Any) -> Any:

grep -n "class AvatarsConfig" src/probos/config.py
  1166: class AvatarsConfig(BaseModel):
  1175:    renderer_enabled: bool = False  # transitional flag

grep -n "dsl_drafts_dir" src/probos/config.py
  1174:    dsl_drafts_dir: str = "data/avatars/.drafts"

grep -n "CrewVRM" ui/src/components/profile/CrewVRM.tsx
  13: import { VRMLoaderPlugin, ... } from '@pixiv/three-vrm';
  250: // Resolve bare filenames (e.g. "Ezri.vrm") against the avatar-serving API.

grep -n "AgentProfilePanel" ui/src/components/profile/AgentProfilePanel.tsx
  225: const r = await fetch(`/api/agent/${agentId}/appearance/propose`, ...
```
