# Review: AD-566f — Qualification → Skill Bridge

**Verdict:** ⚠️ Conditional
**Headline:** Class name mismatch (`SkillService` vs `AgentSkillService`); missing `ProficiencyLevel` import.

## Required

1. **Class name mismatch.** Prompt's bridge constructs `skill_service: Any` and calls `await self._skill_service.get_profile(...)` / `update_proficiency(...)`. The actual class is `AgentSkillService` at [skill_framework.py:435](src/probos/skill_framework.py#L435), not `SkillService`. Runtime wiring is correct (`runtime.skill_service` IS an `AgentSkillService`), but Section 1 docstring/typing should call out the real type.
2. **`ProficiencyLevel` enum must be imported.** The bridge's line ~118 calls `ProficiencyLevel(target_level)`. Add `from probos.skill_framework import ProficiencyLevel` to bridge module imports.
3. **Wiring location specificity.** Prompt says "after [runtime.py:1551](src/probos/runtime.py#L1551), where both `skill_service` and `_qualification_store` are available." Line 1551 is `self.skill_service = comm.skill_service`. Provide an exact insert point (next line) and verify `_qualification_store` is set BEFORE 1551 (it's at line 1310, so safe).

## Recommended

1. **Mock alignment in tests.** Test 6 mocks `skill_service` with FOLLOW(1) proficiency but doesn't specify the `get_profile()` return shape. Provide a fixture for `SkillProfile` with nested skill records.
2. **Threshold tunability.** `DEFAULT_SCORE_THRESHOLDS` (0.50 ASSIST, 0.60 APPLY, etc.) is hardcoded. Note as a future enhancement: domain-specific thresholds (e.g., threat_analysis may need 0.80) should move to config.

## Nits

- `SkillAdvancement.qualification_test: str` — clarify whether it's a test name (`"threat_analysis_t1"`) or a class path.

## Verified

- `QualificationStore` at [cognitive/qualification.py:136](src/probos/cognitive/qualification.py#L136).
- `AgentSkillService` at [skill_framework.py:435](src/probos/skill_framework.py#L435).
- `update_proficiency()` at [skill_framework.py:542](src/probos/skill_framework.py#L542).
- `get_profile()` at [skill_framework.py:611](src/probos/skill_framework.py#L611).
- `ProficiencyLevel` at [skill_framework.py:38](src/probos/skill_framework.py#L38).
- `runtime._qualification_store` at [runtime.py:1310](src/probos/runtime.py#L1310); `runtime.skill_service` at [runtime.py:1551](src/probos/runtime.py#L1551).

---

## Re-review (2026-04-29, second pass)

**Verdict:** ✅ Approved.

| Prior Required | Status | Evidence |
|---|---|---|
| Class name `AgentSkillService` not `SkillService` | ✅ Fixed | "Verified Against Codebase" section now correctly cites `AgentSkillService` at [skill_framework.py:435](src/probos/skill_framework.py#L435). Bridge accepts `skill_service: Any` (receives an `AgentSkillService` from `runtime.skill_service`) — correct. |
| Import `ProficiencyLevel` | ✅ Fixed | Late-bound `from probos.skill_framework import ProficiencyLevel` inside `process_qualification()`. |
| Wiring location specificity | ✅ Fixed | Verified `_qualification_store` set at [runtime.py:1310](src/probos/runtime.py#L1310) and `skill_service` at [runtime.py:1551](src/probos/runtime.py#L1551); insertion safe immediately after 1551. |

### Recommended (non-blocking)

- Annotate `skill_service: AgentSkillService` (not `Any`) on the bridge constructor for IDE/static-analyzer benefit. Forward-import via `TYPE_CHECKING` if needed to avoid circular imports.
- Test 6 still needs an explicit `SkillProfile` mock fixture so the builder doesn't have to invent the shape mid-test. Provide a fixture stub.
- `DEFAULT_SCORE_THRESHOLDS` remains hardcoded — fine for MVP; mark as a follow-up to expose via config when domain-specific tuning is needed.

Ready for builder.
