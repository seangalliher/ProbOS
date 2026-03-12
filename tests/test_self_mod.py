"""Tests for Phase 10 — Self-Modification pipeline."""

from __future__ import annotations

import asyncio
import textwrap
import pytest

from probos.config import SelfModConfig, SystemConfig, load_config
from probos.cognitive.code_validator import CodeValidator


# ---------------------------------------------------------------------------
# Valid agent source code — used across multiple test classes
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


# ---------------------------------------------------------------------------
# TestSelfModConfig (tests 1-3)
# ---------------------------------------------------------------------------


class TestSelfModConfig:
    """SelfModConfig model default and override tests."""

    def test_defaults(self):
        cfg = SelfModConfig()
        assert cfg.enabled is False
        assert cfg.require_user_approval is True
        assert cfg.max_designed_agents == 5
        assert cfg.probationary_alpha == 1.0
        assert cfg.probationary_beta == 3.0
        assert cfg.sandbox_timeout_seconds == 60.0
        assert "asyncio" in cfg.allowed_imports
        assert "subprocess" in cfg.forbidden_patterns[0]

    def test_custom_values(self):
        cfg = SelfModConfig(
            enabled=True,
            require_user_approval=False,
            max_designed_agents=10,
            probationary_alpha=2.0,
            probationary_beta=2.0,
            sandbox_timeout_seconds=5.0,
        )
        assert cfg.enabled is True
        assert cfg.require_user_approval is False
        assert cfg.max_designed_agents == 10
        assert cfg.probationary_alpha == 2.0

    def test_system_config_includes_self_mod(self):
        sc = SystemConfig()
        assert hasattr(sc, "self_mod")
        assert isinstance(sc.self_mod, SelfModConfig)
        assert sc.self_mod.enabled is False


# ---------------------------------------------------------------------------
# TestCodeValidator (tests 8-19)
# ---------------------------------------------------------------------------


class TestCodeValidator:
    """CodeValidator static analysis tests."""

    def _make_validator(self) -> CodeValidator:
        return CodeValidator(SelfModConfig())

    def test_valid_agent_passes(self):
        """Test 8: Valid agent code passes all checks."""
        v = self._make_validator()
        errors = v.validate(VALID_AGENT_SOURCE)
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_syntax_error_detected(self):
        """Test 9: Syntax error detected."""
        v = self._make_validator()
        errors = v.validate("def foo(:\n    pass")
        assert len(errors) == 1
        assert "Syntax error" in errors[0]

    def test_forbidden_import_subprocess(self):
        """Test 10: Forbidden import subprocess detected."""
        v = self._make_validator()
        source = VALID_AGENT_SOURCE + "\nimport subprocess\n"
        errors = v.validate(source)
        forbidden = [e for e in errors if "subprocess" in e.lower()]
        assert len(forbidden) >= 1

    def test_forbidden_import_socket(self):
        """Test 11: Forbidden import socket detected."""
        v = self._make_validator()
        source = VALID_AGENT_SOURCE + "\nimport socket\n"
        errors = v.validate(source)
        forbidden = [e for e in errors if "socket" in e.lower()]
        assert len(forbidden) >= 1

    def test_allowed_imports_pass(self):
        """Test 12: Allowed imports (pathlib, json, re) pass."""
        v = self._make_validator()
        source = "import pathlib\nimport json\nimport re\n" + VALID_AGENT_SOURCE
        errors = v.validate(source)
        import_errors = [e for e in errors if "import" in e.lower()]
        assert import_errors == []

    def test_forbidden_pattern_eval(self):
        """Test 13: Forbidden pattern eval() detected."""
        v = self._make_validator()
        source = VALID_AGENT_SOURCE.replace(
            'count = len(text.split())',
            'count = eval("len(text.split())")',
        )
        errors = v.validate(source)
        pattern_errors = [e for e in errors if "eval" in e.lower()]
        assert len(pattern_errors) >= 1

    def test_forbidden_pattern_exec(self):
        """Test 14: Forbidden pattern exec() detected."""
        v = self._make_validator()
        source = VALID_AGENT_SOURCE.replace(
            'count = len(text.split())',
            'exec ("print(1)")',
        )
        errors = v.validate(source)
        pattern_errors = [e for e in errors if "exec" in e.lower()]
        assert len(pattern_errors) >= 1

    def test_forbidden_pattern_open_write(self):
        """Test 15: Forbidden pattern open with 'w' detected."""
        v = self._make_validator()
        source = VALID_AGENT_SOURCE + "\nx = open('/tmp/f', 'w')\n"
        errors = v.validate(source)
        pattern_errors = [e for e in errors if "open" in e.lower()]
        assert len(pattern_errors) >= 1

    def test_missing_base_agent_subclass(self):
        """Test 16: Missing BaseAgent subclass detected."""
        v = self._make_validator()
        source = textwrap.dedent('''\
            class Foo:
                pass
        ''')
        errors = v.validate(source)
        assert any("BaseAgent" in e for e in errors)

    def test_missing_intent_descriptors(self):
        """Test 17: Missing intent_descriptors detected."""
        v = self._make_validator()
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentMessage, IntentResult

            class TestAgent(BaseAgent):
                agent_type = "test"
                _handled_intents = ["test"]

                async def handle_intent(self, intent):
                    return None

                async def perceive(self, intent):
                    return None

                async def decide(self, obs):
                    return None

                async def act(self, plan):
                    return None

                async def report(self, result):
                    return result
        ''')
        errors = v.validate(source)
        assert any("intent_descriptors" in e for e in errors)

    def test_missing_handle_intent_method(self):
        """Test 18: Missing handle_intent method detected."""
        v = self._make_validator()
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentDescriptor

            class TestAgent(BaseAgent):
                agent_type = "test"
                _handled_intents = ["test"]
                intent_descriptors = [
                    IntentDescriptor(name="test", params={}, description="test")
                ]

                async def perceive(self, intent):
                    return None

                async def decide(self, obs):
                    return None

                async def act(self, plan):
                    return None

                async def report(self, result):
                    return result
        ''')
        errors = v.validate(source)
        assert any("handle_intent" in e for e in errors)

    def test_module_level_side_effect(self):
        """Test 19: Module-level side effect (bare function call) detected."""
        v = self._make_validator()
        source = "print('hello')\n" + VALID_AGENT_SOURCE
        errors = v.validate(source)
        assert any("side effect" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# TestAgentDesigner (tests 4-7)
# ---------------------------------------------------------------------------


class TestAgentDesigner:
    """AgentDesigner code generation tests."""

    @pytest.fixture
    def designer(self):
        from probos.cognitive.agent_designer import AgentDesigner
        from probos.cognitive.llm_client import MockLLMClient
        llm = MockLLMClient()
        return AgentDesigner(llm, SelfModConfig())

    @pytest.mark.asyncio
    async def test_design_agent_returns_valid_source(self, designer):
        """Test 4: design_agent returns valid Python source code via MockLLMClient."""
        source = await designer.design_agent(
            intent_name="count_words",
            intent_description="Count the number of words",
            parameters={"text": "input text"},
        )
        assert "class CountWordsAgent" in source
        assert "CognitiveAgent" in source
        # Verify it's valid Python
        import ast
        ast.parse(source)

    def test_class_name_derivation(self, designer):
        """Test 5: Class name correctly derived from intent name."""
        assert designer._build_class_name("count_words") == "CountWordsAgent"
        assert designer._build_class_name("parse_json") == "ParseJsonAgent"
        assert designer._build_class_name("calculate_checksum") == "CalculateChecksumAgent"

    def test_agent_type_derivation(self, designer):
        """Test 6: Agent type correctly derived from intent name."""
        assert designer._build_agent_type("count_words") == "count_words"
        assert designer._build_agent_type("parse_json") == "parse_json"

    @pytest.mark.asyncio
    async def test_design_prompt_includes_allowed_imports(self, designer):
        """Test 7: Design prompt includes allowed_imports whitelist."""
        from probos.cognitive.agent_designer import AGENT_DESIGN_PROMPT
        # The prompt template has {allowed_imports} placeholder
        assert "{allowed_imports}" in AGENT_DESIGN_PROMPT


# ---------------------------------------------------------------------------
# TestSandboxRunner (tests 20-24)
# ---------------------------------------------------------------------------


class TestSandboxRunner:
    """SandboxRunner isolated execution tests."""

    @pytest.fixture
    def runner(self):
        from probos.cognitive.sandbox import SandboxRunner
        return SandboxRunner(SelfModConfig(sandbox_timeout_seconds=5.0))

    @pytest.mark.asyncio
    async def test_valid_agent_loads_and_handles_intent(self, runner):
        """Test 20: Valid agent loads and handles test intent successfully."""
        result = await runner.test_agent(
            VALID_AGENT_SOURCE,
            intent_name="count_words",
            test_params={"text": "hello world foo"},
        )
        assert result.success is True
        assert result.agent_class is not None
        assert result.error is None
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_agent_that_raises_exception(self, runner):
        """Test 21: Agent that raises exception returns success=False."""
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentMessage, IntentResult, IntentDescriptor

            class BadAgent(BaseAgent):
                agent_type = "bad"
                _handled_intents = ["bad"]
                intent_descriptors = [
                    IntentDescriptor(name="bad", params={}, description="bad agent")
                ]

                async def perceive(self, intent):
                    return intent

                async def decide(self, obs):
                    return obs

                async def act(self, plan):
                    raise RuntimeError("Intentional error")

                async def report(self, result):
                    return result

                async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
                    raise RuntimeError("Intentional error")
        ''')
        result = await runner.test_agent(source, "bad")
        assert result.success is False
        assert result.error is not None
        assert "error" in result.error.lower() or "RuntimeError" in result.error

    @pytest.mark.asyncio
    async def test_agent_timeout(self, runner):
        """Test 22: Agent that times out returns success=False."""
        from probos.cognitive.sandbox import SandboxRunner
        fast_runner = SandboxRunner(SelfModConfig(sandbox_timeout_seconds=0.1))
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
        result = await fast_runner.test_agent(source, "slow")
        assert result.success is False
        assert "timeout" in result.error.lower() or "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_agent_wrong_return_type(self, runner):
        """Test 23: Agent that returns wrong type returns success=False."""
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentMessage, IntentResult, IntentDescriptor

            class WrongTypeAgent(BaseAgent):
                agent_type = "wrong_type"
                _handled_intents = ["wrong_type"]
                intent_descriptors = [
                    IntentDescriptor(name="wrong_type", params={}, description="wrong")
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
        result = await runner.test_agent(source, "wrong_type")
        assert result.success is False
        assert "IntentResult" in result.error

    @pytest.mark.asyncio
    async def test_loaded_class_is_base_agent_subclass(self, runner):
        """Test 24: Loaded class is a proper BaseAgent subclass."""
        from probos.substrate.agent import BaseAgent
        result = await runner.test_agent(
            VALID_AGENT_SOURCE,
            intent_name="count_words",
            test_params={"text": "hello"},
        )
        assert result.success is True
        assert issubclass(result.agent_class, BaseAgent)


# ---------------------------------------------------------------------------
# TestBehavioralMonitor (tests 25-30)
# ---------------------------------------------------------------------------


class TestBehavioralMonitor:
    """BehavioralMonitor anomaly detection tests."""

    @pytest.fixture
    def monitor(self):
        from probos.cognitive.behavioral_monitor import BehavioralMonitor
        return BehavioralMonitor()

    def test_track_agent_type(self, monitor):
        """Test 25: track_agent_type registers agent for monitoring."""
        monitor.track_agent_type("count_words")
        assert "count_words" in monitor._tracked_agents
        assert monitor._execution_times["count_words"] == []
        assert monitor._success_counts["count_words"] == 0

    def test_record_execution_tracks_counts(self, monitor):
        """Test 26: record_execution tracks success/failure counts."""
        monitor.track_agent_type("count_words")
        monitor.record_execution("count_words", 10.0, True)
        monitor.record_execution("count_words", 15.0, False)
        monitor.record_execution("count_words", 12.0, True)
        assert monitor._success_counts["count_words"] == 2
        assert monitor._failure_counts["count_words"] == 1
        assert len(monitor._execution_times["count_words"]) == 3

    def test_high_failure_rate_alert(self, monitor):
        """Test 27: High failure rate triggers alert."""
        monitor.track_agent_type("bad_agent")
        # Record 6 failures and 1 success (> 50% failure rate, >= 5 executions)
        for _ in range(6):
            monitor.record_execution("bad_agent", 10.0, False)
        monitor.record_execution("bad_agent", 10.0, True)
        alerts = monitor.get_alerts("bad_agent")
        failure_alerts = [a for a in alerts if a.alert_type == "high_failure_rate"]
        assert len(failure_alerts) >= 1

    def test_slow_execution_alert(self, monitor):
        """Test 28: Slow execution triggers alert."""
        monitor.track_agent_type("slow_agent")
        # Record 3 slow executions (> 5000ms average)
        for _ in range(3):
            monitor.record_execution("slow_agent", 10000.0, True)
        alerts = monitor.get_alerts("slow_agent")
        slow_alerts = [a for a in alerts if a.alert_type == "slow_execution"]
        assert len(slow_alerts) >= 1

    def test_recommend_removal_high_failure(self, monitor):
        """Test 29: should_recommend_removal True when failure rate > 50% over 10+."""
        monitor.track_agent_type("bad_agent")
        for _ in range(8):
            monitor.record_execution("bad_agent", 10.0, False)
        for _ in range(4):
            monitor.record_execution("bad_agent", 10.0, True)
        # 8 failures / 12 total = 66% failure rate, > 10 executions
        assert monitor.should_recommend_removal("bad_agent") is True

    def test_recommend_removal_performing_well(self, monitor):
        """Test 30: should_recommend_removal False when agent performing well."""
        monitor.track_agent_type("good_agent")
        for _ in range(15):
            monitor.record_execution("good_agent", 10.0, True)
        assert monitor.should_recommend_removal("good_agent") is False


# ---------------------------------------------------------------------------
# TestProbationaryTrust (tests 31-33)
# ---------------------------------------------------------------------------


class TestProbationaryTrust:
    """Tests for create_with_prior() on TrustNetwork."""

    def test_create_with_prior_custom_alpha_beta(self):
        """Test 31: create_with_prior creates record with custom alpha/beta."""
        from probos.consensus.trust import TrustNetwork
        tn = TrustNetwork()
        tn.create_with_prior("agent-1", alpha=1.0, beta=3.0)
        record = tn.get_record("agent-1")
        assert record is not None
        assert record.alpha == 1.0
        assert record.beta == 3.0

    def test_create_with_prior_noop_if_exists(self):
        """Test 32: create_with_prior is no-op if record exists."""
        from probos.consensus.trust import TrustNetwork
        tn = TrustNetwork()
        tn.get_or_create("agent-1")  # Creates with default prior (2,2)
        tn.create_with_prior("agent-1", alpha=1.0, beta=3.0)
        record = tn.get_record("agent-1")
        assert record.alpha == 2.0  # Unchanged
        assert record.beta == 2.0

    def test_probationary_trust_score(self):
        """Test 33: Probationary agent has E[trust] = 0.25 (alpha=1, beta=3)."""
        from probos.consensus.trust import TrustNetwork
        tn = TrustNetwork()
        tn.create_with_prior("agent-1", alpha=1.0, beta=3.0)
        score = tn.get_score("agent-1")
        assert abs(score - 0.25) < 0.001


# ---------------------------------------------------------------------------
# TestSelfModPipeline (tests 34-38)
# ---------------------------------------------------------------------------


class TestSelfModPipeline:
    """SelfModificationPipeline end-to-end tests."""

    def _make_pipeline(self, **overrides):
        """Create a pipeline with mock callables."""
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

        registered_types = []
        created_pools = []
        trust_set = []

        async def register_fn(agent_class):
            registered_types.append(agent_class)

        async def create_pool_fn(agent_type, pool_name, size=2):
            created_pools.append((agent_type, pool_name, size))

        async def set_trust_fn(agent_ids):
            trust_set.extend(agent_ids)

        pipeline = SelfModificationPipeline(
            designer=designer,
            validator=validator,
            sandbox=sandbox,
            monitor=monitor,
            config=config,
            register_fn=overrides.get("register_fn", register_fn),
            create_pool_fn=overrides.get("create_pool_fn", create_pool_fn),
            set_trust_fn=overrides.get("set_trust_fn", set_trust_fn),
            user_approval_fn=overrides.get("user_approval_fn"),
        )
        return pipeline, {
            "registered": registered_types,
            "pools": created_pools,
            "trust": trust_set,
            "monitor": monitor,
        }

    @pytest.mark.asyncio
    async def test_full_pipeline_end_to_end(self):
        """Test 34: Full pipeline: design -> validate -> sandbox -> register."""
        pipeline, mocks = self._make_pipeline()
        record = await pipeline.handle_unhandled_intent(
            intent_name="count_words",
            intent_description="Count the number of words",
            parameters={"text": "input text"},
        )
        assert record is not None
        assert record.status == "active"
        assert record.agent_type == "count_words"
        assert record.class_name == "CountWordsAgent"
        assert len(record.source_code) > 0
        assert len(mocks["registered"]) == 1
        assert len(mocks["pools"]) == 1
        assert mocks["pools"][0][1] == "designed_count_words"

    @pytest.mark.asyncio
    async def test_pipeline_validation_failure(self):
        """Test 35: Pipeline stops at validation failure."""
        from probos.cognitive.agent_designer import AgentDesigner
        from probos.cognitive.behavioral_monitor import BehavioralMonitor
        from probos.cognitive.code_validator import CodeValidator
        from probos.cognitive.sandbox import SandboxRunner
        from probos.cognitive.self_mod import SelfModificationPipeline
        from probos.cognitive.llm_client import MockLLMClient

        config = SelfModConfig(enabled=True, require_user_approval=False)

        # Create a mock LLM that returns code with forbidden import
        class BadDesignLLM(MockLLMClient):
            async def complete(self, request):
                from probos.types import LLMResponse
                return LLMResponse(
                    content="import subprocess\nclass Foo:\n    pass\n",
                    model="mock", tier="standard",
                    tokens_used=10, cached=False,
                    request_id=request.id,
                )

        llm = BadDesignLLM()
        designer = AgentDesigner(llm, config)

        async def noop(*a, **k): pass

        pipeline = SelfModificationPipeline(
            designer=designer,
            validator=CodeValidator(config),
            sandbox=SandboxRunner(config),
            monitor=BehavioralMonitor(),
            config=config,
            register_fn=noop,
            create_pool_fn=noop,
            set_trust_fn=noop,
        )
        record = await pipeline.handle_unhandled_intent("bad", "bad intent", {})
        assert record is None
        records = pipeline.designed_agents()
        assert len(records) == 1
        assert records[0].status == "failed_validation"

    @pytest.mark.asyncio
    async def test_pipeline_sandbox_failure(self):
        """Test 36: Pipeline stops at sandbox failure."""
        from probos.cognitive.agent_designer import AgentDesigner
        from probos.cognitive.behavioral_monitor import BehavioralMonitor
        from probos.cognitive.code_validator import CodeValidator
        from probos.cognitive.sandbox import SandboxRunner
        from probos.cognitive.self_mod import SelfModificationPipeline
        from probos.cognitive.llm_client import MockLLMClient

        config = SelfModConfig(enabled=True, require_user_approval=False, sandbox_timeout_seconds=0.1)

        # Create a mock LLM that returns code that hangs in handle_intent
        class HangingDesignLLM(MockLLMClient):
            async def complete(self, request):
                from probos.types import LLMResponse
                code = textwrap.dedent('''\
                    import asyncio
                    from probos.substrate.agent import BaseAgent
                    from probos.types import IntentMessage, IntentResult, IntentDescriptor

                    class HangAgent(BaseAgent):
                        agent_type = "hang"
                        _handled_intents = ["hang"]
                        intent_descriptors = [
                            IntentDescriptor(name="hang", params={}, description="hangs")
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
                return LLMResponse(
                    content=code, model="mock", tier="standard",
                    tokens_used=10, cached=False, request_id=request.id,
                )

        llm = HangingDesignLLM()
        designer = AgentDesigner(llm, config)

        async def noop(*a, **k): pass

        pipeline = SelfModificationPipeline(
            designer=designer,
            validator=CodeValidator(config),
            sandbox=SandboxRunner(config),
            monitor=BehavioralMonitor(),
            config=config,
            register_fn=noop,
            create_pool_fn=noop,
            set_trust_fn=noop,
        )
        record = await pipeline.handle_unhandled_intent("hang", "hangs", {})
        assert record is None
        records = pipeline.designed_agents()
        assert len(records) == 1
        assert records[0].status == "failed_sandbox"

    @pytest.mark.asyncio
    async def test_pipeline_user_rejection(self):
        """Test 37: Pipeline stops at user rejection."""
        async def reject_fn(description: str) -> bool:
            return False

        pipeline, mocks = self._make_pipeline(
            config=SelfModConfig(enabled=True, require_user_approval=True),
            user_approval_fn=reject_fn,
        )
        record = await pipeline.handle_unhandled_intent("test", "test", {})
        assert record is None
        records = pipeline.designed_agents()
        assert len(records) == 1
        assert records[0].status == "rejected_by_user"

    @pytest.mark.asyncio
    async def test_pipeline_max_designed_agents_limit(self):
        """Test 38: Pipeline respects max_designed_agents limit."""
        pipeline, mocks = self._make_pipeline(
            config=SelfModConfig(
                enabled=True,
                require_user_approval=False,
                max_designed_agents=1,
            ),
        )
        # First should succeed
        r1 = await pipeline.handle_unhandled_intent("count_words", "count words", {"text": "x"})
        assert r1 is not None
        assert r1.status == "active"

        # Second should be blocked by limit
        r2 = await pipeline.handle_unhandled_intent("parse_json", "parse json", {"text": "x"})
        assert r2 is None


# ---------------------------------------------------------------------------
# TestRuntimeSelfMod (tests 39-42)
# ---------------------------------------------------------------------------


class TestRuntimeSelfMod:
    """Runtime self-modification wiring tests."""

    @pytest.fixture
    def _runtime_env(self, tmp_path):
        """Create a ProbOSRuntime with self_mod enabled."""
        from probos.config import SystemConfig, SelfModConfig
        from probos.runtime import ProbOSRuntime
        config = SystemConfig(
            self_mod=SelfModConfig(
                enabled=True,
                require_user_approval=False,
            ),
        )
        rt = ProbOSRuntime(config=config, data_dir=tmp_path)
        return rt

    @pytest.fixture
    def _runtime_disabled(self, tmp_path):
        """Create a ProbOSRuntime with self_mod disabled."""
        from probos.config import SystemConfig, SelfModConfig
        from probos.runtime import ProbOSRuntime
        config = SystemConfig(
            self_mod=SelfModConfig(enabled=False),
        )
        rt = ProbOSRuntime(config=config, data_dir=tmp_path)
        return rt

    @pytest.mark.asyncio
    async def test_runtime_creates_pipeline_when_enabled(self, _runtime_env):
        """Test 39: Runtime creates pipeline when self_mod.enabled=True."""
        rt = _runtime_env
        await rt.start()
        try:
            assert rt.self_mod_pipeline is not None
            assert rt.behavioral_monitor is not None
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_runtime_no_pipeline_when_disabled(self, _runtime_disabled):
        """Test 40: Runtime does NOT create pipeline when self_mod.enabled=False."""
        rt = _runtime_disabled
        await rt.start()
        try:
            assert rt.self_mod_pipeline is None
            assert rt.behavioral_monitor is None
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_status_includes_self_mod(self, _runtime_env):
        """Test 42: status() includes self_mod info."""
        rt = _runtime_env
        await rt.start()
        try:
            status = rt.status()
            assert "self_mod" in status
            assert "designed_agents" in status["self_mod"]
        finally:
            await rt.stop()

    @pytest.mark.asyncio
    async def test_extract_unhandled_intent(self, _runtime_env):
        """Test 41: _extract_unhandled_intent returns valid metadata."""
        rt = _runtime_env
        await rt.start()
        try:
            meta = await rt._extract_unhandled_intent("count all the words in this text")
            assert meta is not None
            assert "name" in meta
            assert "description" in meta
        finally:
            await rt.stop()


# ---------------------------------------------------------------------------
# TestDesignedPanels (tests 43-44)
# ---------------------------------------------------------------------------


class TestDesignedPanels:
    """Tests for /designed command and render_designed_panel."""

    def test_render_designed_panel_with_agents(self):
        """Test 43: render_designed_panel shows agent records."""
        from probos.experience.panels import render_designed_panel
        status = {
            "designed_agents": [
                {
                    "intent_name": "count_words",
                    "agent_type": "count_words",
                    "class_name": "CountWordsAgent",
                    "status": "active",
                    "created_at": 12345.0,
                    "sandbox_time_ms": 15.0,
                    "pool_name": "designed_count_words",
                },
            ],
            "active_count": 1,
            "max_designed_agents": 5,
        }
        panel = render_designed_panel(status)
        assert panel is not None
        assert "Designed Agents" in panel.title

    @pytest.mark.asyncio
    async def test_designed_command(self, tmp_path):
        """Test 44: /designed command renders panel (or 'not enabled')."""
        from probos.config import SystemConfig, SelfModConfig
        from probos.runtime import ProbOSRuntime
        from probos.experience.shell import ProbOSShell
        from rich.console import Console
        from io import StringIO

        # Test with self_mod disabled
        config = SystemConfig(self_mod=SelfModConfig(enabled=False))
        rt = ProbOSRuntime(config=config, data_dir=tmp_path)
        await rt.start()
        try:
            output = StringIO()
            shell = ProbOSShell(rt, console=Console(file=output, force_terminal=True))
            await shell.execute_command("/designed")
            assert "not enabled" in output.getvalue().lower() or "Self-modification" in output.getvalue()
        finally:
            await rt.stop()
