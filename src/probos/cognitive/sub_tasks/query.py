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


def _ctx(context: dict, key: str, default: str = "") -> str:
    """Resolve a key from context, falling back to nested params dict."""
    val = context.get(key, "")
    if not val:
        params = context.get("params")
        if isinstance(params, dict):
            val = params.get(key, "")
    return val or default

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

    thread_id = _ctx(context, "thread_id")
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

    channel_id = _ctx(context, "channel_id")
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

    agent_id = context.get("_agent_id", "") or _ctx(context, "agent_id")
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

    agent_id = context.get("_agent_id", "") or _ctx(context, "agent_id")
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

    agent_id = context.get("_agent_id", "") or _ctx(context, "agent_id")
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

    agent_id = context.get("_agent_id", "") or _ctx(context, "agent_id")
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

    agent_id = context.get("_agent_id", "") or _ctx(context, "agent_id")
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


async def _query_self_monitoring(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """AD-646b: Self-monitoring for chain ward_room path.

    DM threads: check agent's recent posts for self-repetition (Jaccard).
    All threads: report cognitive zone if not green.
    """
    result_parts: list[str] = []

    # DM self-monitoring: check for self-repetition in thread
    channel_name = _ctx(context, "channel_name")
    if channel_name.startswith("dm-"):
        ward_room = getattr(runtime, "ward_room", None)
        if ward_room:
            try:
                callsign = context.get("callsign", "") or _ctx(context, "callsign")
                thread_id = _ctx(context, "thread_id")
                if callsign and thread_id:
                    posts = await ward_room.get_posts_by_author(
                        callsign, limit=3, thread_id=thread_id,
                    )
                    if posts and len(posts) >= 2:
                        from probos.cognitive.similarity import jaccard_similarity, text_to_words
                        word_sets = [text_to_words(p["body"]) for p in posts]
                        total_sim = 0.0
                        pair_count = 0
                        for j in range(len(word_sets)):
                            for k in range(j + 1, len(word_sets)):
                                total_sim += jaccard_similarity(word_sets[j], word_sets[k])
                                pair_count += 1
                        if pair_count > 0:
                            avg_sim = total_sim / pair_count
                            if avg_sim >= 0.4:
                                result_parts.append(
                                    f"WARNING: Your last {len(posts)} messages in this thread "
                                    f"show {avg_sim:.0%} self-similarity. You may be repeating "
                                    "yourself. If you and the other person agree, conclude the "
                                    "conversation naturally. Do NOT restate conclusions you've "
                                    "already communicated. If there's nothing new to add, "
                                    "respond with exactly: [NO_RESPONSE]"
                                )
            except Exception:
                logger.debug("AD-646b: DM self-monitoring query failed", exc_info=True)

    return {"self_monitoring": "\n".join(result_parts) if result_parts else ""}


async def _query_introspective_telemetry(
    runtime: Any, spec: SubTaskSpec, context: dict,
) -> dict:
    """AD-646b: Introspective telemetry for self-referential ward room threads.

    Only fires when the thread content matches introspective patterns (AD-588).
    Returns rendered telemetry text or empty string.
    """
    title = _ctx(context, "title")
    text = _ctx(context, "text")
    thread_text = f"{title} {text}".strip()

    if not thread_text:
        return {"introspective_telemetry": ""}

    from probos.cognitive.cognitive_agent import CognitiveAgent
    if not CognitiveAgent._is_introspective_query(thread_text):
        return {"introspective_telemetry": ""}

    telemetry_svc = getattr(runtime, '_introspective_telemetry', None)
    if not telemetry_svc:
        return {"introspective_telemetry": ""}

    try:
        agent_id = context.get("_agent_id", "") or _ctx(context, "agent_id")
        sovereign_id = context.get("sovereign_id", "") or agent_id
        snapshot = await telemetry_svc.get_full_snapshot(sovereign_id)
        rendered = telemetry_svc.render_telemetry_context(snapshot)
        return {"introspective_telemetry": rendered or ""}
    except Exception:
        logger.debug("AD-646b: introspective telemetry query failed", exc_info=True)
        return {"introspective_telemetry": ""}


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
    "self_monitoring": _query_self_monitoring,                   # AD-646b
    "introspective_telemetry": _query_introspective_telemetry,  # AD-646b
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
