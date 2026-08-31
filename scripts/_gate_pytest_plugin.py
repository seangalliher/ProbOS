"""PYTEST_DONT_REWRITE: protect canonical broad-gate collection."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pytest

_COLLECTION_NODES: tuple[str, ...] = ()
_COLLECTION_FILES: tuple[str, ...] = ()
_FINAL_NODES: tuple[str, ...] = ()
_EXECUTED_NODES: set[str] = set()


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


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    terminal = report.when == "call" or (
        report.when in {"setup", "teardown"} and (report.failed or report.skipped)
    )
    if terminal:
        _EXECUTED_NODES.add(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
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
