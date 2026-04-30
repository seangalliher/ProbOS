from __future__ import annotations

from probos.skill_framework import ROLE_SKILL_TEMPLATES, SkillCategory


ALL_ROLES = {
    "security_officer",
    "engineering_officer",
    "operations_officer",
    "diagnostician",
    "scout",
    "counselor",
    "architect",
    "builder",
    "surgeon",
    "pharmacist",
    "pathologist",
    "data_analyst",
    "systems_analyst",
    "research_specialist",
}

NEW_ROLES = {
    "builder",
    "surgeon",
    "pharmacist",
    "pathologist",
    "data_analyst",
    "systems_analyst",
    "research_specialist",
}

EXPECTED_DOMAINS = {
    "builder": "engineering",
    "surgeon": "medical",
    "pharmacist": "medical",
    "pathologist": "medical",
    "data_analyst": "science",
    "systems_analyst": "science",
    "research_specialist": "science",
}

SCIENCE_ROLES = {"data_analyst", "systems_analyst", "research_specialist"}
VALID_DOMAINS = {"engineering", "medical", "science"}


def test_all_roles_have_templates() -> None:
    assert ALL_ROLES.issubset(ROLE_SKILL_TEMPLATES)


def test_new_role_skill_count() -> None:
    for role in NEW_ROLES:
        assert len(ROLE_SKILL_TEMPLATES[role]) == 3
        assert all(skill.category is SkillCategory.ROLE for skill in ROLE_SKILL_TEMPLATES[role])
        assert all(skill.origin == "role" for skill in ROLE_SKILL_TEMPLATES[role])


def test_new_role_prerequisite_chains() -> None:
    for role in NEW_ROLES:
        skills = ROLE_SKILL_TEMPLATES[role]
        skill_ids = {skill.skill_id for skill in skills}

        prerequisite_skills = [skill for skill in skills if skill.prerequisites]

        assert prerequisite_skills
        for skill in prerequisite_skills:
            assert set(skill.prerequisites).issubset(skill_ids)


def test_new_role_domains_match() -> None:
    for role, expected_domain in EXPECTED_DOMAINS.items():
        skills = ROLE_SKILL_TEMPLATES[role]

        assert expected_domain in VALID_DOMAINS
        assert {skill.domain for skill in skills} == {expected_domain}


def test_new_role_decay_rates() -> None:
    for role in NEW_ROLES:
        expected_decay = 7 if role in SCIENCE_ROLES else 14

        assert {skill.decay_rate_days for skill in ROLE_SKILL_TEMPLATES[role]} == {expected_decay}
