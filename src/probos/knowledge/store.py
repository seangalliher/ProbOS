"""Git-backed persistent knowledge repository (AD-159 through AD-169).

The KnowledgeStore manages a local directory of JSON and Python artifacts
organised into typed subdirectories.  Git integration (commits, rollback,
history) is layered on top of the file I/O primitives.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import keyword
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, TypeVar

from probos.config import KnowledgeConfig
from probos.security.pii_redaction import PIIRedactor
from probos.types import AnchorFrame, Episode

log = logging.getLogger(__name__)

# Subdirectory names — one per artifact type (AD-160).
_SUBDIRS = (
    "episodes",
    "agents",
    "skills",
    "skill_quarantine",
    "trust",
    "routing",
    "workflows",
    "qa",
    "proactive",
)

_SCHEMA_VERSION = 1
_QUARANTINE_MAX_ERRORS = 20
_QUARANTINE_MAX_TEXT_CHARS = 500
_QUARANTINE_MAX_FILE_BYTES = 128 * 1024
_QUARANTINE_FIELDS = frozenset(
    {"intent_name", "source_sha256", "reason", "errors", "timestamp"}
)
_PERSISTED_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$", re.ASCII)
_SOURCE_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_SKILL_STORAGE_DIRS = frozenset({"skills", "skill_quarantine"})

_T = TypeVar("_T")


@dataclass(frozen=True)
class _PersistedSkillPaths:
    """Resolved, containment-checked paths for one persisted skill."""

    source: Path
    descriptor: Path
    quarantine: Path


def validate_persisted_skill_name(intent_name: str) -> str:
    """Return an unchanged safe persisted-skill name or raise ``ValueError``."""
    if (
        not isinstance(intent_name, str)
        or not intent_name.isascii()
        or _PERSISTED_SKILL_NAME_RE.fullmatch(intent_name) is None
        or keyword.iskeyword(intent_name)
        or not f"handle_{intent_name}".isidentifier()
    ):
        raise ValueError(
            "Persisted skill names must match ASCII ^[a-z][a-z0-9_]*$ "
            "and must not be Python keywords"
        )
    return intent_name


def _validate_source_sha256(source_sha256: str) -> str:
    """Return a canonical lowercase SHA-256 digest or raise ``ValueError``."""
    if (
        not isinstance(source_sha256, str)
        or _SOURCE_SHA256_RE.fullmatch(source_sha256) is None
    ):
        raise ValueError("Expected source hash must be 64 lowercase hexadecimal characters")
    return source_sha256


def _source_sha256(source_code: str) -> str:
    """Hash persisted UTF-8 skill source."""
    return hashlib.sha256(source_code.encode("utf-8")).hexdigest()


class KnowledgeStore:
    """Git-backed persistent knowledge repository."""

    def __init__(self, config: KnowledgeConfig, eviction_audit: Any = None) -> None:
        self._config = config
        self._eviction_audit = eviction_audit
        # Resolve repo path: empty → ~/.probos/knowledge/
        if config.repo_path:
            self._repo_path = Path(config.repo_path).expanduser()
        else:
            self._repo_path = Path.home() / ".probos" / "knowledge"

        self._git_available: bool | None = None  # Lazy-checked
        self._repo_initialised: bool = False
        self._flushing: bool = False  # Guard against debounce/flush race (AD-161)
        self._pending_messages: list[str] = []
        self._commit_timer: asyncio.TimerHandle | None = None
        self._skill_locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Ensure repo directory exists.  Git init on first write, not here (AD-159)."""
        repo_root = self._resolved_repo_root()
        repo_root.mkdir(parents=True, exist_ok=True)
        safe_skill_dirs = {
            sub: self._resolve_skill_directory(sub)
            for sub in _SKILL_STORAGE_DIRS
        }
        for sub in _SUBDIRS:
            safe_skill_dirs.get(sub, self._repo_path / sub).mkdir(exist_ok=True)

    @property
    def repo_exists(self) -> bool:
        """Whether the knowledge repo has been git-initialized."""
        return self._repo_initialised or (self._repo_path / ".git").is_dir()

    @property
    def repo_path(self) -> Path:
        return self._repo_path

    # ------------------------------------------------------------------
    # Episode persistence
    # ------------------------------------------------------------------

    async def store_episode(self, episode: Episode) -> None:
        """Write episode to episodes/{id}.json, schedule commit."""
        data = {
            "id": episode.id,
            "timestamp": episode.timestamp,
            "user_input": episode.user_input,
            "dag_summary": episode.dag_summary,
            "outcomes": episode.outcomes,
            "reflection": episode.reflection,
            "agent_ids": episode.agent_ids,
            "duration_ms": episode.duration_ms,
        }
        path = self._repo_path / "episodes" / f"{episode.id}.json"
        await self._write_json(path, data)

        # Evict oldest if over max
        await self._evict_episodes()

        await self._schedule_commit(f"Store episode {episode.id}")

    async def load_episodes(self, limit: int = 100) -> list[Episode]:
        """Load recent episodes from disk, sorted by timestamp desc."""
        episodes_dir = self._repo_path / "episodes"
        if not episodes_dir.is_dir():
            return []

        episodes: list[Episode] = []
        for fp in episodes_dir.glob("*.json"):
            try:
                data = await self._read_json(fp)
                anchors_data = data.get("anchors")
                anchors = AnchorFrame(**anchors_data) if anchors_data else None
                ep = Episode(
                    id=data["id"],
                    timestamp=data.get("timestamp", 0.0),
                    user_input=data.get("user_input", ""),
                    dag_summary=data.get("dag_summary", {}),
                    outcomes=data.get("outcomes", []),
                    reflection=data.get("reflection"),
                    agent_ids=data.get("agent_ids", []),
                    duration_ms=data.get("duration_ms", 0.0),
                    source=data.get("source", "direct"),
                    anchors=anchors,
                )
                episodes.append(ep)
            except FileNotFoundError:
                # BF-658: TOCTOU race — the file was globbed but concurrently
                # evicted (_evict_episodes) / removed before this async read.
                # Benign (the episode was over-capacity and being deleted
                # anyway); skip quietly instead of a misleading WARNING.
                log.debug(
                    "Episode %s vanished between listing and read "
                    "(concurrent eviction)", fp.name,
                )
            except Exception as exc:
                log.warning("Failed to load episode %s: %s", fp.name, exc)

        episodes.sort(key=lambda e: e.timestamp, reverse=True)
        return episodes[:limit]

    async def _evict_episodes(self) -> None:
        """Remove oldest episodes beyond max_episodes limit."""
        episodes_dir = self._repo_path / "episodes"
        if not episodes_dir.is_dir():
            return
        files = sorted(episodes_dir.glob("*.json"), key=lambda f: f.stat().st_mtime)
        excess = len(files) - self._config.max_episodes
        if excess > 0:
            to_delete = files[:excess]
            # AD-541f: Record evictions before deletion
            if self._eviction_audit:
                records = []
                for fp in to_delete:
                    try:
                        data = json.loads(fp.read_text())
                        agent_ids = data.get("agent_ids", [])
                        records.append({
                            "episode_id": fp.stem,
                            "agent_id": agent_ids[0] if agent_ids else "unknown",
                            "episode_timestamp": data.get("timestamp", 0.0),
                        })
                    except Exception:
                        records.append({
                            "episode_id": fp.stem,
                            "agent_id": "unknown",
                        })
                try:
                    await self._eviction_audit.record_batch_eviction(
                        records,
                        reason="capacity",
                        process="_evict_episodes",
                        details=f"batch of {len(to_delete)}, budget={self._config.max_episodes}",
                    )
                except Exception as exc:
                    log.warning("Eviction audit failed: %s", exc)
            for fp in to_delete:
                fp.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Designed agent persistence
    # ------------------------------------------------------------------

    async def store_agent(self, record: Any, source_code: str) -> None:
        """Write agent source to agents/{agent_type}.py and metadata to agents/{agent_type}.json."""
        agent_type = record.agent_type
        py_path = self._repo_path / "agents" / f"{agent_type}.py"
        json_path = self._repo_path / "agents" / f"{agent_type}.json"

        py_path.write_text(source_code, encoding="utf-8")

        metadata = {
            "intent_name": record.intent_name,
            "agent_type": record.agent_type,
            "class_name": record.class_name,
            "created_at": record.created_at,
            "sandbox_time_ms": record.sandbox_time_ms,
            "pool_name": record.pool_name,
            "status": record.status,
            "strategy": record.strategy,
        }
        await self._write_json(json_path, metadata)
        await self._schedule_commit(f"Store agent {agent_type}")

    async def load_agents(self) -> list[tuple[Any, str]]:
        """Load all designed agent records + source code.

        Returns list of (record_dict, source_code) tuples.
        """
        agents_dir = self._repo_path / "agents"
        if not agents_dir.is_dir():
            return []

        results: list[tuple[dict, str]] = []
        for json_fp in agents_dir.glob("*.json"):
            agent_type = json_fp.stem
            py_fp = agents_dir / f"{agent_type}.py"
            if not py_fp.is_file():
                continue
            try:
                metadata = await self._read_json(json_fp)
                source_code = py_fp.read_text(encoding="utf-8")
                results.append((metadata, source_code))
            except FileNotFoundError:
                # BF-658: TOCTOU race — globbed but concurrently removed
                # (remove_agent) before this read. Benign; skip quietly.
                log.debug(
                    "Agent %s vanished between listing and read "
                    "(concurrent removal)", agent_type,
                )
            except Exception as exc:
                log.warning("Failed to load agent %s: %s", agent_type, exc)
        return results

    async def remove_agent(self, agent_type: str) -> None:
        """Delete agent files and commit removal."""
        py_path = self._repo_path / "agents" / f"{agent_type}.py"
        json_path = self._repo_path / "agents" / f"{agent_type}.json"
        py_path.unlink(missing_ok=True)
        json_path.unlink(missing_ok=True)
        await self._schedule_commit(f"Remove agent {agent_type}")

    # ------------------------------------------------------------------
    # Skill persistence
    # ------------------------------------------------------------------

    async def store_skill(
        self,
        intent_name: str,
        source_code: str,
        descriptor: dict[str, Any],
    ) -> None:
        """Write skill source to skills/{intent_name}.py and descriptor to skills/{intent_name}.json."""
        name = validate_persisted_skill_name(intent_name)
        source_hash = _source_sha256(source_code)
        self._resolve_skill_paths(name)

        async def _store() -> None:
            paths = self._resolve_skill_paths(name)
            paths.source.write_text(source_code, encoding="utf-8")
            paths = self._resolve_skill_paths(name)
            await self._write_json(paths.descriptor, descriptor)
            marker = await self._load_skill_quarantine_locked(name)
            if marker is not None and marker["source_sha256"] != source_hash:
                paths = self._resolve_skill_paths(name)
                paths.quarantine.unlink(missing_ok=True)
            await self._schedule_commit(f"Store skill {name}")

        await self._run_skill_transaction(name, _store)

    async def load_skills(self) -> list[tuple[str, str, dict[str, Any]]]:
        """Load all skills: (intent_name, source_code, descriptor_dict)."""
        try:
            skills_dir = self._resolve_skill_directory("skills")
            self._resolve_skill_directory("skill_quarantine")
        except ValueError as exc:
            log.warning(
                "Skipping persisted skill scan because its storage directory "
                "escapes the resolved knowledge repo; no skill source will be "
                "read or executed: %s",
                exc,
            )
            return []
        if not skills_dir.is_dir():
            return []

        results: list[tuple[str, str, dict[str, Any]]] = []
        for json_fp in skills_dir.glob("*.json"):
            try:
                intent_name = validate_persisted_skill_name(json_fp.stem)
            except ValueError as exc:
                log.warning(
                    "Skipping persisted skill descriptor %s because its filename "
                    "is unsafe; the artifact remains untouched: %s",
                    json_fp.name,
                    exc,
                )
                continue

            try:
                self._resolve_skill_paths(intent_name)
                lock = self._skill_lock(intent_name)
                async with lock:
                    loaded = await self._load_skill_pair_locked(intent_name)
                if loaded is not None:
                    results.append(loaded)
            except ValueError as exc:
                log.warning(
                    "Skipping persisted skill %s because its resolved artifact "
                    "path escapes the knowledge repo; the entry remains "
                    "untouched: %s",
                    intent_name,
                    exc,
                )
            except FileNotFoundError:
                # BF-658: TOCTOU race — globbed but concurrently removed
                # (remove_skill) before this read. Benign; skip quietly.
                log.debug(
                    "Skill %s vanished between listing and read "
                    "(concurrent removal)", intent_name,
                )
            except Exception as exc:
                log.warning("Failed to load skill %s: %s", intent_name, exc)
        return results

    async def load_skill_source(self, intent_name: str) -> str | None:
        """Load one persisted skill source under its per-intent lock."""
        name = validate_persisted_skill_name(intent_name)
        self._resolve_skill_paths(name)
        lock = self._skill_lock(name)
        async with lock:
            return self._load_skill_source_locked(name)

    async def load_skill_quarantine(self, intent_name: str) -> dict[str, Any] | None:
        """Load a valid skill quarantine marker, if one exists."""
        name = validate_persisted_skill_name(intent_name)
        self._resolve_skill_paths(name)
        lock = self._skill_lock(name)
        async with lock:
            return await self._load_skill_quarantine_locked(name)

    async def load_skill_source_and_quarantine(
        self,
        intent_name: str,
    ) -> tuple[str | None, dict[str, Any] | None]:
        """Atomically read one source and its valid marker under one skill lock."""
        name = validate_persisted_skill_name(intent_name)
        self._resolve_skill_paths(name)
        lock = self._skill_lock(name)
        async with lock:
            source_code = self._load_skill_source_locked(name)
            marker = await self._load_skill_quarantine_locked(name)
            return source_code, marker

    async def quarantine_skill(
        self,
        intent_name: str,
        *,
        source_code: str,
        expected_source_sha256: str,
        reason: str,
        errors: list[str],
    ) -> bool:
        """Publish a marker only while the expected skill source remains current."""
        name = validate_persisted_skill_name(intent_name)
        expected_hash = _validate_source_sha256(expected_source_sha256)
        if not isinstance(source_code, str) or _source_sha256(source_code) != expected_hash:
            return False
        if not isinstance(reason, str):
            raise ValueError("Skill quarantine reason must be a string")
        if not isinstance(errors, list) or not all(
            isinstance(error, str) for error in errors
        ):
            raise ValueError("Skill quarantine errors must be a list of strings")

        redacted_reason = self._sanitize_quarantine_text(reason)
        if not redacted_reason:
            raise ValueError("Skill quarantine reason must not be empty")
        redacted_errors = [
            self._sanitize_quarantine_text(error)
            for error in errors[:_QUARANTINE_MAX_ERRORS]
        ]

        self._resolve_skill_paths(name)

        async def _quarantine() -> bool:
            current_source = self._load_skill_source_locked(name)
            if current_source is None or _source_sha256(current_source) != expected_hash:
                return False

            path = self._resolve_skill_paths(name).quarantine
            marker = {
                "intent_name": name,
                "source_sha256": expected_hash,
                "reason": redacted_reason,
                "errors": redacted_errors,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await self._write_skill_quarantine_marker(path, marker)
            await self._schedule_commit(f"Quarantine skill {name}")
            return True

        return await self._run_skill_transaction(name, _quarantine)

    async def clear_skill_quarantine(
        self,
        intent_name: str,
        *,
        expected_source_sha256: str,
    ) -> bool:
        """Delete only the valid marker identified by ``expected_source_sha256``."""
        name = validate_persisted_skill_name(intent_name)
        expected_hash = _validate_source_sha256(expected_source_sha256)
        self._resolve_skill_paths(name)

        async def _clear() -> bool:
            marker = await self._load_skill_quarantine_locked(name)
            if marker is None or marker["source_sha256"] != expected_hash:
                return False

            path = self._resolve_skill_paths(name).quarantine
            try:
                path.unlink()
            except FileNotFoundError:
                return False
            await self._schedule_commit(f"Clear skill quarantine {name}")
            return True

        return await self._run_skill_transaction(name, _clear)

    async def remove_skill(
        self,
        intent_name: str,
        *,
        expected_source_sha256: str | None = None,
    ) -> bool:
        """Delete a skill, optionally only while its source hash still matches."""
        name = validate_persisted_skill_name(intent_name)
        expected_hash = (
            _validate_source_sha256(expected_source_sha256)
            if expected_source_sha256 is not None
            else None
        )
        self._resolve_skill_paths(name)

        async def _remove() -> bool:
            current_source = self._load_skill_source_locked(name)
            if expected_hash is not None and (
                current_source is None or _source_sha256(current_source) != expected_hash
            ):
                return False

            paths = self._resolve_skill_paths(name)
            paths_to_remove = [paths.source, paths.descriptor]
            if expected_hash is None:
                paths_to_remove.append(paths.quarantine)
            else:
                marker = await self._load_skill_quarantine_locked(name)
                if marker is not None and marker["source_sha256"] == expected_hash:
                    paths_to_remove.append(paths.quarantine)

            mutated = False
            for path in paths_to_remove:
                paths = self._resolve_skill_paths(name)
                safe_paths = {paths.source, paths.descriptor, paths.quarantine}
                if path not in safe_paths:
                    raise ValueError(
                        f"Persisted skill path changed before removal: {path}"
                    )
                try:
                    path.unlink()
                    mutated = True
                except FileNotFoundError:
                    continue
            if mutated:
                await self._schedule_commit(f"Remove skill {name}")
            return mutated

        return await self._run_skill_transaction(name, _remove)

    async def _run_skill_transaction(
        self,
        intent_name: str,
        operation: Callable[[], Awaitable[_T]],
    ) -> _T:
        """Run a complete locked mutation before propagating cancellation."""
        lock = self._skill_lock(intent_name)
        await lock.acquire()
        try:
            transaction = self._create_skill_transaction_runner(
                intent_name, operation,
            )
            return await self._await_skill_task(transaction)
        finally:
            lock.release()

    def _create_skill_transaction_runner(
        self,
        intent_name: str,
        operation: Callable[[], Awaitable[_T]],
    ) -> asyncio.Task[_T]:
        """Create the private runner that owns and drains one operation task."""
        return asyncio.create_task(
            self._run_skill_transaction_runner(intent_name, operation),
            name=f"probos-skill-transaction:{intent_name}",
        )

    async def _run_skill_transaction_runner(
        self,
        intent_name: str,
        operation: Callable[[], Awaitable[_T]],
    ) -> _T:
        """Keep the operation alive until all mutation and commit work completes."""
        operation_task = asyncio.create_task(
            operation(),
            name=f"probos-skill-operation:{intent_name}",
        )
        return await self._await_skill_task(operation_task)

    @staticmethod
    async def _await_skill_task(task: asyncio.Task[_T]) -> _T:
        """Shield and drain a child task before propagating caller cancellation."""
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancellation:
            current_task = asyncio.current_task()
            if current_task is None or current_task.cancelling() == 0:
                return task.result()
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
            try:
                task.result()
            except BaseException as task_error:
                raise cancellation from task_error
            raise cancellation

    def _skill_lock(self, intent_name: str) -> asyncio.Lock:
        """Return the per-intent lock after the caller has validated the name."""
        lock = self._skill_locks.get(intent_name)
        if lock is None:
            lock = asyncio.Lock()
            self._skill_locks[intent_name] = lock
        return lock

    def _resolved_repo_root(self) -> Path:
        """Return the canonical knowledge root or fail closed on resolution errors."""
        try:
            return self._repo_path.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ValueError(
                f"Knowledge repo path cannot be resolved safely: {self._repo_path}"
            ) from exc

    @staticmethod
    def _require_resolved_child(path: Path, parent: Path, *, label: str) -> None:
        """Require a resolved path to be a strict child of its resolved parent."""
        try:
            relative = path.relative_to(parent)
        except ValueError as exc:
            raise ValueError(
                f"{label} resolves outside its allowed directory: {path}"
            ) from exc
        if relative == Path("."):
            raise ValueError(f"{label} must resolve beneath its allowed directory")

    def _resolve_skill_directory(
        self,
        directory_name: Literal["skills", "skill_quarantine"],
    ) -> Path:
        """Resolve one skill storage directory and reject symlink/junction escape."""
        if directory_name not in _SKILL_STORAGE_DIRS:
            raise ValueError(f"Unsupported persisted skill directory: {directory_name}")
        root = self._resolved_repo_root()
        raw_directory = self._repo_path / directory_name
        try:
            directory = raw_directory.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ValueError(
                f"Persisted skill directory cannot be resolved: {raw_directory}"
            ) from exc
        self._require_resolved_child(
            directory,
            root,
            label=f"Persisted skill directory {directory_name}",
        )
        if raw_directory.exists() and not raw_directory.is_dir():
            raise ValueError(
                f"Persisted skill directory is not a directory: {raw_directory}"
            )
        return directory

    def _resolve_skill_candidate(
        self,
        directory_name: Literal["skills", "skill_quarantine"],
        filename: str,
    ) -> Path:
        """Resolve one skill artifact beneath its canonical storage directory."""
        root = self._resolved_repo_root()
        directory = self._resolve_skill_directory(directory_name)
        raw_candidate = self._repo_path / directory_name / filename
        try:
            candidate = raw_candidate.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ValueError(
                f"Persisted skill artifact cannot be resolved: {raw_candidate}"
            ) from exc
        self._require_resolved_child(
            candidate,
            root,
            label=f"Persisted skill artifact {filename}",
        )
        self._require_resolved_child(
            candidate,
            directory,
            label=f"Persisted skill artifact {filename}",
        )
        return candidate

    def _resolve_skill_paths(self, intent_name: str) -> _PersistedSkillPaths:
        """Resolve all files for one validated skill without creating anything."""
        name = validate_persisted_skill_name(intent_name)
        return _PersistedSkillPaths(
            source=self._resolve_skill_candidate("skills", f"{name}.py"),
            descriptor=self._resolve_skill_candidate("skills", f"{name}.json"),
            quarantine=self._resolve_skill_candidate(
                "skill_quarantine", f"{name}.json"
            ),
        )

    async def _load_skill_pair_locked(
        self,
        intent_name: str,
    ) -> tuple[str, str, dict[str, Any]] | None:
        """Load a source/descriptor pair while the caller holds the skill lock."""
        paths = self._resolve_skill_paths(intent_name)
        if not paths.source.is_file():
            return None
        descriptor = await self._read_json(paths.descriptor)
        paths = self._resolve_skill_paths(intent_name)
        source_code = paths.source.read_text(encoding="utf-8")
        return intent_name, source_code, descriptor

    def _load_skill_source_locked(self, intent_name: str) -> str | None:
        """Read one source while the caller holds the validated intent lock."""
        path = self._resolve_skill_paths(intent_name).source
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None

    async def _load_skill_quarantine_locked(
        self,
        intent_name: str,
    ) -> dict[str, Any] | None:
        """Load and validate one marker while the caller holds the skill lock."""
        path = self._resolve_skill_paths(intent_name).quarantine
        if not path.is_file():
            return None
        try:
            data = await self._read_skill_quarantine_marker(path)
            if not self._is_valid_quarantine_marker(data, intent_name):
                log.warning(
                    "Skill quarantine marker for %s is malformed or outside its "
                    "bounds; ignoring it so the preserved source is revalidated",
                    intent_name,
                )
                return None
            return data
        except FileNotFoundError:
            log.debug(
                "Skill quarantine marker for %s vanished before read; "
                "the preserved source will be revalidated",
                intent_name,
            )
            return None
        except Exception as exc:
            log.warning(
                "Failed to load skill quarantine marker for %s: %s; "
                "ignoring the marker so the preserved source is revalidated",
                intent_name,
                exc,
            )
            return None

    @staticmethod
    def _is_valid_quarantine_marker(data: Any, intent_name: str) -> bool:
        """Return whether untrusted persisted marker data has the exact safe shape."""
        if not isinstance(data, dict) or set(data) != _QUARANTINE_FIELDS:
            return False
        source_hash = data.get("source_sha256")
        reason = data.get("reason")
        errors = data.get("errors")
        timestamp = data.get("timestamp")
        if (
            data.get("intent_name") != intent_name
            or not isinstance(source_hash, str)
            or _SOURCE_SHA256_RE.fullmatch(source_hash) is None
            or not isinstance(reason, str)
            or not reason.strip()
            or len(reason) > _QUARANTINE_MAX_TEXT_CHARS
            or not isinstance(errors, list)
            or len(errors) > _QUARANTINE_MAX_ERRORS
            or any(
                not isinstance(error, str)
                or len(error) > _QUARANTINE_MAX_TEXT_CHARS
                for error in errors
            )
            or not isinstance(timestamp, str)
        ):
            return False
        try:
            parsed_timestamp = datetime.fromisoformat(
                timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
            )
        except ValueError:
            return False
        return (
            parsed_timestamp.tzinfo is not None
            and parsed_timestamp.utcoffset() == timedelta(0)
        )

    async def _read_skill_quarantine_marker(self, path: Path) -> Any:
        """Read a marker through a bounded quarantine-specific JSON seam."""
        safe_directory = self._resolve_skill_directory("skill_quarantine")
        safe_path = path.resolve(strict=False)
        self._require_resolved_child(
            safe_path,
            safe_directory,
            label=f"Skill quarantine marker {path.name}",
        )
        loop = asyncio.get_running_loop()

        def _read() -> Any:
            with safe_path.open("rb") as marker_file:
                raw = marker_file.read(_QUARANTINE_MAX_FILE_BYTES + 1)
            if len(raw) > _QUARANTINE_MAX_FILE_BYTES:
                raise ValueError("marker exceeds maximum encoded size")
            return json.loads(raw.decode("utf-8"))

        return await loop.run_in_executor(None, _read)

    async def _write_skill_quarantine_marker(
        self,
        path: Path,
        marker: dict[str, Any],
    ) -> None:
        """Atomically publish a quarantine marker through a unique sibling temp."""
        loop = asyncio.get_running_loop()
        content = json.dumps(marker, indent=2, ensure_ascii=False)

        def _write() -> None:
            marker_name = marker.get("intent_name")
            safe_path = self._resolve_skill_paths(marker_name).quarantine
            if path.resolve(strict=False) != safe_path:
                raise ValueError(
                    f"Skill quarantine marker path changed before write: {path}"
                )
            safe_path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{safe_path.name}.",
                suffix=".tmp",
                dir=str(safe_path.parent),
            )
            temp_path = Path(temp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as temp_file:
                    fd = -1
                    temp_file.write(content)
                    temp_file.flush()
                    os.fsync(temp_file.fileno())
                os.replace(temp_path, safe_path)
            finally:
                if fd >= 0:
                    os.close(fd)
                temp_path.unlink(missing_ok=True)

        await loop.run_in_executor(None, _write)

    @staticmethod
    def _sanitize_quarantine_text(value: Any) -> str:
        """Redact and bound a marker field without persisting a traceback."""
        text = PIIRedactor.redact_all(str(value))
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if any(line.startswith("Traceback (most recent call last)") for line in lines):
            text = lines[-1] if lines else ""
        else:
            text = " ".join(lines)
        return text[:_QUARANTINE_MAX_TEXT_CHARS]

    # ------------------------------------------------------------------
    # Trust persistence (AD-168)
    # ------------------------------------------------------------------

    async def store_trust_snapshot(self, raw_scores: dict[str, dict]) -> None:
        """Write trust records to trust/snapshot.json.

        raw_scores must contain {agent_id: {alpha, beta, observations}}.
        """
        path = self._repo_path / "trust" / "snapshot.json"
        await self._write_json(path, raw_scores)
        await self._schedule_commit("Store trust snapshot")

    async def load_trust_snapshot(self) -> dict[str, dict] | None:
        """Load trust snapshot.  Returns None if not found."""
        path = self._repo_path / "trust" / "snapshot.json"
        if not path.is_file():
            return None
        try:
            return await self._read_json(path)
        except Exception as exc:
            log.warning("Failed to load trust snapshot: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Hebbian routing persistence
    # ------------------------------------------------------------------

    async def store_routing_weights(self, weights: list[dict]) -> None:
        """Write routing weights to routing/weights.json."""
        path = self._repo_path / "routing" / "weights.json"
        await self._write_json(path, weights)
        await self._schedule_commit("Store routing weights")

    async def load_routing_weights(self) -> list[dict] | None:
        """Load routing weights.  Returns None if not found."""
        path = self._repo_path / "routing" / "weights.json"
        if not path.is_file():
            return None
        try:
            return await self._read_json(path)
        except Exception as exc:
            log.warning("Failed to load routing weights: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Proactive cooldown persistence (AD-415)
    # ------------------------------------------------------------------

    async def store_cooldowns(self, cooldowns: dict[str, float]) -> None:
        """Persist per-agent proactive cooldown overrides."""
        if not cooldowns:
            return
        path = self._repo_path / "proactive" / "cooldowns.json"
        await self._write_json(path, cooldowns)

    async def load_cooldowns(self) -> dict[str, float] | None:
        """Load per-agent proactive cooldown overrides."""
        path = self._repo_path / "proactive" / "cooldowns.json"
        if not path.is_file():
            return None
        try:
            data = await self._read_json(path)
            if isinstance(data, dict):
                return {k: float(v) for k, v in data.items()}
            return None
        except Exception as exc:
            log.warning("Failed to load cooldowns: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Workflow cache persistence
    # ------------------------------------------------------------------

    async def store_workflows(self, entries: list[dict]) -> None:
        """Write workflow cache entries to workflows/cache.json."""
        # Evict if over max
        if len(entries) > self._config.max_workflows:
            entries = sorted(entries, key=lambda e: e.get("hit_count", 0), reverse=True)
            entries = entries[: self._config.max_workflows]

        path = self._repo_path / "workflows" / "cache.json"
        await self._write_json(path, entries)
        await self._schedule_commit("Store workflow cache")

    async def load_workflows(self) -> list[dict] | None:
        """Load workflow cache entries."""
        path = self._repo_path / "workflows" / "cache.json"
        if not path.is_file():
            return None
        try:
            return await self._read_json(path)
        except Exception as exc:
            log.warning("Failed to load workflow cache: %s", exc)
            return None

    # ------------------------------------------------------------------
    # QA report persistence
    # ------------------------------------------------------------------

    async def store_qa_report(self, agent_type: str, report_dict: dict) -> None:
        """Write QA report to qa/{agent_type}.json."""
        path = self._repo_path / "qa" / f"{agent_type}.json"
        await self._write_json(path, report_dict)
        await self._schedule_commit(f"Store QA report for {agent_type}")

    async def load_qa_reports(self) -> dict[str, dict]:
        """Load all QA reports."""
        qa_dir = self._repo_path / "qa"
        if not qa_dir.is_dir():
            return {}

        results: dict[str, dict] = {}
        for fp in qa_dir.glob("*.json"):
            agent_type = fp.stem
            try:
                results[agent_type] = await self._read_json(fp)
            except Exception as exc:
                log.warning("Failed to load QA report %s: %s", agent_type, exc)
        return results

    # ------------------------------------------------------------------
    # Agent manifest persistence (Phase 14c)
    # ------------------------------------------------------------------

    async def store_manifest(self, manifest: list[dict]) -> None:
        """Write the agent roster to manifest.json."""
        path = self._repo_path / "manifest.json"
        await self._write_json(path, manifest)
        await self._schedule_commit("Store agent manifest")

    async def load_manifest(self) -> list[dict]:
        """Load the agent manifest.  Returns empty list if not found."""
        path = self._repo_path / "manifest.json"
        if not path.is_file():
            return []
        try:
            data = await self._read_json(path)
            return data if isinstance(data, list) else []
        except Exception as exc:
            log.warning("Failed to load agent manifest: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Artifact counts (for experience layer)
    # ------------------------------------------------------------------

    def artifact_counts(self) -> dict[str, int]:
        """Count artifacts per subdirectory."""
        counts: dict[str, int] = {}
        for sub in _SUBDIRS:
            d = self._repo_path / sub
            if d.is_dir():
                counts[sub] = len(list(d.glob("*.json"))) + len(list(d.glob("*.py")))
            else:
                counts[sub] = 0
        return counts

    # ------------------------------------------------------------------
    # Git operations — Step 4 will flesh these out
    # ------------------------------------------------------------------

    async def _ensure_repo(self) -> None:
        """Git init if not already a repo (AD-159).

        Creates meta.json with schema_version, probos_version, created (AD-169).
        Checks git version >= 1.8.5 for -C flag support.
        """
        if self._repo_initialised:
            return

        if self._git_available is None:
            self._git_available = shutil.which("git") is not None

        # Write meta.json on first repo init
        meta_path = self._repo_path / "meta.json"
        if not meta_path.is_file():
            meta = {
                "schema_version": _SCHEMA_VERSION,
                "probos_version": "0.1.0",
                "created": datetime.now(timezone.utc).isoformat(),
            }
            await self._write_json(meta_path, meta)

        if not self._git_available:
            self._repo_initialised = True
            return

        if not (self._repo_path / ".git").is_dir():
            # Check git version
            try:
                result = await self._git_run("--version")
                version_str = result.stdout.strip()
                log.debug("Git version: %s", version_str)
            except Exception:
                log.warning("Could not determine Git version", exc_info=True)

            await self._git_run("init")
            await self._git_run("config", "user.email", "probos@localhost")
            await self._git_run("config", "user.name", "ProbOS")

        self._repo_initialised = True

    async def _schedule_commit(self, message: str) -> None:
        """Debounced commit (AD-161).

        Batches writes within the debounce window.
        Skips if _flushing is True (shutdown flush is handling the commit).
        """
        if not self._config.auto_commit:
            return
        await self._ensure_repo()

        if self._flushing:
            return

        self._pending_messages.append(message)

        if self._commit_timer is not None:
            self._commit_timer.cancel()

        try:
            loop = asyncio.get_running_loop()
            self._commit_timer = loop.call_later(
                self._config.commit_debounce_seconds,
                lambda: asyncio.create_task(self._flush_pending()),
            )
        except RuntimeError:
            # No running loop (e.g. during testing without async context)
            pass

    async def _flush_pending(self) -> None:
        """Commit all pending messages.  Called by debounce timer."""
        if self._flushing:
            return
        if not self._pending_messages:
            return

        messages = self._pending_messages[:]
        self._pending_messages.clear()
        self._commit_timer = None

        combined = "; ".join(messages)
        await self._git_commit(combined)

    async def _git_commit(self, message: str) -> None:
        """Run git add + commit in thread executor (AD-166).

        BF: Concurrent processes touching the same repo can leave the
        index or HEAD ref in a half-written state. Detect both classes
        and recover in place rather than just logging a warning.
        """
        if not self._git_available:
            return

        try:
            result_add = await self._git_run("add", "-A")
            if (
                result_add.returncode != 0
                and "index file corrupt" in (result_add.stderr or "")
            ):
                log.warning(
                    "Git index corrupt at %s; rebuilding from HEAD",
                    self._repo_path,
                )
                idx = self._repo_path / ".git" / "index"
                try:
                    idx.unlink(missing_ok=True)
                except OSError:
                    pass
                rebuild = await self._git_run("read-tree", "HEAD")
                if rebuild.returncode != 0:
                    log.warning(
                        "Git index rebuild failed: %s", rebuild.stderr.strip()
                    )
                    return
                result_add = await self._git_run("add", "-A")
            if result_add.returncode != 0:
                log.warning("Git add failed: %s", result_add.stderr.strip())
                return
            result = await self._git_run("commit", "-m", message, "--allow-empty")
            if result.returncode == 0 or "nothing to commit" in result.stdout:
                return
            stderr = result.stderr or ""
            if (
                "reference broken" in stderr
                or "unable to resolve reference" in stderr
                or "cannot lock ref" in stderr
            ):
                # BF: a broken HEAD ref (zero-length or truncated
                # `.git/refs/heads/<branch>`) blocks every commit. The
                # reflog still has the last good SHA — recover by
                # rewriting the ref from `git reflog` and retrying.
                log.warning(
                    "Git ref broken at %s; attempting recovery",
                    self._repo_path,
                )
                sha = await self._recover_last_commit_sha()
                if sha:
                    # `git update-ref` refuses to overwrite a "reference
                    # broken" ref — delete the corrupt loose ref files
                    # first so update-ref can write a clean one.
                    git_dir = self._repo_path / ".git"
                    for rel in (
                        "refs/heads/master",
                        "refs/heads/main",
                    ):
                        p = git_dir / rel
                        try:
                            if p.is_file():
                                p.unlink()
                        except OSError:
                            pass
                    update = await self._git_run(
                        "update-ref", "refs/heads/master", sha
                    )
                    if update.returncode == 0:
                        retry = await self._git_run(
                            "commit", "-m", message, "--allow-empty"
                        )
                        if (
                            retry.returncode == 0
                            or "nothing to commit" in retry.stdout
                        ):
                            return
                        log.warning(
                            "Git commit retry failed after ref recovery: %s",
                            retry.stderr.strip(),
                        )
                        return
                    log.warning(
                        "Git update-ref failed: %s",
                        update.stderr.strip(),
                    )
                    return
                log.warning(
                    "Git ref recovery failed: no recoverable commit "
                    "(reflog empty and no detached HEAD)"
                )
                return
            log.warning("Git commit failed: %s", stderr.strip())
        except Exception as exc:
            log.warning("Git commit error: %s", exc)

    async def flush(self) -> None:
        """Force commit any pending changes.  Called on shutdown.

        Sets _flushing=True, cancels pending timer, commits, resets flag (AD-161).
        """
        self._flushing = True
        try:
            if self._commit_timer is not None:
                self._commit_timer.cancel()
                self._commit_timer = None

            if self._pending_messages:
                messages = self._pending_messages[:]
                self._pending_messages.clear()
                combined = "; ".join(messages)
                await self._git_commit(combined)
            else:
                # Commit any un-committed file changes
                await self._git_commit("Shutdown flush")
        finally:
            self._flushing = False

    async def _git_run(self, *args: str) -> subprocess.CompletedProcess:
        """Run a git command in a thread executor (AD-166)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["git", "-C", str(self._repo_path), *args],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            ),
        )

    async def _recover_last_commit_sha(self) -> str | None:
        """Find the most recent commit SHA when refs are corrupt.

        Tries in order:
          1. ``git reflog --format=%H -n 1`` (works only if HEAD resolves)
          2. Parse ``.git/logs/refs/heads/<branch>`` directly (last entry's
             "new" sha — survives a zeroed branch ref)
          3. Parse ``.git/logs/HEAD`` directly
          4. ``git fsck --lost-found`` and pick the youngest commit object
        """
        # 1. Standard reflog lookup.
        reflog = await self._git_run("reflog", "--format=%H", "-n", "1")
        if reflog.returncode == 0:
            line = (reflog.stdout or "").strip().splitlines()[:1]
            if line and len(line[0]) == 40:
                return line[0]

        git_dir = self._repo_path / ".git"

        # 2. Parse per-branch reflog file directly.
        # 3. Fall back to HEAD reflog file.
        for rel in ("logs/refs/heads/master", "logs/refs/heads/main", "logs/HEAD"):
            log_path = git_dir / rel
            if not log_path.is_file():
                continue
            try:
                # Read as bytes — corrupted reflogs sometimes contain NUL
                # padding that confuses Python's text-mode line splitter.
                data = log_path.read_bytes()
                last = ""
                for raw in data.split(b"\n"):
                    stripped = raw.strip(b"\x00 \t\r")
                    if stripped:
                        last = stripped.decode("utf-8", errors="replace")
                if last:
                    parts = last.split(" ", 2)
                    if len(parts) >= 2 and len(parts[1]) == 40:
                        # Confirm the object exists.
                        check = await self._git_run("cat-file", "-t", parts[1])
                        if check.returncode == 0 and check.stdout.strip() == "commit":
                            return parts[1]
            except OSError:
                continue

        # 4. Last resort: fsck the object DB and pick the most recent
        # dangling commit by mtime of its loose-object file.
        fsck = await self._git_run("fsck", "--lost-found", "--no-progress")
        candidates: list[tuple[float, str]] = []
        for line in (fsck.stdout or "").splitlines():
            # "dangling commit <sha>" — and similarly under fsck stderr.
            if line.startswith("dangling commit "):
                sha = line.split(" ", 2)[-1].strip()
                if len(sha) == 40:
                    obj = git_dir / "objects" / sha[:2] / sha[2:]
                    try:
                        candidates.append((obj.stat().st_mtime, sha))
                    except OSError:
                        candidates.append((0.0, sha))
        if candidates:
            candidates.sort(reverse=True)
            return candidates[0][1]

        return None

    # ------------------------------------------------------------------
    # Rollback (Step 5)
    # ------------------------------------------------------------------

    async def rollback_artifact(self, artifact_type: str, identifier: str) -> bool:
        """Revert a specific artifact to its previous version (AD-164).

        Returns True if rollback succeeded, False if no history found.
        """
        file_path = self._artifact_path(artifact_type, identifier)
        if file_path is None:
            return False
        if not self._git_available or not self.repo_exists:
            return False

        rel_root = (
            self._resolved_repo_root()
            if artifact_type == "skill"
            else self._repo_path
        )
        rel_path = file_path.relative_to(rel_root).as_posix()

        # Get the last two commits affecting this file
        try:
            result = await self._git_run(
                "log", "--follow", "--format=%H", "-n", "2", "--", rel_path
            )
            commits = [c.strip() for c in result.stdout.strip().split("\n") if c.strip()]
        except Exception:
            log.debug("Git operation failed", exc_info=True)
            return False

        if len(commits) < 2:
            return False

        # Retrieve previous version
        prev_commit = commits[1]
        try:
            result = await self._git_run("show", f"{prev_commit}:{rel_path}")
            if result.returncode != 0:
                return False
            previous_content = result.stdout
        except Exception:
            log.debug("Git operation failed", exc_info=True)
            return False

        # Write the previous version
        if artifact_type == "skill":
            current_path = self._artifact_path(artifact_type, identifier)
            if current_path != file_path:
                raise ValueError(
                    "Persisted skill artifact path changed before rollback write"
                )
        file_path.write_text(previous_content, encoding="utf-8")
        await self._git_commit(f"Rollback {artifact_type}/{identifier} to {prev_commit[:8]}")
        return True

    async def artifact_history(
        self, artifact_type: str, identifier: str, limit: int = 10
    ) -> list[dict]:
        """Get commit history for a specific artifact.

        Returns [{commit_hash, timestamp, message}, ...].
        """
        file_path = self._artifact_path(artifact_type, identifier)
        if file_path is None:
            return []
        if not self._git_available or not self.repo_exists:
            return []

        rel_root = (
            self._resolved_repo_root()
            if artifact_type == "skill"
            else self._repo_path
        )
        rel_path = file_path.relative_to(rel_root).as_posix()
        try:
            result = await self._git_run(
                "log", "--follow", f"--format=%H|%aI|%s", f"-n{limit}",
                "--", rel_path,
            )
            if result.returncode != 0:
                return []

            entries: list[dict] = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("|", 2)
                if len(parts) == 3:
                    entries.append({
                        "commit_hash": parts[0],
                        "timestamp": parts[1],
                        "message": parts[2],
                    })
            return entries
        except Exception:
            log.debug("Git operation failed", exc_info=True)
            return []

    def _artifact_path(self, artifact_type: str, identifier: str) -> Path | None:
        """Resolve artifact type + identifier to a file path."""
        if artifact_type == "episode":
            return self._repo_path / "episodes" / f"{identifier}.json"
        elif artifact_type == "agent":
            return self._repo_path / "agents" / f"{identifier}.json"
        elif artifact_type == "skill":
            skill_name = validate_persisted_skill_name(identifier)
            return self._resolve_skill_paths(skill_name).descriptor
        elif artifact_type == "trust":
            return self._repo_path / "trust" / "snapshot.json"
        elif artifact_type == "routing":
            return self._repo_path / "routing" / "weights.json"
        elif artifact_type == "workflow":
            return self._repo_path / "workflows" / "cache.json"
        elif artifact_type == "qa":
            return self._repo_path / "qa" / f"{identifier}.json"
        return None

    # ------------------------------------------------------------------
    # Recent commit log (for /knowledge history)
    # ------------------------------------------------------------------

    async def recent_commits(self, limit: int = 20) -> list[dict]:
        """Get recent commit history for the whole repo."""
        if not self._git_available or not self.repo_exists:
            return []
        try:
            result = await self._git_run(
                "log", f"--format=%H|%aI|%s", f"-n{limit}",
            )
            if result.returncode != 0:
                return []
            entries: list[dict] = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("|", 2)
                if len(parts) == 3:
                    entries.append({
                        "commit_hash": parts[0],
                        "timestamp": parts[1],
                        "message": parts[2],
                    })
            return entries
        except Exception:
            log.debug("Git operation failed", exc_info=True)
            return []

    async def commit_count(self) -> int:
        """Get total number of commits."""
        if not self._git_available or not self.repo_exists:
            return 0
        try:
            result = await self._git_run("rev-list", "--count", "HEAD")
            return int(result.stdout.strip()) if result.returncode == 0 else 0
        except Exception:
            log.debug("Git operation failed", exc_info=True)
            return 0

    async def meta_info(self) -> dict | None:
        """Read meta.json if it exists."""
        meta_path = self._repo_path / "meta.json"
        if meta_path.is_file():
            return await self._read_json(meta_path)
        return None

    # ------------------------------------------------------------------
    # File I/O helpers
    # ------------------------------------------------------------------

    async def _write_json(self, path: Path, data: Any) -> None:
        """Write JSON data to file.  Creates parent dirs if needed."""
        path.parent.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: path.write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            ),
        )

    async def _read_json(self, path: Path) -> Any:
        """Read JSON data from file."""
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(
            None, lambda: path.read_text(encoding="utf-8")
        )
        return json.loads(text)
