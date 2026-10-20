"""AD-1343 S1 (#1595): the Captain's stop for one crew agent.

    GET  /api/stops                  the stops in force, with refusals counted by seam
    POST /api/stops/{agent_id}       stop one crew agent (slot id, certificate UUID or did:probos DID)
    POST /api/stops/{agent_id}/lift  lift it

Authority is the existing Captain authority on the API. ``require_crew_scope`` answers 401
to a missing or wrong bearer token once ``auth.crew_scope_token`` is set; because it lets
every caller through while no token is set, these routes answer 403 until one is (the
AD-1196 / AD-1340 rule: no Captain order through an open gate). Agent tools do not reach
them: ``security/url_guard.py`` refuses loopback to ``http_fetch`` and to every browser
context ProbOS creates. The residual is stated in the AD-1343 contract (C1): a shell or
sandbox run that could read ``config/system.yaml`` could present the token.

Every answer that reports an order carries ``scope`` (the list, a stop, a stop not written,
a lift): what S1 refuses and what it does not end. A refused request (401, 403, 404, 422,
or 503 for an absent service or a failed lift) carries its code only.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from probos.agent_stop import LIFT_NOTE, S1_SCOPE, AgentStopService, StopNotFound
from probos.crew_utils import is_crew_agent
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stops", tags=["agent-stop"])

_TOKEN_REQUIRED = "agent_stop_requires_crew_scope_token"
_UNAVAILABLE = "agent_stop_unavailable"


class AgentStopRequest(BaseModel):
    """The Captain's reason for a stop or a lift."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


async def _captain_stops(runtime: Any = Depends(get_runtime)) -> AgentStopService:
    """The stop service for a Captain order: 503 while absent, then 403 while no token is configured."""
    stops = getattr(runtime, "agent_stops", None)
    if not isinstance(stops, AgentStopService):
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)
    if not runtime.config.auth.crew_scope_token:  # AD-1343: never a Captain order through an open gate
        raise HTTPException(status_code=403, detail=_TOKEN_REQUIRED)
    return stops


def _slot_id(runtime: Any, agent_id: str) -> str:
    """The slot id an agent id, certificate UUID or did:probos DID names (BF-907 resolver)."""
    identities = getattr(runtime, "identity_registry", None)
    slot = identities.resolve_slot_id(agent_id) if identities is not None else None
    return slot or agent_id


def _enforceable(agent: Any) -> bool:
    """True when the agent's work entry points are the ones the stop guards."""
    from probos.cognitive.cognitive_agent import CognitiveAgent

    cls = type(agent)
    return (
        getattr(cls, "handle_intent", None) is CognitiveAgent.handle_intent
        and getattr(cls, "handle_consultation_request", None) is CognitiveAgent.handle_consultation_request
    )


@router.get("", dependencies=[Depends(require_crew_scope)])
async def list_agent_stops(stops: AgentStopService = Depends(_captain_stops)) -> dict[str, Any]:
    """The stops in force, oldest first, with refusals counted by seam since this start."""
    return {
        "stops": [
            {**record.public_dict(), "refused": stops.refused_counts(record.stop_id)}
            for record in stops.active()
        ],
        "scope": dict(S1_SCOPE),
    }


@router.post("/{agent_id}", dependencies=[Depends(require_crew_scope)])
async def issue_agent_stop(
    agent_id: str,
    req: AgentStopRequest,
    runtime: Any = Depends(get_runtime),
    stops: AgentStopService = Depends(_captain_stops),
) -> dict[str, Any]:
    """Stop one crew agent by the Captain's order (AD-1343 S1)."""
    slot = _slot_id(runtime, agent_id)
    agent = runtime.registry.get(slot)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent_not_found")
    if not is_crew_agent(agent, runtime.ontology):
        raise HTTPException(status_code=422, detail="not_crew")
    if not _enforceable(agent):
        raise HTTPException(status_code=422, detail="stop_not_enforceable")
    try:
        outcome = await stops.issue_stop(slot, reason=req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    body: dict[str, Any] = {
        "status": "stopped",
        "already_stopped": outcome.already_stopped,
        "stop": outcome.record.public_dict(),
        "scope": dict(S1_SCOPE),
    }
    if not outcome.durable:
        raise HTTPException(
            status_code=503,
            detail={**body, "code": "stop_not_durable", "applied_until_restart": True},
        )
    return body


@router.post("/{agent_id}/lift", dependencies=[Depends(require_crew_scope)])
async def lift_agent_stop(
    agent_id: str,
    req: AgentStopRequest,
    runtime: Any = Depends(get_runtime),
    stops: AgentStopService = Depends(_captain_stops),
) -> dict[str, Any]:
    """Lift the Captain's stop on one agent. Work refused while it was stopped is not replayed."""
    slot = _slot_id(runtime, agent_id)
    try:
        lifted = await stops.lift_stop(slot, reason=req.reason)
    except StopNotFound:
        raise HTTPException(status_code=404, detail="no_active_stop") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("AD-1343: the lift of %s's stop was not written; the agent stays stopped", slot, exc_info=True)
        raise HTTPException(status_code=503, detail="stop_store_write_failed") from exc
    return {
        "status": "lifted",
        "stop": lifted.record.public_dict(),
        "lifted_at": lifted.lifted_at,
        "refused_while_stopped": lifted.refused,
        "note": LIFT_NOTE,
        "scope": dict(S1_SCOPE),  # AD-1343 A2 (F5): every answer that reports an order carries scope
    }
