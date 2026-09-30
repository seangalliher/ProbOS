"""AD-1156: the persisted plan/execute mode record for a chat thread.

A conversation's mode is a fact the thread owns, like its personality override
(AD-809): it is stored on the thread, survives a restart, and is read at the
start of every agent turn. It lives in the thread's JSON ``metadata`` under
:data:`AGENT_MODE_METADATA_KEY` and is written only by
:meth:`probos.threads.ChatThreadStore.set_agent_mode`. The REST layer has no
generic metadata write (``PATCH /api/threads/{id}`` accepts two scoped flags and
``POST /api/threads`` accepts no metadata at all), so the Captain's ``/mode``
command is the one way a record comes into existence.

This module is the schema: pure, no I/O. A record is validated exactly -- key
set and types -- on every read, because a record that does not parse has to be
treated as unknown rather than guessed at. The consumer holds an unknown record
in plan mode (``probos.cognitive.agent_mode``), which is the fail-closed
direction: plan mode only ever withholds tools.

``revision`` increases by one on every transition and is never reused while the
record is readable, so a later slice can bind an approval to the revision the
Captain was looking at. A record that cannot be read is replaced at revision 1, as
is a record set for another agent (below): a reader that has seen no record of its
agent's takes revision 1 as that agent's first (``plan_mode_governed_turn``).

A record names the agent it was set for (``agent_id``, A-8): the agent ``/mode``
addressed, which the writer checks is the thread's one participant. It governs only
while that agent is still the thread's one participant, so an approval given to one
agent never passes to another that takes its place.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

AGENT_MODE_METADATA_KEY = "agent_mode"
AGENT_MODE_PLAN = "plan"
AGENT_MODE_EXECUTE = "execute"
AGENT_MODES: frozenset[str] = frozenset({AGENT_MODE_PLAN, AGENT_MODE_EXECUTE})

_RECORD_KEYS: frozenset[str] = frozenset(
    {"mode", "revision", "changed_at", "changed_by", "previous", "agent_id"}
)
_MAX_CHANGED_BY_CHARS = 128
# An agent id, bounded as the thread store bounds a crew-session participant's id.
_MAX_AGENT_ID_CHARS = 128


class AgentModeRecordError(ValueError):
    """A mode record that does not match the schema exactly."""


class AgentModeNotOneToOneError(ValueError):
    """A-6: the thread does not have exactly one participant, or, when the caller names
    the agent it addressed, when that one participant is another agent (A-7), so no mode
    is set on it.

    :meth:`probos.threads.ChatThreadStore.set_agent_mode` checks the participants inside
    its transaction, so a thread that gained or lost one after the caller read it is
    refused there, and nothing is written.
    """


@dataclass(frozen=True)
class AgentModeRecord:
    """One conversation's current mode and how it got there.

    ``previous`` is the mode this record replaced: ``None`` exactly when this is
    its agent's first record on the thread (``revision == 1``), and never equal to
    ``mode``, because a record is only written when the mode changes. ``agent_id`` is
    the agent it was set for (A-8).
    """

    mode: str
    revision: int
    changed_at: float
    changed_by: str
    previous: str | None
    agent_id: str

    def __post_init__(self) -> None:
        if type(self.mode) is not str or self.mode not in AGENT_MODES:
            raise AgentModeRecordError("agent_mode_record_mode")
        if type(self.revision) is not int or self.revision < 1:
            raise AgentModeRecordError("agent_mode_record_revision")
        if (
            type(self.changed_at) is not float
            or not math.isfinite(self.changed_at)
            or self.changed_at < 0.0
        ):
            raise AgentModeRecordError("agent_mode_record_changed_at")
        if (
            type(self.changed_by) is not str
            or not self.changed_by.strip()
            or len(self.changed_by) > _MAX_CHANGED_BY_CHARS
        ):
            raise AgentModeRecordError("agent_mode_record_changed_by")
        if self.previous is not None and (
            type(self.previous) is not str
            or self.previous not in AGENT_MODES
            or self.previous == self.mode
        ):
            raise AgentModeRecordError("agent_mode_record_previous")
        if (self.revision == 1) != (self.previous is None):
            raise AgentModeRecordError("agent_mode_record_history")
        if (
            type(self.agent_id) is not str
            or not self.agent_id.strip()
            or len(self.agent_id) > _MAX_AGENT_ID_CHARS
        ):
            raise AgentModeRecordError("agent_mode_record_agent_id")

    def to_dict(self) -> dict[str, Any]:
        """The JSON shape stored under :data:`AGENT_MODE_METADATA_KEY`."""
        return {
            "mode": self.mode,
            "revision": self.revision,
            "changed_at": self.changed_at,
            "changed_by": self.changed_by,
            "previous": self.previous,
            "agent_id": self.agent_id,
        }


@dataclass(frozen=True)
class AgentModeTransition:
    """The outcome of one ``set_agent_mode`` call.

    ``changed`` is False when the thread was already in the requested mode; the
    record is then the existing one and nothing was written.
    """

    record: AgentModeRecord
    changed: bool


def parse_agent_mode_record(value: object) -> AgentModeRecord:
    """Validate a stored record exactly, or raise :class:`AgentModeRecordError`."""
    if type(value) is not dict or set(value) != _RECORD_KEYS:
        raise AgentModeRecordError("agent_mode_record_shape")
    return AgentModeRecord(
        mode=value["mode"],
        revision=value["revision"],
        changed_at=value["changed_at"],
        changed_by=value["changed_by"],
        previous=value["previous"],
        agent_id=value["agent_id"],
    )


def advance_agent_mode(
    current: AgentModeRecord | None,
    mode: str,
    *,
    changed_by: str,
    changed_at: float,
    agent_id: str,
) -> AgentModeTransition:
    """The transition that moves ``current`` to ``mode`` for ``agent_id``.

    Already in ``mode``: ``current`` is returned unchanged with ``changed=False``.
    Raises :class:`AgentModeRecordError` for an unknown ``mode`` or an invalid
    ``changed_by`` or ``agent_id``: all are caller errors, and a bad record must never
    be built. A ``current`` record set for another agent is not this agent's to
    continue (A-8): the new record starts at revision 1, with no previous mode.
    """
    if current is not None and current.agent_id != agent_id:
        current = None
    if current is not None and current.mode == mode:
        return AgentModeTransition(record=current, changed=False)
    record = AgentModeRecord(
        mode=mode,
        revision=1 if current is None else current.revision + 1,
        changed_at=float(changed_at),
        changed_by=changed_by,
        previous=None if current is None else current.mode,
        agent_id=agent_id,
    )
    return AgentModeTransition(record=record, changed=True)
