from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from probos.security.permission_card import PermissionCardManager


@pytest.mark.asyncio
async def test_create_card_and_list_pending_returns_created_card() -> None:
    manager = PermissionCardManager()

    card = await manager.create_card(
        intent="write_file",
        scope="~/Documents/project.md",
        reason="UpdateArchitectureDecision (#703)",
        ttl_sec=3600,
    )
    pending = await manager.list_pending()

    assert len(pending) == 1
    assert pending[0].id == card.id
    assert pending[0].status == "pending"


@pytest.mark.asyncio
async def test_approve_and_reject_append_audit_trail_events() -> None:
    manager = PermissionCardManager()

    approved = await manager.create_card(
        intent="write_file",
        scope="~/Documents/a.md",
        reason="test",
    )
    rejected = await manager.create_card(
        intent="write_file",
        scope="~/Documents/b.md",
        reason="test",
    )

    await manager.approve(approved.id, approver="Captain")
    await manager.reject(rejected.id, reason="Not now")

    approved_pending = await manager.list_pending()

    assert approved_pending == []
    assert approved.audit_trail[-1]["event"] == "approved"
    assert rejected.audit_trail[-1]["event"] == "rejected"
    assert rejected.audit_trail[-1]["reason"] == "Not now"


@pytest.mark.asyncio
async def test_expired_card_cannot_be_approved() -> None:
    manager = PermissionCardManager()

    card = await manager.create_card(
        intent="write_file",
        scope="~/Documents/stale.md",
        reason="stale",
    )
    card.expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(ValueError, match="permission_card_expired"):
        await manager.approve(card.id, approver="Captain")
