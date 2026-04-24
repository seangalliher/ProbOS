"""Tests for AD-595d: Qualification-aware billet assignment."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock

from probos.ontology.models import Post


# --- Post dataclass tests ---

class TestPostQualifications:

    def test_required_qualifications_field_exists(self):
        """AD-595d: Post has required_qualifications field."""
        post = Post(id="chief_engineer", title="Chief Engineer", department_id="engineering", reports_to=None)
        assert hasattr(post, 'required_qualifications')
        assert post.required_qualifications == []

    def test_required_qualifications_populated(self):
        """AD-595d: required_qualifications can be populated."""
        post = Post(
            id="chief_engineer",
            title="Chief Engineer",
            department_id="engineering",
            reports_to=None,
            required_qualifications=["bfi2_personality_probe", "episodic_recall_probe"],
        )
        assert len(post.required_qualifications) == 2
        assert "bfi2_personality_probe" in post.required_qualifications

    def test_backwards_compatible(self):
        """AD-595d: Existing Posts without qualifications still work."""
        post = Post(id="sensor_op", title="Sensor Operator", department_id="science", reports_to="chief_science_officer")
        assert post.required_qualifications == []


# --- Helper factories ---

def _make_mock_dept(posts: dict[str, Post] | None = None):
    """Create mock DepartmentService with given posts."""
    dept = MagicMock()
    if posts:
        dept.get_post = MagicMock(side_effect=lambda pid: posts.get(pid))
    else:
        dept.get_post = MagicMock(return_value=None)
    dept.get_posts = MagicMock(return_value=list((posts or {}).values()))
    dept.get_agents_for_post = MagicMock(return_value=[])
    dept.get_assignment_for_agent = MagicMock(return_value=None)
    dept.update_assignment_callsign = MagicMock()
    return dept


def _make_mock_qual_store(results: dict[str, bool | None]):
    """Create mock QualificationStore.

    results: {test_name: passed_bool_or_None}.
    None means no test result exists (get_latest returns None).
    True/False means test exists with that passed value.
    """
    store = MagicMock()

    async def _get_latest(agent_id: str, test_name: str):
        if test_name not in results:
            return None
        val = results[test_name]
        if val is None:
            return None
        result = MagicMock()
        result.passed = val
        return result

    store.get_latest = AsyncMock(side_effect=_get_latest)
    return store


def _make_assignment(agent_id: str = "agent-001"):
    """Create a mock Assignment with agent_id."""
    assignment = MagicMock()
    assignment.agent_id = agent_id
    assignment.callsign = ""
    return assignment


# --- Qualification checking tests ---

class TestCheckQualifications:

    @pytest.mark.asyncio
    async def test_no_requirements_passes(self):
        """Agent qualifies for billet with no requirements."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(id="sensor_op", title="Sensor Op", department_id="science", reports_to=None)
        dept = _make_mock_dept({"sensor_op": post})
        store = _make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("sensor_op", "data_analyst", "agent-001")
        assert qualified
        assert missing == []

    @pytest.mark.asyncio
    async def test_all_qualifications_passed(self):
        """Agent with all qualifications passes."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe", "episodic_recall_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({
            "bfi2_personality_probe": True,
            "episodic_recall_probe": True,
        })

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "agent-001")
        assert qualified
        assert missing == []

    @pytest.mark.asyncio
    async def test_missing_qualification_allow_untested(self):
        """Untested qualification allowed when allow_untested=True (cold start)."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe", "episodic_recall_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({
            "bfi2_personality_probe": True,
            # episodic_recall_probe: no result exists
        })

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications(
            "chief_engineer", "engineer", "agent-001", allow_untested=True,
        )
        assert qualified
        assert missing == []

    @pytest.mark.asyncio
    async def test_missing_qualification_disallow_untested(self):
        """Untested qualification fails when allow_untested=False (promotion)."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe", "episodic_recall_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({
            "bfi2_personality_probe": True,
            # episodic_recall_probe: no result exists
        })

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications(
            "chief_engineer", "engineer", "agent-001", allow_untested=False,
        )
        assert not qualified
        assert "episodic_recall_probe" in missing

    @pytest.mark.asyncio
    async def test_failed_qualification(self):
        """Agent who failed a test doesn't qualify."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({"bfi2_personality_probe": False})

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "agent-001")
        assert not qualified
        assert "bfi2_personality_probe" in missing

    @pytest.mark.asyncio
    async def test_no_store_passes_by_default(self):
        """Without qualification store, agent qualifies by default."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})

        reg = BilletRegistry(dept)  # No qualification_store
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "agent-001")
        assert qualified

    @pytest.mark.asyncio
    async def test_no_agent_id_passes_by_default(self):
        """Without agent_id and no assignment, qualification check passes."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "")
        assert qualified

    @pytest.mark.asyncio
    async def test_agent_type_resolves_agent_id(self):
        """agent_type is used to look up agent_id when not provided."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        # Return an assignment so agent_id resolves
        dept.get_assignment_for_agent = MagicMock(return_value=_make_assignment("agent-001"))
        store = _make_mock_qual_store({"bfi2_personality_probe": True})

        reg = BilletRegistry(dept, qualification_store=store)
        # Pass empty agent_id — should resolve from assignment
        qualified, missing = await reg.check_qualifications("chief_engineer", "engineer", "")
        assert qualified
        store.get_latest.assert_called_once_with("agent-001", "bfi2_personality_probe")

    @pytest.mark.asyncio
    async def test_unknown_billet_passes(self):
        """Unknown billet returns qualified (nothing to check)."""
        from probos.ontology.billet_registry import BilletRegistry

        dept = _make_mock_dept({})
        store = _make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications("unknown", "engineer", "agent-001")
        assert qualified

    @pytest.mark.asyncio
    async def test_cold_start_all_untested_passes(self):
        """Cold start: all qualifications untested, allow_untested=True → passes."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe", "episodic_recall_probe", "confab_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        # All return None — no tests taken yet
        store = _make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications(
            "chief_engineer", "engineer", "agent-001", allow_untested=True,
        )
        assert qualified
        assert missing == []

    @pytest.mark.asyncio
    async def test_cold_start_all_untested_fails_strict(self):
        """Strict mode: all qualifications untested → fails."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe", "episodic_recall_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        qualified, missing = await reg.check_qualifications(
            "chief_engineer", "engineer", "agent-001", allow_untested=False,
        )
        assert not qualified
        assert len(missing) == 2


# --- assign_qualified tests ---

class TestAssignQualified:

    @pytest.mark.asyncio
    async def test_qualified_agent_assigned(self):
        """Qualified agent gets assigned via assign_qualified."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = MagicMock()
        store.get_latest = AsyncMock(return_value=MagicMock(passed=True))

        reg = BilletRegistry(dept, qualification_store=store)
        assigned, missing = await reg.assign_qualified("chief_engineer", "engineer", "agent-001", callsign="LaForge")
        assert assigned
        assert missing == []

    @pytest.mark.asyncio
    async def test_unqualified_agent_rejected(self):
        """Unqualified agent is rejected by assign_qualified."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = MagicMock()
        store.get_latest = AsyncMock(return_value=None)  # No test taken

        reg = BilletRegistry(dept, qualification_store=store)
        # allow_untested=False → strict mode → untested = missing
        assigned, missing = await reg.assign_qualified(
            "chief_engineer", "engineer", "agent-001", allow_untested=False,
        )
        assert not assigned
        assert "bfi2_personality_probe" in missing

    @pytest.mark.asyncio
    async def test_unqualified_agent_not_assigned(self):
        """Rejected agent does not emit assignment event."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = MagicMock()
        store.get_latest = AsyncMock(return_value=MagicMock(passed=False))
        events: list[tuple] = []

        reg = BilletRegistry(
            dept,
            emit_event_fn=lambda et, d: events.append((et, d)),
            qualification_store=store,
        )
        assigned, missing = await reg.assign_qualified(
            "chief_engineer", "engineer", "agent-001", callsign="LaForge",
        )

        assert not assigned
        assert missing == ["bfi2_personality_probe"]
        assert events == []

    @pytest.mark.asyncio
    async def test_assign_unconditional(self):
        """assign() does not check qualifications — always assigns."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        # Even with qualifications required, assign() doesn't check
        reg = BilletRegistry(dept)  # No store at all
        result = reg.assign("chief_engineer", "engineer", callsign="LaForge")
        assert result

    @pytest.mark.asyncio
    async def test_assign_qualified_cold_start_allows_untested(self):
        """Cold start: assign_qualified with allow_untested=True succeeds."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = MagicMock()
        store.get_latest = AsyncMock(return_value=None)  # No test results

        reg = BilletRegistry(dept, qualification_store=store)
        assigned, missing = await reg.assign_qualified(
            "chief_engineer", "engineer", "agent-001",
            callsign="LaForge", allow_untested=True,  # default
        )
        assert assigned
        assert missing == []

    @pytest.mark.asyncio
    async def test_no_requirements_always_assigns(self):
        """Billet with no requirements always assigns via assign_qualified."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="sensor_op", title="Sensor Op",
            department_id="science", reports_to=None,
            # No required_qualifications
        )
        dept = _make_mock_dept({"sensor_op": post})
        store = _make_mock_qual_store({})

        reg = BilletRegistry(dept, qualification_store=store)
        assigned, missing = await reg.assign_qualified("sensor_op", "data_analyst", "agent-001")
        assert assigned
        assert missing == []


# --- set_qualification_store tests ---

class TestSetQualificationStore:

    def test_set_qualification_store(self):
        """set_qualification_store() sets the store."""
        from probos.ontology.billet_registry import BilletRegistry

        dept = _make_mock_dept({})
        reg = BilletRegistry(dept)
        assert reg._qualification_store is None

        store = MagicMock()
        reg.set_qualification_store(store)
        assert reg._qualification_store is store

    @pytest.mark.asyncio
    async def test_late_bound_store_works(self):
        """Store wired after construction works for qualification checks."""
        from probos.ontology.billet_registry import BilletRegistry

        post = Post(
            id="chief_engineer", title="Chief Engineer",
            department_id="engineering", reports_to=None,
            required_qualifications=["bfi2_personality_probe"],
        )
        dept = _make_mock_dept({"chief_engineer": post})
        store = _make_mock_qual_store({"bfi2_personality_probe": True})

        reg = BilletRegistry(dept)  # No store at construction
        # Check before store — should pass (no store = allow)
        q1, _ = await reg.check_qualifications("chief_engineer", "engineer", "agent-001")
        assert q1

        # Wire store
        reg.set_qualification_store(store)
        # Check after store — should pass (test passed)
        q2, _ = await reg.check_qualifications("chief_engineer", "engineer", "agent-001")
        assert q2