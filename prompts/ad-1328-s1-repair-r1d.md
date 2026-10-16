# AD-1328 S1 repair r1d -- classes E and F from the final fuzz and the enumerative run

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Status:** BUILD-READY. Amends `prompts/ad-1328-s1-repair-r1.md`. Apply after r1b and r1c (both installed). Every SEARCH below was grepped in the installed worktree. No new AD or BF number (#1530).
**Dependencies:** r1, r1b and r1c installed.
**Estimated tests:** +29 cases in `tests/test_ad1328_s1_command_parse_repair.py` (13 refusal rows, 1 table check, 15 reading rows); 2 oracle rows (S22 and S23), each run under both PowerShell shells and every-host.

Verified against: `command_policy.py` `1340350af056ac5f561de458fdfbfea794636594`, fixture `5e84ecd65a0b701b1650e07d94f0f2b5542f2f90`, `DECISIONS.md` `c002e966a71dea2a45b42062ad7d1bcc09b32cf3` (from `git diff --full-index`; the fixture is untracked).

## Problem

The orchestrator ran random lines (posix 12,000, cmd 12,000, PowerShell 6,000) and an enumerative run (every printable ASCII character in 24 word contexts, and 34x34 character pairs) against the real shells. posix and cmd show 0 divergences. PowerShell (5.1 and 7.6.7) shows two classes.

### Class E -- pwsh 7 expands an escaped leading tilde

`_PowerShellLexer.lex` marks an unescaped `~` at the start of a word dynamic and variadic (`command_policy.py:784-785`). `_escape` (`:790-801`) appends `` `~ `` as a plain literal. pwsh 7 expands a bare word whose value is `~` or starts with `~/`, however the tilde was written: `` `~ `` gives `<HOME>` and `` `~/x `` gives `<HOME>/x`. 5.1 passes the text unchanged. Quoted (`'~'`, `"~"`) and mid-word (`` a`~b ``, `` x`~ ``, `` ``~ ``) tildes are never expanded. An escaped `*`, `?` or `[` is literal in both versions, so this class does not apply to them.

### Class F -- a single-dash word is scanned as a parameter token

In both versions, a bare word that starts with `-` and then a letter, `_` or `?` is a parameter token:

- **It splits at the first `.` or `[` after the name:**
  - `-qq.zz` gives `-qq`, `.zz`.
  - `-o=a.txt` gives `-o=a`, `.txt`.
  - `-a.b -c.d` gives four words.
- **A backtick after the name passes literally:**
  - `` -qq`zz `` gives `` -qq`zz ``, which the policy reads as `-qqzz`.
  - `` -a`.b `` gives `` -a` ``, `.b`.

These are unchanged:

- `--a.b`, `--output=a.txt`, `-1.5`, `-.5`, `-1x.y`;
- `-Wall`, `-O2`, `-DFOO=bar`, `-a=b`;
- `-qq-zz`, `-qq_zz`, `-qq+zz`, `-qq/zz`, `-qq*`, `-qq?`;
- `-`, `-=`, `-.`;
- `-a:b.c`;
- `` `-a.b ``, `'-a.b'`;
- `` -`qq `` (gives `-qq`).

The policy reads every split form as one word. `_check_word` (`:923-948`) has no check for this.

## Solution

**E.** In `_escape`, an escaped `~` at a word start (`self._start < 0`) marks the word dynamic and variadic, exactly like the unescaped branch at `:784-785`. One rule covers both spellings, and the variadic mark admits both versions' readings, including `` `~x ``, which is not expanded but is already admitted by the same mark when written unescaped. These producers are not affected:

- `_double_quoted` calls `_escape` only after the word has begun (`:823` in r1b's numbering).
- `_splat` (`@` followed by an identifier) cannot start with `~`.
- An escape after a variable (`` $x`~ ``) is already dynamic.

An escaped `*`, `?` or `[` stays literal, as measured.

**F.** In `_check_word`, take `head`, the raw text before the first `:`. If `head` starts with `-` followed by a letter, `_`, `?` or a backtick (`_PS_PARAMETER_START`), and holds a `.`, `[` or backtick after those two characters (`_PS_PARAMETER_BREAKS`), the word is refused. The check reads `raw`, so it covers literal and dynamic words alike (`-a*.b`). It also covers the backtick that `_escape` would otherwise consume, and the `=` form, which `head` contains.

The backtick is in the start class because `` -`qq `` is processed: it gives `-qq`, so it is accepted, and `` -`qq.zz `` is refused. These keep their current reading:

- `-1.5` (refused as a number, `:943`);
- `--long.x` (the second character is `-`);
- `` `-a.b `` and `'-a.b'` (the raw does not start with `-`).

**How F composes with r1c.** r1c checks the whole raw of a word that has a colon. F checks only the part before the first colon, so the r1c forms measured as unchanged stay accepted (`-a:b.c`, `-a:b[0]` and `[` is refused as syntax anyway, `:781-782`). A dot before the colon (`-a.b:c`), which r1c's regex admits, is now refused by F. A backtick anywhere in a colon word is already refused by r1c, because the regex excludes it.

**Already closed by other checks:**

- `-qq[0]` is refused as syntax (`[`, `:781`).
- `-a$x.b` and `-$x.b` are refused as member access (`:867-868`).
- `-qq,zz` and `-qq{1}` are refused as syntax.

**Usability:**

- None of the 31 PowerShell `USABILITY_CORPUS` rows (`tests/test_ad1328_s1_command_parse_repair.py:692-723`) has a single-dash word with `.`, `[` or a backtick.
- The S2a examples (`git status`, `powershell -Sta -Command "git status"`, `curl -sS example.com`, `git push origin main`) do not either.
- `gcc -I.` becomes refused (row `r1d_ps_dash_include_dot`); `gcc -I .` is the accepted spelling.

### Section 1 -- `src/probos/execution/command_policy.py` (Class E, `_PowerShellLexer._escape`)

SEARCH:
```python
            raise _Unparseable(f"the PowerShell escape '`{following}', which expands to another character")
        self._literal(following, quoted=True)
        self.i += 2
```
REPLACE:
```python
            raise _Unparseable(f"the PowerShell escape '`{following}', which expands to another character")
        if following == "~" and self._start < 0:  # measured: pwsh 7 expands an escaped leading tilde like a bare one
            self._mark_dynamic(variadic=True)
        self._literal(following, quoted=True)
        self.i += 2
```

### Section 2 -- `src/probos/execution/command_policy.py` (Class F, constants)

SEARCH:
```python
_PS_COLON_PARAMETER: Final = re.compile(r"-[A-Za-z0-9_.-]*:[A-Za-z_][A-Za-z0-9_.:/\\+=-]*")
```
REPLACE:
```python
_PS_COLON_PARAMETER: Final = re.compile(r"-[A-Za-z0-9_.-]*:[A-Za-z_][A-Za-z0-9_.:/\\+=-]*")
# A bare '-' then a name character starts a parameter token: both versions end it at '.' or '[' and pass a later
# backtick literally (measured: `-qq.zz` -> `-qq` `.zz`; `-qq`zz` -> `-qq`zz`).
_PS_PARAMETER_START: Final = re.compile(r"-[A-Za-z_?`]")
_PS_PARAMETER_BREAKS: Final = frozenset(".[`")
```

### Section 3 -- `src/probos/execution/command_policy.py` (Class F, `_PowerShellLexer._check_word`)

SEARCH:
```python
            raise _Unparseable("a '-name:' word whose argument is not a plain name, which PowerShell passes differently")
        if whole and not value:
```
REPLACE:
```python
            raise _Unparseable("a '-name:' word whose argument is not a plain name, which PowerShell passes differently")
        head = word.raw.partition(":")[0]
        if _PS_PARAMETER_START.match(head) and any(char in _PS_PARAMETER_BREAKS for char in head[2:]):
            raise _Unparseable("a '.', '[' or '`' after a -name, which PowerShell reads as the end of a parameter")
        if whole and not value:
```

### Section 4 -- `tests/fixtures/ad1328_shell_oracle.json`

S22 records `live` for Windows PowerShell 5.1 only: pwsh 7's `<HOME>` depends on the host, so under `pwsh` the row is checked by admission against the `v` marks.

SEARCH (S21, the last row):
```json
    {"id": "S21", "dialect": "powershell", "constructs": ["S-WORD"], "text": "{P} a:b a:b:c x: :b", "policy": [["a:b", "a:b:c", "x:", ":b"]], "live": [["a:b", "a:b:c", "x:", ":b"]]}
```
REPLACE:
```json
    {"id": "S21", "dialect": "powershell", "constructs": ["S-WORD"], "text": "{P} a:b a:b:c x: :b", "policy": [["a:b", "a:b:c", "x:", ":b"]], "live": [["a:b", "a:b:c", "x:", ":b"]]},
    {"id": "S22", "dialect": "powershell", "constructs": ["S-ESC"], "text": "{P} `~ `~/x `~x a`~b '~'", "policy": [[null, null, null, "a~b", "~"]], "marks": ["vvvll"], "live": {"powershell": [["~", "~/x", "~x", "a~b", "~"]]}},
    {"id": "S23", "dialect": "powershell", "constructs": ["S-PARAM"], "text": "{P} --a.b --output=a.txt --qq=a.zz -Wall -O2 -DFOO=bar -a -a=b -qq-zz -qq_zz -qq+zz -qq/zz - -= -. -a:b.c `-a.b", "policy": [["--a.b", "--output=a.txt", "--qq=a.zz", "-Wall", "-O2", "-DFOO=bar", "-a", "-a=b", "-qq-zz", "-qq_zz", "-qq+zz", "-qq/zz", "-", "-=", "-.", "-a:b.c", "-a.b"]], "live": [["--a.b", "--output=a.txt", "--qq=a.zz", "-Wall", "-O2", "-DFOO=bar", "-a", "-a=b", "-qq-zz", "-qq_zz", "-qq+zz", "-qq/zz", "-", "-=", "-.", "-a:b.c", "-a.b"]]}
```

### Section 5 -- `DECISIONS.md` (the sentence r1c left)

SEARCH:
```
(cmd.exe ends the target there). Contracts `prompts/ad-1328-s1-repair-r1.md`, `prompts/ad-1328-s1-repair-r1b.md` and `prompts/ad-1328-s1-repair-r1c.md`.
```
REPLACE:
```
(cmd.exe ends the target there). An enumerative run then closed an escaped leading `~` (dynamic, as pwsh 7 expands it) and a `.`, `[` or backtick after a single-dash parameter name (refused, as both versions split there). Contracts `prompts/ad-1328-s1-repair-r1.md`, `prompts/ad-1328-s1-repair-r1b.md`, `prompts/ad-1328-s1-repair-r1c.md` and `prompts/ad-1328-s1-repair-r1d.md`.
```

## Tests (milestone R1D-M2, Builder, tests only)

R1D-M1 applies Sections 1-5. R1D-M2 appends the block below to the end of `tests/test_ad1328_s1_command_parse_repair.py`, after r1c's block (`:893`). It reuses `test_finding_refusals` (`:301`) and `test_r1b_readings_unchanged` (`:827`).

**No existing r1, r1b or r1c test or oracle row changes.** A grep of `tests/test_ad1328*.py` and the fixture for a single-dash word with `.`, `[` or a backtick found nothing. No existing row escapes a leading `~`.

```python
# --------------------------------------------------------------------------------------
# r1d (prompts/ad-1328-s1-repair-r1d.md) -- the final fuzz and the enumerative run
#   Class E: an escaped leading '~' is dynamic like a bare one (oracle S22).
#   Class F: '.', '[' or '`' after a single-dash parameter name (oracle S23 pins the accepted forms live).
# --------------------------------------------------------------------------------------

R1D_REFUSALS: list[tuple[str, str, str, str, str, str]] = [
    ("r1d_ps_dash_dot", "powershell", "echo -qq.zz", "line", "after a -name", "echo --qq.zz"),
    ("r1d_ps_dash_trailing_dot", "powershell", "echo -qq.", "line", "after a -name", "echo -qq"),
    ("r1d_ps_dash_two_words", "powershell", "echo -a.b -c.d", "line", "after a -name", "echo -a -c"),
    ("r1d_ps_dash_equals_dot", "powershell", "echo -o=a.txt", "line", "after a -name", "echo --output=a.txt"),
    ("r1d_ps_dash_underscore", "powershell", "echo -_a.b", "line", "after a -name", "echo -_ab"),
    ("r1d_ps_dash_question", "powershell", "echo -?.b", "line", "after a -name", "echo -?"),
    ("r1d_ps_dash_backtick", "powershell", "echo -qq`zz", "line", "after a -name", "echo --qq`zz"),
    ("r1d_ps_dash_backtick_dollar", "powershell", "echo -qq`$zz", "line", "after a -name", "echo -qqzz"),
    ("r1d_ps_dash_escaped_name_dot", "powershell", "echo -`qq.zz", "line", "after a -name", "echo -`qq"),
    ("r1d_ps_dash_dynamic_dot", "powershell", "echo -a*.b", "line", "after a -name", "echo -a*b"),
    ("r1d_ps_dash_dot_before_colon", "powershell", "echo -a.b:c", "line", "after a -name", "echo -a:b.c"),
    ("r1d_ps_dash_include_dot", "powershell", "gcc -I.", "line", "after a -name", "gcc -I ."),
    ("r1d_ps_dash_variable_dot", "powershell", "echo -a$x.b", "line", "member access", "echo -a$x-b"),
]


def test_r1d_refusals_table() -> None:
    ids = [row[0] for row in R1D_REFUSALS]
    assert len(R1D_REFUSALS) == 13
    assert len(set(ids)) == len(ids)
    earlier = {row[0] for row in FINDING_REFUSALS} | {row[0] for row in R1B_REFUSALS} | {row[0] for row in R1C_REFUSALS}
    assert not set(ids) & earlier


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "scope", "reason", "neighbour"), R1D_REFUSALS, ids=[row[0] for row in R1D_REFUSALS],
)
def test_r1d_refusals(case_id: str, dialect: Dialect, command: str, scope: str, reason: str, neighbour: str) -> None:
    test_finding_refusals(case_id, dialect, command, scope, reason, neighbour)


R1D_READINGS: list[tuple[str, Dialect, str, tuple[str, ...], tuple[bool, ...]]] = [
    ("e_escaped_tilde", "powershell", "echo `~", ("echo", "~"), (False, True)),  # oracle S22
    ("e_escaped_tilde_path", "powershell", "echo `~/x", ("echo", "~/x"), (False, True)),  # oracle S22
    ("e_escaped_tilde_name", "powershell", "echo `~x", ("echo", "~x"), (False, True)),  # as the bare `~x` reads
    ("e_mid_word", "powershell", "echo a`~b", ("echo", "a~b"), (False, False)),  # oracle S22
    ("e_trailing", "powershell", "echo x`~", ("echo", "x~"), (False, False)),
    ("e_escaped_backtick", "powershell", "echo ``~", ("echo", "`~"), (False, False)),
    ("e_quoted", "powershell", "echo '~'", ("echo", "~"), (False, False)),  # oracle S22
    ("e_escaped_glob_literal", "powershell", "echo `*.nomatch `?x", ("echo", "*.nomatch", "?x"), (False, False, False)),
    ("f_double_dash", "powershell", "echo --a.b --output=a.txt", ("echo", "--a.b", "--output=a.txt"), (False,) * 3),  # S23
    ("f_plain_parameters", "powershell", "echo -Wall -O2 -DFOO=bar -a=b", ("echo", "-Wall", "-O2", "-DFOO=bar", "-a=b"), (False,) * 5),  # S23
    ("f_no_name", "powershell", "echo - -= -.", ("echo", "-", "-=", "-."), (False,) * 4),  # S23
    ("f_colon_dot", "powershell", "echo -a:b.c", ("echo", "-a:b.c"), (False, False)),  # S23
    ("f_escaped_dash", "powershell", "echo `-a.b", ("echo", "-a.b"), (False, False)),  # S23
    ("f_escaped_name", "powershell", "echo -`qq", ("echo", "-qq"), (False, False)),  # measured: -`qq -> -qq
    ("f_dash_dash_backtick", "powershell", "echo --qq`zz", ("echo", "--qqzz"), (False, False)),  # measured: --qqzz
]


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "tokens", "dynamic"), R1D_READINGS, ids=[row[0] for row in R1D_READINGS],
)
def test_r1d_readings_unchanged(
    case_id: str, dialect: Dialect, command: str, tokens: tuple[str, ...], dynamic: tuple[bool, ...],
) -> None:
    test_r1b_readings_unchanged(case_id, dialect, command, tokens, dynamic)
```

## Mutation campaign (rows added; anchors single-line and unique after r1d)

| Id | Anchor | Mutant | Killer |
|---|---|---|---|
| M108 | `if following == "~" and self._start < 0:  # measured: pwsh 7 expands an escaped leading tilde like a bare one` | `if False:` | `e_escaped_tilde`, `e_escaped_tilde_path`, `e_escaped_tilde_name` |
| M109 | same | `if following == "~":` | `e_mid_word`, `e_trailing` |
| M110 | `if _PS_PARAMETER_START.match(head) and any(char in _PS_PARAMETER_BREAKS for char in head[2:]):` | `if False:` | `r1d_ps_dash_*` except `_variable_dot` |
| M111 | same | `if _PS_PARAMETER_START.match(head) and any(char in _PS_PARAMETER_BREAKS for char in head[1:]):` | `f_escaped_name` |
| M112 | `head = word.raw.partition(":")[0]` | `head = word.raw` | `f_colon_dot` |
| M113 | ``_PS_PARAMETER_START: Final = re.compile(r"-[A-Za-z_?`]")`` | `_PS_PARAMETER_START: Final = re.compile(r"-")` | `f_double_dash`, `f_dash_dash_backtick` |
| M114 | ``_PS_PARAMETER_START: Final = re.compile(r"-[A-Za-z_?`]")`` | `_PS_PARAMETER_START: Final = re.compile(r"-[A-Za-z]")` | `r1d_ps_dash_underscore`, `_question`, `_escaped_name_dot` |
| M115 | ``_PS_PARAMETER_BREAKS: Final = frozenset(".[`")`` | `_PS_PARAMETER_BREAKS: Final = frozenset(".")` | `r1d_ps_dash_backtick`, `_backtick_dollar` |

## Closure enumeration (rows added)

| Class | Producer or exit | Closed by |
|---|---|---|
| E | `_escape` from `lex` at a word start (`:753-754`) | Section 1 |
| E | Unescaped leading `~` (`:784-785`) | Already dynamic (r1) |
| E | `_escape` from `_double_quoted` | Not a producer: the word has begun, and a quoted tilde is never expanded |
| E | `_splat`, `_variable` | `@` and `$` start with an identifier, not `~`. `` $x`~ `` is already dynamic |
| E | Escaped `*`, `?`, `[` | Literal in both versions (measured); no change |
| E | `-a:~`, `` -a:`~ `` | Already refused by r1c (the argument must start with a letter or `_`) |
| F | Literal single-dash word, `.` / `[` / backtick after the name | Section 3 |
| F | The `=` form (`-o=a.txt`) | Section 3: `head` holds `=` and what follows it |
| F | Dynamic forms (`-a*.b`) | Section 3 reads `raw`. `-a$x.b` and `-$x.b` are already refused as member access (`:867-868`) |
| F | The backtick `_escape` would consume (`` -qq`zz ``) | Section 3 reads `raw`, which keeps the backtick |
| F | `[` unescaped | Already refused as syntax (`:781`) |
| F | Colon forms | r1c's whole-raw check, then F on the part before the colon (`-a.b:c` refused; `-a:b.c` accepted, S23) |
| F | `--long`, digit or `.` after the dash, `` `-x ``, quoted words | Not parameter tokens: `_PS_PARAMETER_START` does not match (S23 pins them live) |
| F | Program word and redirection target | Section 3 applies to every word (over-refusal) |

## What This Does NOT Change

r1b and r1c rules and rows, the public API, the oracle schema and test file, posix and cmd lexing, R2 matching, the canonical key and digest, `operations.py`, S2a.

## Tracking

DECISIONS.md (Section 5). No PROGRESS or roadmap change.

## Acceptance Criteria

- Sections 1-5 applied exactly.
- The focused tests `test_ad1328_s1_command_parse_repair.py`, `test_ad1328_s1_command_parse.py` and `test_ad1328_s1_shell_oracle.py` pass at `-n 0`, and S22 and S23 pass live under both PowerShell shells.
- M108-M115 are each killed.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-10-16, installed r1b + r1c)

```
command_policy.py:135   _PS_COLON_PARAMETER: Final = re.compile(...)   (unique)
command_policy.py:781-782  elif ch in _PS_SYNTAX: raise ... syntax
command_policy.py:784-785  if ch in "*?" or (ch == "~" and self._start < 0): self._mark_dynamic(variadic=True)
command_policy.py:790-801  _escape; :798-799 the expanding-escape raise, then :800 self._literal(following, quoted=True), :801 self.i += 2
command_policy.py:923-948  _check_word; :929-930 r1c colon check, then :931 `if whole and not value:`
command_policy.py:943   number check (whole and ...)
fixture:81              S21 is the last row
DECISIONS.md:21         "(cmd.exe ends the target there). Contracts ... r1c.md`."   (1 occurrence)
repair test:301, :827, :893   test_finding_refusals, test_r1b_readings_unchanged, the end of r1c's block
repair test:692-723     the 31 PowerShell USABILITY_CORPUS rows
```

## Absence Verified (2026-10-16)

```
CLAIM: no existing test, oracle row or S2a example has a single-dash PowerShell word with '.', '[' or a backtick
RUN:   Grep "[ \"'(]-[A-Za-z_?][^ \"',)]*[.`\[]" tests/test_ad1328*.py, tests/fixtures/ad1328_shell_oracle.json
FOUND: none
RUN:   Grep "[ \"'\[]-[A-Za-z_?][^ \"',\]]*[.`]" prompts/ad-1328-s2a-command-policy-wiring.md
FOUND: :267 "-Command``" (reST markup in a docstring, not a command)
HOLDS: yes
```

## Prior Art and Blind Spots

A ProbOS-specific grammar repair; no external search. Not measured or not decided here:

- **Not measured live:** `` `~\x `` (a backslash after the tilde). It is dynamic either way.
- **Not measured live:** `-qq$zz`, `-a*b` and `-?`. They are used as neighbours and are read as dynamic or literal by the existing rules.
- **Program-side globbing (considered, not in this class).** PowerShell strips quotes, so a quoted or escaped `*` or `?` reaches a Windows program bare. That program may glob it if it is linked with UCRT `setargv` or MSYS2. The policy reads it as literal, while cmd marks a quoted glob dynamic (`:718-719`). The Python probe does not glob, so the fuzz cannot see this. It needs a globbing probe before any rule; I recommend it as the next oracle extension.
