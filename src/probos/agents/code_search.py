"""AD-989: CodeSearchAgent — lexical content grep for the mesh.

Code is an *exact-token* domain: lexical/regex content search beats embedding/RAG
for it (exact, always-fresh, and self-explaining — you get back the matched line,
not a similarity score). ProbOS already leans lexical (AD-979c hybrid FTS5, BF-625
BM25 ranking, AD-988 retrieval transparency); this agent fills the missing
capability — there was no content grep in the mesh at all.

Engine selection mirrors the BYO-binary pattern used for Piper TTS / Rhubarb
(AD-738): if the operator has the ``rg`` (ripgrep) binary on PATH or under
``tools/``, use it (linear-time, gitignore-native); otherwise fall back to a
bounded pure-Python line scan over the AD-990 ignore-aware walk, with every
supplied pattern run through the AD-991 ReDoS guard. ripgrep itself is dual
MIT/Unlicense and is *pattern-absorbed*, never vendored (it is Rust); ``rg`` is an
optional operator binary, not a dependency.

Read-only, core-tier, no consensus. Bounded everywhere (max_results, max_files via
the walk, per-line cap, subprocess timeout); honest-degrade on every failure.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.substrate.file_walk import iter_files
from probos.substrate.safe_regex import UnsafePatternError, safe_compile
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RESULTS = 200
_MAX_LINE_BYTES = 2000       # skip pathological long lines (bounds backtracking)
_LINE_PREVIEW_CHARS = 300
_RG_TIMEOUT_SECONDS = 20.0


class CodeSearchAgent(BaseAgent):
    """Search file *contents* for a regex, returning ``path:line:text`` matches.

    Capabilities: search_content. Read-only — no consensus required.
    """

    agent_type: str = "code_search"
    tier = "core"
    default_capabilities = [
        CapabilityDescriptor(
            can="search_content",
            detail="Search file contents for a regex pattern (grep)",
            formats=["json"],
        ),
    ]
    initial_confidence: float = 0.8
    intent_descriptors = [
        IntentDescriptor(
            name="search_content",
            params={
                "path": "<absolute_dir_or_file>",
                "pattern": "<regex>",
                "max_results": "<int, default 200>",
                "case_insensitive": "<bool, default false>",
                "glob": "<optional glob filter, e.g. *.py>",
                "include_ignored": "<bool, default false>",
            },
            description="Search file contents for a regex pattern (returns path:line:text)",
            usage_hint="[MESH search_content path=<dir> pattern=<regex>] (grep file contents → path:line:text; gitignored dirs skipped)",
        ),
    ]

    _handled_intents = {"search_content"}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None
        plan = await self.decide(observation)
        if plan is None:
            return None
        result = await self.act(plan)
        report = await self.report(result)
        success = report.get("success", False)
        self.update_confidence(success)
        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("data") if success else None,
            error=report.get("error"),
            confidence=self.confidence,
        )

    async def perceive(self, intent: dict[str, Any]) -> Any:
        if intent.get("intent", "") not in self._handled_intents:
            return None
        return {"intent": intent.get("intent", ""), "params": intent.get("params", {})}

    async def decide(self, observation: Any) -> Any:
        params = observation["params"]
        path = params.get("path")
        pattern = params.get("pattern")
        if not path:
            return {"action": "error", "error": "No path specified"}
        if not pattern:
            return {"action": "error", "error": "No pattern specified"}
        try:
            max_results = int(params.get("max_results", _DEFAULT_MAX_RESULTS))
        except (TypeError, ValueError):
            max_results = _DEFAULT_MAX_RESULTS
        return {
            "action": "search",
            "path": path,
            "pattern": pattern,
            "max_results": max(1, min(max_results, 5000)),
            "case_insensitive": bool(params.get("case_insensitive", False)),
            "glob": params.get("glob") or None,
            "include_ignored": bool(params.get("include_ignored", False)),
        }

    async def act(self, plan: Any) -> Any:
        if plan.get("action") == "error":
            return {"success": False, "error": plan["error"]}
        if plan.get("action") != "search":
            return {"success": False, "error": f"Unknown action: {plan.get('action')}"}

        root = Path(plan["path"])
        if not root.exists():
            return {"success": False, "error": f"Path not found: {plan['path']}"}

        # Prefer the operator's ripgrep binary; fall back to pure Python.
        rg = _resolve_rg_binary()
        if rg is not None:
            rg_result = await self._search_rg(rg, plan, root)
            if rg_result is not None:
                return rg_result
            # Tier-2: rg failed -> fall through to the Python engine.
        return self._search_python(plan, root)

    async def report(self, result: Any) -> dict[str, Any]:
        return result

    # ------------------------------------------------------------------
    # rg engine (preferred when available)
    # ------------------------------------------------------------------

    async def _search_rg(self, rg: str, plan: dict, root: Path) -> dict | None:
        """Run ``rg`` via subprocess (no shell -> no injection). Returns a result
        dict, or ``None`` to signal the caller to fall back to Python."""
        args = [rg, "--line-number", "--no-heading", "--color", "never",
                "--max-count", str(plan["max_results"])]
        if plan["case_insensitive"]:
            args.append("--ignore-case")
        if plan["include_ignored"]:
            args.append("-uuu")
        if plan["glob"]:
            args += ["--glob", plan["glob"]]
        args += ["--regexp", plan["pattern"], str(root)]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_RG_TIMEOUT_SECONDS,
            )
        except (OSError, asyncio.TimeoutError, ValueError):
            logger.debug("AD-989: rg engine failed; falling back to Python", exc_info=True)
            return None
        # rg exit 0 = matches, 1 = no matches (both fine); 2 = error -> fall back.
        if proc.returncode not in (0, 1):
            return None
        matches: list[dict] = []
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            parsed = _parse_rg_line(line)
            if parsed is not None:
                matches.append(parsed)
                if len(matches) >= plan["max_results"]:
                    break
        return {
            "success": True,
            "data": matches,
            "count": len(matches),
            "engine": "rg",
            "truncated": len(matches) >= plan["max_results"],
        }

    # ------------------------------------------------------------------
    # pure-Python engine (always available; ReDoS-guarded)
    # ------------------------------------------------------------------

    def _search_python(self, plan: dict, root: Path) -> dict:
        flags = re.IGNORECASE if plan["case_insensitive"] else 0
        try:
            rx = safe_compile(plan["pattern"], flags=flags)
        except UnsafePatternError as exc:
            return {"success": False, "error": f"Unsafe pattern: {exc}"}

        max_results = plan["max_results"]
        glob = plan["glob"]
        matches: list[dict] = []
        files = [root] if root.is_file() else iter_files(
            root, skip_binary=True,
            include_hidden=plan["include_ignored"],
            respect_default_ignores=not plan["include_ignored"],
        )
        truncated = False
        for fp in files:
            if glob and not fp.match(glob):
                continue
            try:
                with fp.open("r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, start=1):
                        if len(line) > _MAX_LINE_BYTES:
                            continue
                        if rx.search(line):
                            matches.append({
                                "path": str(fp),
                                "line": lineno,
                                "text": line.rstrip("\n")[:_LINE_PREVIEW_CHARS],
                            })
                            if len(matches) >= max_results:
                                truncated = True
                                break
            except OSError:
                continue
            if truncated:
                break
        return {
            "success": True,
            "data": matches,
            "count": len(matches),
            "engine": "python",
            "truncated": truncated,
        }


def _install_root() -> Path:
    """AD-1025b: the ProbOS install/repo root. ``src/probos/agents/code_search.py``
    -> ``parents[3]`` (code_search->agents->probos->src->root). Mirrors
    ``__main__.py``'s ``project_root`` and ``piper_backend._probos_root`` (the
    bundled ``tools/`` anchor). NEVER the CWD."""
    return Path(__file__).resolve().parents[3]


def _resolve_rg_binary() -> str | None:
    """Find ripgrep: PATH first, then a gitignored ``tools/rg[.exe]`` (the AD-738
    BYO-binary disposition). Returns the executable path, or ``None``."""
    found = shutil.which("rg")
    if found:
        return found
    candidate = _install_root() / "tools" / "rg"
    if sys.platform == "win32":
        candidate = candidate.with_suffix(".exe")
    try:
        if candidate.is_file():
            return str(candidate.resolve())
    except OSError:
        pass
    return None


def _parse_rg_line(line: str) -> dict | None:
    """Parse an ``rg --no-heading --line-number`` line: ``path:lineno:text``."""
    # Split only on the first two colons (paths/lines never contain them; text may).
    first = line.find(":")
    if first <= 0:
        return None
    second = line.find(":", first + 1)
    if second < 0:
        return None
    path = line[:first]
    lineno_str = line[first + 1:second]
    text = line[second + 1:]
    try:
        lineno = int(lineno_str)
    except ValueError:
        return None
    return {"path": path, "line": lineno, "text": text[:_LINE_PREVIEW_CHARS]}
