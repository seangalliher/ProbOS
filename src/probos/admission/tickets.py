"""AD-1346 M3d1 (#1604): work tickets and the registry that is their authority, in memory.

A work ticket is the capability of epic #1601's design note. ``TicketRegistry.issue`` registers one
for a unit of work admitted at its seam, ``issue_child`` registers one no wider than its parent for work
that unit hands on, and ``check`` is the liveness check an effect point runs. The registry is the
authority: ``check`` and ``issue_child`` read what they compare (principal, scope, budget, parent,
expiry) from the registry's entry for the presented ticket's id, never from the presented object. A
hand-built ``WorkTicket`` with a live id therefore resolves to that entry, and any other object, None
and a ``TestTicket`` aside, is ``ticket_unknown``. ``TestTicket`` is the one explicit test form; a
registry built without ``allow_test_tickets=True`` refuses it.

Nothing here blocks, charges or logs. ``check`` returns a finding, and ``issue`` and ``issue_child`` a
``TicketIssue`` that holds one; each finding carries a code from ``TICKET_REASON_CODES`` and a cause and is counted
in ``tally``. A
budget is a pair of ceilings compared when a child is issued and never decremented (AD-1346 M5 owns
accounts). A Captain's stop is read with ``AgentStopService.stop_for``, which counts nothing, for the
entry's principal and then for each registered ancestor's; the first entry found under a stop is
marked revoked with every registered descendant, and stays revoked after the stop is lifted.

Bounds (F-209): ``issue`` and ``issue_child`` add an entry only through ``_register``, which first
drops entries in issue order while the oldest one ended (expired, was released or was revoked) more
than ``retain_seconds`` before now, then refuses with ``ticket_registry_full`` while ``MAX_TICKETS``
entries remain. A registry is built empty: it has no store and nothing restores it. It holds no lock
and awaits nothing; like ``DelegationTreeBudget``, it is to be used only from the thread that runs
its event loop.
"""

from __future__ import annotations

import secrets
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from probos.admission.taxonomy import (
    SEAM_MODEL_CALL,
    SEAMS,
    TICKET_EXPIRED,
    TICKET_ISSUED,
    TICKET_LIVE,
    TICKET_MISSING,
    TICKET_OUT_OF_SCOPE,
    TICKET_PRINCIPAL_MISMATCH,
    TICKET_REASON_CODES,
    TICKET_REGISTRY_FULL,
    TICKET_REVOKED,
    TICKET_TEST_REFUSED,
    TICKET_TOO_DEEP,
    TICKET_UNKNOWN,
    TICKET_WIDENED,
    WORK_KINDS,
)
from probos.agent_stop import SEAM_TOOL, AgentStopService

if TYPE_CHECKING:
    from collections.abc import Callable

#: The effect points a scope names: the tool sink's seam (AD-1343) and the model gateway's.
TICKET_EFFECTS: Final[tuple[str, ...]] = (SEAM_TOOL, SEAM_MODEL_CALL)
OP_ISSUE: Final = "issue"
#: What a finding is about: an issue, or the check at one effect point.
TICKET_OPERATIONS: Final[tuple[str, ...]] = (OP_ISSUE, *TICKET_EFFECTS)
#: The keys of ``TicketFinding.to_dict()``, in order. Append-only (the ``VERDICT_KEYS`` discipline).
TICKET_FINDING_KEYS: Final[tuple[str, ...]] = (
    "operation", "code", "cause", "ticket_id", "principal_key", "presented_key", "parent_id", "depth", "work_kind",
    "stop_id",
)
#: The most entries one registry holds (F-209: a bound from day one).
MAX_TICKETS: Final = 50_000
#: A root ticket's life from its issue, on the registry's clock; a child's ends no later than its parent's.
TICKET_TTL_SECONDS: Final = 3_600.0
#: The least time an ended entry is kept, so that a check reads ``ticket_expired`` or ``ticket_revoked``, not ``ticket_unknown``.
TICKET_RETAIN_SECONDS: Final = 600.0
#: The most characters of an id or a key that a finding carries.
SHOWN_CHARS: Final = 64
_EFFECT_SET: Final = frozenset(TICKET_EFFECTS)


@dataclass(frozen=True, slots=True)
class WorkTicket:
    """A ticket as its holder carries it: the id and nothing else. The registry's entry for the id is the authority."""

    ticket_id: str

    def __post_init__(self) -> None:
        if type(self.ticket_id) is not str:
            raise TypeError("WorkTicket.ticket_id must be a str")


@dataclass(frozen=True, slots=True)
class TestTicket:
    """The explicit test form (#1601, Risks): ``check`` answers ``ticket_live`` for it in a registry built with
    ``allow_test_tickets=True`` and ``ticket_test_refused`` in any other. It parents nothing."""

    __test__ = False  # not a pytest test class

    label: str = ""


@dataclass(frozen=True, slots=True)
class TicketScope:
    """The effect points a ticket's work may reach: a frozenset within ``TICKET_EFFECTS``."""

    effects: frozenset[str]

    def __post_init__(self) -> None:
        if type(self.effects) is not frozenset or not self.effects <= _EFFECT_SET:
            raise ValueError(f"AD-1346: a ticket scope is a frozenset within {TICKET_EFFECTS}")


@dataclass(frozen=True, slots=True)
class TicketBudget:
    """Two ceilings, each None (unbounded) or an int of at least 1; compared when a child is issued, never charged."""

    max_tokens: int | None = None
    max_iterations: int | None = None

    def __post_init__(self) -> None:
        for value in (self.max_tokens, self.max_iterations):
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError("AD-1346: a ticket budget ceiling is None or an int of at least 1")


@dataclass(frozen=True, slots=True)
class TicketEntry:
    """The registry's record of one ticket: what a sink reads, never the presented object."""

    ticket_id: str
    principal_key: str
    work_kind: str
    seam: str
    scope: TicketScope
    budget: TicketBudget
    parent_id: str
    depth: int
    issued_at: float
    expires_at: float
    revoked_at: float | None = None
    stop_id: str = ""


@dataclass(frozen=True, slots=True)
class TicketFinding:
    """One issue or one check: its operation, its code, its cause, and what the registry holds for the ticket."""

    operation: str
    code: str
    cause: str
    ticket_id: str = ""
    principal_key: str = ""
    presented_key: str = ""
    parent_id: str = ""
    depth: int = 0
    work_kind: str = ""
    stop_id: str = ""

    def __post_init__(self) -> None:
        if self.operation not in TICKET_OPERATIONS or self.code not in TICKET_REASON_CODES:
            raise ValueError(f"AD-1346: unknown ticket operation or code {self.operation!r}, {self.code!r}")

    def to_dict(self) -> dict[str, object]:
        """The stable form: ``TICKET_FINDING_KEYS`` in order."""
        return {name: getattr(self, name) for name in TICKET_FINDING_KEYS}


@dataclass(frozen=True, slots=True)
class TicketIssue:
    """What ``issue`` or ``issue_child`` returns: the new ticket, or None, and the finding."""

    ticket: WorkTicket | None
    finding: TicketFinding


class TicketRegistry:
    """Ship's Computer service: the in-memory authority for work tickets (AD-1346 M3d1); it blocks and charges nothing."""

    def __init__(
        self,
        stop_service: AgentStopService,
        *,
        max_depth: int,
        ttl_seconds: float = TICKET_TTL_SECONDS,
        retain_seconds: float = TICKET_RETAIN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        allow_test_tickets: bool = False,
    ) -> None:
        if not isinstance(stop_service, AgentStopService):
            raise TypeError("TicketRegistry needs the AgentStopService record")
        if type(max_depth) is not int or max_depth < 0:
            raise ValueError("AD-1346: max_depth is an int of at least 0, as delegation_max_depth is")
        for seconds in (ttl_seconds, retain_seconds):
            if type(seconds) not in (int, float) or not 0 < seconds < float("inf"):
                raise ValueError("AD-1346: a ticket's life and retention are finite seconds above 0")
        if type(allow_test_tickets) is not bool:
            raise TypeError("AD-1346: allow_test_tickets is a bool")
        self._stops = stop_service
        self._max_depth = max_depth
        self._ttl = float(ttl_seconds)
        self._retain = float(retain_seconds)
        self._clock = clock
        self._allow_test = allow_test_tickets
        self._entries: dict[str, TicketEntry] = {}
        self._order: deque[str] = deque()
        self._children: dict[str, set[str]] = {}
        self._tally: dict[tuple[str, str], int] = {}

    def __len__(self) -> int:
        """The entries held: live ones, and ended ones not yet dropped."""
        return len(self._entries)

    def issue(
        self, *, principal_key: str, work_kind: str, seam: str, scope: TicketScope, budget: TicketBudget,
    ) -> TicketIssue:
        """Register a root ticket (depth 0, no parent) for a unit of work admitted at its seam; it expires ``ttl_seconds`` from now."""
        _require(principal_key, work_kind, seam, scope, budget)
        now = self._clock()
        return self._register(principal_key, work_kind, seam, scope, budget, None, now, now + self._ttl)

    def issue_child(
        self, parent: object, *, principal_key: str, work_kind: str, seam: str, scope: TicketScope,
        budget: TicketBudget,
    ) -> TicketIssue:
        """Register a child of the live, registered ``parent``, checked against the parent's entry (the design note's rule 3).

        The child is one level deeper and at most ``max_depth``; its scope is a subset of the parent's; each
        ceiling it leaves None is the parent's, and each it sets is no larger than a ceiling the parent has; it
        expires no later than the parent. A parent that is not live is refused with its own code, a deeper child
        with ``ticket_too_deep`` and a wider one with ``ticket_widened``; a refusal adds no entry.
        """
        _require(principal_key, work_kind, seam, scope, budget)
        now = self._clock()
        parent_entry, found = self._liveness(parent, now, OP_ISSUE, "")
        if parent_entry is None or found.code != TICKET_LIVE:
            cause = f"No child was issued: {found.cause}"
            return _refusal(self._tally, found.code, cause, principal_key, work_kind, found.ticket_id, 0, found.stop_id)
        depth = parent_entry.depth + 1
        if depth > self._max_depth:
            cause = f"No child was issued: a child of ticket {parent_entry.ticket_id} would be at depth {depth}, beyond {self._max_depth}."
            return _refusal(self._tally, TICKET_TOO_DEEP, cause, principal_key, work_kind, parent_entry.ticket_id, depth, "")
        tokens = parent_entry.budget.max_tokens if budget.max_tokens is None else budget.max_tokens
        iterations = parent_entry.budget.max_iterations if budget.max_iterations is None else budget.max_iterations
        wider_scope = not scope.effects <= parent_entry.scope.effects
        wider_tokens = not _within(tokens, parent_entry.budget.max_tokens)
        wider_iterations = not _within(iterations, parent_entry.budget.max_iterations)
        if wider_scope or wider_tokens or wider_iterations:
            cause = f"No child was issued: its scope or a ceiling is wider than ticket {parent_entry.ticket_id}'s."
            return _refusal(self._tally, TICKET_WIDENED, cause, principal_key, work_kind, parent_entry.ticket_id, depth, "")
        expires_at = min(now + self._ttl, parent_entry.expires_at)
        return self._register(
            principal_key, work_kind, seam, scope, TicketBudget(tokens, iterations), parent_entry, now, expires_at,
        )

    def check(self, ticket: object, *, effect: str, presented_key: str = "") -> TicketFinding:
        """The liveness check an effect point runs (#1601 Target 2): the counted finding for ``ticket`` at ``effect``.

        In order: no ticket is ``ticket_missing``; a ``TestTicket`` is ``ticket_live`` in a registry built for
        tests; then ``_liveness`` (``ticket_test_refused``, ``ticket_unknown``, ``ticket_revoked``,
        ``ticket_expired``, or ``ticket_revoked`` under a Captain's stop); then ``ticket_principal_mismatch``
        when ``presented_key`` is given and is not the entry's principal, ``ticket_out_of_scope`` when
        ``effect`` is not in the entry's scope, else ``ticket_live``. It raises no ``Exception`` for any
        presented ``ticket``. An ``effect`` outside ``TICKET_EFFECTS`` raises ``ValueError``, and a
        ``presented_key`` that is not a ``str`` raises ``TypeError``.
        """
        if type(effect) is not str or effect not in _EFFECT_SET:
            raise ValueError(f"AD-1346: unknown effect {effect!r}")
        if type(presented_key) is not str:
            raise TypeError("AD-1346: presented_key is a str")
        shown_key = _shown(presented_key)
        if ticket is None:
            missing = TicketFinding(effect, TICKET_MISSING, f"No ticket was presented at {effect}.", presented_key=shown_key)
            return _counted(self._tally, missing)
        if type(ticket) is TestTicket and self._allow_test:
            cause = f"A TestTicket is live at {effect} in a registry built for tests."
            return _counted(self._tally, TicketFinding(effect, TICKET_LIVE, cause, presented_key=shown_key))
        entry, found = self._liveness(ticket, self._clock(), effect, shown_key)
        if entry is None or found.code != TICKET_LIVE:
            return _counted(self._tally, found)
        if presented_key and presented_key != entry.principal_key:
            cause = f"Ticket {entry.ticket_id} is registered to {_shown(entry.principal_key)}, not to {shown_key}."
            return _counted(self._tally, replace(found, code=TICKET_PRINCIPAL_MISMATCH, cause=cause))
        if effect not in entry.scope.effects:
            cause = f"Ticket {entry.ticket_id}'s scope does not include {effect}."
            return _counted(self._tally, replace(found, code=TICKET_OUT_OF_SCOPE, cause=cause))
        cause = f"Ticket {entry.ticket_id} of {_shown(entry.principal_key)} is live at {effect}."
        return _counted(self._tally, replace(found, cause=cause))

    def revoke(self, ticket: object) -> int:
        """Revoke a registered ticket and its registered descendants; return how many entries this revoked.

        The issuer's act (AD-1346 M4 decides who calls it). Anything not registered revokes nothing and returns 0.
        """
        ticket_id = _presented_id(ticket)
        if ticket_id is None or ticket_id not in self._entries:
            return 0
        return self._revoke_tree(ticket_id, self._clock(), "")

    def release(self, ticket: object) -> bool:
        """End a registered ticket's life now, as its work ends; a later check reads ``ticket_expired`` unless it is revoked.

        False for anything not registered. Its children keep their own expiry.
        """
        ticket_id = _presented_id(ticket)
        entry = None if ticket_id is None else self._entries.get(ticket_id)
        if entry is None:
            return False
        now = self._clock()
        if now < entry.expires_at:
            self._entries[entry.ticket_id] = replace(entry, expires_at=now)
        return True

    def entry(self, ticket: object) -> TicketEntry | None:
        """The registry's entry for a presented ticket's id, live or ended and not yet dropped, or None.

        What a sink reads; never the presented object.
        """
        ticket_id = _presented_id(ticket)
        return None if ticket_id is None else self._entries.get(ticket_id)

    def tally(self) -> dict[tuple[str, str], int]:
        """Findings by (operation, code) since this registry was built; a copy."""
        return dict(self._tally)

    def _register(
        self, principal_key: str, work_kind: str, seam: str, scope: TicketScope, budget: TicketBudget,
        parent: TicketEntry | None, now: float, expires_at: float,
    ) -> TicketIssue:
        """Add one entry after ``_purge``, unless ``MAX_TICKETS`` entries remain."""
        self._purge(now)
        parent_id = "" if parent is None else parent.ticket_id
        depth = 0 if parent is None else parent.depth + 1
        if len(self._entries) >= MAX_TICKETS:
            cause = f"The ticket registry holds {len(self._entries)} tickets, its bound; none was issued."
            return _refusal(self._tally, TICKET_REGISTRY_FULL, cause, principal_key, work_kind, parent_id, depth, "")
        ticket_id = secrets.token_hex(16)
        self._entries[ticket_id] = TicketEntry(
            ticket_id, principal_key, work_kind, seam, scope, budget, parent_id, depth, now, expires_at,
        )
        self._order.append(ticket_id)
        if parent is not None:
            self._children.setdefault(parent_id, set()).add(ticket_id)
        cause = f"Ticket {ticket_id} issued to {_shown(principal_key)} for {work_kind} at {seam}, depth {depth}."
        finding = TicketFinding(
            OP_ISSUE, TICKET_ISSUED, cause, ticket_id=ticket_id, principal_key=_shown(principal_key),
            parent_id=parent_id, depth=depth, work_kind=work_kind,
        )
        return TicketIssue(WorkTicket(ticket_id), _counted(self._tally, finding))

    def _purge(self, now: float) -> None:
        """Drop entries in issue order while the oldest ended more than ``retain_seconds`` before ``now``."""
        while self._order:
            oldest = self._entries[self._order[0]]
            if now - _ended(oldest) <= self._retain:
                return
            self._order.popleft()
            del self._entries[oldest.ticket_id]
            self._children.pop(oldest.ticket_id, None)

    def _liveness(
        self, ticket: object, now: float, operation: str, presented_key: str,
    ) -> tuple[TicketEntry | None, TicketFinding]:
        """The registered entry for a presented ticket and its finding: ``ticket_test_refused``, ``ticket_unknown``,
        ``ticket_revoked``, ``ticket_expired``, then a Captain's stop on its principal or an ancestor's
        (``ticket_revoked``), else ``ticket_live`` with no cause yet."""
        if type(ticket) is TestTicket and not self._allow_test:
            cause = "A TestTicket was presented to a registry that refuses test tickets."
            return None, TicketFinding(operation, TICKET_TEST_REFUSED, cause, presented_key=presented_key)
        ticket_id = _presented_id(ticket)
        entry = None if ticket_id is None else self._entries.get(ticket_id)
        if entry is None:
            shown = "" if ticket_id is None else _shown(ticket_id)
            cause = "The presented object is not a ticket the registry holds."
            return None, TicketFinding(operation, TICKET_UNKNOWN, cause, ticket_id=shown, presented_key=presented_key)
        found = TicketFinding(
            operation, TICKET_LIVE, "", ticket_id=entry.ticket_id, principal_key=_shown(entry.principal_key),
            presented_key=presented_key, parent_id=entry.parent_id, depth=entry.depth, work_kind=entry.work_kind,
        )
        if entry.revoked_at is not None:
            cause = _revoked_cause(entry.ticket_id, entry.stop_id)
            return entry, replace(found, code=TICKET_REVOKED, cause=cause, stop_id=entry.stop_id)
        if now >= entry.expires_at:
            cause = f"Ticket {entry.ticket_id} ended: it expired, or was released when its work ended."
            return entry, replace(found, code=TICKET_EXPIRED, cause=cause)
        node: TicketEntry | None = entry
        while node is not None:
            record = self._stops.stop_for(node.principal_key)
            if record is not None:
                self._revoke_tree(node.ticket_id, now, record.stop_id)
                cause = _revoked_cause(entry.ticket_id, record.stop_id)
                return entry, replace(found, code=TICKET_REVOKED, cause=cause, stop_id=record.stop_id)
            node = self._entries.get(node.parent_id)
        return entry, found

    def _revoke_tree(self, ticket_id: str, now: float, stop_id: str) -> int:
        """Mark a registered entry and each registered descendant revoked at ``now``; return how many were not already."""
        revoked = 0
        pending = [ticket_id]
        while pending:
            current = self._entries.get(pending.pop())
            if current is None:  # a dropped id holds nothing to revoke
                continue
            if current.revoked_at is None:
                self._entries[current.ticket_id] = replace(current, revoked_at=now, stop_id=stop_id)
                revoked += 1
            pending.extend(self._children.get(current.ticket_id, ()))
        return revoked


def _shown(value: str) -> str:
    """An id or a key as a finding carries it: at most ``SHOWN_CHARS`` characters."""
    return value[:SHOWN_CHARS]


def _ended(entry: TicketEntry) -> float:
    """When an entry stopped being live: its expiry, or its revocation when that came first."""
    return entry.expires_at if entry.revoked_at is None else min(entry.expires_at, entry.revoked_at)


def _within(child: int | None, parent: int | None) -> bool:
    """A child's ceiling is no wider than the parent's: anything under an unbounded parent, else a value at most the parent's."""
    return parent is None or (child is not None and child <= parent)


def _presented_id(ticket: object) -> str | None:
    """The id of an exact ``WorkTicket``; None for any other object, and for one built without its id."""
    if type(ticket) is WorkTicket:
        try:
            ticket_id = ticket.ticket_id
        except AttributeError:  # built with object.__new__: the slot is empty
            return None
        return ticket_id if type(ticket_id) is str else None
    return None


def _revoked_cause(ticket_id: str, stop_id: str) -> str:
    """Why a ticket is revoked: the Captain's stop by its order's id, or its issuer; never the Captain's reason."""
    if stop_id:
        return f"Ticket {ticket_id} is revoked: its principal or an ancestor's is under the Captain's stop {stop_id}."
    return f"Ticket {ticket_id} is revoked by its issuer, itself or with an ancestor."


def _require(principal_key: object, work_kind: object, seam: object, scope: object, budget: object) -> None:
    """An issue's arguments: str values, a non-empty principal key, a known work kind and seam, a TicketScope and a TicketBudget."""
    for value in (principal_key, work_kind, seam):
        if type(value) is not str:
            raise TypeError("AD-1346: a ticket's principal key, work kind and seam are str")
    if not principal_key or work_kind not in WORK_KINDS or seam not in SEAMS:
        raise ValueError(f"AD-1346: an empty principal key, or an unknown work kind or seam: {work_kind!r}, {seam!r}")
    if type(scope) is not TicketScope or type(budget) is not TicketBudget:
        raise TypeError("AD-1346: a ticket takes a TicketScope and a TicketBudget")


def _counted(tally: dict[tuple[str, str], int], finding: TicketFinding) -> TicketFinding:
    """Count a finding under (operation, code) and return it."""
    key = (finding.operation, finding.code)
    tally[key] = tally.get(key, 0) + 1
    return finding


def _refusal(
    tally: dict[tuple[str, str], int], code: str, cause: str, principal_key: str, work_kind: str, parent_id: str,
    depth: int, stop_id: str,
) -> TicketIssue:
    """An issue that added no entry: no ticket, and its counted finding."""
    finding = TicketFinding(
        OP_ISSUE, code, cause, principal_key=_shown(principal_key), parent_id=parent_id, depth=depth,
        work_kind=work_kind, stop_id=stop_id,
    )
    return TicketIssue(None, _counted(tally, finding))
