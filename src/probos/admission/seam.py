"""AD-1346 M3c and M3d2 (#1604): the statements a site adds beside its own stop check.

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
