"""BF-892 (#1543): every subprocess launch under src/ states its environment on purpose.

A launch passes ``env=`` from an owner in ``probos.execution.command_env``:
``build_command_env(...)`` (the allowlist; for commands or code the model or an agent
wrote) or ``trusted_command_env()`` (the runtime's environment; for argv ProbOS fixes,
each listed in TRUSTED_ENV_SITES with its reason). A dict display may extend an owner
(``{**build_command_env(), "PYTHONPATH": p}``) and a local name may carry one. An
environment that arrives from elsewhere (a parameter, another function) is INDIRECT and
listed in INDIRECT_ENV_SITES. Anything else fails: no env, env=None, a None branch,
``**kwargs`` without env, os.environ used whole by any route, a launch API bound by
reference, or a launch API that cannot take an environment.

Limits: a static scan cannot see these and they pass it silently, so they are a review
question, not a guard one: getattr(subprocess, "run") and other dynamic calls,
importlib-loaded modules, launches inside third-party libraries (Playwright's driver,
webbrowser), an environment mutated under a second name (``e = env; e.update(...)``), and a
mapping from elsewhere merged into a sanctioned base, which counts as an addition
(``{**build_command_env(), **request.env}`` stays allowlist). Import aliases resolve by
lexical scope (a function's own imports, then each enclosing function's, then the
module's); a name bound in no scope of that chain falls back to any scope's import of it,
so ``global``/``nonlocal`` imports are still seen; a later rebinding by assignment is not
tracked.
"""

from __future__ import annotations

import ast
import os
import textwrap
from collections import ChainMap, Counter, deque
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

from probos.execution.command_env import trusted_command_env

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
_OWNER = "probos.execution.command_env"
_ALLOWLIST_OWNER = f"{_OWNER}.build_command_env"
_TRUSTED_OWNER = f"{_OWNER}.trusted_command_env"
ALLOWLIST, TRUSTED, INDIRECT = "allowlist", "trusted", "indirect"
_FAIL_WHOLE_ENV = "fail: the runtime environment by another route; use trusted_command_env()"

_ENV_LAUNCHERS = frozenset({
    "subprocess.Popen", "subprocess.run", "subprocess.call", "subprocess.check_call",
    "subprocess.check_output", "asyncio.create_subprocess_exec", "asyncio.create_subprocess_shell",
    "asyncio.subprocess.create_subprocess_exec", "asyncio.subprocess.create_subprocess_shell",
})
_LOOP_LAUNCH_ATTRS = frozenset({"subprocess_exec", "subprocess_shell"})
#: Launch APIs the guard rejects: they take no environment (os.system, os.popen, getoutput,
#: pty.spawn, multiprocessing) or take one only positionally (os.execve/execle/execvpe,
#: os.spawnve/spawnle/spawnvpe/spawnlpe, os.posix_spawn[p]). Launch through subprocess or
#: asyncio with env=, which the guard can read.
_NO_ENV_LAUNCHERS = frozenset({
    "os.system", "os.popen", "os.startfile", "os.posix_spawn", "os.posix_spawnp",
    "subprocess.getoutput", "subprocess.getstatusoutput", "pty.spawn",
    "multiprocessing.Process", "multiprocessing.Pool", "concurrent.futures.ProcessPoolExecutor",
})
_NO_ENV_PREFIXES = ("os.exec", "os.spawn")
#: Launches found at 7301f647 (2026-10-14). The scan must reach at least these.
_KNOWN_LAUNCH_FLOOR = 39

TRUSTED_ENV_SITES: dict[tuple[str, str], tuple[int, str]] = {
    ("src/probos/__main__.py", "_ensure_ollama"): (1, "ollama serve: OLLAMA_* and GPU variables"),
    ("src/probos/__main__.py", "_check_nats"): (1, "nats-server, fixed argv"),
    ("src/probos/__main__.py", "_cmd_reset"): (2, "git add/commit in the Captain's repo during reset"),
    ("src/probos/agents/code_search.py", "CodeSearchAgent._search_rg"): (1, "rg; model text only as a bound --regexp/--glob value; RIPGREP_CONFIG_PATH"),
    ("src/probos/audio/tts/piper_backend.py", "PiperBackend.synthesize._run_sync"): (1, "piper; text on stdin"),
    ("src/probos/avatars/blender_renderer.py", "BlenderRenderer.render"): (1, "blender running ProbOS's own script"),
    ("src/probos/avatars/rhubarb_backend.py", "_convert_to_wav._run_sync"): (1, "ffmpeg, fixed argv"),
    ("src/probos/avatars/rhubarb_backend.py", "probe_version._probe_sync"): (1, "rhubarb --version"),
    ("src/probos/avatars/rhubarb_backend.py", "_run_rhubarb._run_sync"): (1, "rhubarb, fixed argv"),
    ("src/probos/cognitive/dm/artifact_extractor.py", "_to_docx_libreoffice"): (1, "soffice convert; content is data (follow-up: narrow)"),
    ("src/probos/cognitive/referent_gate.py", "GitObjectResolver._resolve_sync"): (1, "git cat-file -e -- <token>"),
    ("src/probos/cognitive/scout.py", "ScoutAgent._search_github"): (1, "gh api needs GH_TOKEN or gh config"),
    ("src/probos/credential_store.py", "CredentialStore._resolve"): (1, "credential helper (gh auth token)"),
    ("src/probos/doctor/checks/sandbox_check.py", "_docker_info_sync"): (1, "docker info: DOCKER_HOST"),
    ("src/probos/episodic_health.py", "check_episodic_health"): (1, "ProbOS's own probe module: PROBOS_* config"),
    ("src/probos/execution/authority.py", "_ManifestPreparer._repository_binding"): (3, "git with system/global config stripped"),
    ("src/probos/integrations/mcp_bridge/transport.py", "StdioTransport.start"): (1, "operator-approved MCP server (follow-up: narrow)"),
    ("src/probos/knowledge/records_store.py", "RecordsStore._git_sync"): (1, "git on the records repo"),
    ("src/probos/knowledge/store.py", "KnowledgeStore._git_run"): (1, "git on the knowledge repo"),
    ("src/probos/security/container_sandbox.py", "DockerContainerSandbox.run"): (1, "docker CLI on the host; the container gets only -e"),
    ("src/probos/worktree_manager.py", "WorktreeManager._run_git"): (1, "git worktree verbs"),
}
INDIRECT_ENV_SITES: dict[tuple[str, str], tuple[int, str]] = {
    ("src/probos/agents/red_team.py", "RedTeamAgent._run_verify_sync"): (2, "env parameter; its one caller passes build_command_env"),
    ("src/probos/execution/isolation.py", "SubprocessSandbox._run_sync_inner"): (1, "run_python sandbox: _build_env starts from SANDBOX_ENV_PASSTHROUGH"),
}


@dataclass(frozen=True)
class Launch:
    path: str
    line: int
    callee: str
    shape: str  # "direct" | "by-reference" | "bound"
    scope: str
    verdict: str

    def render(self) -> str:
        return f"{self.path}:{self.line} {self.callee} ({self.shape}, {self.scope}) -> {self.verdict}"


def _module_parts(rel_path: str) -> tuple[list[str], bool]:
    parts = list(Path(rel_path).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    is_package = bool(parts) and parts[-1] == "__init__"
    return (parts[:-1] if is_package else parts), is_package


def _scope_aliases(scope: ast.AST, rel_path: str) -> dict[str, str]:
    """Import aliases bound directly in *scope*'s own body (the module, or one function).

    A nested function is its own scope and is not entered; a class body is entered.
    """
    module, is_package = _module_parts(rel_path)
    package = module if is_package else module[:-1]
    names: dict[str, str] = {}
    pending = deque(ast.iter_child_nodes(scope))
    while pending:
        node = pending.popleft()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    names[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    names[head] = head
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                origin = ".".join([*base, node.module] if node.module else base)
            else:
                origin = node.module or ""
            for alias in node.names:
                names[alias.asname or alias.name] = f"{origin}.{alias.name}"
        pending.extend(ast.iter_child_nodes(node))
    return names


def _dotted(node: ast.AST, aliases: Mapping[str, str]) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(aliases.get(node.id, node.id))
    return ".".join(reversed(parts))


def _is_type_reference(node: ast.AST) -> bool:
    """A pure type expression: (dotted) names, constants, subscripts, unions, tuples/lists of these."""
    if isinstance(node, (ast.Name, ast.Constant)):
        return True
    if isinstance(node, ast.Attribute):
        return _dotted(node, {}) is not None
    if isinstance(node, ast.Subscript):
        return _is_type_reference(node.value) and _is_type_reference(node.slice)
    if isinstance(node, (ast.Tuple, ast.List)):
        return all(_is_type_reference(e) for e in node.elts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_type_reference(node.left) and _is_type_reference(node.right)
    return False


def _launcher(node: ast.AST, aliases: Mapping[str, str]) -> tuple[str, bool] | None:
    """(callee, takes_env) when *node* names a launch API."""
    dotted = _dotted(node, aliases)
    if dotted is not None:
        if dotted in _ENV_LAUNCHERS:
            return dotted, True
        if dotted in _NO_ENV_LAUNCHERS or dotted.startswith(_NO_ENV_PREFIXES):
            return dotted, False
    if isinstance(node, ast.Attribute) and node.attr in _LOOP_LAUNCH_ATTRS:
        return f"<loop>.{node.attr}", True
    return None


def _reads_whole_environment(expr: ast.AST, aliases: Mapping[str, str]) -> bool:
    """True when *expr* uses os.environ whole (copy, spread, pass), not one .get()/[...] read."""
    parents = {id(child): node for node in ast.walk(expr) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(expr):
        if _dotted(node, aliases) != "os.environ":
            continue
        parent = parents.get(id(node))
        if isinstance(parent, ast.Subscript) and parent.value is node:
            continue
        if isinstance(parent, ast.Attribute) and parent.attr == "get":
            continue
        return True
    return False


def _bindings(function: ast.AST, name: str) -> tuple[list[ast.AST | None], list[ast.AST]]:
    """(values bound to *name* in *function*'s own body, contributions merged into it); None = unreadable.

    A contribution is ``name |= x``, ``name[k] = v``, or an argument of ``name.update(...)`` /
    ``name.setdefault(...)``.
    """
    values: list[ast.AST | None] = []
    augmented: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(function))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    values.append(node.value)
                elif isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id == name:
                    augmented.append(node.value)
                elif not isinstance(target, (ast.Subscript, ast.Attribute)) and any(
                    isinstance(n, ast.Name) and n.id == name for n in ast.walk(target)
                ):
                    values.append(None)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            if node.value is not None:
                values.append(node.value)
        elif isinstance(node, ast.NamedExpr) and node.target.id == name:
            values.append(node.value)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            augmented.append(node.value)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr in ("update", "setdefault")
              and isinstance(node.func.value, ast.Name) and node.func.value.id == name):
            augmented.extend([*node.args, *(kw.value for kw in node.keywords)])
        elif isinstance(node, (ast.For, ast.AsyncFor)) and any(
            isinstance(n, ast.Name) and n.id == name for n in ast.walk(node.target)
        ):
            values.append(None)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None and any(
            isinstance(n, ast.Name) and n.id == name for n in ast.walk(node.optional_vars)
        ):
            values.append(None)
        stack.extend(ast.iter_child_nodes(node))
    return values, augmented


def _widest(verdicts: list[str]) -> str:
    if TRUSTED in verdicts:
        return TRUSTED
    return INDIRECT if INDIRECT in verdicts else ALLOWLIST


class _Scanner(ast.NodeVisitor):
    def __init__(self, tree: ast.Module, rel_path: str) -> None:
        self.path = rel_path
        module_aliases = _scope_aliases(tree, rel_path)
        self._alias_stack: list[dict[str, str]] = [module_aliases]  # module first
        # Every scope's imports in one map (what the whole-tree walk used to build): the fallback
        # for a name the lexical chain does not bind, i.e. a `global`/`nonlocal` import.
        self._every_alias: dict[str, str] = dict(module_aliases)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._every_alias.update(_scope_aliases(node, rel_path))
        self.scope: list[str] = []
        self.functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self.launches: list[Launch] = []
        self._consumed: set[int] = set()

    @property
    def aliases(self) -> ChainMap[str, str]:
        """Import aliases in force here: the lexical chain (innermost function first), then every scope's."""
        return ChainMap(*reversed(self._alias_stack), self._every_alias)

    def _enter(self, node: ast.AST, name: str, is_function: bool) -> None:
        self.scope.append(name)
        if is_function:
            self.functions.append(node)  # type: ignore[arg-type]
            self._alias_stack.append(_scope_aliases(node, self.path))
            args = node.args  # type: ignore[attr-defined]
            params = (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
            self._skip_annotations(node.returns, *(p.annotation for p in params if p is not None))  # type: ignore[attr-defined]
        self.generic_visit(node)
        if is_function:
            self._alias_stack.pop()
            self.functions.pop()
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.name, False)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter(node, node.name, True)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter(node, node.name, True)

    def _skip_annotations(self, *annotations: ast.AST | None) -> None:
        """A launch API named in a pure type annotation is not a launch or a binding; an
        annotation holding anything else (a call, a walrus) is scanned like code."""
        for annotation in annotations:
            if annotation is not None and _is_type_reference(annotation):
                self._consumed.update(id(n) for n in ast.walk(annotation))

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._skip_annotations(node.annotation)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        direct = _launcher(node.func, self.aliases)
        if direct is not None:
            self._consumed.add(id(node.func))
            self._record(node, direct, "direct")
        else:
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                ref = _launcher(arg, self.aliases)
                if ref is not None:
                    self._consumed.add(id(arg))
                    self._record(node, ref, "by-reference")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._bound(node)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        self._bound(node)

    def _bound(self, node: ast.AST) -> None:
        if id(node) in self._consumed:
            return
        ref = _launcher(node, self.aliases)
        if ref is not None:
            self.launches.append(Launch(self.path, node.lineno, ref[0], "bound", ".".join(self.scope) or "<module>",
                                        "fail: a launch API bound by reference; call it with env="))

    def _record(self, call: ast.Call, launcher: tuple[str, bool], shape: str) -> None:
        callee, takes_env = launcher
        verdict = self._verdict(call) if takes_env else (
            "fail: this launch API cannot be given env= (it takes none, or only positionally); "
            "launch through subprocess/asyncio with env="
        )
        self.launches.append(Launch(self.path, call.lineno, callee, shape, ".".join(self.scope) or "<module>", verdict))

    def _verdict(self, call: ast.Call) -> str:
        env = [kw.value for kw in call.keywords if kw.arg == "env"]
        if not env:
            if any(kw.arg is None for kw in call.keywords):
                return "fail: **kwargs without an explicit env="
            return "fail: no env="
        return self._classify(env[0], 0)

    def _classify(self, expr: ast.AST, depth: int) -> str:
        if depth > 6:
            return "fail: environment not resolvable"
        if isinstance(expr, ast.Constant) and expr.value is None:
            return "fail: env=None"
        if _reads_whole_environment(expr, self.aliases):
            return _FAIL_WHOLE_ENV
        if isinstance(expr, ast.Call):
            owner = _dotted(expr.func, self.aliases)
            if owner == _ALLOWLIST_OWNER:
                return ALLOWLIST
            if owner == _TRUSTED_OWNER:
                return TRUSTED
            return self._other(expr)
        if isinstance(expr, ast.Dict):
            if not expr.keys or expr.keys[0] is not None:
                return "fail: a dict environment must start with **build_command_env(...) or **trusted_command_env()"
            base = self._classify(expr.values[0], depth + 1)
            if base.startswith("fail"):
                return base
            if base not in (ALLOWLIST, TRUSTED):
                return "fail: a dict environment must start from a sanctioned owner"
            verdicts = [base]
            for key, value in zip(expr.keys[1:], expr.values[1:]):
                if key is None:
                    added = self._contribution(value, depth)
                    if added is not None and added.startswith("fail"):
                        return added
                    if added is not None:
                        verdicts.append(added)
            return _widest(verdicts)
        if isinstance(expr, ast.IfExp):
            branches = [self._classify(expr.body, depth + 1), self._classify(expr.orelse, depth + 1)]
            failed = [b for b in branches if b.startswith("fail")]
            return failed[0] if failed else _widest(branches)
        if isinstance(expr, ast.Name):
            return self._classify_name(expr.id, depth)
        return self._other(expr)

    def _other(self, expr: ast.AST) -> str:
        """A non-owner expression: trusted when it carries trusted_command_env anywhere."""
        if any(_dotted(n, self.aliases) == _TRUSTED_OWNER for n in ast.walk(expr)):
            return TRUSTED
        return INDIRECT

    def _contribution(self, expr: ast.AST, depth: int) -> str | None:
        """What merging *expr* into an environment adds: the whole-environment failure, TRUSTED,
        or None (an addition such as ``request.env`` or ``os.environ.get(...)``)."""
        verdict = self._classify(expr, depth + 1)
        return verdict if verdict in (_FAIL_WHOLE_ENV, TRUSTED) else None

    def _classify_name(self, name: str, depth: int) -> str:
        added: list[str] = []
        for function in reversed(self.functions):
            args = function.args
            params = {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}
            params |= {a.arg for a in (args.vararg, args.kwarg) if a is not None}
            values, contributions = _bindings(function, name)
            for contribution in contributions:
                extra = self._contribution(contribution, depth)
                if extra is not None and extra.startswith("fail"):
                    return extra
                if extra is not None:
                    added.append(extra)
            if values:
                verdicts = [
                    self._classify(v, depth + 1) if v is not None else "fail: environment bound in a way the guard cannot read"
                    for v in values
                ]
                failed = [v for v in verdicts if v.startswith("fail")]
                return failed[0] if failed else _widest([*verdicts, *added])
            if name in params:
                return _widest([INDIRECT, *added])
        return _widest([INDIRECT, *added])


def _scan_source(source: str, rel_path: str) -> list[Launch]:
    tree = ast.parse(source)
    scanner = _Scanner(tree, rel_path)
    scanner.visit(tree)
    return scanner.launches


@cache
def _scan_tree() -> tuple[Launch, ...]:
    launches: list[Launch] = []
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_REPO_ROOT).as_posix()
        launches.extend(_scan_source(path.read_text(encoding="utf-8-sig"), rel))
    return tuple(launches)


# --- the guard's tests -------------------------------------------------------------------------


def test_every_launch_under_src_states_its_environment() -> None:
    failures = [launch.render() for launch in _scan_tree() if launch.verdict.startswith("fail")]
    assert failures == []


@pytest.mark.parametrize(
    ("verdict", "inventory"),
    [(TRUSTED, TRUSTED_ENV_SITES), (INDIRECT, INDIRECT_ENV_SITES)],
    ids=[TRUSTED, INDIRECT],
)
def test_inventory_matches_the_code(verdict: str, inventory: dict[tuple[str, str], tuple[int, str]]) -> None:
    found = dict(Counter((launch.path, launch.scope) for launch in _scan_tree() if launch.verdict == verdict))
    listed = {site: count for site, (count, _reason) in inventory.items()}
    assert found == listed


def test_scan_reaches_the_known_launches() -> None:
    launches = _scan_tree()
    assert len(launches) >= _KNOWN_LAUNCH_FLOOR  # premise: the walk reaches the whole tree
    reached = {(launch.path, launch.scope, launch.shape, launch.verdict) for launch in launches}
    # `import asyncio as _asyncio` inside the function: only an alias-aware scan resolves it.
    assert ("src/probos/cognitive/swe_harness/tools.py", "RunCommandTool.invoke", "direct", ALLOWLIST) in reached
    # A launch API handed to asyncio.to_thread: only a by-reference scan sees it.
    assert ("src/probos/cognitive/scout.py", "ScoutAgent._search_github", "by-reference", TRUSTED) in reached


def test_trusted_command_env_is_a_copy_of_the_runtime_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    name = "BF892_TRUSTED_PLAIN"
    monkeypatch.setenv(name, "bf892-plain")
    env = trusted_command_env()
    # Single values go into locals before the assert, so a failure prints a value and never
    # the environment (`env.get(...)` inside the assert would print the whole dict).
    carried = env.get(name)
    assert carried == "bf892-plain"
    env[name] = "changed"
    left_alone = os.environ.get(name)
    assert left_alone == "bf892-plain"


_X_PATH = "src/probos/x.py"
_RELATIVE_PATH = "src/probos/execution/snippet.py"


def _case(case_id: str, source: str, shape: str, expected: str, rel_path: str = _X_PATH) -> object:
    return pytest.param(textwrap.dedent(source), shape, expected, rel_path, id=case_id)


# Each case plants exactly one launch. The test asserts that first (its premise), so a scanner
# that misses the launch, or invents a second, fails there instead of passing on an empty list.
_SHAPE_CASES = [
    _case("no-env", """\
        import subprocess
        subprocess.run(['x'])
        """, "direct", "fail: no env="),
    _case("env-none", """\
        import subprocess
        subprocess.run(['x'], env=None)
        """, "direct", "fail: env=None"),
    _case("kwargs-splat", """\
        import subprocess
        def f(**kw):
            subprocess.Popen(['x'], **kw)
        """, "direct", "fail: **kwargs"),
    _case("aliased-module", """\
        import subprocess as sp
        sp.Popen(['x'])
        """, "direct", "fail: no env="),
    _case("from-import", """\
        from subprocess import run
        run(['x'])
        """, "direct", "fail: no env="),
    _case("from-import-alias", """\
        from subprocess import Popen as P
        P(['x'])
        """, "direct", "fail: no env="),
    _case("aliased-asyncio", """\
        import asyncio as _a
        async def f():
            await _a.create_subprocess_shell('x')
        """, "direct", "fail: no env="),
    # Import aliases resolve by lexical scope: a function's own import shadows the module's only
    # inside that function (and the functions nested in it), never in a sibling function.
    _case("local-import-shadows-module-alias", """\
        import subprocess as sp
        def other():
            import json as sp
            return sp
        def launch():
            return sp.run(['x'])
        """, "direct", "fail: no env="),
    _case("sibling-local-alias-does-not-hide", """\
        def a():
            import subprocess as sp
            return sp.run(['x'])
        def b():
            import json as sp
            return sp
        """, "direct", "fail: no env="),
    # Control: a nested function still sees its enclosing function's import.
    _case("nested-function-sees-outer-import", """\
        def outer():
            import subprocess as sp
            def inner():
                return sp.run(['x'])
            return inner
        """, "direct", "fail: no env="),
    # A name bound in no scope of that chain falls back to any scope's import of it, so an import
    # bound through `global` in one function is still seen from another.
    _case("global-import-seen-from-another-function", """\
        def setup():
            global sp
            import subprocess as sp
        def launch():
            return sp.run(['x'])
        """, "direct", "fail: no env="),
    _case("asyncio-subprocess", """\
        import asyncio
        async def f():
            await asyncio.subprocess.create_subprocess_exec('x')
        """, "direct", "fail: no env="),
    _case("loop-method", """\
        async def f(loop, p):
            await loop.subprocess_exec(p, 'x')
        """, "direct", "fail: no env="),
    _case("to-thread", """\
        import asyncio, subprocess
        async def f():
            await asyncio.to_thread(subprocess.run, ['x'])
        """, "by-reference", "fail: no env="),
    _case("run-in-executor", """\
        import subprocess
        async def f(loop):
            await loop.run_in_executor(None, subprocess.run, ['x'])
        """, "by-reference", "fail: no env="),
    _case("partial", """\
        import functools, subprocess
        functools.partial(subprocess.run, ['x'])
        """, "by-reference", "fail: no env="),
    _case("bound", """\
        import subprocess
        launch = subprocess.run
        """, "bound", "fail: a launch API bound"),
    # Negative control for the annotation rule: an annotated NAME is skipped, its VALUE is not.
    _case("annotated-binding", """\
        import subprocess
        launch: object = subprocess.run
        """, "bound", "fail: a launch API bound"),
    _case("os-system", """\
        import os
        os.system('x')
        """, "direct", "fail: this launch API cannot"),
    _case("os-popen", """\
        import os
        os.popen('x')
        """, "direct", "fail: this launch API cannot"),
    _case("os-execv", """\
        import os
        os.execv('/bin/x', ['x'])
        """, "direct", "fail: this launch API cannot"),
    _case("os-spawnl", """\
        import os
        os.spawnl(os.P_WAIT, '/bin/x', 'x')
        """, "direct", "fail: this launch API cannot"),
    _case("getoutput", """\
        import subprocess
        subprocess.getoutput('x')
        """, "direct", "fail: this launch API cannot"),
    _case("multiprocessing", """\
        import multiprocessing
        multiprocessing.Process(target=print)
        """, "direct", "fail: this launch API cannot"),
    _case("environ-copy", """\
        import os, subprocess
        subprocess.run(['x'], env=os.environ.copy())
        """, "direct", "fail: the runtime environment"),
    _case("environ-dict", """\
        import os, subprocess
        subprocess.run(['x'], env=dict(os.environ))
        """, "direct", "fail: the runtime environment"),
    _case("environ-spread", """\
        import os, subprocess
        subprocess.run(['x'], env={**os.environ, 'A': 'b'})
        """, "direct", "fail: the runtime environment"),
    _case("environ-via-name", """\
        import os, subprocess
        def f():
            env = os.environ.copy()
            subprocess.run(['x'], env=env)
        """, "direct", "fail: the runtime environment"),
    _case("from-os-environ", """\
        from os import environ
        import subprocess
        subprocess.run(['x'], env=dict(environ))
        """, "direct", "fail: the runtime environment"),
    _case("none-branch", """\
        import subprocess
        from probos.execution.command_env import build_command_env
        def f(a):
            subprocess.run(['x'], env=build_command_env() if a else None)
        """, "direct", "fail: env=None"),
    _case("dict-without-owner", """\
        import subprocess
        subprocess.run(['x'], env={'PATH': '/bin'})
        """, "direct", "fail: a dict environment"),
    _case("allowlist-inline", """\
        import subprocess
        from probos.execution.command_env import build_command_env
        subprocess.run(['x'], env=build_command_env())
        """, "direct", ALLOWLIST),
    _case("allowlist-extended", """\
        import subprocess
        from probos.execution.command_env import build_command_env
        def f(p):
            subprocess.run(['x'], env={**build_command_env(), 'PYTHONPATH': p})
        """, "direct", ALLOWLIST),
    _case("allowlist-name-item", """\
        import os, subprocess
        from probos.execution.command_env import build_command_env
        def f():
            env = build_command_env()
            env['X'] = os.environ.get('X', '')
            subprocess.run(['x'], env=env)
        """, "direct", ALLOWLIST),
    _case("trusted-by-reference", """\
        import asyncio, subprocess
        from probos.execution.command_env import trusted_command_env
        async def f():
            await asyncio.to_thread(subprocess.run, ['x'], env=trusted_command_env())
        """, "by-reference", TRUSTED),
    _case("relative-owner", """\
        import subprocess
        from .command_env import build_command_env
        subprocess.run(['x'], env=build_command_env())
        """, "direct", ALLOWLIST, _RELATIVE_PATH),
    _case("parameter", """\
        import subprocess
        def f(env):
            subprocess.run(['x'], env=env)
        """, "direct", INDIRECT),
    _case("lookalike-owner", """\
        import subprocess
        def build_command_env():
            return {}
        subprocess.run(['x'], env=build_command_env())
        """, "direct", INDIRECT),
    _case("trusted-spread-widens", """\
        import subprocess
        from probos.execution.command_env import build_command_env, trusted_command_env
        subprocess.run(['x'], env={**build_command_env(), **trusted_command_env()})
        """, "direct", TRUSTED),
    _case("trusted-wrapped", """\
        import subprocess
        from probos.execution.command_env import trusted_command_env
        subprocess.run(['x'], env=dict(trusted_command_env()))
        """, "direct", TRUSTED),
    _case("environ-update", """\
        import os, subprocess
        from probos.execution.command_env import build_command_env
        def f():
            env = build_command_env()
            env.update(os.environ)
            subprocess.run(['x'], env=env)
        """, "direct", "fail: the runtime environment"),
    _case("environ-name-spread", """\
        import os, subprocess
        from probos.execution.command_env import build_command_env
        def f():
            extra = os.environ.copy()
            subprocess.run(['x'], env={**build_command_env(), **extra})
        """, "direct", "fail: the runtime environment"),
    _case("trusted-update-widens", """\
        import subprocess
        from probos.execution.command_env import build_command_env, trusted_command_env
        def f():
            env = build_command_env()
            env.update(trusted_command_env())
            subprocess.run(['x'], env=env)
        """, "direct", TRUSTED),
    _case("trusted-ior-widens", """\
        import subprocess
        from probos.execution.command_env import build_command_env, trusted_command_env
        def f():
            env = build_command_env()
            env |= trusted_command_env()
            subprocess.run(['x'], env=env)
        """, "direct", TRUSTED),
    # Negative controls: merging a mapping from elsewhere stays allowlist (container sandbox shape).
    _case("allowlist-request-spread", """\
        import subprocess
        from probos.execution.command_env import build_command_env
        def f(request):
            env = {**build_command_env(), **request.env}
            subprocess.run(['x'], env=env)
        """, "direct", ALLOWLIST),
    _case("allowlist-update-parameter", """\
        import subprocess
        from probos.execution.command_env import build_command_env
        def f(extra):
            env = build_command_env()
            env.update(extra)
            env.setdefault('LANG', 'C')
            subprocess.run(['x'], env=env)
        """, "direct", ALLOWLIST),
    _case("annotation-walrus", """\
        import subprocess
        x: (launch := subprocess.run) = None
        """, "bound", "fail: a launch API bound"),
    _case("parameter-annotation-walrus", """\
        import subprocess
        def f(a: (launch := subprocess.run) = None):
            return a
        """, "bound", "fail: a launch API bound"),
    _case("annotation-call", """\
        import subprocess
        x: subprocess.run(['x']) = None
        """, "direct", "fail: no env="),
    _case("os-spawnve", """\
        import os
        os.spawnve(os.P_WAIT, '/bin/x', ['x'], {})
        """, "direct", "fail: this launch API cannot"),
]


@pytest.mark.parametrize(("source", "shape", "expected", "rel_path"), _SHAPE_CASES)
def test_scanner_classifies_shape(source: str, shape: str, expected: str, rel_path: str) -> None:
    launches = _scan_source(source, rel_path)
    assert len(launches) == 1, [launch.render() for launch in launches]  # premise: exactly the planted launch
    assert launches[0].shape == shape
    assert launches[0].verdict.startswith(expected), launches[0].render()


# A launch API that appears only in a type annotation is neither a launch nor a binding. Every
# annotation position is here: positional-only, regular, keyword-only, *args and **kwargs
# arguments, the return, an AnnAssign in a function and in a class, a method's argument, and an
# attribute target. The AST is the same with or without `from __future__ import annotations`.
_ANNOTATION_ONLY = textwrap.dedent("""\
    import subprocess
    def f(p: subprocess.Popen[bytes], q: subprocess.Popen, /, *a: subprocess.Popen, r: subprocess.Popen, **k: subprocess.Popen) -> subprocess.Popen | None:
        x: subprocess.Popen | None = None
        y: list[subprocess.Popen[bytes]] | tuple[subprocess.Popen, ...] = []
        return p
    class C:
        proc: subprocess.Popen
        def m(self, other: subprocess.Popen) -> None:
            self.held: subprocess.Popen | None = None
    """)


@pytest.mark.parametrize("prefix", ["from __future__ import annotations\n", ""], ids=["future", "plain"])
def test_scanner_ignores_annotations(prefix: str) -> None:
    assert _scan_source(prefix + _ANNOTATION_ONLY, _X_PATH) == []
