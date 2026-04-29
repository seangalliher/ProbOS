"""Tests for AD-680 public runtime API promotion."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

from probos.events import EventType
from probos.protocols import EventEmitterProtocol
from probos.runtime import ProbOSRuntime


def _minimal_runtime() -> ProbOSRuntime:
    runtime = ProbOSRuntime.__new__(ProbOSRuntime)
    runtime._event_listeners = []
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
    pattern = re.compile(
        r"runtime\._emit_event|rt\._emit_event|self\._runtime\._emit_event|"
        r"getattr\((?:runtime|rt|self\._runtime),\s*['\"]_emergence_metrics_engine['\"]"
    )
    matches: list[tuple[Path, int, str]] = []

    for path in src_root.rglob("*.py"):
        if path.name == "runtime.py":
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                matches.append((path.relative_to(src_root), line_number, line.strip()))

    assert matches == []
