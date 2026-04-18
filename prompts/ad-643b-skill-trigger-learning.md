# AD-643b: Skill Trigger Learning — Adaptive Trigger Discovery & Graduation

**Status:** Design — Ready for review
**Parent:** AD-643 (Intent-Driven Skill Activation)
**Depends on:** AD-643a (two-phase intent routing — COMPLETE)
**Related:** AD-535 (Dreyfus graduated compilation), AD-539 (gap detection),
AD-531 (episode clustering), Cognitive JIT pipeline (AD-531–539)

---

## Problem Statement

AD-643a introduced two-phase chain execution where ANALYZE produces
`intended_actions` and skills load only for matching triggers. This works
when agents correctly declare their intended actions. But agents sometimes
take actions they didn't declare — e.g., Lyra (systems_analyst) declared
`['ward_room_reply']` but wrote a notebook entry during COMPOSE. The
`notebook-quality` skill never loaded, so her notebook lacked quality
guidelines.

Three problems at different scales:

1. **Immediate:** Agents don't know what triggers exist, so they can't
   declare actions they don't know about.
2. **Reactive:** When agents miss a trigger, there's no feedback loop to
   help them learn.
3. **Scale:** With 100+ triggers, injecting the full list into every
   ANALYZE prompt burns the tokens AD-643a was designed to save.

## Design: Three-Phase Trigger Learning Lifecycle

### Phase 1: Trigger Awareness (Bootstrapping)

**Goal:** Tell agents what triggers exist so they can declare them.

**Mechanism:** At triage time, inject a scoped trigger list into the
ANALYZE prompt. Not the full catalog — only triggers for skills the agent
is eligible to receive (filtered by department + rank, same logic as
`find_triggered_skills()`).

**Implementation:**

#### Change 1: `skill_catalog.py` — `get_eligible_triggers()`

New method on `CognitiveSkillCatalog`:

```python
def get_eligible_triggers(
    self,
    department: str | None = None,
    agent_rank: str | None = None,
) -> dict[str, list[str]]:
    """Return {action_tag: [skill_names]} for skills this agent could trigger.

    Filters by department and rank eligibility. Used to inject trigger
    awareness into the ANALYZE prompt so agents know what actions will
    load quality skills.
    """
```

Returns a dict like:
```python
{
    "ward_room_reply": ["communication-discipline"],
    "ward_room_post": ["communication-discipline"],
    "endorse": ["communication-discipline"],
    "notebook": ["notebook-quality"],
    "leadership_review": ["leadership-feedback"],
}
```

#### Change 2: `analyze.py` — Inject trigger awareness

In the ANALYZE prompt template, after the `intended_actions` instruction,
add a trigger awareness block:

```
Available skill triggers for your role:
{trigger_list}
Declare ALL actions you plan to take — including notebook writes,
endorsements, and leadership reviews — so relevant quality skills load.
```

Where `{trigger_list}` is formatted from `get_eligible_triggers()`:
```
- ward_room_reply → loads: communication-discipline
- notebook → loads: notebook-quality
- leadership_review → loads: leadership-feedback
```

#### Change 3: `cognitive_agent.py` — Pass triggers to observation

In `_execute_chain_with_intent_routing()`, before triage:

```python
catalog = self._get_skill_catalog()
if catalog:
    eligible = catalog.get_eligible_triggers(
        department=observation.get("_department"),
        agent_rank=observation.get("_agent_rank"),
    )
    observation["_eligible_triggers"] = eligible
```

**Scale constraint:** This list is scoped per agent. With 100 skills but
only 10-15 relevant to a given agent's department and rank, the injection
stays small (~200 tokens). Universal skills (`department: "*"`) appear for
everyone; department-specific skills only for their department.

---

### Phase 2: Post-Hoc Feedback (Reactive Learning)

**Goal:** When an agent takes an action it didn't declare, provide feedback
so episodic memory captures the miss.

**Mechanism:** After COMPOSE runs, detect undeclared actions in the output.
If found, inject a feedback note into REFLECT so the reflection (which
flows to episodic memory) includes the learning signal.

**Implementation:**

#### Change 4: `cognitive_agent.py` — Detect undeclared actions

New helper method:

```python
def _detect_undeclared_actions(
    self,
    compose_output: str,
    intended_actions: list[str],
) -> list[str]:
    """Detect actions taken in COMPOSE that weren't declared in intended_actions.

    Scans compose output for action markers:
    - [NOTEBOOK ...] tag → 'notebook' action
    - [ENDORSE] tag → 'endorse' action
    - [LEADERSHIP ...] tag → 'leadership_review' action
    - [PROPOSAL ...] tag → 'proposal' action

    Returns list of undeclared action tags.
    """
```

Detection is pattern-based — look for the output markers that correspond
to action tags. These are the same markers COMPOSE already emits:
- `[NOTEBOOK` → `notebook`
- `[ENDORSE]` → `endorse`
- `[LEADERSHIP` → `leadership_review`
- `[PROPOSAL` → `proposal`
- Ward Room post/reply detected by compose mode (not output markers)

#### Change 5: `reflect.py` — Skill trigger feedback injection

When undeclared actions are detected, inject a feedback block into the
REFLECT prompt:

```
## Skill Trigger Feedback

You took the following actions without declaring them in your
intended_actions during triage:
{undeclared_actions_list}

This meant the following quality skills did NOT load for your output:
{missed_skills_list}

In future triage, include these action tags in your intended_actions
so the relevant skills load and improve your output quality.
```

This feedback becomes part of REFLECT's output → stored as episodic
memory → recalled in future triage contexts. The agent literally
remembers being told to declare the action.

#### Change 6: `cognitive_agent.py` — Wire detection into chain

In `_execute_chain_with_intent_routing()`, after COMPOSE completes and
before REFLECT:

```python
# Detect undeclared actions in compose output
compose_result = [r for r in phase2_results if r.sub_task_type == SubTaskType.COMPOSE]
if compose_result and intended_actions:
    undeclared = self._detect_undeclared_actions(
        compose_result[-1].result.get("output", ""),
        intended_actions,
    )
    if undeclared:
        catalog = self._get_skill_catalog()
        missed_skills = []
        for tag in undeclared:
            triggered = catalog.find_triggered_skills(
                [tag], intent, dept, rank_val
            )
            missed_skills.extend(s.name for s in triggered)
        observation["_undeclared_action_feedback"] = {
            "undeclared_actions": undeclared,
            "missed_skills": list(set(missed_skills)),
        }
        logger.info(
            "AD-643b: %s took undeclared actions %s, missed skills %s",
            self.agent_type, undeclared, missed_skills,
        )
```

---

### Phase 3: Trigger Graduation (Cognitive JIT Integration)

**Goal:** As agents internalize trigger declarations through repeated
feedback, remove the prompt-injected trigger list. The Dreyfus progression
applies: novice (needs the list) → proficient (episodic recall) → expert
(automatic).

**Mechanism:** Track trigger declaration accuracy per agent. When an agent
consistently declares triggers correctly (no undeclared actions detected
over N cycles), graduate them from prompt injection.

**Implementation:**

#### Change 7: Trigger proficiency tracking

New lightweight tracker (could be a dict in `CognitiveSkillCatalog` or a
small SQLite table):

```python
@dataclass
class TriggerProficiency:
    agent_type: str
    action_tag: str
    correct_declarations: int = 0    # Declared when needed
    missed_declarations: int = 0     # Took action without declaring
    total_observations: int = 0      # Times action was taken
    graduated: bool = False          # No longer needs prompt injection
```

**Graduation criteria:**
- `correct_declarations >= TRIGGER_GRADUATION_THRESHOLD` (default: 5)
- `missed_declarations == 0` in last `TRIGGER_GRADUATION_WINDOW` cycles
  (default: 10)
- Maps to Dreyfus Level 3+ (Validated) — the agent has demonstrated
  reliable trigger declaration

**Demotion criteria:**
- If a graduated agent misses a declaration, `graduated = False`
- Reset `correct_declarations` to 0
- Maps to Dreyfus demotion (failure → Level 2)

#### Change 8: Scoped trigger injection based on graduation

Modify the trigger awareness injection (Change 2) to exclude graduated
triggers:

```python
eligible = catalog.get_eligible_triggers(department, rank)
graduated = catalog.get_graduated_triggers(agent_type)
# Only inject non-graduated triggers
inject_triggers = {
    tag: skills for tag, skills in eligible.items()
    if tag not in graduated
}
```

An agent who has mastered `notebook` declaration no longer sees it in the
prompt. An agent who still misses `endorse` continues to see it. The
prompt injection shrinks per agent over time.

#### Change 9: Integration with gap detection (AD-539)

When `TriggerProficiency.missed_declarations` exceeds a threshold (e.g.,
5+ misses on the same tag), emit a gap signal to the existing gap
predictor:

```python
if proficiency.missed_declarations >= TRIGGER_GAP_THRESHOLD:
    # Signal to gap_predictor — this is a "knowledge" gap
    # The agent doesn't know to declare this action
    await self._emit_event("SKILL_TRIGGER_GAP", {
        "agent_type": agent_type,
        "action_tag": action_tag,
        "missed_count": proficiency.missed_declarations,
        "gap_type": "knowledge",
    })
```

This connects to the existing Cognitive JIT gap → qualification pipeline.
Persistent trigger misses could eventually trigger a qualification program
focused on triage quality.

---

## Token Economics

**Current state (AD-643a):** ~225K tokens/session saved via silent
short-circuit and targeted skill loading.

**AD-643b additions:**
- Trigger awareness injection: ~100-200 tokens per triage (scoped list)
- Feedback injection: ~50-100 tokens per REFLECT (only on miss events)
- Net: Slight increase per triage, but graduates over time. Long-term,
  mature agents have zero trigger injection overhead.

**Scale projection (100 triggers):**
- Universal triggers (`department: "*"`): maybe 10-15 tags
- Department-specific: 5-10 per department
- Per-agent injection: ~15-25 tags max → ~200 tokens
- After graduation: trending toward 0

---

## Dreyfus Mapping

| Dreyfus Level | Trigger Behavior | Prompt Overhead |
|---|---|---|
| 1 Novice | Full trigger list injected | ~200 tokens |
| 2 Guided | Trigger list + episodic memories of past feedback | ~250 tokens |
| 3 Validated | Graduated triggers removed, only new/missed remain | ~50-100 tokens |
| 4 Autonomous | No trigger injection needed | 0 tokens |
| 5 Expert | Agent correctly predicts novel trigger patterns | 0 tokens |

---

## Backward Compatibility

- Agents without trigger proficiency data get the full scoped list
  (same as Phase 1 only — safe default)
- Skills without `probos-triggers` continue to use intent-based fallback
  (AD-643a backward compat preserved)
- No changes to `_execute_sub_task_chain()` — only
  `_execute_chain_with_intent_routing()` affected

## Test Requirements

### Unit Tests (~35 tests)

**`test_trigger_learning.py`:**

1. `get_eligible_triggers()` — filters by department, rank, returns
   correct action→skill mapping
2. `get_eligible_triggers()` — universal skills (`"*"`) appear for all
3. `get_eligible_triggers()` — rank gating excludes above-rank skills
4. `_detect_undeclared_actions()` — detects `[NOTEBOOK` in output
5. `_detect_undeclared_actions()` — detects `[ENDORSE]` in output
6. `_detect_undeclared_actions()` — no false positive when action declared
7. `_detect_undeclared_actions()` — multiple undeclared actions detected
8. `_detect_undeclared_actions()` — empty output returns empty list
9. Feedback injection into REFLECT — undeclared actions produce feedback block
10. Feedback injection — no feedback when all actions declared
11. Trigger proficiency tracking — correct declaration increments counter
12. Trigger proficiency tracking — missed declaration increments counter
13. Graduation — meets threshold → graduated = True
14. Graduation — missed after graduation → graduated = False (demotion)
15. Scoped injection — graduated triggers excluded from prompt
16. Scoped injection — non-graduated triggers still present
17. Gap signal — persistent misses emit SKILL_TRIGGER_GAP event
18. Integration — full chain with undeclared notebook detects miss
19. Integration — full chain with declared notebook loads skill
20. Integration — graduated agent gets no trigger injection

### Integration Tests (~10 tests)

21. End-to-end: agent declares `notebook` → skill loads → quality output
22. End-to-end: agent misses `notebook` → feedback in REFLECT → episodic stored
23. End-to-end: agent recalls prior feedback → declares correctly next time
24. Graduation lifecycle: miss → feedback → learn → graduate → no injection
25. Demotion lifecycle: graduated → miss → demotion → injection resumes
26. Scale: 50 triggers, agent eligible for 12 → correct scoping
27. Backward compat: skill without triggers → intent fallback works
28. Backward compat: agent without proficiency data → full list injected
29. Multi-skill trigger: `notebook` + `ward_room_post` → both skills load
30. Gap integration: 5+ misses → SKILL_TRIGGER_GAP event emitted

---

## Implementation Order

Recommend phased delivery:

1. **AD-643b-1:** Phase 1 (trigger awareness) — Changes 1-3
   - Low risk, immediate value, agents see available triggers
   - ~15 tests

2. **AD-643b-2:** Phase 2 (post-hoc feedback) — Changes 4-6
   - Medium complexity, requires REFLECT injection wiring
   - Creates the learning loop
   - ~10 tests

3. **AD-643b-3:** Phase 3 (graduation) — Changes 7-9
   - Higher complexity, Cognitive JIT integration
   - Can defer until trigger count warrants it
   - ~10 tests

Each phase is independently valuable and backward compatible.

---

## Research Context

### Cognitive Science Alignment

- **Metacognitive monitoring** (Flavell, 1979): Phase 2 feedback is
  metacognitive — agents monitoring their own cognitive process (triage
  accuracy) and adjusting future behavior.
- **Situated cognition** (Lave & Wenger, 1991): Trigger knowledge is
  situated — agents learn which triggers matter through participation in
  their specific role/department context, not abstract instruction.
- **Scaffolding → fading** (Wood, Bruner & Ross, 1976): Phase 1 provides
  scaffolding (explicit trigger list), Phase 3 fades it as competence
  develops. Classic instructional design pattern.
- **Dreyfus skill acquisition** (Dreyfus & Dreyfus, 1986): Already
  implemented in AD-535 for procedures. AD-643b extends the same
  progression to trigger declaration — from rule-following (list) to
  intuitive pattern recognition (graduated).

### ProbOS Precedent

- **AD-535 graduated compilation:** Same 5-level Dreyfus model, same
  promotion/demotion mechanics, same trust gating.
- **AD-539 gap detection:** Same gap → qualification pipeline. Trigger
  misses are "knowledge" gaps in the existing taxonomy.
- **AD-504 self-monitoring:** Agents already have self-monitoring context.
  Trigger accuracy is another self-monitoring signal.
- **BF-204 confabulation detection:** Same post-COMPOSE detection pattern
  — scan output for markers, inject finding into EVALUATE/REFLECT.

---

## Key Design Decisions

**DD-1: Per-agent scoping, not global injection.**
Inject only triggers the agent is eligible for. Prevents prompt bloat at
scale. Uses existing `find_triggered_skills()` filter logic.

**DD-2: Post-hoc detection, not capability gating.**
Skills are guidance, not gates. An agent can still write a notebook
without `notebook-quality` loaded. Detection informs future behavior
without blocking current output.

**DD-3: Episodic memory as the learning medium.**
REFLECT feedback → episodic storage → future recall. No new learning
infrastructure needed. Rides existing memory recall pipeline.

**DD-4: Graduation reduces overhead over time.**
The trigger list is training wheels that self-remove. Mature crews have
zero trigger injection overhead. New crew get full scaffolding.

**DD-5: Three-phase delivery for risk management.**
Each phase independently valuable. Phase 3 can defer until trigger count
warrants the complexity.
