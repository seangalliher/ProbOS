# Review: AD-566i — Role Skill Template Expansion

**Verdict:** ✅ Approved
**Headline:** Template structure correct; 7 new roles match existing domain/decay conventions.

## Required

None.

## Recommended

1. Domain consistency in tests — assert against a whitelist (or enum) so typos like `"medicl"` or `"enginnering"` fail loudly.
2. Document the 14-role complete fleet roster in PROGRESS.md after this lands so future audits have a quick reference.

## Nits

- Verified-Against-Codebase section references line 530; cross-reference line 392 (`SkillRegistry.initialize_agent_skills` loop) too — both use `ROLE_SKILL_TEMPLATES`.

## Verified

- `ROLE_SKILL_TEMPLATES` at [skill_framework.py:225](src/probos/skill_framework.py#L225).
- 7 existing roles: security_officer, engineering_officer, operations_officer, diagnostician, scout, counselor, architect.
- `SkillDefinition` at [skill_framework.py:55](src/probos/skill_framework.py#L55).
- Template iteration at [skill_framework.py:392](src/probos/skill_framework.py#L392) and [line 530](src/probos/skill_framework.py#L530).
- Decay rates and domains match existing patterns (science=7d, medical/ops=14d).
