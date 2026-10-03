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

AD-1198 slice 3a: while ``federation.peer_admission_enabled`` is armed a peer
presents no bearer token. It POSTs a signed peer request
(``probos.federation.peer_requests``) to the same path on ``peer_router``, which
``create_app`` serves only then, and this GET answers 403 after step 1 -- even to
this ship's crew-scope token, because peers must never hold it. Off, the GET is
unchanged and ``peer_router`` is not served.

NATS transport, a mime-fastpath, and auto-resolution are deferred to later
AD-731 follow-ups.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from probos.federation.mcp_server import bearer_token_matches, is_json_media_type, read_bounded_body
from probos.federation.peer_requests import ATTACHMENT_REQUEST, MAX_PEER_REQUEST_BYTES
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")
peer_router = APIRouter(prefix="/api")  # AD-1198: served by create_app only while peer admission is armed

_PEER_REQUEST_REFUSED = "peer_request_refused"


def peer_requests_armed(config: Any) -> bool:
    """AD-1198: whether ``federation.peer_admission_enabled`` is armed, so peers fetch with signed requests."""
    return getattr(getattr(config, "federation", None), "peer_admission_enabled", False) is True


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _is_content_hash(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


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
    request: Request,
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
    if peer_requests_armed(runtime.config):  # AD-1198 armed: peers use signed requests, never a bearer token
        if runtime.config.auth.crew_scope_token:
            logger.error(
                "AD-1198: this ship's crew-scope token was presented from %s on GET /api/federation/attachments "
                "while peer admission is armed, and was refused; peers fetch with signed requests and must never "
                "hold it -- if a peer sent it, rotate auth.crew_scope_token",
                _client(request),
            )
        raise HTTPException(status_code=403, detail="federation_peer_request_required")
    # 2. Fail-closed token hardening — never serve through a pass-through gate.
    if not runtime.config.auth.crew_scope_token:
        raise HTTPException(
            status_code=403, detail="remote_serving_requires_token"
        )
    # 3. Content-hash format (no store touch on malformed input).
    if not _is_content_hash(content_hash):
        raise HTTPException(status_code=400, detail="invalid_content_hash")
    return await _serve_blob(runtime, content_hash)


async def _serve_blob(runtime: Any, content_hash: str) -> FileResponse:
    """Steps 4-6 of both routes: existence (404), the size cap (413), then the bytes."""
    attachments = runtime.config.attachments
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


@peer_router.post("/federation/attachments/{content_hash}")
async def serve_peer_attachment(
    content_hash: str,
    request: Request,
    runtime: Any = Depends(get_runtime),
) -> FileResponse:
    """AD-1198: serve attachment bytes to the pinned peer whose signed request names exactly this hash.

    No bearer token is read: a request carrying ``Authorization`` is refused, and this ship's crew-scope
    token arriving here is reported. The flag (404), the media type (415), the hash format (400) and the
    seam's availability (503) are checked before the body is read; every authentication failure after that
    is the same 401, so a caller cannot tell an unknown peer from a bad signature or a replay.
    """
    if not getattr(runtime.config.attachments, "serve_remote_enabled", False):
        raise HTTPException(status_code=404, detail="attachments_remote_serving_disabled")
    if not is_json_media_type(request.headers.get("content-type", "")):
        raise HTTPException(status_code=415, detail="peer_request_must_be_json")
    authorization = request.headers.get("authorization")
    if authorization is not None:  # AD-1198 a peer request carries no bearer credential
        crew = getattr(getattr(runtime.config, "auth", None), "crew_scope_token", "") or ""
        if crew and bearer_token_matches(authorization, crew):
            logger.error(
                "AD-1198: a peer request from %s presented this ship's crew-scope token and was refused; peers "
                "must never hold it, so rotate auth.crew_scope_token",
                _client(request),
            )
        raise HTTPException(status_code=401, detail=_PEER_REQUEST_REFUSED)
    if not _is_content_hash(content_hash):
        raise HTTPException(status_code=400, detail="invalid_content_hash")
    peer_requests = getattr(runtime, "federation_peer_requests", None)
    if peer_requests is None:
        raise HTTPException(status_code=503, detail="federation_peer_requests_unavailable")
    body = await read_bounded_body(request, MAX_PEER_REQUEST_BYTES)
    peer = None if body is None else await peer_requests.authenticate(
        body, topic=ATTACHMENT_REQUEST, payload={"content_hash": content_hash},
    )
    if peer is None:  # AD-1198 one refusal for every authentication failure
        raise HTTPException(status_code=401, detail=_PEER_REQUEST_REFUSED)
    return await _serve_blob(runtime, content_hash)
