"""AD-478 v1: Meta-Learning -- Workspace Ontology read-only register.

Bounded in-memory frequency-tracking term registry. Callers register terms
manually in v1; auto-discovery from dream cycles is AD-478b. Persistent
goals and abstract pattern recognition are AD-478c/d.

Privacy invariant: ``WORKSPACE_TERM_REGISTERED`` payload includes only
``term_length`` (NOT the term itself), matching the AD-530/AD-511 pattern.
"""

from __future__ import annotations

import logging
from typing import Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


class WorkspaceOntologyRegistry:
    """v1 in-memory frequency-bounded term registry. AD-478 v1.

    Future consumer (AD-478b): dream cycle auto-discovers terms. v1 callers
    register terms manually. Eviction policy: when ``len(_terms)`` exceeds
    ``max_terms`` after an insert, the lowest-frequency term is dropped.
    Tie-break is dict insertion order (Python 3.7+ preserves insertion
    order; ``min`` is stable, so the earliest-inserted lowest-frequency term
    is evicted first).
    """

    def __init__(
        self,
        max_terms: int = 1000,
        *,
        emit_event: Callable[..., None] | None = None,
    ) -> None:
        self._max_terms = max_terms
        self._terms: dict[str, int] = {}  # term -> frequency
        # Public field per Wave 5 convention #1; mirrors AD-530 ClassificationGate.
        self.emit_event = emit_event

    def add_term(self, term: str, frequency: int = 1) -> None:
        """Register or increment a term's frequency.

        No-op for empty ``term``. Emits ``WORKSPACE_TERM_REGISTERED`` only
        on the first insertion of a term (not on subsequent increments) to
        bound event volume.
        """
        if not term:
            return
        is_new = term not in self._terms
        self._terms[term] = self._terms.get(term, 0) + frequency
        if len(self._terms) > self._max_terms:
            # Evict lowest-frequency term (insertion-order tie-break).
            evict = min(self._terms.items(), key=lambda kv: kv[1])[0]
            del self._terms[evict]
        if is_new and term in self._terms:
            self._emit(term, self._terms[term])

    def top_terms(self, k: int = 20) -> tuple[tuple[str, int], ...]:
        """Top ``k`` terms by frequency, descending. ``k <= 0`` returns ``()``."""
        if k <= 0:
            return ()
        sorted_terms = sorted(
            self._terms.items(),
            key=lambda kv: kv[1],
            reverse=True,
        )
        return tuple(sorted_terms[:k])

    def get_frequency(self, term: str) -> int:
        """Return frequency for ``term`` (0 if not registered)."""
        return self._terms.get(term, 0)

    def term_count(self) -> int:
        """Return current number of distinct terms tracked."""
        return len(self._terms)

    def _emit(self, term: str, frequency: int) -> None:
        if self.emit_event is None:
            return
        try:
            self.emit_event(
                EventType.WORKSPACE_TERM_REGISTERED,
                # Privacy: term length, not term itself (AD-530/AD-511 pattern).
                {"term_length": len(term), "frequency": frequency},
            )
        except Exception:
            logger.warning(
                "AD-478: emit_event failed for WORKSPACE_TERM_REGISTERED; continuing",
                exc_info=True,
            )
