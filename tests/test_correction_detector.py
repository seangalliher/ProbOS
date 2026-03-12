"""Tests for Phase 18b — CorrectionDetector (AD-229)."""

from __future__ import annotations

import json

import pytest

from probos.cognitive.correction_detector import CorrectionDetector, CorrectionSignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeLLMClient:
    """Minimal mock that returns a configurable string from complete()."""

    def __init__(self, response: str = "") -> None:
        self._response = response
        self.calls: list[str] = []

    async def complete(self, request):
        self.calls.append(request.prompt if hasattr(request, "prompt") else str(request))
        return self._response


def _make_dag_with_nodes(nodes):
    """Create a minimal object with .nodes attribute."""
    class _FakeDAG:
        pass
    dag = _FakeDAG()
    dag.nodes = nodes
    return dag


def _make_node(intent="test_intent", status="completed", result=None, params=None):
    class _FakeNode:
        pass
    n = _FakeNode()
    n.intent = intent
    n.status = status
    n.result = result or {}
    n.params = params or {}
    return n


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCorrectionDetection:
    """CorrectionDetector.detect() tests."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_prior_execution(self):
        """No prior execution text → None."""
        detector = CorrectionDetector(llm_client=_FakeLLMClient())
        result = await detector.detect(
            user_text="use http",
            last_execution_text=None,
            last_execution_dag=None,
            last_execution_success=True,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_dag(self):
        """No prior DAG → None."""
        detector = CorrectionDetector(llm_client=_FakeLLMClient())
        result = await detector.detect(
            user_text="use http",
            last_execution_text="get news",
            last_execution_dag=None,
            last_execution_success=True,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_dag_has_no_nodes(self):
        """DAG with no nodes → empty summary → None."""
        detector = CorrectionDetector(llm_client=_FakeLLMClient())
        dag = _make_dag_with_nodes([])
        result = await detector.detect(
            user_text="use http",
            last_execution_text="get news",
            last_execution_dag=dag,
            last_execution_success=True,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_detects_correction_from_llm_response(self):
        """LLM responds with is_correction=True → CorrectionSignal returned."""
        llm_response = json.dumps({
            "is_correction": True,
            "confidence": 0.9,
            "correction_type": "url_fix",
            "target_intent": "fetch_news",
            "target_agent_type": "fetch_news",
            "corrected_values": {"url": "http://rss.cnn.com"},
            "explanation": "Use HTTP instead of HTTPS",
        })
        detector = CorrectionDetector(llm_client=_FakeLLMClient(llm_response))
        dag = _make_dag_with_nodes([_make_node(intent="fetch_news")])

        result = await detector.detect(
            user_text="use http not https",
            last_execution_text="get news from CNN",
            last_execution_dag=dag,
            last_execution_success=False,
        )

        assert result is not None
        assert isinstance(result, CorrectionSignal)
        assert result.correction_type == "url_fix"
        assert result.target_intent == "fetch_news"
        assert result.corrected_values == {"url": "http://rss.cnn.com"}
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_returns_none_for_new_request(self):
        """LLM says is_correction=False → None."""
        llm_response = json.dumps({
            "is_correction": False,
            "confidence": 0.1,
            "correction_type": None,
            "target_intent": None,
            "target_agent_type": None,
            "corrected_values": None,
            "explanation": "This is a new request",
        })
        detector = CorrectionDetector(llm_client=_FakeLLMClient(llm_response))
        dag = _make_dag_with_nodes([_make_node()])

        result = await detector.detect(
            user_text="read /tmp/foo.txt",
            last_execution_text="get news",
            last_execution_dag=dag,
            last_execution_success=True,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_confidence_too_low(self):
        """Confidence < 0.5 → returns None."""
        llm_response = json.dumps({
            "is_correction": True,
            "confidence": 0.3,
            "correction_type": "parameter_fix",
            "target_intent": "test",
            "target_agent_type": "test",
            "corrected_values": {},
            "explanation": "Maybe a correction",
        })
        detector = CorrectionDetector(llm_client=_FakeLLMClient(llm_response))
        dag = _make_dag_with_nodes([_make_node()])

        result = await detector.detect(
            user_text="hmm maybe http",
            last_execution_text="get news",
            last_execution_dag=dag,
            last_execution_success=False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_parses_correction_type_parameter_fix(self):
        """correction_type=parameter_fix parsed correctly."""
        llm_response = json.dumps({
            "is_correction": True,
            "confidence": 0.85,
            "correction_type": "parameter_fix",
            "target_intent": "fetch_data",
            "target_agent_type": "fetch_data",
            "corrected_values": {"port": "8080"},
            "explanation": "Use port 8080",
        })
        detector = CorrectionDetector(llm_client=_FakeLLMClient(llm_response))
        dag = _make_dag_with_nodes([_make_node(intent="fetch_data")])

        result = await detector.detect(
            user_text="the port should be 8080",
            last_execution_text="connect to server",
            last_execution_dag=dag,
            last_execution_success=False,
        )
        assert result is not None
        assert result.correction_type == "parameter_fix"
        assert result.corrected_values == {"port": "8080"}

    @pytest.mark.asyncio
    async def test_handles_malformed_llm_response(self):
        """Non-JSON response → returns None gracefully."""
        detector = CorrectionDetector(llm_client=_FakeLLMClient("not valid json {{{"))
        dag = _make_dag_with_nodes([_make_node()])

        result = await detector.detect(
            user_text="use http",
            last_execution_text="get news",
            last_execution_dag=dag,
            last_execution_success=False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_includes_execution_context_in_prompt(self):
        """The LLM prompt includes prior execution details."""
        client = _FakeLLMClient(json.dumps({"is_correction": False}))
        detector = CorrectionDetector(llm_client=client)
        dag = _make_dag_with_nodes([
            _make_node(intent="http_fetch", params={"url": "http://example.com"}),
        ])

        await detector.detect(
            user_text="use http",
            last_execution_text="fetch the page",
            last_execution_dag=dag,
            last_execution_success=True,
        )

        assert len(client.calls) == 1
        prompt = client.calls[0]
        assert "fetch the page" in prompt
        assert "http_fetch" in prompt

    @pytest.mark.asyncio
    async def test_llm_call_failure_returns_none(self):
        """LLM exception → returns None gracefully."""
        class _FailingClient:
            async def complete(self, req):
                raise RuntimeError("LLM down")

        detector = CorrectionDetector(llm_client=_FailingClient())
        dag = _make_dag_with_nodes([_make_node()])

        result = await detector.detect(
            user_text="use http",
            last_execution_text="get news",
            last_execution_dag=dag,
            last_execution_success=False,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_markdown_fences_in_response(self):
        """LLM wraps JSON in markdown fences → still parsed."""
        inner_json = json.dumps({
            "is_correction": True,
            "confidence": 0.8,
            "correction_type": "approach_fix",
            "target_intent": "test_intent",
            "target_agent_type": "test_intent",
            "corrected_values": {"method": "GET"},
            "explanation": "Use GET",
        })
        llm_response = f"```json\n{inner_json}\n```"
        detector = CorrectionDetector(llm_client=_FakeLLMClient(llm_response))
        dag = _make_dag_with_nodes([_make_node()])

        result = await detector.detect(
            user_text="use GET method",
            last_execution_text="fetch data",
            last_execution_dag=dag,
            last_execution_success=False,
        )
        assert result is not None
        assert result.correction_type == "approach_fix"

    @pytest.mark.asyncio
    async def test_dag_as_dict_format(self):
        """DAG stored as dict (from _last_execution) still parsed."""
        inner_dag = _make_dag_with_nodes([_make_node(intent="test_op")])
        dag_dict = {"dag": inner_dag}

        llm_response = json.dumps({
            "is_correction": True,
            "confidence": 0.7,
            "correction_type": "parameter_fix",
            "target_intent": "test_op",
            "target_agent_type": "test_op",
            "corrected_values": {"key": "val"},
            "explanation": "Fix the key",
        })
        detector = CorrectionDetector(llm_client=_FakeLLMClient(llm_response))

        result = await detector.detect(
            user_text="change key to val",
            last_execution_text="run test_op",
            last_execution_dag=dag_dict,
            last_execution_success=True,
        )
        assert result is not None
        assert result.target_intent == "test_op"
