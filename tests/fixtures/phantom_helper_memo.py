"""AD-1270f P2.2: run the phantom-API helper's real ``main()`` in-process, keeping its parse cache between calls.

``scripts/phantom_api_ast_helper.py`` parses every ``*.py`` under ``src/probos``
three times per invocation (``build_index``, ``build_class_method_index`` and
``build_class_field_index``), and the kwargs tests paid that in a fresh interpreter
for each of ten calls. Here the helper source is read once, digested, and compiled
from those same bytes into a private module namespace. ``main()`` then runs against a
swapped ``sys.stdin``, with ``sys.stdout`` and ``sys.stderr`` captured, so the helper's
own module-level caches (keyed by resolved path only, never by content) stay warm for
the next call. ``main()``'s argument parsing, stdin read, aggregation, JSON output and
exit status stay under test; only the process boundary goes. An exit follows
``sys.exit``: None is status 0, an int is itself, and anything else is status 1 with
``str(code)`` and a newline written to the captured stderr, as CPython does.

The held module, and with it every parse it cached, is served again only while both
of these equal the values recorded when it was cached. Otherwise a fresh instance is
compiled and executed, and a fresh instance has empty caches:

* the content digest of the helper source;
* ``tree_fingerprint(src_root)``: the relative path and content digest of every
  ``*.py`` under the source root. That is everything the helper reads: three
  ``rglob`` builders, plus ``runtime.py`` and ``startup/finalize.py`` which sit under
  the root.

A cold run is cached only if those inputs are identical before and after it, so an
edit made while the helper was parsing cannot seed the cache. Any exception other than
``SystemExit`` discards the instance. The code that runs is the code that was digested:
it is compiled from the bytes read for the digest and not imported, so no ``__pycache__``
entry is read or written (a stale one could otherwise run old code under a new digest),
the module is never registered in ``sys.modules``, ``sys.path`` is untouched, and the
helper's private ``_*_CACHE`` globals are never read, cleared or patched. It cannot share
state with the copy that other phantom tests import.

Stated limits:

* There is no per-call time limit. A subprocess call is cut off by
  ``subprocess.run(timeout=...)``, but an in-process call cannot be preempted safely: a
  thread that swaps the process-wide standard streams cannot be cancelled. A hung call
  is guarded only by the suite-wide pytest-timeout (180 s). On Windows that timeout
  terminates the xdist worker, and the canonical gate's exactly-once check turns that
  into a red gate, never a false green. Test 1 of the kwargs file keeps a real
  subprocess, with its own 60 s guard.
* The instance shares the interpreter with the tests. A test that patched ``ast``,
  ``json``, ``re`` or ``pathlib`` while a run is in flight could change its result, as
  a fresh subprocess could not be affected. The fixture that owns an instance should be
  module-scoped so that no other file shares it.
* The process entry point (the ``__main__`` guard and ``sys.exit``) is not exercised
  here. A real subprocess test must keep covering it.
* The key covers what the helper reads today. If the helper starts reading another
  file, ``tree_fingerprint`` must be extended to include it.
* Not thread-safe: ``run`` swaps the process-wide standard streams.
"""

from __future__ import annotations

import hashlib
import io
import sys
import types
from dataclasses import dataclass
from pathlib import Path

HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "phantom_api_ast_helper.py"

_PRIVATE_MODULE_NAME = "_phantom_api_ast_helper_inprocess"

_Inputs = tuple[bytes, tuple[tuple[str, bytes], ...]]


@dataclass(frozen=True)
class HelperRun:
    """What the helper CLI would have produced: exit status and both text streams."""

    returncode: int
    stdout: str
    stderr: str


def _digest(data: bytes) -> bytes:
    return hashlib.blake2b(data, digest_size=16).digest()


def tree_fingerprint(root: Path) -> tuple[tuple[str, bytes], ...] | None:
    """(relative POSIX path, content digest) for every ``*.py`` under ``root``, or None if one is unreadable."""
    try:
        return tuple(
            (path.relative_to(root).as_posix(), _digest(path.read_bytes()))
            for path in sorted(root.rglob("*.py"))
        )
    except OSError:
        return None


def _exit_status(code: object, stderr: io.StringIO) -> int:
    """The status ``sys.exit(code)`` ends a process with. A code that is not an int is printed to ``stderr``."""
    if code is None:
        return 0
    if isinstance(code, int):
        return int(code)
    stderr.write(str(code) + "\n")
    return 1


class InProcessPhantomHelper:
    """Run ``main()`` of one private copy of the helper over ``src_root``; see the module docstring."""

    def __init__(self, src_root: Path, *, helper_path: Path = HELPER_PATH) -> None:
        self._src_root = Path(src_root)
        self._helper_path = Path(helper_path)
        self._module: types.ModuleType | None = None
        self._cached_inputs: _Inputs | None = None
        self.module_loads: int = 0
        self.cold_runs: int = 0
        self.warm_runs: int = 0

    def run(self, body: str) -> HelperRun:
        """Run the helper as ``python <helper> --src-root <src_root>`` would with ``body`` on stdin."""
        try:
            source, inputs = self._read_inputs()
        except OSError:
            self.release()
            raise
        held = self._module
        if held is not None and inputs is not None and inputs == self._cached_inputs:
            module, warm = held, True
            self.warm_runs += 1
        else:
            self.release()
            module, warm = self._load(source), False
            self.cold_runs += 1
        try:
            result = self._invoke(module, body)
        except BaseException:
            self.release()
            raise
        if not warm and inputs is not None and self._unchanged_since(inputs):
            self._module, self._cached_inputs = module, inputs
        return result

    def release(self) -> None:
        """Drop the held instance and every parse it cached. The counters are kept."""
        self._module = None
        self._cached_inputs = None

    def _read_inputs(self) -> tuple[bytes, _Inputs | None]:
        """The helper source, and the key it forms with the tree. The key is None when the tree is unreadable."""
        source = self._helper_path.read_bytes()
        tree = tree_fingerprint(self._src_root)
        return source, None if tree is None else (_digest(source), tree)

    def _unchanged_since(self, inputs: _Inputs) -> bool:
        try:
            return self._read_inputs()[1] == inputs
        except OSError:
            return False

    def _load(self, source: bytes) -> types.ModuleType:
        module = types.ModuleType(_PRIVATE_MODULE_NAME)
        module.__file__ = str(self._helper_path)
        code = compile(source, str(self._helper_path), "exec", dont_inherit=True)
        exec(code, module.__dict__)  # noqa: S102 -- this repository's own helper script, see the module docstring
        self.module_loads += 1
        return module

    def _invoke(self, module: types.ModuleType, body: str) -> HelperRun:
        stdout, stderr = io.StringIO(), io.StringIO()
        saved = (sys.stdin, sys.stdout, sys.stderr)
        sys.stdin, sys.stdout, sys.stderr = io.StringIO(body), stdout, stderr
        try:
            try:
                status = _exit_status(module.main(["--src-root", str(self._src_root)]), stderr)
            except SystemExit as exit_request:
                status = _exit_status(exit_request.code, stderr)
        finally:
            sys.stdin, sys.stdout, sys.stderr = saved
        return HelperRun(status, stdout.getvalue(), stderr.getvalue())
