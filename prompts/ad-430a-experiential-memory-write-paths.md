# AD-430a: Agent Experiential Memory — Write Paths (Pillars 1-2)

## Context

ProbOS agents have episodic memory infrastructure (`EpisodicMemory` in `src/probos/cognitive/episodic.py`) but most agent activity never writes to it. Only 5 write paths exist today — none cover proactive thoughts or Ward Room conversations. This AD closes two of the three critical memory gaps.

**Episode dataclass** (`src/probos/types.py` line 301): `Episode(id, timestamp, user_input, dag_summary, outcomes, reflection, agent_ids, duration_ms, embedding, shapley_values, trust_deltas)`. The `user_input` field is what ChromaDB embeds for semantic search. The `agent_ids` list determines sovereign shard ownership (used by `recall_for_agent()`).

**Existing pattern** — the shell `/hail` session (shell.py ~line 1528) is the model to follow:
```python
episode = Episode(
    user_input=f"[1:1 with {self._session_callsign}] Captain: {text}",
    timestamp=_time.time(),
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

## Pillar 1: Proactive Think Episodes

**File:** `src/probos/proactive.py`

**What:** After a proactive think cycle completes, store an episode recording the agent's thought and outcome.

**Where:** In `_think_for_agent()` (line 143). Two storage points:

### 1a. Successful proactive thought (after Ward Room post, ~line 209)

After `await self._post_to_ward_room(agent, response_text)` and the cooldown update at line 210, store an episode:

```python
# AD-430a: Store proactive thought as episodic memory
if hasattr(rt, 'episodic_memory') and rt.episodic_memory:
    try:
        import time as _time
        from probos.types import Episode
        callsign = ""
        if hasattr(rt, 'callsign_registry'):
            callsign = rt.callsign_registry.get_callsign(agent.agent_type)
        thought_summary = response_text[:200]
        episode = Episode(
            user_input=f"[Proactive thought] {callsign or agent.agent_type}: {thought_summary}",
            timestamp=_time.time(),
            agent_ids=[agent.id],
            outcomes=[{
                "intent": "proactive_think",
                "success": True,
                "response": response_text[:500],
                "duty_id": duty.duty_id if duty else None,
                "agent_type": agent.agent_type,
            }],
            reflection=f"{callsign or agent.agent_type} observed: {thought_summary}",
        )
        await rt.episodic_memory.store(episode)
    except Exception:
        logger.debug("Failed to store proactive thought episode for %s", agent.agent_type, exc_info=True)
```

### 1b. No-response proactive thought (~line 192-206, before the `return`)

When the agent thinks but produces `[NO_RESPONSE]` or empty — still store an episode. "I thought about it and had nothing to say" is a memory that prevents redundant re-analysis.

```python
# AD-430a: Store no-response as episodic memory (prevents redundant re-analysis)
if hasattr(rt, 'episodic_memory') and rt.episodic_memory:
    try:
        import time as _time
        from probos.types import Episode
        callsign = ""
        if hasattr(rt, 'callsign_registry'):
            callsign = rt.callsign_registry.get_callsign(agent.agent_type)
        episode = Episode(
            user_input=f"[Proactive thought — no response] {callsign or agent.agent_type}: reviewed context, nothing to report",
            timestamp=_time.time(),
            agent_ids=[agent.id],
            outcomes=[{
                "intent": "proactive_think",
                "success": True,
                "response": "[NO_RESPONSE]",
                "duty_id": duty.duty_id if duty else None,
                "agent_type": agent.agent_type,
            }],
            reflection=f"{callsign or agent.agent_type} reviewed context but had nothing to report.",
        )
        await rt.episodic_memory.store(episode)
    except Exception:
        logger.debug("Failed to store no-response episode for %s", agent.agent_type, exc_info=True)
```

**Insert location:** Just before each `return` in the no-response block (line 206). Make sure to place the episode storage AFTER the duty recording and trust signal but BEFORE the `return`.

**Note on imports:** `Episode` and `time` should be imported inside the try block to avoid top-level import coupling (consistent with the shell.py pattern). If you prefer, you can add `from probos.types import Episode` to the top-level imports and use the module-level `time` — either approach is fine as long as it's consistent.

## Pillar 2: Ward Room Conversation Episodes

**File:** `src/probos/ward_room.py`

**What:** When an agent creates a thread or post, store an episode for the **authoring agent only** (sovereign memory).

**Design choice:** Add an `episodic_memory` parameter to `WardRoomService.__init__()` so the service can store episodes internally. This keeps the memory writing co-located with the data creation rather than requiring every caller to know about episodic memory.

### 2a. Constructor change

**File:** `src/probos/ward_room.py`, line 207

Add `episodic_memory` parameter:

```python
def __init__(self, db_path: str | None = None, emit_event: Any = None, episodic_memory: Any = None):
    self.db_path = db_path
    self._db: aiosqlite.Connection | None = None
    self._emit_event = emit_event
    self._episodic_memory = episodic_memory  # AD-430a: For storing conversation episodes
    self._channel_cache: list[dict[str, Any]] = []
```

### 2b. Thread creation episode

**File:** `src/probos/ward_room.py`, after line 836 (`self._emit(...)` block for `ward_room_thread_created`)

After the emit and before `return thread`:

```python
# AD-430a: Store thread creation as authoring agent's episodic memory
if self._episodic_memory and author_id:
    try:
        import time as _time
        from probos.types import Episode
        channel_name = ""
        for ch in self._channel_cache:
            if ch.get("id") == channel_id:
                channel_name = ch.get("name", "")
                break
        episode = Episode(
            user_input=f"[Ward Room] {channel_name} — {author_callsign or author_id}: {title}",
            timestamp=_time.time(),
            agent_ids=[author_id],
            outcomes=[{
                "intent": "ward_room_post",
                "success": True,
                "channel": channel_name,
                "thread_title": title,
                "thread_id": thread.id,
                "is_reply": False,
                "thread_mode": thread_mode,
            }],
            reflection=f"{author_callsign or author_id} posted to {channel_name}: {title[:100]}",
        )
        await self._episodic_memory.store(episode)
    except Exception:
        pass  # Non-critical — don't block Ward Room operations
```

### 2c. Post (reply) creation episode

**File:** `src/probos/ward_room.py`, after line 997 (`self._emit(...)` block for `ward_room_post_created`)

After the emit and before `return post`:

```python
# AD-430a: Store reply as authoring agent's episodic memory
if self._episodic_memory and author_id:
    try:
        import time as _time
        from probos.types import Episode
        # Get thread title for context
        thread_title = ""
        try:
            row = await self._db.execute_fetchone(
                "SELECT title, channel_id FROM threads WHERE id = ?", (thread_id,)
            )
            if row:
                thread_title = row[0] or ""
        except Exception:
            pass
        episode = Episode(
            user_input=f"[Ward Room reply] {author_callsign or author_id}: {body[:200]}",
            timestamp=_time.time(),
            agent_ids=[author_id],
            outcomes=[{
                "intent": "ward_room_post",
                "success": True,
                "thread_title": thread_title,
                "thread_id": thread_id,
                "is_reply": True,
            }],
            reflection=f"{author_callsign or author_id} replied in thread '{thread_title[:80]}'.",
        )
        await self._episodic_memory.store(episode)
    except Exception:
        pass  # Non-critical
```

### 2d. Runtime wiring

**File:** `src/probos/runtime.py`

When the `WardRoomService` is instantiated, pass `episodic_memory` to it. Search for where `WardRoomService(` is called and add the parameter:

```python
self.ward_room = WardRoomService(
    db_path=ward_room_db_path,
    emit_event=self._emit_event,
    episodic_memory=self.episodic_memory,  # AD-430a
)
```

**Important:** If `episodic_memory` is not yet initialized when `WardRoomService` is constructed, you can instead set it after initialization:
```python
self.ward_room._episodic_memory = self.episodic_memory
```
Check the initialization order in runtime.py to determine which approach is correct.

## Tests

**File:** `tests/test_proactive.py` — Add to existing test class.

### Test 1: Successful proactive thought stores episode
```
Mock runtime with episodic_memory. Run a proactive think that produces meaningful output. Assert episodic_memory.store() was called with an Episode whose:
- user_input contains "[Proactive thought]"
- agent_ids == [agent.id]
- outcomes[0]["intent"] == "proactive_think"
- outcomes[0]["success"] is True
- outcomes[0]["response"] contains the response text
```

### Test 2: No-response proactive thought stores episode
```
Mock runtime with episodic_memory. Run a proactive think that produces "[NO_RESPONSE]". Assert episodic_memory.store() was called with an Episode whose:
- user_input contains "[Proactive thought — no response]"
- agent_ids == [agent.id]
- outcomes[0]["response"] == "[NO_RESPONSE]"
```

### Test 3: Proactive thought without episodic_memory doesn't crash
```
Mock runtime WITHOUT episodic_memory. Run a proactive think. Assert it completes without error. No store() call.
```

### Test 4: Episode storage failure doesn't block proactive loop
```
Mock runtime with episodic_memory that raises on store(). Run a proactive think. Assert it completes successfully (thought still posted to Ward Room, trust signal still recorded). Episode storage failure is non-critical.
```

**File:** `tests/test_ward_room.py` — Add to existing test class.

### Test 5: Thread creation stores episode for author
```
Create a WardRoomService with a mock episodic_memory. Create a thread via create_thread(). Assert episodic_memory.store() was called with an Episode whose:
- user_input contains "[Ward Room]"
- agent_ids == [author_id]
- outcomes[0]["intent"] == "ward_room_post"
- outcomes[0]["is_reply"] is False
- outcomes[0]["thread_id"] matches the returned thread.id
```

### Test 6: Post reply stores episode for author
```
Create a WardRoomService with mock episodic_memory. Create a thread, then create a reply post. Assert episodic_memory.store() was called for the reply with:
- user_input contains "[Ward Room reply]"
- outcomes[0]["is_reply"] is True
```

### Test 7: Ward Room without episodic_memory doesn't crash
```
Create WardRoomService with episodic_memory=None. Create a thread and post. Assert no errors.
```

### Test 8: Ward Room episode storage failure doesn't block post creation
```
Create WardRoomService with episodic_memory that raises on store(). Create a thread. Assert the thread is still created and returned successfully. Episode failure is non-critical.
```

## Constraints

- All episode storage is wrapped in try/except — episodic memory is non-critical and must never block the primary operation.
- Only **crew agents** (Tier 3) end up with episodes stored, because only crew agents have IDs that `recall_for_agent()` would match. Infrastructure agents don't have meaningful `agent_ids` in the episodic system.
- `response_text` in proactive episodes is truncated to 500 chars in outcomes to avoid bloating ChromaDB metadata.
- `user_input` field is the semantic search key — keep it descriptive and prefixed with `[Proactive thought]` or `[Ward Room]` for intent-based filtering.
- Do NOT store episodes when the proactive think raises an exception (the `except` block at line 131). Failed LLM calls are not memories — they're infrastructure errors.

## Run

```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_proactive.py tests/test_ward_room.py -x -v 2>&1 | tail -40
```
