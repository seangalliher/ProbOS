"""AD-1229 (#1202): message_receipts -- what became of a direct message an agent sent.

The Counselor asked on #1202 (2026-08-10): "did this reach anyone, and did anything
come back". Increment 1 answers that and nothing more: "No causal surface, no
correlational view, no windowing. Delivery and engagement facts only."

The rule: report *facts the Ward Room stores, never what a message achieved*. Every
value is a closed code, a registry label, a count or a UTC time; ``MessageReceipt``
refuses anything else, so no receipt can say a message worked, helped or landed.

* ``read`` is always ``not_recorded``: the Ward Room keeps no read record for a DM
  channel, so a message with no reply may or may not have been seen.
* No id and no channel name is rendered: a quoted uuid reads as an AD-1119
  referent that no room can resolve.
* Scope: DM threads authored under the caller's own registry id -- crew DMs,
  therapeutic DMs and DMs to the Captain. Not the AD-536/537 promotion and teaching
  DMs (authored as an agent type), group chats, public threads or notifications.
* An empty answer means nothing is stored: a send dropped before storage left no
  row, so this never reports "not sent".
* Read-only and ownership-scoped: it writes nothing, and an empty identity is not
  a wildcard.
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any, Callable, Collection, Iterable, Protocol

from probos.tools.protocol import ToolResult, ToolType, refuse_undeclared_params
from probos.ward_room.channels import CAPTAIN_DM_KEY, captain_dm_channel_name, dm_channel_keys, dm_channel_name
from probos.ward_room.receipt_facts import MAX_CHANNEL_NAMES, DmFactsPage, DmThreadFacts

logger = logging.getLogger(__name__)

# ── The closed vocabulary: the single source for code, schema text and tests ──
CREW_DM = "crew_dm"
CAPTAIN_DM = "captain_dm"
OTHER_DM = "other_dm"
EXACT = "exact"
CAPTAIN_CHANNEL = "captain_channel"
SHARED_KEY = "shared_key"
UNREGISTERED_KEY = "unregistered_key"
UNRECOGNISED_CHANNEL = "unrecognised_channel"
UNCONFIRMED = "unconfirmed"  # a registered agent holds the key, but the thread names none of them
RECIPIENT_BASES = frozenset({EXACT, CAPTAIN_CHANNEL, SHARED_KEY, UNCONFIRMED, UNREGISTERED_KEY, UNRECOGNISED_CHANNEL})
NAMED_BASES = frozenset({EXACT, CAPTAIN_CHANNEL})  # the only bases that prove who the recipient is
UNCONFIRMED_BASES = frozenset({SHARED_KEY, UNCONFIRMED})  # may or may not be to a filtered recipient
DELIVERED = "delivered"
NO_REGISTERED_RECIPIENT = "no_registered_recipient"
UNKNOWN = "unknown"
DELIVERY_FOR_BASIS = {
    EXACT: DELIVERED, CAPTAIN_CHANNEL: DELIVERED, SHARED_KEY: UNKNOWN, UNCONFIRMED: UNKNOWN,
    UNREGISTERED_KEY: NO_REGISTERED_RECIPIENT, UNRECOGNISED_CHANNEL: UNKNOWN,
}
CHANNEL_FOR_BASIS = {
    EXACT: CREW_DM, SHARED_KEY: CREW_DM, UNCONFIRMED: CREW_DM, UNREGISTERED_KEY: CREW_DM,
    CAPTAIN_CHANNEL: CAPTAIN_DM, UNRECOGNISED_CHANNEL: OTHER_DM,
}
READ_NOT_RECORDED = "not_recorded"
REPLIED = "replied"
NO_REPLY_YET = "no_reply_yet"
REPLY_CODES = frozenset({REPLIED, NO_REPLY_YET, UNKNOWN})
CAPTAIN_AUTHOR_ID = "captain"  # the id the Captain posts under (routers/wardroom.py:25)
SYSTEM_AUTHOR_IDS = frozenset({"system"})  # system posts are not replies (ward_room_router.py:263)
CAPTAIN_LABEL = "Captain"
UNREGISTERED_LABEL = "unregistered"
CREW_MEMBER_LABEL = "crew member"
LABEL_RE = re.compile(r"[A-Za-z][A-Za-z0-9 .'_-]{0,47}")

# Bounds (DP-13a: each ceiling states its cost).
MAX_REPLIED_BY = 5  # names "who else replied" in a DM; cost: a busier thread lists only its first five
WINDOW_DEFAULT_HOURS = 24  # one day, about when a DM is archived; cost: an older one needs since_hours
# Default retention prunes inactive threads after 7 days, so a longer window would promise facts
# the store may no longer hold; cost: an older message is not reported even where retention is longer.
WINDOW_MAX_HOURS = 168
LIMIT_DEFAULT = 10  # ten receipts are about 3,650 characters; cost: an eleventh needs a larger limit
# A receipt renders in about 365 characters, so 20 is a page, not a flood; cost: a busy agent
# narrows by recipient or since_hours, and truncated tells it to.
LIMIT_MAX = 20
TIME_FORMAT = "%Y-%m-%d %H:%M:%S UTC"

# ── Every model-facing string (scanned by T7) ──
DESCRIPTION = (
    "Check what became of direct messages you sent: whether each one was delivered to its recipient's DM "
    "channel, and whether the recipient has written back. Use it before following up on a message or saying "
    "you heard nothing, instead of judging from memory. It lists your own direct messages from the last 24 "
    "hours by default (at most 168), newest first; pass recipient -- a callsign, or \"captain\" -- to see only "
    "your messages to them, with unconfirmed counting the ones in their DM channel that do not show who they "
    "were sent to. Each entry gives when you sent it, whether it was delivered, how often and when "
    "the recipient replied in that thread, whether they wrote elsewhere in the same DM channel afterwards, "
    "who else replied, and whether the Ward Room has archived the thread (it archives direct messages after "
    "about a day, and then stops offering them as new). An entry names its recipient only when the stored "
    "message shows who it was sent to; otherwise to is null and delivery is unknown. The Ward Room keeps no "
    "record of reading, so read is "
    "always not_recorded: a message with no reply may or may not have been seen. Entries report what the "
    "Ward Room stores, never message text. Read-only: it changes nothing."
)
PARAM_RECIPIENT = (
    "Only your messages to this crew member (their callsign) or to the Captain "
    "(\"captain\"). Omit it for all of your recent direct messages."
)
PARAM_SINCE_HOURS = "How far back to look, in whole hours from 1 to 168. Default 24."
PARAM_LIMIT = "The most entries to return, from 1 to 20. Default 10."
R_IDENTITY = "the caller's identity is unknown, so there are no messages to report"
R_WARD_ROOM = "the Ward Room is not running on this ship, so no messages are stored"
# Never formatted with caller input: an echo reaches the model as a referent or a gap phrase.
R_RECIPIENT = "no crew member answers to that callsign"
R_NOT_ABOARD = "no crew member with that callsign is registered aboard, so there is no DM channel to look in"
R_SELF = "that is your own callsign; there are no direct messages to yourself"
R_WHOLE = "{name} must be a whole number"
R_FAULT = "the message records could not be read just now"
NOTE_EMPTY = "No direct message from you{to_part} in the last {hours} hours is stored in the Ward Room."
NOTE_UNCONFIRMED = (
    "No direct message from you{to_part} in the last {hours} hours is confirmed in the Ward Room, though "
    "other messages are stored in that DM channel (see unconfirmed and truncated)."
)


# ── Narrow dependencies (exact signatures) ──
class _DmFactsSource(Protocol):
    @property
    def is_started(self) -> bool: ...
    async def dm_receipt_facts(
        self, author_id: str, *, since: float, limit: int, channel_names: tuple[str, ...] = (),
    ) -> DmFactsPage: ...


class _AgentDirectory(Protocol):
    def get(self, agent_id: str) -> Any: ...
    def all(self) -> list[Any]: ...


class _CallsignDirectory(Protocol):
    def resolve(self, callsign: str) -> dict[str, Any] | None: ...
    def get_callsign(self, agent_type: str) -> str: ...


@dataclass(frozen=True)
class RecipientResolution:
    basis: str
    holder_ids: tuple[str, ...]


def classify_dm_recipient(
    channel_name: str, sender_id: str, registered_ids: Iterable[str], addressed_ids: Collection[str] = frozenset(),
) -> RecipientResolution:
    """Who a DM channel name and its title prove the recipient is -- never a guess (the Q3 rule, A-3).

    The recipient holds the key that is not the sender's and is the one such holder the thread's title
    addressed (``addressed_ids``); a ``captain`` key counts only beside the sender's own.
    """
    keys = dm_channel_keys(channel_name)
    if keys is None or not sender_id:
        return RecipientResolution(UNRECOGNISED_CHANNEL, ())
    own = sender_id[:8]
    first, second = keys
    if CAPTAIN_DM_KEY in keys:
        other = second if first == CAPTAIN_DM_KEY else first
        return RecipientResolution(CAPTAIN_CHANNEL if other == own else UNRECOGNISED_CHANNEL, ())
    if own not in keys:
        return RecipientResolution(UNRECOGNISED_CHANNEL, ())
    other = second if first == own else first
    holders = tuple(sorted(i for i in registered_ids if i[:8] == other and i != sender_id))
    if not holders:
        return RecipientResolution(UNREGISTERED_KEY, ())
    proven = tuple(i for i in holders if i in addressed_ids)
    if len(proven) == 1:
        return RecipientResolution(EXACT, proven)
    return RecipientResolution(SHARED_KEY if len(proven) > 1 else UNCONFIRMED, holders)


def addressee_ids(token: str | None, everyone: list[Any], callsigns: _CallsignDirectory | None) -> frozenset[str]:
    """Every registered agent of the type a title's addressed callsign resolves to; empty when it resolves to none."""
    resolved = callsigns.resolve(token) if token and callsigns is not None else None
    agent_type = resolved.get("agent_type") if resolved else None
    return frozenset(a.id for a in everyone if agent_type and a.agent_type == agent_type)


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _utc(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).strftime(TIME_FORMAT)


def _is_label(value: Any) -> bool:
    """The one guard for model-facing labels: a bounded name that reads as neither a gap claim nor a referent."""
    from probos.cognitive.decomposer import is_capability_gap
    from probos.cognitive.referent_gate import extract_referents

    if not (isinstance(value, str) and LABEL_RE.fullmatch(value)):
        return False
    return not is_capability_gap(value) and not extract_referents(value)


@dataclass(frozen=True)
class MessageReceipt:
    """One DM the agent sent, as the Ward Room stores it. The constructor refuses anything else."""

    to: str | None
    channel: str
    sent_at: float
    delivery: str
    recipient_basis: str
    archived: bool
    reply: str
    recipient_replies: int | None
    first_reply_at: float | None
    last_reply_at: float | None
    later_in_channel: bool | None
    replied_by: tuple[str, ...]
    read: str = READ_NOT_RECORDED

    def __post_init__(self) -> None:
        if self.to is not None and not _is_label(self.to):
            raise ValueError("AD-1229: receipt 'to' must be a registry label or None")
        if self.recipient_basis not in RECIPIENT_BASES:
            raise ValueError("AD-1229: unknown recipient basis")
        if self.to is not None and self.recipient_basis not in NAMED_BASES:
            raise ValueError("AD-1229: only an exact or Captain-channel basis names a recipient")
        if self.channel != CHANNEL_FOR_BASIS[self.recipient_basis]:
            raise ValueError("AD-1229: the channel kind does not follow from the recipient basis")
        if self.delivery != DELIVERY_FOR_BASIS[self.recipient_basis]:
            raise ValueError("AD-1229: delivery does not follow from the recipient basis")
        if not _finite(self.sent_at):
            raise ValueError("AD-1229: sent_at must be a finite timestamp")
        if not isinstance(self.archived, bool):
            raise ValueError("AD-1229: archived must be a bool")
        if self.read != READ_NOT_RECORDED:
            raise ValueError("AD-1229: the Ward Room keeps no read record, so read must be not_recorded")
        if self.reply not in REPLY_CODES:
            raise ValueError("AD-1229: unknown reply code")
        known = self.to is not None
        if known != (self.reply != UNKNOWN):
            raise ValueError("AD-1229: reply is unknown exactly when the recipient is")
        replies = self.recipient_replies
        if known:
            if isinstance(replies, bool) or not isinstance(replies, int) or replies < 0:
                raise ValueError("AD-1229: recipient_replies must be a non-negative int")
            if (self.reply == REPLIED) != (replies > 0):
                raise ValueError("AD-1229: replied means the recipient posted in this thread")
            if not isinstance(self.later_in_channel, bool):
                raise ValueError("AD-1229: later_in_channel must be a bool when the recipient is known")
        elif replies is not None or self.later_in_channel is not None:
            raise ValueError("AD-1229: recipient facts need a known recipient")
        first, last = self.first_reply_at, self.last_reply_at
        if (replies or 0) > 0:
            if not (_finite(first) and _finite(last)) or first > last:
                raise ValueError("AD-1229: reply times must be finite and ordered")
        elif (first, last) != (None, None):
            raise ValueError("AD-1229: reply times need a reply")
        by = self.replied_by
        if not (isinstance(by, tuple) and len(by) <= MAX_REPLIED_BY and len(set(by)) == len(by) and all(map(_is_label, by))):
            raise ValueError("AD-1229: replied_by must be at most five distinct labels")

    def to_output(self) -> dict[str, Any]:
        """The receipt's keys in declared order: times as UTC text, ``replied_by`` as a list."""
        out = {f.name: getattr(self, f.name) for f in fields(self)}
        for key in ("sent_at", "first_reply_at", "last_reply_at"):
            out[key] = _utc(out[key])
        out["replied_by"] = list(self.replied_by)
        return out


def label_for(author_id: str, agents: _AgentDirectory, callsigns: _CallsignDirectory | None) -> str:
    """A registry label for an author: the Captain, a callsign, the agent type, or a fixed fallback."""
    if author_id == CAPTAIN_AUTHOR_ID:
        return CAPTAIN_LABEL
    agent = agents.get(author_id)
    if agent is None:
        return UNREGISTERED_LABEL
    agent_type = str(getattr(agent, "agent_type", "") or "")
    text = (callsigns.get_callsign(agent_type) if callsigns is not None else "") or agent_type
    return text if _is_label(text) else CREW_MEMBER_LABEL


def build_receipt(
    fact: DmThreadFacts, resolution: RecipientResolution, *,
    agents: _AgentDirectory, callsigns: _CallsignDirectory | None,
) -> MessageReceipt:
    """The receipt one stored DM thread supports under ``resolution``; the recipient is named only when proven."""
    basis = resolution.basis
    to: str | None = None
    recipient_ids: frozenset[str] = frozenset()
    if basis == CAPTAIN_CHANNEL:
        to, recipient_ids = CAPTAIN_LABEL, frozenset({CAPTAIN_AUTHOR_ID})
    elif basis == EXACT:
        to = label_for(resolution.holder_ids[0], agents, callsigns)
        recipient_ids = frozenset(resolution.holder_ids)
    in_thread = tuple(a for a in fact.in_thread if a.author_id not in SYSTEM_AUTHOR_IDS)
    ordered = sorted(in_thread, key=lambda a: a.first_at)
    replied_by = tuple(dict.fromkeys(label_for(a.author_id, agents, callsigns) for a in ordered))[:MAX_REPLIED_BY]
    common: dict[str, Any] = {"channel": CHANNEL_FOR_BASIS[basis], "sent_at": fact.created_at,
                              "delivery": DELIVERY_FOR_BASIS[basis], "recipient_basis": basis,
                              "archived": bool(fact.archived), "replied_by": replied_by}
    if to is None:
        return MessageReceipt(
            to=None, reply=UNKNOWN, recipient_replies=None, first_reply_at=None, last_reply_at=None,
            later_in_channel=None, **common,
        )
    mine = [a for a in in_thread if a.author_id in recipient_ids]
    recipient_posts = sum(a.count for a in in_thread if a.author_id in recipient_ids)
    later = any(a.author_id in recipient_ids for a in fact.later_in_channel)
    return MessageReceipt(
        to=to, reply=REPLIED if recipient_posts > 0 else NO_REPLY_YET, recipient_replies=recipient_posts,
        first_reply_at=min((a.first_at for a in mine), default=None),
        last_reply_at=max((a.last_at for a in mine), default=None), later_in_channel=later, **common,
    )


class MessageReceiptsTool:
    """AD-1229: the asking agent's own direct messages -- delivered, and whether the recipient wrote back.

    The AD-423a ``Tool`` protocol (duck-typed); ``invoke`` never raises except ``CancelledError``.
    """

    def __init__(self, *, runtime: Any, clock: Callable[[], float] = time.time) -> None:
        self._runtime = runtime
        self._clock = clock  # wall time, because Ward Room created_at is wall time (never monotonic)

    @property
    def tool_id(self) -> str:
        return "message_receipts"

    @property
    def name(self) -> str:
        return "Message Receipts"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return DESCRIPTION

    @property
    def input_schema(self) -> dict[str, Any]:
        window = {"minimum": 1, "maximum": WINDOW_MAX_HOURS, "default": WINDOW_DEFAULT_HOURS}
        entries = {"minimum": 1, "maximum": LIMIT_MAX, "default": LIMIT_DEFAULT}
        return {
            "type": "object",
            "properties": {
                "recipient": {"type": "string", "description": PARAM_RECIPIENT},
                "since_hours": {"type": "integer", **window, "description": PARAM_SINCE_HOURS},
                "limit": {"type": "integer", **entries, "description": PARAM_LIMIT},
            },
            "required": [],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        t0 = time.monotonic()

        def _done(output: dict[str, Any]) -> ToolResult:
            return ToolResult(output=output, error=None, duration_ms=(time.monotonic() - t0) * 1000.0)

        def _refuse(reason: str) -> ToolResult:
            return _done({"messages": [], "count": 0, "reason": reason})

        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        values = params if isinstance(params, dict) else {}
        agent_id = str((context or {}).get("agent_id") or "")
        if not agent_id:
            return _refuse(R_IDENTITY)
        hours, bad_hours = self._whole(values.get("since_hours"), WINDOW_DEFAULT_HOURS, "since_hours")
        limit, bad_limit = self._whole(values.get("limit"), LIMIT_DEFAULT, "limit")
        problem = bad_hours or bad_limit
        if problem is not None:
            return _refuse(problem)
        hours = min(max(hours, 1), WINDOW_MAX_HOURS)
        limit = min(max(limit, 1), LIMIT_MAX)
        ward_room: _DmFactsSource | None = getattr(self._runtime, "ward_room", None)
        if ward_room is None or getattr(ward_room, "is_started", False) is not True:
            return _refuse(R_WARD_ROOM)
        agents: _AgentDirectory | None = getattr(self._runtime, "registry", None)
        if agents is None:
            logger.warning(
                "AD-1229: the runtime has no agent registry, so DM recipients for agent %s cannot be "
                "named; the agent gets an honest could-not-read answer and the turn continues", agent_id,
            )
            return _refuse(R_FAULT)
        callsigns: _CallsignDirectory | None = getattr(self._runtime, "callsign_registry", None)
        everyone = list(agents.all())
        registered = tuple(a.id for a in everyone)
        names, to_part, filtered_ids, refused = self._recipient_channels(
            values.get("recipient"), agent_id, everyone, callsigns,
        )
        if refused is not None:
            return _refuse(refused)
        since = self._clock() - hours * 3600
        messages: list[dict[str, Any]] = []
        unconfirmed = 0
        try:
            page = await ward_room.dm_receipt_facts(agent_id, since=since, limit=limit, channel_names=names)
            for fact in page.threads:
                addressed = addressee_ids(fact.addressed, everyone, callsigns)
                resolution = classify_dm_recipient(fact.channel_name, agent_id, registered, addressed)
                if filtered_ids is None or (resolution.basis == EXACT and resolution.holder_ids[0] in filtered_ids):
                    messages.append(build_receipt(fact, resolution, agents=agents, callsigns=callsigns).to_output())
                else:
                    unconfirmed += int(resolution.basis in UNCONFIRMED_BASES)
        except Exception:  # noqa: BLE001 -- a read fault must not fail the turn
            logger.warning(
                "AD-1229: reading DM receipts for agent %s failed; the agent gets an honest "
                "could-not-read answer and the turn continues", agent_id, exc_info=True,
            )
            return _refuse(R_FAULT)
        output: dict[str, Any] = {"messages": messages, "count": len(messages), "window_hours": hours,
                                  "truncated": page.truncated}
        if filtered_ids is not None:
            output["unconfirmed"] = unconfirmed
        if not messages:
            clear = not page.truncated and not unconfirmed
            output["note"] = (NOTE_EMPTY if clear else NOTE_UNCONFIRMED).format(to_part=to_part, hours=hours)
        return _done(output)

    @staticmethod
    def _whole(value: Any, default: int, name: str) -> tuple[int, str | None]:
        """A whole number, the default for None, or the refusal for a bool, text or fraction."""
        if value is None:
            return default, None
        if isinstance(value, int) and not isinstance(value, bool):
            return value, None
        if isinstance(value, float) and value.is_integer():
            return int(value), None
        return default, R_WHOLE.format(name=name)

    @staticmethod
    def _recipient_channels(
        recipient: Any, agent_id: str, everyone: list[Any], callsigns: _CallsignDirectory | None,
    ) -> tuple[tuple[str, ...], str, frozenset[str] | None, str | None]:
        """The DM channel names one recipient filter covers, its note fragment, the ids it may prove, or a refusal."""
        wanted = "" if recipient is None else str(recipient).strip()
        if not wanted:
            return (), "", None, None
        if wanted.casefold() == CAPTAIN_DM_KEY:
            names = tuple(sorted({captain_dm_channel_name(agent_id), dm_channel_name(agent_id, CAPTAIN_DM_KEY)}))
            return names, " to the Captain", None, None
        resolved = callsigns.resolve(wanted) if callsigns is not None else None
        if resolved is None:
            return (), "", None, R_RECIPIENT
        agent_type = resolved.get("agent_type")
        holders = [a.id for a in everyone if a.agent_type == agent_type and a.id != agent_id]
        if not holders:
            own_types = {a.agent_type for a in everyone if a.id == agent_id}
            reason = R_SELF if agent_type in own_types else R_NOT_ABOARD
            return (), "", None, reason
        callsign = str(resolved.get("callsign") or "")
        to_part = f" to {callsign}" if _is_label(callsign) else " to that crew member"
        names = tuple(sorted({dm_channel_name(agent_id, h) for h in holders}))[:MAX_CHANNEL_NAMES]
        return names, to_part, frozenset(holders), None
