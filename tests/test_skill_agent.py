"""Tests for SkillBasedAgent and SkillDesigner — Phase 11 Part B."""

from __future__ import annotations

import asyncio
import time

import pytest

from probos.cognitive.skill_designer import SkillDesigner
from probos.cognitive.skill_validator import SkillValidator
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SelfModConfig
from probos.substrate.skill_agent import SkillBasedAgent
from probos.types import IntentDescriptor, IntentMessage, IntentResult, Skill


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_skill_agent_class():
    """Reset SkillBasedAgent class-level state between tests."""
    SkillBasedAgent._handled_intents = set()
    SkillBasedAgent.intent_descriptors = []
    yield
    SkillBasedAgent._handled_intents = set()
    SkillBasedAgent.intent_descriptors = []


def _make_skill(name: str = "translate_text", handler=None) -> Skill:
    """Create a test Skill."""
    async def default_handler(intent: IntentMessage, llm_client=None) -> IntentResult:
        return IntentResult(
            intent_id=intent.id,
            agent_id="skill",
            success=True,
            result={"translation": "bonjour"},
        )
    return Skill(
        name=name,
        descriptor=IntentDescriptor(
            name=name,
            params={"text": "source text", "target_lang": "language"},
            description=f"Handle {name} intent",
            requires_reflect=True,
        ),
        source_code="# test skill",
        handler=handler or default_handler,
        created_at=time.monotonic(),
        origin="designed",
    )


# ---------------------------------------------------------------------------
# SkillBasedAgent tests
# ---------------------------------------------------------------------------


class TestSkillBasedAgent:
    """Tests for SkillBasedAgent."""

    def test_agent_creates_with_empty_skills(self):
        """Agent creates with empty skills list."""
        agent = SkillBasedAgent(pool="test")
        assert agent.skills == []
        assert agent.agent_type == "skill_agent"

    def test_add_skill_registers_intent_on_instance(self):
        """add_skill registers intent on instance."""
        agent = SkillBasedAgent(pool="test")
        skill = _make_skill("translate_text")
        agent.add_skill(skill)
        assert "translate_text" in agent._handled_intents
        assert any(d.name == "translate_text" for d in agent.intent_descriptors)

    def test_add_skill_updates_class_level_descriptors(self):
        """add_skill updates class-level intent_descriptors."""
        agent = SkillBasedAgent(pool="test")
        skill = _make_skill("translate_text")
        agent.add_skill(skill)
        # Class-level should be updated
        assert any(d.name == "translate_text" for d in SkillBasedAgent.intent_descriptors)
        assert "translate_text" in SkillBasedAgent._handled_intents

    def test_remove_skill_clears_intent_from_both_levels(self):
        """remove_skill clears intent from both instance and class."""
        agent = SkillBasedAgent(pool="test")
        skill = _make_skill("translate_text")
        agent.add_skill(skill)
        assert "translate_text" in agent._handled_intents

        agent.remove_skill("translate_text")
        assert "translate_text" not in agent._handled_intents
        assert not any(d.name == "translate_text" for d in agent.intent_descriptors)
        assert "translate_text" not in SkillBasedAgent._handled_intents
        assert not any(d.name == "translate_text" for d in SkillBasedAgent.intent_descriptors)

    @pytest.mark.asyncio
    async def test_handle_intent_dispatches_to_correct_skill(self):
        """handle_intent dispatches to correct skill."""
        agent = SkillBasedAgent(pool="test")
        skill = _make_skill("translate_text")
        agent.add_skill(skill)

        intent = IntentMessage(intent="translate_text", params={"text": "hello", "target_lang": "fr"})
        result = await agent.handle_intent(intent)
        assert result is not None
        assert result.success is True
        assert result.result == {"translation": "bonjour"}

    @pytest.mark.asyncio
    async def test_handle_intent_returns_none_for_unknown(self):
        """handle_intent returns None for unknown intent."""
        agent = SkillBasedAgent(pool="test")
        intent = IntentMessage(intent="unknown_skill", params={})
        result = await agent.handle_intent(intent)
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_intent_passes_llm_client(self):
        """handle_intent passes llm_client to skill handler."""
        received_client = None

        async def handler_with_client(intent, llm_client=None):
            nonlocal received_client
            received_client = llm_client
            return IntentResult(
                intent_id=intent.id, agent_id="skill", success=True, result={}
            )

        mock_llm = MockLLMClient()
        agent = SkillBasedAgent(pool="test", llm_client=mock_llm)
        skill = _make_skill("test_skill", handler=handler_with_client)
        agent.add_skill(skill)

        intent = IntentMessage(intent="test_skill", params={})
        await agent.handle_intent(intent)
        assert received_client is mock_llm

    @pytest.mark.asyncio
    async def test_multiple_skills_dispatch_independently(self):
        """Multiple skills dispatch independently."""
        async def handler_a(intent, llm_client=None):
            return IntentResult(
                intent_id=intent.id, agent_id="skill", success=True, result={"from": "a"}
            )

        async def handler_b(intent, llm_client=None):
            return IntentResult(
                intent_id=intent.id, agent_id="skill", success=True, result={"from": "b"}
            )

        agent = SkillBasedAgent(pool="test")
        agent.add_skill(_make_skill("skill_a", handler=handler_a))
        agent.add_skill(_make_skill("skill_b", handler=handler_b))

        result_a = await agent.handle_intent(IntentMessage(intent="skill_a", params={}))
        result_b = await agent.handle_intent(IntentMessage(intent="skill_b", params={}))
        assert result_a.result == {"from": "a"}
        assert result_b.result == {"from": "b"}

    def test_agent_type_is_skill_agent(self):
        """agent_type is 'skill_agent'."""
        agent = SkillBasedAgent(pool="test")
        assert agent.agent_type == "skill_agent"

    @pytest.mark.asyncio
    async def test_skill_with_llm_handler(self):
        """Skill with LLM — handler calls llm_client."""
        async def llm_skill_handler(intent, llm_client=None):
            if llm_client:
                from probos.types import LLMRequest
                resp = await llm_client.complete(LLMRequest(prompt="test", tier="fast"))
                return IntentResult(
                    intent_id=intent.id, agent_id="skill", success=True,
                    result={"llm_response": resp.content}
                )
            return IntentResult(
                intent_id=intent.id, agent_id="skill", success=True,
                result={"llm_response": None}
            )

        mock_llm = MockLLMClient()
        agent = SkillBasedAgent(pool="test", llm_client=mock_llm)
        skill = _make_skill("llm_task", handler=llm_skill_handler)
        agent.add_skill(skill)

        intent = IntentMessage(intent="llm_task", params={})
        result = await agent.handle_intent(intent)
        assert result.success is True
        assert result.result["llm_response"] is not None


# ---------------------------------------------------------------------------
# SkillDesigner tests
# ---------------------------------------------------------------------------


class TestSkillDesigner:
    """Tests for SkillDesigner."""

    @pytest.mark.asyncio
    async def test_design_skill_returns_valid_function_source(self):
        """design_skill returns valid function source."""
        mock_llm = MockLLMClient()
        config = SelfModConfig()
        designer = SkillDesigner(mock_llm, config)

        source = await designer.design_skill(
            intent_name="translate_text",
            intent_description="Translate text between languages",
            parameters={"text": "source text", "target_lang": "language"},
            target_agent_type="skill_agent",
        )
        assert "async def handle_translate_text" in source
        assert "IntentResult" in source

    @pytest.mark.asyncio
    async def test_generated_code_passes_validator(self):
        """Generated skill code passes SkillValidator."""
        mock_llm = MockLLMClient()
        config = SelfModConfig()
        designer = SkillDesigner(mock_llm, config)
        validator = SkillValidator(config)

        source = await designer.design_skill(
            intent_name="translate_text",
            intent_description="Translate text",
            parameters={"text": "source text"},
            target_agent_type="skill_agent",
        )
        errors = validator.validate(source, "translate_text")
        assert errors == [], f"Validation errors: {errors}"

    def test_build_function_name(self):
        """_build_function_name conversion."""
        config = SelfModConfig()
        mock_llm = MockLLMClient()
        designer = SkillDesigner(mock_llm, config)
        assert designer._build_function_name("translate_text") == "handle_translate_text"
        assert designer._build_function_name("count_words") == "handle_count_words"


# ---------------------------------------------------------------------------
# SkillValidator tests
# ---------------------------------------------------------------------------


class TestSkillValidator:
    """Tests for SkillValidator."""

    def test_valid_skill_code_passes(self):
        """Valid skill code passes validation."""
        config = SelfModConfig()
        validator = SkillValidator(config)
        code = (
            'from probos.types import IntentMessage, IntentResult\n'
            '\n'
            'async def handle_my_skill(intent: IntentMessage, llm_client=None) -> IntentResult:\n'
            '    return IntentResult(intent_id=intent.id, agent_id="skill", success=True)\n'
        )
        errors = validator.validate(code, "my_skill")
        assert errors == []

    def test_missing_async_function_rejected(self):
        """Missing async function is rejected."""
        config = SelfModConfig()
        validator = SkillValidator(config)
        code = (
            'from probos.types import IntentMessage, IntentResult\n'
            '\n'
            'def handle_my_skill(intent, llm_client=None):\n'
            '    return None\n'
        )
        errors = validator.validate(code, "my_skill")
        assert any("Missing async function" in e for e in errors)

    def test_wrong_function_name_rejected(self):
        """Wrong function name is rejected."""
        config = SelfModConfig()
        validator = SkillValidator(config)
        code = (
            'from probos.types import IntentMessage, IntentResult\n'
            '\n'
            'async def handle_wrong_name(intent, llm_client=None):\n'
            '    return None\n'
        )
        errors = validator.validate(code, "my_skill")
        assert any("Missing async function" in e for e in errors)

    def test_forbidden_import_rejected(self):
        """Forbidden import is rejected."""
        config = SelfModConfig()
        validator = SkillValidator(config)
        code = (
            'import subprocess\n'
            'from probos.types import IntentMessage, IntentResult\n'
            '\n'
            'async def handle_my_skill(intent, llm_client=None):\n'
            '    return None\n'
        )
        errors = validator.validate(code, "my_skill")
        assert any("Forbidden import" in e for e in errors)

    def test_forbidden_pattern_rejected(self):
        """Forbidden pattern is rejected."""
        config = SelfModConfig()
        validator = SkillValidator(config)
        code = (
            'from probos.types import IntentMessage, IntentResult\n'
            '\n'
            'async def handle_my_skill(intent, llm_client=None):\n'
            '    result = eval("1+1")\n'
            '    return None\n'
        )
        errors = validator.validate(code, "my_skill")
        assert any("Forbidden pattern" in e for e in errors)

    def test_module_level_side_effects_rejected(self):
        """Module-level side effects are rejected."""
        config = SelfModConfig()
        validator = SkillValidator(config)
        code = (
            'from probos.types import IntentMessage, IntentResult\n'
            '\n'
            'print("hello")\n'
            '\n'
            'async def handle_my_skill(intent, llm_client=None):\n'
            '    return None\n'
        )
        errors = validator.validate(code, "my_skill")
        assert any("side effect" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Pipeline skill integration tests
# ---------------------------------------------------------------------------


class TestSkillPipeline:
    """Tests for skill integration in the self-modification pipeline."""

    @pytest.mark.asyncio
    async def test_handle_add_skill_full_flow(self):
        """handle_add_skill full flow — design -> validate -> compile -> attach."""
        from probos.cognitive.behavioral_monitor import BehavioralMonitor
        from probos.cognitive.agent_designer import AgentDesigner
        from probos.cognitive.code_validator import CodeValidator
        from probos.cognitive.sandbox import SandboxRunner
        from probos.cognitive.self_mod import SelfModificationPipeline

        mock_llm = MockLLMClient()
        config = SelfModConfig(enabled=True)

        attached_skills = []

        async def mock_add_skill(skill, target_agent_type="skill_agent"):
            attached_skills.append(skill)

        pipeline = SelfModificationPipeline(
            designer=AgentDesigner(mock_llm, config),
            validator=CodeValidator(config),
            sandbox=SandboxRunner(config),
            monitor=BehavioralMonitor(),
            config=config,
            register_fn=lambda x: asyncio.sleep(0),
            create_pool_fn=lambda *a: asyncio.sleep(0),
            set_trust_fn=lambda *a: asyncio.sleep(0),
            skill_designer=SkillDesigner(mock_llm, config),
            skill_validator=SkillValidator(config),
            add_skill_fn=mock_add_skill,
        )

        record = await pipeline.handle_add_skill(
            intent_name="translate_text",
            intent_description="Translate text",
            parameters={"text": "source text"},
            target_agent_type="skill_agent",
        )

        assert record is not None
        assert record.status == "active"
        assert record.strategy == "skill"
        assert len(attached_skills) == 1
        assert attached_skills[0].name == "translate_text"

    @pytest.mark.asyncio
    async def test_handle_add_skill_validation_failure(self):
        """handle_add_skill validation failure aborts."""
        from probos.cognitive.behavioral_monitor import BehavioralMonitor
        from probos.cognitive.agent_designer import AgentDesigner
        from probos.cognitive.code_validator import CodeValidator
        from probos.cognitive.sandbox import SandboxRunner
        from probos.cognitive.self_mod import SelfModificationPipeline

        mock_llm = MockLLMClient()
        config = SelfModConfig(enabled=True, forbidden_patterns=[r"handle_translate"])

        pipeline = SelfModificationPipeline(
            designer=AgentDesigner(mock_llm, config),
            validator=CodeValidator(config),
            sandbox=SandboxRunner(config),
            monitor=BehavioralMonitor(),
            config=config,
            register_fn=lambda x: asyncio.sleep(0),
            create_pool_fn=lambda *a: asyncio.sleep(0),
            set_trust_fn=lambda *a: asyncio.sleep(0),
            skill_designer=SkillDesigner(mock_llm, config),
            skill_validator=SkillValidator(config),
            add_skill_fn=lambda s, **kw: asyncio.sleep(0),
        )

        record = await pipeline.handle_add_skill(
            intent_name="translate_text",
            intent_description="Translate text",
            parameters={"text": "source text"},
            target_agent_type="skill_agent",
        )

        assert record is None

    def test_designed_agent_record_strategy_field(self):
        """DesignedAgentRecord.strategy field exists and defaults correctly."""
        from probos.cognitive.self_mod import DesignedAgentRecord

        record = DesignedAgentRecord(
            intent_name="test",
            agent_type="test",
            class_name="TestAgent",
            source_code="",
            created_at=0.0,
        )
        assert record.strategy == "new_agent"

        skill_record = DesignedAgentRecord(
            intent_name="test",
            agent_type="test",
            class_name="handle_test",
            source_code="",
            created_at=0.0,
            strategy="skill",
        )
        assert skill_record.strategy == "skill"

    @pytest.mark.asyncio
    async def test_runtime_add_skill_to_agents(self):
        """Runtime _add_skill_to_agents updates all pool members."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime()
        config_override = rt.config.self_mod.model_copy(update={"enabled": True})
        rt.config = rt.config.model_copy(update={"self_mod": config_override})

        try:
            await rt.start()

            # skills pool should exist
            assert "skills" in rt.pools

            skill = _make_skill("test_skill")
            await rt._add_skill_to_agents(skill)

            # All agents in skills pool should have the skill
            pool = rt.pools["skills"]
            for agent_id in pool.healthy_agents:
                agent = rt.registry.get(agent_id)
                if isinstance(agent, SkillBasedAgent):
                    assert "test_skill" in agent._handled_intents
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_descriptor_refresh_after_skill_addition(self):
        """Descriptor refresh after skill addition includes new intent."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime()
        config_override = rt.config.self_mod.model_copy(update={"enabled": True})
        rt.config = rt.config.model_copy(update={"self_mod": config_override})

        try:
            await rt.start()

            skill = _make_skill("new_capability")
            await rt._add_skill_to_agents(skill)

            # Decomposer should have the new descriptor
            descriptors = rt._collect_intent_descriptors()
            names = {d.name for d in descriptors}
            assert "new_capability" in names
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_skills_pool_spawned_when_self_mod_enabled(self):
        """Skills pool only spawned when self_mod.enabled=True."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime()
        config_override = rt.config.self_mod.model_copy(update={"enabled": True})
        rt.config = rt.config.model_copy(update={"self_mod": config_override})

        try:
            await rt.start()
            assert "skills" in rt.pools
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_skills_pool_not_spawned_when_self_mod_disabled(self):
        """Skills pool NOT spawned when self_mod.enabled=False."""
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime()
        config_override = rt.config.self_mod.model_copy(update={"enabled": False})
        rt.config = rt.config.model_copy(update={"self_mod": config_override})

        try:
            await rt.start()
            assert "skills" not in rt.pools
        finally:
            await rt.stop()
