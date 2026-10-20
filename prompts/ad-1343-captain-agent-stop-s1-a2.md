## Amendment A2 (2026-10-19): review round 1 (F1–F6); F7 is test-only (scratch Builder)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-19 — against staged tree `fc8b0819`, HEAD `9c80a083`

### Section 11: `src/probos/agent_stop.py`

11.1 module docstring (F5)
<<<<<<< SEARCH
S1 refuses new work. It does not end work already running (S2), stop every agent at
once (S3) or reach external harness sessions (S4); ``S1_SCOPE`` says so in every answer
the Captain receives.
=======
S1 refuses new work. It does not end work already running (S2), stop every agent at
once (S3) or reach external harness sessions (S4); ``S1_SCOPE`` says so in every answer
that reports an order to the Captain.
>>>>>>> REPLACE

11.2 seams (F1)
<<<<<<< SEARCH
SEAM_BROWSER_ACTION: Final = "browser_action_ack"
SEAMS: Final[frozenset[str]] = frozenset({
    SEAM_INTENT, SEAM_CONSULTATION, SEAM_TOOL, SEAM_PROACTIVE, SEAM_WARD_ROOM,
    SEAM_DM_ROUTE, SEAM_GROUP_FANOUT, SEAM_BROWSER_ACTION,
})
=======
SEAM_BROWSER_ACTION: Final = "browser_action_ack"
SEAM_AGENTIC_RUN: Final = "agentic_run"  # A2: the shared entry of every new agentic run, and correction rounds
SEAM_DELEGATION: Final = "delegation"  # A2: a task delegated to a stopped agent
SEAMS: Final[frozenset[str]] = frozenset({
    SEAM_INTENT, SEAM_CONSULTATION, SEAM_TOOL, SEAM_PROACTIVE, SEAM_WARD_ROOM,
    SEAM_DM_ROUTE, SEAM_GROUP_FANOUT, SEAM_BROWSER_ACTION, SEAM_AGENTIC_RUN, SEAM_DELEGATION,
})
>>>>>>> REPLACE

11.3 `S1_SCOPE` (F1, F2)
<<<<<<< SEARCH
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
=======
S1_SCOPE: Final[dict[str, str]] = {
    "refuses": (
        "New work for the agent, wherever it is dispatched: intents (DMs, Ward Room notices, "
        "proactive and duty cycles, work items and the mesh), consultations, group chat turns, "
        "the DM route, tasks delegated to it, crew subtasks (it is not eligible for crew work: a new "
        "subtask goes to an eligible colleague and one already assigned to it is not started), "
        "correction re-runs of its refuted subtasks (escalated unverified instead), browser actions "
        "and every tool call, protected effects included."
    ),
    "does_not_end": (
        "Work already running when the order was given (AD-1343 S2): a turn in progress may "
        "finish and post, though each tool call it makes is refused and a browser action it "
        "proposes is dropped; a crew subtask it is running is not re-invoked for another iteration; "
        "a promoted turn the Captain approves while the agent is stopped resumes, with its tool "
        "calls refused."
    ),
    "not_covered": (
        "Voice and appearance proposals the Captain requests, directly or through the Counselor; "
        "the ship's upkeep of the agent's records (dreams, trust decay); every agent at once "
        "(AD-1343 S3); external harness sessions, which are not_reachable until AD-1342."
    ),
}
>>>>>>> REPLACE

11.4 the final-count statement (F3)
<<<<<<< SEARCH
_LIFT: Final = (
    "UPDATE agent_stops SET lifted_by = ?, lifted_at = ?, lift_reason = ?, refused_json = ? "
    "WHERE stop_id = ? AND lifted_at IS NULL"
)
=======
_LIFT: Final = (
    "UPDATE agent_stops SET lifted_by = ?, lifted_at = ?, lift_reason = ?, refused_json = ? "
    "WHERE stop_id = ? AND lifted_at IS NULL"
)
_FINAL_COUNTS: Final = (
    "UPDATE agent_stops SET refused_json = ? WHERE stop_id = ? AND lifted_at IS NOT NULL"
)
>>>>>>> REPLACE

11.5 rollback helpers (F4)
<<<<<<< SEARCH
def _valid_reason(reason: object) -> str:
    if type(reason) is not str or not reason.strip() or len(reason) > MAX_REASON_CHARS:
        raise ValueError(f"AD-1343: a reason of 1..{MAX_REASON_CHARS} characters is required")
    return reason.strip()
=======
def _valid_reason(reason: object) -> str:
    if type(reason) is not str or not reason.strip() or len(reason) > MAX_REASON_CHARS:
        raise ValueError(f"AD-1343: a reason of 1..{MAX_REASON_CHARS} characters is required")
    return reason.strip()


async def _rollback_quietly(db: "DatabaseConnection") -> None:
    """Undo an uncommitted write so a later commit cannot land it (the AD-1213 pattern)."""
    try:
        await db.execute("ROLLBACK")
    except Exception:  # noqa: BLE001 -- no open transaction is the common case
        logger.debug("AD-1343: rollback after a failed stop write found no open transaction")


async def _commit_or_roll_back(db: "DatabaseConnection", sql: str, params: tuple[Any, ...]) -> None:
    """One statement and its commit; on any failure or cancellation the transaction is rolled back
    (so the next successful commit cannot land it) and the original error is re-raised."""
    try:
        await db.execute(sql, params)
        await db.commit()
    except BaseException:
        await _rollback_quietly(db)
        raise
>>>>>>> REPLACE

11.6 the thread notice (F6)
<<<<<<< SEARCH
    def notice(self, callsign: str) -> str:
        """One line for a thread that addressed the stopped agent."""
        return (
            f"{callsign} is stopped by the Captain's order (stop {self.stop_id}) "
            "and will not reply here until the stop is lifted."
        )
=======
    def notice(self, callsign: str) -> str:
        """One line for a thread that addressed the stopped agent: the order and its start, never the reason."""
        return (
            f"{callsign} is stopped by the Captain's order (stop {self.stop_id}, since {_utc(self.issued_at)}). "
            "New messages here are not delivered to them until the stop is lifted; "
            "a reply already in progress may still post."
        )
>>>>>>> REPLACE

11.7 the run refusal (F1)
<<<<<<< SEARCH
class StopNotFound(LookupError):
    """No Captain's stop is in force for the agent."""
=======
class StopNotFound(LookupError):
    """No Captain's stop is in force for the agent."""


class AgentStopped(RuntimeError):
    """A new agentic run refused for a stopped agent: nothing was started (AD-1343 S1, A2).

    Raised, never returned, so no caller can read the refusal as finished work or store it
    as output; each caller maps it to its own not-started vocabulary. The message names the
    order and its start, never the Captain's reason.
    """

    def __init__(self, record: StopRecord) -> None:
        super().__init__(record.sender_text())
        self.record = record
>>>>>>> REPLACE

11.8 a cancelled issue is honest (F4)
<<<<<<< SEARCH
            record = StopRecord(uuid.uuid4().hex, agent_id, text, CAPTAIN, self._clock())
            self._active[agent_id] = record
            durable = await self._write_issued(record)
            if not durable:
                self._volatile.add(record.stop_id)
=======
            record = StopRecord(uuid.uuid4().hex, agent_id, text, CAPTAIN, self._clock())
            self._active[agent_id] = record
            try:
                durable = await self._write_issued(record)
            except BaseException:  # cancelled mid-write: the order stays in force, honestly marked unwritten
                self._volatile.add(record.stop_id)
                raise
            if not durable:
                self._volatile.add(record.stop_id)
>>>>>>> REPLACE

11.9 the lift (F3, F4)
<<<<<<< SEARCH
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
=======
    async def lift_stop(self, agent_id: str, *, reason: str) -> StopLifted:
        """Lift the Captain's stop on one agent.

        Written before it is applied: if the write fails it is rolled back, the agent stays
        stopped and the error propagates. Work refused while stopped is not replayed. The
        counts returned, sent to the EventLog and kept in the row are final: a seam can count
        under this order until the in-memory lift, so a refusal made while the lift was being
        written is included, and the row is brought up to date when one was. A failure of that
        second write is logged and leaves the lift standing.
        """
        text = _valid_reason(reason)
        async with self._lock:
            record = self.stop_for(agent_id)
            if record is None:
                raise StopNotFound(agent_id)
            lifted_at = self._clock()
            durable = record.stop_id not in self._volatile
            written = self.refused_counts(record.stop_id)
            if durable:
                if self._db is None:
                    raise RuntimeError("AD-1343: the stop store is closed; the stop stays in force")
                await _commit_or_roll_back(
                    self._db, _LIFT, (CAPTAIN, lifted_at, text, json.dumps(written, sort_keys=True), record.stop_id),
                )
            del self._active[agent_id]  # the last moment a seam can count a refusal under this order
            self._volatile.discard(record.stop_id)
            refused = self._refused.pop(record.stop_id, {})
            if durable and refused != written:
                await self._write_final_counts(record, refused)
        await self._record_lifted(record, lifted_at, refused)
        return StopLifted(record, lifted_at, refused)
>>>>>>> REPLACE

11.10 the issue write rolls back (F4)
<<<<<<< SEARCH
        try:
            await self._db.execute(
                _INSERT, (record.stop_id, record.agent_id, record.reason, record.issued_by, record.issued_at),
            )
            await self._db.commit()
        except Exception:
=======
        try:
            await _commit_or_roll_back(
                self._db, _INSERT, (record.stop_id, record.agent_id, record.reason, record.issued_by, record.issued_at),
            )
        except Exception:
>>>>>>> REPLACE

11.11 the final-count write (F3)
<<<<<<< SEARCH
            return False  # log-and-degrade: the stop stays in force
        return True

    async def _record_issued(self, record: StopRecord, durable: bool) -> None:
=======
            return False  # log-and-degrade: the stop stays in force
        return True

    async def _write_final_counts(self, record: StopRecord, refused: dict[str, int]) -> None:
        """Bring a lifted row's refusal counts to their final value; on failure log it (the lift stands)."""
        if self._db is None:  # for the type checker: stop() closes the store only under the lock held here
            return
        try:
            await _commit_or_roll_back(self._db, _FINAL_COUNTS, (json.dumps(refused, sort_keys=True), record.stop_id))
        except Exception:
            logger.error(
                "AD-1343: stop %s for %s is lifted, but its final refusal counts %s were NOT written; "
                "the row keeps the counts at the moment the lift was written",
                record.stop_id, record.agent_id, refused, exc_info=True,
            )

    async def _record_issued(self, record: StopRecord, durable: bool) -> None:
>>>>>>> REPLACE

11.12 the eligibility question and the run entry (F1)
<<<<<<< SEARCH
def tool_refusal(gate: object, agent_id: object, tool_id: str) -> ToolResult | None:
    """The tool sink's refusal for a stopped agent, or None."""
    stopped = active_stop(gate, agent_id, SEAM_TOOL)
    if stopped is None:
        return None
    return ToolResult(
        error=f"Tool {tool_id!r} was not run. {stopped.sender_text()}",
        metadata={STOP_METADATA_KEY: stopped.sender_detail()},
    )
=======
def tool_refusal(gate: object, agent_id: object, tool_id: str) -> ToolResult | None:
    """The tool sink's refusal for a stopped agent, or None."""
    stopped = active_stop(gate, agent_id, SEAM_TOOL)
    if stopped is None:
        return None
    return ToolResult(
        error=f"Tool {tool_id!r} was not run. {stopped.sender_text()}",
        metadata={STOP_METADATA_KEY: stopped.sender_detail()},
    )


def standing_stop(gate: object, agent_id: object) -> StopRecord | None:
    """The order in force for ``agent_id``, or None, WITHOUT counting a refusal (A2).

    For an eligibility question asked about many candidates (crew assignment), where an
    answer refuses no work. The same type guards as ``active_stop``.
    """
    if type(agent_id) is not str or not isinstance(gate, AgentStopService):
        return None
    found = gate.stop_for(agent_id)
    return found if type(found) is StopRecord else None


def refuse_new_run(runtime: object, agent_id: object) -> None:
    """Raise ``AgentStopped`` when ``agent_id`` is stopped: the shared entry of every new agentic run (A2).

    The gate is the one the run's own tool calls are refused by, ``runtime.tool_registry.stop_gate``:
    the ship's runtime and the projected correction runtime (``crew_verifier.py``) both carry it.
    """
    gate = getattr(getattr(runtime, "tool_registry", None), "stop_gate", None)
    stopped = active_stop(gate, agent_id, SEAM_AGENTIC_RUN)
    if stopped is not None:
        raise AgentStopped(stopped)
>>>>>>> REPLACE

### Section 12: `src/probos/routers/agent_stop.py` (F5)

12.1 docstring
<<<<<<< SEARCH
Every answer carries ``scope``: what S1 refuses and what it does not end.
=======
Every answer that reports an order carries ``scope`` (the list, a stop, a stop not written,
a lift): what S1 refuses and what it does not end. A refused request (401, 403, 404, 422,
or 503 for an absent service or a failed lift) carries its code only.
>>>>>>> REPLACE

12.2 the lift answer
<<<<<<< SEARCH
        "refused_while_stopped": lifted.refused,
        "note": LIFT_NOTE,
    }
=======
        "refused_while_stopped": lifted.refused,
        "note": LIFT_NOTE,
        "scope": dict(S1_SCOPE),  # AD-1343 A2 (F5): every answer that reports an order carries scope
    }
>>>>>>> REPLACE

### Section 13: `src/probos/cognitive/agentic_dispatch.py` (F1)

13.1 import
<<<<<<< SEARCH
from probos import work_item_steps as owned_steps
from probos.artifacts.refs import validate_artifact_ref
=======
from probos import work_item_steps as owned_steps
from probos.agent_stop import refuse_new_run  # AD-1343 A2
from probos.artifacts.refs import validate_artifact_ref
>>>>>>> REPLACE

13.2 the run entry
<<<<<<< SEARCH
        inner_loop_hook: Any = None,
    ) -> WorkItemAgenticOutcome:
        """Reserve browser use across offer construction, execution and finalization."""
        if any(value is not None for value in (
=======
        inner_loop_hook: Any = None,
        admitted_turn: bool = False,
    ) -> WorkItemAgenticOutcome:
        """Reserve browser use across offer construction, execution and finalization.

        AD-1343: a stopped agent starts no new run, whoever asks (a delegation, a crew child, a
        correction): ``AgentStopped`` is raised before any validation, browser reservation, context
        or model work. ``admitted_turn=True`` is passed only by the agent's own turn, which the
        intent sink admitted or S2 resumes (pinned by tests/test_ad1343_stop_seam_inventory.py).
        """
        if not admitted_turn:
            refuse_new_run(runtime, agent_id)
        if any(value is not None for value in (
>>>>>>> REPLACE

### Section 14: `src/probos/cognitive/cognitive_agent.py` (F1: the agent's own admitted turns)

14.1 `_run_agentic_dispatch`
<<<<<<< SEARCH
            failure_scope=str(work_item_id or ""),
            **_scope_kwargs,
        )
=======
            failure_scope=str(work_item_id or ""),
            admitted_turn=True,  # AD-1343: a work item the intent sink admitted (handle_intent)
            **_scope_kwargs,
        )
>>>>>>> REPLACE

14.2 `_maybe_run_conversational_agentic._run_pass`
<<<<<<< SEARCH
                    compose_disposition=False,
                    # AD-1248: every pass of THIS turn shares one scope, so a
=======
                    compose_disposition=False,
                    admitted_turn=True,  # AD-1343: this conversational turn was admitted by the intent sink
                    # AD-1248: every pass of THIS turn shares one scope, so a
>>>>>>> REPLACE

14.3 `recover_promoted_turn._recovered_pass`
<<<<<<< SEARCH
                    failure_scope=work_item_id,
                    token_budget=amount,
                    **plan_kwargs,
                )
=======
                    failure_scope=work_item_id,
                    token_budget=amount,
                    admitted_turn=True,  # AD-1343: S2 resumes a promoted turn the Captain approved (S1_SCOPE)
                    **plan_kwargs,
                )
>>>>>>> REPLACE

### Section 15: `src/probos/tools/delegate_task_tool.py` (F1)

15.1 import
<<<<<<< SEARCH
from typing import Any, NoReturn

from probos.tools.delegation_budget import (
=======
from typing import Any, NoReturn

from probos.agent_stop import SEAM_DELEGATION, STOP_REASON_CODE, AgentStopped, StopRecord, active_stop
from probos.tools.delegation_budget import (
>>>>>>> REPLACE

15.2 the not-started answer (module function: outside the class body)
<<<<<<< SEARCH
logger = logging.getLogger(__name__)


class DelegateTaskTool:
=======
logger = logging.getLogger(__name__)


def _stopped_target(record: StopRecord, t0: float) -> DelegatedToolResult:
    """AD-1343: a delegation whose target is stopped by the Captain's order: nothing started, nothing queued."""
    return DelegatedToolResult(
        output={"delegated": False, "reason": STOP_REASON_CODE, "stop": record.sender_detail()},
        duration_ms=(time.monotonic() - t0) * 1000.0,
        evidence=unobserved_delegation_evidence(status="not_started"),
    )


class DelegateTaskTool:
>>>>>>> REPLACE

15.3 the check, before any tree slot, binding or run
<<<<<<< SEARCH
            # Self-guard: an agent must not delegate to itself.
            if target.id == ctx.get("agent_id"):
                return DelegatedToolResult(
                    output={"delegated": False, "reason": "target_not_found"},
                    duration_ms=(time.monotonic() - t0) * 1000.0,
                    evidence=unobserved_delegation_evidence(status="not_started"),
                )

            # AD-1190: admit against the tree budget the root run opened, after
=======
            # Self-guard: an agent must not delegate to itself.
            if target.id == ctx.get("agent_id"):
                return DelegatedToolResult(
                    output={"delegated": False, "reason": "target_not_found"},
                    duration_ms=(time.monotonic() - t0) * 1000.0,
                    evidence=unobserved_delegation_evidence(status="not_started"),
                )

            # AD-1343: a stopped target starts nothing; refused before any tree slot, binding or run.
            stopped = active_stop(getattr(self._runtime, "agent_stops", None), target.id, SEAM_DELEGATION)
            if stopped is not None:
                return _stopped_target(stopped, t0)

            # AD-1190: admit against the tree budget the root run opened, after
>>>>>>> REPLACE

15.4 a stop that lands between the check and the run
<<<<<<< SEARCH
            return DelegatedToolResult(
                output=output,
                duration_ms=(time.monotonic() - t0) * 1000.0,
                evidence=evidence,
            )
        except CorrelatedEffectError as exc:
=======
            return DelegatedToolResult(
                output=output,
                duration_ms=(time.monotonic() - t0) * 1000.0,
                evidence=evidence,
            )
        except AgentStopped as exc:  # AD-1343: the target was stopped after the check above; nothing ran
            return _stopped_target(exc.record, t0)
        except CorrelatedEffectError as exc:
>>>>>>> REPLACE

### Section 16: `src/probos/cognitive/crew_assignment.py` (F1: a stopped agent is not eligible for crew work)

16.1 import
<<<<<<< SEARCH
from probos.cognitive.agentic_dispatch import (
    AgenticIdentity,
=======
from probos.agent_stop import standing_stop
from probos.cognitive.agentic_dispatch import (
    AgenticIdentity,
>>>>>>> REPLACE

16.2 type-only import
<<<<<<< SEARCH
if TYPE_CHECKING:
    from probos.mesh.capability import CapabilityMatch, CapabilityRegistry
=======
if TYPE_CHECKING:
    from probos.agent_stop import AgentStopService
    from probos.mesh.capability import CapabilityMatch, CapabilityRegistry
>>>>>>> REPLACE

16.3 the reason
<<<<<<< SEARCH
    reason: Literal["eligible", "missing", "inactive", "unresolved_identity"]
=======
    reason: Literal["eligible", "missing", "inactive", "unresolved_identity", "stopped"]
>>>>>>> REPLACE

16.4 constructor injection
<<<<<<< SEARCH
        agent_registry: CrewAssignmentRegistry,
    ) -> None:
        self._capability_registry = capability_registry
        self._ontology = ontology
        self._trust_network = trust_network
        self._agent_registry = agent_registry
=======
        agent_registry: CrewAssignmentRegistry,
        agent_stops: "AgentStopService | None" = None,
    ) -> None:
        self._capability_registry = capability_registry
        self._ontology = ontology
        self._trust_network = trust_network
        self._agent_registry = agent_registry
        self._agent_stops = agent_stops  # AD-1343: a stopped agent is not eligible for crew work
>>>>>>> REPLACE

16.5 the check, before any lookup
<<<<<<< SEARCH
        if type(agent_id) is not str or not agent_id:
            return CrewWorkerEligibility(None, "unresolved_identity")
        try:
            agent = self._agent_registry.get(agent_id)
=======
        if type(agent_id) is not str or not agent_id:
            return CrewWorkerEligibility(None, "unresolved_identity")
        # AD-1343: an agent stopped by the Captain's order is not eligible: it is never assigned,
        # and a subtask already assigned to it is not started (CrewWorkerUnavailable, the existing
        # lost-eligibility outcome). Memory only and not counted: asking about a candidate refuses no work.
        if standing_stop(self._agent_stops, agent_id) is not None:
            return CrewWorkerEligibility(None, "stopped")
        try:
            agent = self._agent_registry.get(agent_id)
>>>>>>> REPLACE

### Section 17: `src/probos/startup/finalize.py` (F1 wiring)

17.1
<<<<<<< SEARCH
    assignment_resolver = CrewAssignmentResolver(
        capability_registry=capability_registry,
        ontology=ontology,
        trust_network=trust_network,
        agent_registry=registry,
    )
=======
    assignment_resolver = CrewAssignmentResolver(
        capability_registry=capability_registry,
        ontology=ontology,
        trust_network=trust_network,
        agent_registry=registry,
        agent_stops=getattr(runtime, "agent_stops", None),  # AD-1343: a stopped agent is not eligible for crew work
    )
>>>>>>> REPLACE

### Section 18: `src/probos/cognitive/crew_verifier.py` (F1: corrections)

18.1 import
<<<<<<< SEARCH
from probos import work_item_steps as owned_steps
from probos.cognitive.crew_verdict import (
=======
from probos import work_item_steps as owned_steps
from probos.agent_stop import SEAM_AGENTIC_RUN, AgentStopped, active_stop
from probos.cognitive.crew_verdict import (
>>>>>>> REPLACE

18.2 legacy: check each round before admission
<<<<<<< SEARCH
        while rounds < self._max_rounds:
            rounds += 1
            critiqued_task = f"{task_text}\n\nCRITIQUE:\n{verdict.critique}"
=======
        while rounds < self._max_rounds:
            # AD-1343: a stopped producer is not re-run; its refuted result escalates unverified below.
            if active_stop(getattr(self._runtime, "agent_stops", None), result.agent_id, SEAM_AGENTIC_RUN) is not None:
                break
            rounds += 1
            critiqued_task = f"{task_text}\n\nCRITIQUE:\n{verdict.critique}"
>>>>>>> REPLACE

18.3 legacy: a stop that lands after the check
<<<<<<< SEARCH
            except owned_steps.OwnedStepsError:
                raise
            except Exception:
                logger.warning(
                    "AD-860: convergence re-run failed for sub-task %s "
=======
            except AgentStopped:
                break  # AD-1343: stopped after the check above; nothing ran, nothing is re-verified
            except owned_steps.OwnedStepsError:
                raise
            except Exception:
                logger.warning(
                    "AD-860: convergence re-run failed for sub-task %s "
>>>>>>> REPLACE

18.4 session: check each attempt before admission
<<<<<<< SEARCH
        for attempt_index in range(1, max_rounds + 1):
            critiqued_task = (
                f"{normalized_task}\n\nCRITIQUE:\n{verdict.critique}"
            )
=======
        for attempt_index in range(1, max_rounds + 1):
            # AD-1343: a stopped producer is not re-run; checked before a correction is admitted.
            if active_stop(getattr(self._runtime, "agent_stops", None), current.agent_id, SEAM_AGENTIC_RUN) is not None:
                return self._producer_stopped_outcome(current, history)
            critiqued_task = (
                f"{normalized_task}\n\nCRITIQUE:\n{verdict.critique}"
            )
>>>>>>> REPLACE

18.5 session: a stop that lands after the check
<<<<<<< SEARCH
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "Session correction failed for child %s on attempt %d; "
=======
            except asyncio.CancelledError:
                raise
            except AgentStopped:
                return self._producer_stopped_outcome(current, history)  # AD-1343: stopped after the check above
            except Exception:
                logger.warning(
                    "Session correction failed for child %s on attempt %d; "
>>>>>>> REPLACE

18.6 the terminal
<<<<<<< SEARCH
        return self._session_terminal_outcome(
            current,
            status="unverified",
            rounds_used=max_rounds,
            failure_code="convergence_exhausted",
            history=history,
            terminal_attempt=None,
        )

    # ------------------------------------------------------------------ internals
=======
        return self._session_terminal_outcome(
            current,
            status="unverified",
            rounds_used=max_rounds,
            failure_code="convergence_exhausted",
            history=history,
            terminal_attempt=None,
        )

    @staticmethod
    def _producer_stopped_outcome(
        result: "SubtaskResult", history: list[SessionVerificationRound],
    ) -> SessionConvergenceOutcome:
        """AD-1343: a refuted child whose producer is stopped by the Captain's order is not corrected.

        No correction was admitted or run. It ends as exhaustion does (``unverified``, no terminal
        attempt) with the rounds actually used, so the finalizer's ``rounds_used == len(rounds) - 1``
        holds and nothing reads the stop as a producer or execution fault.
        """
        return SubtaskVerifier._session_terminal_outcome(
            result,
            status="unverified",
            rounds_used=len(history) - 1,
            failure_code="convergence_exhausted",
            history=history,
            terminal_attempt=None,
        )

    # ------------------------------------------------------------------ internals
>>>>>>> REPLACE

### Section 19: `src/probos/cognitive/dm/reply_pipeline.py` (F2)

19.1
<<<<<<< SEARCH
        envelopes = parse_action_envelopes(self.ctx.response_text)
        if not envelopes:
            return

        # Enforce per-DM-turn cap; extra envelopes dropped + logged.
=======
        envelopes = parse_action_envelopes(self.ctx.response_text)
        if not envelopes:
            return

        # AD-1343: a stopped agent proposes and runs no browser action, even in a turn admitted
        # before the order (this inline tier-1 call bypasses the tool sink, #1523 F-177): the
        # markers are stripped as for an unwired dispatcher, and the refusal counts as a tool call.
        from probos.agent_stop import SEAM_TOOL, active_stop

        if active_stop(getattr(self.ctx.runtime, "agent_stops", None), self.ctx.agent_id, SEAM_TOOL) is not None:
            self.ctx.response_text = strip_action_markers(self.ctx.response_text)
            return

        # Enforce per-DM-turn cap; extra envelopes dropped + logged.
>>>>>>> REPLACE

### Section 20: existing tests (each change carries an inline reason; none deleted)

20.1 `tests/test_ad1343_agent_stop.py` T8
<<<<<<< SEARCH
    assert SEAMS == frozenset({
        "intent", "consultation", "tool", "proactive", "ward_room", "dm_route", "group_fanout", "browser_action_ack",
    })  # the seam names the Captain reads in every answer
=======
    assert SEAMS == frozenset({
        "intent", "consultation", "tool", "proactive", "ward_room", "dm_route", "group_fanout", "browser_action_ack",
        "agentic_run", "delegation",  # A2 (F1): the run entry and correction rounds; a delegated task
    })  # the seam names the Captain reads in every answer
>>>>>>> REPLACE

20.2 `tests/test_ad1343_agent_stop.py` T17
<<<<<<< SEARCH
        assert post["body"].startswith("[System] ") and CALLSIGN in post["body"] and record.stop_id in post["body"]
        assert PRIVATE_FRAGMENT not in post["body"]  # the thread learns of the order, never the reason
=======
        assert post["body"].startswith("[System] ") and CALLSIGN in post["body"] and record.stop_id in post["body"]
        assert PRIVATE_FRAGMENT not in post["body"]  # the thread learns of the order, never the reason
        assert record.sender_detail()["since"] in post["body"]  # A2 (F6): when the order began, as senders are promised
        assert "will not reply" not in post["body"] and "may still post" in post["body"]  # A2 (F6): S2 lets a running turn post
>>>>>>> REPLACE

20.3 `tests/test_ad1343_agent_stop.py` T24
<<<<<<< SEARCH
    assert body["note"] == LIFT_NOTE and isinstance(body["lifted_at"], float)
=======
    assert body["note"] == LIFT_NOTE and isinstance(body["lifted_at"], float)
    assert body["scope"] == S1_SCOPE  # A2 (F5): an answer that reports an order carries scope
>>>>>>> REPLACE

20.4 `tests/test_ad1155_loop_until_done.py`
<<<<<<< SEARCH
        "inner_loop_hook",  # AD-1322: optional economic-organ hook only
    ]
=======
        "inner_loop_hook",  # AD-1322: optional economic-organ hook only
        "admitted_turn",  # AD-1343 A2: the agent's own admitted turn skips the stop entry check; not continuation policy
    ]
>>>>>>> REPLACE

### Section 21: `tests/test_ad1343_stop_seam_inventory.py` (I10–I13)

21.1 docstring
<<<<<<< SEARCH
4. ORDER: each sink consults the stop first; each source check precedes the work it guards.
5. REACH: only the Captain's routes issue or lift a stop; the URL floor refuses its routes.
=======
4. ORDER: each sink consults the stop first; each source check precedes the work it guards.
5. REACH: only the Captain's routes issue or lift a stop; the URL floor refuses its routes.
6. RUNS (A2): every construction of ``WorkItemAgenticExecutor``, by enclosing function; the run entry
   refuses first; only the agent's own admitted turns pass ``admitted_turn``.
7. CREW (A2): crew eligibility consults the stop before any lookup, and its one construction is wired.
>>>>>>> REPLACE

21.2 recorded callees
<<<<<<< SEARCH
_STOP_CALLEES = frozenset({"active_stop", "tool_refusal", "refusal"})
_RECORDED = _STOP_CALLEES | {"invoke", "issue_stop", "lift_stop"}
=======
_STOP_CALLEES = frozenset({"active_stop", "tool_refusal", "refusal", "refuse_new_run"})
_RECORDED = _STOP_CALLEES | {
    "invoke", "issue_stop", "lift_stop", "standing_stop", "WorkItemAgenticExecutor", "CrewAssignmentResolver",
}
_PINNED_KEYWORDS = frozenset({"admitted_turn", "agent_stops"})  # recorded as "name=value" on any call passing one
>>>>>>> REPLACE

21.3 the stop checks (new entries in order)
<<<<<<< SEARCH
    ("src/probos/routers/agent_actions.py", "ack_action", "active_stop"): "SEAM_BROWSER_ACTION",
}
=======
    ("src/probos/routers/agent_actions.py", "ack_action", "active_stop"): "SEAM_BROWSER_ACTION",
    ("src/probos/cognitive/agentic_dispatch.py", "WorkItemAgenticExecutor.run", "refuse_new_run"): "SEAM_AGENTIC_RUN",
    ("src/probos/tools/delegate_task_tool.py", "DelegateTaskTool.invoke", "active_stop"): "SEAM_DELEGATION",
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge_for_session", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", "active_stop"): "SEAM_TOOL",
}
>>>>>>> REPLACE

21.4 the inline browser action is reclassified (F2)
<<<<<<< SEARCH
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", "browser_tool"):
        "runs only in a DM or group turn whose route checked the stop; plan-mode projection runs no step",
=======
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", "browser_tool"):
        "after its own stop check at SEAM_TOOL (A2, F2): a turn admitted before the order proposes and runs no action",
>>>>>>> REPLACE

21.5 order, and the new tables
<<<<<<< SEARCH
    ("src/probos/routers/agent_actions.py", "ack_action", ("invoke", "mark_executed", "mark_failed")),
)
=======
    ("src/probos/routers/agent_actions.py", "ack_action", ("invoke", "mark_executed", "mark_failed")),
    ("src/probos/tools/delegate_task_tool.py", "DelegateTaskTool.invoke", ("admit", "bind_delegated_run", "WorkItemAgenticExecutor")),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge", ("admit_correction", "run")),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge_for_session", ("admit_correction", "run")),
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", ("register", "invoke")),
)

# A2: every place a WorkItemAgenticExecutor is built, and how a stopped agent is refused there.
_AGENTIC_RUN_OWNERS: dict[tuple[str, str], str] = {
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent._run_agentic_dispatch"): "admitted turn (handle_intent)",
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent._maybe_run_conversational_agentic"): "admitted turn",
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.recover_promoted_turn"): "S2 promoted resume",
    ("src/probos/tools/delegate_task_tool.py", "DelegateTaskTool.invoke"): "SEAM_DELEGATION, then the run entry",
    ("src/probos/startup/finalize.py", "_wire_crew_orchestrator"): "crew eligibility, correction rounds, the run entry",
}
_ADMITTED_TURN_SITES: frozenset[tuple[str, str, str]] = frozenset({
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent._run_agentic_dispatch", "admitted_turn=True"),
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent._maybe_run_conversational_agentic._run_pass", "admitted_turn=True"),
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.recover_promoted_turn._recovered_pass", "admitted_turn=True"),
})
>>>>>>> REPLACE

21.6 the record carries pinned keywords
<<<<<<< SEARCH
    receiver: str
    seam: str


class _Visitor(ast.NodeVisitor):
=======
    receiver: str
    seam: str
    keywords: tuple[str, ...] = ()


class _Visitor(ast.NodeVisitor):
>>>>>>> REPLACE

21.7 the visitor
<<<<<<< SEARCH
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
=======
        keywords = tuple(f"{k.arg}={ast.unparse(k.value)}" for k in node.keywords if k.arg in _PINNED_KEYWORDS)
        if callee in _RECORDED or keywords:
            seam = ""
            if callee == "refusal" and len(node.args) >= 2:
                seam = ast.unparse(node.args[1])
            elif callee == "active_stop" and len(node.args) >= 3:
                seam = ast.unparse(node.args[2])
            elif callee == "tool_refusal":
                seam = "SEAM_TOOL"
            elif callee == "refuse_new_run":
                seam = "SEAM_AGENTIC_RUN"
            self.calls.append(_Call(self._rel, ".".join(self._scope) or "<module>", callee, receiver, seam, keywords))
        self.generic_visit(node)
>>>>>>> REPLACE

21.8 the new census tests (I10–I13)
<<<<<<< SEARCH
def test_agent_fetch_and_browser_tools_cannot_reach_the_stop_routes() -> None:
    for url in ("http://127.0.0.1:18900/api/stops/counselor_0", "http://[::1]:18900/api/stops/counselor_0/lift"):
        assert validate_public_url(url) is not None, url
=======
def test_agent_fetch_and_browser_tools_cannot_reach_the_stop_routes() -> None:
    for url in ("http://127.0.0.1:18900/api/stops/counselor_0", "http://[::1]:18900/api/stops/counselor_0/lift"):
        assert validate_public_url(url) is not None, url


def test_every_agentic_run_is_built_by_a_classified_owner() -> None:
    found = {(c.file, c.function) for c in _census() if c.callee == "WorkItemAgenticExecutor"}
    assert found == set(_AGENTIC_RUN_OWNERS), sorted(found ^ set(_AGENTIC_RUN_OWNERS))


def test_the_run_entry_refuses_before_anything_else() -> None:
    body = _function("src/probos/cognitive/agentic_dispatch.py", "WorkItemAgenticExecutor.run").body
    index = next(i for i, stmt in enumerate(body) if any(_calls("refuse_new_run")(n) for n in ast.walk(stmt)))
    assert index == 1, index  # after the docstring: before owned-steps validation, the browser reservation and the run
    assert not any(isinstance(n, ast.Await) for stmt in body[:index] for n in ast.walk(stmt))


def test_only_the_agents_own_turns_pass_admitted_turn() -> None:
    found = {(c.file, c.function, k) for c in _census() for k in c.keywords if k.startswith("admitted_turn=")}
    assert found == _ADMITTED_TURN_SITES, sorted(found ^ _ADMITTED_TURN_SITES)


def test_crew_eligibility_consults_the_stop_first_and_is_wired() -> None:
    check = _function("src/probos/cognitive/crew_assignment.py", "CrewAssignmentResolver.check_eligibility")

    def registry_get(node: ast.AST) -> bool:
        return isinstance(node, ast.Call) and ast.unparse(node.func) == "self._agent_registry.get"

    assert _first_line(check, _calls("standing_stop")) < _first_line(check, registry_get)
    built = {(c.file, c.function, c.keywords) for c in _census() if c.callee == "CrewAssignmentResolver"}
    assert built == {(
        "src/probos/startup/finalize.py", "_wire_crew_orchestrator", ("agent_stops=getattr(runtime, 'agent_stops', None)",),
    )}, built
>>>>>>> REPLACE

### Tests (A2)

New unit tests go in **`tests/test_ad1343_agent_stop_runs.py`** (new file; import `_service`, `_Clock`, `_FlakyFactory`, `REASON`, `LIFT_REASON`, `PRIVATE_FRAGMENT`, `AGENT`, `OTHER` from `tests.test_ad1343_agent_stop`). New crossing tests go in **`tests/test_ad1343_stop_crossing_runs.py`** (new file). Two new files avoid conflicts with the scratch Builder's F7 edits.

Goldens use `caplog.at_level(logging.INFO)` and assert **no record at INFO or above** from `probos.agent_stop` and from the changed module's logger on the unstopped path. Such a golden fails if INFO logging is added there.

| # | Test | Must show |
|---|---|---|
| T27 | `test_a_refusal_made_while_the_lift_is_written_is_kept_in_the_answer_the_event_and_the_row` | A test-local connection that pauses `commit` after the `UPDATE agent_stops SET lifted_by` statement, until the test releases it. Run `lift_stop` as a task. While it is paused, `refusal(AGENT, SEAM_TOOL)` returns the record (still stopped). After release: `StopLifted.refused == {"tool": 1}`; the real EventLog lifted row's `data["refused"] == {"tool": 1}`; the stdlib-read row's `refused_json == '{"tool": 1}'`. **Golden:** no refusal during the write gives exactly one UPDATE statement and the row equals the lift-time counts. |
| T28 | `test_a_failed_final_count_write_leaves_the_lift_standing_and_is_logged` | Same pause, plus `_FlakyFactory("UPDATE agent_stops SET refused_json")`: the lift returns `{"tool": 1}`; `stop_for(AGENT) is None`; one ERROR from `probos.agent_stop` names the stop id and not `PRIVATE_FRAGMENT`; the row keeps `{}`; a restart is not stopped. |
| T29 | `test_a_failed_or_cancelled_commit_is_rolled_back_on_issue_and_lift` | A connection whose `commit` raises a simulated error once, after the INSERT or UPDATE has executed (a transaction is open). (a) **Issue:** `durable=False`. Then issuing for `OTHER` succeeds. Restart: AGENT not stopped, OTHER stopped. (b) **Lift:** raises the original error (`match="simulated"`) and the agent stays stopped. Then a successful issue for OTHER. Restart: AGENT still stopped, `lifted_at` is NULL. (c) **Cancel:** cancel the lift task during the paused commit. `CancelledError` propagates, the counts are intact, and after another successful write and a restart AGENT is still stopped. (d) **Cancel issue:** cancel during the INSERT commit; issuing again gives `already_stopped=True, durable=False`. |
| T30 | `test_the_run_entry_refuses_a_stopped_agent_before_any_work` | A real `WorkItemAgenticExecutor(llm_client=<counting client>)`. The runtime is a `SimpleNamespace` whose `tool_registry` is a real `ToolRegistry` with `set_stop_gate(service)`, and which has NO `agent_stops` attribute (so the projected-runtime source is proved). Stopped: `AgentStopped` is raised; `exc.record.stop_id` matches; `str(exc)` names the stop and not `PRIVATE_FRAGMENT`; the LLM was called 0 times; a spy `_run_reserved` was not reached; a spy owned-steps port's `validate` was not called; `refused_counts == {"agentic_run": 1}`. With `admitted_turn=True`: `_run_reserved` is reached. **Golden** (empty service): `_run_reserved` receives exactly the dict it receives with no gate, and no INFO+ logs. |
| T31 | `test_a_delegation_to_a_stopped_target_is_refused_not_started` | `DelegateTaskTool` built with the `tests/test_ad1072_agentic_tools.py` callsign-registry helper and `runtime.agent_stops = service`. Stopped target: `output == {"delegated": False, "reason": "agent_stopped", "stop": record.sender_detail()}`; `evidence.status == "not_started"`; a tree budget's slot count is unchanged; a spy `effect_broker.bind_delegated_run` was not called; a monkeypatched `WorkItemAgenticExecutor` was not constructed; no `PRIVATE_FRAGMENT` anywhere in the output. **Race:** the stop is issued inside the spy `bind_delegated_run`, so the real run entry raises; the result is the same not-started shape with `error is None`, and no WARNING `delegation failed`. **Golden** (empty service): delegated True with the stub outcome, no INFO+ logs. |
| T32 | `test_a_stopped_agent_is_not_eligible_for_crew_work` | Reuse the `native_workers` fixture shape from `tests/test_ad859_crew_executor.py:225-266` with `CrewAssignmentResolver(..., agent_stops=service)`. Stop builder-1 (highest trust): `check_eligibility("builder-1") == CrewWorkerEligibility(None, "stopped")`; `resolve(spec capability="analysis")` picks builder-2; `refused_counts == {}` (not counted). **Golden** (empty service): every agent is `"eligible"` and `resolve` picks builder-1. |
| T33 | `test_a_stopped_producer_is_not_re_run_for_correction` | A refuted result whose producer is stopped, set up as `tests/test_ad860_crew_verifier.py` (legacy) and `tests/test_ad1126_verified_finalization.py` (session) build them. Legacy: `ConvergenceOutcome.status == "unverified"`, `rounds == 0`, the executor's `run` is never called, `verify` is called once. Session: `status == "unverified"`, `failure_code == "convergence_exhausted"`, `terminal_attempt is None`, `rounds_used == len(history) - 1`; `admit_correction` is not called (owned variant); and the finalizer's `ChildVerificationRecord` built from it validates. **Race** (an executor whose `run` raises `AgentStopped`): legacy does no second `verify`; session ends `unverified`, never `failed` / `correction_execution_defect`. |
| T34 | `test_a_stopped_agents_browser_action_is_neither_registered_nor_run` | A `DmReplyPipeline` context as the AD-745 tests build it (action dispatch enabled, recording dispatcher, recording browser tool, tier-1 classification). Stopped: the browser tool is not invoked; `dispatcher.register` is not called; `ctx.response_text` has no action markers; `refused_counts == {"tool": 1}`. **Golden** (empty service): invoked once, registered once, no INFO+ from `probos.agent_stop`. |
| X4 | `test_a_delegation_to_a_stopped_crew_member_starts_nothing_on_a_real_ship` | Boot as in `test_ad1343_stop_crossing.py:43-54`. Register `DelegateTaskTool(runtime=rt, llm_client=<counting MockLLM>, max_depth=1, max_iterations=2)` on `rt.tool_registry` when `get("delegate_task") is None`. Call `rt.tool_registry.check_and_invoke(colleague.id, "delegate_task", {"task": "...", "to": <target callsign>}, ...)`, with the permission the reviewer's probe used. **Golden before the order:** `delegated True`. After `rt.agent_stops.issue_stop(target.id, ...)`: `delegated False`, `reason == "agent_stopped"`, `stop.stop_id` matches, and the counting LLM's calls for the nested run are 0. If the real registry denies permission for the colleague, **stop and report**; do not fake the registry. |
| X5 | `test_a_crew_child_of_a_stopped_agent_is_not_started` | The `test_ad859_crew_executor.py:269-302` shape with the real resolver from T32, a real `WorkItemAgenticExecutor(llm_client=<counting>)` and a stopped builder-1: `executor.run(parent.id)` raises `CrewWorkerUnavailable("crew_worker_unavailable")`; the child is untouched (`is_untouched_crew_child`, metadata unchanged); 0 LLM calls; nothing is persisted as `failed`. **Golden:** with no order, the eligibility premise holds (`:281`). |

Census: I10 `test_every_agentic_run_is_built_by_a_classified_owner`, I11 `test_the_run_entry_refuses_before_anything_else`, I12 `test_only_the_agents_own_turns_pass_admitted_turn`, I13 `test_crew_eligibility_consults_the_stop_first_and_is_wired`. The existing I2, I3 and I7 pick up the new entries.

**Existing tests that change (all listed above):** `test_ad1343_agent_stop.py` T8, T17 and T24; `test_ad1343_stop_seam_inventory.py` (§21); `test_ad1155_loop_until_done.py:538-543`.

**Checked, need no change:**
- `test_ad859` and `test_ad864` build resolvers without `agent_stops` (default `None`).
- `WorkItemAgenticExecutor` fakes in `test_ad1065`, `bf698`, `ad1165`, `ad1208`, `ad1324` and `bf887` take `**kwargs`.
- `test_ad1142:508` and `test_ad1180:410` check single parameters.
- No test pins `S1_SCOPE` text; they compare to the constant.

**Focused gate:**
`pytest tests/test_ad1343_*.py tests/test_ad859_crew_executor.py tests/test_ad864_crew_assignment.py tests/test_ad860_crew_verifier.py tests/test_ad1126_verified_finalization.py tests/test_ad1072_agentic_tools.py tests/test_ad1190_delegation_tree_budget.py tests/test_ad1155_loop_until_done.py tests/test_ad1239*.py tests/test_bf887_continue_resumes_the_promoted_turn.py tests/test_ad933_group_chat_escalation.py tests/test_ad1195_eventlog_pair_freeze.py -n 0`

Then the eight preflights; `check_architecture_principles.py --check` must report srp-size 92 and `DelegateTaskTool` must be at most 500 lines.

### Mutation rows (A2; whole stripped lines, unique per file)

| ID | File: anchor → mutant | Killed by |
|---|---|---|
| R7′ | agent_stop.py `self._db, _LIFT, (CAPTAIN, lifted_at, text, json.dumps(written, sort_keys=True), record.stop_id),` → `record.stop_id` replaced by `None` | T1 |
| R8′ | agent_stop.py `del self._active[agent_id]  # the last moment a seam can count a refusal under this order` → `pass` | T24, X1 |
| A1 | agent_stop.py `refused = self._refused.pop(record.stop_id, {})` → `refused = written` | T27 |
| A2 | agent_stop.py `if durable and refused != written:` → `if False:` | T27 (row) |
| A3 | agent_stop.py `await _rollback_quietly(db)` → `pass` | T29 (a), (b) |
| A4 | agent_stop.py `except BaseException:` → `except Exception:` | T29 (c) |
| A5 | agent_stop.py `except BaseException:  # cancelled mid-write: the order stays in force, honestly marked unwritten` → `except Exception:  # A5` | T29 (d) |
| A6 | agent_stop.py `f"{callsign} is stopped by the Captain's order (stop {self.stop_id}, since {_utc(self.issued_at)}). "` → without `, since …` | T17 |
| A7 | agent_stop.py `gate = getattr(getattr(runtime, "tool_registry", None), "stop_gate", None)` → `gate = getattr(runtime, "agent_stops", None)` | T30 |
| A8 | agent_stop.py `raise AgentStopped(stopped)` → `pass` | T30, T31 race, T33 race |
| A9 | agent_stop.py `if type(agent_id) is not str or not isinstance(gate, AgentStopService):` → `if False:` | `test_ad859_crew_executor.py` (a `None` gate) |
| A10 | agentic_dispatch.py `if not admitted_turn:` → `if False:` | T30 |
| A11 | agentic_dispatch.py `refuse_new_run(runtime, agent_id)` → `pass` | T30, I11 |
| A12 | delegate_task_tool.py `stopped = active_stop(getattr(self._runtime, "agent_stops", None), target.id, SEAM_DELEGATION)` → `stopped = None` | T31 (slot, binding) |
| A13 | delegate_task_tool.py `return _stopped_target(exc.record, t0)` → `raise` | T31 race |
| A14 | crew_assignment.py `if standing_stop(self._agent_stops, agent_id) is not None:` → `if False:` | T32, X5 |
| A15 | crew_assignment.py `self._agent_stops = agent_stops  # AD-1343: a stopped agent is not eligible for crew work` → `self._agent_stops = None` | T32, X5 |
| A16 | crew_verifier.py `if active_stop(getattr(self._runtime, "agent_stops", None), result.agent_id, SEAM_AGENTIC_RUN) is not None:` → `if False:` | T33 legacy (run not called) |
| A17 | crew_verifier.py `break  # AD-1343: stopped after the check above; nothing ran, nothing is re-verified` → `pass` | T33 legacy race |
| A18 | crew_verifier.py `if active_stop(getattr(self._runtime, "agent_stops", None), current.agent_id, SEAM_AGENTIC_RUN) is not None:` → `if False:` | T33 session (`admit_correction` not called) |
| A19 | crew_verifier.py `return self._producer_stopped_outcome(current, history)  # AD-1343: stopped after the check above` → `raise` | T33 session race |
| A20 | crew_verifier.py `rounds_used=len(history) - 1,` → `rounds_used=len(history),` | T33 session (finalizer record) |
| A21 | reply_pipeline.py `if active_stop(getattr(self.ctx.runtime, "agent_stops", None), self.ctx.agent_id, SEAM_TOOL) is not None:` → `if False:` | T34 |
| A22 | routers/agent_stop.py `"scope": dict(S1_SCOPE),  # AD-1343 A2 (F5): every answer that reports an order carries scope` → removed | T24 |
| HA1 | finalize.py `agent_stops=getattr(runtime, "agent_stops", None),  # AD-1343: a stopped agent is not eligible for crew work` → removed (HAND, wiring) | I13 |
| HA2 | cognitive_agent.py, each `admitted_turn=True,  # AD-1343: …` line → removed (HAND, three rows) | I12 |
| HA3 | agent_stop.py `_write_final_counts`'s `except Exception:` body → `raise` (HAND: log-and-degrade) | T28 |
| HA4 | agent_stop.py `_rollback_quietly`'s `except Exception:` body → `raise` (HAND) | T29 (b): the original error must surface (`match="simulated"`) |

**Campaign of record:** rerun every R/H row whose file A2 changes — agent_stop.py (R1–R17, H7), routers/agent_stop.py (R31–R37), crew_verifier.py (R20), cognitive_agent.py (R21–R23) — then the A rows. All other rows stand.

### Diff Reviewer: properties to verify (delta)

- **P3 (amended):** with no stop, the run entry, delegation, crew eligibility, correction rounds, the inline action and the lift return exactly what they did before, with no new INFO+ line. The only intended difference is that the lift answer gains `scope`.
- **P8 (replaced):** every answer that reports an order carries `scope`; a refused request carries its code only. Nothing claims running work was ended.
- **P12:** every new agentic run for a stopped agent is refused before owned-steps validation, the browser reservation, context or model work. Only the three pinned sites of the agent's own turns pass `admitted_turn=True`.
- **P13:** `AgentStopped` never surfaces as a fault, retry, breaker trip or trust write:
  - delegation → `not_started`, with no tree slot and no broker binding;
  - crew → not eligible, so the existing `CrewWorkerUnavailable` / lost-eligibility outcomes;
  - correction → the existing `unverified` escalation, with no admitted correction.
  No durable crew vocabulary changes.
- **P14:** the lift's counts are final at the in-memory lift; a second write happens only when they changed, and its failure leaves the lift standing. Both write paths roll back on failure or cancellation and re-raise the original error. A cancelled issue is marked not durable.
- **P15:** a stopped agent's action envelopes are stripped; nothing is registered or invoked; it counts as one `tool` refusal.
- **P9 (extended):** `DelegateTaskTool` stays at most 500 lines; `CrewAssignmentResolver` gains no method; srp-size stays at 92.

### Decisions

| # | Decision | Rejected | Envelope |
|---|---|---|---|
| D19 | One run entry: `refuse_new_run` is the first statement of `WorkItemAgenticExecutor.run`; it raises `AgentStopped`; the gate is `runtime.tool_registry.stop_gate`; the agent's own turns opt out with `admitted_turn=True`, census-pinned | A returned outcome (written as output, or read as failure); per-caller checks only (they decay — the AD-1180 lesson); `runtime.agent_stops` (missing on the correction projection) | Architect |
| D20 | Delegation is checked before tree admission and binding, with the existing not-started shape; `SEAMS` gains `agentic_run` and `delegation` | Mapping it to `delegation_failed` (a fault) | Architect |
| D21 | Crew: a stop makes the agent not eligible (`"stopped"`, memory only, not counted), reusing lost-eligibility outcomes; a child already running is S2 (`crew_worker_identity_lost` on its next iteration) | A new `agent_stopped` crew reason (a closed durable vocabulary in three modules; breaks downgrade) | Architect; S2 owns a dedicated label |
| D22 | Corrections are checked at the top of each round, before admission; legacy breaks to unverified, session uses the exhaustion terminal with the true `rounds_used` | `correction_capability_denied` (finalizer needs `denied_tools`); `correction_execution_defect` (a fault) | Architect |
| D23 | F2: stopped → envelopes stripped, counted at `SEAM_TOOL` | Routing the call through the registry (F-177, separate) | Architect |
| D24 | F3: counts are final at the in-memory lift; a second write only when they changed; its failure is logged ERROR | Applying before writing (unsafe if the write fails) | Architect |
| D25 | F4: rollback via `execute("ROLLBACK")` on both paths (AD-1213 pattern); a cancelled issue is not durable | Recording on #1523 (the code is already being touched); a new `rollback()` on `DatabaseConnection` (protocol change) | Architect |
| D26 | F5 wording: answers that report an order carry `scope` | `scope` on 4xx bodies | Architect |
| D27 | F6 notice text (start time; S2-true) | — | Architect |
| D28 | `S1_SCOPE` reworded (delegation, crew, corrections, inline actions, the Counselor route) | — | Architect |

### Verified Against Codebase (2026-10-19, staged tree `fc8b0819`)

- `agentic_dispatch.py:2591-2662` — `run`: first statement 2614, browser reservation 2660.
- `cognitive_agent.py:2376, 4879 (in _run_pass:4870), 5484 (in _recovered_pass:5477)`; `handle_intent` at 7747-7755 and 7807.
- `delegate_task_tool.py:361-366, 398, 455, 476, 546-565` — the class is 88-565.
- `crew_executor.py:70-83, 1032-1044, 1987-1989, 2150-2161, 2204, 2386, 2597-2617`.
- `crew_assignment.py:58-62, 96-107, 113-139, 191, 220`.
- `crew_verifier.py:463, 611-623, 1002-1013, 1556-1558, 1599, 1640, 1733-1741, 1988-1991, 2054, 2099, 2127-2155, 2269-2276, 2595-2613`.
- `crew_finalizer.py:487-497, 552-571, 3450-3460`; `work_item_steps.py:368-374, 494`.
- `reply_pipeline.py:1009, 1045-1069, 1157, 1159-1170`.
- `finalize.py:2122-2133, 2196-2205, 2276`; `test_ad1155_loop_until_done.py:503-543`.
- `test_ad859_crew_executor.py:225-302`; `approval_authority.py:111-119, 241-243`; `protocols.py:325-358`.
- `architecture-baseline.yaml:349-355, 407-411, 433-439, 493-508, 993-997`; `check_architecture_principles.py:187-188`.

### Absence Verified (2026-10-19)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No other `WorkItemAgenticExecutor(` construction in src | grep `WorkItemAgenticExecutor\(` src/probos | cognitive_agent 2375, 4633, 5473; finalize 2196; delegate_task_tool 449 (agentic_dispatch 2347 is a docstring) | yes |
| No other `executor.run(` on an agentic executor | grep `executor\.run\(` src/probos | the five sites above, scout.py 545 (a `ProcessChainExecutor`), crew_orchestrator (CrewTaskExecutor) | yes |
| No other `AgenticLoop(` | grep | agentic_dispatch 3954 (inside `_run_reserved`), native_builder 139 (admitted turn) | yes |
| `interpret_recall` / `interpret_own_dream` have no caller | grep src | definitions and a docstring only | yes |
| No other `CrewAssignmentResolver(` in src | grep | finalize 2200 | yes |

### Prior Art and Blind Spots

ProbOS-specific plumbing; there is no outside analogue worth a search, so none was done. Blind spots, each recorded rather than widening scope:
- After admission, an owned-steps correction interrupted by any exception (not only a stop) still conflicts on replay. This is pre-existing.
- In the delegation race, a broker binding is left unused. Same as any child run that fails before its first effect.
- A `CrewTaskExecutor` built without a resolver (tests only; both production constructions pass one, `finalize.py:2227, 2320`) would map `AgentStopped` to `execution_exception`.

**Provenance.** Amendment A2 above: **Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-19, after review round 1 of the S1 candidate (tree `fc8b0819`); the orchestrator verified that every one of its 48 SEARCH blocks matches the candidate exactly once, on the candidate and on the candidate with the review's test repairs. The orchestrator's additions below are A2.1.

## Amendment A2.1 (orchestrator, 2026-10-19): four existing tests pin the exact keyword set the agent's own turns pass to `WorkItemAgenticExecutor.run`

Found by the whole-suite dry run of the candidate plus amendment A2 (4 failed of 48,847; the dry-run output named them): A2 makes the three of the agent's own run sites pass `admitted_turn=True` (Section 14), and two test files assert the exact keyword set of two of those sites. The assertions' purpose is unchanged (an unarmed turn passes the same kwargs as before AD-1208, plus nothing the economic organ adds); `admitted_turn` is the one new, always-passed key, pinned by the census (I12). Each edit carries an inline reason; none is deleted.

### Section 22: `tests/test_ad1208_cost_bounded_turns.py` (three tests)

22.1 the exact keys of the DM turn
<<<<<<< SEARCH
_P1_RUN_KWARGS = [
    "agent_id",
=======
_P1_RUN_KWARGS = [
    "admitted_turn",  # AD-1343 A2: the DM turn is the agent's own admitted turn; the run entry skips its stop check
    "agent_id",
>>>>>>> REPLACE

### Section 23: `tests/test_ad1323_continue_extension_e2e.py` (one test)

23.1 the keys of the recovered pass
<<<<<<< SEARCH
        "compose_disposition", "failure_scope", "token_budget", "plan_mode_tool_ids",
    }
=======
        "compose_disposition", "failure_scope", "token_budget", "plan_mode_tool_ids",
        "admitted_turn",  # AD-1343 A2: S2's promoted resume is an admitted turn; the run entry skips its stop check
    }
>>>>>>> REPLACE

## Test additions after the amendment (orchestrator; five new files, test-only)

The amendment's Tests table is implemented in five new files, each written red first on the candidate and green with A2 applied: `tests/test_ad1343_agent_stop_lift.py` (T27 to T29, plus a statement-fails-first flavour of T29 (b) so that `_rollback_quietly`'s failure handler is exercised), `tests/test_ad1343_agent_stop_runs.py` (T30, T31, T34), `tests/test_ad1343_agent_stop_crew.py` (T32, T33 with its owned and race variants), `tests/test_ad1343_stop_crossing_runs.py` (the amendment's X4, labelled X5 in the file because the crossing file already holds an X4, the fail-closed boot) and `tests/test_ad1343_stop_crossing_crew.py` (the amendment's X5, labelled X6). The review's test-coverage findings (F7) and its cheap test-strength items are added to `tests/test_ad1343_agent_stop.py` and `tests/test_ad1343_stop_crossing.py`.
