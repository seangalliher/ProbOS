# Fix: Lightning Bolt Emoji + Stronger Geographic Context Resolution

## Fix 1: Replace remaining lightning bolt emoji

Find any remaining ⚡ (lightning bolt) emoji in ui/src/components/IntentSurface.tsx. Replace with an inline SVG that matches the neon glow design language:

```tsx
<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="9,1 4,9 8,9 7,15 12,7 8,7 9,1" /></svg>
```

Also check DecisionSurface.tsx and api.py for any remaining emoji characters (⚡, ✅, or others that aren't Unicode geometric symbols like ⬡ ◎ △ ◈).

## Fix 2: Stronger geographic context in conversation history

The current context enrichment in runtime.py sends:
```
Context: [Last execution: get_weather(location=Denver, CO)]
```

The LLM doesn't interpret this strongly enough — it still resolves "Evergreen" to Alabama instead of Colorado. Make the context more explicit.

### File: `src/probos/runtime.py`

Find the conversation context enrichment block (around line 1153). Change:

```python
intent_summary = "; ".join(
    f'{n.intent}({", ".join(f"{k}={v}" for k, v in n.params.items())})'
    for n in last_dag.nodes
)
if intent_summary:
    conversation_history = list(conversation_history) + [
        ("context", f"[Last execution: {intent_summary}]")
    ]
```

To:

```python
intent_summary = "; ".join(
    f'{n.intent}: {", ".join(f"{k}={v}" for k, v in n.params.items())}'
    for n in last_dag.nodes
)
if intent_summary:
    conversation_history = list(conversation_history) + [
        ("context", 
         f"Previous action: {intent_summary}. "
         f"When the user references a place, person, or topic without full qualification, "
         f"assume the same context (location, region, domain) as the previous query.")
    ]
```

This gives the LLM an explicit instruction to carry forward geographic and topical context, not just raw parameters.

## Constraints

- Touch: `ui/src/components/IntentSurface.tsx`, `ui/src/components/DecisionSurface.tsx`, `src/probos/api.py`, `src/probos/runtime.py`
- Rebuild UI: `cd ui && npm run build`
- Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
