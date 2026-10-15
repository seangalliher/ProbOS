# Build contract: BF-895 (#1548): the rg engine parses Windows paths and never reports a false zero

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-15
**Status:** built as one slice (2026-10-15) · **Depends on:** none (`agents/code_search.py` and its tests as on `main` `f2a0db6d`; unchanged on `579b5530`, where it was built) · **New tests:** 26 collected, in one new file (24 run everywhere; the two real-rg cases skip when `rg` is not on PATH). The contract's 25 plus one the orchestrator added: the fallback warning carries the exit code, a byte count and the root, and never match text.

**Verdict: build it.** Three changes in one file:

1. **Parser.** `_parse_rg_line` uses a lazy regex, `(.+?):([0-9]+):(.*)` with `fullmatch`. The path is everything up to the FIRST `:<digits>:`. This handles a Windows drive (`C:\`), `\\?\C:\` long paths, UNC paths, a POSIX filename that contains a colon (`/tmp/a:b.txt`), and match text that itself starts `12:`.
   - What it cannot parse: a path segment that contains `:<digits>:` (POSIX only, since Windows names cannot hold `:`). That line is split at the wrong place: the path is cut short, and the line number is taken from inside the name.
   - Rejected alternatives:
     - **`rg --json`** would replace the whole output format and add `begin`/`end`/`summary`/`context` event handling plus base64 decoding of `path.bytes` and `lines.bytes`. That is a larger change to fix one line shape.
     - **The anchored drive-letter regex** (`^((?:[A-Za-z]:)?[^:]*):…`) drops `\\?\C:\…` paths and every POSIX filename that contains a colon.
2. **One rg argument is added: `--with-filename`.**
   - The issue's "no change to the rg arguments" yields for this one flag. ripgrep's docs say it never prints the path "when ripgrep is explicitly instructed to search one file", and `act` accepts a file root (`_search_python` handles `root.is_file()`, code_search.py:222). So a file root returns `3:hello`, which has no path and can never satisfy acceptance (1).
   - The flag adds an argument and changes no existing one; the timeout is untouched.
   - The spawn-env guard counts launches per function, not argv, so its inventory does not change.
3. **No false zero.** If rg exits 0 (which means it found a match) or prints anything, and nothing parsed, `_search_rg` logs a warning and returns `None`. `act` then falls back to the Python engine (code_search.py:153-156).
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
| `tests/test_ad989_code_search.py:166-173` `test_parse_rg_line` | asserts `src/main.py:12:…`, `a.py:3:x = {1: 2}` text, `garbage` → None, `a.py:notnum:text` → None | all four still hold under the regex; do not edit it |
| `tests/test_ad989_code_search.py:18-24` autouse fixture forces the Python engine | none of its tests reach `_search_rg` | unchanged; the new tests live in a new file without that fixture |
| `tests/test_bf892_spawn_env_guard.py:86` keys `CodeSearchAgent._search_rg` with 1 launch | moving the launch or adding a second one breaks the inventory | keep the single `create_subprocess_exec` inside `_search_rg`; adding an argument is safe |
| `tests/test_ad1025b_path_anchoring.py:94-125` patches `_resolve_rg_binary`/`shutil.which` | binary resolution only | untouched |

## Section 1: `src/probos/agents/code_search.py`

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

## Section 2: `tests/test_bf895_rg_line_parse.py` (new, whole file)

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

## Mutation table (single-line anchors; CRLF tree; one campaign on the frozen candidate)

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

## Do not build
- Any change to `_search_python`, the timeout or the existing rg arguments (only `--with-filename` is added).
- `rg --json` (see the verdict; it is follow-up 1 if the colon-segment limit ever bites).
- Moving the launch out of `_search_rg` or adding a second launch (guard row :86).
- Edits to `tests/test_ad989_code_search.py` (its parser assertions still hold).
- Detecting partial drops (some lines parsed, others not); see follow-up 2.

## Acceptance
1. A real rg match on Windows is reported with its path and line, and the count equals the Python engine's for the same query (`test_real_rg_matches_python_engine`, directory and file root, run locally on Windows).
2. A POSIX line and a path without a colon parse as before. A malformed line is still dropped. If rg exits 0 or prints output but nothing parses, the search falls back to the Python engine. Exit 1 with no output stays `success`, `count: 0`, `engine: "rg"`.
3. The focused gate is green. The mutation campaign kills 1-3 and 6-11; 4 and 5 are recorded as equivalent.
4. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

**Tracking:** a BF-895 entry in `PROGRESS.md` and a short `DECISIONS.md` entry (the rg argument and the fallback are design decisions). No Bug Tracker row: that table in `docs/development/roadmap.md` lists only bugs "filed but deliberately not fixed", and this one is fixed here (the contract as drafted asked for a row and no `DECISIONS.md` entry; the orchestrator changed both when installing it).

## Prior Art and Blind Spots
- Prior art: ripgrep's flag docs (`crates/core/flags/defs.rs`, WithFilename/WithFilenameNo) and its `--json` format. JSON was considered and deferred, because the regex plus `--with-filename` covers every path shape `resolve_for_runtime` can produce on the supported platforms.
- Blind spot found: the single-file root dropped the path on every OS. This was not in the issue; `--with-filename` fixes it.
- Blind spot left: the two engines differ in what they search.
  - rg does not skip lines over 2000 bytes; `_search_python` does (:234).
  - `--max-count` limits matches per file, not in total; the caller caps the total.
  - Ignore rules differ (`.gitignore` inside git repos versus `iter_files` default ignores).
  - These are pre-existing and out of scope (follow-up 3).

## Follow-ups (with reach)
1. **`rg --json`**: only if a POSIX path segment containing `:<digits>:` is ever observed. Reach: `_search_rg` only.
2. **Detect a partial drop**: count output lines against parsed lines, and fall back when any line is unparsed. Reach: `_search_rg`; small. Defer until a real case shows up.
3. **Engine parity**: long-line skip, ignore rules and the per-file `--max-count` semantics. One AD that compares the two engines on a fixture tree. Reach: `_search_rg`, `_search_python`, `substrate/file_walk.py`.
