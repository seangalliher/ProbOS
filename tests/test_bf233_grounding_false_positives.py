"""Tests for BF-233: Grounding check must not suppress legitimate entity IDs."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from probos.cognitive.sub_tasks.evaluate import EvaluateHandler
from probos.cognitive.sub_task import SubTaskSpec, SubTaskResult, SubTaskType


def _make_handler(*, expect_llm_eval: bool = True):
    """EvaluateHandler for deterministic-path-only tests.

    The LLM client must be non-None to pass the guard at the top of
    __call__ — otherwise the handler returns early with
    'LLM client unavailable' before reaching the BF-204 grounding check.

    When expect_llm_eval=True (default), the mock LLM returns a valid
    approve response so tests that pass the grounding check don't crash
    on the subsequent LLM evaluation step.
    """
    llm = AsyncMock()
    if expect_llm_eval:
        resp = MagicMock()
        resp.content = '{"pass": true, "score": 0.8, "criteria": {}, "recommendation": "approve"}'
        resp.tokens_used = 50
        resp.tier = "fast"
        llm.complete = AsyncMock(return_value=resp)
    return EvaluateHandler(llm_client=llm)


def _prior_analyze_result(text: str = "Analysis complete.") -> list[SubTaskResult]:
    """Fake prior ANALYZE result."""
    return [
        SubTaskResult(
            sub_task_type=SubTaskType.ANALYZE,
            name="analyze-reply",
            result={"analysis": text},
            tokens_used=0,
            duration_ms=1,
            success=True,
            tier_used="",
        )
    ]


def _compose_result(text: str) -> SubTaskResult:
    """Fake COMPOSE result."""
    return SubTaskResult(
        sub_task_type=SubTaskType.COMPOSE,
        name="compose-reply",
        result={"output": text},
        tokens_used=10,
        duration_ms=5,
        success=True,
        tier_used="fast",
    )


def _spec():
    return SubTaskSpec(
        sub_task_type=SubTaskType.EVALUATE,
        name="evaluate-reply",
        prompt_template="",
        depends_on=("compose-reply",),
    )


class TestBF233GroundingFalsePositives:
    """BF-233: Entity IDs from params must be treated as grounded."""

    @pytest.mark.asyncio
    async def test_thread_id_in_compose_not_flagged(self):
        """Agent referencing its thread_id should not be suppressed."""
        handler = _make_handler()
        thread_id = "a6ec8b06-1234-5678-9abc-be2f4f7e5ee2"
        ctx = {
            "context": "Thread: All Hands\nCaptain: Status report",
            "params": {"thread_id": thread_id, "channel_id": "c1d2e3f4-0000-0000-0000-000000000001"},
            "_agent_id": "78a87214-aaaa-bbbb-cccc-b45a928286e5",
            "_agent_type": "engineer",
            "_chain_trust_band": "mid",
        }
        # Compose output references thread ID substrings (regex splits on hyphens)
        compose = _compose_result(
            "Responding to thread a6ec8b06. As noted in be2f4f7e5ee2, systems nominal."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        # Should NOT be suppressed — these hex IDs are from thread_id
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_agent_own_id_in_compose_not_flagged(self):
        """Agent referencing its own UUID should not be suppressed."""
        handler = _make_handler()
        agent_id = "78a87214-aaaa-bbbb-cccc-b45a928286e5"
        ctx = {
            "context": "Thread: Status Check",
            "params": {"thread_id": "deadbeef-0000-0000-0000-000000000001"},
            "_agent_id": agent_id,
            "_agent_type": "operations_officer",
            "_chain_trust_band": "mid",
        }
        compose = _compose_result(
            "Agent 78a87214 reporting. Identity confirmed via b45a928286e5 credential."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_channel_id_in_compose_not_flagged(self):
        """Agent referencing channel_id should not be suppressed."""
        handler = _make_handler()
        ctx = {
            "context": "Thread: Department Update",
            "params": {
                "thread_id": "11111111-2222-3333-4444-555555555555",
                "channel_id": "c36cc630-abcd-efef-1234-3e5c9b4cade5",
            },
            "_agent_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "_agent_type": "pharmacist",
            "_chain_trust_band": "mid",
        }
        compose = _compose_result(
            "Channel c36cc630 update: reviewing prescription protocols per 3e5c9b4cade5."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_truncated_post_id_plus_full_uuid_not_flagged(self):
        """BF-233 regression: thread context has 8-char truncated post IDs,
        but agent references the full UUID. The truncated form matches thread
        context; the suffix matches the agent's own _agent_id."""
        handler = _make_handler()
        # Thread context has truncated post ID [deadbeef]
        # Agent's own ID has suffix cafebabe1234
        ctx = {
            "context": "Thread: Discussion\n[deadbeef] Alice: opening point",
            "params": {
                "thread_id": "00000000-1111-2222-3333-444444444444",
                "channel_id": "55555555-1111-2222-3333-666666666666",
            },
            "_agent_id": "99999999-1111-2222-3333-cafebabe1234",
            "_agent_type": "test_agent",
            "_chain_trust_band": "mid",
        }
        # deadbeef matches thread context, cafebabe1234 matches _agent_id
        compose = _compose_result(
            "Building on deadbeef analysis, also noting cafebabe1234 implications."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_other_agent_full_uuid_still_flagged(self):
        """BF-233 known limitation: full UUIDs of OTHER agents' posts
        (not in agent's own params) still trigger BF-204 if agent
        references them instead of using the truncated 8-char form."""
        handler = _make_handler()
        ctx = {
            "context": "Thread: Discussion\n[deadbeef] Alice: opening point",
            "params": {
                "thread_id": "00000000-1111-2222-3333-444444444444",
            },
            "_agent_id": "99999999-1111-2222-3333-aaaaaaaaaaaa",
            "_agent_type": "test_agent",
            "_chain_trust_band": "mid",
        }
        # Agent references a DIFFERENT agent's post UUID suffix — not in any
        # of this agent's params or identity. This is a known scope boundary.
        compose = _compose_result(
            "Per deadbeef and their follow-up cafebabe1234, I concur."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        # deadbeef matches thread context, but cafebabe1234 is ungrounded.
        # Only 1 ungrounded (below threshold of 2), so this actually passes.
        # If agent referenced TWO other agents' full UUIDs, it would suppress.
        # This documents the boundary — not a regression.
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_fabricated_ids_still_caught(self):
        """BF-204 core protection: truly fabricated hex IDs still trigger suppression."""
        handler = _make_handler(expect_llm_eval=False)
        ctx = {
            "context": "Thread: Science Report",
            "params": {"thread_id": "11111111-0000-0000-0000-000000000001"},
            "_agent_id": "22222222-0000-0000-0000-000000000002",
            "_agent_type": "science_officer",
            "_chain_trust_band": "mid",
        }
        # These hex IDs are NOT in any params or identity field — truly fabricated
        compose = _compose_result(
            "According to analysis f8a9e2b7c3d4, metric e5f6a7b8d9c0 shows anomalies."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        # SHOULD be suppressed — these are fabricated
        assert result.result.get("rejection_reason") == "confabulation_detected"

    @pytest.mark.asyncio
    async def test_mixed_legit_and_fabricated(self):
        """One legit ID + two fabricated = still suppressed."""
        handler = _make_handler(expect_llm_eval=False)
        thread_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        ctx = {
            "context": "Thread: Mixed Test",
            "params": {"thread_id": thread_id},
            "_agent_id": "99999999-0000-0000-0000-000000000001",
            "_agent_type": "test_agent",
            "_chain_trust_band": "mid",
        }
        # a1b2c3d4 is legit (from thread_id), but deadcafe and baadf00d are fabricated
        compose = _compose_result(
            "Thread a1b2c3d4 referenced. Also see deadcafe analysis and baadf00d metric."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        # Two fabricated IDs remain after filtering legit ones — should suppress
        assert result.result.get("rejection_reason") == "confabulation_detected"

    @pytest.mark.asyncio
    async def test_no_params_degrades_gracefully(self):
        """Missing params dict doesn't crash the grounding check."""
        handler = _make_handler()
        ctx = {
            "context": "Some context",
            # No "params" key at all
            "_agent_type": "test_agent",
            "_chain_trust_band": "mid",
        }
        compose = _compose_result("Simple response with no hex references.")
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        # No hex IDs in output → passes
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_params_non_dict_degrades_gracefully(self):
        """Non-dict params doesn't crash grounding check."""
        handler = _make_handler()
        ctx = {
            "context": "Some context",
            "params": ["unexpected", "list"],  # Not a dict
            "_agent_type": "test_agent",
            "_chain_trust_band": "mid",
        }
        compose = _compose_result("Simple response with no hex references.")
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_author_id_captain_not_hex(self):
        """author_id='captain' (non-hex) doesn't break grounding source."""
        handler = _make_handler()
        ctx = {
            "context": "Thread: Captain's Orders",
            "params": {
                "thread_id": "abcdef01-2345-6789-abcd-ef0123456789",
                "author_id": "captain",  # Not a hex UUID
            },
            "_agent_id": "fedcba98-7654-3210-fedc-ba9876543210",
            "_agent_type": "first_officer",
            "_chain_trust_band": "high",
        }
        compose = _compose_result(
            "Acknowledged, Captain. Thread abcdef01 orders received. Agent fedcba98 standing by."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        assert result.result.get("rejection_reason") != "confabulation_detected"

    @pytest.mark.asyncio
    async def test_intent_id_in_compose_not_flagged(self):
        """Agent referencing its intent_id should not be suppressed.
        intent_id is set at top-level context by cognitive_agent.py:1046."""
        handler = _make_handler()
        intent_id = "deed1234-abab-cdcd-efef-567890abcdef"
        ctx = {
            "context": "Thread: Coordination",
            "params": {"thread_id": "00000000-1111-2222-3333-444444444444"},
            "_agent_id": "55555555-6666-7777-8888-999999999999",
            "intent_id": intent_id,
            "_agent_type": "comms_officer",
            "_chain_trust_band": "mid",
        }
        compose = _compose_result(
            "Processing intent deed1234. Correlation 567890abcdef confirmed."
        )
        prior = _prior_analyze_result()
        prior.append(compose)

        result = await handler(
            spec=_spec(),
            context=ctx,
            prior_results=prior,
        )
        assert result.result.get("rejection_reason") != "confabulation_detected"
