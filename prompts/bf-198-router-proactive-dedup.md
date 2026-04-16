# BF-198: Router/Proactive Response Dedup — Responded-To Thread Tracker

## Problem

Agents respond to the same Ward Room message **twice** — once via the router path (event-driven, `WARD_ROOM_THREAD_CREATED`) and once via the proactive loop (poll-driven, `get_recent_activity()`). The router dispatches immediately on the event; seconds later the proactive loop ticks, sees the same Captain message in the activity window, and the LLM generates another response.

**Root cause:** The two paths share no state about which threads an agent has already responded to. The proactive loop filters out the agent's own posts (`author_id in self_ids`, line ~1249) but not threads the agent already *replied to* via the router. `update_last_seen` is written but never read by the proactive activity query.

**Observed:** Sentinel posted twice to Captain's "Hello Crew" communication test — first a short confirmation, then an expanded version. BF-197 added a similarity guard as a safety net, but the real fix is preventing the second dispatch entirely.

## Solution: Shared Responded-To Tracker

Add a lightweight in-memory tracker that records `(agent_id, thread_id)` whenever an agent's response is posted to a Ward Room thread, regardless of which path triggered it. Both the router and proactive loop consult this tracker before responding.

### Design

**Data structure** in `WardRoomRouter`:

```python
# BF-198: Track threads each agent has already responded to.
# Shared between router path and proactive loop to prevent double-response.
# Key: (agent_id, thread_id), Value: timestamp of response.
self._responded_threads: dict[tuple[str, str], float] = {}
```

**Recording** — called from both paths after a response is posted:

```python
def record_agent_response(self, agent_id: str, thread_id: str) -> None:
    """BF-198: Record that agent has responded to thread."""
    self._responded_threads[(agent_id, thread_id)] = time.time()

def has_agent_responded(self, agent_id: str, thread_id: str) -> bool:
    """BF-198: Check if agent already responded to thread."""
    return (agent_id, thread_id) in self._responded_threads
```

**Eviction** — stale entries older than 10 minutes are purged periodically (same pattern as `_reply_cooldowns`). This prevents unbounded memory growth and allows agents to re-engage with long-lived threads after a reasonable window.

```python
def _evict_stale_responses(self, max_age: float = 600.0) -> None:
    """BF-198: Evict response records older than max_age seconds."""
    cutoff = time.time() - max_age
    self._responded_threads = {
        k: v for k, v in self._responded_threads.items() if v > cutoff
    }
```

### Integration Points

#### 1. Router path (`ward_room_router.py`, Phase 3 result processing, ~line 589+)

After `create_post()` succeeds, record the response:

```python
await self._ward_room.create_post(...)
self.record_agent_response(agent_id, thread_id)  # BF-198
```

#### 2. Proactive loop — Ward Room activity filtering (`proactive.py`, ~line 1236)

When building `ward_room_activity` context, skip threads the agent already responded to:

```python
# BF-198: Skip threads agent already responded to via router
wr_router = getattr(rt, 'ward_room_router', None)
context["ward_room_activity"] = [
    {
        "type": a["type"],
        "author": a["author"],
        ...
    }
    for a in activity
    if (a.get("author_id", "") or a.get("author", "")) not in self_ids  # BF-032
    and not (wr_router and wr_router.has_agent_responded(agent.id, a.get("thread_id", "")))  # BF-198
]
```

Apply the same filter to All Hands activity (~line 1270) and Recreation activity (~line 1305).

#### 3. Proactive loop — after posting new thread (`proactive.py`, ~line 715)

When the proactive loop posts a new thread or reply, also record it so the router won't double-respond if the event fires:

```python
# After create_thread or create_post in proactive path
if rt.ward_room_router:
    rt.ward_room_router.record_agent_response(agent.id, thread_id)  # BF-198
```

#### 4. Eviction — call during periodic maintenance

In `_evict_stale_responses`, run from the router's existing tick or from the proactive loop's cycle start. A simple approach: call at the top of `route_event()` if more than 60 seconds since last eviction (same pattern as other cache maintenance).

### NATS Compatibility

This tracker is **transport-agnostic**. It's an in-memory dict keyed by `(agent_id, thread_id)`, not tied to how the event arrived. When AD-637 (NATS Event Bus) replaces the current asyncio event dispatch:

- The router becomes a NATS subscriber instead of receiving `route_event()` calls
- The proactive loop remains a poller (or becomes a NATS consumer with windowed replay)
- The `_responded_threads` dict works identically in both models
- If NATS provides message dedup (JetStream exactly-once), this tracker becomes defense-in-depth rather than the primary guard

The tracker could later be promoted to a NATS KV bucket for multi-process visibility, but for single-process ProbOS the in-memory dict is sufficient.

### Testing

1. **Unit — `record_agent_response` / `has_agent_responded`:** Record, check True, check different agent/thread False.
2. **Unit — eviction:** Record, advance time past max_age, evict, check False.
3. **Integration — router records response:** Mock `create_post`, call router processing, assert `has_agent_responded` True.
4. **Integration — proactive skips responded thread:** Set up `_responded_threads` entry, build ward_room_activity context, assert thread is excluded.
5. **Integration — proactive records response:** Proactive loop posts thread, assert `has_agent_responded` True on the router.
6. **End-to-end — no double post:** Captain message → router dispatches Sentinel → proactive loop ticks → Sentinel's activity context excludes the Captain's thread → no second post.

### Files Modified

- `src/probos/ward_room_router.py` — add tracker dict, `record_agent_response()`, `has_agent_responded()`, `_evict_stale_responses()`, record call after `create_post()`
- `src/probos/proactive.py` — filter `ward_room_activity` by responded tracker (~3 locations), record after proactive post
- `tests/test_bf198_router_proactive_dedup.py` — new test file

### Verification

```bash
python -m pytest tests/test_bf198_router_proactive_dedup.py tests/test_ad629_reply_gate.py tests/test_proactive_quality.py -x -q -o addopts=""
```
