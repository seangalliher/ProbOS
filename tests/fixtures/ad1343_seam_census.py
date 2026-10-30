"""AD-1343 M0 (#1595): the AST census of ``src/probos`` that the stop's seam registry is checked against.

Lifted from ``tests/test_ad1343_stop_seam_inventory.py`` (S1) so the S1 inventory and the registry guard
(``tests/test_ad1343_seam_registry.py``) read one census; the data is ``tests/fixtures/ad1343_seam_registry.py``.

Report (never gated): ``python -m tests.fixtures.ad1343_seam_census`` prints every model call (``.complete(``) outside
the crew modules, by file, enclosing function and receiver, classified by ``MODEL_CALLS_OUTSIDE_CREW`` or structurally:
``agent class X`` when the enclosing class subclasses CognitiveAgent (by simple base name), else ``outside an agent class``.
"""

from __future__ import annotations

import ast
import functools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import probos
from tests.fixtures import ad1343_seam_registry as registry

PACKAGE = Path(probos.__file__).resolve().parent
ROOT = PACKAGE.parents[1]
IMPLEMENTATION = "src/probos/agent_stop.py"
STOP_CALLEES = frozenset({"active_stop", "tool_refusal", "refusal", "refuse_new_run"})
# M0: the calls a guard can be: the S1 stop questions, crew eligibility's and the verifier's.
GUARD_CALLEES = STOP_CALLEES | {"standing_stop", "_stopped"}
# M0: the agent-work entry primitives: CognitiveAgent's classified public coroutines (all but its lifecycle) and its
# synchronous work starters, so a coroutine added there is scanned as soon as S1's census classifies it.
AGENT_WORK_METHODS = frozenset(
    name for name, kind in registry.COGNITIVE_AGENT_COROUTINES.items() if kind != "lifecycle"
) | frozenset(registry.SYNC_WORK_STARTERS)
# Names other classes also use (a store's decide, an organ's act): such a call counts only when its receiver names an agent.
GENERIC_AGENT_METHODS = frozenset({"perceive", "decide", "act", "report", "consult"})
RECORDED = STOP_CALLEES | AGENT_WORK_METHODS | {
    "invoke", "issue_stop", "lift_stop", "standing_stop", "WorkItemAgenticExecutor", "CrewAssignmentResolver",
    "CrewSessionFinalizer", "_stopped", "complete",  # A3
    "CrewRecoveryTransientError", "finalize", "run_crew_task",  # N1
    "shadow_at",  # AD-1346 M3c: the shadow statement beside a stop check
    "hold_at",  # AD-1346 M3d2: the work-ticket hold an admitted entry takes (tests/test_ad1346_admission_ticket_issue.py, I10)
}
PINNED_KEYWORDS = frozenset({"admitted_turn", "agent_stops", "admitted_synthesis"})  # recorded as "name=value" on any call passing one
CREW_PREFIX = "src/probos/cognitive/crew_"


@dataclass(frozen=True)
class Call:
    file: str
    function: str
    callee: str
    receiver: str
    seam: str
    keywords: tuple[str, ...] = ()


class Visitor(ast.NodeVisitor):
    def __init__(self, rel: str) -> None:
        self._rel = rel
        self._scope: list[str] = []
        self.calls: list[Call] = []

    def _enter(self, node: ast.AST, name: str) -> None:
        self._scope.append(name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._enter(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute):
            callee, receiver = func.attr, ast.unparse(func.value)
        elif isinstance(func, ast.Name):
            callee, receiver = func.id, ""
        else:
            callee, receiver = "", ""
        keywords = tuple(f"{k.arg}={ast.unparse(k.value)}" for k in node.keywords if k.arg in PINNED_KEYWORDS)
        if callee in RECORDED or keywords:
            seam = ""
            if callee == "refusal" and len(node.args) >= 2:
                seam = ast.unparse(node.args[1])
            elif callee == "active_stop" and len(node.args) >= 3:
                seam = ast.unparse(node.args[2])
            elif callee == "tool_refusal":
                seam = "SEAM_TOOL"
            elif callee == "refuse_new_run":
                seam = "SEAM_AGENTIC_RUN"
            elif callee == "CrewRecoveryTransientError" and node.args:  # N1: the transient code it is built with
                seam = ast.unparse(node.args[0])
            self.calls.append(Call(self._rel, ".".join(self._scope) or "<module>", callee, receiver, seam, keywords))
        self.generic_visit(node)


def scan(source: bytes | str, rel: str) -> tuple[Call, ...]:
    """The census of one module's source, read as the repo-relative path ``rel``."""
    visitor = Visitor(rel)
    visitor.visit(ast.parse(source, filename=rel))
    return tuple(visitor.calls)


@functools.lru_cache(maxsize=1)
def census() -> tuple[Call, ...]:
    found: list[Call] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        found += scan(path.read_bytes(), path.relative_to(ROOT).as_posix())
    return tuple(found)


def function(rel: str, qualname: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse((ROOT / rel).read_bytes(), filename=rel)

    def walk(body: list[ast.stmt], prefix: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        for node in body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = f"{prefix}.{node.name}" if prefix else node.name
                if name == qualname and not isinstance(node, ast.ClassDef):
                    return node
                hit = walk(node.body, name)
                if hit is not None:
                    return hit
        return None

    found = walk(tree.body, "")
    assert found is not None, (rel, qualname)
    return found


def calls(name: str) -> Callable[[ast.AST], bool]:
    def match(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        return (isinstance(func, ast.Attribute) and func.attr == name) or (
            isinstance(func, ast.Name) and func.id == name
        )
    return match


def first_line(node: ast.AST, predicate: Callable[[ast.AST], bool]) -> int:
    lines = [n.lineno for n in ast.walk(node) if predicate(n)]
    assert lines, f"nothing matched in {getattr(node, 'name', node)}"
    return min(lines)


def is_agent_work_call(call: Call) -> bool:
    """M0: a call that starts another agent's work: a primitive called as an attribute on a receiver other than the caller."""
    if call.callee not in AGENT_WORK_METHODS or call.receiver in ("", "self") or call.receiver.startswith("super("):
        return False
    if call.callee in GENERIC_AGENT_METHODS:
        last = call.receiver.split(".")[-1]
        return last == "agent" or last.endswith("_agent")
    return True


def agent_work_calls() -> frozenset[tuple[str, str, str]]:
    """Every (file, enclosing function, callee) in ``src/probos`` that starts another agent's work."""
    return frozenset((c.file, c.function, c.callee) for c in census() if is_agent_work_call(c))


@functools.lru_cache(maxsize=1)
def agent_classes() -> frozenset[str]:
    """Class names in ``src/probos`` that subclass ``CognitiveAgent``, resolved by simple base name (report only)."""
    bases: dict[str, set[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_bytes())):
            if isinstance(node, ast.ClassDef):
                bases.setdefault(node.name, set()).update(ast.unparse(base).split(".")[-1] for base in node.bases)
    found = {"CognitiveAgent"}
    while True:
        more = {name for name, parents in bases.items() if parents & found} - found
        if not more:
            return frozenset(found)
        found |= more


def model_call_report() -> tuple[tuple[str, str, str, str], ...]:
    """Report only: (file, function, receiver, classification) for each model call outside the crew modules."""
    rows = {
        (c.file, c.function, c.receiver)
        for c in census()
        if c.callee == "complete" and c.receiver and not c.file.startswith(CREW_PREFIX)
    }
    report = []
    for file, function_name, receiver in sorted(rows):
        how = registry.MODEL_CALLS_OUTSIDE_CREW.get((file, function_name))
        if how is None:
            owner = function_name.split(".")[0]
            how = f"agent class {owner}" if owner in agent_classes() else "outside an agent class"
        report.append((file, function_name, receiver, how))
    return tuple(report)


if __name__ == "__main__":
    rows = model_call_report()
    for file, function_name, receiver, how in rows:
        print(f"{file}::{function_name}  {receiver}.complete(...)  {how}")
    print(f"{len(rows)} model call sites outside the crew modules (report only; #1601 M3 gates them)")
