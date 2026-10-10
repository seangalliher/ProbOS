from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import multiprocessing
import os
import sqlite3
import stat
import subprocess
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from probos.config import ProtectedExecutionConfig, SystemConfig
from probos.execution.authority import (
    REQUIRED_ENFORCEMENT_KINDS,
    AdmissionRequest,
    EnforcementSourceSnapshot,
    ExecutionGrant,
    IsolationBoundaryError,
    ManifestPublicationRequest,
    ManifestValidationError,
    ProtectedExecutionAuthority,
    StaleGrantError,
    WitnessSchemaError,
    WitnessUnavailableError,
)
from probos.storage.registry import load_default_store_registry
from probos.storage.sqlite_factory import default_factory


def _digest(domain: str, content: bytes) -> str:
    value = hashlib.sha256()
    value.update(domain.encode("ascii"))
    value.update(b"\x00")
    value.update(content)
    return value.hexdigest()


def _json_digest(domain: str, value: object) -> str:
    return _digest(
        domain,
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8"),
    )


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_repository(root: Path, source_text: str = "agent source") -> Path:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "authority@example.invalid")
    _git(root, "config", "user.name", "Authority Test")
    source = root / "agent.py"
    source.write_text(source_text, encoding="utf-8")
    _git(root, "add", "agent.py")
    _git(root, "commit", "-q", "-m", "seed")
    return source


def _make_layout(
    tmp_path: Path,
    *,
    policy: dict[str, object] | None = None,
    source_text: str = "agent source",
) -> dict[str, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    repository = tmp_path / "repository"
    selected_source = _make_repository(repository, source_text)
    protected = tmp_path / "protected"
    protected.mkdir()
    issuer = protected / "authority.py"
    issuer.write_text("issuer", encoding="utf-8")
    policy_path = protected / "policy.json"
    policy_payload = policy or {
        "operations": [
            {"operation_kind": "read", "handler": "read_handler", "allow": True},
            {"operation_kind": "write", "handler": "write_handler", "allow": False},
        ]
    }
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")
    sources: list[EnforcementSourceSnapshot] = []
    paths: list[Path] = []
    for kind in REQUIRED_ENFORCEMENT_KINDS:
        path = protected / f"{kind}.metadata"
        content = f"{kind}:metadata".encode()
        path.write_bytes(content)
        paths.append(path)
        sources.append(
            EnforcementSourceSnapshot(
                kind=kind,
                name=f"{kind}-effective",
                sha256=_digest(f"probos.enforcement-source.{kind}.v1", content),
                version="1",
                item_count=1,
            )
        )
    return {
        "repository": repository,
        "selected_source": selected_source,
        "protected": protected,
        "issuer": issuer,
        "policy": policy_path,
        "sources": tuple(sources),
        "source_paths": tuple(paths),
        "db": tmp_path / "execution_authority.db",
        "worker": tmp_path / "worker",
    }


def _authority(
    layout: dict[str, Any],
    *,
    session: str = "runtime-session",
    timeout_ms: int = 5000,
    connection_factory: Any = None,
) -> ProtectedExecutionAuthority:
    return ProtectedExecutionAuthority(
        db_path=layout["db"],
        runtime_session_id=session,
        witness_busy_timeout_ms=timeout_ms,
        protected_installation_root=layout["protected"],
        policy_path=layout["policy"],
        worker_write_roots=(layout["worker"],),
        connection_factory=connection_factory,
        issuer_module_path=layout["issuer"],
    )


def _publication(
    layout: dict[str, Any],
    **overrides: Any,
) -> ManifestPublicationRequest:
    values = {
        "repository_root": layout["repository"],
        "selected_agent_id": "selected-agent-canary",
        "selected_agent_type": "Builder",
        "selected_agent_source_path": layout["selected_source"],
        "enforcement_sources": layout["sources"],
        "enforcement_source_paths": layout["source_paths"],
        "policy_path": layout["policy"],
        "protected_installation_root": layout["protected"],
        "worker_write_roots": (layout["worker"],),
    }
    values.update(overrides)
    return ManifestPublicationRequest(**values)


def _admission(
    manifest: Any,
    *,
    session: object = "runtime-session",
    operation: object = "read",
    target: object = "target",
    shape: object | None = None,
) -> AdmissionRequest:
    return AdmissionRequest(
        manifest_id=manifest.manifest_id,
        generation=manifest.generation,
        runtime_session_id=session,
        operation_kind=operation,
        target_identity=target,
        parameter_shape_sha256=shape or hashlib.sha256(b"shape").hexdigest(),
    )


async def _started_authority(
    tmp_path: Path,
    **layout_options: Any,
) -> tuple[dict[str, Any], ProtectedExecutionAuthority]:
    layout = _make_layout(tmp_path, **layout_options)
    authority = _authority(layout)
    await authority.start()
    return layout, authority


def _child_positive(layout_values: dict[str, str], queue: Any) -> None:
    async def run() -> None:
        layout = _child_layout(layout_values)
        authority = _authority(layout, session="child-session")
        await authority.start()
        manifest = await authority.publish_manifest(_publication(layout))
        decision = await authority.admit(_admission(manifest, session="child-session"))
        assert decision.grant is not None
        with sqlite3.connect(layout["db"]) as reader:
            terminal = reader.execute(
                "SELECT outcome FROM admission_attempts WHERE attempt_id=?",
                (decision.attempt_id,),
            ).fetchone()
            grant = reader.execute(
                "SELECT state FROM execution_grants WHERE grant_id=?",
                (decision.grant.grant_id,),
            ).fetchone()
        assert terminal == ("admitted",)
        assert grant == ("active",)
        await authority.validate_grant(decision.grant)
        marker = Path(layout_values["marker"])
        marker.write_text(str(time.time_ns()), encoding="utf-8")
        queue.put((asdict(decision.grant), asdict(manifest.host)))
        await authority.stop()

    asyncio.run(run())


def _child_hard_kill(
    layout_values: dict[str, str],
    queue: Any,
    release: Any,
) -> None:
    async def run() -> None:
        layout = _child_layout(layout_values)
        authority = _authority(layout, session="kill-session")
        await authority.start()
        manifest = await authority.publish_manifest(_publication(layout))
        decision = await authority.admit(_admission(manifest, session="kill-session"))
        assert decision.grant is not None
        queue.put(asdict(decision.grant))
        release.wait(30)
        await authority.validate_grant(decision.grant)
        Path(layout_values["marker"]).write_text("effect", encoding="utf-8")

    asyncio.run(run())


def _child_stale_effect(
    layout_values: dict[str, str],
    queue: Any,
    release: Any,
) -> None:
    async def run() -> None:
        layout = _child_layout(layout_values)
        authority = _authority(layout, session="stale-session")
        await authority.start()
        manifest = await authority.publish_manifest(_publication(layout))
        decision = await authority.admit(_admission(manifest, session="stale-session"))
        assert decision.grant is not None
        queue.put(asdict(decision.grant))
        release.wait(30)
        try:
            await authority.validate_grant(decision.grant)
        except StaleGrantError:
            queue.put("stale")
        else:
            Path(layout_values["marker"]).write_text("effect", encoding="utf-8")
            queue.put("validated")
        await authority.stop()

    asyncio.run(run())


def _child_layout(values: dict[str, str]) -> dict[str, Any]:
    protected = Path(values["protected"])
    sources = []
    paths = []
    for kind in REQUIRED_ENFORCEMENT_KINDS:
        path = protected / f"{kind}.metadata"
        content = path.read_bytes()
        paths.append(path)
        sources.append(
            EnforcementSourceSnapshot(
                kind=kind,
                name=f"{kind}-effective",
                sha256=_digest(f"probos.enforcement-source.{kind}.v1", content),
                version="1",
                item_count=1,
            )
        )
    return {
        "repository": Path(values["repository"]),
        "selected_source": Path(values["selected_source"]),
        "protected": protected,
        "issuer": Path(values["issuer"]),
        "policy": Path(values["policy"]),
        "sources": tuple(sources),
        "source_paths": tuple(paths),
        "db": Path(values["db"]),
        "worker": Path(values["worker"]),
    }


def _child_values(layout: dict[str, Any], marker: Path) -> dict[str, str]:
    return {
        key: str(layout[key])
        for key in (
            "repository",
            "selected_source",
            "protected",
            "issuer",
            "policy",
            "db",
            "worker",
        )
    } | {"marker": str(marker)}


@pytest.mark.asyncio
async def test_start_fresh_database_creates_schema_v1(tmp_path: Path) -> None:
    layout, authority = await _started_authority(tmp_path)
    await authority.stop()
    with sqlite3.connect(layout["db"]) as db:
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        indexes = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        version = db.execute("PRAGMA user_version").fetchone()[0]
        journal = db.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = db.execute("PRAGMA synchronous").fetchone()[0]
        host = db.execute(
            "SELECT host_instance_id FROM authority_meta"
        ).fetchone()[0]
    assert {
        "authority_meta",
        "execution_manifests",
        "manifest_sources",
        "admission_attempts",
        "execution_grants",
    }.issubset(tables)
    assert {
        "idx_admission_attempts_outcome_requested",
        "idx_execution_grants_generation_state",
    }.issubset(indexes)
    assert (version, journal, synchronous) == (1, "wal", 2)
    assert host


@pytest.mark.asyncio
async def test_start_version_zero_migrates_seeded_database(tmp_path: Path) -> None:
    layout = _make_layout(tmp_path)
    with sqlite3.connect(layout["db"]) as db:
        db.execute("CREATE TABLE seed(value TEXT)")
        db.execute("INSERT INTO seed VALUES ('preserved')")
    authority = _authority(layout)
    await authority.start()
    await authority.stop()
    with sqlite3.connect(layout["db"]) as db:
        assert db.execute("SELECT value FROM seed").fetchone() == ("preserved",)
        assert db.execute("PRAGMA user_version").fetchone() == (1,)


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["future", "column"])
async def test_start_future_or_drifted_schema_fails_closed(
    tmp_path: Path, drift: str
) -> None:
    layout = _make_layout(tmp_path)
    if drift == "future":
        with sqlite3.connect(layout["db"]) as db:
            db.execute("PRAGMA user_version=2")
    else:
        authority = _authority(layout)
        await authority.start()
        await authority.stop()
        with sqlite3.connect(layout["db"]) as db:
            db.execute("ALTER TABLE authority_meta RENAME TO authority_meta_old")
            db.execute(
                "CREATE TABLE authority_meta(singleton INTEGER PRIMARY KEY, "
                "schema_version INTEGER, host_instance_id TEXT)"
            )
            db.execute(
                "INSERT INTO authority_meta VALUES (1,1,'preserved-host')"
            )
            db.execute("DROP TABLE authority_meta_old")
    with pytest.raises(WitnessSchemaError):
        await _authority(layout).start()
    with sqlite3.connect(layout["db"]) as db:
        if drift == "future":
            assert db.execute("PRAGMA user_version").fetchone() == (2,)
        else:
            assert db.execute(
                "SELECT host_instance_id FROM authority_meta"
            ).fetchone() == ("preserved-host",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table", "old", "new"),
    [
        (
            "admission_attempts",
            "operation_kind TEXT NOT NULL",
            "operation_kind BLOB",
        ),
        (
            "admission_attempts",
            "outcome TEXT NOT NULL CHECK(outcome IN "
            "('pending','admitted','denied','rejected','failed'))",
            "outcome TEXT NOT NULL",
        ),
        (
            "manifest_sources",
            "manifest_id TEXT NOT NULL REFERENCES execution_manifests(manifest_id)",
            "manifest_id TEXT NOT NULL",
        ),
        (
            "admission_attempts",
            "'pending','admitted','denied','rejected','failed'",
            "'PENDING','admitted','denied','rejected','failed'",
        ),
        (
            "admission_attempts",
            "'pending','admitted','denied','rejected','failed'",
            "'pend ing','admitted','denied','rejected','failed'",
        ),
    ],
)
async def test_start_same_name_incompatible_table_definition_fails_closed(
    tmp_path: Path, table: str, old: str, new: str
) -> None:
    layout, authority = await _started_authority(tmp_path)
    await authority.stop()
    with sqlite3.connect(layout["db"]) as db:
        sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()[0]
        assert old in sql
        db.execute("PRAGMA writable_schema=ON")
        db.execute(
            "UPDATE sqlite_master SET sql=? WHERE type='table' AND name=?",
            (sql.replace(old, new), table),
        )
        db.execute("PRAGMA writable_schema=OFF")
    with pytest.raises(WitnessSchemaError):
        await _authority(layout).start()


@pytest.mark.asyncio
async def test_start_same_name_incompatible_index_definition_fails_closed(
    tmp_path: Path,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    await authority.stop()
    with sqlite3.connect(layout["db"]) as db:
        db.execute("DROP INDEX idx_admission_attempts_outcome_requested")
        db.execute(
            "CREATE INDEX idx_admission_attempts_outcome_requested "
            "ON admission_attempts(reason_code, requested_at_ms)"
        )
    with pytest.raises(WitnessSchemaError):
        await _authority(layout).start()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "table",
    [
        "authority_meta",
        "execution_manifests",
        "manifest_sources",
        "admission_attempts",
        "execution_grants",
    ],
)
async def test_start_trigger_on_witness_table_fails_closed(
    tmp_path: Path,
    table: str,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    await authority.stop()
    with sqlite3.connect(layout["db"]) as db:
        db.execute(
            f"CREATE TRIGGER injected_{table} BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(IGNORE); END"
        )

    candidate = _authority(layout)
    try:
        with pytest.raises(WitnessSchemaError):
            await candidate.start()
    finally:
        await candidate.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("table", "column", "value"),
    [
        ("authority_meta", "current_generation", 1.5),
        ("authority_meta", "updated_at_ms", "not-an-integer"),
        ("authority_meta", "current_generation", -1),
        ("authority_meta", "current_generation", 2**63 - 1),
        ("execution_manifests", "generation", 1.5),
        ("execution_manifests", "created_at_ms", "not-an-integer"),
        ("execution_manifests", "os_pid", -1),
        ("execution_manifests", "repository_dirty", 2),
        ("manifest_sources", "item_count", 1.5),
        ("manifest_sources", "item_count", "not-an-integer"),
        ("manifest_sources", "item_count", -1),
        ("admission_attempts", "requested_at_ms", 1.5),
        ("admission_attempts", "resolved_at_ms", "not-an-integer"),
        ("admission_attempts", "presented_generation", -1),
        ("admission_attempts", "admitted_at_ms", 1.5),
        ("admission_attempts", "failed_at_ms", "not-an-integer"),
        ("execution_grants", "generation", 1.5),
        ("execution_grants", "issued_at_ms", "not-an-integer"),
        ("execution_grants", "revoked_at_ms", -1),
    ],
)
async def test_start_malformed_persisted_integer_fails_closed(
    tmp_path: Path,
    table: str,
    column: str,
    value: object,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    manifest = await authority.publish_manifest(_publication(layout))
    admitted = await authority.admit(_admission(manifest))
    assert admitted.grant is not None
    await authority.stop()

    with sqlite3.connect(layout["db"]) as db:
        db.execute("PRAGMA ignore_check_constraints=ON")
        db.execute(f"UPDATE {table} SET {column}=?", (value,))
        persisted = db.execute(
            f"SELECT typeof({column}),{column} FROM {table} LIMIT 1"
        ).fetchone()
    if isinstance(value, float):
        assert persisted == ("real", value)
    elif isinstance(value, str):
        assert persisted == ("text", value)
    else:
        assert persisted == ("integer", value)

    candidate = _authority(layout)
    try:
        with pytest.raises(WitnessSchemaError):
            await candidate.start()
    finally:
        await candidate.stop()


@pytest.mark.asyncio
async def test_publish_complete_manifest_is_deterministic_and_bound(
    tmp_path: Path,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    manifest = await authority.publish_manifest(_publication(layout))
    repeated = await authority.publish_manifest(_publication(layout))
    assert repeated is manifest
    assert manifest.version == 1
    assert manifest.repository.head_sha == _git(layout["repository"], "rev-parse", "HEAD")
    assert manifest.host.os_pid == os.getpid()
    assert manifest.host.runtime_session_sha256 == _json_digest(
        "probos.runtime-session.v1", "runtime-session"
    )
    assert manifest.selected_agent.source_relative_path == "agent.py"
    assert len(manifest.enforcement_sources) == 7
    assert len(manifest.manifest_sha256) == 64
    await authority.stop()


@pytest.mark.asyncio
async def test_publish_repository_binding_never_executes_configured_fsmonitor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    repository = layout["repository"]
    expected_head = _git(repository, "rev-parse", "HEAD")
    expected_tree = _digest(
        "probos.repository-tracked-tree.v1",
        subprocess.run(
            ["git", "-C", str(repository), "ls-files", "-s"],
            check=True,
            capture_output=True,
        ).stdout,
    )
    callback = repository / ".git" / "fsmonitor-canary"
    canary = repository / ".git" / "fsmonitor-executed"
    callback.write_text(
        "#!/bin/sh\necho invoked > .git/fsmonitor-executed\nexit 1\n",
        encoding="utf-8",
    )
    callback.chmod(callback.stat().st_mode | stat.S_IXUSR)
    _git(repository, "config", "core.fsmonitor", callback.as_posix())
    callback_environment = os.environ.copy()
    for name in tuple(callback_environment):
        if name.startswith("GIT_CONFIG_"):
            del callback_environment[name]
    subprocess.run(
        ["git", "-C", str(repository), "status", "--porcelain"],
        check=True,
        capture_output=True,
        env=callback_environment,
    )
    assert canary.exists()
    canary.unlink()
    for name in tuple(os.environ):
        if name.startswith("GIT_CONFIG_"):
            monkeypatch.delenv(name)

    try:
        manifest = await authority.publish_manifest(_publication(layout))

        assert not canary.exists()
        assert manifest.repository.head_sha == expected_head
        assert manifest.repository.tracked_tree_sha256 == expected_tree
        assert manifest.repository.dirty is False
    finally:
        await authority.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "item_count",
    [True, 1.0, float("inf"), -1, 2**63],
)
async def test_publish_invalid_enforcement_item_count_rejected_before_persistence(
    tmp_path: Path,
    item_count: object,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    sources = (
        replace(layout["sources"][0], item_count=item_count),
        *layout["sources"][1:],
    )

    try:
        with pytest.raises(ManifestValidationError):
            await authority.publish_manifest(
                _publication(layout, enforcement_sources=sources)
            )

        with sqlite3.connect(layout["db"]) as db:
            assert db.execute(
                "SELECT COUNT(*) FROM execution_manifests"
            ).fetchone() == (0,)
            assert db.execute(
                "SELECT COUNT(*) FROM manifest_sources"
            ).fetchone() == (0,)
    finally:
        await authority.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("item_count", [0, 2**63 - 1])
async def test_publish_bounded_integer_enforcement_item_count_persists(
    tmp_path: Path,
    item_count: int,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    sources = (
        replace(layout["sources"][0], item_count=item_count),
        *layout["sources"][1:],
    )

    manifest = await authority.publish_manifest(
        _publication(layout, enforcement_sources=sources)
    )

    assert manifest.enforcement_sources[0].item_count == item_count
    with sqlite3.connect(layout["db"]) as db:
        assert db.execute(
            "SELECT item_count FROM manifest_sources "
            "WHERE manifest_id=? AND kind=?",
            (manifest.manifest_id, sources[0].kind),
        ).fetchone() == (item_count,)
    await authority.stop()


@pytest.mark.asyncio
async def test_publish_missing_policy_leaves_no_manifest_or_grant(
    tmp_path: Path,
) -> None:
    layout = _make_layout(tmp_path)
    authority = _authority(layout)
    await authority.start()
    layout["policy"].unlink()
    with pytest.raises(ManifestValidationError):
        await authority.publish_manifest(_publication(layout))
    with sqlite3.connect(layout["db"]) as db:
        assert db.execute("SELECT count(*) FROM execution_manifests").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM execution_grants").fetchone() == (0,)
    await authority.stop()


@pytest.mark.asyncio
async def test_publish_duplicate_operation_or_handler_rejects(
    tmp_path: Path,
) -> None:
    layout = _make_layout(
        tmp_path,
        policy={
            "operations": [
                {"operation_kind": "read", "handler": "shared", "allow": True},
                {"operation_kind": "write", "handler": "shared", "allow": True},
            ]
        },
    )
    authority = _authority(layout)
    await authority.start()
    with pytest.raises(ManifestValidationError):
        await authority.publish_manifest(_publication(layout))
    await authority.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata_field",
    ["selected_agent_type", "source_name", "source_version"],
)
async def test_publish_content_bearing_identifier_metadata_rejects_before_persistence(
    tmp_path: Path,
    metadata_field: str,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    overrides: dict[str, object] = {}
    if metadata_field == "selected_agent_type":
        overrides["selected_agent_type"] = "Builder\nraw-content"
    else:
        source = layout["sources"][0]
        replacement = replace(
            source,
            name="source\nraw-content"
            if metadata_field == "source_name"
            else source.name,
            version="version\nraw-content"
            if metadata_field == "source_version"
            else source.version,
        )
        overrides["enforcement_sources"] = (
            replacement,
            *layout["sources"][1:],
        )

    with pytest.raises(ManifestValidationError):
        await authority.publish_manifest(_publication(layout, **overrides))

    with sqlite3.connect(layout["db"]) as db:
        assert db.execute("SELECT count(*) FROM execution_manifests").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM manifest_sources").fetchone() == (0,)
    await authority.stop()


@pytest.mark.asyncio
async def test_publish_policy_change_during_single_read_rejects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout, authority = await _started_authority(tmp_path)
    original_read_bytes = Path.read_bytes

    def _changing_read(path: Path) -> bytes:
        content = original_read_bytes(path)
        if path == layout["policy"]:
            path.write_bytes(content + b" ")
        return content

    monkeypatch.setattr(Path, "read_bytes", _changing_read)
    with pytest.raises(ManifestValidationError):
        await authority.publish_manifest(_publication(layout))
    await authority.stop()


@pytest.mark.asyncio
async def test_publish_policy_digest_and_rules_use_same_stable_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from probos.execution import authority as authority_module

    layout, authority = await _started_authority(tmp_path)
    original_policy = layout["policy"].read_bytes()
    original_read_stable_bytes = authority_module._read_stable_bytes

    def _change_after_stable_read(path: Path) -> bytes:
        content = original_read_stable_bytes(path)
        if path == layout["policy"]:
            path.write_text(
                json.dumps(
                    {
                        "operations": [
                            {
                                "operation_kind": "read",
                                "handler": "read_handler",
                                "allow": False,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
        return content

    monkeypatch.setattr(
        authority_module, "_read_stable_bytes", _change_after_stable_read
    )
    manifest = await authority.publish_manifest(_publication(layout))
    decision = await authority.admit(_admission(manifest))
    assert manifest.policy_sha256 == _digest(
        "probos.admission-policy.v1", original_policy
    )
    assert decision.outcome == "admitted"
    await authority.stop()


@pytest.mark.asyncio
async def test_publish_source_change_rotates_generation_and_revokes_grant(
    tmp_path: Path,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    first = await authority.publish_manifest(_publication(layout))
    decision = await authority.admit(_admission(first))
    assert decision.grant is not None
    layout["selected_source"].write_text("changed source", encoding="utf-8")
    second = await authority.publish_manifest(_publication(layout))
    assert second.generation == first.generation + 1
    with pytest.raises(StaleGrantError):
        await authority.validate_grant(decision.grant)
    with sqlite3.connect(layout["db"]) as db:
        assert db.execute(
            "SELECT state, revoked_reason FROM execution_grants"
        ).fetchone() == ("revoked", "manifest_rotated")
    await authority.stop()


@pytest.mark.asyncio
async def test_superseded_issuer_cannot_publish_admit_or_validate(
    tmp_path: Path,
) -> None:
    layout, first = await _started_authority(tmp_path)
    manifest = await first.publish_manifest(_publication(layout))
    decision = await first.admit(_admission(manifest))
    assert decision.grant is not None
    second = _authority(layout)
    await second.start()
    layout["selected_source"].write_text("superseded change", encoding="utf-8")
    with pytest.raises(StaleGrantError):
        await first.publish_manifest(_publication(layout))
    denied = await first.admit(_admission(manifest))
    assert (denied.outcome, denied.reason_code, denied.grant) == (
        "denied",
        "issuer_superseded",
        None,
    )
    with pytest.raises(StaleGrantError):
        await first.validate_grant(decision.grant)
    await second.stop()
    await first.stop()


@pytest.mark.asyncio
async def test_admit_stale_session_denies_and_grant_is_stale(
    tmp_path: Path,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    manifest = await authority.publish_manifest(_publication(layout))
    stale = await authority.admit(_admission(manifest, session="other-session"))
    assert (stale.outcome, stale.reason_code, stale.grant) == (
        "denied",
        "runtime_session_mismatch",
        None,
    )
    current = await authority.admit(_admission(manifest))
    assert current.grant is not None
    bad_grant = replace(current.grant, runtime_session_sha256="0" * 64)
    with pytest.raises(StaleGrantError):
        await authority.validate_grant(bad_grant)
    await authority.stop()


@pytest.mark.asyncio
async def test_restart_rotates_issuer_and_recovers_pending_attempt(
    tmp_path: Path,
) -> None:
    layout, first_authority = await _started_authority(tmp_path)
    manifest = await first_authority.publish_manifest(_publication(layout))
    decision = await first_authority.admit(_admission(manifest))
    assert decision.grant is not None
    await first_authority.stop()
    with sqlite3.connect(layout["db"]) as db:
        first_meta = db.execute(
            "SELECT host_instance_id,process_id,current_generation FROM authority_meta"
        ).fetchone()
        db.execute(
            "INSERT INTO admission_attempts VALUES "
            "('pending-crash',1,NULL,NULL,NULL,'h','op','t','p','pending','pending',NULL,NULL)"
        )
    second_authority = _authority(layout)
    await second_authority.start()
    with sqlite3.connect(layout["db"]) as db:
        second_meta = db.execute(
            "SELECT host_instance_id,process_id,current_generation FROM authority_meta"
        ).fetchone()
        recovered = db.execute(
            "SELECT outcome,reason_code FROM admission_attempts "
            "WHERE attempt_id='pending-crash'"
        ).fetchone()
        state = db.execute(
            "SELECT state FROM execution_grants WHERE grant_id=?",
            (decision.grant.grant_id,),
        ).fetchone()
    assert second_meta[0] == first_meta[0]
    assert second_meta[1] != first_meta[1]
    assert second_meta[2] == first_meta[2] + 1
    assert recovered == ("failed", "issuer_interrupted")
    assert state == ("revoked",)
    await second_authority.stop()


@pytest.mark.asyncio
async def test_mark_start_failed_revalidates_rotation_inside_update_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    manifest = await authority.publish_manifest(_publication(layout))
    admitted = await authority.admit(_admission(manifest))
    assert admitted.grant is not None
    original_validate = authority.validate_grant
    rotated_evidence: dict[str, tuple[object, ...]] = {}

    async def _validate_then_rotate(grant: ExecutionGrant) -> None:
        await original_validate(grant)
        with sqlite3.connect(layout["db"]) as db:
            db.execute(
                "UPDATE authority_meta SET current_generation=current_generation+1, "
                "process_id='rotated-issuer' WHERE singleton=1"
            )
            db.execute(
                "UPDATE execution_grants SET state='revoked', revoked_at_ms=123, "
                "revoked_reason='issuer_restarted' WHERE grant_id=?",
                (grant.grant_id,),
            )
            rotated_evidence["attempt"] = db.execute(
                "SELECT * FROM admission_attempts WHERE attempt_id=?",
                (grant.attempt_id,),
            ).fetchone()
            rotated_evidence["grant"] = db.execute(
                "SELECT * FROM execution_grants WHERE grant_id=?",
                (grant.grant_id,),
            ).fetchone()

    monkeypatch.setattr(authority, "validate_grant", _validate_then_rotate)

    with pytest.raises(StaleGrantError):
        await authority.mark_start_failed(
            admitted.grant,
            reason_code="effect_start_failed",
        )

    with sqlite3.connect(layout["db"]) as db:
        attempt = db.execute(
            "SELECT * FROM admission_attempts WHERE attempt_id=?",
            (admitted.attempt_id,),
        ).fetchone()
        grant = db.execute(
            "SELECT * FROM execution_grants WHERE grant_id=?",
            (admitted.grant.grant_id,),
        ).fetchone()
    assert attempt == rotated_evidence["attempt"]
    assert grant == rotated_evidence["grant"]
    await authority.stop()


@pytest.mark.asyncio
async def test_admit_commit_is_visible_before_probe_effect(tmp_path: Path) -> None:
    layout, authority = await _started_authority(tmp_path)
    manifest = await authority.publish_manifest(_publication(layout))
    decision = await authority.admit(_admission(manifest))
    assert decision.grant is not None
    with sqlite3.connect(layout["db"]) as reader:
        assert reader.execute(
            "SELECT outcome FROM admission_attempts WHERE attempt_id=?",
            (decision.attempt_id,),
        ).fetchone() == ("admitted",)
        assert reader.execute(
            "SELECT state FROM execution_grants WHERE grant_id=?",
            (decision.grant.grant_id,),
        ).fetchone() == ("active",)
    marker = tmp_path / "effect.marker"
    marker.write_text("effect", encoding="utf-8")
    assert marker.exists()
    await authority.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("suppressed_write", ["grant_insert", "terminal_update"])
async def test_admit_suppressed_durable_postcondition_fails_closed(
    tmp_path: Path,
    suppressed_write: str,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    manifest = await authority.publish_manifest(_publication(layout))
    with sqlite3.connect(layout["db"]) as db:
        if suppressed_write == "grant_insert":
            db.execute(
                "CREATE TRIGGER suppress_grant_insert "
                "BEFORE INSERT ON execution_grants "
                "BEGIN SELECT RAISE(IGNORE); END"
            )
        else:
            db.execute(
                "CREATE TRIGGER suppress_terminal_update "
                "BEFORE UPDATE OF outcome ON admission_attempts "
                "WHEN OLD.outcome='pending' "
                "BEGIN SELECT RAISE(IGNORE); END"
            )

    with pytest.raises(WitnessUnavailableError):
        await authority.admit(_admission(manifest))
    with pytest.raises(WitnessUnavailableError):
        await authority.query_attempts()

    with sqlite3.connect(layout["db"]) as db:
        attempt = db.execute(
            "SELECT outcome FROM admission_attempts ORDER BY requested_at_ms DESC"
        ).fetchone()
        grants = db.execute("SELECT COUNT(*) FROM execution_grants").fetchone()
    assert attempt == (
        "admitted" if suppressed_write == "grant_insert" else "pending",
    )
    assert grants == (
        0 if suppressed_write == "grant_insert" else 1,
    )


class _CancellingStartConnection:
    def __init__(self) -> None:
        self.cancelled = False
        self.closed = False

    async def execute(
        self, sql: str, parameters: tuple[object, ...] = ()
    ) -> Any:
        if not self.cancelled and sql == "PRAGMA foreign_keys = ON":
            self.cancelled = True
            raise asyncio.CancelledError
        return self

    async def fetchone(self) -> tuple[int]:
        return (0,)

    async def fetchall(self) -> list[tuple[object, ...]]:
        return []

    async def executemany(self, sql: str, parameters: Any) -> Any:
        return self

    async def commit(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True


class _CancellingStartFactory:
    def __init__(self) -> None:
        self.connection = _CancellingStartConnection()

    async def connect(self, db_path: str) -> _CancellingStartConnection:
        return self.connection


@pytest.mark.asyncio
async def test_start_cancellation_closes_acquired_connection(tmp_path: Path) -> None:
    layout = _make_layout(tmp_path)
    factory = _CancellingStartFactory()
    authority = _authority(layout, connection_factory=factory)
    with pytest.raises(asyncio.CancelledError):
        await authority.start()
    assert factory.connection.closed is True
    with pytest.raises(WitnessUnavailableError):
        await authority.query_attempts()


class _FailingCommitConnection:
    def __init__(self, connection: Any, fail_at: int) -> None:
        self.connection = connection
        self.fail_at = fail_at
        self.commit_count = 0

    async def execute(self, sql: str, parameters: Any = ()) -> Any:
        return await self.connection.execute(sql, parameters)

    async def executemany(self, sql: str, parameters: Any) -> Any:
        return await self.connection.executemany(sql, parameters)

    async def executescript(self, script: str) -> None:
        await self.connection.executescript(script)

    async def commit(self) -> None:
        self.commit_count += 1
        if self.commit_count == self.fail_at:
            raise sqlite3.OperationalError("injected commit failure")
        await self.connection.commit()

    async def close(self) -> None:
        await self.connection.close()


class _FailingCommitFactory:
    def __init__(self, fail_at: int) -> None:
        self.fail_at = fail_at

    async def connect(self, db_path: str) -> _FailingCommitConnection:
        connection = await default_factory.connect(db_path)
        return _FailingCommitConnection(connection, self.fail_at)


class _CancellingFailureRecordConnection(_FailingCommitConnection):
    def __init__(self, connection: Any) -> None:
        super().__init__(connection, fail_at=5)
        self.closed = False

    async def execute(self, sql: str, parameters: Any = ()) -> Any:
        if "reason_code='evaluation_failed'" in sql:
            raise asyncio.CancelledError
        return await super().execute(sql, parameters)

    async def close(self) -> None:
        self.closed = True
        await super().close()


class _CancellingFailureRecordFactory:
    def __init__(self) -> None:
        self.connection: _CancellingFailureRecordConnection | None = None

    async def connect(self, db_path: str) -> _CancellingFailureRecordConnection:
        connection = _CancellingFailureRecordConnection(
            await default_factory.connect(db_path)
        )
        self.connection = connection
        return connection


class _CancellingPublicationConnection:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.cancel_once = True

    async def execute(self, sql: str, parameters: Any = ()) -> Any:
        if self.cancel_once and sql.startswith(
            "INSERT INTO execution_manifests"
        ):
            self.cancel_once = False
            raise asyncio.CancelledError
        return await self.connection.execute(sql, parameters)

    async def executemany(self, sql: str, parameters: Any) -> Any:
        return await self.connection.executemany(sql, parameters)

    async def executescript(self, script: str) -> None:
        await self.connection.executescript(script)

    async def commit(self) -> None:
        await self.connection.commit()

    async def close(self) -> None:
        await self.connection.close()


class _CancellingPublicationFactory:
    async def connect(self, db_path: str) -> _CancellingPublicationConnection:
        return _CancellingPublicationConnection(
            await default_factory.connect(db_path)
        )


@pytest.mark.asyncio
async def test_publish_post_begin_cancellation_rolls_back_for_retry(
    tmp_path: Path,
) -> None:
    layout = _make_layout(tmp_path)
    authority = _authority(
        layout,
        connection_factory=_CancellingPublicationFactory(),
    )
    await authority.start()

    with pytest.raises(asyncio.CancelledError):
        await authority.publish_manifest(_publication(layout))

    with sqlite3.connect(layout["db"], timeout=0.1) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.rollback()
    manifest = await authority.publish_manifest(_publication(layout))
    assert manifest.generation > 0
    await authority.stop()


@pytest.mark.asyncio
async def test_default_factory_external_lock_cancellation_releases_transaction(
    tmp_path: Path,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    manifest = await authority.publish_manifest(_publication(layout))
    external = sqlite3.connect(layout["db"], timeout=0.1)
    external.execute("BEGIN IMMEDIATE")
    admission = asyncio.create_task(authority.admit(_admission(manifest)))
    try:
        await asyncio.sleep(0.05)
        admission.cancel()
        await asyncio.sleep(0.05)
    finally:
        external.rollback()
        external.close()
    with pytest.raises(asyncio.CancelledError):
        await admission

    with sqlite3.connect(layout["db"], timeout=0.1) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.rollback()
    decision = await authority.admit(_admission(manifest))
    assert decision.outcome == "admitted"
    assert decision.grant is not None
    await authority.stop()


@pytest.mark.asyncio
async def test_witness_closed_locked_and_commit_failure_fail_closed(
    tmp_path: Path,
) -> None:
    closed_layout, closed = await _started_authority(tmp_path / "closed")
    await closed.stop()
    with pytest.raises(WitnessUnavailableError):
        await closed.admit(
            AdmissionRequest("m", 1, "s", "op", "target", "0" * 64)
        )
    locked_layout, locked = await _started_authority(tmp_path / "locked")
    locked_manifest = await locked.publish_manifest(_publication(locked_layout))
    external = sqlite3.connect(locked_layout["db"], timeout=0.1)
    external.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(WitnessUnavailableError):
            await locked.admit(_admission(locked_manifest))
    finally:
        external.rollback()
        external.close()
        await locked.stop()
    failed_layout = _make_layout(tmp_path / "failed")
    failing = _authority(
        failed_layout,
        connection_factory=_FailingCommitFactory(fail_at=5),
    )
    await failing.start()
    failed_manifest = await failing.publish_manifest(_publication(failed_layout))
    marker = tmp_path / "uncreated.marker"
    with pytest.raises(WitnessUnavailableError):
        await failing.admit(_admission(failed_manifest))
    assert not marker.exists()
    await failing.stop()


@pytest.mark.asyncio
async def test_admit_failure_record_cancellation_rolls_back_without_closing_owner(
    tmp_path: Path,
) -> None:
    layout = _make_layout(tmp_path)
    factory = _CancellingFailureRecordFactory()
    authority = _authority(layout, connection_factory=factory)
    await authority.start()
    manifest = await authority.publish_manifest(_publication(layout))

    with pytest.raises(asyncio.CancelledError):
        await authority.admit(_admission(manifest))

    assert factory.connection is not None
    assert factory.connection.closed is False
    attempts = await authority.query_attempts()
    grants = await authority.query_grants()
    assert len(attempts) == 1
    assert attempts[0][9:11] == ("pending", "pending")
    assert grants == ()
    with sqlite3.connect(layout["db"], timeout=0.1) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.rollback()
    await authority.stop()
    assert factory.connection.closed is True


@pytest.mark.asyncio
async def test_admit_before_manifest_persists_denial(tmp_path: Path) -> None:
    layout, authority = await _started_authority(tmp_path)
    request = AdmissionRequest(
        "missing", 1, "runtime-session", "read", "target",
        hashlib.sha256(b"shape").hexdigest(),
    )
    decision = await authority.admit(request)
    assert (decision.outcome, decision.reason_code, decision.grant) == (
        "denied",
        "manifest_unavailable",
        None,
    )
    with sqlite3.connect(layout["db"]) as db:
        assert db.execute(
            "SELECT outcome,reason_code FROM admission_attempts"
        ).fetchone() == ("denied", "manifest_unavailable")
    await authority.stop()


class _FailingPolicyAuthority(ProtectedExecutionAuthority):
    def _policy_allows(self, operation: str) -> bool:
        raise RuntimeError("evaluation failed")


@pytest.mark.asyncio
async def test_attempt_outcome_denominator_has_distinct_durable_ids(
    tmp_path: Path,
) -> None:
    layout = _make_layout(tmp_path)
    authority = _FailingPolicyAuthority(
        db_path=layout["db"],
        runtime_session_id="runtime-session",
        witness_busy_timeout_ms=5000,
        protected_installation_root=layout["protected"],
        policy_path=layout["policy"],
        worker_write_roots=(layout["worker"],),
        issuer_module_path=layout["issuer"],
    )
    await authority.start()
    manifest = await authority.publish_manifest(_publication(layout))
    failed = await authority.admit(_admission(manifest))
    assert failed.outcome == "failed"
    await authority.stop()

    authority = _authority(layout)
    await authority.start()
    manifest = await authority.publish_manifest(_publication(layout))
    admitted = await authority.admit(_admission(manifest))
    denied = await authority.admit(_admission(manifest, operation="write"))
    rejected = await authority.admit(_admission(manifest, operation=None))
    assert admitted.grant is not None
    await authority.mark_start_failed(admitted.grant, reason_code="effect_start_failed")
    await authority.stop()
    with sqlite3.connect(layout["db"]) as db:
        db.execute(
            "INSERT INTO admission_attempts VALUES "
            "('interrupted',1,NULL,NULL,NULL,'h','op','t','p','pending','pending',NULL,NULL)"
        )
    recovery = _authority(layout)
    await recovery.start()
    rows = await recovery.query_attempts()
    ids = [str(row[0]) for row in rows]
    outcomes = {str(row[9]) for row in rows}
    reasons = {str(row[10]) for row in rows}
    assert len(ids) == len(set(ids)) == 5
    assert outcomes == {"failed", "denied", "rejected"}
    assert {"evaluation_failed", "effect_start_failed", "issuer_interrupted"}.issubset(
        reasons
    )
    assert denied.outcome == "denied"
    assert rejected.outcome == "rejected"
    failed_rows = [row for row in rows if row[9] == "failed"]
    assert len(failed_rows) == 3
    assert all(row[2] is not None and row[12] == row[2] for row in failed_rows)
    assert all(
        row[12] is None
        for row in rows
        if row[9] in {"denied", "rejected"}
    )
    await recovery.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason_code",
    ["failure\nraw-content", "FailureCode", "failure-code", "x" * 129],
)
async def test_mark_start_failed_unstable_reason_code_rejects_before_persistence(
    tmp_path: Path,
    reason_code: str,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    manifest = await authority.publish_manifest(_publication(layout))
    admitted = await authority.admit(_admission(manifest))
    assert admitted.grant is not None

    with pytest.raises(ValueError):
        await authority.mark_start_failed(admitted.grant, reason_code=reason_code)

    with sqlite3.connect(layout["db"]) as db:
        attempt = db.execute(
            "SELECT outcome,reason_code FROM admission_attempts WHERE attempt_id=?",
            (admitted.attempt_id,),
        ).fetchone()
        grant = db.execute(
            "SELECT state,revoked_reason FROM execution_grants WHERE grant_id=?",
            (admitted.grant.grant_id,),
        ).fetchone()
    assert attempt == ("admitted", "policy_allowed")
    assert grant == ("active", "")
    await authority.stop()


@pytest.mark.asyncio
async def test_unlisted_operation_never_evaluates_unknown_persistence_label(
    tmp_path: Path,
) -> None:
    policy = {
        "operations": [
            {
                "operation_kind": "unknown",
                "handler": "unknown_handler",
                "allow": True,
            }
        ]
    }
    layout, authority = await _started_authority(tmp_path, policy=policy)
    manifest = await authority.publish_manifest(_publication(layout))
    decision = await authority.admit(
        _admission(manifest, operation="unlisted-operation")
    )
    assert (decision.outcome, decision.reason_code, decision.grant) == (
        "denied",
        "policy_refused",
        None,
    )
    with sqlite3.connect(layout["db"]) as db:
        assert db.execute(
            "SELECT operation_kind,outcome FROM admission_attempts "
            "WHERE attempt_id=?",
            (decision.attempt_id,),
        ).fetchone() == ("unknown", "denied")
    await authority.stop()


@pytest.mark.asyncio
async def test_concurrent_admissions_preserve_all_claims(tmp_path: Path) -> None:
    layout, authority = await _started_authority(tmp_path)
    manifest = await authority.publish_manifest(_publication(layout))
    operations = ["read" if index % 2 == 0 else "write" for index in range(32)]
    decisions = await asyncio.gather(
        *[_admit_one(authority, manifest, operation) for operation in operations]
    )
    assert len({decision.attempt_id for decision in decisions}) == 32
    assert sum(decision.outcome == "admitted" for decision in decisions) == 16
    assert sum(decision.outcome == "denied" for decision in decisions) == 16
    assert len(await authority.query_attempts()) == 32
    await authority.stop()


async def _admit_one(
    authority: ProtectedExecutionAuthority, manifest: Any, operation: str
) -> Any:
    return await authority.admit(_admission(manifest, operation=operation))


@pytest.mark.asyncio
async def test_persistence_and_logs_are_metadata_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    canaries = {
        "SOURCE-CANARY",
        "POLICY-CANARY",
        "TARGET-CANARY",
        "PROMPT-CANARY",
        "CREDENTIAL-CANARY",
        "ENV-CANARY",
    }
    layout = _make_layout(
        tmp_path,
        source_text="SOURCE-CANARY PROMPT-CANARY CREDENTIAL-CANARY ENV-CANARY",
    )
    layout["policy"].write_text(
        json.dumps({
            "operations": [
                {
                    "operation_kind": "read",
                    "handler": "POLICY-CANARY",
                    "allow": True,
                }
            ]
        }),
        encoding="utf-8",
    )
    authority = _authority(layout)
    caplog.set_level(logging.INFO)
    await authority.start()
    manifest = await authority.publish_manifest(_publication(layout))
    await authority.admit(
        _admission(
            manifest,
            target="TARGET-CANARY",
            shape=hashlib.sha256(b"parameter-canary").hexdigest(),
        )
    )
    await authority.stop()
    with sqlite3.connect(layout["db"]) as db:
        text = "\n".join(
            str(value)
            for table in (
                "authority_meta",
                "execution_manifests",
                "manifest_sources",
                "admission_attempts",
                "execution_grants",
            )
            for row in db.execute(f"SELECT * FROM {table}")
            for value in row
            if isinstance(value, str)
        )
    captured = caplog.text
    assert all(canary not in text and canary not in captured for canary in canaries)
    assert manifest.selected_agent.source_sha256 in text
    assert _json_digest("probos.admission-target.v1", "TARGET-CANARY") in text


@pytest.mark.asyncio
async def test_invalid_manifest_and_operation_are_not_persisted_or_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    layout, authority = await _started_authority(tmp_path)
    manifest = await authority.publish_manifest(_publication(layout))
    manifest_canary = "REQUEST-CONTENT-CANARY\nsecond-line"
    operation_canary = "OPERATION-CONTENT-CANARY\nsecond-line"
    caplog.set_level(logging.INFO)
    decision = await authority.admit(
        AdmissionRequest(
            manifest_id=manifest_canary,
            generation=manifest.generation,
            runtime_session_id="runtime-session",
            operation_kind=operation_canary,
            target_identity="target",
            parameter_shape_sha256=hashlib.sha256(b"shape").hexdigest(),
        )
    )
    assert (decision.outcome, decision.reason_code) == (
        "rejected",
        "malformed_request",
    )
    with sqlite3.connect(layout["db"]) as db:
        stored = db.execute(
            "SELECT manifest_id, operation_kind FROM admission_attempts "
            "WHERE attempt_id=?",
            (decision.attempt_id,),
        ).fetchone()
    assert stored == (None, "unknown")
    assert manifest_canary not in caplog.text
    assert operation_canary not in caplog.text
    assert "manifest_id=none" in caplog.text
    await authority.stop()


@pytest.mark.asyncio
async def test_out_of_range_generation_is_durably_rejected(
    tmp_path: Path,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    manifest = await authority.publish_manifest(_publication(layout))
    decision = await authority.admit(
        replace(_admission(manifest), generation=2**100)
    )
    assert (decision.outcome, decision.reason_code, decision.grant) == (
        "rejected",
        "malformed_request",
        None,
    )
    with sqlite3.connect(layout["db"]) as db:
        assert db.execute(
            "SELECT presented_generation,outcome FROM admission_attempts "
            "WHERE attempt_id=?",
            (decision.attempt_id,),
        ).fetchone() == (None, "rejected")
    await authority.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malformed_sha",
    [
        "+" + "a" * 63,
        "-" + "a" * 63,
        "a_" + "b" * 62,
        "A" * 64,
        " " + "a" * 63,
    ],
)
async def test_admit_noncanonical_sha256_is_durably_rejected(
    tmp_path: Path,
    malformed_sha: str,
) -> None:
    layout, authority = await _started_authority(tmp_path)
    manifest = await authority.publish_manifest(_publication(layout))
    decision = await authority.admit(
        _admission(manifest, shape=malformed_sha)
    )
    assert (decision.outcome, decision.reason_code, decision.grant) == (
        "rejected",
        "malformed_request",
        None,
    )
    with sqlite3.connect(layout["db"]) as db:
        stored = db.execute(
            "SELECT parameter_shape_sha256,outcome FROM admission_attempts "
            "WHERE attempt_id=?",
            (decision.attempt_id,),
        ).fetchone()
    assert stored is not None
    assert stored[0] != malformed_sha
    assert stored[1] == "rejected"
    await authority.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("overlap", ["witness", "policy", "installation"])
async def test_isolation_overlap_rejected_but_repository_allowed(
    tmp_path: Path, overlap: str
) -> None:
    layout = _make_layout(tmp_path)
    if overlap == "witness":
        worker_roots = (layout["db"].parent,)
    elif overlap == "policy":
        worker_roots = (layout["policy"],)
    else:
        worker_roots = (layout["protected"],)
    authority = ProtectedExecutionAuthority(
        db_path=layout["db"],
        runtime_session_id="session",
        witness_busy_timeout_ms=5000,
        protected_installation_root=layout["protected"],
        policy_path=layout["policy"],
        worker_write_roots=worker_roots,
        issuer_module_path=layout["issuer"],
    )
    with pytest.raises(IsolationBoundaryError):
        await authority.start()
    allowed = _authority(layout)
    await allowed.start()
    manifest = await allowed.publish_manifest(_publication(layout))
    assert manifest.repository.root_sha256
    await allowed.stop()


@pytest.mark.asyncio
async def test_real_process_commits_before_effect_marker(tmp_path: Path) -> None:
    layout = _make_layout(tmp_path)
    marker = tmp_path / "effect.marker"
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    process = context.Process(
        target=_child_positive,
        args=(_child_values(layout, marker), queue),
    )
    process.start()
    process.join(30)
    assert process.exitcode == 0
    grant, host = queue.get(timeout=5)
    assert marker.exists()
    with sqlite3.connect(layout["db"]) as db:
        assert db.execute(
            "SELECT outcome FROM admission_attempts WHERE attempt_id=?",
            (grant["attempt_id"],),
        ).fetchone() == ("admitted",)
        assert db.execute(
            "SELECT host_instance_id,process_id FROM authority_meta"
        ).fetchone() == (host["host_instance_id"], host["process_id"])


@pytest.mark.asyncio
async def test_real_process_hard_kill_keeps_evidence_and_no_effect(
    tmp_path: Path,
) -> None:
    layout = _make_layout(tmp_path)
    marker = tmp_path / "effect.marker"
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    release = context.Event()
    process = context.Process(
        target=_child_hard_kill,
        args=(_child_values(layout, marker), queue, release),
    )
    process.start()
    grant_data = queue.get(timeout=30)
    process.terminate()
    process.join(10)
    assert not marker.exists()
    with sqlite3.connect(layout["db"]) as db:
        assert db.execute(
            "SELECT outcome FROM admission_attempts WHERE attempt_id=?",
            (grant_data["attempt_id"],),
        ).fetchone() == ("admitted",)
    restarted = _authority(layout, session="kill-session")
    await restarted.start()
    with pytest.raises(StaleGrantError):
        await restarted.validate_grant(ExecutionGrant(**grant_data))
    await restarted.stop()


@pytest.mark.asyncio
async def test_real_process_stale_grant_validation_prevents_effect_marker(
    tmp_path: Path,
) -> None:
    layout = _make_layout(tmp_path)
    marker = tmp_path / "stale-effect.marker"
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    release = context.Event()
    process = context.Process(
        target=_child_stale_effect,
        args=(_child_values(layout, marker), queue, release),
    )
    process.start()
    grant_data = queue.get(timeout=30)
    superseding = _authority(layout, session="stale-session")
    await superseding.start()
    release.set()
    process.join(30)
    assert process.exitcode == 0
    assert queue.get(timeout=5) == "stale"
    assert not marker.exists()
    with sqlite3.connect(layout["db"]) as db:
        assert db.execute(
            "SELECT state FROM execution_grants WHERE grant_id=?",
            (grant_data["grant_id"],),
        ).fetchone() == ("revoked",)
    await superseding.stop()


def test_default_config_preserves_ordinary_behavior() -> None:
    config = SystemConfig()
    assert config.protected_execution == ProtectedExecutionConfig()
    assert config.security_infra.audit_enabled is True
    assert config.security_infra.audit_persistence_enabled is True
    with pytest.raises(ValidationError):
        ProtectedExecutionConfig(profile="strict")
    with pytest.raises(ValidationError):
        ProtectedExecutionConfig(witness_filename="../authority.db")


@pytest.mark.asyncio
async def test_runtime_strict_phase_one_exposes_and_closes_authority(
    tmp_path: Path,
) -> None:
    from probos.execution import authority as authority_module
    from probos.startup.infrastructure import boot_infrastructure

    package_root = Path(authority_module.__file__).resolve().parents[1]
    policy = package_root / f".ad1315-policy-{os.getpid()}.json"
    policy.write_text(
        json.dumps({"operations": []}),
        encoding="utf-8",
    )

    class _Started:
        async def start(self) -> None:
            return None

    class _EventLog(_Started):
        async def stop(self) -> None:
            return None

    async def _prune() -> None:
        await asyncio.Event().wait()

    config = SystemConfig(
        protected_execution=ProtectedExecutionConfig(
            enabled=True,
            profile="strict",
            protected_installation_root=str(package_root),
            policy_path=str(policy),
        )
    )
    try:
        result = await boot_infrastructure(
            event_log=_EventLog(),
            hebbian_router=_Started(),
            signal_manager=_Started(),
            gossip=_Started(),
            trust_network=_Started(),
            data_dir=tmp_path / "data",
            config=config,
            event_log_prune_loop_fn=_prune,
            runtime_session_id="runtime-phase-one",
        )
        assert result.execution_authority is not None
        await result.execution_authority.stop()  # type: ignore[attr-defined]
        result.event_prune_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await result.event_prune_task
        await result.identity_registry.stop()
    finally:
        policy.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_runtime_strict_witness_failure_propagates_before_later_services(
    tmp_path: Path,
) -> None:
    from probos.execution import authority as authority_module
    from probos.startup.infrastructure import boot_infrastructure

    package_root = Path(authority_module.__file__).resolve().parents[1]
    policy = package_root / f".ad1315-failure-policy-{os.getpid()}.json"
    policy.write_text(json.dumps({"operations": []}), encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    with sqlite3.connect(data_dir / "execution_authority.db") as db:
        db.execute("PRAGMA user_version=2")

    class _EventLog:
        def __init__(self) -> None:
            self.started = False

        async def start(self) -> None:
            self.started = True

    class _MustNotStart:
        async def start(self) -> None:
            raise AssertionError("later infrastructure started after witness failure")

    async def _prune() -> None:
        raise AssertionError("background task started after witness failure")

    event_log = _EventLog()
    config = SystemConfig(
        protected_execution=ProtectedExecutionConfig(
            enabled=True,
            profile="strict",
            protected_installation_root=str(package_root),
            policy_path=str(policy),
        )
    )
    try:
        with pytest.raises(WitnessSchemaError):
            await boot_infrastructure(
                event_log=event_log,  # type: ignore[arg-type]
                hebbian_router=_MustNotStart(),  # type: ignore[arg-type]
                signal_manager=_MustNotStart(),  # type: ignore[arg-type]
                gossip=_MustNotStart(),  # type: ignore[arg-type]
                trust_network=_MustNotStart(),  # type: ignore[arg-type]
                data_dir=data_dir,
                config=config,
                event_log_prune_loop_fn=_prune,
                runtime_session_id="failed-runtime-phase-one",
            )
        assert event_log.started is True
    finally:
        policy.unlink(missing_ok=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_type", [RuntimeError, asyncio.CancelledError])
async def test_runtime_phase_one_failure_unwinds_local_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_type: type[BaseException],
) -> None:
    from probos.execution import authority as authority_module
    from probos.startup.infrastructure import boot_infrastructure

    package_root = Path(authority_module.__file__).resolve().parents[1]
    policy = package_root / f".ad1315-unwind-policy-{os.getpid()}.json"
    policy.write_text(json.dumps({"operations": []}), encoding="utf-8")

    class _Authority:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

    class _EventLog:
        async def start(self) -> None:
            return None

    class _LaterFailure:
        async def start(self) -> None:
            raise failure_type("phase-one-service-failure")

    async def _prune() -> None:
        return None

    authority = _Authority()
    monkeypatch.setattr(
        authority_module,
        "ProtectedExecutionAuthority",
        lambda **kwargs: authority,
    )
    config = SystemConfig(
        protected_execution=ProtectedExecutionConfig(
            enabled=True,
            profile="strict",
            protected_installation_root=str(package_root),
            policy_path=str(policy),
        )
    )
    try:
        with pytest.raises(failure_type):
            await boot_infrastructure(
                event_log=_EventLog(),  # type: ignore[arg-type]
                hebbian_router=_LaterFailure(),  # type: ignore[arg-type]
                signal_manager=_LaterFailure(),  # type: ignore[arg-type]
                gossip=_LaterFailure(),  # type: ignore[arg-type]
                trust_network=_LaterFailure(),  # type: ignore[arg-type]
                data_dir=tmp_path / "data",
                config=config,
                event_log_prune_loop_fn=_prune,
                runtime_session_id="failed-runtime-phase-one",
            )
        assert authority.started is True
        assert authority.stopped is True
    finally:
        policy.unlink(missing_ok=True)


def test_store_registry_declares_protected_authority() -> None:
    registry = load_default_store_registry()
    declarations = {
        declaration.id: declaration for declaration in registry.declarations()
    }
    declaration = declarations["execution.protected-authority"]
    assert declaration.owner_module == "probos.execution.authority"
    assert declaration.owner_symbol == "ProtectedExecutionAuthority"
    assert declaration.canonical_path == "execution_authority.db"
    assert declaration.retention.value == "unbounded"
