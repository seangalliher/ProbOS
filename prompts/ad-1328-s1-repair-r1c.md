# AD-1328 S1 repair r1c -- classes C and D from the seed-3 fuzz

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Status:** BUILD-READY. Amends `prompts/ad-1328-s1-repair-r1.md`. **Apply after `prompts/ad-1328-s1-repair-r1b.md`**: every SEARCH below is anchored on the module, fixture and DECISIONS.md as r1b leaves them. No new AD or BF number (#1530).
**Dependencies:** r1 and r1b installed.
**Estimated tests:** +24 cases in `tests/test_ad1328_s1_command_parse_repair.py` (17 refusal rows, 1 table check, 6 reading rows); 3 oracle rows (S20 and S21 under 2 PowerShell shells, C13 under cmd), each also every-host.

Pre-r1b blobs grepped for the lines r1b does not touch: `command_policy.py` `89a68fc92383d448555a1c146a7b3184db3c453b`, fixture `d18e2a39464646ce7d52bc3835c59b96cbab0489`, `DECISIONS.md` `8ea0eb88cff7f03f8029ffe43bba3b16bd88ce18`. Lines r1b touches are quoted from r1b's REPLACE text.

## Problem

Measured by the orchestrator's argv probe (Windows PowerShell 5.1, pwsh 7.6.7, `cmd.exe /c`), seed-3 fuzz plus single-line checks.

### Class C -- a PowerShell `-name:` word

In PowerShell, a bare word that starts with `-` and has a colon is a parameter (`-name:`) followed by a **separate argument token**. For a native program, PowerShell glues the two back together. The glue is exact only when that argument token is a plain name:

| Text | Real argv | Policy (one word) |
|---|---|---|
| `-a:b`, `-a:b:c`, `--a:b`, `-:b`, `-a:b:`, `-a::b`, `-a:-b`, `-1:2` | unchanged | same |
| `-a:` | parse error, nothing runs | `-a:` |
| `-a:-b:c` | `-a:-b:`, `c` (split) | `-a:-b:c` |
| `-qq:-qq:zz` | 5.1 `-qq:-qq:`, `zz`; 7 `zz` | `-qq:-qq:zz` |
| `` -qq:` zz `` | `-qq:`, `zz` (the escaped blank starts the argument token, so r1b's class A applies there) | `-qq: zz` |
| `-a:$x` | 5.1 `-a:`; 7 nothing | dynamic, variadic |

`-a:'b c'` is already refused, because `_single_quoted` refuses a quote inside a word (`command_policy.py:798-799`).

### Class D -- cmd: `=` ends a redirection target

cmd.exe ends a redirection target at `=`, as it does at `,` and `;`, and passes the rest on as an argument. Examples: `vv >zz=ww` gives `["vv", "=ww"]` and writes file `zz`; `vv 2>zz=` gives `["vv", "="]`; `vv >=zz` writes `zz`; `vv <zz=ww` fails. The policy reads the target as `zz=ww`. `vv >"zz=ww"` writes `zz=ww`, and `=` in an ordinary argument (`a=b`, `a=`, `=a`) is unchanged. `_segment` (`:1054-1059`) takes the target word's `raw` as it is, and `_CmdLexer` refuses unquoted `,` and `;` (`_CMD_REFUSED_UNQUOTED`, `:103`) but not `=`.

## Solution

**C.** In `_PowerShellLexer._check_word`, a word whose `raw` starts with `-` and contains `:` is read only when the **whole raw** matches `-[A-Za-z0-9_.-]*:[A-Za-z_][A-Za-z0-9_.:/\\+=-]*`. In words: a plain parameter name, then an argument token that starts with a letter or `_` and holds only name, path and separator characters. Everything else is refused:

- an empty argument (`-a:`);
- an argument that starts another parameter (`-`), starts with a number (`1kb`, `0x10`), or starts with a colon;
- an escape, variable, glob, splat, `#` or `~` anywhere in the word (`` -qq:` zz ``, `-a:$x`, `-a:*`, `` -a`:b ``).

Measured-safe forms that this over-refuses are `-a::b`, `-a:-b` and `-1:2` (`-1:2` is already refused as a number). These forms are rare, and the ordinary native forms `--flag=value`, `-x v` and `git -c k=v` are untouched. A word that starts with a quote is not a parameter and is outside the rule. The check runs on dynamic words too: r1b removed the skip.

**D.** In `_segment`, under `cmd`, refuse a redirection target whose `raw` contains `=`, quoted or not. A quoted `=` is measured safe, but refusing it keeps the check to one line and costs almost nothing. The rest of the delimiter set is already handled: blank and tab end the word in `_CmdLexer.lex` (`:679-681`); `,` and `;` are refused unquoted (`:103`, `:686-687`); control and non-ASCII characters are refused by `_checked_text` (`:994-1006`). So `=` is the only gap. `2>&1=` is already refused, because a duplication target must be one descriptor (`:1057`).

**r1b class A: no widening.** The only measured token start inside a policy word is the argument after `-name:`. Rule C requires that argument to start with a letter or `_`, so an escaped blank there is refused (row `r1c_ps_colon_escaped_blank`). The other token starts PowerShell knows (after `,`, `(`, `{`) are already refused as syntax (`_PS_SYNTAX`, `:121`).

### Section 1 -- `src/probos/execution/command_policy.py` (constant)

SEARCH:
```python
_PS_PROVIDER_PREFIXES: Final = ("alias:", "function:", "env:", "variable:")
```
REPLACE:
```python
_PS_PROVIDER_PREFIXES: Final = ("alias:", "function:", "env:", "variable:")
# A bare word that starts with '-' and holds ':' is a parameter and a separate argument token, which PowerShell glues
# back for a program only when that token is a plain name (measured on 5.1 and 7: `-a:` fails to parse, `-a:-b:c`
# splits, `-a:$x` drops).
_PS_COLON_PARAMETER: Final = re.compile(r"-[A-Za-z0-9_.-]*:[A-Za-z_][A-Za-z0-9_.:/\\+=-]*")
```

### Section 2 -- `src/probos/execution/command_policy.py` (`_PowerShellLexer._check_word`, as r1b leaves it)

SEARCH:
```python
            raise _Unparseable("the -- or --% (stop-parsing) token, which PowerShell versions pass differently")
        if whole and not value:
```
REPLACE:
```python
            raise _Unparseable("the -- or --% (stop-parsing) token, which PowerShell versions pass differently")
        if word.raw.startswith("-") and ":" in word.raw and _PS_COLON_PARAMETER.fullmatch(word.raw) is None:
            raise _Unparseable("a '-name:' word whose argument is not a plain name, which PowerShell passes differently")
        if whole and not value:
```

### Section 3 -- `src/probos/execution/command_policy.py` (`_segment`)

SEARCH:
```python
            if item.text.endswith(("<&", ">&")) and (target.dynamic or target.raw not in _DUPLICATION_TARGETS[dialect]):
                raise _Unparseable("a descriptor duplication whose target is not one descriptor")
            redirections.append(f"{item.text}{target.raw}")
```
REPLACE:
```python
            if item.text.endswith(("<&", ">&")) and (target.dynamic or target.raw not in _DUPLICATION_TARGETS[dialect]):
                raise _Unparseable("a descriptor duplication whose target is not one descriptor")
            if dialect == "cmd" and "=" in target.raw:  # measured: cmd.exe ends the target at '=' and passes the rest on
                raise _Unparseable("an '=' in a redirection target, which cmd.exe reads as the end of the target")
            redirections.append(f"{item.text}{target.raw}")
```

### Section 4 -- `tests/fixtures/ad1328_shell_oracle.json` (accepted boundaries, live)

SEARCH (C12, unique):
```json
    {"id": "C12", "dialect": "cmd", "constructs": ["C-WRAP-PS-WORDS"], "requires": ["pwsh"], "text": "pwsh -NoProfile -Command {B} a b", "policy": [["a", "b"]]},
```
REPLACE:
```json
    {"id": "C12", "dialect": "cmd", "constructs": ["C-WRAP-PS-WORDS"], "requires": ["pwsh"], "text": "pwsh -NoProfile -Command {B} a b", "policy": [["a", "b"]]},
    {"id": "C13", "dialect": "cmd", "constructs": ["C-WORD"], "text": "{P} a=b a= b =a", "policy": [["a=b", "a=", "b", "=a"]], "live": [["a=b", "a=", "b", "=a"]]},
```

SEARCH (S19, the last row as r1b leaves it):
```json
    {"id": "S19", "dialect": "powershell", "constructs": [], "text": "{P} $x` b", "policy": [[null]], "marks": ["v"], "live": [[" b"]]}
```
REPLACE:
```json
    {"id": "S19", "dialect": "powershell", "constructs": [], "text": "{P} $x` b", "policy": [[null]], "marks": ["v"], "live": [[" b"]]},
    {"id": "S20", "dialect": "powershell", "constructs": ["S-PARAM"], "text": "{P} -a:b -a:b:c --a:b -:b -a:b:", "policy": [["-a:b", "-a:b:c", "--a:b", "-:b", "-a:b:"]], "live": [["-a:b", "-a:b:c", "--a:b", "-:b", "-a:b:"]]},
    {"id": "S21", "dialect": "powershell", "constructs": ["S-WORD"], "text": "{P} a:b a:b:c x: :b", "policy": [["a:b", "a:b:c", "x:", ":b"]], "live": [["a:b", "a:b:c", "x:", ":b"]]}
```

### Section 5 -- `DECISIONS.md` (the sentence r1b added)

SEARCH:
```
and a bare word may not start with an escaped blank. Contracts `prompts/ad-1328-s1-repair-r1.md` and `prompts/ad-1328-s1-repair-r1b.md`.
```
REPLACE:
```
and a bare word may not start with an escaped blank. A second seed closed a PowerShell `-name:` word whose argument is not a plain name, and an `=` in a cmd redirection target (cmd.exe ends the target there). Contracts `prompts/ad-1328-s1-repair-r1.md`, `prompts/ad-1328-s1-repair-r1b.md` and `prompts/ad-1328-s1-repair-r1c.md`.
```

## Tests (milestone R1C-M2, Builder, tests only)

Milestone R1C-M1 applies Sections 1-5 and runs after r1b's Sections 1-4. Milestone R1C-M2 appends the code below to the end of `tests/test_ad1328_s1_command_parse_repair.py`, after r1b's block. It reuses `test_finding_refusals` and `test_r1b_readings_unchanged`.

**No existing test or oracle row changes.** A grep of `tests/test_ad1328*.py` for `-<name>:` words and for `=` in a redirection target finds none. The two `requests>=2.31` corpus rows (`:640`, `:672`) are quoted arguments, not redirections.

```python
# --------------------------------------------------------------------------------------
# r1c (prompts/ad-1328-s1-repair-r1c.md) -- seed-3 fuzz
#   Class C: a PowerShell '-name:' word (oracle S20, S21 pin the accepted forms live).
#   Class D: an '=' in a cmd redirection target (oracle C13 pins '=' in ordinary arguments live).
# --------------------------------------------------------------------------------------

R1C_REFUSALS: list[tuple[str, str, str, str, str, str]] = [
    ("r1c_ps_colon_empty", "powershell", "echo -a:", "line", "'-name:' word", "echo -a:b"),
    ("r1c_ps_colon_parameter_argument", "powershell", "echo -a:-b:c", "line", "'-name:' word", "echo -a:b:c"),
    ("r1c_ps_colon_fuzz", "powershell", "wwxx kk -qq:-qq:zz ww", "line", "'-name:' word", "wwxx kk -qq:zz ww"),
    ("r1c_ps_colon_escaped_blank", "powershell", "echo -qq:` zz", "line", "'-name:' word", "echo -qq:zz"),
    ("r1c_ps_colon_variable", "powershell", "echo -a:$x", "line", "'-name:' word", "echo -a $x"),
    ("r1c_ps_colon_glob", "powershell", "echo -a:*", "line", "'-name:' word", "echo -a *"),
    ("r1c_ps_colon_number", "powershell", "echo -a:1kb", "line", "'-name:' word", "echo -a:kb"),
    ("r1c_ps_colon_double_colon", "powershell", "echo -a::b", "line", "'-name:' word", "echo -a:b"),
    ("r1c_ps_colon_escaped_colon", "powershell", "echo -a`:b", "line", "'-name:' word", "echo a`:b"),
    ("r1c_ps_colon_quoted", "powershell", "echo -a:'b c'", "line", "a quote inside a word", "echo -a 'b c'"),
    ("r1c_cmd_redirect_equals", "cmd", "echo x >zz=ww", "line", "'=' in a redirection target", "echo x >zz"),
    ("r1c_cmd_redirect_equals_trailing", "cmd", "echo x 2>zz=", "line", "'=' in a redirection target", "echo x 2>zz"),
    ("r1c_cmd_redirect_equals_leading", "cmd", "echo x >=zz", "line", "'=' in a redirection target", "echo x > zz"),
    ("r1c_cmd_redirect_equals_spaced", "cmd", "echo x > zz=ww", "line", "'=' in a redirection target", "echo x zz=ww"),
    ("r1c_cmd_redirect_equals_quoted", "cmd", 'echo x >"zz=ww"', "line", "'=' in a redirection target", 'echo x >"zz ww"'),
    ("r1c_cmd_input_equals", "cmd", "echo x <zz=ww", "line", "'=' in a redirection target", "echo x <zz"),
    ("r1c_cmd_duplication_equals", "cmd", "echo x 2>&1=", "line", "not one descriptor", "echo x 2>&1"),
]


def test_r1c_refusals_table() -> None:
    ids = [row[0] for row in R1C_REFUSALS]
    assert len(R1C_REFUSALS) == 17
    assert len(set(ids)) == len(ids)
    assert not set(ids) & ({row[0] for row in FINDING_REFUSALS} | {row[0] for row in R1B_REFUSALS})


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "scope", "reason", "neighbour"), R1C_REFUSALS, ids=[row[0] for row in R1C_REFUSALS],
)
def test_r1c_refusals(case_id: str, dialect: Dialect, command: str, scope: str, reason: str, neighbour: str) -> None:
    test_finding_refusals(case_id, dialect, command, scope, reason, neighbour)


R1C_READINGS: list[tuple[str, Dialect, str, tuple[str, ...], tuple[bool, ...]]] = [
    (
        "s20_colon_parameters", "powershell", "echo -a:b -a:b:c --a:b -:b -a:b:",
        ("echo", "-a:b", "-a:b:c", "--a:b", "-:b", "-a:b:"), (False,) * 6,
    ),  # oracle S20
    ("s21_colons", "powershell", "echo a:b a:b:c x: :b", ("echo", "a:b", "a:b:c", "x:", ":b"), (False,) * 5),  # S21
    ("ps_quoted_dash_colon", "powershell", "echo '-a:'", ("echo", "-a:"), (False, False)),  # a quoted word is no parameter
    ("c13_equals_arguments", "cmd", "echo a=b a= b =a", ("echo", "a=b", "a=", "b", "=a"), (False,) * 5),  # oracle C13
    ("posix_redirect_equals", "posix", "echo x >a=b", ("echo", "x"), (False, False)),  # rule D is cmd-only
    ("ps_redirect_equals", "powershell", "echo x > a=b", ("echo", "x"), (False, False)),  # rule D is cmd-only
]


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "tokens", "dynamic"), R1C_READINGS, ids=[row[0] for row in R1C_READINGS],
)
def test_r1c_readings_unchanged(
    case_id: str, dialect: Dialect, command: str, tokens: tuple[str, ...], dynamic: tuple[bool, ...],
) -> None:
    test_r1b_readings_unchanged(case_id, dialect, command, tokens, dynamic)
```

## Mutation campaign (rows added; anchors single-line and unique after r1b + r1c)

| Id | Anchor | Mutant | Killer |
|---|---|---|---|
| M102 | `if word.raw.startswith("-") and ":" in word.raw and _PS_COLON_PARAMETER.fullmatch(word.raw) is None:` | `if False:` | `r1c_ps_colon_*` except `_quoted` |
| M103 | `_PS_COLON_PARAMETER: Final = re.compile(r"-[A-Za-z0-9_.-]*:[A-Za-z_][A-Za-z0-9_.:/\\+=-]*")` | `... re.compile(r"-[A-Za-z0-9_.-]*:.*")` | `r1c_ps_colon_empty`, `_parameter_argument`, `_variable` |
| M104 | same | `... re.compile(r"-[A-Za-z0-9_.-]*:[A-Za-z0-9_:-][A-Za-z0-9_.:/\\+=-]*")` | `r1c_ps_colon_number`, `_parameter_argument`, `_double_colon` |
| M105 | `if dialect == "cmd" and "=" in target.raw:  # measured: cmd.exe ends the target at '=' and passes the rest on` | `if False:` | `r1c_cmd_*` except `_duplication_equals` |
| M106 | same | `if "=" in target.raw:` | `R1C_READINGS` `posix_redirect_equals`, `ps_redirect_equals` |
| M107 | same | `if dialect == "cmd" and target.raw.startswith("="):` | `r1c_cmd_redirect_equals`, `_trailing`, `_spaced`, `_quoted`, `_input_equals` |

## Closure enumeration (rows added)

| Class | Producer or exit | Closed by |
|---|---|---|
| C | Bare PowerShell word, literal (`_check_word` via `_end_word`, `:478`) | Section 2 |
| C | Same word, dynamic (`-a:$x`, `-a:*`, `-$x:b`, `-a:@x`) | Section 2: the check runs on every word since r1b, and the regex excludes `$ * ? ~ @ #` and the backtick |
| C | Quoted word (`'-a:'`, `"-a:b"`) | Not a parameter: the rule tests `raw`, which starts with the quote |
| C | Quoted argument glued to `-a:` (`-a:'b c'`, `-a:"b c"`) | Already refused: "a quote inside a word" (`:798-799`, `:820-821`) |
| C | The program word (`-a:b x`) | `_check_word` runs before `_powershell_program_problem`; both refuse |
| C | A redirection target (`> -a:`) | Section 2 applies to every word: over-refusal |
| A (r1b) | Escaped blank at the argument token after `-name:` | Section 2: the argument must start with a letter or `_`. No change to `_escape` is needed |
| D | cmd target after `>`, `>>`, `<`, `n>` (`_segment`, `:1054-1059`) | Section 3 |
| D | cmd target after `>&` / `<&` | Already refused (`:1057`: one descriptor) |
| D | cmd target delimiters other than `=` | blank, tab: `lex` `:679-681`; `,` `;` `(` `)` `^` `'`: `_CMD_REFUSED_UNQUOTED` `:103`, `:686-687`; control and non-ASCII: `_checked_text` `:994-1006`; `&`, `|`, `<`, `>`: operators (`:690-696`) |
| D | `=` before a redirection, in the same word (`a=>zz`) | Already refused: "a redirection written against a word" (`:729-730`) |
| D | `=` in a cmd program word | Already refused: `_CMD_PROGRAM` excludes `=` (`:107`, `:1167`) |
| D | posix and PowerShell targets | Not the cmd delimiter set; out of the measured class. Pinned as accepted by `posix_redirect_equals` and `ps_redirect_equals` (not measured live) |

## What This Does NOT Change

r1b's rules and rows, the public API, the oracle schema and test file, posix lexing, R2 matching, the canonical key and digest, `operations.py`, S2a.

## Tracking

DECISIONS.md (Section 5). No PROGRESS or roadmap change.

## Acceptance Criteria

- r1b, then Sections 1-5, applied exactly.
- The focused tests `test_ad1328_s1_command_parse_repair.py`, `test_ad1328_s1_command_parse.py` and `test_ad1328_s1_shell_oracle.py` pass at `-n 0`, and S20, S21 and C13 pass live on the Captain's host.
- M102-M107 are each killed.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-10-16)

```
command_policy.py:103   _CMD_REFUSED_UNQUOTED: Final = frozenset("^(),;'")
command_policy.py:107   _CMD_PROGRAM: Final = re.compile(r"[A-Za-z0-9_.+\\: -]+")   (no '=')
command_policy.py:121   _PS_SYNTAX: Final = frozenset("(){}[],")
command_policy.py:131   _PS_PROVIDER_PREFIXES: Final = ("alias:", "function:", "env:", "variable:")   (unique; r1b does not touch it)
command_policy.py:679-696  cmd lex: blank/tab end the word; refused sets; & | operators
command_policy.py:727-730  cmd _redirection: "a redirection written against a word"
command_policy.py:798-799, 820-821  PS: "a quote inside a word"
command_policy.py:1054-1059  _segment target handling; :1057 duplication check (r1b does not touch it)
r1b Section 2 REPLACE   the --/--% raise line followed by `if whole and not value:` (unique)
r1b Section 3 REPLACE   S19 is the fixture's last row
fixture:56              C12 row (unique), followed by the S01 row
fixture:15              "S-PARAM" and "S-WORD" are listed powershell constructs; fixture:14 "C-WORD"
r1b Section 4 REPLACE   "... and a bare word may not start with an escaped blank. Contracts ... r1b.md`."
```

## Absence Verified (2026-10-16)

```
CLAIM: no existing test reads a PowerShell '-name:' word or a cmd redirection target with '='
RUN:   Grep "-[A-Za-z0-9]*:|[>]\s*[^ ]*=|>&1=" tests/test_ad1328*.py
FOUND: shell_oracle.py:174, :340; policy_evaluation.py:322; policy_models.py:91, :455, :570, :642 (comments and code,
       not command rows); command_parse_repair.py:640, :672 ("requests>=2.31", a quoted argument)
HOLDS: yes
```

## Prior Art and Blind Spots

A ProbOS-specific grammar repair; no external search. Not measured live:

- `-a:1kb` and `-a:0x10` (refused by the rule either way).
- `-a:b-c`, accepted by the regex: the argument token starts with a letter, like S01's `b-c`.
- A posix or PowerShell redirection target with `=` (accepted).
- Whether PowerShell's parameter scan stops at a backtick in a dash word without a colon (`` -a` b ``). It is outside both classes: no colon, and the fuzz reported nothing.
