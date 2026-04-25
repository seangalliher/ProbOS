# AD-646: Universal Cognitive Baseline — Build Prompt

**AD:** 646  
**Depends on:** AD-644, AD-645  
**Research:** `docs/research/ad-646-universal-cognitive-baseline.md`  
**Issue:** #288  
**Scope:** ~100 lines across 2 files. Zero new modules. Zero new infrastructure.

---

## Problem

Ward Room chain responses are data-starved. When a `ward_room_notification` enters the cognitive chain, the agent enters ANALYZE knowing the thread content but **nothing about itself** — no working memory, no temporal awareness, no episodic recall, no ontology, no trust metrics. The composition brief instruction tuning (AD-645) works for `proactive_think` but not for `ward_room_notification` because the **input data** is absent, not the instructions.

**Root cause:** `_build_cognitive_state()` (line 2977 of `cognitive_agent.py`) reads from `context_parts`, which is populated by `proactive.py`'s `_gather_context()`. Ward Room notifications bypass proactive.py — `context_parts` is `{}`, so most innate faculties return nothing. Additionally, `_agent_metrics` (line 1858-1864) reads `trust_score`, `agency_level`, `rank` from `_params`, which ward_room_notification doesn't provide — resulting in "Your trust: ? | Agency: ? | Rank: ?".

---

## Design

Split `_build_cognitive_state()` into two methods:

1. **`_build_cognitive_baseline(observation)`** — agent-intrinsic, runs for ALL chain executions unconditionally. Zero dependency on `context_parts`.
2. **`_build_cognitive_extensions(context_parts)`** — externally-gathered data, runs only when `context_parts` is non-empty (proactive path).

Then update `_build_thread_analysis_prompt()` in analyze.py to consume the baseline keys it currently lacks.

compose.py needs **no changes** — its shared `_build_user_prompt()` (line 225) already consumes all baseline keys via `context.get()`.

---

## Phase 1: Split `_build_cognitive_state()` in `cognitive_agent.py`

### Step 1a: Create `_build_cognitive_baseline(self, observation: dict) -> dict[str, str]`

Extract from `_build_cognitive_state()` the items that are **self-contained** (no `context_parts` dependency) and make any currently-dependent items self-contained:

| # | Key | Current Source | Baseline Source |
|---|-----|---------------|-----------------|
| 1 | `_temporal_context` | `self._build_temporal_context()` | Same — already self-contained |
| 2 | `_working_memory_context` | `self._working_memory.render_context(budget=1500)` | Same — already self-contained |
| 3 | `_agent_metrics` | `_params.get("trust_score", "?")` etc. (line 1858) | **Compute from agent attributes** — see below |
| 4 | `_ontology_context` | `context_parts.get("ontology")` (line 3106) | **Compute from `self._runtime.ontology`** — see below |
| 5 | `_source_attribution_text` | `context_parts.get("recent_memories")` (line 3086) | **Read from `observation["recent_memories"]`** — already populated by perceive() |
| 6 | `_confabulation_guard` | `self._confabulation_guard(_authority_val)` | Call with `None` authority — produces generic guard |
| 7 | `_no_episodic_memories` | `not memories` from context_parts (line 3139) | **Read from `observation["recent_memories"]`** — same as #5 |
| 8 | `_comm_proficiency` | `self._get_comm_proficiency_guidance()` | Same — already self-contained |

**For item 3 (`_agent_metrics`):** Compute trust, agency, and rank directly from agent/runtime attributes instead of reading from `_params`. Pattern:

```python
_rt = getattr(self, '_runtime', None)
_trust_val = 0.5  # default
if _rt and hasattr(_rt, 'trust_network'):
    _trust_val = _rt.trust_network.get_score(self.id)
# Use Rank.from_trust() and agency_from_rank() — same pattern as agents.py line 79-81
```

Look at `src/probos/routers/agents.py` lines 74-81 for the exact import paths and method signatures:
- `from probos.crew_profile import Rank`
- `from probos.earned_agency import agency_from_rank`
- `Rank.from_trust(trust_score).value`
- `agency_from_rank(Rank.from_trust(trust_score)).value`

Use `from probos.config import format_trust` to format the trust score display.

**For item 4 (`_ontology_context`):** Build from `self._runtime.ontology.get_crew_context(self.agent_type)`. This is the same call proactive.py uses at line 1396. The returned dict has the same structure as what `_build_cognitive_state()` currently reads at line 3107-3128. Copy the rendering logic (lines 3107-3128) into the baseline, but source from the runtime call instead of `context_parts`.

Wrap the ontology and trust lookups in `try/except Exception` with `logger.debug()` — log-and-degrade tier (these are non-critical; the chain should work with partial baseline).

**For items 5 and 7 (source attribution, no-memories):** Read `observation.get("recent_memories", [])` — perceive() populates this for all intent types. Build a simplified source attribution: count of episodes + "training knowledge only" fallback. Do NOT read `_source_framing` from context_parts — the baseline version doesn't need authority classification. For the full version with authority, the extensions method will override if context_parts is available.

### Step 1b: Create `_build_cognitive_extensions(self, context_parts: dict) -> dict[str, str]`

Move the **context_parts-dependent** items out of `_build_cognitive_state()`:

| # | Key | Source |
|---|-----|--------|
| 1 | `_self_monitoring` | `context_parts.get("self_monitoring")` — lines 3003-3083 |
| 2 | `_introspective_telemetry` | `context_parts.get("introspective_telemetry")` — lines 3100-3103 |
| 3 | `_orientation_supplement` | `context_parts.get("orientation_supplement")` — lines 3130-3133 |
| 4 | `_source_attribution_text` | OVERRIDE baseline version with full authority-aware version from `context_parts.get("_source_framing")` — lines 3085-3098 |
| 5 | `_confabulation_guard` | OVERRIDE baseline version with authority-aware version — lines 3135-3137 |

Note: items 4 and 5 **override** baseline keys with richer versions when `context_parts` has the data.

### Step 1c: Update `_build_cognitive_state()` to delegate

`_build_cognitive_state(self, context_parts)` becomes a thin wrapper calling baseline + extensions, for backward compatibility:

```python
def _build_cognitive_state(self, context_parts: dict, observation: dict | None = None) -> dict[str, str]:
    """AD-644 Phase 2 / AD-646: Populate innate faculty observation keys."""
    state = self._build_cognitive_baseline(observation or {})
    if context_parts:
        extensions = self._build_cognitive_extensions(context_parts)
        state.update(extensions)  # Extensions override baseline keys where richer
    return state
```

### Step 1d: Update the caller in `_execute_chain_with_intent_routing()`

At lines 1857-1875, change to:

1. **Remove** the `_params`-based `_agent_metrics` computation (lines 1858-1865). The baseline now computes this directly from agent attributes.
2. **Pass `observation`** to `_build_cognitive_state()` so the baseline can read `recent_memories`:

```python
# AD-646: Universal cognitive baseline — always runs
_context_parts = _params.get("context_parts", {})
_cognitive_state = self._build_cognitive_state(_context_parts, observation=observation)
observation.update(_cognitive_state)

# AD-644 Phase 3: Situation awareness — environmental perception
# Only runs when context_parts available (proactive path)
if _context_parts:
    _situation = self._build_situation_awareness(_context_parts)
    observation.update(_situation)
```

**Important:** The proactive path previously had `_agent_metrics` set before `_build_cognitive_state()` was called, then `_build_cognitive_state()` didn't touch it. Now the baseline will set `_agent_metrics`. Since `observation.update(_cognitive_state)` runs after, the baseline's computed metrics will be in the observation. This is correct — the baseline computes from actual runtime state rather than from stale `_params` values. No conflict.

**Important:** Keep `_active_duty` from `_params` — that's intent-specific (line 1854-1856), not part of baseline.

---

## Phase 2: Update `_build_thread_analysis_prompt()` in `analyze.py`

The thread analysis prompt (line 46) currently consumes only 6 observation keys. The situation review prompt (line 127) consumes 22. After Phase 1, the baseline keys will be present in the observation dict for ward_room chains. The thread analysis prompt needs to render them.

Add an **"Agent State"** section to the user prompt, between the memory section and the "Analysis Required" section. Use the same key names and section headers that `_build_situation_review_prompt()` uses (lines 238-268):

```python
# AD-646: Universal baseline keys — agent self-knowledge
agent_state_parts = []

_temporal = context.get("_temporal_context", "")
if _temporal:
    agent_state_parts.append(f"**Temporal:** {_temporal}")

_wm = context.get("_working_memory_context", "")
if _wm:
    agent_state_parts.append(f"**Working Memory:**\n{_wm}")

_metrics = context.get("_agent_metrics", "")
if _metrics:
    agent_state_parts.append(f"**Status:** {_metrics}")

_ontology = context.get("_ontology_context", "")
if _ontology:
    agent_state_parts.append(f"**Identity:** {_ontology}")

_source_attr = context.get("_source_attribution_text", "")
if _source_attr:
    agent_state_parts.append(_source_attr)

_confab = context.get("_confabulation_guard", "")
if _confab:
    agent_state_parts.append(_confab)

agent_state_section = ""
if agent_state_parts:
    agent_state_section = "## Your Current State\n\n" + "\n\n".join(agent_state_parts) + "\n\n"
```

Insert `{agent_state_section}` into the user prompt f-string between `{memory_section}` and the "## Analysis Required" heading.

**Do NOT add SA keys** (`_ward_room_activity`, `_recent_alerts`, `_recent_events`, `_infrastructure_status`, `_subordinate_stats`, `_cold_start_note`, `_active_game`) to the thread analysis prompt. Those are environmental perception — intent-specific to the proactive path. The thread analysis gets its environmental data from the thread content itself.

---

## What NOT To Change

- **compose.py** — `_build_user_prompt()` already consumes all baseline keys via `context.get()`. No changes needed. The keys will now be populated for ward_room chains because the baseline runs unconditionally.
- **`_build_situation_review_prompt()` in analyze.py** — the proactive analysis prompt already reads all baseline + SA keys. No changes.
- **`_build_situation_awareness()`** — remains intent-specific (proactive only until NATS). No changes to this method.
- **Chain definitions** — `_build_chain_for_intent()` unchanged. The QUERY operations remain intent-specific.
- **`SubTaskSpec`** — no changes.
- **`proactive.py`** — no changes. It continues to gather `context_parts` as before.
- **`ward_room_router.py`** — no changes. The params it sends are unchanged.

---

## Engineering Principles Compliance

| Principle | How This Change Complies |
|-----------|------------------------|
| **Single Responsibility** | `_build_cognitive_baseline()` = agent self-knowledge. `_build_cognitive_extensions()` = externally-gathered data. Clean separation. |
| **Open/Closed** | New intent types get baseline automatically. Only need intent-specific extensions if they have unique data. |
| **Dependency Inversion** | Baseline reads from agent attributes and runtime interfaces, not from a specific caller's data format (`context_parts`). |
| **DRY** | Ontology rendering code consolidated — baseline builds it once from `self._runtime.ontology`, not duplicated per intent path. Source attribution simplified in baseline, enriched in extensions. |
| **Fail Fast (log-and-degrade)** | Runtime lookups (trust, ontology) wrapped in try/except with `logger.debug()`. Baseline degrades gracefully — chain still works with partial state. |
| **Law of Demeter** | Baseline accesses `self._runtime.trust_network.get_score()` and `self._runtime.ontology.get_crew_context()` — these are public APIs on direct dependencies, not reaching through internals. |
| **Backward Compatibility** | `_build_cognitive_state()` becomes a thin wrapper. Existing callers unchanged. Extensions override baseline keys where richer data is available. |

---

## Tests

Create `tests/test_ad646_cognitive_baseline.py`.

### Test 1: Baseline produces all expected keys with no context_parts

```
Given: A CognitiveAgent with working memory, temporal context enabled, and a runtime with trust_network and ontology
When: _build_cognitive_baseline(observation={"recent_memories": [fake_episode]}) is called
Then: Returns dict with keys: _temporal_context, _working_memory_context, _agent_metrics, _ontology_context, _source_attribution_text, _confabulation_guard, _comm_proficiency
And: _agent_metrics contains actual trust/agency/rank values (not "?")
And: _source_attribution_text mentions "1 episodes"
```

### Test 2: Baseline works with empty observation (no memories)

```
Given: A CognitiveAgent with minimal setup
When: _build_cognitive_baseline(observation={}) is called
Then: Returns dict with _no_episodic_memories set
And: _source_attribution_text mentions "training knowledge only"
And: _agent_metrics has values (possibly defaults, not "?")
```

### Test 3: Baseline degrades when runtime unavailable

```
Given: A CognitiveAgent with no _runtime attribute
When: _build_cognitive_baseline(observation={}) is called
Then: Returns dict with _temporal_context and _working_memory_context populated
And: Does NOT raise any exception
And: _agent_metrics shows default values
```

### Test 4: Extensions override baseline keys

```
Given: Baseline state with generic _confabulation_guard and _source_attribution_text
When: _build_cognitive_extensions(context_parts_with_source_framing_and_memories) is called
Then: Returns dict with _confabulation_guard and _source_attribution_text that differ from baseline
And: _self_monitoring is populated
And: _introspective_telemetry is populated
```

### Test 5: `_build_cognitive_state()` wrapper combines baseline + extensions

```
Given: A CognitiveAgent with full context_parts (proactive path)
When: _build_cognitive_state(context_parts, observation=obs) is called
Then: Returns dict with both baseline keys AND extension keys
And: Extension keys override baseline where both set the same key
```

### Test 6: `_build_cognitive_state()` with empty context_parts (ward_room path)

```
Given: A CognitiveAgent with empty context_parts
When: _build_cognitive_state({}, observation=obs_with_memories) is called
Then: Returns dict with baseline keys populated
And: Extension-only keys (_self_monitoring, _introspective_telemetry) are absent
And: _agent_metrics has real values (not "?")
```

### Test 7: Thread analysis prompt includes baseline state

```
Given: An observation dict with baseline keys populated (_temporal_context, _working_memory_context, _agent_metrics, _ontology_context)
When: _build_thread_analysis_prompt(context, prior_results, callsign, department) is called
Then: Returned user_prompt contains "Your Current State" section
And: Contains temporal context, working memory, agent metrics, ontology
```

### Test 8: Thread analysis prompt works without baseline keys (backward compat)

```
Given: An observation dict with NO baseline keys
When: _build_thread_analysis_prompt(context, prior_results, callsign, department) is called
Then: Returned user_prompt does NOT contain "Your Current State" section
And: Does NOT raise any exception
```

### Test 9: Proactive path regression — full context still works

```
Given: A CognitiveAgent with full context_parts from proactive.py
When: _build_cognitive_state(full_context_parts, observation=obs) is called
Then: Returns dict with ALL keys (baseline + extensions)
And: _self_monitoring is populated from context_parts
And: _ontology_context is populated (extensions override baseline)
And: _introspective_telemetry is populated
```

### Test 10: _agent_metrics computed from runtime, not params

```
Given: A CognitiveAgent with runtime.trust_network returning score 0.75
When: _build_cognitive_baseline(observation={}) is called
Then: _agent_metrics contains "0.75" (not "?")
And: _agent_metrics contains actual rank and agency values
```

---

## Verification Checklist

After implementation:

- [ ] Ward Room chain ANALYZE step receives temporal awareness, working memory, agent metrics, ontology
- [ ] Ward Room chain COMPOSE step receives all baseline keys (no code change needed — just verify keys flow through)
- [ ] Proactive chain still works identically — all keys populated from baseline + extensions
- [ ] `_agent_metrics` shows real trust/rank/agency values for both intents
- [ ] No new async calls in the baseline path — all reads are in-memory
- [ ] All 10 tests pass
- [ ] `pytest tests/test_ad646_cognitive_baseline.py -v` green
- [ ] `pytest tests/ -x -q` — no regressions in existing tests
