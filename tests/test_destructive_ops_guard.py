from __future__ import annotations

import pytest

from probos.security.destructive_ops import DestructiveOpsGuard
from probos.security.permission_model import PermissionConfig, PermissionMode, should_auto_approve


@pytest.mark.asyncio
async def test_destructive_intent_never_auto_approves_even_if_whitelisted() -> None:
    config = PermissionConfig(
        mode=PermissionMode.AUTOPILOT,
        auto_approve_read_only=True,
        read_only_whitelist={"write_file"},
    )

    allowed = await should_auto_approve("write_file", config)

    assert allowed is False


@pytest.mark.asyncio
async def test_check_and_log_destructive_intent_emits_warning(caplog: pytest.LogCaptureFixture) -> None:
    guard = DestructiveOpsGuard()

    with caplog.at_level("WARNING"):
        flagged = await guard.check_and_log("delete_file")

    assert flagged is True
    assert "destructive intent requested" in caplog.text
