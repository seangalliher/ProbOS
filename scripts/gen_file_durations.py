"""AD-1270f P1.4: write ``tests/fixtures/file_durations.json`` from a green canonical gate.

    python scripts/gen_file_durations.py --junit PATH [--collection PATH] [--output PATH]

``--collection`` defaults to the sibling ``<stem>.collection.json`` that the
canonical wrapper writes next to ``<stem>.xml``, and ``--output`` to
``tests/fixtures/file_durations.json``. The scheduler in
``tests/fixtures/duration_scheduler.py`` reads that file to start the longest
test files first.

A testcase is credited to the collected file whose dotted module name (the path
with ``/`` replaced by ``.`` and the trailing ``.py`` dropped, which is how
pytest builds the legacy JUnit ``classname``) is the longest prefix of the
``classname`` ending at a ``.`` boundary. The ``file`` attribute is not used: for
a test inherited from a base class it names the file where the test is defined,
not the file that collected it. The testcase's node ID is rebuilt from that file,
the rest of the ``classname`` (the class chain) and the raw ``name``, which keeps
any parametrize id, ``/`` and ``::`` included. Time is summed per file.

The tool refuses -- exits 1 and leaves ``--output`` untouched -- unless the inputs
describe one clean run of exactly the collection: no failing or erroring testcase,
a readable collection artifact, every testcase credited to a collected file, the
rebuilt node IDs identical to the collected node IDs (none missing, none extra,
none repeated), every file path usable as a ``files`` key, and a positive total.
Identical inputs give byte-identical output.

Standard library only; it imports none of the gate scripts or tests. What a
``files`` key may look like is defined once, here (``file_key_problem``): the
scheduler's loader loads this file and applies the same function, so the writer
and the reader cannot disagree. The other schema constants are restated here and
pinned against the loader by ``tests/test_ad1270f_gen_file_durations.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import uuid
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path, PureWindowsPath
from typing import Any, NamedTuple, Sequence

SCHEMA_VERSION = 1
FILE_SECONDS_DIGITS = 1
MEAN_SECONDS_DIGITS = 4
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "file_durations.json"
_COLLECTION_SUFFIX = ".collection.json"
_FAILURE_TAGS = frozenset({"failure", "error"})
_MAX_REPORTED_MISMATCHES = 10


class DurationRefusal(Exception):
    """The inputs cannot be turned into a trustworthy durations file."""


def sibling_collection(junit: Path) -> Path:
    """The collection artifact the wrapper writes beside its JUnit report."""
    return junit.with_suffix(_COLLECTION_SUFFIX)


def dotted_module_name(file_path: str) -> str:
    """Legacy JUnit ``classname`` prefix for a collected file path."""
    stem = file_path[: -len(".py")] if file_path.endswith(".py") else file_path
    return stem.replace("/", ".")


def file_key_problem(key: str) -> str | None:
    """Why ``key`` cannot be a ``files`` key, or None when it can.

    A key is a relative test path as pytest writes it in a node ID: not empty, no
    drive or root, no backslash, no ``..`` segment and no ``::``. The scheduler's
    loader loads this module and applies this same function to every key it reads.
    """
    pure = PureWindowsPath(key)
    if (
        not key
        or "\\" in key
        or "::" in key
        or pure.drive
        or pure.root
        or ".." in key.split("/")
    ):
        return f"files key must be a relative test path with no '..', '::' or backslash: {key!r}"
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def collected_node_ids(collection: Path) -> list[str]:
    """The collected node IDs, from the wrapper's validated artifact."""
    try:
        payload = json.loads(collection.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        # ValueError covers a bad encoding, bad JSON and Python's integer digit limit;
        # RecursionError covers nesting the parser cannot follow. All are unreadable input.
        raise DurationRefusal(f"collection artifact is unreadable: {collection}: {exc}") from exc
    version = payload.get("schema_version") if isinstance(payload, dict) else None
    if isinstance(version, bool) or version != 1:
        raise DurationRefusal(f"collection artifact is not schema_version 1: {collection}")
    nodes = payload.get("collected_nodeids")
    if not isinstance(nodes, list) or not nodes or not all(isinstance(n, str) for n in nodes):
        raise DurationRefusal(f"collection artifact has no collected_nodeids: {collection}")
    if len(nodes) != len(set(nodes)):
        raise DurationRefusal("collection artifact lists a node ID more than once")
    return nodes


def _dotted_index(files: Sequence[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for file_path in files:
        dotted = dotted_module_name(file_path)
        if dotted in index:
            raise DurationRefusal(
                f"two collected files share the dotted name {dotted!r}: "
                f"{index[dotted]} and {file_path}"
            )
        index[dotted] = file_path
    return index


def _credit(classname: str, index: dict[str, str]) -> str | None:
    parts = classname.split(".")
    for length in range(len(parts), 0, -1):
        file_path = index.get(".".join(parts[:length]))
        if file_path is not None:
            return file_path
    return None


class Testcase(NamedTuple):
    """One JUnit testcase: the collected file it is credited to, its node ID, its seconds."""

    file: str
    node_id: str
    seconds: float


def _node_id(file_path: str, dotted: str, classname: str, name: str) -> str:
    """Rebuild the node ID: the file, the class chain left of ``classname``, the raw name."""
    rest = classname[len(dotted) :]
    chain = rest[1:].split(".") if rest else []
    return "::".join([file_path, *chain, name])


def read_testcases(junit: Path, index: dict[str, str]) -> list[Testcase]:
    """Every JUnit testcase, credited to its collected file; refuses a failing run or an orphan."""
    try:
        root = ET.parse(junit).getroot()
    except (OSError, ET.ParseError) as exc:
        raise DurationRefusal(f"JUnit report is unreadable: {junit}: {exc}") from exc
    testcases: list[Testcase] = []
    failing: list[str] = []
    orphans: list[str] = []
    credited: dict[str, tuple[str, str] | None] = {}
    for element in root.iter():
        if _local_tag(element) != "testcase":
            continue
        classname = element.attrib.get("classname", "")
        name = element.attrib.get("name", "")
        if any(_local_tag(child) in _FAILURE_TAGS for child in element):
            failing.append(f"{classname}::{name}")
            continue
        try:
            seconds = float(element.attrib["time"])
        except (KeyError, ValueError):
            raise DurationRefusal(f"testcase {classname}::{name} has no numeric time") from None
        if not math.isfinite(seconds) or seconds < 0:
            raise DurationRefusal(f"testcase {classname}::{name} has time {seconds!r}")
        if classname not in credited:
            file_path = _credit(classname, index)
            credited[classname] = (
                None if file_path is None else (file_path, dotted_module_name(file_path))
            )
        owner = credited[classname]
        if owner is None:
            orphans.append(f"{classname}::{name}")
            continue
        file_path, dotted = owner
        testcases.append(Testcase(file_path, _node_id(file_path, dotted, classname, name), seconds))
    if failing:
        raise DurationRefusal(
            f"{len(failing)} testcase(s) failed or errored, so the run is not clean: "
            + ", ".join(failing[:5])
        )
    if orphans:
        raise DurationRefusal(
            f"{len(orphans)} testcase(s) match no collected file: " + ", ".join(orphans[:5])
        )
    return testcases


def _require_the_collected_nodes(testcases: Sequence[Testcase], collected: Sequence[str]) -> None:
    """The JUnit must describe exactly the collection: every node once, nothing else."""
    seen = Counter(testcase.node_id for testcase in testcases)
    expected = set(collected)
    missing = sorted(expected - seen.keys())
    unexpected = sorted(seen.keys() - expected)
    repeated = sorted(node for node, count in seen.items() if count > 1)
    if not (missing or unexpected or repeated):
        return
    problems = (
        [f"collected but not in the JUnit: {node}" for node in missing]
        + [f"in the JUnit but not collected: {node}" for node in unexpected]
        + [f"repeated in the JUnit: {node}" for node in repeated]
    )
    raise DurationRefusal(
        "the JUnit is not a run of exactly this collection "
        f"({len(missing)} missing, {len(unexpected)} unexpected, {len(repeated)} repeated); "
        f"first {min(_MAX_REPORTED_MISMATCHES, len(problems))}: "
        + "; ".join(problems[:_MAX_REPORTED_MISMATCHES])
    )


def build_payload(junit: Path, collection: Path) -> dict[str, Any]:
    nodes = collected_node_ids(collection)
    files = sorted({node.split("::", 1)[0] for node in nodes})
    for file_path in files:
        problem = file_key_problem(file_path)
        if problem is not None:
            raise DurationRefusal(f"a collected file path cannot be written as a key: {problem}")
    testcases = read_testcases(junit, _dotted_index(files))
    _require_the_collected_nodes(testcases, nodes)
    times: dict[str, list[float]] = {}
    for testcase in testcases:
        times.setdefault(testcase.file, []).append(testcase.seconds)
    total = math.fsum(math.fsum(values) for values in times.values())
    if not total > 0:
        raise DurationRefusal(f"the run records no time (testcases={len(testcases)}, total={total})")
    mean = round(total / len(testcases), MEAN_SECONDS_DIGITS)
    if not mean > 0:
        raise DurationRefusal(f"mean seconds per test rounds to {mean}; the loader would reject it")
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "junit": junit.name,
            "collection": collection.name,
            "junit_sha256": _sha256_file(junit),
            "collection_sha256": _sha256_file(collection),
            "testcases": len(testcases),
            "total_seconds": round(total, FILE_SECONDS_DIGITS),
        },
        "mean_test_seconds": mean,
        "files": {
            file_path: round(math.fsum(times[file_path]), FILE_SECONDS_DIGITS)
            for file_path in sorted(times)
        },
    }


def render(payload: dict[str, Any]) -> bytes:
    """UTF-8, LF line endings, stable key order: the same inputs give the same bytes."""
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--junit", required=True, type=Path, help="JUnit XML of a green canonical gate")
    parser.add_argument(
        "--collection",
        type=Path,
        default=None,
        help="collection artifact (default: the sibling <stem>.collection.json)",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="file to write")
    arguments = parser.parse_args(argv)
    collection = arguments.collection or sibling_collection(arguments.junit)
    try:
        payload = build_payload(arguments.junit, collection)
        write_atomic(arguments.output, render(payload))
    except (DurationRefusal, OSError, ValueError, RecursionError) as exc:
        # Input problems exit 1 with a reason, never a traceback: besides refusals this
        # covers unreadable files and the parser limits that surface as ValueError.
        print(f"gen_file_durations: refusing, {arguments.output} not written: {exc}", file=sys.stderr)
        return 1
    source = payload["source"]
    print(
        f"gen_file_durations: wrote {arguments.output}: {len(payload['files'])} files, "
        f"{source['testcases']} testcases, {source['total_seconds']} s total, "
        f"{payload['mean_test_seconds']} s/test"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
