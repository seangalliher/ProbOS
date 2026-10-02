"""AD-1270f P2.2: the in-process phantom-helper harness used by the kwargs tests.

``tests/fixtures/phantom_helper_memo.py`` runs the helper's real ``main()`` in-process and
keeps the helper's parse cache between calls. The kwargs tests prove it against the real
helper and tree. These tests pin its own rules on tiny tmp_path trees and stub helpers:
when a held instance may be served again, that a changed helper runs the changed code and
never a stale ``__pycache__`` entry, how an exit maps to a status and stderr, and that a
failed run leaves nothing held.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import os
import py_compile
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

from tests.fixtures.phantom_helper_memo import (
    HelperRun,
    InProcessPhantomHelper,
    tree_fingerprint,
)

_BODY = "hello"
_CALL = 'rows = event_log.query(event_type="x", limit=1)\n'
# Same length on purpose: a size-and-mtime check cannot tell the two apart.
_FLAGGING = "class EventLog:\n    def query(self, event_typo=None, limit=10):\n        return []\n"
_ACCEPTING = "class EventLog:\n    def query(self, event_type=None, limit=10):\n        return []\n"
_COUNTING = (
    "import sys\n"
    "calls = 0\n"
    "\n"
    "\n"
    "def main(argv=None):\n"
    "    global calls\n"
    "    calls += 1\n"
    "    if sys.stdin.read() == 'raise':\n"
    "        raise RuntimeError('boom')\n"
    "    print(calls)\n"
    "    return 0\n"
)


def _tree(tmp_path: Path, mod_source: str = "X = 1\n") -> Path:
    src_root = tmp_path / "src" / "probos"
    src_root.mkdir(parents=True)
    (src_root / "mod.py").write_bytes(mod_source.encode("utf-8"))
    return src_root


def _helper_file(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "helper.py"
    path.write_bytes(source.encode("utf-8"))
    return path


def _echo(marker: str) -> str:
    """A helper whose ``main`` prints ``marker`` and the stdin it was given."""
    return (
        f"MARKER = {marker!r}\n"
        "import sys\n"
        "\n"
        "\n"
        "def main(argv=None):\n"
        "    print(MARKER + ':' + sys.stdin.read())\n"
        "    return 0\n"
    )


def _counters(helper: InProcessPhantomHelper) -> tuple[int, int, int]:
    return helper.module_loads, helper.cold_runs, helper.warm_runs


def _rewrite_keeping_stamp(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` of the same length and put its mtime back."""
    before = path.stat()
    data = text.encode("utf-8")
    assert len(data) == before.st_size, "the edit must keep the size"
    path.write_bytes(data)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = path.stat()
    assert (after.st_size, after.st_mtime_ns) == (before.st_size, before.st_mtime_ns)


def _marker_an_import_would_run(path: Path) -> str:
    """The ``MARKER`` that importing ``path`` executes: the stock loader consults ``__pycache__``."""
    name = "_stock_import_probe"
    namespace: dict[str, object] = {}
    exec(SourceFileLoader(name, str(path)).get_code(name), namespace)  # noqa: S102 -- a stub this test wrote
    return str(namespace["MARKER"])


def _flagged_kwargs(result: HelperRun) -> set[str]:
    assert result.returncode == 0, result.stderr
    return {p["kwarg"] for p in json.loads(result.stdout)["phantoms"] if "kwarg" in p}


@pytest.mark.parametrize(
    ("main_body", "status", "stderr"),
    [
        pytest.param("return None", 0, "", id="return-none"),
        pytest.param("return 3", 3, "", id="return-int"),
        pytest.param("return 'boom'", 1, "boom\n", id="return-str"),
        pytest.param("raise SystemExit", 0, "", id="exit-none"),
        pytest.param("raise SystemExit(7)", 7, "", id="exit-int"),
        pytest.param("raise SystemExit(True)", 1, "", id="exit-bool"),
        pytest.param("raise SystemExit('boom')", 1, "boom\n", id="exit-str"),
        pytest.param("raise SystemExit((1, 2))", 1, "(1, 2)\n", id="exit-tuple"),
    ],
)
def test_an_exit_maps_to_the_status_and_stderr_sys_exit_gives(
    tmp_path: Path, main_body: str, status: int, stderr: str,
) -> None:
    source = f"def main(argv=None):\n    {main_body}\n"
    helper = InProcessPhantomHelper(_tree(tmp_path), helper_path=_helper_file(tmp_path, source))

    result = helper.run(_BODY)

    assert result == HelperRun(status, "", stderr)
    assert type(result.returncode) is int


def test_the_body_is_stdin_and_both_output_streams_are_captured_then_restored(tmp_path: Path) -> None:
    src_root = _tree(tmp_path)
    source = (
        "import sys\n"
        "\n"
        "\n"
        "def main(argv=None):\n"
        "    print('out:' + sys.stdin.read() + '|' + ' '.join(argv))\n"
        "    print('err', file=sys.stderr)\n"
        "    return 0\n"
    )
    helper = InProcessPhantomHelper(src_root, helper_path=_helper_file(tmp_path, source))
    streams = (sys.stdin, sys.stdout, sys.stderr)

    result = helper.run(_BODY)

    assert result == HelperRun(0, f"out:hello|--src-root {src_root}\n", "err\n")
    assert all(now is before for now, before in zip((sys.stdin, sys.stdout, sys.stderr), streams))


def test_an_unchanged_input_is_served_warm_and_an_exception_discards_the_instance(tmp_path: Path) -> None:
    helper = InProcessPhantomHelper(_tree(tmp_path), helper_path=_helper_file(tmp_path, _COUNTING))
    streams = (sys.stdin, sys.stdout, sys.stderr)

    assert helper.run("go").stdout == "1\n"
    assert helper.run("go").stdout == "2\n", "the same instance, so its state carries over"
    with pytest.raises(RuntimeError, match="boom"):
        helper.run("raise")
    assert all(now is before for now, before in zip((sys.stdin, sys.stdout, sys.stderr), streams))
    assert helper.run("go").stdout == "1\n", "a fresh instance after the failure"
    assert _counters(helper) == (2, 2, 2)


def test_a_changed_helper_runs_its_changed_code(tmp_path: Path) -> None:
    helper_path = _helper_file(tmp_path, _echo("OLD"))
    helper = InProcessPhantomHelper(_tree(tmp_path), helper_path=helper_path)
    assert helper.run(_BODY).stdout == "OLD:hello\n"
    assert helper.run(_BODY).stdout == "OLD:hello\n"
    assert _counters(helper) == (1, 1, 1)

    helper_path.write_bytes(_echo("CHANGED").encode("utf-8"))

    assert helper.run(_BODY).stdout == "CHANGED:hello\n"
    assert _counters(helper) == (2, 2, 1)
    assert helper.run(_BODY).stdout == "CHANGED:hello\n"
    assert _counters(helper) == (2, 2, 2)


def test_a_same_size_same_mtime_edit_runs_the_new_source_not_stale_bytecode(tmp_path: Path) -> None:
    helper_path = _helper_file(tmp_path, _echo("OLD"))
    py_compile.compile(
        str(helper_path), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
    )
    helper = InProcessPhantomHelper(_tree(tmp_path), helper_path=helper_path)
    assert helper.run(_BODY).stdout == "OLD:hello\n"

    _rewrite_keeping_stamp(helper_path, _echo("NEW"))

    assert _marker_an_import_would_run(helper_path) == "OLD", "premise: an import would run the stale bytecode"
    assert helper.run(_BODY).stdout == "NEW:hello\n"
    assert _counters(helper) == (2, 2, 0)


def test_loading_writes_no_bytecode_and_registers_no_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    helper_path = _helper_file(tmp_path, _echo("OLD"))
    sys_path = list(sys.path)

    InProcessPhantomHelper(_tree(tmp_path), helper_path=helper_path).run(_BODY)

    assert not Path(importlib.util.cache_from_source(str(helper_path))).exists()
    assert all(getattr(module, "__file__", None) != str(helper_path) for module in list(sys.modules.values()))
    assert sys.path == sys_path


def test_the_code_that_runs_is_the_code_that_was_digested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper_path = _helper_file(tmp_path, _echo("OLD"))
    # Successive reads of the helper disagree: the first is OLD, every later one is NEW.
    reads = itertools.chain([_echo("OLD").encode("utf-8")], itertools.repeat(_echo("NEW").encode("utf-8")))
    real_read_bytes = Path.read_bytes

    def read_bytes(self: Path) -> bytes:
        return next(reads) if self == helper_path else real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    helper = InProcessPhantomHelper(_tree(tmp_path), helper_path=helper_path)

    assert helper.run(_BODY).stdout == "OLD:hello\n", "compiled from the read that was digested, not a second read"
    assert _counters(helper) == (1, 1, 0)
    assert helper.run(_BODY).stdout == "NEW:hello\n", "the post-run read saw NEW, so OLD was not kept"
    assert _counters(helper) == (2, 2, 0)
    assert helper.run(_BODY).stdout == "NEW:hello\n"
    assert _counters(helper) == (2, 2, 1)


def test_a_tree_edit_that_keeps_size_and_mtime_is_seen_by_the_next_run(tmp_path: Path) -> None:
    src_root = _tree(tmp_path, _FLAGGING)
    helper = InProcessPhantomHelper(src_root)
    assert _flagged_kwargs(helper.run(_CALL)) == {"event_type"}
    assert _flagged_kwargs(helper.run(_CALL)) == {"event_type"}
    assert _counters(helper) == (1, 1, 1)

    _rewrite_keeping_stamp(src_root / "mod.py", _ACCEPTING)

    assert _flagged_kwargs(helper.run(_CALL)) == set()
    assert _counters(helper) == (2, 2, 1)


def test_an_edit_made_during_a_cold_run_keeps_that_instance_out_of_the_cache(tmp_path: Path) -> None:
    src_root = _tree(tmp_path)
    source = (
        "import sys\n"
        "\n"
        "\n"
        "def main(argv=None):\n"
        "    if sys.stdin.read() == 'edit':\n"
        f"        with open({str(src_root / 'mod.py')!r}, 'ab') as handle:\n"
        "            handle.write(b'#')\n"
        "    return 0\n"
    )
    helper = InProcessPhantomHelper(src_root, helper_path=_helper_file(tmp_path, source))
    original = (src_root / "mod.py").read_bytes()

    helper.run("edit")
    (src_root / "mod.py").write_bytes(original)

    helper.run("quiet")
    assert _counters(helper) == (2, 2, 0), "an instance built while the tree changed was not kept"
    helper.run("quiet")
    assert _counters(helper) == (2, 2, 1)


def test_tree_fingerprint_is_each_py_files_relative_path_and_content_digest(tmp_path: Path) -> None:
    src_root = _tree(tmp_path)
    (src_root / "pkg").mkdir()
    (src_root / "pkg" / "inner.py").write_bytes(b"Y = 2\n")
    (src_root / "notes.txt").write_bytes(b"not python\n")

    first = tree_fingerprint(src_root)

    assert first is not None
    assert [path for path, _ in first] == ["mod.py", "pkg/inner.py"]
    assert len({digest for _, digest in first}) == 2
    assert all(len(digest) == 16 for _, digest in first)
    os.utime(src_root / "mod.py", (1_000_000_000, 1_000_000_000))
    assert tree_fingerprint(src_root) == first, "an mtime-only change is not a change"
    (src_root / "mod.py").write_bytes(b"X = 9\n")
    assert tree_fingerprint(src_root) != first, "a same-size content change is"


def test_an_unreadable_tree_entry_gives_no_fingerprint_and_is_never_cached(tmp_path: Path) -> None:
    src_root = _tree(tmp_path)
    (src_root / "bad.py").mkdir()
    assert tree_fingerprint(src_root) is None

    helper = InProcessPhantomHelper(src_root, helper_path=_helper_file(tmp_path, _echo("OLD")))
    helper.run(_BODY)
    helper.run(_BODY)

    assert _counters(helper) == (2, 2, 0)


def test_a_missing_helper_raises_and_leaves_nothing_held(tmp_path: Path) -> None:
    helper_path = _helper_file(tmp_path, _echo("OLD"))
    helper = InProcessPhantomHelper(_tree(tmp_path), helper_path=helper_path)
    helper.run(_BODY)

    helper_path.unlink()
    with pytest.raises(OSError):
        helper.run(_BODY)

    helper_path.write_bytes(_echo("OLD").encode("utf-8"))
    helper.run(_BODY)
    assert _counters(helper) == (2, 2, 0), "the instance was dropped when the helper went missing"
