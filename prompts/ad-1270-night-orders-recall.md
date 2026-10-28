# AD-1270 (#1324) Night Orders slice 1b: T2 finds a producer of an inert trigger by parsing each tracked file

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-28

**Status:** build-ready. Drafted on `8cb4bad5` (tree `1e8bcaea`, slice 4c's candidate head). Builds after slice 5 merges, alone (the Architect's Decision 3). No new AD or BF number: this is slice 1b of #1324's Night Orders item (register R13). **Captain:** nothing parked.

**Precedence.** This contract supersedes the drafted text R13 names: A3 and A4 (`698950a9`, `6cc1a1a3`), §7.9 and §7.10, the §10 H rows, §14 items 16 to 23, and "R11 as drafted" in `prompts/ad-1270-night-orders-escalation.md`. Where a later amendment to this contract differs from earlier text here, the later amendment wins.

**Anchors.** Three pairs (P1 to P3) edit `tests/test_ad1270_night_orders_triggers.py`; three (U1, U2a, U2b) edit the trackers; there is one new file (§7.1.N). The working copies on the Captain's host are CRLF (`git ls-files --eol`: `i/lf w/crlf` for all three edited files). The pairs are written LF; apply them line-ending-agnostically, as for earlier contracts. No pair's SEARCH text is in a file slice 5 is known to edit. U1 anchors on the `# ProbOS Progress` header line, which an insertion above an existing entry leaves in place. The oracle's dry run on the post-slice-5 tree confirms each SEARCH occurs exactly once.

**Which text describes the head.** These are records of the tree they were written on (`8cb4bad5`): the Status and Anchors paragraphs, §1, §3, §5's site lists, §7's pairs, §10, §11 (every Verified, Absence and Not verified block) and §13. The text that describes the candidate's head, names no commit, and gives counts only where a named command or gate measures them is: the Milestones and Tests lists, §2, §4, §6's columns, §8's texts, §9, §12, §14, §15, the register, and every docstring and comment in §7.1.N.

**Milestones:**
- **M1 (STANDARD, test-only):** the new file, plus P1 to P3 (T2 moves out of the triggers file).
- **M2 (docs):** U1, U2a and U2b, plus the regenerated ledger files.

Each milestone is one Builder delegation and one local commit, staged by explicit path. One cross-family review (`gpt-6.1-sol`) of M1 and M2 against §14. One mutation campaign of record on the M1 tree (§10). The broad gate runs once, after M2:

`d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad1270-night-orders-recall --receipt logs/gates/ad1270-night-orders-recall.receipt.json`

**Tests:**
- New: `tests/test_ad1270_night_orders_recall.py`, 76 cases, as `pytest <file> -n 0` reports.
- Updated: `tests/test_ad1270_night_orders_triggers.py` loses T2, going from 38 cases to 37 (no case in it is renamed or loosened).

## 1. Problem

- T2 (`tests/test_ad1270_night_orders_triggers.py:59-64`) matches text over `_SRC.rglob("*.py")`, reading each file as UTF-8. The weaknesses are listed in register R11:
  - It sees `security_alert` emissions only.
  - It fails on a comment, a docstring, a longer name or `xemit_event(`.
  - It raises `UnicodeDecodeError` on a valid Latin-1 module.
  - It reads untracked files.
  - It misses whitespace before the parenthesis, bare and whitespace forms of `set_alert_condition`, and keywords, `*` and `**`.
- The parser drafts (A3, A4) fixed some of these but failed review:
  - Round 3: G1 (payload keywords read as the event), G2 (a BOM file), G3 and G4 (recall that depended on a text prefilter), and G5 (matcher branches and T2's own wiring with no fixture).
  - Round 4: F1 (A4's `tokenize.open` rejects a CR-only module, and two Latin-1 modules, that the importer runs) and F2 (positional unpacking).
  - Round 5: F1 (the docstring "If this fails, a producer exists now" was false; it has since been deleted).

## 2. Solution

T2 moves to `tests/test_ad1270_night_orders_recall.py`. It parses, from the bytes, every Python file git tracks under `<repo>/src/probos`, with no prefilter. It flags two kinds of call:
- a call whose callee, a name or an attribute, is `set_alert_condition`;
- a call whose callee, with leading underscores stripped, starts with `emit_event`, and whose event argument contains an old event name as a string constant. The event argument is the first positional argument, after any `*` over a tuple or list display has been opened.

Keywords are never read. A tracked file that does not parse raises `SyntaxError` naming it, and an empty or unanswerable file list fails.

The fixtures pin what the scan flags, what it ignores and what it does not resolve. Eight decode cases compare `ast.parse(bytes)` with the importer. Tests on a temporary git repository run T2's own file list and scan.

## 3. Decisions

- **D1.** The scanner and T2 live in the new test file, not in a helper module or a script (the Architect's Decision 1).
- **D2.** The file list is `_tracked_python_files` on `<repo>/src/probos`, rooted at the test file's location. `None` and `[]` both fail (Decision 2). Calling the checker's private function is deliberate: R13 names it, the checker's own tests call it, and its public wrapper falls back to walking the disk.
- **D3.** No prefilter. The orchestrator measured the cost of parsing every file and needs none.
- **D4.** The event argument is matched by containment: any string constant inside it equal to an old name. Two consequences:
  - It keeps round 1's recall for `"security_alert" + x`, conditional expressions and f-strings without placeholders.
  - It fails, without a producer, on `rename("red_alert")` and on `_emit_event_local({...})` (1b-R2). That is the safe direction.
- **D5.** The checker is registered in `sys.modules` under a private name (`_ad1270_recall_architecture_checker`). The new file never replaces the `check_architecture_principles` module that `test_ad1270b_architecture_fitness.py:61` registers.

## 4. Milestones

**M1 build order:**
1. Write §7.1.N.
2. Run the premise probes: `d:/ProbOS/.venv/Scripts/pytest.exe -n 0 tests/test_ad1270_night_orders_recall.py -k "decodes_as_the_importer or earlier_reads or module_level_return"`. Predicted: 14 passed. Any other result is a stop: report the outcome table to the Architect.
3. Run the whole new file. Predicted: 76 passed.
4. Apply P1 to P3. Run the triggers file. Predicted: 37 passed.
5. Run the focused gate. Commit.

**M2 build order:**
1. Apply U1, U2a and U2b.
2. Run `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py`. Stage `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`.
3. Run the focused gate. Commit.

| M | Tier | Sections | Focused gate (`d:/ProbOS/.venv/Scripts/pytest.exe -n 0 …`) |
|---|---|---|---|
| **M1** | STANDARD | 7.1 | `tests/test_ad1270_night_orders_recall.py tests/test_ad1270_night_orders_triggers.py tests/test_ad1270_night_orders_delivery.py tests/test_ad1270b_architecture_fitness.py`; then the same in one process in reverse order, `tests/test_ad1270b_architecture_fitness.py tests/test_ad1270_night_orders_recall.py`; then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_architecture_principles.py --check` |
| **M2** | docs | 7.2, §8 | `tests/test_ad1184_ad_ledger.py`; `-P scripts/gen_ad_ledger.py --check`. AD-1270 must still resolve `shipped` |

## 5. Consumers

- **T2's verdict:** consumed by pytest discovery in CI (`.github/workflows/ci.yml:71`) and by the broad gate (`scripts/run_test_gate.py`).
- **`scripts/check_architecture_principles.py`:** loaded read-only, under a private module name. Its behaviour, baseline and other callers are unchanged.
- **`tests/test_ad1270_night_orders_triggers.py`:**
  - T1 keeps `_SRC`, `_source`, `Path`, `probos` and `EventType`.
  - `re` is used only by T2 (Grep: `:10`, `:63`, `:64`), so it goes.
- **No production consumer:** no file under `src/` changes.

## 6. Tests

| Test (new file) | Cases | Pins |
|---|---|---|
| `test_old_producer_calls_flags_a_literal_producer` | 24 | All four names. The callee as a bare name, private, with a suffix, or normalised. Split, escaped and raw literals. Concatenation, a conditional, containment in a call, an f-string with no placeholder. Opened unpacking (F2), an empty unpacking first, nested unpacking. `_emit_event_local`. Three setter forms. Bytes with a BOM |
| `test_old_producer_calls_ignores_what_is_not_a_producer` | 17 | Round 1's false matches. G1's payload keywords. Unpacked payload. Bytes and look-alike literals. Definitions, a reference, no arguments |
| `test_old_producer_calls_does_not_resolve_these_forms` | 12 | 1b-R1 |
| `test_a_source_that_does_not_parse_raises` | 2 | No prefilter |
| `test_parsing_the_bytes_decodes_as_the_importer_does` | 8 | The importer and `ast.parse` agree. Expected: five `ok`, three `SyntaxError` |
| `test_the_earlier_reads_reject_round_4s_modules` | 5 | Negative control: `tokenize.open` (A4) on F1's three modules; a UTF-8 read (round 1) on the two Latin-1 modules |
| `test_a_module_level_return_parses_but_does_not_import` | 1 | Parsing is not full compilation |
| `test_the_scan_lists_the_tracked_files_and_finds_only_the_tracked_producer` | 1 | G5: T2's own list and scan; F1's modules, BOM and comment-only modules pass; an untracked producer is not read |
| `test_the_scan_fails_on_a_tracked_file_that_does_not_parse` | 3 | `SyntaxError` naming `bad.py` |
| `test_the_file_list_fails_when_git_lists_no_python_file` | 2 | The guard's premise |
| `test_the_inert_triggers_still_have_no_producer` (T2) | 1 | The real tree |

## 7. The contract

### 7.1 M1

**Pair P1 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
import math
import re
from io import StringIO
```
REPLACE:
```
import math
from io import StringIO
```

**Pair P2 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
# --- T1, T2: the map names producers, and only producers ---------------------
```
REPLACE:
```
# --- T1: the map names producers (T2 is in test_ad1270_night_orders_recall.py) --------
```

**Pair P3 (`tests/test_ad1270_night_orders_triggers.py`).** SEARCH:
```
def test_the_inert_triggers_still_have_no_producer() -> None:
    values = {m.value for m in EventType}
    assert values.isdisjoint({"trust_change", "alert_condition_change", "security_alert", "red_alert"})
    texts = {p.relative_to(_SRC).as_posix(): p.read_text(encoding="utf-8") for p in _SRC.rglob("*.py")}
    assert [p for p, t in texts.items() if re.search(r"\.set_alert_condition\(", t)] == []
    assert [p for p, t in texts.items() if re.search(r"""emit_event\w*\(\s*["']security_alert""", t)] == []


def test_every_template_trigger_is_wired_or_known_inert() -> None:
```
REPLACE:
```
def test_every_template_trigger_is_wired_or_known_inert() -> None:
```

#### 7.1.N New file: `tests/test_ad1270_night_orders_recall.py`

```python
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
```

### 7.2 M2: trackers (pairs in §8), then `scripts/gen_ad_ledger.py`

## 8. Tracking (M2's commit)

**Head constraint:** neither new head has a lifecycle keyword (`retired|abandoned|withdrawn|superseded|deferred|postponed|closed|shipped|staged|landed|open`) in its first 120 characters (`gen_ad_ledger.py:126-139,176-184`). Fill in `2026-10-2X` with the landing date.

**Pair U1 (`PROGRESS.md`).** SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**AD-1270 (2026-10-2X), #1324 Night Orders slice 1b -- T2 finds a producer of an inert trigger by parsing.** T2, the guard that `red_alert`, `security_alert`, `trust_change` and `alert_condition_change` have no producer, matched source text: a comment or a longer name failed it, a valid module that is not UTF-8 failed it, and it saw emissions of `security_alert` only. It now parses every Python file git tracks under `src/probos`, from the file's bytes, and fails on a `set_alert_condition` call or on an `emit_event*` call whose event argument contains an old name as a string constant; a tracked file that does not parse, or an empty file list, fails it too. The forms it does not resolve, and the forms that fail it without being a producer, are #1324 register 1b-R1 and 1b-R2. No production change. New: `tests/test_ad1270_night_orders_recall.py`, to which T2 moved from `tests/test_ad1270_night_orders_triggers.py`. The contract is `prompts/ad-1270-night-orders-recall.md`.

```

**Pair U2a (`DECISIONS.md`; the SEARCH is a substring of one line).** SEARCH:
```
A guard test (T2) fails if an `EventType` value is one of the four old names (`trust_change`, `alert_condition_change`, `security_alert`, `red_alert`), or if the text of any `*.py` file under the `probos` package directory matches `\.set_alert_condition\(` or `emit_event\w*\(\s*["']security_alert`. It matches text, not calls, so it misses some producers and can fail on text that is not one; its limits are #1324 register R11, and it is a backstop, not a guarantee.
```
REPLACE:
```
A guard test (T2) fails if an `EventType` value is one of the four old names (`trust_change`, `alert_condition_change`, `security_alert`, `red_alert`), or if it finds a call that may produce one. Since slice 1b it finds calls by parsing each tracked file (the AD-1270 slice 1b entry); its limits are #1324 register 1b-R1 and 1b-R2, and it is a backstop, not a guarantee.
```

**Pair U2b (`DECISIONS.md`).** SEARCH:
```
### AD-1270 (#1324) -- the dormant-class check: value uses with in-module reachability, a disposition-only baseline, report-only (2026-10-27)
```
REPLACE:
```
### AD-1270 (#1324) -- Night Orders slice 1b: T2 finds a producer of an inert trigger by parsing each tracked file (2026-10-2X)

**Decision.** T2 (`test_the_inert_triggers_still_have_no_producer`, now in `tests/test_ad1270_night_orders_recall.py`) parses every Python file git tracks under `src/probos`, from the file's bytes, with no text prefilter. It fails on a call whose callee, a name or an attribute, is `set_alert_condition`, and on a call whose callee, leading underscores stripped, starts with `emit_event` and whose event argument contains `trust_change`, `alert_condition_change`, `security_alert` or `red_alert` as a string constant. The event argument is the first positional argument, after any `*` over a tuple or list display is opened; keywords are never read. A listed file that does not parse fails T2 with its name, and so does a file list git cannot give or that is empty. **Why.** Round 1's T2 matched text: a comment or a longer name failed it, a valid module that is not UTF-8 failed it, and it saw emissions of `security_alert` only. Parsing every file makes recall independent of a prefilter (round 3 G3, G4). `ast.parse` of the bytes decodes them as `compile` does, the route by which the importer runs a module; a test runs the importer and the parse on round 4's three modules, a BOM file, a coding-line file and three files both reject, and another shows that A4's `tokenize.open` and round 1's UTF-8 read reject round 4's modules (round 4 F1). Keywords can be a forwarder's payload (round 3 G1). The file list is `git ls-files`, the list the gate's materialised checkout has. **Effect.** No production change. T2 no longer fails on a mention in a comment, docstring or string, on a longer or look-alike name, or on a valid module's encoding, and it sees all four names. It does not resolve an emitter under another name, a call through `getattr` or a subscript, an event passed by keyword, through `**` or through `*` over a non-display, a name held in a variable or computed from another literal, or a producer outside `src/probos`. It fails without a producer on an event argument that contains an old name but evaluates to another, and on an `_emit_event_local` call whose event dict names one (that call bypasses the Night Orders hook). An untracked file is not read. A file that only full compilation rejects (a module-level `return`) is parsed, not failed. These are #1324 register 1b-R1 and 1b-R2. **Rejected.** A text prefilter (parsing every tracked file needs none on cost, by the orchestrator's measurement); `tokenize.open` (round 4 F1); a UTF-8 read, with or without `-sig` (round 3 G2; round 4's Latin-1 modules); the checker's `iter_modules` (it skips files it cannot decode or parse); a `scripts/` check with its own gate seam (a second home for one guard).

### AD-1270 (#1324) -- the dormant-class check: value uses with in-module reachability, a disposition-only baseline, report-only (2026-10-27)
```

**Claim → probe (U1, U2a, U2b):**

| Claim | Probe (positive / negative) |
|---|---|
| comment, docstring, longer name, look-alike name pass | `ignores[comment, docstring, longer-name, longer-name-trust, lookalike-string]`; round 1's regexes flag `docstring` and `prefixed-callee` (§10's discrimination prediction) |
| all four names are seen | `flags[positional]` (red), `[private-callee]` (security), `[bare-name]` (trust), `[suffixed-callee]` (alert_condition) |
| first positional; `*` display opened; keywords never read | `flags[unpacked-display, empty-unpacking-first, nested-unpacking]` / `ignores[payload-event-type, payload-keyword-bound, unpacked-payload]`, `unresolved[event-kw, name-kw, event-type-kw, unpacked-mapping, unpacked-variable]` |
| containment of a string constant | `flags[concatenated, conditional, contained-in-call, f-string-no-placeholder]` / `unresolved[computed, f-string-placeholder, variable]` |
| no prefilter; a file that does not parse fails with its name | `test_a_source_that_does_not_parse_raises[unrelated]`, `flags[normalised-callee, split-literal, escaped]`; `test_the_scan_fails_on_a_tracked_file_that_does_not_parse` (×3) |
| decodes like the importer; earlier reads reject F1 | `test_parsing_the_bytes_decodes_as_the_importer_does` (5 ok, 3 SyntaxError) / `test_the_earlier_reads_reject_round_4s_modules` (×5) |
| a valid module's encoding no longer fails T2; untracked not read | `test_the_scan_lists_the_tracked_files_and_finds_only_the_tracked_producer` |
| empty or unanswerable list fails | `test_the_file_list_fails_when_git_lists_no_python_file` (×2) |
| fails without a producer on `rename(...)`, `_emit_event_local` | `flags[contained-in-call, local-dispatch]` |
| module-level `return` parsed, not failed | `test_a_module_level_return_parses_but_does_not_import` |
| emitter alias, `getattr`, subscript not resolved | `unresolved[alias, getattr, getattr-setter, subscript-callee]` |

Parent checklist (the orchestrator, on #1324): tick the slice-1b sub-item under the Night Orders entry, with the commits and the receipt.

## 9. What this does NOT change

- Anything under `src/`: `NIGHT_ORDER_TRIGGER_EVENTS`, `night_order_trigger`, status, the console, `_emit_event` and its hook.
- `scripts/check_architecture_principles.py` and its baseline (loaded, never edited). The other two `_tracked_python_files` copies (`check_store_registry.py`, `check_seam_contracts.py`).
- `tests/test_ad1270_night_orders_triggers.py` beyond P1 to P3: T1, T3 to T5 and the template test keep their bodies. `tests/test_ad1270_night_orders_delivery.py`.
- Other source-scan guards (`tests/test_bf925_guard_names.py`, 1b-R3). Slice 2's dormant-class check. R12 (the console TTL; a BF is recommended separately).

## 10. Mutation rows (one campaign of record on the M1 tree; baseline `tests/test_ad1270_night_orders_recall.py` = 76 passed; run with `--tests tests/test_ad1270_night_orders_recall.py`)

**Grammar.** This follows slice 4c's §10:
- **Line:** the exact text of one line of the target file, without its indentation. Each Line occurs once in the file; "same" repeats the row above.
- **Mutate to:** replaces that text, keeping the line's indentation. A `\n` begins a new line written with its own indentation.
- **Killed:** a row is killed when at least one test in its Killed-by cell fails or errors with the mutant applied.
- **Expected:** no row is equivalent, and all 20 are predicted killed.
- **Not rows:** T2's three assertions and its premise line survive any weakening on a producer-free tree, by construction. They have no fixture killer; the scan they call is pinned by the temporary-repository tests.

All rows target `tests/test_ad1270_night_orders_recall.py` (M1).

| # | M | File | Line | Mutate to | Killed by |
|---|---|---|---|---|---|
| N-1 | M1 | recall | `_OLD_EVENT_NAMES = frozenset({"trust_change", "alert_condition_change", "security_alert", "red_alert"})` | `_OLD_EVENT_NAMES = frozenset({"security_alert", "red_alert"})` | `test_old_producer_calls_flags_a_literal_producer[bare-name]`, `[suffixed-callee]`, `[nested-unpacking]` |
| N-2 | M1 | recall | `callee = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""` | `callee = func.attr if isinstance(func, ast.Attribute) else ""` | `test_old_producer_calls_flags_a_literal_producer[bare-name]`, `[set-alert-bare]` |
| N-3 | M1 | recall | `if callee == "set_alert_condition":` | `if False:` | `test_old_producer_calls_flags_a_literal_producer[set-alert]`, `[set-alert-space]`, `[set-alert-bare]` |
| N-4 | M1 | recall | `if not callee.lstrip("_").startswith("emit_event"):` | `if callee.lstrip("_") != "emit_event":` | `test_old_producer_calls_flags_a_literal_producer[suffixed-callee]`, `[local-dispatch]` |
| N-5 | M1 | recall | same | `if not callee.startswith("emit_event"):` | `test_old_producer_calls_flags_a_literal_producer[private-callee]`, `[suffixed-callee]`, `[local-dispatch]` |
| N-6 | M1 | recall | `pending = list(call.args)` | `pending = list(call.args[:1])` | `test_old_producer_calls_flags_a_literal_producer[empty-unpacking-first]` |
| N-7 | M1 | recall | `if isinstance(arg, ast.Starred) and isinstance(arg.value, (ast.Tuple, ast.List)):` | `if False:` | `test_old_producer_calls_flags_a_literal_producer[empty-unpacking-first]`, `test_old_producer_calls_ignores_what_is_not_a_producer[unpacked-payload]` |
| N-8 | M1 | recall | `pending[:0] = arg.value.elts` | `pass` | `test_old_producer_calls_flags_a_literal_producer[unpacked-display]`, `[nested-unpacking]` |
| N-9 | M1 | recall | `if event is None:` | `if False:` | `test_old_producer_calls_ignores_what_is_not_a_producer[payload-keyword-bound]`, `[no-arguments]`, `test_old_producer_calls_does_not_resolve_these_forms[event-type-kw]`, `[event-kw]`, `[name-kw]`, `[unpacked-mapping]` (each by `AttributeError`) |
| N-10 | M1 | recall | `for part in ast.walk(event):` | `for part in (event,):` | `test_old_producer_calls_flags_a_literal_producer[concatenated]`, `[conditional]`, `[contained-in-call]`, `[f-string-no-placeholder]` |
| N-11 | M1 | recall | `if isinstance(part, ast.Constant) and part.value in _OLD_EVENT_NAMES:` | `if isinstance(part, ast.Constant) and isinstance(part.value, str) and part.value.startswith(tuple(_OLD_EVENT_NAMES)):` | `test_old_producer_calls_ignores_what_is_not_a_producer[longer-name]`, `[longer-name-trust]` |
| N-12 | M1 | recall | `for node in ast.walk(ast.parse(source, filename=filename)):` | `for node in (ast.walk(ast.parse(source, filename=filename)) if any(m in (source if isinstance(source, bytes) else source.encode()) for m in (b"emit_event", b"set_alert_condition")) else ()):` | `test_old_producer_calls_flags_a_literal_producer[normalised-callee]`, `test_a_source_that_does_not_parse_raises[unrelated]` |
| N-13 | M1 | recall | `return sorted(hits)` | `return hits` | `test_old_producer_calls_flags_a_literal_producer[two-calls]` |
| N-14 | M1 | recall | `hits = _old_producer_calls((root / name).read_bytes(), name)` | `hits = _old_producer_calls(tokenize.open(root / name).read(), name)` | `test_the_scan_lists_the_tracked_files_and_finds_only_the_tracked_producer` |
| N-15 | M1 | recall | same | `hits = _old_producer_calls((root / name).read_text(encoding="utf-8"), name)` | `test_the_scan_lists_the_tracked_files_and_finds_only_the_tracked_producer` |
| N-16 | M1 | recall | same | `hits = _old_producer_calls((root / name).read_bytes())` | `test_the_scan_fails_on_a_tracked_file_that_does_not_parse[broken_syntax]`, `[undeclared_non_utf8]`, `[unknown_coding_line_1]` |
| N-17 | M1 | recall | `for name in _tracked_sources(root):` | `for name in sorted(p.relative_to(root).as_posix() for p in root.rglob("*.py")):` | `test_the_scan_lists_the_tracked_files_and_finds_only_the_tracked_producer` |
| N-18 | M1 | recall | `names = _checker()._tracked_python_files(root)` | `names = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.py"))` | `test_the_scan_lists_the_tracked_files_and_finds_only_the_tracked_producer`, `test_the_file_list_fails_when_git_lists_no_python_file[no-tracked-python]`, `[not-a-repository]` |
| N-19 | M1 | recall | `assert names, f"git listed no tracked Python file under {root} (not a git checkout, or none tracked)"` | `pass` | `test_the_file_list_fails_when_git_lists_no_python_file[no-tracked-python]`, `[not-a-repository]` |
| N-20 | M1 | recall | `if hits:` | `if True:` | `test_the_scan_lists_the_tracked_files_and_finds_only_the_tracked_producer`, `test_the_inert_triggers_still_have_no_producer` |

**What the rows map to.** G5's two mutants are N-2 (attribute-only) and N-4 (exact name). The prefilter is N-12 (G3, G4). A4's read is N-14 and round 1's read is N-15 (F1, G2). Payload-as-event (G1) is guarded by N-7 and the `ignores` payload cases. The disk walk is N-17 and N-18.

## 11. Verified Against Codebase (2026-10-28, on `8cb4bad5`)

```
git log -1 --format="%H %T %s"   -> 8cb4bad53f3f… 1e8bcaeae83c… (slice 4c M4); git status --porcelain -> clean
git ls-files -- "src/probos/*.py" | wc -l   -> 1075
git ls-files --eol PROGRESS.md DECISIONS.md tests/test_ad1270_night_orders_triggers.py -> i/lf w/crlf (all three)
Read tests/test_ad1270_night_orders_triggers.py:1-76 -> import re :10; header :46; T1 :49-56; T2 :59-64; template :67
Grep "\bre\.|import re\b" triggers -> :10, :63, :64 only
Grep "^def |^@pytest" triggers + parametrize lists -> 38 cases (1+1+1+6+14+4+3+1+1+1+1+1+3)
Read scripts/check_architecture_principles.py:118-133 (git ls-files, AST only), :293-320 (_tracked_python_files: None on OSError or nonzero exit; "/" names), :348-363 (tracked_module_names: disk-walk fallback, warning only), :366-408 (iter_modules skips UnicodeDecodeError/OSError/SyntaxError; text_prefilter), :711-749 (source-text-tests: inspect.getsource, or read_text on a __file__ path; report-only, :168)
Grep check_architecture_principles.py top level -> imports :138-151 (yaml, dataclasses); __main__ guard :1275
Read tests/test_ad1270b_architecture_fitness.py:48-63 (load by path; sys.modules["check_architecture_principles"] for PEP 563 dataclasses); :71-102 (git init/add precedent)
Grep 'def _*emit_event\w*\(' src/probos -> 10: builder.py:1331 (self_, event_type, data), :1334; runtime.py:1930 (event_type, data), :1977 _emit_event_local(event dict, type_str), :2018 (event, data); pairing/service.py:74 (name, payload); protocols.py:244; evolution_store.py:1253 (name, **payload); approval_gate.py:169 (name, **payload); proposal.py:269 (name, proposal_id, action, **extra)
Read runtime.py:1930-2023 -> hook _check_night_order_escalation at :1949; _emit_event_local bypasses it (:1966, :1975)
Grep 'set_alert_condition\s*\(' src -> ontology/service.py:105 (def only)
Grep '["'](red_alert|security_alert|trust_change|alert_condition_change)["']' src -> 11 lines: conn.py:54,56,202; config_models/knowledge.py:310; workforce.py:804,822,840; watch_rotation.py:190,197,204; cognitive/importance_scorer.py:26 (list or dict displays; conn.py:196-205 read)
Read events.py:540-569 -> BaseEvent.event_type: EventType
grep -o DECISIONS.md:871 -> U2a's SEARCH text; Grep "A guard test \(T2\)" -> 1 in DECISIONS.md
Grep '^### AD-1270' DECISIONS.md -> :869 Night Orders, :880 dormant-class check (U2b), :900 Explicit delegation
Grep '# ProbOS Progress' PROGRESS.md -> 1
Read scripts/gen_ad_ledger.py:120-184 (status keywords; 120-character head window)
Grep run_test_gate.py -> :635 git worktree add --detach; :1093 probos.__file__ check
Read .github/workflows/ci.yml:40-74 (actions/checkout; uv sync; pytest tests/ -n auto); pyproject.toml requires-python >=3.12, addopts -n 16 --dist=loadfile, timeout 180
Grep scripts/ci_shards.py -> unknown files weigh their node count (:219, :261)
scripts/ad_ceiling.py -> CEILING AD-1354 (GitHub issue titles); no number allocated
```

## Absence Verified (2026-10-28)

```
CLAIM: no emit_event* call in src/probos binds its event by keyword, or opens its arguments with * or **
RUN:   Grep multiline 'emit_event\w*\s*\(\s*\w+\s*=[^=]' and 'emit_event\w*\s*\(\s*\*' over src/probos
FOUND: none; none
HOLDS: yes at the text level (the AST call count is the oracle's)

CLAIM: nothing in src calls set_alert_condition
RUN:   Grep 'set_alert_condition\s*\(' src
FOUND: ontology/service.py:105 (its def)
HOLDS: yes

CLAIM: no old-name string literal is an argument of an emit_event* call in src/probos (real-tree scan predicted {})
RUN:   the literal Grep above (11 lines), each line read
FOUND: list or dict entries only
HOLDS: yes

CLAIM: the new test file, the contract file and the checker's private module name do not exist yet
RUN:   Glob tests/test_ad1270*night*; Glob prompts/ad-1270*.md; Grep '_ad1270_recall' (excluding logs/)
FOUND: delivery and triggers test files only; no night-orders-recall prompt; none
HOLDS: yes

CLAIM: T2's name is defined once in tests, and only one test file registers check_architecture_principles in sys.modules
RUN:   Grep 'test_the_inert_triggers_still_have_no_producer' (excluding logs/ and prompts/); Grep 'sys.modules\["check_architecture_principles"\]' tests
FOUND: triggers.py:59; test_ad1270b_architecture_fitness.py:61
HOLDS: yes
```

## Not verified (the orchestrator verifies by running)

- **Every count:** 76 and 37 cases; the size of the file list on the post-slice-5 tree; all 20 kills.
- **The decode outcomes in §6,** especially: `cr_only_unknown_coding_line_3` and the two Latin-1 cases are `ok` under both routes; `unknown_coding_line_1` and `undeclared_non_utf8` raise `SyntaxError` under both. My fixtures are rebuilt from round 4's description; the reviewer's own evidence bytes are not in this worktree.
- **The error filename:** `SyntaxError.filename == "bad.py"` in all three cases of `test_the_scan_fails_on_a_tracked_file_that_does_not_parse`.
- **Standard-library details** (not readable from this worktree): `SourceLoader.source_to_code` compiles bytes, and `get_source` uses `tokenize.detect_encoding`. The decode test proves the behaviour on the eight cases.
- **Environment:** that `git init` and `git add` work under the gate's redirected home (the precedent is `test_ad1270b_architecture_fitness.py`), and T2's wall time on the gate host.
- **Anchors:** that slice 5's pairs leave every SEARCH here intact (slice 5's contract is not in this worktree).

## 12. Deterministic gate checks, resolved up front

- **`check_architecture_principles.py --check`:** passes with no row change. No `src` change. The new file has no `inspect.getsource` and no `read_text` on a `__file__` path, so the report-only `source-text-tests` category gains nothing.
- **`gen_ad_ledger.py --check`:** passes after regeneration, and AD-1270 stays `shipped` (predicted; M2 measures it).
- **Test collection:** one new test file and none deleted (`git diff --name-status --diff-filter=AD` over the slice, `-- tests`). The CI sharder weighs an unknown file by its node count.
- **`check_dormant_classes.py`:** not affected (no `src` change).

## 13. Prior Art and Blind Spots

- **Internal:**
  - `check_architecture_principles.py`'s rules ("AST only, never regex over source text"; "the file list comes from `git ls-files`"). Adopted.
  - `iter_modules` (it skips files it cannot read; it has a text prefilter). Rejected for a guard.
  - R13's design constraints. Followed.
  - `tests/test_bf925_guard_names.py:190` reads `rglob` with UTF-8, as round 1 did, and `_tracked_python_files` is defined three times. Considered, deferred (1b-R3).
- **External** (date used: 2026-10-28):
  - CPython's importer runs a module through `SourceLoader.get_code` → `source_to_code`, which compiles the bytes; `get_source` decodes with `tokenize.detect_encoding`. A4 followed the second route, which explains F1. Adopted the first route, proven by the decode test. Sources: [CPython importlib.abc mirror](https://chromium.googlesource.com/external/github.com/python/cpython/+/6da701511e70fb26ad4710153d8d5a82b809919c/Lib/importlib/abc.py), [PEP 263](https://peps.python.org/0263).
  - Semgrep's within-file constant propagation would resolve 1b-R1's `variable` form. Rejected: a new tool dependency for one guard. Considered, deferred. Source: [Semgrep constant propagation](https://semgrep.dev/docs/writing-rules/data-flow/constant-propagation).
  - `docs/research/reference-projects.md`: no listed project concerns static source guards. None examined; no row updates.
- **Blind spots found:**
  - (1) A file that only full compilation rejects (a module-level `return`) is parsed, not failed. Pinned.
  - (2) The scan reads `<repo>/src/probos`, not `probos.__file__`, so it does not depend on how the package is installed; the `EventType` check uses the imported package.
  - (3) A tracked file deleted from the local working tree raises `FileNotFoundError` locally. Loud; the gate's checkout is unaffected (1b-R2).
  - (4) Untracked files are no longer read. By design.
  - (5) `_emit_event_local`'s event dict and calls with an old name inside them are flagged. The safe direction (1b-R2).
  - (6) A `BaseEvent` whose `event_type` is set to a plain `str` is not resolved (1b-R1).
  - (7) Both CI and the gate run CPython 3.12. The decode probes re-run every time, so an interpreter change that breaks agreement fails loudly.
  - (8) The private `sys.modules` name avoids interfering with the fitness test file in the same xdist worker (`--dist=loadfile`).

## 14. Diff Reviewer: properties to verify (by execution)

1. **The real tree:** T2 passes. `_tracked_sources(src/probos)` equals `git ls-files -- "src/probos/*.py"` (made relative), and the scan parses every listed file, once.
2. **Decoding:** for each `_ENCODING_CASES` entry, and any module the reviewer adds, the importer's outcome equals `ast.parse(bytes)`'s. A module the importer runs that the scan rejects is a blocking finding.
3. **Recall against round 1:** run round 1's two regexes and `_old_producer_calls` over the 52 `str` sources in the three fixture tables, plus the reviewer's own corpus. Every disagreement must be listed in §8's Effect, 1b-R1 or 1b-R2. Predicted by reading the regexes: round 1 flags 5 of the 23 `str` flag cases (`private-callee`, `nested`, `two-calls`, `concatenated`, `set-alert`), 2 of the 17 ignore cases (`docstring`, `prefixed-callee`) and 0 of the 12 unresolved cases.
4. **Claims:** each claim in U1, U2a, U2b and the new file's docstrings is true of the head and maps to §8's claim table. None is an unprobed universal.
5. **The census:** rerun at least three §10 rows of the reviewer's choice; each is killed by a test in its cell.
6. **Scope:** no file under `src/` changes. The triggers-file diff is P1 to P3 exactly. T2's name is defined once under `tests/`.
7. **Isolation:** `pytest -n 0 tests/test_ad1270b_architecture_fitness.py tests/test_ad1270_night_orders_recall.py`, run in both orders, passes. `sys.modules["check_architecture_principles"]` is never set by the new file.
8. **The trackers' heads:** neither head has a lifecycle keyword in its first 120 characters.

## 15. Acceptance criteria

- The new file passes (76) and the triggers file passes (37). Every §10 mutant is killed.
- `check_architecture_principles.py --check` and `gen_ad_ledger.py --check` pass. The focused gates pass and the broad gate's receipt is green.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1324)

- **R13: built by this slice.** Each point R13 listed is covered:
  - G1: `ignores[payload-*]` and N-7.
  - G2: the BOM decode case, the tmp-repository scan and N-15.
  - G3 and G4: no prefilter; `flags[split-literal, escaped, normalised-callee]` and N-12.
  - G5: N-2, N-4 and the tmp-repository tests.
  - Round 4 F1: the three modules, the decode test, the earlier-reads test and N-14.
  - Round 4 F2: `flags[unpacked-display]`.
  - B3: all four names.
  - The first-positional rule: re-enumerated in §11.
  - Round 5 F1: no "failure means a producer" claim.
- **R11: superseded.**
  - Resolved: (a), (b) except `getattr`, (c)'s whitespace, `*`-display, split, escaped, raw and placeholder-free f-string forms, every false match, and the reading clause.
  - Not resolved: (b) `getattr`, (c)'s keyword, `**`, variable and placeholder f-string forms, and (d) and (e). These move to 1b-R1. Untracked files are no longer read.
- **1b-R1 (P3, injected-only; owner #1324; trigger: the slice that wires an alert-condition writer, or AD-455b):** T2 does not resolve an emitter alias, a call through `getattr` or a subscript (the setter included), a name held in a variable, an f-string with a placeholder, a name computed from another literal, an event passed by keyword (`event=`, `event_type=`, `name=`), through `**`, or through `*` over a non-display, a `BaseEvent` whose `event_type` is a plain `str`, or a producer outside `src/probos`. Each form except the last two is pinned in `test_old_producer_calls_does_not_resolve_these_forms`.
- **1b-R2 (P3, injected-only):** T2 fails without a producer on an event argument that contains an old name but evaluates to another (`flags[contained-in-call]`), on `_emit_event_local` whose event dict names one (`flags[local-dispatch]`; it bypasses the hook), and locally on a tracked file deleted from the working tree. The safe direction; no action.
- **1b-R3 (trivial, deferred):** `tests/test_bf925_guard_names.py` reads `rglob` with UTF-8 (round 1's reading), and three scripts each define `_tracked_python_files`. A shared tracked-source parsing helper would serve them all, in a later slice.
