"""AD-1270 (#1324) Night Orders slice 1b: T2 finds a producer of an inert trigger by parsing.

T2 (``test_the_inert_triggers_still_have_no_producer``) parses every Python file git
tracks under ``src/probos``, from its bytes. It fails on a call to ``set_alert_condition``
and on an ``emit_event*`` call whose event argument contains one of the four old event
names as a string constant (``_old_producer_calls``). The fixtures pin what the scan
flags, what it ignores and what it does not resolve (register 1b-R1 and 1b-R2 on #1324);
the tests over a temporary git repository run T2's own file list and scan. T2 is a
backstop, not a guarantee.
"""
from __future__ import annotations

import ast
import functools
import importlib.util
import subprocess
import sys
import tokenize
import types
from collections.abc import Callable
from pathlib import Path

import pytest

from probos.events import EventType

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src" / "probos"
_CHECKER_PATH = _REPO_ROOT / "scripts" / "check_architecture_principles.py"
_CHECKER_NAME = "_ad1270_recall_architecture_checker"
_OLD_EVENT_NAMES = frozenset({"trust_change", "alert_condition_change", "security_alert", "red_alert"})


# --- The scan ---------------------------------------------------------------------------


@functools.cache
def _checker() -> types.ModuleType:
    """The architecture checker, loaded from its path (``scripts/`` is not a package).

    Registered under a name of its own, so this file never replaces the module another test
    file registers as ``check_architecture_principles``; registered at all because its
    dataclasses read their annotations through ``sys.modules``.
    """
    spec = importlib.util.spec_from_file_location(_CHECKER_NAME, _CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_CHECKER_NAME] = module
    spec.loader.exec_module(module)
    return module


def _tracked_sources(root: Path) -> list[str]:
    """Root-relative POSIX names of the ``*.py`` files git tracks under ``root``.

    The checker's ``git ls-files`` list, not a disk walk, so an untracked file is not read.
    The checker returns ``None`` when git cannot answer; that, or an empty list, fails here,
    so the guard cannot pass by reading nothing.
    """
    names = _checker()._tracked_python_files(root)
    assert names, f"git listed no tracked Python file under {root} (not a git checkout, or none tracked)"
    return names


def _event_argument(call: ast.Call) -> ast.expr | None:
    """The expression ``call`` passes first by position, or ``None``.

    A ``*`` over a tuple or list display is opened, and its elements take its place.
    """
    pending = list(call.args)
    while pending:
        arg = pending.pop(0)
        if isinstance(arg, ast.Starred) and isinstance(arg.value, (ast.Tuple, ast.List)):
            pending[:0] = arg.value.elts
            continue
        return arg
    return None


def _old_producer_calls(source: str | bytes, filename: str = "<unknown>") -> list[tuple[int, str]]:
    """``(line, name)`` for each call in ``source`` that may produce an inert trigger, in line order.

    Flagged: a call whose callee (a name or an attribute) is ``set_alert_condition``; and a call
    whose callee, with leading underscores stripped, starts with ``emit_event`` and whose event
    argument (``_event_argument``) contains a string constant equal to an old event name.
    Keywords are never read (round 3 G1: a forwarder's keywords can be payload). ``source`` is
    parsed whole; a source that does not parse raises ``SyntaxError``.
    """
    hits: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        callee = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
        if callee == "set_alert_condition":
            hits.append((node.lineno, callee))
        if not callee.lstrip("_").startswith("emit_event"):
            continue
        event = _event_argument(node)
        if event is None:
            continue
        for part in ast.walk(event):
            if isinstance(part, ast.Constant) and part.value in _OLD_EVENT_NAMES:
                hits.append((node.lineno, part.value))
    return sorted(hits)


def _scan(root: Path) -> dict[str, list[tuple[int, str]]]:
    """T2's scan: ``{name: hits}`` for each file ``_tracked_sources(root)`` lists that has a hit.

    Each file's bytes go to ``ast.parse``, which decodes them as ``compile`` does, the route by
    which the importer compiles a module (``test_parsing_the_bytes_decodes_as_the_importer_does``).
    A listed file that does not parse raises ``SyntaxError`` naming it.
    """
    found: dict[str, list[tuple[int, str]]] = {}
    for name in _tracked_sources(root):
        hits = _old_producer_calls((root / name).read_bytes(), name)
        if hits:
            found[name] = hits
    return found


# --- The decoding premise, proved before it is relied on (R13) ---------------------------

# Round 4 F1's three modules, a BOM file, a coding-line file, and three files both routes reject.
_ENCODING_CASES: dict[str, tuple[bytes, str]] = {
    "cr_only_unknown_coding_line_3": (
        b"# one\r# two\r# -*- coding: bogus -*-\rMARKERS = ('emit_event', 'red_alert')\r", "ok"),
    "latin1_cookie_with_non_ascii_comment": (b"# -*- coding: latin-1 -*- caf\xe9\nLABEL = 'caf\xe9'\n", "ok"),
    "latin1_non_ascii_line_1_cookie_line_2": (b"# caf\xe9\n# -*- coding: latin-1 -*-\nLABEL = 'caf\xe9'\n", "ok"),
    "utf8_bom": (b"\xef\xbb\xbfMARKERS = ('emit_event', 'red_alert')\n", "ok"),
    "pep263_cp1252": (b"# -*- coding: cp1252 -*-\nLABEL = '\x80'\n", "ok"),
    "undeclared_non_utf8": (b"LABEL = 'caf\xe9'\n", "SyntaxError"),
    "unknown_coding_line_1": (b"# -*- coding: bogus -*-\nLABEL = 1\n", "SyntaxError"),
    "broken_syntax": (b"def (:\n", "SyntaxError"),
}


def _outcome(run: Callable[[], object]) -> str:
    try:
        run()
    except SyntaxError:
        return "SyntaxError"
    return "ok"


def _import(path: Path) -> None:
    """Load ``path`` through the importer's source loader, as ``import`` would, and run it."""
    spec = importlib.util.spec_from_file_location(f"_ad1270_encoding_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(importlib.util.module_from_spec(spec))


@pytest.mark.parametrize("case", sorted(_ENCODING_CASES))
def test_parsing_the_bytes_decodes_as_the_importer_does(tmp_path: Path, case: str) -> None:
    """R13: ``ast.parse`` of a file's bytes accepts and rejects what the importer does, on each case."""
    data, expected = _ENCODING_CASES[case]
    path = tmp_path / f"{case}.py"
    path.write_bytes(data)
    assert (_outcome(lambda: _import(path)), _outcome(lambda: ast.parse(data))) == (expected, expected)


@pytest.mark.parametrize(
    ("case", "read", "error"),
    [
        ("cr_only_unknown_coding_line_3", "tokenize.open", SyntaxError),
        ("latin1_cookie_with_non_ascii_comment", "tokenize.open", SyntaxError),
        ("latin1_non_ascii_line_1_cookie_line_2", "tokenize.open", SyntaxError),
        ("latin1_cookie_with_non_ascii_comment", "utf-8", UnicodeDecodeError),
        ("latin1_non_ascii_line_1_cookie_line_2", "utf-8", UnicodeDecodeError),
    ],
    ids=["cr-only-tokenize", "latin1-cookie-tokenize", "latin1-line-2-tokenize", "latin1-cookie-utf8",
         "latin1-line-2-utf8"],
)
def test_the_earlier_reads_reject_round_4s_modules(
    tmp_path: Path, case: str, read: str, error: type[Exception]
) -> None:
    """The negative control: A4's ``tokenize.open`` and round 1's UTF-8 read reject modules the importer runs."""
    path = tmp_path / f"{case}.py"
    path.write_bytes(_ENCODING_CASES[case][0])
    with pytest.raises(error):
        if read == "utf-8":
            path.read_text(encoding="utf-8")
        else:
            with tokenize.open(path) as handle:
                handle.read()


def test_a_module_level_return_parses_but_does_not_import(tmp_path: Path) -> None:
    """R13: the scan parses, it does not compile, so a file only full compilation rejects is read, not failed."""
    path = tmp_path / "module_level_return.py"
    path.write_bytes(b"return 1\n")
    assert _outcome(lambda: ast.parse(path.read_bytes())) == "ok"
    assert _outcome(lambda: _import(path)) == "SyntaxError"


# --- What the scan flags, ignores and does not resolve ---------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('rt.emit_event("red_alert", {})\n', [(1, "red_alert")]),
        ('rt.emit_event ("red_alert", {})\n', [(1, "red_alert")]),
        ('rt.emit_event(\n    "red_alert",\n    {},\n)\n', [(1, "red_alert")]),
        ('emit_event("trust_change", {})\n', [(1, "trust_change")]),
        ('self._emit_event("security_alert", {})\n', [(1, "security_alert")]),
        ('self._emit_event_fn("alert_condition_change", {})\n', [(1, "alert_condition_change")]),
        ('rt.\uff45mit_event("red_alert", {})\n', [(1, "red_alert")]),
        ('log(rt.emit_event("security_alert", {}))\n', [(1, "security_alert")]),
        ('log(rt.emit_event("security_alert", {}))\nrt.emit_event("red_alert", {})\n',
         [(1, "security_alert"), (2, "red_alert")]),
        ('rt.emit_event("red_" "alert", {})\n', [(1, "red_alert")]),
        ('rt.emit_event("red\\x5falert", {})\n', [(1, "red_alert")]),
        ('rt.emit_event(r"red_alert", {})\n', [(1, "red_alert")]),
        ('rt.emit_event("security_alert" + suffix, {})\n', [(1, "security_alert")]),
        ('rt.emit_event("red_alert" if bad else "build_failure", {})\n', [(1, "red_alert")]),
        ('rt.emit_event(rename("red_alert"), {})\n', [(1, "red_alert")]),
        ('rt.emit_event(f"red_alert", {})\n', [(1, "red_alert")]),
        ('rt.emit_event(*("security_alert", {}))\n', [(1, "security_alert")]),
        ('rt.emit_event(*[], "red_alert", {})\n', [(1, "red_alert")]),
        ('rt.emit_event(*(*["trust_change"], {}))\n', [(1, "trust_change")]),
        ('rt._emit_event_local({"type": "red_alert", "data": {}}, "red_alert")\n', [(1, "red_alert")]),
        ('svc.set_alert_condition("RED")\n', [(1, "set_alert_condition")]),
        ('svc.set_alert_condition ("RED")\n', [(1, "set_alert_condition")]),
        ('set_alert_condition("RED")\n', [(1, "set_alert_condition")]),
        (b'\xef\xbb\xbfrt.emit_event("red_alert", {})\n', [(1, "red_alert")]),
    ],
    ids=["positional", "space-before-paren", "split-lines", "bare-name", "private-callee", "suffixed-callee",
         "normalised-callee", "nested", "two-calls", "split-literal", "escaped", "raw-literal", "concatenated",
         "conditional", "contained-in-call", "f-string-no-placeholder", "unpacked-display", "empty-unpacking-first",
         "nested-unpacking", "local-dispatch", "set-alert", "set-alert-space", "set-alert-bare", "bytes-with-bom"],
)
def test_old_producer_calls_flags_a_literal_producer(source: str | bytes, expected: list[tuple[int, str]]) -> None:
    """A call whose event argument names an old event is found. ``contained-in-call`` and ``local-dispatch``
    are flagged though neither need produce one (register 1b-R2)."""
    assert _old_producer_calls(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        '# e.g. rt.emit_event("red_alert", {})\nx = 1\n',
        '"""Page with rt.emit_event("red_alert", {}) or svc.set_alert_condition("RED")."""\n',
        'rt.emit_event("red_alert_resolved", {})\n',
        'rt.emit_event("trust_change_summary", {})\n',
        'rt.emit_event("build_failure", {})\nrt.publish("red_alert", {})\n',
        'xemit_event("security_alert", {})\n',
        'rt.emit_event("build_failure", "red_alert")\n',
        'rt.emit_event("build_failure", data="red_alert")\n',
        'self._emit_event("build_failure", event_type="red_alert")\n',
        'self._emit_event(name="build_failure", event_type="red_alert")\n',
        'rt.emit_event(*("build_failure", {"note": "red_alert"}))\n',
        'rt.emit_event(b"red_alert", {})\n',
        'rt.emit_event("\uff52ed_alert", {})\n',
        'def set_alert_condition(self, condition):\n    pass\n',
        'def emit_event(self, event="red_alert"):\n    pass\n',
        'handler = svc.set_alert_condition\n',
        'rt.emit_event()\n',
    ],
    ids=["comment", "docstring", "longer-name", "longer-name-trust", "other-callee", "prefixed-callee",
         "second-positional", "other-keyword", "payload-event-type", "payload-keyword-bound", "unpacked-payload",
         "bytes-literal", "lookalike-string", "definition-only", "default-argument", "reference-only",
         "no-arguments"],
)
def test_old_producer_calls_ignores_what_is_not_a_producer(source: str) -> None:
    """Text that only mentions a producer, a longer or look-alike name, or an old name outside the event
    argument is not flagged (round 1's false matches; round 3 G1)."""
    assert _old_producer_calls(source) == []


@pytest.mark.parametrize(
    "source",
    [
        'fire = rt.emit_event\nfire("red_alert", {})\n',
        'getattr(rt, "emit_event")("red_alert", {})\n',
        'getattr(svc, "set_alert_condition")("RED")\n',
        'handlers["emit_event"]("red_alert", {})\n',
        'name = "red_alert"\nrt.emit_event(name, {})\n',
        'kind = "alert"\nrt.emit_event(f"red_{kind}", {})\n',
        'rt.emit_event("red_alert_"[:-1], {})\n',
        'rt._emit_event(event_type="trust_change", data={})\n',
        'rt.emit_event(event="security_alert")\n',
        'self._emit_event(name="alert_condition_change", payload={})\n',
        'args = ("red_alert", {})\nrt.emit_event(*args)\n',
        'rt.emit_event(**{"event": "red_alert"})\n',
    ],
    ids=["alias", "getattr", "getattr-setter", "subscript-callee", "variable", "f-string-placeholder", "computed",
         "event-type-kw", "event-kw", "name-kw", "unpacked-variable", "unpacked-mapping"],
)
def test_old_producer_calls_does_not_resolve_these_forms(source: str) -> None:
    """Register 1b-R1 on #1324: producers the scan does not resolve. If one starts to match, update 1b-R1
    and DECISIONS."""
    assert _old_producer_calls(source) == []


@pytest.mark.parametrize("source", ['rt.emit_event("red_alert", {}\n', "def (:\n"], ids=["unclosed-producer", "unrelated"])
def test_a_source_that_does_not_parse_raises(source: str) -> None:
    """Every source is parsed (no text prefilter), so one that does not parse fails instead of being skipped."""
    with pytest.raises(SyntaxError):
        _old_producer_calls(source)


# --- T2's own file list and scan, over a temporary git repository ------------------------


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", *args],
        cwd=root, check=True, capture_output=True,
    )


def _repo(tmp_path: Path, tracked: dict[str, bytes], untracked: dict[str, bytes] | None = None) -> Path:
    """A git repository whose ``tracked`` files are in the index (``git ls-files`` lists the index)."""
    root = tmp_path / "src"
    root.mkdir()
    _git(root, "init", "-q")
    for name, data in {**tracked, **(untracked or {})}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    _git(root, "add", "--", *tracked)
    return root


_TRACKED = {
    "clean.py": b"X = 1\n",
    "pkg/__init__.py": b"",
    "pkg/comment_only.py": b'# rt.emit_event("red_alert", {})\n# svc.set_alert_condition("RED")\nX = 1\n',
    "pkg/bom_markers.py": _ENCODING_CASES["utf8_bom"][0],
    "pkg/cr_only.py": _ENCODING_CASES["cr_only_unknown_coding_line_3"][0],
    "pkg/latin1_cookie.py": _ENCODING_CASES["latin1_cookie_with_non_ascii_comment"][0],
    "pkg/latin1_line_2.py": _ENCODING_CASES["latin1_non_ascii_line_1_cookie_line_2"][0],
    "pkg/pep263.py": _ENCODING_CASES["pep263_cp1252"][0],
    "pkg/producer.py": b'\xef\xbb\xbfrt.emit_event("red_alert", {})\n',
}


def test_the_scan_lists_the_tracked_files_and_finds_only_the_tracked_producer(tmp_path: Path) -> None:
    """Round 3 G5: T2's own list and scan. Round 4 F1's modules, a BOM file and a comment-only module (round 5
    F1) pass; the tracked producer is found and the untracked one is not read."""
    root = _repo(tmp_path, _TRACKED, {"pkg/untracked_producer.py": b'rt.emit_event("security_alert", {})\n'})
    assert sorted(_tracked_sources(root)) == sorted(_TRACKED)
    assert _scan(root) == {"pkg/producer.py": [(1, "red_alert")]}


@pytest.mark.parametrize("case", ["broken_syntax", "undeclared_non_utf8", "unknown_coding_line_1"])
def test_the_scan_fails_on_a_tracked_file_that_does_not_parse(tmp_path: Path, case: str) -> None:
    """A tracked file that does not parse fails the scan, and the error names it."""
    root = _repo(tmp_path, {"clean.py": b"X = 1\n", "bad.py": _ENCODING_CASES[case][0]})
    with pytest.raises(SyntaxError) as raised:
        _scan(root)
    assert raised.value.filename == "bad.py"


@pytest.mark.parametrize("repository", [True, False], ids=["no-tracked-python", "not-a-repository"])
def test_the_file_list_fails_when_git_lists_no_python_file(tmp_path: Path, repository: bool) -> None:
    """The guard's premise: a list git cannot give, or an empty one, fails instead of passing."""
    if repository:
        root = _repo(tmp_path, {"notes.txt": b"x\n"}, {"untracked.py": b"X = 1\n"})
    else:
        root = tmp_path / "plain"
        root.mkdir()
        (root / "untracked.py").write_bytes(b"X = 1\n")
    with pytest.raises(AssertionError):
        _tracked_sources(root)


# --- T2 ----------------------------------------------------------------------------------


def test_the_inert_triggers_still_have_no_producer() -> None:
    """T2: no ``EventType`` member has an old name, and no tracked ``src/probos`` file holds a call the scan
    flags. If it finds one, map the producer in ``NIGHT_ORDER_TRIGGER_EVENTS`` if it is one; register 1b-R2
    on #1324 lists known forms the scan flags that need not produce an event."""
    assert {m.value for m in EventType}.isdisjoint(_OLD_EVENT_NAMES)
    assert {"runtime.py", "watch_rotation.py", "routers/build.py"} <= set(_tracked_sources(_SRC))
    found = _scan(_SRC)
    assert found == {}, f"calls that may produce an inert Night Orders trigger (file: [(line, name)]): {found}"
