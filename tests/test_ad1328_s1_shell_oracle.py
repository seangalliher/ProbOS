"""AD-1328 S1 (#1530), repair round 1, milestone R-M4 -- the reference-shell oracle.

Tests only. ``tests/fixtures/ad1328_shell_oracle.json`` records, row by row, a command line whose programs are the
argv probe (``tests/fixtures/ad1328_argv_probe.py``), the reading the policy must give it (``policy`` and ``marks``)
and, where the row says so, the argv the real shell hands the probe (``live``). This file checks:

* ``test_oracle_file_shape``, ``test_admission_helper``, ``test_distinct_admission_helper`` and
  ``test_live_skip_reason_helper``: the data, and the helpers the live test stands on, on every host;
* ``test_policy_reads_each_row_as_recorded``: on every host, ``parse_command`` reads each row, under a fixed synthetic
  prefix, exactly as the row records it;
* ``test_live_shell_agrees``: where the shell exists, the shell started the way its consumer starts it (``/bin/sh -c``
  off Windows, ``cmd.exe /c`` through ``shell=True``, ``powershell`` and ``pwsh`` with ``-NoProfile -Command``) runs
  the row's real text; what the probe received is admitted by the policy's reading of that same text and, where the
  row records it, equals the recorded argv.

A live row that fails is a finding for the Architect (the expectations are authored from each shell's documented
grammar): the failure prints the observed argv lists, and no row is ever edited, xfailed or weakened to make it pass.
Nothing is imported from another test file, and no test marks itself ``slow``: each live run is a few short processes.
"""

from __future__ import annotations

import functools
import json
import ntpath
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from probos.config_models.operations import CommandPolicyConfig, windows_program_stem
from probos.execution.command_policy import DIALECTS, CommandSegment, ParsedCommand, evaluate_command, parse_command

# --------------------------------------------------------------------------------------
# The oracle and its constants
# --------------------------------------------------------------------------------------

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_PROBE_PATH = _FIXTURES / "ad1328_argv_probe.py"
# Read as UTF-8 explicitly: row P21 is non-ASCII.
_ORACLE: dict[str, Any] = json.loads((_FIXTURES / "ad1328_shell_oracle.json").read_text(encoding="utf-8"))
_ROWS: list[dict[str, Any]] = _ORACLE["rows"]

_SCHEMA = "probos.ad1328.shell_oracle/v1"
_ID_PREFIX = {"posix": "P-", "cmd": "C-", "powershell": "S-"}
# The shells each dialect's rows run under live (R6); a row's own ``shells`` may name a subset.
_SHELLS: dict[str, tuple[str, ...]] = {"posix": ("dash", "bash"), "cmd": ("cmd",), "powershell": ("powershell", "pwsh")}
_POSIX_SHELLS = frozenset({"dash", "bash"})
_WINDOWS_SHELLS = frozenset({"cmd", "powershell"})
# The fixed synthetic prefixes of the every-host check: (interpreter, probe).
_SYNTHETIC: dict[str, tuple[str, str]] = {
    "posix": ("/opt/ad1328/python3", "/opt/ad1328/probe.py"),
    "cmd": (r"C:\ad1328\python.exe", r"C:\ad1328\probe.py"),
    "powershell": (r"C:\ad1328\python.exe", r"C:\ad1328\probe.py"),
}

_REQUIRED_KEYS = frozenset({"id", "dialect", "constructs", "text", "policy"})
_OPTIONAL_KEYS = frozenset({"marks", "runs", "live", "env", "files", "requires", "shells"})
_FILE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")

# A bare prefix (``{B}``) is the two paths separated by a space: they must hold nothing a shell reads (R6).
_BARE_SAFE = re.compile(r"[A-Za-z0-9_.:\\/-]+")
# A quoted prefix (``{P}``) cannot carry a quote, ``%``, ``$``, a backtick or a character outside printable ASCII
# (cmd and PowerShell read an ASCII-only language): such a path is skipped live, never run into a false failure.
_QUOTE_UNSAFE = re.compile(r"""['"%$`]|[^\x20-\x7e]""")
_RUN_TIMEOUT_SECONDS = 60

# One probe segment as the policy reads it: the words after the prefix (None = a dynamic word) and one mark each
# (``l`` literal, ``o`` one word, ``v`` any number of words).
Reading = tuple[list[str | None], str]


# --------------------------------------------------------------------------------------
# Helpers (local: nothing is imported across test files)
# --------------------------------------------------------------------------------------


def _prefix(dialect: str, python: str, probe: str) -> str:
    """The dialect's probe prefix (R6): the interpreter and the probe, quoted the way the dialect reads them."""
    if dialect == "posix":
        return f"'{python}' '{probe}'"
    if dialect == "cmd":
        return f'"{python}" "{probe}"'
    if dialect == "powershell":
        return f"& '{python}' '{probe}'"
    raise ValueError(f"unknown dialect {dialect!r}")


def _substitute(text: str, dialect: str, python: str, probe: str) -> str:
    """Replace ``{P}`` (the dialect's prefix) and ``{B}`` (the bare prefix) with ``str.replace``: rows hold braces."""
    return text.replace("{P}", _prefix(dialect, python, probe)).replace("{B}", f"{python} {probe}")


def _probe_segments(parsed: ParsedCommand, python: str, probe: str) -> list[CommandSegment]:
    """The segments that start the probe, in segment order: the program is the interpreter (by its Windows stem) and
    the first argument ends with the probe's file name (``probe.py`` synthetic, ``ad1328_argv_probe.py`` live)."""
    stem = windows_program_stem(python)
    name = ntpath.basename(probe)
    return [
        segment
        for segment in parsed.segments
        if len(segment.tokens) > 1
        and windows_program_stem(segment.tokens[0]) == stem
        and segment.tokens[1].endswith(name)
    ]


_MARK = {(False, False): "l", (True, False): "o", (True, True): "v"}


def _reading(segment: CommandSegment) -> Reading:
    """The words after the prefix as the policy reads them (None for a dynamic word) and their marks; a word that is
    literal yet variadic has no mark and reads as ``?``."""
    words = [None if dynamic else token for token, dynamic in zip(segment.tokens[2:], segment.dynamic[2:], strict=True)]
    marks = "".join(_MARK.get(flags, "?") for flags in zip(segment.dynamic[2:], segment.variadic[2:], strict=True))
    return words, marks


def _row_readings(row: dict[str, Any]) -> list[Reading]:
    """What the row records per probe segment: the ``policy`` words and the ``marks`` (default: all literal)."""
    marks = row.get("marks") or ["l" * len(words) for words in row["policy"]]
    return [(list(words), mark) for words, mark in zip(row["policy"], marks, strict=True)]


def _reading_problem(row: dict[str, Any], parsed: ParsedCommand, segments: list[CommandSegment]) -> str | None:
    """Why the policy does not read the line as the row records, or None (shared by the every-host and live tests)."""
    if parsed.unparseable is not None:
        return f"the policy refuses the whole line: {parsed.unparseable}"
    # r2 (review r2, F6): every segment of the line, not only the probe's; a refused side command fails the row too.
    unreadable = [segment.unparseable for segment in parsed.segments if segment.unparseable is not None]
    if unreadable:
        return f"the policy cannot read a segment of the line: {unreadable}"
    expected = _row_readings(row)
    if len(segments) != len(expected):
        return (
            f"the policy finds {len(segments)} probe segments, the row records {len(expected)}; "
            f"it reads the segments {[segment.tokens for segment in parsed.segments]!r}"
        )
    for index, (segment, want) in enumerate(zip(segments, expected, strict=True)):
        got = _reading(segment)
        if got != want:
            return f"probe segment {index}: the policy reads {got!r}, the row records {want!r}"
    return None


def _admits(words: Sequence[str | None], marks: str, argv: Sequence[str]) -> bool:
    """True when ``argv`` is something the reading admits: a literal (``l``) equals its word, a one-word dynamic word
    (``o``) takes exactly one argument, a variadic one (``v``) takes zero or more. A memoised alignment."""
    if len(words) != len(marks):
        raise ValueError(f"a reading has one mark per word: {len(words)} words, marks {marks!r}")

    @functools.cache
    def fits(word: int, arg: int) -> bool:
        if word == len(marks):
            return arg == len(argv)
        mark = marks[word]
        if mark == "l":
            return arg < len(argv) and argv[arg] == words[word] and fits(word + 1, arg + 1)
        if mark == "o":
            return arg < len(argv) and fits(word + 1, arg + 1)
        if mark == "v":
            return any(fits(word + 1, taken) for taken in range(arg, len(argv) + 1))
        return False

    return fits(0, 0)


def _distinct_admission(readings: Sequence[Reading], observed: Sequence[Sequence[str]]) -> bool:
    """True when every observed argv list can be given its own probe segment that admits it. Order-insensitive: a
    pipeline or a background job starts its programs in no fixed order (a bipartite matching, by augmenting paths)."""
    owner: dict[int, int] = {}

    def place(argv: int, tried: set[int]) -> bool:
        for index, (words, marks) in enumerate(readings):
            if index in tried or not _admits(words, marks, observed[argv]):
                continue
            tried.add(index)
            if index not in owner or place(owner[index], tried):
                owner[index] = argv
                return True
        return False

    return all(place(argv, set()) for argv in range(len(observed)))


def _is_argv_lists(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(argv, list) and all(isinstance(word, str) for word in argv) for argv in value
    )


def _row_shape_problems(row: dict[str, Any], constructs: dict[str, list[str]]) -> list[str]:
    """Everything wrong with one row's shape (the fields of the contract's Section 4), as messages."""
    keys = set(row)
    problems: list[str] = []
    if _REQUIRED_KEYS - keys:
        problems.append(f"missing keys {sorted(_REQUIRED_KEYS - keys)}")
    if keys - _REQUIRED_KEYS - _OPTIONAL_KEYS:
        problems.append(f"unknown keys {sorted(keys - _REQUIRED_KEYS - _OPTIONAL_KEYS)}")
    if problems:
        return problems
    dialect = row["dialect"]
    if dialect not in DIALECTS:
        return [f"unknown dialect {dialect!r}"]
    if not isinstance(row["text"], str) or not ("{P}" in row["text"] or "{B}" in row["text"]):
        problems.append("text must be a string that starts the probe through {P} or {B}")
    if not isinstance(row["constructs"], list) or not set(row["constructs"]) <= set(constructs[dialect]):
        problems.append(f"constructs {row['constructs']!r} are not a subset of the {dialect} list")

    policy = row["policy"]
    if not isinstance(policy, list) or not policy or not all(
        isinstance(words, list) and all(word is None or isinstance(word, str) for word in words) for words in policy
    ):
        return [*problems, "policy must be a non-empty list of word lists (a string, or null for a dynamic word)"]
    marks = row.get("marks")
    if marks is None:
        if any(word is None for words in policy for word in words):
            problems.append("a dynamic word (null) needs marks")
    elif not isinstance(marks, list) or len(marks) != len(policy):
        problems.append(f"marks must hold one string per probe segment ({len(policy)})")
    else:
        for index, (words, mark) in enumerate(zip(policy, marks, strict=True)):
            if not isinstance(mark, str) or len(mark) != len(words):
                problems.append(f"marks[{index}] {mark!r} must hold one mark per word ({len(words)})")
            elif set(mark) - set("lov"):
                problems.append(f"marks[{index}] {mark!r} may use only l, o and v")
            elif any((kind == "l") != (word is not None) for kind, word in zip(mark, words, strict=True)):
                problems.append(f"marks[{index}] {mark!r}: a literal mark belongs to a literal word, and only to one")

    runs = row.get("runs", len(policy))
    if not isinstance(runs, int) or isinstance(runs, bool) or not 1 <= runs <= len(policy):
        problems.append(f"runs {runs!r} must be an integer from 1 to the probe-segment count ({len(policy)})")
        runs = len(policy)
    live = row.get("live")
    if live is not None:
        if isinstance(live, dict):
            if set(live) - set(_SHELLS[dialect]):
                problems.append(f"live maps {sorted(set(live) - set(_SHELLS[dialect]))} outside the {dialect} shells")
            lists = list(live.values())
        else:
            lists = [live]
        for argv_lists in lists:
            if not _is_argv_lists(argv_lists):
                problems.append("live must be a list of argv lists (strings), or a map from shell to one")
            elif len(argv_lists) != runs:
                problems.append(f"live holds {len(argv_lists)} argv lists, the run starts {runs} invocations")

    env = row.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        problems.append("env must map names to strings")
    files = row.get("files", [])
    if not isinstance(files, list) or not all(isinstance(name, str) and _FILE_NAME.fullmatch(name) for name in files):
        problems.append("files must be plain file names")
    requires = row.get("requires", [])
    if not isinstance(requires, list) or not all(isinstance(name, str) and name for name in requires):
        problems.append("requires must list program names")
    shells = row.get("shells", list(_SHELLS[dialect]))
    if not isinstance(shells, list) or not shells or not set(shells) <= set(_SHELLS[dialect]):
        problems.append(f"shells must be a non-empty subset of {list(_SHELLS[dialect])}")
    return problems


def _live_skip_reason(
    row: dict[str, Any],
    shell: str,
    *,
    windows: bool = sys.platform == "win32",
    paths: Sequence[str] | None = None,
) -> str | None:
    """Why this row cannot run under this shell on this host, or None. ``windows`` and ``paths`` (the interpreter and
    the probe) default to this host's; they are arguments so the skip rules can be exercised on any host."""
    if shell in _POSIX_SHELLS and windows:
        return "POSIX rows run live off Windows only: MSYS argument transport on Windows is not the reference"
    if shell in _WINDOWS_SHELLS and not windows:
        return f"{shell} exists on Windows only"
    if shell != "cmd" and shutil.which(shell) is None:
        return f"{shell} is not found on PATH"
    for program in row.get("requires", []):
        if shutil.which(program) is None:
            return f"{program}, which the row requires, is not found on PATH"
    if paths is None:
        paths = (sys.executable, str(_PROBE_PATH))
    if "{B}" in row["text"] and not all(_BARE_SAFE.fullmatch(path) for path in paths):
        return (
            "the interpreter or probe path holds a character outside [A-Za-z0-9_.:\\/-]: "
            "a bare prefix cannot carry it"
        )
    if any(_QUOTE_UNSAFE.search(path) for path in paths):
        return (
            "the interpreter or probe path holds a quote, %, $, a backtick or a non-ASCII character: "
            "a quoted prefix cannot carry it"
        )
    return None


def _run_shell(shell: str, text: str, env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Start ``text`` exactly as its consumer starts it (R6): POSIX ``[shell_path, "-c", text]``, cmd ``text`` with
    ``shell=True`` (``cmd.exe /c "..."``), PowerShell ``["powershell" | "pwsh", "-NoProfile", "-Command", text]``."""
    options: dict[str, Any] = {
        "env": env,
        "cwd": cwd,
        "capture_output": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": _RUN_TIMEOUT_SECONDS,
    }
    if shell in _POSIX_SHELLS:
        return subprocess.run([shutil.which(shell) or shell, "-c", text], **options)
    if shell == "cmd":
        return subprocess.run(text, shell=True, **options)
    if shell in ("powershell", "pwsh"):
        return subprocess.run([shell, "-NoProfile", "-Command", text], **options)
    raise ValueError(f"unknown shell {shell!r}")


def _read_log(log: Path) -> list[list[str]]:
    """The argv lists the probe appended, one JSON line per invocation; none when no probe ran."""
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def _expected_live(row: dict[str, Any], shell: str) -> list[list[str]] | None:
    """The argv lists the row records for this shell: ``live`` itself, or its entry for the shell when it is a map."""
    live = row.get("live")
    return live.get(shell) if isinstance(live, dict) else live


# --------------------------------------------------------------------------------------
# 1. The file's own shape
# --------------------------------------------------------------------------------------


def test_oracle_file_shape() -> None:
    """The data is well-formed: schema, unique ids, known dialects, every construct id tied to a row, marks that
    fit their words, live maps that name only the dialect's shells."""
    problems: list[str] = []
    if _ORACLE["schema"] != _SCHEMA:
        problems.append(f"schema is {_ORACLE['schema']!r}, expected {_SCHEMA!r}")
    constructs: dict[str, list[str]] = _ORACLE["constructs"]
    if set(constructs) != set(DIALECTS):
        problems.append(f"constructs lists {sorted(constructs)}, expected one list per dialect {sorted(DIALECTS)}")
        constructs = {dialect: constructs.get(dialect, []) for dialect in DIALECTS}
    for dialect in DIALECTS:
        listed = constructs[dialect]
        if len(listed) != len(set(listed)):
            problems.append(f"constructs.{dialect} repeats an id")
        stray = [name for name in listed if not name.startswith(_ID_PREFIX[dialect])]
        if stray:
            problems.append(f"constructs.{dialect} holds ids without the {_ID_PREFIX[dialect]!r} prefix: {stray}")

    ids = [row.get("id") for row in _ROWS]
    duplicated = sorted({str(row_id) for row_id in ids if ids.count(row_id) > 1})
    if duplicated:
        problems.append(f"row ids are not unique: {duplicated}")
    used: dict[str, set[str]] = {dialect: set() for dialect in DIALECTS}
    for index, row in enumerate(_ROWS):
        label = row.get("id", f"row #{index}")
        problems.extend(f"{label}: {problem}" for problem in _row_shape_problems(row, constructs))
        if row.get("dialect") in used and isinstance(row.get("constructs"), list):
            used[row["dialect"]].update(name for name in row["constructs"] if isinstance(name, str))
    for dialect in DIALECTS:
        unused = [name for name in constructs[dialect] if name not in used[dialect]]
        if unused:
            problems.append(f"constructs.{dialect}: no row exercises {unused}")

    assert not problems, "the oracle file is malformed:\n" + "\n".join(problems)


# --------------------------------------------------------------------------------------
# 2. The admission helpers
# --------------------------------------------------------------------------------------


def test_admission_helper() -> None:
    """``_admits``: a literal equals, ``o`` takes exactly one argument, ``v`` zero or more; the alignment backtracks."""
    assert _admits(["a", None], "lv", ["a", "x", "y"])
    assert not _admits(["a", None], "lo", ["a", "x", "y"])  # `o` is exactly one word
    assert _admits(["a", None], "lo", ["a", "x"])  # ... and one word fits it
    assert not _admits(["a"], "l", ["b"])  # a literal mismatch
    assert not _admits(["a"], "l", [])  # a literal must be present
    assert not _admits(["a"], "l", ["a", "b"])  # an argument no word accounts for
    assert _admits([None], "v", [])  # `v` admits no words at all
    assert not _admits([None], "o", [])  # ... `o` does not
    assert _admits([], "", [])
    assert not _admits([], "", ["a"])
    assert _admits(["a", None, "b"], "lvl", ["a", "b"])  # a variadic word between literals can be empty
    assert _admits(["a", None, "b"], "lvl", ["a", "b", "b"])  # ... or swallow what a literal also equals
    assert not _admits(["a", None, "b"], "lvl", ["a", "b", "c"])  # ... but the literal after it must still appear
    # Row P15 as the policy reads it: `$W "$W" ${W} "${W}"` with W="x  y" reaches the probe as six words.
    assert _admits([None] * 4, "vovo", ["x", "y", "x  y", "x", "y", "x  y"])
    assert not _admits([None], "?", ["x"])  # a (literal, variadic) pair is no reading at all
    with pytest.raises(ValueError):
        _admits(["a"], "ll", ["a"])


def test_distinct_admission_helper() -> None:
    """``_distinct_admission``: every observed argv list needs its own admitting reading, in any order."""
    literal_a: Reading = (["a"], "l")
    literal_b: Reading = (["b"], "l")
    anything: Reading = ([None], "v")
    assert _distinct_admission([literal_a, literal_b], [["b"], ["a"]])  # no fixed order
    assert _distinct_admission([literal_a, literal_b, literal_a], [["a"], ["b"]])  # fewer runs than segments
    assert _distinct_admission([anything, literal_a], [["a"], ["b"]])  # an augmenting path: `a` must yield `anything`
    assert not _distinct_admission([literal_a], [["a"], ["a"]])  # one segment cannot account for two runs
    assert not _distinct_admission([literal_a, literal_b], [["a"], ["a"]])  # `b` never admits `a`
    assert not _distinct_admission([literal_a], [["c"]])  # no reading admits it
    assert _distinct_admission([literal_a], [])  # no run, nothing to place
    assert not _distinct_admission([], [["a"]])


def test_live_skip_reason_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_live_skip_reason``: a row runs only where its consumer runs, with its shell and required programs on PATH and
    with paths its prefix can carry; otherwise it is skipped, and the reason names the cause."""
    on_path = {"dash", "bash", "powershell", "pwsh", "nice"}
    monkeypatch.setattr(shutil, "which", lambda name: f"/found/{name}" if name in on_path else None)
    carried = ("/usr/bin/python3", "/work/tests/fixtures/ad1328_argv_probe.py")
    quoted: dict[str, Any] = {"text": "{P} a"}
    bare: dict[str, Any] = {"text": "{B} a"}

    for shell in ("dash", "bash"):  # POSIX shells run off Windows only
        assert _live_skip_reason(quoted, shell, windows=False, paths=carried) is None
        assert "off Windows only" in str(_live_skip_reason(quoted, shell, windows=True, paths=carried))
    for shell in ("cmd", "powershell"):  # cmd.exe and Windows PowerShell run on Windows only
        assert _live_skip_reason(quoted, shell, windows=True, paths=carried) is None
        assert _live_skip_reason(quoted, shell, windows=False, paths=carried) == f"{shell} exists on Windows only"
    for windows in (True, False):  # pwsh runs wherever it is found
        assert _live_skip_reason(quoted, "pwsh", windows=windows, paths=carried) is None
    on_path.discard("pwsh")
    assert _live_skip_reason(quoted, "pwsh", windows=True, paths=carried) == "pwsh is not found on PATH"

    assert _live_skip_reason({"text": "{P} a", "requires": ["nice"]}, "bash", windows=False, paths=carried) is None
    missing = _live_skip_reason({"text": "{P} a", "requires": ["nice", "stdbuf"]}, "bash", windows=False, paths=carried)
    assert missing == "stdbuf, which the row requires, is not found on PATH"

    spaced = ("/usr/bin/python 3", "/work/tests/fixtures/ad1328_argv_probe.py")
    windows_paths = (r"D:\ProbOS\.venv\Scripts\python.exe", r"D:\ProbOS-wt\tests\fixtures\ad1328_argv_probe.py")
    assert "bare prefix" in str(_live_skip_reason(bare, "bash", windows=False, paths=spaced))  # {B}: no space
    assert "bare prefix" in str(_live_skip_reason(bare, "bash", windows=False, paths=(carried[0], "/my dir/probe.py")))
    assert _live_skip_reason(bare, "cmd", windows=True, paths=windows_paths) is None  # a drive and backslashes are fine
    assert _live_skip_reason(quoted, "bash", windows=False, paths=spaced) is None  # {P}: quotes carry a space
    for unsafe in ("/it's/python3", "/50%/python3", "/$HOME/python3", "/a`b/python3", "/caf\u00e9/python3"):
        reason = _live_skip_reason(quoted, "bash", windows=False, paths=(unsafe, carried[1]))
        assert "quoted prefix" in str(reason), f"{unsafe!r} -> {reason!r}"


# --------------------------------------------------------------------------------------
# 3. The policy reads each row as recorded (every host)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("row", _ROWS, ids=[row.get("id", f"row-{index}") for index, row in enumerate(_ROWS)])
def test_policy_reads_each_row_as_recorded(row: dict[str, Any]) -> None:
    """Under the fixed synthetic prefix the line parses, and each probe segment's words after the prefix are the
    row's (literals equal, ``(dynamic, variadic)`` per mark), in segment order."""
    dialect = row["dialect"]
    python, probe = _SYNTHETIC[dialect]
    text = _substitute(row["text"], dialect, python, probe)
    parsed = parse_command(text, dialect=dialect)
    problem = _reading_problem(row, parsed, _probe_segments(parsed, python, probe))
    assert problem is None, f"{row['id']} ({dialect}) {text!r}: {problem}"


# --------------------------------------------------------------------------------------
# 4. The live shell agrees (where the shell exists)
# --------------------------------------------------------------------------------------

_LIVE_CASES = [
    pytest.param(row, shell, id=f"{row.get('id', f'row-{index}')}-{shell}")
    for index, row in enumerate(_ROWS)
    for shell in row.get("shells", _SHELLS.get(row.get("dialect"), ()))
]


@pytest.mark.parametrize(("row", "shell"), _LIVE_CASES)
def test_live_shell_agrees(row: dict[str, Any], shell: str, tmp_path: Path) -> None:
    """The real shell runs the row's real text. The policy reads that text as in the every-host test; the probe is
    started ``runs`` times; each argv it received is admitted by its own probe segment of the policy's reading and,
    where the row records ``live`` (per shell when it is a map), the argv lists equal the recorded ones."""
    reason = _live_skip_reason(row, shell)
    if reason is not None:
        pytest.skip(reason)
    dialect = row["dialect"]
    python, probe = sys.executable, str(_PROBE_PATH)
    text = _substitute(row["text"], dialect, python, probe)
    parsed = parse_command(text, dialect=dialect)
    segments = _probe_segments(parsed, python, probe)
    problem = _reading_problem(row, parsed, segments)
    assert problem is None, f"{row['id']} ({shell}) live text {text!r}: {problem}"

    for name in row.get("files", []):
        (tmp_path / name).touch()
    log = tmp_path / "ad1328_probe.log"
    env = {
        **os.environ,
        **row.get("env", {}),
        "AD1328_PROBE_LOG": str(log),
        "MSYS_NO_PATHCONV": "1",
        "MSYS2_ARG_CONV_EXCL": "*",
    }
    try:
        completed = _run_shell(shell, text, env, tmp_path)
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"{row['id']} under {shell} did not finish in {_RUN_TIMEOUT_SECONDS} s; live text {text!r}; "
            f"observed argv lists so far {_read_log(log)!r}"
        )
    observed = _read_log(log)
    context = (
        f"{row['id']} under {shell}: live text {text!r}; observed argv lists {observed!r}; "
        f"exit code {completed.returncode}; stderr {completed.stderr.strip()[:1000]!r}"
    )

    runs = row.get("runs", len(segments))
    assert len(observed) == runs, f"the probe started {len(observed)} times, the row records {runs}: {context}"
    readings = [_reading(segment) for segment in segments]
    assert _distinct_admission(readings, observed), (
        f"each observed argv list needs its own probe segment that admits it; the policy reads {readings!r}: {context}"
    )
    expected = _expected_live(row, shell)
    if expected is not None:
        assert sorted(observed) == sorted(expected), f"the row records the argv lists {expected!r}: {context}"


@pytest.mark.parametrize("row_id", ["P11", "P17"])
def test_reading_problem_fails_a_refused_non_probe_segment(row_id: str) -> None:
    # Review r2, F6: P11's `wait` and P17's `printf` are side commands; a refusal there must fail the row.
    row = next(row for row in _ROWS if row["id"] == row_id)
    python, probe = _SYNTHETIC[row["dialect"]]
    text = _substitute(row["text"], row["dialect"], python, probe)
    parsed = parse_command(text, dialect=row["dialect"])
    probes = _probe_segments(parsed, python, probe)
    assert _reading_problem(row, parsed, probes) is None  # premise: the row reads as recorded
    others = [segment for segment in parsed.segments if segment not in probes]
    assert others, "premise: the row has a segment that is not a probe segment"
    refused = replace(
        parsed,
        segments=tuple(replace(s, unparseable="counterfactual refusal") if s in others else s for s in parsed.segments),
    )
    problem = _reading_problem(row, refused, _probe_segments(refused, python, probe))
    assert problem is not None and "counterfactual refusal" in problem


def test_r3_ssh_agent_runs_its_argument_as_a_child(tmp_path: Path) -> None:
    """Review r3, F1 (executed with Git for Windows' ssh-agent under bash, dash, cmd, PowerShell 5.1 and pwsh 7,
    2026-10-16, ``launcher_property.py``): ssh-agent runs the program its arguments name. The policy part runs on every
    host. The live part runs where POSIX rows run (off Windows: MSYS transport is not the reference), with bash,
    ssh-agent and printf on PATH; otherwise it skips and names the cause."""
    config = CommandPolicyConfig.model_validate(
        {
            "rules": [{"name": "no-printf", "pattern": ["printf"], "decision": "forbid", "justification": "r3", "alternative": "other"}],
            "unmatched_decision": "allow",
            "unparseable_decision": "escalate",
        }
    )
    text = "ssh-agent printf R3CHILD"
    assert evaluate_command(config, "printf R3CHILD", dialect="posix").decision == "forbid"  # control
    assert evaluate_command(config, text, dialect="posix").decision == "escalate"
    reason = _live_skip_reason({"text": text, "requires": ["ssh-agent", "printf"]}, "bash", paths=("python", "probe.py"))
    if reason is not None:
        pytest.skip(reason)
    completed = _run_shell("bash", text, dict(os.environ), tmp_path)
    assert (completed.returncode, completed.stdout) == (0, "R3CHILD"), completed.stderr  # the premise: the child ran
