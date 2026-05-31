# AD-822 — Subprocess-isolated ChromaDB boot-time health probe

**Status:** Ready to build
**Dependencies:** AD-820 (shutdown_integrity.py), AD-819 (rebuild-episodic), AD-816 (pidfile_guard)
**GH Issue:** #756
**Estimated tests:** 6+ (in a single new file)

## Problem

AD-820's `check_previous_shutdown` only catches the case where the last shutdown
left a `partial` marker. The class of failure it misses is **corruption without
unclean shutdown** — e.g. a torn HNSW write from a previous process generation,
or a chroma.sqlite3 page corruption from disk error. In those cases the marker
says `status=clean` and the runtime opens ChromaDB anyway. The native side then
segfaults inside `chromadb.PersistentClient(...)` or the first
`get_or_create_collection(...)` call, killing the Python process with no
traceback (the failure mode that produced #750 the first time).

The fix is to probe ChromaDB **in an isolated subprocess** before the main
runtime touches it. If the subprocess survives a trivial open + peek + count,
the index is intact. If it segfaults / errors / hangs, the parent runtime
refuses to boot with an actionable remediation message pointing at
`probos rebuild-episodic` (AD-819).

## Live-environment constraint (read first)

**Do NOT touch the live operator runtime or any data dir under
`C:\Users\seang\AppData\Local\ProbOS\`.** All tests use `tmp_path`. Do NOT
attempt to open or repair the operator's real chroma store under any
circumstance.

## Codebase facts verified before drafting

These are grepped from HEAD; the prompt depends on them being accurate. If
HEAD has moved, re-verify before changing the line-number references.

```
src/probos/shutdown_integrity.py:42       class UncleanShutdownDetected(RuntimeError)
src/probos/shutdown_integrity.py:200      def check_previous_shutdown(data_dir, *, force_unclean, is_first_boot)
src/probos/__main__.py:557                async def _serve(...)
src/probos/__main__.py:594-611            AD-820 check block: imports + check_previous_shutdown + SystemExit(3)
src/probos/__main__.py:613                runtime, config, console = await _boot_runtime(...)
src/probos/cognitive/episodic.py:851      async def start(self) -> None:
src/probos/cognitive/episodic.py:858      self._client = chromadb.PersistentClient(path=str(db_dir))
src/probos/cognitive/episodic.py:860      get_or_create_collection(name="episodes", ...)
src/probos/agents/shell_command.py:154-227 canonical Popen + run_in_executor pattern (_run_sync)
src/probos/__main__.py:455-466            EpisodicMemory(...) construction in _boot_runtime
```

Two important facts the original spec got wrong; the Builder must use these:

1. **ChromaDB lives at `data_dir` root, NOT at `data_dir / "episodic"`.**
   `EpisodicMemory.start()` opens `PersistentClient(path=str(db_dir))` where
   `db_dir = Path(self.db_path).parent`. The db_path passed from `_boot_runtime`
   is `data_path / "episodic.db"`, so `db_dir == data_path`. There is no
   `episodic/` subdirectory. `chroma.sqlite3` sits in `data_path` directly,
   alongside `events.db`, `journal.db`, etc. The probe must open at the
   data_dir root, not at `data_dir/'episodic'`.

2. **Collection name is `"episodes"` (hardcoded in `episodic.py:860`).**
   `MemoryConfig.collection_name = "probos_episodes"` exists in config.py but
   is NOT what the live code uses for the episodes collection. The probe must
   call `get_collection("episodes")` to match production.

## Solution overview

Three new pieces of code, in this order:

1. **`src/probos/_episodic_probe.py`** — a standalone script invoked as
   `python -m probos._episodic_probe <data_dir>` that opens chroma, peeks
   one row, counts the collection, and exits 0/1. Designed to be killable
   without affecting anything else. Prints diagnostics to stderr on failure.

2. **`src/probos/episodic_health.py`** — public API
   `check_episodic_health(data_dir, timeout_s=30.0) -> EpisodicHealthResult`.
   Spawns the probe via `subprocess.Popen` (NOT `asyncio.create_subprocess_*`
   — see standing rule in `.github/copilot-instructions.md` and shell_command
   _run_sync precedent). Captures stderr to a tempfile (NOT stdout — BF-282
   Windows binary-stdout lesson; stderr is text but we use tempfile for
   consistency and to avoid any pipe-buffer deadlock). Waits up to
   `timeout_s`. Kills the process if it hangs. Returns a result dataclass.

3. **Wire into `_serve` in `src/probos/__main__.py`** — call
   `check_episodic_health` **after** `check_previous_shutdown` (line 598)
   and **before** `_boot_runtime` (line 613). If the result is not ok,
   raise `EpisodicCorruptionDetected` with the same operator-readable
   remediation shape as `UncleanShutdownDetected`. Honor an env-var
   bypass `PROBOS_SKIP_EPISODIC_HEALTH_CHECK=1` with a WARNING log.

The probe is read-only and only opens the existing collection — it MUST NOT
create the `episodes` collection. On a first boot where chroma doesn't
exist yet, the probe should exit 0 without error (treat absence as ok).

## Section 1 — Create `src/probos/_episodic_probe.py`

Create a NEW file at `src/probos/_episodic_probe.py`. Full content (no
existing file to modify):

```python
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
```

Engineering principles to verify in this file:

- All public/module-level functions fully typed.
- No `asyncio.create_subprocess_*` (there's no asyncio in this file at all —
  it's a sync script).
- Log/error context: every stderr message names the operation that failed
  (`open-client-failed`, `peek-or-count-failed`).
- No imports from `probos.runtime`, `probos.config`, or any startup module.

## Section 2 — Create `src/probos/episodic_health.py`

Create a NEW file at `src/probos/episodic_health.py`. Mirror the dataclass
shape used by `shutdown_integrity.py` (frozen dataclass + RuntimeError
subclass that formats an operator-readable remediation message).

```python
"""AD-822: subprocess-isolated ChromaDB boot-time health probe.

Companion to AD-820's :mod:`probos.shutdown_integrity`. Where AD-820 detects
*unclean shutdown* on the previous run, this module detects *corruption
present right now* — the class of failure that segfaults the runtime when
it first touches chroma (#750 root cause).

The probe spawns ``python -m probos._episodic_probe <data_dir>`` in a
subprocess. If the probe crashes (including native SIGSEGV), errors, or
hangs past ``timeout_s``, this module returns a non-ok result and the
caller refuses to boot.

Why a subprocess and not an in-process try/except: ChromaDB's native HNSW
code can SIGSEGV on a torn index. SIGSEGV bypasses Python's exception
machinery — a try/except cannot catch it. Running the probe in a child
process means a segfault kills the child without affecting the parent
runtime, and the parent observes the non-zero exit code as evidence.

Uses :class:`subprocess.Popen` rather than :func:`asyncio.create_subprocess_exec`
per the standing rule in ``.github/copilot-instructions.md`` —
``WindowsSelectorEventLoop`` does not support async subprocess. The
canonical reference for this pattern is
:meth:`probos.agents.shell_command.ShellCommandAgent._run_sync`.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SKIP_ENV_VAR = "PROBOS_SKIP_EPISODIC_HEALTH_CHECK"


class EpisodicCorruptionDetected(RuntimeError):
    """The episodic store failed the boot-time health probe.

    Carries the probe stderr / exit code so the caller can shape an
    operator-readable error message pointing at AD-819 recovery.
    """

    def __init__(self, data_dir: Path, error: str, duration_s: float) -> None:
        self.data_dir = data_dir
        self.error = error
        self.duration_s = duration_s
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        return (
            f"Episodic memory health probe failed after {self.duration_s:.1f}s.\n"
            f"  reason: {self.error}\n\n"
            f"The on-disk ChromaDB index appears corrupted. Booting the "
            f"runtime would likely segfault inside the native HNSW code.\n\n"
            f"Options:\n"
            f"  (a) Run 'probos rebuild-episodic' to reconstruct ChromaDB "
            f"from the surviving ward room (AD-819).\n"
            f"  (b) Restore the data dir from a backup (AD-823).\n"
            f"  (c) Set {SKIP_ENV_VAR}=1 to bypass the probe (NOT recommended "
            f"— the runtime will likely crash on first episodic access).\n\n"
            f"Data dir: {self.data_dir}"
        )


@dataclass(frozen=True)
class EpisodicHealthResult:
    ok: bool
    error: str | None
    duration_s: float


def check_episodic_health(
    data_dir: Path,
    *,
    timeout_s: float = 30.0,
) -> EpisodicHealthResult:
    """Probe chroma in a subprocess; return a result the caller can gate on.

    Args:
        data_dir: the per-instance data directory. Same value passed to
            ``EpisodicMemory(db_path=str(data_dir / 'episodic.db'))`` —
            chroma lives at ``data_dir`` root (not under an ``episodic/``
            subdir; see :func:`EpisodicMemory.start`).
        timeout_s: maximum wall time to wait for the probe. Defaults to
            30s; cold chroma open + HNSW load is normally <5s, so 30s
            leaves headroom for a slow disk.

    The :envvar:`PROBOS_SKIP_EPISODIC_HEALTH_CHECK` env var bypasses the
    probe entirely; a WARNING is logged so post-mortems can see the
    operator accepted the risk.
    """
    if os.environ.get(SKIP_ENV_VAR, "").strip() == "1":
        logger.warning(
            "AD-822: %s=1 — skipping episodic health probe (operator override)",
            SKIP_ENV_VAR,
        )
        return EpisodicHealthResult(ok=True, error=None, duration_s=0.0)

    data_dir = Path(data_dir)
    start = time.monotonic()

    # stderr -> tempfile (not stdout — BF-282 binary-stdout lesson, applied
    # defensively even though stderr is text). The tempfile is cleaned up
    # in finally so a hung child doesn't leak files.
    stderr_file = tempfile.NamedTemporaryFile(
        prefix="probos-episodic-probe-",
        suffix=".log",
        delete=False,
    )
    stderr_path = Path(stderr_file.name)
    stderr_file.close()

    proc: subprocess.Popen[bytes] | None = None
    try:
        with open(stderr_path, "wb") as stderr_sink:
            proc = subprocess.Popen(
                [sys.executable, "-m", "probos._episodic_probe", str(data_dir)],
                stdout=subprocess.DEVNULL,
                stderr=stderr_sink,
            )
            try:
                exit_code = proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                # Probe hung — almost certainly a torn index that's deadlocked
                # the chroma native code. Kill it and surface as a failure.
                proc.kill()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    pass
                duration_s = time.monotonic() - start
                logger.warning(
                    "AD-822: episodic health probe hung past %.1fs; killed",
                    timeout_s,
                )
                return EpisodicHealthResult(
                    ok=False,
                    error=f"probe timed out after {timeout_s:.1f}s",
                    duration_s=duration_s,
                )

        duration_s = time.monotonic() - start
        if exit_code == 0:
            logger.info(
                "AD-822: episodic health probe ok (%.2fs)", duration_s,
            )
            return EpisodicHealthResult(ok=True, error=None, duration_s=duration_s)

        try:
            stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            stderr_text = ""
        reason = stderr_text or f"probe exited with code {exit_code}"
        logger.warning(
            "AD-822: episodic health probe failed exit=%s reason=%s",
            exit_code, reason,
        )
        return EpisodicHealthResult(
            ok=False,
            error=reason,
            duration_s=duration_s,
        )
    finally:
        try:
            stderr_path.unlink(missing_ok=True)
        except OSError:
            pass
```

Engineering principles to verify in this file:

- `EpisodicHealthResult` is a frozen dataclass (matches `ShutdownStatusPayload`
  shape in shutdown_integrity.py).
- All public functions have full type annotations.
- Log messages include context: operation that failed, duration, env-var
  name on bypass. No bare `logger.warning("error")`.
- No `asyncio.create_subprocess_*`.
- Exception handling tiering:
  - `subprocess.TimeoutExpired` on the inner wait → log + return non-ok
    (log-and-degrade — caller decides whether to propagate).
  - `OSError` on stderr cleanup → swallow with comment (cleanup tier).
  - Probe non-zero exit → log + return non-ok (caller decides).
- No imports from `probos.runtime`, `probos.config`, or chroma directly
  (chroma must only live in the subprocess).

## Section 3 — Wire into `_serve` in `src/probos/__main__.py`

Read `src/probos/__main__.py` lines 580–615 to confirm context before
editing. The AD-820 block currently looks like:

```python
    # AD-820: refuse to start when the previous shutdown left the data dir
    # in a known-bad state. ...
    from probos.shutdown_integrity import (
        UncleanShutdownDetected,
        check_previous_shutdown,
    )
    _is_first_boot = not (resolved_data_dir / "events.db").exists()
    try:
        check_previous_shutdown(
            resolved_data_dir,
            force_unclean=force_unclean,
            is_first_boot=_is_first_boot,
        )
    except UncleanShutdownDetected as exc:
        console.print(f"[red]✗[/red] {exc}")
        # Release the pidfile so a follow-up recovery boot isn't blocked
        # by our own stale marker.
        try:
            _pidfile.unlink(missing_ok=True)
        except Exception:
            pass
        raise SystemExit(3) from exc

    runtime, config, console = await _boot_runtime(config_path, fresh, data_dir, console)
```

Insert a NEW block **between the AD-820 try/except and the
`_boot_runtime` call**, using SystemExit code **4** (AD-820 owns 2 and 3):

```
===MODIFY: src/probos/__main__.py===

===SEARCH===
    except UncleanShutdownDetected as exc:
        console.print(f"[red]✗[/red] {exc}")
        # Release the pidfile so a follow-up recovery boot isn't blocked
        # by our own stale marker.
        try:
            _pidfile.unlink(missing_ok=True)
        except Exception:
            pass
        raise SystemExit(3) from exc

    runtime, config, console = await _boot_runtime(config_path, fresh, data_dir, console)
===REPLACE===
    except UncleanShutdownDetected as exc:
        console.print(f"[red]✗[/red] {exc}")
        # Release the pidfile so a follow-up recovery boot isn't blocked
        # by our own stale marker.
        try:
            _pidfile.unlink(missing_ok=True)
        except Exception:
            pass
        raise SystemExit(3) from exc

    # AD-822: probe ChromaDB in an isolated subprocess BEFORE the runtime
    # opens it. Catches the corruption-without-unclean-shutdown class of
    # failure that AD-820's marker misses (e.g. torn HNSW from a prior
    # process generation, sqlite page corruption from disk error). A
    # SIGSEGV inside the probe kills only the child; the parent observes
    # the non-zero exit code and refuses to boot with an actionable
    # remediation message pointing at AD-819. PROBOS_SKIP_EPISODIC_HEALTH_CHECK=1
    # bypasses the probe with a WARNING log.
    from probos.episodic_health import (
        EpisodicCorruptionDetected,
        check_episodic_health,
    )
    _health = check_episodic_health(resolved_data_dir)
    if not _health.ok:
        _exc = EpisodicCorruptionDetected(
            resolved_data_dir,
            _health.error or "unknown probe failure",
            _health.duration_s,
        )
        console.print(f"[red]✗[/red] {_exc}")
        try:
            _pidfile.unlink(missing_ok=True)
        except Exception:
            pass
        raise SystemExit(4) from _exc

    runtime, config, console = await _boot_runtime(config_path, fresh, data_dir, console)
===END REPLACE===
```

## Section 4 — Tests

Create a NEW file at `tests/test_ad822_episodic_health.py` with at least
**6 tests**. Required cases (each one a separate test function):

1. `test_probe_on_healthy_db_returns_ok` — `tmp_path` data dir; build a real
   chroma store by opening `chromadb.PersistentClient(path=str(tmp_path))`,
   `get_or_create_collection("episodes")`, add a couple of rows, close;
   then call `check_episodic_health(tmp_path)`. Assert `result.ok is True`
   and `result.error is None`.
2. `test_probe_on_first_boot_returns_ok` — call `check_episodic_health` on
   a non-existent path. Assert `result.ok is True` (the probe treats absence
   of `chroma.sqlite3` as healthy first-boot).
3. `test_probe_on_corrupt_db_returns_not_ok` — `tmp_path`, write garbage
   bytes (e.g. `b"GARBAGE\x00" * 1024`) to `tmp_path / "chroma.sqlite3"`,
   call `check_episodic_health(tmp_path)`. Assert `result.ok is False` and
   `result.error` is non-empty.
4. `test_probe_timeout_returns_not_ok` — call `check_episodic_health(tmp_path,
   timeout_s=0.01)` with a real but slow-to-open store (or monkey-patch the
   probe entrypoint to sleep). Assert `result.ok is False` and "timed out"
   in `result.error`.
5. `test_skip_env_var_bypasses_probe` — set
   `PROBOS_SKIP_EPISODIC_HEALTH_CHECK=1` via monkeypatch, call
   `check_episodic_health(tmp_path)` against a CORRUPT db (so the probe
   would fail if it ran). Assert `result.ok is True` and `result.duration_s == 0.0`.
6. `test_subprocess_isolation_parent_survives_probe_crash` — run the probe
   against the same corrupt db as test 3 (which causes the chroma native
   side to error out). Assert that `check_episodic_health` returns a result
   (does NOT raise, does NOT kill the test process). Also assert that
   `os.getpid()` is the same before and after the call.

Test discipline reminders:

- All tests use `tmp_path` — NO test may touch
  `C:\Users\seang\AppData\Local\ProbOS\` or `d:/ProbOS/data/`.
- Each test creates its own fixtures, no shared mutable state.
- Order-independent — verify by running each test alone with `-k <name>`.
- Run with `pytest tests/test_ad822_episodic_health.py -v -n 0 --timeout=60`.
  Do NOT use `-n auto`.

If a test depends on real chromadb being installed, gate it with
`pytest.importorskip("chromadb")` at the top of the test function. The
probe itself does NOT need that gate — the probe's job is to spawn a
subprocess that imports chromadb; tests verify behavior, not that the
import succeeds.

## Section 5 — Boundaries (do not change)

- Do NOT modify `src/probos/shutdown_integrity.py`. AD-822 is additive next
  to AD-820, not a replacement.
- Do NOT modify `src/probos/cognitive/episodic.py`. The probe must NOT
  share code with `EpisodicMemory` — that's the entire point of subprocess
  isolation.
- Do NOT add new CLI flags. The bypass is env-var only (consistent with
  fail-safe defaults — operator must explicitly accept the risk).
- Do NOT touch `_boot_runtime` (line 404) — the wire-in goes in `_serve`
  before `_boot_runtime` is called. `_boot_runtime` is called from other
  test/CLI paths that should NOT trigger the probe (e.g. `probos run`
  without the server lifecycle).
- Do NOT add the probe to the rebuild-episodic CLI path. Rebuild explicitly
  opens a fresh chroma; running the probe against a corrupt db just before
  rebuilding it would be circular.
- Do NOT touch the operator's live data dir under
  `C:\Users\seang\AppData\Local\ProbOS\` at any point.

## Tracking

After Builder completes:

- `PROGRESS.md`: add `AD-822 — Subprocess-isolated ChromaDB boot health probe`
  with commit SHA + test count.
- `docs/development/roadmap.md`: tick #756 closed.
- Do NOT append to `DECISIONS.md` unless explicitly requested — the design
  is already captured here and the AD body in PROGRESS.md is sufficient.

## Acceptance criteria

- [ ] All 6+ tests pass with `pytest tests/test_ad822_episodic_health.py -v -n 0 --timeout=60`.
- [ ] Full focused test gate green:
      `pytest tests/test_ad820_shutdown_integrity.py tests/test_ad819_rebuild_episodic.py tests/test_ad821_hnsw_sync.py tests/test_ad822_episodic_health.py -v -n 0 --timeout=60`.
- [ ] Full parallel gate green:
      `pytest tests/ -q -n 4 --dist=loadfile --timeout=60`.
- [ ] Boot path: starting the runtime against a corrupted `chroma.sqlite3`
      under `tmp_path` exits with SystemExit(4) and prints the
      `EpisodicCorruptionDetected` remediation message.
- [ ] `PROBOS_SKIP_EPISODIC_HEALTH_CHECK=1` boot path: same corrupt db,
      runtime proceeds past the probe with a WARNING log line containing
      `AD-822: ... operator override`.
- [ ] No `asyncio.create_subprocess_*` introduced anywhere.
- [ ] No imports of `chromadb` outside `_episodic_probe.py`.
- [ ] Cross-platform: probe spawning uses `sys.executable` and `Path`
      throughout, no string concat or shell quoting.
- [ ] Verify all changes comply with the Engineering Principles in
      `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-22)

```
grep -n "class UncleanShutdownDetected" src/probos/shutdown_integrity.py
  47: class UncleanShutdownDetected(RuntimeError):

grep -n "def check_previous_shutdown" src/probos/shutdown_integrity.py
  200: def check_previous_shutdown(

grep -n "async def _serve" src/probos/__main__.py
  557: async def _serve(

grep -n "check_previous_shutdown" src/probos/__main__.py
  594:        check_previous_shutdown,
  598:        check_previous_shutdown(

grep -n "SystemExit(3)" src/probos/__main__.py
  611:        raise SystemExit(3) from exc

grep -n "await _boot_runtime" src/probos/__main__.py
  613:    runtime, config, console = await _boot_runtime(config_path, fresh, data_dir, console)

grep -n "PersistentClient" src/probos/cognitive/episodic.py
  858:        self._client = chromadb.PersistentClient(path=str(db_dir))

grep -n 'name="episodes"' src/probos/cognitive/episodic.py
  860:            self._collection = self._client.get_or_create_collection(
  861:                name="episodes",

grep -n "EpisodicMemory(" src/probos/__main__.py
  455:    episodic_memory = EpisodicMemory(

grep -n 'episodic_db = data_path' src/probos/__main__.py
  454:    episodic_db = data_path / "episodic.db"

# Confirmed absent (new files):
file_search src/probos/episodic_health.py   -> not found
file_search src/probos/_episodic_probe.py   -> not found
file_search tests/test_ad822_episodic_health.py -> not found
```
