# AD-430c: Memory-Aware Decision Making + Act-Store Lifecycle Hook (Pillars 4-5)

## Context

AD-430a added episode write paths for proactive thoughts and Ward Room conversations. AD-430b added HXI 1:1 history passing and episode storage. Agents now *create* memories — but they don't *use* them. A direct message or Ward Room notification triggers `perceive()` → `decide()` with zero memory context. The agent has no recall of past interactions, past observations, or past decisions.

This AD closes the loop: agents recall relevant memories before deciding, and every crew action produces a memory record as a universal safety net.

**Prerequisite:** AD-430a and AD-430b must be merged first.

**Key architectural finding:** No domain agent overrides `handle_intent()`. All crew agents (Builder, Architect, Counselor, Scout, Security, Operations, Engineering, Diagnostician, Surgeon, Pathologist, Pharmacist) inherit from `CognitiveAgent`. Modifying `handle_intent()` once covers all of them.

## Changes

### Step 1 (Pillar 4): Memory recall in handle_intent()

**File:** `src/probos/cognitive/cognitive_agent.py`

Find `handle_intent()` (line 223). Between the `perceive()` call (line 246) and the `decide()` call (line 247), insert memory recall:

```python
    # Cognitive lifecycle — LLM-guided reasoning
    observation = await self.perceive(intent)

    # AD-430c (Pillar 4): Enrich observation with relevant episodic memories
    observation = await self._recall_relevant_memories(intent, observation)

    decision = await self.decide(observation)
```

### Step 2 (Pillar 4): The _recall_relevant_memories() method

**File:** `src/probos/cognitive/cognitive_agent.py`

Add this method to the `CognitiveAgent` class. Place it after `_build_user_message()` (after line 424) and before `_resolve_tier()` (line 426):

```python
async def _recall_relevant_memories(self, intent: IntentMessage, observation: dict) -> dict:
    """AD-430c: Inject relevant episodic memories into observation for decide().

    Only fires for crew agents on conversational intents. Proactive think
    already gets memory context via _gather_context() — skip to avoid duplication.
    """
    # Skip proactive_think — already has memory context from proactive loop
    if intent.intent == "proactive_think":
        return observation

    # Guard: need runtime + episodic memory + crew check
    if not self._runtime:
        return observation
    if not hasattr(self._runtime, 'episodic_memory') or not self._runtime.episodic_memory:
        return observation
    if not hasattr(self._runtime, '_is_crew_agent') or not self._runtime._is_crew_agent(self):
        return observation

    try:
        # Build a semantic query from the intent content
        params = observation.get("params", {})
        if intent.intent == "direct_message":
            query = params.get("text", "")[:200]
        elif intent.intent == "ward_room_notification":
            query = f"{params.get('title', '')} {params.get('text', '')}".strip()[:200]
        else:
            query = intent.context[:200] if intent.context else intent.intent

        if not query:
            return observation

        episodes = await self._runtime.episodic_memory.recall_for_agent(
            self.id, query, k=3
        )
        if episodes:
            observation["recent_memories"] = [
                {
                    "input": ep.user_input[:200] if ep.user_input else "",
                    "reflection": ep.reflection[:200] if ep.reflection else "",
                }
                for ep in episodes
            ]
    except Exception:
        pass  # Non-critical — agent proceeds without memory context

    return observation
```

### Step 3 (Pillar 4): Render memories in _build_user_message()

**File:** `src/probos/cognitive/cognitive_agent.py`

The `direct_message` and `ward_room_notification` branches of `_build_user_message()` need to render memory context when present. The `proactive_think` branch already renders memories (lines 373-382) — follow the same pattern.

**3a. Direct message (line 310-322):**

Replace the `direct_message` block:

```python
        # AD-397: direct_message — conversational context for 1:1 sessions
        if intent_name == "direct_message":
            parts: list[str] = []

            # AD-430c: Episodic memory context
            memories = observation.get("recent_memories", [])
            if memories:
                parts.append("Your recent memories (relevant past experiences):")
                for m in memories:
                    if m.get("reflection"):
                        parts.append(f"  - {m['reflection']}")
                    elif m.get("input"):
                        parts.append(f"  - {m['input']}")
                parts.append("")

            session_history = params.get("session_history", [])
            if session_history:
                parts.append("Previous conversation:")
                for entry in session_history:
                    role = entry.get("role", "unknown")
                    text = entry.get("text", "")
                    parts.append(f"  {role}: {text}")
                parts.append("")
            parts.append(f"Captain says: {params.get('text', '')}")
            return "\n".join(parts)
```

**3b. Ward Room notification (line 324-344):**

Add memory rendering after the `[Ward Room — #channel]` header. Insert before the author identification (before line 337):

```python
        # AD-407b: ward_room_notification — thread context for Ward Room
        if intent_name == "ward_room_notification":
            channel_name = params.get("channel_name", "")
            author_callsign = params.get("author_callsign", "unknown")
            title = params.get("title", "")
            context = observation.get("context", "")

            wr_parts: list[str] = []
            wr_parts.append(f"[Ward Room — #{channel_name}]")
            wr_parts.append(f"Thread: {title}")

            # AD-430c: Episodic memory context
            memories = observation.get("recent_memories", [])
            if memories:
                wr_parts.append("")
                wr_parts.append("Your relevant memories:")
                for m in memories:
                    if m.get("reflection"):
                        wr_parts.append(f"  - {m['reflection']}")
                    elif m.get("input"):
                        wr_parts.append(f"  - {m['input']}")

            if context:
                wr_parts.append(f"\nConversation so far:\n{context}")
            # AD-407d: Distinguish Captain vs crew member posts
            author_id = params.get("author_id", "")
            if author_id == "captain":
                wr_parts.append(f"\nThe Captain posted the above.")
            else:
                wr_parts.append(f"\n{author_callsign} posted the above.")
            wr_parts.append("Respond naturally as yourself. Share your perspective if you have something meaningful to contribute.")
            wr_parts.append("If this topic is outside your expertise or you have nothing to add, respond with exactly: [NO_RESPONSE]")
            return "\n".join(wr_parts)
```

### Step 4 (Pillar 5): Act-store lifecycle hook in handle_intent()

**File:** `src/probos/cognitive/cognitive_agent.py`

In `handle_intent()`, after line 250 (`report = await self.report(result)`) and before line 252 (`success = report.get("success", False)`), insert the episode storage hook:

```python
    report = await self.report(result)

    # AD-430c (Pillar 5): Store action as episodic memory for crew agents
    await self._store_action_episode(intent, observation, report)

    success = report.get("success", False)
```

### Step 5 (Pillar 5): The _store_action_episode() method

**File:** `src/probos/cognitive/cognitive_agent.py`

Add this method near `_recall_relevant_memories()`:

```python
async def _store_action_episode(self, intent: IntentMessage, observation: dict, report: dict) -> None:
    """AD-430c: Universal post-action episode storage for crew agents.

    This is the safety net — ensures every crew agent action produces a memory
    record. Callers that already store episodes (proactive loop, Ward Room
    service, HXI API) produce sovereign-shard episodes through their own paths,
    but this hook captures any actions that would otherwise be missed.

    Deduplication: proactive_think is skipped (AD-430a stores in proactive.py).
    ward_room_notification is skipped (AD-430a stores in ward_room.py).
    direct_message from hxi_profile is skipped (AD-430b stores in api.py).
    direct_message from captain (shell /hail) is skipped (shell.py stores).
    """
    # Skip intents that already have dedicated episode storage
    if intent.intent == "proactive_think":
        return
    if intent.intent == "ward_room_notification":
        return

    params = observation.get("params", {})
    source = params.get("from", "")
    if intent.intent == "direct_message" and source in ("hxi_profile", "captain"):
        return

    # Guard: need runtime + episodic memory + crew check
    if not self._runtime:
        return
    if not hasattr(self._runtime, 'episodic_memory') or not self._runtime.episodic_memory:
        return
    if not hasattr(self._runtime, '_is_crew_agent') or not self._runtime._is_crew_agent(self):
        return

    try:
        import time as _time
        from probos.types import Episode

        result_text = str(report.get("result", ""))[:500]
        callsign = ""
        if hasattr(self._runtime, 'callsign_registry'):
            callsign = self._runtime.callsign_registry.get_callsign(self.agent_type) or ""

        query_text = params.get("text", intent.context or intent.intent)

        episode = Episode(
            user_input=f"[Action: {intent.intent}] {callsign or self.agent_type}: {str(query_text)[:200]}",
            timestamp=_time.time(),
            agent_ids=[self.id],
            outcomes=[{
                "intent": intent.intent,
                "success": report.get("success", False),
                "response": result_text,
                "agent_type": self.agent_type,
                "source": source or "intent_bus",
            }],
            reflection=f"{callsign or self.agent_type} handled {intent.intent}: {result_text[:100]}",
        )
        await self._runtime.episodic_memory.store(episode)
    except Exception:
        pass  # Non-critical — never block the action
```

## Tests

**File:** `tests/test_cognitive_agent.py` — Add to existing test file (or `tests/test_cognitive.py` — find the right file).

### Test 1: Memory recall injects recent_memories into observation
```
Create a CognitiveAgent with a mock runtime that has episodic_memory and _is_crew_agent returning True.
Mock recall_for_agent() to return 2 Episode objects with user_input and reflection.
Send a direct_message intent via handle_intent().
Assert that _build_user_message() receives observation with "recent_memories" key containing 2 entries.
```

### Test 2: Memory recall skips proactive_think (no duplication)
```
Create a CognitiveAgent with mock runtime and episodic_memory.
Send a proactive_think intent.
Assert recall_for_agent() was NOT called (proactive loop handles its own memory context).
```

### Test 3: Memory recall skips non-crew agents
```
Create a CognitiveAgent with mock runtime where _is_crew_agent returns False.
Send a direct_message intent.
Assert recall_for_agent() was NOT called.
```

### Test 4: Memory recall failure doesn't block decide()
```
Create a CognitiveAgent with mock runtime where recall_for_agent() raises an exception.
Send a direct_message intent.
Assert handle_intent() completes successfully — agent decides without memory context.
```

### Test 5: Memory recall with no runtime doesn't crash
```
Create a CognitiveAgent with _runtime=None.
Send a direct_message intent.
Assert handle_intent() completes successfully.
```

### Test 6: Act-store hook stores episode for uncovered intents
```
Create a CognitiveAgent with mock runtime (episodic_memory, _is_crew_agent=True).
Send an intent with name "analyze" (not proactive_think, not direct_message, not ward_room_notification).
Assert episodic_memory.store() was called with an Episode whose:
- user_input contains "[Action: analyze]"
- agent_ids == [agent.id]
- outcomes[0]["intent"] == "analyze"
```

### Test 7: Act-store hook skips proactive_think (dedup)
```
Send a proactive_think intent.
Assert episodic_memory.store() was NOT called from handle_intent() (proactive.py handles it).
```

### Test 8: Act-store hook skips ward_room_notification (dedup)
```
Send a ward_room_notification intent.
Assert episodic_memory.store() was NOT called from handle_intent() (ward_room.py handles it).
```

### Test 9: Act-store hook skips hxi_profile direct_message (dedup)
```
Send a direct_message intent with params["from"] == "hxi_profile".
Assert episodic_memory.store() was NOT called from handle_intent() (api.py handles it).
```

### Test 10: Act-store hook skips captain direct_message (dedup)
```
Send a direct_message intent with params["from"] == "captain".
Assert episodic_memory.store() was NOT called from handle_intent() (shell.py handles it).
```

### Test 11: Act-store hook failure doesn't block response
```
Create a CognitiveAgent with mock runtime where episodic_memory.store() raises.
Send an intent. Assert handle_intent() returns IntentResult successfully.
```

### Test 12: Direct message _build_user_message includes memories
```
Call _build_user_message() with observation containing recent_memories.
Assert the returned string contains "Your recent memories" and the reflection text.
```

### Test 13: Ward Room _build_user_message includes memories
```
Call _build_user_message() with ward_room_notification observation containing recent_memories.
Assert the returned string contains "Your relevant memories" and the reflection text.
```

## Constraints

- All memory operations are wrapped in try/except — non-critical, never blocks the cognitive lifecycle.
- Memory recall budget: max 3 episodes, max 200 chars per field — keeps LLM context lean.
- `proactive_think` is explicitly excluded from BOTH recall and act-store — the proactive loop (`proactive.py`) already handles its own memory via `_gather_context()` and episode storage (AD-430a). No duplication.
- Act-store dedup: skip `proactive_think`, `ward_room_notification`, `direct_message` from `hxi_profile`/`captain`. These all have dedicated storage paths from AD-430a/b and the shell.
- Act-store only fires for crew agents (Tier 3) — checked via `self._runtime._is_crew_agent(self)`.
- `response` in episode outcomes is truncated to 500 chars (consistent with AD-430a/b).
- No changes to domain agent subclasses — all modifications are in `CognitiveAgent` base class.
- No changes to `proactive.py`, `ward_room.py`, or `api.py` — those paths are already complete from AD-430a/b.

## Run

```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_cognitive_agent.py -x -v 2>&1 | tail -40
```

If the test file is named differently, find the right file:
```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/ -x -v -k "cognitive" 2>&1 | tail -40
```
