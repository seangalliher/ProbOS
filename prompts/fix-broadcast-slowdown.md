# FIX: run_command Hang — Bundled Agents Not Self-Deselecting Fast Enough

## Root Cause (diagnosed)

The `intent_bus.broadcast()` fans out to ALL ~55 subscribers concurrently. For `run_command`, only 3 `ShellCommandAgent` instances should respond. The other ~52 agents should self-deselect by returning `None` instantly.

BUT — the 20 bundled CognitiveAgent subclasses may be making LLM calls before self-deselecting. The `_BundledMixin` check is supposed to short-circuit, but if `CognitiveAgent.handle_intent()` is calling the LLM BEFORE the mixin check runs, each bundled agent makes an LLM call (5-30 seconds) for every broadcast, even for intents they don't handle.

With 20 bundled agents × slow LLM = the broadcast takes 30+ seconds to collect all results, even though only 3 shell agents actually respond.

## Verification Steps

1. **Check the `_BundledMixin` implementation**: Is the self-deselect check the FIRST thing in `handle_intent()`? It must return `None` before any LLM call.

2. **Check `CognitiveAgent.handle_intent()`**: Does it check `_handled_intents` before calling `perceive()` → `decide()` (which calls the LLM)?

3. **Add timing logs**: In `intent.py` `_invoke_handler()`, log the time each handler takes:
   ```python
   import time
   t0 = time.monotonic()
   result = await handler(intent)
   elapsed = (time.monotonic() - t0) * 1000
   if elapsed > 100:  # log handlers taking > 100ms
       logger.warning("Slow handler: agent=%s intent=%s elapsed=%.0fms result=%s",
                       agent_id[:8], intent.intent, elapsed, 
                       "responded" if result else "declined")
   ```

4. **Quick test**: Temporarily make `_invoke_handler` skip bundled agents for unknown intents:
   ```python
   # Before calling handler, check if this is a known handler
   # This is a diagnostic hack — the real fix is in the agent code
   ```

## The Fix

The `_BundledMixin` or `CognitiveAgent.handle_intent()` must check `intent.intent in self._handled_intents` FIRST, before any `perceive()`, `decide()`, or LLM call:

```python
async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
    # FAST PATH: self-deselect immediately for unrecognized intents
    if intent.intent not in self._handled_intents:
        return None
    
    # Skill check
    if intent.intent in self._skills:
        return await self._skills[intent.intent].handler(intent, llm_client=self._llm_client)
    
    # Full cognitive lifecycle (perceive → decide → act → report) — only for handled intents
    observation = await self.perceive(intent)
    ...
```

Check ALL these files:
- `src/probos/agents/bundled/web_agents.py` — `_BundledMixin.handle_intent()` 
- `src/probos/cognitive/cognitive_agent.py` — `CognitiveAgent.handle_intent()`
- Verify the mixin's check runs BEFORE the parent class's LLM call

## This is PRE-Phase 22 regression

Before Phase 22, there were ~25 agents (all core + utility). Broadcasting was fast because:
- FileReaderAgent: checks `_handled_intents`, instant decline
- ShellCommandAgent: checks `_handled_intents`, accepts `run_command`
- All core agents: deterministic, no LLM calls

Phase 22 added 20 CognitiveAgent instances. If they make LLM calls before declining, broadcasts became 20x slower.

## After Fix

1. CLI test: `python -m probos` → "what time is it?" → should complete in < 10 seconds
2. Add the timing logs to `_invoke_handler` permanently (DEBUG level) — useful for future performance monitoring
3. Run full test suite: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
