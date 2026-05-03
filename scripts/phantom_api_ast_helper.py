#!/usr/bin/env python
"""Phantom-API kwarg + method-name validation helper (AD-685, AD-685b).

Walks `src/probos/` building two AST indexes:
  1. Method signature index keyed by method name (AD-685 v1) — used to
     validate kwarg names against any matching signature.
  2. Class method index keyed by class name (AD-685b) — used to validate
     `<obj>.<method>(...)` call sites where `<obj>` resolves to a class.

For each `<obj>.<method>(<kwargs>)` call site found in a (pre-filtered)
prompt body, validates:
  - kwarg names against any matching signature (AD-685 v1), AND
  - method-name existence on the resolved class (AD-685b).

Class resolution heuristic (AD-685b, conservative):
  - Pattern A — `runtime.X` resolution from `runtime.py` and
    `startup/finalize.py`. 4-level priority order:
      1. `AnnAssign` in runtime.py (highest fidelity — explicit type hint).
      2. `Assign` with `Call` RHS in finalize.py (instantiation site).
      3. `Assign` with `Call` RHS in runtime.py `__init__` (fallback).
      4. Unresolved (skip).
    Same-priority conflicts (different classes) → emit `unresolved`
    record with `pattern_a_conflict` reason; never guess.
  - Pattern B — `<var> = SomeClass(...)` assignment within prompt body.
    First-assignment-wins. Reassignment to different class →
    `pattern_b_reassignment` (skip subsequent call sites on `<var>`).
  - Skip when class resolution fails — emit `unresolved` record only for
    Pattern A (runtime.X) sites; bare-var unresolveds are silently
    skipped to avoid flooding output.

Inputs:
    --src-root <path>   Root of src/probos to scan.
    Body on stdin       Pre-filtered prompt body (PowerShell wrapper applies
                        the shared pre-filter; this helper trusts its input).

Output (stdout, UTF-8 JSON):
    {"phantoms": [
        # AD-685 v1 kwarg phantoms (no `category` field for back-compat):
        {"call_site": "...", "method": "...", "kwarg": "...",
         "candidates": [{"file": "...", "line": N, "params": [...]}]},
        # AD-685b method-name phantoms:
        {"call_site": "...", "obj": "...", "resolved_class": "...",
         "method": "...", "category": "method_phantom",
         "candidates_at": ["..."]},
    ],
     "unresolved": [
        {"call_site": "...", "obj": "...", "reason": "..."},
        ...
     ]}

Heuristics applied AFTER the wrapper's shared pre-filter:
- If a method name has multiple definitions across src/, accept the kwarg
  if ANY signature accepts it (AD-685 v1).
- For method-name validation, class methods include sync + async defs but
  exclude dunders. Multiple ClassDef definitions of same name → union of
  methods (no inheritance walk in v1 — deferred).
- AST-only — never imports from src/probos/ (would break sandbox).
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

# AD-685b caches.
# class_name -> set of public method names (sync + async, dunders excluded).
_CLASS_METHODS_CACHE: dict[str, dict[str, set[str]]] = {}
# attr_name -> resolved class_name for `runtime.X` access.
_RUNTIME_ATTRS_CACHE: dict[str, dict[str, str]] = {}
# attrs whose Pattern A resolution conflicted (different classes at same
# priority level) — emit `pattern_a_conflict` unresolved on use.
_RUNTIME_CONFLICTS_CACHE: dict[str, set[str]] = {}

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


# ---------------------------------------------------------------------------
# AD-685b: Method-name validation against resolved class.
# ---------------------------------------------------------------------------

# `runtime.X.method(...)` — Pattern A call site (chained on runtime).
_RUNTIME_CALL_RE = re.compile(
    r"\bruntime\.([a-zA-Z_][a-zA-Z0-9_]*)\.([a-z_][a-z0-9_]+)\s*\(",
)
# `<var> = SomeClass(...)` — Pattern B assignment in prompt body.
_PATTERN_B_RE = re.compile(
    r"^\s*([a-z_][a-zA-Z0-9_]*)\s*=\s*([A-Z][a-zA-Z0-9_]+)\s*\(",
    re.MULTILINE,
)


def _extract_class_from_annotation(node: ast.AST) -> str | None:
    """Resolve a class name from a type annotation AST node.

    Handles `Name`, `Optional[X]`, `X | None`, `None | X`, `list[X]` (only
    the inner type if it's `Optional`/`X | None`-shaped — list/dict don't
    resolve to a single class). Returns None if no single class resolves.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Subscript):
        # Optional[X] -> X. Other subscripts (list[X], dict[K, V]) don't
        # resolve to a single class.
        if isinstance(node.value, ast.Name) and node.value.id == "Optional":
            return _extract_class_from_annotation(node.slice)
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        # X | None or None | X (or even X | Y | None) — extract the first
        # non-None Name on either side recursively.
        for side in (node.left, node.right):
            if _is_none_node(side):
                continue
            cls = _extract_class_from_annotation(side)
            if cls is not None:
                return cls
        return None
    return None


def _is_none_node(node: ast.AST) -> bool:
    """True if AST node represents `None` (literal or Name)."""
    if isinstance(node, ast.Constant) and node.value is None:
        return True
    if isinstance(node, ast.Name) and node.id == "None":
        return True
    return False


def _extract_class_from_call(call: ast.Call) -> str | None:
    """Resolve a class name from a Call node.

    Returns the callee name only if it looks like a CamelCase class. Bare
    lowercase calls (factory functions) return None — we can't tell which
    class they construct without runtime semantics.
    """
    if isinstance(call.func, ast.Name):
        name = call.func.id
        if name and name[0].isupper():
            return name
    if isinstance(call.func, ast.Attribute):
        # `module.SomeClass(...)` form — take the attribute name.
        if call.func.attr and call.func.attr[0].isupper():
            return call.func.attr
    return None


def build_class_method_index(src_root: Path) -> dict[str, set[str]]:
    """Build a class_name -> set of method names index.

    Includes sync + async method definitions. Excludes dunders. When the
    same class name is defined in multiple files (or refined by multiple
    ClassDef nodes), unions the methods — no inheritance walk in v1.
    """
    cache_key = str(src_root.resolve())
    if cache_key in _CLASS_METHODS_CACHE:
        return _CLASS_METHODS_CACHE[cache_key]

    classes: dict[str, set[str]] = {}
    for py_file in src_root.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            methods: set[str] = set()
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = item.name
                    if name.startswith("__") and name.endswith("__"):
                        continue
                    methods.add(name)
            if methods or node.name not in classes:
                classes.setdefault(node.name, set()).update(methods)

    _CLASS_METHODS_CACHE[cache_key] = classes
    return classes


def build_runtime_attr_index(src_root: Path) -> tuple[dict[str, str], set[str]]:
    """Build a runtime attribute -> class_name index.

    Returns (resolved, conflicts):
      - resolved: attr_name -> class_name (Pattern A priority order applied).
      - conflicts: attrs where same-priority matches gave different classes.

    Pattern A priority order (first hit wins):
      1. AnnAssign of `self.X: SomeClass` in runtime.py.
      2. Assign+Call of `runtime.X = SomeClass(...)` in finalize.py.
      3. Assign+Call of `self.X = SomeClass(...)` in runtime.py.
      4. Unresolved (skipped — emitted as `no_class_resolution`).

    Within a single priority level, multiple matches with the same class
    are fine (concordant). Different classes at the same priority →
    `pattern_a_conflict` (recorded in `conflicts`; resolution skipped).

    No git blame in v1 — conservative skip-on-conflict satisfies the
    "never guess" intent (AD-685b spec, Pattern A tie-breaking clause;
    the architect-noted commit-date tiebreak is documented as deferred).
    """
    cache_key = str(src_root.resolve())
    if cache_key in _RUNTIME_ATTRS_CACHE:
        conflicts = _RUNTIME_CONFLICTS_CACHE.get(cache_key, set())
        return _RUNTIME_ATTRS_CACHE[cache_key], conflicts

    runtime_py = src_root / "runtime.py"
    finalize_py = src_root / "startup" / "finalize.py"

    p1: dict[str, set[str]] = {}  # AnnAssign in runtime.py: attr -> {classes}
    p2: dict[str, set[str]] = {}  # Assign+Call in finalize.py
    p3: dict[str, set[str]] = {}  # Assign+Call in runtime.py

    if runtime_py.is_file():
        try:
            tree = ast.parse(runtime_py.read_text(encoding="utf-8"), filename=str(runtime_py))
            for node in ast.walk(tree):
                if isinstance(node, ast.AnnAssign):
                    target = node.target
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                    ):
                        cls = _extract_class_from_annotation(node.annotation)
                        if cls is not None:
                            p1.setdefault(target.attr, set()).add(cls)
                elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                    cls = _extract_class_from_call(node.value)
                    if cls is None:
                        continue
                    for tgt in node.targets:
                        if (
                            isinstance(tgt, ast.Attribute)
                            and isinstance(tgt.value, ast.Name)
                            and tgt.value.id == "self"
                        ):
                            p3.setdefault(tgt.attr, set()).add(cls)
        except (OSError, SyntaxError):
            pass

    if finalize_py.is_file():
        try:
            tree = ast.parse(finalize_py.read_text(encoding="utf-8"), filename=str(finalize_py))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
                    continue
                cls = _extract_class_from_call(node.value)
                if cls is None:
                    continue
                for tgt in node.targets:
                    if (
                        isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name)
                        and tgt.value.id == "runtime"
                    ):
                        p2.setdefault(tgt.attr, set()).add(cls)
        except (OSError, SyntaxError):
            pass

    resolved: dict[str, str] = {}
    conflicts: set[str] = set()
    all_attrs = set(p1) | set(p2) | set(p3)
    for attr in all_attrs:
        for tier in (p1, p2, p3):
            if attr not in tier:
                continue
            classes = tier[attr]
            if len(classes) == 1:
                resolved[attr] = next(iter(classes))
                break
            # Same-priority conflict — skip, never guess.
            conflicts.add(attr)
            break

    _RUNTIME_ATTRS_CACHE[cache_key] = resolved
    _RUNTIME_CONFLICTS_CACHE[cache_key] = conflicts
    return resolved, conflicts


def _resolve_pattern_b(body: str) -> tuple[dict[str, str], set[str]]:
    """Resolve `<var> = SomeClass(...)` assignments in the prompt body.

    Returns (var -> class, set of unresolved-due-to-reassignment vars).

    Conservative approach: first-assignment-wins. If a later assignment
    targets the same var with a DIFFERENT class, the var is marked
    unresolved and removed from the resolved map — no line-aware scoping
    in v1 (`pattern_b_reassignment` reason emitted on use).
    """
    first: dict[str, str] = {}
    unresolved: set[str] = set()
    for match in _PATTERN_B_RE.finditer(body):
        var = match.group(1)
        cls = match.group(2)
        if var in unresolved:
            continue
        if var in first:
            if first[var] != cls:
                unresolved.add(var)
                first.pop(var, None)
            continue
        first[var] = cls
    return first, unresolved


def find_method_phantoms(
    body: str,
    class_methods: dict[str, set[str]],
    runtime_attrs: dict[str, str],
    runtime_conflicts: set[str],
    pattern_b_vars: dict[str, str],
    pattern_b_unresolved: set[str],
) -> tuple[list[dict], list[dict]]:
    """Scan body for method-name phantoms; return (phantoms, unresolved).

    Pattern A (runtime.X.method) emits `unresolved` records when class
    resolution fails or conflicts. Pattern B (bare-var.method) silently
    skips unresolved cases to avoid flooding the output (the bare-var
    namespace includes stdlib aliases, fixture parameters, etc.).
    """
    phantoms: list[dict] = []
    unresolved: list[dict] = []
    seen_unresolved: set[str] = set()

    def _add_unresolved(call_site: str, obj: str, reason: str) -> None:
        key = f"{call_site}::{reason}"
        if key in seen_unresolved:
            return
        seen_unresolved.add(key)
        unresolved.append({"call_site": call_site, "obj": obj, "reason": reason})

    # --- Pattern A: runtime.X.method(...) ---
    for match in _RUNTIME_CALL_RE.finditer(body):
        attr = match.group(1)
        method = match.group(2)
        if method in _NOISY_METHODS:
            continue
        obj_str = f"runtime.{attr}"
        call_site = f"{obj_str}.{method}(...)"

        if attr in runtime_conflicts:
            _add_unresolved(call_site, obj_str, "pattern_a_conflict")
            continue

        cls = runtime_attrs.get(attr)
        if cls is None:
            _add_unresolved(call_site, obj_str, "no_class_resolution")
            continue

        methods = class_methods.get(cls)
        if methods is None:
            # Class itself unknown (e.g., third-party) — conservative skip.
            _add_unresolved(call_site, obj_str, "no_class_resolution")
            continue

        if method not in methods:
            phantoms.append({
                "call_site": call_site,
                "obj": obj_str,
                "resolved_class": cls,
                "method": method,
                "category": "method_phantom",
                "candidates_at": sorted(methods)[:5],
            })

    # --- Pattern B: bare-var.method(...) ---
    for match in _CALL_RE.finditer(body):
        # Skip dotted-chain receivers (already handled by Pattern A).
        if match.start() > 0 and body[match.start() - 1] == ".":
            continue
        receiver = match.group(1)
        method = match.group(2)
        if receiver in _NOISY_RECEIVER_TOKENS:
            continue
        if receiver == "runtime":
            continue  # Pattern A territory.
        if method in _NOISY_METHODS:
            continue

        call_site = f"{receiver}.{method}(...)"

        if receiver in pattern_b_unresolved:
            _add_unresolved(call_site, receiver, "pattern_b_reassignment")
            continue

        cls = pattern_b_vars.get(receiver)
        if cls is None:
            # Conservative silent skip — bare-var namespace includes
            # stdlib aliases, function parameters, fixture names, etc.
            # Emitting `no_class_resolution` for every such match would
            # flood the output (per AD-685b R1 wrapper-display target).
            continue

        methods = class_methods.get(cls)
        if methods is None:
            continue

        if method not in methods:
            phantoms.append({
                "call_site": call_site,
                "obj": receiver,
                "resolved_class": cls,
                "method": method,
                "category": "method_phantom",
                "candidates_at": sorted(methods)[:5],
            })

    return phantoms, unresolved


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
    class_methods = build_class_method_index(args.src_root)
    runtime_attrs, runtime_conflicts = build_runtime_attr_index(args.src_root)
    pattern_b_vars, pattern_b_unresolved = _resolve_pattern_b(body)

    kwarg_phantoms = find_kwarg_phantoms(body, index)
    method_phantoms, unresolved = find_method_phantoms(
        body,
        class_methods,
        runtime_attrs,
        runtime_conflicts,
        pattern_b_vars,
        pattern_b_unresolved,
    )

    print(json.dumps({
        "phantoms": kwarg_phantoms + method_phantoms,
        "unresolved": unresolved,
    }), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
