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
from dataclasses import asdict, dataclass
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol, TypeAlias

from probos.protocols import ConnectionFactory, DatabaseConnection
from probos.storage.sqlite_factory import default_factory

logger = logging.getLogger(__name__)

EXECUTION_MANIFEST_VERSION = 1
EXECUTION_WITNESS_SCHEMA_VERSION = 1
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
        ("schema_version", 1, 1, False),
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
}

_SCHEMA = """
CREATE TABLE authority_meta(
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    schema_version INTEGER NOT NULL CHECK(schema_version=1),
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
        git_environment = os.environ.copy()
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
                    "INSERT INTO authority_meta VALUES (1,1,?,?,?,?)",
                    (str(uuid.uuid4()), 0, "", _now_ms()),
                )
                await db.execute("PRAGMA user_version=1")
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
        elif version != EXECUTION_WITNESS_SCHEMA_VERSION:
            raise WitnessSchemaError("unsupported protected witness schema version")
        await self._validate(db)

    async def _validate(self, db: DatabaseConnection) -> None:
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


class ProtectedExecutionAuthority:
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
