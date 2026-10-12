"""AD-1240: neutral, identity-bound workspace result contracts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Protocol, TypeGuard, TypeVar, runtime_checkable

# About two ordinary 6000-character ASCII allowances: catches the measured
# 14,373-byte lost-middle document without a recovery turn for small outputs.
TOOL_RESULT_THRESHOLD_BYTES = 12_288
CANONICAL_MAX_BYTES = 1_048_576
ENCODED_MAX_BYTES = 8_388_608
OUTLINE_MAX_BYTES = 1024
INSPECTION_MAX_SLOTS = 4096
INSPECTION_MAX_DEPTH = 32
READ_ARGUMENT_MAX_BYTES = 4096
RESULT_RETENTION_SECONDS = 86_400
RESULT_DIRECTORY = ".tool-results"
# A generation is one UTC hour of the injected clock. Whole generations are the
# only unit the reaper ever removes (see ``generation_expiry``).
GENERATION_SECONDS = 3600
GENERATION_NAME_RE = re.compile(r"\d{8}T\d{2}Z")  # fullmatch only
_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,95}")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_T = TypeVar("_T")


class WorkspaceResultError(Exception):
    """Content-free delivery refusal; never a replacement producer outcome."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or _ERROR_CODE.fullmatch(code) is None:
            raise ValueError("invalid workspace result error code")
        self.code = code
        super().__init__(code)


def result_time(value: object) -> float:
    """A finite injected-clock reading; anything else is a typed refusal."""
    if type(value) not in (int, float):
        raise WorkspaceResultError("clock_invalid")
    try:
        number = float(value)
    except OverflowError as exc:
        raise WorkspaceResultError("clock_invalid") from exc
    if not math.isfinite(number):
        raise WorkspaceResultError("clock_invalid")
    return number


def generation_name(t: float) -> str:
    """The canonical name, ``YYYYMMDDTHHZ``, of the UTC hour containing ``t``."""
    hour_start = (result_time(t) // GENERATION_SECONDS) * GENERATION_SECONDS
    try:
        moment = _EPOCH + timedelta(seconds=hour_start)
    except OverflowError as exc:
        raise WorkspaceResultError("clock_invalid") from exc
    return f"{moment.year:04d}{moment.month:02d}{moment.day:02d}T{moment.hour:02d}Z"


def generation_start(name: str) -> float:
    """Start, in seconds, of the hour a canonical name denotes.

    The parse is strict: only a name that ``generation_name`` would itself
    produce round-trips, so no other spelling is ever treated as ours.
    """
    if type(name) is not str or GENERATION_NAME_RE.fullmatch(name) is None:
        raise WorkspaceResultError("generation_invalid")
    try:
        moment = datetime(
            int(name[0:4]), int(name[4:6]), int(name[6:8]), int(name[9:11]),
            tzinfo=timezone.utc,
        )
    except ValueError as exc:
        raise WorkspaceResultError("generation_invalid") from exc
    start = (moment - _EPOCH).total_seconds()
    if generation_name(start) != name:
        raise WorkspaceResultError("generation_invalid")
    return start


def generation_expiry(name: str) -> float:
    """Clock value at which the generation may be removed whole.

    The hour must have ended and every artifact committed inside it must have
    outlived its own retention, so this is decided by the name alone.
    """
    return generation_start(name) + GENERATION_SECONDS + RESULT_RETENTION_SECONDS


@dataclass(frozen=True)
class AgentWorkspace:
    agent_id: str
    owner_key: str
    owner_digest: str
    root: Path
    authority: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class CanonicalCapture:
    text: str = field(repr=False)
    representation: Literal["text", "python-repr"]
    source_chars: int
    utf8_bytes: int
    sha256: str
    outline: str

    def __post_init__(self) -> None:
        if (
            type(self.text) is not str or type(self.outline) is not str
            or type(self.representation) is not str or self.representation not in ("text", "python-repr")
        ):
            raise WorkspaceResultError("capture_invalid")
        if len(self.text) > CANONICAL_MAX_BYTES:
            raise WorkspaceResultError("capture_limit")
        try:
            encoded = self.text.encode("utf-8", errors="strict")
            outline = self.outline.encode("ascii", errors="strict")
        except (UnicodeError, AttributeError) as exc:
            raise WorkspaceResultError("capture_encoding") from exc
        if len(encoded) > CANONICAL_MAX_BYTES:
            raise WorkspaceResultError("capture_limit")
        if (
            type(self.source_chars) is not int or self.source_chars != len(self.text)
            or type(self.utf8_bytes) is not int or self.utf8_bytes != len(encoded)
            or self.sha256 != hashlib.sha256(encoded).hexdigest()
            or not outline or len(outline) > OUTLINE_MAX_BYTES
        ):
            raise WorkspaceResultError("capture_invalid")
        try:
            summary = json.loads(self.outline)
        except ValueError as exc:
            raise WorkspaceResultError("capture_invalid") from exc
        if (
            type(summary) is not dict
            or summary.get("representation") != self.representation
            or type(summary.get("chars")) is not int or summary["chars"] != self.source_chars
            or type(summary.get("utf8_bytes")) is not int or summary["utf8_bytes"] != self.utf8_bytes
            or type(summary.get("lines")) is not int or summary["lines"] != len(self.text.splitlines())
            or summary.get("omitted") != ["keys", "values"]
            or summary.get("root_type") not in ("str", "NoneType", "bool", "int", "float", "list", "tuple", "dict")
            or type(summary.get("shape")) is not dict
            or set(summary["shape"]) != {"slots", "dicts", "lists", "tuples", "scalars", "revisits"}
            or any(type(value) is not int or not 0 <= value <= INSPECTION_MAX_SLOTS for value in summary["shape"].values())
        ):
            raise WorkspaceResultError("capture_invalid")


@dataclass(frozen=True)
class WorkspaceResultRef:
    path: str
    owner_digest: str
    artifact_id: str
    sha256: str
    source_chars: int
    utf8_bytes: int
    representation: Literal["text", "python-repr"]
    committed_at: float
    expires_at: float
    outline: str


@dataclass(frozen=True)
class SourceRef:
    agent_id: str
    run_nonce: str
    path: str
    identity: tuple[int, int, int]
    revision: tuple[int, int, int]
    raw_sha256: str
    line_start: int
    line_end: int
    total_lines: int
    whole: bool

    def __post_init__(self) -> None:
        if (
            type(self.agent_id) is not str or not self.agent_id
            or type(self.run_nonce) is not str or not self.run_nonce
            or type(self.path) is not str or not Path(self.path).is_absolute()
            or type(self.raw_sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", self.raw_sha256) is None
            or type(self.whole) is not bool
            or any(type(value) is not int or value < 0 for value in (
                self.line_start, self.line_end, self.total_lines,
            ))
            or not self.line_start <= self.line_end <= self.total_lines
            or any(type(value) is not tuple or len(value) != 3 or any(
                type(part) is not int for part in value
            ) for value in (self.identity, self.revision))
        ):
            raise WorkspaceResultError("source_reference_invalid")


@dataclass(frozen=True)
class FreshRead:
    agent_id: str
    run_nonce: str


@dataclass(frozen=True)
class RecoverRead:
    agent_id: str
    run_nonce: str
    reference: SourceRef | None


class SourceRecoveryScope:
    """Loop-owned, invocation-local source promises; never a durable catalog."""

    def __init__(self, agent_id: str, run_nonce: str) -> None:
        if type(agent_id) is not str or not agent_id or type(run_nonce) is not str or not run_nonce:
            raise WorkspaceResultError("source_scope_invalid")
        self.agent_id = agent_id
        self.run_nonce = run_nonce
        self._active = True
        self._references: dict[str, SourceRef] = {}
        self._workspace: set[str] = set()

    @staticmethod
    def _key(path: str) -> str:
        if type(path) is not str or not path or not Path(path).is_absolute():
            raise WorkspaceResultError("reference_unavailable")
        return os.path.normcase(os.path.normpath(path))

    def select(self, path: str) -> FreshRead | RecoverRead:
        if not self._active:
            raise WorkspaceResultError("reference_unavailable")
        reference = self._references.get(self._key(path))
        if reference is None:
            return FreshRead(self.agent_id, self.run_nonce)
        return RecoverRead(self.agent_id, self.run_nonce, reference)

    def reserve(self, reference: SourceRef) -> None:
        if (
            not self._active or type(reference) is not SourceRef
            or reference.agent_id != self.agent_id or reference.run_nonce != self.run_nonce
        ):
            raise WorkspaceResultError("reference_unavailable")
        key = self._key(reference.path)
        prior = self._references.get(key)
        if prior is not None and (
            prior.identity, prior.revision, prior.raw_sha256
        ) != (reference.identity, reference.revision, reference.raw_sha256):
            raise WorkspaceResultError("source_conflict")
        if prior is None:
            self._references[key] = reference

    def reserve_workspace(self, reference: WorkspaceResultRef) -> None:
        """Promise this run's own published artifact path, so a later call to it is never a silent fresh read."""
        if not self._active or type(reference) is not WorkspaceResultRef:
            raise WorkspaceResultError("reference_unavailable")
        self._workspace.add(self._key(reference.path))

    def workspace_promised(self, path: str) -> bool:
        """Whether ``path`` is an artifact this run published and promised to serve."""
        if not self._active or type(path) is not str or not path or not Path(path).is_absolute():
            return False
        return self._key(path) in self._workspace

    def validate(self, path: str, directive: FreshRead | RecoverRead) -> None:
        if (
            not self._active or type(directive) not in (FreshRead, RecoverRead)
            or directive.agent_id != self.agent_id or directive.run_nonce != self.run_nonce
        ):
            raise WorkspaceResultError("reference_unavailable")
        if type(directive) is RecoverRead:
            reference = directive.reference
            if (
                type(reference) is not SourceRef
                or self._references.get(self._key(reference.path)) is not reference
            ):
                raise WorkspaceResultError("reference_unavailable")
            if self._key(path) != self._key(reference.path):
                raise WorkspaceResultError("source_changed")
        elif self._references.get(self._key(path)) is not None:
            raise WorkspaceResultError("reference_unavailable")

    def close(self) -> None:
        self._active = False
        self._references.clear()
        self._workspace.clear()


@dataclass(frozen=True)
class WorkspaceSlice:
    text: str = field(repr=False)
    start: int
    end: int
    reference: WorkspaceResultRef


@dataclass(frozen=True)
class WorkspaceReapResult:
    deleted: int = 0
    skipped: int = 0
    failed: int = 0
    deferred: int = 0


@runtime_checkable
class WorkspaceResults(Protocol):
    @property
    def background_tasks(self) -> tuple[asyncio.Task[None], ...]: ...

    def bind_agent(self, agent_id: str, registered_agent: object) -> AgentWorkspace: ...

    async def store_tool_result(
        self, binding: AgentWorkspace, payload: CanonicalCapture,
    ) -> WorkspaceResultRef: ...

    async def read_tool_result_slice(
        self, binding: AgentWorkspace, path: str,
        offset: int | None, limit: int | None,
    ) -> WorkspaceSlice: ...

    async def reap_tool_results(self) -> WorkspaceReapResult: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


@dataclass(frozen=True)
class WorkspaceReadContext:
    owner: WorkspaceResults
    binding: AgentWorkspace
    scope: SourceRecoveryScope
    directive: FreshRead | RecoverRead

    def __post_init__(self) -> None:
        if (
            not isinstance(self.owner, WorkspaceResults) or type(self.binding) is not AgentWorkspace
            or type(self.scope) is not SourceRecoveryScope
            or type(self.directive) not in (FreshRead, RecoverRead)
            or self.binding.agent_id != self.scope.agent_id
        ):
            raise WorkspaceResultError("reference_unavailable")


@dataclass(frozen=True)
class ResultDelivery:
    status: Literal["workspace", "source", "recovered", "receipt", "failed"]
    presentation: str = field(repr=False)
    reference: WorkspaceResultRef | SourceRef | None = None
    code: str | None = None
    capture_available: bool = True

    def __post_init__(self) -> None:
        if (
            self.status not in ("workspace", "source", "recovered", "receipt", "failed")
            or type(self.presentation) is not str
            or type(self.capture_available) is not bool
            or (self.reference is not None and type(self.reference) not in (SourceRef, WorkspaceResultRef))
        ):
            raise WorkspaceResultError("delivery_invalid")
        if self.status == "failed":
            WorkspaceResultError(self.code)


@dataclass(frozen=True)
class UnavailableWorkspaceResults:
    """An armed dependency failure, not permission to use ambient storage."""

    @property
    def background_tasks(self) -> tuple[asyncio.Task[None], ...]:
        return ()

    def bind_agent(self, agent_id: str, registered_agent: object) -> AgentWorkspace:
        raise WorkspaceResultError("workspace_unavailable")

    async def store_tool_result(
        self, binding: AgentWorkspace, payload: CanonicalCapture,
    ) -> WorkspaceResultRef:
        raise WorkspaceResultError("workspace_unavailable")

    async def read_tool_result_slice(
        self, binding: AgentWorkspace, path: str,
        offset: int | None, limit: int | None,
    ) -> WorkspaceSlice:
        raise WorkspaceResultError("workspace_unavailable")

    async def reap_tool_results(self) -> WorkspaceReapResult:
        raise WorkspaceResultError("workspace_unavailable")

    async def start(self) -> None:
        raise WorkspaceResultError("workspace_unavailable")

    async def stop(self) -> None:
        return None


def resolve_workspace_results(runtime: object) -> WorkspaceResults:
    """Resolve only the public injected owner; never construct ambient storage."""
    try:
        owner = getattr(runtime, "workspace_results", None)
    except Exception:
        return UnavailableWorkspaceResults()
    if is_workspace_results(owner):
        return owner
    return UnavailableWorkspaceResults()


def is_workspace_results(owner: object) -> TypeGuard[WorkspaceResults]:
    try:
        return (
            isinstance(owner, WorkspaceResults)
            and all(callable(getattr(owner, method, None)) for method in (
                "bind_agent", "store_tool_result", "read_tool_result_slice",
                "reap_tool_results", "start", "stop",
            ))
            and type(owner.background_tasks) is tuple
            and all(isinstance(task, asyncio.Task) for task in owner.background_tasks)
        )
    except Exception:
        return False


def is_workspace_result_path(path: Path) -> bool:
    """Recognize the namespace component; the reader also checks workspace roots."""
    return any(part.casefold() == RESULT_DIRECTORY for part in path.parts)


async def drained_result_io(operation: Callable[[], _T]) -> _T:
    """Cancellation does not release an I/O owner until its worker has exited."""
    task = asyncio.create_task(asyncio.to_thread(operation), name="workspace-result-io")
    return await await_result_task(task)


async def await_result_task(task: asyncio.Task[_T]) -> _T:
    """Drain a retained result operation before propagating cancellation."""
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            task.exception()
        raise
