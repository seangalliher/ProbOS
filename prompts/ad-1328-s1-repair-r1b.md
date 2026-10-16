# AD-1328 S1 repair r1b -- two PowerShell classes found by the differential fuzz

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Status:** BUILD-READY. Amends `prompts/ad-1328-s1-repair-r1.md` (installed). No new AD or BF number: this is the same contract (#1530).
**Dependencies:** the r1 repair as installed in `feat/ad1328-s1-20261016-26250c9c` (base `26250c9c`).
**Estimated tests:** +31 cases (16 refusal rows + 1 table check + 10 reading rows in `tests/test_ad1328_s1_command_parse_repair.py`; 5 oracle rows x 2 PowerShell shells live, 5 every-host).

Verified against these blobs (from `git diff --full-index`; the source and DECISIONS are worktree versions, the tests and fixture are untracked):

| File | Blob |
|---|---|
| `src/probos/execution/command_policy.py` (installed r1) | `89a68fc92383d448555a1c146a7b3184db3c453b` |
| `DECISIONS.md` | `8ea0eb88cff7f03f8029ffe43bba3b16bd88ce18` |
| `tests/fixtures/ad1328_shell_oracle.json` | `d18e2a39464646ce7d52bc3835c59b96cbab0489` |
| `tests/test_ad1328_s1_command_parse_repair.py` | `643da647e5500d9903e24e456a40c66aba09c6f0` |

If a blob differs, re-grep each SEARCH block before applying it.

## Problem

The orchestrator's differential fuzz harness (outside the repository) ran accepted lines through Git bash 5.2, dash, cmd.exe, Windows PowerShell 5.1 and pwsh 7.6.7 and compared the policy's words with the argv a probe received. On the r1 module it found 0 divergences in posix (14,500 lines) and cmd (8,500 lines), and two classes in PowerShell (2,600 lines). The behaviour was the same on both PowerShell versions unless stated.

### Class A -- a bare word that starts with a backtick-escaped blank

`_PowerShellLexer._escape` (`command_policy.py:786-795`) appends any escaped character that does not expand, a blank included, so `` echo ` zz `` reads `("echo", " zz")`. Both PowerShell versions read an escaped blank at the start of a bare word as a blank:

| Text (`ww` = the printer) | Real argv after `ww` |
|---|---|
| `` ww ` zz `` | `["zz"]` |
| `` ww ` `` | `[]` |
| `` ww ` ` x `` | `["x"]` |
| `` ww ` $x `` | `[]` |
| accepted, unchanged: `` ww a` b `` / `` ww x` y` z `` / `` ww a` `` / `` ww "` zz" `` / `` ww $x` b `` | `["a b"]` / `["x y z"]` / `["a "]` / `[" zz"]` / `[" b"]` |

### Class B -- a dynamic word's literal text skips every check

`_PowerShellLexer._check_word` (`:917-940`) begins `if word.dynamic: return` (`:918-919`). So `` echo $x`"b jj jj `` is accepted as `("echo", '"b', "jj", "jj")`. The real argv is `["b jj jj"]` in 5.1 and `['"b', "jj", "jj"]` in 7. Its literal twin `` echo a`"b jj `` is refused. The same skip lets a dynamic word carry the batch-file metacharacters `& | < > ^ % !` into a `.bat` program (`` run.bat $x`&calc ``), a tab, a blank with a trailing backslash, a single quote without a blank, the `--%` stop-parsing prefix, and a provider prefix `alias:` / `env:` (`Set-Item alias:$x curl`).

## Solution

**A.** Refuse an escaped blank that starts a bare word. `_escape` sees that case as `self._start < 0`. Inside double quotes the word has already begun (`_double_quoted` calls `_literal("", quoted=True)`, `:823`), so the in-quotes case stays accepted. So do the mid-word and trailing cases, because both shells agree on them.

**B.** Every check of the characters a word holds now also runs on a dynamic word's literal text (`word.text`, which is the literal parts only). These characters reach the program whatever the shell computes around them. Their effect also escapes the word: they merge or split the neighbouring arguments, run cmd.exe syntax in a batch file, change how the rest of the line is parsed (`--%`), or change how later commands resolve (provider paths).

Two checks read the **whole value**: the empty argument (`:923`) and the number-like word (`:935`). They stay literal-only. Every PowerShell dynamic word is variadic (`_mark_dynamic(variadic=True)` at `:781`, `:869`, `:879`), so it already stands for zero or more words of any value, and a different reading inside the word is admitted by that mark. The `--` / `--%` check runs on dynamic words too: `--%` is a parser token, and refusing `--$x` costs only usability.

**Closing the class.** All the other checks run before the dynamic mark is set, or refuse dynamic words outright (see "Closure enumeration"). cmd and posix have no finished-word override, so they have no such skip.

### Section 1 -- `src/probos/execution/command_policy.py` (Class A, `_PowerShellLexer._escape`)

SEARCH:
```python
        if following == "\n":  # PowerShell continues the line, which it reads differently inside a word
            raise _Unparseable("a backtick line continuation")
        if following in _PS_EXPANDING_ESCAPES:
```
REPLACE:
```python
        if following == "\n":  # PowerShell continues the line, which it reads differently inside a word
            raise _Unparseable("a backtick line continuation")
        if following == " " and self._start < 0:  # measured: 5.1 and 7 read it as a blank, not as part of the word
            raise _Unparseable("an escaped blank ('` ') at the start of a word, which PowerShell reads as a blank")
        if following in _PS_EXPANDING_ESCAPES:
```

### Section 2 -- `src/probos/execution/command_policy.py` (Class B, `_PowerShellLexer._check_word`)

SEARCH (2a; unique because of the `if word.dynamic:` / `return` pair):
```python
    def _check_word(self, word: _Word) -> None:
        if word.dynamic:
            return
        value = word.text
        if value == "--" or value.startswith("--%"):
            raise _Unparseable("the -- or --% (stop-parsing) token, which PowerShell versions pass differently")
        if not value:
```
REPLACE:
```python
    def _check_word(self, word: _Word) -> None:
        # r1b: every check reads a dynamic word's literal text too; only the "whole" ones need the whole value.
        value = word.text
        whole = not word.dynamic  # a dynamic word is variadic here: it already stands for any words of any value
        if value == "--" or value.startswith("--%"):
            raise _Unparseable("the -- or --% (stop-parsing) token, which PowerShell versions pass differently")
        if whole and not value:
```

SEARCH (2b):
```python
        if word.raw[:1] not in ("'", '"') and _PS_NUMBER_START.match(value) and _PS_INTEGER.fullmatch(value) is None:
```
REPLACE:
```python
        if whole and word.raw[:1] not in ("'", '"') and _PS_NUMBER_START.match(value) and _PS_INTEGER.fullmatch(value) is None:
```

The checks for `"`, the batch metacharacters, a tab or a blank with a trailing backslash, a single quote without a blank, and the provider prefixes are unchanged. They now run on every word. The reason texts are unchanged.

### Section 3 -- `tests/fixtures/ad1328_shell_oracle.json` (live boundary of Class A)

The schema records only lines the policy reads (`policy` is required, and `_reading_problem` fails a refused line, `test_ad1328_s1_shell_oracle.py:131-137`). So the refused forms are pinned by the refusal rows below, and the oracle pins their accepted neighbours live. S17 stands for the trailing case: `a` ` is followed by a separator blank, so the command text does not end in a blank that the transport could trim.

SEARCH:
```json
    {"id": "S14", "dialect": "powershell", "constructs": ["S-WRAP-PS-WORDS"], "requires": ["pwsh"], "text": "pwsh -NoProfile -Command {B} a b", "policy": [["a", "b"]]}
```
REPLACE:
```json
    {"id": "S14", "dialect": "powershell", "constructs": ["S-WRAP-PS-WORDS"], "requires": ["pwsh"], "text": "pwsh -NoProfile -Command {B} a b", "policy": [["a", "b"]]},
    {"id": "S15", "dialect": "powershell", "constructs": ["S-ESC"], "text": "{P} a` b", "policy": [["a b"]], "live": [["a b"]]},
    {"id": "S16", "dialect": "powershell", "constructs": ["S-ESC"], "text": "{P} x` y` z", "policy": [["x y z"]], "live": [["x y z"]]},
    {"id": "S17", "dialect": "powershell", "constructs": ["S-ESC"], "text": "{P} a`  b", "policy": [["a ", "b"]], "live": [["a ", "b"]]},
    {"id": "S18", "dialect": "powershell", "constructs": ["S-DQ", "S-ESC"], "text": "{P} \"` zz\"", "policy": [[" zz"]], "live": [[" zz"]]},
    {"id": "S19", "dialect": "powershell", "constructs": [], "text": "{P} $x` b", "policy": [[null]], "marks": ["v"], "live": [[" b"]]}
```

### Section 4 -- `DECISIONS.md` (one sentence in the repair bullet)

SEARCH:
```
Unicode is validated at model ingress. Contract `prompts/ad-1328-s1-repair-r1.md`.
```
REPLACE:
```
Unicode is validated at model ingress. A differential fuzz on all five shells then closed two PowerShell classes: a dynamic word's literal text gets every character check a literal word gets (only the empty and number checks need the whole value, which a variadic word already stands for), and a bare word may not start with an escaped blank. Contracts `prompts/ad-1328-s1-repair-r1.md` and `prompts/ad-1328-s1-repair-r1b.md`.
```

## Tests (Builders, tests only; never edit `src/`, `tests/fixtures/` or the prompts)

**No existing test or oracle row changes.** The 108-row count test stays as it is. The new rows go in a separate table, appended at the end of `tests/test_ad1328_s1_command_parse_repair.py`, and reuse `test_finding_refusals` and `_accepted`. Existing PowerShell dynamic rows that were checked against the new rule and still hold: arity `:364` (`echo $x "$x" ${x} @a *.py ~ a$1b $env:X '$x' a~b`), `f4_ps_member` neighbour `echo "$a.b"`, `f4_ps_splat_*` neighbours `git push @args ...`, `test_ad1328_s1_command_parse.py:461-469`, `:616-617`, `:655`, oracle S11 and S12.

```python
# --------------------------------------------------------------------------------------
# r1b (prompts/ad-1328-s1-repair-r1b.md) -- two PowerShell classes from the differential fuzz
#   Class A: an escaped blank that starts a bare word (oracle S15-S19 pin the accepted boundary live).
#   Class B: a dynamic word's literal text gets every character check.
# --------------------------------------------------------------------------------------

R1B_REFUSALS: list[tuple[str, str, str, str, str, str]] = [
    ("r1b_ps_escaped_blank_start", "powershell", "echo ` zz", "line", "escaped blank", "echo a` b"),
    ("r1b_ps_escaped_blank_alone", "powershell", "echo ` ", "line", "escaped blank", "echo a`  b"),
    ("r1b_ps_escaped_blank_twice", "powershell", "echo ` ` x", "line", "escaped blank", "echo x` y` z"),
    ("r1b_ps_escaped_blank_variable", "powershell", "echo ` $x", "line", "escaped blank", "echo $x` b"),
    ("r1b_ps_escaped_blank_then_blank", "powershell", "xx `  ww", "line", "escaped blank", 'echo "` zz"'),
    ("r1b_ps_dynamic_quote", "powershell", 'echo $x`"b jj jj', "line", "a double quote inside an argument", "echo $x-b jj jj"),
    ("r1b_ps_dynamic_quote_in_quotes", "powershell", 'echo "$x`"b" jj', "line", "a double quote inside an argument", 'echo "$x b" jj'),
    ("r1b_ps_dynamic_batch_ampersand", "powershell", "run.bat $x`&calc", "line", "batch-file program", "run.bat $x-calc"),
    ("r1b_ps_dynamic_batch_percent", "powershell", "echo a%*", "line", "batch-file program", "echo a*"),
    ("r1b_ps_dynamic_tab", "powershell", 'echo "$x\tb"', "line", "quotes for a program", 'echo "$x b"'),
    ("r1b_ps_dynamic_blank_backslash", "powershell", 'echo "$x a\\"', "line", "quotes for a program", 'echo "$x a\\b"'),
    ("r1b_ps_dynamic_single_quote", "powershell", 'echo "$x\'b"', "line", "single quote in an argument without a blank", 'echo "$x\'b c"'),
    ("r1b_ps_dynamic_provider", "powershell", "Set-Item alias:$x curl", "line", "alias:", "Set-Item x$x curl"),
    ("r1b_ps_dynamic_provider_after_variable", "powershell", "Remove-Item ${x}env:PATH", "line", "env:", "Remove-Item ${x}envPATH"),
    ("r1b_ps_dynamic_stop_parsing", "powershell", "echo --%$x", "line", "the -- or --%", "echo -$x"),
    ("r1b_ps_dynamic_dashdash", "powershell", "git checkout --$x", "line", "the -- or --%", "git checkout -$x"),
]


def test_r1b_refusals_table() -> None:
    ids = [row[0] for row in R1B_REFUSALS]
    assert len(R1B_REFUSALS) == 16
    assert len(set(ids)) == len(ids)
    assert not set(ids) & {row[0] for row in FINDING_REFUSALS}


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "scope", "reason", "neighbour"), R1B_REFUSALS, ids=[row[0] for row in R1B_REFUSALS],
)
def test_r1b_refusals(case_id: str, dialect: Dialect, command: str, scope: str, reason: str, neighbour: str) -> None:
    test_finding_refusals(case_id, dialect, command, scope, reason, neighbour)


# (id, dialect, command, tokens, dynamic flags): what r1b must leave as it was.
R1B_READINGS: list[tuple[str, Dialect, str, tuple[str, ...], tuple[bool, ...]]] = [
    ("s15_mid_word", "powershell", "echo a` b", ("echo", "a b"), (False, False)),  # oracle S15
    ("s16_two_escapes", "powershell", "echo x` y` z", ("echo", "x y z"), (False, False)),  # oracle S16
    ("s17_trailing", "powershell", "echo a`  b", ("echo", "a ", "b"), (False, False, False)),  # oracle S17
    ("s18_in_quotes", "powershell", 'echo "` zz"', ("echo", " zz"), (False, False)),  # oracle S18
    ("s19_after_variable", "powershell", "echo $x` b", ("echo", " b"), (False, True)),  # oracle S19
    ("dynamic_empty_text", "powershell", "echo $x", ("echo", ""), (False, True)),  # the empty check is literal-only
    ("dynamic_number_like", "powershell", "echo 0x1*", ("echo", "0x1*"), (False, True)),  # the number check is literal-only
    ("dynamic_dash_text", "powershell", "echo $x-b", ("echo", "-b"), (False, True)),
    ("cmd_glob_after_quote", "cmd", 'echo "a b"*', ("echo", "a b*"), (False, True)),  # cmd checks per character
    ("posix_glob_after_quote", "posix", 'echo "a b"*', ("echo", "a b*"), (False, True)),  # posix checks per character
]


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "tokens", "dynamic"), R1B_READINGS, ids=[row[0] for row in R1B_READINGS],
)
def test_r1b_readings_unchanged(
    case_id: str, dialect: Dialect, command: str, tokens: tuple[str, ...], dynamic: tuple[bool, ...],
) -> None:
    parsed = _accepted(command, dialect)
    assert len(parsed.segments) == 1, case_id
    assert parsed.segments[0].tokens == tokens, case_id
    assert parsed.segments[0].dynamic == dynamic, case_id
```

`tests/test_ad1328_s1_shell_oracle.py` is unchanged: it parametrizes over the fixture's rows, so S15-S19 run every-host and live under `powershell` and `pwsh`.

## Mutation campaign (rows added to r1's table; anchors are single-line and unique in the amended file)

| Id | Anchor | Mutant | Killer |
|---|---|---|---|
| M23 (re-anchored) | `if whole and not value:` | `if False:` | `f3_ps_empty` |
| M25 (re-anchored) | `if whole and word.raw[:1] not in ("'", '"') and _PS_NUMBER_START.match(value) and _PS_INTEGER.fullmatch(value) is None:` | `if False:` | `f3_ps_hex` |
| M97 | `if following == " " and self._start < 0:  # measured: 5.1 and 7 read it as a blank, not as part of the word` | `if False:` | `r1b_ps_escaped_blank_*` (5 rows) |
| M98 | same | `if following == " ":` | `R1B_READINGS` `s15`-`s19`; the neighbours of `r1b_ps_escaped_blank_start` and `_then_blank` |
| M99 | `# r1b: every check reads a dynamic word's literal text too; only the "whole" ones need the whole value.` | `if word.dynamic: return` (same indent) | `r1b_ps_dynamic_*` (11 rows) |
| M100 | `whole = not word.dynamic  # a dynamic word is variadic here: it already stands for any words of any value` | `whole = True` | `R1B_READINGS` `dynamic_empty_text`, `dynamic_number_like`; arity row `:364` |
| M101 | M25's anchor | `if word.raw[:1] not in ("'", '"') and _PS_NUMBER_START.match(value) and _PS_INTEGER.fullmatch(value) is None:` | `R1B_READINGS` `dynamic_number_like` |

The r1 rows M22, M24, M26, M27 and M66 keep their anchors.

## Closure enumeration (rows added to r1's table)

| Class | Producer or exit | Closed by |
|---|---|---|
| A | `_PowerShellLexer._escape` from `lex` (`:753-754`) at a word start | Section 1 |
| A | `_escape` from `_double_quoted` (`:836-837`) | Not a producer: the word began at `:823`, so `_start >= 0`. Both shells agree (S18). |
| A | posix `\ ` and cmd | posix `_backslash` keeps a literal blank, and dash and bash agree (fuzz: 0 divergences). cmd has no escape character. |
| B | `_PowerShellLexer._check_word` | Section 2. Character checks run on every word; the whole-value checks (empty, number) are literal-only, because every PowerShell dynamic word is variadic (`:781`, `:869`, `:879`). |
| B | `_Lexer._check_word` base no-op (posix, cmd) | No skip. Every posix and cmd refusal is a per-character test in `lex`, `_quoted_run`, `_redirection`, `_backslash`, `_double_quoted` or `_checked_text` (`:503-534`, `:562-588`, `:684-689`, `:710-717`, `:729`, `:988-1009`). Each runs as it reads the character, whether or not the word has been marked dynamic. A cmd glob next to a quote (`"a b"*`) passes the same literal text it would without the glob, and the UCRT reading is admitted by the variadic mark (fuzz: 0 cmd divergences; `cmd_glob_after_quote` row). |
| B | PowerShell words from several parts | None exist: a quote inside a word is refused (`:798-799`, `:820-821`) and so is text after a closing quote (`_begin`, `:447-448`). A word is one quoted string, or bare parts only. |
| B | `_segment` duplication target (`:1057`) | Refuses a dynamic target. |
| B | `_strip_process_wrappers` / `_wrapper_width` (`:1094`, `:1106`, `:1119`, `:1134`, `:1140`) | A dynamic word stops the strip or returns `None`; the program check (`:1146`) or the wrapper reason then refuses. |
| B | `_program_problem` (`:1146`), `_launcher_problem` (`:1204`), `_shell_wrapper` (`:1217`, `readable`) | Refuse. |
| B | `_is_state_mutator` (`:1288`) | Only reached for a segment whose dynamic program `:1146` already refuses. |
| B | `_restrictive_cover` / `_match` (`:1462-1464`, `:1487`), `_is_simple` (`:1709`) | By design (R2): a variadic word covers every remaining word, an allow never matches across one, and the key falls back to a script key. |
| B | PS redirection target | A target is a word: the checks now refuse a dynamic target with these characters. This is over-refusal; a target is not an argv. |

## What This Does NOT Change

The public API, the oracle schema, `test_ad1328_s1_shell_oracle.py`, the 108-row table, posix and cmd lexing, R2 matching, the canonical key, the digest scheme, `operations.py`, and S2a.

## Tracking

DECISIONS.md (Section 4). No PROGRESS or roadmap change: same AD, same PR.

## Acceptance Criteria

- Sections 1-4 applied exactly. The focused tests `test_ad1328_s1_command_parse_repair.py`, `test_ad1328_s1_command_parse.py` and `test_ad1328_s1_shell_oracle.py` pass at `-n 0`, and the live S15-S19 rows pass under both PowerShell shells on the Captain's host.
- M23, M25 and M97-M101 are each killed.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-10-16, blobs above)

```
command_policy.py:753-754  elif ch == "`": self._escape()   (lex, bare)
command_policy.py:786-795  def _escape ... self._literal(following, quoted=True)
command_policy.py:790      if following == "\n":  # PowerShell continues the line ...   (unique)
command_policy.py:823      self._literal("", quoted=True)   (_double_quoted begins the word)
command_policy.py:836-837  elif ch == "`": self._escape()   (_double_quoted)
command_policy.py:917-919  def _check_word ... if word.dynamic: return
command_policy.py:923      if not value:   (unique)
command_policy.py:935      if word.raw[:1] not in ("'", '"') and _PS_NUMBER_START.match(value) ...   (unique)
command_policy.py:781/869/879  self._mark_dynamic(variadic=True)   (every PowerShell dynamic mark)
command_policy.py:447-448  _begin: "text directly after a closing quote"
oracle.json:70             S14 row (unique, last row)
oracle test:63-64          required/optional keys; :131-137 refused line fails a row
repair test:285-334        108-row count test, test_finding_refusals(case_id, dialect, command, scope, reason, neighbour)
DECISIONS.md:21            "... Unicode is validated at model ingress. Contract `prompts/ad-1328-s1-repair-r1.md`."
```

## Absence Verified (2026-10-16)

```
CLAIM: no other finished-word or per-character check skips a dynamic word
RUN:   Grep "dynamic" src/probos/execution/command_policy.py
FOUND: :438-:476 (buffer), :541/:543/:603/:612/:616/:623 (posix marks), :699/:719 (cmd marks), :781/:869/:879 (PS marks),
       :918 (the skip, closed here), :1057, :1076, :1094, :1106, :1119, :1134, :1140, :1146, :1204, :1217, :1288,
       :1462-1464, :1487, :1709
HOLDS: yes -- each is classified in "Closure enumeration"
CLAIM: no existing test reads a PowerShell dynamic word that r1b refuses
RUN:   Grep powershell rows with $ / @ / * / ~ in tests/test_ad1328*.py
FOUND: repair :142-147, :364; parse :444-469, :535, :616-617, :655; evaluation :803; oracle S11, S12
HOLDS: yes -- none has `"`, & | < > ^ % !, a tab, ' without a blank, a blank with a trailing \, --, --% or a provider prefix in its literal text
```

## Prior Art and Blind Spots

A ProbOS-specific grammar repair; no external search. Blind spots considered:

- A variable's runtime value containing `"` or a blank with a trailing `\` can merge the words after it in 5.1. That cannot be refused statically. It is covered because the word is variadic: a restrictive pattern aligns across it, and an allow prefix never includes it.
- A `#` directly after a variable (`$x#y`): the policy reads it as literal. If PowerShell reads a comment there, words are dropped, so the policy judges a superset. Not measured live.
- Number-like dynamic words (`1kb$x`, `0x1*`) are accepted because the variadic mark covers them. Not measured live.
