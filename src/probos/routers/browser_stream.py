"""AD-706a: Captain-watch MJPEG streaming bridge.

Exposes ``GET /api/browser/sessions/{session_id}/stream`` as
``multipart/x-mixed-replace`` MJPEG. Every browser renders this natively in an
``<img>`` tag, so zero client-side JS is required.

Auth: ``require_crew_scope`` (AD-722b-1) with AD-706a query-param fallback so
``<img src>`` can carry ``?token=``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from probos.events import EventType
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/browser", tags=["browser-stream"])

_BOUNDARY = b"--frame"


def _safe_emit(runtime: Any, event_type: EventType, payload: dict[str, Any]) -> None:
    """Best-effort event emit (Tier-2 log-and-degrade)."""
    try:
        emit = getattr(runtime, "emit_event", None)
        if callable(emit):
            emit(event_type, payload)
    except Exception:
        logger.debug("AD-706a: emit_event failed for %s", event_type, exc_info=True)


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

    session = browser_tool.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")

    acquired = await browser_tool.acquire_viewer_slot()
    if not acquired:
        raise HTTPException(
            status_code=503,
            detail="viewer_cap_exhausted",
            headers={"Retry-After": "5"},
        )

    cfg = getattr(browser_tool, "_config", None)
    fps = int(getattr(cfg, "streaming_fps", 4) or 4)
    quality = int(getattr(cfg, "streaming_jpeg_quality", 60) or 60)
    frame_interval = 1.0 / max(1, fps)

    async def _generate() -> Any:
        _safe_emit(
            runtime,
            EventType.BROWSER_STREAM_OPENED,
            {"session_id": session_id, "fps": fps, "quality": quality},
        )
        close_reason = "client_disconnect"
        try:
            while True:
                page = getattr(session, "page", None)
                if page is None:
                    close_reason = "page_unavailable"
                    return
                try:
                    jpeg_bytes = await page.screenshot(type="jpeg", quality=quality)
                except Exception as exc:  # noqa: BLE001 - Tier-2 log-and-degrade
                    logger.warning(
                        "AD-706a: screenshot failed for session %s: %s; closing stream",
                        session_id,
                        exc,
                    )
                    close_reason = "screenshot_failed"
                    return
                yield (
                    _BOUNDARY
                    + b"\r\nContent-Type: image/jpeg\r\n\r\n"
                    + jpeg_bytes
                    + b"\r\n"
                )
                await asyncio.sleep(frame_interval)
        except asyncio.CancelledError:
            close_reason = "cancelled"
            raise
        finally:
            _safe_emit(
                runtime,
                EventType.BROWSER_STREAM_CLOSED,
                {"session_id": session_id, "reason": close_reason},
            )
            await browser_tool.release_viewer_slot()

    return StreamingResponse(
        _generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            # BF: long-lived MJPEG streams without no-store cause Chromium to
            # buffer the response body into its on-disk HTTP cache, which can
            # grow to tens of GB during multi-hour Captain-watch sessions and
            # exhaust the system drive. no-store keeps the stream memory-only.
            "Cache-Control": "no-store, no-transform",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
