# Fix: Enrich Conversation Context with Last Execution Intent Parameters

## Problem

When the user says "What about Evergreen?" after asking about Denver, CO weather, the LLM picks Evergreen, Alabama instead of Colorado. The conversation context (AD-273) sends response text but not the structured intent parameters. The LLM doesn't see `location="Denver, CO"` and can't infer geographic context.

## Fix

Inject the last execution's intent+params as a structured context entry into the conversation history before passing to the decomposer. The LLM then sees:

```
User: What is the weather in Denver, CO?
ProbOS: The weather in Denver is 72°F...
Context: [Last execution: get_weather(location=Denver, CO)]
User: What about Evergreen?
```

## Implementation

### File: `src/probos/runtime.py`

In `process_natural_language()`, find where `conversation_history` is passed to `self.decomposer.decompose()`. Before that call, enrich the history with the last execution's structured data:

```python
# Enrich conversation context with last execution's structured intent data
if conversation_history and self._last_execution:
    dag = self._last_execution.get("dag")
    if dag and hasattr(dag, "nodes") and dag.nodes:
        intent_summary = "; ".join(
            f'{n.intent}({", ".join(f"{k}={v}" for k, v in n.params.items())})'
            for n in dag.nodes
        )
        if intent_summary:
            conversation_history = list(conversation_history) + [
                ("context", f"[Last execution: {intent_summary}]")
            ]
```

### File: `src/probos/cognitive/decomposer.py`

In the `decompose()` method, in the CONVERSATION CONTEXT section where history messages are formatted, update the role label to handle the "context" role:

Change:
```python
label = "User" if role == "user" else "ProbOS"
```

To:
```python
label = "User" if role == "user" else ("Context" if role == "context" else "ProbOS")
```

## Constraints

- Only touch `src/probos/runtime.py` and `src/probos/cognitive/decomposer.py`
- Do NOT touch any UI files
- Do NOT change how the frontend sends history — the enrichment happens server-side
- Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
