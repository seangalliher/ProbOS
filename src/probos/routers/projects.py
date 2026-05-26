"""AD-793 (Wave 196): REST routes for the Projects substrate.

Projects are long-lived context groups owning N chat threads + pinned
attachment refs. Mirrors Claude "Projects" + Teams "channels under a
team" affordances. The description injects as a per-turn system-message
preamble to every chat inside a contained thread (see ``routers/agents``
AD-793 block; order is ``visual → project → recall → user``).

Endpoints:
    GET    /api/projects                        — list
    POST   /api/projects                        — create
    GET    /api/projects/{id}                   — fetch one
    PATCH  /api/projects/{id}                   — update (name/description/archived)
    DELETE /api/projects/{id}?cascade=false     — delete (default: unparent threads)
    POST   /api/projects/{id}/pin               — pin an attachment SHA
    POST   /api/projects/{id}/unpin             — unpin an attachment SHA

Response shapes (matches Wave 195 review correction):
    single-project endpoints → ``Project.to_dict()`` DIRECTLY (no wrapper)
    list                     → ``{"projects": [...]}``
    delete                   → ``{"deleted": bool, "affected_threads": int, "cascade": bool}``
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _get_store(runtime: Any):
    store = getattr(runtime, "project_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Project store not available")
    return store


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    pinned_attachment_ids: list[str] = Field(default_factory=list)


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    archived: bool | None = None


class PinAttachmentRequest(BaseModel):
    attachment_id: str = Field(..., min_length=1, max_length=128)


@router.get("")
async def list_projects(
    include_archived: bool = False,
    limit: int = 100,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    projects = store.list_projects(
        include_archived=include_archived,
        limit=max(1, min(limit, 500)),
    )
    return {"projects": [p.to_dict() for p in projects]}


@router.post("")
async def create_project(
    body: CreateProjectRequest,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    project = store.create_project(
        name=body.name,
        description=body.description,
        pinned_attachment_ids=body.pinned_attachment_ids,
    )
    return project.to_dict()


@router.get("/{project_id}")
async def get_project(
    project_id: str, runtime: Any = Depends(get_runtime)
) -> dict:
    store = _get_store(runtime)
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.to_dict()


@router.patch("/{project_id}")
async def update_project(
    project_id: str,
    body: UpdateProjectRequest,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    project = store.update_project(
        project_id,
        name=body.name,
        description=body.description,
        archived=body.archived,
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project.to_dict()


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    cascade: bool = False,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    deleted, affected = store.delete_project(project_id, cascade=cascade)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "deleted": True,
        "affected_threads": affected,
        "cascade": cascade,
    }


@router.post("/{project_id}/pin")
async def pin_attachment(
    project_id: str,
    body: PinAttachmentRequest,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """AD-793: pin an attachment SHA to a project.

    Validates that the SHA exists in the AttachmentStore (400 when
    missing — the request was syntactically valid but the referenced
    data is unknown). ``AttachmentStore.exists()`` is async per
    ``attachments/store.py:60`` so this endpoint MUST be ``async def``
    and ``await`` the call.
    """
    store = _get_store(runtime)
    # Validate project first (404 trumps 400 — the operator picked a
    # non-existent project).
    project = store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Cross-router import (precedent at routers/avatars.py:55).
    from probos.routers.chat import _get_attachment_store
    attachment_store = _get_attachment_store(runtime)
    try:
        sha_exists = await attachment_store.exists(body.attachment_id)
    except Exception:
        logger.warning(
            "AD-793: AttachmentStore.exists raised for sha=%s; treating "
            "as missing and returning 400",
            body.attachment_id,
            exc_info=True,
        )
        sha_exists = False
    if not sha_exists:
        raise HTTPException(
            status_code=400,
            detail=f"Attachment {body.attachment_id} not found in store",
        )

    updated = store.pin_attachment(project_id, body.attachment_id)
    if updated is None:
        # Project vanished between get + pin (rare race).
        raise HTTPException(status_code=404, detail="Project not found")
    return updated.to_dict()


@router.post("/{project_id}/unpin")
async def unpin_attachment(
    project_id: str,
    body: PinAttachmentRequest,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    updated = store.unpin_attachment(project_id, body.attachment_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return updated.to_dict()
