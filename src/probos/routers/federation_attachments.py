"""AD-731a-1: cross-host attachment serving endpoint (issue #638).

Default-OFF, fail-closed serving of content-addressed attachment bytes to an
authenticated federation peer. Pairs with the verifying client helper in
``probos/federation/attachment_fetch.py``.

Security posture (Defense in Depth, evaluated in order):
1. Feature flag (``attachments.serve_remote_enabled``) — 404 when off
   (byte-identical to "feature absent"; does not leak token state).
2. Token hardening — 403 when ``auth.crew_scope_token`` is unset, because
   ``require_crew_scope`` is a pass-through with an empty token and we must
   never serve bytes through an open gate.
3. Content-hash format — 400 on a non-64-hex hash (no store touch).
4. Existence — 404 when the blob is absent.
5. Size cap — 413 when the blob exceeds ``max_attachment_bytes``.
6. Serve the bytes (content-addressed path; mime via ``ext_to_mime``).

NATS transport, a mime-fastpath, and auto-resolution are deferred to later
AD-731 follow-ups.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

router = APIRouter(prefix="/api")


def _get_attachment_store(runtime: Any) -> Any:
    """Resolve the content-addressed attachment store.

    Prefers ``runtime.attachment_store`` (set during startup; injectable in
    tests on a tmp_path per BF-287) and falls back to the chat-router resolver
    when the attribute is absent. The fallback keeps production robust without
    coupling this module to the filesystem root layout.
    """
    store = getattr(runtime, "attachment_store", None)
    if store is not None:
        return store
    from probos.routers.chat import _get_attachment_store as _chat_get_store
    return _chat_get_store(runtime)


@router.get(
    "/federation/attachments/{content_hash}",
    dependencies=[Depends(require_crew_scope)],
)
async def serve_remote_attachment(
    content_hash: str,
    runtime: Any = Depends(get_runtime),
) -> FileResponse:
    """Serve attachment bytes by content-hash to an authenticated peer.

    AD-731a-1: default-OFF + fail-closed. See the module docstring for the
    Defense-in-Depth ordering. ``require_crew_scope`` (the route dependency)
    enforces the bearer token BEFORE this body runs; the in-body token check
    is the fail-closed guard against the pass-through (empty-token) mode.
    """
    attachments = runtime.config.attachments
    # 1. Feature flag — default-OFF.
    if not getattr(attachments, "serve_remote_enabled", False):
        raise HTTPException(
            status_code=404, detail="attachments_remote_serving_disabled"
        )
    # 2. Fail-closed token hardening — never serve through a pass-through gate.
    if not runtime.config.auth.crew_scope_token:
        raise HTTPException(
            status_code=403, detail="remote_serving_requires_token"
        )
    # 3. Content-hash format (no store touch on malformed input).
    if not (
        len(content_hash) == 64
        and all(c in "0123456789abcdef" for c in content_hash)
    ):
        raise HTTPException(status_code=400, detail="invalid_content_hash")
    # 4. Existence.
    store = _get_attachment_store(runtime)
    if not await store.exists(content_hash):
        raise HTTPException(status_code=404, detail="attachment_not_found")
    # 5. Size cap.
    if await store.size(content_hash) > attachments.max_attachment_bytes:
        raise HTTPException(status_code=413, detail="attachment_too_large")
    # 6. Serve — content-addressed path; mime via the single-source helper.
    #    Mirrors routers/chat.py's GET /chat/attachments serve pattern, with
    #    the crew-scope auth dependency added.
    from probos.attachments.filesystem_store import ext_to_mime
    path = await store.get_path(content_hash)
    mime = ext_to_mime(path.suffix)
    return FileResponse(path, media_type=mime)
