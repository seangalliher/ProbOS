# Phase 15a — CognitiveAgent Base Class

## Context

You are building Phase 15a of ProbOS, a probabilistic agent-native OS runtime. Read `PROGRESS.md` for full architectural context. Current state: **1073/1073 tests passing + 11 skipped. Latest AD: AD-190.**

This phase introduces `CognitiveAgent` — a new agent base class where the `decide()` and/or `act()` steps consult an LLM guided by per-agent `instructions`. This brings reasoning *inside* the mesh as a trust-scored, confidence-tracked, recyclable participant rather than concentrating all reasoning in the decomposer.

**This is the single biggest architectural change since Phase 3a.** Get it right. Read the existing code carefully before writing anything.

---

## Pre-Build Audit

Before writing any code, verify:

1. **Latest AD number in PROGRESS.md** — confirm AD-190 is the latest. Phase 15a AD numbers start at **AD-191**. If AD-190 is NOT the latest, adjust all AD numbers in this prompt upward accordingly.
2. **Test count** — confirm 1073 tests pass before starting: `uv run pytest tests/ -v`
3. **Read these files thoroughly:**
   - `src/probos/substrate/agent.py` — understand `BaseAgent` lifecycle, `__init__` signature, `tier`, `agent_id`, `**kwargs`
   - `src/probos/cognitive/agent_designer.py` — understand how designed agents are currently generated (full `act()` logic, `__init__(**kwargs)`, `self._llm_client = kwargs.get("llm_client")`)
   - `src/probos/cognitive/self_mod.py` — understand `SelfModificationPipeline`, `DesignedAgentRecord`, the full flow from unhandled intent → code generation → validation → sandbox → registration
   - `src/probos/cognitive/code_validator.py` — understand schema conformance checks (BaseAgent subclass, `intent_descriptors`, `handle_intent`, `agent_type`, `_handled_intents`)
   - `src/probos/cognitive/sandbox.py` — understand `SandboxRunner` dynamic loading and test execution
   - `src/probos/cognitive/llm_client.py` — understand `BaseLLMClient`, `MockLLMClient` pattern registry, `LLMRequest`/`LLMResponse`
   - `src/probos/cognitive/strategy.py` — understand `StrategyRecommender` and `_get_llm_equipped_types()`
   - `src/probos/runtime.py` — understand `_create_designed_pool()`, `_register_designed_agent()`, `_extract_unhandled_intent()`, `register_agent_type()`, LLM client injection
   - `src/probos/substrate/skill_agent.py` — understand `SkillBasedAgent` pattern for comparison

---

## What To Build

### Step 1: `CognitiveAgent` Base Class (AD-191, AD-192)

**File:** `src/probos/cognitive/cognitive_agent.py` (new)

Create `CognitiveAgent(BaseAgent)` — an abstract base class for agents whose `decide()` step consults an LLM.

**AD-191: CognitiveAgent base class.** `CognitiveAgent` extends `BaseAgent` with an `instructions: str` field that serves as the LLM system prompt governing the agent's reasoning. The perceive/decide/act/report lifecycle is preserved. `decide()` invokes the LLM with `instructions` as the system prompt and the current observation (from `perceive()`) as the user message. `act()` executes based on the LLM's decision. The agent uses the existing per-tier LLM client infrastructure — no new LLM integration.

**AD-192: `instructions` field on BaseAgent.** Add `instructions: str | None = None` as a class attribute on `BaseAgent` (not just on `CognitiveAgent`). This allows any agent to optionally carry instructions. Tool agents ignore it (their code *is* their instruction). `CognitiveAgent` requires it — `__init__` raises `ValueError` if `instructions` is None or empty. This keeps the type hierarchy clean: a `BaseAgent` *may* have instructions; a `CognitiveAgent` *must* have them.

Design details:

```python
class CognitiveAgent(BaseAgent):
    """Agent whose decide() step consults an LLM guided by instructions."""
    
    tier = "domain"  # Cognitive agents are domain-tier by default
    
    # Subclasses MUST set these (or pass via __init__)
    instructions: str | None = None
    agent_type: str = "cognitive"
    
    def __init__(self, **kwargs):
        # Extract instructions from kwargs if provided (overrides class attr)
        if "instructions" in kwargs:
            self.instructions = kwargs.pop("instructions")
        
        super().__init__(**kwargs)
        
        # LLM client from kwargs (same pattern as designed agents)
        self._llm_client = kwargs.get("llm_client")
        
        # Runtime reference for mesh sub-intent dispatch
        self._runtime = kwargs.get("runtime")
        
        # Validate instructions exist
        if not self.instructions:
            raise ValueError(
                f"{self.__class__.__name__} requires non-empty instructions"
            )
    
    async def perceive(self, intent: IntentMessage) -> dict:
        """Package the intent as an observation for the LLM."""
        return {
            "intent": intent.intent,
            "params": intent.params,
            "context": intent.context,
        }
    
    async def decide(self, observation: dict) -> dict:
        """Consult the LLM with instructions + observation."""
        if not self._llm_client:
            return {"action": "error", "reason": "No LLM client available"}
        
        # Build user message from observation
        user_message = self._build_user_message(observation)
        
        request = LLMRequest(
            prompt=user_message,
            system_prompt=self.instructions,
            tier=self._resolve_tier(),
        )
        response = await self._llm_client.complete(request)
        
        return {
            "action": "execute",
            "llm_output": response.text,
            "tier_used": response.tier,
        }
    
    async def act(self, decision: dict) -> dict:
        """Execute based on LLM decision. Override for structured output."""
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}
        return {
            "success": True,
            "result": decision.get("llm_output", ""),
        }
    
    async def report(self, result: dict) -> IntentResult:
        """Package result as IntentResult."""
        return IntentResult(
            agent_id=self.id,
            success=result.get("success", False),
            result=result.get("result"),
            error=result.get("error"),
            confidence=self.confidence,
        )
    
    def _build_user_message(self, observation: dict) -> str:
        """Build the user message from the observation dict.
        Override in subclasses for custom formatting."""
        parts = [f"Intent: {observation.get('intent', 'unknown')}"]
        if observation.get("params"):
            parts.append(f"Parameters: {observation['params']}")
        if observation.get("context"):
            parts.append(f"Context: {observation['context']}")
        return "\n".join(parts)
    
    def _resolve_tier(self) -> str:
        """Determine which LLM tier to use. Default: None (use config default).
        Override in subclasses for tier-specific routing."""
        return None
    
    async def handle_intent(self, message: IntentMessage) -> IntentResult:
        """Full lifecycle: perceive → decide → act → report."""
        observation = await self.perceive(message)
        decision = await self.decide(observation)
        result = await self.act(decision)
        return await self.report(result)
```

Key principles:
- **The mesh is the toolbox.** `CognitiveAgent` does NOT get embedded tools for file I/O, HTTP, shell. It dispatches sub-intents through `self._runtime.intent_bus.broadcast()` to existing tool agents. The `_runtime` reference (same pattern as designed agents, AD-147) is the interface.
- **Instructions are sovereign.** Each agent's `instructions` are its own — no shared system-wide personality or template. Two cognitive agents may reason differently. The mesh governs *outcomes* (trust, consensus); *process* is sovereign.
- **LLM tier is configurable.** `_resolve_tier()` returns `None` by default (uses config default tier). Subclasses can override for tier-specific routing (e.g., an analyzer agent might always use `"standard"` tier).
- **`act()` is the extension point.** The base `act()` returns the raw LLM output. Subclasses override `act()` to parse structured output, dispatch sub-intents, or perform multi-step reasoning.

**Run tests after this step: `uv run pytest tests/ -v` — all 1073 existing tests must still pass.**

---

### Step 2: Update `BaseAgent` (AD-192)

**File:** `src/probos/substrate/agent.py`

Add `instructions: str | None = None` as a class attribute on `BaseAgent`. This is a backward-compatible addition — all existing agents ignore it.

Ensure `**kwargs` passthrough in `BaseAgent.__init__` does NOT consume `instructions` — let it flow through to subclasses that need it. If `instructions` is already in `kwargs`, it should be accessible to subclasses but not stored on `BaseAgent` instances unless the subclass explicitly handles it.

**Run tests: all 1073 must pass.**

---

### Step 3: Update `AgentDesigner` to Produce `CognitiveAgent` Subclasses (AD-193, AD-194)

**File:** `src/probos/cognitive/agent_designer.py`

This is the critical integration point. Currently, `AgentDesigner` generates full `BaseAgent` subclasses with complete `act()` logic. Change it to generate `CognitiveAgent` subclasses where the LLM does the reasoning at runtime.

**AD-193: AgentDesigner generates CognitiveAgent subclasses.** The generated code template changes from:
- **Before:** `class FooAgent(BaseAgent)` with hardcoded `act()` logic and `self._llm_client` usage inline
- **After:** `class FooAgent(CognitiveAgent)` with `instructions = "..."` class attribute and a minimal `act()` override that parses the LLM's output for the specific intent

The `instructions` string is the core output of the design process — it's what the LLM generates instead of procedural code. The instructions tell the cognitive agent *how to reason about its domain*, not *what code to execute*.

**AD-194: Design prompt rewrite for instructions-first generation.** Rewrite the `AgentDesigner` prompt template to ask the LLM to generate:
1. A `CognitiveAgent` subclass (not `BaseAgent`)
2. An `instructions` class attribute — a detailed system prompt describing the agent's reasoning behavior, domain expertise, output format expectations, and constraints
3. `intent_descriptors` with appropriate metadata
4. `agent_type` and `_handled_intents`
5. A `perceive()` override if the intent needs custom observation packaging (optional — base class default is usually fine)
6. An `act()` override that parses the LLM's decision output into a structured `IntentResult`-compatible dict (the base class `decide()` handles the LLM call; `act()` handles the parsing)
7. The import line: `from probos.cognitive.cognitive_agent import CognitiveAgent`

The generated `instructions` should include:
- What domain this agent covers
- What output format the agent should produce (so `act()` can parse it reliably)
- What constraints the agent operates under
- How the agent should handle edge cases and errors
- That the agent should be concise and structured in its responses

**Do NOT change the `AgentDesigner` constructor signature or public API.** The `design()` method still takes the same inputs and returns source code + metadata. The change is in *what code it generates*.

Example of generated code shape (illustrative, not exact):

```python
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentDescriptor, IntentMessage, IntentResult

class TextSummarizerAgent(CognitiveAgent):
    agent_type = "text_summarizer"
    _handled_intents = {"summarize_text"}
    instructions = (
        "You are a text summarization specialist. "
        "Given text content, produce a concise summary. "
        "Output format: JSON with keys 'summary' (string) and 'key_points' (list of strings). "
        "Keep summaries under 3 sentences. "
        "If the input is too short to summarize, return the original text as the summary."
    )
    intent_descriptors = [
        IntentDescriptor(
            name="summarize_text",
            params=["text"],
            description="Summarize the given text into key points",
            requires_consensus=False,
            requires_reflect=True,
            tier="domain",
        )
    ]
    
    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}
        llm_output = decision.get("llm_output", "")
        # Parse LLM output — the instructions asked for JSON
        try:
            import json
            parsed = json.loads(llm_output)
            return {"success": True, "result": parsed}
        except (json.JSONDecodeError, KeyError):
            return {"success": True, "result": llm_output}
```

**Run tests: all 1073 must pass. Existing designed-agent tests must not break.**

---

### Step 4: Update `CodeValidator` Schema Conformance (AD-195)

**File:** `src/probos/cognitive/code_validator.py`

**AD-195: CodeValidator accepts both BaseAgent and CognitiveAgent subclasses.** The existing schema check verifies the generated class is a `BaseAgent` subclass. Update it to also accept `CognitiveAgent` subclasses. Since `CognitiveAgent` extends `BaseAgent`, this may already work via inheritance — verify. Also ensure the validator:
- Accepts `from probos.cognitive.cognitive_agent import CognitiveAgent` in the import whitelist (add `probos.cognitive.cognitive_agent` to `allowed_imports` if not already covered by the `probos` prefix)
- Does NOT require `perceive`/`decide`/`act`/`report` method definitions on `CognitiveAgent` subclasses (these are inherited from the base class — only `act()` override is typical)
- Still requires `intent_descriptors`, `handle_intent` (inherited), `agent_type`, `_handled_intents`

**Run tests: all 1073 must pass.**

---

### Step 5: Update `SandboxRunner` (AD-196)

**File:** `src/probos/cognitive/sandbox.py`

**AD-196: SandboxRunner discovers CognitiveAgent subclasses.** The sandbox currently discovers `BaseAgent` subclasses via `issubclass(obj, BaseAgent)`. Since `CognitiveAgent` extends `BaseAgent`, this should work automatically — but verify. The sandbox also needs:
- `CognitiveAgent` importable in the sandbox execution context — add it to the namespace injected during dynamic module loading
- The synthetic `IntentMessage` test still works (the `handle_intent()` lifecycle runs through `perceive → decide → act → report`)
- LLM client forwarding works for `CognitiveAgent` instances (the `_llm_client` kwarg pattern is the same as current designed agents)

**Run tests: all 1073 must pass.**

---

### Step 6: Update `MockLLMClient` Patterns (AD-197)

**File:** `src/probos/cognitive/llm_client.py`

**AD-197: MockLLMClient cognitive agent patterns.** Add patterns so `CognitiveAgent` instances work in tests without live LLM:

1. **`agent_design` pattern update** — the existing `agent_design` mock response generates `BaseAgent` subclass code. Update it to generate `CognitiveAgent` subclass code matching the new template from Step 3. The mock should produce a valid `CognitiveAgent` subclass with `instructions`, `intent_descriptors`, and a minimal `act()` override.

2. **`cognitive_agent_decide` pattern** (new) — when a `CognitiveAgent` calls `decide()`, the LLM request has a system prompt (the agent's `instructions`) and a user message (the observation). Add a mock pattern that matches requests with a non-empty `system_prompt` containing keywords like "agent" or common instruction patterns, returning a reasonable mock response. Keep this generic — the pattern should work for any cognitive agent's instructions.

**Run tests: all 1073 must pass.**

---

### Step 7: Update Runtime Wiring (AD-198)

**File:** `src/probos/runtime.py`

**AD-198: Runtime creates CognitiveAgent pools with LLM client + runtime injection.** `_create_designed_pool()` already injects `llm_client` and `runtime` into spawned agents (AD-115, AD-147). Verify this works for `CognitiveAgent` subclasses — the kwargs pattern should be identical. If `CognitiveAgent.__init__` pops `instructions` from kwargs before calling `super().__init__(**kwargs)`, the runtime doesn't need to change. But verify:
- `register_agent_type()` works with `CognitiveAgent` subclasses
- `_collect_intent_descriptors()` picks up cognitive agent descriptors (they're `domain` tier, non-empty descriptors — should work via existing Phase 14d logic)
- Descriptor refresh after registration includes the new cognitive agent's intents
- `_set_probationary_trust()` applies normally

If `_create_designed_pool()` or `register_agent_type()` need changes, keep them minimal and backward-compatible.

**Run tests: all 1073 must pass.**

---

### Step 8: Tests (target: 1105+ total)

Write comprehensive tests across these test files:

**`tests/test_cognitive_agent.py`** (new) — ~20 tests:
- `CognitiveAgent` raises `ValueError` without instructions
- `CognitiveAgent` raises `ValueError` with empty string instructions
- `CognitiveAgent` accepts instructions via class attribute
- `CognitiveAgent` accepts instructions via `__init__` kwarg (overrides class attr)
- `CognitiveAgent` tier defaults to `"domain"`
- `CognitiveAgent` has correct lifecycle: perceive → decide → act → report
- `perceive()` packages intent correctly
- `decide()` calls LLM with instructions as system prompt
- `decide()` returns error dict when no LLM client
- `act()` returns success with LLM output
- `act()` returns error on error decision
- `report()` produces valid `IntentResult`
- `handle_intent()` runs full lifecycle end-to-end
- `_build_user_message()` formats observation correctly
- `_resolve_tier()` returns None by default
- Subclass with custom `act()` override works
- Subclass with custom `_resolve_tier()` override works
- Subclass with custom `perceive()` override works
- `instructions` field on `BaseAgent` is `None` by default
- `BaseAgent` subclasses (existing tool agents) are unaffected by `instructions` field
- CognitiveAgent with `_runtime` reference can be created

**`tests/test_agent_designer_cognitive.py`** (new) — ~10 tests:
- `AgentDesigner` generates `CognitiveAgent` subclass code (contains `CognitiveAgent` in source)
- Generated code has `instructions` class attribute
- Generated code has valid `intent_descriptors`
- Generated code has `agent_type` and `_handled_intents`
- Generated code passes `CodeValidator`
- Generated code passes `SandboxRunner` with MockLLMClient
- Generated code produces `CognitiveAgent` instance (not plain `BaseAgent`)
- `CodeValidator` accepts `CognitiveAgent` import
- `CodeValidator` does not require all 4 lifecycle methods on CognitiveAgent subclass
- End-to-end: design → validate → sandbox → register → handle intent

**Update existing tests if needed** — any test that checks the `agent_design` MockLLMClient pattern may need updating to match the new `CognitiveAgent` template. Check:
- `tests/test_self_mod.py`
- `tests/test_agent_designer.py` (if it exists)
- `tests/test_sandbox.py`
- `tests/test_code_validator.py`

**Run final test suite: `uv run pytest tests/ -v` — target 1105+ tests passing (1073 existing + ~32 new). All 11 skipped tests remain skipped (live LLM tests).**

---

## AD Summary

| AD | Decision |
|----|----------|
| AD-191 | `CognitiveAgent(BaseAgent)` base class: `decide()` invokes LLM with `instructions` as system prompt + observation as user message. Full perceive/decide/act/report lifecycle preserved. `act()` is the subclass extension point for structured output parsing. `_resolve_tier()` returns None (config default) |
| AD-192 | `instructions: str | None = None` on `BaseAgent` (class attribute). Tool agents ignore it. `CognitiveAgent` requires non-empty instructions — raises `ValueError` otherwise. kwargs override for runtime-provided instructions |
| AD-193 | `AgentDesigner` generates `CognitiveAgent` subclasses. Instructions string is the core design output. Minimal `act()` override for output parsing. No more fully-generated procedural `act()` logic |
| AD-194 | Design prompt rewrite: LLM generates instructions (reasoning prompt) instead of procedural code. The cognitive agent reasons at runtime, not at design time |
| AD-195 | `CodeValidator` accepts `CognitiveAgent` subclasses. Does not require all 4 lifecycle methods when parent provides them. `probos.cognitive.cognitive_agent` in import whitelist |
| AD-196 | `SandboxRunner` discovers and tests `CognitiveAgent` subclasses via existing `BaseAgent` inheritance. `CognitiveAgent` added to sandbox namespace |
| AD-197 | `MockLLMClient` updated: `agent_design` pattern generates `CognitiveAgent` code, new `cognitive_agent_decide` pattern for testing cognitive agent LLM calls |
| AD-198 | Runtime `_create_designed_pool()` works for `CognitiveAgent` via existing kwargs injection (`llm_client`, `runtime`). No API changes needed |

---

## Do NOT Build

- **Cognitive agent archetypes** (analyzer, critic, planner, synthesizer) — Phase 15b
- **Domain-aware skill attachment** (StrategyRecommender scoring cognitive agent instructions against skills) — Phase 15b
- **Consensus for cognitive outputs** (additional consensus gates on cognitive agent results) — Phase 15b
- **Domain meshes** or mesh-level organization — future phase
- **Changes to existing tool agents** — FileReaderAgent, ShellCommandAgent, etc. remain exactly as they are
- **Changes to the decomposer** — decomposition logic unchanged
- **Changes to the StrategyRecommender** — strategy selection unchanged (still recommends `new_agent` or `add_skill`)
- **New slash commands** — no new shell commands in this phase

---

## Milestone

Demonstrate the following end-to-end:

1. A `CognitiveAgent` subclass is instantiated with custom `instructions` and a `MockLLMClient`
2. It receives an `IntentMessage` via `handle_intent()`
3. `perceive()` packages the intent as an observation
4. `decide()` sends the observation to the LLM with `instructions` as system prompt
5. `act()` parses the LLM response
6. `report()` returns a valid `IntentResult` with the result
7. The agent participates in the normal trust/confidence/tier framework (domain tier, Bayesian trust, confidence tracking)

And separately:

8. `AgentDesigner` (via MockLLMClient) generates a `CognitiveAgent` subclass
9. `CodeValidator` passes the generated code
10. `SandboxRunner` successfully loads and test-executes the generated agent
11. The generated agent can be registered in the runtime and handle intents

---

## Update PROGRESS.md When Done

Add Phase 15a section with:
- AD decisions (AD-191 through AD-198)
- Files changed/created table
- Test count (target: 1105+)
- Update the Current Status line at the top
- Update the What's Been Built tables for new/changed files
- Mark the Phase 15 Cognitive Agents roadmap item as partially complete (Phase 15a done, 15b pending)
