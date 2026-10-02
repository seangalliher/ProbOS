"""AD-1270f P2.2: run the phantom-API helper's real ``main()`` in-process, keeping its parse cache between calls.

``scripts/phantom_api_ast_helper.py`` parses every ``*.py`` under ``src/probos``
three times per invocation (``build_index``, ``build_class_method_index`` and
``build_class_field_index``), and the kwargs tests paid that in a fresh interpreter
for each of ten calls. Here the helper is loaded once as a private module and
``main()`` runs against a swapped ``sys.stdin``, with ``sys.stdout`` and
``sys.stderr`` captured, so the helper's own module-level caches (keyed by resolved
path only, never by content) stay warm for the next call. ``main()``'s argument
parsing, stdin read, aggregation, JSON output and exit status stay under test; only
the process boundary goes.

The held module, and with it every parse it cached, is served again only while both
of these equal the values recorded when it was cached. Otherwise a fresh instance is
loaded, and a fresh instance has empty caches:

* the content digest of the helper file;
* ``tree_fingerprint(src_root)``: the relative path and content digest of every
  ``*.py`` under the source root. That is everything the helper reads: three
  ``rglob`` builders, plus ``runtime.py`` and ``startup/finalize.py`` which sit under
  the root.

A cold run is cached only if those inputs are identical before and after it, so an
edit made while the helper was parsing cannot seed the cache. Any exception other than
``SystemExit`` discards the instance. The private module is never registered in
``sys.modules``, ``sys.path`` is untouched, and the helper's private ``_*_CACHE``
globals are never read, cleared or patched, so it cannot share state with the copy
that other phantom tests import.

Stated limits:

* The instance shares the interpreter with the tests. A test that patched ``ast``,
  ``json``, ``re`` or ``pathlib`` while a run is in flight could change its result, as
  a fresh subprocess could not be affected. The fixture that owns an instance should be
  module-scoped so that no other file shares it.
* The process entry point (the ``__main__`` guard and ``sys.exit``) is not exercised
  here. A real subprocess test must keep covering it.
* The key covers what the helper reads today. If the helper starts reading another
  file, ``tree_fingerprint`` must be extended to include it.
* The helper source goes through Python's normal source loader, which can reuse a
  ``__pycache__`` entry whose recorded size and whole-second mtime match. An edit that
  keeps both can therefore run the old code although its digest changed. A script run
  in a subprocess never uses bytecode.
* Not thread-safe: ``run`` swaps the process-wide standard streams.
"""

from __future__ import annotations

import hashlib
import importlib.util
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


def _digest(path: Path) -> bytes:
    return hashlib.blake2b(path.read_bytes(), digest_size=16).digest()


def tree_fingerprint(root: Path) -> tuple[tuple[str, bytes], ...] | None:
    """(relative POSIX path, content digest) for every ``*.py`` under ``root``, or None if one is unreadable."""
    try:
        return tuple(
            (path.relative_to(root).as_posix(), _digest(path))
            for path in sorted(root.rglob("*.py"))
        )
    except OSError:
        return None


def _exit_status(code: object) -> int:
    """The process status ``sys.exit(code)`` would produce."""
    if code is None:
        return 0
    if isinstance(code, int):
        return int(code)
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
        inputs = self._inputs()
        held = self._module
        if held is not None and inputs is not None and inputs == self._cached_inputs:
            module, warm = held, True
            self.warm_runs += 1
        else:
            self.release()
            module, warm = self._load(), False
            self.cold_runs += 1
        try:
            result = self._invoke(module, body)
        except BaseException:
            self.release()
            raise
        if not warm and inputs is not None and self._inputs() == inputs:
            self._module, self._cached_inputs = module, inputs
        return result

    def release(self) -> None:
        """Drop the held instance and every parse it cached. The counters are kept."""
        self._module = None
        self._cached_inputs = None

    def _inputs(self) -> _Inputs | None:
        try:
            helper = _digest(self._helper_path)
        except OSError:
            return None
        tree = tree_fingerprint(self._src_root)
        return None if tree is None else (helper, tree)

    def _load(self) -> types.ModuleType:
        spec = importlib.util.spec_from_file_location(_PRIVATE_MODULE_NAME, self._helper_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load the phantom helper from {self._helper_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.module_loads += 1
        return module

    def _invoke(self, module: types.ModuleType, body: str) -> HelperRun:
        stdout, stderr = io.StringIO(), io.StringIO()
        saved = (sys.stdin, sys.stdout, sys.stderr)
        sys.stdin, sys.stdout, sys.stderr = io.StringIO(body), stdout, stderr
        try:
            try:
                status = _exit_status(module.main(["--src-root", str(self._src_root)]))
            except SystemExit as exit_request:
                status = _exit_status(exit_request.code)
        finally:
            sys.stdin, sys.stdout, sys.stderr = saved
        return HelperRun(status, stdout.getvalue(), stderr.getvalue())
