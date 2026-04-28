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
    "bills",        # AD-618a: Standard Operating Procedures (raw YAML, not markdown)
    "_archived",
)

# Classification hierarchy (higher index = broader access)
_CLASSIFICATION_LEVELS = {
    "private": 0,
    "department": 1,
    "ship": 2,
    "fleet": 3,
}


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Word-level Jaccard similarity between two texts."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


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
        self._confidence_tracker: Any = None

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
        metrics: dict[str, Any] | None = None,  # AD-553
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

        # AD-550: Update-in-place — preserve created timestamp + track revision
        file_path = self._safe_path(path)
        if file_path.exists():
            try:
                existing_raw = file_path.read_text(encoding="utf-8")
                existing_fm, _ = self._parse_document(existing_raw)
                if "created" in existing_fm:
                    frontmatter["created"] = existing_fm["created"]
                existing_rev = existing_fm.get("revision", 1)
                frontmatter["revision"] = existing_rev + 1
            except Exception:
                logger.debug("AD-550: Could not read existing frontmatter for update-in-place", exc_info=True)

        if department:
            frontmatter["department"] = department
        if topic:
            frontmatter["topic"] = topic
        if tags:
            frontmatter["tags"] = tags

        # AD-553: Attach metrics snapshot
        if metrics:
            frontmatter["metrics"] = metrics

        # Compose full document
        fm_yaml = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
        full_content = f"---\n{fm_yaml}---\n\n{content}"

        # Write file
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(full_content, encoding="utf-8")

        # Git add + commit
        if self._config.auto_commit:
            await self._git("add", path)
            await self._commit(f"[records] {message} — by {author}")

        if self._confidence_tracker is not None:
            self._confidence_tracker.initialize_entry(path)

        logger.info("Record written: %s by %s (%s)", path, author, classification)
        return path

    def set_confidence_tracker(self, tracker: Any) -> None:
        """AD-444: Late-bind confidence tracker."""
        self._confidence_tracker = tracker

    async def confirm_entry(self, entry_path: str) -> float | None:
        """AD-444: Confirm an entry, increasing its confidence score."""
        if self._confidence_tracker is not None:
            return self._confidence_tracker.confirm(entry_path)
        return None

    async def contradict_entry(self, entry_path: str) -> float | None:
        """AD-444: Contradict an entry, decreasing its confidence score."""
        if self._confidence_tracker is not None:
            return self._confidence_tracker.contradict(entry_path)
        return None

    async def seed_manuals(self, source_dir: Path) -> int:
        """Seed manuals from source directory into ship-records/manuals/.

        BF-084: Copies markdown files from config/manuals/ to manuals/ with
        ship-classified frontmatter. Overwrites existing (shipyard-managed).
        Returns count of seeded manuals.
        """
        if not source_dir.is_dir():
            logger.info("BF-084: Manual source dir %s not found, skipping", source_dir)
            return 0

        count = 0
        for md_file in sorted(source_dir.glob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            path = f"manuals/{md_file.name}"
            await self.write_entry(
                author="shipyard",
                path=path,
                content=content,
                message=f"Seed manual: {md_file.stem}",
                classification="ship",
                status="published",
                topic=md_file.stem,
                tags=["manual"],
            )
            count += 1

        if count:
            logger.info("BF-084: Seeded %d manual(s) into Ship's Records", count)
        return count

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
        metrics: dict[str, Any] | None = None,  # AD-553
    ) -> str:
        """Write to an agent's notebook.

        Creates or updates notebooks/{callsign}/{topic_slug}.md
        """
        if not callsign or not callsign.strip():  # BF-218: guard against empty callsign
            raise ValueError("callsign must not be empty for notebook writes")
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
            metrics=metrics,
        )

    async def write_bill(
        self,
        bill_id: str,
        content: str,
        author: str = "captain",
        *,
        version: int = 1,
    ) -> str:
        """Write a Bill YAML file to Ship's Records (AD-618a).

        Bypasses write_entry() — bills are raw YAML, not markdown with
        frontmatter. write_entry() wraps content in ``---\\nfrontmatter\\n---``
        which would corrupt the bill YAML and make it unparseable by
        parse_bill_file(). Uses _safe_path() for traversal prevention,
        writes directly, then git add + commit.

        Args:
            bill_id: Unique bill identifier (slug, e.g. "research-consultation").
            content: Full YAML content of the bill. Not validated against the
                bill schema — callers should use parse_bill() first if they
                want pre-write validation. Raw write supports drafts and
                authoring workflows.
            author: Who authored this bill.
            version: Bill version number.

        Returns:
            Relative path of the created file.
        """
        filename = f"{bill_id}.bill.yaml"
        rel_path = f"bills/{filename}"

        file_path = self._safe_path(rel_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

        if self._config.auto_commit:
            await self._git("add", rel_path)
            await self._commit(
                f"[records] [bill] {bill_id} v{version} — authored by {author}"
            )

        logger.info("Bill written: %s by %s", rel_path, author)
        return rel_path

    async def list_bills(self) -> list[dict]:
        """List all Bill files in Ship's Records (AD-618a).

        Bypasses list_entries() — bills are .bill.yaml files, not .md.
        list_entries() uses rglob("*.md") which would never find them.

        Returns:
            List of dicts with 'path' and 'bill_id' keys for each bill.
        """
        bills_dir = self._safe_path("bills")
        if not bills_dir.exists():
            return []

        results = []
        for yaml_file in sorted(bills_dir.rglob("*.bill.yaml")):
            rel_path = str(yaml_file.relative_to(self._repo_path)).replace("\\", "/")
            # Extract bill_id from filename (e.g. "research-consultation.bill.yaml" → "research-consultation")
            bill_id = yaml_file.name.removesuffix(".bill.yaml")
            results.append({"path": rel_path, "bill_id": bill_id})

        return results

    async def check_notebook_similarity(
        self,
        callsign: str,
        topic_slug: str,
        new_content: str,
        *,
        similarity_threshold: float = 0.8,
        staleness_hours: float = 72.0,
        max_scan_entries: int = 20,
    ) -> dict:
        """AD-550: Check if a notebook write is redundant.

        Returns:
            {
                "action": "write" | "update" | "suppress",
                "reason": str,
                "existing_path": str | None,
                "existing_content": str | None,
                "similarity": float,
            }
        """
        no_match: dict[str, Any] = {
            "action": "write",
            "reason": "no_existing_entry",
            "existing_path": None,
            "existing_content": None,
            "similarity": 0.0,
            # AD-552: Frequency metadata
            "revision": 0,
            "created_iso": None,
            "updated_iso": None,
            # AD-553: Previous metrics for baseline delta
            "existing_metrics": {},
        }

        now = datetime.now(timezone.utc)
        staleness_cutoff = now.timestamp() - (staleness_hours * 3600)

        # --- Layer 2: Exact topic match ---
        exact_path = f"notebooks/{callsign}/{topic_slug}.md"
        exact_file = self._safe_path(exact_path)
        if exact_file.exists():
            try:
                raw = exact_file.read_text(encoding="utf-8")
                fm, existing_content = self._parse_document(raw)
                updated_str = fm.get("updated", "")
                entry_ts = 0.0
                if updated_str:
                    try:
                        entry_ts = datetime.fromisoformat(updated_str).timestamp()
                    except (ValueError, TypeError):
                        pass

                similarity = _jaccard_similarity(new_content, existing_content)

                # AD-552: Extract frequency metadata from frontmatter
                _revision = fm.get("revision", 1)
                _created_iso = fm.get("created", None)
                _updated_iso = fm.get("updated", None)
                # AD-553: Extract existing metrics for baseline delta
                _existing_metrics = fm.get("metrics", {})

                if entry_ts > staleness_cutoff and similarity >= similarity_threshold:
                    return {
                        "action": "suppress",
                        "reason": "content unchanged from recent entry",
                        "existing_path": exact_path,
                        "existing_content": existing_content,
                        "similarity": similarity,
                        "revision": _revision,
                        "created_iso": _created_iso,
                        "updated_iso": _updated_iso,
                        "existing_metrics": _existing_metrics,
                    }

                if entry_ts <= staleness_cutoff:
                    return {
                        "action": "update",
                        "reason": "stale entry, refreshing",
                        "existing_path": exact_path,
                        "existing_content": existing_content,
                        "similarity": similarity,
                        "revision": _revision,
                        "created_iso": _created_iso,
                        "updated_iso": _updated_iso,
                        "existing_metrics": _existing_metrics,
                    }

                # Fresh but different content → update
                return {
                    "action": "update",
                    "reason": "different content for same topic",
                    "existing_path": exact_path,
                    "existing_content": existing_content,
                    "similarity": similarity,
                    "revision": _revision,
                    "created_iso": _created_iso,
                    "updated_iso": _updated_iso,
                    "existing_metrics": _existing_metrics,
                }
            except Exception:
                logger.debug("AD-550: Error reading existing notebook entry", exc_info=True)

        # --- Layer 3: Cross-topic scan ---
        notebook_dir = self._repo_path / "notebooks" / callsign
        if notebook_dir.is_dir():
            try:
                entries: list[tuple[float, Path]] = []
                for md_file in notebook_dir.glob("*.md"):
                    if md_file.name == f"{topic_slug}.md":
                        continue  # Already checked above
                    try:
                        raw = md_file.read_text(encoding="utf-8")
                        fm, _ = self._parse_document(raw)
                        updated_str = fm.get("updated", "")
                        entry_ts = 0.0
                        if updated_str:
                            try:
                                entry_ts = datetime.fromisoformat(updated_str).timestamp()
                            except (ValueError, TypeError):
                                pass
                        if entry_ts > staleness_cutoff:
                            entries.append((entry_ts, md_file))
                    except Exception:
                        continue

                # Sort by recency, cap scan
                entries.sort(key=lambda x: x[0], reverse=True)
                for _, md_file in entries[:max_scan_entries]:
                    try:
                        raw = md_file.read_text(encoding="utf-8")
                        _, existing_content = self._parse_document(raw)
                        similarity = _jaccard_similarity(new_content, existing_content)
                        if similarity >= similarity_threshold:
                            matched_path = f"notebooks/{callsign}/{md_file.name}"
                            return {
                                "action": "suppress",
                                "reason": f"similar content exists at {matched_path}",
                                "existing_path": matched_path,
                                "existing_content": existing_content,
                                "similarity": similarity,
                            }
                    except Exception:
                        continue
            except Exception:
                logger.debug("AD-550: Cross-topic scan failed", exc_info=True)

        return no_match

    async def check_cross_agent_convergence(
        self,
        anchor_callsign: str,
        anchor_department: str,
        anchor_topic_slug: str,
        anchor_content: str,
        *,
        convergence_threshold: float = 0.5,
        divergence_threshold: float = 0.3,
        staleness_hours: float = 72.0,
        max_scan_per_agent: int = 5,
        min_convergence_agents: int = 2,
        min_convergence_departments: int = 2,
    ) -> dict[str, Any]:
        """AD-554: Incremental cross-agent convergence/divergence scan.

        Anchored on a just-written entry, scans recent notebooks from OTHER
        agents in OTHER departments for convergent or divergent conclusions.
        """
        result: dict[str, Any] = {
            "convergence_detected": False,
            "convergence_agents": [],
            "convergence_departments": [],
            "convergence_coherence": 0.0,
            "convergence_topic": "",
            "convergence_matches": [],
            "convergence_independence_score": 0.0,  # AD-583
            "convergence_is_independent": True,      # AD-583
            "divergence_detected": False,
            "divergence_agents": [],
            "divergence_departments": [],
            "divergence_topic": "",
            "divergence_similarity": 1.0,
            "divergence_matches": [],
        }

        notebooks_dir = self._repo_path / "notebooks"
        if not notebooks_dir.is_dir():
            return result

        now = datetime.now(timezone.utc)
        staleness_cutoff = now.timestamp() - (staleness_hours * 3600)

        convergence_matches: list[dict[str, Any]] = []
        divergence_matches: list[dict[str, Any]] = []

        # Scan other agents' notebook directories
        try:
            for agent_dir in sorted(notebooks_dir.iterdir()):
                if not agent_dir.is_dir():
                    continue
                other_callsign = agent_dir.name
                if other_callsign == anchor_callsign:
                    continue  # Skip self

                # Collect recent entries for this agent
                entries: list[tuple[float, Path, str, str]] = []  # (ts, path, topic, dept)
                for md_file in agent_dir.glob("*.md"):
                    try:
                        raw = md_file.read_text(encoding="utf-8")
                        fm, content = self._parse_document(raw)
                        updated_str = fm.get("updated", "")
                        entry_ts = 0.0
                        if updated_str:
                            try:
                                entry_ts = datetime.fromisoformat(updated_str).timestamp()
                            except (ValueError, TypeError):
                                pass
                        if entry_ts <= staleness_cutoff:
                            continue
                        dept = fm.get("department", "")
                        topic = fm.get("topic", md_file.stem)
                        entries.append((entry_ts, md_file, topic, dept))
                    except Exception:
                        continue

                # Sort by recency, cap scan
                entries.sort(key=lambda x: x[0], reverse=True)
                for _, md_file, topic, dept in entries[:max_scan_per_agent]:
                    try:
                        raw = md_file.read_text(encoding="utf-8")
                        fm, content = self._parse_document(raw)
                        similarity = _jaccard_similarity(anchor_content, content)
                        rel_path = f"notebooks/{other_callsign}/{md_file.name}"
                        match_info = {
                            "callsign": other_callsign,
                            "department": dept,
                            "topic_slug": topic,
                            "similarity": similarity,
                            "path": rel_path,
                            "content": content,
                            "frontmatter": fm,  # AD-583: preserved for anchor independence
                        }

                        # Convergence: high similarity from different department
                        if similarity >= convergence_threshold and dept and dept != anchor_department:
                            convergence_matches.append(match_info)

                        # Divergence: same topic, low similarity, different department
                        if (
                            topic == anchor_topic_slug
                            and similarity < divergence_threshold
                            and dept
                            and dept != anchor_department
                        ):
                            divergence_matches.append(match_info)
                    except Exception:
                        continue
        except Exception:
            logger.debug("AD-554: Cross-agent scan error", exc_info=True)
            return result

        # Evaluate convergence
        if convergence_matches:
            conv_agents = {anchor_callsign}
            conv_depts = {anchor_department}
            for m in convergence_matches:
                conv_agents.add(m["callsign"])
                conv_depts.add(m["department"])

            if len(conv_agents) >= min_convergence_agents and len(conv_depts) >= min_convergence_departments:
                # Compute coherence (average pairwise similarity among converging entries)
                similarities = [m["similarity"] for m in convergence_matches]
                coherence = sum(similarities) / len(similarities) if similarities else 0.0

                # Infer topic from common words
                from collections import Counter as _Counter
                all_words: list[str] = []
                all_words.extend(anchor_content.lower().split()[:50])
                for m in convergence_matches:
                    all_words.extend(m.get("content", "").lower().split()[:50])
                common = _Counter(all_words).most_common(3)
                topic = "-".join(w for w, _ in common) if common else anchor_topic_slug

                result["convergence_detected"] = True
                result["convergence_agents"] = sorted(conv_agents)
                result["convergence_departments"] = sorted(conv_depts)
                result["convergence_coherence"] = coherence
                result["convergence_topic"] = topic
                result["convergence_matches"] = [
                    {k: v for k, v in m.items() if k not in ("content", "frontmatter")}
                    for m in convergence_matches
                ]

                # AD-583: Compute anchor independence for converging entries
                try:
                    from types import SimpleNamespace
                    from probos.cognitive.social_verification import compute_anchor_independence

                    independence_threshold = convergence_threshold  # reuse param as fallback
                    try:
                        # Try to get config threshold
                        from probos.config import RecordsConfig as _RC583
                        _rc = _RC583()
                        independence_threshold = _rc.convergence_independence_threshold
                    except Exception:
                        independence_threshold = 0.3

                    episodes = []
                    for m in convergence_matches:
                        fm = m.get("frontmatter", {})
                        anchors = SimpleNamespace(
                            duty_cycle_id=fm.get("duty_cycle_id", ""),
                            channel_id=fm.get("channel_id", ""),
                            thread_id=fm.get("thread_id", ""),
                        )
                        ts = 0.0
                        updated_str = fm.get("updated", "")
                        if updated_str:
                            try:
                                ts = datetime.fromisoformat(updated_str).timestamp()
                            except (ValueError, TypeError):
                                pass
                        episodes.append(SimpleNamespace(anchors=anchors, timestamp=ts))

                    independence_score = compute_anchor_independence(episodes)
                    result["convergence_independence_score"] = independence_score
                    result["convergence_is_independent"] = independence_score >= independence_threshold
                except Exception:
                    # Non-critical — default to conservative (potentially pathological)
                    result["convergence_independence_score"] = 0.0
                    result["convergence_is_independent"] = False

        # Evaluate divergence
        if divergence_matches:
            div_agents = {anchor_callsign}
            div_depts = {anchor_department}
            lowest_sim = 1.0
            for m in divergence_matches:
                div_agents.add(m["callsign"])
                div_depts.add(m["department"])
                if m["similarity"] < lowest_sim:
                    lowest_sim = m["similarity"]

            result["divergence_detected"] = True
            result["divergence_agents"] = sorted(div_agents)
            result["divergence_departments"] = sorted(div_depts)
            result["divergence_topic"] = anchor_topic_slug
            result["divergence_similarity"] = lowest_sim
            result["divergence_matches"] = [
                {k: v for k, v in m.items() if k != "content"} for m in divergence_matches
            ]

        return result

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
                logger.debug("Skipping unreadable file", exc_info=True)
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
            logger.debug("Git query failed", exc_info=True)
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
                logger.debug("Skipping unreadable file", exc_info=True)
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
            logger.debug("Git query failed", exc_info=True)
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
