"""RankService — promotion and qualification queries."""

from __future__ import annotations

from typing import Any

from probos.ontology.models import Assignment, QualificationPath, RoleTemplate


class RankService:
    """Queries for role templates and qualification paths."""

    def __init__(
        self,
        role_templates: dict[str, RoleTemplate],
        qualification_paths: dict[str, QualificationPath],
        assignments: dict[str, Assignment],
    ) -> None:
        self._role_templates = role_templates
        self._qualification_paths = qualification_paths
        self._assignments = assignments
        self._skill_service: Any = None

    def get_role_template(self, post_id: str) -> RoleTemplate | None:
        """Get the skill requirements for a post."""
        return self._role_templates.get(post_id)

    def get_role_template_for_agent(self, agent_type: str) -> RoleTemplate | None:
        """Get the role template for an agent's assigned post."""
        assignment = self._assignments.get(agent_type)
        if not assignment:
            return None
        return self._role_templates.get(assignment.post_id)

    def get_qualification_path(self, from_rank: str, to_rank: str) -> QualificationPath | None:
        """Get the qualification requirements for a rank transition."""
        key = f"{from_rank}_to_{to_rank}"
        return self._qualification_paths.get(key)

    def get_all_qualification_paths(self) -> list[QualificationPath]:
        """Get all defined qualification paths."""
        return list(self._qualification_paths.values())

    def set_skill_service(self, skill_service: Any) -> None:
        """Set reference to AgentSkillService for skill context queries."""
        self._skill_service = skill_service
