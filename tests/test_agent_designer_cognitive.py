"""Tests for AgentDesigner producing CognitiveAgent subclasses (Phase 15a, AD-193–AD-198)."""

from __future__ import annotations

import ast
import asyncio

import pytest

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SelfModConfig
from probos.substrate.agent import BaseAgent
from probos.types import IntentMessage, IntentResult


class TestAgentDesignerCognitive:
    """Test that AgentDesigner generates CognitiveAgent subclasses."""

    @pytest.fixture
    def config(self):
        return SelfModConfig(enabled=True)

    @pytest.fixture
    def llm(self):
        return MockLLMClient()

    @pytest.fixture
    def designer(self, llm, config):
        from probos.cognitive.agent_designer import AgentDesigner
        return AgentDesigner(llm, config)

    @pytest.mark.asyncio
    async def test_generates_cognitive_agent_subclass(self, designer):
        """AgentDesigner generates CognitiveAgent subclass code."""
        source = await designer.design_agent(
            intent_name="summarize_text",
            intent_description="Summarize text",
            parameters={"text": "input"},
        )
        assert "CognitiveAgent" in source
        assert "class SummarizeTextAgent" in source

    @pytest.mark.asyncio
    async def test_generated_code_has_instructions(self, designer):
        """Generated code has instructions class attribute."""
        source = await designer.design_agent(
            intent_name="translate_text",
            intent_description="Translate text",
            parameters={"text": "input"},
        )
        assert "instructions" in source

    @pytest.mark.asyncio
    async def test_generated_code_has_intent_descriptors(self, designer):
        """Generated code has valid intent_descriptors."""
        source = await designer.design_agent(
            intent_name="count_words",
            intent_description="Count words",
            parameters={"text": "input"},
        )
        assert "intent_descriptors" in source
        assert "IntentDescriptor" in source

    @pytest.mark.asyncio
    async def test_generated_code_has_agent_type_and_handled(self, designer):
        """Generated code has agent_type and _handled_intents."""
        source = await designer.design_agent(
            intent_name="parse_json",
            intent_description="Parse JSON",
            parameters={"text": "input"},
        )
        assert 'agent_type = "parse_json"' in source
        assert "_handled_intents" in source

    @pytest.mark.asyncio
    async def test_generated_code_passes_validator(self, designer, config):
        """Generated code passes CodeValidator."""
        from probos.cognitive.code_validator import CodeValidator
        validator = CodeValidator(config)

        source = await designer.design_agent(
            intent_name="count_words",
            intent_description="Count words",
            parameters={"text": "input"},
        )

        errors = validator.validate(source)
        assert errors == [], f"Validation errors: {errors}"

    @pytest.mark.asyncio
    async def test_generated_code_passes_sandbox(self, designer, llm, config):
        """Generated code passes SandboxRunner with MockLLMClient."""
        from probos.cognitive.sandbox import SandboxRunner
        sandbox = SandboxRunner(config, llm_client=llm)

        source = await designer.design_agent(
            intent_name="count_words",
            intent_description="Count words",
            parameters={"text": "input"},
        )

        result = await sandbox.test_agent(source, "count_words", {"text": "hello world"})
        assert result.success, f"Sandbox failed: {result.error}"

    @pytest.mark.asyncio
    async def test_generated_agent_is_cognitive(self, designer, llm, config):
        """Generated code produces CognitiveAgent instance (not plain BaseAgent)."""
        from probos.cognitive.sandbox import SandboxRunner
        sandbox = SandboxRunner(config, llm_client=llm)

        source = await designer.design_agent(
            intent_name="count_words",
            intent_description="Count words",
            parameters={"text": "input"},
        )

        result = await sandbox.test_agent(source, "count_words", {"text": "hello"})
        assert result.success
        assert result.agent_class is not None
        assert issubclass(result.agent_class, CognitiveAgent)
        assert issubclass(result.agent_class, BaseAgent)


class TestCodeValidatorCognitive:
    """Test CodeValidator with CognitiveAgent subclasses."""

    @pytest.fixture
    def validator(self):
        from probos.cognitive.code_validator import CodeValidator
        return CodeValidator(SelfModConfig())

    def test_accepts_cognitive_agent_import(self, validator):
        """CodeValidator accepts CognitiveAgent import."""
        source = (
            'from probos.cognitive.cognitive_agent import CognitiveAgent\n'
            'from probos.types import IntentDescriptor\n'
            '\n'
            'class TestAgent(CognitiveAgent):\n'
            '    agent_type = "test"\n'
            '    _handled_intents = {"test"}\n'
            '    instructions = "Test instructions."\n'
            '    intent_descriptors = [\n'
            '        IntentDescriptor(name="test", params={}, description="Test")\n'
            '    ]\n'
            '    async def act(self, decision: dict) -> dict:\n'
            '        return {"success": True, "result": ""}\n'
        )
        errors = validator.validate(source)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_does_not_require_handle_intent_on_cognitive(self, validator):
        """CodeValidator does not require handle_intent on CognitiveAgent subclass."""
        source = (
            'from probos.cognitive.cognitive_agent import CognitiveAgent\n'
            'from probos.types import IntentDescriptor\n'
            '\n'
            'class TestAgent(CognitiveAgent):\n'
            '    agent_type = "test"\n'
            '    _handled_intents = {"test"}\n'
            '    instructions = "Test."\n'
            '    intent_descriptors = [\n'
            '        IntentDescriptor(name="test", params={}, description="Test")\n'
            '    ]\n'
            '    async def act(self, decision: dict) -> dict:\n'
            '        return {"success": True}\n'
        )
        errors = validator.validate(source)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_still_requires_handle_intent_on_base_agent(self, validator):
        """CodeValidator still requires handle_intent on BaseAgent subclass."""
        source = (
            'from probos.substrate.agent import BaseAgent\n'
            'from probos.types import IntentDescriptor\n'
            '\n'
            'class TestAgent(BaseAgent):\n'
            '    agent_type = "test"\n'
            '    _handled_intents = {"test"}\n'
            '    intent_descriptors = [\n'
            '        IntentDescriptor(name="test", params={}, description="Test")\n'
            '    ]\n'
            '    async def perceive(self, i): return i\n'
            '    async def decide(self, o): return o\n'
            '    async def act(self, p): return p\n'
            '    async def report(self, r): return r\n'
        )
        errors = validator.validate(source)
        assert any("handle_intent" in e for e in errors)


class TestEndToEndCognitiveDesign:
    """End-to-end: design → validate → sandbox → register → handle intent."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """Full end-to-end: design a CognitiveAgent, validate, sandbox, handle intent."""
        from probos.cognitive.agent_designer import AgentDesigner
        from probos.cognitive.code_validator import CodeValidator
        from probos.cognitive.sandbox import SandboxRunner

        config = SelfModConfig(enabled=True)
        llm = MockLLMClient()
        designer = AgentDesigner(llm, config)
        validator = CodeValidator(config)
        sandbox = SandboxRunner(config, llm_client=llm)

        # 1. Design
        source = await designer.design_agent(
            intent_name="analyze_sentiment",
            intent_description="Analyze sentiment of text",
            parameters={"text": "input text"},
        )

        # 2. Validate
        errors = validator.validate(source)
        assert errors == [], f"Validation errors: {errors}"

        # 3. Sandbox
        sandbox_result = await sandbox.test_agent(source, "analyze_sentiment", {"text": "I love this"})
        assert sandbox_result.success, f"Sandbox failed: {sandbox_result.error}"
        assert sandbox_result.agent_class is not None

        # 4. Instantiate and handle intent
        agent_class = sandbox_result.agent_class
        agent = agent_class(pool="test", llm_client=llm)
        assert isinstance(agent, CognitiveAgent)

        intent = IntentMessage(intent="analyze_sentiment", params={"text": "I love this"})
        result = await agent.handle_intent(intent)

        assert isinstance(result, IntentResult)
        assert result.success is True
        assert result.agent_id == agent.id

    @pytest.mark.asyncio
    async def test_self_mod_pipeline_creates_cognitive_agent(self):
        """SelfModificationPipeline creates CognitiveAgent via full flow."""
        from probos.cognitive.agent_designer import AgentDesigner
        from probos.cognitive.behavioral_monitor import BehavioralMonitor
        from probos.cognitive.code_validator import CodeValidator
        from probos.cognitive.sandbox import SandboxRunner
        from probos.cognitive.self_mod import SelfModificationPipeline

        config = SelfModConfig(enabled=True)
        llm = MockLLMClient()

        registered_classes = []

        async def mock_register(cls):
            registered_classes.append(cls)

        pipeline = SelfModificationPipeline(
            designer=AgentDesigner(llm, config),
            validator=CodeValidator(config),
            sandbox=SandboxRunner(config, llm_client=llm),
            monitor=BehavioralMonitor(),
            config=config,
            register_fn=mock_register,
            create_pool_fn=lambda *a: asyncio.sleep(0),
            set_trust_fn=lambda *a: asyncio.sleep(0),
        )

        record = await pipeline.handle_unhandled_intent(
            intent_name="extract_keywords",
            intent_description="Extract keywords from text",
            parameters={"text": "input"},
        )

        assert record is not None
        assert record.status == "active"
        assert record.class_name == "ExtractKeywordsAgent"
        assert len(registered_classes) == 1
        assert issubclass(registered_classes[0], CognitiveAgent)

    def test_design_prompt_uses_mesh_fetch_not_httpx(self):
        """AD-268: web-fetching template uses mesh broadcast, not raw httpx."""
        from probos.cognitive.agent_designer import AGENT_DESIGN_PROMPT
        assert "intent_bus.broadcast" in AGENT_DESIGN_PROMPT
        assert "http_fetch" in AGENT_DESIGN_PROMPT
        assert "httpx.AsyncClient" not in AGENT_DESIGN_PROMPT
