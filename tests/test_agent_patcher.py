"""Tests for Phase 18b — AgentPatcher (AD-230)."""

from __future__ import annotations

import dataclasses
import json

import pytest

from probos.cognitive.agent_patcher import AgentPatcher, PatchResult, CorrectionResult
from probos.cognitive.correction_detector import CorrectionSignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _FakeRecord:
    """Minimal stand-in for DesignedAgentRecord."""
    intent_name: str = "test_intent"
    agent_type: str = "test_intent"
    class_name: str = "TestIntentAgent"
    source_code: str = "class TestIntentAgent: pass"
    strategy: str = "new_agent"
    status: str = "active"


def _signal(
    correction_type="parameter_fix",
    target_intent="test_intent",
    target_agent_type="test_intent",
    corrected_values=None,
    explanation="Fix the URL",
    confidence=0.9,
) -> CorrectionSignal:
    return CorrectionSignal(
        correction_type=correction_type,
        target_intent=target_intent,
        target_agent_type=target_agent_type,
        corrected_values=corrected_values or {"url": "http://example.com"},
        explanation=explanation,
        confidence=confidence,
    )


class _FakeLLM:
    """Mock LLM that returns a configurable source code string."""
    def __init__(self, response: str = ""):
        self._response = response
        self.calls: list = []

    async def complete(self, request):
        self.calls.append(request)
        return self._response


class _FakeValidator:
    """Mock CodeValidator."""
    def __init__(self, errors=None):
        self._errors = errors or []

    def validate(self, source: str):
        return self._errors


@dataclasses.dataclass
class _SandboxResult:
    success: bool = True
    agent_class: type | None = None
    error: str | None = None
    execution_time_ms: float = 10


class _FakeSandbox:
    """Mock SandboxRunner."""
    def __init__(self, result=None):
        self._result = result or _SandboxResult(success=True, agent_class=type("Dummy", (), {}))

    async def test_agent(self, source, intent_name, test_params=None):
        return self._result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentPatcher:
    """AgentPatcher.patch() tests."""

    @pytest.mark.asyncio
    async def test_patch_success_agent_strategy(self):
        """Successful patch returns PatchResult with agent_class."""
        patched_code = "class TestIntentAgent: pass  # patched"
        patcher = AgentPatcher(
            llm_client=_FakeLLM(patched_code),
            code_validator=_FakeValidator(),
            sandbox=_FakeSandbox(),
        )
        result = await patcher.patch(_FakeRecord(), _signal(), "original request")

        assert result.success is True
        assert result.patched_source == patched_code
        assert result.agent_class is not None
        assert result.handler is None
        assert result.original_source == "class TestIntentAgent: pass"

    @pytest.mark.asyncio
    async def test_patch_preserves_original_source(self):
        """PatchResult.original_source contains the original code."""
        original = "class TestIntentAgent:\n    pass"
        record = _FakeRecord(source_code=original)
        patcher = AgentPatcher(
            llm_client=_FakeLLM("class TestIntentAgent:\n    pass  # fixed"),
            code_validator=_FakeValidator(),
            sandbox=_FakeSandbox(),
        )
        result = await patcher.patch(record, _signal(), "original request")

        assert result.original_source == original

    @pytest.mark.asyncio
    async def test_patch_includes_changes_description(self):
        """PatchResult includes changes_description from correction."""
        patcher = AgentPatcher(
            llm_client=_FakeLLM("class TestIntentAgent: pass"),
            code_validator=_FakeValidator(),
            sandbox=_FakeSandbox(),
        )
        sig = _signal(explanation="Changed URL to http")
        result = await patcher.patch(_FakeRecord(), sig, "original request")

        assert result.success is True
        assert result.changes_description == "Changed URL to http"

    @pytest.mark.asyncio
    async def test_validation_failure_returns_error(self):
        """Validation errors → PatchResult(success=False)."""
        patcher = AgentPatcher(
            llm_client=_FakeLLM("bad code"),
            code_validator=_FakeValidator(errors=["disallowed import: os"]),
            sandbox=_FakeSandbox(),
        )
        result = await patcher.patch(_FakeRecord(), _signal(), "original request")

        assert result.success is False
        assert result.error is not None
        assert "Validation failed" in result.error

    @pytest.mark.asyncio
    async def test_sandbox_failure_returns_error(self):
        """Sandbox failure → PatchResult(success=False)."""
        sandbox = _FakeSandbox(
            result=_SandboxResult(success=False, error="Class not found")
        )
        patcher = AgentPatcher(
            llm_client=_FakeLLM("class TestIntentAgent: pass"),
            code_validator=_FakeValidator(),
            sandbox=sandbox,
        )
        result = await patcher.patch(_FakeRecord(), _signal(), "original request")

        assert result.success is False
        assert result.error is not None
        assert "Sandbox failed" in result.error

    @pytest.mark.asyncio
    async def test_llm_failure_returns_error(self):
        """LLM exception → PatchResult(success=False)."""
        class _FailLLM:
            async def complete(self, req):
                raise RuntimeError("LLM error")

        patcher = AgentPatcher(
            llm_client=_FailLLM(),
            code_validator=_FakeValidator(),
            sandbox=_FakeSandbox(),
        )
        result = await patcher.patch(_FakeRecord(), _signal(), "original request")

        assert result.success is False
        assert "LLM call failed" in result.error

    @pytest.mark.asyncio
    async def test_empty_llm_response_returns_error(self):
        """Empty patched source → PatchResult(success=False)."""
        patcher = AgentPatcher(
            llm_client=_FakeLLM(""),
            code_validator=_FakeValidator(),
            sandbox=_FakeSandbox(),
        )
        result = await patcher.patch(_FakeRecord(), _signal(), "original request")

        assert result.success is False
        assert "empty" in result.error.lower()

    @pytest.mark.asyncio
    async def test_skill_strategy_returns_handler(self):
        """Skill strategy → PatchResult with handler, not agent_class."""
        skill_code = (
            "async def handle_test_intent(params, context=None):\n"
            "    return {'success': True}\n"
        )
        patcher = AgentPatcher(
            llm_client=_FakeLLM(skill_code),
            code_validator=_FakeValidator(),
            sandbox=_FakeSandbox(),
        )
        record = _FakeRecord(strategy="skill", source_code="async def handle_test_intent(p): pass")
        result = await patcher.patch(record, _signal(), "original request")

        assert result.success is True
        assert result.handler is not None
        assert result.agent_class is None

    @pytest.mark.asyncio
    async def test_clean_source_strips_markdown_fences(self):
        """_clean_source strips markdown code fences."""
        raw = "```python\nclass Foo: pass\n```"
        cleaned = AgentPatcher._clean_source(raw)
        assert "```" not in cleaned
        assert "class Foo: pass" in cleaned

    @pytest.mark.asyncio
    async def test_clean_source_strips_think_blocks(self):
        """_clean_source strips <think>...</think> blocks."""
        raw = "<think>thinking hard</think>\nclass Foo: pass"
        cleaned = AgentPatcher._clean_source(raw)
        assert "<think>" not in cleaned
        assert "class Foo: pass" in cleaned

    @pytest.mark.asyncio
    async def test_patch_sends_correction_info_to_llm(self):
        """The LLM prompt includes correction details."""
        llm = _FakeLLM("class TestIntentAgent: pass")
        patcher = AgentPatcher(
            llm_client=llm,
            code_validator=_FakeValidator(),
            sandbox=_FakeSandbox(),
        )
        sig = _signal(
            corrected_values={"url": "http://example.com"},
            explanation="Fix the protocol",
        )
        await patcher.patch(_FakeRecord(), sig, "original request")

        assert len(llm.calls) == 1
        prompt = llm.calls[0].prompt
        assert "http://example.com" in prompt
        assert "Fix the protocol" in prompt

    @pytest.mark.asyncio
    async def test_patch_result_dataclass_defaults(self):
        """PatchResult defaults are sensible."""
        pr = PatchResult(success=False)
        assert pr.patched_source == ""
        assert pr.agent_class is None
        assert pr.handler is None
        assert pr.error is None
        assert pr.original_source == ""
        assert pr.changes_description == ""

    @pytest.mark.asyncio
    async def test_correction_result_dataclass_defaults(self):
        """CorrectionResult defaults are sensible."""
        cr = CorrectionResult(success=True)
        assert cr.agent_type == ""
        assert cr.strategy == ""
        assert cr.changes_description == ""
        assert cr.retried is False
        assert cr.retry_result is None
