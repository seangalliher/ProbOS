# Phase 15b — Domain-Aware Skill Attachment

## Context

You are building Phase 15b of ProbOS, a probabilistic agent-native OS runtime. Read `PROGRESS.md` for full architectural context. Current state: **1109/1109 tests passing + 11 skipped. Latest AD: AD-198.**

Phase 15a introduced `CognitiveAgent` — agents whose `decide()` consults an LLM guided by per-agent `instructions`. Phase 15b wires the skill system so skills are attached to the cognitive agent whose domain best matches the new capability, rather than always to the generic `SkillBasedAgent` dispatcher. This makes skills more effective (the cognitive agent's domain context is semantically adjacent) and more discoverable (the agent's existing descriptors are related to the new skill).

**This is a wiring change between existing subsystems — no new infrastructure needed.** The StrategyRecommender already uses `compute_similarity()` (AD-175). CognitiveAgent already has `_llm_client` and `handle_intent()`. The runtime already has `_add_skill_to_agents()`. This phase connects them.

---

## Pre-Build Audit

Before writing any code, verify:

1. **Latest AD number in PROGRESS.md** — confirm AD-198 is the latest. Phase 15b AD numbers start at **AD-199**. If AD-198 is NOT the latest, adjust all AD numbers in this prompt upward accordingly.
2. **Test count** — confirm 1109 tests pass before starting: `uv run pytest tests/ -v`
3. **Read these files thoroughly:**
   - `src/probos/cognitive/cognitive_agent.py` — understand the Phase 15a CognitiveAgent: `handle_intent()`, `instructions`, `_llm_client`, `_handled_intents`, `intent_descriptors`
   - `src/probos/substrate/skill_agent.py` — understand `SkillBasedAgent.add_skill()`, `remove_skill()`, `_skills` dict, how `handle_intent()` dispatches to skill handlers, the instance+class level descriptor sync pattern (AD-128)
   - `src/probos/cognitive/strategy.py` — understand `StrategyRecommender`, `StrategyOption.target_agent_type`, how `add_skill` vs `new_agent` strategies are scored, `compute_similarity()` usage (AD-175), the `_llm_equipped_types` filtering
   - `src/probos/cognitive/self_mod.py` — understand `SelfModificationPipeline.handle_add_skill()`, the `add_skill_fn` callback, `DesignedAgentRecord`
   - `src/probos/runtime.py` — understand `_add_skill_to_agents()` (filters by `isinstance(agent, SkillBasedAgent)`), `_get_llm_equipped_types()`, how the strategy menu is presented and how the chosen strategy flows into `_handle_self_mod()`
   - `src/probos/types.py` — understand `Skill` (descriptor, source_code, compiled handler)
   - `src/probos/mesh/capability.py` — understand `compute_similarity()` (embedding-based with bag-of-words fallback)

---

## What To Build

### Step 1: Add Skill Support to CognitiveAgent (AD-199)

**File:** `src/probos/cognitive/cognitive_agent.py`

**AD-199: CognitiveAgent skill attachment.** Add `add_skill()` and `remove_skill()` to `CognitiveAgent`, following the same pattern as `SkillBasedAgent` (AD-128). Skills are stored in a `_skills: dict[str, Skill]` mapping intent name to Skill object. `add_skill()` updates both instance-level AND class-level `_handled_intents` and `intent_descriptors` — this is critical for the decomposer's dynamic intent discovery to pick up the new capability.

`handle_intent()` must check skills first: if `message.intent` is in `_skills`, dispatch directly to the skill handler (same pattern as `SkillBasedAgent`), passing `llm_client=self._llm_client`. If no skill matches, fall through to the normal cognitive lifecycle (`perceive → decide → act → report`).

Design details:

```python
# In CognitiveAgent.__init__:
self._skills: dict[str, Skill] = {}

def add_skill(self, skill: Skill) -> None:
    """Attach a skill to this cognitive agent.
    Updates both instance and class-level descriptors for decomposer discovery."""
    self._skills[skill.descriptor.name] = skill
    self._handled_intents.add(skill.descriptor.name)
    # Instance-level descriptor update
    if skill.descriptor not in self.intent_descriptors:
        self.intent_descriptors.append(skill.descriptor)
    # Class-level sync for decomposer discovery
    cls = type(self)
    if not hasattr(cls, '_handled_intents') or cls._handled_intents is self._handled_intents:
        pass  # Already shared reference
    else:
        cls._handled_intents = cls._handled_intents | {skill.descriptor.name}
    if skill.descriptor not in cls.intent_descriptors:
        cls.intent_descriptors = [*cls.intent_descriptors, skill.descriptor]

def remove_skill(self, intent_name: str) -> None:
    """Remove a skill from this cognitive agent."""
    if intent_name in self._skills:
        removed = self._skills.pop(intent_name)
        self._handled_intents.discard(intent_name)
        self.intent_descriptors = [
            d for d in self.intent_descriptors
            if d.name != intent_name
        ]
        # Class-level cleanup
        cls = type(self)
        cls._handled_intents = cls._handled_intents - {intent_name}
        cls.intent_descriptors = [
            d for d in cls.intent_descriptors
            if d.name != intent_name
        ]

async def handle_intent(self, message: IntentMessage) -> IntentResult:
    """Skills first, then cognitive lifecycle."""
    # Skill dispatch — direct handler call, no LLM reasoning
    if message.intent in self._skills:
        skill = self._skills[message.intent]
        return await skill.handler(message, llm_client=self._llm_client)
    # Cognitive lifecycle — LLM-guided reasoning
    observation = await self.perceive(message)
    decision = await self.decide(observation)
    result = await self.act(decision)
    return await self.report(result)
```

**Important:** Study the exact `SkillBasedAgent` implementation before writing this. The class-level vs instance-level descriptor sync is subtle — get it right by matching the proven pattern. The code above is illustrative guidance, not copy-paste. Read the actual `SkillBasedAgent.add_skill()` and replicate its descriptor sync mechanics precisely.

**Do NOT extract a shared mixin.** Two agent types with skill support doesn't justify a mixin abstraction yet. Keep CognitiveAgent and SkillBasedAgent as independent implementations of the same pattern. If a third skill-bearing agent type emerges, then extract a mixin.

**Run tests after this step: `uv run pytest tests/ -v` — all 1109 existing tests must still pass.**

---

### Step 2: StrategyRecommender Domain-Aware Scoring (AD-200, AD-201)

**File:** `src/probos/cognitive/strategy.py`

**AD-200: StrategyRecommender scores cognitive agents as skill targets.** When evaluating `add_skill` strategies, the recommender currently hardcodes `target_agent_type = "skill_agent"`. Change this: score each registered agent type that has LLM capability (from `_llm_equipped_types`) AND has non-empty `instructions` (i.e., is a CognitiveAgent or subclass) by computing semantic similarity between the new intent description and the agent's `instructions`. Use the existing `compute_similarity()` function (same one used for intent-descriptor scoring in AD-175).

The scoring logic:
1. For each LLM-equipped agent type, check if it has `instructions` (class attribute). If it does, compute `similarity = compute_similarity(intent_description, agent_instructions)`.
2. The highest-scoring cognitive agent above a minimum threshold (0.3) becomes the `add_skill` target. This produces a `StrategyOption` with `target_agent_type` set to the matching cognitive agent's `agent_type`.
3. If no cognitive agent scores above the threshold, fall back to `target_agent_type = "skill_agent"` (the generic dispatcher).
4. The `add_skill` strategy's confidence should incorporate the domain match score — a strong domain match increases confidence in the `add_skill` strategy relative to the `new_agent` fallback.

**AD-201: StrategyRecommender accepts agent registry for instructions lookup.** The recommender needs access to registered agent classes to read their `instructions`. Add an optional `agent_classes: dict[str, type]` parameter (mapping agent_type string to agent class) that the runtime passes in. The recommender iterates over these to find cognitive agents with matching domains. If `agent_classes` is not provided, fall back to the current behavior (hardcoded `skill_agent` target).

Design details for the recommender's `recommend()` method (adapt to existing method signature — do NOT rename):

```python
def _find_best_skill_target(self, intent_name: str, intent_description: str) -> tuple[str, float]:
    """Find the best cognitive agent to attach a skill to.
    Returns (target_agent_type, domain_match_score).
    Falls back to ("skill_agent", 0.0) if no cognitive match."""
    if not self._agent_classes:
        return "skill_agent", 0.0
    
    best_type = "skill_agent"
    best_score = 0.0
    min_threshold = 0.3
    
    for agent_type, agent_cls in self._agent_classes.items():
        instructions = getattr(agent_cls, 'instructions', None)
        if not instructions:
            continue
        # Score intent description against agent's domain instructions
        score = compute_similarity(intent_description, instructions)
        if score > best_score and score >= min_threshold:
            best_score = score
            best_type = agent_type
    
    return best_type, best_score
```

Then in the `add_skill` strategy construction, use the result:

```python
target_type, domain_score = self._find_best_skill_target(intent_name, intent_desc)
# Incorporate domain_score into confidence
# A strong domain match makes add_skill more confident
confidence = base_confidence + (domain_score * 0.2)  # adjust weight as appropriate
option = StrategyOption(
    strategy="add_skill",
    target_agent_type=target_type,
    ...
)
```

**The code above is guidance, not copy-paste.** Read the actual `StrategyRecommender` implementation and integrate cleanly with the existing scoring logic. The key change is: `target_agent_type` is no longer always `"skill_agent"` — it's the best-matching agent type.

**Run tests: all 1109 must pass. Existing strategy recommender tests must not break.**

---

### Step 3: Runtime `_add_skill_to_agents()` Generalization (AD-202)

**File:** `src/probos/runtime.py`

**AD-202: `_add_skill_to_agents()` accepts any skill-capable agent type.** Currently this method filters by `isinstance(agent, SkillBasedAgent)`. Generalize it:

1. Accept a `target_agent_type: str` parameter (from the `StrategyOption.target_agent_type`).
2. Find agents of the target type across all pools (not just the `skills` pool).
3. Call `add_skill()` on matching agents — this works for both `SkillBasedAgent` and `CognitiveAgent` instances since both now have `add_skill()`.
4. If no agents of the target type are found, fall back to `SkillBasedAgent` instances in the `skills` pool (preserving current behavior as safety net).

Also update the call site — wherever `_add_skill_to_agents()` is invoked after skill design, pass the `target_agent_type` from the strategy recommendation.

Update `_get_llm_equipped_types()` if needed to include `CognitiveAgent` subclasses (they should already be included since they have `_llm_client`).

Wire the `agent_classes` dict into the `StrategyRecommender` constructor — the runtime has access to all registered agent templates in `self._agent_templates` (or wherever they're stored). Pass the relevant subset to the recommender.

**Run tests: all 1109 must pass.**

---

### Step 4: Update StrategyRecommender Presentation (AD-203)

**File:** `src/probos/cognitive/strategy.py` and/or `src/probos/experience/shell.py` (renderer)

**AD-203: Strategy menu shows target agent when not skill_agent.** When the strategy menu is presented to the user (the renderer's strategy display), the `add_skill` option should indicate which agent type will receive the skill. Currently it just says "Add skill to existing agent" or similar. When the target is a cognitive agent, the label should communicate this — e.g., "Add skill to text_analyzer agent" instead of "Add skill to skill_agent". The `StrategyOption.target_agent_type` field already carries this information; this step ensures it's visible to the user.

This is a display-only change. Check how `StrategyOption` is currently rendered (likely in `shell.py` or `panels.py`) and update the label/reason to include the target agent type when it's not `"skill_agent"`.

**Run tests: all 1109 must pass.**

---

### Step 5: Tests (target: 1140+ total)

Write comprehensive tests across these test files:

**`tests/test_cognitive_agent_skills.py`** (new) — ~15 tests:
- `CognitiveAgent` starts with empty `_skills` dict
- `add_skill()` adds skill to `_skills`, `_handled_intents`, `intent_descriptors`
- `add_skill()` updates class-level descriptors (decomposer discovery)
- `remove_skill()` removes from all three locations
- `remove_skill()` for non-existent intent is a no-op (no error)
- `handle_intent()` dispatches to skill handler when intent matches skill
- `handle_intent()` falls through to cognitive lifecycle when intent doesn't match skill
- `handle_intent()` passes `llm_client` to skill handler
- Skill handler receives correct `IntentMessage`
- Multiple skills can coexist on one cognitive agent
- Adding duplicate skill (same intent name) replaces the previous one
- Skill-dispatched intent returns valid `IntentResult`
- Cognitive lifecycle intent returns valid `IntentResult` (after skill check misses)

**`tests/test_strategy_domain_aware.py`** (new) — ~15 tests:
- Recommender with no agent_classes falls back to `skill_agent` target
- Recommender with no cognitive agents falls back to `skill_agent` target
- Recommender scores cognitive agent instructions against intent description
- Highest-scoring cognitive agent above threshold becomes target
- Below-threshold cognitive agents fall back to `skill_agent`
- Domain match score incorporated into `add_skill` confidence
- Strong domain match produces higher confidence than weak match
- `target_agent_type` set to matching cognitive agent's `agent_type`
- Multiple cognitive agents — best match wins
- SkillBasedAgent (no `instructions`) is not scored as cognitive target
- Tool agents (no `instructions`) are ignored in scoring
- Existing behavior preserved when no cognitive agents registered
- `_find_best_skill_target()` returns `("skill_agent", 0.0)` when no match
- Strategy option label/reason includes target agent type

**`tests/test_runtime_skill_routing.py`** (new) — ~5 tests:
- `_add_skill_to_agents()` with `target_agent_type="skill_agent"` works (backward compat)
- `_add_skill_to_agents()` with cognitive agent type finds correct agents
- `_add_skill_to_agents()` falls back to SkillBasedAgent when target type not found
- End-to-end: strategy recommends cognitive agent → skill designed → skill attached to cognitive agent → intent handled
- `_get_llm_equipped_types()` includes CognitiveAgent subclasses

**Update existing tests if needed** — check:
- `tests/test_self_mod.py` — strategy/skill pipeline tests
- `tests/test_strategy.py` (if it exists) — recommender tests
- Any test that asserts `target_agent_type == "skill_agent"` may need updating to account for the new behavior (only when cognitive agents are registered — existing tests with no cognitive agents should still produce `skill_agent` target)

**Run final test suite: `uv run pytest tests/ -v` — target 1140+ tests passing (1109 existing + ~35 new). All 11 skipped tests remain skipped (live LLM tests).**

---

## AD Summary

| AD | Decision |
|----|----------|
| AD-199 | `CognitiveAgent` skill attachment: `add_skill()` / `remove_skill()` following SkillBasedAgent pattern (AD-128). `_skills` dict, instance+class descriptor sync. `handle_intent()` checks skills first, falls through to cognitive lifecycle |
| AD-200 | StrategyRecommender domain-aware scoring: scores cognitive agents' `instructions` against new intent via `compute_similarity()`. Best match above 0.3 threshold becomes `target_agent_type`. Falls back to `skill_agent` |
| AD-201 | StrategyRecommender accepts `agent_classes: dict[str, type]` for instructions lookup. Runtime passes registered agent templates |
| AD-202 | Runtime `_add_skill_to_agents()` generalized: accepts `target_agent_type`, searches all pools, falls back to SkillBasedAgent if target type not found |
| AD-203 | Strategy menu shows target agent type in label/reason when target is a cognitive agent (display-only) |

---

## Do NOT Build

- **Cognitive agent archetypes** (analyzer, critic, planner, synthesizer) — Phase 15c
- **Instructions-guided skill execution** (cognitive agent LLM reasoning wrapping the skill handler) — future enhancement; skills execute directly for now
- **Shared SkillMixin** between CognitiveAgent and SkillBasedAgent — premature abstraction; two implementations is fine
- **StrategyRecommender changes to `new_agent` strategy** — new_agent targeting is unchanged
- **Changes to SkillDesigner or SkillValidator** — skill generation and validation are unchanged
- **Changes to the decomposer or PromptBuilder** — decomposition logic unchanged
- **New slash commands** — no new shell commands in this phase
- **Domain meshes** or mesh-level organization — future phase
- **Changes to existing tool agents** — FileReaderAgent, ShellCommandAgent, etc. remain as-is

---

## Milestone

Demonstrate the following end-to-end:

1. A `CognitiveAgent` subclass with `instructions = "You are a data analysis specialist..."` is registered in the runtime
2. An unhandled intent like `"analyze_csv"` triggers the self-mod pipeline
3. The `StrategyRecommender` scores the cognitive agent's instructions against the new intent description
4. Because "analyze_csv" is semantically close to "data analysis specialist," the recommender recommends `add_skill` with `target_agent_type` set to the cognitive agent's type (not `"skill_agent"`)
5. The skill is designed, validated, and attached to the cognitive agent via `add_skill()`
6. The cognitive agent's `handle_intent()` dispatches the new intent to the skill handler
7. The cognitive agent still handles its original intents (those without matching skills) through the normal cognitive lifecycle
8. If no cognitive agent matches, skill falls back to `SkillBasedAgent` (existing behavior preserved)

---

## Update PROGRESS.md When Done

Add Phase 15b section with:
- AD decisions (AD-199 through AD-203)
- Files changed/created table
- Test count (target: 1140+)
- Update the Current Status line at the top
- Update the What's Been Built tables for changed files
- Note in the Phase 15 roadmap item that domain-aware skill attachment is now complete
