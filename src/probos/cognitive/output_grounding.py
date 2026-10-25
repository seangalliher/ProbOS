"""BF-922 (#1639): the deterministic output checks, shared by the chain's EVALUATE and the single-call fallback.

BF-191 rejects raw intent JSON. BF-204 rejects a reply that cites at least two distinct hex
identifiers that were not in what the replying call was given from outside the model's own
output: on the chain, the world sections of the COMPOSE prompt
(``sub_tasks.compose.composer_world_text``; a failed Ward Room lookup's echo of the reference
ANALYZE chose is not one); on the single-call fallback, the text that call sent (the request's
system prompt and user prompt, and any per-tier suffix the answering attempt appended); on
both, the intent's own ids (BF-233, :func:`intent_entity_ids`).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: A cited identifier: a whole word of six or more hex characters with at least one letter a-f.
#: Pure-decimal numbers (counts, timestamps, ports) are not identifiers (BF-922).
_CITED_ID = re.compile(r"\b(?=[0-9]*[a-f])[0-9a-f]{6,}\b")

#: A run of six or more hex characters anywhere in given text. An id cited inside a run was
#: given, exactly as ``id in text`` held for BF-204 before BF-922.
_GIVEN_RUN = re.compile(r"[0-9a-f]{6,}")

#: BF-204's threshold, counted over distinct ids (BF-922).
MIN_UNGROUNDED_IDS = 2

#: How many ungrounded ids the BF-204 log line names (it named 3 before BF-922).
LOGGED_UNGROUNDED_IDS = 8

REJECTION_RAW_JSON = "raw_json_output"
REJECTION_UNGROUNDED = "confabulation_detected"

#: The gates, as the log lines and the CONFABULATION_SUPPRESSED payload name them.
PATH_CHAIN = "chain"
PATH_FALLBACK = "single_call_fallback"


@dataclass(frozen=True)
class OutputRejection:
    """Why a deterministic check rejected an output."""

    reason: str
    criteria: dict[str, Any]
    ungrounded: tuple[str, ...] = ()

    def as_evaluate_result(self) -> dict[str, Any]:
        """The EVALUATE result BF-191 and BF-204 have always returned."""
        return {
            "pass": False,
            "score": 0.0,
            "criteria": dict(self.criteria),
            "recommendation": "suppress",
            "rejection_reason": self.reason,
        }


def shown_hex_runs(*texts: str) -> tuple[str, ...]:
    """The distinct lowercase runs of six or more hex characters in ``texts``, in order."""
    runs: dict[str, None] = {}
    for text in texts:
        for run in _GIVEN_RUN.findall((text or "").lower()):
            runs[run] = None
    return tuple(runs)


def cited_ids(output: str) -> tuple[str, ...]:
    """The distinct identifiers ``output`` cites, lowercase, in order of first citation."""
    return tuple(dict.fromkeys(_CITED_ID.findall((output or "").lower())))


def ungrounded_ids(output: str, shown: Iterable[str]) -> tuple[str, ...]:
    """The identifiers ``output`` cites that occur in no given hex run."""
    shown_text = " ".join(shown)
    return tuple(cited for cited in cited_ids(output) if cited not in shown_text)


def intent_entity_ids(context: dict[str, Any]) -> tuple[str, ...]:
    """BF-233's ids: the intent's thread, channel and author, the agent, its target and the intent."""
    ids: list[str] = []
    params = context.get("params", {})
    if isinstance(params, dict):
        for key in ("thread_id", "channel_id", "author_id"):
            value = params.get(key, "")
            if value:
                ids.append(str(value))
    for key in ("_agent_id", "target_agent_id", "intent_id"):
        value = context.get(key)
        if value:
            ids.append(str(value))
    return tuple(ids)


def is_raw_intent_json(output: str) -> bool:
    """BF-191: the output is raw intent JSON, not natural language."""
    stripped = (output or "").strip()
    return stripped.startswith("{") and ('"intents"' in stripped[:200] or '"intent"' in stripped[:200])


def deterministic_rejection(output: str, shown: Iterable[str]) -> OutputRejection | None:
    """BF-191, then BF-204. ``None`` when ``output`` passes both."""
    if is_raw_intent_json(output):
        return OutputRejection(
            reason=REJECTION_RAW_JSON,
            criteria={"format": {"pass": False, "reason": "Raw JSON instead of natural language"}},
        )
    ungrounded = ungrounded_ids(output, shown)
    if len(ungrounded) >= MIN_UNGROUNDED_IDS:
        return OutputRejection(
            reason=REJECTION_UNGROUNDED,
            criteria={
                "grounding": {"pass": False, "reason": f"Ungrounded identifiers: {list(ungrounded[:3])}"},
            },
            ungrounded=ungrounded,
        )
    return None


def log_rejection(
    rejection: OutputRejection,
    output: str,
    *,
    agent_type: str,
    agent_id: str,
    callsign: str,
    path: str,
) -> None:
    """The BF-191 and BF-204 lines, naming the agent and the gate (BF-922)."""
    if rejection.reason == REJECTION_RAW_JSON:
        logger.warning(
            "BF-191: Evaluate rejected raw intent JSON from %s (agent_id=%s, callsign=%s, path=%s; %d chars)",
            agent_type, agent_id, callsign, path, len(output or ""),
        )
        return
    logger.warning(
        "BF-204: Grounding check failed for %s (agent_id=%s, callsign=%s, path=%s) — %d ungrounded hex IDs: %s",
        agent_type, agent_id, callsign, path,
        len(rejection.ungrounded), list(rejection.ungrounded[:LOGGED_UNGROUNDED_IDS]),
    )
