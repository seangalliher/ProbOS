# BF-013: Ship's Computer Callsign Awareness

## Problem

The ship's computer doesn't recognize crew callsigns. When a user asks "Is Wesley aboard?" without the `@` prefix, the decomposer emits `agent_info` with `agent_type: "wesley"`. The `IntrospectAgent._agent_info()` handler searches by agent_type, agent_id, and pool name — but never checks the `CallsignRegistry`. Result: "No agents found matching: wesley."

Additionally, `BaseAgent.info()` omits the callsign from its return dict, so even successful agent lookups don't include the crew name. And the orb mesh doesn't show callsigns on hover.

## Root Cause

Three gaps from AD-397/398 callsign implementation:
1. `IntrospectAgent._agent_info()` has no callsign resolution fallback
2. `BaseAgent.info()` doesn't include `callsign` in returned data
3. Decomposer prompt has no callsign examples or vocabulary

## Fixes

### Fix 1: IntrospectAgent callsign fallback

**File:** `src/probos/agents/introspect.py`

In `_agent_info()`, after all existing search attempts fail (agent_type exact match, substring, pool name) and before returning "no agents found," add a callsign resolution step:

```python
# Callsign resolution fallback (BF-013)
if not agents and hasattr(rt, 'callsign_registry'):
    resolved = rt.callsign_registry.resolve(agent_type or agent_id or "")
    if resolved:
        agents = [a for a in rt.registry.all()
                  if a.agent_type == resolved["agent_type"]]
```

Read the full `_agent_info()` method to find the exact insertion point — it should go just before the "no agents found" return path.

### Fix 2: BaseAgent.info() includes callsign

**File:** `src/probos/substrate/agent.py`

In the `info()` method return dict, add the callsign field:

```python
def info(self) -> dict[str, Any]:
    return {
        "id": self.id,
        "type": self.agent_type,
        "callsign": self.callsign,  # BF-013
        "pool": self._pool_name,
        # ... rest unchanged ...
    }
```

Read the existing `info()` method and add `"callsign": self.callsign` in the appropriate position (after "type" is natural).

### Fix 3: Decomposer prompt callsign context

**File:** `src/probos/cognitive/prompt_builder.py`

Add a callsign mapping block to the system prompt context. Find where the intent table is built (the `agent_info` row). After the intent table, inject a callsign reference so the LLM knows how to translate crew names:

```python
# After the intent table, add callsign context (BF-013)
if hasattr(runtime, 'callsign_registry') and runtime.callsign_registry:
    callsign_lines = []
    for agent_type, callsign in runtime.callsign_registry.all_callsigns().items():
        callsign_lines.append(f"  {callsign} = {agent_type}")
    if callsign_lines:
        prompt += "\n\nCrew callsigns (use agent_type when referenced by callsign):\n"
        prompt += "\n".join(callsign_lines) + "\n"
```

**Important:** Check if `CallsignRegistry` has an `all_callsigns()` or similar method that returns the full mapping. If not, you'll need to add one:

**File:** `src/probos/crew_profile.py`

Add to `CallsignRegistry`:

```python
def all_callsigns(self) -> dict[str, str]:
    """Return {agent_type: display_callsign} for all registered callsigns."""
    return dict(self._type_to_callsign)
```

Also add a callsign example to the decomposer few-shot examples in prompt_builder.py. Find the existing `agent_info` example and add one for callsigns:

```
User: "is Wesley aboard?"
{"intents": [{"id": "t1", "intent": "agent_info", "params": {"agent_type": "scout"}, "depends_on": []}]}
```

### Fix 4: Orb mesh callsign tooltip

**File:** `ui/src/components/OrbMesh.tsx` (or wherever agent orbs are rendered)

Find where agent orbs render their tooltip/hover content. Add the callsign to the tooltip display. The agent data should now include `callsign` from Fix 2 via the API.

Search for the orb component that displays agent info on hover. The tooltip should show:

```
Wesley (scout)
Department: Science
Trust: 0.92
```

Instead of the current:

```
scout
Trust: 0.92
```

Read the orb component to understand the current tooltip structure and where agent data flows from.

## Files Modified

| File | Change |
|------|--------|
| `src/probos/agents/introspect.py` | Callsign resolution fallback in `_agent_info()` |
| `src/probos/substrate/agent.py` | Add `callsign` to `info()` return dict |
| `src/probos/cognitive/prompt_builder.py` | Inject callsign mapping + example into decomposer prompt |
| `src/probos/crew_profile.py` | Add `all_callsigns()` method to `CallsignRegistry` |
| `ui/src/components/OrbMesh.tsx` (or equivalent) | Show callsign in orb tooltip |

## Testing

### New/updated tests:

1. **`_agent_info` resolves callsign** — Mock runtime with callsign_registry, call `_agent_info` with `agent_type="wesley"`, verify it returns the scout agent.
2. **`_agent_info` callsign case-insensitive** — Call with "Wesley", "WESLEY", "wesley" — all should resolve.
3. **`BaseAgent.info()` includes callsign** — Create agent with callsign set, call `info()`, verify `callsign` key in returned dict.
4. **`all_callsigns()` returns mapping** — Load profiles, verify returns `{"scout": "Wesley", "builder": "Scotty", ...}`.
5. **Decomposer prompt includes callsigns** — Build prompt with runtime that has callsign_registry, verify prompt text includes "Crew callsigns" section.

### Regression:

```
uv run pytest tests/test_introspect.py tests/test_decomposer.py tests/test_agent_base.py -v
```

Then:
```
uv run pytest tests/ --tb=short
```

## Commit Message

```
Fix ship's computer callsign awareness and orb tooltips (BF-013)

IntrospectAgent._agent_info() now falls back to CallsignRegistry when
agent_type/id lookup fails. BaseAgent.info() includes callsign field.
Decomposer prompt injected with callsign→agent_type mapping so LLM
can translate crew names. Orb tooltip shows callsign display name.
```
