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

Programs started by other programs (S1 repair r3). A launcher in this module's
table, a shell it does not unwrap and a subcommand launcher are unparseable wherever
they are the program. Any other program may start a program its arguments name, so
restrictive rules also read each argument word as if it began a command: when a
restrictive rule matches from that word (the program's normaliser and matcher), or
the word names a shell, the segment is unparseable and takes ``unparseable_decision``,
or the stricter decision of a rule matching its program. Words an ``allow`` rule's
own pattern names are exempt.

Declared boundary: a prefix rule does not see a program named (a) by a word the
shell computes (a variable, a substitution, a glob) beyond that word's literal text;
(b) inside a larger word: a command string, an option value or a configuration entry
(``hyperfine 'printf x'``, ``--exec=printf``, ``git -c alias.x=!printf``); (c) by
another program's files, interpreters or configuration (``python -c``, ``make``, a
script); (d) by any spelling that running it directly would also escape, such as a
renamed copy of its binary; nor options placed before a subcommand (``git -C .
push``). So a deny-list ``forbid`` (``unmatched_decision: allow``) is best effort. An
allow-list (``unmatched_decision`` ``escalate`` or ``forbid``) is the sound mode: a
program no rule allows is never allowed, though an allowed program keeps whatever
reach it has to start others (#1530, Do Not Build). Nothing here launches a process,
reads the environment or touches a file, and nothing under ``src/`` constructs this
policy yet: AD-1328 S2 wires it before broker admission.
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
# r2: a Windows path that names one file whatever the current drive and directory: 'C:\x', or a UNC or device path.
_WINDOWS_ABSOLUTE: Final = re.compile(r"[A-Za-z]:[\\/]|[\\/]{2}[^\\/]")
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
# r2: PowerShell computes a variable's value (and pwsh 7 the home directory for a leading '~') and builds the program's
# command line from it without the quoting the policy reads: a '"' in the value regroups the neighbouring words on 5.1,
# and a '&' starts another command in a batch file on 5.1 and 7 (review r2, F1, executed).
_PS_COMPUTED: Final = (
    "a value PowerShell computes (a variable, a splat or a leading '~'), which it passes to a program without the "
    "quoting the policy reads"
)
# A bare word that starts with '-' and holds ':' is a parameter and a separate argument token, which PowerShell glues
# back for a program only when that token is a plain name (measured on 5.1 and 7: `-a:` fails to parse, `-a:-b:c`
# splits, `-a:$x` drops).
_PS_COLON_PARAMETER: Final = re.compile(r"-[A-Za-z0-9_.-]*:[A-Za-z_][A-Za-z0-9_.:/\\+=-]*")
# A bare '-' then a name character starts a parameter token: both versions end it at '.' or '[' and pass a later
# backtick literally (measured: `-qq.zz` -> `-qq` `.zz`; `-qq`zz` -> `-qq`zz`).
_PS_PARAMETER_START: Final = re.compile(r"-[A-Za-z_?`]")
_PS_PARAMETER_BREAKS: Final = frozenset(".[`")
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
# r3: every name a shell is known by. Named as an argument it runs a script the policy does not read (review r3, F1).
_ARGUMENT_SHELLS: Final = _POSIX_SHELLS | _PS_SHELLS | _OTHER_SHELLS | {"cmd"}
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
_ANOTHER_COMMAND: Final = "another command in the line runs before or beside this one and may change where it resolves"
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
    find (another command in the line, a directory or environment change, a login
    shell, a PowerShell profile, ``command -p``), or is None.
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
    """The decision for one segment: by ``rule`` match, ``unmatched`` or ``unparseable``.

    r3: when an argument word may start a program a restrictive rule governs, or a shell, the basis is
    ``unparseable`` and ``segment.unparseable`` names the word, its position and the rule. ``matches`` still lists the
    rules that match the segment's program, and ``decision`` is the strictest of theirs and ``unparseable_decision``.
    """

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
    """One example that does not hold for its rule; or (r3, ``expectation`` ``host_executable``) a pinned rule none of
    whose paths can prove its program under the dialect, ``example`` then listing the paths."""

    rule: str
    expectation: Literal["match", "not_match", "host_executable"]
    example: str
    observed: str

    @property
    def message(self) -> str:
        if self.expectation == "host_executable":
            return f"rule {self.rule!r}: host_executable {self.example} {self.observed}"
        return f"rule {self.rule!r}: {self.expectation} example {self.example!r} {self.observed}"


@dataclass(frozen=True)
class SelfTestReport:
    """Every rule's examples, and every pinned rule's paths (r3), judged under one dialect. ``examples_checked``
    counts the examples only."""

    dialect: Dialect
    examples_checked: int
    failures: tuple[SelfTestFailure, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


class CommandPolicySelfTestError(ValueError):
    """A policy whose examples do not hold, or with a pinned rule none of whose paths can prove its program (r3),
    under its dialect; at startup, a startup error."""

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
    its normalised absolute path when it is written as one or the resolver answers
    with one (so ``git`` and ``/usr/bin/git`` share a key), else the name the shell
    looks up as written (case folded on Windows), then the arguments; the dialect is
    not part of it. A relative program path, or a POSIX one with ``..``, has no such
    identity (r2). ``script``: anything else -- the dialect and the exact
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
                if ch == "~" and self._start < 0:
                    raise _Unparseable(_PS_COMPUTED)  # r2: pwsh 7 puts the home directory here itself
                if ch in "*?":
                    self._mark_dynamic(variadic=True)  # the program (or pwsh 7 off Windows) may expand it
                self._literal(ch, quoted=False)
                self.i += 1
        self._end_word()

    def _escape(self) -> None:
        following = self.text[self.i + 1:self.i + 2]
        if not following:
            raise _Unparseable("a trailing '`'")
        if following == "\n":  # PowerShell continues the line, which it reads differently inside a word
            raise _Unparseable("a backtick line continuation")
        if following == " " and self._start < 0:  # measured: 5.1 and 7 read it as a blank, not as part of the word
            raise _Unparseable("an escaped blank ('` ') at the start of a word, which PowerShell reads as a blank")
        if following in _PS_EXPANDING_ESCAPES:
            raise _Unparseable(f"the PowerShell escape '`{following}', which expands to another character")
        if following == "~" and self._start < 0:  # measured: pwsh 7 expands an escaped leading tilde like a bare one
            raise _Unparseable(_PS_COMPUTED)  # r2: as a bare leading '~'
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
        raise _Unparseable(_PS_COMPUTED)  # r2: the value reaches the program without the quoting the policy reads

    def _splat(self) -> None:
        following = self.text[self.i + 1:self.i + 2]
        if not following or _IDENT_START.fullmatch(following) is None:
            raise _Unparseable("an '@' form the policy does not model (an array, a hash table, a here-string or a splat)")
        raise _Unparseable(_PS_COMPUTED)  # r2: a splat passes computed values

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
        value = word.text
        whole = not word.dynamic  # a dynamic word is variadic here: it already stands for any words of any value
        if value == "--" or value.startswith("--%"):
            raise _Unparseable("the -- or --% (stop-parsing) token, which PowerShell versions pass differently")
        if word.raw.startswith("-") and ":" in word.raw and _PS_COLON_PARAMETER.fullmatch(word.raw) is None:
            raise _Unparseable("a '-name:' word whose argument is not a plain name, which PowerShell passes differently")
        head = word.raw.partition(":")[0]
        if _PS_PARAMETER_START.match(head) and any(char in _PS_PARAMETER_BREAKS for char in head[2:]):
            raise _Unparseable("a '.', '[' or '`' after a -name, which PowerShell reads as the end of a parameter")
        if whole and not value:
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
        if whole and word.raw[:1] not in ("'", '"') and _PS_NUMBER_START.match(value) and _PS_INTEGER.fullmatch(value) is None:
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


def _pin_keys(pins: tuple[str, ...], dialect: Dialect) -> frozenset[str]:
    """r3 (review r3, F2, F3): the keys of the pins that can prove a program under ``dialect``. A pin counts only when it
    is absolute there (a POSIX ``/usr/bin/git`` is root-relative to cmd.exe) and normalises (``_path_key``)."""
    return frozenset(key for pin in pins if _is_absolute(pin, dialect) and (key := _path_key(pin, dialect)) is not None)


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
            if dialect == "cmd" and "=" in target.raw:  # measured: cmd.exe ends the target at '=' and passes the rest on
                raise _Unparseable("an '=' in a redirection target, which cmd.exe reads as the end of the target")
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
    if wrappers and words and words[0].assignment:
        # r2: after bash's `time` keyword the assignment is the timed command's own (`time X=1 p` runs p); after the
        # other wrappers it names the program. Neither is read (review r2, F4, executed on bash).
        return (
            f"an assignment ({words[0].raw}) after the process wrapper {wrappers[-1]!r}, "
            "which the policy does not read",
            lookup,
        )
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
    if resolved is not None and not _is_absolute(resolved, segment.dialect):  # r3: a relative path proves no pin
        why = f"{resolved!r} is not an absolute path, so the file it names depends on where the command runs"
        return _pin_violation(rule, prefix, index, resolved, why, paths)
    pinned = _pin_keys(rule.host_executable, segment.dialect)
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


_RestrictiveIndex = dict[str, tuple[CommandPolicyRule, ...]]


def _restrictive_index(config: CommandPolicyConfig) -> _RestrictiveIndex:
    """r3: the restrictive rules by the program name each matches (``windows_program_stem`` of each alternative), in rule
    order; empty when the policy has no restrictive rule."""
    index: dict[str, list[CommandPolicyRule]] = {}
    for rule in config.rules:
        if rule.decision == "allow":  # r3: an allow rule hides nothing
            continue
        for name in dict.fromkeys(windows_program_stem(option) for option in _options(rule.pattern[0])):
            index.setdefault(name, []).append(rule)
    return {name: tuple(rules) for name, rules in index.items()}


def _hidden_program(governed: _RestrictiveIndex, segment: CommandSegment, start: int) -> str | None:
    """r3 (review r3, F1): why an argument word may start a program the policy governs, or None.

    Each word from ``start`` (at least 1: ``_match`` reads the program) is read as if it began a command: its text (a
    dynamic word's literal text) normalised as a restrictive rule normalises a program. The segment is unreadable when
    that name is a shell, or when a restrictive rule for it matches from that word with ``_restrictive_cover``. A
    pattern covers at most its own length of words, so each view is that long and the work is linear in the words.
    """
    tokens = segment.tokens
    for at in range(start, len(tokens)):
        name = windows_program_stem(tokens[at])
        if name in _ARGUMENT_SHELLS:
            return f"argument {at} ({segment.raw[at]}) may be a shell that {tokens[0]!r} starts; the policy does not read what it runs"
        rules = governed.get(name, ())
        if not rules:
            continue
        end = at + max(len(rule.pattern) for rule in rules)
        view = replace(segment, tokens=tokens[at:end], dynamic=segment.dynamic[at:end], variadic=segment.variadic[at:end])
        hit = next((rule for rule in rules if _restrictive_cover(rule.pattern, view) is not None), None)
        if hit is not None:
            return f"argument {at} ({segment.raw[at]}) may be a program that rule {hit.name!r} governs, started by {tokens[0]!r}"
    return None


def _judge(
    config: CommandPolicyConfig,
    segment: CommandSegment,
    index: int,
    unmatched: CommandDecisionName,
    resolve: ProgramResolver | None,
    governed: _RestrictiveIndex,
) -> SegmentVerdict:
    if segment.unparseable is not None:
        return SegmentVerdict(index, segment, config.unparseable_decision, "unparseable", ())
    matches = tuple(found for rule in config.rules if (found := _match(rule, segment, index, resolve)) is not None)
    if governed:
        # r3: the words an allow rule's own pattern names are what the operator allowed; the reading starts after them
        start = max((len(match.matched_prefix) for match in matches if match.decision == "allow"), default=1)
        hidden = _hidden_program(governed, segment, start)
        if hidden is not None:
            decision = _strictest((config.unparseable_decision, *(match.decision for match in matches)))
            return SegmentVerdict(index, replace(segment, unparseable=hidden), decision, "unparseable", matches)
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
    governed = _restrictive_index(config)
    verdicts = tuple(
        _judge(config, segment, index, unmatched, resolve, governed) for index, segment in enumerate(parsed.segments)
    )
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
    and the result does not depend on the host. A pinned rule none of whose
    ``host_executable`` paths is absolute under ``dialect`` fails too (r3): it could
    never allow its program, whether or not it has examples. Never raises for a
    failing example: ``CommandPolicy`` turns a failed report into an error.
    """
    _require_config(config)
    chosen = _dialect(dialect)
    digest = policy_digest(config)
    failures: list[SelfTestFailure] = []
    checked = 0
    for rule in config.rules:
        if rule.host_executable and not _pin_keys(rule.host_executable, chosen):  # r3: review r3, F3
            program = rule.pattern[0]
            failures.append(SelfTestFailure(
                rule.name,
                "host_executable",
                ", ".join(rule.host_executable),
                f"names no absolute path for {_DIALECT_NAMES[chosen]}, so the rule can never allow {program!r} here; "
                f"add the path {program!r} runs from on this platform (one rule may list a POSIX path and a Windows path)",
            ))
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
    ``ValueError``) naming each failing rule and example, or a pinned rule with no
    path absolute under the dialect (r3), so a policy whose examples are wrong, or
    whose pins could never prove, cannot be built; AD-1328 S2 builds it at startup, where a
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
        program = _canonical_program(segment, resolve_program)
        if program is not None:
            return CanonicalCommand("argv", None, (program, *segment.tokens[1:]))
    return CanonicalCommand("script", chosen, (command,))
