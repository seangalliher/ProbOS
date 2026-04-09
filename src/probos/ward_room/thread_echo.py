"""AD-583g: Ward Room thread echo detection and source tracing.

Analyzes a Ward Room thread's post history to identify amplification
chains — where multiple agents echo the same content without independent
evidence. Identifies the "Patient Zero" (source post) and the propagation
chain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PropagationStep:
    """One step in an echo propagation chain."""

    callsign: str
    post_id: str
    timestamp: float
    similarity_to_source: float


@dataclass(frozen=True)
class ThreadEchoResult:
    """Result of thread echo analysis.

    echo_detected=False means the thread does not show amplification patterns.
    When True, source_* fields identify Patient Zero and propagation_chain
    shows how the content spread.
    """

    echo_detected: bool
    thread_id: str
    source_post_id: str = ""
    source_callsign: str = ""
    source_timestamp: float = 0.0
    propagation_chain: list[PropagationStep] = field(default_factory=list)
    chain_length: int = 0
    anchor_independence_score: float = 1.0


class ThreadManagerProtocol(Protocol):
    """Narrow protocol for thread data access (ISP)."""

    async def get_thread_posts_temporal(
        self, thread_id: str
    ) -> list[dict[str, Any]]: ...


class ThreadEchoAnalyzer:
    """Analyze Ward Room threads for echo amplification patterns.

    Constructor-injected dependencies (DIP). Uses ThreadManagerProtocol
    to access thread data, not the full ThreadManager.
    """

    def __init__(
        self,
        thread_manager: ThreadManagerProtocol,
        *,
        min_chain_length: int = 3,
        similarity_threshold: float = 0.4,
    ) -> None:
        self._thread_manager = thread_manager
        self._min_chain_length = min_chain_length
        self._similarity_threshold = similarity_threshold

    async def analyze(self, thread_id: str) -> ThreadEchoResult:
        """Analyze a thread for echo amplification patterns.

        Algorithm:
        1. Get flat temporal post list.
        2. If fewer than min_chain_length unique authors, return no echo.
        3. Tokenize each post. Keep first post per author.
        4. Build propagation chain from source through echoing authors.
        5. If chain >= min_chain_length, compute anchor independence.
        """
        posts = await self._thread_manager.get_thread_posts_temporal(thread_id)
        if not posts:
            return ThreadEchoResult(echo_detected=False, thread_id=thread_id)

        from probos.cognitive.similarity import jaccard_similarity, text_to_words

        # Tokenize all posts
        for post in posts:
            post["_words"] = text_to_words(post.get("body", ""))

        # Keep first post per author (their initial contribution)
        seen_authors: dict[str, dict[str, Any]] = {}
        for post in posts:
            author = post.get("author_id", "")
            if author and author not in seen_authors:
                seen_authors[author] = post

        unique_authors = list(seen_authors.values())
        if len(unique_authors) < self._min_chain_length:
            return ThreadEchoResult(echo_detected=False, thread_id=thread_id)

        # Source is the first post (thread body)
        source = posts[0]
        source_words = source["_words"]
        if not source_words:
            return ThreadEchoResult(echo_detected=False, thread_id=thread_id)

        # Build propagation chain: subsequent authors whose first post
        # is similar to the source
        chain: list[PropagationStep] = []
        for author_post in unique_authors[1:]:  # Skip source author
            sim = jaccard_similarity(source_words, author_post["_words"])
            if sim >= self._similarity_threshold:
                chain.append(PropagationStep(
                    callsign=author_post.get("author_callsign", ""),
                    post_id=author_post.get("id", ""),
                    timestamp=author_post.get("created_at", 0.0),
                    similarity_to_source=sim,
                ))

        # Include source in chain length count
        chain_length = len(chain) + 1  # +1 for source
        if chain_length < self._min_chain_length:
            return ThreadEchoResult(echo_detected=False, thread_id=thread_id)

        # Sort chain by timestamp
        chain.sort(key=lambda s: s.timestamp)

        # Compute anchor independence — all same thread → low score
        independence = 1.0
        try:
            from types import SimpleNamespace
            from probos.cognitive.social_verification import (
                compute_anchor_independence,
            )

            episodes = []
            # Source episode
            episodes.append(SimpleNamespace(
                anchors=SimpleNamespace(thread_id=thread_id),
                timestamp=source.get("created_at", 0.0),
            ))
            # Chain participant episodes
            for step in chain:
                episodes.append(SimpleNamespace(
                    anchors=SimpleNamespace(thread_id=thread_id),
                    timestamp=step.timestamp,
                ))
            independence = compute_anchor_independence(episodes)
        except Exception:
            logger.debug("AD-583g: Independence scoring failed", exc_info=True)

        return ThreadEchoResult(
            echo_detected=True,
            thread_id=thread_id,
            source_post_id=source.get("id", ""),
            source_callsign=source.get("author_callsign", ""),
            source_timestamp=source.get("created_at", 0.0),
            propagation_chain=chain,
            chain_length=chain_length,
            anchor_independence_score=independence,
        )
