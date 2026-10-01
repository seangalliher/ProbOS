"""PYTEST_DONT_REWRITE: CI shard filter and execution recorder for .github/workflows/ci.yml.

CI shard evidence is not release authority; the canonical gate
(``scripts/run_test_gate.py``) is. Load this with ``-p scripts._ci_shard_pytest_plugin``
through ``python -m pytest`` (the bare ``pytest`` command leaves the repository root off
``sys.path``) and give all of::

    --probos-shard-index K --probos-shard-count N --probos-shard-evidence-dir DIR

plus, optionally, ``--probos-shard-durations PATH``. Relative paths resolve against
pytest's rootpath. With none of the first three options the plugin is inert. A partial
set, an index outside 1..N or an unusable durations file raises ``pytest.UsageError``
from ``pytest_configure``, before xdist starts any worker. Pytest's rootdir detection
runs before this plugin loads and reads the value after an unknown option as a path
argument, so pass explicit test paths (CI passes ``tests/``) or write ``--option=value``.

Every pytest process that runs the collection hook (each xdist worker, or the one process
under ``-n 0``) collects the whole suite, refuses to continue if another hook removed,
added or renamed an item, keeps only the files ``scripts/ci_shards.assign_files`` gives
shard K and hands the rest to ``pytest_deselected``. When its session finishes it writes
``DIR/shard-K/<gwN|main>.json`` atomically: the digests of the full collection and of the
assignment, and the node ID of every setup-phase report in execution order with repeats
kept. ``scripts/ci_shards.py verify`` turns those into the exactly-once proof. The plugin
changes no markers, scheduling, timeouts or outcomes. The xdist controller never collects,
so it never writes.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from scripts import ci_shards

_RECORDER_NAME = "probos-ci-shard-recorder"
_PREVIEW_LIMIT = 5


def _preview(nodeids: list[str]) -> str:
    shown = ", ".join(nodeids[:_PREVIEW_LIMIT])
    extra = len(nodeids) - _PREVIEW_LIMIT
    return f"[{shown}{f', ... +{extra} more' if extra > 0 else ''}]"


def _resolve(rootpath: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else rootpath / path


def _durations_label(rootpath: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(rootpath.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("probos-ci-shard", "ProbOS CI shard evidence (not release authority)")
    group.addoption(
        "--probos-shard-index",
        dest="probos_shard_index",
        type=int,
        default=None,
        metavar="K",
        help="run only shard K (1-based) of --probos-shard-count",
    )
    group.addoption(
        "--probos-shard-count",
        dest="probos_shard_count",
        type=int,
        default=None,
        metavar="N",
        help="split the collected test files into N shards",
    )
    group.addoption(
        "--probos-shard-evidence-dir",
        dest="probos_shard_evidence_dir",
        default=None,
        metavar="DIR",
        help="write shard-K/<worker>.json evidence under DIR",
    )
    group.addoption(
        "--probos-shard-durations",
        dest="probos_shard_durations",
        default=None,
        metavar="PATH",
        help=f"durations JSON for the split (default: {ci_shards.DEFAULT_DURATIONS_PATH})",
    )


class ShardRecorder:
    """Keeps this process's shard of the collection and records what it executes."""

    def __init__(
        self,
        *,
        index: int,
        count: int,
        evidence_dir: Path,
        durations_label: str,
        durations: ci_shards.DurationsFile,
    ) -> None:
        self._index = index
        self._count = count
        self._evidence_dir = evidence_dir
        self._durations_label = durations_label
        self._durations = durations
        self._run_uid = uuid.uuid4().hex
        self._collection: list[str] | None = None
        self._plan: ci_shards.ShardPlan | None = None
        self._setup_reports: list[str] = []

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(
        self,
        session: pytest.Session,
        config: pytest.Config,
        items: list[pytest.Item],
    ) -> Generator[None, Any, Any]:
        before = [item.nodeid for item in items]
        result = yield
        after = [item.nodeid for item in items]
        duplicated = sorted(nodeid for nodeid, seen in Counter(before).items() if seen > 1)
        if duplicated:
            raise pytest.UsageError(
                f"CI shard plugin: the collection has duplicate node IDs {_preview(duplicated)}"
            )
        removed = sorted((Counter(before) - Counter(after)).elements())
        added = sorted((Counter(after) - Counter(before)).elements())
        if removed or added:
            raise pytest.UsageError(
                "CI shard plugin forbids another hook removing, adding or renaming "
                f"collected items (-k, -m, --deselect, --lf ...): removed {_preview(removed)}, "
                f"added {_preview(added)}"
            )
        collection = sorted(before)
        try:
            plan = ci_shards.assign_files(collection, self._durations.milliseconds, self._count)
        except ci_shards.ShardError as exc:
            raise pytest.UsageError(
                f"CI shard plugin cannot split the collection into {self._count} shards: {exc}"
            ) from exc
        kept: list[pytest.Item] = []
        dropped: list[pytest.Item] = []
        for item in items:
            owner = plan.file_shards[ci_shards.node_file(item.nodeid)]
            (kept if owner == self._index else dropped).append(item)
        items[:] = kept
        if dropped:
            config.hook.pytest_deselected(items=dropped)
        self._collection = collection
        self._plan = plan
        return result

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if self._plan is not None and report.when == "setup":
            self._setup_reports.append(report.nodeid)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self._collection is None or self._plan is None:
            return
        worker_input = getattr(session.config, "workerinput", None)
        if isinstance(worker_input, dict):
            worker_id = str(worker_input["workerid"])
            worker_count = int(worker_input["workercount"])
            testrunuid = str(worker_input["testrunuid"])
        else:
            worker_id, worker_count, testrunuid = "main", 1, self._run_uid
        payload = ci_shards.build_evidence(
            shard_index=self._index,
            shard_count=self._count,
            worker_id=worker_id,
            worker_count=worker_count,
            testrunuid=testrunuid,
            exitstatus=int(exitstatus),
            durations_path=self._durations_label,
            durations_sha256=self._durations.sha256,
            collection=self._collection,
            plan=self._plan,
            setup_reports=self._setup_reports,
        )
        ci_shards.write_evidence(self._evidence_dir, payload)


def pytest_configure(config: pytest.Config) -> None:
    index = config.getoption("probos_shard_index")
    count = config.getoption("probos_shard_count")
    evidence_dir = config.getoption("probos_shard_evidence_dir")
    given = [value is not None for value in (index, count, evidence_dir)]
    if not any(given):
        return
    if not all(given):
        raise pytest.UsageError(
            "--probos-shard-index, --probos-shard-count and --probos-shard-evidence-dir "
            "must be given together"
        )
    if count < 1:
        raise pytest.UsageError(f"--probos-shard-count must be >= 1, got {count}")
    if not 1 <= index <= count:
        raise pytest.UsageError(
            f"--probos-shard-index must be within 1..{count} (--probos-shard-count), got {index}"
        )
    if not evidence_dir.strip():
        raise pytest.UsageError("--probos-shard-evidence-dir must not be empty")
    override = config.getoption("probos_shard_durations")
    durations_path = _resolve(
        config.rootpath, ci_shards.DEFAULT_DURATIONS_PATH if override is None else override
    )
    try:
        durations = ci_shards.read_durations(durations_path)
    except ci_shards.ShardError as exc:
        raise pytest.UsageError(f"CI shard plugin: {exc}") from exc
    recorder = ShardRecorder(
        index=index,
        count=count,
        evidence_dir=_resolve(config.rootpath, evidence_dir),
        durations_label=_durations_label(config.rootpath, durations_path),
        durations=durations,
    )
    config.pluginmanager.register(recorder, _RECORDER_NAME)
