# AD-654d: Internal Event Emitters

**Priority:** Enables reactive multi-agent workflows  
**Depends:** AD-654a (Async Dispatch) ✅, AD-654b (Cognitive Queue) ✅, AD-654c (TaskEvent + Dispatcher) ✅  
**Plan:** `cheerful-tinkering-pudding.md` (AD-654 decomposition)

## Problem

AD-654c delivered the TaskEvent protocol and Dispatcher — but nothing emits TaskEvents yet. Every activation still flows through the old paths:

1. **Recreation games** (`ward_room_router.py:657-695`): When an agent makes a move, the router posts a board update with `@next_player` to the Ward Room thread. The next player finds out it's their turn via ward room notification — an indirect, multi-hop path: `make_move() → router posts @mention → WardRoom event → router dispatches ward_room_notification → agent`. No direct "your turn" signal exists.

2. **Ward Room @mentions** (`ward_room_router.py:424-431`): Mentions are detected by the router during dispatch and set `was_mentioned=True` on the IntentMessage. This works but is coupled to the router's dispatch path — only ward room notifications carry mention semantics. There's no standalone "you were mentioned" event that other systems could subscribe to.

3. **Agent-to-agent delegation**: Agents cannot delegate work to each other. No `[ASSIGN @agent]` or `[HANDOFF @agent]` action tags exist. The only inter-agent activation path is posting to the Ward Room and hoping the router dispatches it.

4. **Workforce state transitions** (`workforce.py:1133-1266`): WorkItem status changes emit `WORK_ITEM_STATUS_CHANGED` and `WORK_ITEM_ASSIGNED` events to the event bus (for HXI WebSocket), but don't create TaskEvents. An assigned agent has no reactive notification that work was pushed to them.

**Fix:** Wire internal ProbOS services as TaskEvent emitters, using the AD-654c Dispatcher. Each emitter creates a TaskEvent with the right target and priority, and the Dispatcher routes it to the agent's cognitive queue. Agents react to events instead of polling the Ward Room.

## Scope — What This AD Does and Does NOT Do

### In Scope (4 emitters)

1. **RecreationService** — `move_required` TaskEvent when it's an agent's turn
2. **Agent delegation tags** — `[ASSIGN @agent task]` and `[HANDOFF @agent reason]` parsed from agent output, dispatched as TaskEvents
3. **WorkItem assignment** — TaskEvent when a WorkItem is assigned/claimed, notifying the assigned agent
4. **Ward Room @mention** — standalone `mention` TaskEvent alongside the existing ward room notification path (additive, not replacing)

### NOT In Scope

- **Ward Room router migration to Dispatcher.** The router has 8+ policy layers (cooldown, round tracking, max_agent_rounds, DM exchange limits, BF-188 Captain delivery ordering, @mention bypass, post cap, BF-173 suppression). These are ward-room-specific policy that would be wrong to move into the Dispatcher. The router continues using `IntentBus.dispatch_async()` for ward room notifications. A future AD may refactor the router to build TaskEvents and call Dispatcher, but that requires careful policy-layer separation and is out of scope here.
- **Proactive loop migration.** The proactive loop continues calling `agent.handle_intent()` directly. Making the proactive loop emit ambient-priority TaskEvents is architecturally clean but changes the proactive processing model — deferred.
- **Alert escalation TaskEvents.** Bridge alerts already have ESCALATION_START/RESOLVED/EXHAUSTED events and a Counselor subscription model. Wiring these as TaskEvents would require designing which agent receives them and what they do with them — deferred until the clinical/bridge alert model is clearer.
- **External integration.** MCP Apps, webhooks — AD-654e scope.

## Architecture Change

**Before (AD-654c — current):**
```
RecreationService.make_move()  → router posts @mention to Ward Room
                                → agent sees ward_room_notification (indirect)

Agent output: "[ASSIGN @Atlas investigate]"  → ignored (tag doesn't exist)

WorkItem assigned to agent     → WORK_ITEM_ASSIGNED event (HXI only)
                                → agent has no notification

Agent posts "@Reed check this" → router sets was_mentioned=True
                                → interlocked with ward_room_notification
```

**After (AD-654d):**
```
RecreationService.make_move()  → TaskEvent(move_required) → Dispatcher → agent queue
                                  (PLUS existing @mention path preserved for WR context)

Agent output: "[ASSIGN @Atlas investigate]"
                               → TaskEvent(task_assigned) → Dispatcher → Atlas queue

WorkItem assigned to agent     → TaskEvent(work_item_assigned) → Dispatcher → agent queue
                                  (PLUS existing WORK_ITEM_ASSIGNED event preserved)

Agent posts "@Reed check this" → TaskEvent(mention) → Dispatcher → Reed queue
                                  (PLUS existing ward_room_notification path preserved)
```

All new TaskEvent paths are **additive** — existing mechanisms continue working. The TaskEvents provide a direct, priority-aware activation path alongside the existing Ward Room notification flow.

## Emitter 1: RecreationService — `move_required`

### Current Flow (ward_room_router.py:657-695)

After `rec_svc.make_move()`, the router posts to the game's Ward Room thread:
```python
_next = game_info['state']['current_player']
body = f"```\n{board}\n```\nYour move, @{_next}"
await self._ward_room.create_post(thread_id=..., body=body, ...)
```

The `@{_next}` mention triggers a ward room notification to the next player. This works but is indirect — 4 hops: make_move → post to WR → WR event → router dispatch → agent queue.

### New: Direct TaskEvent

In `RecreationService.make_move()` (`src/probos/recreation/service.py`), after the move is applied and the game is NOT finished, emit a `move_required` TaskEvent:

```python
# After existing GAME_UPDATE emission (line 131-143), BEFORE the game completion check at line 146:
if not engine.is_finished(new_state) and self._dispatcher:
    next_player_callsign = new_state["current_player"]
    next_agent_id = self._resolve_callsign(next_player_callsign)
    if next_agent_id:
        from probos.activation import task_event_for_agent
        event = task_event_for_agent(
            agent_id=next_agent_id,
            source_type="recreation",
            source_id=game_id,
            event_type="move_required",
            priority=Priority.NORMAL,
            payload={
                "game_id": game_id,
                "game_type": game_info["game_type"],
                "board": engine.render_board(new_state),
                "valid_moves": engine.get_valid_moves(new_state),
                "opponent": next(
                    (p for p in (game_info["challenger"], game_info["opponent"])
                     if p != next_player_callsign), ""
                ),
                "your_symbol": new_state["symbols"].get(next_player_callsign, ""),
                "thread_id": game_info.get("thread_id", ""),
            },
            thread_id=game_info.get("thread_id"),
        )
        await self._dispatcher.dispatch(event)
```

### Dispatcher Injection

RecreationService constructor (`service.py:26-31`) currently takes `ward_room=None`, `records_store=None`, `emit_event_fn=None` (all typed `Any`). Add optional `dispatcher` and `callsign_registry` parameters:

```python
def __init__(
    self,
    ward_room: Any = None,
    records_store: Any = None,
    emit_event_fn: Any = None,
    dispatcher: Any | None = None,            # AD-654d
    callsign_registry: Any | None = None,     # AD-654d: for callsign → agent_id
) -> None:
    ...
    self._dispatcher = dispatcher
    self._callsign_registry = callsign_registry
```

### Callsign → Agent ID Resolution

RecreationService tracks players by callsign (e.g., "Wesley", "Atlas"). The Dispatcher needs `agent_id`. Add a private helper:

**Verified:** `CallsignRegistry.resolve(callsign) -> dict[str, Any] | None` returns `{"callsign": str, "agent_type": str, "agent_id": str | None, "display_name": str, "department": str}`. `agent_id` is `None` if no live agent found in the registry. See `crew_profile.py:350-373`.

```python
def _resolve_callsign(self, callsign: str) -> str | None:
    """Resolve a callsign to agent_id via CallsignRegistry."""
    if not self._callsign_registry:
        return None
    resolved = self._callsign_registry.resolve(callsign)
    return resolved.get("agent_id") if resolved else None
```

### Ward Room @mention Preserved

The existing Ward Room post with `@next_player` continues. The TaskEvent is an **additional** direct activation path. Both fire — the agent gets the TaskEvent in their queue (fast, direct) and also sees the Ward Room thread update (provides conversational context). This is intentional redundancy during the transition period. A future AD may remove the @mention notification once the TaskEvent path is validated.

### Startup Wiring

In `src/probos/startup/finalize.py:290-296`, where RecreationService is created:

```python
# Current (line 292-296):
runtime.recreation_service = RecreationService(
    ward_room=runtime.ward_room,
    records_store=runtime._records_store,
    emit_event_fn=runtime._emit_event,
)

# Change to:
runtime.recreation_service = RecreationService(
    ward_room=runtime.ward_room,
    records_store=runtime._records_store,
    emit_event_fn=runtime._emit_event,
    dispatcher=runtime.dispatcher,                # AD-654d
    callsign_registry=runtime.callsign_registry,  # AD-654d
)
```

## Emitter 2: Agent Delegation Tags — `[ASSIGN]` and `[HANDOFF]`

### Design

Agents can delegate work to other agents via action tags in their Ward Room responses or proactive output:

- `[ASSIGN @callsign] task description [/ASSIGN]` — push a task to another agent. The target agent receives a `task_assigned` TaskEvent with NORMAL priority.
- `[HANDOFF @callsign] reason/context [/HANDOFF]` — transfer responsibility for an active engagement. The target agent receives a `task_handoff` TaskEvent with CRITICAL priority. Justification: the originating agent is dropping the work — the handoff recipient must pick it up before the engagement goes stale. This is a genuine time-sensitive responsibility transfer, not a queued task.

### Parsing Location

Add delegation tag parsing to `ProactiveCognitiveLoop._extract_and_execute_actions()` in `src/probos/proactive.py`. This method already handles `[ENDORSE]`, `[REPLY]`, `[DM]`, `[NOTEBOOK]` tags (lines ~1997-2200). Add `[ASSIGN]` and `[HANDOFF]` extraction **at the end of the existing tag chain** (after line ~2062, after the DM extraction block). Each prior handler does `text = re.sub(...)` so processing order matters — appending at the end ensures delegation tags don't interfere with existing tag extraction.

```python
# --- ASSIGN (AD-654d) ---
assign_pattern = r'\[ASSIGN\s+@([\w-]+)\]\s*(.*?)\s*\[/ASSIGN\]'
for match in re.finditer(assign_pattern, text, re.DOTALL):
    target_callsign = match.group(1)
    task_description = match.group(2).strip()
    if rt.dispatcher and rt.callsign_registry:
        resolved = rt.callsign_registry.resolve(target_callsign)
        target_agent_id = resolved.get("agent_id") if resolved else None
        if target_agent_id and target_agent_id != agent.id:  # self-assignment guard
            from probos.activation import task_event_for_agent
            event = task_event_for_agent(
                agent_id=target_agent_id,
                source_type="agent",
                source_id=agent.id,
                event_type="task_assigned",
                priority=Priority.NORMAL,
                payload={
                    "from_agent_id": agent.id,
                    "from_callsign": getattr(agent, 'callsign', ''),
                    "task_description": task_description,
                },
            )
            await rt.dispatcher.dispatch(event)
            actions.append({"type": "assign", "target": target_callsign, "task": task_description})
            logger.info("AD-654d: %s assigned task to @%s", agent.id[:12], target_callsign)
text = re.sub(assign_pattern, '', text, flags=re.DOTALL).strip()

# --- HANDOFF (AD-654d) ---
handoff_pattern = r'\[HANDOFF\s+@([\w-]+)\]\s*(.*?)\s*\[/HANDOFF\]'
for match in re.finditer(handoff_pattern, text, re.DOTALL):
    target_callsign = match.group(1)
    handoff_context = match.group(2).strip()
    if rt.dispatcher and rt.callsign_registry:
        resolved = rt.callsign_registry.resolve(target_callsign)
        target_agent_id = resolved.get("agent_id") if resolved else None
        if target_agent_id and target_agent_id != agent.id:  # self-handoff guard
            from probos.activation import task_event_for_agent
            event = task_event_for_agent(
                agent_id=target_agent_id,
                source_type="agent",
                source_id=agent.id,
                event_type="task_handoff",
                priority=Priority.CRITICAL,
                payload={
                    "from_agent_id": agent.id,
                    "from_callsign": getattr(agent, 'callsign', ''),
                    "handoff_context": handoff_context,
                },
            )
            await rt.dispatcher.dispatch(event)
            actions.append({"type": "handoff", "target": target_callsign, "context": handoff_context})
            logger.info("AD-654d: %s handed off to @%s", agent.id[:12], target_callsign)
text = re.sub(handoff_pattern, '', text, flags=re.DOTALL).strip()
```

### Rank Gating

Delegation should be rank-gated. Not every ensign should be able to assign tasks to peers. Apply the same rank-gating pattern used in the same method for DM extraction (`proactive.py:2059-2060`):

```python
# Before ASSIGN parsing (rank and trust are already computed at lines 2018-2019):
# trust_score = rt.trust_network.get_score(agent.id) if rt.trust_network else 0.5
# rank = Rank.from_trust(trust_score)
assign_min_rank = Rank.LIEUTENANT
_RANK_ORDER_ASSIGN = [Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR]
can_assign = _RANK_ORDER_ASSIGN.index(rank) >= _RANK_ORDER_ASSIGN.index(assign_min_rank)
```

If the agent doesn't meet the rank requirement for `[ASSIGN]`, skip the tag (log at DEBUG, don't emit TaskEvent). `[HANDOFF]` has no rank gate — any agent should be able to escalate.

### Self-Assignment / Self-Handoff Guard

An agent assigning or handing off to itself is a no-op. Both guards are inline in the code above: `if target_agent_id and target_agent_id != agent.id`.

### Runtime Access

`_extract_and_execute_actions()` already accesses runtime via `rt = self._runtime` (line 2013). `runtime.dispatcher` and `runtime.callsign_registry` are available via this reference. Use `rt.dispatcher` and `rt.callsign_registry` in the delegation tag parsing code (consistent with the existing `rt.trust_network`, `rt.ward_room` references in the same method).

## Emitter 3: WorkItem Assignment — `work_item_assigned`

### Current Flow (workforce.py:1208-1266)

`WorkItemStore.assign_work_item()` assigns a WorkItem to an agent (BookableResource) and emits `WORK_ITEM_ASSIGNED` event. But the assigned agent has no reactive notification — they'll only discover the work item during their next proactive scan (if workforce context is included).

### New: TaskEvent on Assignment

After the existing `WORK_ITEM_ASSIGNED` event emission (`workforce.py:1266-1270`), emit a TaskEvent to the assigned agent:

```python
# After existing event emission (line 1270):
if self._dispatcher and resource_id:
    # resource_id may be agent_uuid (not agent.id). The Dispatcher and cognitive
    # queues are keyed by agent.id. Look up the resource to get agent_type, then
    # resolve back to agent.id. For now, resource_id IS agent.id in practice
    # (agent_uuid is empty on most non-DID agents). If they diverge, the
    # Dispatcher will return unroutable — safe failure.
    from probos.activation import task_event_for_agent
    event = task_event_for_agent(
        agent_id=resource_id,
        source_type="workforce",
        source_id=work_item_id,
        event_type="work_item_assigned",
        priority=Priority.NORMAL,
        payload={
            "work_item_id": work_item_id,
            "title": item.title,
            "description": item.description,
            "work_type": item.work_type,
            "status": "scheduled",
            "assigned_by": source,
        },
    )
    await self._dispatcher.dispatch(event)
```

**Note on resource_id vs agent_id:** `BookableResource.resource_id` is set via `getattr(agent, 'agent_uuid', '') or agent.id` at `runtime.py:1662`. In the current codebase, `agent_uuid` is typically empty (only set after DID commissioning), so `resource_id == agent.id`. If DID commissioning is active and they diverge, the Dispatcher's `_get_queue(agent_id)` will return None (cognitive queues are keyed by `agent.id`) and the dispatch will fall through to `dispatch_async_fn` or `create_task`. This is safe — the task still routes, just not via the optimized queue path. A future AD may normalize workforce IDs to use `agent.id` consistently.

### Also Emit on Claim

`WorkItemStore.claim_work_item()` (`workforce.py:1273-1305`) is the pull-assignment path. The agent chose the work — they already know about it. No TaskEvent needed for self-claim.

### Dispatcher Injection

`WorkItemStore` constructor (`workforce.py:910-917`) takes `db_path`, `emit_event`, `tick_interval`, `config`, `connection_factory`. Add `_dispatcher = None` initialization and a public `attach_dispatcher()` setter:

```python
class WorkItemStore(EventEmitterMixin):
    def __init__(self, db_path: str, ...):
        ...
        self._dispatcher: Any | None = None  # AD-654d: set via attach_dispatcher()

    def attach_dispatcher(self, dispatcher: Any) -> None:
        """AD-654d: Late-bind dispatcher for work_item_assigned TaskEvent."""
        self._dispatcher = dispatcher
```

**Do NOT modify the constructor signature or `startup/communication.py`.** WorkItemStore is created in `startup/communication.py:98-106` (Phase 4), before the Dispatcher exists (Phase 7). Wire in `startup/finalize.py` via the public setter:

```python
# In finalize.py, after Dispatcher is wired:
if runtime.work_item_store:
    runtime.work_item_store.attach_dispatcher(runtime.dispatcher)
```

`runtime.work_item_store` is set at `runtime.py:1488`.

## Emitter 4: Ward Room @mention — `mention` TaskEvent

### Design

When a Ward Room post contains `@callsign`, emit a standalone `mention` TaskEvent to the mentioned agent. This is **additive** — the existing ward room notification path with `was_mentioned=True` continues unchanged. The standalone mention TaskEvent enables:
- Future subscribers to react to mentions (e.g., a mention dashboard)
- Consistent activation semantics (mentions are events, not flags on other events)
- Mention-specific priority (NORMAL, not tied to captain/non-captain classification)

### Emission Location

In `WardRoom.create_post()` flow — specifically in `MessageStore.create_post()` (`src/probos/ward_room/messages.py:230-237`), after the existing `WARD_ROOM_POST_CREATED` event emission, and in `ThreadManager.create_thread()` (`src/probos/ward_room/threads.py:483-491`), after `WARD_ROOM_THREAD_CREATED`:

```python
# After existing event emission:
mentions = extract_mentions(body)
if mentions and self._dispatcher and self._callsign_registry:
    for callsign in mentions:
        resolved = self._callsign_registry.resolve(callsign)
        if resolved and resolved.get("agent_id") and resolved["agent_id"] != author_id:
            from probos.activation import task_event_for_agent
            event = task_event_for_agent(
                agent_id=resolved["agent_id"],
                source_type="ward_room",
                source_id=post.id,  # or thread.id for thread creation
                event_type="mention",
                priority=Priority.NORMAL,
                payload={
                    "mentioned_by": author_id,
                    "mentioned_by_callsign": author_callsign,
                    "channel_id": channel_id if available else thread.channel_id,
                    "body_preview": body[:200],
                },
                thread_id=thread_id,
            )
            await self._dispatcher.dispatch(event)
```

### Dispatcher Injection

`MessageStore` and `ThreadManager` need `dispatcher` and `callsign_registry`. These flow through the `WardRoom` service facade via a public `attach_dispatcher()` setter (NOT private attribute assignment — Law of Demeter, matching AD-654c's callback injection discipline):

**Step 1:** Add `attach_dispatcher()` methods to MessageStore, ThreadManager, and WardRoomService:

```python
# In MessageStore (messages.py):
def attach_dispatcher(self, dispatcher: Any, callsign_registry: Any) -> None:
    """AD-654d: Late-bind dispatcher for mention TaskEvent emission."""
    self._dispatcher = dispatcher
    self._callsign_registry = callsign_registry

# In ThreadManager (threads.py):
def attach_dispatcher(self, dispatcher: Any, callsign_registry: Any) -> None:
    """AD-654d: Late-bind dispatcher for mention TaskEvent emission."""
    self._dispatcher = dispatcher
    self._callsign_registry = callsign_registry

# In WardRoomService (service.py):
def attach_dispatcher(self, dispatcher: Any, callsign_registry: Any) -> None:
    """AD-654d: Late-bind dispatcher into message/thread stores."""
    if self._messages:
        self._messages.attach_dispatcher(dispatcher, callsign_registry)
    if self._threads:
        self._threads.attach_dispatcher(dispatcher, callsign_registry)
```

Initialize `self._dispatcher = None` and `self._callsign_registry = None` in both `MessageStore.__init__()` and `ThreadManager.__init__()`.

**Step 2:** Wire in `startup/finalize.py`, after the Dispatcher is created:

```python
# In finalize.py, after Dispatcher is wired (after runtime.dispatcher is set):
if runtime.ward_room:
    runtime.ward_room.attach_dispatcher(runtime.dispatcher, runtime.callsign_registry)
```

One public method call. No reaching through `_messages` or `_threads` from finalize.py. WardRoomService delegates internally to its own sub-services — which is its right as the facade owner.

### Dedup with Ward Room Notification

The agent may receive both a `mention` TaskEvent AND a `ward_room_notification` IntentMessage with `was_mentioned=True`. This is intentional — the ward_room_notification carries full thread context and the agent's cognitive chain processes it as a conversation event. The mention TaskEvent is a lightweight direct signal. The cognitive queue deduplicates by `_task_event_id` if needed in a future AD, but for now both are processed (they serve different purposes).

## EventType Additions

None needed. All four event types (`move_required`, `task_assigned`, `task_handoff`, `mention`) are dispatched via TaskEvent → Dispatcher → cognitive queue. They are NOT broadcast on the event bus. The Dispatcher already emits `TASK_EVENT_DISPATCHED` and `TASK_EVENT_UNROUTABLE` (from AD-654c) for observability — those are the only EventType entries consumed.

`WORK_ITEM_ASSIGNED` already exists in `events.py` and continues to be emitted by the event bus path. The new TaskEvent emission is a separate, additive path.

Do NOT add `MOVE_REQUIRED`, `TASK_ASSIGNED`, or `TASK_HANDOFF` to the EventType enum — they would be dead code.

## Engineering Principles Compliance

- **SOLID/S:** Each emitter has single responsibility — RecreationService emits game events, proactive loop parses delegation tags, WorkItemStore emits assignment events, WardRoom emits mention events. The Dispatcher handles routing. No emitter knows about other emitters.
- **SOLID/O:** RecreationService extended via constructor injection. WorkItemStore and WardRoom extended via public `attach_dispatcher()` setters. No existing behavior modified — all emissions are additive alongside existing event bus emissions.
- **SOLID/D:** Emitters receive `dispatcher: Any | None` — duck-typed, depends on the `dispatch()` method abstraction. No concrete Dispatcher import needed in emitter modules (only `task_event_for_agent` factory imported).
- **Law of Demeter:** Emitters call `self._dispatcher.dispatch(event)` — one dot. No reaching through runtime or other services. CallsignRegistry access is direct (`self._callsign_registry.resolve()`), not through runtime. Late-binding uses public `attach_dispatcher()` methods, NOT private attribute writes from finalize.py — matching AD-654c's callback injection discipline.
- **DRY:** All emitters use the same `task_event_for_agent()` factory and `Dispatcher.dispatch()` path. No duplicated routing logic. Rank gating for delegation reuses the existing `Rank.from_trust()` pattern from recreation commands.
- **Fail Fast:** If dispatcher is None, skip emission (graceful degradation — emitters are optional enhancers, not required for correctness). If callsign resolution fails, log at DEBUG and skip. If dispatch returns unroutable, Dispatcher already emits TASK_EVENT_UNROUTABLE.
- **Cloud-Ready:** TaskEvents are in-process for now. In Nooplex Cloud, the Dispatcher could publish to JetStream for cross-instance routing — but that's AD-654e.

## Files Changed

| File | Change |
|------|--------|
| `src/probos/recreation/service.py` | Add dispatcher/callsign_registry injection, emit `move_required` TaskEvent after make_move() |
| `src/probos/proactive.py` | Add `[ASSIGN]`/`[HANDOFF]` tag parsing in `_extract_and_execute_actions()` |
| `src/probos/workforce.py` | Add dispatcher param to WorkItemStore, emit TaskEvent in `assign_work_item()` |
| `src/probos/ward_room/messages.py` | Add `attach_dispatcher()`, emit `mention` TaskEvent on post creation with @mentions |
| `src/probos/ward_room/threads.py` | Add `attach_dispatcher()`, emit `mention` TaskEvent on thread creation with @mentions |
| `src/probos/startup/finalize.py` | Wire dispatcher via `attach_dispatcher()` into RecreationService, WorkItemStore, and WardRoom |
| `tests/test_ad654d_internal_emitters.py` | **NEW** — ~25 tests |

## What This Does NOT Do

1. **Does NOT migrate ward room router.** The router continues using `IntentBus.dispatch_async()` with all its policy layers (cooldown, round tracking, etc.). TaskEvents are additive alongside, not replacing.
2. **Does NOT migrate proactive loop.** The proactive loop continues calling `agent.handle_intent()` directly for ambient-priority work.
3. **Does NOT modify the Dispatcher.** AD-654c's Dispatcher is used as-is — no changes needed.
4. **Does NOT add agent intent handlers.** Agents receive `move_required`, `task_assigned`, `task_handoff`, and `mention` as IntentMessage intents (via Dispatcher's TaskEvent→IntentMessage conversion). Their existing `handle_intent()` method processes them. No new handler registration is needed — the cognitive chain's `decide()` step determines how to respond based on the intent name and params.
5. **Does NOT add JetStream streams.** All dispatch goes through existing cognitive queues (in-memory). JetStream is the upstream durable layer that feeds the queues (AD-654a).
6. **Does NOT wire alert escalation.** Bridge alert → TaskEvent is architecturally clean but requires design decisions about clinical authority and Counselor integration. Deferred.
7. **Does NOT update agent instructions.** Agents will only use `[ASSIGN]`/`[HANDOFF]` tags after their system prompts or standing orders are updated to teach them the syntax. This AD builds the infrastructure; agent instruction updates are a separate task (may happen organically via LLM discovery from examples in Ward Room context, or via explicit standing order updates).

## Tests

File: `tests/test_ad654d_internal_emitters.py`

### Recreation Emitter (5 tests)

1. **test_move_required_emitted_after_move** — `make_move()` emits TaskEvent with event_type="move_required" targeting next player's agent_id
2. **test_move_required_not_emitted_on_game_over** — no TaskEvent when game finishes (no next player)
3. **test_move_required_skipped_without_dispatcher** — graceful degradation when dispatcher is None
4. **test_move_required_payload_contains_game_context** — payload includes game_id, board, valid_moves, opponent, your_symbol, thread_id
5. **test_move_required_callsign_resolution_failure** — unresolvable callsign logs debug, no crash

### Delegation Tags (8 tests)

6. **test_assign_tag_parsed_and_dispatched** — `[ASSIGN @Atlas] investigate anomaly [/ASSIGN]` → TaskEvent(task_assigned, NORMAL) to Atlas
7. **test_handoff_tag_parsed_and_dispatched** — `[HANDOFF @Reed] taking over analysis [/HANDOFF]` → TaskEvent(task_handoff, CRITICAL) to Reed
8. **test_assign_rank_gated** — agents below Lieutenant rank: [ASSIGN] tag ignored, no TaskEvent emitted
9. **test_handoff_no_rank_gate** — any rank can use [HANDOFF] (escalation always allowed)
10. **test_assign_self_skipped** — agent assigning to self is a no-op
11. **test_handoff_self_skipped** — agent handing off to self is a no-op
12. **test_assign_unknown_callsign_skipped** — unresolvable callsign logged at DEBUG, no crash
13. **test_assign_tag_stripped_from_output** — tag text removed from agent's post body after extraction

### WorkItem Assignment (4 tests)

14. **test_work_item_assigned_emits_taskevent** — `assign_work_item()` emits TaskEvent with event_type="work_item_assigned" to assigned agent
15. **test_work_item_assigned_payload** — payload includes work_item_id, title, description, work_type, status, assigned_by
16. **test_work_item_assigned_no_dispatcher** — graceful degradation when dispatcher is None
17. **test_work_item_claim_no_taskevent** — `claim_work_item()` does NOT emit TaskEvent (agent already knows)

### Ward Room Mention (6 tests)

18. **test_mention_emits_taskevent** — post with `@Reed` emits TaskEvent(mention, NORMAL) to Reed's agent_id
19. **test_mention_multiple_agents** — post with `@Reed @Atlas` emits one TaskEvent per mentioned agent
20. **test_mention_self_excluded** — author mentioning themselves: no TaskEvent emitted for self
21. **test_mention_unknown_callsign_skipped** — unresolvable @mention: no crash, logged at DEBUG
22. **test_mention_thread_creation** — thread creation with @mentions also emits mention TaskEvents
23. **test_mention_no_dispatcher** — graceful degradation when dispatcher is None

### End-to-End Delivery (2 tests)

24. **test_move_required_reaches_cognitive_queue** — Create a Dispatcher with a real `AgentCognitiveQueue`, dispatch a move_required TaskEvent, assert the queue contains an IntentMessage with intent="move_required" and correct params
25. **test_assign_reaches_cognitive_queue** — Same pattern: dispatch task_assigned TaskEvent, verify IntentMessage lands in the target agent's queue with intent="task_assigned"

### Test Helpers

```python
def _make_dispatcher(accept=True):
    """Create a mock Dispatcher with dispatch() returning DispatchResult."""
    ...

def _make_callsign_registry(mapping=None):
    """Create a mock CallsignRegistry. mapping: {callsign: {agent_id, agent_type}}."""
    ...

def _make_recreation_service(dispatcher=None, callsign_registry=None):
    """Create RecreationService with mocked deps."""
    ...
```

Use `unittest.mock.MagicMock` and `AsyncMock`. Do NOT import runtime or require database fixtures. For WorkItemStore tests, use an in-memory SQLite database (the existing test pattern for workforce tests).

## Verification

```bash
# AD-654d tests
pytest tests/test_ad654d_internal_emitters.py -v

# Recreation regression
pytest tests/test_recreation*.py -v

# Ward Room regression
pytest tests/test_ward_room.py tests/test_routing.py -v

# Workforce regression
pytest tests/test_workforce*.py -v

# Proactive/action extraction regression
pytest tests/test_proactive*.py -v

# Dispatcher regression (unchanged)
pytest tests/test_ad654c_taskevent_dispatcher.py -v

# Cognitive queue regression (unchanged)
pytest tests/test_ad654b_cognitive_queue.py -v

# Full suite
pytest -n auto
```
