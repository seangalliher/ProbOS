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
AD-1346 M3d3a added ``check_ticket``: ``probos.admission.seam.check_at`` calls it at the tool sink and the model
gateway, and nothing is refused. A service built with an event loop checks on that loop: a sink on
another thread, or on another thread's loop, hands its check there with ``call_soon_threadsafe`` (D128). A sink check
that raises an ``Exception`` in ``_check_ticket`` is counted in ``failures`` and logged, as ``hold``'s is.
AD-1346 M3d3b2: a service built with a recorder also hands the finding of each issue and of each sink check that the
registry answers, in ``hold`` and in ``_check_ticket``, to ``ShadowRecorder.offer_ticket``, inside the same ``try`` and,
in ``hold``, before the carrier is set; an ``Exception`` from that offer is counted in ``failures`` and logged as the
rest of that ``try``'s are.
AD-1346 M3e1: ``check_at`` is also called at subprocess sinks (five from M3e1, seven from AD-1346 M3e2a) with the effect
``subprocess``, which ``TICKET_EFFECTS`` now holds, so the scope ``hold`` asks for includes it.
The service reads no configuration.
"""

from __future__ import annotations

import asyncio
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

#: AD-1346 M3d2 (D113): the scope and budget ``hold`` asks for: every effect point of ``TICKET_EFFECTS`` (three from
#: AD-1346 M3e1), no ceiling (M5 owns accounts).
_WORK_SCOPE: Final = TicketScope(frozenset(TICKET_EFFECTS))
_NO_CEILINGS: Final = TicketBudget()


def _running_loop() -> asyncio.AbstractEventLoop | None:
    """The loop running on this thread, or None (``asyncio.get_running_loop`` raises ``RuntimeError`` when none runs)."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


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
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        if not isinstance(identity_service, IdentityService):
            raise TypeError("AdmissionService needs the IdentityService facade")
        if not isinstance(stop_service, AgentStopService):
            raise TypeError("AdmissionService needs the AgentStopService record")
        if recorder is not None and not isinstance(recorder, ShadowRecorder):
            raise TypeError("AdmissionService takes a ShadowRecorder or None")
        if tickets is not None and not isinstance(tickets, TicketRegistry):
            raise TypeError("AdmissionService takes a TicketRegistry or None")
        if loop is not None and not isinstance(loop, asyncio.AbstractEventLoop):
            raise TypeError("AdmissionService takes an event loop or None")
        self._identities = identity_service
        self._stops = stop_service
        self._clock = clock
        self._recorder = recorder
        self._tickets = tickets  # AD-1346 M3d2: compared with None, never by truth (an empty registry is falsy)
        self._loop = loop  # AD-1346 M3d3a (D128): the loop its sink checks run on; None checks in place (tests)
        self._off_loop: dict[str, int] = {}  # AD-1346 M3d3a: checks handed to that loop from elsewhere, by effect
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
        """Decide, issue and check nothing from now on: a later ``shadow`` returns None at once, a later ``hold`` returns ``NO_HOLD`` and a later sink check, or one handed to the loop before this call, checks nothing; ``decide`` is unaffected (AD-1346 M3c, D61; M3d2; M3d3a)."""
        self._closed = True

    def hold(self, *, presented_id: str, work_kind: str, seam: str, child: bool) -> TicketHold:
        """Issue the work ticket of one unit an entry's own stop check admitted and put it in the carrier (AD-1346 M3d2).

        ``probos.admission.seam.hold_at`` calls it. With no registry, or after ``close``, it returns ``NO_HOLD`` and
        issues nothing. Otherwise the ticket's principal is the key ``decide`` gives the presented id (the slot when it
        resolves, D112); ``hold`` asks for every effect point of ``TICKET_EFFECTS`` and no ceiling (D113; AD-1346 M3e1
        added ``subprocess``). The ticket is a child of the carried
        ticket when ``child is True`` and the carrier holds one, else a root (D111). The carrier then holds the new
        ticket, or None when the registry refused the issue and counted its finding (D114).
        AD-1346 M3d3b2 (D152): with a recorder, the issue's finding is offered to ``ShadowRecorder.offer_ticket`` before
        the carrier is set, so an offer that raises leaves the carrier as it was; for an ``Exception``, an entry the
        issue added stays registered and ``hold`` returns ``NO_HOLD``.
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
            if self._recorder is not None:  # AD-1346 M3d3b2 (D152): before the carrier is set, so a raising offer leaves it
                self._recorder.offer_ticket(issued.finding, off_loop=False)
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

    def check_ticket(self, *, effect: str, presented_id: object) -> None:
        """The sink check of one effect point, in shadow: the registry's finding for the ticket the carrier holds (AD-1346 M3d3a).

        ``probos.admission.seam.check_at`` calls it at the tool sink, the model gateway and, from AD-1346 M3e1, the
        subprocess sinks (seven from AD-1346 M3e2a). It reads the carrier in the
        caller's context. On the loop the service was built with, or on any thread when it was built with none, it checks
        at once (``_check_ticket``). Anywhere else (another thread, or another thread's loop) it hands the check, with the
        ticket it read, to that loop with ``call_soon_threadsafe``, so a service built with a loop makes its sink
        checks on that loop's thread (D128). A hand-off that raises an ``Exception`` (a
        closed loop raises ``RuntimeError``) checks and counts nothing. It returns None, so a sink has nothing to act
        on; no ``Exception`` leaves it, and a ``BaseException`` that is not an ``Exception`` propagates.
        """
        ticket = CURRENT_TICKET.get()
        if self._loop is None or _running_loop() is self._loop:
            self._check_ticket(ticket, effect, presented_id, False)
            return None
        try:
            self._loop.call_soon_threadsafe(self._check_ticket, ticket, effect, presented_id, True)
        except Exception:  # noqa: BLE001 -- D128: a hand-off that raises (a closed loop) checks and counts nothing
            pass  # off the loop nothing may be counted: the counts are the loop's (D99)
        return None

    def _check_ticket(self, ticket: object, effect: str, presented_id: object, off_loop: bool) -> None:
        """One sink check on the service's loop, or in place: the registry counts its finding for ``ticket`` at ``effect``.

        With no registry, or after ``close`` (a check handed over before it included), it checks nothing. The principal
        compared is the key ``decide`` gives ``presented_id`` when that is a non-empty ``str``, else none. A check handed
        over from elsewhere is counted in ``off_loop_checks`` once answered. AD-1346 M3d3b2 (D152): with a recorder, the
        finding is then offered to ``ShadowRecorder.offer_ticket`` with ``off_loop``, on the thread the check ran on.
        An ``Exception`` is counted in ``failures``
        and logged, as ``hold``'s is; a ``BaseException`` that is not an ``Exception`` propagates.
        """
        if self._closed or self._tickets is None:  # no registry, or closed (a check handed over before close included): nothing is checked
            return None
        try:
            key = resolve_principal(presented_id, self._identities).key if type(presented_id) is str and presented_id else ""
            finding = self._tickets.check(ticket, effect=effect, presented_key=key)
            if off_loop:
                self._off_loop[effect] = self._off_loop.get(effect, 0) + 1
            if self._recorder is not None:  # AD-1346 M3d3b2 (D152): after the off-loop count, on the thread of the check
                self._recorder.offer_ticket(finding, off_loop=off_loop)
        except Exception:  # D129: counted and logged; the sink gets None
            self._failures += 1
            try:
                logger.log(
                    logging.WARNING if self._failures == 1 else logging.DEBUG,
                    "AD-1346 M3d3a: a work ticket's sink check raised (%d failures so far); check_ticket() returned None to the sink",
                    self._failures,
                    exc_info=True,
                )
            except Exception:  # noqa: BLE001 -- F-212 (D59): a logging handler that raised must not reach the sink
                pass  # the failure is already counted in ``failures``
        return None

    def off_loop_checks(self) -> dict[str, int]:
        """Sink checks handed to the service's loop from another thread or loop and answered there by the registry, by effect, since this service was built; a copy."""
        return dict(self._off_loop)

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
        """Exceptions that the ``except Exception`` of ``shadow``, of ``hold`` or of a sink check (``_check_ticket``) counted since this service was built."""
        return self._failures
