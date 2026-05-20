from __future__ import annotations

import pytest

from probos.consensus.quorum import QuorumResult, vote_on_intent
from probos.governance.policy_engine import NullPolicyEngine
from probos.security.permission_card import PermissionCard
from probos.security.permission_model import PermissionConfig, PermissionMode
from probos.types import IntentMessage


class _PermitPolicyEngine(NullPolicyEngine):
    async def evaluate_permission(self, card: PermissionCard) -> bool:
        return True


@pytest.mark.asyncio
async def test_vote_on_intent_auto_approve_read_only_skips_standard_quorum() -> None:
    called = False

    async def _standard_quorum() -> QuorumResult:
        nonlocal called
        called = True
        return QuorumResult(approved=False, reason="quorum")

    config = PermissionConfig(
        mode=PermissionMode.AUTOPILOT,
        auto_approve_read_only=True,
    )
    intent = IntentMessage(intent="read_file", params={"scope": "~/Documents"})

    result = await vote_on_intent(
        intent,
        config,
        policy_engine=NullPolicyEngine(),
        standard_quorum_voting=_standard_quorum,
    )

    assert result.approved is True
    assert result.reason == "auto_approve_read_only"
    assert called is False


@pytest.mark.asyncio
async def test_vote_on_intent_policy_approval_checked_before_quorum() -> None:
    called = False

    async def _standard_quorum() -> QuorumResult:
        nonlocal called
        called = True
        return QuorumResult(approved=False, reason="quorum")

    config = PermissionConfig(
        mode=PermissionMode.MANUAL,
        auto_approve_read_only=False,
    )
    intent = IntentMessage(intent="teams_send_message", params={"scope": "dm"})

    result = await vote_on_intent(
        intent,
        config,
        policy_engine=_PermitPolicyEngine(),
        standard_quorum_voting=_standard_quorum,
    )

    assert result.approved is True
    assert result.reason == "policy_approved"
    assert called is False
