"""AD-724 family — DM path hardening tests (AD-724-1 + AD-724-2 + AD-724-5).

Covers:
- AD-724-2: stdlib-difflib similarity-based repetition beyond exact-prefix.
- AD-724-1: controlled one-shot retry on rejection — should_retry surface
  + DM router dispatches exactly one retry.
- AD-724-5: apply_dm_sanity shared helper for WR / chain reply paths.

Boundary tests per the engineering principles: happy path + edge + empty.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.dm_sanity_gate import (
    DmSanityGate,
    DmSanityGateConfig,
    DmSanityResult,
    _normalize_for_repetition,
    apply_dm_sanity,
)


# ---------------------------------------------------------------------------
# AD-724-2: fuzzy repetition (stdlib only — no rapidfuzz)
# ---------------------------------------------------------------------------


class TestAD724_2_FuzzyRepetition:
    def test_normalize_collapses_whitespace_and_strips_tags(self):
        text = "  Hello\n\n[REPLY foo]   World\t\t[/REPLY]  "
        out = _normalize_for_repetition(text)
        # Tags removed, whitespace collapsed, lowercased.
        assert out == "hello world"

    def test_similarity_ratio_above_threshold_fires(self):
        gate = DmSanityGate(DmSanityGateConfig())
        # First reply primes the cache.
        first = "A" * 60 + " hello"
        gate.process("agent-1", first)
        # Second reply differs ONLY in trailing whitespace + tag noise;
        # exact-prefix check WILL match (both share the first 100 chars
        # because the differ in chars >100 is whitespace).
        # To exercise the similarity branch alone, build a string whose
        # first 100 chars differ but normalized form is identical.
        second = first[:50] + "X" + first[50:] + "\n[NOTEBOOK foo]"
        # Force a NON-exact-prefix scenario by mutating the first char.
        second = "Z" + first[1:] + "\n[NOTEBOOK foo]"
        result = gate.process("agent-1", second)
        # Exact-prefix differs at position 0; similarity should still
        # fire on the normalized form (it's mostly the same text).
        warning_names = [n for n, _ in result.warnings]
        assert "repetition" in warning_names

    def test_similarity_ratio_below_threshold_silent(self):
        gate = DmSanityGate(DmSanityGateConfig())
        gate.process("agent-1", "The quick brown fox jumps over the lazy dog. " * 5)
        result = gate.process("agent-1", "Yesterday morning the sky was blue and clear.")
        assert all(n != "repetition" for n, _ in result.warnings)

    def test_empty_previous_reply_no_repetition_warning(self):
        gate = DmSanityGate(DmSanityGateConfig())
        # First call — cache is empty, repetition check must be silent.
        result = gate.process("agent-1", "hello world this is the first reply")
        assert all(n != "repetition" for n, _ in result.warnings)

    def test_exact_prefix_match_still_wins_fast_path(self):
        gate = DmSanityGate(DmSanityGateConfig())
        text = "A" * 150
        gate.process("agent-1", text)
        result = gate.process("agent-1", text + " trailing extra")
        # Exact-prefix should fire (cheaper than similarity).
        warning_names = [n for n, _ in result.warnings]
        assert "repetition" in warning_names


# ---------------------------------------------------------------------------
# AD-724-1: controlled retry semantics on DmSanityResult
# ---------------------------------------------------------------------------


class TestAD724_1_ControlledRetry:
    def test_should_retry_true_when_length_floor_fires(self):
        gate = DmSanityGate(DmSanityGateConfig())
        result = gate.process("agent-1", "ok")  # 2 chars < default floor=5
        warning_names = [n for n, _ in result.warnings]
        assert "length_floor" in warning_names
        assert result.should_retry is True

    def test_should_retry_false_when_only_repetition_fires(self):
        # Default retry_warnings = ["length_floor", "orphaned_tag"] — repetition
        # alone should NOT trigger a retry.
        gate = DmSanityGate(DmSanityGateConfig())
        long_reply = "A" * 200 + " hello world this is a sufficiently long reply."
        gate.process("agent-1", long_reply)
        result = gate.process("agent-1", long_reply)  # exact dup → repetition
        warning_names = [n for n, _ in result.warnings]
        assert "repetition" in warning_names
        assert result.should_retry is False

    def test_should_retry_false_when_disabled_in_config(self):
        cfg = DmSanityGateConfig(retry_on_rejection=False)
        gate = DmSanityGate(cfg)
        result = gate.process("agent-1", "x")  # would fire length_floor
        warning_names = [n for n, _ in result.warnings]
        assert "length_floor" in warning_names
        # Retry is disabled — should_retry must be False.
        assert result.should_retry is False


# ---------------------------------------------------------------------------
# AD-724-5: apply_dm_sanity shared helper
# ---------------------------------------------------------------------------


class TestAD724_5_ApplyHelper:
    def test_returns_noop_when_gate_missing(self):
        # Runtime with no dm_sanity_gate attribute → no-op.
        rt = MagicMock(spec=[])  # spec=[] disables auto-attribute creation
        result = apply_dm_sanity(rt, "agent-1", "**[REPLY] hi [/REPLY]**")
        assert isinstance(result, DmSanityResult)
        # Input text preserved verbatim — no strip happened.
        assert result.cleaned_text == "**[REPLY] hi [/REPLY]**"
        assert result.warnings == []
        assert result.should_retry is False

    def test_strips_markdown_via_helper(self):
        rt = MagicMock()
        rt.dm_sanity_gate = DmSanityGate(DmSanityGateConfig())
        result = apply_dm_sanity(rt, "agent-1", "**[REPLY post-1] hello [/REPLY]**")
        # BF-120 markdown strip is applied even when gate is enabled.
        assert "[REPLY post-1]" in result.cleaned_text
        assert "**[REPLY" not in result.cleaned_text

    def test_returns_dmsanityresult_with_warnings_propagated(self):
        rt = MagicMock()
        rt.dm_sanity_gate = DmSanityGate(DmSanityGateConfig())
        result = apply_dm_sanity(rt, "agent-1", "hi")  # 2 chars < floor=5
        assert isinstance(result, DmSanityResult)
        assert any(n == "length_floor" for n, _ in result.warnings)


# ---------------------------------------------------------------------------
# AD-724-1: DM router retry integration — at most one re-dispatch
# ---------------------------------------------------------------------------


class TestAD724_1_RouterRetry:
    @pytest.mark.asyncio
    async def test_router_dispatches_at_most_one_retry(self):
        """The DM router calls intent_bus.send exactly twice: initial + 1 retry.
        Even if the retry also fires warnings, no second retry happens.
        """
        from probos.routers.agents import agent_chat
        from probos.api_models import AgentChatRequest

        # Build a minimal runtime + agent that returns short responses (so the
        # length_floor warning fires both times).
        runtime = MagicMock()
        runtime.config = MagicMock()
        runtime.config.attachments = MagicMock()
        runtime.config.attachments.enabled = False

        gate = DmSanityGate(DmSanityGateConfig())
        runtime.dm_sanity_gate = gate

        # Both calls return short replies that fail length_floor.
        result1 = MagicMock()
        result1.result = "ok"
        result1.error = None
        result2 = MagicMock()
        result2.result = "x"
        result2.error = None
        runtime.intent_bus = MagicMock()
        runtime.intent_bus.send = AsyncMock(side_effect=[result1, result2])

        # Agent stub.
        agent = MagicMock()
        agent.id = "test-id"
        agent.agent_type = "scout"
        runtime.registry = MagicMock()
        runtime.registry.get_agent = MagicMock(return_value=agent)
        runtime.callsign_registry = MagicMock()
        runtime.callsign_registry.get_callsign = MagicMock(return_value="Wesley")
        runtime.recreation_service = None
        runtime.episodic_memory = None
        runtime.ward_room = None
        runtime.avatar_sampling_state = None
        runtime.avatar_event_bus = None
        runtime.ontology = MagicMock()

        # is_crew_agent shim — bypass crew gating for the test.
        from probos.routers import agents as agents_mod
        original_is_crew = agents_mod.is_crew_agent
        agents_mod.is_crew_agent = lambda a, o: True
        try:
            req = AgentChatRequest(message="hello", history=[], attachment_ids=[])
            try:
                await agent_chat("test-id", req, runtime)
            except Exception:
                # Downstream code (episodic, working_memory, etc.) may raise
                # on the mocked runtime — we only care about send call_count.
                pass
        finally:
            agents_mod.is_crew_agent = original_is_crew

        # Exactly 2 sends: initial + 1 retry. NOT 3+.
        assert runtime.intent_bus.send.call_count == 2
