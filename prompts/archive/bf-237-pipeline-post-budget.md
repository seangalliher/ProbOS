# BF-237: Single-Invocation Post Budget in Ward Room Pipeline

**Status:** Ready for builder  
**Priority:** High  
**Tracker:** PROGRESS.md, roadmap.md, DECISIONS.md  
**Issue:** (create after review)

---

## Problem

A single cognitive handler invocation can produce multiple `create_post` calls within one `process_and_post()` pipeline execution. Two distinct failure modes:

1. **Extractor ↔ extractor (the Atlas incident):** `_extract_and_execute_replies` in `proactive.py` has a `for match in pattern.finditer(text):` loop (line ~2792). If the LLM emits multiple `[REPLY]` blocks, each match fires `create_post` (line ~2868). Same applies to the game MOVE `for match in re.finditer(move_pattern, text):` loop (line ~2531). N `[REPLY]` or `[MOVE]` blocks → N posts.

2. **Extractor ↔ Step 7:** The action extractor at Step 3 fires `create_post` for `[REPLY]` blocks, then Step 7 fires another `create_post` for the cleaned text (line ~125 in `ward_room_pipeline.py`). This adds +1 to the N above.

The existing dedup layers don't cover this:
- **BF-197** (content similarity) — catches near-duplicate *text*, not duplicate *posts from the same invocation*
- **BF-234** (transport dedup) — catches duplicate *dispatches*, not multiple posts within one dispatch
- **BF-236** (round-scoped tracker) — records posts *after* `create_post` and checks at *dispatch* time, not within the pipeline

BF-237 adds a **pipeline-level invocation budget**: each call to `process_and_post()` gets exactly one `create_post`. The budget is checked *before* every `create_post` inside the extractor loops AND at Step 7. First post wins; subsequent posts are suppressed with a WARN log.

## Dedup Stack Context

After BF-237, the four-layer dedup stack is:
1. **BF-234** — Transport: `IntentBus._on_dispatch()` deduplicates redelivered JetStream messages by `intent.id`
2. **BF-236** — Dispatch: `_posted_in_round` tracker prevents same agent responding twice in a conversational round
3. **BF-237** — Pipeline: invocation-scoped post budget prevents N+1 posts within one `process_and_post()` call
4. **BF-197** — Content: similarity guard suppresses near-duplicate text across agents

---

## Implementation

### 1. Add `PostBudget` dataclass and pass through `process_and_post()`

**File:** `src/probos/ward_room_pipeline.py`

Add a small dataclass at module level (after imports):

```python
from dataclasses import dataclass

@dataclass
class PostBudget:
    """BF-237: Tracks whether a create_post has fired in the current pipeline invocation."""
    spent: bool = False
```

At the top of `process_and_post()` (around line 58), create the budget instance and pass it to the action extractor.

**Current code (around line 83–88):**
```python
        # Step 3: Action extraction (endorsements, replies, DMs, notebooks, recreation)
        if agent and self._proactive_loop:
            response_text, _actions = await self._proactive_loop.extract_and_execute_actions(
                agent, response_text,
            )
            response_text = response_text.strip()
```

**New code:**
```python
        # Step 3: Action extraction (endorsements, replies, DMs, notebooks, recreation)
        # BF-237: Budget tracks whether action extractor already posted.
        budget = PostBudget()
        if agent and self._proactive_loop:
            response_text, _actions = await self._proactive_loop.extract_and_execute_actions(
                agent, response_text,
                post_budget=budget,
            )
            response_text = response_text.strip()
```

### 2. Gate Step 7 on budget; show full final shape of lines ~117–149

**File:** `src/probos/ward_room_pipeline.py`

Replace the current Steps 6–10 block (around lines 117–149) with the following. Steps 8–10 are **unconditional** — they must NOT be inside the `else` block.

**Current code (around lines 117–149):**
```python
        # Step 6: Bracket marker stripping (BF-174)
        from probos.proactive import _strip_bracket_markers
        response_text = _strip_bracket_markers(response_text)
        if not response_text:
            return False

        # Step 7: Post to Ward Room
        parent_id = post_id if event_type == "ward_room_post_created" else None
        await self._ward_room.create_post(
            thread_id=thread_id,
            author_id=agent.id,
            body=response_text,
            parent_id=parent_id,
            author_callsign=agent_callsign or agent.agent_type,
        )

        # Step 8: Record response (BF-198 anti-double-posting)
        if self._router:
            self._router.record_agent_response(agent.id, thread_id)
            self._router.record_round_post(agent.id, thread_id)  # BF-236

        # Step 9: Skill exercise recording (AD-625)
        _rt = self._runtime
        if _rt and hasattr(_rt, 'skill_service') and _rt.skill_service:
            try:
                await _rt.skill_service.record_exercise(agent.id, "communication")
            except Exception:
                logger.debug("AD-654a: Skill exercise recording failed for %s", agent.id, exc_info=True)

        # Step 10: Cooldown update
        if self._router:
            self._router.update_cooldown(agent.id)
```

**New code:**
```python
        # Step 6: Bracket marker stripping (BF-174)
        from probos.proactive import _strip_bracket_markers
        response_text = _strip_bracket_markers(response_text)
        if not response_text:
            return False

        # Step 7: Post to Ward Room
        # BF-237: If action extractor already posted, suppress the main post.
        if budget.spent:
            logger.warning(
                "BF-237: Suppressing main post for %s — action extractor already posted in this invocation",
                agent.agent_type,
            )
            # BF-237: Emit telemetry event for observability
            if self._runtime and getattr(self._runtime, 'event_log', None):
                try:
                    await self._runtime.event_log.log(
                        category="pipeline",
                        event="pipeline_post_budget_exceeded",
                        agent_id=agent.id,
                        agent_type=agent.agent_type,
                        detail=f"thread_id={thread_id}",
                    )
                except Exception:
                    logger.debug("BF-237: telemetry log failed", exc_info=True)
        else:
            parent_id = post_id if event_type == "ward_room_post_created" else None
            await self._ward_room.create_post(
                thread_id=thread_id,
                author_id=agent.id,
                body=response_text,
                parent_id=parent_id,
                author_callsign=agent_callsign or agent.agent_type,
            )

        # Step 8: Record response (BF-198 anti-double-posting)
        # UNCONDITIONAL — runs whether or not Step 7 posted. If the extractor
        # already posted, BF-236's round tracker must still record it so the
        # agent is correctly marked as "has posted in this round."
        if self._router:
            self._router.record_agent_response(agent.id, thread_id)
            self._router.record_round_post(agent.id, thread_id)  # BF-236

        # Step 9: Skill exercise recording (AD-625)
        _rt = self._runtime
        if _rt and hasattr(_rt, 'skill_service') and _rt.skill_service:
            try:
                await _rt.skill_service.record_exercise(agent.id, "communication")
            except Exception:
                logger.debug("AD-654a: Skill exercise recording failed for %s", agent.id, exc_info=True)

        # Step 10: Cooldown update
        if self._router:
            self._router.update_cooldown(agent.id)
```

### 3. Thread `post_budget` through `extract_and_execute_actions` → extractors, with in-loop budget check

**File:** `src/probos/proactive.py`

First, add the import at the top of the file (after existing imports):

```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from probos.ward_room_pipeline import PostBudget
```

#### 3a. Update public wrapper signature

**Current code (around line 1858):**
```python
    async def extract_and_execute_actions(
        self, agent: Any, text: str,
    ) -> tuple[str, list[dict]]:
        """Public wrapper for _extract_and_execute_actions (AD-654a)."""
        return await self._extract_and_execute_actions(agent, text)
```

**New code:**
```python
    async def extract_and_execute_actions(
        self, agent: Any, text: str,
        *,
        post_budget: PostBudget | None = None,
    ) -> tuple[str, list[dict]]:
        """Public wrapper for _extract_and_execute_actions (AD-654a)."""
        return await self._extract_and_execute_actions(agent, text, post_budget=post_budget)
```

#### 3b. Update `_extract_and_execute_actions` signature and pass-through

**Current code (around line 1997):**
```python
    async def _extract_and_execute_actions(
        self, agent: Any, text: str,
    ) -> tuple[str, list[dict]]:
```

**New code:**
```python
    async def _extract_and_execute_actions(
        self, agent: Any, text: str,
        *,
        post_budget: PostBudget | None = None,
    ) -> tuple[str, list[dict]]:
```

Pass `post_budget` to `_extract_and_execute_replies` (around line 2048):

**Current code:**
```python
            text, reply_actions = await self._extract_and_execute_replies(
                agent, text
            )
```

**New code:**
```python
            text, reply_actions = await self._extract_and_execute_replies(
                agent, text, post_budget=post_budget,
            )
```

#### 3c. Update `_extract_and_execute_replies` — budget check BEFORE `create_post` in the loop

**File:** `src/probos/proactive.py`

This is the critical fix. The `for match in pattern.finditer(text):` loop (line ~2792) iterates over all `[REPLY]` blocks and calls `create_post` for each. The budget check must go **inside the loop**, **before** `create_post`, **after** all existing guards (similarity, cooldown, post cap, bracket strip).

**Update the function signature:**

**Current signature:**
```python
    async def _extract_and_execute_replies(
        self, agent: Any, text: str,
    ) -> tuple[str, list[dict]]:
```

**New signature:**
```python
    async def _extract_and_execute_replies(
        self, agent: Any, text: str,
        *,
        post_budget: PostBudget | None = None,
    ) -> tuple[str, list[dict]]:
```

**Insert budget check before `create_post` (around line 2864–2868).** Find the block after bracket stripping and before `create_post`:

**Current code (around line 2864–2892):**
```python
                reply_body = _strip_bracket_markers(reply_body)  # BF-174
                if not reply_body:
                    continue

                await rt.ward_room.create_post(
                    thread_id=thread_id,
                    author_id=agent.id,
                    body=reply_body,
                    author_callsign=callsign or agent.agent_type,
                )
                # BF-198: Record reply so router won't double-respond
                if rt.ward_room_router:
                    rt.ward_room_router.record_agent_response(agent.id, thread_id)
                # AD-638: Track post for boot camp graduation
                if hasattr(rt, 'boot_camp') and rt.boot_camp and rt.boot_camp.is_enrolled(agent.id):
                    try:
                        _ch_type = ""
                        if channel_id:
                            try:
                                _ch_obj = await rt.ward_room.get_channel(channel_id)
                                _ch_type = getattr(_ch_obj, 'channel_type', '')
                            except Exception:
                                pass
                        await rt.boot_camp.on_agent_post(agent.id, _ch_type)
                    except Exception:
                        logger.debug("AD-638: Boot camp post tracking failed", exc_info=True)
                # BF-171: Record reply timestamp for channel cooldown
                if channel_id:
                    self._reply_cooldowns[f"{agent.id}:{channel_id}"] = time.monotonic()
```

**New code:**
```python
                reply_body = _strip_bracket_markers(reply_body)  # BF-174
                if not reply_body:
                    continue

                # BF-237: Enforce single-post budget per pipeline invocation.
                # Check BEFORE create_post so the second [REPLY] match in
                # a multi-REPLY LLM response is suppressed, not posted.
                if post_budget is not None and post_budget.spent:
                    logger.warning(
                        "BF-237: Suppressing additional [REPLY] from %s — post budget spent",
                        agent.agent_type,
                    )
                    continue

                await rt.ward_room.create_post(
                    thread_id=thread_id,
                    author_id=agent.id,
                    body=reply_body,
                    author_callsign=callsign or agent.agent_type,
                )
                # BF-237: Mark budget as spent after successful post
                if post_budget is not None:
                    post_budget.spent = True
                # BF-198: Record reply so router won't double-respond
                if rt.ward_room_router:
                    rt.ward_room_router.record_agent_response(agent.id, thread_id)
                # AD-638: Track post for boot camp graduation
                if hasattr(rt, 'boot_camp') and rt.boot_camp and rt.boot_camp.is_enrolled(agent.id):
                    try:
                        _ch_type = ""
                        if channel_id:
                            try:
                                _ch_obj = await rt.ward_room.get_channel(channel_id)
                                _ch_type = getattr(_ch_obj, 'channel_type', '')
                            except Exception:
                                pass
                        await rt.boot_camp.on_agent_post(agent.id, _ch_type)
                    except Exception:
                        logger.debug("AD-638: Boot camp post tracking failed", exc_info=True)
                # BF-171: Record reply timestamp for channel cooldown
                if channel_id:
                    self._reply_cooldowns[f"{agent.id}:{channel_id}"] = time.monotonic()
```

#### 3d. Budget check BEFORE game MOVE `create_post` in the loop

**File:** `src/probos/proactive.py`

The game MOVE handler in `_extract_and_execute_actions` (around line 2531) has `for match in re.finditer(move_pattern, text):`. The `create_post` at line ~2562 is inside this loop. Add the budget check before it.

**Current code (around line 2550–2569).** The `create_post` is inside a `if rt.ward_room and player_game.get("thread_id"):` block after game-over/in-progress branching sets `body`:

```python
                            if rt.ward_room and player_game.get("thread_id"):
                                board = rec_svc.render_board(player_game["game_id"]) if not game_info.get("result") else ""
                                result = game_info.get("result")
                                if result:
                                    status = result.get("status", "")
                                    winner = result.get("winner", "")
                                    body = f"Game over! {'Winner: ' + winner if winner else 'Draw!'}"
                                else:
                                    _next = game_info['state']['current_player']
                                    # BF-212: @mention next player so they receive the notification
                                    body = f"```\n{board}\n```\nYour move, @{_next}"
                                try:
                                    await rt.ward_room.create_post(
                                        thread_id=player_game["thread_id"],
                                        author_id=agent.id,
                                        body=body,
                                        author_callsign=callsign,
                                    )
                                except Exception:
                                    logger.debug("AD-526a: Board update post failed", exc_info=True)
```

**New code:** Replace the `try: await rt.ward_room.create_post(...)` block (lines 2561–2569) with the budget-gated version. Keep all surrounding code intact:

```python
                                # BF-237: Enforce single-post budget
                                if post_budget is not None and post_budget.spent:
                                    logger.warning(
                                        "BF-237: Suppressing additional [MOVE] board post from %s — post budget spent",
                                        agent.agent_type,
                                    )
                                else:
                                    try:
                                        await rt.ward_room.create_post(
                                            thread_id=player_game["thread_id"],
                                            author_id=agent.id,
                                            body=body,
                                            author_callsign=callsign,
                                        )
                                        # BF-237: Mark budget as spent
                                        if post_budget is not None:
                                            post_budget.spent = True
                                    except Exception:
                                        logger.debug("AD-526a: Board update post failed", exc_info=True)
```

---

## What This Does NOT Change

- **Action extractor parsing logic** — `[REPLY]` regex patterns, match loop, strip behavior: unchanged. The loop still iterates all matches (for side effects like command extraction), but only the first fires `create_post`.
- **BF-236 round-post tracker** — Records and checks remain as-is. BF-237 operates *inside* the pipeline, BF-236 operates *between* dispatches.
- **BF-234 transport dedup** — JetStream intent dedup: unchanged.
- **BF-197 content similarity** — Similarity guard: unchanged.
- **Proactive observation path (→ BF-238)** — `proactive.py` line ~693 calls `_extract_and_execute_actions` then `_post_to_ward_room` at line ~721. This is a separate code path from `process_and_post()` with the same N+1 potential AND no `record_round_post()` equivalent for extractor-only posts (so BF-236's round tracker is blind to extractor posts on this path). Not in scope for BF-237. **Open BF-238 to track this gap.**
- **DM extraction** — DMs use a separate send path, not `create_post` on the ward room. Not affected.
- **Endorsement extraction** — Endorsements don't create posts. Not affected.
- **`_extract_commands_from_reply` within `_extract_and_execute_replies`** — Game commands inside `[REPLY]` blocks are extracted by `_extract_commands_from_reply` (line ~2861), which modifies `reply_body` before the `create_post` at line ~2868. These go through the same budget-checked `create_post`, so they're covered.

---

## Existing Test Impact

Search for tests referencing `process_and_post`, `extract_and_execute_actions`, `_extract_and_execute_replies`:

- `tests/test_bf234_ward_room_dispatch_dedup.py` — Tests transport dedup. No changes needed.
- `tests/test_bf236_dispatch_dedup_gate.py` — Tests round-post tracker. No changes needed.
- `tests/test_ad437_action_space.py` — Calls `_extract_and_execute_actions` and `_extract_and_execute_replies`. No changes needed (new `post_budget` kwarg defaults to `None`).
- `tests/test_ad550_notebook_dedup.py` — Calls `_extract_and_execute_actions`. No changes needed.
- `tests/test_ad654a_async_dispatch.py` — Uses public `extract_and_execute_actions`. No changes needed.
- `tests/test_ad654d_internal_emitters.py` — Calls `_extract_and_execute_actions`. No changes needed.
- `tests/test_proactive.py` — Multiple calls. No changes needed.
- `tests/test_proactive_quality.py` — Multiple calls. No changes needed.
- `tests/test_bf201_thread_post_cap.py` — References action extraction. No changes needed.

Additionally, the proactive observation path at `proactive.py` line ~693 calls `_extract_and_execute_actions(agent, response_text)` positionally — safe because `post_budget` defaults to `None`. This path is out of scope (→ BF-238).

All callers use positional args only. The new `post_budget` keyword-only parameter defaults to `None`, so all existing tests remain backward-compatible. No assertion changes needed.

---

## New Tests

**File:** `tests/test_bf237_pipeline_post_budget.py`

Write tests under `pytest` + `pytest-asyncio`. Works under the project's `asyncio_mode = "auto"` configuration.

### Test 1: `test_main_post_suppressed_when_action_extractor_posts`
- Create a `WardRoomPostPipeline` with a mock `_proactive_loop` whose `extract_and_execute_actions` sets `budget.spent = True` and returns cleaned text.
- Call `process_and_post()`.
- Assert `_ward_room.create_post` was **not** called from the pipeline (Step 7).
- Assert the WARN log was emitted containing "BF-237".

### Test 2: `test_main_post_proceeds_when_no_action_post`
- Create a pipeline with a mock `_proactive_loop` that does NOT set `budget.spent` (leaves it `False`).
- Call `process_and_post()`.
- Assert `_ward_room.create_post` **was** called exactly once.

### Test 3: `test_round_post_recorded_even_when_main_post_suppressed`
- BF-236 regression test. When `budget.spent` is True (main post suppressed):
  - Assert `record_round_post()` was called exactly once.
  - Assert `_ward_room.create_post` was called exactly once (by the extractor mock, not by Step 7).
  - Assert `record_agent_response()` was called.
- This ensures Steps 8-10 are unconditional.

### Test 4: `test_post_budget_threaded_to_reply_extractor`
- Mock `_extract_and_execute_replies` to capture the `post_budget` arg.
- Call `extract_and_execute_actions` with `post_budget=PostBudget()`.
- Assert the budget instance was passed through to `_extract_and_execute_replies`.

### Test 5: `test_multi_reply_blocks_collapse_to_one_post`
- **This is the Atlas regression test.** Create a `ProactiveLoop` with mocked runtime (ward_room, ward_room_router).
- Provide text with **two** `[REPLY thread_id]` blocks:
  ```
  [REPLY abc123]First reply[/REPLY]
  [REPLY abc123]Second reply[/REPLY]
  ```
- Call `_extract_and_execute_replies(agent, text, post_budget=PostBudget())`.
- Assert `create_post` was called **exactly once** (the first reply).
- Assert `post_budget.spent` is `True`.
- Assert the WARN log contains "BF-237" and "Suppressing additional [REPLY]".

### Test 6: `test_no_budget_mutation_when_no_replies`
- Call `_extract_and_execute_replies(agent, "plain text", post_budget=PostBudget())`.
- Assert `post_budget.spent` remains `False`.

### Test 7: `test_post_budget_none_does_not_crash`
- Call with `post_budget=None` (backward compatibility).
- Assert no error, normal behavior.

### Test 8: `test_telemetry_event_emitted_on_suppression`
- When main post is suppressed, assert `event_log.log` was called with `category="pipeline"`, `event="pipeline_post_budget_exceeded"`.

### Test 9: `test_multi_move_blocks_collapse_to_one_post`
- Provide text with **two** `[MOVE ...]` blocks, mocked game engine that returns valid game state for both.
- Call `_extract_and_execute_actions` with `post_budget=PostBudget()`.
- Assert `create_post` was called **exactly once**.
- Assert `post_budget.spent` is `True`.

### Test 10: `test_single_reply_sets_budget`
- Single `[REPLY thread_id]content[/REPLY]` block.
- Call `_extract_and_execute_replies(agent, text, post_budget=PostBudget())`.
- Assert `create_post` was called exactly once.
- Assert `post_budget.spent` is `True`.

**Test count: 10 new tests.**

---

## Engineering Principles Compliance

Verify all changes comply with the Engineering Principles in `docs/development/contributing.md`:

- **SOLID (S):** `PostBudget` has one responsibility — tracking invocation-scoped post count.
- **SOLID (O):** Budget check is additive; existing `create_post` logic unchanged.
- **SOLID (D):** `PostBudget` is a plain dataclass, no framework coupling.
- **Law of Demeter:** Budget is passed as a parameter, not reached through `self._runtime._pipeline._budget`.
- **Fail Fast:** Budget violations logged at WARN level with agent_type for diagnosis. Telemetry event emitted.
- **DRY:** Budget check pattern is consistent across all three `create_post` sites (reply loop, MOVE loop, Step 7).

---

## Verification

```bash
# Targeted tests
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf237_pipeline_post_budget.py -v

# Related dedup tests still pass
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf234_ward_room_dispatch_dedup.py tests/test_bf236_dispatch_dedup_gate.py -v

# Full suite
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracker Updates

### PROGRESS.md
Add after the BF-236 line:
```
BF-237 CLOSED. Pipeline-level post budget — single create_post per process_and_post() invocation. PostBudget dataclass tracks spent state. Budget checked before every create_post: inside [REPLY] finditer loop, inside [MOVE] finditer loop, and at Step 7. First post wins, subsequent suppressed with WARN log + telemetry. Fixes Atlas multi-[REPLY] double-post. Defense-in-depth layer 3 of 4 in dedup stack. 10 new tests.
```

Also add:
```
BF-238 OPEN. Proactive observation path (proactive.py ~line 693) has no post budget and no record_round_post() for extractor-only posts. Same N+1 potential as BF-237 but on a different code path. Track separately.
```

Update BF-236 line status from `OPEN` to `CLOSED` if not already done.

### docs/development/roadmap.md
Add rows to Bug Tracker table:
```
| BF-237 | Pipeline post budget — multi-[REPLY]/[MOVE] + Step 7 = N+1 suppressed | High | **Closed** |
| BF-238 | Proactive observation path missing post budget + round tracker | Medium | Open |
```

### DECISIONS.md
Add entry:
```
## BF-237: Pipeline Post Budget (Single-Invocation Guard)

**Date:** 2026-04-25
**Status:** Accepted

The `process_and_post()` pipeline now enforces a budget of one `create_post` per invocation via a `PostBudget` dataclass. The budget is checked *before* every `create_post` call — inside the `_extract_and_execute_replies` finditer loop, inside the game MOVE finditer loop, and at Step 7. The first successful `create_post` marks `budget.spent = True`; subsequent attempts in the same invocation are suppressed with a WARN log and telemetry event. This means multiple `[REPLY]` or `[MOVE]` blocks in a single LLM response collapse to one post.

This is layer 3 in the four-layer dedup stack: BF-234 (transport) → BF-236 (dispatch round) → **BF-237 (pipeline invocation)** → BF-197 (content similarity).

**Alternatives considered:**
- Mutable `list[bool]` flag threaded through functions — rejected: anti-pattern, obscures data flow, impossible to type precisely. `PostBudget` dataclass is self-documenting and impossible to misuse.
- Counting posts in `WardRoomService.create_post()` itself — rejected: mixes transport concern with pipeline concern; `create_post` shouldn't need to know about invocation context.
- Setting flag after `create_post` without checking it in the loop — rejected: doesn't fix the multi-`[REPLY]` production failure mode (the actual Atlas incident). The check must be *before* `create_post` inside the loop.
```
