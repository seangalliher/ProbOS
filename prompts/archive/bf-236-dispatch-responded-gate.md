# BF-236: Semantic Duplicate Dispatch — Round-Scoped Post Tracker

**Status:** Ready for builder
**Priority:** Medium
**Files:** `src/probos/ward_room_router.py`, `src/probos/ward_room_pipeline.py`, `tests/test_bf236_dispatch_dedup_gate.py`

## Problem

Agents post duplicate responses in the same Ward Room thread when multiple posts arrive in quick succession. BF-234 catches transport-layer duplicates (identical intent IDs from JetStream redelivery), but a higher-level semantic duplicate occurs when the router dispatches *different* intents to the same agent for the same thread from separate `route_event()` calls.

**Observed (2026-04-25, thread 6bd36913):** 6 agents each posted twice to the same thread — once from each of two back-to-back `route_event()` calls triggered by near-simultaneous posts.

**Root cause:** `_route_to_agents()` has no check for "has this agent already posted in the current conversational round for this thread?" The existing BF-198 `_responded_threads` tracker is keyed on `(agent_id, thread_id)` with a 600s eviction window — using it as a dispatch gate would block agents from responding to *any* Captain follow-up in the same thread for 10 minutes, breaking multi-turn conversations.

**Correct invariant:** Track posts per-round, cleared on Captain repost. Captain posts reset the conversational round (lines 274–280 in `ward_room_router.py` already reset `_thread_rounds` and clear `_round_participants`). The new tracker should be cleared alongside them so agents become eligible again when the Captain follows up.

**Coverage (honest):** BF-236 catches semantic duplicates when pipeline recording from the first dispatch (multi-second LLM delay + post) outpaces the second `route_event()` call. For sub-second rapid-fire events where both route_events run before any pipeline recording, BF-236 does not help — BF-234 (transport-layer dedup) and BF-197 (content similarity guard) provide defense at those layers. BF-236 is partial coverage, defense-in-depth, not a full fix.

## What This Does NOT Change

- `intent.py` — no changes. Consumer-side dedup (BF-234) and response recording (AD-654b) remain as-is.
- `proactive.py` — no changes. Its 3 existing `has_agent_responded()` call sites use BF-198's `_responded_threads`, which is a different tracker and different invariant.
- BF-198 `_responded_threads` / `record_agent_response()` / `has_agent_responded()` — completely untouched. BF-198 is semantic round-tracking for proactive-loop dedup. BF-236 adds a separate tracker for dispatch-level dedup.
- BF-234 `_seen_intents` transport-layer dedup — unchanged. Different invariant, different key (intent ID vs agent+thread).
- BF-201 thread post cap — unchanged.
- AD-614 DM exchange limit — unchanged.
- AD-623 convergence gate — unchanged (thread-level, not agent-level).

---

## Section 1: Add Round-Scoped Post Tracker to WardRoomRouter

**File:** `src/probos/ward_room_router.py`

### 1a: Add state in `__init__`

After the existing `_responded_threads` state block (search for the comment `# BF-198: Track threads each agent has already responded to.`), add:

```python
        # BF-236: Round-scoped post tracker — dispatch-level semantic dedup.
        # Tracks which agents have already POSTED (not just been dispatched) in
        # the current conversational round for each thread. Cleared on Captain
        # repost alongside _round_participants. Key: (agent_id, thread_id).
        # Separate from BF-198 _responded_threads (different invariant, different
        # lifecycle — _responded_threads serves proactive-loop dedup with 600s
        # eviction; this tracker resets per-round).
        self._posted_in_round: dict[tuple[str, str], float] = {}
        self._last_posted_in_round_eviction: float = time.time()
```

### 1b: Add public methods

After the existing BF-198 methods section (search for the comment `# BF-198: Responded-thread tracker`), add a new section:

```python
    # ------------------------------------------------------------------
    # BF-236: Round-scoped post tracker (dispatch-level semantic dedup)
    # ------------------------------------------------------------------

    def record_round_post(self, agent_id: str, thread_id: str) -> None:
        """BF-236: Record that agent posted in the current round of a thread.

        Called by WardRoomPostPipeline after create_post (Step 8).
        """
        if not agent_id or not thread_id:
            return
        self._posted_in_round[(agent_id, thread_id)] = time.time()

    def has_posted_in_round(self, agent_id: str, thread_id: str) -> bool:
        """BF-236: Check if agent already posted in the current round."""
        if not agent_id or not thread_id:
            return False
        return (agent_id, thread_id) in self._posted_in_round

    def _clear_round_posts_for_thread(self, thread_id: str) -> None:
        """BF-236: Clear round-post records for a thread (Captain repost)."""
        self._posted_in_round = {
            k: v for k, v in self._posted_in_round.items()
            if k[1] != thread_id
        }

    def _evict_stale_round_posts(self, max_age: float = 120.0) -> None:
        """BF-236: Evict round-post records older than max_age seconds."""
        cutoff = time.time() - max_age
        self._posted_in_round = {
            k: v for k, v in self._posted_in_round.items() if v > cutoff
        }
        self._last_posted_in_round_eviction = time.time()

    def _maybe_evict_round_posts(self, interval: float = 60.0) -> None:
        """BF-236: Periodic eviction — runs at most once per interval seconds.

        Interval (60s) is half of max_age (120s) so stale entries are caught
        within one round of typical conversation flow. Shorter ratio than
        BF-198's 60s/600s because round-post records are transient (cleared
        on Captain repost) and the 120s max_age only needs to cover a
        long-tailed LLM handler followed by post.
        """
        if time.time() - self._last_posted_in_round_eviction >= interval:
            self._evict_stale_round_posts()
```

### 1c: Clear tracker on Captain repost

In `route_event()`, find the Captain repost block (search for the comment `# Captain posts reset the round counter`). After the existing `_round_participants` clearing loop, add one line:

Current code:
```python
        # Captain posts reset the round counter (must happen before depth check)
        if is_captain and thread_id:
            self._thread_rounds[thread_id] = 0
            # Clear round participation tracking for this thread
            keys_to_clear = [k for k in self._round_participants
                             if k.startswith(f"{thread_id}:")]
            for k in keys_to_clear:
                del self._round_participants[k]
```

Replace with:
```python
        # Captain posts reset the round counter (must happen before depth check)
        if is_captain and thread_id:
            self._thread_rounds[thread_id] = 0
            # Clear round participation tracking for this thread
            keys_to_clear = [k for k in self._round_participants
                             if k.startswith(f"{thread_id}:")]
            for k in keys_to_clear:
                del self._round_participants[k]
            # BF-236: Clear round-post records so agents can respond to
            # Captain follow-ups in the same thread.
            self._clear_round_posts_for_thread(thread_id)
```

### 1d: Add gate to Phase 1 eligibility

In `_route_to_agents()`, after the Layer 3 round-participation check (search for the comment `# Layer 3: Agent already responded in this round of this thread`) and before the `IntentMessage` construction (search for `intent = IntentMessage(`), insert the BF-236 gate:

Current code:
```python
            # Layer 3: Agent already responded in this round of this thread
            if not is_direct_target and is_agent_post and agent_id in round_participants:
                continue

            intent = IntentMessage(
```

Replace with:
```python
            # Layer 3: Agent already responded in this round of this thread
            if not is_direct_target and is_agent_post and agent_id in round_participants:
                continue

            # BF-236: Semantic dispatch dedup — skip agent if it already posted
            # in the current round of this thread. Recorded by pipeline after
            # create_post. Cleared on Captain repost. Separate from BF-198's
            # _responded_threads (proactive-loop dedup, 600s window). NOT gated
            # on is_agent_post — duplicates occur on Captain-authored threads too.
            # Explicit dispatch (@mention, DM) bypasses — same as cooldown/round gates.
            if not is_direct_target and self.has_posted_in_round(agent_id, thread_id):
                logger.debug(
                    "BF-236: %s already posted in round for thread %s, skipping",
                    agent_id[:12], thread_id[:8],
                )
                continue

            intent = IntentMessage(
```

### 1e: Add periodic eviction call

In `route_event()`, find the existing `_maybe_evict_stale_responses()` call (search for `self._maybe_evict_stale_responses()`). Add the BF-236 eviction call immediately after:

Current code:
```python
        self._maybe_evict_stale_responses()
```

Replace with:
```python
        self._maybe_evict_stale_responses()
        self._maybe_evict_round_posts()  # BF-236
```

### 1f: Extend `cleanup_tracking()` for pruned threads

In `cleanup_tracking()` (around line 1006), add BF-236 cleanup after the existing BF-201 `_cap_notices_posted` cleanup:

Current code:
```python
        # BF-201: Clean up cap notification dedup state for pruned threads
        self._cap_notices_posted = {
            (tid, cap) for tid, cap in self._cap_notices_posted
            if tid not in pruned_thread_ids
        }
```

Replace with:
```python
        # BF-201: Clean up cap notification dedup state for pruned threads
        self._cap_notices_posted = {
            (tid, cap) for tid, cap in self._cap_notices_posted
            if tid not in pruned_thread_ids
        }
        # BF-236: Clean up round-post records for pruned threads
        self._posted_in_round = {
            k: v for k, v in self._posted_in_round.items()
            if k[1] not in pruned_thread_ids
        }
```

---

## Section 2: Record Post in Pipeline

**File:** `src/probos/ward_room_pipeline.py`

In `process_and_post()`, after the existing BF-198 response recording (search for the comment `# Step 8: Record response (BF-198 anti-double-posting)`), add the BF-236 recording:

Current code:
```python
        # Step 8: Record response (BF-198 anti-double-posting)
        if self._router:
            self._router.record_agent_response(agent.id, thread_id)
```

Replace with:
```python
        # Step 8: Record response (BF-198 anti-double-posting)
        if self._router:
            self._router.record_agent_response(agent.id, thread_id)
            self._router.record_round_post(agent.id, thread_id)  # BF-236
```

**Why record here (after create_post) and not at dispatch time:**
- Recording at post time means the gate only fires after a **real post**, not after delivery. If an agent is dispatched but doesn't post (BF-197 similarity filter, `[NO_RESPONSE]`, LLM error), the tracker stays clean and the agent remains eligible for the next dispatch.
- The multi-second LLM delay between dispatch and post means the recording happens after enough time that a second `route_event()` call (from a follow-up post arriving seconds later) will see it. This covers the most common real-world duplicate scenario.
- For sub-second rapid-fire events where both route_events run before any pipeline recording, the gate won't help — BF-234 (transport) and BF-197 (content similarity) cover those layers.

---

## Section 3: Tests

**File:** `tests/test_bf236_dispatch_dedup_gate.py`

New test file.

**Imports:**
```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
```

**Helpers:**
```python
def _make_config():
    cfg = MagicMock()
    cfg.ward_room.event_coalesce_ms = 200
    cfg.ward_room.max_thread_posts = 50
    return cfg


def _make_router():
    from probos.ward_room_router import WardRoomRouter

    ontology = MagicMock()
    ontology.get_agent_department.return_value = None

    return WardRoomRouter(
        ward_room=MagicMock(),
        registry=MagicMock(),
        intent_bus=MagicMock(),
        trust_network=MagicMock(),
        ontology=ontology,
        callsign_registry=MagicMock(),
        episodic_memory=None,
        event_emitter=MagicMock(),
        event_log=MagicMock(),
        config=_make_config(),
        proactive_loop=None,
    )


def _route_args(router, **overrides):
    """Build default _route_to_agents() kwargs, applying overrides."""
    channel = MagicMock()
    channel.channel_type = overrides.pop("channel_type", "ship")
    channel.name = "general"
    defaults = dict(
        target_agent_ids=["agent-a"],
        is_captain=True,
        is_agent_post=False,
        mentioned_agent_ids=set(),
        channel=channel,
        thread_id="thread-1",
        channel_id="chan-1",
        event_type="new_post",
        title="Test",
        author_id="captain-1",
        data={},
        thread_context="context",
        cooldown=0,
        current_round=0,
        round_participants=set(),
    )
    defaults.update(overrides)
    return defaults
```

### Test 1: `test_gate_skips_agent_that_already_posted`

Record round post via `router.record_round_post("agent-a", "thread-1")`. Call `await router._route_to_agents(**_route_args(router))`. Assert `router._intent_bus.dispatch_async.assert_not_called()` — agent-a was skipped.

### Test 2: `test_gate_allows_agent_without_prior_post`

Do NOT record a prior post. Mock `router._intent_bus.dispatch_async = AsyncMock()`. Call `await router._route_to_agents(**_route_args(router))`. Assert `router._intent_bus.dispatch_async.assert_called_once()`.

### Test 3: `test_gate_bypassed_for_mentioned_agent`

Record round post for agent-a in thread-1. Mock `router._intent_bus.dispatch_async = AsyncMock()`. Call with `mentioned_agent_ids={"agent-a"}`. Assert `dispatch_async` was called — explicit @mention bypasses.

### Test 4: `test_gate_bypassed_for_dm_channel`

Record round post for agent-a in thread-1. Set `channel_type="dm"`. Set `router._ward_room.count_posts_by_author = AsyncMock(return_value=0)` (prevent AD-614 exchange limit from triggering). Mock `router._intent_bus.dispatch_async = AsyncMock()`. Assert `dispatch_async` was called — DM `is_direct_target` bypasses.

### Test 5: `test_gate_fires_for_both_captain_and_agent_posts`

Parametrize with `@pytest.mark.parametrize("is_captain,is_agent_post", [(True, False), (False, True)])`. Record round post for agent-a. Call with each parameter combo. Assert `dispatch_async` not called in either case — gate is NOT gated on `is_agent_post`.

### Test 6: `test_gate_no_crash_on_empty_thread_id`

Call with `thread_id=""`. `has_posted_in_round()` returns False for empty thread_id. Assert no exception and dispatch proceeds normally.

### Test 7: `test_gate_allows_different_thread`

Record round post for agent-a in thread-1. Call with `thread_id="thread-2"`. Assert `dispatch_async` was called.

### Test 8: `test_gate_allows_different_agent_same_thread`

Record round post for agent-a in thread-1. Call with `target_agent_ids=["agent-b"]`. Assert `dispatch_async` was called.

### Test 9: `test_captain_repost_clears_tracker_agent_eligible_again`

**This is the multi-turn regression guard.** Record round post for agent-a in thread-1. Assert `router.has_posted_in_round("agent-a", "thread-1") is True`. Call `router._clear_round_posts_for_thread("thread-1")`. Assert `router.has_posted_in_round("agent-a", "thread-1") is False`. Mock `router._intent_bus.dispatch_async = AsyncMock()`. Call `await router._route_to_agents(**_route_args(router))`. Assert `dispatch_async.assert_called_once()` — agent-a is eligible again after Captain repost clears the tracker.

### Test 9b: `test_captain_repost_clears_tracker_via_route_event`

**Verifies the 1c wiring — that `route_event()` actually calls `_clear_round_posts_for_thread()` on Captain repost.** Without this, a builder who forgets the 1c line can still pass Test 9 (which calls the helper directly). Setup: record round post for agent-a in thread-1. Mock `router._ward_room = MagicMock()` with `router._ward_room.get_thread = AsyncMock(return_value={"thread": {"channel_id": "chan-1", "thread_mode": "discuss"}})`, `router._ward_room.get_channel = AsyncMock(return_value=MagicMock(channel_type="ship", name="general"))`, and `router._ward_room.count_posts_in_thread = AsyncMock(return_value=1)`. Call `await router.route_event("ward_room_post_created", {"author_id": "captain", "thread_id": "thread-1", "channel_id": "chan-1"})`. Assert `router.has_posted_in_round("agent-a", "thread-1") is False` — the tracker was cleared as a side effect of the Captain repost path in `route_event()`.

### Test 10: `test_clear_does_not_affect_other_threads`

Record round post for agent-a in thread-1 AND thread-2. Call `router._clear_round_posts_for_thread("thread-1")`. Assert `has_posted_in_round("agent-a", "thread-1") is False` but `has_posted_in_round("agent-a", "thread-2") is True`.

### Test 11: `test_eviction_removes_stale_entries`

Record round posts for 3 agent+thread combinations. Manually set 2 of them to `time.time() - 200.0` (beyond 120s). Call `router._evict_stale_round_posts(max_age=120.0)`. Assert only 1 entry remains.

### Test 12: `test_cleanup_tracking_removes_pruned_threads`

Record round posts for agent-a in thread-1 AND thread-2. Call `router.cleanup_tracking({"thread-1"})`. Assert `has_posted_in_round("agent-a", "thread-1") is False` but `has_posted_in_round("agent-a", "thread-2") is True`.

---

## Verification

Run targeted tests:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf236_dispatch_dedup_gate.py -v
```

Run BF-198 tests to verify no regression (separate tracker, should be clean):
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf198_router_proactive_dedup.py -v
```

Run BF-234 tests to verify no regression:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf234_ward_room_dispatch_dedup.py -v
```

Run full suite:
```
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

Report test count at each step.

---

## Tracker Updates

### PROGRESS.md
Update BF-236 status from `Open` to `**Closed**`.

### docs/development/roadmap.md
Update BF-236 row with fix description:
```
| BF-236 | **Semantic duplicate dispatch — round-scoped post tracker.** `_route_to_agents()` had no check for "agent already posted in this conversational round." Back-to-back `route_event()` calls dispatched the same agent for the same thread with different intent IDs (invisible to BF-234). Using BF-198's `_responded_threads` would block Captain follow-ups for 10 min (wrong invariant). **Fix:** New `_posted_in_round` tracker on WardRoomRouter, keyed on `(agent_id, thread_id)`, cleared on Captain repost alongside `_round_participants`. Recorded by WardRoomPostPipeline after `create_post` (not at dispatch/delivery) — gate fires only after a real post, avoids false positives from non-posting agents. 120s eviction. Gate in Phase 1 after Layer 3 round-participation check, respects `is_direct_target` bypass. `cleanup_tracking()` extended to clear pruned threads. Partial coverage: catches duplicates when pipeline recording outpaces second `route_event()`; sub-second races covered by BF-234 (transport) and BF-197 (similarity). 13 new tests including multi-turn Captain follow-up regression guard and route_event wiring verification. | Medium | **Closed** |
```

### DECISIONS.md
Add entry:
```
**BF-236: Round-scoped post tracker is the correct invariant for dispatch-level semantic dedup — not BF-198's `_responded_threads`.** BF-198 tracks `(agent_id, thread_id)` with 600s eviction for proactive-loop dedup; reusing it as a dispatch gate would block agents from responding to Captain follow-ups for 10 minutes. BF-236 adds a separate `_posted_in_round` tracker (same key shape, different lifecycle): cleared on Captain repost alongside `_round_participants` so agents become eligible again when the Captain follows up. Recorded by WardRoomPostPipeline after `create_post` (not at delivery) — only real posts register, avoiding false positives from agents dispatched but filtered by BF-197 or LLM error. Coverage is partial (honest): catches duplicates when multi-second LLM handler latency means the first post is recorded before the second `route_event()` runs eligibility. Sub-second rapid-fire races fall through to BF-234 (transport-layer dedup on identical intent IDs) and BF-197 (content similarity guard). Ordering between post-event-fan-out and `record_round_post` is best-effort; race is bounded by Python's single-threaded asyncio scheduling and rarely matters in practice. Three defense-in-depth layers: BF-234 (transport) → BF-236 (dispatch, round-scoped) → BF-197 (content).
```
