"""BF-961 (#1774): reading a bundled agent's stored list without reading a failure as an empty list.

TodoAgent and SchedulerAgent show the model the list stored in a file and write back the list it builds, so a read that
failed must never read as "no list". ``read_stored_list`` says which of three things a ``read_file`` broadcast told;
``UnreadableListGuard`` ends the intent before the model, and so before any write, when the read failed (the shape of
BF-769 and BF-772, ``web_agents._FetchGatedMixin``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from probos.agents.file_reader import is_file_not_found
from probos.types import IntentMessage

logger = logging.getLogger(__name__)

#: The observation key ``perceive`` sets, to the text the user is answered with, when the stored list could not be read.
UNREADABLE_KEY = "stored_list_unreadable"


class ReadStatus(str, Enum):
    FOUND = "found"  # a reader returned the file's text, which may be empty: the file exists
    MISSING = "missing"  # every answer is the reader's "no such file": nothing is stored yet
    FAILED = "failed"  # nobody answered, or an answer was a refusal or an error: what is stored is not known


@dataclass(frozen=True)
class ListRead:
    status: ReadStatus
    text: str = ""  # the file's text; empty unless FOUND
    reason: str = ""  # why, for the log; set when FAILED


async def read_stored_list(runtime: Any, path: str) -> ListRead:
    """Broadcast ``read_file`` for *path* and say what the answers told.

    The first success with text is the text (as before). Failing that, a success with no text is an existing empty file;
    answers that are all the reader's "no such file" are a file that is not there yet; anything else, including no answer
    at all, is a failure and is logged at WARNING.
    """
    bus = getattr(runtime, "intent_bus", None)
    if bus is None:
        return _failed(path, "the runtime has no intent bus")
    answers = await bus.broadcast(IntentMessage(intent="read_file", params={"path": path}))
    empty = False
    missing = 0
    reason = "no reader answered"
    for r in answers:
        if r.success:
            content = r.result
            if isinstance(content, dict):
                content = content.get("content", content.get("data", str(content)))
            if content:
                return ListRead(ReadStatus.FOUND, str(content))
            if content is None:
                reason = "a reader answered success with no content"
            else:
                empty = True
        elif is_file_not_found(r.error):
            missing += 1
        else:
            reason = f"a reader answered: {str(r.error)[:200]}"
    if empty:
        return ListRead(ReadStatus.FOUND)
    if answers and missing == len(answers):
        return ListRead(ReadStatus.MISSING)
    return _failed(path, reason)


def _failed(path: str, reason: str) -> ListRead:
    logger.warning("BF-961: %s could not be read (%s)", path, reason)
    return ListRead(ReadStatus.FAILED, reason=reason)


class UnreadableListGuard:
    """Mixin, ahead of ``CognitiveAgent`` in the bases: an agent whose ``perceive`` could not read its stored list answers
    so and does nothing else, so that no list the model builds is written over what is stored."""

    async def _stored_list(self, obs: dict, path: str, what: str) -> str | None:
        """The stored text ("" when there is none yet), or None after marking *obs* so that ``decide`` ends the intent."""
        read = await read_stored_list(self._runtime, path)
        if read.status is ReadStatus.FAILED:
            obs[UNREADABLE_KEY] = f"Could not read {what}; nothing was changed or saved."
            return None
        return read.text

    async def decide(self, observation: dict) -> dict:
        # No model call: ``act`` answers success False with this text, as it does for a failed model call.
        refusal = observation.get(UNREADABLE_KEY)
        if refusal:
            return {"action": "error", "reason": refusal}
        return await super().decide(observation)  # type: ignore[misc]
