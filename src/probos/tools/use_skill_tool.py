"""AD-1068: UseSkillTool — load a cognitive skill into the conversational loop.

The bridge between the :class:`CognitiveSkillCatalog` (AD-596a) and the
code-execution tool (AD-1066). An agent in the AD-1065 ``AgenticLoop`` calls
``use_skill(name)`` to pull a skill's ``SKILL.md`` body (its instructions —
loaded on demand, progressive disclosure) plus a manifest of the skill's bundled
files and the absolute ``skill_dir``. The agent then runs the skill's scripts via
``run_python`` (AD-1066) **by absolute path** — the AD-993 ``SubprocessSandbox``
is Tier-1 confinement-by-convention (a script may read host files by absolute
path), so a skill's scripts execute from ``skill_dir`` without staging.

Governance: read-only. ``use_skill`` only surfaces instructions, so it is offered
whenever the catalog is wired (it does not itself require ``execution.enabled`` —
*running* the returned scripts does, via ``run_python``). Department/rank
visibility is honored (the same filter the progressive-disclosure descriptions
use). The tool never raises out of ``invoke`` — every miss is an honest-degrade
``ToolResult`` the loop can reason over (AD-592).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from probos.tools.protocol import ToolResult, ToolType, refuse_undeclared_params

logger = logging.getLogger(__name__)

# Files that are skill machinery, not loadable bundled resources.
_SKILL_DOC_NAME = "SKILL.md"
_SKIP_DIR_PARTS = {".venv", "venv", "__pycache__", ".git", "node_modules", ".pytest_cache"}
# Bound the manifest so a skill folder with a large tree can't flood the loop ctx.
_MAX_FILES = 200


class UseSkillTool:
    """AD-1068: load a named cognitive skill's instructions + bundled-file
    manifest into the agentic loop so the agent can run the skill's scripts.

    Satisfies the AD-423a ``Tool`` protocol (duck-typed — no inheritance).
    Constructed with the runtime so it can read ``runtime.cognitive_skill_catalog``.
    """

    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime

    # ── Tool protocol ─────────────────────────────────────────────
    @property
    def tool_id(self) -> str:
        return "use_skill"

    @property
    def name(self) -> str:
        return "Use Skill"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return (
            "Load a cognitive skill by name to get its step-by-step instructions "
            "and its bundled scripts. Use this when a task matches a known skill "
            "(e.g. creating a Word document, a spreadsheet, or a PDF). Returns the "
            "skill's instructions, the absolute path to its folder (skill_dir), and "
            "the list of files it bundles. To run a bundled script, call run_python "
            "and reference it by its absolute path, e.g. "
            "subprocess.run([sys.executable, r'<skill_dir>/scripts/make.py'], check=True) "
            "— any file the script writes into the working directory is saved as a "
            "downloadable artifact. Call with an unknown or empty name to list the "
            "skills available to you."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The skill name to load (e.g. 'docx').",
                },
            },
            "required": ["name"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    # ── Execution ─────────────────────────────────────────────────
    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        t0 = time.monotonic()
        # AD-1179: ahead of the catalog probe. A misnamed key would otherwise
        # fall through to the discovery branch and be answered as "no such
        # skill", which is the wrong correction to hand back.
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        catalog = getattr(self._runtime, "cognitive_skill_catalog", None)
        if catalog is None:
            return ToolResult(error="Skills are not available (no skill catalog).")

        ctx = context or {}
        department = (str(ctx.get("department") or "").strip()) or None
        rank = (str(ctx.get("rank") or "").strip()) or None

        try:
            visible = catalog.list_entries(department=department, min_rank=rank)
        except Exception:
            logger.warning(
                "AD-1068: catalog.list_entries failed; treating all skills as "
                "visible for agent=%s", ctx.get("agent_id", "?"), exc_info=True,
            )
            visible = []
        visible_names = sorted({e.name for e in visible})

        name = str((params or {}).get("name") or "").strip()
        entry = catalog.get_entry(name) if name else None
        # Not provided / unknown / outside the agent's visibility → discovery.
        if (
            not name
            or entry is None
            or (visible_names and name not in visible_names)
        ):
            available = visible_names or sorted(
                e.name for e in self._all_entries(catalog)
            )
            return ToolResult(
                output={
                    "found": False,
                    "available": available[:50],
                    "message": (
                        "No skill named %r is available to you. Pick one of "
                        "'available', or proceed without a skill." % name
                        if name else
                        "Provide one of the skills in 'available'."
                    ),
                },
                duration_ms=(time.monotonic() - t0) * 1000.0,
            )

        try:
            instructions = catalog.get_instructions(name) or ""
            skill_dir = Path(entry.skill_dir).resolve()
            files = self._bundled_files(skill_dir)
            return ToolResult(
                output={
                    "found": True,
                    "name": entry.name,
                    "description": entry.description,
                    "instructions": instructions,
                    "skill_dir": str(skill_dir),
                    "files": files,
                },
                duration_ms=(time.monotonic() - t0) * 1000.0,
            )
        except Exception as exc:
            logger.warning(
                "AD-1068: failed to load skill %r for agent=%s: %s",
                name, ctx.get("agent_id", "?"), exc, exc_info=True,
            )
            return ToolResult(error=f"could not load skill '{name}': {exc}")

    # ── Helpers ───────────────────────────────────────────────────
    @staticmethod
    def _all_entries(catalog: Any) -> list[Any]:
        try:
            return catalog.list_entries()
        except Exception:
            return []

    @staticmethod
    def _bundled_files(skill_dir: Path) -> list[dict[str, str]]:
        """Manifest of the skill's bundled files (everything under ``skill_dir``
        except ``SKILL.md`` and machinery dirs), capped at ``_MAX_FILES``."""
        out: list[dict[str, str]] = []
        try:
            paths = sorted(skill_dir.rglob("*"))
        except OSError:
            return out
        for p in paths:
            try:
                if not p.is_file():
                    continue
            except OSError:
                continue
            rel_parts = p.relative_to(skill_dir).parts
            if any(part in _SKIP_DIR_PARTS for part in rel_parts):
                continue
            if len(rel_parts) == 1 and p.name == _SKILL_DOC_NAME:
                continue
            out.append(
                {"path": "/".join(rel_parts), "abs": str(p.resolve())}
            )
            if len(out) >= _MAX_FILES:
                break
        return out
