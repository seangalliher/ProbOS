"""BF-917 (#1625): the role templates audited against the skill catalog.

Pure functions over what ``OntologyLoader`` loads. ``probos doctor``'s
``role_templates`` check reports what they find, and the tests run them over the
shipped ``config/ontology``, so a template that names a skill no definition
registers fails CI before a vessel boots it. They read; they never write.
"""

from __future__ import annotations

from collections.abc import Mapping
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
