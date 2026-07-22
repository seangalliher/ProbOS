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


@pytest.mark.asyncio
async def test_counselor_handles_minor_violation() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._registry = {"agent-1": SimpleNamespace(callsign="Data")}
    counselor._trust_network = MagicMock()
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)

    await counselor._on_event_async({
        "type": EventType.CONDUCT_VIOLATION.value,
        "data": {
            "agent_id": "agent-1",
            "principle": "Honesty",
            "severity": "minor",
            "detail": "Uncertainty was not stated.",
        },
    })

    counselor._send_therapeutic_dm.assert_awaited_once()
    assert counselor._send_therapeutic_dm.await_args.args[0] == "agent-1"
    assert counselor._send_therapeutic_dm.await_args.args[1] == "Data"
    assert "reminder, not a penalty" in counselor._send_therapeutic_dm.await_args.args[2]
    counselor._trust_network.record_outcome.assert_not_called()


@pytest.mark.asyncio
async def test_counselor_handles_severe_violation() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._registry = {"agent-1": SimpleNamespace(callsign="Data")}
    counselor._trust_network = MagicMock()
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)

    await counselor._on_event_async({
        "type": EventType.CONDUCT_VIOLATION.value,
        "data": {
            "agent_id": "agent-1",
            "principle": "Respect",
            "severity": "severe",
            "detail": "Dismissive conduct repeated.",
        },
    })

    counselor._trust_network.record_outcome.assert_called_once_with(
        "agent-1",
        success=False,
        weight=0.5,
        source="conduct_violation",
    )
    counselor._send_therapeutic_dm.assert_awaited_once()
    assert counselor._send_therapeutic_dm.await_args.args[1] == "Data"
    assert "trust adjustment has been applied" in counselor._send_therapeutic_dm.await_args.args[2]


@pytest.mark.asyncio
async def test_counselor_busy_trust_still_sends_honest_severe_violation_dm() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._registry = {"agent-1": SimpleNamespace(callsign="Data")}
    counselor._trust_network = MagicMock()
    counselor._trust_network.record_outcome.side_effect = RuntimeError(
        "trust_write_in_progress",
    )
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)

    await counselor._on_conduct_violation({
        "agent_id": "agent-1",
        "principle": "Respect",
        "severity": "severe",
        "detail": "Dismissive conduct repeated.",
    })

    counselor._send_therapeutic_dm.assert_awaited_once()
    message = counselor._send_therapeutic_dm.await_args.args[2]
    assert "trust adjustment was skipped" in message
    assert "has been applied" not in message


@pytest.mark.asyncio
async def test_counselor_other_trust_runtime_error_propagates() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._registry = {"agent-1": SimpleNamespace(callsign="Data")}
    counselor._trust_network = MagicMock()
    counselor._trust_network.record_outcome.side_effect = RuntimeError(
        "trust store defect",
    )
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)

    with pytest.raises(RuntimeError, match="^trust store defect$"):
        await counselor._on_conduct_violation({
            "agent_id": "agent-1",
            "principle": "Respect",
            "severity": "severe",
            "detail": "Dismissive conduct repeated.",
        })
    counselor._send_therapeutic_dm.assert_not_awaited()


@pytest.mark.asyncio
async def test_conduct_violation_without_agent_id_is_noop() -> None:
    from probos.cognitive.counselor import CounselorAgent

    counselor = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
    counselor._trust_network = MagicMock()
    counselor._send_therapeutic_dm = AsyncMock(return_value=True)

    await counselor._on_event_async({
        "type": EventType.CONDUCT_VIOLATION.value,
        "data": {
            "principle": "Cooperation",
            "severity": "minor",
            "detail": "No agent attached.",
        },
    })

    counselor._send_therapeutic_dm.assert_not_awaited()
    counselor._trust_network.record_outcome.assert_not_called()


def test_record_outcome_source_field() -> None:
    trust_network = TrustNetwork()

    trust_network.record_outcome(
        "agent-1",
        success=False,
        source="conduct_violation",
    )
