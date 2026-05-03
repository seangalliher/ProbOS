#!/usr/bin/env python
"""Phantom-API kwarg validation helper (AD-685).

Walks `src/probos/` building an AST signature index keyed by method name.
For each `<obj>.<method>(<kwargs>)` call site found in a (pre-filtered)
prompt body, validates kwarg names against any matching signature.

Inputs:
    --src-root <path>   Root of src/probos to scan.
    Body on stdin       Pre-filtered prompt body (PowerShell wrapper applies
                        the shared pre-filter; this helper trusts its input).

Output (stdout, UTF-8 JSON):
    {"phantoms": [
        {"call_site": "...", "method": "...", "kwarg": "...",
         "candidates": [{"file": "...", "line": N, "params": [...]}]},
        ...
    ]}

Heuristics applied AFTER the wrapper's shared pre-filter:
- If a method name has multiple definitions across src/, accept the kwarg
  if ANY signature accepts it. Documented limitation: receiver-class
  resolution deferred to AD-685c/d.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# Module-level cache for the AST signature index. A single orchestrator
# stage often scans multiple prompts in a row; rebuilding the index per
# call would be wasteful (AD-685, Recommended #1 promotion).
_INDEX_CACHE: dict[str, dict[str, list[dict]]] = {}

# Stdlib / common third-party method names that are noisy to validate.
# These are method names where false-positive risk outweighs catch rate.
_NOISY_METHODS = frozenset({
    "format", "join", "split", "strip", "replace", "startswith", "endswith",
    "lower", "upper", "encode", "decode", "items", "keys", "values", "get",
    "append", "extend", "pop", "remove", "insert", "count", "index", "copy",
    "update", "clear", "setdefault", "fromkeys",
    "dumps", "loads", "dump", "load",
    "match", "search", "findall", "finditer", "sub", "compile",
    "info", "debug", "warning", "error", "exception", "critical", "log",
    "execute", "executemany", "fetchone", "fetchall", "commit", "rollback",
    "create_task", "gather", "sleep", "wait", "wait_for", "run",
    "assert_called", "assert_called_with", "assert_called_once",
    "assert_called_once_with", "assert_not_called", "assert_any_call",
    "side_effect", "return_value",
    "now", "fromtimestamp", "fromisoformat", "strftime", "strptime",
    "read_text", "write_text", "read_bytes", "write_bytes", "exists", "mkdir",
    "is_file", "is_dir", "iterdir", "glob", "rglob", "resolve", "absolute",
    "model_dump", "model_validate", "model_dump_json",
})

# Receivers that are clearly stdlib / third-party — skip their calls entirely.
_NOISY_RECEIVER_TOKENS = frozenset({
    "self", "cls", "super",
    "asyncio", "json", "os", "sys", "time", "logging", "pathlib", "re",
    "datetime", "uuid", "math", "hashlib", "subprocess", "shutil",
    "pytest", "httpx", "logger", "log", "config", "kwargs", "args",
    "Mock", "MagicMock", "AsyncMock",
    "Path", "True", "False", "None",
})

# `<obj>.<method>(<kwargs>)` with kwargs we can statically inspect.
# Match: receiver.method(arg=value, ...). Receiver is a single identifier
# (chained receivers like a.b.c are matched on the LAST segment to avoid
# walking the chain). The kwarg block stops at the first unbalanced ')'.
_CALL_RE = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-z_][a-z0-9_]*)\s*\(([^()]*)\)",
)
_KWARG_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\s*=")


def build_index(src_root: Path) -> dict[str, list[dict]]:
    """Build a method-name -> list of signature dicts index from src/probos.

    Cached at module level keyed by absolute src_root. First call per
    process is cold; subsequent calls reuse the cached index.
    """
    cache_key = str(src_root.resolve())
    if cache_key in _INDEX_CACHE:
        return _INDEX_CACHE[cache_key]

    index: dict[str, list[dict]] = {}
    for py_file in src_root.rglob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (OSError, SyntaxError):
            # Skip unreadable / unparseable files — index is best-effort.
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = _collect_param_names(node)
                index.setdefault(node.name, []).append({
                    "file": str(py_file.relative_to(src_root.parent.parent)
                                  if src_root.parent.parent in py_file.parents
                                  else py_file),
                    "line": node.lineno,
                    "params": params,
                    "accepts_kwargs": _has_var_keyword(node),
                })

    _INDEX_CACHE[cache_key] = index
    return index


def _collect_param_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Collect every accepted parameter name (positional + keyword-only)."""
    args = func.args
    names: list[str] = []
    for a in args.posonlyargs:
        names.append(a.arg)
    for a in args.args:
        names.append(a.arg)
    for a in args.kwonlyargs:
        names.append(a.arg)
    if args.vararg is not None:
        names.append(args.vararg.arg)
    if args.kwarg is not None:
        names.append(args.kwarg.arg)
    return names


def _has_var_keyword(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if the function accepts **kwargs (any kwarg passes)."""
    return func.args.kwarg is not None


def find_kwarg_phantoms(body: str, index: dict[str, list[dict]]) -> list[dict]:
    """Scan `body` for kwarg phantoms against the signature index.

    Returns a list of phantom records, each describing a call site whose
    kwarg name does not match any same-named definition's parameter list.
    """
    phantoms: list[dict] = []
    for match in _CALL_RE.finditer(body):
        receiver = match.group(1)
        method = match.group(2)
        kwarg_block = match.group(3)
        if receiver in _NOISY_RECEIVER_TOKENS:
            continue
        if method in _NOISY_METHODS:
            continue
        candidates = index.get(method)
        if not candidates:
            # Method not in src — that's a symbol phantom (PowerShell
            # wrapper handles it via existing regex). Skip here.
            continue
        # If any candidate accepts **kwargs, every kwarg name is valid.
        if any(c["accepts_kwargs"] for c in candidates):
            continue
        accepted_params: set[str] = set()
        for c in candidates:
            accepted_params.update(c["params"])
        for kw_match in _KWARG_RE.finditer(kwarg_block):
            kwarg_name = kw_match.group(1)
            if kwarg_name in accepted_params:
                continue
            call_site = f"{receiver}.{method}({kwarg_block.strip()})"
            phantoms.append({
                "call_site": call_site,
                "method": method,
                "kwarg": kwarg_name,
                "candidates": candidates[:5],
            })
    return phantoms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="AST-aware kwarg validator for phantom-API pre-check (AD-685).",
    )
    parser.add_argument(
        "--src-root",
        required=True,
        type=Path,
        help="Path to src/probos/ (or other source tree to index).",
    )
    args = parser.parse_args(argv)

    if not args.src_root.is_dir():
        print(json.dumps({
            "phantoms": [],
            "error": f"src-root not found: {args.src_root}",
        }), flush=True)
        return 2

    # Read pre-filtered body from stdin (UTF-8).
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    body = sys.stdin.read()

    # Ensure stdout is UTF-8 to avoid Windows codepage surprises (Nit #4).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    index = build_index(args.src_root)
    phantoms = find_kwarg_phantoms(body, index)
    print(json.dumps({"phantoms": phantoms}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
