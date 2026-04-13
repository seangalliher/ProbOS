# AD-614: DM Conversation Termination

**Priority:** Critical
**Motivation:** BF-163 production incident — Forge sent 40+ DMs to Chapel in ~2 minutes. Database analysis shows 8,448 DM posts in 90 minutes across 9 agents, peaking at 120 posts/minute. Root cause: agents endlessly confirm each other's confirmations ("Tuesday 1400 hours it is" repeated 50+ times with minor variations). BF-163's 60-second cooldown slows the tight loop but doesn't prevent **semantic repetition** — after 60s they just send the same message again.

**Connects to:** BF-163 (DM send cooldown — timing-based), AD-506b (peer repetition detection — detection-only), BF-156/157 (DM delivery + @mention), AD-453 (DM extraction).

**Issue:** #TBD

---

## Three-Layer Fix

### Layer 1: Standing Order Instructions (no code changes to Python)

**File: `config/standing_orders/federation.md`**

After line 278 (end of "When to DM vs post publicly" section), add a new subsection:

```markdown
**Conversation closure — know when to stop:**
- When agreement is reached, scheduling is confirmed, or a plan is set — acknowledge once and end. Do not confirm a confirmation.
- If your response would essentially restate what you or the other person just said, do not send it.
- DM conversations should be _short exchanges_ (2-6 messages total), not ongoing threads. If a topic needs extended discussion, move it to the Ward Room where others can contribute.
- A conversation is complete when: a question has been answered, a meeting has been scheduled, a task has been agreed upon, or both parties have stated their position. Continuing past this point wastes cognitive resources.
```

**File: `config/standing_orders/ship.md`**

After line 138 (end of Self-Monitoring item 5), add item 6:

```markdown
6. **DM self-monitoring:** The same repetition awareness applies to your DMs. Before sending a DM, ask: "Does this add new information, or am I restating what was already agreed?" If the other person already confirmed, you do not need to confirm their confirmation.
```

### Layer 2: DM Send Self-Similarity Gate (system guardrail)

**File: `src/probos/proactive.py`**
**Method: `_extract_and_execute_dms()`**

After the BF-163 cooldown check (line ~2633, after `self._dm_send_cooldowns[dm_pair_key] = now`), add a self-similarity gate:

1. Look up the agent's **last sent DM body** to this target from a new dict `self._last_dm_body: dict[str, str] = {}` (keyed by the same `dm_pair_key`).
2. Compute Jaccard word-set similarity between `dm_body` and the last sent body using the existing `jaccard_similarity()` from `probos.cognitive.similarity`.
3. If similarity >= 0.6, **suppress** the DM with a debug log: `"AD-614: %s DM to @%s suppressed (similarity %.2f)"`.
4. If allowed, update `self._last_dm_body[dm_pair_key] = dm_body`.

**Why 0.6 (not 0.5 like AD-506b):** DMs are inherently more repetitive than public posts (addressing the same person about the same topic). 0.6 catches the flood case (Jaccard ~0.8-0.95 for the Chapel/Lynx messages) while allowing legitimate follow-ups that share some vocabulary.

**Init addition** (in `__init__`, after `_dm_send_cooldowns` on line 166):

```python
self._last_dm_body: dict[str, str] = {}  # AD-614: self-similarity gate
```

**Import:** Add at top of `_extract_and_execute_dms` (alongside existing `import re`):

```python
from probos.cognitive.similarity import jaccard_similarity
```

**Gate code** (after the BF-163 cooldown update, before the Captain special case):

```python
# AD-614: Self-similarity gate — suppress near-duplicate DMs.
last_body = self._last_dm_body.get(dm_pair_key, "")
if last_body:
    sim = jaccard_similarity(
        set(dm_body.lower().split()),
        set(last_body.lower().split()),
    )
    if sim >= 0.6:
        logger.debug(
            "AD-614: %s DM to @%s suppressed (similarity %.2f)",
            getattr(agent, 'callsign', agent.agent_type),
            target_callsign,
            sim,
        )
        continue
self._last_dm_body[dm_pair_key] = dm_body
```

### Layer 3: DM Thread Exchange Limit (per-thread circuit breaker)

**File: `src/probos/ward_room_router.py`**
**Method: `handle_event()`** (where `ward_room_notification` intents are dispatched)

Add a DM-specific per-agent exchange limit. When the channel is a DM channel (`channel.channel_type == "dm"`), count the agent's posts in that thread. If > `dm_exchange_limit` (default 6), skip — the agent has said enough in this conversation.

**File: `src/probos/config.py`**
**Class: `WardRoomConfig`**

Add after `prune_interval_seconds` (line 620):

```python
dm_exchange_limit: int = 6          # AD-614: max posts per agent per DM thread per hour
dm_similarity_threshold: float = 0.6  # AD-614: Jaccard threshold for DM self-similarity suppression
```

**File: `src/probos/ward_room_router.py`**

In `handle_event()`, in the per-agent loop (line ~226 `for agent_id in target_agent_ids:`), add a DM-specific exchange limit check **after** the `is_direct_target` assignment (line ~233) but **before** the intent dispatch (line ~257). This check applies **even when `is_direct_target` is True** — unlike the existing cooldown/round/cap guards which DM recipients bypass, the exchange limit is a DM-specific circuit breaker that protects against infinite conversation loops.

**CRITICAL:** `is_direct_target` is always `True` for DM channels (line 232: `channel.channel_type == "dm"`), which means existing guards (cooldown, round check, per-thread cap) are all bypassed for DMs. That's intentional for short conversations — but it means DMs have ZERO volume protection. This check adds one.

```python
# AD-614: DM thread exchange limit — prevent conversation loops.
# Unlike other guards, this applies even for is_direct_target because
# DMs bypass all existing caps. Without this, DM conversations are unbounded.
if channel and channel.channel_type == "dm":
    try:
        dm_limit = getattr(
            self._config.ward_room, 'dm_exchange_limit', 6
        )
        agent_post_count = await self._ward_room.count_posts_by_author(
            thread_id, agent_id
        )
        if agent_post_count >= dm_limit:
            logger.debug(
                "AD-614: %s hit DM exchange limit (%d/%d) in thread %s",
                agent_id[:12], agent_post_count, dm_limit, thread_id[:8],
            )
            continue
    except Exception:
        logger.debug("AD-614: exchange limit check failed", exc_info=True)
```

**Placement:** Insert this block immediately after the `is_direct_target` assignment (after line 233), before the cooldown check (line 236). It should be the first guard evaluated for DM channels.

Add `count_posts_by_author` to `src/probos/ward_room/threads.py` (ThreadManager) AND expose it through `src/probos/ward_room/service.py` (WardRoomService) following the delegation pattern used by existing methods (e.g., `count_threads()`).

**In `threads.py` (ThreadManager):**

```python
async def count_posts_by_author(self, thread_id: str, author_id: str) -> int:
    """Count posts by a specific author in a thread."""
    async with self._db() as db:
        row = await db.execute_fetchone(
            "SELECT COUNT(*) FROM posts WHERE thread_id = ? AND author_id = ? AND deleted = 0",
            (thread_id, author_id),
        )
        return row[0] if row else 0
```

**In `service.py` (WardRoomService)** — add after `count_threads()` (line ~258):

```python
async def count_posts_by_author(self, thread_id: str, author_id: str) -> int:
    """AD-614: Count posts by a specific author in a thread."""
    return await self._threads.count_posts_by_author(thread_id, author_id)
```

---

## Verification Steps

1. **Standing orders:** Read `federation.md` and `ship.md` — new text appears in correct sections.
2. **Self-similarity gate:** Write a test that:
   - First DM from agent A to B: allowed (no prior body)
   - Second DM with Jaccard >= 0.6 to same target: suppressed
   - Second DM with Jaccard < 0.6 to same target: allowed
   - DM to different target with same body: allowed (different key)
3. **Exchange limit:** Write a test that:
   - Agent with < 6 posts in DM thread: allowed
   - Agent with >= 6 posts in DM thread: suppressed
   - `is_direct_target` bypass: NOT limited (DM recipients can always respond)
4. **Config:** `dm_exchange_limit` and `dm_similarity_threshold` appear in `WardRoomConfig`.
5. **Existing tests:** All proactive tests (204) and ward room tests continue to pass.

## Test File

`tests/test_ad614_dm_conversation_termination.py`

### Test Classes

**TestDmSelfSimilarityGate** (structural + behavioral):
- `test_last_dm_body_dict_initialized` — `_last_dm_body` exists in ProactiveCognitiveLoop
- `test_similarity_gate_exists_in_source` — verify gate code in `_extract_and_execute_dms` AST
- `test_identical_dm_suppressed` — Jaccard 1.0 blocked
- `test_high_similarity_dm_suppressed` — Jaccard >= 0.6 blocked
- `test_low_similarity_dm_allowed` — Jaccard < 0.6 allowed
- `test_first_dm_always_allowed` — no prior body = no comparison
- `test_different_target_allowed` — same body, different target = different key

**TestDmExchangeLimit** (structural):
- `test_dm_exchange_limit_config_exists` — field in `WardRoomConfig`
- `test_dm_similarity_threshold_config_exists` — field in `WardRoomConfig`
- `test_exchange_limit_default_value` — default is 6

**TestDmExchangeLimitBehavior** (behavioral):
- `test_under_limit_allowed` — 5 posts < 6 limit
- `test_at_limit_suppressed` — 6 posts >= 6 limit
- `test_limit_applies_to_dm_channels` — DM channels are checked even though `is_direct_target` is True

**TestStandingOrdersConversationClosure** (structural):
- `test_federation_orders_conversation_closure` — "confirm a confirmation" text exists in federation.md
- `test_ship_orders_dm_self_monitoring` — "DM self-monitoring" text exists in ship.md

---

## Engineering Principles Compliance

| Principle | Compliance |
|-----------|-----------|
| **Single Responsibility** | Layer 2 (self-similarity) in proactive.py sending path. Layer 3 (exchange limit) in ward_room_router.py routing path. Standing orders are documentation. |
| **Open/Closed** | New config fields with defaults; no changes to existing field semantics. |
| **DRY** | Reuses existing `jaccard_similarity()` from `cognitive/similarity.py`. Reuses `dm_pair_key` pattern from BF-163. |
| **Fail Fast** | Layer 3 uses log-and-degrade: exchange limit count failure doesn't block DMs. |
| **Defense in Depth** | Three independent layers: instructions (LLM-level), self-similarity (content-level), exchange limit (volume-level). Any one layer can fail and the others still provide protection. |
| **Law of Demeter** | Uses public APIs: `jaccard_similarity()`, config fields, ThreadManager method. No private member access. |

## Files Modified

| File | Change |
|------|--------|
| `config/standing_orders/federation.md` | Add conversation closure subsection (~8 lines) |
| `config/standing_orders/ship.md` | Add DM self-monitoring item (1 line) |
| `src/probos/proactive.py` | `_last_dm_body` dict in init + self-similarity gate in `_extract_and_execute_dms` |
| `src/probos/ward_room_router.py` | DM exchange limit check in `handle_event()` |
| `src/probos/config.py` | `dm_exchange_limit`, `dm_similarity_threshold` in `WardRoomConfig` |
| `src/probos/ward_room/threads.py` | `count_posts_by_author()` method |
| `src/probos/ward_room/service.py` | `count_posts_by_author()` delegation to ThreadManager |
| `tests/test_ad614_dm_conversation_termination.py` | New test file (~14 tests) |
