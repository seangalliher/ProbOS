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

# BF-721: the Captain is not a registered agent, so a Captain-authored thread has
# no agent to reply to — the target is the *other* party and must come from the
# channel-level fallback.
_CAPTAIN_AUTHOR_ID = "captain"

_DM_CHANNEL_PREFIX = "dm-"


def _resolve_dm_target_agent_id(channel_name: str, runtime: Any) -> str | None:
    """AD-574b: Resolve the non-Captain participant agent_id from a DM channel name.

    DM channel names use one of two formats:
      - ``dm-captain-{agent_id[:8]}`` (Captain DMs, ``proactive.py:3599``)
      - ``dm-{sorted_ids[0][:8]}-{sorted_ids[1][:8]}`` (agent-to-agent, ``ward_room/channels.py:203``)

    The UI's DM panel needs the FULL agent_id (not the 8-char prefix) to call
    ``POST /api/agent/{id}/chat``. Resolve by scanning ``runtime.registry.all()``
    for a registered crew agent whose id starts with the non-Captain prefix.

    This is the **channel-level default**. It is inherently lossy: the 8-char
    prefix truncates inside the agent type (every Counselor instance keys to
    ``counselo``) and an agent-to-agent channel has two participants but only
    one answer. Prefer :func:`_resolve_thread_target_agent_id`, which uses the
    thread's own ``author_id``; this remains the fallback when no thread context
    is available or the author is not a registered agent.

    BF-721: registration, not liveness, is the test. The previous
    ``getattr(agent, "is_alive", False)`` gate meant a resting crew member — the
    normal state for a proactive agent between think ticks — resolved to
    ``None`` and the Captain's reply silently degraded to the async post-only
    path. AD-1076 established the same rule for group-chat membership: a
    *persistent* relationship must not depend on momentary liveness.

    Returns ``None`` when no registered agent matches (deleted/renamed/lookup
    failure). Tier-2 log-and-degrade: any unexpected error is caught, logged at
    warning, and returns ``None`` so the UI falls back to the async post-only path.
    """
    if not channel_name.startswith(_DM_CHANNEL_PREFIX):
        return None
    try:
        registry = getattr(runtime, "registry", None)
        if registry is None:
            return None
        parts = channel_name.split("-")  # ["dm", "<a>", "<b>"] or ["dm", "captain", "<b>"]
        if len(parts) != 3:
            return None
        # The non-Captain prefix is the part that is not literally "captain".
        candidates = [p for p in parts[1:] if p != _CAPTAIN_AUTHOR_ID]
        if not candidates:
            return None
        prefix = candidates[0]
        for agent in registry.all():
            agent_id = getattr(agent, "id", "")
            if agent_id and agent_id.startswith(prefix):
                return agent_id
        return None
    except Exception as exc:  # noqa: BLE001 — Tier-2 log-and-degrade
        logger.warning(
            "AD-574b: failed to resolve DM target agent_id for channel %r: %s",
            channel_name, exc,
        )
        return None


def _resolve_thread_target_agent_id(
    channel_name: str, author_id: str, runtime: Any,
) -> str | None:
    """BF-721: Resolve the reply target for ONE thread rather than a whole channel.

    One DM channel holds many threads and may have several authors — the live
    vessel has 20+ agent-to-agent channels with two distinct thread authors, and
    the ``dm-captain-{agent_id[:8]}`` scheme collapses every same-type instance
    onto one channel. A single channel-level answer therefore routes some
    replies to the wrong agent.

    ``threads.author_id`` already holds the exact, full agent id of the filer, so
    the authoritative target is per thread. Rules:

    1. Non-DM channel ⇒ ``None``. Only DM threads carry a synchronous reply target.
    2. Author is a registered agent ⇒ that agent. Registration is checked via
       ``registry.get(author_id)``, **not** liveness (see AD-1076 / BF-721).
    3. Otherwise — the Captain authored it, or the author has since been
       unregistered — fall back to the channel-level default, which answers
       "who is the other party in this channel".

    A failed fallback still yields ``None``, so the UI degrades to the async
    post-only path exactly as before.
    """
    if not channel_name.startswith(_DM_CHANNEL_PREFIX):
        return None
    if author_id and author_id != _CAPTAIN_AUTHOR_ID:
        try:
            registry = getattr(runtime, "registry", None)
            if registry is not None and registry.get(author_id) is not None:
                return author_id
        except Exception as exc:  # noqa: BLE001 — Tier-2 log-and-degrade
            logger.warning(
                "BF-721: registry lookup failed for thread author %r in channel %r "
                "(%s); falling back to channel-level DM target",
                author_id, channel_name, exc,
            )
    return _resolve_dm_target_agent_id(channel_name, runtime)


def _thread_with_target(thread: Any, channel_name: str, runtime: Any) -> dict[str, Any]:
    """BF-721: project a thread into a dict carrying its own ``target_agent_id``.

    Accepts a ``WardRoomThread`` dataclass or an already-dict thread row and
    always returns a fresh dict, so the source object is never mutated. Every
    pre-existing key is preserved verbatim — the payload gains one key and
    changes nothing else.
    """
    data: dict[str, Any] = dict(thread) if isinstance(thread, dict) else dict(vars(thread))
    data["target_agent_id"] = _resolve_thread_target_agent_id(
        channel_name, str(data.get("author_id") or ""), runtime,
    )
    return data


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
        # AD-613: Use count_threads() instead of fetching 100 rows for len()
        thread_count = await runtime.ward_room.count_threads(ch.id)
        result.append({
            "channel": {
                "id": ch.id, "name": ch.name,
                "description": ch.description,
                "created_at": ch.created_at,
            },
            # BF-721: each thread carries its own target, derived from its author.
            "latest_thread": (
                _thread_with_target(threads[0], ch.name, runtime) if threads else None
            ),
            "thread_count": thread_count,
            # BF-721: channel-level default retained for consumers with no thread
            # context, and as the fallback for Captain-authored threads.
            "target_agent_id": _resolve_dm_target_agent_id(ch.name, runtime),
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
    # BF-721: per-thread reply target, derived from each thread's own author.
    return {
        "channel": dm_ch,
        "threads": [_thread_with_target(t, dm_ch.name, runtime) for t in threads],
    }


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
        # AD-613: Use count_threads() for accurate count independent of limit
        thread_count = await runtime.ward_room.count_threads(ch.id)
        result.append({
            "channel": {"id": ch.id, "name": ch.name, "description": ch.description,
                        "created_at": ch.created_at},
            # BF-721: each thread carries its own target, derived from its author.
            "threads": [_thread_with_target(t, ch.name, runtime) for t in threads],
            "thread_count": thread_count,
            # BF-721: channel-level default retained for consumers with no thread
            # context, and as the fallback for Captain-authored threads.
            "target_agent_id": _resolve_dm_target_agent_id(ch.name, runtime),
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
    # BF-721: this is the payload the HXI reads for the OPEN thread, so it is the
    # one that must carry the per-thread reply target. Non-DM threads resolve to
    # ``None`` — only DM threads have a synchronous reply target.
    thread = result.get("thread")
    if thread is not None:
        result["thread"] = _thread_with_target(
            thread,
            str((thread.get("channel_name") if isinstance(thread, dict)
                 else getattr(thread, "channel_name", "")) or ""),
            runtime,
        )
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
    # BF-263: Resolve callsign server-side when the client omits author_callsign.
    # The UI DM dual-write path (WardRoomThreadDetail.submitReply) posts the
    # agent reply with only author_id, which would otherwise render as
    # "unknown" because WardRoomPostItem falls back when author_callsign == "".
    author_callsign = req.author_callsign or ""
    if not author_callsign and req.author_id and req.author_id != "captain":
        try:
            agent = runtime.registry.get(req.author_id)
            callsign_registry = getattr(runtime, "callsign_registry", None)
            if agent is not None and callsign_registry is not None:
                author_callsign = callsign_registry.get_callsign(agent.agent_type) or ""
        except Exception:
            logger.debug(
                "BF-263: callsign resolution failed for author_id=%s; "
                "posting with empty callsign",
                req.author_id,
                exc_info=True,
            )
    try:
        post = await runtime.ward_room.create_post(
            thread_id=thread_id, author_id=req.author_id,
            body=req.body, parent_id=req.parent_id,
            author_callsign=author_callsign,
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
