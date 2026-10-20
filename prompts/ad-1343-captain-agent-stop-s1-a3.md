## Amendment A3 (2026-10-19): review round 2 (R1–R5)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-19 — against staged tree `f812eae4`, HEAD `b4aa6b28`

### Section 24: `src/probos/agent_stop.py` (R3, R4; scope)

24.1 `S1_SCOPE` (R1, R2)
<<<<<<< SEARCH
        "the DM route, tasks delegated to it, crew subtasks (it is not eligible for crew work: a new "
        "subtask goes to an eligible colleague and one already assigned to it is not started), "
        "correction re-runs of its refuted subtasks (escalated unverified instead), browser actions "
        "and every tool call, protected effects included."
=======
        "the DM route, tasks delegated to it, crew work under its name (it is not eligible for a crew "
        "subtask: a new one goes to an eligible colleague and one already assigned to it is not started; "
        "it is not picked to verify a colleague's work; a crew session it facilitates waits for the "
        "Captain before synthesis), correction re-runs of its refuted subtasks (a crew session waits for "
        "the Captain instead; elsewhere the result is escalated unverified), browser actions and every "
        "tool call, protected effects included."
>>>>>>> REPLACE

24.2 the settled write (R3, R4)
<<<<<<< SEARCH
async def _commit_or_roll_back(db: "DatabaseConnection", sql: str, params: tuple[Any, ...]) -> None:
    """One statement and its commit; on any failure or cancellation the transaction is rolled back
    (so the next successful commit cannot land it) and the original error is re-raised."""
    try:
        await db.execute(sql, params)
        await db.commit()
    except BaseException:
        await _rollback_quietly(db)
        raise
=======
async def _commit_or_roll_back(db: "DatabaseConnection", sql: str, params: tuple[Any, ...]) -> None:
    """One statement and its commit; on a failure the transaction is rolled back (so the next
    successful commit cannot land it) and the original error is re-raised. A3: run only as
    ``_write_settled``'s task, which its caller never cancels; a task cancelled by a closing loop
    still rolls back."""
    try:
        await db.execute(sql, params)
        await db.commit()
    except BaseException:
        await _rollback_quietly(db)
        raise


async def _write_settled(
    db: "DatabaseConnection", sql: str, params: tuple[Any, ...],
) -> tuple[Exception | None, asyncio.CancelledError | None]:
    """One statement and its commit, run to its end whatever happens to the caller (A3: R3, R4).

    Cancelling an await on aiosqlite does not stop the call its worker thread was given: a queued
    COMMIT runs even after its future is cancelled, and a ROLLBACK queued behind it then has nothing
    to undo, so a cancellation says nothing about whether the write landed. The write runs in a task
    of its own and the caller waits through a shield (the AD-1198 A-1 pattern of
    ``federation/envelope.py``): the caller's cancellation is held until the write has ended.
    Returns ``(failure, cancellation)``: ``failure`` is None when the commit landed, else the
    write's own error, already rolled back; ``cancellation`` is the caller's, to be raised once
    memory matches the store. Unbounded, as an uncancelled write is.
    """
    write = asyncio.create_task(_commit_or_roll_back(db, sql, params), name="ad1343-agent-stop-write")
    cancellation: asyncio.CancelledError | None = None
    while not write.done():
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError as exc:  # the caller's: the write goes on
            cancellation = cancellation or exc
        except Exception:  # noqa: BLE001 -- the write's own failure, read from its task below
            break
    failure = write.exception()  # raises CancelledError only when the write itself was cancelled (a closing loop)
    if failure is None or isinstance(failure, Exception):
        return failure, cancellation
    raise failure
>>>>>>> REPLACE

24.3 issue (R3)
<<<<<<< SEARCH
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
            try:
                durable = await self._write_issued(record)
            except BaseException:  # cancelled mid-write: the order stays in force, honestly marked unwritten
                self._volatile.add(record.stop_id)
                raise
            if not durable:
                self._volatile.add(record.stop_id)
        await self._record_issued(record, durable)
        return StopIssued(record, already_stopped=False, durable=durable)
=======
        Applied to the in-memory view before it is written: if the write fails the agent
        is still stopped, and the answer says the order ends at the next restart. Issuing
        for an agent already stopped returns the order in force. A3: the write runs to its end
        even when the caller is cancelled, so ``durable`` is what the store holds; the
        cancellation is raised once the order, its durability and its event are settled.
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
            durable, cancellation = await self._write_issued(record)  # A3: settled, so durable is what the store holds
            if not durable:
                self._volatile.add(record.stop_id)
        await self._record_issued(record, durable)
        if cancellation is not None:
            raise cancellation  # A3: held until the order, its durability and its event were settled
        return StopIssued(record, already_stopped=False, durable=durable)
>>>>>>> REPLACE

24.4 lift (R4)
<<<<<<< SEARCH
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
=======
        written is included, and the row is brought up to date when one was. A failure of that
        second write is logged and leaves the lift standing. A3: each write runs to its end even
        when the caller is cancelled, so what is applied in memory is what the store holds; the
        cancellation is raised once the lift, its counts and its event are settled.
        """
        text = _valid_reason(reason)
        cancellation: asyncio.CancelledError | None = None
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
                failure, cancellation = await _write_settled(
                    self._db, _LIFT, (CAPTAIN, lifted_at, text, json.dumps(written, sort_keys=True), record.stop_id),
                )
                if failure is not None and cancellation is not None:
                    raise cancellation from failure  # rolled back: the agent stays stopped, and the caller is still cancelled
                if failure is not None:
                    raise failure  # rolled back: the agent stays stopped
            del self._active[agent_id]  # the last moment a seam can count a refusal under this order
            self._volatile.discard(record.stop_id)
            refused = self._refused.pop(record.stop_id, {})
            if durable and refused != written:
                cancellation = await self._write_final_counts(record, refused) or cancellation
        await self._record_lifted(record, lifted_at, refused)
        if cancellation is not None:
            raise cancellation  # A3: held until the lift, its counts and its event were settled
        return StopLifted(record, lifted_at, refused)
>>>>>>> REPLACE

24.5 the two writers (R3, R4)
<<<<<<< SEARCH
    async def _write_issued(self, record: StopRecord) -> bool:
        """Write an order; False (logged) when the store is closed or the write fails."""
        if self._db is None:
            logger.error(
                "AD-1343: stop %s for %s is in force but NOT written (the stop store is closed); "
                "it ends at the next restart", record.stop_id, record.agent_id,
            )
            return False
        try:
            await _commit_or_roll_back(
                self._db, _INSERT, (record.stop_id, record.agent_id, record.reason, record.issued_by, record.issued_at),
            )
        except Exception:
            logger.error(
                "AD-1343: stop %s for %s is in force but was NOT written; it ends at the next restart",
                record.stop_id, record.agent_id, exc_info=True,
            )
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
=======
    async def _write_issued(self, record: StopRecord) -> tuple[bool, asyncio.CancelledError | None]:
        """Write an order, run to its end (A3): ``(durable, cancellation)``. Not durable (logged) when the
        store is closed or the write fails; ``cancellation`` is the caller's, if one arrived meanwhile."""
        if self._db is None:
            logger.error(
                "AD-1343: stop %s for %s is in force but NOT written (the stop store is closed); "
                "it ends at the next restart", record.stop_id, record.agent_id,
            )
            return False, None
        failure, cancellation = await _write_settled(
            self._db, _INSERT, (record.stop_id, record.agent_id, record.reason, record.issued_by, record.issued_at),
        )
        if failure is not None:
            logger.error(
                "AD-1343: stop %s for %s is in force but was NOT written; it ends at the next restart",
                record.stop_id, record.agent_id, exc_info=failure,
            )
            return False, cancellation  # log-and-degrade: the stop stays in force
        return True, cancellation

    async def _write_final_counts(self, record: StopRecord, refused: dict[str, int]) -> asyncio.CancelledError | None:
        """Bring a lifted row's refusal counts to their final value, run to its end (A3); on failure log it
        (the lift stands). Returns the caller's cancellation, if one arrived while it was written."""
        if self._db is None:  # for the type checker: stop() closes the store only under the lock held here
            return None
        failure, cancellation = await _write_settled(
            self._db, _FINAL_COUNTS, (json.dumps(refused, sort_keys=True), record.stop_id),
        )
        if failure is not None:
            logger.error(
                "AD-1343: stop %s for %s is lifted, but its final refusal counts %s were NOT written; "
                "the row keeps the counts at the moment the lift was written",
                record.stop_id, record.agent_id, refused, exc_info=failure,
            )
        return cancellation
>>>>>>> REPLACE

### Section 25: `src/probos/cognitive/crew_verifier.py` (R1, R2, R5)

25.1 import
<<<<<<< SEARCH
from probos.agent_stop import SEAM_AGENTIC_RUN, AgentStopped, active_stop
=======
from probos.agent_stop import SEAM_AGENTIC_RUN, AgentStopped, active_stop, standing_stop
>>>>>>> REPLACE

25.2 legacy judgment: re-checked after the awaits that build its prompt (R1)
<<<<<<< SEARCH
        prompt += await self._build_trace_section(
            getattr(result, "tool_trace_ref", None),
        )
        request_tier = self._judge_tier()
=======
        prompt += await self._build_trace_section(
            getattr(result, "tool_trace_ref", None),
        )
        if self._stopped(verifier_id):  # A3 (R1): stopped while its prompt was built; nothing is judged under its name
            return VerificationVerdict(
                accepted=False,
                confidence=0.0,
                critique="No independent verifier available; result unverified.",
                verifier_agent_id="",
                verification_defect=True,
            )
        request_tier = self._judge_tier()
>>>>>>> REPLACE

25.3 session judgment (R1)
<<<<<<< SEARCH
            prompt += await self._build_trace_section(
                getattr(result, "tool_trace_ref", None),
            )
            response = await self._llm.complete(LLMRequest(
=======
            prompt += await self._build_trace_section(
                getattr(result, "tool_trace_ref", None),
            )
            if self._stopped(verifier_id):  # A3 (R1): stopped while its prompt was built (session); nothing is judged
                return SessionVerificationPass(
                    status="unavailable",
                    accepted=False,
                    confidence=0.0,
                    critique="No eligible independent verifier is available.",
                    verifier_agent_id="",
                    tokens_used=0,
                    failure_code="independent_verifier_unavailable",
                )
            response = await self._llm.complete(LLMRequest(
>>>>>>> REPLACE

25.4 docstring (R2)
<<<<<<< SEARCH
        """Converge one child with bounded revisions and no learning writes."""
=======
        """Converge one child with bounded revisions and no learning writes.

        AD-1343 A3: raises ``AgentStopped`` when the producer of a refuted child is stopped by the
        Captain's order before its correction runs. No correction executes and no outcome is
        returned, so nothing can read the stop as exhaustion; the finalizer blocks the session as
        for a producer that is not available.
        """
>>>>>>> REPLACE

25.5 before admission (R2)
<<<<<<< SEARCH
            # AD-1343: a stopped producer is not re-run; checked before a correction is admitted.
            if active_stop(getattr(self._runtime, "agent_stops", None), current.agent_id, SEAM_AGENTIC_RUN) is not None:
                return self._producer_stopped_outcome(current, history)
=======
            # AD-1343: a stopped producer is not re-run; checked before a correction is admitted. A3 (R2): raised, not
            # returned, so no outcome is recorded and nothing reads the stop as exhaustion.
            stopped = active_stop(getattr(self._runtime, "agent_stops", None), current.agent_id, SEAM_AGENTIC_RUN)
            if stopped is not None:
                raise AgentStopped(stopped)  # A3 (R2): before admission, so nothing was admitted or executed
>>>>>>> REPLACE

25.6 at the run entry (R2, R5)
<<<<<<< SEARCH
            except AgentStopped:
                return self._producer_stopped_outcome(current, history)  # AD-1343: stopped after the check above
=======
            except AgentStopped:
                # AD-1343 A3 (R2, R5): stopped after the check above, at the run entry. No correction executed and no
                # outcome is recorded. A correction admitted first (an owned session) keeps its permit as the evidence
                # of that admission, and is said so here.
                if correction_permit is not None:
                    logger.warning(
                        "AD-1343: correction %d of child %s was admitted but not executed: its producer %s is "
                        "stopped by the Captain's order",
                        attempt_index, current.work_item_id, current.agent_id,
                    )
                raise  # A3 (R2): the finalizer blocks the session as for a producer that is not available
>>>>>>> REPLACE

25.7 the stop question replaces the exhaustion terminal (R1, R2)
<<<<<<< SEARCH
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
=======
    def _stopped(self, agent_id: object) -> bool:
        """AD-1343 A3 (R1): is ``agent_id`` stopped by the Captain's order? Memory only, and not counted.

        Asked of each verifier candidate and again just before a judgment's model call. A candidate
        passed over refuses no work (a colleague verifies, or the existing unavailable outcome stands),
        the ``CrewAssignmentResolver.check_eligibility`` rule.
        """
        return standing_stop(getattr(self._runtime, "agent_stops", None), agent_id) is not None
>>>>>>> REPLACE

25.8 session pick (R1)
<<<<<<< SEARCH
            if self._registry.get(candidate_id) is not candidate:
                continue
            if getattr(candidate, "is_alive", None) is not True:
                continue
            return candidate_id
=======
            if self._registry.get(candidate_id) is not candidate:
                continue
            if getattr(candidate, "is_alive", None) is not True:
                continue
            if self._stopped(candidate_id):  # A3 (R1): a stopped colleague is never picked
                continue
            return candidate_id
>>>>>>> REPLACE

25.9 legacy pick, any independent (R1)
<<<<<<< SEARCH
        for agent in agents:
            agent_id = getattr(agent, "id", None)
            if agent_id and agent_id != producer_id:
                return agent_id
        return None
=======
        for agent in agents:
            agent_id = getattr(agent, "id", None)
            if agent_id and agent_id != producer_id and not self._stopped(agent_id):  # A3 (R1): never a stopped agent
                return agent_id
        return None
>>>>>>> REPLACE

25.10 department peer (R1)
<<<<<<< SEARCH
            if self._registry.get(agent_id) is None:
                continue  # dead/unregistered — excluded
=======
            if self._registry.get(agent_id) is None:
                continue  # dead/unregistered — excluded
            if self._stopped(agent_id):  # A3 (R1): a stopped department peer is passed over
                continue
>>>>>>> REPLACE

25.11 chief (R1)
<<<<<<< SEARCH
                if self._registry.get(cand_id) is None:
                    continue  # superior post unfilled by a live agent — excluded
                return cand_id
=======
                if self._registry.get(cand_id) is None:
                    continue  # superior post unfilled by a live agent — excluded
                if self._stopped(cand_id):  # A3 (R1): a stopped chief is passed over
                    continue
                return cand_id
>>>>>>> REPLACE

### Section 26: `src/probos/cognitive/crew_synth.py` (R1)

26.1 import
<<<<<<< SEARCH
from probos.cognitive.crew_verdict import criteria_to_json, judge_to_json
from probos.cognitive.crew_verifier import SubtaskVerifier
=======
from probos.agent_stop import SEAM_AGENTIC_RUN, AgentStopped, active_stop
from probos.cognitive.crew_verdict import criteria_to_json, judge_to_json
from probos.cognitive.crew_verifier import SubtaskVerifier
>>>>>>> REPLACE

26.2 docstring
<<<<<<< SEARCH
        """Produce one bounded session draft without completion or learning writes."""
=======
        """Produce one bounded session draft without completion or learning writes.

        AD-1343 A3: raises ``AgentStopped`` before the model call when the facilitator is stopped by
        the Captain's order; invalid inputs still fail first, as before.
        """
>>>>>>> REPLACE

26.3 the entry
<<<<<<< SEARCH
        system_prompt = f"{self._SESSION_SYSTEM_PROMPT}\n\nFACILITATOR INSTRUCTIONS:\n{instructions}"
        try:
            response = await self._llm.complete(LLMRequest(
=======
        system_prompt = f"{self._SESSION_SYSTEM_PROMPT}\n\nFACILITATOR INSTRUCTIONS:\n{instructions}"
        # AD-1343 A3 (R1): the facilitator's model work is new work under its name and instructions. A stopped
        # facilitator is refused here, after the inputs are validated and with no await before the model call.
        stopped = active_stop(getattr(self._runtime, "agent_stops", None), producer_key, SEAM_AGENTIC_RUN)
        if stopped is not None:
            raise AgentStopped(stopped)
        try:
            response = await self._llm.complete(LLMRequest(
>>>>>>> REPLACE

### Section 27: `src/probos/cognitive/crew_finalizer.py` (R1, R2)

27.1 import
<<<<<<< SEARCH
from probos import work_item_steps as owned_steps
from probos.cognitive.crew_session import CrewSynthesisMetadata
=======
from probos import work_item_steps as owned_steps
from probos.agent_stop import SEAM_AGENTIC_RUN, AgentStopped, AgentStopService, active_stop
from probos.cognitive.crew_session import CrewSynthesisMetadata
>>>>>>> REPLACE

27.2 constructor injection
<<<<<<< SEARCH
        approval_threshold: float = 0.6,
        use_confidence_weights: bool = True,
    ) -> None:
=======
        approval_threshold: float = 0.6,
        use_confidence_weights: bool = True,
        agent_stops: AgentStopService | None = None,
    ) -> None:
>>>>>>> REPLACE

27.3
<<<<<<< SEARCH
        self._use_confidence_weights = use_confidence_weights
        self._active_claims: dict[str, _ClaimAttempt] = {}
=======
        self._use_confidence_weights = use_confidence_weights
        self._agent_stops = agent_stops  # AD-1343 A3: a stopped facilitator's synthesis is not claimed
        self._active_claims: dict[str, _ClaimAttempt] = {}
>>>>>>> REPLACE

27.4 resume: a stopped producer, as one not live (R2)
<<<<<<< SEARCH
        outcome = await self._verifier.converge_for_session(
            result,
            instructions=instructions,
            task_text=task_text,
            expected_output=self._expected_output(child),
            parent_id=session.task_id,
            thread_id=session.thread_id,
            department=str(getattr(producer, "department", "") or ""),
            rank=str(getattr(producer, "rank", "ensign") or "ensign"),
            **(
                {"owned_steps_snapshot": owned_snapshot}
                if owned_snapshot is not None
                else {}
            ),
        )
        return await self._defer_checkpoint(self._checkpoint_child_convergence(
=======
        try:
            outcome = await self._verifier.converge_for_session(
                result,
                instructions=instructions,
                task_text=task_text,
                expected_output=self._expected_output(child),
                parent_id=session.task_id,
                thread_id=session.thread_id,
                department=str(getattr(producer, "department", "") or ""),
                rank=str(getattr(producer, "rank", "ensign") or "ensign"),
                **(
                    {"owned_steps_snapshot": owned_snapshot}
                    if owned_snapshot is not None
                    else {}
                ),
            )
        except AgentStopped as exc:  # A3 (R2): the producer was stopped before its correction; nothing is recorded
            raise ValueError("child_producer_unavailable") from exc
        return await self._defer_checkpoint(self._checkpoint_child_convergence(
>>>>>>> REPLACE

27.5 resume: a stopped facilitator, checked before the claim (R1)
<<<<<<< SEARCH
        facilitator = self._live_agent(session.facilitator_id)
        if facilitator is None:
            raise ValueError("synthesis_producer_unavailable")
        instructions = _text(
            getattr(facilitator, "instructions", None),
            maximum_codepoints=32_768,
            maximum_bytes=_MAX_INSTRUCTIONS_BYTES,
        )
        await self._claim_owned_synthesis(session)
        draft = await self._synthesizer.synthesize_for_session(
            parent_id=session.task_id,
            producer_agent_id=session.facilitator_id,
            producer_instructions=instructions,
            goal=session.goal,
            success_criteria=session.success_criteria,
            expected_deliverable=session.expected_deliverable,
            outcomes=tuple(item.outcome for item in publications),
        )
=======
        facilitator = self._live_agent(session.facilitator_id)
        if facilitator is None or active_stop(self._agent_stops, session.facilitator_id, SEAM_AGENTIC_RUN) is not None:
            # AD-1343 A3 (R1): a facilitator stopped by the Captain's order is not available, as one not live; checked
            # before the synthesis is claimed, so a resume after the lift is not read as an interrupted synthesis.
            raise ValueError("synthesis_producer_unavailable")
        instructions = _text(
            getattr(facilitator, "instructions", None),
            maximum_codepoints=32_768,
            maximum_bytes=_MAX_INSTRUCTIONS_BYTES,
        )
        await self._claim_owned_synthesis(session)
        try:
            draft = await self._synthesizer.synthesize_for_session(
                parent_id=session.task_id,
                producer_agent_id=session.facilitator_id,
                producer_instructions=instructions,
                goal=session.goal,
                success_criteria=session.success_criteria,
                expected_deliverable=session.expected_deliverable,
                outcomes=tuple(item.outcome for item in publications),
            )
        except AgentStopped as exc:  # A3 (R1): stopped while the synthesis was claimed; nothing was synthesized
            raise ValueError("synthesis_producer_unavailable") from exc
>>>>>>> REPLACE

27.6 fresh path: a stopped producer (R2)
<<<<<<< SEARCH
                correction_tokens = self._correction_tokens(outcome)
            except asyncio.CancelledError:
                raise
            except Exception:
                return await self._fail(
                    session,
                    reason="verification_defect",
                    accepted_count=self._accepted_count(publications),
                    total_count=len(children),
                )
=======
                correction_tokens = self._correction_tokens(outcome)
            except asyncio.CancelledError:
                raise
            except AgentStopped:  # A3 (R2): the producer was stopped before its correction; no outcome, no exhaustion
                return await self._fail(
                    session,
                    reason="child_producer_unavailable",
                    accepted_count=self._accepted_count(publications),
                    total_count=len(children),
                    blocked=True,
                )
            except Exception:
                return await self._fail(
                    session,
                    reason="verification_defect",
                    accepted_count=self._accepted_count(publications),
                    total_count=len(children),
                )
>>>>>>> REPLACE

27.7 fresh path: a stopped facilitator (R1)
<<<<<<< SEARCH
            if validated_final_text != draft.final_text:
                raise ValueError("crew_finalization_synthesis_invalid")
        except asyncio.CancelledError:
            raise
        except Exception:
=======
            if validated_final_text != draft.final_text:
                raise ValueError("crew_finalization_synthesis_invalid")
        except asyncio.CancelledError:
            raise
        except AgentStopped:  # A3 (R1): the facilitator is stopped; nothing was synthesized, as a facilitator not live
            return await self._fail(
                session,
                reason="synthesis_producer_unavailable",
                accepted_count=self._accepted_count(publications),
                total_count=len(children),
                blocked=True,
            )
        except Exception:
>>>>>>> REPLACE

### Section 28: `src/probos/startup/finalize.py` (wiring)

28.1
<<<<<<< SEARCH
        use_confidence_weights=getattr(
            consensus_config,
            "use_confidence_weights",
            True,
        ),
    )
    runtime.crew_orchestrator = CrewOrchestrator(  # public attr (Wave 5 conv #1)
=======
        use_confidence_weights=getattr(
            consensus_config,
            "use_confidence_weights",
            True,
        ),
        agent_stops=getattr(runtime, "agent_stops", None),  # AD-1343 A3: a stopped facilitator's synthesis is not claimed
    )
    runtime.crew_orchestrator = CrewOrchestrator(  # public attr (Wave 5 conv #1)
>>>>>>> REPLACE

### Section 29: `tests/test_ad1343_agent_stop_lift.py` (T28, T29; each change states why inline)

29.1 docstring
<<<<<<< SEARCH
* T29: a commit that fails or is cancelled is rolled back, on issue and on lift, so no later successful write lands it.
=======
* T29: a commit that fails is rolled back, on issue and on lift, so no later successful write lands it; a cancelled caller
  waits for its write to settle, and memory follows what the store holds (A3: R3, R4).
>>>>>>> REPLACE

29.2 T28: the lift event (review item b)
<<<<<<< SEARCH
    factory = _GatedFactory(_COUNTS_SQL)  # the final-count UPDATE raises; every other statement works
    with caplog.at_level(logging.WARNING, logger="probos.agent_stop"):
        async with _service(tmp_path, connection_factory=factory, clock=_Clock()) as service:
=======
    factory = _GatedFactory(_COUNTS_SQL)  # the final-count UPDATE raises; every other statement works
    # A3 (review item b): with an EventLog, so a lift that skipped its event when the second write fails cannot pass.
    event_log = EventLog(db_path=tmp_path / "events.db")
    await event_log.start()
    with caplog.at_level(logging.WARNING, logger="probos.agent_stop"):
        async with _service(tmp_path, connection_factory=factory, event_log=event_log, clock=_Clock()) as service:
>>>>>>> REPLACE

29.3
<<<<<<< SEARCH
            attempts = [sql for sql in factory.statements if sql.lstrip().startswith(_COUNTS_SQL)]
            assert len(attempts) == 1  # premise: the row was brought up to date once, and that statement raised

    errors = [line for level, line in _stop_log(caplog) if level == logging.ERROR]
=======
            attempts = [sql for sql in factory.statements if sql.lstrip().startswith(_COUNTS_SQL)]
            assert len(attempts) == 1  # premise: the row was brought up to date once, and that statement raised
    await event_log.stop()
    with contextlib.closing(sqlite3.connect(tmp_path / "events.db")) as conn:
        lifted_events = [json.loads(data) for (data,) in conn.execute("SELECT data FROM events WHERE event = 'agent_stop_lifted'")]
    assert [(event["stop_id"], event["refused"]) for event in lifted_events] == [(issued.record.stop_id, {"tool": 1})]

    errors = [line for level, line in _stop_log(caplog) if level == logging.ERROR]
>>>>>>> REPLACE

29.4 T29 driver
<<<<<<< SEARCH
    await _lift_whose_statement_fails(tmp_path / "lift_statement")
    await _lift_cancelled_in_its_commit(tmp_path / "lift_cancelled")
    await _issue_cancelled_in_its_commit(tmp_path / "issue_cancelled")
=======
    await _lift_whose_statement_fails(tmp_path / "lift_statement")
    # A3 (R3, R4): (c) and (d) asserted that a cancelled caller's write is rolled back. That held only because this double
    # never forwarded the COMMIT once its caller was cancelled; the real aiosqlite worker does (aiosqlite/core.py:59-75), and
    # tests/test_ad1343_agent_stop_settle.py pauses the real worker. Each case is now split by what the COMMIT then does.
    await _lift_cancelled_in_its_commit_that_lands(tmp_path / "lift_cancelled")
    await _lift_cancelled_in_its_commit_that_fails(tmp_path / "lift_cancelled_fails")
    await _issue_cancelled_in_its_commit_that_lands(tmp_path / "issue_cancelled")
    await _issue_cancelled_in_its_commit_that_fails(tmp_path / "issue_cancelled_fails")
>>>>>>> REPLACE

29.5 (c), (d) replaced (premise corrected, see 29.4)
<<<<<<< SEARCH
async def _lift_cancelled_in_its_commit(data_dir: Path) -> None:
    """(c) Cancel: the lift is cancelled while its COMMIT is paused. CancelledError propagates, the counts are intact, and a
    later write cannot land the lift."""
    factory = _GatedFactory()
    async with _service(data_dir, connection_factory=factory, clock=_Clock()) as service:
        issued = await service.issue_stop(AGENT, reason=REASON)
        assert issued.durable is True  # premise: the order is written
        assert service.refusal(AGENT, SEAM_TOOL) == issued.record  # premise: a count that must survive the cancelled lift
        factory.gate.pause_after = _LIFT_SQL
        async with _paused(factory.gate, service.lift_stop(AGENT, reason=LIFT_REASON)) as lift:
            lift.cancel()
            await asyncio.wait({lift}, timeout=_BOUND)
            assert lift.cancelled()  # CancelledError propagated out of lift_stop: it was not swallowed
        assert service.stop_for(AGENT) == issued.record  # the lift was not applied
        assert service.refused_counts(issued.record.stop_id) == {"tool": 1}  # and the counts are intact
        other = await service.issue_stop(OTHER, reason=REASON)
        assert other.durable is True  # a later write succeeds
    assert _rows_by_agent(data_dir)[AGENT]["lifted_at"] is None  # and does not commit the cancelled lift
    async with _service(data_dir) as restarted:
        assert restarted.stop_for(AGENT) == issued.record
        assert restarted.stop_for(OTHER) == other.record


async def _issue_cancelled_in_its_commit(data_dir: Path) -> None:
    """(d) Cancel issue: the issue is cancelled while the INSERT's COMMIT is paused. The order stays in force, marked unwritten,
    and a later write cannot land it."""
    factory = _GatedFactory()
    async with _service(data_dir, connection_factory=factory, clock=_Clock()) as service:
        factory.gate.pause_after = _INSERT_SQL
        async with _paused(factory.gate, service.issue_stop(AGENT, reason=REASON)) as issue:
            in_force = service.stop_for(AGENT)
            assert in_force is not None  # premise: an order is applied before it is written
            issue.cancel()
            await asyncio.wait({issue}, timeout=_BOUND)
            assert issue.cancelled()  # CancelledError propagated out of issue_stop: it was not swallowed
        again = await service.issue_stop(AGENT, reason=REASON)
        assert again.already_stopped is True and again.record == in_force  # the order is still in force
        assert again.durable is False  # and the answer is honest: nothing was written
        other = await service.issue_stop(OTHER, reason=REASON)
        assert other.durable is True  # a later write succeeds
        assert list(_rows_by_agent(data_dir)) == [OTHER]  # and lands itself alone, not the cancelled order
    async with _service(data_dir) as restarted:
        assert restarted.stop_for(AGENT) is None  # unwritten, as the answer said
        assert restarted.stop_for(OTHER) == other.record
=======
async def _lift_cancelled_in_its_commit_that_lands(data_dir: Path) -> None:
    """(c) Cancel, then the COMMIT lands: CancelledError propagates once it has, and the lift is applied, in memory and on file."""
    factory = _GatedFactory()
    async with _service(data_dir, connection_factory=factory, clock=_Clock()) as service:
        issued = await service.issue_stop(AGENT, reason=REASON)
        assert issued.durable is True  # premise: the order is written
        assert service.refusal(AGENT, SEAM_TOOL) == issued.record  # premise: a count the lift carries
        factory.gate.pause_after = _LIFT_SQL
        async with _paused(factory.gate, service.lift_stop(AGENT, reason=LIFT_REASON)) as lift:
            lift.cancel()
            factory.gate.release.set()  # the paused COMMIT goes on, as the real worker's does
            await asyncio.wait({lift}, timeout=_BOUND)
            assert lift.cancelled()  # held until the write settled, then propagated: not swallowed
        assert service.stop_for(AGENT) is None  # the lift landed, so it is applied
    row = _rows_by_agent(data_dir)[AGENT]
    assert row["lifted_at"] is not None and row["refused_json"] == '{"tool": 1}'
    async with _service(data_dir) as restarted:
        assert restarted.stop_for(AGENT) is None


async def _lift_cancelled_in_its_commit_that_fails(data_dir: Path) -> None:
    """(c2) Cancel, then the COMMIT fails: the caller is still cancelled, the agent stays stopped, the counts are intact, and a
    later write cannot land the lift."""
    factory = _GatedFactory()
    async with _service(data_dir, connection_factory=factory, clock=_Clock()) as service:
        issued = await service.issue_stop(AGENT, reason=REASON)
        assert issued.durable is True
        assert service.refusal(AGENT, SEAM_TOOL) == issued.record
        factory.gate.pause_after = _LIFT_SQL
        factory.gate.fail_after = _LIFT_SQL
        async with _paused(factory.gate, service.lift_stop(AGENT, reason=LIFT_REASON)) as lift:
            lift.cancel()
            factory.gate.release.set()
            await asyncio.wait({lift}, timeout=_BOUND)
            assert lift.cancelled()  # told it was cancelled, not handed the write's error
        assert factory.gate.failed == 1  # premise: the COMMIT raised after the pause
        assert service.stop_for(AGENT) == issued.record
        assert service.refused_counts(issued.record.stop_id) == {"tool": 1}
        other = await service.issue_stop(OTHER, reason=REASON)
        assert other.durable is True
    assert _rows_by_agent(data_dir)[AGENT]["lifted_at"] is None
    async with _service(data_dir) as restarted:
        assert restarted.stop_for(AGENT) == issued.record
        assert restarted.stop_for(OTHER) == other.record


async def _issue_cancelled_in_its_commit_that_lands(data_dir: Path) -> None:
    """(d) Cancel issue, then the COMMIT lands: the order is in force and durable, as the store holds it."""
    factory = _GatedFactory()
    async with _service(data_dir, connection_factory=factory, clock=_Clock()) as service:
        factory.gate.pause_after = _INSERT_SQL
        async with _paused(factory.gate, service.issue_stop(AGENT, reason=REASON)) as issue:
            in_force = service.stop_for(AGENT)
            assert in_force is not None  # premise: an order is applied before it is written
            issue.cancel()
            factory.gate.release.set()
            await asyncio.wait({issue}, timeout=_BOUND)
            assert issue.cancelled()
        again = await service.issue_stop(AGENT, reason=REASON)
        assert again.already_stopped is True and again.record == in_force
        assert again.durable is True  # A3 (R3): what the store holds
    assert list(_rows_by_agent(data_dir)) == [AGENT]
    async with _service(data_dir) as restarted:
        assert restarted.stop_for(AGENT) == in_force


async def _issue_cancelled_in_its_commit_that_fails(data_dir: Path) -> None:
    """(d2) Cancel issue, then the COMMIT fails: the order stays in force, marked unwritten, and a later write cannot land it."""
    factory = _GatedFactory()
    async with _service(data_dir, connection_factory=factory, clock=_Clock()) as service:
        factory.gate.pause_after = _INSERT_SQL
        factory.gate.fail_after = _INSERT_SQL
        async with _paused(factory.gate, service.issue_stop(AGENT, reason=REASON)) as issue:
            in_force = service.stop_for(AGENT)
            assert in_force is not None
            issue.cancel()
            factory.gate.release.set()
            await asyncio.wait({issue}, timeout=_BOUND)
            assert issue.cancelled()
        again = await service.issue_stop(AGENT, reason=REASON)
        assert again.already_stopped is True and again.record == in_force
        assert again.durable is False
        other = await service.issue_stop(OTHER, reason=REASON)
        assert other.durable is True
        assert list(_rows_by_agent(data_dir)) == [OTHER]
    async with _service(data_dir) as restarted:
        assert restarted.stop_for(AGENT) is None
        assert restarted.stop_for(OTHER) == other.record
>>>>>>> REPLACE

### Section 30: `tests/test_ad1343_agent_stop_crew.py` (T33; review item d)

30.1 docstring
<<<<<<< SEARCH
* T33: ``SubtaskVerifier`` does not re-run a stopped producer for a correction. The legacy loop and the session loop both end the
  refuted result ``unverified`` (the session record carrying the rounds actually used, which the finalizer's
  ``ChildVerificationRecord`` accepts), the owned-steps port is never asked to admit the correction, and a stop that lands after the
  check, so that the executor's run entry refuses, is handled as the same escalation and not as a fault.
=======
* T33: ``SubtaskVerifier`` does not re-run a stopped producer for a correction. The legacy loop ends the refuted result
  ``unverified``; the session loop raises ``AgentStopped`` and records no outcome (A3, R2: an exhaustion record charged the stopped
  producer), the owned-steps port is never asked to admit the correction, and a stop that lands after the check, so that the
  executor's run entry refuses, is re-raised and never a fault. Finalization and trust: tests/test_ad1343_stop_crossing_finalizer.py.
>>>>>>> REPLACE

30.2 helper whose last use A3 removes
<<<<<<< SEARCH
def _escalated_unverified(document: dict[str, Any]) -> tuple[Any, ...]:
    return (
        document["status"], document["rounds_used"], len(document["rounds"]), document["failure_code"], document["terminal_attempt"],
    )


=======
>>>>>>> REPLACE

30.3 T33
<<<<<<< SEARCH
        record = (await service.issue_stop(AGENT, reason=REASON)).record
        outcome = await converge(verifier)

        # the refuted result ends unverified; the answer was not changed by any correction
        assert outcome.status == "unverified"
        assert outcome.result.output == FIRST_DRAFT
        if loop == "legacy":
            assert outcome.rounds == 0  # no round ran
            assert (outcome.verdict.accepted, outcome.verdict.critique) == (False, CRITIQUE)  # premise: a refutation, so a re-run was due
        else:
            assert (outcome.failure_code, outcome.terminal_attempt) == ("convergence_exhausted", None)
            assert [(item.verdict.status, item.verdict.critique) for item in outcome.history] == [("refuted", CRITIQUE)]  # premise
            assert outcome.rounds_used == len(outcome.history) - 1 == 0  # the rounds actually used: the finalizer demands it
            assert _escalated_unverified(_finalizer_document(outcome)) == ("unverified", 0, 1, "convergence_exhausted", None)
=======
        record = (await service.issue_stop(AGENT, reason=REASON)).record
        if loop == "legacy":
            outcome = await converge(verifier)
            # the refuted result ends unverified; the answer was not changed by any correction
            assert outcome.status == "unverified"
            assert outcome.result.output == FIRST_DRAFT
            assert outcome.rounds == 0  # no round ran
            assert (outcome.verdict.accepted, outcome.verdict.critique) == (False, CRITIQUE)  # premise: a refutation, so a re-run was due
        else:
            # A3 (R2): no outcome is recorded for a stopped producer (an exhaustion record charged it in finalization); the loop
            # raises and the finalizer blocks the session (tests/test_ad1343_stop_crossing_finalizer.py, X7).
            with pytest.raises(agent_stop.AgentStopped) as raised:
                await converge(verifier)
            assert raised.value.record == record and PRIVATE_FRAGMENT not in str(raised.value)
>>>>>>> REPLACE

30.4 T33 (owned)
<<<<<<< SEARCH
        record = (await service.issue_stop(AGENT, reason=REASON)).record
        outcome = await _converge_session(verifier, snapshot=_owned_snapshot())

        assert port.admitted == [CHILD]  # the stopped producer's correction was not admitted: the port was not asked again
        assert executor.calls == []
        assert (outcome.status, outcome.failure_code, outcome.terminal_attempt) == ("unverified", "convergence_exhausted", None)
        assert outcome.rounds_used == len(outcome.history) - 1 == 0
        assert _escalated_unverified(_finalizer_document(outcome)) == ("unverified", 0, 1, "convergence_exhausted", None)
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}
=======
        record = (await service.issue_stop(AGENT, reason=REASON)).record
        with caplog.at_level(logging.WARNING), pytest.raises(agent_stop.AgentStopped):
            await _converge_session(verifier, snapshot=_owned_snapshot())  # A3 (R2): raised; no outcome is recorded

        assert port.admitted == [CHILD]  # the stopped producer's correction was not admitted: the port was not asked again
        assert executor.calls == []
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}
        assert not any("admitted but not executed" in r.getMessage() for r in caplog.records)  # A3 (R5): before admission
>>>>>>> REPLACE

30.5 T33 (race, session): renamed, since it no longer ends unverified
<<<<<<< SEARCH
async def test_a_stopped_producer_race_ends_unverified_never_failed_session(
=======
async def test_a_stopped_producer_race_is_re_raised_never_failed_session(
>>>>>>> REPLACE

30.6
<<<<<<< SEARCH
        outcome = await _converge_session(verifier)

        record = service.stop_for(AGENT)
        assert record is not None and entry.reached == 1
        # the run entry reached through the projected correction runtime (which has no ``agent_stops``) refused all the same
        assert isinstance(entry.raised, agent_stop.AgentStopped) and entry.raised.record == record
        assert record.stop_id in str(entry.raised) and PRIVATE_FRAGMENT not in str(entry.raised)
        assert llm.calls == []
        # unverified, never failed / correction_execution_defect, and the finalizer accepts the record
        assert (outcome.status, outcome.failure_code, outcome.terminal_attempt) == ("unverified", "convergence_exhausted", None)
        assert outcome.rounds_used == len(outcome.history) - 1
        assert _escalated_unverified(_finalizer_document(outcome)) == ("unverified", outcome.rounds_used, 1, "convergence_exhausted", None)
        assert len(judge.requests) == 1
        assert outcome.result.output == FIRST_DRAFT
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}
        assert _logged_as_a_fault(caplog) == []
=======
        with pytest.raises(agent_stop.AgentStopped) as raised:  # A3 (R2): re-raised, never a terminal outcome
            await _converge_session(verifier)

        record = service.stop_for(AGENT)
        assert record is not None and entry.reached == 1
        # the run entry reached through the projected correction runtime (which has no ``agent_stops``) refused all the same
        assert isinstance(entry.raised, agent_stop.AgentStopped) and entry.raised.record == record
        assert raised.value is entry.raised  # the verifier re-raised the entry's refusal unchanged
        assert record.stop_id in str(entry.raised) and PRIVATE_FRAGMENT not in str(entry.raised)
        assert llm.calls == []
        assert len(judge.requests) == 1
        assert service.refused_counts(record.stop_id) == {"agentic_run": 1}
        assert _logged_as_a_fault(caplog) == []  # never failed / correction_execution_defect
>>>>>>> REPLACE

### Section 31: `tests/test_ad1343_stop_crossing_crew.py` (X6; review item a)

31.1
<<<<<<< SEARCH
        assert is_untouched_crew_child(child, initial_status=initial_status)
        assert parent.status != "failed" and child.status != "failed"

        record = (await service.issue_stop("builder-1", reason=REASON)).record
=======
        assert is_untouched_crew_child(child, initial_status=initial_status)
        assert parent.status != "failed" and child.status != "failed"

        # A3 (review item a): the golden must RUN the executor, or "CrewTaskExecutor.run always raises CrewWorkerUnavailable"
        # passes. A second parent whose child is also builder-1's, run with no order in force, is started: it reaches the model
        # (which refuses every call, so the run then ends however the executor ends that) and is never refused as unavailable.
        golden_parent = await store.create_work_item(title="golden parent", work_type="work_order")
        await store.create_work_item(
            title="analysis", description="please do analysis", work_type="task", parent_id=golden_parent.id,
            assigned_to="builder-1", depends_on=[], metadata={"spec_id": "spec-a"},
        )
        try:
            await asyncio.wait_for(executor.run(golden_parent.id), timeout=_BOUND)
        except CrewWorkerUnavailable:
            raise AssertionError("AD-1343 X6 golden: an unstopped agent's child was refused as unavailable") from None
        except Exception:  # noqa: BLE001 -- the counting model refuses to answer; the golden claims only that the run started
            pass
        assert llm.calls, "AD-1343 X6 golden: the unstopped child never reached the model"
        llm.calls.clear()

        record = (await service.issue_stop("builder-1", reason=REASON)).record
>>>>>>> REPLACE

31.2 (the store now holds two parents; the stopped parent's child list is unchanged)
<<<<<<< SEARCH
        assert [(item.id, item.status) for item in await store.list_work_items(parent_id=parent.id, limit=10)] == [
=======
        assert [(item.id, item.status) for item in await store.list_work_items(parent_id=parent.id, limit=10)] == [  # A3: per parent
>>>>>>> REPLACE

### Section 32: `tests/test_ad1343_stop_seam_inventory.py` (I14–I17; review item e)

32.1 docstring
<<<<<<< SEARCH
7. CREW (A2): crew eligibility consults the stop before any lookup, and its one construction is wired.
=======
7. CREW (A2): crew eligibility consults the stop before any lookup, and its one construction is wired.
8. CREW MODEL WORK (A3): every model call in the crew modules is classified; each one under a crew agent's name is preceded by
   a stop question with no await between them; the verifier asks at every pick; the session finalizer is given the stop; the
   crew run asks eligibility right before its run entry, so it needs no ``AgentStopped`` catch.
>>>>>>> REPLACE

32.2
<<<<<<< SEARCH
    "invoke", "issue_stop", "lift_stop", "standing_stop", "WorkItemAgenticExecutor", "CrewAssignmentResolver",
}
=======
    "invoke", "issue_stop", "lift_stop", "standing_stop", "WorkItemAgenticExecutor", "CrewAssignmentResolver",
    "CrewSessionFinalizer", "_stopped", "complete",  # A3
}
>>>>>>> REPLACE

32.3
<<<<<<< SEARCH
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge_for_session", "active_stop"): "SEAM_AGENTIC_RUN",
=======
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge_for_session", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer.synthesize_for_session", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_synthesis", "active_stop"): "SEAM_AGENTIC_RUN",
>>>>>>> REPLACE

32.4
<<<<<<< SEARCH
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge_for_session", ("admit_correction", "run")),
=======
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.converge_for_session", ("admit_correction", "run")),
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer.synthesize_for_session", ("complete",)),
    ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_synthesis", ("_claim_owned_synthesis", "synthesize_for_session")),
>>>>>>> REPLACE

32.5 tables
<<<<<<< SEARCH
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.recover_promoted_turn._recovered_pass", "admitted_turn=True"),
})
=======
    ("src/probos/cognitive/cognitive_agent.py", "CognitiveAgent.recover_promoted_turn._recovered_pass", "admitted_turn=True"),
})

# A3 (R1): every model call in the crew modules, by enclosing function, and whose name it runs under.
_CREW_MODEL_CALLS: dict[tuple[str, str], str] = {
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.verify"): "verifier: picked stop-free, re-checked before the call",
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.verify_for_session"): "verifier: picked stop-free, re-checked before the call",
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer.synthesize_for_session"): "facilitator: SEAM_AGENTIC_RUN at the entry",
    ("src/probos/cognitive/crew_synth.py", "CrewSynthesizer._synthesize_output"): "ship: the generic _SYSTEM_PROMPT, no crew identity or instructions",
}
# A3 (R1): the verifier's stop question, and every place that asks it.
_VERIFIER_STOP_SITES: frozenset[tuple[str, str]] = frozenset({
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._pick_independent_verifier"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._pick_department_peer"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._pick_authority_chief"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._pick_live_session_verifier"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.verify"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier.verify_for_session"),
})
_STANDING_STOP_SITES: frozenset[tuple[str, str]] = frozenset({
    ("src/probos/cognitive/crew_assignment.py", "CrewAssignmentResolver.check_eligibility"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._stopped"),
})
>>>>>>> REPLACE

32.6 new tests at the end of the file
<<<<<<< SEARCH
    assert built == {(
        "src/probos/startup/finalize.py", "_wire_crew_orchestrator", ("agent_stops=getattr(runtime, 'agent_stops', None)",),
    )}, built
=======
    assert built == {(
        "src/probos/startup/finalize.py", "_wire_crew_orchestrator", ("agent_stops=getattr(runtime, 'agent_stops', None)",),
    )}, built


def test_every_crew_model_call_is_classified() -> None:
    """I14 (A3): a new model call in a crew module fails here until it is classified."""
    found = {(c.file, c.function) for c in _census() if c.callee == "complete" and c.file.startswith("src/probos/cognitive/crew_")}
    assert found == set(_CREW_MODEL_CALLS), sorted(found ^ set(_CREW_MODEL_CALLS))


def test_each_attributed_crew_model_call_is_checked_with_no_await_between() -> None:
    """I15 (A3): the last stop question before a crew agent's model call has no await between it and the call."""
    for (rel, qualname), how in _CREW_MODEL_CALLS.items():
        if how.startswith("ship:"):
            continue
        fn = _function(rel, qualname)
        model = _first_line(fn, _calls("complete"))
        check = "_stopped" if how.startswith("verifier:") else "active_stop"
        checks = [n.lineno for n in ast.walk(fn) if _calls(check)(n) and n.lineno < model]
        assert checks, (qualname, check)
        between = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Await) and max(checks) < n.lineno < model]
        assert between == [], (qualname, between)


def test_the_verifier_asks_the_stop_at_every_pick_and_judgment() -> None:
    """I15b (A3): removing a verifier stop question fails here as well as in its behaviour test."""
    asked = {(c.file, c.function) for c in _census() if c.callee == "_stopped"}
    assert asked == _VERIFIER_STOP_SITES, sorted(asked ^ _VERIFIER_STOP_SITES)
    standing = {(c.file, c.function) for c in _census() if c.callee == "standing_stop" and c.file != _IMPLEMENTATION}
    assert standing == _STANDING_STOP_SITES, sorted(standing ^ _STANDING_STOP_SITES)


def test_the_session_finalizer_is_given_the_stop() -> None:
    """I16 (A3)."""
    built = {(c.file, c.function, c.keywords) for c in _census() if c.callee == "CrewSessionFinalizer"}
    assert built == {(
        "src/probos/startup/finalize.py", "_wire_crew_orchestrator", ("agent_stops=getattr(runtime, 'agent_stops', None)",),
    )}, built


def test_the_crew_run_asks_eligibility_right_before_its_run_entry() -> None:
    """I17 (A3): CrewTaskExecutor has no AgentStopped catch and needs none. Its eligibility question (synchronous, and its
    answer includes the stop) is the statement right before the awaited run entry, so no stop can land between them."""
    rel = "src/probos/cognitive/crew_executor.py"
    fn = _function(rel, "CrewTaskExecutor._run_agentic_with_outer_loop")
    tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try) and any(_calls("_require_eligible")(m) for s in n.body for m in ast.walk(s))]
    assert len(tries) == 1, len(tries)
    body = tries[0].body
    index = next(i for i, stmt in enumerate(body) if any(_calls("_require_eligible")(n) for n in ast.walk(stmt)))
    after = body[index + 1]
    assert isinstance(after, ast.Assign) and isinstance(after.value, ast.Await), ast.dump(after)
    assert ast.unparse(after.value.value.func) == "self._executor.run"
    assert isinstance(_function(rel, "CrewTaskExecutor._require_eligible"), ast.FunctionDef)  # synchronous
>>>>>>> REPLACE

### Section 33: `tests/test_ad1343_agent_stop_settle.py` (new, whole file)

```python
"""AD-1343 S1 (#1595), amendment A3 (R3, R4): a cancelled issue or lift is settled against what the store holds (S1 to S4).

Cancelling an await on aiosqlite does not stop the call its worker thread was given (``aiosqlite/core.py``: a queued call runs
even after its future is cancelled). Before A3 a cancelled issue was marked unwritten although its COMMIT then landed, and a
cancelled lift left the agent stopped in memory although its row was lifted. These tests pause the REAL worker inside COMMIT: a
test-held SQLite connection keeps a read transaction open, so the service's COMMIT waits for its lock on the worker thread while
the test cancels the caller; then the test ends its read and the COMMIT lands.

* S1: an issue cancelled while its COMMIT is blocked is durable once the COMMIT lands; the re-issue, a lift and a restart agree.
* S2: a lift cancelled while its COMMIT is blocked is applied once the COMMIT lands; the EventLog has the lift; a restart agrees.
* S3: two cancellations during one blocked COMMIT end in one CancelledError and one settled, durable order.
* S4 (golden): with no cancellation the blocked COMMIT simply lands; the issue and the lift each run one statement, no ROLLBACK.

Every store lives in ``tmp_path``; the live data directory is never read. Waits are on events and tasks, bounded by ``_BOUND``;
S3 yields one loop turn so that its first cancellation is delivered before its second. The service's connection keeps SQLite's
default busy timeout (5 s), far above the few loop turns the test holds its read.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from probos.agent_stop import STORE_FILENAME
from probos.substrate.event_log import EventLog
from tests.test_ad1343_agent_stop import AGENT, LIFT_REASON, REASON, _Clock, _FlakyFactory, _service, _stop_rows

_BOUND = 10.0  # seconds: the longest any step here waits; a wedged step raises TimeoutError instead of hanging the run


class _CommitSeen:
    """Test-local connection wrapper: forwards every call; marks each COMMIT just before the real ``commit`` queues it."""

    def __init__(self, inner: Any, seen: asyncio.Event) -> None:
        self._inner = inner
        self._seen = seen

    async def commit(self) -> None:
        self._seen.set()
        await self._inner.commit()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _CommitSeenFactory:
    """The SQLite default behind a ``_FlakyFactory`` (which records statements), with each COMMIT marked."""

    def __init__(self) -> None:
        self.seen = asyncio.Event()
        self._flaky = _FlakyFactory()

    @property
    def statements(self) -> list[str]:
        return self._flaky.statements

    async def connect(self, db_path: str) -> _CommitSeen:
        return _CommitSeen(await self._flaky.connect(db_path), self.seen)


@contextlib.contextmanager
def _read_held(data_dir: Path) -> Iterator[sqlite3.Connection]:
    """A test-held read transaction on ``agent_stops.db``: while it is open the service's COMMIT waits on the worker thread."""
    conn = sqlite3.connect(data_dir / STORE_FILENAME, isolation_level=None)
    try:
        conn.execute("BEGIN")
        conn.execute("SELECT count(*) FROM agent_stops").fetchone()
        yield conn
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.execute("COMMIT")
        conn.close()


# S1
async def test_an_issue_cancelled_while_its_commit_lands_is_durable(tmp_path: Path) -> None:
    factory = _CommitSeenFactory()
    async with _service(tmp_path, connection_factory=factory, clock=_Clock()) as service:
        factory.seen.clear()  # start() committed its schema
        with _read_held(tmp_path) as reader:
            issue = asyncio.create_task(service.issue_stop(AGENT, reason=REASON))
            await asyncio.wait_for(factory.seen.wait(), timeout=_BOUND)
            assert not issue.done()  # premise: the INSERT ran and its COMMIT is on the worker, waiting for the test's read
            issue.cancel()
            reader.execute("COMMIT")  # the read ends: the COMMIT the worker holds can land
            await asyncio.wait({issue}, timeout=_BOUND)
        assert issue.cancelled()  # the caller's cancellation still propagated
        in_force = service.stop_for(AGENT)
        assert in_force is not None
        assert [row["stop_id"] for row in _stop_rows(tmp_path)] == [in_force.stop_id]  # premise: the COMMIT landed
        again = await service.issue_stop(AGENT, reason=REASON)
        assert again.already_stopped is True and again.record == in_force
        assert again.durable is True  # durability is what the store holds, not what the cancellation suggested
        lifted = await service.lift_stop(AGENT, reason=LIFT_REASON)
        assert service.stop_for(AGENT) is None
    assert _stop_rows(tmp_path)[0]["lifted_at"] == lifted.lifted_at  # the lift wrote its row: it did not skip it as unwritten
    async with _service(tmp_path) as restarted:
        assert restarted.stop_for(AGENT) is None


# S2
async def test_a_lift_cancelled_while_its_commit_lands_is_applied(tmp_path: Path) -> None:
    stops = tmp_path / "stops"
    factory = _CommitSeenFactory()
    event_log = EventLog(db_path=tmp_path / "events.db")
    await event_log.start()
    try:
        async with _service(stops, connection_factory=factory, event_log=event_log, clock=_Clock()) as service:
            issued = await service.issue_stop(AGENT, reason=REASON)
            assert issued.durable is True  # premise: written, so the lift writes its row
            factory.seen.clear()
            with _read_held(stops) as reader:
                lift = asyncio.create_task(service.lift_stop(AGENT, reason=LIFT_REASON))
                await asyncio.wait_for(factory.seen.wait(), timeout=_BOUND)
                assert not lift.done()  # premise: the lift's UPDATE ran and its COMMIT waits on the worker
                assert service.stop_for(AGENT) == issued.record  # in force while the lift is written
                lift.cancel()
                reader.execute("COMMIT")
                await asyncio.wait({lift}, timeout=_BOUND)
            assert lift.cancelled()
            assert service.stop_for(AGENT) is None  # R4: the lift that landed is applied in memory
    finally:
        await event_log.stop()
    rows = _stop_rows(stops)
    assert len(rows) == 1 and rows[0]["lifted_at"] is not None and rows[0]["lift_reason"] == LIFT_REASON
    with contextlib.closing(sqlite3.connect(tmp_path / "events.db")) as conn:
        events = [json.loads(data) for (data,) in conn.execute("SELECT data FROM events WHERE event = 'agent_stop_lifted'")]
    assert [event["stop_id"] for event in events] == [issued.record.stop_id]  # the lift's event is kept
    async with _service(stops) as restarted:
        assert restarted.stop_for(AGENT) is None


# S3
async def test_two_cancellations_during_one_commit_settle_it_once(tmp_path: Path) -> None:
    factory = _CommitSeenFactory()
    async with _service(tmp_path, connection_factory=factory, clock=_Clock()) as service:
        factory.seen.clear()
        with _read_held(tmp_path) as reader:
            issue = asyncio.create_task(service.issue_stop(AGENT, reason=REASON))
            await asyncio.wait_for(factory.seen.wait(), timeout=_BOUND)
            issue.cancel()
            await asyncio.sleep(0)  # one loop turn, not a wait on time: the first cancellation is delivered
            assert not issue.done()  # premise: still waiting on the blocked COMMIT
            issue.cancel()
            reader.execute("COMMIT")
            await asyncio.wait({issue}, timeout=_BOUND)
        assert issue.cancelled()
        again = await service.issue_stop(AGENT, reason=REASON)
        assert again.already_stopped is True and again.durable is True
        assert len(_stop_rows(tmp_path)) == 1


# S4 (golden)
async def test_an_uncancelled_write_waits_for_its_commit_and_issues_no_rollback(tmp_path: Path) -> None:
    factory = _CommitSeenFactory()
    async with _service(tmp_path, connection_factory=factory, clock=_Clock()) as service:
        factory.seen.clear()
        mark = len(factory.statements)
        with _read_held(tmp_path) as reader:
            issue = asyncio.create_task(service.issue_stop(AGENT, reason=REASON))
            await asyncio.wait_for(factory.seen.wait(), timeout=_BOUND)
            assert not issue.done()
            reader.execute("COMMIT")
            issued = await asyncio.wait_for(issue, timeout=_BOUND)
        assert issued.durable is True and issued.already_stopped is False
        lifted = await service.lift_stop(AGENT, reason=LIFT_REASON)
        assert lifted.refused == {}
        assert [sql.lstrip().split()[0] for sql in factory.statements[mark:]] == ["INSERT", "UPDATE"]  # no ROLLBACK, no extra
    async with _service(tmp_path) as restarted:
        assert restarted.stop_for(AGENT) is None
```

### Tests (A3)

New files: `tests/test_ad1343_agent_stop_settle.py` (Section 33, whole). The two files below are specified here for the Builder:
- `tests/test_ad1343_agent_stop_verify.py`. Import the rigs of `tests/test_ad1343_agent_stop_crew.py`, and `ontology_dir`, `data_dir`, `ontology`, `_register`, `_FakeLLM`, `_FakeStore`, `_FakeExecutor`, `_result` from `tests/test_ad866_dept_verifier.py`.
- `tests/test_ad1343_stop_crossing_finalizer.py`. Reuse `stores` and `trust_network` from `tests/test_ad1130_outcome_only_room_trust.py:140-157`, and `_executing_case`, `_registry_for`, `_runtime`, `_make_verifier`, `_make_synthesizer` from `tests/test_ad1126_verified_finalization.py`. The finalizer is built as `_recorder_finalizer` builds it (`test_ad1130:232-269`), but constructed directly with `agent_stops=stops`. The runtime gets `runtime.agent_stops = stops` and `runtime.tool_registry.set_stop_gate(stops)`.

Every test has a golden: with no order in force it returns exactly what it did before, and `probos.agent_stop` writes nothing at INFO or above.

| # | File | Must show | RED on staged |
|---|---|---|---|
| S1 | settle | Section 33 | yes (re-issue `durable False`; the lift skips its UPDATE; restart stopped) |
| S2 | settle | Section 33 (R4) | yes (memory still stopped) |
| S3 | settle | Section 33 | yes |
| S4 | settle | golden | no |
| T28′ | lift | one `agent_stop_lifted` event with `{"tool": 1}` | no (guard) |
| T29 (c), (d) | lift | Section 29 | yes |
| T29 (c2), (d2) | lift | Section 29 | no (guard for B5) |
| T33 ×3 | crew | Section 30 | yes (staged returns an outcome) |
| T35 | verify | **R5.** A spy owned-steps port whose `admit_correction` issues the stop, then returns `SimpleNamespace(permit="ad1343-permit-0001", disposition="new")`. It has `correction_execution_lease()` and a `record_correction` that raises. The executor is a real `WorkItemAgenticExecutor` over `_CountingLLM`. Shows: `AgentStopped` raised; exactly one admission; `record_correction` never called; `llm.calls == []`; exactly one WARNING containing "admitted but not executed", with no `exc_info`; counts `{"agentic_run": 1}`. | yes |
| P1 | verify | **Legacy pick, no ontology.** Registry: v1 (stopped), v2, AGENT. `verify` is judged by v2. Golden: v1. Counts `{}`. | yes |
| P2 | verify | **Ontology peer** (the `test_ad866:158` shape). The engineering peer is stopped, so the pick is not that peer; it is the next peer or the chief. | yes |
| P3 | verify | **Chief** (the `test_ad866:180` shape). The chief is stopped; the any-independent pick is not the chief. | yes |
| P4 | verify | **Session pick.** The first candidate is stopped, so the second is picked. With every candidate stopped: `status == "unavailable"`, `failure_code == "independent_verifier_unavailable"`, 0 judge calls. | yes |
| P5 | verify | **Legacy race.** A work-item store whose `get_work_item` issues the stop for the picked verifier. The verdict is `verification_defect=True` with `verifier_agent_id == ""` and 0 judge calls. | yes |
| P6 | verify | **Session race.** The verifier instance's `_build_trace_section` is monkeypatched (test-local, recorded inline) with an async function that issues the stop and returns `""`. The pass is `unavailable` with 0 judge calls. | yes |
| Y1 | verify | **`synthesize_for_session`, stopped facilitator.** `AgentStopped` naming the order (no `PRIVATE_FRAGMENT`), 0 model calls, `{"agentic_run": 1}`. Empty `success_criteria` with a stopped facilitator still raises `ValueError("session_synthesis_input_invalid")`. Golden: one call, the draft returned. | yes |
| X7 | crossing | **R2 through finalization.** Producer stopped before `finalize`; judge script `[refute]`. Result: `state == "blocked_needs_captain"`, `reason == "child_producer_unavailable"`. `trust_network.get_score("producer-1")` is unchanged; `_outbox_rows(stores.work) == []`; one judge call; `refused_counts == {"agentic_run": 1}`. **Parity:** the same rig with the producer's `is_alive=False` ends with the same state, reason, counts and outbox rows. **Control:** the stop service wired with no order repeats `test_ad1130:1107-1137` (reason `convergence_exhausted`, producer beta > 2, 4 trust rows). | yes |
| X8 | crossing | **R1 verifier.** verifier-1 stopped. The child is verified by facilitator-1 (`child.verification["rounds"][0]["verdict"]["verifier_agent_id"] == "facilitator-1"`). The final verification finds no candidate, so the session is blocked `independent_verifier_unavailable`. Judge 1 call, synthesizer 1. No verdict names verifier-1. Golden: verifier-1 judges both and the session completes. | yes (2 judge calls; completes) |
| X9 | crossing | **R1 synthesis.** facilitator-1 stopped. The child is accepted by verifier-1, then the session is blocked `synthesis_producer_unavailable` with 0 synthesizer calls and `{"agentic_run": 1}`. **Race:** a test-local `CrewSynthesizer` subclass whose `synthesize_for_session` issues the stop, then calls `super()`; same outcome. | yes |
| X10 | crossing | **Owned resume, facilitator stopped** (drive `finalizer.resume` as `tests/test_ad1192_owned_steps_finalization.py:353-435` does). Shows `ValueError("synthesis_producer_unavailable")` and 0 synthesizer calls. After the lift, a second `resume` completes and never raises `owned_steps_synthesis_interrupted`. **Race (X10b):** the store's `claim_owned_synthesis` is wrapped to issue the stop, then forward. Same `ValueError`, 0 synthesizer calls. | yes |
| X11 | crossing | **Resume, producer stopped, round 0 refuted.** Ends exactly as the same resume with the producer `is_alive=False` (`ValueError("child_producer_unavailable")`), with no trust-outbox row. | yes |
| I14–I17 | inventory | Section 32 | yes (I14–I16) |

If a rig cannot take the stop service without changing its helper, add a test-only keyword with default `None` to that helper. Do not copy the helper. If the X6 golden cannot reach the model with its rig, stop and report.

**Existing tests that change:**
- `test_ad1343_agent_stop_lift.py`: T28, T29.
- `test_ad1343_agent_stop_crew.py`: three T33 tests, the docstring, and `_escalated_unverified` removed.
- `test_ad1343_stop_crossing_crew.py`: X6.
- `test_ad1343_stop_seam_inventory.py`.

**Checked; no change needed:**
- `test_ad1155_loop_until_done.py:573-586`: A3 adds no `token_budget`, `compactor` or `AD-1155` text.
- `test_ad1130:1549-1567`: no `.verify`, `.synthesize` or `.record_outcome` attribute call is added to `crew_finalizer.py`.
- `test_ad1126:6104-6126`: the annotations of `verify_for_session`, `converge_for_session` and `synthesize_for_session` are unchanged, and `CrewSessionFinalizer.__init__` is not pinned (`grep` of tests: none).
- `test_bf777:441` monkeypatches the picker.
- `test_ad866` passes `runtime=SimpleNamespace()`: no `agent_stops`, so `_stopped` is False.
- No test touches `_write_issued`, `_commit_or_roll_back` or `_write_final_counts` (`grep` → only `EventLog._rollback_quietly` in `bf873`).
- `S1_SCOPE` is compared as a constant (`test_ad1343_agent_stop.py:672-801`).

**Focused gate:**
`pytest tests/test_ad1343_*.py tests/test_ad866_dept_verifier.py tests/test_ad860_crew_verifier.py tests/test_bf777_bf778_verifier_trust.py tests/test_ad1126_verified_finalization.py tests/test_ad1127_crew_session_lifecycle_recovery.py tests/test_ad1130_outcome_only_room_trust.py tests/test_ad1192_owned_steps_finalization.py tests/test_ad1282_verifier_credit_full_chain.py tests/test_ad1155_loop_until_done.py tests/test_ad859_crew_executor.py tests/test_ad1195_eventlog_pair_freeze.py -n 0`

Then the preflights. `check_architecture_principles.py --check` must report srp-size 92, and both baselines must be byte-identical (`git diff --exit-code docs/development/*baseline*.yaml`).

### Mutation rows (A3; whole stripped lines, unique per file)

| ID | File: anchor → mutant | Killed by |
|---|---|---|
| B1 | agent_stop.py `await asyncio.shield(write)` → `await write` | S1, S2, S3 |
| B2 | agent_stop.py `cancellation = cancellation or exc` → `raise` | S2, S3 |
| B3 | agent_stop.py `raise cancellation  # A3: held until the order, its durability and its event were settled` → `pass` | S1 (`issue.cancelled()`) |
| B4 | agent_stop.py `raise cancellation  # A3: held until the lift, its counts and its event were settled` → `pass` | S2 |
| B5 | agent_stop.py `raise cancellation from failure  # rolled back: the agent stays stopped, and the caller is still cancelled` → `raise failure` | T29 (c2) |
| B6 | agent_stop.py `return True, cancellation` → `return False, cancellation` | T1, S1 |
| V1 | crew_verifier.py `if agent_id and agent_id != producer_id and not self._stopped(agent_id):  # A3 (R1): never a stopped agent` → without `and not self._stopped(agent_id)` | P1 |
| V2 | crew_verifier.py `if self._stopped(agent_id):  # A3 (R1): a stopped department peer is passed over` → `if False:` | P2 |
| V3 | crew_verifier.py `if self._stopped(cand_id):  # A3 (R1): a stopped chief is passed over` → `if False:` | P3 |
| V4 | crew_verifier.py `if self._stopped(candidate_id):  # A3 (R1): a stopped colleague is never picked` → `if False:` | P4, X8 |
| V5 | crew_verifier.py `if self._stopped(verifier_id):  # A3 (R1): stopped while its prompt was built; nothing is judged under its name` → `if False:` | P5 |
| V6 | crew_verifier.py `if self._stopped(verifier_id):  # A3 (R1): stopped while its prompt was built (session); nothing is judged` → `if False:` | P6 |
| V7 | crew_verifier.py `return standing_stop(getattr(self._runtime, "agent_stops", None), agent_id) is not None` → `return False` | P1–P6, X8 |
| V8 | crew_verifier.py `raise AgentStopped(stopped)  # A3 (R2): before admission, so nothing was admitted or executed` → `pass` | T33 owned (the port is asked again) |
| V9 | crew_verifier.py `raise  # A3 (R2): the finalizer blocks the session as for a producer that is not available` → `return None` | T33 race (session) |
| V10 | crew_verifier.py `if correction_permit is not None:` → `if False:` | T35 |
| A18′ | crew_verifier.py `stopped = active_stop(getattr(self._runtime, "agent_stops", None), current.agent_id, SEAM_AGENTIC_RUN)` → `stopped = None` | T33 owned |
| Y1m | crew_synth.py `raise AgentStopped(stopped)` → `pass` | Y1, X9 |
| Y2m | crew_synth.py `stopped = active_stop(getattr(self._runtime, "agent_stops", None), producer_key, SEAM_AGENTIC_RUN)` → `stopped = None` | Y1, X9 |
| F1 | crew_finalizer.py `if facilitator is None or active_stop(self._agent_stops, session.facilitator_id, SEAM_AGENTIC_RUN) is not None:` → `if facilitator is None:` | X10 |
| F2 | crew_finalizer.py `raise ValueError("synthesis_producer_unavailable") from exc` → `raise` | X10b |
| F3 | crew_finalizer.py `raise ValueError("child_producer_unavailable") from exc` → `raise` | X11 |
| F4 | crew_finalizer.py `except AgentStopped:  # A3 (R2): the producer was stopped before its correction; no outcome, no exhaustion` → `except ZeroDivisionError:` | X7 |
| F5 | crew_finalizer.py `except AgentStopped:  # A3 (R1): the facilitator is stopped; nothing was synthesized, as a facilitator not live` → `except ZeroDivisionError:` | X9 |
| F6 | crew_finalizer.py `self._agent_stops = agent_stops  # AD-1343 A3: a stopped facilitator's synthesis is not claimed` → `self._agent_stops = None` | X10 |
| HB1 | finalize.py `agent_stops=getattr(runtime, "agent_stops", None),  # AD-1343 A3: a stopped facilitator's synthesis is not claimed` → removed (HAND, wiring) | I16 |
| HB2 | agent_stop.py `cancellation = await self._write_final_counts(record, refused) or cancellation` → without `or cancellation` (HAND: a cancellation during the second write; no test pauses it) | review |
| HB3 | agent_stop.py `_write_final_counts`'s `if failure is not None:` → raise it (HAND: log-and-degrade) | T28 |

Retired A2 rows:
- **A5, A19, A20:** their lines are removed.
- **A4** (`except BaseException:` → `except Exception:` in `_commit_or_roll_back`): equivalent under A3, because the caller never cancels the write's task. It becomes a HAND row (closing-loop only).
- **HA3:** replaced by HB3.
- **A18:** retargeted to A18′.

**Campaign of record:** rerun every A-row and R-row on `agent_stop.py` and `crew_verifier.py`, then the B, V, Y and F rows. All other rows stand.

### Diff Reviewer: properties to verify (delta)

- **P3 (amended).** With no order and no cancellation, every changed path returns exactly what it did before and issues the same SQL: one statement per write and no ROLLBACK after a commit that landed (S4). There is no new INFO or higher line.
- **P13 (replaced).** `AgentStopped` never surfaces as a fault, retry or trust write:
  - session correction → blocked `child_producer_unavailable`, with no `ChildVerificationRecord`, no checkpoint and no trust effect;
  - legacy correction → the existing unverified escalation;
  - facilitator → blocked `synthesis_producer_unavailable`;
  - verifier → never picked, or the existing unavailable outcome.

  No persisted shape or vocabulary changes, and genuine exhaustion is charged exactly as before (X7 control).
- **P14 (replaced).** Each stop write runs to its end whatever happens to its caller. Memory follows what the store holds. A held cancellation is raised once the bookkeeping is settled. A failed write with a cancelled caller raises `CancelledError` caused by the failure, and the agent stays stopped.
- **P16 (new).** Every crew model call under a crew agent's name follows a stop question with no await between them (I15). Verifier questions are not counted. The facilitator is counted once, at `agentic_run`.
- **P17 (new, a recorded residual).** A correction admitted in an owned session just before the stop keeps its permit and logs one WARNING. A retry after the lift fails closed as the existing interrupted-correction replay, with no trust effect.
- **P9 (extended).** srp-size 92; `CrewSynthesizer` gains no method; both baselines are byte-identical.

### Decisions

| # | Decision | Rejected | Envelope |
|---|---|---|---|
| D29 | R1 is S1 scope. Verifier candidates and judgments ask `_stopped` (memory only, not counted); the facilitator is refused at the `synthesize_for_session` entry (`agentic_run`); `SEAMS` does not grow | A new `verification` seam (it refuses no work of the agent's own; a colleague verifies); changing `_live_agent` (that would invalidate replayed verdicts via `_validate_verifier_identity`, `crew_finalizer.py:3267`) | Architect |
| D30 | R2 option A: the session correction raises; the finalizer maps it to the existing `child_producer_unavailable` (blocked), fresh and resume | C, a new failure code (breaks downgrade; Captain); B, inference (fragile); D, relabelling (dishonest) | Architect |
| D31 | The finalizer is given `agent_stops` by constructor injection; the resume checks the facilitator before the owned synthesis is claimed | Reaching into the synthesizer's runtime (Demeter); a new `CrewSynthesizer` method (the 16th method trips its srp `methods` trigger) | Architect |
| D32 | R3 and R4: `_write_settled` (the AD-1198 A-1 pattern), unbounded; memory is applied from the settled outcome; R4 is fixed, not filed | Rolling back on cancellation (cannot undo a landed COMMIT); a time bound (needs a third "unknown" durability state S1 lacks) | Architect |
| D33 | A held cancellation completes the event and final counts, then is raised | Skipping the bookkeeping (loses the audit of a lift that happened) | Architect |
| D34 | R5 wording; WARNING after admission. The orphan-permit replay residual is recorded on #1523 | A new owned-steps "release permit" transition (a shared contract outside S1) | Architect |
| D35 | No `AgentStopped` catch in `CrewTaskExecutor`; the adjacency is pinned (I17) | A catch mapped to `crew_worker_identity_lost` (unreachable, wrong label) | Architect |
| D36 | `S1_SCOPE["refuses"]` reworded for verification and synthesis | — | Architect |
| D37 | X6's golden runs the executor; T29 (c) and (d) premise corrected and split | — | Architect |
| D38 | Round 3 is whole-candidate (shared contracts change: the `converge_for_session` raise, `CrewSessionFinalizer.__init__`, the stop writes) | Delta review | Architect |

### Verified Against Codebase (2026-10-19, staged tree `f812eae4`)

- `agent_stop.py:143-159` (helpers), `338-362` (issue), `364-394` (lift), `396-427` (writers), `75-96` (scope).
- `crew_verifier.py`:
  - `verify` 1417-1486 (pick 1430, trace 1448-1450, model 1458);
  - `verify_for_session` 1833-1924 (pick 1842, unavailable 1861-1870, trace 1883-1885, model 1886);
  - `converge_for_session` 1926/1939 (docstring), pre-check 1995-1997, admission 2063-2105, `except` 2136-2139;
  - `_producer_stopped_outcome` 2289-2306; pickers 2332-2358 and 2801-2901; import :58.
- `crew_synth.py`: imports 49-50; methods 718-1305 (15 direct methods); `synthesize_for_session` 886-1001 (prompt 978, model 980); `_SYSTEM_PROMPT` 725.
- `crew_finalizer.py`:
  - imports 25-26; `__init__` 687-737;
  - `_convergence_failure_trust_effects` 1041-1063; `_resume_child_convergence` 1611-1696;
  - `_resume_synthesis` 1960-2028 (claim 2012); `_finalize_claimed` 2598-2888 (2624-2632, 2683-2724, 2834-2888);
  - `_live_agent` 3124-3141; `_validate_verifier_identity` 3254-3269; `_outcome_failure` 3450-3460; validator 552-623.
- `crew_trust.py:361-420`.
- `finalize.py:2205, 2220-2228, 2298-2318, 2321`; `runtime.py:3265`; `crew_executor.py:1985-1988, 2150-2161`.
- `aiosqlite/core.py:32-41, 48-75, 150-160` (venv); `federation/envelope.py:339-358`.
- `architecture-baseline.yaml:1-6, 442-501`; `check_architecture_principles.py:187-188, 195-200`.
- `tests/test_ad1343_agent_stop_lift.py:1-323`, `tests/test_ad1343_agent_stop_crew.py:1-476`, `tests/test_ad1343_stop_crossing_crew.py:1-105`, `tests/test_ad1343_stop_seam_inventory.py:1-329`, `tests/test_ad1343_agent_stop.py:69-197`.
- `tests/test_ad1130_outcome_only_room_trust.py:140-269, 1107-1137, 1549-1567`; `tests/test_ad1126_verified_finalization.py:200-226, 579-593, 725-739, 902-1024, 6104-6126`; `tests/test_ad866_dept_verifier.py:128-176`; `tests/test_ad1155_loop_until_done.py:573-586`.

### Absence Verified (2026-10-19)

| Claim | Run | Found | Holds |
|---|---|---|---|
| No other model call in the crew modules | grep `\.complete\(` in `src/probos/cognitive/crew_*.py` | `crew_synth` 980, 1024; `crew_verifier` 1458, 1886 | yes |
| No other caller of the session verify, converge or synthesize | grep `verify_for_session\(\|converge_for_session\(\|synthesize_for_session\(` src | finalizer 1673, 2013, 2129, 2684, 2858, 2912; verifier 1965, 2258 | yes |
| Base never wrote a stop-caused exhaustion | `git show 45058ae7:…/crew_verifier.py \| grep -c "_producer_stopped_outcome\|agent_stop"` | 0 | yes |
| Base already writes both blocked reasons | `git show 45058ae7:…/crew_finalizer.py \| grep -n producer_unavailable` | 1656, 2006, 2628, 2647, 2838, 2852 | yes |
| No `_stopped(` call in src today | grep | none | yes |
| No test pins the changed private stop internals | grep tests `_write_issued\|_commit_or_roll_back\|_write_final_counts\|_volatile` | `bf873` (EventLog's own `_rollback_quietly`) only | yes |
| One `CrewSessionFinalizer(` construction in src | grep | `finalize.py:2298` | yes |
| Production crew executors always get the resolver | grep `eligibility_resolver=` src | `finalize.py:2228, 2321` | yes |

### Prior Art and Blind Spots

This is a repair of ProbOS plumbing, so no external search was made. Internal prior art adopted: AD-1198 A-1 shield-and-wait (`federation/envelope.py:339-358`, `startup/fleet_organization.py:81-85`), deliberately without its time bound (D32).

Blind spots, recorded:
- The orphan permit after admission (D34).
- A resume re-judges round 0 once (D30).
- A stopped verifier whose model call had already started finishes its verdict: S2, in flight.
- Non-crew model sites are classified by a grep bound, not site by site (D29).
