"""AD-797: REST routes for the artifacts pane."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
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
    """AD-797 (Wave 197): native + project-pinned artifacts for a thread.

    Native artifacts (created in this thread) are returned with
    ``_pinned_from_project=False``. When the thread belongs to a
    project with ``pinned_attachment_ids``, additional artifacts whose
    ``content_hash`` matches a pinned SHA are appended with
    ``_pinned_from_project=True``. Native wins on collision: pinned
    SHAs that already appear in the native list are skipped. Pinned
    SHAs with no matching ``Artifact`` row (raw upload, not extracted)
    are skipped silently.

    Response shape remains HEAD-compatible:
    ``{"thread_id": ..., "artifacts": [...]}``.
    """
    store = _get_store(runtime)
    native = store.list_thread_latest(thread_id)
    native_dicts = [a.to_dict() for a in native]
    for d in native_dicts:
        d["_pinned_from_project"] = False

    pinned_dicts: list[dict] = []
    chat_thread_store = getattr(runtime, "chat_thread_store", None)
    project_store = getattr(runtime, "project_store", None)
    if chat_thread_store is not None and project_store is not None:
        thread = chat_thread_store.get_thread(thread_id)
        if thread is not None and getattr(thread, "project_id", None):
            project = project_store.get_project(thread.project_id)
            pinned_ids = getattr(project, "pinned_attachment_ids", None) or []
            if project is not None and pinned_ids:
                native_hashes = {d["content_hash"] for d in native_dicts}
                for sha in pinned_ids:
                    if sha in native_hashes:
                        continue  # native wins
                    matched = store.find_first_by_hash(sha)
                    if matched is None:
                        continue  # raw upload, no Artifact row — skip silently
                    d = matched.to_dict()
                    d["_pinned_from_project"] = True
                    pinned_dicts.append(d)

    return {"thread_id": thread_id, "artifacts": native_dicts + pinned_dicts}


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


@router.get("/{artifact_id}/content")
async def get_artifact_content(
    artifact_id: str, runtime: Any = Depends(get_runtime)
):
    """AD-797 (Wave 197): stream raw bytes for an artifact.

    Returns the AttachmentStore blob keyed by ``artifact.content_hash``
    with ``Content-Type`` from ``artifact.mime``. Used by the drawer
    viewer (markdown/code/image render) and the Captain's Save-to-file
    button. For ``mime='text/uri-list'`` the body IS the URL bytes; the
    UI dereferences to ``<img src>``.

    404 ``artifact_not_found`` when the row is missing; 404
    ``content_missing`` when the row exists but the AttachmentStore
    blob is gone (orphan — caller should refresh the list).
    """
    store = _get_store(runtime)
    a = store.get(artifact_id)
    if a is None:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    attachment_store = getattr(runtime, "attachment_store", None)
    if attachment_store is None:
        raise HTTPException(status_code=503, detail="attachment_store_unavailable")
    try:
        blob = await attachment_store.read(a.content_hash)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="content_missing")
    return Response(content=blob, media_type=a.mime)


@router.delete("/{artifact_id}")
async def delete_artifact(
    artifact_id: str, runtime: Any = Depends(get_runtime)
) -> dict:
    store = _get_store(runtime)
    if not store.delete(artifact_id):
        raise HTTPException(status_code=404, detail="Artifact not found")
    return {"deleted": True, "artifact_id": artifact_id}
