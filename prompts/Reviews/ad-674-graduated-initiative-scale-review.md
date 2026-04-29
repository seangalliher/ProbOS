# Review: AD-674 — Graduated Initiative Scale

**Verdict:** ⚠️ Conditional
**Headline:** Threshold config wired into runtime is missing; minor scope clarifications needed.

## Required

1. **Verify `InitiativeLevel` doesn't already exist.** Grep confirms the enum is new (no matches in codebase). Insertion after `AgencyLevel` at [earned_agency.py:11](src/probos/earned_agency.py#L11) is correct, but pin the line by SEARCH text not number.
2. **`Rank.from_trust()` parameter type.** Prompt calls `Rank.from_trust(float(...))`. Verify the function accepts `float` (it should — already used at `cognitive_agent.py:3626`). Add an explicit verification step.
3. **Threshold config not wired to call site.** Prompt adds `initiative_trust_thresholds` to `EarnedAgencyConfig` but no code reads it and passes it into `resolve_initiative_level()` at the call site in [cognitive_agent.py:3622](src/probos/cognitive/cognitive_agent.py#L3622). Add a wiring step (Section 3 or 4) that loads the config and threads it through.
4. **Import collision risk.** Section 4 adds `resolve_initiative_level` import to cognitive_agent.py near the existing `agency_from_rank` import (line 3620-ish). Verify no circular import or name shadowing.

## Recommended

1. **Test `Rank.from_trust(0.1) == Rank.ENSIGN`** to lock the threshold mapping. If `Rank.from_trust` ever changes, the initiative-level mapping silently breaks.
2. **Configuration timing.** Specify whether thresholds are read at instruction-injection time (recommended, allows hot-reload) or per-call. Don't leave this implicit.

## Nits

- Section 2 says "Rank is already imported at module level (line 8)." Verify it's still line 8; line numbers drift.
- `Rank.from_trust()` is called with a ternary (`isinstance(_trust_val, str) else _trust_val`). Trust values should already be float at this point — enforce typing at the assignment instead.

## Verified

- `AgencyLevel` at [earned_agency.py:11](src/probos/earned_agency.py#L11).
- `Rank` imported at [earned_agency.py:8](src/probos/earned_agency.py#L8).
- `agency_from_rank()` at [earned_agency.py:135](src/probos/earned_agency.py#L135).
- Three gate functions at [earned_agency.py:145, 171, 180](src/probos/earned_agency.py#L145).
- `EarnedAgencyConfig` at [config.py:1099](src/probos/config.py#L1099).
- Integration point in cognitive_agent.py at [lines 3622-3629](src/probos/cognitive/cognitive_agent.py#L3622).
- `InitiativeLevel` does NOT yet exist (zero matches in codebase).
