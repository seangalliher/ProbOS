"""Read-only timing helpers shared by the canonical gate wrapper and gate-balance.

Measurement only. Nothing here validates a gate, changes an exit code, or
authorizes a release: only a validated success receipt from the gate wrapper
does that. The module is the single owner of four things, so the wrapper's
duration budget and the ``--gate-balance`` report cannot disagree about one run:

* ``junit_node_id``: a JUnit ``testcase`` element to a pytest node ID;
* per-worker busy time, from the ``timing`` block of each ``gwN.json`` when it is
  present and valid, otherwise from the JUnit durations of the worker's
  ``executed_nodeids``;
* the critical-path worker and its dominant file;
* the report-only duration budget.

It uses only the standard library, imports neither the wrapper nor the selector,
and only reads the JUnit report and the ``gw*.json`` files it is handed.
"""

from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

#: Version of the ``timing`` block of ``gwN.json`` that this module reads.
TIMING_VERSION = 1

#: Version of the ``duration_budget`` record.
BUDGET_VERSION = 1

EVENT_NAMES: tuple[str, ...] = (
    "plugin_loaded",
    "session_start",
    "collection_finished",
    "first_test_start",
    "last_test_end",
    "session_finish",
)

# Budget policy. Report-only: nothing reads these to fail a gate. They are looked
# up when a budget is built, not bound as defaults, so a test can lower them.
_DURATION_BUDGET_TEST_SECONDS = 10.0
_DURATION_BUDGET_FILE_SECONDS = 120.0
_DURATION_BUDGET_MEAN_BUSY_SHARE = 0.5
_DURATION_BUDGET_ITEM_LIMIT = 500

_ERROR_TEXT_LIMIT = 500
_WORKER_FILE_RE = re.compile(r"^gw(\d+)\.json$")

Stamp = Mapping[str, float]


def junit_node_id(attributes: dict[str, str]) -> str | None:
    """Reconstruct a pytest node ID from a JUnit ``testcase`` element.

    ``classname`` is the dotted module path plus any class chain, so the class
    chain is whatever remains after stripping the module derived from ``file``.
    """
    file_name = (attributes.get("file") or "").replace("\\", "/").removeprefix("./")
    name = attributes.get("name") or ""
    classname = attributes.get("classname") or ""
    if not file_name.endswith(".py") or not name:
        return None
    module = file_name[: -len(".py")].replace("/", ".")
    if classname == module:
        chain: list[str] = []
    elif classname.startswith(f"{module}."):
        chain = classname[len(module) + 1 :].split(".")
    else:
        return None
    return "::".join([file_name, *chain, name])


@dataclass(frozen=True)
class JUnitTimes:
    """Durations read from one JUnit report.

    ``nodes`` keeps every resolved node ID in document order, duplicates
    included. ``node_seconds`` and ``file_seconds`` sum duplicates.
    """

    testcase_count: int
    unresolved: int
    nodes: tuple[str, ...]
    node_seconds: dict[str, float]
    file_seconds: dict[str, float]


def _seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        return 0.0
    return value if math.isfinite(value) else 0.0


def read_junit_times(junit_path: Path) -> JUnitTimes:
    """Read the duration of every ``testcase`` in ``junit_path``.

    Raises ``ET.ParseError`` or ``OSError`` when the report cannot be read. A
    ``time`` attribute that is absent, unparsable or not finite counts as 0.
    """
    root = ET.parse(junit_path).getroot()
    testcases = [
        element
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "testcase"
    ]
    nodes: list[str] = []
    node_seconds: dict[str, float] = {}
    file_seconds: dict[str, float] = {}
    unresolved = 0
    for testcase in testcases:
        node = junit_node_id(dict(testcase.attrib))
        if node is None:
            unresolved += 1
            continue
        nodes.append(node)
        seconds = _seconds(testcase.attrib.get("time", "0"))
        node_seconds[node] = node_seconds.get(node, 0.0) + seconds
        file_name = node.split("::", 1)[0]
        file_seconds[file_name] = file_seconds.get(file_name, 0.0) + seconds
    return JUnitTimes(
        testcase_count=len(testcases),
        unresolved=unresolved,
        nodes=tuple(nodes),
        node_seconds=node_seconds,
        file_seconds=file_seconds,
    )


@dataclass(frozen=True)
class WorkerTiming:
    """A validated version-1 ``timing`` block."""

    events: dict[str, Stamp | None]
    file_seconds: dict[str, float]


@dataclass(frozen=True)
class WorkerEvidence:
    """One worker's ``gwN.json``; ``timing`` is ``None`` when absent or rejected."""

    worker: str
    index: int
    executed_nodeids: tuple[str, ...]
    timing: WorkerTiming | None


@dataclass(frozen=True)
class WorkerLoad:
    """Every readable worker file, in numeric worker order, plus what was wrong."""

    workers: tuple[WorkerEvidence, ...]
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


class _TimingRejected(ValueError):
    """A ``timing`` block that must not be trusted; the caller falls back to JUnit."""


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _is_stamp(value: object) -> bool:
    return (
        isinstance(value, dict)
        and _is_finite(value.get("monotonic"))
        and _is_finite(value.get("wall"))
    )


def _read_timing(value: object, executed_count: int) -> WorkerTiming:
    if not isinstance(value, dict):
        raise _TimingRejected("the timing block is not an object")
    if not _is_int(value.get("version")) or value["version"] != TIMING_VERSION:
        raise _TimingRejected(f"unsupported timing version {value.get('version')!r}")
    events = value.get("events")
    files = value.get("files")
    if not isinstance(events, dict) or not isinstance(files, dict):
        raise _TimingRejected("the timing block lacks an events or files object")
    parsed_events: dict[str, Stamp | None] = {}
    for name in EVENT_NAMES:
        if name not in events:
            raise _TimingRejected(f"timing event {name} is missing")
        stamp = events[name]
        if stamp is not None and not _is_stamp(stamp):
            raise _TimingRejected(f"timing event {name} is not a stamp")
        parsed_events[name] = stamp
    file_seconds: dict[str, float] = {}
    counted = 0
    for file_name, entry in files.items():
        if not isinstance(entry, dict):
            raise _TimingRejected(f"timing file entry {file_name} is not an object")
        seconds = entry.get("duration_seconds")
        count = entry.get("node_count")
        if not _is_finite(seconds) or seconds < 0 or not _is_int(count) or count < 0:
            raise _TimingRejected(f"timing file entry {file_name} has a bad duration")
        for key in ("first_start", "last_end"):
            if key not in entry or (
                entry[key] is not None and not _is_stamp(entry[key])
            ):
                raise _TimingRejected(f"timing file entry {file_name} has a bad {key}")
        file_seconds[file_name] = float(seconds)
        counted += count
    if counted != executed_count:
        raise _TimingRejected(
            f"the timing block counts {counted} executed nodes but the worker "
            f"executed {executed_count}"
        )
    return WorkerTiming(events=parsed_events, file_seconds=file_seconds)


def _worker_problem(payload: object, worker: str) -> str | None:
    if not isinstance(payload, dict):
        return "not a JSON object"
    if payload.get("schema_version") != 1:
        return f"schema_version is {payload.get('schema_version')!r}, expected 1"
    if payload.get("worker_id") != worker:
        return f"worker_id is {payload.get('worker_id')!r}, expected {worker!r}"
    executed = payload.get("executed_nodeids")
    if not isinstance(executed, list) or not all(
        isinstance(node, str) for node in executed
    ):
        return "executed_nodeids is not a list of strings"
    return None


def default_workers_dir(collection_path: Path) -> Path:
    """The per-worker directory the gate keeps next to ``<stem>.collection.json``."""
    suffix = ".collection.json"
    name = collection_path.name
    stem = name[: -len(suffix)] if name.endswith(suffix) else collection_path.stem
    return collection_path.with_name(f"{stem}.collection-workers")


def load_worker_evidence(workers_dir: Path) -> WorkerLoad:
    """Read every ``gw*.json`` in ``workers_dir``.

    A worker file that cannot be read or is structurally invalid is an error. A
    missing or empty directory is only a warning, because gates that predate the
    per-worker directory exist. A ``timing`` block that is present but rejected
    is a warning too: the worker is then measured from JUnit instead.
    """
    if not workers_dir.is_dir():
        return WorkerLoad(
            (),
            (),
            (f"no per-worker evidence directory at {workers_dir.as_posix()}",),
        )
    paths = sorted(workers_dir.glob("gw*.json"))
    if not paths:
        return WorkerLoad(
            (),
            (),
            (f"no gw*.json files in {workers_dir.as_posix()}",),
        )
    workers: list[WorkerEvidence] = []
    errors: list[str] = []
    warnings: list[str] = []
    for path in paths:
        match = _WORKER_FILE_RE.match(path.name)
        if match is None:
            errors.append(f"unexpected worker evidence file name: {path.name}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"unreadable worker evidence {path.name}: {exc}")
            continue
        problem = _worker_problem(payload, path.stem)
        if problem is not None:
            errors.append(f"invalid worker evidence {path.name}: {problem}")
            continue
        executed = tuple(payload["executed_nodeids"])
        timing: WorkerTiming | None = None
        if payload.get("timing") is not None:
            try:
                timing = _read_timing(payload["timing"], len(executed))
            except _TimingRejected as exc:
                warnings.append(
                    f"{path.stem}: {exc}; busy time comes from JUnit durations"
                )
        workers.append(
            WorkerEvidence(
                worker=path.stem,
                index=int(match.group(1)),
                executed_nodeids=executed,
                timing=timing,
            )
        )
    workers.sort(key=lambda worker: worker.index)
    return WorkerLoad(tuple(workers), tuple(errors), tuple(warnings))


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def _span(
    events: Mapping[str, Stamp | None], later: str, earlier: str
) -> float | None:
    end, start = events[later], events[earlier]
    if end is None or start is None:
        return None
    return end["monotonic"] - start["monotonic"]


def _wall(events: Mapping[str, Stamp | None], name: str) -> float | None:
    stamp = events[name]
    return None if stamp is None else round(stamp["wall"], 3)


def _busy_entry(worker: WorkerEvidence, junit: JUnitTimes) -> dict[str, Any]:
    junit_total = 0.0
    junit_files: dict[str, float] = {}
    for node in worker.executed_nodeids:
        seconds = junit.node_seconds.get(node, 0.0)
        junit_total += seconds
        file_name = node.split("::", 1)[0]
        junit_files[file_name] = junit_files.get(file_name, 0.0) + seconds

    timing = worker.timing
    timeline: dict[str, float | None] = {
        "collection_seconds": None,
        "start_wait_seconds": None,
        "active_span_seconds": None,
        "in_span_gap_seconds": None,
        "tail_seconds": None,
        "first_test_start_wall": None,
        "last_test_end_wall": None,
    }
    if timing is None:
        source = "junit"
        busy = junit_total
        files = junit_files
    else:
        source = "timestamps"
        busy = sum(timing.file_seconds.values(), 0.0)
        files = timing.file_seconds
        events = timing.events
        active = _span(events, "last_test_end", "first_test_start")
        timeline = {
            "collection_seconds": _rounded(
                _span(events, "collection_finished", "session_start")
            ),
            "start_wait_seconds": _rounded(
                _span(events, "first_test_start", "collection_finished")
            ),
            "active_span_seconds": _rounded(active),
            "in_span_gap_seconds": None if active is None else round(active - busy, 3),
            "tail_seconds": _rounded(_span(events, "session_finish", "last_test_end")),
            "first_test_start_wall": _wall(events, "first_test_start"),
            "last_test_end_wall": _wall(events, "last_test_end"),
        }
    rounded_files = {name: round(seconds, 3) for name, seconds in files.items()}
    dominant = min(
        rounded_files.items(), key=lambda item: (-item[1], item[0]), default=None
    )
    return {
        "worker": worker.worker,
        "busy_seconds": round(busy, 3),
        "busy_source": source,
        "junit_busy_seconds": round(junit_total, 3),
        "executed_count": len(worker.executed_nodeids),
        "file_count": len(rounded_files),
        "dominant_file": None if dominant is None else dominant[0],
        "dominant_file_seconds": None if dominant is None else dominant[1],
        **timeline,
    }


def compute_busy(
    workers: Sequence[WorkerEvidence], junit: JUnitTimes
) -> dict[str, Any] | None:
    """Per-worker busy time and the critical path, or ``None`` without workers.

    A worker's busy time is the sum of ``timing.files[*].duration_seconds`` when
    it has a valid timing block, otherwise the sum of JUnit time over its
    ``executed_nodeids``. The critical-path worker has the most busy time (a tie
    goes to the lowest numeric ``gw`` index); its dominant file is its largest
    (a tie goes to the lexicographically smallest path). Monotonic stamps are
    only ever compared within one worker, and ``in_span_gap_seconds`` (active
    span minus busy time) can be a few milliseconds negative on a clock with
    coarse granularity.
    """
    ordered = sorted(workers, key=lambda worker: worker.index)
    if not ordered:
        return None
    entries = [_busy_entry(worker, junit) for worker in ordered]
    busy_values = [entry["busy_seconds"] for entry in entries]
    critical_position = max(
        range(len(entries)), key=lambda i: (busy_values[i], -ordered[i].index)
    )
    critical = entries[critical_position]
    executed: set[str] = set()
    for worker in ordered:
        executed.update(worker.executed_nodeids)
    sources = {entry["busy_source"] for entry in entries}
    return {
        "source": sources.pop() if len(sources) == 1 else "mixed",
        "workers": entries,
        "mean_seconds": round(sum(busy_values) / len(busy_values), 3),
        "max_seconds": max(busy_values),
        "min_seconds": min(busy_values),
        "critical_path": {
            "worker": critical["worker"],
            "busy_seconds": critical["busy_seconds"],
            "file": critical["dominant_file"],
            "file_seconds": critical["dominant_file_seconds"],
        },
        "unattributed_junit_seconds": round(
            sum(
                (
                    seconds
                    for node, seconds in junit.node_seconds.items()
                    if node not in executed
                ),
                0.0,
            ),
            3,
        ),
    }


def _clip(text: str) -> str:
    return text if len(text) <= _ERROR_TEXT_LIMIT else text[:_ERROR_TEXT_LIMIT] + "..."


def _bounded(items: list[dict[str, Any]], id_key: str) -> dict[str, Any]:
    ordered = sorted(items, key=lambda item: (-item["seconds"], item[id_key]))
    limit = max(_DURATION_BUDGET_ITEM_LIMIT, 0)
    return {
        "count": len(ordered),
        "truncated": len(ordered) > limit,
        "items": ordered[:limit],
    }


def build_duration_budget(junit_path: Path, workers_dir: Path) -> dict[str, Any]:
    """The report-only duration budget of one finished gate.

    Lists tests over ``_DURATION_BUDGET_TEST_SECONDS`` and files over
    ``_DURATION_BUDGET_FILE_SECONDS`` or over ``_DURATION_BUDGET_MEAN_BUSY_SHARE``
    of the mean worker busy time, from JUnit, plus the critical path. Per-worker
    evidence that is missing or invalid leaves the busy fields empty and says why
    in ``error``; it never hides the JUnit findings. Nothing is keyed by a path or
    a node ID, so a case-insensitive JSON reader cannot collide two of them.
    Raises ``ET.ParseError`` or ``OSError`` when the JUnit report is unreadable.
    """
    junit = read_junit_times(junit_path)
    load = load_worker_evidence(workers_dir)
    busy = compute_busy(load.workers, junit) if not load.errors else None
    error: str | None = None
    if load.errors:
        error = "per-worker evidence is invalid: " + "; ".join(load.errors)
    elif busy is None:
        error = "per-worker evidence is unavailable: " + "; ".join(load.warnings)
    mean = None if busy is None else busy["mean_seconds"]

    test_limit = _DURATION_BUDGET_TEST_SECONDS
    file_limit = _DURATION_BUDGET_FILE_SECONDS
    share = _DURATION_BUDGET_MEAN_BUSY_SHARE
    share_limit = None if mean is None else share * mean

    slow_tests: list[dict[str, Any]] = []
    for node, raw_seconds in junit.node_seconds.items():
        seconds = round(raw_seconds, 3)
        if seconds > test_limit:
            slow_tests.append({"id": node, "seconds": seconds})
    slow_files: list[dict[str, Any]] = []
    for file_name, raw_seconds in junit.file_seconds.items():
        seconds = round(raw_seconds, 3)
        over_file = seconds > file_limit
        over_share = None if share_limit is None else seconds > share_limit
        if over_file or over_share:
            slow_files.append(
                {
                    "file": file_name,
                    "seconds": seconds,
                    "over_file_seconds": over_file,
                    "over_mean_busy_share": over_share,
                }
            )
    return {
        "version": BUDGET_VERSION,
        "report_only": True,
        "thresholds": {
            "test_seconds": test_limit,
            "file_seconds": file_limit,
            "mean_busy_share": share,
            "item_limit": _DURATION_BUDGET_ITEM_LIMIT,
        },
        "busy_source": None if busy is None else busy["source"],
        "worker_busy": []
        if busy is None
        else [
            {
                "worker": entry["worker"],
                "busy_seconds": entry["busy_seconds"],
                "busy_source": entry["busy_source"],
            }
            for entry in busy["workers"]
        ],
        "mean_busy_seconds": mean,
        "critical_path": None if busy is None else busy["critical_path"],
        "slow_tests": _bounded(slow_tests, "id"),
        "slow_files": _bounded(slow_files, "file"),
        "unresolved_junit_testcases": junit.unresolved,
        "error": None if error is None else _clip(error),
    }
