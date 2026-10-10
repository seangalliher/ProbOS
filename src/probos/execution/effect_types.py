"""Cycle-free governed-effect contracts (AD-1316)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from probos.tools.protocol import ToolPermission, ToolResult

EffectClass = Literal[
    "filesystem", "shell", "code", "network", "mcp", "browser", "delegation", "tool"
]
EffectIdempotency = Literal[
    "idempotent", "provider_keyed", "non_idempotent", "opaque"
]
EffectOutcome = Literal["result", "denied", "failed", "cancelled", "unknown"]
EffectDeliveryState = Literal[
    "not_started", "started", "sent_unconfirmed", "completed"
]
EffectRetryDisposition = Literal[
    "terminal", "reconcile", "retry_same_operation", "blocked"
]
EffectAdapterKind = Literal[
    "native_file", "code_backend", "mcp", "mesh", "browser", "delegation", "opaque"
]
EffectOperationState = Literal[
    "pending", "ready", "running", "result", "denied", "failed",
    "cancelled", "unknown", "blocked",
]
ReconciliationObservation = Literal["applied", "not_applied", "failed"]


@dataclass(frozen=True, slots=True)
class EffectRequest:
    logical_key: str
    agent_id: str
    tool_id: str
    effect_class: EffectClass
    target_identity: str
    parameter_shape_sha256: str
    idempotency: EffectIdempotency
    parent_operation_id: str | None = None
    provider_call_id: str | None = None
    resolved_tool_id: str = ""
    adapter_kind: EffectAdapterKind = "opaque"
    continuation_binding_sha256: str = ""
    isolation_binding_sha256: str = ""
    parent_attempt_id: str | None = None
    child_run_id: str = ""
    binding_token: str = ""
    preflight_denial_reason: str = ""
    authorized_root: str = ""


@dataclass(frozen=True, slots=True)
class EffectOperationHandle:
    operation_id: str
    attempt_id: str
    adapter_kind: EffectAdapterKind
    continuation_token: str
    outcome: EffectOutcome
    retry_disposition: EffectRetryDisposition


@dataclass(frozen=True, slots=True)
class EffectCorrelation:
    operation_id: str
    attempt_id: str
    outcome: EffectOutcome
    reason_code: str


@dataclass(frozen=True, slots=True)
class EffectFailureEnvelope:
    correlation: EffectCorrelation
    error_code: str
    delivery_state: EffectDeliveryState
    retry_disposition: EffectRetryDisposition


@dataclass(frozen=True, slots=True)
class EffectTargetRequest:
    effect_class: EffectClass
    canonical_target: str
    adapter_kind: EffectAdapterKind


@dataclass(frozen=True, slots=True)
class EffectTargetDecision:
    allowed: bool
    reason_code: str
    isolation_binding_sha256: str
    authorized_root: str = ""


@dataclass(frozen=True, slots=True)
class DelegationRunBinding:
    parent_operation_id: str
    parent_attempt_id: str
    child_agent_id: str
    child_run_id: str
    binding_token: str


@dataclass(frozen=True, slots=True)
class ExternalEffectContext:
    operation_id: str
    attempt_id: str
    provider_idempotency_key: str | None
    adapter_kind: EffectAdapterKind


@dataclass(frozen=True, slots=True)
class MeshEffectContext:
    operation_id: str
    attempt_id: str
    handler_receipt_key: str


@dataclass(frozen=True, slots=True)
class PreparedEffect:
    requested_tool_id: str
    resolved_tool_id: str
    effect_class: EffectClass
    adapter_kind: EffectAdapterKind
    canonical_target: str
    parameter_shape_sha256: str
    continuation_binding_sha256: str
    isolation_binding_sha256: str
    idempotency: EffectIdempotency
    retry_disposition: EffectRetryDisposition
    denial_reason: str = ""


@dataclass(frozen=True, slots=True)
class AdapterCompletion:
    outcome: EffectOutcome
    reason_code: str
    delivery_state: EffectDeliveryState
    retry_disposition: EffectRetryDisposition
    result_sha256: str = ""
    receipt_sha256: str = ""


@dataclass(frozen=True, slots=True)
class EffectPermit:
    operation_id: str
    attempt_id: str
    tool_id_sha256: str
    generation: int
    nonce: str
    signature: str


@dataclass(frozen=True, slots=True)
class EffectDispatchContext:
    operation_id: str
    attempt_id: str
    permit: EffectPermit
    provider_idempotency_key: str | None
    parent_operation_id: str | None
    operation_handle: EffectOperationHandle | None = None


@dataclass(frozen=True, slots=True)
class EffectDispatchResult:
    operation_id: str
    attempt_id: str
    outcome: EffectOutcome
    result: ToolResult | None
    reason_code: str
    duplicate_suppressed: bool = False
    retry_disposition: EffectRetryDisposition = "terminal"
    continuation_token: str = ""


@dataclass(frozen=True, slots=True)
class ReconciliationEvidence:
    operation_id: str
    receipt: str
    observed: ReconciliationObservation
    provider: str


@dataclass(frozen=True, slots=True)
class EffectOperationView:
    operation_id: str
    state: EffectOperationState
    reason_code: str
    effect_class: EffectClass
    idempotency: EffectIdempotency
    generation: int
    parent_operation_id: str | None
    attempt_count: int
    result_sha256: str
    receipt_sha256: str
    adapter_kind: EffectAdapterKind = "opaque"
    continuation_binding_sha256: str = ""
    parent_attempt_id: str | None = None
    child_run_sha256: str = ""


@dataclass(frozen=True, slots=True)
class EffectAttemptView:
    attempt_id: str
    operation_id: str
    ordinal: int
    state: str
    reason_code: str
    lease_expires_at_ms: int | None
    started_at_ms: int | None
    finished_at_ms: int | None
    result_sha256: str
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class EffectReserveRequest:
    request: EffectRequest
    runtime_session_id: str
    lease_seconds: int
    max_attempts: int
    permit: EffectPermit
    operation_handle: EffectOperationHandle | None = None


@dataclass(frozen=True, slots=True)
class EffectReserveDecision:
    operation_id: str
    attempt_id: str
    outcome: Literal["ready", "denied", "failed", "cancelled", "duplicate", "blocked"]
    reason_code: str
    permit: EffectPermit | None
    operation_state: EffectOperationState


@dataclass(frozen=True, slots=True)
class EffectFinishRequest:
    operation_id: str
    attempt_id: str
    outcome: EffectOutcome
    reason_code: str
    result_sha256: str


@runtime_checkable
class EffectReconciler(Protocol):
    async def reconcile(
        self, operation: EffectOperationView
    ) -> ReconciliationEvidence | None: ...


@runtime_checkable
class EffectAdapter(Protocol):
    def prepare(
        self,
        *,
        tool_id: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> PreparedEffect: ...

    def match_continuation(
        self, *, pending: EffectOperationView, prepared: PreparedEffect
    ) -> bool: ...

    async def reconcile(
        self, operation: EffectOperationView
    ) -> ReconciliationEvidence | None: ...

    def project_result(self, result: ToolResult) -> AdapterCompletion: ...


@runtime_checkable
class GovernedEffectBrokerProtocol(Protocol):
    async def dispatch(
        self,
        request: EffectRequest,
        invoke: Callable[[EffectDispatchContext], Awaitable[ToolResult]],
        operation_handle: EffectOperationHandle | None = None,
    ) -> EffectDispatchResult: ...

    async def reconcile(
        self, operation_id: str, reconciler: EffectReconciler
    ) -> EffectOperationView: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def classify_tool(
        self,
        tool_id: str,
        params: dict[str, Any],
        required: ToolPermission,
        context: dict[str, Any],
    ) -> EffectRequest: ...

    async def start_permitted_effect(
        self, permit: EffectPermit, tool_id: str
    ) -> None: ...

    async def bind_delegated_run(
        self,
        *,
        parent: EffectDispatchContext,
        child_agent_id: str,
        child_run_id: str,
    ) -> DelegationRunBinding: ...


@runtime_checkable
class ProtectedEffectAuthorityProtocol(Protocol):
    async def reserve_effect(
        self, request: EffectReserveRequest
    ) -> EffectReserveDecision: ...

    async def mark_effect_started(self, permit: EffectPermit) -> None: ...

    async def finish_effect(self, request: EffectFinishRequest) -> EffectOperationView: ...

    async def reconcile_effect(
        self, evidence: ReconciliationEvidence, *, receipt_sha256: str
    ) -> EffectOperationView: ...

    async def recover_effects(self, *, now_ms: int | None = None) -> int: ...

    async def shutdown_effects(self) -> int: ...

    async def query_effect_operations(
        self, operation_id: str | None = None
    ) -> tuple[EffectOperationView, ...]: ...

    async def query_effect_attempts(
        self, operation_id: str
    ) -> tuple[EffectAttemptView, ...]: ...

    async def authorize_effect_target(
        self, request: EffectTargetRequest
    ) -> EffectTargetDecision: ...

    async def bind_delegated_run(self, binding: DelegationRunBinding) -> None: ...
