# AD-596b: Intent Discovery + compose_instructions() Integration

**Priority:** High — Wires T2 cognitive skills into agent prompts and intent routing
**Issue:** #166
**Scope:** OSS (`d:\ProbOS`)
**Dependencies:** AD-596a (Cognitive Skill Catalog — COMPLETE)
**Connects to:** AD-596c (Skill-Registry Bridge), AD-625 (Communication Discipline Skill), AD-339 (Standing Orders)

---

## Context

AD-596a delivered the `CognitiveSkillCatalog` — SKILL.md file discovery, parsing, and serving via REST API. The catalog is wired into runtime (`runtime.cognitive_skill_catalog`) and starts at boot.

**What's missing:** The catalog exists but nothing _uses_ it. Skills are discovered but never:
1. Shown to agents in their system prompt (no progressive disclosure)
2. Loaded on-demand when an intent matches
3. Surfaced to the decomposer for intent routing

**This AD connects the catalog to three integration points:**
1. `compose_instructions()` — inject skill descriptions into the system prompt (progressive disclosure)
2. `_gather_context()` — inject available skill summaries into proactive think context
3. `_collect_intent_descriptors()` — feed cognitive skill intents to the decomposer
4. `handle_intent()` — load full skill instructions on intent match (on-demand activation)

**Design principle:** Progressive disclosure. At startup, agents see skill names + descriptions (~100 tokens each). When an intent matches a skill, the full SKILL.md instructions (<5000 tokens) are loaded and injected into that specific cognitive cycle.

---

## What to Build

### 1. Wire Catalog into `compose_instructions()` — New Tier 7

**File:** `src/probos/cognitive/standing_orders.py`

Add a module-level catalog reference and setter, following the existing `_directive_store` pattern (lines 24-25, 76-79):

```python
# Cognitive skill catalog reference, set by runtime at startup (AD-596b)
_skill_catalog: Any = None

def set_skill_catalog(catalog: Any) -> None:
    """Wire the CognitiveSkillCatalog for tier 7 composition (AD-596b)."""
    global _skill_catalog
    _skill_catalog = catalog
```

Add the `compose_instructions()` function signature — add two new keyword-only parameters:

```python
def compose_instructions(
    agent_type: str,
    hardcoded_instructions: str,
    *,
    orders_dir: Path | None = None,
    department: str | None = None,
    callsign: str | None = None,
    agent_rank: str | None = None,        # NEW: AD-596b — for skill filtering
) -> str:
```

After the existing Tier 6 (Active Directives, line 265), add Tier 7 — Available Cognitive Skills:

```python
    # 7. Available cognitive skills (AD-596b) — progressive disclosure
    if _skill_catalog is not None:
        dept = department or get_department(agent_type)
        skill_descs = _skill_catalog.get_descriptions(
            department=dept,
            agent_rank=agent_rank,
        )
        if skill_descs:
            skill_lines = []
            for sname, sdesc in skill_descs:
                skill_lines.append(f"- **{sname}**: {sdesc}")
            parts.append(
                "## Available Cognitive Skills\n\n"
                "You have access to the following skills. When a task matches "
                "a skill description, the skill's detailed instructions will be "
                "provided automatically.\n\n"
                + "\n".join(skill_lines)
            )
```

**Important:** `compose_instructions()` uses `@lru_cache` on `_load_file()` but is NOT itself cached. The skill descriptions are read from the in-memory catalog cache (fast, O(n) where n = number of skills), so no caching concern.

### 2. Wire Catalog Reference at Startup

**File:** `src/probos/startup/structural_services.py`

Find where `set_directive_store(directive_store)` is called (line 146). Add the catalog wiring immediately after:

```python
from probos.cognitive.standing_orders import set_skill_catalog
if runtime.cognitive_skill_catalog:
    set_skill_catalog(runtime.cognitive_skill_catalog)
```

**File:** `src/probos/startup/shutdown.py`

Find where `set_directive_store(None)` is called (line 163). Add catalog cleanup immediately after:

```python
from probos.cognitive.standing_orders import set_skill_catalog
set_skill_catalog(None)
```

### 3. Pass `agent_rank` Through Existing Call Sites

The `compose_instructions()` function is called in several places. The new `agent_rank` parameter has a default of `None` (no filtering), so existing call sites continue to work unchanged. However, the key conversational call site in `cognitive_agent.py` should pass the rank for proper skill filtering.

**File:** `src/probos/cognitive/cognitive_agent.py`

In `_decide_via_llm()` (line 1203), update the `compose_instructions()` call:

```python
composed = compose_instructions(
    agent_type=getattr(self, "agent_type", self.__class__.__name__.lower()),
    hardcoded_instructions="",
    callsign=self._resolve_callsign(),
    agent_rank=getattr(self, "_rank", None),  # AD-596b: skill filtering
)
```

Check if the agent has a `_rank` attribute. If not, search for how rank is currently resolved. The rank is computed from trust via `Rank.from_trust(trust_score)` in the proactive loop. The agent may store it as `self._rank` or it may need to be resolved. If no `_rank` attribute exists on the agent, pass `None` — this is safe (no filtering = all skills shown).

### 4. Inject Skill Context into `_gather_context()`

**File:** `src/probos/proactive.py`

After section 6 (Skill profile, line 1377), add a new section for cognitive skill descriptions:

```python
        # 7. Cognitive skill catalog (AD-596b) — available skills for this agent
        if hasattr(rt, 'cognitive_skill_catalog') and rt.cognitive_skill_catalog:
            try:
                # Get agent's department and rank for filtering
                _dept = None
                if hasattr(rt, 'ontology') and rt.ontology:
                    _dept = rt.ontology.get_agent_department(agent.agent_type)
                # NOTE: agents do NOT have a _rank attribute. Rank is computed
                # transiently from trust via Rank.from_trust(). Compute here.
                _rank_str = None
                if hasattr(rt, 'trust_network') and rt.trust_network:
                    try:
                        from probos.crew_profile import Rank
                        _trust = rt.trust_network.get_score(agent.id)
                        _rank_str = Rank.from_trust(_trust).value
                    except Exception:
                        pass

                skill_descs = rt.cognitive_skill_catalog.get_descriptions(
                    department=_dept,
                    agent_rank=_rank_str,
                )
                if skill_descs:
                    context["cognitive_skills"] = [
                        {"name": name, "description": desc}
                        for name, desc in skill_descs
                    ]
            except Exception:
                logger.debug("AD-596b: Cognitive skill context failed for %s", agent.id, exc_info=True)
```

### 5. Feed Cognitive Skill Intents to the Decomposer

**File:** `src/probos/runtime.py`

Modify `_collect_intent_descriptors()` (line 2722) to include intents declared by cognitive skills. After collecting from agent templates, also collect from the catalog:

```python
    def _collect_intent_descriptors(self) -> list[IntentDescriptor]:
        """Collect unique intent descriptors from all registered agent templates
        and cognitive skill catalog (AD-596b)."""
        seen: set[str] = set()
        descriptors: list[IntentDescriptor] = []
        # Existing: collect from agent class templates
        for type_name, agent_class in self.spawner._templates.items():
            for desc in getattr(agent_class, "intent_descriptors", []):
                if desc.name not in seen:
                    seen.add(desc.name)
                    descriptors.append(desc)

        # AD-596b: collect from cognitive skill catalog
        if self.cognitive_skill_catalog:
            for entry in self.cognitive_skill_catalog.list_entries():
                for intent_name in entry.intents:
                    if intent_name not in seen:
                        seen.add(intent_name)
                        descriptors.append(IntentDescriptor(
                            name=intent_name,
                            description=f"[Cognitive Skill: {entry.name}] {entry.description}",
                            tier="domain",
                        ))

        return descriptors
```

### 6. On-Demand Skill Instruction Loading in `handle_intent()`

**File:** `src/probos/cognitive/cognitive_agent.py`

This is the core activation mechanism. When an agent receives an intent that matches a cognitive skill, load the full SKILL.md instructions and inject them into the observation context before the `decide()` call.

In `handle_intent()` (line 1404), after the existing `_handled_intents` check (line 1418-1419), add cognitive skill intent discovery:

```python
        # AD-596b: Check if a cognitive skill handles this intent
        _cognitive_skill_instructions = None
        if not is_direct and intent.intent not in self._handled_intents:
            # Not in hardcoded intents — check cognitive skill catalog
            _catalog = getattr(self, '_cognitive_skill_catalog', None)
            if _catalog:
                _skill_entries = _catalog.find_by_intent(intent.intent)
                if _skill_entries:
                    # Found a matching cognitive skill — load its instructions
                    _entry = _skill_entries[0]  # First match
                    _cognitive_skill_instructions = _catalog.get_instructions(_entry.name)
                    if _cognitive_skill_instructions:
                        logger.info(
                            "AD-596b: Loaded cognitive skill '%s' for intent '%s' on %s",
                            _entry.name, intent.intent, self.agent_type,
                        )
                    else:
                        # Skill found but instructions couldn't be loaded
                        return None
                else:
                    # No cognitive skill handles this intent either
                    return None
            else:
                return None
```

Then, in the observation dict constructed for `decide()`, inject the skill instructions if present. Find where the observation is built (after the `perceive()` call or the observation construction section) and add:

```python
        # AD-596b: Inject cognitive skill instructions into observation context
        if _cognitive_skill_instructions:
            observation["cognitive_skill_instructions"] = _cognitive_skill_instructions
            observation["cognitive_skill_name"] = _skill_entries[0].name
```

In `_decide_via_llm()`, when constructing the system prompt for a cognitive skill activation, the skill instructions should be appended to the composed instructions. Find where `composed` is built (line 1203-1207 for conversational path) and add after:

```python
        # AD-596b: Append cognitive skill instructions when activated
        _skill_instr = observation.get("cognitive_skill_instructions")
        if _skill_instr:
            composed += f"\n\n---\n\n## Active Skill: {observation.get('cognitive_skill_name', 'Unknown')}\n\n{_skill_instr}"
```

### 7. Wire Catalog Reference onto Agents During Onboarding

**File:** `src/probos/agent_onboarding.py`

The catalog needs to be accessible on each agent for `handle_intent()` to check.

**IMPORTANT:** `AgentOnboardingService` is constructed in `runtime.py:1064` **before** the communication phase runs — the catalog doesn't exist yet at construction time. Follow the existing late-binding pattern used by `set_tool_registry()` (line 82) and `set_orientation_service()` (line 78).

Add a public setter (after `set_tool_registry` at line 84):

```python
    def set_cognitive_skill_catalog(self, catalog: Any) -> None:
        """AD-596b: Set cognitive skill catalog (public setter for LoD)."""
        self._cognitive_skill_catalog = catalog
```

Add the instance variable initialization in `__init__` (after `self._tool_registry` at line 74):

```python
        self._cognitive_skill_catalog: Any = None  # AD-596b: Late-bound
```

In `wire_agent()`, after ToolContext creation (line ~359, end of the method), add:

```python
        # AD-596b: Wire cognitive skill catalog for on-demand skill loading
        if self._cognitive_skill_catalog:
            agent._cognitive_skill_catalog = self._cognitive_skill_catalog
```

**File:** `src/probos/startup/finalize.py`

After the `set_tool_registry` call (line 151), add:

```python
    # AD-596b: Wire cognitive skill catalog into onboarding service
    if runtime.cognitive_skill_catalog:
        runtime.onboarding.set_cognitive_skill_catalog(runtime.cognitive_skill_catalog)
```

### 8. Register Cognitive Skill Intents on the IntentBus

When a cognitive skill declares intents via `probos-intents`, those intents need to be registered on the IntentBus so the broadcast routing includes agents that can handle them.

**File:** `src/probos/agent_onboarding.py`

In `wire_agent()`, at the intent bus subscription block (lines 111-114), extend the intent_names list to include intents from cognitive skills available to this agent:

```python
        if hasattr(agent, "handle_intent"):
            intent_names = [d.name for d in getattr(agent, "intent_descriptors", [])] or []

            # AD-596b: Add intents from cognitive skills available to this agent
            if self._cognitive_skill_catalog:
                _dept = None
                if self._ontology:
                    _dept = self._ontology.get_agent_department(agent.agent_type)
                # NOTE: agents do NOT have a _rank attribute. Rank is computed
                # from trust. Resolve it the same way AD-423c ToolContext does
                # (see wire_agent lines 326-332).
                _rank_str = None
                try:
                    _trust = self._trust_network.get_score(agent.id)
                    from probos.crew_profile import Rank
                    _rank_str = Rank.from_trust(_trust).value
                except Exception:
                    pass
                for entry in self._cognitive_skill_catalog.list_entries(department=_dept, min_rank=_rank_str):
                    for intent_name in entry.intents:
                        if intent_name not in intent_names:
                            intent_names.append(intent_name)

            self._intent_bus.subscribe(
                agent.id, agent.handle_intent,
                intent_names=intent_names if intent_names else None,
            )
```

Note the original code uses `or None` on intent_names — the updated version should preserve that behavior: pass `None` if the list is empty (agent receives all broadcasts), pass the list if non-empty.

---

## Engineering Principles Compliance

- **Single Responsibility:** Each integration point has a focused change. `compose_instructions()` does progressive disclosure. `handle_intent()` does on-demand loading. `_collect_intent_descriptors()` does decomposer discovery. No single function does all three.
- **Open/Closed:** Existing `_handled_intents` mechanism is preserved. Cognitive skills extend it without modifying it. An agent's hardcoded intents + cognitive skill intents coexist.
- **Dependency Inversion:** Catalog is injected via constructor (onboarding) and module-level setter (standing_orders). No direct imports of concrete classes in composition functions.
- **Law of Demeter:** Agent accesses `self._cognitive_skill_catalog.find_by_intent()` — one level of indirection. No reaching through `runtime.cognitive_skill_catalog` from inside agent code.
- **Fail Fast:** Missing catalog = no skill features (graceful degradation). Invalid skill entries were already filtered at parse time (AD-596a). `try/except` with `logger.debug` wraps all optional enrichments.
- **DRY:** Reuses `_skill_catalog.get_descriptions()` — the same method serves both `compose_instructions()` and `_gather_context()`. Reuses `_skill_catalog.find_by_intent()` for both IntentBus registration and `handle_intent()` dispatch.
- **Defense in Depth:** Rank and department filtering applied at every access point: `compose_instructions()`, `_gather_context()`, IntentBus registration.
- **Cloud-Ready Storage:** No new database operations — uses existing `CognitiveSkillCatalog` in-memory cache.

---

## Test Requirements

**File:** `tests/test_cognitive_skill_596b.py` (new)

### compose_instructions() Integration

- `test_compose_includes_skill_descriptions` — With catalog set, output includes "Available Cognitive Skills" section
- `test_compose_no_catalog_no_skills_section` — Without catalog, output unchanged from baseline
- `test_compose_filters_by_department` — Agent in "engineering" only sees engineering + wildcard skills
- `test_compose_filters_by_rank` — Ensign-ranked agent doesn't see commander-rank skills
- `test_compose_agent_rank_none_shows_all` — `agent_rank=None` shows all skills (backward compat)

### _gather_context() Integration

- `test_gather_context_includes_cognitive_skills` — Context dict has `cognitive_skills` key with name/description pairs
- `test_gather_context_no_catalog_no_skills` — Without catalog, context unchanged
- `test_gather_context_filters_by_department_and_rank` — Proper filtering applied

### _collect_intent_descriptors() Integration

- `test_collect_descriptors_includes_catalog_intents` — Descriptor list includes cognitive skill intents
- `test_collect_descriptors_deduplicates` — If agent template and skill declare same intent, no duplicate
- `test_collect_descriptors_no_catalog_unchanged` — Without catalog, returns only template descriptors

### handle_intent() — On-Demand Loading

- `test_handle_intent_cognitive_skill_match` — Intent not in `_handled_intents` but in catalog → skill instructions loaded and decision made
- `test_handle_intent_no_match_returns_none` — Intent not in `_handled_intents` and not in catalog → returns None
- `test_handle_intent_hardcoded_takes_precedence` — Intent in both `_handled_intents` and catalog → hardcoded path used (no regression)
- `test_handle_intent_skill_instructions_injected` — Observation dict contains `cognitive_skill_instructions` when skill activated
- `test_handle_intent_no_catalog_returns_none` — Agent without catalog set, unhandled intent → returns None

### Onboarding Wiring

- `test_wire_agent_sets_catalog_on_agent` — After `wire_agent()`, agent has `_cognitive_skill_catalog` attribute
- `test_wire_agent_registers_skill_intents_on_bus` — IntentBus subscription includes cognitive skill intent names
- `test_wire_agent_no_catalog_unchanged` — Without catalog, `wire_agent()` behaves identically to before

### Startup/Shutdown

- `test_startup_sets_skill_catalog_on_standing_orders` — After structural services, `_skill_catalog` is not None
- `test_shutdown_clears_skill_catalog` — After shutdown, `_skill_catalog` is None

---

## Files to Create

| File | Purpose |
|------|---------|
| `tests/test_cognitive_skill_596b.py` | All tests |

## Files to Modify

| File | Change |
|------|--------|
| `src/probos/cognitive/standing_orders.py` | Add `_skill_catalog` module-level ref + `set_skill_catalog()` setter + Tier 7 in `compose_instructions()` + `agent_rank` parameter |
| `src/probos/cognitive/cognitive_agent.py` | `handle_intent()` cognitive skill dispatch + `_decide_via_llm()` skill instruction injection + pass `agent_rank` to `compose_instructions()` |
| `src/probos/proactive.py` | `_gather_context()` section 7 — cognitive skill descriptions |
| `src/probos/runtime.py` | `_collect_intent_descriptors()` — add catalog intents |
| `src/probos/agent_onboarding.py` | `set_cognitive_skill_catalog()` setter + `wire_agent()` — catalog injection onto agents + IntentBus skill intent registration |
| `src/probos/startup/structural_services.py` | Wire `set_skill_catalog()` after `set_directive_store()` |
| `src/probos/startup/shutdown.py` | Clear `set_skill_catalog(None)` after `set_directive_store(None)` |
| `src/probos/startup/finalize.py` | Wire `set_cognitive_skill_catalog()` onto onboarding service (after `set_tool_registry`) |

## Files NOT to Modify

- `src/probos/cognitive/skill_catalog.py` — AD-596a is complete, no changes needed
- `src/probos/skill_framework.py` — Registry bridge is AD-596c
- `src/probos/routers/skills.py` — API endpoints already exist from AD-596a
- `src/probos/startup/communication.py` — Onboarding is constructed in `runtime.py`, not here. Catalog is already wired via `CommunicationResult.cognitive_skill_catalog` (AD-596a)

---

## Verification

After implementation:
1. `pytest tests/test_cognitive_skill_596b.py -v` — All new tests pass
2. `pytest tests/test_cognitive_skill_catalog.py -v` — AD-596a tests still pass
3. `pytest tests/test_skill_framework.py -v` — Existing skill tests unbroken
4. `pytest tests/test_standing_orders.py -v` — Standing orders tests unbroken
5. `pytest tests/ -x --timeout=60` — Full suite passes (run in background)
6. Manual verification: Start runtime → check that `communication-discipline` skill description appears when composing instructions for any agent → check `/api/skills/catalog` still returns the skill
