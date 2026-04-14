"""AD-622: Special Access Grants (ClearanceGrant).

Tests for the clearance grant system:
- ClearanceGrant dataclass
- effective_recall_tier() with grants
- ClearanceGrantStore (issue, revoke, list, cache)
- resolve_active_grants() helper
- Shell command parsing
"""
from __future__ import annotations

import time
from dataclasses import FrozenInstanceError
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.crew_profile import Rank
from probos.earned_agency import (
    ClearanceGrant,
    RecallTier,
    effective_recall_tier,
    resolve_active_grants,
)


# ---------------------------------------------------------------------------
# 1-2: ClearanceGrant dataclass
# ---------------------------------------------------------------------------

class TestClearanceGrantDataclass:
    def test_grant_creation_defaults(self) -> None:
        """ClearanceGrant with required fields only — verify defaults."""
        grant = ClearanceGrant(
            id="g-001",
            target_agent_id="agent-abc",
            recall_tier=RecallTier.FULL,
        )
        assert grant.scope == "general"
        assert grant.reason == ""
        assert grant.issued_by == "captain"
        assert grant.issued_at == 0.0
        assert grant.expires_at is None
        assert grant.revoked is False
        assert grant.revoked_at is None

    def test_grant_is_frozen(self) -> None:
        """ClearanceGrant is immutable (frozen dataclass)."""
        grant = ClearanceGrant(
            id="g-002", target_agent_id="agent-xyz",
            recall_tier=RecallTier.ENHANCED,
        )
        with pytest.raises(FrozenInstanceError):
            grant.scope = "project:x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 3-9: effective_recall_tier with grants
# ---------------------------------------------------------------------------

class TestEffectiveRecallTierWithGrants:
    def test_no_grants_existing_behavior(self) -> None:
        """Empty grants → same as before (AD-620 behavior)."""
        assert effective_recall_tier(Rank.ENSIGN) == RecallTier.BASIC
        assert effective_recall_tier(Rank.COMMANDER, "full") == RecallTier.FULL

    def test_grant_elevates_beyond_rank(self) -> None:
        """Ensign (BASIC rank) + ORACLE grant → ORACLE."""
        grant = ClearanceGrant(
            id="g-010", target_agent_id="a",
            recall_tier=RecallTier.ORACLE,
        )
        assert effective_recall_tier(Rank.ENSIGN, "", (grant,)) == RecallTier.ORACLE

    def test_grant_elevates_beyond_billet(self) -> None:
        """Officer (ENHANCED billet) + FULL grant → FULL."""
        grant = ClearanceGrant(
            id="g-011", target_agent_id="a",
            recall_tier=RecallTier.FULL,
        )
        assert effective_recall_tier(Rank.LIEUTENANT, "enhanced", (grant,)) == RecallTier.FULL

    def test_max_all_three_sources(self) -> None:
        """rank=BASIC, billet=ENHANCED, grant=FULL → FULL."""
        grant = ClearanceGrant(
            id="g-012", target_agent_id="a",
            recall_tier=RecallTier.FULL,
        )
        assert effective_recall_tier(Rank.ENSIGN, "enhanced", (grant,)) == RecallTier.FULL

    def test_grant_lower_than_existing_no_effect(self) -> None:
        """Grant at BASIC when rank gives FULL — no downgrade."""
        grant = ClearanceGrant(
            id="g-013", target_agent_id="a",
            recall_tier=RecallTier.BASIC,
        )
        assert effective_recall_tier(Rank.COMMANDER, "", (grant,)) == RecallTier.FULL

    def test_multiple_grants_highest_wins(self) -> None:
        """Two grants (ENHANCED, FULL) → FULL used."""
        grants = (
            ClearanceGrant(id="g-014a", target_agent_id="a", recall_tier=RecallTier.ENHANCED),
            ClearanceGrant(id="g-014b", target_agent_id="a", recall_tier=RecallTier.FULL),
        )
        assert effective_recall_tier(Rank.ENSIGN, "", grants) == RecallTier.FULL


# ---------------------------------------------------------------------------
# 10-17: ClearanceGrantStore
# ---------------------------------------------------------------------------

class TestClearanceGrantStore:
    @pytest.fixture
    async def store(self, tmp_path):
        from probos.clearance_grants import ClearanceGrantStore
        s = ClearanceGrantStore(db_path=str(tmp_path / "grants.db"))
        await s.start()
        yield s
        await s.stop()

    @pytest.mark.asyncio
    async def test_issue_grant_creates_record(self, store) -> None:
        """Issue + list → grant present."""
        grant = await store.issue_grant(
            target_agent_id="agent-001",
            recall_tier=RecallTier.FULL,
            scope="investigation:sec-42",
            reason="security audit",
        )
        grants = await store.list_grants()
        assert len(grants) == 1
        assert grants[0].id == grant.id
        assert grants[0].target_agent_id == "agent-001"
        assert grants[0].recall_tier == RecallTier.FULL
        assert grants[0].scope == "investigation:sec-42"

    @pytest.mark.asyncio
    async def test_revoke_grant_soft_deletes(self, store) -> None:
        """Revoke → still in list(active_only=False) but revoked."""
        grant = await store.issue_grant("agent-002", RecallTier.ORACLE)
        ok = await store.revoke_grant(grant.id)
        assert ok is True

        active = await store.list_grants(active_only=True)
        assert len(active) == 0

        all_grants = await store.list_grants(active_only=False)
        assert len(all_grants) == 1
        assert all_grants[0].revoked is True
        assert all_grants[0].revoked_at is not None

    @pytest.mark.asyncio
    async def test_get_active_grants_sync_cached(self, store) -> None:
        """Issue → sync read returns grant."""
        await store.issue_grant("agent-003", RecallTier.ENHANCED)
        grants = store.get_active_grants_sync("agent-003")
        assert len(grants) == 1
        assert grants[0].recall_tier == RecallTier.ENHANCED

    @pytest.mark.asyncio
    async def test_expired_grants_excluded_from_sync(self, store) -> None:
        """Grant with expires_at in past → not in sync results."""
        await store.issue_grant(
            "agent-004", RecallTier.FULL,
            expires_at=time.time() - 100,  # already expired
        )
        grants = store.get_active_grants_sync("agent-004")
        assert len(grants) == 0

    @pytest.mark.asyncio
    async def test_revoke_updates_cache(self, store) -> None:
        """Revoke → sync read no longer returns grant."""
        grant = await store.issue_grant("agent-005", RecallTier.ORACLE)
        assert len(store.get_active_grants_sync("agent-005")) == 1
        await store.revoke_grant(grant.id)
        assert len(store.get_active_grants_sync("agent-005")) == 0

    @pytest.mark.asyncio
    async def test_list_grants_all(self, store) -> None:
        """--all includes revoked and expired."""
        g1 = await store.issue_grant("a1", RecallTier.BASIC)
        g2 = await store.issue_grant("a2", RecallTier.ENHANCED, expires_at=time.time() - 10)
        g3 = await store.issue_grant("a3", RecallTier.FULL)
        await store.revoke_grant(g3.id)

        active = await store.list_grants(active_only=True)
        all_g = await store.list_grants(active_only=False)
        assert len(active) == 1  # only g1
        assert len(all_g) == 3   # all three

    @pytest.mark.asyncio
    async def test_start_loads_cache(self, tmp_path) -> None:
        """Pre-populate DB, restart → cache populated."""
        from probos.clearance_grants import ClearanceGrantStore
        s1 = ClearanceGrantStore(db_path=str(tmp_path / "grants2.db"))
        await s1.start()
        await s1.issue_grant("agent-load", RecallTier.FULL)
        await s1.stop()

        # Restart with same DB
        s2 = ClearanceGrantStore(db_path=str(tmp_path / "grants2.db"))
        await s2.start()
        grants = s2.get_active_grants_sync("agent-load")
        assert len(grants) == 1
        assert grants[0].recall_tier == RecallTier.FULL
        await s2.stop()

    @pytest.mark.asyncio
    async def test_get_grant_by_id(self, store) -> None:
        """Returns specific grant or None."""
        grant = await store.issue_grant("agent-006", RecallTier.ENHANCED)
        fetched = await store.get_grant(grant.id)
        assert fetched is not None
        assert fetched.id == grant.id

        missing = await store.get_grant("nonexistent-id")
        assert missing is None


# ---------------------------------------------------------------------------
# 18-19: resolve_active_grants helper
# ---------------------------------------------------------------------------

class TestResolveActiveGrants:
    def test_none_store_returns_empty(self) -> None:
        """None grant store → empty list."""
        result = resolve_active_grants("agent-x", None)
        assert result == []

    def test_store_returns_grants(self) -> None:
        """Helper returns active grants for agent."""
        grant = ClearanceGrant(
            id="g-020", target_agent_id="agent-y",
            recall_tier=RecallTier.ORACLE,
        )
        mock_store = MagicMock()
        mock_store.get_active_grants_sync.return_value = [grant]
        result = resolve_active_grants("agent-y", mock_store)
        assert len(result) == 1
        assert result[0].recall_tier == RecallTier.ORACLE
        mock_store.get_active_grants_sync.assert_called_once_with("agent-y")

    def test_store_exception_returns_empty(self) -> None:
        """Store raises → returns empty list (fail-open)."""
        mock_store = MagicMock()
        mock_store.get_active_grants_sync.side_effect = RuntimeError("db gone")
        result = resolve_active_grants("agent-z", mock_store)
        assert result == []


# ---------------------------------------------------------------------------
# 20-22: Shell command tests
# ---------------------------------------------------------------------------

class TestShellCommands:
    @pytest.mark.asyncio
    async def test_cmd_grant_issue(self) -> None:
        """Valid args → grant created."""
        from probos.experience.commands.commands_clearance import cmd_grant
        from rich.console import Console

        mock_runtime = MagicMock()
        mock_runtime.callsign_registry.resolve.return_value = {
            "agent_id": "slot-001",
            "callsign": "TestAgent",
            "agent_type": "test_agent",
            "department": "engineering",
        }
        mock_runtime.identity_registry = None
        mock_store = AsyncMock()
        grant = ClearanceGrant(
            id="g-cmd-001", target_agent_id="slot-001",
            recall_tier=RecallTier.FULL,
            issued_at=time.time(),
        )
        mock_store.issue_grant.return_value = grant
        mock_runtime.clearance_grant_store = mock_store

        console = Console(file=StringIO())
        await cmd_grant(mock_runtime, console, "issue TestAgent full")

        mock_store.issue_grant.assert_called_once()
        call_kwargs = mock_store.issue_grant.call_args
        assert call_kwargs.kwargs["recall_tier"] == RecallTier.FULL

    @pytest.mark.asyncio
    async def test_cmd_grant_revoke_prefix(self) -> None:
        """8-char prefix matches grant ID."""
        from probos.experience.commands.commands_clearance import cmd_grant
        from rich.console import Console

        grant = ClearanceGrant(
            id="abcd1234-5678-9012-3456-789012345678",
            target_agent_id="agent-x",
            recall_tier=RecallTier.ENHANCED,
            issued_at=time.time(),
        )
        mock_store = AsyncMock()
        mock_store.list_grants.return_value = [grant]
        mock_store.revoke_grant.return_value = True

        mock_runtime = MagicMock()
        mock_runtime.clearance_grant_store = mock_store

        console = Console(file=StringIO())
        await cmd_grant(mock_runtime, console, "revoke abcd1234")

        mock_store.revoke_grant.assert_called_once_with(grant.id)

    @pytest.mark.asyncio
    async def test_cmd_grant_list_renders(self) -> None:
        """List command renders table without crash."""
        from probos.experience.commands.commands_clearance import cmd_grant
        from rich.console import Console

        grant = ClearanceGrant(
            id="list-test-001", target_agent_id="agent-list",
            recall_tier=RecallTier.FULL,
            issued_at=time.time(), scope="general",
        )
        mock_store = AsyncMock()
        mock_store.list_grants.return_value = [grant]

        mock_runtime = MagicMock()
        mock_runtime.clearance_grant_store = mock_store
        mock_runtime.callsign_registry.list_all.return_value = []

        console = Console(file=StringIO())
        await cmd_grant(mock_runtime, console, "list")

        mock_store.list_grants.assert_called_once()
