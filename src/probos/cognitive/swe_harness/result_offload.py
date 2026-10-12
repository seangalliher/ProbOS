"""AD-1240: post-observer, pre-render delivery admission.

A large tool result is offloaded to the agent's workspace (or, for an original
source read, promised by path) after every observer has seen the producer's
outcome and before anything is rendered. This module owns that admission:

* ``prepare_result`` decides, per result, between legacy delivery, a workspace
  pointer, a source promise and a recovery slice, and never changes or retries
  the producer's outcome.
* ``DeliveryRun`` is one run's state: the owner, the source-recovery scope and
  the reader identity a worked call was admitted against.
* ``DeliveryRun.invocation_context`` selects a worked call's lexical promise
  BEFORE any registry lookup, permission check, bind or resolver call (R2-1), so
  nothing that fails or is replaced afterwards can turn a promised recovery
  into a fresh read. When that promise's authority is lost it raises a
  content-free ``WorkspaceResultError``; the loop reports it as an
  ``InvocationRefusal``, which is never a producer outcome.
* ``WorkspaceResultsSlot`` is the descriptor that holds a loop's owner without
  giving the loop a binder method.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, overload

from probos.cognitive.swe_harness.tool_call import (
    CapturedConversion, DelegatedToolCallResult, ToolCallResult,
    dedupe_llm_definitions, llm_function_name_claimants, result_delivery,
    tool_registration_to_llm_definition, with_result_delivery,
)
from probos.cognitive.swe_harness.tools import (
    CodebaseReadSourceTool, InstructionSourceToolResult, ReadFileTool,
    RecoveryFailureToolResult, SourceToolResult, WorkspaceSliceToolResult,
)
from probos.execution.workspace_results import (
    CANONICAL_MAX_BYTES,
    READ_ARGUMENT_MAX_BYTES,
    RESULT_DIRECTORY,
    TOOL_RESULT_THRESHOLD_BYTES,
    AgentWorkspace,
    CanonicalCapture,
    FreshRead,
    RecoverRead,
    ResultDelivery,
    SourceRecoveryScope,
    SourceRef,
    UnavailableWorkspaceResults,
    WorkspaceReadContext,
    WorkspaceResultError,
    WorkspaceResultRef,
    WorkspaceResults,
    drained_result_io,
    generation_name,
    is_workspace_results,
    resolve_workspace_results,
)
from probos.tools.delegation_evidence import MESSAGE_OMISSION_MARKER, evidence_frame
from probos.tools.protocol import ToolPermission, ToolRegistration
from probos.tools.work_item_pull_tool import WorkPullReceipt
from probos.tools.work_item_steps_tool import OwnedStepsViewResult

logger = logging.getLogger(__name__)

# The two native readers a worked call can name, and the argument that carries
# the path. Trusted by tool id: a promise is selected from the call's own
# arguments, never from whatever tool the registry holds under that id now.
_READER_TOOLS: Mapping[str, tuple[str, type]] = {
    "read_file": ("path", ReadFileTool),
    "codebase_read_source": ("file_path", CodebaseReadSourceTool),
}

# Name of the instance flag that closes ``WorkspaceResultsSlot`` for good.
_SLOT_SEALED = "_workspace_results_sealed"

# ``<GEN>`` is a fixed-width name, so a preview path sized with any canonical
# name is exactly as long as the path the owner will publish under.
_PREVIEW_GENERATION = generation_name(0.0)


class ReaderRegistry(Protocol):
    def get(self, tool_id: str) -> ToolRegistration | None: ...

    def list_ids(self) -> list[str]: ...

    def check_permission(
        self, agent_id: str, tool_id: str, required: ToolPermission, *,
        agent_department: str | None = None, agent_rank: str = "ensign",
        agent_types: list[str] | None = None,
    ) -> bool: ...

    def get_lock(self, tool_id: str) -> Mapping[str, object] | None: ...


@dataclass(frozen=True)
class DeliveryAccess:
    registry: ReaderRegistry
    registered_agent: object = field(repr=False)


def workspace_delivery_context(
    runtime: object, registry: ReaderRegistry, agent_id: str,
) -> dict[str, DeliveryAccess]:
    """Carry the SAME authorized view, only when a real owner was injected."""
    if isinstance(resolve_workspace_results(runtime), UnavailableWorkspaceResults):
        return {}
    agents = getattr(runtime, "registry", None)
    getter = getattr(agents, "get", None)
    try:
        registered = getter(agent_id) if callable(getter) else None
    except Exception:
        registered = None
        logger.debug(
            "Workspace agent lookup failed; no fallback identity is selected and "
            "large-result delivery will refuse the unresolved owner",
        )
    return {"_workspace_delivery": DeliveryAccess(registry, registered)}


@dataclass(frozen=True)
class InvocationRefusal:
    """A pre-invocation refusal: a control record, never a producer outcome.

    The loop returns this for an issued request that must not be executed
    (a promised recovery whose authority was lost). It carries only the issued
    request id and a content-free code, so no tool, hook, event or observer
    ever sees a fabricated result for it.
    """

    request_id: str
    code: str

    def __post_init__(self) -> None:
        if type(self.request_id) is not str:
            raise TypeError("an invocation refusal requires the issued request id")
        WorkspaceResultError(self.code)


class WorkspaceResultsSlot:
    """A loop's optional workspace-results owner, held as a data descriptor.

    ``__get__`` returns the bound owner, or ``None`` when none was assigned.
    ``__set__`` accepts only a valid ``WorkspaceResults`` owner and refuses every
    assignment once ``seal_workspace_results`` has closed the instance, so an
    owner can be wired after construction but never swapped mid-flight and no
    binder method is needed on the loop.

    Refusals are ``WorkspaceResultError``: ``workspace_owner_invalid`` for an
    owner that is not valid (``None`` included), ``workspace_binding_closed``
    for an assignment after the first ``run()`` began.
    """

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = f"_{name}"

    @overload
    def __get__(self, instance: None, owner: type | None = None) -> WorkspaceResultsSlot: ...

    @overload
    def __get__(self, instance: object, owner: type | None = None) -> WorkspaceResults | None: ...

    def __get__(
        self, instance: object | None, owner: type | None = None,
    ) -> WorkspaceResultsSlot | WorkspaceResults | None:
        if instance is None:
            return self
        return instance.__dict__.get(self._name)

    def __set__(self, instance: object, value: object) -> None:
        if instance.__dict__.get(_SLOT_SEALED, False):
            raise WorkspaceResultError("workspace_binding_closed")
        if not is_workspace_results(value):
            raise WorkspaceResultError("workspace_owner_invalid")
        instance.__dict__[self._name] = value


def seal_workspace_results(instance: object) -> None:
    """Close ``instance``'s ``WorkspaceResultsSlot`` for good.

    The loop calls this as its first ``run()`` begins, before any callback, so
    every later assignment is refused whatever way that run exits.
    """
    instance.__dict__[_SLOT_SEALED] = True


@dataclass(frozen=True)
class DeliverySettings:
    max_chars: int
    head_chars: int
    tail_chars: int
    max_iterations: int


@dataclass(frozen=True)
class AuthorizedReader:
    tool: ReadFileTool
    definition: dict[str, Any]


@dataclass(frozen=True, eq=False)
class ReaderIdentity:
    """The reader a worked call was admitted against: the tool and its resolver.

    A replacement of either is a different reader. Comparing the resolver as
    well as the tool means a redirected resolver is refused before it can run,
    while one that merely answers differently is still caught later by the
    reader's own target check.
    """

    tool: object = field(repr=False)
    resolver: object = field(repr=False)

    @classmethod
    def of(cls, reader: AuthorizedReader) -> ReaderIdentity:
        return cls(reader.tool, reader.tool.resolve_source_path)

    def matches(self, reader: AuthorizedReader) -> bool:
        return reader.tool is self.tool and reader.tool.resolve_source_path == self.resolver


@dataclass
class DeliveryRun:
    """One run's delivery state: the owner, its source promises and the admitted reader.

    Created by the loop when a run starts and closed when it ends, so a promise
    never outlives the run that made it.
    """

    owner: WorkspaceResults
    access: DeliveryAccess | None
    agent_id: str
    department: str
    rank: str
    settings: DeliverySettings
    scope: SourceRecoveryScope = field(init=False)
    binding: AgentWorkspace | None = field(default=None, init=False)
    promised: bool = field(default=False, init=False)
    admitted_reader: ReaderIdentity | None = field(default=None, init=False, repr=False)
    protected_groups: list[list[dict[str, Any]]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.scope = SourceRecoveryScope(self.agent_id, secrets.token_hex(16))

    def bind(self) -> AgentWorkspace:
        if isinstance(self.owner, UnavailableWorkspaceResults):
            raise WorkspaceResultError("workspace_unavailable")
        if type(self.access) is not DeliveryAccess:
            raise WorkspaceResultError("workspace_authority_unavailable")
        # Repeat validation through the owner even after the first bind.
        self.binding = self.owner.bind_agent(self.agent_id, self.access.registered_agent)
        return self.binding

    def reader(self) -> AuthorizedReader:
        if type(self.access) is not DeliveryAccess:
            raise WorkspaceResultError("reader_unavailable")
        view = self.access.registry
        registration = view.get("read_file")
        if (
            registration is None or registration.enabled is not True
            or type(registration.tool) is not ReadFileTool
            or llm_function_name_claimants("read_file", view.list_ids()) != ["read_file"]
            or not view.check_permission(
                self.agent_id, "read_file", ToolPermission.READ,
                agent_department=self.department, agent_rank=self.rank,
            )
        ):
            raise WorkspaceResultError("reader_unavailable")
        lock = view.get_lock("read_file")
        if lock is not None and lock.get("holder") != self.agent_id:
            raise WorkspaceResultError("reader_locked")
        properties = registration.tool.input_schema.get("properties", {})
        if any(properties.get(key, {}).get("type") != kind for key, kind in (
            ("path", "string"), ("offset", "integer"), ("limit", "integer"),
        )):
            raise WorkspaceResultError("reader_schema_changed")
        return AuthorizedReader(registration.tool, tool_registration_to_llm_definition(registration))

    def admit(self, reader: AuthorizedReader) -> None:
        """Record that a worked call now promises recovery through ``reader``.

        The first admission fixes the reader identity for the whole run; a later
        replacement is refused when its worked call is invoked.
        """
        self.promised = True
        if self.admitted_reader is None:
            self.admitted_reader = ReaderIdentity.of(reader)

    async def invocation_context(
        self, tool_id: str, arguments: dict[str, Any],
    ) -> WorkspaceReadContext | None:
        """The read context for one native reader call, or ``None`` for an ordinary read.

        Raises ``WorkspaceResultError`` (content-free) when the call names a
        promised source and its authority cannot be established; the loop
        turns that into an ``InvocationRefusal`` before the call starts.
        """
        reader_tool = _READER_TOOLS.get(tool_id) if type(tool_id) is str else None
        if reader_tool is None or type(arguments) is not dict:
            return None
        key, expected = reader_tool
        path = arguments.get(key)
        if type(path) is not str or not path:
            return None
        # R2-1: a worked call reserves its exact lexical path, so the promise is
        # selected first -- before any registry lookup, permission check, bind or
        # resolver call -- and nothing that fails or is replaced afterwards can
        # turn it into a fresh read. An artifact path this run published is a
        # promise too (F2): the worked call that names it is validated against
        # the reader admitted with it, and refused if that reader was replaced.
        if Path(path).is_absolute() and self.scope.workspace_promised(path):
            return await self._promised_context(tool_id, path, None)
        directive = self.scope.select(path) if Path(path).is_absolute() else None
        if type(directive) is RecoverRead:
            return await self._promised_context(tool_id, path, directive)
        if type(self.access) is not DeliveryAccess or isinstance(self.owner, UnavailableWorkspaceResults):
            return None
        binding: AgentWorkspace | None = None
        promised_workspace = False
        try:
            registration = self._registration(tool_id, expected)
            if registration is None:
                return None
            target = await drained_result_io(lambda: registration.tool.resolve_source_path(path))
            promised_workspace = self.scope.workspace_promised(str(target))
            directive = self.scope.select(str(target))
            if type(directive) is not RecoverRead and not promised_workspace:
                binding = self.bind()
        except Exception:
            # The real invocation still owns its ordinary permission/path
            # failure and observers. A large result will fail delivery at bind.
            logger.debug(
                "Native source observation authority could not be resolved; the real "
                "invocation retains its refusal and large-result delivery rechecks authority",
            )
            return None
        if promised_workspace:
            # An alias spelling reached a published artifact. Decided outside the
            # try above, so a refusal here is never swallowed into a fresh read.
            return await self._promised_context(tool_id, str(target), None)
        if type(directive) is RecoverRead:
            # An alias or relative spelling reached a promised source. It is
            # found before the owner is bound, so the strict rules apply from
            # here and no later failure becomes a fresh read.
            return await self._promised_context(tool_id, str(target), directive)
        return WorkspaceReadContext(self.owner, binding, self.scope, directive)

    def _registration(self, tool_id: str, expected: type) -> ToolRegistration | None:
        """The live registration for a native reader id, or ``None`` when not usable."""
        view = self.access.registry
        registration = view.get(tool_id)
        if (
            registration is None or registration.enabled is not True
            or type(registration.tool) is not expected
            or not view.check_permission(
                self.agent_id, tool_id, ToolPermission.READ,
                agent_department=self.department, agent_rank=self.rank,
            )
        ):
            return None
        return registration

    async def _promised_context(
        self, tool_id: str, path: str, directive: RecoverRead | None,
    ) -> WorkspaceReadContext:
        """Validate a selected promise, or refuse; never degrade to a fresh read.

        ``directive`` is ``None`` for a published artifact path (F2): there is no
        source reference to compare, so the call must name ``read_file``, the
        reader admitted with the promise must still be the live one, and that
        reader must still resolve the exact published path.
        """
        try:
            if directive is None and tool_id != "read_file":
                raise WorkspaceResultError("reader_unavailable")
            binding = self.bind()
            if directive is not None:
                self.scope.validate(path, directive)
            reader = self.reader()
            if self.admitted_reader is None or not self.admitted_reader.matches(reader):
                raise WorkspaceResultError("reader_unavailable")
            if self._registration(tool_id, _READER_TOOLS[tool_id][1]) is None:
                raise WorkspaceResultError("reader_unavailable")
            if directive is None:
                target = await drained_result_io(lambda: reader.tool.resolve_source_path(path))
                if target != Path(os.path.normpath(path)): raise WorkspaceResultError("source_changed")
                directive = FreshRead(self.agent_id, self.scope.run_nonce)
            return WorkspaceReadContext(self.owner, binding, self.scope, directive)
        except Exception as exc:
            logger.warning(
                "Promised source recovery refused before invocation (%s); the run "
                "stops with reference_unavailable and no tool is called",
                exc.code if isinstance(exc, WorkspaceResultError) else type(exc).__name__,
            )
            raise WorkspaceResultError("reference_unavailable") from None

    def offer(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.promised:
            return tools
        reader = self.reader()
        offered = list(tools)
        index = next((
            index for index, definition in enumerate(offered)
            if (definition.get("function") or {}).get("name") == "read_file"
        ), None)
        if index is None:
            offered.append(reader.definition)
        else:
            offered[index] = reader.definition
        return dedupe_llm_definitions(offered, agent_id=self.agent_id)

    def preserves_groups(self, messages: list[dict[str, Any]]) -> bool:
        return all(any(
            messages[index:index + len(group)] == group
            for index in range(len(messages) - len(group) + 1)
        ) for group in self.protected_groups)

    def close(self) -> None:
        self.scope.close()


@dataclass(frozen=True)
class DeliveryContext:
    run: DeliveryRun
    remaining_iterations: int


def delivery_failure(captured: CapturedConversion, context: DeliveryContext, code: str) -> ToolCallResult:
    producer = captured.result(
        captured.text or "", source_chars=len(captured.text) if captured.text is not None else None,
    )
    return with_result_delivery(producer, ResultDelivery(
        "failed", safe_delivery_error(code, context.run.settings.max_chars), code=code,
        capture_available=(
            captured.text is not None and captured.serialization_error is None
            and code not in ("capture_serialization", "capture_encoding")
        ),
    ))


def safe_delivery_error(code: str, max_chars: int) -> str:
    WorkspaceResultError(code)
    if type(max_chars) is not int or max_chars < 0:
        return "!"
    text = f"Result delivery failed ({code})."
    return text if len(text) <= min(128, max_chars if max_chars > 0 else 128) else "!"


def _admit(text: str, maximum: int) -> str:
    if maximum > 0 and len(text) > maximum:
        raise WorkspaceResultError("delivery_frame_too_large")
    return text


def _evidence_prefix(result: ToolCallResult, maximum: int) -> str:
    if not isinstance(result, DelegatedToolCallResult):
        return ""
    # Use the existing evidence renderer's allocation, but refuse a frame that
    # would be replaced by a marker at a tiny cap: evidence is not body storage.
    if 0 < maximum < 2 * (len(MESSAGE_OMISSION_MARKER) + 1):
        raise WorkspaceResultError("delivery_frame_too_large")
    frame = evidence_frame(result.evidence, max_chars=maximum // 2 if maximum > 0 else 0)
    if frame is None:
        raise WorkspaceResultError("delivery_frame_too_large")
    return frame


def _worked_call(path: str, offset: int, limit: int) -> str:
    arguments = {"path": path, "offset": offset, "limit": limit}
    if len(json.dumps(arguments, ensure_ascii=True).encode("ascii")) > READ_ARGUMENT_MAX_BYTES:
        raise WorkspaceResultError("read_arguments_limit")
    return f"read_file(path={json.dumps(path, ensure_ascii=True)}, offset={offset}, limit={limit})"


def _workspace_frame(reference: WorkspaceResultRef, limit: int) -> str:
    return (
        f"[workspace result v1; sha256={reference.sha256}]\n"
        f"Outline: {reference.outline}\n"
        "Owned artifact: offsets/limits are decoded Unicode characters, not JSONL lines. "
        "Retention is 24 hours from commit, not durable archival. Read then consume next iteration.\n"
        + _worked_call(reference.path, 0, limit)
    )


def _source_frame(reference: SourceRef, capture: CanonicalCapture, allowance: int) -> str:
    lines = capture.text.splitlines()
    if allowance > 0 and any(len(line) > allowance for line in lines):
        raise WorkspaceResultError("source_line_too_large")
    used = count = 0
    for line in lines:
        added = len(line) + (1 if count else 0)
        if allowance > 0 and used + added > allowance:
            break
        used += added
        count += 1
    if not count:
        raise WorkspaceResultError("source_window_unavailable")
    return (
        f"[original source v1; raw_sha256={reference.raw_sha256}; "
        f"observed lines {reference.line_start}:{reference.line_end}]\n"
        f"Outline: {capture.outline}\n"
        "No copy was written. Ordinary zero-based line slicing/newline semantics apply. "
        "Same-run recovery checks identity, revision and digest. Next top-level turn or "
        "restart: a bare path is a FRESH read, not recovery; a lost reference fails explicitly.\n"
        + _worked_call(reference.path, reference.line_start, count)
    )


async def prepare_result(captured: CapturedConversion, context: DeliveryContext) -> ToolCallResult:
    """Prepare delivery without changing or retrying the producer's outcome."""
    try:
        return await _prepare_result(captured, context)
    except WorkspaceResultError as exc:
        return delivery_failure(captured, context, exc.code)
    except Exception:
        logger.error(
            "Workspace result delivery preparation failed; the producer outcome is "
            "retained and the loop will stop without retrying the producer",
        )
        return delivery_failure(captured, context, "delivery_unavailable")


async def _prepare_result(captured: CapturedConversion, context: DeliveryContext) -> ToolCallResult:
    settings = context.run.settings
    if any(type(value) is not int or value < 0 for value in (
        settings.max_chars, settings.head_chars, settings.tail_chars,
    )):
        raise WorkspaceResultError("delivery_bounds_invalid")
    if captured.serialization_error is not None or captured.text is None:
        raise WorkspaceResultError("capture_serialization")
    raw, text = captured.producer, captured.text
    if isinstance(raw, RecoveryFailureToolResult):
        raise WorkspaceResultError(raw.delivery_error)
    producer = captured.result(text, source_chars=len(text))
    if type(raw) is WorkPullReceipt and raw.error is None:
        _admit(text, settings.max_chars)
        return captured.legacy_result()
    if type(raw) is OwnedStepsViewResult and raw.error is None:
        _admit(text, settings.max_chars)
        return captured.legacy_result()
    if str.__len__(text) > CANONICAL_MAX_BYTES:
        raise WorkspaceResultError("capture_limit")
    try:
        encoded_size = len(str.encode(text, "utf-8", errors="strict"))
    except UnicodeError as exc:
        raise WorkspaceResultError("capture_encoding") from exc
    if encoded_size > CANONICAL_MAX_BYTES:
        raise WorkspaceResultError("capture_limit")
    recovery = isinstance(raw, WorkspaceSliceToolResult) or (
        isinstance(raw, (SourceToolResult, InstructionSourceToolResult)) and raw.recovery
    )
    if recovery:
        if context.remaining_iterations < 1:
            raise WorkspaceResultError("recovery_iterations_unavailable")
        _admit(text, settings.max_chars)
        reference = raw.workspace_slice.reference if isinstance(raw, WorkspaceSliceToolResult) else raw.source_reference
        return with_result_delivery(producer, ResultDelivery("recovered", text, reference))
    if encoded_size <= TOOL_RESULT_THRESHOLD_BYTES:
        return captured.legacy_result()
    capture = canonical_capture(captured)
    if context.remaining_iterations < 2:
        raise WorkspaceResultError("recovery_iterations_unavailable")
    binding = context.run.bind()
    reader = context.run.reader()
    prefix = _evidence_prefix(producer, settings.max_chars)
    if producer.is_error:
        prefix += "Producer outcome: error. Recovery retains the original error text.\n"
    allowance = settings.max_chars - len(prefix) if settings.max_chars > 0 else 0
    if settings.max_chars > 0 and allowance <= 0:
        raise WorkspaceResultError("delivery_frame_too_large")
    if isinstance(raw, (SourceToolResult, InstructionSourceToolResult)):
        reference = raw.source_reference
        authorized = await drained_result_io(lambda: reader.tool.resolve_source_path(reference.path))
        if str(authorized) != reference.path:
            raise WorkspaceResultError("source_changed")
        frame = _admit(prefix + _source_frame(reference, capture, allowance), settings.max_chars)
        context.run.scope.reserve(reference)
        delivery = ResultDelivery("source", frame, reference)
    else:
        # Admit the whole, equally-sized path/call BEFORE publication. Artifact
        # IDs are generated by the owner, never from tool names or call IDs, and
        # the generation segment is fixed width, so this preview is exactly as
        # long as the path the owner publishes under.
        path = (
            binding.root / binding.owner_key / RESULT_DIRECTORY / _PREVIEW_GENERATION
            / binding.owner_digest / ("0" * 32) / "payload.jsonl"
        )
        preview = WorkspaceResultRef(
            str(path), binding.owner_digest, "0" * 32, capture.sha256,
            capture.source_chars, capture.utf8_bytes, capture.representation, 0, 86400, capture.outline,
        )
        limit = min(capture.source_chars, allowance if allowance > 0 else 4096, 4096)
        _admit(prefix + _workspace_frame(preview, limit), settings.max_chars)
        authorized = await drained_result_io(lambda: reader.tool.resolve_source_path(str(path)))
        if authorized != path:
            raise WorkspaceResultError("workspace_path_invalid")
        reference = await context.run.owner.store_tool_result(binding, capture)
        frame = _admit(prefix + _workspace_frame(reference, limit), settings.max_chars)
        context.run.scope.reserve_workspace(reference)
        delivery = ResultDelivery("workspace", frame, reference)
    context.run.admit(reader)
    return with_result_delivery(producer, delivery)


def delivery_trace(result: ToolCallResult) -> dict[str, object] | None:
    delivery = result_delivery(result)
    if delivery is None:
        return None
    trace: dict[str, object] = {
        "version": 1, "status": delivery.status, "capture_available": delivery.capture_available,
        "presentation_chars": len(delivery.presentation),
    }
    if delivery.code is not None:
        trace["code"] = delivery.code
    reference = delivery.reference
    if isinstance(reference, WorkspaceResultRef):
        trace.update({
            "path": reference.path, "sha256": reference.sha256,
            "source_chars": reference.source_chars, "utf8_bytes": reference.utf8_bytes,
            "representation": reference.representation, "expires_at": reference.expires_at,
            "retention": "24h-commit-clock",
        })
    elif isinstance(reference, SourceRef):
        trace.update({
            "path": reference.path, "raw_sha256": reference.raw_sha256,
            "line_start": reference.line_start, "line_end": reference.line_end,
            "whole": reference.whole, "retention": "invocation-only",
        })
    if len(json.dumps(trace, ensure_ascii=True).encode("ascii")) > 4096:
        return {"version": 1, "status": delivery.status, "metadata_omitted": True}
    return trace


def canonical_capture(captured: CapturedConversion) -> CanonicalCapture:
    """Qualify the one captured rendering without invoking user hooks again."""
    if captured.serialization_error is not None or captured.text is None:
        raise WorkspaceResultError("capture_serialization")
    text = captured.text
    if str.__len__(text) > CANONICAL_MAX_BYTES:
        raise WorkspaceResultError("capture_limit")
    try:
        encoded = str.encode(text, "utf-8", errors="strict")
    except UnicodeError as exc:
        raise WorkspaceResultError("capture_encoding") from exc
    if len(encoded) > CANONICAL_MAX_BYTES:
        raise WorkspaceResultError("capture_limit")
    inspection = captured.inspection
    if inspection is None:
        raise WorkspaceResultError("capture_inspection_unavailable")
    if inspection.error is not None:
        raise WorkspaceResultError(inspection.error)
    representation = "text" if inspection.root_type in ("str", "NoneType") else "python-repr"
    outline = json.dumps({
        "representation": representation,
        "root_type": inspection.root_type,
        "chars": len(text),
        "utf8_bytes": len(encoded),
        "lines": len(text.splitlines()),
        "shape": dict(inspection.shape),
        "omitted": ["keys", "values"],
    }, ensure_ascii=True, separators=(",", ":"))
    return CanonicalCapture(
        text=text, representation=representation, source_chars=len(text),
        utf8_bytes=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(), outline=outline,
    )
