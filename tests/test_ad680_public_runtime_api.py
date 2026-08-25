"""Tests for AD-680 public runtime API promotion."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from probos.events import EventType
from probos.protocols import EventEmitterProtocol
from probos.runtime import ProbOSRuntime

# BF-853: matched as attribute access rather than as text, so a docstring or
# comment naming the API is not mistaken for a use of it. The receiver test is
# a SUFFIX match because the regex this replaces matched anywhere in the line,
# so it also caught ownership forms like ``wrapper.runtime`` and
# ``self.runtime``. Those are ordinary, not evasion -- narrowing to an exact set
# would have made the guard weaker while looking cleaner.
_FORBIDDEN_SUFFIXES = ("runtime", "rt")


def _is_forbidden_receiver(receiver: str) -> bool:
    return bool(receiver) and receiver.endswith(_FORBIDDEN_SUFFIXES)


def _dotted(node: ast.expr) -> str:
    """Source-level dotted name of a receiver, or "" if it is not a plain chain."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


def _is_getattr(func: ast.expr) -> bool:
    """``getattr(...)`` however it is spelled, including ``builtins.getattr``."""
    if isinstance(func, ast.Name):
        return func.id == "getattr"
    return isinstance(func, ast.Attribute) and func.attr == "getattr"


def _private_runtime_access(source: str, path: str) -> list[tuple[str, int, str]]:
    """Every private-runtime reach in ``source``, as (path, line, expression)."""
    hits: list[tuple[str, int, str]] = []
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith("_emit_event"):
            receiver = _dotted(node.value)
            if _is_forbidden_receiver(receiver):
                hits.append((path, node.lineno, f"{receiver}.{node.attr}"))
        elif isinstance(node, ast.Call) and _is_getattr(node.func) and len(node.args) >= 2:
            receiver = _dotted(node.args[0])
            wanted = node.args[1]
            if (
                _is_forbidden_receiver(receiver)
                and isinstance(wanted, ast.Constant)
                and wanted.value == "_emergence_metrics_engine"
            ):
                hits.append((
                    path, node.lineno,
                    f"getattr({receiver}, '_emergence_metrics_engine')",
                ))

    return sorted(hits)


def _minimal_runtime() -> ProbOSRuntime:
    runtime = ProbOSRuntime.__new__(ProbOSRuntime)
    runtime._event_listeners = []
    runtime._live_event_listeners = []
    runtime._event_listener_tasks = set()
    runtime._nats_publish_tasks = set()
    runtime.nats_bus = None
    runtime._check_night_order_escalation = lambda _event_type, _data: None
    return runtime


def test_emit_event_accepts_event_type_enum() -> None:
    runtime = _minimal_runtime()

    runtime.emit_event(EventType.LLM_HEALTH_CHANGED, {"new_status": "degraded"})

    runtime_annotation = inspect.signature(ProbOSRuntime.emit_event).parameters["event"].annotation
    protocol_annotation = inspect.signature(EventEmitterProtocol.emit_event).parameters["event"].annotation
    assert "EventType" in str(runtime_annotation)
    assert "EventType" in str(protocol_annotation)


def test_emergence_metrics_engine_property() -> None:
    runtime = ProbOSRuntime.__new__(ProbOSRuntime)
    sentinel: object = object()
    runtime._emergence_metrics_engine = sentinel

    assert runtime.emergence_metrics_engine is sentinel


def test_emergence_metrics_engine_default_none() -> None:
    runtime = ProbOSRuntime.__new__(ProbOSRuntime)
    runtime._emergence_metrics_engine = None

    assert runtime.emergence_metrics_engine is None


def test_no_private_emit_event_in_external_modules() -> None:
    src_root = Path(__file__).resolve().parents[1] / "src" / "probos"
    matches: list[tuple[str, int, str]] = []

    for path in src_root.rglob("*.py"):
        if path.name == "runtime.py":
            continue
        matches.extend(
            _private_runtime_access(
                path.read_text(encoding="utf-8"), str(path.relative_to(src_root)),
            )
        )

    assert matches == []


def test_the_guard_catches_every_forbidden_receiver() -> None:
    """The guard must still fail on real access, or it is decoration.

    Includes the ownership forms (``wrapper.runtime``, ``self.runtime``) and
    qualified ``builtins.getattr`` that the replaced regex caught by matching
    anywhere in the line, and all three getattr receivers -- restricting the
    getattr branch to ``self._runtime`` alone otherwise survives mutation.
    """
    source = (
        "def a(runtime):\n"
        "    runtime._emit_event('x', {})\n"
        "    getattr(runtime, '_emergence_metrics_engine')\n"
        "def b(rt):\n"
        "    rt._emit_event_local('x', {})\n"
        "    getattr(rt, '_emergence_metrics_engine')\n"
        "def c(wrapper):\n"
        "    wrapper.runtime._emit_event('x', {})\n"
        "class C:\n"
        "    def m(self):\n"
        "        self._runtime._emit_event('x', {})\n"
        "        self.runtime._emit_event('x', {})\n"
        "        builtins.getattr(self._runtime, '_emergence_metrics_engine')\n"
    )

    found = {expr for _, _, expr in _private_runtime_access(source, "s.py")}

    assert found == {
        "runtime._emit_event",
        "rt._emit_event_local",
        "wrapper.runtime._emit_event",
        "self._runtime._emit_event",
        "self.runtime._emit_event",
        "getattr(runtime, '_emergence_metrics_engine')",
        "getattr(rt, '_emergence_metrics_engine')",
        "getattr(self._runtime, '_emergence_metrics_engine')",
    }


def test_the_guard_ignores_prose_that_names_the_api() -> None:
    """BF-853: a text scan cannot tell a requirement from a mention of it.

    This guard failed a full gate against a docstring explaining *why* the
    surrounding code took a reservation before its first await -- arguably the
    most useful comment in that module. The pressure from a false positive is
    to delete or mangle the explanation, which makes the codebase worse to keep
    the test green. Matching attribute nodes drops docstrings and comments for
    free, because neither is an attribute access.
    """
    source = (
        "def f(runtime):\n"
        '    """Note: runtime._emit_event is private; use emit_event.\n'
        "\n"
        "    self._runtime._emit_event and rt._emit_event are also out, and\n"
        "    getattr(runtime, '_emergence_metrics_engine') is too.\n"
        '    """\n'
        "    # runtime._emit_event here as well\n"
        "    return runtime.emit_event('x', {})\n"
    )

    assert _private_runtime_access(source, "s.py") == []
