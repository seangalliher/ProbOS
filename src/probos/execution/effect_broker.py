"""Runtime-owned governed effect dispatch and reconciliation (AD-1316)."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable

from probos.execution.authority import StaleGrantError, WitnessUnavailableError
from probos.execution.effect_types import (
    DelegationRunBinding,
    EffectCorrelation,
    EffectAttemptView,
    EffectClass,
    EffectDispatchContext,
    EffectDispatchResult,
    EffectDeliveryState,
    EffectFinishRequest,
    EffectIdempotency,
    EffectFailureEnvelope,
    EffectOperationHandle,
    EffectOperationView,
    EffectPermit,
    EffectReconciler,
    EffectRequest,
    EffectRetryDisposition,
    EffectReserveRequest,
    EffectTargetRequest,
    GovernedEffectBrokerProtocol,
    ProtectedEffectAuthorityProtocol,
    ReconciliationEvidence,
)
from probos.execution.effect_adapters import _EffectAdapterRegistry
from probos.tools.protocol import ToolPermission, ToolResult

logger = logging.getLogger(__name__)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ProtectedEffectError(RuntimeError):
    """Base error for strict governed effect dispatch."""


class ProtectedEffectBypassDenied(ProtectedEffectError):
    """A strict ToolRegistry invocation lacked a valid one-use permit."""


class InvalidEffectRequest(ProtectedEffectError):
    """Trusted runtime correlation is absent or malformed."""


class NoEffectFailure(ProtectedEffectError):
    """A trusted adapter proved that no external effect occurred."""

    def __init__(self, reason_code: str = "known_no_effect") -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class EffectDenied(ProtectedEffectError):
    """A pre-consumer control refused the operation."""

    def __init__(
        self,
        reason_code: str,
        *,
        result: ToolResult | None = None,
        cause: Exception | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.result = result
        self.cause = cause
        super().__init__(reason_code)


class CorrelatedEffectError(ProtectedEffectError):
    """Strict failure whose printable form cannot disclose consumer data."""

    def __init__(
        self,
        failure: EffectFailureEnvelope,
        *,
        operation_handle: EffectOperationHandle | None = None,
    ) -> None:
        self._failure = failure
        self.operation_handle = operation_handle
        super().__init__(failure.error_code)

    @property
    def failure(self) -> EffectFailureEnvelope:
        return self._failure


@dataclass(frozen=True, slots=True)
class EffectCoverageReport:
    covered: tuple[str, ...]
    conditional: tuple[str, ...]
    uncovered: tuple[str, ...]
    complete: bool


def effect_coverage_report() -> EffectCoverageReport:
    """Return the honest selected-agent boundary; this slice is not universal."""
    return EffectCoverageReport(
        covered=(
            "strict ToolExecutor/ToolRegistry filesystem",
            "strict ToolExecutor mesh adapters",
            "strict ToolExecutor MCP adapters",
            "strict ToolExecutor browser adapters",
            "strict ToolExecutor delegation",
        ),
        conditional=(
            "run_python is refused until a concrete strict isolation backend proves containment",
            "opaque shell requires manifest-bound isolation",
            "current MCP is opaque and replay-blocked without a negotiated receipt",
        ),
        uncovered=(
            "direct browser router and DM reply paths",
            "ordinary IntentBus and BaseAgent effects",
            "provider inference transport",
            "API routes",
            "notification transports",
            "federation transports",
        ),
        complete=False,
    )


def _digest(domain: str, value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(domain.encode("ascii") + b"\x00" + payload).hexdigest()


def _tool_digest(tool_id: str) -> str:
    return _digest("probos.effect-tool-id.v1", tool_id)


def _scoped_logical_key(runtime_session_id: str, logical_key: str) -> str:
    return f"{runtime_session_id}\x00{logical_key}"


class _EffectBrokerCore(GovernedEffectBrokerProtocol):
    """Deterministic durable boundary for effects already chosen by an agent."""

    def __init__(
        self,
        *,
        authority: ProtectedEffectAuthorityProtocol,
        runtime_session_id: str,
        lease_seconds: int,
        max_attempts: int,
        permit_secret: bytes | None = None,
    ) -> None:
        self._authority = authority
        self._runtime_session_id = runtime_session_id
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts
        self._permit_secret = permit_secret or secrets.token_bytes(32)
        self._accepting = False
        self._consumed_permits: set[tuple[str, str, str]] = set()
        self._started_permits: set[tuple[str, str, str]] = set()
        self._adapters = _EffectAdapterRegistry()

    @staticmethod
    def _unresolved_handle(
        request: EffectRequest,
        operation_id: str,
        attempt_id: str,
    ) -> EffectOperationHandle:
        return EffectOperationHandle(
            operation_id=operation_id,
            attempt_id=attempt_id,
            adapter_kind=request.adapter_kind,
            continuation_token=request.continuation_binding_sha256,
            outcome="unknown",
            retry_disposition="reconcile",
        )

    async def start(self) -> None:
        await self._authority.recover_effects()
        self._accepting = True

    async def stop(self) -> None:
        self._accepting = False
        await self._authority.shutdown_effects()

    def classify_tool(
        self,
        tool_id: str,
        params: dict[str, Any],
        required: ToolPermission,
        context: dict[str, Any],
    ) -> EffectRequest:
        logical_key = context.get("_protected_logical_key")
        if (
            not isinstance(logical_key, str)
            or not logical_key
            or len(logical_key.encode("utf-8", "replace")) > 512
        ):
            logical_key = ""
        agent_id = context.get("_protected_agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            raise InvalidEffectRequest("protected_agent_id_missing")
        shape_sha256 = context.get("_protected_parameter_shape_sha256")
        if not isinstance(shape_sha256, str) or _SHA256_RE.fullmatch(shape_sha256) is None:
            raise InvalidEffectRequest("parameter_shape_invalid")
        effect_class, idempotency = self._classify(tool_id, required, context)
        target = context.get("_protected_target_identity")
        if not isinstance(target, str) or not target:
            target = tool_id
        if (
            effect_class == "shell"
            and context.get("_strict_isolation_bound") is not True
        ):
            target = "strict_isolation_unbound"
        parent = context.get("_parent_operation_id")
        provider_call_id = context.get("_protected_provider_call_id")
        return EffectRequest(
            logical_key=logical_key,
            agent_id=agent_id,
            tool_id=tool_id,
            effect_class=effect_class,
            target_identity=target,
            parameter_shape_sha256=shape_sha256,
            idempotency=idempotency,
            parent_operation_id=parent if isinstance(parent, str) and parent else None,
            provider_call_id=(
                provider_call_id
                if isinstance(provider_call_id, str) and provider_call_id else None
            ),
        )

    async def prepare_tool(
        self,
        *,
        tool: Any,
        requested_tool_id: str,
        resolved_tool_id: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> EffectRequest:
        adapter = self._adapters.for_tool(tool, requested_tool_id)
        prepared = adapter.prepare(
            tool_id=resolved_tool_id, params=params, context=context
        )
        isolation = prepared.isolation_binding_sha256
        authorized_root = ""
        denial = prepared.denial_reason
        if prepared.adapter_kind == "native_file" and not denial:
            decision = await self._authority.authorize_effect_target(
                EffectTargetRequest(
                    effect_class=prepared.effect_class,
                    canonical_target=prepared.canonical_target,
                    adapter_kind=prepared.adapter_kind,
                )
            )
            isolation = decision.isolation_binding_sha256
            authorized_root = decision.authorized_root
            if not decision.allowed:
                denial = decision.reason_code
        agent_id = context.get("_protected_agent_id")
        if not isinstance(agent_id, str) or not agent_id:
            raise InvalidEffectRequest("protected_agent_id_missing")
        parent = context.get("_parent_operation_id")
        parent_attempt = context.get("_parent_attempt_id")
        child_run = context.get("_agentic_run_id")
        binding_token = context.get("_delegation_binding_token")
        delegation_supplied = any(
            key in context
            for key in (
                "_parent_operation_id",
                "_parent_attempt_id",
                "_delegation_binding_token",
            )
        )
        if delegation_supplied and not all(
            isinstance(value, str) and value
            for value in (parent, parent_attempt, child_run, binding_token)
        ):
            denial = denial or "delegation_binding_invalid"
        provider_call_id = context.get("_protected_provider_call_id")
        logical_key = context.get("_protected_logical_key")
        return EffectRequest(
            logical_key=logical_key if isinstance(logical_key, str) else "",
            agent_id=agent_id,
            tool_id=requested_tool_id,
            resolved_tool_id=resolved_tool_id,
            effect_class=prepared.effect_class,
            adapter_kind=prepared.adapter_kind,
            target_identity=prepared.canonical_target,
            parameter_shape_sha256=prepared.parameter_shape_sha256,
            continuation_binding_sha256=prepared.continuation_binding_sha256,
            isolation_binding_sha256=isolation,
            idempotency=prepared.idempotency,
            parent_operation_id=parent if isinstance(parent, str) and parent else None,
            parent_attempt_id=(
                parent_attempt
                if isinstance(parent_attempt, str) and parent_attempt else None
            ),
            child_run_id=child_run if isinstance(child_run, str) else "",
            binding_token=(
                binding_token if isinstance(binding_token, str) else ""
            ),
            provider_call_id=(
                provider_call_id
                if isinstance(provider_call_id, str) and provider_call_id else None
            ),
            preflight_denial_reason=denial,
            authorized_root=authorized_root,
        )

    def _classify(
        self,
        tool_id: str,
        required: ToolPermission,
        context: dict[str, Any],
    ) -> tuple[EffectClass, EffectIdempotency]:
        explicit_class = context.get("_effect_class")
        explicit_idempotency = context.get("_effect_idempotency")
        effect_class: EffectClass
        if explicit_class in {
            "filesystem", "shell", "code", "network", "mcp", "browser",
            "delegation", "tool",
        }:
            effect_class = explicit_class
        elif tool_id in {"write_file", "edit_file"}:
            effect_class = "filesystem"
        elif tool_id == "run_command":
            effect_class = "shell"
        elif tool_id == "run_python":
            effect_class = "code"
        elif tool_id.startswith("mcp:"):
            effect_class = "mcp"
        elif tool_id in {"web_search", "read_page", "http_fetch"}:
            effect_class = "network"
        elif "browser" in tool_id:
            effect_class = "browser"
        elif tool_id == "delegate_task":
            effect_class = "delegation"
        else:
            effect_class = "tool"
        if explicit_idempotency in {
            "idempotent", "provider_keyed", "non_idempotent", "opaque"
        }:
            idempotency: EffectIdempotency = explicit_idempotency
        elif required in {ToolPermission.WRITE, ToolPermission.FULL}:
            idempotency = "non_idempotent"
        else:
            idempotency = "idempotent"
        if effect_class in {"shell", "mcp", "browser", "delegation"}:
            idempotency = "opaque"
        return effect_class, idempotency

    def _mint_permit(self, request: EffectRequest) -> EffectPermit:
        operation_id = str(uuid.uuid4())
        attempt_id = str(uuid.uuid4())
        nonce = secrets.token_hex(16)
        generation = 0
        tool_id_sha256 = _tool_digest(request.tool_id)
        payload = (
            f"{operation_id}\x00{attempt_id}\x00{tool_id_sha256}\x00"
            f"{generation}\x00{nonce}"
        ).encode("ascii")
        signature = hmac.new(self._permit_secret, payload, hashlib.sha256).hexdigest()
        return EffectPermit(
            operation_id=operation_id,
            attempt_id=attempt_id,
            tool_id_sha256=tool_id_sha256,
            generation=generation,
            nonce=nonce,
            signature=signature,
        )

    def _resign_permit(self, permit: EffectPermit) -> EffectPermit:
        payload = (
            f"{permit.operation_id}\x00{permit.attempt_id}\x00"
            f"{permit.tool_id_sha256}\x00{permit.generation}\x00{permit.nonce}"
        ).encode("ascii")
        return EffectPermit(
            operation_id=permit.operation_id,
            attempt_id=permit.attempt_id,
            tool_id_sha256=permit.tool_id_sha256,
            generation=permit.generation,
            nonce=permit.nonce,
            signature=hmac.new(
                self._permit_secret, payload, hashlib.sha256
            ).hexdigest(),
        )

    async def start_permitted_effect(
        self, permit: EffectPermit, tool_id: str
    ) -> None:
        expected = self._resign_permit(permit)
        identity = (permit.operation_id, permit.attempt_id, permit.nonce)
        if (
            not hmac.compare_digest(expected.signature, permit.signature)
            or permit.tool_id_sha256 != _tool_digest(tool_id)
            or identity in self._consumed_permits
        ):
            raise ProtectedEffectBypassDenied("protected_effect_permit_refused")
        self._consumed_permits.add(identity)
        await self._authority.mark_effect_started(permit)
        self._started_permits.add(identity)

    def _permit_started(self, permit: EffectPermit) -> bool:
        return (
            permit.operation_id, permit.attempt_id, permit.nonce
        ) in self._started_permits

    def _permit_entered_start(self, permit: EffectPermit) -> bool:
        identity = (permit.operation_id, permit.attempt_id, permit.nonce)
        return identity in self._consumed_permits

class _EffectFinishMixin(_EffectBrokerCore):
    """Finalize durable effects through the protected authority."""

    async def _finish_or_correlate(
        self,
        request: EffectFinishRequest,
        *,
        delivery_state: EffectDeliveryState,
        retry_disposition: EffectRetryDisposition,
        operation_handle: EffectOperationHandle,
    ) -> None:
        try:
            await self._authority.finish_effect(request)
        except Exception as exc:
            raise CorrelatedEffectError(
                EffectFailureEnvelope(
                    correlation=EffectCorrelation(
                        request.operation_id,
                        request.attempt_id,
                        "unknown",
                        "witness_commit_failed",
                    ),
                    error_code="witness_commit_failed",
                    delivery_state=delivery_state,
                    retry_disposition=retry_disposition,
                ),
                operation_handle=operation_handle,
            ) from exc


class _EffectDispatchMixin(_EffectFinishMixin):
    """Execute durable effects without making cognitive choices."""

    async def dispatch(
        self,
        request: EffectRequest,
        invoke: Callable[[EffectDispatchContext], Awaitable[ToolResult]],
        operation_handle: EffectOperationHandle | None = None,
    ) -> EffectDispatchResult:
        if not self._accepting:
            raise WitnessUnavailableError("effect broker is not accepting dispatch")
        if request.logical_key:
            request = replace(request, logical_key=_scoped_logical_key(self._runtime_session_id, request.logical_key))
        seed = self._mint_permit(request)
        decision = await self._authority.reserve_effect(
            EffectReserveRequest(
                request=request,
                runtime_session_id=self._runtime_session_id,
                lease_seconds=self._lease_seconds,
                max_attempts=self._max_attempts,
                permit=seed,
                operation_handle=operation_handle,
            )
        )
        if decision.permit is None:
            outcome = "denied" if decision.outcome == "denied" else "failed"
            if decision.outcome == "cancelled":
                outcome = "cancelled"
            if decision.outcome in {"duplicate", "blocked"}:
                outcome = (
                    "unknown"
                    if decision.operation_state in {"unknown", "running"}
                    else "failed"
                )
            return EffectDispatchResult(
                operation_id=decision.operation_id,
                attempt_id=decision.attempt_id,
                outcome=outcome,
                result=None,
                reason_code=decision.reason_code,
                duplicate_suppressed=decision.outcome in {"duplicate", "blocked"},
                retry_disposition=(
                    "reconcile"
                    if decision.operation_state == "unknown"
                    else "blocked"
                    if decision.outcome in {"duplicate", "blocked"}
                    else "terminal"
                ),
            )
        permit = self._resign_permit(decision.permit)
        provider_key = None
        if request.idempotency == "provider_keyed":
            provider_key = hmac.new(
                self._permit_secret,
                b"probos.provider-idempotency.v1\x00"
                + decision.operation_id.encode("ascii"),
                hashlib.sha256,
            ).hexdigest()
        unresolved_handle = self._unresolved_handle(
            request,
            decision.operation_id,
            decision.attempt_id,
        )
        context = EffectDispatchContext(
            operation_id=decision.operation_id,
            attempt_id=decision.attempt_id,
            permit=permit,
            provider_idempotency_key=provider_key,
            parent_operation_id=request.parent_operation_id,
            operation_handle=unresolved_handle,
        )
        if request.preflight_denial_reason:
            await self._finish_or_correlate(
                EffectFinishRequest(
                    operation_id=decision.operation_id,
                    attempt_id=decision.attempt_id,
                    outcome="denied",
                    reason_code=request.preflight_denial_reason,
                    result_sha256="",
                ),
                delivery_state="not_started",
                retry_disposition="terminal",
                operation_handle=unresolved_handle,
            )
            return EffectDispatchResult(
                decision.operation_id,
                decision.attempt_id,
                "denied",
                None,
                request.preflight_denial_reason,
                retry_disposition="terminal",
                continuation_token=request.continuation_binding_sha256,
            )
        try:
            result = await invoke(context)
        except asyncio.CancelledError:
            started = self._permit_started(permit)
            if not started and self._permit_entered_start(permit):
                started = True
                try:
                    operations = await self._authority.query_effect_operations(
                        decision.operation_id
                    )
                    if len(operations) == 1 and operations[0].state == "ready":
                        started = False
                except Exception:
                    logger.warning(
                        "Effect cancellation state probe failed operation=query_effect "
                        "operation_id=%s attempt_id=%s manifest_id=unavailable "
                        "generation=%d state=ambiguous "
                        "reason_code=cancellation_state_unavailable; treating the "
                        "effect as started so recovery cannot replay it blindly",
                        decision.operation_id,
                        decision.attempt_id,
                        permit.generation,
                    )
            try:
                await self._authority.finish_effect(
                    EffectFinishRequest(
                        operation_id=decision.operation_id,
                        attempt_id=decision.attempt_id,
                        outcome="unknown" if started else "cancelled",
                        reason_code=(
                            "cancelled_after_effect_start"
                            if started else "cancelled_before_effect"
                        ),
                        result_sha256="",
                    )
                )
            except Exception:
                logger.error(
                    "Effect cancellation finalization failed operation=finish_effect "
                    "operation_id=%s attempt_id=%s manifest_id=unavailable "
                    "generation=%d state=%s reason_code=cancellation_commit_failed; "
                    "the original cancellation will propagate and recovery must "
                    "classify durable state",
                    decision.operation_id,
                    decision.attempt_id,
                    permit.generation,
                    "unknown" if started else "cancelled",
                )
            raise
        except CorrelatedEffectError as exc:
            failure = exc.failure
            correlation = failure.correlation
            if (
                correlation.operation_id != decision.operation_id
                or correlation.attempt_id != decision.attempt_id
            ):
                raise InvalidEffectRequest(
                    "correlated_effect_identity_mismatch"
                ) from None
            try:
                await self._finish_or_correlate(
                    EffectFinishRequest(
                        operation_id=decision.operation_id,
                        attempt_id=decision.attempt_id,
                        outcome="unknown",
                        reason_code=failure.error_code,
                        result_sha256="",
                    ),
                    delivery_state=failure.delivery_state,
                    retry_disposition=failure.retry_disposition,
                    operation_handle=unresolved_handle,
                )
            except Exception:
                raise CorrelatedEffectError(
                    EffectFailureEnvelope(
                        correlation=EffectCorrelation(
                            decision.operation_id,
                            decision.attempt_id,
                            "unknown",
                            "witness_commit_failed",
                        ),
                        error_code="witness_commit_failed",
                        delivery_state=failure.delivery_state,
                        retry_disposition="reconcile",
                    ),
                    operation_handle=unresolved_handle,
                ) from None
            raise
        except StaleGrantError as exc:
            if self._permit_started(permit):
                await self._finish_or_correlate(
                    EffectFinishRequest(
                        operation_id=decision.operation_id,
                        attempt_id=decision.attempt_id,
                        outcome="unknown",
                        reason_code="consumer_exception_unknown",
                        result_sha256="",
                    ),
                    delivery_state="started",
                    retry_disposition="reconcile",
                    operation_handle=unresolved_handle,
                )
                raise CorrelatedEffectError(
                    EffectFailureEnvelope(
                        correlation=EffectCorrelation(
                            decision.operation_id,
                            decision.attempt_id,
                            "unknown",
                            "consumer_exception_unknown",
                        ),
                        error_code="consumer_exception_unknown",
                        delivery_state="started",
                        retry_disposition="reconcile",
                    ),
                    operation_handle=unresolved_handle,
                ) from exc
            await self._finish_or_correlate(
                EffectFinishRequest(
                    operation_id=decision.operation_id,
                    attempt_id=decision.attempt_id,
                    outcome="denied",
                    reason_code="stale_generation",
                    result_sha256="",
                ),
                delivery_state="not_started",
                retry_disposition="terminal",
                operation_handle=unresolved_handle,
            )
            return EffectDispatchResult(
                decision.operation_id,
                decision.attempt_id,
                "denied",
                None,
                "stale_generation",
            )
        except EffectDenied as exc:
            if self._permit_started(permit):
                await self._finish_or_correlate(
                    EffectFinishRequest(
                        operation_id=decision.operation_id,
                        attempt_id=decision.attempt_id,
                        outcome="unknown",
                        reason_code="consumer_exception_unknown",
                        result_sha256="",
                    ),
                    delivery_state="started",
                    retry_disposition="reconcile",
                    operation_handle=unresolved_handle,
                )
                raise CorrelatedEffectError(
                    EffectFailureEnvelope(
                        correlation=EffectCorrelation(
                            decision.operation_id,
                            decision.attempt_id,
                            "unknown",
                            "consumer_exception_unknown",
                        ),
                        error_code="consumer_exception_unknown",
                        delivery_state="started",
                        retry_disposition="reconcile",
                    ),
                    operation_handle=unresolved_handle,
                ) from exc
            await self._finish_or_correlate(
                EffectFinishRequest(
                    operation_id=decision.operation_id,
                    attempt_id=decision.attempt_id,
                    outcome="denied",
                    reason_code=exc.reason_code,
                    result_sha256="",
                ),
                delivery_state=(
                    "started" if self._permit_started(permit) else "not_started"
                ),
                retry_disposition="terminal",
                operation_handle=unresolved_handle,
            )
            if exc.cause is not None:
                setattr(exc.cause, "effect_operation_id", decision.operation_id)
                setattr(exc.cause, "effect_attempt_id", decision.attempt_id)
                setattr(
                    exc.cause,
                    "effect_correlation",
                    EffectCorrelation(
                        decision.operation_id,
                        decision.attempt_id,
                        "denied",
                        exc.reason_code,
                    ),
                )
                raise exc.cause
            return EffectDispatchResult(
                decision.operation_id,
                decision.attempt_id,
                "denied",
                exc.result,
                exc.reason_code,
            )
        except NoEffectFailure as exc:
            await self._finish_or_correlate(
                EffectFinishRequest(
                    operation_id=decision.operation_id,
                    attempt_id=decision.attempt_id,
                    outcome="unknown",
                    reason_code=exc.reason_code,
                    result_sha256="",
                ),
                delivery_state="not_started",
                retry_disposition="retry_same_operation",
                operation_handle=unresolved_handle,
            )
            try:
                await self._authority.reconcile_effect(
                    ReconciliationEvidence(
                        operation_id=decision.operation_id,
                        receipt="transport_pre_handoff",
                        observed="not_applied",
                        provider="strict_adapter",
                    ),
                    receipt_sha256=_digest(
                        "probos.effect-receipt.v1",
                        {
                            "provider": "strict_adapter",
                            "receipt": "transport_pre_handoff",
                        },
                    ),
                )
            except Exception as commit_exc:
                raise CorrelatedEffectError(
                    EffectFailureEnvelope(
                        correlation=EffectCorrelation(
                            decision.operation_id,
                            decision.attempt_id,
                            "unknown",
                            "witness_commit_failed",
                        ),
                        error_code="witness_commit_failed",
                        delivery_state="not_started",
                        retry_disposition="reconcile",
                    ),
                    operation_handle=unresolved_handle,
                ) from commit_exc
            raise CorrelatedEffectError(
                EffectFailureEnvelope(
                    correlation=EffectCorrelation(
                        decision.operation_id,
                        decision.attempt_id,
                        "failed",
                        exc.reason_code,
                    ),
                    error_code=exc.reason_code,
                    delivery_state="not_started",
                    retry_disposition="retry_same_operation",
                ),
                operation_handle=EffectOperationHandle(
                    operation_id=decision.operation_id,
                    attempt_id=decision.attempt_id,
                    adapter_kind=request.adapter_kind,
                    continuation_token=request.continuation_binding_sha256,
                    outcome="failed",
                    retry_disposition="retry_same_operation",
                ),
            ) from exc
        except WitnessUnavailableError as exc:
            if self._permit_started(permit):
                await self._finish_or_correlate(
                    EffectFinishRequest(
                        operation_id=decision.operation_id,
                        attempt_id=decision.attempt_id,
                        outcome="unknown",
                        reason_code="consumer_exception_unknown",
                        result_sha256="",
                    ),
                    delivery_state="started",
                    retry_disposition="reconcile",
                    operation_handle=unresolved_handle,
                )
            raise CorrelatedEffectError(
                EffectFailureEnvelope(
                    correlation=EffectCorrelation(
                        decision.operation_id,
                        decision.attempt_id,
                        "unknown",
                        (
                            "consumer_exception_unknown"
                            if self._permit_started(permit)
                            else "witness_commit_failed"
                        ),
                    ),
                    error_code=(
                        "consumer_exception_unknown"
                        if self._permit_started(permit)
                        else "witness_commit_failed"
                    ),
                    delivery_state=(
                        "started" if self._permit_started(permit) else "not_started"
                    ),
                    retry_disposition="reconcile",
                ),
                operation_handle=unresolved_handle,
            ) from exc
        except Exception as exc:
            started = self._permit_started(permit)
            if not started:
                await self._finish_or_correlate(
                    EffectFinishRequest(
                        operation_id=decision.operation_id,
                        attempt_id=decision.attempt_id,
                        outcome="failed",
                        reason_code="consumer_exception_before_start",
                        result_sha256="",
                    ),
                    delivery_state="not_started",
                    retry_disposition="terminal",
                    operation_handle=unresolved_handle,
                )
                raise CorrelatedEffectError(
                    EffectFailureEnvelope(
                        correlation=EffectCorrelation(
                            decision.operation_id,
                            decision.attempt_id,
                            "failed",
                            "consumer_exception_before_start",
                        ),
                        error_code="consumer_exception_before_start",
                        delivery_state="not_started",
                        retry_disposition="terminal",
                    )
                ) from exc
            try:
                await self._finish_or_correlate(
                    EffectFinishRequest(
                        operation_id=decision.operation_id,
                        attempt_id=decision.attempt_id,
                        outcome="unknown",
                        reason_code="consumer_exception_unknown",
                        result_sha256="",
                    ),
                    delivery_state="started",
                    retry_disposition="reconcile",
                    operation_handle=unresolved_handle,
                )
            except CorrelatedEffectError:
                raise
            except Exception as commit_exc:
                raise CorrelatedEffectError(
                    EffectFailureEnvelope(
                        correlation=EffectCorrelation(
                            decision.operation_id,
                            decision.attempt_id,
                            "unknown",
                            "witness_commit_failed",
                        ),
                        error_code="witness_commit_failed",
                        delivery_state="started",
                        retry_disposition="reconcile",
                    ),
                    operation_handle=unresolved_handle,
                ) from commit_exc
            raise CorrelatedEffectError(
                EffectFailureEnvelope(
                    correlation=EffectCorrelation(
                        decision.operation_id,
                        decision.attempt_id,
                        "unknown",
                        "consumer_exception_unknown",
                    ),
                    error_code="consumer_exception_unknown",
                    delivery_state="started",
                    retry_disposition="reconcile",
                ),
                operation_handle=unresolved_handle,
            ) from exc
        outcome = "failed" if result.error is not None else "result"
        reason = "tool_result_error" if result.error is not None else "consumer_result"
        result_sha256 = _digest(
            "probos.effect-result.v1",
            {
                "outcome": outcome,
                "success": result.error is None,
                "output_type": type(result.output).__name__,
                "error_present": result.error is not None,
            },
        )
        await self._finish_or_correlate(
            EffectFinishRequest(
                operation_id=decision.operation_id,
                attempt_id=decision.attempt_id,
                outcome=outcome,
                reason_code=reason,
                result_sha256=result_sha256,
            ),
            delivery_state="completed",
            retry_disposition="reconcile",
            operation_handle=unresolved_handle,
        )
        return EffectDispatchResult(
            decision.operation_id,
            decision.attempt_id,
            outcome,
            result,
            reason,
            retry_disposition="terminal",
            continuation_token=request.continuation_binding_sha256,
        )

class GovernedEffectBroker(_EffectDispatchMixin):
    """Expose governed dispatch, delegation, and reconciliation."""

    async def bind_delegated_run(
        self,
        *,
        parent: EffectDispatchContext,
        child_agent_id: str,
        child_run_id: str,
    ) -> DelegationRunBinding:
        handle = parent.operation_handle
        if (
            type(handle) is not EffectOperationHandle
            or handle.operation_id != parent.operation_id
            or handle.attempt_id != parent.attempt_id
            or handle.adapter_kind != "delegation"
        ):
            raise InvalidEffectRequest("delegation_operation_handle_invalid")
        token = secrets.token_hex(32)
        binding = DelegationRunBinding(
            parent_operation_id=parent.operation_id,
            parent_attempt_id=parent.attempt_id,
            child_agent_id=child_agent_id,
            child_run_id=child_run_id,
            binding_token=token,
        )
        try:
            await self._authority.bind_delegated_run(binding)
        except WitnessUnavailableError:
            raise CorrelatedEffectError(
                EffectFailureEnvelope(
                    correlation=EffectCorrelation(
                        parent.operation_id,
                        parent.attempt_id,
                        "unknown",
                        "delegation_binding_witness_unavailable",
                    ),
                    error_code="delegation_binding_witness_unavailable",
                    delivery_state="started",
                    retry_disposition="reconcile",
                ),
                operation_handle=handle,
            ) from None
        return binding

    async def _commit_reconciliation(
        self,
        *,
        evidence: ReconciliationEvidence,
        receipt_sha256: str,
        operation_id: str,
        attempt_id: str,
    ) -> EffectOperationView:
        try:
            return await self._authority.reconcile_effect(
                evidence, receipt_sha256=receipt_sha256
            )
        except Exception:
            raise CorrelatedEffectError(
                EffectFailureEnvelope(
                    correlation=EffectCorrelation(
                        operation_id,
                        attempt_id,
                        "unknown",
                        "reconciliation_witness_commit_failed",
                    ),
                    error_code="reconciliation_witness_commit_failed",
                    delivery_state="sent_unconfirmed",
                    retry_disposition="reconcile",
                )
            ) from None

    async def reconcile(
        self, operation_id: str, reconciler: EffectReconciler
    ) -> EffectOperationView:
        operations = await self._authority.query_effect_operations(operation_id)
        if len(operations) != 1:
            raise InvalidEffectRequest("effect_operation_unavailable")
        operation = operations[0]
        if operation.state != "unknown":
            return operation
        attempts = await self._authority.query_effect_attempts(operation_id)
        if not attempts:
            raise InvalidEffectRequest("effect_attempt_unavailable")
        latest = max(attempts, key=lambda attempt: attempt.ordinal)
        if latest.operation_id != operation_id:
            raise InvalidEffectRequest("effect_attempt_operation_mismatch")
        evidence = await reconciler.reconcile(operation)
        if evidence is None:
            return await self._commit_reconciliation(
                evidence=ReconciliationEvidence(
                    operation_id=operation_id,
                    receipt="",
                    observed="failed",
                    provider="unavailable",
                ),
                receipt_sha256="",
                operation_id=operation_id,
                attempt_id=latest.attempt_id,
            )
        if evidence.operation_id != operation_id:
            raise InvalidEffectRequest("reconciliation_operation_mismatch")
        if (
            not isinstance(evidence.provider, str)
            or not evidence.provider
            or len(evidence.provider.encode("utf-8", "replace")) > 128
            or not isinstance(evidence.receipt, str)
            or not evidence.receipt
            or len(evidence.receipt.encode("utf-8", "replace")) > 2048
        ):
            return await self._commit_reconciliation(
                evidence=ReconciliationEvidence(
                    operation_id=operation_id,
                    receipt="",
                    observed="failed",
                    provider="unavailable",
                ),
                receipt_sha256="",
                operation_id=operation_id,
                attempt_id=latest.attempt_id,
            )
        receipt_sha256 = _digest(
            "probos.effect-receipt.v1",
            {"provider": evidence.provider, "receipt": evidence.receipt},
        )
        return await self._commit_reconciliation(
            evidence=evidence,
            receipt_sha256=receipt_sha256,
            operation_id=operation_id,
            attempt_id=latest.attempt_id,
        )


__all__ = [
    "EffectAttemptView",
    "EffectClass",
    "EffectCoverageReport",
    "EffectDispatchContext",
    "EffectDispatchResult",
    "EffectIdempotency",
    "EffectOperationView",
    "EffectReconciler",
    "EffectRequest",
    "GovernedEffectBroker",
    "CorrelatedEffectError",
    "InvalidEffectRequest",
    "NoEffectFailure",
    "ProtectedEffectBypassDenied",
    "effect_coverage_report",
]
