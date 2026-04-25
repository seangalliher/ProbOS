# AD-429e: Ontology Dict Migration

## Goal

Replace `_WARD_ROOM_CREW` (hardcoded set in `runtime.py`) and `_AGENT_DEPARTMENTS` (hardcoded dict in `standing_orders.py`) with queries to the `VesselOntologyService`. The ontology has been fully built (AD-429a–d) with replacement methods already tested and ready: `get_crew_agent_types()` and `get_agent_department()`. This AD wires them in and removes the legacy dicts.

## Important Constraints

- The ontology may be `None` (config dir missing, initialization failed). Every replacement site must have a **graceful fallback** — use the ontology when available, fall back to the legacy dict/set when it's not.
- Do NOT remove the `_AGENT_DEPARTMENTS` dict or `_WARD_ROOM_CREW` set yet. Keep them as fallback sources. Mark them with a `# Legacy fallback — remove when ontology is mandatory` comment.
- `register_department()` has no ontology equivalent. Keep it — it mutates `_AGENT_DEPARTMENTS` for dynamic agents.
- `compose_instructions()` calls `get_department()` internally (line 214). Do NOT modify `compose_instructions()` — it already accepts an optional `department` parameter that callers can use.
- The ontology service lives at `runtime.ontology` (type: `VesselOntologyService | None`). Agents access it via `self._runtime.ontology`.

---

## Changes

### File 1: `src/probos/runtime.py`

#### Change 1a: `_is_crew_agent()` — use ontology with fallback

Replace lines 3542–3546:

```python
def _is_crew_agent(self, agent: Any) -> bool:
    """Check if an agent is core crew eligible for Ward Room participation."""
    if not hasattr(agent, 'agent_type'):
        return False
    return agent.agent_type in self._WARD_ROOM_CREW
```

With:

```python
def _is_crew_agent(self, agent: Any) -> bool:
    """Check if an agent is core crew eligible for Ward Room participation."""
    if not hasattr(agent, 'agent_type'):
        return False
    # AD-429e: Prefer ontology, fall back to legacy set
    if self.ontology:
        return agent.agent_type in self.ontology.get_crew_agent_types()
    return agent.agent_type in self._WARD_ROOM_CREW
```

#### Change 1b: `get_department()` call sites in runtime.py — pass ontology result

There are 4 `get_department()` call sites in runtime.py. For each one, replace the pattern:

```python
from probos.cognitive.standing_orders import get_department
dept = get_department(agent.agent_type)
```

With:

```python
from probos.cognitive.standing_orders import get_department
# AD-429e: Prefer ontology, fall back to legacy dict
dept = (self.ontology.get_agent_department(agent.agent_type) if self.ontology else None) or get_department(agent.agent_type)
```

The 4 call sites are at approximately:
- Line 1311 (in the intent routing/dispatch block)
- Line 3347 (in `_department_channel_for_agent` or similar ward room dispatch)
- Line 3391 (in another ward room channel matching block)
- Line 3899 (in ACM onboarding block — note: this one has `or "operations"` fallback, preserve that)

For the ACM line (~3899), the result should be:

```python
department = (self.ontology.get_agent_department(agent.agent_type) if self.ontology else None) or get_department(agent.agent_type) or "operations"
```

#### Change 1c: Add `# Legacy fallback` comment to `_WARD_ROOM_CREW`

At line 3531, change the comment:

```python
# Core crew eligible for Ward Room participation.
# Infrastructure agents (vitals_monitor, red_team, system_qa, introspect,
# emergent_detector) and utility agents are excluded.
```

To:

```python
# Legacy fallback — remove when ontology is mandatory.
# Core crew eligible for Ward Room participation.
# Ontology equivalent: VesselOntologyService.get_crew_agent_types()
```

---

### File 2: `src/probos/cognitive/standing_orders.py`

#### Change 2a: Add `# Legacy fallback` comment to `_AGENT_DEPARTMENTS`

At line 30, change:

```python
# Department mapping: agent_type -> department name
```

To:

```python
# Legacy fallback — remove when ontology is mandatory.
# Department mapping: agent_type -> department name
# Ontology equivalent: VesselOntologyService.get_agent_department()
```

No other changes to standing_orders.py. `get_department()` and `register_department()` remain unchanged — they still operate on the legacy dict, which serves as fallback.

---

### File 3: `src/probos/ward_room.py`

#### Change 3a: Replace `_AGENT_DEPARTMENTS` import with ontology query

At line 526, the `_ensure_default_channels()` method imports `_AGENT_DEPARTMENTS` directly to derive department names:

```python
from probos.cognitive.standing_orders import _AGENT_DEPARTMENTS
departments = sorted(set(_AGENT_DEPARTMENTS.values()))
```

Replace with:

```python
from probos.cognitive.standing_orders import _AGENT_DEPARTMENTS
# AD-429e: Prefer ontology department list, fall back to legacy dict
if self._ontology:
    departments = sorted(d.id for d in self._ontology.get_departments())
else:
    departments = sorted(set(_AGENT_DEPARTMENTS.values()))
```

This requires `_ensure_default_channels()` to have access to the ontology. The `WardRoom` class needs an ontology reference.

#### Change 3b: Add ontology parameter to WardRoom

Find the `WardRoom.__init__()` method. Add an optional `ontology` parameter:

```python
def __init__(self, ..., ontology: Any = None):
```

Store it as `self._ontology = ontology`.

#### Change 3c: Wire ontology into WardRoom from runtime

In `src/probos/runtime.py`, find where WardRoom is constructed (search for `WardRoom(` in `_setup_services` or similar). Pass `ontology=self.ontology` to the constructor.

**IMPORTANT**: Check the initialization order. If WardRoom is constructed BEFORE the ontology is initialized, you'll need to either:
1. Set `ward_room._ontology = self.ontology` AFTER ontology init, or
2. Move WardRoom construction after ontology init.

Search for the construction order and handle appropriately.

---

### File 4: `src/probos/proactive.py`

There are 3 `get_department()` call sites in proactive.py. For each one, enhance with ontology preference:

```python
from probos.cognitive.standing_orders import get_department
dept = get_department(agent.agent_type)
```

Replace with:

```python
from probos.cognitive.standing_orders import get_department
# AD-429e: Prefer ontology, fall back to legacy dict
ont = getattr(rt, 'ontology', None)
dept = (ont.get_agent_department(agent.agent_type) if ont else None) or get_department(agent.agent_type)
```

Where `rt` is the runtime reference (may be `self._runtime`, `rt`, or similar — check the local variable name at each site). The 3 call sites are at approximately:
- Line 429–430
- Line 546–547
- Line 656–657

---

### File 5: `src/probos/experience/shell.py`

There are 4 `get_department()` call sites in shell.py. For each one, enhance with ontology preference:

The shell has a reference to the runtime. Check how it accesses it (likely `self.runtime` or similar). Then apply the same pattern:

```python
# AD-429e: Prefer ontology, fall back to legacy dict
ont = getattr(self.runtime, 'ontology', None) if hasattr(self, 'runtime') else None
dept = (ont.get_agent_department(agent_type) if ont else None) or get_department(agent_type)
```

The 4 call sites are at approximately:
- Line 1087 (target_department in routing)
- Line 1095
- Line 1109 (in a loop over pools)
- Line 1172

Note: shell.py may not have easy access to the runtime. If the ontology can't be accessed from shell context, skip these call sites — mark them with `# AD-429e: TODO — needs ontology access` comments and leave the legacy call.

---

### File 6: `src/probos/cognitive/cognitive_agent.py`

No `get_department()` calls here. The `_is_crew_agent()` usage goes through `self._runtime._is_crew_agent(self)` which is already covered by Change 1a.

No changes needed.

---

### File 7: `src/probos/api.py`

The `_is_crew_agent()` usage goes through `runtime._is_crew_agent(agent)` which is already covered by Change 1a.

No changes needed.

---

## Tests

Create `tests/test_ad429e_dict_migration.py` with these tests:

### Test 1: `test_is_crew_agent_prefers_ontology`

Mock `runtime.ontology` with a `get_crew_agent_types()` that returns `{"security_officer", "counselor"}`. Create a mock agent with `agent_type="security_officer"`. Assert `runtime._is_crew_agent(agent)` returns True. Then set `agent_type="builder"` (which IS in the legacy set). Assert returns False — ontology takes precedence.

### Test 2: `test_is_crew_agent_falls_back_without_ontology`

Set `runtime.ontology = None`. Create a mock agent with `agent_type` in `_WARD_ROOM_CREW`. Assert `_is_crew_agent()` returns True — fallback works.

### Test 3: `test_department_lookup_prefers_ontology`

Test one of the runtime `get_department()` call sites. Mock ontology to return `"engineering"` for `agent_type="builder"`. Verify the ontology result is used. Then mock ontology to return `None` — verify fallback to `get_department()`.

### Test 4: `test_department_lookup_falls_back_without_ontology`

Set `runtime.ontology = None`. Verify `get_department()` from standing_orders is called and returns the correct department.

### Test 5: `test_ward_room_channels_from_ontology`

Create a WardRoom with a mock ontology that has `get_departments()` returning `[Department(id="engineering", ...), Department(id="medical", ...)]`. Call `_ensure_default_channels()`. Assert channels are created for "engineering" and "medical".

### Test 6: `test_ward_room_channels_fallback_without_ontology`

Create a WardRoom with `ontology=None`. Assert `_ensure_default_channels()` still works using `_AGENT_DEPARTMENTS` values.

### Test 7: `test_register_department_still_works`

Call `register_department("new_agent", "security")`. Assert `get_department("new_agent")` returns `"security"`. (Legacy mutation path preserved.)

### Test 8: `test_ontology_crew_matches_legacy_set`

Load the real ontology (from `config/ontology/` if available) and compare `get_crew_agent_types()` output against `_WARD_ROOM_CREW`. They should match (minus "builder" which was removed from crew in BF-018 but may or may not be in the ontology as crew-tier). If ontology config is not available, skip the test.

### Test structure

Use `unittest.mock.MagicMock` for ontology mocks. For runtime tests, create a minimal `ProbOSRuntime` instance or mock. Check existing test patterns in `test_proactive.py` and `test_ward_room_agents.py` for how runtime mocks are set up. For Test 8, use `pytest.importorskip` pattern or check for config directory existence.

---

## Verification

1. `uv run pytest tests/test_ad429e_dict_migration.py -v` — all 8 tests pass
2. `uv run pytest tests/test_standing_orders.py -v` — existing tests pass (legacy dict untouched)
3. `uv run pytest tests/test_proactive.py -v` — existing tests pass
4. `uv run pytest tests/test_ward_room_agents.py -v` — existing tests pass
5. `uv run pytest` — full suite passes

---

## Files

| File | Action |
|------|--------|
| `src/probos/runtime.py` | **MODIFY** — `_is_crew_agent()` ontology preference, 4× `get_department()` ontology preference, legacy comment on `_WARD_ROOM_CREW` |
| `src/probos/cognitive/standing_orders.py` | **MODIFY** — Legacy comment on `_AGENT_DEPARTMENTS` |
| `src/probos/ward_room.py` | **MODIFY** — `_ensure_default_channels()` ontology preference, `__init__()` ontology parameter |
| `src/probos/proactive.py` | **MODIFY** — 3× `get_department()` ontology preference |
| `src/probos/experience/shell.py` | **MODIFY** — 4× `get_department()` ontology preference (or TODO comments if runtime inaccessible) |
| `tests/test_ad429e_dict_migration.py` | **NEW** — 8 tests for ontology-first migration |
