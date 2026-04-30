# AD-566i: Role Skill Template Expansion

**Status:** Ready for builder
**Dependencies:** None
**Estimated tests:** ~5

---

## Problem

`ROLE_SKILL_TEMPLATES` in `skill_framework.py` (line 225) defines role-specific
skills for 7 roles: security_officer, engineering_officer, operations_officer,
diagnostician, scout, counselor, architect. But the fleet has additional
roles with no skill templates: builder, surgeon, pharmacist, pathologist,
data_analyst, systems_analyst, research_specialist.

These roles exist in `config/ontology/organization.yaml` and have pools
registered in `startup/fleet_organization.py`, but when
`SkillRegistry.initialize_agent_skills()` (line 530) looks up role templates,
it finds nothing and skips skill initialization.

## Fix

### Section 1: Add missing role templates

**File:** `src/probos/skill_framework.py`

Add after the `architect` block (line 262), before the closing `}`:

```python
    "builder": [
        SkillDefinition(skill_id="component_integration", name="Component Integration", category=SkillCategory.ROLE, domain="engineering", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="build_automation", name="Build Automation", category=SkillCategory.ROLE, domain="engineering", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="code_generation", name="Code Generation", category=SkillCategory.ROLE, domain="engineering", prerequisites=["component_integration"], decay_rate_days=14, origin="role"),
    ],
    "surgeon": [
        SkillDefinition(skill_id="surgical_precision", name="Surgical Precision", category=SkillCategory.ROLE, domain="medical", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="crisis_response", name="Crisis Response", category=SkillCategory.ROLE, domain="medical", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="system_repair", name="System Repair", category=SkillCategory.ROLE, domain="medical", prerequisites=["surgical_precision", "crisis_response"], decay_rate_days=14, origin="role"),
    ],
    "pharmacist": [
        SkillDefinition(skill_id="intervention_management", name="Intervention Management", category=SkillCategory.ROLE, domain="medical", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="interaction_analysis", name="Interaction Analysis", category=SkillCategory.ROLE, domain="medical", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="compliance_review", name="Compliance Review", category=SkillCategory.ROLE, domain="medical", prerequisites=["intervention_management"], decay_rate_days=14, origin="role"),
    ],
    "pathologist": [
        SkillDefinition(skill_id="system_analysis", name="System Analysis", category=SkillCategory.ROLE, domain="medical", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="failure_identification", name="Failure Identification", category=SkillCategory.ROLE, domain="medical", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="research_methodology", name="Research Methodology", category=SkillCategory.ROLE, domain="medical", prerequisites=["system_analysis"], decay_rate_days=14, origin="role"),
    ],
    "data_analyst": [
        SkillDefinition(skill_id="data_visualization", name="Data Visualization", category=SkillCategory.ROLE, domain="science", decay_rate_days=7, origin="role"),
        SkillDefinition(skill_id="statistical_analysis", name="Statistical Analysis", category=SkillCategory.ROLE, domain="science", decay_rate_days=7, origin="role"),
        SkillDefinition(skill_id="trend_identification", name="Trend Identification", category=SkillCategory.ROLE, domain="science", prerequisites=["statistical_analysis"], decay_rate_days=7, origin="role"),
    ],
    "systems_analyst": [
        SkillDefinition(skill_id="requirements_analysis", name="Requirements Analysis", category=SkillCategory.ROLE, domain="science", decay_rate_days=7, origin="role"),
        SkillDefinition(skill_id="process_optimization", name="Process Optimization", category=SkillCategory.ROLE, domain="science", decay_rate_days=7, origin="role"),
        SkillDefinition(skill_id="integration_testing", name="Integration Testing", category=SkillCategory.ROLE, domain="science", prerequisites=["requirements_analysis"], decay_rate_days=7, origin="role"),
    ],
    "research_specialist": [
        SkillDefinition(skill_id="literature_review", name="Literature Review", category=SkillCategory.ROLE, domain="science", decay_rate_days=7, origin="role"),
        SkillDefinition(skill_id="hypothesis_testing", name="Hypothesis Testing", category=SkillCategory.ROLE, domain="science", decay_rate_days=7, origin="role"),
        SkillDefinition(skill_id="experimental_design", name="Experimental Design", category=SkillCategory.ROLE, domain="science", prerequisites=["hypothesis_testing"], decay_rate_days=7, origin="role"),
    ],
```

**Pattern notes:**
- Medical roles use `decay_rate_days=14` (standard)
- Science roles use `decay_rate_days=7` (matches scout pattern for faster refresh)
- Each role gets 3 skills with at least one prerequisite chain
- All use `category=SkillCategory.ROLE`, `origin="role"`

## Tests

**File:** `tests/test_ad566i_role_skill_template_expansion.py`

5 tests:

1. `test_all_roles_have_templates` — verify ROLE_SKILL_TEMPLATES has entries
   for all 14 roles: security_officer, engineering_officer, operations_officer,
   diagnostician, scout, counselor, architect, builder, surgeon, pharmacist,
   pathologist, data_analyst, systems_analyst, research_specialist
2. `test_new_role_skill_count` — verify each new role has exactly 3 skills
3. `test_new_role_prerequisite_chains` — verify each new role has at least
   one skill with prerequisites, and prerequisites reference valid skill_ids
   within the same role
4. `test_new_role_domains_match` — verify medical roles (surgeon, pharmacist,
   pathologist) have domain="medical", science roles (data_analyst,
   systems_analyst, research_specialist) have domain="science", engineering
   roles (builder) have domain="engineering"
5. `test_new_role_decay_rates` — verify science roles use decay_rate_days=7,
   others use 14

## What This Does NOT Change

- Existing 7 role templates unchanged
- PCC skills unchanged
- SkillRegistry initialization logic unchanged (it already iterates ROLE_SKILL_TEMPLATES)
- SkillDefinition dataclass unchanged
- Does NOT add new SkillCategory values
- Does NOT add ToolPreference entries for new skills (future enhancement)
- Does NOT modify qualification requirements

## Tracking

- `PROGRESS.md`: Add AD-566i as COMPLETE
- `docs/development/roadmap.md`: Update AD-566i status

## Acceptance Criteria

- All 14 fleet roles have skill templates in ROLE_SKILL_TEMPLATES
- Each new role has 3 skills with prerequisite chains
- Domain assignments match department (medical/science/engineering)
- Decay rates follow existing patterns (14 standard, 7 for science)
- All 5 new tests pass
- Full test gate: `pytest tests/ -q -n auto` — no regressions
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`

## Verified Against Codebase (2026-04-29)

```
# Current ROLE_SKILL_TEMPLATES
grep -n "ROLE_SKILL_TEMPLATES" src/probos/skill_framework.py
  225: ROLE_SKILL_TEMPLATES: dict[str, list[SkillDefinition]]

# Existing roles (7)
grep -c "]:$" src/probos/skill_framework.py  # within ROLE_SKILL_TEMPLATES block
  security_officer, engineering_officer, operations_officer,
  diagnostician, scout, counselor, architect

# Missing roles (from fleet_organization.py pool registrations)
grep "pool_names=" src/probos/startup/fleet_organization.py
  → builder, medical_surgeon, medical_pharmacist, medical_pathologist,
    science_data_analyst, science_systems_analyst, science_research_specialist

# SkillRegistry reads templates at initialization
grep -n "ROLE_SKILL_TEMPLATES" src/probos/skill_framework.py
  392: for role_skills in ROLE_SKILL_TEMPLATES.values()
  530: role_skills = ROLE_SKILL_TEMPLATES.get(agent_type, [])
```
