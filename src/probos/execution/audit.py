"""AD-1280: the one place an execution audit record is built.

AD-1247 gave the agentic ``CodeExecutionTool`` path a per-execution
``code_execution`` record. BF-787 (#1251) gave the mesh ``CodeRunnerAgent``
path the same record. This module holds the single definition both call, so a
future security fix to any of the decisions below lands once instead of twice
-- the same reasoning BF-856 used when it collapsed ``error_signature`` and
``ToolDefect.signature`` onto a shared digest: two parallel edits can drift, a
shared definition cannot.

**What counts as an execution.** A record is written for a run of source the
AGENT AUTHORED, and for nothing else. The mesh path can reach ``sandbox.run``
three times in one ``run_python`` turn -- venv creation, ``pip install``, then
the script -- and only the script produces a record. The venv and pip argv are
fixed and this codebase wrote them; the agent chose package *names*, not code.
The record's fields are built around submitted source (``code_sha256``,
``code_chars``), so a record whose digest is the hash of ``""`` would be a
false artifact in the trail. ``install_package``, which runs no script at all,
therefore produces no record: an execution entry for something that executed no
submitted source corrupts the trail in the same way a record for a run that
never started does, which is what the ``launch_state`` guard below exists to
prevent. An install-specific record would be a different category and a
different issue.

**Why both paths can reach ``unknown``.** ``sandbox.run`` hands work to an
executor thread and cancelling the awaiting task does not stop that thread, so
a turn torn down mid-flight leaves the launch question genuinely open on either
path -- the mesh agent's ``handle_intent`` is awaited from the bus and unwinds
through its ``await sandbox.run(...)`` exactly as the tool's ``invoke`` does.
``launch_state`` must therefore come from ``LaunchOutcome``, never from the
caller's intent.

The absence warning is per-INSTANCE, not per-module: each call site holds its
own ``ExecutionAuditor``. Module-level mutable state would leak across tests
and would make the tool's warn-once behaviour depend on whether a mesh agent
had already warned.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# AD-1247: the exact keys an execution audit record may carry. The submitted
# source is represented by a DIGEST and never by its text: code an agent runs
# can contain credentials it was legitimately given, and an audit trail is the
# wrong place to copy them to.
AUDIT_DETAIL_ALLOWLIST: frozenset[str] = frozenset({
    "execution_id",
    "agent_id",
    "launch_state",
    "code_sha256",
    "code_chars",
    "success",
    "exit_code",
    "timed_out",
    "timeout_seconds",
    "duration_ms",
    "artifact_count",
    "fetch_broker",
    "error_type",
    # AD-1278: whether this record was ADMITTED to the durable stream --
    # "queued" or "memory-only". Deliberately not "durable": a record cannot
    # attest its own durability, because it is written before the writer
    # commits. What attests durability is the presence of its row in SQLite,
    # and that evidence lives in the DB rather than in the record.
    "stream",
})

# AD-1247: how long the abnormal path waits for the executor thread to answer
# the launch question. Cancelling the awaiting task does not cancel that thread,
# so without this a script that is about to spawn is recorded as never having
# run. Bounded because it briefly blocks the loop, and only reached when a run
# is torn down before `sandbox.run` returned.
LAUNCH_RESOLVE_SECONDS = 2.0


class ExecutionAuditor:
    """Builds and appends one ``code_execution`` record per execution.

    Constructed with the runtime rather than the sink, and reads
    ``audit_log`` off it per call, so a deployment that never wires the sink
    and one that wires it late behave the same way they did when this logic
    lived inside the tool.
    """

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        # AD-1247: warn once per instance that execution is running untrailed,
        # rather than on every run.
        #
        # AD-1280 made that "once per EXECUTION PATH" rather than once per
        # process, because the tool and the mesh agent each hold their own
        # auditor. That is deliberate, not a leak: an operator who sees only
        # the agentic warning would reasonably conclude the mesh path was
        # trailed, and the whole point of this warning is that an untrailed
        # path must not be silent. Two paths running untrailed is two facts.
        # A process-wide sentinel would report the first and hide the second.
        self._absence_warned = False

    def record(
        self,
        *,
        execution_id: str,
        agent_id: str,
        code: str,
        timeout_seconds: float,
        duration_ms: float,
        launch_state: str,
        result: Any = None,
        artifact_count: int | None = None,
        fetch_broker: bool = False,
        error_type: str | None = None,
    ) -> str:
        """Record an execution attempt against the accountability trail (AD-1247).

        BF-763 established that the agentic ``run_python`` path has no quorum
        gate and, by the Captain's decision, should not acquire one -- a
        foreground coding agent does not vote before each command. What a
        foreground agent pays for that freedom is a human watching it. This
        record is what an unattended agent pays instead, so it is not
        decoration: it is the control that makes the capability defensible
        (Design Principle #13).

        AD-1278 states that control's limit rather than leaving it implied: it
        is durable-PREFERRED, not durable-required. With the sink absent, its
        durable stream ended, or shutdown torn down before the writer flushed,
        the run still happens and the record is best-effort -- in memory only,
        and gone at process exit. Requiring a durable sink would not fix that
        (the losses happen AFTER a successful append) and would buy the
        appearance of a guarantee at real availability cost.

        So this method returns what it can actually OBSERVE -- admission to the
        durable stream -- and never durability, which is decided later by a
        writer this synchronous call does not wait for:

        * ``"queued"`` -- accepted into an open durable stream. The healthy
          path; callers suppress it.
        * ``"in-memory-only"`` -- there is no durable stream: persistence off,
          the stream ended after repeated sink failures, or the writer closed.
          This record dies at process exit.
        * ``"absent"`` -- there is no audit sink at all.
        * ``"unconfirmed"`` -- the append raised; the sink may or may not hold it.
        * ``""`` -- ``launch_state`` says nothing ran, so no record was written.

        Waiting for the commit was considered and rejected: it would couple
        every execution's latency to a disk write and contradict the swallow
        below. Amending the label afterwards is impossible -- the result has
        already been returned. What covers a run that was queued and then died
        in an abandoned batch is that the stream ENDS rather than skipping, and
        the ERROR names the sequence.

        A run with no durable trail has to say so where a reader looks, not only
        in a log line nobody reads.

        ``launch_state`` must come from the sandbox's launch outcome, never
        from the caller's intent. ``"launched"`` means a child was confirmed to
        exist; ``"unknown"`` means the run was torn down before the sandbox
        could answer and a script MAY have run; anything else writes nothing. A
        record for a run that never started corrupts the trail in the opposite
        direction to a missing one, so the uncertain case is labelled rather
        than guessed either way.

        Swallows ``Exception`` from the sink -- an audit write that could fail
        an execution would turn the accountability trail into a new way to lose
        work. It does NOT swallow ``BaseException``: a cancellation arriving
        mid-append belongs to the turn, not to this record, and the caller sets
        its attempted-flag BEFORE calling so such an unwind cannot produce a
        duplicate.
        """
        if launch_state not in ("launched", "unknown"):
            return ""
        audit = getattr(self._runtime, "audit_log", None)
        if audit is None:
            # AD-1247 acceptance 6: the sink is gated by
            # `security_infra.audit_enabled`, so a deployment can run code with
            # no trail. That is allowed -- requiring a sink would make auditing
            # a new way for execution to fail -- but it must not be SILENT, and
            # no docstring may claim a record this can switch off. Warned once
            # per auditor instance so a long-running vessel does not spam.
            if not self._absence_warned:
                self._absence_warned = True
                logger.warning(
                    "AD-1247: code executed with no audit sink "
                    "(security_infra.audit_enabled is off), so this run and "
                    "any that follow leave no accountability record. Execution "
                    "is unaffected; enable audit to restore the trail.",
                )
            return "absent"
        # Read BEFORE the append and from the sink itself: the answer has to be
        # inside the record as well as returned to the caller, and a sink that
        # predates AD-1278 (or a double) answers no. It reports ADMISSION, not
        # commitment -- claiming disk from a call that returns before the writer
        # touches it is the failure this whole AD exists to stop.
        predicate = getattr(audit, "durable_stream_open", None)
        stream_open = bool(predicate()) if callable(predicate) else False
        detail: dict[str, Any] = {
            "execution_id": execution_id,
            "agent_id": agent_id or "unknown",
            "launch_state": launch_state,
            "stream": "queued" if stream_open else "memory-only",
            "code_sha256": hashlib.sha256(code.encode("utf-8", "replace")).hexdigest(),
            "code_chars": len(code),
            "timeout_seconds": float(timeout_seconds),
            "duration_ms": round(float(duration_ms), 1),
            "fetch_broker": bool(fetch_broker),
        }
        # AD-1247: OMITTED rather than defaulted to 0. A run torn down partway
        # through artifact capture had already persisted one artifact while the
        # record said zero -- an acknowledged absence beats a false count, which
        # is this AD's whole premise.
        if artifact_count is not None:
            detail["artifact_count"] = int(artifact_count)
        if result is not None:
            detail["success"] = bool(getattr(result, "success", False))
            detail["exit_code"] = getattr(result, "exit_code", None)
            detail["timed_out"] = bool(getattr(result, "timed_out", False))
        if error_type:
            detail["error_type"] = str(error_type)[:80]
        # The browser tool (AD-706) filters at runtime and deviating to save
        # three lines was not worth it. A test asserting the emitted record is
        # release-time detection; this is a production boundary. Note it bounds
        # KEYS only -- a leak inside an allowed VALUE is a separate problem,
        # which is why `error_type` is a class name and never `str(exc)`: an
        # exception message can carry script source, a path, or a credential,
        # and 80 characters of it is a size bound rather than sanitisation.
        for key in list(detail):
            if key not in AUDIT_DETAIL_ALLOWLIST:
                detail.pop(key, None)
        try:
            audit.append(
                category="code_execution",
                detail=json.dumps(detail, sort_keys=True, default=str),
            )
        except Exception:
            logger.warning(
                "AD-1247: audit append did not complete for agent=%s "
                "(execution %s); the execution itself is unaffected, but "
                "whether this run reached the accountability trail is "
                "UNCONFIRMED -- the sink may have stored the entry before "
                "raising",
                agent_id, execution_id, exc_info=True,
            )
            return "unconfirmed"
        return "queued" if stream_open else "in-memory-only"
