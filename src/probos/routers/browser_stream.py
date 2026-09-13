"""AD-706a: Captain-watch MJPEG streaming bridge.

Exposes ``GET /api/browser/sessions/{session_id}/stream`` as
``multipart/x-mixed-replace`` MJPEG. Every browser renders this natively in an
``<img>`` tag, so zero client-side JS is required.

Auth: ``require_crew_scope`` (AD-722b-1) with AD-706a query-param fallback so
``<img src>`` can carry ``?token=``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, StrictBool
from starlette.types import Receive, Scope, Send

from probos.routers.auth import require_browser_actor, require_crew_scope
from probos.routers.deps import get_runtime
from probos.tools.browser.lifecycle import (
    BrowserActor, BrowserLifecycleConflict, BrowserLifecycleResult,
    BrowserSessionListing,
)

router = APIRouter(prefix="/api/browser", tags=["browser-stream"])

_BOUNDARY = b"--frame"


@router.get(
    "/sessions/{session_id}/stream",
    dependencies=[Depends(require_crew_scope)],
)
async def stream_browser_session(
    session_id: str,
    runtime: Any = Depends(get_runtime),
) -> StreamingResponse:
    """AD-706a: yield MJPEG frames from a live BrowserSession.

    Returns:
        404 when the session is not found.
        503 when the configured viewer cap is exhausted.
        200 ``multipart/x-mixed-replace`` otherwise.
    """
    browser_tool = getattr(runtime, "browser_tool", None)
    if browser_tool is None:
        raise HTTPException(status_code=404, detail="browser_tool_unavailable")

    try:
        stream = await browser_tool.admit_stream(session_id)
    except BrowserLifecycleConflict as exc:
        reason = str(exc)
        status = 404 if reason == "session_not_found" else (
            503 if reason == "viewer_cap_exhausted" else 409
        )
        raise HTTPException(
            status_code=status, detail=reason,
            headers={"Retry-After": "5"} if status == 503 else None,
        ) from exc

    async def _generate() -> AsyncIterator[bytes]:
        frames = browser_tool.stream_frames(session_id, stream=stream)
        try:
            async for jpeg_bytes in frames:
                yield (
                    _BOUNDARY
                    + b"\r\nContent-Type: image/jpeg\r\n\r\n"
                    + jpeg_bytes
                    + b"\r\n"
                )
        finally:
            browser_tool.release_stream(stream)
            await frames.aclose()

    class _BrowserStreamingResponse(StreamingResponse):
        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            try:
                await super().__call__(scope, receive, send)
            finally:
                browser_tool.release_stream(stream)

    return _BrowserStreamingResponse(
        _generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            # AD-733-1: long-lived MJPEG streams without no-store cause
            # Chromium to buffer the response body into its on-disk HTTP
            # cache, which can grow to tens of GB during multi-hour
            # Captain-watch sessions and exhaust the system drive.
            # no-store keeps the stream memory-only.
            "Cache-Control": "no-store, no-transform",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sessions", response_model=BrowserSessionListing)
async def list_browser_sessions(
    runtime: Any = Depends(get_runtime),
    actor: BrowserActor = Depends(require_browser_actor),
) -> BrowserSessionListing:
    """AD-1052a: list active browser sessions for the Captain-watch picker.

    Honest-degrade: returns {"enabled": False, "sessions": []} when the
    browser tool is disabled (runtime.browser_tool unset). Same require_crew_scope
    posture as the stream it feeds; the HXI calls it same-origin with no token.
    """
    browser_tool = getattr(runtime, "browser_tool", None)
    if browser_tool is None:
        return BrowserSessionListing(False, [], False, actor.authority_basis)
    return BrowserSessionListing(
        True, await browser_tool.list_session_metadata(),
        browser_tool.input_forwarding_enabled, actor.authority_basis,
    )


class BrowserLifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: StrictBool


@router.post("/sessions/{session_id}/end", response_model=BrowserLifecycleResult)
async def end_browser_session(
    body: BrowserLifecycleRequest,
    response: Response,
    session_id: str = Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    actor: BrowserActor = Depends(require_browser_actor),
    runtime: Any = Depends(get_runtime),
) -> BrowserLifecycleResult:
    browser_tool = getattr(runtime, "browser_tool", None)
    if browser_tool is None:
        result = BrowserLifecycleResult("rejected", "browser_tool_unavailable", 404)
    else:
        result = await browser_tool.end_session(session_id, actor=actor, confirm=body.confirm)
    response.status_code = result.status_code
    return result


@router.post("/sessions/{session_id}/handoff", response_model=BrowserLifecycleResult)
async def handoff_browser_session(
    body: BrowserLifecycleRequest,
    response: Response,
    session_id: str = Path(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    actor: BrowserActor = Depends(require_browser_actor),
    runtime: Any = Depends(get_runtime),
) -> BrowserLifecycleResult:
    browser_tool = getattr(runtime, "browser_tool", None)
    if browser_tool is None:
        result = BrowserLifecycleResult("rejected", "browser_tool_unavailable", 404)
    else:
        result = await browser_tool.hand_to_crew(session_id, actor=actor, confirm=body.confirm)
    response.status_code = result.status_code
    return result


class BridgeConnectRequest(BaseModel):
    """AD-1052b: body for POST /api/browser/bridge/connect."""
    endpoint: str
    confirm: bool = False


class OpenSessionRequest(BaseModel):
    """AD-1161: body for POST /api/browser/sessions."""
    url: str


@router.post("/sessions", dependencies=[Depends(require_crew_scope)])
async def open_browser_session(
    body: OpenSessionRequest, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-1161: open a browser session on the Captain's behalf.

    Honest-degrade: returns {"opened": False, "reason": "Browser tool is
    disabled."} when the tool is off (runtime.browser_tool unset). All policy
    (enabled / domain allow-denylist / tier) lives in BrowserTool — this is a
    thin adapter. Same require_crew_scope posture as the sessions list it feeds.
    """
    browser_tool = getattr(runtime, "browser_tool", None)
    if browser_tool is None:
        return {"opened": False, "reason": "Browser tool is disabled."}
    return await browser_tool.open_captain_session(body.url)


@router.post("/bridge/connect", dependencies=[Depends(require_crew_scope)])
async def connect_browser_bridge(
    body: BridgeConnectRequest, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-1052b: consent-gated, allowlist-validated CDP bridge connect.

    Honest-degrade: returns {"connected": False, "reason": "Browser tool is
    disabled."} when the tool is off (runtime.browser_tool unset). All policy
    (bridge_enabled / confirm / allowlist) lives in BrowserTool — this is a thin
    adapter. Same require_crew_scope posture as the stream / sessions list.
    """
    browser_tool = getattr(runtime, "browser_tool", None)
    if browser_tool is None:
        return {"connected": False, "reason": "Browser tool is disabled."}
    return await browser_tool.connect_bridge_session(
        body.endpoint, agent_id="captain", confirm=body.confirm,
    )


class InputForwardRequest(BaseModel):
    """AD-1052c: body for POST /api/browser/sessions/{session_id}/input."""
    kind: str
    nx: float = 0.0
    ny: float = 0.0
    button: str = "left"
    key: str | None = None
    text: str | None = None
    dx: float = 0.0
    dy: float = 0.0


@router.post("/sessions/{session_id}/input", dependencies=[Depends(require_crew_scope)])
async def forward_browser_input(
    session_id: str, body: InputForwardRequest, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-1052c: gated human-input forward (thin adapter; all policy in BrowserTool)."""
    browser_tool = getattr(runtime, "browser_tool", None)
    if browser_tool is None:
        return {"forwarded": False, "reason": "Browser tool is disabled."}
    return await browser_tool.forward_input(session_id, body.model_dump(), agent_id="captain")
