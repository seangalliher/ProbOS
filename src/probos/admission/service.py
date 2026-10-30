"""AD-1346 M3a (#1604): the shadow admission decision, in process and synchronous.

``AdmissionService.decide`` resolves the principal through ``IdentityService`` and runs the
checks in ``CHECK_ORDER``; the first that refuses decides the verdict (D18). ``shadow`` is the
form for a seam: it builds the request, decides, counts the verdict and its latency in memory and
returns None, so a seam has no result to act on. Its ``except Exception`` counts an ``Exception``
raised by that work and passes it to the module logger (T12). From AD-1346 M3c that log call has
a guard of its own (F-212, D59), so no ``Exception`` leaves ``shadow``; a ``BaseException`` that
is not an ``Exception`` propagates. AD-1346 M3b added an optional ``ShadowRecorder``: a service
built with one also hands each verdict ``shadow`` counted, and its measured time, to
``ShadowRecorder.offer`` inside the same ``try``; ``decide`` does not call it. AD-1346 M3c added
the site's own outcome (``today_outcome``), which ``shadow`` checks and hands to the recorder for
parity, and ``close``, after which ``shadow`` returns None at once.
``probos.admission.seam.shadow_at`` calls ``shadow`` with the outcome a site's own check reached.
AD-1346 M3d2 added an optional ``TicketRegistry`` and ``hold``: ``probos.admission.seam.hold_at`` calls ``hold``
at three entries, past their own stop check, and ``hold`` issues that unit's work ticket into the carrier
(``probos.admission.carrier``); with no registry, or after ``close``, it issues nothing. ``hold`` has an
``except Exception`` of its own, which counts in ``failures`` and logs as ``shadow``'s does.
The service reads no configuration.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Final

from probos.admission.carrier import CURRENT_TICKET, NO_HOLD, TicketHold
from probos.admission.checks import ADMITTED, check_agent_stop, check_principal, resolve_principal
from probos.admission.record import AdmissionVerdict, WorkRequest
from probos.admission.recorder import ShadowRecorder
from probos.admission.taxonomy import LATENCY_BUCKETS, OUTCOME_ADMIT, OUTCOME_WOULD_REFUSE, TODAY_OUTCOMES
from probos.admission.tickets import TICKET_EFFECTS, TicketBudget, TicketRegistry, TicketScope
from probos.agent_stop import AgentStopService
from probos.identity_service import IdentityService

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

#: AD-1346 M3d2 (D113): the scope and budget ``hold`` asks for: both effect points, no ceiling (M5 owns accounts).
_WORK_SCOPE: Final = TicketScope(frozenset(TICKET_EFFECTS))
_NO_CEILINGS: Final = TicketBudget()


class AdmissionService:
    """Ship's Computer service: one admission decision per unit of work, in shadow (AD-1346 M3)."""

    def __init__(
        self,
        identity_service: IdentityService,
        stop_service: AgentStopService,
        *,
        clock: Callable[[], int] = time.perf_counter_ns,
        recorder: ShadowRecorder | None = None,
        tickets: TicketRegistry | None = None,
    ) -> None:
        if not isinstance(identity_service, IdentityService):
            raise TypeError("AdmissionService needs the IdentityService facade")
        if not isinstance(stop_service, AgentStopService):
            raise TypeError("AdmissionService needs the AgentStopService record")
        if recorder is not None and not isinstance(recorder, ShadowRecorder):
            raise TypeError("AdmissionService takes a ShadowRecorder or None")
        if tickets is not None and not isinstance(tickets, TicketRegistry):
            raise TypeError("AdmissionService takes a TicketRegistry or None")
        self._identities = identity_service
        self._stops = stop_service
        self._clock = clock
        self._recorder = recorder
        self._tickets = tickets  # AD-1346 M3d2: compared with None, never by truth (an empty registry is falsy)
        self._closed = False
        self._tally: dict[tuple[str, str, str], int] = {}
        self._latency: list[int] = [0] * LATENCY_BUCKETS
        self._failures = 0

    def decide(self, request: WorkRequest) -> AdmissionVerdict:
        """The verdict for ``request``: the first check in ``CHECK_ORDER`` that refuses, else admit.

        It reads the facade and ``AgentStopService.stop_for`` and nothing else. A dependency
        that raises propagates from here (T12); ``shadow`` holds the ``except Exception``.
        """
        if type(request) is not WorkRequest:
            raise TypeError("AD-1346: decide() takes a WorkRequest")
        principal = resolve_principal(request.presented_id, self._identities)
        finding = check_principal(principal)
        if finding is None:
            finding = check_agent_stop(principal, self._stops)
        outcome = OUTCOME_ADMIT if finding is None else OUTCOME_WOULD_REFUSE
        found = ADMITTED if finding is None else finding
        return AdmissionVerdict(
            outcome=outcome,
            reason_code=found.reason_code,
            check=found.check,
            cause=found.cause,
            key=principal.key,
            principal_kind=principal.kind,
            principal=principal.ref,
            presented_id=request.presented_id,
            work_kind=request.work_kind,
            seam=request.seam,
            origin=request.origin,
            origin_id=request.origin_id,
            stop_id=found.stop_id,
        )

    def shadow(
        self, *, presented_id: str, work_kind: str, seam: str, origin: str, origin_id: str,
        today_outcome: str | None = None,
    ) -> None:
        """Decide in shadow, count the verdict and its latency, offer both and today's outcome to the recorder when there is one, and return None (#1604 property 6; D24, D25, D46, D57, D59).

        After ``close`` it returns None at once and decides, counts and offers nothing (D61).
        ``today_outcome`` is ``TODAY_ADMIT``, ``TODAY_REFUSE`` or None (no parity record); any other
        value is counted and logged as a failure, as is an ``Exception`` from the request, ``decide``
        or the recorder's offer. A log call that raises an ``Exception`` is swallowed (F-212, D59), so
        no ``Exception`` leaves this method; a ``BaseException`` that is not an ``Exception`` propagates.
        """
        if self._closed:
            return None
        try:
            if today_outcome is not None and (type(today_outcome) is not str or today_outcome not in TODAY_OUTCOMES):
                raise ValueError(f"AD-1346: unknown today_outcome {today_outcome!r}")
            request = WorkRequest(presented_id, work_kind, seam, origin, origin_id)
            started = self._clock()
            verdict = self.decide(request)
            elapsed = self._clock() - started
            self._count(verdict, elapsed)
            if self._recorder is not None:
                self._recorder.offer(verdict, elapsed, today_outcome=today_outcome)
        except Exception:
            self._failures += 1
            try:
                logger.log(
                    logging.WARNING if self._failures == 1 else logging.DEBUG,
                    "AD-1346 M3b: a shadow admission decision, or the recorder's offer, raised (%d so far); shadow() returned None to its caller",
                    self._failures,
                    exc_info=True,
                )
            except Exception:  # noqa: BLE001 -- F-212 (D59): a logging handler that raised must not reach the seam
                pass  # the failure is already counted in ``failures``
        return None

    def close(self) -> None:
        """Decide and issue nothing from now on: a later ``shadow`` returns None at once and a later ``hold`` returns ``NO_HOLD``; ``decide`` is unaffected (AD-1346 M3c, D61; M3d2)."""
        self._closed = True

    def hold(self, *, presented_id: str, work_kind: str, seam: str, child: bool) -> TicketHold:
        """Issue the work ticket of one unit an entry's own stop check admitted and put it in the carrier (AD-1346 M3d2).

        ``probos.admission.seam.hold_at`` calls it. With no registry, or after ``close``, it returns ``NO_HOLD`` and
        issues nothing. Otherwise the ticket's principal is the key ``decide`` gives the presented id (the slot when it
        resolves, D112); ``hold`` asks for both effect points and no ceiling (D113). The ticket is a child of the carried
        ticket when ``child is True`` and the carrier holds one, else a root (D111). The carrier then holds the new
        ticket, or None when the registry refused the issue and counted its finding (D114).
        An ``Exception`` raised here is counted in ``failures`` and logged; a
        ``BaseException`` that is not an ``Exception`` propagates.
        """
        if self._closed or self._tickets is None:
            return NO_HOLD
        try:
            key = resolve_principal(presented_id, self._identities).key
            parent = CURRENT_TICKET.get() if child is True else None
            if parent is None:
                issued = self._tickets.issue(
                    principal_key=key, work_kind=work_kind, seam=seam, scope=_WORK_SCOPE, budget=_NO_CEILINGS,
                )
            else:
                issued = self._tickets.issue_child(
                    parent, principal_key=key, work_kind=work_kind, seam=seam, scope=_WORK_SCOPE, budget=_NO_CEILINGS,
                )
            token = CURRENT_TICKET.set(issued.ticket)
            return TicketHold(self._tickets, issued.ticket, token)
        except Exception:  # D114: counted and logged
            self._failures += 1
            try:
                logger.log(
                    logging.WARNING if self._failures == 1 else logging.DEBUG,
                    "AD-1346 M3d2: a work ticket's issue raised (%d failures so far); hold() returned NO_HOLD",
                    self._failures,
                    exc_info=True,
                )
            except Exception:  # noqa: BLE001 -- F-212 (D59): a logging handler that raised must not reach the entry
                pass  # the failure is already counted in ``failures``
            return NO_HOLD

    def _count(self, verdict: AdmissionVerdict, elapsed_ns: int) -> None:
        key = (verdict.seam, verdict.work_kind, verdict.reason_code)
        self._tally[key] = self._tally.get(key, 0) + 1
        self._latency[min(elapsed_ns.bit_length(), LATENCY_BUCKETS - 1)] += 1

    def tally(self) -> dict[tuple[str, str, str], int]:
        """Shadow verdicts by (seam, work kind, reason code) since this service was built; a copy."""
        return dict(self._tally)

    def latency_histogram(self) -> tuple[int, ...]:
        """Shadow verdicts by log2 bucket of ``decide`` time in ns (D30); a copy."""
        return tuple(self._latency)

    @property
    def failures(self) -> int:
        """Exceptions that the ``except Exception`` of ``shadow`` or of ``hold`` counted since this service was built."""
        return self._failures
