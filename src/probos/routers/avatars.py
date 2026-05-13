"""AD-721b-1 — Avatar pipeline endpoints.

Currently exposes ``POST /api/avatars/lipsync``: takes a sha256
attachment_id pointing at a previously-uploaded audio blob and returns
a viseme schedule produced by rhubarb-lip-sync. Honest-degrade when the
backend is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/avatars", tags=["avatars"])


@router.post("/lipsync")
async def generate_lipsync(
    req: Request,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Generate a viseme schedule for an audio blob already in AttachmentStore.

    Body: ``{"attachment_id": "<sha256-hex>"}``. The audio blob must have
    been uploaded via ``POST /api/chat/attachments`` or
    ``POST /api/chat/attachments/multipart`` first (AD-720 / AD-720a).

    Returns: ``{"backend": "rhubarb"|"heuristic"|"disabled", "frames": [...]}``.
    Empty ``frames`` means the backend was unavailable AND the client should
    fall back to its own heuristic path (AD-721b-2).
    """
    cfg = getattr(runtime.config, "lipsync", None)
    if cfg is None or not cfg.enabled:
        return {"backend": "disabled", "frames": []}

    payload = await req.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_body")
    attachment_id = payload.get("attachment_id")
    if not (
        isinstance(attachment_id, str)
        and len(attachment_id) == 64
        and all(c in "0123456789abcdef" for c in attachment_id)
    ):
        raise HTTPException(status_code=400, detail="invalid_attachment_id")

    # AD-720: reuse the existing chat-router store accessor; never instantiate
    # a second AttachmentStore (Cloud-Ready Storage seam invariant).
    from probos.routers.chat import _get_attachment_store
    store = _get_attachment_store(runtime)
    if not await store.exists(attachment_id):
        raise HTTPException(status_code=404, detail="attachment_not_found")

    if cfg.backend == "heuristic":
        # Backend set to heuristic — caller does the work client-side. Return
        # empty frames; the AD-721b v1 buildHeuristicTrack path on the client
        # handles the rendering. This branch lets the client query the server
        # for the configured backend without reading config separately.
        return {"backend": "heuristic", "frames": []}

    # backend == "rhubarb"
    from probos.avatars.rhubarb_backend import generate_visemes
    audio_path = await store.get_path(attachment_id)
    frames = await generate_visemes(
        audio_path,
        binary_path=cfg.binary_path,
        timeout_seconds=cfg.timeout_seconds,
    )
    if not frames:
        # generate_visemes already log-and-degraded; tell the client.
        return {"backend": "heuristic", "frames": []}
    return {
        "backend": "rhubarb",
        "frames": [
            {"time": f.time, "duration": f.duration, "viseme": f.viseme}
            for f in frames
        ],
    }
