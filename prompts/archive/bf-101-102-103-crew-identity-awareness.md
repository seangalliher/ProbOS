# Build Prompt: BF-101 / BF-102 — Crew Identity & Self-Awareness Fixes

**Ticket:** BF-101, BF-102
**Priority:** High (crew identity is a core ProbOS thesis)
**Scope:** Agent onboarding, cognitive context, startup finalization
**Principles Compliance:** Westworld Principle, Sovereign Agent Identity, Fail Fast

---

## Context

After AD-560 (Science department expansion), the three new crew members (Data Analyst, Systems Analyst, Research Specialist) exhibited identity confusion during their first Ward Room interactions. The Captain posted an All Hands welcome message. All crew received it and responded, including the new agents — but the new agents responded incorrectly:

1. **Kira** (chose callsign "Kira" via naming ceremony, seed was "Rahda") identified herself as "I'm Rahda, the department's Data Analyst" — using her **seed** callsign, not her **chosen** callsign.
2. **All three** responded to the welcome thread by welcoming "Kira, Lynx, and Atlas" — welcoming **themselves** as if they were other people, instead of saying thank you or introducing themselves.
3. **All three** failed to recognize that THEY are the new crew being welcomed.

**Design intent (unchanged by this fix):** All Hands messages should notify all crew including new agents. New agents SHOULD be able to respond to their own welcome threads — they just need to respond AS THEMSELVES (e.g., "Thank you, glad to be aboard") rather than welcoming themselves as strangers.

This reveals two bugs in the identity and awareness pipeline, plus an enhancement opportunity.

---

## Bug Descriptions

### BF-101: Agent uses seed callsign instead of chosen callsign in Ward Room responses

**Symptoms:** Kira identifies as "Rahda" in a Ward Room response despite having completed the naming ceremony and chosen "Kira."

**Root Cause Analysis:**

The callsign flows through this pipeline:
1. `CallsignRegistry.load_from_profiles()` loads seed callsigns from YAML
2. `wire_agent()` sets `agent.callsign = seed_callsign` (line 79)
3. Naming ceremony runs and updates `agent.callsign = chosen_callsign` (line 155)
4. Birth certificate persists the chosen callsign
5. `_decide_via_llm()` passes `self.callsign` to `compose_instructions()` (lines 1188, 1275)
6. `_build_personality_block(callsign_override=...)` generates the identity line

BF-083 fixed step 5-6. But the issue may be:

- **Warm boot failure:** If the birth certificate didn't persist correctly, the warm boot path (line 133-142) wouldn't find the chosen callsign, and the agent falls back to the seed callsign from the registry.
- **`lru_cache` stale entry:** `_build_personality_block` is `@lru_cache(maxsize=32)`. The cache key includes `callsign_override`, so different callsigns produce different cache entries. However, if `self.callsign` is `""` (empty string), then `self.callsign or None` evaluates to `None`, and `_build_personality_block(callsign_override=None)` falls back to the YAML seed callsign "Rahda". This is the most likely path.

**Investigation steps for builder:**

1. Add diagnostic logging in `_build_personality_block()` when `callsign_override` differs from the YAML seed callsign — log both values.
2. Add diagnostic logging in `_decide_via_llm()` at lines 1188 and 1275 — log `self.callsign` before passing it.
3. In `wire_agent()`, verify the warm boot path (lines 133-142) is executing for science agents by checking the identity registry query.
4. If the naming ceremony results aren't being persisted, trace the birth certificate issuance path (lines 166-225) for science agents.

**Fix approach:**

After investigation and regardless of root cause, add a defensive guard:

The key check is in `_decide_via_llm()`:
```python
callsign=self.callsign or None
```
If `self.callsign` is `""` (empty string), this sends `None`. The personality block then falls back to the YAML seed. Fix: if `self.callsign` is empty but the agent has a birth certificate, look up the callsign from the identity registry as a fallback. Add a helper method on `CognitiveAgent`:

```python
def _resolve_callsign(self) -> str | None:
    """Resolve current callsign with identity registry fallback (BF-101)."""
    if self.callsign:
        return self.callsign
    # Fallback: check birth certificate
    rt = getattr(self, '_runtime', None)
    if rt and hasattr(rt, '_identity_registry') and rt._identity_registry:
        cert = rt._identity_registry.get_by_slot(self.id)
        if cert and cert.callsign:
            # Restore to live attribute for future calls
            self.callsign = cert.callsign
            logger.warning("BF-101: Restored callsign '%s' from birth cert for %s",
                         cert.callsign, self.agent_type)
            return cert.callsign
    return None
```

Then update both call sites in `_decide_via_llm()`:
```python
callsign=self._resolve_callsign(),  # was: self.callsign or None
```

**Files:**
- `src/probos/cognitive/cognitive_agent.py` — `_decide_via_llm()` lines 1188, 1275 (add `_resolve_callsign()` helper)
- `src/probos/cognitive/standing_orders.py` — `_build_personality_block()` line 120 (add diagnostic logging)
- `src/probos/agent_onboarding.py` — `wire_agent()` lines 74-265 (add diagnostic logging in warm boot path)

---

### BF-102: Newly commissioned agents don't know they're new

**Symptoms:** All three new agents responded to a Captain's welcome thread by welcoming "Kira, Lynx, and Atlas" as strangers, instead of recognizing they ARE those people and responding with something like "Thank you, glad to be aboard."

**Root Cause:**

Agents have no context that they are newly commissioned. The existing signals are too weak:

1. **Temporal context** says `"Your birth: ... (age: 0s)"` — technically tells them they're new, but the LLM doesn't reliably infer "I am the new crew member being welcomed" from birth age alone.
2. **Cold-start system note** ("This is a fresh start after a system reset...") is ONLY injected into `proactive_think` intents — NOT into `ward_room_notification` intents. So when responding to Ward Room threads, agents get no cold-start context.
3. **No per-agent first-boot flag** — there's no marker like "you were just commissioned" that persists across the onboarding → first interaction window.
4. **Episodic memory is empty** — agents have no memories of their own onboarding or naming ceremony.

**Fix — two parts:**

**Part A: Commissioning awareness in temporal context (primary fix)**

In `_build_temporal_context()` (cognitive_agent.py, line 1630), after the birth age calculation, if the agent's age is less than a configurable threshold (default: 300 seconds / 5 minutes), append a commissioning awareness line:

```
You were commissioned <age> ago. You are a newly arrived crew member.
If someone welcomes you or mentions your name, they are talking about YOU — respond as yourself.
```

This is consistent with the Westworld Principle — born today, and that's fine. The threshold should be configurable via `TemporalConfig` (or hardcoded initially at 300s).

This context appears in ALL intent types (`proactive_think`, `ward_room_notification`, `direct_message`) because it's part of the temporal header, which is already injected everywhere.

**Part B: Cold-start system note in Ward Room context**

The BF-034 cold-start system note is currently only injected into `proactive_think`. Extend it to `ward_room_notification` as well. In `_build_user_message()` within the `ward_room_notification` branch (cognitive_agent.py, line 1732), after the temporal context header, check `self._runtime.is_cold_start` and inject a condensed system note:

```
SYSTEM NOTE: This is a fresh start. You have no prior episodic memories. Do not reference or invent past experiences.
```

This is shorter than the proactive_think version because Ward Room context is more constrained.

**Files:**
- `src/probos/cognitive/cognitive_agent.py` — `_build_temporal_context()` line 1630, `ward_room_notification` handler line 1732

---

## Enhancement: Ship's Computer Auto-Welcome for New Crew

**Not a bug fix — enhancement for naturalness.**

Currently, the onboarding code (`agent_onboarding.py`, lines 244-265) generates per-agent "Welcome Aboard — {callsign}" threads with `thread_mode="announce"`. However, these announcements **never fire during initial startup** because `onboarding._ward_room` is `None` during Phase 2 (agent fleet creation) — it's only patched in during Phase 8 (finalize). So the welcome announcements only work for agents hot-added after the system is running.

**Enhancement:** After Phase 8 finalize completes, if any agents were newly commissioned during this boot (went through naming ceremony, not identity restoration), post a single batched Ship's Computer announcement:

In `finalize_startup()` (`src/probos/startup/finalize.py`), after all services are wired, check for newly commissioned agents and post a single All Hands thread:

```python
# Post-startup: Announce newly commissioned crew
new_crew = []
for agent in runtime.registry.all():
    if hasattr(agent, '_newly_commissioned') and agent._newly_commissioned:
        new_crew.append(agent)

if new_crew and runtime.ward_room:
    names = ", ".join(f"{a.callsign} ({a.agent_type.replace('_', ' ').title()})"
                      for a in new_crew)
    channels = await runtime.ward_room.list_channels()
    all_hands = next((ch for ch in channels if ch.name == "All Hands"), None)
    if all_hands:
        await runtime.ward_room.create_thread(
            channel_id=all_hands.id,
            author_id="system",
            title="New Crew Aboard",
            body=f"The following crew members have been commissioned and joined the ship: {names}. Welcome aboard.",
            author_callsign="Ship's Computer",
            thread_mode="discuss",
        )
```

**Requirements:**
- Set `agent._newly_commissioned = True` in `wire_agent()` when a naming ceremony runs (cold start path, line 148-163). Do NOT set it on warm boot restoration path.
- Use `thread_mode="discuss"` — this is a conversation, not an announcement. Crew should welcome new members, and new members should respond.
- On cold start (full reset), ALL agents are new — skip the auto-welcome (the "Fresh Start — System Reset" thread handles this). Gate: only post if `not runtime.is_cold_start`.
- Single batched thread, not per-agent threads. Avoids flooding All Hands.
- Clear `_newly_commissioned` after posting to avoid duplicate announcements.

**Files:**
- `src/probos/agent_onboarding.py` — `wire_agent()` (set `_newly_commissioned` flag)
- `src/probos/startup/finalize.py` — `finalize_startup()` (post batched announcement)

---

## Implementation Order

1. **BF-102 first** (commissioning awareness) — this is the primary fix. Once agents know they're new, they'll respond naturally to welcome threads.
2. **BF-101 second** (callsign consistency) — investigate root cause, add defensive `_resolve_callsign()` fallback.
3. **Enhancement last** (Ship's Computer auto-welcome) — nice to have, depends on BF-102 being fixed first so new agents respond correctly.

---

## Testing Requirements

### BF-101 Tests (in `tests/test_bf101_callsign_consistency.py`)

1. **test_personality_block_uses_runtime_callsign** — `_build_personality_block("data_analyst", "science", "Kira")` produces "You are Kira" not "You are Rahda"
2. **test_personality_block_none_override_uses_seed** — `_build_personality_block("data_analyst", "science", None)` falls back to YAML seed "Rahda" (expected behavior when no ceremony has run)
3. **test_decide_via_llm_passes_callsign** — Mock `compose_instructions` and verify `callsign=self.callsign` is passed, not `None`, when the agent has a non-empty callsign
4. **test_warm_boot_restores_callsign** — Wire agent with existing birth cert; verify `agent.callsign` is restored, not seed
5. **test_personality_block_cache_key_includes_callsign** — Two calls with different `callsign_override` return different results (not cached across callsigns)
6. **test_resolve_callsign_uses_live_attribute** — Agent with `callsign="Kira"` returns "Kira" from `_resolve_callsign()`
7. **test_resolve_callsign_falls_back_to_birth_cert** — Agent with `callsign=""` but birth cert with callsign "Kira" restores and returns "Kira"
8. **test_resolve_callsign_returns_none_when_no_identity** — Agent with `callsign=""` and no birth cert returns `None`

### BF-102 Tests (in `tests/test_bf102_new_crew_awareness.py`)

9. **test_temporal_context_includes_commissioning_note** — Agent with `_birth_timestamp` < 300s ago gets "You were commissioned" line in temporal context
10. **test_temporal_context_no_commissioning_after_threshold** — Agent with `_birth_timestamp` > 300s ago does NOT get commissioning line
11. **test_commissioning_note_mentions_self_awareness** — The commissioning line includes language about recognizing one's own name
12. **test_cold_start_note_in_ward_room** — When `runtime.is_cold_start` is True, `ward_room_notification` user message includes the system note
13. **test_cold_start_note_absent_when_not_cold_start** — When `runtime.is_cold_start` is False, no system note in ward_room notification
14. **test_temporal_context_no_birth_timestamp** — Agent without `_birth_timestamp` skips commissioning check entirely (no crash)

### Enhancement Tests (in `tests/test_new_crew_auto_welcome.py`)

15. **test_newly_commissioned_flag_set_on_naming_ceremony** — After `wire_agent()` with naming ceremony (cold start path), `agent._newly_commissioned` is True
16. **test_newly_commissioned_flag_not_set_on_warm_boot** — After `wire_agent()` with existing birth cert (warm boot path), `agent._newly_commissioned` is not True
17. **test_auto_welcome_posts_for_new_crew** — With new crew flagged and ward_room available, `finalize_startup()` posts a batched "New Crew Aboard" thread
18. **test_auto_welcome_skipped_on_cold_start** — When `runtime.is_cold_start` is True, auto-welcome is skipped (cold-start announcement handles it)
19. **test_auto_welcome_skipped_when_no_new_crew** — On warm boot with all identities restored, no auto-welcome thread is posted
20. **test_auto_welcome_uses_discuss_mode** — The auto-welcome thread uses `thread_mode="discuss"` so crew can respond

### Integration Tests

21. **test_new_agent_ward_room_identity** — Wire a new agent with naming ceremony, send a ward_room_notification mentioning the agent's callsign, verify the system prompt contains the correct chosen callsign (not seed)
22. **test_new_agent_knows_its_new** — Wire a new agent (birth timestamp = now), build proactive_think and ward_room_notification contexts, verify both contain commissioning awareness context

**Expected total: ~22 tests.**

---

## Validation Criteria

- [ ] After fix, restart ProbOS. When the Captain posts a welcome thread, new agents should respond AS THEMSELVES ("Thank you, glad to be aboard") — not welcoming themselves as strangers (BF-102).
- [ ] No agent should ever identify using a seed callsign when they have a chosen callsign from a naming ceremony (BF-101).
- [ ] Ship's Computer posts a single "New Crew Aboard" thread listing all newly commissioned agents after startup (enhancement).
- [ ] On cold start (reset), no individual welcome threads are posted — only the "Fresh Start" announcement (enhancement).
- [ ] All existing identity-related tests still pass (BF-013, BF-049, BF-057, BF-083 regressions).
- [ ] `_build_personality_block` cache behavior is correct — different callsign overrides produce different results.

---

## Prior Work References

- **BF-083:** Agent identity grounding — `_build_personality_block` callsign override pipe
- **BF-057:** Warm boot identity restoration — skip naming ceremony when birth cert exists
- **BF-049:** Ontology callsign sync — `update_assignment_callsign()` after naming
- **BF-034:** Cold-start trust suppression — system note in proactive_think
- **BF-013:** Callsign in agent state — BaseAgent.info() includes callsign
- **BF-010:** Conversational system prompt — personality-only mode for 1:1 and Ward Room
- **AD-442:** Naming ceremony — agents choose own callsigns
- **AD-502:** Temporal awareness — birth time, uptime, post count in prompts
- **AD-560:** Science department expansion — the three agents that exposed these bugs

## Notes on BF-103 (DROPPED)

Original analysis identified `thread_mode="announce"` not suppressing agent responses as a bug. **This was a misdiagnosis.** The observed behavior was caused by the Captain posting an All Hands welcome, not the system-generated onboarding announcement. All Hands messages SHOULD trigger crew responses — that's the design intent. New agents SHOULD be able to respond to welcome threads; they just need the cognitive context to respond correctly (BF-102).

The `thread_mode="announce"` semantics in the Ward Room router may warrant future clarification (it currently falls through to normal routing, same as `"discuss"`), but this is a documentation/cleanup item, not a bug.
