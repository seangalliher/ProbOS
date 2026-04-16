# AD-632f: Sub-Task Chain Activation Triggers

**Issue:** TBD (will be created)
**Depends on:** AD-632a (COMPLETE), AD-632b (COMPLETE), AD-632c (COMPLETE), AD-632d (COMPLETE)
**Absorbs:** The `_pending_sub_task_chain` external-set pattern (replaces with inline activation)
**Principles:** Single Responsibility, Open/Closed, Fail Fast, Law of Demeter

## Problem

The MVP sub-task chain (Query → Analyze → Compose) is code-complete: three
handlers registered, executor wired onto all crew agents. But nothing ever
fires because:

1. `SubTaskConfig.enabled` is `False` (config.py:258)
2. `_pending_sub_task_chain` is always `None` — nothing builds or sets a chain
3. `decide()` checks the chain at line 1163, finds `None`, falls through to
   single-call `_decide_via_llm()` every time

This AD solves all three: flips the config, builds chains inline in `decide()`,
and defines the trigger heuristics that decide when to use multi-step chains
vs single-call reasoning.

## Design

### Activation Location

**Build chains inside `decide()`**, not via external `_pending_sub_task_chain`
setting. This is cleaner because:

- `decide()` already has the observation context needed to evaluate triggers
- No external coordination required (proactive loop, WR router, etc.)
- Single Responsibility: `decide()` owns the decision about *how* to reason
- The existing `_pending_sub_task_chain` mechanism stays as an escape hatch
  for future external chain injection (e.g. from skills, or AD-632g JIT)

Replace the current block at lines 1162-1173:

```python
# --- AD-632a: Sub-task chain check (Level 3, before single-call Level 2) ---
if self._pending_sub_task_chain is not None:
    chain = self._pending_sub_task_chain
    self._pending_sub_task_chain = None  # consume once
    ...
```

With an expanded block:

```python
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
    chain_result = await self._execute_sub_task_chain(chain, observation)
    if chain_result is not None:
        _cache_ttl = self._get_cache_ttl()
        cache[cache_key] = (chain_result, time.monotonic(), _cache_ttl)
        return chain_result
    logger.info("AD-632f: Falling back to single-call for %s", self.agent_type)
```

### Trigger Evaluation: `_should_activate_chain()`

New method on `CognitiveAgent`. Returns `True` when the observation warrants
multi-step reasoning. Checks are evaluated in order; first match wins.

```python
def _should_activate_chain(self, observation: dict) -> bool:
```

**Gate 0: Global enable check.**
If `SubTaskConfig.enabled` is `False`, return `False` immediately. Access
config via `self._sub_task_executor` — if executor is `None` or its config
has `enabled=False`, short-circuit. Do NOT import config directly (Law of
Demeter). The executor already holds the config reference from registration
in finalize.py.

Add a property or method on `SubTaskExecutor` to expose the enabled flag:

```python
@property
def enabled(self) -> bool:
    return self._config.enabled
```

(sub_task.py, add to SubTaskExecutor class)

**Gate 1: Intent type filter.**
Only activate for conversational intents where multi-step reasoning adds value:
- `ward_room_notification` — thread response (Query context + Analyze thread + Compose reply)
- `proactive_think` — observation cycle (Query activity + Analyze situation + Compose observation)

Do NOT activate for:
- `direct_message` — DM conversations are simple request/response, single-call is sufficient
- Any other intent — skill intents, compound replay, etc. are handled elsewhere

This is a conservative starting point. DM support can be added later by
adding `"direct_message"` to the set.

```python
_CHAIN_ELIGIBLE_INTENTS = {"ward_room_notification", "proactive_think"}
```

Module-level frozenset on cognitive_agent.py.

**Gate 2: Executor readiness.**
`self._sub_task_executor is not None` and `self._sub_task_executor.enabled`.

That's it for Phase 1 triggers. The research doc mentions three trigger
mechanisms (skill annotation, complexity heuristic, quality fallback) — but
starting with intent-type-only is the minimum viable trigger. Complexity
heuristics (thread post count, contributor count) and skill annotation
(`probos-subtask-mode`) are deferred to follow-up ADs.

### Chain Construction: `_build_chain_for_intent()`

New method on `CognitiveAgent`. Builds the appropriate `SubTaskChain` based
on intent type.

```python
def _build_chain_for_intent(self, observation: dict) -> SubTaskChain | None:
```

**Ward Room notification chain:**

```python
SubTaskChain(
    steps=[
        SubTaskSpec(
            sub_task_type=SubTaskType.QUERY,
            name="query-thread-context",
            context_keys=("thread_metadata", "credibility"),
        ),
        SubTaskSpec(
            sub_task_type=SubTaskType.ANALYZE,
            name="analyze-thread",
            prompt_template="thread_analysis",
        ),
        SubTaskSpec(
            sub_task_type=SubTaskType.COMPOSE,
            name="compose-reply",
            prompt_template="ward_room_response",
        ),
    ],
    source="intent_trigger:ward_room_notification",
)
```

- QUERY step retrieves thread metadata and agent credibility for factual
  grounding
- ANALYZE step performs thread comprehension (topics, gaps, contribution
  assessment)
- COMPOSE step generates the actual Ward Room reply with full personality
  and skill injection

**Proactive think chain:**

```python
SubTaskChain(
    steps=[
        SubTaskSpec(
            sub_task_type=SubTaskType.QUERY,
            name="query-situation",
            context_keys=("unread_counts", "trust_score"),
        ),
        SubTaskSpec(
            sub_task_type=SubTaskType.ANALYZE,
            name="analyze-situation",
            prompt_template="situation_review",
        ),
        SubTaskSpec(
            sub_task_type=SubTaskType.COMPOSE,
            name="compose-observation",
            prompt_template="proactive_observation",
        ),
    ],
    source="intent_trigger:proactive_think",
)
```

- QUERY step retrieves unread counts and trust score for situational awareness
- ANALYZE step performs situation review (active threads, priority topics)
- COMPOSE step generates proactive observation with full action vocabulary

**Context key selection:** The QUERY step `context_keys` determine what data
is fetched. Use lightweight keys for Phase 1 — `thread_metadata` and
`credibility` for WR, `unread_counts` and `trust_score` for proactive. These
are fast queries (in-memory cache or simple SQL). Heavier queries like
`thread_activity` or `comm_stats` can be added in follow-ups.

**Unknown intent → return `None`** (triggers single-call fallback).

### Skill Injection Wiring

Augmentation skills are loaded in `_decide_via_llm()` at line 1205-1207.
When the chain path is taken instead, skills must still be loaded and
injected into the observation for the Compose handler to use.

Add skill loading **before** the chain activation check in `decide()`:

```python
# AD-632f: Load augmentation skills before chain check (Compose handler needs them)
if observation.get("intent") in _CHAIN_ELIGIBLE_INTENTS:
    _aug = self._load_augmentation_skills(observation.get("intent", ""))
    if _aug:
        observation["_augmentation_skill_instructions"] = _aug
```

This ensures `_augmentation_skill_instructions` is in the observation dict
when `_execute_sub_task_chain()` passes it to the Compose handler.

Note: `_load_augmentation_skills()` also sets `self._augmentation_skills_used`
(line 2026), which `_execute_sub_task_chain` already passes through via the
observation dict enrichment at line 1446-1454.

### Config Flip

Change `SubTaskConfig.enabled` default from `False` to `True`:

```python
class SubTaskConfig(BaseModel):
    enabled: bool = True  # AD-632f: MVP chain complete, enabled by default
```

Also add `sub_task` section to `config/system.yaml` so users can disable:

```yaml
sub_task:
  enabled: true
  chain_timeout_ms: 30000
  step_timeout_ms: 15000
```

### SubTaskExecutor.enabled Property

Add to `SubTaskExecutor` class in `sub_task.py`:

```python
@property
def enabled(self) -> bool:
    """Whether sub-task chains are globally enabled."""
    return self._config.enabled if self._config else False
```

Check that `SubTaskExecutor.__init__` stores config. If it receives config
as a parameter (grep for `def __init__` on SubTaskExecutor), use the existing
attribute. If not, add `config` parameter.

### Logging

Log chain activation decisions at INFO level:

```
AD-632f: Chain activated for {agent_type} (intent={intent}, source={chain.source})
AD-632f: Chain skipped for {agent_type} (intent={intent} not eligible)
AD-632f: Falling back to single-call for {agent_type}
```

## Files

| File | Action | Purpose |
|------|--------|---------|
| `src/probos/cognitive/cognitive_agent.py` | EDIT | `_should_activate_chain()`, `_build_chain_for_intent()`, `decide()` chain block, skill preload |
| `src/probos/cognitive/sub_task.py` | EDIT | `SubTaskExecutor.enabled` property |
| `src/probos/config.py` | EDIT | `SubTaskConfig.enabled = True` |
| `config/system.yaml` | EDIT | Add `sub_task:` section |
| `tests/test_ad632f_activation_triggers.py` | CREATE | Unit tests |

## Tests

### Test File: `tests/test_ad632f_activation_triggers.py`

Target: 25-35 tests covering:

**`_should_activate_chain()` gate logic:**
- `test_gate_disabled_config` — `enabled=False` → returns `False`
- `test_gate_no_executor` — `_sub_task_executor is None` → returns `False`
- `test_gate_ward_room_eligible` — intent=`ward_room_notification` → `True`
- `test_gate_proactive_eligible` — intent=`proactive_think` → `True`
- `test_gate_dm_not_eligible` — intent=`direct_message` → `False`
- `test_gate_unknown_intent` — intent=`scout_search` → `False`

**`_build_chain_for_intent()` chain construction:**
- `test_ward_room_chain_structure` — 3 steps: QUERY→ANALYZE→COMPOSE
- `test_ward_room_chain_query_keys` — QUERY has `thread_metadata`, `credibility`
- `test_ward_room_chain_analyze_mode` — ANALYZE has `prompt_template="thread_analysis"`
- `test_ward_room_chain_compose_mode` — COMPOSE has `prompt_template="ward_room_response"`
- `test_ward_room_chain_source` — source contains `ward_room_notification`
- `test_proactive_chain_structure` — 3 steps: QUERY→ANALYZE→COMPOSE
- `test_proactive_chain_query_keys` — QUERY has `unread_counts`, `trust_score`
- `test_proactive_chain_analyze_mode` — ANALYZE has `prompt_template="situation_review"`
- `test_proactive_chain_compose_mode` — COMPOSE has `prompt_template="proactive_observation"`
- `test_unknown_intent_returns_none` — `direct_message` → `None`

**Integration with `decide()`:**
- `test_decide_activates_chain_for_ward_room` — with enabled config + mock executor, chain path taken
- `test_decide_falls_through_on_chain_failure` — chain returns `None` → single-call fallback
- `test_decide_prefers_external_chain` — `_pending_sub_task_chain` takes priority over inline trigger
- `test_decide_single_call_when_disabled` — `enabled=False` → `_decide_via_llm()` path
- `test_decide_single_call_for_dm` — DM intent → no chain activation

**Skill injection:**
- `test_skills_loaded_before_chain` — `_augmentation_skill_instructions` in observation when chain activates
- `test_no_skill_loading_for_ineligible_intent` — DM intent → no skill preload for chain path

**SubTaskExecutor.enabled:**
- `test_executor_enabled_default` — `enabled=True` with default config
- `test_executor_enabled_false` — `enabled=False` when config says False
- `test_executor_enabled_no_config` — returns `False` when no config

**Config:**
- `test_subtask_config_default_enabled` — `SubTaskConfig().enabled` is `True`
- `test_subtask_config_yaml_override` — `enabled: false` in YAML disables

### Test Patterns

- Mock `_sub_task_executor` with a `MagicMock(enabled=True)` and mock
  `can_execute()` returning `True`
- Mock `_execute_sub_task_chain` to return a decision dict
  `{"action": "execute", "llm_output": "test", "tier_used": "standard", "sub_task_chain": True}`
- Mock `_decide_via_llm` to verify fallback path
- Mock `_load_augmentation_skills` to verify call/no-call
- Use real `SubTaskChain`, `SubTaskSpec`, `SubTaskType` (not mocks)
- `pytest.mark.asyncio` for async tests

## Verification

```bash
cd d:\ProbOS
python -m pytest tests/test_ad632f_activation_triggers.py -v
python -m pytest tests/test_ad632a_sub_task_foundation.py tests/test_ad632b_query_handler.py tests/test_ad632c_analyze_handler.py tests/test_ad632d_compose_handler.py -v
```

All tests must pass. No existing tests should break.

## What This Does NOT Do

- Does NOT add complexity heuristics (thread length, contributor count) — Phase 2
- Does NOT add skill annotation triggers (`probos-subtask-mode`) — Phase 2
- Does NOT add quality fallback (self-verification failure → retry with chain) — Phase 2
- Does NOT add DM chain support — can be enabled by adding to `_CHAIN_ELIGIBLE_INTENTS`
- Does NOT add Evaluate/Reflect handlers (AD-632e) — separate handler ADs
- Does NOT modify proactive.py or ward_room_router.py — all changes are in cognitive_agent.py
