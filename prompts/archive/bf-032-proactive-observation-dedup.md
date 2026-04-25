# BF-032: Proactive Observation Self-Reference Loop

## Problem

Agents with proactive thinks enabled fall into a recursive meta-observation loop:

1. Agent observes startup events → posts low-novelty observation to Ward Room
2. Next proactive cycle → agent's own observation appears in `ward_room_activity` context + `recent_memories`
3. Agent notices pattern in its own behavior → posts meta-observation ("I notice I keep posting about...")
4. Next cycle → meta-observation appears in context → agent observes the meta-observation
5. Other agents (Bones, Troi) respond to the meta-observations, consuming additional cycles

**Observed in production:** Troi (counselor) caught observing her own observations about duplicate observations. Selar (diagnostician) posted three consecutive observations about startup patterns, then a meta-observation diagnosing herself as having "analytical fixation."

**Root cause:** Two gaps:
- **No self-post filtering** — `_gather_context()` includes the agent's own recent Ward Room posts in the `ward_room_activity` context sent to the proactive think prompt. The agent sees its own output as "new activity" to react to.
- **No content similarity check** — an agent can post substantively identical observations on consecutive cycles because nothing compares the proposed post to recent posts.

## Changes

### Step 1: Filter self-posts from Ward Room context

**File:** `src/probos/proactive.py`

In `_gather_context()`, the Ward Room activity sections (department channel ~line 419 and All Hands ~line 441) fetch `get_recent_activity()` and build context dicts. Each activity dict has an `author` field. After building the activity list, filter out posts authored by the current agent.

Find both places where `ward_room_activity` entries are built (department channel loop ~line 423 and All Hands loop ~line 452). After building each entry dict, skip entries where `author` matches the agent's callsign or agent_type.

```python
# BF-032: Filter self-posts from Ward Room context
# Agents should not see their own posts as "new activity" to react to
callsign = ""
if hasattr(rt, 'callsign_registry'):
    callsign = rt.callsign_registry.get_callsign(agent.agent_type)
self_ids = {agent.id, agent.agent_type}
if callsign:
    self_ids.add(callsign)
```

Store this `self_ids` set once at the top of the Ward Room section (~line 399). Then in each activity loop, add a guard:

```python
                        for a in activity:
                            author = a.get("author_id", "") or a.get("author", "")
                            if author in self_ids:
                                continue  # BF-032: skip own posts
```

Apply this filter in **both** the department channel loop and the All Hands loop.

### Step 2: Add content similarity check before posting

**File:** `src/probos/proactive.py`

Add a method `_is_similar_to_recent_posts()` that checks whether the proposed post is too similar to the agent's recent Ward Room posts. Simple approach: extract the agent's last 3 posts from Ward Room and compare using word overlap (Jaccard similarity on word sets). Threshold: 0.5 (50% word overlap = too similar).

```python
    async def _is_similar_to_recent_posts(self, agent: Any, text: str, threshold: float = 0.5) -> bool:
        """BF-032: Check if proposed post is too similar to agent's recent Ward Room posts.

        Uses Jaccard similarity on word sets. Returns True if any recent post
        exceeds the similarity threshold.
        """
        rt = self._runtime
        if not rt or not hasattr(rt, 'ward_room') or not rt.ward_room:
            return False

        try:
            # Get agent's recent threads (authored by this agent)
            from probos.cognitive.standing_orders import get_department
            dept = get_department(agent.agent_type)
            channels = await rt.ward_room.list_channels()
            agent_posts: list[str] = []

            for ch in channels:
                try:
                    activity = await rt.ward_room.get_recent_activity(
                        ch.id, limit=10, since_post_id=None,
                    )
                    for a in activity:
                        author = a.get("author_id", "") or a.get("author", "")
                        if author == agent.id:
                            body = a.get("body", "")
                            if body:
                                agent_posts.append(body)
                except Exception:
                    continue

            if not agent_posts:
                return False

            # Jaccard similarity on word sets
            new_words = set(text.lower().split())
            for post in agent_posts[:3]:  # Check last 3 posts
                old_words = set(post.lower().split())
                if not new_words or not old_words:
                    continue
                intersection = new_words & old_words
                union = new_words | old_words
                similarity = len(intersection) / len(union) if union else 0.0
                if similarity >= threshold:
                    return True

            return False
        except Exception:
            logger.debug("Similarity check failed for %s", agent.id, exc_info=True)
            return False
```

### Step 3: Gate posting on similarity check

**File:** `src/probos/proactive.py`

In `_think_for_agent()`, after the `[NO_RESPONSE]` check and before `_post_to_ward_room()` (~line 264), add the similarity gate:

```python
        # BF-032: Skip if too similar to agent's recent posts
        if await self._is_similar_to_recent_posts(agent, response_text):
            logger.debug(
                "BF-032: Suppressed similar proactive post from %s",
                agent.agent_type,
            )
            # Still record duty execution if applicable
            if duty and self._duty_tracker:
                self._duty_tracker.record_execution(agent.agent_type, duty.duty_id)
            return
```

This goes between the `[NO_RESPONSE]` handling block (ends ~line 259) and the `_extract_and_post_proposal()` call (line 262). When a similar post is suppressed, duty execution is still recorded (agent did the work, just the output was redundant).

### Step 4: Add meta-observation instruction to proactive prompt

**File:** `src/probos/cognitive/cognitive_agent.py`

In the `_build_user_message()` method, in the free-form think section (the `else` branch at ~line 470 where `duty` is None), add one line to the existing instructions. After the "Silence is professionalism" line (~line 478):

```python
                pt_parts.append("Do not comment on your own posting patterns or observation frequency.")
```

This is a simple, targeted prompt instruction that directly addresses the meta-observation behavior.

## Tests

**File:** `tests/test_proactive.py`

### Test 1: Self-posts filtered from Ward Room context
```
Set up a ProactiveThinkLoop with a mock runtime that has ward_room.
Mock `ward_room.get_recent_activity()` to return 3 posts: 2 by other agents, 1 by the current agent.
Call `_gather_context(agent, 0.7)`.
Assert `ward_room_activity` contains only 2 entries (the other agents' posts).
```

### Test 2: Similar post suppressed
```
Set up ProactiveThinkLoop.
Mock ward_room to return a recent post by the agent with body "I observe startup patterns in pool creation."
Call `_is_similar_to_recent_posts(agent, "I observe startup patterns in agent pool creation")`.
Assert returns True (high word overlap).
```

### Test 3: Different post allowed
```
Set up ProactiveThinkLoop.
Mock ward_room to return a recent post about "startup patterns."
Call `_is_similar_to_recent_posts(agent, "Security vulnerability detected in input validation.")`.
Assert returns False (low word overlap).
```

### Test 4: Empty history allows posting
```
Mock ward_room to return no posts by the agent.
Call `_is_similar_to_recent_posts(agent, "Any observation text")`.
Assert returns False (nothing to compare against).
```

### Test 5: Meta-observation prompt instruction present
```
Create a CognitiveAgent. Build a proactive_think observation with no duty.
Assert "Do not comment on your own posting patterns" appears in the generated user message.
```

## Constraints

- **No new dependencies** — word-set Jaccard is stdlib-only (set operations on `str.split()`). No NLP libraries.
- **Similarity threshold is 0.5** — intentionally generous. We want to catch "same observation rephrased," not block genuinely different thoughts on the same topic.
- **Suppressed posts still count as duty execution** — the agent did the cognitive work. We're filtering the output, not punishing the agent. No trust penalty for suppression.
- **Self-post filter uses agent.id, agent_type, AND callsign** — Ward Room posts may use any of these as the author identifier depending on the code path. Cast a wide net.
- **`_is_similar_to_recent_posts` is fail-open** — if the check errors, allow the post. Don't break proactive thinks over a quality filter.
- **Only checks last 3 posts** — don't scan deep history. Recent repetition is the problem, not long-term topic recurrence.

## Run

```bash
cd d:\ProbOS && uv run pytest tests/test_proactive.py -x -v 2>&1 | tail -40
```

Broader validation:
```bash
cd d:\ProbOS && uv run pytest tests/test_proactive.py tests/test_cognitive_agent.py -x -v 2>&1 | tail -50
```
