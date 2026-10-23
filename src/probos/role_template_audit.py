"""BF-917 (#1625) and BF-915 (#1623): the role templates audited against the skill catalog and the crew posts.

Pure functions over what ``OntologyLoader`` loads. ``probos doctor``'s
``role_templates`` check reports what they find, and the tests run them over the
shipped ``config/ontology``, so a template that names a skill no definition
registers fails CI before a vessel boots it. They read; they never write.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def unregistered_template_skills(
    role_templates: Mapping[str, Any], registered: frozenset[str],
) -> tuple[tuple[str, str], ...]:
    """Each ``(post_id, skill_id)`` a template requires or offers that no registered definition has, sorted."""
    missing = {
        (post_id, req.skill_id)
        for post_id, template in role_templates.items()
        for req in [*template.required_skills, *template.optional_skills]
        if req.skill_id not in registered
    }
    return tuple(sorted(missing))


def crew_posts_without_template(
    posts: Mapping[str, Any], assignments: Iterable[Any], role_templates: Mapping[str, Any],
) -> tuple[tuple[str, str], ...]:
    """BF-915: each ``(post_id, agent_type)`` assigned to a crew-tier post that has no role template, sorted.

    A crew-tier post with no assignment is not reported: no agent is commissioned under it.
    """
    gaps = {
        (assignment.post_id, assignment.agent_type)
        for assignment in assignments
        if (post := posts.get(assignment.post_id)) is not None and post.tier == "crew"
        and assignment.post_id not in role_templates
    }
    return tuple(sorted(gaps))
