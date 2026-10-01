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

Evidence is checked against itself before it is believed. A ``timing`` block must
agree with the worker's own ``executed_nodeids`` (the same files, the same node
counts, stamps in the documented order, durations that fit the span they were
measured in); one that does not is rejected and the worker is measured from JUnit
instead. ``evidence_problems`` additionally checks the workers against the
collection artifact, so a critical path is never reported from incomplete
evidence.

Ranking, ties and thresholds use raw seconds, and sums use ``math.fsum`` so they do
not depend on summation order. Values are rounded to milliseconds only for
display.

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
from typing import Any, Mapping, Sequence, TypeGuard

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

#: Slack, in seconds, when summed per-report durations (``perf_counter``) are
#: compared with the span between two ``time.monotonic()`` stamps. Measured on the
#: reference host (Windows, Python 3.12): ``time.monotonic()`` is
#: ``GetTickCount64()`` with a 15.625 ms resolution, so a span is only known to one
#: tick. Over 400 short windows summed durations overshot the stamped span by at
#: most 14.5 ms, and over one 45 s window by none, so one tick rounded up is
#: enough. Ordering stamps needs no slack: the clock never runs backwards.
_MONOTONIC_EPSILON_SECONDS = 0.02

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
    """Durations read from one JUnit report, in raw (unrounded) seconds.

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
    file_parts: dict[str, list[float]] = {}
    unresolved = 0
    for testcase in testcases:
        node = junit_node_id(dict(testcase.attrib))
        if node is None:
            unresolved += 1
            continue
        nodes.append(node)
        seconds = _seconds(testcase.attrib.get("time", "0"))
        node_seconds[node] = node_seconds.get(node, 0.0) + seconds
        file_parts.setdefault(node.split("::", 1)[0], []).append(seconds)
    return JUnitTimes(
        testcase_count=len(testcases),
        unresolved=unresolved,
        nodes=tuple(nodes),
        node_seconds=node_seconds,
        file_seconds={name: math.fsum(parts) for name, parts in file_parts.items()},
    )


@dataclass(frozen=True)
class WorkerTiming:
    """A validated version-1 ``timing`` block."""

    events: dict[str, Stamp | None]
    file_seconds: dict[str, float]


@dataclass(frozen=True)
class WorkerEvidence:
    """One worker's ``gwN.json``; ``timing`` is ``None`` when absent or rejected.

    ``exitstatus`` is ``None`` when the file does not carry an integer one.
    """

    worker: str
    index: int
    exitstatus: int | None
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


def _is_stamp(value: object) -> TypeGuard[Stamp]:
    return (
        isinstance(value, dict)
        and _is_finite(value.get("monotonic"))
        and _is_finite(value.get("wall"))
    )


def _check_event_order(events: Mapping[str, Stamp | None]) -> None:
    """Reject events that run backwards in the documented order."""
    previous_name: str | None = None
    previous = 0.0
    for name in EVENT_NAMES:
        stamp = events[name]
        if stamp is None:
            continue
        if previous_name is not None and stamp["monotonic"] < previous:
            raise _TimingRejected(f"timing event {name} precedes {previous_name}")
        previous_name, previous = name, stamp["monotonic"]


def _read_timing(value: object, executed: Sequence[str]) -> WorkerTiming:
    """Validate a ``timing`` block against the worker's own ``executed_nodeids``."""
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
    _check_event_order(parsed_events)

    executed_counts: dict[str, int] = {}
    for node in executed:
        file_name = node.split("::", 1)[0]
        executed_counts[file_name] = executed_counts.get(file_name, 0) + 1
    unexecuted = sorted(set(files) - set(executed_counts))
    if unexecuted:
        raise _TimingRejected(
            f"the timing block lists {unexecuted[0]}, which the worker did not execute"
        )
    first_test = parsed_events["first_test_start"]
    last_test = parsed_events["last_test_end"]
    window: tuple[float, float] | None = None
    if executed_counts:
        if first_test is None or last_test is None:
            raise _TimingRejected("tests executed but the first or last test stamp is null")
        window = (first_test["monotonic"], last_test["monotonic"])
    file_seconds: dict[str, float] = {}
    for file_name, executed_count in executed_counts.items():
        entry = files.get(file_name)
        if not isinstance(entry, dict):
            raise _TimingRejected(f"the timing block has no entry for {file_name}")
        seconds = entry.get("duration_seconds")
        count = entry.get("node_count")
        if not _is_finite(seconds) or seconds < 0:
            raise _TimingRejected(f"timing file entry {file_name} has a bad duration")
        if not _is_int(count) or count != executed_count:
            raise _TimingRejected(
                f"timing file entry {file_name} counts {count!r} nodes but the "
                f"worker executed {executed_count}"
            )
        first, last = entry.get("first_start"), entry.get("last_end")
        if not _is_stamp(first) or not _is_stamp(last):
            raise _TimingRejected(
                f"timing file entry {file_name} lacks a first_start or last_end stamp"
            )
        if window is not None and not (
            window[0] <= first["monotonic"] <= last["monotonic"] <= window[1]
        ):
            raise _TimingRejected(
                f"timing file entry {file_name} breaks the first-test-start, "
                "first_start, last_end, last-test-end order"
            )
        file_seconds[file_name] = float(seconds)
    if window is not None:
        active = window[1] - window[0]
        busy = math.fsum(file_seconds.values())
        if busy > active + _MONOTONIC_EPSILON_SECONDS:
            raise _TimingRejected(
                f"the timing durations sum to {busy:.3f} s but the first test start "
                f"to the last test end spans only {active:.3f} s"
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


def load_worker_evidence(
    workers_dir: Path, worker_ids: Sequence[str] | None = None
) -> WorkerLoad:
    """Read the worker files in ``workers_dir``.

    With ``worker_ids`` only ``<id>.json`` for each of those ids is read (a missing
    one is an error), so a caller that has just validated ``gw0..gw(N-1)`` reads
    exactly those files. Without it every ``gw*.json`` is read.

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
    if worker_ids is None:
        paths = sorted(workers_dir.glob("gw*.json"))
        if not paths:
            return WorkerLoad(
                (),
                (),
                (f"no gw*.json files in {workers_dir.as_posix()}",),
            )
    else:
        paths = [workers_dir / f"{worker_id}.json" for worker_id in worker_ids]
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
        except FileNotFoundError:
            errors.append(f"missing worker evidence {path.name}")
            continue
        except (OSError, ValueError, RecursionError) as exc:
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
                timing = _read_timing(payload["timing"], executed)
            except _TimingRejected as exc:
                warnings.append(
                    f"{path.stem}: {exc}; busy time comes from JUnit durations"
                )
        status = payload.get("exitstatus")
        workers.append(
            WorkerEvidence(
                worker=path.stem,
                index=int(match.group(1)),
                exitstatus=status if _is_int(status) else None,
                executed_nodeids=executed,
                timing=timing,
            )
        )
    workers.sort(key=lambda worker: worker.index)
    return WorkerLoad(tuple(workers), tuple(errors), tuple(warnings))


def evidence_problems(
    workers: Sequence[WorkerEvidence],
    expected_counts: Mapping[str, int],
    collected: Sequence[str],
) -> list[str]:
    """Why ``workers`` cannot stand for a whole gate; empty when they can.

    ``expected_counts`` is the collection artifact's ``worker_execution_counts``
    and ``collected`` its node IDs. The workers must be exactly the recorded ones,
    each with exit status 0, executing each node once, in the recorded number,
    and together exactly the collection. A busy time or critical path computed
    from anything less would describe a different gate than the one shipped.
    """
    problems: list[str] = []
    loaded = {worker.worker for worker in workers}
    recorded = set(expected_counts)
    if loaded != recorded:
        problems.append(
            "the worker evidence does not match the collection artifact's workers: "
            f"missing {sorted(recorded - loaded)}, unexpected {sorted(loaded - recorded)}"
        )
    owner: dict[str, str] = {}
    shared: set[str] = set()
    for worker in workers:
        if worker.exitstatus != 0:
            problems.append(f"{worker.worker} has exit status {worker.exitstatus!r}, not 0")
        unique = set(worker.executed_nodeids)
        if len(unique) != len(worker.executed_nodeids):
            problems.append(f"{worker.worker} lists a node ID more than once")
        expected = expected_counts.get(worker.worker)
        if expected is not None and expected != len(worker.executed_nodeids):
            problems.append(
                f"{worker.worker} executed {len(worker.executed_nodeids)} nodes but "
                f"the collection artifact records {expected}"
            )
        for node in unique:
            if node in owner:
                shared.add(node)
            owner[node] = worker.worker
    if shared:
        problems.append(
            f"{len(shared)} node IDs were executed by more than one worker, "
            f"for example {sorted(shared)[0]}"
        )
    collection = set(collected)
    if set(owner) != collection:
        problems.append(
            "the executed nodes differ from the collection: "
            f"{len(collection - set(owner))} missing, {len(set(owner) - collection)} unexpected"
        )
    return problems


_TIMELINE_FIELDS: tuple[str, ...] = (
    "collection_seconds",
    "start_wait_seconds",
    "active_span_seconds",
    "in_span_gap_seconds",
    "tail_seconds",
    "first_test_start_wall",
    "last_test_end_wall",
)


def _rounded(value: float | None) -> float | None:
    """Milliseconds, for display only; nothing is ranked or compared on this."""
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
    return None if stamp is None else stamp["wall"]


@dataclass(frozen=True)
class _WorkerBusy:
    """One worker's busy time in raw seconds; ``_render_worker`` rounds it."""

    worker: str
    index: int
    source: str
    busy: float
    junit_busy: float
    executed_count: int
    files: dict[str, float]
    timeline: dict[str, float | None]
    dominant: tuple[str, float] | None


@dataclass(frozen=True)
class _Analysis:
    workers: tuple[_WorkerBusy, ...]
    source: str
    mean: float
    maximum: float
    minimum: float
    critical: _WorkerBusy
    unattributed: float


def _busy_of(worker: WorkerEvidence, junit: JUnitTimes) -> _WorkerBusy:
    junit_parts: list[float] = []
    junit_file_parts: dict[str, list[float]] = {}
    for node in worker.executed_nodeids:
        seconds = junit.node_seconds.get(node, 0.0)
        junit_parts.append(seconds)
        junit_file_parts.setdefault(node.split("::", 1)[0], []).append(seconds)
    junit_busy = math.fsum(junit_parts)

    timing = worker.timing
    timeline: dict[str, float | None] = dict.fromkeys(_TIMELINE_FIELDS)
    if timing is None:
        source = "junit"
        busy = junit_busy
        files = {name: math.fsum(parts) for name, parts in junit_file_parts.items()}
    else:
        source = "timestamps"
        files = dict(timing.file_seconds)
        busy = math.fsum(files.values())
        events = timing.events
        active = _span(events, "last_test_end", "first_test_start")
        timeline = {
            "collection_seconds": _span(events, "collection_finished", "session_start"),
            "start_wait_seconds": _span(events, "first_test_start", "collection_finished"),
            "active_span_seconds": active,
            # A validated block fits its span to within _MONOTONIC_EPSILON_SECONDS,
            # so a gap below zero is clock granularity, not information.
            "in_span_gap_seconds": None if active is None else max(active - busy, 0.0),
            "tail_seconds": _span(events, "session_finish", "last_test_end"),
            "first_test_start_wall": _wall(events, "first_test_start"),
            "last_test_end_wall": _wall(events, "last_test_end"),
        }
    dominant = min(files.items(), key=lambda item: (-item[1], item[0]), default=None)
    return _WorkerBusy(
        worker=worker.worker,
        index=worker.index,
        source=source,
        busy=busy,
        junit_busy=junit_busy,
        executed_count=len(worker.executed_nodeids),
        files=files,
        timeline=timeline,
        dominant=dominant,
    )


def _analyse(
    workers: Sequence[WorkerEvidence], junit: JUnitTimes
) -> _Analysis | None:
    ordered = sorted(workers, key=lambda worker: worker.index)
    if not ordered:
        return None
    entries = tuple(_busy_of(worker, junit) for worker in ordered)
    # Raw seconds decide the critical path; only an exact tie goes to the lowest
    # numeric gw index.
    critical = max(entries, key=lambda entry: (entry.busy, -entry.index))
    executed: set[str] = set()
    for worker in ordered:
        executed.update(worker.executed_nodeids)
    sources = {entry.source for entry in entries}
    return _Analysis(
        workers=entries,
        source=sources.pop() if len(sources) == 1 else "mixed",
        mean=math.fsum(entry.busy for entry in entries) / len(entries),
        maximum=max(entry.busy for entry in entries),
        minimum=min(entry.busy for entry in entries),
        critical=critical,
        unattributed=math.fsum(
            seconds
            for node, seconds in junit.node_seconds.items()
            if node not in executed
        ),
    )


def _render_worker(entry: _WorkerBusy) -> dict[str, Any]:
    dominant = entry.dominant
    return {
        "worker": entry.worker,
        "busy_seconds": round(entry.busy, 3),
        "busy_source": entry.source,
        "junit_busy_seconds": round(entry.junit_busy, 3),
        "executed_count": entry.executed_count,
        "file_count": len(entry.files),
        "dominant_file": None if dominant is None else dominant[0],
        "dominant_file_seconds": None if dominant is None else round(dominant[1], 3),
        **{name: _rounded(value) for name, value in entry.timeline.items()},
    }


def _render_critical(entry: _WorkerBusy) -> dict[str, Any]:
    dominant = entry.dominant
    return {
        "worker": entry.worker,
        "busy_seconds": round(entry.busy, 3),
        "file": None if dominant is None else dominant[0],
        "file_seconds": None if dominant is None else round(dominant[1], 3),
    }


def _render_busy(analysis: _Analysis) -> dict[str, Any]:
    return {
        "source": analysis.source,
        "workers": [_render_worker(entry) for entry in analysis.workers],
        "mean_seconds": round(analysis.mean, 3),
        "max_seconds": round(analysis.maximum, 3),
        "min_seconds": round(analysis.minimum, 3),
        "critical_path": _render_critical(analysis.critical),
        "unattributed_junit_seconds": round(analysis.unattributed, 3),
    }


def compute_busy(
    workers: Sequence[WorkerEvidence], junit: JUnitTimes
) -> dict[str, Any] | None:
    """Per-worker busy time and the critical path, or ``None`` without workers.

    A worker's busy time is the sum of ``timing.files[*].duration_seconds`` when
    it has a valid timing block, otherwise the sum of JUnit time over its
    ``executed_nodeids``. The critical-path worker has the most busy time (a tie
    goes to the lowest numeric ``gw`` index); its dominant file is its largest
    (a tie goes to the lexicographically smallest path). Both are decided on raw
    seconds, so two workers that differ by a tenth of a millisecond are not a
    tie; the reported values are rounded to milliseconds. Monotonic stamps are
    only ever compared within one worker.
    """
    analysis = _analyse(workers, junit)
    return None if analysis is None else _render_busy(analysis)


def _clip(text: str) -> str:
    return text if len(text) <= _ERROR_TEXT_LIMIT else text[:_ERROR_TEXT_LIMIT] + "..."


def _bounded(
    rows: list[tuple[float, str, dict[str, Any]]], id_key: str
) -> dict[str, Any]:
    """Count exactly, order by raw ``(-seconds, id)``, keep a bounded list."""
    ordered = sorted(rows, key=lambda row: (-row[0], row[1]))
    limit = max(_DURATION_BUDGET_ITEM_LIMIT, 0)
    return {
        "count": len(ordered),
        "truncated": len(ordered) > limit,
        "items": [
            {id_key: name, "seconds": round(seconds, 3), **flags}
            for seconds, name, flags in ordered[:limit]
        ],
    }


def build_duration_budget(
    junit_path: Path,
    workers_dir: Path,
    worker_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """The report-only duration budget of one finished gate.

    Lists tests over ``_DURATION_BUDGET_TEST_SECONDS`` and files over
    ``_DURATION_BUDGET_FILE_SECONDS`` or over ``_DURATION_BUDGET_MEAN_BUSY_SHARE``
    of the mean worker busy time, from JUnit, plus the critical path. Every
    comparison uses raw seconds; only the reported values are rounded.

    ``worker_ids`` names the worker files to read (the wrapper passes the
    ``gw0..gw(N-1)`` it has just validated); ``None`` reads every ``gw*.json``.
    Per-worker evidence that is missing or invalid leaves the busy fields empty and
    says why in ``error``; it never hides the JUnit findings. Nothing is keyed by a
    path or a node ID, so a case-insensitive JSON reader cannot collide two of
    them. The work is linear in the evidence it is given. Raises
    ``ET.ParseError`` or ``OSError`` when the JUnit report is unreadable.
    """
    junit = read_junit_times(junit_path)
    load = load_worker_evidence(workers_dir, worker_ids)
    analysis = None if load.errors else _analyse(load.workers, junit)
    error: str | None = None
    if load.errors:
        error = "per-worker evidence is invalid: " + "; ".join(load.errors)
    elif analysis is None:
        error = "per-worker evidence is unavailable: " + "; ".join(load.warnings)
    mean = None if analysis is None else analysis.mean

    test_limit = _DURATION_BUDGET_TEST_SECONDS
    file_limit = _DURATION_BUDGET_FILE_SECONDS
    share = _DURATION_BUDGET_MEAN_BUSY_SHARE
    share_limit = None if mean is None else share * mean

    slow_tests: list[tuple[float, str, dict[str, Any]]] = []
    for node, seconds in junit.node_seconds.items():
        if seconds > test_limit:
            slow_tests.append((seconds, node, {}))
    slow_files: list[tuple[float, str, dict[str, Any]]] = []
    for file_name, seconds in junit.file_seconds.items():
        over_file = seconds > file_limit
        over_share = None if share_limit is None else seconds > share_limit
        if over_file or over_share:
            slow_files.append(
                (
                    seconds,
                    file_name,
                    {
                        "over_file_seconds": over_file,
                        "over_mean_busy_share": over_share,
                    },
                )
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
        "busy_source": None if analysis is None else analysis.source,
        "worker_busy": []
        if analysis is None
        else [
            {
                "worker": entry.worker,
                "busy_seconds": round(entry.busy, 3),
                "busy_source": entry.source,
            }
            for entry in analysis.workers
        ],
        "mean_busy_seconds": _rounded(mean),
        "critical_path": None if analysis is None else _render_critical(analysis.critical),
        "slow_tests": _bounded(slow_tests, "id"),
        "slow_files": _bounded(slow_files, "file"),
        "unresolved_junit_testcases": junit.unresolved,
        "error": None if error is None else _clip(error),
    }
