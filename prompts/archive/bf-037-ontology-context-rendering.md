# BF-037: Ontology Context Gathered But Never Rendered

## Problem

`_gather_context()` in `proactive.py` collects `context["ontology"]` (AD-429a, line 516) and `context["skill_profile"]` (AD-429b, line 529), but `_build_user_message()` in `cognitive_agent.py` (lines 471-557) never reads these keys. The data is silently dropped. Agents receive zero ontology grounding in their proactive think prompts despite the plumbing being in place across four ADs.

This is the primary anti-Troi-problem mechanism — the entire reason the ontology exists is to ground agents in who they are and where they fit. Without rendering, the ontology has no effect on agent behavior.

## Important Constraints

- Only modify `_build_user_message()` in `cognitive_agent.py` for the `proactive_think` branch (lines 471-557).
- Do NOT modify `proactive.py`, `ontology.py`, or any other files except tests.
- Render the ontology context concisely — this goes into an LLM prompt, so brevity matters. Don't dump raw dicts.
- Place ontology context early in the prompt (after the header/duty block, before memories) — identity grounding should come first.
- The `context_parts` dict has key `"ontology"` (a dict from `get_crew_context()`) and `"skill_profile"` (a list of strings).

## Fix

In `_build_user_message()`, in the `proactive_think` branch, insert two new rendering blocks **after** the cold-start system note block (lines 499-503) and **before** the recent memories block (lines 505-514).

### Block 1: Ontology identity grounding

```python
# AD-429: Ontology identity grounding
ontology = context_parts.get("ontology")
if ontology:
    identity = ontology.get("identity", {})
    dept = ontology.get("department", {})
    vessel = ontology.get("vessel", {})
    pt_parts.append(f"You are {identity.get('callsign', '?')}, {identity.get('post', '?')} in {dept.get('name', '?')} department.")
    if ontology.get("reports_to"):
        pt_parts.append(f"You report to {ontology['reports_to']}.")
    if ontology.get("direct_reports"):
        pt_parts.append(f"Your direct reports: {', '.join(ontology['direct_reports'])}.")
    if ontology.get("peers"):
        pt_parts.append(f"Department peers: {', '.join(ontology['peers'])}.")
    if vessel:
        alert = vessel.get("alert_condition", "GREEN")
        pt_parts.append(f"Ship status: {vessel.get('name', 'ProbOS')} v{vessel.get('version', '?')} — Alert Condition {alert}.")
    pt_parts.append("")
```

### Block 2: Skill profile

```python
# AD-429b: Skill profile
skill_profile = context_parts.get("skill_profile")
if skill_profile:
    pt_parts.append(f"Your skills: {', '.join(skill_profile)}.")
    pt_parts.append("")
```

### Final prompt order

After the fix, the `proactive_think` prompt sections should be in this order:

1. Header (duty cycle or free-form think) + trust/rank
2. Cold-start system note (BF-034)
3. **Ontology identity grounding** ← NEW
4. **Skill profile** ← NEW
5. Recent memories
6. Recent alerts
7. Recent events
8. Recent Ward Room activity
9. Closing instruction

---

## Tests

Add tests to an existing or new test file. Recommended: add to `tests/test_proactive.py` if it tests `_build_user_message`, or create a focused `tests/test_bf037_ontology_rendering.py`.

### Test 1: `test_ontology_rendered_in_proactive_think`
Create a `CognitiveAgent` subclass (or use existing test fixture), call `_build_user_message()` with a `proactive_think` intent containing `context_parts` with an `ontology` dict matching the shape from `get_crew_context()`:
```python
{
    "identity": {"agent_type": "security_officer", "callsign": "Worf", "post": "Chief of Security"},
    "department": {"id": "security", "name": "Security"},
    "vessel": {"name": "ProbOS", "version": "0.4.0", "alert_condition": "GREEN"},
    "chain_of_command": ["Chief of Security", "First Officer", "Captain"],
    "reports_to": "First Officer (Number One)",
    "direct_reports": [],
    "peers": [],
    "adjacent_departments": ["Engineering", "Operations"],
}
```
Assert the output contains "You are Worf, Chief of Security in Security department."

### Test 2: `test_ontology_reports_to_rendered`
Same setup but with `reports_to` populated. Assert output contains "You report to First Officer (Number One)."

### Test 3: `test_ontology_direct_reports_rendered`
Use `first_officer` context with `direct_reports: ["Chief Engineer", "Chief Science Officer"]`. Assert output contains "Your direct reports: Chief Engineer, Chief Science Officer."

### Test 4: `test_ontology_peers_rendered`
Use a medical department agent with peers. Assert output contains "Department peers:".

### Test 5: `test_skill_profile_rendered`
Set `context_parts["skill_profile"] = ["system_analysis: level 3 (competent)", "security: level 4 (proficient)"]`. Assert output contains "Your skills: system_analysis: level 3 (competent), security: level 4 (proficient)."

### Test 6: `test_ontology_absent_no_crash`
Call with `context_parts` that has no `"ontology"` key. Assert the prompt still generates successfully (no KeyError, no crash).

### Test 7: `test_skill_profile_absent_no_crash`
Call with `context_parts` that has no `"skill_profile"` key. Assert the prompt still generates successfully.

### Test 8: `test_ontology_before_memories`
Provide both ontology context and recent memories. Assert that "You are Worf" appears BEFORE "Recent memories" in the output string.

### Test structure

The `_build_user_message()` method is on `CognitiveAgent`. You need a minimal agent instance to call it. Check existing test patterns — `test_proactive.py` or `test_ad437_action_space.py` likely have fixtures for creating agents with minimal runtime mocking. The method signature is `_build_user_message(self, observation: dict) -> str` where `observation` must have `intent: "proactive_think"` and `params` containing `context_parts`, `trust_score`, `agency_level`, `rank`.

---

## Verification

1. `uv run pytest tests/test_bf037_ontology_rendering.py -v` — all 8 tests pass
2. `uv run pytest tests/test_proactive.py -v` — existing proactive tests pass
3. `uv run pytest` — full suite passes

---

## Files

| File | Action |
|------|--------|
| `src/probos/cognitive/cognitive_agent.py` | **MODIFY** — Add ontology + skill_profile rendering blocks in `_build_user_message()` `proactive_think` branch |
| `tests/test_bf037_ontology_rendering.py` | **NEW** — 8 tests for ontology/skill context rendering |
