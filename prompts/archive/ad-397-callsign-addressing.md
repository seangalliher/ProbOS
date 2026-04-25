# AD-397: Callsign Addressing

*"Wesley, report." — not "af37b1ec37ac4af49aeb45c3d80e604e, report."*

## Objective

Add callsign-based addressing so the Captain (and eventually other agents) can address crew members by name (`@wesley report`) or by role (`/scout` — already works). Includes a 1:1 session mode where the Captain can have an ongoing conversation with a specific crew member.

## Architecture Summary

Two addressing modes:
- **`@callsign`** → address a specific crew member by name. `@wesley scan for new projects` routes to the Scout agent with callsign "Wesley"
- **`/role`** → address the station/pool. `/scout scan for new projects` routes to any available agent in the scout pool. **This already works** via existing slash commands — no changes needed

## Current State (READ THESE FILES)

Before writing any code, read and understand these files:

1. `config/standing_orders/crew_profiles/*.yaml` — 13 YAML files defining callsigns for agents (e.g., `scout.yaml` has `callsign: "Wesley"`, `builder.yaml` has `callsign: "Scotty"`)
2. `src/probos/crew_profile.py` — `load_seed_profile()` loads YAML profiles. `CrewProfile` dataclass has a `callsign: str = ""` field
3. `src/probos/cognitive/standing_orders.py` — `_build_personality_block()` reads callsign from YAML into system prompt but no reverse lookup exists
4. `src/probos/experience/shell.py` — Shell REPL. `execute_command()` routes `/` to `_dispatch_slash()`, everything else to `_handle_nl()`. No `@` prefix handling
5. `src/probos/substrate/agent.py` — `BaseAgent` has `self.id` (UUID hex), `self.agent_type`, `self.pool`. No `callsign` attribute
6. `src/probos/substrate/registry.py` — `AgentRegistry` indexes by `agent_id`, can search by `pool_name`. No callsign lookup
7. `src/probos/mesh/intent.py` — `IntentBus.broadcast()` sends to all subscribers. No targeted single-agent dispatch. `IntentMessage` in `src/probos/types.py` has no `target_agent_id` field
8. `src/probos/runtime.py` — `ProbOSRuntime`. `self.pools` dict keyed by pool name. `create_pool()` wires agents. This is where the CallsignRegistry should be initialized
9. `src/probos/channels/base.py` — `ChannelAdapter.handle_message()` routes `/` to slash commands, else to `process_natural_language()`. No `@` parsing
10. `src/probos/channels/discord_adapter.py` — Handles Discord bot `@mentions` only. No ProbOS callsign handling
11. `src/probos/experience/renderer.py` — `process_with_feedback()` is the NL processing path from the shell (goes through the Decomposer/Ship's Computer)

## Implementation Plan

### Part 1: Callsign Registry (Ship's Computer Service)

**File: `src/probos/crew_profile.py`** — Add a `CallsignRegistry` class.

```python
class CallsignRegistry:
    """Ship's universal crew directory. Maps callsigns to agent_type and live agent_id."""

    def __init__(self) -> None:
        self._callsign_to_type: dict[str, str] = {}   # "wesley" -> "scout"
        self._type_to_callsign: dict[str, str] = {}   # "scout" -> "Wesley" (original case)
        self._agent_registry: AgentRegistry | None = None

    def load_from_profiles(self, profiles_dir: str = "") -> None:
        """Scan all crew profile YAMLs and build the callsign index."""
        # Iterate all YAML files in crew_profiles/, load each, index callsign -> agent_type
        # Store lowercase key for case-insensitive lookup, preserve original case for display

    def bind_registry(self, registry: AgentRegistry) -> None:
        """Bind the live AgentRegistry for runtime resolution."""
        self._agent_registry = registry

    def resolve(self, callsign: str) -> dict | None:
        """Resolve a callsign to {callsign, agent_type, agent_id, display_name, department}.
        Returns None if callsign not found.
        If multiple agents share the type, picks the first live one from the registry."""

    def get_callsign(self, agent_type: str) -> str:
        """Get the display callsign for an agent type. Returns empty string if none."""

    def all_callsigns(self) -> list[str]:
        """List all registered callsigns (display case). For tab-completion."""
```

Key behaviors:
- Case-insensitive lookup: `@Wesley`, `@wesley`, `@WESLEY` all resolve the same
- At startup, scan all YAML files in `crew_profiles/` directory (not just known files — iterate the directory)
- `resolve()` needs the bound `AgentRegistry` to find a live `agent_id` for the resolved `agent_type`
- If no live agent found for the type, `resolve()` should still return the type info but with `agent_id: None`

### Part 2: Agent Callsign Attribute

**File: `src/probos/substrate/agent.py`** — Add `callsign: str = ""` class attribute to `BaseAgent`.

**File: `src/probos/runtime.py`** — When wiring agents after pool creation, set `agent.callsign` from the `CallsignRegistry` based on the agent's `agent_type`. Add the `CallsignRegistry` as a runtime attribute (`self.callsign_registry`), initialized in `__init__()` with `load_from_profiles()` and `bind_registry(self.registry)`.

### Part 3: Shell `@callsign` Routing

**File: `src/probos/experience/shell.py`**

Add a third routing path in `execute_command()`:

```python
async def execute_command(self, line: str) -> None:
    line = line.strip()
    if not line:
        return
    # 1:1 session mode — route to session agent
    if self._session_callsign and not line.startswith("/"):
        await self._handle_session_message(line)
        return
    if line.startswith("@"):
        await self._handle_at(line)
    elif line.startswith("/"):
        await self._dispatch_slash(line)
    else:
        await self._handle_nl(line)
```

**`_handle_at()` method:**
1. Parse: split on first space — `@callsign` and the rest is the message
2. Resolve callsign via `self.runtime.callsign_registry.resolve(callsign)`
3. If not found, print error: `Unknown crew member: @{callsign}. Use /agents to see available crew.`
4. If found but no live agent, print: `{callsign} is not currently on duty.`
5. If found with live agent, **enter 1:1 session mode** (see Part 4)

### Part 4: 1:1 Session Mode

**File: `src/probos/experience/shell.py`**

Add session state to `Shell.__init__()`:

```python
self._session_callsign: str | None = None       # Display name (e.g., "Wesley")
self._session_agent_id: str | None = None        # Live agent UUID
self._session_agent_type: str | None = None      # e.g., "scout"
self._session_department: str | None = None       # e.g., "science" (for prompt coloring)
```

**Entering a session:** When `_handle_at()` resolves successfully:
- Set the session state fields
- If there was a message after the callsign (`@wesley report`), immediately dispatch it as the first message in the session
- If just `@wesley` with no message, print a greeting: `[1:1 with {callsign} ({department})] Type /bridge to return to the bridge.`
- Change the shell prompt to show the session: `{callsign} ▸ ` instead of the normal prompt (use `_build_prompt()`)

**Session message dispatch** (`_handle_session_message()`):
- Create an `IntentMessage` with:
  - `intent`: `"direct_message"`
  - `params`: `{"text": message_text, "from": "captain", "session": True, "session_history": self._session_history}`
  - `target_agent_id`: the session agent's ID (new field — see Part 5)
- Dispatch via `self.runtime.intent_bus.send()` (new method — see Part 5)
- Display the response with the agent's callsign as the speaker name
- Format: `{callsign}: {response text}` using the department color for the callsign
- After receiving response, append both messages to `_session_history` and store episodic memory (see Part 4b)

**Exiting a session:**
- `/bridge` command clears all session state fields (including `_session_history`) and prints `Returned to bridge.`
- `/quit` still works normally (exits ProbOS)
- `/status`, `/agents`, and other info commands should still work during a session (fall through to `_dispatch_slash()`)
- Note: the `execute_command()` routing already handles this — `/` prefixed commands go to `_dispatch_slash()` even during a session

**Prompt changes** — modify `_build_prompt()`:
- Normal mode: existing prompt (e.g., `probos ▸ `)
- Session mode: `{callsign} ▸ ` (e.g., `Wesley ▸ `)

### Part 4b: Session Memory (Within-Session + Cross-Session)

**"No more really smart two year olds."** — Every 1:1 conversation feeds the agent's episodic memory. Wesley remembers this session, and he'll remember you next time.

**CRITICAL PRINCIPLE — Sovereign Agent Identity:**

Episodic memory is a shared *service* (Ship's Computer infrastructure), but each agent's memories are their own *shard*. Wesley's conversations are Wesley's memories. Scotty cannot see them unless Wesley tells Scotty about them through communication (Ward Room, Phase 33). Three facets of agent identity:

- **Character** (who I am) = Seed personality (YAML Big Five traits), evolved through experience. The core that makes Wesley curious and Worf direct. Expressed most freely in 1:1 sessions.
- **Reason** (how I decide) = `CognitiveAgent.decide()` — rational processing informed by episodic memory, Hebbian patterns, and current context.
- **Duty** (what I serve) = Standing Orders (4-tier constitution) + Trust model + Captain's directives. Internalized principles, not just external rules.

Every agent has all three facets. 1:1 sessions are where Character gets to express itself — the agent responds as *themselves*, with their personality, not as a routing function. Episodic memories from these conversations form the agent's personal history. This is how they develop individuality.

**Implementation constraint:** All recall during 1:1 sessions MUST be scoped to the session agent only. Never surface one agent's memories to another agent.

---

**Within-session context** — Add to `Shell.__init__()`:

```python
self._session_history: list[dict[str, str]] = []  # [{"role": "captain", "text": "..."}, {"role": "wesley", "text": "..."}]
```

In `_handle_session_message()`, after each exchange:
```python
self._session_history.append({"role": "captain", "text": message_text})
self._session_history.append({"role": self._session_callsign, "text": response_text})
```

The `_session_history` is passed in the intent params (see above) so the agent's `decide()` call receives prior conversation turns as context. This gives back-and-forth coherence within a session.

**Cross-session episodic memory** — After each exchange, store an `Episode` in `runtime.episodic_memory`:

```python
if self.runtime.episodic_memory:
    from probos.types import Episode
    import time
    episode = Episode(
        user_input=f"[1:1 with {self._session_callsign}] Captain: {message_text}",
        timestamp=time.time(),
        agent_ids=[self._session_agent_id],
        outcomes=[{
            "intent": "direct_message",
            "success": True,
            "response": response_text,
            "session_type": "1:1",
            "callsign": self._session_callsign,
            "agent_type": self._session_agent_type,
        }],
        reflection=f"Captain had a 1:1 conversation with {self._session_callsign}.",
    )
    await self.runtime.episodic_memory.store(episode)
```

The `user_input` field is what gets embedded for semantic search. Prefixing with `[1:1 with Wesley]` means future `recall()` queries about Wesley will surface these conversations. The `agent_ids` list scopes this episode to this specific agent — it's *their* memory.

**Scoped recall method** — Add to `src/probos/cognitive/episodic.py`:

```python
async def recall_for_agent(self, agent_id: str, query: str, k: int = 5) -> list[Episode]:
    """Recall episodes scoped to a specific agent. Sovereign memory — only this agent's experiences."""
    if not self._collection:
        return []
    count = self._collection.count()
    if count == 0:
        return []

    # Get all episodes, filter to this agent's shard, then semantic rank
    # ChromaDB stores agent_ids as JSON string, so we filter post-query
    n_results = min(k * 5, count)
    result = self._collection.query(
        query_texts=[query],
        n_results=n_results,
        include=["metadatas", "documents", "distances"],
    )
    if not result or not result["ids"] or not result["ids"][0]:
        return []

    episodes: list[Episode] = []
    for i, doc_id in enumerate(result["ids"][0]):
        distance = result["distances"][0][i] if result["distances"] else 0.0
        similarity = 1.0 - distance
        if similarity < self.relevance_threshold:
            continue
        metadata = result["metadatas"][0][i] if result["metadatas"] else {}

        # Sovereign shard filter — only this agent's memories
        agent_ids_json = metadata.get("agent_ids_json", "[]")
        try:
            agent_ids = json.loads(agent_ids_json)
        except (json.JSONDecodeError, TypeError):
            agent_ids = []
        if agent_id not in agent_ids:
            continue

        document = result["documents"][0][i] if result["documents"] else ""
        ep = self._metadata_to_episode(doc_id, document, metadata)
        episodes.append(ep)
        if len(episodes) >= k:
            break

    return episodes
```

**Cross-session recall** — When entering a 1:1 session (`_handle_at()`), recall *only this agent's* past conversations:

```python
if self.runtime.episodic_memory:
    past = await self.runtime.episodic_memory.recall_for_agent(
        agent_id=resolved["agent_id"],
        query=f"1:1 with {callsign}",
        k=3
    )
    if past:
        # Seed session with this agent's own memories of past conversations
        for ep in past:
            self._session_history.append({
                "role": "system",
                "text": f"[Your memory of a previous conversation] {ep.user_input}"
            })
```

Note the framing: "Your memory of a previous conversation" — not "the system's record." These are the agent's own memories being recalled into their consciousness.

**File: `src/probos/cognitive/cognitive_agent.py`** — In `handle_intent()`, when processing a `direct_message` intent, the `session_history` param should be included in the context passed to `decide()`. The agent's standing orders and personality are already in the system prompt via `compose_instructions()`. The session history provides the conversational memory. The agent should respond in first person, as themselves — their Character expressing through Reason, guided by Duty (standing orders).

### Part 5: Targeted IntentBus Dispatch

**File: `src/probos/types.py`** — Add optional field to `IntentMessage`:

```python
@dataclass
class IntentMessage:
    # ... existing fields ...
    target_agent_id: str | None = None  # NEW: if set, deliver only to this agent
```

**File: `src/probos/mesh/intent.py`** — Add `send()` method to `IntentBus`:

```python
async def send(self, intent: IntentMessage) -> IntentResult | None:
    """Deliver an intent to a specific agent (targeted dispatch).
    Requires intent.target_agent_id to be set.
    Returns the single result, or None if the agent isn't subscribed."""
    if not intent.target_agent_id:
        raise ValueError("send() requires target_agent_id")
    handler = self._subscribers.get(intent.target_agent_id)
    if handler is None:
        return None
    try:
        result = await asyncio.wait_for(handler(intent), timeout=intent.ttl_seconds)
        return result
    except asyncio.TimeoutError:
        return IntentResult(agent_id=intent.target_agent_id, confidence=0.0,
                           result="Agent did not respond in time.")
```

Also update `broadcast()`: if `target_agent_id` is set, delegate to `send()` instead of broadcasting. This ensures existing code that calls `broadcast()` with a targeted intent still works correctly.

### Part 6: CognitiveAgent `direct_message` Intent Handling

**File: `src/probos/cognitive/cognitive_agent.py`**

CognitiveAgents already have `handle_intent()` which calls `decide()`. The `direct_message` intent should be handled naturally by the existing `decide()` flow. The agent's standing orders / personality block (already injected via `compose_instructions()`) will make it respond as itself.

Add handling in `handle_intent()` (or in the `decide()` context building) so that when `intent.intent == "direct_message"`:
- The context includes the Captain's message text from `intent.params["text"]`
- The agent knows this is a direct conversation (not a broadcast task)
- The response should be conversational, first-person, using the agent's personality

If `handle_intent()` already delegates cleanly to `decide()`, you may just need to ensure the `direct_message` intent is in the agent's subscribed intent list. Check how existing intents are subscribed in `_wire_agent()` in `runtime.py` — the new intent may need to be added there.

**Important:** The agent must be subscribed to receive `direct_message` intents. Check `_wire_agent()` in runtime.py — if intent subscription is filtered by intent name, add `"direct_message"` to every CognitiveAgent's subscription list.

### Part 7: Channel Adapter Support

**File: `src/probos/channels/base.py`** — Update `handle_message()` to recognize `@callsign` prefix:

```python
async def handle_message(self, message: ChannelMessage) -> str:
    text = message.text.strip()
    if text.startswith("/"):
        # existing slash handling...
    elif text.startswith("@"):
        return await self._handle_callsign_message(text, message)
    else:
        # existing NL handling...
```

Implement `_handle_callsign_message()`:
1. Parse callsign and message text
2. Resolve via `self.runtime.callsign_registry.resolve(callsign)`
3. Create targeted `IntentMessage` with `target_agent_id`
4. Dispatch via `self.runtime.intent_bus.send()`
5. Return the response text

Note: Channel adapters don't have session mode (that's a shell-only interactive concept). Each `@callsign message` through Discord is a one-shot direct message.

### Part 8: `/bridge` Command

**File: `src/probos/experience/shell.py`** — Add `/bridge` to `COMMANDS` dict and `_dispatch_slash()` handlers dict:

```python
# In COMMANDS dict:
"/bridge": "Return to bridge (exit 1:1 crew session)",

# In handlers dict inside _dispatch_slash():
"/bridge": self._cmd_bridge,
```

Implement `_cmd_bridge()`:
- If in a session: clear session state, print `Returned to bridge.`
- If not in a session: print `You're already on the bridge.`

### Part 9: Agent Display Names in Output

Update any shell output that currently shows agent IDs to prefer callsigns where available. Key locations:

- **`/agents` command** (`_cmd_agents()`): Show callsign next to agent type and ID. Format: `{agent_type} ({callsign}) — {agent_id_short}`
- **`/status` command**: If it shows agent info, include callsigns
- **Scout report output**: The Scout already knows its callsign from its system prompt. If the Scout report currently shows the agent ID in output, the callsign should appear instead. Check how Scout results are displayed in the shell

Use `self.runtime.callsign_registry.get_callsign(agent_type)` for lookups.

## Testing

Create `tests/test_callsign_registry.py`:

1. **`test_load_from_profiles`** — Load real YAML profiles, verify all 12 callsigns indexed
2. **`test_resolve_known_callsign`** — Resolve "wesley" → agent_type "scout"
3. **`test_resolve_case_insensitive`** — "Wesley", "wesley", "WESLEY" all resolve identically
4. **`test_resolve_unknown_callsign`** — Returns None for "picard"
5. **`test_get_callsign_by_type`** — `get_callsign("builder")` returns "Scotty"
6. **`test_all_callsigns`** — Returns list of all display-case callsigns
7. **`test_resolve_with_live_agent`** — Bind a mock AgentRegistry with a live scout agent, verify `resolve("wesley")` includes the `agent_id`
8. **`test_resolve_no_live_agent`** — Bind a mock AgentRegistry with no scout, verify `resolve("wesley")` returns `agent_id: None`

Create `tests/test_targeted_dispatch.py`:

9. **`test_send_to_subscribed_agent`** — IntentBus.send() delivers to the target agent and returns result
10. **`test_send_to_unknown_agent`** — Returns None
11. **`test_send_timeout`** — Agent handler that sleeps too long, verify timeout result
12. **`test_broadcast_with_target_delegates_to_send`** — broadcast() with target_agent_id only delivers to that one agent

Create `tests/test_session_mode.py`:

13. **`test_at_prefix_enters_session`** — `@wesley` sets session state on the shell
14. **`test_session_routes_to_agent`** — During session, NL input dispatches to session agent (not decomposer)
15. **`test_bridge_exits_session`** — `/bridge` clears session state
16. **`test_slash_commands_work_in_session`** — `/status` still works during a session
17. **`test_at_with_message`** — `@wesley report` enters session AND dispatches "report"
18. **`test_session_history_accumulates`** — After 2 exchanges, `_session_history` has 4 entries (2 captain + 2 agent)
19. **`test_session_stores_episodic_memory`** — Each exchange stores an Episode with `session_type: "1:1"`, callsign, and agent_type in outcomes
20. **`test_session_recalls_past_conversations`** — When entering a session, past 1:1 episodes are recalled and seeded into session_history
21. **`test_bridge_clears_history`** — `/bridge` clears `_session_history`
22. **`test_recall_scoped_to_agent`** — `recall_for_agent("wesley_id", ...)` returns only Wesley's episodes, NOT Scotty's episodes stored in the same EpisodicMemory
23. **`test_sovereign_memory_isolation`** — Store episodes for Wesley and Scotty. Recall for Wesley returns only Wesley's. Recall for Scotty returns only Scotty's. Shared infrastructure, sovereign identity

Add tests to `tests/test_channel_adapter.py` (or create if needed):

24. **`test_channel_at_callsign`** — Channel adapter routes `@wesley scan` to the scout agent

Target: **24+ tests**, all passing.

## What This AD Does NOT Include (Deferred)

- **Agent-to-agent @callsign messaging** — The registry and resolution mechanism support it, but agent-side `@callsign` in Ward Room messages is Phase 33
- **Tab-completion** — `all_callsigns()` is available for it, but shell tab-completion is a UX enhancement for later
- **HXI visual session indicator** — The shell shows the session in its prompt, but HXI Bridge panel changes are Phase 34
- **Ambiguity handling for scaled pools** — If 3 builders all need unique callsigns, that's Phase 33. For now, one callsign per agent_type

## Verification Checklist

After implementation, verify:
- [ ] `@wesley report` in the shell dispatches to the Scout agent and shows a response
- [ ] `@Wesley`, `@WESLEY`, `@wesley` all work the same
- [ ] `@scotty` reaches the Builder
- [ ] `@picard` shows "Unknown crew member" error
- [ ] Shell prompt changes to `Wesley ▸` during a session
- [ ] `/bridge` returns to normal prompt
- [ ] `/status` works during a session
- [ ] `/agents` output shows callsigns
- [ ] All 18+ new tests pass
- [ ] All existing tests still pass (run full suite)
