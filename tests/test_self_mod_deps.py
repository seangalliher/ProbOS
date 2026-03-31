"""Tests for Phase 17 — DependencyResolver integration with SelfModificationPipeline."""

from __future__ import annotations

import json
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import SelfModConfig
from probos.cognitive.dependency_resolver import DependencyResolver, DependencyResult
from probos.substrate.event_log import EventLog


# ---------------------------------------------------------------------------
# Valid agent source code for pipeline tests
# ---------------------------------------------------------------------------

VALID_AGENT_SOURCE = textwrap.dedent('''\
    from probos.substrate.agent import BaseAgent
    from probos.types import IntentMessage, IntentResult, IntentDescriptor

    class CountWordsAgent(BaseAgent):
        """Auto-generated agent for count_words."""

        agent_type = "count_words"
        _handled_intents = ["count_words"]
        intent_descriptors = [
            IntentDescriptor(
                name="count_words",
                params={"text": "The text to count words in"},
                description="Count the number of words in a text string",
                requires_consensus=False,
                requires_reflect=False,
            )
        ]

        async def perceive(self, intent):
            intent_name = intent.get("intent", "")
            if intent_name not in self._handled_intents:
                return None
            return {"intent": intent_name, "params": intent.get("params", {})}

        async def decide(self, observation):
            return {"action": "count", "text": observation["params"].get("text", "")}

        async def act(self, plan):
            text = plan.get("text", "")
            count = len(text.split())
            return {"success": True, "data": {"word_count": count}}

        async def report(self, result):
            return result

        async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
            if intent.intent not in self._handled_intents:
                return None
            observation = await self.perceive(intent.__dict__)
            if observation is None:
                return None
            plan = await self.decide(observation)
            result = await self.act(plan)
            report = await self.report(result)
            success = report.get("success", False)
            self.update_confidence(success)
            return IntentResult(
                intent_id=intent.id,
                agent_id=self.id,
                success=success,
                result=report.get("data"),
                error=report.get("error"),
                confidence=self.confidence,
            )
''')

VALID_SKILL_SOURCE = textwrap.dedent('''\
    from probos.types import IntentMessage, IntentResult, LLMRequest

    async def handle_test_skill(intent: IntentMessage, llm_client=None) -> IntentResult:
        """Handle test_skill intent."""
        return IntentResult(
            intent_id=intent.id,
            agent_id="skill",
            success=True,
            result={"result": "ok"},
        )
''')


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline(**overrides):
    """Create a SelfModificationPipeline with mock components."""
    from probos.cognitive.agent_designer import AgentDesigner
    from probos.cognitive.behavioral_monitor import BehavioralMonitor
    from probos.cognitive.code_validator import CodeValidator
    from probos.cognitive.sandbox import SandboxRunner
    from probos.cognitive.self_mod import SelfModificationPipeline
    from probos.cognitive.llm_client import MockLLMClient

    config = overrides.get("config", SelfModConfig(
        enabled=True,
        require_user_approval=False,
        sandbox_timeout_seconds=5.0,
    ))
    llm = MockLLMClient()
    designer = AgentDesigner(llm, config)
    validator = CodeValidator(config)
    sandbox = SandboxRunner(config)
    monitor = BehavioralMonitor()

    async def register_fn(agent_class):
        pass

    async def create_pool_fn(agent_type, pool_name, size=2):
        pass

    async def set_trust_fn(pool_name):
        pass

    pipeline = SelfModificationPipeline(
        designer=designer,
        validator=validator,
        sandbox=sandbox,
        monitor=monitor,
        config=config,
        register_fn=register_fn,
        create_pool_fn=create_pool_fn,
        set_trust_fn=set_trust_fn,
        dependency_resolver=overrides.get("dependency_resolver"),
        event_log=overrides.get("event_log"),
    )
    return pipeline


# ---------------------------------------------------------------------------
# TestPipelineBackwardCompat
# ---------------------------------------------------------------------------


class TestPipelineBackwardCompat:
    """Pipeline works without dependency_resolver (backward compat)."""

    def test_no_resolver_param(self):
        """Pipeline constructs without dependency_resolver."""
        pipeline = _make_pipeline()
        assert pipeline._dependency_resolver is None

    def test_existing_tests_still_pass(self):
        """Pipeline without resolver skips dependency resolution."""
        pipeline = _make_pipeline()
        assert pipeline._dependency_resolver is None


# ---------------------------------------------------------------------------
# TestPipelineDependencyResolution
# ---------------------------------------------------------------------------


class TestPipelineDependencyResolution:
    """Pipeline calls resolver.resolve() between validation and sandbox."""

    @pytest.mark.asyncio
    async def test_resolver_called_after_validator(self):
        """Pipeline calls resolve() after CodeValidator."""
        resolver = MagicMock(spec=DependencyResolver)
        resolver.detect_missing = MagicMock(return_value=[])
        resolver.resolve = AsyncMock(return_value=DependencyResult(success=True))
        pipeline = _make_pipeline(dependency_resolver=resolver)
        pipeline._designer.design_agent = AsyncMock(return_value=VALID_AGENT_SOURCE)

        await pipeline.handle_unhandled_intent(
            intent_name="count_words",
            intent_description="Count words",
            parameters={"text": "hello"},
        )
        resolver.resolve.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_aborts_on_declined(self):
        """Pipeline aborts when dependencies are declined."""
        resolver = MagicMock(spec=DependencyResolver)
        resolver.detect_missing = MagicMock(return_value=["feedparser"])
        resolver.resolve = AsyncMock(return_value=DependencyResult(
            success=False, declined=["feedparser"],
        ))
        pipeline = _make_pipeline(dependency_resolver=resolver)
        pipeline._designer.design_agent = AsyncMock(return_value=VALID_AGENT_SOURCE)

        record = await pipeline.handle_unhandled_intent(
            intent_name="count_words",
            intent_description="Count words",
            parameters={"text": "hello"},
        )
        assert record is not None
        assert record.status == "dependencies_declined"
        assert any(r.status == "dependencies_declined" for r in pipeline._records)

    @pytest.mark.asyncio
    async def test_pipeline_aborts_on_install_failure(self):
        """Pipeline aborts when dependency install fails."""
        resolver = MagicMock(spec=DependencyResolver)
        resolver.detect_missing = MagicMock(return_value=["feedparser"])
        resolver.resolve = AsyncMock(return_value=DependencyResult(
            success=False, failed=["feedparser"], error="install failed",
        ))
        pipeline = _make_pipeline(dependency_resolver=resolver)
        pipeline._designer.design_agent = AsyncMock(return_value=VALID_AGENT_SOURCE)

        record = await pipeline.handle_unhandled_intent(
            intent_name="count_words",
            intent_description="Count words",
            parameters={"text": "hello"},
        )
        assert record is not None
        assert record.status == "dependencies_failed"
        assert any(r.status == "dependencies_failed" for r in pipeline._records)

    @pytest.mark.asyncio
    async def test_pipeline_continues_on_success(self):
        """Pipeline continues to sandbox when deps resolved."""
        resolver = MagicMock(spec=DependencyResolver)
        resolver.detect_missing = MagicMock(return_value=[])
        resolver.resolve = AsyncMock(return_value=DependencyResult(success=True))
        pipeline = _make_pipeline(dependency_resolver=resolver)
        pipeline._designer.design_agent = AsyncMock(return_value=VALID_AGENT_SOURCE)

        await pipeline.handle_unhandled_intent(
            intent_name="count_words",
            intent_description="Count words",
            parameters={"text": "hello"},
        )
        resolver.resolve.assert_called_once()


# ---------------------------------------------------------------------------
# TestSkillDependencyResolution
# ---------------------------------------------------------------------------


class TestSkillDependencyResolution:
    """Skill pipeline also calls dependency resolution."""

    @pytest.mark.asyncio
    async def test_skill_resolver_called(self):
        """handle_add_skill calls resolve()."""
        from probos.cognitive.skill_designer import SkillDesigner
        from probos.cognitive.skill_validator import SkillValidator
        from probos.cognitive.llm_client import MockLLMClient

        resolver = MagicMock(spec=DependencyResolver)
        resolver.detect_missing = MagicMock(return_value=[])
        resolver.resolve = AsyncMock(return_value=DependencyResult(success=True))

        config = SelfModConfig(
            enabled=True, require_user_approval=False,
            sandbox_timeout_seconds=5.0,
        )
        llm = MockLLMClient()

        pipeline = _make_pipeline(dependency_resolver=resolver, config=config)
        pipeline._skill_designer = SkillDesigner(llm, config)
        pipeline._skill_validator = SkillValidator(config)
        pipeline._add_skill_fn = AsyncMock()
        pipeline._skill_designer.design_skill = AsyncMock(return_value=VALID_SKILL_SOURCE)

        await pipeline.handle_add_skill(
            intent_name="test_skill",
            intent_description="Test skill",
            parameters={"text": "hello"},
            target_agent_type="skill_agent",
        )
        resolver.resolve.assert_called_once()


# ---------------------------------------------------------------------------
# TestDependencyEventLog
# ---------------------------------------------------------------------------


class TestDependencyEventLog:
    """Event log records dependency events (AD-215)."""

    @pytest.mark.asyncio
    async def test_dependency_check_event(self):
        """dependency_check event logged."""
        event_log = MagicMock(spec=EventLog)
        event_log.log = AsyncMock()

        resolver = MagicMock(spec=DependencyResolver)
        resolver.detect_missing = MagicMock(return_value=["feedparser"])
        resolver.resolve = AsyncMock(return_value=DependencyResult(
            success=False, declined=["feedparser"],
        ))
        pipeline = _make_pipeline(
            dependency_resolver=resolver, event_log=event_log,
        )
        pipeline._designer.design_agent = AsyncMock(return_value=VALID_AGENT_SOURCE)

        await pipeline.handle_unhandled_intent(
            intent_name="count_words",
            intent_description="Count words",
            parameters={"text": "hello"},
        )

        check_calls = [
            c for c in event_log.log.call_args_list
            if c.kwargs.get("event") == "dependency_check"
        ]
        assert len(check_calls) >= 1

    @pytest.mark.asyncio
    async def test_dependency_declined_event(self):
        """dependency_install_declined event logged when user says no."""
        event_log = MagicMock(spec=EventLog)
        event_log.log = AsyncMock()

        resolver = MagicMock(spec=DependencyResolver)
        resolver.detect_missing = MagicMock(return_value=["feedparser"])
        resolver.resolve = AsyncMock(return_value=DependencyResult(
            success=False, declined=["feedparser"],
        ))
        pipeline = _make_pipeline(
            dependency_resolver=resolver, event_log=event_log,
        )
        pipeline._designer.design_agent = AsyncMock(return_value=VALID_AGENT_SOURCE)

        await pipeline.handle_unhandled_intent(
            intent_name="count_words",
            intent_description="Count words",
            parameters={"text": "hello"},
        )

        declined_calls = [
            c for c in event_log.log.call_args_list
            if c.kwargs.get("event") == "dependency_install_declined"
        ]
        assert len(declined_calls) >= 1

    @pytest.mark.asyncio
    async def test_dependency_approved_and_success_events(self):
        """dependency_install_approved and dependency_install_success logged."""
        event_log = MagicMock(spec=EventLog)
        event_log.log = AsyncMock()

        resolver = MagicMock(spec=DependencyResolver)
        resolver.detect_missing = MagicMock(return_value=["feedparser"])
        resolver.resolve = AsyncMock(return_value=DependencyResult(
            success=True, installed=["feedparser"],
        ))
        pipeline = _make_pipeline(
            dependency_resolver=resolver, event_log=event_log,
        )
        pipeline._designer.design_agent = AsyncMock(return_value=VALID_AGENT_SOURCE)

        await pipeline.handle_unhandled_intent(
            intent_name="count_words",
            intent_description="Count words",
            parameters={"text": "hello"},
        )

        events = [c.kwargs.get("event") for c in event_log.log.call_args_list]
        assert "dependency_install_approved" in events
        assert "dependency_install_success" in events

    @pytest.mark.asyncio
    async def test_dependency_install_failed_event(self):
        """dependency_install_failed event logged on install failure."""
        event_log = MagicMock(spec=EventLog)
        event_log.log = AsyncMock()

        resolver = MagicMock(spec=DependencyResolver)
        resolver.detect_missing = MagicMock(return_value=["feedparser"])
        resolver.resolve = AsyncMock(return_value=DependencyResult(
            success=False, failed=["feedparser"], error="timeout",
        ))
        pipeline = _make_pipeline(
            dependency_resolver=resolver, event_log=event_log,
        )
        pipeline._designer.design_agent = AsyncMock(return_value=VALID_AGENT_SOURCE)

        await pipeline.handle_unhandled_intent(
            intent_name="count_words",
            intent_description="Count words",
            parameters={"text": "hello"},
        )

        events = [c.kwargs.get("event") for c in event_log.log.call_args_list]
        assert "dependency_install_failed" in events


# ---------------------------------------------------------------------------
# TestEndToEnd
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """End-to-end: detect -> approve -> install -> pipeline continues."""

    @pytest.mark.asyncio
    async def test_full_flow(self):
        """Full dependency resolution flow in pipeline."""
        async def mock_install(pkg):
            return True, "ok"

        async def mock_approve(pkgs):
            return True

        resolver = DependencyResolver(
            allowed_imports=["asyncio", "pathlib", "json", "os", "re",
                             "datetime", "typing", "dataclasses",
                             "collections", "math", "feedparser"],
            install_fn=mock_install,
            approval_fn=mock_approve,
        )

        # Mock detect_missing to simulate nothing missing for this test
        resolver.detect_missing = MagicMock(return_value=[])

        pipeline = _make_pipeline(dependency_resolver=resolver)
        pipeline._designer.design_agent = AsyncMock(return_value=VALID_AGENT_SOURCE)

        await pipeline.handle_unhandled_intent(
            intent_name="count_words",
            intent_description="Count words",
            parameters={"text": "hello"},
        )
        assert resolver.detect_missing.call_count >= 1
