"""AD-594b: Crew Consultation Primitive — `consult(question, context)` initiator.

The handler half (``handle_consultation_request``) was already shipped under
AD-594. This AD adds the **initiator** convenience method on
``CognitiveAgent`` so any agent can ask any other agent a question through
the protocol substrate without manually constructing ``ConsultationRequest``.

Tests cover:
- Happy path: routes through the wired protocol with this agent's identity.
- No protocol wired -> returns None, no crash.
- Empty question -> returns None.
- Invalid urgency string -> defaults to MEDIUM, request still issued.
- Optional kwargs forwarded (target_agent_id, required_expertise, context).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.consultation import (
    ConsultationRequest,
    ConsultationResponse,
    ConsultationUrgency,
)


def _make_agent_stub():
    """Construct a minimal CognitiveAgent without invoking its full __init__."""
    from probos.cognitive.cognitive_agent import CognitiveAgent

    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.id = "agent-uuid-1234"
    agent.agent_type = "test_agent"
    agent.callsign = "Tester"
    agent._consultation_protocol = None
    return agent


@pytest.mark.asyncio
async def test_consult_returns_none_when_protocol_not_wired():
    agent = _make_agent_stub()
    result = await agent.consult("Will this work?")
    assert result is None


@pytest.mark.asyncio
async def test_consult_returns_none_on_empty_question():
    agent = _make_agent_stub()
    protocol = MagicMock()
    protocol.request_consultation = AsyncMock()
    agent._consultation_protocol = protocol

    result = await agent.consult("")
    assert result is None
    protocol.request_consultation.assert_not_called()


@pytest.mark.asyncio
async def test_consult_routes_through_protocol_with_agent_identity():
    agent = _make_agent_stub()
    protocol = MagicMock()
    expected_response = ConsultationResponse(
        request_id="r1",
        responder_id="other",
        responder_callsign="Expert",
        answer="42",
        confidence=0.9,
        reasoning_summary="thought it through",
    )
    protocol.request_consultation = AsyncMock(return_value=expected_response)
    agent._consultation_protocol = protocol

    result = await agent.consult("What is the answer?")
    assert result is expected_response

    protocol.request_consultation.assert_awaited_once()
    call_args = protocol.request_consultation.await_args
    request: ConsultationRequest = call_args.args[0]
    assert isinstance(request, ConsultationRequest)
    assert request.requester_id == "agent-uuid-1234"
    assert request.requester_callsign == "Tester"
    assert request.question == "What is the answer?"
    # Topic defaults to the question when not supplied
    assert request.topic == "What is the answer?"
    assert request.urgency == ConsultationUrgency.MEDIUM
    assert request.context == {}
    assert request.target_agent_id is None
    assert request.required_expertise is None


@pytest.mark.asyncio
async def test_consult_forwards_optional_kwargs():
    agent = _make_agent_stub()
    protocol = MagicMock()
    protocol.request_consultation = AsyncMock(return_value=None)
    agent._consultation_protocol = protocol

    ctx = {"thread_id": "wr-thread-1"}
    await agent.consult(
        "Need a tactical read",
        topic="Tactical Assessment",
        context=ctx,
        required_expertise="security_analysis",
        target_agent_id="worf-uuid",
        urgency="high",
    )

    request: ConsultationRequest = protocol.request_consultation.await_args.args[0]
    assert request.topic == "Tactical Assessment"
    assert request.question == "Need a tactical read"
    assert request.context == ctx
    assert request.required_expertise == "security_analysis"
    assert request.target_agent_id == "worf-uuid"
    assert request.urgency == ConsultationUrgency.HIGH


@pytest.mark.asyncio
async def test_consult_defaults_invalid_urgency_to_medium():
    agent = _make_agent_stub()
    protocol = MagicMock()
    protocol.request_consultation = AsyncMock(return_value=None)
    agent._consultation_protocol = protocol

    await agent.consult("Question?", urgency="apocalyptic")
    request: ConsultationRequest = protocol.request_consultation.await_args.args[0]
    assert request.urgency == ConsultationUrgency.MEDIUM


@pytest.mark.asyncio
async def test_consult_propagates_protocol_none_response():
    """Protocol may legitimately return None (rate limit, no expert, timeout)."""
    agent = _make_agent_stub()
    protocol = MagicMock()
    protocol.request_consultation = AsyncMock(return_value=None)
    agent._consultation_protocol = protocol

    result = await agent.consult("Anything?")
    assert result is None
    protocol.request_consultation.assert_awaited_once()
