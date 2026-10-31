"""AD-1346 M3a (#1604): the closed vocabularies of the shadow admission decision.

Each vocabulary here is a set of values a verdict carries or, for ``TODAY_OUTCOMES`` (AD-1346
M3c), a value recorded beside one, or, for ``TICKET_REASON_CODES`` (AD-1346 M3d1), the code a
work-ticket finding carries. ``admission_shadow.db`` persists the verdict's values and today's
outcome, and the ticket codes keep the same rule, so each is append-only:
a value is added by the slice that needs it and is not renamed or removed.
The seams extend the stop's ``SEAMS``, imported from ``probos.agent_stop``, because seam
names key the stop's persisted refusal counts (AD-1343 S1). The reason codes and the ticket codes
use the AD-1316 stable-code syntax (``execution/authority.py``, ``_REASON_CODE_RE``), shared by
syntax and not imported (D8).
"""

from __future__ import annotations

from typing import Final

from probos.agent_stop import SEAMS as STOP_SEAMS
from probos.agent_stop import STOP_REASON_CODE

#: Effect points that are not a stop seam. AD-1346 M3d puts the model gateway's call here.
SEAM_MODEL_CALL: Final = "model_call"
EFFECT_SEAMS: Final[frozenset[str]] = frozenset({SEAM_MODEL_CALL})
SEAMS: Final[frozenset[str]] = STOP_SEAMS | EFFECT_SEAMS
#: AD-1346 M3e1 (D161): the effect a subprocess sink checks a work ticket for, a member of ``TICKET_EFFECTS``. It is not
#: a seam: no verdict names it, so ``SEAMS`` and the verdicts' per-day bounds do not move. Append-only, as the codes are.
EFFECT_SUBPROCESS: Final = "subprocess"

#: v1 (D20): the work the stop seams admit, plus effect-point calls whose unit is not yet known.
WORK_KINDS: Final[tuple[str, ...]] = (
    "intent",
    "consultation",
    "proactive_cycle",
    "ward_room_notice",
    "direct_message",
    "group_turn",
    "browser_action",
    "agentic_run",
    "delegated_task",
    "tool_call",
    "model_call",
    "agent_work",  # AD-1346 M3c3: work an agent creates for itself or requests from a colleague (AD-1347)
)

#: Who asked for the work (recorded; no M3a check reads it, D23).
ORIGINS: Final[tuple[str, ...]] = ("captain", "agent", "system", "federation_peer")

PRINCIPAL_CERTIFICATE: Final = "certificate"
PRINCIPAL_ASSET: Final = "asset"
PRINCIPAL_SYSTEM: Final = "system"
PRINCIPAL_UNRESOLVED: Final = "unresolved"
PRINCIPAL_KINDS: Final[tuple[str, ...]] = (
    PRINCIPAL_CERTIFICATE, PRINCIPAL_ASSET, PRINCIPAL_SYSTEM, PRINCIPAL_UNRESOLVED,
)

OUTCOME_ADMIT: Final = "admit"
OUTCOME_WOULD_REFUSE: Final = "would_refuse"
OUTCOMES: Final[tuple[str, ...]] = (OUTCOME_ADMIT, OUTCOME_WOULD_REFUSE)

#: AD-1346 M3c (D57): what the site's own stop check did with the same work, for parity (#1601 evidence 4).
TODAY_ADMIT: Final = "admit"
TODAY_REFUSE: Final = "refuse"
TODAY_OUTCOMES: Final[tuple[str, ...]] = (TODAY_ADMIT, TODAY_REFUSE)

REASON_ADMITTED: Final = "admitted"
REASON_AGENT_STOPPED: Final = STOP_REASON_CODE
REASON_IDENTITY_UNRESOLVED: Final = "identity_unresolved"
REASON_SYSTEM_PRINCIPAL_UNLISTED: Final = "system_principal_unlisted"
REASON_CODES: Final[tuple[str, ...]] = (
    REASON_ADMITTED, REASON_AGENT_STOPPED, REASON_IDENTITY_UNRESOLVED, REASON_SYSTEM_PRINCIPAL_UNLISTED,
)

#: AD-1346 M3d1: the work-ticket codes (``probos.admission.tickets``), a second closed vocabulary of this one
#: taxonomy. Each fits the AD-1316 syntax and none is in ``REASON_CODES``: a ticket finding carries one and an
#: ``AdmissionVerdict`` never does, so the per-day bounds computed over ``REASON_CODES`` do not move. Append-only.
TICKET_ISSUED: Final = "ticket_issued"
TICKET_LIVE: Final = "ticket_live"
TICKET_MISSING: Final = "ticket_missing"
TICKET_UNKNOWN: Final = "ticket_unknown"
TICKET_TEST_REFUSED: Final = "ticket_test_refused"
TICKET_REVOKED: Final = "ticket_revoked"
TICKET_EXPIRED: Final = "ticket_expired"
TICKET_PRINCIPAL_MISMATCH: Final = "ticket_principal_mismatch"
TICKET_OUT_OF_SCOPE: Final = "ticket_out_of_scope"
TICKET_WIDENED: Final = "ticket_widened"
TICKET_TOO_DEEP: Final = "ticket_too_deep"
TICKET_REGISTRY_FULL: Final = "ticket_registry_full"
TICKET_REASON_CODES: Final[tuple[str, ...]] = (
    TICKET_ISSUED, TICKET_LIVE, TICKET_MISSING, TICKET_UNKNOWN, TICKET_TEST_REFUSED, TICKET_REVOKED, TICKET_EXPIRED,
    TICKET_PRINCIPAL_MISMATCH, TICKET_OUT_OF_SCOPE, TICKET_WIDENED, TICKET_TOO_DEEP, TICKET_REGISTRY_FULL,
)

CHECK_PRINCIPAL: Final = "principal"
CHECK_AGENT_STOP: Final = "agent_stop"
#: D5: the principal is resolved and checked before the stop, because stops are keyed by slot.
CHECK_ORDER: Final[tuple[str, ...]] = (CHECK_PRINCIPAL, CHECK_AGENT_STOP)
#: The epic's other checks, by name and owner; none runs in M3a.
DEFERRED_CHECKS: Final[tuple[tuple[str, str], ...]] = (
    ("vessel_stop", "AD-1343 S3, built in AD-1346 M4"),
    ("lifecycle_acm", "AD-1346 M3f"),
    ("earned_agency", "AD-1346 M3f"),
    ("scope_clearance", "AD-1346 M3f"),
    ("budget_reservation", "AD-1346 M3f"),
    ("pre_intent_hooks", "AD-698, AD-1346 M3f"),
)

SYSTEM_PRINCIPAL_PREFIX: Final = "system:"
#: D17: grows by census in AD-1346 M3e. From AD-1346 M3e1, EC5 (``tests/test_ad1346_admission_effect_census.py``)
#: holds it equal to the principals of the subprocess census's system rows and the ``system:`` literals a seam statement
#: presents (D166).
SYSTEM_PRINCIPALS: Final[frozenset[str]] = frozenset({"system:ship_computer"})

#: D30: log2 buckets of ``decide`` time in integer nanoseconds.
LATENCY_BUCKETS: Final = 40
