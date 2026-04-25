# AD-623: DM Convergence Gate + DM Self-Monitoring

## Context

**BF-168 (applied)** reduced `dm_exchange_limit` from 6 to 3, but doesn't solve the root cause: agents reach mutual agreement within 2-3 exchanges and then continue echoing each other. The exchange limit is a blunt instrument — it caps length but doesn't detect convergence.

**The Atlas-Kira DM thread (2026-04-13)** is the canonical failure case: 12+ exchanges where both agents agreed within the first 3 messages, then spent 9 messages restating the same conclusions with minor phrasing variations and fabricated metrics. Five layers failed simultaneously:

1. **Exchange limit was too generous** (6, now 3 via BF-168)
2. **Peer repetition detection** (AD-506b) is detection-only — the Counselor handler is informational, doesn't intervene
3. **Self-monitoring context** (`_build_self_monitoring_context`) only runs in the proactive loop, NOT during DM or Ward Room responses
4. **Self-similarity suppression** (AD-614) only gates outbound proactive-initiated DMs, not reply path
5. **Source governance tags** (`[observed]`/`[inferred]`/`[training]`) are prompt instructions only — no code validates them, so fabricated "{specific_percentage}% correlation" metrics pass unchecked

AD-623 addresses layers 3 and adds a new structural mechanism (convergence gate) that detects mutual agreement and locks the thread.

**Design reference:** Issue #212 (`seangalliher/ProbOS#212`)

## Scope

**In scope:**
1. **DM Convergence Gate** — detect when both participants in a DM thread have reached mutual agreement and lock the thread
2. **DM Self-Monitoring** — inject self-monitoring context into the WR notification DM response path so agents see their own repetition in real time

**Out of scope:**
- Source tag verification (separate AD)
- Counselor intervention on repetition (existing AD-506b is detection-only by design)
- Proactive DM initiation changes (already gated by AD-614)
- Public channel convergence (different dynamics)

## Engineering Principles Compliance

- **SOLID/S**: Convergence detection is a thread-level concern → lives in `ward_room/threads.py`. Router orchestrates the gate (its routing concern). Self-monitoring is a cognitive concern → lives in `cognitive_agent.py`.
- **SOLID/O**: Extends `route_event()` guard chain without changing signatures. Extends `_build_input()` ward_room_notification path without changing callers.
- **DRY**: Reuses existing `check_peer_similarity()` from `ward_room/threads.py` (AD-506b) — same Jaccard similarity engine, different threshold and scope (consecutive DM exchanges vs channel-wide posts).
- **Law of Demeter**: Router queries thread data through WardRoomService facade, not reaching into DB directly.
- **Fail Fast**: Convergence check fails open (if DB query fails, continue without gating — don't silently drop DMs).

## Changes

### 1. `src/probos/ward_room/threads.py` — NEW function `check_dm_convergence()`

Add after `check_peer_similarity()` (around line 80):

```python
async def check_dm_convergence(
    db: Any, thread_id: str, window: int = 3, threshold: float = 0.55,
) -> dict[str, Any] | None:
    """AD-623: Detect mutual agreement in DM threads.

    Looks at the last `window` consecutive exchange pairs (A→B, B→A) in a
    DM thread. If all pairs show Jaccard similarity >= threshold,
    the conversation has converged — both sides are restating the same position.

    Returns {"converged": True, "similarity": float, "exchange_count": int}
    if convergence detected, None otherwise.
    """
    try:
        # Get recent posts in thread, ordered by creation time
        async with db.execute(
            "SELECT author_id, body FROM posts "
            "WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?",
            (thread_id, window * 2 + 2),  # Extra buffer for edge cases
        ) as cursor:
            posts = [(row[0], row[1] or "") async for row in cursor]

        if len(posts) < 4:
            return None  # Need at least 2 exchange pairs

        # Reverse to chronological order
        posts.reverse()

        # Find consecutive exchange pairs (different authors)
        from probos.cognitive.similarity import jaccard_similarity, text_to_words
        pairs: list[float] = []
        i = 0
        while i < len(posts) - 1 and len(pairs) < window:
            a_author, a_body = posts[i]
            b_author, b_body = posts[i + 1]
            if a_author != b_author:  # Different authors = exchange pair
                sim = jaccard_similarity(text_to_words(a_body), text_to_words(b_body))
                pairs.append(sim)
            i += 1

        if len(pairs) < 2:
            return None  # Need at least 2 exchange pairs to detect convergence

        avg_sim = sum(pairs) / len(pairs)
        if avg_sim >= threshold:
            return {
                "converged": True,
                "similarity": round(avg_sim, 3),
                "exchange_count": len(pairs),
            }

        return None
    except Exception:
        logger.debug("AD-623: DM convergence check failed", exc_info=True)
        return None
```

**Key design decisions:**
- **threshold=0.55** (lower than self-similarity gate's 0.6): We're checking cross-author similarity (both sides saying the same thing), not self-similarity. Cross-author agreement at 0.55 Jaccard indicates strong convergence.
- **window=3**: Check last 3 exchange pairs. If all 3 show convergence, the conversation is done.
- **Returns None on failure**: Fail-open — if DB fails, DM continues normally.

### 2. `src/probos/events.py` — NEW event type

Add after `CONVERGENCE_DETECTED` (line 137):

```python
    DM_CONVERGENCE_DETECTED = "dm_convergence_detected"  # AD-623: DM thread converged
```

**Note:** `CONVERGENCE_DETECTED` (AD-551) is for analytical convergence across agents' analytical outputs. `DM_CONVERGENCE_DETECTED` is for conversational convergence in a specific DM thread. Different events, different semantics.

### 3. `src/probos/ward_room_router.py` — Convergence gate in `route_event()`

**Insert AFTER the existing AD-614 exchange limit check (after line 306) and BEFORE Layer 4 (line 308):**

```python
            # AD-623: DM convergence gate — detect mutual agreement loops.
            # If both participants are echoing each other, the conversation
            # has reached its natural conclusion. Lock the thread.
            if channel and channel.channel_type == "dm" and thread_id:
                try:
                    from probos.ward_room.threads import check_dm_convergence
                    convergence = await check_dm_convergence(
                        self._ward_room._db if self._ward_room else None,
                        thread_id,
                    )
                    if convergence and convergence.get("converged"):
                        logger.info(
                            "AD-623: DM thread %s converged (sim=%.3f, exchanges=%d), "
                            "locking thread",
                            thread_id[:8],
                            convergence["similarity"],
                            convergence["exchange_count"],
                        )
                        # Emit event for Counselor/telemetry
                        if self._emit_event_fn:
                            await self._emit_event_fn(
                                "dm_convergence_detected",
                                {
                                    "thread_id": thread_id,
                                    "channel_id": channel.id if channel else "",
                                    "similarity": convergence["similarity"],
                                    "exchange_count": convergence["exchange_count"],
                                    "participants": list(set(
                                        p for p in [author_id, agent_id] if p
                                    )),
                                },
                            )
                        # Stop routing to this agent — conversation is done
                        continue
                except Exception:
                    logger.debug("AD-623: convergence gate check failed", exc_info=True)
```

**IMPORTANT — Check `self._ward_room._db` access.** The router should NOT reach into private attributes. There are two approaches:

**(A) If WardRoomService exposes the DB (preferred):** Check if `self._ward_room` (which is a WardRoomService or WardRoom facade) exposes a public `.db` property or a method that accepts a callback. If so, use that.

**(B) If no public DB access:** Add a convenience method to the WardRoomService:
```python
async def check_dm_convergence(self, thread_id: str) -> dict | None:
    """AD-623: Check if a DM thread has converged."""
    from probos.ward_room.threads import check_dm_convergence
    if not self._db:
        return None
    return await check_dm_convergence(self._db, thread_id)
```
Then the router calls `await self._ward_room.check_dm_convergence(thread_id)` — clean Law of Demeter.

**Builder: check whether `self._ward_room` in the router is a WardRoomService instance (from `probos.ward_room.messages`) and whether it exposes a `_db` attribute. If it does NOT have a public DB accessor, use approach (B) — add `check_dm_convergence()` method to WardRoomService. Avoid `self._ward_room._db` pattern.**

**Placement in the guard chain:** The convergence gate runs AFTER the exchange limit check. This is intentional — if the agent hit the exchange limit, they're already blocked (no need to run convergence check). The convergence gate catches the case where both agents are UNDER the limit but have already reached agreement.

**Event emission note:** The event is emitted inside the per-agent loop, but convergence is thread-level. To avoid duplicate events (once per remaining target agent), you could move it above the loop or use a flag. Simplest: check `convergence` once before the per-agent loop and skip ALL agents if converged. This is cleaner:

```python
        # AD-623: DM convergence gate — thread-level check (before per-agent loop)
        _dm_converged = False
        if channel and channel.channel_type == "dm" and thread_id:
            try:
                convergence = await self._ward_room.check_dm_convergence(thread_id)
                if convergence and convergence.get("converged"):
                    logger.info(
                        "AD-623: DM thread %s converged (sim=%.3f, exchanges=%d)",
                        thread_id[:8],
                        convergence["similarity"],
                        convergence["exchange_count"],
                    )
                    if self._emit_event_fn:
                        await self._emit_event_fn(
                            "dm_convergence_detected",
                            {
                                "thread_id": thread_id,
                                "channel_id": channel.id if channel else "",
                                "similarity": convergence["similarity"],
                                "exchange_count": convergence["exchange_count"],
                            },
                        )
                    _dm_converged = True
            except Exception:
                logger.debug("AD-623: convergence gate check failed", exc_info=True)

        if _dm_converged:
            return  # Thread is done — no more routing
```

**Place this block after the target agent list is built (after line 226) but before the per-agent notification loop (before line 257).** This way convergence is checked once, not per-agent.

### 4. `src/probos/cognitive/cognitive_agent.py` — Self-monitoring in WR notification/DM path

**The problem:** `_build_self_monitoring_context()` lives in `proactive.py` (ProactiveLoop class). It's called during proactive cycles only. The `ward_room_notification` and `direct_message` paths in `cognitive_agent.py` have no self-monitoring, so agents responding to DM posts have zero awareness of their own repetition.

**Solution:** Inject a lightweight self-monitoring check into the `_build_input()` ward_room_notification path. This needs to be self-contained — can't import ProactiveLoop just for this.

**Add a method to CognitiveAgent:**

```python
    async def _build_dm_self_monitoring(self, thread_id: str) -> str | None:
        """AD-623: Lightweight self-monitoring for DM/WR response path.

        Check this agent's own recent posts in the thread for self-repetition.
        Returns a warning string if similarity is high, None otherwise.
        """
        rt = getattr(self, '_runtime', None)
        if not rt or not hasattr(rt, 'ward_room') or not rt.ward_room:
            return None

        try:
            callsign = getattr(self, 'callsign', None) or getattr(self, 'agent_type', '')
            # Get this agent's recent posts in the thread
            posts = await rt.ward_room.get_posts_by_author(
                callsign, limit=3, thread_id=thread_id,
            )
            if not posts or len(posts) < 2:
                return None

            from probos.cognitive.similarity import jaccard_similarity, text_to_words
            word_sets = [text_to_words(p["body"]) for p in posts]
            total_sim = 0.0
            pair_count = 0
            for j in range(len(word_sets)):
                for k in range(j + 1, len(word_sets)):
                    total_sim += jaccard_similarity(word_sets[j], word_sets[k])
                    pair_count += 1

            if pair_count > 0:
                avg_sim = total_sim / pair_count
                if avg_sim >= 0.4:
                    return (
                        "--- Self-monitoring (AD-623) ---\n"
                        f"WARNING: Your last {len(posts)} messages in this thread "
                        f"show {avg_sim:.0%} self-similarity. You may be repeating "
                        "yourself. If you and the other person agree, conclude the "
                        "conversation naturally. Do NOT restate conclusions you've "
                        "already communicated. If there's nothing new to add, "
                        "respond with exactly: [NO_RESPONSE]"
                    )
        except Exception:
            logger.debug("AD-623: DM self-monitoring failed", exc_info=True)

        return None
```

**IMPORTANT — Check `get_posts_by_author()` signature.** It's at `proactive.py:1473` where it's called with `callsign, limit=, since=`. Check:
1. Does it accept a `thread_id` parameter? If not, we need to filter by thread_id separately.
2. Does it return dicts with `"body"` key? (Yes — confirmed at `proactive.py:1476`)

**Builder: read `ward_room.get_posts_by_author()` implementation (likely in `ward_room/messages.py`). If it doesn't accept `thread_id`, add an optional `thread_id` parameter that filters by thread. If it does, use it directly.**

**Injection point in `_build_input()` — ward_room_notification path (line 2223):**

After the cognitive zone awareness block (after line 2249) and before Working Memory (line 2269), add:

```python
            # AD-623: DM self-monitoring — agents responding to DM threads
            # see their own repetition in real time
            if channel_name.startswith("dm-") or params.get("channel_type") == "dm":
                _dm_self_mon = await self._build_dm_self_monitoring(
                    params.get("thread_id", ""),
                )
                if _dm_self_mon:
                    wr_parts.append("")
                    wr_parts.append(_dm_self_mon)
```

**How to detect DM channel in ward_room_notification path:** The `params` dict (set in WardRoomRouter at lines 326-344) includes `channel_name`. DM channels are named `dm-{agent1}-{agent2}`. Check: does `params` include `channel_type`? If yes, use `params.get("channel_type") == "dm"`. If not, infer from channel_name prefix. **Builder: check what params the router passes for DM notifications — look at lines 326-344.**

### 5. `src/probos/ward_room/messages.py` — Add `thread_id` filter to `get_posts_by_author()`

**Only if `get_posts_by_author()` doesn't already support thread_id filtering.** Builder: read the method signature first.

If needed, add optional `thread_id` parameter:

```python
async def get_posts_by_author(
    self, callsign: str, limit: int = 5, since: float | None = None,
    thread_id: str | None = None,
) -> list[dict]:
    """..."""
    # Existing implementation + optional WHERE thread_id = ? clause
```

### 6. `src/probos/cognitive/counselor.py` — Counselor handler for DM_CONVERGENCE_DETECTED

The Counselor already subscribes to multiple events. Add a handler for the new event:

```python
    async def _on_dm_convergence_detected(self, event_type: str, data: dict) -> None:
        """AD-623: Log DM convergence for crew assessment.

        Convergence in DMs can indicate either healthy closure or stuck
        communication patterns. Record for clinical assessment context.
        """
        thread_id = data.get("thread_id", "")
        similarity = data.get("similarity", 0.0)
        participants = data.get("participants", [])
        logger.info(
            "AD-623: Counselor noting DM convergence in %s (sim=%.3f, participants=%s)",
            thread_id[:8], similarity, participants,
        )
        # Store in Counselor's profile DB for future wellness assessments
        # (uses existing profile persistence infrastructure from AD-505)
```

**Wire the subscription** in the Counselor's event registration (wherever `PEER_REPETITION_DETECTED` is subscribed, add `DM_CONVERGENCE_DETECTED` adjacent):

```python
event_bus.subscribe("dm_convergence_detected", self._on_dm_convergence_detected)
```

**Builder: find where PEER_REPETITION_DETECTED is subscribed in counselor.py and add the new subscription adjacent to it.**

## Tests

### File: `tests/test_ad623_dm_convergence.py` (NEW)

**Convergence detection tests:**
1. **No convergence — dissimilar posts** — Two agents with different post content → `check_dm_convergence()` returns None.
2. **Convergence detected — mutual echo** — Both agents repeating similar content → returns `{"converged": True, "similarity": >0.55}`.
3. **Insufficient posts** — Thread with <4 posts → returns None.
4. **Mixed similarity** — Some pairs similar, some not → below threshold → returns None.
5. **Same author consecutive** — Posts by same author in a row → skipped as exchange pairs (need different authors).

**Router convergence gate tests:**
6. **Router stops routing on convergence** — DM thread converged → `route_event()` returns without sending intents.
7. **Router continues on non-convergence** — DM thread not converged → intents sent normally.
8. **Event emitted on convergence** — `DM_CONVERGENCE_DETECTED` event emitted with thread_id, similarity, exchange_count.
9. **Non-DM channels skip convergence check** — Department/ship channel posts → convergence check not called.
10. **Convergence check failure = continue** — If `check_dm_convergence()` raises → fail open, continue routing.

**Self-monitoring tests:**
11. **Self-monitoring injected for DM notifications** — Agent responding to DM notification gets self-monitoring context when self-similarity is high.
12. **No self-monitoring for low similarity** — Agent's posts are diverse → no warning injected.
13. **No self-monitoring for non-DM channels** — Ward Room notification in department channel → no DM self-monitoring.
14. **Self-monitoring failure = degraded** — If `get_posts_by_author()` fails → no crash, no warning injected.

**Integration tests:**
15. **Exchange limit + convergence gate ordering** — Agent over exchange limit → blocked by exchange limit before convergence check runs.
16. **Convergence + [NO_RESPONSE]** — Agent receiving self-monitoring warning responds [NO_RESPONSE] → post not created.

## Verification

```bash
# AD-623 tests
uv run python -m pytest tests/test_ad623_dm_convergence.py -v

# Verify convergence check is in router
grep -n "dm_convergence" src/probos/ward_room_router.py

# Verify self-monitoring in WR notification path
grep -n "dm_self_monitoring\|AD-623" src/probos/cognitive/cognitive_agent.py

# Verify event type exists
grep -n "DM_CONVERGENCE" src/probos/events.py

# Existing tests still pass
uv run python -m pytest tests/ -x -q
```

## Tracking Updates

- PROGRESS.md: AD-623 → IN PROGRESS
- DECISIONS.md: Add AD-623 entry after build
- roadmap.md: Update status
- GitHub Project: Issue #212 → In Progress
