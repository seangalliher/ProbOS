from __future__ import annotations

import pytest

from probos.security.permission_model import (
    PermissionConfig,
    PermissionMode,
    READ_ONLY_INTENTS,
    should_auto_approve,
)


@pytest.mark.asyncio
async def test_should_auto_approve_read_only_intent_in_autopilot_returns_true() -> None:
    config = PermissionConfig(
        mode=PermissionMode.AUTOPILOT,
        auto_approve_read_only=True,
        read_only_whitelist=set(READ_ONLY_INTENTS),
    )

    allowed = await should_auto_approve("read_file", config)

    assert allowed is True


@pytest.mark.asyncio
async def test_should_auto_approve_destructive_intent_returns_false() -> None:
    config = PermissionConfig(
        mode=PermissionMode.AUTOPILOT,
        auto_approve_read_only=True,
        read_only_whitelist=set(READ_ONLY_INTENTS),
    )

    allowed = await should_auto_approve("write_file", config)

    assert allowed is False


@pytest.mark.asyncio
async def test_should_auto_approve_mode_transition_honored() -> None:
    autopilot = PermissionConfig(
        mode=PermissionMode.AUTOPILOT,
        auto_approve_read_only=True,
        read_only_whitelist=set(READ_ONLY_INTENTS),
    )
    manual = PermissionConfig(
        mode=PermissionMode.MANUAL,
        auto_approve_read_only=True,
        read_only_whitelist=set(READ_ONLY_INTENTS),
    )

    autopilot_allowed = await should_auto_approve("read_file", autopilot)
    manual_allowed = await should_auto_approve("read_file", manual)

    assert autopilot_allowed is True
    assert manual_allowed is False
