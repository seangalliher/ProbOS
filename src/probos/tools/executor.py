"""Wrapped Tool Executor — pre/post hooks around tool invocation (AD-448).

Sits above ToolRegistry.check_and_invoke(), adding:
- Pre-invoke hooks (parameter validation, audit logging)
- Post-invoke hooks (result logging, timing)
- Centralized timing for tool call telemetry

Does NOT duplicate permission resolution or LOTO — those stay in
ToolRegistry. This is a decorator pattern, not a replacement.
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import logging
import math
import secrets
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from itertools import islice
from types import CoroutineType
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Protocol

if TYPE_CHECKING:
    from probos.tools.protocol import ToolResult

logger = logging.getLogger(__name__)

PreHook = Callable[[dict[str, Any]], "bool | Awaitable[bool]"]
PostHook = Callable[[dict[str, Any], "ToolResult"], "None | Awaitable[None]"]

_TOOL_EVENT_CATEGORY = "tool"
_DIGEST_MAX_KEYS = 16
_DIGEST_MAX_SCAN = 256
_DIGEST_MAX_ITEMS = 8
_DIGEST_MAX_DEPTH = 3
_DIGEST_MAX_NODES = 64
_DIGEST_MAX_TEXT_CHARS = 128
_DIGEST_MAX_BYTES = 2048
_RECORD_MAX_BYTES = 4096
_TOOL_ID_MAX_BYTES = 128
_DIGEST_KEY_HASH_CHARS = 12
_DIGEST_DOMAIN = b"probos.tool_shape.v3\x00"
_DIGEST_KEY_DOMAIN = b"probos.tool_parameter_key.v1\x00"
_IDENTITY_DOMAIN = b"probos.tool_identity.v1\x00"
_DIGEST_KEY_SECRET = secrets.token_bytes(32)

_KNOWN_PARAM_KEYS = frozenset({
    "action", "agent_id", "aggregate", "api_key", "args", "authorization",
    "body", "branch", "category", "channel", "channel_id", "cmd", "command",
    "commit", "content", "correlation_id", "cursor", "data", "depth",
    "description", "destination", "direction", "dir_path", "directory",
    "dry_run", "encoding", "end_time", "event", "exclude", "file_path",
    "filter", "filters", "force", "format", "headers", "id", "include",
    "index", "instructions", "issue_number", "json", "key", "keys", "kind",
    "limit", "max_results", "message", "method", "mode", "name", "offset",
    "order", "owner", "page", "params", "password", "path", "paths",
    "pattern", "payload", "prompt", "pull_number", "q", "query", "reason",
    "recursive", "ref", "regex", "repo", "secret", "sha", "since", "sort",
    "source", "start_time", "state", "status", "tags", "target", "text",
    "thread_id", "timeout", "timeout_s", "title", "token", "tool_id", "type",
    "until", "url", "urls", "value", "values", "work_item_id",
})

DEFAULT_MAX_RECORDS_PER_RUN = 500
_MAX_TRACKED_RUNS = 256


def _bounded_text(value: Any) -> str | None:
    """Bound exact-string provenance in UTF-8 and JSON without coercion."""
    if type(value) is not str:
        return None
    bounded = value[:_DIGEST_MAX_TEXT_CHARS].encode("utf-8", "replace")
    text = bounded[:_DIGEST_MAX_TEXT_CHARS].decode("utf-8", "ignore")
    while len(json.dumps(text).encode("utf-8")) > _DIGEST_MAX_TEXT_CHARS:
        text = text[:-1]
    return text


def _bounded_int(value: Any) -> int | None:
    if type(value) is int and -(2**63) <= value < 2**63:
        return value
    return None


def recording_identity(value: Any) -> str | None:
    """Accept an exact bounded provenance identity without truncating a join key."""
    if value is None or (type(value) is str and not value):
        return None
    if type(value) is str and _bounded_text(value) == value:
        return value
    logger.warning(
        "AD-1224: diagnostic identity is invalid or exceeds provenance bounds; "
        "omitting the association while execution and reporting continue",
    )
    return None


def sample_recording_identity(
    provider: Callable[[], str | None] | None,
) -> str | None:
    """Sample a synchronous diagnostic provider; ordinary failures stay private."""
    if provider is None:
        return None
    try:
        value = provider()
        if type(value) is CoroutineType:
            value.close()
        return recording_identity(value)
    except Exception:
        logger.warning(
            "AD-1224: diagnostic identity provider failed; omitting the "
            "association while execution and reporting continue",
        )
        return None


def _type_label(value: Any) -> str:
    value_type = type(value)
    if value_type is type(None):
        return "null"
    if value_type is bool:
        return "bool"
    if value_type is int:
        return "int"
    if value_type is float:
        return "float"
    if value_type is str:
        return "str"
    if value_type is bytes or value_type is bytearray:
        return "bytes"
    if value_type is list or value_type is tuple:
        return "list"
    if value_type is set or value_type is frozenset:
        return "set"
    if value_type is dict:
        return "dict"
    return "other"


def _exact_len(value: Any) -> int | None:
    value_type = type(value)
    if (
        value_type is list or value_type is tuple or value_type is dict
        or value_type is set or value_type is frozenset
    ):
        return len(value)
    return None


def _value_shape(value: Any, depth: int, remaining: list[int]) -> dict[str, Any]:
    shape: dict[str, Any] = {"type": _type_label(value), "size": _exact_len(value)}
    remaining[0] -= 1
    if depth <= 0 or remaining[0] <= 0:
        return shape
    value_type = type(value)
    if value_type is dict:
        members = islice(value.values(), _DIGEST_MAX_ITEMS)
    elif value_type is list or value_type is tuple:
        members = islice(value, _DIGEST_MAX_ITEMS)
    else:
        return shape
    items: list[dict[str, Any]] = []
    for member in members:
        if remaining[0] <= 0:
            break
        items.append(_value_shape(member, depth - 1, remaining))
    shape["items"] = items
    shape["items_omitted"] = max(0, len(value) - len(items))
    return shape


def _key_labels(key: Any) -> tuple[str | None, str | None, str]:
    key_type = _type_label(key)
    if type(key) is str:
        if key in _KNOWN_PARAM_KEYS:
            return key, None, key_type
        material = key.encode("utf-8", "replace")
    elif type(key) is bytes:
        material = key
    else:
        return None, None, key_type
    digest = hmac.new(
        _DIGEST_KEY_SECRET, _DIGEST_KEY_DOMAIN + material, hashlib.sha256,
    ).hexdigest()
    return None, digest[:_DIGEST_KEY_HASH_CHARS], key_type


def _json_size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True).encode("utf-8"))


def _shape_hash(fields: list[dict[str, Any]]) -> str:
    serialized = json.dumps(fields, sort_keys=True).encode("utf-8")
    return hashlib.sha256(_DIGEST_DOMAIN + serialized).hexdigest()


def _collapse_shape(shape: dict[str, Any]) -> None:
    if "items" in shape:
        shape.pop("items")
        shape["items_omitted"] = shape["size"]


def digest_params(params: Any) -> dict[str, Any]:
    """Describe bounded structure, never scalar values or scalar lengths.

    Only exact builtin containers are inspected. Subclasses, class objects,
    and foreign objects are opaque; their representation dunders are not used.
    Container counts, builtin type labels, vocabulary keys, and process-keyed
    unknown-key hashes are permitted structural disclosure. Scan, recursion,
    node and serialized-output budgets bound the retained description. Ordinary
    failures degrade to a fixed payload; lifecycle exceptions still propagate.
    """
    try:
        return _digest_params(params)
    except Exception:
        logger.warning(
            "AD-1224: parameter shape construction failed; recording a fixed "
            "degraded shape and continuing to the registry permission chain",
        )
        return {
            "shape_sha256": "", "key_count": 0, "fields": [],
            "keys_omitted": 0, "degraded": True,
        }


def _digest_params(params: Any) -> dict[str, Any]:
    remaining = [_DIGEST_MAX_NODES]
    digest: dict[str, Any] = {
        "shape_sha256": "0" * 64, "key_count": 0,
        "fields": [], "keys_omitted": 0,
    }
    if type(params) is not dict:
        shape = _value_shape(params, _DIGEST_MAX_DEPTH, remaining)
        digest["non_dict"] = shape
        if _json_size(digest) > _DIGEST_MAX_BYTES:
            _collapse_shape(shape)
        digest["shape_sha256"] = _shape_hash([{"non_dict": shape}])
        return digest

    candidates = [
        (*_key_labels(key), value)
        for key, value in islice(params.items(), _DIGEST_MAX_SCAN)
    ]
    candidates.sort(key=lambda item: (item[2], item[0] or item[1] or ""))
    fields = [
        {
            "key": name, "key_hash": key_hash, "key_type": key_type,
            "value": _value_shape(value, _DIGEST_MAX_DEPTH, remaining),
        }
        for name, key_hash, key_type, value in candidates[:_DIGEST_MAX_KEYS]
    ]
    digest.update(
        key_count=len(params), fields=fields,
        keys_omitted=max(0, len(params) - len(fields)),
    )
    for item in reversed(fields):
        if _json_size(digest) <= _DIGEST_MAX_BYTES:
            break
        _collapse_shape(item["value"])
    while fields and _json_size(digest) > _DIGEST_MAX_BYTES:
        fields.pop()
        digest["keys_omitted"] += 1
    digest["shape_sha256"] = _shape_hash(fields)
    return digest


class ToolCatalog(Protocol):
    """The public catalog needed to verify a retained tool identity."""

    def list_ids(self) -> list[str]: ...


def _catalog_claimants(tool_id: Any, catalog: ToolCatalog | None) -> list[str] | None:
    if type(tool_id) is not str or catalog is None:
        return None
    try:
        from probos.cognitive.swe_harness.tool_call import llm_function_name_claimants

        tool_ids = catalog.list_ids()
        if type(tool_ids) is not list or any(type(name) is not str for name in tool_ids):
            return None
        return llm_function_name_claimants(tool_id, tool_ids)
    except Exception:
        return None


def _opaque_tool_identity(tool_id: Any, *, registered: bool = False) -> str:
    label = "registered-tool:opaque:" if registered else "unknown-tool:"
    material = tool_id.encode("utf-8", "replace") if type(tool_id) is str else b"<opaque>"
    digest = hmac.new(
        _DIGEST_KEY_SECRET,
        _IDENTITY_DOMAIN + label.encode("ascii") + material,
        hashlib.sha256,
    ).hexdigest()
    return label + digest[:32]


def tool_record_identity(tool_id: Any, *, catalog: ToolCatalog | None = None) -> str:
    """Project a tool name to at most 128 UTF-8 bytes for retention.

    Only an unambiguous canonical ID verified by the trusted public catalog is
    retained verbatim. Unknown names and oversized verified IDs use distinct,
    process-keyed opaque identities. This projection never authorizes execution.
    Without a catalog, even provider-valid names remain opaque.
    """
    claimants = _catalog_claimants(tool_id, catalog)
    if claimants is not None and len(claimants) == 1:
        canonical = claimants[0]
        if len(canonical.encode("utf-8", "replace")) <= _TOOL_ID_MAX_BYTES:
            return canonical
        return _opaque_tool_identity(canonical, registered=True)
    return _opaque_tool_identity(tool_id)


ERROR_CATEGORIES = (
    "aborted_by_hook", "ambiguous_tool", "cancelled", "invalid_params",
    "network", "not_found", "permission_denied", "rate_limited",
    "timeout", "unavailable", "other",
)
_ERROR_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("pre-hook aborted", "aborted_by_hook"),
    ("is ambiguous and was not invoked", "ambiguous_tool"),
    ("permission", "permission_denied"), ("denied", "permission_denied"),
    ("not authorized", "permission_denied"), ("forbidden", "permission_denied"),
    ("rate limit", "rate_limited"), ("too many requests", "rate_limited"),
    ("timed out", "timeout"), ("timeout", "timeout"),
    ("cancelled", "cancelled"), ("canceled", "cancelled"),
    ("not found", "not_found"), ("no such", "not_found"),
    ("does not exist", "not_found"), ("unknown tool", "not_found"),
    ("invalid", "invalid_params"), ("missing required", "invalid_params"),
    ("validation", "invalid_params"), ("connection", "network"),
    ("network", "network"), ("dns", "network"), ("ssl", "network"),
    ("unavailable", "unavailable"), ("not available", "unavailable"),
)


def classify_tool_error(error: Any) -> str | None:
    """Return a closed error category, or None for success, without coercion."""
    if error is None:
        return None
    if type(error) is not str:
        return "other"
    if error in ERROR_CATEGORIES:
        return error
    scan_chars = _DIGEST_MAX_TEXT_CHARS * 8
    samples = (error[:scan_chars].lower(), error[-scan_chars:].lower())
    for signature, category in _ERROR_SIGNATURES:
        if any(signature in sample for sample in samples):
            return category
    return "other"


def _exception_category(error: Exception) -> str:
    from probos.tools.registry import ToolPermissionDenied

    if isinstance(error, (PermissionError, ToolPermissionDenied)):
        return "permission_denied"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, FileNotFoundError):
        return "not_found"
    if isinstance(error, ConnectionError):
        return "network"
    if isinstance(error, (ValueError, TypeError)):
        return "invalid_params"
    return "other"


@dataclass
class _RunRecordCounter:
    spent: int = 0
    announced: bool = False
    limit: int | None = None

    def spend(self, limit: int) -> tuple[bool, bool]:
        self.limit = limit if self.limit is None else min(self.limit, limit)
        if self.spent < self.limit:
            self.spent += 1
            return True, False
        if not self.announced:
            self.announced = True
            return False, True
        return False, False


_RUN_RECORD_COUNTER: ContextVar[_RunRecordCounter | None] = ContextVar(
    "probos_tool_record_counter", default=None,
)


@contextmanager
def tool_recording_scope() -> Iterator[None]:
    """Own one run's counter; sibling tasks share it and nested runs restore it."""
    token = _RUN_RECORD_COUNTER.set(_RunRecordCounter())
    try:
        yield
    finally:
        _RUN_RECORD_COUNTER.reset(token)


class ToolRecordBudget:
    """Spend once per pair within a run scope, with a finite standalone fallback.

    Scoped runs own their counter lifetime and cannot be evicted by other runs.
    A standalone hook retains at most max_tracked_runs counters for its lifetime.
    At saturation, new identities are dropped, never evicted and re-admitted;
    one scope-level warning explains that conservative loss of observation.
    """

    def __init__(
        self, *, max_per_run: int, max_tracked_runs: int = _MAX_TRACKED_RUNS,
    ) -> None:
        if type(max_per_run) is not int or not -(2**63) <= max_per_run < 2**63:
            raise ValueError("max_per_run must be a signed 64-bit integer")
        if type(max_tracked_runs) is not int or max_tracked_runs < 1:
            raise ValueError("max_tracked_runs must be a positive integer")
        self._max_per_run = max(0, max_per_run)
        self._max_tracked_runs = min(max_tracked_runs, _MAX_TRACKED_RUNS)
        self._counts: dict[str, _RunRecordCounter] = {}
        self._saturation_announced = False

    def spend(self, run_key: str) -> tuple[bool, bool]:
        """Return (admit_pair, announce_exhaustion), with no await while spending."""
        scoped = _RUN_RECORD_COUNTER.get()
        if scoped is not None:
            return scoped.spend(self._max_per_run)
        key = _bounded_text(run_key) or "<unkeyed>"
        counter = self._counts.get(key)
        if counter is None:
            if len(self._counts) >= self._max_tracked_runs:
                if not self._saturation_announced:
                    self._saturation_announced = True
                    logger.warning(
                        "AD-1224: standalone recording scope exhausted its "
                        "identity capacity; untracked pairs are dropped without "
                        "re-admitting prior runs, while tool execution continues",
                    )
                return False, False
            counter = _RunRecordCounter()
            self._counts[key] = counter
        return counter.spend(self._max_per_run)

    @property
    def max_per_run(self) -> int:
        """The effective pair cap, including any stricter cap in this run."""
        scoped = _RUN_RECORD_COUNTER.get()
        if scoped is not None and scoped.limit is not None:
            return min(self._max_per_run, scoped.limit)
        return self._max_per_run


@dataclass
class InvocationContext:
    """Context passed through the hook chain (AD-448)."""

    agent_id: str
    tool_id: str
    params: dict[str, Any]
    start_time: float = field(default_factory=time.perf_counter)
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    invocation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    record_durable: bool = field(default=False, init=False)
    record_tool_id: str | None = field(default=None, init=False)
    record_metadata: dict[str, Any] = field(default_factory=dict, init=False)
    record_started: bool = field(default=False, init=False)
    record_completed: bool = field(default=False, init=False)
    start_event_id: int | None = field(default=None, init=False)


class ToolExecutor:
    """Wraps ToolRegistry with pre/post invocation hooks (AD-448).

    Usage:
        executor = ToolExecutor(registry=tool_registry)
        executor.add_pre_hook(my_audit_hook)
        result = await executor.invoke(agent_id, tool_id, params, ...)

    The executor delegates ALL permission checks and invocation to
    ToolRegistry.check_and_invoke(). It adds:
    - Pre-hooks: run before invocation. If any returns False, invocation
      is aborted with an error ToolResult.
    - Post-hooks: run after invocation with the result.
    - Timing: elapsed time is recorded on InvocationContext.
    """

    def __init__(self, *, registry: Any) -> None:
        self._registry = registry
        self._pre_hooks: list[PreHook] = []
        self._post_hooks: list[PostHook] = []
        self._terminal_hooks: list[PostHook] = []

    def add_pre_hook(self, hook: PreHook) -> None:
        """Register a pre-invocation hook."""
        self._pre_hooks.append(hook)

    def add_post_hook(self, hook: PostHook) -> None:
        """Register a post-invocation hook."""
        self._post_hooks.append(hook)

    def add_terminal_hook(self, hook: PostHook) -> None:
        """Observe pre-hook aborts and registry exceptions, but not cancellation.

        These are distinct from normal post-hooks: AD-1168 must not count
        refusals as tool faults. An unmatched start means an incomplete recorded
        attempt, including interruption or a failed completion write.
        """
        self._terminal_hooks.append(hook)

    async def _run_terminal_hooks(
        self, hook_context: dict[str, Any], result: "ToolResult",
    ) -> None:
        for hook in self._terminal_hooks:
            try:
                observed = hook(hook_context, result)
                if inspect.isawaitable(observed):
                    await observed
            except Exception:
                logger.warning(
                    "AD-1224: terminal observer failed for tool=%s; execution "
                    "semantics are preserved and recorded completion may be missing",
                    _retained_metadata(hook_context)["tool_id"],
                )

    def _resolve_tool_id(self, tool_id: str) -> str | None:
        """BF-754: accept the provider-safe alias the model was actually shown.

        A tool id the provider rejects (``mcp:{server}:{tool}``) is offered
        under a sanitised alias, so the name that comes back is not the
        registry key. Resolved here rather than in the loop because this is the
        one point every call path shares.

        Returns the canonical id, the name unchanged when nothing claims it, or
        ``None`` when the name is AMBIGUOUS and the caller must refuse.

        BF-757 corrected two things here. This began with an
        ``if registry.get(tool_id) is not None: return tool_id`` fast path, so
        an exact id short-circuited before any ambiguity check ever ran -- and
        then ``resolved or tool_id`` turned a refusal back into the colliding
        id. Both meant the refusal existed in the helper and never reached the
        consumer: measured, the model was shown the aliased tool's definition
        and the executor invoked the other one. A helper that is correct while
        its caller bypasses it is the defect shape this repo produces most.

        An unresolvable name still falls through UNCHANGED. BF-757 recorded
        here that ``ToolRegistry.check_and_invoke`` then raised
        ``ToolPermissionDenied`` for a name that simply did not exist -- the
        agent was told it lacked access to a tool nobody has. #1214 fixed that
        at the registry: existence is now checked before permission, so an
        unknown name returns a not-found ``ToolResult`` and a typo no longer
        reaches ``denied_tools`` or the denial audit trail.
        """
        registry = self._registry
        if registry is None or type(tool_id) is not str:
            return tool_id
        claimants = _catalog_claimants(tool_id, registry)
        if claimants is None:
            logger.debug(
                "BF-754: catalog resolution unavailable for tool=%s; passing "
                "the original name to the registry permission chain",
                _opaque_tool_identity(tool_id),
            )
            return tool_id
        if len(claimants) > 1:
            logger.error(
                "BF-757: refusing ambiguous tool=%s with %d catalog claimants; "
                "neither tool will be invoked",
                _opaque_tool_identity(tool_id), len(claimants),
            )
            return None
        return claimants[0] if claimants else tool_id

    async def invoke(
        self,
        agent_id: str,
        tool_id: str,
        params: dict[str, Any],
        **kwargs: Any,
    ) -> "ToolResult":
        """Execute a tool call with pre/post hooks.

        Delegates to ToolRegistry.check_and_invoke() for permission
        checking and actual invocation. Pre-hook aborts return an error
        ToolResult. Pre-hook exceptions are logged and fail open so the
        registry permission chain remains the authority.

        Args:
            agent_id: The agent requesting the tool
            tool_id: The tool to invoke
            params: Tool parameters
            **kwargs: Forwarded to check_and_invoke (required, agent_department,
                      agent_rank, agent_types, context)
        """
        from probos.tools.protocol import ToolResult

        record_tool_id = tool_record_identity(tool_id, catalog=self._registry)
        resolved = self._resolve_tool_id(tool_id)
        if resolved is None:
            # BF-757: ambiguous. Refusing is the only safe answer -- invoking
            # either claimant could run a tool the model never chose. An error
            # ToolResult (not a raise) keeps this in the agent's own retry path
            # rather than aborting the turn.
            return ToolResult(
                error=(
                    f"Tool name {tool_id!r} is ambiguous and was not invoked. "
                    "Two registered tools would be offered under that name."
                ),
            )
        tool_id = resolved
        ctx = InvocationContext(
            agent_id=agent_id,
            tool_id=tool_id,
            params=params,
        )
        ctx.record_tool_id = record_tool_id
        hook_context = {
            "agent_id": agent_id,
            "tool_id": tool_id,
            "params": params,
            "invocation": ctx,
            "context": kwargs.get("context"),
        }

        for hook in self._pre_hooks:
            try:
                admitted = hook(hook_context)
                if inspect.isawaitable(admitted):
                    admitted = await admitted
            except Exception:
                logger.warning(
                    "AD-448: pre-hook failed for tool=%s; continuing to the "
                    "registry permission chain without retaining hook diagnostics",
                    record_tool_id,
                )
                continue
            if not admitted:
                logger.debug(
                    "AD-448: pre-hook aborted tool=%s; returning the refusal "
                    "and notifying terminal observers",
                    record_tool_id,
                )
                aborted = ToolResult(error=f"Pre-hook aborted invocation of {tool_id}")
                ctx.duration_ms = max(0.0, (time.perf_counter() - ctx.start_time) * 1000)
                await self._run_terminal_hooks(hook_context, aborted)
                return aborted

        try:
            result = await self._registry.check_and_invoke(
                agent_id, tool_id, params, **kwargs,
            )
        except Exception as exc:
            ctx.duration_ms = max(0.0, (time.perf_counter() - ctx.start_time) * 1000)
            await self._run_terminal_hooks(
                hook_context, ToolResult(error=_exception_category(exc)),
            )
            raise

        ctx.duration_ms = max(0.0, (time.perf_counter() - ctx.start_time) * 1000)

        for hook in self._post_hooks:
            try:
                observed = hook(hook_context, result)
                if inspect.isawaitable(observed):
                    await observed
            except Exception:
                logger.warning(
                    "AD-448: post-hook failed for tool=%s; returning the "
                    "original tool result without retaining hook diagnostics",
                    record_tool_id,
                )

        return result

    @property
    def hook_count(self) -> int:
        """Total registered hooks."""
        return len(self._pre_hooks) + len(self._post_hooks) + len(self._terminal_hooks)


def _invocation(ctx: dict[str, Any]) -> InvocationContext | None:
    invocation = ctx.get("invocation")
    return invocation if type(invocation) is InvocationContext else None


def _retained_metadata(
    ctx: dict[str, Any], catalog: ToolCatalog | None = None,
    *,
    work_item_id_provider: Callable[[], str | None] | None = None,
) -> dict[str, Any]:
    invocation = _invocation(ctx)
    if invocation is not None and invocation.record_metadata:
        metadata = dict(invocation.record_metadata)
    else:
        call_context = ctx.get("context")
        if type(call_context) is not dict:
            call_context = {}
        identity = invocation.record_tool_id if invocation is not None else None
        if identity is None:
            identity = tool_record_identity(ctx.get("tool_id"), catalog=catalog)
        metadata = {
            "invocation_id": _bounded_text(invocation.invocation_id) if invocation else None,
            "agent_id": _bounded_text(ctx.get("agent_id")),
            "tool_id": identity,
            "thread_id": _bounded_text(call_context.get("thread_id")),
            "work_item_id": _bounded_text(call_context.get("_crew_work_item_id")),
            "run_id": _bounded_text(call_context.get("_agentic_run_id")),
            "iteration": _bounded_int(call_context.get("iteration")),
        }
    work_item_id = sample_recording_identity(work_item_id_provider)
    if work_item_id is not None:
        if metadata["work_item_id"] is None:
            metadata["work_item_id"] = work_item_id
        elif metadata["work_item_id"] != work_item_id:
            logger.warning(
                "AD-1224: diagnostic work-item association conflicts with the "
                "recorded identity; preserving the original association and execution",
            )
    if invocation is not None:
        invocation.record_metadata = dict(metadata)
    return metadata


def _record_size(payload: dict[str, Any]) -> int:
    """Conservative serialized envelope, including EventLog-owned columns."""
    return _json_size({
        "id": 2**63 - 1, "timestamp": "2000-01-01T00:00:00.000000+00:00",
        "category": _TOOL_EVENT_CATEGORY, "event": "tool_record_budget_exhausted",
        "agent_id": payload.get("agent_id"), "agent_type": None, "pool": None,
        "detail": payload["tool_id"], "correlation_id": payload.get("invocation_id"),
        "parent_event_id": 2**63 - 1, "prev_hash": "0" * 64, "row_hash": "0" * 64,
        "data": json.dumps(payload, sort_keys=True),
    })


def _bounded_record(payload: dict[str, Any]) -> dict[str, Any]:
    params = payload.get("params")
    if params is not None and _record_size(payload) > _RECORD_MAX_BYTES:
        params = dict(params)
        params["fields"] = []
        params["keys_omitted"] = params["key_count"]
        if "non_dict" in params:
            params["non_dict"] = dict(params["non_dict"])
            _collapse_shape(params["non_dict"])
        params["detail_omitted"] = True
        payload = {**payload, "params": params}
    return payload


def _emit_record(
    emit_fn: Callable[[Any, dict[str, Any]], None] | None,
    event: Any,
    payload: dict[str, Any],
) -> None:
    if emit_fn is None:
        return
    try:
        emit_fn(event, payload)
    except Exception:
        logger.warning(
            "AD-1224: lifecycle event emission failed for tool=%s; durable "
            "writes are independent and tool execution is unaffected",
            payload["tool_id"],
        )


def make_audit_hook(
    emit_fn: Callable[[Any, dict[str, Any]], None] | None = None,
    *,
    event_log: Any = None,
    catalog: ToolCatalog | None = None,
    work_item_id_provider: Callable[[], str | None] | None = None,
) -> PostHook:
    """Emit safe TOOL_INVOKED metadata and optionally complete a durable pair.

    Bus-only use stays synchronous. Both retention sinks receive the same
    closed error category; the bus keeps its compatible error key. Neither
    sink receives raw errors, results or parameters. Durable writes require an
    acknowledged start, and bus failures cannot suppress them. ToolResult and
    the execution context remain unchanged for other post-hooks.
    """

    def audit_hook(
        ctx: dict[str, Any], result: "ToolResult",
    ) -> None | Awaitable[None]:
        from probos.events import EventType

        invocation = _invocation(ctx)
        duration = invocation.duration_ms if invocation is not None else 0.0
        if type(duration) is not float and type(duration) is not int:
            duration = 0.0
        if not math.isfinite(duration) or duration < 0:
            duration = 0.0
        category = classify_tool_error(result.error)
        payload = _bounded_record({
            **_retained_metadata(
                ctx, catalog,
                work_item_id_provider=work_item_id_provider if event_log is not None else None,
            ),
            "duration_ms": duration,
            "timestamp": time.time(), "is_error": result.error is not None,
            "error_category": category,
        })

        def emit() -> None:
            _emit_record(emit_fn, EventType.TOOL_INVOKED, {**payload, "error": category})

        if event_log is None:
            emit()
            return None

        async def complete() -> None:
            if (
                invocation is not None and invocation.record_durable
                and not invocation.record_completed
            ):
                invocation.record_completed = True
                try:
                    row_id = await event_log.log(
                        category=_TOOL_EVENT_CATEGORY,
                        event=EventType.TOOL_INVOKED.value,
                        agent_id=payload["agent_id"], detail=payload["tool_id"],
                        correlation_id=payload["invocation_id"],
                        parent_event_id=invocation.start_event_id, data=payload,
                    )
                    if type(row_id) is not int or row_id <= 0:
                        logger.warning(
                            "AD-1224: completion was not acknowledged for tool=%s; "
                            "the start remains an incomplete recorded attempt",
                            payload["tool_id"],
                        )
                except Exception:
                    logger.warning(
                        "AD-1224: completion write failed for tool=%s; the "
                        "original result is preserved and the start may be unpaired",
                        payload["tool_id"],
                    )
            emit()

        return complete()

    return audit_hook


def make_start_hook(
    emit_fn: Callable[[Any, dict[str, Any]], None] | None = None,
    *,
    event_log: Any = None,
    max_records_per_run: int = DEFAULT_MAX_RECORDS_PER_RUN,
    catalog: ToolCatalog | None = None,
    work_item_id_provider: Callable[[], str | None] | None = None,
) -> PreHook:
    """Await a bounded, committed start before the registry executes a tool.

    The pair budget is spent once even if persistence fails. Completion becomes
    eligible only on an inserted row ID. Zero cap emits one disabled explanation
    per run. This observer fails open toward the unchanged permission chain;
    cancellation propagates without manufacturing a terminal completion.
    """
    budget = ToolRecordBudget(max_per_run=max_records_per_run)

    async def start_hook(ctx: dict[str, Any]) -> bool:
        from probos.events import EventType

        invocation = _invocation(ctx)
        if invocation is not None:
            if invocation.record_started:
                return True
            invocation.record_started = True
            invocation.record_durable = False
        metadata = _retained_metadata(
            ctx, catalog,
            work_item_id_provider=work_item_id_provider if event_log is not None else None,
        )
        run_key = (
            metadata["run_id"] or metadata["work_item_id"]
            or metadata["thread_id"] or metadata["agent_id"] or "<unkeyed>"
        )
        record, announce = budget.spend(run_key)
        if announce:
            await _log_budget_exhausted(
                event_log=event_log, emit_fn=emit_fn, metadata=metadata,
                run_key=run_key, max_per_run=budget.max_per_run,
            )
        if not record:
            return True
        payload = _bounded_record({
            **metadata, "params": digest_params(ctx.get("params")),
            "timestamp": time.time(),
        })
        if event_log is not None:
            try:
                row_id = await event_log.log(
                    category=_TOOL_EVENT_CATEGORY, event=EventType.TOOL_STARTED.value,
                    agent_id=metadata["agent_id"], detail=metadata["tool_id"],
                    correlation_id=metadata["invocation_id"], data=payload,
                )
                if type(row_id) is int and row_id > 0:
                    if invocation is not None:
                        invocation.start_event_id = row_id
                        invocation.record_durable = True
                else:
                    logger.warning(
                        "AD-1224: start was not acknowledged for tool=%s; "
                        "execution continues without a durable completion row",
                        metadata["tool_id"],
                    )
            except Exception:
                logger.warning(
                    "AD-1224: start write failed for tool=%s; execution continues "
                    "without a durable completion row or retained error text",
                    metadata["tool_id"],
                )
        _emit_record(emit_fn, EventType.TOOL_STARTED, payload)
        return True

    return start_hook


async def _log_budget_exhausted(
    *,
    event_log: Any,
    emit_fn: Callable[[Any, dict[str, Any]], None] | None,
    metadata: dict[str, Any],
    run_key: str,
    max_per_run: int,
) -> None:
    from probos.events import EventType

    payload = _bounded_record({
        **metadata, "run_key": run_key, "max_records_per_run": max_per_run,
        "reason": "disabled" if max_per_run == 0 else "exhausted",
        "timestamp": time.time(),
    })
    logger.warning(
        "AD-1224: recording pair cap %d reached for tool=%s; subsequent pairs "
        "are omitted in this run while tool execution continues",
        max_per_run, metadata["tool_id"],
    )
    if event_log is not None:
        try:
            row_id = await event_log.log(
                category=_TOOL_EVENT_CATEGORY,
                event=EventType.TOOL_RECORD_BUDGET_EXHAUSTED.value,
                agent_id=metadata["agent_id"], detail=metadata["tool_id"], data=payload,
            )
            if type(row_id) is not int or row_id <= 0:
                logger.warning(
                    "AD-1224: budget explanation was not acknowledged for "
                    "tool=%s; omitted pairs remain unavailable in durable history",
                    metadata["tool_id"],
                )
        except Exception:
            logger.warning(
                "AD-1224: budget explanation write failed for tool=%s; omitted "
                "pairs remain unavailable and tool execution continues",
                metadata["tool_id"],
            )
    _emit_record(emit_fn, EventType.TOOL_RECORD_BUDGET_EXHAUSTED, payload)


def wire_durable_tool_records(
    executor: ToolExecutor,
    *,
    event_log: Any,
    emit_fn: Callable[[Any, dict[str, Any]], None] | None = None,
    work_item_id_provider: Callable[[], str | None] | None = None,
) -> bool:
    """Wire one durable pair; remain inert without an EventLog.

    Terminal completion is durable-only. Dispatch omits emit_fn entirely, so
    enabling durability there introduces no lifecycle bus traffic.
    """
    if event_log is None:
        return False
    executor.add_pre_hook(make_start_hook(
        emit_fn=emit_fn, event_log=event_log, work_item_id_provider=work_item_id_provider,
    ))
    executor.add_post_hook(make_audit_hook(
        event_log=event_log, work_item_id_provider=work_item_id_provider,
    ))
    executor.add_terminal_hook(make_audit_hook(
        event_log=event_log, work_item_id_provider=work_item_id_provider,
    ))
    return True


def wire_tool_invocation_hooks(
    executor: ToolExecutor,
    *,
    emit_fn: Callable[[Any, dict[str, Any]], None] | None = None,
    event_log: Any = None,
    work_item_id_provider: Callable[[], str | None] | None = None,
) -> bool:
    """Keep the legacy live post-hook and add the optional durable lifecycle."""
    wired = wire_durable_tool_records(
        executor, event_log=event_log, emit_fn=emit_fn,
        work_item_id_provider=work_item_id_provider,
    )
    executor.add_post_hook(make_audit_hook(emit_fn=emit_fn))
    return wired
