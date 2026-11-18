"""BF-983 (#1676 item 2): an AD-594 consultation reaches the expert's LLM and comes back with its answer.

``_answer_consultation`` built ``LLMRequest(user_message=...)``. ``LLMRequest`` has no such field and its ``prompt`` has
no default, so every consultation raised ``TypeError`` inside the handler's ``try`` and answered the low-confidence
fallback. C1 crosses the whole seam: ``consult`` on one agent, the real ``ConsultationProtocol``, the other agent's
registered handler and its LLM client. The client is a ``BaseLLMClient`` subclass that keeps each request. Each agent is
built without its ``__init__``, as ``tests/test_ad594b_consult_primitive.py`` builds one, and holds no runtime, so no
stop service and no admission service take part.
"""

from __future__ import annotations

import logging

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.consultation import ConsultationProtocol, ConsultationRequest
from probos.cognitive.llm_client import BaseLLMClient
from probos.types import LLMRequest, LLMResponse, Priority

_AGENT_LOGGER = "probos.cognitive.cognitive_agent"
_FALLBACK_LOG = "AD-594: LLM call failed for consultation by %s; providing fallback"
_QUESTION = "How stable is the warp core?"
_FALLBACK_ANSWER = "I did not complete a full analysis of 'Warp core' at this time."


class _ExpertLLM(BaseLLMClient):
    """Answers every request with one scripted response, or raises one error, and keeps each request."""

    def __init__(self, response: LLMResponse | None = None, error: Exception | None = None) -> None:
        self.requests: list[LLMRequest] = []
        self._response = response
        self._error = error

    async def complete(self, request: LLMRequest, *, priority: Priority = Priority.NORMAL) -> LLMResponse:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


def _agent(agent_id: str, callsign: str, llm: BaseLLMClient | None) -> CognitiveAgent:
    """A CognitiveAgent holding only what the consultation paths read: id, type, callsign, LLM client, protocol."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent.id = agent_id
    agent.agent_type = "test_agent"
    agent.callsign = callsign
    agent._llm_client = llm
    agent._consultation_protocol = None
    return agent


def _fallbacks(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _AGENT_LOGGER and r.msg == _FALLBACK_LOG]


def _request() -> ConsultationRequest:
    return ConsultationRequest(requester_id="requester-1", topic="Warp core", question=_QUESTION, target_agent_id="expert-1")


async def test_a_consultation_reaches_the_experts_llm_and_returns_its_answer(caplog: pytest.LogCaptureFixture) -> None:
    """C1: requester.consult -> ConsultationProtocol -> expert.handle_consultation_request -> the expert's LLM."""
    caplog.set_level(logging.WARNING, logger=_AGENT_LOGGER)
    llm = _ExpertLLM(LLMResponse(content="Stable within tolerance."))
    protocol = ConsultationProtocol()
    expert = _agent("expert-1", "Expert", llm)
    requester = _agent("requester-1", "Asker", None)
    expert.set_consultation_protocol(protocol)
    requester.set_consultation_protocol(protocol)

    response = await requester.consult(_QUESTION, target_agent_id="expert-1")

    assert response is not None  # premise: the protocol routed the request to the expert's handler
    assert [r.exc_info[0].__name__ for r in _fallbacks(caplog) if r.exc_info] == []  # the base logs TypeError here
    assert len(llm.requests) == 1
    sent = llm.requests[0]
    assert sent.prompt == _QUESTION
    assert "You are Expert, responding to an expert consultation." in sent.system_prompt
    assert f"Question: {_QUESTION}" in sent.system_prompt
    assert sent.tier == "fast"
    assert response.responder_id == "expert-1"
    assert response.answer == "Stable within tolerance."
    assert response.confidence == 0.6
    assert response.reasoning_summary == f"Consulted on {_QUESTION}"
    assert _fallbacks(caplog) == []


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(LLMResponse(content="", error="LLM rate limit exceeded for tier fast"), id="error-response"),
        pytest.param(LLMResponse(content="Stable within tolerance.", error="stream interrupted"), id="error-with-text"),
        pytest.param(LLMResponse(content="   "), id="empty-answer"),
    ],
)
async def test_a_response_that_carries_an_error_or_no_text_is_the_low_confidence_fallback(
    response: LLMResponse, caplog: pytest.LogCaptureFixture,
) -> None:
    """C2 (D2): the client reports a failed call as a response, not an exception; it is answered as a failed call."""
    caplog.set_level(logging.WARNING, logger=_AGENT_LOGGER)
    llm = _ExpertLLM(response)
    expert = _agent("expert-1", "Expert", llm)

    answer = await expert.handle_consultation_request(_request())

    assert len(llm.requests) == 1  # premise: the LLM was reached (on the base the request raised TypeError first)
    assert answer.answer == _FALLBACK_ANSWER
    assert answer.confidence == 0.2
    assert answer.reasoning_summary == "LLM call failed; low-confidence fallback response"
    [record] = _fallbacks(caplog)
    assert record.exc_info is not None and record.exc_info[0] is RuntimeError


async def test_an_llm_client_that_raises_is_the_low_confidence_fallback(caplog: pytest.LogCaptureFixture) -> None:
    """C3: a client that raises is answered by the same fallback, with its own exception logged."""
    caplog.set_level(logging.WARNING, logger=_AGENT_LOGGER)
    llm = _ExpertLLM(error=ConnectionError("provider unreachable"))
    expert = _agent("expert-1", "Expert", llm)

    answer = await expert.handle_consultation_request(_request())

    assert len(llm.requests) == 1  # premise: the LLM was reached
    assert answer.answer == _FALLBACK_ANSWER
    assert answer.confidence == 0.2
    [record] = _fallbacks(caplog)
    assert record.exc_info is not None and record.exc_info[0] is ConnectionError


async def test_with_no_llm_client_the_answer_says_so() -> None:
    """C4: no client on the agent and no runtime: the no-LLM answer, unchanged by BF-983 (a guard)."""
    expert = _agent("expert-1", "Expert", None)

    answer = await expert.handle_consultation_request(_request())

    assert answer.confidence == 0.1
    assert answer.reasoning_summary == "No LLM client available"
