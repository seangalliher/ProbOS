"""AD-706b: Browser recording admin endpoints (Captain only).

- ``GET /api/browser/recordings`` - list all session subdirs / webm files.
- ``GET /api/browser/recordings/{session_id}/{filename}`` - stream a file.
- ``DELETE /api/browser/recordings/{session_id}`` - wipe a session subdir.

All three behind ``require_crew_scope`` (AD-722b-1 + AD-706a query-param
fallback for GET surfaces).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/browser", tags=["browser-recordings"])


def _recording_root(runtime: Any) -> Path | None:
    cfg = getattr(runtime, "config", None)
    if cfg is None:
        return None
    tools_cfg = getattr(cfg, "browser_tool", None)
    if tools_cfg is None or not getattr(tools_cfg, "recording_enabled", False):
        return None
    return Path(getattr(tools_cfg, "recording_dir", "data/browser-sessions"))


def _safe_subdir(root: Path, session_id: str) -> Path:
    """Resolve a session-relative subdir; reject path traversal."""
    resolved = (root / session_id).resolve()
    if not str(resolved).startswith(str(root.resolve())):
        raise HTTPException(status_code=400, detail="invalid_session_id")
    return resolved


@router.get(
    "/recordings",
    dependencies=[Depends(require_crew_scope)],
)
async def list_recordings(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    root = _recording_root(runtime)
    if root is None or not root.exists():
        return {"recordings": []}
    out: list[dict[str, Any]] = []
    try:
        for subdir in root.iterdir():
            if not subdir.is_dir():
                continue
            for webm in subdir.glob("*.webm"):
                try:
                    stat = webm.stat()
                except OSError:
                    continue
                out.append({
                    "session_id": subdir.name,
                    "filename": webm.name,
                    "size_bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                })
    except OSError:
        logger.warning(
            "AD-706b: list_recordings scan failed for %s", root, exc_info=True
        )
    return {"recordings": out}


@router.get(
    "/recordings/{session_id}/{filename}",
    dependencies=[Depends(require_crew_scope)],
)
async def fetch_recording(
    session_id: str,
    filename: str,
    runtime: Any = Depends(get_runtime),
) -> FileResponse:
    root = _recording_root(runtime)
    if root is None:
        raise HTTPException(status_code=404, detail="recording_dir_unavailable")
    subdir = _safe_subdir(root, session_id)
    target = (subdir / filename).resolve()
    if not str(target).startswith(str(subdir)):
        raise HTTPException(status_code=400, detail="invalid_filename")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="recording_not_found")
    return FileResponse(target, media_type="video/webm")


@router.delete(
    "/recordings/{session_id}",
    dependencies=[Depends(require_crew_scope)],
)
async def delete_recording(
    session_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    root = _recording_root(runtime)
    if root is None:
        raise HTTPException(status_code=404, detail="recording_dir_unavailable")
    subdir = _safe_subdir(root, session_id)
    if not subdir.exists():
        raise HTTPException(status_code=404, detail="session_not_found")
    try:
        shutil.rmtree(subdir)
    except OSError as exc:
        logger.warning(
            "AD-706b: delete_recording rmtree failed for %s: %s", subdir, exc
        )
        raise HTTPException(status_code=500, detail="delete_failed") from exc
    return {"deleted": True, "session_id": session_id}
