# AD-434: Ship's Records — Git-Backed Instance Knowledge Store

## Overview

Ship's Records is ProbOS's Tier 2 knowledge system — structured documents that persist as institutional memory. Currently, duty output evaporates after one cognitive cycle. Agents recognize this gap (Ogawa: "no prescription history or treatment outcome data"; Bones: "flying without instruments"). This AD gives them somewhere to write.

## Architecture

**RecordsStore** — Ship's Computer infrastructure service (no identity, no personality). Manages a per-instance Git repository for structured document storage. Every write is a git commit. The git log IS the audit trail.

## File: `src/probos/knowledge/records_store.py` (NEW)

Create the core `RecordsStore` service class.

### RecordsConfig

Add to `src/probos/config.py` after the `KnowledgeConfig` class (around line 262):

```python
class RecordsConfig(BaseModel):
    """Ship's Records configuration."""
    enabled: bool = True
    repo_path: str = ""  # Empty = {data_dir}/ship-records/
    auto_commit: bool = True
    commit_debounce_seconds: float = 5.0
    max_episodes_per_hour: int = 20  # Rate limit for notebook writes
```

Add `records: RecordsConfig = RecordsConfig()` to `SystemConfig` (around line 398, after `knowledge`).

### RecordsStore Class

```python
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

    def __init__(self, config, ontology=None):
        self._config = config
        self._repo_path = Path(config.repo_path)
        self._ontology = ontology
        self._commit_lock = asyncio.Lock()
        self._pending_commits: list[str] = []
        self._commit_task: asyncio.Task | None = None

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
        frontmatter = {
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
        file_path = self._repo_path / path
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
        file_path = self._repo_path / path
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
        search_path = self._repo_path / directory if directory else self._repo_path
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
        file_path = self._repo_path / path
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
        dir_counts = {}
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
        loop = asyncio.get_event_loop()
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
```

**Key design decisions in the implementation:**
- Git operations use `subprocess.run` in a thread executor (same pattern as KnowledgeStore)
- Classification enforcement on `read_entry()` — private = author only, department = same dept, ship/fleet = all
- Captain's Log is append-only with daily files and timestamped entries
- `_parse_document()` handles YAML frontmatter extraction
- Search is keyword-based (semantic search handled by CodebaseIndex bridge, not RecordsStore)
- Stats endpoint for HXI dashboard integration

## File: `src/probos/config.py` (MODIFY)

1. Add `RecordsConfig` class after `KnowledgeConfig` (around line 262)
2. Add `records: RecordsConfig = RecordsConfig()` to `SystemConfig` (around line 398)

## File: `src/probos/runtime.py` (MODIFY)

### Declare placeholder (in `__init__`, around line 272)

Add `self._records_store: Any = None` alongside other service declarations.

Also add a property:
```python
@property
def records_store(self):
    return self._records_store
```

### Initialize in `start()` (after KnowledgeStore init, around line 1059)

Follow the KnowledgeStore initialization pattern:

```python
# Initialize Ship's Records (AD-434)
if self.config.records.enabled:
    try:
        from probos.knowledge.records_store import RecordsStore
        rcfg = self.config.records
        if not rcfg.repo_path:
            rcfg = rcfg.model_copy(update={"repo_path": str(self._data_dir / "ship-records")})
        self._records_store = RecordsStore(rcfg, ontology=getattr(self, '_ontology', None))
        await self._records_store.initialize()
        logger.info("ship-records started")
    except Exception as e:
        logger.warning("Ship's Records failed to start: %s — continuing without records", e)
        self._records_store = None
```

### Summary injection

In the runtime summary that gets injected into agent context (look for where Ship's Computer system summary is built), add a line about Ship's Records status:
```python
if self._records_store:
    stats = await self._records_store.get_stats()
    summary_parts.append(f"Ship's Records: {stats['total_documents']} documents, {stats['total_commits']} commits")
```

This is lower priority — add if you find the right injection point, skip if the pattern isn't clear.

## File: `src/probos/proactive.py` (MODIFY)

### Add `[NOTEBOOK]` tag handler

In `_extract_and_execute_actions()` (around line 716), after the existing `[ENDORSE]` and `[REPLY]` handlers, add a `[NOTEBOOK]` handler:

```python
# --- Notebook writes (AD-434) ---
notebook_pattern = r'\[NOTEBOOK\s+([\w-]+)\](.*?)\[/NOTEBOOK\]'
notebook_matches = re.findall(notebook_pattern, text, re.DOTALL)
for topic_slug, notebook_content in notebook_matches:
    notebook_content = notebook_content.strip()
    if not notebook_content or not self._runtime._records_store:
        continue
    try:
        callsign = agent.callsign if hasattr(agent, 'callsign') else agent.agent_type
        department = ""
        if self._runtime._ontology:
            dept = self._runtime._ontology.get_agent_department(agent.agent_type)
            if dept:
                department = dept.department_id if hasattr(dept, 'department_id') else str(dept)
        await self._runtime._records_store.write_notebook(
            callsign=callsign,
            topic_slug=topic_slug,
            content=notebook_content,
            department=department,
            tags=[topic_slug],
        )
        actions_executed.append({
            "type": "notebook_write",
            "topic": topic_slug,
            "callsign": callsign,
        })
        logger.info("Notebook entry written: %s/%s", callsign, topic_slug)
    except Exception as e:
        logger.warning("Notebook write failed for %s: %s", topic_slug, e)
    # Remove the tag from text so it doesn't appear in Ward Room post
    text = text.replace(f"[NOTEBOOK {topic_slug}]{notebook_content}[/NOTEBOOK]", "").strip()
```

### Update proactive system prompt

In the method that builds the proactive think prompt for agents (look for where the system message or user message is composed for `proactive_think` intents), add guidance about the `[NOTEBOOK]` tag. Find where other structured action tags like `[ENDORSE]` are documented in the prompt and add:

```
If your observation warrants detailed documentation beyond a brief Ward Room post,
wrap extended analysis in [NOTEBOOK topic-slug]...[/NOTEBOOK] tags.
This writes to your personal notebook in Ship's Records (AD-434).
Use for: research findings, pattern analysis, baseline readings, diagnostic reports.
```

Only add this if RecordsStore is available (check `self._runtime._records_store`).

## File: `src/probos/api.py` (MODIFY)

### Add REST endpoints

Add after the existing `/api/ontology/records` endpoint (around line 541). Follow the Ward Room endpoint pattern:

```python
# --- Ship's Records API (AD-434) ---

@app.get("/api/records/stats")
async def get_records_stats() -> Any:
    """Get Ship's Records repository statistics."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    return await runtime._records_store.get_stats()

@app.get("/api/records/documents")
async def list_records(
    directory: str = "",
    author: str = "",
    status: str = "",
    classification: str = "",
) -> Any:
    """List documents in Ship's Records."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    entries = await runtime._records_store.list_entries(
        directory=directory, author=author, status=status, classification=classification,
    )
    return {"documents": entries, "count": len(entries)}

@app.get("/api/records/documents/{path:path}")
async def read_record(path: str, reader: str = "captain") -> Any:
    """Read a specific document from Ship's Records."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    entry = await runtime._records_store.read_entry(path, reader_id=reader)
    if entry is None:
        return JSONResponse({"error": "Not found or access denied"}, status_code=404)
    return entry

@app.post("/api/records/captains-log")
async def post_captains_log(request: Request) -> Any:
    """Append a Captain's Log entry."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    body = await request.json()
    content = body.get("content", "")
    if not content:
        return JSONResponse({"error": "content required"}, status_code=400)
    path = await runtime._records_store.append_captains_log(content, body.get("message", ""))
    return {"path": path, "status": "appended"}

@app.get("/api/records/captains-log")
async def get_captains_log(limit: int = 7) -> Any:
    """Get recent Captain's Log entries."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    entries = await runtime._records_store.list_entries("captains-log")
    # Return most recent first
    entries.sort(key=lambda e: e.get("frontmatter", {}).get("created", ""), reverse=True)
    return {"entries": entries[:limit]}

@app.get("/api/records/notebooks/{callsign}")
async def list_notebook(callsign: str) -> Any:
    """List a crew member's notebook entries."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    entries = await runtime._records_store.list_entries(f"notebooks/{callsign}")
    return {"callsign": callsign, "entries": entries}

@app.post("/api/records/notebooks/{callsign}")
async def write_notebook_entry(callsign: str, request: Request) -> Any:
    """Write to a crew member's notebook."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    body = await request.json()
    topic = body.get("topic", "untitled")
    content = body.get("content", "")
    if not content:
        return JSONResponse({"error": "content required"}, status_code=400)
    path = await runtime._records_store.write_notebook(
        callsign=callsign,
        topic_slug=topic,
        content=content,
        department=body.get("department", ""),
        tags=body.get("tags", []),
        classification=body.get("classification", "department"),
    )
    return {"path": path, "status": "written"}

@app.get("/api/records/search")
async def search_records(q: str = "", scope: str = "ship") -> Any:
    """Search Ship's Records by keyword."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    if not q:
        return JSONResponse({"error": "query parameter 'q' required"}, status_code=400)
    results = await runtime._records_store.search(q, scope=scope)
    return {"query": q, "results": results, "count": len(results)}

@app.get("/api/records/history/{path:path}")
async def get_record_history(path: str, limit: int = 20) -> Any:
    """Get git history for a specific record."""
    if not runtime._records_store:
        return JSONResponse({"error": "Ship's Records not available"}, status_code=503)
    history = await runtime._records_store.get_history(path, limit=limit)
    return {"path": path, "history": history}
```

## Testing

Create `tests/test_records_store.py`:

### Unit tests for RecordsStore

1. **test_initialize_creates_repo** — Initialize RecordsStore, verify git repo + subdirectories created
2. **test_write_entry_creates_file_with_frontmatter** — Write an entry, read back, verify YAML frontmatter fields
3. **test_write_entry_commits_to_git** — Write an entry, verify git log shows the commit
4. **test_captains_log_append_only** — Append two entries to same day, verify both present, original unmodified
5. **test_captains_log_daily_files** — Verify daily file naming pattern
6. **test_write_notebook** — Write notebook entry, verify path is `notebooks/{callsign}/{topic}.md`
7. **test_read_entry_classification_private** — Private doc readable by author, denied for others
8. **test_read_entry_classification_department** — Department doc readable by same dept, denied for other dept
9. **test_read_entry_classification_ship** — Ship doc readable by all
10. **test_list_entries_with_filters** — List with author, status, tag filters
11. **test_list_entries_excludes_archived** — Entries in `_archived/` not returned
12. **test_publish_changes_status** — Publish a draft, verify status changed to "published"
13. **test_publish_permission_denied** — Non-author/non-captain cannot publish
14. **test_search_keyword** — Search returns matching documents ranked by relevance
15. **test_search_respects_classification** — Search with scope="department" doesn't return fleet docs
16. **test_get_history** — Write multiple versions, verify history returns commits
17. **test_get_stats** — Verify document counts and commit count
18. **test_parse_document_with_frontmatter** — Valid YAML frontmatter parsed correctly
19. **test_parse_document_without_frontmatter** — Plain markdown returns empty frontmatter
20. **test_duplicate_count_for_agent_removed** — (Meta-test) Verify no duplicate method definitions

### Integration test in existing test files

21. **test_runtime_starts_records_store** — Verify RecordsStore is initialized during runtime startup
22. **test_proactive_notebook_tag_extraction** — Proactive thought with `[NOTEBOOK topic]...[/NOTEBOOK]` creates a notebook entry

## Files Summary

| File | Action | Changes |
|------|--------|---------|
| `src/probos/knowledge/records_store.py` | CREATE | RecordsStore class (~350 lines) |
| `src/probos/config.py` | MODIFY | Add RecordsConfig, add to SystemConfig |
| `src/probos/runtime.py` | MODIFY | Declare, initialize, property for records_store |
| `src/probos/proactive.py` | MODIFY | `[NOTEBOOK]` tag handler + prompt guidance |
| `src/probos/api.py` | MODIFY | 9 REST endpoints under `/api/records/` |
| `tests/test_records_store.py` | CREATE | 22 tests |

## Acceptance Criteria

- [ ] `RecordsStore` service initializes git repo at `{data_dir}/ship-records/`
- [ ] Documents have YAML frontmatter (author, classification, status, department, topic, tags)
- [ ] Classification-based access control enforced on read
- [ ] Captain's Log: append-only, daily files, always ship-classified
- [ ] Agent notebooks: `notebooks/{callsign}/{topic}.md`
- [ ] `[NOTEBOOK topic]...[/NOTEBOOK]` tag works in proactive thoughts
- [ ] 9 REST API endpoints functional
- [ ] Git commit on every write (audit trail)
- [ ] Publish workflow (draft → published)
- [ ] Keyword search across records
- [ ] File history via git log
- [ ] Runtime starts RecordsStore alongside other services
- [ ] 22 tests passing
- [ ] Full test suite green
