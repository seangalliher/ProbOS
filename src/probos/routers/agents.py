"""ProbOS API — Agent routes (AD-406, AD-430b, AD-431, AD-441, AD-497)."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from probos.api_models import (
    AgentChatRequest,
    ApproveVisionCapability,
    MediateAppearanceRevision,
    PreviewAppearanceRequest,
    ProposeAppearanceRequest,
    ProposeAppearanceResponse,
    ProposeVisionCapability,
    ProposeVoiceProfileRequest,
    ProposeVoiceProfileResponse,
    SetAppearanceRequest,
    SetCapability,
    SetCooldownRequest,
    SetVisionCapability,
    SetVoiceProfileRequest,
    VisionCapabilityProposalResponse,
)
from probos.config import format_trust
from probos.crew_utils import is_crew_agent
from probos.cognitive.commands.personality_command import (
    handle_personality_command,
    is_personality_command,
)
from probos.routers.deps import get_runtime
from probos.routers.auth import require_crew_scope, verify_ws_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agents"])


@router.get("/{agent_id}/identity")
async def get_agent_identity(agent_id: str, runtime: Any = Depends(get_runtime)) -> Any:
    """Return the agent's birth certificate and DID."""
    if not runtime.identity_registry:
        return JSONResponse({"error": "Identity registry not available"}, status_code=503)

    cert = runtime.identity_registry.get_by_slot(agent_id)
    if not cert:
        return JSONResponse({"error": "No birth certificate found"}, status_code=404)

    return {
        "sovereign_id": cert.agent_uuid,
        "did": cert.did,
        "birth_certificate": cert.to_verifiable_credential(),
    }


@router.get("/{agent_id}/profile")
async def agent_profile(agent_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Get detailed profile for a specific agent."""
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Basic info
    callsign = ""
    department = ""
    rank = "ensign"
    display_name = ""
    personality: dict[str, float] = {}
    specialization: list[str] = []

    # Crew profile from YAML seed data
    if hasattr(runtime, 'callsign_registry'):
        callsign = runtime.callsign_registry.get_callsign(agent.agent_type)
        resolved = runtime.callsign_registry.resolve(callsign) if callsign else None
        if resolved:
            department = resolved.get("department", "")
            display_name = resolved.get("display_name", "")

    # Load full seed profile for personality
    from probos.crew_profile import load_seed_profile_async, Rank
    seed = await load_seed_profile_async(agent.agent_type)
    if seed:
        personality = seed.get("personality", {})
        specialization = seed.get("specialization", [])
        display_name = display_name or seed.get("display_name", "")
        department = department or seed.get("department", "")

    # Trust
    from probos.config import TRUST_DEFAULT
    trust_score = TRUST_DEFAULT
    trust_history: list[float] = []
    agency_level = "ensign"
    if hasattr(runtime, 'trust_network'):
        trust_score = runtime.trust_network.get_score(agent.id)
        rank = Rank.from_trust(trust_score).value
        from probos.earned_agency import agency_from_rank
        agency_level = agency_from_rank(Rank.from_trust(trust_score)).value
        if hasattr(runtime.trust_network, 'get_history'):
            trust_history = runtime.trust_network.get_history(agent.id, limit=20)

    # Hebbian connections
    hebbian_connections: list[dict[str, Any]] = []
    if hasattr(runtime, 'hebbian_router'):
        for (source, target, rel_type), weight in runtime.hebbian_router.all_weights_typed().items():
            if source == agent.id or target == agent.id:
                other_id = target if source == agent.id else source
                hebbian_connections.append({
                    "targetId": other_id,
                    "weight": format_trust(weight),
                    "relType": rel_type,
                })
        hebbian_connections.sort(key=lambda c: c["weight"], reverse=True)
        hebbian_connections = hebbian_connections[:10]

    # Memory count
    memory_count = 0
    if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
        if hasattr(runtime.episodic_memory, 'count_for_agent'):
            memory_count = await runtime.episodic_memory.count_for_agent(
                getattr(agent, 'sovereign_id', '') or agent.id
            )

    # BF-017: Only crew agents get personality and proactive controls
    is_crew = is_crew_agent(agent, runtime.ontology)

    # AD-718: per-agent voice profile (live ProfileStore takes precedence over seed defaults).
    from probos.voice_profile_defaults import default_voice_for
    voice_profile_dict: dict[str, Any]
    live_profile = None
    if hasattr(runtime, 'profile_store') and runtime.profile_store is not None:
        live_profile = runtime.profile_store.get(agent.id)
    if live_profile is not None:
        voice_profile_dict = live_profile.voice.to_dict()
    elif seed and isinstance(seed.get("voice"), dict):
        voice_profile_dict = seed["voice"]
    else:
        voice_profile_dict = default_voice_for(agent.agent_type).to_dict()

    # AD-721 per-agent appearance profile (live ProfileStore → seed → empty default).
    # AD-721d BF (2026-05-10): live ProfileStore wins, but missing fields fall
    # through to seed so DSL approval doesn't drop the seed vrm_url. Without
    # this, post-approval avatars regress to ParametricAvatar (solid amber).
    appearance_dict: dict[str, Any]
    if live_profile is not None:
        appearance_dict = live_profile.appearance.to_dict()
        if seed and isinstance(seed.get("appearance"), dict):
            seed_app = seed["appearance"]
            if not appearance_dict.get("vrm_url") and seed_app.get("vrm_url"):
                appearance_dict["vrm_url"] = seed_app["vrm_url"]
            if not appearance_dict.get("color_palette_hint") and seed_app.get("color_palette_hint"):
                appearance_dict["color_palette_hint"] = seed_app["color_palette_hint"]
    elif seed and isinstance(seed.get("appearance"), dict):
        appearance_dict = seed["appearance"]
    else:
        appearance_dict = {
            "vrm_url": "",
            "expression_overrides": {},
            "color_palette_hint": "",
        }

    # AD-721d D8: synthesise vrm_url from rendered cache when DSL is set but
    # vrm_url is empty. Pure read-path synthesis — no file write here.
    try:
        if (
            not appearance_dict.get("vrm_url")
            and isinstance(appearance_dict.get("dsl"), dict)
            and getattr(runtime, "config", None) is not None
            and getattr(runtime.config, "avatars", None) is not None
        ):
            from pathlib import Path as _Path
            from probos.routers.system import _resolve_avatars_dir
            avatars_dir = _resolve_avatars_dir(runtime.config.avatars.avatars_dir)
            cached = avatars_dir / f"{agent.id}.vrm"
            if cached.exists() and cached.is_file():
                appearance_dict["vrm_url"] = f"{agent.id}.vrm"
    except Exception:  # defense-in-depth: cache synthesis must never break the read path
        logger.warning(
            "AD-721d: avatar cache synthesis failed for %s; "
            "falling back to parametric (vrm_url left empty)",
            agent.id,
            exc_info=True,
        )

    # AD-721g: per-rank baseline VRM fallback (between cache synthesis and parametric).
    # Only fires when no vrm_url is set by the seed profile, no DSL cache exists,
    # and the operator has configured a non-empty filename for this rank under
    # ``<avatars_dir>/_baselines/``. License-clean: no bytes ship in the repo.
    try:
        if (
            not appearance_dict.get("vrm_url")
            and getattr(runtime, "config", None) is not None
            and getattr(runtime.config, "avatars", None) is not None
        ):
            from probos.avatars.baseline_resolver import (
                _BASELINES_SUBDIR,
                resolve_baseline_vrm_path,
            )
            from probos.routers.system import _resolve_avatars_dir

            avatars_cfg = runtime.config.avatars
            avatars_dir = _resolve_avatars_dir(avatars_cfg.avatars_dir)
            rank_obj = Rank.from_trust(trust_score)
            baseline_path = resolve_baseline_vrm_path(
                rank_obj, avatars_cfg.baseline_vrms, avatars_dir
            )
            if baseline_path is not None:
                appearance_dict["vrm_url"] = f"{_BASELINES_SUBDIR}/{baseline_path.name}"
    except Exception:
        logger.debug(
            "AD-721g: baseline VRM resolution failed for %s; "
            "falling back to parametric",
            agent.id, exc_info=True,
        )

    profile_data = {
        "id": agent.id,
        "sovereignId": getattr(agent, 'sovereign_id', ''),
        "did": getattr(agent, 'did', ''),
        "agentType": agent.agent_type,
        "callsign": callsign,
        "displayName": display_name,
        "rank": rank,
        "agencyLevel": agency_level,
        "department": department,
        "personality": personality if is_crew else {},
        "specialization": specialization,
        "trust": format_trust(trust_score),
        "trustHistory": trust_history,
        "confidence": format_trust(agent.confidence),
        "state": agent.state.value if hasattr(agent.state, 'value') else str(agent.state),
        "tier": agent.tier if hasattr(agent, 'tier') else "domain",
        "pool": agent.pool,
        "hebbianConnections": hebbian_connections,
        "memoryCount": memory_count,
        "voiceProfile": voice_profile_dict,
        "appearance": appearance_dict,
        "uptime": round(time.monotonic() - runtime._start_time, 1),
        "isCrew": is_crew,
        "proactiveCooldown": runtime.proactive_loop.get_agent_cooldown(agent.id) if is_crew and hasattr(runtime, 'proactive_loop') and runtime.proactive_loop else None,
    }

    # AD-982a: surface the LIVE vision-capability gate (registry profile, which
    # reflects boot-applied persistent overrides) so the profile-card toggle can
    # render current state. Read from the live registry, not the seed YAML.
    vision_capable = False
    try:
        if hasattr(runtime, "callsign_registry"):
            _vprof = runtime.callsign_registry._type_to_profile.get(agent.agent_type, {})
            vision_capable = bool(_vprof.get("vision_capable", False))
    except Exception:
        logger.debug("AD-982a: vision_capable lookup failed for %s", agent.id, exc_info=True)
    profile_data["visionCapable"] = vision_capable

    # AD-497: Include workforce data
    if runtime.work_item_store:
        agent_uuid = getattr(agent, 'uuid', agent.id)
        active_items = await runtime.work_item_store.list_work_items(
            assigned_to=agent_uuid, status=None, limit=50,
        )
        profile_data["work_items"] = [wi.to_dict() for wi in active_items]
        bookings = await runtime.work_item_store.list_bookings(
            resource_id=agent_uuid, limit=20,
        )
        profile_data["bookings"] = [b.to_dict() for b in bookings]

    return profile_data


@router.put("/{agent_id}/proactive-cooldown")
async def set_agent_proactive_cooldown(agent_id: str, req: SetCooldownRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Set per-agent proactive cooldown (seconds). Range: 60-1800."""
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    if not is_crew_agent(agent, runtime.ontology):
        raise HTTPException(status_code=400, detail=f"Agent {agent_id} is not a crew agent")
    cooldown = req.cooldown
    if cooldown < 60 or cooldown > 1800:
        raise HTTPException(status_code=400, detail=f"Cooldown must be between 60 and 1800 seconds, got {cooldown}")
    if hasattr(runtime, 'proactive_loop') and runtime.proactive_loop:
        runtime.proactive_loop.set_agent_cooldown(agent_id, cooldown)
    return {"agentId": agent_id, "cooldown": runtime.proactive_loop.get_agent_cooldown(agent_id) if runtime.proactive_loop else 300.0}


@router.put("/{agent_id}/voice-profile")
async def set_agent_voice_profile(
    agent_id: str,
    req: SetVoiceProfileRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-718: Update per-agent voice profile (browser SpeechSynthesis).

    AD-718a: when ``proposal_rationale`` is non-empty, write an episode
    capturing the approve-from-proposal event (the rationale IS the
    learning signal). Hand-edits with empty rationale follow the existing
    path unchanged.
    """
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    from probos.crew_profile import VoiceProfile
    try:
        new_profile = VoiceProfile(
            voice_name=req.voice_name,
            pitch=req.pitch,
            rate=req.rate,
            volume=req.volume,
            wake_phrase=req.wake_phrase,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    old_voice_dict: dict[str, Any] = {}
    if hasattr(runtime, "profile_store") and runtime.profile_store is not None:
        crew = runtime.profile_store.get_or_create(
            agent.id, agent_type=agent.agent_type, pool=agent.pool,
        )
        try:
            old_voice_dict = crew.voice.to_dict()
        except Exception:  # pragma: no cover — defensive
            old_voice_dict = {}
        crew.voice = new_profile
        runtime.profile_store.update(crew)
    else:
        logger.warning(
            "AD-718: profile_store not present on runtime; voice profile for %s not persisted",
            agent_id,
        )

    # AD-718a: episode write on approve-from-proposal path only.
    if (
        req.proposal_rationale
        and hasattr(runtime, "episodic_memory")
        and runtime.episodic_memory is not None
    ):
        try:
            import time as _time
            from probos.cognitive.episodic import resolve_sovereign_id
            from probos.types import AnchorFrame, Episode
            sovereign_id = resolve_sovereign_id(agent)
            new_voice_dict = new_profile.to_dict()
            episode = Episode(
                user_input=(
                    f"[voice approval] Captain approved voice proposal for "
                    f"{agent_id}: {req.proposal_rationale[:200]}"
                ),
                timestamp=_time.time(),
                agent_ids=[sovereign_id],
                outcomes=[{
                    "intent": "voice_profile_change",
                    "success": True,
                    "old_voice": old_voice_dict,
                    "new_voice": new_voice_dict,
                    "rationale": req.proposal_rationale,
                    "agent_id": agent_id,
                }],
                reflection=(
                    f"Captain approved an agent-authored voice proposal for "
                    f"{agent_id}; rationale recorded for learning."
                ),
                source="direct",
                anchors=AnchorFrame(
                    channel="hxi_profile",
                    trigger_type="voice_profile_change",
                    trigger_agent="captain",
                    participants=["captain", agent_id],
                ),
            )
            await runtime.episodic_memory.store(episode)
        except Exception:
            logger.debug(
                "AD-718a: failed to store voice-approval episode for %s",
                agent_id, exc_info=True,
            )

    return {"agentId": agent_id, "voiceProfile": new_profile.to_dict()}


@router.post("/{agent_id}/voice-profile/propose", response_model=ProposeVoiceProfileResponse)
async def propose_agent_voice_profile(
    agent_id: str,
    req: ProposeVoiceProfileRequest | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-718a: trigger ``CognitiveAgent.propose_voice_profile`` and return
    the candidate ``VoiceProfile`` for Captain review. NOT persisted —
    caller must follow up with ``PUT /{agent_id}/voice-profile`` (carrying
    ``proposal_rationale``) once the Captain approves.
    """
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    if not hasattr(agent, "propose_voice_profile"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Agent {agent_id} does not support voice proposal "
                "(not a CognitiveAgent subclass)"
            ),
        )

    from probos.voice.proposal import VoiceProposalError

    captain_note = (req.captain_note if req else "") or ""
    try:
        profile, rationale = await agent.propose_voice_profile(captain_note=captain_note)
    except VoiceProposalError as exc:
        logger.warning(
            "AD-718a: voice proposal rejected for %s: reason=%s detail=%s; "
            "no profile persisted, Captain may retry",
            agent_id, exc.reason, exc.detail,
        )
        raise HTTPException(
            status_code=422,
            detail={"reason": exc.reason, "detail": exc.detail},
        )
    return {
        "agent_id": agent_id,
        "voice_profile": profile.to_dict(),
        "rationale": rationale,
    }


# ── AD-721d: agent-authored appearance pipeline ─────────────────────────


def _avatars_feature_check(runtime: Any) -> None:
    """Raise HTTP 503 if avatars are disabled in config."""
    cfg = getattr(runtime, "config", None)
    enabled = bool(cfg and getattr(cfg, "avatars", None) and cfg.avatars.enabled)
    if not enabled:
        raise HTTPException(
            status_code=503,
            detail="avatars feature disabled in config (cfg.avatars.enabled=False)",
        )


@router.post("/{agent_id}/appearance/propose", response_model=ProposeAppearanceResponse)
async def propose_agent_appearance(
    agent_id: str,
    req: ProposeAppearanceRequest | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-721d D7 + AD-721d-1: trigger ``CognitiveAgent.propose_appearance``
    and return the proposed DSL for Captain review. NOT persisted — caller
    must follow up with ``PUT /{agent_id}/appearance`` once the Captain
    approves.

    AD-721d-1: supports up to ``cfg.avatars.max_proposal_iterations``
    revisions per agent. Iteration count is server-side in-memory
    (cleared on approve / DELETE /appearance/proposal-history). At the
    cap the endpoint returns HTTP 429 with structured detail.
    """
    _avatars_feature_check(runtime)
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    if not hasattr(agent, "propose_appearance"):
        raise HTTPException(
            status_code=400,
            detail=f"Agent {agent_id} does not support appearance proposal "
                   "(not a CognitiveAgent subclass)",
        )

    from probos.avatars.dsl import AppearanceProposalError, AvatarDSL
    from probos.avatars import proposal_history

    captain_note = (req.captain_note if req else "") or ""
    previous_dsl_raw = (req.previous_dsl if req else None)

    # AD-721d-1: validate previous_dsl shape BEFORE incrementing the counter.
    # Malformed previous_dsl must NOT consume an iteration slot.
    if previous_dsl_raw is not None:
        try:
            AvatarDSL.model_validate(previous_dsl_raw)
        except Exception as exc:
            raise HTTPException(
                status_code=422,
                detail={"reason": "invalid_previous_dsl", "detail": str(exc)},
            )

    # AD-721d-1: iteration cap. Reading BEFORE the LLM call ensures we don't
    # spend a $LLM_call when we're going to 429 anyway.
    cfg_max = int(getattr(runtime.config.avatars, "max_proposal_iterations", 3))
    current_iterations = proposal_history.iteration_count(agent_id)
    if current_iterations + 1 > cfg_max:
        raise HTTPException(
            status_code=429,
            detail={
                "reason": "iteration_cap_reached",
                "detail": (
                    f"Maximum {cfg_max} proposal iterations reached for "
                    f"{agent_id}. Approve, reject, or DELETE the proposal "
                    "history to start a new session."
                ),
                "iteration": current_iterations,
                "max_iterations": cfg_max,
            },
        )

    try:
        dsl = await agent.propose_appearance(captain_note=captain_note)
    except AppearanceProposalError as exc:
        logger.warning(
            "AD-721d: appearance proposal rejected for %s: reason=%s detail=%s; "
            "no DSL persisted, Captain may retry",
            agent_id, exc.reason, exc.detail,
        )
        raise HTTPException(
            status_code=422,
            detail={"reason": exc.reason, "detail": exc.detail},
        )

    dsl_dict = dsl.model_dump()
    new_iteration = proposal_history.append(agent_id, dsl_dict, captain_note)

    # AD-721d-1: audit event — string-keyed, not a new EventType enum value.
    try:
        runtime.emit_event(
            "appearance_proposal",
            {
                "agent_id": agent_id,
                "iteration": new_iteration,
                "has_captain_note": bool(captain_note),
                "captain_note_len": len(captain_note),
            },
        )
    except Exception:
        # Tier-2 log-and-degrade: audit failure must not block the Captain.
        logger.warning(
            "AD-721d-1: emit_event('appearance_proposal') failed for %s; "
            "proposal returned to Captain but audit lost",
            agent_id, exc_info=True,
        )

    return {
        "agent_id": agent_id,
        "dsl": dsl_dict,
        "proposal_iteration": new_iteration,
        "max_iterations": cfg_max,
    }


@router.post("/{agent_id}/appearance/preview")
async def preview_agent_appearance(
    agent_id: str,
    req: PreviewAppearanceRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-721d-3: render an unpersisted AvatarDSL to a draft VRM and return
    a SHA-256 AttachmentStore ref for client-side three.js rendering.

    Does NOT persist. Does NOT consume an iteration slot. Does NOT touch
    the canonical ``<avatars_dir>/<agent_id>.vrm`` cache. Honest-degrades
    to 503 when ``renderer_enabled=False`` or Blender is unavailable; the
    HXI keeps the parametric capsule fallback.

    AD-731 invariant: rendered VRM bytes ride ``AttachmentStore.write(sha,
    blob, mime)``, never inlined in the HTTP response body.
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
        raise HTTPException(
            status_code=422,
            detail={"reason": "schema_violation", "detail": str(exc)},
        )

    from probos.avatars.blender_renderer import (
        BlenderNotFoundError,
        BlenderRenderError,
        BlenderRenderer,
    )
    from probos.routers.system import _resolve_avatars_dir
    avatars_dir = _resolve_avatars_dir(avatars_cfg.avatars_dir)
    drafts_dir = _resolve_avatars_dir(avatars_cfg.dsl_drafts_dir)

    renderer = BlenderRenderer(
        blender_path=avatars_cfg.blender_path or None,
        timeout_s=int(avatars_cfg.blender_render_timeout_s),
        drafts_dir=drafts_dir,
        max_vrm_size_bytes=int(avatars_cfg.max_vrm_size_bytes),
        avatars_dir=avatars_dir,
        procedural_fallback=bool(avatars_cfg.procedural_base_mesh_fallback),
    )

    try:
        vrm_path = await renderer.render(dsl, agent_id)
    except BlenderNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail={"reason": "blender_not_found", "detail": str(exc)},
        )
    except BlenderRenderError as exc:
        raise HTTPException(
            status_code=502,
            detail={"reason": "render_failed", "detail": str(exc)},
        )

    # AD-731 invariant: bytes through AttachmentStore SHA-256 refs.
    import hashlib
    blob = vrm_path.read_bytes()
    max_bytes = int(avatars_cfg.max_vrm_size_bytes)
    if len(blob) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={"reason": "preview_too_large", "detail": f"{len(blob)} > {max_bytes}"},
        )
    sha = hashlib.sha256(blob).hexdigest()
    from probos.routers.chat import _get_attachment_store
    store = _get_attachment_store(runtime)
    await store.write(sha, blob, "model/gltf-binary")

    try:
        runtime.emit_event(
            "appearance_preview_rendered",
            {"agent_id": agent_id, "attachment_id": sha, "bytes": len(blob)},
        )
    except Exception:
        logger.warning(
            "AD-721d-3: emit_event('appearance_preview_rendered') failed for %s; "
            "preview ref returned but audit lost",
            agent_id, exc_info=True,
        )

    return {"agent_id": agent_id, "attachment_id": sha, "size_bytes": len(blob)}


@router.put("/{agent_id}/appearance")
async def set_agent_appearance(
    agent_id: str,
    req: SetAppearanceRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-721d D7: persist an approved AvatarDSL on ``AppearanceProfile.dsl``.

    Re-validates the DSL with Pydantic BEFORE writing. Round-trips through the
    existing ``ProfileStore`` JSON-blob column — no new SQLite table.
    """
    _avatars_feature_check(runtime)
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    from probos.avatars.dsl import AvatarDSL

    try:
        dsl = AvatarDSL.model_validate(req.dsl)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail={"reason": "schema_violation", "detail": str(exc)},
        )

    if hasattr(runtime, "profile_store") and runtime.profile_store is not None:
        crew = runtime.profile_store.get_or_create(
            agent.id, agent_type=agent.agent_type, pool=agent.pool,
        )
        # AD-721d BF (2026-05-10): when the live profile is freshly created
        # by get_or_create(), AppearanceProfile defaults to empty vrm_url
        # which causes the read path to fall back to ParametricAvatar (a
        # solid amber capsule) for any crew that previously rendered fine
        # from a seed-YAML vrm_url (e.g. Ezri.vrm). Hydrate vrm_url and
        # color_palette_hint from the seed if the live profile doesn't
        # already have them set, so DSL approval doesn't regress the avatar.
        if not crew.appearance.vrm_url or not crew.appearance.color_palette_hint:
            try:
                from probos.crew_profile import load_seed_profile_async
                seed = await load_seed_profile_async(agent.agent_type) or {}
                seed_app = seed.get("appearance") if isinstance(seed.get("appearance"), dict) else None
                if seed_app:
                    if not crew.appearance.vrm_url and seed_app.get("vrm_url"):
                        crew.appearance.vrm_url = seed_app["vrm_url"]
                    if not crew.appearance.color_palette_hint and seed_app.get("color_palette_hint"):
                        crew.appearance.color_palette_hint = seed_app["color_palette_hint"]
            except Exception:
                logger.debug(
                    "AD-721d: seed-profile hydration failed for %s; "
                    "DSL approval proceeding without seed-vrm fallback",
                    agent_id,
                    exc_info=True,
                )
        crew.appearance.dsl = dsl.model_dump()
        runtime.profile_store.update(crew)
    else:
        logger.warning(
            "AD-721d: profile_store not present on runtime; "
            "appearance DSL for %s not persisted (Captain approval lost)",
            agent_id,
        )

    # AD-721d-1: clear proposal history + emit audit event on approve.
    from probos.avatars import proposal_history
    iterations_used = proposal_history.clear(agent_id)
    try:
        runtime.emit_event(
            "appearance_approved",
            {"agent_id": agent_id, "iterations_used": iterations_used},
        )
    except Exception:
        logger.warning(
            "AD-721d-1: emit_event('appearance_approved') failed for %s; "
            "approval persisted but audit lost",
            agent_id, exc_info=True,
        )

    return {"agentId": agent_id, "dsl": dsl.model_dump()}


@router.post("/{agent_id}/appearance/vrm")
async def upload_agent_vrm(
    agent_id: str,
    file: UploadFile = File(...),
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-721h: Captain-driven VRM upload for an existing agent.

    Multipart. Bytes are stored content-addressably via ``AttachmentStore``
    (AD-731 invariant) AND copied to the named avatar cache
    ``<avatars_dir>/<agent_id>.vrm`` so the existing
    ``/system/avatars/{filename}`` serve route can dispatch. The
    ``ProfileStore`` ``vrm_url`` field is updated so the read path picks
    it up on the next request.

    Defense-in-depth: glTF binary magic bytes verified before storage;
    size cap mirrors ``cfg.avatars.max_vrm_size_bytes``; path-traversal
    guard via ``Path.resolve().relative_to(avatars_dir.resolve())``.
    """
    _avatars_feature_check(runtime)
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    avatars_cfg = runtime.config.avatars
    max_bytes = int(avatars_cfg.max_vrm_size_bytes)
    blob = await file.read()
    if len(blob) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail={"reason": "too_large", "size": len(blob), "max": max_bytes},
        )
    if len(blob) < 12:
        raise HTTPException(status_code=400, detail={"reason": "too_small"})

    # glTF binary magic = b"glTF" at offset 0 (VRM 1.0 = glTF binary container).
    # Defense-in-depth security check: reject anything that isn't a glTF binary
    # before we store the bytes anywhere.
    if blob[:4] != b"glTF":
        raise HTTPException(
            status_code=415,
            detail={"reason": "not_a_vrm", "detail": "missing glTF magic bytes"},
        )

    # AD-731: content-addressed write first.
    import hashlib
    sha = hashlib.sha256(blob).hexdigest()
    from probos.routers.chat import _get_attachment_store
    store = _get_attachment_store(runtime)
    await store.write(sha, blob, "model/gltf-binary")

    # Atomic named copy → <avatars_dir>/<agent_id>.vrm.
    from probos.routers.system import _resolve_avatars_dir
    avatars_dir = _resolve_avatars_dir(avatars_cfg.avatars_dir)
    avatars_dir.mkdir(parents=True, exist_ok=True)
    target = avatars_dir / f"{agent_id}.vrm"
    try:
        target.resolve().relative_to(avatars_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid agent_id")
    import os
    tmp = target.with_suffix(".vrm.tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, target)

    # Persist vrm_url so the read path resolves it without a re-render.
    if hasattr(runtime, "profile_store") and runtime.profile_store is not None:
        crew = runtime.profile_store.get_or_create(
            agent.id, agent_type=agent.agent_type, pool=agent.pool,
        )
        crew.appearance.vrm_url = f"{agent_id}.vrm"
        runtime.profile_store.update(crew)

    try:
        runtime.emit_event(
            "appearance_vrm_uploaded",
            {"agent_id": agent_id, "attachment_id": sha, "bytes": len(blob)},
        )
    except Exception:
        logger.warning(
            "AD-721h: emit_event('appearance_vrm_uploaded') failed for %s; "
            "upload persisted but audit lost",
            agent_id, exc_info=True,
        )

    return {
        "agent_id": agent_id,
        "attachment_id": sha,
        "vrm_url": f"{agent_id}.vrm",
        "bytes": len(blob),
    }


@router.delete("/{agent_id}/appearance/proposal-history")
async def clear_agent_appearance_proposal_history(
    agent_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-721d-1: explicitly drop the in-memory proposal-history for
    ``agent_id``. Used when the Captain rejects a proposal mid-session, or
    when an operator wants to reset the iteration counter without
    approving anything.

    Idempotent: returns ``{"agent_id": ..., "cleared_iterations": N}``
    where N is the prior iteration count (0 if no history existed).
    """
    _avatars_feature_check(runtime)
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    from probos.avatars import proposal_history
    cleared = proposal_history.clear(agent_id)
    try:
        runtime.emit_event(
            "appearance_history_cleared",
            {"agent_id": agent_id, "reason": "delete"},
        )
    except Exception:
        logger.warning(
            "AD-721d-1: emit_event('appearance_history_cleared') failed for %s",
            agent_id, exc_info=True,
        )
    return {"agent_id": agent_id, "cleared_iterations": cleared}


# ── AD-720d-2.1: Captain vision-capability approval ──────────────

@router.post(
    "/{agent_id}/vision-capability/propose",
    response_model=VisionCapabilityProposalResponse,
)
async def propose_vision_capability(
    agent_id: str,
    req: ProposeVisionCapability,
    runtime: Any = Depends(get_runtime),
) -> VisionCapabilityProposalResponse:
    """AD-720d-2.1: agent requests vision capability.

    Captain reviews and approves/denies via the companion endpoint. The
    proposal is recorded in the AD-720d-2.1 history sidecar (in-memory
    + on-disk JSON).
    """
    import time as _time
    import uuid as _uuid
    from probos.avatars import vision_proposal_history as _vph
    from probos.avatars.vision_proposal_history import VisionProposalEntry
    from probos.events import EventType

    if runtime.registry.get(agent_id) is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    entry = VisionProposalEntry(
        proposal_id=str(_uuid.uuid4()),
        agent_id=agent_id,
        rationale=req.rationale,
        proposed_at=_time.time(),
    )
    _vph.append(entry)

    try:
        runtime.emit_event(
            EventType.VISION_CAPABILITY_PROPOSED,
            {
                "agent_id": agent_id,
                "proposal_id": entry.proposal_id,
                "rationale": req.rationale,
            },
        )
    except Exception:
        logger.warning(
            "AD-720d-2.1: emit_event(VISION_CAPABILITY_PROPOSED) failed for %s; "
            "proposal recorded but audit lost",
            agent_id, exc_info=True,
        )

    return VisionCapabilityProposalResponse(
        agent_id=agent_id,
        rationale=req.rationale,
        proposal_id=entry.proposal_id,
        proposed_at=entry.proposed_at,
    )


@router.post("/{agent_id}/vision-capability/approve")
async def approve_vision_capability(
    agent_id: str,
    proposal_id: str,
    req: ApproveVisionCapability,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-720d-2.1: Captain approves or denies a pending vision-capability
    proposal. On approve, the agent's registry profile flips
    ``vision_capable=True``; on deny, the registry is unchanged. Either
    way, the proposal is marked resolved and persisted.
    """
    from probos.avatars import vision_proposal_history as _vph
    from probos.events import EventType

    resolution = "approved" if req.approve else "denied"
    resolved = _vph.resolve(proposal_id, resolution, req.reason)
    if resolved is None:
        raise HTTPException(
            status_code=404,
            detail="proposal_id not found or already resolved",
        )
    if resolved.agent_id != agent_id:
        raise HTTPException(
            status_code=400,
            detail="proposal_id agent mismatch",
        )

    if req.approve:
        ok = runtime.callsign_registry.set_vision_capable(
            agent_id, True, reason=req.reason,
        )
        if not ok:
            raise HTTPException(
                status_code=404,
                detail=f"Agent {agent_id} not found in registry",
            )

    try:
        runtime.emit_event(
            EventType.VISION_CAPABILITY_RESOLVED,
            {
                "agent_id": agent_id,
                "proposal_id": proposal_id,
                "approved": req.approve,
                "reason": req.reason,
            },
        )
    except Exception:
        logger.warning(
            "AD-720d-2.1: emit_event(VISION_CAPABILITY_RESOLVED) failed for %s",
            agent_id, exc_info=True,
        )

    return {"ok": True, "resolution": resolution, "approved": req.approve}


@router.get("/{agent_id}/vision-capability/history")
async def vision_capability_history(
    agent_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-720d-2.1: list prior vision-capability proposals for ``agent_id``.

    Mirrors AD-721d-1 ``appearance/proposal-history`` shape. Returns
    entries in chronological order with resolution metadata.
    """
    from dataclasses import asdict
    from probos.avatars import vision_proposal_history as _vph

    entries = _vph.list_for_agent(agent_id)
    return {
        "agent_id": agent_id,
        "entries": [asdict(e) for e in entries],
    }


@router.post("/{agent_id}/vision-capability/set")
async def set_vision_capability(
    agent_id: str,
    req: SetVisionCapability,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-982a: Captain directly grants or revokes an agent's vision capability.

    Flips the live registry AND records a persistent data-dir override (keyed by
    agent_type, matching the gate) so the grant survives restart without
    mutating the tracked crew-profile YAML. Distinct from the agent-initiated
    propose/approve flow (AD-720d-2.1), which remains for agent-requested grants.
    Audit-logged via VISION_CAPABILITY_RESOLVED.
    """
    from probos.events import EventType
    from probos.perception import vision_overrides as _vov

    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    agent_type = getattr(agent, "agent_type", "") or ""

    # 1) live flip (in-memory registry gate).
    ok = runtime.callsign_registry.set_vision_capable(
        agent_id, req.enabled, reason=req.reason or "captain_set",
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Agent {agent_id} not found in registry",
        )
    # 2) persist the override (survives restart; re-applied at boot).
    _vov.set_override(agent_type, req.enabled)

    try:
        runtime.emit_event(
            EventType.VISION_CAPABILITY_RESOLVED,
            {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "resolution": "captain_granted" if req.enabled else "captain_revoked",
                "reason": req.reason,
                "source": "captain_set",
            },
        )
    except Exception:
        logger.warning(
            "AD-982a: emit_event(VISION_CAPABILITY_RESOLVED) failed for %s; "
            "grant applied but audit lost", agent_id, exc_info=True,
        )

    return {
        "agent_id": agent_id,
        "agent_type": agent_type,
        "vision_capable": req.enabled,
        "persisted": True,
    }


# ── AD-983b: per-agent capability enablement (tools + cognitive skills) ──────
def _tool_origin(tool_type: str, provider: str) -> str:
    """AD-1000a: classify a tool by *source* (provenance), aligning with the
    GitHub Copilot / Claude Code / VS Code taxonomy: ``built_in`` / ``mcp`` /
    ``extension``. Orthogonal to the AD-422 ``ToolType`` (which classifies by
    *function*). MCP-server tools are ``mcp``; tools contributed by the
    sealed-core extension path (AD-481 — self-designed agents/skills, providers
    tagged ``extension``/``designed``) are ``extension``; everything that ships
    with ProbOS is ``built_in``.
    """
    if tool_type == "mcp_server":
        return "mcp"
    if provider and provider.lower() in ("extension", "designed", "self_designed", "plugin"):
        return "extension"
    return "built_in"


def _rank_dept_for_agent(runtime: Any, agent: Any) -> tuple[str | None, str | None]:
    """Resolve (department, rank) for an agent the way onboarding does, for the
    dept/rank skill defaults. Tier-2: returns (None, None) on any failure."""
    dept: str | None = None
    rank: str | None = None
    try:
        ontology = getattr(runtime, "ontology", None)
        if ontology is not None:
            dept = ontology.get_agent_department(agent.agent_type)
    except Exception:
        logger.debug("AD-983b: department resolve failed for %s", agent.id, exc_info=True)
    try:
        trust_net = getattr(runtime, "trust_network", None)
        if trust_net is not None:
            from probos.crew_profile import Rank
            rank = Rank.from_trust(trust_net.get_score(agent.id)).value
    except Exception:
        logger.debug("AD-983b: rank resolve failed for %s", agent.id, exc_info=True)
    return dept, rank


@router.get("/{agent_id}/capabilities")
async def get_agent_capabilities(
    agent_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-983b: the agent's effective tools + cognitive skills, with provenance.

    Unified read surface for the Capability panel (AD-983c). Each entry carries
    ``granted`` and ``source`` (``grant`` / ``restriction`` / ``role_default``
    for tools; ``grant`` / ``restriction`` / ``dept_default`` for skills) so the
    UI can distinguish an explicit Captain grant from a role/department default.
    Honest-degrades to empty lists when a store is unavailable.
    """
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # --- Tools (ToolPermissionStore + ToolRegistry, AD-423b/AD-894) ---
    tools: list[dict[str, Any]] = []
    perms = getattr(runtime, "tool_permission_store", None)
    tool_registry = getattr(runtime, "tool_registry", None)
    if perms is not None:
        for grant in perms.get_active_grants_sync(agent_id):
            meta = tool_registry.get(grant.tool_id) if tool_registry is not None else None
            md = meta.to_dict() if meta is not None else None
            tools.append({
                "id": grant.tool_id,
                "name": (md or {}).get("name", grant.tool_id),
                "description": (md or {}).get("description", ""),
                "origin": _tool_origin((md or {}).get("tool_type", ""), (md or {}).get("provider", "")),
                "permission": grant.permission.value,
                "granted": not grant.is_restriction,
                "source": "restriction" if grant.is_restriction else "grant",
                "grant_id": grant.id,
                "reason": grant.reason,
            })

    # --- Cognitive skills (CognitiveSkillCatalog + SkillGrantStore, AD-983b) ---
    skills: list[dict[str, Any]] = []
    catalog = getattr(runtime, "cognitive_skill_catalog", None)
    grant_store = getattr(runtime, "skill_grant_store", None)
    if catalog is not None:
        dept, rank = _rank_dept_for_agent(runtime, agent)
        # Explicit grants/restrictions for source tagging.
        explicit_grant: set[str] = set()
        explicit_restrict: set[str] = set()
        if grant_store is not None:
            try:
                for g in grant_store.get_active_grants_sync(agent_id):
                    (explicit_restrict if g.is_restriction else explicit_grant).add(g.skill_name)
            except Exception:
                logger.debug("AD-983b: skill grant read failed for %s", agent_id, exc_info=True)
        effective = catalog.effective_entries_for_agent(
            agent_id, department=dept, min_rank=rank,
        )
        for entry in effective:
            source = "grant" if entry.name in explicit_grant else "dept_default"
            skills.append({
                "id": entry.name,
                "name": entry.name,
                "description": entry.description,
                "granted": True,
                "source": source,
                "department": entry.department,
                "min_rank": entry.min_rank,
            })
        # Surface active restrictions too (granted=False) so the UI can show a
        # skill the agent would otherwise hold but has been turned off.
        for name in explicit_restrict:
            entry = catalog.get_entry(name)
            skills.append({
                "id": name,
                "name": name,
                "description": entry.description if entry is not None else "",
                "granted": False,
                "source": "restriction",
                "department": entry.department if entry is not None else "*",
                "min_rank": entry.min_rank if entry is not None else "ensign",
            })

    return {"agent_id": agent_id, "tools": tools, "skills": skills, "mesh_intents": _mesh_intents(runtime)}


def _mesh_intents(runtime: Any) -> list[dict[str, Any]]:
    """AD-1000a: the live mesh-intent capabilities reachable on the ship — the
    third capability axis (alongside tools + skills) surfaced for visibility.

    Walks the live registry and collects every registered agent's
    ``intent_descriptors`` (deduped by name), each with its description,
    usage hint, consensus requirement, and tier. These are *pool-served*
    capabilities (e.g. ``run_python`` served by the CodeRunnerAgent pool), so
    the reachable set is ship-wide rather than per-agent — ``reachable`` reflects
    that a live pool serves the intent right now. Read-only visibility; per-agent
    gating of write intents is a separate design (epic #944). Honest-degrade:
    ``[]`` on no runtime / no registry / any failure.
    """
    registry = getattr(runtime, "registry", None)
    if registry is None:
        return []
    out: dict[str, dict[str, Any]] = {}
    try:
        for agent in registry.all():
            for desc in getattr(agent, "intent_descriptors", None) or []:
                name = getattr(desc, "name", "")
                if not name or name in out:
                    continue
                out[name] = {
                    "id": name,
                    "name": name,
                    "description": getattr(desc, "description", ""),
                    "usage_hint": getattr(desc, "usage_hint", ""),
                    "requires_consensus": bool(getattr(desc, "requires_consensus", False)),
                    "tier": getattr(desc, "tier", "domain"),
                    "origin": "built_in",
                    "reachable": True,
                }
    except Exception:
        logger.debug("AD-1000a: mesh-intent collection failed", exc_info=True)
        return []
    return sorted(out.values(), key=lambda d: d["name"])


@router.get("/{agent_id}/workspace")
async def get_agent_workspace(
    agent_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-998: the agent's code-execution working folder + its contents.

    Surfaces the AD-997 per-agent persistent working folder for the profile-card
    Work tab. The folder is resolved by the SAME key the ``CodeRunnerAgent``
    writes under (``WorkspaceManager.key_for_agent``), so the view matches where
    the agent actually works. Honest-degrades: reports ``enabled=False`` when
    code execution is off, ``persistent=False`` when workspaces are ephemeral
    (nothing to show between runs), and an empty file list for an agent that
    has not run code yet. Read-only.
    """
    from probos.execution.workspace import WorkspaceManager

    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    cfg = getattr(getattr(runtime, "config", None), "execution", None)
    enabled = bool(getattr(cfg, "enabled", False))
    persistent = bool(getattr(cfg, "persistent_workspaces", False))
    root = getattr(cfg, "workspace_root", "") if cfg is not None else ""

    base: dict[str, Any] = {
        "agent_id": agent_id,
        "enabled": enabled,
        "persistent": persistent,
        "root": root,
        "path": None,
        "owner": None,
        "exists": False,
        "files": [],
        "total_bytes": 0,
    }
    # Only persistent + enabled execution has a stable folder worth showing.
    if cfg is None or not enabled or not persistent or not root:
        return base

    try:
        mgr = WorkspaceManager(root)
        owner = mgr.key_for_agent(agent)
        path = mgr.resolve(owner)
        files = mgr.list_files(owner)
        base.update({
            "path": str(path),
            "owner": owner,
            "exists": path.is_dir(),
            "files": [
                {
                    "name": f.name,
                    "is_dir": f.is_dir,
                    "size_bytes": f.size_bytes,
                    "modified": f.modified,
                }
                for f in files
            ],
            "total_bytes": mgr.total_bytes(owner),
        })
    except Exception:
        logger.debug("AD-998: workspace resolve failed for %s", agent_id, exc_info=True)
    return base


@router.post("/{agent_id}/capabilities/set")
async def set_agent_capability(
    agent_id: str,
    req: SetCapability,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-983b: Captain enables/disables a tool or cognitive skill on an agent.

    ``enabled=True`` issues a grant; ``enabled=False`` issues a restriction
    (which overrides a role/department default). Audit-logged via
    ``CAPABILITY_ACCESS_RESOLVED``. The generalization of the AD-982 vision
    ``set`` endpoint to the full tool/skill set.
    """
    from probos.events import EventType

    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    reason = req.reason or "captain_set"
    if req.kind == "tool":
        perms = getattr(runtime, "tool_permission_store", None)
        if perms is None:
            raise HTTPException(status_code=503, detail="tool_permission_store_unavailable")
        tool_registry = getattr(runtime, "tool_registry", None)
        if tool_registry is not None and tool_registry.get(req.id) is None:
            raise HTTPException(status_code=404, detail=f"Tool not found: {req.id}")
        from probos.tools.protocol import ToolPermission
        grant = await perms.issue_grant(
            agent_id, req.id, ToolPermission.READ,
            is_restriction=not req.enabled, reason=reason, issued_by="captain",
        )
        grant_id = grant.id
    else:  # skill
        grant_store = getattr(runtime, "skill_grant_store", None)
        if grant_store is None:
            raise HTTPException(status_code=503, detail="skill_grant_store_unavailable")
        catalog = getattr(runtime, "cognitive_skill_catalog", None)
        if catalog is not None and catalog.get_entry(req.id) is None:
            raise HTTPException(status_code=404, detail=f"Skill not found: {req.id}")
        grant = await grant_store.issue_grant(
            agent_id, req.id,
            is_restriction=not req.enabled, reason=reason, issued_by="captain",
        )
        grant_id = grant.id

    try:
        runtime.emit_event(
            EventType.CAPABILITY_ACCESS_RESOLVED,
            {
                "agent_id": agent_id,
                "kind": req.kind,
                "capability_id": req.id,
                "resolution": "captain_granted" if req.enabled else "captain_restricted",
                "reason": req.reason,
                "source": "captain_set",
            },
        )
    except Exception:
        logger.warning(
            "AD-983b: emit_event(CAPABILITY_ACCESS_RESOLVED) failed for %s; "
            "grant applied but audit lost", agent_id, exc_info=True,
        )

    return {
        "agent_id": agent_id,
        "kind": req.kind,
        "id": req.id,
        "enabled": req.enabled,
        "grant_id": grant_id,
    }


# ── AD-721d-2: Counselor-mediated avatar revision ──────────────

@router.post("/{agent_id}/appearance/mediate")
async def mediate_appearance_revision(
    agent_id: str,
    req: MediateAppearanceRevision,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-721d-2: route a Captain's revision hint through a mediator agent.

    The mediator's agent_id is in the path (typically the Counselor). Body
    carries ``target_agent_id`` + ``captain_hint``. Uses the targeted-RPC
    primitive ``IntentBus.send(IntentMessage(target_agent_id=...))``, NOT
    broadcast — broadcast would fan out to all subscribers and re-trigger
    the mediator multiple times.
    """
    from probos.types import IntentMessage

    msg = IntentMessage(
        intent="mediate_appearance_revision",
        target_agent_id=agent_id,
        params={
            "target_agent_id": req.target_agent_id,
            "captain_hint": req.captain_hint,
        },
    )
    try:
        intent_result = await runtime.intent_bus.send(msg)
    except Exception:
        logger.warning(
            "AD-721d-2: intent_bus.send failed mediator=%s",
            agent_id, exc_info=True,
        )
        raise HTTPException(status_code=503, detail="mediator_unreachable")

    if intent_result is None:
        raise HTTPException(status_code=503, detail="mediator_unreachable")
    payload = getattr(intent_result, "result", None)
    if payload is None and isinstance(intent_result, dict):
        payload = intent_result.get("result")
    if not isinstance(payload, dict) or not payload.get("ok"):
        reason = (
            payload.get("reason")
            if isinstance(payload, dict)
            else "mediation_failed"
        ) or "mediation_failed"
        raise HTTPException(status_code=422, detail=reason)
    return payload


@router.get("/{agent_id}/avatar-telemetry")
async def agent_avatar_telemetry(
    agent_id: str,
    runtime: Any = Depends(get_runtime),
    _: None = Depends(require_crew_scope),
) -> dict[str, Any]:
    """AD-722: read-only avatar telemetry snapshot.

    Reuses the AD-721 ``_avatars_feature_check`` for the 3D-avatar gate
    (503 when avatars disabled), plus an AD-722-specific ``avatar_telemetry.enabled``
    gate. Returns 404 when the agent is missing. Never returns 422 — malformed
    persisted DSL becomes a degraded field with a 200 response (degraded_reasons).
    """
    _avatars_feature_check(runtime)

    cfg = getattr(runtime, "config", None)
    telemetry_cfg = getattr(cfg, "avatar_telemetry", None)
    if telemetry_cfg is None or not telemetry_cfg.enabled:
        raise HTTPException(status_code=503, detail="avatar_telemetry_disabled")

    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    from probos.avatars.telemetry import build_telemetry_snapshot
    snap = await build_telemetry_snapshot(agent_id, runtime)
    return snap.to_dict()


@router.get("/{agent_id}/avatar-telemetry/history")
async def agent_avatar_telemetry_history(
    agent_id: str,
    limit: int = 100,
    since: float | None = None,
    runtime: Any = Depends(get_runtime),
    _: None = Depends(require_crew_scope),
) -> dict[str, Any]:
    """AD-722c: query persisted telemetry snapshots for an agent.

    Returns {"agent_id": ..., "rows": [{"ts": float, "snap": {...}}, ...]}.
    Empty `rows` when feature disabled, agent not found, or no history yet.
    """
    cfg = getattr(runtime, "config", None)
    telemetry_cfg = getattr(cfg, "avatar_telemetry", None)
    if telemetry_cfg is None or not telemetry_cfg.enabled:
        raise HTTPException(status_code=503, detail="avatar_telemetry_disabled")
    if not telemetry_cfg.history_enabled:
        return {"agent_id": agent_id, "rows": []}

    # Boundary defense — clamp limit. Don't 4xx; just clamp.
    limit = max(1, min(int(limit), 1000))

    writer = getattr(runtime, "avatar_telemetry_history", None)
    if writer is None:
        return {"agent_id": agent_id, "rows": []}

    rows = await writer.query(
        agent_id,
        limit=limit,
        since=since,
        retention_days=telemetry_cfg.history_retention_days,
    )
    return {"agent_id": agent_id, "rows": rows}


async def _safe_ws_close(websocket: WebSocket, *, code: int, reason: str) -> None:
    """Close a WebSocket without surfacing close-time races as ASGI errors.

    BF-626: when the peer has already disconnected — common during the boot
    window when the HXI opens the telemetry socket before crew agents finish
    registering, then reconnects — the underlying ``websockets`` legacy
    protocol can raise ``AttributeError: 'WebSocketProtocol' object has no
    attribute 'transfer_data_task'`` (or ``RuntimeError``) from inside
    ``close()`` because the data-transfer task was never created. The
    connection is going away regardless, so a failed close has no functional
    impact; swallow it (Tier-2 honest-degrade) rather than letting it bubble
    up as an unhandled ASGI exception in the server log.
    """
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        logger.debug(
            "BF-626: WS close raced with peer disconnect "
            "(code=%s reason=%s); ignoring",
            code,
            reason,
            exc_info=True,
        )


@router.websocket("/{agent_id}/avatar-telemetry-stream")
async def agent_avatar_telemetry_stream(
    websocket: WebSocket,
    agent_id: str,
) -> None:
    """AD-722b: WebSocket push channel for avatar telemetry.

    Same feature gates as the GET endpoint. Subscribe → tier flip to
    HIGH via ``avatar_sampling_state.enter_popout``; disconnect → flip
    back via ``exit_popout``. Publish loop awaits both an interval timer
    (rate from ``current_rate_ms``) and a per-agent event (set by trigger
    surfaces). On either wake, builds + sends a fresh snapshot.

    Authentication: feature-gate-only — same model as the GET endpoint.
    Forward marker AD-722b-1 covers crew-scoped auth.
    """
    runtime = websocket.app.state.runtime
    # AD-722b-1: crew-scope auth gate (pre-accept). Pass-through when
    # ``auth.crew_scope_token`` is empty (default-OFF, backward-compat).
    if not await verify_ws_token(websocket, runtime):
        return
    cfg = getattr(runtime, "config", None)
    avatars_cfg = getattr(cfg, "avatars", None)
    telemetry_cfg = getattr(cfg, "avatar_telemetry", None)

    # Feature gate 1: avatars system disabled — close before accept.
    if avatars_cfg is None or not avatars_cfg.enabled:
        await _safe_ws_close(websocket, code=1008, reason="avatars_disabled")
        return
    # Feature gate 2: avatar telemetry disabled.
    if telemetry_cfg is None or not telemetry_cfg.enabled:
        await _safe_ws_close(websocket, code=1008, reason="avatar_telemetry_disabled")
        return
    # Agent existence check.
    agent = runtime.registry.get(agent_id)
    if agent is None:
        await _safe_ws_close(websocket, code=1008, reason="agent_not_found")
        return

    # Accept the handshake.
    await websocket.accept()

    # Max-connections enforcement — accept-then-immediate-close so the
    # client receives a structured close frame.
    from probos.avatars.ws_connection_manager import MaxConnectionsExceeded
    conn_manager = getattr(
        runtime, "avatar_telemetry_connection_manager", None,
    )
    sampling_state = getattr(runtime, "avatar_sampling_state", None)
    event_bus = getattr(runtime, "avatar_event_bus", None)
    if conn_manager is None or sampling_state is None or event_bus is None:
        await websocket.send_json(
            {"type": "error", "reason": "telemetry_runtime_unavailable"},
        )
        await _safe_ws_close(websocket, code=1011, reason="runtime_unavailable")
        return

    try:
        connection_id = conn_manager.register(agent_id, websocket)
    except MaxConnectionsExceeded:
        await websocket.send_json(
            {"type": "error", "reason": "max_connections_exceeded"},
        )
        await _safe_ws_close(websocket, code=1008, reason="max_connections_exceeded")
        return

    sampling_state.enter_popout(agent_id)
    event = event_bus.subscribe(agent_id)
    publish_task: asyncio.Task | None = None
    receive_task: asyncio.Task | None = None
    # AD-722b-3: per-connection diff state. Each WS connection has its
    # own "last sent" tracker so reconnects (which receive the full
    # initial snapshot) don't depend on cross-connection memory.
    last_sent_snap_dict: dict[str, Any] | None = None
    tick_count = 0
    try:
        from probos.avatars.telemetry import build_telemetry_snapshot

        # Send an initial snapshot immediately on connect (UI populates fast).
        # AD-722b-2: also write to agent._last_self_avatar_snap so the agent's
        # own sensorium (INTEROCEPTION) stays fresh without re-polling.
        try:
            initial = await build_telemetry_snapshot(agent_id, runtime)
            agent._last_self_avatar_snap = initial
            initial_dict = initial.to_dict()
            await websocket.send_json({"type": "snapshot", **initial_dict})
            last_sent_snap_dict = initial_dict
            # AD-722c: best-effort persistence. Never blocks the publish.
            _hist = getattr(runtime, "avatar_telemetry_history", None)
            if _hist is not None:
                try:
                    await _hist.append(initial)
                except Exception:
                    logger.debug(
                        "AD-722c: history append raised on initial send",
                        exc_info=True,
                    )
            # AD-722d: best-effort Records significance write.
            _rw = getattr(runtime, "avatar_telemetry_records_writer", None)
            if _rw is not None:
                try:
                    await _rw.observe(initial)
                except Exception:
                    logger.debug(
                        "AD-722d: records writer raised on initial send",
                        exc_info=True,
                    )
        except Exception:
            logger.warning(
                "AD-722b: initial snapshot send failed for agent=%s",
                agent_id, exc_info=True,
            )

        async def _publish_loop() -> None:
            """Per-connection publish loop. Sleep-or-event-driven."""
            nonlocal tick_count, last_sent_snap_dict
            while True:
                rate_ms = sampling_state.current_rate_ms(agent_id)
                interval_s = max(0.05, float(rate_ms) / 1000.0)
                event.clear()
                # Race the timer against the event.
                wait_event = asyncio.create_task(event.wait())
                wait_timer = asyncio.create_task(asyncio.sleep(interval_s))
                try:
                    await asyncio.wait(
                        {wait_event, wait_timer},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    for t in (wait_event, wait_timer):
                        if not t.done():
                            t.cancel()
                # Build + send.
                # AD-722b-2: same side-effect as initial — keep agent cache fresh.
                snap = await build_telemetry_snapshot(agent_id, runtime)
                agent._last_self_avatar_snap = snap
                snap_dict = snap.to_dict()
                tick_count += 1
                cfg_t = getattr(runtime.config, "avatar_telemetry", None)
                send_full = (
                    cfg_t is None
                    or not cfg_t.ws_diff_enabled
                    or (tick_count % cfg_t.ws_full_snapshot_every_n) == 0
                )
                if send_full:
                    await websocket.send_json({"type": "snapshot", **snap_dict})
                    last_sent_snap_dict = snap_dict
                else:
                    try:
                        from probos.avatars.snapshot_diff import compute_diff
                        diff = compute_diff(
                            last_sent_snap_dict,
                            snap_dict,
                            threshold=cfg_t.ws_diff_threshold,
                        )
                    except Exception:
                        logger.warning(
                            "AD-722b-3: compute_diff raised; falling back to full snapshot",
                            exc_info=True,
                        )
                        await websocket.send_json({"type": "snapshot", **snap_dict})
                        last_sent_snap_dict = snap_dict
                        diff = None
                    if diff is not None:
                        if not diff:
                            # No significant change — skip the send entirely.
                            # Still run the AD-722c/AD-722d side-effects below
                            # so persistence + significance classification
                            # never drop frames.
                            pass
                        else:
                            await websocket.send_json({
                                "type": "diff",
                                "agent_id": snap.agent_id,
                                "changed": diff,
                            })
                            last_sent_snap_dict = {
                                **(last_sent_snap_dict or {}), **diff,
                            }
                # AD-722c: best-effort persistence. Never blocks the publish.
                _hist = getattr(runtime, "avatar_telemetry_history", None)
                if _hist is not None:
                    try:
                        await _hist.append(snap)
                    except Exception:
                        logger.debug(
                            "AD-722c: history append raised in publish loop",
                            exc_info=True,
                        )
                # AD-722d: best-effort Records significance write.
                _rw = getattr(runtime, "avatar_telemetry_records_writer", None)
                if _rw is not None:
                    try:
                        await _rw.observe(snap)
                    except Exception:
                        logger.debug(
                            "AD-722d: records writer raised in publish loop",
                            exc_info=True,
                        )

        async def _receive_loop() -> None:
            """Drain client messages so WebSocketDisconnect surfaces.

            v1 ignores client message content (no client-driven commands);
            the loop exists solely to detect disconnect. 30 s heartbeat
            ping is sent by this side when no other receive arrives.
            """
            while True:
                try:
                    await asyncio.wait_for(
                        websocket.receive_text(), timeout=30.0,
                    )
                except asyncio.TimeoutError:
                    await websocket.send_json(
                        {"type": "ping", "timestamp": time.time()},
                    )

        publish_task = asyncio.create_task(_publish_loop())
        receive_task = asyncio.create_task(_receive_loop())

        # Whichever finishes first ends the connection.
        done, pending = await asyncio.wait(
            {publish_task, receive_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        # Surface any non-disconnect exception from the completed task.
        for t in done:
            exc = t.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                logger.warning(
                    "AD-722b: WS task ended for agent=%s with %s",
                    agent_id, type(exc).__name__, exc_info=exc,
                )

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning(
            "AD-722b: WS handler error for agent=%s",
            agent_id, exc_info=True,
        )
    finally:
        # Cleanup MUST always run.
        if publish_task is not None and not publish_task.done():
            publish_task.cancel()
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()
        try:
            event_bus.unsubscribe(agent_id, event)
        except Exception:
            logger.debug(
                "AD-722b: unsubscribe failed for agent=%s",
                agent_id, exc_info=True,
            )
        try:
            sampling_state.exit_popout(agent_id)
        except Exception:
            logger.debug(
                "AD-722b: exit_popout failed for agent=%s",
                agent_id, exc_info=True,
            )
        try:
            conn_manager.deregister(agent_id, connection_id)
        except Exception:
            logger.debug(
                "AD-722b: deregister failed for agent=%s",
                agent_id, exc_info=True,
            )


# AD-722b-4: fleet-level avatar telemetry stream.
# Same feature gates as the per-agent endpoint. Adds an additional
# fleet_stream_enabled gate. Iterates all crew agents on accept and
# fans out per-agent publish loops over a single WS connection.
# Every frame carries an explicit "agent_id" field (the per-agent
# endpoint omits it; HXI hooks distinguish by endpoint URL).
@router.websocket("/avatar-telemetry/stream")
async def fleet_avatar_telemetry_stream(websocket: WebSocket) -> None:
    runtime = websocket.app.state.runtime
    # AD-722b-1: crew-scope auth gate (pre-accept). Pass-through when
    # ``auth.crew_scope_token`` is empty (default-OFF, backward-compat).
    if not await verify_ws_token(websocket, runtime):
        return
    cfg = getattr(runtime, "config", None)
    avatars_cfg = getattr(cfg, "avatars", None)
    telemetry_cfg = getattr(cfg, "avatar_telemetry", None)

    if avatars_cfg is None or not avatars_cfg.enabled:
        await _safe_ws_close(websocket, code=1008, reason="avatars_disabled")
        return
    if telemetry_cfg is None or not telemetry_cfg.enabled:
        await _safe_ws_close(websocket, code=1008, reason="avatar_telemetry_disabled")
        return
    if not getattr(telemetry_cfg, "fleet_stream_enabled", True):
        await _safe_ws_close(websocket, code=1008, reason="fleet_stream_disabled")
        return

    await websocket.accept()

    sampling_state = getattr(runtime, "avatar_sampling_state", None)
    event_bus = getattr(runtime, "avatar_event_bus", None)
    if sampling_state is None or event_bus is None:
        await websocket.send_json(
            {"type": "error", "reason": "telemetry_runtime_unavailable"},
        )
        await _safe_ws_close(websocket, code=1011, reason="runtime_unavailable")
        return

    # Build the per-agent task set on accept. Discovery is a snapshot;
    # newly-spawned crew during the connection lifetime are NOT picked
    # up until the client reconnects. v1 simplification — AD-722b-4-1
    # forward marker for dynamic membership.
    crew_agents: list[tuple[str, Any]] = []
    for agent in runtime.registry.all():
        try:
            if is_crew_agent(agent, runtime.ontology):
                crew_agents.append((agent.agent_id, agent))
        except Exception:
            logger.debug(
                "AD-722b-4: crew discovery skipped agent during fleet accept",
                exc_info=True,
            )

    if not crew_agents:
        # Honest-degrade: no crew yet → close cleanly.
        await _safe_ws_close(websocket, code=1008, reason="no_crew_agents")
        return

    events: dict[str, asyncio.Event] = {}
    last_sent: dict[str, dict[str, Any] | None] = {}
    tick_counts: dict[str, int] = {}

    from probos.avatars.telemetry import build_telemetry_snapshot

    for agent_id, _agent in crew_agents:
        sampling_state.enter_popout(agent_id)
        events[agent_id] = event_bus.subscribe(agent_id)
        last_sent[agent_id] = None
        tick_counts[agent_id] = 0

    publish_tasks: list[asyncio.Task] = []
    receive_task: asyncio.Task | None = None
    try:
        # Initial snapshot per agent.
        for agent_id, agent in crew_agents:
            try:
                initial = await build_telemetry_snapshot(agent_id, runtime)
                agent._last_self_avatar_snap = initial
                initial_dict = initial.to_dict()
                await websocket.send_json(
                    {"type": "snapshot", "agent_id": agent_id, **initial_dict},
                )
                last_sent[agent_id] = initial_dict
                _hist = getattr(runtime, "avatar_telemetry_history", None)
                if _hist is not None:
                    try:
                        await _hist.append(initial)
                    except Exception:
                        logger.debug(
                            "AD-722b-4: history append raised on initial for %s",
                            agent_id, exc_info=True,
                        )
                _rw = getattr(runtime, "avatar_telemetry_records_writer", None)
                if _rw is not None:
                    try:
                        await _rw.observe(initial)
                    except Exception:
                        logger.debug(
                            "AD-722b-4: records writer raised on initial for %s",
                            agent_id, exc_info=True,
                        )
            except Exception:
                logger.warning(
                    "AD-722b-4: initial snapshot failed for agent=%s",
                    agent_id, exc_info=True,
                )

        async def _publish_one(agent_id: str, agent: Any) -> None:
            """Per-agent publish loop, mirroring the per-agent endpoint."""
            event = events[agent_id]
            while True:
                rate_ms = sampling_state.current_rate_ms(agent_id)
                interval_s = max(0.05, float(rate_ms) / 1000.0)
                event.clear()
                wait_event = asyncio.create_task(event.wait())
                wait_timer = asyncio.create_task(asyncio.sleep(interval_s))
                try:
                    await asyncio.wait(
                        {wait_event, wait_timer},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                finally:
                    for t in (wait_event, wait_timer):
                        if not t.done():
                            t.cancel()
                snap = await build_telemetry_snapshot(agent_id, runtime)
                agent._last_self_avatar_snap = snap
                snap_dict = snap.to_dict()
                tick_counts[agent_id] += 1
                cfg_t = getattr(runtime.config, "avatar_telemetry", None)
                send_full = (
                    cfg_t is None
                    or not getattr(cfg_t, "ws_diff_enabled", False)
                    or (tick_counts[agent_id] % cfg_t.ws_full_snapshot_every_n) == 0
                )
                if send_full:
                    await websocket.send_json(
                        {"type": "snapshot", "agent_id": agent_id, **snap_dict},
                    )
                    last_sent[agent_id] = snap_dict
                else:
                    diff: dict[str, Any] | None = None
                    try:
                        from probos.avatars.snapshot_diff import compute_diff
                        diff = compute_diff(
                            last_sent[agent_id],
                            snap_dict,
                            threshold=cfg_t.ws_diff_threshold,
                        )
                    except Exception:
                        logger.warning(
                            "AD-722b-4: compute_diff raised; falling back to full snapshot for %s",
                            agent_id, exc_info=True,
                        )
                        await websocket.send_json(
                            {"type": "snapshot", "agent_id": agent_id, **snap_dict},
                        )
                        last_sent[agent_id] = snap_dict
                    if diff:
                        await websocket.send_json({
                            "type": "diff",
                            "agent_id": agent_id,
                            "changed": diff,
                        })
                        last_sent[agent_id] = {
                            **(last_sent[agent_id] or {}), **diff,
                        }
                _hist = getattr(runtime, "avatar_telemetry_history", None)
                if _hist is not None:
                    try:
                        await _hist.append(snap)
                    except Exception:
                        logger.debug(
                            "AD-722b-4: history append raised for %s",
                            agent_id, exc_info=True,
                        )
                _rw = getattr(runtime, "avatar_telemetry_records_writer", None)
                if _rw is not None:
                    try:
                        await _rw.observe(snap)
                    except Exception:
                        logger.debug(
                            "AD-722b-4: records writer raised for %s",
                            agent_id, exc_info=True,
                        )

        async def _receive_loop() -> None:
            while True:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                except asyncio.TimeoutError:
                    await websocket.send_json(
                        {"type": "ping", "timestamp": time.time()},
                    )

        for agent_id, agent in crew_agents:
            publish_tasks.append(asyncio.create_task(_publish_one(agent_id, agent)))
        receive_task = asyncio.create_task(_receive_loop())

        done, pending = await asyncio.wait(
            {*publish_tasks, receive_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        for t in done:
            exc = t.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                logger.warning(
                    "AD-722b-4: fleet WS task ended with %s",
                    type(exc).__name__, exc_info=exc,
                )

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.warning("AD-722b-4: fleet WS handler error", exc_info=True)
    finally:
        for t in publish_tasks:
            if not t.done():
                t.cancel()
        if receive_task is not None and not receive_task.done():
            receive_task.cancel()
        for agent_id in list(events):
            try:
                event_bus.unsubscribe(agent_id, events[agent_id])
            except Exception:
                logger.debug(
                    "AD-722b-4: unsubscribe failed for %s", agent_id, exc_info=True,
                )
            try:
                sampling_state.exit_popout(agent_id)
            except Exception:
                logger.debug(
                    "AD-722b-4: exit_popout failed for %s", agent_id, exc_info=True,
                )


@router.get("/{agent_id}/avatar-telemetry/divergence-history")
async def agent_avatar_divergence_history(
    agent_id: str,
    limit: int = 20,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-722a-5: read-only divergence history for one agent.

    Per-agent only (cross-crew is forward marker AD-722a-6 / #615).
    Most-recent-first. Returns ``history`` (capped at min(limit, ring_size))
    + ``aggregate`` (count + percentage walked over the configured window).

    Feature gate: ``avatar_telemetry.divergence_detection`` -- 503 when off,
    so the UI panel auto-hides without a separate capability probe.
    """
    _avatars_feature_check(runtime)

    cfg = getattr(runtime, "config", None)
    telemetry_cfg = getattr(cfg, "avatar_telemetry", None)
    if telemetry_cfg is None or not telemetry_cfg.enabled:
        raise HTTPException(status_code=503, detail="avatar_telemetry_disabled")
    if not getattr(telemetry_cfg, "divergence_detection", False):
        raise HTTPException(status_code=503, detail="divergence_detection_disabled")

    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    # Read-side clamp on limit (defense in depth -- caller-provided integer).
    if limit < 1:
        limit = 1
    history_map = getattr(runtime, "divergence_history", {}) or {}
    bucket = history_map.get(agent_id)
    entries = list(bucket) if bucket is not None else []

    # Most-recent-first.
    entries_reversed = list(reversed(entries))
    history_payload = [e.to_dict() for e in entries_reversed[:limit]]

    # Aggregate over the configured window (clamped to actual length).
    window_size = int(getattr(
        telemetry_cfg, "divergence_aggregate_window", 50,
    ))
    if window_size < 0:
        window_size = 0
    walked = entries_reversed[:window_size]
    total = len(walked)
    diverged = sum(1 for e in walked if e.result.magnitude > 0.0)
    percentage = (diverged / total) if total > 0 else 0.0

    return {
        "agent_id": agent_id,
        "history": history_payload,
        "aggregate": {
            "window_size": total,
            "total": total,
            "diverged": diverged,
            "percentage": percentage,
        },
    }


@router.post("/{agent_id}/chat")
async def agent_chat(agent_id: str, req: AgentChatRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Send a direct message to a specific agent and get their response."""
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    if not is_crew_agent(agent, runtime.ontology):
        raise HTTPException(status_code=400, detail=f"Agent {agent_id} is not a crew agent — direct chat is crew-only")

    # AD-791a: resolve (or create) the implicit default 1:1 thread for this
    # agent. The chat-thread substrate exists since AD-791; AD-791a wires
    # it into the actual turn flow. ``get_or_create_default_for_agent`` is
    # race-safe via BEGIN IMMEDIATE so two concurrent first-turn requests
    # can't both insert. Tier-2 log-and-degrade: a missing store (early
    # boot / test runtime) yields ``thread = None`` and the rest of the
    # handler proceeds without thread wiring — backward-compatible with
    # any caller that never sees chat_thread_store.
    _thread_store = getattr(runtime, "chat_thread_store", None)
    thread = None
    if _thread_store is not None:
        try:
            _callsign_for_thread = ""
            if hasattr(runtime, "callsign_registry"):
                try:
                    _callsign_for_thread = (
                        runtime.callsign_registry.get_callsign(agent.agent_type) or ""
                    )
                except Exception:
                    _callsign_for_thread = ""
            _title = _callsign_for_thread or agent_id
            # AD-791a: optional explicit thread_id override (forward-compat
            # with AD-792 sidebar). When set, must reference an existing
            # thread that includes this agent in its participants list.
            _explicit_id = getattr(req, "thread_id", None)
            if _explicit_id:
                _explicit = _thread_store.get_thread(_explicit_id)
                if _explicit is None or agent_id not in _explicit.participants:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid thread_id for this agent",
                    )
                thread = _explicit
            else:
                thread = _thread_store.get_or_create_default_for_agent(
                    agent_id, _title,
                )
            # AD-794/AD-809: the captain-message append happens AFTER
            # the /personality slash-command guard + maybe_auto_name
            # below — the slash-command handler logs the captain side
            # itself, and auto-name needs to see the original title.
        except HTTPException:
            raise
        except Exception:
            logger.warning(
                "AD-791a: chat-thread resolve failed for agent=%s; "
                "continuing without thread wiring",
                agent_id, exc_info=True,
            )
            thread = None

    # AD-809: /personality slash command — pure thread-state op. Runs
    # BEFORE auto-name (so the slash-command syntax never names the
    # thread) and BEFORE the captain-message append (the handler logs
    # both the captain command and the system reply itself). Early-
    # return short-circuits IntentBus dispatch and the agent turn.
    if (
        _thread_store is not None
        and thread is not None
        and is_personality_command(req.message)
    ):
        try:
            _personality_result = handle_personality_command(
                req.message,
                thread_id=thread.id,
                store=_thread_store,
            )
            _thread_store.append_message(
                thread.id,
                author_id="captain",
                role="captain",
                body=req.message,
                metadata={"slash_command": "personality"},
            )
            _thread_store.append_message(
                thread.id,
                author_id="system",
                role="system",
                body=_personality_result["system_reply"],
                metadata={
                    "slash_command": "personality",
                    "applied": _personality_result["applied"],
                },
            )
        except Exception:
            logger.warning(
                "AD-809: /personality handler failed for thread=%s agent=%s",
                thread.id, agent_id, exc_info=True,
            )
            _personality_result = {
                "system_reply": "Personality command failed; please try again.",
                "applied": None,
            }
        return {
            "response": _personality_result["system_reply"],
            "thread_id": thread.id,
            "system": True,
            "applied": _personality_result.get("applied"),
            "dag": None,
            "results": None,
        }

    # AD-794: first-turn auto-name from the message body. Idempotent;
    # returns None when the thread is locked, already renamed, or the
    # heuristic produced no useful title. Refresh the local ``thread``
    # var after so downstream code sees the new title.
    if _thread_store is not None and thread is not None:
        try:
            _renamed = _thread_store.maybe_auto_name(thread.id, req.message)
            if _renamed is not None:
                thread = _renamed
        except Exception:
            logger.warning(
                "AD-794: maybe_auto_name failed for thread=%s agent=%s",
                thread.id, agent_id, exc_info=True,
            )

    # AD-791a: log the captain side of the turn before dispatch so the
    # message log reflects the operator's input even if the downstream
    # pipeline raises. (Moved below the /personality guard + auto-name
    # per AD-794 Section 2 ordering.)
    if _thread_store is not None and thread is not None:
        try:
            _thread_store.append_message(
                thread.id,
                author_id="captain",
                role="captain",
                body=req.message,
                metadata={},
            )
        except Exception:
            logger.warning(
                "AD-791a: append captain message failed for thread=%s agent=%s",
                thread.id, agent_id, exc_info=True,
            )

    # AD-743: Captain interruption cancels any pending pacing follow-up so the
    # synthesized user-turn doesn't double-fire after a fresh Captain message.
    _pacing = getattr(runtime, "conversation_pacing_scheduler", None)
    if _pacing is not None:
        try:
            _pacing.cancel_for_conversation(agent_id)
        except Exception:
            logger.debug(
                "AD-743: pacing cancel_for_conversation raised for agent=%s",
                agent_id, exc_info=True,
            )

    # AD-725 (Wave 159): targeted sub-intent dispatch (DM one-shot pre-LLM
    # lookup). Tier-2 — never blocks the DM. When the classifier matches and
    # the lookup returns content, the recall block prepends message_text so
    # the receiving agent's LLM call sees it as part of the user message.
    # Default config: dm_targeted_lookup.enabled=False — opt-in only.
    targeted_recall_block: str | None = None
    try:
        _dm_cfg = getattr(runtime.config, "dm_targeted_lookup", None)
        if _dm_cfg is not None and _dm_cfg.enabled:
            from probos.cognitive.dm_targeted_lookup import LookupDispatcher
            _dispatcher = LookupDispatcher(runtime=runtime, config=_dm_cfg)
            _result = await _dispatcher.maybe_lookup(
                req.message, agent_id=agent_id,
            )
            if _result is not None and _result.content:
                targeted_recall_block = (
                    f"--- Targeted Recall ({_result.lookup_type}) ---\n"
                    f"{_result.content}\n"
                    f"--- End Recall ---"
                )
                logger.info(
                    "AD-725: agent=%s lookup_type=%s elapsed_ms=%.1f chars=%d",
                    agent_id, _result.lookup_type,
                    _result.elapsed_ms, len(_result.content),
                )
    except Exception:
        logger.debug("AD-725: dispatcher branch failed", exc_info=True)

    # AD-730 (Wave 151): vision pipe-through for per-agent DMs.
    # When req.attachment_ids includes an image MIME AND attachments.vision_tier
    # is operational, build the Anthropic-shape multimodal messages array and
    # pass it through IntentMessage.params['vision_messages']. The receiving
    # agent's direct_message handler routes that to LLMRequest(messages=...)
    # via the configured vision tier. When images are absent OR vision tier is
    # degraded, fall back to AD-720d's text-only augmentation (markers + extracted
    # text) so the agent at least sees the attachment names.
    # Tier-2 log-and-degrade throughout: failures revert to the original message.
    message_text = req.message
    vision_messages: list[dict[str, object]] | None = None
    # AD-720d-1: per-attachment timing list; populated when the vision branch
    # builds the multimodal messages. Stays empty for non-attachment DMs so
    # the episode outcome block at lines ~1228-1252 always sees a list.
    per_attachment: list[dict[str, object]] = []
    has_image_attachment = False
    if req.attachment_ids:
        cfg_attach = getattr(runtime.config, "attachments", None)
        if cfg_attach is not None and getattr(cfg_attach, "enabled", False):
            try:
                from probos.cognitive.vision_dispatch import (
                    augment_prompt_with_attachment_text,
                    build_multimodal_messages,
                )
                from probos.routers.chat import _get_attachment_store

                store = _get_attachment_store(runtime)

                async def _mime_lookup(content_hash: str) -> str | None:
                    return await store.mime_for(content_hash)

                # Build the multimodal array once; we may use either the
                # vision-tier path (image_ids present + tier operational) or
                # fall back to the text-only augmentation.
                messages, image_ids, per_attachment = await build_multimodal_messages(
                    prompt=req.message,
                    attachment_ids=list(req.attachment_ids),
                    store=store,
                    mime_lookup=_mime_lookup,
                    text_extraction_max_bytes=cfg_attach.text_extraction_max_bytes,
                    pdf_extraction_enabled=cfg_attach.pdf_extraction_enabled,
                )

                # AD-720d-1: soft warning when image count exceeds the operator
                # threshold. Log-only; never blocks or truncates. Cap the
                # logged attachment_ids list at the first 10 entries.
                warn_threshold = getattr(cfg_attach, "multi_image_warn_threshold", 0)
                if image_ids and warn_threshold and len(image_ids) > warn_threshold:
                    capped = list(req.attachment_ids)[:10]
                    logger.warning(
                        "AD-720d-1: per-agent DM vision turn includes %d images "
                        "(threshold=%d); proceeding without truncation. "
                        "agent_id=%s attachment_ids[:10]=%s",
                        len(image_ids), warn_threshold, agent_id, capped,
                    )

                # AD-730-2: hard cap + downscale + budget gates.
                # Order: cap check first (cheapest), then downscale
                # (rebuilds image_ids when any image was resized), then
                # budget (after downscale because budget tracks final
                # delivered images, not pre-compression count).
                if image_ids:
                    from probos.attachments.image_policy import (
                        ImagePolicyEnforcer, ImagePolicyError,
                    )
                    _enforcer = ImagePolicyEnforcer(runtime, cfg_attach)
                    try:
                        _enforcer.check_hard_cap(len(image_ids))
                    except ImagePolicyError as e:
                        raise HTTPException(
                            status_code=e.status_code, detail=e.detail,
                        )
                    _downscaled = await _enforcer.downscale_if_needed(
                        image_ids, store,
                    )
                    if _downscaled != image_ids:
                        # Rebuild the multimodal payload with the downscaled
                        # hashes substituted for the originals. Walk the
                        # caller's attachment_ids; only IMAGE hashes change.
                        _trans = dict(zip(image_ids, _downscaled))
                        _new_attach_ids = [
                            _trans.get(a, a) for a in req.attachment_ids
                        ]
                        messages, image_ids, per_attachment = await build_multimodal_messages(
                            prompt=req.message,
                            attachment_ids=_new_attach_ids,
                            store=store,
                            mime_lookup=_mime_lookup,
                            text_extraction_max_bytes=cfg_attach.text_extraction_max_bytes,
                            pdf_extraction_enabled=cfg_attach.pdf_extraction_enabled,
                        )
                    # Budget last — operates on the final delivered count.
                    _captain_id = getattr(runtime, "captain_id", None) or "default"
                    try:
                        _enforcer.check_budget(_captain_id, len(image_ids))
                    except ImagePolicyError as e:
                        headers: dict[str, str] = {}
                        if e.retry_after_seconds is not None:
                            headers["Retry-After"] = str(int(e.retry_after_seconds))
                        raise HTTPException(
                            status_code=e.status_code,
                            detail=e.detail,
                            headers=headers,
                        )

                if image_ids:
                    # AD-720d-2: vision_capable gate. If the receiving
                    # agent's CrewProfile.vision_capable is False, demote
                    # this turn to the text-only fallback path. The Captain
                    # attached the image deliberately — we surface attachment
                    # markers, NOT an honest-degrade refusal (that's
                    # AD-732's job for unconfigured/unhealthy *tiers*, a
                    # different failure mode).
                    _prof = runtime.callsign_registry.get_profile(
                        agent.agent_type
                    )
                    if not (_prof or {}).get("vision_capable", False):
                        logger.info(
                            "AD-720d-2: agent_id=%s vision_capable=False; "
                            "routing image attachment through text-only "
                            "fallback (attachment_ids=%s)",
                            agent_id, list(req.attachment_ids),
                        )
                        image_ids = []

                if image_ids:
                    tier = cfg_attach.vision_tier
                    # AD-730-5: per-agent_type override resolves to a
                    # specialized vision tier when configured; otherwise
                    # returns the default. Pure function.
                    from probos.cognitive.vision_dispatch import (
                        resolve_vision_tier_for_agent,
                    )
                    _override = resolve_vision_tier_for_agent(
                        cfg_attach, agent.agent_type, tier
                    )
                    health = runtime.llm_client.get_health_status()
                    if _override != tier and _override not in (
                        health.get("tiers", {}) or {}
                    ):
                        logger.warning(
                            "AD-730-5: vision_tier_overrides[%s]=%s not "
                            "registered in LLM client; falling back to "
                            "default tier=%s",
                            agent.agent_type, _override, tier,
                        )
                    else:
                        tier = _override
                    tier_status = (
                        health.get("tiers", {}).get(tier) or {}
                    ).get("status")
                    from probos.cognitive.vision_dispatch import (
                        VISION_UNCONFIGURED_MESSAGE,
                        VISION_UNHEALTHY_MESSAGE,
                        is_vision_tier_configured,
                    )
                    # AD-732: honest-degrade fires for unconfigured OR
                    # unhealthy vision. Early-return BEFORE
                    # _sampling_state.enter_dm + intent_bus.send so
                    # never-enter → never-exit holds (no DM refcount leak).
                    # The agent has no way to surface a missing endpoint
                    # to the crew; the OS speaks for itself.
                    configured = is_vision_tier_configured(
                        runtime.config.cognitive, tier
                    )
                    # BF-271 (2026-05-12): 'recovering' is operational. It
                    # means the tier has had recent successes but hasn't yet
                    # met the dwell-time threshold to clear its failure
                    # counter. The endpoint IS working — refusing to use it
                    # is over-cautious and produces honest-degrade messages
                    # for a working tier. AD-732's gate fires only on
                    # 'degraded'/'unreachable' (real failures).
                    if not configured or tier_status not in ("operational", "recovering"):
                        # callsign_registry is a stable runtime attribute
                        # (initialized in ProbOSRuntime.__init__); no guard.
                        _callsign = runtime.callsign_registry.get_callsign(
                            agent.agent_type
                        )
                        if not configured:
                            logger.info(
                                "AD-732: agent_chat vision DM unconfigured "
                                "for %s; honest-degrade. attachment_ids=%s",
                                agent_id, list(req.attachment_ids),
                            )
                            return {
                                "response": VISION_UNCONFIGURED_MESSAGE,
                                "callsign": _callsign,
                                "agentId": agent_id,
                            }
                        logger.warning(
                            "AD-732: agent_chat vision tier=%s unhealthy "
                            "(status=%s) for %s; honest-degrade. "
                            "attachment_ids=%s",
                            tier, tier_status, agent_id, list(req.attachment_ids),
                        )
                        return {
                            "response": VISION_UNHEALTHY_MESSAGE,
                            "callsign": _callsign,
                            "agentId": agent_id,
                        }
                    vision_messages = messages
                    has_image_attachment = True
                    # Keep message_text as the original Captain text so
                    # episodic memory remains search-friendly; the LLM
                    # sees the full multimodal array via vision_messages.

                if vision_messages is None:
                    # Text-only path: either no images, or vision degraded.
                    message_text = await augment_prompt_with_attachment_text(
                        prompt=req.message,
                        attachment_ids=list(req.attachment_ids),
                        store=store,
                        mime_lookup=_mime_lookup,
                        text_extraction_max_bytes=cfg_attach.text_extraction_max_bytes,
                        pdf_extraction_enabled=cfg_attach.pdf_extraction_enabled,
                    )
            except Exception as e:
                logger.warning(
                    "agent_chat attachment augmentation failed for %s: %s: %s; "
                    "falling back to text-only message",
                    agent_id, type(e).__name__, e,
                )

    from probos.types import IntentMessage
    # AD-725 (Wave 159): prepend the targeted recall block so the receiving
    # agent's LLM call sees it as part of the user message.
    if targeted_recall_block is not None:
        message_text = f"{targeted_recall_block}\n\n{message_text}"

    # AD-793 (Wave 196): project preamble. When the thread belongs to a
    # project with a non-empty description, prepend the Captain-authored
    # "what this project is about" framing. Inserts BETWEEN recall and
    # visual prepend so the final on-the-wire order is:
    #     visual → project → recall → user
    # Tier-2 honest-degrade: missing store / deleted project / empty
    # description silently omit the block (no crash, no fabrication).
    # Delimiter framing matches AD-733a / BF-294 provenance pattern.
    _project_preamble: str | None = None
    try:
        _project_id = getattr(thread, "project_id", None) if thread else None
        # Type-guard: real ChatThread.project_id is str | None. Defends
        # against MagicMock-auto-attribute test stubs (BF-287 / phantom-
        # via-MagicMock pattern) where attribute access returns a
        # truthy mock that would otherwise inject a garbage preamble.
        if isinstance(_project_id, str) and _project_id:
            _project_store = getattr(runtime, "project_store", None)
            if _project_store is not None:
                _project = _project_store.get_project(_project_id)
                if (
                    _project is not None
                    and isinstance(getattr(_project, "description", None), str)
                    and _project.description.strip()
                    and isinstance(getattr(_project, "name", None), str)
                ):
                    _project_preamble = (
                        f"--- Project: {_project.name} ---\n"
                        f"{_project.description.strip()}\n"
                        f"--- End Project Context ---"
                    )
    except Exception:
        logger.debug("AD-793: project preamble lookup failed", exc_info=True)
    if _project_preamble is not None:
        message_text = f"{_project_preamble}\n\n{message_text}"

    # AD-733a (Wave 171): prepend the agent's current visual context.
    # Confabulation guard (BF-294 lesson): render_for_prompt returns a
    # non-empty "no data" sentinel when the buffer is empty, so the agent
    # never silently invents a scene. Tier-2 — failure logs at debug and
    # drops the visual block; the DM still goes through. The injection is
    # gated on perception.enabled so disabling the subsystem cleanly
    # removes the block from every DM (BF-294: silent-omit is acceptable
    # when the subsystem is off; the agent has no vision expectation).
    try:
        _perception_cfg = getattr(getattr(runtime, "config", None), "perception", None)
        if _perception_cfg is not None and getattr(_perception_cfg, "enabled", False):
            # AD-733c-1: force-describe the latest captured frame before
            # rendering the scene block. Best-effort + bounded (4s timeout
            # via VisionConsumer.force_describe_current_frame). When the
            # cache is empty or the LLM is slow, we silently fall back to
            # whatever the WM already contains.
            _consumer = getattr(runtime, "vision_consumer", None)
            if _consumer is not None and getattr(
                _perception_cfg, "dm_force_describe_enabled", True,
            ):
                try:
                    await _consumer.force_describe_current_frame(timeout_s=4.0)
                except Exception:
                    logger.debug(
                        "AD-733c-1: force_describe raised for %s",
                        agent_id, exc_info=True,
                    )
            # AD-733c-2: notify the mode controller of DM activity so the
            # AMBIENT -> ENGAGED transition (and ENGAGED freshness) tracks
            # the real conversational tempo.
            _mode_ctrl = getattr(runtime, "perception_mode_controller", None)
            # AD-733c-5: prefer per-agent controller via the registry so
            # DMs to one agent don't transition the whole mesh.
            _engagement = getattr(runtime, "perception_engagement_registry", None)
            if _engagement is not None:
                _per_agent_ctrl = _engagement.get(agent_id)
                if _per_agent_ctrl is not None:
                    _mode_ctrl = _per_agent_ctrl
            if _mode_ctrl is not None:
                try:
                    _mode_ctrl.note_dm_activity()
                except Exception:
                    logger.debug(
                        "AD-733c-2: note_dm_activity raised", exc_info=True,
                    )
            from probos.perception.consumer import get_or_create_working_memory
            _wm = get_or_create_working_memory(agent_id)
            _scene_block = _wm.render_for_prompt()
            if _scene_block:
                message_text = f"{_scene_block}\n\n{message_text}"
    except Exception:
        logger.debug(
            "AD-733a: scene-context injection failed for %s",
            agent_id, exc_info=True,
        )
    _params: dict[str, object] = {
        "text": message_text,
        "from": "hxi_profile",
        "session": bool(req.history),
        "session_history": req.history[-10:] if req.history else [],
    }
    # AD-730: thread vision messages through to the agent's LLM-call site.
    # When present, the agent routes to attachments.vision_tier with
    # LLMRequest(messages=vision_messages); otherwise the standard text path.
    if vision_messages is not None:
        _params["vision_messages"] = vision_messages
        _params["has_image_attachment"] = True
    intent = IntentMessage(
        intent="direct_message",
        params=_params,
        target_agent_id=agent_id,
        ttl_seconds=60.0,  # AD-636: Extended TTL for Captain DMs
        thread_id=thread.id if thread is not None else None,  # AD-791a
    )

    # AD-722 BF (2026-05-10): refresh self-avatar snapshot before the agent
    # perceives the DM, so the INTEROCEPTION sensorium block has fresh data
    # when prompt assembly runs. Tier-2 log-and-degrade — telemetry must
    # never block a reply. No-op when avatar_telemetry.enabled is False
    # (build_telemetry_snapshot itself short-circuits gracefully).
    #
    # AD-722f: bracket the DM with HIGH-tier sampling. enter_dm here;
    # exit_dm fires at the mark_reply_emitted site below. The exit is
    # ALSO guaranteed by the spurious-exit clamp in the state machine,
    # so an exception path between enter and exit cannot leak refcount
    # permanently — at worst, the next mark_reply_emitted clamps to 0.
    _sampling_state = getattr(runtime, 'avatar_sampling_state', None)
    _avatar_event_bus = getattr(runtime, 'avatar_event_bus', None)
    if _sampling_state is not None:
        _sampling_state.enter_dm(agent_id)
    if _avatar_event_bus is not None:
        # AD-722b: wake WS publish loop — DM in-flight is a state change.
        _avatar_event_bus.notify(agent_id)
    if hasattr(agent, 'observe_self_avatar'):
        try:
            await agent.observe_self_avatar()
        except Exception:
            logger.debug(
                "AD-722: self-avatar snapshot refresh failed for %s; "
                "INTEROCEPTION block will use stale or empty data",
                agent_id,
                exc_info=True,
            )

    result = await runtime.intent_bus.send(intent)

    callsign = ""
    if hasattr(runtime, 'callsign_registry'):
        callsign = runtime.callsign_registry.get_callsign(agent.agent_type)

    response_text = ""
    if result and result.result:
        response_text = str(result.result)
    elif result and result.error:
        response_text = f"(error: {result.error})"
    elif result is None:
        # BF-289: intent bus returned no result envelope — handler timed out or
        # the agent has no subscriber for ``direct_message``. Distinct from the
        # empty-content path so the Captain can tell "DM never reached the
        # agent" from "agent's LLM tier returned empty content."
        response_text = "(no reply — agent did not respond to intent)"
        logger.warning(
            "BF-289: agent=%s direct_message returned no IntentResult — "
            "either no subscriber registered or handler timed out",
            agent_id,
        )
    else:
        # BF-289: result envelope present but ``result.result`` is empty AND
        # ``result.error`` is empty. Almost always: the agent's LLM tier
        # endpoint (Copilot proxy, local Ollama, etc.) returned an empty
        # completion. Surface that explicitly so the Captain knows to check
        # upstream rather than chasing an in-runtime bug.
        response_text = (
            "(no reply — agent's LLM endpoint returned empty content; "
            "check upstream proxy/endpoint at the configured tier)"
        )

    # BF-622: strip any echoed visual-context scaffolding from the 1:1 reply
    # (same risk as the group path — a degraded LLM proxy can echo its input,
    # which AD-733a prepends the scene block to). Guarded on the marker so a
    # normal reply is untouched; an emptied reply degrades to a non-reply note.
    if "Current Visual Context" in response_text:
        from probos.perception.working_memory import strip_visual_context_block
        response_text = strip_visual_context_block(response_text) or (
            "(no reply — agent's LLM endpoint returned empty content; "
            "check upstream proxy/endpoint at the configured tier)"
        )
        logger.warning(
            "BF-289: agent=%s direct_message returned empty content "
            "(no error, no result) — likely LLM endpoint issue at the "
            "agent's configured tier (Copilot proxy at 127.0.0.1:8080 by default)",
            agent_id,
        )

    # AD-726: post-LLM cleanup pipeline (AD-724/AD-572/AD-430b/AD-573/AD-722a/
    # AD-722f/AD-722b/AD-738e-1 cascade extracted into DmReplyPipeline). Each
    # step preserves its prior Tier-2 boundary; the top-level run() guard is
    # belt-and-braces. Behavior is byte-identical to pre-AD-726 inline form.
    # ``sanity_gate`` is resolved here (NOT inside the pipeline) so that step_1
    # AND step_2/step_3 (which also call extract_challenge / extract_move) all
    # see the same instance via ``self.ctx.sanity_gate``.
    sanity_gate = getattr(runtime, "dm_sanity_gate", None)
    from probos.cognitive.dm import DmReplyContext, DmReplyPipeline
    pipeline = DmReplyPipeline(DmReplyContext(
        runtime=runtime,
        agent=agent,
        agent_id=agent_id,
        callsign=callsign,
        req_message=req.message,
        response_text=response_text,
        has_image_attachment=has_image_attachment,
        per_attachment=per_attachment,
        sanity_gate=sanity_gate,
        params=_params,
        message_text=message_text,
        sampling_state=_sampling_state,
        avatar_event_bus=_avatar_event_bus,
        chat_thread_id=thread.id if thread is not None else "",  # AD-791a
    ))
    await pipeline.run()
    response = pipeline.build_response()
    # AD-791a: append the agent's reply to the thread message log and
    # surface the thread_id on the response dict. Both steps are
    # log-and-degrade so an outage in the thread store cannot block a
    # successful DM round-trip.
    if thread is not None:
        try:
            _thread_store.append_message(
                thread.id,
                author_id=agent_id,
                role="agent",
                body=response.get("response", "") or "",
                metadata={"intent_id": intent.id},
            )
        except Exception:
            logger.warning(
                "AD-791a: append agent reply failed for thread=%s agent=%s",
                thread.id, agent_id, exc_info=True,
            )
        response["thread_id"] = thread.id
        # AD-794: surface the current thread title on the response so
        # the UI can update its chatThreads map without an extra
        # /api/threads/{id} round-trip. Cheap — already in memory.
        response["title"] = thread.title
    return response


@router.get("/{agent_id}/chat/history")
async def agent_chat_history(agent_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Recall past 1:1 interactions with this agent for session seeding."""
    memories: list[dict[str, str]] = []
    if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
        try:
            from probos.cognitive.episodic import resolve_sovereign_id
            agent = runtime.registry.get(agent_id)
            sovereign_id = resolve_sovereign_id(agent) if agent else agent_id
            episodes = await runtime.episodic_memory.recall_for_agent(
                sovereign_id, "1:1 conversation with Captain", k=3
            )
            if not episodes and hasattr(runtime.episodic_memory, 'recent_for_agent'):
                episodes = await runtime.episodic_memory.recent_for_agent(
                    sovereign_id, k=3
                )
            for ep in episodes:
                memories.append({
                    "role": "system",
                    "text": f"[Previous conversation] {ep.user_input}",
                })
        except Exception:
            logger.debug("Failed to load HXI conversation history", exc_info=True)
    return {"memories": memories}


@router.get("/{agent_id}/journal")
async def agent_journal(
    agent_id: str, limit: int = 20,
    since: float | None = None, until: float | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-431: Agent reasoning chain from Cognitive Journal."""
    if not runtime.cognitive_journal:
        return {"entries": []}
    entries = await runtime.cognitive_journal.get_reasoning_chain(
        agent_id, limit=min(limit, 100), since=since, until=until,
    )
    return {"agent_id": agent_id, "entries": entries}


@router.get("/{agent_id}/working-memory")
async def agent_working_memory(
    agent_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-645: Return agent's working memory state including composition briefs."""
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    wm = getattr(agent, '_working_memory', None)
    if wm is None:
        return {"agent_id": agent_id, "working_memory": None}

    return {"agent_id": agent_id, "working_memory": wm.to_dict()}
