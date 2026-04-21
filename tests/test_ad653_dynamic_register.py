"""AD-653: Dynamic Communication Register — 'Speak Freely' Protocol."""
import pytest
from unittest.mock import AsyncMock

from probos.cognitive.sub_task import SubTaskResult, SubTaskType
from probos.cognitive.sub_tasks.compose import (
    _build_proactive_compose_prompt,
    _build_ward_room_compose_prompt,
    _should_short_circuit,
)
from probos.cognitive.sub_tasks.analyze import (
    _build_thread_analysis_prompt,
    _build_situation_review_prompt,
)
from probos.events import EventType


def _make_prior_results(intended_actions=None):
    """Build a prior_results list with an ANALYZE result."""
    result = {
        "composition_brief": {
            "situation": "Test situation",
            "key_evidence": "Test evidence",
            "response_should_cover": "Test coverage",
            "tone": "professional",
            "sources_to_draw_on": "episodic memory",
        },
        "contribution_assessment": "RESPOND",
    }
    if intended_actions is not None:
        result["intended_actions"] = intended_actions
    return [SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze-test",
        success=True,
        result=result,
    )]


# ---------------------------------------------------------------------------
# 1. ANALYZE Prompt Integration (3 tests)
# ---------------------------------------------------------------------------

class TestAnalyzePromptSpeakFreely:
    """Verify speak_freely appears in ANALYZE intended_actions instructions."""

    def test_thread_analysis_prompt_includes_speak_freely_option(self):
        ctx = {"context": "test", "mode": "ward_room_notification"}
        _, user_prompt = _build_thread_analysis_prompt(ctx, [], "Keiko", "medical")
        assert "speak_freely" in user_prompt

    def test_situation_review_prompt_includes_speak_freely_option(self):
        ctx = {"context": "test", "mode": "proactive_observation"}
        _, user_prompt = _build_situation_review_prompt(ctx, [], "Keiko", "medical")
        assert "speak_freely" in user_prompt

    def test_dm_comprehension_prompt_does_not_include_speak_freely(self):
        """DMs are already informal — speak_freely not offered."""
        from probos.cognitive.sub_tasks.analyze import _build_dm_comprehension_prompt
        ctx = {"context": "test", "mode": "direct_message"}
        _, user_prompt = _build_dm_comprehension_prompt(ctx, [], "Keiko", "medical")
        assert "speak_freely" not in user_prompt


# ---------------------------------------------------------------------------
# 2. Trust-Gated Authorization (6 tests)
# ---------------------------------------------------------------------------

class TestTrustGatedSpeakFreely:
    """Verify trust-gated authorization for speak_freely."""

    def test_speak_freely_auto_granted_high_trust(self):
        """High-trust agent (>=0.7) gets SPEAK FREELY auto-granted."""
        emitted = []
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
            "_trust_score": 0.85,
            "_emit_event_fn": lambda et, d: emitted.append((et, d)),
            "_agent_id": "test-agent",
        }
        prior = _make_prior_results(intended_actions=["ward_room_post", "speak_freely"])
        system, _ = _build_proactive_compose_prompt(ctx, prior, "Keiko", "medical")
        assert "SPEAK FREELY — GRANTED" in system
        assert "flagged for review" not in system
        assert len(emitted) == 1
        assert emitted[0][0] == EventType.REGISTER_SHIFT_GRANTED
        assert emitted[0][1]["authorization"] == "auto"

    def test_speak_freely_flagged_mid_trust(self):
        """Mid-trust agent (0.4-0.7) gets SPEAK FREELY but flagged."""
        emitted = []
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
            "_trust_score": 0.55,
            "_emit_event_fn": lambda et, d: emitted.append((et, d)),
            "_agent_id": "test-agent",
        }
        prior = _make_prior_results(intended_actions=["ward_room_post", "speak_freely"])
        system, _ = _build_proactive_compose_prompt(ctx, prior, "Keiko", "medical")
        assert "SPEAK FREELY — GRANTED (flagged for review)" in system
        assert len(emitted) == 1
        assert emitted[0][0] == EventType.REGISTER_SHIFT_GRANTED
        assert emitted[0][1]["authorization"] == "flagged"

    def test_speak_freely_denied_low_trust(self):
        """Low-trust agent (<0.4) gets SPEAK FREELY denied — no prompt change."""
        emitted = []
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
            "_trust_score": 0.3,
            "_emit_event_fn": lambda et, d: emitted.append((et, d)),
            "_agent_id": "test-agent",
        }
        prior = _make_prior_results(intended_actions=["ward_room_post", "speak_freely"])
        system, _ = _build_proactive_compose_prompt(ctx, prior, "Keiko", "medical")
        assert "SPEAK FREELY" not in system
        assert len(emitted) == 1
        assert emitted[0][0] == EventType.REGISTER_SHIFT_DENIED
        assert emitted[0][1]["reason"] == "trust_below_threshold"

    def test_speak_freely_ward_room_response_high_trust(self):
        """Ward room compose also grants speak_freely for high-trust agents."""
        emitted = []
        ctx = {
            "context": "test",
            "mode": "ward_room_notification",
            "_trust_score": 0.85,
            "_emit_event_fn": lambda et, d: emitted.append((et, d)),
            "_agent_id": "test-agent",
        }
        prior = _make_prior_results(intended_actions=["ward_room_reply", "speak_freely"])
        system, _ = _build_ward_room_compose_prompt(ctx, prior, "Keiko", "medical")
        assert "SPEAK FREELY — GRANTED" in system
        assert len(emitted) == 1
        assert emitted[0][0] == EventType.REGISTER_SHIFT_GRANTED

    def test_speak_freely_ward_room_response_denied_low_trust(self):
        """Ward room compose denies speak_freely for low-trust agents."""
        emitted = []
        ctx = {
            "context": "test",
            "mode": "ward_room_notification",
            "_trust_score": 0.3,
            "_emit_event_fn": lambda et, d: emitted.append((et, d)),
            "_agent_id": "test-agent",
        }
        prior = _make_prior_results(intended_actions=["ward_room_reply", "speak_freely"])
        system, _ = _build_ward_room_compose_prompt(ctx, prior, "Keiko", "medical")
        assert "SPEAK FREELY" not in system
        assert len(emitted) == 1
        assert emitted[0][0] == EventType.REGISTER_SHIFT_DENIED

    def test_no_speak_freely_without_intended_action(self):
        """No speak_freely injection when not in intended_actions (even high trust)."""
        emitted = []
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
            "_trust_score": 0.9,
            "_emit_event_fn": lambda et, d: emitted.append((et, d)),
            "_agent_id": "test-agent",
        }
        prior = _make_prior_results(intended_actions=["ward_room_post"])
        system, _ = _build_proactive_compose_prompt(ctx, prior, "Keiko", "medical")
        assert "SPEAK FREELY" not in system
        assert len(emitted) == 0


# ---------------------------------------------------------------------------
# 3. Short-Circuit Guard (2 tests)
# ---------------------------------------------------------------------------

class TestShortCircuitGuard:
    """Verify speak_freely doesn't trigger short-circuit."""

    def test_speak_freely_does_not_trigger_short_circuit(self):
        prior = _make_prior_results(intended_actions=["ward_room_reply", "speak_freely"])
        assert _should_short_circuit(prior) is False

    def test_silent_still_short_circuits(self):
        prior = _make_prior_results(intended_actions=["silent"])
        assert _should_short_circuit(prior) is True


# ---------------------------------------------------------------------------
# 4. Event Types (1 test)
# ---------------------------------------------------------------------------

class TestEventTypes:
    """Verify register shift event types exist."""

    def test_register_shift_event_types_exist(self):
        assert EventType.REGISTER_SHIFT_GRANTED.value == "register_shift_granted"
        assert EventType.REGISTER_SHIFT_DENIED.value == "register_shift_denied"


# ---------------------------------------------------------------------------
# 5. Counselor Subscription (2 tests)
# ---------------------------------------------------------------------------

class TestCounselorRegisterShift:
    """Verify Counselor subscribes to and handles register shift events."""

    def test_counselor_subscribes_to_register_shift_events(self):
        """REGISTER_SHIFT events in Counselor subscription list."""
        import inspect
        from probos.cognitive.counselor import CounselorAgent
        source = inspect.getsource(CounselorAgent)
        assert "REGISTER_SHIFT_GRANTED" in source
        assert "REGISTER_SHIFT_DENIED" in source

    @pytest.mark.asyncio
    async def test_counselor_handles_register_shift_event(self):
        """Handler runs without error for flagged shift."""
        from probos.cognitive.counselor import CounselorAgent
        from probos.cognitive.llm_client import BaseLLMClient

        agent = CounselorAgent(llm_client=AsyncMock(spec=BaseLLMClient))
        # Should not raise
        await agent._on_register_shift({
            "agent_id": "test-agent",
            "trust": 0.55,
            "authorization": "flagged",
            "from_register": "department_discussion",
            "to_register": "speak_freely",
        })
