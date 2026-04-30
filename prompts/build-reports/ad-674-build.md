# AD-674 Graduated Initiative Scale Build Report

**Date:** 2026-04-30
**Status:** Complete
**Prompt:** `prompts/ad-674-graduated-initiative-scale.md`

## Summary

Implemented a graduated initiative scale alongside the existing earned-agency gates. `InitiativeLevel` now provides five ordered initiative levels, `resolve_initiative_level()` maps rank plus trust into that scale, `EarnedAgencyConfig` exposes tunable initiative trust thresholds, and `CognitiveAgent` baseline metrics include the resolved initiative level from runtime trust.

Existing `AgencyLevel`, `agency_from_rank()`, recall tiers, clearance grants, and the three earned-agency gate functions were not changed.

## Files Changed

- `src/probos/earned_agency.py`
  - Added `InitiativeLevel`.
  - Added `resolve_initiative_level()`.
- `src/probos/config.py`
  - Added `EarnedAgencyConfig.initiative_trust_thresholds`.
- `src/probos/cognitive/cognitive_agent.py`
  - Wired runtime earned-agency threshold config into `resolve_initiative_level()`.
  - Added initiative level to `_agent_metrics`.
- `tests/test_ad674_graduated_initiative.py`
  - Added 13 focused tests for initiative enum values, ordering, mappings, threshold overrides, config defaults, and CognitiveAgent metric wiring.
- `PROGRESS.md`, `docs/development/roadmap.md`
  - Updated AD-674 tracking.

## Sections Implemented

- `### Section 1: Create InitiativeLevel enum`
  - Implemented in `src/probos/earned_agency.py`.
- `### Section 2: Add resolve_initiative_level() function`
  - Implemented in `src/probos/earned_agency.py`.
- `### Section 3: Add InitiativeConfig to EarnedAgencyConfig`
  - Implemented as `EarnedAgencyConfig.initiative_trust_thresholds` in `src/probos/config.py`.
- `### Section 4: Expose initiative level on agent context`
  - Implemented in `src/probos/cognitive/cognitive_agent.py`; thresholds are extracted from `_runtime_ref.config.earned_agency.initiative_trust_thresholds` and passed to `resolve_initiative_level()`.
- `## Tests`
  - Implemented in `tests/test_ad674_graduated_initiative.py`.
- `## Tracking`
  - Updated `PROGRESS.md`, `docs/development/roadmap.md`, and this build report.

## Post-Build Section Audit

- `### Section 1: Create InitiativeLevel enum` — complete; five ordered enum values DIRECTED through STRATEGIC exist.
- `### Section 2: Add resolve_initiative_level() function` — complete; rank+trust mappings and optional threshold overrides exist.
- `### Section 3: Add InitiativeConfig to EarnedAgencyConfig` — complete; default responsive/contributory/proactive thresholds are configurable.
- `### Section 4: Expose initiative level on agent context` — complete; CognitiveAgent metrics compute initiative from runtime trust and runtime config thresholds.
- `## Tests` — complete; 13 focused tests added.
- `## Tracking` — complete; trackers and build report updated.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad674_graduated_initiative.py -v -n 0`
  - Result: 13 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_earned_agency.py tests/test_ad646_cognitive_baseline.py tests/test_config.py -v -n 0`
  - Result: 38 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
  - Result: 10213 passed, 18 skipped.

## Deviations

- Added 5 focused tests beyond the prompt's estimated 8 to cover the review-requested `Rank.from_trust(0.1)` check, configurable threshold behavior, config defaults, and CognitiveAgent threshold wiring.
- Attempted a full serial gate with `tests/ -x -q -n 0`; it was stopped after extended runtime without failure output. The required serial prompt and focused gates passed, and the project full parallel gate passed.
