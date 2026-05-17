"""AD-722b-1: minimal crew-scope auth dependency for telemetry surfaces.

v1 scope (Wave 161):
- Single shared secret (Pydantic ``AuthConfig.crew_scope_token``).
- HTTP: ``Authorization: Bearer <token>`` header via FastAPI ``Depends``.
- WebSocket: ``?token=<token>`` query param via ``verify_ws_token``.
- Empty configured token = auth disabled (default-OFF).
- Constant-time compare via ``hmac.compare_digest``.

Out of scope (forward markers AD-722b-1a / AD-722b-1b / AD-722b-1c / AD-722b-1d):
- Multi-Captain / per-crew tokens.
- Token rotation / TTL.
- Federation-bridge JWT verification (AD-480 territory).
"""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import Depends, Header, HTTPException, Request, WebSocket

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)


def _configured_token(runtime: Any) -> str:
    """Pull ``auth.crew_scope_token`` from runtime config; empty when unset."""
    cfg = getattr(runtime, "config", None)
    if cfg is None:
        return ""
    auth_cfg = getattr(cfg, "auth", None)
    if auth_cfg is None:
        return ""
    return auth_cfg.crew_scope_token


async def require_crew_scope(
    request: Request,
    authorization: str | None = Header(default=None),
    runtime: Any = Depends(get_runtime),
) -> None:
    """FastAPI dependency: enforce crew-scope token when configured.

    AD-722b-1: primary path is ``Authorization: Bearer <token>`` header.
    AD-706a: query-param fallback (``?token=...``) when the header is absent.
    The ``<img src>`` element cannot set HTTP headers, so MJPEG streaming
    needs the query-param surface. Header-only callers are unchanged.

    When ``auth.crew_scope_token`` is empty, this dependency is a pass-through -
    backward-compatible with single-operator HXI installs. When configured,
    missing / malformed / wrong tokens raise HTTP 401.
    """
    expected = _configured_token(runtime)
    if not expected:
        return  # auth disabled

    presented = ""
    if authorization and authorization.startswith("Bearer "):
        presented = authorization[len("Bearer "):].strip()
    else:
        # AD-706a: query-param fallback for static surfaces (<img>, <video>).
        # Empty string is treated as "no token presented" - NOT a pass.
        query_token = request.query_params.get("token", "") or ""
        presented = query_token.strip()
        if not presented:
            raise HTTPException(
                status_code=401, detail="missing_or_malformed_authorization"
            )

    if not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="invalid_token")


async def verify_ws_token(websocket: WebSocket, runtime: Any) -> bool:
    """Verify ``?token=`` query param on a WebSocket before ``accept()``.

    On failure, closes with code 1008 and returns False; caller must
    return immediately. On success (or auth-disabled), returns True
    without modifying the WebSocket state.
    """
    expected = _configured_token(runtime)
    if not expected:
        return True
    presented = websocket.query_params.get("token", "") or ""
    if not presented or not hmac.compare_digest(presented, expected):
        try:
            await websocket.close(code=1008, reason="unauthorized")
        except Exception:
            logger.debug(
                "AD-722b-1: ws close failed during unauthorized rejection",
                exc_info=True,
            )
        return False
    return True
