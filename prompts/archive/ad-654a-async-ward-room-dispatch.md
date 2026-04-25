# AD-654a: Async Ward Room Dispatch — JetStream Publish, Not Request/Reply

**Priority:** IMMEDIATE — fixes live NATS send timeout bug  
**Depends:** AD-637a-z (NATS foundation) ✅  
**GitHub:** seangalliher/ProbOS#323  
**Plan:** `cheerful-tinkering-pudding.md` (AD-654 decomposition)

## Problem

Ward Room Router dispatches `ward_room_notification` intents via `IntentBus.send()` which uses NATS `request()` (synchronous request/reply). Captain messages dispatch in parallel via `asyncio.gather()` (TTL 120s per BF-221 lift), non-Captain messages dispatch sequentially (TTL 30s). Each agent runs a 15-30s cognitive chain. While processing, new notifications timeout because the NATS handler is blocked. The result: silent message loss with only a log warning.

**Root cause:** `ward_room_notification` is semantically fire-and-forget (the router posts the agent's response text on the agent's behalf), but is implemented as synchronous request/reply. The TTL values (120s Captain, 30s non-Captain) merely delay the timeout — the fundamental architecture is wrong.

**Fix:** Publish notifications to JetStream. Agents consume via durable consumers. Agents post their own responses. Router's job ends at dispatch.

## Architecture Change

**Before:** Router → `send()` → NATS `request()` → Agent → `IntentResult` → Router posts response  
**After:** Router → `dispatch_async()` → JetStream `js_publish()` → Durable Consumer → Agent → Agent posts own response via `WardRoomPostPipeline`

## Engineering Principles Compliance

- **SOLID/S:** WardRoomPostPipeline has one responsibility (post-processing + posting). Router has one responsibility (dispatch). Agent has one responsibility (cognition + self-posting).
- **SOLID/O:** IntentBus extended with `dispatch_async()`. Existing `send()` preserved for synchronous callers.
- **SOLID/D:** WardRoomPostPipeline depends on injected services (ward_room, trust_network, etc.), not concrete runtime.
- **Law of Demeter:** Agent posts its own response via pipeline, not through the router reaching into IntentResult.
- **DRY:** One WardRoomPostPipeline for both router-path and proactive-path post-processing.
- **Fail Fast:** JetStream publish failure → fallback to `create_task(handler(intent))` with log warning. Never silently drop.
- **Cloud-Ready:** JetStream streams are the persistence layer — translates directly to NATS cluster.

---

## Section 1: New JetStream Stream — INTENT_DISPATCH

**File:** `src/probos/startup/nats.py`

Add a third JetStream stream after the existing WARDROOM stream (line 65):

```python
await bus.ensure_stream(
    "INTENT_DISPATCH",
    ["intent.dispatch.>"],
    max_msgs=10000,   # Ward room notifications are ephemeral — 10k is generous
    max_age=300,      # 5 min retention — stale notifications are worthless
)
```

Update the log message at line 66 to include the new stream:

```python
logger.info("Startup [nats]: JetStream streams ensured (SYSTEM_EVENTS, WARDROOM, INTENT_DISPATCH)")
```

**Signature reference:** `NATSBus.ensure_stream(name: str, subjects: list[str], max_msgs: int = -1, max_age: float = 0)` at `nats_bus.py:479`.

---

## Section 2: IntentBus.dispatch_async() Method

**File:** `src/probos/mesh/intent.py`

### 2a: Add `dispatch_async()` method

Add after the existing `publish()` method (after line 282). This is a NEW method — do NOT modify the existing `publish()` (which is an alias for `broadcast()` used by `runtime.py:776`).

```python
async def dispatch_async(self, intent: IntentMessage) -> None:
    """Fire-and-forget dispatch to a specific agent via JetStream (AD-654a).

    Publishes the intent to the agent's durable JetStream consumer.
    No reply expected — the agent processes asynchronously and posts
    its own response. Falls back to direct async handler invocation
    when NATS/JetStream is unavailable.

    Requires intent.target_agent_id to be set.
    """
    if not intent.target_agent_id:
        raise ValueError("dispatch_async() requires target_agent_id")

    # JetStream path when connected
    if self._nats_bus and self._nats_bus.connected:
        subject = f"intent.dispatch.{intent.target_agent_id}"
        try:
            await self._nats_bus.js_publish(subject, self._serialize_intent(intent))
            logger.debug(
                "AD-654a: Dispatched %s → %s via JetStream",
                intent.intent, intent.target_agent_id[:12],
            )
            return
        except Exception as e:
            logger.warning(
                "AD-654a: JetStream dispatch failed for %s → %s: %s, falling back to direct",
                intent.intent, intent.target_agent_id[:12], e,
            )
            # Fall through to direct dispatch

    # Direct-call fallback when NATS/JetStream unavailable
    handler = self._subscribers.get(intent.target_agent_id)
    if handler is None:
        logger.debug("AD-654a: No handler for %s, dropping", intent.target_agent_id[:12])
        return

    # Soft cap on pending fallback tasks to prevent unbounded growth
    # during sustained NATS outage (e.g., 14 agents × rapid ward room posts)
    _MAX_PENDING_TASKS = 200
    if len(self._pending_sub_tasks) >= _MAX_PENDING_TASKS:
        logger.warning(
            "AD-654a: Pending task cap (%d) reached, dropping dispatch for %s",
            _MAX_PENDING_TASKS, intent.target_agent_id[:12],
        )
        return

    async def _run_handler() -> None:
        try:
            await handler(intent)
        except Exception:
            logger.warning(
                "AD-654a: Direct handler failed for %s",
                intent.target_agent_id[:12],
                exc_info=True,
            )

    task = asyncio.get_running_loop().create_task(
        _run_handler(),
        name=f"dispatch-async-{intent.target_agent_id[:12]}",
    )
    self._pending_sub_tasks.add(task)
    task.add_done_callback(self._pending_sub_tasks.discard)
```

**Key design notes:**
- Uses `js_publish()` (at-least-once via JetStream), NOT `publish()` (core NATS fire-and-forget).
- Subject pattern: `intent.dispatch.{agent_id}` — each agent gets its own subject within the INTENT_DISPATCH stream.
- Fallback wraps handler in `create_task` (non-blocking) — the caller does NOT await the result.
- Tracks fallback tasks in `_pending_sub_tasks` for clean shutdown (AD-637z pattern).

### 2b: NATSMessage.term() and js_subscribe manual_ack support

Before creating the dispatch consumer, two prerequisite changes are needed:

**File:** `src/probos/mesh/nats_bus.py`

**2b-i: Add `term()` to NATSMessage** (after `nak()` at line 54):

```python
    async def term(self) -> None:
        """Terminate JetStream message — permanently reject, no redelivery."""
        if self._msg and hasattr(self._msg, "term"):
            await self._msg.term()
```

**2b-ii: Add `manual_ack` parameter to `js_subscribe()`**

The `js_subscribe()` handler wrapper (lines 418-441) always calls `msg.ack()` on success and `msg.nak()` on error. AD-654a's dispatch consumer needs `msg.term()` on error (cognitive chains must NOT retry). Add a `manual_ack: bool = False` parameter that suppresses the wrapper's ack/nak, letting the callback handle ack semantics itself.

Add `manual_ack: bool = False` to the `js_subscribe()` signature (line 402-410). Then modify the `_handler` wrapper:

```python
        async def _handler(msg: Any) -> None:
            try:
                raw_data = json.loads(msg.data) if msg.data else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.debug("JetStream: invalid JSON on %s", msg.subject)
                if not manual_ack:
                    await msg.nak()
                return
            wrapped = NATSMessage(
                subject=msg.subject,
                data=raw_data,
                reply=msg.reply or "",
                headers=dict(msg.headers) if msg.headers else {},
                _msg=msg,
            )
            try:
                await callback(wrapped)
                if not manual_ack:
                    await msg.ack()
            except Exception:
                logger.error(
                    "JetStream subscriber error on %s",
                    msg.subject,
                    exc_info=True,
                )
                if not manual_ack:
                    await msg.nak()
```

When `manual_ack=True`, the wrapper still does JSON parsing and NATSMessage wrapping, but the callback receives the NATSMessage and is responsible for calling `msg.ack()`, `msg.nak()`, or `msg.term()` itself.

### 2c: Per-agent JetStream consumer subscription

Add a new method after `_nats_subscribe_agent()` (after line 99):

```python
async def _js_subscribe_agent_dispatch(self, agent_id: str, handler: IntentHandler) -> None:
    """Subscribe agent to their JetStream dispatch subject (AD-654a).

    Creates a durable consumer on intent.dispatch.{agent_id} within
    the INTENT_DISPATCH stream. Messages queue while agent is busy
    and are processed sequentially (max_ack_pending=1).

    Uses manual_ack=True because cognitive chains need msg.term() on
    error (not msg.nak()) — LLM calls that already ran must not retry.
    """
    subject = f"intent.dispatch.{agent_id}"

    async def _on_dispatch(msg: "NATSMessage") -> None:
        """JetStream dispatch callback — deserialize and handle.

        Uses manual ack: ack() on success, term() on error.
        The js_subscribe wrapper does NOT handle ack/nak when
        manual_ack=True — we must do it ourselves.
        """
        try:
            intent = self._deserialize_intent(msg.data)
            # AD-654a/BF-198: Record response BEFORE handler runs to close
            # the proactive-loop race window. The proactive loop checks
            # has_agent_responded() — recording early prevents double-posting
            # during the 15-60s handler execution window.
            _rt_ref = getattr(handler, "__self__", None)
            if _rt_ref and hasattr(_rt_ref, "_runtime"):
                _rt = _rt_ref._runtime
                _router = getattr(_rt, "ward_room_router", None)
                _thread_id = intent.params.get("thread_id", "")
                if _router and _thread_id:
                    _router.record_agent_response(intent.target_agent_id, _thread_id)
            await handler(intent)
            await msg.ack()
        except Exception as e:
            logger.warning(
                "AD-654a: Dispatch handler error for %s: %s",
                agent_id[:8], e,
            )
            # term() = permanently reject. Do NOT nak() — cognitive chains
            # must not be retried (LLM already ran, would cause duplicates).
            await msg.term()

    # Durable name must be NATS-safe (alphanumeric + dash).
    # Use FULL agent_id (32 hex chars from uuid4) — [:12] risks collisions.
    # NATS durable name limit is 256 chars; "agent-dispatch-" + 32 = 48, well under.
    durable_name = f"agent-dispatch-{agent_id}"

    sub = await self._nats_bus.js_subscribe(
        subject,
        _on_dispatch,
        durable=durable_name,
        stream="INTENT_DISPATCH",
        max_ack_pending=1,    # Sequential processing — one at a time
        ack_wait=300,         # 5 min — must exceed LLM timeout (BF-220 pattern)
        manual_ack=True,      # AD-654a: We handle ack/term, not the wrapper
    )
    if sub:
        logger.debug("AD-654a: JetStream dispatch consumer for %s", agent_id[:12])
```

**Key design notes:**
- `max_ack_pending=1` — messages queue; only one processed at a time per agent. This is the Actor Model mailbox.
- `ack_wait=300` — matches BF-220 pattern from finalize.py:177. Must exceed maximum LLM call time to prevent redelivery.
- `manual_ack=True` — the `js_subscribe()` wrapper still does JSON parsing and NATSMessage wrapping, but skips automatic ack/nak. The callback receives a `NATSMessage` and calls `msg.ack()` on success or `msg.term()` on error.
- Using `msg.term()` (not `msg.nak()`) on error — cognitive chains that already ran the LLM must NOT be retried (would cause duplicate posts).
- BF-198 early recording: `record_agent_response()` is called BEFORE the handler runs to close the race window between async dispatch and proactive loop double-posting.
- Durable name uses full agent_id (32 hex chars) — no truncation, no collision risk.
- The callback's `_deserialize_intent(msg.data)` works because `msg.data` is already a parsed `dict` (the `js_subscribe` wrapper handles JSON parsing).

### 2d: Wire dispatch consumer in `subscribe()`

Modify the `subscribe()` method (lines 44-70) to also create the JetStream dispatch consumer when NATS is connected:

At line 60, inside the `if self._nats_bus and self._nats_bus.connected:` block, after the existing `_nats_subscribe_agent` task creation (line 63), add:

```python
            # AD-654a: Also subscribe to JetStream dispatch subject
            dispatch_task = loop.create_task(
                self._js_subscribe_agent_dispatch(agent_id, handler),
                name=f"js-dispatch-sub-{agent_id[:12]}",
            )
            self._pending_sub_tasks.add(dispatch_task)
            dispatch_task.add_done_callback(self._pending_sub_tasks.discard)
            dispatch_task.add_done_callback(self._on_nats_task_done)
```

---

## Section 3: WardRoomPostPipeline

**File:** `src/probos/ward_room_pipeline.py` (NEW file)

This class extracts the post-processing pipeline currently duplicated between `ward_room_router.py:559-636` (Phase 3) and `proactive.py:2015-2523` (`_extract_and_execute_actions()`). It provides a single pipeline that:
1. Sanitizes text (BF-199)
2. Extracts and executes actions (endorsements, replies, DMs, notebooks, recreation commands)
3. Checks similarity guard (BF-197)
4. Strips bracket markers (BF-174)
5. Posts to ward room via `create_post()`
6. Records response tracking (BF-198)
7. Records skill exercise (AD-625)
8. Updates cooldown

### Constructor

```python
"""Ward Room post-processing pipeline (AD-654a).

DRY extraction of post-processing logic shared by:
- Agent self-posting path (AD-654a async dispatch)
- Proactive loop observation posting
- Ward Room Router response path (legacy/fallback)
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from probos.ward_room.service import WardRoomService

logger = logging.getLogger(__name__)


class WardRoomPostPipeline:
    """Process and post an agent's Ward Room response.

    Applies the full post-processing chain: text sanitization (BF-199),
    action extraction (endorsements, replies, DMs, notebooks, recreation),
    similarity guard (BF-197), bracket marker stripping (BF-174),
    and ward room posting.  Records response tracking (BF-198),
    skill exercise (AD-625), and cooldown.
    """

    def __init__(
        self,
        *,
        ward_room: "WardRoomService",
        ward_room_router: Any,  # WardRoomRouter — for record_agent_response, cooldowns, endorsements
        proactive_loop: Any | None,  # ProactiveCognitiveLoop — for _extract_and_execute_actions, similarity
        trust_network: Any | None,
        callsign_registry: Any | None,
        config: Any,
        runtime: Any | None = None,  # For skill_service access
    ) -> None:
        self._ward_room = ward_room
        self._router = ward_room_router
        self._proactive_loop = proactive_loop
        self._trust_network = trust_network
        self._callsign_registry = callsign_registry
        self._config = config
        self._runtime = runtime
```

### Core Method: `process_and_post()`

```python
    async def process_and_post(
        self,
        *,
        agent: Any,
        response_text: str,
        thread_id: str,
        event_type: str,
        post_id: str | None = None,
    ) -> bool:
        """Process agent response text and post to ward room.

        Applies the full post-processing pipeline. Returns True if a post
        was created, False if the response was suppressed (empty, similar,
        or filtered).

        Args:
            agent: Agent object (needs .id, .agent_type attributes)
            response_text: Raw LLM response text
            thread_id: Ward Room thread to post to
            event_type: Original event type ("ward_room_thread_created" or "ward_room_post_created")
            post_id: Parent post ID (for replies to posts, not thread creation)
        """
        # Step 1: Text sanitization (BF-199)
        from probos.utils.text_sanitize import sanitize_ward_room_text
        response_text = sanitize_ward_room_text(response_text)
        if not response_text or response_text == "[NO_RESPONSE]":
            return False

        # Step 2: Resolve callsign
        agent_callsign = ""
        if self._callsign_registry:
            agent_callsign = self._callsign_registry.get_callsign(agent.agent_type)

        # Step 3: Action extraction (endorsements, replies, DMs, notebooks, recreation)
        if agent and self._proactive_loop:
            response_text, _actions = await self._proactive_loop.extract_and_execute_actions(
                agent, response_text,
            )
            response_text = response_text.strip()
        elif self._router:
            # Fallback: endorsements only
            response_text, endorsements = self._router.extract_endorsements(response_text)
            if endorsements:
                await self._router.process_endorsements(endorsements, agent_id=agent.id)

        if not response_text:
            return False

        # Step 4: Similarity guard (BF-197)
        if agent and self._proactive_loop:
            if await self._proactive_loop.is_similar_to_recent_posts(
                agent, response_text,
            ):
                logger.debug(
                    "AD-654a/BF-197: Suppressed similar response from %s",
                    agent.agent_type,
                )
                return False

        # Step 5: Recreation commands (BF-123)
        if agent and self._router:
            response_text = await self._router.extract_recreation_commands(
                agent, response_text, agent_callsign,
            )
        if not response_text:
            return False

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

        return True
```

**Design note on `extract_recreation_commands`:** This method currently lives on `WardRoomRouter` as `_extract_recreation_commands()` (lines 638-768). AD-654a promotes it to a public method `extract_recreation_commands()`. This is acceptable because the pipeline is a first-class consumer. Moving it to the pipeline would require moving recreation service access patterns — better done in AD-654d when recreation becomes a TaskEvent emitter.

**Law of Demeter compliance (Issue #6):** The pipeline must NOT reach into private methods or data structures of other objects. The following private methods/attributes must be promoted to public wrappers:

1. **`ProactiveCognitiveLoop`:**
   - `_extract_and_execute_actions()` → add public `extract_and_execute_actions()` wrapper (delegates to private)
   - `_is_similar_to_recent_posts()` → add public `is_similar_to_recent_posts()` wrapper (delegates to private)

2. **`WardRoomRouter`:**
   - `_extract_recreation_commands()` → add public `extract_recreation_commands()` wrapper (delegates to private)
   - `_cooldowns[agent_id] = time.time()` → add public `update_cooldown(agent_id: str)` method

The private methods themselves are NOT renamed — only thin public wrappers are added. The wrappers are one-liners that delegate to the existing private implementations. Existing internal callers continue calling the private methods.

---

## Section 4: Agent Self-Posting for ward_room_notification

**File:** `src/probos/cognitive/cognitive_agent.py`

### 4a: Add ward room self-posting after handle_intent

The agent needs to post its own response after handling `ward_room_notification`. Modify `handle_intent()` to call the WardRoomPostPipeline after the cognitive chain completes.

Find the `handle_intent()` method (line 2168). After the call to `act()` (line 2380) and `report()` (line 2381), and before the IntentResult is constructed (line 2577), add a self-posting block.

Locate the section where the IntentResult is built (around line 2570-2580). Add the following BEFORE the `return IntentResult(...)`:

```python
        # AD-654a: Agent self-posting for ward_room_notification
        if intent.intent == "ward_room_notification" and success and report.get("result"):
            await self._self_post_ward_room_response(intent, str(report["result"]))
```

### 4b: Add `_self_post_ward_room_response()` method

Add this new method to CognitiveAgent (place it near the existing `act()` method, around line 2165):

```python
    async def _self_post_ward_room_response(
        self, intent: "IntentMessage", response_text: str,
    ) -> None:
        """AD-654a: Post own response to ward room after handling notification.

        When activated via JetStream dispatch (AD-654a), the agent is
        responsible for posting its own response — the router no longer
        collects IntentResults and posts on agents' behalf.
        """
        _rt = getattr(self, "_runtime", None)
        if not _rt or not getattr(_rt, "ward_room", None):
            return

        thread_id = intent.params.get("thread_id", "")
        if not thread_id:
            return

        # Use runtime-stored pipeline (created in _apply_finalization)
        pipeline = getattr(_rt, "ward_room_post_pipeline", None)
        if not pipeline:
            logger.debug("AD-654a: No ward_room_post_pipeline on runtime, skipping self-post")
            return

        try:
            await pipeline.process_and_post(
                agent=self,
                response_text=response_text,
                thread_id=thread_id,
                event_type=intent.params.get("event_type", ""),
                post_id=intent.params.get("post_id"),
            )
        except Exception:
            logger.warning(
                "AD-654a: Self-post failed for %s in thread %s",
                self.id[:12], thread_id[:12],
                exc_info=True,
            )
```

**Key design notes:**
- Uses `runtime.ward_room_post_pipeline` (created in `_apply_finalization()` after all dependencies are wired). No per-call construction, no lazy imports.
- `intent.params` already carries `thread_id`, `event_type`, and `post_id` (set in `ward_room_router.py:505-523`). No new data flow needed.
- Fails silently with warning — the agent has already done its cognitive work; a posting failure shouldn't crash the handler.

### 4c: Guard against double-posting

The agent now self-posts AND the router (if processing the fallback/direct path) might still try to post. Two guards:

1. **Router-side:** In the next section, the router's Phase 3 is removed for `ward_room_notification` intents dispatched via `dispatch_async()`. For the direct-call fallback path, the handler still returns an IntentResult. But the router no longer collects results — it discards them.

2. **Agent-side:** The `_self_post_ward_room_response()` method uses the pipeline's BF-198 `record_agent_response()` call. The proactive loop checks `has_agent_responded()` before attempting its own post, preventing triple-posting.

---

## Section 5: Ward Room Router — Replace send() with dispatch_async()

**File:** `src/probos/ward_room_router.py`

### 5a: Replace Phase 2 dispatch (lines 529-554)

Replace the entire Phase 2 block (lines 529-554) with:

```python
        # ---------------------------------------------------------------
        # Phase 2: Dispatch — async fire-and-forget via JetStream (AD-654a)
        # ---------------------------------------------------------------
        # Agents receive notifications via durable JetStream consumers and
        # post their own responses via WardRoomPostPipeline. The router's
        # job ends at dispatch — no result collection needed.
        for agent_id, intent in eligible:
            await self._intent_bus.dispatch_async(intent)
```

**What this changes:**
- No more `asyncio.gather()` for Captain messages — JetStream handles fan-out natively.
- No more sequential `send()` for non-Captain — all dispatches are fire-and-forget.
- No more `dispatch_results` collection.

### 5b: Remove Phase 3 result processing (lines 556-636)

Delete the entire Phase 3 block (lines 556-636). This includes:
- Result iteration (`for agent_id, result in dispatch_results:`)
- Text sanitization (`sanitize_ward_room_text`)
- Action extraction (`_extract_and_execute_actions`)
- Similarity guard (`_is_similar_to_recent_posts`)
- Recreation commands (`_extract_recreation_commands`)
- Bracket marker stripping (`_strip_bracket_markers`)
- `ward_room.create_post()` call
- `record_agent_response()` call
- Skill exercise recording
- Cooldown update
- Round tracking

Replace with:

```python
        # ---------------------------------------------------------------
        # Phase 3: Removed (AD-654a)
        # ---------------------------------------------------------------
        # Agents now process responses and post via WardRoomPostPipeline.
        # Router dispatch is complete. Round tracking for agent-to-agent
        # loop prevention remains in route_event_coalesced eligibility checks.
```

**IMPORTANT:** Do NOT remove the round-tracking increment at line 635-636. This block (`if is_agent_post and responded_this_event:`) must be updated. Since the router no longer knows when agents respond (it dispatches fire-and-forget), agent-to-agent round tracking needs adjustment:

Replace the round tracking block (lines 634-636) with:

```python
        # AD-654a: Round tracking for agent-to-agent loop prevention.
        # In async dispatch, we don't know exactly when agents respond.
        # Increment the round counter on agent-authored events ONLY when
        # at least one agent was dispatched to (otherwise round counter
        # inflates on events where all agents are filtered out).
        if is_agent_post and eligible:
            self._thread_rounds[thread_id] = current_round + 1
```

### 5c: Remove `responded_this_event` variable

The `responded_this_event` variable is initialized earlier in the method and set during Phase 3. Find and remove:
- Its initialization (search for `responded_this_event = False`)
- Any reference to it after Phase 3 removal

### 5d: Preserve `_extract_recreation_commands()`

Do NOT move or remove the `_extract_recreation_commands()` method (lines 638-768). It is still called by `WardRoomPostPipeline.process_and_post()` via the public wrapper.

### 5e: Add public method wrappers (Law of Demeter, Issue #6)

Add thin public wrappers for the two methods the pipeline calls cross-module:

```python
    # AD-654a: Public wrappers for WardRoomPostPipeline access (Law of Demeter)
    async def extract_recreation_commands(
        self, agent: Any, text: str, agent_callsign: str,
    ) -> str:
        """Public wrapper for _extract_recreation_commands (AD-654a)."""
        return await self._extract_recreation_commands(agent, text, agent_callsign)

    def update_cooldown(self, agent_id: str) -> None:
        """Update agent cooldown timestamp (AD-654a)."""
        self._cooldowns[agent_id] = time.time()
```

Place these after the existing `record_agent_response()` method.

---

## Section 6: Proactive Loop — Delegate to WardRoomPostPipeline (DRY)

**File:** `src/probos/proactive.py`

### 6a: No structural changes to proactive.py in AD-654a

The proactive loop's `_post_to_ward_room()` method (line 1960) creates NEW threads (observation posts). This is a DIFFERENT path from ward_room_notification responses (replies to existing threads). No refactoring here.

### 6b: Add public method wrappers (Law of Demeter, Issue #6)

Add thin public wrappers for the two methods the pipeline calls cross-module. These are one-liner delegations — the private methods are NOT renamed.

```python
    # AD-654a: Public wrappers for WardRoomPostPipeline access (Law of Demeter)
    async def extract_and_execute_actions(
        self, agent: Any, text: str,
    ) -> tuple[str, list[dict]]:
        """Public wrapper for _extract_and_execute_actions (AD-654a)."""
        return await self._extract_and_execute_actions(agent, text)

    async def is_similar_to_recent_posts(
        self, agent: Any, text: str,
    ) -> bool:
        """Public wrapper for _is_similar_to_recent_posts (AD-654a)."""
        return await self._is_similar_to_recent_posts(agent, text)
```

Place these near the existing public methods, e.g., after `record_agent_response()` or at the end of the class.

`_extract_and_execute_actions()` stays on `ProactiveCognitiveLoop` and continues to be called by:
1. The proactive loop's own observation posting path (line 682)
2. `WardRoomPostPipeline.process_and_post()` via `self._proactive_loop.extract_and_execute_actions()`

The full DRY refactoring (moving `_extract_and_execute_actions` into the pipeline as a standalone class) is deferred to AD-654b when the cognitive queue replaces inline handler processing.

---

## Section 7: Runtime Wiring — WardRoomPostPipeline + Consumer Cleanup

### 7a: Store pipeline on runtime in `_apply_finalization()`

**File:** `src/probos/runtime.py`

The pipeline depends on `runtime.proactive_loop` and `runtime.ward_room_router`, which are set at runtime.py:1575-1576 — AFTER `finalize.py` returns. Therefore the pipeline CANNOT be created inside `finalize.py`. Create it in `_apply_finalization()`, after the proactive loop and router are stored.

Find `_apply_finalization()` in runtime.py. After the lines that set `self.proactive_loop` and `self.ward_room_router` (lines 1575-1576), add:

```python
        # AD-654a: Create WardRoomPostPipeline for agent self-posting
        from probos.ward_room_pipeline import WardRoomPostPipeline
        self.ward_room_post_pipeline = WardRoomPostPipeline(
            ward_room=self.ward_room,
            ward_room_router=self.ward_room_router,
            proactive_loop=self.proactive_loop,
            trust_network=self.trust_network,
            callsign_registry=self.callsign_registry,
            config=self.config,
            runtime=self,
        )
```

### 7b: Update agent self-post to use runtime pipeline

**File:** `src/probos/cognitive/cognitive_agent.py`

In `_self_post_ward_room_response()` (Section 4b), replace per-call pipeline construction with runtime lookup:

```python
        # Use runtime-stored pipeline (created in _apply_finalization)
        pipeline = getattr(_rt, "ward_room_post_pipeline", None)
        if not pipeline:
            logger.debug("AD-654a: No ward_room_post_pipeline on runtime, skipping self-post")
            return
```

Remove the inline `WardRoomPostPipeline(...)` constructor call from Section 4b. The revised `_self_post_ward_room_response()` becomes:

### 7c: JetStream consumer cleanup on unsubscribe

**File:** `src/probos/mesh/nats_bus.py`

`NATSBus` currently has no method to delete a JetStream durable consumer. Add one:

```python
    async def delete_consumer(self, stream: str, durable_name: str) -> None:
        """Delete a durable JetStream consumer (AD-654a cleanup)."""
        if not self._js:
            return
        try:
            await self._js.delete_consumer(stream, durable_name)
            logger.debug("NATSBus: Deleted consumer %s from stream %s", durable_name, stream)
        except Exception as e:
            logger.debug("NATSBus: Consumer delete failed (%s/%s): %s", stream, durable_name, e)
```

**File:** `src/probos/mesh/intent.py`

In `unsubscribe()` (line 101), after removing the core NATS subscription, also clean up the JetStream durable consumer:

```python
        # AD-654a: Clean up JetStream dispatch consumer
        if self._nats_bus:
            durable_name = f"agent-dispatch-{agent_id}"
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._nats_bus.delete_consumer("INTENT_DISPATCH", durable_name),
                    name=f"cleanup-dispatch-{agent_id[:12]}",
                )
            except RuntimeError:
                pass  # No running loop during shutdown
```

---

## Section 8: What This Does NOT Change

1. **`IntentBus.send()` is preserved.** All existing callers continue to use synchronous request/reply:
   - `channels/base.py:132` — direct_message from Discord/channels
   - `routers/chat.py:121` — direct_message from HXI
   - `routers/agents.py:188` — direct_message from API
   - `cognitive_agent.py:506` — compound_step_replay (step chaining)
   - `experience/commands/session.py:122` — direct_message from session

2. **`IntentBus.broadcast()` and existing `publish()` alias are preserved.** The one caller (`runtime.py:776`, `_dispatch_watch_intent`) continues to work.

3. **`_nats_subscribe_agent()` is preserved.** The core NATS subscription for `send()` request/reply still works alongside the new JetStream dispatch consumer.

4. **Proactive loop is structurally unchanged.** `_extract_and_execute_actions()` stays on ProactiveCognitiveLoop. Only addition: two thin public wrappers (`extract_and_execute_actions()`, `is_similar_to_recent_posts()`) for Law of Demeter compliance.

5. **Ward Room Router eligibility checks (Phase 1) are not modified.** Cooldown checks, round limits, mention filtering, department filtering, channel membership — all preserved.

6. **`_extract_recreation_commands()` stays on WardRoomRouter.** Pipeline calls it via the new public `extract_recreation_commands()` wrapper.

---

## Section 9: Tests

**File:** `tests/test_ad654a_async_dispatch.py` (NEW file)

Use existing test patterns from `test_ward_room_agents.py` and `test_ad637a_nats_foundation.py`.

### Required Tests (~27)

**IntentBus.dispatch_async():**
1. `test_dispatch_async_publishes_to_jetstream` — When NATS connected, `dispatch_async()` calls `nats_bus.js_publish()` with subject `intent.dispatch.{agent_id}`.
2. `test_dispatch_async_fallback_to_direct` — When NATS disconnected, `dispatch_async()` creates a task that calls the handler directly (non-blocking).
3. `test_dispatch_async_requires_target_agent_id` — Raises ValueError when `target_agent_id` is None.
4. `test_dispatch_async_jetstream_failure_falls_back` — When `js_publish()` raises, falls back to direct dispatch with warning.
5. `test_dispatch_async_pending_task_cap` — When `_pending_sub_tasks` exceeds 200, drops dispatch with warning.

**JetStream Consumer (ack semantics):**
6. `test_js_subscribe_agent_dispatch_creates_consumer` — `subscribe()` creates a durable JetStream consumer on `intent.dispatch.{agent_id}` with `max_ack_pending=1` and `manual_ack=True`.
7. `test_js_consumer_acks_on_success` — Callback calls `msg.ack()` after successful handler execution (not the wrapper).
8. `test_js_consumer_terms_on_error` — Callback calls `msg.term()` (NOT `msg.nak()`) when handler raises. Verifies no redelivery loop.
9. `test_js_consumer_processes_sequentially` — Consumer with `max_ack_pending=1` processes one intent at a time (simulated with slow handler).
10. `test_js_consumer_uses_full_agent_id` — Durable name is `agent-dispatch-{full_32_char_id}`, not truncated.
11. `test_js_consumer_records_response_before_handler` — BF-198: `record_agent_response()` called before `handler(intent)` runs.
12. `test_js_subscribe_manual_ack_skips_wrapper_ack` — When `manual_ack=True`, `js_subscribe` wrapper does NOT call `msg.ack()` or `msg.nak()` automatically.

**Consumer Cleanup:**
12. `test_unsubscribe_deletes_jetstream_consumer` — `unsubscribe()` calls `nats_bus.delete_consumer("INTENT_DISPATCH", durable_name)`.
13. `test_delete_consumer_handles_missing_gracefully` — `delete_consumer()` with nonexistent consumer doesn't raise.

**WardRoomPostPipeline:**
14. `test_pipeline_sanitizes_text` — BF-199: Chain JSON is sanitized before posting.
15. `test_pipeline_strips_bracket_markers` — BF-174: Self-monitoring markers removed.
16. `test_pipeline_similarity_guard` — BF-197: Near-duplicate text suppressed (returns False).
17. `test_pipeline_extracts_actions` — Endorsements, replies extracted via proactive loop's public wrapper.
18. `test_pipeline_posts_to_ward_room` — Calls `ward_room.create_post()` with correct args.
19. `test_pipeline_records_response` — BF-198: Calls `ward_room_router.record_agent_response()`.
20. `test_pipeline_records_skill_exercise` — AD-625: Records communication skill exercise.
21. `test_pipeline_no_response_text` — Returns False for `[NO_RESPONSE]` or empty text.

**Ward Room Router Dispatch:**
22. `test_router_dispatches_async_not_send` — Router calls `dispatch_async()` not `send()` for `ward_room_notification`.
23. `test_router_round_counter_only_bumps_with_eligible` — Round counter unchanged when `eligible` is empty.

**Agent Self-Posting:**
24. `test_agent_self_posts_after_ward_room_notification` — Agent calls `_self_post_ward_room_response()` after handling `ward_room_notification`.
25. `test_agent_self_post_uses_runtime_pipeline` — Agent uses `runtime.ward_room_post_pipeline`, not per-call construction.

**Integration:**
26. `test_end_to_end_async_dispatch` — Full flow: router dispatches → agent handler runs → agent self-posts → ward room has the post.

### Test Fixtures

Use `MockNATSBus` from `probos.mesh.nats_bus` for NATS mocking. Use `AsyncMock` for ward room service. Use mock runtime pattern from `test_ward_room_agents.py`.

---

## Section 10: Verification

```bash
# New tests
pytest tests/test_ad654a_async_dispatch.py -v

# Ward Room regression
pytest tests/test_ward_room.py tests/test_ward_room_agents.py -v

# NATS regression
pytest tests/test_ad637a_nats_foundation.py tests/test_ad637z_nats_cleanup.py -v

# Intent bus regression
pytest tests/test_intent.py -v

# Full suite
pytest -n auto
```

---

## Files Summary

| File | Action | Lines Changed |
|------|--------|--------------|
| `src/probos/startup/nats.py` | Edit | +5 (new stream) |
| `src/probos/mesh/nats_bus.py` | Edit | +20 (NATSMessage.term, manual_ack param, delete_consumer) |
| `src/probos/mesh/intent.py` | Edit | +100 (dispatch_async, js_subscribe_agent_dispatch, subscribe wiring, unsubscribe cleanup) |
| `src/probos/ward_room_pipeline.py` | **New** | ~120 (WardRoomPostPipeline class) |
| `src/probos/cognitive/cognitive_agent.py` | Edit | +40 (_self_post_ward_room_response, handle_intent hook) |
| `src/probos/ward_room_router.py` | Edit | -70/+15 (remove Phase 2 gather + Phase 3, add public wrappers) |
| `src/probos/proactive.py` | Edit | +10 (public method wrappers) |
| `src/probos/runtime.py` | Edit | +10 (pipeline creation in _apply_finalization) |
| `tests/test_ad654a_async_dispatch.py` | **New** | ~550 (27 tests) |

**Estimated net:** ~+780 lines new/modified, ~-70 lines removed = ~+710 lines net.
