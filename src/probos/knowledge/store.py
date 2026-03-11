"""Git-backed persistent knowledge repository (AD-159 through AD-169).

The KnowledgeStore manages a local directory of JSON and Python artifacts
organised into typed subdirectories.  Git integration (commits, rollback,
history) is layered on top of the file I/O primitives.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probos.config import KnowledgeConfig
from probos.types import Episode

log = logging.getLogger(__name__)

# Subdirectory names — one per artifact type (AD-160).
_SUBDIRS = ("episodes", "agents", "skills", "trust", "routing", "workflows", "qa")

_SCHEMA_VERSION = 1


class KnowledgeStore:
    """Git-backed persistent knowledge repository."""

    def __init__(self, config: KnowledgeConfig) -> None:
        self._config = config
        # Resolve repo path: empty → ~/.probos/knowledge/
        if config.repo_path:
            self._repo_path = Path(config.repo_path)
        else:
            self._repo_path = Path.home() / ".probos" / "knowledge"

        self._git_available: bool | None = None  # Lazy-checked
        self._repo_initialised: bool = False
        self._flushing: bool = False  # Guard against debounce/flush race (AD-161)
        self._pending_messages: list[str] = []
        self._commit_timer: asyncio.TimerHandle | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Ensure repo directory exists.  Git init on first write, not here (AD-159)."""
        self._repo_path.mkdir(parents=True, exist_ok=True)
        for sub in _SUBDIRS:
            (self._repo_path / sub).mkdir(exist_ok=True)

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
                ep = Episode(
                    id=data["id"],
                    timestamp=data.get("timestamp", 0.0),
                    user_input=data.get("user_input", ""),
                    dag_summary=data.get("dag_summary", {}),
                    outcomes=data.get("outcomes", []),
                    reflection=data.get("reflection"),
                    agent_ids=data.get("agent_ids", []),
                    duration_ms=data.get("duration_ms", 0.0),
                )
                episodes.append(ep)
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
            for fp in files[:excess]:
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

    async def store_skill(self, intent_name: str, source_code: str, descriptor: dict) -> None:
        """Write skill source to skills/{intent_name}.py and descriptor to skills/{intent_name}.json."""
        py_path = self._repo_path / "skills" / f"{intent_name}.py"
        json_path = self._repo_path / "skills" / f"{intent_name}.json"
        py_path.write_text(source_code, encoding="utf-8")
        await self._write_json(json_path, descriptor)
        await self._schedule_commit(f"Store skill {intent_name}")

    async def load_skills(self) -> list[tuple[str, str, dict]]:
        """Load all skills: (intent_name, source_code, descriptor_dict)."""
        skills_dir = self._repo_path / "skills"
        if not skills_dir.is_dir():
            return []

        results: list[tuple[str, str, dict]] = []
        for json_fp in skills_dir.glob("*.json"):
            intent_name = json_fp.stem
            py_fp = skills_dir / f"{intent_name}.py"
            if not py_fp.is_file():
                continue
            try:
                descriptor = await self._read_json(json_fp)
                source_code = py_fp.read_text(encoding="utf-8")
                results.append((intent_name, source_code, descriptor))
            except Exception as exc:
                log.warning("Failed to load skill %s: %s", intent_name, exc)
        return results

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
                log.warning("Could not determine Git version")

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
                lambda: asyncio.ensure_future(self._flush_pending()),
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
        """Run git add + commit in thread executor (AD-166)."""
        if not self._git_available:
            return

        try:
            await self._git_run("add", "-A")
            result = await self._git_run("commit", "-m", message, "--allow-empty")
            if result.returncode != 0 and "nothing to commit" not in result.stdout:
                log.warning("Git commit failed: %s", result.stderr.strip())
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
                text=True,
                timeout=30,
            ),
        )

    # ------------------------------------------------------------------
    # Rollback (Step 5)
    # ------------------------------------------------------------------

    async def rollback_artifact(self, artifact_type: str, identifier: str) -> bool:
        """Revert a specific artifact to its previous version (AD-164).

        Returns True if rollback succeeded, False if no history found.
        """
        if not self._git_available or not self.repo_exists:
            return False

        # Determine file path
        file_path = self._artifact_path(artifact_type, identifier)
        if file_path is None:
            return False

        rel_path = file_path.relative_to(self._repo_path).as_posix()

        # Get the last two commits affecting this file
        try:
            result = await self._git_run(
                "log", "--follow", "--format=%H", "-n", "2", "--", rel_path
            )
            commits = [c.strip() for c in result.stdout.strip().split("\n") if c.strip()]
        except Exception:
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
            return False

        # Write the previous version
        file_path.write_text(previous_content, encoding="utf-8")
        await self._git_commit(f"Rollback {artifact_type}/{identifier} to {prev_commit[:8]}")
        return True

    async def artifact_history(
        self, artifact_type: str, identifier: str, limit: int = 10
    ) -> list[dict]:
        """Get commit history for a specific artifact.

        Returns [{commit_hash, timestamp, message}, ...].
        """
        if not self._git_available or not self.repo_exists:
            return []

        file_path = self._artifact_path(artifact_type, identifier)
        if file_path is None:
            return []

        rel_path = file_path.relative_to(self._repo_path).as_posix()
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
            return []

    def _artifact_path(self, artifact_type: str, identifier: str) -> Path | None:
        """Resolve artifact type + identifier to a file path."""
        if artifact_type == "episode":
            return self._repo_path / "episodes" / f"{identifier}.json"
        elif artifact_type == "agent":
            return self._repo_path / "agents" / f"{identifier}.json"
        elif artifact_type == "skill":
            return self._repo_path / "skills" / f"{identifier}.json"
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
            return []

    async def commit_count(self) -> int:
        """Get total number of commits."""
        if not self._git_available or not self.repo_exists:
            return 0
        try:
            result = await self._git_run("rev-list", "--count", "HEAD")
            return int(result.stdout.strip()) if result.returncode == 0 else 0
        except Exception:
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
