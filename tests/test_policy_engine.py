from __future__ import annotations

import pytest

from probos.governance.policy_engine import NullPolicyEngine
from probos.security.permission_card import card_from_intent


@pytest.mark.asyncio
async def test_null_policy_engine_evaluate_permission_always_true() -> None:
    engine = NullPolicyEngine()
    card = card_from_intent(
        intent="write_file",
        reason="unit-test",
        scope="~/Documents/test.md",
    )

    allowed = await engine.evaluate_permission(card)

    assert allowed is True
