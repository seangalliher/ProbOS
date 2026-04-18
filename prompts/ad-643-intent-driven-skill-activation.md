# AD-643: Intent-Driven Skill Activation & Thought Process Catalog

**Issue:** TBD
**Depends on:** AD-626 (dual-mode skill activation), AD-632f/h (sub-task chains)
**Related:** AD-618 (Bill System / SOPs)
**Absorbs:** None
**Principles:** Single Responsibility, Open/Closed, Interface Segregation

## Problem

### 1. Skills Load Too Early and Too Broadly

Augmentation skills currently load on **broad intents** (`proactive_think`,
`ward_room_notification`), not on **specific agent actions**. Every
`proactive_think` cycle loads ALL matching skills into every chain step —
communication-discipline, notebook-quality, and leadership-feedback —
regardless of what the agent actually intends to do.

### 2. Chains Fire Too Broadly

The communication chain (QUERY→ANALYZE→COMPOSE→EVALUATE→REFLECT) fires on
**every** `proactive_think` because `_CHAIN_ELIGIBLE_INTENTS` is a simple
set membership check. An agent that wants to write a notebook entry runs
through the same 5-step communication chain as one composing a Ward Room
reply. The chain was designed for communication — it shouldn't fire for
notebooks, leadership reviews, or other actions.

### 3. No Thought Process Abstraction

Chains are hardcoded in `_build_chain_for_intent()`. Adding a new thought
pattern (e.g., a notebook chain with draft→review→finalize) requires
modifying Python code. There is no declarative way to define new thought
processes or map skills to specific actions within them.

### 4. No Per-Action Skill Loading

The current architecture loads one blob of skill instructions and passes it
to every chain step. There is no mechanism for different actions within a
thought process to use different skills.

### Current flow

```
proactive_think intent arrives
  → Load ALL augmentation skills                           ← too early
  → Build communication chain (always)                     ← too broad
  → QUERY  (deterministic data fetch)
  → ANALYZE (LLM determines what to do)
  → COMPOSE (LLM writes output — gets ALL skills)          ← wrong skills
  → EVALUATE (quality check — gets ALL skills)             ← wrong skills
  → REFLECT (self-critique — gets ALL skills)              ← wrong skills
```

### Observable problems

1. **Token waste** — ~1,500 tokens of irrelevant skill guidance per cycle.
   At 30 agents × 5+ cycles/session = 225K+ wasted tokens.
2. **Attention dilution** — LLM must mentally filter which skill applies.
3. **Doesn't scale** — 10 skills × 500 tokens = 5K tokens per cycle.
4. **Wrong chain** — Notebook entries don't need the communication chain.
5. **Wrong model** — Claude Code activates skills on task context, not
   broad intents. Claude Code forks subagents when task complexity warrants
   it — the decision is driven by task analysis, not intent type.

## Research Context

### BDI Architecture (Rao & Georgeff, 1995)

The Belief-Desire-Intention architecture provides the formal foundation.
ProbOS already has Beliefs (context, memory, standing orders) and Desires
(intents). What's missing is **Intentions** — committed action plans
selected from a **plan library**. The Thought Process Catalog IS the BDI
plan library.

Key BDI insight: **plans are selected, not constructed.** The agent picks
from a library of known thought patterns, it doesn't build a plan from
scratch. ANALYZE does the selection.

### HTN Planning (Erol, Hendler & Nau, 1994)

Hierarchical Task Networks decompose abstract tasks into subtasks, which
decompose into primitive actions. A "research-report" thought process
decomposes into [analyze-sources, synthesize, write-notebook, post-summary].
This is the single-action vs multi-action distinction formalized:
Thought Process → Action Group (sequential/parallel) → Action → Skill.

### Dual Process Theory (Kahneman, 2011)

System 1 = fast, automatic, single-action (endorse, simple reply).
System 2 = slow, deliberate, multi-step chain (compose→evaluate→reflect).
ANALYZE is the System 1/System 2 gate — it determines whether the thought
needs deliberation (chain) or can be handled reflexively (single action).

### DSPy (Khattab et al., 2023)

Declarative LLM pipelines where each module has its own prompt
optimization. Validates per-action skill loading — modular, per-step
specialization outperforms monolithic prompts.

### OODA Loop (Boyd, 1976)

Already implicit: QUERY=Observe, ANALYZE=Orient, routing=Decide,
execution=Act. Military doctrine validates the two-phase pattern.

### Connection to AD-618 (Bill System / SOPs)

AD-618 defines Bills as multi-AGENT procedures. AD-643 defines thought
processes as single-AGENT cognitive patterns. Same primitives at different
scales:

| Concept | AD-618 (Bill) | AD-643 (Thought Process) |
|---------|---------------|--------------------------|
| **Trigger** | Alert condition / event | `intended_actions` from ANALYZE |
| **Steps** | Bill steps with role assignments | Actions with skill assignments |
| **Skill per step** | `action: cognitive_skill, skill: name` | `skill: name` per action |
| **Dependencies** | XOR/AND/OR gateways | `depends_on` (existing SubTaskSpec) |
| **Parallel** | `type: parallel` | `depends_on` enables parallel (existing executor) |
| **Scope** | Multi-agent coordination | Single-agent thought cycle |

AD-643 is the primitive that AD-618 composes. A Bill step that says
`action: cognitive_skill` invokes the same mechanism — the agent runs a
thought process with a specific skill.

### Existing Infrastructure (Already Built)

The sub-task executor (AD-632h) already supports everything needed for
action dependencies and parallelism:

- **`SubTaskSpec.depends_on`** — explicit dependency declaration between
  steps
- **`_get_ready_steps()`** — topological ordering, finds independent steps
  whose dependencies are satisfied
- **`_execute_steps()`** — parallel dispatch via `asyncio.gather()` when
  multiple steps are ready simultaneously
- **`SubTaskResult`** — structured output per step, flows forward via
  `prior_results`
- **`validate_chain()`** — cycle detection and missing dependency warnings

This means multi-action thought processes with sequential and parallel
actions require NO new executor infrastructure — only a new way to
**construct** chains from declarative definitions.

## Design: Thought Process Catalog

### Core Architecture

```
Agent Cognitive Cycle:

  Thought (intent arrives: proactive_think, ward_room_notification, ...)
    │
    ▼
  QUERY (observe — deterministic data fetch, no LLM)
    │
    ▼
  ANALYZE (orient — LLM expresses intended_actions)
    │
    ▼
  Thought Process Catalog (select — match intended_actions to registered process)
    │
    ├─ Single-action process (System 1)
    │   → Load mapped skill
    │   → Execute action
    │   → Return result
    │
    └─ Multi-action process (System 2)
        → Build chain from process definition
        → Each action loads its mapped skill
        → Actions execute per dependency graph (sequential/parallel)
        → Results flow between actions
        → Return final result
```

### Thought Process Definition

A thought process is a declarative definition of how an agent should
think about a specific type of action:

```python
@dataclass(frozen=True)
class ThoughtAction:
    """A single action within a thought process."""
    name: str                           # "compose-reply", "evaluate-quality"
    sub_task_type: SubTaskType          # COMPOSE, EVALUATE, REFLECT, etc.
    prompt_template: str                # Template name for the handler
    skill: str = ""                     # Skill to load for this action
    depends_on: tuple[str, ...] = ()    # Other action names this depends on
    required: bool = True               # If False, failure doesn't abort
    tier: str = "standard"              # LLM tier override

@dataclass(frozen=True)
class ThoughtProcess:
    """A registered cognitive pattern — single or multi-action."""
    name: str                           # "communication-reply", "notebook-entry"
    description: str                    # Human-readable purpose
    triggers: list[str]                 # Action tags that activate this process
    triage: list[ThoughtAction]         # Phase 1: QUERY + ANALYZE (always runs)
    actions: list[ThoughtAction]        # Phase 2: The actual work
    intent_filter: list[str] = ()       # Which intents this process applies to
    min_rank: str = "ensign"            # Rank gate
    department: str = "*"               # Department gate
```

### Registered Thought Processes

```python
THOUGHT_PROCESSES = [
    ThoughtProcess(
        name="communication-reply",
        description="Compose, evaluate, and reflect on a Ward Room reply",
        triggers=["ward_room_reply", "ward_room_post"],
        intent_filter=["proactive_think", "ward_room_notification"],
        triage=[
            ThoughtAction("query-context", SubTaskType.QUERY, ""),
            ThoughtAction("analyze-situation", SubTaskType.ANALYZE, "situation_review"),
        ],
        actions=[
            ThoughtAction(
                "compose-reply", SubTaskType.COMPOSE, "ward_room_response",
                skill="communication-discipline",
            ),
            ThoughtAction(
                "evaluate-reply", SubTaskType.EVALUATE, "ward_room_quality",
                skill="communication-discipline",
                depends_on=("compose-reply",),
                required=False,
            ),
            ThoughtAction(
                "reflect-reply", SubTaskType.REFLECT, "ward_room_reflection",
                skill="communication-discipline",
                depends_on=("compose-reply", "evaluate-reply"),
                required=False,
            ),
        ],
    ),

    ThoughtProcess(
        name="notebook-entry",
        description="Compose a notebook entry with analytical quality standards",
        triggers=["notebook"],
        intent_filter=["proactive_think"],
        triage=[
            ThoughtAction("query-context", SubTaskType.QUERY, ""),
            ThoughtAction("analyze-situation", SubTaskType.ANALYZE, "situation_review"),
        ],
        actions=[
            ThoughtAction(
                "compose-notebook", SubTaskType.COMPOSE, "notebook_compose",
                skill="notebook-quality",
            ),
        ],
    ),

    ThoughtProcess(
        name="endorse-post",
        description="Endorse a Ward Room post",
        triggers=["endorse"],
        intent_filter=["proactive_think", "ward_room_notification"],
        triage=[
            ThoughtAction("query-context", SubTaskType.QUERY, ""),
            ThoughtAction("analyze-situation", SubTaskType.ANALYZE, "situation_review"),
        ],
        actions=[
            ThoughtAction(
                "compose-endorse", SubTaskType.COMPOSE, "endorse_compose",
                skill="communication-discipline",
            ),
        ],
    ),

    ThoughtProcess(
        name="leadership-review",
        description="Review subordinate communication patterns and send feedback",
        triggers=["leadership_review"],
        intent_filter=["proactive_think"],
        min_rank="lieutenant_commander",
        triage=[
            ThoughtAction("query-context", SubTaskType.QUERY, ""),
            ThoughtAction("analyze-situation", SubTaskType.ANALYZE, "situation_review"),
        ],
        actions=[
            ThoughtAction(
                "compose-feedback", SubTaskType.COMPOSE, "leadership_compose",
                skill="leadership-feedback",
            ),
        ],
    ),
]
```

### Future: Multi-Action Notebook Process

When a single-action notebook process proves insufficient, it can be
upgraded to multi-action without changing any infrastructure:

```python
ThoughtProcess(
    name="notebook-entry",
    description="Draft, verify, and finalize a notebook entry",
    triggers=["notebook"],
    intent_filter=["proactive_think"],
    triage=[...],
    actions=[
        ThoughtAction(
            "read-prior", SubTaskType.QUERY, "notebook_prior_read",
            skill="notebook-quality",
        ),
        ThoughtAction(
            "compose-notebook", SubTaskType.COMPOSE, "notebook_compose",
            skill="notebook-quality",
            depends_on=("read-prior",),
        ),
        ThoughtAction(
            "evaluate-notebook", SubTaskType.EVALUATE, "notebook_quality_check",
            skill="notebook-quality",
            depends_on=("compose-notebook",),
            required=False,
        ),
    ],
)
```

### Future: Parallel Actions

The existing executor already handles this. Two actions with no mutual
dependency run in parallel:

```python
ThoughtProcess(
    name="research-synthesis",
    description="Parallel research then synthesis",
    triggers=["research"],
    triage=[...],
    actions=[
        ThoughtAction(
            "search-codebase", SubTaskType.QUERY, "codebase_search",
        ),
        ThoughtAction(
            "search-docs", SubTaskType.QUERY, "doc_search",
            # No depends_on → parallel with search-codebase
        ),
        ThoughtAction(
            "synthesize", SubTaskType.COMPOSE, "research_synthesis",
            skill="research-analysis",
            depends_on=("search-codebase", "search-docs"),  # joins parallel results
        ),
    ],
)
```

`_get_ready_steps()` already computes the ready set from `depends_on`.
`_execute_steps()` already dispatches ready steps via `asyncio.gather()`.

### How ANALYZE Routes to a Thought Process

ANALYZE outputs `intended_actions`. The catalog matches:

```python
def select_thought_process(
    intended_actions: list[str],
    intent: str,
    agent_rank: str,
    department: str,
) -> ThoughtProcess | None:
    """Select the best matching thought process for the agent's expressed intent.

    Matching rules:
    1. At least one intended_action matches a process trigger
    2. Intent matches process intent_filter
    3. Rank and department gates pass
    4. If multiple match, prefer the one with most trigger overlap
    5. If no match, return None (fallback to single-call)
    """
```

### Two-Phase Execution

```python
async def _execute_thought_process(self, process, observation):
    # Phase 1: Triage (QUERY + ANALYZE — no skills, lightweight)
    triage_chain = self._build_chain_from_actions(process.triage)
    triage_results = await self._sub_task_executor.execute(triage_chain, observation, ...)

    # Extract intended_actions from ANALYZE result
    intended_actions = self._extract_intended_actions(triage_results)

    # Short-circuit on silent
    if "silent" in intended_actions and len(intended_actions) == 1:
        return {"action": "none", "llm_output": "[NO_RESPONSE]"}

    # Phase 2: Execute actions with per-action skill loading
    for action in process.actions:
        if action.skill:
            # Load skill specific to this action
            skill_instructions = self._load_skill_for_action(action.skill)
            observation["_augmentation_skill_instructions"] = skill_instructions

    execute_chain = self._build_chain_from_actions(process.actions)
    results = await self._sub_task_executor.execute(execute_chain, observation, ...)

    return self._extract_decision(results)
```

### Mixed Intended Actions

When ANALYZE returns multiple intended actions (e.g.,
`["ward_room_reply", "notebook"]`):

**Option A (AD-643a):** Select the most complex matching process. Load all
relevant skills. The LLM handles multiple actions in one compose step.

**Option B (AD-643c, future):** Execute multiple thought processes
sequentially. First the communication process, then the notebook process.
Each with its own skill. This is the "each sub-agent loads different skills"
model.

### Graceful Degradation

- ANALYZE omits `intended_actions` → fall back to pre-AD-643 behavior
  (load all skills, use hardcoded chain selection)
- No matching thought process → fall back to single-call `_decide_via_llm()`
  with all skills loaded
- Thought process execution fails → fall back to single-call (existing
  `fallback: "single_call"` behavior)

### What This Is NOT

This is **not** a workflow engine. The differences:

| Workflow Engine (Temporal/Airflow) | Thought Process Catalog |
|-----------------------------------|-----------------------|
| Each step is a deterministic function | Each action is an LLM call with a skill |
| State machine drives execution | Agent has judgment — can deviate |
| Transaction boundaries, rollback | Failure = trust degradation + Counselor |
| Enterprise service orchestration | Individual cognitive cycle |
| Persisted workflow state | Ephemeral — lives within one thought cycle |
| Arbitrary external integrations | Composes LLM calls with skills |

The constraint: agents have judgment. The thought process catalog defines
STRUCTURE (what actions, what order, what skills). The LLM does the
THINKING within each action. SOPs are reference documents, not execution
scripts (AD-618 principle).

## Phasing

### AD-643a: Intent Routing + Targeted Skill Loading

The immediate fix. Minimal code change, maximum token savings.

**Changes:**
1. ANALYZE prompts gain `intended_actions` output field
2. `CognitiveSkillEntry` gains `triggers: list[str]` field
3. `probos-triggers` added to SKILL.md metadata
4. `find_triggered_skills()` added to catalog
5. Skill loading moves from pre-chain to post-ANALYZE
6. Chain selection based on `intended_actions` instead of intent name
7. Communication chain only fires for communication-related actions

**Does NOT include:**
- ThoughtProcess dataclass or catalog
- Per-action skill loading (one set of skills per thought cycle)
- New prompt templates for non-communication actions
- YAML-based thought process definitions

**Files to change:**
| File | Change |
|------|--------|
| `src/probos/cognitive/skill_catalog.py` | Add `triggers` field, `find_triggered_skills()`, parse `probos-triggers` |
| `src/probos/cognitive/cognitive_agent.py` | Move skill loading post-ANALYZE. Replace `_build_chain_for_intent()` with action-based routing. Two-phase execution. |
| `src/probos/cognitive/sub_tasks/analyze.py` | Add `intended_actions` to situation review and thread analysis prompts |
| `config/skills/communication-discipline/SKILL.md` | Add `probos-triggers: "ward_room_post,ward_room_reply,endorse"` |
| `config/skills/notebook-quality/SKILL.md` | Add `probos-triggers: "notebook"` |
| `config/skills/leadership-feedback/SKILL.md` | Add `probos-triggers: "leadership_review"` |

### AD-643b: Thought Process Catalog

Declarative thought process definitions replace hardcoded chain building.

**Changes:**
1. `ThoughtAction` and `ThoughtProcess` dataclasses
2. `ThoughtProcessCatalog` — registry of thought processes, matched by
   triggers
3. `_build_chain_for_intent()` replaced by catalog-driven chain construction
4. Per-action skill loading — each `ThoughtAction` declares its skill,
   loaded independently
5. Registered processes for: communication-reply, notebook-entry,
   endorse-post, leadership-review

**Depends on:** AD-643a (trigger matching, `intended_actions` from ANALYZE)

**Files to create:**
| File | Content |
|------|---------|
| `src/probos/cognitive/thought_process.py` | `ThoughtAction`, `ThoughtProcess`, `ThoughtProcessCatalog` |

**Files to change:**
| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | Replace `_build_chain_for_actions()` with catalog lookup. Per-action skill injection in chain context. |
| `src/probos/cognitive/sub_tasks/compose.py` | Read per-action skill from context (minor change to `_inject_skills()`) |
| `src/probos/cognitive/sub_tasks/reflect.py` | Same — per-action skill context |

### AD-643c: Multi-Action Processes + Sequential Thought Execution

Upgrade single-action processes to multi-action. Support executing
multiple thought processes in sequence when ANALYZE returns mixed actions.

**Changes:**
1. Notebook thought process upgraded to multi-action
   (read-prior → compose → evaluate)
2. Mixed `intended_actions` execute as sequential thought processes
   (communication process then notebook process)
3. Action results from one process available as input to the next
4. New prompt templates for non-communication chain steps
   (notebook_compose, notebook_quality_check, leadership_compose)

**Depends on:** AD-643b (thought process catalog, per-action skills)

**Infrastructure note:** Parallel actions within a single thought process
are already supported by the existing executor (AD-632h). This phase
focuses on multi-action process definitions and sequential process
execution — not new executor features.

**Files to change:**
| File | Change |
|------|--------|
| `src/probos/cognitive/thought_process.py` | Update registered processes with multi-action definitions |
| `src/probos/cognitive/cognitive_agent.py` | Sequential thought process execution for mixed actions |
| `src/probos/cognitive/sub_tasks/compose.py` | New prompt builders for notebook, leadership compose modes |
| `src/probos/cognitive/sub_tasks/evaluate.py` | New prompt builders for notebook quality evaluation |

## ANALYZE Prompt Changes (AD-643a)

### `proactive_think` situation review (analyze.py)

Add `intended_actions` to the required output:

```python
"5. **intended_actions**: What actions will you take? List from:\n"
"   ward_room_post, ward_room_reply, endorse, notebook, leadership_review,\n"
"   proposal, dm, silent. Include ALL that apply.\n"
"   Examples: [\"ward_room_post\", \"notebook\"], [\"endorse\"], [\"silent\"]\n\n"
"Return a JSON object with these 5 keys. No other text."
```

### `ward_room_notification` thread analysis (analyze.py)

Map existing `contribution_assessment` to `intended_actions`:

```python
"6. **intended_actions**: Based on your contribution_assessment, what\n"
"   specific actions will you take? List from:\n"
"   ward_room_reply, endorse, silent.\n"
"   If RESPOND: [\"ward_room_reply\"]. If ENDORSE: [\"endorse\"].\n"
"   If both: [\"ward_room_reply\", \"endorse\"]. If SILENT: [\"silent\"].\n\n"
"Return a JSON object with these 6 keys. No other text."
```

### Future: Auto-Generated Action Vocabulary (AD-643b)

Currently the ANALYZE prompt hardcodes the action vocabulary. AD-643b
replaces this: the catalog auto-generates the vocabulary from registered
thought process triggers. Adding a new thought process automatically makes
its trigger available in the ANALYZE prompt.

## Relationship to Existing ADs

| AD | Relationship |
|----|-------------|
| **AD-618** (Bill System) | Parallel at different scale. Bills = multi-agent SOPs. Thought Processes = single-agent cognitive patterns. Same primitives. AD-643 thought processes are the primitive Bills compose. |
| **AD-626** (dual-mode activation) | Extended. `probos-triggers` is a new activation dimension. |
| **AD-632f/h** (sub-task chains) | Restructured. Chains become runtime artifacts built from thought process definitions. Existing executor, dependency resolution, and parallel dispatch reused unchanged. |
| **AD-634** (notebook-quality) | Updated. `probos-triggers: "notebook"`. In AD-643c, upgraded to multi-action process. |
| **AD-630** (leadership-feedback) | Updated. `probos-triggers: "leadership_review"`. |
| **AD-625/631** (communication-discipline) | Updated. `probos-triggers: "ward_room_post,ward_room_reply,endorse"`. |
| **AD-596a** (cognitive skill loader) | Extended. `CognitiveSkillEntry` gains `triggers` field. |
| **AD-531–539** (Cognitive JIT) | Future connection: successful thought process executions feed episodic memory → JIT could compile agent-specific optimizations of thought processes. |

## Do NOT Change

- `sub_task.py` — `SubTaskExecutor`, `SubTaskSpec`, `SubTaskChain` are
  reused as-is. Thought processes compile DOWN to these existing primitives.
- `skill_bridge.py` — proficiency gating is orthogonal
- `skill_framework.py` — T3 registry is not involved
- Standing orders — action vocabulary defined there, not duplicated

## Engineering Principles Compliance

| Principle | Application |
|-----------|-------------|
| **SRP** | ANALYZE expresses intent. Catalog matches thought processes. Executor runs chains. Each has one job. |
| **Open/Closed** | New thought processes register without modifying executor, catalog code, or existing processes. New skills add triggers without modifying processes. |
| **Interface Segregation** | Thought processes compile to existing `SubTaskChain`/`SubTaskSpec`. No new executor interfaces. |
| **DRY** | Existing executor handles dependencies + parallelism. No reimplementation. Chain construction extracted from hardcoded method to catalog-driven. |
| **Defense in Depth** | Missing `intended_actions` → fallback. No matching process → fallback. Process failure → single-call fallback. Three layers of graceful degradation. |
| **Fail Fast** | Invalid triggers logged and skipped. Cycle detection in dependency graph (existing `validate_chain()`). |

## Test Requirements

### AD-643a Tests (`tests/test_ad643a_intent_routing.py`)

1. **TestSkillTriggerParsing**
   - `test_triggers_parsed_from_skill_md`
   - `test_multiple_triggers_parsed`
   - `test_empty_triggers_default`

2. **TestFindTriggeredSkills**
   - `test_matches_single_trigger`
   - `test_matches_one_of_multiple`
   - `test_no_match_returns_empty`
   - `test_empty_triggers_matches_intent_only` (backward compat)
   - `test_rank_gate_still_applies`
   - `test_department_gate_still_applies`

3. **TestIntendedActionsExtraction**
   - `test_list_extracted_from_analyze_result`
   - `test_string_normalized_to_list`
   - `test_missing_field_returns_empty_list`
   - `test_values_lowercased_and_stripped`

4. **TestChainRouting**
   - `test_ward_room_post_triggers_comm_chain`
   - `test_notebook_skips_comm_chain`
   - `test_silent_short_circuits`
   - `test_endorse_only_skips_chain`
   - `test_fallback_on_missing_actions`

5. **TestTargetedSkillLoading**
   - `test_notebook_action_loads_notebook_skill_only`
   - `test_ward_room_post_loads_comm_skill_only`
   - `test_multiple_actions_load_multiple_skills`
   - `test_silent_loads_no_skills`

6. **TestTwoPhaseExecution**
   - `test_query_and_analyze_run_without_skills`
   - `test_skills_loaded_between_phases`
   - `test_fallback_path_loads_all`

### AD-643b Tests (`tests/test_ad643b_thought_catalog.py`)

1. **TestThoughtProcessDefinition**
   - `test_single_action_process`
   - `test_multi_action_process`
   - `test_action_dependencies_validated`
   - `test_cycle_detection_in_dependencies`

2. **TestCatalogSelection**
   - `test_select_by_trigger`
   - `test_select_with_rank_gate`
   - `test_select_with_intent_filter`
   - `test_no_match_returns_none`
   - `test_most_specific_match_wins`

3. **TestChainConstruction**
   - `test_single_action_builds_minimal_chain`
   - `test_multi_action_preserves_dependencies`
   - `test_parallel_actions_have_no_mutual_deps`

4. **TestPerActionSkillLoading**
   - `test_compose_gets_compose_skill`
   - `test_evaluate_gets_evaluate_skill`
   - `test_different_skills_per_action`

### AD-643c Tests (`tests/test_ad643c_multi_action.py`)

1. **TestMultiActionNotebook**
   - `test_read_prior_before_compose`
   - `test_evaluate_after_compose`
   - `test_prior_results_flow_to_compose`

2. **TestSequentialProcessExecution**
   - `test_mixed_actions_run_sequentially`
   - `test_first_process_results_available_to_second`
   - `test_failure_in_first_stops_second`

3. **TestParallelActions**
   - `test_independent_actions_run_concurrently`
   - `test_join_waits_for_all_parallel`

### Existing test verification

```
pytest tests/test_ad643a_intent_routing.py -v
pytest tests/test_ad643b_thought_catalog.py -v
pytest tests/test_ad643c_multi_action.py -v
pytest tests/test_ad625_comm_discipline.py -v
pytest tests/test_ad626_dual_mode_skill.py -v
pytest tests/ -k "skill or chain or sub_task" --tb=short
```

## Verification Checklist

### AD-643a
- [ ] `CognitiveSkillEntry` has `triggers: list[str]` field
- [ ] `_parse_skill_file()` reads `probos-triggers` from YAML
- [ ] `find_triggered_skills()` matches intent + triggers + rank + department
- [ ] ANALYZE prompts request `intended_actions` field
- [ ] ANALYZE result parsed and normalized
- [ ] Chain routing based on `intended_actions`, not intent name
- [ ] Two-phase execution: triage then execute
- [ ] Skill loading occurs post-ANALYZE, not pre-chain
- [ ] Fallback path unchanged (backward compat)
- [ ] All three SKILL.md files updated with `probos-triggers`
- [ ] Communication chain only fires for communication actions
- [ ] Token savings observable in logs

### AD-643b
- [ ] `ThoughtAction` and `ThoughtProcess` dataclasses defined
- [ ] `ThoughtProcessCatalog` selects processes by trigger + gates
- [ ] Hardcoded `_build_chain_for_intent()` replaced by catalog lookup
- [ ] Per-action skill loading works
- [ ] Thought processes compile to existing `SubTaskChain`/`SubTaskSpec`
- [ ] No changes to `SubTaskExecutor`

### AD-643c
- [ ] Notebook process upgraded to multi-action
- [ ] Sequential thought process execution for mixed actions
- [ ] Action results flow between processes
- [ ] New prompt templates for notebook and leadership actions
- [ ] Parallel actions within a process work (existing executor)

## Deferred Work

- **YAML-based thought process definitions** — Currently registered in
  Python. Future: YAML files in `config/thought_processes/` discovered
  like SKILL.md files. Enables Captain-authored thought processes.
- **Cognitive JIT integration** — Successful thought process executions
  feed episodic memory. JIT could compile agent-specific optimizations.
- **Dynamic action vocabulary** — ANALYZE prompt auto-generated from
  registered thought process triggers. No manual prompt updates when
  adding processes.
- **Thought process learning** — Agents that repeatedly compose novel
  action sequences could have those patterns recognized and registered
  as new thought processes.
- **Per-step skill loading in SubTaskSpec** — `SubTaskSpec.skill_triggers`
  field as an alternative to `ThoughtAction.skill`. Useful when the same
  chain structure is reused with different skills.
