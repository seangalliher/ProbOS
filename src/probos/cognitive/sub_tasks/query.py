"""AD-632b: Query Sub-Task Handler — deterministic data retrieval (zero LLM calls).

Routes `spec.context_keys` to ProbOS service methods via a dispatch table.
Open/Closed: new query operations are added by registering new keys in
`_QUERY_OPERATIONS` — zero changes to `__call__()`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any, Callable, Coroutine

from probos.cognitive.sub_task import SubTaskResult, SubTaskSpec, SubTaskType

logger = logging.getLogger(__name__)

# Type alias for async query operation functions
QueryOperation = Callable[
    [Any, SubTaskSpec, dict],  # runtime, spec, context
    Coroutine[Any, Any, dict],
]


# ---------------------------------------------------------------------------
# Individual query operations — each maps to exactly one ProbOS service method
# ---------------------------------------------------------------------------


async def _query_thread_metadata(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """Retrieve thread metadata from WardRoomService."""
    ward_room = getattr(runtime, "ward_room", None)
    if ward_room is None:
        raise _ServiceUnavailableError("WardRoomService")

    thread_id = context.get("thread_id", "")
    if not thread_id:
        raise ValueError("thread_id required for thread_metadata query")

    thread = await ward_room.get_thread(thread_id)
    if thread is None:
        raise ValueError(f"Thread not found: {thread_id}")

    return {"thread_metadata": thread}


async def _query_thread_activity(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """Retrieve recent activity for a channel."""
    ward_room = getattr(runtime, "ward_room", None)
    if ward_room is None:
        raise _ServiceUnavailableError("WardRoomService")

    channel_id = context.get("channel_id", "")
    if not channel_id:
        raise ValueError("channel_id required for thread_activity query")

    since = context.get("since", 0.0)
    limit = context.get("limit", 10)
    posts = await ward_room.get_recent_activity(channel_id, since, limit=limit)
    return {"thread_activity": posts}


async def _query_comm_stats(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """Retrieve agent communication statistics."""
    ward_room = getattr(runtime, "ward_room", None)
    if ward_room is None:
        raise _ServiceUnavailableError("WardRoomService")

    agent_id = context.get("agent_id", "")
    if not agent_id:
        raise ValueError("agent_id required for comm_stats query")

    since = context.get("since")
    stats = await ward_room.get_agent_comm_stats(agent_id, since=since)
    return {"comm_stats": stats}


async def _query_credibility(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """Retrieve agent credibility from WardRoomService."""
    ward_room = getattr(runtime, "ward_room", None)
    if ward_room is None:
        raise _ServiceUnavailableError("WardRoomService")

    agent_id = context.get("agent_id", "")
    if not agent_id:
        raise ValueError("agent_id required for credibility query")

    cred = await ward_room.get_credibility(agent_id)
    # WardRoomCredibility is a dataclass — convert to plain dict
    return {"credibility": asdict(cred)}


async def _query_unread_counts(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """Retrieve unread message counts per channel."""
    ward_room = getattr(runtime, "ward_room", None)
    if ward_room is None:
        raise _ServiceUnavailableError("WardRoomService")

    agent_id = context.get("agent_id", "")
    if not agent_id:
        raise ValueError("agent_id required for unread_counts query")

    counts = await ward_room.get_unread_counts(agent_id)
    return {"unread_counts": counts}


async def _query_unread_dms(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """Retrieve unread direct messages."""
    ward_room = getattr(runtime, "ward_room", None)
    if ward_room is None:
        raise _ServiceUnavailableError("WardRoomService")

    agent_id = context.get("agent_id", "")
    if not agent_id:
        raise ValueError("agent_id required for unread_dms query")

    limit = context.get("limit", 3)
    dms = await ward_room.get_unread_dms(agent_id, limit=limit)
    return {"unread_dms": dms}


async def _query_trust_score(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """Retrieve trust score for an agent."""
    trust = getattr(runtime, "trust_network", None)
    if trust is None:
        raise _ServiceUnavailableError("TrustNetwork")

    agent_id = context.get("agent_id", "")
    if not agent_id:
        raise ValueError("agent_id required for trust_score query")

    score = trust.get_score(agent_id)  # sync method
    return {"trust_score": {"score": score}}


async def _query_trust_summary(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """Retrieve trust summary for all agents."""
    trust = getattr(runtime, "trust_network", None)
    if trust is None:
        raise _ServiceUnavailableError("TrustNetwork")

    summary = trust.summary()  # sync method
    return {"trust_summary": summary}


async def _query_posts_by_author(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """Retrieve recent posts by a specific author callsign."""
    ward_room = getattr(runtime, "ward_room", None)
    if ward_room is None:
        raise _ServiceUnavailableError("WardRoomService")

    callsign = context.get("author_callsign", "")
    if not callsign:
        raise ValueError("author_callsign required for posts_by_author query")

    limit = context.get("limit", 5)
    posts = await ward_room.get_posts_by_author(callsign, limit=limit)
    return {"posts_by_author": posts}


# ---------------------------------------------------------------------------
# Dispatch table — Open/Closed: add new operations here, no __call__ changes
# ---------------------------------------------------------------------------

_QUERY_OPERATIONS: dict[str, QueryOperation] = {
    "thread_metadata": _query_thread_metadata,
    "thread_activity": _query_thread_activity,
    "comm_stats": _query_comm_stats,
    "credibility": _query_credibility,
    "unread_counts": _query_unread_counts,
    "unread_dms": _query_unread_dms,
    "trust_score": _query_trust_score,
    "trust_summary": _query_trust_summary,
    "posts_by_author": _query_posts_by_author,
}


# ---------------------------------------------------------------------------
# Internal error for service unavailability
# ---------------------------------------------------------------------------

class _ServiceUnavailableError(Exception):
    """Raised when a required runtime service is not available."""
    def __init__(self, service_name: str) -> None:
        self.service_name = service_name
        super().__init__(f"{service_name} not available")


# ---------------------------------------------------------------------------
# QueryHandler — the SubTaskHandler implementation
# ---------------------------------------------------------------------------

class QueryHandler:
    """Deterministic data retrieval handler — zero LLM calls.

    Receives a runtime reference at construction (DIP). Dispatches
    `spec.context_keys` to query operations via `_QUERY_OPERATIONS` table.

    Usage::

        handler = QueryHandler(runtime)
        executor.register_handler(SubTaskType.QUERY, handler)
    """

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    async def __call__(
        self,
        spec: SubTaskSpec,
        context: dict,
        prior_results: list[SubTaskResult],
    ) -> SubTaskResult:
        """Execute query operations specified by spec.context_keys."""
        start = time.monotonic()

        if self._runtime is None:
            return SubTaskResult(
                sub_task_type=SubTaskType.QUERY,
                name=spec.name,
                result={},
                tokens_used=0,
                duration_ms=0.0,
                success=False,
                error="Runtime not available",
                tier_used="",
            )

        if not spec.context_keys:
            # No operations requested — return empty success
            duration = (time.monotonic() - start) * 1000
            return SubTaskResult(
                sub_task_type=SubTaskType.QUERY,
                name=spec.name,
                result={},
                tokens_used=0,
                duration_ms=duration,
                success=True,
                tier_used="",
            )

        merged_result: dict[str, Any] = {}
        errors: list[str] = []

        # Dispatch only known operation keys — other context_keys are data
        # keys that the executor uses for context filtering (passthrough)
        operation_keys = [k for k in spec.context_keys if k in _QUERY_OPERATIONS]

        if not operation_keys:
            # context_keys had values, but none are known operations
            unknown = [k for k in spec.context_keys if k not in _QUERY_OPERATIONS]
            if unknown:
                duration = (time.monotonic() - start) * 1000
                return SubTaskResult(
                    sub_task_type=SubTaskType.QUERY,
                    name=spec.name,
                    result={},
                    tokens_used=0,
                    duration_ms=duration,
                    success=False,
                    error=f"Unknown operation key: {', '.join(unknown)}",
                    tier_used="",
                )

        for key in operation_keys:
            operation = _QUERY_OPERATIONS[key]
            try:
                data = await operation(self._runtime, spec, context)
                merged_result.update(data)
            except _ServiceUnavailableError as exc:
                errors.append(f"{key}: {exc}")
                logger.debug("AD-632b: Service unavailable for '%s': %s", key, exc)
            except Exception as exc:
                errors.append(f"{key}: {exc}")
                logger.warning("AD-632b: Query operation '%s' failed: %s", key, exc)

        duration = (time.monotonic() - start) * 1000
        success = len(errors) == 0

        return SubTaskResult(
            sub_task_type=SubTaskType.QUERY,
            name=spec.name,
            result=merged_result,
            tokens_used=0,
            duration_ms=duration,
            success=success,
            error="; ".join(errors) if errors else "",
            tier_used="",
        )
