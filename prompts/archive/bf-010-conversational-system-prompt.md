# BF-010: 1:1 Conversations Use Domain Instructions — LLM Responds in Task Format

## Problem

BF-009 fixed the routing — `@wesley hello` from HXI now reaches Wesley. But Wesley responds with a `===SCOUT_REPORT===` block analyzing the ship's standing orders instead of having a conversation.

The `act()` guard (AD-398, `scout.py:352-354`) correctly passes through raw LLM output for `direct_message`. But the LLM itself generates domain-formatted output because the **system prompt** still contains task-specific instructions:

```
"For each repository provided, respond with a structured report block."
"RESPONSE FORMAT (one block per repo):"
"===SCOUT_REPORT==="
```

The LLM is following its instructions faithfully. It doesn't know it's in a conversation — its system prompt says "produce scout reports."

This affects ALL crew agents with domain-specific instructions: ScoutAgent (report blocks), BuilderAgent (file change blocks), ArchitectAgent (proposal blocks), SurgeonAgent (JSON remediation), CounselorAgent (assessment format).

## Root Cause

`CognitiveAgent.decide()` (line 128-133) always calls `compose_instructions()` with the agent's full `instructions` field, regardless of whether this is a task or a 1:1 conversation. The system prompt contains domain output format requirements that override the conversational user message ("Captain says: hello").

## Fix: Conversational System Prompt Override

In `CognitiveAgent.decide()`, when `observation["intent"] == "direct_message"`, build a **conversational system prompt** instead of the full domain-instructions system prompt.

### Implementation

In `src/probos/cognitive/cognitive_agent.py`, in `decide()`, after line 110 and before the LLM call at line 135:

```python
# --- LLM call (cache miss) ---
user_message = self._build_user_message(observation)

# BF-010: conversational system prompt for 1:1 sessions
is_conversation = observation.get("intent") == "direct_message"

# ... strategy advice block unchanged ...

from probos.cognitive.standing_orders import compose_instructions

if is_conversation:
    # For 1:1 conversations, use personality + standing orders only.
    # Exclude domain-specific task instructions (report formats, output blocks)
    # so the LLM responds naturally as itself.
    composed = compose_instructions(
        agent_type=getattr(self, "agent_type", self.__class__.__name__.lower()),
        hardcoded_instructions="",  # <-- skip domain instructions
    )
    # Append a conversational directive
    composed += (
        "\n\nYou are in a 1:1 conversation with the Captain. "
        "Respond naturally and conversationally as yourself. "
        "Do NOT use any structured output formats, report blocks, "
        "code blocks, or task-specific templates. "
        "Be genuine, personable, and engage with what the Captain says. "
        "Draw on your expertise and personality, but keep it conversational."
    )
else:
    composed = compose_instructions(
        agent_type=getattr(self, "agent_type", self.__class__.__name__.lower()),
        hardcoded_instructions=self.instructions or "",
    )

request = LLMRequest(
    prompt=user_message,
    system_prompt=composed,
    tier=self._resolve_tier(),
)
```

### Why `hardcoded_instructions=""` and not a flag

`compose_instructions()` assembles a multi-tier system prompt:
1. Hardcoded identity (agent type)
2. **Personality block** (Big Five traits, callsign, display name, department) — AD-393
3. Federation Constitution
4. Ship Standing Orders
5. Department Protocols
6. Personal Standing Orders — AD-379 (e.g., Wesley's curiosity, eagerness)
7. Runtime Directives — AD-386

Only tier 1 (`hardcoded_instructions`) contains the domain output format. Tiers 2-7 are identity, governance, and personality — all valuable for conversation. By passing `hardcoded_instructions=""`, we keep the agent's full identity and personality while stripping the `===SCOUT_REPORT===` format instructions.

### Why not just append "be conversational" to the user message

The LLM weighs system prompt instructions more heavily than user message requests. A system prompt saying "ALWAYS format as ===SCOUT_REPORT===" overrides a user message requesting natural conversation. The fix must be in the system prompt, not the user message.

### Decision cache note

The `is_conversation` check is BEFORE the cache lookup (line 96-106), so cached task decisions won't be returned for conversations. However, direct_message observations will have different `_compute_cache_key()` outputs anyway (different intent, different params), so cache collision is already impossible. No cache changes needed.

Wait — actually the cache lookup happens first (line 96-106). But `_compute_cache_key()` includes the observation dict which includes `intent: "direct_message"` and the unique `text` param, so cache keys will never collide with task intents. No issue.

## Files Modified

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | `decide()` — conversational system prompt branch for `direct_message` |

One file. ~15 lines of new code. Zero new dependencies.

## Testing

1. **Unit test: conversational system prompt excludes domain instructions**
   - Create a CognitiveAgent subclass with `instructions = "ALWAYS use ===REPORT=== format"`
   - Call `decide()` with `observation={"intent": "direct_message", "params": {"text": "hello"}}`
   - Verify the LLM request's `system_prompt` does NOT contain "===REPORT==="
   - Verify it DOES contain the conversational directive

2. **Unit test: task intent still uses full instructions**
   - Same agent, call `decide()` with `observation={"intent": "scout_search", ...}`
   - Verify `system_prompt` DOES contain the domain instructions

3. **Regression: existing act() guards still work**
   - Verify `decision["intent"] == "direct_message"` is still propagated by `handle_intent()`
   - Verify `act()` still returns raw `llm_output` for direct_message

## Commit Message

```
Fix 1:1 conversations using domain instructions instead of conversational prompt (BF-010)

CognitiveAgent.decide() now uses a conversational system prompt for
direct_message intents — personality and standing orders only, no
domain task format instructions. Prevents crew agents from responding
in structured report/code/proposal format during 1:1 sessions.
```
