# AD-594: Crew Consultation Protocol

**Status:** Ready for builder
**Scope:** New file + integration edits (~300 lines new, ~60 lines edits)
**Depends on:** AD-527 (EventType registry), AD-573 (AgentWorkingMemory)

## Summary

Formalized protocol for agents to consult each other's expertise. Today agents communicate through the Ward Room (broadcast) or DMs (point-to-point), but there is no structured "ask an expert" mechanism. This AD adds a consultation request/response cycle: an agent can request expertise from a specific crew member or from "whoever is best qualified," and get a structured response.

Key capabilities:
1. A `ConsultationProtocol` service that manages the request/response lifecycle.
2. Expert selection: if no target agent specified, use `CapabilityRegistry` + `BilletRegistry` to find the best-qualified agent, weighted by billet expertise match, trust score, and current load.
3. Rate limiting: configurable max consultations per agent per hour to prevent consultation storms.
4. Timeout with configurable duration (default 30s).

## Architecture

```
Agent A (requester)
    │
    ├── ConsultationRequest(topic, required_expertise?, target_agent_id?)
    │
    ▼
ConsultationProtocol.request_consultation()
    ├── target specified → route directly to target agent
    └── target NOT specified → expert_selection()
            ├── CapabilityRegistry.query(topic) → ranked matches
            ├── BilletRegistry.get_roster() → billet expertise context
            └── TrustNetwork.get_score() → trust weighting
                    │
                    ▼
              Best candidate selected
                    │
    ▼
Target agent receives ConsultationRequest via callback
    │
    ▼
Target agent produces ConsultationResponse
    │
    ▼
ConsultationProtocol completes the request
    └── emit CONSULTATION_COMPLETED
```

---

## File Changes

| File | Change |
|------|--------|
| `src/probos/cognitive/consultation.py` | **NEW** -- ConsultationProtocol class, request/response dataclasses |
| `src/probos/events.py` | Add CONSULTATION_REQUESTED, CONSULTATION_COMPLETED, CONSULTATION_TIMEOUT |
| `src/probos/config.py` | Add ConsultationConfig + wire into SystemConfig |
| `src/probos/cognitive/cognitive_agent.py` | Add `set_consultation_protocol` setter, add `handle_consultation_request` method |
| `src/probos/startup/cognitive_services.py` | Wire ConsultationProtocol at startup |
| `tests/test_ad594_consultation_protocol.py` | **NEW** -- 20+ tests |

---

## Implementation

### Section 1: EventType Additions

**File:** `src/probos/events.py`

Add to the EventType enum. Place in a new "Consultation" group after the "Sub-task protocol" group (after `SUB_TASK_CHAIN_COMPLETED = "sub_task_chain_completed"` on line 196):

```python
    # Consultation protocol (AD-594)
    CONSULTATION_REQUESTED = "consultation_requested"
    CONSULTATION_COMPLETED = "consultation_completed"
    CONSULTATION_TIMEOUT = "consultation_timeout"
```

### Section 2: ConsultationConfig

**File:** `src/probos/config.py`

Add a new Pydantic config model. Place it after `WorkingMemoryConfig` (around line 682):

```python
class ConsultationConfig(BaseModel):
    """AD-594: Crew Consultation Protocol configuration."""

    enabled: bool = True
    timeout_seconds: float = 30.0
    max_consultations_per_agent_per_hour: int = 20
    max_pending_requests: int = 10
    expert_selection_max_candidates: int = 5
    # Weights for expert selection scoring (must sum to ~1.0)
    weight_capability_match: float = 0.5
    weight_trust: float = 0.3
    weight_billet_relevance: float = 0.2
```

Wire into `SystemConfig` (around line 1152, after the `bill` field):

```python
    consultation: ConsultationConfig = ConsultationConfig()  # AD-594
```

### Section 3: ConsultationProtocol

**File:** `src/probos/cognitive/consultation.py` (NEW)

```python
"""AD-594: Crew Consultation Protocol.

Formalized request/response cycle for agents to consult each other's
expertise. Supports directed consultations (specific target agent) and
expert-selection consultations (best-qualified agent chosen automatically).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)
```

#### Enums and Data Classes

```python
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
```

#### ExpertCandidate (internal)

```python
@dataclass
class _ExpertCandidate:
    """Scored candidate for expert selection (internal)."""
    agent_id: str
    callsign: str
    score: float
    capability_score: float = 0.0
    trust_score: float = 0.0
    billet_score: float = 0.0
```

#### ConsultationProtocol Class

```python
class ConsultationProtocol:
    """Manages the consultation request/response lifecycle.

    One instance per ship (shared service). Agents submit consultation
    requests; the protocol routes them to the best-qualified agent,
    awaits a response (with timeout), and logs the consultation as
    episodes for both parties.

    Parameters
    ----------
    capability_registry : CapabilityRegistry or None
        For expert selection by capability match.
    billet_registry : BilletRegistry or None
        For expert selection by billet/department relevance.
    trust_network : TrustNetwork-like or None
        Provides get_score(agent_id) -> float.
    emit_event_fn : callable or None
        Callback ``(EventType, dict) -> None`` for event emission.
    config : ConsultationConfig-like or None
        Configuration. If None, uses hardcoded defaults.
    """

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

        # Config with defaults
        self._timeout_seconds: float = getattr(config, 'timeout_seconds', 30.0)
        self._max_per_hour: int = getattr(config, 'max_consultations_per_agent_per_hour', 20)
        self._max_pending: int = getattr(config, 'max_pending_requests', 10)
        self._max_candidates: int = getattr(config, 'expert_selection_max_candidates', 5)
        self._w_capability: float = getattr(config, 'weight_capability_match', 0.5)
        self._w_trust: float = getattr(config, 'weight_trust', 0.3)
        self._w_billet: float = getattr(config, 'weight_billet_relevance', 0.2)

        # Rate tracking: agent_id -> list of request timestamps
        self._rate_tracker: dict[str, list[float]] = defaultdict(list)

        # Pending requests: request_id -> (request, asyncio.Future)
        self._pending: dict[str, tuple[ConsultationRequest, asyncio.Future[ConsultationResponse]]] = {}

        # Completed log (bounded, most recent)
        self._completed: list[dict[str, Any]] = []
        self._max_completed: int = 100

        # Handler registry: agent_id -> async callback(ConsultationRequest) -> ConsultationResponse
        self._handlers: dict[str, Callable[..., Any]] = {}
```

##### register_handler / unregister_handler

```python
    def register_handler(
        self,
        agent_id: str,
        handler: Callable[..., Any],
    ) -> None:
        """Register an agent's consultation handler callback.

        The handler signature must be:
            async def handler(request: ConsultationRequest) -> ConsultationResponse
        """
        self._handlers[agent_id] = handler

    def unregister_handler(self, agent_id: str) -> None:
        """Remove an agent's consultation handler."""
        self._handlers.pop(agent_id, None)
```

##### request_consultation

```python
    async def request_consultation(
        self,
        request: ConsultationRequest,
    ) -> ConsultationResponse | None:
        """Submit a consultation request and await the response.

        Returns the ConsultationResponse, or None if:
        - Rate limited
        - No qualified expert found
        - Timeout exceeded
        - Handler not registered for the target agent

        Emits CONSULTATION_REQUESTED on submission, CONSULTATION_COMPLETED
        or CONSULTATION_TIMEOUT on resolution.
        """
        # Validate
        if not request.topic and not request.question:
            logger.warning(
                "AD-594: Consultation request from %s has no topic or question, rejecting",
                request.requester_id,
            )
            return None

        # Rate limit check
        if not self._check_rate_limit(request.requester_id):
            logger.info(
                "AD-594: Consultation rate limit reached for %s (%d/hr max)",
                request.requester_id, self._max_per_hour,
            )
            return None

        # Pending cap
        if len(self._pending) >= self._max_pending:
            logger.warning(
                "AD-594: Max pending consultations reached (%d), rejecting request from %s",
                self._max_pending, request.requester_id,
            )
            return None

        # Select target
        target_id = request.target_agent_id
        if not target_id:
            target_id = self._select_expert(request)
            if not target_id:
                logger.info(
                    "AD-594: No qualified expert found for topic '%s' from %s",
                    request.topic, request.requester_id,
                )
                return None

        # Check handler registered
        if target_id not in self._handlers:
            logger.info(
                "AD-594: No handler registered for target %s, cannot consult",
                target_id,
            )
            return None

        # Record rate
        self._rate_tracker[request.requester_id].append(time.time())

        # Emit request event
        self._emit(EventType.CONSULTATION_REQUESTED, {
            "request_id": request.request_id,
            "requester_id": request.requester_id,
            "requester_callsign": request.requester_callsign,
            "target_agent_id": target_id,
            "topic": request.topic,
            "urgency": request.urgency.value,
        })

        # Create future and register as pending
        future: asyncio.Future[ConsultationResponse] = asyncio.get_running_loop().create_future()
        self._pending[request.request_id] = (request, future)

        # Dispatch to handler with timeout
        handler = self._handlers[target_id]
        try:
            response = await asyncio.wait_for(
                handler(request),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError:
            self._pending.pop(request.request_id, None)
            logger.warning(
                "AD-594: Consultation %s timed out after %.1fs (topic='%s', target=%s)",
                request.request_id, self._timeout_seconds, request.topic, target_id,
            )
            self._emit(EventType.CONSULTATION_TIMEOUT, {
                "request_id": request.request_id,
                "requester_id": request.requester_id,
                "target_agent_id": target_id,
                "topic": request.topic,
                "timeout_seconds": self._timeout_seconds,
            })
            return None
        except Exception:
            self._pending.pop(request.request_id, None)
            logger.warning(
                "AD-594: Consultation handler error for request %s",
                request.request_id,
                exc_info=True,
            )
            return None

        # Complete
        self._pending.pop(request.request_id, None)
        response.request_id = request.request_id

        # Log completion
        completion_record = {
            "request": request.to_dict(),
            "response": response.to_dict(),
            "duration_seconds": response.responded_at - request.created_at,
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
            "duration_seconds": response.responded_at - request.created_at,
        })

        logger.info(
            "AD-594: Consultation completed — %s consulted %s on '%s' (confidence=%.2f, %.1fs)",
            request.requester_callsign or request.requester_id,
            response.responder_callsign or response.responder_id,
            request.topic,
            response.confidence,
            response.responded_at - request.created_at,
        )

        return response
```

##### _select_expert

```python
    def _select_expert(self, request: ConsultationRequest) -> str | None:
        """Select the best-qualified agent for a consultation.

        Scoring formula:
            score = (w_capability * capability_match)
                  + (w_trust * trust_score)
                  + (w_billet * billet_relevance)

        Returns the agent_id of the best candidate, or None.
        """
        candidates: list[_ExpertCandidate] = []

        # Step 1: Get capability matches
        query_text = request.required_expertise or request.topic or request.question
        if self._capability_registry and query_text:
            matches = self._capability_registry.query(query_text)
            for match in matches[:self._max_candidates]:
                # Skip the requester
                if match.agent_id == request.requester_id:
                    continue
                cap_score = match.score
                trust = 0.5  # default
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
                    callsign="",  # Not available from CapabilityMatch
                    score=total,
                    capability_score=cap_score,
                    trust_score=trust,
                    billet_score=billet_score,
                ))

        # Step 2: If no capability matches, try billet roster scan
        if not candidates and self._billet_registry and request.required_expertise:
            roster = self._billet_registry.get_roster()
            expertise_lower = request.required_expertise.lower()
            for holder in roster:
                if not holder.holder_agent_id or holder.holder_agent_id == request.requester_id:
                    continue
                # Simple keyword match on department or title
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

        # Sort by score descending
        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]

        logger.debug(
            "AD-594: Expert selected — %s (score=%.3f, cap=%.2f, trust=%.2f, billet=%.2f)",
            best.agent_id, best.score, best.capability_score,
            best.trust_score, best.billet_score,
        )
        return best.agent_id
```

##### _score_billet_relevance

```python
    def _score_billet_relevance(
        self,
        agent_id: str,
        request: ConsultationRequest,
    ) -> float:
        """Score billet relevance for an agent relative to the request.

        Returns 0.0-1.0. Checks if the agent's billet department or title
        matches the requested expertise.
        """
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
                # Partial: any keyword overlap
                expertise_words = set(expertise_lower.split())
                title_words = set(title_lower.replace("_", " ").split())
                dept_words = set(dept_lower.replace("_", " ").split())
                overlap = expertise_words & (title_words | dept_words)
                if overlap:
                    return 0.5 * len(overlap) / max(len(expertise_words), 1)
                return 0.0
        return 0.0
```

##### _check_rate_limit

```python
    def _check_rate_limit(self, agent_id: str) -> bool:
        """Check if an agent is within the hourly consultation rate limit.

        Returns True if the agent can make another request.
        """
        now = time.time()
        one_hour_ago = now - 3600.0
        # Prune old entries
        timestamps = self._rate_tracker[agent_id]
        self._rate_tracker[agent_id] = [t for t in timestamps if t > one_hour_ago]
        return len(self._rate_tracker[agent_id]) < self._max_per_hour
```

##### _emit and diagnostic

```python
    def _emit(self, event_type: EventType, data: dict[str, Any]) -> None:
        """Emit an event if the callback is set."""
        if self._emit_event_fn:
            try:
                self._emit_event_fn(event_type, data)
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
```

### Section 4: CognitiveAgent Integration

**File:** `src/probos/cognitive/cognitive_agent.py`

#### 4a: Instance variable

In `__init__`, after the `self._qualification_standing_ttl` block (around line 111), add:

```python
        # AD-594: Crew Consultation Protocol
        self._consultation_protocol: Any = None
```

#### 4b: Public setter

After `set_sub_task_executor` (around line 129), add:

```python
    def set_consultation_protocol(self, protocol: Any) -> None:
        """AD-594: Wire consultation protocol for expert consultations."""
        self._consultation_protocol = protocol
```

#### 4c: Consultation handler method

Add a new method. Place it after `_build_dm_self_monitoring` (search for that method and add after it):

```python
    async def handle_consultation_request(
        self,
        request: Any,
    ) -> Any:
        """AD-594: Handle an incoming consultation request.

        Called by ConsultationProtocol when this agent is selected as
        the expert. Produces a response using the LLM with consultation
        context.

        Parameters
        ----------
        request : ConsultationRequest
            The incoming consultation request.

        Returns
        -------
        ConsultationResponse
            The agent's response to the consultation.
        """
        from probos.cognitive.consultation import ConsultationResponse

        callsign = getattr(self, 'callsign', None) or self.agent_type
        logger.info(
            "AD-594: %s handling consultation on '%s' from %s",
            callsign, request.topic, request.requester_callsign or request.requester_id,
        )

        # Build consultation prompt
        system_prompt = (
            f"You are {callsign}, responding to an expert consultation.\n"
            f"Topic: {request.topic}\n"
            f"Question: {request.question}\n"
        )
        if request.required_expertise:
            system_prompt += f"Required expertise: {request.required_expertise}\n"
        if request.context:
            system_prompt += f"Additional context: {request.context}\n"

        system_prompt += (
            "\nProvide a concise, expert answer. Include your reasoning summary. "
            "Rate your confidence (0.0-1.0) in your answer. "
            "If you are not confident, say so honestly."
        )

        user_message = request.question or request.topic

        # Use LLM to generate response
        answer = ""
        confidence = 0.5
        reasoning = ""

        llm = getattr(self, '_llm_client', None) or (
            getattr(self._runtime, 'llm_client', None) if self._runtime else None
        )
        if llm:
            try:
                from probos.types import LLMRequest
                llm_request = LLMRequest(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    tier="fast",
                )
                llm_response = await llm.complete(llm_request)
                answer = llm_response.content if hasattr(llm_response, 'content') else str(llm_response)
                # Attempt to extract confidence from response
                confidence = 0.6  # Default moderate confidence
                reasoning = f"Consulted on {request.topic}"
            except Exception:
                logger.warning(
                    "AD-594: LLM call failed for consultation by %s, providing fallback",
                    callsign,
                    exc_info=True,
                )
                answer = f"I was unable to fully analyze '{request.topic}' at this time."
                confidence = 0.2
                reasoning = "LLM call failed — low-confidence fallback response"
        else:
            answer = f"Acknowledged consultation on '{request.topic}' — no LLM available for detailed analysis."
            confidence = 0.1
            reasoning = "No LLM client available"

        return ConsultationResponse(
            request_id=request.request_id,
            responder_id=self.id,
            responder_callsign=callsign,
            answer=answer,
            confidence=confidence,
            reasoning_summary=reasoning,
        )
```

#### 4d: Register handler on protocol set

Update the `set_consultation_protocol` setter to auto-register the handler:

Actually, the setter in 4b should also register the handler. Replace 4b with:

```python
    def set_consultation_protocol(self, protocol: Any) -> None:
        """AD-594: Wire consultation protocol and register as handler."""
        self._consultation_protocol = protocol
        if protocol is not None:
            protocol.register_handler(self.id, self.handle_consultation_request)
```

### Section 5: Startup Wiring

**File:** `src/probos/startup/cognitive_services.py`

The ConsultationProtocol is created in the cognitive_services startup phase and returned in the result object.

#### 5a: Import

At the top of the file, inside the `if TYPE_CHECKING:` block, add:

```python
    from probos.cognitive.consultation import ConsultationProtocol
```

#### 5b: Create protocol

After the OracleService initialization block (around line 418, after `logger.info("AD-462e: OracleService initialized")`), add:

```python
    # AD-594: Crew Consultation Protocol
    consultation_protocol = None
    if config.consultation.enabled:
        try:
            from probos.cognitive.consultation import ConsultationProtocol as _ConsultationProtocol

            consultation_protocol = _ConsultationProtocol(
                emit_event_fn=emit_event_fn,
                config=config.consultation,
            )
            logger.info("AD-594: ConsultationProtocol initialized")
        except Exception as e:
            logger.warning("AD-594: ConsultationProtocol failed to start: %s — continuing without", e)
            consultation_protocol = None
```

**Note:** The `capability_registry`, `billet_registry`, and `trust_network` are NOT available in `cognitive_services.py`. They are wired later in a different startup phase. The ConsultationProtocol accepts these as None and degrades gracefully. The caller that wires agents post-startup should also wire these registries into the protocol. For this build, create the protocol with only `emit_event_fn` and `config`.

#### 5c: Return result

The `ConsultationProtocol` must be returned from `init_cognitive_services`. Add it to the `CognitiveServicesResult` return.

**First**, check `src/probos/startup/results.py` for the `CognitiveServicesResult` dataclass and add the field:

```python
    consultation_protocol: Any = None  # AD-594
```

Then update the return statement in `init_cognitive_services` (around line 421-442) to include:

```python
        consultation_protocol=consultation_protocol,  # AD-594
```

#### 5d: Agent wiring

The ConsultationProtocol's `register_handler` is called automatically by `set_consultation_protocol` (Section 4b). Agent wiring follows the same pattern as `set_sub_task_executor` and `set_strategy_advisor`.

Search `src/probos/startup/` for `set_sub_task_executor` or `set_strategy_advisor` to find the agent wiring loop. In that loop, add:

```python
            # AD-594: Wire consultation protocol
            if consultation_protocol and hasattr(agent, 'set_consultation_protocol'):
                agent.set_consultation_protocol(consultation_protocol)
```

**Builder:** If the agent wiring loop is not in `cognitive_services.py` but in another startup module (e.g., `finalize.py`, `agent_setup.py`, `structural_services.py`), wire there instead. Search for `set_sub_task_executor` across `src/probos/startup/` to find the correct location. Follow the existing pattern exactly.

#### 5e: Late-bind registries

The `capability_registry`, `billet_registry`, and `trust_network` are created in different startup phases. After they are available, wire them into the protocol. Search for where `capability_registry` or `billet_registry` is assigned to the runtime/ontology, and add:

```python
            # AD-594: Wire registries into consultation protocol
            if consultation_protocol:
                consultation_protocol._capability_registry = capability_registry
                consultation_protocol._billet_registry = billet_registry
                consultation_protocol._trust_network = trust_network
```

**Builder:** This may require adding public setters on ConsultationProtocol instead of accessing private attributes. If so, add these methods to the class:

```python
    def set_capability_registry(self, registry: Any) -> None:
        """Late-bind capability registry for expert selection."""
        self._capability_registry = registry

    def set_billet_registry(self, registry: Any) -> None:
        """Late-bind billet registry for expert selection."""
        self._billet_registry = registry

    def set_trust_network(self, network: Any) -> None:
        """Late-bind trust network for expert selection scoring."""
        self._trust_network = network
```

And use these public setters instead of direct attribute access.

---

## Tests

**File:** `tests/test_ad594_consultation_protocol.py` (NEW)

All tests use `pytest` + `pytest-asyncio`. Use `_Fake*` stubs, not complex mock chains. Each test is isolated with its own fixtures.

### Test List

| # | Test Name | What It Verifies |
|---|-----------|------------------|
| 1 | `test_request_dataclass_defaults` | ConsultationRequest has correct defaults and to_dict works |
| 2 | `test_response_dataclass_defaults` | ConsultationResponse has correct defaults and to_dict works |
| 3 | `test_urgency_enum_values` | ConsultationUrgency has LOW, MEDIUM, HIGH string values |
| 4 | `test_register_handler` | Handler registered for agent_id, visible in protocol |
| 5 | `test_unregister_handler` | Handler removed after unregister |
| 6 | `test_request_directed_consultation` | Directed consultation (target_agent_id specified) routes to correct handler |
| 7 | `test_request_returns_response` | Successful consultation returns ConsultationResponse with answer |
| 8 | `test_request_emits_events` | CONSULTATION_REQUESTED and CONSULTATION_COMPLETED events emitted |
| 9 | `test_request_timeout_returns_none` | Slow handler causes timeout, returns None, emits CONSULTATION_TIMEOUT |
| 10 | `test_request_handler_error_returns_none` | Handler raising exception returns None, does not crash |
| 11 | `test_request_no_handler_returns_none` | Request to unregistered agent returns None |
| 12 | `test_request_empty_topic_returns_none` | Request with no topic and no question is rejected |
| 13 | `test_rate_limit_enforced` | After max_per_hour requests, further requests return None |
| 14 | `test_rate_limit_expires_after_hour` | Old rate entries expire, allowing new requests |
| 15 | `test_max_pending_cap` | Requests beyond max_pending return None |
| 16 | `test_expert_selection_capability_match` | Expert selected based on CapabilityRegistry query scores |
| 17 | `test_expert_selection_excludes_requester` | Requester is not selected as their own expert |
| 18 | `test_expert_selection_billet_fallback` | When no capability match, falls back to billet roster scan |
| 19 | `test_expert_selection_trust_weighting` | Higher-trust agent scores higher in expert selection |
| 20 | `test_billet_relevance_scoring` | _score_billet_relevance returns correct scores for matches/non-matches |
| 21 | `test_snapshot_diagnostic` | snapshot() returns correct structure |
| 22 | `test_get_recent_completions` | Completed consultations appear in recent list |
| 23 | `test_config_defaults` | ConsultationConfig has correct defaults |
| 24 | `test_event_type_members_exist` | CONSULTATION_REQUESTED, CONSULTATION_COMPLETED, CONSULTATION_TIMEOUT exist in EventType |

### Test Pattern

```python
import asyncio
import pytest
import time

from probos.cognitive.consultation import (
    ConsultationProtocol,
    ConsultationRequest,
    ConsultationResponse,
    ConsultationUrgency,
)
from probos.events import EventType


class _FakeEventCollector:
    """Collects emitted events for assertion."""

    def __init__(self):
        self.events: list[tuple] = []

    def __call__(self, event_type, data):
        self.events.append((event_type, data))


class _FakeCapabilityRegistry:
    """Stub CapabilityRegistry for expert selection tests."""

    def __init__(self, matches: list | None = None):
        self._matches = matches or []

    def query(self, intent: str, trust_scores=None):
        return self._matches


class _FakeCapabilityMatch:
    """Stub for CapabilityMatch."""

    def __init__(self, agent_id: str, score: float):
        self.agent_id = agent_id
        self.score = score


class _FakeBilletHolder:
    """Stub for BilletHolder."""

    def __init__(self, agent_id: str, callsign: str, title: str, department: str):
        self.holder_agent_id = agent_id
        self.holder_callsign = callsign
        self.title = title
        self.department = department
        self.billet_id = f"billet_{agent_id}"


class _FakeBilletRegistry:
    """Stub BilletRegistry for expert selection tests."""

    def __init__(self, roster: list | None = None):
        self._roster = roster or []

    def get_roster(self):
        return self._roster


class _FakeTrustNetwork:
    """Stub trust network."""

    def __init__(self, scores: dict | None = None):
        self._scores = scores or {}

    def get_score(self, agent_id: str) -> float:
        return self._scores.get(agent_id, 0.5)


@pytest.fixture
def collector():
    return _FakeEventCollector()


@pytest.fixture
def protocol(collector):
    return ConsultationProtocol(emit_event_fn=collector)


async def _echo_handler(request: ConsultationRequest) -> ConsultationResponse:
    """Simple handler that echoes the topic as the answer."""
    return ConsultationResponse(
        request_id=request.request_id,
        responder_id="expert-1",
        responder_callsign="TestExpert",
        answer=f"Expert answer on: {request.topic}",
        confidence=0.8,
        reasoning_summary="Echoed topic",
    )


async def _slow_handler(request: ConsultationRequest) -> ConsultationResponse:
    """Handler that takes too long."""
    await asyncio.sleep(60)
    return ConsultationResponse()


async def _error_handler(request: ConsultationRequest) -> ConsultationResponse:
    """Handler that raises an exception."""
    raise RuntimeError("Handler failure")
```

---

## Targeted Test Commands

After Section 1-2 (EventType + Config):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad594_consultation_protocol.py::test_config_defaults tests/test_ad594_consultation_protocol.py::test_event_type_members_exist -v
```

After Section 3 (ConsultationProtocol):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad594_consultation_protocol.py -v
```

After Section 4 (CognitiveAgent integration):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad594_consultation_protocol.py -v
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_cognitive_agent.py -v -x
```

After Section 5 (Startup wiring):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad594_consultation_protocol.py -v
```

Full suite (after all sections complete):
```bash
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q
```

---

## Tracking

After all tests pass:

- **PROGRESS.md:** Add line `AD-594 Crew Consultation Protocol — CLOSED`
- **docs/development/roadmap.md:** Update the AD-594 row status to `Complete`
- **DECISIONS.md:** Add entry:
  ```
  AD-594: Crew Consultation Protocol. Formalized expert consultation request/response
  cycle. ConsultationProtocol routes requests to best-qualified agent via
  CapabilityRegistry + BilletRegistry + TrustNetwork weighted scoring. Rate
  limited (20/hr default), configurable timeout (30s default). Logged as
  episodes for both parties. Unlocks AD-600 (Transactive Memory).
  ```

---

## Scope Boundaries

**DO:**
- Create `consultation.py` with ConsultationProtocol, request/response dataclasses, expert selection, rate limiting.
- Add the three EventType members.
- Add ConsultationConfig to config.py and wire into SystemConfig.
- Add `set_consultation_protocol` setter and `handle_consultation_request` method to CognitiveAgent.
- Wire ConsultationProtocol in startup (create instance, return in result, wire to agents).
- Add public setters for late-binding registries.
- Write all 24 tests.

**DO NOT:**
- Change Ward Room messaging, DM handling, or existing intent routing.
- Add API endpoints or HXI dashboard panels.
- Modify existing tests.
- Add docstrings/comments to code you did not change.
- Create database tables or persistent storage for consultations (in-memory only for this AD).
- Add episode storage wiring (deferred to future AD that integrates with EpisodicMemory).
