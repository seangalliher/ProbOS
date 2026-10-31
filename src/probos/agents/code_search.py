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
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from probos.admission.seam import check_at
from probos.admission.taxonomy import EFFECT_SUBPROCESS
from probos.execution.command_env import trusted_command_env
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

        # BF-758: same allowlist, same seam. This one matters most of the three
        # siblings -- ripgrep returns matching LINES, so an unbounded root turns
        # a content search into a way to grep the credential store.
        from probos.security.file_access import resolve_for_runtime

        try:
            root = resolve_for_runtime(str(plan["path"]), getattr(self, "_runtime", None))
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        if not root.exists():
            return {"success": False, "error": f"Path not found: {plan['path']}"}

        # BF-908 A3: one read floor per search for the engines. Both ask it about a file before
        # they count its matches, so a protected file never uses up max_results (a protected first
        # match made a legitimate search come back empty).
        floor = _ReadFloor(getattr(self, "_runtime", None))
        # Prefer the operator's ripgrep binary; fall back to pure Python.
        rg = _resolve_rg_binary()
        if rg is not None:
            rg_result = await self._search_rg(rg, plan, root, floor=floor)
            if rg_result is not None:
                # BF-908 A4: a FRESH floor, built after the engine ran, decides what is returned:
                # the engines' cached allows are not the final authorization (review round 2 of
                # C1b returned a protected line through a link retargeted during the search).
                return _within_floor(rg_result, _ReadFloor(getattr(self, "_runtime", None)))
            # Tier-2: rg failed -> fall through to the Python engine.
        return _within_floor(self._search_python(plan, root, floor=floor), _ReadFloor(getattr(self, "_runtime", None)))

    async def report(self, result: Any) -> dict[str, Any]:
        return result

    # ------------------------------------------------------------------
    # rg engine (preferred when available)
    # ------------------------------------------------------------------

    async def _search_rg(
        self, rg: str, plan: dict, root: Path, *, floor: _ReadFloor | None = None,
    ) -> dict | None:
        """Run ``rg`` via subprocess (no shell -> no injection). Returns a result
        dict, or ``None`` to signal the caller to fall back to Python.

        BF-908 A3: a line in a file *floor* refuses is skipped before it is counted.
        ``--max-count`` is per file, so rg itself still reads such a file; its lines
        never reach the result. ``floor=None`` is the raw engine (the tests' control);
        ``act`` always passes one.
        """
        # BF-895 (#1548): --with-filename keeps the path on every line (rg omits it
        # when the root is a single file); --null ends the path with NUL, which no
        # path can hold, so a path that contains ``:<digits>:`` is never mis-split.
        args = [rg, "--line-number", "--with-filename", "--null", "--no-heading",
                "--color", "never", "--max-count", str(plan["max_results"])]
        if plan["case_insensitive"]:
            args.append("--ignore-case")
        if plan["include_ignored"]:
            args.append("-uuu")
        if plan["glob"]:
            args += ["--glob", plan["glob"]]
        args += ["--regexp", plan["pattern"], str(root)]
        check_at(getattr(getattr(self, "_runtime", None), "admission_service", None), effect=EFFECT_SUBPROCESS, presented_id=None)  # AD-1346 M3e1: the subprocess sink, in shadow; it blocks nothing (D164: no principal)
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                env=trusted_command_env(),
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
        parsed_lines = 0
        # BF-895 (#1548): frame on LF only. str.splitlines() also splits at U+2028, U+2029,
        # U+0085, form feed and others, which a file name or a match can hold: it cut a path
        # short and minted a record from the tail of a match. One trailing CR (a CRLF file's
        # line) is part of the terminator, as splitlines() treated it.
        for line in stdout.decode("utf-8", errors="replace").split("\n"):
            parsed = _parse_rg_line(line.removesuffix("\r"))
            if parsed is None:
                continue
            parsed_lines += 1
            # BF-908 A3: skipped before it is counted, so it never uses up max_results.
            if floor is not None and not floor.permits(parsed["path"]):
                continue
            matches.append(parsed)
            if len(matches) >= plan["max_results"]:
                break
        # BF-895 (#1548): exit 0 means rg found a match. If nothing parsed, the parser
        # and rg disagree: report nothing rather than a false zero, so act() falls back.
        # BF-908 A3: lines that parsed and that the floor refused are not that case.
        if not parsed_lines and (proc.returncode == 0 or stdout):
            logger.warning(
                "BF-895: rg exited %s with %d output bytes but no parsable match under %s; "
                "falling back to the Python engine",
                proc.returncode, len(stdout), root,
            )
            return None
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

    def _search_python(self, plan: dict, root: Path, *, floor: _ReadFloor | None = None) -> dict:
        """BF-908 A3/A4: no line of a file *floor* refuses is kept or counted. The floor is
        asked at a file's first match, so a walk pays for the files that match, not for every
        file it walks. A refused file is still read up to its first match, and ``iter_files``'s
        binary sniff reads up to 8 KiB of every file first; neither reaches a result.
        ``floor=None`` is the raw engine (the tests' control); ``act`` always passes one."""
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
            # BF-908 A5: the file's I/O and its OSError handler live in _text_lines; nothing in this
            # body (the floor's decision included) runs under that handler, so a floor defect propagates.
            for lineno, line in _text_lines(fp):
                if len(line) > _MAX_LINE_BYTES:
                    continue
                if rx.search(line):
                    # BF-908 A4: asked at the file's first match, after the open; later matches hit the cache.
                    if floor is not None and not floor.permits(str(fp)):
                        break  # BF-908 A4: a refused file is left at its first match; none of its lines is kept
                    matches.append({
                        "path": str(fp),
                        "line": lineno,
                        "text": line.rstrip("\n")[:_LINE_PREVIEW_CHARS],
                    })
                    if len(matches) >= max_results:
                        truncated = True
                        break
            if truncated:
                break
        return {
            "success": True,
            "data": matches,
            "count": len(matches),
            "engine": "python",
            "truncated": truncated,
        }


def _text_lines(fp: Path) -> Iterator[tuple[int, str]]:
    """BF-908 A5: ``(line number, line)`` for each line of *fp*, read as UTF-8 with replacement.

    A failure to open or read the file ends it: the lines already yielded stand and the engine
    goes on to the next file, as before A5. Only this generator's own I/O sits under the handler.
    An exception raised in the caller's loop body is not thrown into the generator it iterates,
    so an ``OSError`` from the read floor's decision propagates (D36, R16; review round 3 of
    C1b). A loop that breaks out drops the generator, and CPython closes it at once, which
    closes the file.
    """
    try:
        with fp.open("r", encoding="utf-8", errors="replace") as fh:
            yield from enumerate(fh, start=1)
    except OSError:  # BF-908 A5: the file cannot be opened or read; it contributes no further line
        return


class _ReadFloor:
    """BF-908 A3: the read floor for one search, built once, deciding each path once.

    The roots ``resolve_for_runtime`` uses, composed the way ``repository_instructions``
    and ``swe_harness/tools`` already do, so the per-file check costs one resolution,
    not a fresh floor (review round 1 of C1b measured 200 matches costing 200 floors
    and 1,000 ``Path.resolve()`` calls). Built per search, so the next search sees a
    changed runtime.
    """

    def __init__(self, runtime: Any) -> None:
        from probos.security.file_access import (
            permitted_read_roots,
            protected_read_roots,
            workspace_exempt_roots,
        )

        self._protected = protected_read_roots(runtime)
        self._exempt = workspace_exempt_roots(runtime)
        self._permitted = permitted_read_roots(runtime) or None
        self._decided: dict[str, bool] = {}

    def permits(self, path: str) -> bool:
        """True when a reader that calls the floor may open *path*."""
        if path not in self._decided:
            from probos.security.file_access import FileAccessDenied, resolve_read_path

            try:
                resolve_read_path(
                    path, protected_roots=self._protected, exempt_roots=self._exempt,
                    permitted_roots=self._permitted,
                )
            except FileAccessDenied:
                self._decided[path] = False
            else:
                self._decided[path] = True
        return self._decided[path]


def _within_floor(result: dict, floor: _ReadFloor) -> dict:
    """BF-908: drop every match in a file the read floor refuses (defence in depth).

    The root check in ``act`` admits a directory, and a root can hold a protected
    file (the checkout holding ``config/system.yaml``, or a folder above the data
    directory). Both engines skip such a file before counting its matches (A3); this
    re-checks what an engine returned, so an engine that forgets the floor still
    cannot return a protected file's lines. *floor* must be a fresh ``_ReadFloor``,
    built after the engine ran, never the one the engine asked (A4): it decides each
    distinct result path once, at this check. The decision is by path (residual R15).
    """
    matches = result.get("data")
    if not result.get("success") or not isinstance(matches, list):
        return result
    kept: list[Any] = []
    for match in matches:
        if isinstance(match, dict) and floor.permits(str(match.get("path", ""))):
            kept.append(match)
    if len(kept) == len(matches):
        return result
    logger.info("BF-908: content search dropped %d match(es) in files the read floor refuses", len(matches) - len(kept))
    return {**result, "data": kept, "count": len(kept)}


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
    """BF-895 (#1548): parse an ``rg --null --no-heading --line-number --with-filename``
    line, ``path<NUL>lineno:text``. No path can hold NUL, so the first NUL ends the path
    on every OS (drive letters, ``\\?\\``, NTFS streams, POSIX names with colons); the
    first ``:`` after it ends the line number, so text holding ``12:`` stays text."""
    path, sep, rest = line.partition("\x00")
    if not sep or not path:
        return None
    lineno, sep, text = rest.partition(":")
    if not sep or not (lineno.isascii() and lineno.isdigit()):
        return None
    try:
        number = int(lineno)
    except ValueError:  # over Python's int() digit limit: not a line number
        return None
    return {"path": path, "line": number, "text": text[:_LINE_PREVIEW_CHARS]}
