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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentDescriptor

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


# ---------------------------------------------------------------------------
# Git helpers (AD-303) — async only, no subprocess import
# ---------------------------------------------------------------------------

def _sanitize_branch_name(name: str) -> str:
    """Lowercase, alphanum + hyphens, max 50 chars."""
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return slug[:50]


async def _run_git(args: list[str], work_dir: str) -> tuple[int, str, str]:
    """Run a git command asynchronously.  Returns (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=work_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await proc.communicate()
    return (
        proc.returncode or 0,
        (stdout_b or b"").decode(errors="replace").strip(),
        (stderr_b or b"").decode(errors="replace").strip(),
    )


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

    async def perceive(self, intent: Any) -> dict:
        """Read reference files and build context for the LLM."""
        obs = await super().perceive(intent)

        params = obs.get("params", {})
        reference_files = params.get("reference_files", [])

        file_contexts: list[str] = []
        for ref_path in reference_files:
            try:
                full_path = Path(ref_path)
                if full_path.exists() and full_path.is_file():
                    content = full_path.read_text(encoding="utf-8")
                    file_contexts.append(f"=== {ref_path} ===\n{content}\n")
            except Exception:
                file_contexts.append(f"=== {ref_path} === (could not read)\n")

        obs["file_context"] = "\n".join(file_contexts)

        # Read target files so the LLM can produce accurate SEARCH blocks
        target_files = params.get("target_files", [])
        target_contexts: list[str] = []
        for tgt_path in target_files:
            try:
                full_path = Path(tgt_path)
                if full_path.exists() and full_path.is_file():
                    content = full_path.read_text(encoding="utf-8")
                    target_contexts.append(
                        f"=== {tgt_path} (TARGET — will be modified) ===\n{content}\n"
                    )
            except Exception:
                # File doesn't exist — Builder will create it (use FILE block, not MODIFY)
                target_contexts.append(
                    f"=== {tgt_path} (TARGET — new file, does not exist yet) ===\n"
                )
        obs["target_context"] = "\n".join(target_contexts)

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
            return {"success": False, "error": decision.get("reason")}

        llm_output = decision.get("llm_output", "")

        file_changes = self._parse_file_blocks(llm_output)
        if not file_changes:
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
# Post-approval execution pipeline (AD-303)
# ---------------------------------------------------------------------------

async def execute_approved_build(
    file_changes: list[dict[str, Any]],
    spec: BuildSpec,
    work_dir: str,
    run_tests: bool = True,
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

        # 5. Run tests
        if run_tests and (written or modified_files):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pytest", "--tb=short", "-q",
                    cwd=work_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=120,
                )
                test_out = (stdout_b or b"").decode(errors="replace")
                test_err = (stderr_b or b"").decode(errors="replace")
                result.test_result = test_out + ("\n" + test_err if test_err else "")
                result.tests_passed = proc.returncode == 0
            except asyncio.TimeoutError:
                result.test_result = "pytest timed out after 120s"
                result.tests_passed = False

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
