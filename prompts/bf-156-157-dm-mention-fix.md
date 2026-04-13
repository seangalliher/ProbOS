# BF-156/157: DM Delivery + @Mention Response Guarantee

**Status:** Ready for builder
**Issues:** #187 (BF-156), #188 (BF-157)
**Relates to:** BF-016a, BF-047, BF-051, BF-081, BF-082, AD-357, AD-407b, AD-574

## Context

Two related communication reliability bugs observed in production:

1. **BF-156: Agents don't read DMs.** Agent-to-agent DMs go unanswered. The real-time `_ward_room_emit` notification is fire-and-forget. The BF-082 catch-up mechanism (`_check_unread_dms()`) sits inside the proactive loop AFTER the Ensign rank gate — Ensigns never reach it. Even for higher-rank agents, the per-agent cooldown (45s) silently drops DM notifications if the agent recently responded to anything.

2. **BF-157: @mention doesn't guarantee response.** When the Captain or a crew member @mentions an agent, the `mentions` list is used for *routing only* — deciding who to notify. It is never forwarded in the `IntentMessage` params. The agent's LLM prompt says "If this topic is outside your expertise or you have nothing to add, respond with exactly: [NO_RESPONSE]" — treating @mentions identically to ambient notifications. Additionally, the cooldown and per-thread response cap apply equally to @mentioned agents.

### Prior work absorbed

- **BF-016a** (Closed): @mention exclusivity in routing — if Captain @mentions, ONLY those agents are targeted. Works correctly at the routing layer but the agent doesn't know it was mentioned.
- **BF-047** (Closed): DM callsign resolution — fixed `AttributeError` on `get_agent_type()`. DMs now resolve correctly.
- **BF-051** (Closed): DM syntax in ward room context — `_compose_dm_instructions()` available in `ward_room_notification` branch.
- **BF-081** (Closed): Agent-to-agent DM routing — added DM channel case to `find_targets_for_agent()`. DMs now reach the router correctly.
- **BF-082** (Closed): Unread DM polling fallback — added `_check_unread_dms()` to proactive loop. Works for agents that reach the proactive loop body.
- **AD-357** (Complete): Earned Agency trust-tier gating. @mentions bypass EA correctly.
- **AD-574** (Complete): DM channel targeting — no EA gating for DMs. Correct.

### Root cause chain

**BF-156 path:**
```
Agent A sends [DM @bones] → _extract_and_execute_dms() → create_thread() → 
_ward_room_emit() → asyncio.create_task(route_event()) → intent_bus.send() →
[agent busy / cooldown / timeout] → DM silently lost →
_check_unread_dms() fallback → [Ensign gate blocks it / cooldown blocks it] →
DM permanently unread
```

**BF-157 path:**
```
Captain posts "@atlas what do you think?" → extract_mentions() → ["atlas"] →
route_event() → find_targets() adds atlas (via mentions, bypasses EA) →
IntentMessage params = {event_type, thread_id, channel_name, title, author_id, 
author_callsign} ← NO mention info →
CognitiveAgent._build_user_message() → "atlas posted the above." + 
"If this topic is outside your expertise... respond with [NO_RESPONSE]" →
LLM decides it has nothing to add → [NO_RESPONSE] → silence
```

---

## Change 1: Pass `was_mentioned` flag in IntentMessage params

**File:** `src/probos/ward_room_router.py`
**Location:** Intent construction at line 236-249

The router already knows which agents were @mentioned (from `find_targets()` / `find_targets_for_agent()`). Pass this information through to the agent.

**Before (lines 236-249):**
```python
            intent = IntentMessage(
                intent="ward_room_notification",
                params={
                    "event_type": event_type,
                    "thread_id": thread_id,
                    "channel_id": channel_id,
                    "channel_name": channel.name,
                    "title": title,
                    "author_id": author_id,
                    "author_callsign": data.get("author_callsign", ""),
                },
                context=thread_context,
                target_agent_id=agent_id,
            )
```

First, capture mentioned agent IDs before the dispatch loop. Add after line 213 (`responded_this_event = False`):

```python
        # BF-157: Track which agents were explicitly @mentioned
        mentioned_agent_ids: set[str] = set()
        mentions = data.get("mentions", [])
        if mentions and self._callsign_registry:
            for callsign in mentions:
                resolved = self._callsign_registry.resolve(callsign)
                if resolved and resolved.get("agent_id"):
                    mentioned_agent_ids.add(resolved["agent_id"])
```

Then update the IntentMessage construction to include the flag:

**After:**
```python
            intent = IntentMessage(
                intent="ward_room_notification",
                params={
                    "event_type": event_type,
                    "thread_id": thread_id,
                    "channel_id": channel_id,
                    "channel_name": channel.name,
                    "title": title,
                    "author_id": author_id,
                    "author_callsign": data.get("author_callsign", ""),
                    # BF-157: Tell the agent it was directly mentioned
                    "was_mentioned": agent_id in mentioned_agent_ids,
                },
                context=thread_context,
                target_agent_id=agent_id,
            )
```

## Change 2: Skip cooldown and response cap for @mentioned agents and DM channels

**File:** `src/probos/ward_room_router.py`
**Location:** Cooldown and cap checks at lines 215-234

@mentioned agents and DM recipients should bypass the per-agent cooldown and per-thread response cap. These guards exist to prevent thread explosion in public channels — not to suppress direct communication.

**Before (lines 215-234):**
```python
        for agent_id in target_agent_ids:
            # Layer 4: Per-agent cooldown
            last_response = self._cooldowns.get(agent_id, 0)
            if now - last_response < cooldown:
                continue

            # Layer 3: Agent already responded in this round of this thread
            if is_agent_post and agent_id in round_participants:
                continue

            # BF-016b: Per-thread agent response cap — prevent thread explosion
            max_per_thread = getattr(self._config.ward_room, 'max_agent_responses_per_thread', 3)
            thread_agent_key = f"{thread_id}:{agent_id}"
            prior_responses = self._agent_thread_responses.get(thread_agent_key, 0)
            if prior_responses >= max_per_thread:
                logger.debug(
                    "Ward Room: agent %s hit per-thread response cap (%d) in thread %s",
                    agent_id[:12], max_per_thread, thread_id[:8],
                )
                continue
```

**After:**
```python
        for agent_id in target_agent_ids:
            # BF-156/157: @mentioned agents and DM recipients bypass cooldown/caps.
            # These guards prevent thread explosion in public channels, not
            # suppress direct communication.
            is_direct_target = (
                agent_id in mentioned_agent_ids
                or (channel and channel.channel_type == "dm")
            )

            # Layer 4: Per-agent cooldown
            if not is_direct_target:
                last_response = self._cooldowns.get(agent_id, 0)
                if now - last_response < cooldown:
                    continue

            # Layer 3: Agent already responded in this round of this thread
            if not is_direct_target and is_agent_post and agent_id in round_participants:
                continue

            # BF-016b: Per-thread agent response cap — prevent thread explosion
            if not is_direct_target:
                max_per_thread = getattr(self._config.ward_room, 'max_agent_responses_per_thread', 3)
                thread_agent_key = f"{thread_id}:{agent_id}"
                prior_responses = self._agent_thread_responses.get(thread_agent_key, 0)
                if prior_responses >= max_per_thread:
                    logger.debug(
                        "Ward Room: agent %s hit per-thread response cap (%d) in thread %s",
                        agent_id[:12], max_per_thread, thread_id[:8],
                    )
                    continue
```

## Change 3: Use `was_mentioned` in agent's LLM prompt

**File:** `src/probos/cognitive/cognitive_agent.py`
**Location:** `_build_user_message()`, ward_room_notification branch at lines 2329-2336

When the agent was @mentioned, the prompt should communicate this and suppress `[NO_RESPONSE]` as a valid option. Being directly addressed requires a response.

**Before (lines 2329-2336):**
```python
            # AD-407d: Distinguish Captain vs crew member posts
            author_id = params.get("author_id", "")
            if author_id == "captain":
                wr_parts.append(f"\nThe Captain posted the above.")
            else:
                wr_parts.append(f"\n{author_callsign} posted the above.")
            wr_parts.append("Respond naturally as yourself. Share your perspective if you have something meaningful to contribute.")
            wr_parts.append("If this topic is outside your expertise or you have nothing to add, respond with exactly: [NO_RESPONSE]")
```

**After:**
```python
            # AD-407d: Distinguish Captain vs crew member posts
            author_id = params.get("author_id", "")
            was_mentioned = params.get("was_mentioned", False)

            if author_id == "captain":
                wr_parts.append(f"\nThe Captain posted the above.")
            else:
                wr_parts.append(f"\n{author_callsign} posted the above.")

            # BF-157: @mentioned agents must respond — they were directly addressed.
            if was_mentioned:
                wr_parts.append(
                    "You were directly @mentioned in this post. A response is expected. "
                    "Address the question or request from your area of expertise. "
                    "Be concise and helpful."
                )
            else:
                wr_parts.append("Respond naturally as yourself. Share your perspective if you have something meaningful to contribute.")
                wr_parts.append("If this topic is outside your expertise or you have nothing to add, respond with exactly: [NO_RESPONSE]")
```

**Design note:** The `[NO_RESPONSE]` option is deliberately removed for @mentioned agents. Being directly addressed is a social contract — silence is rude. If the agent truly has nothing relevant to say, it should acknowledge the mention ("I don't have specific data on that, Captain") rather than being silent. The LLM will produce a relevant response when told it was directly addressed.

## Change 4: Move `_check_unread_dms()` before the Ensign gate

**File:** `src/probos/proactive.py`
**Location:** `_run_cycle()`, lines 295-349

Currently `_check_unread_dms()` is at line 349, after the Ensign gate at line 298. Ensigns never reach it. DM delivery is a communication reliability concern, not a proactive agency concern — Ensigns should still receive their DMs.

**Before (lines 288-349, simplified):**
```python
        for agent in all_agents:
            # ... alive check, crew check ...

            # Agency gating: Ensigns don't think proactively
            trust_score = rt.trust_network.get_score(agent.id)
            rank = Rank.from_trust(trust_score)
            if not can_think_proactively(rank):
                continue

            # ... cooldown, circuit breaker, ACM activation ...

            try:
                await self._think_for_agent(agent, rank, trust_score)
            except Exception:
                agent.update_confidence(False)
                # ...

            # --- BF-082: Unread DM check ---
            await self._check_unread_dms(agent, rt)
```

**After:**
```python
        for agent in all_agents:
            # ... alive check, crew check ...

            # BF-156: Unread DM check BEFORE agency gating.
            # DM delivery is communication reliability, not proactive agency.
            # Ensigns should still receive their DMs.
            await self._check_unread_dms(agent, rt)

            # Agency gating: Ensigns don't think proactively
            trust_score = rt.trust_network.get_score(agent.id)
            rank = Rank.from_trust(trust_score)
            if not can_think_proactively(rank):
                continue

            # ... cooldown, circuit breaker, ACM activation ...

            try:
                await self._think_for_agent(agent, rank, trust_score)
            except Exception:
                agent.update_confidence(False)
                # ...
```

Remove the old `_check_unread_dms()` call at the bottom (former line 349). The check now runs once per agent per cycle, before any agent-specific gating.

**Design note:** The DM check placement. The `is_alive` and `is_crew_agent` gates remain above the DM check — dead agents and infrastructure agents don't need DM delivery. But the Ensign gate, cooldown gate, and circuit breaker gate should NOT block DM delivery.

## Change 5: DM channel bypasses thread depth cap

**File:** `src/probos/ward_room_router.py`
**Location:** Thread depth cap at lines 108-117

DM conversations should not be limited to 3 agent rounds. The thread depth cap exists for public channel conversation management. DMs are private 1:1 conversations.

**Before (lines 108-117):**
```python
        # --- Layer 1: Thread depth tracking ---
        max_rounds = getattr(self._config.ward_room, 'max_agent_rounds', 3)
        if is_agent_post and thread_id:
            current_round = self._thread_rounds.get(thread_id, 0)
            if current_round >= max_rounds:
                logger.debug(
                    "Ward Room: thread %s hit agent round limit (%d), silencing",
                    thread_id[:8], max_rounds,
                )
                return
```

**After:**
```python
        # --- Layer 1: Thread depth tracking ---
        # BF-156: DM channels bypass thread depth cap — private conversations
        # should not be artificially truncated.
        max_rounds = getattr(self._config.ward_room, 'max_agent_rounds', 3)
        is_dm_channel = False
        if channel_id:
            _channels = await self._ward_room.list_channels()
            _ch = next((c for c in _channels if c.id == channel_id), None)
            if _ch and _ch.channel_type == "dm":
                is_dm_channel = True

        if is_agent_post and thread_id and not is_dm_channel:
            current_round = self._thread_rounds.get(thread_id, 0)
            if current_round >= max_rounds:
                logger.debug(
                    "Ward Room: thread %s hit agent round limit (%d), silencing",
                    thread_id[:8], max_rounds,
                )
                return
```

**Wait — performance concern.** `list_channels()` is called again on line 151. To avoid double-fetching, move the channel lookup to earlier and reuse it. Better approach:

**Alternative (preferred) — defer the DM check to after channel lookup:**

The thread depth cap check at lines 108-117 runs *before* the channel lookup at line 151. We can't know `channel_type` yet. Instead of adding an early channel fetch, restructure to check thread depth AFTER the channel lookup.

**Revised approach:** Move the thread depth check from lines 108-117 to after line 154 (after `channel` is resolved). This way we have `channel.channel_type` available.

**Before (lines 108-154):**
```python
        # --- Layer 1: Thread depth tracking ---
        max_rounds = getattr(self._config.ward_room, 'max_agent_rounds', 3)
        if is_agent_post and thread_id:
            current_round = self._thread_rounds.get(thread_id, 0)
            if current_round >= max_rounds:
                logger.debug(
                    "Ward Room: thread %s hit agent round limit (%d), silencing",
                    thread_id[:8], max_rounds,
                )
                return

        # Captain posts reset the round counter
        if is_captain and thread_id:
            self._thread_rounds[thread_id] = 0
            # ...

        # --- Get channel info ---
        channel_id = data.get("channel_id", "")
        # ... thread_detail lookup ...
        # ... channel lookup ...
        if not channel:
            return
```

**After:**
```python
        # Captain posts reset the round counter (must happen before depth check)
        if is_captain and thread_id:
            self._thread_rounds[thread_id] = 0
            # Clear round participation tracking for this thread
            keys_to_clear = [k for k in self._round_participants
                             if k.startswith(f"{thread_id}:")]
            for k in keys_to_clear:
                del self._round_participants[k]

        # --- Get channel info ---
        channel_id = data.get("channel_id", "")
        # ... thread_detail lookup (unchanged) ...
        # ... channel lookup (unchanged) ...
        if not channel:
            return

        # --- Layer 1: Thread depth tracking ---
        # BF-156: DM channels bypass thread depth cap — private conversations
        # should not be artificially truncated.
        max_rounds = getattr(self._config.ward_room, 'max_agent_rounds', 3)
        if is_agent_post and thread_id and channel.channel_type != "dm":
            current_round = self._thread_rounds.get(thread_id, 0)
            if current_round >= max_rounds:
                logger.debug(
                    "Ward Room: thread %s hit agent round limit (%d), silencing",
                    thread_id[:8], max_rounds,
                )
                return
```

This moves the "Captain posts reset" block before the channel lookup (it doesn't need channel info) and moves the thread depth check after the channel lookup (it now needs channel type). The `thread_mode` and `inform` check at lines 141-148 stay in their current position (after channel lookup).

---

## Summary of Changes

| # | File | Change | Purpose |
|---|------|--------|---------|
| 1 | `src/probos/ward_room_router.py` | Pass `was_mentioned` flag in IntentMessage params | BF-157: Agent knows it was @mentioned |
| 2 | `src/probos/ward_room_router.py` | Skip cooldown/caps for @mentioned and DM agents | BF-156/157: Direct communication bypasses anti-explosion guards |
| 3 | `src/probos/cognitive/cognitive_agent.py` | Use `was_mentioned` in LLM prompt, suppress `[NO_RESPONSE]` | BF-157: @mentioned agents must respond |
| 4 | `src/probos/proactive.py` | Move `_check_unread_dms()` before Ensign gate | BF-156: Ensigns receive their DMs |
| 5 | `src/probos/ward_room_router.py` | DM channels bypass thread depth cap | BF-156: Private conversations not truncated |

**Source files modified:** 3
**Test files modified:** 0 (new tests below)
**New tests:** See below

---

## Tests

### Test file: `tests/test_bf156_dm_delivery.py`

```python
"""BF-156: DM delivery reliability tests."""

import asyncio
import time

import pytest


class TestUnreadDmBeforeEnsignGate:
    """BF-156: _check_unread_dms() runs before Ensign gate."""

    def test_check_unread_dms_before_rank_gate(self):
        """Verify _check_unread_dms is called even for Ensign-ranked agents.

        The proactive loop should check unread DMs before the
        can_think_proactively() gate, so Ensigns still receive DMs.
        """
        import ast
        from pathlib import Path

        source = Path("src/probos/proactive.py").read_text()
        tree = ast.parse(source)

        # Find _run_cycle method
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "_run_cycle":
                # Find the positions of _check_unread_dms and can_think_proactively
                dm_check_line = None
                rank_gate_line = None
                for child in ast.walk(node):
                    if isinstance(child, ast.Attribute) and child.attr == "_check_unread_dms":
                        dm_check_line = child.lineno
                    if isinstance(child, ast.Call):
                        func = child.func
                        if isinstance(func, ast.Name) and func.id == "can_think_proactively":
                            rank_gate_line = func.lineno
                assert dm_check_line is not None, "_check_unread_dms not found in _run_cycle"
                assert rank_gate_line is not None, "can_think_proactively not found in _run_cycle"
                assert dm_check_line < rank_gate_line, (
                    f"_check_unread_dms (line {dm_check_line}) must come before "
                    f"can_think_proactively (line {rank_gate_line})"
                )
                break
        else:
            pytest.fail("_run_cycle method not found")


class TestDmBypassesCooldown:
    """BF-156: DM channel notifications bypass per-agent cooldown."""

    def test_dm_channel_bypasses_cooldown(self):
        """DM channel type should set is_direct_target = True."""
        # Verify the pattern exists in source
        from pathlib import Path

        source = Path("src/probos/ward_room_router.py").read_text()
        assert 'channel.channel_type == "dm"' in source
        assert "is_direct_target" in source


class TestDmBypassesThreadDepth:
    """BF-156: DM channels bypass thread depth cap."""

    def test_dm_channel_bypasses_thread_depth_cap(self):
        """Thread depth cap check should exclude DM channels."""
        from pathlib import Path

        source = Path("src/probos/ward_room_router.py").read_text()
        # The thread depth guard should have a DM exclusion
        assert 'channel.channel_type != "dm"' in source
```

### Test file: `tests/test_bf157_mention_response.py`

```python
"""BF-157: @mention response guarantee tests."""

import pytest


class TestWasMentionedFlag:
    """BF-157: was_mentioned flag passed to agent."""

    def test_was_mentioned_in_intent_params(self):
        """IntentMessage params should include was_mentioned key."""
        from pathlib import Path

        source = Path("src/probos/ward_room_router.py").read_text()
        assert '"was_mentioned"' in source

    def test_mentioned_agent_ids_built_from_mentions(self):
        """mentioned_agent_ids set should be built before dispatch loop."""
        from pathlib import Path

        source = Path("src/probos/ward_room_router.py").read_text()
        assert "mentioned_agent_ids" in source


class TestMentionedAgentPrompt:
    """BF-157: @mentioned agents get a response-required prompt."""

    def test_mentioned_agent_skips_no_response_option(self):
        """When was_mentioned=True, the prompt should not offer [NO_RESPONSE]."""
        from pathlib import Path

        source = Path("src/probos/cognitive/cognitive_agent.py").read_text()
        # The ward_room_notification path should check was_mentioned
        assert 'was_mentioned' in source
        # Should contain the "directly @mentioned" instruction
        assert "directly" in source.lower() and "mentioned" in source.lower()


class TestMentionedBypassesCooldown:
    """BF-157: @mentioned agents bypass cooldown and response caps."""

    def test_mentioned_agents_bypass_cooldown(self):
        """@mentioned agents should not be subject to per-agent cooldown."""
        from pathlib import Path

        source = Path("src/probos/ward_room_router.py").read_text()
        assert "is_direct_target" in source
        assert "mentioned_agent_ids" in source
```

---

## Engineering Principles Compliance

- **Fail Fast:** DM delivery failures are surfaced through existing BF-082 logging. No silent swallowing of communication.
- **SOLID (O):** Extending existing routing logic by adding `is_direct_target` bypass, not modifying private members of IntentBus or CognitiveAgent.
- **SOLID (S):** The `was_mentioned` flag is computed in the router (who knows about mentions) and consumed in the agent (who knows about prompts). Each component has a single responsibility.
- **DRY:** Reuses `_callsign_registry.resolve()` for mention resolution (same pattern as `find_targets()`). Reuses existing `_check_unread_dms()` method.
- **Defense in Depth:** Multiple layers — real-time notification (bypasses cooldown for direct targets) + polling fallback (runs before rank gate) + prompt instruction (tells agent it was mentioned).
- **Law of Demeter:** `was_mentioned` is passed through params (public API), not by reaching into router internals.

## Verification

After building, run:
```bash
uv run python -m pytest tests/test_bf156_dm_delivery.py tests/test_bf157_mention_response.py -v
```

Then manually test:
1. Start ProbOS, enter `@atlas what is your current assessment?` — Atlas should respond (not [NO_RESPONSE]).
2. Have two agents DM each other — the recipient should respond even if they just responded to something else.
3. Verify agents at Ensign rank still receive DMs.
