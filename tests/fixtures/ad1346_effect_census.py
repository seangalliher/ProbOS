"""AD-1346 M3e1 (#1604): the sink set of property 1 and the census of its subprocess effect point.

#1604 property 1 asks that every effect-point primitive (model call, tool call, subprocess, egress, store write) call the
shadow ``decide()`` or the shadow sink check, or hold a pinned ``system`` principal from a pinned allowlist. ``EFFECT_CLASSES`` names those five
classes and the slice that covers each; ``DELIVERED`` names the ones a member of ``TICKET_EFFECTS`` covers.

The subprocess class is read from BF-892's launch scan (``_scan_tree`` in ``tests/test_bf892_spawn_env_guard.py``, whose
module docstring lists what a static scan cannot see). Each (file, enclosing function) that scan finds is a row of
``SUBPROCESS_SITES`` with its launch count and one coverage:

- ``Sink(check, presented, service, via)``: the function ``check`` of the same file holds a ``check_at`` call for
  ``EFFECT_SUBPROCESS`` with ``service`` (by default ``SERVICE_EXPR``) as its service and ``presented`` as its presented
  id; ``via`` names, in call order, the functions between ``check`` and the launching one (AD-1346 M3e2a);
- ``System(principal, reason)``: a launch in a Ship's Computer service, under ``principal``;
- ``OutsideRuntime(reason)``: a launch in a module under ``OUTSIDE_RUNTIME``;
- ``Pending(owner, reason)``: a launch whose sink the slice ``owner`` adds;
- ``Unreached(names, reason)``: a launch that no other ``src`` code reaches through ``names`` (AD-1346 M3e2a).

``tests/test_ad1346_admission_effect_census.py`` checks the rows against the code, and SK7
(``tests/test_ad1346_admission_ticket_sinks.py``) reads ``subprocess_sink_functions``.
"""

from __future__ import annotations

import ast
import functools
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import probos
from probos.admission.taxonomy import SYSTEM_PRINCIPAL_PREFIX
from tests.test_bf892_spawn_env_guard import _scan_tree

PACKAGE = Path(probos.__file__).resolve().parent
ROOT = PACKAGE.parents[1]
SHIP: Final = "system:ship_computer"
#: The service a subprocess sink hands ``check_at``: its runtime's, read with ``getattr`` defaults as the M3c sites read it.
SERVICE_EXPR: Final = "getattr(getattr(self, '_runtime', None), 'admission_service', None)"
#: The operator's command line: ``probos.__main__`` and the doctor package (D167).
OUTSIDE_RUNTIME: Final = ("src/probos/__main__.py", "src/probos/doctor/")
_OUTSIDE_MODULES: Final = ("probos.__main__", "probos.doctor")
_SEAM_HELPERS: Final = frozenset({"shadow_at", "hold_at", "check_at"})

#: #1604 property 1's five classes and what covers each (D168).
EFFECT_CLASSES: Final[dict[str, str]] = {
    "model_call": "AD-1346 M3d3a: OpenAICompatibleClient.complete (SK7, SK8)",
    "tool": "AD-1346 M3d3a: ToolRegistry.check_and_invoke (SK7)",
    "subprocess": "AD-1346 M3e1 and M3e2a: SUBPROCESS_SITES; its Pending row, AD-1346 M3e2b",
    "egress": "AD-1346 M3e3",
    "store_write": "AD-1346 M3e4",
}
#: The classes a member of ``TICKET_EFFECTS`` covers.
DELIVERED: Final = frozenset({"model_call", "tool", "subprocess"})


@dataclass(frozen=True)
class Sink:
    check: str
    presented: str
    service: str = SERVICE_EXPR  # AD-1346 M3e2a: a component handed its service passes ``self._admission`` (D175)
    via: tuple[str, ...] = ()  # AD-1346 M3e2a: the functions between ``check`` and the launching one, in call order (D179)


@dataclass(frozen=True)
class System:
    principal: str
    reason: str


@dataclass(frozen=True)
class OutsideRuntime:
    reason: str


@dataclass(frozen=True)
class Pending:
    owner: str
    reason: str


@dataclass(frozen=True)
class Unreached:
    names: tuple[str, ...]
    reason: str


_TOOL_PRESENTED: Final = "context.get('agent_id') if type(context) is dict else None"

#: AD-1346 M3e2a (D175): the service a component handed it passes to ``check_at``.
_COMPONENT_SERVICE: Final = "self._admission"
#: AD-1346 M3e2a (D177): the names by which other src code could reach the container sandboxes' launches.
_CONTAINER_NAMES: Final = ("container_sandbox", "InProcessContainerSandbox", "DockerContainerSandbox", "get_container_sandbox")

#: (file, enclosing function as BF-892 scopes it) -> (launches there, coverage). D163; AD-1346 M3e2a: D174 to D178.
SUBPROCESS_SITES: Final[dict[tuple[str, str], tuple[int, Sink | System | OutsideRuntime | Pending | Unreached]]] = {
    # Sinks: a launch an agent or model text directs, as that agent's work.
    ("src/probos/agents/shell_command.py", "ShellCommandAgent._run_sync"): (2, Sink("ShellCommandAgent._run_command", "None")),
    ("src/probos/agents/red_team.py", "RedTeamAgent._run_verify_sync"): (2, Sink("RedTeamAgent._verify_run_command", "None")),
    ("src/probos/agents/code_search.py", "CodeSearchAgent._search_rg"): (1, Sink("CodeSearchAgent._search_rg", "None")),
    ("src/probos/cognitive/scout.py", "ScoutAgent._search_github"): (1, Sink("ScoutAgent._search_github", "self.id")),
    ("src/probos/cognitive/swe_harness/tools.py", "RunCommandTool.invoke"): (1, Sink("RunCommandTool.invoke", _TOOL_PRESENTED)),
    # AD-1346 M3e2a: two components handed the service (D175, D176).
    ("src/probos/execution/isolation.py", "SubprocessSandbox._run_sync_inner"): (1, Sink("SubprocessSandbox.run", "None", service=_COMPONENT_SERVICE, via=("SubprocessSandbox._run_sync",))),
    ("src/probos/cognitive/dependency_resolver.py", "DependencyResolver._install_package"): (3, Sink("DependencyResolver._install_package", "None", service=_COMPONENT_SERVICE)),
    # Pending: the launching code holds no service today (register R76).
    ("src/probos/cognitive/builder.py", "_run_targeted_tests._sync_run"): (1, Pending("M3e2b", "model-authored tests of an approved build")),
    # Unreached: no other src code reaches the launch through its names (D177).
    ("src/probos/cognitive/builder.py", "_run_tests._sync_run"): (1, Unreached(("_run_tests",), "the whole suite; no build path calls it since BF-897")),
    ("src/probos/security/container_sandbox.py", "InProcessContainerSandbox.run"): (1, Unreached(_CONTAINER_NAMES, "a thread workspace command; no other src module names the module")),
    ("src/probos/security/container_sandbox.py", "DockerContainerSandbox.run"): (1, Unreached(_CONTAINER_NAMES, "a thread workspace command; no other src module names the module")),
    # System: a launch in a Ship's Computer service.
    ("src/probos/cognitive/builder.py", "_run_git._sync_run"): (1, System(SHIP, "the build pipeline's git verbs, hardened (BF-904a); names and messages are data")),
    ("src/probos/cognitive/builder.py", "_is_dirty_working_tree"): (2, System(SHIP, "git rev-parse and status of the build tree, fixed argv")),
    ("src/probos/audio/tts/resident.py", "PiperWorker._spawn"): (1, System(SHIP, "resident piper; text on stdin")),
    ("src/probos/avatars/blender_renderer.py", "BlenderRenderer.render"): (1, System(SHIP, "blender running ProbOS's own script")),
    ("src/probos/avatars/rhubarb_backend.py", "_convert_to_wav._run_sync"): (1, System(SHIP, "ffmpeg, fixed argv")),
    ("src/probos/avatars/rhubarb_backend.py", "probe_version._probe_sync"): (1, System(SHIP, "rhubarb --version")),
    ("src/probos/avatars/rhubarb_backend.py", "_run_rhubarb._run_sync"): (1, System(SHIP, "rhubarb, fixed argv")),
    ("src/probos/cognitive/dm/artifact_extractor.py", "_to_docx_libreoffice"): (1, System(SHIP, "soffice convert; the text is data")),
    ("src/probos/cognitive/referent_gate.py", "GitObjectResolver._resolve_sync"): (1, System(SHIP, "git cat-file -e -- <token>, the gate's own check")),
    ("src/probos/credential_store.py", "CredentialStore._resolve"): (1, System(SHIP, "a registered credential helper")),
    ("src/probos/episodic_health.py", "check_episodic_health"): (1, System(SHIP, "ProbOS's own probe module")),
    ("src/probos/execution/authority.py", "_ManifestPreparer._repository_binding"): (3, System(SHIP, "the protected execution authority's manifest git")),
    ("src/probos/integrations/mcp_bridge/transport.py", "StdioTransport.start"): (1, System(SHIP, "an operator-approved MCP server")),
    ("src/probos/knowledge/records_store.py", "RecordsStore._git_sync"): (1, System(SHIP, "git on the records repo")),
    ("src/probos/knowledge/store.py", "KnowledgeStore._git_run"): (1, System(SHIP, "git on the knowledge repo")),
    ("src/probos/worktree_manager.py", "WorktreeManager._run_git"): (1, System(SHIP, "git worktree verbs")),
    # The operator's command line.
    ("src/probos/__main__.py", "_ensure_ollama"): (1, OutsideRuntime("ollama serve")),
    ("src/probos/__main__.py", "_check_nats"): (1, OutsideRuntime("nats-server")),
    ("src/probos/__main__.py", "_cmd_reset"): (2, OutsideRuntime("git add and commit during probos reset")),
    ("src/probos/doctor/checks/sandbox_check.py", "_docker_info_sync"): (1, OutsideRuntime("docker info for probos doctor")),
}


@functools.lru_cache(maxsize=1)
def src_sources() -> dict[str, str]:
    """Every module under ``src/probos`` by repo-relative path, as text (do not mutate the cached dict)."""
    return {path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8-sig") for path in sorted(PACKAGE.rglob("*.py"))}


def launch_counts() -> dict[tuple[str, str], int]:
    """BF-892's launches by (file, enclosing function)."""
    return dict(Counter((launch.path, launch.scope) for launch in _scan_tree()))


def launch_lines() -> dict[tuple[str, str], list[int]]:
    """BF-892's launch lines by (file, enclosing function)."""
    lines: dict[tuple[str, str], list[int]] = {}
    for launch in _scan_tree():
        lines.setdefault((launch.path, launch.scope), []).append(launch.line)
    return lines


def subprocess_sink_functions() -> set[tuple[str, str]]:
    """(file, function) of each subprocess sink's check."""
    return {(path, cover.check) for (path, _scope), (_count, cover) in SUBPROCESS_SITES.items() if isinstance(cover, Sink)}


def census_problems(found: dict[tuple[str, str], int], listed: dict[tuple[str, str], tuple[int, object]]) -> list[str]:
    """What differs between launches found and rows listed: unlisted sites, stale rows, then differing counts."""
    problems = [f"unlisted launch site {site}" for site in sorted(found.keys() - listed.keys())]
    problems += [f"stale row {site}" for site in sorted(listed.keys() - found.keys())]
    problems += [
        f"{site}: {found[site]} launches, the row says {listed[site][0]}"
        for site in sorted(found.keys() & listed.keys())
        if found[site] != listed[site][0]
    ]
    return problems


def references_outside(tree: ast.Module, name: str, allowed: tuple[str, ...]) -> list[tuple[str, int]]:
    """(enclosing function, line) of each reference to ``name``, as an attribute or a bare name, outside ``allowed``."""
    found: list[tuple[str, int]] = []

    def walk(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, (*scope, child.name))
                continue
            qualname = ".".join(scope)
            named = (isinstance(child, ast.Attribute) and child.attr == name) or (isinstance(child, ast.Name) and child.id == name)
            if named and qualname not in allowed:
                found.append((qualname or "<module>", child.lineno))
            walk(child, scope)

    walk(tree, ())
    return found


def system_principal_literals(sources: dict[str, str]) -> set[str]:
    """The ``system:`` strings a ``shadow_at``, ``hold_at`` or ``check_at`` call passes as a literal ``presented_id``."""
    found: set[str] = set()
    for rel, source in sources.items():
        if not any(helper in source for helper in _SEAM_HELPERS):
            continue
        for node in ast.walk(ast.parse(source, filename=rel)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            callee = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            if callee not in _SEAM_HELPERS:
                continue
            for keyword in node.keywords:
                value = keyword.value
                if (
                    keyword.arg == "presented_id" and isinstance(value, ast.Constant) and isinstance(value.value, str)
                    and value.value.startswith(SYSTEM_PRINCIPAL_PREFIX)
                ):
                    found.add(value.value)
    return found


def outside_importers(sources: dict[str, str]) -> list[tuple[str, int]]:
    """(file, line) of each absolute import of ``probos.__main__`` or the doctor package by a module not under
    ``OUTSIDE_RUNTIME``."""
    found: list[tuple[str, int]] = []
    for rel, source in sources.items():
        if rel.startswith(OUTSIDE_RUNTIME) or ("__main__" not in source and "doctor" not in source):
            continue
        for node in ast.walk(ast.parse(source, filename=rel)):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
                names = [node.module] + ([f"probos.{alias.name}" for alias in node.names] if node.module == "probos" else [])
            else:
                continue
            if any(name == module or name.startswith(f"{module}.") for name in names for module in _OUTSIDE_MODULES):
                found.append((rel, node.lineno))
    return found
