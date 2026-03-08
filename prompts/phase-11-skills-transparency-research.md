# Phase 11: Skills Architecture, Transparency & Web Research

**Goal:** Evolve ProbOS self-modification from "design a whole new agent" to a more intelligent, transparent, and research-informed pipeline. Three capabilities, in increasing scope:

1. **Transparency** — The user sees *why* the system recommends self-mod, what strategy it will use, and can choose between options before proceeding.
2. **Skills architecture** — Instead of always creating a new agent, ProbOS can add a skill (new intent handler) to an existing general-purpose agent. This is the brain-inspired approach: neurons gain new synaptic connections before the brain grows new structures.
3. **Web research** — Before designing an agent, ProbOS can optionally research documentation on the internet (via the existing `HttpFetchAgent`) to inform the design prompt with real API docs, examples, and best practices.

### Design Principle Alignment

This phase must respect the probabilistic-vs-governance principle (PROGRESS.md):

> *"Agents are not deterministic automata — they are probabilistic entities with Bayesian confidence, stochastic routing, and non-deterministic LLM-driven decision-making. Like humans with free will who still follow rules in a society, agents in the ProbOS ecosystem are probabilistic but must still follow consensus."*

Concretely:
- **Skills are probabilistic:** A skill-equipped agent uses LLM inference to decide *how* to handle a new intent — it doesn't follow a hardcoded rulebook. The skill's `handle` method is generated code that makes probabilistic decisions.
- **Strategy selection is governance:** The system recommends a strategy (new agent vs. add skill), but the *user* approves. This is collective governance — the system proposes, the human decides.
- **Research is probabilistic:** Web research results are context for the LLM, not deterministic templates. The LLM synthesizes documentation into agent code — it may produce different code from the same docs on different runs.
- **No deterministic overrides:** The strategy recommender uses heuristics (keyword overlap, capability proximity) to *suggest* — never to force. If the system recommends "add skill" but the user prefers "new agent," the user's choice governs.

### Foundational Governance Axioms

Three axioms underpin ProbOS's safety model (see PROGRESS.md for full rationale). This phase should formalize them as explicit, testable properties:

1. **Safety Budget:** Actions carry an implicit risk score; higher-risk actions require proportionally stronger consensus. The strategy recommender (Part A) should factor risk into its confidence scores — a strategy that requires fewer destructive actions should score higher, all else being equal. Research fetches (Part C) go through consensus precisely because external network access is a higher-risk action.

2. **Reversibility Preference:** When multiple strategies can achieve a goal, prefer the most reversible. The strategy recommender should score "add skill" higher than "create new agent" when both are viable — adding a skill is more reversible (a skill can be removed without destroying an agent pool). The decomposer already orders DAG nodes to front-load reads; this phase should ensure skill addition follows the same pattern.

3. **Minimal Authority:** Agents and skills request only the capabilities they need. Skills receive a scoped import whitelist (same as full agents). The `SkillBasedAgent` declares only the intents of its attached skills — not a blanket "handles everything." Research URLs are constrained to a domain whitelist. Designed skills start with the same probationary trust as designed agents.

These axioms are already partially implemented. This phase should add explicit test cases verifying them:
- Safety budget: strategy confidence reflects action risk (at least 1 test)
- Reversibility: add_skill preferred over new_agent when both viable (at least 1 test)
- Minimal authority: skill import whitelist enforced, URL domain whitelist enforced (existing security tests in Part C cover this)

---

## ⚠ AD Numbering

**Before starting**, check the latest AD number in PROGRESS.md. All architectural decisions in this phase start at the next available AD number. Do NOT reuse any existing AD numbers.

---

## ⚠ Pre-Build Audit

**Before writing any code**, read the following files to understand the current self-mod pipeline:

1. `src/probos/cognitive/agent_designer.py` — `AGENT_DESIGN_PROMPT` template, `AgentDesigner` class
2. `src/probos/cognitive/self_mod.py` — `SelfModificationPipeline`, `DesignedAgentRecord`, 9-step flow
3. `src/probos/cognitive/code_validator.py` — `CodeValidator` static analysis
4. `src/probos/cognitive/sandbox.py` — `SandboxRunner` functional testing
5. `src/probos/experience/renderer.py` — Self-mod UX flow (lines ~120-230): capability-gap detection, intent extraction, existing-agent routing, user approval prompt, design + execute
6. `src/probos/runtime.py` — `_extract_unhandled_intent()`, `_register_designed_agent()`, `_create_designed_pool()`
7. `src/probos/cognitive/decomposer.py` — `is_capability_gap()`, `_CAPABILITY_GAP_RE`
8. `src/probos/substrate/agent.py` — `BaseAgent` ABC, lifecycle methods, `intent_descriptors`
9. `src/probos/types.py` — `IntentDescriptor` fields
10. `src/probos/agents/http_fetch.py` — `HttpFetchAgent` for web research integration
11. `src/probos/cognitive/prompt_builder.py` — How intent tables and system prompts are assembled

Also read the Design Principle section in `PROGRESS.md` (search for "Probabilistic Agents, Consensus Governance").

---

## Deliverables

### Part A: Transparency — Strategy Proposals (smallest scope)

Right now, when ProbOS detects a capability gap, the renderer shows:

```
Intent: translate_text
Purpose: Translate text between languages
Create this agent? [y/N]:
```

This is opaque. The user doesn't know *why* a new agent is needed, what alternatives exist, or what the new agent will look like. Enhance this to show a strategy proposal with options.

#### A1. Create `src/probos/cognitive/strategy.py`

The strategy recommender analyzes the unhandled intent and proposes one or more strategies.

```python
from dataclasses import dataclass, field
from probos.types import IntentDescriptor


@dataclass
class StrategyOption:
    """A proposed strategy for handling an unhandled intent."""

    strategy: str  # "new_agent" or "add_skill"
    label: str  # Human-readable label, e.g., "Create new TranslateTextAgent"
    reason: str  # Why this strategy is recommended
    confidence: float  # 0.0-1.0 — how confident the recommender is
    target_agent_type: str | None = None  # For add_skill: which agent to extend
    is_recommended: bool = False  # Whether this is the top recommendation


@dataclass
class StrategyProposal:
    """A set of strategy options for handling an unhandled intent."""

    intent_name: str
    intent_description: str
    options: list[StrategyOption] = field(default_factory=list)

    @property
    def recommended(self) -> StrategyOption | None:
        """Return the recommended option, or None."""
        return next((o for o in self.options if o.is_recommended), None)


class StrategyRecommender:
    """Analyzes an unhandled intent and proposes strategies.

    Two strategies are available:

    1. **add_skill** — If an existing agent type in llm_equipped_types
       could plausibly handle the new intent (based on keyword overlap
       between the intent and the agent's existing descriptors), suggest
       adding a skill. Scored higher than new_agent when both are viable
       (reversibility preference — a skill can be removed without
       destroying an agent pool).
       Example: "translate_text" could be a skill on an LLM-equipped agent.
       Confidence: based on capability proximity + reversibility bonus.

    2. **new_agent** — Always available as a fallback. Confidence is higher
       when the intent has no overlap with existing capabilities.
       Example: "play_audio" has zero overlap with any existing agent.

    The recommender returns ALL viable options sorted by confidence.
    The user chooses. The system does NOT auto-select.
    """

    def __init__(
        self,
        intent_descriptors: list[IntentDescriptor],
        llm_equipped_types: set[str],
    ) -> None:
        """Initialize with current system's intent descriptors and
        the set of agent types that have LLM client access.

        The runtime constructs llm_equipped_types from the agent types
        it injected llm_client into (e.g., {"skill_agent", "introspection"}).
        """
        self._descriptors = intent_descriptors
        self._llm_equipped_types = llm_equipped_types

    def propose(
        self,
        intent_name: str,
        intent_description: str,
        parameters: dict[str, str],
    ) -> StrategyProposal:
        """Analyze the intent and return a StrategyProposal with options.

        Must always return at least one option (new_agent is always viable).
        Options sorted by confidence descending.
        The highest-confidence option has is_recommended=True.
        """

    def _keyword_overlap(self, intent_name: str, descriptor: IntentDescriptor) -> float:
        """Compute keyword overlap between intent name/description tokens
        and an existing descriptor's name/description tokens.

        Uses the same tokenization as attention relevance (AD-55):
        split on underscores and spaces, filter tokens < 3 chars,
        compute overlap ratio.
        """
```

**Key design constraints:**
- The recommender is heuristic, not omniscient. It uses keyword overlap and capability proximity as *signals*. The confidence scores reflect uncertainty — two options might both be 0.5-0.6 confidence, meaning the system genuinely doesn't know which is better. This is probabilistic by design.
- Only two strategies: `new_agent` and `add_skill`. No `delegate_existing` — delegation to an existing agent without code changes is a decomposer concern, not a self-modification concern. If the LLM can already route to an existing agent, it would have done so before reaching the capability gap detector.
- `llm_equipped_types` is passed explicitly by the runtime — no introspection of agent instances or guessing which agents have LLM access. The runtime knows because it injected the `llm_client`.

#### A2. Update `src/probos/experience/renderer.py` — Strategy Display

Replace the current bare `"Create this agent? [y/N]:"` prompt with a richer display:

```
╭─ Self-Modification Proposal ──────────────────────────╮
│                                                        │
│  Unhandled intent: translate_text                      │
│  Purpose: Translate text between languages             │
│                                                        │
│  Strategy options:                                     │
│                                                        │
│  [1] ★ Add skill to existing agent  (confidence: 0.7) │
│      Target: skill_agent (has LLM access)              │
│      Reason: Translation is an LLM task — an existing  │
│      LLM-equipped agent can handle it with a new       │
│      intent handler.                                   │
│                                                        │
│  [2]   Create new TranslateTextAgent (confidence: 0.5) │
│      Reason: Dedicated agent for translation tasks.    │
│      Will be created with probationary trust (0.25).   │
│                                                        │
│  Choose strategy [1-2] or [n] to cancel:               │
╰────────────────────────────────────────────────────────╯
```

The renderer calls `StrategyRecommender.propose()` to get options, displays them with a Rich panel, and waits for user input. The user's choice determines which pipeline path is taken:

- **"1" (add_skill)** → calls the skill pipeline (Part B)
- **"2" (new_agent)** → calls the existing `SelfModificationPipeline.handle_unhandled_intent()`
- **"n"** → cancels self-mod entirely

If only one option is viable (e.g., no skills pool exists because self_mod is disabled, or no LLM-equipped agents exist), skip the menu and show a simpler confirmation prompt (but still show the reason and confidence).

#### A3. Tests — `tests/test_strategy.py`

```
StrategyRecommender tests:
- propose() always returns at least one option (new_agent fallback) (1 test)
- Intent with zero keyword overlap → new_agent has highest confidence (1 test)
- Intent overlapping LLM-equipped agent → add_skill recommended (1 test)
- add_skill confidence higher than new_agent when both viable (reversibility) (1 test)
- Multiple options returned sorted by confidence (1 test)
- recommended property returns is_recommended=True option (1 test)
- recommended property returns None when no options (edge case) (1 test)
- keyword_overlap tokenization matches AD-55 pattern (1 test)
- StrategyOption fields roundtrip (1 test)
- StrategyProposal with empty options (1 test)
- llm_equipped_types filters correctly — agent type not in set excluded from add_skill (1 test)
```

~11 tests.

---

### Part B: Skills Architecture (medium scope)

Currently, self-modification always creates a brand-new agent type with its own pool. But many capabilities are just "ask the LLM a question with specific instructions" — translation, summarization, code explanation, sentiment analysis, etc. These don't need dedicated agent types. They need **skills** — modular intent handlers that can be attached to an existing agent.

This is brain-inspired: the brain doesn't grow a new region for every new task. It forms new synaptic connections in existing regions. A general-purpose cortical area handles many different tasks by learning new activation patterns.

#### B1. Add `Skill` type to `src/probos/types.py`

```python
from typing import Callable, Awaitable

@dataclass
class Skill:
    """A modular intent handler that can be attached to an agent.

    Unlike a full agent (which has its own pool, lifecycle, and identity),
    a skill is a piece of code that extends an existing agent's capabilities.
    The agent discovers its skills via its _skills list and dispatches
    matching intents to the skill's handler.
    """

    name: str  # Intent name this skill handles, e.g., "translate_text"
    descriptor: IntentDescriptor  # Intent metadata for decomposer
    source_code: str  # Python source of the handler function
    handler: Callable[..., Awaitable] | None = None  # Compiled async callable (set after validation)
    created_at: float = 0.0
    origin: str = "designed"  # "designed" or "built_in"
```

#### B2. Create `src/probos/cognitive/skill_designer.py`

Designs skill code (a single async function) instead of a full agent class.

```python
SKILL_DESIGN_PROMPT = """You are the cognitive layer of ProbOS, a probabilistic agent-native OS.
The system received an intent that can be handled by adding a skill to an existing agent.

SKILL TO CREATE:
  Name: {intent_name}
  Description: {intent_description}
  Parameters: {parameters}
  Target agent type: {target_agent_type}

{research_context}

Generate a Python async function that handles this intent.
The function receives an IntentMessage and an optional LLM client,
and returns an IntentResult.

TEMPLATE:

```python
from probos.types import IntentMessage, IntentResult

async def handle_{intent_name}(intent: IntentMessage, llm_client=None) -> IntentResult:
    \"\"\"Handle {intent_name} intent.\"\"\"
    params = intent.params
    # YOUR IMPLEMENTATION HERE
    return IntentResult(
        agent_id="skill",
        intent=intent.intent,
        success=True,
        data={{"result": "..."}},
    )
```

RULES:
- Only use imports from this whitelist: {allowed_imports}
- You have access to `llm_client` for LLM inference — use it for intelligence tasks
- To call the LLM: `response = await llm_client.complete(LLMRequest(prompt="...", tier="fast"))`
- Import LLMRequest: `from probos.types import LLMRequest`
- Do NOT use subprocess, eval, exec, __import__, socket, ctypes
- Return the COMPLETE Python code, nothing else
- No markdown code fences, no explanation

Use the above research to inform your implementation.
If research context says "No research available.", rely on your training knowledge.
"""


class SkillDesigner:
    """Designs skill handler functions via LLM.

    Similar to AgentDesigner but generates a single async function
    instead of a full agent class. The generated function is validated
    by SkillValidator (same forbidden patterns) and tested in sandbox.
    """

    def __init__(self, llm_client, config: SelfModConfig) -> None:
        self._llm = llm_client
        self._config = config

    async def design_skill(
        self,
        intent_name: str,
        intent_description: str,
        parameters: dict[str, str],
        target_agent_type: str,
        research_context: str = "No research available.",
    ) -> str:
        """Generate skill handler source code.

        Returns raw Python source code string containing the handler function.
        """

    def _build_function_name(self, intent_name: str) -> str:
        """Convert intent_name like 'translate_text' to 'handle_translate_text'."""
```

#### B3. Create `src/probos/cognitive/skill_validator.py`

Validates skill code. Similar to `CodeValidator` but checks for a function instead of a class.

```python
class SkillValidator:
    """Validates generated skill handler code.

    Checks (similar to CodeValidator):
    1. Syntax validity
    2. Forbidden imports (not in whitelist)
    3. Forbidden patterns (regex)
    4. Schema conformance: has exactly one async function named handle_{intent_name}
    5. Function signature: takes (intent: IntentMessage, llm_client=None)
    6. No module-level side effects beyond imports and the function def
    """

    def __init__(self, config: SelfModConfig) -> None:
        self._allowed_imports = set(config.allowed_imports)
        self._forbidden_patterns = config.forbidden_patterns

    def validate(self, source_code: str, intent_name: str) -> list[str]:
        """Validate skill source code. Returns list of error strings.

        Empty list = validation passed.
        """
```

#### B4. Create `src/probos/substrate/skill_agent.py` — `SkillBasedAgent`

A general-purpose agent that dispatches intents to attached skills.

```python
from probos.substrate.agent import BaseAgent
from probos.types import IntentMessage, IntentResult, IntentDescriptor, Skill


class SkillBasedAgent(BaseAgent):
    """An agent that handles intents via attached skills.

    Unlike specialized agents (FileReaderAgent, ShellCommandAgent),
    the SkillBasedAgent doesn't have hardcoded intent handlers.
    It discovers its capabilities from its _skills list, which can
    be extended at runtime.

    Each skill is a compiled async function that takes an IntentMessage
    and optional LLM client, and returns an IntentResult.

    This is the brain-inspired approach: instead of growing new brain
    regions (new agent types), the existing neural substrate gains new
    synaptic connections (skills).
    """

    agent_type = "skill_agent"
    _handled_intents: set[str] = set()
    intent_descriptors: list[IntentDescriptor] = []

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._skills: list[Skill] = []
        self._llm_client = kwargs.get("llm_client")

    def add_skill(self, skill: Skill) -> None:
        """Attach a skill to this agent.

        Updates BOTH instance-level AND class-level _handled_intents
        and intent_descriptors so that both the agent's own dispatch
        and the template-based descriptor collection path work.

        The runtime must call decomposer.refresh_descriptors() after
        adding a skill to ensure the LLM sees the new intent.
        """
        self._skills.append(skill)

        # Instance-level update (for this agent's dispatch)
        self._handled_intents.add(skill.name)
        if skill.descriptor not in self.intent_descriptors:
            self.intent_descriptors.append(skill.descriptor)

        # Class-level update (for template-based descriptor collection in
        # _collect_intent_descriptors, which reads class.intent_descriptors)
        if skill.descriptor not in SkillBasedAgent.intent_descriptors:
            SkillBasedAgent.intent_descriptors.append(skill.descriptor)
        SkillBasedAgent._handled_intents.add(skill.name)

    def remove_skill(self, name: str) -> None:
        """Remove a skill by name.

        Updates both instance and class level. Class-level removal is
        safe because _add_skill_to_agents always adds to ALL instances —
        if a skill is removed, it's removed from all instances.
        """
        self._skills = [s for s in self._skills if s.name != name]
        self._handled_intents.discard(name)
        self.intent_descriptors = [
            d for d in self.intent_descriptors if d.name != name
        ]
        # Class-level cleanup
        SkillBasedAgent._handled_intents.discard(name)
        SkillBasedAgent.intent_descriptors = [
            d for d in SkillBasedAgent.intent_descriptors if d.name != name
        ]

    @property
    def skills(self) -> list[Skill]:
        """Return attached skills."""
        return list(self._skills)

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Dispatch intent to the matching skill handler.

        If no skill handles the intent, return None (decline).
        The skill handler receives the LLM client for intelligence tasks.
        """
        for skill in self._skills:
            if skill.name == intent.intent and skill.handler is not None:
                return await skill.handler(intent, llm_client=self._llm_client)
        return None

    # Lifecycle methods — minimal, agent is a dispatcher
    async def perceive(self, intent):
        return intent

    async def decide(self, observation):
        return observation

    async def act(self, plan):
        return plan

    async def report(self, result):
        return {"agent_id": self.id, "result": result}
```

**Key design decisions:**
- `add_skill()` updates BOTH instance-level AND class-level `_handled_intents` and `intent_descriptors`. This is critical because the existing `_collect_intent_descriptors()` reads from `self.spawner._templates.values()` which returns class-level descriptors. Without the class-level update, newly added skills would be invisible to the decomposer's template-based collection path.
- `remove_skill()` cleans up both levels. This is safe because `_add_skill_to_agents()` always adds skills to ALL instances in the pool — skills are not per-instance.
- Skills are probabilistic — the handler function uses LLM inference, not deterministic logic.

#### B5. Wire SkillBasedAgent into runtime — `src/probos/runtime.py`

**Only spawn the skills pool when `self_mod.enabled=True`:**

```python
# In start(), AFTER self_mod pipeline creation:
if self.config.self_mod.enabled:
    # ... (existing pipeline creation) ...
    self._spawn_pool("skills", SkillBasedAgent, 2, llm_client=self.llm_client)
```

Do NOT spawn the skills pool when self_mod is disabled. Idle agents with no skills waste pool slots and show up in `/agents` doing nothing.

Add methods:

```python
async def _add_skill_to_agents(self, skill: Skill) -> None:
    """Add a skill to all agents in the skills pool.

    After adding, refresh decomposer descriptors so the new intent
    is available for decomposition.
    """
    pool = self.pools.get("skills")
    if not pool:
        return
    for agent_id in pool.agent_ids:
        agent = self.registry.get(agent_id)
        if agent and isinstance(agent, SkillBasedAgent):
            agent.add_skill(skill)
    # Refresh descriptors — class-level update in add_skill() means
    # _collect_intent_descriptors() will find the new descriptor via templates
    self.decomposer.refresh_descriptors(self._collect_intent_descriptors())
```

Build `llm_equipped_types` for the strategy recommender:

```python
def _get_llm_equipped_types(self) -> set[str]:
    """Return agent types that have LLM client access.

    The runtime knows because it injected llm_client into these agents.
    """
    types = set()
    if self.pools.get("skills"):
        types.add("skill_agent")
    if self.pools.get("introspect"):
        types.add("introspection")
    # Add any designed agent types that were given LLM access
    # (future extensibility)
    return types
```

Pass `llm_equipped_types` when creating the `StrategyRecommender`:

```python
recommender = StrategyRecommender(
    intent_descriptors=self._collect_intent_descriptors(),
    llm_equipped_types=self._get_llm_equipped_types(),
)
```

#### B6. Update self-mod pipeline — `src/probos/cognitive/self_mod.py`

Add `handle_add_skill()` method:

```python
async def handle_add_skill(
    self,
    intent_name: str,
    intent_description: str,
    parameters: dict[str, str],
    target_agent_type: str,
    research_context: str = "No research available.",
) -> DesignedAgentRecord | None:
    """Design and attach a skill instead of creating a new agent.

    Flow:
    1. Call SkillDesigner.design_skill() → source code
    2. Call SkillValidator.validate() → static analysis
    3. Compile the handler function (importlib)
    4. Create Skill object with handler
    5. Call add_skill_fn callback to attach to skill agents
    6. Record as DesignedAgentRecord with strategy="skill"
    """
```

Add `DesignedAgentRecord.strategy: str = "new_agent"` field to track whether the record was a new agent or a skill addition.

Add `add_skill_fn: Callable` to the pipeline's `__init__` — injected callable, same pattern as all other integration points. The runtime provides `self._add_skill_to_agents`.

#### B7. Update renderer — Strategy dispatch

When the user selects "add_skill" from the strategy menu (Part A), call `pipeline.handle_add_skill()` instead of `pipeline.handle_unhandled_intent()`.

#### B8. Tests — `tests/test_skill_agent.py` and `tests/test_skill_designer.py`

```
SkillBasedAgent tests:
- Agent creates with empty skills list (1 test)
- add_skill registers intent on instance (1 test)
- add_skill updates class-level intent_descriptors (1 test)
- remove_skill clears intent from both instance and class (1 test)
- handle_intent dispatches to correct skill (1 test)
- handle_intent returns None for unknown intent (1 test)
- handle_intent passes llm_client to skill handler (1 test)
- Multiple skills dispatch independently (1 test)
- agent_type is "skill_agent" (1 test)
- Skill with LLM — handler calls llm_client (1 test)

SkillDesigner tests:
- design_skill returns valid function source (1 test)
- Generated code passes SkillValidator (1 test)
- _build_function_name conversion (1 test)

SkillValidator tests:
- Valid skill code passes (1 test)
- Missing async function rejected (1 test)
- Wrong function name rejected (1 test)
- Forbidden import rejected (1 test)
- Forbidden pattern rejected (1 test)
- Module-level side effects rejected (1 test)

Pipeline skill integration:
- handle_add_skill full flow — design → validate → compile → attach (1 test)
- handle_add_skill validation failure aborts (1 test)
- DesignedAgentRecord.strategy field set to "skill" (1 test)
- Runtime _add_skill_to_agents updates all pool members (1 test)
- Descriptor refresh after skill addition includes new intent (1 test)
- Skills pool only spawned when self_mod.enabled=True (1 test)
- Skills pool NOT spawned when self_mod.enabled=False (1 test)
```

~24 tests.

---

### Part C: Web Research Phase (largest scope)

Before designing an agent or skill, ProbOS can optionally research documentation on the internet to produce higher-quality code. This uses the existing `HttpFetchAgent` infrastructure — no new HTTP code is needed.

**Security model:** Web research results are *context* for the LLM, not executed code. The research phase fetches documentation pages, extracts relevant content, and includes it in the design prompt as reference material. The generated code still goes through `CodeValidator` → `SandboxRunner`. The research cannot bypass the safety pipeline.

#### C1. Create `src/probos/cognitive/research.py`

```python
RESEARCH_QUERY_PROMPT = """You are helping ProbOS design a new agent capability.

INTENT TO BUILD:
  Name: {intent_name}
  Description: {intent_description}
  Parameters: {parameters}

What documentation or reference material would help build this?
Generate 2-3 search queries that would find relevant Python library docs,
API references, or code examples.

Respond with ONLY a JSON array of search queries:
["query 1", "query 2", "query 3"]
"""

RESEARCH_SYNTHESIS_PROMPT = """You are preparing reference material for an agent designer.

INTENT TO BUILD:
  Name: {intent_name}
  Description: {intent_description}

DOCUMENTATION FETCHED:
{fetched_content}

Extract the key information needed to implement this intent:
1. Required Python libraries (must be in this whitelist: {allowed_imports})
2. API patterns or function signatures
3. Common pitfalls or error handling patterns
4. Example code snippets (adapted to use only whitelisted imports)

Respond with a concise reference section (max 500 words).
If the fetched content is not useful, say "No useful documentation found."
"""


class ResearchPhase:
    """Researches documentation before agent/skill design.

    Flow:
    1. Ask LLM to generate 2-3 search queries for the intent
    2. Convert queries to documentation site URLs via urllib.parse
    3. Fetch each URL via the mesh (submit_intent for http_fetch)
    4. Truncate fetched content to configured max chars per page
    5. Ask LLM to synthesize relevant information
    6. Return synthesis as additional context for the design prompt

    URL construction strategy:
    Queries are converted to docs.python.org search URLs using the pattern:
        https://docs.python.org/3/search.html?q={query}
    For each query, one URL per whitelisted domain is generated using
    that domain's known search path (see _DOMAIN_SEARCH_PATHS).
    All URLs are constructed via urllib.parse.urlencode() — NEVER raw
    string concatenation.

    Security constraints:
    - Only fetches via the mesh (uses existing HttpFetchAgent + consensus)
    - Fetched content is truncated before LLM processing (no prompt injection
      via enormous pages)
    - Research output is context for code generation, never executed directly
    - All generated code still goes through CodeValidator + SandboxRunner
    - URL construction uses urllib.parse (no raw string concatenation)

    The research phase is OPTIONAL. If it fails (network error, timeout,
    unhelpful content), the design proceeds without research context.
    The design prompt includes a RESEARCH CONTEXT section that is either
    populated or says "No research available."
    """

    # Known search URL patterns for whitelisted domains.
    # Each maps a domain to its search URL path.
    _DOMAIN_SEARCH_PATHS: dict[str, str] = {
        "docs.python.org": "https://docs.python.org/3/search.html",
        "pypi.org": "https://pypi.org/search/",
        "developer.mozilla.org": "https://developer.mozilla.org/en-US/search",
        "learn.microsoft.com": "https://learn.microsoft.com/en-us/search/",
    }

    def __init__(
        self,
        llm_client,
        submit_intent_fn,  # async callable to submit http_fetch intents
        config: SelfModConfig,
    ) -> None:
        self._llm = llm_client
        self._submit_intent = submit_intent_fn
        self._config = config

    async def research(
        self,
        intent_name: str,
        intent_description: str,
        parameters: dict[str, str],
    ) -> str:
        """Research documentation for an intent.

        Returns a synthesized reference section string.
        Returns "No research available." on any failure.
        Never raises — all errors are caught and logged.
        """

    async def _generate_queries(
        self, intent_name: str, intent_description: str, parameters: dict[str, str]
    ) -> list[str]:
        """Ask LLM to generate search queries. Returns list of query strings."""

    def _queries_to_urls(self, queries: list[str]) -> list[str]:
        """Convert search queries to fetchable documentation URLs.

        For each query, constructs a search URL for each whitelisted domain
        using _DOMAIN_SEARCH_PATHS and urllib.parse.urlencode().

        Example:
            query = "python json parsing"
            → "https://docs.python.org/3/search.html?q=python+json+parsing"
            → "https://pypi.org/search/?q=python+json+parsing"
            → etc.

        Total URLs = len(queries) × len(whitelisted_domains), capped at
        config.research_max_pages to limit fetch volume.

        Any domain not in _DOMAIN_SEARCH_PATHS is silently skipped.
        """

    async def _fetch_pages(self, urls: list[str]) -> list[dict]:
        """Fetch each URL via the mesh's http_fetch intent.

        Returns list of {"url": str, "content": str, "success": bool}.
        Each page content is truncated to config.research_max_content_per_page chars.
        Failed fetches are included with success=False.
        """

    async def _synthesize(
        self,
        intent_name: str,
        intent_description: str,
        fetched: list[dict],
    ) -> str:
        """Ask LLM to synthesize relevant information from fetched docs.

        Returns a concise reference section string.
        """
```

**Security design (critical):**

1. **URL construction:** All URLs are built via `urllib.parse.urlencode()` using known search paths from `_DOMAIN_SEARCH_PATHS`. No user-controlled strings are interpolated directly into URLs. The domain whitelist prevents SSRF against internal services.

2. **Content truncation:** Fetched content is hard-capped at `research_max_content_per_page` chars *before* being sent to the LLM. This prevents prompt injection via enormous pages that could overflow the LLM context.

3. **Fetch via mesh:** Research uses the existing `http_fetch` intent through the mesh, meaning it goes through consensus (HttpFetchAgent has `requires_consensus=True`). This means the trust network, quorum voting, and red team verification all apply to research fetches.

4. **Research is context, not execution:** The synthesis output is injected into the `AGENT_DESIGN_PROMPT` or `SKILL_DESIGN_PROMPT` as a `{research_context}` template variable. The generated code still goes through CodeValidator + SandboxRunner. Even if research content contained malicious code snippets, the CodeValidator's AST analysis and forbidden pattern scanning would catch them.

5. **Graceful degradation:** Research failure (network error, timeout, unhelpful content) results in "No research available." — the design proceeds without it. Research is an optimization, not a requirement.

#### C2. Add `ResearchConfig` to `SelfModConfig`

```python
class SelfModConfig(BaseModel):
    # ... existing fields ...
    research_enabled: bool = False  # Opt-in web research before design
    research_domain_whitelist: list[str] = [
        "docs.python.org",
        "pypi.org",
        "developer.mozilla.org",
        "learn.microsoft.com",
    ]
    research_max_pages: int = 3
    research_max_content_per_page: int = 2000
```

#### C3. Update `AGENT_DESIGN_PROMPT`

Add a `{research_context}` section to the existing `AGENT_DESIGN_PROMPT` in `agent_designer.py`:

```
RESEARCH CONTEXT:
{research_context}

Use the above research to inform your implementation.
If research context says "No research available.", rely on your training knowledge.
```

The `SKILL_DESIGN_PROMPT` (B2) already includes `{research_context}`.

#### C4. Wire research into the pipeline

In `SelfModificationPipeline`, before calling `AgentDesigner.design_agent()` or `SkillDesigner.design_skill()`:

```python
research_context = "No research available."
if self._config.research_enabled and self._research:
    research_context = await self._research.research(
        intent_name, intent_description, parameters
    )
```

Pass `research_context` to the designer as an additional parameter.

Add `ResearchPhase` to the pipeline's `__init__` as an optional dependency:

```python
def __init__(
    self,
    ...,
    research: ResearchPhase | None = None,
) -> None:
    self._research = research
```

The runtime creates `ResearchPhase` only when `research_enabled=True` and passes it to the pipeline.

#### C5. Update renderer — Research status display

When research is enabled, show research progress:

```
  Researching documentation for translate_text...
  ✓ Found 2 relevant pages
  Designing agent with research context...
```

This is purely informational — the renderer shows what the research phase found (or if it skipped/failed) but doesn't ask for user input during research.

#### C6. Tests — `tests/test_research.py`

```
ResearchPhase tests:
- research returns synthesis string on success (1 test)
- research returns "No research available." on network failure (1 test)
- research returns "No research available." on empty content (1 test)
- _generate_queries returns list of strings (1 test)
- _generate_queries handles malformed LLM response gracefully (1 test)
- _queries_to_urls uses urllib.parse (no raw string concat) (1 test)
- _queries_to_urls filters non-whitelisted domains (1 test)
- _queries_to_urls returns empty list for empty queries (1 test)
- _queries_to_urls caps total URLs at research_max_pages (1 test)
- _fetch_pages truncates content to max chars (1 test)
- _fetch_pages handles failed fetches (1 test)
- _synthesize passes content to LLM (1 test)
- _synthesize handles "no useful docs" response (1 test)
- Full research flow: queries → URLs → fetch → synthesize (1 test)
- Research context injected into design prompt (1 test)
- Pipeline with research_enabled=False skips research (1 test)
- Pipeline with research_enabled=True includes context (1 test)

Security tests:
- URLs use urllib.parse.urlencode (1 test)
- Non-whitelisted domain URLs are filtered out (1 test)
- Content exceeding max_content_per_page is truncated (1 test)
- Fetch goes through consensus (submit_intent_with_consensus) (1 test)
```

~21 tests.

---

## Implementation Order

**Build in this order** to maintain a working system at each step:

1. **Part A (Transparency)** — `strategy.py`, renderer updates, tests → commit
   - Self-mod still works exactly as before, but now shows strategy options
   - If only "new_agent" is viable (no skill system yet), it shows a single option with reason

2. **Part B (Skills)** — `Skill` type, `SkillBasedAgent`, `SkillDesigner`, `SkillValidator`, pipeline + runtime wiring, tests → commit
   - Now "add_skill" option in the strategy menu actually works
   - The strategy recommender can suggest "add_skill" when appropriate
   - Skills pool only exists when self_mod.enabled=True

3. **Part C (Research)** — `research.py`, config additions, design prompt updates, pipeline wiring, security tests → commit
   - Research is opt-in (disabled by default in config)
   - Both strategies (new_agent, add_skill) benefit from research context

Each part is independently commit-worthy. Part A works without B or C. Part B works without C. Part C enhances both A and B.

Run `uv run pytest tests/ -v` after each part and confirm all existing tests still pass before moving to the next part.

---

## Test Count Estimate

- Part A: ~11 strategy tests
- Part B: ~24 skill agent + designer + validator + pipeline tests
- Part C: ~21 research + security tests
- **Total: ~56 new tests**

---

## What This Phase Does NOT Change

- Existing agents are untouched — FileReaderAgent, ShellCommandAgent, etc. remain as-is
- The consensus pipeline is unchanged — skills and new agents both go through consensus
- Trust mechanics are unchanged — probationary trust still applies to new agents
- The escalation cascade is unchanged
- Red team verification is unchanged — generated code still goes through CodeValidator + SandboxRunner
- The shell command set is unchanged (no new slash commands in this phase)
- Dreaming, attention, workflow cache, federation — all untouched

---

## Success Criteria

After this phase:

1. When ProbOS detects a capability gap, the user sees a strategy proposal with options, each with a confidence score and reason.
2. The user can choose "add skill" to extend an existing agent instead of creating a new one.
3. Skills are modular, testable, and go through the same safety pipeline (validation + sandbox) as full agents.
4. When research is enabled, the design prompt includes real documentation context, producing higher-quality generated code.
5. All research fetches go through consensus. Content is truncated. URLs are whitelisted. Research failure is graceful.
6. The probabilistic design principle is preserved: strategies are recommended with confidence scores, not dictated. Skills use LLM inference, not deterministic logic. Research provides context, not templates.
