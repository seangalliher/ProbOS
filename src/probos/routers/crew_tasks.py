"""ProbOS API — Crew-collaboration surface (AD-862).

Thin router exposing a single crew-collaboration tree: a parent WorkItem plus
its fanned-out children, each with its **live persisted** ``status`` (which
alone drives the HXI motion — pulse while ``in_progress``, settle when
``done`` — per HXI Principle #4). Per-subtask ``verdict``/``rounds`` are NOT
persisted live (``SubtaskVerifier`` keeps them in-memory only, AD-860); they
exist only post-completion inside the AttachmentStore provenance blob written
at synthesis (AD-861), keyed by the parent's
``metadata["crew_synth"]["provenance_ref"]``. So this endpoint reads ONLY
persisted state: live ``status`` always; ``verdict``/``rounds`` attached only
when the parent is ``done`` (deref the provenance ref), else ``null``
(honest-degrade — in-progress, no ref, or no attachment store).

Backed by ``runtime.work_item_store`` (the WorkItem WBS) and
``runtime.attachment_store`` (the content-addressable provenance store). Reuses
the ``WorkItem.to_dict()`` serializer (DRY — same shape ``routers/workforce.py``
serves).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.crew_session_live import load_crew_session_projection
from probos.crew_session_projection import (
    CREW_SESSION_PROJECTION_ERROR,
    CrewSessionProjectionError,
)
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crew-tasks", tags=["crew-tasks"])


async def _provenance_by_work_item(runtime: Any, parent: Any) -> dict[str, Any]:
    """Deref the parent's synthesis provenance blob into a per-child index.

    Returns ``{work_item_id: subtask_dict}`` from the AD-861 provenance blob, or
    an empty dict when the parent is not ``done``, has no ``provenance_ref``, the
    attachment store is unwired, or the deref fails. Honest-degrade at every
    boundary — a missing/absent provenance ref must never crash the surface and
    must never fabricate a verdict.
    """
    if parent.status != "done":
        return {}
    crew_synth = (parent.metadata or {}).get("crew_synth") or {}
    ref = crew_synth.get("provenance_ref")
    if not ref:
        return {}
    store = runtime.attachment_store
    if store is None:
        logger.warning(
            "AD-862: parent %s is done with provenance_ref=%s but no attachment "
            "store is wired; verdict/rounds will be null (honest-degrade)",
            parent.id, ref,
        )
        return {}
    try:
        blob = await store.read(ref)
        prov = json.loads(blob)
    except FileNotFoundError:
        logger.warning(
            "AD-862: provenance blob %s for parent %s not found in the "
            "attachment store; verdict/rounds will be null (honest-degrade)",
            ref, parent.id,
        )
        return {}
    except Exception:
        logger.warning(
            "AD-862: failed to deref/parse provenance %s for parent %s; "
            "verdict/rounds will be null (honest-degrade)",
            ref, parent.id, exc_info=True,
        )
        return {}
    index: dict[str, Any] = {}
    for sub in prov.get("subtasks", []) or []:
        wid = sub.get("work_item_id")
        if wid:
            index[wid] = sub
    return index


def _verdict_from_subtask(sub: dict[str, Any]) -> dict[str, Any]:
    """Map an AD-861 provenance subtask record to the wire ``verdict`` shape.

    Reads only the REAL fields the AD-861 blob carries (``accepted``,
    ``confidence``, ``critique``, ``verifier_agent_id``); ``rounds`` is surfaced
    as a sibling key, not nested in the verdict.
    """
    return {
        "accepted": sub.get("accepted"),
        "confidence": sub.get("confidence"),
        "critique": sub.get("critique"),
        "verifier_agent_id": sub.get("verifier_agent_id"),
    }


@router.get("/{parent_id}")
async def get_crew_task(
    parent_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-862: Return a crew-collaboration tree (parent + children).

    Each node carries its live persisted ``status``. Per-subtask
    ``verdict``/``rounds`` are attached ONLY when the parent is ``done`` and a
    provenance ref derefs cleanly; otherwise they are ``null`` (honest-degrade).
    """
    if not runtime.work_item_store:
        raise HTTPException(status_code=503, detail="workforce engine not enabled")
    store = runtime.work_item_store
    parent = await store.get_work_item(parent_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="crew task not found")

    if parent.work_type == "crew_session":
        service = getattr(runtime, "crew_session_service", None)
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="CrewSession service not available",
            )
        try:
            loaded = await load_crew_session_projection(
                parent.id,
                crew_session_service=service,
                work_item_store=store,
            )
            detail = loaded.detail
            if detail.task_id != parent.id:
                raise CrewSessionProjectionError()
        except ValueError as exc:
            logger.warning(
                "AD-1132: CrewSession parent %s projection failed (%s); "
                "returning stable 409",
                parent.id,
                CREW_SESSION_PROJECTION_ERROR,
            )
            raise HTTPException(
                status_code=409,
                detail=CREW_SESSION_PROJECTION_ERROR,
            ) from exc
        return {"session": detail.to_wire()}

    children = await store.list_work_items(parent_id=parent_id, limit=1000)
    prov_index = await _provenance_by_work_item(runtime, parent)

    serialized_children: list[dict[str, Any]] = []
    for child in children:
        node = child.to_dict()
        sub = prov_index.get(child.id)
        if sub is not None:
            node["verdict"] = _verdict_from_subtask(sub)
            node["rounds"] = sub.get("rounds")
        else:
            node["verdict"] = None
            node["rounds"] = None
        serialized_children.append(node)

    return {
        "parent": parent.to_dict(),
        "children": serialized_children,
        "count": len(serialized_children),
    }
