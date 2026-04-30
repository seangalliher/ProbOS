# AD-566i Role Skill Template Expansion Build Report

**Date:** 2026-04-30
**Status:** Complete
**Prompt:** `prompts/ad-566i-role-skill-template-expansion.md`

## Summary

Expanded `ROLE_SKILL_TEMPLATES` so all 14 fleet roles have role-specific skill templates. The new builder, medical, and science roles each receive exactly 3 role skills with prerequisite chains, department-matched domains, and the specified decay-rate pattern.

Existing role templates, PCC skills, `SkillRegistry` initialization logic, `SkillDefinition`, skill categories, tool preferences, and qualification requirements were not changed.

## Files Changed

- `src/probos/skill_framework.py`
  - Added role skill templates for `builder`, `surgeon`, `pharmacist`, `pathologist`, `data_analyst`, `systems_analyst`, and `research_specialist`.
- `tests/test_ad566i_role_skill_template_expansion.py`
  - Added 5 focused tests for roster completeness, new-role skill count, prerequisite validity, domain assignments, and decay rates.
- `PROGRESS.md`, `docs/development/roadmap.md`
  - Updated AD-566i tracking.

## Sections Implemented

- `### Section 1: Add missing role templates`
  - Implemented in `src/probos/skill_framework.py`.
- `## Tests`
  - Implemented in `tests/test_ad566i_role_skill_template_expansion.py`.
- `## Tracking`
  - Updated `PROGRESS.md`, `docs/development/roadmap.md`, and this build report.

## Post-Build Section Audit

- `### Section 1: Add missing role templates` — complete; all 7 missing roles were added with 3 skills each, prerequisite chains, role category, role origin, department domains, and specified decay rates.
- `## Tests` — complete; 5 focused tests added.
- `## Tracking` — complete; tracker and build report updates added.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad566i_role_skill_template_expansion.py -v -n 0`
  - Result: 5 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_skill_framework.py tests/test_ontology_skills.py tests/test_cognitive_agent_skills.py -v -n 0`
  - Result: 58 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
  - Result: 10096 passed, 17 skipped.

## Deviations

- None.
