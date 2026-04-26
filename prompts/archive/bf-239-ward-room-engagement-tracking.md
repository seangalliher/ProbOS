# BF-239: Ward Room Thread Engagement Tracking (Working Memory)

**Issue:** #342
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-573 (Working Memory — complete), BF-236 (Dispatch Round Dedup — complete), AD-654a (Async Dispatch — complete)
**Files:** `src/probos/cognitive/cognitive_agent.py` (EDIT), `src/probos/cognitive/agent_working_memory.py` (EDIT), `tests/test_bf239_ward_room_engagement_tracking.py` (NEW)

## Problem

Agents double-post in Ward Room threads on all-hands Captain messages. The Captain creates a thread → `ward_room_thread_created` dispatches all agents → agents reply → each agent's reply triggers a coalesced `ward_room_post_created` event → the router dispatches agents **again** for the same thread.

BF-236's round-post tracker (`has_posted_in_round`) checks at **dispatch time** (router context), but the agent's pipeline records `record_round_post` at **completion time** (pipeline Step 8). When the coalesced event fires before the first pipeline finishes, the router sees no record and dispatches the agent a second time. The agent processes the second intent and posts a near-duplicate reply with slightly different wording.

**Observed:** Nova, Lyra, and Forge each posted twice to the same all-hands thread. Content is slightly reworded (not identical), so BF-197 content similarity doesn't catch it.

**Root cause:** The dedup check happens at the wrong architectural layer. The router decides at dispatch time whether the agent should respond. But the agent's cognitive queue is **serial** (`max_ack_pending=1`) — by the time the second intent is processed, the first has completed. The agent itself should know it already replied.

## Design

### Architectural Insight

This is a **cognitive problem**, not an infrastructure problem. The agent lacks self-awareness of its own in-flight and recently-completed ward room engagement. The fix belongs in working memory, not in the router's dispatch logic.

Working memory already has `ActiveEngagement` for games (check-and-skip at `cognitive_agent.py:1394` and `:2849`). This fix extends that pattern to ward room replies.

**What this does NOT do:**
- Does not remove BF-236 or BF-198 — those remain as defense-in-depth at the router layer
- Does not modify the router or pipeline — the fix is entirely in the cognitive agent
- Does not add LLM tokens — the engagement check is a synchronous dict lookup, no LLM call
- Does not block @mentions — explicit dispatch (`is_direct_target`) bypasses the gate

### Serial Queue Guarantee

The cognitive queue processes one intent at a time (`max_ack_pending=1` in `mesh/intent.py:258`). This means:
1. Intent 1 arrives → agent processes → posts → records engagement → completes
2. Intent 2 arrives → agent checks engagement → sees record → skips

No race condition is possible with serial processing. The working memory write from intent 1 is guaranteed visible before intent 2's check.

---

## Section 1: Add `has_thread_engagement` helper to `AgentWorkingMemory`

**File:** `src/probos/cognitive/agent_working_memory.py` (EDIT)

After the existing `get_engagements_by_type` method (line 314), add:

```python
    def has_thread_engagement(self, thread_id: str) -> bool:
        """BF-239: Check if agent has an active ward_room_reply engagement for a thread."""
        _key = f"ward_room:{thread_id}"
        return _key in self._active_engagements and \
            self._active_engagements[_key].engagement_type == "ward_room_reply"
```

**Why namespaced key:** `_active_engagements` is keyed by `engagement_id` alone (line 177). Game engagements use `engagement_id=game_id`. If a thread UUID collided with a game ID, `add_engagement` would silently overwrite the game record. Namespacing the key as `f"ward_room:{thread_id}"` eliminates this. The `has_thread_engagement` method encapsulates the key format — callers pass raw thread_id.

---

## Section 2: Engagement gate at `handle_intent` entry

**File:** `src/probos/cognitive/cognitive_agent.py` (EDIT)

In `handle_intent()` (line 2206), add an engagement gate **after** the `is_direct` check (line 2214–2217) and **before** the self-deselect fast path (line 2219). This must be before any `await` to maintain atomicity in asyncio's cooperative scheduler.

**Builder verification step:** Before implementing, grep `ward_room_router.py` for the `ward_room_notification` IntentMessage construction (line ~592–604) and confirm both `was_mentioned` and `is_dm_channel` are present in `params`. If either is missing, add it to the router's emission as part of this BF. (Expected: both are present — `was_mentioned` at line 601, `is_dm_channel` at line 603.)

### Current code (lines 2206–2220):
```python
    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Skills first, then cognitive lifecycle.

        Returns None (self-deselect) for intents not in _handled_intents,
        unless it's a targeted direct_message (AD-397 1:1 sessions).
        """
        # AD-397: always accept direct_message if targeted to this agent
        # AD-407b: always accept ward_room_notification if targeted to this agent
        is_direct = (
            intent.intent in ("direct_message", "ward_room_notification", "proactive_think", "compound_step_replay")
            and intent.target_agent_id == self.id
        )

        # Fast path: self-deselect for unrecognized intents before any LLM call
        # AD-596b: Check cognitive skill catalog before self-deselecting
```

### New code:
```python
    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Skills first, then cognitive lifecycle.

        Returns None (self-deselect) for intents not in _handled_intents,
        unless it's a targeted direct_message (AD-397 1:1 sessions).
        """
        # AD-397: always accept direct_message if targeted to this agent
        # AD-407b: always accept ward_room_notification if targeted to this agent
        is_direct = (
            intent.intent in ("direct_message", "ward_room_notification", "proactive_think", "compound_step_replay")
            and intent.target_agent_id == self.id
        )

        # BF-239: Ward Room thread engagement gate — skip if already
        # replied to this thread in the current round. Uses working memory
        # engagement tracking (serial queue guarantees no race).
        # @mentions and DMs bypass — same principle as BF-236/cooldown gates.
        _bf239_thread_id = ""
        if intent.intent == "ward_room_notification":
            _bf239_thread_id = intent.params.get("thread_id", "")
            _bf239_mentioned = intent.params.get("was_mentioned", False)
            _bf239_is_dm = intent.params.get("is_dm_channel", False)
            if _bf239_thread_id and not _bf239_mentioned and not _bf239_is_dm:
                _wm = getattr(self, '_working_memory', None)
                if _wm and _wm.has_thread_engagement(_bf239_thread_id):
                    logger.debug(
                        "BF-239: %s already engaged with thread %s, skipping",
                        getattr(self, 'callsign', '') or self.agent_type,
                        _bf239_thread_id[:8],
                    )
                    # [NO_RESPONSE] with current confidence — the agent handled
                    # the intent (chose silence), it did not fail. No
                    # update_confidence() call: no cognitive work was performed,
                    # so Trust/Hebbian feedback should not see this event.
                    return IntentResult(
                        intent_id=intent.id,
                        agent_id=self.id,
                        success=True,
                        result="[NO_RESPONSE]",
                        confidence=self.confidence,
                    )

        # Fast path: self-deselect for unrecognized intents before any LLM call
        # AD-596b: Check cognitive skill catalog before self-deselecting
```

**Why `IntentResult` not `None`:** Returning `None` means "self-deselect, I don't handle this intent type." But the agent DOES handle `ward_room_notification` — it's choosing not to respond to THIS instance. Returning `IntentResult(success=True, result="[NO_RESPONSE]")` is the correct semantic: "I handled it, my answer is silence."

**Why before the first `await`:** In asyncio's cooperative scheduler, synchronous code between two `await` points runs atomically. The engagement check and the early return are both synchronous, so no interleaving can occur between check and return.

**[NO_RESPONSE] confidence semantics:** The early return emits `confidence=self.confidence` (the agent's current confidence level). This is a content-level signal ("my answer is silence"), not a confidence-level one. No `update_confidence()` is called because no cognitive work was performed — the agent didn't try and fail, it recognized a duplicate dispatch and declined. Trust/Hebbian feedback never sees this skip event, which is correct: the router should not learn from a dedup gate, only from genuine cognitive decisions.

---

## Section 3: Extract cognitive lifecycle into helper method

**File:** `src/probos/cognitive/cognitive_agent.py` (EDIT)

Extract the cognitive lifecycle (lines 2257–2626) into a new private method. This is a **move, not a rewrite** — the 370 lines of existing lifecycle code go into the helper unchanged. No re-indentation of the lifecycle body is needed because it's already at the correct indent level for a method body.

### New method (add immediately above `handle_intent`):

```python
    async def _run_cognitive_lifecycle(
        self,
        intent: IntentMessage,
        cognitive_skill_instructions: str | None = None,
        skill_entries: list | None = None,
    ) -> IntentResult:
        """Execute the full cognitive lifecycle: perceive → decide → act → report.

        BF-239: Extracted from handle_intent so try/finally can wrap the
        call site without re-indenting ~370 lines. All existing returns
        (normal completion, compound procedure early return) are preserved.

        Args:
            intent: The IntentMessage being processed.
            cognitive_skill_instructions: AD-596b cognitive skill instructions (if any).
            skill_entries: AD-596b skill catalog entries matched for this intent (if any).
        """
        # --- CUT lines 2257–2626 from handle_intent and PASTE here unchanged ---
        # Starts at line 2257: observation = await self.perceive(intent)
        # Ends at line 2626:   return IntentResult(intent_id=intent.id, ...)
```

The builder should:
1. Cut lines 2257 (starting `observation = await self.perceive(intent)`) through 2626 (ending the final `return IntentResult(...)`) from `handle_intent`.
2. Paste into the new method body unchanged.
3. Rename `_cognitive_skill_instructions` → `cognitive_skill_instructions` in the two places it's referenced (line 2263 `if _cognitive_skill_instructions:` and line 2347 `if _cognitive_skill_instructions and _skill_entries:`).
4. Rename `_skill_entries` → `skill_entries` in the three places it's referenced (line 2265 `_skill_entries[0].name`, line 2347 `_skill_entries`, line 2353 `_skill_entries[0]`).

**Builder pre-cut verification step (REQUIRED):** Before cutting, run:
```
grep -n "_[a-z]" cognitive_agent.py | awk 'NR>=2257 && NR<=2626'
```
and list every `_underscore_local` whose definition is above line 2257. Each one must be either a parameter on the helper or moved into the helper. Known external locals:
- `_cognitive_skill_instructions` — defined at line 2221, used at lines 2263, 2347. Passed as `cognitive_skill_instructions` parameter.
- `_skill_entries` — defined at line 2225, used at lines 2265, 2347, 2353. Passed as `skill_entries` parameter.

All other `_`-prefixed locals in the lifecycle body (`_faithfulness`, `_intro_faith`, `_bridge`, `_aug_used`, `_aug_entry`, etc.) are created within the lifecycle scope or accessed via `getattr(self, ...)` — they are not external dependencies. If the builder finds any additional external locals during the grep, add them as parameters and report the finding.

---

## Section 4: Replace lifecycle call site with engagement + try/finally

**File:** `src/probos/cognitive/cognitive_agent.py` (EDIT)

Where the lifecycle code was removed (Section 3), insert the engagement registration and a try/finally wrapper around the new helper call.

### Current code (after Section 3's extraction, lines 2254–2257 become):
```python
        # Skill dispatch — direct handler call, no LLM reasoning
        if intent.intent in self._skills:
            skill = self._skills[intent.intent]
            return await skill.handler(intent, llm_client=self._llm_client)

        # Cognitive lifecycle — LLM-guided reasoning
        observation = await self.perceive(intent)
        # ... (370 lines removed by Section 3)
```

### New code:
```python
        # Skill dispatch — direct handler call, no LLM reasoning
        if intent.intent in self._skills:
            skill = self._skills[intent.intent]
            return await skill.handler(intent, llm_client=self._llm_client)

        # BF-239: Register ward room thread engagement before cognitive lifecycle.
        # Recorded here (after skill dispatch, before lifecycle) so that:
        # 1. The engagement exists before any await (perceive's LLM call)
        # 2. Skill-dispatched intents don't get engagement-tracked
        # Key namespaced as "ward_room:{thread_id}" to avoid collision
        # with game engagements that use raw game_id as engagement_id.
        if _bf239_thread_id:
            # Function-local import: cognitive_agent.py does not import
            # ActiveEngagement at module level (only AgentWorkingMemory,
            # and that's also function-local at line 100). Keeping the
            # pattern consistent avoids circular import risk.
            from probos.cognitive.agent_working_memory import ActiveEngagement
            _wm = getattr(self, '_working_memory', None)
            if _wm:
                _wm.add_engagement(ActiveEngagement(
                    engagement_type="ward_room_reply",
                    engagement_id=f"ward_room:{_bf239_thread_id}",
                    summary=f"Replying to Ward Room thread {_bf239_thread_id[:8]}",
                    state={"thread_id": _bf239_thread_id},
                ))

        try:
            return await self._run_cognitive_lifecycle(
                intent, _cognitive_skill_instructions, _skill_entries,
            )
        finally:
            # BF-239: Remove ward room thread engagement on ALL exit paths.
            # Covers: normal completion, compound procedure early return,
            # and exceptions from perceive/decide/act/report.
            # The engagement is the short-lived "I'm currently working on this" signal.
            # Historical record preserved via _summarize_action (Section 5).
            if _bf239_thread_id:
                _wm = getattr(self, '_working_memory', None)
                if _wm:
                    _wm.remove_engagement(f"ward_room:{_bf239_thread_id}")
```

**Why extract to helper:** The cognitive lifecycle (lines 2257–2626) is ~370 lines with multiple return points (compound procedure early return at line 2407, normal return at line 2619). Wrapping all of it in `try:` would require re-indenting every line — a massive diff that obscures the actual 10-line change. Extracting to `_run_cognitive_lifecycle` keeps the existing code unchanged and makes the try/finally a clean 6-line wrapper at the call site.

**Why `skill_entries` parameter:** `_skill_entries` is defined at line 2225 inside `handle_intent`'s AD-596b skill-catalog block and referenced at lines 2265, 2347, 2353 inside the lifecycle body. Without passing it through, the extracted helper would raise `NameError` on any cognitive-skill intent. Same class of bug as AD-618b's `_definitions` scoping issue — a referenced local that doesn't exist in the new scope.

**IMPORTANT — `_skill_entries` initialization:** The existing code defines `_skill_entries` only inside `if not is_direct and intent.intent not in self._handled_intents:` (line 2222). When `is_direct` is True (the common ward room path), `_skill_entries` is never assigned. The call site `self._run_cognitive_lifecycle(intent, _cognitive_skill_instructions, _skill_entries)` would raise `NameError`. **Fix:** Add `_skill_entries = None` at line 2222, alongside the existing `_cognitive_skill_instructions = None` at line 2221:

```python
        _cognitive_skill_instructions = None
        _skill_entries = None  # BF-239: must be defined for _run_cognitive_lifecycle call
        if not is_direct and intent.intent not in self._handled_intents:
```

**Why namespaced engagement_id:** `_active_engagements` is keyed by `engagement_id` (line 177 of `agent_working_memory.py`). Game engagements use raw `game_id`. Using `f"ward_room:{thread_id}"` prevents collision if a thread UUID matches a game ID. The `has_thread_engagement` method (Section 1) encapsulates this key format.

**Why try/finally over cleanup-before-each-return:** The extracted helper has multiple return points. `try/finally` at the call site covers all of them — normal completion, early returns, and exceptions — with zero changes inside the helper. Any future early return added to the lifecycle is automatically covered.

**Edge case — failed posts:** If the lifecycle raises or decides `[NO_RESPONSE]`, the engagement is still removed. Correct behavior: the agent has processed (or failed to process) the notification and should not be permanently blocked from future notifications for the same thread.

**Note:** `_bf239_thread_id` is set to `""` for non-ward-room intents (Section 2), so the engagement registration and cleanup are both no-ops for DMs, proactive thinks, etc.

---

## Section 5: Improve `_summarize_action` to include thread_id

**File:** `src/probos/cognitive/cognitive_agent.py` (EDIT)

The existing `_summarize_action` for `ward_room_notification` (line 2938–2940) records channel but not thread. Add thread_id so working memory has thread-level context for future cognitive decisions.

### Current code (lines 2938–2940):
```python
        if intent_type == "ward_room_notification":
            channel = intent.params.get("channel_name", "")
            return f"Responded in Ward Room #{channel}: '{output[:100]}'"
```

### New code:
```python
        if intent_type == "ward_room_notification":
            channel = intent.params.get("channel_name", "")
            thread_id = intent.params.get("thread_id", "")
            _thread_tag = f" (thread {thread_id[:8]})" if thread_id else ""
            return f"Responded in Ward Room #{channel}{_thread_tag}: '{output[:100]}'"
```

---

## Section 6: Tests

**File:** `tests/test_bf239_ward_room_engagement_tracking.py` (NEW)

### Test Setup Pattern

Use the same `CognitiveAgent` instantiation pattern as existing ward room tests. Mock `_working_memory` as a real `AgentWorkingMemory` instance (not a mock — test the actual engagement tracking logic). Mock `_self_post_ward_room_response` to avoid ward room service dependencies.

Build `IntentMessage` instances with:
```python
IntentMessage(
    intent="ward_room_notification",
    params={
        "thread_id": "thread-1",
        "channel_name": "general",
        "event_type": "ward_room_post_created",
        "was_mentioned": False,
        "is_dm_channel": False,
    },
    target_agent_id=agent.id,
)
```

### Tests

1. **First notification for thread proceeds normally** — agent processes `ward_room_notification`, returns `IntentResult` with actual LLM output (not `[NO_RESPONSE]`). Working memory has no prior engagement for the thread.

2. **Second notification for same thread returns [NO_RESPONSE]** — call `handle_intent` twice for the same thread_id. Second call returns `IntentResult(success=True, result="[NO_RESPONSE]")`. Verify `perceive()` is NOT called on the second invocation (no LLM call wasted).

3. **Different thread_id proceeds normally** — agent has engagement for thread-1, receives notification for thread-2. Should proceed to full cognitive lifecycle.

4. **@mentioned agent bypasses engagement gate** — agent has engagement for thread-1, receives notification for thread-1 with `was_mentioned=True`. Should proceed to cognitive lifecycle.

5. **DM channel bypasses engagement gate** — agent has engagement for thread-1, receives notification for thread-1 with `is_dm_channel=True`. Should proceed.

6. **Engagement removed after successful post** — after `handle_intent` completes, `has_thread_engagement(thread_id)` returns False. The engagement is cleaned up.

7. **Engagement removed after [NO_RESPONSE] decision** — agent processes notification but decides `[NO_RESPONSE]` (e.g., empty LLM output). Engagement is still removed so future rounds aren't blocked.

7b. **Engagement removed on lifecycle exception** — mock `perceive()` to raise `RuntimeError`. Verify `has_thread_engagement(thread_id)` returns False after the exception propagates. Tests the `finally` cleanup path.

7c. **Engagement removed on compound procedure early return** — mock the compound procedure path (line 2407) to trigger an early return from `_run_cognitive_lifecycle`. Verify `has_thread_engagement(thread_id)` returns False after. Tests that `finally` covers the mid-lifecycle return, not just the normal exit.

8. **Non-ward-room intents unaffected** — `direct_message` and `proactive_think` intents don't create or check engagements.

9. **has_thread_engagement returns False for wrong thread** — unit test on `AgentWorkingMemory.has_thread_engagement()` — engagement for thread-1 doesn't match thread-2.

10. **has_thread_engagement returns False for wrong type** — game engagement with same ID as thread doesn't match `ward_room_reply` type.

10b. **Namespaced engagement_id accepted by add/remove** — add an `ActiveEngagement(engagement_id="ward_room:thread-1", ...)`, verify `has_thread_engagement("thread-1")` returns True, then `remove_engagement("ward_room:thread-1")` and verify it returns False. Acceptance test that colon in engagement_id doesn't break the dict key path.

11. **Engagement cleared after lifecycle — subsequent dispatch proceeds** — simulate: agent replies to thread → engagement removed at lifecycle exit → agent receives new notification for same thread → should proceed to full cognitive lifecycle. Verifies engagement cleanup doesn't persist across dispatches.

12. **Engagement survives across cognitive lifecycle steps** — verify engagement exists during `perceive()` and `decide()` calls. Use side-effect mocks that assert mid-lifecycle:

```python
async def _assert_engaged_during_perceive(intent):
    """Side-effect mock: runs during perceive(), asserts engagement is live."""
    assert agent._working_memory.has_thread_engagement("thread-1")
    return {"raw_observation": "test"}

agent.perceive = _assert_engaged_during_perceive
result = await agent.handle_intent(ward_room_intent)
# Engagement should be cleaned up AFTER lifecycle completes
assert not agent._working_memory.has_thread_engagement("thread-1")
```

---

## Existing Test Impact

- **BF-236 tests** (`tests/test_bf236_dispatch_dedup_gate.py`) — No changes needed. BF-236 tests operate at the router level. BF-239 is at the agent level. Both layers remain active.
- **AD-654a tests** — No changes needed. `_self_post_ward_room_response` behavior unchanged.
- **AD-573 working memory tests** — No changes needed. New `has_thread_engagement` is additive.

---

## Engineering Principles Compliance

- **SOLID/S** — Working memory owns engagement state. Cognitive agent owns the gate decision. No new classes — extends existing `ActiveEngagement` pattern.
- **SOLID/O** — `has_thread_engagement` is a new method on `AgentWorkingMemory`, not a modification of existing methods. The `handle_intent` gate follows the same pattern as the game engagement check.
- **Law of Demeter** — Gate accesses `self._working_memory.has_thread_engagement()` — one level deep. No reaching through engagement internals.
- **Fail Fast** — Early return with `IntentResult([NO_RESPONSE])` before any LLM call. Zero wasted tokens.
- **Defense in Depth** — BF-239 is the primary cognitive defense. BF-236 (router) and BF-198 (proactive) remain as infrastructure backstops. Three layers, different architectural levels.
- **DRY** — Reuses `ActiveEngagement` dataclass and `add_engagement`/`remove_engagement`/`has_engagement` API. Only adds one new convenience method (`has_thread_engagement`).

---

## Dedup Stack Assessment (Post-BF-239)

After BF-239, the five-layer dedup stack is:

| Layer | Location | Guards Against | Status |
|-------|----------|----------------|--------|
| BF-234 | Transport (intent.py) | JetStream redelivery, publish timeouts | **Necessary** — structural dedup |
| BF-239 | Agent (cognitive_agent.py) | Duplicate ward room dispatch for same thread | **NEW — primary cognitive defense** |
| BF-236 | Router (ward_room_router.py) | Round-scoped re-dispatch | **Backstop** — still useful as cheap infrastructure filter |
| BF-237 | Pipeline (ward_room_pipeline.py) | Action extractor double-post within single invocation | **Necessary** — orthogonal concern |
| BF-197 | Pipeline (proactive.py) | Content-similar posts | **Necessary** — orthogonal concern |

BF-198 (`_responded_threads`, 600s window) overlaps most with BF-239 but serves a different scope (proactive loop, cross-round). Retain for now; consider consolidation in a future AD.

---

## Tracking Updates

### PROGRESS.md
Add:
```
BF-239 COMPLETE. Ward Room thread engagement tracking via working memory — agent-level cognitive dedup using ActiveEngagement pattern. Prevents duplicate replies when dispatched twice for the same thread. Cognitive lifecycle extracted to `_run_cognitive_lifecycle` helper; try/finally at call site ensures engagement cleanup on all exit paths. 15 tests. Issue #342.
```

### DECISIONS.md
Add entry:
```
### BF-239 — Ward Room Thread Engagement Tracking (2026-04-25)
**Context:** Agents double-posted in all-hands threads despite four infrastructure dedup layers (BF-234/236/237/197). Root cause: BF-236 checks at dispatch time, but the agent's serial cognitive queue processes intents sequentially — by the time the second intent arrives, the first has completed but the router already dispatched it.
**Decision:** Fix at the agent cognitive layer using working memory engagement tracking, not at the infrastructure layer. Agent registers an ActiveEngagement("ward_room_reply", thread_id) before the cognitive lifecycle and checks for it at handle_intent entry. Cognitive lifecycle extracted to `_run_cognitive_lifecycle` helper; try/finally at call site ensures engagement cleanup on all exit paths (normal, compound early return, exception). Serial queue (max_ack_pending=1) guarantees the check always sees records from prior completions. @mentions and DMs bypass the gate. Infrastructure dedup layers (BF-236, BF-198) retained as defense-in-depth backstops.
**Lesson learned:** Infrastructure guardrails were solving a problem that belonged at the cognitive layer. The agent's working memory already had the primitives (ActiveEngagement) — they just weren't being used for ward room replies. Before adding infrastructure dedup, ask: "Could the agent solve this itself?"
**Consequences:** Five-layer dedup stack. Agent-level fix is zero-token cost (synchronous dict lookup, no LLM call). Future consideration: BF-198's _responded_threads (600s window) may be redundant with engagement tracking + BF-236's round tracker.
```

### docs/development/roadmap.md
Update BF-239 row to Closed. BF-239a row already added — evaluate BF-198 deprecation T+72h post-deploy.
