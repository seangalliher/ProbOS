# AD-1343 S1: the Captain's stop for one crew agent: one record, refused at every dispatch seam

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-19
**Status:** ready to build (S1 of S1–S4) · **Issue:** #1595 (Captain exemption from the capability pause: safety control) · **Tier:** HIGH · **Base:** `origin/main` `45058ae7` · **Depends on:** BF-906 (#1594, merged), BF-907 (#1597, merged) · **Estimated tests:** 26 + 9 + 3 new, 2 edited

## Problem

`suspend` records an HR status and stops nothing (`routers/acm.py:17-34,84-103`). No ship service refuses an agent's work by the Captain's order. Every operational gate is health or agent state (`proactive.py:1013-1068`; `ward_room_router.py:898-998`). Every path that gives a crew agent work ends in one of three places:
- `CognitiveAgent.handle_intent` (`cognitive_agent.py:7741`), the subscribed handler (`agent_onboarding.py:237`);
- `CognitiveAgent.handle_consultation_request` (`cognitive_agent.py:8435`), called directly by `ConsultationProtocol` (`consultation.py:221`);
- `ToolRegistry.check_and_invoke` (`tools/registry.py:341`).

Five routes do work around those sinks: the DM route (`routers/agents.py:2954`), the group fan-out (`routers/thread_fanout.py:635`), Ward Room routing (`ward_room_router.py:575`), the proactive cycle (`proactive.py:1002`) and the browser-action ACK, which invokes the tool directly (`routers/agent_actions.py:71`).

## Solution

1. One Ship's Computer service, `AgentStopService` (`probos/agent_stop.py`), owns the stop: a durable row per Captain's order in `agent_stops.db`, and an in-memory view loaded at start.
2. Every seam asks it one question through `active_stop(...)`. That call reads memory only and counts a refusal by seam.
3. Three sinks refuse before any skill, LLM, tool or memory work. Five source checks refuse before the work their route does around a sink.
4. Captain routes under `/api/stops` issue, lift and list stops, behind the existing Captain authority.
5. The EventLog records each order and lift (Captain as initiator, no reason text).
6. An AST census pins the inventory, so a later dispatch path cannot bypass the stop silently.
7. S1 does **not** end work that is already running (S2). Every answer says so in `scope`.

## Implementation

### Section 1: `src/probos/agent_stop.py` (new, whole file)

```python
"""AD-1343 S1 (#1595): the Captain's stop for one crew agent, owned by the ship.

ProbOS is a vessel of vessels: each crew member is its own vessel carried inside the
ship. The stop belongs to the ship. This module holds the Captain's stop orders and
answers one question for every dispatch seam: is this agent stopped, and by which
order? The seams consult it; the agent never does, and nothing an agent can reach
issues or lifts an order (``routers/agent_stop.py`` holds the only callers, pinned by
``tests/test_ad1343_stop_seam_inventory.py``).

Durable authority: ``agent_stops.db``, one row per order; a partial unique index
allows one active order per agent, and a lift updates its row and never deletes it.
The in-memory view is loaded at start and is the only thing a seam reads, so no
dispatch does I/O and no seam can find the record unreadable after startup. An
unopenable store aborts startup: nothing runs without the record.

S1 refuses new work. It does not end work already running (S2), stop every agent at
once (S3) or reach external harness sessions (S4); ``S1_SCOPE`` says so in every answer
the Captain receives.

The EventLog is told of each order and lift, best effort: the store is authoritative.
The Captain's free-text reason stays in the store (inside the BF-758 file-read floor)
and is never copied into the EventLog, which agents can query.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from probos.tools.protocol import ToolResult
from probos.types import IntentMessage, IntentResult

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory, DatabaseConnection
    from probos.substrate.event_log import EventLog

logger = logging.getLogger(__name__)

STORE_FILENAME: Final = "agent_stops.db"
CAPTAIN: Final = "captain"
STOP_REASON_CODE: Final = "agent_stopped"
STOP_METADATA_KEY: Final = "agent_stop"
MAX_REASON_CHARS: Final = 500

# The EventLog pair, as module constants bound once so the AD-1195 census resolves
# ('agent_stop', 'agent_stop_issued') and ('agent_stop', 'agent_stop_lifted').
STOP_EVENT_CATEGORY = "agent_stop"
STOP_ISSUED_EVENT = "agent_stop_issued"
STOP_LIFTED_EVENT = "agent_stop_lifted"

# Where a refusal happened. Every seam that consults the stop names one of these.
SEAM_INTENT: Final = "intent"
SEAM_CONSULTATION: Final = "consultation"
SEAM_TOOL: Final = "tool"
SEAM_PROACTIVE: Final = "proactive"
SEAM_WARD_ROOM: Final = "ward_room"
SEAM_DM_ROUTE: Final = "dm_route"
SEAM_GROUP_FANOUT: Final = "group_fanout"
SEAM_BROWSER_ACTION: Final = "browser_action_ack"
SEAMS: Final[frozenset[str]] = frozenset({
    SEAM_INTENT, SEAM_CONSULTATION, SEAM_TOOL, SEAM_PROACTIVE, SEAM_WARD_ROOM,
    SEAM_DM_ROUTE, SEAM_GROUP_FANOUT, SEAM_BROWSER_ACTION,
})

S1_SCOPE: Final[dict[str, str]] = {
    "refuses": (
        "New work for the agent, wherever it is dispatched: intents (DMs, Ward Room notices, "
        "proactive and duty cycles, work items and the mesh), consultations, group chat turns, "
        "the DM route, browser-action ACKs and every tool call, protected effects included."
    ),
    "does_not_end": (
        "Work already running when the order was given (AD-1343 S2): a turn in progress may "
        "finish and post, though each tool call it makes is refused; a promoted turn the Captain "
        "approves while the agent is stopped resumes, with its tool calls refused."
    ),
    "not_covered": (
        "Voice and appearance proposals the Captain requests directly; the ship's upkeep of the "
        "agent's records (dreams, trust decay); every agent at once (AD-1343 S3); external harness "
        "sessions, which are not_reachable until AD-1342."
    ),
}

LIFT_NOTE: Final = (
    "Dispatch is restored. Work refused while the agent was stopped is not replayed; "
    "refused_while_stopped counts it by seam since the last start."
)

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS agent_stops (
    stop_id      TEXT PRIMARY KEY,
    agent_id     TEXT NOT NULL,
    reason       TEXT NOT NULL,
    issued_by    TEXT NOT NULL,
    issued_at    REAL NOT NULL,
    lifted_by    TEXT,
    lifted_at    REAL,
    lift_reason  TEXT,
    refused_json TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS agent_stops_one_active
    ON agent_stops (agent_id) WHERE lifted_at IS NULL;
"""
_INSERT: Final = (
    "INSERT INTO agent_stops (stop_id, agent_id, reason, issued_by, issued_at) VALUES (?, ?, ?, ?, ?)"
)
_SELECT_ACTIVE: Final = (
    "SELECT stop_id, agent_id, reason, issued_by, issued_at FROM agent_stops WHERE lifted_at IS NULL"
)
_LIFT: Final = (
    "UPDATE agent_stops SET lifted_by = ?, lifted_at = ?, lift_reason = ?, refused_json = ? "
    "WHERE stop_id = ? AND lifted_at IS NULL"
)


def _utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds")


def _valid_reason(reason: object) -> str:
    if type(reason) is not str or not reason.strip() or len(reason) > MAX_REASON_CHARS:
        raise ValueError(f"AD-1343: a reason of 1..{MAX_REASON_CHARS} characters is required")
    return reason.strip()


@dataclass(frozen=True, slots=True)
class StopRecord:
    """One Captain's order in force: which agent, why, by whom and since when."""

    stop_id: str
    agent_id: str
    reason: str
    issued_by: str
    issued_at: float

    def sender_text(self) -> str:
        """What a sender is told. Names the order, never the Captain's reason."""
        return (
            f"Not delivered: agent {self.agent_id} is stopped by the Captain's order "
            f"(stop {self.stop_id}, since {_utc(self.issued_at)}). Nothing was started "
            "and nothing is queued for later."
        )

    def sender_detail(self) -> dict[str, str]:
        """The refusal as data, for an HTTP body or result metadata."""
        return {
            "code": STOP_REASON_CODE,
            "agent_id": self.agent_id,
            "stop_id": self.stop_id,
            "since": _utc(self.issued_at),
            "message": self.sender_text(),
        }

    def notice(self, callsign: str) -> str:
        """One line for a thread that addressed the stopped agent."""
        return (
            f"{callsign} is stopped by the Captain's order (stop {self.stop_id}) "
            "and will not reply here until the stop is lifted."
        )

    def refuse_intent(self, intent: IntentMessage, agent_id: str) -> IntentResult | None:
        """A refusal naming the order for an intent sent to this agent; None for a broadcast.

        A broadcast addressed no one, so the stopped agent abstains, as an agent that
        does not handle the intent: a failure row would read to the broadcaster as a fault.
        """
        if intent.target_agent_id != agent_id:
            return None
        text = self.sender_text()
        return IntentResult(
            intent_id=intent.id,
            agent_id=agent_id,
            success=False,
            result=text,
            error=text,
            confidence=0.0,
            metadata={STOP_METADATA_KEY: self.sender_detail()},
        )

    def public_dict(self) -> dict[str, Any]:
        """The Captain's view of the order, reason included."""
        return {
            "stop_id": self.stop_id,
            "agent_id": self.agent_id,
            "reason": self.reason,
            "issued_by": self.issued_by,
            "issued_at": self.issued_at,
            "since": _utc(self.issued_at),
        }


@dataclass(frozen=True, slots=True)
class StopIssued:
    record: StopRecord
    already_stopped: bool
    durable: bool


@dataclass(frozen=True, slots=True)
class StopLifted:
    record: StopRecord
    lifted_at: float
    refused: dict[str, int]


class StopNotFound(LookupError):
    """No Captain's stop is in force for the agent."""


class AgentStopService:
    """Ship's Computer service: the Captain's stop orders and the one question every seam asks."""

    def __init__(
        self,
        *,
        data_dir: str | Path,
        event_log: "EventLog | None" = None,
        connection_factory: "ConnectionFactory | None" = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._event_log = event_log
        self._clock = clock
        self._db: "DatabaseConnection | None" = None
        self._active: dict[str, StopRecord] = {}
        self._volatile: set[str] = set()
        self._refused: dict[str, dict[str, int]] = {}
        self._lock = asyncio.Lock()
        if connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            connection_factory = default_factory
        self._connection_factory = connection_factory

    async def start(self) -> None:
        """Open the store and load every order in force. Raises when the store cannot be opened."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db = await self._connection_factory.connect(str(self._data_dir / STORE_FILENAME))
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        async with self._db.execute(_SELECT_ACTIVE) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            self._active[row[1]] = StopRecord(row[0], row[1], row[2], row[3], float(row[4]))
        if self._active:
            logger.warning(
                "AD-1343: %d agent(s) remain stopped by the Captain's order: %s",
                len(self._active), ", ".join(sorted(self._active)),
            )

    async def stop(self) -> None:
        """Close the store. The in-memory view is kept: a stopped agent stays refused."""
        async with self._lock:
            if self._db is not None:
                await self._db.close()
                self._db = None

    def stop_for(self, agent_id: str) -> StopRecord | None:
        """The order in force for ``agent_id``, or None. Memory only."""
        if type(agent_id) is not str:
            return None
        return self._active.get(agent_id)

    def refusal(self, agent_id: str, seam: str) -> StopRecord | None:
        """The order in force for ``agent_id``, counted as one refusal at ``seam``; None when not stopped."""
        if seam not in SEAMS:
            raise ValueError(f"AD-1343: unknown seam {seam!r}")
        record = self.stop_for(agent_id)
        if record is None:
            return None
        counts = self._refused.setdefault(record.stop_id, {})
        counts[seam] = counts.get(seam, 0) + 1
        logger.log(
            logging.INFO if counts[seam] == 1 else logging.DEBUG,
            "AD-1343: refused %s work for %s under the Captain's stop %s (%d at this seam)",
            seam, agent_id, record.stop_id, counts[seam],
        )
        return record

    def active(self) -> tuple[StopRecord, ...]:
        """Every order in force, oldest first."""
        return tuple(sorted(self._active.values(), key=lambda record: record.issued_at))

    def refused_counts(self, stop_id: str) -> dict[str, int]:
        """Refusals by seam under one order since this start."""
        return dict(self._refused.get(stop_id, {}))

    async def issue_stop(self, agent_id: str, *, reason: str) -> StopIssued:
        """Stop one crew agent by the Captain's order.

        Applied to the in-memory view before it is written: if the write fails the agent
        is still stopped, and the answer says the order ends at the next restart. Issuing
        for an agent already stopped returns the order in force.
        """
        if type(agent_id) is not str or not agent_id:
            raise ValueError("AD-1343: agent_id must be a non-empty str")
        text = _valid_reason(reason)
        async with self._lock:
            existing = self._active.get(agent_id)
            if existing is not None:
                return StopIssued(existing, already_stopped=True, durable=existing.stop_id not in self._volatile)
            record = StopRecord(uuid.uuid4().hex, agent_id, text, CAPTAIN, self._clock())
            self._active[agent_id] = record
            durable = await self._write_issued(record)
            if not durable:
                self._volatile.add(record.stop_id)
        await self._record_issued(record, durable)
        return StopIssued(record, already_stopped=False, durable=durable)

    async def lift_stop(self, agent_id: str, *, reason: str) -> StopLifted:
        """Lift the Captain's stop on one agent.

        Written before it is applied: if the write fails the agent stays stopped and the
        error propagates. Work refused while stopped is not replayed; its counts are kept
        in the row and the lift event.
        """
        text = _valid_reason(reason)
        async with self._lock:
            record = self.stop_for(agent_id)
            if record is None:
                raise StopNotFound(agent_id)
            lifted_at = self._clock()
            refused = self.refused_counts(record.stop_id)
            if record.stop_id not in self._volatile:
                if self._db is None:
                    raise RuntimeError("AD-1343: the stop store is closed; the stop stays in force")
                await self._db.execute(
                    _LIFT, (CAPTAIN, lifted_at, text, json.dumps(refused, sort_keys=True), record.stop_id),
                )
                await self._db.commit()
            del self._active[agent_id]
            self._volatile.discard(record.stop_id)
            self._refused.pop(record.stop_id, None)
        await self._record_lifted(record, lifted_at, refused)
        return StopLifted(record, lifted_at, refused)

    async def _write_issued(self, record: StopRecord) -> bool:
        """Write an order; False (logged) when the store is closed or the write fails."""
        if self._db is None:
            logger.error(
                "AD-1343: stop %s for %s is in force but NOT written (the stop store is closed); "
                "it ends at the next restart", record.stop_id, record.agent_id,
            )
            return False
        try:
            await self._db.execute(
                _INSERT, (record.stop_id, record.agent_id, record.reason, record.issued_by, record.issued_at),
            )
            await self._db.commit()
        except Exception:
            logger.error(
                "AD-1343: stop %s for %s is in force but was NOT written; it ends at the next restart",
                record.stop_id, record.agent_id, exc_info=True,
            )
            return False  # log-and-degrade: the stop stays in force
        return True

    async def _record_issued(self, record: StopRecord, durable: bool) -> None:
        """Tell the EventLog of an order, best effort: the store is authoritative."""
        if self._event_log is None:
            return
        try:
            await self._event_log.log(
                category=STOP_EVENT_CATEGORY,
                event=STOP_ISSUED_EVENT,
                agent_id=record.agent_id,
                data={
                    "stop_id": record.stop_id,
                    "initiated_by": record.issued_by,
                    "issued_at": record.issued_at,
                    "reason_chars": len(record.reason),
                    "durable": durable,
                },
            )
        except Exception:
            logger.warning(
                "AD-1343: the EventLog did not record stop %s for %s; agent_stops.db is authoritative",
                record.stop_id, record.agent_id, exc_info=True,
            )

    async def _record_lifted(self, record: StopRecord, lifted_at: float, refused: dict[str, int]) -> None:
        """Tell the EventLog of a lift, best effort: the store is authoritative."""
        if self._event_log is None:
            return
        try:
            await self._event_log.log(
                category=STOP_EVENT_CATEGORY,
                event=STOP_LIFTED_EVENT,
                agent_id=record.agent_id,
                data={
                    "stop_id": record.stop_id,
                    "initiated_by": CAPTAIN,
                    "issued_at": record.issued_at,
                    "lifted_at": lifted_at,
                    "refused": refused,
                },
            )
        except Exception:
            logger.warning(
                "AD-1343: the EventLog did not record the lift of stop %s; agent_stops.db is authoritative",
                record.stop_id, exc_info=True,
            )


def active_stop(gate: object, agent_id: object, seam: str) -> StopRecord | None:
    """The order in force for ``agent_id``, counted as one refusal at ``seam``, or None.

    ``gate`` is whatever the seam holds. Only a real ``AgentStopService`` answers, and only
    an exact ``StopRecord`` counts, so a seam built without the service (a test double, an
    older wiring) routes exactly as before. The production wiring is pinned by
    tests/test_ad1343_stop_crossing.py.
    """
    if not isinstance(gate, AgentStopService) or type(agent_id) is not str:
        return None
    record = gate.refusal(agent_id, seam)
    return record if type(record) is StopRecord else None


def tool_refusal(gate: object, agent_id: object, tool_id: str) -> ToolResult | None:
    """The tool sink's refusal for a stopped agent, or None."""
    stopped = active_stop(gate, agent_id, SEAM_TOOL)
    if stopped is None:
        return None
    return ToolResult(
        error=f"Tool {tool_id!r} was not run. {stopped.sender_text()}",
        metadata={STOP_METADATA_KEY: stopped.sender_detail()},
    )
```

### Section 2: `src/probos/storage_declarations.py`: declare the store

<<<<<<< SEARCH
            "ignores it). The probos doctor crew_enrollment check reads it with the adapter's read_only open."
        ),
    ),
)
=======
            "ignores it). The probos doctor crew_enrollment check reads it with the adapter's read_only open."
        ),
    ),
    StoreDeclaration(
        id="agent-stop.captain-orders",
        title="The Captain's stop orders for crew agents: issued, in force and lifted (AD-1343)",
        owner_module="probos.agent_stop",
        owner_symbol="AgentStopService",
        canonical_path="agent_stops.db",
        criticality=StoreCriticality.REQUIRED,
        lifecycle_owner="probos.runtime.ProbOSRuntime.start",
        retention=StoreRetention.UNBOUNDED,
        retention_note=(
            "No DELETE FROM in probos.agent_stop. One row per Captain's order; a lift updates its row and "
            "never removes it, so the table is the record of every stop. Growth is bounded by the Captain's "
            "own orders. No `probos reset` tier deletes it: a reset never lifts a stop."
        ),
        backup="included",
        restore="unknown",
        notes=(
            "Started without a guard in ProbOSRuntime.start (Phase 1a, before any agent exists), so an "
            "unopenable agent_stops.db aborts startup; closed in startup/shutdown.py, which keeps the "
            "in-memory view. Opened through the ConnectionFactory. Table: agent_stops, with a partial unique "
            "index allowing one active stop per agent. Inside the BF-758 file-read floor (the data directory)."
        ),
    ),
)
>>>>>>> REPLACE

### Section 3: runtime wiring (`src/probos/runtime.py`, `src/probos/startup/shutdown.py`)

3.1 `runtime.py`, TYPE_CHECKING import
<<<<<<< SEARCH
    from probos.acm import AgentCapitalService
    from probos.approval_authority import ApprovalAuthorityStore  # AD-1213
=======
    from probos.acm import AgentCapitalService
    from probos.agent_stop import AgentStopService  # AD-1343
    from probos.approval_authority import ApprovalAuthorityStore  # AD-1213
>>>>>>> REPLACE

3.2 `runtime.py`, class annotation
<<<<<<< SEARCH
    acm: AgentCapitalService | None
    crew_enrollment: "CrewEnrollmentService | None"  # BF-906
=======
    acm: AgentCapitalService | None
    crew_enrollment: "CrewEnrollmentService | None"  # BF-906
    agent_stops: "AgentStopService | None"  # AD-1343
>>>>>>> REPLACE

3.3 `runtime.py`, `__init__` default
<<<<<<< SEARCH
        self.event_log = EventLog(db_path=self._data_dir / "events.db")
        self.execution_authority = None
        self.effect_broker = None
=======
        self.event_log = EventLog(db_path=self._data_dir / "events.db")
        self.execution_authority = None
        self.effect_broker = None
        self.agent_stops = None  # AD-1343: started in Phase 1a
>>>>>>> REPLACE

3.4 `runtime.py`, Phase 1a (in `ProbOSRuntime.start`)
<<<<<<< SEARCH
        self.execution_authority = infra.execution_authority
        self.effect_broker = infra.effect_broker
        # AD-1195: Phase 1 opened the EventLog; durable rows are written on this loop.
=======
        self.execution_authority = infra.execution_authority
        self.effect_broker = infra.effect_broker
        # AD-1343 (Phase 1a): the Captain's stop record. Started before any agent exists,
        # so no dispatch precedes it; an unopenable agent_stops.db aborts startup, so
        # nothing runs without the record (fail-closed by construction).
        from probos.agent_stop import AgentStopService

        self.agent_stops = AgentStopService(data_dir=self._data_dir, event_log=self.event_log)
        await self.agent_stops.start()
        # AD-1195: Phase 1 opened the EventLog; durable rows are written on this loop.
>>>>>>> REPLACE

3.5 `runtime.py`, the tool sink's gate (after Phase 7). **Apply in M2, together with Section 6.3 (amendment A1: it calls `set_stop_gate`, which does not exist until 6.3).**
<<<<<<< SEARCH
        self.continue_extension_permit_store = comm.continue_extension_permit_store  # AD-1323
        self.tool_registry = comm.tool_registry
        self.tool_permission_store = comm.tool_permission_store
=======
        self.continue_extension_permit_store = comm.continue_extension_permit_store  # AD-1323
        self.tool_registry = comm.tool_registry
        if self.tool_registry is not None:  # AD-1343: every tool path ends in check_and_invoke
            self.tool_registry.set_stop_gate(self.agent_stops)
        self.tool_permission_store = comm.tool_permission_store
>>>>>>> REPLACE

3.6 `startup/shutdown.py`
<<<<<<< SEARCH
    # Stop ACM (AD-427)
    if runtime.acm:
        with steps("ACM stop", runtime.acm):
            await runtime.acm.stop()
        runtime.acm = None
=======
    # Stop ACM (AD-427)
    if runtime.acm:
        with steps("ACM stop", runtime.acm):
            await runtime.acm.stop()
        runtime.acm = None

    # Close the Captain's stop record (AD-1343). The runtime keeps the service: its
    # in-memory view goes on refusing a stopped agent until the process ends.
    agent_stops = getattr(runtime, "agent_stops", None)
    if agent_stops is not None:
        with steps("agent stop record stop", agent_stops):
            await agent_stops.stop()
>>>>>>> REPLACE

### Section 4: Captain routes

4.1 `src/probos/routers/agent_stop.py` (new, whole file)

```python
"""AD-1343 S1 (#1595): the Captain's stop for one crew agent.

    GET  /api/stops                  the stops in force, with refusals counted by seam
    POST /api/stops/{agent_id}       stop one crew agent (slot id, certificate UUID or did:probos DID)
    POST /api/stops/{agent_id}/lift  lift it

Authority is the existing Captain authority on the API. ``require_crew_scope`` answers 401
to a missing or wrong bearer token once ``auth.crew_scope_token`` is set; because it lets
every caller through while no token is set, these routes answer 403 until one is (the
AD-1196 / AD-1340 rule: no Captain order through an open gate). Agent tools do not reach
them: ``security/url_guard.py`` refuses loopback to ``http_fetch`` and to every browser
context ProbOS creates. The residual is stated in the AD-1343 contract (C1): a shell or
sandbox run that could read ``config/system.yaml`` could present the token.

Every answer carries ``scope``: what S1 refuses and what it does not end.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from probos.agent_stop import LIFT_NOTE, S1_SCOPE, AgentStopService, StopNotFound
from probos.crew_utils import is_crew_agent
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stops", tags=["agent-stop"])

_TOKEN_REQUIRED = "agent_stop_requires_crew_scope_token"
_UNAVAILABLE = "agent_stop_unavailable"


class AgentStopRequest(BaseModel):
    """The Captain's reason for a stop or a lift."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)


async def _captain_stops(runtime: Any = Depends(get_runtime)) -> AgentStopService:
    """The stop service for a Captain order: 503 while absent, then 403 while no token is configured."""
    stops = getattr(runtime, "agent_stops", None)
    if not isinstance(stops, AgentStopService):
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)
    if not runtime.config.auth.crew_scope_token:  # AD-1343: never a Captain order through an open gate
        raise HTTPException(status_code=403, detail=_TOKEN_REQUIRED)
    return stops


def _slot_id(runtime: Any, agent_id: str) -> str:
    """The slot id an agent id, certificate UUID or did:probos DID names (BF-907 resolver)."""
    identities = getattr(runtime, "identity_registry", None)
    slot = identities.resolve_slot_id(agent_id) if identities is not None else None
    return slot or agent_id


def _enforceable(agent: Any) -> bool:
    """True when the agent's work entry points are the ones the stop guards."""
    from probos.cognitive.cognitive_agent import CognitiveAgent

    cls = type(agent)
    return (
        getattr(cls, "handle_intent", None) is CognitiveAgent.handle_intent
        and getattr(cls, "handle_consultation_request", None) is CognitiveAgent.handle_consultation_request
    )


@router.get("", dependencies=[Depends(require_crew_scope)])
async def list_agent_stops(stops: AgentStopService = Depends(_captain_stops)) -> dict[str, Any]:
    """The stops in force, oldest first, with refusals counted by seam since this start."""
    return {
        "stops": [
            {**record.public_dict(), "refused": stops.refused_counts(record.stop_id)}
            for record in stops.active()
        ],
        "scope": dict(S1_SCOPE),
    }


@router.post("/{agent_id}", dependencies=[Depends(require_crew_scope)])
async def issue_agent_stop(
    agent_id: str,
    req: AgentStopRequest,
    runtime: Any = Depends(get_runtime),
    stops: AgentStopService = Depends(_captain_stops),
) -> dict[str, Any]:
    """Stop one crew agent by the Captain's order (AD-1343 S1)."""
    slot = _slot_id(runtime, agent_id)
    agent = runtime.registry.get(slot)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent_not_found")
    if not is_crew_agent(agent, runtime.ontology):
        raise HTTPException(status_code=422, detail="not_crew")
    if not _enforceable(agent):
        raise HTTPException(status_code=422, detail="stop_not_enforceable")
    try:
        outcome = await stops.issue_stop(slot, reason=req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    body: dict[str, Any] = {
        "status": "stopped",
        "already_stopped": outcome.already_stopped,
        "stop": outcome.record.public_dict(),
        "scope": dict(S1_SCOPE),
    }
    if not outcome.durable:
        raise HTTPException(
            status_code=503,
            detail={**body, "code": "stop_not_durable", "applied_until_restart": True},
        )
    return body


@router.post("/{agent_id}/lift", dependencies=[Depends(require_crew_scope)])
async def lift_agent_stop(
    agent_id: str,
    req: AgentStopRequest,
    runtime: Any = Depends(get_runtime),
    stops: AgentStopService = Depends(_captain_stops),
) -> dict[str, Any]:
    """Lift the Captain's stop on one agent. Work refused while it was stopped is not replayed."""
    slot = _slot_id(runtime, agent_id)
    try:
        lifted = await stops.lift_stop(slot, reason=req.reason)
    except StopNotFound:
        raise HTTPException(status_code=404, detail="no_active_stop") from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("AD-1343: the lift of %s's stop was not written; the agent stays stopped", slot, exc_info=True)
        raise HTTPException(status_code=503, detail="stop_store_write_failed") from exc
    return {
        "status": "lifted",
        "stop": lifted.record.public_dict(),
        "lifted_at": lifted.lifted_at,
        "refused_while_stopped": lifted.refused,
        "note": LIFT_NOTE,
    }
```

4.2 `src/probos/api.py` (two blocks)
<<<<<<< SEARCH
        approval_authority as approval_authority_router,  # AD-1213: the Captain's approval-authority controls
        decision_pre_clearances as decision_pre_clearances_router,  # AD-1214: the Captain's decision pre-clearances
    )
=======
        approval_authority as approval_authority_router,  # AD-1213: the Captain's approval-authority controls
        decision_pre_clearances as decision_pre_clearances_router,  # AD-1214: the Captain's decision pre-clearances
        agent_stop as agent_stop_router,  # AD-1343: the Captain's stop for one agent
    )
>>>>>>> REPLACE

<<<<<<< SEARCH
        approval_authority_router,  # AD-1213: the Captain's approval-authority controls
        decision_pre_clearances_router,  # AD-1214: the Captain's decision pre-clearances
    ):
        app.include_router(r.router)
=======
        approval_authority_router,  # AD-1213: the Captain's approval-authority controls
        decision_pre_clearances_router,  # AD-1214: the Captain's decision pre-clearances
        agent_stop_router,  # AD-1343: the Captain's stop for one agent
    ):
        app.include_router(r.router)
>>>>>>> REPLACE

### Section 5: the intent and consultation sinks (`src/probos/cognitive/cognitive_agent.py`)

5.1 `handle_intent`
<<<<<<< SEARCH
        Returns None (self-deselect) for intents not in _handled_intents,
        unless it's a targeted direct_message (AD-397 1:1 sessions).
        """
        # AD-397: always accept direct_message if targeted to this agent
=======
        Returns None (self-deselect) for intents not in _handled_intents,
        unless it's a targeted direct_message (AD-397 1:1 sessions).
        """
        # AD-1343: the Captain's stop, before any skill, LLM, tool or memory work.
        # Read through the ship's runtime, never from the agent's own state.
        from probos.agent_stop import SEAM_INTENT, AgentStopService

        _stops = getattr(getattr(self, "_runtime", None), "agent_stops", None)
        if isinstance(_stops, AgentStopService):
            _stopped = _stops.refusal(self.id, SEAM_INTENT)
            if _stopped is not None:
                return _stopped.refuse_intent(intent, self.id)

        # AD-397: always accept direct_message if targeted to this agent
>>>>>>> REPLACE

5.2 `handle_consultation_request`
<<<<<<< SEARCH
        """AD-594: Handle an incoming expert consultation request."""
        from probos.cognitive.consultation import ConsultationResponse

        callsign = getattr(self, "callsign", None) or self.agent_type
=======
        """AD-594: Handle an incoming expert consultation request."""
        from probos.cognitive.consultation import ConsultationResponse

        # AD-1343: a stopped agent gives no consultation; the requester is told which order.
        from probos.agent_stop import SEAM_CONSULTATION, STOP_REASON_CODE, AgentStopService

        _stops = getattr(getattr(self, "_runtime", None), "agent_stops", None)
        if isinstance(_stops, AgentStopService):
            _stopped = _stops.refusal(self.id, SEAM_CONSULTATION)
            if _stopped is not None:
                return ConsultationResponse(
                    request_id=request.request_id,
                    responder_id=self.id,
                    answer=_stopped.sender_text(),
                    confidence=0.0,
                    reasoning_summary=STOP_REASON_CODE,
                )

        callsign = getattr(self, "callsign", None) or self.agent_type
>>>>>>> REPLACE

### Section 6: the tool sink (`src/probos/tools/registry.py`, `src/probos/cognitive/crew_verifier.py`)

**ToolRegistry's body must stay ≤ 500 lines.** It measured 470 on `45058ae7`; these edits add about 21.

6.1 imports
<<<<<<< SEARCH
from probos.events import EventType
from probos.tools.protocol import (
    Tool,
=======
from probos.agent_stop import STOP_REASON_CODE, tool_refusal
from probos.events import EventType
from probos.tools.protocol import (
    Tool,
>>>>>>> REPLACE

<<<<<<< SEARCH
if TYPE_CHECKING:
    from probos.execution.effect_types import (
        EffectPermit,
=======
if TYPE_CHECKING:
    from probos.agent_stop import AgentStopService
    from probos.execution.effect_types import (
        EffectPermit,
>>>>>>> REPLACE

6.2 class default
<<<<<<< SEARCH
        acquire_lock / release_lock / break_lock / get_lock / list_locks — LOTO
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolRegistration] = {}
=======
        acquire_lock / release_lock / break_lock / get_lock / list_locks — LOTO
    """

    # AD-1343: the Captain's stop (set_stop_gate); None routes exactly as before.
    _stop_gate: "AgentStopService | None" = None

    def __init__(self) -> None:
        self._tools: dict[str, ToolRegistration] = {}
>>>>>>> REPLACE

6.3 setter and property
<<<<<<< SEARCH
    def set_event_callback(self, fn: Callable[..., Any]) -> None:
        """Late-bind event emission."""
        self._emit_event = fn
=======
    def set_event_callback(self, fn: Callable[..., Any]) -> None:
        """Late-bind event emission."""
        self._emit_event = fn

    def set_stop_gate(self, gate: "AgentStopService | None") -> None:
        """AD-1343: late-bind the Captain's stop; every tool path ends in check_and_invoke."""
        self._stop_gate = gate

    @property
    def stop_gate(self) -> "AgentStopService | None":
        """AD-1343: the stop this registry enforces (a projected registry inherits it)."""
        return self._stop_gate
>>>>>>> REPLACE

6.4 the check (after the bypass guards, before #1214's existence check)
<<<<<<< SEARCH
                raise ProtectedEffectBypassDenied(
                    "protected_effect_permit_missing"
                )

        # #1214: existence BEFORE permission. This ran the other way round, so
=======
                raise ProtectedEffectBypassDenied(
                    "protected_effect_permit_missing"
                )

        # AD-1343: a stopped agent invokes nothing, whichever path called; refused before any lookup.
        stopped = tool_refusal(self._stop_gate, agent_id, tool_id)
        if stopped is not None:
            if effect_permit is not None:
                from probos.execution.effect_broker import EffectDenied

                raise EffectDenied(STOP_REASON_CODE, result=stopped)
            return stopped

        # #1214: existence BEFORE permission. This ran the other way round, so
>>>>>>> REPLACE

6.5 `crew_verifier.py`, the projected registry inherits the stop
<<<<<<< SEARCH
        super().__init__()
        self._source_registry = source_registry
        self._source_backed_ids = source_backed_ids
=======
        super().__init__()
        # AD-1343: a projected registry enforces its source's stop (super() invokes here).
        self.set_stop_gate(getattr(source_registry, "stop_gate", None))
        self._source_registry = source_registry
        self._source_backed_ids = source_backed_ids
>>>>>>> REPLACE

### Section 7: proactive and Ward Room source checks

7.1 `proactive.py`, import
<<<<<<< SEARCH
from probos.crew_profile import Rank
from probos.crew_utils import is_crew_agent
from probos.cognitive.cognitive_agent import CognitiveAgent
=======
from probos.agent_stop import SEAM_PROACTIVE, active_stop
from probos.crew_profile import Rank
from probos.crew_utils import is_crew_agent
from probos.cognitive.cognitive_agent import CognitiveAgent
>>>>>>> REPLACE

7.2 `proactive.py`, `_run_cycle` eligibility
<<<<<<< SEARCH
        # AD-636: Count eligible agents for stagger calculation
        eligible_agents: list[Any] = []
        for agent in rt.registry.all():
            if not is_crew_agent(agent, rt.ontology):
                continue
            if not agent.is_alive:
                continue
=======
        # AD-636: Count eligible agents for stagger calculation
        eligible_agents: list[Any] = []
        _stops = getattr(rt, "agent_stops", None)  # AD-1343: the Captain's stop
        for agent in rt.registry.all():
            if not is_crew_agent(agent, rt.ontology):
                continue
            if not agent.is_alive:
                continue
            # AD-1343: a stopped agent is offered no proactive work, duty or BF-156 DM sweep.
            if active_stop(_stops, agent.id, SEAM_PROACTIVE) is not None:
                continue
>>>>>>> REPLACE

7.3 `ward_room_router.py`, imports
<<<<<<< SEARCH
from probos.crew_utils import is_crew_agent
from probos.mesh.intent import IntentAuthorizationDenied

if TYPE_CHECKING:
    from probos.cognitive.episodic import EpisodicMemory
=======
from probos.agent_stop import SEAM_WARD_ROOM, active_stop
from probos.crew_utils import is_crew_agent
from probos.mesh.intent import IntentAuthorizationDenied

if TYPE_CHECKING:
    from probos.agent_stop import AgentStopService, StopRecord
    from probos.cognitive.episodic import EpisodicMemory
>>>>>>> REPLACE

7.4 class default
<<<<<<< SEARCH
class WardRoomRouter:
    """Routes Ward Room events to crew agents via intents."""

    _WARD_ROOM_COOLDOWN_SECONDS = 30  # Minimum seconds between responses per agent (captain-triggered)
=======
class WardRoomRouter:
    """Routes Ward Room events to crew agents via intents."""

    _WARD_ROOM_COOLDOWN_SECONDS = 30  # Minimum seconds between responses per agent (captain-triggered)
    # AD-1343: the Captain's stop. A class default so a router built without it routes as before.
    _agent_stops: "AgentStopService | None" = None
>>>>>>> REPLACE

7.5 constructor
<<<<<<< SEARCH
        notify_fn: Callable | None = None,
        proactive_loop: ProactiveCognitiveLoop | None = None,
    ) -> None:
        self._ward_room = ward_room
        self._registry = registry
        self._intent_bus = intent_bus
        self._trust_network = trust_network
        self._ontology = ontology
        self._callsign_registry = callsign_registry
        self._episodic_memory = episodic_memory
        self._event_emitter = event_emitter
        self._event_log = event_log
        self._config = config
        self._notify_fn = notify_fn
        self._proactive_loop = proactive_loop

        # State
=======
        notify_fn: Callable | None = None,
        proactive_loop: ProactiveCognitiveLoop | None = None,
        agent_stops: "AgentStopService | None" = None,
    ) -> None:
        self._ward_room = ward_room
        self._registry = registry
        self._intent_bus = intent_bus
        self._trust_network = trust_network
        self._ontology = ontology
        self._callsign_registry = callsign_registry
        self._episodic_memory = episodic_memory
        self._event_emitter = event_emitter
        self._event_log = event_log
        self._config = config
        self._notify_fn = notify_fn
        self._proactive_loop = proactive_loop
        self._agent_stops = agent_stops

        # State
>>>>>>> REPLACE

7.6 the notice method
<<<<<<< SEARCH
        except Exception:
            logger.debug("BF-200: Failed to post cap notification", exc_info=True)

    # ------------------------------------------------------------------
    # Public API
=======
        except Exception:
            logger.debug("BF-200: Failed to post cap notification", exc_info=True)

    async def _post_stop_notice(self, thread_id: str, agent_id: str, stopped: "StopRecord") -> None:
        """AD-1343: tell a thread once that an agent it addressed is stopped by the Captain."""
        if not self._ward_room:
            return
        notice_key = (thread_id, f"agent_stop:{stopped.stop_id}")
        if notice_key in self._cap_notices_posted:
            return
        self._cap_notices_posted.add(notice_key)
        agent = self._registry.get(agent_id)
        callsign = (getattr(agent, "callsign", "") if agent is not None else "") or agent_id[:8]
        try:
            await self._ward_room.create_post(
                thread_id=thread_id,
                author_id="system",
                body=f"[System] {stopped.notice(callsign)}",
                author_callsign="System",
            )
        except Exception:
            logger.warning(
                "AD-1343: the stop notice for %s in thread %s was not posted", agent_id, thread_id[:8],
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Public API
>>>>>>> REPLACE

7.7 `_route_to_agents`, the check
<<<<<<< SEARCH
            is_direct_target = (
                agent_id in mentioned_agent_ids
                or (channel and channel.channel_type == "dm")
            )

            # AD-614: DM thread exchange limit
=======
            is_direct_target = (
                agent_id in mentioned_agent_ids
                or (channel and channel.channel_type == "dm")
            )

            # AD-1343: a stopped agent is not notified; a thread that addressed it is told once.
            stopped = active_stop(self._agent_stops, agent_id, SEAM_WARD_ROOM)
            if stopped is not None:
                if is_direct_target:
                    await self._post_stop_notice(thread_id, agent_id, stopped)
                continue

            # AD-614: DM thread exchange limit
>>>>>>> REPLACE

7.8 `startup/finalize.py`, wire the router
<<<<<<< SEARCH
            notify_fn=runtime.notify,
            proactive_loop=proactive_loop,
        )
        # AD-637c: Only wire router ref for fallback path (NATS disconnected).
=======
            notify_fn=runtime.notify,
            proactive_loop=proactive_loop,
            agent_stops=getattr(runtime, "agent_stops", None),
        )
        # AD-637c: Only wire router ref for fallback path (NATS disconnected).
>>>>>>> REPLACE

### Section 8: route source checks (DM route, group fan-out, browser ACK)

8.1 `routers/agents.py`, import
<<<<<<< SEARCH
from probos.crew_utils import is_crew_agent
from probos.mesh.intent import IntentAuthorizationDenied
from probos.cognitive.commands.personality_command import (
=======
from probos.agent_stop import SEAM_DM_ROUTE, active_stop
from probos.crew_utils import is_crew_agent
from probos.mesh.intent import IntentAuthorizationDenied
from probos.cognitive.commands.personality_command import (
>>>>>>> REPLACE

8.2 `routers/agents.py`, `_agent_chat_impl`
<<<<<<< SEARCH
    if not is_crew_agent(agent, runtime.ontology):
        raise HTTPException(status_code=400, detail=f"Agent {agent_id} is not a crew agent — direct chat is crew-only")

    # AD-791a: resolve (or create) the implicit default 1:1 thread for this
=======
    if not is_crew_agent(agent, runtime.ontology):
        raise HTTPException(status_code=400, detail=f"Agent {agent_id} is not a crew agent — direct chat is crew-only")

    # AD-1343: a stopped agent takes no DM turn. Refused before the thread, the owned-steps
    # capture, the send and the reply pipeline, so nothing is held, stored or replayed.
    _stopped = active_stop(getattr(runtime, "agent_stops", None), agent_id, SEAM_DM_ROUTE)
    if _stopped is not None:
        raise HTTPException(status_code=409, detail=_stopped.sender_detail())

    # AD-791a: resolve (or create) the implicit default 1:1 thread for this
>>>>>>> REPLACE

8.3 `routers/thread_fanout.py`, import
<<<<<<< SEARCH
from probos.crew_utils import is_crew_agent
from probos.mesh.pre_intent_auth import IntentAuthorizationDenied
from probos.types import IntentMessage
=======
from probos.agent_stop import SEAM_GROUP_FANOUT, active_stop
from probos.crew_utils import is_crew_agent
from probos.mesh.pre_intent_auth import IntentAuthorizationDenied
from probos.types import IntentMessage
>>>>>>> REPLACE

8.4 `routers/thread_fanout.py`, `_send_one_impl`
<<<<<<< SEARCH
        except Exception:
            logger.debug("AD-914: callsign resolve failed for %s", agent_id, exc_info=True)
        # BF-651: saved-output manifest so a reviewer verifies against STORAGE,
=======
        except Exception:
            logger.debug("AD-914: callsign resolve failed for %s", agent_id, exc_info=True)
        # AD-1343: a stopped agent takes no group turn; its slot is released as a decline, so the
        # room is not stalled and nothing is captured, dispatched or stored for it.
        if active_stop(getattr(runtime, "agent_stops", None), agent_id, SEAM_GROUP_FANOUT) is not None:
            return {"agent_id": agent_id, "callsign": callsign, "text": "", "_declined": True}
        # BF-651: saved-output manifest so a reviewer verifies against STORAGE,
>>>>>>> REPLACE

8.5 `routers/agent_actions.py`, import
<<<<<<< SEARCH
from probos.cognitive.dm.action_dispatcher import ActionStatus
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
=======
from probos.agent_stop import SEAM_BROWSER_ACTION, active_stop
from probos.cognitive.dm.action_dispatcher import ActionStatus
from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
>>>>>>> REPLACE

8.6 `routers/agent_actions.py`, `ack_action`
<<<<<<< SEARCH
        return JSONResponse(status_code=409, content={
            "error": "action_already_decided",
            "status": action.status.value,
        })

    browser_tool = getattr(runtime, "browser_tool", None)
    result: Any = None
=======
        return JSONResponse(status_code=409, content={
            "error": "action_already_decided",
            "status": action.status.value,
        })

    # AD-1343: the ACK runs the action as its agent, past the tool registry, so the stop is
    # checked here. The action stays pending; once the stop is lifted it can be ACKed.
    stopped = active_stop(getattr(runtime, "agent_stops", None), action.agent_id, SEAM_BROWSER_ACTION)
    if stopped is not None:
        return JSONResponse(status_code=409, content=stopped.sender_detail())

    browser_tool = getattr(runtime, "browser_tool", None)
    result: Any = None
>>>>>>> REPLACE

### Section 9: existing tests (each change carries an inline `# AD-1343:` reason; none deleted)

9.1 `tests/test_ad1195_eventlog_pair_freeze.py`
<<<<<<< SEARCH
_RESOLVED_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ('backup', 'backup_complete'),
=======
_RESOLVED_PAIRS: frozenset[tuple[str, str]] = frozenset({
    # AD-1343 (#1595): the Captain's stop order and its lift, through STOP_ISSUED_EVENT and
    # STOP_LIFTED_EVENT. Best effort: agent_stops.db is authoritative.
    ('agent_stop', 'agent_stop_issued'),
    ('agent_stop', 'agent_stop_lifted'),
    ('backup', 'backup_complete'),
>>>>>>> REPLACE

9.2 `tests/test_issue1419_failed_start_rollback.py`
<<<<<<< SEARCH
    ("_eviction_audit", "eviction audit log stop"),
    ("acm", "ACM stop"),
    ("visiting_officers", "visiting officer registry stop"),
=======
    ("_eviction_audit", "eviction audit log stop"),
    ("acm", "ACM stop"),
    ("agent_stops", "agent stop record stop"),  # AD-1343: the runtime keeps the service after it closes
    ("visiting_officers", "visiting officer registry stop"),
>>>>>>> REPLACE

### Section 10: `tests/test_ad1343_stop_seam_inventory.py` (new, whole file)

```python
"""AD-1343 S1 (#1595): the stop's seam inventory is pinned, so a later dispatch path cannot bypass it silently.

An AST census of ``src/probos`` in this checkout, in the manner of the AD-1195 pair freeze:

1. STOP CHECKS: every call that consults the Captain's stop (``active_stop(...)``,
   ``tool_refusal(...)`` or ``<x>.refusal(...)``) outside ``probos/agent_stop.py``, by
   (file, enclosing function, callee) and the seam it names. A check removed, added or
   moved fails until this table and the contract's seam inventory change together.
2. ENTRY POINTS: every public coroutine on ``CognitiveAgent``, classified.
3. TOOL BYPASSES: every ``<receiver>.invoke(...)`` whose receiver name ends in ``tool``.
4. ORDER: each sink consults the stop first; each source check precedes the work it guards.
5. REACH: only the Captain's routes issue or lift a stop; the URL floor refuses its routes.

Not seen (stated bounds): an entry reached through an alias or ``getattr``; a tool held
under a name not ending in ``tool``; a synchronous method that starts work
(``resume_promoted_turn`` is named below as S2 scope).
"""

from __future__ import annotations

import ast
import functools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import probos
from probos import agent_stop
from probos.security.url_guard import validate_public_url

_PACKAGE = Path(probos.__file__).resolve().parent
_ROOT = _PACKAGE.parents[1]
_IMPLEMENTATION = "src/probos/agent_stop.py"
_STOP_CALLEES = frozenset({"active_stop", "tool_refusal", "refusal"})
_RECORDED = _STOP_CALLEES | {"invoke", "issue_stop", "lift_stop"}

# (file, enclosing function, callee) -> the seam constant it names.
_STOP_CHECK_SITES: dict[tuple[str, str, str], str] = {
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_intent", "refusal"): "SEAM_INTENT",
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_consultation_request", "refusal"): "SEAM_CONSULTATION",
    ("src/probos/tools/registry.py", "ToolRegistry.check_and_invoke", "tool_refusal"): "SEAM_TOOL",
    ("src/probos/proactive.py", "ProactiveCognitiveLoop._run_cycle", "active_stop"): "SEAM_PROACTIVE",
    ("src/probos/ward_room_router.py", "WardRoomRouter._route_to_agents", "active_stop"): "SEAM_WARD_ROOM",
    ("src/probos/routers/agents.py", "_agent_chat_impl", "active_stop"): "SEAM_DM_ROUTE",
    ("src/probos/routers/thread_fanout.py", "_fan_one_round._send_one_impl", "active_stop"): "SEAM_GROUP_FANOUT",
    ("src/probos/routers/agent_actions.py", "ack_action", "active_stop"): "SEAM_BROWSER_ACTION",
}

# Every public coroutine on CognitiveAgent. sink: consults the stop itself; within_turn: runs
# only inside a turn a sink admitted; dm_route: reached only after the DM route's check;
# captain_persona / s2_in_flight / lifecycle: named S1 exceptions, reported in S1_SCOPE.
_COGNITIVE_AGENT_COROUTINES: dict[str, str] = {
    "handle_intent": "sink",
    "handle_consultation_request": "sink",
    "perceive": "within_turn",
    "decide": "within_turn",
    "act": "within_turn",
    "report": "within_turn",
    "consult": "within_turn",
    "interpret_recall": "within_turn",
    "interpret_own_dream": "within_turn",
    "observe_self_avatar": "dm_route",
    "check_own_render": "dm_route",
    "propose_appearance": "captain_persona",
    "propose_voice_profile": "captain_persona",
    "recover_promoted_turn": "s2_in_flight",
    "stop": "lifecycle",
}
_SYNC_WORK_STARTERS: dict[str, str] = {
    "resume_promoted_turn": "s2_in_flight: AD-855 resume of a turn begun before the stop; tool calls refused",
}

# Direct tool invocations: each skips ToolRegistry.check_and_invoke unless it is that method.
_DIRECT_TOOL_INVOKES: dict[tuple[str, str, str], str] = {
    ("src/probos/tools/registry.py", "ToolRegistry.check_and_invoke", "tool"): "the tool sink, after its check",
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", "browser_tool"):
        "runs only in a DM or group turn whose route checked the stop; plan-mode projection runs no step",
    ("src/probos/routers/agent_actions.py", "ack_action", "browser_tool"): "after SEAM_BROWSER_ACTION",
}

_SOURCE_ORDER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("src/probos/proactive.py", "ProactiveCognitiveLoop._run_cycle", ("_check_unread_dms", "_think_for_agent")),
    ("src/probos/ward_room_router.py", "WardRoomRouter._route_to_agents", ("count_posts_by_author", "dispatch_async")),
    ("src/probos/routers/agents.py", "_agent_chat_impl", ("get_or_create_default_for_agent", "send")),
    ("src/probos/routers/thread_fanout.py", "_fan_one_round._send_one_impl", ("_capture_owned_steps_turn",)),
    ("src/probos/routers/agent_actions.py", "ack_action", ("invoke", "mark_executed", "mark_failed")),
)


@dataclass(frozen=True)
class _Call:
    file: str
    function: str
    callee: str
    receiver: str
    seam: str


class _Visitor(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self._rel = rel
        self._scope: list[str] = []
        self.calls: list[_Call] = []

    def _enter(self, node: ast.AST, name: str) -> None:
        self._scope.append(name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._enter(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            callee, receiver = func.attr, ast.unparse(func.value)
        elif isinstance(func, ast.Name):
            callee, receiver = func.id, ""
        else:
            callee, receiver = "", ""
        if callee in _RECORDED:
            seam = ""
            if callee == "refusal" and len(node.args) >= 2:
                seam = ast.unparse(node.args[1])
            elif callee == "active_stop" and len(node.args) >= 3:
                seam = ast.unparse(node.args[2])
            elif callee == "tool_refusal":
                seam = "SEAM_TOOL"
            self.calls.append(_Call(self._rel, ".".join(self._scope) or "<module>", callee, receiver, seam))
        self.generic_visit(node)


@functools.lru_cache(maxsize=1)
def _census() -> tuple[_Call, ...]:
    calls: list[_Call] = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        visitor = _Visitor(rel)
        visitor.visit(ast.parse(path.read_bytes(), filename=rel))
        calls += visitor.calls
    return tuple(calls)


def _function(rel: str, qualname: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse((_ROOT / rel).read_bytes(), filename=rel)

    def walk(body: list[ast.stmt], prefix: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}.{node.name}" if prefix else node.name
                if name == qualname and not isinstance(node, ast.ClassDef):
                    return node
                hit = walk(node.body, name)
                if hit is not None:
                    return hit
        return None

    found = walk(tree.body, "")
    assert found is not None, (rel, qualname)
    return found


def _calls(name: str) -> Callable[[ast.AST], bool]:
    def match(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        return (isinstance(func, ast.Attribute) and func.attr == name) or (
            isinstance(func, ast.Name) and func.id == name
        )
    return match


def _first_line(node: ast.AST, predicate: Callable[[ast.AST], bool]) -> int:
    lines = [n.lineno for n in ast.walk(node) if predicate(n)]
    assert lines, f"nothing matched in {getattr(node, 'name', node)}"
    return min(lines)


def test_census_premise_reads_this_checkout() -> None:
    """Premise: the census scans this checkout and sees the intent sink."""
    assert (_ROOT / _IMPLEMENTATION).resolve() == Path(agent_stop.__file__).resolve()
    assert any(
        c.function == "CognitiveAgent.handle_intent" and c.callee == "refusal" for c in _census()
    )


def test_stop_checks_are_exactly_the_inventory() -> None:
    found = {
        (c.file, c.function, c.callee): c.seam
        for c in _census()
        if c.callee in _STOP_CALLEES and c.file != _IMPLEMENTATION
    }
    assert found == _STOP_CHECK_SITES, sorted(set(found.items()) ^ set(_STOP_CHECK_SITES.items()))


def test_every_seam_is_checked_and_no_check_names_an_unknown_seam() -> None:
    declared = {
        name for name in dir(agent_stop)
        if name.startswith("SEAM_") and isinstance(getattr(agent_stop, name), str)
    }
    assert {getattr(agent_stop, name) for name in declared} == agent_stop.SEAMS
    assert set(_STOP_CHECK_SITES.values()) == declared


def test_cognitive_agent_entry_points_are_classified() -> None:
    tree = ast.parse((_ROOT / "src/probos/cognitive/cognitive_agent.py").read_bytes())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CognitiveAgent")
    coroutines = {n.name for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and not n.name.startswith("_")}
    assert coroutines == set(_COGNITIVE_AGENT_COROUTINES), sorted(coroutines ^ set(_COGNITIVE_AGENT_COROUTINES))
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    assert set(_SYNC_WORK_STARTERS) <= methods
    sinks = {name for name, kind in _COGNITIVE_AGENT_COROUTINES.items() if kind == "sink"}
    assert sinks == {key[1].split(".")[1] for key in _STOP_CHECK_SITES if key[1].startswith("CognitiveAgent.")}


def test_direct_tool_invocations_are_exactly_the_inventory() -> None:
    found = {
        (c.file, c.function, c.receiver)
        for c in _census()
        if c.callee == "invoke" and c.receiver.split(".")[-1].endswith("tool")
    }
    assert found == set(_DIRECT_TOOL_INVOKES), sorted(found ^ set(_DIRECT_TOOL_INVOKES))


def test_each_sink_consults_the_stop_first() -> None:
    for rel, qualname, limit in (
        ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_intent", 3),
        ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.handle_consultation_request", 4),
    ):
        body = _function(rel, qualname).body
        index = next(i for i, stmt in enumerate(body) if any(_calls("refusal")(n) for n in ast.walk(stmt)))
        assert index <= limit, (qualname, index)
        assert not any(isinstance(n, ast.Await) for stmt in body[:index] for n in ast.walk(stmt)), qualname
    check = _function("src/probos/tools/registry.py", "ToolRegistry.check_and_invoke")
    stop = _first_line(check, _calls("tool_refusal"))
    assert stop < _first_line(check, _calls("resolve_permission"))
    assert stop < _first_line(check, lambda n: isinstance(n, ast.Call) and ast.unparse(n.func) == "self._tools.get")
    assert stop < _first_line(check, _calls("start_permitted_effect"))


def test_each_source_check_precedes_the_work_it_guards() -> None:
    for rel, qualname, guarded in _SOURCE_ORDER:
        fn = _function(rel, qualname)
        stop = _first_line(fn, _calls("active_stop"))
        for name in guarded:
            assert stop < _first_line(fn, _calls(name)), (qualname, name)


def test_only_the_captain_routes_issue_or_lift_a_stop() -> None:
    callers = {(c.file, c.function, c.callee) for c in _census() if c.callee in {"issue_stop", "lift_stop"}}
    assert callers == {
        ("src/probos/routers/agent_stop.py", "issue_agent_stop", "issue_stop"),
        ("src/probos/routers/agent_stop.py", "lift_agent_stop", "lift_stop"),
    }


def test_agent_fetch_and_browser_tools_cannot_reach_the_stop_routes() -> None:
    for url in ("http://127.0.0.1:18900/api/stops/counselor_0", "http://[::1]:18900/api/stops/counselor_0/lift"):
        assert validate_public_url(url) is not None, url
```

## Tests

**`tests/test_ad1343_agent_stop.py`.** Use a real `AgentStopService` on `tmp_path` and a real `EventLog` where events are read.
- **Route tests:** `FastAPI()` plus `app.include_router(router)` plus `app.state.runtime`, called through `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))` on the test's own loop. Use a real `SystemConfig(auth=AuthConfig(crew_scope_token=...))`.
- **Agents in route tests:** `CognitiveAgent.__new__(CognitiveAgent)` with `id` and `agent_type` set, and a fake ontology whose `get_crew_agent_types()` contains that type.

| # | Test | Must show |
|---|---|---|
| T1 | `test_a_stop_is_applied_written_and_survives_a_restart` | issue → close → new service on the same dir → same `stop_id` and reason; lift → restart → `None`; the row has `lifted_at` and `refused_json` |
| T2 | `test_issuing_twice_keeps_one_active_order` | second issue gives `already_stopped=True` and the same id; one row with `lifted_at IS NULL` |
| T3 | `test_a_lifted_agent_can_be_stopped_again_and_history_is_kept` | issue → lift → issue gives `durable=True`; 2 rows, 1 active |
| T4 | `test_a_failed_write_still_stops_the_agent_until_restart` | a connection factory whose `execute` raises on INSERT → `durable=False`; `refusal` returns the record; a restart is not stopped; lifting the volatile order works with no write |
| T5 | `test_a_failed_lift_write_leaves_the_agent_stopped` | UPDATE raises → `lift_stop` raises; `stop_for` still returns the record |
| T6 | `test_lifting_an_agent_that_is_not_stopped_raises` | `StopNotFound` |
| T7 | `test_a_reason_is_required_and_bounded` | `""`, `"   "`, 501 chars and non-str raise `ValueError`; nothing applied |
| T8 | `test_refusals_are_counted_by_seam_and_an_unknown_seam_is_a_bug` | counts by seam; `ValueError` on an unknown seam; counts appear in `StopLifted.refused` |
| T9 | `test_the_eventlog_records_order_and_lift_with_the_captain_and_without_the_reason` | reading `events.db` with stdlib `sqlite3`: rows `('agent_stop','agent_stop_issued')` and `('agent_stop','agent_stop_lifted')`, `initiated_by == "captain"`, and the reason text absent from every `data` |
| T10 | `test_an_eventlog_failure_does_not_undo_a_stop` | `event_log.log` raises → stop applied, `durable=True` |
| T11 | `test_start_raises_when_the_store_cannot_be_opened` | `data_dir` is a file → `start()` raises |
| T12 | `test_closing_keeps_the_in_memory_view` | after `stop()`, `stop_for` still returns the record; a new issue gives `durable=False` |
| T13 | `test_only_a_real_service_answers` | `active_stop(None…)` is `None`; with `MagicMock()`, `gate.refusal.assert_not_called()`; with `MagicMock(spec=AgentStopService)`, `None`; a non-str agent id gives `None` |
| T14 | `test_the_tool_sink_refuses_before_any_lookup_and_is_inert_without_a_stop` | a stopped agent and the unknown id `"ad1343-no-such-tool"` → the stop refusal (not "not found"); **golden**: with no stop, the result equals that of a registry with no gate |
| T15 | `test_a_strict_tool_call_is_denied_with_the_stop_reason_code` | `effect_permit=object()` → `EffectDenied` with `reason_code == "agent_stopped"` and `result` carrying `metadata["agent_stop"]` |
| T16 | `test_a_projected_correction_registry_enforces_its_sources_stop` | `_SessionProjectedToolRegistry(source_registry=reg, source_backed_ids=frozenset(), explicit_denial_ids=frozenset())`: `.stop_gate is gate`, and `check_and_invoke` refuses |
| T17 | `test_ward_room_routing_skips_a_stopped_agent_and_tells_a_direct_thread_once` | a real `WardRoomRouter(...)` built with keyword arguments, `SystemConfig()`, a fake bus that records `dispatch_async` and returns `DispatchAdmission(True)`, and a fake ward room that records `create_post`. Targets `a` (stopped, mentioned) and `b`: only `b` is dispatched; one `[System]` post names the callsign and stop id; a second call posts nothing more; a `create_post` that raises does not stop `b`'s dispatch. **Golden**: with an empty service and with none, the dispatched intents' `params` and `target_agent_id` are identical. |
| T18 | `test_a_browser_action_ack_for_a_stopped_agent_is_refused_and_stays_pending` | fake runtime with `ActionStatus.ACK_PENDING`: 409 with `code == "agent_stopped"`; the browser tool is not invoked; `mark_*` not called. **Golden**: not stopped → invoked |
| T19 | `test_the_stop_routes_refuse_an_open_gate` | token empty: GET, issue and lift → 403 `agent_stop_requires_crew_scope_token`; store untouched |
| T20 | `test_the_stop_routes_require_the_captain_token` | token set: missing header → 401, wrong token → 401, right token → 200, on all three routes |
| T21 | `test_issue_resolves_a_did_to_the_slot_and_answers_with_scope` | fake `resolve_slot_id` maps a DID to the slot; the answer has `stop.agent_id == slot` and `scope == S1_SCOPE` |
| T22 | `test_issue_refuses_unknown_non_crew_and_unenforceable_agents` | 404 `agent_not_found`; 422 `not_crew`; 422 `stop_not_enforceable` (a subclass that overrides `handle_intent`) |
| T23 | `test_a_not_durable_issue_answers_503_and_is_in_force` | 503 with `code == "stop_not_durable"` and `applied_until_restart`; `stop_for` returns the record |
| T24 | `test_lift_answers_with_refusal_counts_404_when_not_stopped_and_503_when_unwritten` | 200 with `refused_while_stopped`; 404 `no_active_stop`; 503 `stop_store_write_failed` with the agent still stopped |
| T25 | `test_the_api_serves_the_stop_routes` | `create_app(MagicMock with real SystemConfig)` → `/api/stops`, `/api/stops/{agent_id}` and `/api/stops/{agent_id}/lift` are among the route paths |
| T26 | `test_refuse_intent_names_the_stop_and_abstains_from_a_broadcast` | a targeted intent gives `success=False` and `stop_id` in `result`; `DmReply.from_intent_result(r).render()` contains the stop id; an untargeted intent gives `None` |

**`tests/test_ad1343_stop_seam_inventory.py`:** Section 10 (I1–I9, in file order).

**`tests/test_ad1343_stop_crossing.py`.** Boot a real runtime: `ProbOSRuntime(data_dir=tmp_path/"data", llm_client=MockLLMClient())` then `await rt.start()`, as in `tests/test_trust_reconcile.py:57-66`. Set the token on `rt.config.auth` with `monkeypatch.setattr`. Pick a crew agent with `next(a for a in rt.registry.all() if is_crew_agent(a, rt.ontology))`.

| # | Test | Must show |
|---|---|---|
| X1 | `test_a_captain_stop_crosses_route_store_restart_and_the_sinks` | **Premise:** `isinstance(rt.agent_stops, AgentStopService)`, `rt.tool_registry.stop_gate is rt.agent_stops`, and `vars(rt.ward_room_router)["_agent_stops"] is rt.agent_stops` when the router exists. **Golden before the stop:** a `direct_message` sent to the agent through `rt.intent_bus.send` returns no `agent_stop` metadata. **Issue** through the route (ASGI) → 200. Then: `send` → `success=False` with the stop id; `crew.handle_consultation_request(ConsultationRequest(requester_id="x", topic="t", question="q", target_agent_id=crew.id))` → `confidence == 0.0` and the stop id in `answer`; `rt.tool_registry.check_and_invoke(crew.id, "ad1343-no-such-tool", {})` → stop metadata. **Stop the runtime**; then `rt.agent_stops.issue_stop(other_crew_id, reason="x")` → `durable is False` (shutdown closed the store). **Second runtime, same `data_dir`:** `stop_for(crew.id).stop_id` matches; `send` is refused again; lift through the route → 200 with `refused_while_stopped["intent"] >= 1`; `send` carries no stop metadata. |
| X2 | `test_a_stopped_agent_gets_no_dm_turn_through_the_route` | with the `routers.agents` router included: POST `/api/agent/{id}/chat` `{"message": "hi"}` → 409 with `detail.code == "agent_stopped"`; `rt.intent_bus.send` (spy) not called |
| X3 | `test_the_proactive_cycle_offers_a_stopped_agent_nothing` | **Premise:** `rt.proactive_loop is not None and rt.ward_room is not None`. If the default boot lacks either, **stop and report to the Architect**; do not invent a fixture. Then set `stagger_enabled=False`, spy on `_check_unread_dms` and `_think_for_agent`, run `await rt.proactive_loop._run_cycle()`: the stopped agent appears in neither spy; at least one other crew agent appears in the `_check_unread_dms` spy. |

**Focused gate per milestone:** `pytest tests/test_ad1343_*.py tests/test_ad1195_eventlog_pair_freeze.py tests/test_issue1419_failed_start_rollback.py tests/test_ad1256_store_registry.py tests/test_bf289_agent_chat_empty_classification.py tests/test_ad791a_chat_threads_wiring.py tests/test_ad617b_per_agent_token_budget.py tests/test_bf190_bf191_route_evaluate.py -n 0`. Then run the eight preflights: `gen_config_reference.py`, `check_config_profiles.py`, `check_config_facade.py`, `gen_ad_ledger.py`, `check_seam_contracts.py`, `check_architecture_principles.py` and `check_store_registry.py` (each with `--check`), plus `compileall`.

## Milestones (each at most about 150 tool calls)

| # | Scope | Green at the cut | Cut point |
|---|---|---|---|
| M1 | §1–§4 except block 3.5, §9 | T1–T13, T19–T26; AD-1195; 1419; store registry; `check_architecture_principles.py --check` | `git diff --stat` shows only the §1–§4/§9 files and `tests/test_ad1343_agent_stop.py` |
| M2 | §5–§8 and block 3.5 (amendment A1) | T14–T18; the source-scan pins listed above; **whole-contract dry run (D18)** | dry-run failures exactly as D18 predicts |
| M3 | §10, the crossing tests, Tracking (including the ledger regeneration) | I1–I9, X1–X3, all preflights | then the Diff Reviewer, the mutation campaign, a local commit, the gate |

## Mutation table (run once on the final tree; every anchor is a whole, unique line in its file)

| ID | File: anchor → mutant | Killed by |
|---|---|---|
| R1 | agent_stop.py `            self._active[agent_id] = record` → `pass` | T1, T23 |
| R2 | agent_stop.py `        return self._active.get(agent_id)` → `return None` | T1, X1 |
| R3 | agent_stop.py `            if existing is not None:` → `if False:` | T2 |
| R4 | agent_stop.py `    ON agent_stops (agent_id) WHERE lifted_at IS NULL;` → `    ON agent_stops (agent_id);` | T3 |
| R5 | agent_stop.py `    "SELECT stop_id, agent_id, reason, issued_by, issued_at FROM agent_stops WHERE lifted_at IS NULL"` → drop the `WHERE` | T1 |
| R6 | agent_stop.py `            self._active[row[1]] = StopRecord(row[0], row[1], row[2], row[3], float(row[4]))` → `pass` | T1, X1 |
| R7 | agent_stop.py `                    _LIFT, (CAPTAIN, lifted_at, text, json.dumps(refused, sort_keys=True), record.stop_id),` → lift writes `None` for `stop_id` | T1 |
| R8 | agent_stop.py `            del self._active[agent_id]` → `pass` | T24, X1 |
| R9 | agent_stop.py `        if seam not in SEAMS:` → `if False:` | T8 |
| R10 | agent_stop.py `        counts[seam] = counts.get(seam, 0) + 1` → `pass` | T8, X1 |
| R11 | agent_stop.py `        if intent.target_agent_id != agent_id:` → `if False:` | T26 |
| R12 | agent_stop.py `                    "reason_chars": len(record.reason),` → `"reason": record.reason,` | T9 |
| R13 | agent_stop.py `                event=STOP_LIFTED_EVENT,` → `event=STOP_ISSUED_EVENT,` | T9, AD-1195 resolved |
| R14 | agent_stop.py `    if not isinstance(gate, AgentStopService) or type(agent_id) is not str:` → `if gate is None:` | T13 |
| R15 | agent_stop.py `    return record if type(record) is StopRecord else None` → `return record` | T13 |
| R16 | agent_stop.py `            return False  # log-and-degrade: the stop stays in force` → `raise` (HAND: log-and-degrade guard) | T4 |
| R17 | agent_stop.py `            if not durable:` → `if False:` | T4 (volatile lift without a write) |
| R18 | registry.py `        stopped = tool_refusal(self._stop_gate, agent_id, tool_id)` → `stopped = None` | T14, X1 |
| R19 | registry.py `                raise EffectDenied(STOP_REASON_CODE, result=stopped)` → `return stopped` | T15 |
| R20 | crew_verifier.py `        self.set_stop_gate(getattr(source_registry, "stop_gate", None))` → removed | T16 |
| R21 | cognitive_agent.py `            _stopped = _stops.refusal(self.id, SEAM_INTENT)` → `_stopped = None` | X1 |
| R22 | cognitive_agent.py `                return _stopped.refuse_intent(intent, self.id)` → `pass` | X1 |
| R23 | cognitive_agent.py `            _stopped = _stops.refusal(self.id, SEAM_CONSULTATION)` → `_stopped = None` | X1 |
| R24 | proactive.py `            if active_stop(_stops, agent.id, SEAM_PROACTIVE) is not None:` → `if False:` | X3 |
| R25 | ward_room_router.py `            stopped = active_stop(self._agent_stops, agent_id, SEAM_WARD_ROOM)` → `stopped = None` | T17 |
| R26 | ward_room_router.py `                if is_direct_target:` → `if False:` | T17 |
| R27 | ward_room_router.py `        if notice_key in self._cap_notices_posted:` → `if False:` | T17 |
| R28 | ward_room_router.py `        self._agent_stops = agent_stops` → `self._agent_stops = None` | T17, X1 |
| R29 | agents.py `    _stopped = active_stop(getattr(runtime, "agent_stops", None), agent_id, SEAM_DM_ROUTE)` → `_stopped = None` | X2 |
| R30 | agent_actions.py `    stopped = active_stop(getattr(runtime, "agent_stops", None), action.agent_id, SEAM_BROWSER_ACTION)` → `stopped = None` | T18 |
| R31 | agent_stop.py router `    if not runtime.config.auth.crew_scope_token:  # AD-1343: never a Captain order through an open gate` → `if False:` | T19 |
| R32 | router `    if not _enforceable(agent):` → `if False:` | T22 |
| R33 | router `    return slot or agent_id` → `return agent_id` | T21 |
| R34 | router `    if not outcome.durable:` → `if False:` | T23 |
| R35 | router `@router.post("/{agent_id}", dependencies=[Depends(require_crew_scope)])` → `@router.post("/{agent_id}")` | T20 |
| R36 | router `@router.get("", dependencies=[Depends(require_crew_scope)])` → `@router.get("")` | T20 |
| R37 | router `        raise HTTPException(status_code=404, detail="no_active_stop") from None` → status 200 | T24 |
| H1 | runtime.py `        await self.agent_stops.start()` → removed (HAND, wiring) | X1 (restart survival), T-1419 leftovers |
| H2 | runtime.py `            self.tool_registry.set_stop_gate(self.agent_stops)` → removed (HAND, wiring) | X1 premise |
| H3 | finalize.py `            agent_stops=getattr(runtime, "agent_stops", None),` → removed (HAND, wiring) | X1 premise |
| H4 | shutdown.py `            await agent_stops.stop()` → `pass` (HAND, wiring) | X1 (`durable is False` after stop); 1419 leftovers |
| H5 | api.py `        agent_stop_router,  # AD-1343: the Captain's stop for one agent` → removed (HAND, wiring) | T25 |
| H6 | thread_fanout.py: delete the two lines `        if active_stop(getattr(runtime, "agent_stops", None), agent_id, SEAM_GROUP_FANOUT) is not None:` and its `return` (HAND, census-only behaviour; S2 adds the joint-work crossing test) | I2 |
| H7 | agent_stop.py `_record_issued`'s `except Exception:` body → `raise` (HAND: log-and-degrade guard) | T10 |
| H8 | ward_room_router.py `_post_stop_notice`'s `except Exception:` body → `raise` (HAND: log-and-degrade guard) | T17 (`b` still dispatched) |

**Campaign of record.** Record it with the tree hash and the sha256 of every changed file. Rerun only the rows whose file differs.

## Diff Reviewer: properties to verify (cross-family)

1. One owner. Only `AgentStopService` reads or writes `agent_stops.db`. Only `routers/agent_stop.py` calls `issue_stop` and `lift_stop`. `issued_by` is always `"captain"` and is not a parameter.
2. Every seam reads memory only. No dispatch path does I/O on the stop. If the store cannot be opened, startup aborts.
3. With no stop issued, every changed seam returns exactly what it returned before, and no new INFO-or-higher log line appears.
4. An order is applied before it is written; a lift is written before it is applied. There is one active order per agent. Nothing is deleted.
5. Each sink consults the stop before any await, LLM, tool or memory work. The tool sink checks before lookup, permission and permit start. The strict path raises `EffectDenied("agent_stopped")` and the broker records it as `denied`, not started.
6. Refused work is never queued for later: a returned refusal is acked, and nothing is replayed on lift. Senders see the stop id and its start time, never the reason. EventLog rows carry `initiated_by: "captain"` and no reason text.
7. All three routes return 401 for a missing or wrong token and 403 while no token is configured.
8. Every answer carries `scope`. Nothing claims that running work was ended.
9. No new EventType, config field or UI. `_LITERAL_PAIRS` stays at 37 and `_RESOLVED_PAIRS` grows by exactly 2. `store-baseline.yaml` and `architecture-baseline.yaml` are byte-identical. The ToolRegistry body is ≤ 500 lines.
10. The shutdown step passes its component to `steps`, and the runtime keeps its reference.
11. Production code reads no private attribute of another module. The agent reads its own `_runtime`; `stop_gate` and `agent_stops` are public.

## What this does NOT change

ACM, suspend and reinstate (still HR only). The circuit breaker. Trust, rank, memory and skills: a stop is not a demerit. `LongRunService.close`. Effect-broker policy. The hook bus. AD-698. Decommission. In-flight work (S2). Vessel-wide stop (S3). Harness sessions (S4). HXI. `config/system.yaml`.

## Decisions

| # | Decision | Rejected alternatives | Envelope |
|---|---|---|---|
| D1 | New `agent_stops.db` owned by `AgentStopService` (`probos/agent_stop.py`), REQUIRED, declared | ACM: at its 15-method cap, and lifecycle can be empty (BF-906). EventLog-sourced: best effort and pruned. Config or directives: reachable. | Architect; additive; reversal is a revert plus deleting the file |
| D2 | Three sinks plus five source checks, one service, memory only, census-pinned | Hook bus: off by default, two paths, a raising handler gives no verdict. AD-698 global hook: intent-only, cannot drop one broadcast candidate. Checks at every caller: they decay. | Architect |
| D3 | `require_crew_scope` plus 403 while the token is unset, on GET, issue and lift | Issue through an open gate: any local caller, including an approved shell, could stop crew | Architect; residual is C1 |
| D4 | Targeted intent → failed `IntentResult` with text and metadata. Broadcast → abstain. Consultation → confidence 0. Tool → error `ToolResult`; strict → `EffectDenied`. DM route and browser ACK → 409. Ward Room → skip plus one notice. Group → declined. Proactive → skip. | A failure row for broadcasts (reads as a fault) | Architect |
| D5 | Record: `stop_id`, slot `agent_id` (DID or UUID resolved by BF-907), reason (1..500), `issued_by` `"captain"`, `issued_at`, plus lift columns. Issuing twice is idempotent. History is kept. | Keying by DID (trust and slots are keyed by slot id, BF-907) | Architect |
| D6 | Issue: apply, then write (503 `stop_not_durable`, `applied_until_restart`). Lift: write, then apply. | Writing first on issue (a disk fault would block an emergency stop) | Architect |
| D7 | If the store cannot be opened, startup aborts (as `acm.db` does) | Fail-open at boot; or stopping every agent while the store is unknown | Architect |
| D8 | The reason is not in the EventLog, which agents can query (`tools/event_log_query_tool.py:161-172`) | Reason in the event | Architect; Captain may overrule |
| D9 | Crew agents only, and only when `handle_intent` and `handle_consultation_request` are CognitiveAgent's; otherwise 422 | Stopping Ship's Computer agents | Architect |
| D10 | No reset tier deletes the store; the startup WARNING lists every agent still stopped | Reset in tier 2 | Architect; Captain may overrule |
| D11 | Named S1 exceptions are reported in `S1_SCOPE` | — | Architect |
| D12 | No EventType, config field or UI | — | Architect |
| D13 | Events go through module constants; the census gains 2 resolved pairs; no `event_persistence` entry | Literal pairs (that would change the count of 37) | Architect |
| D14 | `_STOPPED_COMPONENTS` gains the new step. The runtime keeps its reference after close: a deliberate exception to the "drop the reference" convention, so the in-memory view keeps refusing. | Dropping the reference (an agent would be unstopped during shutdown) | Architect |
| D15 | Class defaults `_stop_gate` and `_agent_stops` = `None`, because `__new__` fixtures are used in 57 test files | Editing those fixtures | Architect |
| D16 | The intent and consultation sinks read the stop through the agent's runtime reference. Crew agents are built with it (`agent_fleet.py:117`), and the spawner treats it as recycle-critical (`spawner.py:78`). Self-mod replacement agents (`self_mod_manager.py:214-224`) are built without it; they are not crew. S2's owner registry removes this dependency. | A module-global registry | Architect |
| D17 | One PR for S1 | — | Architect |
| D18 | Whole-contract dry run before M2 is dispatched: expected failures are exactly the two pins in §9 | — | Architect |
| C1 | Residual: a shell or sandbox run could read the token in `config/system.yaml` | See the answer header | **Captain** before #1595 closes |

## After the next restart (the Captain's checklist)

1. In `%LOCALAPPDATA%\ProbOS\data\logs\probos.log`: **no** `AD-1343: … remain stopped` warning (no stops exist yet).
2. `agent_stops.db` exists. `sqlite3 "file:%LOCALAPPDATA%\ProbOS\data\agent_stops.db?mode=ro" "SELECT count(*) FROM agent_stops"` gives `0`.
3. With `auth.crew_scope_token` empty, `GET /api/stops` answers **403** `agent_stop_requires_crew_scope_token`. Set the token if you want to use the stop.
4. With the token: `Invoke-RestMethod http://127.0.0.1:<api port>/api/stops -Headers @{Authorization="Bearer <token>"}` returns `stops: []` and `scope`.
5. Optional drill on one non-critical crew agent:
   - Issue: `POST /api/stops/<agent id>` with `{"reason":"AD-1343 drill"}`.
   - A DM in the HXI answers **409** naming the stop. (Check how the HXI shows a 409; that is UI, outside S1.)
   - An @mention in the Ward Room gets one `[System] … is stopped` post.
   - In `events.db` (`?mode=ro`), `SELECT timestamp, agent_id, data FROM events WHERE category='agent_stop'` shows the issued row with `"initiated_by": "captain"` and no reason text.
   - Restart: the log shows `1 agent(s) remain stopped`, and the DM still answers 409.
   - Lift: 200 with `refused_while_stopped`, then a lifted row in `events.db`. The DM works again.

## Tracking

- **DECISIONS.md:** add `### AD-1343 S1 -- The Captain's stop for one crew agent: one record, refused at every dispatch seam (2026-10-19, #1595)` directly after the BF-907 entry, before `DECISIONS.md:276`. Include D1–D18, C1's status and the campaign of record.
- **PROGRESS.md:** one paragraph. It covers what S1 refuses, what it does not end (S2), the Captain authority and token requirement, and C1.
- **Ledger:** run `python scripts/gen_ad_ledger.py` (offline), then `--check`.
- **roadmap.md:** no row. Recent ADs carry none (grep `AD-1340` in `roadmap.md` → 0).
- **#1523:** add these findings. (F-175 and F-176 are new; F-177 is already listed by the effect broker as uncovered.)
  - **F-175:** `config/system.yaml`, which holds `auth.crew_scope_token`, is outside the BF-758 file-read floor (`file_access.py:185-202`).
  - **F-176:** no loopback refusal for `run_command` or `run_python`. The sandbox only sets a blackhole proxy (`isolation.py:648`).
  - **F-177:** direct `browser_tool.invoke` at `agent_actions.py:71` and `reply_pipeline.py:1165` bypasses the registry's permission, LOTO and broker checks. The broker already lists these routes as uncovered (`effect_broker.py:126`). S1 gates the stop only.
- **#1595:** stays open (S2, S3, S4 and C1).

## Acceptance Criteria

1. With a real runtime, one Captain-authenticated order stops one crew agent, and it is still stopped after a restart (X1).
2. Every seam in the inventory refuses new work and names the stop to the sender. The census pins the inventory (I2–I7).
3. No agent-reachable in-process path issues or lifts a stop (I8). Agent fetch and browser tools cannot reach the routes (I9). The C1 residual is stated.
4. The order and the lift are EventLog entries with the Captain as initiator (T9). The ACM history is untouched.
5. With no stop issued, behaviour is unchanged (golden tests in T14, T17, T18 and X1). Zero-config boot is unchanged apart from the new store file.
6. The mutation table is run once with every row killed, one receipted broad gate passes, and CI is green.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-10-19 on `45058ae7`)

```
routers/acm.py:17-34 HR_STATUS_NOTE/_hr_transition_body; :84-124 suspend/reinstate (get_runtime only)
routers/auth.py:41-75 require_crew_scope (pass-through when token empty; 401 otherwise)
routers/identity.py:160-165, routers/security.py:223 — 403 while crew_scope_token unset
config.py:2926-2939 AuthConfig.crew_scope_token default ""
security/url_guard.py:3-16,162-175 validate_public_url refuses loopback (shape, literals without DNS)
security/file_access.py:185-202 protected_read_roots = data_dir only
hooks/bus.py:60,131-135,171-207; startup/communication.py:754-773 (hook bus off by default)
cognitive/dm/reply_pipeline.py:1408-1411 PRE_DISPATCH fire; startup/finalize.py:4761-4766 PRE_TOOL_USE
mesh/intent.py:1057,1133,1293,1593,703-894 (_on_dispatch → queue/handler), :978,:441
mesh/pre_intent_auth.py:93-141; extensions/overlay.py:51,195-247
cognitive/queue.py:351-371 handler then ack; activation/dispatcher.py:135,195-203
agent_onboarding.py:237-242 subscribe(agent.handle_intent); :608-610 unwire_agent
cognitive/cognitive_agent.py:1018 class; 1320 self._runtime = kwargs.get("runtime"); 1653 consultation handler
  registration; 7741-7752 handle_intent; 8435-8439 handle_consultation_request; 15 public coroutines listed in §10
cognitive/consultation.py:37-46,64-74,154,201-226
tools/registry.py:81 class (span 470 to EOF 550); 103-124; 341-467 check_and_invoke (bypass guards :360-372, #1214 :374-384,
  resolve_permission :387, start_permitted_effect :457, tool.invoke :467)
tools/executor.py:486-909 (pre-hooks fail open :679-694; strict path → broker.dispatch :886)
execution/effect_broker.py:68-81 EffectDenied; :457 dispatch; :682-744 EffectDenied → "denied"; :110-134 coverage report
execution/authority.py:109 _REASON_CODE_RE [a-z][a-z0-9_]{0,127} ("agent_stopped" matches)
startup/infrastructure.py:102-111 broker only with protected_execution strict + effect_broker_enabled
cognitive/crew_verifier.py:453-464 _SessionProjectedToolRegistry; :565-605 super().check_and_invoke
proactive.py:31-34 imports; 1002-1039 _run_cycle; 1060 breaker; 1307,1319 handle_intent
ward_room_router.py:16-17,34-80,218-272,575-719 (dispatch_async :693)
startup/finalize.py:5329-5342 WardRoomRouter(...); runtime.py:1059,3466 ward_room_router
routers/agents.py:13,44-46,63,2907-2959,3631-3670 (409 placement before thread/send/pipeline)
routers/thread_fanout.py:60-62,635-653,727,761,940-942 declined shape
routers/agent_actions.py:23-29,36-89 (ack invokes browser_tool directly :71); ActionStatus.ACK_PENDING (action_dispatcher.py:44)
cognitive/turn_promotion.py:2881,2919-2933 promoted-turn resume (S2)
runtime.py:164,517-518,624-634,699-701,2677 start,2745-2763,3251-3254,3298-3299,3454-3459
startup/shutdown.py:1402-1426; storage_declarations.py:206-230; storage/declarations.py:113-140
scripts/check_store_registry.py:10-57; scripts/check_architecture_principles.py:187-188 (500 lines / 15 methods)
docs/development/architecture-baseline.yaml:994-997 ToolRegistry [methods]; :1028 WardRoomRouter [lines, methods]
tests/test_ad1195_eventlog_pair_freeze.py:88-114 _RESOLVED_PAIRS; census rules :1-44,210-305
tests/test_issue1419_failed_start_rollback.py:1127-1204 _STOPPED_COMPONENTS/_ALL_STEPS; :1391-1422 guard census
tests/fixtures/runtime_lifecycle.py:368-372 after_infra fires at init_nats (after Phase 1a)
tests/test_trust_reconcile.py:57-66 booted-runtime pattern; tests/test_ad1002_instructions_api.py:31-41 create_app pattern
__main__.py:2603-2642 RESET_TIERS (explicit lists)
scripts/run_test_gate.py:1097-1129 the eight preflights
```

## Absence Verified (2026-10-19)

| Claim | Search | Result |
|---|---|---|
| No stop symbol exists yet | Grep `\.refusal\(\|active_stop\|agent_stops\|AgentStop` in `src/probos` | 0 hits |
| No test or doc collides with the new names | Grep `agent_stop\|/api/stops\|ad1343` in tests, ui, docs, config | Only `agent.stop()` lifecycle tests (3 files), unrelated |
| No other direct tool invoke | Grep `tool\.invoke\(\|tool\)\.invoke\(` in `src/probos` | Exactly 3 (registry, reply_pipeline, agent_actions) |
| Only two hook-bus fire sites | Grep `hook_bus\.fire\|hb\.fire` | 2 (`reply_pipeline.py:1410`, `finalize.py:4765`) |
| `acm.py` has no events | Grep `event_log\|EventType\|_EVENT =` in `acm.py` | 0 |
| LongRunTicket has no agent id | Grep `agent_id` in `long_runs.py` | 0 |
| No UI or command for suspend | Grep `/suspend\|/reinstate` in `ui/src` | Only the skill-management test |
| No EventType value collides with the new events | Grep `agent_stop\|AGENT_STOP` in `events.py` | 0 |
| Execution code has no loopback refusal for a shell | Grep `curl\|127.0.0.1\|localhost\|Invoke-WebRequest\|system.yaml` in `src/probos/execution` | Only the isolation blackhole proxy (`isolation.py:648`) and the fetch-broker bind |
| No existing test pins the edited lines' old order or text beyond §9 | Grep `getsource(...)` on the edited functions | 6 scans found; the contract keeps their strings and order |

## Prior Art and Blind Spots

- **Prior art:** taken from #1595, drafted 2026-10-18. Kubernetes cordon and drain: S1 is the cordon, S2 the drain. OpenAI Agents SDK guardrails: refuse before dispatch, and name any path outside the gate. Reuse AD-1246, BF-893 and AD-1316 in S2. No new external search: S1 is ProbOS seam plumbing.
- **Reference projects:** considered, deferred to S2. Cancellation semantics have outside analogues (asyncio TaskGroup cancellation, the drain eviction API). No row updates in this pass.
- **Blind spots found here, beyond the issue:**
  - Consultations bypass `handle_intent`.
  - The browser ACK and the DM-pipeline browser step bypass the registry.
  - The correction-session projected registry is a separate instance.
  - The AD-855 promoted-turn resume (scoped to S2).
  - The group fan-out runs the reply pipeline on whatever comes back.
  - `__new__` fixtures.
  - The shutdown step census.
  - The sink depends on the agent's runtime reference (D16).
