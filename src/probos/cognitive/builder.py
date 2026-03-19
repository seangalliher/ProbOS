"""BuilderAgent — code generation via LLM with Captain approval (AD-302/303).

A CognitiveAgent in the Engineering team that accepts structured build specs,
generates code via the deep LLM tier, parses file changes from the LLM output,
and returns them for Captain approval.  After approval, `execute_approved_build()`
orchestrates: git branch → write files → pytest → commit → return to main.
"""

from __future__ import annotations

import asyncio
import ast
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentDescriptor, LLMRequest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes (AD-302)
# ---------------------------------------------------------------------------

@dataclass
class BuildSpec:
    """A structured specification for a code change."""

    title: str
    description: str
    target_files: list[str] = field(default_factory=list)
    reference_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    ad_number: int = 0
    branch_name: str = ""
    constraints: list[str] = field(default_factory=list)


@dataclass
class BuildResult:
    """Result of a builder agent execution."""

    success: bool
    spec: BuildSpec
    files_written: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    test_result: str = ""
    tests_passed: bool = False
    branch_name: str = ""
    commit_hash: str = ""
    error: str = ""
    llm_output: str = ""
    fix_attempts: int = 0


# ---------------------------------------------------------------------------
# Git helpers (AD-303) — async only, no subprocess import
# ---------------------------------------------------------------------------

def _sanitize_branch_name(name: str) -> str:
    """Lowercase, alphanum + hyphens, max 50 chars."""
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return slug[:50]


async def _run_git(args: list[str], work_dir: str) -> tuple[int, str, str]:
    """Run a git command asynchronously.  Returns (returncode, stdout, stderr).

    Uses subprocess.run in a thread executor for Windows compatibility —
    asyncio.create_subprocess_exec requires ProactorEventLoop which
    uvicorn/FastAPI may not provide.
    """

    def _sync_run() -> tuple[int, str, str]:
        result = subprocess.run(
            ["git", *args],
            cwd=work_dir,
            capture_output=True,
        )
        return (
            result.returncode,
            (result.stdout or b"").decode(errors="replace").strip(),
            (result.stderr or b"").decode(errors="replace").strip(),
        )

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync_run)


async def _git_current_branch(work_dir: str) -> str:
    """Return the name of the current branch."""
    rc, out, _err = await _run_git(["rev-parse", "--abbrev-ref", "HEAD"], work_dir)
    return out if rc == 0 else "main"


async def _git_create_branch(branch_name: str, work_dir: str) -> tuple[bool, str]:
    """Create and checkout a new git branch.  Returns (success, message)."""
    safe = _sanitize_branch_name(branch_name)
    rc, out, err = await _run_git(["checkout", "-b", safe], work_dir)
    if rc != 0:
        return False, err or out
    return True, safe


async def _git_add_and_commit(
    files: list[str], message: str, work_dir: str,
) -> tuple[bool, str]:
    """Stage *files* and commit.  Returns (success, commit_hash_or_error)."""
    rc, _out, err = await _run_git(["add", *files], work_dir)
    if rc != 0:
        return False, err

    rc, out, err = await _run_git(["commit", "-m", message], work_dir)
    if rc != 0:
        return False, err or out

    # Get commit hash
    rc2, sha, _ = await _run_git(["rev-parse", "--short", "HEAD"], work_dir)
    return True, sha if rc2 == 0 else "unknown"


async def _git_checkout_main(work_dir: str) -> tuple[bool, str]:
    """Switch back to main branch.  Returns (success, message)."""
    rc, out, err = await _run_git(["checkout", "main"], work_dir)
    if rc != 0:
        return False, err or out
    return True, "switched to main"


# ---------------------------------------------------------------------------
# BuilderAgent (AD-302)
# ---------------------------------------------------------------------------

class BuilderAgent(CognitiveAgent):
    """Engineering agent that generates code from build specifications."""

    agent_type = "builder"
    tier = "domain"
    _handled_intents = {"build_code"}
    intent_descriptors = [
        IntentDescriptor(
            name="build_code",
            params={
                "title": "Short title for the code change",
                "description": "Detailed specification of what to build",
            },
            description=(
                "Generate code changes from a build specification. "
                "Creates a git branch, writes code, runs tests, and "
                "presents results for Captain approval."
            ),
            requires_consensus=True,
            requires_reflect=False,
            tier="domain",
        ),
    ]

    instructions = """You are the Builder Agent for ProbOS, a probabilistic agent-native OS.
Your job is to execute code changes based on build specifications.

When given a build spec:
1. Read the reference files to understand the existing code patterns
2. Plan the changes needed to fulfill the specification
3. Generate the code for EACH target file, following existing patterns exactly
4. Generate test code for the test files specified
5. Present the complete set of file changes

IMPORTANT RULES:
- Follow existing code patterns in the codebase exactly (imports, naming, style)
- Every public function/method needs a test
- Use the same typing patterns as existing code (from __future__ import annotations, etc.)
- Do NOT add features beyond what the spec requests
- Do NOT modify files that aren't listed in target_files or test_files
- Include the AD number in code comments where relevant

OUTPUT FORMAT:
For each file, output a block like:
===FILE: path/to/file.py===
<complete file contents or changes>
===END FILE===

If modifying an existing file, use SEARCH/REPLACE blocks to specify exact changes.
Each SEARCH block must match existing code EXACTLY (including whitespace and indentation).
Multiple changes to the same file go in a single MODIFY block:

===MODIFY: path/to/file.py===
===SEARCH===
<exact existing code to find>
===REPLACE===
<replacement code>
===END REPLACE===
===END MODIFY===

Rules for MODIFY blocks:
- The SEARCH text must match EXACTLY — copy it character-for-character from the reference code
- Keep SEARCH blocks as small as possible — just enough context to be unique
- Order SEARCH/REPLACE pairs from top to bottom in the file
- For new imports, SEARCH for the last existing import line and REPLACE with it plus the new one
- For adding a new method to a class, SEARCH for the preceding method's last line and REPLACE with that line plus the new method
"""

    # -- tier override --------------------------------------------------------

    def _resolve_tier(self) -> str:
        """Builder uses deep tier for code generation quality."""
        return "deep"

    # -- lifecycle overrides --------------------------------------------------

    # Context threshold: if total file content exceeds this, use fast-tier
    # localization to select relevant sections instead of sending everything.
    _LOCALIZE_THRESHOLD: int = 20_000  # chars — ~500 lines of code

    @staticmethod
    def _build_file_outline(content: str, path: str) -> str:
        """Build a compact AST outline of a Python file with line numbers.

        Shows class definitions, method signatures, and important assignments
        so the localization LLM can identify which sections to read in full.
        """
        lines = content.split("\n")
        line_count = len(lines)
        header = f"{path} ({line_count} lines):"

        if not path.endswith(".py"):
            # Non-Python: just show line count and first/last few lines
            preview = lines[:5] + ["  ..."] + lines[-5:] if line_count > 15 else lines
            return header + "\n" + "\n".join(f"  L{i+1}: {l}" for i, l in enumerate(preview))

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return header + "\n  (syntax error — cannot outline)"

        parts = [header]

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import | ast.ImportFrom):
                continue  # Skip individual imports — too noisy

            if isinstance(node, ast.ClassDef):
                parts.append(f"  L{node.lineno}: class {node.name}:")
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        args = ", ".join(a.arg for a in child.args.args)
                        prefix = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                        parts.append(f"    L{child.lineno}: {prefix} {child.name}({args})")
                    elif isinstance(child, ast.Assign):
                        for target in child.targets:
                            if isinstance(target, ast.Name):
                                parts.append(f"    L{child.lineno}: {target.id} = ...")

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = ", ".join(a.arg for a in node.args.args)
                prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
                parts.append(f"  L{node.lineno}: {prefix} {node.name}({args})")

            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        parts.append(f"  L{node.lineno}: {target.id} = ...")

        return "\n".join(parts)

    async def _localize_context(
        self,
        description: str,
        title: str,
        all_files: dict[str, str],
        target_paths: list[str],
    ) -> dict[str, str]:
        """Use fast-tier LLM to select relevant sections from large files.

        Returns a dict of path -> selected content (only relevant sections).
        Falls back to head+tail truncation if localization fails.
        """
        # Build outlines for all files
        outlines = "\n\n".join(
            self._build_file_outline(content, path)
            for path, content in all_files.items()
        )

        localize_prompt = (
            f"# Task: Identify code sections needed for this build\n\n"
            f"## Build: {title}\n{description}\n\n"
            f"## File Outlines\n{outlines}\n\n"
            f"## Instructions\n"
            f"For each file, list the line ranges needed to implement this build.\n"
            f"Include:\n"
            f"- Lines 1-20 (imports) for every file\n"
            f"- Class/dict definitions that need modification\n"
            f"- The area where new code should be inserted (include the method BEFORE and AFTER)\n"
            f"- Any related methods referenced in the description\n"
            f"- Add 5 lines of buffer above and below each range\n\n"
            f"Respond with ONLY a JSON object, no markdown fences:\n"
            f'{{"sections": {{"path/to/file.py": [[start, end], [start2, end2]], ...}}}}'
        )

        try:
            request = LLMRequest(
                prompt=localize_prompt,
                system_prompt="You identify relevant code sections. Return only JSON.",
                tier="fast",
                temperature=0.0,
            )
            response = await self._llm_client.complete(request)

            if response.error:
                logger.warning("Builder localize: LLM error, falling back to truncation: %s", response.error)
                return self._fallback_truncate(all_files)

            # Parse JSON response
            import json
            text = response.content.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text
                text = text.rsplit("```", 1)[0] if "```" in text else text
                text = text.strip()

            data = json.loads(text)
            sections = data.get("sections", {})
            logger.info("Builder localize: got sections for %d files", len(sections))

        except Exception as exc:
            logger.warning("Builder localize: failed (%s), falling back to truncation", exc)
            return self._fallback_truncate(all_files)

        # Extract selected line ranges from each file
        result: dict[str, str] = {}
        for path, content in all_files.items():
            file_lines = content.split("\n")
            ranges = sections.get(path)

            if not ranges:
                # File not mentioned by localizer — include first 100 lines as context
                selected = file_lines[:100]
                if len(file_lines) > 100:
                    selected.append(f"  ... [{len(file_lines) - 100} more lines] ...")
                result[path] = "\n".join(selected)
                continue

            # Merge and extract ranges
            selected_parts: list[str] = []
            last_end = 0
            for r in sorted(ranges):
                start = max(1, int(r[0])) - 1  # 0-indexed
                end = min(len(file_lines), int(r[1]))
                if start > last_end + 1:
                    selected_parts.append(f"\n  ... [lines {last_end + 1}-{start} omitted] ...\n")
                selected_parts.append("\n".join(file_lines[start:end]))
                last_end = end

            if last_end < len(file_lines):
                selected_parts.append(f"\n  ... [lines {last_end + 1}-{len(file_lines)} omitted] ...")

            result[path] = "\n".join(selected_parts)
            logger.info(
                "Builder localize: %s — %d ranges, %d/%d lines selected",
                path, len(ranges),
                sum(min(len(file_lines), int(r[1])) - max(0, int(r[0]) - 1) for r in ranges),
                len(file_lines),
            )

        return result

    @staticmethod
    def _fallback_truncate(all_files: dict[str, str]) -> dict[str, str]:
        """Fallback: keep first and last sections of each file."""
        result: dict[str, str] = {}
        for path, content in all_files.items():
            if len(content) <= 15_000:
                result[path] = content
            else:
                lines = content.split("\n")
                head = "\n".join(lines[:200])
                tail = "\n".join(lines[-200:])
                result[path] = (
                    head
                    + f"\n\n  ... [{len(lines) - 400} lines omitted] ...\n\n"
                    + tail
                )
        return result

    async def perceive(self, intent: Any) -> dict:
        """Read reference files and build context for the LLM.

        If total file content exceeds _LOCALIZE_THRESHOLD, uses a fast-tier
        LLM call to identify which sections are relevant, then reads only those.
        """
        obs = await super().perceive(intent)

        # Resolve project root for relative paths (same as execute_approved_build)
        project_root = Path(__file__).resolve().parent.parent.parent

        params = obs.get("params", {})
        reference_files = params.get("reference_files", [])
        target_files = params.get("target_files", [])

        # Step 1: Read all files fully
        all_files: dict[str, str] = {}
        is_target: set[str] = set(target_files)

        for file_path in target_files + reference_files:
            if file_path in all_files:
                continue  # Already read (might be in both lists)
            try:
                full_path = Path(file_path)
                if not full_path.is_absolute():
                    full_path = project_root / file_path
                if full_path.exists() and full_path.is_file():
                    all_files[file_path] = full_path.read_text(encoding="utf-8")
                    logger.info("Builder perceive: read %s (%d chars)", file_path, len(all_files[file_path]))
                else:
                    if file_path in is_target:
                        all_files[file_path] = ""  # New file to create
                        logger.info("Builder perceive: target %s does not exist (new file)", file_path)
                    else:
                        logger.warning("Builder perceive: file not found: %s (resolved: %s)", file_path, full_path)
            except Exception as exc:
                logger.warning("Builder perceive: error reading %s: %s", file_path, exc)

        total_size = sum(len(c) for c in all_files.values())
        logger.info("Builder perceive: %d files, %d total chars", len(all_files), total_size)

        # Step 2: If files are large, use localization to select relevant sections
        if total_size > self._LOCALIZE_THRESHOLD:
            logger.info("Builder perceive: total %d > threshold %d, running localization", total_size, self._LOCALIZE_THRESHOLD)
            localized = await self._localize_context(
                description=params.get("description", ""),
                title=params.get("title", ""),
                all_files=all_files,
                target_paths=target_files,
            )
            # Replace full content with localized content
            all_files = localized

        # Step 3: Build context strings
        target_contexts: list[str] = []
        file_contexts: list[str] = []
        for file_path, content in all_files.items():
            if not content and file_path in is_target:
                target_contexts.append(
                    f"=== {file_path} (TARGET — new file, does not exist yet) ===\n"
                )
            elif file_path in is_target:
                target_contexts.append(
                    f"=== {file_path} (TARGET — will be modified) ===\n{content}\n"
                )
            else:
                file_contexts.append(f"=== {file_path} ===\n{content}\n")

        obs["file_context"] = "\n".join(file_contexts)
        obs["target_context"] = "\n".join(target_contexts)

        total_context = len(obs["file_context"]) + len(obs["target_context"])
        logger.info("Builder perceive: final context = %d chars", total_context)

        return obs

    def _build_user_message(self, observation: dict) -> str:
        """Format the build spec and reference files into an LLM prompt."""
        params = observation.get("params", {})
        title = params.get("title", "Untitled")
        description = params.get("description", "")
        target_files = params.get("target_files", [])
        test_files = params.get("test_files", [])
        constraints = params.get("constraints", [])
        ad_number = params.get("ad_number", 0)
        file_context = observation.get("file_context", "")
        target_context = observation.get("target_context", "")

        parts = [
            f"# Build Spec: {title}",
            f"AD Number: AD-{ad_number}" if ad_number else "",
            f"\n## Description\n{description}",
        ]

        if target_files:
            parts.append("\n## Target Files\n" + "\n".join(f"- {f}" for f in target_files))
        if test_files:
            parts.append("\n## Test Files\n" + "\n".join(f"- {f}" for f in test_files))
        if constraints:
            parts.append("\n## Constraints\n" + "\n".join(f"- {c}" for c in constraints))
        if target_context:
            parts.append(
                f"\n## Target Files (current content — use MODIFY blocks for changes)\n{target_context}"
            )
        if file_context:
            parts.append(f"\n## Reference Code\n{file_context}")

        return "\n".join(p for p in parts if p)

    async def act(self, decision: dict) -> dict:
        """Parse LLM output into file blocks — does NOT write files."""
        if decision.get("action") == "error":
            logger.warning("Builder act: LLM returned error: %s", decision.get("reason"))
            return {"success": False, "error": decision.get("reason")}

        llm_output = decision.get("llm_output", "")
        logger.info("Builder act: LLM output length = %d chars", len(llm_output))
        if llm_output:
            logger.debug("Builder act: LLM output first 500 chars:\n%s", llm_output[:500])

        file_changes = self._parse_file_blocks(llm_output)
        if not file_changes:
            # Log enough to diagnose why parsing failed
            logger.warning(
                "Builder act: no file blocks parsed. Output length=%d, "
                "contains ===FILE: %s, contains ===MODIFY: %s, first 300 chars: %s",
                len(llm_output),
                "===FILE:" in llm_output,
                "===MODIFY:" in llm_output,
                llm_output[:300],
            )
            return {
                "success": False,
                "error": "LLM output contained no file blocks",
                "llm_output": llm_output,
            }

        return {
            "success": True,
            "result": {
                "file_changes": file_changes,
                "llm_output": llm_output,
                "change_count": len(file_changes),
            },
        }

    # -- file-block parser ----------------------------------------------------

    @staticmethod
    def _parse_file_blocks(text: str) -> list[dict[str, Any]]:
        """Extract file paths and content from ===FILE:=== and ===MODIFY:=== markers."""
        blocks: list[dict[str, Any]] = []

        # Pattern for ===FILE: path=== ... ===END FILE===
        for m in re.finditer(
            r"===FILE:\s*(.+?)===\s*\n(.*?)===END FILE===",
            text,
            re.DOTALL,
        ):
            blocks.append({
                "path": m.group(1).strip(),
                "content": m.group(2).strip() + "\n",
                "mode": "create",
                "after_line": None,
            })

        # Pattern for ===MODIFY: path=== ... ===END MODIFY===
        for m in re.finditer(
            r"===MODIFY:\s*(.+?)===\s*\n(.*?)===END MODIFY===",
            text,
            re.DOTALL,
        ):
            body = m.group(2)

            # Check for deprecated ===AFTER LINE:=== format
            if "===AFTER LINE:" in body:
                logger.warning(
                    "BuilderAgent: deprecated ===AFTER LINE:=== format in "
                    "MODIFY block for %s, skipping",
                    m.group(1).strip(),
                )
                continue

            # Parse ===SEARCH=== / ===REPLACE=== / ===END REPLACE=== pairs
            replacements: list[dict[str, str]] = []
            for sr in re.finditer(
                r"===SEARCH===\s*\n(.*?)===REPLACE===\s*\n(.*?)===END REPLACE===",
                body,
                re.DOTALL,
            ):
                search_text = sr.group(1).strip("\n")
                replace_text = sr.group(2).strip("\n")
                replacements.append({
                    "search": search_text,
                    "replace": replace_text,
                })

            if not replacements:
                logger.warning(
                    "BuilderAgent: MODIFY block for %s has no valid "
                    "SEARCH/REPLACE pairs, skipping",
                    m.group(1).strip(),
                )
                continue

            blocks.append({
                "path": m.group(1).strip(),
                "mode": "modify",
                "replacements": replacements,
            })

        return blocks


# ---------------------------------------------------------------------------
# Validation helpers (AD-313)
# ---------------------------------------------------------------------------

def _validate_python(path: Path) -> str | None:
    """Validate a Python file with ast.parse(). Returns error string or None."""
    if path.suffix != ".py":
        return None
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return None
    except SyntaxError as exc:
        return f"{path}: line {exc.lineno}: {exc.msg}"


# ---------------------------------------------------------------------------
# Test & fix helpers (AD-314)
# ---------------------------------------------------------------------------

async def _run_tests(work_dir: str, timeout: int = 120) -> tuple[bool, str]:
    """Run pytest and return (passed, output)."""
    def _sync_run() -> tuple[int, str]:
        try:
            result = subprocess.run(
                ["pytest", "--tb=short", "-q"],
                cwd=work_dir,
                capture_output=True,
                timeout=timeout,
            )
            test_out = (result.stdout or b"").decode(errors="replace")
            test_err = (result.stderr or b"").decode(errors="replace")
            output = test_out + ("\n" + test_err if test_err else "")
            return result.returncode, output
        except subprocess.TimeoutExpired:
            return 1, f"pytest timed out after {timeout}s"

    loop = asyncio.get_running_loop()
    returncode, output = await loop.run_in_executor(None, _sync_run)
    return returncode == 0, output


def _build_fix_prompt(
    spec_title: str,
    test_output: str,
    file_changes: list[dict[str, Any]],
    attempt: int,
) -> str:
    """Build a prompt asking the LLM to fix test failures."""
    file_listing = "\n".join(
        f"- {c['path']} ({c['mode']})" for c in file_changes
    )
    return (
        f"# Test Fix Required (attempt {attempt})\n\n"
        f"Build: {spec_title}\n\n"
        f"## Files Changed\n{file_listing}\n\n"
        f"## Test Failures\n```\n{test_output[-3000:]}\n```\n\n"
        "Fix the failing tests. Output ONLY the file changes needed to fix the "
        "failures. Use the same ===MODIFY: path=== or ===FILE: path=== format. "
        "Do NOT rewrite files that don't need changes. Keep fixes minimal — "
        "fix the bug, don't refactor."
    )


# ---------------------------------------------------------------------------
# Post-approval execution pipeline (AD-303)
# ---------------------------------------------------------------------------

async def execute_approved_build(
    file_changes: list[dict[str, Any]],
    spec: BuildSpec,
    work_dir: str,
    run_tests: bool = True,
    max_fix_attempts: int = 2,
    llm_client: Any | None = None,
) -> BuildResult:
    """Execute an approved build: write files, run tests, create git branch.

    Called AFTER the Captain reviews the BuilderAgent's output and approves
    the changes.  The agent generates the plan; this function executes it.
    """
    result = BuildResult(success=False, spec=spec)

    # 1. Save current branch
    original_branch = await _git_current_branch(work_dir)

    # 2. Generate branch name
    branch = spec.branch_name
    if not branch:
        slug = _sanitize_branch_name(spec.title)
        branch = f"builder/ad-{spec.ad_number}-{slug}" if spec.ad_number else f"builder/{slug}"

    # 3. Create branch
    ok, msg = await _git_create_branch(branch, work_dir)
    if not ok:
        result.error = f"Failed to create branch: {msg}"
        return result
    result.branch_name = _sanitize_branch_name(branch)

    written: list[str] = []
    modified_files: list[str] = []
    validation_errors: list[str] = []
    try:
        # 4. Write/modify files
        for change in file_changes:
            path = Path(work_dir) / change["path"]
            if change["mode"] == "modify":
                if not path.exists():
                    logger.warning(
                        "BuilderAgent: MODIFY target %s does not exist, skipping",
                        change["path"],
                    )
                    continue

                original = path.read_text(encoding="utf-8")
                modified = original

                for i, repl in enumerate(change.get("replacements", [])):
                    search_text = repl["search"]
                    replace_text = repl["replace"]

                    if search_text not in modified:
                        logger.warning(
                            "BuilderAgent: SEARCH block %d not found in %s, "
                            "skipping this replacement",
                            i, change["path"],
                        )
                        continue

                    # Replace first occurrence only
                    modified = modified.replace(search_text, replace_text, 1)

                if modified != original:
                    path.write_text(modified, encoding="utf-8")
                    modified_files.append(change["path"])
                    logger.info(
                        "BuilderAgent: modified %s (%d replacements)",
                        change["path"], len(change.get("replacements", [])),
                    )
                else:
                    logger.warning(
                        "BuilderAgent: no changes applied to %s", change["path"],
                    )

                # Validate Python files after modify
                err = _validate_python(path)
                if err:
                    validation_errors.append(err)

                continue

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(change["content"], encoding="utf-8")
            written.append(change["path"])
            logger.info("BuilderAgent: wrote %s", change["path"])

            # Validate Python files after create
            err = _validate_python(path)
            if err:
                validation_errors.append(err)

        result.files_written = written
        result.files_modified = modified_files

        # 5. Run tests with fix loop (AD-314)
        if run_tests and (written or modified_files):
            all_changes = list(file_changes)  # track for fix prompt
            for attempt in range(1 + max_fix_attempts):
                passed, test_output = await _run_tests(work_dir)
                result.test_result = test_output
                result.tests_passed = passed

                if passed:
                    break

                if attempt < max_fix_attempts and llm_client is not None:
                    logger.info(
                        "BuilderAgent: test failures on attempt %d/%d, "
                        "requesting fix from LLM",
                        attempt + 1, max_fix_attempts,
                    )
                    fix_prompt = _build_fix_prompt(
                        spec.title, test_output, all_changes, attempt + 1,
                    )
                    fix_request = LLMRequest(
                        prompt=fix_prompt,
                        system_prompt=BuilderAgent.instructions,
                        tier="deep",
                    )
                    try:
                        fix_response = await llm_client.complete(fix_request)
                        fix_changes = BuilderAgent._parse_file_blocks(
                            fix_response.content,
                        )
                    except Exception as exc:
                        logger.warning(
                            "BuilderAgent: LLM fix call failed: %s", exc,
                        )
                        fix_changes = []

                    if not fix_changes:
                        logger.warning(
                            "BuilderAgent: LLM returned no fix blocks, "
                            "skipping attempt %d",
                            attempt + 1,
                        )
                        result.fix_attempts += 1
                        continue

                    # Apply fix changes
                    for change in fix_changes:
                        path = Path(work_dir) / change["path"]
                        if change["mode"] == "modify":
                            if not path.exists():
                                continue
                            original = path.read_text(encoding="utf-8")
                            mod = original
                            for repl in change.get("replacements", []):
                                if repl["search"] in mod:
                                    mod = mod.replace(
                                        repl["search"], repl["replace"], 1,
                                    )
                            if mod != original:
                                path.write_text(mod, encoding="utf-8")
                                if change["path"] not in modified_files:
                                    modified_files.append(change["path"])
                        else:
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text(
                                change["content"], encoding="utf-8",
                            )
                            if change["path"] not in written:
                                written.append(change["path"])
                        err = _validate_python(path)
                        if err:
                            validation_errors.append(err)

                    all_changes.extend(fix_changes)
                    result.fix_attempts += 1
                else:
                    # No LLM client or exhausted retries
                    if attempt < max_fix_attempts:
                        result.fix_attempts += 1

            result.files_written = written
            result.files_modified = modified_files

        # 6. Commit
        if written or modified_files:
            desc_short = spec.description[:200] if spec.description else ""
            commit_msg = (
                f"{spec.title}"
                + (f" (AD-{spec.ad_number})" if spec.ad_number else "")
                + (f"\n\n{desc_short}" if desc_short else "")
                + "\n\nCo-Authored-By: ProbOS Builder <probos@probos.dev>"
            )
            ok, sha = await _git_add_and_commit(
                written + modified_files, commit_msg, work_dir,
            )
            if ok:
                result.commit_hash = sha
            else:
                result.error = f"Commit failed: {sha}"

        if validation_errors:
            result.error = "Syntax errors:\n" + "\n".join(validation_errors)
            result.success = False
        else:
            result.success = True

    except Exception as exc:
        result.error = str(exc)
    finally:
        # 7. Return to original branch
        await _git_checkout_main(work_dir)

    return result
