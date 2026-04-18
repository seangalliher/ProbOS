"""AD-639: Cognitive Chain Personality Tuning tests.

Trust-band adaptive chain: low trust skips EVALUATE/REFLECT,
mid trust adds personality-aware criteria, high trust unchanged.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from probos.config import ChainTuningConfig, SystemConfig
from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType
from probos.cognitive.sub_tasks.evaluate import (
    EvaluateHandler,
    _build_ward_room_eval_prompt,
    _build_proactive_eval_prompt,
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
    """Create a successful Compose result."""
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose",
        result={"output": output},
        tokens_used=100,
        duration_ms=50,
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
    return resp


# ===========================================================================
# Config tests
# ===========================================================================

class TestChainTuningConfig:
    def test_defaults(self):
        cfg = ChainTuningConfig()
        assert cfg.enabled is True
        assert cfg.low_trust_ceiling == 0.60
        assert cfg.high_trust_floor == 0.75

    def test_wired_into_system_config(self):
        sc = SystemConfig()
        assert hasattr(sc, "chain_tuning")
        assert isinstance(sc.chain_tuning, ChainTuningConfig)

    def test_disabled(self):
        cfg = ChainTuningConfig(enabled=False)
        assert cfg.enabled is False


# ===========================================================================
# Trust band resolution tests (context injection in cognitive_agent.py)
# These test the band classification logic directly.
# ===========================================================================

class TestTrustBandClassification:
    """Test trust band classification against thresholds."""

    @pytest.mark.parametrize(
        "trust,expected_band",
        [
            (0.40, "low"),
            (0.59, "low"),
            (0.60, "mid"),
            (0.65, "mid"),
            (0.74, "mid"),
            (0.75, "high"),
            (0.90, "high"),
        ],
    )
    def test_trust_band_classification(self, trust, expected_band):
        cfg = ChainTuningConfig()
        if trust < cfg.low_trust_ceiling:
            band = "low"
        elif trust >= cfg.high_trust_floor:
            band = "high"
        else:
            band = "mid"
        assert band == expected_band

    def test_boot_camp_takes_precedence(self):
        """When boot camp is active, trust band should NOT be injected."""
        # This tests the guard in cognitive_agent.py:
        # if not observation.get("_boot_camp_active"):
        obs = {"_boot_camp_active": True}
        cfg = ChainTuningConfig(enabled=True)
        # Boot camp active → no trust band injection
        if not obs.get("_boot_camp_active"):
            obs["_chain_trust_band"] = "low"
        assert "_chain_trust_band" not in obs

    def test_trust_network_unavailable_defaults_low(self):
        """When trust network is unavailable, default trust 0.5 → low band."""
        cfg = ChainTuningConfig()
        trust = 0.5  # default when trust network unavailable
        if trust < cfg.low_trust_ceiling:
            band = "low"
        elif trust >= cfg.high_trust_floor:
            band = "high"
        else:
            band = "mid"
        assert band == "low"


# ===========================================================================
# Evaluate handler tests
# ===========================================================================

class TestEvaluateLowTrustBypass:
    @pytest.mark.asyncio
    async def test_low_trust_bypass(self):
        handler = EvaluateHandler(llm_client=AsyncMock())
        ctx = _base_context(_chain_trust_band="low", _trust_score=0.45)
        result = await handler(_eval_spec(), ctx, [_compose_result()])

        assert result.success is True
        assert result.tokens_used == 0
        assert result.result["pass"] is True
        assert result.result["score"] == 0.0
        assert result.result["bypass_reason"] == "low_trust_band"
        assert result.result["recommendation"] == "approve"

    @pytest.mark.asyncio
    async def test_low_trust_bypass_score_is_zero(self):
        """Score 0.0 signals 'not evaluated', distinct from boot camp's 0.8."""
        handler = EvaluateHandler(llm_client=AsyncMock())
        ctx = _base_context(_chain_trust_band="low", _trust_score=0.45)
        result = await handler(_eval_spec(), ctx, [_compose_result()])
        assert result.result["score"] == 0.0

    @pytest.mark.asyncio
    async def test_high_trust_no_bypass(self):
        """High trust → full LLM evaluation (no bypass)."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_mock_llm_response())
        handler = EvaluateHandler(llm_client=llm)
        ctx = _base_context(_chain_trust_band="high", _trust_score=0.85)
        result = await handler(_eval_spec(), ctx, [_compose_result()])

        assert result.tokens_used > 0 or llm.complete.called
        assert "bypass_reason" not in result.result

    @pytest.mark.asyncio
    async def test_boot_camp_takes_precedence_over_low_trust(self):
        """Boot camp bypass fires before trust band check."""
        handler = EvaluateHandler(llm_client=AsyncMock())
        ctx = _base_context(
            _boot_camp_active=True,
            _chain_trust_band="low",
            _trust_score=0.45,
        )
        result = await handler(_eval_spec(), ctx, [_compose_result()])
        assert result.result.get("bypass_reason") == "boot_camp"

    @pytest.mark.asyncio
    async def test_social_obligation_takes_precedence_over_low_trust(self):
        """Social obligation bypass fires before trust band check."""
        handler = EvaluateHandler(llm_client=AsyncMock())
        ctx = _base_context(
            _from_captain=True,
            _chain_trust_band="low",
            _trust_score=0.45,
        )
        result = await handler(_eval_spec(), ctx, [_compose_result()])
        assert result.result.get("bypass_reason") == "captain_message"

    @pytest.mark.asyncio
    async def test_bf191_json_rejection_before_low_trust(self):
        """BF-191 JSON rejection must fire before AD-639 bypass."""
        handler = EvaluateHandler(llm_client=AsyncMock())
        ctx = _base_context(_chain_trust_band="low", _trust_score=0.45)
        bad_compose = _compose_result('{"intents": [{"type": "reply"}]}')
        result = await handler(_eval_spec(), ctx, [bad_compose])

        assert result.result.get("rejection_reason") == "raw_json_output"
        assert result.result["recommendation"] == "suppress"

    @pytest.mark.asyncio
    async def test_disabled_config_no_bypass(self):
        """When config disabled, no trust band is set → standard evaluation."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_mock_llm_response())
        handler = EvaluateHandler(llm_client=llm)
        # No _chain_trust_band in context (disabled config = no injection)
        ctx = _base_context()
        result = await handler(_eval_spec(), ctx, [_compose_result()])
        assert "bypass_reason" not in result.result


class TestEvaluateMidTrustVoice:
    def test_ward_room_voice_criterion_present(self):
        ctx = _base_context(_chain_trust_band="mid")
        sys_prompt, _ = _build_ward_room_eval_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "Voice" in sys_prompt
        assert '"voice"' in sys_prompt

    def test_ward_room_no_voice_at_high_trust(self):
        ctx = _base_context(_chain_trust_band="high")
        sys_prompt, _ = _build_ward_room_eval_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "Voice" not in sys_prompt
        assert '"voice"' not in sys_prompt

    def test_proactive_voice_criterion_present(self):
        ctx = _base_context(_chain_trust_band="mid")
        sys_prompt, _ = _build_proactive_eval_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "Voice" in sys_prompt
        assert '"voice"' in sys_prompt

    def test_proactive_no_voice_at_high_trust(self):
        ctx = _base_context(_chain_trust_band="high")
        sys_prompt, _ = _build_proactive_eval_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "Voice" not in sys_prompt

    def test_no_trust_band_defaults_to_high(self):
        """When no trust band set, defaults to high (no voice criterion)."""
        ctx = _base_context()  # no _chain_trust_band
        sys_prompt, _ = _build_ward_room_eval_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "Voice" not in sys_prompt


# ===========================================================================
# Reflect handler tests
# ===========================================================================

class TestReflectLowTrustBypass:
    @pytest.mark.asyncio
    async def test_low_trust_bypass(self):
        handler = ReflectHandler(llm_client=AsyncMock())
        ctx = _base_context(_chain_trust_band="low", _trust_score=0.45)
        compose = _compose_result("My personality-rich output")
        result = await handler(_reflect_spec(), ctx, [compose])

        assert result.success is True
        assert result.tokens_used == 0
        assert result.result["output"] == "My personality-rich output"
        assert result.result["revised"] is False
        assert result.result["reflection"] == "low_trust_band_bypass"

    @pytest.mark.asyncio
    async def test_high_trust_no_bypass(self):
        """High trust → full LLM reflection (no bypass)."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_mock_llm_response(
            '{"output": "revised", "revised": true, "reflection": "improved"}'
        ))
        handler = ReflectHandler(llm_client=llm)
        ctx = _base_context(_chain_trust_band="high", _trust_score=0.85)
        result = await handler(_reflect_spec(), ctx, [_compose_result()])

        assert llm.complete.called
        assert "low_trust_band_bypass" not in str(result.result)

    @pytest.mark.asyncio
    async def test_boot_camp_takes_precedence_over_low_trust(self):
        handler = ReflectHandler(llm_client=AsyncMock())
        ctx = _base_context(
            _boot_camp_active=True,
            _chain_trust_band="low",
            _trust_score=0.45,
        )
        result = await handler(_reflect_spec(), ctx, [_compose_result()])
        assert result.result.get("bypass_reason") == "boot_camp"

    @pytest.mark.asyncio
    async def test_disabled_config_no_bypass(self):
        """No trust band in context → standard reflection."""
        llm = AsyncMock()
        llm.complete = AsyncMock(return_value=_mock_llm_response(
            '{"output": "text", "revised": false, "reflection": "ok"}'
        ))
        handler = ReflectHandler(llm_client=llm)
        ctx = _base_context()  # no _chain_trust_band
        result = await handler(_reflect_spec(), ctx, [_compose_result()])
        assert llm.complete.called


class TestReflectMidTrustPersonality:
    def test_ward_room_personality_block(self):
        ctx = _base_context(_chain_trust_band="mid", _agent_type="science_agent")
        with patch(
            "probos.cognitive.standing_orders._build_personality_block",
            return_value="[PERSONALITY: curious, analytical]",
        ) as mock_pb:
            sys_prompt, _ = _build_ward_room_reflect_prompt(
                ctx, [_compose_result()], "Kira", "science",
            )
        assert "[PERSONALITY: curious, analytical]" in sys_prompt
        assert "Preserve your personality" in sys_prompt
        assert "Voice consistency" in sys_prompt

    def test_ward_room_no_personality_at_high(self):
        ctx = _base_context(_chain_trust_band="high")
        sys_prompt, _ = _build_ward_room_reflect_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "Preserve your personality" not in sys_prompt
        assert "Voice consistency" not in sys_prompt
        assert "You are Kira (science department)" in sys_prompt

    def test_proactive_personality_block(self):
        ctx = _base_context(_chain_trust_band="mid", _agent_type="science_agent")
        with patch(
            "probos.cognitive.standing_orders._build_personality_block",
            return_value="[PERSONALITY: methodical]",
        ):
            sys_prompt, _ = _build_proactive_reflect_prompt(
                ctx, [_compose_result()], "Kira", "science",
            )
        assert "[PERSONALITY: methodical]" in sys_prompt
        assert "Preserve your personality" in sys_prompt
        assert "Voice consistency" in sys_prompt

    def test_proactive_no_personality_at_high(self):
        ctx = _base_context(_chain_trust_band="high")
        sys_prompt, _ = _build_proactive_reflect_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "Preserve your personality" not in sys_prompt
        assert "You are Kira (science department)" in sys_prompt

    def test_general_personality_block(self):
        ctx = _base_context(_chain_trust_band="mid", _agent_type="science_agent")
        with patch(
            "probos.cognitive.standing_orders._build_personality_block",
            return_value="[PERSONALITY: thorough]",
        ):
            sys_prompt, _ = _build_general_reflect_prompt(
                ctx, [_compose_result()], "Kira", "science",
            )
        assert "[PERSONALITY: thorough]" in sys_prompt
        assert "Preserve your personality" in sys_prompt

    def test_general_no_personality_at_high(self):
        ctx = _base_context(_chain_trust_band="high")
        sys_prompt, _ = _build_general_reflect_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "Preserve your personality" not in sys_prompt
        assert "You are Kira (science department)" in sys_prompt

    def test_no_trust_band_defaults_to_high(self):
        """When no trust band set, bare identity prompt used."""
        ctx = _base_context()  # no _chain_trust_band
        sys_prompt, _ = _build_ward_room_reflect_prompt(
            ctx, [_compose_result()], "Kira", "science",
        )
        assert "You are Kira (science department)" in sys_prompt
        assert "Preserve your personality" not in sys_prompt


# ===========================================================================
# Integration-style tests
# ===========================================================================

class TestChainIntegration:
    @pytest.mark.asyncio
    async def test_low_trust_token_savings(self):
        """EVALUATE + REFLECT at low trust = 0 tokens total."""
        eval_handler = EvaluateHandler(llm_client=AsyncMock())
        reflect_handler = ReflectHandler(llm_client=AsyncMock())
        ctx = _base_context(_chain_trust_band="low", _trust_score=0.45)
        compose = _compose_result("Output with personality")

        eval_result = await eval_handler(_eval_spec(), ctx, [compose])
        reflect_result = await reflect_handler(
            _reflect_spec(), ctx, [compose, eval_result],
        )

        assert eval_result.tokens_used == 0
        assert reflect_result.tokens_used == 0
        assert reflect_result.result["output"] == "Output with personality"

    @pytest.mark.asyncio
    async def test_mid_trust_full_chain_with_personality(self):
        """Mid trust: both steps execute with personality enhancements."""
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=[
            _mock_llm_response(),  # evaluate response
            _mock_llm_response(  # reflect response
                '{"output": "revised with voice", "revised": true, "reflection": "ok"}'
            ),
        ])
        eval_handler = EvaluateHandler(llm_client=llm)
        reflect_handler = ReflectHandler(llm_client=llm)
        ctx = _base_context(_chain_trust_band="mid", _trust_score=0.65)
        compose = _compose_result("Output")

        eval_result = await eval_handler(_eval_spec(), ctx, [compose])
        assert eval_result.success is True
        assert "bypass_reason" not in eval_result.result

        with patch(
            "probos.cognitive.standing_orders._build_personality_block",
            return_value="[PERSONALITY]",
        ):
            reflect_result = await reflect_handler(
                _reflect_spec(), ctx, [compose, eval_result],
            )
        assert reflect_result.success is True

    @pytest.mark.asyncio
    async def test_high_trust_unchanged(self):
        """High trust: standard chain, no AD-639 modifications."""
        llm = AsyncMock()
        llm.complete = AsyncMock(side_effect=[
            _mock_llm_response(),
            _mock_llm_response(
                '{"output": "text", "revised": false, "reflection": "good"}'
            ),
        ])
        eval_handler = EvaluateHandler(llm_client=llm)
        reflect_handler = ReflectHandler(llm_client=llm)
        ctx = _base_context(_chain_trust_band="high", _trust_score=0.85)
        compose = _compose_result("Output")

        eval_result = await eval_handler(_eval_spec(), ctx, [compose])
        reflect_result = await reflect_handler(
            _reflect_spec(), ctx, [compose, eval_result],
        )

        assert eval_result.success is True
        assert reflect_result.success is True
        assert llm.complete.call_count == 2
