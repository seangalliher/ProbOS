"""ProbOS API — Agent routes (AD-406, AD-430b, AD-431, AD-441, AD-497)."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from probos.api_models import (
    AgentChatRequest,
    ProposeAppearanceRequest,
    ProposeAppearanceResponse,
    ProposeVoiceProfileRequest,
    ProposeVoiceProfileResponse,
    SetAppearanceRequest,
    SetCooldownRequest,
    SetVoiceProfileRequest,
)
from probos.config import format_trust
from probos.crew_utils import is_crew_agent
from probos.routers.deps import get_runtime

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
    """AD-721d D7: trigger ``CognitiveAgent.propose_appearance`` and return the
    proposed DSL for Captain review. NOT persisted — caller must follow up with
    ``PUT /{agent_id}/appearance`` once the Captain approves.
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

    from probos.avatars.dsl import AppearanceProposalError

    captain_note = (req.captain_note if req else "") or ""
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
    return {"agent_id": agent_id, "dsl": dsl.model_dump()}


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

    return {"agentId": agent_id, "dsl": dsl.model_dump()}


@router.get("/{agent_id}/avatar-telemetry")
async def agent_avatar_telemetry(agent_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
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


@router.post("/{agent_id}/chat")
async def agent_chat(agent_id: str, req: AgentChatRequest, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Send a direct message to a specific agent and get their response."""
    agent = runtime.registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    if not is_crew_agent(agent, runtime.ontology):
        raise HTTPException(status_code=400, detail=f"Agent {agent_id} is not a crew agent — direct chat is crew-only")

    from probos.types import IntentMessage
    intent = IntentMessage(
        intent="direct_message",
        params={
            "text": req.message,
            "from": "hxi_profile",
            "session": bool(req.history),
            "session_history": req.history[-10:] if req.history else [],
        },
        target_agent_id=agent_id,
        ttl_seconds=60.0,  # AD-636: Extended TTL for Captain DMs
    )

    # AD-722 BF (2026-05-10): refresh self-avatar snapshot before the agent
    # perceives the DM, so the INTEROCEPTION sensorium block has fresh data
    # when prompt assembly runs. Tier-2 log-and-degrade — telemetry must
    # never block a reply. No-op when avatar_telemetry.enabled is False
    # (build_telemetry_snapshot itself short-circuits gracefully).
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
    else:
        response_text = "(no response)"

    # BF-120: Strip markdown formatting that wraps structured tags.
    # LLMs sometimes emit **[COMMAND ...]** or `[COMMAND ...]` which
    # prevents regex patterns from matching.
    if response_text:
        response_text = re.sub(r'[`*]{1,3}\[', '[', response_text)
        response_text = re.sub(r'\][`*]{1,3}', ']', response_text)

    # BF-119: Parse [CHALLENGE @callsign game_type] from DM response
    if response_text and hasattr(runtime, 'recreation_service') and runtime.recreation_service:
        challenge_match = re.search(r'\[CHALLENGE\s+@(\w+)\s+(\w+)\]', response_text)
        if challenge_match:
            target_callsign = challenge_match.group(1)
            game_type = challenge_match.group(2)
            try:
                rec_svc = runtime.recreation_service
                # Resolve target callsign
                target_agent = None
                if hasattr(runtime, 'callsign_registry'):
                    target_agent = runtime.callsign_registry.resolve(target_callsign)
                if target_agent:
                    # Create Recreation channel thread
                    thread_id = ""
                    if runtime.ward_room:
                        channels = await runtime.ward_room.list_channels()
                        rec_ch = next((c for c in channels if c.name == "Recreation"), None)
                        if rec_ch:
                            thread = await runtime.ward_room.create_thread(
                                channel_id=rec_ch.id,
                                author_id=agent_id,
                                title=f"[Challenge] {callsign} challenges {target_callsign} to {game_type}!",
                                body=f"{callsign} has challenged {target_callsign} to a game of {game_type}! Reply to accept.",
                                author_callsign=callsign,
                            )
                            thread_id = thread.id if thread else ""
                    game_info = await rec_svc.create_game(
                        game_type=game_type,
                        challenger=callsign,
                        opponent=target_callsign,
                        thread_id=thread_id,
                    )
                    logger.info("BF-119: %s challenged %s to %s via DM (game %s)",
                                callsign, target_callsign, game_type, game_info["game_id"])
                    # Register game engagement in working memory
                    try:
                        wm = getattr(agent, 'working_memory', None)
                        if wm:
                            from probos.cognitive.agent_working_memory import ActiveEngagement
                            wm.add_engagement(ActiveEngagement(
                                engagement_type="game",
                                engagement_id=game_info["game_id"],
                                summary=f"Playing {game_type} against {target_callsign}",
                                state={
                                    "game_type": game_type,
                                    "opponent": target_callsign,
                                },
                            ))
                    except Exception:
                        logger.debug("BF-119: Working memory game engagement record failed", exc_info=True)
                else:
                    logger.debug("BF-119: Target callsign %s not found", target_callsign)
            except Exception as e:
                logger.warning("BF-119: DM game challenge failed for %s: %s", callsign, e)
            # Strip [CHALLENGE] tag from response text shown to Captain
            response_text = re.sub(r'\[CHALLENGE\s+@\w+\s+\w+\]', '', response_text).strip()

    # AD-572: Parse [MOVE pos] from DM response and execute against RecreationService
    game_move_result = None
    if response_text and hasattr(runtime, 'recreation_service') and runtime.recreation_service:
        move_match = re.search(r'\[MOVE\s+(\S+)\]', response_text)
        if move_match:
            position = move_match.group(1)
            try:
                rec_svc = runtime.recreation_service
                game = rec_svc.get_game_by_player(callsign)
                if game:
                    game_move_result = await rec_svc.make_move(
                        game_id=game["game_id"],
                        player=callsign,
                        move=position,
                    )
                    # Post board update to Ward Room thread (same as proactive path)
                    if runtime.ward_room and game.get("thread_id"):
                        try:
                            result_info = game_move_result.get("result")
                            if result_info:
                                body = f"Game over! {'Winner: ' + result_info.get('winner', '') if result_info.get('winner') else 'Draw!'}"
                            else:
                                board = rec_svc.render_board(game["game_id"])
                                body = f"```\n{board}\n```\nNext: {game_move_result['state']['current_player']}"
                            await runtime.ward_room.create_post(
                                thread_id=game["thread_id"],
                                author_id=agent_id,
                                body=body,
                                author_callsign=callsign,
                            )
                        except Exception:
                            logger.debug("AD-572: Board update post failed", exc_info=True)
            except Exception as e:
                logger.warning("AD-572: DM game move failed for %s: %s", callsign, e)

            # Strip [MOVE] tag from response text shown to Captain
            response_text = re.sub(r'\[MOVE\s+\S+\]', '', response_text).strip()

    # AD-430b: Store HXI 1:1 interaction as episodic memory
    if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
        try:
            import time as _time
            from probos.cognitive.episodic import resolve_sovereign_id
            from probos.types import AnchorFrame, Episode
            sovereign_id = resolve_sovereign_id(agent)
            episode = Episode(
                user_input=f"[1:1 with {callsign or agent_id}] Captain: {req.message}",
                timestamp=_time.time(),
                agent_ids=[sovereign_id],
                outcomes=[{
                    "intent": "direct_message",
                    "success": True,
                    "response": response_text[:500],
                    "session_type": "1:1",
                    "callsign": callsign,
                    "source": "hxi_profile",
                    "agent_type": agent.agent_type,
                }],
                reflection=f"Captain had a 1:1 conversation with {callsign or agent_id} via HXI.",
                source="direct",
                anchors=AnchorFrame(
                    channel="dm",
                    trigger_type="direct_message",
                    trigger_agent="captain",
                    participants=["captain", callsign or agent_id],
                ),
            )
            await runtime.episodic_memory.store(episode)
        except Exception:
            logger.debug("Failed to store HXI conversation episode", exc_info=True)

    # AD-573: Record DM conversation to agent's working memory
    try:
        wm = getattr(agent, 'working_memory', None)
        if wm:
            captain_text = req.message[:100] if req.message else ""
            wm.record_conversation(
                f"Captain DM: '{captain_text}' → responded",
                partner="Captain",
                source="dm",
            )
    except Exception:
        logger.debug("AD-573: Working memory DM record failed", exc_info=True)

    # AD-722: stamp the last-reply emission timestamp. Single source of truth.
    if hasattr(agent, 'mark_reply_emitted'):
        agent.mark_reply_emitted()

    response = {
        "response": response_text,
        "callsign": callsign,
        "agentId": agent_id,
    }
    if game_move_result:
        response["gameMoveExecuted"] = True
        response["gameStatus"] = game_move_result.get("state", {}).get("status", "")
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
