"""DepartmentService — organization structure queries and agent wiring."""

from __future__ import annotations

from probos.ontology.models import Assignment, Department, Post


class DepartmentService:
    """Queries and mutations for departments, posts, and agent assignments."""

    def __init__(
        self,
        departments: dict[str, Department],
        posts: dict[str, Post],
        assignments: dict[str, Assignment],
    ) -> None:
        self._departments = departments
        self._posts = posts
        self._assignments = assignments

    def get_departments(self) -> list[Department]:
        """Return all departments."""
        return list(self._departments.values())

    def get_department(self, dept_id: str) -> Department | None:
        """Return a department by ID."""
        return self._departments.get(dept_id)

    def get_posts(self, department_id: str | None = None) -> list[Post]:
        """Return posts, optionally filtered by department."""
        if department_id:
            return [p for p in self._posts.values() if p.department_id == department_id]
        return list(self._posts.values())

    def get_post(self, post_id: str) -> Post | None:
        """Return a post by ID."""
        return self._posts.get(post_id)

    def get_chain_of_command(self, post_id: str) -> list[Post]:
        """Walk reports_to chain from post up to captain. Returns [self, ..., captain]."""
        chain: list[Post] = []
        visited: set[str] = set()
        current_id: str | None = post_id
        while current_id and current_id not in visited:
            visited.add(current_id)
            post = self._posts.get(current_id)
            if post is None:
                break
            chain.append(post)
            current_id = post.reports_to
        return chain

    def get_direct_reports(self, post_id: str) -> list[Post]:
        """Posts that report to this post."""
        return [p for p in self._posts.values() if p.reports_to == post_id]

    def get_all_assignments(self) -> list[Assignment]:
        """Return all crew assignments."""
        return list(self._assignments.values())

    def get_assignment_for_agent(self, agent_type: str) -> Assignment | None:
        """Return assignment for an agent_type."""
        return self._assignments.get(agent_type)

    def get_agent_department(self, agent_type: str) -> str | None:
        """Return department_id for an agent_type."""
        assignment = self._assignments.get(agent_type)
        if not assignment:
            return None
        post = self._posts.get(assignment.post_id)
        if not post:
            return None
        return post.department_id

    def get_crew_agent_types(self) -> set[str]:
        """Return set of agent_types assigned to crew-tier posts."""
        result: set[str] = set()
        for agent_type, assignment in self._assignments.items():
            post = self._posts.get(assignment.post_id)
            if post and post.tier == "crew":
                result.add(agent_type)
        return result

    def get_post_for_agent(self, agent_type: str) -> Post | None:
        """Return the Post that an agent_type is assigned to."""
        assignment = self._assignments.get(agent_type)
        if not assignment:
            return None
        return self._posts.get(assignment.post_id)

    def wire_agent(self, agent_type: str, agent_id: str) -> None:
        """Associate a runtime agent_id with its post assignment."""
        assignment = self._assignments.get(agent_type)
        if assignment:
            assignment.agent_id = agent_id

    def update_assignment_callsign(self, agent_type: str, new_callsign: str) -> bool:
        """Update the callsign on an agent's Assignment after naming ceremony (BF-049)."""
        assignment = self._assignments.get(agent_type)
        if not assignment:
            return False
        self._assignments[agent_type] = Assignment(
            agent_type=assignment.agent_type,
            post_id=assignment.post_id,
            callsign=new_callsign,
            agent_id=assignment.agent_id,
        )
        return True

    def get_assignment_for_agent_by_id(self, agent_id: str) -> Assignment | None:
        """Find assignment by runtime agent_id (set via wire_agent)."""
        for a in self._assignments.values():
            if a.agent_id == agent_id:
                return a
        return None

    def get_agents_for_post(self, post_id: str) -> list[Assignment]:
        """AD-630: Return all agent assignments for a given post_id.

        Typically returns one assignment, but the model allows multiple
        agents assigned to the same billet.

        Args:
            post_id: The post identifier from organization.yaml.

        Returns:
            List of Assignment objects with matching post_id.
        """
        return [a for a in self._assignments.values() if a.post_id == post_id]
