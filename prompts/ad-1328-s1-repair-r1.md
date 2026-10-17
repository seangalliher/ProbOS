# AD-1328 S1 repair, round 1 -- a closed command grammar: read only what each shell and each receiving program is known to read, refuse the rest

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16

**Status:** BUILD-READY. Repair of slice S1 of AD-1328 (#1530) after Diff Reviewer round 1 (`logs/architect/ad1328-s1-review-r1-report.md`: 12 findings, P1 x10, P2 x2, all ordinary reach, verdict REQUEST CHANGES). No new AD or BF number (`scripts/ad_ceiling.py`, run 2026-10-16: ceiling AD-1341 from issue titles, next AD-1342; AD-1328 is #1530's).
**Base:** `26250c9c`; contract commit `8c9e9553` (`prompts/ad-1328-s1-command-policy-core.md`); the S1 candidate staged in this worktree (staged blobs: `command_policy.py` `28f39d09e68e`, `operations.py` `27b380b78e51`; `git diff --stat` empty, so the working tree equals the index; the orchestrator's tree id `40db5331` was not recomputed here, `git write-tree` is not an allowed bridge command). Branch `feat/ad1328-s1-20261016-26250c9c`.
**Dependencies:** none unbuilt. S2a (`prompts/ad-1328-s2a-command-policy-wiring.md`, untracked) is downstream; its required amendments are listed below.
**Estimated tests:** existing three files change in the named tests below; about 45 new test functions (about 420 cases with parametrisation) across the three S1 files and one new file, `tests/test_ad1328_s1_shell_oracle.py`.

One-line summary: S1's reader is replaced by a closed grammar per dialect, so a construct is read only when its meaning to the shell and to the program receiving the words is modelled and tied to a reference-shell oracle row; dynamic words become one-word or zero-or-more, matched by alignment; launchers are classified in one table and unwrapped only in modelled forms, with the wrapper's context inherited; pin proof needs the starting lookup context; a PowerShell string is not an invocation; Unicode is validated at model ingress and malformed command text never raises.

---

## Problem

Twelve findings, each a class with several producers (`CP` = `src/probos/execution/command_policy.py` at the staged blob; `OM` = `src/probos/config_models/operations.py`). Seven reproduced by the orchestrator (`logs/architect/ad1328-s1-r1-verification.txt`).

| # | Finding (class) | Producers in S1 |
|---|---|---|
| F1 | Pin proof survives changed shell state | `_allow_match` `CP:1082-1110` resolves every bare name in the initial context; nothing tracks `cd`/`export`/`Set-Location`/`set`/`PATH`. |
| F2 | A dynamic word is exactly one word | `_match` `CP:1064-1075`: `len(tokens) < len(pattern)` and one-position skipping; cmd `%X%` adds syntax (`_CmdLexer._percent` `CP:578-587`). |
| F3 | Lexical words are not native argv | cmd `^`/quote/backslash (`CP:539-576`); PS 5.1 empty and embedded-quote strings (`CP:646-685`); Win32 trailing-space names; MSYS conversion. |
| F4 | Expansion markers fall through to literal | PS `_variable` `CP:687-709` (`$1`, Unicode), `_splat` `CP:711-723` (`@?` `@$` `@^`); cmd `^%X%`, `%X: =%`; bash `a=~`. |
| F5 | Wrapper options become program names | `_wrapper_width` `CP:872-893` (`command -p`/`--`, repeated `nice -n`, `stdbuf` `--`). |
| F6 | Wrapper script keeps outer quoting | `_rest_of_line` `CP:937-941` joins `raw` spellings; both producers (PowerShell and cmd wrappers). |
| F7 | Unwrapping drops governing context | `_unwrap` `CP:1004-1021` and the canonical loop `CP:1315-1329` drop parent assignments, redirections, process wrappers. |
| F8 | Operator grammar differs from consumers | `&>`/`|&` (`CP:416`, `:429-435`) bash-only; PS `&&`/`||` (`CP:637-640`, `:725-729`) absent in 5.1; PS `>` mid-word and stream numbers (`CP:630-634`); cmd multi-digit descriptors (`CP:547-551`). |
| F9 | Known launchers stay ordinary programs | `_OPAQUE_PROGRAMS` `CP:86-101` misses PS `return`/`throw`/`exit`, Windows spellings of POSIX wrappers, `bash.exe`, zsh/fish/csh/tcsh/busybox/wsl/ssh/uv/npx. |
| F10 | PS string expression and invocation share a key | `_segment` `CP:821-824` discards the call operator; `_is_simple`/`canonical_command` `CP:1279-1329`. |
| F11 | Newline handling changes literal words | `_checked_text` `CP:780-786` rewrites CRLF; `_Lexer._escape` `CP:367-374` continuation in cmd and PS. |
| F12 | Lone surrogates cross the RFC 8785 boundary | `OM:60-123` accept them; `policy_digest` `CP:1271-1276` and `CanonicalCommand.key` raise `UnicodeEncodeError`. |

The reviewer also found that the S1 tests have no reference-shell oracle, so passing them is not conformance evidence.

## Solution

Replace `command_policy.py` whole (Section 2, a NEW-file block: about 70% of the module changes), amend `operations.py` with four small blocks (Section 1), add a probe and an oracle data file (Sections 3-4) and one `DECISIONS.md` block (Section 5). The public API S2a uses is unchanged; two fields are added to `CommandSegment` with defaults.

### R1 -- Governing principle and grammar (decided: closed-world)

| Option | Verdict |
|---|---|
| **A. Closed-world grammar** per dialect, each accepted construct tied to an oracle row; the rest unparseable (`unparseable_decision`, default `escalate`, Design Principle 13(c)). | **Chosen.** Converges: a refusal can only make a decision stricter, so the safety claims shrink to the accepted constructs, each checked live. Matches Codex's allow-list of tree-sitter node kinds (below). |
| B. Model more of each shell, including native argument marshalling per callee | Rejected: the callee is unknown (UCRT, MSYS2/Cygwin, a batch file through `cmd.exe`, cmdlets); not tractable and not checkable. |
| C. Narrow dialect scope (drop a dialect) | Rejected: `cmd` (`RunCommandTool`) and Windows PowerShell 5.1 (`ShellCommandAgent`) are the Captain's call sites. |

**Safety direction (stated rule).** A refusal or a dynamic mark can only escalate or withhold `allow`; an error there costs usability, not safety. A literal reading is a safety claim: every accepted literal construct below has a live oracle row (R6). Dynamic and refused constructs make no claim about argv, so a policy row (tests) suffices.

**Text, all dialects.** Never rewritten. Refused: a lone surrogate (F12), CR (F11), other C0 controls and DEL. `cmd`: newline refused; `cmd` and `powershell`: any non-ASCII character refused (PowerShell reads several as syntax; a Windows program reading ANSI argv may best-fit map one to `"` or `-`, the WorstFit class). `posix`: non-ASCII allowed except categories `Cc Cf Cs Co Cn Zl Zp Zs` (bidi and zero-width controls, unusual spaces, line separators).

**`posix`** (consumer `/bin/sh -c` = dash or bash on a POSIX host; read only what both read alike):

| Construct | Accepted reading | Refused |
|---|---|---|
| Blanks, words | space/tab separate; any other accepted character literal (`HEAD~1`, `a=b`, `x!y`, `%`, `^`, `,`, `@`) | -- |
| Quoting | `'...'` literal (may hold newlines); `"..."` with `\` escaping `$ \` " \` and newline (continuation), other `\` literal; `\x` outside quotes; `\`+newline removed (both contexts); adjacent parts concatenate | backtick substitution (use `$( )`); `$'...'`, `$"..."`; trailing `\` |
| Expansion (dynamic) | `$NAME`, `${NAME}`, `$0-$9`, `$@ $* $# $? $$ $! $-`, `${N}`/`${@}` etc. (fullmatch), `$( )`; unquoted `* ? [ { }`; `~` at word start or after unquoted `=`/`:` | `$((`, `$[`, any other `$` form (`$` + blank/end/non-ASCII), `${X:-...}` and every other `${...}` operator |
| Operators | `;` `&&` `||` `|` `&` newline; `&&`/`||`/`|` + newline continues | `|&`, `&>`, `&>>`, `;;`, `;&`, `(`, `)` |
| Redirections | `<` `>` `>>` `<&` `>&` with an optional single-digit descriptor written against them; `>&`/`<&` target one digit or `-` | here-docs/strings `<<*`, `>|`, `<>`, `<(`/`>(`, multi-digit descriptors, `{name}>` |
| Comments | `#` at word start to end of line | -- |
| Assignments | leading unquoted `NAME=value` (context, kept out of tokens) | an assignment-only segment (no command) is unparseable |

**`cmd`** (consumer `cmd.exe /c` from `create_subprocess_shell`; the words the started program reads under the UCRT rules, read alike by MSYS2/Cygwin programs):

| Construct | Accepted | Refused |
|---|---|---|
| Characters | ASCII printable, space, tab | `%` and `!` anywhere, even quoted (expanded before quotes and operators are read; `!` when the registry enables delayed expansion); unquoted `^ ( ) , ; '`; newline |
| Quoting | `"..."` runs (operators and `^ ( ) , ; '` literal inside); a word is unquoted and quoted runs concatenated, quotes removed; a lone `""` word is an empty argument | `\` immediately before any `"`; `""` inside a word (`"a""b"`, `a""b`) |
| Dynamic | `* ? [ {` anywhere in a word, quoted or not (the callee may glob); a word starting with unquoted `~` or `@` (tilde, response files): all variadic | -- |
| Operators | `&` `&&` `||` `|` | -- |
| Redirections | `<` `>` `>>` `<&` `>&` with an optional single-digit descriptor that is a whole word; `>&`/`<&` target one digit | a redirection written against any other word (`a2>f`, `12>f`) |
| Program word | `[A-Za-z0-9_.+\\: -]`, blanks only quoted, `:` only after a drive letter at index 1 | `/`, `=`, `@`, `~` (8.3 short names), a trailing blank or dot (Win32 drops them), a word cmd.exe reads as an internal command plus a delimiter (`echo.exe`, `cd\x`) |

**`powershell`** (consumers Windows PowerShell 5.1 `-Command` and PowerShell 7 `-Command`; read only what both read alike, and only argument values both pass to a program unchanged):

| Construct | Accepted | Refused |
|---|---|---|
| Words | bareword of ASCII letters, digits, `_ - . / \ : = + % ~ ^ ! @ #` (mid-word); a quote may only start a word, and nothing may follow its close | quote mid-word, text after a closing quote; `( ) { } [ ] , <` |
| Quoting | `'...'` with `''`; `"..."` with backtick escapes, `""`, `$` expansion; backtick escape outside quotes | newline inside quotes; backtick + newline (continuation); backtick + `0 a b e f n r t u v` (A1, kept); trailing backtick |
| Argument value (each literal word, as passed to a program) | non-empty; no `"`; no tab; no trailing `\` when it holds a blank; `'` only with a blank (PowerShell then wraps it in double quotes); unquoted number-like words only as `-?(0|[1-9][0-9]{0,8})` | `''` (5.1 drops it); `a"b`; `& | < > ^ % !` (a batch-file callee re-reads them as `cmd.exe` syntax, the BatBadBut class); `--` and `--%` (5.1 and 7 pass them differently); `0x10`, `007`, `1kb`, `1.5`; `alias: function: env: variable:` paths (they change how later commands resolve) |
| Dynamic (all variadic: 5.1 drops empty strings, arrays pass as many) | `$name`, `$scope:name`, `${name}`/`${scope:name}`, `$?` `$^` `$$`, `@name` splat at word start; `*` `?`; `~` at word start | `$(`, member access/index after an unquoted variable (`$a.b`, `$a[0]`, `$a:`), any other `$` or `@` form (`@?`, `@$`, `@(`, `@'`) |
| Operators | `;` `|` newline (`|` + newline continues); `&` only as the call operator at statement start followed by a blank | `&&`, `||` (absent in 5.1), background `&` |
| Redirections | `>` `>>` with an optional stream `1-6` or `*` written as a whole word against it; `N>&1` for `N` in `2-6 *` | a redirection written against any other word, `1>&1`, any other `>&` form |
| Comments | `#` at word start | `<#` (via `<`) |
| Program word | bare `[A-Za-z_.\\/][A-Za-z0-9_.+\\/:-]*`; after `&`, quoted or bare `[A-Za-z0-9_.+\\/: -]`; `:` only after a drive letter | a quoted string without `&` (an expression, F10); a word PowerShell may read as an expression (starts with a digit, `-`, `$`...); `~`; trailing blank or dot; keywords |

**Usability guard (corpus, about 30 per dialect).** Every line below parses (`unparseable is None`), every segment has `unparseable is None`, and the tokens are as given (M2 `test_usability_corpus`). Under a deny-list policy (`forbid ["curl"]`, `unmatched_decision="allow"`) every line evaluates to `allow`.

```python
USABILITY_CORPUS = {
    "posix": [
        ("git status", [("git", "status")]),
        ("git status --short", [("git", "status", "--short")]),
        ("git diff HEAD~1 -- src/probos/config.py", [("git", "diff", "HEAD~1", "--", "src/probos/config.py")]),
        ("git log --oneline -20", [("git", "log", "--oneline", "-20")]),
        ("git commit -m 'fix: handle empty input'", [("git", "commit", "-m", "fix: handle empty input")]),
        ('git commit -m "fix: the \\"x\\" case"', [("git", "commit", "-m", 'fix: the "x" case')]),
        ("git add src/probos/execution/command_policy.py tests/test_x.py", [("git", "add", "src/probos/execution/command_policy.py", "tests/test_x.py")]),
        ("git push origin feat/x", [("git", "push", "origin", "feat/x")]),
        ("git checkout -b feat/new-branch", [("git", "checkout", "-b", "feat/new-branch")]),
        ("pytest tests/test_x.py -q -n 0", [("pytest", "tests/test_x.py", "-q", "-n", "0")]),
        ('pytest -k "parse and not slow" -x', [("pytest", "-k", "parse and not slow", "-x")]),
        ("python -m pytest tests -q", [("python", "-m", "pytest", "tests", "-q")]),
        ("python -m pip install -e .", [("python", "-m", "pip", "install", "-e", ".")]),
        ('pip install "requests>=2.31"', [("pip", "install", "requests>=2.31")]),
        ("uv pip install ruff", [("uv", "pip", "install", "ruff")]),
        ("uv sync", [("uv", "sync")]),
        ("npm install", [("npm", "install")]),
        ("npm run build", [("npm", "run", "build")]),
        ("npm test -- --watch=false", [("npm", "test", "--", "--watch=false")]),
        ("ruff check src tests", [("ruff", "check", "src", "tests")]),
        ("ruff format --check .", [("ruff", "format", "--check", ".")]),
        ("mypy src/probos/execution/command_policy.py", [("mypy", "src/probos/execution/command_policy.py")]),
        ("make test", [("make", "test")]),
        ("ls -la src", [("ls", "-la", "src")]),
        ("cat README.md", [("cat", "README.md")]),
        ("grep -rn 'def parse' src/probos", [("grep", "-rn", "def parse", "src/probos")]),
        ("cd src && ls", [("cd", "src"), ("ls",)]),
        ("git status && git diff --stat", [("git", "status"), ("git", "diff", "--stat")]),
        ("pytest -q 2>&1 | tail -n 20", [("pytest", "-q"), ("tail", "-n", "20")]),
        ("python scripts/run_test_gate.py --label x --receipt logs/gates/x.receipt.json", [("python", "scripts/run_test_gate.py", "--label", "x", "--receipt", "logs/gates/x.receipt.json")]),
        ("find . -name '*.py' -newer setup.cfg", [("find", ".", "-name", "*.py", "-newer", "setup.cfg")]),
    ],
    "cmd": [
        ("git status", [("git", "status")]),
        ("git status --short", [("git", "status", "--short")]),
        ("git diff HEAD~1 -- src/probos/config.py", [("git", "diff", "HEAD~1", "--", "src/probos/config.py")]),
        ("git log --oneline -20", [("git", "log", "--oneline", "-20")]),
        ('git commit -m "fix: handle empty input"', [("git", "commit", "-m", "fix: handle empty input")]),
        ("git add src\\probos\\execution\\command_policy.py tests\\test_x.py", [("git", "add", "src\\probos\\execution\\command_policy.py", "tests\\test_x.py")]),
        ("git push origin feat/x", [("git", "push", "origin", "feat/x")]),
        ("git checkout -b feat/new-branch", [("git", "checkout", "-b", "feat/new-branch")]),
        ("pytest tests\\test_x.py -q -n 0", [("pytest", "tests\\test_x.py", "-q", "-n", "0")]),
        ('pytest -k "parse and not slow" -x', [("pytest", "-k", "parse and not slow", "-x")]),
        ("python -m pytest tests -q", [("python", "-m", "pytest", "tests", "-q")]),
        ("python -m pip install -e .", [("python", "-m", "pip", "install", "-e", ".")]),
        ('pip install "requests>=2.31"', [("pip", "install", "requests>=2.31")]),
        ("uv pip install ruff", [("uv", "pip", "install", "ruff")]),
        ("npm install", [("npm", "install")]),
        ("npm run build", [("npm", "run", "build")]),
        ("ruff check src tests", [("ruff", "check", "src", "tests")]),
        ("ruff format --check .", [("ruff", "format", "--check", ".")]),
        ("mypy src\\probos\\execution\\command_policy.py", [("mypy", "src\\probos\\execution\\command_policy.py")]),
        ("make test", [("make", "test")]),
        ("dir src", [("dir", "src")]),
        ("type README.md", [("type", "README.md")]),
        ('findstr /n "def parse" src\\probos\\config.py', [("findstr", "/n", "def parse", "src\\probos\\config.py")]),
        ("cd src && dir", [("cd", "src"), ("dir",)]),
        ("git status && git diff --stat", [("git", "status"), ("git", "diff", "--stat")]),
        ("pytest -q 2>&1 | findstr FAILED", [("pytest", "-q"), ("findstr", "FAILED")]),
        ("python scripts\\run_test_gate.py --label x --receipt logs\\gates\\x.receipt.json", [("python", "scripts\\run_test_gate.py", "--label", "x", "--receipt", "logs\\gates\\x.receipt.json")]),
        ('"C:\\Program Files\\Git\\cmd\\git.exe" status', [("C:\\Program Files\\Git\\cmd\\git.exe", "status")]),
        ("d:\\ProbOS\\.venv\\Scripts\\python.exe -m pytest -q", [("d:\\ProbOS\\.venv\\Scripts\\python.exe", "-m", "pytest", "-q")]),
        ("git log --pretty=oneline -5", [("git", "log", "--pretty=oneline", "-5")]),
        ("echo done", [("echo", "done")]),
    ],
    "powershell": [
        ("git status", [("git", "status")]),
        ("git status --short", [("git", "status", "--short")]),
        ("git diff HEAD~1 src/probos/config.py", [("git", "diff", "HEAD~1", "src/probos/config.py")]),
        ("git log --oneline -20", [("git", "log", "--oneline", "-20")]),
        ("git commit -m 'fix: handle empty input'", [("git", "commit", "-m", "fix: handle empty input")]),
        ('git commit -m "fix: handle empty input"', [("git", "commit", "-m", "fix: handle empty input")]),
        ("git add src/probos/execution/command_policy.py tests/test_x.py", [("git", "add", "src/probos/execution/command_policy.py", "tests/test_x.py")]),
        ("git push origin feat/x", [("git", "push", "origin", "feat/x")]),
        ("git checkout -b feat/new-branch", [("git", "checkout", "-b", "feat/new-branch")]),
        ("pytest tests/test_x.py -q -n 0", [("pytest", "tests/test_x.py", "-q", "-n", "0")]),
        ("pytest -k 'parse and not slow' -x", [("pytest", "-k", "parse and not slow", "-x")]),
        ("python -m pytest tests -q", [("python", "-m", "pytest", "tests", "-q")]),
        ("python -m pip install -e .", [("python", "-m", "pip", "install", "-e", ".")]),
        ("pip install requests", [("pip", "install", "requests")]),
        ("uv pip install ruff", [("uv", "pip", "install", "ruff")]),
        ("npm install", [("npm", "install")]),
        ("npm run build", [("npm", "run", "build")]),
        ("ruff check src tests", [("ruff", "check", "src", "tests")]),
        ("ruff format --check .", [("ruff", "format", "--check", ".")]),
        ("mypy src/probos/execution/command_policy.py", [("mypy", "src/probos/execution/command_policy.py")]),
        ("make test", [("make", "test")]),
        ("Get-ChildItem src", [("Get-ChildItem", "src")]),
        ("Get-Content README.md", [("Get-Content", "README.md")]),
        ("Select-String -Path src/probos/config.py -Pattern 'def parse'", [("Select-String", "-Path", "src/probos/config.py", "-Pattern", "def parse")]),
        ("Set-Location src; Get-ChildItem", [("Set-Location", "src"), ("Get-ChildItem",)]),
        ("git status; git diff --stat", [("git", "status"), ("git", "diff", "--stat")]),
        ("pytest -q 2>&1 | Select-Object -Last 20", [("pytest", "-q"), ("Select-Object", "-Last", "20")]),
        ("python scripts/run_test_gate.py --label x --receipt logs/gates/x.receipt.json", [("python", "scripts/run_test_gate.py", "--label", "x", "--receipt", "logs/gates/x.receipt.json")]),
        ("& 'C:\\Program Files\\Git\\cmd\\git.exe' status", [("C:\\Program Files\\Git\\cmd\\git.exe", "status")]),
        ("d:\\ProbOS\\.venv\\Scripts\\python.exe -m pytest -q", [("d:\\ProbOS\\.venv\\Scripts\\python.exe", "-m", "pytest", "-q")]),
        ("Write-Output done", [("Write-Output", "done")]),
    ],
}
```

Measured usability costs, accepted: `cmd` refuses `%` (so `git log --format=%H` escalates; `--pretty=oneline` works), `^` (`HEAD^`; `HEAD~1` works), `!`, single quotes, non-ASCII; PowerShell refuses `--` (`git diff -- path` escalates), `'requests>=2.31'` (`>`), `&&`; `uv run`, `npx`, `poetry run` escalate (launchers). Each escalates; none is `allow`.

### R2 -- Dynamic words and matching (closes F2, F4)

- A dynamic word stands for **one** word of any value (POSIX quoted expansions `"$X"`, `"${X}"`, `"$(...)"`, `"$#"`; tilde) or, when **variadic**, for **zero or more** words of any value (every unquoted POSIX expansion, `"$@"`, globs and braces; every `cmd` and PowerShell dynamic word). `CommandSegment.dynamic[i]` keeps its meaning; new `CommandSegment.variadic[i]` says which.
- **Restrictive match (`_restrictive_cover`, bounded):** scan words after the program; a literal word must equal the next pattern word; a one-word dynamic word supplies the next pattern word; a variadic word supplies every remaining pattern word, so it matches at once. The scan stops when the pattern is covered or a literal differs: at most `len(pattern) - 1` steps (no backtracking is needed, because a variadic word ends the search). `matched_prefix` is the words up to the cover.
- **Allow never matches across one:** an `allow` rule requires its first `len(pattern)` words to be literal and equal (D4's proof requirement): a computed word is no proof of what the program receives.
- **Recognised versus refused markers:** the R1 tables. Every `$`/`@`/`%`/`!` form not listed as dynamic is refused; none falls through to literal (F4's class: PS `$1` and `a$1b` are dynamic; PS Unicode variable names are refused as non-ASCII; `@?` `@$` `@^` refused; cmd `^%X%` and `%X: =%` refused; POSIX `a=~` is dynamic; POSIX `$` + anything unmodelled refused).

### R3 -- Wrappers, launchers and inherited context (closes F5, F6, F7, F9)

**Decision rule for a launcher.** A program is a launcher when its documented primary purpose, or that of one of its subcommands, is to start a program that its own arguments name (`nice git push` runs `git push`). A launcher is either unwrapped in an exactly modelled form or unparseable. Programs that run code found in files or configuration (`make`, `npm run`, `pytest`, `python script.py`) or in an option's value (`find -exec`, `python -c`, `git -c alias.x=!cmd`) remain the documented boundary of a prefix-rule language; so does `git -C . push`.

**One central classification** (`_classify`-style tables in Section 2, all compared on `windows_program_stem(name)`, so `.exe`/`.cmd` spellings and case are normalised in every dialect):

| Class | Members | Treatment |
|---|---|---|
| Process wrappers (`_PROCESS_WRAPPERS`) | `command nice nohup stdbuf time timeout` | POSIX, exact basename only: unwrapped in the forms below. Any other spelling (`nice.exe`, `NICE`) and every Windows dialect: unparseable. |
| Unwrappable shells | `sh bash dash` (POSIX outer, exact basename); `cmd` (cmd outer); `powershell pwsh` (cmd or PowerShell outer) | Unwrapped in the forms below; any other form, spelling or outer dialect (cross-family: `bash` from cmd, `pwsh` from POSIX, `cmd` from PowerShell): unparseable. |
| Other shells (`_OTHER_SHELLS`) | `zsh ksh ksh93 mksh pdksh ash yash posh rbash fish csh tcsh nu elvish xonsh busybox toybox wsl wslhost` | Unparseable (grammars not modelled; `busybox` runs applets). |
| Launchers everywhere | `env sudo doas su runuser pkexec chroot setsid setpriv ionice chrt taskset numactl flock unshare nsenter xargs parallel watch strace ltrace gdb valgrind firejail bwrap systemd-run script expect ssh npx pnpx bunx uvx pipx runas` | Unparseable. |
| Dialect launchers | POSIX `eval exec source . alias unalias enable shopt trap builtin noglob`; cmd `call start forfiles doskey`; PowerShell `invoke-expression iex invoke-command icm start-process saps start start-job sajb start-threadjob foreach-object % foreach where-object ? where invoke-item ii invoke-history ihy r set-alias sal new-alias nal import-module ipmo .` | Unparseable. |
| Keywords | POSIX `! [[ ]] { } case coproc do done elif else esac fi for function if in select then until while`; cmd `for goto if rem`; PowerShell's reserved words incl. `return throw exit trap` | Unparseable. |
| Subcommand launchers | `uv:run npm:exec,x pnpm:exec,dlx yarn:exec,dlx bun:x,exec poetry:run pdm:run hatch:run pipenv:run conda/mamba/micromamba:run docker/podman:run,exec kubectl:exec,run nix:run,shell,develop rye:run` | Unparseable when any later word is dynamic or equals a listed subcommand (any position, so options before the subcommand do not hide it). |

**Process-wrapper option grammars (POSIX), closed.** `command [-p] PROG` (`-p`: lookup on the default PATH, so pin proof is withheld); `command -v|-V ...` runs nothing (ordinary program `command`); `nice [-n N] PROG` (N `-?[0-9]{1,3}`, exactly one `-n`); `nohup PROG`; `time PROG`; `timeout DURATION PROG`; `stdbuf -[ioe]MODE... PROG` (glued modes only). **After the modelled prefix, a program word that starts with `-` makes the segment unparseable** (closes F5's class for every wrapper: `command --`, `-pv`, a second `nice -n`, `stdbuf --`, `--output=`, `timeout --foreground`, `nohup --`). At most four wrappers.

**Shell-wrapper forms and transport (closes F6).** The script is rebuilt from the **values** the launcher receives, never from outer spelling:
- POSIX: `sh|bash|dash -c S`, `-lc S`, `-cl S`, `-l -c S`, `--login -c S`; exactly one script word, no `$0` arguments; `S` is the dequoted word (execve passes it unchanged). `-l` = login shell = lookup context changed.
- cmd outer: `cmd [/d] /c REST` where no word after `/c` contains a `"` (cmd's `/c` quote-stripping rule depends on the filesystem); `REST` = the words' values joined by one blank (the outer cmd applied its own redirections and split at its own operators; `%`/`^`/`!` are refused, so the outer passes the text unchanged).
- cmd or PowerShell outer: `powershell|pwsh [-NoProfile|-NoLogo|-NonInteractive|-ExecutionPolicy P]... -Command|-c ARGS...`; script = the argument values joined by one blank (PowerShell joins `-Command` arguments; each value is CRT-faithful under the R1 constraints). Without `-NoProfile`, lookup context changed. Script `-` (stdin) or empty: unparseable.
- No shell argument may be dynamic; nesting counts against `max_nesting`.

**Inherited context (closes F7).** The segments of an unwrapped script, and of substitutions inside it, inherit the wrapper segment's `assignments`, `redirections` and `wrappers` (parent first) and its `lookup_changed`. So `X=1 sh -c 'git status'` has `assignments == ("X=1",)` and an `allow` rule does not match it; restrictive rules still do. A substitution at the top level does not inherit the enclosing command's assignments (they apply to that command only).

### R4 -- Lookup context (closes F1)

`CommandSegment.lookup_changed` (new, default None) records why the program may not be the one the command's starting PATH and working directory find:
- **A state mutator anywhere in the parsed line** (any segment, any depth, before or after): POSIX `cd pushd popd export unset hash set readonly declare typeset local`; cmd `cd chdir pushd popd set path setlocal endlocal` and a drive change `D:`; PowerShell `cd chdir sl set-location pushd push-location popd pop-location` and `D:`. Every segment of the line gets "the command changes the working directory or the environment (NAME)". Line-wide rather than order-aware: pipelines and `&` run concurrently, and the cost is one escalation per pinned rule.
- A login shell (`bash -lc`), PowerShell without `-NoProfile`, `command -p`.
- PowerShell `Env:`/`alias:`/`function:`/`variable:` paths are refused outright (R1), and `$env:X = ...` has a dynamic program, so neither needs this field.

**Pin proof** is available only when `lookup_changed is None`, or the program is written as a path (an absolute path is context-free; a relative one never equals a pin). Otherwise a pinned `allow` gives `forbid` with `pin_violation=True` and a justification naming the cause and "is not proven", consistent with D4's "unproven is refused". Unpinned `allow`, restrictive rules and canonical `argv` keys (R5) are as stated there.

### R5 -- Remaining classes (closes F3, F8, F10, F11, F12)

- **F3 native argv.** cmd: no `^`; `\` before `"` refused; `""` inside a word refused; single quotes refused outside double quotes (MSYS2/Cygwin read them as quotes when globbing is on); program words lose nothing to Win32 (no trailing blank/dot, no `~`, no `/`). PowerShell: the argument-value rules in R1 (empty, `"`, trailing `\` with a blank, `'` without a blank, batch metacharacters, numbers, `--`). The words recorded are then the program's argv under both UCRT and MSYS2/Cygwin rules; `*?[{` and leading `~`/`@` stay variadic because a callee may expand them. A cmd internal command (`dir`, `echo`, `del`) reads the raw line, so its canonical key is a script key.
- **F8 operators.** Per-consumer intersection: POSIX refuses `&>`, `&>>`, `|&`, `>|`, `<>`, multi-digit and `{name}` descriptors, a `>&`/`<&` target other than a digit or `-`; PowerShell refuses `&&`, `||`, a redirection glued to a word other than a stream `1-6`/`*`, and `>&` other than `2-6|*>&1`; cmd refuses a redirection glued to any word but a whole single digit, and a `>&` target other than a digit.
- **F10 call operator.** In PowerShell a segment whose first word starts with a quote and has no `&` before it is unparseable ("an expression, not a command"); with `&` it is an invocation. The two never share a key: one is unparseable (script key of the text), the other an argv key.
- **F11 newlines.** No CRLF rewriting; CR refused everywhere; cmd refuses newline; PowerShell refuses a newline inside quotes and backtick-newline; POSIX keeps quoted newlines literal and removes `\`+newline (dash and bash agree).
- **F12 Unicode.** Models refuse lone surrogates in every string field at ingress (Section 1). The reader refuses them as "not valid Unicode text" without raising; `canonical_command` of such text returns the two-part script key `("probos.command_policy/malformed-utf16le-hex", <utf-16-le surrogatepass hex>)` (every other script key has one part, so no collision) and its `key` never raises.
- **Canonical key (D6 amended).** `argv` only for exactly one segment that is readable, all-literal, without assignments, redirections or wrappers (own or inherited), with `lookup_changed is None`, and not a cmd internal command; everything else is `("script", <outer dialect>, (<exact original text>,))`. Wrapper variants without context still share the `argv` key (`sh -c 'git  status'`, `cmd /c git status`, `pwsh -NoProfile -Command "git status"` = `git status`); `bash -lc` and `pwsh -Command` (no `-NoProfile`) no longer do. The script key no longer strips wrappers (A2's loop is retired: the full parse bounds nesting).

### R6 -- Conformance evidence: the reference-shell oracle

- **Data:** `tests/fixtures/ad1328_shell_oracle.json` (Section 4): 53 rows of `(dialect, text with placeholders)` -> the policy's reading (literal words, or `null` for a dynamic word, with marks `l`/`o`/`v`) and the argv each probe invocation receives, optionally per shell. Placeholders: `{P}` the dialect's probe prefix (POSIX `'<py>' '<probe>'`, cmd `"<py>" "<probe>"`, PowerShell `& '<py>' '<probe>'`), `{B}` the bare prefix `<py> <probe>` (rows needing it are skipped live when either path holds a character outside `[A-Za-z0-9_.:\\/-]`). Substitution is `str.replace`, never `str.format` (rows contain braces).
- **Probe:** `tests/fixtures/ad1328_argv_probe.py` (Section 3) appends `json.dumps(sys.argv[1:])` to `$AD1328_PROBE_LOG`: the argv a UCRT/CPython program receives.
- **Policy check (every host):** the text with a fixed synthetic prefix (`/opt/ad1328/python3` and `/opt/ad1328/probe.py` for POSIX; `C:\ad1328\python.exe` and `C:\ad1328\probe.py` for cmd and PowerShell) parses, and the probe segments' words after the prefix equal the row (literals, marks).
- **Live check (only where the shell exists):** POSIX rows under `dash` and `bash` found on PATH, off Windows only (Linux CI has both; MSYS argument transport on Windows is not the reference); cmd rows under `subprocess.run(text, shell=True)` on Windows (exactly `create_subprocess_shell`'s `cmd.exe /c "..."`); PowerShell rows under `["powershell", "-NoProfile", "-Command", text]` (Windows) and `["pwsh", "-NoProfile", "-Command", text]` (wherever found), exactly `ShellCommandAgent`'s argv. The live text uses the real interpreter and probe paths and is re-checked by the policy first. Each live argv must be admitted by a distinct probe segment of the policy reading (literal equal, `o` one word, `v` any number), the invocation count is `runs` (default: the number of probe segments), and rows with `live` must match it exactly (order-insensitive).
- **Construct ties:** every accepted literal construct (R1) has an id (`P-*`, `C-*`, `S-*`), listed in Section 4's `constructs`; a test asserts each id appears in at least one row.
- **Provenance:** I could not run the reference shells (the bridge denied executing dash). The expectations are authored from each shell's documented grammar; the **install step runs the live oracle on this host** (cmd.exe, Windows PowerShell 5.1, pwsh 7.6.7) and CI runs the POSIX rows (ubuntu-latest: dash, bash, pwsh). The orchestrator records the shell versions in `provenance.verified_on`. **A failing live row is a hard stop to the Architect** with the observed argv; do not edit a row to pass.

### R7 -- Delivery

Section 2 is the whole module (replace the file). Section 1 is four SEARCH/REPLACE blocks against the current `operations.py` (each SEARCH occurs once). Sections 3-4 are new files; Section 5 one `DECISIONS.md` block. Builders (Sonnet 5.5) write tests only: R-M1..R-M4 below. The mutation campaign below replaces the S1 table and runs once, by the orchestrator, on the committed tree.

## Amendments to the S1 contract

| S1 item (`prompts/ad-1328-s1-command-policy-core.md`) | Overridden by |
|---|---|
| D3 *Compound boundaries* (`|&` in POSIX; `&&`/`||` in PowerShell; newline in cmd) | R1, R5 F8/F11 |
| D3 *Quoting* (cmd caret escape, PS `""` in values, continuations in cmd/PS) | R1, R5 F3/F11 |
| D3 *Dynamic words* (one position each; cmd `%NAME%`; backtick substitutions) | R2; cmd `%` and POSIX backticks refused |
| D3 *Unparseable* lists | R1 tables (closed: listed constructs are read, the rest refused) |
| D3 *Kept out of the match tokens* (wrapper forms) | R3 process-wrapper grammars |
| D3 *Shell wrappers unwrapped* (`zsh ksh ash`; any outer dialect; raw-spelling scripts; `cmd /C "..."`) | R3 (sh/bash/dash only; same-family outers; values joined; no `"` after `/c`) |
| D4 restrictive match (one position per dynamic word; POSIX basename exact) | R2 alignment; R3 folding for restrictive rules in every dialect (allow stays exact in POSIX) |
| D4 pinning | R4 lookup context |
| D6 canonical command (innermost script text; `-lc` dropped; A2 loop) | R5 canonical key; A2 retired |
| A1 (PowerShell expanding escapes) | Kept unchanged |
| A3 test deviations | Superseded where the tests below change |
| M1-M3 test texts | "Existing tests that change" below |
| Mutation campaign of record (E*/R* rows) | Replaced by the table below |
| Purity (M3 #17 import set) | adds `unicodedata` |
| New obligation **O-S1-12** | S2 never passes `dialect="posix"` for a Windows call site (`serving_dialects("win32") == ("cmd", "powershell")` in S2a already holds); a POSIX shell started from a Windows dialect is unparseable here. |

## Closure enumeration (for the delta review)

| F | Every producer / exit and where it is closed (Section 2 names) |
|---|---|
| F1 | `_with_lookup_context` (all mutators, all depths, line-wide); `_posix_script` (login), `_powershell_script` (profile), `_wrapper_width` (`command -p`); `_inherit` carries it into wrapped scripts; `_allow_match` withholds proof; `_is_simple` refuses argv keys. PS `Env:`/`alias:`/`function:`/`variable:` in `_PowerShellLexer._check_word`; `$env:X=` via dynamic program. |
| F2 | `_CmdLexer.lex` refuses `%`/`!`; POSIX `_dollar`/`_substitution`/`_plain`, cmd `lex`/`_quoted_run`, PS `_variable`/`_splat`/`lex` mark `variadic`; `_restrictive_cover`; `_match` (allow); redirection targets: POSIX ones are file names (no new command), cmd ones cannot expand, PS ones may be dynamic (file effects, AD-1316). |
| F3 | `_CmdLexer` (`^`, `'`, `\"`, `""`), `_cmd_program_problem`, `_windows_program_name_problem`, `_PowerShellLexer._check_word`, `_powershell_program_problem`, `_checked_text` (non-ASCII). |
| F4 | POSIX `_dollar` (final `raise`), `_plain` (`~` after `=`/`:`); PS `_variable` (final `raise`, member access), `_splat`; cmd `%`/`^`. |
| F5 | `_strip_process_wrappers` (option-like program refused after every wrapper), `_wrapper_width` (closed grammars). |
| F6 | `_posix_script`, `_cmd_script`, `_powershell_script` (values joined; quotes after `/c` refused); `_rest_of_line` deleted. |
| F7 | `_Context`, `_inherit`, `_unwrap`, `_emit` (substitutions in a wrapped script inherit); `canonical_command` uses the inherited segment. |
| F8 | POSIX `_separator`, `_redirection`, `_descriptor`; PS `lex` (`||`), `_ampersand` (`&&`), `_redirection`; cmd `_redirection`; `_segment` (duplication targets). |
| F9 | `_launcher_problem` (keywords, launchers, other shells, wrapper spellings, subcommands), `_shell_wrapper` (exact basenames, same-family outers), all on `windows_program_stem`. |
| F10 | `_powershell_program_problem` (quoted first word without `&`), `_segment` (`called`). |
| F11 | `_checked_text` (no rewrite; CR; cmd newline), PS `_escape`, `_single_quoted`, `_double_quoted`. |
| F12 | `OM` `_has_surrogate` in `_check_policy_text`, `_check_pattern`, `_check_pins`; `_checked_text`; `canonical_command` malformed key. |

---

### Section 1 -- `src/probos/config_models/operations.py`

<<<<<<< SEARCH
def _has_control_character(value: str, allowed: str = "") -> bool:
    return any((ord(char) < 32 and char not in allowed) or ord(char) == 127 for char in value)
=======
def _has_control_character(value: str, allowed: str = "") -> bool:
    return any((ord(char) < 32 and char not in allowed) or ord(char) == 127 for char in value)


def _has_surrogate(value: str) -> bool:
    """True when ``value`` holds a lone surrogate: text that is not valid Unicode, which the RFC 8785
    policy digest cannot encode (AD-1328 S1 repair, finding 12)."""
    return any("\ud800" <= char <= "\udfff" for char in value)
>>>>>>> REPLACE

<<<<<<< SEARCH
    if _has_control_character(value, "\t\n" if newlines else ""):
        raise ValueError(f"{what} contains a control character")
=======
    if _has_control_character(value, "\t\n" if newlines else ""):
        raise ValueError(f"{what} contains a control character")
    if _has_surrogate(value):
        raise ValueError(f"{what} is not valid Unicode text (a lone surrogate)")
>>>>>>> REPLACE

<<<<<<< SEARCH
            if position == 0 and any(char in token for char in "/\\ \t"):
=======
            if _has_surrogate(token):
                raise ValueError(f"{where}: pattern position {position} is not valid Unicode text (a lone surrogate)")
            if position == 0 and any(char in token for char in "/\\ \t"):
>>>>>>> REPLACE

<<<<<<< SEARCH
        if not absolute or len(pin) > _MAX_PINNED_PATH_CHARS or _has_control_character(pin):
=======
        if _has_surrogate(pin):
            raise ValueError(f"{where}: a host_executable path is not valid Unicode text (a lone surrogate)")
        if not absolute or len(pin) > _MAX_PINNED_PATH_CHARS or _has_control_character(pin):
>>>>>>> REPLACE

### Section 2 -- `src/probos/execution/command_policy.py` (replace the whole file)

```python
"""AD-1328 S1 (#1530): the command execution policy core -- pure, deterministic, unwired.

``run_command`` is governed only as a whole tool today. This module reads one
shell command line the way its shell, and the programs that shell starts, will
read it; splits it into simple commands (segments); and decides each against the
operator's ordered token-prefix rules
(``probos.config_models.operations.CommandPolicyConfig``):

* ``parse_command`` -- a bounded, single-pass reader for three dialects:
  ``posix`` (``/bin/sh -c`` on a POSIX host, dash or bash: ``create_subprocess_shell``
  and ``shell=True`` off Windows), ``cmd`` (``cmd.exe /c``, which
  ``create_subprocess_shell`` starts on Windows) and ``powershell`` (``powershell
  -NoProfile -Command``, which ``ShellCommandAgent`` starts on Windows, and
  ``pwsh``). The dialect is an explicit argument whose default comes from the
  platform, so every dialect can be exercised on any machine.
* ``evaluate_command`` -- the strictest decision over every segment, with every
  matched rule listed. With no rules it returns ``no_policy`` and parses nothing.
* ``self_test`` -- every rule's ``match`` / ``not_match`` examples, judged by the
  same evaluator. A ``CommandPolicy`` cannot be built from a policy that fails it.
* ``canonical_command`` and ``policy_digest`` -- the approval-reuse key and the
  versioned digest of the policy an approval was granted under.

A closed grammar (S1 repair, review round 1). A construct is read only when its
meaning to the shell, and to the program that receives the words, is modelled and
checked against that shell (``tests/fixtures/ad1328_shell_oracle.json``); anything
else is unparseable and takes ``unparseable_decision``, never ``allow``. ``posix``
reads what dash and bash read alike. ``cmd`` and ``powershell`` read a smaller,
ASCII-only language whose words reach a program unchanged under the UCRT argument
rules, the MSYS2/Cygwin ones, and a batch file's ``cmd.exe``.

What the policy sees. A word the shell computes is *dynamic*: it stands for one
word of any value or, when *variadic*, for zero or more. Restrictive rules
(``escalate``, ``forbid``) see through what can hide a program: a path or another
spelling of its name, leading assignments, process wrappers, unwrapped shell
wrappers, command substitution, and dynamic words (a variadic word can supply every
word a pattern still needs). Permissive rules need proof: an ``allow`` rule matches
a bare program name, or a program resolved to one of its pinned paths in the lookup
context the command starts with, and never a segment with assignments (its own or
a wrapper's) or a dynamic word inside its prefix.

A prefix rule does not see a program started through another program's arguments,
files or configuration (``find -exec``, ``python -c``, ``git -c alias.x=!cmd``,
``make``) or options placed before a subcommand (``git -C . push``): that is the
boundary of a prefix-rule language (#1530, Do Not Build). A program whose purpose is
to start a program its arguments name is a launcher, and every launcher this module
does not unwrap is unparseable. Nothing here launches a process, reads the
environment or touches a file, and nothing under ``src/`` constructs this policy
yet: AD-1328 S2 wires it before broker admission.
"""

from __future__ import annotations

import hashlib
import ntpath
import posixpath
import re
import sys
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Final, Literal, cast

from probos.config_models.operations import (
    COMMAND_DECISION_RANK,
    CommandDecisionName,
    CommandPolicyConfig,
    CommandPolicyRule,
    windows_program_stem,
)

Dialect = Literal["posix", "cmd", "powershell"]
DIALECTS: Final[tuple[Dialect, ...]] = ("posix", "cmd", "powershell")
#: Maps a bare program name to the absolute path the shell would run, or None.
ProgramResolver = Callable[[str], str | None]

POLICY_DIGEST_SCHEME: Final = "probos.command_policy/policy/v1"
CANONICAL_KEY_SCHEME: Final = "probos.command_policy/canonical_command/v1"
_POLICY_DOMAIN: Final = b"probos.command_policy/policy/v1\x00"
_CANONICAL_DOMAIN: Final = b"probos.command_policy/canonical_command/v1\x00"
# The first of the two parts of the script key of text that is not valid Unicode; every other script key has one part.
_MALFORMED_SCRIPT_TAG: Final = "probos.command_policy/malformed-utf16le-hex"

_DEFAULT_LIMITS: Final = CommandPolicyConfig()
_SEPARATORS: Final = frozenset({";", "&&", "||", "|", "&", "\n"})
_CONTINUING: Final = frozenset({"&&", "||", "|"})
_CALL_OPERATOR: Final = "&call"
_IDENT_START: Final = re.compile(r"[A-Za-z_]")
_IDENT_CHAR: Final = re.compile(r"[A-Za-z0-9_]")
_LEADING_LETTERS: Final = re.compile(r"[A-Za-z]+")
_DRIVE_CHANGE: Final = re.compile(r"[A-Za-z]:")
_MAX_REPORTED_FAILURES: Final = 5
_DIALECT_NAMES: Final[dict[str, str]] = {"posix": "a POSIX shell", "cmd": "cmd.exe", "powershell": "PowerShell"}

# POSIX: what dash and bash, as /bin/sh -c, read alike.
_POSIX_SPECIAL_PARAMETERS: Final = frozenset("@*#?$!-0123456789")
_POSIX_BRACED_PARAMETER: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]|[@*#?$!-]")
_POSIX_REDIRECTIONS: Final = ("<<", ">>", ">&", "<&", ">|", "<>", ">", "<")
_POSIX_EXPANDING: Final = frozenset("*?[{}")
_POSIX_REFUSED_CATEGORIES: Final = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp", "Zs"})

# cmd.exe /c, and the words a program it starts receives (UCRT rules, read alike by MSYS2 and Cygwin programs).
_CMD_REFUSED_ANYWHERE: Final = frozenset("%!")
_CMD_REFUSED_UNQUOTED: Final = frozenset("^(),;'")
_CMD_EXPANSION: Final = "'%' or '!', which cmd.exe expands before it reads quotes and operators (percent or delayed expansion)"
_CMD_BACKSLASH_QUOTE: Final = "a backslash before a double quote, which a program reads as an escaped quote"
_CMD_DOUBLED_QUOTE: Final = 'a "" inside a word, which programs read differently'
_CMD_PROGRAM: Final = re.compile(r"[A-Za-z0-9_.+\\: -]+")
_CMD_INTERNAL: Final = frozenset({
    "assoc", "break", "call", "cd", "chdir", "cls", "color", "copy", "date", "del", "dir", "dpath", "echo",
    "endlocal", "erase", "exit", "for", "ftype", "goto", "if", "keys", "md", "mkdir", "mklink", "move", "path",
    "pause", "popd", "prompt", "pushd", "rd", "rem", "ren", "rename", "rmdir", "set", "setlocal", "shift", "start",
    "time", "title", "type", "ver", "verify", "vol",
})
_WINDOWS_EXPANDING: Final = frozenset("*?[{")
_WINDOWS_EXPANDING_START: Final = frozenset("~@")

# PowerShell: what Windows PowerShell 5.1 and PowerShell 7 read alike, and pass to a program unchanged.
# A backtick before one of these is not the plain next character (measured on pwsh 7.6.7 and Windows PowerShell 5.1:
# all but e and u expand in both, e only in 7, and u{67} is g only in 7), so the word differs per host.
_PS_EXPANDING_ESCAPES: Final = frozenset("0abefnrtuv")
_PS_SYNTAX: Final = frozenset("(){}[],")
_PS_CHAIN: Final = "&& or ||, which Windows PowerShell 5.1 does not have"
_PS_BARE_PROGRAM: Final = re.compile(r"[A-Za-z_.\\/][A-Za-z0-9_.+\\/:-]*")
_PS_CALLED_PROGRAM: Final = re.compile(r"[A-Za-z0-9_.+\\/: -]+")
_PS_NUMBER_START: Final = re.compile(r"[0-9]|[-+.][0-9]")
_PS_INTEGER: Final = re.compile(r"-?(?:0|[1-9][0-9]{0,8})")
_PS_BRACED_VARIABLE: Final = re.compile(r"[A-Za-z0-9_]+(?::[A-Za-z0-9_]+)?")
_PS_STREAMS: Final = frozenset({"1", "2", "3", "4", "5", "6", "*"})
_PS_MERGING_STREAMS: Final = frozenset({"2", "3", "4", "5", "6", "*"})
_PS_BATCH_METACHARACTERS: Final = frozenset("&|<>^%!")
_PS_PROVIDER_PREFIXES: Final = ("alias:", "function:", "env:", "variable:")
_PS_EXECUTION_POLICIES: Final = frozenset({
    "allsigned", "bypass", "default", "remotesigned", "restricted", "undefined", "unrestricted",
})

# Launchers: programs whose purpose is to start a program their arguments name. All names are compared as
# windows_program_stem() gives them (basename, lower case, no .exe/.com/.bat/.cmd), in every dialect.
_POSIX_SHELLS: Final = frozenset({"sh", "bash", "dash"})
_POSIX_SCRIPT_FLAGS: Final[dict[str, bool]] = {"-c": False, "-lc": True, "-cl": True}  # flag -> a login shell
_PS_SHELLS: Final = frozenset({"powershell", "pwsh"})
_OTHER_SHELLS: Final = frozenset({
    "zsh", "ksh", "ksh93", "mksh", "pdksh", "ash", "yash", "posh", "rbash", "fish", "csh", "tcsh", "nu", "elvish",
    "xonsh", "busybox", "toybox", "wsl", "wslhost",
})
_PROCESS_WRAPPERS: Final = frozenset({"command", "nice", "nohup", "stdbuf", "time", "timeout"})
_LAUNCHERS_EVERYWHERE: Final = frozenset({
    "env", "sudo", "doas", "su", "runuser", "pkexec", "chroot", "setsid", "setpriv", "ionice", "chrt", "taskset",
    "numactl", "flock", "unshare", "nsenter", "xargs", "parallel", "watch", "strace", "ltrace", "gdb", "valgrind",
    "firejail", "bwrap", "systemd-run", "script", "expect", "ssh", "npx", "pnpx", "bunx", "uvx", "pipx", "runas",
})
_LAUNCHERS: Final[dict[str, frozenset[str]]] = {
    "posix": _LAUNCHERS_EVERYWHERE | {
        "eval", "exec", "source", ".", "alias", "unalias", "enable", "shopt", "trap", "builtin", "noglob",
    },
    "cmd": _LAUNCHERS_EVERYWHERE | {"call", "start", "forfiles", "doskey"},
    "powershell": _LAUNCHERS_EVERYWHERE | {
        "invoke-expression", "iex", "invoke-command", "icm", "start-process", "saps", "start", "start-job", "sajb",
        "start-threadjob", "foreach-object", "%", "foreach", "where-object", "?", "where", "invoke-item", "ii",
        "invoke-history", "ihy", "r", "set-alias", "sal", "new-alias", "nal", "import-module", "ipmo", ".",
    },
}
_KEYWORDS: Final[dict[str, frozenset[str]]] = {
    "posix": frozenset({
        "!", "[[", "]]", "{", "}", "case", "coproc", "do", "done", "elif", "else", "esac", "fi", "for", "function",
        "if", "in", "select", "then", "until", "while",
    }),
    "cmd": frozenset({"for", "goto", "if", "rem"}),
    "powershell": frozenset({
        "begin", "break", "catch", "class", "clean", "continue", "data", "define", "do", "dynamicparam", "else",
        "elseif", "end", "enum", "exit", "filter", "finally", "for", "foreach", "from", "function", "hidden", "if",
        "in", "inlinescript", "parallel", "param", "process", "return", "sequence", "static", "switch", "throw",
        "trap", "try", "until", "using", "var", "while", "workflow",
    }),
}
# A subcommand launcher is unreadable when any later word is dynamic or names one of its launching subcommands.
_SUBCOMMAND_LAUNCHERS: Final[dict[str, frozenset[str]]] = {
    "uv": frozenset({"run"}), "npm": frozenset({"exec", "x"}), "pnpm": frozenset({"exec", "dlx"}),
    "yarn": frozenset({"exec", "dlx"}), "bun": frozenset({"exec", "x"}), "poetry": frozenset({"run"}),
    "pdm": frozenset({"run"}), "hatch": frozenset({"run"}), "pipenv": frozenset({"run"}),
    "conda": frozenset({"run"}), "mamba": frozenset({"run"}), "micromamba": frozenset({"run"}),
    "docker": frozenset({"exec", "run"}), "podman": frozenset({"exec", "run"}),
    "kubectl": frozenset({"exec", "run"}), "nix": frozenset({"develop", "run", "shell"}), "rye": frozenset({"run"}),
}
# Programs that change the working directory or the environment, so later programs may resolve elsewhere.
_STATE_MUTATORS: Final[dict[str, frozenset[str]]] = {
    "posix": frozenset({
        "cd", "declare", "export", "hash", "local", "popd", "pushd", "readonly", "set", "typeset", "unset",
    }),
    "cmd": frozenset({"cd", "chdir", "endlocal", "path", "popd", "pushd", "set", "setlocal"}),
    "powershell": frozenset({"cd", "chdir", "pop-location", "popd", "push-location", "pushd", "set-location", "sl"}),
}
_DUPLICATION_TARGETS: Final[dict[str, frozenset[str]]] = {
    "posix": frozenset("0123456789-"),
    "cmd": frozenset("0123456789"),
    "powershell": frozenset(),
}
_LOGIN_SHELL: Final = "a login shell reads profile files that may change PATH"
_PS_PROFILE: Final = "PowerShell without -NoProfile reads a profile that may define commands or change PATH"
_DEFAULT_PATH: Final = "command -p looks the program up on the default PATH"
_MAX_PROCESS_WRAPPERS: Final = 4
_NICE_LEVEL: Final = re.compile(r"-?[0-9]{1,3}")
_DURATION: Final = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,9})?[smhd]?")
_STDBUF_OPTION: Final = re.compile(r"-[ioe](?:L|0|[1-9][0-9]{0,8}[KMG]?)")


class _Unparseable(Exception):
    """Text the policy cannot read with confidence; ``reason`` says why."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _OverBudget(_Unparseable):
    """A bound on the work was reached: the whole command is unparseable."""


@dataclass(frozen=True)
class _Word:
    text: str
    raw: str
    dynamic: bool
    variadic: bool
    assignment: bool
    quoted: bool


@dataclass(frozen=True)
class _Op:
    text: str
    redirect: bool
    needs_target: bool = True


@dataclass(frozen=True)
class _Context:
    """What a shell wrapper's segment passes to every segment of the script it runs."""

    assignments: tuple[str, ...]
    redirections: tuple[str, ...]
    wrappers: tuple[str, ...]
    lookup_changed: str | None


_Unwrapped = tuple[str, Dialect, str | None]  # (script, its dialect, why the lookup context changes, or None)


@dataclass(frozen=True)
class CommandSegment:
    """One simple command of a command line, as the policy reads it.

    ``tokens`` are the words as the program receives them, program first.
    ``dynamic[i]`` is True where the shell computes word ``i`` (a variable, a
    substitution, a glob): ``tokens[i]`` then holds only its literal text, and
    ``variadic[i]`` says whether it may stand for zero or more words rather than
    exactly one. ``raw`` is each word as written. Leading ``NAME=value``
    ``assignments`` (POSIX), ``redirections`` (operator and target) and the
    stripped process ``wrappers`` are kept out of ``tokens``; the segments of a
    script a shell wrapper runs inherit that wrapper's three. ``depth`` counts the
    substitutions and shell wrappers around the segment. ``unparseable`` says why
    the policy cannot read this segment, or is None. ``lookup_changed`` says why the
    program may not be the one the command's starting PATH and working directory
    find (a directory or environment change in the line, a login shell, a
    PowerShell profile, ``command -p``), or is None.
    """

    dialect: Dialect
    tokens: tuple[str, ...]
    dynamic: tuple[bool, ...]
    raw: tuple[str, ...]
    assignments: tuple[str, ...]
    redirections: tuple[str, ...]
    wrappers: tuple[str, ...]
    depth: int
    unparseable: str | None
    variadic: tuple[bool, ...] = ()
    lookup_changed: str | None = None


@dataclass(frozen=True)
class ParsedCommand:
    """A command line split into segments. ``unparseable`` is set, and ``segments``
    is empty, when the line as a whole cannot be read."""

    dialect: Dialect
    segments: tuple[CommandSegment, ...]
    unparseable: str | None


@dataclass(frozen=True)
class RuleMatch:
    """One rule matching one segment.

    ``decision`` is the rule's, except that a pinned ``allow`` rule whose program is
    not proven to be at a pinned path gives ``forbid`` with ``pin_violation`` set and
    a justification naming the path found or why none is proven. ``matched_prefix``
    is the segment's words the pattern covered, as the program receives them.
    """

    rule: str
    decision: CommandDecisionName
    justification: str
    alternative: str | None
    matched_prefix: tuple[str, ...]
    segment: int
    resolved_program: str | None
    pin_violation: bool


@dataclass(frozen=True)
class SegmentVerdict:
    """The decision for one segment: by ``rule`` match, ``unmatched`` or ``unparseable``."""

    index: int
    segment: CommandSegment
    decision: CommandDecisionName
    basis: Literal["rule", "unmatched", "unparseable"]
    matches: tuple[RuleMatch, ...]


@dataclass(frozen=True)
class CommandEvaluation:
    """The policy's answer for one command line.

    ``status`` is ``no_policy`` when no rule is configured: nothing was parsed or
    decided, ``decision`` is None, and the caller runs the command exactly as it
    would without a policy. Otherwise ``decision`` is the strictest over
    ``segments``, or ``unparseable_decision`` when the whole line could not be read
    (``unparseable`` says why, and ``segments`` is empty).
    """

    status: Literal["no_policy", "evaluated"]
    decision: CommandDecisionName | None
    dialect: Dialect
    policy_digest: str | None
    segments: tuple[SegmentVerdict, ...]
    unparseable: str | None

    @property
    def matched_rules(self) -> tuple[RuleMatch, ...]:
        """Every rule match: segment by segment, and in rule order within a segment."""
        return tuple(match for verdict in self.segments for match in verdict.matches)

    @property
    def governing(self) -> tuple[RuleMatch, ...]:
        """The matches that carry the final decision; their justifications and
        alternatives are what the agent is told."""
        return tuple(match for match in self.matched_rules if match.decision == self.decision)


@dataclass(frozen=True)
class SelfTestFailure:
    """One example that does not hold for its rule."""

    rule: str
    expectation: Literal["match", "not_match"]
    example: str
    observed: str

    @property
    def message(self) -> str:
        return f"rule {self.rule!r}: {self.expectation} example {self.example!r} {self.observed}"


@dataclass(frozen=True)
class SelfTestReport:
    """Every rule's examples judged under one dialect."""

    dialect: Dialect
    examples_checked: int
    failures: tuple[SelfTestFailure, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


class CommandPolicySelfTestError(ValueError):
    """A policy whose examples do not hold under its dialect; at startup, a startup error."""

    def __init__(self, report: SelfTestReport) -> None:
        shown = "; ".join(failure.message for failure in report.failures[:_MAX_REPORTED_FAILURES])
        extra = len(report.failures) - _MAX_REPORTED_FAILURES
        more = f" (and {extra} more)" if extra > 0 else ""
        super().__init__(f"command policy self-test failed under the {report.dialect} dialect: {shown}{more}")
        self.report = report


@dataclass(frozen=True)
class CanonicalCommand:
    """The approval-reuse identity of a command (#1530 amendment; S1 repair R5).

    ``argv``: exactly one simple command that runs in the starting lookup context,
    with only literal words and no assignments, redirections or process wrappers
    (its own or a shell wrapper's), after unwrapping shell wrappers: the program as
    its normalised resolved path when the resolver knows it (so ``git`` and
    ``/usr/bin/git`` share a key), else its normalised name, then the arguments; the
    dialect is not part of it. ``script``: anything else -- the dialect and the exact
    command text; text that is not valid Unicode has two parts, a tag and its
    UTF-16 hex.
    """

    kind: Literal["argv", "script"]
    dialect: Dialect | None
    parts: tuple[str, ...]

    @property
    def key(self) -> str:
        """``CANONICAL_KEY_SCHEME``: sha256 of a domain tag and the RFC 8785 JSON of
        ``[kind, dialect, parts]``."""
        payload = _canonical_json([self.kind, self.dialect, list(self.parts)])
        return hashlib.sha256(_CANONICAL_DOMAIN + payload).hexdigest()


# --------------------------------------------------------------------------------------
# Lexers: one pass over one string each
# --------------------------------------------------------------------------------------


class _Lexer:
    """The word buffer every dialect shares. Subclasses own quoting, expansion and operators."""

    def __init__(self, text: str, depth: int, max_nesting: int) -> None:
        self.text = text
        self.i = 0
        self.depth = depth
        self.max_nesting = max_nesting
        self.items: list[_Word | _Op] = []
        self.subs: list[_Lexer] = []
        self._reset()

    def lex(self) -> None:
        raise NotImplementedError

    def _reset(self) -> None:
        self._buf: list[str] = []
        self._start = -1
        self._dynamic = False
        self._variadic = False
        self._quoted = False
        self._ident = True
        self._assignment = False
        self._sealed = False
        self._last = ""

    def _begin(self) -> None:
        if self._sealed:
            raise _Unparseable("text directly after a closing quote")
        if self._start < 0:
            self._start = self.i

    def _literal(self, chars: str, *, quoted: bool) -> None:
        self._begin()
        if quoted:
            self._quoted = True
        if not self._assignment:
            if not quoted and chars == "=" and self._buf and self._ident:
                self._assignment = True
            elif quoted or _IDENT_CHAR.fullmatch(chars) is None or (not self._buf and chars.isdigit()):
                self._ident = False
        self._buf.append(chars)
        self._last = "" if quoted else chars[-1:]

    def _mark_dynamic(self, *, variadic: bool) -> None:
        self._begin()
        self._dynamic = True
        self._variadic = self._variadic or variadic
        self._last = ""
        if not self._assignment:
            self._ident = False

    def _end_word(self) -> None:
        if self._start >= 0:
            word = _Word(
                "".join(self._buf), self.text[self._start:self.i], self._dynamic, self._variadic, self._assignment,
                self._quoted,
            )
            self._check_word(word)
            self.items.append(word)
        self._reset()

    def _check_word(self, word: _Word) -> None:
        """A dialect's check of a finished word; raises ``_Unparseable`` for a value it does not read."""

    def _op(self, text: str, *, redirect: bool = False, needs_target: bool = True) -> None:
        self._end_word()
        self.items.append(_Op(text, redirect, needs_target))

    def _comment(self) -> None:
        end = self.text.find("\n", self.i)
        self.i = len(self.text) if end < 0 else end

    def _nest(self) -> None:
        if self.depth >= self.max_nesting:
            raise _Unparseable(f"command substitution nested deeper than {self.max_nesting}")


class _PosixLexer(_Lexer):
    """``/bin/sh -c`` on a POSIX host: only what dash and bash read alike."""

    def lex(self, *, closing: bool = False) -> None:
        text = self.text
        while self.i < len(text):
            ch = text[self.i]
            if ch in " \t":
                self._end_word()
                self.i += 1
            elif ch == "\n":
                self._op("\n")
                self.i += 1
            elif ch == "#" and self._start < 0:
                self._comment()
            elif ch == "\\":
                self._backslash()
            elif ch == "'":
                self._single_quoted()
            elif ch == '"':
                self._double_quoted()
            elif ch == "`":
                raise _Unparseable("a backtick command substitution (the policy reads $( ) instead)")
            elif ch == "$":
                self._dollar(quoted=False)
            elif ch == ")" and closing:
                self._end_word()
                self.i += 1
                return
            elif ch in "()":
                raise _Unparseable("a subshell, a group or a function definition")
            elif ch in "<>":
                self._redirection()
            elif ch in ";&|":
                self._separator()
            else:
                self._plain(ch)
        if closing:
            raise _Unparseable("an unbalanced $(")
        self._end_word()

    def _plain(self, ch: str) -> None:
        if ch in _POSIX_EXPANDING:
            self._mark_dynamic(variadic=True)
        elif ch == "~" and (self._start < 0 or self._last in ("=", ":")):
            self._mark_dynamic(variadic=False)  # tilde expansion: one word (bash also expands it after = and :)
        self._literal(ch, quoted=False)
        self.i += 1

    def _backslash(self) -> None:
        following = self.text[self.i + 1:self.i + 2]
        if not following:
            raise _Unparseable("a trailing backslash")
        if following != "\n":  # a backslash before a newline continues the line and leaves nothing
            self._literal(following, quoted=True)
        self.i += 2

    def _single_quoted(self) -> None:
        end = self.text.find("'", self.i + 1)
        if end < 0:
            raise _Unparseable("an unbalanced single quote")
        self._literal(self.text[self.i + 1:end], quoted=True)
        self.i = end + 1

    def _double_quoted(self) -> None:
        text = self.text
        self._literal("", quoted=True)
        self.i += 1
        while self.i < len(text):
            ch = text[self.i]
            if ch == '"':
                self.i += 1
                return
            if ch == "\\":
                following = text[self.i + 1:self.i + 2]
                if following == "\n":  # a continuation inside double quotes
                    self.i += 2
                elif following in ("$", "`", '"', "\\"):
                    self._literal(following, quoted=True)
                    self.i += 2
                else:
                    self._literal("\\", quoted=True)
                    self.i += 1
            elif ch == "`":
                raise _Unparseable("a backtick command substitution (the policy reads $( ) instead)")
            elif ch == "$":
                self._dollar(quoted=True)
            else:
                self._literal(ch, quoted=True)
                self.i += 1
        raise _Unparseable("an unbalanced double quote")

    def _dollar(self, *, quoted: bool) -> None:
        text, i = self.text, self.i
        following = text[i + 1:i + 2]
        if text.startswith("$((", i):
            raise _Unparseable("arithmetic expansion")
        if following == "(":
            self._substitution(quoted=quoted)
            return
        if following == "{":
            end = text.find("}", i + 2)
            name = text[i + 2:end] if end >= 0 else ""
            if end < 0 or _POSIX_BRACED_PARAMETER.fullmatch(name) is None:
                raise _Unparseable("a ${...} form the policy does not model")
            self._mark_dynamic(variadic=(not quoted) or name == "@")
            self.i = end + 1
            return
        if following in ("'", '"'):
            raise _Unparseable("$'...' or $\"...\" quoting")
        if following and _IDENT_START.fullmatch(following) is not None:
            end = i + 2
            while end < len(text) and _IDENT_CHAR.fullmatch(text[end]) is not None:
                end += 1
            self._mark_dynamic(variadic=not quoted)
            self.i = end
            return
        if following and following in _POSIX_SPECIAL_PARAMETERS:
            self._mark_dynamic(variadic=(not quoted) or following == "@")
            self.i = i + 2
            return
        raise _Unparseable("a '$' the policy does not model in a POSIX shell")

    def _substitution(self, *, quoted: bool) -> None:
        self._nest()
        self._mark_dynamic(variadic=not quoted)
        inner = _PosixLexer(self.text, self.depth + 1, self.max_nesting)
        inner.i = self.i + 2
        inner.lex(closing=True)
        self.subs.append(inner)  # its segments are judged too
        self.i = inner.i

    def _redirection(self) -> None:
        text = self.text
        op = next(candidate for candidate in _POSIX_REDIRECTIONS if text.startswith(candidate, self.i))
        if op == "<<":
            raise _Unparseable("a here-document or a here-string")
        if op in (">|", "<>"):
            raise _Unparseable(f"the redirection {op!r}, which the policy does not model")
        if op in ("<", ">") and text.startswith("(", self.i + 1):
            raise _Unparseable("process substitution")
        descriptor = self._descriptor()
        self._op(descriptor + op, redirect=True)
        self.i += len(op)

    def _descriptor(self) -> str:
        """The descriptor written directly before a redirection (``2`` in ``2>``), consumed; else ``""``."""
        if self._start < 0:
            return ""
        raw = self.text[self._start:self.i]
        if raw.isascii() and raw.isdigit():
            if len(raw) > 1:
                raise _Unparseable("a multi-digit file descriptor, which dash and bash read differently")
            self._reset()
            return raw
        if "{" in raw or "}" in raw:
            raise _Unparseable("a {name} descriptor, which only bash reads")
        self._end_word()
        return ""

    def _separator(self) -> None:
        pair = self.text[self.i:self.i + 2]
        if pair in (";;", ";&"):
            raise _Unparseable("case-statement syntax")
        if pair == "|&":
            raise _Unparseable("|&, a pipe of both streams that only bash reads")
        if pair == "&>":
            raise _Unparseable("&>, which bash reads as a redirection and dash as a background job")
        op = pair if pair in ("&&", "||") else self.text[self.i]
        self._op(op)
        self.i += len(op)


class _CmdLexer(_Lexer):
    """``cmd.exe /c``, as ``create_subprocess_shell`` starts it on Windows, and the words the program it starts
    receives (the UCRT rules, read alike by MSYS2 and Cygwin programs)."""

    def lex(self) -> None:
        text = self.text
        while self.i < len(text):
            ch = text[self.i]
            if ch in " \t":
                self._end_word()
                self.i += 1
            elif ch == '"':
                self._quoted_run()
            elif ch in _CMD_REFUSED_ANYWHERE:
                raise _Unparseable(_CMD_EXPANSION)
            elif ch in _CMD_REFUSED_UNQUOTED:
                raise _Unparseable(f"{ch!r} outside quotes, which cmd.exe or the program it starts reads as syntax")
            elif ch == "\\" and text.startswith('"', self.i + 1):
                raise _Unparseable(_CMD_BACKSLASH_QUOTE)
            elif ch in "<>":
                self._redirection()
            elif ch in "&|":
                pair = text[self.i:self.i + 2]
                op = pair if pair in ("&&", "||") else ch
                self._op(op)
                self.i += len(op)
            else:
                if ch in _WINDOWS_EXPANDING or (ch in _WINDOWS_EXPANDING_START and self._start < 0):
                    self._mark_dynamic(variadic=True)  # the program may glob it, or read @file / ~
                self._literal(ch, quoted=False)
                self.i += 1
        self._end_word()

    def _quoted_run(self) -> None:
        text = self.text
        end = text.find('"', self.i + 1)
        if end < 0:
            raise _Unparseable("an unbalanced double quote")
        body = text[self.i + 1:end]
        if any(char in _CMD_REFUSED_ANYWHERE for char in body):
            raise _Unparseable(_CMD_EXPANSION)
        if body.endswith("\\"):
            raise _Unparseable(_CMD_BACKSLASH_QUOTE)
        if not body and (self._start >= 0 or text[end + 1:end + 2] not in ("", " ", "\t", "&", "|", "<", ">")):
            raise _Unparseable(_CMD_DOUBLED_QUOTE)
        if text.startswith('"', end + 1):
            raise _Unparseable(_CMD_DOUBLED_QUOTE)
        if any(char in _WINDOWS_EXPANDING for char in body):
            self._mark_dynamic(variadic=True)
        self._literal(body, quoted=True)
        self.i = end + 1

    def _redirection(self) -> None:
        text = self.text
        op = next(candidate for candidate in (">>", ">&", "<&", ">", "<") if text.startswith(candidate, self.i))
        descriptor = ""
        if self._start >= 0:
            raw = text[self._start:self.i]
            if not (len(raw) == 1 and raw.isdigit()):
                raise _Unparseable("a redirection written against a word, which cmd.exe may read as a descriptor")
            descriptor = raw
            self._reset()
        self._op(descriptor + op, redirect=True)
        self.i += len(op)


class _PowerShellLexer(_Lexer):
    """PowerShell ``-Command`` text: only what Windows PowerShell 5.1 and PowerShell 7 read alike, and only
    argument values both pass to a program unchanged."""

    def lex(self) -> None:
        text = self.text
        while self.i < len(text):
            ch = text[self.i]
            if ch in " \t":
                self._end_word()
                self.i += 1
            elif ch == "\n":
                self._op("\n")
                self.i += 1
            elif ch == "#" and self._start < 0:
                self._comment()
            elif ch == "`":
                self._escape()
            elif ch == "'":
                self._single_quoted()
            elif ch == '"':
                self._double_quoted()
            elif ch == "$":
                self._variable(quoted=False)
            elif ch == "@" and self._start < 0:
                self._splat()
            elif ch == ">":
                self._redirection()
            elif ch == "<":
                raise _Unparseable("a '<', reserved in PowerShell, or a block comment")
            elif ch == "&":
                self._ampersand()
            elif ch == "|":
                if text.startswith("||", self.i):
                    raise _Unparseable(_PS_CHAIN)
                self._op("|")
                self.i += 1
            elif ch == ";":
                self._op(";")
                self.i += 1
            elif ch in _PS_SYNTAX:
                raise _Unparseable(f"{ch!r}, which PowerShell reads as syntax")
            else:
                if ch in "*?" or (ch == "~" and self._start < 0):
                    self._mark_dynamic(variadic=True)  # PowerShell 7 or the program may expand it
                self._literal(ch, quoted=False)
                self.i += 1
        self._end_word()

    def _escape(self) -> None:
        following = self.text[self.i + 1:self.i + 2]
        if not following:
            raise _Unparseable("a trailing '`'")
        if following == "\n":  # PowerShell continues the line, which it reads differently inside a word
            raise _Unparseable("a backtick line continuation")
        if following in _PS_EXPANDING_ESCAPES:
            raise _Unparseable(f"the PowerShell escape '`{following}', which expands to another character")
        self._literal(following, quoted=True)
        self.i += 2

    def _single_quoted(self) -> None:
        if self._start >= 0:
            raise _Unparseable("a quote inside a word")
        text = self.text
        self._literal("", quoted=True)
        at = self.i + 1
        while at < len(text):
            ch = text[at]
            if ch == "\n":  # a newline in single quotes
                raise _Unparseable("a newline inside a quoted string")
            if ch == "'":
                if not text.startswith("''", at):
                    self.i = at + 1
                    self._sealed = True
                    return
                self._literal("'", quoted=True)
                at += 2
            else:
                self._literal(ch, quoted=True)
                at += 1
        raise _Unparseable("an unbalanced single quote")

    def _double_quoted(self) -> None:
        if self._start >= 0:
            raise _Unparseable("a quote inside a word")
        text = self.text
        self._literal("", quoted=True)
        self.i += 1
        while self.i < len(text):
            ch = text[self.i]
            if ch == "\n":  # a newline in double quotes
                raise _Unparseable("a newline inside a quoted string")
            if ch == '"':
                if not text.startswith('""', self.i):
                    self.i += 1
                    self._sealed = True
                    return
                self._literal('"', quoted=True)
                self.i += 2
            elif ch == "`":
                self._escape()
            elif ch == "$":
                self._variable(quoted=True)
            else:
                self._literal(ch, quoted=True)
                self.i += 1
        raise _Unparseable("an unbalanced double quote")

    def _variable(self, *, quoted: bool) -> None:
        text, i = self.text, self.i
        following = text[i + 1:i + 2]
        if following == "(":
            raise _Unparseable("a subexpression $( )")
        if following == "{":
            end = text.find("}", i + 2)
            if end < 0 or _PS_BRACED_VARIABLE.fullmatch(text[i + 2:end]) is None:
                raise _Unparseable("a ${...} form the policy does not model")
            end += 1
        elif following and following in "?^$":
            end = i + 2
        elif following and _IDENT_CHAR.fullmatch(following) is not None:
            end = i + 2
            while end < len(text) and _IDENT_CHAR.fullmatch(text[end]) is not None:
                end += 1
            if text.startswith(":", end) and _IDENT_CHAR.fullmatch(text[end + 1:end + 2] or "-") is not None:
                end += 1  # a scope or drive: $env:PATH
                while end < len(text) and _IDENT_CHAR.fullmatch(text[end]) is not None:
                    end += 1
        else:
            raise _Unparseable("a '$' the policy does not model in PowerShell")
        if not quoted and text[end:end + 1] in (".", ":", "["):
            raise _Unparseable("member access or indexing on a PowerShell variable")
        self._mark_dynamic(variadic=True)  # Windows PowerShell 5.1 drops an empty string; an array passes as many
        self.i = end

    def _splat(self) -> None:
        following = self.text[self.i + 1:self.i + 2]
        if not following or _IDENT_START.fullmatch(following) is None:
            raise _Unparseable("an '@' form the policy does not model (an array, a hash table, a here-string or a splat)")
        end = self.i + 2
        while end < len(self.text) and _IDENT_CHAR.fullmatch(self.text[end]) is not None:
            end += 1
        self._mark_dynamic(variadic=True)
        self.i = end

    def _redirection(self) -> None:
        text = self.text
        stream = ""
        if self._start >= 0:
            raw = text[self._start:self.i]
            if raw not in _PS_STREAMS:
                raise _Unparseable("a redirection written against a word")
            stream = raw
            self._reset()
        if text.startswith(">&1", self.i):
            if stream not in _PS_MERGING_STREAMS:
                raise _Unparseable("a stream redirection the policy does not model")
            self._op(f"{stream}>&1", redirect=True, needs_target=False)
            self.i += 3
            return
        op = ">>" if text.startswith(">>", self.i) else ">"
        if text.startswith("&", self.i + len(op)):
            raise _Unparseable("a stream redirection the policy does not model")
        self._op(stream + op, redirect=True)
        self.i += len(op)

    def _ampersand(self) -> None:
        text = self.text
        if text.startswith("&&", self.i):
            raise _Unparseable(_PS_CHAIN)
        at_start = self._start < 0 and (
            not self.items or (isinstance(self.items[-1], _Op) and not self.items[-1].redirect)
        )
        if not at_start:
            raise _Unparseable("a background job (&)")
        if text[self.i + 1:self.i + 2] not in (" ", "\t"):
            raise _Unparseable("a call operator (&) not followed by a blank")
        self._op(_CALL_OPERATOR)
        self.i += 1

    def _check_word(self, word: _Word) -> None:
        if word.dynamic:
            return
        value = word.text
        if value == "--" or value.startswith("--%"):
            raise _Unparseable("the -- or --% (stop-parsing) token, which PowerShell versions pass differently")
        if not value:
            raise _Unparseable("an empty argument, which Windows PowerShell 5.1 drops")
        if '"' in value:
            raise _Unparseable("a double quote inside an argument, which PowerShell passes to a program unescaped")
        if any(char in _PS_BATCH_METACHARACTERS for char in value):
            raise _Unparseable(
                "'&', '|', '<', '>', '^', '%' or '!' in an argument, which a batch-file program reads as cmd.exe syntax"
            )
        if "\t" in value or (" " in value and value.endswith("\\")):
            raise _Unparseable("an argument PowerShell quotes for a program in a way it may read differently")
        if "'" in value and " " not in value:
            raise _Unparseable("a single quote in an argument without a blank, which some programs read as quoting")
        if word.raw[:1] not in ("'", '"') and _PS_NUMBER_START.match(value) and _PS_INTEGER.fullmatch(value) is None:
            raise _Unparseable("a word PowerShell reads as a number")
        if value.lower().startswith(_PS_PROVIDER_PREFIXES):
            raise _Unparseable(
                "a PowerShell alias:, function:, env: or variable: path, which changes how later commands resolve"
            )


_LEXERS: Final[dict[str, type[_Lexer]]] = {
    "posix": _PosixLexer,
    "cmd": _CmdLexer,
    "powershell": _PowerShellLexer,
}


# --------------------------------------------------------------------------------------
# Segments
# --------------------------------------------------------------------------------------


def default_dialect(platform: str | None = None) -> Dialect:
    """The shell ``create_subprocess_shell`` starts: ``cmd`` on Windows, else ``posix``.

    ``ShellCommandAgent`` runs PowerShell on Windows; its caller passes
    ``"powershell"`` explicitly.
    """
    return "cmd" if (sys.platform if platform is None else platform) == "win32" else "posix"


def _dialect(dialect: object) -> Dialect:
    if dialect is None:
        return default_dialect()
    if type(dialect) is not str or dialect not in DIALECTS:
        raise ValueError("command_policy_dialect_invalid")
    return cast(Dialect, dialect)


def _program_name(program: str, dialect: Dialect) -> str:
    return posixpath.basename(program) if dialect == "posix" else windows_program_stem(program)


def _is_path(program: str, dialect: Dialect) -> bool:
    return "/" in program if dialect == "posix" else any(char in program for char in "/\\:")


def _path_key(path: str, dialect: Dialect) -> str:
    return posixpath.normpath(path) if dialect == "posix" else ntpath.normcase(ntpath.normpath(path))


def _is_scalar_text(text: str) -> bool:
    return not any("\ud800" <= char <= "\udfff" for char in text)


def _checked_text(text: str, dialect: Dialect) -> str:
    """Refuse what no dialect reads safely, and what this one does not read. The text is never rewritten."""
    for char in text:
        code = ord(char)
        if 0xD800 <= code <= 0xDFFF:
            raise _Unparseable("text that is not valid Unicode (a lone surrogate)")
        if char == "\t" or (char == "\n" and dialect != "cmd") or 32 <= code < 127:
            continue
        if char == "\n":
            raise _Unparseable("a newline, which cmd.exe /c does not read the way the policy would")
        if char == "\r":
            raise _Unparseable("a carriage return (a control character)")
        if code < 32 or code == 127:
            raise _Unparseable("a control character")
        if dialect != "posix":  # a Windows program may read a non-ASCII character as another one
            raise _Unparseable(
                "a non-ASCII character: PowerShell reads some as syntax, and a Windows program may read any as "
                "another character"
            )
        if unicodedata.category(char) in _POSIX_REFUSED_CATEGORIES:
            raise _Unparseable("an unusual space, line break or formatting character")
    return text


def _groups(items: list[_Word | _Op]) -> list[list[_Word | _Op]]:
    """Split lexer items at the compound boundaries."""
    groups: list[list[_Word | _Op]] = []
    current: list[_Word | _Op] = []
    pending: str | None = None  # a separator that needs a command after it
    for item in items:
        if isinstance(item, _Op) and not item.redirect and item.text in _SEPARATORS:
            if current:
                groups.append(current)
                current = []
                pending = item.text if item.text in _CONTINUING else None
            elif item.text != "\n":
                raise _Unparseable(f"an empty command before {item.text!r}")
        else:
            current.append(item)
    if current:
        groups.append(current)
    elif pending is not None:
        raise _Unparseable(f"nothing after {pending!r}")
    return groups


def _segment(group: list[_Word | _Op], dialect: Dialect, depth: int) -> CommandSegment:
    words: list[_Word] = []
    redirections: list[str] = []
    called = False
    problem: str | None = None
    at = 0
    while at < len(group):
        item = group[at]
        if isinstance(item, _Word):
            words.append(item)
            at += 1
        elif item.text == _CALL_OPERATOR:
            if at:
                problem = "a misplaced call operator"
            called = True
            at += 1
        elif not item.needs_target:
            redirections.append(item.text)
            at += 1
        else:
            target = group[at + 1] if at + 1 < len(group) else None
            if not isinstance(target, _Word):
                raise _Unparseable(f"the redirection {item.text!r} has no target")
            if item.text.endswith(("<&", ">&")) and (target.dynamic or target.raw not in _DUPLICATION_TARGETS[dialect]):
                raise _Unparseable("a descriptor duplication whose target is not one descriptor")
            redirections.append(f"{item.text}{target.raw}")
            at += 2
    assignments: list[str] = []
    if dialect == "posix":
        while words and words[0].assignment:
            assignments.append(words.pop(0).raw)
    wrappers: list[str] = []
    lookup: str | None = None
    if problem is None and dialect == "posix":
        problem, lookup = _strip_process_wrappers(words, wrappers)
    if problem is None:
        problem = _program_problem(words[0], dialect, called=called) if words else "no command, only assignments or redirections"
    if problem is None:
        problem = _launcher_problem(words, dialect)
    return CommandSegment(
        dialect=dialect,
        tokens=tuple(word.text for word in words),
        dynamic=tuple(word.dynamic for word in words),
        raw=tuple(word.raw for word in words),
        assignments=tuple(assignments),
        redirections=tuple(redirections),
        wrappers=tuple(wrappers),
        depth=depth,
        unparseable=problem,
        variadic=tuple(word.variadic for word in words),
        lookup_changed=lookup,
    )


def _strip_process_wrappers(words: list[_Word], wrappers: list[str]) -> tuple[str | None, str | None]:
    """Strip the POSIX process wrappers that run their argument vector as the command, in the forms modelled.

    Returns why the segment is unreadable (or None), and why the program is looked up elsewhere (or None).
    """
    lookup: str | None = None
    while words and not words[0].dynamic and posixpath.basename(words[0].text) in _PROCESS_WRAPPERS:
        head = words[0].text
        if len(wrappers) == _MAX_PROCESS_WRAPPERS:
            return f"more than {_MAX_PROCESS_WRAPPERS} process wrappers", lookup
        width, note = _wrapper_width(words)
        if width is None:
            return f"{head!r} with options the policy does not read", lookup
        if width == 0:
            return None, lookup  # command -v / -V looks a name up and runs nothing
        if len(words) == width:
            return f"{head!r} with no command", lookup
        following = words[width]
        if not following.dynamic and following.text.startswith("-"):
            return f"{head!r} with options the policy does not read", lookup
        lookup = note or lookup
        wrappers.append(" ".join(word.raw for word in words[:width]))
        del words[:width]
    return None, lookup


def _wrapper_width(words: list[_Word]) -> tuple[int | None, str | None]:
    """Words the wrapper at ``words[0]`` takes, and any lookup change it makes: 0 when it runs nothing, None for a
    form the policy does not read."""
    name = posixpath.basename(words[0].text)
    args = words[1:]
    if args and args[0].dynamic:
        return None, None
    first = args[0].text if args else None
    if name == "command":
        if first in ("-v", "-V"):
            return 0, None
        if first == "-p":
            return 2, _DEFAULT_PATH
        return 1, None
    if name in ("time", "nohup"):
        return 1, None
    if name == "nice":
        if first != "-n":
            return 1, None
        level = args[1] if len(args) > 1 else None
        if level is not None and not level.dynamic and _NICE_LEVEL.fullmatch(level.text):
            return 3, None
        return None, None
    if name == "timeout":
        return (2, None) if first is not None and _DURATION.fullmatch(first) else (None, None)
    width = 1  # stdbuf
    while width < len(words) and not words[width].dynamic and _STDBUF_OPTION.fullmatch(words[width].text):
        width += 1
    return (width, None) if width > 1 else (None, None)


def _program_problem(word: _Word, dialect: Dialect, *, called: bool) -> str | None:
    if word.dynamic:  # the shell decides the program
        return "the program is not a literal word"
    if not word.text:
        return "the program is an empty word"
    if dialect == "cmd":
        return _cmd_program_problem(word.text)
    if dialect == "powershell":
        return _powershell_program_problem(word, called=called)
    return None


def _windows_program_name_problem(value: str) -> str | None:
    if value.endswith((" ", ".")):
        return "a program name that ends in a blank or a dot, which Windows drops"
    drive = len(value) > 1 and value[1] == ":" and value[0].isascii() and value[0].isalpha()
    if value.count(":") > 1 or (":" in value and not drive):
        return "a ':' in a program word other than after a drive letter"
    return None


def _cmd_program_problem(value: str) -> str | None:
    if _CMD_PROGRAM.fullmatch(value) is None:
        return "a program word cmd.exe may split or read as syntax (a '/', '=', '@', '~' or another character)"
    problem = _windows_program_name_problem(value)
    if problem is not None:
        return problem
    head = _LEADING_LETTERS.match(value)
    if head is not None and head.group().lower() in _CMD_INTERNAL and len(head.group()) < len(value) and not value[len(head.group())].isalnum():
        return f"a program word cmd.exe may split: it reads it as its internal command {head.group().lower()!r}"
    return None


def _powershell_program_problem(word: _Word, *, called: bool) -> str | None:
    value = word.text
    if not called:
        if word.raw[:1] in ("'", '"'):
            return "a quoted string at the start of a PowerShell statement is an expression, not a command (use &)"
        if _PS_BARE_PROGRAM.fullmatch(value) is None:
            return "a program word PowerShell may read as an expression or an operator"
    elif _PS_CALLED_PROGRAM.fullmatch(value) is None:
        return "a program word with a character the policy does not read after the call operator"
    if value == ".":
        return None  # dot-sourcing: the launcher check names it
    return _windows_program_name_problem(value)


def _launcher_problem(words: list[_Word], dialect: Dialect) -> str | None:
    program = words[0].text
    name = windows_program_stem(program)
    if name in _KEYWORDS[dialect]:
        return f"{program!r} is {_DIALECT_NAMES[dialect]} syntax the policy does not read"
    if name in _LAUNCHERS[dialect] or name in _OTHER_SHELLS:
        return f"{program!r} runs a command the policy cannot see"
    if name in _PROCESS_WRAPPERS and (dialect != "posix" or posixpath.basename(program) != name):
        return f"{program!r} runs a command the policy cannot see (a process wrapper spelled or started as the policy does not read)"
    subcommands = _SUBCOMMAND_LAUNCHERS.get(name)
    if subcommands is not None:
        for word in words[1:]:
            if word.dynamic or word.text in subcommands:
                return f"{program!r} {word.raw} runs a program the policy cannot see"
    return None


def _shell_wrapper(segment: CommandSegment) -> _Unwrapped | str | None:
    """``(script, dialect, lookup change)`` for a shell wrapper the policy unwraps; a reason for a shell started
    any other way (it would run commands the policy cannot see); None for any other program."""
    if not segment.tokens:
        return None
    head = segment.tokens[0]
    name = windows_program_stem(head)
    args = segment.tokens[1:]
    readable = not any(segment.dynamic)
    outer = segment.dialect
    if name in _POSIX_SHELLS:
        if outer != "posix":
            return f"{head!r} starts a POSIX shell from {_DIALECT_NAMES[outer]}, which the policy does not read"
        if outer == "posix" and posixpath.basename(head) in _POSIX_SHELLS and readable:
            script = _posix_script(args)
            if script is not None:
                return script
        return f"{head!r} runs commands the policy cannot see unless it is sh, bash or dash with one inline script"
    if name in _PS_SHELLS:
        if outer == "posix":
            return f"{head!r} starts PowerShell from a POSIX shell, which the policy does not read"
        if outer != "posix" and readable:
            script = _powershell_script(args)
            if script is not None:
                return script
        return f"{head!r} runs a script the policy cannot see unless it is a -Command script"
    if name == "cmd":
        if outer != "cmd":
            return f"{head!r} starts cmd.exe from {_DIALECT_NAMES[outer]}, which the policy does not read"
        if outer == "cmd" and readable:
            script = _cmd_script(segment)
            if script is not None:
                return script
        return f"{head!r} runs commands the policy cannot see unless they follow /c with no double quote"
    return None


def _posix_script(args: tuple[str, ...]) -> _Unwrapped | None:
    if len(args) == 2 and args[0] in _POSIX_SCRIPT_FLAGS:
        return args[1], "posix", (_LOGIN_SHELL if _POSIX_SCRIPT_FLAGS[args[0]] else None)
    if len(args) == 3 and args[0] in ("-l", "--login") and args[1] == "-c":
        return args[2], "posix", _LOGIN_SHELL
    return None


def _powershell_script(args: tuple[str, ...]) -> _Unwrapped | None:
    """The script ``-Command`` runs: the argument values PowerShell receives, joined by one blank."""
    at, profile = 0, True
    while at < len(args):
        flag = args[at].lower()
        if flag == "-noprofile":
            profile = False
            at += 1
        elif flag in ("-nologo", "-noninteractive"):
            at += 1
        elif flag == "-executionpolicy" and at + 1 < len(args) and args[at + 1].lower() in _PS_EXECUTION_POLICIES:
            at += 2
        elif flag in ("-command", "-c"):
            script = " ".join(args[at + 1:])
            if not script.strip() or script.strip() == "-":
                return None
            return script, "powershell", (_PS_PROFILE if profile else None)
        else:
            return None
    return None


def _cmd_script(segment: CommandSegment) -> _Unwrapped | None:
    """The command ``cmd /c`` runs: the words after ``/c``, which the outer cmd.exe passes on unchanged."""
    args = segment.tokens[1:]
    at = 1 if args and args[0].lower() == "/d" else 0
    if len(args) <= at + 1 or args[at].lower() != "/c":
        return None
    if any('"' in raw for raw in segment.raw[at + 2:]):
        return None
    return " ".join(args[at + 1:]), "cmd", None


def _is_state_mutator(segment: CommandSegment) -> bool:
    if not segment.tokens or segment.dynamic[0]:
        return False
    program = segment.tokens[0]
    if segment.dialect != "posix" and _DRIVE_CHANGE.fullmatch(program):
        return True
    return windows_program_stem(program) in _STATE_MUTATORS[segment.dialect]


# --------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------


def parse_command(
    command: str,
    *,
    dialect: Dialect | None = None,
    limits: CommandPolicyConfig | None = None,
    unwrap_shells: bool = True,
) -> ParsedCommand:
    """Split ``command`` into segments under ``dialect`` (default: ``default_dialect()``).

    ``limits`` supplies ``max_command_chars``, ``max_segments`` and ``max_nesting``
    (default: ``CommandPolicyConfig()``'s). With ``unwrap_shells`` a shell wrapper the
    policy unwraps (``bash -c S``, ``cmd /c S``, ``pwsh -NoProfile -Command S``) is
    replaced by the segments of ``S``, which inherit its context. Hostile text never
    raises: what cannot be read is reported as ``unparseable``.
    """
    if type(command) is not str:
        raise TypeError("command_policy_command_type_invalid")
    chosen = _dialect(dialect)
    bounds = _DEFAULT_LIMITS if limits is None else limits
    segments: list[CommandSegment] = []
    try:
        if len(command) > bounds.max_command_chars:
            raise _OverBudget(f"the command is longer than {bounds.max_command_chars} characters")
        _parse_into(command, chosen, bounds, 0, unwrap_shells, segments, None)
        if not segments:
            raise _Unparseable("no command")
    except _Unparseable as exc:
        return ParsedCommand(chosen, (), exc.reason)
    return ParsedCommand(chosen, _with_lookup_context(segments), None)


def _with_lookup_context(segments: list[CommandSegment]) -> tuple[CommandSegment, ...]:
    """A line that changes the working directory or the environment changes where every program in it resolves."""
    mutator = next((segment for segment in segments if _is_state_mutator(segment)), None)
    if mutator is None:
        return tuple(segments)
    reason = f"the command changes the working directory or the environment ({mutator.tokens[0]})"
    return tuple(s if s.lookup_changed is not None else replace(s, lookup_changed=reason) for s in segments)


def _parse_into(
    text: str,
    dialect: Dialect,
    bounds: CommandPolicyConfig,
    depth: int,
    unwrap: bool,
    out: list[CommandSegment],
    context: _Context | None,
) -> None:
    lexer = _LEXERS[dialect](_checked_text(text, dialect), depth, bounds.max_nesting)
    lexer.lex()
    _emit(lexer, dialect, bounds, unwrap, out, context)


def _emit(
    lexer: _Lexer,
    dialect: Dialect,
    bounds: CommandPolicyConfig,
    unwrap: bool,
    out: list[CommandSegment],
    context: _Context | None,
) -> None:
    for group in _groups(lexer.items):
        segment = _segment(group, dialect, lexer.depth)
        if context is not None:
            segment = _inherit(segment, context)
        wrapper = _shell_wrapper(segment) if unwrap and segment.unparseable is None else None
        if isinstance(wrapper, tuple):
            refused = _unwrap(segment, wrapper, bounds, out)
            if refused is not None:
                out.append(refused)
        else:
            out.append(segment if wrapper is None else replace(segment, unparseable=wrapper))
        if len(out) > bounds.max_segments:
            raise _OverBudget(f"more than {bounds.max_segments} segments")
    for inner in lexer.subs:
        _emit(inner, "posix", bounds, unwrap, out, context)


def _inherit(segment: CommandSegment, context: _Context) -> CommandSegment:
    return replace(
        segment,
        assignments=context.assignments + segment.assignments,
        redirections=context.redirections + segment.redirections,
        wrappers=context.wrappers + segment.wrappers,
        lookup_changed=segment.lookup_changed or context.lookup_changed,
    )


def _unwrap(
    segment: CommandSegment, wrapper: _Unwrapped, bounds: CommandPolicyConfig, out: list[CommandSegment],
) -> CommandSegment | None:
    """Replace a shell-wrapper segment by its script's segments, which inherit its context; None when that worked."""
    script, inner, note = wrapper
    if segment.depth >= bounds.max_nesting:
        return replace(segment, unparseable=f"shell wrappers nested deeper than {bounds.max_nesting}")
    context = _Context(segment.assignments, segment.redirections, segment.wrappers, note or segment.lookup_changed)
    mark = len(out)
    try:
        _parse_into(script, inner, bounds, segment.depth + 1, True, out, context)
    except _OverBudget:
        raise
    except _Unparseable as exc:
        del out[mark:]
        return replace(segment, unparseable=f"the wrapped script is unparseable: {exc.reason}")
    if len(out) == mark:
        return replace(segment, unparseable="the wrapped script is empty")
    return None


# --------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------


def _require_config(config: object) -> None:
    if type(config) is not CommandPolicyConfig:
        raise TypeError("command_policy_config_type_invalid")


def _no_policy(dialect: Dialect) -> CommandEvaluation:
    return CommandEvaluation("no_policy", None, dialect, None, (), None)


def _resolve(resolve: ProgramResolver | None, program: str) -> str | None:
    if resolve is None:
        return None
    resolved = resolve(program)
    if resolved is not None and type(resolved) is not str:
        raise TypeError("command_policy_resolver_result_invalid")
    return resolved


def _strictest(decisions: Iterable[CommandDecisionName]) -> CommandDecisionName:
    return max(decisions, key=COMMAND_DECISION_RANK.__getitem__)


def _options(entry: str | tuple[str, ...]) -> tuple[str, ...]:
    return (entry,) if isinstance(entry, str) else entry


def _program_matches(expected: str | tuple[str, ...], program: str, dialect: Dialect, *, restrictive: bool) -> bool:
    names = _options(expected)
    if dialect == "posix" and not restrictive:
        return posixpath.basename(program) in names
    stem = windows_program_stem(program)  # a restrictive rule matches every spelling of its program
    return any(windows_program_stem(name) == stem for name in names)


def _restrictive_cover(pattern: tuple[str | tuple[str, ...], ...], segment: CommandSegment) -> int | None:
    """How many of the segment's words a restrictive pattern covers, or None when it cannot match.

    A literal word must equal the next pattern word, a one-word dynamic word can be it, and a variadic word can be
    every pattern word still wanted. At most ``len(pattern) - 1`` steps.
    """
    tokens = segment.tokens
    wanted = len(pattern) - 1
    if wanted == 0:
        return 1
    done = 0
    for at in range(1, len(tokens)):
        if segment.variadic[at]:
            return at + 1  # zero or more words of any value: it can supply every word still wanted
        if not segment.dynamic[at] and tokens[at] not in _options(pattern[done + 1]):
            return None
        done += 1
        if done == wanted:
            return at + 1
    return None


def _match(
    rule: CommandPolicyRule, segment: CommandSegment, index: int, resolve: ProgramResolver | None,
) -> RuleMatch | None:
    restrictive = rule.decision != "allow"
    tokens = segment.tokens
    if not _program_matches(rule.pattern[0], tokens[0], segment.dialect, restrictive=restrictive):
        return None
    if restrictive:
        covered = _restrictive_cover(rule.pattern, segment)
        if covered is None:
            return None
        return RuleMatch(rule.name, rule.decision, rule.justification, rule.alternative, tokens[:covered], index, None, False)
    if len(tokens) < len(rule.pattern) or segment.assignments:
        return None
    for position in range(1, len(rule.pattern)):
        if segment.dynamic[position] or tokens[position] not in _options(rule.pattern[position]):
            return None  # a word the shell computes is no proof of what the program receives
    return _allow_match(rule, segment, tokens[: len(rule.pattern)], index, resolve)


def _allow_match(
    rule: CommandPolicyRule,
    segment: CommandSegment,
    prefix: tuple[str, ...],
    index: int,
    resolve: ProgramResolver | None,
) -> RuleMatch | None:
    program = segment.tokens[0]
    is_path = _is_path(program, segment.dialect)
    if not rule.host_executable:
        if is_path:
            return None  # a path is another binary than the bare name the rule allows, unless pinned
        return RuleMatch(rule.name, "allow", rule.justification, None, prefix, index, None, False)
    paths = ", ".join(rule.host_executable)
    if is_path:
        resolved: str | None = program
    elif segment.lookup_changed is not None:
        why = f"{segment.lookup_changed}, so where {program!r} runs from is not proven"
        return _pin_violation(rule, prefix, index, None, why, paths)
    else:
        resolved = _resolve(resolve, program)
    pinned = {_path_key(pin, segment.dialect) for pin in rule.host_executable}
    if resolved is not None and _path_key(resolved, segment.dialect) in pinned:
        return RuleMatch(rule.name, "allow", rule.justification, None, prefix, index, resolved, False)
    found = repr(resolved) if resolved is not None else "a program that does not resolve"
    return _pin_violation(rule, prefix, index, resolved, f"{found} is not one of them", paths)


def _pin_violation(
    rule: CommandPolicyRule, prefix: tuple[str, ...], index: int, resolved: str | None, why: str, paths: str,
) -> RuleMatch:
    return RuleMatch(
        rule.name,
        "forbid",
        f"rule {rule.name!r} allows {rule.pattern[0]} only at {paths}; {why}",
        f"run the pinned executable: {paths}",
        prefix,
        index,
        resolved,
        True,
    )


def _judge(
    config: CommandPolicyConfig,
    segment: CommandSegment,
    index: int,
    unmatched: CommandDecisionName,
    resolve: ProgramResolver | None,
) -> SegmentVerdict:
    if segment.unparseable is not None:
        return SegmentVerdict(index, segment, config.unparseable_decision, "unparseable", ())
    matches = tuple(found for rule in config.rules if (found := _match(rule, segment, index, resolve)) is not None)
    if not matches:
        return SegmentVerdict(index, segment, unmatched, "unmatched", ())
    return SegmentVerdict(index, segment, _strictest(match.decision for match in matches), "rule", matches)


def _evaluate(
    config: CommandPolicyConfig,
    command: str,
    dialect: Dialect,
    resolve: ProgramResolver | None,
    digest: str,
) -> CommandEvaluation:
    """The one evaluator: ``evaluate_command``, ``CommandPolicy.evaluate`` and ``self_test`` all call it."""
    parsed = parse_command(command, dialect=dialect, limits=config)
    if parsed.unparseable is not None:
        return CommandEvaluation("evaluated", config.unparseable_decision, dialect, digest, (), parsed.unparseable)
    unmatched = cast(CommandDecisionName, config.unmatched_decision)  # declared whenever rules exist
    verdicts = tuple(_judge(config, segment, index, unmatched, resolve) for index, segment in enumerate(parsed.segments))
    return CommandEvaluation("evaluated", _strictest(v.decision for v in verdicts), dialect, digest, verdicts, None)


def evaluate_command(
    config: CommandPolicyConfig,
    command: str,
    *,
    dialect: Dialect | None = None,
    resolve_program: ProgramResolver | None = None,
) -> CommandEvaluation:
    """Judge ``command`` against ``config`` under ``dialect`` (default: the platform's).

    ``resolve_program`` maps a bare program name to the path it would run in the
    command's starting context; it is consulted only for a pinned ``allow`` rule, and
    without it (or after the line changes that context) such a rule cannot prove a
    bare name and refuses it.
    """
    _require_config(config)
    chosen = _dialect(dialect)
    if not config.rules:  # no policy: nothing is parsed or decided
        return _no_policy(chosen)
    return _evaluate(config, command, chosen, resolve_program, policy_digest(config))


# --------------------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------------------


def _example_problem(rule: str, expectation: str, evaluation: CommandEvaluation) -> str | None:
    own = [match for match in evaluation.matched_rules if match.rule == rule]
    matched = any(not match.pin_violation for match in own)
    if expectation == "not_match":
        return "matches it" if matched else None
    if matched:
        return None
    if evaluation.unparseable is not None:
        return f"does not match: the example is unparseable ({evaluation.unparseable})"
    unread = [verdict.segment.unparseable for verdict in evaluation.segments if verdict.segment.unparseable]
    if unread:
        return f"does not match: part of the example is unparseable ({unread[0]})"
    if own:
        return f"does not match: {own[0].justification}"
    return "does not match"


def self_test(config: CommandPolicyConfig, *, dialect: Dialect | None = None) -> SelfTestReport:
    """Judge every rule's examples with the runtime evaluator, under ``dialect``.

    No program resolver is used, so a pinned rule's examples name absolute paths
    and the result does not depend on the host. Never raises for a failing
    example: ``CommandPolicy`` turns a failed report into an error.
    """
    _require_config(config)
    chosen = _dialect(dialect)
    digest = policy_digest(config)
    failures: list[SelfTestFailure] = []
    checked = 0
    for rule in config.rules:
        for expectation, examples in (("match", rule.match), ("not_match", rule.not_match)):
            for example in examples:
                checked += 1
                observed = _example_problem(rule.name, expectation, _evaluate(config, example, chosen, None, digest))
                if observed is not None:
                    failures.append(SelfTestFailure(rule.name, cast(Literal["match", "not_match"], expectation), example, observed))
    return SelfTestReport(chosen, checked, tuple(failures))


class CommandPolicy:
    """A command policy that has passed its self-test under one dialect.

    Construction runs ``self_test`` and raises ``CommandPolicySelfTestError`` (a
    ``ValueError``) naming each failing rule and example, so a policy whose
    examples are wrong cannot be built; AD-1328 S2 builds it at startup, where a
    failure stops startup. With no rules, ``evaluate`` returns ``no_policy`` and
    parses nothing.
    """

    def __init__(self, config: CommandPolicyConfig, *, dialect: Dialect | None = None) -> None:
        _require_config(config)
        self._config = config
        self._dialect = _dialect(dialect)
        self._digest = policy_digest(config)
        self._report = self_test(config, dialect=self._dialect)
        if not self._report.passed:
            raise CommandPolicySelfTestError(self._report)

    @property
    def config(self) -> CommandPolicyConfig:
        return self._config

    @property
    def dialect(self) -> Dialect:
        return self._dialect

    @property
    def digest(self) -> str:
        return self._digest

    @property
    def self_test_report(self) -> SelfTestReport:
        return self._report

    @property
    def configured(self) -> bool:
        """False when no rule is configured, so every command runs as it would without a policy."""
        return bool(self._config.rules)

    def evaluate(self, command: str, *, resolve_program: ProgramResolver | None = None) -> CommandEvaluation:
        if not self._config.rules:
            return _no_policy(self._dialect)
        return _evaluate(self._config, command, self._dialect, resolve_program, self._digest)

    def canonical(self, command: str, *, resolve_program: ProgramResolver | None = None) -> CanonicalCommand:
        return canonical_command(command, dialect=self._dialect, resolve_program=resolve_program, limits=self._config)


# --------------------------------------------------------------------------------------
# Canonical command and policy digest
# --------------------------------------------------------------------------------------


def _canonical_json(value: object) -> bytes:
    """RFC 8785 bytes (AD-1144's canonicaliser), imported lazily so that importing this
    module does not run the federation package ``__init__`` (precedent:
    ``probos.cognitive.elastic_team.canonicalize_projection``)."""
    from probos.federation.ard.jcs import canonicalize

    return canonicalize(value)


def policy_digest(config: CommandPolicyConfig) -> str:
    """``POLICY_DIGEST_SCHEME``: sha256 of a domain tag and the RFC 8785 JSON of the whole
    policy, examples included. Any change to the policy changes it, which is what
    expires an approval granted under the old one."""
    _require_config(config)
    return hashlib.sha256(_POLICY_DOMAIN + _canonical_json(config.model_dump(mode="json"))).hexdigest()


def _is_simple(segment: CommandSegment) -> bool:
    return (
        segment.unparseable is None
        and bool(segment.tokens)
        and not segment.assignments
        and not segment.redirections
        and not segment.wrappers
        and not any(segment.dynamic)
        and segment.lookup_changed is None
        and not (segment.dialect == "cmd" and windows_program_stem(segment.tokens[0]) in _CMD_INTERNAL)
    )


def _canonical_program(segment: CommandSegment, resolve: ProgramResolver | None) -> str:
    program = segment.tokens[0]
    if _is_path(program, segment.dialect):
        return _path_key(program, segment.dialect)
    resolved = _resolve(resolve, program)
    if resolved is not None:
        return _path_key(resolved, segment.dialect)
    return _program_name(program, segment.dialect)


def canonical_command(
    command: str,
    *,
    dialect: Dialect | None = None,
    resolve_program: ProgramResolver | None = None,
    limits: CommandPolicyConfig | None = None,
) -> CanonicalCommand:
    """The approval-reuse identity of ``command`` (see ``CanonicalCommand``).

    Read with the same parser the evaluation uses (shell wrappers unwrapped, at most
    ``max_nesting`` deep); pass the same ``resolve_program`` the evaluation used.
    Never raises for hostile text.
    """
    if type(command) is not str:
        raise TypeError("command_policy_command_type_invalid")
    bounds = _DEFAULT_LIMITS if limits is None else limits
    chosen = _dialect(dialect)
    if not _is_scalar_text(command):
        return CanonicalCommand("script", chosen, (_MALFORMED_SCRIPT_TAG, command.encode("utf-16-le", "surrogatepass").hex()))
    parsed = parse_command(command, dialect=chosen, limits=bounds)
    if parsed.unparseable is None and len(parsed.segments) == 1 and _is_simple(parsed.segments[0]):
        segment = parsed.segments[0]
        return CanonicalCommand("argv", None, (_canonical_program(segment, resolve_program), *segment.tokens[1:]))
    return CanonicalCommand("script", chosen, (command,))
```

### Section 3 -- NEW `tests/fixtures/ad1328_argv_probe.py`

```python
"""AD-1328 S1 repair (R6): the argv probe the shell oracle runs.

Appends the arguments this process received, as one JSON line, to the file named by
``AD1328_PROBE_LOG``; prints nothing. Started by the shells under test, never imported.
"""

import json
import os
import sys

with open(os.environ["AD1328_PROBE_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
```

### Section 4 -- NEW `tests/fixtures/ad1328_shell_oracle.json`

Fields: `id`, `dialect`, `constructs`, `text` (placeholders `{P}`, `{B}`, replaced with `str.replace`), `policy` (per probe segment: the words after the prefix, `null` for a dynamic word), optional `marks` (per probe segment: `l` literal, `o` one word, `v` variadic; default all `l`), optional `runs` (live invocations; default the number of probe segments), optional `live` (exact argv lists, or a map shell -> lists), `env`, `files` (created empty in the run directory), `requires` (programs that must be on PATH), `shells` (subset of the dialect's shells).

```json
{
  "schema": "probos.ad1328.shell_oracle/v1",
  "provenance": {
    "authored": "2026-10-16 claude-architect, from each shell's documented grammar (prompts/ad-1328-s1-repair-r1.md, R6); not yet executed by the author",
    "consumers": {
      "posix": "/bin/sh -c: dash and bash on a POSIX host",
      "cmd": "cmd.exe /c, as subprocess.run(text, shell=True) and asyncio.create_subprocess_shell start it on Windows",
      "powershell": "powershell -NoProfile -Command (Windows PowerShell 5.1) and pwsh -NoProfile -Command (PowerShell 7)"
    },
    "verified_on": []
  },
  "constructs": {
    "posix": ["P-WORD", "P-SQ", "P-DQ", "P-BS", "P-CONCAT", "P-CONT", "P-QNL", "P-EMPTY", "P-SEQ", "P-NL", "P-AND", "P-OR", "P-PIPE", "P-BG", "P-COMMENT", "P-REDIR", "P-ASSIGN", "P-UNICODE", "P-WRAP-SH", "P-WRAP-BASH", "P-WRAP-DASH", "P-WRAP-LOGIN", "P-WRAPPERS", "P-TIME"],
    "cmd": ["C-WORD", "C-PROGRAM-QUOTED", "C-PROGRAM-BARE", "C-DQ", "C-QSPECIAL", "C-EMPTY", "C-CONCAT", "C-BACKSLASH", "C-SEQ", "C-AND", "C-OR", "C-PIPE", "C-REDIR", "C-WRAP-CMD", "C-WRAP-PS", "C-WRAP-PS-WORDS"],
    "powershell": ["S-WORD", "S-CALL", "S-PROGRAM-BARE", "S-SQ", "S-DQ", "S-ESC", "S-NUM", "S-PARAM", "S-SEQ", "S-NL", "S-PIPE", "S-REDIR", "S-COMMENT", "S-WRAP-PS", "S-WRAP-PS-WORDS"]
  },
  "rows": [
    {"id": "P01", "dialect": "posix", "constructs": ["P-WORD"], "text": "{P} a b-c d.e f/g h:i j=k l+m n,o p@q r%s t^u v!w HEAD~1", "policy": [["a", "b-c", "d.e", "f/g", "h:i", "j=k", "l+m", "n,o", "p@q", "r%s", "t^u", "v!w", "HEAD~1"]]},
    {"id": "P02", "dialect": "posix", "constructs": ["P-SQ", "P-EMPTY"], "text": "{P} 'a b' 'c\"d' '$e' 'f\\g' ''", "policy": [["a b", "c\"d", "$e", "f\\g", ""]]},
    {"id": "P03", "dialect": "posix", "constructs": ["P-DQ", "P-EMPTY"], "text": "{P} \"a b\" \"c'd\" \"e\\\"f\" \"g\\\\h\" \"i\\j\" \"k\\$l\" \"m\\`n\" \"\"", "policy": [["a b", "c'd", "e\"f", "g\\h", "i\\j", "k$l", "m`n", ""]]},
    {"id": "P04", "dialect": "posix", "constructs": ["P-BS"], "text": "{P} a\\ b c\\\"d e\\\\f \\$g", "policy": [["a b", "c\"d", "e\\f", "$g"]]},
    {"id": "P05", "dialect": "posix", "constructs": ["P-CONCAT"], "text": "{P} a'b c'd\"e f\"g", "policy": [["ab cde fg"]]},
    {"id": "P06", "dialect": "posix", "constructs": ["P-CONT"], "text": "{P} ab\\\ncd \"e\\\nf\"", "policy": [["abcd", "ef"]]},
    {"id": "P07", "dialect": "posix", "constructs": ["P-QNL"], "text": "{P} 'a\nb' \"c\nd\"", "policy": [["a\nb", "c\nd"]]},
    {"id": "P08", "dialect": "posix", "constructs": ["P-SEQ", "P-NL"], "text": "{P} a; {P} b\n{P} c", "policy": [["a"], ["b"], ["c"]]},
    {"id": "P09", "dialect": "posix", "constructs": ["P-AND", "P-OR"], "text": "{P} a && {P} b || {P} c", "policy": [["a"], ["b"], ["c"]], "runs": 2, "live": [["a"], ["b"]]},
    {"id": "P10", "dialect": "posix", "constructs": ["P-PIPE"], "text": "{P} a | {P} b", "policy": [["a"], ["b"]]},
    {"id": "P11", "dialect": "posix", "constructs": ["P-BG"], "text": "{P} a & {P} b; wait", "policy": [["a"], ["b"]]},
    {"id": "P12", "dialect": "posix", "constructs": ["P-COMMENT"], "text": "{P} a # b c\n{P} d#e", "policy": [["a"], ["d#e"]]},
    {"id": "P13", "dialect": "posix", "constructs": ["P-REDIR"], "text": "{P} a > /dev/null; {P} b 2>&1; {P} c < /dev/null; {P} d 2>/dev/null >>/dev/null; {P} e >&2 3<&-", "policy": [["a"], ["b"], ["c"], ["d"], ["e"]]},
    {"id": "P14", "dialect": "posix", "constructs": ["P-ASSIGN"], "text": "X=1 Y='a b' {P} a", "policy": [["a"]]},
    {"id": "P15", "dialect": "posix", "constructs": [], "env": {"W": "x  y"}, "text": "{P} $W \"$W\" ${W} \"${W}\"", "policy": [[null, null, null, null]], "marks": ["vovo"], "live": [["x", "y", "x  y", "x", "y", "x  y"]]},
    {"id": "P16", "dialect": "posix", "constructs": [], "text": "{P} \"$#\" $1 \"$@\"", "policy": [[null, null, null]], "marks": ["ovv"], "live": [["0"]]},
    {"id": "P17", "dialect": "posix", "constructs": [], "text": "{P} $(printf 'a b') \"$(printf 'c d')\"", "policy": [[null, null]], "marks": ["vo"], "live": [["a", "b", "c d"]]},
    {"id": "P18", "dialect": "posix", "constructs": [], "files": ["g1.txt", "g2.txt"], "text": "{P} g*.txt 'g*.txt' g?.txt", "policy": [[null, "g*.txt", null]], "marks": ["vlv"], "live": [["g1.txt", "g2.txt", "g*.txt", "g1.txt", "g2.txt"]]},
    {"id": "P19", "dialect": "posix", "constructs": [], "text": "{P} {a,b} x{c,d}", "policy": [[null, null]], "marks": ["vv"], "live": {"bash": [["a", "b", "xc", "xd"]], "dash": [["{a,b}", "x{c,d}"]]}},
    {"id": "P20", "dialect": "posix", "constructs": [], "env": {"HOME": "/tmp/ad1328-home"}, "text": "{P} ~ ~/x a=~ b:~ \"~\" a~b", "policy": [[null, null, null, null, "~", "a~b"]], "marks": ["ooooll"]},
    {"id": "P21", "dialect": "posix", "constructs": ["P-UNICODE"], "text": "{P} café 'naïve' \"日本\"", "policy": [["café", "naïve", "日本"]]},
    {"id": "P22", "dialect": "posix", "constructs": ["P-WRAP-SH"], "text": "sh -c \"{P} a 'b c'\"", "policy": [["a", "b c"]]},
    {"id": "P23", "dialect": "posix", "constructs": ["P-WRAP-BASH"], "requires": ["bash"], "text": "bash -c \"{P} a\"", "policy": [["a"]]},
    {"id": "P24", "dialect": "posix", "constructs": ["P-WRAP-DASH"], "requires": ["dash"], "text": "dash -c \"{P} a\"", "policy": [["a"]]},
    {"id": "P25", "dialect": "posix", "constructs": ["P-WRAP-LOGIN"], "requires": ["bash"], "text": "bash -lc \"{P} a\"", "policy": [["a"]]},
    {"id": "P26", "dialect": "posix", "constructs": ["P-WRAPPERS"], "requires": ["nice", "nohup", "timeout", "stdbuf"], "text": "nice -n 5 {P} a; nohup {P} b; timeout 30 {P} c; stdbuf -oL {P} d; command {P} e; command -p {P} f", "policy": [["a"], ["b"], ["c"], ["d"], ["e"], ["f"]]},
    {"id": "P27", "dialect": "posix", "constructs": ["P-TIME"], "shells": ["bash"], "text": "time {P} a", "policy": [["a"]]},
    {"id": "C01", "dialect": "cmd", "constructs": ["C-WORD", "C-PROGRAM-QUOTED"], "text": "{P} a b-c d.e f/g h\\i j:k l=m n+o p#q r$s t@u v~w HEAD~1", "policy": [["a", "b-c", "d.e", "f/g", "h\\i", "j:k", "l=m", "n+o", "p#q", "r$s", "t@u", "v~w", "HEAD~1"]]},
    {"id": "C02", "dialect": "cmd", "constructs": ["C-DQ", "C-QSPECIAL", "C-EMPTY"], "text": "{P} \"a b\" \"c&d|e<f>g\" \"h(i)j;k,l'm^n\" \"\"", "policy": [["a b", "c&d|e<f>g", "h(i)j;k,l'm^n", ""]]},
    {"id": "C03", "dialect": "cmd", "constructs": ["C-CONCAT"], "text": "{P} a\"b c\"d \"e\"f g\"h\"", "policy": [["ab cd", "ef", "gh"]]},
    {"id": "C04", "dialect": "cmd", "constructs": ["C-BACKSLASH"], "text": "{P} a\\b c\\\\d \"e\\f\" \"g\\\\h i\"", "policy": [["a\\b", "c\\\\d", "e\\f", "g\\\\h i"]]},
    {"id": "C05", "dialect": "cmd", "constructs": ["C-SEQ", "C-AND", "C-OR"], "text": "{P} a & {P} b && {P} c || {P} d", "policy": [["a"], ["b"], ["c"], ["d"]], "runs": 3, "live": [["a"], ["b"], ["c"]]},
    {"id": "C06", "dialect": "cmd", "constructs": ["C-PIPE"], "text": "{P} a | {P} b", "policy": [["a"], ["b"]]},
    {"id": "C07", "dialect": "cmd", "constructs": ["C-REDIR"], "text": "{P} a > NUL & {P} b 2>&1 & {P} c 2> NUL & {P} d >> NUL & {P} e < NUL", "policy": [["a"], ["b"], ["c"], ["d"], ["e"]]},
    {"id": "C08", "dialect": "cmd", "constructs": [], "files": ["a1.txt"], "text": "{P} a*.txt b?c [d] {e} @f ~g", "policy": [[null, null, null, null, null, null]], "marks": ["vvvvvv"]},
    {"id": "C09", "dialect": "cmd", "constructs": ["C-PROGRAM-BARE"], "text": "{B} a", "policy": [["a"]]},
    {"id": "C10", "dialect": "cmd", "constructs": ["C-WRAP-CMD"], "text": "cmd /c {B} a b", "policy": [["a", "b"]]},
    {"id": "C11", "dialect": "cmd", "constructs": ["C-WRAP-PS"], "requires": ["powershell"], "text": "powershell -NoProfile -Command \"{B} a 'b c'\"", "policy": [["a", "b c"]]},
    {"id": "C12", "dialect": "cmd", "constructs": ["C-WRAP-PS-WORDS"], "requires": ["pwsh"], "text": "pwsh -NoProfile -Command {B} a b", "policy": [["a", "b"]]},
    {"id": "S01", "dialect": "powershell", "constructs": ["S-WORD", "S-CALL"], "text": "{P} a b-c d.e f/g h\\i j:k l=m n+o p#q t@u v~w HEAD~1 a.b.c", "policy": [["a", "b-c", "d.e", "f/g", "h\\i", "j:k", "l=m", "n+o", "p#q", "t@u", "v~w", "HEAD~1", "a.b.c"]]},
    {"id": "S02", "dialect": "powershell", "constructs": ["S-SQ"], "text": "{P} 'a b' 'it''s ok' 'c$d' 'e`f'", "policy": [["a b", "it's ok", "c$d", "e`f"]]},
    {"id": "S03", "dialect": "powershell", "constructs": ["S-DQ"], "text": "{P} \"a b\" \"c`$d\" \"e``f\" \"g'h i\"", "policy": [["a b", "c$d", "e`f", "g'h i"]]},
    {"id": "S04", "dialect": "powershell", "constructs": ["S-ESC"], "text": "{P} a` b c`#d e`$f", "policy": [["a b", "c#d", "e$f"]]},
    {"id": "S05", "dialect": "powershell", "constructs": ["S-NUM", "S-PARAM"], "text": "{P} -20 10 0 -n --force -x:y", "policy": [["-20", "10", "0", "-n", "--force", "-x:y"]]},
    {"id": "S06", "dialect": "powershell", "constructs": ["S-SEQ", "S-NL"], "text": "{P} a; {P} b\n{P} c", "policy": [["a"], ["b"], ["c"]]},
    {"id": "S07", "dialect": "powershell", "constructs": ["S-PIPE"], "text": "{P} a | {P} b", "policy": [["a"], ["b"]]},
    {"id": "S08", "dialect": "powershell", "constructs": ["S-REDIR"], "text": "{P} a > $null; {P} b 2>&1; {P} c 2> x.txt; {P} d *> y.txt; {P} e >> z.txt", "policy": [["a"], ["b"], ["c"], ["d"], ["e"]]},
    {"id": "S09", "dialect": "powershell", "constructs": ["S-COMMENT"], "text": "{P} a # b\n{P} c#d", "policy": [["a"], ["c#d"]]},
    {"id": "S10", "dialect": "powershell", "constructs": ["S-PROGRAM-BARE"], "text": "{B} a", "policy": [["a"]]},
    {"id": "S11", "dialect": "powershell", "constructs": [], "env": {"W": "x y"}, "text": "{P} $env:W \"$env:W\" ${env:W}", "policy": [[null, null, null]], "marks": ["vvv"]},
    {"id": "S12", "dialect": "powershell", "constructs": [], "files": ["a1.txt"], "text": "{P} a*.txt ~", "policy": [[null, null]], "marks": ["vv"]},
    {"id": "S13", "dialect": "powershell", "constructs": ["S-WRAP-PS"], "requires": ["powershell"], "text": "powershell -NoProfile -Command \"{B} a 'b c'\"", "policy": [["a", "b c"]]},
    {"id": "S14", "dialect": "powershell", "constructs": ["S-WRAP-PS-WORDS"], "requires": ["pwsh"], "text": "pwsh -NoProfile -Command {B} a b", "policy": [["a", "b"]]}
  ]
}
```

### Section 5 -- `DECISIONS.md`

<<<<<<< SEARCH
- *D6 (canonical command, digest).* An `argv` key (resolved program, literal words, dialect-free) for one simple command after unwrapping at most `max_nesting` shell wrappers; otherwise a `script` key of the innermost script's exact text and dialect (the `-lc`/`-c` mode is dropped). Both keys and the policy digest are domain-separated sha256 over RFC 8785 JSON, versioned `.../v1`.
=======
- *D6 (canonical command, digest).* An `argv` key (resolved program, literal words, dialect-free) for exactly one simple command, after unwrapping shell wrappers (at most `max_nesting`), that runs in the starting lookup context with no assignments, redirections or process wrappers of its own or its wrapper's, and is not a `cmd.exe` internal command; otherwise a `script` key of the dialect and the exact command text (text that is not valid Unicode keys as a two-part script key of its UTF-16 hex). Both keys and the policy digest are domain-separated sha256 over RFC 8785 JSON, versioned `.../v1`.
- *Repair after review round 1 (2026-10-16).* A closed grammar: a construct is read only when its meaning to the shell and to the program receiving the words is modelled and checked against that shell by a recorded oracle (`tests/fixtures/ad1328_shell_oracle.json`); everything else is unparseable. `cmd` and PowerShell read an ASCII-only language whose words reach a program unchanged (UCRT, MSYS2/Cygwin and batch-file readers); `posix` reads what dash and bash read alike. Dynamic words are one word or zero-or-more; a restrictive pattern aligns across them, an `allow` never does. Launchers are classified in one table and unwrapped only in modelled forms (`sh`/`bash`/`dash -c` from POSIX, `cmd /c` from `cmd`, `powershell`/`pwsh -Command` from `cmd` or PowerShell, the script rebuilt from the words the launcher receives); an unwrapped script inherits its wrapper's assignments, redirections and process wrappers. Pin proof needs the starting lookup context. Unicode is validated at model ingress. Contract `prompts/ad-1328-s1-repair-r1.md`.
>>>>>>> REPLACE

---

## Tests (Builders, tests only; never edit `src/`, `tests/fixtures/` or the prompts)

Rules as in the S1 contract (explicit dialects; `model_validate` from dicts; premise and accepted-neighbour controls; reason substrings). Two new rules: (1) every new refusal row asserts **both** the reason substring and, under the deny-list `forbid ["curl"]` with `unmatched_decision="allow"`, an evaluation decision of `escalate` (never `allow`); (2) a test that pins a reading the oracle covers cites the row id in a comment.

### Existing tests that change (by name, with why; do not weaken anything else)

`tests/test_ad1328_s1_command_parse.py`

| Test | Change | Why |
|---|---|---|
| `test_cmd_quoting` | Drop the four caret rows (`caret_escaped_ampersand_stays_one_segment`, the `x^&y` row, `caret_escapes_a_caret`, `caret_newline_continues_the_line`); add `echo "a&b"` -> `[("echo", "a&b")]` and `echo a"b c"d` -> `[("echo", "ab cd")]` | `^` and newline refused in cmd (F3, F11); the refusals move to `test_finding_refusals` |
| `test_powershell_quoting` | Replace the first row with `git commit -m 'it''s fine' 'a b' "c d"` -> `("git", "commit", "-m", "it's fine", "a b", "c d")`; drop `backtick_newline_continues_the_line` | `it's` without a blank, `a"b` and backtick-newline are refused (F3, F11) |
| `test_powershell_backtick_neighbours_stay_literal` | Drop `"`, `'` and `%` from the plain list and assert instead that `` echo a`"b ``, `` echo a`'b ``, `` echo a`%b `` are line-unparseable ("double quote", "single quote", "batch-file"); turn the two backtick-newline assertions into line refusals ("continuation") | F3, F11 |
| `test_powershell_expanding_backtick_escape_in_a_wrapped_script` | Drop the two `posix` outer rows; keep the `cmd` row | POSIX -> PowerShell is cross-family and refused (F9 row `f9_posix_pwsh`) |
| `test_compound_split` | POSIX row `a; b && c || d | e & g` + newline + `h` -> programs `a b c d e g h`; PowerShell row `a; b | c` + newline + `d` -> `a b c d`; the in-quote check uses `echo 'a; b'` for PowerShell (`&`/`|` are refused in a value); the newline-continuation assertions run for POSIX (`&&`, `||`, `|`) and PowerShell (`|` only); cmd `a &&` + newline + `b` is line-unparseable ("newline") | F8, F11 |
| `test_posix_substitution_segments` | `` echo $(curl x | sh) `id` `` -> `echo $(curl x | sh) $(id)` (same programs and dynamics); `` echo "`b`" `` -> `echo "$(b)"`; the single-quoted literal control is unchanged | backticks refused (R1) |
| `test_dynamic_words` | Drop the cmd `%` rows (`cmd_percent`, `cmd_percent_inside_quotes`, `cmd_quoted_percent_literal`, `cmd_lone_percent`); add cmd `echo *.py` -> `(False, True)`; also assert `variadic` per `test_dynamic_word_arity` | `%` refused (F2, F4) |
| `test_unparseable_line` | `posix_backtick` neighbour -> `echo $(a)`; `posix_dangling_pipe_and` -> command `a |&`, reason `"|&"`, neighbour `a | b`; `posix_lone_cr` neighbour -> `echo a` + LF + `b`; `cmd_trailing_caret` -> reason `"'^'"`, neighbour `echo a`; `ps_stop_parsing` neighbour -> `git -x x`; `cmd_parenthesised_block` reason -> `"outside quotes"`; `ps_smart_quote_inside_a_string` reason -> `"non-ASCII"` | each old neighbour is now refused; two reasons are now the closed grammar's |
| `test_unparseable_segment` | `cmd_dynamic_program_with_a_path` (`%X%\git push`) moves to `test_finding_refusals` (line, "percent"); `ps_empty_program` (`'' x`) moves there too (line, "empty argument", neighbour `x 'y'`) | refusals now at line level |
| `test_process_wrappers_that_wrap_nothing_stay_ordinary_programs` | Rows `powershell_timeout_is_a_program` and `cmd_timeout_is_a_program` become segment refusals ("process wrapper"); keep `command -v git` | F9 |
| `test_shell_wrappers_unwrapped` | `cmd /C "git status"` -> `cmd /C git status`; POSIX `powershell -c git status` moves to refusals; assert `lookup_changed` contains "login shell" for `bash -lc` and is None for the `pwsh -NoProfile` row | F6, F9, R4 |
| `test_shell_wrappers_refused_forms_are_one_unparseable_segment` | `pwsh -EncodedCommand AAA` and `pwsh -File x.ps1` rows switch to dialect `cmd` with neighbour cmd `pwsh -NoProfile -Command AAA`; `cmd %X% x` -> `cmd /s /c x` (neighbour `cmd /c x`) | cross-family; `%` refused |
| `test_canonical_wrapper_variants_share_one_key` | POSIX variants `git status`, `bash -c 'git status'`, `/bin/bash -c "git status"`, `sh -c 'git  status'`; cmd variants `git status`, `cmd /c git status`, `cmd /C git status`, `pwsh -NoProfile -Command "git status"`; add: `bash -lc 'git status'` and cmd `pwsh -Command "git status"` are kind `script` | R4, R5 |
| `test_canonical_command_unwraps_at_most_max_nesting` | Rewrite: for levels <= `max_nesting` the key is `argv` `("git", "status")`; at `max_nesting + 1` it is `("script", "posix", (<the exact original text>,))` | A2 retired (R5) |
| `test_canonical_script_fallback` | `parts` are the exact original text: `bash -lc 'ls && pwd'` -> `("script", "posix", ("bash -lc 'ls && pwd'",))`, and `/bin/bash -c 'ls && pwd'` now has a different key; the other rows are unchanged | D6 amended |
| `test_canonical_key_known_answer` | Script expectation bytes `b'["script","posix",["bash -lc \'ls && pwd\'"]]'` (compute with `canonicalize`, as now) | D6 amended |

`tests/test_ad1328_s1_policy_evaluation.py`

| Test | Change | Why |
|---|---|---|
| `test_one_forbidden_segment_forbids_the_command` | Control per dialect: PowerShell uses `git status; git log` | `&&` refused in PowerShell (F8) |
| `test_powershell_escaped_program_is_not_unmatched` | Drop the `pwsh_wrapper_from_posix` row | cross-family (F9) |
| `test_windows_program_names_are_case_insensitive` (its POSIX part) | POSIX `CURL x` under `forbid ["curl"]` is now `forbid`; add the control that `allow ["curl"]` with `unmatched="escalate"` leaves POSIX `CURL x` `escalate` (`unmatched`) | restrictive folding in every dialect (R3); allow stays exact |
| `test_self_test_runs_under_the_dialect_given` | Rule `["echo", "a\\b"]` with match example `echo a\b`: passes under `cmd`, fails under `posix` (`\b` is `b`); same assertions otherwise | `^` refused in cmd |
| `test_the_policy_module_is_pure` | Add `"unicodedata"` to `_PURE_IMPORTS` | R5 |

`tests/test_ad1328_s1_policy_models.py`: no existing test changes.

### R-M1 `tests/test_ad1328_s1_policy_models.py` (add)

1. `test_lone_surrogates_are_refused_at_ingress[justification, alternative, pattern_program, pattern_word, pattern_alternative, pin, match, not_match]`: each field holding `"\ud800"` (inside otherwise valid text) is a `ValidationError` containing `not valid Unicode` and the rule name. Controls: the same fields holding `é` or `日本` are accepted, and `policy_digest` of that config returns 64 hex characters. Kills R8.

### R-M2 `tests/test_ad1328_s1_command_parse.py` (add)

1. `test_finding_refusals[...]`: one row per line below, `(id, dialect, command, scope, reason substring, accepted neighbour)`. `line`: `segments == ()`, reason in `unparseable`; `segment`: the line parses and the one segment (or the named one) has the reason. The neighbour parses with every segment readable. Plus the deny-list evaluation rule above.

| id | dialect | command | scope | reason | neighbour |
|---|---|---|---|---|---|
| f3_cmd_caret | cmd | `echo a^ b` | line | `'^'` | `echo "a b"` |
| f3_cmd_backslash_quote | cmd | `echo a\"b"` | line | `backslash before a double quote` | `echo "a\b"` |
| f3_cmd_backslash_closing | cmd | `echo "a\"` | line | `backslash before a double quote` | `echo "a\ "` |
| f3_cmd_doubled_quote | cmd | `echo "a""b"` | line | `""` | `echo "a" "b"` |
| f3_cmd_single_quote | cmd | `echo 'a b'` | line | `outside quotes` | `echo "a b"` |
| f3_ps_empty | powershell | `echo ''` | line | `empty argument` | `echo 'x'` |
| f3_ps_empty_program | powershell | `'' x` | line | `empty argument` | `x 'y'` |
| f3_ps_embedded_quote | powershell | `echo 'a"b'` | line | `double quote inside an argument` | `echo 'a b'` |
| f3_ps_quote_no_blank | powershell | `echo 'it''s'` | line | `single quote in an argument without a blank` | `echo 'it''s ok'` |
| f3_ps_trailing_backslash | powershell | `echo 'a b\'` | line | `PowerShell quotes for a program` | `echo 'a\b'` |
| f3_ps_batch_metacharacter | powershell | `echo 'a&b'` | line | `batch-file` | `echo 'a+b'` |
| f3_ps_hex | powershell | `echo 0x10` | line | `number` | `echo 16` |
| f3_ps_leading_zero | powershell | `echo 007` | line | `number` | `echo 7` |
| f3_ps_suffix | powershell | `echo 1kb` | line | `number` | `echo '1kb'` |
| f3_cmd_trailing_blank_program | cmd | `"git " status` | segment | `blank or a dot` | `"git" status` |
| f3_cmd_trailing_dot_program | cmd | `git. status` | segment | `blank or a dot` | `git status` |
| f3_cmd_short_name | cmd | `GIT~1.EXE status` | segment | `cmd.exe may split` | `GIT.EXE status` |
| f3_ps_trailing_blank_program | powershell | `& 'git ' status` | segment | `blank or a dot` | `& 'git' status` |
| f3_cmd_slash_program | cmd | `C:/Git/cmd/git.exe status` | segment | `cmd.exe may split` | `C:\Git\cmd\git.exe status` |
| f3_cmd_internal_echo | cmd | `echo.exe x` | segment | `internal command` | `echo x` |
| f3_cmd_internal_cd | cmd | `cd\x` | segment | `internal command` | `cd x` |
| f4_ps_splat_question | powershell | `git push @? --force` | line | `'@' form` | `git push @args --force` |
| f4_ps_splat_dollar | powershell | `git push @$ x` | line | `'@' form` | `git push @args x` |
| f4_ps_splat_caret | powershell | `git push @^ x` | line | `'@' form` | `git push @args x` |
| f4_ps_bare_dollar | powershell | `echo $ x` | line | `'$' the policy does not model` | `echo '$' x` |
| f4_ps_unicode_variable | powershell | `echo $é` | line | `non-ASCII` | `echo $e` |
| f4_ps_member | powershell | `echo $a.b` | line | `member access` | `echo "$a.b"` |
| f4_cmd_caret_percent | cmd | `echo ^%X^%` | line | `'^'` | `echo X` |
| f4_cmd_percent_substitution | cmd | `echo %X: =%` | line | `percent` | `echo X` |
| f4_cmd_percent_quoted | cmd | `echo "%X%"` | line | `percent` | `echo "X"` |
| f4_cmd_percent_program | cmd | `%X%\git push` | line | `percent` | `x\git push` |
| f4_cmd_delayed | cmd | `echo !X!` | line | `delayed expansion` | `echo X` |
| f4_posix_bare_dollar | posix | `echo $` | line | `'$' the policy does not model` | `echo '$'` |
| f4_posix_unicode_variable | posix | `echo $é` | line | `'$' the policy does not model` | `echo $e` |
| f4_posix_default_value | posix | `echo ${X:-a}` | line | `${...}` | `echo ${X}` |
| f4_posix_old_arithmetic | posix | `echo $[1]` | line | `'$' the policy does not model` | `echo $1` |
| f5_command_dashdash | posix | `command -- git push --force` | segment | `options the policy does not read` | `command git push --force` |
| f5_command_pv | posix | `command -pv git` | segment | `options the policy does not read` | `command -v git` |
| f5_nice_repeated | posix | `nice -n 5 -n 3 git push --force` | segment | `options the policy does not read` | `nice -n 5 git push --force` |
| f5_stdbuf_terminator | posix | `stdbuf -oL -- git push --force` | segment | `options the policy does not read` | `stdbuf -oL git push --force` |
| f5_stdbuf_separate | posix | `stdbuf -o L git` | segment | `options the policy does not read` | `stdbuf -oL git` |
| f5_stdbuf_long | posix | `stdbuf --output=L git` | segment | `options the policy does not read` | `stdbuf -oL git` |
| f5_timeout_option | posix | `timeout --foreground 5 git` | segment | `options the policy does not read` | `timeout 5 git` |
| f5_nohup_dashdash | posix | `nohup -- git` | segment | `options the policy does not read` | `nohup git` |
| f6_cmd_c_quoted | cmd | `cmd /c "git status"` | segment | `no double quote` | `cmd /c git status` |
| f8_posix_amp_redirect | posix | `git status &> f` | line | `&>` | `git status > f 2>&1` |
| f8_posix_amp_append | posix | `git status &>> f` | line | `&>` | `git status >> f 2>&1` |
| f8_posix_pipe_amp | posix | `a |& b` | line | `|&` | `a 2>&1 | b` |
| f8_posix_multi_digit | posix | `a 10>f` | line | `multi-digit` | `a 1>f` |
| f8_posix_named_descriptor | posix | `a {fd}>f` | line | `{name}` | `a 3>f` |
| f8_posix_clobber | posix | `a >| f` | line | `does not model` | `a > f` |
| f8_posix_duplication_word | posix | `a >&f` | line | `descriptor duplication` | `a >&2` |
| f8_ps_and | powershell | `a && b` | line | `5.1` | `a; b` |
| f8_ps_or | powershell | `a || b` | line | `5.1` | `a; b` |
| f8_ps_glued | powershell | `echo a>b` | line | `written against a word` | `echo a > b` |
| f8_ps_bad_stream | powershell | `echo x 7>f` | line | `written against a word` | `echo x 2>f` |
| f8_ps_merge_one | powershell | `echo x 1>&1` | line | `stream redirection` | `echo x 2>&1` |
| f8_cmd_multi_digit | cmd | `echo a 12>f` | line | `written against a word` | `echo a 2>f` |
| f8_cmd_glued | cmd | `echo a2>f` | line | `written against a word` | `echo a 2>f` |
| f8_cmd_duplication_word | cmd | `echo a >&x` | line | `descriptor duplication` | `echo a >&2` |
| f9_ps_return | powershell | `return git push --force` | segment | `syntax the policy does not read` | `git push --force` |
| f9_ps_throw | powershell | `throw git` | segment | `syntax the policy does not read` | `git` |
| f9_ps_exit | powershell | `exit git` | segment | `syntax the policy does not read` | `git` |
| f9_cmd_env_exe | cmd | `env.exe git push --force` | segment | `runs a command the policy cannot see` | `git push --force` |
| f9_ps_nice | powershell | `nice git` | segment | `process wrapper` | `git` |
| f9_cmd_timeout | cmd | `timeout 30 git` | segment | `process wrapper` | `git` |
| f9_posix_bash_exe | posix | `bash.exe -c 'git status'` | segment | `runs commands the policy cannot see` | `bash -c 'git status'` |
| f9_posix_upper_bash | posix | `BASH -c 'git status'` | segment | `runs commands the policy cannot see` | `bash -c 'git status'` |
| f9_posix_zsh | posix | `zsh -c 'git status'` | segment | `runs a command the policy cannot see` | `sh -c 'git status'` |
| f9_posix_fish | posix | `fish -c 'git status'` | segment | `runs a command the policy cannot see` | `sh -c 'git status'` |
| f9_posix_csh | posix | `csh -c 'git status'` | segment | `runs a command the policy cannot see` | `sh -c 'git status'` |
| f9_posix_tcsh | posix | `tcsh -c 'git status'` | segment | `runs a command the policy cannot see` | `sh -c 'git status'` |
| f9_posix_busybox | posix | `busybox sh -c 'git status'` | segment | `runs a command the policy cannot see` | `sh -c 'git status'` |
| f9_posix_ssh | posix | `ssh host git push` | segment | `runs a command the policy cannot see` | `git push` |
| f9_posix_wsl | posix | `wsl git status` | segment | `runs a command the policy cannot see` | `git status` |
| f9_posix_npx | posix | `npx cowsay hi` | segment | `runs a command the policy cannot see` | `npm install` |
| f9_posix_uvx | posix | `uvx ruff check` | segment | `runs a command the policy cannot see` | `ruff check` |
| f9_posix_uv_run | posix | `uv run pytest` | segment | `runs a program the policy cannot see` | `uv pip install ruff` |
| f9_posix_uv_option_run | posix | `uv -q run pytest` | segment | `runs a program the policy cannot see` | `uv -q sync` |
| f9_posix_poetry_run | posix | `poetry run pytest` | segment | `runs a program the policy cannot see` | `poetry install` |
| f9_posix_docker_run | posix | `docker run img x` | segment | `runs a program the policy cannot see` | `docker ps` |
| f9_posix_subcommand_dynamic | posix | `uv $SUB pytest` | segment | `runs a program the policy cannot see` | `uv sync` |
| f9_cmd_bash | cmd | `bash -c "git status"` | segment | `starts a POSIX shell` | `git status` |
| f9_ps_bash | powershell | `bash -c 'git status'` | segment | `starts a POSIX shell` | `git status` |
| f9_posix_pwsh | posix | `pwsh -NoProfile -Command 'git status'` | segment | `starts PowerShell from a POSIX shell` | `git status` |
| f9_posix_cmd | posix | `cmd /c git status` | segment | `starts cmd.exe` | `git status` |
| f9_ps_cmd | powershell | `cmd /c git status` | segment | `starts cmd.exe` | `git status` |
| f9_posix_alias | posix | `alias git=curl` | segment | `runs a command the policy cannot see` | `git status` |
| f9_ps_provider_alias | powershell | `Set-Item alias:git curl` | line | `alias:` | `Set-Item x curl` |
| f9_ps_provider_env | powershell | `Remove-Item env:PATH` | line | `env:` | `Remove-Item x` |
| f10_ps_expression | powershell | `"C:/Program Files/Git/cmd/git.exe" status` | segment | `expression, not a command` | `& "C:/Program Files/Git/cmd/git.exe" status` |
| f10_ps_expression_single | powershell | `'git' status` | segment | `expression, not a command` | `& 'git' status` |
| f11_cmd_newline | cmd | `git status` + LF + `x` | line | `newline` | `git status & x` |
| f11_ps_continuation | powershell | `` echo a` `` + LF + `b` | line | `continuation` | `` echo a` b `` |
| f11_posix_crlf | posix | `echo a` + CR LF + `b` | line | `carriage return` | `echo a` + LF + `b` |
| f11_ps_crlf | powershell | `git status` + CR LF + `ls` | line | `carriage return` | `git status` + LF + `ls` |
| f11_ps_quoted_newline | powershell | `echo 'a` + LF + `b'` | line | `newline inside a quoted string` | `echo 'a b'` |
| f12_posix_surrogate | posix | `echo ` + U+D800 | line | `lone surrogate` | `echo x` |
| f12_cmd_surrogate | cmd | `echo ` + U+D800 | line | `lone surrogate` | `echo x` |
| f12_ps_surrogate | powershell | `echo ` + U+D800 | line | `lone surrogate` | `echo x` |
| r1_posix_bidi | posix | `echo a` + U+202E + `b` | line | `formatting character` | `echo ab` |
| r1_posix_nbsp | posix | `git` + U+00A0 + `push` | line | `unusual space` | `git push` |
| r1_cmd_comma | cmd | `git push,--force` | line | `outside quotes` | `git push --force` |
| r1_ps_dashdash | powershell | `git checkout -- x` | line | `the -- or --%` | `git checkout x` |
| r1_ps_digit_program | powershell | `7z x a.zip` | line | `number` | `x7z x a.zip` |
| r1_ps_dash_program | powershell | `-x y` | segment | `expression or an operator` | `x y` |
| r1_ps_call_glued | powershell | `&git status` | line | `not followed by a blank` | `& git status` |
| r1_posix_backtick | posix | `` echo `id` `` | line | `backtick` | `echo $(id)` |

2. `test_dynamic_word_arity[posix, cmd, powershell]`: the first segment's `(dynamic, variadic)` per word:
   - posix `echo $X "$X" ${X} "${X}" "$@" $(a) "$(a)" *.py ~ a=~ b:~ {a,b} a~b '$X'` -> dynamic `(F,T,T,T,T,T,T,T,T,T,T,T,T,F,F)`, variadic `(F,T,F,T,F,T,T,F,T,F,F,F,T,F,F)`.
   - cmd `echo *.py a?b [x] {y} @f ~h a~b a@b "*"` -> dynamic `(F,T,T,T,T,T,T,F,F,T)`, variadic the same.
   - powershell `echo $x "$x" ${x} @a *.py ~ a$1b $env:X '$x' a~b` -> dynamic `(F,T,T,T,T,T,T,T,T,F,F)`, variadic the same.
   Kills M38, M39, M40.
3. `test_state_mutators_mark_the_lookup_context[...]`: every segment's `lookup_changed` contains the named cause: posix `cd sub && git status` (`(cd)`), `export PATH=/tmp/x && git status` (`(export)`), `pushd x; git status`, `hash -p /tmp/git git; git status`, `unset PATH; git status`; cmd `cd sub && git status`, `set PATH=C:\x& git status`, `path C:\x & git status`, `D: & git status`, `pushd x & git status`; powershell `Set-Location sub; git status`, `cd sub; git status`, `D:; git status`, `Push-Location x; git status`. Context sources: posix `bash -lc 'git status'` (`login shell`), `command -p git status` (`default PATH`); cmd `powershell -Command "git status"` (`-NoProfile`). Controls (all `None`): posix `git status && ls`, cmd `git status & dir`, powershell `git status; ls`, cmd `powershell -NoProfile -Command "git status"`. Kills M11, M15-M17, M20, M49.
4. `test_unwrapped_segments_inherit_context`: posix `X=1 sh -c 'git status'` -> inner `assignments == ("X=1",)`, `depth == 1`, `tokens == ("git", "status")`; `nice sh -c 'git status'` -> `wrappers == ("nice",)`; `sh -c 'git status' > out` -> `redirections == (">out",)`; `X=1 sh -c 'Y=2 git status'` -> `("X=1", "Y=2")`; `X=1 sh -c 'echo $(git status)'` -> the `git` segment has `("X=1",)`; cmd `cmd /c git status > out` -> inner `(">out",)`. Control: `X=1 echo $(git status)` -> the `git` segment has `()`. Kills M12-M14.
5. `test_wrapped_scripts_are_rebuilt_from_the_words_the_launcher_receives`: cmd `powershell -NoProfile -Command git "push --force"` and cmd `powershell -NoProfile -Command "git push" --force` -> one inner segment `("git", "push", "--force")`, dialect `powershell`; powershell `pwsh -NoProfile -Command git 'push --force'` -> the same; cmd `cmd /c git push --force` -> `("git", "push", "--force")`, dialect `cmd`. Kills M18.
6. `test_canonical_identity_follows_what_runs`: script keys (with `parts == (original,)`) for posix `X=1 sh -c 'git status'`, `nice sh -c 'git status'`, `sh -c 'git status' > out`, `bash -lc 'git status'`, `cd x`; cmd `pwsh -Command "git status"`, `dir src`; powershell `"C:/x/git.exe" status`. Argv keys: posix `bash -c 'git status'` equals `git status`; cmd `pwsh -NoProfile -Command "git status"` equals cmd `git status`; powershell `& "C:/x/git.exe" status` is `argv` and differs from `"C:/x/git.exe" status`; cmd `git "a b"` differs from `git a b`, and cmd `git "a" b` equals `git a b`. Malformed: posix `"git \ud800"` -> kind `script`, dialect `posix`, `parts == ("probos.command_policy/malformed-utf16le-hex", "git \ud800".encode("utf-16-le", "surrogatepass").hex())`, `.key` is 64 hex characters and differs from that of `"git \udc00"`. Kills M44-M47.
7. `test_usability_corpus[<dialect>-<n>]`: the R1 corpus (copy the literal): the line parses, every segment's `unparseable is None`, tokens equal; under the deny-list the decision is `allow`. `cd src && ls`, `cd src && dir` and `Set-Location src; Get-ChildItem` additionally have `lookup_changed` set.

### R-M3 `tests/test_ad1328_s1_policy_evaluation.py` (add)

1. `test_dynamic_words_align_with_restrictive_patterns`: forbid `["git", "push", "--force"]`, `unmatched="allow"`: posix `git $W`, `git $W --force`, `git push $F`, `git "$W" --force`, `git "$A" "$B"`, powershell `git @a`, `git $x`, cmd `git push *` -> `forbid`; posix `git "$W"` and `git status $W` -> `allow`. `matched_prefix` of `git $W` is `("git", "")`. Allow `["git", "push"]`, `unmatched="escalate"`: posix `git $W`, `git push$X` -> `escalate` (`unmatched`); `git push $X`, `git push "$X"` -> `allow`. Kills M02-M04.
2. `test_pin_proof_needs_the_starting_lookup_context`: allow `["git"]` pinned `/usr/bin/git`, resolver `{"git": "/usr/bin/git"}.get`, `unmatched="escalate"`: posix `git status` -> `allow` (control); in `cd sub && git status`, `export PATH=/tmp/x && git status`, `command -p git status` and `bash -lc 'git status'` the git segment's match is `forbid` with `pin_violation`, and its justification contains `not proven` and the cause (`changes the working directory`, `default PATH`, `login shell`); `cd sub && /usr/bin/git status` -> the git segment `allow`; `bash -c 'git status'` -> `allow`. cmd, pin `C:\Program Files\Git\cmd\git.exe`, resolver to it: `powershell -Command "git status"` -> the git segment `forbid` (`-NoProfile` in the justification); `powershell -NoProfile -Command "git status"` -> `allow`; `cd x & git status` -> the git segment `forbid`. Kills M08, M11, M15-M17, M49.
3. `test_inherited_assignments_block_an_allow_match`: allow `["git", "status"]`, `unmatched="escalate"`: posix `X=1 sh -c 'git status'` -> `escalate` (`unmatched`); `sh -c 'git status'` -> `allow`. Forbid `["git", "push", "--force"]`: `X=1 sh -c 'git push --force'` -> `forbid`. Kills M12.
4. `test_a_powershell_string_is_not_an_invocation`: escalate `["git"]`, `unmatched="allow"`: powershell `"C:/x/git.exe" status` -> `escalate`, basis `unparseable`, `matched_rules == ()`; `& "C:/x/git.exe" status` -> basis `rule`. Kills M21.
5. `test_wrapper_option_forms_never_reach_allow`: forbid `["git", "push", "--force"]`, `unmatched="allow"`: posix `command -p git push --force` -> `forbid`; `command -- git push --force`, `nice -n 5 -n 3 git push --force`, `stdbuf -oL -- git push --force` -> `escalate` (`unparseable`). Kills M48, M49.
6. `test_transport_follows_what_the_launcher_receives`: forbid `["git", "push", "--force"]`, `unmatched="allow"`: cmd `powershell -NoProfile -Command git "push --force"` -> `forbid`. Kills M18.
7. `test_restrictive_rules_fold_the_program_spelling_in_every_dialect`: forbid `["curl"]`: posix `CURL x`, `curl.exe x`, `/usr/bin/CURL x` -> `forbid`; allow `["curl"]`, `unmatched="escalate"`: posix `CURL x` -> `escalate`. Kills M06, M07.
8. `test_malformed_text_is_judged_not_raised`: `evaluate_command(cfg, "git \ud800", dialect=d)` for each dialect -> `evaluated`, decision `escalate`, `unparseable` contains `lone surrogate`; `CommandPolicy(cfg, dialect="posix").canonical("git \ud800").key` returns. Kills M41, M44.

### R-M4 `tests/test_ad1328_s1_shell_oracle.py` (new)

Load `tests/fixtures/ad1328_shell_oracle.json` (path from `__file__`, read with `encoding="utf-8"`: row P21 is non-ASCII). Helpers (local): `_prefix(dialect, python, probe)` per R6; `_substitute(text, dialect, python, probe)` replacing `{P}` and `{B}` with `str.replace`; `_probe_segments(parsed, python)` = the segments whose `tokens[0]` has `windows_program_stem` equal to that of `python` and whose `tokens[1]` ends with `probe.py` (synthetic) or `ad1328_argv_probe.py` (live), in segment order; `_admits(words, marks, argv)` = a memoised alignment (literal equal, `o` exactly one, `v` zero or more) returning bool.

1. `test_oracle_file_shape`: schema; ids unique; every row's `dialect` known, `constructs` a subset of that dialect's list; every construct id in some row; `marks` strings match the `policy` lengths; `live` maps only to that dialect's shells.
2. `test_admission_helper`: `_admits(["a", None], "lv", ["a", "x", "y"])` true; `"lo"` false; a literal mismatch false; `"v"` admits `[]`.
3. `test_policy_reads_each_row_as_recorded[row]` (every host): synthetic prefixes (R6); the line parses (`unparseable is None`); the probe segments are all readable, their count equals `len(policy)`, and per segment the words after the prefix are `len(row)` long, literal ones equal, and `(dynamic, variadic)` per mark (`l` -> `(False, False)`, `o` -> `(True, False)`, `v` -> `(True, True)`).
4. `test_live_shell_agrees[row-shell]`: shells per dialect (R6), skipped with a reason when the shell, a `requires` program or (for `{B}` rows) a bare-safe path is missing; POSIX shells are skipped on Windows. In `tmp_path`: create `files`; env = `os.environ` + row `env` + `AD1328_PROBE_LOG` + `MSYS_NO_PATHCONV=1` + `MSYS2_ARG_CONV_EXCL=*`; the live text uses `sys.executable` and the real probe path (POSIX on Windows is skipped, so no slash conversion is needed); first assert the policy reads the live text as in #3; run with `timeout=60`, `cwd=tmp_path`, `capture_output=True`. Read the log: the number of lines equals `runs` (default the probe-segment count); each argv is admitted by a distinct probe segment; with `live`, `sorted(observed) == sorted(expected)` (the per-shell list when `live` is a map). On failure, print the observed argv lists. Never edits the fixture.

Mark nothing `slow`; each run is one short process.

## What This Does NOT Change

- No call site, config field, re-export, approval, record, event, store, API or `doctor` change (S2a's).
- The public API (`parse_command`, `evaluate_command(config, command, *, dialect, resolve_program)`, `CommandPolicy`, `self_test`, `canonical_command`, `policy_digest`, `default_dialect`, `CommandEvaluation`, `RuleMatch`, `SegmentVerdict`, `SelfTestReport`, `SelfTestFailure`, `CanonicalCommand`, `CommandPolicySelfTestError`, `CommandSegment`, `ParsedCommand`, the two models, the schemes) keeps every name, parameter and field; `CommandSegment` gains `variadic` and `lookup_changed` with defaults.
- The digest and key schemes stay `v1` (nothing has been persisted or released: S1 is unwired and unpushed).
- `ExecutionConfig` and every other model in `operations.py` are byte-identical apart from Section 1.

## Do Not Build

Native argument marshalling per callee; a POSIX dialect for Windows (MSYS/WSL); Codex-style tree-sitter; per-program option parsers (`git -C`, `find -exec`); a safe-variable list; any change to `max_*` bounds; S2 wiring.

## S2a amendments required (`prompts/ad-1328-s2a-command-policy-wiring.md`)

| S2a item | Amendment |
|---|---|
| M1 #2 `test_gate_self_tests_every_serving_dialect` (`:1246`) | Example `echo a^&b` is now unparseable under `cmd` too; use rule `["echo", "a&b"]` with match example `echo "a&b"` (holds under `cmd`; PowerShell refuses `&` in a value). |
| M1 #10 (`:1254`) | Run under a `posix` or `powershell` gate: `cmd` refuses an unquoted `;`. |
| Verified Against Codebase cites of S1 lines (`command_policy.py:1208-1254`, `:207-233`) | Re-grep after install; the module is replaced. |
| D7 causes | Optional: an unparseable or pin-violation cause may quote `CommandSegment.lookup_changed`; the justification already carries it. |
| O-S1-12 | Confirm in the S2a obligations list (already true of `serving_dialects`). |

The starter policy (`:1177-1193`) and M2 #5/#6 (`:1287-1288`) hold under the new grammar (checked: `curl -sS example.com`, `Invoke-WebRequest example.com`, `git push origin main`, `& "<sys.executable>" -c "print(1)"`, `powershell -Sta -Command "git status"`).

## Tracking

`DECISIONS.md` (Section 5). No `PROGRESS.md` or roadmap change (S1's entry stands; closure is S2's O-S2a-8). Regenerate the AD ledger (`scripts/gen_ad_ledger.py`, then `--check`).

## Acceptance Criteria

1. Sections 1-5 install mechanically: Section 2 replaces the file; each Section 1 and 5 SEARCH occurs exactly once.
2. Every row of `test_finding_refusals` refuses with its reason and escalates under the deny-list, and its neighbour is readable (F3-F12).
3. Mutators, login shells, PowerShell profiles and `command -p` withhold pin proof (F1); inherited context blocks `allow` and changes keys (F7); dynamic words align (F2); a PowerShell string is not an invocation (F10).
4. The usability corpus parses and evaluates to `allow` under the deny-list in all three dialects.
5. The oracle: shape and policy rows pass on every host; the live rows pass on this host for cmd, Windows PowerShell 5.1 and pwsh, and in CI for dash, bash and pwsh. A live failure is a hard stop to the Architect.
6. Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s1_policy_models.py tests/test_ad1328_s1_command_parse.py tests/test_ad1328_s1_policy_evaluation.py tests/test_ad1328_s1_shell_oracle.py -q -n 0`; then the S1 neighbour list and five `--check` scripts of S1 acceptance 8.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Hidden Pins (enumerated)

| Pin | Evidence | Effect |
|---|---|---|
| Purity scan import set | `tests/test_ad1328_s1_policy_evaluation.py:947` `_PURE_IMPORTS` | Changes (adds `unicodedata`); listed above. |
| Unwired scan | same file `:866` | Unaffected: no new import of the module under `src/`. |
| `operations.py` imports nothing from `probos` | `tests/test_ad1270e2e_operations_models.py:572-582` | Section 1 adds no import. |
| Architecture fitness (500 body lines, 15 methods per class) | `scripts/check_architecture_principles.py:187-188` | Largest class `_PosixLexer` about 170 lines, 10 methods; `_PowerShellLexer` 11 methods. |
| CI shards weigh an unknown test file at the mean | `tests/test_ci_shards.py:498` | The new oracle file needs no duration row. |
| `tests/fixtures/` holders | `tests/test_ci_shards.py:31` (only `file_durations.json` is read by name) | New fixtures are not scanned. |
| BF-892 launch guard scans `src/` only | `tests/test_bf892_spawn_env_guard.py:53-54` | The oracle test's `subprocess.run` is under `tests/`. |
| CI runner | `.github/workflows/ci.yml:17` `ubuntu-latest` | POSIX live rows run there. |
| AD ledger | `scripts/gen_ad_ledger.py` reads `DECISIONS.md` headings | Section 5 adds no heading; regenerate and `--check`. |

## Verified Against Codebase (2026-10-16, base `26250c9c`, HEAD `8c9e9553`, staged S1)

```
git rev-parse HEAD                                    -> 8c9e95531e9dc9e628e75681fe0f579b4763c053
git ls-files -s (staged)                              -> command_policy.py 28f39d09e68e..., operations.py 27b380b78e51...
git diff --stat                                       -> (empty: working tree == index)
scripts/ad_ceiling.py                                 -> CEILING AD-1341 (issue titles); NEXT AD-1342
CP:367-374    _Lexer._escape: escape + newline continues the line
CP:416, :429-435  POSIX '&>' to _redirection; _separator reads '|&'
CP:539-576    _CmdLexer: '^' escapes; quoted runs; '%' via _percent (:578-587)
CP:593-600, :84   PS _escape/_refuse_expanding_escape; _PS_EXPANDING_ESCAPES = "0abefnrtuv" (A1, kept)
CP:630-640, :725-736  PS '>' with descriptor; '||'; '&&' and the call operator
CP:646-685    PS quoted strings ("" and ``" inside values)
CP:687-723    PS _variable ($1, Unicode fall to literal), _splat ('@?' literal)
CP:780-786    _checked_text: text.replace("\r\n", "\n")
CP:811-850    _segment: call operator discarded (:821-824)
CP:853-893    _strip_process_wrappers / _wrapper_width
CP:908-941    _shell_wrapper; _rest_of_line joins raw spellings
CP:1004-1021  _unwrap: no context passed to the script's segments
CP:1059-1110  _match (len(tokens) < len(pattern); one position per dynamic word), _allow_match
CP:1262-1276  _canonical_json / policy_digest
CP:1279-1329  _is_simple, canonical_command loop (A2)
OM:49-57      windows_program_stem
OM:60-70      _has_control_character, _check_policy_text
OM:73-93      _check_pattern (position-0 '/\\ \t' check at :89)
OM:96-115     _check_pins (absolute/length/control check at :112)
src/probos/agents/shell_command.py:217-228  _rewrite_python_interpreter emits '& "<sys.executable>"' on win32
tests/test_ad1328_s1_command_parse.py: test names at :107-:1144 (listed in "Existing tests that change")
tests/test_ad1328_s1_policy_evaluation.py:947, :961  _PURE_IMPORTS, _LAZY_IMPORTS
tests/test_ad1328_s1_policy_evaluation.py:616-634  test_self_test_runs_under_the_dialect_given (echo a^&b)
prompts/ad-1328-s2a-command-policy-wiring.md:1246, :1254, :1177-1193, :1198-1199, :1287-1288
DECISIONS.md:20 (D6 line, Section 5 SEARCH), :22 (the contract line S2a's Section 15 SEARCHes; untouched)
docs/research/reference-projects.md:29-30  Codex 2026-10-14, Claude Code 2026-10-16 (not overdue)
.github/workflows/ci.yml:17   runs-on: ubuntu-latest
```

## Absence Verified (2026-10-16)

```
A1 CLAIM: nothing under src/ imports the module or uses _rest_of_line/_shell_wrapper
   RUN:   Grep "command_policy|_rest_of_line|_shell_wrapper" src/
   FOUND: src/probos/execution/command_policy.py, src/probos/config_models/operations.py (comment) only
   HOLDS: yes
A2 CLAIM: no test imports a private name from the module
   RUN:   Grep "command_policy\._|_PS_EXPANDING_ESCAPES|_OPAQUE_PROGRAMS|_PROCESS_WRAPPERS" tests/
   FOUND: tests/test_ad1328_s1_command_parse.py:723 REFUSED_PROCESS_WRAPPERS (a local list), nothing imported
   HOLDS: yes
A3 CLAIM: no test reads every file of tests/fixtures
   RUN:   Grep "fixtures" tests/test_ci_shards.py; Grep 'fixtures"\)|fixtures/\*' tests/
   FOUND: only named files (file_durations.json, duration_scheduler); other hits are per-test fixture paths
   HOLDS: yes
```

Not verified (stated, not assumed): every reference-shell expectation in Section 4 (the bridge denied running dash; the install-step live run is the evidence); Windows PowerShell 5.1's treatment of `--`, `-x:y` and number-like barewords for native programs (the first and third are refused, so only `-x:y` in S05 is a live claim); Cygwin's `@file` handling (refusal-direction only); the orchestrator's S1 tree id `40db5331`.

## Prior Art and Blind Spots

- **Internal.** S1's prior-art section (Codex `execpolicy`, Claude Code permission rules, Cline) stands. `docs/research/codex-harness-absorption.md` rows 2-3 remain the absorption decision.
- **Codex `bash.rs`** (`try_parse_word_only_commands_sequence`; seen only through mirrors, e.g. [forge.lthn.ai copy](https://forge.lthn.ai/core/core-agent-ide/raw/commit/b68a84ee8e46d7172308cf8a95a3374262db3f46/codex-rs/shell-command/src/bash.rs), so secondhand): accepts a script only when every tree-sitter node kind is on an allow-list (words, strings, concatenation, `&&`/`||`/`;`/`|`) and rejects anything else. **Adopted** as R1's principle; **adapted** with hand-written per-dialect readers (no parser dependency, S1 Do Not Build) and a live oracle.
- **WorstFit** ([DEVCORE, 2025-01-09](https://devco.re/blog/2025/01/09/worstfit-unveiling-hidden-transformers-in-windows-ansi/); [mingw-w64 fix](https://mingw.googlesource.com/mingw-w64/+/0d42217123d3aec0341b79f6d959c76e09648a1e)): Windows best-fit conversion turns U+FF02 into `"` in an ANSI program's argv. **Adopted:** `cmd` and PowerShell refuse non-ASCII.
- **BatBadBut** (CVE-2024-24576, Flatt Security; [Tenable](https://tenable.com/cve/CVE-2024-24576)): a batch-file callee re-parses its arguments with `cmd.exe` rules, and no escaping is correct in every case. **Adopted:** PowerShell values may not hold `& | < > ^ % !` (npm, yarn, pnpm are `.cmd` files on Windows).
- **Cygwin `build_argv`** ([cygwin list, 2016](https://sourceware.org/ml/cygwin/2016-05/msg00082.html); [2019](https://inbox.sourceware.org/cygwin/5d71ac65.1c69fb81.686f1.8589@mx.google.com/T/)): from a Windows command line, single quotes quote when globbing is on, and parsing differs from Microsoft's. **Adopted:** single quotes refused in `cmd` words outside double quotes and in PowerShell values without a blank; globs variadic.
- **PowerShell native argument passing** ([about_Parsing](https://docs.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_Parsing); [PowerShell#18664](https://github.com/PowerShell/PowerShell/issues/18664); [mklement0/native](https://github.com/mklement0/native)): the binder consumes `--`; `--%` semantics changed across versions. **Adopted:** both refused.
- **Trojan Source** (CVE-2021-42574): bidi controls make displayed text differ from what runs. **Adopted:** POSIX refuses `Cf`.
- **Reference projects** (date used 2026-10-16): Codex (2026-10-14) and Claude Code (2026-10-16) are not overdue; Aider and Goose are overdue but unrelated to shell reading: considered, deferred. No row updated.
- **Blind spots raised.** (1) Case-insensitive file systems (macOS APFS, WSL drvfs) and WSL interop (`curl.exe` on Linux) run another spelling of a forbidden program: restrictive rules now fold in POSIX too. (2) 8.3 short names (`POWERS~1.EXE`) dodge stems: `~` refused in Windows program words. (3) `cmd` reads `echo.`, `cd\`, `dir/w` as an internal command plus an argument, and `/` in an external program word as a switch: refused. (4) PowerShell number parsing in argument mode (`0x10` -> `16`, `1kb` -> `1024`). (5) Login shells and PowerShell profiles change PATH (pyenv, asdf shims): pin proof withheld. (6) `cmd /c "..."` quote stripping depends on whether a file of that name exists, so an agent-created file could change the reading: quotes after `/c` refused. (7) cmd AutoRun (registry) runs in both the outer and an inner `cmd /c`; it is environment the S2 resolver cannot see either (considered, deferred to S2). (8) `BASH_ENV`/`ENV` in the child environment are read by a non-interactive `bash -c`/`sh -c` (considered, deferred: BF-890 owns the child environment).

## Mutation campaign of record (replaces S1's table)

Run once by the orchestrator on the committed tree after R-M1..R-M4 pass. Anchors are single lines that occur exactly once in the named file (as installed); replacements are literal. Record the base commit and the sha256 of both source files; a later candidate whose two files match reuses this campaign; one whose files differ reruns the rows anchored in the changed file.

| Id | File | Anchor | Replacement | Killer |
|---|---|---|---|---|
| M01 | command_policy.py | `return max(decisions, key=COMMAND_DECISION_RANK.__getitem__)` | `return min(decisions, key=COMMAND_DECISION_RANK.__getitem__)` | M3 `test_strictest_wins_with_overlapping_rules` |
| M02 | command_policy.py | `if segment.variadic[at]:` | `if False:` | R-M3 #1 (`git $W`) |
| M03 | command_policy.py | `if not segment.dynamic[at] and tokens[at] not in _options(pattern[done + 1]):` | `if tokens[at] not in _options(pattern[done + 1]):` | R-M3 #1 (`git "$W" --force`) |
| M04 | command_policy.py | `if segment.dynamic[position] or tokens[position] not in _options(rule.pattern[position]):` | `if tokens[position] not in _options(rule.pattern[position]):` | R-M3 #1 (`git push$X`) |
| M05 | command_policy.py | `if len(tokens) < len(rule.pattern) or segment.assignments:` | `if len(tokens) < len(rule.pattern):` | M3 `test_restrictive_rules_see_through_and_allow_rules_need_proof` (`FOO=1 git push`) |
| M06 | command_policy.py | `return posixpath.basename(program) in names` | `return windows_program_stem(program) in names` | R-M3 #7 (allow `CURL x`) |
| M07 | command_policy.py | `if dialect == "posix" and not restrictive:` | `if dialect == "posix":` | R-M3 #7 (forbid `CURL x`) |
| M08 | command_policy.py | `elif segment.lookup_changed is not None:` | `elif False:` | R-M3 #2 |
| M09 | command_policy.py | `if resolved is not None and _path_key(resolved, segment.dialect) in pinned:` | `if resolved is not None:` | M3 `test_pinning_refuses_a_same_basename_executable_outside_the_pins` |
| M10 | command_policy.py | `return None  # a path is another binary than the bare name the rule allows, unless pinned` | `return RuleMatch(rule.name, "allow", rule.justification, None, prefix, index, None, False)` | M3 `test_restrictive_rules_see_through_and_allow_rules_need_proof` (`./git push`) |
| M11 | command_policy.py | `if mutator is None:` | `if True:` | R-M2 #3, R-M3 #2 |
| M12 | command_policy.py | `assignments=context.assignments + segment.assignments,` | `assignments=segment.assignments,` | R-M2 #4, R-M3 #3 |
| M13 | command_policy.py | `wrappers=context.wrappers + segment.wrappers,` | `wrappers=segment.wrappers,` | R-M2 #4, R-M2 #6 |
| M14 | command_policy.py | `redirections=context.redirections + segment.redirections,` | `redirections=segment.redirections,` | R-M2 #4, R-M2 #6 |
| M15 | command_policy.py | `lookup_changed=segment.lookup_changed or context.lookup_changed,` | `lookup_changed=segment.lookup_changed,` | R-M2 #3, R-M3 #2 |
| M16 | command_policy.py | `return args[1], "posix", (_LOGIN_SHELL if _POSIX_SCRIPT_FLAGS[args[0]] else None)` | `return args[1], "posix", None` | R-M2 #3, R-M3 #2 |
| M17 | command_policy.py | `return script, "powershell", (_PS_PROFILE if profile else None)` | `return script, "powershell", None` | R-M2 #3, R-M3 #2 |
| M18 | command_policy.py | `script = " ".join(args[at + 1:])` | `script = args[at + 1] if at + 1 < len(args) else ""` | R-M2 #5, R-M3 #6 |
| M19 | command_policy.py | `if any('"' in raw for raw in segment.raw[at + 2:]):` | `if False:` | R-M2 #1 `f6_cmd_c_quoted` |
| M20 | command_policy.py | `return windows_program_stem(program) in _STATE_MUTATORS[segment.dialect]` | `return False` | R-M2 #3 |
| M21 | command_policy.py | `if word.raw[:1] in ("'", '"'):` | `if False:` | R-M2 #1 `f10_*`, R-M3 #4 |
| M22 | command_policy.py | `if '"' in value:` | `if False:` | R-M2 #1 `f3_ps_embedded_quote` |
| M23 | command_policy.py | `if not value:` | `if False:` | R-M2 #1 `f3_ps_empty` |
| M24 | command_policy.py | `if any(char in _PS_BATCH_METACHARACTERS for char in value):` | `if False:` | R-M2 #1 `f3_ps_batch_metacharacter` |
| M25 | command_policy.py | `if word.raw[:1] not in ("'", '"') and _PS_NUMBER_START.match(value) and _PS_INTEGER.fullmatch(value) is None:` | `if False:` | R-M2 #1 `f3_ps_hex` |
| M26 | command_policy.py | `if value == "--" or value.startswith("--%"):` | `if False:` | R-M2 #1 `r1_ps_dashdash`; M2 `ps_stop_parsing` |
| M27 | command_policy.py | `if "'" in value and " " not in value:` | `if False:` | R-M2 #1 `f3_ps_quote_no_blank` |
| M28 | command_policy.py | `elif ch in _CMD_REFUSED_ANYWHERE:` | `elif False:` | R-M2 #1 `f4_cmd_percent_substitution` |
| M29 | command_policy.py | `if any(char in _CMD_REFUSED_ANYWHERE for char in body):` | `if False:` | R-M2 #1 `f4_cmd_percent_quoted` |
| M30 | command_policy.py | `elif ch in _CMD_REFUSED_UNQUOTED:` | `elif False:` | R-M2 #1 `f3_cmd_caret` |
| M31 | command_policy.py | `if body.endswith("\\"):` | `if False:` | R-M2 #1 `f3_cmd_backslash_closing` |
| M32 | command_policy.py | `elif ch == "\\" and text.startswith('"', self.i + 1):` | `elif False:` | R-M2 #1 `f3_cmd_backslash_quote` |
| M33 | command_policy.py | `if not (len(raw) == 1 and raw.isdigit()):` | `if False:` | R-M2 #1 `f8_cmd_multi_digit` |
| M34 | command_policy.py | `if pair == "&>":` | `if False:` | R-M2 #1 `f8_posix_amp_redirect` |
| M35 | command_policy.py | `if pair == "|&":` | `if False:` | R-M2 #1 `f8_posix_pipe_amp` (reason `|&`; the mutant refuses with "empty command") |
| M36 | command_policy.py | `if len(raw) > 1:` | `if False:` | R-M2 #1 `f8_posix_multi_digit` |
| M37 | command_policy.py | `if op in (">|", "<>"):` | `if False:` | R-M2 #1 `f8_posix_clobber` |
| M38 | command_policy.py | `if ch in _POSIX_EXPANDING:` | `if False:` | R-M2 #2 |
| M39 | command_policy.py | `elif ch == "~" and (self._start < 0 or self._last in ("=", ":")):` | `elif ch == "~" and self._start < 0:` | R-M2 #2 (`a=~`) |
| M40 | command_policy.py | `self._mark_dynamic(variadic=(not quoted) or name == "@")` | `self._mark_dynamic(variadic=False)` | R-M2 #2 (`${X}`) |
| M41 | command_policy.py | `if 0xD800 <= code <= 0xDFFF:` | `if False:` | R-M2 #1 `f12_*` (reason), R-M3 #8 |
| M42 | command_policy.py | `if dialect != "posix":  # a Windows program may read a non-ASCII character as another one` | `if False:` | R-M2 #1 `f4_ps_unicode_variable` |
| M43 | command_policy.py | `if char == "\r":` | `if False:` | R-M2 #1 `f11_posix_crlf` (reason `carriage return`) |
| M44 | command_policy.py | `if not _is_scalar_text(command):` | `if False:` | R-M2 #6, R-M3 #8 |
| M45 | command_policy.py | `and segment.lookup_changed is None` | `and True` | R-M2 #6 (`bash -lc`) |
| M46 | command_policy.py | `and not (segment.dialect == "cmd" and windows_program_stem(segment.tokens[0]) in _CMD_INTERNAL)` | `and True` | R-M2 #6 (`dir src`) |
| M47 | command_policy.py | `if parsed.unparseable is None and len(parsed.segments) == 1 and _is_simple(parsed.segments[0]):` | `if parsed.unparseable is None and len(parsed.segments) == 1:` | R-M2 #6 |
| M48 | command_policy.py | `if not following.dynamic and following.text.startswith("-"):` | `if False:` | R-M2 #1 `f5_*`, R-M3 #5 |
| M49 | command_policy.py | `if first == "-p":` | `if False:` | R-M3 #5 (`command -p ... --force` must forbid), R-M2 #3 |
| M50 | command_policy.py | `if name in _LAUNCHERS[dialect] or name in _OTHER_SHELLS:` | `if False:` | R-M2 #1 `f9_posix_zsh`, `f9_posix_ssh` |
| M51 | command_policy.py | `if name in _KEYWORDS[dialect]:` | `if False:` | R-M2 #1 `f9_ps_return` |
| M52 | command_policy.py | `if name in _PROCESS_WRAPPERS and (dialect != "posix" or posixpath.basename(program) != name):` | `if False:` | R-M2 #1 `f9_ps_nice`, `f9_cmd_timeout` |
| M53 | command_policy.py | `if word.dynamic or word.text in subcommands:` | `if False:` | R-M2 #1 `f9_posix_uv_run` |
| M54 | command_policy.py | `if outer == "posix" and posixpath.basename(head) in _POSIX_SHELLS and readable:` | `if readable:` | R-M2 #1 `f9_posix_bash_exe` |
| M55 | command_policy.py | `return f"{head!r} starts PowerShell from a POSIX shell, which the policy does not read"` | `pass` | R-M2 #1 `f9_posix_pwsh` |
| M56 | command_policy.py | `return f"{head!r} starts cmd.exe from {_DIALECT_NAMES[outer]}, which the policy does not read"` | `pass` | R-M2 #1 `f9_ps_cmd` |
| M57 | command_policy.py | `if raw not in _PS_STREAMS:` | `if False:` | R-M2 #1 `f8_ps_glued` |
| M58 | command_policy.py | `if stream not in _PS_MERGING_STREAMS:` | `if False:` | R-M2 #1 `f8_ps_merge_one` |
| M59 | command_policy.py | `if not following or _IDENT_START.fullmatch(following) is None:` | `if False:` | R-M2 #1 `f4_ps_splat_question` |
| M60 | command_policy.py | `if not quoted and text[end:end + 1] in (".", ":", "["):` | `if False:` | R-M2 #1 `f4_ps_member` |
| M61 | command_policy.py | `if _PS_BARE_PROGRAM.fullmatch(value) is None:` | `if False:` | R-M2 #1 `r1_ps_dash_program` |
| M62 | command_policy.py | `if _CMD_PROGRAM.fullmatch(value) is None:` | `if False:` | R-M2 #1 `f3_cmd_slash_program` |
| M63 | command_policy.py | `if value.endswith((" ", ".")):` | `if False:` | R-M2 #1 `f3_cmd_trailing_blank_program` |
| M64 | command_policy.py | `if head is not None and head.group().lower() in _CMD_INTERNAL and len(head.group()) < len(value) and not value[len(head.group())].isalnum():` | `if False:` | R-M2 #1 `f3_cmd_internal_echo` |
| M65 | command_policy.py | `if text[self.i + 1:self.i + 2] not in (" ", "\t"):` | `if False:` | R-M2 #1 `r1_ps_call_glued` |
| M66 | command_policy.py | `if value.lower().startswith(_PS_PROVIDER_PREFIXES):` | `if False:` | R-M2 #1 `f9_ps_provider_alias` |
| M67 | command_policy.py | `if text.startswith('"', end + 1):` | `if False:` | R-M2 #1 `f3_cmd_doubled_quote` |
| M68 | command_policy.py | `if following in _PS_EXPANDING_ESCAPES:` | `if False:` | M2 `test_powershell_expanding_backtick_escapes`; M3 `test_powershell_escaped_program_is_not_unmatched` |
| M69 | command_policy.py | `_PS_EXPANDING_ESCAPES: Final = frozenset("0abefnrtuv")` | ten sub-rows, each dropping one letter; plus `frozenset("0abefnrtuvN")` | as M68; the widened row is killed by `` `Ngit status `` in M2 |
| M70 | command_policy.py | `if following == "\n":  # PowerShell continues the line, which it reads differently inside a word` | `if False:` | R-M2 #1 `f11_ps_continuation` |
| M71 | command_policy.py | `if char == "\t" or (char == "\n" and dialect != "cmd") or 32 <= code < 127:` | `if char == "\t" or char == "\n" or 32 <= code < 127:` | R-M2 #1 `f11_cmd_newline` |
| M72 | command_policy.py | `if ch == "\n":  # a newline in single quotes` | `if False:` | R-M2 #1 `f11_ps_quoted_newline` |
| M73 | command_policy.py | `if unicodedata.category(char) in _POSIX_REFUSED_CATEGORIES:` | `if False:` | R-M2 #1 `r1_posix_bidi` |
| M74 | command_policy.py | `if pair in (";;", ";&"):` | `if False:` | M2 `test_unparseable_line` (`case`) |
| M75 | command_policy.py | `elif pending is not None:` | `elif False:` | M2 `test_unparseable_line` (`nothing after`) |
| M76 | command_policy.py | `self.subs.append(inner)  # its segments are judged too` | `pass` | M2 `test_posix_substitution_segments`; M3 #4 `posix_substitution` |
| M77 | command_policy.py | `if self.depth >= self.max_nesting:` | `if False:` | M2 `test_bounds` |
| M78 | command_policy.py | `if len(out) > bounds.max_segments:` | `if False:` | M2 `test_bounds` |
| M79 | command_policy.py | `if len(command) > bounds.max_command_chars:` | `if False:` | M2 `test_bounds` |
| M80 | command_policy.py | `if word.dynamic:  # the shell decides the program` | `if False:` | M2 `test_unparseable_segment` (dynamic programs); M3 #5 |
| M81 | command_policy.py | `while words and words[0].assignment:` | `while False:` | M2 `test_leading_assignments_posix`; M3 #6 |
| M82 | command_policy.py | `_PROCESS_WRAPPERS: Final = frozenset({"command", "nice", "nohup", "stdbuf", "time", "timeout"})` | `_PROCESS_WRAPPERS: Final = frozenset()` | M2 `test_process_wrappers` |
| M83 | command_policy.py | `if segment.depth >= bounds.max_nesting:` | `if False:` | M2 `test_bounds_shell_wrapper_nesting` |
| M84 | command_policy.py | `if type(dialect) is not str or dialect not in DIALECTS:` | `if False:` | M2 `test_dialects` |
| M85 | command_policy.py | `return "cmd" if (sys.platform if platform is None else platform) == "win32" else "posix"` | `return "posix"` | M2 `test_dialects` |
| M86 | command_policy.py | `_POLICY_DOMAIN: Final = b"probos.command_policy/policy/v1\x00"` | `_POLICY_DOMAIN: Final = b"probos.command_policy/policy/v2\x00"` | M1 `test_policy_digest_known_answer` |
| M87 | command_policy.py | `_CANONICAL_DOMAIN: Final = b"probos.command_policy/canonical_command/v1\x00"` | `_CANONICAL_DOMAIN: Final = b"probos.command_policy/canonical_command/v2\x00"` | M2 `test_canonical_key_known_answer` |
| M88 | command_policy.py | `return _path_key(resolved, segment.dialect)` | `return _program_name(program, segment.dialect)` | M2 `test_canonical_program_resolution` |
| M89 | command_policy.py | `return SegmentVerdict(index, segment, config.unparseable_decision, "unparseable", ())` | `return SegmentVerdict(index, segment, unmatched, "unparseable", ())` | M3 `test_unmatched_and_unparseable_decisions` |
| M90 | command_policy.py | `return CommandEvaluation("evaluated", config.unparseable_decision, dialect, digest, (), parsed.unparseable)` | `return CommandEvaluation("evaluated", "allow", dialect, digest, (), parsed.unparseable)` | M3 `test_unmatched_and_unparseable_decisions` |
| M91 | command_policy.py | `if not config.rules:  # no policy: nothing is parsed or decided` | `if False:` | M3 `test_no_rules_is_no_policy_and_parses_nothing` |
| M92 | command_policy.py | `if not self._config.rules:` | `if False:` | M3 `test_no_rules_is_no_policy_and_parses_nothing` |
| M93 | command_policy.py | `if not self._report.passed:` | `if False:` | M3 `test_a_wrong_example_names_the_rule_and_the_example` |
| M94 | command_policy.py | `return "matches it" if matched else None` | `return None` | M3 `test_a_wrong_example_names_the_rule_and_the_example` |
| M95 | command_policy.py | `matched = any(not match.pin_violation for match in own)` | `matched = bool(own)` | M3 `test_a_wrong_example_names_the_rule_and_the_example` |
| M96 | command_policy.py | `if op == "<<":` | `if False:` | M2 `test_unparseable_line` (here-document, here-string) |
| R1-R7 | operations.py | unchanged from S1's table | unchanged | unchanged |
| R8 | operations.py | `return any("\ud800" <= char <= "\udfff" for char in value)` | `return False` | R-M1 #1 |

Equivalent mutants, not listed: removing the PowerShell `&&` check in `_ampersand` or the `||` check in `lex` (a `&` after a word is a background job, and a second `|` is an empty command, so both are still refused, with another reason). No mutant above can loop: each replaced condition falls through to a branch that advances the cursor or returns.

## Milestones

| M | Scope | Calls (about) |
|---|---|---|
| Install | Sections 1-5 by script; ledger regeneration; the live oracle on this host (cmd, Windows PowerShell 5.1, pwsh) after R-M4, with versions recorded in `provenance.verified_on` | n/a |
| R-M1 | `tests/test_ad1328_s1_policy_models.py` (add #1) | 20 |
| R-M2 | `tests/test_ad1328_s1_command_parse.py` (changed tests; add #1-#7) | 160 |
| R-M3 | `tests/test_ad1328_s1_policy_evaluation.py` (changed tests; add #1-#8) | 90 |
| R-M4 | `tests/test_ad1328_s1_shell_oracle.py` (new), then the focused gate (acceptance 6) | 90 |
| Campaign | the table above, once, on the committed tree | n/a |

=== BUILDER BRIEFS ===

### Brief R-M1 -- `tests/test_ad1328_s1_policy_models.py`

Tests only; never edit `src/`, `tests/fixtures/` or prompts. Add R-M1 #1 from `prompts/ad-1328-s1-repair-r1.md` ("Tests"). Build models with `model_validate` from dicts; assert `not valid Unicode` and the rule name in `str(exc)`. Must kill R8. Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s1_policy_models.py -q -n 0`. Stop and report a source defect rather than weaken a test.

### Brief R-M2 -- `tests/test_ad1328_s1_command_parse.py`

Tests only. Apply every change in "Existing tests that change" for this file exactly, then add R-M2 #1-#7 (the refusal table and the corpus are data: copy them literally; write control characters and surrogates with escapes such as `"\r\n"`, `"\ud800"`, `"\u202e"`). Pass `dialect=` explicitly. Each refusal row also asserts the deny-list evaluation (`forbid ["curl"]`, `unmatched_decision="allow"`) is `escalate`. Mutants to kill: the R-M2 rows of the campaign. Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s1_command_parse.py -q -n 0`. A reading that differs from the contract is a finding to report, not a test to relax.

### Brief R-M3 -- `tests/test_ad1328_s1_policy_evaluation.py`

Tests only. Apply the changes listed for this file, then add R-M3 #1-#8. Use the `_policy`/`_rule` helpers already in the file; resolvers are dict lookups. Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s1_policy_evaluation.py -q -n 0`.

### Brief R-M4 -- `tests/test_ad1328_s1_shell_oracle.py`

Tests only; never edit the oracle or the probe. Implement R-M4 #1-#4 per R6 and "R-M4" in the contract. Live runs use exactly the consumer launch forms: POSIX `[shell_path, "-c", text]` (off Windows), cmd `subprocess.run(text, shell=True)` (Windows), PowerShell `["powershell", "-NoProfile", "-Command", text]` and `["pwsh", "-NoProfile", "-Command", text]`. Skip, with a reason, when a shell or a `requires` program is missing. A live row that fails is reported with its observed argv lists to the orchestrator (hard stop to the Architect); never adjust a row. Then run the focused gate (contract acceptance 6) and report every count and exit code, and which shells ran live.
