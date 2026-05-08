"""AD-641g: NATS subject schema for cognitive chain step lifecycle.

Pure helpers — no external imports beyond ``SubTaskType``. The transport
foundation for the async cognitive pipeline. See AD-641g v1 prompt.
"""
from __future__ import annotations

from probos.cognitive.sub_task import SubTaskType

# JetStream stream that holds chain step lifecycle messages
CHAIN_STREAM = "COGNITIVE_CHAIN"

# Subject template: chain.{agent_id}.{step}.{phase}
# phase ∈ {"start", "complete", "error"}
CHAIN_SUBJECT_PREFIX = "chain"


def _safe_token(value: str) -> str:
    """Sanitize an agent_id into a NATS-token-safe string.

    NATS subject tokens allow [A-Za-z0-9_-]. Dots are token separators.
    Anything else (colons, spaces, slashes) becomes underscore. Mirrors the
    ``_NATS_UNSAFE_CHAR`` regex used by ``probos.mesh.nats_bus``.
    """
    if not value:
        return "_"
    out = []
    for ch in value:
        if ch.isalnum() or ch in "_-":
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def chain_subject(
    agent_id: str,
    step: SubTaskType | str,
    phase: str = "complete",
) -> str:
    """Build a chain-step lifecycle subject.

    >>> chain_subject("alice", SubTaskType.ANALYZE)
    'chain.alice.analyze.complete'
    >>> chain_subject("agent:42", "compose", "error")
    'chain.agent_42.compose.error'
    """
    step_str = step.value if isinstance(step, SubTaskType) else str(step)
    safe_phase = _safe_token(phase) or "complete"
    return f"{CHAIN_SUBJECT_PREFIX}.{_safe_token(agent_id)}.{_safe_token(step_str)}.{safe_phase}"


def chain_wildcard(agent_id: str = "*", step: str = "*") -> str:
    """Wildcard subject for subscribers.

    Use ``*`` for a single token wildcard or ``>`` to match the remainder.

    >>> chain_wildcard()
    'chain.*.*.>'
    >>> chain_wildcard("alice")
    'chain.alice.*.>'
    """
    return f"{CHAIN_SUBJECT_PREFIX}.{agent_id}.{step}.>"


def chain_stream_subjects() -> list[str]:
    """Subjects covered by the COGNITIVE_CHAIN JetStream stream."""
    return [f"{CHAIN_SUBJECT_PREFIX}.>"]
