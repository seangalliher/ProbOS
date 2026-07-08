"""AD-482d v1: Evolution Store -- append-only lessons learned with time-decay.

ChromaDB-backed semantic store mirroring `EpisodicMemory` construction shape,
but on a separate collection (``self_improvement_lessons``) and with a
time-decay weighting layered over cosine similarity.

Tier-2 log-and-degrade: when ``chroma_client`` is None the store keeps lessons
in an in-memory list and serves recall via plain substring matching. The
public API contract is identical in both modes.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Lesson:
    """One append-only lesson record."""

    id: str
    category: str  # "approved", "rejected", "pivot", custom
    summary: str
    source_proposal_id: str
    outcome: str
    timestamp: float
    payload: dict[str, Any] = field(default_factory=dict)


class EvolutionStore:
    """Append-only lessons store with time-decay recall."""

    def __init__(
        self,
        *,
        chroma_client: Any = None,
        collection_name: str = "self_improvement_lessons",
        clock: Callable[[], float] = time.time,
        half_life_seconds: float = 2592000.0,  # 30 days
        event_emit_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._client = chroma_client
        self._collection_name = collection_name
        self._clock = clock
        self._half_life = max(1.0, half_life_seconds)
        self._emit = event_emit_fn
        self._collection: Any = None
        self._fallback: list[Lesson] = []  # used when chroma is None

    def start(self) -> None:
        """Open the chroma collection. Tier-2 log-and-degrade on failure.

        Safe to call multiple times -- idempotent.
        """
        if self._client is None:
            return
        if self._collection is not None:
            return
        try:
            from probos.knowledge.embeddings import get_collection_embedding_function

            ef = get_collection_embedding_function()
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                embedding_function=ef,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception:
            logger.warning(
                "AD-482d: failed to open chroma collection %r; falling back to in-memory",
                self._collection_name,
                exc_info=True,
            )
            self._collection = None

    def record_lesson(
        self,
        category: str,
        summary: str,
        source_proposal_id: str,
        outcome: str,
        payload: dict[str, Any],
    ) -> str:
        """Append a lesson. Returns the lesson id."""
        lesson = Lesson(
            id=uuid.uuid4().hex[:12],
            category=category,
            summary=summary,
            source_proposal_id=source_proposal_id,
            outcome=outcome,
            timestamp=self._clock(),
            payload=dict(payload),
        )
        if self._collection is not None:
            try:
                self._collection.add(
                    ids=[lesson.id],
                    documents=[lesson.summary],
                    metadatas=[
                        {
                            "category": lesson.category,
                            "source_proposal_id": lesson.source_proposal_id,
                            "outcome": lesson.outcome,
                            "timestamp": lesson.timestamp,
                        }
                    ],
                )
            except Exception:
                logger.warning(
                    "AD-482d: chroma add failed for lesson %s; falling back",
                    lesson.id,
                    exc_info=True,
                )
                self._fallback.append(lesson)
        else:
            self._fallback.append(lesson)
        self._emit_event(
            "EVOLUTION_LESSON_RECORDED",
            lesson_id=lesson.id,
            category=lesson.category,
            outcome=lesson.outcome,
        )
        return lesson.id

    def recall(
        self,
        query: str,
        *,
        top_k: int = 5,
        now: float | None = None,
    ) -> list[Lesson]:
        """Return top-k lessons ranked by ``similarity * time_decay``.

        Time decay: ``0.5 ** ((now - timestamp) / half_life)``.
        Older lessons fade; recent lessons retained.
        """
        when = self._clock() if now is None else now
        if self._collection is not None:
            try:
                hits = self._collection.query(query_texts=[query], n_results=max(top_k * 2, top_k))
                ids_batch = hits.get("ids") or [[]]
                docs_batch = hits.get("documents") or [[]]
                metas_batch = hits.get("metadatas") or [[]]
                dists_batch = hits.get("distances") or [[]]
                ids = ids_batch[0] if ids_batch else []
                docs = docs_batch[0] if docs_batch else []
                metas = metas_batch[0] if metas_batch else []
                dists = dists_batch[0] if dists_batch else [0.0] * len(ids)
                scored: list[tuple[float, Lesson]] = []
                for lid, doc, meta, dist in zip(ids, docs, metas, dists, strict=False):
                    similarity = max(0.0, 1.0 - float(dist))
                    ts = float(meta.get("timestamp", when))
                    age = max(0.0, when - ts)
                    decay = 0.5 ** (age / self._half_life)
                    score = similarity * decay
                    lesson = Lesson(
                        id=lid,
                        category=str(meta.get("category", "")),
                        summary=str(doc),
                        source_proposal_id=str(meta.get("source_proposal_id", "")),
                        outcome=str(meta.get("outcome", "")),
                        timestamp=ts,
                        payload={},
                    )
                    scored.append((score, lesson))
                scored.sort(key=lambda x: x[0], reverse=True)
                return [lesson for _, lesson in scored[:top_k]]
            except Exception:
                logger.warning(
                    "AD-482d: chroma query failed; using in-memory fallback",
                    exc_info=True,
                )
        # Fallback: substring match + time-decay
        scored_fb: list[tuple[float, Lesson]] = []
        q_lower = query.lower()
        for lesson in self._fallback:
            similarity = 1.0 if q_lower in lesson.summary.lower() else 0.1
            age = max(0.0, when - lesson.timestamp)
            decay = 0.5 ** (age / self._half_life)
            scored_fb.append((similarity * decay, lesson))
        scored_fb.sort(key=lambda x: x[0], reverse=True)
        return [lesson for _, lesson in scored_fb[:top_k]]

    def _emit_event(self, name: str, **payload: Any) -> None:
        if self._emit is None:
            return
        try:
            self._emit(name, payload)
        except Exception:
            logger.warning("AD-482d: event_emit %s failed", name, exc_info=True)
