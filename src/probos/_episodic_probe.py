"""AD-822: subprocess-isolated ChromaDB health probe.

Spawned by :mod:`probos.episodic_health` as
``python -m probos._episodic_probe <data_dir>``. Opens chroma at the given
data_dir, peeks one row from the ``episodes`` collection, calls ``.count()``,
exits 0 on success.

Any uncaught exception (including SIGSEGV inside the chroma native code) kills
this process WITHOUT taking the parent runtime down. Caller treats non-zero
exit + any stderr content as evidence the index is unsafe to open.

Read-only:
    * Opens the existing collection via :meth:`get_collection`, never
      :meth:`get_or_create_collection`. A first-boot data_dir where the
      ``episodes`` collection does not yet exist is treated as healthy
      (exit 0 with note on stderr).
    * Does no writes, no migrations, no schema mutations.

Output contract:
    * stdout: a single line ``ok rows=<count>`` on success.
    * stderr: a single line describing the failure on error.
    * exit code: 0 = healthy, 1 = unhealthy, 2 = bad arguments.

Do NOT import probos.runtime or any heavy module here — the probe must
boot fast and have no side effects on event_log / pidfile / etc.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _probe(data_dir: Path) -> int:
    try:
        import chromadb
    except Exception as exc:  # pragma: no cover — defensive
        print(f"import-chromadb-failed: {exc!r}", file=sys.stderr)
        return 1

    if not data_dir.exists():
        # First boot: data_dir hasn't been created yet. Treat as healthy.
        print("ok rows=0 first-boot", file=sys.stdout)
        return 0

    sqlite_marker = data_dir / "chroma.sqlite3"
    if not sqlite_marker.exists():
        # data_dir exists but chroma has never been initialized here.
        # Healthy — runtime will create the collection on first start().
        print("ok rows=0 no-chroma-sqlite", file=sys.stdout)
        return 0

    # AD-822b: structural HNSW file validation BEFORE chromadb touches
    # the files. Catches torn writes that would segfault inside the
    # native mmap path. Read-only, <10ms.
    try:
        from probos.episodic_health import validate_hnsw_files
        validation = validate_hnsw_files(data_dir)
    except Exception as exc:
        # Defensive: if validation itself throws, treat as a soft
        # failure rather than masking it with a successful open.
        print(f"hnsw-validation-crashed: {exc!r}", file=sys.stderr)
        return 5
    if not validation.ok:
        for err in validation.errors:
            print(f"hnsw-validation: {err}", file=sys.stderr)
        return 5

    try:
        client = chromadb.PersistentClient(path=str(data_dir))
    except Exception as exc:
        print(f"open-client-failed: {exc!r}", file=sys.stderr)
        return 1

    try:
        collection = client.get_collection(name="episodes")
    except Exception as exc:
        # If the collection simply does not exist, that's NOT corruption —
        # the runtime will create it. Anything else (deserialization, HNSW
        # load failure, sqlite schema corruption) IS corruption.
        msg = str(exc).lower()
        if "does not exist" in msg or "could not find" in msg:
            print("ok rows=0 no-collection", file=sys.stdout)
            return 0
        print(f"get-collection-failed: {exc!r}", file=sys.stderr)
        return 1

    try:
        # Peek before count: peek triggers HNSW load if it's going to fail.
        _ = collection.peek(1)
        rows = collection.count()
    except Exception as exc:
        print(f"peek-or-count-failed: {exc!r}", file=sys.stderr)
        return 1

    print(f"ok rows={rows}", file=sys.stdout)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m probos._episodic_probe <data_dir>", file=sys.stderr)
        return 2
    return _probe(Path(argv[1]))


if __name__ == "__main__":  # pragma: no cover — script entrypoint
    raise SystemExit(main(sys.argv))
