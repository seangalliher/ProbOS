"""BF-630: keyword_search OR-expands natural-language queries before FTS5 MATCH.

Root cause (proven live, 2026-06-18): the 1:1 DM recall path runs
``_recall_relevant_memories`` -> ``recall_weighted`` -> ``keyword_search``,
which passed the RAW Captain message straight to FTS5 ``MATCH``. A
conversational string is a *phrase* query to FTS5 (and a hard
``fts5: syntax error`` on the trailing ``?``), so the keyword axis silently
returned nothing for real questions like "What do you know about my dogs?".
Only the dense cosine axis ran, and when it under-ranked the relevant episode
the agent reported no memory of it (the giant-schnauzer cross-session miss).

BF-630 centralises the natural-language -> FTS5 OR-of-keywords translation
inside ``keyword_search`` (via ``fts_or_query``) so every caller is correct by
construction. OR matching is a strict superset of the old phrase/AND
behaviour, so previously-found episodes are still found.
"""

from __future__ import annotations

import functools
import time

import pytest

from probos.types import Episode


async def _start_episodic_memory(em) -> None:
    try:
        await em.start()
    except Exception as exc:  # pragma: no cover - environment guard
        if "INVALID_PROTOBUF" in str(exc) or "onnx" in str(exc).lower():
            pytest.skip(f"ChromaDB ONNX model unavailable: {exc}")
        raise


def _skip_on_onnx_error(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - environment guard
            if "INVALID_PROTOBUF" in str(exc) or "onnx" in str(exc).lower():
                pytest.skip(f"ChromaDB ONNX model unavailable: {exc}")
            raise

    return wrapper


def _make_episode(*, user_input: str, agent_ids: list[str] | None = None,
                  timestamp: float | None = None) -> Episode:
    return Episode(
        user_input=user_input,
        timestamp=timestamp or time.time(),
        agent_ids=agent_ids or ["agent-001"],
        source="direct",
        outcomes=[{"intent": "direct_message", "success": True}],
    )


class TestKeywordSearchNaturalLanguage:
    """keyword_search must handle raw conversational queries."""

    @pytest.mark.asyncio
    @_skip_on_onnx_error
    async def test_punctuated_nl_question_no_longer_errors_and_finds_match(self, tmp_path):
        """The exact failing case: a question ending in '?' surfaces the episode.

        Pre-BF-630 this raised ``fts5: syntax error near "?"`` inside
        keyword_search (caught -> returned []), so the dog episode was invisible
        to the keyword axis. Post-BF-630 the query is OR-expanded and the
        porter-stemmed token ``dogs`` -> ``dog`` matches the stored episode.
        """
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100)
        await _start_episodic_memory(em)
        try:
            ep = _make_episode(
                user_input="My dog Grim is a giant schnauzer and a very good boy",
            )
            await em.store(ep)

            results = await em.keyword_search("What do you know about my dogs?", k=5)

            found_ids = [r[0] for r in results]
            assert ep.id in found_ids, (
                "BF-630: punctuated NL question must surface the keyword-matched "
                f"episode; got {found_ids}"
            )
        finally:
            await em.stop()

    @pytest.mark.asyncio
    @_skip_on_onnx_error
    async def test_or_semantics_match_any_token(self, tmp_path):
        """OR-of-keywords: an episode sharing ANY content token is found.

        The stored episode shares only the token 'schnauzer' with the query;
        under the pre-BF-630 phrase semantics the multi-word query would not
        have matched.
        """
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100)
        await _start_episodic_memory(em)
        try:
            ep = _make_episode(user_input="The schnauzer trotted across the bridge")
            await em.store(ep)

            results = await em.keyword_search(
                "do you remember anything about a schnauzer", k=5,
            )

            assert ep.id in [r[0] for r in results]
        finally:
            await em.stop()

    @pytest.mark.asyncio
    @_skip_on_onnx_error
    async def test_single_word_query_still_works(self, tmp_path):
        """Regression guard: single-keyword queries are unaffected by the fix."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100)
        await _start_episodic_memory(em)
        try:
            ep = _make_episode(user_input="quantum entanglement experiment results")
            await em.store(ep)

            results = await em.keyword_search("quantum", k=5)

            assert ep.id in [r[0] for r in results]
        finally:
            await em.stop()

    @pytest.mark.asyncio
    @_skip_on_onnx_error
    async def test_empty_or_stopword_only_query_returns_empty(self, tmp_path):
        """A query that yields no usable FTS tokens returns [] (no crash)."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(str(tmp_path / "ep.db"), max_episodes=100)
        await _start_episodic_memory(em)
        try:
            await em.store(_make_episode(user_input="anything at all"))

            # Punctuation-only / single-char tokens -> fts_or_query yields ""
            assert await em.keyword_search("? ! .", k=5) == []
            assert await em.keyword_search("", k=5) == []
        finally:
            await em.stop()


class TestRecallWeightedNaturalLanguage:
    """End-to-end: the live DM recall method surfaces NL keyword matches."""

    @pytest.mark.asyncio
    @_skip_on_onnx_error
    async def test_recall_weighted_surfaces_keyword_match_for_nl_question(self, tmp_path):
        """The live 1:1 DM path (recall_weighted) surfaces an owned episode that
        a conversational question keyword-matches but the dense axis misses.

        relevance_threshold=0.99 blocks the semantic axis (mirrors the AD-567b
        merge test), isolating the keyword axis. Pre-BF-630 recall_weighted
        passed the raw "What do you know about my dogs?" to keyword_search,
        which errored on the '?' and returned [] -> the episode never surfaced.
        """
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(
            str(tmp_path / "ep.db"), max_episodes=100,
            relevance_threshold=0.99,  # block the semantic axis
        )
        await _start_episodic_memory(em)
        try:
            ep = _make_episode(
                user_input="My dog Grim is a giant schnauzer",
                agent_ids=["agent-001"],
            )
            await em.store(ep)

            results = await em.recall_weighted(
                "agent-001", "What do you know about my dogs?",
                k=5, context_budget=10000,
            )

            assert any(rs.episode.id == ep.id for rs in results), (
                "BF-630: recall_weighted must surface the keyword-matched dog "
                f"episode for an NL question; got {[rs.episode.id for rs in results]}"
            )
        finally:
            await em.stop()

    @pytest.mark.asyncio
    @_skip_on_onnx_error
    async def test_recall_weighted_keyword_match_respects_shard(self, tmp_path):
        """Sovereign isolation: a keyword match owned by ANOTHER agent is not
        returned in this agent's recall_weighted result (the merge filters on
        ``agent_id in agent_ids``)."""
        from probos.cognitive.episodic import EpisodicMemory

        em = EpisodicMemory(
            str(tmp_path / "ep.db"), max_episodes=100,
            relevance_threshold=0.99,
        )
        await _start_episodic_memory(em)
        try:
            other = _make_episode(
                user_input="My dog Grim is a giant schnauzer",
                agent_ids=["agent-OTHER"],
            )
            await em.store(other)

            results = await em.recall_weighted(
                "agent-001", "What do you know about my dogs?",
                k=5, context_budget=10000,
            )

            assert all(rs.episode.id != other.id for rs in results), (
                "another agent's keyword-matched episode leaked into recall_weighted"
            )
        finally:
            await em.stop()
