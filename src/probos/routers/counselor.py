"""ProbOS API — Counselor routes (AD-503).

AD-903: every read here is a CONFIDENTIAL clinical access. All endpoints carry
the ``require_crew_scope`` dependency (pass-through while ``auth.crew_scope_token``
is empty — the single-operator HXI default, so behavior is byte-identical) plus
an optional ``as_agent_id``. An omitted ``as_agent_id`` is the Captain console
(full authority); a provided one is resolved against the registry and run
through the deny-by-default ``clinical_access`` gate. Per-target reads gate on
the subject agent; crew-wide reads gate on ``""`` (only Captain / counselor /
``clinical:*`` wildcard clear that bar). 403 on deny; every access is audited.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from probos.cognitive.clinical_access import clinical_access_for_caller
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/counselor", tags=["counselor"])


@router.get("/profiles")
async def list_profiles(
    as_agent_id: str = "",
    runtime: Any = Depends(get_runtime),
    _auth: None = Depends(require_crew_scope),
) -> Any:
    """List all cognitive profiles (summary view)."""
    _gate_clinical_access(
        runtime, as_agent_id=as_agent_id, target_agent_id="", query_type="clinical_profiles"
    )
    if not runtime._counselor_profile_store:
        return JSONResponse({"error": "Counselor not available"}, status_code=503)
    summary = await runtime._counselor_profile_store.get_crew_summary()
    return {"profiles": summary}


@router.get("/profile/{agent_id}")
async def get_profile(
    agent_id: str,
    as_agent_id: str = "",
    runtime: Any = Depends(get_runtime),
    _auth: None = Depends(require_crew_scope),
) -> Any:
    """Get detailed cognitive profile for an agent."""
    _gate_clinical_access(
        runtime, as_agent_id=as_agent_id, target_agent_id=agent_id, query_type="clinical_profile"
    )
    if not runtime._counselor_profile_store:
        return JSONResponse({"error": "Counselor not available"}, status_code=503)
    profile = await runtime._counselor_profile_store.load_profile(agent_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"No profile for {agent_id}")
    return profile.to_dict()


@router.get("/assessments/{agent_id}")
async def get_assessments(
    agent_id: str,
    limit: int = 20,
    as_agent_id: str = "",
    runtime: Any = Depends(get_runtime),
    _auth: None = Depends(require_crew_scope),
) -> Any:
    """Get assessment history for an agent."""
    _gate_clinical_access(
        runtime, as_agent_id=as_agent_id, target_agent_id=agent_id, query_type="clinical_assessments"
    )
    if not runtime._counselor_profile_store:
        return JSONResponse({"error": "Counselor not available"}, status_code=503)
    history = await runtime._counselor_profile_store.get_assessment_history(
        agent_id, limit=limit
    )
    return {"agent_id": agent_id, "assessments": [a.to_dict() for a in history]}


@router.get("/summary")
async def crew_summary(
    as_agent_id: str = "",
    runtime: Any = Depends(get_runtime),
    _auth: None = Depends(require_crew_scope),
) -> Any:
    """Get crew-wide wellness summary."""
    _gate_clinical_access(
        runtime, as_agent_id=as_agent_id, target_agent_id="", query_type="clinical_summary"
    )
    counselor = _get_counselor_agent(runtime)
    if not counselor:
        return JSONResponse({"error": "Counselor not available"}, status_code=503)
    profiles = counselor.all_profiles()
    red = sum(1 for p in profiles if p.alert_level == "red")
    yellow = sum(1 for p in profiles if p.alert_level == "yellow")
    green = sum(1 for p in profiles if p.alert_level == "green")
    return {
        "total": len(profiles),
        "red": red,
        "yellow": yellow,
        "green": green,
        "profiles": [
            {
                "agent_id": p.agent_id,
                "alert_level": p.alert_level,
                "last_assessed": p.last_assessed,
            }
            for p in profiles
        ],
    }


@router.get("/interventions")
async def get_interventions(
    as_agent_id: str = "",
    runtime: Any = Depends(get_runtime),
    _auth: None = Depends(require_crew_scope),
) -> dict[str, Any]:
    """Return Counselor intervention summary (AD-561)."""
    _gate_clinical_access(
        runtime, as_agent_id=as_agent_id, target_agent_id="", query_type="clinical_interventions"
    )
    counselor = _get_counselor_agent(runtime)
    if not counselor:
        return {"status": "no_counselor", "summary": {}, "recent": []}
    return {
        "summary": counselor.get_intervention_summary(),
        "recent": [
            {
                "type": r.intervention_type.value,
                "agent_id": r.agent_id,
                "callsign": r.callsign,
                "trigger": r.trigger,
                "severity": r.severity,
                "detail": r.detail,
                "timestamp": r.timestamp,
            }
            for r in counselor.get_intervention_history(limit=20)
        ],
    }


@router.post("/assess/{agent_id}")
async def assess_agent(
    agent_id: str,
    as_agent_id: str = "",
    runtime: Any = Depends(get_runtime),
    _auth: None = Depends(require_crew_scope),
) -> Any:
    """Trigger an on-demand assessment for a specific agent."""
    _gate_clinical_access(
        runtime, as_agent_id=as_agent_id, target_agent_id=agent_id, query_type="clinical_assess"
    )
    counselor = _get_counselor_agent(runtime)
    if not counselor:
        return JSONResponse({"error": "Counselor not available"}, status_code=503)
    agent = runtime.registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    metrics = counselor._gather_agent_metrics(agent_id)
    assessment = counselor.assess_agent(
        agent_id,
        current_trust=metrics["trust_score"],
        current_confidence=metrics["confidence"],
        hebbian_avg=metrics["hebbian_avg"],
        success_rate=metrics["success_rate"],
        personality_drift=metrics["personality_drift"],
        trigger="api",
    )
    # Persist
    if runtime._counselor_profile_store:
        profile = counselor.get_profile(agent_id)
        if profile:
            await runtime._counselor_profile_store.save_profile(profile)
        await runtime._counselor_profile_store.save_assessment(assessment)
    return assessment.to_dict()


@router.post("/sweep")
async def run_sweep(
    as_agent_id: str = "",
    runtime: Any = Depends(get_runtime),
    _auth: None = Depends(require_crew_scope),
) -> Any:
    """Trigger a full crew wellness sweep."""
    _gate_clinical_access(
        runtime, as_agent_id=as_agent_id, target_agent_id="", query_type="clinical_sweep"
    )
    counselor = _get_counselor_agent(runtime)
    if not counselor:
        return JSONResponse({"error": "Counselor not available"}, status_code=503)
    results = await counselor._run_wellness_sweep()
    return {
        "total_assessed": len(results),
        "assessments": [r.to_dict() for r in results],
    }


@router.get("/clinical/{agent_id}")
async def clinical_trends(
    agent_id: str,
    as_agent_id: str = "",
    trust_n: int = 20,
    zone_n: int = 20,
    sim_n: int = 20,
    assess_n: int = 10,
    runtime: Any = Depends(get_runtime),
    _auth: None = Depends(require_crew_scope),
) -> Any:
    """AD-903: gated clinical INDICATOR trend surface for one agent.

    Reads indicator stores ONLY (trust / cognitive-zone / self-similarity /
    hebbian-drift / duty) — never any agent's episodic store. 403 on access
    deny; each stream honest-degrades to []/null when its store is absent.
    """
    _gate_clinical_access(
        runtime, as_agent_id=as_agent_id, target_agent_id=agent_id, query_type="clinical_trend"
    )
    streams = _assemble_clinical_trends(
        runtime,
        agent_id,
        as_agent_id=as_agent_id,
        trust_n=trust_n,
        zone_n=zone_n,
        sim_n=sim_n,
        assess_n=assess_n,
    )
    return {"agent_id": agent_id, "streams": streams}


# --------------------------------------------------------------------------- #
# AD-904: confidential clinical notes (gated read/write)
# --------------------------------------------------------------------------- #


class _NoteWriteRequest(BaseModel):
    """Body for POST /notes/{agent_id} — the confidential note text."""

    body: str


@router.post("/notes/{agent_id}")
async def write_clinical_note(
    agent_id: str,
    payload: _NoteWriteRequest,
    as_agent_id: str = "",
    runtime: Any = Depends(get_runtime),
    _auth: None = Depends(require_crew_scope),
) -> Any:
    """AD-904: write a CONFIDENTIAL clinical note about ``agent_id`` (gated).

    Gate (fail-closed audit) → 503 when the store is absent → store-layer
    re-check (defense in depth) → write. Any store error fails closed (503) and
    never echoes the submitted body.
    """
    _gate_notes_access(
        runtime, as_agent_id=as_agent_id, target_agent_id=agent_id, query_type="notes_write"
    )
    store = getattr(runtime, "clinical_notes_store", None)
    if store is None:
        return JSONResponse(
            {"error": "Clinical notes store not available"}, status_code=503
        )
    _recheck_clinical_access(runtime, as_agent_id=as_agent_id, target_agent_id=agent_id)
    try:
        note = await store.write_note(
            target_agent_id=agent_id,
            author_agent_id=as_agent_id or "captain",
            body=payload.body,
        )
    except Exception:
        logger.error(
            "AD-904: clinical note write failed for %s; FAIL-CLOSED", agent_id,
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail="clinical_notes_unavailable")
    return {"id": note.id}


@router.get("/notes/{agent_id}")
async def list_clinical_notes(
    agent_id: str,
    limit: int = 50,
    as_agent_id: str = "",
    runtime: Any = Depends(get_runtime),
    _auth: None = Depends(require_crew_scope),
) -> Any:
    """AD-904: list CONFIDENTIAL clinical notes for ``agent_id`` (newest first).

    Gate (fail-closed audit) → 503 when the store is absent → store-layer
    re-check → list. A store error fails closed (503) and never leaks note
    bodies.
    """
    _gate_notes_access(
        runtime, as_agent_id=as_agent_id, target_agent_id=agent_id, query_type="notes_read"
    )
    store = getattr(runtime, "clinical_notes_store", None)
    if store is None:
        return JSONResponse(
            {"error": "Clinical notes store not available"}, status_code=503
        )
    _recheck_clinical_access(runtime, as_agent_id=as_agent_id, target_agent_id=agent_id)
    try:
        notes = await store.list_notes(agent_id, limit=limit)
    except Exception:
        logger.error(
            "AD-904: clinical note list failed for %s; FAIL-CLOSED", agent_id,
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail="clinical_notes_unavailable")
    return {"notes": [n.to_dict() for n in notes]}


@router.get("/notes/{agent_id}/{note_id}")
async def get_clinical_note(
    agent_id: str,
    note_id: str,
    as_agent_id: str = "",
    runtime: Any = Depends(get_runtime),
    _auth: None = Depends(require_crew_scope),
) -> Any:
    """AD-904: read one CONFIDENTIAL clinical note by id (gated).

    Gate (fail-closed audit) → 503 when the store is absent → store-layer
    re-check → fetch. 404 when the note is missing OR belongs to a different
    target (a caller gated for ``agent_id`` cannot read another crewman's note
    by id). A store error fails closed (503) and never leaks the body.
    """
    _gate_notes_access(
        runtime, as_agent_id=as_agent_id, target_agent_id=agent_id, query_type="notes_read"
    )
    store = getattr(runtime, "clinical_notes_store", None)
    if store is None:
        return JSONResponse(
            {"error": "Clinical notes store not available"}, status_code=503
        )
    _recheck_clinical_access(runtime, as_agent_id=as_agent_id, target_agent_id=agent_id)
    try:
        note = await store.get_note(note_id)
    except Exception:
        logger.error(
            "AD-904: clinical note get failed for %s; FAIL-CLOSED", note_id,
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail="clinical_notes_unavailable")
    if note is None or note.target_agent_id != agent_id:
        raise HTTPException(status_code=404, detail="clinical_note_not_found")
    return note.to_dict()


# --------------------------------------------------------------------------- #
# AD-903: clinical access gate + indicator trend assembler
# --------------------------------------------------------------------------- #


def _resolve_caller(runtime: Any, as_agent_id: str) -> tuple[str, str, bool]:
    """Resolve ``(caller_agent_id, caller_agent_type, is_captain)`` from the id.

    AD-722b-1 single-operator model: an omitted ``as_agent_id`` is the Captain
    console (same-origin, no token) → full authority. A provided id selects a
    crew role *within* the operator boundary; its ``agent_type`` is resolved
    from the registry for the deny-by-default ladder.
    """
    if not as_agent_id:
        return ("", "", True)
    agent_type = ""
    try:
        agent = runtime.registry.get(as_agent_id)
        if agent is not None:
            agent_type = getattr(agent, "agent_type", "") or ""
    except Exception:
        logger.debug(
            "AD-903: caller agent_type lookup failed for %s", as_agent_id, exc_info=True
        )
    return (as_agent_id, agent_type, False)


def _audit_clinical_access(
    runtime: Any,
    *,
    requester_agent_id: str,
    query_type: str,
    granted: bool,
    target_agent_id: str = "",
) -> None:
    """Append one clinical-access decision to the runtime audit ring (AD-903).

    Mirrors the ``ClinicalTelemetryService._record_audit`` entry shape. The ring
    is fail-safe — a missing/failing ring never blocks the access decision.
    """
    audit = getattr(runtime, "clinical_access_audit", None)
    if audit is None:
        return
    entry: dict[str, Any] = {
        "ts": time.time(),
        "requester_agent_id": requester_agent_id or "captain",
        "query_type": query_type,
        "granted": bool(granted),
        "result_count": 0,
    }
    if target_agent_id:
        entry["target_agent_id"] = target_agent_id
    try:
        audit.append(entry)
    except Exception:
        logger.debug("AD-903: clinical access audit append failed", exc_info=True)


def _gate_clinical_access(
    runtime: Any,
    *,
    as_agent_id: str,
    target_agent_id: str,
    query_type: str,
) -> None:
    """Resolve clinical access, audit the decision, and raise 403 on deny.

    The single gate for every clinical read. Per-target reads pass the subject
    ``target_agent_id``; crew-wide reads pass ``""`` (only the Captain, a
    counselor-role caller, or a ``clinical:*`` wildcard grant clear that bar —
    a per-target grant cannot unlock crew-wide).
    """
    caller_id, caller_type, is_captain = _resolve_caller(runtime, as_agent_id)
    decision = clinical_access_for_caller(
        caller_agent_id=caller_id,
        caller_agent_type=caller_type,
        target_agent_id=target_agent_id,
        is_captain=is_captain,
        grant_store=getattr(runtime, "clearance_grant_store", None),
    )
    _audit_clinical_access(
        runtime,
        requester_agent_id=caller_id,
        query_type=query_type,
        granted=decision.allowed,
        target_agent_id=target_agent_id,
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail="clinical_access_denied")


def _audit_notes_access_strict(
    runtime: Any,
    *,
    requester_agent_id: str,
    query_type: str,
    granted: bool,
    target_agent_id: str = "",
) -> None:
    """Append one clinical-notes access decision to the audit ring — FAIL CLOSED.

    Reuses the AD-903 ``runtime.clinical_access_audit`` deque and the
    ``ClinicalTelemetryService._record_audit`` entry shape, but — unlike the
    AD-903 fail-SAFE ``_audit_clinical_access`` — a CONFIDENTIAL *note* access
    that cannot be recorded is DENIED, not silently allowed: a missing ring or a
    failing append raises ``HTTPException(503)`` so no note body is ever served
    on an unauditable path.
    """
    audit = getattr(runtime, "clinical_access_audit", None)
    if audit is None:
        logger.error(
            "AD-904: clinical_access_audit ring absent; FAIL-CLOSED deny "
            "(requester=%s target=%s)",
            requester_agent_id,
            target_agent_id,
        )
        raise HTTPException(status_code=503, detail="clinical_notes_unavailable")
    entry: dict[str, Any] = {
        "ts": time.time(),
        "requester_agent_id": requester_agent_id or "captain",
        "query_type": query_type,
        "granted": bool(granted),
        "result_count": 0,
    }
    if target_agent_id:
        entry["target_agent_id"] = target_agent_id
    try:
        audit.append(entry)
    except Exception:
        logger.error(
            "AD-904: clinical notes audit append failed; FAIL-CLOSED deny",
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail="clinical_notes_unavailable")


def _gate_notes_access(
    runtime: Any,
    *,
    as_agent_id: str,
    target_agent_id: str,
    query_type: str,
) -> None:
    """Resolve clinical-notes access, audit (fail-closed), and 403 on deny.

    The router-layer gate for every confidential-notes read/write. Reuses the
    AD-903 ``_resolve_caller`` + ``clinical_access_for_caller`` ladder (so the
    subject-never-reads-own and grant rungs are identical to the indicator
    surface) but pairs it with the STRICT, fail-closed notes audit — a
    CONFIDENTIAL note must be recorded or denied. The AD-903
    ``_gate_clinical_access`` (fail-safe audit) is deliberately NOT reused here:
    note *bodies* demand a stricter audit posture than the indicator trends.
    """
    caller_id, caller_type, is_captain = _resolve_caller(runtime, as_agent_id)
    decision = clinical_access_for_caller(
        caller_agent_id=caller_id,
        caller_agent_type=caller_type,
        target_agent_id=target_agent_id,
        is_captain=is_captain,
        grant_store=getattr(runtime, "clearance_grant_store", None),
    )
    _audit_notes_access_strict(
        runtime,
        requester_agent_id=caller_id,
        query_type=query_type,
        granted=decision.allowed,
        target_agent_id=target_agent_id,
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail="clinical_access_denied")


def _recheck_clinical_access(
    runtime: Any,
    *,
    as_agent_id: str,
    target_agent_id: str,
) -> None:
    """Store-layer defense-in-depth re-check (AD-904) — 403 on deny, NO audit.

    Re-resolves the deny-by-default ladder immediately before touching the notes
    store, refusing a denied caller even if the router-level gate were bypassed.
    No audit row here — the single audit entry is owned by ``_gate_notes_access``
    (mirrors the re-check inside ``_assemble_clinical_trends``).
    """
    caller_id, caller_type, is_captain = _resolve_caller(runtime, as_agent_id)
    decision = clinical_access_for_caller(
        caller_agent_id=caller_id,
        caller_agent_type=caller_type,
        target_agent_id=target_agent_id,
        is_captain=is_captain,
        grant_store=getattr(runtime, "clearance_grant_store", None),
    )
    if not decision.allowed:
        raise HTTPException(status_code=403, detail="clinical_access_denied")


def _assemble_clinical_trends(
    runtime: Any,
    agent_id: str,
    *,
    as_agent_id: str,
    trust_n: int,
    zone_n: int,
    sim_n: int,
    assess_n: int,
) -> dict[str, Any]:
    """Assemble the five INDICATOR trend streams for one agent (AD-903).

    Reads trust / cognitive-zone / self-similarity / hebbian-drift / duty
    stores EXCLUSIVELY — never touches any agent's episodic store. Each stream
    honest-degrades to []/null when its store is absent.
    """
    # Defense in depth: re-resolve the gate and refuse a denied caller even if
    # this is reached without the router-level gate. No audit here — the single
    # audit row is owned by ``_gate_clinical_access`` at the router.
    caller_id, caller_type, is_captain = _resolve_caller(runtime, as_agent_id)
    recheck = clinical_access_for_caller(
        caller_agent_id=caller_id,
        caller_agent_type=caller_type,
        target_agent_id=agent_id,
        is_captain=is_captain,
        grant_store=getattr(runtime, "clearance_grant_store", None),
    )
    if not recheck.allowed:
        raise HTTPException(status_code=403, detail="clinical_access_denied")

    streams: dict[str, Any] = {}

    # (1) Trust event window + raw Beta parameters.
    trust_stream: dict[str, Any] = {"events": [], "raw": None}
    trust_network = getattr(runtime, "trust_network", None)
    if trust_network is not None:
        try:
            events = trust_network.get_events_for_agent(agent_id, n=trust_n)
            trust_stream["events"] = [
                {
                    "timestamp": e.timestamp,
                    "success": e.success,
                    "old_score": e.old_score,
                    "new_score": e.new_score,
                    "intent_type": e.intent_type,
                }
                for e in events
            ]
            trust_stream["raw"] = trust_network.raw_scores().get(agent_id)
        except Exception:
            logger.debug("AD-903: trust stream failed for %s", agent_id, exc_info=True)
    streams["trust"] = trust_stream

    # (2) Cognitive-zone history (via the proactive loop's public breaker).
    zones: list[dict[str, Any]] = []
    proactive_loop = getattr(runtime, "proactive_loop", None)
    if proactive_loop is not None:
        try:
            breaker = proactive_loop.circuit_breaker
            zones = [
                {"zone": z, "timestamp": t}
                for z, t in breaker.get_zone_history(agent_id, n=zone_n)
            ]
        except Exception:
            logger.debug("AD-903: zone stream failed for %s", agent_id, exc_info=True)
    streams["zones"] = zones

    # (3) Self-similarity history ring.
    self_sim: list[dict[str, Any]] = []
    history = getattr(runtime, "self_similarity_history", None)
    if history is not None:
        try:
            self_sim = [
                {"timestamp": ts, "similarity": sim}
                for ts, sim in history.recent(agent_id, n=sim_n)
            ]
        except Exception:
            logger.debug(
                "AD-903: self-similarity stream failed for %s", agent_id, exc_info=True
            )
    streams["self_similarity"] = self_sim

    # (4) Hebbian drift trend + recent assessments (Counselor profile).
    hebbian: dict[str, Any] = {"drift_trend": None, "assessments": []}
    counselor = _get_counselor_agent(runtime)
    if counselor is not None:
        try:
            profile = counselor.get_profile(agent_id)
            if profile is not None:
                hebbian["drift_trend"] = profile.drift_trend("hebbian_drift")
                hebbian["assessments"] = [
                    a.to_dict() for a in profile.assessments[-assess_n:]
                ]
        except Exception:
            logger.debug(
                "AD-903: hebbian drift stream failed for %s", agent_id, exc_info=True
            )
    streams["hebbian_drift"] = hebbian

    # (5) Duty execution/outcome surface.
    duty: dict[str, Any] = {
        "execution_count": 0,
        "last_executed": 0.0,
        "success_rate": None,
    }
    tracker = getattr(runtime, "duty_schedule_tracker", None)
    if tracker is not None:
        try:
            agent = runtime.registry.get(agent_id)
            agent_type = getattr(agent, "agent_type", "") if agent is not None else ""
            if agent_type:
                statuses = tracker.get_status(agent_type)
                duty["execution_count"] = sum(
                    int(s.get("execution_count", 0)) for s in statuses
                )
                duty["last_executed"] = max(
                    (float(s.get("last_executed", 0.0)) for s in statuses), default=0.0
                )
                duty["success_rate"] = tracker.success_rate(agent_type)
        except Exception:
            logger.debug("AD-903: duty stream failed for %s", agent_id, exc_info=True)
    streams["duty"] = duty

    return streams


def _get_counselor_agent(runtime: Any) -> Any:
    """Get the counselor agent from the pool."""
    if "counselor" not in runtime.pools:
        return None
    agents = runtime.registry.get_by_pool("counselor")
    return agents[0] if agents else None
