"""ProbOS API — Ward Room routes (AD-407, AD-412, AD-416, AD-424, AD-425, AD-426, AD-453, AD-485)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from probos.api_models import (
    CreateChannelRequest, CreatePostRequest, CreateThreadRequest,
    EndorseRequest, SubscribeRequest, UpdateThreadRequest,
)
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wardroom", tags=["wardroom"])


# ── DMs (AD-453/AD-485) ──────────────────────────────────────────


@router.get("/dms")
async def list_dm_channels(runtime: Any = Depends(get_runtime)):
    """List all DM channels with latest thread info. Captain oversight."""
    if not runtime.ward_room:
        return []
    channels = await runtime.ward_room.list_channels()
    dm_channels = [c for c in channels if c.channel_type == "dm"]
    result = []
    for ch in dm_channels:
        threads = await runtime.ward_room.list_threads(ch.id, limit=1)
        all_threads = await runtime.ward_room.list_threads(ch.id, limit=100)
        result.append({
            "channel": {
                "id": ch.id, "name": ch.name,
                "description": ch.description,
                "created_at": ch.created_at,
            },
            "latest_thread": threads[0] if threads else None,
            "thread_count": len(all_threads),
        })
    return result


@router.get("/dms/{channel_id}/threads")
async def list_dm_threads(channel_id: str, runtime: Any = Depends(get_runtime)):
    """List all threads in a DM channel. Captain oversight."""
    if not runtime.ward_room:
        raise HTTPException(status_code=404, detail="Ward Room not available")
    channels = await runtime.ward_room.list_channels()
    dm_ch = next((c for c in channels if c.id == channel_id and c.channel_type == "dm"), None)
    if not dm_ch:
        raise HTTPException(status_code=404, detail="DM channel not found")
    threads = await runtime.ward_room.list_threads(channel_id, limit=100)
    return {"channel": dm_ch, "threads": threads}


@router.get("/captain-dms")
async def list_captain_dms(runtime: Any = Depends(get_runtime)):
    """List all DMs addressed to the Captain."""
    if not runtime.ward_room:
        return []
    channels = await runtime.ward_room.list_channels()
    captain_channels = [c for c in channels
                        if c.channel_type == "dm" and "captain" in c.name.lower()]
    result = []
    for ch in captain_channels:
        threads = await runtime.ward_room.list_threads(ch.id, limit=20)
        result.append({
            "channel": {"id": ch.id, "name": ch.name, "description": ch.description,
                        "created_at": ch.created_at},
            "threads": threads,
            "thread_count": len(threads),
        })
    return result


@router.get("/dms/archive")
async def search_dm_archive(q: str = "", since: float = 0, until: float = 0, runtime: Any = Depends(get_runtime)):
    """Search archived DM messages. Captain oversight."""
    if not runtime.ward_room:
        return {"results": [], "count": 0}
    channels = await runtime.ward_room.list_channels()
    dm_channels = [c for c in channels if c.channel_type == "dm"]
    results = []
    for ch in dm_channels:
        threads = await runtime.ward_room.list_threads(
            ch.id, limit=200, include_archived=True
        )
        for t in threads:
            _title = getattr(t, 'title', '') or ''
            _body = getattr(t, 'body', '') or ''
            _created = getattr(t, 'created_at', 0) or 0
            if q and q.lower() not in (_title + _body).lower():
                continue
            if since and _created < since:
                continue
            if until and _created > until:
                continue
            results.append({"channel": ch.name, "thread": t})
    return {"results": results, "count": len(results)}


# ── Channels & Threads (AD-407) ───────────────────────────────────


@router.get("/channels")
async def wardroom_channels(runtime: Any = Depends(get_runtime)):
    if not runtime.ward_room:
        return {"channels": []}
    channels = await runtime.ward_room.list_channels()
    return {"channels": [vars(c) for c in channels]}


@router.post("/channels")
async def wardroom_create_channel(req: CreateChannelRequest, runtime: Any = Depends(get_runtime)):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    try:
        ch = await runtime.ward_room.create_channel(
            name=req.name, channel_type="custom",
            created_by=req.created_by, description=req.description,
        )
        return vars(ch)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/channels/{channel_id}/threads")
async def wardroom_threads(channel_id: str, limit: int = 50, offset: int = 0, sort: str = "recent", runtime: Any = Depends(get_runtime)):
    if not runtime.ward_room:
        return {"threads": []}
    threads = await runtime.ward_room.list_threads(channel_id, limit=limit, offset=offset, sort=sort)
    return {"threads": [vars(t) for t in threads]}


@router.post("/channels/{channel_id}/threads")
async def wardroom_create_thread(channel_id: str, req: CreateThreadRequest, runtime: Any = Depends(get_runtime)):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    try:
        thread = await runtime.ward_room.create_thread(
            channel_id=channel_id, author_id=req.author_id,
            title=req.title, body=req.body,
            author_callsign=req.author_callsign,
            thread_mode=req.thread_mode,
            max_responders=req.max_responders,
        )
        return vars(thread)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/threads/{thread_id}")
async def wardroom_thread_detail(thread_id: str, runtime: Any = Depends(get_runtime)):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    result = await runtime.ward_room.get_thread(thread_id)
    if not result:
        raise HTTPException(404, "Thread not found")
    return result


@router.patch("/threads/{thread_id}")
async def wardroom_update_thread(thread_id: str, req: UpdateThreadRequest, runtime: Any = Depends(get_runtime)):
    """AD-424: Update thread properties (Captain-level)."""
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No updates provided")
    thread = await runtime.ward_room.update_thread(thread_id, **updates)
    if not thread:
        raise HTTPException(404, "Thread not found")
    return vars(thread)


@router.post("/threads/{thread_id}/posts")
async def wardroom_create_post(thread_id: str, req: CreatePostRequest, runtime: Any = Depends(get_runtime)):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    try:
        post = await runtime.ward_room.create_post(
            thread_id=thread_id, author_id=req.author_id,
            body=req.body, parent_id=req.parent_id,
            author_callsign=req.author_callsign,
        )
        return vars(post)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/posts/{post_id}/endorse")
async def wardroom_endorse(post_id: str, req: EndorseRequest, runtime: Any = Depends(get_runtime)):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    try:
        result = await runtime.ward_room.endorse(
            target_id=post_id, target_type="post",
            voter_id=req.voter_id, direction=req.direction,
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/threads/{thread_id}/endorse")
async def wardroom_endorse_thread(thread_id: str, req: EndorseRequest, runtime: Any = Depends(get_runtime)):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    try:
        result = await runtime.ward_room.endorse(
            target_id=thread_id, target_type="thread",
            voter_id=req.voter_id, direction=req.direction,
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/channels/{channel_id}/subscribe")
async def wardroom_subscribe(channel_id: str, req: SubscribeRequest, runtime: Any = Depends(get_runtime)):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    if req.action == "unsubscribe":
        await runtime.ward_room.unsubscribe(req.agent_id, channel_id)
    else:
        await runtime.ward_room.subscribe(req.agent_id, channel_id)
    return {"ok": True}


@router.get("/agent/{agent_id}/credibility")
async def wardroom_credibility(agent_id: str, runtime: Any = Depends(get_runtime)):
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    cred = await runtime.ward_room.get_credibility(agent_id)
    result = vars(cred)
    result["restrictions"] = list(cred.restrictions)
    return result


@router.get("/notifications")
async def wardroom_notifications(agent_id: str, runtime: Any = Depends(get_runtime)):
    if not runtime.ward_room:
        return {"unread": {}}
    counts = await runtime.ward_room.get_unread_counts(agent_id)
    return {"unread": counts}


# AD-425: Activity feed
@router.get("/activity")
async def wardroom_activity_feed(
    agent_id: str | None = None,
    channel_id: str | None = None,
    thread_mode: str | None = None,
    limit: int = 20,
    since: float = 0.0,
    sort: str = "recent",
    runtime: Any = Depends(get_runtime),
):
    """Browse Ward Room threads across channels."""
    if not runtime.ward_room:
        return {"threads": []}
    if channel_id:
        threads = await runtime.ward_room.list_threads(channel_id, limit=limit, sort=sort)
        if thread_mode:
            threads = [t for t in threads if t.thread_mode == thread_mode]
        if since > 0:
            threads = [t for t in threads if t.last_activity > since]
    elif agent_id:
        threads = await runtime.ward_room.browse_threads(
            agent_id, thread_mode=thread_mode, limit=limit, since=since,
            sort=sort,
        )
    else:
        all_channels = await runtime.ward_room.list_channels()
        all_ch_ids = [c.id for c in all_channels]
        threads = await runtime.ward_room.browse_threads(
            "_anonymous", channels=all_ch_ids,
            thread_mode=thread_mode, limit=limit, since=since,
            sort=sort,
        )
    return {"threads": [vars(t) for t in threads]}


@router.put("/channels/{channel_id}/seen")
async def wardroom_mark_seen(channel_id: str, agent_id: str, runtime: Any = Depends(get_runtime)):
    """Mark all threads in a channel as seen for an agent."""
    if not runtime.ward_room:
        raise HTTPException(503, "Ward Room not available")
    await runtime.ward_room.update_last_seen(agent_id, channel_id)
    return {"status": "ok"}


# AD-412: Improvement proposals
@router.get("/proposals")
async def list_improvement_proposals(
    status: str | None = None, limit: int = 20,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-412: List improvement proposals from the #Improvement Proposals channel."""
    if not runtime.ward_room:
        return {"proposals": []}

    channels = await runtime.ward_room.list_channels()
    proposals_ch = None
    for ch in channels:
        if ch.name == "Improvement Proposals":
            proposals_ch = ch
            break

    if not proposals_ch:
        return {"proposals": []}

    threads = await runtime.ward_room.list_threads(
        proposals_ch.id, limit=min(limit, 100),
    )

    proposals = []
    for t in threads:
        proposal = {
            "thread_id": t.id,
            "title": t.title,
            "body": t.body,
            "author": t.author_callsign or t.author_id,
            "created_at": t.created_at,
            "net_score": t.net_score,
            "reply_count": t.reply_count,
            "status": "approved" if t.net_score > 0 else "shelved" if t.net_score < 0 else "pending",
        }
        proposals.append(proposal)

    if status:
        proposals = [p for p in proposals if p["status"] == status]

    return {"channel_id": proposals_ch.id, "proposals": proposals}
