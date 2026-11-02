"""AD-1347 S3 (#1627): the Ship's Computer runs agent-created work and reports it where it was asked.

One runner per vessel, built in finalize only while ``runtime.agent_work`` exists. It reacts to the work store's own
events (one listener):

- a created self-task or chief assignment runs at once, in its assignee's agentic loop;
- a created department request is announced once to each eligible member, in that department's channel, with the
  claim and decline tags (a pull reaches nobody by itself; the TTL is the backstop);
- a claimed request runs in its claimant's agentic loop (AD-1187's claim; the chain's CLAIM_WORK claims through the
  same tool sink and also starts the run itself);
- an item that ends has its live bookings closed and is reported, once per recipient, to its requester and watchers.

Every run is confined (``ToolCallConfinement``): the tools in ``AGENT_WORK_READ_TOOL_IDS`` run as usual and a call to
any other tool is put to the run's gate (``_gate_for``, whose docstring gives its order), which may file it as an
AD-1154 ``action`` request. A run that filed a call can park the item ``blocked`` on the first request its gate
returned, through AD-855's ``block_on_request``; its approval fulfils it and AD-855 resumes the item through
``resume_agent_work``, and its denial cancels the item (AD-855). BF-947: before a run, the agent-work requests the
item's assignee filed on it are read, oldest first. A denied one cancels the item; else a pending one, or an approved
one not yet fulfilled, parks the item on it again; else the run goes ahead, and a fulfilled one may admit its call once
(a claim-once row). The run is given the results
this runner keeps of calls admitted on the item for the same agent, and the gate answers a repeat of one of those calls
without running it. The report reads a denial's reason from the request.

The stop: every run enters at ``WorkItemAgenticExecutor.run``, which refuses a stopped agent at ``agentic_run``. A
request whose claimant may no longer run it (stopped, moved, lost the tool) goes back to the board unclaimed, never
failed. Expiry stays the store's TTL sweep; this runner only reports it. The cognitive layer is imported inside the
functions that run work, so the approval route's import of ``agent_work_approval`` loads no agentic stack.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from probos.agent_stop import AgentStopped
from probos.agent_work import (
    KIND_REQUEST,
    MAX_REASON_CHARS,
    OUTCOME_EXPIRED,
    SCAN_LIMIT,
    AgentWorkNotice,
    AgentWorkRecord,
    AgentWorkService,
    read_agent_work,
)
from probos.capability_request import (
    AGENT_WORK_CALL_ACTION,
    AGENT_WORK_SCOPE_PREFIX,
    action_dedup_key,
    agent_work_call,
    requests_for_work_item,
    validate_action_payload,
)
from probos.events import EventType
from probos.tools.protocol import ToolPermission, ToolResultPresentation
from probos.workforce import AGENT_WORK_METADATA_KEY, WorkItem

if TYPE_CHECKING:
    from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

logger = logging.getLogger(__name__)

#: The tools an agent-created work run calls directly: the plan-mode read set (``agent_mode.PLAN_MODE_TOOL_IDS``, each
#: asserted read-only there) without the three that reach off the ship (web_search, read_page, http_fetch) and without
#: discover_work_items. Every other call is filed for the Captain's approval: a new or renamed tool is filed until
#: someone decides it only reads.
AGENT_WORK_READ_TOOL_IDS: Final[frozenset[str]] = frozenset({
    "event_log_query", "oracle_query", "self_query", "search_capabilities", "use_skill",
    "work_item_status", "read_owned_steps", "recall_artifact", "message_receipts", "load_tools",
})
APPROVAL_ACTION: Final = AGENT_WORK_CALL_ACTION  # A1 (F1): one definition, shared with the fulfilment predicate
APPROVAL_SCOPE_PREFIX: Final = AGENT_WORK_SCOPE_PREFIX
#: A1 (F15): parameters an approval never records, as AD-1154's inbox strips them (``_APPROVAL_PARAM_STRIP_KEYS``): a
#: browser confirmation token is a bearer token ``BrowserTool`` honours, so persisting it is BF-682. Stripped before
#: filing and before matching alike, so the approved call's identity does not depend on it.
APPROVAL_UNRECORDED_PARAMS: Final[frozenset[str]] = frozenset({"confirmation_token"})
APPROVAL_USE_PREFIX: Final = "approval_use:"
NOTICE_ACTIVATION: Final = "activation"
NOTICE_DECLINE: Final = "decline"
RESULT_METADATA_KEY: Final = "agent_work_result"
SHIP_COMPUTER_ID: Final = "system"
SHIP_COMPUTER_CALLSIGN: Final = "Ship's Computer"
RUN_SOURCE: Final = "agent_work_runner"
REPORT_MAX_CHARS: Final = 1_500
BLOCKED_REASON: Final = "waiting for the Captain's decision on a tool call outside the read-only set"
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset({"done", "failed", "cancelled"})
#: A1 (F4): how a report names a run that stopped without a finished answer, by the executor's ``stopped_reason``
#: (``agentic_loop``); ``complete`` without an answer, and any other reason, read as ``UNFINISHED_WORDS``.
STOP_WORDS: Final[dict[str, str]] = {
    "max_iterations": "the run reached its step limit before it finished",
    "token_budget": "the run used up its token budget before it finished",
    "error": "the run stopped on an error",
}
UNFINISHED_WORDS: Final = "the run stopped without a finished answer"
_HANDLED_EVENTS: Final[frozenset[str]] = frozenset({
    EventType.WORK_ITEM_CREATED.value, EventType.WORK_ITEM_CLAIMED.value, EventType.WORK_ITEM_STATUS_CHANGED.value,
})
#: The claim tool renders its receipt through the invocation's presentation; the runner reads the board, not the text.
_PRESENTATION: Final = ToolResultPresentation(render_complete=repr)
#: BF-947: an agent-work request in these statuses is waited for (an approved one is not yet fulfilled).
_UNDECIDED: Final[frozenset[str]] = frozenset({"pending", "approved"})
#: BF-947 (M3): how many results of admitted calls the runner keeps per item, and how much of each it keeps.
CARRIED_RESULTS_MAX: Final = 8
CARRIED_RESULT_MAX_CHARS: Final = 1_500
CARRIED_PARAMS_MAX_CHARS: Final = 200


@dataclass(frozen=True)
class CarriedResult:
    """BF-947 (M3): the result of one call admitted in a run of an item, by the agent that made it."""

    agent_id: str
    key: str  # the call's ``action_dedup_key``
    tool_id: str
    params: str  # its recorded parameters as JSON, cut at ``CARRIED_PARAMS_MAX_CHARS``
    output: str  # its output as text, cut at ``CARRIED_RESULT_MAX_CHARS``


class CarriedResults:
    """BF-947 (M3): per item, the results of admitted calls that returned no error, in this process only: the newest
    ``CARRIED_RESULTS_MAX`` per item, oldest first; an entry replaces one with the same call key."""

    def __init__(self) -> None:
        self._by_item: dict[str, tuple[CarriedResult, ...]] = {}

    def for_agent(self, work_item_id: str, agent_id: str) -> tuple[CarriedResult, ...]:
        """The results kept on this item for ``agent_id``, oldest first."""
        return tuple(entry for entry in self._by_item.get(work_item_id, ()) if entry.agent_id == agent_id)

    def recorder(self, work_item_id: str) -> Callable[[str, Any, Any, Any], None]:
        """The ``ToolCallConfinement.record`` of one run of this item."""

        def record(agent_id: str, tool_id: Any, params: Any, result: Any) -> None:
            payload = approval_payload(tool_id, params, work_item_id)
            if payload is None or getattr(result, "error", None) is not None:
                return
            entry = CarriedResult(
                agent_id=agent_id,
                key=action_dedup_key(agent_id=agent_id, payload=payload, work_item_id=work_item_id),
                tool_id=payload["tool_id"],
                params=json.dumps(payload["params"], sort_keys=True, default=str)[:CARRIED_PARAMS_MAX_CHARS],
                output=str(getattr(result, "output", ""))[:CARRIED_RESULT_MAX_CHARS],
            )
            kept = tuple(old for old in self._by_item.get(work_item_id, ()) if old.key != entry.key)
            self._by_item[work_item_id] = (*kept, entry)[-CARRIED_RESULTS_MAX:]

        return record

    def forget(self, work_item_id: str) -> None:
        """Drop the results kept on an item."""
        self._by_item.pop(work_item_id, None)


def agent_work_approval(request: Any) -> dict[str, Any] | None:
    """The validated payload when ``request`` asks to make one tool call in one agent-created work item, else None.

    A1 (F1): one definition, ``capability_request.agent_work_call``, which the fulfilment predicate shares.
    """
    return agent_work_call(request)


def approval_payload(tool_id: Any, params: Any, work_item_id: str) -> dict[str, Any] | None:
    """The AD-1154 ``action`` payload that asks for one call, or None when the call cannot be recorded."""
    if type(tool_id) is not str or type(params) is not dict:
        return None
    recorded = {key: value for key, value in params.items() if key not in APPROVAL_UNRECORDED_PARAMS}
    return validate_action_payload({
        "tool_id": tool_id, "action": APPROVAL_ACTION, "params": recorded,
        "scope_key": APPROVAL_SCOPE_PREFIX + work_item_id, "session_id": None, "thread_id": "",
    })


def _provenance(item: WorkItem) -> dict[str, Any]:
    metadata = item.metadata if type(item.metadata) is dict else {}
    raw = metadata.get(AGENT_WORK_METADATA_KEY)
    return raw if type(raw) is dict else {}


def _origin_thread(item: WorkItem) -> str:
    """The Ward Room thread the work was asked in, or "" (a proactive thought, or no thread)."""
    origin = _provenance(item).get("origin")
    if type(origin) is not dict or origin.get("channel") != "ward_room":
        return ""
    thread_id = origin.get("thread_id")
    return thread_id if type(thread_id) is str else ""


def task_text(item: WorkItem, *, requester: str, now: float, carried: tuple[CarriedResult, ...] = ()) -> str:
    """What the run is asked: the colleague's request, its reason and its tool, ``now`` (an epoch time) as UTC, the
    ``carried`` results (BF-947), and the confinement in plain words."""
    provenance = _provenance(item)
    reason = provenance.get("reason") if type(provenance.get("reason")) is str else ""
    tool = provenance.get("tool_id") if type(provenance.get("tool_id")) is str else "the read-only tools you hold"
    details = f"{item.description}\n\n" if item.description and item.description != item.title else ""
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    earlier = "".join(f"- {entry.tool_id} {entry.params}: {entry.output}\n" for entry in carried)
    if earlier:
        earlier = (
            "Calls of this work that were approved and already ran, with their results (each cut at "
            f"{CARRIED_RESULT_MAX_CHARS:,} characters). Do not make them again:\n{earlier}\n"
        )
    return (
        f"Agent work {item.id}: {item.title}\n\n{details}"
        f"Asked by {requester}. Reason: {reason}. Tool named: {tool}.\n\n"
        f"Current UTC time: {stamp}.\n\n"
        f"{earlier}"
        "Read-only tools run directly. A call to another tool may be filed for approval instead of running; this work "
        "continues when no call you filed on it awaits a decision or its fulfilment, and ends if one of them is "
        "denied. Do the reading, then answer with what you found and the tool results you relied on. Your answer is "
        "posted where the work was asked for."
    )


def outcome_text(item: WorkItem, outcome: str, *, mentions: str, denial: str = "") -> str:
    """The post that tells the requester and watchers how the work came out (the echo-chamber rule included)."""
    head = f"{mentions} Agent work {item.id[:8]} (\"{item.title}\")"
    metadata = item.metadata if type(item.metadata) is dict else {}
    result = metadata.get(RESULT_METADATA_KEY)
    if type(result) is dict and type(result.get("answer")) is str:
        tools = ", ".join(name for name in result.get("tools", ()) if type(name) is str) or "none"
        trace = result.get("trace") if type(result.get("trace")) is str else ""
        evidence = f"Evidence: tools that answered: {tools}; their records are filed under work item {item.id}"
        evidence += f", trace {trace}" if trace else ""
        if outcome == "done":
            status = "is done"
        elif type(result.get("stopped")) is str:  # A1 (F4): the run stopped without a finished answer
            status = f"ended as {outcome}: {STOP_WORDS.get(result['stopped'], UNFINISHED_WORDS)}, after this answer"
        else:
            status = f"ended as {outcome}, after this answer"
        return (
            f"{head} {status}. {result.get('executor', 'A colleague')} reported:\n\n{result['answer']}\n\n"
            f"{evidence}. This is a colleague's report: check it against the record before you rely on it."
        )
    if outcome == OUTCOME_EXPIRED:
        return f"{head} expired before anyone produced a result. Ask again if it is still needed."
    if denial:
        return f"{head} was stopped: the Captain declined a step it needed. Reason: {denial}"
    if outcome == "failed":
        return f"{head} failed before it produced a result."
    return f"{head} ended as {outcome} without a result."


def _linked_calls(requests: Any, work_item_id: str, slot_id: str) -> list[Any]:
    """BF-947: the agent-work call requests ``slot_id`` filed on this item, oldest first."""
    return [
        request for request in requests_for_work_item(requests, work_item_id)
        if request.agent_id == slot_id and agent_work_approval(request) is not None
    ]


def _admissions(linked: list[Any], slot_id: str, work_item_id: str) -> dict[str, list[str]]:
    """BF-947 (M2): call key -> the ids of the fulfilled requests in ``linked`` that cover it, oldest first."""
    keys: dict[str, list[str]] = {}
    for request in linked:
        payload = agent_work_approval(request)
        if request.status == "fulfilled" and payload is not None:
            key = action_dedup_key(agent_id=slot_id, payload=payload, work_item_id=work_item_id)
            keys.setdefault(key, []).append(request.id)
    return keys


async def _cancel_or_park(store: Any, parking: Any, work_item_id: str, linked: list[Any]) -> bool:
    """BF-947 (M4): True when the item is not run now. The oldest denied request in ``linked`` moves it from
    in_progress to cancelled, with that request's decision reason as ``denial_reason``; else the oldest request in
    ``linked`` that is pending, or approved and not yet fulfilled, parks it on that request through
    ``block_on_request``."""
    denied = next((request for request in linked if request.status == "denied"), None)
    if denied is not None:
        moved = await store.transition_work_item(
            work_item_id, "cancelled", source=RUN_SOURCE, expected_status="in_progress",
            metadata_patch={"denial_reason": str(denied.decision_reason or "")},
        )
        if moved is not None:
            await _close_bookings(store, work_item_id, completed=False)
        return True
    waiting = next((request for request in linked if request.status in _UNDECIDED), None)
    if waiting is None:
        return False
    await parking.block_on_request(work_item_id=work_item_id, request_id=waiting.id, reason=BLOCKED_REASON)
    return True


async def _forget_if_ended(store: Any, carried: CarriedResults, work_item_id: str) -> None:
    """BF-947 A2 (F2): drop the results kept on an item that has ended or is gone. A call in flight when the item ended
    returns after the terminal event dropped them and is recorded then, so ``_run`` calls this after its executor
    returns and in its failure handler. Never raises: when the item cannot be read, its results stay (L12)."""
    try:
        latest = await store.get_work_item(work_item_id)
    except Exception:
        logger.warning(
            "BF-947: work item %s could not be read after its run; the results kept on it stay", work_item_id,
            exc_info=True,
        )
        return
    if latest is None or latest.status in TERMINAL_STATUSES:
        carried.forget(work_item_id)


async def _denial_reason(requests: Any, item: WorkItem) -> str:
    """The reason recorded with a denied agent-work request of this item, else "": first the request the item was
    parked on, then (BF-947) the requests its assignee filed on it, oldest first.

    Read from the request, not the item: AD-855 writes ``denial_reason`` only after the cancel this notice follows.
    """
    metadata = item.metadata if type(item.metadata) is dict else {}
    request_id = metadata.get("capability_request_id")
    candidates: list[Any] = []
    if type(request_id) is str and request_id:
        candidates.append(await requests.get(request_id))
    if type(item.assigned_to) is str and item.assigned_to:
        candidates.extend(_linked_calls(requests, item.id, item.assigned_to))
    for request in candidates:
        if request is not None and request.status == "denied" and agent_work_approval(request) is not None:
            return str(request.decision_reason or "no reason recorded")[:MAX_REASON_CHARS]
    return ""


async def _close_bookings(store: Any, work_item_id: str, *, completed: bool) -> None:
    """A finished item's live booking is completed (done) or cancelled, so its claimant's capacity is freed."""
    for booking in await store.list_bookings(work_item_id=work_item_id):
        if booking.status in ("completed", "cancelled"):
            continue
        if completed and booking.status in ("active", "scheduled"):
            await store.complete_booking(booking.id)
        else:
            await store.cancel_booking(booking.id)


def ttl_words(seconds: int) -> str:
    """The TTL as a notice states it, never rounded (A1, F13): whole hours, else whole minutes, else seconds."""
    for unit, size in (("h", 3_600), ("min", 60)):
        if seconds >= size and seconds % size == 0:
            return f"{seconds // size} {unit}"
    return f"{seconds} s"


async def _record_outcome(store: Any, item: WorkItem, executor: str, outcome: Any) -> None:
    """A1 (F4): how a run that neither filed a call nor was parked is recorded. Done only when the executor completed
    with an answer; any other stop (its step limit, its token budget, an error, an empty answer) is failed, with the
    reason the report names. The result goes with the status in one write; an item the TTL ended meanwhile keeps its
    end and gains the result (register R3)."""
    answer = (outcome.final_text or "").strip()[:REPORT_MAX_CHARS]
    stopped = outcome.stopped_reason if type(outcome.stopped_reason) is str else ""
    finished = stopped == "complete" and bool(answer)
    invocations = getattr(outcome, "tool_invocations", None)
    result: dict[str, Any] = {
        "executor": executor,
        "answer": answer or "(no answer text)",
        "tools": sorted(getattr(invocations, "succeeded", ()) or ()),
        "trace": outcome.tool_trace_ref or "",
    }
    if not finished:
        result["stopped"] = stopped or "unknown"
    status = "done" if finished else "failed"
    moved = await store.transition_work_item(
        item.id, status, source=RUN_SOURCE, expected_status="in_progress", metadata_patch={RESULT_METADATA_KEY: result},
    )
    if moved is None:
        current = await store.get_work_item(item.id)
        if current is not None and current.status in TERMINAL_STATUSES:
            await store.transition_work_item(
                item.id, current.status, source=RUN_SOURCE, expected_status=current.status,
                metadata_patch={RESULT_METADATA_KEY: result},
            )
    await _close_bookings(store, item.id, completed=moved is not None and finished)


class AgentWorkRunner:
    """Ship's Computer: runs agent-created work in its assignee's agentic loop and reports it (AD-1347 S3)."""

    def __init__(
        self,
        *,
        service: AgentWorkService,
        store: Any,
        ward_room: Any,
        tools: Any,
        requests: Any,
        parking: Any,
        executor: WorkItemAgenticExecutor,
        runtime: Any,
        agents: Any,
        callsign_of: Callable[[str], str],
        max_pending: int = 20,
        ttl_seconds: int = 86_400,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if any(value is None for value in (service, store, ward_room, tools, requests, parking, executor, agents)):
            raise ValueError("agent_work_runner_dependencies_required")
        self._service = service
        self._store = store
        self._ward_room = ward_room
        self._tools = tools
        self._requests = requests
        self._parking = parking
        self._executor = executor
        self._runtime = runtime  # passed through to each run only (the executor reads its stores from it)
        self._agents = agents
        self._callsign_of = callsign_of
        self._max_pending = max_pending
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._tasks: set[asyncio.Task[None]] = set()
        self._active: set[str] = set()
        self._restart: set[str] = set()  # A1 (F2): starts that arrived while the item ran; made when that run ends
        self.carried = CarriedResults()  # BF-947 (M3)
        self._deliver_lock = asyncio.Lock()
        self._stopping = False

    @property
    def running(self) -> tuple[asyncio.Task[None], ...]:
        """The runs in flight (``stop`` cancels them; a test awaits them)."""
        return tuple(self._tasks)

    async def on_store_event(self, event: Any) -> None:
        """The work store's events: created and claimed agent work starts, ended work is reported. Never raises."""
        try:
            raw_type = event.get("type") if type(event) is dict else None
            kind = getattr(raw_type, "value", raw_type)
            data = event.get("data") if type(event) is dict else None
            raw = data.get("work_item") if type(data) is dict else None
            work_item_id = raw.get("id") if type(raw) is dict else None
            if kind not in _HANDLED_EVENTS or type(work_item_id) is not str or not work_item_id:
                return
            item = await self._store.get_work_item(work_item_id)
            record = read_agent_work(item) if item is not None else None
            if item is None or record is None:
                return
            if kind == EventType.WORK_ITEM_STATUS_CHANGED.value:
                if item.status in TERMINAL_STATUSES:
                    self.carried.forget(item.id)  # BF-947
                    await _close_bookings(self._store, item.id, completed=item.status == "done")
                    await self.deliver_due_notices()
            elif kind == EventType.WORK_ITEM_CREATED.value and record.kind == KIND_REQUEST:
                await self._announce(item, record)
            elif kind == EventType.WORK_ITEM_CREATED.value or record.kind == KIND_REQUEST:
                self._start(item.id)
        except Exception:
            logger.warning(
                "AD-1347: an agent-work event could not be handled; the board is unchanged and the next start's "
                "recovery retries it", exc_info=True,
            )

    async def claim(self, actor: str, work_item_id: str) -> tuple[str, str]:
        """CLAIM_WORK: claim through the tool sink (the stop at ``tool``, the claim tool's rank, AD-1187's compare and
        set, S1's eligibility gate), then run. Returns (outcome, what the claimant is told)."""
        member = self._service.crew_member(actor)
        short = work_item_id[:8]
        if member is None:
            return "refused", f"work item {short} was not claimed: you are not a live crew member"
        try:
            result = await self._tools.check_and_invoke(
                member.slot_id, "claim_work_item", {"work_item_id": work_item_id}, required=ToolPermission.WRITE,
                agent_department=member.department, agent_rank=member.rank, agent_types=[member.agent_type],
                context={"agent_id": member.slot_id, "_tool_result_presentation": _PRESENTATION},
            )
            claimed = result.error is None
        except Exception:
            logger.info("AD-1347: %s could not claim work item %s through the tool", member.slot_id, short, exc_info=True)
            claimed = False
        claimed_item = await self._store.get_work_item(work_item_id) if claimed else None
        if claimed_item is None or claimed_item.assigned_to != member.slot_id:
            return "not_claimed", f"work item {short} was not claimed by you: it is taken, closed, or not yours to serve"
        self._start(claimed_item.id)
        return "claimed", f"you claimed work item {short} (\"{claimed_item.title}\"); it runs now and its result is posted where it was asked"

    async def decline(self, actor: str, work_item_id: str, reason: str) -> tuple[str, str]:
        """DECLINE_WORK: a member of the request's department says why it is not theirs, once; the requester is told in
        the thread the work was asked in. The request stays open for the rest of the department."""
        member = self._service.crew_member(actor)
        short = work_item_id[:8]
        item = await self._store.get_work_item(work_item_id)
        record = read_agent_work(item) if item is not None else None
        if (
            member is None or item is None or record is None or record.kind != KIND_REQUEST
            or item.status != "open" or member.department != record.department
        ):
            return "refused", f"work item {short} is not an open request to your department"
        if not await self._store.claim_work_notice(item.id, member.slot_id, NOTICE_DECLINE, self._clock()):
            return "repeated", f"you already declined work item {short}"
        why = " ".join(reason.split())[:MAX_REASON_CHARS] or "no reason given"
        # A1 (F8): the requester and every watcher of a deduplicated request; posted once (the decline is claimed above).
        recipients = await self._service.notice_recipients(item.id)
        names = [self._callsign_of(slot) for slot in recipients]
        mentions = " ".join(f"@{name}" for name in names)
        posted = await self._post(item, record, f"{mentions} {self._callsign_of(member.slot_id)} declined work item {short} (\"{item.title}\"): {why}")
        told = ", ".join(names)
        if not posted:  # A1 (F9, the literal): a post that did not go through is not "told"
            return "declined", f"you declined work item {short}; the notice to {told} could not be posted"
        return "declined", f"you declined work item {short}; {told} {'was' if len(names) == 1 else 'were'} told"

    async def resume(self, work_item_id: str) -> None:
        """AD-855 resumed a parked item (its request settled): run it again."""
        self._start(work_item_id)

    async def recover(self) -> int:
        """At start: run again every agent-created item a previous run left assigned and unfinished (a parked item
        waits for its request), then send the notices it owed. Idempotent; returns how many runs it started."""
        started = 0
        for open_item in await self._store.list_agent_work(True, None, SCAN_LIMIT):
            if open_item.assigned_to is None or open_item.status == "blocked":
                continue
            self._start(open_item.id)
            started += 1
        await self.deliver_due_notices()
        return started

    async def deliver_due_notices(self) -> int:
        """Tell each requester and watcher how ended agent work came out: one post per item, naming everyone newly
        told. A notice is claimed before it is sent (S1), so overlapping deliveries and a restart send it at most once.
        Returns how many recipients were told."""
        async with self._deliver_lock:
            grouped: dict[str, list[AgentWorkNotice]] = {}
            for notice in await self._service.terminal_notices_due():
                grouped.setdefault(notice.work_item_id, []).append(notice)
            told = 0
            for work_item_id, notices in grouped.items():
                item = await self._store.get_work_item(work_item_id)
                record = read_agent_work(item) if item is not None else None
                if item is None or record is None:
                    continue
                claimed = [notice.recipient for notice in notices if await self._service.claim_notice(work_item_id, notice.recipient)]
                if not claimed:
                    continue
                mentions = " ".join(f"@{self._callsign_of(recipient)}" for recipient in claimed)
                body = outcome_text(item, notices[0].outcome, mentions=mentions, denial=await _denial_reason(self._requests, item))
                if await self._post(item, record, body):
                    told += len(claimed)
            return told

    async def stop(self) -> None:
        """Shutdown: start nothing more, cancel the runs in flight and wait for them (``recover`` restarts them)."""
        self._stopping = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _start(self, work_item_id: str) -> None:
        """Run one item in the background, at most once at a time in this process.

        A1 (F2): a start that arrives while the item runs (an approval that settled before the run parked, through
        BF-878, or a duplicate event) is kept and made when that run ends; that run re-reads the item, so a finished or
        parked one does nothing. A stopped runner starts and keeps nothing: the next start's ``recover`` runs what is left.
        """
        if self._stopping:
            return
        if work_item_id in self._active:
            self._restart.add(work_item_id)
            return
        self._active.add(work_item_id)
        task = asyncio.create_task(self._run(work_item_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, work_item_id: str) -> None:
        """One confined run of one item, then return it to the board, park it, or record how it ended. Never raises
        (a cancellation from ``stop`` excepted); a failure marks the item failed, which its requester is told.

        A1 (review round 1): a request's eligibility is asked again first (F5); a run that filed a call parks on it and
        one the executor parked itself stays parked (F3); only a completed run with an answer is done (F4,
        ``_record_outcome``); a start that arrived during this run is made when it ends (F2). BF-947: before the agent
        runs, ``_cancel_or_park`` cancels the item on a denied call or parks it on an undecided one.
        """
        try:
            item = await self._store.get_work_item(work_item_id)
            record = read_agent_work(item) if item is not None else None
            if item is None or record is None or item.assigned_to is None or item.status in TERMINAL_STATUSES:
                return
            if item.status == "blocked":
                return
            slot = item.assigned_to
            if not self._service.execution_allowed(item, slot):
                if record.kind == KIND_REQUEST:
                    await self._store.unassign_work_item(item.id, reason="the claimant may not run it now")
                return
            if not await self._begin(item):
                return
            linked = _linked_calls(self._requests, item.id, slot)
            if await _cancel_or_park(self._store, self._parking, item.id, linked):
                return
            from probos.cognitive.agentic_dispatch import ToolCallConfinement

            agent = self._agents.get(slot)
            filed: list[str] = []
            confinement = ToolCallConfinement(
                AGENT_WORK_READ_TOOL_IDS, self._gate_for(item.id, _admissions(linked, slot, item.id), filed),
                record=self.carried.recorder(item.id),
            )
            try:
                outcome = await self._executor.run(
                    agent_id=slot, instructions=str(getattr(agent, "instructions", "") or ""),
                    task_text=task_text(
                        item, requester=self._callsign_of(record.requester), now=self._clock(),
                        carried=self.carried.for_agent(item.id, slot),
                    ),
                    runtime=self._runtime, failure_scope=item.id,
                    work_item_id_provider=lambda: item.id, confinement=confinement,
                )
            except AgentStopped:
                if record.kind == KIND_REQUEST:
                    await self._store.unassign_work_item(item.id, reason="the claimant was stopped by the Captain")
                return
            # BF-947 A2 (F2): a call in flight when the item ended was recorded after the terminal event dropped the
            # item's results; no call of this run is in flight now.
            await _forget_if_ended(self._store, self.carried, item.id)
            # A1 (F5): before the park, so a claimant stopped (or that lost the tool) after it filed a call is released,
            # never parked; a call it filed stays on the Captain's queue: AD-855 acts only on an item parked on that
            # request, and a run admits only calls its own assignee filed (BF-947).
            if record.kind == KIND_REQUEST and not self._service.execution_allowed(item, slot):
                await self._store.unassign_work_item(item.id, reason="the claimant was stopped or lost the tool during the run")
                return
            if filed:
                await self._parking.block_on_request(work_item_id=item.id, request_id=filed[0], reason=BLOCKED_REASON)
                return
            if outcome.parked_request_id:
                return  # A1 (F3): AD-1324 parked the item on its own tier-floor ask; that decision resumes it
            await _record_outcome(self._store, item, self._callsign_of(slot), outcome)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "AD-1347: the run of agent work item %s failed; it is marked failed and its requester is told",
                work_item_id, exc_info=True,
            )
            try:
                if await self._store.transition_work_item(
                    work_item_id, "failed", source=RUN_SOURCE, expected_status="in_progress",
                ) is not None:
                    await _close_bookings(self._store, work_item_id, completed=False)
            except Exception:
                logger.warning("AD-1347: work item %s could not be marked failed; it stays in_progress", work_item_id, exc_info=True)
            # BF-947 A2 (F2): an item that ended while the run was failing gets no event from the transition above.
            await _forget_if_ended(self._store, self.carried, work_item_id)
        finally:
            self._active.discard(work_item_id)
            if work_item_id in self._restart:  # A1 (F2): a start that arrived during this run runs now
                self._restart.discard(work_item_id)
                self._start(work_item_id)

    async def _begin(self, item: WorkItem) -> bool:
        """Move the item to in_progress once: a claimed request starts its booking; a self-task or an assignment
        moves from open; a resumed item is in_progress already."""
        if item.status == "in_progress":
            return True
        if item.status == "scheduled":
            bookings = [
                booking for booking in await self._store.list_bookings(work_item_id=item.id, status="scheduled")
                if booking.resource_id == item.assigned_to
            ]
            return len(bookings) == 1 and await self._store.start_booking(bookings[0].id) is not None
        if item.status == "open":
            moved = await self._store.transition_work_item(item.id, "in_progress", source=RUN_SOURCE, expected_status="open")
            return moved is not None
        return False

    def _gate_for(
        self, work_item_id: str, admissions: dict[str, list[str]], filed: list[str],
    ) -> Callable[[str, Any, Any], Awaitable[str]]:
        """The run's confinement gate, in this order. A call that cannot be recorded is refused. A call whose result
        this runner keeps on the item for the agent is answered and does not run (BF-947). A call a fulfilled request
        in ``admissions`` covers is admitted, once per request; with each such request used, it goes on as any other
        call. Any other call is refused when the agent has ``max_pending`` or more pending requests, else filed for
        approval (refused when the filing returns no request)."""
        from probos.cognitive.agentic_dispatch import (
            CONFINEMENT_ADMIT,
            CONFINEMENT_ANSWERED,
            CONFINEMENT_FILED,
            CONFINEMENT_REFUSED,
        )

        async def gate(agent_id: str, tool_id: Any, params: Any) -> str:
            payload = approval_payload(tool_id, params, work_item_id)
            if payload is None:
                return CONFINEMENT_REFUSED
            key = action_dedup_key(agent_id=agent_id, payload=payload, work_item_id=work_item_id)
            if any(entry.key == key for entry in self.carried.for_agent(work_item_id, agent_id)):
                return CONFINEMENT_ANSWERED
            for request_id in admissions.get(key, ()):
                if await self._store.claim_work_notice(
                    work_item_id, agent_id, APPROVAL_USE_PREFIX + request_id, self._clock(),
                ):
                    return CONFINEMENT_ADMIT
            if self._requests.count_pending_sync(agent_id) >= self._max_pending:
                return CONFINEMENT_REFUSED
            request = await self._requests.file_action_request(
                agent_id, payload, rationale=f"agent work {work_item_id[:8]} called {tool_id}, outside the read-only set",
                work_item_id=work_item_id,
            )
            if request is None or not getattr(request, "id", ""):
                return CONFINEMENT_REFUSED
            if request.id not in filed:
                filed.append(request.id)
            return CONFINEMENT_FILED

        return gate

    async def _announce(self, item: WorkItem, record: AgentWorkRecord) -> int:
        """The activation notice: once per eligible member of the request's department, in that department's channel,
        with routing held to the members named (``max_responders``). Returns how many were told."""
        if record.tool_id is None or item.status != "open":
            return 0
        fresh: list[str] = []
        for member in self._service.eligible_members(record.tool_id):
            if member.department != record.department or member.slot_id == record.requester:
                continue
            if await self._store.claim_work_notice(item.id, member.slot_id, NOTICE_ACTIVATION, self._clock()):
                fresh.append(member.slot_id)
        if not fresh:
            return 0
        reason = _provenance(item).get("reason", "")
        body = (
            " ".join(f"@{self._callsign_of(slot)}" for slot in fresh)
            + f" {self._callsign_of(record.requester)} asks {record.department} for work with {record.tool_id}: "
            f"\"{item.title}\". Reason: {reason}. Work item {item.id}. To take it, reply in this thread with "
            f"[CLAIM_WORK {item.id}]. If it is not yours to do, reply with [DECLINE_WORK {item.id}] and your reason, "
            f"then [/DECLINE_WORK]. The first claim wins; it expires {ttl_words(self._ttl_seconds)} after it was asked."
        )
        try:
            channel = await self._ward_room.get_channel_by_department(record.department)
            if channel is None:
                logger.warning("AD-1347: no %s channel for the notice of work item %s; its TTL is the backstop", record.department, item.id[:8])
                return 0
            await self._ward_room.create_thread(
                channel_id=channel.id, author_id=SHIP_COMPUTER_ID, title=f"[Work request] {item.title}"[:200],
                body=body, author_callsign=SHIP_COMPUTER_CALLSIGN, max_responders=len(fresh),
            )
        except Exception:
            logger.warning("AD-1347: the notice of work item %s was not posted; its TTL is the backstop", item.id[:8], exc_info=True)
            return 0
        return len(fresh)

    async def _post(self, item: WorkItem, record: AgentWorkRecord, body: str) -> bool:
        """Post in the thread the work was asked in; with none (a proactive thought, a pruned or locked thread), in the
        department channel of the work. Authored by the Ship's Computer; the text names who did what. Never raises."""
        thread_id = _origin_thread(item)
        if thread_id:
            try:
                await self._ward_room.create_post(
                    thread_id=thread_id, author_id=SHIP_COMPUTER_ID, body=body, author_callsign=SHIP_COMPUTER_CALLSIGN,
                )
                return True
            except Exception:
                logger.info(
                    "AD-1347: thread %s could not take the post for work item %s; it goes to the %s channel",
                    thread_id[:8], item.id[:8], record.department, exc_info=True,
                )
        try:
            channel = await self._ward_room.get_channel_by_department(record.department)
            if channel is None:
                logger.warning("AD-1347: no %s channel for the post of work item %s; it was not posted", record.department, item.id[:8])
                return False
            await self._ward_room.create_thread(
                channel_id=channel.id, author_id=SHIP_COMPUTER_ID, title=f"[Agent work] {item.title}"[:200],
                body=body, author_callsign=SHIP_COMPUTER_CALLSIGN,
            )
            return True
        except Exception:
            logger.warning("AD-1347: the post for work item %s was not made", item.id[:8], exc_info=True)
            return False


async def resume_agent_work(runtime: Any, item: Any) -> bool:
    """AD-855's resume of agent-created work: through its runner, never the WorkItemRouter (which drops it). False for
    any other item, which AD-855 resumes as before. Never raises."""
    if read_agent_work(item) is None:
        return False
    runner = getattr(runtime, "agent_work_runner", None)
    if type(runner) is not AgentWorkRunner:
        logger.warning(
            "AD-1347: agent work item %s was resumed but no agent-work runner is wired; it stays in_progress until the "
            "next start's recovery runs it", getattr(item, "id", "?"),
        )
        return True
    await runner.resume(item.id)
    return True
