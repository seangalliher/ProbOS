"""BF-060/061/062: Proactive loop quality tests."""

import re
from unittest.mock import AsyncMock, MagicMock

import pytest


# ── BF-060: Notebook stripping ──


def _make_engine_and_rt(trust_score=0.55):
    """Create a ProactiveEngine with mocked runtime for action extraction tests."""
    from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
    from probos.proactive import ProactiveCognitiveLoop

    engine = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
    engine._circuit_breaker = CognitiveCircuitBreaker()
    rt = MagicMock()
    rt.ward_room = MagicMock()
    rt.ward_room.list_channels = AsyncMock(return_value=[])
    rt.trust_network = MagicMock()
    rt.trust_network.get_score = MagicMock(return_value=trust_score)
    rt._extract_endorsements = MagicMock(return_value=("", []))
    rt._records_store = MagicMock()
    rt._records_store.write_notebook = AsyncMock()
    rt.ontology = None
    rt.callsign_registry = MagicMock()
    rt.callsign_registry.get_callsign = MagicMock(return_value="TestAgent")
    rt.config = MagicMock()
    rt.config.communications = MagicMock(dm_min_rank="ensign")
    engine._runtime = rt
    return engine, rt


class TestNotebookStripping:
    """BF-060: [NOTEBOOK] blocks must be stripped from Ward Room text."""

    @pytest.mark.asyncio
    async def test_notebook_stripped_from_ward_room_text(self):
        """Notebook tags are removed from text after extraction."""
        engine, rt = _make_engine_and_rt(trust_score=0.3)  # Ensign — only notebook runs
        rt._records_store.write_notebook = AsyncMock()

        agent = MagicMock()
        agent.callsign = "Atlas"
        agent.agent_type = "scout"
        agent.id = "scout_001"

        text = (
            "I observed unusual patterns.\n"
            "[NOTEBOOK observations]\n"
            "Detailed analysis of the codebase patterns.\n"
            "[/NOTEBOOK]\n"
            "This should remain in the Ward Room post."
        )

        result, actions = await engine._extract_and_execute_actions(agent, text)
        assert "[NOTEBOOK" not in result
        assert "[/NOTEBOOK]" not in result
        assert "This should remain" in result

    @pytest.mark.asyncio
    async def test_notebook_stripped_with_leading_whitespace(self):
        """Stripping works even with whitespace differences (the bug cause)."""
        engine, rt = _make_engine_and_rt(trust_score=0.3)
        rt._records_store.write_notebook = AsyncMock()

        agent = MagicMock()
        agent.callsign = "Cora"
        agent.agent_type = "counselor"
        agent.id = "counselor_001"

        text = (
            "Observation.\n"
            "[NOTEBOOK wellness]\n\n"
            "  Content with leading whitespace\n\n"
            "[/NOTEBOOK]\n"
            "Post text."
        )

        result, actions = await engine._extract_and_execute_actions(agent, text)
        assert "[NOTEBOOK" not in result
        assert "[/NOTEBOOK]" not in result
        assert "Post text." in result

    @pytest.mark.asyncio
    async def test_notebook_content_still_saved(self):
        """Notebook content IS written to records_store despite stripping."""
        engine, rt = _make_engine_and_rt(trust_score=0.3)

        agent = MagicMock()
        agent.callsign = "Pascal"
        agent.agent_type = "architect"
        agent.id = "arch_001"

        text = (
            "Observation.\n"
            "[NOTEBOOK analysis]\n"
            "Important analysis content.\n"
            "[/NOTEBOOK]"
        )

        result, actions = await engine._extract_and_execute_actions(agent, text)
        rt._records_store.write_notebook.assert_called_once()
        call_kwargs = rt._records_store.write_notebook.call_args
        saved_content = call_kwargs.kwargs.get("content", "")
        assert "Important analysis content." in saved_content


# ── BF-061: Reply pattern + rank gate ──


class TestReplyPatternAndRank:
    """BF-061: Reply pattern flexibility and Lieutenant+ gate."""

    def test_reply_pattern_matches_thread_prefix(self):
        """Pattern captures thread ID without 'thread:' prefix."""
        pattern = re.compile(
            r'\[REPLY\s+(?:thread:?\s*)?(\S+)\]\s*(.*?)\s*\[/REPLY\]',
            re.DOTALL | re.IGNORECASE,
        )
        text = "[REPLY thread:abc123]\nReply body here\n[/REPLY]"
        m = pattern.search(text)
        assert m is not None
        assert m.group(1) == "abc123"
        assert "Reply body here" in m.group(2)

    def test_reply_pattern_matches_no_newline(self):
        """Pattern matches when body is on same line as tag."""
        pattern = re.compile(
            r'\[REPLY\s+(?:thread:?\s*)?(\S+)\]\s*(.*?)\s*\[/REPLY\]',
            re.DOTALL | re.IGNORECASE,
        )
        text = "[REPLY abc123]Reply body[/REPLY]"
        m = pattern.search(text)
        assert m is not None
        assert m.group(1) == "abc123"
        assert "Reply body" in m.group(2)

    def test_reply_pattern_plain_id(self):
        """Pattern matches plain thread ID without prefix."""
        pattern = re.compile(
            r'\[REPLY\s+(?:thread:?\s*)?(\S+)\]\s*(.*?)\s*\[/REPLY\]',
            re.DOTALL | re.IGNORECASE,
        )
        text = "[REPLY 65a0cf3e-1234-5678-abcd-ef0123456789]\nBody\n[/REPLY]"
        m = pattern.search(text)
        assert m is not None
        assert m.group(1) == "65a0cf3e-1234-5678-abcd-ef0123456789"

    @pytest.mark.asyncio
    async def test_reply_lieutenant_can_reply(self):
        """Lieutenant rank is sufficient for replies (was Commander+)."""
        engine, rt = _make_engine_and_rt(trust_score=0.55)  # Lieutenant
        full_tid = "full-thread-id-1234"
        rt.ward_room.get_thread = AsyncMock(return_value={"thread": {"locked": False}})
        rt.ward_room.create_post = AsyncMock()
        rt.ward_room.list_channels = AsyncMock(return_value=[])
        engine._resolve_thread_id = AsyncMock(return_value=full_tid)

        agent = MagicMock()
        agent.agent_type = "scout"
        agent.id = "scout_001"
        agent.callsign = "Minerva"

        text = "Some obs.\n[REPLY abc123]\nMy reply.\n[/REPLY]\nMore text."

        result, actions = await engine._extract_and_execute_actions(agent, text)
        assert any(a["type"] == "reply" for a in actions), "Lieutenant should be able to reply"

    @pytest.mark.asyncio
    async def test_reply_partial_thread_id_resolved(self):
        """Partial thread ID is resolved via prefix match."""
        from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
        from probos.proactive import ProactiveCognitiveLoop

        engine = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        engine._circuit_breaker = CognitiveCircuitBreaker()
        rt = MagicMock()
        full_tid = "65a0cf3e-1234-5678-abcd-ef0123456789"
        rt.ward_room = MagicMock()
        rt.ward_room.get_thread = AsyncMock(side_effect=lambda tid: {"thread": {}} if tid == full_tid else None)
        ch = MagicMock()
        ch.id = "ch1"
        rt.ward_room.list_channels = AsyncMock(return_value=[ch])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[
            {"thread_id": full_tid, "body": "Original post"},
        ])
        engine._runtime = rt

        resolved = await engine._resolve_thread_id("65a0cf3e")
        assert resolved == full_tid


# ── BF-062: Similarity gate ──


class TestSimilarityGate:
    """BF-062: Improved similarity detection."""

    @pytest.mark.asyncio
    async def test_similar_post_catches_near_duplicate(self):
        """Near-duplicate posts with shared core phrases are caught."""
        from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
        from probos.proactive import ProactiveCognitiveLoop

        engine = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        engine._circuit_breaker = CognitiveCircuitBreaker()
        rt = MagicMock()
        rt.ward_room = MagicMock()
        rt.ontology = MagicMock()
        rt.ontology.get_agent_department = MagicMock(return_value=None)

        ch = MagicMock()
        ch.id = "ch1"
        rt.ward_room.list_channels = AsyncMock(return_value=[ch])
        old_post = "baseline cognitive assessment for crew members completed"
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[
            {"author_id": "agent1", "body": old_post},
        ])
        engine._runtime = rt

        agent = MagicMock()
        agent.id = "agent1"
        agent.agent_type = "counselor"

        # Same core phrase, minor word differences — caught by word OR bigram Jaccard
        new_post = "updated baseline cognitive assessment for crew members finished"
        result = await engine._is_similar_to_recent_posts(agent, new_post)
        assert result is True

    @pytest.mark.asyncio
    async def test_similar_post_checks_ten_posts(self):
        """Post #8 in the list is checked (old limit of 3 would miss it)."""
        from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
        from probos.proactive import ProactiveCognitiveLoop

        engine = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        engine._circuit_breaker = CognitiveCircuitBreaker()
        rt = MagicMock()
        rt.ward_room = MagicMock()
        rt.ontology = MagicMock()
        rt.ontology.get_agent_department = MagicMock(return_value=None)

        ch = MagicMock()
        ch.id = "ch1"
        rt.ward_room.list_channels = AsyncMock(return_value=[ch])
        posts = [{"author_id": "agent1", "body": f"unique post number {i}"} for i in range(7)]
        posts.append({"author_id": "agent1", "body": "establish cognitive baselines for crew"})
        posts.extend([{"author_id": "agent1", "body": f"another unique {i}"} for i in range(2)])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=posts)
        engine._runtime = rt

        agent = MagicMock()
        agent.id = "agent1"
        agent.agent_type = "counselor"

        new_post = "establish cognitive baselines for crew"
        result = await engine._is_similar_to_recent_posts(agent, new_post)
        assert result is True, "Post #8 should be checked with window=10"

    @pytest.mark.asyncio
    async def test_dissimilar_post_passes(self):
        """Genuinely different posts pass both word and bigram checks."""
        from probos.cognitive.circuit_breaker import CognitiveCircuitBreaker
        from probos.proactive import ProactiveCognitiveLoop

        engine = ProactiveCognitiveLoop.__new__(ProactiveCognitiveLoop)
        engine._circuit_breaker = CognitiveCircuitBreaker()
        rt = MagicMock()
        rt.ward_room = MagicMock()
        rt.ontology = MagicMock()
        rt.ontology.get_agent_department = MagicMock(return_value=None)

        ch = MagicMock()
        ch.id = "ch1"
        rt.ward_room.list_channels = AsyncMock(return_value=[ch])
        rt.ward_room.get_recent_activity = AsyncMock(return_value=[
            {"author_id": "agent1", "body": "The warp drive is operating at peak efficiency"},
        ])
        engine._runtime = rt

        agent = MagicMock()
        agent.id = "agent1"
        agent.agent_type = "engineer"

        new_post = "Security sweep of deck three complete, all sections clear"
        result = await engine._is_similar_to_recent_posts(agent, new_post)
        assert result is False
