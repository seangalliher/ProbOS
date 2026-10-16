"""AD-1328 S2a (#1530): the command execution policy where ``run_command`` executes.

One ``CommandPolicyGate`` per runtime (``ProbOSRuntime.command_policy_gate``), built
in ``ProbOSRuntime.__init__`` from ``execution.command_policy`` and injected into
every place a ``run_command`` executes: ``RunCommandTool`` (``create_subprocess_shell``:
``cmd.exe`` on Windows, ``/bin/sh`` elsewhere), ``ShellCommandAgent`` and the red
team's re-run (Windows PowerShell on Windows, ``/bin/sh`` elsewhere), and, through
``RunCommandTool.command_policy_preflight``, the AD-1316 shell adapter before the
broker reserves anything. Building it runs every rule's examples under each dialect
those sites use (``probos.execution.command_policy.CommandPolicy``), so a wrong
example is a startup error naming the rule.

``judge`` answers for one command as its call site will run it. With no rules it
returns ``NO_POLICY`` at once: nothing is parsed, resolved or recorded, and the
caller takes the path it took before the policy existed. Otherwise it evaluates the
command, computes its canonical approval key with the same memoised resolver (where the
child's shell finds a bare program name: ``cmd.exe`` its working directory, then PATH, in
PATHEXT order; ``/bin/sh`` PATH; PowerShell never, because it runs an alias, function or
cmdlet before any file; and never a name the shell runs itself, a ``cmd.exe`` internal
command or a ``/bin/sh`` built-in -- see ``make_program_resolver``), and
returns a ``CommandGateVerdict``: whether the command runs, the refusal the agent is
told (each cause: rule and justification, the alternative for ``forbid``, or the
reason when no rule decided it), the AD-1316 reason code, and a bounded record for
the AD-1224 tool record that carries no command text.

AD-1328 S2a refuses an ``escalate`` truthfully without asking anyone; S2b routes it
to the AD-1154 approval inbox. The policy only adds gates: it never admits a command
that the permission ladder, consensus or the effect broker would refuse.
"""

from __future__ import annotations

import json
import logging
import ntpath
import os
import posixpath
import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal

from probos.config_models.operations import (
    COMMAND_DECISION_RANK,
    CommandDecisionName,
    CommandPolicyConfig,
)
from probos.execution.command_policy import (
    CanonicalCommand,
    CommandEvaluation,
    CommandPolicy,
    Dialect,
    ProgramResolver,
    SelfTestReport,
    default_dialect,
    policy_digest,
    self_test,
)

logger = logging.getLogger(__name__)

CallSite = Literal["run_command_tool", "shell_command_agent"]
#: The shells a run_command executes in, by call site; ``shell_command_agent`` also
#: names the red team's re-run, which starts the same shell.
CALL_SITES: Final[tuple[CallSite, ...]] = ("run_command_tool", "shell_command_agent")
#: The version of the record a run_command result carries to the AD-1224 tool record.
RECORD_SCHEMA: Final = "probos.command_policy.record/v1"
#: A record's JSON text is at most this long; one AD-1224 record is at most 4,096 bytes.
MAX_RECORD_CHARS: Final = 2048
#: The AD-1316 reason code when the policy could not judge a command before admission.
COMMAND_POLICY_UNAVAILABLE: Final = "command_policy_unavailable"
COMMAND_POLICY_UNAVAILABLE_MESSAGE: Final = (
    "The command policy could not judge this command, so it was not run. "
    "Do not repeat this call; report that the command policy failed on it."
)
_FORBID_FRAME: Final = (
    "The command policy forbids this command, so it was not run. {causes} "
    "Do not repeat it; use the alternative named, or report that this step is blocked."
)
#: AD-1328 S2a: refused without asking anyone. S2b replaces this with the approval inbox.
_ESCALATE_FRAME: Final = (
    "The command policy requires approval from the chain of command before this command "
    "runs, and no approval was requested from here, so it was not run. {causes} Do not "
    "repeat this call; continue with the rest of your task and report that this command "
    "needs approval."
)
_MAX_RECORDED: Final = 8
_MAX_SHOWN: Final = 5
_MAX_REASON_CHARS: Final = 300
_RECORD_KEYS: Final = frozenset({
    "schema", "call_site", "decision", "dialect", "policy_digest", "canonical_key",
    "canonical_kind", "matched_rules", "matched_rules_omitted", "causes", "causes_omitted",
})


def run_command_tool_dialect(platform: str | None = None) -> Dialect:
    """The shell ``asyncio.create_subprocess_shell`` starts: ``cmd`` on Windows, else ``posix``."""
    return default_dialect(platform)


def shell_command_agent_dialect(platform: str | None = None) -> Dialect:
    """The shell ``ShellCommandAgent`` and the red team's re-run start: Windows PowerShell
    (``powershell -NoProfile -Command``) on Windows, else ``/bin/sh`` (``shell=True``)."""
    return "powershell" if (sys.platform if platform is None else platform) == "win32" else "posix"


def call_site_dialect(site: CallSite, platform: str | None = None) -> Dialect:
    """The dialect ``site`` runs a command in on ``platform`` (default: this one)."""
    if site == "run_command_tool":
        return run_command_tool_dialect(platform)
    if site == "shell_command_agent":
        return shell_command_agent_dialect(platform)
    raise ValueError("command_policy_call_site_invalid")


def serving_dialects(platform: str | None = None) -> tuple[Dialect, ...]:
    """Every dialect a run_command call site uses on ``platform``, once each, in site order."""
    found: list[Dialect] = []
    for site in CALL_SITES:
        dialect = call_site_dialect(site, platform)
        if dialect not in found:
            found.append(dialect)
    return tuple(found)


#: S2a repair r1 (review F1): a Windows path that names one directory whatever the current
#: drive and directory: 'C:\x', or a UNC or device path.
_WINDOWS_ABSOLUTE: Final = re.compile(r"[A-Za-z]:[\\/]|[\\/]{2}[^\\/]")
#: A name holding one of these is not a bare name for the cmd lookup: an extension, a path,
#: a drive, a quote, a variable or a wildcard.
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


def _cmd_lookup(
    name: str, directories: tuple[str, ...], extensions: tuple[str, ...], is_file: Callable[[str], bool],
) -> str | None:
    """Where ``cmd.exe`` finds the bare name ``name`` (measured, review r1: 12 layouts): each
    directory in order and, within one, each ``PATHEXT`` extension in order; the first file
    wins. None when that cannot be established, and for a name cmd runs as its own internal
    command before any file (S2a repair r2, review F2)."""
    if not name or any(char in _NOT_A_BARE_NAME for char in name):
        return None
    if _is_cmd_internal(name):
        return None  # cmd runs its internal command, never a file of that name
    for directory in directories:
        if not directory:
            continue  # an empty PATH entry
        if any(char in directory for char in '"%') or _WINDOWS_ABSOLUTE.match(directory) is None:
            return None  # cmd may read this entry otherwise: nothing after it is proven
        for extension in extensions:
            candidate = ntpath.join(directory, name + extension)
            if is_file(candidate):
                return candidate
    return None


def make_program_resolver(
    *,
    dialect: Dialect,
    search_path: str | None,
    cwd: str | None,
    pathext: str | None = None,
    which: Callable[..., Any] = shutil.which,
    is_file: Callable[[str], bool] = os.path.isfile,
) -> ProgramResolver:
    """Where the child's shell finds a bare program name, memoised for one judgement.

    ``search_path`` and ``pathext`` are the child's ``PATH`` and ``PATHEXT`` (from
    ``build_command_env``). None means the answer cannot be established; a pinned
    ``allow`` then refuses, naming the pinned path to run instead (S2a repair r1, F1).

    - ``posix``: ``which`` on ``search_path``; only an absolute answer counts (an empty or
      relative PATH entry is relative to a directory this lookup does not see). A
      ``/bin/sh`` built-in (``_POSIX_SHELL_BUILTINS``) proves nothing: the shell runs it,
      not the file ``which`` names (S2a repair r2).
    - ``cmd``: ``cwd`` -- or this process's directory, which a child given none inherits
      -- then each PATH entry; within a directory each ``PATHEXT`` extension in order; the
      first file wins. A name with an extension or a path, a name cmd reads as an internal
      command (``_is_cmd_internal``), a ``PATHEXT`` outside ``_PATHEXT_GRAMMAR``, and a
      relative, quoted or ``%`` entry reached before the answer prove nothing.
    - ``powershell``: never answers. PowerShell runs an alias, function or cmdlet (module
      auto-loading reads the child's ``PSModulePath``) before any file, and within a PATH
      directory ``<name>.ps1`` before every ``PATHEXT`` file (measured on 5.1 and 7), so no
      file lookup names what it runs. A pinned program is written as its absolute path.

    Symlinks are not followed: a pinned rule names the path the lookup yields.
    """
    extensions = _pathext(pathext)
    directories = (cwd if cwd else os.getcwd(), *(search_path or "").split(";")) if dialect == "cmd" else ()
    found: dict[str, str | None] = {}

    def lookup(name: str) -> str | None:
        if dialect == "powershell":
            return None
        if dialect == "cmd":
            return None if extensions is None else _cmd_lookup(name, directories, extensions, is_file)
        if name in _POSIX_SHELL_BUILTINS:
            return None  # the shell runs its built-in, never the file which() names (S2a repair r2, review F2)
        answer = which(name, path=search_path) if search_path else None
        return answer if type(answer) is str and posixpath.isabs(answer) else None

    def resolve(name: str) -> str | None:
        if name not in found:
            found[name] = lookup(name)
        return found[name]

    return resolve


@dataclass(frozen=True)
class CommandPolicyCause:
    """One reason a command took its decision: a rule, or a segment no rule decided."""

    kind: Literal["rule", "unmatched", "unparseable"]
    segment: int | None  # None: the whole line could not be read
    rule: str | None
    text: str  # the justification, or the reason; told to the agent, never recorded
    alternative: str | None


def _causes(evaluation: CommandEvaluation) -> tuple[CommandPolicyCause, ...]:
    causes = [
        CommandPolicyCause("rule", match.segment, match.rule, match.justification, match.alternative)
        for match in evaluation.governing
    ]
    if evaluation.unparseable is not None:
        causes.append(CommandPolicyCause(
            "unparseable", None, None, f"the policy could not read the command: {evaluation.unparseable}", None,
        ))
    for verdict in evaluation.segments:
        if verdict.decision != evaluation.decision or verdict.basis == "rule":
            continue
        if verdict.basis == "unparseable":
            text = f"the policy could not read part {verdict.index + 1}: {verdict.segment.unparseable}"
        else:
            program = verdict.segment.tokens[0] if verdict.segment.tokens else ""
            text = f"no rule covers {program!r}, and commands no rule covers are set to {verdict.decision}"
        causes.append(CommandPolicyCause(verdict.basis, verdict.index, None, text, None))
    return tuple(causes)


def _sentence(text: str) -> str:
    stripped = text.strip()[:_MAX_REASON_CHARS]
    return stripped if stripped.endswith((".", "!", "?")) else f"{stripped}."


def _describe(causes: tuple[CommandPolicyCause, ...]) -> str:
    parts: list[str] = []
    for cause in causes[:_MAX_SHOWN]:
        if cause.kind == "rule":
            text = f"Rule {cause.rule!r}: {_sentence(cause.text)}"
            if cause.alternative:
                text = f"{text} Instead: {_sentence(cause.alternative)}"
        else:
            text = _sentence(cause.text[0].upper() + cause.text[1:] if cause.text else cause.text)
        parts.append(text)
    if len(causes) > _MAX_SHOWN:
        parts.append(f"(and {len(causes) - _MAX_SHOWN} more)")
    return " ".join(parts)


@dataclass(frozen=True)
class CommandGateVerdict:
    """The gate's answer for one command at one call site."""

    status: Literal["no_policy", "evaluated"]
    call_site: CallSite | None
    evaluation: CommandEvaluation | None
    canonical: CanonicalCommand | None

    @property
    def decision(self) -> CommandDecisionName | None:
        return None if self.evaluation is None else self.evaluation.decision

    @property
    def runs(self) -> bool:
        """Whether the caller runs the command: no policy, or ``allow``."""
        return self.status == "no_policy" or self.decision == "allow"

    @property
    def causes(self) -> tuple[CommandPolicyCause, ...]:
        return () if self.evaluation is None else _causes(self.evaluation)

    @property
    def denial_reason(self) -> str:
        """The AD-1316 reason code for a refusal; empty when the command runs."""
        return "" if self.runs else f"command_policy_{self.decision}"

    @property
    def refusal_message(self) -> str | None:
        """What the agent is told when the command does not run; None when it runs."""
        if self.runs:
            return None
        frame = _FORBID_FRAME if self.decision == "forbid" else _ESCALATE_FRAME
        return frame.format(causes=_describe(self.causes))

    @property
    def record(self) -> dict[str, Any] | None:
        """The bounded decision record (no command text); None with no policy."""
        if self.evaluation is None or self.canonical is None:
            return None
        names = list(dict.fromkeys(match.rule for match in self.evaluation.matched_rules))
        causes = self.causes
        return {
            "schema": RECORD_SCHEMA,
            "call_site": self.call_site,
            "decision": self.decision,
            "dialect": self.evaluation.dialect,
            "policy_digest": self.evaluation.policy_digest,
            "canonical_key": self.canonical.key,
            "canonical_kind": self.canonical.kind,
            "matched_rules": names[:_MAX_RECORDED],
            "matched_rules_omitted": max(len(names) - _MAX_RECORDED, 0),
            "causes": [
                {"kind": cause.kind, "segment": cause.segment, "rule": cause.rule}
                for cause in causes[:_MAX_RECORDED]
            ],
            "causes_omitted": max(len(causes) - _MAX_RECORDED, 0),
        }


#: No rules: nothing was evaluated and the command runs as it would without a policy.
NO_POLICY: Final = CommandGateVerdict("no_policy", None, None, None)


def policy_result_metadata(verdict: CommandGateVerdict | None) -> dict[str, Any]:
    """The ``ToolResult.metadata`` a run_command result carries: empty with no policy."""
    record = None if verdict is None else verdict.record
    return {} if record is None else {"command_policy": record}


#: S2a repair r1 (review F4): the one tool whose result carries a decision record, and the
#: closed values each field of that record can hold. The rule-name grammar is the literal
#: twin of ``config_models.operations._COMMAND_RULE_NAME_PATTERN`` (a test pins that).
RUN_COMMAND_TOOL_ID: Final = "run_command"
_RECORD_SCHEMAS: Final = frozenset({RECORD_SCHEMA})
_RECORD_SITES: Final = frozenset({"run_command_tool"})
_RECORD_DIALECTS: Final = frozenset({run_command_tool_dialect("win32"), run_command_tool_dialect("linux")})
_RECORD_DECISIONS: Final = frozenset(COMMAND_DECISION_RANK)
_RECORD_KINDS: Final = frozenset({"argv", "script"})
_CAUSE_KEYS: Final = frozenset({"kind", "segment", "rule"})
_CAUSE_KINDS: Final = frozenset({"rule", "unmatched", "unparseable"})
_RECORD_RULE_NAME: Final = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_RECORD_DIGEST: Final = re.compile(r"[0-9a-f]{64}")
_MAX_COUNT: Final = 2**31 - 1


def _one_of(value: object, allowed: frozenset[str]) -> bool:
    return type(value) is str and value in allowed


def _is_digest(value: object) -> bool:
    return type(value) is str and _RECORD_DIGEST.fullmatch(value) is not None


def _is_rule_name(value: object) -> bool:
    return type(value) is str and _RECORD_RULE_NAME.fullmatch(value) is not None


def _is_count(value: object) -> bool:
    return type(value) is int and 0 <= value <= _MAX_COUNT


def _cause_of(value: object) -> dict[str, Any] | None:
    """One recorded cause rebuilt from its three typed fields; None if any is not typed."""
    if type(value) is not dict or set(value) != _CAUSE_KEYS:
        return None
    kind, segment, rule = value["kind"], value["segment"], value["rule"]
    if not _one_of(kind, _CAUSE_KINDS):
        return None
    if not (_is_count(segment) or (segment is None and kind == "unparseable")):
        return None
    if not (_is_rule_name(rule) if kind == "rule" else rule is None):
        return None
    return {"kind": kind, "segment": segment, "rule": rule}


def command_policy_record_of(result: object, *, tool_id: object) -> dict[str, Any] | None:
    """The decision record a tool result carries, projected for the AD-1224 sink; else None.

    Only the resolved ``run_command`` tool's own result is read (``tool_id`` is the
    executor's resolved id). Every field must hold its closed type: a fixed constant, a
    64-character lower-case hex digest, a rule name in the rule-name grammar, or a bounded
    count. The record is rebuilt from those fields, so no field can hold command text.
    Anything else drops the whole record, never repairs it (S2a repair r1, F4).
    """
    if type(tool_id) is not str or tool_id != RUN_COMMAND_TOOL_ID:
        return None
    metadata = getattr(result, "metadata", None)
    if type(metadata) is not dict:
        return None
    record = metadata.get("command_policy")
    if type(record) is not dict or set(record) != _RECORD_KEYS:
        return None
    rules, causes = record["matched_rules"], record["causes"]
    checks = (
        _one_of(record["schema"], _RECORD_SCHEMAS),
        _one_of(record["call_site"], _RECORD_SITES),
        _one_of(record["decision"], _RECORD_DECISIONS),
        _one_of(record["dialect"], _RECORD_DIALECTS),
        _one_of(record["canonical_kind"], _RECORD_KINDS),
        _is_digest(record["policy_digest"]),
        _is_digest(record["canonical_key"]),
        _is_count(record["matched_rules_omitted"]),
        _is_count(record["causes_omitted"]),
        type(rules) is list and len(rules) <= _MAX_RECORDED and all(_is_rule_name(name) for name in rules),
        type(causes) is list and len(causes) <= _MAX_RECORDED,
    )
    if not all(checks):
        return None
    projected = [_cause_of(cause) for cause in causes]
    if any(cause is None for cause in projected):
        return None
    copied: dict[str, Any] = {
        "schema": record["schema"],
        "call_site": record["call_site"],
        "decision": record["decision"],
        "dialect": record["dialect"],
        "policy_digest": record["policy_digest"],
        "canonical_key": record["canonical_key"],
        "canonical_kind": record["canonical_kind"],
        "matched_rules": list(rules),
        "matched_rules_omitted": record["matched_rules_omitted"],
        "causes": projected,
        "causes_omitted": record["causes_omitted"],
    }
    if len(json.dumps(copied, sort_keys=True)) > MAX_RECORD_CHARS:
        return None  # not reachable for an S2a record (at most about 1,900 characters)
    return copied


def compact_command_policy_record(record: dict[str, Any]) -> dict[str, Any]:
    """``record`` without its two lists, their entries counted as omitted: the form the
    AD-1224 sink keeps when the whole record does not fit the envelope (S2a repair r1, F5)."""
    return {
        **record,
        "matched_rules": [],
        "matched_rules_omitted": min(len(record["matched_rules"]) + record["matched_rules_omitted"], _MAX_COUNT),
        "causes": [],
        "causes_omitted": min(len(record["causes"]) + record["causes_omitted"], _MAX_COUNT),
    }


@dataclass(frozen=True)
class CommandPolicyReport:
    """What ``probos doctor`` reports about the configured policy."""

    rule_count: int
    digest: str | None
    reports: tuple[SelfTestReport, ...]
    error: str | None

    @property
    def passed(self) -> bool:
        return self.error is None and all(report.passed for report in self.reports)


def describe_command_policy(config: object, *, platform: str | None = None) -> CommandPolicyReport:
    """The policy's rule count, digest and self-test under each serving dialect. Never raises."""
    if type(config) is not CommandPolicyConfig:
        return CommandPolicyReport(
            0, None, (), f"execution.command_policy is a {type(config).__name__}, not a command policy",
        )
    if not config.rules:
        return CommandPolicyReport(0, None, (), None)
    try:
        reports = tuple(self_test(config, dialect=dialect) for dialect in serving_dialects(platform))
        return CommandPolicyReport(len(config.rules), policy_digest(config), reports, None)
    except Exception as exc:  # doctor reports; it never raises
        return CommandPolicyReport(len(config.rules), None, (), f"{type(exc).__name__}: {exc}")


class CommandPolicyGate:
    """The runtime's one command policy, self-tested under each dialect its call sites use.

    Construction raises ``CommandPolicySelfTestError`` naming the dialect, each failing
    rule and example; ``ProbOSRuntime.__init__`` builds it, so that stops startup.
    ``which`` (``shutil.which``, the posix lookup) and ``is_file`` (``os.path.isfile``, the
    cmd lookup) are the program lookup's probes; tests inject them.
    """

    def __init__(
        self,
        config: CommandPolicyConfig,
        *,
        platform: str | None = None,
        which: Callable[..., Any] = shutil.which,
        is_file: Callable[[str], bool] = os.path.isfile,
    ) -> None:
        if type(config) is not CommandPolicyConfig:
            raise TypeError("command_policy_config_type_invalid")
        self._config = config
        self._platform = sys.platform if platform is None else platform
        self._which = which
        self._is_file = is_file
        self._policies: dict[Dialect, CommandPolicy] = {}
        self._digest: str | None = None
        # No rules: nothing to self-test and no digest. Building a CommandPolicy computes
        # the digest, which imports the federation package (probos.federation.ard.jcs), so
        # a runtime without a policy must not build one.
        if config.rules:
            self._policies = {
                dialect: CommandPolicy(config, dialect=dialect) for dialect in serving_dialects(self._platform)
            }
            self._digest = policy_digest(config)
            logger.info(
                "AD-1328: command policy loaded: %d rules, digest %s, examples hold under %s",
                len(config.rules), self._digest, ", ".join(self._policies),
            )

    @property
    def config(self) -> CommandPolicyConfig:
        return self._config

    @property
    def configured(self) -> bool:
        """False with no rules: every command runs as it would without a policy."""
        return bool(self._config.rules)

    @property
    def digest(self) -> str | None:
        """The policy digest; None with no rules."""
        return self._digest

    @property
    def dialects(self) -> tuple[Dialect, ...]:
        """The dialects this gate's call sites use on its platform."""
        return serving_dialects(self._platform)

    @property
    def self_test_reports(self) -> tuple[SelfTestReport, ...]:
        return tuple(policy.self_test_report for policy in self._policies.values())

    def dialect_for(self, site: CallSite) -> Dialect:
        return call_site_dialect(site, self._platform)

    def judge(
        self,
        command: str,
        *,
        site: CallSite,
        search_path: str | None,
        cwd: str | None = None,
        pathext: str | None = None,
    ) -> CommandGateVerdict:
        """Judge ``command`` as ``site`` will run it: in its dialect, resolving programs as
        ``make_program_resolver`` does on the child's ``search_path`` (PATH), ``pathext``
        (PATHEXT) and, for ``cmd``, ``cwd``. ``command`` must be exactly a ``str``; anything
        else raises ``TypeError`` (S1), so a caller runs the very object judged and never
        a conversion of it (S2a repair r1, F3)."""
        if not self._config.rules:  # no policy: nothing is parsed, resolved or recorded
            return NO_POLICY
        dialect = self.dialect_for(site)
        policy = self._policies[dialect]
        resolve = make_program_resolver(
            dialect=dialect, search_path=search_path, cwd=cwd, pathext=pathext,
            which=self._which, is_file=self._is_file,
        )
        verdict = CommandGateVerdict(
            "evaluated",
            site,
            policy.evaluate(command, resolve_program=resolve),
            policy.canonical(command, resolve_program=resolve),
        )
        if not verdict.runs:
            record = verdict.record or {}
            logger.info(
                "AD-1328: command policy %s a %s command (rules=%s, key=%s, digest=%s)",
                "forbids" if verdict.decision == "forbid" else "escalates",
                site,
                ",".join(record.get("matched_rules", [])) or "-",
                str(record.get("canonical_key", ""))[:16],
                str(self._digest)[:16],
            )
        return verdict
