# AD-649: Communication Context Awareness for Cognitive Chain — Build Prompt

**AD:** 649  
**Issue:** #293  
**Parent:** AD-632 (Cognitive Sub-Tasks)  
**Related:** AD-639 (trust-band tuning), AD-645 (composition briefs), AD-646/646b (cognitive baseline/parity)  
**Scope:** ~80 lines across 2 files. Zero new modules.

---

## Problem

The cognitive communication chain (QUERY → ANALYZE → COMPOSE) produces formal, clinical output regardless of communication context. The same agent responding to the same question produces natural, personality-rich responses through the one-shot path but rigid, report-style output through the chain.

**Root cause (diagnosed with crew input):** COMPOSE receives no communication context — channel type, audience, register expectations. It defaults to the most formal register ("safer professionally") and strips the reasoning process that makes communication useful. ANALYZE's composition brief asks for a `tone` field but provides no explicit data about the communication context for the LLM to base it on.

**Evidence:** Two agents (Ezri/Counselor, Nova/Operations) independently diagnosed the same problem when shown their chain vs one-shot output:
- Ezri: "The chain path might be defaulting to Ward Room mode even in our private conversation"
- Nova: "It's like I was reading from a crisis management checklist rather than having a conversation"
- Both identified the fix: explicit context markers for communication type

**Design principle (LLM Independence):** The one-shot path works well because the LLM natively handles audience adaptation, personality, and register shifting. But this is a fragile dependency on the current model's emergent capability. The chain must encode desired behavior prescriptively so it works across LLMs. The chain should produce good output with a less capable model and excellent output with a more capable one.

---

## What Already Exists

- `channel_name` is available in `observation["params"]` for `ward_room_notification` (cognitive_agent.py line 3663)
- `_is_dm` flag is set on the observation (cognitive_agent.py line 1825)
- Channel types: `ship` (all-hands), `department`, `dm`, `recreation`, `custom`
- COMPOSE has three modes: `ward_room_response`, `dm_response`, `proactive_observation` (compose.py lines 383-387)
- ANALYZE produces a `composition_brief` with a `tone` field (analyze.py line 181)
- One-shot Ward Room prompt includes "Speak in your natural voice. Don't be formal unless the topic demands it." (cognitive_agent.py line 1275) — chain does NOT have this
- `compose_instructions()` provides personality + standing orders in all modes

---

## Fix

Three changes across 2 files. No new modules, no new dependencies.

### Part A: Propagate communication context into the observation (cognitive_agent.py)

In `_execute_chain_with_intent_routing()`, after the `_is_dm` flag is set (around line 1825), add communication context derivation:

```python
# AD-649: Communication context for chain register adaptation
_channel_name = _params.get("channel_name", "")
_is_dm_channel = _params.get("is_dm_channel", False)
if _is_dm_channel or _channel_name.startswith("dm-"):
    observation["_communication_context"] = "private_conversation"
elif _channel_name == "bridge":
    observation["_communication_context"] = "bridge_briefing"
elif _channel_name == "recreation":
    observation["_communication_context"] = "casual_social"
elif _channel_name in ("general", "all-hands"):
    observation["_communication_context"] = "ship_wide"
else:
    # Department channels, custom channels
    observation["_communication_context"] = "department_discussion"
observation["_channel_name"] = _channel_name
```

**Key details:**
- Five registers: `private_conversation`, `bridge_briefing`, `casual_social`, `ship_wide`, `department_discussion`
- Derived from existing `channel_name` and `is_dm_channel` — no new data sources
- Stored on observation so both ANALYZE and COMPOSE can access it

### Part B: Add communication context to ANALYZE composition brief (analyze.py)

In `_build_thread_analysis_prompt()`, add communication context to the composition_brief instructions. Find the existing `tone` field instruction (around line 181):

```
f"   - **tone**: How should the reply be framed for this thread?\n"
```

Replace with:

```python
f"   - **tone**: How should the reply be framed? Consider the communication\n"
f"     context: {context.get('_communication_context', 'department_discussion')}.\n"
f"     Private conversations are warm and exploratory. Bridge briefings are\n"
f"     concise and strategic. Department discussions are collegial and\n"
f"     technically specific. Recreation is casual and playful. Ship-wide\n"
f"     posts are measured and broadly relevant.\n"
f"     Include your reasoning process, not just conclusions.\n"
```

In `_build_situation_review_prompt()`, find the tone field in the composition_brief (lines 362-363):

```
f"   - **tone**: How should the response be framed? Consider audience, formality,\n"
f"     and your relationship with the recipient.\n"
```

Replace with:

```python
f"   - **tone**: How should the response be framed? Consider the communication\n"
f"     context: {context.get('_communication_context', 'department_discussion')}.\n"
f"     Private conversations are warm and exploratory. Bridge briefings are\n"
f"     concise and strategic. Department discussions are collegial and\n"
f"     technically specific. Recreation is casual and playful. Ship-wide\n"
f"     posts are measured and broadly relevant.\n"
f"     Include your reasoning process, not just conclusions.\n"
```

In `_build_dm_comprehension_prompt()`, find the `tone` sub-field inside `composition_brief` (lines 428-429):

```
f"   - **tone**: How should you respond given the emotional_tone and your\n"
f"     relationship with the sender?\n"
```

After it, add:

```python
f"   - **register**: This is a {context.get('_communication_context', 'private_conversation')}.\n"
f"     Be warm, conversational, and exploratory. Share reasoning, not just\n"
f"     conclusions. Engage as a trusted colleague, not a reporting system.\n"
```

### Part C: Add personality reinforcement and register adaptation to COMPOSE (compose.py)

#### C1: Ward Room compose prompt — add voice and register guidance

In `_build_ward_room_compose_prompt()`, find the existing mode framing (lines 84-89):

```python
system_prompt += (
    "\n\nYou are responding to a Ward Room thread. "
    "Write concise, conversational posts (2-4 sentences). "
    "Engage naturally — agree, disagree, build on ideas, ask questions. "
    "Do NOT repeat what someone else already said."
)
```

Replace with:

```python
# AD-649: Communication context and register adaptation
_comm_context = context.get("_communication_context", "department_discussion")

system_prompt += (
    "\n\nYou are responding to a Ward Room thread. "
    "Speak in your natural voice. Don't be formal unless the topic demands it. "
    "Write concise, conversational posts (2-4 sentences). "
    "Engage naturally — agree, disagree, build on ideas, ask questions. "
    "Show your reasoning, not just conclusions. "
    "Do NOT repeat what someone else already said."
)

if _comm_context == "casual_social":
    system_prompt += (
        " This is the recreation channel — be relaxed, playful, and social."
    )
elif _comm_context == "bridge_briefing":
    system_prompt += (
        " This is the bridge channel — be concise, strategic, and command-focused."
    )
elif _comm_context == "ship_wide":
    system_prompt += (
        " This is a ship-wide channel — be measured and broadly relevant. "
        "Junior crew may act on what you say, so be clear about what is "
        "observation versus recommendation."
    )
```

**Key changes from current:**
- Added "Speak in your natural voice. Don't be formal unless the topic demands it." — parity with one-shot (line 1275)
- Added "Show your reasoning, not just conclusions." — addresses Nova's "NUMBERS ARE BIG, PANIC NOW" problem
- Register-specific guidance appended based on `_communication_context`
- Department channel (default) gets no extra constraint — natural behavior is correct for peer discussion

#### C2: Proactive compose prompt — add voice guidance

In `_build_proactive_compose_prompt()`, find the non-duty framing (around line 168-174):

```python
system_prompt += (
    "\n\nYou are reviewing recent ship activity during a quiet moment. "
    "If you notice something noteworthy — a pattern, a concern, an insight "
    "related to your expertise — compose a brief observation (2-4 sentences). "
    "This will be posted to the Ward Room as a new thread. "
    "Speak in your natural voice. Be specific and actionable."
)
```

This already has "Speak in your natural voice." — no change needed for non-duty.

For the duty framing (around line 161-166):

```python
system_prompt += (
    f"\n\nYou are performing a scheduled duty: {_duty_desc}. "
    "Compose a Ward Room post with your findings (2-4 sentences). "
    "Be specific and actionable. If nothing noteworthy to report, "
    "respond with exactly: [NO_RESPONSE]"
)
```

Replace with:

```python
system_prompt += (
    f"\n\nYou are performing a scheduled duty: {_duty_desc}. "
    "Compose a Ward Room post with your findings (2-4 sentences). "
    "Speak in your natural voice. Be specific and actionable. "
    "Show your reasoning — explain what you found and why it matters, "
    "not just the data points. If nothing noteworthy to report, "
    "respond with exactly: [NO_RESPONSE]"
)
```

#### C3: DM compose prompt — fix hardcoded Captain assumption

In `_build_dm_compose_prompt()`, find the mode framing (lines 120-126):

```python
system_prompt += (
    "\n\nYou are in a 1:1 conversation with the Captain. "
    "Respond naturally and conversationally as yourself. "
    "Do NOT use any structured output formats, report blocks, "
    "code blocks, or task-specific templates. "
    "Be genuine, personable, and engage with what the Captain says. "
    "Draw on your expertise and personality, but keep it conversational."
)
```

Replace with:

```python
# AD-649: Dynamic recipient awareness
_recipient = context.get("_dm_recipient", "the Captain")
system_prompt += (
    f"\n\nYou are in a 1:1 private conversation with {_recipient}. "
    "Respond naturally and conversationally as yourself. "
    "Do NOT use any structured output formats, report blocks, "
    "code blocks, or task-specific templates. "
    "Be genuine, personable, and engage with what they say. "
    "Share your reasoning and thought process, not just conclusions. "
    "Draw on your expertise and personality, but keep it conversational."
)
```

**Note:** `_dm_recipient` is not yet populated by any caller — defaults to "the Captain" for backward compatibility. Future work (when DMs enter the chain) will set this from observation params.

---

## What NOT To Change

- **`_CHAIN_ELIGIBLE_INTENTS`** — DMs should remain one-shot for now. This AD improves Ward Room chain quality; DM chain routing is future scope.
- **evaluate.py / reflect.py** — AD-639 trust-band tuning handles personality preservation in these steps. No changes needed.
- **`_build_cognitive_baseline()`** — Ontology context is handled by AD-648. No changes here.
- **query.py** — QUERY fetches data; communication context is not its concern.
- **Standing orders / personality** — Already injected via `compose_instructions()`. This AD adds context, not identity.
- **One-shot path** — Already works well. No changes to `_decide_via_llm()`.

---

## Tests

Create `tests/test_ad649_communication_context.py`.

### Test 1: Communication context — DM channel

```
Given: observation with params.channel_name="dm-captain-nova", params.is_dm_channel=True
When: _execute_chain_with_intent_routing() sets up context
Then: observation["_communication_context"] == "private_conversation"
```

### Test 2: Communication context — bridge channel

```
Given: observation with params.channel_name="bridge"
When: _execute_chain_with_intent_routing() sets up context
Then: observation["_communication_context"] == "bridge_briefing"
```

### Test 3: Communication context — recreation channel

```
Given: observation with params.channel_name="recreation"
When: _execute_chain_with_intent_routing() sets up context
Then: observation["_communication_context"] == "casual_social"
```

### Test 4: Communication context — department channel

```
Given: observation with params.channel_name="science"
When: _execute_chain_with_intent_routing() sets up context
Then: observation["_communication_context"] == "department_discussion"
```

### Test 5: Communication context — ship-wide channel

```
Given: observation with params.channel_name="general"
When: _execute_chain_with_intent_routing() sets up context
Then: observation["_communication_context"] == "ship_wide"
```

### Test 6: Ward Room compose includes voice instruction

```
Given: context with _communication_context="department_discussion"
When: _build_ward_room_compose_prompt() is called
Then: system_prompt contains "Speak in your natural voice"
And: system_prompt contains "Show your reasoning"
```

### Test 7: Ward Room compose — recreation register

```
Given: context with _communication_context="casual_social"
When: _build_ward_room_compose_prompt() is called
Then: system_prompt contains "relaxed, playful, and social"
```

### Test 8: Ward Room compose — bridge register

```
Given: context with _communication_context="bridge_briefing"
When: _build_ward_room_compose_prompt() is called
Then: system_prompt contains "concise, strategic, and command-focused"
```

### Test 9: Ward Room compose — ship-wide register

```
Given: context with _communication_context="ship_wide"
When: _build_ward_room_compose_prompt() is called
Then: system_prompt contains "observation versus recommendation"
```

### Test 10: ANALYZE thread analysis includes communication context

```
Given: context with _communication_context="casual_social"
When: _build_thread_analysis_prompt() is called
Then: user_prompt's tone field contains "casual_social"
And: user_prompt contains "Private conversations are warm"
```

### Test 11: Proactive duty compose includes voice guidance

```
Given: context with _active_duty={"duty_id": "scout_report", "description": "External research scan"}
When: _build_proactive_compose_prompt() is called
Then: system_prompt contains "Speak in your natural voice"
And: system_prompt contains "Show your reasoning"
```

### Test 12: DM compose uses dynamic recipient

```
Given: context with _dm_recipient="Lieutenant Sage"
When: _build_dm_compose_prompt() is called
Then: system_prompt contains "private conversation with Lieutenant Sage"
And: system_prompt does NOT contain "the Captain"
```

### Test 13: DM compose defaults to Captain when no recipient

```
Given: context with no _dm_recipient key
When: _build_dm_compose_prompt() is called
Then: system_prompt contains "private conversation with the Captain"
```

### Test 14: Communication context defaults to department_discussion

```
Given: observation with params.channel_name="custom-channel-xyz"
When: _execute_chain_with_intent_routing() sets up context
Then: observation["_communication_context"] == "department_discussion"
```

---

## Verification Checklist

- [ ] Ward Room chain responses include "Speak in your natural voice"
- [ ] Recreation channel posts are casual and playful in tone
- [ ] Bridge channel posts are concise and strategic
- [ ] Department channel posts show reasoning alongside conclusions
- [ ] ANALYZE composition brief includes communication context in tone guidance
- [ ] DM compose prompt is not hardcoded to "the Captain"
- [ ] One-shot path unchanged — no regressions in DM quality
- [ ] `pytest tests/test_ad649_communication_context.py -v` green
- [ ] `pytest tests/ -x -q` — no regressions
