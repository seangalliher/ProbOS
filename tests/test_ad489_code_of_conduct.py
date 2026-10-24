"""Tests for AD-489 Federation Code of Conduct."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.llm_client import BaseLLMClient
from probos.consensus.trust import TrustNetwork
from probos.events import EventType


FEDERATION_ORDERS = Path("config/standing_orders/federation.md")


def test_federation_standing_orders_contain_code_of_conduct() -> None:
    text = FEDERATION_ORDERS.read_text(encoding="utf-8")

    assert "<!-- category: code_of_conduct -->" in text
    assert "## Code of Conduct" in text
    for principle in (
        "Honesty",
        "Cooperation",
        "Respect",
        "Accountability",
        "Proportionality",
        "Constructive Engagement",
    ):
        assert f"**{principle}**" in text


def test_code_of_conduct_category_marker() -> None:
    text = FEDERATION_ORDERS.read_text(encoding="utf-8")

    assert text.count("<!-- category: code_of_conduct -->") == 1
    conduct_index = text.index("<!-- category: code_of_conduct -->")
    core_index = text.index("<!-- category: core_directives -->")
    assert conduct_index < core_index


def test_conduct_violation_event_type_exists() -> None:
    assert EventType.CONDUCT_VIOLATION.value == "conduct_violation"


# BF-921 (#1636): AD-489 named no producer of CONDUCT_VIOLATION ("assessed by the Counselor or by
# department Chiefs", config/standing_orders/federation.md) and none was built, so the Counselor's
# subscription, handler and trust penalty were removed rather than left as a penalty path that the
# first emitter would inherit without a qualified gauge. The five tests that drove the removed
# handler (minor, severe, busy trust, propagating trust error, no agent id) now pin the removal.


@pytest.mark.asyncio
async def test_counselor_does_not_subscribe_to_conduct_violation() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    add_listener = MagicMock()
    await counselor.initialize(add_event_listener_fn=add_listener)

    (types,) = [call.kwargs["event_types"] for call in add_listener.call_args_list]
    assert EventType.CONDUCT_VIOLATION not in types
    assert EventType.CONFABULATION_SUPPRESSED in types


@pytest.mark.asyncio
async def test_a_conduct_violation_event_changes_nothing() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._registry = {"agent-1": SimpleNamespace(callsign="Data")}
    counselor._trust_network = MagicMock()
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)

    await counselor._on_event_async({
        "type": EventType.CONDUCT_VIOLATION.value,
        "data": {"agent_id": "agent-1", "principle": "Respect", "severity": "severe", "detail": "x"},
    })

    counselor._send_therapeutic_dm.assert_not_awaited()
    counselor._trust_network.record_outcome.assert_not_called()
    assert not hasattr(CounselorAgent, "_on_conduct_violation")


def test_record_outcome_source_field() -> None:
    trust_network = TrustNetwork()

    trust_network.record_outcome(
        "agent-1",
        success=False,
        source="conduct_violation",
    )
