# BF-029: Ward Room Memory Recall Quality in 1:1 Conversations

## Symptom

When the Captain opens a 1:1 conversation with an agent and asks about their Ward Room activity (e.g., "Can you recall posting anything in the Ward Room?"), the agent cannot retrieve those memories — even though the Ward Room episodes are correctly stored in EpisodicMemory (confirmed via AD-430a).

BF-027 lowered the recall threshold to 0.3 and added `recent_for_agent()` timestamp fallback. BF-028 extended that fallback to proactive and shell paths. But the observed failure persists because of three remaining issues in the recall pipeline.

## Root Cause (Three Issues)

### Issue A: Recall query is the raw Captain message — no Ward Room signal

`_recall_relevant_memories()` (cognitive_agent.py line 528-529) uses the Captain's raw message text as the ChromaDB semantic query:

```python
if intent.intent == "direct_message":
    query = params.get("text", "")[:200]
```

When the Captain asks `"Can you recall posting anything in the Ward Room?"`, that's the query text. The stored Ward Room episode `user_input` is `"[Ward Room reply] Counselor: I've noticed increased trust variance..."`. ChromaDB's MiniLM embedding sees a meta-question about memory vs. domain-specific content — the cosine similarity is low. Even at the 0.3 threshold, this often returns zero or weak results, and the `recent_for_agent()` fallback returns the 3 most recent episodes of **any type**, which may not include the Ward Room memory at all if the agent has had other recent activity.

**Fix:** Prepend Ward Room context to the query so the embedding is biased toward Ward Room episodes when they exist.

### Issue B: Memory presentation prefers thin reflections over content-rich input

`_build_user_message()` (cognitive_agent.py lines 375-379) shows recalled memories to the agent with `reflection` preferred over `input`:

```python
if m.get("reflection"):
    parts.append(f"  - {m['reflection']}")
elif m.get("input"):
    parts.append(f"  - {m['input']}")
```

Ward Room reply reflections are thin: `"Counselor replied in thread 'Thread Title'."` — this has zero content signal. The agent reads this "memory" and still has no idea what it actually posted. The `input` field has the real content: `"[Ward Room reply] Counselor: I've noticed increased trust variance..."`.

**Fix:** Reverse the preference — show `input` first, fall back to `reflection`. Apply to both the `direct_message` and `ward_room_notification` prompt builders.

### Issue C: Ward Room reply reflections lack content

`ward_room.py` line 1053 stores reply reflections as:

```python
reflection=f"{author_callsign or author_id} replied in thread '{thread_title[:80]}'.",
```

This tells the agent it replied, but not **what** it said. Even when recall works, the reflection-based memory summary is useless for answering content questions. Thread creation reflections (line 861) are slightly better because they include the title, but reply reflections lose the body entirely.

**Fix:** Include a content excerpt in Ward Room reply reflections.

## Fix

### Fix 1: Enrich direct_message recall query with Ward Room context

**File:** `src/probos/cognitive/cognitive_agent.py`

Find the query construction in `_recall_relevant_memories()` (lines 527-533). Replace:

```python
            # Build a semantic query from the intent content
            params = observation.get("params", {})
            if intent.intent == "direct_message":
                query = params.get("text", "")[:200]
            elif intent.intent == "ward_room_notification":
                query = f"{params.get('title', '')} {params.get('text', '')}".strip()[:200]
            else:
                query = intent.context[:200] if intent.context else intent.intent
```

With:

```python
            # Build a semantic query from the intent content
            params = observation.get("params", {})
            if intent.intent == "direct_message":
                # BF-029: Prepend agent context so the embedding is biased
                # toward the agent's own experiences (Ward Room posts, proactive
                # thoughts, etc.) rather than just matching the Captain's phrasing.
                callsign = ""
                if self._runtime and hasattr(self._runtime, 'callsign_registry'):
                    callsign = self._runtime.callsign_registry.get_callsign(self.agent_type) or ""
                captain_text = params.get("text", "")[:150]
                query = f"Ward Room {callsign} {captain_text}".strip()[:200]
            elif intent.intent == "ward_room_notification":
                query = f"{params.get('title', '')} {params.get('text', '')}".strip()[:200]
            else:
                query = intent.context[:200] if intent.context else intent.intent
```

**Why this works:** By prepending `"Ward Room {callsign}"` to the Captain's message, the embedding now has signal that matches stored Ward Room episodes (`"[Ward Room reply] Counselor: ..."`, `"[Ward Room] All Hands — Counselor: ..."`). The agent's callsign also biases toward their own authored content. The Captain's message text is still included so topical queries are also served.

### Fix 2: Reverse memory presentation preference — input over reflection

**File:** `src/probos/cognitive/cognitive_agent.py`

**2a. Fix `direct_message` prompt builder** (lines 371-380):

Replace:

```python
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
```

With:

```python
            # AD-430c: Episodic memory context
            memories = observation.get("recent_memories", [])
            if memories:
                parts.append("Your recent memories (relevant past experiences):")
                for m in memories:
                    # BF-029: Prefer input (content-rich) over reflection (often thin)
                    if m.get("input"):
                        parts.append(f"  - {m['input']}")
                    elif m.get("reflection"):
                        parts.append(f"  - {m['reflection']}")
                parts.append("")
```

**2b. Fix `ward_room_notification` prompt builder** (lines 404-413):

Replace:

```python
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
```

With:

```python
            # AD-430c: Episodic memory context
            memories = observation.get("recent_memories", [])
            if memories:
                wr_parts.append("")
                wr_parts.append("Your relevant memories:")
                for m in memories:
                    # BF-029: Prefer input (content-rich) over reflection (often thin)
                    if m.get("input"):
                        wr_parts.append(f"  - {m['input']}")
                    elif m.get("reflection"):
                        wr_parts.append(f"  - {m['reflection']}")
```

### Fix 3: Strengthen Ward Room reply reflections with content excerpt

**File:** `src/probos/ward_room.py`

**3a. Fix reply reflection** (line 1053):

Replace:

```python
                    reflection=f"{author_callsign or author_id} replied in thread '{thread_title[:80]}'.",
```

With:

```python
                    reflection=f"{author_callsign or author_id} replied in thread '{thread_title[:60]}': {body[:120]}",
```

**3b. Fix reply `user_input` to include channel context** (line 1043):

The reply episode currently lacks channel information, which makes it harder to semantically match "Ward Room" queries. The thread title is fetched (line 1035-1041) but the channel name is not.

Replace the thread title lookup block and episode construction (lines 1032-1054):

```python
                # Get thread title and channel for context
                thread_title = ""
                channel_name = ""
                try:
                    row = await self._db.execute_fetchone(
                        "SELECT t.title, c.name FROM threads t LEFT JOIN channels c ON t.channel_id = c.id WHERE t.id = ?",
                        (thread_id,)
                    )
                    if row:
                        thread_title = row[0] or ""
                        channel_name = row[1] or ""
                except Exception:
                    pass
                episode = Episode(
                    user_input=f"[Ward Room reply] {channel_name} — {author_callsign or author_id}: {body[:200]}",
                    timestamp=_time.time(),
                    agent_ids=[author_id],
                    outcomes=[{
                        "intent": "ward_room_post",
                        "success": True,
                        "channel": channel_name,
                        "thread_title": thread_title,
                        "thread_id": thread_id,
                        "is_reply": True,
                    }],
                    reflection=f"{author_callsign or author_id} replied in thread '{thread_title[:60]}': {body[:120]}",
                )
```

Note: The `channel_name` is now included in the `user_input` (matching the thread creation format) and in the `outcomes` dict. The SQL join is safe — `channels` table is always present when Ward Room is active.

## Tests

**File:** `tests/test_cognitive_agent.py` — Add to existing test file.

### Test 1: direct_message recall query includes Ward Room and callsign

```
Create a CognitiveAgent with mock runtime that has a callsign_registry.
Mock callsign_registry.get_callsign() to return "Counselor".
Call _recall_relevant_memories() with a direct_message intent (params.text = "What did you post?").
Assert the query passed to recall_for_agent() starts with "Ward Room Counselor" and includes the Captain's text.
```

### Test 2: direct_message recall query works without callsign_registry

```
Create a CognitiveAgent with mock runtime that has NO callsign_registry.
Call _recall_relevant_memories() with a direct_message intent.
Assert recall_for_agent() is called (no crash), query starts with "Ward Room".
```

### Test 3: Memory presentation prefers input over reflection

```
Create a CognitiveAgent. Build observation with recent_memories containing:
  [{"input": "[Ward Room reply] Counselor: Trust variance noted", "reflection": "Counselor replied in thread 'Status Update'."}]
Call _build_user_message() with intent_name="direct_message".
Assert the output contains "[Ward Room reply] Counselor: Trust variance noted".
Assert the output does NOT contain "replied in thread".
```

### Test 4: Memory presentation falls back to reflection when input is empty

```
Build observation with recent_memories containing:
  [{"input": "", "reflection": "Counselor observed something."}]
Call _build_user_message() with intent_name="direct_message".
Assert the output contains "Counselor observed something."
```

### Test 5: ward_room_notification memory presentation also prefers input

```
Build observation with recent_memories and intent_name="ward_room_notification".
Assert the output contains the input text, not the reflection.
```

**File:** `tests/test_ward_room.py` — Add to existing test file.

### Test 6: Reply episode reflection includes body excerpt

```
Create a WardRoom with mock episodic memory.
Create a thread, then create a reply with body "I've noticed increased trust variance across departments".
Capture the Episode passed to episodic_memory.store().
Assert episode.reflection contains a body excerpt (not just "replied in thread").
Assert "trust variance" appears in episode.reflection.
```

### Test 7: Reply episode user_input includes channel name

```
Create a WardRoom, create a channel "All Hands", create a thread, create a reply.
Capture the stored Episode.
Assert episode.user_input contains "All Hands" (the channel name).
Assert episode.user_input starts with "[Ward Room reply] All Hands —".
```

### Test 8: Reply episode outcomes include channel field

```
Create a WardRoom, create a reply.
Capture the stored Episode.
Assert episode.outcomes[0] has a "channel" key with a non-empty value.
```

### Test 9: End-to-end Ward Room recall in 1:1

```
Integration test using MockEpisodicMemory:
1. Store a Ward Room reply episode for agent "counselor-1" with user_input "[Ward Room reply] All Hands — Counselor: I've noticed increased trust variance".
2. Create a CognitiveAgent with id "counselor-1", agent_type "counselor", mock runtime with the MockEpisodicMemory.
3. Mock callsign_registry.get_callsign("counselor") to return "Counselor".
4. Call _recall_relevant_memories() with direct_message intent, params.text = "What have you posted in the Ward Room?"
5. Assert observation["recent_memories"] is non-empty.
6. Assert the recalled memory input contains "Ward Room" and "trust variance".
```

### Test 10: Fallback still fires when enriched query also misses

```
Create a CognitiveAgent with mock runtime.
Mock recall_for_agent() to return [] (even with enriched query).
Mock recent_for_agent() to return 2 episodes.
Call _recall_relevant_memories() with direct_message intent.
Assert recent_for_agent() was called (fallback still works).
Assert observation["recent_memories"] has 2 entries.
```

## Constraints

- The `"Ward Room {callsign}"` prefix is prepended only for `direct_message` intents — not for `ward_room_notification` (which already has its own query construction) or other intents.
- Captain's text is truncated to 150 chars (down from 200) to leave room for the prefix within the 200-char query budget.
- The channel name JOIN in `ward_room.py` uses `LEFT JOIN` so it doesn't fail if the channel was somehow deleted.
- All changes are backward-compatible — existing episodes without channel metadata work fine (they'll just have empty `channel_name` in the query).
- The `input` vs `reflection` preference change affects both `direct_message` and `ward_room_notification` prompt builders. Both currently have the same `reflection`-first logic, both get the same fix.
- `_store_action_episode()` dedup logic is not affected — it skips `ward_room_notification` and `direct_message` from known sources as before.

## Run

```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_cognitive_agent.py tests/test_ward_room.py -x -v -k "recall or ward_room or memory" 2>&1 | tail -30
```

Broader validation:
```bash
cd d:\ProbOS && .venv/Scripts/python -m pytest tests/test_cognitive_agent.py tests/test_ward_room.py tests/test_proactive.py tests/test_session_mode.py -x -v 2>&1 | tail -40
```
