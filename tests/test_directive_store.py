"""Tests for AD-386: Runtime Directive Overlays."""

import time
import unittest

from probos.crew_profile import Rank
from probos.directive_store import (
    DirectiveStatus,
    DirectiveStore,
    DirectiveType,
    RuntimeDirective,
    authorize_directive,
)


class TestRuntimeDirectiveRoundtrip(unittest.TestCase):
    def test_directive_to_dict_roundtrip(self) -> None:
        d = RuntimeDirective(
            id="abc-123",
            target_agent_type="builder",
            target_department="engineering",
            directive_type=DirectiveType.CAPTAIN_ORDER,
            content="Always run tests before committing",
            issued_by="captain",
            issued_by_department=None,
            authority=1.0,
            priority=5,
            status=DirectiveStatus.ACTIVE,
            created_at=1000.0,
            expires_at=2000.0,
            revoked_by=None,
            revoked_at=None,
        )
        data = d.to_dict()
        d2 = RuntimeDirective.from_dict(data)
        assert d2.id == d.id
        assert d2.target_agent_type == d.target_agent_type
        assert d2.target_department == d.target_department
        assert d2.directive_type == d.directive_type
        assert d2.content == d.content
        assert d2.issued_by == d.issued_by
        assert d2.authority == d.authority
        assert d2.priority == d.priority
        assert d2.status == d.status
        assert d2.created_at == d.created_at
        assert d2.expires_at == d.expires_at


class TestEnums(unittest.TestCase):
    def test_directive_type_enum(self) -> None:
        for dt in DirectiveType:
            assert isinstance(dt.value, str)
            assert DirectiveType(dt.value) == dt

    def test_directive_status_enum(self) -> None:
        for ds in DirectiveStatus:
            assert isinstance(ds.value, str)
            assert DirectiveStatus(ds.value) == ds


class TestAuthorizeDirective(unittest.TestCase):
    def test_authorize_captain_order(self) -> None:
        ok, reason = authorize_directive(
            "captain", None, Rank.SENIOR, "builder", "engineering", DirectiveType.CAPTAIN_ORDER
        )
        assert ok is True

    def test_authorize_captain_order_non_captain(self) -> None:
        ok, reason = authorize_directive(
            "builder", "engineering", Rank.SENIOR, "diagnostician", "medical", DirectiveType.CAPTAIN_ORDER
        )
        assert ok is False

    def test_authorize_counselor_guidance(self) -> None:
        ok, reason = authorize_directive(
            "counselor", "bridge", Rank.COMMANDER, "builder", "engineering", DirectiveType.COUNSELOR_GUIDANCE
        )
        assert ok is True

    def test_authorize_counselor_guidance_non_bridge(self) -> None:
        ok, reason = authorize_directive(
            "builder", "engineering", Rank.COMMANDER, "diagnostician", "medical", DirectiveType.COUNSELOR_GUIDANCE
        )
        assert ok is False

    def test_authorize_chief_directive_commander(self) -> None:
        ok, reason = authorize_directive(
            "builder", "engineering", Rank.COMMANDER, "code_reviewer", "engineering", DirectiveType.CHIEF_DIRECTIVE
        )
        assert ok is True

    def test_authorize_chief_directive_lt_rank(self) -> None:
        ok, reason = authorize_directive(
            "builder", "engineering", Rank.LIEUTENANT, "code_reviewer", "engineering", DirectiveType.CHIEF_DIRECTIVE
        )
        assert ok is False

    def test_authorize_chief_directive_cross_dept(self) -> None:
        ok, reason = authorize_directive(
            "builder", "engineering", Rank.COMMANDER, "diagnostician", "medical", DirectiveType.CHIEF_DIRECTIVE
        )
        assert ok is False

    def test_authorize_chief_directive_broadcast(self) -> None:
        ok, reason = authorize_directive(
            "builder", "engineering", Rank.COMMANDER, "*", None, DirectiveType.CHIEF_DIRECTIVE
        )
        assert ok is False

    def test_authorize_learned_lesson_self(self) -> None:
        ok, reason = authorize_directive(
            "builder", "engineering", Rank.LIEUTENANT, "builder", "engineering", DirectiveType.LEARNED_LESSON
        )
        assert ok is True

    def test_authorize_learned_lesson_other(self) -> None:
        ok, reason = authorize_directive(
            "builder", "engineering", Rank.LIEUTENANT, "diagnostician", "medical", DirectiveType.LEARNED_LESSON
        )
        assert ok is False

    def test_authorize_peer_suggestion_lt(self) -> None:
        ok, reason = authorize_directive(
            "builder", "engineering", Rank.LIEUTENANT, "diagnostician", "medical", DirectiveType.PEER_SUGGESTION
        )
        assert ok is True

    def test_authorize_peer_suggestion_ensign(self) -> None:
        ok, reason = authorize_directive(
            "builder", "engineering", Rank.ENSIGN, "diagnostician", "medical", DirectiveType.PEER_SUGGESTION
        )
        assert ok is False


class TestDirectiveStore(unittest.TestCase):
    def setUp(self) -> None:
        self.store = DirectiveStore(db_path=":memory:")

    def _make_directive(self, **kwargs) -> RuntimeDirective:
        defaults = {
            "id": "test-1",
            "target_agent_type": "builder",
            "target_department": "engineering",
            "directive_type": DirectiveType.CAPTAIN_ORDER,
            "content": "Test directive",
            "issued_by": "captain",
            "issued_by_department": None,
            "authority": 1.0,
            "priority": 3,
            "status": DirectiveStatus.ACTIVE,
            "created_at": time.time(),
        }
        defaults.update(kwargs)
        return RuntimeDirective(**defaults)

    def test_store_add_and_retrieve(self) -> None:
        d = self._make_directive()
        self.store.add(d)
        results = self.store.get_active_for_agent("builder", "engineering")
        assert len(results) == 1
        assert results[0].content == "Test directive"

    def test_store_target_filtering(self) -> None:
        d = self._make_directive(target_agent_type="builder")
        self.store.add(d)
        results = self.store.get_active_for_agent("diagnostician", "medical")
        assert len(results) == 0

    def test_store_broadcast_directive(self) -> None:
        d = self._make_directive(target_agent_type="*", target_department=None)
        self.store.add(d)
        for agent in ("builder", "diagnostician", "architect"):
            results = self.store.get_active_for_agent(agent)
            assert len(results) == 1

    def test_store_department_filtering(self) -> None:
        d = self._make_directive(target_agent_type="*", target_department="engineering")
        self.store.add(d)
        eng = self.store.get_active_for_agent("builder", "engineering")
        assert len(eng) == 1
        med = self.store.get_active_for_agent("diagnostician", "medical")
        assert len(med) == 0

    def test_store_revoke(self) -> None:
        d = self._make_directive()
        self.store.add(d)
        result = self.store.revoke("test-1", "captain")
        assert result is True
        active = self.store.get_active_for_agent("builder", "engineering")
        assert len(active) == 0

    def test_store_approve_pending(self) -> None:
        d = self._make_directive(status=DirectiveStatus.PENDING_APPROVAL)
        self.store.add(d)
        # Not returned as active yet
        active = self.store.get_active_for_agent("builder", "engineering")
        assert len(active) == 0
        # Approve
        result = self.store.approve("test-1")
        assert result is True
        active = self.store.get_active_for_agent("builder", "engineering")
        assert len(active) == 1

    def test_store_approve_non_pending(self) -> None:
        d = self._make_directive(status=DirectiveStatus.ACTIVE)
        self.store.add(d)
        result = self.store.approve("test-1")
        assert result is False  # Already active, not pending

    def test_store_expiry(self) -> None:
        d = self._make_directive(expires_at=time.time() - 100)  # Already expired
        self.store.add(d)
        results = self.store.get_active_for_agent("builder", "engineering")
        assert len(results) == 0

    def test_store_priority_ordering(self) -> None:
        d1 = self._make_directive(id="p5", priority=5)
        d2 = self._make_directive(id="p1", priority=1)
        d3 = self._make_directive(id="p3", priority=3)
        self.store.add(d1)
        self.store.add(d2)
        self.store.add(d3)
        results = self.store.get_active_for_agent("builder", "engineering")
        assert len(results) == 3
        assert [r.priority for r in results] == [1, 3, 5]

    def test_create_directive_captain(self) -> None:
        directive, reason = self.store.create_directive(
            issuer_type="captain",
            issuer_department=None,
            issuer_rank=Rank.SENIOR,
            target_agent_type="builder",
            target_department="engineering",
            directive_type=DirectiveType.CAPTAIN_ORDER,
            content="Use Python 3.12 features",
        )
        assert directive is not None
        assert directive.status == DirectiveStatus.ACTIVE

    def test_create_directive_learned_lesson_ensign(self) -> None:
        directive, reason = self.store.create_directive(
            issuer_type="builder",
            issuer_department="engineering",
            issuer_rank=Rank.ENSIGN,
            target_agent_type="builder",
            target_department="engineering",
            directive_type=DirectiveType.LEARNED_LESSON,
            content="Use asyncio.gather for parallel IO",
        )
        assert directive is not None
        assert directive.status == DirectiveStatus.PENDING_APPROVAL

    def test_create_directive_learned_lesson_lt(self) -> None:
        directive, reason = self.store.create_directive(
            issuer_type="builder",
            issuer_department="engineering",
            issuer_rank=Rank.LIEUTENANT,
            target_agent_type="builder",
            target_department="engineering",
            directive_type=DirectiveType.LEARNED_LESSON,
            content="Prefer dataclasses over plain dicts",
        )
        assert directive is not None
        assert directive.status == DirectiveStatus.ACTIVE

    def test_create_directive_peer_suggestion(self) -> None:
        directive, reason = self.store.create_directive(
            issuer_type="architect",
            issuer_department="science",
            issuer_rank=Rank.LIEUTENANT,
            target_agent_type="builder",
            target_department="engineering",
            directive_type=DirectiveType.PEER_SUGGESTION,
            content="Consider using dependency injection",
        )
        assert directive is not None
        assert directive.status == DirectiveStatus.PENDING_APPROVAL

    def test_all_directives_active_only(self) -> None:
        d1 = self._make_directive(id="a1", status=DirectiveStatus.ACTIVE)
        d2 = self._make_directive(id="a2", status=DirectiveStatus.REVOKED)
        d3 = self._make_directive(id="a3", status=DirectiveStatus.PENDING_APPROVAL)
        self.store.add(d1)
        self.store.add(d2)
        self.store.add(d3)
        results = self.store.all_directives(include_inactive=False)
        ids = {d.id for d in results}
        assert "a1" in ids
        assert "a3" in ids
        assert "a2" not in ids

    def test_all_directives_include_inactive(self) -> None:
        d1 = self._make_directive(id="b1", status=DirectiveStatus.ACTIVE)
        d2 = self._make_directive(id="b2", status=DirectiveStatus.REVOKED)
        d3 = self._make_directive(id="b3", status=DirectiveStatus.EXPIRED)
        self.store.add(d1)
        self.store.add(d2)
        self.store.add(d3)
        results = self.store.all_directives(include_inactive=True)
        ids = {d.id for d in results}
        assert "b1" in ids
        assert "b2" in ids
        assert "b3" in ids
