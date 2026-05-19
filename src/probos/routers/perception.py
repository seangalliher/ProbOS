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

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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
        origin="perception_frame",
    )
    if not ok:
        return JSONResponse(
            status_code=result["status_code"],
            content=result["body"],
            headers=result.get("headers"),
        )

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
async def get_recent_observations(limit: int = 8, runtime: Any = Depends(get_runtime)) -> Any:
    """BF-303 / BF-306: return the most recent vision observations across all
    per-agent working memories, newest first, AND the most recent supervisor
    decisions (kept frames + dropped frames with reason + novelty score).
    Operator-facing debug surface for the preview panel.
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

    # BF-306: surface supervisor decisions so the operator can SEE why
    # frames are or aren't being described. Pulled from the runtime's
    # consumer instance — honest-degrade to empty list when absent.
    decisions: list[dict[str, Any]] = []
    consumer = getattr(runtime, "vision_consumer", None)
    if consumer is not None and hasattr(consumer, "recent_decisions"):
        try:
            decisions = consumer.recent_decisions(limit=max(1, min(limit, 32)))
        except Exception:
            decisions = []

    return {
        "observations": items[: max(1, min(limit, 32))],
        "recent_decisions": decisions,
    }


# AD-733c-2 (Wave 172) - Mode status + manual override.

@router.get("/mode", dependencies=[Depends(require_crew_scope)])
async def get_perception_mode(runtime: Any = Depends(get_runtime)) -> Any:
    """Return the current PerceptionMode, when it transitioned, the last DM
    activity, the three preset bundles, and the most recent transitions.
    """
    controller = getattr(runtime, "perception_mode_controller", None)
    if controller is None:
        return JSONResponse(
            status_code=503,
            content={"error": "perception_mode_controller_unavailable"},
        )
    from probos.perception.mode_controller import PRESETS

    presets = {
        m.value: {
            "min_interval_seconds": p.min_interval_seconds,
            "novelty_threshold": p.novelty_threshold,
            "baseline_max_age_seconds": p.baseline_max_age_seconds,
        }
        for m, p in PRESETS.items()
    }
    transitions = [
        {
            "at": t.at,
            "from_mode": t.from_mode.value,
            "to_mode": t.to_mode.value,
            "trigger": t.trigger,
        }
        for t in controller.recent_transitions(limit=3)
    ]
    # AD-733c-5: per-agent modes for HXI rendering. Defaults to an empty
    # dict when the registry is unwired (back-compat for legacy single-
    # controller deployments).
    per_agent: dict[str, str] = {}
    _engagement = getattr(runtime, "perception_engagement_registry", None)
    if _engagement is not None:
        try:
            per_agent = _engagement.current_modes()
        except Exception:
            logger.debug(
                "AD-733c-5: engagement registry current_modes raised",
                exc_info=True,
            )
    return {
        "mode": controller.current_mode.value,
        "since": controller.mode_since,
        "last_dm_activity": controller.last_dm_activity_at,
        "presets": presets,
        "transitions": transitions,
        "per_agent": per_agent,
    }


class _PerceptionModeRequest(BaseModel):
    mode: str


@router.post("/mode", dependencies=[Depends(require_crew_scope)])
async def post_perception_mode(
    body: _PerceptionModeRequest,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """Manual operator override. Trigger='manual' bypasses the programmatic cooldown."""
    controller = getattr(runtime, "perception_mode_controller", None)
    if controller is None:
        return JSONResponse(
            status_code=503,
            content={"error": "perception_mode_controller_unavailable"},
        )
    from probos.perception.mode_controller import Mode
    try:
        target = Mode(body.mode.strip().lower())
    except ValueError:
        return JSONResponse(
            status_code=400, content={"error": "invalid_mode", "value": body.mode},
        )
    changed = controller.transition_to(target, trigger="manual")
    return {"ok": True, "mode": controller.current_mode.value, "changed": changed}


# AD-733c-3 (Wave 172) - Wake-word engage.

class _PerceptionEngageRequest(BaseModel):
    agent: str | None = None        # callsign of the targeted agent (informational)
    phrase: str | None = None       # the matched phrase (informational, for logs)
    source: str = "wake_word"       # "wake_word" | "manual"


@router.post("/engage", dependencies=[Depends(require_crew_scope)])
async def post_perception_engage(
    body: _PerceptionEngageRequest,
    runtime: Any = Depends(get_runtime),
) -> Any:
    """AD-733c-3: flip the mode controller to ENGAGED on a wake-word event.

    Body fields are informational (logged); the controller only needs the
    side effect. 5s cooldown enforced at the controller level.

    AD-733c-5: when ``body.agent`` resolves to a registered per-agent
    controller (either by agent_id or by callsign), the engagement is
    scoped to that agent only. Otherwise falls back to the legacy
    singleton (runtime-wide engagement).
    """
    controller = getattr(runtime, "perception_mode_controller", None)
    if controller is None:
        return JSONResponse(
            status_code=503,
            content={"error": "perception_mode_controller_unavailable"},
        )
    if body.source not in ("wake_word", "manual"):
        return JSONResponse(
            status_code=400, content={"error": "invalid_source", "value": body.source},
        )

    # AD-733c-5: prefer per-agent routing.
    routed_agent: str | None = None
    _engagement = getattr(runtime, "perception_engagement_registry", None)
    if _engagement is not None and body.agent:
        # Try agent_id first.
        _per = _engagement.get(body.agent)
        if _per is None:
            # Try callsign → agent_id resolution.
            cs_reg = getattr(runtime, "callsign_registry", None)
            if cs_reg is not None:
                try:
                    resolved = cs_reg.resolve(body.agent)
                except Exception:
                    resolved = None
                if resolved is not None:
                    _aid = getattr(resolved, "id", None) or getattr(
                        resolved, "agent_id", None
                    )
                    if _aid is not None:
                        _per = _engagement.get(_aid)
                        if _per is not None:
                            routed_agent = _aid
        else:
            routed_agent = body.agent
        # When agent was specified but no per-agent controller resolved,
        # return 404 honest-degrade per AD-733c-5 contract.
        if _per is None:
            return JSONResponse(
                status_code=404,
                content={"error": "unknown_agent", "value": body.agent},
            )
        controller = _per

    transitioned, reason = controller.note_wake_word()
    logger.info(
        "AD-733c-3: engage agent=%s phrase=%s source=%s transitioned=%s reason=%s "
        "routed_agent=%s",
        (body.agent or "*")[:32], (body.phrase or "*")[:64], body.source,
        transitioned, reason, routed_agent or "*",
    )
    return {
        "ok": True,
        "mode": controller.current_mode.value,
        "transitioned": transitioned,
        "reason": reason,
        "agent_id": routed_agent,
    }


@router.post("/identity/enroll", dependencies=[Depends(require_crew_scope)])
async def enroll_identity(
    file: UploadFile = File(...),
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-742b: enroll the Captain's reference face.

    Accepts a multipart image upload (JPEG/PNG). Computes the 512-d
    embedding via facenet-pytorch, persists to ``data/captain_identity.json``,
    and discards the image bytes. The reference photo is NOT stored.
    """
    resolver = getattr(runtime, "identity_resolver", None)
    if resolver is None:
        raise HTTPException(
            status_code=503,
            detail="AD-742b: IdentityResolver not wired. Check that perception.identity_resolver_enabled is True and facenet-pytorch is installed.",
        )
    content = await file.read()
    if not content or len(content) > 10 * 1024 * 1024:  # 10 MB cap
        raise HTTPException(status_code=400, detail="empty or oversized image")
    try:
        # Offload sync inference from the event loop.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, resolver.enroll, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"enrolled": True, "model_id": "facenet-pytorch-vggface2-1.0"}


@router.delete("/identity", dependencies=[Depends(require_crew_scope)])
async def revoke_identity(
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-742b: delete the enrolled face embedding."""
    resolver = getattr(runtime, "identity_resolver", None)
    if resolver is None:
        return {"removed": False, "reason": "resolver not wired"}
    removed = resolver.revoke()
    return {"removed": removed}


@router.get("/identity", dependencies=[Depends(require_crew_scope)])
async def get_identity_status(
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-742b: report enrollment status (no embedding returned)."""
    resolver = getattr(runtime, "identity_resolver", None)
    if resolver is None:
        return {"enrolled": False, "resolver_wired": False}
    return {
        "enrolled": resolver.is_enrolled(),
        "resolver_wired": True,
        "model_id": "facenet-pytorch-vggface2-1.0",
    }


@router.get("/budget", dependencies=[Depends(require_crew_scope)])
async def get_vision_budget(
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-742e (Wave 174): vision LLM call budget telemetry.

    Returns per-tier (vision / vision_fast) call counts for the current
    session AND for today (UTC). Plus a next-allowed-in estimate based
    on the supervisor's min-interval floor.
    """
    consumer = getattr(runtime, "vision_consumer", None)
    if consumer is None:
        return {
            "session_id": "",
            "calls_this_session": {"vision": 0, "vision_fast": 0},
            "calls_today": {"vision": 0, "vision_fast": 0},
            "total_session": 0,
            "total_today": 0,
            "session_ceiling_estimate": 0,
            "next_allowed_in_seconds": 0.0,
            "consumer_wired": False,
        }
    snapshot = consumer.get_budget_snapshot()
    snapshot["consumer_wired"] = True
    return snapshot
