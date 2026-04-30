# AD-676 Action Risk Tiers Build Report

**Date:** 2026-04-30
**Status:** Complete
**Prompt:** `prompts/ad-676-action-risk-tiers.md`

## Summary

Implemented a unified action-risk classification registry. `ActionRiskRegistry` now maps Ward Room actions, remediation actions, and system operations to ROUTINE/ELEVATED/CRITICAL tiers and checks authorization from rank ordinal, trust score, clearance grant, and Captain override inputs. Startup finalization wires the registry onto runtime when risk tiers are enabled.

Existing earned-agency gates, tool permission resolution, initiative action gates, quorum authorization, and Counselor intervention paths were not changed.

## Files Changed

- `src/probos/governance/__init__.py`
  - Created the governance package.
- `src/probos/governance/risk_tiers.py`
  - Added `RiskTier`, `RiskPolicy`, `TIER_POLICIES`, and `ActionRiskRegistry`.
- `src/probos/events.py`
  - Added `EventType.ACTION_RISK_DENIED`.
- `src/probos/config.py`
  - Added `RiskTierConfig`.
  - Added `SystemConfig.risk_tiers`.
- `src/probos/startup/finalize.py`
  - Added finalize-time `ActionRiskRegistry` initialization and config-based policy overrides.
- `tests/test_ad676_action_risk_tiers.py`
  - Added 12 focused tests for tiers, classification, authorization, event, and config behavior.
- `PROGRESS.md`, `docs/development/roadmap.md`
  - Updated AD-676 tracking.

## Sections Implemented

- `### Section 1: Create RiskTier enum and ActionRiskRegistry`
  - Implemented in `src/probos/governance/risk_tiers.py`; `src/probos/governance/__init__.py` created first.
- `### Section 2: Add ACTION_RISK_CHECK event type`
  - Implemented as `EventType.ACTION_RISK_DENIED` per the prompt replacement text.
- `### Section 3: Add RiskTierConfig to SystemConfig`
  - Implemented in `src/probos/config.py`.
- `### Section 4: Wire into startup`
  - Implemented in `src/probos/startup/finalize.py`.
- `## Tests`
  - Implemented in `tests/test_ad676_action_risk_tiers.py`.
- `## Tracking`
  - Updated `PROGRESS.md`, `docs/development/roadmap.md`, and this build report.

## Post-Build Section Audit

- `### Section 1: Create RiskTier enum and ActionRiskRegistry` — complete; governance package, risk enum, policies, defaults, registration, authorization checks, and list API exist.
- `### Section 2: Add ACTION_RISK_CHECK event type` — complete as `ACTION_RISK_DENIED`, matching the prompt's acceptance criteria and replacement block.
- `### Section 3: Add RiskTierConfig to SystemConfig` — complete; config model and `SystemConfig.risk_tiers` exist.
- `### Section 4: Wire into startup` — complete; finalization wires runtime `_risk_registry` when enabled.
- `## Tests` — complete; 12 focused tests added.
- `## Tracking` — complete; tracker and build report updates added.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad676_action_risk_tiers.py -v -n 0`
  - Result: 12 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_config.py tests/test_api_system.py -v -n 0`
  - Result: 8 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
  - Result: 10125 passed, 18 skipped.

## Deviations

- Used per-registry policy copies for config overrides instead of mutating module-level `TIER_POLICIES`, following the approved review recommendation to avoid global policy mutation.
- Added 2 tests beyond the prompt's 10 to cover `EventType.ACTION_RISK_DENIED` and `RiskTierConfig` defaults.
