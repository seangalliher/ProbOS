"""AD-1228 (#1201): standing interests -- an agent is told when a declared condition becomes true.

An agent registers a *standing interest* in one declared condition and is told,
in its next accounted proactive think, when the condition becomes true, instead
of polling for it. The vocabulary is three kinds, and nothing else:

- ``work_item_finished``: one of the holder's own work items reaches a final
  state (the AD-1209 ownership rule, ``owns_work_item``);
- ``trust_falling``: another crew member's trust is on a significant downward
  trend (``linear_regression`` and ``MetricTrend`` over the AD-903 trust window;
  a steep or a dominant fall under a good fit, A-5);
- ``self_similarity_high``: another crew member's self-similarity reaches the
  self-monitoring "high" line.

Declared behavioural signals, never content. A notice carries ids, closed
codes, numbers and booleans only, and ``StandingInterestNotice`` refuses
anything else, so free text cannot be represented in one. A work item's title,
description and metadata prose are never read into a notice -- only the closed
``stranded_reason`` code. The boundary case is ``CounselorAssessment``
(``counselor.py:67``): its free-text fields are the Counselor's own prose about
a crew member, not a signal, and nothing here reads them.

Scope reuses two existing rules and is rechecked at delivery: the work kind is
the assignee only (AD-1209); the two crew-member kinds are clinical indicators
under the AD-903 ladder (``clinical_access_for_caller``), audited in the shape
of the Counselor router's clinical reads.

Transparency default (C-1, ``NOTIFY_SUBJECT_OF_CROSS_AGENT_INTEREST``): when a
new cross-agent interest is registered, its subject is told that it exists --
who holds it, which kind, until when -- and never any value.

Latency bound: detection is event-driven (listeners on the trust and work-item
events, one observer on the self-similarity ring). Delivery is the holder's
next proactive think that reaches the model; until then the notice waits in a
bounded in-memory queue, and a think that is skipped, fails or raises returns it.
Delivery is at least once and bounded (A-6): a bare ``[NO_RESPONSE]`` may be an
AD-672 shed that never reached the model, so a silent think returns the notice
until its key has been shown ``MAX_SILENT_DELIVERIES`` times. A notice whose
registration was revoked or has expired is never delivered.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from typing import Any, Protocol

from probos.cognitive.clinical_access import ClinicalAccessDecision, clinical_access_for_caller
from probos.cognitive.emergent_detector import MetricTrend, TrendDirection, linear_regression
from probos.cognitive.standing_interest_store import SELF_SIMILARITY_HIGH as KIND_SELF_SIMILARITY_HIGH
from probos.cognitive.standing_interest_store import (
    _ID_RE,
    CROSS_AGENT_KINDS,
    KINDS,
    TRUST_FALLING,
    WORK_ITEM_FINISHED,
    StandingInterest,
    StandingInterestLimitReached,
    StandingInterestStore,
    StandingInterestUnavailable,
)
from probos.tools.work_item_status_tool import (
    TERMINAL_WORK_ITEM_STATUSES,
    owns_work_item,
    resolve_owned_work_item,
)

logger = logging.getLogger(__name__)

# The AD-903 trust window: the Counselor trend surface reads the last 20 trust
# events (routers/counselor.py:210, ``trust_n: int = 20``).
TRUST_TREND_WINDOW = 20
# Below this many events a fitted slope is not read as a trend (AD-1228 choice).
TRUST_TREND_MIN_EVENTS = 8
# A-5: a trend needs a fit -- r2 above this on either arm (compute_trends uses 0.5).
TRUST_TREND_MIN_R_SQUARED = 0.8
# Steep arm: the EmergentDetector ``trend_threshold`` default that compute_trends applies.
TRUST_TREND_SLOPE_THRESHOLD = 0.005
# A-5 scale-free arm: slope / mean |step| is -1 when every step falls and near 0 for noise, at any tenure.
TRUST_TREND_MIN_CONSISTENCY = 0.8
# Self-monitoring's high line (proactive.py ``if sim >= 0.5`` cooldown,
# cognitive_agent.py ``if sim >= 0.5`` warning) and its moderate line
# (cognitive_agent.py ``elif sim >= 0.3``), below which a fired interest re-arms.
SELF_SIMILARITY_HIGH = 0.5
SELF_SIMILARITY_REARM = 0.3
# At most this many notices are rendered into one think; the rest wait for the next.
MAX_NOTICES_PER_THINK = 5
# Transparency notices a subject may have waiting on top of the registration cap.
MAX_TRANSPARENCY_PENDING = 8
# A-6, at least once and bounded: a notice shown in this many silent thinks (a deliberate
# [NO_RESPONSE] and an AD-672 shed look the same) is consumed as delivered.
MAX_SILENT_DELIVERIES = 2
# The closed stranding codes their producers write (quartermaster.py:339,
# turn_promotion.py:239 ``_UNCONFIRMED_EXPIRED_REASON``).
STRANDED_REASON_CODES: frozenset[str] = frozenset({"stalled_not_dispatchable", "unconfirmed_grace_expired"})
# The kind of the notice that tells a subject a cross-agent interest exists.
TRANSPARENCY = "transparency"
# C-1 (the Captain's open question), in-envelope default: the subject is told.
NOTIFY_SUBJECT_OF_CROSS_AGENT_INTEREST = True
# The only measure keys a notice of each kind may carry.
DECLARED_MEASURES: dict[str, frozenset[str]] = {
    WORK_ITEM_FINISHED: frozenset({"status", "stranded_reason", "opened_before_restart"}),
    TRUST_FALLING: frozenset({"slope", "r_squared", "window", "current"}),
    KIND_SELF_SIMILARITY_HIGH: frozenset({"similarity", "threshold"}),
    TRANSPARENCY: frozenset({"about_kind", "expires_at"}),
}
_NOTICE_KINDS: frozenset[str] = KINDS | {TRANSPARENCY}
# The measure keys whose value is text, each drawn from a closed set.
_CLOSED_TEXT: dict[str, frozenset[str]] = {
    "status": TERMINAL_WORK_ITEM_STATUSES,
    "stranded_reason": STRANDED_REASON_CODES | {"", "other"},
    "about_kind": CROSS_AGENT_KINDS,
}
_KEY_RE = re.compile(r"(?:t:)?[0-9a-f]{32}")
_AUDIT_REGISTER = "standing_interest_register"
_AUDIT_NOTICE = "standing_interest_notice"

# Model-facing text (contract P-I). Every string is clean against the
# decomposer's capability-gap pattern (test T5).
REASON_KIND = "kind must be one of: " + ", ".join(sorted(KINDS))
REASON_SUBJECT = (
    "a subject is needed: a work item id for work_item_finished, or a crew member's callsign or id "
    "for the other kinds"
)
REASON_NOT_OWNED = "no task with that id belongs to you; a work_item_finished interest names one of your own tasks"
REASON_SELF_CLINICAL = (
    "a crew member's clinical indicators are kept from the crew member themselves (AD-903), so "
    "trust_falling and self_similarity_high name another crew member"
)
REASON_CLINICAL = (
    "trust and self-similarity trends are clinical indicators; they are open to the Counselor and "
    "to holders of a Captain-issued clinical grant for that crew member (AD-903)"
)
REASON_UNKNOWN_SUBJECT = "no crew member matches that callsign or id"
REASON_CAP = "you already hold {limit} standing interests, the limit; revoke one first"
REASON_OFFLINE = "standing interests are offline right now; nothing was registered"
REASON_NO_WORK = "task records are switched off on this ship, so work_item_finished has nothing to follow"
REASON_REVOKE = "no standing interest of yours has that id"
REASON_ALREADY_FINISHED = "that task has already finished: {status}; a standing interest follows a task that is still open"
REASON_UNKNOWN_HOLDER = "the registering crew member is not on the crew roster, so nothing was registered"
REASON_TTL = "ttl_hours must be a whole number of hours, at least 1"
DELIVERY_TEXT = "Notices arrive as a SYSTEM NOTE in your next proactive think after the condition becomes true."
NOTICE_HEADER = "SYSTEM NOTE: {count} of your standing interests fired (AD-1228)."
NOTICE_FOOTER = "In a task or a conversation, the standing_interest tool lists or revokes them."
_WORK_LINE = "Work item {item} finished: {status}."
_STRANDED_LINE = " It was ended by the system (stranded: {code})."
_RESTART_LINE = " It was opened before the last restart."
_TRUST_LINE = (
    "Trust for {label} is falling: {slope:.3f} per update over the last {window} updates "
    "(fit r2 {r_squared:.2f}); now {current:.2f}."
)
_SIMILARITY_LINE = (
    "Self-similarity for {label} reached {similarity:.2f}; self-monitoring calls {threshold:.2f} and above high."
)
_TRANSPARENCY_LINE = (
    "{holder} registered a standing interest in your {about} until {until}. "
    "Only its existence is shared with you, never values."
)
_ABOUT: dict[str, str] = {TRUST_FALLING: "trust trend", KIND_SELF_SIMILARITY_HIGH: "self-similarity"}


class _TrustHistory(Protocol):
    def get_events_for_agent(self, agent_id: str, n: int = 20) -> list[Any]: ...


class _AgentLookup(Protocol):
    def get(self, agent_id: str) -> Any: ...


class _CallsignLookup(Protocol):
    def resolve(self, callsign: str) -> dict[str, Any] | None: ...

    def get_callsign(self, agent_type: str) -> str: ...


class _WorkItemReader(Protocol):
    async def get_work_item(self, work_item_id: str) -> Any: ...


@dataclass(frozen=True)
class StandingInterestNotice:
    """One fired standing interest, waiting for its recipient's next proactive think.

    ``key`` is the registration id (``t:<id>`` for a transparency notice).
    ``subject_id`` is a work-item id, a crew agent id, or -- for transparency --
    the holder's id. ``measure`` holds declared scalars only: the constructor
    refuses an undeclared key, text outside its closed set and non-finite
    numbers, so content cannot be represented here at all.
    """

    key: str
    recipient_id: str
    kind: str
    subject_id: str
    fired_at: float
    measure: tuple[tuple[str, float | int | bool | str], ...] = ()

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in _NOTICE_KINDS:
            raise ValueError("AD-1228: a notice kind is one of the standing interest kinds or transparency")
        if type(self.key) is not str or _KEY_RE.fullmatch(self.key) is None:
            raise ValueError("AD-1228: a notice key is a registration id")
        for value in (self.recipient_id, self.subject_id):
            if type(value) is not str or _ID_RE.fullmatch(value) is None:
                raise ValueError("AD-1228: notice ids must match the standing interest id pattern")
        if type(self.fired_at) not in (int, float) or not math.isfinite(self.fired_at):
            raise ValueError("AD-1228: fired_at must be a finite real")
        if type(self.measure) is not tuple:
            raise ValueError("AD-1228: measure must be a tuple of (name, value) pairs")
        declared = DECLARED_MEASURES[self.kind]
        seen: set[str] = set()
        for pair in self.measure:
            if type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str:
                raise ValueError("AD-1228: measure must be a tuple of (name, value) pairs")
            name, value = pair
            if name not in declared or name in seen:
                raise ValueError(f"AD-1228: {name[:32]!r} is not a declared measure of {self.kind}, or repeats")
            seen.add(name)
            closed = _CLOSED_TEXT.get(name)
            if closed is not None:
                if type(value) is not str or value not in closed:
                    raise ValueError(f"AD-1228: measure {name} must come from its closed set")
            elif type(value) is float:
                if not math.isfinite(value):
                    raise ValueError(f"AD-1228: measure {name} must be finite")
            elif type(value) not in (int, bool):
                raise ValueError(f"AD-1228: measure {name} must be a number or a bool")


@dataclass(frozen=True)
class RegistrationOutcome:
    """What ``register`` did: registered (renewed, clamped), or refused with a reason."""

    registered: bool
    reason: str = ""
    record: StandingInterest | None = None
    renewed: bool = False
    clamped: bool = False
    subject_label: str = ""


@dataclass
class _EdgeState:
    """Per-registration edge and debounce state. In memory: a restart re-arms."""

    armed: bool = True
    last_fired: float = -math.inf


def format_utc(ts: float) -> str:
    """``ts`` as ``YYYY-MM-DD HH:MM UTC`` -- the only way a time reaches the model."""
    return datetime.fromtimestamp(float(ts), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def evaluate_trust_trend(values: Sequence[float]) -> MetricTrend | None:
    """A FALLING trust ``MetricTrend``, or None: the A-5 rule over the last trust updates.

    Over at least ``TRUST_TREND_MIN_EVENTS`` values, ``linear_regression`` must fit with
    ``r_squared`` above ``TRUST_TREND_MIN_R_SQUARED``, and the slope must meet one arm:
    steep, a fall faster than ``TRUST_TREND_SLOPE_THRESHOLD`` per update (a short record's
    large fall), or consistent, a fall of at least ``TRUST_TREND_MIN_CONSISTENCY`` of the
    window's mean absolute step. The fitted slope is a weighted mean of the steps, so the
    consistent arm does not depend on tenure, outcome weight or dampening.
    """
    if len(values) < TRUST_TREND_MIN_EVENTS:
        return None
    ys = [float(value) for value in values]
    xs = [float(i) for i in range(len(ys))]
    slope, _intercept, r_squared = linear_regression(xs, ys)
    if r_squared <= TRUST_TREND_MIN_R_SQUARED:
        return None
    # r2 > 0.8 excludes a flat window, so mean_step > 0 and either arm implies slope < 0.
    mean_step = sum(abs(b - a) for a, b in zip(ys, ys[1:])) / (len(ys) - 1)
    steep = slope < -TRUST_TREND_SLOPE_THRESHOLD
    consistent = slope <= -TRUST_TREND_MIN_CONSISTENCY * mean_step
    if not (steep or consistent):
        return None
    return MetricTrend(
        metric_name="trust",
        direction=TrendDirection.FALLING,
        slope=slope,
        r_squared=r_squared,
        current_value=ys[-1],
        window_size=len(ys),
        significant=True,
    )


def stranded_reason_code(metadata: object) -> str:
    """The closed stranding code in a work item's metadata: the code, ``"other"``, or ``""`` when absent."""
    if not isinstance(metadata, dict):
        return ""
    code = metadata.get("stranded_reason")
    if code is None or code == "":
        return ""
    if type(code) is str and code in STRANDED_REASON_CODES:
        return code
    return "other"


def render_notices(notices: Sequence[StandingInterestNotice], *, label_for: Callable[[str], str]) -> str:
    """The SYSTEM NOTE block: a header, one line per notice, then the footer."""
    lines = [NOTICE_HEADER.format(count=len(notices))]
    for notice in notices:
        measure = dict(notice.measure)
        if notice.kind == WORK_ITEM_FINISHED:
            line = _WORK_LINE.format(item=notice.subject_id[:8], status=measure.get("status", ""))
            if measure.get("stranded_reason"):
                line += _STRANDED_LINE.format(code=measure["stranded_reason"])
            if measure.get("opened_before_restart") is True:
                line += _RESTART_LINE
        elif notice.kind == TRUST_FALLING:
            line = _TRUST_LINE.format(
                label=label_for(notice.subject_id), slope=measure.get("slope", 0.0),
                window=measure.get("window", 0), r_squared=measure.get("r_squared", 0.0),
                current=measure.get("current", 0.0),
            )
        elif notice.kind == KIND_SELF_SIMILARITY_HIGH:
            line = _SIMILARITY_LINE.format(
                label=label_for(notice.subject_id), similarity=measure.get("similarity", 0.0),
                threshold=measure.get("threshold", SELF_SIMILARITY_HIGH),
            )
        else:
            line = _TRANSPARENCY_LINE.format(
                holder=label_for(notice.subject_id),
                about=_ABOUT.get(str(measure.get("about_kind", "")), "clinical indicators"),
                until=format_utc(measure.get("expires_at", notice.fired_at)),
            )
        lines.append(line)
    lines.append(NOTICE_FOOTER)
    return "\n".join(lines)


def _label_for(agents: _AgentLookup | None, callsigns: _CallsignLookup | None, agent_id: str) -> str:
    """The callsign of ``agent_id``'s agent type, else the first 12 characters of the id."""
    try:
        agent = agents.get(agent_id) if agents is not None else None
        agent_type = str(getattr(agent, "agent_type", "") or "") if agent is not None else ""
        callsign = callsigns.get_callsign(agent_type) if callsigns is not None and agent_type else ""
    except Exception:  # noqa: BLE001 -- a label lookup must not lose the notice
        logger.debug("AD-1228: callsign lookup for %s failed; the id is shown instead", agent_id[:32], exc_info=True)
        callsign = ""
    if isinstance(callsign, str) and callsign and callsign.isprintable():
        return callsign[:64]
    return agent_id[:12]


def _resolve_crew_id(agents: _AgentLookup, callsigns: _CallsignLookup | None, subject: str) -> str | None:
    """An exact agent-registry id, else the agent a callsign resolves to, else None."""
    if agents.get(subject) is not None:
        return subject
    resolved = callsigns.resolve(subject) if callsigns is not None else None
    agent_id = resolved.get("agent_id") if isinstance(resolved, dict) else None
    return agent_id if isinstance(agent_id, str) and agent_id else None


def _work_item_measure(item: Any, *, session_started_at: float) -> tuple[tuple[str, str | bool], ...]:
    """A finished item's declared measure: status, stranding code, opened before this session."""
    created = getattr(item, "created_at", None)
    before = type(created) in (int, float) and math.isfinite(created) and created < session_started_at
    return (
        ("status", str(getattr(item, "status", "") or "")),
        ("stranded_reason", stranded_reason_code(getattr(item, "metadata", None))),
        ("opened_before_restart", bool(before)),
    )


def _audit_clinical(ring: Any, *, requester: str, target: str, query_type: str, granted: bool) -> None:
    """Append one AD-903-shaped clinical access entry. A missing or failing ring never blocks."""
    if ring is None:
        return
    entry: dict[str, Any] = {
        "ts": time.time(),
        "requester_agent_id": requester,
        "query_type": query_type,
        "granted": bool(granted),
        "result_count": 0,
        "target_agent_id": target,
    }
    try:
        ring.append(entry)
    except Exception:  # noqa: BLE001 -- the AD-903 ring is fail-safe by design
        logger.debug("AD-1228: clinical access audit append failed; the decision stands", exc_info=True)


def _trim(queue: list[StandingInterestNotice], bound: int, recipient_id: str, silent: dict[str, int]) -> None:
    """Keep the newest ``bound`` notices, logging each one dropped; its silent count goes with it (A-8)."""
    while len(queue) > bound:
        dropped = queue.pop(0)
        silent.pop(dropped.key, None)
        logger.info(
            "AD-1228: a %s notice for %s was dropped: more than %d were waiting, so the oldest "
            "goes and the newest are kept",
            dropped.kind, recipient_id[:32], bound,
        )


def _drop_key(pending: dict[str, list[StandingInterestNotice]], recipient_id: str, key: str) -> None:
    """Remove ``recipient_id``'s pending notice for ``key`` (a retired registration)."""
    queue = pending.get(recipient_id)
    if not queue:
        return
    queue[:] = [notice for notice in queue if notice.key != key]
    if not queue:
        pending.pop(recipient_id, None)


def _live_registration_ids(store: StandingInterestStore) -> set[str] | None:
    """The ids of every live registration, or None while the store is offline."""
    try:
        return {record.id for record in store.live()}
    except StandingInterestUnavailable:
        return None


def _trust_measure(trend: MetricTrend | None) -> tuple[tuple[str, float | int], ...]:
    """A falling trend's declared measure, or ``()`` when the trend is not falling."""
    if trend is None:
        return ()
    return (
        ("slope", trend.slope),
        ("r_squared", trend.r_squared),
        ("window", trend.window_size),
        ("current", trend.current_value),
    )


def _silent_showing(
    notices: Sequence[StandingInterestNotice], shown: dict[str, int], replaced: set[str],
) -> list[StandingInterestNotice]:
    """Count one silent showing of each notice in ``shown``; return those now at ``MAX_SILENT_DELIVERIES``.

    A notice that a newer firing replaced during the think is not counted (A-7): that firing counts its own.
    """
    consumed: list[StandingInterestNotice] = []
    for notice in notices:
        if notice.key in replaced:
            continue
        count = shown.get(notice.key, 0) + 1
        if count >= MAX_SILENT_DELIVERIES:
            consumed.append(notice)
        else:
            shown[notice.key] = count
    return consumed


async def _recheck_work_items(
    reader: _WorkItemReader | None,
    batch: Sequence[StandingInterestNotice],
    retire: Callable[..., Awaitable[bool]],
) -> tuple[list[StandingInterestNotice], list[StandingInterestNotice]]:
    """A-7: ``(deliverable, back)`` -- each work-item notice's item is re-read before it is shown.

    A missing or reassigned item drops the notice and retires its interest (``retire``); a
    fault while reading or retiring puts the notice ``back``, neither delivered nor dropped.
    """
    deliverable: list[StandingInterestNotice] = []
    back: list[StandingInterestNotice] = []
    for notice in batch:
        if notice.kind == WORK_ITEM_FINISHED:
            try:
                current = await reader.get_work_item(notice.subject_id) if reader is not None else None
                if not owns_work_item(current, notice.recipient_id):
                    await retire(registration_id=notice.key)
                    logger.info(
                        "AD-1228: work item %s is no longer %s's at delivery; its notice is dropped and "
                        "the interest retired",
                        notice.subject_id[:8], notice.recipient_id[:32],
                    )
                    continue
            except Exception:  # noqa: BLE001 -- a fault must neither deliver nor drop the notice
                logger.warning(
                    "AD-1228: checking work item %s for %s's notice failed; the notice waits for the "
                    "next think",
                    notice.subject_id[:8], notice.recipient_id[:32], exc_info=True,
                )
                back.append(notice)
                continue
        deliverable.append(notice)
    return deliverable, back


def _live_at_delivery(
    store: StandingInterestStore,
    popped: list[StandingInterestNotice],
    batch: list[StandingInterestNotice],
    back: list[StandingInterestNotice],
    silent: dict[str, int],
) -> tuple[list[StandingInterestNotice], list[StandingInterestNotice]]:
    """A-8: ``(deliverable, back)`` with liveness read again once the take's last await is over.

    A registration revoked or expired while the take was suspended drops its notice and its
    silent count here, before the clinical re-scope and the render. While the store is offline
    liveness is unknown, so every notice goes ``back`` to wait, as it would before the take, in
    its ``popped`` order; a notice whose interest the re-read retired stays out (A-9).
    """
    live_now = _live_registration_ids(store)
    if live_now is None:
        return [], [notice for notice in popped if notice in batch or notice in back]
    deliverable: list[StandingInterestNotice] = []
    for notice in batch:
        if notice.key.removeprefix("t:") not in live_now:
            silent.pop(notice.key, None)
            logger.debug(
                "AD-1228: a %s notice for %s was dropped at delivery: its registration was revoked or "
                "expired while the notice was being taken",
                notice.kind, notice.recipient_id[:32],
            )
            continue
        deliverable.append(notice)
    return deliverable, back


class StandingInterestService:
    """Registers standing interests, detects their conditions from events, and queues notices.

    Public API:
        resume() -- re-queue finished work-item notices after a restart (wiring calls it once)
        register(...) / revoke(...) / describe(holder_id) -- the tool's three actions
        on_trust_update(event) / on_work_item_event(event) / on_self_similarity(agent_id, sim)
            -- two runtime listeners and the self-similarity observer; none of them raises
        take_notices(agent_id) / settle(agent_id, notices, delivered=..., silent=...) /
            restore_notices(agent_id, notices) -- the proactive think
    """

    def __init__(
        self,
        *,
        store: StandingInterestStore,
        trust_history: _TrustHistory,
        agents: _AgentLookup,
        callsigns: _CallsignLookup | None,
        work_items: _WorkItemReader | None,
        grant_store: Any,
        clinical_audit: Any,
        max_per_agent: int,
        default_ttl_hours: int,
        max_ttl_hours: int,
        min_fire_interval_seconds: int,
        session_started_at: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._trust = trust_history
        self._agents = agents
        self._callsigns = callsigns
        self._work_items = work_items
        self._grant_store = grant_store
        self._audit = clinical_audit
        self._max_per_agent = max_per_agent
        self._default_ttl_hours = min(default_ttl_hours, max_ttl_hours)
        self._max_ttl_hours = max_ttl_hours
        self._min_fire_interval = float(min_fire_interval_seconds)
        self._session_started_at = float(session_started_at)
        self._clock = clock
        self._pending: dict[str, list[StandingInterestNotice]] = {}
        self._pending_bound = max_per_agent + MAX_TRANSPARENCY_PENDING
        self._edges: dict[str, _EdgeState] = {}
        self._silent: dict[str, int] = {}  # A-6: silent showings per notice key, until it is consumed
        self._label = partial(_label_for, agents, callsigns)

    async def resume(self) -> int:
        """Queue a notice for each live work-item interest whose item finished while nothing listened."""
        if self._work_items is None:
            return 0
        queued = 0
        for record in self._store.live(WORK_ITEM_FINISHED):
            item = await self._work_items.get_work_item(record.subject_id)
            status = str(getattr(item, "status", "") or "") if item is not None else ""
            if status in TERMINAL_WORK_ITEM_STATUSES and owns_work_item(item, record.agent_id):
                self._queue(StandingInterestNotice(
                    key=record.id,
                    recipient_id=record.agent_id,
                    kind=WORK_ITEM_FINISHED,
                    subject_id=record.subject_id,
                    fired_at=self._clock(),
                    measure=_work_item_measure(item, session_started_at=self._session_started_at),
                ))
                queued += 1
        logger.info("AD-1228: resume queued %d notice(s) for work items that finished while undelivered", queued)
        return queued

    async def register(
        self, *, holder_id: str, kind: str, subject: str, ttl_hours: int | None,
    ) -> RegistrationOutcome:
        """Register (or renew) ``holder_id``'s interest in ``kind`` of ``subject``; a refusal carries its reason."""
        if type(kind) is not str or kind not in KINDS:
            return RegistrationOutcome(registered=False, reason=REASON_KIND)
        if not isinstance(subject, str) or not subject.strip():
            return RegistrationOutcome(registered=False, reason=REASON_SUBJECT)
        if ttl_hours is not None and (type(ttl_hours) is not int or ttl_hours < 1):
            return RegistrationOutcome(registered=False, reason=REASON_TTL)
        if type(holder_id) is not str or _ID_RE.fullmatch(holder_id) is None or self._agents.get(holder_id) is None:
            return RegistrationOutcome(registered=False, reason=REASON_UNKNOWN_HOLDER)
        if kind == WORK_ITEM_FINISHED:
            if self._work_items is None:
                return RegistrationOutcome(registered=False, reason=REASON_NO_WORK)
            item = await resolve_owned_work_item(self._work_items, subject, holder_id)
            if item is None:
                return RegistrationOutcome(registered=False, reason=REASON_NOT_OWNED)
            status = str(getattr(item, "status", "") or "")
            if status in TERMINAL_WORK_ITEM_STATUSES:
                return RegistrationOutcome(registered=False, reason=REASON_ALREADY_FINISHED.format(status=status))
            subject_id = str(getattr(item, "id", "") or "")
            label = subject_id[:8]
        else:
            resolved = _resolve_crew_id(self._agents, self._callsigns, subject.strip())
            if resolved is None:
                return RegistrationOutcome(registered=False, reason=REASON_UNKNOWN_SUBJECT)
            subject_id = resolved
            decision = self._clinical_scope(holder_id, subject_id)
            _audit_clinical(
                self._audit, requester=holder_id, target=subject_id, query_type=_AUDIT_REGISTER,
                granted=decision.allowed,
            )
            if not decision.allowed:
                reason = REASON_SELF_CLINICAL if decision.source == "subject_denied" else REASON_CLINICAL
                return RegistrationOutcome(registered=False, reason=reason)
            label = self._label(subject_id)
        requested = ttl_hours or self._default_ttl_hours
        hours = min(requested, self._max_ttl_hours)
        try:
            record, renewed = await self._store.register(
                agent_id=holder_id, kind=kind, subject_id=subject_id,
                ttl_seconds=hours * 3600, max_live=self._max_per_agent,
            )
        except StandingInterestLimitReached as exc:
            return RegistrationOutcome(registered=False, reason=REASON_CAP.format(limit=exc.limit))
        except StandingInterestUnavailable:
            return RegistrationOutcome(registered=False, reason=REASON_OFFLINE)
        if kind in CROSS_AGENT_KINDS and NOTIFY_SUBJECT_OF_CROSS_AGENT_INTEREST:
            if not renewed and holder_id != subject_id:
                self._queue(StandingInterestNotice(
                    key="t:" + record.id,
                    recipient_id=subject_id,
                    kind=TRANSPARENCY,
                    subject_id=holder_id,
                    fired_at=self._clock(),
                    measure=(("about_kind", kind), ("expires_at", record.expires_at)),
                ))
        live_ids = {live.id for live in self._store.live()}
        for dead in [rid for rid in self._edges if rid not in live_ids]:
            del self._edges[dead]
        self._silent = {key: shown for key, shown in self._silent.items() if key.removeprefix("t:") in live_ids}
        logger.info(
            "AD-1228: %s %s a %s interest in %s for %d hour(s)%s",
            holder_id[:32], "renewed" if renewed else "registered", kind, subject_id[:32], hours,
            " (clamped to the ceiling)" if hours < requested else "",
        )
        return RegistrationOutcome(
            registered=True, record=record, renewed=renewed, clamped=hours < requested, subject_label=label,
        )

    async def revoke(self, *, holder_id: str, registration_id: str) -> bool:
        """Retire the holder's registration; its pending notice and edge state go with it."""
        removed = await self._store.revoke(registration_id, agent_id=holder_id)
        if removed:
            self._edges.pop(registration_id, None)
            _drop_key(self._pending, holder_id, registration_id)
        return removed

    def describe(self, holder_id: str) -> dict[str, Any]:
        """What ``holder_id`` holds, and the cross-agent interests others hold about them."""
        held = [
            {
                "registration_id": record.id,
                "kind": record.kind,
                "subject": record.subject_id[:8] if record.kind == WORK_ITEM_FINISHED else self._label(record.subject_id),
                "expires_at_utc": format_utc(record.expires_at),
            }
            for record in self._store.live_for_holder(holder_id)
        ]
        about_you = [
            {"kind": record.kind, "holder": self._label(record.agent_id), "expires_at_utc": format_utc(record.expires_at)}
            for record in self._store.live_naming(holder_id)
        ]
        return {"held": held, "held_about_you": about_you, "limit": self._max_per_agent, "count": len(held)}

    def on_trust_update(self, event: dict[str, Any]) -> None:
        """TRUST_UPDATE listener: evaluate the live trust_falling interests in the updated agent. Never raises."""
        try:
            data = event.get("data") if isinstance(event, dict) else None
            subject = data.get("agent_id") if isinstance(data, dict) else None
            if not isinstance(subject, str) or not subject:
                return
            records = self._store.live_for_subject(TRUST_FALLING, subject)
            if not records:
                return
            window = [e.new_score for e in self._trust.get_events_for_agent(subject, n=TRUST_TREND_WINDOW)]
            trend = evaluate_trust_trend(window)
            measure = _trust_measure(trend)
            for record in records:
                self._fire_level(record, condition=trend is not None, rearm=trend is None, measure=measure)
        except StandingInterestUnavailable:
            logger.debug("AD-1228: a trust update was not evaluated: the standing interest store is offline")
        except Exception:  # noqa: BLE001 -- a listener must never break the emitter
            logger.warning(
                "AD-1228: evaluating a trust update failed; this update is skipped and the next one is evaluated",
                exc_info=True,
            )

    async def on_work_item_event(self, event: dict[str, Any]) -> None:
        """Work-item status/update listener: the payload names the item, the store says its state."""
        try:
            data = event.get("data") if isinstance(event, dict) else None
            payload = data.get("work_item") if isinstance(data, dict) else None
            item_id = payload.get("id") if isinstance(payload, dict) else None
            if not isinstance(item_id, str) or not item_id:
                return
            records = self._store.live_for_subject(WORK_ITEM_FINISHED, item_id)
            if not records or self._work_items is None:
                return
            current = await self._work_items.get_work_item(item_id)
            status = str(getattr(current, "status", "") or "") if current is not None else ""
            if status not in TERMINAL_WORK_ITEM_STATUSES:
                return
            measure = _work_item_measure(current, session_started_at=self._session_started_at)
            for record in records:
                if not owns_work_item(current, record.agent_id):
                    await self.revoke(holder_id=record.agent_id, registration_id=record.id)
                    logger.info(
                        "AD-1228: work item %s finished after it was reassigned; %s's interest in it "
                        "is retired without a notice",
                        item_id[:8], record.agent_id[:32],
                    )
                    continue
                self._queue(StandingInterestNotice(
                    key=record.id,
                    recipient_id=record.agent_id,
                    kind=WORK_ITEM_FINISHED,
                    subject_id=current.id,
                    fired_at=self._clock(),
                    measure=measure,
                ))
        except StandingInterestUnavailable:
            logger.debug("AD-1228: a work item event was not evaluated: the standing interest store is offline")
        except Exception:  # noqa: BLE001 -- a listener must never break the emitter
            logger.warning(
                "AD-1228: evaluating a work item event failed; this event is skipped and the next one "
                "is evaluated",
                exc_info=True,
            )

    def on_self_similarity(self, agent_id: str, sim: float) -> None:
        """Self-similarity observer: evaluate the live self_similarity_high interests in ``agent_id``. Never raises."""
        try:
            if not isinstance(agent_id, str) or not agent_id:
                return
            if type(sim) not in (int, float) or not math.isfinite(sim):
                return
            records = self._store.live_for_subject(KIND_SELF_SIMILARITY_HIGH, agent_id)
            if not records:
                return
            high = sim >= SELF_SIMILARITY_HIGH
            rearm = sim < SELF_SIMILARITY_REARM
            measure = (("similarity", float(sim)), ("threshold", SELF_SIMILARITY_HIGH))
            for record in records:
                self._fire_level(record, condition=high, rearm=rearm, measure=measure)
        except StandingInterestUnavailable:
            logger.debug("AD-1228: a self-similarity sample was not evaluated: the standing interest store is offline")
        except Exception:  # noqa: BLE001 -- an observer must never break the producer
            logger.warning(
                "AD-1228: evaluating a self-similarity sample failed; this sample is skipped and the next "
                "one is evaluated",
                exc_info=True,
            )

    async def take_notices(self, agent_id: str) -> tuple[tuple[StandingInterestNotice, ...], str]:
        """Pop up to ``MAX_NOTICES_PER_THINK`` of ``agent_id``'s notices, oldest first, and render them.

        A notice whose registration is no longer live (revoked, deleted or expired) is dropped. A
        work-item notice's item is re-read (A-7): missing or no longer the recipient's, the notice
        is dropped and its interest retired; a read fault puts it back. Liveness is read again after
        that last await (A-8). A crew-member notice is then re-checked against the AD-903 ladder: a
        scope withdrawn since the firing drops it, audited ``granted=False``. While the store is
        offline nothing is taken, and the notices wait.
        """
        queue = self._pending.get(agent_id)
        if not queue:
            return (), ""
        live = _live_registration_ids(self._store)
        if live is None:
            logger.debug("AD-1228: notices for %s wait: the standing interest store is offline", agent_id[:32])
            return (), ""
        for notice in list(queue):
            if notice.key.removeprefix("t:") not in live:
                queue.remove(notice)
                self._silent.pop(notice.key, None)
                logger.debug(
                    "AD-1228: a %s notice for %s was dropped: its registration was revoked or has expired",
                    notice.kind, agent_id[:32],
                )
        popped = queue[:MAX_NOTICES_PER_THINK]
        del queue[:MAX_NOTICES_PER_THINK]
        if not queue:
            self._pending.pop(agent_id, None)
        try:
            batch, back = await _recheck_work_items(self._work_items, popped, partial(self.revoke, holder_id=agent_id))
        except asyncio.CancelledError:
            self.restore_notices(agent_id, popped)  # a take cancelled mid-read loses nothing
            raise
        batch, back = _live_at_delivery(self._store, popped, batch, back, self._silent)  # A-8: nothing awaits after this
        if back:
            self.restore_notices(agent_id, back)
        taken: list[StandingInterestNotice] = []
        for notice in batch:
            if notice.kind in CROSS_AGENT_KINDS:
                if not self._clinical_scope(notice.recipient_id, notice.subject_id).allowed:
                    _audit_clinical(
                        self._audit, requester=notice.recipient_id, target=notice.subject_id,
                        query_type=_AUDIT_NOTICE, granted=False,
                    )
                    logger.info(
                        "AD-1228: a %s notice for %s was dropped at delivery: the clinical scope that "
                        "admitted it has been withdrawn",
                        notice.kind, agent_id[:32],
                    )
                    continue
                _audit_clinical(
                    self._audit, requester=notice.recipient_id, target=notice.subject_id,
                    query_type=_AUDIT_NOTICE, granted=True,
                )
            taken.append(notice)
        return (tuple(taken), render_notices(taken, label_for=self._label)) if taken else ((), "")

    async def settle(
        self, agent_id: str, notices: Sequence[StandingInterestNotice], *, delivered: bool, silent: bool = False,
    ) -> None:
        """After the think: consume what the model saw and put the rest back (A-6, at least once).

        ``delivered`` consumes every notice. ``silent`` -- a bare ``[NO_RESPONSE]``, which an
        AD-672 shed also returns -- puts each one back until its firing has been shown
        ``MAX_SILENT_DELIVERIES`` times, then consumes it; a newer firing counts afresh (A-7).
        Otherwise every notice goes back. Consuming a ``work_item_finished`` notice retires its
        one-shot registration.
        """
        if not notices:
            return
        consumed = list(notices) if delivered else []
        if silent and not delivered:
            replaced = {waiting.key for waiting in self._pending.get(agent_id, ())}
            consumed = _silent_showing(notices, self._silent, replaced)
        back = [notice for notice in notices if notice not in consumed]
        if back:
            self.restore_notices(agent_id, back)
        for notice in consumed:
            self._silent.pop(notice.key, None)
            if notice.kind == WORK_ITEM_FINISHED:
                await self._store.revoke(notice.key, agent_id=agent_id)
                _drop_key(self._pending, agent_id, notice.key)
        if consumed:
            logger.info("AD-1228: %d notice(s) delivered to %s", len(consumed), agent_id[:32])

    def restore_notices(self, agent_id: str, notices: Sequence[StandingInterestNotice]) -> None:
        """Put taken ``notices`` back at the front of ``agent_id``'s queue. Synchronous; never raises.

        A notice whose registration is no longer live (revoked, deleted or expired) is
        dropped, and a newer pending notice with the same key wins. While the store is
        offline liveness is unknown, so every notice goes back and the next take decides.
        """
        try:
            live = _live_registration_ids(self._store)
            queue = self._pending.setdefault(agent_id, [])
            newer = {waiting.key for waiting in queue}
            kept: list[StandingInterestNotice] = []
            for notice in notices:
                if live is not None and notice.key.removeprefix("t:") not in live:
                    self._silent.pop(notice.key, None)
                    logger.debug(
                        "AD-1228: a %s notice for %s was not put back: its registration was revoked or "
                        "has expired",
                        notice.kind, agent_id[:32],
                    )
                elif notice.key not in newer:
                    kept.append(notice)
            queue[:0] = kept
            _trim(queue, self._pending_bound, agent_id, self._silent)
            if not queue:
                self._pending.pop(agent_id, None)
            logger.info(
                "AD-1228: %d notice(s) for %s went back to the queue for the next think", len(kept), agent_id[:32],
            )
        except Exception:  # noqa: BLE001 -- it runs in a finally, where raising would mask the think's own exception
            logger.warning(
                "AD-1228: putting standing interest notices back for %s failed; they are lost, and the "
                "think's own outcome or exception stands",
                agent_id, exc_info=True,
            )

    def _clinical_scope(self, holder_id: str, subject_id: str) -> ClinicalAccessDecision:
        """The AD-903 ladder for ``holder_id`` reading ``subject_id``'s clinical indicators."""
        holder = self._agents.get(holder_id)
        return clinical_access_for_caller(
            caller_agent_id=holder_id,
            caller_agent_type=str(getattr(holder, "agent_type", "") or ""),
            target_agent_id=subject_id,
            is_captain=False,
            grant_store=self._grant_store,
        )

    def _queue(self, notice: StandingInterestNotice) -> None:
        """Queue ``notice``; a newer firing replaces a pending one with the same key and starts its own silent count."""
        queue = self._pending.setdefault(notice.recipient_id, [])
        queue[:] = [waiting for waiting in queue if waiting.key != notice.key]
        queue.append(notice)
        self._silent[notice.key] = 0
        _trim(queue, self._pending_bound, notice.recipient_id, self._silent)

    def _fire_level(
        self, record: StandingInterest, *, condition: bool, rearm: bool,
        measure: tuple[tuple[str, float | int | bool | str], ...],
    ) -> None:
        """Edge-trigger ``record``: re-arm first, then fire once while armed, true and past the interval."""
        state = self._edges.setdefault(record.id, _EdgeState())
        if rearm:
            state.armed = True
        if not condition or not state.armed:
            return
        now = self._clock()
        if now - state.last_fired < self._min_fire_interval:
            return
        notice = StandingInterestNotice(
            key=record.id,
            recipient_id=record.agent_id,
            kind=record.kind,
            subject_id=record.subject_id,
            fired_at=now,
            measure=measure,
        )
        state.armed = False
        state.last_fired = now
        self._queue(notice)
