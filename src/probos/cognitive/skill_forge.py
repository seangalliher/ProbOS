"""AD-1069: SkillForge — generate, validate, smoke-test + register cognitive skills.

The generative, skill-side sibling of ``AgentDesigner``: given a spec, the forge
asks the LLM to produce an ORIGINAL cognitive skill (a ``SKILL.md`` plus a
self-contained bundled script), then runs a four-gate pipeline before the skill
is ever registered —

  1. **generate** — one deep-tier LLM call emitting ``===FILE:`` blocks;
  2. **validate** — frontmatter (``parse_skill_file``) + structural
     (``_validate_spec``) + per-script ``ast.parse`` + a dangerous-pattern scan;
  3. **smoke-test** — actually run the primary script in the AD-993
     ``SubprocessSandbox`` and require it to produce a real deliverable file;
  4. **register** — ``CognitiveSkillCatalog.import_skill(..., origin="generated")``.

A skill that fails any gate is never registered (honest-degrade, AD-592) — the
forge returns a :class:`ForgeResult` with the reasons. The smoke-test is the real
safety boundary: the script runs out-of-process, time/output/memory-bounded, with
the network off. Generated skills land with ``origin="generated"`` so operators
and agents can tell machine-forged skills from hand-authored ones (the skill-side
analogue of designed-agent probation).

License: the forge produces ORIGINAL skills from public-library knowledge
(python-docx, openpyxl, python-pptx, the stdlib). It must never copy a
proprietary skill library verbatim — the generation prompt says so explicitly.
"""

from __future__ import annotations

import ast
import logging
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from probos.cognitive.skill_catalog import _validate_spec, parse_skill_file
from probos.execution.isolation import (
    ExecutionRequest,
    SubprocessSandbox,
    remove_workdir_off_loop,
)
from probos.types import LLMRequest

if TYPE_CHECKING:
    from probos.cognitive.skill_catalog import CognitiveSkillCatalog

logger = logging.getLogger(__name__)

# Defense-in-depth at generation time (the sandbox is the real boundary). A
# generated skill script must not contain these — doc/data generation never
# legitimately needs them.
_FORBIDDEN_SCRIPT_PATTERNS: tuple[str, ...] = (
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\b__import__\s*\(",
    r"\bos\.system\s*\(",
    r"\bsubprocess\b",
    r"\bsocket\b",
    r"\bctypes\b",
)

_FILE_BLOCK_RE = re.compile(r"^===FILE:\s*(?P<path>[^=\n]+?)\s*===\s*$", re.MULTILINE)

# Generation budget + smoke bounds.
_GEN_MAX_TOKENS = 4096
_SMOKE_TIMEOUT_S = 60.0
_SMOKE_MAX_OUTPUT = 64 * 1024
_SMOKE_MAX_MEMORY_MB = 512
_SCRIPT_NAME = "script.py"  # the sandbox writes the submitted code here

_FORGE_PROMPT = """You are the SkillForge of ProbOS, a probabilistic agent-native OS. \
Design a NEW, ORIGINAL cognitive skill that a crew agent can load and run to \
perform a task and produce a deliverable file (the Claude Cowork / Codex / \
GitHub Copilot model).

SKILL TO FORGE
  Name: {name}
  Description: {description}
  Task it must perform: {task}
  Department: {department}
  Minimum rank: {min_rank}

OUTPUT FORMAT — emit EXACTLY these two blocks and NOTHING else (no prose, no \
markdown code fences):

===FILE: SKILL.md===
---
name: {name}
description: {description}
metadata:
  probos-department: "{department}"
  probos-min-rank: "{min_rank}"
  probos-activation: discovery
---

# <Title>

<Concise instructions a capable agent can follow: what this skill produces and
how to run the bundled script. State that scripts/generate.py is self-contained
and, run with no arguments, writes a sample deliverable into the current working
directory. Describe the CONFIG block at the top of the script that an agent edits
to customize the real output, then re-runs via run_python.>

===FILE: scripts/generate.py===
<A SELF-CONTAINED Python script. Hard requirements:
 - Running `python generate.py` with NO arguments MUST write at least one
   deliverable file into the CURRENT WORKING DIRECTORY by plain filename
   (e.g. doc.save('sample.docx')).
 - Put an editable CONFIG dict / constants at the TOP so an agent can customize
   the real output, then re-run.
 - Use ONLY the Python standard library and these permissive, installed
   libraries as needed: python-docx (import docx), openpyxl, python-pptx
   (import pptx). Pick the right one for the task.
 - DO NOT use the network, subprocess, eval, exec, __import__, os.system,
   sockets, or ctypes, and do not read files outside the working directory.
 - It must run under Python isolated mode (-I).>

Produce original work. Do NOT copy any proprietary skill library verbatim.
"""


@dataclass
class _SmokeOutcome:
    ok: bool
    detail: str = ""
    artifacts: list[str] = field(default_factory=list)


@dataclass
class ForgeResult:
    """Outcome of one forge attempt. ``success`` is True only when the skill
    passed every gate and was registered."""

    success: bool
    name: str = ""
    skill_dir: str = ""
    errors: list[str] = field(default_factory=list)
    smoke_artifacts: list[str] = field(default_factory=list)
    skill_md: str = ""


class SkillForge:
    """AD-1069: generate → validate → smoke-test → register a cognitive skill.

    Constructor-injected (DIP): an LLM client, the target
    :class:`CognitiveSkillCatalog`, and an optional sandbox (defaults to a fresh
    :class:`SubprocessSandbox`). Stateless across calls.
    """

    def __init__(
        self,
        *,
        llm_client: Any,
        catalog: "CognitiveSkillCatalog",
        sandbox: SubprocessSandbox | None = None,
        tier: str = "deep",
    ) -> None:
        self._llm = llm_client
        self._catalog = catalog
        self._sandbox = sandbox
        self._tier = tier

    async def forge(
        self,
        *,
        name: str,
        description: str,
        task: str,
        department: str = "*",
        min_rank: str = "ensign",
        primary_script: str = "scripts/generate.py",
    ) -> ForgeResult:
        """Forge one cognitive skill. Never raises — every failure is an
        honest-degrade :class:`ForgeResult` with ``success=False``."""
        name = (name or "").strip()
        if not name:
            return ForgeResult(success=False, errors=["a skill name is required"])
        # The name becomes a directory name + the catalog key — guard it before use.
        if len(name) > 64 or not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", name):
            return ForgeResult(
                success=False, name=name,
                errors=[
                    "invalid skill name (lowercase alphanumeric + single hyphens, "
                    "\u226464 chars)"
                ],
            )

        # 1. Generate.
        try:
            raw = await self._generate(
                name=name, description=description, task=task,
                department=department, min_rank=min_rank,
            )
        except Exception as exc:
            logger.warning("AD-1069: skill generation failed for %s: %s", name, exc)
            return ForgeResult(success=False, name=name, errors=[f"generation failed: {exc}"])

        files = self._parse_files(raw)
        skill_md = files.get("SKILL.md", "")
        if not skill_md:
            return ForgeResult(
                success=False, name=name,
                errors=["LLM output contained no SKILL.md block"],
            )

        # The skill dir MUST be named exactly <name> — _validate_spec requires
        # entry.name == skill_dir.name, and import_skill copies the dir wholesale.
        staging_root = Path(tempfile.mkdtemp(prefix="forge-"))
        staging = staging_root / name
        try:
            try:
                staging.mkdir(parents=True, exist_ok=True)
                self._write_files(staging, files)
            except ValueError as exc:
                return ForgeResult(
                    success=False, name=name, skill_md=skill_md,
                    errors=[str(exc)],
                )

            # 3. Validate (frontmatter + structural + scripts).
            errors = self._validate(staging, expected_name=name)
            if errors:
                return ForgeResult(
                    success=False, name=name, skill_md=skill_md, errors=errors,
                )

            # 4. Smoke-test the primary script in the sandbox.
            smoke = await self._smoke_test(staging, primary_script)
            if not smoke.ok:
                return ForgeResult(
                    success=False, name=name, skill_md=skill_md,
                    errors=[f"smoke-test failed: {smoke.detail}"],
                )

            # 5. Register (copies staging → config/skills/<name>).
            try:
                entry = await self._catalog.import_skill(staging, origin="generated")
            except ValueError as exc:
                return ForgeResult(
                    success=False, name=name, skill_md=skill_md,
                    errors=[f"registration failed: {exc}"],
                    smoke_artifacts=smoke.artifacts,
                )

            logger.info(
                "AD-1069: forged skill '%s' (origin=generated, artifacts=%s)",
                entry.name, smoke.artifacts,
            )
            return ForgeResult(
                success=True,
                name=entry.name,
                skill_dir=str(entry.skill_dir),
                smoke_artifacts=smoke.artifacts,
                skill_md=skill_md,
            )
        except Exception as exc:  # honest-degrade: never raise out of forge
            logger.warning("AD-1069: forge failed for %s: %s", name, exc, exc_info=True)
            return ForgeResult(success=False, name=name, skill_md=skill_md, errors=[f"forge failed: {exc}"])
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

    # ── pipeline stages ───────────────────────────────────────────
    async def _generate(
        self, *, name: str, description: str, task: str,
        department: str, min_rank: str,
    ) -> str:
        prompt = _FORGE_PROMPT.format(
            name=name, description=description, task=task,
            department=department, min_rank=min_rank,
        )
        request = LLMRequest(prompt=prompt, tier=self._tier, max_tokens=_GEN_MAX_TOKENS)
        response = await self._llm.complete(request)
        content = getattr(response, "content", "") or ""
        if getattr(response, "error", None) or not content.strip():
            raise ValueError(
                f"empty or error LLM response: {getattr(response, 'error', None)}"
            )
        return content

    @staticmethod
    def _parse_files(raw: str) -> dict[str, str]:
        """Parse ``===FILE: path===`` blocks into ``{path: content}``. Strips a
        single outer markdown code fence if the whole payload is fenced."""
        text = raw.strip()
        text = re.sub(r"^```[a-zA-Z0-9]*\s*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
        matches = list(_FILE_BLOCK_RE.finditer(text))
        files: dict[str, str] = {}
        for i, m in enumerate(matches):
            path = m.group("path").strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            files[path] = text[start:end].strip("\n")
        return files

    @staticmethod
    def _write_files(staging: Path, files: dict[str, str]) -> None:
        """Write parsed files under ``staging`` with a path-traversal guard (the
        LLM output is untrusted). A containment check (resolved dest must stay
        under ``staging``) catches ``..`` and platform-specific absolute forms
        (e.g. ``/etc/x`` is only drive-relative — not ``is_absolute`` — on
        Windows)."""
        base = staging.resolve()
        for rel, content in files.items():
            parts = Path(rel).parts
            dest = (staging / rel).resolve()
            if (
                not rel
                or Path(rel).is_absolute()
                or ".." in parts
                or not dest.is_relative_to(base)
            ):
                raise ValueError(f"unsafe path in generated skill: {rel!r}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content + "\n", encoding="utf-8")

    def _validate(self, staging: Path, *, expected_name: str) -> list[str]:
        errors: list[str] = []
        skill_md = staging / "SKILL.md"
        entry = parse_skill_file(skill_md)
        if entry is None:
            return ["SKILL.md failed to parse (invalid frontmatter)"]
        if entry.name != expected_name:
            errors.append(
                f"generated skill name {entry.name!r} != requested {expected_name!r}"
            )
        errors.extend(_validate_spec(entry))

        scripts_dir = staging / "scripts"
        script_files = sorted(scripts_dir.rglob("*.py")) if scripts_dir.exists() else []
        if not script_files:
            errors.append("no bundled script under scripts/")
        for script in script_files:
            try:
                src = script.read_text(encoding="utf-8")
            except OSError as exc:
                errors.append(f"{script.name}: unreadable ({exc})")
                continue
            try:
                ast.parse(src)
            except SyntaxError as exc:
                errors.append(f"{script.name}: syntax error: {exc.msg} (line {exc.lineno})")
                continue
            for pat in _FORBIDDEN_SCRIPT_PATTERNS:
                if re.search(pat, src):
                    errors.append(f"{script.name}: forbidden pattern {pat!r}")
        return errors

    async def _smoke_test(self, staging: Path, primary_script: str) -> _SmokeOutcome:
        script_path = staging / primary_script
        if not script_path.is_file():
            return _SmokeOutcome(False, f"primary script {primary_script!r} not found")
        try:
            code = script_path.read_text(encoding="utf-8")
        except OSError as exc:
            return _SmokeOutcome(False, f"primary script unreadable: {exc}")

        workdir = Path(tempfile.mkdtemp(prefix="forge-smoke-"))
        try:
            sandbox = self._sandbox or SubprocessSandbox(
                scratch_root=str(workdir.parent)
            )
            res = await sandbox.run(
                ExecutionRequest(
                    code=code,
                    workdir=workdir,
                    timeout_seconds=_SMOKE_TIMEOUT_S,
                    max_output_bytes=_SMOKE_MAX_OUTPUT,
                    max_memory_mb=_SMOKE_MAX_MEMORY_MB,
                    allow_network=False,
                )
            )
            if not res.success:
                detail = (res.stderr or res.error or "non-zero exit").strip()
                return _SmokeOutcome(False, detail[:500])
            produced = sorted(
                p.name
                for p in workdir.glob("*")
                if p.is_file() and p.name != _SCRIPT_NAME
            )
            if not produced:
                return _SmokeOutcome(False, "script produced no deliverable file")
            return _SmokeOutcome(True, "", produced)
        finally:
            # BF-840: was a one-shot ``rmtree(workdir, ignore_errors=True)``,
            # which cannot remove a directory a live smoke-test child still
            # holds and reports nothing when it fails -- measured to leave the
            # directory on disk even after the child had exited, because
            # nothing retried. Off-loop because this is a ``finally`` on the
            # event loop and the retry budget runs to ~9s.
            await remove_workdir_off_loop(workdir)
