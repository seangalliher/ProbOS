"""AD-1346 M3a (#1604): the two checks of the shadow decision, in ``CHECK_ORDER``.

``resolve_principal`` turns the presented id into the principal the checks read.
``check_principal`` refuses an unresolved principal and a system principal outside
``SYSTEM_PRINCIPALS``. ``check_agent_stop`` reads the Captain's stop record with
``AgentStopService.stop_for``, keyed on the principal's slot id (stops are keyed by slot,
``routers/agent_stop.py``). It does not call ``refusal`` or the ``active_stop`` helper:
those count a refusal, and the counts are the order's final counts at a lift (AD-1343 S1).

Each check returns None or a ``Finding``. The functions here hold no state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from probos.admission.taxonomy import (
    CHECK_AGENT_STOP,
    CHECK_PRINCIPAL,
    PRINCIPAL_ASSET,
    PRINCIPAL_CERTIFICATE,
    PRINCIPAL_SYSTEM,
    PRINCIPAL_UNRESOLVED,
    REASON_ADMITTED,
    REASON_AGENT_STOPPED,
    REASON_IDENTITY_UNRESOLVED,
    REASON_SYSTEM_PRINCIPAL_UNLISTED,
    SYSTEM_PRINCIPAL_PREFIX,
    SYSTEM_PRINCIPALS,
)

if TYPE_CHECKING:
    from probos.agent_stop import AgentStopService
    from probos.identity_service import IdentityRef, IdentityService


@dataclass(frozen=True, slots=True)
class Principal:
    """Who the work runs under: its kind, the key a verdict aggregates on, and the ref when one resolved."""

    kind: str
    key: str
    ref: IdentityRef | None


@dataclass(frozen=True, slots=True)
class Finding:
    """One check's answer: the check, the reason code, the cause and the stop it names (``""`` for none)."""

    check: str
    reason_code: str
    cause: str
    stop_id: str


#: The finding an admit carries: no check, the code ``admitted``, no stop.
ADMITTED: Final = Finding("", REASON_ADMITTED, "Admitted: no check refused.", "")


def resolve_principal(presented_id: str, identities: IdentityService) -> Principal:
    """The principal of a presented id: a resolved ref first, then a system principal, else unresolved (D22)."""
    ref = identities.resolve(presented_id)
    if ref is not None:
        kind = PRINCIPAL_CERTIFICATE if ref.did else PRINCIPAL_ASSET
        return Principal(kind, ref.slot_id, ref)
    if presented_id.startswith(SYSTEM_PRINCIPAL_PREFIX):
        return Principal(PRINCIPAL_SYSTEM, presented_id, None)
    return Principal(PRINCIPAL_UNRESOLVED, presented_id, None)


def check_principal(principal: Principal) -> Finding | None:
    """Refuse an unresolved principal (D6) and a system principal not on the allowlist (D17)."""
    if principal.kind == PRINCIPAL_UNRESOLVED:
        cause = f"No agent identity resolves from the presented id {principal.key!r}."
        return Finding(CHECK_PRINCIPAL, REASON_IDENTITY_UNRESOLVED, cause, "")
    if principal.kind == PRINCIPAL_SYSTEM and principal.key not in SYSTEM_PRINCIPALS:
        cause = f"The system principal {principal.key!r} is not on the system-principal allowlist."
        return Finding(CHECK_PRINCIPAL, REASON_SYSTEM_PRINCIPAL_UNLISTED, cause, "")
    return None


def check_agent_stop(principal: Principal, stops: AgentStopService) -> Finding | None:
    """Refuse a principal whose slot is under a Captain's stop, read with ``stop_for``, which counts nothing."""
    if principal.ref is None:
        return None
    record = stops.stop_for(principal.ref.slot_id)
    if record is None:
        return None
    cause = f"Agent {record.agent_id} is under the Captain's stop {record.stop_id}."
    return Finding(CHECK_AGENT_STOP, REASON_AGENT_STOPPED, cause, record.stop_id)
