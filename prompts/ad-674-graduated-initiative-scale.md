# AD-674: Graduated Initiative Scale

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~8

---

## Problem

The current initiative model has four discrete `AgencyLevel` values
(REACTIVE→SUGGESTIVE→AUTONOMOUS→UNRESTRICTED) mapped 1:1 from `Rank`.
This is coarse — a newly promoted Lieutenant has the same initiative
privileges as one with high trust and proven track record.

A graduated 5-level initiative scale that considers both rank AND trust
would provide finer-grained control over agent autonomy without breaking
the existing rank-based gates.

## Fix

### Section 1: Create `InitiativeLevel` enum

**File:** `src/probos/earned_agency.py`

Add a new 5-level enum alongside the existing `AgencyLevel`. The two systems
coexist — `AgencyLevel` remains for backward compatibility, `InitiativeLevel`
is the graduated refinement.

Add after the existing `AgencyLevel` enum (line 16):

```python
class InitiativeLevel(int, Enum):
    """Graduated initiative scale (AD-674).

    Combines rank-based gates with trust-based graduation.
    Higher levels = more autonomous behavior.

    Level 0: DIRECTED     — Only acts on explicit instructions
    Level 1: RESPONSIVE   — Responds to @mentions and direct assignments
    Level 2: CONTRIBUTORY — Participates in department discussions
    Level 3: PROACTIVE    — Self-initiates within department scope
    Level 4: STRATEGIC    — Cross-department coordination, mentoring
    """

    DIRECTED = 0
    RESPONSIVE = 1
    CONTRIBUTORY = 2
    PROACTIVE = 3
    STRATEGIC = 4
```

### Section 2: Add `resolve_initiative_level()` function

**File:** `src/probos/earned_agency.py`

This function computes initiative level from rank + trust score. The
existing 3-gate model (ambient response, proactive thinking, action
permission) maps into the 5 levels without replacing the gates.

```python
def resolve_initiative_level(
    rank: "Rank",
    trust_score: float,
    *,
    thresholds: dict[str, float] | None = None,
) -> InitiativeLevel:
    """Resolve graduated initiative level from rank and trust (AD-674).

    Maps:
      Rank.ENSIGN + trust < 0.3       → DIRECTED (0)
      Rank.ENSIGN + trust ≥ 0.3       → RESPONSIVE (1)
      Rank.LIEUTENANT + trust < 0.5   → RESPONSIVE (1)
      Rank.LIEUTENANT + trust ≥ 0.5   → CONTRIBUTORY (2)
      Rank.COMMANDER + trust < 0.7    → CONTRIBUTORY (2)
      Rank.COMMANDER + trust ≥ 0.7    → PROACTIVE (3)
      Rank.SENIOR                     → STRATEGIC (4)

    The three existing gates remain authoritative for specific permissions.
    This function provides a unified scalar for initiative decisions.

    Args:
        rank: Agent's current rank
        trust_score: Agent's current trust score (0.0-1.0)
        thresholds: Optional override thresholds from config. Keys:
            "responsive" (default 0.3), "contributory" (default 0.5),
            "proactive" (default 0.7).

    Note: Rank is already imported at module level (line 8) from
    probos.crew_profile — do NOT re-import from probos.config.
    """
    t = thresholds or {}
    t_responsive = t.get("responsive", 0.3)
    t_contributory = t.get("contributory", 0.5)
    t_proactive = t.get("proactive", 0.7)

    rank_ordinal = {
        Rank.ENSIGN: 0,
        Rank.LIEUTENANT: 1,
        Rank.COMMANDER: 2,
        Rank.SENIOR: 3,
    }.get(rank, 0)

    if rank_ordinal >= 3:
        return InitiativeLevel.STRATEGIC

    if rank_ordinal >= 2:
        if trust_score >= t_proactive:
            return InitiativeLevel.PROACTIVE
        return InitiativeLevel.CONTRIBUTORY

    if rank_ordinal >= 1:
        if trust_score >= t_contributory:
            return InitiativeLevel.CONTRIBUTORY
        return InitiativeLevel.RESPONSIVE

    # Ensign
    if trust_score >= t_responsive:
        return InitiativeLevel.RESPONSIVE
    return InitiativeLevel.DIRECTED
```

### Section 3: Add `InitiativeConfig` to EarnedAgencyConfig

**File:** `src/probos/config.py`

Extend the existing `EarnedAgencyConfig` (line 1099):

SEARCH:
```python
class EarnedAgencyConfig(BaseModel):
    """Earned Agency — trust-tiered behavioral gating (AD-357)."""

    enabled: bool = False
```

REPLACE:
```python
class EarnedAgencyConfig(BaseModel):
    """Earned Agency — trust-tiered behavioral gating (AD-357)."""

    enabled: bool = False
    # AD-674: Graduated initiative thresholds
    initiative_trust_thresholds: dict[str, float] = {
        "responsive": 0.3,    # Ensign threshold
        "contributory": 0.5,  # Lieutenant threshold
        "proactive": 0.7,     # Commander threshold
    }
```

### Section 4: Expose initiative level on agent context

**File:** `src/probos/cognitive/cognitive_agent.py`

The `agency_from_rank()` call is at line 3622-3626 in the `_agent_metrics`
injection block. Add the graduated initiative level alongside it:

SEARCH:
```python
                from probos.earned_agency import agency_from_rank
```

REPLACE:
```python
                from probos.earned_agency import agency_from_rank, resolve_initiative_level
```

Then after `_agency_val = agency_from_rank(Rank.from_trust(_trust_val)).value`
(line 3626), add:

```python
                _initiative_val = resolve_initiative_level(
                    Rank.from_trust(float(_trust_val) if isinstance(_trust_val, str) else _trust_val),
                    _rt.trust_network.get_score(self.id),
                ).value
```

And append to the `_agent_metrics` string (line 3628-3629):

SEARCH:
```python
            state["_agent_metrics"] = (
                f"Your trust: {_trust_val} | "
```

REPLACE:
```python
            state["_agent_metrics"] = (
                f"Your trust: {_trust_val} | Initiative: {_initiative_val} | "
```

## Tests

**File:** `tests/test_ad674_graduated_initiative.py`

8 tests:

1. `test_initiative_level_enum_values` — verify 5 levels DIRECTED(0) through
   STRATEGIC(4) exist
2. `test_initiative_level_ordering` — verify DIRECTED < RESPONSIVE < CONTRIBUTORY
   < PROACTIVE < STRATEGIC via integer comparison
3. `test_ensign_low_trust_directed` — Ensign + trust 0.1 → DIRECTED
4. `test_ensign_moderate_trust_responsive` — Ensign + trust 0.4 → RESPONSIVE
5. `test_lieutenant_low_trust_responsive` — Lieutenant + trust 0.3 → RESPONSIVE
6. `test_lieutenant_high_trust_contributory` — Lieutenant + trust 0.6 → CONTRIBUTORY
7. `test_commander_high_trust_proactive` — Commander + trust 0.8 → PROACTIVE
8. `test_senior_always_strategic` — Senior + any trust → STRATEGIC

## What This Does NOT Change

- `AgencyLevel` enum remains unchanged — backward compatible
- The 3-gate model (`can_respond_ambient`, `can_think_proactively`,
  `can_perform_action`) remains authoritative for specific permissions
- `agency_from_rank()` remains unchanged
- `RecallTier` and `ClearanceGrant` are unaffected
- Does NOT change proactive loop tier configuration
- Does NOT modify Ward Room action permissions

## Tracking

- `PROGRESS.md`: Add AD-674 as COMPLETE
- `docs/development/roadmap.md`: Update AD-674 status

## Acceptance Criteria

- `InitiativeLevel` enum with 5 levels exists
- `resolve_initiative_level(rank, trust)` produces correct mappings
- Config thresholds are tunable via `EarnedAgencyConfig`
- Existing `AgencyLevel` and 3-gate model unchanged
- All 8 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# Current 4-level agency model
grep -n "class AgencyLevel" src/probos/earned_agency.py
  11: class AgencyLevel(str, Enum): REACTIVE, SUGGESTIVE, AUTONOMOUS, UNRESTRICTED

# Rank-to-agency mapping
grep -n "def agency_from_rank" src/probos/earned_agency.py
  135: maps Rank → AgencyLevel

# Three gates
grep -n "def can_respond_ambient\|def can_think_proactively\|def can_perform_action" \
  src/probos/earned_agency.py
  145: can_respond_ambient(rank, is_captain_post, same_department)
  171: can_think_proactively(rank)
  180: can_perform_action(rank, action)

# EarnedAgencyConfig
grep -n "class EarnedAgencyConfig" src/probos/config.py
  1099: enabled: bool = False

# Proactive tier config
grep -n "AgencyLevel" src/probos/proactive.py
  1741-1746: tier configs per agency level

# No existing InitiativeLevel
grep -rn "InitiativeLevel\|initiative_level" src/probos/ → no matches
```
