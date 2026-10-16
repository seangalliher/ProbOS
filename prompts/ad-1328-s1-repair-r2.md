# AD-1328 S1 repair r2 -- review round 2: computed PowerShell values, lookup proof, launchers, timed assignments, program identity

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16
**Status:** BUILD-READY. Amends `prompts/ad-1328-s1-repair-r1.md` and r1b to r1e (see "Amendments"). Every SEARCH was grepped in the worktree as it is now and occurs once. No new AD or BF number (#1530).
**Dependencies:** r1 to r1e installed and their tests present (R1D and R1E blocks are in `tests/test_ad1328_s1_command_parse_repair.py:900-1040`).
**Estimated tests:** about +330 cases (36 refusal rows, 8 reading rows, 261 launcher cases, 11 lookup lines, 10 identity rows, 6 single tests, 2 oracle property cases); about 20 existing rows edited (Hidden pins H1); oracle rows S11 and S19 removed, S08, S12 and S22 edited.

Verified against (staged blobs, `git ls-files -s`; base `26250c9c`, HEAD `e58f80fc`, no unstaged change):

| File | Blob |
|---|---|
| `src/probos/execution/command_policy.py` | `e14b27719bbea46cd46bdb2f766fc1c51c7b4d71` |
| `tests/fixtures/ad1328_shell_oracle.json` | `d8f1e08177e004dda44885513f0b9d7bd5721d6e` |
| `tests/test_ad1328_s1_command_parse_repair.py` | `fdbd2d951de0801362aa616cb4a0d63e9f08afd0` |
| `tests/test_ad1328_s1_command_parse.py` | `ed876092b969fec90f1c0abc0c81191028f4a36b` |
| `tests/test_ad1328_s1_policy_evaluation.py` | `e071f86b7d2e79632eeaa49d27168d393bbfda69` |
| `tests/test_ad1328_s1_shell_oracle.py` | `a46eecddda4109034897736e85b97db22a7bec85` |
| `DECISIONS.md` | `d9f36fe1e86e340eaa5ffc68adc2b4000fe20807` |

If a blob differs, re-grep each SEARCH before installing.

## Problem

GPT-6.1 Sol, review round 2 on the whole candidate (`logs/architect/ad1328-s1-review-r2-report.md`, evidence in `logs/architect/review2-evidence/`): six findings, all reproduced by the orchestrator. F1 to F5 are ordinary reach and reproduce on the round-1 blob. Each lets the policy **allow** a command it forbids when written directly.

| F | What the policy reads | What the shell runs |
|---|---|---|
| F1 | `receiver.cmd $env:CP_WORD` is one segment, the variable a variadic word (`_variable`, `:857-882`; `_splat`, `:884-892`) | 5.1 and 7 run `receiver.cmd` **and** `secondary.cmd` when the value is `alpha&secondary.cmd`; a value holding `"` regroups the neighbouring literal words on 5.1 |
| F2 | After `Set-Item Environment::PATH x; selected`, `read PATH; ...`, `printf -v PATH ...`, `selected` keeps its pin proof: `lookup_changed` is None (`_with_lookup_context`, `:1361-1367`, which knows only `_STATE_MUTATORS`, `:193-199`) | the changed program |
| F3 | `mintty -e python ...` is an ordinary unmatched program (`_LAUNCHERS_EVERYWHERE`, `:154-158`) | python |
| F4 | `time X=1 p push --force`: after `time` is stripped (`_strip_process_wrappers`, `:1117-1140`), `X=1` is the program | bash runs `p push --force` |
| F5 | `selected` and `.\selected` share the key `7b0b3b75...` (`_canonical_program`, `:1744-1751`: `_path_key(".\\selected")` normalises to `selected`, the bare name's key) | two different programs |

F6 (P2, injected-only, regression from the repair oracle): `_reading_problem` (`tests/test_ad1328_s1_shell_oracle.py:135`) looks for a refusal only among the probe segments, so a refused side command (P11's `wait`, P17's `printf`) does not fail its row.

## Decisions

**D-r2-1 Principle (F1).** The closed world stands: what the shell or the receiving program does with a word is modelled and oracle-backed, or the word is refused. Of the options, (a) refuse every value PowerShell itself computes, (b) refuse only when the program may be a batch file, (c) keep the variadic mark and add checks, only (a) can be decided from the text: (b) needs the program's file type, which the policy cannot see, and (c) cannot bound a runtime value. **Decided: (a).** PowerShell computes and transports, without the quoting the policy reads, three things: a `$` variable (plain, digit, special `$? $^ $$`, scoped `$env:X`, braced `${x}`, `${env:x}`, inside double quotes or concatenated), a splat `@name`, and a leading unquoted or escaped `~` (pwsh 7 substitutes the home directory itself, measured in r1d; a Windows profile path may hold `&`). All three are now unparseable, at line scope, with one reason `_PS_COMPUTED`. `$(...)`, `${...}` other forms, member access, `@(`, `@{` and here-strings keep their earlier refusals and reasons. Wildcards (`*?[{`, a quoted leading `~`/`@`) stay variadic: on Windows the program, not PowerShell, expands them into its own argv, and nothing re-parses that argv (r1e). **Cost:** no row of the usability corpus or the S2a starter uses a variable, a splat or a leading `~` (Absence A2). `git commit -m $msg`, `cd ~` and `echo $env:PATH` now escalate. A one-line command cannot assign a variable anyway (a `$x = ...` statement has a dynamic program, which is refused), so a variable can only be an automatic or environment one. **Other transport cases, checked:** cmd `%X%`/`!X!` are refused (r1) and `for` is a refused keyword. POSIX `$`, `$(...)`, globs and `~` reach the program through `execve`, unparsed; the review held them. A POSIX shell cannot be reached on Windows: the default dialect there is `cmd` (`:988`), and a POSIX shell started from cmd or PowerShell is refused (`:1249-1250`). Literal batch metacharacters in a PowerShell word are refused already (r1b).

**D-r2-2 Lookup context (F2).** The options were (a) an explicit table of context-pure programs, (b) a wider mutator table, and (c) "every other segment changes lookup context". **Decided: (c), with no pure table.** A builtin (`read`, `printf -v`, `let`, `mapfile`, `getopts`), a cmdlet on any provider path (`Set-Item`, `New-Item`, `Copy-Item`, `Set-Content`; `Environment::`, `Env:`, `-Path:`), a module function, or any program that writes a file into a PATH directory (or into cmd's working directory, which cmd searches first) can change what a name resolves to. A pipeline or background job gives no order to rely on. So a list of mutators cannot be complete, and a pure list would need its own oracle. (c) needs neither and is one rule: **a line of two or more segments proves no bare program's lookup context.** A known mutator still gives its own, more specific reason. Producers of "another segment": the separators `; & && || |` and newline, POSIX `$(...)` bodies, and unwrapped `sh/bash/dash -c`, `cmd /c` and `powershell/pwsh -Command` scripts. All go through `parse_command` -> `_with_lookup_context`, the one producer. A single segment cannot change its own lookup before it runs: its own assignments are refused by `allow` (`_match`, `:1513`), `command -p`, a login shell and a profile already mark it, and an in-segment expression is refused (`(`, `$(`, `@(`). **Exits, unchanged:** a pinned `allow` on a bare name becomes `forbid` with `pin_violation` and the alternative "run the pinned executable: <path>" (`_allow_match`, `:1537-1539`). An absolute path keeps its proof. `_is_simple` sends the line to a script key, as any multi-segment line already is. An unpinned `allow`, `forbid` and `escalate` are unaffected. **Cost:** a pinned program in a multi-segment line must be written as its absolute path. The starter has no pins.

**D-r2-3 Launchers (F3, F4).** **The rule:** a program is a launcher when its documented purpose is to run a program or command line that its arguments name: now, later, in another terminal, console or PTY, as another user, on another host, or under a changed identity, environment or limit. One table, `_LAUNCHERS_EVERYWHERE`, which every dialect reads through `windows_program_stem`. r2 adds 85 names, listed in Section 3: 44 terminals, consoles and PTY hosts; 36 elevation, remote, scheduling, environment and limit runners; and 5 openers. It moves `forfiles` and `start` from the cmd-only set into the shared table, because both are programs (Git for Windows ships `/usr/bin/start`) that PowerShell and POSIX lines can start. The test literal therefore has 87 names. Already covered: `script`, `expect`, `sudo`, `doas`, `su`, `runas`, `ssh`, `env`, `xargs`, `Start-Process`, `Start-Job`, `Invoke-Command`, `Invoke-Item`, and the shells. Interpreters and build tools stay at the r1 boundary (`find -exec`, `python -c`, `make`). **`time` (F4):** after any stripped process wrapper, a word with assignment syntax is refused. After bash's `time` keyword it is the timed command's own assignment; after the other wrappers it would be a program named `X=1`. Neither is read, and refusing costs nothing. A dynamic word right after a wrapper was already refused (`_wrapper_width`, `:1148-1149`). A quoted name (`time "X"=1 p`) is not an assignment, and bash runs `X=1` as the program, which is what the policy reads.

**D-r2-4 Identity (F5).** The argv key's program part is either (i) an **absolute** path, normalised, written as such or answered by the resolver, or (ii) the **name the shell looks up, as written** (case-folded on Windows). Anything else gets a `script` key: a relative path (`./x`, `.\x`, `sub\..\x`, drive-relative `C:x`, root-relative `\x`) or a POSIX path with a `..` component, whose target the kernel finds after following symbolic links, so `/a/../b` need not be `/b`. Windows resolves `..` in the text, so its absolute paths stay normalised. A resolver answer that is relative, or POSIX with `..`, is no identity, and the key stays the name. The name is no longer reduced to its stem: `git`, `git.exe` and `git.cmd` may find different files on a Windows PATH, so each is its own key. Path and name keys cannot collide: a path key holds `/`, `\` or a drive, and a name cannot. The pin check uses the same `_path_key`, so a POSIX `..` path, as written or as a pin, proves no pin. **Existing keys:** none are persisted (S2b is unbuilt). The keys that change are relative paths and POSIX `..` paths (argv to script), unresolved Windows names with an extension (stem to exact name), and relative resolver answers (path to name). `CANONICAL_KEY_SCHEME` stays v1.

**D-r2-5 Delivery.** Sections 1-12 below are fenced pairs for `install_fenced_pairs.py`: source, fixture and DECISIONS. The Builder writes tests only (R2-M2). Existing tests are edited only where Hidden pins H1 says. The added oracle edits only remove words that r2 refuses; the orchestrator re-runs every cmd and PowerShell row live after install. **Requested S2a/S2b amendments: none** (H3-H5).

**Captain:** none. Every decision makes the policy refuse more and widens no authority, so all of them are inside the envelope.

## Section 1 -- `src/probos/execution/command_policy.py` (constant `_WINDOWS_ABSOLUTE`)

SEARCH:
```python
_DRIVE_CHANGE: Final = re.compile(r"[A-Za-z]:")
```
REPLACE:
```python
_DRIVE_CHANGE: Final = re.compile(r"[A-Za-z]:")
# r2: a Windows path that names one file whatever the current drive and directory: 'C:\x', or a UNC or device path.
_WINDOWS_ABSOLUTE: Final = re.compile(r"[A-Za-z]:[\\/]|[\\/]{2}[^\\/]")
```

## Section 2 -- `src/probos/execution/command_policy.py` (constant `_PS_COMPUTED`)

SEARCH:
```python
_PS_PROVIDER_PREFIXES: Final = ("alias:", "function:", "env:", "variable:")
```
REPLACE:
```python
_PS_PROVIDER_PREFIXES: Final = ("alias:", "function:", "env:", "variable:")
# r2: PowerShell computes a variable's value (and pwsh 7 the home directory for a leading '~') and builds the program's
# command line from it without the quoting the policy reads: a '"' in the value regroups the neighbouring words on 5.1,
# and a '&' starts another command in a batch file on 5.1 and 7 (review r2, F1, executed).
_PS_COMPUTED: Final = (
    "a value PowerShell computes (a variable, a splat or a leading '~'), which it passes to a program without the "
    "quoting the policy reads"
)
```

## Section 3 -- `src/probos/execution/command_policy.py` (launchers)

SEARCH:
```python
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
```
REPLACE:
```python
# r2: a program is a launcher when its documented purpose is to run a program or command line its arguments name --
# now, later, in another terminal, console or PTY, as another user, on another host, or under a changed identity,
# environment or limit (review r2, F3: `mintty -e` ran the program the policy forbade).
_LAUNCHERS_EVERYWHERE: Final = frozenset({
    "env", "sudo", "doas", "su", "runuser", "pkexec", "chroot", "setsid", "setpriv", "ionice", "chrt", "taskset",
    "numactl", "flock", "unshare", "nsenter", "xargs", "parallel", "watch", "strace", "ltrace", "gdb", "valgrind",
    "firejail", "bwrap", "systemd-run", "script", "expect", "ssh", "npx", "pnpx", "bunx", "uvx", "pipx", "runas",
    # r2: terminals, consoles and PTY hosts
    "mintty", "winpty", "wt", "windowsterminal", "conhost", "openconsole", "conemu", "conemu64", "conemuc",
    "conemuc64", "tmux", "screen", "byobu", "dtach", "abduco", "unbuffer", "socat", "rlwrap", "openvt", "xterm",
    "uxterm", "gnome-terminal", "kgx", "ptyxis", "konsole", "xfce4-terminal", "mate-terminal", "lxterminal",
    "qterminal", "terminator", "tilix", "urxvt", "rxvt", "st", "foot", "footclient", "kitty", "alacritty", "wezterm",
    "wezterm-gui", "ghostty", "terminology", "sakura", "x-terminal-emulator",
    # r2: another user, host or time, or a changed identity, environment or limit
    "psexec", "psexec64", "paexec", "gsudo", "winrs", "wmic", "schtasks", "at", "batch", "mosh", "rsh",
    "start-stop-daemon", "daemonize", "chpst", "setuidgid", "envdir", "envuidgid", "softlimit", "prlimit", "cgexec",
    "systemd-nspawn", "xvfb-run", "dbus-launch", "dbus-run-session", "faketime", "fakeroot", "proot", "torsocks",
    "proxychains", "proxychains4", "tsocks", "entr", "catchsegv", "caffeinate", "sandbox-exec", "arch",
    # r2: openers; forfiles and start (Git for Windows ships /usr/bin/start) also run outside cmd.exe
    "explorer", "rundll32", "pcalua", "xdg-open", "open", "forfiles", "start",
})
_LAUNCHERS: Final[dict[str, frozenset[str]]] = {
    "posix": _LAUNCHERS_EVERYWHERE | {
        "eval", "exec", "source", ".", "alias", "unalias", "enable", "shopt", "trap", "builtin", "noglob",
    },
    "cmd": _LAUNCHERS_EVERYWHERE | {"call", "doskey"},
```

## Section 4 -- `src/probos/execution/command_policy.py` (constant `_ANOTHER_COMMAND`)

SEARCH:
```python
_DEFAULT_PATH: Final = "command -p looks the program up on the default PATH"
```
REPLACE:
```python
_DEFAULT_PATH: Final = "command -p looks the program up on the default PATH"
_ANOTHER_COMMAND: Final = "another command in the line runs before or beside this one and may change where it resolves"
```

## Section 5 -- `src/probos/execution/command_policy.py` (`CommandSegment` docstring)

SEARCH:
```python
    program may not be the one the command's starting PATH and working directory
    find (a directory or environment change in the line, a login shell, a
    PowerShell profile, ``command -p``), or is None.
```
REPLACE:
```python
    program may not be the one the command's starting PATH and working directory
    find (another command in the line, a directory or environment change, a login
    shell, a PowerShell profile, ``command -p``), or is None.
```

## Section 6 -- `src/probos/execution/command_policy.py` (`CanonicalCommand` docstring)

SEARCH:
```python
    (its own or a shell wrapper's), after unwrapping shell wrappers: the program as
    its normalised resolved path when the resolver knows it (so ``git`` and
    ``/usr/bin/git`` share a key), else its normalised name, then the arguments; the
    dialect is not part of it. ``script``: anything else -- the dialect and the exact
```
REPLACE:
```python
    (its own or a shell wrapper's), after unwrapping shell wrappers: the program as
    its normalised absolute path when it is written as one or the resolver answers
    with one (so ``git`` and ``/usr/bin/git`` share a key), else the name the shell
    looks up as written (case folded on Windows), then the arguments; the dialect is
    not part of it. A relative program path, or a POSIX one with ``..``, has no such
    identity (r2). ``script``: anything else -- the dialect and the exact
```

## Section 7 -- `src/probos/execution/command_policy.py` (`_PowerShellLexer`: four producers of a computed value)

SEARCH (7a, `lex`):
```python
            else:
                if ch in "*?" or (ch == "~" and self._start < 0):
                    self._mark_dynamic(variadic=True)  # PowerShell 7 or the program may expand it
                self._literal(ch, quoted=False)
```
REPLACE:
```python
            else:
                if ch == "~" and self._start < 0:
                    raise _Unparseable(_PS_COMPUTED)  # r2: pwsh 7 puts the home directory here itself
                if ch in "*?":
                    self._mark_dynamic(variadic=True)  # the program (or pwsh 7 off Windows) may expand it
                self._literal(ch, quoted=False)
```

SEARCH (7b, `_escape`):
```python
        if following == "~" and self._start < 0:  # measured: pwsh 7 expands an escaped leading tilde like a bare one
            self._mark_dynamic(variadic=True)
        self._literal(following, quoted=True)
```
REPLACE:
```python
        if following == "~" and self._start < 0:  # measured: pwsh 7 expands an escaped leading tilde like a bare one
            raise _Unparseable(_PS_COMPUTED)  # r2: as a bare leading '~'
        self._literal(following, quoted=True)
```

SEARCH (7c, `_variable`):
```python
        if not quoted and text[end:end + 1] in (".", ":", "["):
            raise _Unparseable("member access or indexing on a PowerShell variable")
        self._mark_dynamic(variadic=True)  # Windows PowerShell 5.1 drops an empty string; an array passes as many
        self.i = end
```
REPLACE:
```python
        if not quoted and text[end:end + 1] in (".", ":", "["):
            raise _Unparseable("member access or indexing on a PowerShell variable")
        raise _Unparseable(_PS_COMPUTED)  # r2: the value reaches the program without the quoting the policy reads
```

SEARCH (7d, `_splat`):
```python
        end = self.i + 2
        while end < len(self.text) and _IDENT_CHAR.fullmatch(self.text[end]) is not None:
            end += 1
        self._mark_dynamic(variadic=True)
        self.i = end
```
REPLACE:
```python
        raise _Unparseable(_PS_COMPUTED)  # r2: a splat passes computed values
```

## Section 8 -- `src/probos/execution/command_policy.py` (names and paths)

SEARCH:
```python
def _program_name(program: str, dialect: Dialect) -> str:
    return posixpath.basename(program) if dialect == "posix" else windows_program_stem(program)


def _is_path(program: str, dialect: Dialect) -> bool:
    return "/" in program if dialect == "posix" else any(char in program for char in "/\\:")


def _path_key(path: str, dialect: Dialect) -> str:
    return posixpath.normpath(path) if dialect == "posix" else ntpath.normcase(ntpath.normpath(path))
```
REPLACE:
```python
def _program_name(program: str, dialect: Dialect) -> str:
    """The name the shell looks up, as written (r2): ``git`` and ``git.exe`` may find different files on a Windows
    PATH, so only the case is folded there."""
    return program if dialect == "posix" else program.lower()


def _is_path(program: str, dialect: Dialect) -> bool:
    return "/" in program if dialect == "posix" else any(char in program for char in "/\\:")


def _is_absolute(path: str, dialect: Dialect) -> bool:
    """r2: a path that names one file whatever the working directory and the current drive are. A relative path, a
    drive-relative ``C:x`` and a root-relative ``\\x`` do not."""
    return path.startswith("/") if dialect == "posix" else _WINDOWS_ABSOLUTE.match(path) is not None


def _path_key(path: str, dialect: Dialect) -> str | None:
    """``path`` normalised, or None when normalising could name another file (r2): the kernel resolves a POSIX '..'
    after following symbolic links, so ``/a/../b`` need not be ``/b``. Windows resolves '..' in the text itself."""
    if dialect == "posix":
        return None if ".." in path.split("/") else posixpath.normpath(path)
    return ntpath.normcase(ntpath.normpath(path))
```

## Section 9 -- `src/probos/execution/command_policy.py` (`_strip_process_wrappers`, F4)

SEARCH:
```python
        lookup = note or lookup
        wrappers.append(" ".join(word.raw for word in words[:width]))
        del words[:width]
    return None, lookup
```
REPLACE:
```python
        lookup = note or lookup
        wrappers.append(" ".join(word.raw for word in words[:width]))
        del words[:width]
    if wrappers and words and words[0].assignment:
        # r2: after bash's `time` keyword the assignment is the timed command's own (`time X=1 p` runs p); after the
        # other wrappers it names the program. Neither is read (review r2, F4, executed on bash).
        return (
            f"an assignment ({words[0].raw}) after the process wrapper {wrappers[-1]!r}, "
            "which the policy does not read",
            lookup,
        )
    return None, lookup
```

## Section 10 -- `src/probos/execution/command_policy.py` (`_with_lookup_context`, F2)

SEARCH:
```python
def _with_lookup_context(segments: list[CommandSegment]) -> tuple[CommandSegment, ...]:
    """A line that changes the working directory or the environment changes where every program in it resolves."""
    mutator = next((segment for segment in segments if _is_state_mutator(segment)), None)
    if mutator is None:
        return tuple(segments)
    reason = f"the command changes the working directory or the environment ({mutator.tokens[0]})"
    return tuple(s if s.lookup_changed is not None else replace(s, lookup_changed=reason) for s in segments)
```
REPLACE:
```python
def _with_lookup_context(segments: list[CommandSegment]) -> tuple[CommandSegment, ...]:
    """Where a program resolves is proven only for a line of one segment (r2). A known mutator is named; otherwise
    any other segment counts, whatever it is: a builtin, a cmdlet on a provider path, a function, or a program that
    writes a file on PATH can change the lookup, and a pipeline or background job gives no order to rely on."""
    mutator = next((segment for segment in segments if _is_state_mutator(segment)), None)
    if mutator is not None:
        reason = f"the command changes the working directory or the environment ({mutator.tokens[0]})"
    elif len(segments) > 1:
        reason = _ANOTHER_COMMAND
    else:
        return tuple(segments)
    return tuple(s if s.lookup_changed is not None else replace(s, lookup_changed=reason) for s in segments)
```

## Section 11 -- `src/probos/execution/command_policy.py` (`_allow_match`, `_canonical_program`, `canonical_command`; F5)

SEARCH (11a):
```python
    pinned = {_path_key(pin, segment.dialect) for pin in rule.host_executable}
```
REPLACE:
```python
    pinned = {_path_key(pin, segment.dialect) for pin in rule.host_executable} - {None}  # r2: a pin with '..' proves nothing
```

SEARCH (11b):
```python
def _canonical_program(segment: CommandSegment, resolve: ProgramResolver | None) -> str:
    program = segment.tokens[0]
    if _is_path(program, segment.dialect):
        return _path_key(program, segment.dialect)
    resolved = _resolve(resolve, program)
    if resolved is not None:
        return _path_key(resolved, segment.dialect)
    return _program_name(program, segment.dialect)
```
REPLACE:
```python
def _canonical_program(segment: CommandSegment, resolve: ProgramResolver | None) -> str | None:
    """The program's identity: an absolute path, normalised, or the name the shell looks up. None when neither is
    proven (r2): a relative path, which depends on the working directory and must never share a bare name's key, or
    a POSIX path with '..'. A resolver's answer counts only when it is such an absolute path."""
    program = segment.tokens[0]
    if _is_path(program, segment.dialect):
        return _path_key(program, segment.dialect) if _is_absolute(program, segment.dialect) else None
    resolved = _resolve(resolve, program)
    if resolved is not None and _is_absolute(resolved, segment.dialect):
        key = _path_key(resolved, segment.dialect)
        if key is not None:
            return key
    return _program_name(program, segment.dialect)
```

SEARCH (11c):
```python
    if parsed.unparseable is None and len(parsed.segments) == 1 and _is_simple(parsed.segments[0]):
        segment = parsed.segments[0]
        return CanonicalCommand("argv", None, (_canonical_program(segment, resolve_program), *segment.tokens[1:]))
    return CanonicalCommand("script", chosen, (command,))
```
REPLACE:
```python
    if parsed.unparseable is None and len(parsed.segments) == 1 and _is_simple(parsed.segments[0]):
        segment = parsed.segments[0]
        program = _canonical_program(segment, resolve_program)
        if program is not None:
            return CanonicalCommand("argv", None, (program, *segment.tokens[1:]))
    return CanonicalCommand("script", chosen, (command,))
```

## Section 12 -- `tests/fixtures/ad1328_shell_oracle.json` (rows that recorded words r2 refuses)

S11 (`$env:W`) and S19 (`$x`) read only words that are now refused, so they are removed. S08 loses its `$null` target. S12 and S22 lose their leading `~` words. The words left in each row are unchanged from the measured rows.

SEARCH (12a, provenance):
```json
      "2026-10-16, Git for Windows bash 5.2.37 and its dash, scripts fed on stdin: the posix reading was cross-checked by a differential fuzz outside the repository (accepted lines compared with the argv a probe received), not by these rows"
    ]
```
REPLACE:
```json
      "2026-10-16, Git for Windows bash 5.2.37 and its dash, scripts fed on stdin: the posix reading was cross-checked by a differential fuzz outside the repository (accepted lines compared with the argv a probe received), not by these rows",
      "2026-10-16, r2 (prompts/ad-1328-s1-repair-r2.md) edit, not a measurement: S11 and S19 removed and S08, S12 and S22 cut to the words r2 still reads (it refuses a PowerShell variable, splat or leading '~'); the remaining words are those measured above, and the orchestrator re-runs every cmd and PowerShell row live after install"
    ]
```

SEARCH (12b):
```json
    {"id": "S08", "dialect": "powershell", "constructs": ["S-REDIR"], "text": "{P} a > $null; {P} b 2>&1; {P} c 2> x.txt; {P} d *> y.txt; {P} e >> z.txt", "policy": [["a"], ["b"], ["c"], ["d"], ["e"]]},
```
REPLACE:
```json
    {"id": "S08", "dialect": "powershell", "constructs": ["S-REDIR"], "text": "{P} a > w.txt; {P} b 2>&1; {P} c 2> x.txt; {P} d *> y.txt; {P} e >> z.txt", "policy": [["a"], ["b"], ["c"], ["d"], ["e"]]},
```

SEARCH (12c):
```json
    {"id": "S11", "dialect": "powershell", "constructs": [], "env": {"W": "x y"}, "text": "{P} $env:W \"$env:W\" ${env:W}", "policy": [[null, null, null]], "marks": ["vvv"]},
    {"id": "S12", "dialect": "powershell", "constructs": [], "files": ["a1.txt"], "text": "{P} a*.txt ~", "policy": [[null, null]], "marks": ["vv"]},
```
REPLACE:
```json
    {"id": "S12", "dialect": "powershell", "constructs": [], "files": ["a1.txt"], "text": "{P} a*.txt", "policy": [[null]], "marks": ["v"]},
```

SEARCH (12d):
```json
    {"id": "S18", "dialect": "powershell", "constructs": ["S-DQ", "S-ESC"], "text": "{P} \"` zz\"", "policy": [[" zz"]], "live": [[" zz"]]},
    {"id": "S19", "dialect": "powershell", "constructs": [], "text": "{P} $x` b", "policy": [[null]], "marks": ["v"], "live": [[" b"]]},
```
REPLACE:
```json
    {"id": "S18", "dialect": "powershell", "constructs": ["S-DQ", "S-ESC"], "text": "{P} \"` zz\"", "policy": [[" zz"]], "live": [[" zz"]]},
```

SEARCH (12e):
```json
    {"id": "S22", "dialect": "powershell", "constructs": ["S-ESC"], "text": "{P} `~ `~/x `~x a`~b '~'", "policy": [[null, null, null, "a~b", null]], "marks": ["vvvlv"], "live": {"powershell": [["~", "~/x", "~x", "a~b", "~"]]}},
```
REPLACE:
```json
    {"id": "S22", "dialect": "powershell", "constructs": ["S-ESC"], "text": "{P} a`~b '~'", "policy": [["a~b", null]], "marks": ["lv"], "live": {"powershell": [["a~b", "~"]]}},
```

## Section 13 -- `DECISIONS.md`

SEARCH:
```
the set cmd already uses. Contracts `prompts/ad-1328-s1-repair-r1.md` to `prompts/ad-1328-s1-repair-r1e.md`.
```
REPLACE:
```
the set cmd already uses. Review round 2 then closed five ordinary-reach classes by refusal or by loss of proof. A value PowerShell computes (a variable, a splat, a leading `~`) is unparseable, because PowerShell passes it to a program without the quoting the policy reads. A line of two or more segments proves no bare program's lookup context, so a pinned `allow` needs a one-segment line or an absolute path. Terminals, consoles, PTY hosts and the other launchers in `_LAUNCHERS_EVERYWHERE` are opaque. An assignment after a process wrapper is refused. The canonical key gives a relative program path, or a POSIX path with `..`, a script key, and keys a name as written. Contracts `prompts/ad-1328-s1-repair-r1.md` to `prompts/ad-1328-s1-repair-r2.md`.
```

## Tests (milestone R2-M2, Builder, tests only)

### Part A -- existing tests that change (each pinned the defect or now refuses)

In every table cell of this contract, `\|` is the Markdown escape for a literal `|`; type `|`.

| File:line (blob above) | Change | Why |
|---|---|---|
| `test_ad1328_s1_command_parse.py:477-479, :484-486` (`ps_var`, `ps_brace`, `ps_splat`, `ps_double_quoted_var`, `ps_double_quoted_scoped_var`, `ps_automatic_variable`) | Remove the six rows; add `pytest.param("powershell", "echo *.py", (False, True), (False, True), id="ps_glob")`; comment `:457` "S11, S12" -> "S12" | F1: refused (rows `r2_ps_*` below) |
| `test_ad1328_s1_command_parse.py:551` (`ps_subexpression`) | neighbour `"echo $x"` -> `"echo x"` | the neighbour is now refused |
| `test_ad1328_s1_command_parse.py:632-633` (`ps_dynamic_call`, `_with_a_path`) and comment `:625-628` | Remove both rows. The comment drops `& $x` / `& $d/git` | now line refusals: `r2_ps_call_variable`, `_path` |
| `test_ad1328_s1_command_parse.py:826-834` (`posix_sh_c_two_commands`) | lookup `None` -> `"another command in the line"` | F2: two segments |
| `test_ad1328_s1_policy_evaluation.py:429` | Drop `"/usr/local/../bin/git status"` from the allow loop. After the loop assert that it gives `forbid` with one match, `pin_violation is True` (comment: POSIX `..` is resolved after symlinks, r2) | F5: the row pinned the defect |
| `test_ad1328_s1_policy_evaluation.py:802-803` | `("powershell", "git @a")`, `("powershell", "git $x")` -> `("powershell", "git *")`, `("powershell", "git '*'")`; comment `:786` "S11 and S12" -> "S12 and S24" | F1 |
| `test_ad1328_s1_command_parse_repair.py:142-144` | neighbours -> `"git push args --force"`, `"git push args x"`, `"git push args x"` | neighbour refused |
| `...repair.py:146`, `:147` | neighbours -> `"echo e"`, `"echo a.b"` | neighbour refused |
| `...repair.py:363-368` (ARITY powershell) | command `"echo *.py '*' '$x' a~b"`, dynamic and variadic `"F,T,T,F,F"`; comment `:341` drops S11 and the `~` of S12 | F1 |
| `...repair.py:430-432` (LOOKUP controls `posix_control`, `cmd_control`, `ps_control`) | cause `None` -> `"another command in the line"`; append `("posix_single_control", "posix", "git status", 1, None)`, `("cmd_single_control", "cmd", "git status", 1, None)`, `("ps_single_control", "powershell", "git status", 1, None)` | F2: they pinned the defect |
| `...repair.py:728-732` (`_CONTEXT_CHANGING`) and comment `:620-621` | add `("posix", "git status && git diff --stat")`, `("posix", "pytest -q 2>&1 \| tail -n 20")`, `("cmd", "git status && git diff --stat")`, `("cmd", "pytest -q 2>&1 \| findstr FAILED")`, `("powershell", "git status; git diff --stat")`, `("powershell", "pytest -q 2>&1 \| Select-Object -Last 20")`; comment: "every row of two or more segments" | F2 (the decision stays `allow`: no pins) |
| `...repair.py:779` | neighbour -> ``"echo x` b"`` | neighbour refused |
| `...repair.py:781-791` (R1B dynamic rows) | Rewritten in the next table. The count stays 16 | each now refused by `$` first; the rewrite keeps M99 killed with a wildcard-dynamic word |
| `...repair.py:815`, `:816`, `:818` | `s19_after_variable` -> ``("s19_glob_then_escaped_blank", "powershell", "echo *` b", ("echo", "* b"), (False, True))``; remove `dynamic_empty_text` (no PowerShell dynamic word has empty literal text now); `dynamic_dash_text` command -> `"echo *-b"`, tokens `("echo", "*-b")` | F1 |
| `...repair.py:847` (`r1c_ps_colon_variable`) | reason -> `"a value PowerShell computes"`, neighbour -> `"echo -a x"` | `$x` is refused first |
| `...repair.py:918` (`r1d_ps_dash_variable_dot`) | neighbour -> `"echo -ax-b"` (reason unchanged: member access is checked first) | neighbour refused |
| `...repair.py:938-940` (`e_escaped_tilde`, `_path`, `_name`) | Remove them; their refusals are `r2_ps_escaped_tilde*` | F1 |
| `test_ad1328_s1_shell_oracle.py:135-137` | Replace them with the block after the next table | F6 |

R1B rows 781-791 as rewritten. Each id is unchanged. Python literals are shown; ``"echo *` a\\"`` is the text ``echo *` a\``.

| id | command | reason | neighbour |
|---|---|---|---|
| `r1b_ps_dynamic_quote` | ``'echo *`"b jj jj'`` | `a double quote inside an argument` | `"echo *-b jj jj"` |
| `r1b_ps_dynamic_quote_in_quotes` | ``'echo "*`"b" jj'`` | same | `'echo "* b" jj'` |
| `r1b_ps_dynamic_batch_ampersand` | ``"run.bat *`&calc"`` | `batch-file program` | `"run.bat *-calc"` |
| `r1b_ps_dynamic_batch_percent` | unchanged | unchanged | unchanged |
| `r1b_ps_dynamic_tab` | `'echo "*\tb"'` | `quotes for a program` | `'echo "* b"'` |
| `r1b_ps_dynamic_blank_backslash` | ``"echo *` a\\"`` | `quotes for a program` | ``"echo *` a\\b"`` |
| `r1b_ps_dynamic_single_quote` | ``"echo *`'b"`` | `single quote in an argument without a blank` | ``"echo *`'` b"`` |
| `r1b_ps_dynamic_provider` | `"Set-Item alias:* curl"` | `alias:` | `"Set-Item x* curl"` |
| `r1b_ps_dynamic_provider_after_variable` | unchanged | `a value PowerShell computes` | `"Remove-Item envPATH"` |
| `r1b_ps_dynamic_stop_parsing` | `"echo --%*"` | `the -- or --%` | `"echo -*"` |
| `r1b_ps_dynamic_dashdash` | unchanged | `a value PowerShell computes` | `"git checkout --x"` |

`_reading_problem`, F6:

```python
    # r2 (review r2, F6): every segment of the line, not only the probe's; a refused side command fails the row too.
    unreadable = [segment.unparseable for segment in parsed.segments if segment.unparseable is not None]
    if unreadable:
        return f"the policy cannot read a segment of the line: {unreadable}"
```

### Part B -- appended to `tests/test_ad1328_s1_command_parse_repair.py` (after the R1E block)

It reuses `test_finding_refusals`, `test_r1b_readings_unchanged`, `_accepted` and `_deny_curl`. Add `from collections.abc import Callable` only if a type hint needs it.

```python
# --------------------------------------------------------------------------------------
# r2 (prompts/ad-1328-s1-repair-r2.md) -- adversarial review round 2, F1-F5
#   F1: a value PowerShell computes ($ variable, @ splat, leading '~') is refused.
#   F2: a line of two or more segments proves no bare program's lookup context.
#   F3: terminals, consoles, PTY hosts and the other launchers are opaque.
#   F4: an assignment after a process wrapper is refused.
#   F5: a relative program path, or a POSIX path with '..', has no argv identity; a name is keyed as written.
# --------------------------------------------------------------------------------------

_R2_COMPUTED = "a value PowerShell computes"
_R2_AFTER_WRAPPER = "after the process wrapper"
_R2_ANOTHER = "another command in the line"

R2_REFUSALS: list[tuple[str, str, str, str, str, str]] = [
    # F1 -- every producer of a PowerShell computed value (review r2 executed the first on 5.1 and 7)
    ("r2_ps_env_variable", "powershell", "receiver.cmd $env:CP_WORD", "line", _R2_COMPUTED, "receiver.cmd CP_WORD"),
    ("r2_ps_plain_variable", "powershell", "echo before $x tail last", "line", _R2_COMPUTED, "echo before x tail last"),
    ("r2_ps_scoped_variable", "powershell", "echo $script:x", "line", _R2_COMPUTED, "echo script-x"),
    ("r2_ps_braced_variable", "powershell", "echo ${x}", "line", _R2_COMPUTED, "echo x"),
    ("r2_ps_braced_scoped_variable", "powershell", "echo ${env:PATH}", "line", _R2_COMPUTED, "echo env-PATH"),
    ("r2_ps_automatic_variable", "powershell", "echo $HOME", "line", _R2_COMPUTED, "echo HOME"),
    ("r2_ps_special_question", "powershell", "echo $?", "line", _R2_COMPUTED, "echo q"),
    ("r2_ps_special_caret", "powershell", "echo $^", "line", _R2_COMPUTED, "echo c"),
    ("r2_ps_special_dollar", "powershell", "echo $$", "line", _R2_COMPUTED, "echo d"),
    ("r2_ps_quoted_variable", "powershell", 'echo "$x"', "line", _R2_COMPUTED, 'echo "x"'),
    ("r2_ps_interpolated", "powershell", 'echo "a $x b"', "line", _R2_COMPUTED, 'echo "a x b"'),
    ("r2_ps_interpolated_scoped", "powershell", 'echo "$env:W"', "line", _R2_COMPUTED, 'echo "env-W"'),
    ("r2_ps_interpolated_digit", "powershell", 'echo "cost $5"', "line", _R2_COMPUTED, 'echo "cost 5"'),
    ("r2_ps_concatenated_before", "powershell", "echo pre$x", "line", _R2_COMPUTED, "echo prex"),
    ("r2_ps_concatenated_after", "powershell", "echo $x-post", "line", _R2_COMPUTED, "echo x-post"),
    ("r2_ps_splat", "powershell", "git push @args", "line", _R2_COMPUTED, "git push args"),
    ("r2_ps_splat_then_words", "powershell", "git @a --force", "line", _R2_COMPUTED, "git a --force"),
    ("r2_ps_call_variable", "powershell", "& $x", "line", _R2_COMPUTED, "& x"),
    ("r2_ps_call_variable_path", "powershell", "& $d/git push", "line", _R2_COMPUTED, "& d/git push"),
    ("r2_ps_redirect_variable", "powershell", "echo a > $null", "line", _R2_COMPUTED, "echo a > w.txt"),
    ("r2_ps_tilde", "powershell", "echo ~", "line", _R2_COMPUTED, "echo '~'"),
    ("r2_ps_tilde_path", "powershell", "echo ~/x", "line", _R2_COMPUTED, "echo '~/x'"),
    ("r2_ps_escaped_tilde", "powershell", "echo `~", "line", _R2_COMPUTED, "echo a`~b"),
    ("r2_ps_escaped_tilde_path", "powershell", "echo `~/x", "line", _R2_COMPUTED, "echo x`~"),
    ("r2_ps_escaped_tilde_name", "powershell", "echo `~x", "line", _R2_COMPUTED, "echo ``~"),
    (
        "r2_cmd_wrapped_variable", "cmd", 'powershell -NoProfile -Command "echo $x"', "segment", _R2_COMPUTED,
        'powershell -NoProfile -Command "echo x"',
    ),
    # F4 -- an assignment after a process wrapper (review r2 executed the first on bash)
    ("r2_time_assignment", "posix", "time X=1 p push --force", "segment", _R2_AFTER_WRAPPER, "time p push --force"),
    ("r2_time_twice_assignment", "posix", "time time X=1 p", "segment", _R2_AFTER_WRAPPER, "time time p"),
    ("r2_time_quoted_value", "posix", "time X='a b' p", "segment", _R2_AFTER_WRAPPER, "X='a b' p"),
    ("r2_time_assignment_only", "posix", "time X=1", "segment", _R2_AFTER_WRAPPER, "time x"),
    ("r2_time_assignment_then_wrapper", "posix", "time X=1 nice p", "segment", _R2_AFTER_WRAPPER, "time nice p"),
    ("r2_leading_then_timed_assignment", "posix", "A=1 time B=2 p", "segment", _R2_AFTER_WRAPPER, "A=1 time p"),
    ("r2_nohup_assignment", "posix", "nohup X=1 p", "segment", _R2_AFTER_WRAPPER, "nohup p"),
    ("r2_command_assignment", "posix", "command X=1 p", "segment", _R2_AFTER_WRAPPER, "command p"),
    ("r2_timeout_assignment", "posix", "timeout 5 X=1 p", "segment", _R2_AFTER_WRAPPER, "timeout 5 p"),
    ("r2_stdbuf_assignment", "posix", "stdbuf -oL X=1 p", "segment", _R2_AFTER_WRAPPER, "stdbuf -oL p"),
]


def test_r2_refusals_table() -> None:
    ids = [row[0] for row in R2_REFUSALS]
    assert len(R2_REFUSALS) == 36
    assert len(set(ids)) == len(ids)
    earlier = {row[0] for row in FINDING_REFUSALS + R1B_REFUSALS + R1C_REFUSALS + R1D_REFUSALS + R1E_REFUSALS}
    assert not set(ids) & earlier


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "scope", "reason", "neighbour"), R2_REFUSALS, ids=[row[0] for row in R2_REFUSALS],
)
def test_r2_refusals(case_id: str, dialect: Dialect, command: str, scope: str, reason: str, neighbour: str) -> None:
    test_finding_refusals(case_id, dialect, command, scope, reason, neighbour)


R2_READINGS: list[tuple[str, Dialect, str, tuple[str, ...], tuple[bool, ...]]] = [
    ("r2_time_program", "posix", "time p push --force", ("p", "push", "--force"), (False, False, False)),
    ("r2_time_quoted_name_is_the_program", "posix", 'time "X"=1 p', ("X=1", "p"), (False, False)),  # bash runs X=1
    ("r2_assignment_before_time", "posix", "X=1 time p", ("p",), (False,)),
    ("r2_ps_quoted_tilde", "powershell", "echo '~'", ("echo", "~"), (False, True)),  # rule G; PowerShell passes it as is
    ("r2_ps_glob_still_variadic", "powershell", "echo *.txt", ("echo", "*.txt"), (False, True)),
    ("r2_ps_single_quoted_dollar", "powershell", "echo '$x'", ("echo", "$x"), (False, False)),
    ("r2_ps_escaped_dollar", "powershell", "echo `$x", ("echo", "$x"), (False, False)),
    ("r2_posix_variable_unchanged", "posix", "echo $x", ("echo", ""), (False, True)),
]


@pytest.mark.parametrize(
    ("case_id", "dialect", "command", "tokens", "dynamic"), R2_READINGS, ids=[row[0] for row in R2_READINGS],
)
def test_r2_readings(case_id: str, dialect: Dialect, command: str, tokens: tuple[str, ...], dynamic: tuple[bool, ...]) -> None:
    test_r1b_readings_unchanged(case_id, dialect, command, tokens, dynamic)


def _r2_policy(*rules: dict[str, Any]) -> CommandPolicyConfig:
    return CommandPolicyConfig.model_validate(
        {"rules": list(rules), "unmatched_decision": "allow", "unparseable_decision": "escalate"}
    )


def _r2_forbid(program: str) -> dict[str, Any]:
    return {"name": f"no-{program}", "pattern": [program], "decision": "forbid", "justification": "r2", "alternative": "other"}


def _r2_pinned(program: str, pin: str) -> dict[str, Any]:
    return {"name": f"{program}-ok", "pattern": [program], "decision": "allow", "justification": "r2", "host_executable": [pin]}


def test_r2_computed_value_is_not_one_allowed_segment() -> None:
    # The review's executed chain: a policy forbidding `secondary` allowed `receiver.cmd $env:CP_WORD`, and both
    # PowerShell versions ran secondary.cmd. Now the line cannot be read, so it escalates.
    config = _r2_policy(_r2_forbid("secondary"))
    assert evaluate_command(config, "receiver.cmd alpha", dialect="powershell").decision == "allow"  # control
    assert evaluate_command(config, "secondary.cmd", dialect="powershell").decision == "forbid"  # control
    result = evaluate_command(config, "receiver.cmd $env:CP_WORD", dialect="powershell")
    assert result.unparseable is not None and _R2_COMPUTED in result.unparseable
    assert result.decision == "escalate"


# The literal of Section 3's r2 names, including forfiles and start, which moved out of the cmd-only set: 87.
R2_LAUNCHERS = (
    "mintty", "winpty", "wt", "windowsterminal", "conhost", "openconsole", "conemu", "conemu64", "conemuc",
    "conemuc64", "tmux", "screen", "byobu", "dtach", "abduco", "unbuffer", "socat", "rlwrap", "openvt", "xterm",
    "uxterm", "gnome-terminal", "kgx", "ptyxis", "konsole", "xfce4-terminal", "mate-terminal", "lxterminal",
    "qterminal", "terminator", "tilix", "urxvt", "rxvt", "st", "foot", "footclient", "kitty", "alacritty", "wezterm",
    "wezterm-gui", "ghostty", "terminology", "sakura", "x-terminal-emulator",
    "psexec", "psexec64", "paexec", "gsudo", "winrs", "wmic", "schtasks", "at", "batch", "mosh", "rsh",
    "start-stop-daemon", "daemonize", "chpst", "setuidgid", "envdir", "envuidgid", "softlimit", "prlimit", "cgexec",
    "systemd-nspawn", "xvfb-run", "dbus-launch", "dbus-run-session", "faketime", "fakeroot", "proot", "torsocks",
    "proxychains", "proxychains4", "tsocks", "entr", "catchsegv", "caffeinate", "sandbox-exec", "arch",
    "explorer", "rundll32", "pcalua", "xdg-open", "open", "forfiles", "start",
)


def test_r2_launcher_literal() -> None:
    assert len(R2_LAUNCHERS) == 87
    assert len(set(R2_LAUNCHERS)) == 87


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize("name", R2_LAUNCHERS)
def test_r2_launchers_are_opaque(name: str, dialect: Dialect) -> None:
    _accepted("pytest -e python x", dialect)  # control: an ordinary program with the same arguments is read
    parsed = parse_command(f"{name} -e python x", dialect=dialect)
    assert parsed.unparseable is None, parsed.unparseable  # premise: the line reads; the segment is what is refused
    (segment,) = parsed.segments
    # cmd reads `start-stop-daemon` as its internal `start` first; every other case is the launcher reason
    expected = "may split" if (dialect, name) == ("cmd", "start-stop-daemon") else "runs a command the policy cannot see"
    assert segment.unparseable is not None and expected in segment.unparseable, segment.unparseable
    assert evaluate_command(_r2_policy(_r2_forbid("python")), f"{name} -e python x", dialect=dialect).decision == "escalate"


def test_r2_terminal_child_is_not_allowed() -> None:
    # The review's executed forms (cmd and PowerShell 5.1 started python through mintty while the policy allowed it).
    config = _r2_policy(_r2_forbid("python"))
    mintty = '"C:\\Program Files\\Git\\usr\\bin\\mintty.exe"'
    tail = " -w hide -h never -e python C:\\w\\terminal_marker.py tag push --force"
    assert evaluate_command(config, "python x", dialect="cmd").decision == "forbid"  # control
    for dialect, command in (("cmd", mintty + tail), ("powershell", "& " + mintty + tail), ("posix", "mintty -e python x")):
        result = evaluate_command(config, command, dialect=dialect)
        assert result.unparseable is None, (dialect, result.unparseable)
        (verdict,) = result.segments
        assert verdict.basis == "unparseable" and "runs a command the policy cannot see" in str(verdict.segment.unparseable)
        assert result.decision == "escalate", dialect


R2_LOOKUP_LINES: list[tuple[str, Dialect, str, str, str]] = [
    # (id, dialect, command, pinned program, its pin) -- review r2 executed the first two on 5.1 and 7, and posix_read
    ("ps_environment_provider", "powershell", "Set-Item Environment::PATH C:\\other; selected", "selected", "C:\\pins\\selected.cmd"),
    ("ps_colon_parameters", "powershell", "Set-Item -Path:Env:PATH -Value:C:\\other; selected", "selected", "C:\\pins\\selected.cmd"),
    ("ps_file_on_path", "powershell", "Copy-Item C:\\evil\\selected.cmd C:\\tools\\selected.cmd; selected", "selected", "C:\\pins\\selected.cmd"),
    ("ps_mutation_after", "powershell", "selected; Set-Item Environment::PATH C:\\other", "selected", "C:\\pins\\selected.cmd"),
    ("ps_pipeline", "powershell", "Get-ChildItem | selected", "selected", "C:\\pins\\selected.cmd"),
    ("cmd_file_in_working_directory", "cmd", "copy C:\\evil\\git.exe git.exe & git status", "git", "C:\\pins\\git.exe"),
    ("posix_read", "posix", "read PATH < /dev/null; git status", "git", "/usr/bin/git"),
    ("posix_printf_v", "posix", "printf -v PATH /tmp/x; git status", "git", "/usr/bin/git"),
    ("posix_builtin_true", "posix", "true; git status", "git", "/usr/bin/git"),
    ("posix_substitution", "posix", "echo $(git status)", "git", "/usr/bin/git"),
    ("posix_wrapped_script", "posix", "sh -c 'read PATH; git status'", "git", "/usr/bin/git"),
]


@pytest.mark.parametrize(
    ("dialect", "command", "program", "pin"), [pytest.param(*row[1:], id=row[0]) for row in R2_LOOKUP_LINES],
)
def test_r2_another_segment_leaves_a_pinned_name_unproven(dialect: Dialect, command: str, program: str, pin: str) -> None:
    config = _r2_policy(_r2_pinned(program, pin))
    resolve = {program: pin}.get
    alone = evaluate_command(config, program, dialect=dialect, resolve_program=resolve)  # control: one segment proves
    assert alone.decision == "allow"
    result = evaluate_command(config, command, dialect=dialect, resolve_program=resolve)
    assert result.unparseable is None
    pinned = [verdict for verdict in result.segments if verdict.segment.tokens[:1] == (program,)]
    assert len(pinned) == 1, [verdict.segment.tokens for verdict in result.segments]
    (verdict,) = pinned
    assert verdict.segment.unparseable is None  # premise: read, so the forbid below is the lookup rule
    assert verdict.segment.lookup_changed is not None and _R2_ANOTHER in verdict.segment.lookup_changed
    (match,) = verdict.matches
    assert (match.decision, match.pin_violation) == ("forbid", True)
    assert _R2_ANOTHER in match.justification
    assert result.decision == "forbid"


def test_r2_an_absolute_path_keeps_its_proof_in_a_longer_line() -> None:
    config = _r2_policy(_r2_pinned("git", "/usr/bin/git"))
    result = evaluate_command(config, "read PATH < /dev/null; /usr/bin/git status", dialect="posix")
    assert result.segments[1].segment.lookup_changed is not None  # premise: the context is unproven
    assert result.decision == "allow"


def test_r2_a_posix_path_with_dotdot_proves_no_pin() -> None:
    control = _r2_policy(_r2_pinned("git", "/usr/bin/git"))
    assert evaluate_command(control, "/usr/bin/git status", dialect="posix").decision == "allow"  # control
    assert evaluate_command(control, "/usr/local/../bin/git status", dialect="posix").decision == "forbid"
    by_resolver = evaluate_command(control, "git status", dialect="posix", resolve_program={"git": "/usr/local/../bin/git"}.get)
    assert by_resolver.decision == "forbid"
    dotted_pin = _r2_policy(_r2_pinned("git", "/opt/../usr/bin/git"))  # a '..' pin proves nothing, even against '..'
    assert evaluate_command(dotted_pin, "/x/../usr/bin/git status", dialect="posix").decision == "forbid"


R2_IDENTITY: list[tuple[str, Dialect, str, str, str]] = [
    # (id, dialect, an unproven spelling, the bare name, an absolute path a resolver may answer for the name)
    ("ps_dot_backslash", "powershell", ".\\selected", "selected", "C:\\pins\\selected.exe"),
    ("ps_dot_slash", "powershell", "./selected", "selected", "C:\\pins\\selected.exe"),
    ("ps_parent", "powershell", "sub\\..\\selected", "selected", "C:\\pins\\selected.exe"),
    ("ps_drive_relative", "powershell", "C:selected", "selected", "C:\\pins\\selected.exe"),
    ("ps_root_relative", "powershell", "\\tools\\selected", "selected", "C:\\pins\\selected.exe"),
    ("cmd_dot_backslash", "cmd", ".\\selected", "selected", "C:\\pins\\selected.exe"),
    ("cmd_parent", "cmd", "sub\\..\\selected", "selected", "C:\\pins\\selected.exe"),
    ("posix_dot_slash", "posix", "./selected", "selected", "/usr/bin/selected"),
    ("posix_parent", "posix", "sub/../selected", "selected", "/usr/bin/selected"),
    ("posix_absolute_parent", "posix", "/opt/x/../selected", "selected", "/usr/bin/selected"),
]


@pytest.mark.parametrize(
    ("dialect", "spelled", "bare", "answer"), [pytest.param(*row[1:], id=row[0]) for row in R2_IDENTITY],
)
def test_r2_unproven_program_paths_have_script_keys(dialect: Dialect, spelled: str, bare: str, answer: str) -> None:
    # The review: `selected` and `.\selected` shared a key under every resolver exit, yet ran different programs.
    for resolve in (None, {}.get, lambda name: None, {bare: answer}.get):
        name = canonical_command(f"{bare} a", dialect=dialect, resolve_program=resolve)
        assert name.kind == "argv"  # control
        path = canonical_command(f"{spelled} a", dialect=dialect, resolve_program=resolve)
        assert (path.kind, path.dialect, path.parts) == ("script", dialect, (f"{spelled} a",))
        assert path.key != name.key


def test_r2_absolute_paths_keep_argv_identity() -> None:
    windows = canonical_command("C:\\x\\..\\pins\\selected.exe a", dialect="cmd")  # Windows resolves '..' in the text
    assert (windows.kind, windows.parts) == ("argv", ("c:\\pins\\selected.exe", "a"))
    assert canonical_command("\\\\srv\\share\\selected.exe a", dialect="cmd").kind == "argv"  # a UNC path
    assert canonical_command("/usr/./bin/selected a", dialect="posix").parts == ("/usr/bin/selected", "a")


def test_r2_a_name_is_keyed_as_written() -> None:
    for dialect in ("cmd", "powershell"):
        plain = canonical_command("git status", dialect=dialect)
        assert plain.parts == ("git", "status")  # control
        assert canonical_command("GIT status", dialect=dialect).key == plain.key  # Windows names fold case
        assert canonical_command("git.exe status", dialect=dialect).key != plain.key  # PATHEXT may find git.cmd first
        assert canonical_command("git.cmd status", dialect=dialect).key != canonical_command("git.exe status", dialect=dialect).key
    assert canonical_command("Git status", dialect="posix").key != canonical_command("git status", dialect="posix").key
    # a resolver's relative or POSIX '..' answer is no identity: the key stays the name
    relative = canonical_command("git status", dialect="cmd", resolve_program={"git": "bin\\git.exe"}.get)
    assert relative.parts == ("git", "status")
    dotted = canonical_command("git status", dialect="posix", resolve_program={"git": "/opt/x/../bin/git"}.get)
    assert dotted.parts == ("git", "status")
```

`Any` is already imported (`:29`). `CommandPolicyConfig` is already imported (`:33`).

### Part C -- appended to `tests/test_ad1328_s1_shell_oracle.py` (F6; adapted from the review's `test_oracle_refusal_property.py`)

Add `from dataclasses import replace` to the imports.

```python
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
```

Run at `-n 0`: the four `test_ad1328_s1_*` parse, repair, evaluation and oracle files. All must pass (POSIX live rows skip on Windows).

## Mutation campaign (rows added; anchors are single lines and unique after r2)

`command_policy.py` changes, so the r1 rule applies: the whole `command_policy.py` campaign (M01-M120 as amended below, plus M121-M143) is rerun on the committed tree. M144 runs against the oracle test. Record the base commit and the sha256 of each file.

| Id | File | Anchor | Mutant | Killer |
|---|---|---|---|---|
| M121 | command_policy.py | `raise _Unparseable(_PS_COMPUTED)  # r2: the value reaches the program without the quoting the policy reads` | `self._mark_dynamic(variadic=True); self.i = end` | `r2_ps_*variable*`, `r2_ps_interpolated*`, `r2_ps_concatenated_*`, `r2_ps_call_variable*`, `r2_ps_redirect_variable`, `r2_cmd_wrapped_variable`; `test_r2_computed_value_is_not_one_allowed_segment` |
| M122 | command_policy.py | `raise _Unparseable(_PS_COMPUTED)  # r2: a splat passes computed values` | `self._mark_dynamic(variadic=True); self.i += 2` | `r2_ps_splat`, `r2_ps_splat_then_words` |
| M123 | command_policy.py | `raise _Unparseable(_PS_COMPUTED)  # r2: pwsh 7 puts the home directory here itself` | `self._mark_dynamic(variadic=True)` | `r2_ps_tilde`, `r2_ps_tilde_path` |
| M124 | command_policy.py | `if ch == "~" and self._start < 0:` | `if ch == "~":` | ARITY powershell (`a~b`); usability `git diff HEAD~1` (powershell); oracle S01 |
| M125 | command_policy.py | `if ch in "*?":` | `if False:` | `R1B_READINGS` `s19_glob_then_escaped_blank` (rule G does not mark a word with a blank) |
| M126 | command_policy.py | `raise _Unparseable(_PS_COMPUTED)  # r2: as a bare leading '~'` | `self._mark_dynamic(variadic=True)` | `r2_ps_escaped_tilde*` |
| M127 | command_policy.py | `elif len(segments) > 1:` | `elif False:` | LOOKUP `posix_control`, `cmd_control`, `ps_control`; SHELL_WRAPPERS `posix_sh_c_two_commands`; `test_r2_another_segment_leaves_a_pinned_name_unproven` |
| M128 | command_policy.py | same | `elif True:` | LOOKUP `*_single_control`, `cmd_powershell_noprofile_control`; usability single-segment rows |
| M129 | command_policy.py | same | `elif len(segments) > 2:` | the two-segment rows of M127 |
| M130 | command_policy.py | `if mutator is not None:` | `if False:` | LOOKUP mutator rows (the cause names the program); evaluation `test_pin_proof_needs_the_starting_lookup_context` (`(cd)`) |
| M131 | command_policy.py | `if wrappers and words and words[0].assignment:` | `if False:` | `r2_time_*`, `r2_*_assignment` |
| M132 | command_policy.py | same | `if wrappers and words:` | `R2_READINGS` `r2_time_program`; parse `test_process_wrappers` |
| M133 | command_policy.py | `return None if ".." in path.split("/") else posixpath.normpath(path)` | `return posixpath.normpath(path)` | `test_r2_a_posix_path_with_dotdot_proves_no_pin`; `posix_absolute_parent`; evaluation `:429` (amended) |
| M134 | command_policy.py | `return program if dialect == "posix" else program.lower()` | `return posixpath.basename(program) if dialect == "posix" else windows_program_stem(program)` | `test_r2_a_name_is_keyed_as_written` (`git.exe`, `git.cmd`) |
| M135 | command_policy.py | same | `return program` | `test_r2_a_name_is_keyed_as_written` (`GIT`) |
| M136 | command_policy.py | `return path.startswith("/") if dialect == "posix" else _WINDOWS_ABSOLUTE.match(path) is not None` | `return True` | `test_r2_unproven_program_paths_have_script_keys`; `test_r2_a_name_is_keyed_as_written` (`bin\git.exe`) |
| M137 | command_policy.py | `_WINDOWS_ABSOLUTE: Final = re.compile(r"[A-Za-z]:[\\/]\|[\\/]{2}[^\\/]")` | `_WINDOWS_ABSOLUTE: Final = re.compile(r"[A-Za-z]:\|[\\/]")` | `ps_drive_relative`, `ps_root_relative` |
| M138 | command_policy.py | `return _path_key(program, segment.dialect) if _is_absolute(program, segment.dialect) else None` | `return _path_key(program, segment.dialect)` | `test_r2_unproven_program_paths_have_script_keys` (relative rows) |
| M139 | command_policy.py | `if resolved is not None and _is_absolute(resolved, segment.dialect):` | `if resolved is not None:` | `test_r2_a_name_is_keyed_as_written` (`bin\git.exe`) |
| M140 | command_policy.py | `if key is not None:` | `if True:` | `test_r2_a_name_is_keyed_as_written` (`/opt/x/../bin/git`) |
| M141 | command_policy.py | `if program is not None:` | `if True:` | `test_r2_unproven_program_paths_have_script_keys` |
| M142 | command_policy.py | `pinned = {_path_key(pin, segment.dialect) for pin in rule.host_executable} - {None}  # r2: a pin with '..' proves nothing` | `pinned = {_path_key(pin, segment.dialect) for pin in rule.host_executable}` | `test_r2_a_posix_path_with_dotdot_proves_no_pin` (dotted pin) |
| M143 | command_policy.py | each r2 name in Section 3 (87 sub-rows; the name occurs once on an r2 line) | delete `"<name>", ` from that line | `test_r2_launchers_are_opaque[<name>-*]` (`start`: the cmd and posix cases; PowerShell keeps its own `start`) |
| M144 | tests/test_ad1328_s1_shell_oracle.py | `unreadable = [segment.unparseable for segment in parsed.segments if segment.unparseable is not None]` | `... for segment in segments ...` | `test_reading_problem_fails_a_refused_non_probe_segment[P11, P17]` |
| M88 (re-anchored) | command_policy.py | `key = _path_key(resolved, segment.dialect)` | `key = _program_name(program, segment.dialect)` | parse `test_canonical_program_resolution` |
| M108 (killer amended) | command_policy.py | unchanged | `if False:` | `r2_ps_escaped_tilde*` (the `~` reads as a literal) |
| M99 (killer amended) | command_policy.py | unchanged | unchanged | the 9 rewritten `r1b_ps_dynamic_*` rows with a wildcard word (not `_provider_after_variable`, `_dashdash`) |
| M100 (killer amended) | command_policy.py | unchanged | unchanged | `R1B_READINGS` `dynamic_number_like` |
| M103 (killer amended) | command_policy.py | unchanged | unchanged | `r1c_ps_colon_empty`, `_parameter_argument` |

**Retired:** M11 (its anchor `if mutator is None:` is gone; M130 and M127-M129 replace it).

**Equivalent mutants, not listed:**
- `if words and words[0].assignment:` for M131's anchor: leading assignments are already popped, so only a wrapper can leave one at the front.
- `if not value:` for r1b's `if whole and not value:`: after r2, no PowerShell dynamic word has empty literal text.

No mutant above can loop. M121 and M122 restore an advancing cursor, and every other mutant falls through to a branch that advances it or returns.

## Closure enumeration

| F | Producer or exit | Closed by |
|---|---|---|
| F1 | `_variable`: plain, digit, special `?^$`, scoped `x:y`, braced `${x}`/`${x:y}`; unquoted, in double quotes, concatenated before or after literal text | Section 7c |
| F1 | `_variable`: `$(`, unmodelled `${`, member access or indexing, any other `$` | Already refused (r1), with their own reasons, before 7c |
| F1 | `_splat` `@name` | Section 7d. `@(`, `@{`, here-strings, `@?` and the like are already refused by its first check |
| F1 | bare leading `~` in `lex`; escaped leading `` `~ `` in `_escape` | Sections 7a and 7b |
| F1 | `~` mid-word, after `=` or `:`, or inside quotes | Literal: PowerShell does not expand it (S22 measured `` a`~b ``). A quoted leading `~` is rule G variadic (callee) |
| F1 | Wildcards: bare `*?`, rule G (`_end_word`) | Unchanged: the callee expands them into its own argv, and nothing re-parses that (r1e) |
| F1 | Redirection target, `-name:` argument, call operator target, wrapped `-Command` script | Each lexes through the same `_variable`/`_splat`/`lex`, so they are refused too (rows `r2_ps_redirect_variable`, `r2_ps_call_variable*`, `r2_cmd_wrapped_variable`, `r1c_ps_colon_variable`) |
| F1 | cmd `%`, `!`, `for` | Already refused (r1) |
| F1 | posix `$`, `$(...)`, globs, `~` | Hold: `execve` transport (review r2 held them); a POSIX shell is not reachable on Windows (D-r2-1) |
| F2 | separators `; & && \|\| \|` and newline (each dialect's lexer), POSIX substitution bodies (`_emit` subs), unwrapped wrapper scripts (`_unwrap`) | All reach `parse_command` -> `_with_lookup_context` (Section 10): two or more segments -> `_ANOTHER_COMMAND` |
| F2 | Known mutators (`_STATE_MUTATORS`, drive change) | Unchanged reason (Section 10, first branch) |
| F2 | Single segment: own assignments | `_match` refuses `allow` with assignments (`:1513`) |
| F2 | Single segment: inherited assignments, `command -p`, login shell, profile | Unchanged (r1 R4) |
| F2 | Single segment: in-segment expression | Refused: `(`, `$(`, `@(` (r1) |
| F2 | Exit: `_allow_match` bare name | Violation with `_ANOTHER_COMMAND` in the justification |
| F2 | Exit: `_allow_match` path | Its own proof (`test_r2_an_absolute_path_keeps_its_proof_in_a_longer_line`) |
| F2 | Exit: `_is_simple` | Script (already, for any multi-segment line) |
| F2 | Exit: restrictive rules | Unaffected |
| F3 | `_launcher_problem` (every dialect, `windows_program_stem`) | Section 3 |
| F3 | `_shell_wrapper` shells | Unchanged |
| F3 | `_PROCESS_WRAPPERS` spelled outside posix | Unchanged (M52) |
| F3 | Subcommand launchers | Unchanged |
| F4 | `_strip_process_wrappers` (posix only; other dialects refuse the wrapper names) | Section 9: assignment after a wrapper -> refused |
| F4 | Dynamic word after a wrapper | Already refused (`_wrapper_width`, `:1148`) |
| F4 | Option after a wrapper | Already refused (`:1135`) |
| F4 | Quoted name (`"X"=1`) | Read as the program, as bash runs it (`r2_time_quoted_name_is_the_program`) |
| F5 | argv[0] written as an absolute path | `_path_key` (POSIX `..` -> None -> script) |
| F5 | argv[0] written as a relative path | Script (Section 11b) |
| F5 | Bare name + resolver absolute | Path key, unless POSIX `..` |
| F5 | Bare name + resolver relative, None, `{}`, omitted | The name as written (`_program_name`) |
| F5 | Resolver non-str | `TypeError` (unchanged) |
| F5 | Pin compare | `_path_key` on pins and program; None is never in the pinned set (11a) |
| F6 | `_reading_problem` | Every `parsed.segments` (Part A); used by both the every-host and live row tests |

## Amendments (what r2 overrides)

| Earlier text | r2 |
|---|---|
| r1 R3 launcher table; cmd-only `start`, `forfiles` | 85 names added, `start`/`forfiles` shared (Section 3) |
| r1 R4: only state mutators, login shell, profile and `command -p` change the lookup context | And any other segment of the line (Section 10) |
| r1 R5 canonical program: "normalised resolved path ... else its normalised name" | Absolute paths only; POSIX `..` none; the name as written (Sections 6, 8, 11) |
| r1 mutation M11, M88 | M11 retired; M88 re-anchored |
| r1b blind spot "a variable's runtime value containing `"` ... is covered because the word is variadic" | Refuted by review r2 F1; every PowerShell variable is refused |
| r1b Class B rows `r1b_ps_dynamic_*`, `R1B_READINGS` `s19_after_variable`, `dynamic_empty_text`, `dynamic_dash_text`; killers of M99 and M100 | Rewritten (Part A) |
| r1c `r1c_ps_colon_variable` reason; M103 killers | Part A |
| r1d Class E (an escaped leading `~` is dynamic), `R1D_READINGS` `e_escaped_tilde*`, S22; M108 killer | Refused (7b); rows moved to `r2_ps_escaped_tilde*` |
| r1e closure row "PS `$`, splat: dynamic"; blind spot "a variable value that holds a wildcard is dynamic already" | Refused (7c, 7d) |
| r1 R6 oracle: a row fails on a refused **probe** segment | On any refused segment (F6) |
| Oracle S08, S11, S12, S19, S22 | Section 12 |

## Hidden pins (enumerated)

| Id | Pin | Command | Effect here |
|---|---|---|---|
| H1 | Existing tests that read a PowerShell variable, splat or leading `~`, a multi-segment `lookup_changed is None`, or a POSIX `..` pin | Grep listed in Absence A1, A3 | Part A, every row named |
| H2 | Oracle rows | `tests/fixtures/ad1328_shell_oracle.json:68, :71-72, :78-79, :82` | Section 12. Live re-run after install |
| H3 | S2a starter: 9 examples under all three dialects | `prompts/ad-1328-s2a-command-policy-wiring.md:1186-1193` | None uses `$`, `@`, a leading `~`, a relative program, an r2 launcher, `time X=` or two segments: they hold |
| H4 | S2a tests | Grep `\$env:\|@args\|\./` and `powershell` in the S2a prompt | No match. Pinned tests are single-segment `git status` (`:1249-1272`): unaffected |
| H5 | S2b approval key | `prompts/ad-1328-s2b-command-policy-escalation.md:7, :133` (`canonical_key` length 64) | Same API and length. Keys change only for the forms in D-r2-4. Nothing is persisted |
| H6 | AST purity scan | `test_ad1328_s1_policy_evaluation.py:1253-1294` (`ast.Name` only) | The string `"open"` in Section 3 is a constant, not a Name: holds |
| H7 | Refusal-table counts 108, 16, 17, 13, 2 | `...repair.py:287, :797, :865, :924, :980` | Unchanged: rows are rewritten, not removed |
| H8 | Usability corpus 93 rows | `...repair.py:745-746` | Unchanged count; only `_CONTEXT_CHANGING` grows |

## What This Does NOT Change

Public API names and signatures (`_canonical_program` and `_path_key` are private), `CANONICAL_KEY_SCHEME`/`POLICY_DIGEST_SCHEME`, `operations.py`, cmd and posix lexing, R2 matching, wildcard marks, S2a, S2b.

## Tracking

DECISIONS.md (Section 13). No PROGRESS or roadmap change (same AD, same PR).

## Acceptance Criteria

- Sections 1-13 are installed exactly, then Parts A to C. The four focused files pass at `-n 0`.
- The orchestrator re-runs the cmd and PowerShell oracle rows live under cmd, `powershell` and `pwsh`, then the review's `boundary_probes.py`. Each of its five probes must now fail its own "bypass" assertion, because the decision is no longer `allow`. Then the differential harness.
- M121-M144 are each killed, the amended killers hold, and the rest of the `command_policy.py` campaign is rerun.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-10-16, blobs above)

```
command_policy.py:90        _DRIVE_CHANGE: Final = re.compile(r"[A-Za-z]:")            (Section 1 anchor, once)
command_policy.py:131       _PS_PROVIDER_PREFIXES ... ("alias:", "function:", "env:", "variable:")
command_policy.py:154-163   _LAUNCHERS_EVERYWHERE ... "cmd": _LAUNCHERS_EVERYWHERE | {"call", "start", "forfiles", "doskey"},
command_policy.py:193-199   _STATE_MUTATORS (posix cd declare export hash local popd pushd readonly set typeset unset)
command_policy.py:207       _DEFAULT_PATH
command_policy.py:269-272   CommandSegment docstring, lookup_changed
command_policy.py:401-406   CanonicalCommand docstring
command_policy.py:787-790   lex: if ch in "*?" or (ch == "~" and self._start < 0): ... self._literal(ch, quoted=False)
command_policy.py:804-806   _escape: escaped leading tilde -> _mark_dynamic
command_policy.py:857-882   _variable; :879-882 member check, _mark_dynamic, self.i = end
command_policy.py:884-892   _splat
command_policy.py:929-937   r1e _end_word (rule G)
command_policy.py:988       default_dialect: "cmd" on win32
command_policy.py:999-1008  _program_name, _is_path, _path_key
command_policy.py:1117-1140 _strip_process_wrappers; :1148-1149 dynamic word after a wrapper -> None
command_policy.py:1221-1235 _launcher_problem (windows_program_stem; keywords, launchers, wrappers, subcommands)
command_policy.py:1249-1250 a POSIX shell from cmd/PowerShell is refused
command_policy.py:1361-1367 _with_lookup_context
command_policy.py:1513      if len(tokens) < len(rule.pattern) or segment.assignments:
command_policy.py:1537-1546 _allow_match: lookup_changed -> _pin_violation; pinned = {...}
command_policy.py:1744-1751 _canonical_program; :1774-1777 canonical_command tail
operations.py:121-127       pins: absolute ('/', '\\\\', 'X:\'), stem must name the program
oracle test:131-137         _reading_problem (the probe-only filter at :135)
oracle test:57-61, :84-97   _SYNTHETIC, _prefix, _substitute (absolute prefixes: no relative program)
fixture:68, :71-72, :78-79, :82, :11-13   S08, S11-S12, S18-S19, S22, verified_on
DECISIONS.md:21             "... the set cmd already uses. Contracts `...r1.md` to `...r1e.md`."   (1 occurrence)
review2-evidence/boundary_probes.py:33-87   the five executed probes (commands reused in Part B)
```

## Absence Verified (2026-10-16)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A1 | Every existing test that reads a PowerShell `$`/`@` word is in Part A | Grep `"powershell".*(\$[A-Za-z_{?^$]\|@[A-Za-z_])` and `(\$[A-Za-z_{?^(]\|@[A-Za-z]+[ "']\|(\s\|`)~)` in `tests/` | parse `:460, :467` (literal: quoted or escaped, unchanged), `:477-479, :484-486, :551, :632-633`; eval `:802-803`; repair `:142-147, :364, :779-791, :815-818, :847, :913` (escaped, unchanged), `:918, :938-945`; fixture S02-S04 (literal), S08, S11, S19, S22, S24 (quoted, unchanged) | yes |
| A2 | No usability or starter command uses `$`, `@name`, a leading PowerShell `~`, a relative program, an r2 launcher or `time X=` | Read `...repair.py:625-724`; S2a `:1186-1193`; Grep launcher names in `tests/` | none (`HEAD~1` is mid-word) | yes |
| A3 | Only the listed tests assert `lookup_changed is None` | Grep `lookup_changed` in `tests/` | parse `:891` (SHELL_WRAPPERS), eval `:882, :904` (one segment), repair `:448` (LOOKUP), `:761` (usability) | yes |
| A4 | `_program_name` and `_path_key` have no other callers; no test imports them | Grep `_path_key\(\|_program_name\(` in `src/`; the import blocks in `tests/` | `:1542-1543, :1747, :1750-1751`; tests import public names only | yes |
| A5 | No hard-coded agent command uses a PowerShell variable | Grep `\$[A-Za-z{(]\|@[a-z]+\b\|~[/\\]` in `red_team.py`, `shell_command.py` | decorators only | yes |
| A6 | No test pins the stem merge of a Windows name in a canonical key | Grep `canonical_command\(\|\.canonical\(` in `tests/` | every Windows call uses an absolute path, a resolver, or `git` | yes |

## Not verified

- No shell was run here (the bridge allows no shell other than its listed git, gh and pytest prefixes). These are claimed from documents or from the review and are not re-measured:
  - pwsh 7 quoting of a home path that holds `&` for a batch file. The refusal does not depend on it.
  - The `copy ... & git` cmd working-directory case.
  - The POSIX `..`-after-symlink rule (POSIX pathname resolution).
  - `PATHEXT` order for `git` versus `git.exe`.
- The staged tree id `ce7d2c01...` was not recomputed (`git write-tree` is denied). The blobs above come from `git ls-files -s`.

## Prior Art and Blind Spots

A repair of a reviewed grammar: no external search. The decisions follow measured behaviour (review r2, r1d, r1e), and `docs/research/reference-projects.md` was not consulted. Blind spots, considered and deferred:

1. `BASH_ENV` for an unwrapped `bash -c`. It belongs to the starting environment, which S2a's resolver and BF-890 (#1529, environment scrubbing) own.
2. A cmd redirection (`git status > git.exe`) creates an empty file in the working directory before cmd searches it. An empty file runs nothing.
3. NTFS per-directory case sensitivity. Names and paths fold case, as the pins do (r1 R5).
4. A POSIX pin containing `..` never proves anything, so its rule's self-test fails at startup, naming the rule.
5. pwsh off Windows globs for native commands. The variadic mark covers it.
6. Program-defined launching (`git -c core.sshCommand`, `make`) stays the r1 boundary.

=== BUILDER BRIEFS ===

### Brief R2-M2 -- tests (effort: high, at most 120 calls)

Contract: `prompts/ad-1328-s1-repair-r2.md`. The source and fixture are installed and frozen: edit nothing under `src/` or `tests/fixtures/`.

1. Apply Part A exactly, row by row. Each edit changes only the named row or comment.
2. Append Part B to `tests/test_ad1328_s1_command_parse_repair.py` after the R1E block.
3. Append Part C to `tests/test_ad1328_s1_shell_oracle.py`, adding the `replace` import.
4. Run `test_ad1328_s1_command_parse.py`, `test_ad1328_s1_command_parse_repair.py`, `test_ad1328_s1_policy_evaluation.py` and `test_ad1328_s1_shell_oracle.py` with `-n 0`.

If a premise assertion fails, stop and report the case and the observed value. Do not weaken an assertion or change a reason substring. Report the counts and the skips with their reasons.

### Brief R2-M3 -- mutation campaign (effort: high, at most 150 calls)

Use the committed R2-M2 tree. Run the baseline green first. Count each anchor: it must occur exactly once (M143: each name once on its r2 line). Apply one mutant at a time, with a `.mutbak` restore in `finally`, and run the four files serially. Record the base commit, the sha256 of `command_policy.py` and of the oracle test, and each result as KILLED / INERT / INVALID with its killer. Rerun r1's `command_policy.py` rows with the amended killers. If a mutant survives, stop and report it with the test that should have killed it. Do not edit source or the table.

## Amendments after install (2026-10-16, orchestrator; none changes a decision)

- **A1 (Part A omitted a row).** `tests/test_ad1328_s1_policy_evaluation.py::test_command_policy_surface` evaluated `git status && bash -c 'git push --force origin'` under a policy that pins `git`, and expected `["allow", "forbid"]`. Under D-r2-2 (the stated cost: "a pinned program in a multi-segment line must be written as its absolute path") both segments now lose their pin proof, so the line gives `["forbid", "forbid"]` and `governing` also names the pin violation. Absence A3 had grepped `lookup_changed` assertions, not decisions that depend on the proof. Changed without weakening: the chain uses `/usr/bin/git` in both segments (decisions `["allow", "forbid"]` and `governing` the `no-force` rule alone, observed), and a companion asserts the bare spelling's F2 outcome (`["forbid", "forbid"]`, two `git-ok` pin violations, the agent told "run the pinned executable: /usr/bin/git" besides "use the governed path"). The R2-M2 Builder stopped on it as instructed.
- **A2 (counts at install).** Before R2-M2: 47 existing cases failed (all Part A rows, the six `test_usability_corpus` rows only on the `lookup_changed` expectation). After: the five `test_ad1328_s1_*` files give 1,209 passed, 53 skipped (the POSIX live oracle rows, off Windows only), 0 failed; the S1 total before r2 was 887.
- **A3 (closure checked by the orchestrator).** The review's five bypass probes (`review2-evidence/boundary_probes.py`) no longer reproduce, and `files/probe_r2_closure.py` (which prints the policy's own decision, with allowed controls first) shows every F1-F5 form refused or script-keyed. S2a's 166 tests pass against this module unchanged (no S2a amendment).
- **A4 (differential harness, at the hardened limits of #1523 F-108).** PowerShell enumeration: 2,660 accepted lines (3,055 under r1e), 0 real mismatches on both shells, every dynamic line admitted; 0 lines accepted now that were not accepted under r1e (r2 only refuses: 395 lines, all with `$`, `@` or a leading `~`).
