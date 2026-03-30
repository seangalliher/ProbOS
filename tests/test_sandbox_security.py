"""Security tests for SandboxRunner — BF-086.

Tests the execution boundary, agent class discovery, and integration
with CodeValidator. Uses real SelfModConfig defaults.
"""

from __future__ import annotations

import sys
import textwrap

import pytest

from probos.config import SelfModConfig
from probos.cognitive.sandbox import SandboxRunner, SandboxResult


# ---------------------------------------------------------------------------
# Shared valid agent source
# ---------------------------------------------------------------------------

VALID_AGENT_SOURCE = textwrap.dedent('''\
    from probos.substrate.agent import BaseAgent
    from probos.types import IntentMessage, IntentResult, IntentDescriptor

    class TestAgent(BaseAgent):
        """Test agent for sandbox."""

        agent_type = "test_sandbox"
        _handled_intents = ["test_sandbox"]
        intent_descriptors = [
            IntentDescriptor(
                name="test_sandbox",
                params={},
                description="test sandbox agent",
                requires_consensus=False,
                requires_reflect=False,
            )
        ]

        async def perceive(self, intent):
            return intent

        async def decide(self, obs):
            return obs

        async def act(self, plan):
            return {"success": True}

        async def report(self, result):
            return result

        async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
            return IntentResult(
                intent_id=intent.id,
                agent_id=self.id,
                success=True,
                result={"message": "ok"},
                confidence=self.confidence,
            )
''')


@pytest.fixture
def runner():
    return SandboxRunner(SelfModConfig(sandbox_timeout_seconds=5.0))


@pytest.fixture
def fast_runner():
    return SandboxRunner(SelfModConfig(sandbox_timeout_seconds=0.1))


# ===========================================================================
# Part A: Execution Boundary Tests
# ===========================================================================


class TestExecutionBoundary:
    """Verify sandbox execution boundaries."""

    @pytest.mark.asyncio
    async def test_valid_agent_succeeds(self, runner):
        result = await runner.test_agent(
            VALID_AGENT_SOURCE,
            intent_name="test_sandbox",
        )
        assert result.success is True
        assert result.agent_class is not None
        assert result.error is None

    @pytest.mark.asyncio
    async def test_syntax_error_fails(self, runner):
        source = "def broken(:\n    pass"
        result = await runner.test_agent(source, intent_name="test")
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_no_agent_class_fails(self, runner):
        source = textwrap.dedent('''\
            def some_function():
                return 42
        ''')
        result = await runner.test_agent(source, intent_name="test")
        assert result.success is False
        assert "No BaseAgent subclass" in result.error

    @pytest.mark.asyncio
    async def test_wrong_return_type_fails(self, runner):
        """handle_intent returns string instead of IntentResult."""
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentMessage, IntentResult, IntentDescriptor

            class BadReturnAgent(BaseAgent):
                agent_type = "bad_return"
                _handled_intents = ["bad_return"]
                intent_descriptors = [
                    IntentDescriptor(
                        name="bad_return", params={}, description="bad return type"
                    )
                ]

                async def perceive(self, intent):
                    return intent

                async def decide(self, obs):
                    return obs

                async def act(self, plan):
                    return plan

                async def report(self, result):
                    return result

                async def handle_intent(self, intent: IntentMessage):
                    return "not an IntentResult"
        ''')
        result = await runner.test_agent(source, intent_name="bad_return")
        assert result.success is False
        assert "IntentResult" in result.error

    @pytest.mark.asyncio
    async def test_timeout_enforced(self, fast_runner):
        source = textwrap.dedent('''\
            import asyncio
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentMessage, IntentResult, IntentDescriptor

            class SlowAgent(BaseAgent):
                agent_type = "slow"
                _handled_intents = ["slow"]
                intent_descriptors = [
                    IntentDescriptor(name="slow", params={}, description="slow")
                ]

                async def perceive(self, intent):
                    return intent

                async def decide(self, obs):
                    return obs

                async def act(self, plan):
                    return plan

                async def report(self, result):
                    return result

                async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
                    await asyncio.sleep(999)
                    return None
        ''')
        result = await fast_runner.test_agent(source, intent_name="slow")
        assert result.success is False
        assert "timed out" in result.error.lower() or "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_exception_in_handle_intent(self, runner):
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentMessage, IntentResult, IntentDescriptor

            class RaiserAgent(BaseAgent):
                agent_type = "raiser"
                _handled_intents = ["raiser"]
                intent_descriptors = [
                    IntentDescriptor(name="raiser", params={}, description="raises")
                ]

                async def perceive(self, intent):
                    return intent

                async def decide(self, obs):
                    return obs

                async def act(self, plan):
                    return plan

                async def report(self, result):
                    return result

                async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
                    raise ValueError("intentional test error")
        ''')
        result = await runner.test_agent(source, intent_name="raiser")
        assert result.success is False
        assert "ValueError" in result.error

    @pytest.mark.asyncio
    async def test_exception_in_init(self, runner):
        """Agent __init__ raises → success=False."""
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentMessage, IntentResult, IntentDescriptor

            class InitFailAgent(BaseAgent):
                agent_type = "init_fail"
                _handled_intents = ["init_fail"]
                intent_descriptors = [
                    IntentDescriptor(name="init_fail", params={}, description="init fail")
                ]

                def __init__(self, *args, **kwargs):
                    raise RuntimeError("init exploded")

                async def perceive(self, intent):
                    return intent

                async def decide(self, obs):
                    return obs

                async def act(self, plan):
                    return plan

                async def report(self, result):
                    return result

                async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
                    return None
        ''')
        result = await runner.test_agent(source, intent_name="init_fail")
        assert result.success is False
        assert "RuntimeError" in result.error or "init" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execution_time_measured(self, runner):
        result = await runner.test_agent(
            VALID_AGENT_SOURCE, intent_name="test_sandbox",
        )
        assert result.success is True
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_temp_file_cleaned_up(self, runner, tmp_path):
        """After test_agent(), verify no leftover temp files from sandbox."""
        import tempfile
        import os

        # Count temp files before
        temp_dir = tempfile.gettempdir()
        before = {f for f in os.listdir(temp_dir) if f.startswith("tmp") and f.endswith(".py")}

        await runner.test_agent(VALID_AGENT_SOURCE, intent_name="test_sandbox")

        # Count temp files after
        after = {f for f in os.listdir(temp_dir) if f.startswith("tmp") and f.endswith(".py")}

        # No new .py temp files should remain
        new_files = after - before
        assert len(new_files) == 0, f"Temp files not cleaned up: {new_files}"

    @pytest.mark.asyncio
    async def test_module_removed_from_sys_modules(self, runner):
        """After test_agent(), verify no _probos_sandbox_* in sys.modules."""
        await runner.test_agent(VALID_AGENT_SOURCE, intent_name="test_sandbox")

        sandbox_modules = [
            k for k in sys.modules if k.startswith("_probos_sandbox_")
        ]
        assert sandbox_modules == [], (
            f"Sandbox modules not cleaned up: {sandbox_modules}"
        )


# ===========================================================================
# Part B: Agent Class Discovery Tests
# ===========================================================================


class TestAgentClassDiscovery:
    """Test _find_agent_class behavior."""

    @pytest.mark.asyncio
    async def test_finds_base_agent_subclass(self, runner):
        result = await runner.test_agent(
            VALID_AGENT_SOURCE, intent_name="test_sandbox",
        )
        assert result.success is True
        assert result.agent_class is not None
        from probos.substrate.agent import BaseAgent
        assert issubclass(result.agent_class, BaseAgent)

    @pytest.mark.asyncio
    async def test_finds_cognitive_agent_subclass(self, runner):
        """Module with CognitiveAgent subclass → found."""
        source = textwrap.dedent('''\
            from probos.cognitive.cognitive_agent import CognitiveAgent
            from probos.types import IntentMessage, IntentResult, IntentDescriptor

            class SmartAgent(CognitiveAgent):
                agent_type = "smart"
                _handled_intents = ["smart"]
                instructions = "Be smart."
                intent_descriptors = [
                    IntentDescriptor(name="smart", params={}, description="smart agent")
                ]
        ''')
        result = await runner.test_agent(source, intent_name="smart")
        assert result.success is True
        assert result.agent_class is not None
        assert result.agent_class.__name__ == "SmartAgent"

    @pytest.mark.asyncio
    async def test_skips_base_agent_itself(self, runner):
        """Module that only imports BaseAgent without subclassing → not found."""
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
        ''')
        result = await runner.test_agent(source, intent_name="test")
        assert result.success is False
        assert "No BaseAgent subclass" in result.error

    @pytest.mark.asyncio
    async def test_skips_cognitive_agent_itself(self, runner):
        """Module that only imports CognitiveAgent without subclassing → not found."""
        source = textwrap.dedent('''\
            from probos.cognitive.cognitive_agent import CognitiveAgent
        ''')
        result = await runner.test_agent(source, intent_name="test")
        assert result.success is False
        assert "No BaseAgent subclass" in result.error

    @pytest.mark.asyncio
    async def test_requires_intent_descriptors(self, runner):
        """Subclass without intent_descriptors → not found → success=False."""
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentMessage, IntentResult

            class NoDescriptorAgent(BaseAgent):
                agent_type = "no_desc"
                _handled_intents = ["no_desc"]

                async def perceive(self, intent):
                    return intent

                async def decide(self, obs):
                    return obs

                async def act(self, plan):
                    return plan

                async def report(self, result):
                    return result

                async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
                    return None
        ''')
        result = await runner.test_agent(source, intent_name="no_desc")
        assert result.success is False
        assert "No BaseAgent subclass" in result.error


# ===========================================================================
# Part C: Integration with CodeValidator
# ===========================================================================


class TestValidatorSandboxIntegration:
    """Test the validator → sandbox pipeline."""

    @pytest.mark.asyncio
    async def test_validator_then_sandbox_pipeline(self, runner):
        """Valid code passes validator, then passes sandbox."""
        from probos.cognitive.code_validator import CodeValidator

        config = SelfModConfig()
        validator = CodeValidator(config)

        # Validate first
        errors = validator.validate(VALID_AGENT_SOURCE)
        assert errors == [], f"Validator should pass: {errors}"

        # Then sandbox
        result = await runner.test_agent(
            VALID_AGENT_SOURCE, intent_name="test_sandbox",
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_validator_rejects_sandbox_skipped(self, runner):
        """Invalid code fails validator; sandbox never called."""
        from probos.cognitive.code_validator import CodeValidator

        config = SelfModConfig()
        validator = CodeValidator(config)

        dangerous_source = textwrap.dedent('''\
            import subprocess
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentDescriptor, IntentMessage, IntentResult

            class DangerAgent(BaseAgent):
                agent_type = "danger"
                _handled_intents = ["danger"]
                intent_descriptors = [
                    IntentDescriptor(name="danger", params={}, description="dangerous")
                ]
                async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
                    subprocess.run(["rm", "-rf", "/"])
                    return None
        ''')

        # Validator should reject
        errors = validator.validate(dangerous_source)
        assert len(errors) > 0
        assert any("subprocess" in e for e in errors)

        # In the real pipeline, sandbox would NOT be called.
        # We verify the contract: validator catches it, sandbox isn't needed.
