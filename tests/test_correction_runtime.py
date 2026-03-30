"""Tests for Phase 18b — Correction Runtime Integration (AD-231, AD-232, AD-233, AD-234, AD-235)."""

from __future__ import annotations

import dataclasses
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.agent_patcher import CorrectionResult, PatchResult
from probos.cognitive.correction_detector import CorrectionSignal
from probos.cognitive.feedback import FeedbackEngine, FeedbackResult
from probos.consensus.trust import TrustNetwork
from probos.mesh.routing import HebbianRouter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _FakeRecord:
    intent_name: str = "fetch_news"
    agent_type: str = "fetch_news"
    class_name: str = "FetchNewsAgent"
    source_code: str = "class FetchNewsAgent: pass"
    strategy: str = "new_agent"
    status: str = "active"


def _signal(**overrides) -> CorrectionSignal:
    defaults = dict(
        correction_type="url_fix",
        target_intent="fetch_news",
        target_agent_type="fetch_news",
        corrected_values={"url": "http://rss.cnn.com"},
        explanation="Use HTTP",
        confidence=0.9,
    )
    defaults.update(overrides)
    return CorrectionSignal(**defaults)


def _patch_result(**overrides) -> PatchResult:
    defaults = dict(
        success=True,
        patched_source="class FetchNewsAgent: pass  # patched",
        agent_class=type("FetchNewsAgent", (), {}),
        original_source="class FetchNewsAgent: pass",
        changes_description="Changed URL protocol",
    )
    defaults.update(overrides)
    return PatchResult(**defaults)


def _make_dag(intents=None):
    """Create a fake DAG with nodes."""
    class _N:
        def __init__(self, intent, status="completed", result=None, params=None):
            self.intent = intent
            self.status = status
            self.result = result or {}
            self.params = params or {}
            self.id = f"t_{intent}"
            self.depends_on = []

    class _DAG:
        def __init__(self, nodes):
            self.nodes = nodes

    nodes = [_N(i) for i in (intents or ["fetch_news"])]
    return _DAG(nodes)


def _attach_self_mod_manager(rt, pipeline=None):
    """AD-515: Attach a minimal SelfModManager for __new__-based tests."""
    from probos.self_mod_manager import SelfModManager
    mgr = SelfModManager.__new__(SelfModManager)
    mgr._self_mod_pipeline = pipeline or getattr(rt, 'self_mod_pipeline', None)
    mgr._last_execution = getattr(rt, '_last_execution', None)
    mgr._last_execution_text = getattr(rt, '_last_execution_text', None)
    rt.self_mod_manager = mgr
    return mgr


# ---------------------------------------------------------------------------
# find_designed_record
# ---------------------------------------------------------------------------


class TestFindDesignedRecord:
    """runtime.self_mod_manager.find_designed_record() tests."""

    def test_returns_most_recent_active_record(self):
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.self_mod_pipeline = MagicMock()
        r1 = _FakeRecord(status="active")
        r2 = _FakeRecord(status="active")
        rt.self_mod_pipeline._records = [r1, r2]
        _attach_self_mod_manager(rt)

        result = rt.self_mod_manager.find_designed_record("fetch_news")
        assert result is r2  # most recent (last in list)

    def test_returns_none_for_built_in_agent(self):
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.self_mod_pipeline = MagicMock()
        rt.self_mod_pipeline._records = [_FakeRecord(agent_type="other")]
        _attach_self_mod_manager(rt)

        result = rt.self_mod_manager.find_designed_record("http_fetch")
        assert result is None

    def test_returns_none_when_no_pipeline(self):
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.self_mod_pipeline = None
        # AD-515: self_mod_manager not set → no attribute → returns None
        rt.self_mod_manager = None
        assert rt.self_mod_manager is None

    def test_returns_patched_record(self):
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt.self_mod_pipeline = MagicMock()
        r = _FakeRecord(status="patched")
        rt.self_mod_pipeline._records = [r]
        _attach_self_mod_manager(rt)

        result = rt.self_mod_manager.find_designed_record("fetch_news")
        assert result is r


# ---------------------------------------------------------------------------
# was_last_execution_successful
# ---------------------------------------------------------------------------


class TestWasLastExecutionSuccessful:
    """runtime.self_mod_manager.was_last_execution_successful() tests."""

    def test_returns_false_when_no_execution(self):
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._last_execution = None
        rt.self_mod_manager = None

        assert rt.self_mod_manager is None

    def test_returns_true_when_all_completed(self):
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        dag = _make_dag(["a", "b"])
        rt._last_execution = {"dag": dag}
        mgr = _attach_self_mod_manager(rt)
        mgr._last_execution = rt._last_execution

        assert rt.self_mod_manager.was_last_execution_successful() is True

    def test_returns_false_when_node_failed(self):
        from probos.runtime import ProbOSRuntime

        class _N:
            def __init__(self, status):
                self.status = status
        class _D:
            def __init__(self):
                self.nodes = [_N("completed"), _N("failed")]

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._last_execution = {"dag": _D()}
        mgr = _attach_self_mod_manager(rt)
        mgr._last_execution = rt._last_execution

        assert rt.self_mod_manager.was_last_execution_successful() is False


# ---------------------------------------------------------------------------
# format_execution_context (AD-235)
# ---------------------------------------------------------------------------


class TestFormatExecutionContext:
    """runtime.self_mod_manager.format_execution_context() tests."""

    def test_returns_empty_when_no_execution(self):
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._last_execution = None
        rt.self_mod_manager = None

        assert rt.self_mod_manager is None

    def test_includes_prior_request_text(self):
        from probos.runtime import ProbOSRuntime

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._last_execution = {"dag": _make_dag(["http_fetch"])}
        rt._last_execution_text = "get news from CNN"
        mgr = _attach_self_mod_manager(rt)
        mgr._last_execution = rt._last_execution
        mgr._last_execution_text = rt._last_execution_text

        ctx = rt.self_mod_manager.format_execution_context()
        assert "get news from CNN" in ctx

    def test_includes_intent_and_params(self):
        from probos.runtime import ProbOSRuntime

        class _N:
            intent = "http_fetch"
            status = "completed"
            params = {"url": "http://rss.cnn.com"}
            result = {"output": "headlines"}
        class _D:
            nodes = [_N()]

        rt = ProbOSRuntime.__new__(ProbOSRuntime)
        rt._last_execution = {"dag": _D()}
        rt._last_execution_text = "get news"
        mgr = _attach_self_mod_manager(rt)
        mgr._last_execution = rt._last_execution
        mgr._last_execution_text = rt._last_execution_text

        ctx = rt.self_mod_manager.format_execution_context()
        assert "http_fetch" in ctx
        assert "http://rss.cnn.com" in ctx


# ---------------------------------------------------------------------------
# FeedbackEngine.apply_correction_feedback (AD-234)
# ---------------------------------------------------------------------------


class TestCorrectionFeedback:
    """FeedbackEngine.apply_correction_feedback() tests."""

    @pytest.mark.asyncio
    async def test_correction_applied_on_retry_success(self):
        """Successful retry → feedback_type=correction_applied."""
        trust = TrustNetwork()
        hebbian = HebbianRouter()
        engine = FeedbackEngine(trust_network=trust, hebbian_router=hebbian)

        result = await engine.apply_correction_feedback(
            original_text="get CNN news",
            correction=_signal(),
            patch_result=_patch_result(),
            retry_success=True,
        )

        assert result.feedback_type == "correction_applied"
        assert "fetch_news" in result.agents_updated

    @pytest.mark.asyncio
    async def test_correction_failed_on_retry_failure(self):
        """Failed retry → feedback_type=correction_failed."""
        trust = TrustNetwork()
        hebbian = HebbianRouter()
        engine = FeedbackEngine(trust_network=trust, hebbian_router=hebbian)

        result = await engine.apply_correction_feedback(
            original_text="get CNN news",
            correction=_signal(),
            patch_result=_patch_result(),
            retry_success=False,
        )

        assert result.feedback_type == "correction_failed"

    @pytest.mark.asyncio
    async def test_hebbian_strengthened_on_success(self):
        """Retry success → Hebbian route strengthened."""
        trust = TrustNetwork()
        hebbian = HebbianRouter()
        engine = FeedbackEngine(trust_network=trust, hebbian_router=hebbian)

        await engine.apply_correction_feedback(
            original_text="get CNN news",
            correction=_signal(),
            patch_result=_patch_result(),
            retry_success=True,
        )

        # Check that connection exists with positive weight
        weights = hebbian.all_weights_typed()
        intent_weights = {k: v for k, v in weights.items() if k[0] == "fetch_news"}
        assert len(intent_weights) > 0

    @pytest.mark.asyncio
    async def test_trust_updated_on_success(self):
        """Retry success → trust score increased."""
        trust = TrustNetwork()
        hebbian = HebbianRouter()
        engine = FeedbackEngine(trust_network=trust, hebbian_router=hebbian)

        baseline = trust.get_score("fetch_news")

        await engine.apply_correction_feedback(
            original_text="get CNN news",
            correction=_signal(),
            patch_result=_patch_result(),
            retry_success=True,
        )

        assert trust.get_score("fetch_news") > baseline

    @pytest.mark.asyncio
    async def test_trust_not_updated_on_failure(self):
        """Retry failure → no trust change."""
        trust = TrustNetwork()
        hebbian = HebbianRouter()
        engine = FeedbackEngine(trust_network=trust, hebbian_router=hebbian)

        baseline = trust.get_score("fetch_news")

        await engine.apply_correction_feedback(
            original_text="get CNN news",
            correction=_signal(),
            patch_result=_patch_result(),
            retry_success=False,
        )

        # Trust should not have been updated
        assert trust.get_score("fetch_news") == baseline

    @pytest.mark.asyncio
    async def test_episodic_memory_stored(self):
        """Correction episode stored in episodic memory."""
        trust = TrustNetwork()
        hebbian = HebbianRouter()
        episodic = AsyncMock()
        episodic.store = AsyncMock()
        engine = FeedbackEngine(
            trust_network=trust,
            hebbian_router=hebbian,
            episodic_memory=episodic,
        )

        await engine.apply_correction_feedback(
            original_text="get CNN news",
            correction=_signal(),
            patch_result=_patch_result(),
            retry_success=True,
        )

        episodic.store.assert_awaited_once()
        episode = episodic.store.call_args[0][0]
        assert episode.user_input == "get CNN news"
        assert any("correction_applied" in str(o) for o in episode.outcomes)

    @pytest.mark.asyncio
    async def test_event_log_recorded(self):
        """Correction event logged."""
        trust = TrustNetwork()
        hebbian = HebbianRouter()
        event_log = AsyncMock()
        event_log.log = AsyncMock()
        engine = FeedbackEngine(
            trust_network=trust,
            hebbian_router=hebbian,
            event_log=event_log,
        )

        await engine.apply_correction_feedback(
            original_text="get CNN news",
            correction=_signal(),
            patch_result=_patch_result(),
            retry_success=True,
        )

        event_log.log.assert_awaited_once()
        call_kwargs = event_log.log.call_args[1]
        assert call_kwargs["event"] == "feedback_correction_applied"


# ---------------------------------------------------------------------------
# /correct shell command (AD-233)
# ---------------------------------------------------------------------------


class TestCorrectShellCommand:
    """Shell /correct command tests."""

    def test_help_includes_correct(self):
        """COMMANDS dict includes /correct."""
        from probos.experience.shell import ProbOSShell
        assert "/correct" in ProbOSShell.COMMANDS

    def test_correct_description_present(self):
        """Description for /correct is present."""
        from probos.experience.shell import ProbOSShell
        desc = ProbOSShell.COMMANDS["/correct"]
        assert "correct" in desc.lower() or "Correct" in desc


# ---------------------------------------------------------------------------
# Correction runs before decompose (AD-232 fix)
# ---------------------------------------------------------------------------


class TestCorrectionBeforeDecompose:
    """Correction detection must fire before decomposer.decompose()."""

    @pytest.mark.asyncio
    async def test_successful_correction_skips_decompose(self):
        """When correction detection succeeds, decompose() is NOT called."""
        from probos.runtime import ProbOSRuntime
        from probos.cognitive.agent_patcher import CorrectionResult

        rt = ProbOSRuntime.__new__(ProbOSRuntime)

        # Minimal wiring required by process_natural_language preamble
        rt._last_feedback_applied = False
        rt._last_execution_text = "get news from CNN"
        rt._last_execution = {"dag": _make_dag(["fetch_news"])}
        rt._previous_execution = None
        rt._last_request_time = 0
        rt.dream_scheduler = None
        rt.attention = MagicMock()
        rt.working_memory = MagicMock()
        rt.working_memory.assemble = MagicMock(return_value=MagicMock(to_text=lambda: ""))
        rt.episodic_memory = None
        rt.capability_registry = MagicMock()
        rt.capability_registry._capabilities = {}
        rt.registry = MagicMock()
        rt.trust_network = MagicMock()
        rt.hebbian_router = MagicMock()

        # Correction detector returns a signal
        rt._correction_detector = AsyncMock()
        rt._correction_detector.detect = AsyncMock(return_value=_signal())

        # self_mod_manager with find_designed_record and apply_correction
        correction_result = CorrectionResult(
            success=True,
            agent_type="fetch_news",
            strategy="new_agent",
            changes_description="Fixed URL",
            retried=True,
            retry_result={"success": True},
        )
        mock_mgr = MagicMock()
        mock_mgr.find_designed_record = MagicMock(return_value=_FakeRecord())
        mock_mgr.was_last_execution_successful = MagicMock(return_value=True)
        mock_mgr.apply_correction = AsyncMock(return_value=correction_result)
        rt.self_mod_manager = mock_mgr

        # Patcher succeeds
        rt._agent_patcher = AsyncMock()
        rt._agent_patcher.patch = AsyncMock(return_value=_patch_result())

        # Decomposer — should NOT be called
        rt.decomposer = MagicMock()
        rt.decomposer.decompose = AsyncMock()
        rt.decomposer.pre_warm_intents = []

        result = await rt.process_natural_language("use http not https")

        # Correction should have been applied
        assert result is not None
        assert "correction" in result
        assert result["correction"]["success"] is True

        # Decomposer must NOT have been called
        rt.decomposer.decompose.assert_not_awaited()


# ---------------------------------------------------------------------------
# AgentDesigner execution_context (AD-235)
# ---------------------------------------------------------------------------


class TestAgentDesignerExecutionContext:
    """AgentDesigner.design_agent() execution_context parameter."""

    @pytest.mark.asyncio
    async def test_execution_context_included_in_prompt(self):
        """execution_context appears in the LLM prompt."""
        from probos.cognitive.agent_designer import AgentDesigner
        from probos.config import SelfModConfig

        class _MockLLM:
            def __init__(self):
                self.prompts = []
            async def complete(self, req):
                self.prompts.append(req.prompt)
                class _R:
                    content = "class TestAgent(CognitiveAgent): pass"
                    error = None
                return _R()

        llm = _MockLLM()
        config = SelfModConfig()
        designer = AgentDesigner(llm_client=llm, config=config)

        await designer.design_agent(
            intent_name="test_intent",
            intent_description="A test intent",
            parameters={"url": "str"},
            execution_context="Prior request used http://rss.cnn.com with success",
        )

        assert len(llm.prompts) == 1
        assert "http://rss.cnn.com" in llm.prompts[0]

    @pytest.mark.asyncio
    async def test_empty_execution_context_uses_default(self):
        """Empty execution_context → default message in prompt."""
        from probos.cognitive.agent_designer import AgentDesigner
        from probos.config import SelfModConfig

        class _MockLLM:
            def __init__(self):
                self.prompts = []
            async def complete(self, req):
                self.prompts.append(req.prompt)
                class _R:
                    content = "class TestAgent(CognitiveAgent): pass"
                    error = None
                return _R()

        llm = _MockLLM()
        config = SelfModConfig()
        designer = AgentDesigner(llm_client=llm, config=config)

        await designer.design_agent(
            intent_name="test_intent",
            intent_description="A test",
            parameters={},
        )

        assert "No prior execution context available" in llm.prompts[0]

    @pytest.mark.asyncio
    async def test_handle_unhandled_intent_passes_context(self):
        """SelfModificationPipeline passes execution_context through."""
        from probos.cognitive.self_mod import SelfModificationPipeline
        from probos.config import SelfModConfig

        calls = []

        class _MockDesigner:
            async def design_agent(self, **kwargs):
                calls.append(kwargs)
                return "class TestAgent(CognitiveAgent): pass"
            def _build_class_name(self, name):
                return "TestAgent"
            def _build_agent_type(self, name):
                return name

        class _MockValidator:
            def validate(self, src):
                return ["skip"]  # Force failure to avoid sandbox

        pipeline = SelfModificationPipeline.__new__(SelfModificationPipeline)
        pipeline._config = SelfModConfig(require_user_approval=False, research_enabled=False)
        pipeline._designer = _MockDesigner()
        pipeline._validator = _MockValidator()
        pipeline._sandbox = None
        pipeline._research = None
        pipeline._records = []
        pipeline._user_approval_fn = None
        pipeline._dependency_resolver = None

        await pipeline.handle_unhandled_intent(
            intent_name="test",
            intent_description="test desc",
            parameters={},
            execution_context="Prior exec used http://example.com",
        )

        assert len(calls) == 1
        assert calls[0].get("execution_context") == "Prior exec used http://example.com"
