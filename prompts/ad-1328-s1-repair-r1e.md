# AD-1328 S1 repair r1e -- class G: Windows programs expand the wildcards PowerShell passes them unquoted

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Status:** BUILD-READY. Amends `prompts/ad-1328-s1-repair-r1.md`. Apply after r1b, r1c and r1d. Every SEARCH was grepped in the worktree as it is now. No new AD or BF number (#1530).
**Dependencies:** r1 to r1d source sections installed. **Open:** r1d's test milestone R1D-M2 is not in the worktree. The repair test file ends with r1c's block (`tests/test_ad1328_s1_command_parse_repair.py:893`), and `R1D_` occurs nowhere under `tests/`. Apply it before R1E-M2, with the two row changes listed below.
**Estimated tests:** +20 cases (2 refusal rows, 1 table check, 15 reading rows, 2 see-through tests); oracle S24 under 2 shells plus every-host; S22 re-marked.

Verified against: `command_policy.py` `26ce6f9093f182942492a22179fef48e11b36d33`, fixture `4dce998c7d263bb8fd8006194d8528e7898161ad`, `DECISIONS.md` `ca1420c105baffedc3f3d51b527cb2889cfc5e75` (from `git diff --full-index`).

## Problem

The orchestrator ran a globbing probe: `ls.exe` from Git for Windows, an MSYS2 program, in a directory holding `a.txt`, `b.txt` and `a x.txt`. Windows PowerShell 5.1 and pwsh 7.6.7 behaved identically. In both, `'*.txt'`, `"*.txt"`, `` `*.txt ``, `'?.txt'` and `'[ab].txt'` are **expanded by the program**, because PowerShell strips the quotes and escapes before it builds the command line. It keeps quotes only around a word that holds a blank (`'a *.txt'` is not expanded).

The policy reads such words as literal. `_single_quoted` (`:809`), `_double_quoted` (`:831`) and `_escape` (`:794`) append the text with `quoted=True` and never mark the word dynamic. Only a bare `*` or `?` is marked dynamic (`:788-789`). As a result `git push '--f*'` reads as the literal `--f*`, which does not match the forbid pattern word `--force`, but an expanding program may receive `--force`.

The Cygwin/MSYS2 runtime, which also governs MSYS2 programs, is wider than the probe showed. Its source (`winsup/cygwin/dcrt0.cc`) shows:

- `globify` runs on a word that starts with `~` or contains any of `?*["'(){}`.
- It calls `glob` with `GLOB_TILDE | GLOB_BRACE | GLOB_QUOTE`.
- `build_argv` reads an **unquoted** `@file` argument as a response file.
- None of this happens when the parent is a Cygwin process or for argv[0].

cmd already models exactly that set for the program it starts: `_WINDOWS_EXPANDING = "*?[{"` anywhere and `_WINDOWS_EXPANDING_START = "~@"` at the start of a word (`:114-115`, used at `:706` and `:726`). PowerShell reaches the same programs, without the quotes.

## Solution

**Rule G.** In PowerShell, a finished word whose literal text holds **no blank** and holds `*`, `?`, `[` or `{`, or starts with `~` or `@`, is dynamic and variadic. This holds however the word was written: bare, single-quoted, double-quoted or backtick-escaped.

The rule reuses cmd's two constants, so one table states what a Windows program may expand. Marking the word, rather than refusing it, is enough:

- A restrictive rule sees through a variadic word (`_restrictive_cover`, `:1469`), so `git push '--f*'` is forbidden.
- An allow rule never matches across one.
- The canonical key falls back to a script key.

A quoted word that starts with `-` or `[` gets the same mark and no refusal. The mark already covers every option such a word could expand to.

**One producer.** `_PowerShellLexer` overrides `_end_word`, so every path that finishes a word applies the rule: `lex`, `_op`, and the separators. The override sets the fields directly instead of calling `_mark_dynamic`, because `_mark_dynamic` calls `_begin`, which refuses text after a closing quote.

**Where each producer stands:**

- `_single_quoted`, `_double_quoted` and `_escape`: covered by the override.
- `$` and splat: already dynamic.
- Here-strings (`@'`, `@"`): refused by `_splat`.
- A `*>` stream redirection: reset by `_redirection`, never finished as a word, so unaffected.
- Program word: a wildcard there now makes it dynamic, so it is refused as "the program is not a literal word". It was already refused, because `_PS_BARE_PROGRAM` and `_PS_CALLED_PROGRAM` exclude `*?[{~@` (`:123-124`); only the reason changes, and no existing row pins it.
- The `=` form (`` --x=`* ``): dynamic.
- `-name:` forms: r1c already refuses a wildcard or backtick after the colon.

**cmd.** `^*`, `^?` and `^[` are already refused: `^` is in `_CMD_REFUSED_UNQUOTED` (`:103`, `:694`), pinned by row `r1e_cmd_caret_star`. A quoted glob is already dynamic (`:726`). cmd keeps the quotes for the program, so the Cygwin runtime sees `sawquote` and does not read a quoted `@` or `~`. cmd therefore needs no change.

**Usability.** No `USABILITY_CORPUS` row in PowerShell or cmd has a quoted or escaped `*?[{` or a quoted leading `~`/`@`; the posix `find . -name '*.py'` row is posix and unchanged. The S2a starter examples (`curl -sS example.com`, `wget example.com`, `Invoke-WebRequest example.com`, `git push`, `git push origin main`) have none either. `git add '*.py'` stays accepted; it now carries a dynamic word, so it gets a script key.

### Section 1 -- `src/probos/execution/command_policy.py` (`_PowerShellLexer._end_word`)

SEARCH:
```python
    def _check_word(self, word: _Word) -> None:
        # r1b: every check reads a dynamic word's literal text too; only the "whole" ones need the whole value.
```
REPLACE:
```python
    def _end_word(self) -> None:
        # r1e: PowerShell strips a word's quotes and escapes unless it holds a blank, so a Windows program receives its
        # wildcards, braces and a leading '~' or '@' bare, and may expand them (measured with an MSYS2 ls.exe on 5.1
        # and 7; the Cygwin runtime globs '*?[{' and a leading '~' and reads an unquoted '@file'), as under cmd.
        if self._start >= 0 and not self._dynamic:
            text = "".join(self._buf)
            if " " not in text and (any(char in _WINDOWS_EXPANDING for char in text) or text[:1] in _WINDOWS_EXPANDING_START):
                self._dynamic = self._variadic = True  # not _mark_dynamic: _begin refuses text after a closing quote
        super()._end_word()

    def _check_word(self, word: _Word) -> None:
        # r1b: every check reads a dynamic word's literal text too; only the "whole" ones need the whole value.
```

### Section 2 -- `tests/fixtures/ad1328_shell_oracle.json`

Under rule G the `'~'` in S22 is dynamic, so its policy entry becomes `null` and its mark `v`. The 5.1 `live` argv is unchanged.

SEARCH:
```json
"text": "{P} `~ `~/x `~x a`~b '~'", "policy": [[null, null, null, "a~b", "~"]], "marks": ["vvvll"],
```
REPLACE:
```json
"text": "{P} `~ `~/x `~x a`~b '~'", "policy": [[null, null, null, "a~b", null]], "marks": ["vvvlv"],
```

S24 pins the marks. The probe does not glob, so its `live` argv is the same as for bare wildcards. The row records that PowerShell passes these words unquoted and unchanged, and the policy marks them `v`. The expansion itself was measured with `ls.exe` and is not repeated in the oracle.

SEARCH (the end of S23, the last row):
```json
"-a:b.c", "-a.b"]]}
  ]
```
REPLACE:
```json
"-a:b.c", "-a.b"]]},
    {"id": "S24", "dialect": "powershell", "constructs": ["S-SQ", "S-DQ", "S-ESC"], "text": "{P} '*.nomatch' \"?x\" `*y '[a]' '{b,c}' '@nofile' '~/z' 'a *.txt' 'a@b'", "policy": [[null, null, null, null, null, null, null, "a *.txt", "a@b"]], "marks": ["vvvvvvvll"], "live": [["*.nomatch", "?x", "*y", "[a]", "{b,c}", "@nofile", "~/z", "a *.txt", "a@b"]]}
  ]
```

### Section 3 -- `DECISIONS.md`

SEARCH:
```
(refused, as both versions split there). Contracts `prompts/ad-1328-s1-repair-r1.md`, `prompts/ad-1328-s1-repair-r1b.md`, `prompts/ad-1328-s1-repair-r1c.md` and `prompts/ad-1328-s1-repair-r1d.md`.
```
REPLACE:
```
(refused, as both versions split there). A globbing probe then showed that PowerShell passes a quoted or escaped wildcard to a Windows program unquoted, so a PowerShell word without a blank holding `*?[{` or starting with `~`/`@` is dynamic however it is written, the set cmd already uses. Contracts `prompts/ad-1328-s1-repair-r1.md` to `prompts/ad-1328-s1-repair-r1e.md`.
```

## Tests

**R1D-M2 (not yet applied), as amended by r1e.** Apply r1d's test block as written, with two `R1D_READINGS` rows changed:

| Row | Dynamic flags | Why |
|---|---|---|
| `e_escaped_glob_literal` (`` echo `*.nomatch `?x ``) | `(False, True, True)` | rule G: escaped `*` and `?` |
| `e_quoted` (`echo '~'`) | `(False, True)` | rule G: a quoted leading `~` |

No other r1, r1b, r1c or r1d row changes. A grep of `tests/` for PowerShell rows with a quoted or escaped `*?[{` or a quoted leading `~`/`@` found only S22 (Section 2) and `0x1*` (already dynamic). The `{esc}` templates at `test_ad1328_s1_command_parse.py:252-260` and `test_ad1328_s1_policy_evaluation.py:266` are refused at the escape first.

**R1E-M2** appends to `tests/test_ad1328_s1_command_parse_repair.py`, after the R1D block. It reuses `test_finding_refusals` (`:301`), `test_r1b_readings_unchanged` (`:827`) and `_deny_curl`.

```python
# --------------------------------------------------------------------------------------
# r1e (prompts/ad-1328-s1-repair-r1e.md) -- class G: a Windows program expands what PowerShell passes it unquoted
#   (oracle S24 pins the marks; the expansion was measured with an MSYS2 ls.exe, which the argv probe cannot show).
# --------------------------------------------------------------------------------------

R1E_REFUSALS: list[tuple[str, str, str, str, str, str]] = [
    ("r1e_ps_quoted_glob_program", "powershell", "& 'g*t' status", "segment", "not a literal word", "& 'git' status"),
    ("r1e_cmd_caret_star", "cmd", "echo ^*.txt", "line", "'^'", 'echo "*.txt"'),
]


def test_r1e_refusals_table() -> None:
    ids = [row[0] for row in R1E_REFUSALS]
    assert len(R1E_REFUSALS) == 2
    assert len(set(ids)) == len(ids)
    earlier = {row[0] for row in FINDING_REFUSALS + R1B_REFUSALS + R1C_REFUSALS + R1D_REFUSALS}
    assert not set(ids) & earlier


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "scope", "reason", "neighbour"), R1E_REFUSALS, ids=[row[0] for row in R1E_REFUSALS],
)
def test_r1e_refusals(case_id: str, dialect: Dialect, command: str, scope: str, reason: str, neighbour: str) -> None:
    test_finding_refusals(case_id, dialect, command, scope, reason, neighbour)


R1E_READINGS: list[tuple[str, Dialect, str, tuple[str, ...], tuple[bool, ...]]] = [
    ("g_single_quoted_star", "powershell", "echo '*.txt'", ("echo", "*.txt"), (False, True)),  # measured: ls.exe expands
    ("g_double_quoted_question", "powershell", 'echo "?.txt"', ("echo", "?.txt"), (False, True)),
    ("g_quoted_bracket", "powershell", "echo '[ab].txt'", ("echo", "[ab].txt"), (False, True)),  # measured
    ("g_escaped_star", "powershell", "echo `*.txt", ("echo", "*.txt"), (False, True)),  # measured
    ("g_quoted_brace", "powershell", "echo '{a,b}'", ("echo", "{a,b}"), (False, True)),  # Cygwin GLOB_BRACE
    ("g_quoted_at_start", "powershell", "echo '@args.txt'", ("echo", "@args.txt"), (False, True)),  # Cygwin @file
    ("g_quoted_tilde_start", "powershell", "echo '~/x'", ("echo", "~/x"), (False, True)),  # Cygwin GLOB_TILDE
    ("g_equals_escaped_star", "powershell", "echo --x=`*", ("echo", "--x=*"), (False, True)),
    ("g_blank_keeps_literal", "powershell", "echo 'a *.txt'", ("echo", "a *.txt"), (False, False)),  # measured: quoted
    ("g_at_mid_word", "powershell", "echo 'a@b'", ("echo", "a@b"), (False, False)),
    ("g_tilde_mid_word", "powershell", "echo 'a~b'", ("echo", "a~b"), (False, False)),
    ("g_plain_quoted", "powershell", "echo 'a.txt'", ("echo", "a.txt"), (False, False)),
    ("g_cmd_quoted_glob", "cmd", 'echo "*.txt"', ("echo", "*.txt"), (False, True)),  # unchanged (:726)
    ("g_cmd_quoted_at", "cmd", 'echo "@a"', ("echo", "@a"), (False, False)),  # unchanged: cmd keeps the quotes
    ("g_posix_quoted_glob", "posix", "echo '*.txt'", ("echo", "*.txt"), (False, False)),  # unchanged
]


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "tokens", "dynamic"), R1E_READINGS, ids=[row[0] for row in R1E_READINGS],
)
def test_r1e_readings(
    case_id: str, dialect: Dialect, command: str, tokens: tuple[str, ...], dynamic: tuple[bool, ...],
) -> None:
    test_r1b_readings_unchanged(case_id, dialect, command, tokens, dynamic)


def test_r1e_quoted_wildcard_is_variadic() -> None:
    segment = parse_command("echo '*.txt'", dialect="powershell").segments[0]
    assert segment.variadic == (False, True)


def test_r1e_restrictive_rule_sees_through_a_quoted_wildcard() -> None:
    config = CommandPolicyConfig.model_validate(
        {
            "rules": [
                {
                    "name": "no-force",
                    "pattern": ["git", "push", "--force"],
                    "decision": "forbid",
                    "justification": "no force push",
                    "alternative": "push without --force",
                }
            ],
            "unmatched_decision": "allow",
            "unparseable_decision": "escalate",
        }
    )
    assert evaluate_command(config, "git push origin main", dialect="powershell").decision == "allow"  # control
    for command in ("git push '--f*'", 'git push "--f*"', "git push `--f*"):
        assert evaluate_command(config, command, dialect="powershell").decision == "forbid", command
```

## Mutation campaign (rows added; anchors single-line and unique after r1e)

| Id | Anchor | Mutant | Killer |
|---|---|---|---|
| M116 | `if " " not in text and (any(char in _WINDOWS_EXPANDING for char in text) or text[:1] in _WINDOWS_EXPANDING_START):` | `if False:` | `g_single_quoted_star` and the other `True` rows; `test_r1e_restrictive_rule_sees_through_a_quoted_wildcard`; S24 |
| M117 | same | `if any(char in _WINDOWS_EXPANDING for char in text) or text[:1] in _WINDOWS_EXPANDING_START:` | `g_blank_keeps_literal` |
| M118 | same | `if " " not in text and (any(char in _WINDOWS_EXPANDING for char in text) or any(char in _WINDOWS_EXPANDING_START for char in text)):` | `g_at_mid_word`, `g_tilde_mid_word` |
| M119 | same | `if " " not in text and any(char in _WINDOWS_EXPANDING for char in text):` | `g_quoted_at_start`, `g_quoted_tilde_start` |
| M120 | `self._dynamic = self._variadic = True  # not _mark_dynamic: _begin refuses text after a closing quote` | `self._dynamic = True` | `test_r1e_quoted_wildcard_is_variadic` |

## Closure enumeration (rows added)

| Producer or exit | Closed by |
|---|---|
| PS `_single_quoted`, `_double_quoted` (whole quoted word) | Section 1 |
| PS `_escape` (`` `* ``, `` `? ``, `` `[ ``, `` `{ ``, `` `~ `` and `` `@ `` at the start) | Section 1. `` `~ `` was already dynamic (r1d) |
| PS bare `*`, `?`, leading `~` | Already dynamic (`:788-789`) |
| PS bare `[`, `{` | Refused as syntax (`_PS_SYNTAX`, `:121`) |
| PS `$`, splat, here-strings | Dynamic (`$`, splat); here-strings refused (`_splat`) |
| PS program word | Now dynamic, so "not a literal word"; it was already refused by the program regexes |
| PS `=` form, `-name:` form | `=`: Section 1. `-name:`: r1c refuses a wildcard or backtick after the colon |
| PS word with a blank | Not marked: PowerShell quotes it, and the program sees it quoted (measured) |
| PS redirection target `> '*.txt'` | Dynamic; a file target is recorded raw as before. Not a program argument |
| cmd `^*` / `^?` / `^[` | Already refused: `^` unquoted (`:103`) |
| cmd quoted glob, leading `~` / `@` | Already modelled (`:706`, `:726`); a quoted `@` / `~` keeps its quotes, so it is literal to the Cygwin runtime |
| posix | A POSIX program does not expand its own arguments; the posix dialect is a POSIX host's `/bin/sh` |

## Program-side transformations of a Windows program's own command line (the family)

| Transformation | Status | Why |
|---|---|---|
| UCRT/mingw `setargv` wildcard expansion (`*?`, mingw also `[`) | PS: rule G. cmd: already | Unquoted only; cmd quoted globs are already dynamic |
| Cygwin/MSYS2 `globify` (`*?[`, `{}` braces, a leading `~`, quote removal) | PS: rule G. cmd: already (`_WINDOWS_EXPANDING*`) | Quote removal: `'` without a blank is refused (r1); `"` in a PS value is refused (r1b) |
| Cygwin/MSYS2 `@file` response files (unquoted, not argv[0]) | PS: rule G (a leading `@`). cmd: already (`_WINDOWS_EXPANDING_START`) | A mid-word `@` (`-d@f`) is the program reading its own options: boundary |
| Program-defined `@file` (gcc, javac, MSVC `cl`/`link`, `python -X`...) | Leading `@`: covered as above. Option values: boundary | A prefix rule cannot see a program's files or configuration (#1530, Do Not Build) |
| MSYS2 POSIX-path conversion | Boundary | It happens when an MSYS2 program starts a native one: a program starting a program |
| UCRT backslash and double-quote rules | Already (r1: cmd `\"` and `""` refused; PS `"` refused, blank with a trailing `\` refused) | — |
| Non-ASCII best-fit code-page mapping | Already (r1: non-ASCII refused in cmd and PS) | — |
| A batch file's `%`, `!`, `& \| < > ^` | Already (r1, r1b) | — |
| PowerShell cmdlet wildcard parameters (`Remove-Item '*.txt'`) | PS: rule G | A cmdlet expands a quoted wildcard as a program does |
| Option parsing (getopt permutation, abbreviations, `--`), environment and alias expansion inside a program | Boundary | Prefix-rule language (#1530, Do Not Build) |

## What This Does NOT Change

cmd and posix lexing, r1b to r1d rules, the public API, the oracle schema and test file, R2 matching, the canonical key scheme and digest, `operations.py`, S2a.

## Tracking

DECISIONS.md (Section 3). No PROGRESS or roadmap change.

## Acceptance Criteria

- Sections 1-3 applied exactly. R1D-M2 is applied with the two amended rows, then R1E-M2.
- The focused tests `test_ad1328_s1_command_parse_repair.py`, `test_ad1328_s1_command_parse.py`, `test_ad1328_s1_policy_evaluation.py` and `test_ad1328_s1_shell_oracle.py` pass at `-n 0`. S22 and S24 pass live under both PowerShell shells.
- M116-M120 are each killed.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-10-16, after r1d)

```
command_policy.py:103       _CMD_REFUSED_UNQUOTED: Final = frozenset("^(),;'")
command_policy.py:114-115   _WINDOWS_EXPANDING = frozenset("*?[{"); _WINDOWS_EXPANDING_START = frozenset("~@")
command_policy.py:480       _Lexer._end_word (base; _PowerShellLexer has no override)
command_policy.py:706, 726  cmd: bare and quoted marks from _WINDOWS_EXPANDING(_START)
command_policy.py:804       r1d: `if following == "~" and self._start < 0:` in _escape
command_policy.py:929-930   PS _check_word + its r1b comment line (unique; the SEARCH anchor)
command_policy.py:938       r1d F check
fixture:82                  S22 line; fixture:83 S23, the last row, ending `"-a:b.c", "-a.b"]]}`; fixture:84 `  ]`
DECISIONS.md:21             "(refused, as both versions split there). Contracts ... r1d.md`."   (1 occurrence)
repair test:893             the file ends with r1c's block; R1D_ not present in tests/
s2a prompt:1186, :1192      starter examples (no wildcard)
cygwin dcrt0.cc             globify trigger `*word != '~' && strpbrk(word, "?*[\"\'(){}")`; glob(GLOB_TILDE|GLOB_NOCHECK|GLOB_BRACE|GLOB_QUOTE);
                            `if (argc && sawquote != word && *word == '@')` insert_file; skipped for a Cygwin parent
```

## Absence Verified (2026-10-16)

```
CLAIM: no existing PowerShell test or oracle row reads a quoted or escaped '*?[{' or a quoted leading '~'/'@' as literal
RUN:   Grep "\"powershell\".*(['\"][^'\" ]*[*?\[{][^'\" ]*['\"]|'[~@]|`[*?\[{~@])" tests/
FOUND: fixture:82 (S22, re-marked in Section 2); parse.py:276, :310, :536, :540, :655; repair:142-144, :817; evaluation:266
HOLDS: yes -- the rest are refused before the word ends (escapes, here-strings, braces, splats), a stream
       redirection (*>), or already dynamic (0x1*)
CLAIM: R1D-M2 is not applied
RUN:   Grep "^R1[BCD]_|^def test_r1" tests/   ->  R1B_ and R1C_ only (repair :775-:893)
HOLDS: yes
```

## Prior Art and Blind Spots

External source read: the Cygwin runtime's `dcrt0.cc` (`globify`, `build_argv`), <https://github.com/cygwin/cygwin/blob/main/winsup/cygwin/dcrt0.cc>, adopted as the model for the MSYS2 row. These are not measured live:

- Braces, a leading `~` and a leading `@` under PowerShell. They follow from that source and from cmd's existing model.
- mingw's `[` expansion.
- A variable value that holds a wildcard (`$x = '*'`) is dynamic already.
