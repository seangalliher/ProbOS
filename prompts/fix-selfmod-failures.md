# Fix: Self-Mod Agent Design Failures — Diagnosis + Better Error Surfacing

## Problem 1: Self-mod design fails silently

When the self-mod pipeline fails to design a new agent (as seen with the RSS feed reader attempt), the user sees:
- "Could not design agent for 'rss_feed_reader': design failed"

No detail about WHY. Was it:
- CodeValidator rejection (bad imports, forbidden patterns)?
- SandboxRunner crash (agent code doesn't work)?
- LLM generated invalid code (syntax error, wrong class structure)?
- Timeout during design?

The user can't help fix the problem or understand what happened.

## Problem 2: Self-mod design may have a regression

Self-mod used to work reliably from the CLI (it was tested through Phase 10-15). The RSS feed reader failure suggests either:
1. The LLM (now Sonnet via Copilot proxy instead of qwen via Ollama) generates different code that doesn't pass validation
2. The async self-mod changes (from `hxi-async-selfmod.md`) broke the pipeline
3. The agent designer prompt needs updating for the current code patterns

## Diagnosis steps

### Step 1: Run self-mod from the CLI and capture the full error

Start `python -m probos` (interactive shell, NOT `probos serve`). Try:
```
> write me a haiku about the ocean
```

Watch the terminal output. The CLI shows the full self-mod pipeline steps:
- "Capability gap detected" or similar
- "Designing agent..." 
- Validation result (pass/fail with details)
- Sandbox result (pass/fail with details)

If the CLI shows detailed error messages but the HXI doesn't, the issue is just error surfacing in the API.

### Step 2: Add detailed error logging to the async self-mod API path

**File:** `src/probos/api.py` — in `_run_selfmod()` (the async self-mod handler)

The self-mod pipeline returns a `DesignedAgentRecord` with a `status` field. When status is not "active", log the FULL record including any error details:

```python
async def _run_selfmod(req, runtime):
    try:
        runtime._emit_event("self_mod_started", {
            "intent": req.intent_name,
            "message": f"🔧 Designing agent for '{req.intent_name}'..."
        })
        
        record = await runtime.self_mod_pipeline.handle_unhandled_intent(
            intent_name=req.intent_name,
            intent_description=req.intent_description,
            parameters=req.parameters,
        )
        
        if record and record.status == "active":
            # success path — existing code
            ...
        else:
            # FAILURE: Surface the details
            error_detail = "Unknown error"
            if record:
                error_detail = getattr(record, 'error', None) or getattr(record, 'status', 'unknown')
                # Check if there's a validation error
                if hasattr(record, 'validation_error'):
                    error_detail = record.validation_error
                elif hasattr(record, 'sandbox_error'):
                    error_detail = record.sandbox_error
            
            logger.warning("Self-mod design failed for %s: %s", req.intent_name, error_detail)
            
            runtime._emit_event("self_mod_failure", {
                "intent": req.intent_name,
                "message": f"❌ Agent design failed: {error_detail}",
                "error": str(error_detail),
            })
    except Exception as e:
        logger.error("Self-mod exception for %s: %s", req.intent_name, e, exc_info=True)
        runtime._emit_event("self_mod_failure", {
            "intent": req.intent_name,
            "message": f"❌ Agent design error: {e}",
            "error": str(e),
        })
```

### Step 3: Check the SelfModificationPipeline for error details

**File:** `src/probos/cognitive/self_mod.py`

Read the `handle_unhandled_intent()` method. Find where it returns a record with a non-"active" status. What information is available about the failure? The pipeline has these stages:

1. Config check (max_designed_agents limit)
2. Agent design (LLM generates code)
3. Code validation (CodeValidator)
4. Sandbox testing (SandboxRunner)
5. Registration

Each stage can fail. The `DesignedAgentRecord` should capture which stage failed and why. Check:
- Does `DesignedAgentRecord` have an `error` or `failure_reason` field?
- If not, add one — the record should carry the failure detail
- At each failure point in the pipeline, set the error detail before returning

### Step 4: Surface error details in the HXI chat

When the frontend receives a `self_mod_failure` event with an `error` field, display it:

```
❌ Agent design failed: CodeValidator rejected — import 'requests' is not in the allowed imports list
```

This tells the user exactly what went wrong and might even let them fix it ("oh, I need to add 'requests' to allowed imports").

### Step 5: Test self-mod end-to-end

After fixes:
1. Start `probos serve`
2. In HXI chat: "write me a haiku about the ocean"
3. Should see: capability gap → [✨ Build Agent] → click → progress → either success (haiku) or detailed failure message
4. If failure: the error message should explain WHY (validation error, sandbox error, etc.)
5. Try from CLI too: `python -m probos` → same query → should work or show detailed error

### Step 6: If the design itself is failing (LLM generates bad code)

The issue may be that Sonnet generates different code structure than qwen did, and the validator/sandbox rejects it. Check:
- Does the designed agent code import from `probos.cognitive.cognitive_agent`? (required by CodeValidator)
- Does it subclass `CognitiveAgent`? (required by schema check)
- Does it have `intent_descriptors` and `agent_type`? (required)
- Does the sandbox test pass? (synthetic intent → IntentResult)

If Sonnet's code structure is different, the `AGENT_DESIGN_PROMPT` in `agent_designer.py` may need examples updated for the current validator expectations.

## After fix

1. Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
2. Test self-mod from CLI: `python -m probos` → "write me a haiku"
3. Test self-mod from HXI: `probos serve` → same query
4. Verify: failure messages include specific error details, not just "design failed"
