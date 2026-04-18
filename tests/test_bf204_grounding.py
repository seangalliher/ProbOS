"""BF-204: Evaluate Grounding Criterion tests.

Deterministic grounding pre-check, defense ordering (SAFETY > OBLIGATION > TRUST),
LLM grounding criterion in prompt builders, and reflect grounding reminder.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.evaluate import (
    EvaluateHandler,
    _build_ward_room_eval_prompt,
    _build_proactive_eval_prompt,
    _build_notebook_eval_prompt,
)
from probos.cognitive.sub_tasks.reflect import (
    ReflectHandler,
    _build_ward_room_reflect_prompt,
    _build_proactive_reflect_prompt,
    _build_general_reflect_prompt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compose_result(output: str = "Test output") -> SubTaskResult:
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose",
        result={"output": output},
        tokens_used=100,
        duration_ms=50,
        success=True,
        tier_used="fast",
    )


def _eval_result_suppress() -> SubTaskResult:
    """An EVALUATE result that recommends suppression."""
    return SubTaskResult(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate",
        result={
            "pass": False,
            "score": 0.0,
            "criteria": {"grounding": {"pass": False, "reason": "fabricated"}},
            "recommendation": "suppress",
            "rejection_reason": "confabulation_detected",
        },
        tokens_used=0,
        duration_ms=10,
        success=True,
        tier_used="",
    )


def _eval_result_approve() -> SubTaskResult:
    """An EVALUATE result that approves."""
    return SubTaskResult(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate",
        result={
            "pass": True,
            "score": 0.8,
            "criteria": {},
            "recommendation": "approve",
        },
        tokens_used=50,
        duration_ms=100,
        success=True,
        tier_used="fast",
    )


def _eval_spec(mode: str = "ward_room_quality") -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate",
        prompt_template=mode,
        tier="fast",
    )


def _reflect_spec(mode: str = "ward_room_reflection") -> SubTaskSpec:
    return SubTaskSpec(
        sub_task_type=SubTaskType.REFLECT,
        name="reflect",
        prompt_template=mode,
        tier="fast",
    )


def _base_context(**overrides) -> dict:
    ctx = {
        "_agent_type": "science_agent",
        "_callsign": "Kira",
        "_department": "science",
        "context": "Some thread content",
    }
    ctx.update(overrides)
    return ctx


def _mock_llm_response(content: str = '{"pass": true, "score": 0.8, "criteria": {}, "recommendation": "approve"}'):
    resp = MagicMock()
    resp.content = content
    resp.tokens_used = 50
    resp.tier = "fast"
    return resp


# ===========================================================================
# Deterministic grounding check tests (8)
# ===========================================================================

class TestDeterministicGroundingCheck:
    @pytest.mark.asyncio
    async def test_two_ungrounded_hex_ids_suppressed(self):
        """Compose output with 2+ hex IDs not in source -> suppress."""
        handler = EvaluateHandler(llm_client=AsyncMock())
        ctx = _base_context(context="Clean thread content, no hex IDs")
        compose = _compose_result(
            "I found thread f8a9e2b7 showing a synchronization event "
            "at timestamp 3c4d5e6f with 200ms latency."
        )
        result = await handler(_eval_spec(), ctx, [compose])

        assert result.success is True
        assert result.result["recommendation"] == "suppress"
        assert result.result["rejection_reason"] == "confabulation_detected"
        assert result.result["pass"] is False
        assert result.tokens_used == 0

    @pytest.mark.asyncio
    async def test_hex_ids_in_source_no_false_positive(self):
        """Hex IDs present in source material -> passes."""
        handler = EvaluateHandler(llm_client=AsyncMock())
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_mock_llm_response())
        handler = EvaluateHandler(llm_client=llm)
        ctx = _base_context(
            context="Thread f8a9e2b7 discussed event 3c4d5e6f earlier"
        )
        compose = _compose_result(
            "Building on thread f8a9e2b7, the event 3c4d5e6f shows latency."
        )
        result = await handler(_eval_spec(), ctx, [compose])

        # Should NOT be caught by grounding check
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_one_hex_id_below_threshold(self):
        """Single ungrounded hex ID -> passes (threshold is 2+)."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_mock_llm_response())
        handler = EvaluateHandler(llm_client=llm)
        ctx = _base_context(context="Clean thread content")
        compose = _compose_result("I found thread f8a9e2b7 with interesting data.")
        result = await handler(_eval_spec(), ctx, [compose])

        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_no_hex_ids_passes(self):
        """Compose output with no hex IDs -> passes."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_mock_llm_response())
        handler = EvaluateHandler(llm_client=llm)
        ctx = _base_context()
        compose = _compose_result("Latency patterns suggest investigation needed.")
        result = await handler(_eval_spec(), ctx, [compose])

        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_case_insensitive_matching(self):
        """F8A9E2B7 in compose, f8a9e2b7 in source -> passes."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_mock_llm_response())
        handler = EvaluateHandler(llm_client=llm)
        ctx = _base_context(context="Thread f8a9e2b7 and event 3c4d5e6f")
        compose = _compose_result(
            "Thread F8A9E2B7 shows event 3C4D5E6F with normal latency."
        )
        result = await handler(_eval_spec(), ctx, [compose])

        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_grounding_before_social_obligation_dm(self):
        """DM with fabricated IDs -> caught by grounding BEFORE social obligation."""
        handler = EvaluateHandler(llm_client=AsyncMock())
        ctx = _base_context(
            _is_dm=True,
            context="Simple DM conversation",
        )
        compose = _compose_result(
            "I traced thread a1b2c3d4 to event e5f6a7b8 in the logs."
        )
        result = await handler(_eval_spec(), ctx, [compose])

        assert result.result["rejection_reason"] == "confabulation_detected"
        assert result.result["recommendation"] == "suppress"
        # Social obligation did NOT bypass the safety check
        assert result.result.get("bypass_reason") is None

    @pytest.mark.asyncio
    async def test_grounding_before_low_trust_bypass(self):
        """Low trust with fabricated IDs -> caught by grounding BEFORE trust bypass."""
        handler = EvaluateHandler(llm_client=AsyncMock())
        ctx = _base_context(
            _chain_trust_band="low",
            _trust_score=0.45,
            context="Clean content",
        )
        compose = _compose_result(
            "Thread a1b2c3d4 shows event e5f6a7b8 with anomalies."
        )
        result = await handler(_eval_spec(), ctx, [compose])

        assert result.result["rejection_reason"] == "confabulation_detected"
        assert result.result.get("bypass_reason") != "low_trust_band"

    @pytest.mark.asyncio
    async def test_bf191_runs_before_grounding(self):
        """BF-191 JSON rejection fires before BF-204 grounding check."""
        handler = EvaluateHandler(llm_client=AsyncMock())
        ctx = _base_context(context="Clean content")
        # Raw JSON with intents key AND fabricated hex IDs
        compose = _compose_result(
            '{"intents": [{"type": "reply"}], "id": "a1b2c3d4", "ref": "e5f6a7b8"}'
        )
        result = await handler(_eval_spec(), ctx, [compose])

        # BF-191 should catch it first
        assert result.result["rejection_reason"] == "raw_json_output"


# ===========================================================================
# Defense ordering tests (4)
# ===========================================================================

class TestDefenseOrdering:
    @pytest.mark.asyncio
    async def test_bf191_before_social_obligation(self):
        """DM with raw JSON -> BF-191 catches before social obligation."""
        handler = EvaluateHandler(llm_client=AsyncMock())
        ctx = _base_context(_is_dm=True)
        compose = _compose_result('{"intents": [{"type": "reply"}]}')
        result = await handler(_eval_spec(), ctx, [compose])

        assert result.result["rejection_reason"] == "raw_json_output"
        assert result.result.get("bypass_reason") is None

    @pytest.mark.asyncio
    async def test_bf204_before_social_obligation(self):
        """DM with fabricated IDs -> BF-204 catches before social obligation."""
        handler = EvaluateHandler(llm_client=AsyncMock())
        ctx = _base_context(_is_dm=True, context="Clean")
        compose = _compose_result(
            "Traced a1b2c3d4e5 to event f6a7b8c9d0 in the system."
        )
        result = await handler(_eval_spec(), ctx, [compose])

        assert result.result["rejection_reason"] == "confabulation_detected"
        assert result.result.get("bypass_reason") is None

    @pytest.mark.asyncio
    async def test_reflect_suppress_honors_even_for_dm(self):
        """EVALUATE suppress -> REFLECT honors suppress even for DMs."""
        handler = ReflectHandler(llm_client=AsyncMock())
        ctx = _base_context(_is_dm=True)
        compose = _compose_result("Fabricated content")
        eval_suppress = _eval_result_suppress()
        result = await handler(
            _reflect_spec(), ctx, [compose, eval_suppress],
        )

        assert result.result["output"] == "[NO_RESPONSE]"
        assert result.result["suppressed"] is True
        assert result.result.get("bypass_reason") is None

    @pytest.mark.asyncio
    async def test_social_obligation_approves_clean_dm(self):
        """Clean DM -> social obligation approves normally."""
        handler = EvaluateHandler(llm_client=AsyncMock())
        ctx = _base_context(_is_dm=True, context="Clean conversation")
        compose = _compose_result("I agree with your analysis on the latency patterns.")
        result = await handler(_eval_spec(), ctx, [compose])

        assert result.result.get("bypass_reason") == "dm_recipient"
        assert result.result["pass"] is True


# ===========================================================================
# LLM grounding criterion tests (4)
# ===========================================================================

class TestLLMGroundingCriterion:
    def test_ward_room_includes_grounding(self):
        ctx = _base_context()
        sys_prompt, _ = _build_ward_room_eval_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "Grounding" in sys_prompt
        assert '"grounding"' in sys_prompt
        assert "fabrication" in sys_prompt

    def test_proactive_includes_grounding(self):
        ctx = _base_context()
        sys_prompt, _ = _build_proactive_eval_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "Grounding" in sys_prompt
        assert '"grounding"' in sys_prompt
        assert "fabrication" in sys_prompt

    def test_notebook_includes_grounding(self):
        ctx = _base_context()
        sys_prompt, _ = _build_notebook_eval_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "Grounding" in sys_prompt
        assert '"grounding"' in sys_prompt

    def test_ward_room_json_format_includes_grounding_key(self):
        ctx = _base_context()
        sys_prompt, _ = _build_ward_room_eval_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert '"grounding": {"pass": true/false' in sys_prompt


# ===========================================================================
# AD-639 integration — voice criterion renumbering (2)
# ===========================================================================

class TestVoiceCriterionRenumbering:
    def test_mid_trust_ward_room_voice_is_criterion_6(self):
        """Mid trust: voice criterion should be #6 (grounding is #5)."""
        ctx = _base_context(_chain_trust_band="mid")
        sys_prompt, _ = _build_ward_room_eval_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "6. **Voice**" in sys_prompt
        assert "5. **Grounding**" in sys_prompt

    def test_mid_trust_proactive_voice_is_criterion_6(self):
        """Mid trust: voice criterion should be #6 (grounding is #5)."""
        ctx = _base_context(_chain_trust_band="mid")
        sys_prompt, _ = _build_proactive_eval_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "6. **Voice**" in sys_prompt
        assert "5. **Grounding**" in sys_prompt


# ===========================================================================
# Reflect grounding tests (3)
# ===========================================================================

class TestReflectGrounding:
    def test_mid_trust_ward_room_grounding_text(self):
        ctx = _base_context(_chain_trust_band="mid", _agent_type="science_agent")
        with patch(
            "probos.cognitive.standing_orders._build_personality_block",
            return_value="[PERSONALITY: curious]",
        ):
            sys_prompt, _ = _build_ward_room_reflect_prompt(
                ctx, [_compose_result()], "Kira", "science",
            )
        assert "Grounding" in sys_prompt
        assert "unverifiable specifics" in sys_prompt

    def test_mid_trust_proactive_grounding_text(self):
        ctx = _base_context(_chain_trust_band="mid", _agent_type="science_agent")
        with patch(
            "probos.cognitive.standing_orders._build_personality_block",
            return_value="[PERSONALITY: methodical]",
        ):
            sys_prompt, _ = _build_proactive_reflect_prompt(
                ctx, [_compose_result()], "Kira", "science",
            )
        assert "Grounding" in sys_prompt
        assert "unverifiable specifics" in sys_prompt

    def test_high_trust_no_grounding_text(self):
        """High trust reflect does NOT include grounding self-check."""
        ctx = _base_context(_chain_trust_band="high")
        sys_prompt, _ = _build_ward_room_reflect_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "unverifiable specifics" not in sys_prompt


# ===========================================================================
# Integration tests (3)
# ===========================================================================

class TestGroundingIntegration:
    @pytest.mark.asyncio
    async def test_fabricated_ids_at_low_trust_suppressed(self):
        """Fabricated hex IDs at low trust -> grounding suppression fires first."""
        eval_handler = EvaluateHandler(llm_client=AsyncMock())
        reflect_handler = ReflectHandler(llm_client=AsyncMock())
        ctx = _base_context(
            _chain_trust_band="low",
            _trust_score=0.45,
            context="Clean content",
        )
        compose = _compose_result(
            "Thread a1b2c3d4 and event e5f6a7b8 show anomalies."
        )

        eval_result = await eval_handler(_eval_spec(), ctx, [compose])
        assert eval_result.result["rejection_reason"] == "confabulation_detected"
        assert eval_result.result["recommendation"] == "suppress"

        # REFLECT should honor suppress
        reflect_result = await reflect_handler(
            _reflect_spec(), ctx, [compose, eval_result],
        )
        assert reflect_result.result["output"] == "[NO_RESPONSE]"
        assert reflect_result.result["suppressed"] is True

    @pytest.mark.asyncio
    async def test_fabricated_ids_in_dm_suppressed(self):
        """Fabricated hex IDs in DM -> grounding suppression overrides social obligation."""
        eval_handler = EvaluateHandler(llm_client=AsyncMock())
        reflect_handler = ReflectHandler(llm_client=AsyncMock())
        ctx = _base_context(
            _is_dm=True,
            context="DM conversation",
        )
        compose = _compose_result(
            "I traced thread a1b2c3d4 to event e5f6a7b8."
        )

        eval_result = await eval_handler(_eval_spec(), ctx, [compose])
        assert eval_result.result["rejection_reason"] == "confabulation_detected"

        reflect_result = await reflect_handler(
            _reflect_spec(), ctx, [compose, eval_result],
        )
        assert reflect_result.result["output"] == "[NO_RESPONSE]"
        assert reflect_result.result["suppressed"] is True

    @pytest.mark.asyncio
    async def test_clean_dm_passes_normally(self):
        """Clean content in DM -> social obligation approves at both stages."""
        eval_handler = EvaluateHandler(llm_client=AsyncMock())
        reflect_handler = ReflectHandler(llm_client=AsyncMock())
        ctx = _base_context(
            _is_dm=True,
            context="DM conversation about system status",
        )
        compose = _compose_result(
            "The system status looks stable based on the thread discussion."
        )

        eval_result = await eval_handler(_eval_spec(), ctx, [compose])
        assert eval_result.result.get("bypass_reason") == "dm_recipient"
        assert eval_result.result["pass"] is True

        reflect_result = await reflect_handler(
            _reflect_spec(), ctx, [compose, eval_result],
        )
        assert reflect_result.result.get("bypass_reason") == "dm_recipient"
        assert reflect_result.result["output"] == compose.result["output"]
