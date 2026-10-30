"""AD-1346 M3d2 (#1604): the work-ticket carrier, an observation device in shadow (D101, D110).

``CURRENT_TICKET`` holds the ticket of the unit of work running in the current context, or None. In ``src``,
``AdmissionService.hold`` is the one call that sets it and ``TicketHold.end`` the one that resets it
(``tests/test_ad1346_admission_ticket_issue.py``, I11). Each entry that takes a hold ends it in the ``finally`` of the
``try`` that holds the entry's work (I10), so ``end`` runs when that work returns, raises or is cancelled.

An awaited coroutine runs in its caller's context (PEP 567: "Every advance of the wrapped coroutine is done in the
task's context"), so a delegated run that a tool call awaits inline reads the delegating unit's ticket. Work started
with a context of its own reads what that context holds. Nothing here blocks, charges or logs, and nothing is persisted;
AD-1346 M4 decides whether a ticket is threaded explicitly instead.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from probos.admission.tickets import TicketRegistry, WorkTicket

#: The ticket of the unit of work running in this context; None outside any held unit. Created at module level, as the
#: ``contextvars`` documentation asks.
CURRENT_TICKET: Final[ContextVar[WorkTicket | None]] = ContextVar("probos_admission_ticket", default=None)


@dataclass(frozen=True, slots=True)
class TicketHold:
    """One admitted unit's place in the carrier: the registry, the ticket it issued (None when it refused), and the
    token of the carrier's ``set``. ``NO_HOLD``, with none of them, is what an entry gets when nothing was issued."""

    registry: TicketRegistry | None = None
    ticket: WorkTicket | None = None
    token: Token[WorkTicket | None] | None = None

    def end(self) -> None:
        """End the unit's hold when its work ends: put back what the carrier held before the hold, then release the ticket.

        It raises no ``Exception``. A token that was already used, or that this context did not create, is passed
        over (``ContextVar.reset`` raises ``RuntimeError`` or ``ValueError``, PEP 567), and so is an ``Exception`` from
        the release; a ``BaseException`` that is not an ``Exception`` propagates. ``NO_HOLD.end()`` does nothing.
        """
        if self.token is not None:
            try:
                CURRENT_TICKET.reset(self.token)
            except (RuntimeError, ValueError):  # PEP 567: a token already used, or one set in another context
                pass
        if self.registry is not None and self.ticket is not None:
            try:
                self.registry.release(self.ticket)
            except Exception:  # noqa: BLE001 -- #1604 property 6: ending a shadow ticket never changes the work's outcome
                pass


#: The hold of a unit for which nothing was issued: its ``end`` does nothing.
NO_HOLD: Final = TicketHold()
