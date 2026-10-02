"""AD-1270f P2.7: CI shard planning and exactly-once evidence verification.

CI shard evidence is not release authority. The canonical local gate
(``scripts/run_test_gate.py``) stays the only release authority, and nothing here feeds
it, its receipts or ``scripts/select_tests.py``.

    python scripts/ci_shards.py verify --evidence-root DIR --shard-count N [--durations PATH]

``.github/workflows/ci.yml`` runs the suite as N file-level shards. Every shard collects
the whole suite, keeps the files ``assign_files`` gives it and, in each pytest process,
``scripts/_ci_shard_pytest_plugin.py`` writes one evidence file. ``verify`` accepts the
evidence only if every collected test executed exactly once across all the shards: the
shards' collections are identical, the assignment recomputed here reproduces theirs
(so the shards are disjoint and cover the collection), and every node's execution
*count* is 1, which a union of node sets could not show.

``verify`` exits 0 when verified, 1 when the evidence is rejected (at most 20 node IDs
per category, then one ``::error::`` line) and 2 on a usage error. Standard library
only. The node-list digest uses the encoding of ``scripts/_gate_pytest_plugin.py``. What a
durations ``files`` key may look like is defined once, by ``scripts/gen_file_durations.py``
(``file_key_problem``): the durations loader here executes that rule, as the scheduler's
loader (``tests/fixtures/duration_scheduler.py``) does.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import types
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DURATIONS_PATH = "tests/fixtures/file_durations.json"
DURATIONS_SCHEMA_VERSION = 1
EVIDENCE_KIND = "probos-ci-shard-evidence"
EVIDENCE_SCHEMA_VERSION = 1
FALLBACK_NODE_MS = 1000
MAX_REPORTED_NODES = 20
MAX_WORKERS = 100_000
PRIMARY_WORKER_IDS = frozenset({"gw0", "main"})

_GENERATOR_PATH = REPO_ROOT / "scripts" / "gen_file_durations.py"
_RULE_MODULE = "_ad1270f_p27_file_key_rule"
_WORKER_FILE = re.compile(r"(?:main|gw[0-9]{1,6})\.json")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ShardError(ValueError):
    """Durations data or a shard request that cannot be used."""


class DurationsFile(NamedTuple):
    """Integer milliseconds per test file, and the sha256 of the bytes they were read from."""

    milliseconds: dict[str, int]
    sha256: str


class ShardPlan(NamedTuple):
    """Where every collected file runs: 1-based shard per file, estimated ms per shard."""

    file_shards: dict[str, int]
    shard_ms: tuple[int, ...]
    unknown_files: tuple[str, ...]
    assignment_sha256: str


def node_file(nodeid: str) -> str:
    """The file part of a node ID: the unit xdist's ``--dist=loadfile`` schedules."""
    return nodeid.split("::", 1)[0]


def node_digest(ids: Iterable[str]) -> str:
    """sha256 over the gate plugin's node-list encoding, in the order the caller passes."""
    payload = json.dumps(tuple(ids), ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reject_constant(token: str) -> float:
    raise ShardError(f"non-finite JSON constant {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ShardError("a JSON object repeats a key")
    return dict(pairs)


def _file_key_rule() -> Callable[[str], str | None]:
    """``file_key_problem`` from ``scripts/gen_file_durations.py``, the writer of the file.

    The writer defines what a ``files`` key may look like and the scheduler's loader applies
    the same function, so the three cannot disagree. The script is executed here, not
    imported: neither import form works from both entry points (``python scripts/ci_shards.py``
    has ``scripts/`` on ``sys.path``, the plugin's ``scripts.ci_shards`` the repository root),
    and an import would register a module and write ``scripts/__pycache__``. Its source is
    compiled and run in a private namespace instead. Every way that can fail, ``SystemExit``
    included, is a ``ShardError``: nothing the borrowed script does may end ``verify`` with
    status 0. Only ``KeyboardInterrupt``, the operator's own, still propagates.
    """
    where = _GENERATOR_PATH.name
    try:
        namespace = types.ModuleType(_RULE_MODULE)
        namespace.__file__ = str(_GENERATOR_PATH)
        code = compile(_GENERATOR_PATH.read_bytes(), str(_GENERATOR_PATH), "exec", dont_inherit=True)
        exec(code, namespace.__dict__)  # noqa: S102 -- this repository's own script, see above
        rule = namespace.file_key_problem
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        raise ShardError(f"cannot load the key rule from {where} ({type(exc).__name__})") from exc
    if not callable(rule):
        raise ShardError(f"cannot load the key rule from {where} (file_key_problem is not callable)")

    def checked(key: str) -> str | None:
        try:
            return rule(key)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:
            raise ShardError(f"the key rule failed on {key!r} ({type(exc).__name__})") from exc

    return checked


def _seconds_to_ms(value: object, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ShardError(f"{where} is not a number: {value!r}")
    try:
        finite = math.isfinite(float(value))
        scaled = value * 1000
        finite = finite and math.isfinite(scaled)
    except OverflowError:
        finite = False
    if not finite:
        raise ShardError(f"{where} is not a finite number in range: {value!r}")
    if value < 0:
        raise ShardError(f"{where} must be >= 0: {value!r}")
    return max(1, round(scaled))


def _parse_durations(raw: bytes) -> dict[str, int]:
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ShardError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ShardError(f"not valid JSON ({type(exc).__name__})") from exc
    if not isinstance(payload, dict):
        raise ShardError("must hold a JSON object")
    # P2.7 contract AC1: only schema_version and files are read, so any other top-level key
    # is ignored. The scheduler's loader is stricter there (it insists on exactly its four
    # keys); the key rule and the value rules below are the same as its.
    version = payload.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != DURATIONS_SCHEMA_VERSION:
        raise ShardError(f"schema_version must be {DURATIONS_SCHEMA_VERSION}: {version!r}")
    files = payload.get("files")
    if not isinstance(files, dict):
        raise ShardError("files must be an object of seconds per test file")
    key_problem = _file_key_rule()
    milliseconds: dict[str, int] = {}
    for key, seconds in files.items():
        problem = key_problem(key)
        if problem is not None:
            raise ShardError(problem)
        milliseconds[key] = _seconds_to_ms(seconds, f"files[{key!r}]")
    return milliseconds


def read_durations(path: Path | str) -> DurationsFile:
    """Parse the P1.4 durations file into integer milliseconds, or raise ``ShardError``.

    Accepts ``{"schema_version": 1, "files": {"tests/test_x.py": <seconds>}}``; other
    top-level keys are ignored (the scheduler's loader refuses them). Every ``files`` key
    must pass the generator's ``file_key_problem``. Seconds must be finite, non-negative
    and not bool, and become ``max(1, round(seconds * 1000))``.
    """
    location = Path(path)
    try:
        raw = location.read_bytes()
    except OSError as exc:
        raise ShardError(f"durations file {location.name}: unreadable ({type(exc).__name__})") from exc
    try:
        milliseconds = _parse_durations(raw)
    except ShardError as exc:
        raise ShardError(f"durations file {location.name}: {exc}") from None
    return DurationsFile(milliseconds, hashlib.sha256(raw).hexdigest())


def load_durations(path: Path | str) -> dict[str, int]:
    """Integer milliseconds per test file from the durations JSON at ``path``."""
    return read_durations(path).milliseconds


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def assign_files(
    nodeids: Iterable[str], durations_ms: Mapping[str, int], shard_count: int
) -> ShardPlan:
    """Split the collected files across ``shard_count`` shards, longest first.

    A known file weighs its recorded milliseconds. An unknown file weighs its node count
    times the known files' mean milliseconds per node (at least 1), or 1000 ms per node
    when no collected file is known. Files are taken in (-weight, path) order and each
    goes to the shard with the lowest (load_ms, file_count, index), so the plan does not
    depend on the order of ``nodeids``. Duplicate IDs, ``shard_count < 1`` and an empty
    shard raise ``ShardError``.
    """
    if not _is_int(shard_count) or shard_count < 1:
        raise ShardError(f"shard_count must be an integer >= 1: {shard_count!r}")
    ids = list(nodeids)
    if len(ids) != len(set(ids)):
        repeated = sorted(nodeid for nodeid, seen in Counter(ids).items() if seen > 1)
        raise ShardError(f"duplicate node IDs in the collection: {repeated[:3]!r}")
    node_counts = Counter(node_file(nodeid) for nodeid in ids)
    known = {path: durations_ms[path] for path in node_counts if path in durations_ms}
    for path, milliseconds in known.items():
        if not _is_int(milliseconds) or milliseconds < 1:
            raise ShardError(f"durations_ms[{path!r}] must be an integer >= 1: {milliseconds!r}")
    known_nodes = sum(node_counts[path] for path in known)
    per_node_ms = max(1, sum(known.values()) // known_nodes) if known_nodes else FALLBACK_NODE_MS
    weights = {
        path: known[path] if path in known else node_counts[path] * per_node_ms
        for path in node_counts
    }
    loads = [0] * shard_count
    sizes = [0] * shard_count
    file_shards: dict[str, int] = {}
    for path in sorted(node_counts, key=lambda candidate: (-weights[candidate], candidate)):
        target = min(range(shard_count), key=lambda index: (loads[index], sizes[index], index))
        file_shards[path] = target + 1
        loads[target] += weights[path]
        sizes[target] += 1
    empty = [index + 1 for index, size in enumerate(sizes) if size == 0]
    if empty:
        raise ShardError(
            f"shard(s) {empty} would get no files: {len(node_counts)} collected file(s) "
            f"cannot fill {shard_count} shards"
        )
    pairs = sorted([path, shard] for path, shard in file_shards.items())
    digest = hashlib.sha256(
        json.dumps(pairs, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    unknown = tuple(sorted(path for path in node_counts if path not in known))
    return ShardPlan(file_shards, tuple(loads), unknown, digest)


def assigned_nodeids(
    nodeids: Iterable[str], file_shards: Mapping[str, int], shard: int
) -> list[str]:
    """The sorted node IDs whose file the plan gives to ``shard``."""
    return sorted(nodeid for nodeid in nodeids if file_shards[node_file(nodeid)] == shard)


def build_evidence(
    *,
    shard_index: int,
    shard_count: int,
    worker_id: str,
    worker_count: int,
    testrunuid: str,
    exitstatus: int,
    durations_path: str,
    durations_sha256: str,
    collection: Sequence[str],
    plan: ShardPlan,
    setup_reports: Sequence[str],
) -> dict[str, Any]:
    """One pytest process's evidence. ``collection`` is the sorted, unique full collection."""
    assigned = assigned_nodeids(collection, plan.file_shards, shard_index)
    payload: dict[str, Any] = {
        "kind": EVIDENCE_KIND,
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "shard_index": shard_index,
        "shard_count": shard_count,
        "worker_id": worker_id,
        "worker_count": worker_count,
        "testrunuid": testrunuid,
        "exitstatus": int(exitstatus),
        "durations_path": durations_path,
        "durations_sha256": durations_sha256,
        "collection_count": len(collection),
        "collection_sha256": node_digest(collection),
        "assignment_sha256": plan.assignment_sha256,
        "assigned_count": len(assigned),
        "assigned_sha256": node_digest(assigned),
        "unknown_file_count": len(plan.unknown_files),
        "setup_reports": list(setup_reports),
    }
    if worker_id in PRIMARY_WORKER_IDS:
        payload["collected_nodeids"] = list(collection)
        payload["file_shards"] = dict(sorted(plan.file_shards.items()))
    return payload


def write_evidence(evidence_dir: Path | str, payload: Mapping[str, Any]) -> Path:
    """Atomically write ``<evidence_dir>/shard-<k>/<worker_id>.json`` and return its path."""
    worker_id = str(payload["worker_id"])
    if _WORKER_FILE.fullmatch(f"{worker_id}.json") is None:
        raise ShardError(f"worker id {worker_id!r} is not main or gw<N>")
    shard_index = payload["shard_index"]
    if not _is_int(shard_index) or shard_index < 1:
        raise ShardError(f"shard index {shard_index!r} is not a positive integer")
    directory = Path(evidence_dir) / f"shard-{shard_index}"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{worker_id}.json"
    temporary = directory / f".{worker_id}.{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


@dataclass
class ShardSummary:
    """What one shard assigned, executed and ran on, for the verified report."""

    shard: int
    assigned: int
    executed: int
    workers: int
    estimated_ms: int
    unknown_files: int


@dataclass
class VerifyResult:
    """Everything ``verify_evidence`` found. ``ok`` only if it found nothing wrong."""

    total_nodes: int = 0
    problems: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    duplicated: list[tuple[str, list[str]]] = field(default_factory=list)
    unexpected: list[tuple[str, str]] = field(default_factory=list)
    shards: list[ShardSummary] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.problems or self.missing or self.duplicated or self.unexpected)


@dataclass
class _Shard:
    index: int
    present: set[str]
    workers: dict[str, dict[str, Any]]


def _worker_order(worker_id: str) -> tuple[int, int]:
    return (0, 0) if worker_id == "main" else (1, int(worker_id[2:]))


def validate_evidence_shape(
    payload: object, *, worker_id: str, shard_index: int, shard_count: int
) -> list[str]:
    """Problems with one evidence payload's own fields; an empty list when well formed."""
    if not isinstance(payload, dict):
        return ["is not a JSON object"]
    checks: tuple[tuple[str, Any], ...] = (
        ("kind", lambda value: value == EVIDENCE_KIND),
        ("schema_version", lambda value: _is_int(value) and value == EVIDENCE_SCHEMA_VERSION),
        ("shard_index", lambda value: _is_int(value) and value == shard_index),
        ("shard_count", lambda value: _is_int(value) and value == shard_count),
        ("worker_id", lambda value: value == worker_id),
        ("worker_count", lambda value: _is_int(value) and 1 <= value <= MAX_WORKERS),
        ("testrunuid", lambda value: isinstance(value, str) and bool(value)),
        ("exitstatus", _is_int),
        ("durations_path", lambda value: isinstance(value, str)),
        ("durations_sha256", lambda value: isinstance(value, str) and _SHA256.fullmatch(value) is not None),
        ("collection_count", lambda value: _is_int(value) and value >= 1),
        ("collection_sha256", lambda value: isinstance(value, str) and _SHA256.fullmatch(value) is not None),
        ("assignment_sha256", lambda value: isinstance(value, str) and _SHA256.fullmatch(value) is not None),
        ("assigned_count", lambda value: _is_int(value) and value >= 1),
        ("assigned_sha256", lambda value: isinstance(value, str) and _SHA256.fullmatch(value) is not None),
        ("unknown_file_count", lambda value: _is_int(value) and value >= 0),
        (
            "setup_reports",
            lambda value: isinstance(value, list) and all(isinstance(item, str) for item in value),
        ),
    )
    problems = []
    for name, accepts in checks:
        if name not in payload:
            problems.append(f"lacks field {name}")
        elif not accepts(payload[name]):
            problems.append(f"has an invalid {name}: {str(payload[name])[:60]!r}")
    if worker_id in PRIMARY_WORKER_IDS:
        collected = payload.get("collected_nodeids")
        if not isinstance(collected, list) or not all(isinstance(item, str) for item in collected):
            problems.append("lacks a list of collected_nodeids")
        shards = payload.get("file_shards")
        if not isinstance(shards, dict) or not all(
            isinstance(key, str) and _is_int(value) for key, value in shards.items()
        ):
            problems.append("lacks a file_shards map")
    return problems


def _read_shards(root: Path, shard_count: int, result: VerifyResult) -> dict[int, _Shard]:
    shards: dict[int, _Shard] = {}
    if not root.is_dir():
        result.problems.append(f"evidence root {root} is not a directory")
        return shards
    expected = {f"shard-{index}" for index in range(1, shard_count + 1)}
    actual = {entry.name for entry in root.iterdir()}
    for name in sorted(expected - actual):
        result.problems.append(f"evidence root has no {name} directory")
    for name in sorted(actual - expected):
        result.problems.append(f"evidence root has an unexpected entry {name}")
    for index in range(1, shard_count + 1):
        directory = root / f"shard-{index}"
        if f"shard-{index}" not in actual:
            continue
        if directory.is_symlink() or not directory.is_dir():
            result.problems.append(f"shard-{index} is not a directory")
            continue
        shards[index] = _read_shard(directory, index, shard_count, result)
    return shards


def _read_shard(directory: Path, index: int, shard_count: int, result: VerifyResult) -> _Shard:
    shard = _Shard(index, set(), {})
    prefix = f"shard-{index}"
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if _WORKER_FILE.fullmatch(entry.name) is None or entry.is_symlink() or not entry.is_file():
            result.problems.append(f"{prefix} has an unexpected entry {entry.name}")
            continue
        worker_id = entry.name[: -len(".json")]
        shard.present.add(worker_id)
        try:
            payload = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError, RecursionError) as exc:
            result.problems.append(f"{prefix}/{entry.name} is unreadable ({type(exc).__name__})")
            continue
        flaws = validate_evidence_shape(
            payload, worker_id=worker_id, shard_index=index, shard_count=shard_count
        )
        if flaws:
            result.problems.extend(f"{prefix}/{entry.name} {flaw}" for flaw in flaws)
            continue
        shard.workers[worker_id] = payload
    _check_shard_workers(shard, result)
    return shard


def _check_shard_workers(shard: _Shard, result: VerifyResult) -> None:
    prefix = f"shard-{shard.index}"
    if not shard.present:
        result.problems.append(f"{prefix} holds no evidence files")
        return
    for worker_id in sorted(shard.workers, key=_worker_order):
        status = shard.workers[worker_id]["exitstatus"]
        if status != 0:
            result.problems.append(f"{prefix}/{worker_id} reports exitstatus {status}, not 0")
    counts = {payload["worker_count"] for payload in shard.workers.values()}
    run_uids = {payload["testrunuid"] for payload in shard.workers.values()}
    if len(counts) > 1:
        result.problems.append(f"{prefix} workers disagree on worker_count: {sorted(counts)}")
    if len(run_uids) > 1:
        result.problems.append(f"{prefix} mixes {len(run_uids)} different testrunuid values")
    if "main" in shard.present:
        if shard.present != {"main"}:
            result.problems.append(
                f"{prefix} mixes main.json with {sorted(shard.present - {'main'})}"
            )
        if counts - {1}:
            result.problems.append(f"{prefix}/main reports worker_count {sorted(counts)}, not 1")
        return
    if len(counts) == 1:
        expected = {f"gw{number}" for number in range(next(iter(counts)))}
        for worker_id in sorted(expected - shard.present, key=_worker_order):
            result.problems.append(f"{prefix} lacks worker file {worker_id}.json")
        for worker_id in sorted(shard.present - expected, key=_worker_order):
            result.problems.append(f"{prefix} has an extra worker file {worker_id}.json")


def _agreed_collection(shards: Mapping[int, _Shard], result: VerifyResult) -> list[str] | None:
    claims: dict[tuple[int, str], list[str]] = {}
    for shard in shards.values():
        for worker_id, payload in shard.workers.items():
            key = (payload["collection_count"], payload["collection_sha256"])
            claims.setdefault(key, []).append(f"shard-{shard.index}/{worker_id}")
    if not claims:
        result.problems.append("no evidence file could be read, so no collection can be checked")
        return None
    if len(claims) > 1:
        detail = "; ".join(
            f"{count} nodes sha256 {digest[:12]} from {', '.join(sources[:3])}"
            for (count, digest), sources in sorted(claims.items(), key=lambda item: item[1])
        )
        result.problems.append(f"workers report different full collections: {detail}")
        return None
    ((count, digest),) = claims
    reference: list[str] | None = None
    for shard in shards.values():
        for worker_id in sorted(PRIMARY_WORKER_IDS & set(shard.workers), key=_worker_order):
            where = f"shard-{shard.index}/{worker_id}"
            ids = shard.workers[worker_id]["collected_nodeids"]
            if ids != sorted(ids) or len(set(ids)) != len(ids):
                result.problems.append(f"{where} collected_nodeids is not sorted and unique")
            elif len(ids) != count or node_digest(ids) != digest:
                result.problems.append(
                    f"{where} collected_nodeids does not hash to its collection_sha256"
                )
            elif reference is None:
                reference = ids
    if reference is None:
        result.problems.append("no primary worker file carries a verifiable full collection")
    return reference


def _check_assignment(
    shards: Mapping[int, _Shard],
    collection: Sequence[str],
    plan: ShardPlan,
    durations: DurationsFile,
    result: VerifyResult,
) -> None:
    for shard in shards.values():
        assigned = assigned_nodeids(collection, plan.file_shards, shard.index)
        expected = (
            ("durations_sha256", durations.sha256),
            ("assignment_sha256", plan.assignment_sha256),
            ("assigned_sha256", node_digest(assigned)),
            ("assigned_count", len(assigned)),
            ("unknown_file_count", len(plan.unknown_files)),
        )
        differing: dict[str, list[str]] = {}
        for worker_id in sorted(shard.workers, key=_worker_order):
            payload = shard.workers[worker_id]
            for name, value in expected:
                if payload[name] != value:
                    differing.setdefault(name, []).append(worker_id)
            if worker_id in PRIMARY_WORKER_IDS and payload["file_shards"] != plan.file_shards:
                differing.setdefault("file_shards", []).append(worker_id)
        for name, workers in differing.items():
            result.problems.append(
                f"shard-{shard.index}: {', '.join(workers)} report a {name} that the verifier's "
                "recomputation from the collection and its durations file does not reproduce"
            )


def _check_executions(
    shards: Mapping[int, _Shard],
    collection: Sequence[str],
    plan: ShardPlan | None,
    result: VerifyResult,
) -> None:
    collected = set(collection)
    runs: dict[str, list[str]] = {}
    for shard in shards.values():
        for worker_id in sorted(shard.workers, key=_worker_order):
            where = f"shard-{shard.index}/{worker_id}"
            for nodeid in shard.workers[worker_id]["setup_reports"]:
                runs.setdefault(nodeid, []).append(where)
                if nodeid not in collected:
                    result.unexpected.append((nodeid, f"{where} ran it; it is not in the collection"))
                elif plan is not None and plan.file_shards[node_file(nodeid)] != shard.index:
                    result.unexpected.append(
                        (nodeid, f"{where} ran it; it belongs to shard-{plan.file_shards[node_file(nodeid)]}")
                    )
    result.missing = [nodeid for nodeid in collection if nodeid not in runs]
    result.duplicated = sorted(
        (nodeid, places) for nodeid, places in runs.items() if nodeid in collected and len(places) > 1
    )
    result.unexpected.sort()


def _summarise(
    shards: Mapping[int, _Shard],
    collection: Sequence[str],
    plan: ShardPlan | None,
    result: VerifyResult,
) -> None:
    for index in sorted(shards):
        shard = shards[index]
        assigned = len(assigned_nodeids(collection, plan.file_shards, index)) if plan else 0
        unknown = (
            sum(1 for path in plan.unknown_files if plan.file_shards[path] == index) if plan else 0
        )
        result.shards.append(
            ShardSummary(
                shard=index,
                assigned=assigned,
                executed=sum(len(payload["setup_reports"]) for payload in shard.workers.values()),
                workers=len(shard.present),
                estimated_ms=plan.shard_ms[index - 1] if plan else 0,
                unknown_files=unknown,
            )
        )


def verify_evidence(
    evidence_root: Path | str, shard_count: int, durations: DurationsFile
) -> VerifyResult:
    """Check the shard evidence under ``evidence_root``; the result lists everything wrong."""
    result = VerifyResult()
    shards = _read_shards(Path(evidence_root), shard_count, result)
    collection = _agreed_collection(shards, result)
    if collection is None:
        return result
    result.total_nodes = len(collection)
    plan: ShardPlan | None = None
    try:
        plan = assign_files(collection, durations.milliseconds, shard_count)
    except ShardError as exc:
        result.problems.append(f"the verifier cannot recompute the file assignment: {exc}")
    if plan is not None:
        _check_assignment(shards, collection, plan, durations, result)
    _check_executions(shards, collection, plan, result)
    _summarise(shards, collection, plan, result)
    return result


def _printable(text: str) -> str:
    escaped = text.encode("ascii", "backslashreplace").decode("ascii")
    return "".join(
        character if " " <= character <= "~" else f"\\x{ord(character):02x}"
        for character in escaped
    )


def _workflow_escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _category(lines: list[str], title: str, rows: list[str]) -> None:
    if not rows:
        return
    shown = rows[:MAX_REPORTED_NODES]
    lines.append(f"{title}: {len(rows)} (showing {len(shown)})")
    lines.extend(f"  {_printable(row)}" for row in shown)


def render_report(result: VerifyResult, shard_count: int) -> list[str]:
    """The lines ``verify`` prints: a summary when verified, else the findings and one ::error:: line."""
    if result.ok:
        lines = [
            f"verified {result.total_nodes} nodes: every collected node executed exactly once "
            f"across {shard_count} shards"
        ]
        lines.extend(
            f"  shard {summary.shard}: assigned={summary.assigned} executed={summary.executed} "
            f"workers={summary.workers} estimated_load={summary.estimated_ms / 1000:.1f}s "
            f"unknown_files={summary.unknown_files}"
            for summary in result.shards
        )
        return lines
    lines = ["CI shard evidence REJECTED"]
    lines.extend(f"  problem: {_printable(problem)}" for problem in result.problems)
    _category(lines, "missing (never executed)", result.missing)
    _category(
        lines,
        "duplicated (executed more than once)",
        [
            f"{nodeid} <- "
            + ", ".join(f"{place} x{times}" if times > 1 else place for place, times in Counter(places).items())
            for nodeid, places in result.duplicated
        ],
    )
    _category(
        lines,
        "unexpected (outside the collection or its shard)",
        [f"{nodeid} <- {detail}" for nodeid, detail in result.unexpected],
    )
    if result.problems:
        first = result.problems[0]
    elif result.missing:
        first = f"missing {result.missing[0]}"
    elif result.duplicated:
        first = f"duplicated {result.duplicated[0][0]}"
    else:
        first = f"unexpected {result.unexpected[0][0]}"
    summary = (
        f"{len(result.problems)} problem(s), {len(result.missing)} missing, "
        f"{len(result.duplicated)} duplicated, {len(result.unexpected)} unexpected; first: {first}"
    )
    lines.append(f"::error title=CI shard evidence::{_workflow_escape(_printable(summary))}")
    return lines


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1: {value}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ci_shards.py", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser(
        "verify", help="prove every collected test executed exactly once across the shards"
    )
    verify.add_argument("--evidence-root", required=True, type=Path, help="directory holding shard-1..shard-N")
    verify.add_argument("--shard-count", required=True, type=_positive_int, help="number of shards N")
    verify.add_argument(
        "--durations",
        type=Path,
        default=None,
        help=f"durations JSON (default: {DEFAULT_DURATIONS_PATH} in the repository)",
    )
    arguments = parser.parse_args(argv)
    durations_path = arguments.durations or REPO_ROOT / DEFAULT_DURATIONS_PATH
    try:
        durations = read_durations(durations_path)
    except ShardError as exc:
        print(f"ci_shards: usage error: {_printable(str(exc))}", file=sys.stderr)
        return 2
    result = verify_evidence(arguments.evidence_root, arguments.shard_count, durations)
    for line in render_report(result, arguments.shard_count):
        print(line)
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
