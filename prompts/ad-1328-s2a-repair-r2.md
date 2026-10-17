# AD-1328 S2a repair r2 -- review round 2: PATHEXT read verbatim or not at all, a name the shell runs itself never proves a pin, B22 without path assumptions, and S1 r3's four amendments

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Status:** BUILD-READY, built on the **replayed** stack: S2a replayed onto the final S1 commit first (S1 r3; `logs/architect/s2a-replay-amendments.md`), then this contract. Amends `prompts/ad-1328-s2a-repair-r1.md` and `prompts/ad-1328-s2a-command-policy-wiring.md` (see "Amendments"). Every SEARCH below was read from the staged file and occurs once in it. No new AD or BF number (#1530).
**Dependencies:** the frozen r1 candidate (staged, base `e5dc1000`); S1 r3's public API by name only, plus S1's texts `_pin_violation` (`"rule {name!r} allows {program} only at {paths}; {why}"`, alternative `"run the pinned executable: {paths}"`) and `SelfTestFailure.message` for `host_executable`, which B33 and the rewritten B22 read.
**Estimated tests:** about +75 cases (gate about 30 with the name lists iterated inside tests, tool and executor 6, agents and doctor 5, real shells 8 on Windows); 4 existing tests edited (Part A).

Verified against (staged blobs, `git ls-files -s`; `git diff` empty, so the worktree equals the index):

| File | Blob |
|---|---|
| `src/probos/execution/command_gate.py` | `90acdfffc74efa120334cfa274ce09925e2279ad` |
| `src/probos/doctor/checks/command_policy_check.py` | `02f1123810f8f7e17cb5dcad2857a698f0ea6ed2` |
| `src/probos/cognitive/swe_harness/tools.py` | `7d46d8d12f593977f80700e953398180dcad2fd9` (read, not changed) |
| `src/probos/agents/shell_command.py` | `f41ada1415d0fcc779d6a90310d212d88c54823c` (read, not changed) |
| `src/probos/agents/red_team.py` | `f8646143286b2a9990efefd6316916d2f62959b2` (read, not changed) |
| `src/probos/tools/executor.py` | `a2b74e528a51dc805aeb5fc8b637875e1719cd54` (read, not changed) |
| `DECISIONS.md` | `f053701eb41d181804816a70ed056185345e5f39` |
| `tests/test_ad1328_s2a_gate.py` | `5fe687268311b135bac73ca0a0f96f2668acda24` |
| `tests/test_ad1328_s2a_run_command_tool.py` | `2063c9c5c06951d42607f4b2fefa996c051d8c5a` |
| `tests/test_ad1328_s2a_shell_agent.py` | `2b813c735338162eb05b1c44350748b3c3a7e64f` |
| `tests/test_ad1328_s2a_startup_and_doctor.py` | `ebb0af8ddb20141bfd303be16369faa2e8c6a626` |
| `tests/test_ad1328_s2a_r1_real_shells.py` | `32a42727576fd34433702676d4954041b76bdc0d` |

The S2a-owned files do not change in the replay, so these blobs hold after it. If a blob differs, re-grep each SEARCH before installing.

## Problem

GPT-6.1 Sol, round 2 (delta of r1) on staged tree `d2a1bbdb` (`logs/architect/ad1328-s2a-review-r2-report.md`). REQUEST CHANGES, three findings; the orchestrator reproduced all three with the real gate and real `cmd.exe` (`logs/architect/s2a-review2-evidence/probe_s2a_r2_f1f2.py`).

| F | Reach | What is wrong | Where |
|---|---|---|---|
| F1 (P1, regression) | ordinary | `_pathext` strips each entry. With `PATHEXT='.EXE; .CMD;.BAT'` or `'.EXE;.CMD ;.BAT'` and a rule pinned to `tool.cmd`, `judge` allows the bare `tool`, but `cmd.exe` keeps the blank (` .CMD` is another extension), so `tool.cmd` is no candidate and it runs `tool.bat`. Controls: `.EXE;.CMD;.BAT` allows and runs CMD; `.COM;.EXE;.BAT;.CMD` refuses and cmd runs BAT. r1 had returned `forbid` for both forms | `command_gate.py:135-143` |
| F2 (P1, not a regression) | ordinary | A file lookup is taken as proof of what a shell runs for a name it runs itself. A rule `echo` pinned to `<d1>\echo.cmd`: the gate allows the bare `echo`, cmd runs its internal `echo` (`ECHO is on.`); the written path runs the file. POSIX shells: `echo`, `printf`, `test`, `[`, `kill`, `pwd`, `type`... are built-ins that outrank the file `which` names (Git `sh` confirmed by the reviewer). PowerShell never answers (r1), so it is safe | `command_gate.py:146-163`, `:199-205` |
| F3 (P2, regression) | ordinary | B22 fails when pytest's temp directory is long or holds a blank: its own `assert " " not in pin` (`test_ad1328_s2a_r1_real_shells.py:193`), the whole escaped path asserted inside a refusal the gate caps at 300 characters per cause (`command_gate.py:90`, `:247-249`; `:214-215`), and an unquoted written PowerShell path (`:227`). Reproduced with a 167-character `--basetemp` holding blanks: 1 failed, 9 passed | `test_ad1328_s2a_r1_real_shells.py:182-229` |

## Decisions

**D-s2a-r2-1 PATHEXT (F1).** Ranked:

| Option | Correct | Safe | Usable | Testable |
|---|---|---|---|---|
| (a) one grammar for the whole value, nothing stripped or skipped; anything else answers None | yes: every value it accepts is one cmd reads as written (no blank, no empty entry), so the model and cmd agree by construction | yes: a refusal names the pinned path | default and installer-extended PATHEXTs (`.COM;.EXE;...;.PY;.PYW`) fit it | one regex, rows per character class |
| (b) model cmd's literal reading of blanks, empty entries, quotes | only as far as measured; each unmeasured form is a new finding | no until measured | marginally more | needs a real-shell row per form |

**Decided: (a).** `_PATHEXT_GRAMMAR = \.[A-Za-z0-9]{1,15}(?:;\.[A-Za-z0-9]{1,15}){0,63}`, matched with `fullmatch` against the child's value, ASCII classes only. The class, and what the resolver returns:

| Value form | Answer | Why |
|---|---|---|
| `.EXE;.CMD;.BAT`; any case (`.exe;.Cmd`) | extensions upper-cased, in order | Windows file names compare case-insensitively; r1's behaviour |
| duplicates (`.CMD;.CMD;.BAT`) | accepted, in order | a repeated extension cannot change which file is found first |
| a blank or tab anywhere (`'.EXE; .CMD'`, `'.CMD ;'`, `'.E XE'`), a newline | None | cmd keeps it as part of the extension (F1, measured); not modelled |
| an empty entry: `;;`, leading or trailing `;`, `''` | None | not measured; r1 skipped it (an unproven guess) |
| quotes, `%`, `*`, `_`, any non-ASCII letter or digit (`.ÉXE`, fullwidth) | None | cmd's reading is not modelled; `str.isalnum` accepted non-ASCII in r1 |
| a bare `.`, an entry without the leading `.` (`COM;.EXE`) | None | as r1 |
| more than 64 entries, an entry longer than 15 characters after the `.` | None | bounds the probes (directories x extensions) a single judgement makes |
| missing or not an exact `str` | None | as r1 |

Cost: a host whose PATHEXT has a trailing `;` or a blank gets refusals for every **bare** pinned program under `cmd`, each naming the path to write; nothing else changes. Measurement M1 below checks the Captain's host.

**D-s2a-r2-2 A name the serving shell runs itself never proves (F2).** One rule, at the one producer (`make_program_resolver`): **the resolver answers None for a bare name that the serving shell runs itself before any file.** Per dialect:
- **PowerShell:** already never answers (r1; aliases, functions, cmdlets).
- **cmd:** `_is_cmd_internal(name)`. The name's leading ASCII letters, lower-cased, are one of cmd's internal commands, and the next character, if any, is not a letter or digit. That is S1's own reading of a program word cmd may split (`command_policy.py:1278-1280`; S1 already refuses such a word as unparseable, so through the gate only the exact names reach the resolver). The list `_CMD_INTERNAL_COMMANDS` holds the 45 names of S1's private `_CMD_INTERNAL` (`command_policy.py:124-129`). **Local list, not an S1 export:** S1 is frozen, and an export costs an S1 review round. A src import of a private name is forbidden, but a test may read one, so B26 pins `command_gate._CMD_INTERNAL_COMMANDS == command_policy._CMD_INTERNAL` and an S1 addition fails loudly. Source: Microsoft's `cmd` reference lists no internal set (fetched; it names only the extension-affected commands), so S1's reviewed list is the source of record. The replay needs nothing; review round 3 checks the equality test. Considered and deferred: a public S1 export, the next time S1 is opened.
- **posix (`/bin/sh`: dash, bash as `sh`, BusyBox ash):** `name in _POSIX_SHELL_BUILTINS`, exact case. That is 96 names:
  - POSIX.1-2024's 15 special built-ins (step 1a of 2.9.1.4; 2.15);
  - its 16 intrinsic utilities (1.7: `alias bg cd command fc fg getopts hash jobs kill read type ulimit umask unalias wait`);
  - the 55 names whose result POSIX leaves unspecified (2.9.1.4 step 1b: `alloc` ... `whence`);
  - dash's other built-ins (`true false echo printf pwd test [`);
  - bash's `enable`, `compopt`;
  - BusyBox ash's `[[`.

  POSIX 2.9.1.4 step 1e also lets a shell run a built-in in place of the PATH file. A bare name is never searched when it holds a `/` (S1 `_is_path`).

What it costs and what it does not touch:
- **Answer and exits.** The answer is None, so a pinned `allow` refuses with S1's `"run the pinned executable: <paths>"`, and the **written** absolute path still proves. The shell agent, the red team, the tool and preflight all inherit it: each calls `CommandPolicyGate.judge`, the resolver's one caller (Absence A1).
- **Cost to an operator who pins `/bin/echo` for the rule `echo`.** The bare `echo` never proves; `/bin/echo hi` does. The canonical key of the bare form becomes `echo` (S1 `_canonical_program` falls back to the name), and the written form's is `/bin/echo`. The two run different implementations, so S2b's approval reuse no longer conflates them (H11).
- **A command written as `echo.cmd` or `echo.exe`.** Under `cmd`, S1 refuses the word as unparseable: cmd reads `echo.` as its internal `echo` and prints `cmd`. The resolver also refuses, since `.` is in `_NOT_A_BARE_NAME`. Under posix it is another name, not a built-in, and `which` answers it as before. Under PowerShell there is still no answer.
- **What the list does not cover.** Functions and aliases cannot reach the child. A non-interactive `sh -c` reads no rc file, and `ENV`/`BASH_ENV` are not in the child's allowlist. `BASH_FUNC_*%%` fails the declared-name shape, so it cannot even be declared (`command_env.py:45-48`, `:62`). A `/bin/sh` that is zsh, or ksh93 with loaded built-ins, is outside the list. That is considered and deferred (Prior Art).

**D-s2a-r2-3 Tests (F3 and the reviewer's notes).**
- **B22**, rewritten (Part A), runs at two roots:
  - `plain`: `tmp_path`.
  - `long_spaced`: a directory under it holding a blank, whose path is at least 200 characters.
  - The root's helper skips only when the host's temp path leaves no room below a 240-character file path, or holds a character S1 refuses in a written program path. Both are honest environment limits, and the skip names them.
  - The refusal is asserted as a decision, no execution, and the **bounded** prefix the gate can show: `(<S1 cause text>)[:_MAX_REASON_CHARS]`.
  - The written PowerShell path is `& '<path>'`.
  - The same roots and rules apply to the new real-shell tests B34 and B35.
- **B16b:** the docstring takes the measured numbers: durable 3,903 bytes; 3,995 with the 1,898-character admitted maximum; about 100-190 bytes of headroom. New **B31** makes it a discriminating guard: the admitted maximum crosses the real executor into a real `EventLog` and stays whole.
- **The 19 survivors.**
  - Strengthen **B20**: two layouts where a `which`-style lookup and cmd disagree (`extensionless_d1_cmd_d2`, `proc_cwd_bat_d1_cmd`).
  - The rest stay controls, by design:
    - the four `judge` type guards (`test_r1_judge_takes_exactly_a_str`): S1 raises; the repair's property lives at the call sites, killed by B11b, B17 and B18;
    - exact-string identity (B11): `str(c) is c` for an exact `str`, equivalent by construction;
    - the grammar twin and accepted-shape rows (B8, B6 control);
    - the shell-agent guard (B18): no source change, a pin;
    - B16b: characterisation; B31 discriminates.
- **Cost notes, accepted and recorded, no change:**
  - Two child-environment builds per call with an active policy, against one. Sharing them changes `_policy_verdict`'s signature, which S2b anchors (H8).
  - JSON dumps go from 2 to 4 for a retained record: the 2,048-character check and the envelope budget.

**D-s2a-r2-4 S1 r3 amendments (H4-H7).**
- **H4:** Section 6, the doctor remediation text.
- **H5:** B33, other-platform pins under `win32` and `linux`, plus a host half through `ProbOSRuntime` and the registered doctor check.
- **H6:** B19. The comment now says what is true under r3, and a new assertion on the reason restores B19's discrimination of G12: under r3 the G12 mutant still refuses, because `/d1/tool.CMD` is not absolute under PowerShell, so the old B19 no longer told it apart.
- **H7:** B28, a segment with basis `unparseable` whose `matches` are not empty yields one rule cause and one unparseable cause, and the record projection accepts both. No S2a test assumes `matches == ()` (Absence A5).
- **M9:** already green (260).

**D-s2a-r2-5 Delivery.**
- Sections 1-7 are fenced pairs: `command_gate.py` (Sections 1-5), `command_policy_check.py` (6) and `DECISIONS.md` (7).
- Builders write tests only:
  - R2-M1: the gate.
  - R2-M2: the tool and executor.
  - R2-M3: agents, startup and doctor, and real shells.
- **S1 amendments: none. S2b: H8 extended (H11). Captain: none.** Every decision makes the gate prove less: it refuses more and widens nothing.

## Section 1 -- `src/probos/execution/command_gate.py` (module docstring)

SEARCH:
```python
command, computes its canonical approval key with the same memoised resolver (where the
child's shell finds a bare program name: ``cmd.exe`` its working directory, then PATH, in
PATHEXT order; ``/bin/sh`` PATH; PowerShell never, because it runs an alias, function or
cmdlet before any file -- see ``make_program_resolver``), and
```
REPLACE:
```python
command, computes its canonical approval key with the same memoised resolver (where the
child's shell finds a bare program name: ``cmd.exe`` its working directory, then PATH, in
PATHEXT order; ``/bin/sh`` PATH; PowerShell never, because it runs an alias, function or
cmdlet before any file; and never a name the shell runs itself, a ``cmd.exe`` internal
command or a ``/bin/sh`` built-in -- see ``make_program_resolver``), and
```

## Section 2 -- `src/probos/execution/command_gate.py` (PATHEXT grammar, the built-in lists, F1, F2)

SEARCH:
```python
_NOT_A_BARE_NAME: Final = frozenset('.\\/:"%*?<>|')


def _pathext(value: str | None) -> tuple[str, ...] | None:
    """The child's ``PATHEXT`` as ordered upper-case extensions; None when it is missing or
    holds an entry that is not '.' followed by letters or digits."""
    if type(value) is not str:
        return None
    entries = tuple(entry.strip().upper() for entry in value.split(";") if entry.strip())
    if not entries or any(len(entry) < 2 or entry[0] != "." or not entry[1:].isalnum() for entry in entries):
        return None
    return entries
```
REPLACE:
```python
_NOT_A_BARE_NAME: Final = frozenset('.\\/:"%*?<>|')
#: S2a repair r2 (review F1): the only PATHEXT the cmd lookup reads. Every entry is '.' then 1
#: to 15 ASCII letters or digits, ';'-separated, at most 64 entries. Nothing is stripped or
#: skipped: cmd keeps a blank as part of an extension (measured: with '.EXE; .CMD;.BAT' it ran
#: tool.bat beside tool.cmd), so a blank, an empty entry, a quote, a '%', a non-ASCII
#: character or an over-long value proves nothing.
_PATHEXT_GRAMMAR: Final = re.compile(r"\.[A-Za-z0-9]{1,15}(?:;\.[A-Za-z0-9]{1,15}){0,63}")
#: S2a repair r2 (review F2): cmd.exe's internal commands. For a bare name cmd runs one of these
#: itself, before any file of that name (measured: 'echo' with echo.cmd on PATH printed "ECHO
#: is on."). The names of S1's private ``command_policy._CMD_INTERNAL``; a test pins the
#: equality, so this module imports no private name.
_CMD_INTERNAL_COMMANDS: Final = frozenset({
    "assoc", "break", "call", "cd", "chdir", "cls", "color", "copy", "date", "del", "dir", "dpath", "echo",
    "endlocal", "erase", "exit", "for", "ftype", "goto", "if", "keys", "md", "mkdir", "mklink", "move", "path",
    "pause", "popd", "prompt", "pushd", "rd", "rem", "ren", "rename", "rmdir", "set", "setlocal", "shift", "start",
    "time", "title", "type", "ver", "verify", "vol",
})
_LEADING_LETTERS: Final = re.compile(r"[A-Za-z]+")
#: S2a repair r2 (review F2): what /bin/sh (dash, bash as sh, BusyBox ash) runs itself for a bare
#: name, before any PATH file: POSIX.1-2024's special built-ins (2.15) and intrinsic utilities
#: (1.7), the names whose result it leaves unspecified (2.9.1.4, step 1b), dash's and bash's
#: other built-ins, and ash's '[['. Exact case: these shells match a built-in's name exactly.
_POSIX_SHELL_BUILTINS: Final = frozenset({
    ".", ":", "[", "[[", "alias", "alloc", "autoload", "bg", "bind", "bindkey", "break", "builtin", "bye", "caller",
    "cap", "cd", "chdir", "clone", "command", "comparguments", "compcall", "compctl", "compdescribe", "compfiles",
    "compgen", "compgroups", "complete", "compopt", "compound", "compquote", "comptags", "comptry", "compvalues",
    "continue", "declare", "dirs", "disable", "disown", "dosh", "echo", "echotc", "echoti", "enable", "enum", "eval",
    "exec", "exit", "export", "false", "fc", "fg", "float", "getopts", "hash", "help", "hist", "history", "integer",
    "jobs", "kill", "let", "local", "login", "logout", "map", "mapfile", "nameref", "popd", "print", "printf", "pushd",
    "pwd", "read", "readarray", "readonly", "repeat", "return", "savehistory", "set", "shift", "shopt", "source",
    "stop", "suspend", "test", "times", "trap", "true", "type", "typeset", "ulimit", "umask", "unalias", "unset",
    "wait", "whence",
})


def _pathext(value: str | None) -> tuple[str, ...] | None:
    """The child's ``PATHEXT`` as ordered upper-case extensions; None unless the whole value is
    in ``_PATHEXT_GRAMMAR`` (S2a repair r2: nothing is stripped or skipped)."""
    if type(value) is not str or _PATHEXT_GRAMMAR.fullmatch(value) is None:
        return None
    return tuple(entry.upper() for entry in value.split(";"))


def _is_cmd_internal(name: str) -> bool:
    """Whether cmd.exe reads the bare word ``name`` as one of its internal commands: its
    leading letters name one, and the next character, if any, is not a letter or digit (the
    reading S1 refuses as a program word cmd may split, ``command_policy._cmd_program_problem``)."""
    head = _LEADING_LETTERS.match(name)
    if head is None or head.group().lower() not in _CMD_INTERNAL_COMMANDS:
        return False
    rest = name[head.end():]
    return not rest or not rest[0].isalnum()
```

## Section 3 -- `src/probos/execution/command_gate.py` (`_cmd_lookup`: an internal command proves nothing, F2)

SEARCH:
```python
    wins. None when that cannot be established."""
    if not name or any(char in _NOT_A_BARE_NAME for char in name):
        return None
```
REPLACE:
```python
    wins. None when that cannot be established, and for a name cmd runs as its own internal
    command before any file (S2a repair r2, review F2)."""
    if not name or any(char in _NOT_A_BARE_NAME for char in name):
        return None
    if _is_cmd_internal(name):
        return None  # cmd runs its internal command, never a file of that name
```

## Section 4 -- `src/probos/execution/command_gate.py` (`make_program_resolver` docstring)

SEARCH:
```python
    - ``posix``: ``which`` on ``search_path``; only an absolute answer counts (an empty or
      relative PATH entry is relative to a directory this lookup does not see).
    - ``cmd``: ``cwd`` -- or this process's directory, which a child given none inherits
      -- then each PATH entry; within a directory each ``PATHEXT`` extension in order; the
      first file wins. A name with an extension or a path, a missing or malformed
      ``PATHEXT``, and a relative, quoted or ``%`` entry reached before the answer prove
      nothing.
```
REPLACE:
```python
    - ``posix``: ``which`` on ``search_path``; only an absolute answer counts (an empty or
      relative PATH entry is relative to a directory this lookup does not see). A
      ``/bin/sh`` built-in (``_POSIX_SHELL_BUILTINS``) proves nothing: the shell runs it,
      not the file ``which`` names (S2a repair r2).
    - ``cmd``: ``cwd`` -- or this process's directory, which a child given none inherits
      -- then each PATH entry; within a directory each ``PATHEXT`` extension in order; the
      first file wins. A name with an extension or a path, a name cmd reads as an internal
      command (``_is_cmd_internal``), a ``PATHEXT`` outside ``_PATHEXT_GRAMMAR``, and a
      relative, quoted or ``%`` entry reached before the answer prove nothing.
```

## Section 5 -- `src/probos/execution/command_gate.py` (posix: a built-in proves nothing, F2)

SEARCH:
```python
        answer = which(name, path=search_path) if search_path else None
        return answer if type(answer) is str and posixpath.isabs(answer) else None
```
REPLACE:
```python
        if name in _POSIX_SHELL_BUILTINS:
            return None  # the shell runs its built-in, never the file which() names (S2a repair r2, review F2)
        answer = which(name, path=search_path) if search_path else None
        return answer if type(answer) is str and posixpath.isabs(answer) else None
```

## Section 6 -- `src/probos/doctor/checks/command_policy_check.py` (remediation, S1 r3 H4)

SEARCH:
```python
                    "Correct each named rule's pattern or example in execution.command_policy; "
                    f"ProbOS will not start until every example holds under {dialects}."
```
REPLACE:
```python
                    "Correct each named rule's pattern, example or host_executable path in execution.command_policy; "
                    f"ProbOS will not start until every rule's examples and pinned paths hold under {dialects}."
```

## Section 7 -- `DECISIONS.md` (the S2a entry, *Three call sites*)

SEARCH:
```markdown
PowerShell never, because it runs an alias, function or cmdlet before any file and a `.ps1` before PATHEXT files, so a pinned program is written as its path there (repair r1).
```
REPLACE:
```markdown
PowerShell never, because it runs an alias, function or cmdlet before any file and a `.ps1` before PATHEXT files, so a pinned program is written as its path there (repair r1). A name the serving shell runs itself never proves a pin either, so it too is written as its path: cmd's internal commands, and `/bin/sh`'s built-ins (POSIX's special built-ins and intrinsic utilities, the names POSIX leaves unspecified, dash's and bash's other built-ins). cmd's PATHEXT is read only when every entry is a `.` and 1-15 ASCII letters or digits, with no blank, empty entry, quote or `%`, because cmd keeps a blank as part of an extension and ran another file than a stripped reading named (repair r2).
```

## Tests

Rules as S2a and r1: never edit `src/`; spawns recorded by monkeypatching except in the real-shell file; gates built with explicit `platform=`, an injected `which` and an injected `is_file`. **Every test runs on the replayed stack (final S1 r3)**: B28, B33 and the rewritten B22 read S1 r3 behaviour. In every table cell, `\|` is a literal `|`.

### Part A -- existing tests that change

| File:line (blob above) | Change | Why |
|---|---|---|
| `test_ad1328_s2a_r1_real_shells.py:182-229` (B22) | Rewritten as specified under R2-M3 below: parametrized `nest` in `["plain", "long_spaced"]` over `_work_root`; the `" " not in pin` guard (`:193`) removed; `:214-215` replaced by the bounded assertion; `:225` replaced by the bounded alternative; `:227` written as `& '<pin>'` with an allow premise | F3 (one rule for the class: no assumption about the path's length or characters) |
| `test_ad1328_s2a_r1_real_shells.py:103-145` (B20) | Two layouts added. **`extensionless_d1_cmd_d2`**: files `d1/tool` (no extension, body `@echo EXTLESS`) and `d2/tool.cmd`, PATH `d1;d2`; the model names `d2\tool.CMD`; the extensionless file is written with `write_bytes` directly, not `_write_tool`, and skips the alone-control loop. **`proc_cwd_bat_d1_cmd`**: files `proc/tool.bat` and `d1/tool.cmd`, PATH `d1`; the test also takes `monkeypatch` and `monkeypatch.chdir(directories["proc"])` before both the lookup and `_run_cmd` (the child's `cwd` stays `directories["cwd"]`); the model names `d1\tool.CMD`. Add `"proc"` to the directory names. The third tuple element names the directory this process runs in (`"cwd"` for the seven existing layouts, meaning no chdir) | A `which`-style lookup (process `.` first; an extensionless file in an earlier directory) names another file than cmd runs in these two, so B20 now discriminates a reversion to `which` (review: B20's seven layouts survived it) |
| `test_ad1328_s2a_shell_agent.py:646` and after `:659` (B19, S1 r3 H6) | Comment becomes: `# what a posix lookup would answer; S1 r3 counts a pin only where it is absolute, never this one under cmd or PowerShell`. Add after `:659`: `assert "a program that does not resolve" in refused["error"]  # PowerShell's lookup answered nothing (a posix lookup would give '/d1/tool.CMD', refused as not absolute)` | Under r3 the G12 mutant refuses too (another reason), so only the reason tells it apart |
| `test_ad1328_s2a_run_command_tool.py:1448-1450` (B16b docstring) | Replace from `Measured 2026-10-16:` to `re-anchor B16 and B16b.` with: `Measured 2026-10-16 (review round 2): the durable envelope is 3,903 bytes with this record and ``'"' * 200`` provenance (``_bounded_text`` caps each string at 128 JSON bytes, so 63 quotes, the worst escaping case), and 3,995 bytes with the largest admitted record (1,898 characters) in its place (B31): about 100 to 190 bytes of headroom, not the 207 first stated. A record that grows (S2b's ``approval`` field, about 200 characters) fails B31 and may fail this test; S2b must re-measure and re-anchor B16, B16b and B31.` | Reviewer measurement replaces the author's claim |

No other existing test changes: no S2a test passes a PATHEXT outside the grammar except `malformed_pathext` (None before and after), pins a built-in name, asserts the doctor remediation phrase, or assumes `matches == ()` for an unparseable segment (Absence A2-A5). The posix canonical key of a bare built-in becomes its name: `test_allow_runs_once_and_records` (`test_ad1328_s2a_run_command_tool.py:345-347`) already expects that (`resolve_program=lambda name: None`).

### Part B -- new tests

**R2-M1, appended to `tests/test_ad1328_s2a_gate.py`:**

- **B23** `test_r2_cmd_pathext_grammar[...]`: `make_program_resolver(dialect="cmd", search_path="C:\\d1", cwd="C:\\work", pathext=<value>, which=_FakeWhich(fallback="C:\\fake\\tool.EXE"), is_file=_RecordingIsFile({"C:\\d1\\tool.CMD", "C:\\d1\\tool.BAT"}))("tool")`.
  - Refused, answer None and **no probe**:
    - `lead_blank` `.EXE; .CMD;.BAT`, `trail_blank` `.EXE;.CMD ;.BAT`, `inner_blank` `.E XE;.CMD`, `tab` `.EXE;\t.CMD`, `newline` `.EXE;.CMD\n`;
    - `empty_entry` `.EXE;;.CMD`, `leading_semicolon` `;.CMD`, `trailing_semicolon` `.CMD;`, `empty` `""`;
    - `bare_dot` `.EXE;.`, `quoted` `".CMD"`, `percent` `%PE%;.CMD`, `underscore` `.E_X;.CMD`;
    - `non_ascii` `.ÉXE;.CMD`, `fullwidth` `.ＣＭＤ`;
    - `entry_16_chars` `.ABCDEFGHIJKLMNOP;.CMD`;
    - `entries_65`: `";".join(f".E{i}" for i in range(64)) + ";.CMD"`.
  - Controls:
    - `plain` `.EXE;.CMD;.BAT` gives `C:\d1\tool.CMD`;
    - `lower_case` `.exe;.cmd` gives `C:\d1\tool.CMD` (probes upper-case);
    - `duplicates` `.CMD;.CMD;.BAT` gives `C:\d1\tool.CMD`;
    - `entries_64`: `";".join(f".E{i}" for i in range(63)) + ";.CMD"` gives `C:\d1\tool.CMD`;
    - `entry_15_chars` `.ABCDEFGHIJKLMNO;.BAT` gives `C:\d1\tool.BAT`.
  - `which.calls == []` in every row.
- **B24** `test_r2_cmd_internal_commands_never_answer`.
  - For every name in `sorted(command_gate._CMD_INTERNAL_COMMANDS)`, plus `ECHO`, `Echo`, `echo+x`, `echo,`, `echo=`, `echo(`, `echo[`: an `is_file` that answers True for `C:\d1\<name>.CMD`, with PATHEXT `.CMD` and PATH `C:\d1`, gives None with **no probe**.
  - Controls, each answering `C:\d1\<name>.CMD` after probing `C:\work\<name>.CMD` then it: `echo1`, `echoes`, `xecho`, `cdx`, `tool`.
  - Iterate inside one test, with the name in each assertion message.
- **B25** `test_r2_posix_builtins_never_answer`.
  - For every name in `sorted(command_gate._POSIX_SHELL_BUILTINS)`: `make_program_resolver(dialect="posix", search_path="/usr/bin", cwd=None, which=_FakeWhich(fallback="/usr/bin/x"))(name) is None`, and that `which` has `calls == []`.
  - Controls, each answering `/usr/bin/x` with one `which` call: `git`, `ECHO` (exact case), `echo.cmd`, `printf2`.
- **B26** `test_r2_builtin_lists_are_pinned`.
  - `command_gate._CMD_INTERNAL_COMMANDS == command_policy._CMD_INTERNAL` (`from probos.execution import command_policy`; reading S1's private name is allowed in a test; H9) and `len == 45`.
  - `command_gate._POSIX_SHELL_BUILTINS == frozenset({<the 96 names of Section 2, re-typed literally>})` and `len == 96`.
  - The POSIX special built-ins and intrinsic utilities are each a subset of it: `{"break", ":", "continue", ".", "eval", "exec", "exit", "export", "readonly", "return", "set", "shift", "times", "trap", "unset"}` and `{"alias", "bg", "cd", "command", "fc", "fg", "getopts", "hash", "jobs", "kill", "read", "type", "ulimit", "umask", "unalias", "wait"}`.
- **B27** `test_r2_a_pinned_builtin_name_never_proves[cmd, posix]`, through `CommandPolicyGate`, rule `echo-pinned` (`allow`, `["echo"]`), `unmatched="escalate"`:
  - `cmd`: `platform="win32"`, pin `C:\d1\echo.CMD`, `is_file` True for it, `judge(..., site="run_command_tool", search_path="C:\\d1", cwd="C:\\work", pathext=".CMD")`.
    - `echo hi` gives `forbid`, `runs is False`, and the refusal contains `run the pinned executable: C:\d1\echo.CMD`; `is_file.calls == []`.
    - Written `C:\d1\echo.CMD hi` gives `allow`. Both forms have `canonical.kind == "script"`: S1's `_is_simple` treats any cmd program whose stem is an internal name as a script (`command_policy.py:1887`).
  - `posix`: `platform="linux"`, pin `/bin/echo`, `which` answering `/bin/echo`.
    - `echo hi` at both sites gives `forbid` naming `/bin/echo`; `which.calls == []`; `canonical.parts[0] == "echo"`.
    - Written `/bin/echo hi` gives `allow` with `canonical.parts[0] == "/bin/echo"`, so the two keys differ.
  - Premise first in both: the gate builds (no self-test failure).
- **B28** `test_r2_unparseable_segment_with_matches_gives_both_causes` (S1 r3 H7). Linux gate, rules `no-tool` (`forbid`, `["tool"]`) and `no-curl` (`forbid`, `["curl"]`), `unmatched="allow"`; `judge("tool curl", site="run_command_tool", search_path="/usr/bin")`.
  - Premise (S1 r3): `segments[0].basis == "unparseable"` and `[m.rule for m in segments[0].matches] == ["no-tool"]`.
  - `decision == "forbid"`, and `[(c.kind, c.segment, c.rule) for c in verdict.causes] == [("rule", 0, "no-tool"), ("unparseable", 0, None)]`.
  - The refusal contains `Rule 'no-tool'` and `could not read part 1`.
  - `command_policy_record_of(ToolResult(metadata=policy_result_metadata(verdict)), tool_id=RUN_COMMAND_TOOL_ID)["causes"]` equals the two typed causes.
  - Control: `tool x` gives basis `rule` and one cause.

**R2-M2, appended to `tests/test_ad1328_s2a_run_command_tool.py`:**

- **B29** `test_r2_tool_reads_the_childs_pathext_verbatim[lead_blank, trail_blank, control]`.
  - Setup: `setenv("PATH", "C:\\d1")`, `setenv("PATHEXT", value)`, a tool built with `command_env_passthrough=("PATHEXT",)` (so the child carries PATHEXT on every host) and a win32 gate.
  - The rule `pinned-tool` is pinned to `C:\d1\tool.CMD`; `is_file` answers True for `C:\d1\tool.CMD` and `C:\d1\tool.BAT`.
  - `{"command": "tool", "working_directory": "C:\\work"}`:
    - `lead_blank` `.EXE; .CMD;.BAT` and `trail_blank` `.EXE;.CMD ;.BAT`: error set, decision `forbid`, no spawn;
    - `control` `.EXE;.CMD;.BAT`: one spawn, decision `allow`.
  - Premise: `build_command_env(("PATHEXT",))["PATHEXT"] == value`.
- **B30** `test_r2_tool_refuses_a_pinned_posix_builtin_bare`. Linux gate, rule `echo` pinned to `/bin/echo`, `which` answering `/bin/echo`:
  - `{"command": "echo hi"}`: error names `/bin/echo`, decision `forbid`, no spawn, `which.calls == []`.
  - `{"command": "/bin/echo hi"}`: one spawn of that same object, decision `allow`.
- **B31** `test_r2_the_largest_admitted_record_fits_the_real_envelope`. No patch.
  - The record: the B10 maximum, rebuilt here because tests do not import each other: 8 rule names of 64 characters; 8 `rule` causes with those names and segment `2**31-1`; both counts `2**31-1`; decision `escalate`, dialect `posix`, kind `script`, hex digests.
  - Premise: `command_policy_record_of` accepts it unchanged, and `len(json.dumps(record, sort_keys=True)) <= MAX_RECORD_CHARS`.
  - A `_StandInTool` with `tool_id = "run_command"` (B14's) returns `ToolResult(output={}, metadata={"command_policy": record})`, called with B16b's maximal provenance `q = '"' * 200`.
  - The emitted payload keeps `command_policy == record` (not compacted) with `_record_size <= 4096`.
  - Durable half as B16b, real `EventLog` in `tmp_path`: the persisted row keeps the same whole record, and its data has `_record_size <= 4096`.
  - Comment: `# measured by review round 2: 3,995 bytes durable (M4)`. If a premise or the bound fails, stop and report the sizes.

**R2-M3, agents and startup:**

- **B32**, appended to `tests/test_ad1328_s2a_shell_agent.py`: `test_r2_agents_refuse_a_pinned_posix_builtin_bare`. Linux gate (`CommandPolicyGate(config, platform="linux", which=<answers /bin/echo>, is_file=lambda path: False)`), rule `echo` pinned to `/bin/echo`.
  - `shell._run_command("echo hi")` is refused naming `/bin/echo`, and `runs.calls == []`.
  - `_verify(red_team, "echo hi", claimed_success=True)` gives `verified is False`, and `reruns.calls == []`.
  - Control: `/bin/echo hi` runs at both, `runs.commands == ["/bin/echo hi"]` and `reruns.commands == ["/bin/echo hi"]`.
- **B33**, appended to `tests/test_ad1328_s2a_startup_and_doctor.py`: `test_r2_a_rule_pinned_only_to_the_other_platform_stops_startup_and_fails_the_doctor[win32, linux]` (S1 r3 H5). Rule `pinned-git` (`allow`, `["git"]`) via the file's `_rule`. It is pinned to `["/usr/bin/git"]` under `win32` and to `["C:\\Git\\cmd\\git.exe"]` under `linux`.
  - With `policy = _config_with(rule).execution.command_policy`, `CommandPolicyGate(policy, platform=p, is_file=lambda path: False)` raises `CommandPolicySelfTestError`, and its text contains `'pinned-git'` and `host_executable <the pin>`.
  - `describe_command_policy(policy, platform=p)` has `passed is False`. Every failure has `expectation == "host_executable"`, one per serving dialect: `cmd` and `powershell` for `win32`, `posix` for `linux`.
  - Control: the same rule pinned to both paths builds under `p`, and its report passes.
  - Host half, once, outside the parametrization: with the pin for the platform this host is not, `ProbOSRuntime(config=..., data_dir=tmp_path / "pinned" / "data")` raises `CommandPolicySelfTestError`, and `tmp_path / "pinned"` does not exist. The registered doctor check gives `FAIL`; `host_executable` is in the message, and `"pattern, example or host_executable path"` and `", ".join(_HOST_DIALECTS)` are in the remediation.

**R2-M3, `tests/test_ad1328_s2a_r1_real_shells.py`** (Windows only, as r1; files only under `tmp_path`; every subprocess `timeout=60`). Add at module level:

```python
_POLICY_PATH = re.compile(r"[A-Za-z0-9_.+\\: -]+")  # the characters S1 reads in a written program path (cmd and PowerShell)
_MAX_FILE_PATH = 240  # below the 260 characters a cmd.exe working directory and its file names may take


def _work_root(tmp_path: Path, nest: str) -> Path:
    """``tmp_path`` (``plain``), or a directory under it with a blank whose path is at least 200 characters
    (``long_spaced``): the refusals then exceed the gate's 300-character cause bound. Skips when the host's temp
    path leaves no room, or holds a character the policy does not read in a written program path."""
    root = tmp_path
    if nest == "long_spaced":
        root = tmp_path / "with space"
        root = root / ("L" * max(1, 200 - len(str(root)) - 1))
    if len(str(root / "empty" / "tool.CMD")) > _MAX_FILE_PATH:
        pytest.skip(f"the temp path ({len(str(root))} characters) leaves no room under cmd.exe's path limit")
    if _POLICY_PATH.fullmatch(str(root)) is None:
        pytest.skip("the temp path holds a character the policy refuses in a written program path")
    root.mkdir(parents=True, exist_ok=True)
    return root
```

Import `re` and `from probos.execution.command_gate import _MAX_REASON_CHARS`.

- **B22**, rewritten (Part A), `test_r1_tool_and_agent_end_to_end[plain, long_spaced]`. `root = _work_root(tmp_path, nest)`; `d1 = root / "d1"`; `empty = root / "empty"`. In `long_spaced`, premise: `" " in str(root) and len(str(root)) >= 200`. PATH and PATHEXT as now, the rule as now, `pin = ntpath.join(str(d1), "tool.CMD")`.
  - (a) Unchanged.
  - (b) After planting `<empty>\tool.bat`:
    ```python
    named = ntpath.join(str(empty), "tool.BAT")
    cause = f"rule 'pinned-tool' allows tool only at {pin}; {named!r} is not one of them"
    assert refused.metadata["command_policy"]["decision"] == "forbid"
    assert cause[:_MAX_REASON_CHARS].lower() in refused.error.lower()  # the gate shows at most this much of a cause
    assert not (empty / "ran_bat").exists() and not (d1 / "ran_cmd").exists()
    ```
  - (c) Agent: `bare["success"] is False`, `f"run the pinned executable: {pin}"[:_MAX_REASON_CHARS].lower() in bare["error"].lower()`, and no `ran_ps1`. Written: `command = f"& '{pin}'"`. Premise: `gate.judge(command, site="shell_command_agent", search_path=os.environ["PATH"]).decision == "allow"`. Then `written = await agent._run_command(command)` succeeds with stdout `CMD`.
- **B34** `test_r2_cmd_keeps_a_blank_in_pathext[lead_blank, trail_blank] x [plain, long_spaced]`. `d1` holds `tool.cmd` and `tool.bat`, PATH `<d1>;System32`, `setenv("PATHEXT", value)`, the rule pinned to `<d1>\tool.CMD`, a real win32 gate and `RunCommandTool` with `working_directory=<empty>`.
  - Premise, the class measured: `subprocess.run("tool", shell=True, cwd=empty, env={SYSTEMROOT, PATH, PATHEXT: value}, ...)` prints `BAT`.
  - `make_program_resolver(dialect="cmd", search_path=PATH, cwd=str(empty), pathext=value)("tool") is None`.
  - The tool's call is refused (`forbid`), with neither `ran_bat` nor `ran_cmd`.
  - Control, same layout with `PATHEXT=.EXE;.CMD;.BAT`: `allow`, stdout `CMD`.
- **B35** `test_r2_cmd_runs_its_internal_command_not_the_pinned_file[plain, long_spaced]`. `d1/echo.cmd` (body `@echo off\r\necho CMD\r\necho ran> "%~dp0ran_cmd"\r\n`), PATH `<d1>;System32`, PATHEXT as the file's.
  - Premise: `subprocess.run("echo", shell=True, cwd=empty, env=..., ...)` prints something other than `CMD`, and `ran_cmd` is absent (the text of `ECHO is on.` is locale-dependent: do not assert it).
  - `make_program_resolver(dialect="cmd", ...)("echo") is None`.
  - The rule `echo-pinned` is pinned to `<d1>\echo.CMD`. The tool with `echo` gives `forbid`, and the refusal contains the bounded `f"run the pinned executable: {pin}"[:_MAX_REASON_CHARS]`.
  - Written `f'"{pin}"'`. Premise: the gate gives `allow`. The tool then runs it, with stdout `CMD`.

## Mutation campaign (rows added; anchors are single lines, unique after r2)

The campaign of record (52 of 52, r1) pinned the four S2a source files. After r2, `command_gate.py` changes:
- **Rerun every G row (G1-G38)** on the replayed r2 tree. G18 is re-anchored below; G15-G17 and G19 keep their anchors (unchanged lines).
- `tools.py`, `red_team.py` and `executor.py` do not change, so T1-T7, R1, R2 and X1-X5 stand as the campaign of record.
- Add the rows below.

| Id | File | Anchor | Mutant | Killer |
|---|---|---|---|---|
| G18 (re-anchored) | command_gate.py | `if type(value) is not str or _PATHEXT_GRAMMAR.fullmatch(value) is None:` | `if type(value) is not str:` | B23 `empty_entry`, `lead_blank`; B2 `malformed_pathext` |
| G39 | command_gate.py | `_PATHEXT_GRAMMAR: Final = re.compile(r"\.[A-Za-z0-9]{1,15}(?:;\.[A-Za-z0-9]{1,15}){0,63}")` | `_PATHEXT_GRAMMAR: Final = re.compile(r"\s*\.[A-Za-z0-9]{1,15}\s*(?:;\s*\.[A-Za-z0-9]{1,15}\s*){0,63}")` | B23 `lead_blank`, `trail_blank`; B29; B34 |
| G40 | command_gate.py | (G39's) | `{0,63}` -> `*` | B23 `entries_65` |
| G41 | command_gate.py | (G39's) | both `{1,15}` -> `+` | B23 `entry_16_chars` |
| G42 | command_gate.py | (G39's) | both `[A-Za-z0-9]` -> `\w` | B23 `underscore`, `non_ascii`, `fullwidth` |
| G43 | command_gate.py | `return tuple(entry.upper() for entry in value.split(";"))` | `return tuple(value.split(";"))` | B23 `lower_case` |
| G44 | command_gate.py | `if _is_cmd_internal(name):` | `if False:` | B24; B27 `cmd`; B35 |
| G45 | command_gate.py | `if head is None or head.group().lower() not in _CMD_INTERNAL_COMMANDS:` | `if head is None or head.group() not in _CMD_INTERNAL_COMMANDS:` | B24 `ECHO`, `Echo` |
| G46 | command_gate.py | `return not rest or not rest[0].isalnum()` | `return not rest` | B24 `echo+x`, `echo,` |
| G47 | command_gate.py | (G46's) | `return True` | B24 control `echo1` |
| G48 | command_gate.py | `"assoc", "break", "call", "cd", "chdir", "cls", "color", "copy", "date", "del", "dir", "dpath", "echo",` | drop `"echo",` | B26 (equality with S1) |
| G49 | command_gate.py | `if name in _POSIX_SHELL_BUILTINS:` | `if False:` | B25; B27 `posix`; B30; B32 |
| G50 | command_gate.py | (G49's) | `if name.lower() in _POSIX_SHELL_BUILTINS:` | B25 control `ECHO` |
| G51 | command_gate.py | `"continue", "declare", "dirs", "disable", "disown", "dosh", "echo", "echotc", "echoti", "enable", "enum", "eval",` | drop `"echo", ` | B26 (literal pin) |
| G52 | command_gate.py | `if verdict.decision != evaluation.decision or verdict.basis == "rule":` | `if verdict.decision != evaluation.decision or verdict.basis != "unmatched":` | B28 |
| D1 | command_policy_check.py | `"Correct each named rule's pattern, example or host_executable path in execution.command_policy; "` | `"Correct each named rule's pattern or example in execution.command_policy; "` | B33 host half |

The anchors are single lines. G39-G42 share one anchor and apply one mutant at a time. Equivalent mutants (not listed): `head.end()` -> `len(head.group())` (same value); reordering either built-in set. No mutant can loop: every loop iterates a finite tuple, list or string.

## Closure enumeration

| F | Producer, exit or consumer | Closed by |
|---|---|---|
| F1 | `_pathext`, the one producer of extensions (called only by `make_program_resolver`) | Section 2 (one grammar) |
| F1 | Exits: `judge` -> `RunCommandTool.invoke` and `command_policy_preflight` (both `_policy_verdict`, the only caller passing `pathext`, `tools.py:1157-1163`) | Section 2; B29 (tool), B34 (real) |
| F1 | Shell agent and red team (`shell_command.py:221`, `red_team.py:425`): no `pathext`; PowerShell and posix never read it | Holds |
| F1 | Value forms: blank or tab (leading, trailing, inner), newline, empty entry (`;;`, leading or trailing `;`, `""`), quote, `%`, `_`, non-ASCII, bare `.`, no leading `.`, over 64 entries, over 15 characters, missing, not a `str` | None (B23 rows) |
| F1 | Case, duplicates | Accepted; same first file (B23 controls) |
| F1 | Adjacent: a PATH entry with a trailing blank | Holds: `is_file` and cmd share Win32 path normalisation, and the returned path keeps the blank, so a pin compares unequal and refuses; a leading blank fails `_WINDOWS_ABSOLUTE` (None) |
| F2 | `make_program_resolver`, the one producer (Absence A1), per dialect: PowerShell (never, r1), cmd (`_is_cmd_internal`, Section 3), posix (`_POSIX_SHELL_BUILTINS`, Section 5) | Sections 2, 3, 5 |
| F2 | Consumers through `judge`: tool, preflight, shell agent, red team; S1's pin proof (`_allow_match`) and canonical key (`_canonical_program`) | B27, B30, B32, B35; the key of a bare built-in is its name |
| F2 | cmd forms: exact name, any case, internal followed by a non-alphanumeric (S1 refuses the word first), `echo.cmd` (S1 unparseable; `.` refused here), a quoted `"echo"` (refused: over-refusal, safe) | B24 |
| F2 | posix: functions, aliases, `ENV`/`BASH_ENV`, `BASH_FUNC_*` | Holds: none reaches a non-interactive `sh -c` with the child's allowlist (`command_env.py:28-48`); `BASH_FUNC_x%%` fails the name shape (`:62`) |
| F2 | posix: a `/bin/sh` that is zsh, or ksh93 with loaded built-ins | Recorded, not closed (Prior Art); the written path always proves |
| F3 | B22's three assumptions: a blank, the full path in a bounded refusal, the unquoted written path | Part A B22: `_work_root` plain and long-spaced, bounded prefixes, `& '<pin>'` |
| F3 | The same class in the new real-shell tests | B34 and B35 use `_work_root`, bounded prefixes and quoted written paths; B20 and B21 write no path into a command |
| H5 | A pin absolute only on the other platform: gate construction (startup) and doctor | B33 |
| H7 | `_causes` with basis `unparseable` and non-empty `matches` | B28 |

## Amendments (what r2 overrides)

| Earlier text | r2 |
|---|---|
| r1 D-s2a-1: "a missing or malformed `PATHEXT` ... An empty entry is skipped" (PATH); `_pathext` stripped and skipped PATHEXT entries | PATHEXT: one grammar, nothing stripped or skipped (D-s2a-r2-1). An empty PATH entry is still skipped (unchanged, B20 `d1_empty_d2_cmd`) |
| r1 D-s2a-1 *posix* keeps `which`, absolute answers only | Plus: a `/bin/sh` built-in never answers |
| r1 D-s2a-1 *cmd* model | Plus: an internal command never answers |
| r1 B16b docstring "about 207 bytes of headroom" | Measured: 3,903 and 3,995 bytes; about 100-190 bytes (Part A); B31 |
| r1 B19 comment "so a posix lookup would allow it" | False under S1 r3 (H6); restated, and a reason assertion added |
| r1 B22 | Rewritten (Part A) |
| Wiring prompt `:1133-1136` doctor remediation | Section 6 (S1 r3 H4) |
| r1 Hidden pin H8 (S2b re-anchor list) | Extended by H11 |

## Amendments after install

None yet. Amendments from S1 r3 (`prompts/ad-1328-s1-repair-r3.md` H4-H7, M9, in `logs/architect/s2a-replay-amendments.md`), all taken up here:

| Id | Taken up as |
|---|---|
| H4 | Section 6; B33's host half asserts the text |
| H5 | B33 |
| H6 | Part A, B19 |
| H7 | B28; Absence A5 |
| M9 | Already green (260); rerun after r2 as acceptance 2 |
| Replay notes 6-7 (S1 test conflicts, `operations.py` line shifts) | Replay only; this contract anchors no S1 file |

## Hidden pins (enumerated)

| Id | Pin | Effect |
|---|---|---|
| H1-H8 | r1's, as listed there | Unchanged except H8 (H11) |
| H9 | B26 reads S1's private `command_policy._CMD_INTERNAL` | A rename or addition in S1 fails B26 loudly; the fix is to update `_CMD_INTERNAL_COMMANDS` (or import a public export once S1 has one) |
| H10 | B22, B33 and B35 read S1 r3's texts (`_pin_violation`'s `"allows {program} only at {paths}; {why}"`, its alternative `"run the pinned executable: "`, `"a program that does not resolve"`, the `host_executable` failure message) | Valid on the replayed stack only; an S1 wording change re-anchors them |
| H11 | **S2b re-anchor list (adds to r1 H8)**. (1) `_pathext` returns None outside `_PATHEXT_GRAMMAR`. (2) The canonical key of a bare posix built-in is its name, not the `which` path, so approval reuse keys `echo` and `/bin/echo` apart; cmd internals were already `script`-kind. (3) B31 pins the admitted maximum at 3,995 of 4,096 bytes: S2b's `approval` field (about 200 characters) exceeds it, so S2b must re-measure B16, B16b and B31, and either raise the budget or rely on compaction, decided in S2b. (4) `CommandPolicyGate` and `judge` signatures are unchanged | S2b's prompt is not in this worktree, so its line anchors were not checked here |
| H12 | Architecture fitness (`scripts/check_architecture_principles.py`) | Two module functions (`_is_cmd_internal`, `_pathext`) and four constants only; `CommandPolicyGate` keeps 8 methods |
| H13 | S1 wiring scan `test_only_the_gate_constructs_the_policy` (spares `command_gate.py`'s imports from `command_policy`) | No new import from `command_policy` (the list is local) |

## What This Does NOT Change

S1 (`command_policy.py`, `operations.py`); `tools.py`, `red_team.py`, `shell_command.py`, `executor.py`; the record keys and schema; the refusal frames; the no-policy paths; the PowerShell branch; PATH-entry handling; preflight; the broker; the starter policy (no pins).

## Tracking

DECISIONS.md (Section 7). No PROGRESS or roadmap change (same AD, same PR).

## Acceptance Criteria

1. S2a is replayed onto the final S1 commit first; then Sections 1-7 install mechanically, and each SEARCH occurs exactly once.
2. Part A and Part B as written. The four S2a test files plus `tests/test_ad1328_s2a_r1_real_shells.py` pass at `-n 0` on Windows, also with `--basetemp` set to a path of about 170 characters holding blanks, and on Linux with the real-shell file skipped. Report every skip with its reason.
3. The orchestrator re-runs `logs/architect/s2a-review2-evidence/probe_s2a_r2_f1f2.py`. F1: both blank forms are refused, and the controls are unchanged. F2: the bare `echo` pinned to `echo.cmd` is refused, and the written path runs. F3: the `--basetemp` run above.
4. S2a's focused gate (wiring contract acceptance 8) and the seven `--check` scripts (acceptance 9) pass.
5. Every row above is killed, and G1-G38 are rerun on the r2 tree. Record the base commit and each changed file's sha256 as the campaign of record.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-10-16, blobs above; S1 = `D:\ProbOS-worktrees\ad1328-s1-26250c9c`, read only)

```
command_gate.py:16-19     module docstring resolver sentence                       (Section 1)
command_gate.py:132-143   _NOT_A_BARE_NAME; _pathext strips and skips entries        (Section 2; F1)
command_gate.py:146-153   _cmd_lookup docstring tail and the bare-name check         (Section 3)
command_gate.py:181-187   resolver docstring posix/cmd bullets                       (Section 4)
command_gate.py:199-205   lookup(): powershell None; cmd; posix which + isabs        (Section 5; F2)
command_gate.py:90, :247-249  _MAX_REASON_CHARS = 300; _sentence caps each cause      (F3)
command_gate.py:226-244   _causes: governing, then segments with basis != "rule"     (H7, G52)
command_gate.py:560-569   judge builds the resolver; evaluate and canonical share it
command_policy_check.py:44-47  remediation "pattern or example"                     (Section 6)
DECISIONS.md:29           the S2a "Three call sites" bullet                          (Section 7)
tools.py:1157-1163        _policy_verdict passes search_path, cwd, pathext=child_env PATHEXT
shell_command.py:221; red_team.py:425   judge(command, site="shell_command_agent", search_path=PATH)  (no pathext)
command_env.py:36-41, :45-48, :62, :98-111  allowlists (PATHEXT on win32; no ENV/BASH_ENV); name shape
S1 command_policy.py:124-129   _CMD_INTERNAL (45 names; same set at S2a's old copy :108-113)
S1 command_policy.py:103, :1272-1281  _LEADING_LETTERS; _cmd_program_problem (internal + non-alnum -> unparseable)
S1 command_policy.py:1056-1063, :1074-1077  _is_path; _is_absolute; _pin_keys (absolute under the dialect only)
S1 command_policy.py:1603-1646  _allow_match; _pin_violation texts ("allows ... only at ...; ...", "run the pinned executable: ...")
S1 command_policy.py:1688-1708  _judge: hidden program -> basis "unparseable" WITH matches (r3)
S1 command_policy.py:400-403, :406-419  governing; SelfTestFailure host_executable message
S1 command_policy.py:1878-1903  _is_simple (cmd internal -> script); _canonical_program falls back to the name
tests real_shells:32, :79-80, :103-145, :182-229   PATHEXT; _env; B20 layouts; B22
tests shell_agent:640-669   B19 (two pins, comment :646, assertion :659)
tests run_command_tool:1442-1450, :345-347   B16b docstring; resolver-None canonical expectation
tests startup:62, :69, :89-113, :339-371, :635-698   _HOST_DIALECTS; _rule; _config_with; runtime/doctor tests
tests gate:59, :1059-1136, :1158-1196, :405-434   _MAX_REASON_CHARS import; B2; B4/B5; _FakeWhich calls (name, path)
POSIX.1-2024 XCU 2.9.1.4 (steps 1a-1e), 2.15, 1.7 Intrinsic Utilities (fetched 2026-10-16)
GNU Bash manual, Bash Builtins; dash(1) Builtins (man7.org) (fetched 2026-10-16)
learn.microsoft.com windows-commands/cmd (fetched 2026-10-16): no internal-command list; S1's list is the source
```

## Absence Verified (2026-10-16)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A1 | `make_program_resolver` has one src caller; `judge` has three | Grep `make_program_resolver\|_pathext\|_cmd_lookup` (repo), `judge\(` in `src/` | src: `command_gate.py` only; judge: `tools.py:1157`, `shell_command.py:221`, `red_team.py:425` | yes |
| A2 | No S2a test passes a PATHEXT outside the grammar except `malformed_pathext` | Grep `pathext\|PATHEXT` in `tests/test_ad1328_s2a*` | `.COM;.EXE;.BAT;.CMD`, `.COM;.EXE`, `.EXE`, `.CMD;.BAT`, `COM;.EXE` (None before and after) | yes |
| A3 | No S2a test pins a built-in name | Grep `host_executable` in `tests/test_ad1328_s2a*` | `tool`, `git` only | yes |
| A4 | No test asserts the doctor remediation phrase | Grep `pattern or example\|every example holds` repo-wide | the doctor source and the wiring prompt only | yes |
| A5 | No S2a test assumes an unparseable segment has no matches | Grep `\.matches\|matches == \(\)\|basis` in `tests/test_ad1328_s2a*` | `gate.py:684, :694, :700, :705` (basis lists only, all pass under S1 r3 per M9) | yes |
| A6 | No S2a test expects `which` to be called for a built-in name | Grep `which\.calls` and `\("(echo\|printf\|test\|kill\|pwd\|type\|...)", ` in `tests/test_ad1328_s2a*` | `git`, `nope` only | yes |

## Measurements requested (not verifiable in this session)

| Id | Claim | How |
|---|---|---|
| M1 | The Captain's host PATHEXT fullmatches `_PATHEXT_GRAMMAR` (else every bare pin under cmd refuses on this host) | `python -c "import os,re;print(repr(os.environ['PATHEXT']))"`; report the value |
| M2 | `cmd.exe` accepts a working directory of about 230 characters holding blanks (B22, B34 and B35 `long_spaced`) | The first R2-M3 run; if it fails, report and lower `_work_root`'s 200 to the largest that works (Builder stop, not an assertion change) |
| M3 | S1 r3 reads `& '<path with blanks>'` (PowerShell) and `"<path with blanks>"` (cmd) as the written pin | B22 and B35 premises (the reviewer's quoted spaced probe passed for PowerShell) |
| M4 | The admitted-maximum durable envelope is 3,995 bytes (reviewer) | B31's comment; the test asserts only `<= 4096` |
| M5 | cmd ignores an extensionless `d1\tool` and runs `d2\tool.cmd` | B20 `extensionless_d1_cmd_d2` (the reviewer executed extensionless files with no finding) |
| M6 | The staged tree id | `git write-tree` is denied here; blobs from `git ls-files -s`, `git diff` empty |

## Prior Art and Blind Spots

A repair. External sources fetched and used:
- POSIX.1-2024 XCU 2.9.1.4. It fixes the order: special built-ins, the unspecified names, functions, intrinsic utilities, then PATH. Step 1e lets a shell run its built-in in place of the PATH file. With 2.15 and 1.7, it gives the posix list.
- dash(1) and the bash manual: the shells' other built-ins.
- Microsoft's `cmd` page: no internal list. S1's reviewed list stands.

Considered and rejected: asking the child shell (`command -v` in a fresh `sh` with the child's environment), which costs a subprocess per judgement inside a synchronous gate; and posix never answering, as PowerShell does, which costs every bare pin on Linux for names no built-in uses.

Considered and deferred:
- zsh or ksh93 as `/bin/sh` (macOS `/private/var/select/sh` can select zsh): those shells' further built-ins (`which`, `where`, `limit`, `sched` and others) are not listed, and the written path always proves;
- `\\?\` PATH entries (r1 accepts them as absolute, and cmd's reading of them is unmeasured);
- a public S1 export of the cmd list.

`docs/research/reference-projects.md` was not consulted: no listed project models shell command resolution.

=== BUILDER BRIEFS ===

### Brief R2-M1 -- `tests/test_ad1328_s2a_gate.py` (effort: high, at most 70 calls)

Contract `prompts/ad-1328-s2a-repair-r2.md`. The stack is replayed and r2's source installed and frozen: write tests only. Append B23-B28. The cmd lookups use the injected recording `is_file`, and B25 the fake `which`; never probe the host. B26 re-types the 96 posix names from Section 2 literally; do not build the expected set from the module's own constant. Kill G18, G39-G52. Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s2a_gate.py -q -n 0`. If B28's S1 r3 premise (basis `unparseable` with `matches`) or B27's build premise fails, stop and report the observed values; do not weaken an assertion.

### Brief R2-M2 -- `tests/test_ad1328_s2a_run_command_tool.py` (effort: medium, at most 60 calls)

Apply Part A's B16b docstring row, then B29-B31. B31's durable half is real (`EventLog` in `tmp_path`, `_paired` and `_rows` as B16b). Kill G39 (B29) and G49 (B30). Run the file with `-n 0`, then `tests/test_ad1224_durable_tool_start.py -q -n 0`. If B31's size exceeds 4,096, stop and report it: that is an architectural stop, not a bound to move.

### Brief R2-M3 -- agents, startup and doctor, real shells (effort: high, at most 90 calls)

Apply Part A's B19 row and append B32 (`test_ad1328_s2a_shell_agent.py`) and B33 (`test_ad1328_s2a_startup_and_doctor.py`). In `tests/test_ad1328_s2a_r1_real_shells.py`: add `_work_root`; apply Part A's B20 and B22 rows; append B34 and B35 (Windows only, real shells, files only under `tmp_path`, `timeout=60`).
- Run the five files with `-n 0`.
- Run the real-shell file again with `--basetemp` set to a fresh directory of about 170 characters that holds blanks; report both counts and every skip with its reason.
- Then run S2a's focused gate.
- If B20, B34 or B35 finds cmd running a file the lookup names differently, or M2 fails, stop and report the layout and both answers.

### Mutation campaign (orchestrator, effort: high)

On the committed R2-M3 tree (replayed stack):
1. Baseline green.
2. Count each anchor: exactly once (G39-G42 share one).
3. Apply one mutant at a time, with a `.mutbak` restore in `finally`.
4. Run the four S2a files and the real-shell file serially (Windows).
5. Rows: the 15 new rows, G18 re-anchored, and G1-G38 rerun. T, R and X stand.
6. Record KILLED / INERT / INVALID with the killer, the base commit, and the sha256 of `command_gate.py` and `command_policy_check.py`.
