"""PYTEST_DONT_REWRITE: protect canonical broad-gate collection."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import pytest

_COLLECTION_NODES: tuple[str, ...] = ()
_COLLECTION_FILES: tuple[str, ...] = ()
_FINAL_NODES: tuple[str, ...] = ()
_EXECUTED_NODES: set[str] = set()


def _stamp() -> dict[str, float]:
    return {"monotonic": time.monotonic(), "wall": time.time()}


# Timing is measurement only. Monotonic stamps are comparable within one worker
# process; wall stamps are the only values comparable across workers.
_TIMING_VERSION = 1
_TIMING_EVENTS: dict[str, dict[str, float] | None] = {
    "plugin_loaded": _stamp(),
    "session_start": None,
    "collection_finished": None,
    "first_test_start": None,
    "last_test_end": None,
    "session_finish": None,
}
_TIMING_FILES: dict[str, dict[str, Any]] = {}
_TIMING_FAULTS = 0


def _guarded(record: Callable[..., None], *arguments: object) -> None:
    """Run one timing recorder so that it can never fail the session.

    An exception inside a pytest hook becomes an internal error and would change
    the gate's exit code for what is only a measurement. A fault is counted
    instead, and the timing block is then withheld rather than written partial.
    """
    global _TIMING_FAULTS
    try:
        record(*arguments)
    except Exception:
        _TIMING_FAULTS += 1


def _file_of(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def _file_entry(file_name: str) -> dict[str, Any]:
    entry = _TIMING_FILES.get(file_name)
    if entry is None:
        entry = {"first_start": None, "last_end": None, "duration_seconds": 0.0}
        _TIMING_FILES[file_name] = entry
    return entry


def _note_event(name: str) -> None:
    _TIMING_EVENTS[name] = _stamp()


def _note_test_start(nodeid: str) -> None:
    now = _stamp()
    if _TIMING_EVENTS["first_test_start"] is None:
        _TIMING_EVENTS["first_test_start"] = now
    entry = _file_entry(_file_of(nodeid))
    if entry["first_start"] is None:
        entry["first_start"] = now


def _note_test_end(nodeid: str) -> None:
    now = _stamp()
    _file_entry(_file_of(nodeid))["last_end"] = now
    _TIMING_EVENTS["last_test_end"] = now


def _note_report_duration(report: pytest.TestReport) -> None:
    _file_entry(_file_of(report.nodeid))["duration_seconds"] += float(report.duration)


def _timing_payload() -> dict[str, Any] | None:
    """The ``timing`` block for gwN.json, or ``None`` when it cannot be trusted."""
    if _TIMING_FAULTS:
        return None
    try:
        node_counts: dict[str, int] = {}
        for nodeid in _EXECUTED_NODES:
            name = _file_of(nodeid)
            node_counts[name] = node_counts.get(name, 0) + 1
        return {
            "version": _TIMING_VERSION,
            "events": dict(_TIMING_EVENTS),
            "files": {
                name: {
                    "first_start": entry["first_start"],
                    "last_end": entry["last_end"],
                    "duration_seconds": entry["duration_seconds"],
                    "node_count": node_counts.get(name, 0),
                }
                for name, entry in sorted(_TIMING_FILES.items())
            },
        }
    except Exception:
        return None


def _digest(values: tuple[str, ...]) -> str:
    payload = json.dumps(values, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_collection_modifyitems(
    session: pytest.Session,
    config: pytest.Config,
    items: list[pytest.Item],
) -> Any:
    global _COLLECTION_FILES, _COLLECTION_NODES, _FINAL_NODES
    before = tuple(item.nodeid for item in items)
    before_files = tuple(
        sorted({item.location[0].replace("\\", "/") for item in items})
    )
    if len(before) != len(set(before)):
        raise pytest.UsageError("canonical gate collection contains duplicate node IDs")
    yield
    after = tuple(item.nodeid for item in items)
    _COLLECTION_NODES = tuple(sorted(before))
    _COLLECTION_FILES = before_files
    _FINAL_NODES = tuple(sorted(after))


def pytest_sessionstart() -> None:
    _guarded(_note_event, "session_start")


def pytest_collection_finish() -> None:
    _guarded(_note_event, "collection_finished")


def pytest_runtest_logstart(nodeid: str) -> None:
    _guarded(_note_test_start, nodeid)


def pytest_runtest_logfinish(nodeid: str) -> None:
    _guarded(_note_test_end, nodeid)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    terminal = report.when == "call" or (
        report.when in {"setup", "teardown"} and (report.failed or report.skipped)
    )
    if terminal:
        _EXECUTED_NODES.add(report.nodeid)
    _guarded(_note_report_duration, report)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _guarded(_note_event, "session_finish")
    worker_input = getattr(session.config, "workerinput", None)
    output_dir = os.environ.get("PROBOS_GATE_COLLECTION_DIR")
    if not isinstance(worker_input, dict) or not output_dir:
        return
    worker_id = str(worker_input.get("workerid", "unknown"))
    payload: dict[str, object] = {
        "schema_version": 1,
        "worker_id": worker_id,
        "exitstatus": int(exitstatus),
        "collection_count": len(_COLLECTION_NODES),
        "collection_sha256": _digest(_COLLECTION_NODES),
        "final_count": len(_FINAL_NODES),
        "final_sha256": _digest(_FINAL_NODES),
        "removed_nodeids": sorted(set(_COLLECTION_NODES) - set(_FINAL_NODES)),
        "added_nodeids": sorted(set(_FINAL_NODES) - set(_COLLECTION_NODES)),
        "executed_nodeids": sorted(_EXECUTED_NODES),
    }
    if worker_id == "gw0":
        payload["collected_nodeids"] = list(_COLLECTION_NODES)
        payload["collected_files"] = list(_COLLECTION_FILES)
    timing = _timing_payload()
    if timing is not None:
        payload["timing"] = timing
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{worker_id}.json"
    temporary = destination / f".{worker_id}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
