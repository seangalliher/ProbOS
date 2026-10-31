"""AD-1346 M3c, M3d2 and M3d3a (#1604): the statements a site adds beside its own stop check, and at an effect point.

``shadow_at`` hands the site's work to ``AdmissionService.shadow`` with what the site's own check
did (``refused``) and returns None, so the site has no result to act on. It calls only an exact
``AdmissionService``: None, a test double or any other object is passed over. It awaits nothing.
It raises no ``Exception``: its own work is one type check and
one call with the keywords ``shadow`` takes, and ``shadow`` lets no ``Exception`` out (D59); a
``BaseException`` that is not an ``Exception`` propagates.

``hold_at`` (AD-1346 M3d2) hands one entry's admitted unit to ``AdmissionService.hold`` for an exact
``AdmissionService`` and returns its ``TicketHold``; for anything else it returns ``NO_HOLD``. The entry's only use of
the hold is its ``end()`` in a ``finally`` (``tests/test_ad1346_admission_ticket_issue.py``, I10). It awaits nothing
and raises no ``Exception``: ``hold`` lets none out.

``check_at`` (AD-1346 M3d3a) hands one effect point's call to ``AdmissionService.check_ticket`` for an exact
``AdmissionService``; for anything else it does nothing. The tool sink and the model gateway call it
(``tests/test_ad1346_admission_ticket_sinks.py``, SK7), and from AD-1346 M3e1 the subprocess sinks, seven from AD-1346
M3e2a (``tests/test_ad1346_admission_effect_census.py``, EC3). It returns None, awaits nothing and raises no ``Exception``:
``check_ticket`` lets none out.
"""

from __future__ import annotations

from probos.admission.carrier import NO_HOLD, TicketHold
from probos.admission.service import AdmissionService
from probos.admission.taxonomy import TODAY_ADMIT, TODAY_REFUSE


def shadow_at(
    service: object, *, presented_id: str, work_kind: str, seam: str, origin: str, origin_id: str, refused: bool,
) -> None:
    """Shadow one unit of work at a stop-check site: today's outcome is ``TODAY_REFUSE`` when ``refused is True``, else ``TODAY_ADMIT``."""
    if type(service) is not AdmissionService:
        return None
    service.shadow(
        presented_id=presented_id, work_kind=work_kind, seam=seam, origin=origin, origin_id=origin_id,
        today_outcome=TODAY_REFUSE if refused is True else TODAY_ADMIT,
    )
    return None


def hold_at(service: object, *, presented_id: str, work_kind: str, seam: str, child: bool) -> TicketHold:
    """The ticket hold of one unit an entry's own stop check admitted: ``AdmissionService.hold`` for an exact service, else ``NO_HOLD``."""
    if type(service) is AdmissionService:
        return service.hold(presented_id=presented_id, work_kind=work_kind, seam=seam, child=child)
    return NO_HOLD


def check_at(service: object, *, effect: str, presented_id: object) -> None:
    """The sink check of one effect point, in shadow: ``AdmissionService.check_ticket`` for an exact service, else nothing."""
    if type(service) is AdmissionService:  # an exact service; None, a double or any other object is passed over
        service.check_ticket(effect=effect, presented_id=presented_id)
    return None
