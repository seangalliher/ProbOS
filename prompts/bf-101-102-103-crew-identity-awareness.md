# Build Prompt: BF-101 / BF-102 / BF-103 — Crew Identity & Self-Awareness Fixes

**Ticket:** BF-101, BF-102, BF-103
**Priority:** High (crew identity is a core ProbOS thesis)
**Scope:** Agent onboarding, Ward Room routing, cognitive context
**Principles Compliance:** Westworld Principle, Sovereign Agent Identity, Fail Fast

---

## Context

After AD-560 (Science department expansion), the three new crew members (Data Analyst, Systems Analyst, Research Specialist) exhibited identity confusion during their first Ward Room interactions:

1. **Kira** (chose callsign "Kira" via naming ceremony, seed was "Rahda") identified herself as "I'm Rahda, the department's Data Analyst" — using her **seed** callsign, not her **chosen** callsign.
2. **All three** responded to a welcome thread by welcoming "Kira, Lynx, and Atlas" — welcoming **themselves** as if they were other people.
3. **All three** failed to recognize that THEY are the new crew being welcomed.

This reveals three distinct bugs in the identity and awareness pipeline.

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
- **`lru_cache` stale entry:** `_build_personality_block` is `@lru_cache(maxsize=32)`. If ANY code path calls it with the seed callsign before the naming ceremony updates, the cache holds the stale entry. Although the cache key includes `callsign_override`, if the first call passes `callsign_override=None` (because `self.callsign or None` evaluates to `None` when callsign is `""`), the personality block renders the YAML seed. Subsequent calls with `callsign_override="Kira"` would be cache misses and render correctly — but if there's a code path that still passes `None`, it gets the cached seed version.

**Investigation steps for builder:**

1. Add diagnostic logging in `_build_personality_block()` when `callsign_override` differs from the YAML seed callsign — log both values.
2. Add diagnostic logging in `_decide_via_llm()` at lines 1188 and 1275 — log `self.callsign` before passing it.
3. In `wire_agent()`, verify the warm boot path (lines 133-142) is executing for science agents by checking the identity registry query.
4. If the naming ceremony results aren't being persisted, trace the birth certificate issuance path (lines 166-225) for science agents.

**Fix approach:**

After investigation and regardless of root cause, add a defensive guard:

In `compose_instructions()` (standing_orders.py, line 194), if `callsign` is provided, call `_build_personality_block.cache_clear()` would be too aggressive. Instead, the fix should ensure `_build_personality_block` is NEVER called with `callsign_override=None` when a runtime callsign exists.

The key check is in `_decide_via_llm()`:
```python
callsign=self.callsign or None
```
If `self.callsign` is `""` (empty string), this sends `None`. The personality block then falls back to the YAML seed. Fix: if `self.callsign` is empty but the agent has a birth certificate, look up the callsign from the identity registry as a fallback.

**Files:**
- `src/probos/cognitive/cognitive_agent.py` — `_decide_via_llm()` lines 1188, 1275
- `src/probos/cognitive/standing_orders.py` — `_build_personality_block()` line 120
- `src/probos/agent_onboarding.py` — `wire_agent()` lines 74-265

---

### BF-102: Newly commissioned agents don't know they're new

**Symptoms:** All three new agents responded to a welcome thread about themselves by welcoming "Kira, Lynx, and Atlas" — not recognizing that those names refer to themselves.

**Root Cause:**

Agents have no context that they are newly commissioned. The existing signals are too weak:

1. **Temporal context** says `"Your birth: ... (age: 0s)"` — technically tells them they're new, but the LLM doesn't reliably infer "I am the new crew member" from "age: 0s."
2. **Cold-start system note** ("This is a fresh start after a system reset...") is ONLY injected into `proactive_think` intents — NOT into `ward_room_notification` intents. So when responding to Ward Room threads, agents get no cold-start context.
3. **No per-agent first-boot flag** — there's no marker like "you were just commissioned" that persists across the onboarding → first interaction window.
4. **Episodic memory is empty** — agents have no memories of their own onboarding or naming ceremony.

**Fix — two parts:**

**Part A: New-crew temporal context (primary fix)**

In `_build_temporal_context()` (cognitive_agent.py, line 1630), after the birth age calculation, if the agent's age is less than a configurable threshold (default: 300 seconds / 5 minutes), append a commissioning awareness line:

```
You were commissioned <age> ago. You are a new crew member — this is your first time aboard.
If someone welcomes you, they are welcoming YOU. Respond as the person being welcomed.
```

This is consistent with the Westworld Principle — born today, and that's fine. The threshold should be configurable via `TemporalConfig` (or hardcoded initially at 300s).

**Part B: Cold-start system note in Ward Room context**

The BF-034 cold-start system note is currently only injected into `proactive_think`. Extend it to `ward_room_notification` as well. In `_build_ward_room_user_message()` (cognitive_agent.py, line 1732), after the temporal context header, check `self._runtime.is_cold_start` and inject a condensed system note:

```
SYSTEM NOTE: This is a fresh start. You have no prior episodic memories. Do not reference or invent past experiences.
```

This is shorter than the proactive_think version because Ward Room context is more constrained.

**Files:**
- `src/probos/cognitive/cognitive_agent.py` — `_build_temporal_context()` line 1630, ward_room_notification handler line 1732

---

### BF-103: `thread_mode="announce"` does not suppress responses

**Symptoms:** The onboarding welcome announcement (`"Welcome Aboard — {callsign}"`) triggers crew responses. The intent was informational — announce the new crew member without soliciting responses.

**Root Cause:**

The Ward Room router (ward_room_router.py) only recognizes `thread_mode="inform"` as a silenced mode (line 147):
```python
if thread_mode == "inform":
    return
```

`thread_mode="announce"` is not handled — it falls through to normal routing and triggers crew notifications. Additionally, `max_responders=0` means "unlimited" (not zero), and the responder cap only applies to `thread_mode="discuss"` (line 178).

The onboarding code (agent_onboarding.py, lines 255-262) uses:
```python
thread_mode="announce",
max_responders=0,
```
This was clearly intended to mean "post an announcement, don't solicit responses." But neither mechanism achieves that.

**Fix:**

Add `"announce"` to the suppressed thread modes in the Ward Room router:

```python
# AD-424: INFORM and ANNOUNCE threads — no agent notification
if thread_mode in ("inform", "announce"):
    return
```

Announce threads are visible on the Ward Room (crew can read them in HXI), but they don't trigger agent notification dispatch. This is the correct semantic: announcements are for reading, not for responding to.

Review all uses of `thread_mode="announce"` in the codebase to confirm this semantic is correct:
- `agent_onboarding.py` — welcome aboard announcements (should be read-only)
- `startup/dreaming.py` — cold-start announcement (should be read-only)
- `startup/finalize.py` — startup announcement (should be read-only)
- Any other occurrences

**Files:**
- `src/probos/ward_room_router.py` — line 147

---

## Implementation Order

1. **BF-103 first** (announce thread suppression) — this prevents the cascade. Simplest fix, highest impact. Without this, even with perfect identity, agents will still respond to their own welcome announcements.
2. **BF-102 second** (new-crew awareness) — ensures agents know they're new when they DO interact.
3. **BF-101 last** (callsign consistency) — investigate and fix the seed callsign regression.

---

## Testing Requirements

### BF-101 Tests (in `tests/test_bf101_callsign_consistency.py`)

1. **test_personality_block_uses_runtime_callsign** — `_build_personality_block("data_analyst", "science", "Kira")` produces "You are Kira" not "You are Rahda"
2. **test_personality_block_none_override_uses_seed** — `_build_personality_block("data_analyst", "science", None)` falls back to YAML seed "Rahda" (expected behavior when no ceremony has run)
3. **test_decide_via_llm_passes_callsign** — Mock `compose_instructions` and verify `callsign=self.callsign` is passed, not `None`, when the agent has a non-empty callsign
4. **test_warm_boot_restores_callsign** — Wire agent with existing birth cert; verify `agent.callsign` is restored, not seed
5. **test_personality_block_cache_key_includes_callsign** — Two calls with different `callsign_override` return different results (not cached across callsigns)

### BF-102 Tests (in `tests/test_bf102_new_crew_awareness.py`)

6. **test_temporal_context_includes_commissioning_note** — Agent with `_birth_timestamp` < 300s ago gets "You were commissioned" line in temporal context
7. **test_temporal_context_no_commissioning_after_threshold** — Agent with `_birth_timestamp` > 300s ago does NOT get commissioning line
8. **test_cold_start_note_in_ward_room** — When `runtime.is_cold_start` is True, `ward_room_notification` user message includes the system note
9. **test_cold_start_note_absent_when_not_cold_start** — When `runtime.is_cold_start` is False, no system note in ward_room notification
10. **test_temporal_context_no_birth_timestamp** — Agent without `_birth_timestamp` skips commissioning check entirely (no crash)

### BF-103 Tests (in `tests/test_bf103_announce_suppression.py`)

11. **test_announce_thread_suppresses_notifications** — Create a thread with `thread_mode="announce"` and verify the router returns without dispatching any agent notifications
12. **test_inform_thread_still_suppressed** — Existing behavior: `thread_mode="inform"` still suppressed (regression guard)
13. **test_discuss_thread_still_routes** — Existing behavior: `thread_mode="discuss"` still routes normally
14. **test_onboarding_welcome_is_announce** — Verify `agent_onboarding.py` creates welcome threads with `thread_mode="announce"` (documentation test)
15. **test_cold_start_announcement_is_announce** — Verify `startup/dreaming.py` creates cold-start threads with `thread_mode="announce"` (documentation test)

### Integration Tests

16. **test_new_agent_ward_room_identity** — Wire a new agent with naming ceremony, send a ward_room_notification mentioning the agent's callsign, verify the system prompt contains the correct chosen callsign (not seed)
17. **test_new_agent_knows_its_new** — Wire a new agent (birth timestamp = now), build proactive_think and ward_room_notification contexts, verify both contain commissioning awareness context

**Expected total: ~17 tests.**

---

## Validation Criteria

- [ ] After fix, restart ProbOS. New agents should NOT respond to their own "Welcome Aboard" threads (BF-103).
- [ ] If a crew member organically welcomes them in a separate thread, new agents should recognize themselves and respond appropriately ("Thank you, I'm new here...") rather than welcoming themselves (BF-102).
- [ ] No agent should ever identify using a seed callsign when they have a chosen callsign from a naming ceremony (BF-101).
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
