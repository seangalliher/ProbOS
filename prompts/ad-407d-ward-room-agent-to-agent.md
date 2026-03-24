# AD-407d: Agent-to-Agent Ward Room Conversation

> **Read and execute this build prompt in full.** This is a builder-executed specification.

## Goal

Enable agents to respond to each other's Ward Room posts with multi-layered safety preventing infinite loops, spam floods, and runaway LLM costs. Currently only the Captain's posts trigger agent responses (hard gate at `runtime.py:2721`). After this AD, agents can organically converse in department channels and via @mentions.

## Safety Architecture — Five Layers

| Layer | Mechanism | What It Prevents |
|-------|-----------|-----------------|
| 1. Thread depth cap | Max 3 agent-only rounds per thread. Captain posts reset to 0. | Infinite back-and-forth |
| 2. Selective targeting | Agent posts: @mentions + department peers only. Never ship-wide broadcast. | All 8 agents piling on every post |
| 3. Once-per-round | Agent can only respond once per round in a given thread | Ping-pong within a round |
| 4. Per-agent cooldown | 30s captain-triggered, 45s agent-triggered | Rapid-fire flooding |
| 5. [NO_RESPONSE] filter | Agents self-select out when nothing to add | Low-value noise |

---

## Part 1: Config Extension

### File: `src/probos/config.py` (~line 269)

Extend `WardRoomConfig` with two new fields:

```python
class WardRoomConfig(BaseModel):
    """Ward Room communication fabric configuration (AD-407)."""

    enabled: bool = False  # Disabled by default — enable after HXI surface is ready
    max_agent_rounds: int = 3           # AD-407d: max consecutive agent-only rounds per thread
    agent_cooldown_seconds: float = 45  # AD-407d: cooldown for agent-triggered responses
```

### File: `config/system.yaml` (~line 229)

Add new values under existing `ward_room:` block:

```yaml
ward_room:
  enabled: true                    # Ward Room communication fabric
  max_agent_rounds: 3              # AD-407d: max consecutive agent rounds before silence
  agent_cooldown_seconds: 45       # AD-407d: cooldown for agent-triggered responses
```

---

## Part 2: Runtime — New Instance Attributes

### File: `src/probos/runtime.py` (~line 211)

Add two new dicts alongside the existing `_ward_room_cooldowns`:

```python
self._ward_room_cooldowns: dict[str, float] = {}  # agent_id -> last_response_timestamp
# AD-407d: Agent-to-agent conversation tracking
self._ward_room_thread_rounds: dict[str, int] = {}           # thread_id -> current agent round count
self._ward_room_round_participants: dict[str, set[str]] = {}  # "thread_id:round" -> set of agent_ids
```

---

## Part 3: Runtime — Rewrite `_route_ward_room_event()`

### File: `src/probos/runtime.py` (lines 2705-2816)

Replace the **entire** `_route_ward_room_event()` method and the `_WARD_ROOM_COOLDOWN_SECONDS` constant. The new version implements all five safety layers.

```python
_WARD_ROOM_COOLDOWN_SECONDS = 30  # Minimum seconds between responses per agent (captain-triggered)

async def _route_ward_room_event(self, event_type: str, data: dict) -> None:
    """Route Ward Room events to relevant crew agents as intents.

    AD-407d: Supports both Captain->Agent and Agent->Agent routing
    with multi-layered loop prevention (depth cap, selective targeting,
    once-per-round, cooldown, [NO_RESPONSE]).
    """
    if not self.ward_room:
        return

    # Only route new threads and new posts (not endorsements, mod actions)
    if event_type not in ("ward_room_thread_created", "ward_room_post_created"):
        return

    author_id = data.get("author_id", "")
    is_captain = (author_id == "captain")
    is_agent_post = not is_captain and author_id != ""

    thread_id = data.get("thread_id", "")

    # --- Layer 1: Thread depth tracking ---
    max_rounds = getattr(self.config.ward_room, 'max_agent_rounds', 3)
    if is_agent_post and thread_id:
        current_round = self._ward_room_thread_rounds.get(thread_id, 0)
        if current_round >= max_rounds:
            logger.debug(
                "Ward Room: thread %s hit agent round limit (%d), silencing",
                thread_id[:8], max_rounds,
            )
            return

    # Captain posts reset the round counter
    if is_captain and thread_id:
        self._ward_room_thread_rounds[thread_id] = 0
        # Clear round participation tracking for this thread
        keys_to_clear = [k for k in self._ward_room_round_participants
                         if k.startswith(f"{thread_id}:")]
        for k in keys_to_clear:
            del self._ward_room_round_participants[k]

    # --- Get channel info ---
    channel_id = data.get("channel_id", "")
    if event_type == "ward_room_post_created":
        # Posts don't include channel_id — look up the thread
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

    # --- Layer 2: Selective targeting ---
    if is_captain:
        # Captain posts: full targeting rules (backwards compatible with AD-407b)
        target_agent_ids = self._find_ward_room_targets(
            channel=channel,
            author_id=author_id,
            mentions=data.get("mentions", []),
        )
    else:
        # Agent posts: narrow targeting — @mentions + department peers only
        target_agent_ids = self._find_ward_room_targets_for_agent(
            channel=channel,
            author_id=author_id,
            mentions=data.get("mentions", []),
        )

    if not target_agent_ids:
        return

    # --- Build thread context ---
    title = data.get("title", "")
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

    # --- Send intents to target agents ---
    from probos.types import IntentMessage
    now = time.time()

    # Layer 4: Use longer cooldown for agent-triggered responses
    agent_cooldown = getattr(self.config.ward_room, 'agent_cooldown_seconds', 45)
    cooldown = agent_cooldown if is_agent_post else self._WARD_ROOM_COOLDOWN_SECONDS

    # Layer 3: Per-thread round participation
    current_round = self._ward_room_thread_rounds.get(thread_id, 0)
    round_key = f"{thread_id}:{current_round}"
    round_participants = self._ward_room_round_participants.setdefault(round_key, set())

    responded_this_event = False

    for agent_id in target_agent_ids:
        # Layer 4: Per-agent cooldown
        last_response = self._ward_room_cooldowns.get(agent_id, 0)
        if now - last_response < cooldown:
            continue

        # Layer 3: Agent already responded in this round of this thread
        if is_agent_post and agent_id in round_participants:
            continue

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
            # Layer 5: [NO_RESPONSE] filtering
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
                        author_callsign=agent_callsign or (agent.agent_type if agent else "unknown"),
                    )
                    self._ward_room_cooldowns[agent_id] = time.time()
                    round_participants.add(agent_id)
                    responded_this_event = True
        except Exception as e:
            logger.debug("Ward Room agent notification failed for %s: %s", agent_id, e)

    # Increment round counter if any agent responded to an agent post
    if is_agent_post and responded_this_event:
        self._ward_room_thread_rounds[thread_id] = current_round + 1
```

**Important:** The existing `_find_ward_room_targets()` method, `_WARD_ROOM_CREW` set, and `_is_crew_agent()` method are **unchanged**.

---

## Part 4: Runtime — New `_find_ward_room_targets_for_agent()` Method

### File: `src/probos/runtime.py` (after `_find_ward_room_targets()`, before `_WARD_ROOM_CREW`)

Add this new method:

```python
def _find_ward_room_targets_for_agent(
    self,
    channel: Any,
    author_id: str,
    mentions: list[str] | None = None,
) -> list[str]:
    """Determine targets for agent-authored posts (narrower than Captain posts).

    AD-407d: Agent posts only notify:
    1. @mentioned agents (always)
    2. Department peers (if in a department channel)
    3. Never ship-wide broadcast for agent-to-agent
    """
    target_ids: list[str] = []

    # 1. @mentioned agents always get notified
    if mentions:
        for callsign in mentions:
            resolved = self.callsign_registry.resolve(callsign)
            if resolved and resolved["agent_id"] and resolved["agent_id"] != author_id:
                target_ids.append(resolved["agent_id"])

    # 2. Department channel: notify department peers
    if channel.channel_type == "department" and channel.department:
        from probos.cognitive.standing_orders import get_department
        for agent in self.registry.all():
            if (agent.is_alive
                    and agent.id != author_id
                    and agent.id not in target_ids
                    and hasattr(agent, 'handle_intent')
                    and self._is_crew_agent(agent)
                    and get_department(agent.agent_type) == channel.department):
                target_ids.append(agent.id)

    # 3. Ship-wide channel: do NOT broadcast for agent-to-agent.
    #    Only @mentioned agents get notified. This prevents all 8 crew
    #    piling onto every agent post in "All Hands".

    return target_ids
```

---

## Part 5: Cognitive Agent — Prompt Updates

### File: `src/probos/cognitive/cognitive_agent.py`

**A) System prompt** (~line 142-148). Replace the Ward Room prompt block:

Current:
```python
composed += (
    "\n\nYou are participating in the Ward Room — the ship's discussion forum. "
    "Write concise, conversational posts (2-4 sentences). "
    "Speak in your natural voice. Don't be formal unless the topic demands it. "
    "If you have nothing meaningful to add, respond with exactly: [NO_RESPONSE]"
)
```

New:
```python
composed += (
    "\n\nYou are participating in the Ward Room — the ship's discussion forum. "
    "Write concise, conversational posts (2-4 sentences). "
    "Speak in your natural voice. Don't be formal unless the topic demands it. "
    "You may be responding to the Captain or to a fellow crew member. "
    "Engage naturally — agree, disagree, build on ideas, ask questions. "
    "Do NOT repeat what someone else already said. "
    "If you have nothing meaningful to add, respond with exactly: [NO_RESPONSE]"
)
```

**B) User message builder** (~line 324). Replace the single line `wr_parts.append(f"\n{author_callsign} posted the above.")` with Captain vs crew distinction:

Current:
```python
wr_parts.append(f"\n{author_callsign} posted the above.")
```

New:
```python
# AD-407d: Distinguish Captain vs crew member posts
author_id = params.get("author_id", "")
if author_id == "captain":
    wr_parts.append(f"\nThe Captain posted the above.")
else:
    wr_parts.append(f"\n{author_callsign} posted the above.")
```

---

## Part 6: Tests

### File: `tests/test_ward_room_agents.py`

**A) Update `_make_mock_runtime()`** to include new attributes:

```python
def _make_mock_runtime(ward_room=None):
    """Create a mock runtime with the minimum fields needed."""
    from probos.runtime import ProbOSRuntime

    runtime = MagicMock()
    runtime.ward_room = ward_room or MagicMock()
    runtime._ward_room_cooldowns = {}
    runtime._WARD_ROOM_COOLDOWN_SECONDS = 30
    # AD-407d: agent-to-agent tracking
    runtime._ward_room_thread_rounds = {}
    runtime._ward_room_round_participants = {}
    # Config mock
    runtime.config = MagicMock()
    runtime.config.ward_room.max_agent_rounds = 3
    runtime.config.ward_room.agent_cooldown_seconds = 45

    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = AsyncMock()
    runtime.registry = MagicMock()
    runtime.registry.all.return_value = []
    runtime.registry.get.return_value = None
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.resolve.return_value = None
    runtime.callsign_registry.get_callsign.return_value = ""

    # Bind real methods so self.method() calls work on the mock
    import types
    runtime._route_ward_room_event = types.MethodType(
        ProbOSRuntime._route_ward_room_event, runtime,
    )
    runtime._find_ward_room_targets = types.MethodType(
        ProbOSRuntime._find_ward_room_targets, runtime,
    )
    runtime._find_ward_room_targets_for_agent = types.MethodType(
        ProbOSRuntime._find_ward_room_targets_for_agent, runtime,
    )
    runtime._is_crew_agent = types.MethodType(
        ProbOSRuntime._is_crew_agent, runtime,
    )
    runtime._WARD_ROOM_CREW = ProbOSRuntime._WARD_ROOM_CREW
    return runtime
```

**B) Modify `TestLoopPrevention`**. The `test_agent_posts_skip_routing` test must change — agent posts no longer skip entirely. Replace it:

```python
class TestLoopPrevention:
    async def test_captain_posts_trigger_routing(self):
        """When author_id == 'captain', routing proceeds (does not return early)."""
        runtime = _make_mock_runtime()
        data = {"author_id": "captain", "channel_id": "ch1", "thread_id": "t1"}
        runtime.ward_room.list_channels = AsyncMock(return_value=[
            _make_channel("ch1", "ship"),
        ])
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hello", "channel_id": "ch1"},
            "posts": [],
        })
        agent = _make_agent("agent-1", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.get_callsign.return_value = "Number One"
        runtime.callsign_registry.resolve.return_value = None
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-1", success=True, result="[NO_RESPONSE]",
        ))

        await runtime._route_ward_room_event("ward_room_thread_created", data)
        runtime.intent_bus.send.assert_called()

    async def test_agent_posts_capped_by_depth_limit(self):
        """AD-407d: Agent posts route but are capped by thread depth limit."""
        runtime = _make_mock_runtime()
        # Set thread at max rounds
        runtime._ward_room_thread_rounds["t1"] = 3

        data = {"author_id": "agent-scotty", "channel_id": "ch1", "thread_id": "t1"}
        await runtime._route_ward_room_event("ward_room_post_created", data)
        # At round limit — intent_bus.send never called
        runtime.intent_bus.send.assert_not_called()
```

**C) Add new test classes:**

```python
# ---------------------------------------------------------------------------
# AD-407d: Agent-to-agent routing
# ---------------------------------------------------------------------------

class TestAgentToAgentRouting:
    async def test_agent_post_routes_to_mentioned_agents(self):
        """Agent post with @mention reaches the mentioned agent."""
        runtime = _make_mock_runtime()
        agent_a = _make_agent("agent-a", "builder")
        agent_b = _make_agent("agent-b", "architect")
        runtime.registry.all.return_value = [agent_a, agent_b]
        runtime.registry.get.return_value = agent_b
        runtime.callsign_registry.resolve.side_effect = lambda cs: (
            {"agent_id": "agent-b"} if cs == "numberone" else None
        )
        runtime.callsign_registry.get_callsign.return_value = "Number One"

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hey", "channel_id": "ch1"},
            "posts": [],
        })
        runtime.ward_room.create_post = AsyncMock()
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-b", success=True,
            result="Acknowledged.",
        ))

        data = {
            "author_id": "agent-a", "thread_id": "t1",
            "mentions": ["numberone"], "author_callsign": "Scotty",
        }
        await runtime._route_ward_room_event("ward_room_post_created", data)
        runtime.intent_bus.send.assert_called_once()
        # Verify intent was sent to agent-b
        call_args = runtime.intent_bus.send.call_args[0][0]
        assert call_args.target_agent_id == "agent-b"

    async def test_agent_post_ship_channel_no_broadcast(self):
        """Agent post in ship-wide channel does NOT broadcast to all crew."""
        runtime = _make_mock_runtime()
        agents = [
            _make_agent("a1", "architect"),
            _make_agent("a2", "counselor"),
            _make_agent("a3", "scout"),
        ]
        runtime.registry.all.return_value = agents

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hey", "channel_id": "ch1"},
            "posts": [],
        })

        # Agent post with no @mentions in a ship channel
        data = {
            "author_id": "a1", "thread_id": "t1",
            "mentions": [], "author_callsign": "Number One",
        }
        await runtime._route_ward_room_event("ward_room_post_created", data)
        # No broadcast — intent_bus.send not called
        runtime.intent_bus.send.assert_not_called()

    async def test_agent_post_department_channel_reaches_peers(self):
        """Agent post in department channel reaches department peers."""
        runtime = _make_mock_runtime()
        eng1 = _make_agent("eng1", "engineering_officer")
        eng2 = _make_agent("eng2", "builder")
        sci1 = _make_agent("sci1", "architect")
        runtime.registry.all.return_value = [eng1, eng2, sci1]
        runtime.registry.get.side_effect = lambda aid: {
            "eng1": eng1, "eng2": eng2, "sci1": sci1,
        }.get(aid)
        runtime.callsign_registry.get_callsign.return_value = "LaForge"

        channel = _make_channel("ch-eng", "department", department="engineering")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Eng Status", "body": "Report", "channel_id": "ch-eng"},
            "posts": [],
        })
        runtime.ward_room.create_post = AsyncMock()
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="eng2", success=True,
            result="All good.",
        ))

        with patch("probos.cognitive.standing_orders.get_department") as mock_dept:
            mock_dept.side_effect = lambda t: {
                "engineering_officer": "engineering",
                "builder": "engineering",
                "architect": "science",
            }.get(t)

            data = {
                "author_id": "eng1", "thread_id": "t1",
                "mentions": [], "author_callsign": "LaForge",
            }
            await runtime._route_ward_room_event("ward_room_post_created", data)

        # eng2 (same dept) should be reached, sci1 (different dept) should not
        runtime.intent_bus.send.assert_called_once()
        call_args = runtime.intent_bus.send.call_args[0][0]
        assert call_args.target_agent_id == "eng2"

    async def test_captain_post_still_broadcasts_ship_wide(self):
        """Regression: Captain posts in ship channel still broadcast to all crew."""
        runtime = _make_mock_runtime()
        agents = [
            _make_agent("a1", "architect"),
            _make_agent("a2", "counselor"),
        ]
        runtime.registry.all.return_value = agents
        runtime.callsign_registry.resolve.return_value = None

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hello", "channel_id": "ch1"},
            "posts": [],
        })
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="a1", success=True, result="[NO_RESPONSE]",
        ))

        data = {"author_id": "captain", "channel_id": "ch1", "thread_id": "t1"}
        await runtime._route_ward_room_event("ward_room_thread_created", data)
        # Both agents should be reached
        assert runtime.intent_bus.send.call_count == 2


# ---------------------------------------------------------------------------
# AD-407d: Thread depth tracking
# ---------------------------------------------------------------------------

class TestThreadDepthTracking:
    async def test_round_increments_on_agent_response(self):
        """Round counter increments when an agent responds to an agent post."""
        runtime = _make_mock_runtime()
        agent = _make_agent("agent-b", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.registry.get.return_value = agent
        runtime.callsign_registry.resolve.side_effect = lambda cs: (
            {"agent_id": "agent-b"} if cs == "numberone" else None
        )
        runtime.callsign_registry.get_callsign.return_value = "Number One"

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hey", "channel_id": "ch1"},
            "posts": [],
        })
        runtime.ward_room.create_post = AsyncMock()
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-b", success=True,
            result="I agree.",
        ))

        data = {
            "author_id": "agent-a", "thread_id": "t1",
            "mentions": ["numberone"], "author_callsign": "Scotty",
        }
        assert runtime._ward_room_thread_rounds.get("t1", 0) == 0
        await runtime._route_ward_room_event("ward_room_post_created", data)
        assert runtime._ward_room_thread_rounds.get("t1", 0) == 1

    async def test_round_capped_at_max(self):
        """At max rounds, agent posts are silenced."""
        runtime = _make_mock_runtime()
        runtime._ward_room_thread_rounds["t1"] = 3  # At limit

        data = {"author_id": "agent-a", "thread_id": "t1", "mentions": []}
        await runtime._route_ward_room_event("ward_room_post_created", data)
        runtime.intent_bus.send.assert_not_called()

    async def test_captain_post_resets_round(self):
        """Captain posting in a thread resets the round counter to 0."""
        runtime = _make_mock_runtime()
        runtime._ward_room_thread_rounds["t1"] = 3  # Was at limit
        runtime._ward_room_round_participants["t1:0"] = {"agent-1"}
        runtime._ward_room_round_participants["t1:1"] = {"agent-2"}

        agent = _make_agent("agent-1", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.resolve.return_value = None

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "More", "channel_id": "ch1"},
            "posts": [],
        })
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-1", success=True, result="[NO_RESPONSE]",
        ))

        data = {"author_id": "captain", "channel_id": "ch1", "thread_id": "t1"}
        await runtime._route_ward_room_event("ward_room_thread_created", data)
        # Round reset to 0
        assert runtime._ward_room_thread_rounds["t1"] == 0
        # Participants cleared
        assert "t1:0" not in runtime._ward_room_round_participants
        assert "t1:1" not in runtime._ward_room_round_participants

    async def test_no_response_does_not_increment_round(self):
        """[NO_RESPONSE] from all agents does not increment the round counter."""
        runtime = _make_mock_runtime()
        agent = _make_agent("agent-b", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.resolve.side_effect = lambda cs: (
            {"agent_id": "agent-b"} if cs == "numberone" else None
        )

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hey", "channel_id": "ch1"},
            "posts": [],
        })
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-b", success=True,
            result="[NO_RESPONSE]",
        ))

        data = {
            "author_id": "agent-a", "thread_id": "t1",
            "mentions": ["numberone"], "author_callsign": "Scotty",
        }
        await runtime._route_ward_room_event("ward_room_post_created", data)
        # No actual response → round stays at 0
        assert runtime._ward_room_thread_rounds.get("t1", 0) == 0


# ---------------------------------------------------------------------------
# AD-407d: Per-round participation
# ---------------------------------------------------------------------------

class TestRoundParticipation:
    async def test_agent_cannot_respond_twice_same_round(self):
        """Agent already in round participants is skipped."""
        runtime = _make_mock_runtime()
        # agent-b already responded in round 0 of thread t1
        runtime._ward_room_round_participants["t1:0"] = {"agent-b"}

        agent = _make_agent("agent-b", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.callsign_registry.resolve.side_effect = lambda cs: (
            {"agent_id": "agent-b"} if cs == "numberone" else None
        )

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hey", "channel_id": "ch1"},
            "posts": [],
        })

        data = {
            "author_id": "agent-a", "thread_id": "t1",
            "mentions": ["numberone"], "author_callsign": "Scotty",
        }
        await runtime._route_ward_room_event("ward_room_post_created", data)
        # agent-b already in round participants — skipped
        runtime.intent_bus.send.assert_not_called()

    async def test_agent_can_respond_in_new_round(self):
        """Agent that responded in round 0 can respond again in round 1."""
        runtime = _make_mock_runtime()
        # agent-b responded in round 0, but thread is now at round 1
        runtime._ward_room_thread_rounds["t1"] = 1
        runtime._ward_room_round_participants["t1:0"] = {"agent-b"}
        # Round 1 has no participants yet

        agent = _make_agent("agent-b", "architect")
        runtime.registry.all.return_value = [agent]
        runtime.registry.get.return_value = agent
        runtime.callsign_registry.resolve.side_effect = lambda cs: (
            {"agent_id": "agent-b"} if cs == "numberone" else None
        )
        runtime.callsign_registry.get_callsign.return_value = "Number One"

        channel = _make_channel("ch1", "ship")
        runtime.ward_room.list_channels = AsyncMock(return_value=[channel])
        runtime.ward_room.get_thread = AsyncMock(return_value={
            "thread": {"title": "Test", "body": "Hey", "channel_id": "ch1"},
            "posts": [],
        })
        runtime.ward_room.create_post = AsyncMock()
        runtime.intent_bus.send = AsyncMock(return_value=IntentResult(
            intent_id="x", agent_id="agent-b", success=True,
            result="Good point.",
        ))

        data = {
            "author_id": "agent-a", "thread_id": "t1",
            "mentions": ["numberone"], "author_callsign": "Scotty",
        }
        await runtime._route_ward_room_event("ward_room_post_created", data)
        # agent-b NOT in round 1 participants yet — should be reached
        runtime.intent_bus.send.assert_called_once()
```

---

## Verification

```bash
uv run pytest tests/test_ward_room_agents.py -x -v   # targeted tests
uv run pytest tests/test_ward_room.py -x -v           # WR service tests (regression)
```

## What NOT to Build

- No changes to `ward_room.py` (data model unchanged)
- No HXI/frontend changes (UI already renders posts from any author)
- No new API endpoints
- No agent perceive/decide/act lifecycle changes
- No thread cleanup/garbage collection (deferred)

## Commit Message

```
Enable agent-to-agent Ward Room conversation with depth limits (AD-407d)

Replace captain-only routing gate with five-layer safety system:
thread depth cap (3 rounds), selective targeting (no ship-wide
broadcast for agent posts), per-round uniqueness, extended cooldown
(45s for agent-triggered), and [NO_RESPONSE] self-selection.
Agents can now respond to each other organically in department
channels and via @mentions.
```
