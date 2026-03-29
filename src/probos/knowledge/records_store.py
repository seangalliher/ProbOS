"""Ship's Records — Git-backed instance knowledge store (AD-434)."""

import asyncio
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Directory structure per AD-434 design
_SUBDIRS = (
    "captains-log",
    "notebooks",
    "reports",
    "duty-logs",
    "operations",
    "manuals",
    "_archived",
)

# Classification hierarchy (higher index = broader access)
_CLASSIFICATION_LEVELS = {
    "private": 0,
    "department": 1,
    "ship": 2,
    "fleet": 3,
}


class RecordsStore:
    """Git-backed institutional knowledge store for a ProbOS instance.

    Every document has YAML frontmatter with author, classification, status,
    department, topic, tags. Every write is a git commit. Git log = audit trail.
    """

    def __init__(self, config: Any, ontology: Any = None):
        self._config = config
        self._repo_path = Path(config.repo_path)
        self._ontology = ontology
        self._commit_lock = asyncio.Lock()
        self._pending_commits: list[str] = []
        self._commit_task: asyncio.Task | None = None

    @property
    def repo_path(self) -> Path:
        return self._repo_path

    async def initialize(self) -> None:
        """Initialize the records repository. Creates dir + git init if needed."""
        self._repo_path.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        for subdir in _SUBDIRS:
            (self._repo_path / subdir).mkdir(exist_ok=True)

        # Git init if not already a repo
        git_dir = self._repo_path / ".git"
        if not git_dir.exists():
            await self._git("init")
            # Configure local git identity for this repo
            await self._git("config", "user.email", "records@probos.local")
            await self._git("config", "user.name", "Ship Records")
            # Create .shiprecords.yaml config
            await self._write_config()
            await self._git("add", ".shiprecords.yaml")
            await self._git("commit", "-m", "Ship's Records initialized")
            logger.info("Ship's Records initialized: %s", self._repo_path)
        else:
            logger.info("Ship's Records loaded: %s", self._repo_path)

    async def write_entry(
        self,
        author: str,
        path: str,
        content: str,
        message: str,
        *,
        classification: str = "ship",
        status: str = "draft",
        department: str = "",
        topic: str = "",
        tags: list[str] | None = None,
    ) -> str:
        """Write a document to Ship's Records.

        Generates YAML frontmatter, writes file, git add + commit.
        Returns the relative path of the created file.
        """
        # Validate classification
        if classification not in _CLASSIFICATION_LEVELS:
            raise ValueError(f"Invalid classification: {classification}")

        # Build frontmatter
        now = datetime.now(timezone.utc).isoformat()
        frontmatter: dict[str, Any] = {
            "author": author,
            "classification": classification,
            "status": status,
            "created": now,
            "updated": now,
        }
        if department:
            frontmatter["department"] = department
        if topic:
            frontmatter["topic"] = topic
        if tags:
            frontmatter["tags"] = tags

        # Compose full document
        fm_yaml = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
        full_content = f"---\n{fm_yaml}---\n\n{content}"

        # Write file
        file_path = self._safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(full_content, encoding="utf-8")

        # Git add + commit
        if self._config.auto_commit:
            await self._git("add", path)
            await self._commit(f"[records] {message} — by {author}")

        logger.info("Record written: %s by %s (%s)", path, author, classification)
        return path

    async def append_captains_log(self, content: str, message: str = "") -> str:
        """Append an entry to the Captain's Log.

        Append-only, daily files, always ship-classified.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = f"captains-log/{today}.md"
        file_path = self._repo_path / path

        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        entry = f"\n### {timestamp}\n\n{content}\n"

        if file_path.exists():
            # Append to existing daily file
            existing = file_path.read_text(encoding="utf-8")
            file_path.write_text(existing + entry, encoding="utf-8")
        else:
            # New daily file with frontmatter
            frontmatter = {
                "author": "captain",
                "classification": "ship",
                "status": "published",
                "created": datetime.now(timezone.utc).isoformat(),
            }
            fm_yaml = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(f"---\n{fm_yaml}---\n\n# Captain's Log — {today}\n{entry}", encoding="utf-8")

        if self._config.auto_commit:
            await self._git("add", path)
            await self._commit(message or f"[captains-log] Entry for {today}")

        logger.info("Captain's Log entry appended: %s", path)
        return path

    async def write_notebook(
        self,
        callsign: str,
        topic_slug: str,
        content: str,
        *,
        department: str = "",
        tags: list[str] | None = None,
        classification: str = "department",
    ) -> str:
        """Write to an agent's notebook.

        Creates or updates notebooks/{callsign}/{topic_slug}.md
        """
        path = f"notebooks/{callsign}/{topic_slug}.md"
        self._safe_path(path)  # Validate before delegating to write_entry
        return await self.write_entry(
            author=callsign,
            path=path,
            content=content,
            message=f"{callsign} notebook: {topic_slug}",
            classification=classification,
            status="draft",
            department=department,
            topic=topic_slug,
            tags=tags,
        )

    async def read_entry(
        self,
        path: str,
        reader_id: str,
        reader_department: str = "",
    ) -> dict | None:
        """Read a document, enforcing classification access control.

        Returns {"frontmatter": {...}, "content": "..."} or None if denied.
        """
        file_path = self._safe_path(path)
        if not file_path.exists():
            return None

        raw = file_path.read_text(encoding="utf-8")
        frontmatter, content = self._parse_document(raw)

        # Classification check
        doc_class = frontmatter.get("classification", "ship")
        doc_author = frontmatter.get("author", "")
        doc_dept = frontmatter.get("department", "")

        if doc_class == "private" and reader_id != doc_author:
            return None
        if doc_class == "department" and reader_department != doc_dept and reader_id != doc_author:
            return None
        # ship and fleet are readable by all crew

        return {"frontmatter": frontmatter, "content": content, "path": path}

    async def list_entries(
        self,
        directory: str = "",
        *,
        author: str = "",
        status: str = "",
        tags: list[str] | None = None,
        classification: str = "",
    ) -> list[dict]:
        """List documents with optional filters.

        Returns list of {"path": ..., "frontmatter": {...}} dicts.
        """
        search_path = self._safe_path(directory) if directory else self._repo_path
        results = []

        for md_file in sorted(search_path.rglob("*.md")):
            rel_path = str(md_file.relative_to(self._repo_path)).replace("\\", "/")
            # Skip archived
            if rel_path.startswith("_archived/"):
                continue
            try:
                raw = md_file.read_text(encoding="utf-8")
                fm, _ = self._parse_document(raw)
            except Exception:
                continue

            # Apply filters
            if author and fm.get("author") != author:
                continue
            if status and fm.get("status") != status:
                continue
            if classification and fm.get("classification") != classification:
                continue
            if tags and not set(tags).issubset(set(fm.get("tags", []))):
                continue

            results.append({"path": rel_path, "frontmatter": fm})

        return results

    async def get_history(self, path: str, limit: int = 20) -> list[dict]:
        """Get git log for a specific file."""
        self._safe_path(path)  # Validate — raises ValueError if traversal
        try:
            result = await self._git(
                "log", f"--max-count={limit}",
                "--format=%H|%aI|%s", "--follow", "--", path
            )
            entries = []
            for line in result.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("|", 2)
                if len(parts) == 3:
                    entries.append({
                        "commit": parts[0],
                        "timestamp": parts[1],
                        "message": parts[2],
                    })
            return entries
        except Exception:
            return []

    async def publish(self, path: str, author: str) -> None:
        """Promote a document from draft to published status."""
        file_path = self._safe_path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Record not found: {path}")

        raw = file_path.read_text(encoding="utf-8")
        fm, content = self._parse_document(raw)

        if fm.get("author") != author and author != "captain":
            raise PermissionError("Only the author or Captain can publish")

        fm["status"] = "published"
        fm["updated"] = datetime.now(timezone.utc).isoformat()

        fm_yaml = yaml.dump(fm, default_flow_style=False, sort_keys=False)
        file_path.write_text(f"---\n{fm_yaml}---\n\n{content}", encoding="utf-8")

        if self._config.auto_commit:
            await self._git("add", path)
            await self._commit(f"[records] Published: {path} — by {author}")

    async def search(self, query: str, scope: str = "ship") -> list[dict]:
        """Keyword search across records.

        Simple word-matching against frontmatter fields and content.
        """
        query_words = set(query.lower().split())
        results = []
        for md_file in sorted(self._repo_path.rglob("*.md")):
            rel_path = str(md_file.relative_to(self._repo_path)).replace("\\", "/")
            if rel_path.startswith("_archived/"):
                continue
            try:
                raw = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            # Simple keyword match
            raw_lower = raw.lower()
            matches = sum(1 for w in query_words if w in raw_lower)
            if matches > 0:
                fm, content_text = self._parse_document(raw)
                # Classification scope check
                doc_class = fm.get("classification", "ship")
                if _CLASSIFICATION_LEVELS.get(doc_class, 0) > _CLASSIFICATION_LEVELS.get(scope, 2):
                    continue
                results.append({
                    "path": rel_path,
                    "frontmatter": fm,
                    "score": matches / len(query_words) if query_words else 0,
                    "snippet": content_text[:200],
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:20]

    async def get_stats(self) -> dict:
        """Get repository statistics."""
        doc_count = sum(1 for _ in self._repo_path.rglob("*.md"))
        try:
            commit_count_str = await self._git("rev-list", "--count", "HEAD")
            commit_count = int(commit_count_str.strip())
        except Exception:
            commit_count = 0

        # Count by directory
        dir_counts: dict[str, int] = {}
        for subdir in _SUBDIRS:
            if subdir.startswith("_"):
                continue
            subdir_path = self._repo_path / subdir
            if subdir_path.exists():
                dir_counts[subdir] = sum(1 for _ in subdir_path.rglob("*.md"))

        return {
            "total_documents": doc_count,
            "total_commits": commit_count,
            "repo_path": str(self._repo_path),
            "directories": dir_counts,
        }

    # --- Internal helpers ---

    def _parse_document(self, raw: str) -> tuple[dict, str]:
        """Parse YAML frontmatter + content from a markdown document."""
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                try:
                    fm = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError:
                    fm = {}
                return fm, parts[2].strip()
        return {}, raw

    def _safe_path(self, user_path: str) -> Path:
        """Validate and resolve a user-supplied path, preventing traversal.

        Raises ValueError if the resolved path escapes the records repo.
        """
        resolved = (self._repo_path / user_path).resolve()
        repo_resolved = self._repo_path.resolve()

        if not resolved.is_relative_to(repo_resolved):
            raise ValueError(f"Path traversal denied: {user_path!r}")

        return resolved

    async def _write_config(self) -> None:
        """Write the .shiprecords.yaml configuration file."""
        config = {
            "version": "1.0",
            "retention_policies": {
                "captains_log": "permanent",
                "published_reports": "permanent",
                "active_notebooks": "archive_90_days_inactive",
                "draft_notebooks": "archive_365_days",
                "operations": "until_superseded",
            },
            "classification_default": "department",
        }
        config_path = self._repo_path / ".shiprecords.yaml"
        config_path.write_text(
            yaml.dump(config, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    async def _git(self, *args: str) -> str:
        """Run a git command in the records repo."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._git_sync, args)

    def _git_sync(self, args: tuple[str, ...]) -> str:
        """Synchronous git execution."""
        result = subprocess.run(
            ["git"] + list(args),
            cwd=str(self._repo_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            if result.stderr.strip():
                logger.debug("git %s stderr: %s", args[0], result.stderr.strip())
        return result.stdout

    async def _commit(self, message: str) -> None:
        """Debounced git commit."""
        if not self._config.auto_commit:
            return
        async with self._commit_lock:
            try:
                await self._git("commit", "-m", message, "--allow-empty-message")
            except Exception as e:
                logger.debug("Git commit skipped: %s", e)
