"""AD-1346 M3a (#1604): the request a seam describes and the verdict the shadow decision returns.

``AdmissionVerdict.to_dict()`` is the record AD-1346 M3b will persist. ``VERDICT_KEYS`` is
its key order and is append-only, the discipline of ``IDENTITY_REF_KEYS``: a later key is
appended, and none of these is renamed, removed or retyped. The principal is embedded as
``IdentityRef.to_dict()``, and a verdict is keyed on the ref's ``slot_id`` (the binding on
M3, #1601).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from probos.admission.taxonomy import (
    ORIGINS,
    OUTCOME_ADMIT,
    OUTCOMES,
    PRINCIPAL_KINDS,
    REASON_ADMITTED,
    REASON_CODES,
    SEAMS,
    WORK_KINDS,
)

if TYPE_CHECKING:
    from probos.identity_service import IdentityRef

#: AD-1346 M3a (v1): the keys of ``AdmissionVerdict.to_dict()``, in order. Append-only.
VERDICT_KEYS: tuple[str, ...] = (
    "outcome", "reason_code", "check", "cause", "key", "principal_kind", "principal",
    "presented_id", "work_kind", "seam", "origin", "origin_id", "stop_id",
)

_REQUEST_FIELDS: tuple[str, ...] = ("presented_id", "work_kind", "seam", "origin", "origin_id")


@dataclass(frozen=True, slots=True)
class WorkRequest:
    """One unit of work as a seam describes it.

    ``presented_id`` is the identity the work runs under, in any form ``IdentityService.resolve``
    takes, or a system principal (the ``system:`` prefix). ``origin`` and ``origin_id`` name who
    asked for it; M3a records them and no check reads them. A field that is not an exact ``str``
    raises ``TypeError``; a ``work_kind``, ``seam`` or ``origin`` outside its set raises
    ``ValueError``. An empty ``presented_id`` is accepted: the decision refuses it.
    """

    presented_id: str
    work_kind: str
    seam: str
    origin: str
    origin_id: str

    def __post_init__(self) -> None:
        for name in _REQUEST_FIELDS:
            if type(getattr(self, name)) is not str:
                raise TypeError(f"WorkRequest.{name} must be a str")
        if self.work_kind not in WORK_KINDS:
            raise ValueError(f"AD-1346: unknown work kind {self.work_kind!r}")
        if self.seam not in SEAMS:
            raise ValueError(f"AD-1346: unknown seam {self.seam!r}")
        if self.origin not in ORIGINS:
            raise ValueError(f"AD-1346: unknown origin {self.origin!r}")


@dataclass(frozen=True, slots=True)
class AdmissionVerdict:
    """What the shadow decision found for one ``WorkRequest``. It blocks nothing.

    ``outcome`` is ``admit`` with ``reason_code`` ``admitted`` and an empty ``check``, or
    ``would_refuse`` with the code and the name of the check that refused (D18). ``key`` is the
    principal's ``slot_id`` when it resolved, the system principal's id, or else the presented
    id (D6). ``cause`` is built from ids (D29). ``stop_id`` names the Captain's stop for
    ``agent_stopped`` and is ``""`` otherwise.
    """

    outcome: str
    reason_code: str
    check: str
    cause: str
    key: str
    principal_kind: str
    principal: IdentityRef | None
    presented_id: str
    work_kind: str
    seam: str
    origin: str
    origin_id: str
    stop_id: str

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES or self.reason_code not in REASON_CODES:
            raise ValueError(f"AD-1346: unknown outcome or reason code {self.outcome!r}, {self.reason_code!r}")
        if (self.outcome == OUTCOME_ADMIT) != (self.reason_code == REASON_ADMITTED):
            raise ValueError("AD-1346: an admit carries the code admitted, and a refusal does not")
        if self.principal_kind not in PRINCIPAL_KINDS:
            raise ValueError(f"AD-1346: unknown principal kind {self.principal_kind!r}")

    def to_dict(self) -> dict[str, Any]:
        """The stable JSON form: ``VERDICT_KEYS`` in order, the principal as ``IdentityRef.to_dict()`` or None."""
        body: dict[str, Any] = {name: getattr(self, name) for name in VERDICT_KEYS}
        if self.principal is not None:
            body["principal"] = self.principal.to_dict()
        return body
