"""AD-594: Crew Consultation Protocol.

Formalized request/response cycle for agents to consult each other's
expertise. Supports directed consultations and expert-selection
consultations where the best-qualified agent is chosen automatically.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from probos.events import EventType

logger = logging.getLogger(__name__)


class ConsultationUrgency(str, Enum):
    """Urgency level for consultation requests."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ConsultationRequest:
    """A request for expert consultation."""

    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    requester_id: str = ""
    requester_callsign: str = ""
    topic: str = ""
    question: str = ""
    required_expertise: str | None = None
    target_agent_id: str | None = None
    urgency: ConsultationUrgency = ConsultationUrgency.MEDIUM
    context: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "requester_id": self.requester_id,
            "requester_callsign": self.requester_callsign,
            "topic": self.topic,
            "question": self.question,
            "required_expertise": self.required_expertise,
            "target_agent_id": self.target_agent_id,
            "urgency": self.urgency.value,
            "context": self.context,
            "created_at": self.created_at,
        }


@dataclass
class ConsultationResponse:
    """A response to a consultation request."""

    request_id: str = ""
    responder_id: str = ""
    responder_callsign: str = ""
    answer: str = ""
    confidence: float = 0.5
    reasoning_summary: str = ""
    suggested_followup: str | None = None
    responded_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "responder_id": self.responder_id,
            "responder_callsign": self.responder_callsign,
            "answer": self.answer,
            "confidence": self.confidence,
            "reasoning_summary": self.reasoning_summary,
            "suggested_followup": self.suggested_followup,
            "responded_at": self.responded_at,
        }


@dataclass
class _ExpertCandidate:
    """Scored candidate for expert selection."""

    agent_id: str
    callsign: str
    score: float
    capability_score: float = 0.0
    trust_score: float = 0.0
    billet_score: float = 0.0


class ConsultationProtocol:
    """Manages the consultation request/response lifecycle."""

    def __init__(
        self,
        capability_registry: Any = None,
        billet_registry: Any = None,
        trust_network: Any = None,
        emit_event_fn: Callable[[EventType, dict[str, Any]], None] | None = None,
        config: Any = None,
    ) -> None:
        self._capability_registry = capability_registry
        self._billet_registry = billet_registry
        self._trust_network = trust_network
        self._emit_event_fn = emit_event_fn

        if config is not None:
            self._timeout_seconds = config.timeout_seconds
            self._max_per_hour = config.max_consultations_per_agent_per_hour
            self._max_pending = config.max_pending_requests
            self._max_candidates = config.expert_selection_max_candidates
            self._w_capability = config.weight_capability_match
            self._w_trust = config.weight_trust
            self._w_billet = config.weight_billet_relevance
        else:
            self._timeout_seconds = 30.0
            self._max_per_hour = 20
            self._max_pending = 10
            self._max_candidates = 5
            self._w_capability = 0.5
            self._w_trust = 0.3
            self._w_billet = 0.2

        self._rate_tracker: dict[str, list[float]] = defaultdict(list)
        self._pending: dict[
            str, tuple[ConsultationRequest, asyncio.Future[ConsultationResponse]]
        ] = {}
        self._completed: list[dict[str, Any]] = []
        self._max_completed = 100
        self._handlers: dict[str, Callable[..., Any]] = {}

    def set_capability_registry(self, registry: Any) -> None:
        """Late-bind capability registry for expert selection."""
        self._capability_registry = registry

    def set_billet_registry(self, registry: Any) -> None:
        """Late-bind billet registry for expert selection."""
        self._billet_registry = registry

    def set_trust_network(self, network: Any) -> None:
        """Late-bind trust network for expert selection scoring."""
        self._trust_network = network

    def register_handler(self, agent_id: str, handler: Callable[..., Any]) -> None:
        """Register an agent's consultation handler callback."""
        self._handlers[agent_id] = handler

    def unregister_handler(self, agent_id: str) -> None:
        """Remove an agent's consultation handler."""
        self._handlers.pop(agent_id, None)

    async def request_consultation(
        self,
        request: ConsultationRequest,
    ) -> ConsultationResponse | None:
        """Submit a consultation request and await the response."""
        if not request.topic and not request.question:
            logger.warning(
                "AD-594: Consultation request from %s has no topic or question; rejecting",
                request.requester_id,
            )
            return None

        if not self._check_rate_limit(request.requester_id):
            logger.info(
                "AD-594: Consultation rate limit reached for %s (%d/hr max); rejecting",
                request.requester_id,
                self._max_per_hour,
            )
            return None

        if len(self._pending) >= self._max_pending:
            logger.warning(
                "AD-594: Max pending consultations reached (%d); rejecting request from %s",
                self._max_pending,
                request.requester_id,
            )
            return None

        target_id = request.target_agent_id
        if not target_id:
            target_id = self._select_expert(request)
            if not target_id:
                logger.info(
                    "AD-594: No qualified expert found for topic '%s' from %s; rejecting",
                    request.topic,
                    request.requester_id,
                )
                return None

        if target_id not in self._handlers:
            logger.info(
                "AD-594: No handler registered for target %s; consultation rejected",
                target_id,
            )
            return None

        self._rate_tracker[request.requester_id].append(time.time())
        self._emit(EventType.CONSULTATION_REQUESTED, {
            "request_id": request.request_id,
            "requester_id": request.requester_id,
            "requester_callsign": request.requester_callsign,
            "target_agent_id": target_id,
            "topic": request.topic,
            "urgency": request.urgency.value,
        })

        future: asyncio.Future[ConsultationResponse] = asyncio.get_running_loop().create_future()
        self._pending[request.request_id] = (request, future)

        handler = self._handlers[target_id]
        try:
            response = await asyncio.wait_for(
                handler(request),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError:
            self._pending.pop(request.request_id, None)
            logger.warning(
                "AD-594: Consultation %s timed out after %.1fs (topic='%s', target=%s); returning no response",
                request.request_id,
                self._timeout_seconds,
                request.topic,
                target_id,
            )
            self._emit(EventType.CONSULTATION_TIMEOUT, {
                "request_id": request.request_id,
                "requester_id": request.requester_id,
                "target_agent_id": target_id,
                "topic": request.topic,
                "timeout_seconds": self._timeout_seconds,
            })
            return None
        except asyncio.CancelledError:
            self._pending.pop(request.request_id, None)
            raise
        except Exception:
            self._pending.pop(request.request_id, None)
            logger.warning(
                "AD-594: Consultation handler error for request %s "
                "(requester=%s, target=%s, topic='%s'); returning no response",
                request.request_id,
                request.requester_id,
                target_id,
                request.topic,
                exc_info=True,
            )
            self._emit(EventType.CONSULTATION_FAILED, {
                "request_id": request.request_id,
                "requester_id": request.requester_id,
                "target_agent_id": target_id,
                "topic": request.topic,
                "error": "handler_exception",
            })
            return None

        self._pending.pop(request.request_id, None)
        response.request_id = request.request_id
        duration = response.responded_at - request.created_at

        completion_record = {
            "request": request.to_dict(),
            "response": response.to_dict(),
            "duration_seconds": duration,
        }
        self._completed.append(completion_record)
        if len(self._completed) > self._max_completed:
            self._completed = self._completed[-self._max_completed:]

        self._emit(EventType.CONSULTATION_COMPLETED, {
            "request_id": request.request_id,
            "requester_id": request.requester_id,
            "responder_id": response.responder_id,
            "responder_callsign": response.responder_callsign,
            "topic": request.topic,
            "confidence": response.confidence,
            "duration_seconds": duration,
        })

        logger.info(
            "AD-594: Consultation completed: %s consulted %s on '%s' "
            "(confidence=%.2f, %.1fs)",
            request.requester_callsign or request.requester_id,
            response.responder_callsign or response.responder_id,
            request.topic,
            response.confidence,
            duration,
        )
        return response

    def _select_expert(self, request: ConsultationRequest) -> str | None:
        """Select the best-qualified agent for a consultation."""
        candidates: list[_ExpertCandidate] = []
        query_text = request.required_expertise or request.topic or request.question

        if self._capability_registry and query_text:
            matches = self._capability_registry.query(query_text)
            for match in matches[:self._max_candidates]:
                if match.agent_id == request.requester_id:
                    continue
                cap_score = match.score
                trust = 0.5
                if self._trust_network:
                    trust = self._trust_network.get_score(match.agent_id)
                billet_score = self._score_billet_relevance(match.agent_id, request)
                total = (
                    self._w_capability * cap_score
                    + self._w_trust * trust
                    + self._w_billet * billet_score
                )
                candidates.append(_ExpertCandidate(
                    agent_id=match.agent_id,
                    callsign="",
                    score=total,
                    capability_score=cap_score,
                    trust_score=trust,
                    billet_score=billet_score,
                ))

        if not candidates and self._billet_registry and request.required_expertise:
            roster = self._billet_registry.get_roster()
            expertise_lower = request.required_expertise.lower()
            for holder in roster:
                if not holder.holder_agent_id or holder.holder_agent_id == request.requester_id:
                    continue
                title_lower = holder.title.lower()
                dept_lower = holder.department.lower()
                if expertise_lower in title_lower or expertise_lower in dept_lower:
                    trust = 0.5
                    if self._trust_network:
                        trust = self._trust_network.get_score(holder.holder_agent_id)
                    candidates.append(_ExpertCandidate(
                        agent_id=holder.holder_agent_id,
                        callsign=holder.holder_callsign or "",
                        score=self._w_trust * trust + self._w_billet * 0.8,
                        capability_score=0.0,
                        trust_score=trust,
                        billet_score=0.8,
                    ))

        if not candidates:
            return None

        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        best = candidates[0]
        logger.debug(
            "AD-594: Expert selected: %s (score=%.3f, cap=%.2f, trust=%.2f, billet=%.2f)",
            best.agent_id,
            best.score,
            best.capability_score,
            best.trust_score,
            best.billet_score,
        )
        return best.agent_id

    def _score_billet_relevance(
        self,
        agent_id: str,
        request: ConsultationRequest,
    ) -> float:
        """Score billet relevance for an agent relative to the request."""
        if not self._billet_registry:
            return 0.0

        expertise = request.required_expertise or request.topic or ""
        if not expertise:
            return 0.0

        expertise_lower = expertise.lower()
        roster = self._billet_registry.get_roster()
        for holder in roster:
            if holder.holder_agent_id == agent_id:
                title_lower = holder.title.lower()
                dept_lower = holder.department.lower()
                if expertise_lower in title_lower or expertise_lower in dept_lower:
                    return 1.0
                expertise_words = set(expertise_lower.split())
                title_words = set(title_lower.replace("_", " ").split())
                dept_words = set(dept_lower.replace("_", " ").split())
                overlap = expertise_words & (title_words | dept_words)
                if overlap:
                    return 0.5 * len(overlap) / max(len(expertise_words), 1)
                return 0.0
        return 0.0

    def _check_rate_limit(self, agent_id: str) -> bool:
        """Check if an agent is within the hourly consultation rate limit."""
        now = time.time()
        one_hour_ago = now - 3600.0
        timestamps = self._rate_tracker[agent_id]
        self._rate_tracker[agent_id] = [t for t in timestamps if t > one_hour_ago]
        if not self._rate_tracker[agent_id]:
            del self._rate_tracker[agent_id]
            return True
        return len(self._rate_tracker[agent_id]) < self._max_per_hour

    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Emit an event if the callback is set."""
        if self._emit_event_fn is None:
            return
        try:
            self._emit_event_fn(event_type, data)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug(
                "AD-594: Failed to emit %s", event_type, exc_info=True,
            )

    @property
    def pending_count(self) -> int:
        """Number of consultations currently awaiting responses."""
        return len(self._pending)

    @property
    def completed_count(self) -> int:
        """Number of completed consultations in the recent log."""
        return len(self._completed)

    def get_recent_completions(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most recent completed consultations."""
        return list(reversed(self._completed[-limit:]))

    def snapshot(self) -> dict[str, Any]:
        """Diagnostic snapshot for monitoring."""
        return {
            "pending_count": self.pending_count,
            "completed_count": self.completed_count,
            "handlers_registered": len(self._handlers),
            "rate_tracker_agents": len(self._rate_tracker),
        }