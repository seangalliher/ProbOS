"""AD-1346 M3a (#1604): the closed vocabularies of the shadow admission decision.

Each tuple here is a set of values a verdict carries and AD-1346 M3b will persist, so each
is append-only: a value is added by the slice that needs it and is not renamed or removed.
The seams extend the stop's ``SEAMS``, imported from ``probos.agent_stop``, because seam
names key the stop's persisted refusal counts (AD-1343 S1). The reason codes use the
AD-1316 stable-code syntax (``execution/authority.py``, ``_REASON_CODE_RE``), shared by
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

REASON_ADMITTED: Final = "admitted"
REASON_AGENT_STOPPED: Final = STOP_REASON_CODE
REASON_IDENTITY_UNRESOLVED: Final = "identity_unresolved"
REASON_SYSTEM_PRINCIPAL_UNLISTED: Final = "system_principal_unlisted"
REASON_CODES: Final[tuple[str, ...]] = (
    REASON_ADMITTED, REASON_AGENT_STOPPED, REASON_IDENTITY_UNRESOLVED, REASON_SYSTEM_PRINCIPAL_UNLISTED,
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
#: D17: grows by census in AD-1346 M3e.
SYSTEM_PRINCIPALS: Final[frozenset[str]] = frozenset({"system:ship_computer"})

#: D30: log2 buckets of ``decide`` time in integer nanoseconds.
LATENCY_BUCKETS: Final = 40
