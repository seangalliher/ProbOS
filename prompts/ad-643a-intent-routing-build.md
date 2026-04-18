# AD-643a Build Prompt: Intent Routing + Targeted Skill Loading

**Parent design:** `prompts/ad-643-intent-driven-skill-activation.md`
**Phase:** AD-643a (of three phases: a, b, c)
**Depends on:** AD-626 (dual-mode skill activation), AD-632f/h (sub-task chains)
**Principles:** SRP, Open/Closed, Defense in Depth, DRY, Fail Fast

---

## Goal

Move augmentation skill loading from **before** the chain to **after** the
ANALYZE step. ANALYZE expresses `intended_actions` (what the agent wants to
do). Skills declare `probos-triggers` (what actions they enhance). Only
skills whose triggers match the agent's intended actions are loaded.

The communication chain only fires for communication-related actions, not
for every `proactive_think`. Non-communication actions (notebook, leadership
review) fall through to the existing single-call `_decide_via_llm()` path
until AD-643b/c add dedicated thought processes for them.

**Token savings:** ~1,500 tokens/cycle × 30 agents × 5 cycles = ~225K
tokens/session eliminated when agents don't intend communication actions.

---

## What to Change

### 1. `CognitiveSkillEntry` — Add `triggers` field

**File:** `src/probos/cognitive/skill_catalog.py`
**Line:** After line 69 (`activation` field), add:

```python
triggers: list[str] = field(default_factory=list)  # AD-643a: action tags this skill enhances
```

This is an in-memory field like `activation` — NOT stored in SQLite. Parsed
from SKILL.md metadata at load time.

### 2. `parse_skill_file()` — Parse `probos-triggers`

**File:** `src/probos/cognitive/skill_catalog.py`
**Location:** Inside `parse_skill_file()`, after the `activation` parsing
block (after line 141). Same pattern as `probos-intents` parsing.

Parse `probos-triggers` from the `metadata` block:

```python
# AD-643a: Parse trigger tags for intent-driven activation
triggers_str = str(meta.get("probos-triggers", "")).strip()
if "," in triggers_str:
    triggers = [t.strip().lower() for t in triggers_str.split(",") if t.strip()]
else:
    triggers = [t.lower() for t in triggers_str.split() if t] if triggers_str else []
```

Pass `triggers=triggers` to the `CognitiveSkillEntry` constructor (line 156
area).

### 3. `find_triggered_skills()` — New method on `CognitiveSkillCatalog`

**File:** `src/probos/cognitive/skill_catalog.py`
**Location:** After `find_augmentation_skills()` (after line 409).

```python
def find_triggered_skills(
    self,
    intended_actions: list[str],
    intent_name: str,
    department: str | None = None,
    agent_rank: str | None = None,
) -> list[CognitiveSkillEntry]:
    """AD-643a: Find augmentation skills matching specific action triggers.

    Unlike find_augmentation_skills() which matches by intent name,
    this matches by action trigger tags declared in probos-triggers.
    Falls back to find_augmentation_skills() if no triggers are defined
    on any skill (backward compatibility).

    Args:
        intended_actions: Action tags from ANALYZE output (e.g., ["ward_room_reply", "notebook"])
        intent_name: The parent intent (e.g., "proactive_think") — used for fallback
        department: Optional department filter
        agent_rank: Optional rank filter

    Returns:
        List of matching CognitiveSkillEntry objects.
    """
    if not intended_actions:
        return []

    action_set = set(intended_actions)
    results = []
    for entry in self._cache.values():
        if entry.activation not in ("augmentation", "both"):
            continue
        # AD-643a: Match by triggers if declared
        if entry.triggers:
            if not action_set.intersection(entry.triggers):
                continue
        else:
            # No triggers declared — fall back to intent matching (backward compat)
            if intent_name not in entry.intents:
                continue
        # Department gate
        if department and entry.department != "*" and entry.department != department:
            continue
        # Rank gate
        if agent_rank:
            agent_rank_order = _RANK_ORDER.get(agent_rank, 0)
            if _RANK_ORDER.get(entry.min_rank, 0) > agent_rank_order:
                continue
        results.append(entry)
    return results
```

### 4. ANALYZE prompts — Add `intended_actions` output field

**File:** `src/probos/cognitive/sub_tasks/analyze.py`

#### 4a. Situation review (proactive_think) — `_build_situation_review_prompt()`

**Current** (lines 141-147): 4 JSON keys, returns "4 keys".

**Change:** Add a 5th key after `department_relevance`:

```python
"5. **intended_actions**: What actions will you take? List as a JSON array from:\n"
"   ward_room_post, ward_room_reply, endorse, notebook, leadership_review,\n"
"   proposal, dm, silent. Include ALL that apply.\n"
"   Examples: [\"ward_room_post\", \"notebook\"], [\"endorse\"], [\"silent\"]\n\n"
"Return a JSON object with these 5 keys. No other text."
```

Replace the existing "Return a JSON object with these 4 keys" line.

#### 4b. Thread analysis (ward_room_notification) — `_build_thread_analysis_prompt()`

**Current** (lines 89-92): 5 JSON keys, returns "5 keys".

**Change:** Add a 6th key after `contribution_assessment`:

```python
"6. **intended_actions**: Based on your contribution_assessment, what\n"
"   specific actions will you take? List as a JSON array from:\n"
"   ward_room_reply, endorse, silent.\n"
"   If RESPOND: [\"ward_room_reply\"]. If ENDORSE: [\"endorse\"].\n"
"   If both: [\"ward_room_reply\", \"endorse\"]. If SILENT: [\"silent\"].\n\n"
"Return a JSON object with these 6 keys. No other text."
```

Replace the existing "Return a JSON object with these 5 keys" line.

### 5. Extract `intended_actions` from ANALYZE result

**File:** `src/probos/cognitive/cognitive_agent.py`

Create a helper method on `CognitiveAgent`:

```python
@staticmethod
def _extract_intended_actions(chain_results: list) -> list[str]:
    """AD-643a: Extract intended_actions from ANALYZE step results.

    Returns normalized list of action tags, or empty list if not found.
    Handles: list, comma-separated string, single string.
    """
    from probos.cognitive.sub_task import SubTaskType
    for r in reversed(chain_results):
        if r.sub_task_type == SubTaskType.ANALYZE and r.success and r.result:
            raw = r.result.get("intended_actions")
            if raw is None:
                return []
            if isinstance(raw, list):
                return [str(a).strip().lower() for a in raw if str(a).strip()]
            if isinstance(raw, str):
                # Handle comma-separated or single value
                if "," in raw:
                    return [a.strip().lower() for a in raw.split(",") if a.strip()]
                stripped = raw.strip().lower()
                return [stripped] if stripped else []
            return []
    return []
```

### 6. Two-phase chain execution in `decide()`

**File:** `src/probos/cognitive/cognitive_agent.py`
**Location:** Lines 1168-1196 (the skill loading + chain activation block).

Replace the current flow with two-phase execution:

**Current flow (lines 1168-1196):**
```
1. Load ALL augmentation skills (line 1169-1172)
2. Check chain activation (line 1181)
3. Build chain (line 1182)
4. Execute full chain (line 1191)
```

**New flow:**
```
1. Check chain activation (intent eligible + executor exists)
2. Build and execute TRIAGE phase only (QUERY + ANALYZE)
3. Extract intended_actions from ANALYZE result
4. Route based on intended_actions:
   a. ["silent"] only → short-circuit, return NO_RESPONSE
   b. Communication actions present → load triggered skills, execute
      remaining chain steps (COMPOSE + EVALUATE + REFLECT)
   c. No communication actions → skip chain, fall through to
      _decide_via_llm() with triggered skills in observation
   d. Empty intended_actions (fallback) → pre-AD-643 behavior
```

**Implementation approach:**

The key change is splitting `_execute_sub_task_chain()` into two phases.
Rather than modifying that method (which is complex and battle-tested),
create a new method `_execute_chain_with_intent_routing()`:

```python
async def _execute_chain_with_intent_routing(self, observation: dict) -> dict | None:
    """AD-643a: Two-phase chain execution with intent-driven skill loading.

    Phase 1 (Triage): QUERY + ANALYZE — no skills, determines intended_actions.
    Phase 2 (Execute): Load targeted skills, run remaining chain steps.

    Returns decision dict or None (fall through to _decide_via_llm).
    """
    from probos.cognitive.sub_task import SubTaskChain, SubTaskSpec, SubTaskType

    intent = observation.get("intent", "")

    # --- Phase 1: Build and execute triage (QUERY + ANALYZE only) ---
    full_chain = self._build_chain_for_intent(observation)
    if full_chain is None:
        return None

    # Split chain: triage = QUERY + ANALYZE, execute = COMPOSE + EVALUATE + REFLECT
    triage_steps = [s for s in full_chain.steps if s.sub_task_type in (SubTaskType.QUERY, SubTaskType.ANALYZE)]
    execute_steps = [s for s in full_chain.steps if s.sub_task_type not in (SubTaskType.QUERY, SubTaskType.ANALYZE)]

    if not triage_steps:
        # No triage steps — fall back to full chain with all skills
        return None

    triage_chain = SubTaskChain(
        steps=triage_steps,
        chain_timeout_ms=full_chain.chain_timeout_ms,
        fallback=full_chain.fallback,
        source=f"{full_chain.source}:triage",
    )

    try:
        triage_results = await self._sub_task_executor.execute(
            triage_chain,
            observation,
            agent_id=self.id,
            agent_type=self.agent_type,
            intent=intent,
            intent_id=observation.get("intent_id", ""),
            journal=self._cognitive_journal,
        )
    except Exception as exc:
        logger.warning("AD-643a: Triage phase failed, falling back: %s", exc)
        return None

    # --- Extract intended_actions ---
    intended_actions = self._extract_intended_actions(triage_results)

    if not intended_actions:
        # ANALYZE didn't produce intended_actions — fall back to pre-AD-643 behavior
        logger.info("AD-643a: No intended_actions from ANALYZE, falling back to full chain")
        _aug = self._load_augmentation_skills(intent)
        if _aug:
            observation["_augmentation_skill_instructions"] = _aug
        # Re-execute full chain (triage results are lost — acceptable for fallback)
        return await self._execute_sub_task_chain(full_chain, observation)

    logger.info(
        "AD-643a: Agent %s intended_actions=%s (intent=%s)",
        self.agent_type, intended_actions, intent,
    )

    # --- Silent short-circuit ---
    if intended_actions == ["silent"]:
        logger.info("AD-643a: Silent intent — short-circuiting")
        return {
            "action": "execute",
            "llm_output": "[NO_RESPONSE]",
            "tier_used": "",
            "sub_task_chain": True,
            "chain_source": f"{full_chain.source}:silent",
            "chain_steps": len(triage_steps),
        }

    # --- Determine if communication chain should fire ---
    _COMM_ACTIONS = frozenset({"ward_room_post", "ward_room_reply", "endorse", "dm"})
    has_comm_action = bool(_COMM_ACTIONS.intersection(intended_actions))

    # --- Load targeted skills based on intended_actions ---
    catalog = getattr(self, '_cognitive_skill_catalog', None)
    if catalog:
        department = getattr(self, 'department', None)
        rank = getattr(self, 'rank', None)
        rank_val = rank.value if hasattr(rank, 'value') else rank
        entries = catalog.find_triggered_skills(
            intended_actions, intent,
            department=department, agent_rank=rank_val,
        )
        if entries:
            bridge = getattr(self, '_skill_bridge', None)
            profile = getattr(self, '_skill_profile', None)
            parts = []
            loaded_entries = []
            for entry in entries:
                if bridge and not bridge.check_proficiency_gate(self.id, entry, profile):
                    continue
                instructions = catalog.get_instructions(entry.name)
                if instructions:
                    parts.append(instructions)
                    loaded_entries.append(entry)
                    logger.info(
                        "AD-643a: Loaded triggered skill '%s' for actions %s on %s",
                        entry.name, intended_actions, self.agent_type,
                    )
            if parts:
                observation["_augmentation_skill_instructions"] = "".join(parts)
            self._augmentation_skills_used = loaded_entries
        else:
            self._augmentation_skills_used = []
    else:
        self._augmentation_skills_used = []

    # --- Phase 2: Execute remaining chain or fall through ---
    if has_comm_action and execute_steps:
        # Build execute chain with triage results carried forward
        execute_chain = SubTaskChain(
            steps=execute_steps,
            chain_timeout_ms=full_chain.chain_timeout_ms,
            fallback=full_chain.fallback,
            source=f"{full_chain.source}:execute",
        )

        # Inject triage results as prior context for execute phase
        # The executor passes prior_results to handlers — we need to
        # prepend triage_results. The cleanest way: re-build a full chain
        # with all steps but skip already-completed triage steps.
        # Actually, use the full chain and pass triage_results as initial state.
        #
        # SIMPLEST APPROACH: Rebuild full chain, execute it, but triage
        # steps will re-execute (cheap: QUERY is deterministic, ANALYZE
        # is one LLM call). This avoids modifying SubTaskExecutor.
        #
        # BETTER APPROACH: Execute full chain from scratch with skills now
        # loaded. Triage re-runs but that's 1 QUERY (0 tokens) + 1 ANALYZE
        # call. Total overhead: ~200 tokens. Acceptable for correctness.
        return await self._execute_sub_task_chain(full_chain, observation)
    else:
        # Non-communication actions: fall through to _decide_via_llm()
        # Skills are already loaded in observation if any matched.
        # Return None to signal "use single-call path".
        logger.info(
            "AD-643a: No comm actions in %s — skipping chain, using single-call",
            intended_actions,
        )
        return None
```

### 7. Wire the new method into `decide()`

**File:** `src/probos/cognitive/cognitive_agent.py`
**Location:** Lines 1168-1196

Replace:

```python
# --- AD-632f: Load augmentation skills before chain check (Compose handler needs them) ---
if observation.get("intent") in _CHAIN_ELIGIBLE_INTENTS:
    _aug = self._load_augmentation_skills(observation.get("intent", ""))
    if _aug:
        observation["_augmentation_skill_instructions"] = _aug

# --- AD-632f: Sub-task chain activation (Level 3) ---
# Priority 1: externally-set chain (escape hatch for skills, JIT, etc.)
# Priority 2: inline trigger evaluation
chain = None
if self._pending_sub_task_chain is not None:
    chain = self._pending_sub_task_chain
    self._pending_sub_task_chain = None  # consume once
elif self._should_activate_chain(observation):
    chain = self._build_chain_for_intent(observation)

if chain is not None:
    logger.info(
        "AD-632f: Chain activated for %s (intent=%s, source=%s)",
        self.agent_type,
        observation.get("intent", ""),
        getattr(chain, "source", "unknown"),
    )
    chain_result = await self._execute_sub_task_chain(chain, observation)
    if chain_result is not None:
        _cache_ttl = self._get_cache_ttl()
        cache[cache_key] = (chain_result, time.monotonic(), _cache_ttl)
        return chain_result
    logger.info("AD-632f: Falling back to single-call for %s", self.agent_type)
```

With:

```python
# --- AD-643a: Intent-driven chain activation with targeted skill loading ---
# Priority 1: externally-set chain (escape hatch for skills, JIT, etc.)
if self._pending_sub_task_chain is not None:
    chain = self._pending_sub_task_chain
    self._pending_sub_task_chain = None  # consume once
    # External chains get all augmentation skills (pre-AD-643 behavior)
    if observation.get("intent") in _CHAIN_ELIGIBLE_INTENTS:
        _aug = self._load_augmentation_skills(observation.get("intent", ""))
        if _aug:
            observation["_augmentation_skill_instructions"] = _aug
    logger.info(
        "AD-632f: External chain activated for %s (intent=%s, source=%s)",
        self.agent_type,
        observation.get("intent", ""),
        getattr(chain, "source", "unknown"),
    )
    chain_result = await self._execute_sub_task_chain(chain, observation)
    if chain_result is not None:
        _cache_ttl = self._get_cache_ttl()
        cache[cache_key] = (chain_result, time.monotonic(), _cache_ttl)
        return chain_result
    logger.info("AD-632f: Falling back to single-call for %s", self.agent_type)

# Priority 2: intent-driven routing (AD-643a)
elif self._should_activate_chain(observation):
    chain_result = await self._execute_chain_with_intent_routing(observation)
    if chain_result is not None:
        _cache_ttl = self._get_cache_ttl()
        cache[cache_key] = (chain_result, time.monotonic(), _cache_ttl)
        return chain_result
    # chain_result is None → fall through to _decide_via_llm()
    # Skills may already be loaded in observation from intent routing
```

### 8. Update `_should_short_circuit()` for `intended_actions`

**File:** `src/probos/cognitive/sub_tasks/compose.py`
**Location:** `_should_short_circuit()` (lines 32-44)

Add `intended_actions` check alongside `contribution_assessment`:

After line 42 (`if r.get("should_respond") is False:`), add:

```python
            # AD-643a: Also check intended_actions
            actions = r.get("intended_actions")
            if isinstance(actions, list) and actions == ["silent"]:
                return True
            if isinstance(actions, str) and actions.strip().lower() == "silent":
                return True
```

### 9. Update SKILL.md files with `probos-triggers`

#### `config/skills/communication-discipline/SKILL.md`

Add to metadata block:

```yaml
  probos-triggers: "ward_room_post,ward_room_reply,endorse"
```

#### `config/skills/notebook-quality/SKILL.md`

Add to metadata block:

```yaml
  probos-triggers: "notebook"
```

#### `config/skills/leadership-feedback/SKILL.md`

Add to metadata block:

```yaml
  probos-triggers: "leadership_review"
```

---

## Do NOT Change

- `sub_task.py` — SubTaskExecutor, SubTaskSpec, SubTaskChain unchanged
- `skill_bridge.py` — proficiency gating is orthogonal
- `skill_framework.py` — T3 registry not involved
- `_build_chain_for_intent()` — chains stay as-is; AD-643b replaces them
- `evaluate.py` / `reflect.py` — skill injection stays the same mechanism
- SQLite schema — `triggers` is in-memory only (like `activation`)
- `_decide_via_llm()` — single-call path unchanged; it receives skills
  via observation if intent routing loaded them

---

## Backward Compatibility

1. **`intended_actions` absent from ANALYZE result** → `_extract_intended_actions()`
   returns `[]` → fall back to pre-AD-643 full chain with all skills loaded.
   This handles: older LLM outputs, JSON parse failures, unexpected formats.

2. **Skills without `probos-triggers`** → `find_triggered_skills()` falls
   back to intent matching (same as `find_augmentation_skills()`). Existing
   skills without triggers work exactly as before.

3. **External chains (`_pending_sub_task_chain`)** → bypass intent routing
   entirely, use pre-AD-643 all-skills behavior. Ensures JIT, skills, and
   other chain sources are unaffected.

4. **Agents without executor** → `_should_activate_chain()` returns False
   (existing gate). No change needed.

---

## Known Issues (NOT in scope)

1. **`_RANK_ORDER` incomplete** — Missing `lieutenant_commander`,
   `lieutenant_junior`, `captain`. Leadership-feedback's rank gate works by
   accident (unknown ranks default to 0). Separate BF ticket.

2. **`_augmentation_skills_used` not in observation** — Set on `self` but
   compose.py reads from `context`. Compose gets generic "augmentation" name
   instead of actual skill name. Cosmetic. Separate fix.

3. **Triage re-execution overhead** — Phase 2 re-executes QUERY + ANALYZE
   (~200 extra tokens) because SubTaskExecutor doesn't support injecting
   prior results. Acceptable tradeoff vs modifying the executor.
   AD-643b eliminates this with proper thought process execution.

---

## Test Requirements

Create `tests/test_ad643a_intent_routing.py`:

### TestSkillTriggerParsing

```python
def test_triggers_parsed_from_skill_md():
    """probos-triggers: 'ward_room_post,ward_room_reply' → ['ward_room_post', 'ward_room_reply']"""
    # Create temp SKILL.md with triggers, parse, verify entry.triggers

def test_single_trigger_parsed():
    """probos-triggers: 'notebook' → ['notebook']"""

def test_empty_triggers_default():
    """No probos-triggers → triggers == []"""

def test_triggers_lowercased():
    """probos-triggers: 'Ward_Room_Post' → ['ward_room_post']"""
```

### TestFindTriggeredSkills

```python
def test_matches_single_trigger():
    """intended_actions=['notebook'] matches skill with triggers=['notebook']"""

def test_matches_one_of_multiple_triggers():
    """intended_actions=['endorse'] matches skill with triggers=['ward_room_post','ward_room_reply','endorse']"""

def test_no_match_returns_empty():
    """intended_actions=['notebook'] doesn't match skill with triggers=['ward_room_reply']"""

def test_no_triggers_falls_back_to_intent():
    """Skill without triggers matched by intent_name (backward compat)"""

def test_rank_gate_applies():
    """lieutenant_commander skill not returned for ensign rank"""

def test_department_gate_applies():
    """Department-specific skill not returned for other department"""

def test_empty_intended_actions_returns_empty():
    """intended_actions=[] → no skills returned"""
```

### TestIntendedActionsExtraction

```python
def test_list_extracted():
    """ANALYZE result with intended_actions: ["ward_room_reply"] → ["ward_room_reply"]"""

def test_string_normalized_to_list():
    """ANALYZE result with intended_actions: "notebook" → ["notebook"]"""

def test_comma_string_split():
    """ANALYZE result with intended_actions: "ward_room_reply,notebook" → ["ward_room_reply", "notebook"]"""

def test_missing_field_returns_empty():
    """ANALYZE result without intended_actions → []"""

def test_values_lowercased_and_stripped():
    """" Ward_Room_Reply " → ["ward_room_reply"]"""

def test_non_analyze_results_skipped():
    """Only ANALYZE results are checked, not COMPOSE/EVALUATE/REFLECT"""
```

### TestChainRouting

```python
def test_comm_action_triggers_chain():
    """intended_actions=['ward_room_reply'] → full chain executes"""

def test_notebook_skips_chain():
    """intended_actions=['notebook'] → chain skipped, falls to single-call"""

def test_silent_short_circuits():
    """intended_actions=['silent'] → NO_RESPONSE without COMPOSE/EVALUATE/REFLECT"""

def test_mixed_with_comm_triggers_chain():
    """intended_actions=['ward_room_reply','notebook'] → chain fires (has comm action)"""

def test_fallback_on_missing_actions():
    """No intended_actions → full chain with all skills (backward compat)"""

def test_external_chain_bypasses_routing():
    """_pending_sub_task_chain → pre-AD-643 all-skills behavior"""
```

### TestTargetedSkillLoading

```python
def test_notebook_loads_notebook_skill_only():
    """intended_actions=['notebook'] → only notebook-quality loaded"""

def test_comm_loads_comm_skill_only():
    """intended_actions=['ward_room_post'] → only communication-discipline loaded"""

def test_multiple_actions_load_multiple_skills():
    """intended_actions=['ward_room_post','notebook'] → both skills loaded"""

def test_silent_loads_no_skills():
    """intended_actions=['silent'] → no skills loaded"""

def test_leadership_review_loads_leadership_skill():
    """intended_actions=['leadership_review'] → leadership-feedback loaded"""
```

### TestShortCircuitIntegration

```python
def test_compose_short_circuits_on_intended_actions_silent():
    """_should_short_circuit returns True when intended_actions == ['silent']"""

def test_compose_short_circuit_social_override():
    """Captain message overrides silent intended_actions (existing BF-186 behavior)"""
```

### Existing test suites — verify no regressions

```bash
pytest tests/test_ad625_comm_discipline.py -v
pytest tests/test_ad626_skill_activation.py -v
pytest tests/test_ad630_leadership_feedback.py -v
pytest tests/test_ad634_notebook_quality.py -v
pytest tests/test_ad632d_compose_handler.py -v
pytest tests/test_ad632f_activation_triggers.py -v
pytest tests/ -k "skill or chain or sub_task" --tb=short
```

---

## Verification Checklist

- [ ] `CognitiveSkillEntry` has `triggers: list[str]` field
- [ ] `parse_skill_file()` reads `probos-triggers` from YAML metadata
- [ ] `find_triggered_skills()` matches intended_actions to triggers
- [ ] `find_triggered_skills()` falls back to intent matching when no triggers
- [ ] ANALYZE situation review prompt requests `intended_actions` (5 keys)
- [ ] ANALYZE thread analysis prompt requests `intended_actions` (6 keys)
- [ ] `_extract_intended_actions()` handles list, string, missing, malformed
- [ ] `_execute_chain_with_intent_routing()` splits triage from execute
- [ ] Silent intended_actions short-circuit before COMPOSE
- [ ] Communication actions trigger full chain; non-comm actions fall through
- [ ] `_should_short_circuit()` checks `intended_actions` alongside `contribution_assessment`
- [ ] External chains (`_pending_sub_task_chain`) bypass intent routing
- [ ] Missing `intended_actions` falls back to pre-AD-643 full chain behavior
- [ ] All three SKILL.md files updated with `probos-triggers`
- [ ] Communication-discipline triggers: `ward_room_post,ward_room_reply,endorse`
- [ ] Notebook-quality triggers: `notebook`
- [ ] Leadership-feedback triggers: `leadership_review`
- [ ] Token savings logged — "AD-643a: Loaded triggered skill" vs "AD-626: Loaded augmentation skill"
- [ ] All existing chain/skill tests pass without modification
- [ ] New test file `tests/test_ad643a_intent_routing.py` with all tests above

---

## File Change Summary

| File | Action | Lines |
|------|--------|-------|
| `src/probos/cognitive/skill_catalog.py` | Edit | Add `triggers` field (~1 line), parse `probos-triggers` (~5 lines), add `find_triggered_skills()` (~30 lines) |
| `src/probos/cognitive/sub_tasks/analyze.py` | Edit | Add `intended_actions` to both prompts (~8 lines each) |
| `src/probos/cognitive/cognitive_agent.py` | Edit | Add `_extract_intended_actions()` (~20 lines), add `_execute_chain_with_intent_routing()` (~90 lines), replace decide() chain block (~25 lines) |
| `src/probos/cognitive/sub_tasks/compose.py` | Edit | Add `intended_actions` check to `_should_short_circuit()` (~5 lines) |
| `config/skills/communication-discipline/SKILL.md` | Edit | Add `probos-triggers` line |
| `config/skills/notebook-quality/SKILL.md` | Edit | Add `probos-triggers` line |
| `config/skills/leadership-feedback/SKILL.md` | Edit | Add `probos-triggers` line |
| `tests/test_ad643a_intent_routing.py` | Create | ~300-400 lines |

**Estimated net new code:** ~160 lines production + ~350 lines test
