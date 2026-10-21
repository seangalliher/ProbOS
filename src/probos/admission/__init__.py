"""AD-1346 M3a (#1604): the shadow admission decision of epic #1601.

``AdmissionService`` decides once per unit of work and, in shadow, blocks nothing. The
vocabularies are in ``probos.admission.taxonomy``. A top-level package, unranked by the
layer map; ``tests/test_ad1346_admission_service.py`` (T14) pins what it may import.
"""

from probos.admission.record import VERDICT_KEYS, AdmissionVerdict, WorkRequest
from probos.admission.service import AdmissionService

__all__ = ["VERDICT_KEYS", "AdmissionService", "AdmissionVerdict", "WorkRequest"]
