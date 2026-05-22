"""AD-791: REST routes for the chat-threads substrate.

Endpoints:
    GET    /api/threads                       — list (filter by project_id, include_archived)
    POST   /api/threads                       — create
    GET    /api/threads/{id}                  — fetch one
    PATCH  /api/threads/{id}                  — update (pin/archive/title/etc.)
    DELETE /api/threads/{id}                  — delete (+ cascading messages)
    GET    /api/threads/{id}/messages         — list messages
    POST   /api/threads/{id}/messages         — append message

The legacy ``/api/agent/{id}/chat`` path is untouched in v1 — it keeps
working with its implicit per-agent default thread. AD-791a wires it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from probos.routers.deps import get_runtime

router = APIRouter(prefix="/api/threads", tags=["threads"])


def _get_store(runtime: Any):
    store = getattr(runtime, "chat_thread_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Chat thread store not available")
    return store


class CreateThreadRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    participants: list[str] = Field(default_factory=list)
    project_id: str | None = None
    task_id: str | None = None
    personality_override: str | None = None
    workspace_root: str | None = None


class UpdateThreadRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    personality_override: str | None = None
    workspace_root: str | None = None
    project_id: str | None = None
    task_id: str | None = None


class AppendMessageRequest(BaseModel):
    author_id: str = Field(..., min_length=1, max_length=128)
    role: str = Field(..., pattern="^(captain|agent|system)$")
    body: str = Field(..., min_length=1)
    metadata: dict | None = None


@router.get("")
async def list_threads(
    include_archived: bool = False,
    project_id: str | None = None,
    limit: int = 100,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    threads = store.list_threads(
        include_archived=include_archived,
        project_id=project_id,
        limit=max(1, min(limit, 500)),
    )
    return {"threads": [t.to_dict() for t in threads]}


@router.post("")
async def create_thread(
    body: CreateThreadRequest, runtime: Any = Depends(get_runtime)
) -> dict:
    store = _get_store(runtime)
    thread = store.create_thread(
        title=body.title,
        participants=body.participants,
        project_id=body.project_id,
        task_id=body.task_id,
        personality_override=body.personality_override,
        workspace_root=body.workspace_root,
    )
    return thread.to_dict()


@router.get("/{thread_id}")
async def get_thread(thread_id: str, runtime: Any = Depends(get_runtime)) -> dict:
    store = _get_store(runtime)
    thread = store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread.to_dict()


@router.patch("/{thread_id}")
async def update_thread(
    thread_id: str,
    body: UpdateThreadRequest,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    thread = store.update_thread(
        thread_id,
        title=body.title,
        pinned=body.pinned,
        archived=body.archived,
        personality_override=body.personality_override,
        workspace_root=body.workspace_root,
        project_id=body.project_id,
        task_id=body.task_id,
    )
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread.to_dict()


@router.delete("/{thread_id}")
async def delete_thread(thread_id: str, runtime: Any = Depends(get_runtime)) -> dict:
    store = _get_store(runtime)
    deleted = store.delete_thread(thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"deleted": True, "thread_id": thread_id}


@router.get("/{thread_id}/messages")
async def list_messages(
    thread_id: str,
    limit: int = 200,
    before: float | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    if store.get_thread(thread_id) is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    msgs = store.list_messages(
        thread_id, limit=max(1, min(limit, 1000)), before=before
    )
    return {"thread_id": thread_id, "messages": [m.to_dict() for m in msgs]}


@router.post("/{thread_id}/messages")
async def append_message(
    thread_id: str,
    body: AppendMessageRequest,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    msg = store.append_message(
        thread_id,
        author_id=body.author_id,
        role=body.role,
        body=body.body,
        metadata=body.metadata,
    )
    if msg is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return msg.to_dict()
