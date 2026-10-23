"""AD-1347 S1 (#1627): the Ship's Computer service that owns the work crew agents create.

Authority (D2). A crew agent may create work for itself. A chief may assign work to a member of its
own department. Any other target, a peer or another department, is never an assignment: it becomes
an unassigned request published to one department that holds the named tool (AD-1187 department
scope), and an eligible member claims it.

Eligibility (D3) is the tool registry's own answer for each member: ``check_permission`` at read
level with the member's id, department, rank and agent type, so AD-423b's department scope,
``restricted_to``, rank matrix and the Captain's grants and restrictions all apply. It is asked when
a request is created and again at every discovery and every new claim (``claim_allowed``, the store's
gate). A same-owner replay of a claim already persisted is AD-1187's receipt and acquires nothing, so the
store does not ask again; S3 asks before it runs anything (Amendment A3).
An unregistered or disabled tool has no eligible member.

Provenance (D7) sits under ``metadata["agent_work"]``: never a top-level ``thread_id`` and never a
``parent_id``, because ``WorkItemStore._standalone_pull_item`` refuses either and the request would
reach nobody. The origin is a back-reference that says where S3 reports, not room ownership in the
AD-1187 sense: no room scopes, owns or receives the work. Depth is read from the parent item's
stored record, never taken from the caller.

S1 creates and governs; it runs nothing, and nothing calls it until S2. Expiry is the store's own
TTL sweep (``WorkItemStore._expire_ttl_items``); this service holds no loop. It never calls AD-1346's
``decide``, issues no ticket and widens no tool's departments or ranks.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from probos.agent_stop import SEAM_AGENT_WORK, STOP_REASON_CODE, StopRecord, active_stop, standing_stop
from probos.tools.protocol import ToolPermission
from probos.workforce import AGENT_WORK_METADATA_KEY, BookableResource, WorkItem

if TYPE_CHECKING:
    from probos.agent_stop import AgentStopService
    from probos.config import AgentWorkConfig
    from probos.identity_service import IdentityRef
    from probos.workforce import WorkItemStore

logger = logging.getLogger(__name__)

AGENT_WORK_VERSION: Final = 1
AGENT_WORK_TAG: Final = "agent_work"
KIND_SELF: Final = "self"
KIND_ASSIGNMENT: Final = "assignment"
KIND_REQUEST: Final = "request"
KINDS: Final[tuple[str, ...]] = (KIND_SELF, KIND_ASSIGNMENT, KIND_REQUEST)
NOTICE_TERMINAL: Final = "terminal"
OUTCOME_EXPIRED: Final = "expired"
ORIGIN_CHANNELS: Final[frozenset[str]] = frozenset({"ward_room", "dm", "proactive", "agent_work"})
MAX_TITLE_CHARS: Final = 200
MAX_DESCRIPTION_CHARS: Final = 4_000
MAX_REASON_CHARS: Final = 500
MAX_ID_CHARS: Final = 128
RATE_WINDOW_SECONDS: Final = 3_600
#: Rows read per volume check. A page this full means more agent work is on the board than any valid
#: configuration allows open, so the create is refused rather than counted short.
SCAN_LIMIT: Final = 2_000

REFUSAL_INVALID: Final = "invalid_request"
REFUSAL_UNRESOLVED: Final = "requester_unresolved"
REFUSAL_PARENT_UNKNOWN: Final = "parent_unknown"
REFUSAL_DEPTH: Final = "depth_exceeded"
REFUSAL_TOOL_UNAVAILABLE: Final = "tool_unavailable"
REFUSAL_REQUESTER_NOT_ELIGIBLE: Final = "requester_not_eligible"
REFUSAL_REQUESTER_HOLDS_TOOL: Final = "requester_holds_tool"
REFUSAL_ASSIGNEE_UNKNOWN: Final = "assignee_unknown"
REFUSAL_ASSIGNEE_STOPPED: Final = "assignee_stopped"
REFUSAL_ASSIGNEE_NOT_ELIGIBLE: Final = "assignee_not_eligible"
REFUSAL_DEPARTMENT_NOT_ELIGIBLE: Final = "department_not_eligible"
REFUSAL_NO_ELIGIBLE_MEMBER: Final = "no_eligible_member"
REFUSAL_RATE: Final = "rate_limited"
REFUSAL_AGENT_CAP: Final = "agent_cap_reached"
REFUSAL_DEPARTMENT_CAP: Final = "department_cap_reached"
REFUSAL_SHIP_CAP: Final = "ship_cap_reached"
#: Every code a refused create can carry (the stop's own code included), in the order the checks run.
REFUSAL_CODES: Final[tuple[str, ...]] = (
    REFUSAL_INVALID, REFUSAL_UNRESOLVED, STOP_REASON_CODE, REFUSAL_PARENT_UNKNOWN, REFUSAL_DEPTH,
    REFUSAL_TOOL_UNAVAILABLE, REFUSAL_REQUESTER_NOT_ELIGIBLE, REFUSAL_ASSIGNEE_UNKNOWN,
    REFUSAL_ASSIGNEE_STOPPED, REFUSAL_ASSIGNEE_NOT_ELIGIBLE, REFUSAL_REQUESTER_HOLDS_TOOL,
    REFUSAL_DEPARTMENT_NOT_ELIGIBLE, REFUSAL_NO_ELIGIBLE_MEMBER, REFUSAL_RATE, REFUSAL_AGENT_CAP,
    REFUSAL_DEPARTMENT_CAP, REFUSAL_SHIP_CAP,
)


def _encodable(value: str) -> bool:
    """Whether ``value`` encodes as UTF-8 (Amendment A3).

    A JSON body can decode to a str holding an unpaired surrogate. SQLite's bind and the dedup key's sha256 refuse
    such a str with an exception, and a field that reaches neither would be stored as poisoned provenance, so every
    text and id input passes this check before any lookup or write.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _text(value: object, limit: int, *, required: bool) -> str | None:
    """The stripped text, or None when it is not an exact str, is blank where required, is too long, or is not UTF-8."""
    if type(value) is not str:
        return None
    stripped = value.strip()
    if (required and not stripped) or len(stripped) > limit or not _encodable(stripped):
        return None
    return stripped


def _identifier(value: object) -> bool:
    """An exact str of 1 to 128 characters with no surrounding whitespace that encodes as UTF-8."""
    return type(value) is str and 1 <= len(value) <= MAX_ID_CHARS and value.strip() == value and _encodable(value)


def normalize_title(title: str) -> str:
    """The dedup form of a title: Unicode NFKC, case-folded, every whitespace run one space, stripped."""
    return " ".join(unicodedata.normalize("NFKC", title).casefold().split())


def dedup_key(department: str, tool_id: str, title: str) -> str:
    """sha256 over the department, the tool and the normalised title, joined by the unit separator."""
    material = "\x1f".join((department, tool_id, normalize_title(title)))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AgentWorkOrigin:
    """Where the need was found: the channel and, when there is one, the thread and post (S3 reports there)."""

    channel: str
    thread_id: str = ""
    post_id: str = ""

    def __post_init__(self) -> None:
        if type(self.channel) is not str or self.channel not in ORIGIN_CHANNELS:
            raise ValueError("agent_work_origin_channel_invalid")
        for value in (self.thread_id, self.post_id):
            if type(value) is not str or len(value) > MAX_ID_CHARS or value.strip() != value or not _encodable(value):
                raise ValueError("agent_work_origin_id_invalid")

    def to_dict(self) -> dict[str, str]:
        """The stored form, under ``metadata["agent_work"]["origin"]``."""
        return {"channel": self.channel, "thread_id": self.thread_id, "post_id": self.post_id}


@dataclass(frozen=True)
class CrewMember:
    """One live crew member as the tool registry judges it: slot id, agent type, department, rank, chief."""

    slot_id: str
    agent_type: str
    department: str
    rank: str
    chief_slot_id: str | None = None


@dataclass(frozen=True)
class AgentWorkRecord:
    """The provenance under ``metadata["agent_work"]``, as ``read_agent_work`` reads it back."""

    kind: str
    requester: str
    depth: int
    department: str
    tool_id: str | None
    dedup_key: str | None


@dataclass(frozen=True)
class AgentWorkCreated:
    """A created item, or the open request a create matched (``deduplicated``); ``notify`` is for S3's notice."""

    work_item: WorkItem
    kind: str
    deduplicated: bool = False
    converted: bool = False
    notify: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentWorkRefusal:
    """A refused create: a stable ``code`` from ``REFUSAL_CODES`` and a reason the requester may read."""

    code: str
    detail: str = ""


@dataclass(frozen=True)
class AgentWorkNotice:
    """One terminal notice due: the item, who hears it, and its outcome (``expired`` or the item's status)."""

    work_item_id: str
    recipient: str
    outcome: str


def read_agent_work(item: WorkItem) -> AgentWorkRecord | None:
    """The item's agent-work provenance, or None when it has none or it is malformed.

    Total over JSON-decoded metadata: it reads only dicts, strs and ints and never raises for them.
    """
    metadata = item.metadata if type(item.metadata) is dict else {}
    raw = metadata.get(AGENT_WORK_METADATA_KEY)
    if type(raw) is not dict or type(raw.get("version")) is not int or raw["version"] != AGENT_WORK_VERSION:
        return None
    kind, requester, depth = raw.get("kind"), raw.get("requester"), raw.get("depth")
    department, tool_id, key = raw.get("department"), raw.get("tool_id"), raw.get("dedup_key")
    if (
        type(kind) is not str or kind not in KINDS
        or not _identifier(requester)
        or type(depth) is not int or depth < 1
        or type(department) is not str or not department
        or (tool_id is not None and not _identifier(tool_id))
        or (key is not None and type(key) is not str)
    ):
        return None
    return AgentWorkRecord(kind, requester, depth, department, tool_id, key)


def _requested_by(item: WorkItem, slot_id: str) -> bool:
    record = read_agent_work(item)
    return record is not None and record.requester == slot_id


class AgentWorkStore(Protocol):
    """The ``WorkItemStore`` methods the service uses."""

    async def create_work_item(self, **kwargs: Any) -> WorkItem: ...
    async def get_work_item(self, work_item_id: str) -> WorkItem | None: ...
    async def list_agent_work(self, open_only: bool, created_since: float | None, limit: int) -> list[WorkItem]: ...
    async def add_work_watcher(self, work_item_id: str, agent_id: str, added_at: float) -> bool: ...
    async def list_work_watchers(self, work_item_id: str) -> tuple[str, ...]: ...
    async def claim_work_notice(self, work_item_id: str, recipient: str, kind: str, claimed_at: float) -> bool: ...
    async def list_due_work_notices(self, kind: str, limit: int) -> list[tuple[str, str]]: ...


class ToolPermissionView(Protocol):
    """The ``ToolRegistry`` reads eligibility needs: the registration and AD-423b's permission answer."""

    def get(self, tool_id: str) -> Any: ...

    def check_permission(
        self, agent_id: str, tool_id: str, required: ToolPermission, *,
        agent_department: str | None = None, agent_rank: str = "ensign", agent_types: list[str] | None = None,
    ) -> bool: ...


class IdentityResolver(Protocol):
    """``IdentityService.resolve`` (AD-1346 M1a): any identity form to its slot's ref, or None."""

    def resolve(self, key: str) -> IdentityRef | None: ...


class CrewDirectory(Protocol):
    """The live crew; ``probos.cognitive.crew_directory.RuntimeCrewDirectory`` in production."""

    def members(self) -> tuple[CrewMember, ...]: ...
    def member(self, slot_id: str) -> CrewMember | None: ...


def _registered(tools: ToolPermissionView, tool_id: str) -> bool:
    registration = tools.get(tool_id)
    return registration is not None and registration.enabled is True


class AgentWorkService:
    """Ship's Computer service: creates and governs the work crew agents create (AD-1347 S1)."""

    def __init__(
        self,
        *,
        config: AgentWorkConfig,
        store: AgentWorkStore,
        tools: ToolPermissionView,
        identities: IdentityResolver,
        directory: CrewDirectory,
        stop_gate: AgentStopService,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if any(value is None for value in (config, store, tools, identities, directory, stop_gate)):
            raise ValueError("agent_work_dependencies_required")
        self._config = config
        self._store = store
        self._tools = tools
        self._identities = identities
        self._directory = directory
        self._stop_gate = stop_gate
        self._clock = clock
        self._lock = asyncio.Lock()

    async def create_self_task(
        self,
        requester: str,
        *,
        title: str,
        description: str,
        reason: str,
        origin: AgentWorkOrigin,
        tool_id: str | None = None,
        spawned_from: str | None = None,
    ) -> AgentWorkCreated | AgentWorkRefusal:
        """Work an agent schedules for itself, assigned to it; it runs later in its own agentic loop (S3).

        ``tool_id`` is checked with the other input, before any lookup or the Captain's stop (A4).
        """
        if tool_id is not None and not _identifier(tool_id):
            return AgentWorkRefusal(REFUSAL_INVALID, "the tool is not a valid id")
        admitted = await self._admit(requester, title, description, reason, origin, spawned_from)
        if isinstance(admitted, AgentWorkRefusal):
            return admitted
        member, ref, depth = admitted
        if tool_id is not None:
            if not _registered(self._tools, tool_id):
                return AgentWorkRefusal(REFUSAL_TOOL_UNAVAILABLE, f"{tool_id} is not a registered, enabled tool")
            if not self._holds_tool(member, tool_id):
                return AgentWorkRefusal(REFUSAL_REQUESTER_NOT_ELIGIBLE, f"you cannot use {tool_id}; request it")
        return await self._commit(
            member, ref, KIND_SELF, depth, title, description, reason, origin, tool_id,
            department=member.department, assignee=member.slot_id, spawned_from=spawned_from,
        )

    async def request_work(
        self,
        requester: str,
        *,
        title: str,
        description: str,
        reason: str,
        origin: AgentWorkOrigin,
        tool_id: str,
        assignee: str | None = None,
        department: str | None = None,
        spawned_from: str | None = None,
    ) -> AgentWorkCreated | AgentWorkRefusal:
        """Work for a colleague: a chief's own department member is assigned it; anyone else's becomes a request.

        A request is published to one department holding ``tool_id``: ``department`` when given (refused when no
        member there is eligible), else the named assignee's department when eligible, else the department with the
        most eligible members (ties by name). An open request with the same department, tool and normalised title is
        returned instead, and the requester becomes its watcher.

        The ids are checked with the other input, before any lookup or the Captain's stop (A4).
        """
        if (
            not _identifier(tool_id)
            or (assignee is not None and not _identifier(assignee))
            or (department is not None and not _identifier(department))
        ):
            return AgentWorkRefusal(REFUSAL_INVALID, "the tool, assignee or department is not a valid id")
        admitted = await self._admit(requester, title, description, reason, origin, spawned_from)
        if isinstance(admitted, AgentWorkRefusal):
            return admitted
        member, ref, depth = admitted
        if not _registered(self._tools, tool_id):
            return AgentWorkRefusal(REFUSAL_TOOL_UNAVAILABLE, f"{tool_id} is not a registered, enabled tool")
        target: CrewMember | None = None
        if assignee is not None:
            named = self._identities.resolve(assignee)
            target = self._directory.member(named.slot_id) if named is not None else None
            if target is None:
                return AgentWorkRefusal(REFUSAL_ASSIGNEE_UNKNOWN, "the named colleague is not a live crew member")
            if target.slot_id == member.slot_id:
                if not self._holds_tool(member, tool_id):
                    return AgentWorkRefusal(REFUSAL_REQUESTER_NOT_ELIGIBLE, f"you cannot use {tool_id}; request it")
                return await self._commit(
                    member, ref, KIND_SELF, depth, title, description, reason, origin, tool_id,
                    department=member.department, assignee=member.slot_id, spawned_from=spawned_from,
                )
            if target.department == member.department and target.chief_slot_id == member.slot_id:
                if self._stopped_now(target.slot_id):
                    return AgentWorkRefusal(REFUSAL_ASSIGNEE_STOPPED, "the colleague is stopped by the Captain's order")
                if not self._holds_tool(target, tool_id):
                    return AgentWorkRefusal(REFUSAL_ASSIGNEE_NOT_ELIGIBLE, f"{target.slot_id} cannot use {tool_id}")
                return await self._commit(
                    member, ref, KIND_ASSIGNMENT, depth, title, description, reason, origin, tool_id,
                    department=target.department, assignee=target.slot_id, spawned_from=spawned_from,
                )
        if self._holds_tool(member, tool_id):
            return AgentWorkRefusal(REFUSAL_REQUESTER_HOLDS_TOOL, f"you can use {tool_id} yourself; create a self-task")
        eligible = self.eligible_members(tool_id)
        departments = sorted({candidate.department for candidate in eligible})
        if department is not None:
            if department not in departments:
                return AgentWorkRefusal(REFUSAL_DEPARTMENT_NOT_ELIGIBLE, f"no member of {department} can use {tool_id} now")
            chosen = department
        elif not eligible:
            return AgentWorkRefusal(REFUSAL_NO_ELIGIBLE_MEMBER, f"no live crew member can use {tool_id} now")
        elif target is not None and target.department in departments:
            chosen = target.department
        else:
            chosen = min(departments, key=lambda name: (-sum(1 for m in eligible if m.department == name), name))
        notify = tuple(sorted(candidate.slot_id for candidate in eligible if candidate.department == chosen))
        return await self._commit(
            member, ref, KIND_REQUEST, depth, title, description, reason, origin, tool_id,
            department=chosen, assignee=None, spawned_from=spawned_from,
            converted_from=target.slot_id if target is not None else None, notify=notify,
        )

    def eligible_members(self, tool_id: str) -> tuple[CrewMember, ...]:
        """Live, unstopped crew members who may use ``tool_id`` at read level; empty for an unregistered tool."""
        if not _identifier(tool_id) or not _registered(self._tools, tool_id):
            return ()
        return tuple(
            candidate for candidate in self._directory.members()
            if not self._stopped_now(candidate.slot_id) and self._holds_tool(candidate, tool_id)
        )

    def claim_allowed(self, item: WorkItem, resource: BookableResource) -> bool:
        """The store's claim gate (``WorkItemStore.set_agent_work_claim_gate``): may this resource claim this now?

        Only a well-formed request can be claimed, by a live member of its department who is not stopped and may
        use its tool. Synchronous and without I/O, because the store asks inside its claim transaction. Never raises.
        """
        try:
            record = read_agent_work(item)
            if record is None or record.kind != KIND_REQUEST or record.tool_id is None:
                return False
            claimant = self._directory.member(resource.resource_id)
            if claimant is None or claimant.department != record.department:
                return False
            return not self._stopped_now(claimant.slot_id) and self._holds_tool(claimant, record.tool_id)
        except Exception:
            logger.warning(
                "AD-1347: the claim check for work item %s failed; it is not claimable by %s now and discovery continues",
                getattr(item, "id", "?"), getattr(resource, "resource_id", "?"), exc_info=True,
            )
            return False

    async def notice_recipients(self, work_item_id: str) -> tuple[str, ...]:
        """Who hears an item's outcome: its requester, then each watcher once (S3 delivers to every one)."""
        item = await self._store.get_work_item(work_item_id)
        record = read_agent_work(item) if item is not None else None
        if record is None:
            return ()
        watchers = await self._store.list_work_watchers(work_item_id)
        return (record.requester, *(watcher for watcher in watchers if watcher != record.requester))

    async def terminal_notices_due(self, limit: int = 50) -> tuple[AgentWorkNotice, ...]:
        """Ended agent work whose requester or a watcher has not been told; S3 claims each before sending it."""
        rows = await self._store.list_due_work_notices(NOTICE_TERMINAL, limit)
        notices: list[AgentWorkNotice] = []
        for work_item_id, recipient in rows:
            item = await self._store.get_work_item(work_item_id)
            if item is None:
                continue
            expired = (
                item.status == "cancelled" and item.ttl_seconds is not None
                and item.updated_at >= item.created_at + item.ttl_seconds
            )
            notices.append(AgentWorkNotice(work_item_id, recipient, OUTCOME_EXPIRED if expired else item.status))
        return tuple(notices)

    async def claim_notice(self, work_item_id: str, recipient: str) -> bool:
        """Claim the one terminal notice to ``recipient`` before sending it: True once, False ever after."""
        return await self._store.claim_work_notice(work_item_id, recipient, NOTICE_TERMINAL, self._clock())

    async def _admit(
        self, requester: str, title: str, description: str, reason: str,
        origin: AgentWorkOrigin, spawned_from: str | None,
    ) -> tuple[CrewMember, IdentityRef, int] | AgentWorkRefusal:
        """The shared checks, in order: the input, the requester (fail closed), the Captain's stop, the depth."""
        if (
            not _identifier(requester)
            or _text(title, MAX_TITLE_CHARS, required=True) is None
            or _text(description, MAX_DESCRIPTION_CHARS, required=False) is None
            or _text(reason, MAX_REASON_CHARS, required=True) is None
            or type(origin) is not AgentWorkOrigin
            or (spawned_from is not None and not _identifier(spawned_from))
        ):
            return AgentWorkRefusal(REFUSAL_INVALID, "a title, a reason and an origin are required, within their limits")
        ref = self._identities.resolve(requester)
        member = self._directory.member(ref.slot_id) if ref is not None else None
        if member is None or ref is None:
            return AgentWorkRefusal(REFUSAL_UNRESOLVED, "the requester is not a live crew member")
        stopped = self._requester_stop(member.slot_id)
        if stopped is not None:
            return AgentWorkRefusal(STOP_REASON_CODE, stopped.sender_text())
        depth = 1
        if spawned_from is not None:
            parent = await self._store.get_work_item(spawned_from)
            if parent is None:
                return AgentWorkRefusal(REFUSAL_PARENT_UNKNOWN, "the work this was created from does not exist")
            record = read_agent_work(parent)
            depth = record.depth + 1 if record is not None else 1
        if depth > self._config.max_depth:
            return AgentWorkRefusal(REFUSAL_DEPTH, f"depth {depth} is past the limit of {self._config.max_depth}")
        return member, ref, depth

    def _requester_stop(self, slot_id: str) -> StopRecord | None:
        """AD-1343: the requester's stop, counted as one refusal at SEAM_AGENT_WORK."""
        return active_stop(self._stop_gate, slot_id, SEAM_AGENT_WORK)

    def _stopped_now(self, slot_id: str) -> bool:
        """AD-1343: whether a colleague is stopped; asked of many candidates, so nothing is counted."""
        return standing_stop(self._stop_gate, slot_id) is not None

    def _holds_tool(self, member: CrewMember, tool_id: str) -> bool:
        """The registry's own answer for this member: department scope, restricted_to, rank, the Captain's grants."""
        return self._tools.check_permission(
            member.slot_id, tool_id, ToolPermission.READ,
            agent_department=member.department, agent_rank=member.rank, agent_types=[member.agent_type],
        )

    async def _commit(
        self, member: CrewMember, ref: IdentityRef, kind: str, depth: int, title: str, description: str,
        reason: str, origin: AgentWorkOrigin, tool_id: str | None, *, department: str, assignee: str | None,
        spawned_from: str | None, converted_from: str | None = None, notify: tuple[str, ...] = (),
    ) -> AgentWorkCreated | AgentWorkRefusal:
        """Dedup (requests), the volume guards, then one insert, under one lock: this service is the only writer."""
        clean_title = title.strip()
        converted = converted_from is not None
        key = dedup_key(department, tool_id, clean_title) if kind == KIND_REQUEST and tool_id is not None else None
        async with self._lock:
            now = self._clock()
            open_items = await self._store.list_agent_work(True, None, SCAN_LIMIT)
            open_records = [read_agent_work(item) for item in open_items]
            if key is not None:
                for item, record in zip(open_items, open_records):
                    if record is not None and record.kind == KIND_REQUEST and record.dedup_key == key:
                        if record.requester != member.slot_id:
                            await self._store.add_work_watcher(item.id, member.slot_id, now)
                        return AgentWorkCreated(item, KIND_REQUEST, deduplicated=True, converted=converted, notify=notify)
            recent = await self._store.list_agent_work(False, now - RATE_WINDOW_SECONDS, SCAN_LIMIT)
            if len(open_items) >= SCAN_LIMIT or len(recent) >= SCAN_LIMIT:
                return AgentWorkRefusal(REFUSAL_SHIP_CAP, "more agent-created work is on the board than the guards count")
            mine_recent = sum(1 for item in recent if _requested_by(item, member.slot_id))
            mine_open = sum(1 for record in open_records if record is not None and record.requester == member.slot_id)
            department_open = sum(
                1 for record in open_records
                if record is not None and record.kind == KIND_REQUEST and record.department == department
            )
            if mine_recent >= self._config.max_created_per_agent_per_hour:
                return AgentWorkRefusal(REFUSAL_RATE, f"at most {self._config.max_created_per_agent_per_hour} an hour")
            if mine_open >= self._config.max_open_per_agent:
                return AgentWorkRefusal(REFUSAL_AGENT_CAP, f"at most {self._config.max_open_per_agent} open at once")
            if kind == KIND_REQUEST and department_open >= self._config.max_open_per_department:
                return AgentWorkRefusal(REFUSAL_DEPARTMENT_CAP, f"{department} already has {department_open} open requests")
            if len(open_items) >= self._config.max_open_ship:
                return AgentWorkRefusal(REFUSAL_SHIP_CAP, f"the ship already has {len(open_items)} open agent work items")
            provenance: dict[str, Any] = {
                "version": AGENT_WORK_VERSION,
                "kind": kind,
                "requester": member.slot_id,
                "requester_sovereign_id": ref.sovereign_id,
                "origin": origin.to_dict(),
                "reason": reason.strip(),
                "depth": depth,
                "department": department,
                "tool_id": tool_id,
                "dedup_key": key,
                "spawned_from": spawned_from,
                "assignee_requested": converted_from,
            }
            metadata: dict[str, Any] = {AGENT_WORK_METADATA_KEY: provenance}
            if kind == KIND_REQUEST:
                metadata["agent_pull"] = {"version": 1, "scope": "department", "department": department}
            item = await self._store.create_work_item(
                title=clean_title,
                description=description.strip() or clean_title,
                work_type="task",
                assigned_to=assignee,
                created_by=member.slot_id,
                created_at=now,
                updated_at=now,
                ttl_seconds=self._config.ttl_seconds,
                tags=[AGENT_WORK_TAG],
                metadata=metadata,
            )
        logger.info(
            "AD-1347: %s %s created by %s (depth %d, department %s, tool %s)",
            kind, item.id, member.slot_id, depth, department, tool_id,
        )
        return AgentWorkCreated(item, kind, converted=converted, notify=notify)


async def open_agent_work_service(
    *,
    config: AgentWorkConfig,
    store: WorkItemStore | None,
    tools: ToolPermissionView | None,
    identities: IdentityResolver | None,
    directory: CrewDirectory | None,
    stop_gate: AgentStopService | None,
    clock: Callable[[], float] = time.time,
) -> AgentWorkService | None:
    """The one way the runtime builds the service (D1). None while ``config.enabled`` is False, touching nothing.

    When enabled, a missing collaborator or a schema failure is logged and the feature stays off for this run
    (log-and-degrade: the vessel boots). Otherwise the watcher and notice tables are created, the store's claim
    gate is set to ``claim_allowed`` and the service is returned.
    """
    if not config.enabled:
        return None
    if store is None or tools is None or identities is None or directory is None or stop_gate is None:
        missing = [
            name for name, value in (
                ("work_item_store", store), ("tool_registry", tools), ("identity_service", identities),
                ("crew_directory", directory), ("agent_stops", stop_gate),
            ) if value is None
        ]
        logger.warning(
            "AD-1347: agent_work.enabled is set but these collaborators are missing: %s; "
            "agent-created work stays off for this run", ", ".join(missing),
        )
        return None
    try:
        await store.ensure_agent_work_schema()
    except Exception:
        logger.error(
            "AD-1347: the agent-work tables could not be created in workforce.db; "
            "agent-created work stays off for this run",
            exc_info=True,
        )
        return None
    service = AgentWorkService(
        config=config, store=store, tools=tools, identities=identities,
        directory=directory, stop_gate=stop_gate, clock=clock,
    )
    store.set_agent_work_claim_gate(service.claim_allowed)
    logger.info(
        "AD-1347: agent-created work is on (open caps: %d per agent, %d per department, %d ship-wide)",
        config.max_open_per_agent, config.max_open_per_department, config.max_open_ship,
    )
    return service
