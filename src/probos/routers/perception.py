"""AD-733: Camera frame ingestion endpoint.

POST /api/perception/camera/frame accepts a multipart JPEG, validates +
stores it via the shared :func:`_validate_and_store_attachment` chain (AD-731:
SHA-256 keyed bytes in :class:`AttachmentStore`), and broadcasts a
``vision_observation`` :class:`IntentMessage` whose params carry ONLY the
SHA ref — never the bytes.

v1 has no LLM consumer for the intent (AD-733a forward marker). Per the
dynamic intent discovery design, an unconsumed intent is broadcast and
silently dropped; the audit trail still lands in the journal.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from probos.routers.auth import require_crew_scope
from probos.routers.chat import _validate_and_store_attachment
from probos.routers.deps import get_runtime
from probos.types import AnchorFrame, Episode, IntentMessage
from probos.perception import VISION_OBSERVATION_DESCRIPTOR  # noqa: F401  registers descriptor

router = APIRouter(prefix="/api/perception", tags=["perception"])
logger = logging.getLogger(__name__)

# Per-session token bucket. Module-scoped: one runtime per process.
_buckets: dict[str, tuple[float, float]] = {}

# One anchor episode per session per runtime boot. Cleared on process exit.
_ANCHOR_WRITTEN: set[str] = set()


def _reset_state_for_tests() -> None:
    """Test-only helper — clears module state so each test runs in isolation."""
    _buckets.clear()
    _ANCHOR_WRITTEN.clear()


def _check_rate(session_id: str, max_fps: int) -> bool:
    """Token-bucket admission: True when a frame slot is available."""
    now = time.monotonic()
    last, tokens = _buckets.get(session_id, (now, float(max_fps)))
    elapsed = now - last
    tokens = min(float(max_fps), tokens + elapsed * max_fps)
    if tokens < 1.0:
        _buckets[session_id] = (now, tokens)
        return False
    _buckets[session_id] = (now, tokens - 1.0)
    return True


async def _write_anchor_episode(
    runtime: Any, session_id: str, sha: str, captured_at: float
) -> None:
    """AD-541b: anchored episode marking camera-stream-began.

    Tier-2 honest-degrade: logs WARNING on any failure, never raises. The
    frame upload result is independent of episode storage.
    """
    if session_id in _ANCHOR_WRITTEN:
        return
    _ANCHOR_WRITTEN.add(session_id)
    episodic = getattr(runtime, "episodic_memory", None)
    if episodic is None:
        return
    try:
        episode = Episode(
            timestamp=captured_at,
            user_input="",
            outcomes=[{
                "intent": "vision_observation",
                "success": True,
                "session_id": session_id,
                "attachment_ref": sha,
            }],
            reflection=(
                f"Camera stream began (session={session_id[:8]}, sha={sha[:8]}). "
                "AD-733 v1 wire shape proven; no LLM consumer in v1."
            ),
            source="direct",
            importance=8,
            anchors=AnchorFrame(
                channel="perception",
                trigger_type="camera_stream_began",
                trigger_agent="captain",
            ),
        )
        await episodic.store(episode)
    except Exception as ex:
        logger.warning(
            "AD-733 anchor episode store failed (session=%s, sha=%s): %s; "
            "frame is still stored, no agent observation in v1.",
            session_id, sha[:8], ex,
        )


@router.post("/camera/frame", dependencies=[Depends(require_crew_scope)])
async def upload_camera_frame(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    force: str = Form(""),
    runtime: Any = Depends(get_runtime),
) -> Any:
    cfg = getattr(runtime.config, "perception", None)
    if cfg is None or not cfg.enabled:
        return JSONResponse(status_code=503, content={"error": "perception_disabled"})
    if not cfg.camera.enabled:
        return JSONResponse(status_code=503, content={"error": "camera_disabled"})

    if not _check_rate(session_id, cfg.camera_max_fps_server):
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited"},
            headers={"Retry-After": "1"},
        )

    blob = await file.read()
    if len(blob) > cfg.frame_max_size_bytes:
        return JSONResponse(status_code=413, content={"error": "frame_too_large"})
    if len(blob) < 12:
        return JSONResponse(status_code=400, content={"error": "frame_too_small"})

    ok, result = await _validate_and_store_attachment(
        runtime, blob, "image/jpeg",
        declared_filename=None, declared_hash_or_None=None,
    )
    if not ok:
        return JSONResponse(status_code=result["status_code"], content=result["body"])

    sha = result["attachment_id"]
    captured_at = time.time()
    is_forced = force.lower() in {"1", "true", "yes"}

    # AD-731 invariant: refs only — NEVER inline bytes in IntentMessage.params.
    # BF-302: ``force`` carries Captain's explicit "describe this frame even
    # if the supervisor would normally drop it" intent. Used by the operator
    # preview panel for testing the pipeline without waiting on novelty.
    msg = IntentMessage(
        intent="vision_observation",
        params={
            "attachment_ref": sha,
            "mime": "image/jpeg",
            "captured_at": captured_at,
            "source": "camera",
            "session_id": session_id,
            "force": is_forced,
        },
    )
    try:
        await runtime.intent_bus.broadcast(msg)
    except Exception as ex:
        logger.warning(
            "AD-733 intent_bus.broadcast failed (session=%s, sha=%s): %s; "
            "frame is still stored, no agent observation in v1.",
            session_id, sha[:8], ex,
        )

    await _write_anchor_episode(runtime, session_id, sha, captured_at)

    return {"ok": True, "attachment_ref": sha, "captured_at": captured_at}


@router.get("/recent", dependencies=[Depends(require_crew_scope)])
async def get_recent_observations(limit: int = 8) -> Any:
    """BF-303: return the most recent vision observations across all per-agent
    working memories, newest first. Operator-facing debug surface for the
    preview panel — lets the Captain see what the perception gateway last
    described.
    """
    from probos.perception.consumer import _WORKING_MEMORIES

    items: list[dict[str, Any]] = []
    for agent_id, wm in _WORKING_MEMORIES.items():
        for obs in wm.entries():
            items.append(
                {
                    "agent_id": agent_id,
                    "timestamp": obs.timestamp,
                    "attachment_ref": obs.attachment_ref,
                    "description": obs.description,
                    "novelty_score": obs.novelty_score,
                    "subject_identity": obs.subject_identity,
                    "session_id": obs.session_id,
                }
            )
    items.sort(key=lambda it: it["timestamp"], reverse=True)
    return {"observations": items[: max(1, min(limit, 32))]}
