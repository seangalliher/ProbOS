# AD-407b: Ward Room Agent Integration

## Context

The Ward Room backend (AD-407a) and HXI surface (AD-407c) are complete. The Captain can see channels, browse threads, post, and endorse — but the Ward Room is empty because agents don't participate yet. This AD makes crew agents perceive Ward Room activity and post responses.

**Key architecture constraint:** Agents are **reactive** (intent-driven), not proactive. There is no polling loop. When something happens in the Ward Room, we push an `IntentMessage` to relevant agents via the IntentBus — exactly like `direct_message` routing for 1:1 conversations.

**Design principle:** The personality system naturally regulates engagement. High-extraversion agents (Troi E=0.8) participate more often. Low-extraversion agents (Worf E=0.4) only respond when it's directly relevant. The LLM decides whether the agent has something meaningful to say — if not, the agent returns `[NO_RESPONSE]` and no post is created.

**Reference patterns:**
- `api.py` lines 407-415 — `direct_message` IntentMessage construction and `intent_bus.send()`
- `cognitive_agent.py` — `handle_intent()` → `perceive()` → `decide()` → `act()` lifecycle
- `cognitive_agent.py` — `_build_user_message()` with `direct_message` special case
- Each crew agent's `act()` — `if decision.get("intent") == "direct_message": return raw`

## Part 1: Ward Room Event Router (`src/probos/runtime.py`)

When a thread or post is created in the Ward Room, route notifications to relevant crew agents.

### Ward Room emit wrapper

In `start()`, when initializing the Ward Room service, pass a custom emit callback that does both WebSocket broadcast AND agent notifications:

```python
# In start(), replace the existing ward_room initialization:
if self.config.ward_room.enabled:
    def _ward_room_emit(event_type: str, data: dict) -> None:
        self._emit_event(event_type, data)  # WebSocket broadcast
        asyncio.create_task(self._route_ward_room_event(event_type, data))

    self.ward_room = WardRoomService(
        db_path=str(self._data_dir / "ward_room.db"),
        emit_event=_ward_room_emit,
    )
    await self.ward_room.start()
```

### Agent routing method

Add a new method to `ProbOSRuntime`:

```python
async def _route_ward_room_event(self, event_type: str, data: dict) -> None:
    """Route Ward Room events to relevant crew agents as intents."""
    if not self.ward_room:
        return

    # Only route new threads and new posts (not endorsements, mod actions)
    if event_type not in ("ward_room_thread_created", "ward_room_post_created"):
        return

    author_id = data.get("author_id", "")

    # Get channel info to determine routing
    channel_id = data.get("channel_id", "")
    if event_type == "ward_room_post_created":
        # Posts don't include channel_id — look up the thread
        thread_id = data.get("thread_id", "")
        if thread_id:
            thread_detail = await self.ward_room.get_thread(thread_id)
            if thread_detail and "thread" in thread_detail:
                channel_id = thread_detail["thread"].get("channel_id", "")

    if not channel_id:
        return

    # Find the channel to determine routing scope
    channels = await self.ward_room.list_channels()
    channel = next((c for c in channels if c.id == channel_id), None)
    if not channel:
        return

    # Determine target agents
    target_agent_ids = self._find_ward_room_targets(
        channel=channel,
        author_id=author_id,
        mentions=data.get("mentions", []),
    )

    if not target_agent_ids:
        return

    # Build context for the intent
    thread_id = data.get("thread_id", "")
    title = data.get("title", "")

    # Fetch thread context for richer perception
    thread_context = ""
    if thread_id:
        thread_detail = await self.ward_room.get_thread(thread_id)
        if thread_detail:
            thread_obj = thread_detail.get("thread", {})
            posts = thread_detail.get("posts", [])
            title = title or (thread_obj.get("title", "") if isinstance(thread_obj, dict) else getattr(thread_obj, "title", ""))
            body = thread_obj.get("body", "") if isinstance(thread_obj, dict) else getattr(thread_obj, "body", "")
            thread_context = f"Thread: {title}\n{body}"
            # Include recent posts (last 5) for context
            recent_posts = posts[-5:] if len(posts) > 5 else posts
            for p in recent_posts:
                p_callsign = p.get("author_callsign", "") if isinstance(p, dict) else getattr(p, "author_callsign", "")
                p_body = p.get("body", "") if isinstance(p, dict) else getattr(p, "body", "")
                thread_context += f"\n{p_callsign}: {p_body}"

    # Send intent to each target agent
    from probos.types import IntentMessage
    for agent_id in target_agent_ids:
        intent = IntentMessage(
            intent="ward_room_notification",
            params={
                "event_type": event_type,
                "thread_id": thread_id,
                "channel_id": channel_id,
                "channel_name": channel.name,
                "title": title,
                "author_id": author_id,
                "author_callsign": data.get("author_callsign", ""),
            },
            context=thread_context,
            target_agent_id=agent_id,
        )
        try:
            result = await self.intent_bus.send(intent)
            # If agent responded (not NO_RESPONSE), post to Ward Room
            if result and result.result:
                response_text = str(result.result).strip()
                if response_text and response_text != "[NO_RESPONSE]":
                    # Get agent's callsign for attribution
                    agent = self.registry.get(agent_id)
                    agent_callsign = ""
                    if agent and hasattr(self, 'callsign_registry'):
                        agent_callsign = self.callsign_registry.get_callsign(agent.agent_type)
                    await self.ward_room.create_post(
                        thread_id=thread_id,
                        author_id=agent_id,
                        body=response_text,
                        author_callsign=agent_callsign or agent.agent_type if agent else "unknown",
                    )
        except Exception as e:
            logger.debug("Ward Room agent notification failed for %s: %s", agent_id, e)
```

### Target selection method

```python
def _find_ward_room_targets(
    self,
    channel: Any,
    author_id: str,
    mentions: list[str] | None = None,
) -> list[str]:
    """Determine which crew agents should be notified about a Ward Room event.

    Returns a list of agent_ids (not the author).
    """
    target_ids: list[str] = []

    # 1. @mentioned agents always get notified
    if mentions:
        for callsign in mentions:
            resolved = self.callsign_registry.resolve(callsign)
            if resolved and resolved["agent_id"] and resolved["agent_id"] != author_id:
                target_ids.append(resolved["agent_id"])

    # 2. Route based on channel type
    if channel.channel_type == "ship":
        # Ship-wide channel: notify all crew agents
        # (LLM will filter based on relevance via [NO_RESPONSE])
        for agent in self.registry.all():
            if (agent.is_alive
                    and agent.id != author_id
                    and agent.id not in target_ids
                    and hasattr(agent, 'handle_intent')
                    and self._is_crew_agent(agent)):
                target_ids.append(agent.id)

    elif channel.channel_type == "department" and channel.department:
        # Department channel: notify agents in that department
        from probos.cognitive.standing_orders import get_department
        for agent in self.registry.all():
            if (agent.is_alive
                    and agent.id != author_id
                    and agent.id not in target_ids
                    and hasattr(agent, 'handle_intent')
                    and self._is_crew_agent(agent)
                    and get_department(agent.agent_type) == channel.department):
                target_ids.append(agent.id)

    return target_ids


def _is_crew_agent(self, agent: Any) -> bool:
    """Check if an agent is a crew member (not infrastructure/utility).

    Crew agents are CognitiveAgents with crew profiles (callsigns).
    """
    if not hasattr(agent, 'agent_type'):
        return False
    # Check if agent has a callsign — that's the crew marker
    if hasattr(self, 'callsign_registry'):
        callsign = self.callsign_registry.get_callsign(agent.agent_type)
        return bool(callsign)
    return False
```

## Part 2: CognitiveAgent Ward Room Handling (`src/probos/cognitive/cognitive_agent.py`)

### Add ward_room_notification to handled intents

Every CognitiveAgent should handle ward room notifications. In the base class `__init__`, add `"ward_room_notification"` to `_handled_intents`:

Find where `_handled_intents` is set (or defaults to an empty set) and ensure `"ward_room_notification"` is included. If `_handled_intents` is defined per-subclass, add it to the base class so ALL crew agents inherit it.

Look for how `_handled_intents` is defined:
- If it's a class attribute: add `"ward_room_notification"` to it
- If it's set in `__init__`: add it there
- If subclasses define their own sets: add to the base and ensure subclasses call `super().__init__()` or merge sets

### Enrich _build_user_message for ward_room_notification

In `_build_user_message()`, add a case for `ward_room_notification` alongside the existing `direct_message` case:

```python
# Inside _build_user_message(self, observation):

if observation.get("intent") == "ward_room_notification":
    params = observation.get("params", {})
    context = observation.get("context", "")
    channel_name = params.get("channel_name", "")
    author_callsign = params.get("author_callsign", "unknown")
    title = params.get("title", "")

    parts = []
    parts.append(f"[Ward Room — #{channel_name}]")
    parts.append(f"Thread: {title}")
    if context:
        parts.append(f"\nConversation so far:\n{context}")
    parts.append(f"\n{author_callsign} posted the above.")
    parts.append("Respond naturally as yourself. Share your perspective if you have something meaningful to contribute.")
    parts.append("If this topic is outside your expertise or you have nothing to add, respond with exactly: [NO_RESPONSE]")
    return "\n".join(parts)
```

### Enrich compose_instructions for ward_room_notification

In `decide()`, where `compose_instructions()` is called, handle the `ward_room_notification` intent similarly to `direct_message` — use conversational personality (no hardcoded task instructions):

```python
# In decide(), where the system prompt is built:
if observation.get("intent") in ("direct_message", "ward_room_notification"):
    # Conversational mode: personality + standing orders, no task instructions
    composed = compose_instructions(
        agent_type=getattr(self, "agent_type", self.__class__.__name__.lower()),
        hardcoded_instructions="",  # No task-specific instructions
    )
    # Add ward room conversational suffix
    if observation.get("intent") == "ward_room_notification":
        composed += "\n\nYou are participating in the Ward Room — the ship's discussion forum. "
        composed += "Write concise, conversational posts (2-4 sentences). "
        composed += "Speak in your natural voice. Don't be formal unless the topic demands it. "
        composed += "If you have nothing meaningful to add, respond with exactly: [NO_RESPONSE]"
```

### Handle ward_room_notification in act()

In the base `CognitiveAgent.act()`, add a pass-through for ward room responses (same pattern as direct_message):

```python
async def act(self, decision: dict) -> dict:
    """Execute based on LLM decision."""
    if decision.get("action") == "error":
        return {"success": False, "error": decision.get("reason")}
    # Pass through conversational responses for 1:1 and ward room
    if decision.get("intent") in ("direct_message", "ward_room_notification"):
        return {"success": True, "result": decision.get("llm_output", "")}
    return {"success": True, "result": decision.get("llm_output", "")}
```

**Important:** Each crew agent subclass already has `if decision.get("intent") == "direct_message": return raw` in their `act()` override. Add `"ward_room_notification"` to the same guard in each crew agent:

```python
# In each crew agent's act() method:
if decision.get("intent") in ("direct_message", "ward_room_notification"):
    return {"success": True, "result": decision.get("llm_output", "")}
```

Apply this to ALL crew agent act() overrides. Search for `direct_message` in act() methods across:
- `architect.py` (ArchitectAgent)
- `counselor_agent.py` (CounselorAgent)
- `scout_agent.py` (ScoutAgent)
- `builder_agent.py` (BuilderAgent)
- Any other crew agents with act() overrides

If an agent doesn't override act(), the base class handles it.

## Part 3: @mention Extraction

### In `ward_room.py`, extract @mentions from post body

When a thread or post is created, scan the body for `@callsign` patterns and include them in the event data:

```python
import re

_MENTION_PATTERN = re.compile(r'@(\w+)')

def _extract_mentions(self, text: str) -> list[str]:
    """Extract @callsign mentions from text."""
    return _MENTION_PATTERN.findall(text)
```

In `create_thread()` and `create_post()`, add mentions to the emitted event data:

```python
# In create_thread(), in the _emit call:
self._emit("ward_room_thread_created", {
    "thread_id": thread.id,
    "channel_id": channel_id,
    "author_id": author_id,
    "title": title,
    "author_callsign": author_callsign,
    "mentions": self._extract_mentions(body),  # ADD THIS
})

# In create_post(), in the _emit call:
self._emit("ward_room_post_created", {
    "post_id": post.id,
    "thread_id": thread_id,
    "author_id": author_id,
    "parent_id": parent_id,
    "author_callsign": author_callsign,
    "mentions": self._extract_mentions(body),  # ADD THIS
})
```

## Part 4: Rate Limiting

Prevent agents from rapid-fire responding. Add a simple cooldown tracker to the runtime:

```python
# In ProbOSRuntime.__init__:
self._ward_room_cooldowns: dict[str, float] = {}  # agent_id -> last_response_timestamp
_WARD_ROOM_COOLDOWN_SECONDS = 30  # Minimum seconds between responses per agent
```

In `_route_ward_room_event()`, before sending the intent to an agent, check cooldown:

```python
import time

# Before sending intent to each agent:
now = time.time()
last_response = self._ward_room_cooldowns.get(agent_id, 0)
if now - last_response < _WARD_ROOM_COOLDOWN_SECONDS:
    continue  # Skip — agent responded recently

# ... send intent and handle response ...

# After a successful post (response != [NO_RESPONSE]):
self._ward_room_cooldowns[agent_id] = now
```

## Part 5: Prevent Infinite Loops

**Critical:** When an agent posts to the Ward Room, that triggers a `ward_room_post_created` event, which would route back to agents, causing an infinite loop.

Guard against this in `_route_ward_room_event()`:

```python
async def _route_ward_room_event(self, event_type: str, data: dict) -> None:
    """Route Ward Room events to relevant crew agents as intents."""
    if not self.ward_room:
        return

    author_id = data.get("author_id", "")

    # CRITICAL: Don't route agent-authored posts back to agents.
    # Only route posts from the Captain (or external participants).
    # This prevents infinite response loops.
    if author_id != "captain":
        return

    # ... rest of routing logic ...
```

This is the simplest and safest guard: **only the Captain's posts trigger agent responses.** Agent-to-agent Ward Room conversation can be enabled later (AD-407d) with more sophisticated loop detection (conversation depth limits, topic exhaustion detection, turn-taking protocols).

## Part 6: Tests (`tests/test_ward_room_agents.py`)

Create a new test file for Ward Room agent integration.

```python
"""Tests for Ward Room agent integration (AD-407b)."""

import pytest
import pytest_asyncio
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

from probos.ward_room import WardRoomService


@pytest_asyncio.fixture
async def ward_room_svc(tmp_path):
    svc = WardRoomService(db_path=str(tmp_path / "wr.db"))
    await svc.start()
    yield svc
    await svc.stop()
```

### Required test cases:

1. **test_mention_extraction** — `_extract_mentions("Hello @wesley and @worf")` returns `["wesley", "worf"]`
2. **test_mention_extraction_empty** — `_extract_mentions("No mentions here")` returns `[]`
3. **test_thread_event_includes_mentions** — Create a thread with body containing `@wesley`. Verify the emitted event includes `mentions: ["wesley"]`.
4. **test_post_event_includes_mentions** — Create a post with body containing `@troi`. Verify the emitted event includes `mentions: ["troi"]`.
5. **test_captain_posts_trigger_routing** — Verify that when `author_id == "captain"`, the routing method proceeds (does not return early).
6. **test_agent_posts_skip_routing** — Verify that when `author_id != "captain"` (e.g., an agent), `_route_ward_room_event()` returns without sending any intents (loop prevention).
7. **test_cooldown_prevents_rapid_response** — Set an agent's cooldown timestamp to recent (< 30s ago). Verify the agent is skipped.
8. **test_no_response_marker_not_posted** — Simulate an agent returning `[NO_RESPONSE]`. Verify no post is created in the Ward Room.
9. **test_agent_response_posted** — Simulate an agent returning a real response. Verify a post IS created in the Ward Room with the agent's callsign.
10. **test_department_channel_targets_department** — For a department channel (e.g., Engineering), verify only engineering agents are targeted.
11. **test_ship_channel_targets_all_crew** — For the ship-wide channel, verify all crew agents are targeted.

For tests that need a runtime mock, mock:
- `self.registry.all()` → return mock agents with `is_alive=True`, `agent_type`, `id`
- `self.callsign_registry` → mock `resolve()` and `get_callsign()`
- `self.intent_bus.send()` → return `IntentResult` with `result` set
- `self.ward_room` → the real `WardRoomService` from fixture (or mock as needed)

## Part 7: Store Update for Real-Time Thread Refresh

In `ui/src/store/useStore.ts`, ensure the WebSocket handlers for `ward_room_post_created` refresh the thread detail if the user is viewing that thread. This is likely already in place from AD-407c, but verify:

```typescript
case 'ward_room_post_created': {
  const threadId = (data as any).thread_id;
  if (get().wardRoomActiveThread === threadId) {
    get().selectWardRoomThread(threadId);  // Refresh to show new agent reply
  }
  get().refreshWardRoomUnread();
  break;
}
```

If this handler already exists, no changes needed. Just verify it works.

## Verification

```bash
# Run ward room tests (new + existing)
cd d:\ProbOS && uv run pytest tests/test_ward_room.py tests/test_api_wardroom.py tests/test_ward_room_agents.py -v --tb=short

# Run all tests to check for regressions
cd d:\ProbOS && uv run pytest tests/ --tb=short -q

# TypeScript check
cd d:\ProbOS\ui && npx tsc --noEmit

# Vitest
cd d:\ProbOS\ui && npx vitest run
```

## Commit Message

```
Add Ward Room agent integration — crew responds to Captain's posts (AD-407b)

Agents perceive Ward Room threads via IntentBus push (not polling).
Captain's posts route to crew based on channel scope: ship-wide →
all crew, department → department members, @mention → targeted.
LLM decides engagement via personality-shaped system prompt. Agents
return [NO_RESPONSE] to skip. 30s per-agent cooldown prevents spam.
Agent-to-agent routing disabled (loop prevention) — Captain-only
trigger for Phase 1.
```

## What NOT to Build

- Agent-to-agent conversations (Phase 2 — needs turn-taking, depth limits, topic exhaustion detection)
- Proactive posting (agent initiates threads on its own) — future
- Endorsement by agents (agents voting on each other's posts) — future
- Credibility evolution from Ward Room participation — future
- Ward Room perception in the main `perceive()` cycle — we use dedicated intents instead
- Any changes to the dream consolidation pipeline
- Any UI changes beyond verifying the existing WebSocket handler works
