"""Tests for AD-595b: Naming ceremony -> BilletRegistry integration."""

from __future__ import annotations

import dataclasses

from unittest.mock import MagicMock

from probos.cognitive.orientation import OrientationContext
from probos.events import EventType
from probos.ontology.billet_registry import BilletRegistry
from probos.ontology.models import Post, Assignment


# --- Fixtures ---

def _make_dept_service():
    """Create a minimal DepartmentService-like object with real data."""
    svc = MagicMock()
    posts = {
        "chief_engineer": Post(id="chief_engineer", title="Chief Engineer", department_id="engineering", reports_to="first_officer"),
        "chief_medical": Post(id="chief_medical", title="Chief Medical Officer", department_id="medical", reports_to="first_officer"),
    }
    assignments = {
        "engineer": Assignment(agent_type="engineer", post_id="chief_engineer", callsign="LaForge", agent_id="agent-001"),
    }
    svc.get_posts.return_value = list(posts.values())
    svc.get_post.side_effect = lambda pid: posts.get(pid)
    svc.get_post_for_agent.side_effect = lambda at: posts.get(assignments[at].post_id) if at in assignments else None
    svc.get_agents_for_post.side_effect = lambda pid: [a for a in assignments.values() if a.post_id == pid]
    svc.get_assignment_for_agent.side_effect = lambda at: assignments.get(at)
    return svc, posts, assignments


# --- BilletRegistry.assign() tests ---

class TestBilletRegistryAssign:

    def test_assign_emits_billet_assigned_event(self):
        """AD-595b: assign() emits BILLET_ASSIGNED with correct payload."""
        dept_svc, _, _ = _make_dept_service()
        events: list[tuple] = []
        registry = BilletRegistry(dept_svc, emit_event_fn=lambda et, d: events.append((et, d)))

        result = registry.assign("chief_engineer", "engineer", callsign="LaForge")

        assert result is True
        assert len(events) == 1
        et, data = events[0]
        assert et == EventType.BILLET_ASSIGNED
        assert data["billet_id"] == "chief_engineer"
        assert data["title"] == "Chief Engineer"
        assert data["department"] == "engineering"
        assert data["agent_type"] == "engineer"
        assert data["callsign"] == "LaForge"

    def test_assign_unknown_post_returns_false(self):
        """AD-595b: assign() returns False for non-existent post."""
        dept_svc, _, _ = _make_dept_service()
        events: list[tuple] = []
        registry = BilletRegistry(dept_svc, emit_event_fn=lambda et, d: events.append((et, d)))

        result = registry.assign("nonexistent_post", "engineer")

        assert result is False
        assert len(events) == 0

    def test_assign_idempotent(self):
        """AD-595b: assign() called twice emits twice (idempotent, no error)."""
        dept_svc, _, _ = _make_dept_service()
        events: list[tuple] = []
        registry = BilletRegistry(dept_svc, emit_event_fn=lambda et, d: events.append((et, d)))

        registry.assign("chief_engineer", "engineer", callsign="LaForge")
        registry.assign("chief_engineer", "engineer", callsign="LaForge")

        assert len(events) == 2  # Both succeed

    def test_assign_no_callback_no_crash(self):
        """AD-595b: assign() without event callback doesn't crash."""
        dept_svc, _, _ = _make_dept_service()
        registry = BilletRegistry(dept_svc, emit_event_fn=None)

        result = registry.assign("chief_engineer", "engineer")

        assert result is True  # Post exists, just no emission

    def test_assign_vacant_billet(self):
        """AD-595b: assign() works for billet with no prior holder."""
        dept_svc, _, _ = _make_dept_service()
        events: list[tuple] = []
        registry = BilletRegistry(dept_svc, emit_event_fn=lambda et, d: events.append((et, d)))

        result = registry.assign("chief_medical", "doctor", callsign="Bones")

        assert result is True
        assert events[0][1]["title"] == "Chief Medical Officer"

    def test_assign_empty_callsign_falls_back_to_assignment(self):
        """AD-595b: assign() with empty callsign looks up stored assignment callsign."""
        dept_svc, _, _ = _make_dept_service()
        events: list[tuple] = []
        registry = BilletRegistry(dept_svc, emit_event_fn=lambda et, d: events.append((et, d)))

        # engineer's assignment has callsign="LaForge" in the fixture
        result = registry.assign("chief_engineer", "engineer", callsign="")

        assert result is True
        assert events[0][1]["callsign"] == "LaForge"  # Fell back to assignment

    def test_assign_empty_callsign_no_assignment(self):
        """AD-595b: assign() with empty callsign and no assignment emits empty callsign."""
        dept_svc, _, _ = _make_dept_service()
        events: list[tuple] = []
        registry = BilletRegistry(dept_svc, emit_event_fn=lambda et, d: events.append((et, d)))

        # chief_medical has no assignment in the fixture
        result = registry.assign("chief_medical", "unknown_agent", callsign="")

        assert result is True
        assert events[0][1]["callsign"] == ""  # No assignment to fall back to


# --- OrientationContext tests ---

class TestOrientationContextBilletTitle:

    def test_billet_title_field_exists(self):
        """AD-595b: OrientationContext has billet_title field with empty default."""
        ctx = OrientationContext()
        assert ctx.billet_title == ""

    def test_billet_title_set_at_construction(self):
        """AD-595b: billet_title can be populated at construction."""
        ctx = OrientationContext(billet_title="Chief Engineer")
        assert ctx.billet_title == "Chief Engineer"

    def test_billet_title_via_dataclasses_replace(self):
        """AD-595b: billet_title can be set via dataclasses.replace (frozen)."""
        ctx = OrientationContext(post="chief_engineer")
        ctx2 = dataclasses.replace(ctx, billet_title="Chief Engineer")
        assert ctx2.billet_title == "Chief Engineer"
        assert ctx2.post == "chief_engineer"  # Other fields preserved


# --- Integration: billet title in orientation ---

class TestBilletTitleInOrientation:

    def test_resolve_provides_title_for_orientation(self):
        """AD-595b: BilletRegistry.resolve() returns title usable for orientation."""
        dept_svc, _, _ = _make_dept_service()
        registry = BilletRegistry(dept_svc)

        holder = registry.resolve("chief_engineer")
        assert holder is not None
        assert holder.title == "Chief Engineer"

        # Simulate what wire_agent does: enrich orientation
        ctx = OrientationContext(post="chief_engineer")
        ctx = dataclasses.replace(ctx, billet_title=holder.title)
        assert ctx.billet_title == "Chief Engineer"


# --- Onboarding setter ---

class TestOnboardingBilletRegistryWiring:

    def _make_onboarding_service(self):
        """Create AgentOnboardingService with all required kwargs mocked."""
        from probos.agent_onboarding import AgentOnboardingService
        from probos.config import SystemConfig

        return AgentOnboardingService(
            config=SystemConfig(),
            callsign_registry=MagicMock(),
            capability_registry=MagicMock(),
            gossip=MagicMock(),
            intent_bus=MagicMock(),
            trust_network=MagicMock(),
            event_log=MagicMock(),
            identity_registry=None,
            ontology=None,
            event_emitter=MagicMock(),
            llm_client=None,
            registry=MagicMock(),
            ward_room=None,
            acm=None,
        )

    def test_set_billet_registry(self):
        """AD-595b: AgentOnboardingService accepts billet registry via setter."""
        svc = self._make_onboarding_service()

        mock_reg = MagicMock()
        svc.set_billet_registry(mock_reg)
        assert svc._billet_registry is mock_reg

    def test_no_crash_without_billet_registry(self):
        """AD-595b: Onboarding works fine when billet_registry is None."""
        svc = self._make_onboarding_service()

        # _billet_registry is None by default
        assert svc._billet_registry is None
