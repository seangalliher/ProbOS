# Wave 1: Agent Awareness & DM Accessibility (BF-049/050/051/052)

## Context

Sea trial on 2026-03-27 after AD-485 (Communications Command Center) revealed four agent awareness bugs that prevent crew from using DMs and knowing their peers. The Captain ordered all departments to DM their peers — every agent acknowledged publicly but none actually DMed. Root causes: stale callsigns in ontology, no self-identity in chat, DM syntax only in proactive prompt, flat crew roster with no department grouping.

## Prerequisites

- Read `docs/development/roadmap.md` bug tracker entries BF-049 through BF-052
- Read the files listed under each fix below before modifying them

---

## Fix 1: Sync ontology callsigns after naming ceremony (BF-049, BF-050)

**Root cause:** `runtime.py` naming ceremony (line ~4012-4014) updates `agent.callsign` and `callsign_registry.set_callsign()` but never updates `ontology.Assignment.callsign`. The ontology retains seed callsigns ("Number One", "LaForge", "Scotty"). When `get_crew_context()` renders peers and reports_to, it shows stale names. Agents see stale callsigns in their ontology context and reference them in conversation.

**Files to modify:**
- `src/probos/runtime.py` — after naming ceremony callsign update (~line 4014)
- `src/probos/ontology.py` — add `update_assignment_callsign()` method

**Implementation:**

1. In `ontology.py`, add a method to `ShipOntology`:
```python
def update_assignment_callsign(self, agent_type: str, new_callsign: str) -> bool:
    """Update the callsign on an agent's Assignment after naming ceremony."""
    assignment = self._assignments.get(agent_type)
    if not assignment:
        return False
    # dataclass — create new instance with updated callsign
    self._assignments[agent_type] = Assignment(
        agent_type=assignment.agent_type,
        post_id=assignment.post_id,
        callsign=new_callsign,
        agent_id=assignment.agent_id,
    )
    return True
```

2. In `runtime.py`, after `self.callsign_registry.set_callsign(agent.agent_type, chosen_callsign)` (line ~4014), add:
```python
# Sync ontology assignment so peers/reports_to show current callsigns
if hasattr(self, 'ontology') and self.ontology:
    self.ontology.update_assignment_callsign(agent.agent_type, chosen_callsign)
```

**Tests (new file: `tests/test_ontology_callsign_sync.py`):**
1. `test_update_assignment_callsign_updates_peer_context` — create ontology with 2 agents in same department, update one's callsign, verify `get_crew_context()` for the other shows new name in peers
2. `test_update_assignment_callsign_updates_reports_to` — update a superior's callsign, verify subordinate's `get_crew_context()` reports_to shows new name
3. `test_update_assignment_callsign_nonexistent_agent` — returns False for unknown agent_type
4. `test_naming_ceremony_syncs_ontology` — mock the naming ceremony flow, verify ontology assignment has new callsign after ceremony

---

## Fix 2: DM syntax in chat/1:1 context (BF-051)

**Root cause:** The DM instruction block (lines 223-253 of `cognitive_agent.py`) is inside the `elif observation.get("intent") == "proactive_think":` branch. When agents respond to Ward Room notifications or direct messages, they don't see the `[DM @callsign]` syntax instructions. The Captain ordered agents to DM peers, but they could only acknowledge publicly because the DM output format wasn't available in their prompt.

**Files to modify:**
- `src/probos/cognitive/cognitive_agent.py` — `compose_system_prompt()` method

**Implementation:**

1. Extract the DM instruction block (crew roster + DM syntax) into a helper method `_compose_dm_instructions(self) -> str` that builds the roster and returns the instruction text.

2. Call this helper in BOTH the `proactive_think` branch (where it already lives, lines 223-253) AND the `ward_room_notification` branch (after line 183). The Ward Room context should include a shorter version:
```
"\n\nYou may also send a private message to a crew member:\n"
"[DM @callsign]\nYour message (2-3 sentences).\n[/DM]\n"
f"{_dm_crew_list}"
"ONLY DM crew listed above. You may DM @captain for urgent matters.\n"
```

3. For the `direct_message` branch (1:1 with Captain, line 255-263), do NOT add DM syntax — 1:1 conversations don't produce DM output, they're already a DM context.

**Tests (add to existing `tests/test_communications_settings.py` or new):**
1. `test_dm_syntax_in_ward_room_prompt` — compose system prompt with `intent="ward_room_notification"`, verify `[DM @callsign]` syntax is present
2. `test_dm_syntax_in_proactive_prompt` — verify it's still present (existing behavior, regression guard)
3. `test_dm_syntax_not_in_direct_message_prompt` — compose with `intent="direct_message"`, verify `[DM @` is NOT present
4. `test_dm_crew_roster_in_ward_room_prompt` — verify crew roster appears in ward_room_notification prompt

---

## Fix 3: Department-grouped crew roster (BF-052)

**Root cause:** `all_callsigns()` at line 228-233 returns a flat `{agent_type: callsign}` dict. The crew roster rendered in the prompt is `Available crew to DM: @Chapel, @Forge, @Hawkins, @Hikari, @Keiko, @Meridian, @Phlox, @Sage, @Sentinel, @Tesla, @Vega`. No department context. Tesla doesn't know Forge is also in Engineering. When told to "coordinate with your departmental peer," agents can't identify who that is from the roster alone.

**Files to modify:**
- `src/probos/cognitive/cognitive_agent.py` — the `_compose_dm_instructions()` helper (from Fix 2)

**Implementation:**

1. In the `_compose_dm_instructions()` helper, instead of building a flat list, group crew by department using the ontology:

```python
def _compose_dm_instructions(self) -> str:
    """Build DM instruction block with department-grouped roster."""
    _rt = getattr(self, '_runtime', None)
    if not _rt:
        return ""

    # Build department-grouped roster
    _dm_crew_list = ""
    if hasattr(_rt, 'callsign_registry') and hasattr(_rt, 'ontology') and _rt.ontology:
        try:
            _all_cs = _rt.callsign_registry.all_callsigns()
            _self_atype = getattr(self, 'agent_type', '')

            # Group by department using ontology
            dept_groups: dict[str, list[str]] = {}
            for atype, cs in _all_cs.items():
                if atype == _self_atype or not cs:
                    continue
                dept = _rt.ontology.get_agent_department(atype)
                dept_name = dept or "Bridge"
                dept_groups.setdefault(dept_name, []).append(f"@{cs}")

            if dept_groups:
                parts = []
                for dept_name in sorted(dept_groups):
                    members = ", ".join(sorted(dept_groups[dept_name]))
                    parts.append(f"{dept_name}: {members}")
                _dm_crew_list = "Available crew to DM:\n" + "\n".join(parts) + "\n"
        except Exception:
            # Fallback to flat list
            try:
                _all_cs = _rt.callsign_registry.all_callsigns()
                _self_atype = getattr(self, 'agent_type', '')
                _crew_entries = [f"@{cs}" for atype, cs in _all_cs.items()
                                 if atype != _self_atype and cs]
                if _crew_entries:
                    _dm_crew_list = f"Available crew to DM: {', '.join(sorted(_crew_entries))}\n"
            except Exception:
                pass
    elif hasattr(_rt, 'callsign_registry'):
        # No ontology — flat list fallback
        try:
            _all_cs = _rt.callsign_registry.all_callsigns()
            _self_atype = getattr(self, 'agent_type', '')
            _crew_entries = [f"@{cs}" for atype, cs in _all_cs.items()
                             if atype != _self_atype and cs]
            if _crew_entries:
                _dm_crew_list = f"Available crew to DM: {', '.join(sorted(_crew_entries))}\n"
        except Exception:
            pass

    return (
        "**Direct message a crew member** — reach out privately to another agent:\n"
        "[DM @callsign]\n"
        "Your message to this crew member (2-3 sentences).\n"
        "[/DM]\n"
        f"{_dm_crew_list}"
        "Use for: consulting a specialist, coordinating on a shared concern, "
        "asking for input on something in your department. "
        "ONLY DM crew members listed above. Do NOT invent crew members who don't exist. "
        "You may DM @captain for urgent matters that need the Captain's direct attention. "
        "Use sparingly — routine reports belong in your observation post.\n"
    )
```

The rendered output should look like:
```
Available crew to DM:
Bridge: @Sage
Engineering: @Forge, @Tesla
Medical: @Chapel, @Hawkins, @Hikari, @Phlox
Science: @Meridian, @Vega
Security: @Sentinel
Operations: @Keiko
```

**Tests:**
1. `test_crew_roster_grouped_by_department` — set up ontology + callsign registry, compose prompt, verify department headers appear
2. `test_crew_roster_excludes_self` — verify the agent's own callsign is not in the roster
3. `test_crew_roster_fallback_flat_when_no_ontology` — verify flat list when ontology is None

---

## Verification

After implementing all fixes:

1. **Targeted tests only** — run the new tests from each fix
2. **Regression** — run `pytest tests/test_communications_settings.py tests/test_callsign_validation.py tests/test_ontology_callsign_sync.py tests/test_onboarding.py -v`
3. **Full suite in background** — `pytest -n auto -m "not slow"` to verify no regressions

## Files Summary

**Modify:**
- `src/probos/ontology.py` — add `update_assignment_callsign()` method
- `src/probos/runtime.py` — sync ontology after naming ceremony
- `src/probos/cognitive/cognitive_agent.py` — extract `_compose_dm_instructions()`, add DM syntax to ward_room_notification, department-grouped roster

**Create:**
- `tests/test_ontology_callsign_sync.py` — 4 tests for ontology callsign sync

**Modify (tests):**
- `tests/test_communications_settings.py` — add 4 tests for DM syntax availability + 3 tests for department grouping

## Tracking

Update on completion:
- `PROGRESS.md` — mark BF-049, BF-050, BF-051, BF-052 closed
- `DECISIONS.md` — add brief BF summary
- `docs/development/roadmap.md` — update bug tracker entries to Closed
