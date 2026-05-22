"""AD-797: REST routes for the artifacts pane."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from probos.routers.deps import get_runtime

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


def _get_store(runtime: Any):
    store = getattr(runtime, "artifact_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Artifact store not available")
    return store


class AddArtifactRequest(BaseModel):
    thread_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=200)
    content_hash: str = Field(..., min_length=8, max_length=128)
    mime: str = Field(..., min_length=1, max_length=200)
    size_bytes: int = Field(..., ge=0)
    created_by: str = Field(..., min_length=1, max_length=128)


@router.post("")
async def add_artifact(body: AddArtifactRequest, runtime: Any = Depends(get_runtime)) -> dict:
    store = _get_store(runtime)
    a = store.add_version(
        thread_id=body.thread_id,
        name=body.name,
        content_hash=body.content_hash,
        mime=body.mime,
        size_bytes=body.size_bytes,
        created_by=body.created_by,
    )
    return a.to_dict()


@router.get("/thread/{thread_id}")
async def list_thread_artifacts(
    thread_id: str, runtime: Any = Depends(get_runtime)
) -> dict:
    store = _get_store(runtime)
    items = store.list_thread_latest(thread_id)
    return {"thread_id": thread_id, "artifacts": [a.to_dict() for a in items]}


@router.get("/thread/{thread_id}/name/{name}/versions")
async def list_versions(
    thread_id: str, name: str, runtime: Any = Depends(get_runtime)
) -> dict:
    store = _get_store(runtime)
    items = store.list_versions(thread_id=thread_id, name=name)
    return {"thread_id": thread_id, "name": name, "versions": [a.to_dict() for a in items]}


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str, runtime: Any = Depends(get_runtime)) -> dict:
    store = _get_store(runtime)
    a = store.get(artifact_id)
    if a is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return a.to_dict()


@router.delete("/{artifact_id}")
async def delete_artifact(
    artifact_id: str, runtime: Any = Depends(get_runtime)
) -> dict:
    store = _get_store(runtime)
    if not store.delete(artifact_id):
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"deleted": True, "artifact_id": artifact_id}
