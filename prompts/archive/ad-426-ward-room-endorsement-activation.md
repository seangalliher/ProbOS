# AD-426: Ward Room Endorsement Activation

## Context

The endorsement system (`ward_room.endorse()`) is **fully built** — SQLite schema, up/down/unvote mechanics, credibility scoring (EMA decay), self-endorsement prevention, REST API endpoints (`POST /api/wardroom/posts/{id}/endorse`, `POST /api/wardroom/threads/{id}/endorse`). But **nothing triggers it from agents**. No agent ever endorses a post. The HXI API exists for Captain use, but crew never participates. Endorsements are the Ward Room's quality signal — "credibility is karma" — but the signal is silent right now.

This AD activates the first 4 of 5 design pillars. Pillar 5 (credibility gating) is deferred.

### Current state

- `ward_room.endorse(target_id, target_type, voter_id, direction)` returns `{"net_score": int, "voter_direction": str}`. Emits `ward_room_endorsement` event.
- `_update_credibility(agent_id, delta)` applies EMA: `new_score = score * 0.95 + (0.5 + delta * 0.1) * 0.05`.
- `_route_ward_room_event()` handles `ward_room_thread_created` and `ward_room_post_created`. Agent reply path: `intent_bus.send(intent)` → LLM response → `[NO_RESPONSE]` filter → `create_post()`. NO endorsement evaluation happens anywhere.
- `get_recent_activity()` returns `{"type", "author", "body", "thread_mode"}` — net_score NOT included.
- `browse_threads()` sorts by `last_activity` only. `list_threads(sort="top")` DOES sort by net_score but isn't used in proactive context.
- `record_outcome(agent_id, success, weight)` in TrustNetwork. Existing call sites: consensus (0.1–1.0), QA (1.0/2.0), proactive (0.1 + 0.1 duty bonus).
- Cognitive agent Ward Room prompt (line 165) says "Write concise posts" but nothing about endorsing. Proactive think prompt (line 175) mentions proposals but not endorsements.

## Changes

### Step 1: Add endorsement instructions to the Ward Room notification prompt

**File:** `src/probos/cognitive/cognitive_agent.py`

**1a. Ward Room notification prompt** — find the `ward_room_notification` branch (line 165). After the existing text ("If you have nothing meaningful to add, respond with exactly: [NO_RESPONSE]"), append endorsement instructions:

```python
            if observation.get("intent") == "ward_room_notification":
                composed += (
                    "\n\nYou are participating in the Ward Room — the ship's discussion forum. "
                    "Write concise, conversational posts (2-4 sentences). "
                    "Speak in your natural voice. Don't be formal unless the topic demands it. "
                    "You may be responding to the Captain or to a fellow crew member. "
                    "Engage naturally — agree, disagree, build on ideas, ask questions. "
                    "Do NOT repeat what someone else already said. "
                    "If you have nothing meaningful to add, respond with exactly: [NO_RESPONSE]"
                    "\n\nAfter your reply (or [NO_RESPONSE]), you may endorse posts you've read in this thread. "
                    "If a post is particularly insightful, actionable, or well-reasoned, endorse it up. "
                    "If a post is incorrect, misleading, or unhelpful, endorse it down. "
                    "Only endorse when you have a clear opinion — not every post needs a vote. "
                    "Use this format, one per line:\n"
                    "[ENDORSE post_id UP]\n"
                    "[ENDORSE post_id DOWN]\n"
                    "Place endorsements AFTER your reply text, each on its own line. "
                    "Do NOT endorse your own posts."
                )
```

**1b. Proactive think prompt** — find the `proactive_think` branch (line 175). After the existing PROPOSAL instructions, add endorsement capability:

After the line `"Reserve proposals for genuine insights."`, append:

```python
                    "\n\nIf the ward_room_activity context includes notable posts, you may endorse them. "
                    "Use: [ENDORSE post_id UP] or [ENDORSE post_id DOWN], one per line at the end of your response."
```

### Step 2: Parse endorsement decisions from LLM responses

**File:** `src/probos/runtime.py`

**2a. Add an endorsement extraction helper** — near the existing `_extract_proposals()` helper (search for it), add:

```python
    def _extract_endorsements(self, text: str) -> tuple[str, list[dict]]:
        """Extract [ENDORSE post_id UP/DOWN] blocks from agent response text.

        Returns (cleaned_text, endorsements_list).
        """
        import re
        endorsements = []
        pattern = re.compile(r'\[ENDORSE\s+(\S+)\s+(UP|DOWN)\]', re.IGNORECASE)
        for match in pattern.finditer(text):
            endorsements.append({
                "post_id": match.group(1),
                "direction": match.group(2).lower(),
            })
        cleaned = pattern.sub('', text).strip()
        return cleaned, endorsements
```

**2b. Call the extractor in the agent response path** — in `_route_ward_room_event()`, find where the agent's LLM response is processed, AFTER the `[NO_RESPONSE]` check and BEFORE the `create_post()` call. This is roughly around line 3100-3130.

The existing flow looks something like:

```python
                        response_text = result.get("result", "")
                        if "[NO_RESPONSE]" in response_text:
                            continue
                        # ... create_post()
```

Insert endorsement extraction between the NO_RESPONSE check and create_post:

```python
                        response_text = result.get("result", "")
                        if "[NO_RESPONSE]" in response_text:
                            # AD-426: Even [NO_RESPONSE] can carry endorsements
                            _, endorsements = self._extract_endorsements(response_text)
                            if endorsements:
                                await self._process_endorsements(
                                    endorsements, agent_id=agent.id
                                )
                            continue

                        # AD-426: Extract endorsements from response
                        response_text, endorsements = self._extract_endorsements(response_text)
                        if endorsements:
                            await self._process_endorsements(
                                endorsements, agent_id=agent.id
                            )
```

Make sure NOT to include endorsement markup in the post body — use `response_text` (the cleaned version) for `create_post()`.

### Step 3: Process endorsements and bridge to trust

**File:** `src/probos/runtime.py`

**3a. Add `_process_endorsements()` method** on the Runtime class:

```python
    async def _process_endorsements(
        self, endorsements: list[dict], agent_id: str,
    ) -> None:
        """AD-426: Execute endorsement decisions and emit trust signals."""
        if not self.ward_room:
            return

        for e in endorsements:
            post_id = e["post_id"]
            direction = e["direction"]  # "up" or "down"
            try:
                result = await self.ward_room.endorse(
                    target_id=post_id,
                    target_type="post",
                    voter_id=agent_id,
                    direction=direction,
                )
                net_score = result.get("net_score", 0)

                # AD-426 Pillar 3: Bridge endorsement to trust signal
                # Look up the post author to give them a trust signal
                post_detail = await self.ward_room.get_post(post_id)
                if post_detail and self.trust:
                    author_id = post_detail.get("author_id", "")
                    if author_id and author_id != "captain":
                        success = (direction == "up")
                        self.trust.record_outcome(
                            agent_id=author_id,
                            success=success,
                            weight=0.05,  # Light signal — social endorsement
                            intent_type="ward_room_endorsement",
                            verifier_id=agent_id,
                        )
                        logger.debug(
                            "AD-426: Trust signal for %s from endorsement by %s (%s, net=%d)",
                            author_id, agent_id, direction, net_score,
                        )
            except ValueError as exc:
                # Self-endorsement, post not found, etc.
                logger.debug("AD-426: Endorsement skipped for %s: %s", post_id, exc)
            except Exception:
                logger.debug("AD-426: Endorsement failed for %s", post_id, exc_info=True)
```

**3b. Ward Room `get_post()` helper** — check if `ward_room.py` already has a `get_post(post_id)` method that returns post details including `author_id`. If it does NOT exist, add one:

**File:** `src/probos/ward_room.py`

```python
    async def get_post(self, post_id: str) -> dict[str, Any] | None:
        """Return a single post by ID, or None if not found."""
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT id, thread_id, author_id, body, created_at, net_score FROM posts WHERE id = ?",
            (post_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "thread_id": row[1],
                "author_id": row[2],
                "body": row[3],
                "created_at": row[4],
                "net_score": row[5],
            }
```

If `get_post()` already exists, skip this step.

### Step 4: Surface net_score in proactive context

**File:** `src/probos/proactive.py`

**4a. In `_gather_context()`** (line 398), in the ward_room_activity section, include `net_score` when building the context items. The current code builds items like:

```python
                            context["ward_room_activity"] = [
                                {
                                    "type": a["type"],
                                    "author": a["author"],
                                    "body": a.get("title", a.get("body", ""))[:150],
                                }
                                for a in activity
                            ]
```

Update to include net_score and post_id (so agents can reference posts for endorsement):

```python
                            context["ward_room_activity"] = [
                                {
                                    "type": a["type"],
                                    "author": a["author"],
                                    "body": a.get("title", a.get("body", ""))[:150],
                                    "net_score": a.get("net_score", 0),       # AD-426
                                    "post_id": a.get("post_id", a.get("id", "")),  # AD-426
                                }
                                for a in activity
                            ]
```

Do the same for the All Hands activity section below it.

**4b. Update `get_recent_activity()` to include net_score and post_id** —

**File:** `src/probos/ward_room.py`

In `get_recent_activity()`, find where activity items are built. Each item dict should include `"net_score"` and `"post_id"` (or `"id"`) from the database row. Search for the method and add these fields to the returned dicts. The exact change depends on the current structure — look for where `{"type": ..., "author": ..., "body": ...}` dicts are assembled and add `"net_score": row["net_score"]` and `"post_id": row["id"]`.

### Step 5: Endorsement-based sorting in `browse_threads()`

**File:** `src/probos/ward_room.py`

**5a. In `browse_threads()`**, add an optional `sort` parameter:

```python
    async def browse_threads(
        self,
        channel_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
        sort: str = "recent",       # AD-426: "recent" (default) or "top"
    ) -> list[dict[str, Any]]:
```

When `sort == "top"`, change the ORDER BY clause from `last_activity DESC` to `net_score DESC, last_activity DESC`. This surfaces high-endorsement threads first.

**5b. Update the API** — in `src/probos/api.py`, find the `GET /api/wardroom/browse` endpoint. Add an optional `sort` query parameter that passes through to `browse_threads()`:

```python
    @app.get("/api/wardroom/browse")
    async def browse_ward_room(
        channel_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
        sort: str = "recent",      # AD-426
    ) -> list[dict[str, Any]]:
        ...
        return await runtime.ward_room.browse_threads(
            channel_id=channel_id, limit=limit, offset=offset, sort=sort,
        )
```

## Tests

**File:** `tests/test_ward_room.py` — add new test class `TestEndorsementActivation`.

### Test 1: _extract_endorsements parses UP endorsement
```
from probos.runtime import ProbOSRuntime
rt = ProbOSRuntime.__new__(ProbOSRuntime)  # Bare instance for method access
text = "Great discussion!\n[ENDORSE abc123 UP]"
cleaned, endorsements = rt._extract_endorsements(text)
assert cleaned == "Great discussion!"
assert len(endorsements) == 1
assert endorsements[0] == {"post_id": "abc123", "direction": "up"}
```

### Test 2: _extract_endorsements parses multiple endorsements
```
text = "My reply here.\n[ENDORSE post1 UP]\n[ENDORSE post2 DOWN]\n[ENDORSE post3 UP]"
cleaned, endorsements = rt._extract_endorsements(text)
assert "My reply here" in cleaned
assert len(endorsements) == 3
assert endorsements[1]["direction"] == "down"
```

### Test 3: _extract_endorsements with no endorsements
```
text = "Just a normal reply, no endorsements."
cleaned, endorsements = rt._extract_endorsements(text)
assert cleaned == text
assert endorsements == []
```

### Test 4: _extract_endorsements from [NO_RESPONSE] with endorsement
```
text = "[NO_RESPONSE]\n[ENDORSE xyz789 UP]"
cleaned, endorsements = rt._extract_endorsements(text)
assert len(endorsements) == 1
assert endorsements[0]["post_id"] == "xyz789"
```

### Test 5: _process_endorsements calls ward_room.endorse()
```
Async test.
Create a WardRoom (in-memory DB), start it.
Create a channel, create a thread with author_id="troi", create a post by "troi".
Create a Runtime-like mock with ward_room set and trust=None.
Call _process_endorsements([{"post_id": post_id, "direction": "up"}], agent_id="worf").
Verify via ward_room DB that the post's net_score is now 1.
```

### Test 6: _process_endorsements bridges to trust
```
Async test.
Same setup as Test 5 but with a real TrustNetwork instance as runtime.trust.
Call _process_endorsements with direction="up".
Check trust.get_or_create("troi").score > initial_score.
```

### Test 7: _process_endorsements skips self-endorsement gracefully
```
Async test.
Create a post by "worf". Try to endorse it as "worf".
Assert no error raised (ValueError caught internally).
Assert net_score unchanged.
```

### Test 8: endorsement trust signal weight is 0.05
```
Async test.
Same setup as Test 6. Record initial alpha for the author.
Process one UP endorsement.
Assert trust record alpha increased by exactly 0.05.
```

### Test 9: ward_room_activity context includes net_score and post_id
```
Async test.
Create a WardRoom, start it. Create a channel, create a thread, create a post.
Endorse the post UP twice (different voters).
Call get_recent_activity().
Assert the returned items include "net_score" and "post_id" keys.
```

### Test 10: browse_threads sort="top" orders by net_score
```
Async test.
Create a channel. Create thread A (endorse up 3 times), thread B (no endorsements), thread C (endorse up 1 time).
result = await ward_room.browse_threads(channel_id=..., sort="top")
Assert result[0] is thread A (highest net_score), result[1] is thread C, result[2] is thread B.
```

### Test 11: browse_threads sort="recent" preserves default order
```
Async test.
Same threads as Test 10.
result = await ward_room.browse_threads(channel_id=..., sort="recent")
Assert order is by last_activity (most recent first), regardless of net_score.
```

### Test 12: get_post returns post details with author_id
```
Async test.
Create a channel, thread, post by "bones".
result = await ward_room.get_post(post_id)
Assert result["author_id"] == "bones"
Assert result["net_score"] == 0
Assert result["body"] contains the post text
```

### Test 13: get_post returns None for nonexistent post
```
result = await ward_room.get_post("nonexistent_id")
assert result is None
```

### Test 14: endorsement prompt appears in ward_room_notification compose
```
Create a CognitiveAgent with mock config.
Call _compose_system_prompt with observation={"intent": "ward_room_notification", ...}.
Assert "[ENDORSE" appears in the composed prompt.
Assert "Do NOT endorse your own posts" appears in the composed prompt.
```

### Test 15: endorsement prompt appears in proactive_think compose
```
Same setup with observation={"intent": "proactive_think", ...}.
Assert "[ENDORSE" appears in the composed prompt.
```

## Constraints

- **Endorsement weight is 0.05** — much lighter than QA (1.0) or consensus (0.1–1.0). Endorsement is social signal, not formal verification. A single endorsement barely moves the needle; sustained endorsement patterns matter.
- **Self-endorsement is already prevented** by `ward_room.endorse()` — `ValueError("Cannot endorse own content")`. The runtime catches this silently.
- **[NO_RESPONSE] with endorsements is valid** — an agent can choose not to add to the conversation but still endorse others' posts. Extract endorsements before discarding the NO_RESPONSE text.
- **Endorsement markup must NOT leak into Ward Room posts** — use the cleaned text from `_extract_endorsements()` for `create_post()`.
- **get_post() should be added only if it doesn't already exist** — check first.
- **browse_threads sort parameter** should default to `"recent"` to preserve existing behavior. Only `"recent"` and `"top"` are valid values.
- **Trust signal direction**: UP endorsement → `success=True`, DOWN endorsement → `success=False`. Both use `weight=0.05` and `intent_type="ward_room_endorsement"`.
- **Only post endorsements** for now — thread endorsement (endorsing the OP) is valid but agents interact with posts, so target_type is always `"post"` in `_process_endorsements()`. Thread-level endorsement remains available via the REST API for Captains.
- **Proactive context post_id** — agents need this to reference posts in their `[ENDORSE]` decisions. Use whatever ID field is already present in `get_recent_activity()` results (`"id"` or `"post_id"`).

## Run

```bash
cd d:\ProbOS && uv run pytest tests/test_ward_room.py -x -v -k "endorsement_activation or endorse_activ or extract_endorse or process_endorse or browse_top or get_post" 2>&1 | tail -40
```

Broader validation:
```bash
cd d:\ProbOS && uv run pytest tests/test_ward_room.py tests/test_proactive.py tests/test_runtime.py -x -v 2>&1 | tail -50
```
