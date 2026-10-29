"""AD-1346 M3c (#1604): the one statement a stop-check site adds beside its own check.

``shadow_at`` hands the site's work to ``AdmissionService.shadow`` with what the site's own check
did (``refused``) and returns None, so the site has no result to act on. It calls only an exact
``AdmissionService``: None, a test double or any other object is passed over. It awaits nothing.
It raises no ``Exception``: its own work is one type check and
one call with the keywords ``shadow`` takes, and ``shadow`` lets no ``Exception`` out (D59); a
``BaseException`` that is not an ``Exception`` propagates.
"""

from __future__ import annotations

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
