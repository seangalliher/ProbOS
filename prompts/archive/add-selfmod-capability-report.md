# AD-266: Post-Design Capability Report in Self-Mod Success Event

## Problem

When self-mod successfully designs a new agent, the HXI shows only "BitcoinPriceAgent deployed! Handling your request..." — not enough for a demo audience to understand what was built, how it works, or why it's impressive. The sophistication of the design pipeline (validate, sandbox, register) is invisible.

## Design

After a successful agent design in the `/api/selfmod/approve` flow, use the LLM to generate a brief capability report from the agent's source code. Include the report in the `self_mod_success` event's `message` field. The HXI already renders this as a system chat message — no frontend changes needed.

## Implementation

### File: `src/probos/api.py` — inside `_run_selfmod()`, after `record.status == "active"` check

After the post-creation work block (KnowledgeStore, SemanticLayer) and BEFORE emitting `self_mod_success`, add a capability report generation step:

```python
# Generate capability report from designed agent source
capability_report = ""
try:
    # Extract the instructions string from source code
    import ast
    tree = ast.parse(record.source_code)
    instructions_value = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "instructions":
                    if isinstance(node.value, (ast.Constant, ast.Str)):
                        instructions_value = getattr(node.value, 'value', '') or getattr(node.value, 's', '')
                    elif isinstance(node.value, ast.JoinedStr):
                        instructions_value = "(f-string instructions)"

    if instructions_value and hasattr(rt, 'llm_client'):
        report_prompt = (
            f"A new ProbOS agent was just created. Summarize what it does in 2-3 sentences "
            f"for a non-technical audience. Be specific about its capabilities.\n\n"
            f"Agent name: {record.class_name}\n"
            f"Intent: {record.intent_name}\n"
            f"Description: {req.intent_description}\n"
            f"Agent instructions: {instructions_value[:500]}\n"
        )
        from probos.types import LLMRequest
        report_response = await rt.llm_client.complete(LLMRequest(
            prompt=report_prompt,
            system_prompt="You are a technical writer. Write a brief, impressive summary of a new AI agent's capabilities. Use bullet points. Keep it under 100 words.",
        ))
        if report_response and report_response.text:
            capability_report = report_response.text.strip()
except Exception:
    logger.debug("Capability report generation failed", exc_info=True)

# Build the success message
deploy_msg = f"✅ {record.class_name} deployed!"
if capability_report:
    deploy_msg += f"\n\n{capability_report}\n\nHandling your request..."
else:
    deploy_msg += " Handling your request..."
```

Then change the `self_mod_success` event emission to use `deploy_msg`:

```python
rt._emit_event("self_mod_success", {
    "intent": req.intent_name,
    "agent_type": record.agent_type,
    "message": deploy_msg,
})
```

### Key design decisions

- **AST extraction of `instructions`** — the instructions string is the best human-readable description of what the agent does. Extracting it from the source code via AST is safe and deterministic.
- **LLM summarization** — the instructions are written for the LLM (technical, imperative). The summary rewrites them for a human audience.
- **Graceful fallback** — if any step fails (AST parse, LLM call, empty response), falls back to the existing message format. Zero risk of breaking the flow.
- **No frontend changes** — the HXI already renders `data.message` from `self_mod_success` events as a system chat message. Longer messages just display with more text.

## Tests

### File: `tests/test_hxi_events.py` (or `tests/test_distribution.py`)

Add 1-2 tests:

1. `test_selfmod_success_event_has_capability_report` — mock the LLM, verify the `self_mod_success` event message contains the report text (not just "deployed")
2. `test_selfmod_success_fallback_without_llm` — verify fallback message when LLM is unavailable

If testing the full async `_run_selfmod` is too complex to set up, these can be skipped — the capability report is best-effort with a try/except fallback. The critical thing is that the existing flow doesn't break.

## PROGRESS.md

Update:
- Status line (line 3) test count if it changed
- Add AD-266 section before `## Active Roadmap`:

```
### AD-266: Post-Design Capability Report

**Problem:** When self-mod designs a new agent, the HXI only shows "[ClassName] deployed!" — not enough for users (or demo audiences) to understand what was built.

| AD | Decision |
|----|----------|
| AD-266 | After successful agent design, LLM generates a brief capability summary from the agent's `instructions` string (extracted via AST). Included in the `self_mod_success` event message. HXI already renders it — no frontend changes. Graceful fallback to original message on failure |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/api.py` | Added capability report generation in `_run_selfmod()` after successful design, before `self_mod_success` event |

NNNN/NNNN tests passing (+ 11 skipped).
```

Replace NNNN with the actual test count.

## Constraints

- Only touch `src/probos/api.py` and optionally `tests/test_hxi_events.py` or `tests/test_distribution.py`
- Also update `PROGRESS.md`
- Do NOT modify any UI/TypeScript files — the HXI already renders the message
- Do NOT modify `self_mod.py`, `runtime.py`, `agent_designer.py`
- Do NOT change the self-mod pipeline — this is a presentation-layer addition in the API
- The capability report is best-effort — failures must not break the self-mod flow
- Run tests after each edit: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
