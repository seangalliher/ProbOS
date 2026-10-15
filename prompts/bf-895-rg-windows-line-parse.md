# Build contract: BF-895 (#1548): the rg engine parses Windows paths and never reports a false zero

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-15
**Revised by:** `claude-architect` (Opus 5.5), 2026-10-15, after review round 1 (see Revision 1)
**Status:** built as one slice, revised after review round 1 (2026-10-15) · **Depends on:** none (`agents/code_search.py` and its tests as on `main` `f2a0db6d`; unchanged on `579b5530`, where it was built) · **New tests:** 37 collected, in one new file (33 run everywhere; four cases from three test functions need `rg` on PATH, one of them Windows-only). The first build's 25, plus one the orchestrator added (the fallback warning carries the exit code, a byte count and the root, and never match text), reworked for the `--null` shape in round 1.

**Verdict: build it.** Three changes in one file:

1. **Parser (revised after review round 1).** rg runs with `--null`, so every line is `path<NUL>lineno:text`, and `_parse_rg_line` splits at the first NUL and then at the first `:`; the line-number field must be ASCII digits within `int()`'s digit limit (the old parser's `ValueError` guard is kept), or the line is unparsed. No path can hold NUL, so this is exact on every OS: a Windows drive, `\\?\C:\` long paths, UNC paths, NTFS streams (`f.txt:7`), a POSIX filename with a colon or a `:<digits>:` segment, and match text that itself starts `12:`.
   - History: the first build used a lazy colon pattern, `(.+?):([0-9]+):(.*)` with `fullmatch`. Review round 1 reproduced that it mis-splits an NTFS stream file root (`f.txt:7` came back as `f.txt`, line 7), so the "POSIX only" limit this contract first stated was wrong; `--null` removes the ambiguity instead of working around it.
   - Rejected alternatives:
     - **`rg --json`** would replace the whole output format and add `begin`/`end`/`summary`/`context` event handling plus base64 decoding of `path.bytes` and `lines.bytes`. That is a larger change to fix one line shape.
     - **The anchored drive-letter regex** (`^((?:[A-Za-z]:)?[^:]*):…`) drops `\\?\C:\…` paths and every POSIX filename that contains a colon.
     - **Stripping the known `str(root)` prefix** (a file root only, or both root kinds) depends on rg echoing the root byte for byte and keeps a pattern as the fallback.
2. **Two rg arguments are added: `--with-filename` and `--null`.**
   - The issue's "no change to the rg arguments" yields for these two flags. ripgrep's docs say it never prints the path "when ripgrep is explicitly instructed to search one file", and `act` accepts a file root (`_search_python` handles `root.is_file()`, code_search.py:222). So a file root returns `3:hello`, which has no path and can never satisfy acceptance (1). `--null` (round 1) ends each printed path with NUL for the parse above; it changes nothing when no path is printed, so `--with-filename` stays.
   - The flags add arguments and change no existing one; the timeout is untouched.
   - The spawn-env guard counts launches per function, not argv, so its inventory does not change.
3. **No false zero.** If rg exits 0 (which means it found a match) or prints anything (any byte, whitespace included: round 1), and nothing parsed, `_search_rg` logs a warning and returns `None`. `act` then falls back to the Python engine (code_search.py:153-156).
   - Exit 1 with no output stays `success: True, count: 0, engine: "rg"`.
   - Context lines (`path-3-text`) and `--` separators cannot occur, because the arguments never include `-A`/`-B`/`-C`.
   - Warnings go to stderr, which is not parsed. A launch that hits a file error exits 2, which already falls back (:191).

## Verified Against Codebase (2026-10-15, HEAD `16abfbf7`)

```
Grep "_parse_rg_line|_search_rg|returncode|max_results" src/probos/agents/code_search.py
  152:            rg_result = await self._search_rg(rg, plan, root)
  156:        return self._search_python(plan, root)
  165:    async def _search_rg(self, rg: str, plan: dict, root: Path) -> dict | None:
  168:        args = [rg, "--line-number", "--no-heading", "--color", "never",
  169:                "--max-count", str(plan["max_results"])]
  191:        if proc.returncode not in (0, 1):
  195:            parsed = _parse_rg_line(line)
  283:def _parse_rg_line(line: str) -> dict | None:
Read code_search.py:283-299   split on first two colons; first <= 0 -> None; int(lineno) else None
Read code_search.py:222        files = [root] if root.is_file() else iter_files(   (a file root is supported)
Grep "^import|^logger|^_[A-Z_]+ =" code_search.py
  25:import re   42:logger = logging.getLogger(__name__)   46:_LINE_PREVIEW_CHARS = 300
Read code_search.py:95-100     handle_intent returns result=report["data"] (no engine) -> tests call decide/act
Grep "rg|ripgrep" .github/workflows/ci.yml   -> only runs-on: ubuntu-latest (no ripgrep install step)
Grep "code_search" tests/test_bf892_spawn_env_guard.py
  86: ("src/probos/agents/code_search.py", "CodeSearchAgent._search_rg"): (1, "rg; model text only as a bound --regexp/--glob value; RIPGREP_CONFIG_PATH"),
ripgrep crates/core/flags/defs.rs (WithFilenameNo): "never print the file path ... This is the default
  when ripgrep is explicitly instructed to search one file or stdin."
```

### Absence Verified

| Claim | Run | Found | Holds |
|---|---|---|---|
| `_parse_rg_line` has no other production caller | Grep `_parse_rg_line` src/ | code_search.py:195, :283 | yes |
| No test exercises a real or faked rg subprocess | Grep `_search_rg\|create_subprocess_exec` tests/ for code_search | only the guard row at test_bf892_spawn_env_guard.py:86 | yes |
| The rg arguments never request context lines | Read code_search.py:168-176 | no `-A/-B/-C/--context` | yes |
| CI does not install ripgrep | Grep `rg\|ripgrep` .github/workflows/ci.yml | none | yes (whether the `ubuntu-latest` image ships `rg` is not verified; the skip covers both cases) |
| No other rg line parser in src | Grep `--line-number\|with-filename` src/ | code_search.py:168 only | yes |

## Hidden pins

| Pin | Why | Action |
|---|---|---|
| `tests/test_ad989_code_search.py:166-173` `test_parse_rg_line` | asserts the parser's four properties: a parsed line, text containing colons, `garbage` → None, a non-numeric line number → None | rewritten to the NUL shape (`src/main.py\x0012:def foo():`), same four properties, reason inline (round 1 ruling: the old `path:lineno:text` shape is the ambiguous one) |
| `tests/test_ad989_code_search.py:18-24` autouse fixture forces the Python engine | none of its tests reach `_search_rg` | unchanged; the new tests live in a new file without that fixture |
| `tests/test_bf892_spawn_env_guard.py:86` keys `CodeSearchAgent._search_rg` with 1 launch | moving the launch or adding a second one breaks the inventory | keep the single `create_subprocess_exec` inside `_search_rg`; adding an argument is safe |
| `tests/test_ad1025b_path_anchoring.py:94-125` patches `_resolve_rg_binary`/`shutil.which` | binary resolution only | untouched |

## Revision 1 (2026-10-15, after review round 1; claude-architect consult, session `60f918ad`)

Round 1 (GPT-6.1 Sol) found three P2s, all reproduced by the orchestrator: (1) ordinary reach: a file root that is an NTFS stream with a numeric name (`f.txt:7`) is mis-split by the lazy colon pattern (path `f.txt`, line 7); (2) a regression: the old parser's `ValueError` guard was lost, so a line-number field over `int()`'s 4,300-digit limit (reachable through an operator's ripgreprc, which `trusted_command_env()` passes to rg) aborts the search; (3) whitespace-only stdout with exit 1 was reported as an rg zero. Decisions: **D1 = `--null`** (ranked above stripping the known root prefix, for a file root only or for both root kinds); **D2 = keep the guard** (the field must be ASCII digits; `try/except ValueError`); **D3 = fix here** (`stdout` in place of `stdout.strip()`). **Sections 1 and 2 below are the first build and are superseded.** The current code and tests are `src/probos/agents/code_search.py` (`--null` in the argv, `_parse_rg_line` on `path<NUL>lineno:text`, `or stdout`), `tests/test_bf895_rg_line_parse.py` (37 tests) and the rewritten pin `tests/test_ad989_code_search.py::test_parse_rg_line`.

## Section 1: `src/probos/agents/code_search.py` (first build; superseded by Revision 1)

<<<<<<< SEARCH
        args = [rg, "--line-number", "--no-heading", "--color", "never",
                "--max-count", str(plan["max_results"])]
        if plan["case_insensitive"]:
=======
        # BF-895 (#1548): --with-filename keeps the path on every line; rg omits it
        # when the root is a single file.
        args = [rg, "--line-number", "--with-filename", "--no-heading",
                "--color", "never", "--max-count", str(plan["max_results"])]
        if plan["case_insensitive"]:
>>>>>>> REPLACE

<<<<<<< SEARCH
                if len(matches) >= plan["max_results"]:
                    break
        return {
            "success": True,
            "data": matches,
=======
                if len(matches) >= plan["max_results"]:
                    break
        # BF-895 (#1548): exit 0 means rg found a match. If nothing parsed, the parser
        # and rg disagree: report nothing rather than a false zero, so act() falls back.
        if not matches and (proc.returncode == 0 or stdout.strip()):
            logger.warning(
                "BF-895: rg exited %s with %d output bytes but no parsable match under %s; "
                "falling back to the Python engine",
                proc.returncode, len(stdout), root,
            )
            return None
        return {
            "success": True,
            "data": matches,
>>>>>>> REPLACE

<<<<<<< SEARCH
def _parse_rg_line(line: str) -> dict | None:
    """Parse an ``rg --no-heading --line-number`` line: ``path:lineno:text``."""
    # Split only on the first two colons (paths/lines never contain them; text may).
    first = line.find(":")
    if first <= 0:
        return None
    second = line.find(":", first + 1)
    if second < 0:
        return None
    path = line[:first]
    lineno_str = line[first + 1:second]
    text = line[second + 1:]
    try:
        lineno = int(lineno_str)
    except ValueError:
        return None
    return {"path": path, "line": lineno, "text": text[:_LINE_PREVIEW_CHARS]}
=======
# BF-895 (#1548): ``path:lineno:text``. The path may hold colons (a Windows drive,
# ``\\?\C:\``), so the lazy path ends at the FIRST ``:<digits>:``; text holding ``12:``
# stays text. Limit: a path segment holding ``:<digits>:`` (POSIX only) is mis-split.
_RG_LINE = re.compile(r"(.+?):([0-9]+):(.*)", re.DOTALL)


def _parse_rg_line(line: str) -> dict | None:
    """Parse an ``rg --no-heading --line-number --with-filename`` line."""
    m = _RG_LINE.fullmatch(line)
    if m is None:
        return None
    return {"path": m.group(1), "line": int(m.group(2)), "text": m.group(3)[:_LINE_PREVIEW_CHARS]}
>>>>>>> REPLACE

## Section 2: `tests/test_bf895_rg_line_parse.py` (first build; superseded by Revision 1: the file was replaced by the 37-test version)

```python
"""BF-895 (#1548): the rg engine parses Windows paths and never reports a false zero."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from probos.agents import code_search
from probos.agents.code_search import CodeSearchAgent, _parse_rg_line

_RG = shutil.which("rg")
needs_rg = pytest.mark.skipif(_RG is None, reason="ripgrep (rg) is not on PATH")


@pytest.mark.parametrize("line, path, lineno, text", [
    (r"C:\tmp\f.txt:3:hello", r"C:\tmp\f.txt", 3, "hello"),
    (r"c:\Users\a b\x.py:12:def f(): pass", r"c:\Users\a b\x.py", 12, "def f(): pass"),
    (r"\\?\C:\long\f.txt:7:x", r"\\?\C:\long\f.txt", 7, "x"),
    (r"C:\tmp\f.txt:3:12:34 text", r"C:\tmp\f.txt", 3, "12:34 text"),
    (r"C:\tmp\f.txt:3:", r"C:\tmp\f.txt", 3, ""),
])
def test_drive_letter_lines_parse(line, path, lineno, text):
    assert _parse_rg_line(line) == {"path": path, "line": lineno, "text": text}


@pytest.mark.parametrize("line, path, lineno, text", [
    ("src/main.py:12:def foo():", "src/main.py", 12, "def foo():"),
    ("/tmp/f.txt:3:hello", "/tmp/f.txt", 3, "hello"),
    ("a.py:3:x = {1: 2}", "a.py", 3, "x = {1: 2}"),
    ("/tmp/f.txt:3:12:x", "/tmp/f.txt", 3, "12:x"),
    (r"\\server\share\f.txt:2:y", r"\\server\share\f.txt", 2, "y"),
    ("/tmp/a:b.txt:4:z", "/tmp/a:b.txt", 4, "z"),
])
def test_colon_free_and_posix_lines_parse(line, path, lineno, text):
    assert _parse_rg_line(line) == {"path": path, "line": lineno, "text": text}


@pytest.mark.parametrize("line", [
    "", "garbage", "a.py:notnum:text", "a.py:3", "3:hello", r"C:\tmp\f.txt:x:y",
])
def test_malformed_lines_are_dropped(line):
    assert _parse_rg_line(line) is None


def test_text_is_truncated_to_preview():
    parsed = _parse_rg_line("p.txt:1:" + "x" * 400)
    assert parsed is not None and len(parsed["text"]) == 300


class _FakeProc:
    def __init__(self, returncode: int, stdout: bytes) -> None:
        self.returncode = returncode
        self._stdout = stdout

    async def communicate(self):
        return self._stdout, b""


def _fake_rg(monkeypatch, returncode: int, stdout: bytes) -> list:
    seen: list = []

    async def fake_exec(*args, **kwargs):
        seen.append(args)
        return _FakeProc(returncode, stdout)

    monkeypatch.setattr(code_search.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(code_search, "_resolve_rg_binary", lambda: "rg")
    return seen


async def _run(root: Path, pattern: str) -> dict:
    agent = CodeSearchAgent(agent_id="bf895")
    plan = await agent.decide({"params": {"path": str(root), "pattern": pattern}})
    return await agent.act(plan)


def _tree(tmp_path: Path) -> Path:
    (tmp_path / "a.txt").write_text("one\nhello world\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("returncode, stdout", [
    (0, b"this is not an rg match line\n"),
    (0, b""),
    (1, b"stray output\n"),
])
async def test_unparsed_rg_output_falls_back_to_python(tmp_path, monkeypatch, returncode, stdout):
    seen = _fake_rg(monkeypatch, returncode, stdout)
    result = await _run(_tree(tmp_path), "hello")
    assert seen, "the fake rg was not launched"
    assert "--with-filename" in seen[0]
    assert result["engine"] == "python"
    assert result["success"] and result["count"] == 1


async def test_empty_rg_result_stays_a_zero_success(tmp_path, monkeypatch):
    _fake_rg(monkeypatch, 1, b"")
    result = await _run(_tree(tmp_path), "absent")
    assert result == {"success": True, "data": [], "count": 0, "engine": "rg", "truncated": False}


async def test_parsed_drive_letter_output_is_reported_by_rg(tmp_path, monkeypatch):
    _fake_rg(monkeypatch, 0, b"C:\\x\\a.txt:2:hello world\r\n")
    result = await _run(_tree(tmp_path), "hello")
    assert result["engine"] == "rg"
    assert result["data"] == [{"path": r"C:\x\a.txt", "line": 2, "text": "hello world"}]


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(p))


@needs_rg
@pytest.mark.parametrize("file_root", [False, True])
async def test_real_rg_matches_python_engine(tmp_path, file_root):
    root = _tree(tmp_path)
    (root / "b.txt").write_text("hello again\n12:hello in text\nnope\n", encoding="utf-8")
    target = root / "a.txt" if file_root else root
    agent = CodeSearchAgent(agent_id="bf895")
    plan = await agent.decide({"params": {"path": str(target), "pattern": "hello"}})
    via_rg = await agent._search_rg(_RG, plan, target)
    via_py = agent._search_python(plan, target)
    assert via_rg is not None and via_rg["engine"] == "rg"
    assert via_rg["count"] == via_py["count"] > 0
    assert sorted((_norm(m["path"]), m["line"]) for m in via_rg["data"]) == \
        sorted((_norm(m["path"]), m["line"]) for m in via_py["data"])
```

**Test premises (why each one fails before the fix):**
- `test_drive_letter_lines_parse`: the old parser returns `None` for every row, because the first colon is the drive's.
- `posix_lines[/tmp/a:b.txt]`: the old parser returns `None`. The other rows in that test are controls that pass before and after.
- `test_malformed_lines_are_dropped`: these are controls. `3:hello` is the file-root shape without a path.
- Fallback rows:
  - The old code returns `engine: "rg", count: 0`.
  - The old argv lacks `--with-filename`.
  - Row `(1, b"stray output")` pins the "or output" half of the condition.
- `test_empty_rg_result_stays_a_zero_success` is a control: it passes before and after.
- `test_parsed_drive_letter_output_is_reported_by_rg`: the old parser drops the line, so the result is `count: 0`.
- `test_real_rg_matches_python_engine`:
  - Before the fix, on Windows, the directory row gets `rg count 0 != python 3`.
  - Before the fix, on any OS, the `file_root` row breaks: rg prints `2:hello world` with no path, so the count is 0.
  - On Linux the directory row is a control.

**What the Linux CI job cannot prove:**
- The real Windows `C:\` output. `ci.yml` installs no ripgrep, so both real-rg rows may skip there.
- Linux CI still proves:
  - the parser rows, using literal Windows strings;
  - the fallback and the empty control, using a faked subprocess;
  - that `--with-filename` is in argv.
- The Windows proof is the local focused run on the Captain's machine, where ripgrep 15.2.0 is installed. Record the pass or skip lines in the build report.

**Focused gate:** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf895_rg_line_parse.py tests/test_ad989_code_search.py tests/test_bf892_spawn_env_guard.py tests/test_ad1025b_path_anchoring.py -q -n 0`

## Mutation table, first build (superseded by Revision 1; kept as history)

| # | File | Anchor line | Mutant | Killed by |
|---|---|---|---|---|
| 1 | code_search.py | `_RG_LINE = re.compile(r"(.+?):([0-9]+):(.*)", re.DOTALL)` | `(.+?)` → `([^:]+)` | drive_letter[*]; posix[`/tmp/a:b.txt`] |
| 2 | same line | | `(.+?)` → `(.+)` (greedy) | drive_letter[`12:34 text`]; posix[`/tmp/f.txt:3:12:x`] |
| 3 | same line | | `([0-9]+)` → `([^:]+)` | malformed[`a.py:notnum:text`] (ValueError in `int`, so the test errors) |
| 4 | same line | | drop `, re.DOTALL` | none: `splitlines` leaves no newline; equivalent, record as such |
| 5 | code_search.py | `    m = _RG_LINE.fullmatch(line)` | `fullmatch` → `search` | none: the pattern already spans the line; equivalent, record as such |
| 6 | code_search.py | `    return {"path": m.group(1), "line": int(m.group(2)), "text": m.group(3)[:_LINE_PREVIEW_CHARS]}` | drop `[:_LINE_PREVIEW_CHARS]` | test_text_is_truncated_to_preview |
| 7 | code_search.py | `        if not matches and (proc.returncode == 0 or stdout.strip()):` | `if False:` | fallback[*] |
| 8 | same line | | drop `proc.returncode == 0 or` | fallback[`(0, b"")`] |
| 9 | same line | | drop `or stdout.strip()` | fallback[`(1, b"stray output")`] |
| 10 | same line | | drop `not matches and` | parsed_drive_letter (falls back to python, so engine != "rg"); empty control unaffected |
| 11 | code_search.py | `        args = [rg, "--line-number", "--with-filename", "--no-heading",` | drop `"--with-filename", ` | fallback[*] argv assertion; real_rg[file_root=True] |

## Mutation table (Revision 1; single-line anchors; CRLF tree; one campaign on the frozen candidate)

Rows 1-11 above are void: `_RG_LINE` and its `fullmatch` and `return` lines are gone. N1 to N16 are the Architect's; N18 to N21 are the orchestrator's (analogues of the first build's rows 12 to 15). N17, the AD-989 pin, is a test edit and not a mutant. Acceptance 3: the campaign kills every row except N5, which is equivalent.

| # | File | Anchor | Replacement | Expected killer |
|---|---|---|---|---|
| N1 | code_search.py | `args = [rg, "--line-number", "--with-filename", "--null", "--no-heading",` | `args = [rg, "--line-number", "--null", "--no-heading",` | fallback argv assertion; real_rg[file_root=True]; numeric_stream |
| N2 | same line | | `args = [rg, "--line-number", "--with-filename", "--no-heading",` | fallback argv assertion; real_rg (no NUL, so None); numeric_stream |
| N3 | code_search.py | `path, sep, rest = line.partition("\x00")` | `path, sep, rest = line.rpartition("\x00")` | posix[`3:x<NUL>y`] |
| N4 | code_search.py | `if not sep or not path:` | `if not sep:` | malformed[`<NUL>3:x`] |
| N5 | same line | | `if not path:` | none: with no NUL, `rest` is empty and the second partition rejects it. Equivalent |
| N6 | code_search.py | `lineno, sep, text = rest.partition(":")` | `lineno, sep, text = rest.rpartition(":")` | windows[`3:12:34 text`]; posix[`3:12:x`] |
| N7 | code_search.py | `if not sep or not (lineno.isascii() and lineno.isdigit()):` | `if not (lineno.isascii() and lineno.isdigit()):` | malformed[`a.py<NUL>3`] |
| N8 | same line | | `if not sep or not (lineno.isdigit()):` | malformed[`\u0663:x`] |
| N9 | same line | | `if not sep or not (lineno.isascii()):` | malformed[`+3:x`] |
| N10 | code_search.py | `except ValueError:  # over Python's int() digit limit: not a line number` | `except TypeError:  # over Python's int() digit limit: not a line number` | oversized_is_unparsed; oversized_line_number_field_from_rg_config |
| N11 | code_search.py | `return {"path": path, "line": number, "text": text[:_LINE_PREVIEW_CHARS]}` | `return {"path": path, "line": number, "text": text}` | test_text_is_truncated_to_preview |
| N12 | code_search.py | `if not matches and (proc.returncode == 0 or stdout):` | `if False:` | fallback[*] |
| N13 | same line | | `if not matches and (stdout):` | fallback[(0, empty)] |
| N14 | same line | | `if not matches and (proc.returncode == 0):` | fallback[(1, stray); (1, whitespace)] |
| N15 | same line | | `if (proc.returncode == 0 or stdout):` | parsed_drive_letter (engine becomes python) |
| N16 | same line | | `if not matches and (proc.returncode == 0 or stdout.strip()):` | fallback[(1, whitespace)] |
| N18 | same line | | `if not matches and (proc.returncode != 0 or stdout):` | fallback[(0, empty)]; empty_rg_result_stays_zero |
| N19 | code_search.py | `proc.returncode, len(stdout), root,` | `proc.returncode, len(stdout), stdout,` | fallback_warning content test |
| N20 | code_search.py | `return {"path": path, "line": number, "text": text[:_LINE_PREVIEW_CHARS]}` | `return {"path": path, "line": number + 1, "text": text[:_LINE_PREVIEW_CHARS]}` | parse rows; real_rg comparison |
| N21 | same line | | `return {"path": text, "line": number, "text": path[:_LINE_PREVIEW_CHARS]}` | parse rows |

## Do not build
- Any change to `_search_python`, the timeout or the existing rg arguments (only `--with-filename` and `--null` are added).
- `rg --json` (rejected; see the verdict).
- Moving the launch out of `_search_rg` or adding a second launch (guard row :86).
- Detecting partial drops (some lines parsed, others not); see follow-up 2.

## Acceptance
1. A real rg match on Windows is reported with its path and line, and the count equals the Python engine's for the same query (`test_real_rg_matches_python_engine`, directory and file root, run locally on Windows).
2. A POSIX line and a path without a colon parse as before; a path holding `:<digits>:` (a POSIX segment, an NTFS stream file root) parses exactly. A malformed line is still dropped. If rg exits 0 or prints any byte but nothing parses, the search falls back to the Python engine. Exit 1 with no output stays `success`, `count: 0`, `engine: "rg"`.
3. The focused gate is green. The mutation campaign kills every Revision 1 row except N5, which is recorded as equivalent.
4. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**Tracking:** a BF-895 entry in `PROGRESS.md` and a short `DECISIONS.md` entry (the rg argument and the fallback are design decisions). No Bug Tracker row: that table in `docs/development/roadmap.md` lists only bugs "filed but deliberately not fixed", and this one is fixed here (the contract as drafted asked for a row and no `DECISIONS.md` entry; the orchestrator changed both when installing it).

## Prior Art and Blind Spots
- Prior art: ripgrep's flag docs (`crates/core/flags/defs.rs`, WithFilename/WithFilenameNo; `-0/--null`) and its `--json` format. JSON was considered and rejected (a new event format). The first build's colon regex plus `--with-filename` was shown by review round 1 not to cover every path shape (an NTFS stream file root), so `--null` was adopted: a long-standing flag that makes the path/line split exact without a new output format.
- Blind spot found: the single-file root dropped the path on every OS. This was not in the issue; `--with-filename` fixes it.
- Blind spot left: the two engines differ in what they search.
  - rg does not skip lines over 2000 bytes; `_search_python` does (:234).
  - `--max-count` limits matches per file, not in total; the caller caps the total.
  - Ignore rules differ (`.gitignore` inside git repos versus `iter_files` default ignores).
  - These are pre-existing and out of scope (follow-up 3).

## Follow-ups (with reach)
1. ~~`rg --json`~~: withdrawn. Its trigger, the colon-segment limit, no longer exists: `--null` closes it (and F-71 on #1523).
2. **Detect a partial drop**: count output lines against parsed lines, and fall back when any line is unparsed. Reach: `_search_rg`; small. Defer until a real case shows up. With `--null`, a line without a NUL is by definition unparsed, which makes this check sharper.
3. **Engine parity**: long-line skip, ignore rules, the per-file `--max-count` semantics and lone-`\r` line numbering. One AD that compares the two engines on a fixture tree. Reach: `_search_rg`, `_search_python`, `substrate/file_walk.py`.
4. **`splitlines()` on rg's output** (narrowed by `--null`): it may cut a match's preview text at `\x0c`, `\x85` or `\u2028`; the fragment has no NUL, so it can no longer become a false match. Reach: `_search_rg` preview text.
