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
not the file that collected it. Time is summed per file.

The tool refuses -- exits 1 and leaves ``--output`` untouched -- unless the inputs
describe one clean run of the whole collection: no failing or erroring testcase,
a readable collection artifact, every testcase credited to exactly one file, every
file's testcase count equal to its collected node count, and a positive total.
Identical inputs give byte-identical output. Standard library only; it imports
none of the gate scripts or tests, so the schema is restated here and pinned
against the loader by ``tests/test_ad1270f_gen_file_durations.py``.
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
from pathlib import Path
from typing import Any, Sequence

SCHEMA_VERSION = 1
FILE_SECONDS_DIGITS = 1
MEAN_SECONDS_DIGITS = 4
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "file_durations.json"
_COLLECTION_SUFFIX = ".collection.json"
_FAILURE_TAGS = frozenset({"failure", "error"})


class DurationRefusal(Exception):
    """The inputs cannot be turned into a trustworthy durations file."""


def sibling_collection(junit: Path) -> Path:
    """The collection artifact the wrapper writes beside its JUnit report."""
    return junit.with_suffix(_COLLECTION_SUFFIX)


def dotted_module_name(file_path: str) -> str:
    """Legacy JUnit ``classname`` prefix for a collected file path."""
    stem = file_path[: -len(".py")] if file_path.endswith(".py") else file_path
    return stem.replace("/", ".")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def collected_file_counts(collection: Path) -> Counter[str]:
    """Collected node count per file, from the wrapper's validated artifact."""
    try:
        payload = json.loads(collection.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DurationRefusal(f"collection artifact is unreadable: {collection}: {exc}") from exc
    version = payload.get("schema_version") if isinstance(payload, dict) else None
    if isinstance(version, bool) or version != 1:
        raise DurationRefusal(f"collection artifact is not schema_version 1: {collection}")
    nodes = payload.get("collected_nodeids")
    if not isinstance(nodes, list) or not nodes or not all(isinstance(n, str) for n in nodes):
        raise DurationRefusal(f"collection artifact has no collected_nodeids: {collection}")
    if len(nodes) != len(set(nodes)):
        raise DurationRefusal("collection artifact lists a node ID more than once")
    return Counter(node.split("::", 1)[0] for node in nodes)


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


def credited_seconds(junit: Path, index: dict[str, str]) -> tuple[dict[str, list[float]], Counter[str]]:
    """Per-file testcase times and counts; refuses a failing run or an orphan testcase."""
    try:
        root = ET.parse(junit).getroot()
    except (OSError, ET.ParseError) as exc:
        raise DurationRefusal(f"JUnit report is unreadable: {junit}: {exc}") from exc
    times: dict[str, list[float]] = {}
    counts: Counter[str] = Counter()
    failing: list[str] = []
    orphans: list[str] = []
    cache: dict[str, str | None] = {}
    for testcase in root.iter():
        if _local_tag(testcase) != "testcase":
            continue
        classname = testcase.attrib.get("classname", "")
        name = testcase.attrib.get("name", "")
        if any(_local_tag(child) in _FAILURE_TAGS for child in testcase):
            failing.append(f"{classname}::{name}")
            continue
        try:
            seconds = float(testcase.attrib["time"])
        except (KeyError, ValueError):
            raise DurationRefusal(f"testcase {classname}::{name} has no numeric time") from None
        if not math.isfinite(seconds) or seconds < 0:
            raise DurationRefusal(f"testcase {classname}::{name} has time {seconds!r}")
        if classname not in cache:
            cache[classname] = _credit(classname, index)
        file_path = cache[classname]
        if file_path is None:
            orphans.append(f"{classname}::{name}")
            continue
        times.setdefault(file_path, []).append(seconds)
        counts[file_path] += 1
    if failing:
        raise DurationRefusal(
            f"{len(failing)} testcase(s) failed or errored, so the run is not clean: "
            + ", ".join(failing[:5])
        )
    if orphans:
        raise DurationRefusal(
            f"{len(orphans)} testcase(s) match no collected file: " + ", ".join(orphans[:5])
        )
    return times, counts


def build_payload(junit: Path, collection: Path) -> dict[str, Any]:
    collected = collected_file_counts(collection)
    index = _dotted_index(sorted(collected))
    times, counts = credited_seconds(junit, index)
    mismatched = sorted(
        file_path
        for file_path in collected
        if counts.get(file_path, 0) != collected[file_path]
    )
    if mismatched:
        detail = ", ".join(
            f"{file_path} junit={counts.get(file_path, 0)} collected={collected[file_path]}"
            for file_path in mismatched[:5]
        )
        raise DurationRefusal(
            f"{len(mismatched)} file(s) have a different testcase count than collected nodes: {detail}"
        )
    testcases = sum(counts.values())
    total = math.fsum(math.fsum(values) for values in times.values())
    if testcases <= 0 or not total > 0:
        raise DurationRefusal(f"the run records no time (testcases={testcases}, total={total})")
    mean = round(total / testcases, MEAN_SECONDS_DIGITS)
    if not mean > 0:
        raise DurationRefusal(f"mean seconds per test rounds to {mean}; the loader would reject it")
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "junit": junit.name,
            "collection": collection.name,
            "junit_sha256": _sha256_file(junit),
            "collection_sha256": _sha256_file(collection),
            "testcases": testcases,
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
    except (DurationRefusal, OSError) as exc:
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
