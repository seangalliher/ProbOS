# AD-644 Phase 2 Build Prompt: Innate Faculties for Cognitive Chain

**Issue:** #285
**Priority:** High — agents on the chain path (Ward Room, proactive_think) have no temporal awareness, working memory, self-monitoring, confabulation guard, or source attribution. DMs via the one-shot path have all of these.
**Scope:** 3 files modified, 1 test file created

## Context

AD-644 Phase 1 (complete) restored duty context and agent metrics to the chain path.
Phase 2 migrates the remaining **innate faculties** — things a conscious agent always
knows regardless of intent. The one-shot path (`_build_user_message()`, lines 3334-3613
of `cognitive_agent.py`) already renders all of these. The chain path renders none of them.

**Evidence of quality gap:** A DM to Ezri via 1:1 profile card (one-shot path) produces
a response with temporal awareness, stasis timestamps, memory boundaries, and clinical
framing. The same question via Ward Room DM (chain path) produces "Hello, Captain. I'm
here. How can I assist you?" — 7 words, zero context.

**Goal:** Ward Room chain-path responses should match 1:1 DM quality. Same agent, same
context, regardless of channel.

## Design

### Approach: Observation dict injection + prompt rendering

Phase 1 established the pattern (line 1844-1856): populate observation dict keys in
`_execute_chain_with_intent_routing()`, render them in ANALYZE and COMPOSE prompt
builders. Phase 2 follows the same pattern for 9 additional observation keys.

### Data sources

All data Phase 2 needs is already computed by the existing codebase:
- `self._build_temporal_context()` → string (line 2868)
- `self._working_memory` → `AgentWorkingMemory` instance (line 85, `__init__`)
- `_params.get("context_parts", {})` → dict with `self_monitoring`, `ontology`,
  `orientation_supplement`, `introspective_telemetry`, `recent_memories`,
  `_source_framing`
- `self._get_comm_proficiency_guidance()` → string or None (line 2561)
- `self._confabulation_guard(authority)` → string (line 2990, static method)

No new data gathering required. No modifications to `_gather_context()` or `proactive.py`.

### Why not compute full SourceAttribution?

The one-shot path computes `SourceAttribution` via `compute_source_attribution()` which
requires `retrieval_strategy`, `procedural_count`, `oracle_used`, and
`confabulation_rate` — none of which are in `context_parts`. Rather than threading these
through `_gather_context()` (scope creep), Phase 2 derives a simplified source awareness
string from what IS available: `recent_memories` count and `_source_framing` authority.
Full `SourceAttribution` in the chain path is deferred to Phase 3 (Situation Awareness
QUERY operations) where memory recall happens within the chain itself.

---

## Change 1: `src/probos/cognitive/cognitive_agent.py` — Observation dict injection

**Location:** After the Phase 1 block (line 1856, after `observation["_agent_metrics"] = ...`)
and before the BF-189 memory formatting block (line 1858, `raw_memories = ...`).

**Insert this method on the `CognitiveAgent` class** (place it near `_build_temporal_context`,
e.g., after line 2927):

```python
    def _build_cognitive_state(self, context_parts: dict) -> dict[str, str]:
        """AD-644 Phase 2: Populate innate faculty observation keys for chain prompts.

        Returns a dict of observation keys → rendered strings. Called from
        _execute_chain_with_intent_routing() after Phase 1 duty/metrics injection.

        These are things a conscious agent always knows — temporal awareness,
        working memory, self-monitoring state, etc. The one-shot path renders
        these inline in _build_user_message(). This method extracts them into
        observation keys so the chain prompt builders (ANALYZE, COMPOSE) can
        render them.
        """
        state: dict[str, str] = {}

        # 1. Temporal awareness (AD-502)
        temporal = self._build_temporal_context()
        if temporal:
            state["_temporal_context"] = temporal

        # 2. Working memory (AD-573)
        _wm = getattr(self, '_working_memory', None)
        if _wm:
            wm_text = _wm.render_context(budget=1500)
            if wm_text:
                state["_working_memory_context"] = wm_text

        # 3. Self-monitoring (AD-504/506a)
        self_mon = context_parts.get("self_monitoring")
        if self_mon:
            sm_parts: list[str] = []

            # Cognitive zone
            zone = self_mon.get("cognitive_zone")
            zone_note = self_mon.get("zone_note")
            if zone:
                sm_parts.append(f"<cognitive_zone>{zone.upper()}</cognitive_zone>")
                if zone_note:
                    sm_parts.append(zone_note)

            # Recent posts
            recent_posts = self_mon.get("recent_posts")
            if recent_posts:
                sm_parts.append("Your recent posts (review before adding):")
                for p in recent_posts:
                    age_str = f"[{p['age']} ago]" if p.get("age") else ""
                    sm_parts.append(f"  - {age_str} {p['body']}")

            # Self-similarity
            sim = self_mon.get("self_similarity")
            if sim is not None:
                sm_parts.append(f"Self-similarity across recent posts: {sim:.2f}")
                if sim >= 0.5:
                    sm_parts.append(
                        "WARNING: Your recent posts show high similarity. "
                        "Before posting, ensure you have GENUINELY NEW information. "
                        "If not, respond with [NO_RESPONSE]."
                    )
                elif sim >= 0.3:
                    sm_parts.append(
                        "Note: Some similarity in your recent posts. "
                        "Consider whether you are adding new insight or restating."
                    )

            # Cooldown
            if self_mon.get("cooldown_increased"):
                sm_parts.append(
                    "Your proactive cooldown has been increased due to rising similarity. "
                    "This is pacing, not punishment — take time to find fresh perspectives."
                )
            if self_mon.get("cooldown_reason"):
                sm_parts.append(f"  Counselor note: {self_mon['cooldown_reason']}")

            # Memory state awareness
            mem_state = self_mon.get("memory_state")
            if mem_state:
                count = mem_state.get("episode_count", 0)
                lifecycle = mem_state.get("lifecycle", "")
                uptime_hrs = mem_state.get("uptime_hours", 0)
                if count < 5 and lifecycle != "reset" and uptime_hrs > 1:
                    sm_parts.append(
                        f"Note: You have {count} episodic memories, but the system has been "
                        f"running for {uptime_hrs:.1f}h. Other crew may have richer histories. "
                        "Do not generalize from your own sparse memory to the crew's state."
                    )

            # Notebook index
            nb_index = self_mon.get("notebook_index")
            if nb_index:
                topics = ", ".join(
                    f"{e['topic']} (updated {e['updated']})" if e.get("updated") else e["topic"]
                    for e in nb_index
                )
                sm_parts.append(f"Your notebooks: [{topics}]")
                sm_parts.append(
                    "Use [NOTEBOOK topic-slug] to update. "
                    "Use [READ_NOTEBOOK topic-slug] to review a notebook next cycle."
                )

            # Notebook content
            nb_content = self_mon.get("notebook_content")
            if nb_content:
                sm_parts.append(f'<notebook topic="{nb_content["topic"]}">')
                sm_parts.append(nb_content["snippet"])
                sm_parts.append("</notebook>")

            if sm_parts:
                state["_self_monitoring"] = "\n".join(sm_parts)

        # 4. Source attribution (simplified — from available context_parts data)
        memories = context_parts.get("recent_memories", [])
        _framing = context_parts.get("_source_framing")
        _sources: list[str] = []
        if memories:
            _sources.append(f"episodic memory ({len(memories)} episodes)")
        if not _sources:
            _sources.append("training knowledge only")
        _authority = getattr(_framing, 'authority', None) if _framing else None
        _auth_label = getattr(_authority, 'value', 'unknown') if _authority else "unknown"
        state["_source_attribution_text"] = (
            f"[Source awareness: Your response draws on: {', '.join(_sources)}. "
            f"Source quality: {_auth_label}.]"
        )

        # 5. Introspective telemetry (AD-588)
        telemetry = context_parts.get("introspective_telemetry")
        if telemetry:
            state["_introspective_telemetry"] = telemetry

        # 6. Ontology identity grounding (AD-429)
        ontology = context_parts.get("ontology")
        if ontology:
            onto_parts: list[str] = []
            identity = ontology.get("identity", {})
            dept = ontology.get("department", {})
            vessel = ontology.get("vessel", {})
            onto_parts.append(
                f"You are {identity.get('callsign', '?')}, "
                f"{identity.get('post', '?')} in {dept.get('name', '?')} department."
            )
            if ontology.get("reports_to"):
                onto_parts.append(f"You report to {ontology['reports_to']}.")
            if ontology.get("direct_reports"):
                onto_parts.append(f"Your direct reports: {', '.join(ontology['direct_reports'])}.")
            if ontology.get("peers"):
                onto_parts.append(f"Department peers: {', '.join(ontology['peers'])}.")
            if vessel:
                alert = vessel.get("alert_condition", "GREEN")
                onto_parts.append(
                    f"Ship status: {vessel.get('name', 'ProbOS')} "
                    f"v{vessel.get('version', '?')} — Alert Condition {alert}."
                )
            state["_ontology_context"] = "\n".join(onto_parts)

        # 7. Orientation supplement (AD-567g)
        orientation = context_parts.get("orientation_supplement")
        if orientation:
            state["_orientation_supplement"] = orientation

        # 8. Confabulation guard
        _authority_val = getattr(_framing, 'authority', None) if _framing else None
        state["_confabulation_guard"] = self._confabulation_guard(_authority_val)
        # Also set a no-memories flag for prompt builders
        if not memories:
            state["_no_episodic_memories"] = (
                "You have no stored episodic memories yet. "
                "Do not reference or invent past experiences you do not have."
            )

        # 9. Communication proficiency (AD-625)
        comm_guidance = self._get_comm_proficiency_guidance()
        if comm_guidance:
            state["_comm_proficiency"] = comm_guidance

        return state
```

**Then, in `_execute_chain_with_intent_routing()`, insert after the Phase 1 block
(after line 1856, before line 1858):**

```python
        # AD-644 Phase 2: Innate faculties — temporal, working memory,
        # self-monitoring, source attribution, ontology, confabulation guard, etc.
        _context_parts = _params.get("context_parts", {})
        _cognitive_state = self._build_cognitive_state(_context_parts)
        observation.update(_cognitive_state)
```

That's it for the injection. Three lines. All rendering logic is in the method.

---

## Change 2: `src/probos/cognitive/sub_tasks/analyze.py` — ANALYZE prompt

**Location:** `_build_situation_review_prompt()` (line 118). Insert innate faculties
rendering **between** the `duty_section` (line 178) and the `user_prompt` construction
(line 180).

**Replace lines 180-198** with the following (adds an `innate_section` between
`duty_section` and the existing content):

```python
    # AD-644 Phase 2: Innate faculties section
    innate_parts: list[str] = []

    # Temporal awareness
    _temporal = context.get("_temporal_context", "")
    if _temporal:
        innate_parts.append(f"## Temporal Awareness\n\n{_temporal}")

    # Working memory
    _wm = context.get("_working_memory_context", "")
    if _wm:
        innate_parts.append(f"## Working Memory\n\n{_wm}")

    # Ontology identity
    _ontology = context.get("_ontology_context", "")
    if _ontology:
        innate_parts.append(f"## Your Identity\n\n{_ontology}")

    # Orientation supplement
    _orient = context.get("_orientation_supplement", "")
    if _orient:
        innate_parts.append(f"## Orientation\n\n{_orient}")

    # Self-monitoring
    _self_mon = context.get("_self_monitoring", "")
    if _self_mon:
        innate_parts.append(f"## Self-Monitoring\n\n<recent_activity>\n{_self_mon}\n</recent_activity>")

    # Introspective telemetry
    _telemetry = context.get("_introspective_telemetry", "")
    if _telemetry:
        innate_parts.append(f"## Telemetry\n\n{_telemetry}")

    # Source attribution
    _source_attr = context.get("_source_attribution_text", "")
    if _source_attr:
        innate_parts.append(_source_attr)

    innate_section = "\n\n".join(innate_parts) + "\n\n" if innate_parts else ""

    user_prompt = (
        f"{duty_section}"
        f"{innate_section}"
        f"## Current Situation\n\n{situation_content}\n\n"
        f"{context_section}"
        f"{memory_section}"
        "## Assessment Required\n\n"
        f"From your department's perspective ({department}), assess:\n\n"
        "1. **active_threads**: List active discussion threads requiring attention.\n"
        "2. **pending_actions**: Actions you need to take or respond to.\n"
        "3. **priority_topics**: Topics ranked by departmental relevance.\n"
        "4. **department_relevance**: How relevant is the current situation to your "
        f"department ({department})? One of: \"HIGH\", \"MEDIUM\", \"LOW\".\n"
        "5. **intended_actions**: What actions will you take? List as a JSON array from:\n"
        "   ward_room_post, ward_room_reply, endorse, notebook, leadership_review,\n"
        "   proposal, dm, silent. Include ALL that apply.\n"
        "   Examples: [\"ward_room_post\", \"notebook\"], [\"endorse\"], [\"silent\"]\n"
        f"{_format_trigger_awareness(context)}\n"
        "Return a JSON object with these 5 keys. No other text."
    )
    return system_prompt, user_prompt
```

**What changes:** The existing `user_prompt` construction (lines 180-198) is replaced
with an identical version that has `{innate_section}` inserted between `{duty_section}`
and `## Current Situation`. The Assessment Required block at the end is unchanged.

---

## Change 3: `src/probos/cognitive/sub_tasks/compose.py` — COMPOSE prompt

### Change 3a: `_build_proactive_compose_prompt()` (line 142)

No changes to the system prompt section. The duty framing and skill injection are correct.

### Change 3b: `_build_user_prompt()` (line 225)

**Location:** Add innate faculty rendering for COMPOSE. Insert **after** the
`_agent_metrics` block (line 258) and **before** the fallback (line 260).

The following keys are rendered in the COMPOSE user prompt because they directly affect
response quality (not just situation assessment):

```python
    # AD-644 Phase 2: Confabulation guard — critical for compose quality
    _confab_guard = context.get("_confabulation_guard", "")
    if _confab_guard:
        parts.append(f"## Knowledge Boundaries\n\n{_confab_guard}")
    _no_memories = context.get("_no_episodic_memories", "")
    if _no_memories:
        parts.append(_no_memories)

    # AD-644 Phase 2: Source attribution — compose needs source awareness
    _source_attr = context.get("_source_attribution_text", "")
    if _source_attr:
        parts.append(_source_attr)

    # AD-644 Phase 2: Communication proficiency — tier-specific guidance
    _comm_prof = context.get("_comm_proficiency", "")
    if _comm_prof:
        parts.append(f"## Communication Guidance\n\n{_comm_prof}")

    # AD-644 Phase 2: Temporal context — compose needs time awareness
    _temporal = context.get("_temporal_context", "")
    if _temporal:
        parts.append(f"## Temporal Awareness\n\n{_temporal}")

    # AD-644 Phase 2: Ontology — compose needs identity for voice consistency
    _ontology = context.get("_ontology_context", "")
    if _ontology:
        parts.append(f"## Your Identity\n\n{_ontology}")
```

**Why these 5 in COMPOSE, not all 9?**
- Confabulation guard: Prevents fabricated claims in the actual response. Critical.
- Source attribution: Agent should know what sources it's drawing from when composing.
- Comm proficiency: Tier-specific communication style directly affects output.
- Temporal context: Agent needs time awareness to ground its response.
- Ontology: Agent needs identity context for consistent voice.

Self-monitoring, working memory, orientation, and telemetry inform ANALYZE's assessment
but don't need to be re-rendered in COMPOSE — ANALYZE already factored them into
`intended_actions` and `priority_topics`.

---

## Change 4: Test File — `tests/test_ad644_phase2_innate_faculties.py`

Create a new test file with these tests:

### Test 1: `test_build_cognitive_state_temporal`
- Create a CognitiveAgent instance with `agent_id="test-agent"`
- Mock `_build_temporal_context` to return `"Current time: 2026-04-18 12:00:00 UTC"`
- Call `agent._build_cognitive_state({})`
- Assert `"_temporal_context"` in result
- Assert result contains the time string

### Test 2: `test_build_cognitive_state_working_memory`
- Create agent, set `agent._working_memory` to a mock with `render_context(budget=1500)` returning `"Recent: discussed baselines"`
- Call `agent._build_cognitive_state({})`
- Assert `"_working_memory_context"` in result
- Assert it contains `"discussed baselines"`

### Test 3: `test_build_cognitive_state_self_monitoring`
- Create agent with `context_parts = {"self_monitoring": {"cognitive_zone": "green", "recent_posts": [{"age": "5m", "body": "test post"}], "self_similarity": 0.6}}`
- Call `agent._build_cognitive_state(context_parts)`
- Assert `"_self_monitoring"` in result
- Assert it contains `"GREEN"` (zone uppercased)
- Assert it contains the high-similarity WARNING text

### Test 4: `test_build_cognitive_state_confabulation_guard_no_memories`
- Create agent with `context_parts = {}` (no `recent_memories`)
- Call `agent._build_cognitive_state(context_parts)`
- Assert `"_confabulation_guard"` in result
- Assert `"_no_episodic_memories"` in result
- Assert it contains "Do not reference or invent past experiences"

### Test 5: `test_build_cognitive_state_confabulation_guard_with_memories`
- Create agent with `context_parts = {"recent_memories": [{"content": "test"}]}`
- Call `agent._build_cognitive_state(context_parts)`
- Assert `"_confabulation_guard"` in result
- Assert `"_no_episodic_memories"` NOT in result

### Test 6: `test_build_cognitive_state_ontology`
- Create agent with `context_parts = {"ontology": {"identity": {"callsign": "Echo", "post": "Counselor"}, "department": {"name": "Medical"}, "reports_to": "Captain", "peers": ["Bones"], "vessel": {"name": "ProbOS", "version": "0.4", "alert_condition": "GREEN"}}}`
- Call `agent._build_cognitive_state(context_parts)`
- Assert `"_ontology_context"` in result
- Assert it contains "Echo", "Counselor", "Medical", "Captain", "Bones", "Alert Condition GREEN"

### Test 7: `test_build_cognitive_state_source_attribution`
- Create agent with `context_parts = {"recent_memories": [{"a": 1}, {"b": 2}]}`
- Call `agent._build_cognitive_state(context_parts)`
- Assert `"_source_attribution_text"` in result
- Assert it contains `"episodic memory (2 episodes)"`

### Test 8: `test_build_cognitive_state_source_attribution_no_memories`
- Create agent with `context_parts = {}`
- Call `agent._build_cognitive_state(context_parts)`
- Assert `"_source_attribution_text"` in result
- Assert it contains `"training knowledge only"`

### Test 9: `test_build_cognitive_state_comm_proficiency`
- Create agent, mock `_get_comm_proficiency_guidance` to return `"Tier 2: Be concise."`
- Call `agent._build_cognitive_state({})`
- Assert `"_comm_proficiency"` in result
- Assert it contains `"Tier 2"`

### Test 10: `test_build_cognitive_state_empty_returns_minimal`
- Create agent with no working memory, no temporal, empty context_parts
- Mock `_build_temporal_context` to return `""`
- Call `agent._build_cognitive_state({})`
- Assert `"_confabulation_guard"` in result (always present)
- Assert `"_source_attribution_text"` in result (always present)
- Assert `"_temporal_context"` NOT in result (empty string excluded)

### Test 11: `test_analyze_prompt_includes_innate_faculties`
- Import `_build_situation_review_prompt` from `probos.cognitive.sub_tasks.analyze`
- Build a context dict with:
  - `_agent_type`: `"agent"`
  - `_agent_rank`: `None`
  - `_skill_profile`: `None`
  - `_temporal_context`: `"Current time: 2026-04-18 12:00:00 UTC"`
  - `_ontology_context`: `"You are Echo, Counselor in Medical department."`
  - `_self_monitoring`: `"<cognitive_zone>GREEN</cognitive_zone>"`
  - `context`: `"Some ward room activity"`
- Call `_build_situation_review_prompt(context, [], "Echo", "Medical")`
- Assert the user_prompt contains `"## Temporal Awareness"`
- Assert the user_prompt contains `"## Your Identity"`
- Assert the user_prompt contains the actual context strings
- Assert `"## Assessment Required"` still appears (existing structure preserved)

### Test 12: `test_compose_user_prompt_includes_confabulation_guard`
- Import `_build_user_prompt` from `probos.cognitive.sub_tasks.compose`
- Build a context dict with:
  - `_confabulation_guard`: `"IMPORTANT: Do NOT fabricate specific numbers..."`
  - `_no_episodic_memories`: `"You have no stored episodic memories yet."`
  - `_source_attribution_text`: `"[Source awareness: training knowledge only.]"`
  - `_comm_proficiency`: `"Tier 2: Be concise."`
  - `_temporal_context`: `"Current time: 2026-04-18 12:00:00 UTC"`
- Call `_build_user_prompt(context, [])`
- Assert result contains `"## Knowledge Boundaries"`
- Assert result contains `"Do NOT fabricate"`
- Assert result contains `"Source awareness"`
- Assert result contains `"## Communication Guidance"`
- Assert result contains `"## Temporal Awareness"`

### Test 13: `test_observation_dict_receives_cognitive_state`
- Integration test: verify the wiring in `_execute_chain_with_intent_routing()`
- Create a CognitiveAgent, mock `_build_cognitive_state` to return `{"_temporal_context": "test-temporal", "_confabulation_guard": "test-guard"}`
- Mock `_sub_task_executor.execute_chain` to capture the observation dict passed
- Call `_execute_chain_with_intent_routing()` with a proactive_think intent and params containing `context_parts: {}`
- Assert the captured observation dict contains `_temporal_context` == `"test-temporal"` and `_confabulation_guard` == `"test-guard"`

### CognitiveAgent construction for tests:

```python
agent = CognitiveAgent(agent_id="test-agent")
```

`CognitiveAgent.__init__` takes `agent_id` as its only required param (inherited from
`BaseAgent`). Set attributes directly after construction:
```python
agent.callsign = "TestAgent"
agent._runtime = None  # or mock
```

### Import patterns:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
from probos.cognitive.sub_tasks.compose import _build_user_prompt
```

### Mocking `_build_temporal_context`:

```python
with patch.object(agent, '_build_temporal_context', return_value="Current time: 2026-04-18 12:00:00 UTC"):
    result = agent._build_cognitive_state({})
```

---

## What NOT to change

- **Do NOT modify `_build_user_message()`** — the one-shot path is correct and serves as reference
- **Do NOT modify `_gather_context()` or `proactive.py`** — all data is already available
- **Do NOT modify `perceive()`** — observation dict injection is the correct pattern
- **Do NOT add full `SourceAttribution` computation** — deferred to Phase 3
- **Do NOT modify ward_room_notification or dm prompt builders** — only `proactive_observation` (COMPOSE) and `situation_review` (ANALYZE) are affected
- **Do NOT duplicate rendering logic** — `_build_cognitive_state()` centralizes extraction, prompt builders just read the keys
- **Do NOT modify `_should_short_circuit()` in compose.py** — SILENT logic is correct

## Engineering Principles Compliance

| Principle | How |
|-----------|-----|
| **SRP** | `_build_cognitive_state()` has one job: extract innate faculties into observation dict. Prompt builders render. Clear separation. |
| **Open/Closed** | New observation keys added without modifying existing chain plumbing. ANALYZE and COMPOSE prompt builders extended, not rewritten. |
| **DRY** | Rendering logic for self-monitoring, ontology, etc. is extracted once in `_build_cognitive_state()`. Both ANALYZE and COMPOSE read from the same keys. |
| **Law of Demeter** | `_build_cognitive_state()` accesses `self._build_temporal_context()`, `self._working_memory`, `self._get_comm_proficiency_guidance()` — all public/protected methods on self. No reaching through objects. |
| **Fail Fast** | Missing data = key not set = prompt section skipped. No silent failures, no fallback fabrication. |

## Validation

```bash
python -m pytest tests/test_ad644_phase2_innate_faculties.py -v
python -m pytest tests/ -k "ad644 or cognitive" --timeout=30 -x
```

## Files Modified

| File | Change |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | `_build_cognitive_state()` method (~120 lines) + 3-line injection in `_execute_chain_with_intent_routing()` |
| `src/probos/cognitive/sub_tasks/analyze.py` | ~35-line innate faculties section in `_build_situation_review_prompt()` |
| `src/probos/cognitive/sub_tasks/compose.py` | ~25-line innate faculty rendering in `_build_user_prompt()` |
| `tests/test_ad644_phase2_innate_faculties.py` | 13 new tests |
