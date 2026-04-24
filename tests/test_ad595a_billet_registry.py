"""Tests for AD-595a: BilletRegistry — billet resolution + events."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from probos.events import EventType
from probos.ontology.models import Post, Assignment, Department
from probos.ontology.departments import DepartmentService
from probos.ontology.billet_registry import BilletRegistry, BilletHolder


# --- Fixtures ---

@pytest.fixture
def dept_service():
    """Create a DepartmentService with test departments, posts, and assignments."""
    departments = {
        "engineering": Department(id="engineering", name="Engineering", description=""),
        "science": Department(id="science", name="Science", description=""),
    }
    posts = {
        "chief_engineer": Post(
            id="chief_engineer",
            title="Chief Engineer",
            department_id="engineering",
            reports_to="first_officer",
            tier="crew",
        ),
        "engineering_officer": Post(
            id="engineering_officer",
            title="Engineering Officer",
            department_id="engineering",
            reports_to="chief_engineer",
            tier="crew",
        ),
        "chief_science": Post(
            id="chief_science",
            title="Chief Science Officer",
            department_id="science",
            reports_to="first_officer",
            tier="crew",
        ),
        "vacant_post": Post(
            id="vacant_post",
            title="Vacant Post",
            department_id="science",
            reports_to="chief_science",
            tier="crew",
        ),
    }
    assignments = {
        "engineer": Assignment(
            agent_type="engineer",
            post_id="chief_engineer",
            callsign="LaForge",
            agent_id="agent-eng-001",
        ),
        "engineering_officer": Assignment(
            agent_type="engineering_officer",
            post_id="engineering_officer",
            callsign="Torres",
            agent_id="agent-eng-002",
        ),
        "number_one": Assignment(
            agent_type="number_one",
            post_id="chief_science",
            callsign="Meridian",
            agent_id="agent-sci-001",
        ),
        # vacant_post has no assignment
    }
    return DepartmentService(departments, posts, assignments)


@pytest.fixture
def registry(dept_service):
    """BilletRegistry with mock event emitter."""
    mock_emit = MagicMock()
    return BilletRegistry(dept_service, emit_event_fn=mock_emit)


# --- Resolution tests ---

class TestBilletResolution:

    def test_resolve_by_post_id(self, registry):
        """Resolve by post_id returns correct holder."""
        result = registry.resolve("chief_engineer")
        assert result is not None
        assert result.billet_id == "chief_engineer"
        assert result.title == "Chief Engineer"
        assert result.holder_callsign == "LaForge"
        assert result.holder_agent_type == "engineer"

    def test_resolve_by_title(self, registry):
        """Resolve by title (case-insensitive) returns correct holder."""
        result = registry.resolve("Chief Engineer")
        assert result is not None
        assert result.holder_callsign == "LaForge"

    def test_resolve_by_title_case_insensitive(self, registry):
        """Title resolution is case-insensitive."""
        result = registry.resolve("chief engineer")
        assert result is not None
        assert result.holder_callsign == "LaForge"

    def test_resolve_vacant_billet(self, registry):
        """Vacant billet returns BilletHolder with None holder fields."""
        result = registry.resolve("vacant_post")
        assert result is not None
        assert result.billet_id == "vacant_post"
        assert result.holder_agent_type is None
        assert result.holder_callsign is None
        assert result.holder_agent_id is None

    def test_resolve_nonexistent_billet(self, registry):
        """Nonexistent billet returns None."""
        result = registry.resolve("nonexistent")
        assert result is None

    def test_resolve_agent_type(self, registry):
        """Convenience method returns just the agent_type."""
        assert registry.resolve_agent_type("Chief Engineer") == "engineer"

    def test_resolve_callsign(self, registry):
        """Convenience method returns just the callsign."""
        assert registry.resolve_callsign("Chief Engineer") == "LaForge"

    def test_resolve_agent_type_nonexistent(self, registry):
        """Convenience returns None for unknown billet."""
        assert registry.resolve_agent_type("nonexistent") is None


# --- Roster tests ---

class TestBilletRoster:

    def test_get_roster_returns_all_billets(self, registry):
        """Full roster includes all billets."""
        roster = registry.get_roster()
        assert len(roster) == 4
        ids = {b.billet_id for b in roster}
        assert "chief_engineer" in ids
        assert "vacant_post" in ids

    def test_get_roster_includes_vacant(self, registry):
        """Roster includes vacant billets with None holder."""
        roster = registry.get_roster()
        vacant = next(b for b in roster if b.billet_id == "vacant_post")
        assert vacant.holder_agent_type is None

    def test_get_department_roster(self, registry):
        """Department roster filters correctly."""
        eng_roster = registry.get_department_roster("engineering")
        assert len(eng_roster) == 2
        assert all(b.department == "engineering" for b in eng_roster)

    def test_get_department_roster_empty(self, registry):
        """Empty department returns empty list."""
        assert registry.get_department_roster("nonexistent") == []


# --- Event tests ---

class TestBilletEvents:

    def test_set_event_callback(self, dept_service):
        """set_event_callback wires the callback."""
        reg = BilletRegistry(dept_service)
        mock_emit = MagicMock()
        reg.set_event_callback(mock_emit)
        assert reg._emit_event_fn is mock_emit

    def test_no_crash_without_callback(self, dept_service):
        """No crash when emit_event_fn is None."""
        reg = BilletRegistry(dept_service, emit_event_fn=None)
        # _emit should not raise
        reg._emit(EventType.BILLET_ASSIGNED, {"test": True})


# --- BilletHolder dataclass ---

class TestBilletHolder:

    def test_billet_holder_fields(self):
        """BilletHolder has expected fields."""
        bh = BilletHolder(
            billet_id="test",
            title="Test",
            department="eng",
            holder_agent_type="agent",
            holder_callsign="Name",
            holder_agent_id="id-1",
        )
        assert bh.billet_id == "test"
        assert bh.holder_callsign == "Name"

    def test_billet_holder_is_frozen(self):
        """BilletHolder is immutable (frozen dataclass)."""
        bh = BilletHolder(
            billet_id="test",
            title="Test",
            department="eng",
            holder_agent_type="agent",
            holder_callsign="Name",
            holder_agent_id="id-1",
        )
        with pytest.raises(AttributeError):
            bh.holder_callsign = "Changed"


# --- Refresh ---

class TestBilletRefresh:

    def test_refresh_rebuilds_title_index(self, dept_service):
        """refresh() rebuilds the title index from current posts."""
        reg = BilletRegistry(dept_service)
        # Title index should already work
        assert reg.resolve("Chief Engineer") is not None
        # Simulate a new post being added to the underlying service
        dept_service._posts["new_post"] = Post(
            id="new_post",
            title="New Post",
            department_id="engineering",
            reports_to="chief_engineer",
            tier="crew",
        )
        # Before refresh, title resolution doesn't find the new post
        assert reg.resolve("New Post") is None
        # After refresh, it does
        reg.refresh()
        assert reg.resolve("New Post") is not None
        assert reg.resolve("New Post").billet_id == "new_post"
