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
    # AD-794: when True, the title update routes through
    # ``set_title(lock=True)`` which atomically writes
    # ``metadata.title_locked = true`` so subsequent first-turn auto-
    # naming skips this thread. Operator-initiated renames (sidebar
    # right-click, future UI) should send this; the internal first-
    # turn auto-name path bypasses the API and calls
    # ``set_title(lock=False)`` directly.
    title_locked: bool | None = None


class AppendMessageRequest(BaseModel):
    author_id: str = Field(..., min_length=1, max_length=128)
    role: str = Field(..., pattern="^(captain|agent|system)$")
    body: str = Field(..., min_length=1)
    metadata: dict | None = None


class ParticipantRequest(BaseModel):
    # AD-913: declared as a plain str with an empty default (NOT
    # Field(..., min_length=1)) so a missing OR empty agent_id is
    # caught by the explicit 400 check below — min_length would 422.
    agent_id: str = ""


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


# AD-792: sidebar search + recents endpoints.
@router.get("/search")
async def search_threads(
    q: str = "",
    limit: int = 50,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    results = store.search_threads(q, limit=limit)
    return {"query": q, "results": [t.to_dict() for t in results]}


@router.get("/recents")
async def list_recents(limit: int = 20, runtime: Any = Depends(get_runtime)) -> dict:
    store = _get_store(runtime)
    items = store.recents(limit=limit)
    return {"recents": [t.to_dict() for t in items]}


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
    # AD-794: when an operator-initiated rename arrives with
    # ``title_locked=True``, route the title update through
    # ``set_title(lock=True)`` so the metadata flag is written
    # atomically alongside the new title. All other fields fall
    # through to the existing ``update_thread`` shape so nothing else
    # changes for non-lock callers.
    if body.title is not None and body.title_locked is True:
        if store.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail="Thread not found")
        store.set_title(thread_id, body.title, lock=True)
        # Apply any remaining fields (pinned/archived/etc.) via the
        # normal path so a single PATCH can carry both a locked rename
        # and a sibling flag change in one round-trip.
        thread = store.update_thread(
            thread_id,
            pinned=body.pinned,
            archived=body.archived,
            personality_override=body.personality_override,
            workspace_root=body.workspace_root,
            project_id=body.project_id,
            task_id=body.task_id,
        )
        if thread is None:
            thread = store.get_thread(thread_id)
        return thread.to_dict() if thread else {"id": thread_id}

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
    # AD-793 (Wave 196): when the thread belongs to a project, bump the
    # project's last_active_at so the sidebar's last-active-ordered
    # project list reflects conversational tempo. Router-layer call
    # site keeps threads/__init__.py decoupled from the projects layer.
    # Tier-2 honest-degrade: missing project_store or vanished project
    # row is debug-logged and skipped.
    try:
        thread = store.get_thread(thread_id)
        if thread is not None and thread.project_id:
            project_store = getattr(runtime, "project_store", None)
            if project_store is not None:
                project_store.touch(thread.project_id)
    except Exception:
        import logging
        logging.getLogger(__name__).debug(
            "AD-793: project touch failed for thread=%s", thread_id,
            exc_info=True,
        )
    return msg.to_dict()


# AD-913: chat-thread participant management. Foundation for the
# ad-hoc group-chat epic — "add crew to a 1:1" (POST) and "the Captain
# joins an agent-created chat" / "remove a participant" (DELETE).
@router.post("/{thread_id}/participants")
async def add_participant(
    thread_id: str,
    body: ParticipantRequest,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    agent_id = body.agent_id.strip()
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    thread = store.add_participant(thread_id, agent_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread.to_dict()


@router.delete("/{thread_id}/participants/{agent_id}")
async def remove_participant(
    thread_id: str,
    agent_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict:
    store = _get_store(runtime)
    thread = store.remove_participant(thread_id, agent_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    return thread.to_dict()


# AD-794: thread auto-naming. v1 heuristic; AD-794a LLM-backed.
@router.post("/{thread_id}/auto-name")
async def auto_name_thread(
    thread_id: str, runtime: Any = Depends(get_runtime)
) -> dict:
    store = _get_store(runtime)
    thread = store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")
    msgs = store.list_messages(thread_id, limit=1)
    if not msgs:
        raise HTTPException(status_code=409, detail="Thread has no messages yet")
    # AD-794: refactor to share ``maybe_auto_name`` with the first-turn
    # auto-trigger in the chat handlers. ``force=True`` preserves this
    # endpoint's pre-AD-794 always-rename behavior — only the
    # title_locked flag short-circuits it. The first-turn caller uses
    # ``force=False`` to apply the single-participant + default-title
    # pre-conditions.
    updated = store.maybe_auto_name(thread_id, msgs[0].body, force=True)
    return updated.to_dict() if updated else thread.to_dict()


# AD-815c: promote a chat instruction into a tracked Task. Creates an
# AD-477 WorkItem + AD-815a TaskSession + links the two together. If
# `description` is omitted, the most recent message body in the thread
# is used as the brief.
class PromoteToTaskRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    assigned_to: str | None = None
    schedule_kind: str = Field(default="one_shot", pattern="^(one_shot|recurring)$")
    schedule_cron: str | None = None
    schedule_timezone: str | None = None
    recurrence_policy: str = Field(
        default="reuse", pattern="^(reuse|new_session_each_run)$"
    )
    container_image: str | None = None
    egress_policy: str = Field(default="bridge", pattern="^(none|bridge|allowlist)$")
    priority: int = Field(default=3, ge=1, le=5)


@router.post("/{thread_id}/promote-to-task")
async def promote_thread_to_task(
    thread_id: str,
    body: PromoteToTaskRequest,
    runtime: Any = Depends(get_runtime),
) -> dict:
    """AD-815c: convert a chat brief into a WorkItem + TaskSession."""
    store = _get_store(runtime)
    thread = store.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    description = body.description
    if not description:
        last_msgs = store.list_messages(thread_id, limit=1)
        # Prefer the most recent captain turn; otherwise any latest msg.
        if last_msgs:
            description = last_msgs[-1].body
    if not description:
        raise HTTPException(
            status_code=409,
            detail="Thread has no messages and no description supplied",
        )

    # Choose assignee: explicit override > thread's single participant > None.
    assigned_to = body.assigned_to
    if assigned_to is None and len(thread.participants) == 1:
        assigned_to = thread.participants[0]

    # WorkItem (AD-477). Optional — runtime may not have a store in tests.
    work_item_id: str | None = None
    wi_store = getattr(runtime, "work_item_store", None)
    if wi_store is not None:
        try:
            item = await wi_store.create_work_item(
                title=body.title,
                description=description,
                work_type="task",
                priority=body.priority,
                assigned_to=assigned_to,
                created_by="captain",
                tags=["cowork", f"thread:{thread_id}"],
                metadata={"thread_id": thread_id},
            )
            work_item_id = item.id
        except Exception:
            # Tier-2 log-and-degrade: the TaskSession still ships even if
            # the WorkItemStore is busy. The kanban surface will pick up
            # the AD-815a session on its next sweep (AD-815c follow-up).
            work_item_id = None

    # TaskSession (AD-815a).
    ts_store = getattr(runtime, "task_session_store", None)
    if ts_store is None:
        raise HTTPException(
            status_code=503, detail="TaskSessionStore not available"
        )
    session = ts_store.create_session(
        thread_id=thread_id,
        title=body.title,
        work_item_id=work_item_id,
        schedule_kind=body.schedule_kind,
        schedule_cron=body.schedule_cron,
        schedule_timezone=body.schedule_timezone,
        recurrence_policy=body.recurrence_policy,
        container_image=body.container_image,
        egress_policy=body.egress_policy,
    )
    return {
        "task_session": session.to_dict(),
        "work_item_id": work_item_id,
    }
