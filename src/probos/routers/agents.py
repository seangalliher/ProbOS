"""ProbOS API — Agent routes (AD-406, AD-430b, AD-431, AD-441, AD-497)."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from probos.api_models import AgentChatRequest, SetCooldownRequest
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
            memory_count = await runtime.episodic_memory.count_for_agent(agent.id)

    # BF-017: Only crew agents get personality and proactive controls
    is_crew = is_crew_agent(agent, runtime.ontology)

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

    # AD-430b: Store HXI 1:1 interaction as episodic memory
    if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
        try:
            import time as _time
            from probos.types import Episode
            episode = Episode(
                user_input=f"[1:1 with {callsign or agent_id}] Captain: {req.message}",
                timestamp=_time.time(),
                agent_ids=[agent_id],
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
            )
            await runtime.episodic_memory.store(episode)
        except Exception:
            logger.debug("Failed to store HXI conversation episode", exc_info=True)

    return {
        "response": response_text,
        "callsign": callsign,
        "agentId": agent_id,
    }


@router.get("/{agent_id}/chat/history")
async def agent_chat_history(agent_id: str, runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Recall past 1:1 interactions with this agent for session seeding."""
    memories: list[dict[str, str]] = []
    if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
        try:
            episodes = await runtime.episodic_memory.recall_for_agent(
                agent_id, "1:1 conversation with Captain", k=3
            )
            if not episodes and hasattr(runtime.episodic_memory, 'recent_for_agent'):
                episodes = await runtime.episodic_memory.recent_for_agent(
                    agent_id, k=3
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
