# AD-1346 M3a: the inert shadow `AdmissionService` library (epic #1601, child #1604, slice M3a)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-20
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-21, after a read-only conformance check against the #1604 design memo: four text-only repairs (the memo's D15 and D16 labels, acceptance 7, and D33's disclosed replacement of the memo's "zero-config boot" test); no code change. **Orchestrator corrections, 2026-10-21, found by applying the whole contract to a scratch tree:** the `DECISIONS.md` anchor of Section 5b (the draft's anchor would have put the entry before M1a's and BF-910's) and Section 5c (the AD-ledger regeneration the gate's `ad-ledger` phase needs); no code change.
**Status:** build-ready contract. **Tier: HIGH** (governance; a shared record contract that M3b persists). Confirmed, not lowered.
**Number:** rides under **AD-1346** (the epic), as M1a does. No new number. Ceiling run 2026-10-20 with `scripts/ad_ceiling.py` on this tree: AD-1346 from all three sources (git subjects, 1,451 issue titles in all states, 95 prompt filenames); next free AD-1347. No BF is allocated here.
**Base:** `origin/main` `e237c3525a4eb7432fbf50fab042bc0c5efd4dbe` (BF-910 merged, PR #1611, on top of AD-1346 M1a, PR #1610 `5548a476`). The contract was drafted on `5548a476`; on 2026-10-21 its code, tests and 37 mutation rows were run on a scratch tree at `5548a476` (the 19 tests pass, 37 of 37 mutants are killed), and all seven SEARCH pairs were re-checked to match exactly once on `e237c352`; BF-910 edits none of the files this contract edits except the two trackers. The working tree checks out CRLF and the index holds LF (`git ls-files --eol`): match the SEARCH blocks line by line, not byte by byte.
**Binding design:** the Architect's memo on #1604 (comment 6306056229: slice table, D1 to D17, hidden pins, the Ship Trial deviation), the corrected binding on M3 (comment 6304627643 on #1601; `DECISIONS.md:416`), the S1 constraints (comment 6283928462 on #1595). This contract adds D18 to D35.
**Dependencies:** AD-1346 M1a (`IdentityRef`, `IdentityService`), AD-1343 S1 (`AgentStopService`). **Blocks:** M3b (the store), M3c (the seams).
**Not concurrent with:** M2 (#1601; `startup/finalize.py`, which this slice does not touch) is not a conflict. BF-910 merged first (PR #1611, `e237c352`); the four `runtime.py` anchors and the one `shutdown.py` anchor were re-verified on it (see Base).
**Estimated tests:** 19 new (16 unit and structural in `tests/test_ad1346_admission_service.py`, 3 real-boot in `tests/test_ad1346_admission_service_boot.py`). No existing test changes.

---

## Problem

Epic #1601 decides admission once per unit of work. #1604 (M3) proves the decision in shadow before anything depends on it. The memo slices M3 into M3a to M3e; this is M3a: the decision as a library, built at boot, called by nothing.

What exists on this tree, read for this contract:

- The identity facade: `src/probos/identity_service.py:66-135` (`IdentityService.resolve`, `:79-95`; `IdentityRef`, `:34-63`; `IDENTITY_REF_KEYS`, `:31`). A cert ref has the certificate's DID (`:119-125`); an asset ref has `did=""` (`:128-134`).
- The Captain's stop record: `src/probos/agent_stop.py`. `stop_for` reads memory and counts nothing (`:373-377`); `refusal` counts a refusal per seam (`:379-393`), and the counts are final at a lift (`:439-441`). `SEAMS` (`:70-73`), `STOP_REASON_CODE = "agent_stopped"` (`:49`). `StopRecord.sender_text()` says "Nothing was started and nothing is queued for later" (`:237-243`).
- Stops are keyed by slot id: the stop route resolves any key to the slot before it issues or lifts (`src/probos/routers/agent_stop.py:62-66`, `:100-109`, `:134-136`).
- The boot: `runtime.py:2773-2774` starts `AgentStopService` in Phase 1a; `:2816-2818` builds `IdentityService`; `:2820` calls `create_agent_fleet`. Shutdown releases the facade in the identity-registry block (`startup/shutdown.py:1429-1434`).
- The AD-1316 stable-code syntax: `_REASON_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")` (`execution/authority.py:109`). `AdmissionRequest` and `AdmissionDecision` already exist (`execution/authority.py:481`, `:491`), hence D4's names.

Nothing in `src/` is named `WorkRequest`, `AdmissionVerdict`, `AdmissionService`, `admission_service` or `probos.admission` (Absence Verified, A1).

## Solution

A new top-level package `src/probos/admission/` (D2), five files, no class over 7 methods, no file over about 200 lines:

| File | Holds |
|---|---|
| `__init__.py` | re-exports `AdmissionService`, `AdmissionVerdict`, `WorkRequest`, `VERDICT_KEYS` |
| `taxonomy.py` | the closed vocabularies, `CHECK_ORDER`, `DEFERRED_CHECKS`, the system-principal allowlist, `LATENCY_BUCKETS` |
| `record.py` | `WorkRequest`, `AdmissionVerdict`, `VERDICT_KEYS` |
| `checks.py` | `Principal`, `Finding`, `ADMITTED`, `resolve_principal`, `check_principal`, `check_agent_stop` |
| `service.py` | `AdmissionService`: `decide`, `shadow`, `tally`, `latency_histogram`, `failures` |

`decide(request)` resolves the principal, then runs `check_principal` and, when it passes, `check_agent_stop`; the first finding decides (D18). `shadow(**fields)` builds the request inside its `try`, decides, counts, and returns None (D7, D24). `runtime.start()` builds it right after `IdentityService` and before `create_agent_fleet`, inside a `try` that logs and leaves the attribute None (memo; D34). `shutdown` sets it to None beside `identity_service` (D27).

No caller, no store, no config field, no route, no event type, no persisted schema.

---

## Decisions

D1 to D17 are the memo's and bind this contract (D2 package, D3 `admission_service`, D4 `WorkRequest`/`AdmissionVerdict`, D5 principal before stop, D6 None principal refused and keyed on the presented id, an asset ref admitted, D7 `shadow()` returns None, D8 AD-1316 codes shared by syntax, D15 no config field in M3a, D16 binding on M4: no check is enforced that had no shadow period (M3a enforces nothing), D17 the allowlist starts as `{"system:ship_computer"}`). D11 to D17 are numbered in the memo's order. New here:

| # | Decision | Rejected alternative | Why |
|---|---|---|---|
| D18 | The first check that refuses decides; later checks do not run. The verdict names one `check` (`""` for an admit). | Run every check and record a list of findings | A list is a record shape M3b would freeze for no consumer. In M3a the two checks cannot both refuse one request: `check_principal` refuses only a principal with `ref is None`, and `check_agent_stop` returns None for one (Section 2b). |
| D19 | `taxonomy.SEAMS = agent_stop.SEAMS | EFFECT_SEAMS`, `EFFECT_SEAMS = {"model_call"}`; `STOP_SEAMS` is the imported object. | Copy the ten names | The seam names key the stop's persisted refusal counts (S1 constraint), so they are imported, not restated. `model_call` is the one effect point the epic names that has no stop seam (`tool` already exists, `agent_stop.py:62`). Later effect seams are appended by M3d/M3e. |
| D20 | `WORK_KINDS` v1: `intent`, `consultation`, `proactive_cycle`, `ward_room_notice`, `direct_message`, `group_turn`, `browser_action`, `agentic_run`, `delegated_task`, `tool_call`, `model_call`. Append-only. | Define kinds in M3c when the seams are wired | M3a must close the set to validate a request. These name the work the ten stop seams admit (`agent_stop.py:75-88`), plus `tool_call` and `model_call` for an effect-point call whose enclosing unit is not known before M3d's ticket carrier. Scheduled, holodeck, qualification and federation work are added by the slice that enumerates them (#1604 blind spot 1; the memo marks the holodeck kind unverified). |
| D21 | `PRINCIPAL_KINDS`: `certificate`, `asset`, `system`, `unresolved`. A resolved ref with a non-empty `did` is `certificate`, an empty `did` is `asset`. | `crew` / `agent` | Named by mechanism: the facade sets `did=""` for an asset ref and the certificate's DID otherwise (`identity_service.py:119-134`). Whether a certificate holder is crew is the ontology's question, which M3a does not ask. |
| D22 | The presented id is resolved through the facade first; only an id that does not resolve and starts with `system:` is a system principal. | Test the prefix first | An id that resolves names a slot, and the slot's stop applies to it. Prefix-first would let a `system:`-prefixed slot id skip the stop check. |
| D23 | `origin` and `origin_id` are validated and recorded; no M3a check reads them. | Refuse an agent origin for a system principal | No rule for it is decided; recording first is what the shadow period is for. |
| D24 | `shadow()` takes the five fields keyword-only and builds the `WorkRequest` inside its `try`. | Seams build the request and pass it | A seam that built a request with an unknown seam name would get a `ValueError` at the seam, which changes its behaviour; inside `shadow` it is a counted failure. |
| D25 | A failure in `shadow` increments `failures`; the first is logged at WARNING with the traceback, later ones at DEBUG. | Log every failure at WARNING | `shadow` runs on the dispatch loop for every unit of work from M3c on; one defect would flood the log. Same shape as `refusal` (`agent_stop.py:388-392`). |
| D26 | Constructed positionally as `AdmissionService(identity_service, stop_service, *, clock=...)`. | `agent_stops=` keyword | The census records every call passing a keyword named `agent_stops` (`tests/fixtures/ad1343_seam_census.py:40`); a parameter named so would put the runtime's construction in that census. No parameter or attribute name ends in `agent` (`census.py:153-155`). |
| D27 | `shutdown` sets `runtime.admission_service = None` on the line after `runtime.identity_service = None`, inside the identity-registry block; no `steps(...)`. | A `steps(...)` block | The service has nothing to stop (it holds references and counters). A `steps(...)` row would need a case in `tests/test_issue1419_failed_start_rollback.py:1392-1426`. |
| D28 | `AdmissionVerdict.__post_init__` refuses an outcome, reason code or principal kind outside its set, and an outcome/code pair where exactly one of them is the admit value. | No validation (only `decide` builds verdicts) | M3b persists `to_dict()`; a malformed verdict found at write time is harder to trace than one refused where it is built. |
| D29 | The cause is built from ids: unresolved `No agent identity resolves from the presented id '<id>'.`; unlisted `The system principal '<id>' is not on the system-principal allowlist.`; stopped `Agent <slot> is under the Captain's stop <stop_id>.` | `StopRecord.sender_text()` | `sender_text()` says "Nothing was started" (`agent_stop.py:240-242`), which is false of shadow work. The stop's free-text reason is not read (T9, T17 pin it with a canary). |
| D30 | The tally keys on `(seam, work_kind, reason_code)`; with the D19-D20 sets (11 seams, 11 kinds) and four codes it has at most 11 × 11 × 4 = 484 keys. The histogram has `LATENCY_BUCKETS = 40` buckets: bucket `i` counts a `decide` whose elapsed `perf_counter_ns` has `bit_length() == i`, and bucket 39 also counts every longer one. The clock is keyword-only and injectable; `decide` reads no clock. | Key on presented id; a float-seconds histogram | Every key field is validated against a closed set, so the tally cannot grow with traffic. Integer nanoseconds avoid float bucketing. |
| D31 | The runtime's `except` branch only logs; it does not assign None. | Assign None in the `except` | The attribute is None from `__init__` (Section 3c), and the assignment in the `try` does not happen when the constructor raises. A reassignment would be a mutant no test can kill. |
| D32 | `SYSTEM_PRINCIPALS` is a module constant, not a constructor parameter. | Inject it | D17 grows it by census in M3e, as a reviewed edit. One fewer surface for M3c to wire. |
| D33 | Tests: 16 unit and structural over real registries and a real `AgentStopService` under `tmp_path`, 3 real-boot. T17 and T19 boot with M1a's `_config()` (`SystemConfig()` with the naming ceremony, the proactive loop and QA off); T18 uses the rollback fixture's `lifecycle_config(..., zero_grace=True)`, as M1a's T15 does. | A literal `SystemConfig()` boot (the memo's "a zero-config boot" test; **this decision replaces it**, and the Captain may overrule) | M3a reads no configuration (T13 pins the constructor's parameters and that `SystemConfig` has no `admission` field), which a boot cannot show. T17 and T19 build `SystemConfig()` with no config file and turn off the same three switches as M1a's boot tests (`tests/test_ad1346_identity_service_boot.py:46-51`); the three switches concern no admission code. Bound stated in Residuals R6. |
| D34 | The import of `probos.admission` is inside the runtime's `try`. | Import at the top of `start()` | A defect that makes the package fail to import is then a logged, contained failure, as a constructor failure is (#1604 property 11). |
| D35 | **Binding on M3c:** seams call `shadow(...)`, not `decide(...)`, and call it on the event loop. | Seams call `decide` | `decide` is in the census's generic agent-work names (`census.py:34`); a receiver named `*_agent` calling it would be recorded as agent work. `shadow` mutates plain dicts and holds no lock (T14), so a call from another thread would race the counters (this follows from the code; not measured). |

---

## Implementation

### Section 0: Event Types

None. This slice adds no `EventType` value and writes nothing to the EventLog.

### Section 1: the package (new files)

#### File 1a: `src/probos/admission/__init__.py`

```python
"""AD-1346 M3a (#1604): the shadow admission decision of epic #1601.

``AdmissionService`` decides once per unit of work and, in shadow, blocks nothing. The
vocabularies are in ``probos.admission.taxonomy``. A top-level package, unranked by the
layer map; ``tests/test_ad1346_admission_service.py`` (T14) pins what it may import.
"""

from probos.admission.record import VERDICT_KEYS, AdmissionVerdict, WorkRequest
from probos.admission.service import AdmissionService

__all__ = ["VERDICT_KEYS", "AdmissionService", "AdmissionVerdict", "WorkRequest"]
```

#### File 1b: `src/probos/admission/taxonomy.py`

```python
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
```

#### File 1c: `src/probos/admission/record.py`

```python
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
```

#### File 1d: `src/probos/admission/checks.py`

```python
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
```

#### File 1e: `src/probos/admission/service.py`

```python
"""AD-1346 M3a (#1604): the shadow admission decision, in process and synchronous.

``AdmissionService.decide`` resolves the principal through ``IdentityService`` and runs the
checks in ``CHECK_ORDER``; the first that refuses decides the verdict (D18). ``shadow`` is
the form a seam calls from AD-1346 M3c on: it builds the request, decides, counts the
verdict and its latency in memory and returns None, so a seam has no result to act on; when
anything in it raises it counts the failure, logs it and returns None. M3a has no caller,
no store and no configuration field; AD-1346 M3b persists the counts.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from probos.admission.checks import ADMITTED, check_agent_stop, check_principal, resolve_principal
from probos.admission.record import AdmissionVerdict, WorkRequest
from probos.admission.taxonomy import LATENCY_BUCKETS, OUTCOME_ADMIT, OUTCOME_WOULD_REFUSE
from probos.agent_stop import AgentStopService
from probos.identity_service import IdentityService

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class AdmissionService:
    """Ship's Computer service: one admission decision per unit of work, in shadow (AD-1346 M3)."""

    def __init__(
        self,
        identity_service: IdentityService,
        stop_service: AgentStopService,
        *,
        clock: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        if not isinstance(identity_service, IdentityService):
            raise TypeError("AdmissionService needs the IdentityService facade")
        if not isinstance(stop_service, AgentStopService):
            raise TypeError("AdmissionService needs the AgentStopService record")
        self._identities = identity_service
        self._stops = stop_service
        self._clock = clock
        self._tally: dict[tuple[str, str, str], int] = {}
        self._latency: list[int] = [0] * LATENCY_BUCKETS
        self._failures = 0

    def decide(self, request: WorkRequest) -> AdmissionVerdict:
        """The verdict for ``request``: the first check in ``CHECK_ORDER`` that refuses, else admit.

        It reads the facade and ``AgentStopService.stop_for`` and nothing else. A dependency
        that raises propagates from here; ``shadow`` is where a failure is contained.
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

    def shadow(self, *, presented_id: str, work_kind: str, seam: str, origin: str, origin_id: str) -> None:
        """Decide in shadow, count the verdict and its latency, and return None (fail open, #1604 property 6)."""
        try:
            request = WorkRequest(presented_id, work_kind, seam, origin, origin_id)
            started = self._clock()
            verdict = self.decide(request)
            elapsed = self._clock() - started
            self._count(verdict, elapsed)
        except Exception:
            self._failures += 1
            logger.log(
                logging.WARNING if self._failures == 1 else logging.DEBUG,
                "AD-1346 M3a: a shadow admission decision raised (%d so far); shadow() returned None to its caller",
                self._failures,
                exc_info=True,
            )
        return None

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
        """Shadow calls that raised since this service was built."""
        return self._failures
```

### Section 2: notes the Builder must keep (no code)

- **2a.** Do not add `__slots__` to `AdmissionService` (T13 reads `vars()`), and do not name any parameter or attribute `agent_stops` or `*_agent` (D26).
- **2b.** D18's disjointness claim rests on two lines: `check_principal` returns a finding only for kinds `unresolved` and `system`, both built with `ref=None` (`resolve_principal`), and `check_agent_stop` returns None when `principal.ref is None`. If either line changes, D18's text changes with it.
- **2c.** No file in the package may import anything outside T14's allowlist, and no import may sit inside a function.

### Section 3: `src/probos/runtime.py` (four edits)

**3a. The `TYPE_CHECKING` import** (`runtime.py:164-166`).

SEARCH:
```python
    from probos.acm import AgentCapitalService
    from probos.agent_stop import AgentStopService  # AD-1343
    from probos.approval_authority import ApprovalAuthorityStore  # AD-1213
```
REPLACE:
```python
    from probos.acm import AgentCapitalService
    from probos.admission import AdmissionService  # AD-1346 M3a
    from probos.agent_stop import AgentStopService  # AD-1343
    from probos.approval_authority import ApprovalAuthorityStore  # AD-1213
```

**3b. The class annotation** (`runtime.py:523-526`).

SEARCH:
```python
    identity_registry: AgentIdentityRegistry | None
    identity_key_binding: IdentityKeyBinding | None  # AD-1196
    identity_service: IdentityService | None  # AD-1346 M1a: built at Phase 2 entry, released with the identity registry
    pool_scaler: PoolScaler | None
```
REPLACE:
```python
    identity_registry: AgentIdentityRegistry | None
    identity_key_binding: IdentityKeyBinding | None  # AD-1196
    identity_service: IdentityService | None  # AD-1346 M1a: built at Phase 2 entry, released with the identity registry
    admission_service: AdmissionService | None  # AD-1346 M3a: set in start() after identity_service; set to None in shutdown
    pool_scaler: PoolScaler | None
```

**3c. The `__init__` default** (`runtime.py:1201-1203`).

SEARCH:
```python
        self.identity_registry: AgentIdentityRegistry | None = None
        self.identity_key_binding: IdentityKeyBinding | None = None  # AD-1196
        self.identity_service: IdentityService | None = None  # AD-1346 M1a: set at Phase 2 entry in start()
```
REPLACE:
```python
        self.identity_registry: AgentIdentityRegistry | None = None
        self.identity_key_binding: IdentityKeyBinding | None = None  # AD-1196
        self.identity_service: IdentityService | None = None  # AD-1346 M1a: set at Phase 2 entry in start()
        self.admission_service: AdmissionService | None = None  # AD-1346 M3a: set after identity_service in start()
```

**3d. The guarded construction** (`runtime.py:2816-2820`).

SEARCH:
```python
        from probos.identity_service import IdentityService

        self.identity_service = IdentityService(infra.identity_registry, self.callsign_registry)

        fleet = await create_agent_fleet(
```
REPLACE:
```python
        from probos.identity_service import IdentityService

        self.identity_service = IdentityService(infra.identity_registry, self.callsign_registry)

        # AD-1346 M3a: the shadow admission decision, over the facade above and the stop record
        # Phase 1a started. Nothing calls it yet (AD-1346 M3c adds the seams). If the import or the
        # constructor raises, the failure is logged, the attribute keeps its __init__ None and the
        # boot goes on (#1604, property 11; D31, D34).
        try:
            from probos.admission import AdmissionService

            self.admission_service = AdmissionService(self.identity_service, self.agent_stops)
        except Exception:  # AD-1346 M3a: a failed construction is logged and the boot goes on (#1604, property 11)
            logger.warning("AD-1346 M3a: the shadow admission service was not built; runtime.admission_service stays None and the boot continues", exc_info=True)

        fleet = await create_agent_fleet(
```

### Section 4: `src/probos/startup/shutdown.py` (one line, `:1429-1434`)

SEARCH:
```python
    # Stop Identity Registry (AD-441)
    if runtime.identity_registry:
        with steps("identity registry stop", runtime.identity_registry):
            await runtime.identity_registry.stop()
        runtime.identity_registry = None
        runtime.identity_service = None  # AD-1346 M1a: the facade holds the registry; released with it
```
REPLACE:
```python
    # Stop Identity Registry (AD-441)
    if runtime.identity_registry:
        with steps("identity registry stop", runtime.identity_registry):
            await runtime.identity_registry.stop()
        runtime.identity_registry = None
        runtime.identity_service = None  # AD-1346 M1a: the facade holds the registry; released with it
        runtime.admission_service = None  # AD-1346 M3a: the service holds the facade; released with it
```

What the rollback covers: a start that fails is rolled back through `shutdown(..., rollback=True)` (`tests/test_issue1419_failed_start_rollback.py:504`), which runs this block; M1a's T15 proves the block runs on a rollback from `fleet_entry` for `identity_service` (`tests/test_ad1346_identity_service_boot.py:134-151`). T18 proves it for `admission_service` by a real boot. M3a adds no `steps(...)`, so no row is added to `_STOPPED_COMPONENTS` (`test_issue1419_failed_start_rollback.py:1127`).

### Section 5: trackers

**5a. `PROGRESS.md`** — SEARCH (the first line and the blank line after it):
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1346 M3a (2026-10-2X), #1604 -- the shadow admission decision exists as an in-process library with no caller: `probos.admission` holds the closed vocabularies, a frozen `WorkRequest`, a frozen `AdmissionVerdict` v1 and `AdmissionService`, which the runtime builds at Phase 2 entry.** `decide()` resolves the presented id through `IdentityService` and runs two checks in a pinned order: the principal (an id that the facade does not resolve and that has no `system:` prefix, or a `system:` id outside the allowlist `{"system:ship_computer"}`, is a would-refuse) and then the Captain's stop, read with `AgentStopService.stop_for` on the principal's slot id, which counts no refusal. A verdict keys on the slot id when one resolved, embeds `IdentityRef.to_dict()`, carries one of four reason codes (`admitted`, `agent_stopped`, `identity_unresolved`, `system_principal_unlisted`) and a cause built from ids, not from the Captain's reason. `shadow()` builds the request, decides, counts the verdict by (seam, work kind, reason code) and its latency in a log2 histogram, in memory, and returns None; when anything in it raises it counts the failure, logs it and returns None. The runtime builds the service after `IdentityService` and before `create_agent_fleet`, inside a `try` that holds both the import and the constructor; when the constructor raises (a real-boot test injects it), the failure is logged, `runtime.admission_service` stays None and the boot continues. Shutdown sets it to None with the identity facade. A structural test pins that only `runtime.py` and `startup/shutdown.py` name it outside the package. No route, store, configuration field, event type or persisted schema; the store is M3b, the seams M3c. 19 new tests (16 unit and structural, 3 real-boot). HIGH tier. The decisions are in DECISIONS.md (AD-1346 M3a); the contract is `prompts/ad-1346-m3a-shadow-admission-service.md`.

```
(The Builder writes the commit date in place of `2026-10-2X`.)

**5b. `DECISIONS.md`** — the new entry follows the newest entry of the recent run (BF-910), so it anchors on the heading that follows that entry (orchestrator anchor correction, 2026-10-21: the draft anchored on M1a's heading, which would have put M3a before M1a and BF-910, against the file's order). SEARCH:
```
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE (the new section, a blank line, then the unchanged heading):
```
### AD-1346 M3a -- the inert shadow AdmissionService library (2026-10-2X, #1604)

AD-1346 M3 (#1604) proves one admission decision per unit of work in shadow before anything depends on it. The Architect sliced it into M3a to M3e (comment 6306056229 on #1604, decisions D1 to D17); M3a is the decision as a library, built at boot and called by nothing. The contract is `prompts/ad-1346-m3a-shadow-admission-service.md`; the code is `src/probos/admission/`.

- *D1 to D17.* As recorded on #1604 (comment 6306056229). In this slice: a top-level package `probos.admission` (D2), the runtime attribute `admission_service` (D3), the types `WorkRequest` and `AdmissionVerdict` (D4), the principal checked before the stop (D5), an unresolved principal recorded as a would-refuse keyed on the presented id and an asset ref admitted (D6), `shadow()` returning None (D7), the AD-1316 reason-code syntax shared, not imported (D8), no configuration field (D15), the system-principal allowlist `{"system:ship_computer"}` (D17). D16 (no check is enforced that had no shadow period) binds M4; M3a enforces nothing.
- *D18 (first refusal decides).* `decide` runs `check_principal` and, when it returns None, `check_agent_stop`; the first finding is the verdict. `check_principal` refuses only principals with no ref and `check_agent_stop` returns None for those (`admission/checks.py`), so in M3a the two cannot both refuse one request.
- *D19 to D21 (vocabularies).* Seams are `agent_stop.SEAMS` (the imported object) plus `model_call`. Eleven v1 work kinds, append-only. Principal kinds `certificate` (a ref with a DID), `asset` (a ref with `did == ""`), `system`, `unresolved`.
- *D22, D23.* The facade is asked first; an id it does not resolve is a system principal only with the `system:` prefix. Origin is validated and recorded; no check reads it.
- *D24, D25 (fail open).* `shadow` takes the fields keyword-only and builds the request inside its `try`; a failure increments `failures`, the first is logged at WARNING with its traceback and later ones at DEBUG.
- *D26, D27 (wiring).* Constructed positionally from `self.identity_service` and `self.agent_stops` inside a `try` that logs and leaves the attribute None; released on the line after `identity_service` in shutdown's identity-registry block, with no `steps(...)`.
- *D28 to D30 (the record).* `AdmissionVerdict` refuses values outside its sets and an outcome/code pair where exactly one is the admit value. The cause is built from ids, not from `StopRecord.sender_text()`, whose "Nothing was started" is false of shadow work. The tally keys on (seam, work kind, reason code), each field from a closed set; 40 log2 nanosecond latency buckets, the last also counting longer times.
- *D31 to D35.* The `except` only logs; the allowlist is a constant; two boot tests use M1a's three-switch `SystemConfig()` in place of the memo's literal zero-config boot (D33, R6; the Captain may overrule) and the rollback test uses `lifecycle_config`; the import is inside the `try`. **Binding on M3c:** seams call `shadow()`, not `decide()`, on the event loop.
- *Tests.* 19: 16 in `tests/test_ad1346_admission_service.py` over a real identity registry, callsign registry and `AgentStopService` under `tmp_path`, and 3 real-boot in `tests/test_ad1346_admission_service_boot.py` (the service answers over the runtime's own facade and stop record and a clean stop releases it; it exists at `create_agent_fleet` and a rollback from there releases it; a raising constructor is logged and the boot completes).
- *Residual, accepted.* R1 to R7 of the contract (the work-kind names are chosen before a seam uses them; thread use is a binding on M3c, not a guard; a stop on a slot the facade cannot resolve reads as `identity_unresolved`; the cost of the DID and certificate-UUID forms is the facade's crew scan, measured in M3b; no literal default-config boot; a resolvable `system:` slot is an agent principal; `refusal` stays callable by any holder of the stop record).
- *Mutation campaign of record.* (The Builder records: date, platform, tree SHA, rows killed of 37, first failing test per row, and the sha256 of `src/probos/admission/{__init__,taxonomy,record,checks,service}.py`, `src/probos/runtime.py`, `src/probos/startup/shutdown.py` and the two test files.)
- *Reversal.* Revert the AD-1346 M3a commits. Nothing is persisted, and nothing outside the runtime's wiring reads the service (T16).

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**5c. The AD ledger** (orchestrator addition, 2026-10-21, found by running the contract on a scratch tree: `python -P scripts/gen_ad_ledger.py --check` fails with `STALE: docs/development/open-ads-report.md` once 5a and 5b are applied). After 5a and 5b, run `python -P scripts/gen_ad_ledger.py` (write mode) and then `--check`; it rewrites `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json` (three lines each on the scratch run: the pinned snapshot's timestamp and commit, and the shifted `PROGRESS.md` line numbers). Both files belong to the M3a commit; the full gate's `ad-ledger` phase reads them.

No `roadmap.md` row: this slice files no BF.

---

## Tests

### File T1: `tests/test_ad1346_admission_service.py` (16 tests)

```python
"""AD-1346 M3a (epic #1601, #1604): the shadow admission decision, over real registries and a real stop record.

``probos.admission`` decides once per unit of work and blocks nothing: ``decide`` resolves the principal through the
``IdentityService`` facade and runs two checks in ``CHECK_ORDER`` (the principal, then the Captain's stop), and
``shadow`` counts each verdict in memory and returns None. These tests drive it over a real ``AgentIdentityRegistry``,
a real ``CallsignRegistry`` and a real ``AgentStopService``, all under ``tmp_path``, and pin its structure:

- T1  the vocabularies: the seams are the stop's ``SEAMS`` plus the effect seams, the stop's reason code is imported,
      every reason code fits the AD-1316 stable-code syntax.
- T2  ``CHECK_ORDER`` and ``DEFERRED_CHECKS``, and ``decide`` calls the checks in that order.
- T3  ``WorkRequest``: exact ``str`` fields from closed sets; frozen.
- T4  ``AdmissionVerdict`` v1: ``VERDICT_KEYS``, the field order, ``to_dict`` embedding ``IdentityRef.to_dict()``, the
      JSON round trip and the record's own checks.
- T5  a certificate principal is admitted and keyed on its slot in each form the facade resolves.
- T6  an asset principal is admitted as an asset.
- T7  an unresolved principal is a would-refuse ``identity_unresolved`` keyed on the presented id.
- T8  the system-principal allowlist.
- T9  a Captain's stop: ``agent_stopped`` with the order's id, read without counting a refusal, and a cause that carries
      no part of the Captain's reason.
- T10 the constructor and ``decide`` refuse the wrong types.
- T11 ``shadow`` returns None and counts each verdict and its latency bucket.
- T12 ``shadow`` fails open: a malformed request or a raising dependency is counted and logged, not raised.
- T13 the service's inputs: no configuration field and no dependency beyond the facade and the stop record.
- T14 the package awaits nothing, imports only its allowlist and logs only in ``shadow``.
- T15 the seam census: the package calls none of the stop's guard functions and starts no agent work.
- T16 outside the package only ``runtime.py`` and ``startup/shutdown.py`` name the service, only ``runtime.py``
      imports the package, and no router does either.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

import probos
import probos.admission as admission_package
from probos import agent_stop
from probos.admission import VERDICT_KEYS, AdmissionService, AdmissionVerdict, WorkRequest, taxonomy
from probos.agent_stop import AgentStopService
from probos.config import SystemConfig
from probos.crew_profile import CallsignRegistry
from probos.execution import authority
from probos.identity import AgentBirthCertificate, AgentIdentityRegistry
from probos.identity_service import IDENTITY_REF_KEYS, IdentityRef, IdentityService
from probos.substrate.registry import AgentRegistry
from tests.fixtures.ad1343_seam_census import GUARD_CALLEES, calls, census, first_line, function, is_agent_work_call

INSTANCE_ID = "ad1346-m3a-ship"
VESSEL_NAME = "Ad1346m3a"
SURGEON_SLOT = "surgeon_medical_surgeon_0_b2321292"
COUNSELOR_SLOT = "counselor_counselor_0_67c601cb"
TOOL_SLOT = "calculator_calculator_0_5f3a9c1e"
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
CANARY = "CANARY-ad1346-m3a: the Captain's private reason"

_SRC = Path(probos.__file__).resolve().parent
_PACKAGE = _SRC / "admission"
_ALLOWED_IMPORTS: dict[str, set[str]] = {
    "__init__.py": {"probos.admission.record", "probos.admission.service"},
    "taxonomy.py": {"__future__", "typing", "probos.agent_stop"},
    "record.py": {"__future__", "dataclasses", "typing", "probos.admission.taxonomy", "probos.identity_service"},
    "checks.py": {
        "__future__", "dataclasses", "typing", "probos.admission.taxonomy", "probos.agent_stop", "probos.identity_service",
    },
    "service.py": {
        "__future__", "collections.abc", "logging", "time", "typing", "probos.admission.checks",
        "probos.admission.record", "probos.admission.taxonomy", "probos.agent_stop", "probos.identity_service",
    },
}
_FORBIDDEN_CALLS = frozenset({
    "open", "print", "input", "exec", "eval", "__import__", "sleep", "Lock", "RLock", "Semaphore", "Condition",
    "acquire", "connect", "execute", "create_task", "run_in_executor",
})


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def registry(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    """A real identity registry in ``tmp_path``, started and commissioned as tests/test_ad1346_identity_service.py does."""
    reg = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await reg.start()
        await reg.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        yield reg
    finally:
        await reg.stop()


@pytest.fixture
def identities(tmp_path: Path, registry: AgentIdentityRegistry) -> IdentityService:
    """The real facade over the registry and a real ``CallsignRegistry`` bound to an empty ``AgentRegistry``."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    (profiles / "surgeon.yaml").write_text("callsign: Meridian\n", encoding="utf-8")
    callsigns = CallsignRegistry()
    callsigns.load_from_profiles(str(profiles))
    callsigns.bind_registry(AgentRegistry())
    return IdentityService(registry, callsigns)


@pytest_asyncio.fixture
async def stops(tmp_path: Path) -> AsyncIterator[AgentStopService]:
    """A real Captain's stop record over ``tmp_path``."""
    record = AgentStopService(data_dir=tmp_path / "stops")
    await record.start()
    try:
        yield record
    finally:
        await record.stop()


@pytest.fixture
def gate(identities: IdentityService, stops: AgentStopService) -> AdmissionService:
    return AdmissionService(identities, stops)


async def _certify(
    reg: AgentIdentityRegistry, slot_id: str = SURGEON_SLOT, agent_type: str = "surgeon", department: str = "medical",
) -> AgentBirthCertificate:
    return await reg.resolve_or_issue(
        slot_id=slot_id, agent_type=agent_type, callsign=agent_type.title(), instance_id=INSTANCE_ID,
        vessel_name=VESSEL_NAME, department=department, post_id=agent_type, baseline_version="v1",
    )


def _request(
    presented_id: str, *, work_kind: str = "intent", seam: str = "intent", origin: str = "captain",
    origin_id: str = "captain",
) -> WorkRequest:
    return WorkRequest(presented_id, work_kind, seam, origin, origin_id)


def _shadow(gate: AdmissionService, presented_id: str, **fields: str) -> None:
    values = {"work_kind": "intent", "seam": "intent", "origin": "captain", "origin_id": "captain", **fields}
    return gate.shadow(presented_id=presented_id, **values)


def _module_names(nodes: list[Any]) -> set[str]:
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def _within(node: ast.AST, scope: ast.AST) -> bool:
    return scope.lineno <= node.lineno <= (scope.end_lineno or scope.lineno)


class _Str(str):
    """A ``str`` subclass, which is not an exact ``str``."""


# ---------------------------------------------------------------------------
# T1 to T4: the vocabularies and the records
# ---------------------------------------------------------------------------


def test_the_vocabularies_are_closed_and_share_the_stop_codes() -> None:
    """T1: the seams extend the stop's, the stop's code is imported, every code fits AD-1316's syntax (kills M1, M2)."""
    assert taxonomy.STOP_SEAMS is agent_stop.SEAMS
    assert taxonomy.EFFECT_SEAMS == frozenset({"model_call"})
    assert taxonomy.SEAMS == agent_stop.SEAMS | taxonomy.EFFECT_SEAMS
    assert agent_stop.SEAMS < taxonomy.SEAMS and not agent_stop.SEAMS & taxonomy.EFFECT_SEAMS
    tree = ast.parse((_PACKAGE / "taxonomy.py").read_text(encoding="utf-8"))
    imported = {
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "probos.agent_stop" for alias in node.names
    }
    assert imported == {"SEAMS", "STOP_REASON_CODE"}, "the stop's names are imported, not restated"
    assert taxonomy.REASON_AGENT_STOPPED == agent_stop.STOP_REASON_CODE == "agent_stopped"
    assert taxonomy.REASON_CODES == ("admitted", "agent_stopped", "identity_unresolved", "system_principal_unlisted")
    assert authority._REASON_CODE_RE.pattern == r"[a-z][a-z0-9_]{0,127}\Z", "premise: the AD-1316 syntax shared (D8)"
    for code in taxonomy.REASON_CODES:
        assert authority._REASON_CODE_RE.fullmatch(code), code
    assert taxonomy.ORIGINS == ("captain", "agent", "system", "federation_peer")
    assert taxonomy.PRINCIPAL_KINDS == ("certificate", "asset", "system", "unresolved")
    assert taxonomy.OUTCOMES == ("admit", "would_refuse")
    assert taxonomy.WORK_KINDS == (
        "intent", "consultation", "proactive_cycle", "ward_room_notice", "direct_message", "group_turn",
        "browser_action", "agentic_run", "delegated_task", "tool_call", "model_call",
    )
    for vocabulary in (
        taxonomy.REASON_CODES, taxonomy.ORIGINS, taxonomy.PRINCIPAL_KINDS, taxonomy.OUTCOMES, taxonomy.WORK_KINDS,
    ):
        assert len(set(vocabulary)) == len(vocabulary), vocabulary


def test_the_check_order_and_the_deferred_checks_are_pinned() -> None:
    """T2: two checks in ``CHECK_ORDER``, the deferred ones with their owners, and ``decide`` calls them in order."""
    assert taxonomy.CHECK_ORDER == ("principal", "agent_stop")
    assert taxonomy.DEFERRED_CHECKS == (
        ("vessel_stop", "AD-1343 S3, built in AD-1346 M4"),
        ("lifecycle_acm", "AD-1346 M3f"),
        ("earned_agency", "AD-1346 M3f"),
        ("scope_clearance", "AD-1346 M3f"),
        ("budget_reservation", "AD-1346 M3f"),
        ("pre_intent_hooks", "AD-698, AD-1346 M3f"),
    )
    assert not {name for name, _ in taxonomy.DEFERRED_CHECKS} & set(taxonomy.CHECK_ORDER)
    decide = function("src/probos/admission/service.py", "AdmissionService.decide")
    resolved = first_line(decide, calls("resolve_principal"))
    assert resolved < first_line(decide, calls("check_principal")) < first_line(decide, calls("check_agent_stop"))


def test_a_work_request_takes_exact_strings_from_the_closed_sets() -> None:
    """T3: exact ``str`` fields, each closed set enforced, frozen (kills M1, M4, M5, M6, M7)."""
    assert [f.name for f in dataclasses.fields(WorkRequest)] == ["presented_id", "work_kind", "seam", "origin", "origin_id"]
    for seam in sorted(taxonomy.SEAMS):
        assert _request("x", seam=seam).seam == seam
    for kind in taxonomy.WORK_KINDS:
        assert _request("x", work_kind=kind).work_kind == kind
    for origin in taxonomy.ORIGINS:
        assert _request("x", origin=origin).origin == origin
    assert _request("").presented_id == ""  # accepted: the decision refuses it (T7)
    with pytest.raises(ValueError, match="work kind"):
        _request("x", work_kind="holodeck")
    with pytest.raises(ValueError, match="seam"):
        _request("x", seam="subprocess")
    with pytest.raises(ValueError, match="origin"):
        _request("x", origin="peer")
    with pytest.raises(TypeError, match="presented_id"):
        _request(_Str("x"))  # a str subclass is not a str (kills M4)
    with pytest.raises(TypeError, match="origin_id"):
        WorkRequest("x", "intent", "intent", "captain", None)  # type: ignore[arg-type]
    request = _request("x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.seam = "tool"  # type: ignore[misc]


async def test_the_verdict_v1_is_frozen(registry: AgentIdentityRegistry, gate: AdmissionService) -> None:
    """T4: ``VERDICT_KEYS``, the field order, the embedded ref, the JSON round trip, the record's checks (kills M8 to M10)."""
    await _certify(registry)
    assert VERDICT_KEYS == (
        "outcome", "reason_code", "check", "cause", "key", "principal_kind", "principal",
        "presented_id", "work_kind", "seam", "origin", "origin_id", "stop_id",
    )
    assert tuple(f.name for f in dataclasses.fields(AdmissionVerdict)) == VERDICT_KEYS
    verdict = gate.decide(_request(SURGEON_SLOT, work_kind="tool_call", seam="tool", origin="agent", origin_id="x"))
    body = verdict.to_dict()
    assert tuple(body) == VERDICT_KEYS
    assert isinstance(verdict.principal, IdentityRef)
    assert body["principal"] == verdict.principal.to_dict() and tuple(body["principal"]) == IDENTITY_REF_KEYS
    assert json.loads(json.dumps(body)) == body
    assert (body["work_kind"], body["seam"], body["origin"], body["origin_id"]) == ("tool_call", "tool", "agent", "x")
    refused = gate.decide(_request("nobody")).to_dict()
    assert refused["principal"] is None and json.loads(json.dumps(refused)) == refused
    with pytest.raises(dataclasses.FrozenInstanceError):
        verdict.outcome = "would_refuse"  # type: ignore[misc]
    fields = {name: getattr(verdict, name) for name in VERDICT_KEYS}
    with pytest.raises(ValueError):
        AdmissionVerdict(**{**fields, "reason_code": "agent_stopped"})  # an admit carrying a refusal code (kills M8)
    with pytest.raises(ValueError):
        AdmissionVerdict(**{**fields, "outcome": "would_refuse"})  # a refusal carrying admitted
    with pytest.raises(ValueError):
        AdmissionVerdict(**{**fields, "outcome": "refuse", "reason_code": "agent_stopped"})  # kills M9
    with pytest.raises(ValueError):
        AdmissionVerdict(**{**fields, "principal_kind": "crew"})


# ---------------------------------------------------------------------------
# T5 to T10: decide
# ---------------------------------------------------------------------------


async def test_a_certificate_principal_is_admitted_and_keyed_on_its_slot(
    registry: AgentIdentityRegistry, gate: AdmissionService,
) -> None:
    """T5: the slot, the certificate UUID and the DID give one admit keyed on the slot (kills M12, M24)."""
    cert = await _certify(registry)
    verdicts = [gate.decide(_request(key)) for key in (SURGEON_SLOT, cert.agent_uuid, cert.did)]
    for verdict in verdicts:
        assert (verdict.outcome, verdict.reason_code, verdict.check, verdict.stop_id) == ("admit", "admitted", "", "")
        assert verdict.key == SURGEON_SLOT
        assert verdict.principal_kind == "certificate"
        assert verdict.principal is not None and verdict.principal.slot_id == SURGEON_SLOT
        assert verdict.principal.did == cert.did
    assert [v.presented_id for v in verdicts] == [SURGEON_SLOT, cert.agent_uuid, cert.did]
    bodies = [{k: v for k, v in verdict.to_dict().items() if k != "presented_id"} for verdict in verdicts]
    assert bodies[0] == bodies[1] == bodies[2]


async def test_an_asset_principal_is_admitted_as_an_asset(registry: AgentIdentityRegistry, gate: AdmissionService) -> None:
    """T6: an asset slot and its tag UUID are admitted with kind ``asset`` and no DID (kills M11)."""
    tag = await registry.resolve_or_issue_asset_tag(TOOL_SLOT, "calculator", "calculator")
    for key in (TOOL_SLOT, tag.asset_uuid):
        verdict = gate.decide(_request(key, work_kind="tool_call", seam="tool", origin="agent", origin_id=SURGEON_SLOT))
        assert (verdict.outcome, verdict.reason_code, verdict.principal_kind, verdict.key) == (
            "admit", "admitted", "asset", TOOL_SLOT,
        ), key
        assert verdict.principal is not None and verdict.principal.did == ""


async def test_an_unresolved_principal_would_be_refused_and_keyed_on_the_presented_id(
    registry: AgentIdentityRegistry, gate: AdmissionService,
) -> None:
    """T7: an id the facade does not resolve, a callsign included, is a would-refuse (kills M14, M21, M23)."""
    await _certify(registry)
    for presented in ("", "nobody_0_00000000", "Surgeon", UNKNOWN_UUID):
        verdict = gate.decide(_request(presented))
        assert (verdict.outcome, verdict.reason_code, verdict.check) == (
            "would_refuse", "identity_unresolved", "principal",
        ), presented
        assert verdict.key == presented and verdict.presented_id == presented
        assert verdict.principal_kind == "unresolved" and verdict.principal is None and verdict.stop_id == ""
        assert repr(presented) in verdict.cause


async def test_only_an_allowlisted_system_principal_is_admitted(gate: AdmissionService) -> None:
    """T8: ``system:ship_computer`` is admitted, any other ``system:`` id is not (kills M3, M13, M15, M21, M37)."""
    assert taxonomy.SYSTEM_PRINCIPAL_PREFIX == "system:"
    assert taxonomy.SYSTEM_PRINCIPALS == frozenset({"system:ship_computer"})
    listed = gate.decide(_request("system:ship_computer", origin="system", origin_id="system:ship_computer"))
    assert (listed.outcome, listed.reason_code, listed.check, listed.principal_kind, listed.key) == (
        "admit", "admitted", "", "system", "system:ship_computer",
    )
    assert listed.principal is None
    unlisted = gate.decide(_request("system:dream_scheduler", origin="system", origin_id="system:dream_scheduler"))
    assert (unlisted.outcome, unlisted.reason_code, unlisted.check, unlisted.principal_kind, unlisted.key) == (
        "would_refuse", "system_principal_unlisted", "principal", "system", "system:dream_scheduler",
    )
    assert "'system:dream_scheduler'" in unlisted.cause


async def test_a_captains_stop_is_read_without_counting_and_its_reason_stays_out(
    registry: AgentIdentityRegistry, stops: AgentStopService, gate: AdmissionService,
) -> None:
    """T9: a stop on the slot is seen through every form, counts no refusal and leaks no reason (kills M2, M12, M16, M17, M22, M24, M25)."""
    cert = await _certify(registry)
    await _certify(registry, COUNSELOR_SLOT, "counselor", "medical")
    issued = await stops.issue_stop(SURGEON_SLOT, reason=CANARY)
    stop_id = issued.record.stop_id
    for key in (SURGEON_SLOT, cert.agent_uuid, cert.did):  # D5: a DID presented for a stopped slot is caught (BF-907 class)
        verdict = gate.decide(_request(key))
        assert (verdict.outcome, verdict.reason_code, verdict.check) == ("would_refuse", "agent_stopped", "agent_stop"), key
        assert verdict.stop_id == stop_id and verdict.key == SURGEON_SLOT
        assert stop_id in verdict.cause and SURGEON_SLOT in verdict.cause
        assert "CANARY" not in json.dumps(verdict.to_dict())
    assert _shadow(gate, cert.did) is None
    assert stops.refused_counts(stop_id) == {}, "a shadow decision must count no refusal (AD-1343 S1 constraint)"
    assert gate.decide(_request(COUNSELOR_SLOT)).outcome == "admit", "a stop on one slot does not touch another"
    await stops.lift_stop(SURGEON_SLOT, reason="lifted by the test")
    assert gate.decide(_request(SURGEON_SLOT)).outcome == "admit", "a lift is read at the next decision"


async def test_the_service_takes_only_the_real_facade_and_stop_record(
    identities: IdentityService, stops: AgentStopService, gate: AdmissionService,
) -> None:
    """T10: the constructor refuses anything but the two real types, and ``decide`` anything but a request (kills M18 to M20)."""
    with pytest.raises(TypeError, match="IdentityService"):
        AdmissionService(None, stops)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="AgentStopService"):
        AdmissionService(identities, None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="AgentStopService"):
        AdmissionService(identities, SimpleNamespace(stop_for=lambda agent_id: None))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="WorkRequest"):
        gate.decide({"presented_id": SURGEON_SLOT})  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# T11 to T13: shadow
# ---------------------------------------------------------------------------


async def test_shadow_returns_none_and_counts_each_verdict_and_its_latency(
    registry: AgentIdentityRegistry, identities: IdentityService, stops: AgentStopService,
) -> None:
    """T11: None for every call, the tally by (seam, kind, code), one latency bucket per call (kills M26 to M29)."""
    await _certify(registry)
    ticks = iter([100, 105, 200, 200, 300, 300 + 2**45])
    gate = AdmissionService(identities, stops, clock=lambda: next(ticks))
    assert gate.tally() == {} and gate.latency_histogram() == (0,) * taxonomy.LATENCY_BUCKETS and gate.failures == 0
    assert _shadow(gate, SURGEON_SLOT) is None
    assert _shadow(gate, "nobody", work_kind="tool_call", seam="tool", origin="agent", origin_id=SURGEON_SLOT) is None
    assert _shadow(gate, SURGEON_SLOT) is None
    assert gate.tally() == {("intent", "intent", "admitted"): 2, ("tool", "tool_call", "identity_unresolved"): 1}
    assert taxonomy.LATENCY_BUCKETS == 40
    histogram = gate.latency_histogram()
    assert histogram[3] == 1, histogram  # 5 ns: bit_length 3
    assert histogram[0] == 1, histogram  # 0 ns
    assert histogram[39] == 1, histogram  # 2**45 ns: past the last bucket, counted in it
    assert sum(histogram) == 3 and gate.failures == 0
    copy = gate.tally()
    copy.clear()
    assert gate.tally() != {}, "tally() returns a copy"


async def test_shadow_fails_open_counts_and_logs(
    identities: IdentityService, gate: AdmissionService, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """T12: a malformed request and a raising facade are counted and logged, never raised (kills M30 to M32)."""
    caplog.set_level(logging.DEBUG, logger="probos.admission.service")
    assert _shadow(gate, SURGEON_SLOT, seam="subprocess") is None
    assert gate.failures == 1 and gate.tally() == {}

    def boom(key: str) -> None:
        raise RuntimeError("INJECTED resolver failure")

    monkeypatch.setattr(identities, "resolve", boom)
    assert _shadow(gate, SURGEON_SLOT) is None
    assert gate.failures == 2 and gate.tally() == {} and sum(gate.latency_histogram()) == 0
    with pytest.raises(RuntimeError, match="INJECTED"):
        gate.decide(_request(SURGEON_SLOT))  # decide propagates; only shadow contains a failure
    records = [r for r in caplog.records if r.name == "probos.admission.service"]
    assert [r.levelno for r in records] == [logging.WARNING, logging.DEBUG]
    assert all(r.exc_info for r in records)


async def test_the_service_reads_no_configuration_and_holds_only_its_two_dependencies(gate: AdmissionService) -> None:
    """T13: no configuration field; the facade, the stop record, a clock and its counters are all it holds."""
    assert "admission" not in SystemConfig.model_fields
    init = inspect.signature(AdmissionService.__init__).parameters
    assert list(init) == ["self", "identity_service", "stop_service", "clock"]
    assert init["clock"].kind is inspect.Parameter.KEYWORD_ONLY
    shadow = inspect.signature(AdmissionService.shadow).parameters
    assert list(shadow) == ["self", "presented_id", "work_kind", "seam", "origin", "origin_id"]
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for name, p in shadow.items() if name != "self")
    assert set(vars(gate)) == {"_identities", "_stops", "_clock", "_tally", "_latency", "_failures"}


# ---------------------------------------------------------------------------
# T14 to T16: structure
# ---------------------------------------------------------------------------


def test_the_package_awaits_nothing_imports_only_its_allowlist_and_logs_only_in_shadow() -> None:
    """T14: no await, lock, file or connection call; the import allowlist per file; logging and the clock only in shadow."""
    assert admission_package.__all__ == ["VERDICT_KEYS", "AdmissionService", "AdmissionVerdict", "WorkRequest"]
    assert sorted(p.name for p in _PACKAGE.glob("*.py")) == sorted(_ALLOWED_IMPORTS), "premise: the package's files"
    for name, allowed in _ALLOWED_IMPORTS.items():
        tree = ast.parse((_PACKAGE / name).read_text(encoding="utf-8"), filename=name)
        top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        guarded = [
            s for n in tree.body
            if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "TYPE_CHECKING" for s in n.body
        ]
        every = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        assert len(every) == len(top) + len(guarded), f"{name}: an import outside the module body or its TYPE_CHECKING block"
        assert _module_names(every) == allowed, name
        for node in ast.walk(tree):
            assert not isinstance(node, (ast.Await, ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith)), (name, node.lineno)
            if isinstance(node, ast.Call):
                func = node.func
                callee = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
                assert callee not in _FORBIDDEN_CALLS, (name, node.lineno, callee)
        if name != "service.py":
            assert not any(isinstance(n, ast.Name) and n.id == "logger" for n in ast.walk(tree)), name
    tree = ast.parse((_PACKAGE / "service.py").read_text(encoding="utf-8"))
    shadow = function("src/probos/admission/service.py", "AdmissionService.shadow")
    init = function("src/probos/admission/service.py", "AdmissionService.__init__")
    loggers = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "logger" and isinstance(n.ctx, ast.Load)]
    assert loggers and all(_within(n, shadow) for n in loggers), "only shadow() logs"
    clocks = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "_clock"]
    assert all(_within(n, shadow) or (_within(n, init) and isinstance(n.ctx, ast.Store)) for n in clocks), (
        "only shadow() reads the clock"
    )
    assert sum(_within(n, shadow) for n in clocks) == 2, "premise: shadow() reads the clock twice"


def test_the_package_calls_no_stop_guard_and_starts_no_agent_work() -> None:
    """T15: the seam census over the package: no guard callee, no agent-work call, the stop read with ``stop_for`` (kills M16)."""
    assert {"active_stop", "refusal", "tool_refusal", "refuse_new_run", "standing_stop"} <= GUARD_CALLEES  # premise
    found = [c for c in census() if c.file.startswith("src/probos/admission/")]
    assert ("src/probos/admission/service.py", "AdmissionService.shadow", "decide", "self") in {
        (c.file, c.function, c.callee, c.receiver) for c in found
    }, "premise: the census scanned the package"
    assert [c for c in found if c.callee in GUARD_CALLEES] == []
    assert [c for c in found if is_agent_work_call(c)] == []
    assert first_line(function("src/probos/admission/checks.py", "check_agent_stop"), calls("stop_for")) > 0


def test_nothing_outside_the_wiring_names_the_service_or_imports_the_package() -> None:
    """T16: the consumer census. No router and no other module reads the service in M3a (#1604, property 11)."""
    named: set[str] = set()
    importers: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC.parent).as_posix()
        if rel.startswith("probos/admission/"):
            continue
        text = path.read_text(encoding="utf-8")
        if "admission_service" in text:
            named.add(rel)
        if "admission" not in text:
            continue
        for node in ast.walk(ast.parse(text, filename=rel)):
            if any(m == "probos.admission" or m.startswith("probos.admission.") for m in _module_names([node])):
                importers.add(rel)
            if isinstance(node, ast.ImportFrom) and node.module == "probos" and any(a.name == "admission" for a in node.names):
                importers.add(rel)
    assert named == {"probos/runtime.py", "probos/startup/shutdown.py"}, sorted(named)
    assert importers == {"probos/runtime.py"}, sorted(importers)
    assert not {rel for rel in named | importers if rel.startswith("probos/routers/") or rel == "probos/api.py"}
```

### File T2: `tests/test_ad1346_admission_service_boot.py` (3 tests)

```python
"""AD-1346 M3a (#1604) - real-boot tests: the shadow ``AdmissionService`` is wired, and its failure does not stop a boot.

These boot a real ``ProbOSRuntime`` through every startup phase with the mock LLM, as
``tests/test_ad1346_identity_service_boot.py`` does:

- T17 after a boot the service answers over the runtime's own facade and stop record: each agent the facade resolves is
      admitted under its slot, a Captain's stop issued through ``runtime.agent_stops`` is seen by the next decision and
      no refusal is counted for it, and a clean ``stop()`` releases the service.
- T18 the service exists when ``create_agent_fleet`` is reached and answers there, and the rollback of a start that fails
      there releases it.
- T19 a constructor that raises is logged once at WARNING with its traceback, ``runtime.admission_service`` stays None,
      and the boot completes.

T17 and T19 boot with ``SystemConfig()`` and the three switches M1a's boot tests turn off (naming ceremony, proactive
loop, QA); T18 uses ``lifecycle_config(..., zero_grace=True)`` as M1a's T15 does. M3a adds no configuration field (T13).
Every data directory is under ``tmp_path``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

import probos.admission as admission
from probos.admission import AdmissionService, AdmissionVerdict, WorkRequest
from probos.agent_stop import AgentStopService
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.crew_utils import is_crew_agent
from probos.identity_service import IdentityService
from probos.runtime import ProbOSRuntime
from tests.fixtures.runtime_factory import make_runtime
from tests.fixtures.runtime_lifecycle import InjectedStartFailure, inject_start_failure, lifecycle_config

CANARY = "CANARY-ad1346-m3a-boot: the Captain's private reason"


def _config() -> SystemConfig:
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    return config


async def _boot(data_dir: Path) -> ProbOSRuntime:
    runtime = ProbOSRuntime(config=_config(), data_dir=data_dir, llm_client=MockLLMClient())
    await runtime.start()
    return runtime


def _intent(presented_id: str) -> WorkRequest:
    return WorkRequest(presented_id, "intent", "intent", "captain", "captain")


async def test_after_a_boot_the_service_answers_over_the_runtimes_own_facade_and_stop_record(tmp_path: Path) -> None:
    """T17 (kills M16, M17, M22, M25, M33, M36)."""
    rt = await _boot(tmp_path / "data")
    try:
        gate = rt.admission_service
        assert isinstance(gate, AdmissionService), "the boot must build the shadow admission service"
        assert isinstance(rt.identity_service, IdentityService) and isinstance(rt.agent_stops, AgentStopService)
        kinds: set[str] = set()
        for agent in rt.registry.all():
            ref = rt.identity_service.resolve(agent.id)
            if ref is None:
                continue  # T7 covers an unresolved principal
            verdict = gate.decide(_intent(agent.id))
            assert (verdict.outcome, verdict.key, verdict.principal) == ("admit", agent.id, ref), agent.id
            kinds.add(verdict.principal_kind)
        assert kinds == {"certificate", "asset"}, f"premise: the boot has a certified agent and an asset: {kinds}"
        crew = next(
            (
                a for a in rt.registry.all()
                if a.did and is_crew_agent(a, rt.ontology) and getattr(rt.identity_service.resolve(a.did), "slot_id", None) == a.id
            ),
            None,
        )
        assert crew is not None, "premise: a certified crew agent whose DID resolves to its own slot"
        issued = await rt.agent_stops.issue_stop(crew.id, reason=CANARY)
        try:
            before = rt.agent_stops.refused_counts(issued.record.stop_id)
            verdict = gate.decide(_intent(crew.did))  # no await between the two reads of the counts
            assert rt.agent_stops.refused_counts(issued.record.stop_id) == before, "decide counted a refusal"
            assert (verdict.reason_code, verdict.stop_id, verdict.key) == ("agent_stopped", issued.record.stop_id, crew.id)
            assert "CANARY" not in json.dumps(verdict.to_dict())
        finally:
            await rt.agent_stops.lift_stop(crew.id, reason="lifted by the test")
    finally:
        await rt.stop()
    assert rt.admission_service is None, "a clean stop must release the service"


async def test_the_service_exists_before_the_fleet_and_a_failed_start_releases_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T18: built before ``create_agent_fleet`` and answering there; the rollback releases it (kills M3, M13, M33, M36, M37)."""
    monkeypatch.chdir(tmp_path)
    runtime = make_runtime(tmp_path, config=lifecycle_config(tmp_path, zero_grace=True))
    seen: list[tuple[Any, AdmissionVerdict | None]] = []

    def at_fleet_entry(rt: ProbOSRuntime) -> None:
        gate = rt.admission_service
        answer = None
        if isinstance(gate, AdmissionService):
            answer = gate.decide(WorkRequest("system:ship_computer", "intent", "intent", "system", "system:ship_computer"))
        seen.append((gate, answer))

    failure = inject_start_failure(monkeypatch, runtime, "fleet_entry", on_fire=at_fleet_entry)
    with pytest.raises(InjectedStartFailure) as raised:
        await runtime.start()

    assert raised.value is failure.error
    assert len(seen) == 1, "premise: the start reached create_agent_fleet"
    gate, answer = seen[0]
    assert isinstance(gate, AdmissionService), "the service must exist when the fleet is created"
    assert answer is not None and answer.outcome == "admit"
    assert runtime.admission_service is None, "a rolled-back start must release the service"


async def test_a_constructor_that_raises_is_logged_and_the_boot_completes_without_the_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """T19: #1604 property 11, the gate's startup failure leaves the boot going (kills M34, M35)."""

    class _Refuses:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("INJECTED admission construction failure")

    monkeypatch.setattr(admission, "AdmissionService", _Refuses)
    caplog.set_level(logging.WARNING, logger="probos.runtime")
    rt = await _boot(tmp_path / "data")
    try:
        assert rt.admission_service is None
        assert isinstance(rt.identity_service, IdentityService), "premise: the boot went past Phase 2 entry"
        assert rt.registry.count > 0, "premise: the fleet was created after the failure"
        warned = [
            r for r in caplog.records
            if r.name == "probos.runtime" and "shadow admission service was not built" in r.getMessage()
        ]
        assert len(warned) == 1 and warned[0].levelno == logging.WARNING
        assert warned[0].exc_info is not None and "INJECTED admission construction failure" in str(warned[0].exc_info[1])
    finally:
        await rt.stop()
```

### What each test proves, and does not

| # | Proves | Does not prove |
|---|---|---|
| T1 | The seam set is the imported stop set plus `model_call`; the stop's names are imported (AST); the four codes fit AD-1316's pattern, whose text is pinned as a premise | That M3c's seams pass these values |
| T2 | The order of the three calls in `decide` and the deferred list | That a deferred check is ever built |
| T3 | Field names and order, exact-`str` and closed-set validation, immutability | — |
| T4 | v1 keys, field order, JSON form, the ref embedded as `IDENTITY_REF_KEYS`, the record's checks | That M3b persists it (M3b) |
| T5 | Three identity forms give one verdict keyed on the slot | The callsign form (not a key, D6 of M1a; T7 refuses it) |
| T6 | Asset ref → `asset`, admitted | — |
| T7 | Four unresolved shapes refused with the presented id as key | — |
| T8 | The allowlist, both branches | That a seam presents `system:` ids (M3e) |
| T9 | A real stop seen through slot, UUID and DID; no count; canary absent; another slot unaffected; a lift read at the next call | Parity with today's seam refusals (M3c) |
| T10 | Exact-type construction and request typing | — |
| T11 | Return None; tally keys; three bucket edges | p99 on live work (M3b) |
| T12 | Fail-open for a malformed request and a raising dependency; the log levels | A `BaseException` (deliberately not caught) |
| T13 | No config field; the constructor and `shadow` signatures; the instance's state | — |
| T14 | No await, lock, file or connection call; import allowlist per file; logger and clock confined to `shadow` | A blocking call reached through an imported function (the facade's own code is M1a's T13/D9) |
| T15 | The package is invisible to S1's guard census and to M0's agent-work census, and reads the stop with `stop_for` | — |
| T16 | Outside the package, only `runtime.py` and `shutdown.py` contain `admission_service`; only `runtime.py` imports the package; no router or `api.py` does | A reach through `getattr(runtime, "admission" + "_service")` (string assembly) |
| T17 | Real wiring: the service holds the runtime's own facade and stop record; a clean stop releases it | A literal default-config boot (R6) |
| T18 | Built before the fleet; answers at `fleet_entry`; the rollback releases it | — |
| T19 | A raising constructor: one WARNING with traceback, attribute None, fleet created | An import failure of the package (same `try`, D34; not injected) |

Premise assertions are marked "premise:" in the code. The M1a test `tests/test_ad1346_identity_service.py:463-481` (only the facade constructs an `IdentityRef`) also covers this package: it constructs none.

---

## Milestones (about 50 tool calls each)

| M | Scope | Focused checks (run at `-n 0`; never `pytest tests/`) |
|---|---|---|
| **M1** | Section 1 (Files 1a-1e) and File T1 | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1346_admission_service.py -v -n 0`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py -q -n 0`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1346_identity_service.py -q -n 0 -k "only_the_facade_constructs"`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_layer_boundaries.py -q -n 0`; `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check` |
| **M2** | Sections 3 and 4, File T2 | `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1346_admission_service_boot.py -v -n 0`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1346_identity_service_boot.py -q -n 0`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_issue1419_failed_start_rollback.py -q -n 0 -k "a_failed_start_rolls_back_everything or every_guarded_step or every_step_that_stops or a_clean_stop_makes_every_session_write or start_is_wrapped"`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1346_admission_service.py -q -n 0 -k "nothing_outside_the_wiring"`; `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad680_public_runtime_api.py -q -n 0`; `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check`; `d:/ProbOS/.venv/Scripts/python.exe scripts/check_seam_contracts.py --check` |
| **M3** | Section 5 (trackers), the mutation campaign, the section audit (each Section to code, each T to a test) | Rerun Files T1 and T2 after the trackers. The broad gate is run once by the main session, not the Builder. |

---

## Mutation table (run once on the final tree; every anchor is a whole, unique, stripped line)

Apply one mutant at a time (replace the whole stripped line, keeping its indentation), run the named tests' file at `-n 0`, and restore. Rows M1 to M32 and M37 run against File T1 (M16 also against `tests/test_ad1343_stop_seam_inventory.py`); M33 to M36 against File T2. **Campaign of record:** record the base tree SHA and the sha256 of the seven source files and two test files listed in `DECISIONS.md` (Section 5b); a later round whose files match does not repeat it; if one differs, rerun only the rows anchored in that file.

| ID | File | Line (stripped) → mutant | Killed by |
|---|---|---|---|
| M1 | taxonomy.py | `SEAMS: Final[frozenset[str]] = STOP_SEAMS \| EFFECT_SEAMS` → `SEAMS: Final[frozenset[str]] = EFFECT_SEAMS` | T1, T3 |
| M2 | taxonomy.py | `REASON_AGENT_STOPPED: Final = STOP_REASON_CODE` → `REASON_AGENT_STOPPED: Final = "agent_stop"` | T1, T9 |
| M3 | taxonomy.py | `SYSTEM_PRINCIPALS: Final[frozenset[str]] = frozenset({"system:ship_computer"})` → `SYSTEM_PRINCIPALS: Final[frozenset[str]] = frozenset()` | T8, T18 |
| M4 | record.py | `if type(getattr(self, name)) is not str:` → `if not isinstance(getattr(self, name), str):` | T3 |
| M5 | record.py | `raise ValueError(f"AD-1346: unknown work kind {self.work_kind!r}")` → `pass` | T3 |
| M6 | record.py | `raise ValueError(f"AD-1346: unknown seam {self.seam!r}")` → `pass` | T3 |
| M7 | record.py | `raise ValueError(f"AD-1346: unknown origin {self.origin!r}")` → `pass` | T3 |
| M8 | record.py | `if (self.outcome == OUTCOME_ADMIT) != (self.reason_code == REASON_ADMITTED):` → `if False:` | T4 |
| M9 | record.py | `if self.outcome not in OUTCOMES or self.reason_code not in REASON_CODES:` → `if False:` | T4 |
| M10 | record.py | `body["principal"] = self.principal.to_dict()` → `pass` | T4 |
| M11 | checks.py | `kind = PRINCIPAL_CERTIFICATE if ref.did else PRINCIPAL_ASSET` → `kind = PRINCIPAL_CERTIFICATE` | T6 |
| M12 | checks.py | `return Principal(kind, ref.slot_id, ref)` → `return Principal(kind, presented_id, ref)` | T5, T9 |
| M13 | checks.py | `if presented_id.startswith(SYSTEM_PRINCIPAL_PREFIX):` → `if False:` | T8, T18 |
| M14 | checks.py | `if principal.kind == PRINCIPAL_UNRESOLVED:` → `if False:` | T7 |
| M15 | checks.py | `if principal.kind == PRINCIPAL_SYSTEM and principal.key not in SYSTEM_PRINCIPALS:` → `if False:` | T8 |
| M16 | checks.py | `record = stops.stop_for(principal.ref.slot_id)` → `record = stops.refusal(principal.ref.slot_id, "tool")` | T9, T15, T17 |
| M17 | checks.py | `record = stops.stop_for(principal.ref.slot_id)` → `record = None` | T9, T17 |
| M18 | service.py | `if not isinstance(identity_service, IdentityService):` → `if False:` | T10 |
| M19 | service.py | `if not isinstance(stop_service, AgentStopService):` → `if False:` | T10 |
| M20 | service.py | `if type(request) is not WorkRequest:` → `if False:` | T10 |
| M21 | service.py | `finding = check_principal(principal)` → `finding = None` | T7, T8 |
| M22 | service.py | `finding = check_agent_stop(principal, self._stops)` → `pass` | T9, T17 |
| M23 | service.py | `outcome = OUTCOME_ADMIT if finding is None else OUTCOME_WOULD_REFUSE` → `outcome = OUTCOME_ADMIT` | T7 |
| M24 | service.py | `key=principal.key,` → `key=request.presented_id,` | T5, T9 |
| M25 | service.py | `stop_id=found.stop_id,` → `stop_id="",` | T9, T17 |
| M26 | service.py | `elapsed = self._clock() - started` → `elapsed = 0` | T11 |
| M27 | service.py | `self._tally[key] = self._tally.get(key, 0) + 1` → `pass` | T11 |
| M28 | service.py | `self._latency[min(elapsed_ns.bit_length(), LATENCY_BUCKETS - 1)] += 1` → `self._latency[min(elapsed_ns.bit_length(), LATENCY_BUCKETS - 1) - 1] += 1` | T11 |
| M29 | service.py | `return None` → `return verdict` | T11, T12 |
| M30 | service.py | `except Exception:` → `except ValueError:` | T12 |
| M31 | service.py | `self._failures += 1` → `pass` | T12 |
| M32 | service.py | `logging.WARNING if self._failures == 1 else logging.DEBUG,` → `logging.WARNING,` | T12 |
| M33 | runtime.py | `self.admission_service = AdmissionService(self.identity_service, self.agent_stops)` → `pass` | T17, T18 |
| M34 | runtime.py | `except Exception:  # AD-1346 M3a: a failed construction is logged and the boot goes on (#1604, property 11)` → `except TypeError:  # AD-1346 M3a` | T19 |
| M35 | runtime.py | `logger.warning("AD-1346 M3a: the shadow admission service was not built; runtime.admission_service stays None and the boot continues", exc_info=True)` → `pass` | T19 |
| M36 | shutdown.py | `runtime.admission_service = None  # AD-1346 M3a: the service holds the facade; released with it` → `pass` | T17, T18 |
| M37 | checks.py | `if principal.ref is None:` → `if False:` | T8, T18 |

Uniqueness, checked against the file texts in this contract: `return None` occurs once in `service.py` (`decide` and the readers return values); `except Exception:` occurs once in `service.py`; `if principal.ref is None:` once in `checks.py`. In `runtime.py`, M34's anchor carries a comment no other line has, and M33 and M35 are new text. M16 and M17 share an anchor (two mutants of one line). M1's `\|` is a Markdown escape of `|`.

---

## Hidden pins (enumerated on this tree)

| Pin | Reads | Effect of this slice |
|---|---|---|
| `tests/test_ad1343_stop_seam_inventory.py:66-72` | every `STOP_CALLEES` call in `src/probos` outside `agent_stop.py` | none: the package calls `stop_for`, which is not in `STOP_CALLEES` (`census.py:25`) |
| `tests/test_ad1343_stop_seam_inventory.py:199-205` | `_stopped` and `standing_stop` callers | none: neither is called (T15) |
| `tests/test_ad1343_seam_registry.py:44-45`, `:74-77` (R1) | `GUARD_CALLEES` sites; `agent_work_calls()` | `self.decide(...)` in `shadow` is recorded with receiver `self`, which `is_agent_work_call` excludes (`census.py:151`) |
| `tests/fixtures/ad1343_seam_census.py:40` | calls passing `agent_stops=`, `admitted_turn=`, `admitted_synthesis=` | none: positional construction (D26) |
| `tests/test_ad1346_identity_service.py:463-481` | `IdentityRef(...)` constructions in `src` | none: the package constructs none |
| `tests/test_issue1419_failed_start_rollback.py:150-164` | `ProbOSRuntime.start` source (decorator, signature, last statement) | none of those lines changes |
| `tests/test_issue1419_failed_start_rollback.py:1392-1426` | every `steps(...)` in shutdown has a case | no `steps(...)` added (D27) |
| `tests/test_layer_boundaries.py:152-165` | layer of each `probos.*` import | `admission` is in no layer map; runtime is core |
| `tests/test_ad1270b_architecture_fitness.py:488` | `unranked_top_level` contains `toolbox` | `admission` is added to the report's unranked list; the assertion is a containment |
| `scripts/check_architecture_principles.py:187-188`, baseline `docs/development/architecture-baseline.yaml:870-874` | SRP triggers; the `ProbOSRuntime` row records triggers, not counts | no runtime method; the largest new class has 7 methods |
| `scripts/check_store_registry.py:15-20` | modules holding `CREATE TABLE`; `storage_declarations.py` files | none in the package (M3b adds the store and its declaration) |
| `tests/test_bf781_isolation_claims.py:317-369` | three phrases in `shutdown.py` | untouched lines |
| `tests/test_ad680_public_runtime_api.py:106-119` | private runtime access outside `runtime.py` | the package reads no runtime attribute |
| `tests/fixtures/runtime_factory.py:74-92` | fast-teardown modules, pinned by an AST scan | File T2 uses `rt.stop()` and no fast teardown |

---

## What This Does NOT Change

- No seam calls the service (M3c). No store, flusher or report (M3b). No ticket, carrier or sink check (M3d). No effect-point census (M3e). No lifecycle, earned-agency, scope, budget or AD-698 check (M3f).
- No change to `AgentStopService`, `IdentityService`, `routers/agent_stop.py`, any router, `api.py`, `startup/finalize.py`, `config.py`.
- No enforcement (M4). Nothing is refused anywhere.

## Compatibility

- **Routes, schemas, config, events:** none added or changed. Enumerated: T16 lists every file in `src/probos` containing `admission_service` (two) and importing `probos.admission` (one), neither a router.
- **Behaviour:** the boot gains one construction between `IdentityService` and `create_agent_fleet` with no await and no I/O (T14); nothing reads the result (T16). A construction failure logs one WARNING and changes nothing else (T19).
- **Zero-config boot:** M3a reads no configuration (T13). Bound: R6.

## Tracking

- `PROGRESS.md`: Section 5a.
- `DECISIONS.md`: Section 5b, with the campaign of record filled in.
- `docs/development/roadmap.md`: no row (no BF).
- #1604 checklist: the orchestrator records M3a against acceptance 6, 7 (the method: the in-memory log2 latency histogram; the persisted p99 is M3b), 9 (the taxonomy and the cause), 10, 11 (the gate's startup never blocks), 12 and 13, as the memo's slice table states them.

## Acceptance Criteria

1. Files 1a-1e exist as specified; Sections 3-4 applied; File T1 (16) and File T2 (3) pass at `-n 0`.
2. The M1 and M2 focused checks pass, including both checkers.
3. Mutation campaign: 37 of 37 killed, recorded as the campaign of record in `DECISIONS.md`.
4. No file outside those named here changes (`git diff --cached --stat`).
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Diff Reviewer: properties to verify

The consumer that must accept this change: M3b and M3c's contracts, which freeze on `VERDICT_KEYS`, the vocabularies and `shadow()`'s signature.

1. `check_agent_stop` reads the stop record with `stop_for` and nothing else on it; no line in the package calls `refusal`, `active_stop`, `standing_stop`, `tool_refusal` or `refuse_new_run`.
2. Every verdict a request can produce passes `AdmissionVerdict.__post_init__`, and every value in `to_dict()` is JSON-serializable.
3. `shadow()` cannot raise an `Exception` subclass to its caller and returns None on every path.
4. No cause string is built from `StopRecord.reason`.
5. The runtime's construction is between `IdentityService` and `create_agent_fleet`, and any `Exception` from the import or the constructor leaves `admission_service` None and lets `start()` continue.
6. Shutdown's release runs on a clean stop and on a rollback (T17, T18).
7. Tracker and docstring prose states mechanisms; a universal word ("every", "only", "never", "always", "at most", "before", "until") is pinned by a named test or cites its enumeration.

---

## Verified Against Codebase (2026-10-20, on `5548a476`)

```
git rev-parse HEAD
  5548a476b0e92ac3a8f57621cfa9aad8fedf9b2d
scripts/ad_ceiling.py
  CEILING: AD-1346 (git log --all subjects, GitHub issue titles (all states), prompts/ad-*.md filenames); NEXT AD-1347
git ls-files --eol PROGRESS.md DECISIONS.md src/probos/runtime.py src/probos/startup/shutdown.py
  i/lf w/crlf (each)

src/probos/agent_stop.py
  49:  STOP_REASON_CODE: Final = "agent_stopped"
  62:  SEAM_TOOL: Final = "tool"
  70:  SEAMS: Final[frozenset[str]] = frozenset({
  237-243: def sender_text ... "Nothing was started and nothing is queued for later."
  325: class AgentStopService:
  328-335: __init__(self, *, data_dir, event_log=None, connection_factory=None, clock=time.time)
  373-377: def stop_for(self, agent_id: str) -> StopRecord | None: ... return self._active.get(agent_id)
  379-393: def refusal(...): counts[seam] = counts.get(seam, 0) + 1
  388-392: logger.log(logging.INFO if counts[seam] == 1 else logging.DEBUG, ...)
  399: def refused_counts(self, stop_id: str) -> dict[str, int]:
  403: async def issue_stop(self, agent_id: str, *, reason: str) -> StopIssued:
  435: async def lift_stop(self, agent_id: str, *, reason: str) -> StopLifted:
  439-441: "The counts returned, sent to the EventLog and kept in the row are final"
  563: def active_stop(gate, agent_id, seam)   588: def standing_stop(gate, agent_id)
src/probos/identity_service.py
  31:  IDENTITY_REF_KEYS = ("slot_id", "sovereign_id", "did", "callsign", "agent_type")
  79:  def resolve(self, key: str) -> IdentityRef | None:
  119-125: cert ref, did=cert.did     128-134: asset ref, did=""
src/probos/identity.py
  804-827: resolve_slot_id: "Reads the in-memory caches only; never raises."
  870-876: async def resolve_or_issue_asset_tag(self, slot_id, asset_type, pool_name, tier="infrastructure")
src/probos/routers/agent_stop.py
  62-66: def _slot_id(...): slot = identities.resolve_slot_id(agent_id) ...; return slot or agent_id
  100-109: slot = _slot_id(runtime, agent_id) ... await stops.issue_stop(slot, reason=req.reason)
src/probos/execution/authority.py
  109: _REASON_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")
  481: class AdmissionRequest:    491: class AdmissionDecision:
src/probos/runtime.py
  164-166: from probos.acm import AgentCapitalService / from probos.agent_stop import AgentStopService  # AD-1343 / from probos.approval_authority import ApprovalAuthorityStore  # AD-1213
  226: logger = logging.getLogger(__name__)
  523-526: identity_registry / identity_key_binding / identity_service annotations / pool_scaler
  635: self.config = config or load_config(_DEFAULT_CONFIG)
  1201-1203: self.identity_registry / identity_key_binding / identity_service = None defaults
  2773-2774: self.agent_stops = AgentStopService(...); await self.agent_stops.start()
  2816-2820: from probos.identity_service import IdentityService / self.identity_service = IdentityService(...) / fleet = await create_agent_fleet(
src/probos/startup/shutdown.py
  1408-1413: agent stop record stop (steps)
  1429-1434: identity registry block; 1434: runtime.identity_service = None  # AD-1346 M1a ...
tests/fixtures/ad1343_seam_census.py
  25: STOP_CALLEES   27: GUARD_CALLEES = STOP_CALLEES | {"standing_stop", "_stopped"}
  34: GENERIC_AGENT_METHODS = frozenset({"perceive", "decide", "act", "report", "consult"})
  40: PINNED_KEYWORDS = frozenset({"admitted_turn", "agent_stops", "admitted_synthesis"})
  106: def census()  113: def function(rel, qualname)  132: def calls(name)  143: def first_line(...)
  149-156: is_agent_work_call: receiver "" / "self" excluded; generic names need a receiver ending in agent
tests/fixtures/ad1343_seam_registry.py
  46: "decide": "within_turn"
tests/fixtures/runtime_lifecycle.py
  60-68: START_FAILURE_PHASES includes "fleet_entry"; 336: def inject_start_failure; 372-373: fleet_entry -> create_agent_fleet
tests/test_ad1346_identity_service_boot.py
  46-57: _config(), _boot();  134-151: T15 fleet_entry + rollback releases identity_service
tests/test_issue1419_failed_start_rollback.py
  150-164: start source pins;  1127: _STOPPED_COMPONENTS;  1392: test_every_guarded_step_in_shutdown_has_a_case_in_this_file
src/probos/config_models/knowledge.py
  361-362: ArchiveConfig enabled True, db_path ""  (tests/conftest.py:17-18 sets PROBOS_DATA_DIR under the test temp dir)
pyproject.toml
  181: asyncio_mode = "auto"
```

## Absence Verified (2026-10-20)

```
A1 CLAIM: no WorkRequest, AdmissionVerdict, AdmissionService, admission_service or probos.admission in any .py
   RUN:   Grep "admission_service|probos\.admission\b|from probos import admission|WorkRequest|AdmissionVerdict|AdmissionService" glob *.py
   FOUND: routers/threads.py:126,269 (StartWorkRequest); execution/authority.py:726,1272 and tests/test_ad1315...:820,1526 ("probos.admission-policy.v1", "probos.admission-target.v1" digest labels)
   HOLDS: yes; none is the name, the attribute or the package
A2 CLAIM: src/probos/admission does not exist
   RUN:   Glob src/probos/admission*     FOUND: none     HOLDS: yes
A3 CLAIM: execution/ defines no *_CODE constant (D8)
   RUN:   Grep "^\s*[A-Z][A-Z0-9_]*_CODE[A-Z_]*\s*(:|=)" in src/probos/execution     FOUND: none     HOLDS: yes
A4 CLAIM: no probos logger turns propagation off (T12, T19 read caplog)
   RUN:   Grep "propagate = False|\.propagate =" in src/probos     FOUND: none     HOLDS: yes
A5 CLAIM: AgentIdentityRegistry defines no __len__ or __bool__ (shutdown's `if runtime.identity_registry:` is a None test)
   RUN:   Grep "def __len__|def __bool__" in src/probos/identity.py     FOUND: none     HOLDS: yes
A6 CLAIM: no test pins the full unranked-package list
   RUN:   Grep "unranked_top_level|top_level" in tests     FOUND: test_ad1270b_architecture_fitness.py:488 (containment of "toolbox"); others unrelated
   HOLDS: yes
A7 CLAIM: no test pins `identity_service = None` or the Phase 2 construction text
   RUN:   Grep "create_agent_fleet|identity_service = None|_AOS\(|Phase 2: Agent Fleet" in tests
   FOUND: runtime_lifecycle.py:373; test_ad1346_identity_service_boot.py docstrings and assertions on behaviour; test_ad691 and test_identity_deterministic read create_agent_fleet's own source
   HOLDS: yes
A8 CLAIM: config.py declares no field whose name starts with "admission" (T13's `"admission" not in SystemConfig.model_fields`)
   RUN:   Grep "^\s+admission\w*\s*:" in src/probos/config.py (SystemConfig is at :3858)     FOUND: none     HOLDS: yes
```

## Prior Art and Blind Spots

**Internal.** The epic's design note (#1601: single decision, effect points, the forgery rule), the memo (#1604, D1-D17), M1a's binding (`DECISIONS.md:416`) and S1's constraints are the inputs and are absorbed above. The architecture review `docs/architecture/architecture-review-2026-10-20.md` is the epic's source and was not re-read for this slice.

**External (date used: 2026-10-20).**
- Envoy's RBAC filter evaluates `shadow_rules` beside the enforced rules and only increments `shadow_allowed` / `shadow_denied` counters, "used to test that a new set of policies work before rolling out" ([Envoy RBAC filter](https://envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/rbac_filter)). **Absorbed:** the in-memory tally; adapted to key on the reason code as well as the outcome, because #1604 property 3 classifies each would-refuse by cause.
- Kubernetes `ValidatingAdmissionPolicy` separates a policy's verdict actions (`Deny`, `Warn`, `Audit`) from its error handling (`failurePolicy: Ignore` drops evaluation errors) ([Validating Admission Policy](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/)). **Adapted:** shadow is the audit action, and errors fail open, but they are **counted** (`failures`) rather than dropped, because #1604 property 6 says shadow "fails open and counts".
- OPA-style decision logs (each decision with its input and result): **considered, deferred** to M3b, which owns persistence.
- `docs/research/reference-projects.md`: no listed row is an authorization or admission project, so no overdue row was examined and no row changes.

**Blind spots named.**
1. A seam that builds its own `WorkRequest` would raise into the seam (closed by D24).
2. Log flooding from one defect on the hot path (D25).
3. Threads: `shadow` mutates plain dicts and holds no lock (T14); M3c must call it on the loop (D35, R2).
4. A stop on a slot that resolves to nothing reads as `identity_unresolved`, not `agent_stopped` (R3).
5. The tally's key space is closed by validation (D30), so traffic cannot grow it.

## Residuals

- **R1.** The v1 work-kind names are chosen before any seam uses them. They become persisted values in M3b; a name no seam uses stays as an unused value.
- **R2.** Thread use is a binding on M3c (D35), not a guard in the code. Follows from the code; not measured.
- **R3.** A Captain's stop on a slot the facade does not resolve gives `identity_unresolved` in shadow while today's seam refuses `agent_stopped` (`active_stop` keys on the id the seam passes, `agent_stop.py:563-574`). Both are refusals; M3c's parity count compares outcomes and records the code pair.
- **R4.** The DID and certificate-UUID forms cost the facade's scan over the crew (`identity.py:821`); M3b's measured p99 is the evidence (#1604 property 7).
- **R5.** `refusal` stays callable by anything holding the stop record; T15 pins only that this package does not call it.
- **R6.** No literal `SystemConfig()` boot runs (naming ceremony, proactive loop and QA on). The construction reads no configuration (T13); that it therefore behaves the same follows from the code and is not measured.
- **R7.** A `system:`-prefixed id that resolves through the facade is an agent principal and gets the stop check (D22).

## Captain's post-deploy steps for this slice

Nothing observable is expected: no route, log line on a healthy boot, file or event changes. Optional check, read-only: the vessel's startup log has no line containing `shadow admission service was not built`. If it has one, the service is absent (`runtime.admission_service` None) and the boot continued; report it on #1604.

**Needs the Captain:** nothing.

---

## Amendment A1 (2026-10-21, after review round 1: findings F2 and F3; F1 is process)

### A1: round-1 findings F2 (narrow the fail-open claims to the mechanism) and F3 (resolve first for a `system:` id)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-21

Every SEARCH below is written against candidate r1 (staged tree `3907ba15`) and occurs once in its file. The only source changes are docstrings, comments and one log-message string.

**Decisions.**

| # | Decision | Rejected alternative | Why |
|---|---|---|---|
| D36 | Each of the two `except Exception` branches (`shadow`, and the runtime's from D31 and D34) holds one log call with no guard of its own. The prose states that mechanism and no wider fail-open claim. Recorded as F-212 on #1523. **Binding on M3c:** its contract, which adds the first caller of `shadow`, decides whether `shadow` guards its log call and pins the answer with a test. The runtime block stays as it is. | Guard both log calls now | In M3a, `shadow` has no caller (T16). The one `logging.Handler` subclass in `src/` counts records (`__main__.py:97-111`). The stdlib handlers `__main__.py` installs send an `emit` failure other than `RecursionError` to `handleError`. `start()` already logs without a guard on the same logger (`runtime.py:2696-2698`). |
| D37 | T8 also registers `system:dream_scheduler` as an asset slot. It pins that the facade's answer comes first: unresolved, the id is `system` / would-refuse / `system_principal_unlisted`; registered, the id and its tag UUID are `asset` / admit / `admitted`, keyed on the slot. The code is unchanged (D22). | Test the prefix first | This is D22's rejection: a slot id with the `system:` prefix would skip the stop check. |

**A1-1 `src/probos/admission/service.py`**

SEARCH:
```python
verdict and its latency in memory and returns None, so a seam has no result to act on; when
anything in it raises it counts the failure, logs it and returns None. M3a has no caller,
no store and no configuration field; AD-1346 M3b persists the counts.
```
REPLACE:
```python
verdict and its latency in memory and returns None, so a seam has no result to act on. Its
``except Exception`` counts an ``Exception`` raised by that work, passes it to the module
logger and returns None (T12); the log call has no guard of its own (D36). M3a has no caller,
no store and no configuration field; AD-1346 M3b persists the counts.
```

SEARCH:
```python
        that raises propagates from here; ``shadow`` is where a failure is contained.
```
REPLACE:
```python
        that raises propagates from here (T12); ``shadow`` holds the ``except Exception``.
```

SEARCH:
```python
        """Decide in shadow, count the verdict and its latency, and return None (fail open, #1604 property 6)."""
```
REPLACE:
```python
        """Decide in shadow, count the verdict and its latency, and return None; count and log an ``Exception`` (#1604 property 6; D24, D25, D36)."""
```

SEARCH:
```python
        """Shadow calls that raised since this service was built."""
```
REPLACE:
```python
        """Exceptions that ``shadow``'s ``except Exception`` counted since this service was built."""
```

**A1-2 `src/probos/runtime.py` (comments and the log string only)**

SEARCH:
```python
        # Phase 1a started. Nothing calls it yet (AD-1346 M3c adds the seams). If the import or the
        # constructor raises, the failure is logged, the attribute keeps its __init__ None and the
        # boot goes on (#1604, property 11; D31, D34).
        try:
            from probos.admission import AdmissionService

            self.admission_service = AdmissionService(self.identity_service, self.agent_stops)
        except Exception:  # AD-1346 M3a: a failed construction is logged and the boot goes on (#1604, property 11)
            logger.warning("AD-1346 M3a: the shadow admission service was not built; runtime.admission_service stays None and the boot continues", exc_info=True)
```
REPLACE:
```python
        # Phase 1a started. Nothing calls it yet (AD-1346 M3c adds the seams). The import and the
        # constructor are inside the try; the except branch logs an Exception and assigns nothing, so
        # the attribute keeps its __init__ None (#1604, property 11; D31, D34). Its log call has no
        # guard of its own (D36).
        try:
            from probos.admission import AdmissionService

            self.admission_service = AdmissionService(self.identity_service, self.agent_stops)
        except Exception:  # AD-1346 M3a (#1604, property 11; D31, D34)
            logger.warning("AD-1346 M3a: the shadow admission service was not built; runtime.admission_service stays None", exc_info=True)
```

**A1-3 `tests/test_ad1346_admission_service.py`**

SEARCH: `- T8  the system-principal allowlist.`
REPLACE: `- T8  the system-principal allowlist, for an id the facade does not resolve; a ``system:`` id it resolves is that slot's.`

SEARCH: `- T12 ``shadow`` fails open: a malformed request or a raising dependency is counted and logged, not raised.`
REPLACE: `- T12 ``shadow`` counts and logs a malformed request and a raising facade and returns None; ``decide`` propagates.`

SEARCH:
```python
async def test_only_an_allowlisted_system_principal_is_admitted(gate: AdmissionService) -> None:
    """T8: ``system:ship_computer`` is admitted, any other ``system:`` id is not (kills M3, M13, M15, M21, M37)."""
```
REPLACE:
```python
async def test_the_system_allowlist_applies_to_an_id_the_facade_does_not_resolve(
    registry: AgentIdentityRegistry, gate: AdmissionService,
) -> None:
    """T8: unresolved, ``system:ship_computer`` is admitted and ``system:dream_scheduler`` is not; registered as an asset
    slot, ``system:dream_scheduler`` and its tag UUID resolve through the facade first and are admitted as an asset (D22,
    D37; kills M3, M13, M15, M21, M37, M38). Not covered: a certificate slot with the prefix, or a stop on one."""
```

SEARCH:
```python
    assert "'system:dream_scheduler'" in unlisted.cause
```
REPLACE:
```python
    assert "'system:dream_scheduler'" in unlisted.cause
    tag = await registry.resolve_or_issue_asset_tag("system:dream_scheduler", "dream_scheduler", "dream_scheduler")
    for key in ("system:dream_scheduler", tag.asset_uuid):
        resolved = gate.decide(_request(key, origin="system", origin_id="system:dream_scheduler"))
        assert (resolved.outcome, resolved.reason_code, resolved.check, resolved.principal_kind, resolved.key) == (
            "admit", "admitted", "", "asset", "system:dream_scheduler",
        ), key
        assert resolved.principal is not None and resolved.principal.slot_id == "system:dream_scheduler"
        assert resolved.principal.did == ""
```

SEARCH: `    """T10: the constructor refuses anything but the two real types, and ``decide`` anything but a request (kills M18 to M20)."""`
REPLACE: `    """T10: the constructor refuses an object that is not an instance of the two types, and ``decide`` one whose type is not ``WorkRequest`` (kills M18 to M20)."""`

SEARCH:
```python
async def test_shadow_fails_open_counts_and_logs(
```
REPLACE:
```python
async def test_shadow_counts_and_logs_an_exception_and_returns_none(
```

SEARCH: `    """T12: a malformed request and a raising facade are counted and logged, never raised (kills M30 to M32)."""`
REPLACE: `    """T12: with healthy logging, a malformed request and a raising facade are counted, logged and answered with None (kills M30 to M32)."""`

SEARCH: `        gate.decide(_request(SURGEON_SLOT))  # decide propagates; only shadow contains a failure`
REPLACE: `        gate.decide(_request(SURGEON_SLOT))  # decide propagates the facade's exception`

**A1-4 `tests/test_ad1346_admission_service_boot.py`**

SEARCH: `"""AD-1346 M3a (#1604) - real-boot tests: the shadow ``AdmissionService`` is wired, and its failure does not stop a boot.`
REPLACE: `"""AD-1346 M3a (#1604) - real-boot tests: the shadow ``AdmissionService`` is wired, and a constructor that raises is logged.`

SEARCH:
```
- T19 a constructor that raises is logged once at WARNING with its traceback, ``runtime.admission_service`` stays None,
      and the boot completes.
```
REPLACE:
```
- T19 a constructor that raises ``RuntimeError`` is logged once at WARNING with its traceback,
      ``runtime.admission_service`` stays None, and that boot completes.
```

SEARCH: `    """T19: #1604 property 11, the gate's startup failure leaves the boot going (kills M34, M35)."""`
REPLACE: `    """T19: #1604 property 11 for a constructor that raises ``RuntimeError``: logged, the attribute None, the boot completes (kills M34, M35)."""`

**A1-5 `PROGRESS.md` (substrings of line 3)**

SEARCH: `(an id that the facade does not resolve and that has no `system:` prefix, or a `system:` id outside the allowlist `{"system:ship_computer"}`, is a would-refuse)`
REPLACE: `(an id that the facade does not resolve is a would-refuse unless it is a `system:` id on the allowlist `{"system:ship_computer"}`; the facade is asked first, so a `system:` id that names a registered slot is that slot's certificate or asset principal)`

SEARCH: `; when anything in it raises it counts the failure, logs it and returns None.`
REPLACE: `; its `except Exception` counts an `Exception` raised by that work in `failures`, passes it to the module logger and returns None.`

SEARCH: `; when the constructor raises (a real-boot test injects it), the failure is logged, `runtime.admission_service` stays None and the boot continues.`
REPLACE: `; its `except Exception` logs the exception and assigns nothing, so `runtime.admission_service` keeps its `__init__` None (a real-boot test injects a constructor `RuntimeError`, and that boot completes). Neither `except` guards its own log call (F-212 on #1523).`

**A1-6 `DECISIONS.md` (the AD-1346 M3a entry)**

SEARCH: `a failure increments `failures`, the first is logged at WARNING with its traceback and later ones at DEBUG.`
REPLACE: `an `Exception` raised inside the `try` increments `failures`; the first is passed to the logger at WARNING with its traceback and later ones at DEBUG (T12). The log call has no guard of its own (D36).`

SEARCH: `**Binding on M3c:** seams call `shadow()`, not `decide()`, on the event loop.`
REPLACE:
```
**Binding on M3c:** seams call `shadow()`, not `decide()`, on the event loop.
- *D36 (the fail-open mechanism; round-1 F2, F-212 on #1523).* Each `except Exception` (`shadow`'s, and the runtime's of D31 and D34) holds one log call with no guard of its own; the prose states that mechanism and no wider fail-open claim. M3a guards neither: `shadow` has no caller in M3a (T16), the one `logging.Handler` subclass in `src/` counts records (`__main__.py:97-111`), the stdlib handlers `__main__.py` installs send an `emit` failure other than `RecursionError` to `handleError`, and `start()` logs unguarded on the same logger (`runtime.py:2696-2698`). **Binding on M3c:** its contract, which adds the first caller, decides whether `shadow` guards its log call and pins the answer with a test; the runtime block stays as it is. Rejected: guard both log calls now.
- *D37 (resolve first for a `system:` id; round-1 F3).* T8 registers `system:dream_scheduler` as an asset slot: unresolved it is `system` / would-refuse / `system_principal_unlisted`; registered, it and its tag UUID are `asset` / admit / `admitted`, keyed on the slot (M38). The code is unchanged (D22). Rejected: test the prefix first (D22).
```

SEARCH: `a raising constructor is logged and the boot completes`
REPLACE: `a constructor that raises `RuntimeError` is logged and that boot completes`

SEARCH: `a resolvable `system:` slot is an agent principal`
REPLACE: `a `system:` id the facade resolves is a certificate or asset principal, T8 pinning the asset case`

**Mutation table changes:** M34 and M35 get new anchors, and M38 is a new row. The full rows are in section 5 below.

**Tests first: the measurement against r1.** No production behaviour changes, so with the A1 tests the r1 code passes 19 of 19 and collects 16 + 3 tests. The discriminating measurement is M38:
1. Apply M38 with the **r1** test file at `-n 0`. T8 passes: M38 survives on r1.
2. Apply M38 with the **A1** test file. T8 fails.
3. On the A1 tree, check that T19 kills M34 and M35 at their new anchors.

**What This Does NOT Change:** the code paths of `checks.py`, `service.py` or `runtime.py`; T14's logger rule; the number of tests.

**Acceptance:** verify that all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**Verified against r1 (2026-10-21):**
- `service.py`: :6-8, :53-54, :81, :88-95, :113
- `runtime.py`: :2696-2698, :2823-2832
- `checks.py`: :63-69, :74-80, :85-86
- `identity.py:870-881` (`resolve_or_issue_asset_tag(slot_id, asset_type, pool_name, …)`)
- `__main__.py`: :97-111, :148, :155, :171
- CPython 3.12.13: `logging/__init__.py:1159-1168`, `logging/handlers.py:65-77`
- tests: `…service.py:17`, `:22`, `:325-338`, `:365`, `:404-407`, `:419`; `…boot.py:1`, `:11-12`, `:128`

**Absence verified (2026-10-21):**
- **Claim:** no other `Handler` subclass exists in `src/`. **Run:** Grep `class \w+\([^)]*Handler[^)]*\)` in src. **Found:** `__main__.py:97` only.
- **Claim:** no test pins the narrowed runtime text. **Run:** Grep `boot goes on|a failed construction|AD-1346 M3a` in tests/, excluding the two M3a test files. **Found:** nothing.
- **Claim:** nothing outside the T1 file and the contract uses the renamed test names. **Run:** Grep `only_an_allowlisted_system_principal|shadow_fails_open`. **Found:** the T1 file and the contract only.

**5. Mutation rows (from the Architect's answer to A1; the orchestrator reruns the whole table, now 38 rows, on the final tree)**

| ID | File | Whole stripped line → mutant | Killed by | Status |
|---|---|---|---|---|
| M34 | runtime.py | `except Exception:  # AD-1346 M3a (#1604, property 11; D31, D34)` → `except TypeError:  # AD-1346 M3a` | T19 | Re-anchored. Unique: Grep `AD-1346 M3a` in runtime.py shows only :2831 with this `except` form. |
| M35 | runtime.py | `logger.warning("AD-1346 M3a: the shadow admission service was not built; runtime.admission_service stays None", exc_info=True)` → `pass` | T19 | Re-anchored; new text. T19 matches only the substring "shadow admission service was not built". |
| M38 | checks.py | `if ref is not None:` → `if ref is not None and not presented_id.startswith(SYSTEM_PRINCIPAL_PREFIX):` | T8 | New row. Unique: `checks.py:64`; the nearby lines are `:85 if principal.ref is None:` and `:88 if record is None:`. |
