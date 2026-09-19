"""AD-1205: bounded, process-local observations; publication stays with the store."""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
import uuid
from collections import Counter, OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from probos.fault_report import (
    FaultReport,
    ToolDefect,
    canonical_tool_id,
    detect_tool_defect,
)
from probos.tools.protocol import ToolResult

logger = logging.getLogger(__name__)

MAX_FAULT_CANDIDATES = 1024
FAULT_WINDOW_SECONDS = 3600.0
FAULT_DISTINCT_TURNS = 3
_SIGNATURE = re.compile(r"[0-9a-f]{64}")
_NOISE = frozenset({
    "permission_denied", "cancelled", "ambiguous_tool", "invalid_params",
    "aborted_by_hook",
})


class ToolFaultDisposition(Enum):
    ORDINARY = "ordinary"
    NEUTRAL = "neutral"


class ToolFaultAdapterKind(Enum):
    MCP = "mcp"
    BROWSER = "browser"


@runtime_checkable
class ToolFaultAdapterQuery(Protocol):
    def tool_fault_adapter_kind(self, tool_id: str) -> ToolFaultAdapterKind | None: ...


class ToolFaultCapture:
    """One run's bounded non-invocation facts, captured before result rendering."""

    def __init__(
        self, *, adapter_kind: Callable[[str], ToolFaultAdapterKind | None],
    ) -> None:
        if not callable(adapter_kind):
            raise TypeError("fault_capture_adapter_query_invalid")
        self._adapter_kind = adapter_kind
        self._calls: dict[str, tuple[str, ToolFaultDisposition]] = {}
        self._failed = False

    def fail(self) -> None:
        if not self._failed:
            logger.warning(
                "AD-1205: raw tool disposition capture is unavailable; this "
                "run contributes no health evidence and legacy filing stays suppressed"
            )
            self._failed = True

    def record(self, request_id: str, observed_name: str, raw_result: ToolResult) -> None:
        if self._failed:
            return
        try:
            if (
                type(request_id) is not str or not 0 < len(request_id) <= 128
                or type(observed_name) is not str or not 0 < len(observed_name) <= 128
                or request_id in self._calls
                or len(self._calls) >= MAX_FAULT_CANDIDATES
                or not isinstance(raw_result, ToolResult)
            ):
                raise ValueError("fault_capture_call_invalid")
            kind = self._adapter_kind(observed_name)
            if kind is not None and type(kind) is not ToolFaultAdapterKind:
                raise ValueError("fault_capture_adapter_kind_invalid")
            disposition = ToolFaultDisposition.ORDINARY
            metadata = raw_result.metadata
            output = raw_result.output
            if (
                kind is ToolFaultAdapterKind.MCP
                and raw_result.error == "requires_confirmation"
                and type(metadata) is dict
                and metadata.get("mcp_tier") == "confirm"
                and metadata.get("outcome") == "requires_confirmation"
            ):
                disposition = ToolFaultDisposition.NEUTRAL
            elif (
                kind is ToolFaultAdapterKind.BROWSER
                and raw_result.error is None
                and type(output) is dict and type(metadata) is dict
                and output.get("intervention_required") is True
                and type(output.get("tier")) is int and output["tier"] == 3
                and type(metadata.get("tier")) is int and metadata["tier"] == 3
                and type(output.get("session_id")) is str and output["session_id"]
                and output["session_id"] == metadata.get("session_id")
            ):
                disposition = ToolFaultDisposition.NEUTRAL
            self._calls[request_id] = (observed_name, disposition)
        except Exception:
            # Diagnostic collaborators cannot change the tool result or its events.
            self.fail()

    def validate(self) -> None:
        if (
            type(self) is not ToolFaultCapture or self._failed
            or len(self._calls) > MAX_FAULT_CANDIDATES
        ):
            raise ValueError("fault_capture_unavailable")

    def is_neutral(self, request_id: str, observed_name: str) -> bool:
        self.validate()
        captured = self._calls.get(request_id)
        if captured is None:
            # An invocation exception has no raw result and is still ordinary
            # error evidence; it cannot have returned a success-shaped refusal.
            return False
        if captured[0] != observed_name:
            self.fail()
            raise ValueError("fault_capture_identity_mismatch")
        return captured[1] is ToolFaultDisposition.NEUTRAL


def _valid_defect(value: Any) -> bool:
    return (
        type(value) is ToolDefect
        and type(value.tool_id) is str and 0 < len(value.tool_id) <= 128
        and type(value.error_text) is str and len(value.error_text) <= 2000
        and type(value.error_key) is str and 0 < len(value.error_key) <= 2000
        and bool(value.error_key.strip())
        and type(value.observed_as) is str and len(value.observed_as) <= 128
        and type(value.count) is int and 1 <= value.count <= 1_000_000
    )


@dataclass(frozen=True)
class FaultObservationResult:
    """Handled observation, not a persistence receipt; empty IDs are failed attempts."""

    attempts: tuple[tuple[str, str], ...] = ()
    failed: bool = False

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if (
            type(self) is not FaultObservationResult
            or type(self.failed) is not bool
            or type(self.attempts) is not tuple
            or len(self.attempts) > MAX_FAULT_CANDIDATES
        ):
            raise ValueError("fault_observation_result_invalid")
        seen: set[str] = set()
        for entry in self.attempts:
            if (
                type(entry) is not tuple or len(entry) != 2
                or type(entry[0]) is not str or not _SIGNATURE.fullmatch(entry[0])
                or type(entry[1]) is not str or len(entry[1]) > 128
                or entry[0] in seen
            ):
                raise ValueError("fault_observation_attempt_invalid")
            seen.add(entry[0])

    def fault_id(self, signature: str) -> str:
        self.validate()
        return dict(self.attempts).get(signature, "")


@dataclass(frozen=True)
class ToolFaultEvidence:
    tool_id: str
    defect: ToolDefect | None = None
    succeeded: bool = False
    mixed: bool = False

    def validate(self) -> None:
        if (
            type(self) is not ToolFaultEvidence
            or type(self.tool_id) is not str or not 0 < len(self.tool_id) <= 128
            or type(self.succeeded) is not bool or type(self.mixed) is not bool
            or not (self.succeeded or self.mixed or self.defect is not None)
            or (
                self.defect is not None
                and (not _valid_defect(self.defect) or self.defect.tool_id != self.tool_id)
            )
        ):
            raise ValueError("fault_run_evidence_invalid")


@dataclass(frozen=True)
class ToolFaultBatch:
    tools: tuple[ToolFaultEvidence, ...] = ()
    same_run: ToolDefect | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if (
            type(self) is not ToolFaultBatch or type(self.tools) is not tuple
            or len(self.tools) > MAX_FAULT_CANDIDATES
            or (
                self.same_run is not None
                and (not _valid_defect(self.same_run) or self.same_run.count < 2)
            )
        ):
            raise ValueError("fault_batch_invalid")
        seen: set[str] = set()
        for item in self.tools:
            if type(item) is not ToolFaultEvidence:
                raise ValueError("fault_run_evidence_invalid")
            item.validate()
            if item.tool_id in seen:
                raise ValueError("fault_batch_duplicate_tool")
            seen.add(item.tool_id)


@dataclass
class _BatchTool:
    defect: ToolDefect | None = None
    succeeded: bool = False
    mixed: bool = False


def collect_tool_fault_batch(
    outcome: Any, *, classify_error: Callable[[Any], str | None],
    resolve_tool_id: Callable[[str], str] | None = None,
    denied_tools: Iterable[str] = (),
    fault_capture: ToolFaultCapture | None = None,
) -> ToolFaultBatch:
    """Project only unique, correlated completed calls; never retain raw pairs."""
    if fault_capture is not None:
        if type(fault_capture) is not ToolFaultCapture:
            raise ValueError("fault_capture_invalid")
        fault_capture.validate()
    calls = getattr(outcome, "tool_calls", ())
    results = getattr(outcome, "tool_results", ())
    if not isinstance(calls, (list, tuple)) or not isinstance(results, (list, tuple)):
        raise ValueError("fault_run_pairs_invalid")
    call_counts = Counter(
        call.id for call in calls
        if type(getattr(call, "id", None)) is str and call.id
    )
    result_counts = Counter(
        result.id for result in results
        if type(getattr(result, "id", None)) is str and result.id
    )
    by_id = {
        call.id: call for call in calls
        if type(getattr(call, "id", None)) is str and call.id
        and call_counts[call.id] == 1
    }
    denied = set(denied_tools)
    same_run = detect_tool_defect(outcome, resolve_tool_id=resolve_tool_id)
    same_run_count = 0
    states: dict[str, _BatchTool] = {}
    overflow = False
    for result in results:
        ident = getattr(result, "id", None)
        call = by_id.get(ident) if type(ident) is str else None
        name = getattr(call, "name", None)
        failed = getattr(result, "is_error", None)
        if (
            call is None or result_counts[ident] != 1
            or type(name) is not str or not name
            or type(failed) is not bool
            or getattr(result, "name", name) != name
        ):
            logger.warning(
                "AD-1205: uncorrelatable tool outcome skipped; it is neither "
                "fault nor success evidence, so diagnosis continues without it"
            )
            continue
        canonical = canonical_tool_id(name, resolve_tool_id)[:128]
        raw = getattr(result, "output", None)
        defect = None
        if failed:
            if type(raw) is not str:
                logger.warning(
                    "AD-1205: non-text tool error skipped; no error identity "
                    "can be established, so it contributes no diagnostic vote"
                )
                continue
            defect = ToolDefect(
                tool_id=canonical, error_text=raw, count=1,
                observed_as="" if name == canonical else name,
            )
            if not _valid_defect(defect):
                logger.warning(
                    "AD-1205: empty or invalid tool error skipped; no diagnostic "
                    "vote or success reset is inferred"
                )
                continue
            if same_run is not None and defect.signature == same_run.signature:
                same_run_count += 1
        # Legacy counting above is unchanged. Non-invocations affect neither
        # failures nor success resets in the separate cross-turn health lane.
        if (
            (fault_capture is not None and fault_capture.is_neutral(ident, name))
            or name in denied or canonical in denied
            or (failed and classify_error(raw) in _NOISE)
        ):
            continue
        if canonical not in states:
            if len(states) >= MAX_FAULT_CANDIDATES:
                if not overflow:
                    logger.warning(
                        "AD-1205: run evidence reached its tool bound; further "
                        "tools are omitted from diagnosis, not from execution"
                    )
                    overflow = True
                continue
            states[canonical] = _BatchTool()
        state = states[canonical]
        if not failed:
            state.succeeded = True
        elif defect is not None:
            if state.defect is None:
                state.defect = defect
            elif state.defect.signature != defect.signature:
                state.mixed = True
    return ToolFaultBatch(
        tools=tuple(
            ToolFaultEvidence(
                tool_id=tool_id, defect=state.defect, succeeded=state.succeeded,
                mixed=state.mixed,
            )
            for tool_id, state in states.items()
            if state.defect is not None or state.succeeded
        ),
        same_run=same_run if same_run_count >= 2 else None,
    )


class ToolFaultTurn:
    """One owning operation, shared across its passes, with a non-evicting budget."""

    def __init__(self) -> None:
        self._identity = uuid.uuid4().hex
        self._tools: dict[str, str | None] = {}
        self._attempts: dict[str, str] = {}
        self._warned = False
        self._failed = False

    @property
    def identity(self) -> str:
        return self._identity

    def _admit(self) -> bool:
        if len(self._tools) + len(self._attempts) < MAX_FAULT_CANDIDATES:
            return True
        if not self._warned:
            logger.warning(
                "AD-1205: logical-turn diagnostic budget exhausted; keeping "
                "existing reservations and declining new observations"
            )
            self._warned = True
        return False

    def note(self, tool_id: str, signature: str | None) -> str:
        if (
            type(tool_id) is not str or not 0 < len(tool_id) <= 128
            or (signature is not None and (
                type(signature) is not str or not _SIGNATURE.fullmatch(signature)
            ))
        ):
            raise ValueError("fault_turn_evidence_invalid")
        if tool_id in self._tools:
            prior = self._tools[tool_id]
            if prior is not None and prior == signature:
                return "repeat"
            self._tools[tool_id] = None
            return "reset"
        if not self._admit():
            return "overflow"
        self._tools[tool_id] = signature
        return "new" if signature is not None else "reset"

    def reserve(self, signature: str) -> bool:
        if type(signature) is not str or not _SIGNATURE.fullmatch(signature):
            raise ValueError("fault_turn_signature_invalid")
        if signature in self._attempts or not self._admit():
            return False
        self._attempts[signature] = ""
        return True

    def finish(self, signature: str, fault_id: str) -> None:
        if (
            signature not in self._attempts
            or type(fault_id) is not str or len(fault_id) > 128
        ):
            raise ValueError("fault_turn_publication_invalid")
        self._attempts[signature] = fault_id

    def fail(self) -> None:
        self._failed = True

    def result(self) -> FaultObservationResult:
        return FaultObservationResult(tuple(self._attempts.items()), self._failed)


@runtime_checkable
class ToolFaultObservationSink(Protocol):
    async def observe_tool_run(
        self, *, turn: ToolFaultTurn, batch: ToolFaultBatch, agent_id: str,
        thread_id: str = "", attempted: str = "",
        tool_trace_ref: str | None = None,
    ) -> FaultObservationResult: ...


@dataclass(frozen=True, slots=True)
class ToolFaultObservationPort:
    """Expose observation alone to a runtime projection, not store authority."""

    _observe: Callable[..., Awaitable[FaultObservationResult]]

    async def observe_tool_run(
        self, *, turn: ToolFaultTurn, batch: ToolFaultBatch, agent_id: str,
        thread_id: str = "", attempted: str = "",
        tool_trace_ref: str | None = None,
    ) -> FaultObservationResult:
        return await self._observe(
            turn=turn, batch=batch, agent_id=agent_id, thread_id=thread_id,
            attempted=attempted, tool_trace_ref=tool_trace_ref,
        )


def fault_observer_for(runtime: Any) -> ToolFaultObservationSink | None:
    source = getattr(runtime, "fault_observer", None)
    if source is None:
        source = getattr(runtime, "fault_report_store", None)
    if not isinstance(source, ToolFaultObservationSink):
        return None
    if not callable(source.observe_tool_run):
        logger.warning(
            "AD-1205: observation collaborator has no callable observation "
            "method; retaining the uninstrumented execution path"
        )
        return None
    return source


async def observe_completed_tool_run(
    sink: ToolFaultObservationSink, *, outcome: Any, turn: ToolFaultTurn,
    classify_error: Callable[[Any], str | None], agent_id: str,
    resolve_tool_id: Callable[[str], str] | None = None,
    denied_tools: Iterable[str] = (), thread_id: str = "", attempted: str = "",
    tool_trace_ref: str | None = None,
    fault_capture: ToolFaultCapture | None = None,
) -> FaultObservationResult:
    """Contain diagnostic failure without reopening an older publication path."""
    try:
        batch = collect_tool_fault_batch(
            outcome, classify_error=classify_error,
            resolve_tool_id=resolve_tool_id, denied_tools=denied_tools,
            fault_capture=fault_capture,
        )
        result = await sink.observe_tool_run(
            turn=turn, batch=batch, agent_id=agent_id, thread_id=thread_id,
            attempted=attempted, tool_trace_ref=tool_trace_ref,
        )
        if type(result) is not FaultObservationResult:
            raise ValueError("fault_observation_result_invalid")
        result.validate()
        return result
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "AD-1205: observing completed tool evidence failed for agent %r; "
            "execution remains unchanged and legacy publication is suppressed",
            agent_id, exc_info=True,
        )
        if type(turn) is ToolFaultTurn:
            turn.fail()
            return turn.result()
        return FaultObservationResult(failed=True)


@dataclass
class _Candidate:
    signature: str
    turns: list[tuple[str, float]]


class ToolFaultObserver:
    def __init__(
        self, *, publish: Callable[..., Awaitable[FaultReport]],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._publish = publish
        self._clock = clock
        self._candidates: OrderedDict[str, _Candidate] = OrderedDict()
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def transition(self) -> AsyncIterator[None]:
        """Serialize diagnostic publication and closure, never tool execution."""
        async with self._lock:
            yield

    def forget(self, signature: str) -> None:
        for tool_id, candidate in tuple(self._candidates.items()):
            if candidate.signature == signature:
                del self._candidates[tool_id]

    async def observe_tool_run(
        self, *, turn: ToolFaultTurn, batch: ToolFaultBatch, agent_id: str,
        thread_id: str = "", attempted: str = "",
        tool_trace_ref: str | None = None,
    ) -> FaultObservationResult:
        if type(turn) is not ToolFaultTurn:
            raise ValueError("fault_turn_invalid")
        if type(batch) is not ToolFaultBatch:
            raise ValueError("fault_batch_invalid")
        batch.validate()
        async with self.transition():
            now = self._clock()
            if type(now) not in (int, float) or not math.isfinite(now):
                raise ValueError("fault_clock_invalid")
            for tool_id, candidate in tuple(self._candidates.items()):
                candidate.turns[:] = [
                    entry for entry in candidate.turns
                    if now - entry[1] < FAULT_WINDOW_SECONDS
                ]
                if not candidate.turns:
                    del self._candidates[tool_id]
            qualified: dict[str, ToolDefect] = {}
            if batch.same_run is not None:
                qualified[batch.same_run.signature] = batch.same_run
            for evidence in batch.tools:
                defect = evidence.defect
                reset = evidence.succeeded or evidence.mixed
                signature = None if reset or defect is None else defect.signature
                vote = turn.note(evidence.tool_id, signature)
                if reset or vote == "reset":
                    self._candidates.pop(evidence.tool_id, None)
                    continue
                if vote != "new" or defect is None:
                    continue
                candidate = self._candidates.get(evidence.tool_id)
                if candidate is None or candidate.signature != signature:
                    self._candidates.pop(evidence.tool_id, None)
                    if len(self._candidates) >= MAX_FAULT_CANDIDATES:
                        self._candidates.popitem(last=False)
                    candidate = _Candidate(defect.signature, [])
                    self._candidates[evidence.tool_id] = candidate
                candidate.turns.append((turn.identity, now))
                candidate.turns[:] = candidate.turns[-FAULT_DISTINCT_TURNS:]
                self._candidates.move_to_end(evidence.tool_id)
                if len(candidate.turns) == FAULT_DISTINCT_TURNS:
                    qualified[defect.signature] = defect
            for signature, defect in qualified.items():
                if not turn.reserve(signature):
                    continue
                try:
                    report = await self._publish(
                        tool_id=defect.tool_id, error_text=defect.error_text,
                        defect=defect, agent_id=agent_id, thread_id=thread_id,
                        attempted=attempted, tool_trace_ref=tool_trace_ref,
                    )
                    fault_id = getattr(report, "id", None)
                    if type(fault_id) is not str or not fault_id:
                        raise ValueError("fault_publication_missing_id")
                    turn.finish(signature, fault_id)
                except asyncio.CancelledError:
                    turn.fail()
                    raise
                except Exception:
                    turn.fail()
                    logger.warning(
                        "AD-1205: fault publication failed for tool %r; keeping "
                        "the turn's reservation without claiming persistence "
                        "or retrying through a legacy caller",
                        defect.tool_id, exc_info=True,
                    )
            return turn.result()
