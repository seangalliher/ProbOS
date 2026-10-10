"""Strict real-consumer effect adapters (AD-1316 amendment 1)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from probos.execution.effect_types import (
    AdapterCompletion,
    EffectAdapter,
    EffectCorrelation,
    EffectOperationView,
    EffectPermit,
    PreparedEffect,
    ReconciliationEvidence,
)
from probos.tools.protocol import Tool, ToolPermission, ToolResult


def _digest(domain: str, value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(domain.encode("ascii") + b"\x00" + encoded).hexdigest()


def _shape(context: dict[str, Any]) -> str:
    value = context.get("_protected_parameter_shape_sha256")
    return value if isinstance(value, str) and len(value) == 64 else ""


class _BaseEffectAdapter:
    kind = "opaque"

    def match_continuation(
        self, *, pending: EffectOperationView, prepared: PreparedEffect
    ) -> bool:
        return (
            pending.adapter_kind == prepared.adapter_kind
            and pending.continuation_binding_sha256
            == prepared.continuation_binding_sha256
        )

    async def reconcile(
        self, operation: EffectOperationView
    ) -> ReconciliationEvidence | None:
        return None

    def project_result(self, result: ToolResult) -> AdapterCompletion:
        if result.error is not None:
            return AdapterCompletion(
                outcome="failed",
                reason_code="consumer_failed",
                delivery_state="completed",
                retry_disposition="terminal",
                result_sha256=_digest(
                    "probos.effect-result-shape.v1",
                    {"type": type(result.output).__name__, "error": True},
                ),
            )
        return AdapterCompletion(
            outcome="result",
            reason_code="completed",
            delivery_state="completed",
            retry_disposition="terminal",
            result_sha256=_digest(
                "probos.effect-result-shape.v1",
                {"type": type(result.output).__name__, "error": False},
            ),
        )


class _NativeFileEffectAdapter(_BaseEffectAdapter):
    kind = "native_file"

    def __init__(self, *, tool: Tool, edit: bool) -> None:
        self._tool = tool
        self._edit = edit

    def prepare(
        self,
        *,
        tool_id: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> PreparedEffect:
        path = params.get("path")
        if not isinstance(path, str) or not path:
            canonical = ""
            denial = "file_target_invalid"
        else:
            try:
                resolver = getattr(self._tool, "resolve_effect_target", None)
                if resolver is None:
                    raise ValueError("native file target resolver unavailable")
                target = resolver(path)
                if not isinstance(target, Path):
                    raise ValueError("native file target resolver returned invalid path")
                canonical = str(target)
                denial = ""
            except (OSError, RuntimeError, ValueError):
                canonical = ""
                denial = "file_target_resolution_failed"
        if self._edit:
            continuation = _digest(
                "probos.native-file-edit-continuation.v1",
                {
                    "target": canonical,
                    "old": _digest("probos.native-file-old.v1", params.get("old_text")),
                    "new": _digest("probos.native-file-new.v1", params.get("new_text")),
                    "all": params.get("replace_all") is True,
                },
            )
            idempotency = "non_idempotent"
            retry = "blocked"
        else:
            continuation = _digest(
                "probos.native-file-write-continuation.v1",
                {
                    "target": canonical,
                    "content": _digest(
                        "probos.native-file-content.v1", params.get("content")
                    ),
                },
            )
            idempotency = "idempotent"
            retry = "retry_same_operation"
        return PreparedEffect(
            requested_tool_id=tool_id,
            resolved_tool_id=tool_id,
            effect_class="filesystem",
            adapter_kind="native_file",
            canonical_target=canonical,
            parameter_shape_sha256=_shape(context),
            continuation_binding_sha256=continuation,
            isolation_binding_sha256="",
            idempotency=idempotency,
            retry_disposition=retry,
            denial_reason=denial,
        )


class _CodeExecutionEffectAdapter(_BaseEffectAdapter):
    kind = "code_backend"

    def prepare(
        self,
        *,
        tool_id: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> PreparedEffect:
        return PreparedEffect(
            requested_tool_id=tool_id,
            resolved_tool_id=tool_id,
            effect_class="code",
            adapter_kind="code_backend",
            canonical_target="strict-code-backend",
            parameter_shape_sha256=_shape(context),
            continuation_binding_sha256=_digest(
                "probos.strict-code-continuation.v1", {"tool": tool_id}
            ),
            isolation_binding_sha256="",
            idempotency="opaque",
            retry_disposition="blocked",
            denial_reason="code_isolation_unproven",
        )


class _ShellEffectAdapter(_BaseEffectAdapter):
    kind = "opaque"

    def prepare(
        self,
        *,
        tool_id: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> PreparedEffect:
        return PreparedEffect(
            requested_tool_id=tool_id,
            resolved_tool_id=tool_id,
            effect_class="shell",
            adapter_kind="opaque",
            canonical_target="strict-shell-backend",
            parameter_shape_sha256=_shape(context),
            continuation_binding_sha256=_digest(
                "probos.strict-shell-continuation.v1", {"tool": tool_id}
            ),
            isolation_binding_sha256="",
            idempotency="opaque",
            retry_disposition="blocked",
            denial_reason="shell_isolation_unproven",
        )


class _McpEffectAdapter(_BaseEffectAdapter):
    kind = "mcp"

    def __init__(self, tool: Tool) -> None:
        self._tool = tool

    def prepare(
        self,
        *,
        tool_id: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> PreparedEffect:
        target = {
            "server": getattr(self._tool, "_server_id", ""),
            "tool": getattr(self._tool, "_tool_name", ""),
        }
        return PreparedEffect(
            requested_tool_id=tool_id,
            resolved_tool_id=tool_id,
            effect_class="mcp",
            adapter_kind="mcp",
            canonical_target=_digest("probos.mcp-target.v1", target),
            parameter_shape_sha256=_shape(context),
            continuation_binding_sha256=_digest(
                "probos.mcp-continuation.v1",
                {"target": target, "params": _digest("probos.mcp-params.v1", params)},
            ),
            isolation_binding_sha256="",
            idempotency="opaque",
            retry_disposition="blocked",
        )


class _MeshEffectAdapter(_BaseEffectAdapter):
    kind = "mesh"

    def __init__(self, tool: Tool) -> None:
        self._tool = tool

    def prepare(
        self,
        *,
        tool_id: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> PreparedEffect:
        intent = getattr(self._tool, "_intent_name", "")
        return PreparedEffect(
            requested_tool_id=tool_id,
            resolved_tool_id=tool_id,
            effect_class="network",
            adapter_kind="mesh",
            canonical_target=_digest("probos.mesh-target.v1", intent),
            parameter_shape_sha256=_shape(context),
            continuation_binding_sha256=_digest(
                "probos.mesh-continuation.v1",
                {"intent": intent, "params": _digest("probos.mesh-params.v1", params)},
            ),
            isolation_binding_sha256="",
            idempotency="provider_keyed",
            retry_disposition="reconcile",
        )


class _DelegationEffectAdapter(_BaseEffectAdapter):
    kind = "delegation"

    def prepare(
        self,
        *,
        tool_id: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> PreparedEffect:
        return PreparedEffect(
            requested_tool_id=tool_id,
            resolved_tool_id=tool_id,
            effect_class="delegation",
            adapter_kind="delegation",
            canonical_target=_digest(
                "probos.delegation-target.v1",
                {"agent": params.get("agent_id"), "department": params.get("department")},
            ),
            parameter_shape_sha256=_shape(context),
            continuation_binding_sha256=_digest(
                "probos.delegation-continuation.v1",
                {"task": _digest("probos.delegation-task.v1", params)},
            ),
            isolation_binding_sha256="",
            idempotency="opaque",
            retry_disposition="blocked",
        )


class _OpaqueEffectAdapter(_BaseEffectAdapter):
    def prepare(
        self,
        *,
        tool_id: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> PreparedEffect:
        return PreparedEffect(
            requested_tool_id=tool_id,
            resolved_tool_id=tool_id,
            effect_class="tool",
            adapter_kind="opaque",
            canonical_target=_digest("probos.opaque-target.v1", tool_id),
            parameter_shape_sha256=_shape(context),
            continuation_binding_sha256=_digest(
                "probos.opaque-continuation.v1", {"tool": tool_id}
            ),
            isolation_binding_sha256="",
            idempotency="opaque",
            retry_disposition="blocked",
        )


class _EffectAdapterRegistry:
    """Select strict semantics only from the registered concrete tool."""

    def for_tool(self, tool: Tool, requested_tool_id: str) -> EffectAdapter:
        module = type(tool).__module__
        name = type(tool).__name__
        if module == "probos.cognitive.swe_harness.tools" and name == "WriteFileTool":
            return _NativeFileEffectAdapter(tool=tool, edit=False)
        if module == "probos.cognitive.swe_harness.tools" and name == "EditFileTool":
            return _NativeFileEffectAdapter(tool=tool, edit=True)
        if module == "probos.tools.code_execution_tool" and name == "CodeExecutionTool":
            return _CodeExecutionEffectAdapter()
        if module == "probos.cognitive.swe_harness.tools" and name == "RunCommandTool":
            return _ShellEffectAdapter()
        if name == "_McpTool":
            return _McpEffectAdapter(tool)
        if name == "_MeshIntentTool":
            return _MeshEffectAdapter(tool)
        if requested_tool_id == "delegate_task":
            return _DelegationEffectAdapter()
        return _OpaqueEffectAdapter()


class StrictEffectPrivacyProjector:
    """Produce allowlisted strict surfaces without raw consumer values."""

    _OUTCOMES = frozenset({"result", "denied", "failed", "cancelled", "unknown"})
    _REASON_CHARS = frozenset(
        "abcdefghijklmnopqrstuvwxyz0123456789_"
    )
    _IDENTIFIER_CHARS = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    )
    _TOKEN_SOURCES = frozenset({"measured", "estimated", "mixed"})
    _DIAGNOSTIC_CORRELATION_LIMIT = 400

    @classmethod
    def _reason(cls, value: str) -> str:
        if (
            type(value) is not str
            or not 1 <= len(value) <= 64
            or any(character not in cls._REASON_CHARS for character in value)
        ):
            raise ValueError("strict reason code is not bounded")
        return value

    @classmethod
    def _correlation(cls, value: EffectCorrelation) -> EffectCorrelation:
        if (
            type(value) is not EffectCorrelation
            or type(value.outcome) is not str
            or value.outcome not in cls._OUTCOMES
        ):
            raise ValueError("strict correlation is not trusted")
        cls._reason(value.reason_code)
        return value

    @classmethod
    def sanitize_diagnostic_correlation(
        cls,
        value: object,
    ) -> EffectCorrelation | None:
        if type(value) is not EffectCorrelation:
            return None
        try:
            operation_id = value.operation_id
            attempt_id = value.attempt_id
            outcome = value.outcome
            reason_code = value.reason_code
        except AttributeError:
            return None
        if (
            type(operation_id) is not str
            or not 1 <= len(operation_id) <= 128
            or any(
                character not in cls._IDENTIFIER_CHARS
                for character in operation_id
            )
            or type(attempt_id) is not str
            or not 1 <= len(attempt_id) <= 128
            or any(
                character not in cls._IDENTIFIER_CHARS
                for character in attempt_id
            )
            or type(outcome) is not str
            or outcome not in cls._OUTCOMES
        ):
            return None
        try:
            cls._reason(reason_code)
        except ValueError:
            return None
        return value

    @classmethod
    def sanitize_diagnostic_correlations(
        cls,
        values: object,
        *,
        limit: int,
    ) -> tuple[EffectCorrelation, ...]:
        bounded_limit = (
            min(max(limit, 0), cls._DIAGNOSTIC_CORRELATION_LIMIT)
            if type(limit) is int
            else 0
        )
        if bounded_limit == 0:
            return ()
        try:
            iterator = iter(values)
        except Exception:
            return ()
        retained: list[EffectCorrelation] = []
        for _ in range(bounded_limit):
            try:
                value = next(iterator)
            except StopIteration:
                break
            except Exception:
                break
            trusted = cls.sanitize_diagnostic_correlation(value)
            if trusted is not None:
                retained.append(trusted)
        return tuple(
            sorted(
                retained,
                key=lambda value: (
                    value.operation_id,
                    value.attempt_id,
                    value.outcome,
                    value.reason_code,
                ),
            )
        )

    @staticmethod
    def tool_digest(tool_id: str) -> str:
        if type(tool_id) is not str:
            raise ValueError("strict tool identity must be text")
        return _digest("probos.strict-tool-id.v1", tool_id)

    @staticmethod
    def _count(value: object) -> int:
        return min(max(value, 0), 2**31 - 1) if type(value) is int else 0

    @staticmethod
    def _identifier_digest(domain: str, value: str) -> str:
        if type(value) is not str:
            raise ValueError("strict identifier must be text")
        return _digest(domain, value)

    def project_iteration(
        self,
        *,
        agent_id: str,
        run_id: str | None,
        iteration: int,
        tool_ids: tuple[str, ...],
        total_tokens: int,
        token_source: str | None,
    ) -> dict[str, Any]:
        if type(tool_ids) is not tuple or any(type(value) is not str for value in tool_ids):
            raise ValueError("strict tool history must be typed")
        payload: dict[str, Any] = {
            "phase": "iteration",
            "iteration": self._count(iteration),
            "total_tokens": self._count(total_tokens),
            "tool_count": self._count(len(tool_ids)),
            "unique_tool_count": self._count(len(set(tool_ids))),
            "tool_history_digest": _digest(
                "probos.strict-tool-history.v1", tool_ids
            ),
            "agent_digest": self._identifier_digest(
                "probos.strict-agent-id.v1", agent_id
            ),
        }
        if run_id is not None:
            payload["run_digest"] = self._identifier_digest(
                "probos.strict-run-id.v1", run_id
            )
        if token_source in self._TOKEN_SOURCES:
            payload["token_source"] = token_source
        return payload

    def project_permission_denial(
        self,
        *,
        permit: EffectPermit,
        agent_id: str,
        tool_id: str,
        required: ToolPermission,
        held: ToolPermission,
        parameter_names: tuple[str, ...],
    ) -> dict[str, Any]:
        if type(permit) is not EffectPermit:
            raise ValueError("strict permission denial requires a permit")
        if type(required) is not ToolPermission or type(held) is not ToolPermission:
            raise ValueError("strict permission values are invalid")
        if (
            type(parameter_names) is not tuple
            or any(type(value) is not str for value in parameter_names)
        ):
            raise ValueError("strict parameter names must be typed")
        return {
            "operation_id": permit.operation_id,
            "attempt_id": permit.attempt_id,
            "outcome": "denied",
            "reason_code": "permission_denied",
            "agent_digest": self._identifier_digest(
                "probos.strict-agent-id.v1", agent_id
            ),
            "tool_digest": self.tool_digest(tool_id),
            "required": required.value,
            "held": held.value,
            "parameter_count": self._count(len(parameter_names)),
            "parameter_digest": _digest(
                "probos.strict-parameter-names.v1", parameter_names
            ),
        }

    def project_tool_record(
        self,
        *,
        phase: Literal["started", "completed", "budget_exhausted"],
        correlation: EffectCorrelation,
        agent_id: str,
        tool_id: str,
        run_id: str,
        thread_id: str,
        work_item_id: str,
        invocation_id: str,
        parameter_names: tuple[str, ...] = (),
        duration_ms: float | None = None,
        is_error: bool | None = None,
        error_code: str = "",
        record_count: int | None = None,
    ) -> dict[str, Any]:
        if phase not in {"started", "completed", "budget_exhausted"}:
            raise ValueError("strict tool record phase is invalid")
        trusted = self._correlation(correlation)
        if (
            type(parameter_names) is not tuple
            or any(type(value) is not str for value in parameter_names)
        ):
            raise ValueError("strict parameter names must be typed")
        payload: dict[str, Any] = {
            "phase": phase,
            "operation_id": trusted.operation_id,
            "attempt_id": trusted.attempt_id,
            "outcome": trusted.outcome,
            "reason_code": trusted.reason_code,
            "agent_digest": self._identifier_digest(
                "probos.strict-agent-id.v1", agent_id
            ),
            "tool_digest": self.tool_digest(tool_id),
            "run_digest": self._identifier_digest(
                "probos.strict-run-id.v1", run_id
            ),
            "thread_digest": self._identifier_digest(
                "probos.strict-thread-id.v1", thread_id
            ),
            "work_item_digest": self._identifier_digest(
                "probos.strict-work-item-id.v1", work_item_id
            ),
            "invocation_digest": self._identifier_digest(
                "probos.strict-invocation-id.v1", invocation_id
            ),
            "parameter_count": self._count(len(parameter_names)),
            "parameter_digest": _digest(
                "probos.strict-parameter-names.v1", parameter_names
            ),
        }
        if type(duration_ms) in {int, float}:
            payload["duration_ms"] = min(
                max(float(duration_ms), 0.0), 86_400_000.0
            )
        if type(is_error) is bool:
            payload["is_error"] = is_error
        if error_code:
            payload["error_code"] = self._reason(error_code)
        if record_count is not None:
            payload["record_count"] = self._count(record_count)
        return payload

    def project_failure_log(
        self,
        *,
        operation: str,
        reason_code: str,
        correlations: object,
    ) -> dict[str, Any]:
        try:
            operation_value = self._reason(operation)
            reason = self._reason(reason_code)
        except ValueError:
            operation_value = "strict_diagnostic"
            reason = "strict_diagnostic_invalid"
        trusted = self.sanitize_diagnostic_correlations(
            correlations,
            limit=self._DIAGNOSTIC_CORRELATION_LIMIT,
        )
        pairs = tuple(
            {
                "operation_id": value.operation_id,
                "attempt_id": value.attempt_id,
                "outcome": value.outcome,
                "reason_code": value.reason_code,
            }
            for value in trusted
        )
        return {
            "operation": operation_value,
            "reason_code": reason,
            "correlation_count": self._count(len(pairs)),
            "correlation_digest": _digest(
                "probos.strict-effect-correlations.v1", pairs
            ),
            "correlations": pairs,
        }

    def project_event(
        self,
        *,
        phase: Literal["started", "completed"],
        tool_id: str,
        iteration: int,
        correlation: EffectCorrelation | None,
        is_error: bool | None,
        duration_ms: float | None,
    ) -> dict[str, Any]:
        if phase not in {"started", "completed"}:
            raise ValueError("strict event phase is invalid")
        if phase == "started" and correlation is not None:
            raise ValueError("strict started event cannot carry correlation")
        if phase == "completed" and correlation is None:
            raise ValueError("strict completed event requires correlation")
        if phase == "completed" and type(is_error) is not bool:
            raise ValueError("strict completed event requires error state")
        payload: dict[str, Any] = {
            "tool_digest": self.tool_digest(tool_id),
            "phase": phase,
            "iteration": min(max(iteration, 0), 2**31 - 1)
            if type(iteration) is int
            else 0,
        }
        if correlation is not None:
            trusted = self._correlation(correlation)
            payload.update(
                {
                    "operation_id": trusted.operation_id,
                    "attempt_id": trusted.attempt_id,
                    "outcome": trusted.outcome,
                    "reason_code": trusted.reason_code,
                }
            )
        if type(is_error) is bool:
            payload["is_error"] = is_error
        if type(duration_ms) in {int, float}:
            payload["duration_ms"] = min(max(float(duration_ms), 0.0), 86_400_000.0)
        return payload

    def project_refusal(self, *, correlation: EffectCorrelation) -> str:
        return self._correlation(correlation).reason_code

    def log_fields(
        self,
        *,
        correlation: object,
        operation: str,
        reason_code: str | None = None,
    ) -> dict[str, str]:
        try:
            operation_value = self._reason(operation)
        except ValueError:
            operation_value = "strict_diagnostic"
        trusted = self.sanitize_diagnostic_correlation(correlation)
        if trusted is None:
            return {
                "operation": operation_value,
                "reason_code": "correlation_unavailable",
            }
        try:
            reason = (
                trusted.reason_code
                if reason_code is None
                else self._reason(reason_code)
            )
        except ValueError:
            reason = "strict_diagnostic_invalid"
        return {
            "operation": operation_value,
            "operation_id": trusted.operation_id,
            "attempt_id": trusted.attempt_id,
            "outcome": trusted.outcome,
            "reason_code": reason,
        }

    def project_trace_entry(
        self,
        *,
        provider_call_id: str,
        tool_digest: str,
        parameter_names: tuple[str, ...],
        correlation: object,
        output_type: str,
        output_size: int,
        error_code: str,
    ) -> dict[str, Any]:
        return {
            "provider_call_digest": _digest(
                "probos.strict-provider-call.v1", provider_call_id
            ),
            "tool_digest": tool_digest,
            "correlation": correlation,
            "output_type": output_type,
            "output_size": max(0, output_size),
            "error_code": self._reason(error_code) if error_code else "",
        }


# Amendment-1 compatibility for internal consumers while new code uses the
# public lower-layer policy.
_StrictPrivacyProjector = StrictEffectPrivacyProjector
