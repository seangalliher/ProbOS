# BF-024 Follow-Up: Complete Conversational Passthrough Guards

## Context

BF-024 fixed `proactive_think` passthrough in Builder, Architect, Counselor, and Scout. Post-fix review found that **SurgeonAgent** was missed — its `act()` only guards `direct_message`, missing both `ward_room_notification` and `proactive_think`. Since Surgeon is crew (added to `_WARD_ROOM_CREW` in the medical crew upgrade), this will cause the same degradation pattern on proactive think cycles.

Additionally, the existing test file `test_ad398_crew_identity.py` only covers `direct_message` passthrough. We need regression coverage for `ward_room_notification` and `proactive_think` across all agents with custom `act()` overrides.

## Pre-Build Audit

Read these files before editing:

1. `src/probos/agents/medical/surgeon.py` — the file to fix (line 57: only guards `direct_message`)
2. `tests/test_ad398_crew_identity.py` — existing test structure to extend
3. Reference the BF-024 pattern already applied in:
   - `src/probos/cognitive/builder.py` (line 2165: guard tuple with all three intents)
   - `src/probos/cognitive/architect.py` (line 577)
   - `src/probos/cognitive/counselor.py` (line 363)
   - `src/probos/cognitive/scout.py` (line 353)

## What To Build

### Step 1: Fix SurgeonAgent passthrough guard

In `src/probos/agents/medical/surgeon.py`, line 57, change:

```python
# AD-398: pass through conversational responses for 1:1 sessions
if decision.get("intent") == "direct_message":
    return {"success": True, "result": decision.get("llm_output", "")}
```

To:

```python
# AD-398/BF-024: pass through conversational responses for 1:1, ward room, and proactive
if decision.get("intent") in ("direct_message", "ward_room_notification", "proactive_think"):
    return {"success": True, "result": decision.get("llm_output", "")}
```

### Step 2: Add regression tests for ward_room_notification and proactive_think

Extend `tests/test_ad398_crew_identity.py` with a new test class after `TestDirectMessagePassthrough`:

```python
class TestConversationalPassthrough:
    """BF-024: act() passthrough for ward_room_notification and proactive_think."""
```

For each of these 5 agents that have custom `act()` overrides:
- ScoutAgent
- BuilderAgent
- ArchitectAgent
- SurgeonAgent
- CounselorAgent

Add two tests each (10 total):
1. `test_{agent}_ward_room_notification` — pass `{"intent": "ward_room_notification", "llm_output": "..."}` to `act()`, assert `success is True` and `result` matches.
2. `test_{agent}_proactive_think` — pass `{"intent": "proactive_think", "llm_output": "..."}` to `act()`, assert `success is True` and `result` matches.

Follow the exact pattern of the existing `TestDirectMessagePassthrough` tests (same mock setup, same assertion style).

### Step 3: Housekeeping — .gitignore and cross_layer_analysis.py

**`.gitignore`** — Add coverage artifacts after the `# Python` section:

```
# Coverage
.coverage
.coverage.*
htmlcov/
coverage.xml
```

**`cross_layer_analysis.py`** — Two small fixes:
1. Line 12: Replace hardcoded path with repository-relative:
   ```python
   BASE = Path(__file__).resolve().parent / "src" / "probos"
   ```
2. Line 38: Add `consensus` to cognitive's allowed imports:
   ```python
   "cognitive":  {"knowledge", "substrate", "mesh", "consensus"},
   ```

**Remove `.coverage`** from working tree:
```bash
rm -f .coverage
```

## Allowed Files

- `src/probos/agents/medical/surgeon.py`
- `tests/test_ad398_crew_identity.py`
- `cross_layer_analysis.py`
- `.gitignore`

## Do Not Build

- Do not modify Builder, Architect, Counselor, or Scout — they're already fixed
- Do not refactor unrelated agent code
- Do not add CI workflows or documentation
- Do not touch the commercial repo

## Test Gates

After Step 1 + Step 2:
```bash
uv run pytest tests/test_ad398_crew_identity.py -x -q
```

After full change set:
```bash
uv run pytest tests/ -x -q --tb=short
```

## Acceptance Criteria

1. SurgeonAgent.act() handles all three conversational intents
2. 10 new passthrough regression tests (2 per agent x 5 agents)
3. .gitignore includes coverage artifacts
4. cross_layer_analysis.py uses relative path and allows cognitive → consensus
5. All tests pass
