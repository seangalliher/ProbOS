"""Strict protected-execution authority and durable admission witness (AD-1315)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol, TypeAlias

from probos.protocols import ConnectionFactory, DatabaseConnection
from probos.execution.command_env import trusted_command_env
from probos.execution.effect_types import (
    DelegationRunBinding,
    EffectAttemptView,
    EffectFinishRequest,
    EffectOperationView,
    EffectPermit,
    EffectTargetDecision,
    EffectTargetRequest,
    EffectReserveDecision,
    EffectReserveRequest,
    ReconciliationEvidence,
)
from probos.storage.sqlite_factory import default_factory

logger = logging.getLogger(__name__)

EXECUTION_MANIFEST_VERSION = 1
EXECUTION_WITNESS_SCHEMA_VERSION = 2
REQUIRED_ENFORCEMENT_KINDS = (
    "agent_source",
    "tool_catalog",
    "effective_permissions",
    "runtime_security_config",
    "admission_policy",
    "executor_source",
    "isolation_boundary",
)
EnforcementKind: TypeAlias = Literal[
    "agent_source",
    "tool_catalog",
    "effective_permissions",
    "runtime_security_config",
    "admission_policy",
    "executor_source",
    "isolation_boundary",
]

_SQLITE_INTEGER_MAX = (1 << 63) - 1
_SQLITE_INTEGER_FIELDS = {
    "authority_meta": (
        ("singleton", 1, 1, False),
        ("schema_version", 2, 2, False),
        ("current_generation", 0, _SQLITE_INTEGER_MAX - 1, False),
        ("updated_at_ms", 0, _SQLITE_INTEGER_MAX, False),
    ),
    "execution_manifests": (
        ("version", 1, 1, False),
        ("generation", 0, _SQLITE_INTEGER_MAX, False),
        ("created_at_ms", 0, _SQLITE_INTEGER_MAX, False),
        ("os_pid", 0, _SQLITE_INTEGER_MAX, False),
        ("repository_dirty", 0, 1, False),
    ),
    "manifest_sources": (
        ("item_count", 0, _SQLITE_INTEGER_MAX, False),
    ),
    "admission_attempts": (
        ("requested_at_ms", 0, _SQLITE_INTEGER_MAX, False),
        ("resolved_at_ms", 0, _SQLITE_INTEGER_MAX, True),
        ("presented_generation", 0, _SQLITE_INTEGER_MAX, True),
        ("admitted_at_ms", 0, _SQLITE_INTEGER_MAX, True),
        ("failed_at_ms", 0, _SQLITE_INTEGER_MAX, True),
    ),
    "execution_grants": (
        ("generation", 0, _SQLITE_INTEGER_MAX, False),
        ("issued_at_ms", 0, _SQLITE_INTEGER_MAX, False),
        ("revoked_at_ms", 0, _SQLITE_INTEGER_MAX, True),
    ),
    "effect_operations": (
        ("generation", 0, _SQLITE_INTEGER_MAX, False),
        ("created_at_ms", 0, _SQLITE_INTEGER_MAX, False),
        ("updated_at_ms", 0, _SQLITE_INTEGER_MAX, False),
    ),
    "effect_attempts": (
        ("ordinal", 1, _SQLITE_INTEGER_MAX, False),
        ("lease_expires_at_ms", 0, _SQLITE_INTEGER_MAX, True),
        ("started_at_ms", 0, _SQLITE_INTEGER_MAX, True),
        ("finished_at_ms", 0, _SQLITE_INTEGER_MAX, True),
    ),
    "effect_transitions": (
        ("transition_id", 1, _SQLITE_INTEGER_MAX, False),
        ("recorded_at_ms", 0, _SQLITE_INTEGER_MAX, False),
    ),
    "effect_delegation_bindings": (
        ("created_at_ms", 0, _SQLITE_INTEGER_MAX, False),
        ("closed_at_ms", 0, _SQLITE_INTEGER_MAX, True),
    ),
}
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_REASON_CODE_RE = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_TABLE_COLUMNS = {
    "authority_meta": (
        "singleton", "schema_version", "host_instance_id", "current_generation",
        "process_id", "updated_at_ms",
    ),
    "execution_manifests": (
        "manifest_id", "version", "generation", "created_at_ms",
        "host_instance_id", "process_id", "os_pid", "runtime_session_sha256",
        "repository_root_sha256", "repository_head_sha",
        "repository_tree_sha256", "repository_dirty",
        "selected_agent_id_sha256", "selected_agent_type",
        "selected_agent_source_path", "selected_agent_source_sha256",
        "policy_sha256", "manifest_sha256",
    ),
    "manifest_sources": (
        "manifest_id", "kind", "name", "sha256", "version", "item_count",
    ),
    "admission_attempts": (
        "attempt_id", "requested_at_ms", "resolved_at_ms", "manifest_id",
        "presented_generation", "runtime_session_sha256", "operation_kind",
        "target_sha256", "parameter_shape_sha256", "outcome", "reason_code",
        "admitted_at_ms", "failed_at_ms",
    ),
    "execution_grants": (
        "grant_id", "attempt_id", "manifest_id", "generation",
        "runtime_session_sha256", "issued_at_ms", "state", "revoked_at_ms",
        "revoked_reason",
    ),
    "effect_operations": (
        "operation_id", "logical_key_sha256", "manifest_id", "generation",
        "runtime_session_sha256", "agent_id_sha256", "requested_tool_id_sha256",
        "resolved_tool_id_sha256", "effect_class", "adapter_kind",
        "target_sha256", "parameter_shape_sha256",
        "continuation_binding_sha256", "isolation_binding_sha256", "idempotency",
        "parent_operation_id", "parent_attempt_id", "child_run_sha256",
        "provider_call_id_sha256",
        "state", "reason_code", "result_sha256", "receipt_sha256",
        "created_at_ms", "updated_at_ms",
    ),
    "effect_attempts": (
        "attempt_id", "operation_id", "ordinal", "admission_attempt_id",
        "grant_id", "state", "reason_code", "lease_expires_at_ms",
        "started_at_ms", "finished_at_ms", "result_sha256", "receipt_sha256",
    ),
    "effect_transitions": (
        "transition_id", "operation_id", "attempt_id", "from_state",
        "to_state", "reason_code", "recorded_at_ms",
    ),
    "effect_delegation_bindings": (
        "parent_operation_id", "parent_attempt_id", "child_agent_id_sha256",
        "child_run_sha256", "binding_sha256", "state", "created_at_ms",
        "closed_at_ms",
    ),
}
_REQUIRED_INDEXES = {
    "idx_admission_attempts_outcome_requested": (
        "admission_attempts",
        ("outcome", "requested_at_ms"),
    ),
    "idx_execution_grants_generation_state": (
        "execution_grants",
        ("generation", "state"),
    ),
    "idx_effect_operations_state_updated": (
        "effect_operations", ("state", "updated_at_ms"),
    ),
    "idx_effect_operations_generation_state": (
        "effect_operations", ("generation", "state"),
    ),
    "idx_effect_attempts_operation_ordinal": (
        "effect_attempts", ("operation_id", "ordinal"),
    ),
    "idx_effect_attempts_state_lease": (
        "effect_attempts", ("state", "lease_expires_at_ms"),
    ),
    "idx_effect_transitions_operation_transition": (
        "effect_transitions", ("operation_id", "transition_id"),
    ),
    "idx_effect_operations_session_agent_adapter_state": (
        "effect_operations",
        ("runtime_session_sha256", "agent_id_sha256", "adapter_kind", "state"),
    ),
    "idx_effect_operations_parent_attempt": (
        "effect_operations", ("parent_operation_id", "parent_attempt_id"),
    ),
    "idx_effect_delegation_child_state": (
        "effect_delegation_bindings",
        ("child_agent_id_sha256", "child_run_sha256", "state"),
    ),
}

_SCHEMA = """
CREATE TABLE authority_meta(
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    schema_version INTEGER NOT NULL CHECK(schema_version=2),
    host_instance_id TEXT NOT NULL,
    current_generation INTEGER NOT NULL CHECK(current_generation>=0),
    process_id TEXT NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE TABLE execution_manifests(
    manifest_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL CHECK(version=1),
    generation INTEGER NOT NULL UNIQUE,
    created_at_ms INTEGER NOT NULL,
    host_instance_id TEXT NOT NULL,
    process_id TEXT NOT NULL,
    os_pid INTEGER NOT NULL,
    runtime_session_sha256 TEXT NOT NULL,
    repository_root_sha256 TEXT NOT NULL,
    repository_head_sha TEXT NOT NULL,
    repository_tree_sha256 TEXT NOT NULL,
    repository_dirty INTEGER NOT NULL CHECK(repository_dirty IN (0,1)),
    selected_agent_id_sha256 TEXT NOT NULL,
    selected_agent_type TEXT NOT NULL,
    selected_agent_source_path TEXT NOT NULL,
    selected_agent_source_sha256 TEXT NOT NULL,
    policy_sha256 TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL UNIQUE
);
CREATE TABLE manifest_sources(
    manifest_id TEXT NOT NULL REFERENCES execution_manifests(manifest_id),
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    version TEXT NOT NULL,
    item_count INTEGER NOT NULL CHECK(item_count>=0),
    PRIMARY KEY(manifest_id,kind,name)
);
CREATE TABLE admission_attempts(
    attempt_id TEXT PRIMARY KEY,
    requested_at_ms INTEGER NOT NULL,
    resolved_at_ms INTEGER,
    manifest_id TEXT,
    presented_generation INTEGER,
    runtime_session_sha256 TEXT NOT NULL,
    operation_kind TEXT NOT NULL,
    target_sha256 TEXT NOT NULL,
    parameter_shape_sha256 TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('pending','admitted','denied','rejected','failed')),
    reason_code TEXT NOT NULL,
    admitted_at_ms INTEGER,
    failed_at_ms INTEGER
);
CREATE TABLE execution_grants(
    grant_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE REFERENCES admission_attempts(attempt_id),
    manifest_id TEXT NOT NULL REFERENCES execution_manifests(manifest_id),
    generation INTEGER NOT NULL,
    runtime_session_sha256 TEXT NOT NULL,
    issued_at_ms INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('active','revoked')),
    revoked_at_ms INTEGER,
    revoked_reason TEXT NOT NULL
);
CREATE INDEX idx_admission_attempts_outcome_requested
    ON admission_attempts(outcome, requested_at_ms);
CREATE INDEX idx_execution_grants_generation_state
    ON execution_grants(generation, state);
CREATE TABLE effect_operations(
    operation_id TEXT PRIMARY KEY,
    logical_key_sha256 TEXT NOT NULL UNIQUE,
    manifest_id TEXT NOT NULL REFERENCES execution_manifests(manifest_id),
    generation INTEGER NOT NULL,
    runtime_session_sha256 TEXT NOT NULL,
    agent_id_sha256 TEXT NOT NULL,
    requested_tool_id_sha256 TEXT NOT NULL,
    resolved_tool_id_sha256 TEXT NOT NULL,
    effect_class TEXT NOT NULL,
    adapter_kind TEXT NOT NULL,
    target_sha256 TEXT NOT NULL,
    parameter_shape_sha256 TEXT NOT NULL,
    continuation_binding_sha256 TEXT NOT NULL,
    isolation_binding_sha256 TEXT NOT NULL,
    idempotency TEXT NOT NULL,
    parent_operation_id TEXT REFERENCES effect_operations(operation_id),
    parent_attempt_id TEXT REFERENCES effect_attempts(attempt_id),
    child_run_sha256 TEXT NOT NULL,
    provider_call_id_sha256 TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('pending','ready','running','result','denied','failed','cancelled','unknown','blocked')),
    reason_code TEXT NOT NULL,
    result_sha256 TEXT NOT NULL,
    receipt_sha256 TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);
CREATE TABLE effect_attempts(
    attempt_id TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES effect_operations(operation_id),
    ordinal INTEGER NOT NULL CHECK(ordinal>=1),
    admission_attempt_id TEXT REFERENCES admission_attempts(attempt_id),
    grant_id TEXT REFERENCES execution_grants(grant_id),
    state TEXT NOT NULL CHECK(state IN ('reserved','intent_committed','running','result','denied','failed','cancelled','unknown')),
    reason_code TEXT NOT NULL,
    lease_expires_at_ms INTEGER,
    started_at_ms INTEGER,
    finished_at_ms INTEGER,
    result_sha256 TEXT NOT NULL,
    receipt_sha256 TEXT NOT NULL,
    UNIQUE(operation_id, ordinal)
);
CREATE TABLE effect_transitions(
    transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
    operation_id TEXT NOT NULL REFERENCES effect_operations(operation_id),
    attempt_id TEXT REFERENCES effect_attempts(attempt_id),
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    recorded_at_ms INTEGER NOT NULL
);
CREATE TABLE effect_delegation_bindings(
    parent_operation_id TEXT NOT NULL REFERENCES effect_operations(operation_id),
    parent_attempt_id TEXT NOT NULL REFERENCES effect_attempts(attempt_id),
    child_agent_id_sha256 TEXT NOT NULL,
    child_run_sha256 TEXT NOT NULL,
    binding_sha256 TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK(state IN ('active','closed')),
    created_at_ms INTEGER NOT NULL,
    closed_at_ms INTEGER,
    PRIMARY KEY(parent_operation_id,parent_attempt_id,child_run_sha256)
);
CREATE INDEX idx_effect_operations_state_updated
    ON effect_operations(state, updated_at_ms);
CREATE INDEX idx_effect_operations_generation_state
    ON effect_operations(generation, state);
CREATE INDEX idx_effect_attempts_operation_ordinal
    ON effect_attempts(operation_id, ordinal);
CREATE INDEX idx_effect_attempts_state_lease
    ON effect_attempts(state, lease_expires_at_ms);
CREATE INDEX idx_effect_transitions_operation_transition
    ON effect_transitions(operation_id, transition_id);
CREATE INDEX idx_effect_operations_session_agent_adapter_state
    ON effect_operations(runtime_session_sha256,agent_id_sha256,adapter_kind,state);
CREATE INDEX idx_effect_operations_parent_attempt
    ON effect_operations(parent_operation_id,parent_attempt_id);
CREATE INDEX idx_effect_delegation_child_state
    ON effect_delegation_bindings(child_agent_id_sha256,child_run_sha256,state);
"""
_SCHEMA_STATEMENTS = tuple(
    statement.strip() for statement in _SCHEMA.split(";") if statement.strip()
)
_TABLE_SQL = {
    table: next(
        statement
        for statement in _SCHEMA_STATEMENTS
        if statement.startswith(f"CREATE TABLE {table}(")
    )
    for table in _TABLE_COLUMNS
}
_INDEX_SQL = {
    index: next(
        statement
        for statement in _SCHEMA_STATEMENTS
        if statement.startswith(f"CREATE INDEX {index}")
    )
    for index in _REQUIRED_INDEXES
}
_EXPECTED_FOREIGN_KEYS = {
    "authority_meta": set(),
    "execution_manifests": set(),
    "manifest_sources": {
        ("execution_manifests", "manifest_id", "manifest_id", "NO ACTION", "NO ACTION"),
    },
    "admission_attempts": set(),
    "execution_grants": {
        ("admission_attempts", "attempt_id", "attempt_id", "NO ACTION", "NO ACTION"),
        ("execution_manifests", "manifest_id", "manifest_id", "NO ACTION", "NO ACTION"),
    },
    "effect_operations": {
        ("execution_manifests", "manifest_id", "manifest_id", "NO ACTION", "NO ACTION"),
        ("effect_operations", "parent_operation_id", "operation_id", "NO ACTION", "NO ACTION"),
        ("effect_attempts", "parent_attempt_id", "attempt_id", "NO ACTION", "NO ACTION"),
    },
    "effect_attempts": {
        ("effect_operations", "operation_id", "operation_id", "NO ACTION", "NO ACTION"),
        ("admission_attempts", "admission_attempt_id", "attempt_id", "NO ACTION", "NO ACTION"),
        ("execution_grants", "grant_id", "grant_id", "NO ACTION", "NO ACTION"),
    },
    "effect_transitions": {
        ("effect_operations", "operation_id", "operation_id", "NO ACTION", "NO ACTION"),
        ("effect_attempts", "attempt_id", "attempt_id", "NO ACTION", "NO ACTION"),
    },
    "effect_delegation_bindings": {
        ("effect_operations", "parent_operation_id", "operation_id", "NO ACTION", "NO ACTION"),
        ("effect_attempts", "parent_attempt_id", "attempt_id", "NO ACTION", "NO ACTION"),
    },
}


class ProtectedExecutionError(RuntimeError):
    """Base error for strict protected execution."""


class WitnessUnavailableError(ProtectedExecutionError):
    """The durable witness cannot confirm the requested transition."""


class WitnessSchemaError(ProtectedExecutionError):
    """The witness schema is absent, incompatible, or too new."""


class IsolationBoundaryError(ProtectedExecutionError):
    """A protected path overlaps a Worker-writable root."""


class ManifestValidationError(ProtectedExecutionError):
    """Manifest input is incomplete, invalid, or changed while read."""


class StaleGrantError(ProtectedExecutionError):
    """A grant is absent, revoked, or no longer bound to this issuer."""


@dataclass(frozen=True, slots=True)
class EnforcementSourceSnapshot:
    kind: EnforcementKind
    name: str
    sha256: str
    version: str
    item_count: int


@dataclass(frozen=True, slots=True)
class RepositoryBinding:
    root_sha256: str
    head_sha: str
    tracked_tree_sha256: str
    dirty: bool


@dataclass(frozen=True, slots=True)
class HostBinding:
    host_instance_id: str
    process_id: str
    os_pid: int
    runtime_session_sha256: str


@dataclass(frozen=True, slots=True)
class SelectedAgentBinding:
    agent_id_sha256: str
    agent_type: str
    source_relative_path: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class ExecutionManifest:
    version: Literal[1]
    manifest_id: str
    generation: int
    created_at_ms: int
    repository: RepositoryBinding
    host: HostBinding
    selected_agent: SelectedAgentBinding
    enforcement_sources: tuple[EnforcementSourceSnapshot, ...]
    policy_sha256: str
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class ExecutionGrant:
    grant_id: str
    attempt_id: str
    manifest_id: str
    generation: int
    runtime_session_sha256: str


@dataclass(frozen=True, slots=True)
class AdmissionRequest:
    manifest_id: object
    generation: object
    runtime_session_id: object
    operation_kind: object
    target_identity: object
    parameter_shape_sha256: object


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    attempt_id: str
    outcome: Literal["admitted", "denied", "rejected", "failed"]
    reason_code: str
    grant: ExecutionGrant | None


@dataclass(frozen=True, slots=True)
class ManifestPublicationRequest:
    repository_root: Path
    selected_agent_id: str
    selected_agent_type: str
    selected_agent_source_path: Path
    enforcement_sources: tuple[EnforcementSourceSnapshot, ...]
    enforcement_source_paths: tuple[Path | None, ...]
    policy_path: Path
    protected_installation_root: Path
    worker_write_roots: tuple[Path, ...]


class ProtectedExecutionAuthorityProtocol(Protocol):
    async def publish_manifest(
        self, request: ManifestPublicationRequest
    ) -> ExecutionManifest: ...

    async def admit(self, request: AdmissionRequest) -> AdmissionDecision: ...

    async def validate_grant(self, grant: ExecutionGrant) -> None: ...

    async def mark_start_failed(
        self, grant: ExecutionGrant, *, reason_code: str
    ) -> None: ...

    async def reserve_effect(
        self, request: EffectReserveRequest
    ) -> EffectReserveDecision: ...

    async def mark_effect_started(self, permit: EffectPermit) -> None: ...

    async def finish_effect(
        self, request: EffectFinishRequest
    ) -> EffectOperationView: ...

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


def _now_ms() -> int:
    return int(time.time() * 1000)


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _sha256_bytes(domain: str, value: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(domain.encode("ascii"))
    digest.update(b"\x00")
    digest.update(value)
    return digest.hexdigest()


def _sha256_json(domain: str, value: object) -> str:
    return _sha256_bytes(domain, _canonical_json(value))


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _read_stable_bytes(path: Path) -> bytes:
    try:
        before = path.stat()
        content = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise ManifestValidationError("required manifest source is unreadable") from exc
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ino != after.st_ino
    ):
        raise ManifestValidationError("manifest source changed during read")
    return content


def _read_stable_digest(path: Path, domain: str) -> str:
    return _sha256_bytes(domain, _read_stable_bytes(path))


def _normalize_schema_sql(value: str) -> str:
    normalized: list[str] = []
    index = 0
    in_literal = False
    while index < len(value):
        character = value[index]
        if character == "'":
            normalized.append(character)
            if in_literal and index + 1 < len(value) and value[index + 1] == "'":
                normalized.append("'")
                index += 2
                continue
            in_literal = not in_literal
        elif in_literal:
            normalized.append(character)
        elif character not in {'"', "`"} and not character.isspace():
            normalized.append(character.lower())
        index += 1
    return "".join(normalized)


def _issued_identifier(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 36:
        return None
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return None
    return value if str(parsed) == value else None


def _metadata_identifier(value: object) -> str | None:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        return None
    return value


def _bounded_text_hash(value: object, domain: str) -> str:
    marker = value if isinstance(value, str) else {"type": type(value).__name__}
    return _sha256_json(domain, marker)


class _ManifestPreparer:
    def __init__(
        self,
        *,
        db_path: Path,
        protected_installation_root: Path,
        policy_path: Path,
        worker_write_roots: tuple[Path, ...],
        issuer_module_path: Path,
    ) -> None:
        self._db_path = db_path
        self._protected_installation_root = protected_installation_root
        self._policy_path = policy_path
        self._worker_write_roots = worker_write_roots
        self._issuer_module_path = issuer_module_path

    def validate_configured_isolation(self) -> None:
        self._validate_isolation(
            self._protected_installation_root,
            self._policy_path,
            self._worker_write_roots,
        )

    def prepare(
        self, request: ManifestPublicationRequest
    ) -> tuple[dict[str, object], dict[str, bool]]:
        repository_root = request.repository_root.resolve()
        protected_root = request.protected_installation_root.resolve()
        policy_path = request.policy_path.resolve()
        worker_roots = tuple(path.resolve() for path in request.worker_write_roots)
        self._validate_isolation(protected_root, policy_path, worker_roots)
        if protected_root != self._protected_installation_root:
            raise IsolationBoundaryError("publication protected root differs from issuer")
        if policy_path != self._policy_path:
            raise ManifestValidationError("publication policy differs from issuer policy")
        if repository_root == protected_root:
            raise IsolationBoundaryError(
                "repository root cannot be the protected installation root"
            )
        if len(request.enforcement_sources) != len(request.enforcement_source_paths):
            raise ManifestValidationError("enforcement source paths are incomplete")
        kinds = [source.kind for source in request.enforcement_sources]
        if sorted(kinds) != sorted(REQUIRED_ENFORCEMENT_KINDS):
            raise ManifestValidationError(
                "required enforcement kinds must be present exactly once"
            )
        identities: set[tuple[str, str]] = set()
        for source, source_path in zip(
            request.enforcement_sources,
            request.enforcement_source_paths,
            strict=True,
        ):
            identity = (source.kind, source.name)
            if identity in identities:
                raise ManifestValidationError("duplicate enforcement source identity")
            identities.add(identity)
            if (
                _metadata_identifier(source.name) is None
                or _metadata_identifier(source.version) is None
                or type(source.item_count) is not int
                or not 0 <= source.item_count <= _SQLITE_INTEGER_MAX
                or not _is_sha256(source.sha256)
            ):
                raise ManifestValidationError("invalid enforcement source metadata")
            if source_path is not None:
                observed = _read_stable_digest(
                    source_path.resolve(), f"probos.enforcement-source.{source.kind}.v1"
                )
                if observed != source.sha256:
                    raise ManifestValidationError("enforcement source digest mismatch")
        selected_path = request.selected_agent_source_path.resolve()
        if _metadata_identifier(request.selected_agent_type) is None:
            raise ManifestValidationError("invalid selected agent metadata")
        if not _path_is_within(selected_path, repository_root):
            raise ManifestValidationError("selected agent source escapes repository")
        selected_digest = _read_stable_digest(
            selected_path, "probos.selected-agent-source.v1"
        )
        policy_bytes = _read_stable_bytes(policy_path)
        policy_digest = _sha256_bytes("probos.admission-policy.v1", policy_bytes)
        policy = self._load_policy(policy_bytes)
        repository = self._repository_binding(repository_root)
        selected = {
            "agent_id_sha256": _sha256_json(
                "probos.selected-agent-id.v1", request.selected_agent_id
            ),
            "agent_type": request.selected_agent_type,
            "source_relative_path": selected_path.relative_to(repository_root).as_posix(),
            "source_sha256": selected_digest,
        }
        prepared: dict[str, object] = {
            "repository": asdict(repository),
            "selected_agent": selected,
            "enforcement_sources": [
                asdict(source) for source in request.enforcement_sources
            ],
            "policy_sha256": policy_digest,
        }
        return prepared, policy

    def _validate_isolation(
        self,
        protected_root: Path,
        policy_path: Path,
        worker_roots: tuple[Path, ...],
    ) -> None:
        protected_paths = (
            protected_root,
            policy_path,
            self._issuer_module_path,
            self._db_path,
            Path(f"{self._db_path}-wal"),
            Path(f"{self._db_path}-shm"),
        )
        if not protected_root.is_absolute() or not protected_root.exists():
            raise IsolationBoundaryError("protected installation root is unavailable")
        if not policy_path.is_absolute() or not policy_path.is_file():
            raise ManifestValidationError("admission policy is unavailable")
        if not _path_is_within(self._issuer_module_path, protected_root):
            raise IsolationBoundaryError("authority issuer is outside protected installation")
        if not _path_is_within(policy_path, protected_root):
            raise IsolationBoundaryError("admission policy is outside protected installation")
        for worker_root in worker_roots:
            for protected_path in protected_paths:
                if _path_is_within(protected_path, worker_root) or _path_is_within(
                    worker_root, protected_path
                ):
                    raise IsolationBoundaryError(
                        "protected path overlaps a Worker-writable root"
                    )

    def _repository_binding(self, root: Path) -> RepositoryBinding:
        if not root.is_dir():
            raise ManifestValidationError("repository root is unavailable")
        git_environment = trusted_command_env()
        for name in tuple(git_environment):
            if name.startswith("GIT_CONFIG_"):
                del git_environment[name]
        git_environment.update(
            {
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_OPTIONAL_LOCKS": "0",
            }
        )
        git_command = [
            "git",
            "--no-pager",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-C",
            str(root),
        ]
        try:
            head = subprocess.run(
                [*git_command, "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                env=git_environment,
            ).stdout.strip()
            tree = subprocess.run(
                [*git_command, "ls-files", "-s"],
                check=True,
                capture_output=True,
                text=True,
                env=git_environment,
            ).stdout
            status = subprocess.run(
                [*git_command, "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
                env=git_environment,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ManifestValidationError("repository binding is unavailable") from exc
        return RepositoryBinding(
            root_sha256=_sha256_json("probos.repository-root.v1", str(root)),
            head_sha=head,
            tracked_tree_sha256=_sha256_bytes(
                "probos.repository-tracked-tree.v1", tree.encode("utf-8")
            ),
            dirty=bool(status),
        )

    def _load_policy(self, content: bytes) -> dict[str, bool]:
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ManifestValidationError("admission policy is unreadable") from exc
        if not isinstance(payload, dict) or set(payload) != {"operations"}:
            raise ManifestValidationError("admission policy has unsupported fields")
        operations = payload["operations"]
        if not isinstance(operations, list):
            raise ManifestValidationError("admission policy operations must be a list")
        policy: dict[str, bool] = {}
        handlers: set[str] = set()
        for claim in operations:
            if (
                not isinstance(claim, dict)
                or set(claim) != {"operation_kind", "handler", "allow"}
                or not isinstance(claim["operation_kind"], str)
                or _metadata_identifier(claim["operation_kind"]) is None
                or not isinstance(claim["handler"], str)
                or _metadata_identifier(claim["handler"]) is None
                or type(claim["allow"]) is not bool
            ):
                raise ManifestValidationError("admission policy claim is malformed")
            operation = claim["operation_kind"]
            handler = claim["handler"]
            if operation in policy or handler in handlers:
                raise ManifestValidationError(
                    "duplicate effective operation or handler claim"
                )
            policy[operation] = claim["allow"]
            handlers.add(handler)
        return policy


class _WitnessSchema:
    async def migrate_or_validate(self, db: DatabaseConnection) -> None:
        row = await self._fetchone(db, "PRAGMA user_version")
        version = int(row[0]) if row is not None else -1
        if version == 0:
            try:
                await db.execute("BEGIN IMMEDIATE")
                for statement in _SCHEMA_STATEMENTS:
                    await db.execute(statement)
                await db.execute(
                    "INSERT INTO authority_meta VALUES (1,2,?,?,?,?)",
                    (str(uuid.uuid4()), 0, "", _now_ms()),
                )
                await db.execute("PRAGMA user_version=2")
                await self._validate(db)
                await db.commit()
            except BaseException:
                try:
                    await db.execute("ROLLBACK")
                except BaseException:
                    logger.error(
                        "protected witness migration rollback failed operation=migrate "
                        "attempt_id=none manifest_id=none generation=0 "
                        "reason_code=rollback_failed; startup remains failed"
                    )
                raise
        elif version == 1:
            await self._migrate_v1_to_v2(db)
        elif version != EXECUTION_WITNESS_SCHEMA_VERSION:
            raise WitnessSchemaError("unsupported protected witness schema version")
        await self._validate(db)

    async def _migrate_v1_to_v2(self, db: DatabaseConnection) -> None:
        await self._validate_v1(db)
        required_v1 = {
            "authority_meta",
            "execution_manifests",
            "manifest_sources",
            "admission_attempts",
            "execution_grants",
        }
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        observed = {str(row[0]) for row in await cursor.fetchall()}
        if not required_v1.issubset(observed):
            raise WitnessSchemaError("protected witness v1 is partial")
        meta = await self._fetchone(
            db, "SELECT schema_version FROM authority_meta WHERE singleton=1"
        )
        if meta is None or int(meta[0]) != 1:
            raise WitnessSchemaError("protected witness v1 metadata drift")
        effect_statements = tuple(
            statement for statement in _SCHEMA_STATEMENTS
            if statement.startswith("CREATE TABLE effect_")
            or statement.startswith("CREATE INDEX idx_effect_")
        )
        try:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute("ALTER TABLE authority_meta RENAME TO authority_meta_v1")
            await db.execute(_TABLE_SQL["authority_meta"])
            await db.execute(
                "INSERT INTO authority_meta "
                "(singleton,schema_version,host_instance_id,current_generation,"
                "process_id,updated_at_ms) "
                "SELECT singleton,2,host_instance_id,current_generation,"
                "process_id,updated_at_ms FROM authority_meta_v1"
            )
            await db.execute("DROP TABLE authority_meta_v1")
            for statement in effect_statements:
                await db.execute(statement)
            await db.execute("PRAGMA user_version=2")
            await self._validate(db)
            await db.commit()
        except BaseException:
            try:
                await db.execute("ROLLBACK")
            except BaseException:
                logger.error(
                    "protected witness migration rollback failed operation=migrate "
                    "attempt_id=none manifest_id=none generation=0 "
                    "reason_code=rollback_failed; startup remains failed"
                )
            raise

    async def _validate_v1(self, db: DatabaseConnection) -> None:
        v1_tables = (
            "authority_meta",
            "execution_manifests",
            "manifest_sources",
            "admission_attempts",
            "execution_grants",
        )
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
        observed_tables = {str(row[0]) for row in await cursor.fetchall()}
        if observed_tables != set(v1_tables):
            raise WitnessSchemaError("protected witness v1 table drift")
        for table in v1_tables:
            cursor = await db.execute(f"PRAGMA table_info({table})")
            columns = tuple(str(row[1]) for row in await cursor.fetchall())
            if columns != _TABLE_COLUMNS[table]:
                raise WitnessSchemaError("protected witness v1 column drift")
            schema_row = await self._fetchone(
                db,
                "SELECT sql FROM sqlite_master WHERE type='table' "
                f"AND name='{table}'",
            )
            expected_sql = _TABLE_SQL[table]
            if table == "authority_meta":
                expected_sql = expected_sql.replace(
                    "CHECK(schema_version=2)", "CHECK(schema_version=1)"
                )
            if schema_row is None or _normalize_schema_sql(
                str(schema_row[0])
            ) != _normalize_schema_sql(expected_sql):
                raise WitnessSchemaError("protected witness v1 definition drift")
            cursor = await db.execute(f"PRAGMA foreign_key_list({table})")
            foreign_keys = {
                (
                    str(row[2]),
                    str(row[3]),
                    str(row[4]),
                    str(row[5]),
                    str(row[6]),
                )
                for row in await cursor.fetchall()
            }
            if foreign_keys != _EXPECTED_FOREIGN_KEYS[table]:
                raise WitnessSchemaError("protected witness v1 foreign key drift")
        expected_indexes = {
            name: value
            for name, value in _REQUIRED_INDEXES.items()
            if value[0] in v1_tables
        }
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name NOT LIKE 'sqlite_%'"
        )
        if {str(row[0]) for row in await cursor.fetchall()} != set(expected_indexes):
            raise WitnessSchemaError("protected witness v1 index drift")
        for index, (table, expected_columns) in expected_indexes.items():
            schema_row = await self._fetchone(
                db,
                "SELECT tbl_name,sql FROM sqlite_master WHERE type='index' "
                f"AND name='{index}'",
            )
            if (
                schema_row is None
                or str(schema_row[0]) != table
                or _normalize_schema_sql(str(schema_row[1]))
                != _normalize_schema_sql(_INDEX_SQL[index])
            ):
                raise WitnessSchemaError("protected witness v1 index drift")
            cursor = await db.execute(f"PRAGMA index_info({index})")
            if tuple(str(row[2]) for row in await cursor.fetchall()) != expected_columns:
                raise WitnessSchemaError("protected witness v1 index drift")
        cursor = await db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' LIMIT 1"
        )
        if await cursor.fetchone() is not None:
            raise WitnessSchemaError("protected witness v1 triggers are not allowed")
        meta = await self._fetchone(
            db,
            "SELECT schema_version FROM authority_meta WHERE singleton=1"
        )
        if meta is None or type(meta[0]) is not int or int(meta[0]) != 1:
            raise WitnessSchemaError("protected witness v1 metadata drift")

    async def _validate(self, db: DatabaseConnection) -> None:
        user_version = await self._fetchone(db, "PRAGMA user_version")
        if user_version is None or int(user_version[0]) != 2:
            raise WitnessSchemaError("protected witness schema version drift")
        for table, expected in _TABLE_COLUMNS.items():
            cursor = await db.execute(f"PRAGMA table_info({table})")
            rows = await cursor.fetchall()
            observed = tuple(str(row[1]) for row in rows)
            if observed != expected:
                raise WitnessSchemaError("protected witness schema column drift")
            schema_row = await self._fetchone(
                db,
                "SELECT sql FROM sqlite_master WHERE type='table' "
                f"AND name='{table}'",
            )
            if schema_row is None or _normalize_schema_sql(
                str(schema_row[0])
            ) != _normalize_schema_sql(_TABLE_SQL[table]):
                raise WitnessSchemaError("protected witness table definition drift")
            cursor = await db.execute(f"PRAGMA foreign_key_list({table})")
            foreign_keys = {
                (
                    str(row[2]),
                    str(row[3]),
                    str(row[4]),
                    str(row[5]),
                    str(row[6]),
                )
                for row in await cursor.fetchall()
            }
            if foreign_keys != _EXPECTED_FOREIGN_KEYS[table]:
                raise WitnessSchemaError("protected witness foreign key drift")
        meta = await self._fetchone(
            db,
            "SELECT schema_version FROM authority_meta WHERE singleton=1"
        )
        if meta is None or type(meta[0]) is not int or int(meta[0]) != 2:
            raise WitnessSchemaError("protected witness metadata version drift")
        for index, (table, expected_columns) in _REQUIRED_INDEXES.items():
            schema_row = await self._fetchone(
                db,
                "SELECT tbl_name, sql FROM sqlite_master WHERE type='index' "
                f"AND name='{index}'",
            )
            if (
                schema_row is None
                or str(schema_row[0]) != table
                or _normalize_schema_sql(str(schema_row[1]))
                != _normalize_schema_sql(_INDEX_SQL[index])
            ):
                raise WitnessSchemaError("protected witness index definition drift")
            cursor = await db.execute(f"PRAGMA index_info({index})")
            columns = tuple(str(row[2]) for row in await cursor.fetchall())
            if columns != expected_columns:
                raise WitnessSchemaError("protected witness index column drift")
        witness_tables = ",".join(f"'{table}'" for table in _TABLE_COLUMNS)
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            f"AND tbl_name IN ({witness_tables}) ORDER BY name"
        )
        if await cursor.fetchall():
            raise WitnessSchemaError("protected witness triggers are not allowed")
        for table, fields in _SQLITE_INTEGER_FIELDS.items():
            for column, minimum, maximum, nullable in fields:
                predicate = (
                    f"typeof({column})!='integer' OR "
                    f"{column}<{minimum} OR {column}>{maximum}"
                )
                if nullable:
                    predicate = f"{column} IS NOT NULL AND ({predicate})"
                row = await self._fetchone(
                    db,
                    f"SELECT 1 FROM {table} WHERE {predicate} LIMIT 1",
                )
                if row is not None:
                    raise WitnessSchemaError(
                        "protected witness persisted integer drift"
                    )

    async def _fetchone(
        self, db: DatabaseConnection, sql: str
    ) -> object:
        cursor = await db.execute(sql)
        return await cursor.fetchone()


class _WitnessTransactions:
    async def fetchone(
        self,
        db: DatabaseConnection,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> object:
        cursor = await db.execute(sql, parameters)
        return await cursor.fetchone()

    async def rollback(self, db: DatabaseConnection, generation: int) -> bool:
        try:
            await db.execute("ROLLBACK")
        except BaseException:
            logger.error(
                "protected witness rollback failed operation=rollback "
                "attempt_id=none manifest_id=none generation=%d "
                "reason_code=rollback_failed; connection will be disabled",
                generation,
            )
            return False
        return True


class _AdmissionDurability:
    def __init__(self, transactions: _WitnessTransactions) -> None:
        self._transactions = transactions

    async def verify(
        self,
        db: DatabaseConnection,
        decision: AdmissionDecision,
    ) -> None:
        attempt = await self._transactions.fetchone(
            db,
            "SELECT outcome, reason_code FROM admission_attempts WHERE attempt_id=?",
            (decision.attempt_id,),
        )
        if attempt is None or (
            str(attempt[0]) != decision.outcome
            or str(attempt[1]) != decision.reason_code
        ):
            raise WitnessUnavailableError(
                "admission terminal postcondition could not be confirmed"
            )
        if decision.outcome != "admitted":
            if decision.grant is not None:
                raise WitnessUnavailableError(
                    "admission terminal postcondition could not be confirmed"
                )
            return
        grant = decision.grant
        if grant is None:
            raise WitnessUnavailableError(
                "admission grant postcondition could not be confirmed"
            )
        row = await self._transactions.fetchone(
            db,
            "SELECT attempt_id, manifest_id, generation, runtime_session_sha256, "
            "state, revoked_at_ms, revoked_reason FROM execution_grants "
            "WHERE grant_id=?",
            (grant.grant_id,),
        )
        if row is None or (
            str(row[0]) != grant.attempt_id
            or str(row[1]) != grant.manifest_id
            or int(row[2]) != grant.generation
            or str(row[3]) != grant.runtime_session_sha256
            or str(row[4]) != "active"
            or row[5] is not None
            or str(row[6]) != ""
        ):
            raise WitnessUnavailableError(
                "admission grant postcondition could not be confirmed"
            )

    async def record_failed(
        self,
        db: DatabaseConnection,
        attempt_id: str,
        rollback_or_disable: Callable[[DatabaseConnection], Awaitable[None]],
    ) -> None:
        try:
            now = _now_ms()
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "UPDATE admission_attempts SET outcome='failed', "
                "reason_code='evaluation_failed', resolved_at_ms=?, failed_at_ms=? "
                "WHERE attempt_id=? AND outcome='pending'",
                (now, now, attempt_id),
            )
            await db.commit()
        except asyncio.CancelledError:
            await rollback_or_disable(db)
            raise
        except Exception as exc:
            await rollback_or_disable(db)
            raise WitnessUnavailableError(
                "failed admission outcome could not commit"
            ) from exc


class _AdmissionNormalizer:
    def normalize(
        self,
        request: AdmissionRequest,
        active_manifest: ExecutionManifest | None,
        policy: dict[str, bool],
    ) -> tuple[bool, dict[str, object]]:
        manifest_identifier = _issued_identifier(request.manifest_id)
        operation_identifier = _metadata_identifier(request.operation_kind)
        generation = (
            request.generation
            if type(request.generation) is int
            and 0 <= request.generation <= _SQLITE_INTEGER_MAX
            else None
        )
        issued_manifest_id = (
            manifest_identifier
            if active_manifest is not None
            and manifest_identifier == active_manifest.manifest_id
            else None
        )
        valid = (
            manifest_identifier is not None
            and generation is not None
            and isinstance(request.runtime_session_id, str)
            and bool(request.runtime_session_id)
            and operation_identifier is not None
            and isinstance(request.target_identity, str)
            and bool(request.target_identity)
            and _is_sha256(request.parameter_shape_sha256)
        )
        return valid, {
            "manifest_id": issued_manifest_id,
            "generation": generation,
            "runtime_session_sha256": _bounded_text_hash(
                request.runtime_session_id, "probos.runtime-session.v1"
            ),
            "operation_kind": (
                operation_identifier
                if operation_identifier in policy
                else "unknown"
            ),
            "operation_in_policy": operation_identifier in policy,
            "target_sha256": _bounded_text_hash(
                request.target_identity, "probos.admission-target.v1"
            ),
            "parameter_shape_sha256": (
                request.parameter_shape_sha256
                if _is_sha256(request.parameter_shape_sha256)
                else _bounded_text_hash(
                    request.parameter_shape_sha256,
                    "probos.parameter-shape-malformed.v1",
                )
            ),
        }


class _AdmissionTransactions:
    def __init__(self, transactions: _WitnessTransactions) -> None:
        self._transactions = transactions

    async def resolve(
        self,
        db: DatabaseConnection,
        attempt_id: str,
        valid: bool,
        values: dict[str, object],
        *,
        process_id: str,
        active_manifest: ExecutionManifest | None,
        runtime_session_sha256: str,
        policy_allows: Callable[[str], bool],
    ) -> AdmissionDecision:
        row = await self._transactions.fetchone(
            db,
            "SELECT current_generation, process_id FROM authority_meta WHERE singleton=1",
        )
        if row is None:
            raise WitnessSchemaError("authority metadata row is missing")
        now = _now_ms()
        outcome: Literal["admitted", "denied", "rejected", "failed"]
        reason: str
        grant: ExecutionGrant | None = None
        if str(row[1]) != process_id:
            outcome, reason = "denied", "issuer_superseded"
        elif active_manifest is None:
            outcome, reason = "denied", "manifest_unavailable"
        elif not valid:
            outcome, reason = "rejected", "malformed_request"
        elif values["manifest_id"] != active_manifest.manifest_id:
            outcome, reason = "denied", "manifest_mismatch"
        elif values["generation"] != int(row[0]):
            outcome, reason = "denied", "generation_mismatch"
        elif values["runtime_session_sha256"] != runtime_session_sha256:
            outcome, reason = "denied", "runtime_session_mismatch"
        elif not values["operation_in_policy"]:
            outcome, reason = "denied", "policy_refused"
        else:
            operation = str(values["operation_kind"])
            try:
                allowed = policy_allows(operation)
            except Exception:
                outcome, reason = "failed", "evaluation_failed"
            else:
                outcome, reason = ("admitted", "policy_allowed") if allowed else (
                    "denied", "policy_refused"
                )
            if outcome == "admitted":
                grant = ExecutionGrant(
                    grant_id=str(uuid.uuid4()),
                    attempt_id=attempt_id,
                    manifest_id=active_manifest.manifest_id,
                    generation=int(row[0]),
                    runtime_session_sha256=runtime_session_sha256,
                )
                await db.execute(
                    "INSERT INTO execution_grants VALUES "
                    "(?,?,?,?,?,?,'active',NULL,'')",
                    (
                        grant.grant_id, grant.attempt_id, grant.manifest_id,
                        grant.generation, grant.runtime_session_sha256, now,
                    ),
                )
        await db.execute(
            "UPDATE admission_attempts SET outcome=?, reason_code=?, resolved_at_ms=?, "
            "admitted_at_ms=?, failed_at_ms=? "
            "WHERE attempt_id=? AND outcome='pending'",
            (
                outcome, reason, now, now if outcome == "admitted" else None,
                now if outcome == "failed" else None,
                attempt_id,
            ),
        )
        return AdmissionDecision(attempt_id, outcome, reason, grant)

    async def validate_grant_binding(
        self,
        db: DatabaseConnection,
        grant: ExecutionGrant,
        *,
        process_id: str,
        runtime_session_sha256: str,
    ) -> None:
        row = await self._transactions.fetchone(
            db,
            "SELECT g.state,a.outcome,a.manifest_id,a.presented_generation,"
            "a.runtime_session_sha256,g.manifest_id,g.generation,"
            "g.runtime_session_sha256,m.process_id,x.current_generation,x.process_id "
            "FROM execution_grants g "
            "JOIN admission_attempts a ON a.attempt_id=g.attempt_id "
            "JOIN execution_manifests m ON m.manifest_id=g.manifest_id "
            "JOIN authority_meta x ON x.singleton=1 "
            "WHERE g.grant_id=? AND g.attempt_id=?",
            (grant.grant_id, grant.attempt_id),
        )
        if row is None or (
            str(row[0]) != "active"
            or str(row[1]) != "admitted"
            or str(row[2]) != grant.manifest_id
            or row[3] != grant.generation
            or str(row[4]) != grant.runtime_session_sha256
            or str(row[5]) != grant.manifest_id
            or row[6] != grant.generation
            or str(row[7]) != grant.runtime_session_sha256
            or str(row[7]) != runtime_session_sha256
            or str(row[8]) != process_id
            or row[9] != grant.generation
            or str(row[10]) != process_id
        ):
            raise StaleGrantError("grant is not active for the current issuer")


class _ProtectedExecutionAuthorityCore:
    """Runtime-owned strict issuer backed by one durable SQLite witness."""

    def __init__(
        self,
        *,
        db_path: Path,
        runtime_session_id: str,
        witness_busy_timeout_ms: int,
        protected_installation_root: Path,
        policy_path: Path,
        worker_write_roots: tuple[Path, ...],
        connection_factory: ConnectionFactory | None = None,
        issuer_module_path: Path | None = None,
    ) -> None:
        self._db_path = db_path.resolve()
        self._runtime_session_id = runtime_session_id
        self._runtime_session_sha256 = _sha256_json(
            "probos.runtime-session.v1", runtime_session_id
        )
        self._busy_timeout_ms = witness_busy_timeout_ms
        self._protected_installation_root = protected_installation_root.resolve()
        self._policy_path = policy_path.resolve()
        self._worker_write_roots = tuple(path.resolve() for path in worker_write_roots)
        self._connection_factory = connection_factory or default_factory
        self._issuer_module_path = (issuer_module_path or Path(__file__)).resolve()
        self._manifest_preparer = _ManifestPreparer(
            db_path=self._db_path,
            protected_installation_root=self._protected_installation_root,
            policy_path=self._policy_path,
            worker_write_roots=self._worker_write_roots,
            issuer_module_path=self._issuer_module_path,
        )
        self._schema = _WitnessSchema()
        self._transactions = _WitnessTransactions()
        self._admission_durability = _AdmissionDurability(self._transactions)
        self._admission_normalizer = _AdmissionNormalizer()
        self._admission_transactions = _AdmissionTransactions(self._transactions)
        self._db: DatabaseConnection | None = None
        self._lock = asyncio.Lock()
        self._closed = True
        self._host_instance_id = ""
        self._process_id = ""
        self._generation = 0
        self._active_manifest: ExecutionManifest | None = None
        self._active_fingerprint = ""
        self._policy: dict[str, bool] = {}

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _next_generation(self, generation: int) -> int:
        if generation >= _SQLITE_INTEGER_MAX:
            raise WitnessSchemaError("protected witness generation is exhausted")
        return generation + 1

    def _policy_allows(self, operation: str) -> bool:
        return self._policy.get(operation, False)

    def _require_db(self) -> DatabaseConnection:
        if self._closed or self._db is None:
            raise WitnessUnavailableError("protected witness is not available")
        return self._db

    async def _rollback_or_disable(self, db: DatabaseConnection) -> None:
        if await self._transactions.rollback(db, self._generation):
            return
        if self._db is db:
            self._db = None
        self._closed = True
        self._active_manifest = None
        self._active_fingerprint = ""
        self._policy = {}
        try:
            await db.close()
        except BaseException:
            logger.error(
                "protected witness disable close failed operation=rollback "
                "attempt_id=none manifest_id=none generation=%d "
                "reason_code=close_failed; witness remains disabled",
                self._generation,
            )

    async def _rollback_and_close(self) -> None:
        db = self._db
        self._db = None
        self._closed = True
        if db is None:
            return
        await self._transactions.rollback(db, self._generation)
        try:
            await db.close()
        except BaseException:
            logger.error(
                "protected witness cleanup failed operation=start "
                "attempt_id=none manifest_id=none generation=%d "
                "reason_code=cleanup_failed; startup remains failed",
                self._generation,
            )

    async def start(self) -> None:
        async with self._lock:
            if self._db is not None and not self._closed:
                return
            self._manifest_preparer.validate_configured_isolation()
            try:
                db = await self._connection_factory.connect(str(self._db_path))
                self._db = db
                await db.execute("PRAGMA foreign_keys = ON")
                await db.execute("PRAGMA journal_mode = WAL")
                await db.execute("PRAGMA synchronous = FULL")
                await db.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
                await self._schema.migrate_or_validate(db)
                await db.execute("BEGIN IMMEDIATE")
                row = await self._transactions.fetchone(
                    db,
                    "SELECT host_instance_id, current_generation FROM authority_meta "
                    "WHERE singleton=1",
                )
                if row is None:
                    raise WitnessSchemaError("authority metadata row is missing")
                now = _now_ms()
                self._host_instance_id = str(row[0])
                self._generation = self._next_generation(int(row[1]))
                self._process_id = str(uuid.uuid4())
                await db.execute(
                    "UPDATE authority_meta SET current_generation=?, process_id=?, "
                    "updated_at_ms=? WHERE singleton=1",
                    (self._generation, self._process_id, now),
                )
                await db.execute(
                    "UPDATE execution_grants SET state='revoked', revoked_at_ms=?, "
                    "revoked_reason='issuer_restarted' "
                    "WHERE state='active' AND generation < ?",
                    (now, self._generation),
                )
                await db.execute(
                    "UPDATE admission_attempts SET outcome='failed', "
                    "reason_code='issuer_interrupted', resolved_at_ms=?, failed_at_ms=? "
                    "WHERE outcome='pending'",
                    (now, now),
                )
                await db.commit()
                self._closed = False
                self._active_manifest = None
                self._active_fingerprint = ""
                self._policy = {}
            except (WitnessSchemaError, IsolationBoundaryError):
                await self._rollback_and_close()
                raise
            except Exception as exc:
                await self._rollback_and_close()
                raise WitnessUnavailableError(
                    "protected witness startup could not commit"
                ) from exc
            except BaseException:
                await self._rollback_and_close()
                raise

    async def stop(self) -> None:
        async with self._lock:
            db = self._db
            self._closed = True
            self._active_manifest = None
            self._active_fingerprint = ""
            self._policy = {}
            self._db = None
            if db is not None:
                try:
                    await db.close()
                except Exception as exc:
                    raise WitnessUnavailableError(
                        "protected witness close failed after admission was disabled"
                    ) from exc

    async def publish_manifest(
        self, request: ManifestPublicationRequest
    ) -> ExecutionManifest:
        async with self._lock:
            db = self._require_db()
            prepared, policy = self._manifest_preparer.prepare(request)
            fingerprint = _sha256_json("probos.execution-manifest.v1", prepared)
            try:
                await db.execute("BEGIN IMMEDIATE")
                row = await self._transactions.fetchone(
                    db,
                    "SELECT current_generation, process_id FROM authority_meta "
                    "WHERE singleton=1",
                )
                if row is None:
                    raise WitnessSchemaError("authority metadata row is missing")
                if str(row[1]) != self._process_id:
                    raise StaleGrantError(
                        "manifest issuer is not the current durable issuer"
                    )
                if (
                    self._active_manifest is not None
                    and self._active_fingerprint == fingerprint
                ):
                    await db.commit()
                    return self._active_manifest
                generation = self._next_generation(int(row[0]))
                created_at = _now_ms()
                manifest_id = str(uuid.uuid4())
                repository = RepositoryBinding(**prepared["repository"])
                host = HostBinding(
                    host_instance_id=self._host_instance_id,
                    process_id=self._process_id,
                    os_pid=os.getpid(),
                    runtime_session_sha256=self._runtime_session_sha256,
                )
                selected = SelectedAgentBinding(**prepared["selected_agent"])
                sources = tuple(request.enforcement_sources)
                payload = {
                    **prepared,
                    "version": EXECUTION_MANIFEST_VERSION,
                    "manifest_id": manifest_id,
                    "generation": generation,
                    "created_at_ms": created_at,
                    "host": asdict(host),
                }
                manifest_sha = _sha256_json("probos.execution-manifest.v1", payload)
                manifest = ExecutionManifest(
                    version=1,
                    manifest_id=manifest_id,
                    generation=generation,
                    created_at_ms=created_at,
                    repository=repository,
                    host=host,
                    selected_agent=selected,
                    enforcement_sources=sources,
                    policy_sha256=str(prepared["policy_sha256"]),
                    manifest_sha256=manifest_sha,
                )
                await db.execute(
                    "INSERT INTO execution_manifests VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        manifest.manifest_id, manifest.version, manifest.generation,
                        manifest.created_at_ms, host.host_instance_id, host.process_id,
                        host.os_pid, host.runtime_session_sha256,
                        repository.root_sha256, repository.head_sha,
                        repository.tracked_tree_sha256, int(repository.dirty),
                        selected.agent_id_sha256, selected.agent_type,
                        selected.source_relative_path, selected.source_sha256,
                        manifest.policy_sha256, manifest.manifest_sha256,
                    ),
                )
                await db.executemany(
                    "INSERT INTO manifest_sources VALUES (?,?,?,?,?,?)",
                    (
                        (
                            manifest.manifest_id, source.kind, source.name,
                            source.sha256, source.version, source.item_count,
                        )
                        for source in sources
                    ),
                )
                await db.execute(
                    "UPDATE execution_grants SET state='revoked', revoked_at_ms=?, "
                    "revoked_reason='manifest_rotated' WHERE state='active'",
                    (created_at,),
                )
                await db.execute(
                    "UPDATE authority_meta SET current_generation=?, updated_at_ms=? "
                    "WHERE singleton=1",
                    (generation, created_at),
                )
                await db.commit()
            except asyncio.CancelledError:
                await self._rollback_or_disable(db)
                raise
            except (ManifestValidationError, WitnessSchemaError, StaleGrantError):
                await self._rollback_or_disable(db)
                raise
            except Exception as exc:
                await self._rollback_or_disable(db)
                raise WitnessUnavailableError(
                    "manifest publication could not commit"
                ) from exc
            self._generation = generation
            self._active_manifest = manifest
            self._active_fingerprint = fingerprint
            self._policy = policy
            logger.info(
                "protected manifest published operation=publish_manifest "
                "manifest_id=%s generation=%d reason_code=manifest_committed",
                manifest.manifest_id,
                manifest.generation,
            )
            return manifest

    async def admit(self, request: AdmissionRequest) -> AdmissionDecision:
        async with self._lock:
            db = self._require_db()
            attempt_id = str(uuid.uuid4())
            requested_at = _now_ms()
            valid, values = self._admission_normalizer.normalize(
                request, self._active_manifest, self._policy
            )
            try:
                await db.execute("BEGIN IMMEDIATE")
                await db.execute(
                    "INSERT INTO admission_attempts VALUES "
                    "(?,?,?,?,?,?,?,?,?,'pending','pending',NULL,NULL)",
                    (
                        attempt_id, requested_at, None, values["manifest_id"],
                        values["generation"], values["runtime_session_sha256"],
                        values["operation_kind"], values["target_sha256"],
                        values["parameter_shape_sha256"],
                    ),
                )
                await db.commit()
            except asyncio.CancelledError:
                await self._rollback_or_disable(db)
                raise
            except Exception as exc:
                await self._rollback_or_disable(db)
                raise WitnessUnavailableError(
                    "admission pending attempt could not commit"
                ) from exc
            try:
                await db.execute("BEGIN IMMEDIATE")
                decision = await self._admission_transactions.resolve(
                    db,
                    attempt_id,
                    valid,
                    values,
                    process_id=self._process_id,
                    active_manifest=self._active_manifest,
                    runtime_session_sha256=self._runtime_session_sha256,
                    policy_allows=self._policy_allows,
                )
                await db.commit()
                await self._admission_durability.verify(db, decision)
            except asyncio.CancelledError:
                await self._rollback_or_disable(db)
                raise
            except WitnessUnavailableError:
                await self._rollback_or_disable(db)
                raise
            except Exception as exc:
                await self._rollback_or_disable(db)
                await self._admission_durability.record_failed(
                    db, attempt_id, self._rollback_or_disable
                )
                raise WitnessUnavailableError(
                    "admission terminal state could not commit"
                ) from exc
            logger.info(
                "protected admission resolved operation=admit attempt_id=%s "
                "manifest_id=%s generation=%s reason_code=%s",
                attempt_id,
                values["manifest_id"] or "none",
                values["generation"] if values["generation"] is not None else "none",
                decision.reason_code,
            )
            return decision

    async def validate_grant(self, grant: ExecutionGrant) -> None:
        async with self._lock:
            db = self._require_db()
            await self._admission_transactions.validate_grant_binding(
                db,
                grant,
                process_id=self._process_id,
                runtime_session_sha256=self._runtime_session_sha256,
            )

    async def mark_start_failed(
        self, grant: ExecutionGrant, *, reason_code: str
    ) -> None:
        if (
            not isinstance(reason_code, str)
            or _REASON_CODE_RE.fullmatch(reason_code) is None
        ):
            raise ValueError("reason_code must use bounded stable-code syntax")
        await self.validate_grant(grant)
        async with self._lock:
            db = self._require_db()
            now = _now_ms()
            try:
                await db.execute("BEGIN IMMEDIATE")
                await self._admission_transactions.validate_grant_binding(
                    db,
                    grant,
                    process_id=self._process_id,
                    runtime_session_sha256=self._runtime_session_sha256,
                )
                await db.execute(
                    "UPDATE admission_attempts SET outcome='failed', reason_code=?, "
                    "resolved_at_ms=?, failed_at_ms=? "
                    "WHERE attempt_id=? AND outcome='admitted'",
                    (reason_code, now, now, grant.attempt_id),
                )
                await db.execute(
                    "UPDATE execution_grants SET state='revoked', revoked_at_ms=?, "
                    "revoked_reason=? WHERE grant_id=? AND state='active'",
                    (now, reason_code, grant.grant_id),
                )
                await db.commit()
            except asyncio.CancelledError:
                await self._rollback_or_disable(db)
                raise
            except StaleGrantError:
                await self._rollback_or_disable(db)
                raise
            except Exception as exc:
                await self._rollback_or_disable(db)
                raise WitnessUnavailableError(
                    "failed-start evidence could not commit"
                ) from exc

    async def query_attempts(self) -> tuple[tuple[object, ...], ...]:
        async with self._lock:
            db = self._require_db()
            cursor = await db.execute(
                "SELECT * FROM admission_attempts ORDER BY requested_at_ms, attempt_id"
            )
            return tuple(await cursor.fetchall())

    async def query_grants(self) -> tuple[tuple[object, ...], ...]:
        async with self._lock:
            db = self._require_db()
            cursor = await db.execute(
                "SELECT * FROM execution_grants ORDER BY issued_at_ms, grant_id"
            )
            return tuple(await cursor.fetchall())


class _EffectDelegationMixin:
    async def authorize_effect_target(
        self, request: EffectTargetRequest
    ) -> EffectTargetDecision:
        if request.adapter_kind != "native_file" or request.effect_class != "filesystem":
            return EffectTargetDecision(False, "target_adapter_unsupported", "")
        try:
            target = Path(request.canonical_target).resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return EffectTargetDecision(False, "file_target_resolution_failed", "")
        protected = (
            self._protected_installation_root,
            self._db_path,
            self._policy_path,
            self._issuer_module_path,
        )
        if any(target == path or _path_is_within(target, path) for path in protected):
            return EffectTargetDecision(False, "file_target_protected", "")
        root = next(
            (candidate for candidate in self._worker_write_roots
             if target == candidate or _path_is_within(target, candidate)),
            None,
        )
        if root is None:
            return EffectTargetDecision(False, "file_target_outside_worker_root", "")
        manifest = self._active_manifest
        if manifest is None:
            raise StaleGrantError("target authorization requires an active manifest")
        binding = _sha256_json(
            "probos.effect-isolation-binding.v1",
            {
                "manifest": manifest.manifest_id,
                "generation": self._generation,
                "root": str(root),
                "target": str(target),
            },
        )
        return EffectTargetDecision(
            True, "target_authorized", binding, authorized_root=str(root)
        )

    async def bind_delegated_run(self, binding: DelegationRunBinding) -> None:
        if (
            _issued_identifier(binding.parent_operation_id) is None
            or _issued_identifier(binding.parent_attempt_id) is None
            or not binding.child_agent_id
            or not binding.child_run_id
            or not binding.binding_token
        ):
            raise ValueError("delegation binding contains invalid trusted fields")
        async with self._lock:
            db = self._require_db()
            now = _now_ms()
            expected = _sha256_json(
                "probos.effect-delegation-binding.v1",
                {
                    "operation": binding.parent_operation_id,
                    "attempt": binding.parent_attempt_id,
                    "agent": binding.child_agent_id,
                    "run": binding.child_run_id,
                    "token": binding.binding_token,
                },
            )
            try:
                await db.execute("BEGIN IMMEDIATE")
                parent = await self._transactions.fetchone(
                    db,
                    "SELECT o.effect_class,o.state,o.manifest_id,o.generation,a.state "
                    "FROM effect_operations o JOIN effect_attempts a "
                    "ON a.operation_id=o.operation_id "
                    "WHERE o.operation_id=? AND a.attempt_id=?",
                    (binding.parent_operation_id, binding.parent_attempt_id),
                )
                manifest = self._active_manifest
                if (
                    parent is None
                    or manifest is None
                    or str(parent[0]) != "delegation"
                    or str(parent[1]) != "running"
                    or str(parent[2]) != manifest.manifest_id
                    or int(parent[3]) != self._generation
                    or str(parent[4]) != "running"
                ):
                    raise StaleGrantError("delegation parent is not running")
                await db.execute(
                    "INSERT INTO effect_delegation_bindings VALUES "
                    "(?,?,?,?,?,'active',?,NULL)",
                    (
                        binding.parent_operation_id,
                        binding.parent_attempt_id,
                        _sha256_json(
                            "probos.selected-agent-id.v1", binding.child_agent_id
                        ),
                        _sha256_json(
                            "probos.effect-child-run.v1", binding.child_run_id
                        ),
                        expected,
                        now,
                    ),
                )
                await db.commit()
            except asyncio.CancelledError:
                await self._rollback_or_disable(db)
                raise
            except StaleGrantError:
                await self._rollback_or_disable(db)
                raise
            except Exception as exc:
                await self._rollback_or_disable(db)
                raise WitnessUnavailableError(
                    "delegation binding could not commit"
                ) from exc

    async def _authorized_delegated_child(
        self,
        db: DatabaseConnection,
        effect: object,
        manifest: ExecutionManifest,
    ) -> bool:
        parent_operation_id = getattr(effect, "parent_operation_id", None)
        parent_attempt_id = getattr(effect, "parent_attempt_id", None)
        child_run_id = getattr(effect, "child_run_id", "")
        binding_token = getattr(effect, "binding_token", "")
        agent_id = getattr(effect, "agent_id", "")
        if not all(
            isinstance(value, str) and value
            for value in (
                parent_operation_id,
                parent_attempt_id,
                child_run_id,
                binding_token,
                agent_id,
            )
        ):
            return False
        row = await self._transactions.fetchone(
            db,
            "SELECT b.binding_sha256,o.effect_class,o.state,o.manifest_id,"
            "o.generation,a.state FROM effect_delegation_bindings b "
            "JOIN effect_operations o ON o.operation_id=b.parent_operation_id "
            "JOIN effect_attempts a ON a.attempt_id=b.parent_attempt_id "
            "WHERE b.parent_operation_id=? AND b.parent_attempt_id=? "
            "AND b.child_agent_id_sha256=? AND b.child_run_sha256=? "
            "AND b.state='active'",
            (
                parent_operation_id,
                parent_attempt_id,
                _sha256_json("probos.selected-agent-id.v1", agent_id),
                _sha256_json("probos.effect-child-run.v1", child_run_id),
            ),
        )
        expected = _sha256_json(
            "probos.effect-delegation-binding.v1",
            {
                "operation": parent_operation_id,
                "attempt": parent_attempt_id,
                "agent": agent_id,
                "run": child_run_id,
                "token": binding_token,
            },
        )
        return bool(
            row is not None
            and str(row[0]) == expected
            and str(row[1]) == "delegation"
            and str(row[2]) == "running"
            and str(row[3]) == manifest.manifest_id
            and int(row[4]) == self._generation
            and str(row[5]) == "running"
        )
class _EffectReservationMixin(_EffectDelegationMixin):
    """Atomic operation identity, grant validation, and intent reservation."""

    async def reserve_effect(
        self, request: EffectReserveRequest
    ) -> EffectReserveDecision:
        effect = request.request
        if (
            not isinstance(effect.logical_key, str)
            or not isinstance(effect.agent_id, str)
            or not effect.agent_id
            or not isinstance(effect.tool_id, str)
            or not effect.tool_id
            or not _is_sha256(effect.parameter_shape_sha256)
            or type(request.lease_seconds) is not int
            or not 1 <= request.lease_seconds <= 3600
            or type(request.max_attempts) is not int
            or not 1 <= request.max_attempts <= 10
        ):
            raise ValueError("effect reservation contains invalid trusted fields")
        async with self._lock:
            db = self._require_db()
            manifest = self._active_manifest
            if manifest is None:
                raise StaleGrantError("effect reservation requires an active manifest")
            malformed_logical_key = not effect.logical_key
            logical_key_sha256 = _sha256_json(
                "probos.effect-logical-key.v1",
                (
                    effect.logical_key
                    if not malformed_logical_key
                    else {"malformed_operation_id": request.permit.operation_id}
                ),
            )
            now = _now_ms()
            try:
                await db.execute("BEGIN IMMEDIATE")
                existing = await self._transactions.fetchone(
                    db,
                    "SELECT operation_id,state,reason_code,manifest_id,generation,"
                    "runtime_session_sha256,agent_id_sha256,"
                    "requested_tool_id_sha256,resolved_tool_id_sha256,"
                    "effect_class,adapter_kind,target_sha256,parameter_shape_sha256,"
                    "continuation_binding_sha256,isolation_binding_sha256,idempotency,"
                    "parent_operation_id,parent_attempt_id,child_run_sha256 "
                    "FROM effect_operations WHERE "
                    + (
                        "operation_id=?"
                        if request.operation_handle is not None
                        else "logical_key_sha256=?"
                    ),
                    (
                        request.operation_handle.operation_id
                        if request.operation_handle is not None
                        else logical_key_sha256,
                    ),
                )
                if existing is not None:
                    operation_id = str(existing[0])
                    state = str(existing[1])
                    reason = str(existing[2])
                    last_attempt = await self._transactions.fetchone(
                        db,
                        "SELECT attempt_id,ordinal,state FROM effect_attempts "
                        "WHERE operation_id=? ORDER BY ordinal DESC LIMIT 1",
                        (operation_id,),
                    )
                    attempt_id = str(last_attempt[0]) if last_attempt else ""
                    ordinal = int(last_attempt[1]) if last_attempt else 0
                    attempt_state = str(last_attempt[2]) if last_attempt else ""
                    agent_id_sha256 = _sha256_json(
                        "probos.selected-agent-id.v1", effect.agent_id
                    )
                    parent_authorized = (
                        await self._authorized_delegated_child(
                            db, effect, manifest
                        )
                        if effect.parent_operation_id is not None
                        else False
                    )
                    bindings_match = (
                        str(existing[3]) == manifest.manifest_id
                        and int(existing[4]) == self._generation
                        and str(existing[5]) == self._runtime_session_sha256
                        and str(existing[6]) == agent_id_sha256
                        and str(existing[7]) == _sha256_json(
                            "probos.effect-tool-id.v1", effect.tool_id
                        )
                        and str(existing[8]) == _sha256_json(
                            "probos.effect-tool-id.v1",
                            effect.resolved_tool_id or effect.tool_id,
                        )
                        and str(existing[9]) == effect.effect_class
                        and str(existing[10]) == effect.adapter_kind
                        and str(existing[11]) == _sha256_json(
                            "probos.effect-target.v1", effect.target_identity
                        )
                        and str(existing[12]) == effect.parameter_shape_sha256
                        and str(existing[13])
                        == effect.continuation_binding_sha256
                        and str(existing[14]) == effect.isolation_binding_sha256
                        and str(existing[15]) == effect.idempotency
                        and (
                            str(existing[16])
                            if existing[16] is not None
                            else None
                        ) == effect.parent_operation_id
                        and (
                            str(existing[17])
                            if existing[17] is not None
                            else None
                        ) == effect.parent_attempt_id
                        and str(existing[18]) == _sha256_json(
                            "probos.effect-child-run.v1", effect.child_run_id
                        )
                        and (
                            parent_authorized
                            if effect.parent_operation_id is not None
                            else agent_id_sha256
                            == manifest.selected_agent.agent_id_sha256
                        )
                    )
                    if not bindings_match:
                        await db.commit()
                        return EffectReserveDecision(
                            operation_id, attempt_id, "denied",
                            "operation_binding_mismatch", None, state,
                        )
                    if state in {
                        "result", "denied", "failed", "cancelled", "blocked"
                    }:
                        await db.commit()
                        return EffectReserveDecision(
                            operation_id, attempt_id, "duplicate",
                            "duplicate_terminal", None, state,
                        )
                    if state in {"running", "pending"}:
                        await db.commit()
                        return EffectReserveDecision(
                            operation_id, attempt_id, "blocked",
                            "blocked_unknown", None, state,
                        )
                    if state == "unknown":
                        await db.commit()
                        return EffectReserveDecision(
                            operation_id, attempt_id, "blocked",
                            "reconciliation_required", None, state,
                        )
                    if state == "ready" and attempt_state == "intent_committed":
                        await db.commit()
                        return EffectReserveDecision(
                            operation_id, attempt_id, "blocked",
                            "duplicate_in_flight", None, state,
                        )
                    if state != "ready" or ordinal >= request.max_attempts:
                        await db.execute(
                            "UPDATE effect_operations SET state='blocked', "
                            "reason_code='attempt_limit',updated_at_ms=? "
                            "WHERE operation_id=?",
                            (now, operation_id),
                        )
                        await self._insert_effect_transition(
                            db, operation_id, None, state, "blocked",
                            "attempt_limit", now,
                        )
                        await db.commit()
                        return EffectReserveDecision(
                            operation_id, attempt_id, "blocked",
                            "attempt_limit", None, "blocked",
                        )
                    attempt_id = str(uuid.uuid4())
                    ordinal += 1
                    grant = await self._active_effect_grant(db, manifest)
                    if grant is None:
                        await db.execute(
                            "UPDATE effect_operations SET state='denied', "
                            "reason_code='grant_unavailable',updated_at_ms=? "
                            "WHERE operation_id=?",
                            (now, operation_id),
                        )
                        await self._insert_effect_transition(
                            db, operation_id, None, "ready", "denied",
                            "grant_unavailable", now,
                        )
                        await db.commit()
                        return EffectReserveDecision(
                            operation_id, "", "denied", "grant_unavailable",
                            None, "denied",
                        )
                    permit = replace(
                        request.permit,
                        operation_id=operation_id,
                        attempt_id=attempt_id,
                        generation=self._generation,
                    )
                    await self._insert_effect_attempt(
                        db, permit, ordinal, grant, request.lease_seconds, now
                    )
                    await db.commit()
                    return EffectReserveDecision(
                        operation_id, attempt_id, "ready", "intent_committed",
                        permit, "ready",
                    )
                if request.operation_handle is not None:
                    await db.commit()
                    return EffectReserveDecision(
                        request.operation_handle.operation_id,
                        request.operation_handle.attempt_id,
                        "denied",
                        "operation_handle_unknown",
                        None,
                        "denied",
                    )

                operation_id = request.permit.operation_id
                attempt_id = request.permit.attempt_id
                agent_id_sha256 = _sha256_json(
                    "probos.selected-agent-id.v1", effect.agent_id
                )
                provider_call_hash = _sha256_json(
                    "probos.effect-provider-call.v1", effect.provider_call_id or ""
                )
                parent_authorized = False
                if effect.parent_operation_id is not None:
                    parent_authorized = await self._authorized_delegated_child(
                        db, effect, manifest
                    )
                await db.execute(
                    "INSERT INTO effect_operations("
                    "operation_id,logical_key_sha256,manifest_id,generation,"
                    "runtime_session_sha256,agent_id_sha256,"
                    "requested_tool_id_sha256,resolved_tool_id_sha256,"
                    "effect_class,adapter_kind,target_sha256,"
                    "parameter_shape_sha256,continuation_binding_sha256,"
                    "isolation_binding_sha256,idempotency,parent_operation_id,"
                    "parent_attempt_id,child_run_sha256,provider_call_id_sha256,"
                    "state,reason_code,result_sha256,receipt_sha256,"
                    "created_at_ms,updated_at_ms) VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
                    "'pending','pending','','',?,?)",
                    (
                        operation_id,
                        logical_key_sha256,
                        manifest.manifest_id,
                        self._generation,
                        self._runtime_session_sha256,
                        agent_id_sha256,
                        _sha256_json("probos.effect-tool-id.v1", effect.tool_id),
                        _sha256_json(
                            "probos.effect-tool-id.v1",
                            effect.resolved_tool_id or effect.tool_id,
                        ),
                        effect.effect_class,
                        effect.adapter_kind,
                        _sha256_json(
                            "probos.effect-target.v1", effect.target_identity
                        ),
                        effect.parameter_shape_sha256,
                        effect.continuation_binding_sha256,
                        effect.isolation_binding_sha256,
                        effect.idempotency,
                        (
                            effect.parent_operation_id
                            if parent_authorized else None
                        ),
                        (
                            effect.parent_attempt_id
                            if parent_authorized else None
                        ),
                        _sha256_json(
                            "probos.effect-child-run.v1", effect.child_run_id
                        ),
                        provider_call_hash,
                        now,
                        now,
                    ),
                )
                await self._insert_effect_transition(
                    db, operation_id, None, "new", "pending", "pending", now
                )
                grant = await self._active_effect_grant(db, manifest)
                denial_reason = ""
                if malformed_logical_key:
                    denial_reason = "malformed_request"
                elif request.runtime_session_id != self._runtime_session_id:
                    denial_reason = "runtime_session_mismatch"
                elif (
                    not parent_authorized
                    if effect.parent_operation_id is not None
                    else agent_id_sha256
                    != manifest.selected_agent.agent_id_sha256
                ):
                    denial_reason = "selected_agent_mismatch"
                elif (
                    effect.effect_class == "shell"
                    and effect.target_identity == "strict_isolation_unbound"
                ):
                    denial_reason = "shell_isolation_unbound"
                elif (
                    effect.adapter_kind == "native_file"
                    and not _is_sha256(effect.isolation_binding_sha256)
                    and not effect.preflight_denial_reason
                ):
                    denial_reason = "file_target_unauthorized"
                elif request.permit.tool_id_sha256 != _sha256_json(
                    "probos.effect-tool-id.v1", effect.tool_id
                ):
                    denial_reason = "tool_binding_mismatch"
                elif grant is None:
                    denial_reason = "grant_unavailable"
                elif not self._policy_allows(effect.effect_class):
                    denial_reason = "policy_refused"
                if denial_reason:
                    await db.execute(
                        "INSERT INTO effect_attempts VALUES "
                        "(?,?,1,NULL,NULL,'denied',?,NULL,NULL,?,'','')",
                        (attempt_id, operation_id, denial_reason, now),
                    )
                    await db.execute(
                        "UPDATE effect_operations SET state='denied',reason_code=?,"
                        "updated_at_ms=? WHERE operation_id=?",
                        (denial_reason, now, operation_id),
                    )
                    await self._insert_effect_transition(
                        db, operation_id, attempt_id, "pending", "denied",
                        denial_reason, now,
                    )
                    await db.commit()
                    return EffectReserveDecision(
                        operation_id, attempt_id, "denied", denial_reason,
                        None, "denied",
                    )
                permit = replace(request.permit, generation=self._generation)
                await self._insert_effect_attempt(
                    db, permit, 1, grant, request.lease_seconds, now
                )
                await db.execute(
                    "UPDATE effect_operations SET state='ready',"
                    "reason_code='intent_committed',updated_at_ms=? "
                    "WHERE operation_id=?",
                    (now, operation_id),
                )
                await self._insert_effect_transition(
                    db, operation_id, attempt_id, "pending", "ready",
                    "intent_committed", now,
                )
                await db.commit()
                return EffectReserveDecision(
                    operation_id, attempt_id, "ready", "intent_committed",
                    permit, "ready",
                )
            except asyncio.CancelledError:
                await self._rollback_or_disable(db)
                raise
            except (StaleGrantError, WitnessSchemaError):
                await self._rollback_or_disable(db)
                raise
            except Exception as exc:
                await self._rollback_or_disable(db)
                raise WitnessUnavailableError(
                    "effect intent could not commit"
                ) from exc

    async def _active_effect_grant(
        self, db: DatabaseConnection, manifest: ExecutionManifest
    ) -> tuple[str, str] | None:
        row = await self._transactions.fetchone(
            db,
            "SELECT grant_id,attempt_id FROM execution_grants "
            "WHERE manifest_id=? AND generation=? "
            "AND runtime_session_sha256=? AND state='active' "
            "ORDER BY issued_at_ms DESC LIMIT 1",
            (
                manifest.manifest_id,
                self._generation,
                self._runtime_session_sha256,
            ),
        )
        if row is None:
            return None
        return str(row[0]), str(row[1])

    async def _insert_effect_attempt(
        self,
        db: DatabaseConnection,
        permit: EffectPermit,
        ordinal: int,
        grant: tuple[str, str],
        lease_seconds: int,
        now: int,
    ) -> None:
        await db.execute(
            "INSERT INTO effect_attempts VALUES "
            "(?,?,?,?,?,'intent_committed','intent_committed',?,NULL,NULL,'','')",
            (
                permit.attempt_id,
                permit.operation_id,
                ordinal,
                grant[1],
                grant[0],
                now + lease_seconds * 1000,
            ),
        )

    async def _insert_effect_transition(
        self,
        db: DatabaseConnection,
        operation_id: str,
        attempt_id: str | None,
        from_state: str,
        to_state: str,
        reason_code: str,
        now: int,
    ) -> None:
        await db.execute(
            "INSERT INTO effect_transitions "
            "(operation_id,attempt_id,from_state,to_state,reason_code,recorded_at_ms) "
            "VALUES (?,?,?,?,?,?)",
            (operation_id, attempt_id, from_state, to_state, reason_code, now),
        )


class _EffectTransitionMixin:
    """Effect start, terminal transition, reconciliation, recovery, and query."""

    async def mark_effect_started(self, permit: EffectPermit) -> None:
        async with self._lock:
            db = self._require_db()
            now = _now_ms()
            try:
                await db.execute("BEGIN IMMEDIATE")
                row = await self._transactions.fetchone(
                    db,
                    "SELECT o.state,o.generation,a.state,a.grant_id "
                    "FROM effect_operations o JOIN effect_attempts a "
                    "ON a.operation_id=o.operation_id "
                    "WHERE o.operation_id=? AND a.attempt_id=?",
                    (permit.operation_id, permit.attempt_id),
                )
                if (
                    row is None
                    or str(row[0]) != "ready"
                    or int(row[1]) != self._generation
                    or permit.generation != self._generation
                    or str(row[2]) != "intent_committed"
                ):
                    raise StaleGrantError("effect permit is stale or already consumed")
                grant = await self._transactions.fetchone(
                    db,
                    "SELECT state,generation FROM execution_grants WHERE grant_id=?",
                    (str(row[3]),),
                )
                if (
                    grant is None
                    or str(grant[0]) != "active"
                    or int(grant[1]) != self._generation
                ):
                    raise StaleGrantError("effect grant is no longer active")
                attempt_update = await db.execute(
                    "UPDATE effect_attempts SET state='running',"
                    "reason_code='consumer_started',started_at_ms=? "
                    "WHERE attempt_id=? AND state='intent_committed'",
                    (now, permit.attempt_id),
                )
                operation_update = await db.execute(
                    "UPDATE effect_operations SET state='running',"
                    "reason_code='consumer_started',updated_at_ms=? "
                    "WHERE operation_id=? AND state='ready'",
                    (now, permit.operation_id),
                )
                if attempt_update.rowcount != 1 or operation_update.rowcount != 1:
                    raise StaleGrantError("effect permit compare-and-set failed")
                await self._insert_effect_transition(
                    db, permit.operation_id, permit.attempt_id,
                    "ready", "running", "consumer_started", now,
                )
                await db.commit()
            except asyncio.CancelledError:
                await self._rollback_or_disable(db)
                raise
            except StaleGrantError:
                await self._rollback_or_disable(db)
                raise
            except Exception as exc:
                await self._rollback_or_disable(db)
                raise WitnessUnavailableError(
                    "effect start could not commit"
                ) from exc

    async def finish_effect(
        self, request: EffectFinishRequest
    ) -> EffectOperationView:
        if _REASON_CODE_RE.fullmatch(request.reason_code) is None:
            raise ValueError("reason_code must use bounded stable-code syntax")
        if request.result_sha256 and not _is_sha256(request.result_sha256):
            raise ValueError("result_sha256 must be empty or SHA-256")
        async with self._lock:
            db = self._require_db()
            now = _now_ms()
            try:
                await db.execute("BEGIN IMMEDIATE")
                row = await self._transactions.fetchone(
                    db,
                    "SELECT o.state,a.state FROM effect_operations o "
                    "JOIN effect_attempts a ON a.operation_id=o.operation_id "
                    "WHERE o.operation_id=? AND a.attempt_id=?",
                    (request.operation_id, request.attempt_id),
                )
                if row is None:
                    raise StaleGrantError("effect attempt is unavailable")
                operation_state = str(row[0])
                attempt_state = str(row[1])
                valid_finish = (
                    operation_state == "running"
                    and attempt_state == "running"
                    and request.outcome in {"result", "failed", "unknown"}
                ) or (
                    request.outcome in {"cancelled", "denied", "failed"}
                    and operation_state == "ready"
                    and attempt_state == "intent_committed"
                )
                if not valid_finish:
                    raise StaleGrantError("effect finish compare-and-set failed")
                await db.execute(
                    "UPDATE effect_attempts SET state=?,reason_code=?,"
                    "finished_at_ms=?,result_sha256=? WHERE attempt_id=?",
                    (
                        request.outcome, request.reason_code, now,
                        request.result_sha256, request.attempt_id,
                    ),
                )
                await db.execute(
                    "UPDATE effect_operations SET state=?,reason_code=?,"
                    "result_sha256=?,updated_at_ms=? WHERE operation_id=?",
                    (
                        request.outcome, request.reason_code,
                        request.result_sha256, now, request.operation_id,
                    ),
                )
                await self._insert_effect_transition(
                    db, request.operation_id, request.attempt_id,
                    operation_state, request.outcome, request.reason_code, now,
                )
                await db.execute(
                    "UPDATE effect_delegation_bindings SET state='closed',"
                    "closed_at_ms=? WHERE parent_operation_id=? "
                    "AND parent_attempt_id=? AND state='active'",
                    (now, request.operation_id, request.attempt_id),
                )
                await db.commit()
            except asyncio.CancelledError:
                await self._rollback_or_disable(db)
                raise
            except StaleGrantError:
                await self._rollback_or_disable(db)
                raise
            except Exception as exc:
                await self._rollback_or_disable(db)
                raise WitnessUnavailableError(
                    "effect outcome could not commit"
                ) from exc
        operations = await self.query_effect_operations(request.operation_id)
        if len(operations) != 1:
            raise WitnessUnavailableError("effect outcome postcondition is missing")
        return operations[0]

    async def reconcile_effect(
        self, evidence: ReconciliationEvidence, *, receipt_sha256: str
    ) -> EffectOperationView:
        if receipt_sha256 and not _is_sha256(receipt_sha256):
            raise ValueError("receipt_sha256 must be empty or SHA-256")
        next_state = {
            "applied": "result",
            "not_applied": "ready",
            "failed": "blocked" if not receipt_sha256 else "failed",
        }[evidence.observed]
        reason = {
            "applied": "receipt_applied",
            "not_applied": "receipt_not_applied",
            "failed": "reconciliation_unavailable" if not receipt_sha256 else "receipt_failed",
        }[evidence.observed]
        async with self._lock:
            db = self._require_db()
            now = _now_ms()
            try:
                await db.execute("BEGIN IMMEDIATE")
                row = await self._transactions.fetchone(
                    db,
                    "SELECT state FROM effect_operations WHERE operation_id=?",
                    (evidence.operation_id,),
                )
                if row is None or str(row[0]) != "unknown":
                    raise StaleGrantError("only unknown effects can reconcile")
                await db.execute(
                    "UPDATE effect_operations SET state=?,reason_code=?,"
                    "receipt_sha256=?,updated_at_ms=? WHERE operation_id=?",
                    (
                        next_state, reason, receipt_sha256, now,
                        evidence.operation_id,
                    ),
                )
                await self._insert_effect_transition(
                    db, evidence.operation_id, None, "unknown",
                    next_state, reason, now,
                )
                await db.commit()
            except asyncio.CancelledError:
                await self._rollback_or_disable(db)
                raise
            except StaleGrantError:
                await self._rollback_or_disable(db)
                raise
            except Exception as exc:
                await self._rollback_or_disable(db)
                raise WitnessUnavailableError(
                    "effect reconciliation could not commit"
                ) from exc
        operations = await self.query_effect_operations(evidence.operation_id)
        return operations[0]

    async def recover_effects(self, *, now_ms: int | None = None) -> int:
        return await self._recover_effects(now_ms=now_ms, shutdown=False)

    async def shutdown_effects(self) -> int:
        return await self._recover_effects(now_ms=_now_ms(), shutdown=True)

    async def _recover_effects(
        self, *, now_ms: int | None, shutdown: bool
    ) -> int:
        async with self._lock:
            db = self._require_db()
            now = _now_ms() if now_ms is None else now_ms
            recovered = 0
            try:
                await db.execute("BEGIN IMMEDIATE")
                cursor = await db.execute(
                    "SELECT operation_id,state,generation FROM effect_operations "
                    "WHERE state IN ('pending','ready','running')"
                )
                for row in await cursor.fetchall():
                    operation_id = str(row[0])
                    state = str(row[1])
                    generation = int(row[2])
                    attempt = await self._transactions.fetchone(
                        db,
                        "SELECT attempt_id,state,lease_expires_at_ms "
                        "FROM effect_attempts WHERE operation_id=? "
                        "ORDER BY ordinal DESC LIMIT 1",
                        (operation_id,),
                    )
                    if attempt is None:
                        continue
                    lease = (
                        int(attempt[2]) if attempt[2] is not None else None
                    )
                    if state == "running" and (
                        shutdown
                        or
                        generation < self._generation
                        or lease is None
                        or lease <= now
                    ):
                        next_state, reason = "unknown", "issuer_interrupted_after_effect"
                    elif state in {"pending", "ready"} and (
                        shutdown or generation < self._generation
                    ):
                        next_state, reason = "cancelled", "issuer_interrupted_before_effect"
                    else:
                        continue
                    await db.execute(
                        "UPDATE effect_operations SET state=?,reason_code=?,"
                        "updated_at_ms=? WHERE operation_id=?",
                        (next_state, reason, now, operation_id),
                    )
                    await db.execute(
                        "UPDATE effect_attempts SET state=?,reason_code=?,"
                        "finished_at_ms=? WHERE attempt_id=?",
                        (next_state, reason, now, str(attempt[0])),
                    )
                    await self._insert_effect_transition(
                        db, operation_id, str(attempt[0]), state,
                        next_state, reason, now,
                    )
                    recovered += 1
                await db.commit()
            except asyncio.CancelledError:
                await self._rollback_or_disable(db)
                raise
            except Exception as exc:
                await self._rollback_or_disable(db)
                raise WitnessUnavailableError(
                    "effect recovery could not commit"
                ) from exc
            return recovered

    async def query_effect_operations(
        self, operation_id: str | None = None
    ) -> tuple[EffectOperationView, ...]:
        async with self._lock:
            db = self._require_db()
            sql = (
                "SELECT operation_id,state,reason_code,effect_class,idempotency,"
                "generation,parent_operation_id,result_sha256,receipt_sha256,"
                "(SELECT COUNT(*) FROM effect_attempts a "
                "WHERE a.operation_id=o.operation_id),adapter_kind,"
                "continuation_binding_sha256,parent_attempt_id,child_run_sha256 "
                "FROM effect_operations o"
            )
            parameters: tuple[object, ...] = ()
            if operation_id is not None:
                sql += " WHERE operation_id=?"
                parameters = (operation_id,)
            sql += " ORDER BY created_at_ms,operation_id"
            cursor = await db.execute(sql, parameters)
            return tuple(
                EffectOperationView(
                    operation_id=str(row[0]),
                    state=str(row[1]),
                    reason_code=str(row[2]),
                    effect_class=str(row[3]),
                    idempotency=str(row[4]),
                    generation=int(row[5]),
                    parent_operation_id=(
                        str(row[6]) if row[6] is not None else None
                    ),
                    result_sha256=str(row[7]),
                    receipt_sha256=str(row[8]),
                    attempt_count=int(row[9]),
                    adapter_kind=str(row[10]),
                    continuation_binding_sha256=str(row[11]),
                    parent_attempt_id=(
                        str(row[12]) if row[12] is not None else None
                    ),
                    child_run_sha256=str(row[13]),
                )
                for row in await cursor.fetchall()
            )

    async def query_effect_attempts(
        self, operation_id: str
    ) -> tuple[EffectAttemptView, ...]:
        async with self._lock:
            db = self._require_db()
            cursor = await db.execute(
                "SELECT attempt_id,operation_id,ordinal,state,reason_code,"
                "lease_expires_at_ms,started_at_ms,finished_at_ms,"
                "result_sha256,receipt_sha256 FROM effect_attempts "
                "WHERE operation_id=? ORDER BY ordinal",
                (operation_id,),
            )
            return tuple(
                EffectAttemptView(
                    attempt_id=str(row[0]),
                    operation_id=str(row[1]),
                    ordinal=int(row[2]),
                    state=str(row[3]),
                    reason_code=str(row[4]),
                    lease_expires_at_ms=(
                        int(row[5]) if row[5] is not None else None
                    ),
                    started_at_ms=(
                        int(row[6]) if row[6] is not None else None
                    ),
                    finished_at_ms=(
                        int(row[7]) if row[7] is not None else None
                    ),
                    result_sha256=str(row[8]),
                    receipt_sha256=str(row[9]),
                )
                for row in await cursor.fetchall()
            )


class ProtectedExecutionAuthority(
    _ProtectedExecutionAuthorityCore,
    _EffectReservationMixin,
    _EffectTransitionMixin,
):
    """Runtime-owned strict issuer and governed-effect witness."""
