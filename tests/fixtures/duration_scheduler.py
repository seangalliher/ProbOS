"""AD-1270f P1.4: start the longest test files first under ``--dist=loadfile``.

xdist queues one work unit per test file, most *tests* first. A file with few,
slow tests (``test_experience.py`` had 109 tests and took 872 s) therefore starts
late and sets the wall-clock of the whole run while the other workers idle. This
module orders the same units by their *recorded seconds* instead, longest first
(LPT), using ``tests/fixtures/file_durations.json`` as written by
``scripts/gen_file_durations.py``.

What changes, and what cannot. ``DurationOrderedLoadFileScheduling`` is xdist's
own ``LoadFileScheduling``. Its ``schedule()`` only arms a one-shot flag. The
first ``_assign_work_unit()`` after xdist has built the whole work queue re-sorts
that queue in place -- same scope keys, same work-unit dicts, a stable sort so
ties keep xdist's order -- and then calls xdist. Comparing the collections,
shutting down surplus workers, the first unit per worker, the low-watermark
top-ups, crash handling and every later ``schedule()`` stay xdist code.

The guarantee is order only, and it is stated as narrowly as it holds. For a run
that completes, every collected node runs exactly once, as with stock xdist, and
the canonical gate's collection-identity and exactly-once checks judge that run
unchanged. xdist's own crash handling is inherited as it is: it re-queues a
crashed worker's unit, so the crashing node is retried. Under ``--maxfail`` or
``-x`` (CI uses ``--maxfail=10``) the run stops early, and *which* nodes ran
before the stop depends on the order, as it does for any order change; the
scheduler stays enabled there.

The scheduler is used only when every condition holds; otherwise the hook in
``tests/conftest.py`` returns ``None`` and xdist builds its stock scheduler:

* ``--dist=loadfile`` with xdist's ``--loadscope-reorder`` still on (xdist's own
  ``--no-loadscope-reorder`` is the only opt-out);
* the durations file loads and passes every check in ``load_file_durations``,
  including parser failures such as an integer over Python's digit limit, and any
  fault in the key rule it borrows from ``scripts/gen_file_durations.py`` (a missing,
  broken or raising script); each is a ``DurationDataError`` like any other bad data;
* xdist's ``LoadFileScheduling`` still has ``schedule`` and ``_assign_work_unit``
  and starts with an ``OrderedDict`` work queue and no collection.

A ``loadfile`` session whose workers collected the same non-empty set prints
exactly one ``AD-1270f duration scheduler:`` line saying which of those happened,
including ``order NOT applied`` if xdist's first distribution never reached
``_assign_work_unit``. An empty collection, or collections that differ between
workers, ends before any unit is handed out: an enabled scheduler then prints
nothing (a disabled one has already printed its reason when it was built).

Stated bounds. The override depends on private xdist 3.8 members, so
``test_ad1270f_duration_scheduler.py`` pins the major.minor version; an upgrade
must re-verify the first-pop contract and update that pin. The durations are a
snapshot: a file missing from it is estimated at its test count times the suite's
mean seconds per test (not the per-test median, under 10 ms, which would send an
unseen heavy file last), and a file whose cost changed since the snapshot is
ordered by the old figure until the file is regenerated.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import TYPE_CHECKING

from xdist.scheduler import LoadFileScheduling

if TYPE_CHECKING:
    import pytest
    from xdist.remote import Producer
    from xdist.workermanage import WorkerController

_LOG = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DURATIONS_PATH = Path(__file__).with_name("file_durations.json")
DURATIONS_NAME = "tests/fixtures/file_durations.json"
REPORT_PREFIX = "AD-1270f duration scheduler:"
_GENERATOR_PATH = Path(__file__).resolve().parents[2] / "scripts" / "gen_file_durations.py"
_RULE_MODULE = "_ad1270f_file_key_rule"
_STOCK_ORDER = "using xdist's stock LoadFileScheduling order"
_MAX_REPORTED_NAMES = 5
_TOP_LEVEL_KEYS = frozenset({"schema_version", "source", "mean_test_seconds", "files"})
_SOURCE_KEYS = frozenset(
    {"junit", "collection", "junit_sha256", "collection_sha256", "testcases", "total_seconds"}
)
_SHA256 = re.compile(r"[0-9a-f]{64}")


class DurationDataError(ValueError):
    """The durations file is missing or untrustworthy, so xdist's stock order is used."""


@dataclass(frozen=True)
class FileDurations:
    """Recorded seconds per collected test file, plus the suite mean for unseen files."""

    files: Mapping[str, float]
    mean_test_seconds: float

    def is_recorded(self, scope: str) -> bool:
        return scope in self.files

    def estimate(self, scope: str, test_count: int) -> float:
        """Recorded seconds for ``scope``; unseen files cost ``test_count`` x the suite mean."""
        recorded = self.files.get(scope)
        return recorded if recorded is not None else test_count * self.mean_test_seconds


def _reject_constant(token: str) -> float:
    raise DurationDataError(f"non-finite JSON constant {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise DurationDataError("a JSON object repeats a key")
    return dict(pairs)


def _seconds(value: object, what: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DurationDataError(f"{what} is not a number: {value!r}")
    try:
        number = float(value)
    except OverflowError:
        raise DurationDataError(f"{what} is out of range") from None
    if not math.isfinite(number):
        raise DurationDataError(f"{what} is not finite: {value!r}")
    if number < 0 or (positive and number == 0):
        raise DurationDataError(f"{what} must be {'> 0' if positive else '>= 0'}: {value!r}")
    return number


def _check_source(source: object) -> None:
    if not isinstance(source, dict) or set(source) != _SOURCE_KEYS:
        raise DurationDataError("source must hold exactly " + ", ".join(sorted(_SOURCE_KEYS)))
    for key in ("junit", "collection"):
        name = source[key]
        if not isinstance(name, str) or not name or "/" in name or "\\" in name:
            raise DurationDataError(f"source.{key} must be a file basename: {name!r}")
    for key in ("junit_sha256", "collection_sha256"):
        digest = source[key]
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise DurationDataError(f"source.{key} must be 64 lowercase hex characters")
    testcases = source["testcases"]
    if isinstance(testcases, bool) or not isinstance(testcases, int) or testcases <= 0:
        raise DurationDataError(f"source.testcases must be an int > 0: {testcases!r}")
    _seconds(source["total_seconds"], "source.total_seconds")


def _first_clause(exc: BaseException) -> str:
    """A short single-line reason for a report: the message up to its first colon."""
    lines = str(exc).splitlines()
    return (lines[0].split(":", 1)[0] if lines else "") or type(exc).__name__


def _file_key_rule() -> Callable[[str], str | None]:
    """``file_key_problem`` from ``scripts/gen_file_durations.py``, the writer of the file.

    What a ``files`` key may look like is defined once, by the writer, and applied here
    to every key read, so the two cannot disagree. The script is not imported: its source
    is read, compiled and executed here in a fresh module namespace, so nothing is
    registered in ``sys.modules`` and no bytecode cache is written beside it. It is
    another file's code running inside the xdist controller, so every way it can fail --
    executing it, a missing or non-callable rule, and each later call of the rule -- is
    bad data like any other: ``DurationDataError``, and the run falls back to the stock
    order. Only ``KeyboardInterrupt``, the operator's own, still propagates.
    """
    where = _GENERATOR_PATH.name
    try:
        module = ModuleType(_RULE_MODULE)
        module.__file__ = str(_GENERATOR_PATH)
        code = compile(_GENERATOR_PATH.read_bytes(), str(_GENERATOR_PATH), "exec", dont_inherit=True)
        exec(code, module.__dict__)  # noqa: S102 -- this repository's own script, see above
        rule = module.file_key_problem
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # SystemExit and friends included: nothing here may end the run
        raise DurationDataError(f"cannot load the key rule from {where} ({type(exc).__name__})") from exc
    if not callable(rule):
        raise DurationDataError(f"cannot load the key rule from {where} (file_key_problem is not callable)")

    def checked(key: str) -> str | None:
        try:
            return rule(key)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:
            raise DurationDataError(f"the key rule failed on {key!r} ({type(exc).__name__})") from exc

    return checked


def load_file_durations(path: Path = DURATIONS_PATH) -> FileDurations:
    """Load and fully validate the durations file, or raise ``DurationDataError``."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DurationDataError(f"{path.name} is unreadable ({type(exc).__name__})") from exc
    try:
        payload = json.loads(
            text, parse_constant=_reject_constant, object_pairs_hook=_reject_duplicate_keys
        )
    except DurationDataError:
        raise  # a hook above refused the data; keep its reason (it is also a ValueError)
    except json.JSONDecodeError as exc:
        raise DurationDataError(f"{path.name} is not valid JSON ({exc.msg})") from exc
    except RecursionError:
        raise DurationDataError(f"{path.name} is nested too deeply") from None
    except ValueError as exc:
        # The parser's own limits, such as an integer over Python's digit cap, are plain
        # ValueErrors: bad data like any other, so fall back instead of failing the run.
        raise DurationDataError(f"{path.name} cannot be parsed ({_first_clause(exc)})") from exc
    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_KEYS:
        raise DurationDataError(f"{path.name} must hold exactly " + ", ".join(sorted(_TOP_LEVEL_KEYS)))
    version = payload["schema_version"]
    if isinstance(version, bool) or version != SCHEMA_VERSION:
        raise DurationDataError(f"schema_version must be {SCHEMA_VERSION}: {version!r}")
    _check_source(payload["source"])
    mean = _seconds(payload["mean_test_seconds"], "mean_test_seconds", positive=True)
    files = payload["files"]
    if not isinstance(files, dict) or not files:
        raise DurationDataError("files must be a non-empty object")
    key_problem = _file_key_rule()
    checked: dict[str, float] = {}
    for key, value in files.items():
        problem = key_problem(key)
        if problem is not None:
            raise DurationDataError(problem)
        checked[key] = _seconds(value, f"files[{key!r}]")
    return FileDurations(files=MappingProxyType(checked), mean_test_seconds=mean)


def _report(config: pytest.Config, message: str) -> None:
    line = f"{REPORT_PREFIX} {message}"
    terminal = config.pluginmanager.getplugin("terminalreporter")
    if terminal is not None:
        terminal.write_line(line)
    else:
        _LOG.warning("%s", line)


class DurationOrderedLoadFileScheduling(LoadFileScheduling):
    """``LoadFileScheduling`` whose first distribution hands out the longest files first."""

    def __init__(
        self,
        config: pytest.Config,
        log: Producer | None = None,
        *,
        durations: FileDurations,
    ) -> None:
        super().__init__(config, log)
        self._durations = durations
        self._order_pending = False

    def schedule(self) -> None:
        first_distribution = self.collection is None
        if first_distribution:
            self._order_pending = True
        try:
            super().schedule()
            unapplied = self._order_pending
        finally:
            self._order_pending = False
        if first_distribution and unapplied and self.collection:
            _report(
                self.config,
                "order NOT applied (xdist's first distribution never reached "
                f"_assign_work_unit); {_STOCK_ORDER}",
            )

    def _assign_work_unit(self, node: WorkerController) -> None:
        if self._order_pending:
            self._order_pending = False
            self._apply_duration_order()
        super()._assign_work_unit(node)

    def _apply_duration_order(self) -> None:
        queue = self.workqueue
        estimates = {
            scope: self._durations.estimate(scope, len(unit)) for scope, unit in queue.items()
        }
        ordered = sorted(queue, key=lambda scope: -estimates[scope])
        for scope in ordered:
            queue.move_to_end(scope)
        unseen = [scope for scope in ordered if not self._durations.is_recorded(scope)]
        detail = f"{len(ordered) - len(unseen)} recorded, {len(unseen)} estimated"
        if unseen:
            names = ", ".join(unseen[:_MAX_REPORTED_NAMES])
            if len(unseen) > _MAX_REPORTED_NAMES:
                names += ", ..."
            detail += f" at {self._durations.mean_test_seconds:.4f} s/test; {names}"
        _report(
            self.config,
            f"LPT order over {len(ordered)} files ({detail}) from {DURATIONS_NAME}",
        )


def _missing_internals() -> list[str]:
    return [
        name
        for name in ("schedule", "_assign_work_unit")
        if not callable(getattr(LoadFileScheduling, name, None))
    ]


def make_duration_scheduler(
    config: pytest.Config,
    log: Producer | None,
    *,
    durations_path: Path = DURATIONS_PATH,
) -> DurationOrderedLoadFileScheduling | None:
    """The duration-ordered scheduler for ``--dist=loadfile``, else ``None`` (stock xdist)."""
    if config.getoption("dist") != "loadfile":
        return None
    if not config.getoption("loadscopereorder", True):
        _report(config, f"disabled (--no-loadscope-reorder); {_STOCK_ORDER}")
        return None
    try:
        durations = load_file_durations(durations_path)
    except DurationDataError as exc:
        _report(config, f"disabled ({exc}); {_STOCK_ORDER}")
        return None
    missing = _missing_internals()
    if missing:
        _report(
            config,
            f"disabled (xdist LoadFileScheduling has no {', '.join(missing)}); {_STOCK_ORDER}",
        )
        return None
    scheduler = DurationOrderedLoadFileScheduling(config, log, durations=durations)
    if not isinstance(scheduler.workqueue, OrderedDict) or scheduler.collection is not None:
        _report(
            config,
            "disabled (xdist LoadFileScheduling no longer starts empty with an OrderedDict "
            f"work queue); {_STOCK_ORDER}",
        )
        return None
    return scheduler
