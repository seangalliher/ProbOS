"""AD-1328 S2a (#1530), M1: the command policy gate alone (``probos.execution.command_gate``).

Tests only. The contract is ``prompts/ad-1328-s2a-command-policy-wiring.md`` ("Tests", M1), amended by
``prompts/ad-1328-s1-repair-r1.md`` ("S2a amendments required") for S1's closed grammar: ``cmd`` refuses an unquoted ``;``
and PowerShell refuses a ``&`` inside a value, so the dialect-sensitive rows use the rule ``["echo", "a&b"]`` with the
match example ``echo "a&b"`` (it holds under ``cmd`` and ``posix`` and fails under PowerShell) and read ``git push; ls``
under a ``posix`` or PowerShell gate.

Nothing here starts a process, reads the real ``PATH`` or touches the host shell: every gate is built with an explicit
``platform=`` (``win32`` or ``linux``), an injected recording ``which`` (the posix lookup) and an injected recording
``is_file`` (the cmd lookup; S2a repair r1), so the file passes on both hosts. Each test
asserts its own premise (what the policy made of the command it is about) and a control: the accepted neighbour of every
refused case is checked first, so a test cannot pass because the gate refuses everything.
"""

from __future__ import annotations

import json
import logging
import ntpath
import os
import sys
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.cognitive.swe_harness.tools import RunCommandTool
from probos.config_models import operations
from probos.config_models.operations import CommandPolicyConfig
from probos.execution import command_gate
from probos.execution.command_gate import (
    CALL_SITES,
    COMMAND_POLICY_UNAVAILABLE,
    COMMAND_POLICY_UNAVAILABLE_MESSAGE,
    MAX_RECORD_CHARS,
    NO_POLICY,
    RECORD_SCHEMA,
    RUN_COMMAND_TOOL_ID,
    CallSite,
    CommandGateVerdict,
    CommandPolicyGate,
    call_site_dialect,
    command_policy_record_of,
    compact_command_policy_record,
    describe_command_policy,
    make_program_resolver,
    policy_result_metadata,
    run_command_tool_dialect,
    serving_dialects,
    shell_command_agent_dialect,
)

# The two fixed frames and the reason bound are private: they are the text the agent is told, so the tests pin them (and
# check the frames against the capability-gap regex) rather than re-typing them.
from probos.execution.command_gate import _ESCALATE_FRAME, _FORBID_FRAME, _MAX_REASON_CHARS
from probos.execution.command_policy import (
    CommandPolicy,
    CommandPolicySelfTestError,
    policy_digest,
    self_test,
)
from probos.execution import command_policy
from probos.tools.protocol import ToolResult

# --------------------------------------------------------------------------------------
# Helpers (the S1 `_policy` / `_rule` shapes are copied; tests do not import each other)
# --------------------------------------------------------------------------------------


def _policy(*rules: dict, unmatched: str = "allow", **extra: object) -> CommandPolicyConfig:
    return CommandPolicyConfig.model_validate({"rules": list(rules), "unmatched_decision": unmatched, **extra})


def _rule(name: str, pattern: list, decision: str, **extra: object) -> dict:
    base = {"name": name, "pattern": pattern, "decision": decision, "justification": f"{name} because"}
    if decision == "forbid":
        base["alternative"] = "use the governed path"
    return {**base, **extra}


class _FakeWhich:
    """A ``shutil.which`` stand-in that records every call and answers from the search path it was given."""

    def __init__(self, answers: dict[str | None, object] | None = None, *, fallback: object = None) -> None:
        self._answers = dict(answers or {})
        self._fallback = fallback
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, name: str, path: str | None = None) -> object:
        self.calls.append((name, path))
        return self._answers.get(path, self._fallback)


class _RecordingIsFile:
    """An ``os.path.isfile`` stand-in: answers from a fixed set of paths and records every probe, so no test reads the host."""

    def __init__(self, files: set[str] | None = None) -> None:
        self._files = set(files or ())
        self.calls: list[str] = []

    def __call__(self, path: str) -> bool:
        self.calls.append(path)
        return path in self._files


def _gate(
    config: CommandPolicyConfig,
    *,
    platform: str = "linux",
    which: _FakeWhich | None = None,
    is_file: Callable[[str], bool] | None = None,
) -> CommandPolicyGate:
    return CommandPolicyGate(
        config,
        platform=platform,
        which=_FakeWhich() if which is None else which,
        is_file=_RecordingIsFile() if is_file is None else is_file,
    )


def _judge(
    gate: CommandPolicyGate,
    command: str,
    *,
    site: CallSite = "run_command_tool",
    search_path: str | None = "/bin",
    cwd: str | None = None,
) -> CommandGateVerdict:
    return gate.judge(command, site=site, search_path=search_path, cwd=cwd)


def _split_frame(frame: str) -> tuple[str, str]:
    head, tail = frame.split("{causes}")
    return head, tail


def _cause_text(message: str, frame: str) -> str:
    """The cause sentences between a frame's fixed head and tail; asserts the message is built from that frame."""
    head, tail = _split_frame(frame)
    assert message.startswith(head), message
    assert message.endswith(tail), message
    return message[len(head) : len(message) - len(tail)]


def _pinned_git_status() -> CommandPolicyConfig:
    return _policy(
        _rule(
            "git-status", ["git", "status"], "allow", host_executable=["/usr/bin/git"],
            match=["/usr/bin/git status"], not_match=["/tmp/evil/git status"],
        ),
        unmatched="escalate",
    )


def _amp_policy() -> CommandPolicyConfig:
    """A rule whose example holds under ``cmd`` and ``posix`` and fails under PowerShell (S1: ``&`` in a value)."""
    return _policy(_rule("amp", ["echo", "a&b"], "forbid", match=['echo "a&b"']))


_PUSH_JUSTIFICATION = "a push publishes work to the shared remote"

# (platform, call site, the dialect that site runs a command in): every dialect a call site uses
_SITE_MATRIX = [
    pytest.param("win32", "run_command_tool", "cmd", id="win32-tool-cmd"),
    pytest.param("win32", "shell_command_agent", "powershell", id="win32-agent-powershell"),
    pytest.param("linux", "run_command_tool", "posix", id="linux-tool-posix"),
]

# AD-1328 S2b: the record gained "approval" (None until the approval route acts), so its key set has one more.
_RECORD_KEYS = {
    "schema", "call_site", "decision", "dialect", "policy_digest", "canonical_key", "canonical_kind",
    "matched_rules", "matched_rules_omitted", "causes", "causes_omitted", "approval",
}


# --------------------------------------------------------------------------------------
# 1. The dialect each call site runs a command in
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "tool", "agent", "serving"),
    [
        pytest.param("win32", "cmd", "powershell", ("cmd", "powershell"), id="win32"),
        pytest.param("linux", "posix", "posix", ("posix",), id="linux"),
        pytest.param("darwin", "posix", "posix", ("posix",), id="darwin"),
    ],
)
def test_dialect_per_call_site(platform: str, tool: str, agent: str, serving: tuple[str, ...]) -> None:
    assert CALL_SITES == ("run_command_tool", "shell_command_agent")  # premise: the two sites the map covers
    assert call_site_dialect("run_command_tool", platform) == tool
    assert call_site_dialect("shell_command_agent", platform) == agent
    assert run_command_tool_dialect(platform) == tool
    assert shell_command_agent_dialect(platform) == agent
    assert serving_dialects(platform) == serving
    # a gate answers for the platform it was given, not for the host
    gate = _gate(CommandPolicyConfig(), platform=platform)
    assert gate.dialects == serving
    assert gate.dialect_for("run_command_tool") == tool
    assert gate.dialect_for("shell_command_agent") == agent


def test_dialect_unknown_site_raises() -> None:
    assert call_site_dialect("run_command_tool", "win32") == "cmd"  # control: a real site answers
    with pytest.raises(ValueError, match="command_policy_call_site_invalid"):
        call_site_dialect("elsewhere", "win32")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="command_policy_call_site_invalid"):
        _gate(CommandPolicyConfig(), platform="win32").dialect_for("elsewhere")  # type: ignore[arg-type]


def test_dialect_default_platform_is_this_one() -> None:
    for site in CALL_SITES:
        assert call_site_dialect(site) == call_site_dialect(site, sys.platform)
    assert serving_dialects() == serving_dialects(sys.platform)


# --------------------------------------------------------------------------------------
# 2. The gate self-tests every dialect its call sites use
# --------------------------------------------------------------------------------------


def test_gate_self_tests_every_serving_dialect() -> None:
    config = _amp_policy()
    # premise: the example holds under cmd and posix and fails under powershell, naming the unparseable `&`
    assert self_test(config, dialect="cmd").passed is True
    assert self_test(config, dialect="posix").passed is True
    powershell = self_test(config, dialect="powershell")
    assert powershell.passed is False
    assert "unparseable" in powershell.failures[0].observed

    # control: where only posix serves (linux, darwin), the same policy builds
    for platform in ("linux", "darwin"):
        built = _gate(config, platform=platform)
        assert built.dialects == ("posix",)
        assert [report.dialect for report in built.self_test_reports] == ["posix"]

    # win32 serves cmd AND powershell: the powershell build fails, and the error names it, the rule and the example
    with pytest.raises(CommandPolicySelfTestError) as raised:
        _gate(config, platform="win32")
    text = str(raised.value)
    assert "powershell" in text
    assert "'amp'" in text
    assert repr('echo "a&b"') in text
    assert raised.value.report.dialect == "powershell"
    assert [failure.rule for failure in raised.value.report.failures] == ["amp"]


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_gate_builds_when_every_dialect_holds_the_examples(platform: str) -> None:
    config = _policy(
        _rule("no-push", ["git", "push"], "forbid", match=["git push origin main"], not_match=["git status"]),
    )
    for dialect in ("cmd", "powershell", "posix"):  # premise: the examples hold in all three builds
        assert self_test(config, dialect=dialect).passed is True

    gate = _gate(config, platform=platform)
    assert gate.dialects == serving_dialects(platform)
    assert [report.dialect for report in gate.self_test_reports] == list(serving_dialects(platform))
    assert len(gate.self_test_reports) == len(serving_dialects(platform))
    assert all(report.passed and report.examples_checked == 2 for report in gate.self_test_reports)
    assert gate.configured is True
    assert gate.digest == policy_digest(config)
    assert gate.config is config


def test_gate_rejects_a_config_that_is_not_a_command_policy() -> None:
    assert _gate(CommandPolicyConfig()).configured is False  # control: a real config builds
    for wrong in ({"rules": []}, None, "policy"):
        with pytest.raises(TypeError, match="command_policy_config_type_invalid"):
            CommandPolicyGate(wrong, platform="linux", which=_FakeWhich())  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# 3. No rules: nothing is built, parsed, resolved or recorded
# --------------------------------------------------------------------------------------


def _reached(*args: object, **kwargs: object) -> object:
    raise AssertionError("the policy engine was reached although no rule is configured")


def test_no_rules_is_inert(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _FakeWhich(fallback="/usr/bin/anything")
    configured = _policy(_rule("no-curl", ["curl"], "forbid"))
    with monkeypatch.context() as patched:
        patched.setattr(command_gate, "CommandPolicy", _reached)
        patched.setattr(command_gate, "policy_digest", _reached)
        # control: the patch is live, so a configured gate cannot be built through it
        with pytest.raises(AssertionError, match="reached"):
            CommandPolicyGate(configured, platform="linux", which=spy)
        # no rules: builds no policy and computes no digest (S1's digest imports the federation package)
        gate = CommandPolicyGate(CommandPolicyConfig(), which=spy)
        verdicts = [gate.judge("(((", site=site, search_path="/bin") for site in CALL_SITES]

    assert gate.digest is None
    assert gate.self_test_reports == ()
    assert gate.configured is False
    for verdict in verdicts:
        assert verdict is NO_POLICY
        assert verdict.status == "no_policy"
        assert verdict.decision is None
        assert verdict.runs is True
        assert verdict.record is None
        assert verdict.refusal_message is None
        assert verdict.denial_reason == ""
        assert verdict.causes == ()
    assert spy.calls == []

    # a policy that evaluates is not consulted either
    monkeypatch.setattr(CommandPolicy, "evaluate", _reached)
    monkeypatch.setattr(CommandPolicy, "canonical", _reached)
    assert gate.judge("(((", site="run_command_tool", search_path="/bin") is NO_POLICY
    assert spy.calls == []

    # control: with rules, the same text is judged (it is unreadable, so it is not run), never NO_POLICY
    monkeypatch.undo()
    configured_verdict = _judge(_gate(_policy(_rule("no-curl", ["curl"], "forbid"))), "(((")
    assert configured_verdict is not NO_POLICY
    assert configured_verdict.status == "evaluated"
    assert configured_verdict.runs is False


# --------------------------------------------------------------------------------------
# 4-6. The program resolver: the child's PATH, memoised, and what a pinned rule does with it
# --------------------------------------------------------------------------------------

_PROCESS_CWD = "<this process's working directory>"


@pytest.mark.parametrize(
    ("dialect", "search_path", "cwd", "entries"),
    [
        pytest.param("cmd", "C:\\P", "C:\\work", ["C:\\work", "C:\\P"], id="cmd_with_cwd"),
        pytest.param("cmd", "C:\\P", None, [_PROCESS_CWD, "C:\\P"], id="cmd_without_cwd"),
        pytest.param("posix", "P", "/work", ["P"], id="posix"),
        pytest.param("powershell", "C:\\P", "C:\\work", [], id="powershell"),
        pytest.param("posix", None, "/work", [], id="no_path"),
    ],
)
def test_resolver_search_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    dialect: str,
    search_path: str | None,
    cwd: str | None,
    entries: list[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    which = _FakeWhich(fallback="/found/git")
    is_file = _RecordingIsFile()  # answers False for every probe
    resolve = make_program_resolver(
        dialect=dialect, search_path=search_path, cwd=cwd, pathext=".COM;.EXE", which=which, is_file=is_file,  # type: ignore[arg-type]
    )
    assert which.calls == [] and is_file.calls == []  # a resolver does nothing until it is asked

    answer = resolve("git")

    if dialect == "cmd":
        # D-s2a-1: cmd never calls which; it probes each directory then each PATHEXT extension, in order, and finds nothing here
        assert which.calls == []
        assert answer is None
        if cwd is not None:
            assert is_file.calls == ["C:\\work\\git.COM", "C:\\work\\git.EXE", "C:\\P\\git.COM", "C:\\P\\git.EXE"]
        elif sys.platform == "win32":  # a child given no directory starts in this process's, a Windows path here
            here = os.getcwd()
            assert is_file.calls == [
                ntpath.join(here, "git.COM"), ntpath.join(here, "git.EXE"), "C:\\P\\git.COM", "C:\\P\\git.EXE",
            ]
        else:  # os.getcwd() is not a Windows path here: it proves nothing, so nothing is probed
            assert is_file.calls == []
    elif entries:
        expected = os.pathsep.join(entries)
        assert which.calls == [("git", expected)]
        assert answer == "/found/git"
        assert is_file.calls == []
    else:
        # no search path, or PowerShell: nothing to look up, so neither probe runs and the answer is None
        assert which.calls == []
        assert is_file.calls == []
        assert answer is None


def test_resolver_cmd_searches_its_directory_even_without_a_path() -> None:
    which = _FakeWhich(fallback="C:\\other\\git.exe")
    is_file = _RecordingIsFile({"C:\\work\\git.EXE"})
    for search_path in (None, ""):
        resolve = make_program_resolver(
            dialect="cmd", search_path=search_path, cwd="C:\\work", pathext=".EXE", which=which, is_file=is_file,
        )
        assert resolve("git") == "C:\\work\\git.EXE"
    assert is_file.calls == ["C:\\work\\git.EXE", "C:\\work\\git.EXE"]
    # control: the dialects that do not search their working directory look at nothing
    for dialect in ("posix", "powershell"):
        resolve = make_program_resolver(
            dialect=dialect, search_path="", cwd="C:\\work", pathext=".EXE", which=which, is_file=is_file,  # type: ignore[arg-type]
        )
        assert resolve("git") is None
    assert len(is_file.calls) == 2  # PowerShell and posix added no probe
    assert which.calls == []  # and cmd never called which


@pytest.mark.parametrize(
    "answer",
    [PurePosixPath("/usr/bin/git"), b"/usr/bin/git", 42, ["/usr/bin/git"]],
    ids=["path_object", "bytes", "int", "list"],
)
def test_resolver_non_string_answer_is_none(answer: object) -> None:
    str_resolve = make_program_resolver(dialect="posix", search_path="/usr/bin", cwd=None, which=_FakeWhich(fallback="/usr/bin/git"))
    assert str_resolve("git") == "/usr/bin/git"  # control: a string answer is the answer
    resolve = make_program_resolver(dialect="posix", search_path="/usr/bin", cwd=None, which=_FakeWhich(fallback=answer))
    assert resolve("git") is None


def test_resolver_is_memoised_within_one_judgement() -> None:
    # unit: each name is looked up once, a miss included
    which = _FakeWhich({"/usr/bin": "/usr/bin/git"})
    resolve = make_program_resolver(dialect="posix", search_path="/usr/bin", cwd=None, which=which)
    assert [resolve("git"), resolve("git")] == ["/usr/bin/git", "/usr/bin/git"]
    which_miss = _FakeWhich()
    resolve_miss = make_program_resolver(dialect="posix", search_path="/usr/bin", cwd=None, which=which_miss)
    assert [resolve_miss("nope"), resolve_miss("nope")] == [None, None]
    assert which.calls == [("git", "/usr/bin")]
    assert which_miss.calls == [("nope", "/usr/bin")]

    # through the gate: evaluation and the canonical key both use the lookup, yet which is called once per judgement
    where = _FakeWhich({"/usr/bin": "/usr/bin/git"})
    gate = _gate(_pinned_git_status(), platform="linux", which=where)
    first = _judge(gate, "git status", search_path="/usr/bin")
    assert first.decision == "allow" and first.runs  # premise: the pinned rule was proven at the resolved path...
    assert first.evaluation.matched_rules[0].resolved_program == "/usr/bin/git"
    assert first.canonical.parts[0] == "/usr/bin/git"  # ...and the canonical key was built from the same answer
    assert where.calls == [("git", "/usr/bin")]
    _judge(gate, "git status", search_path="/usr/bin")
    assert where.calls == [("git", "/usr/bin"), ("git", "/usr/bin")]  # the memo lives for one judgement only


def test_pinned_allow_follows_the_child_path() -> None:
    where = _FakeWhich({"/usr/bin": "/usr/bin/git", "/tmp/evil": "/tmp/evil/git"})  # any other path: not found
    gate = _gate(_pinned_git_status(), platform="linux", which=where)

    allowed = _judge(gate, "git status", search_path="/usr/bin")  # the accepted neighbour first
    assert allowed.decision == "allow"
    assert allowed.runs is True
    assert allowed.refusal_message is None

    planted = _judge(gate, "git status", search_path="/tmp/evil")
    assert planted.decision == "forbid"
    assert planted.runs is False
    assert planted.denial_reason == "command_policy_forbid"
    assert "/tmp/evil/git" in planted.refusal_message  # the path the child would run
    assert "/usr/bin/git" in planted.refusal_message  # the path the rule pins

    missing = _judge(gate, "git status", search_path="/nowhere")
    assert missing.decision == "forbid"  # a program the child's PATH does not find is not the pinned one
    assert missing.runs is False
    assert "/usr/bin/git" in missing.refusal_message  # the alternative names the pinned executable

    # the lookup used the child's PATH each time, never another
    assert where.calls == [("git", "/usr/bin"), ("git", "/tmp/evil"), ("git", "/nowhere")]


def test_judge_resolves_programs_on_the_childs_path_and_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    config = _policy(_rule("no-curl", ["curl"], "forbid"), unmatched="allow")

    cmd_where = _FakeWhich()
    cmd_files = _RecordingIsFile()  # answers False: every probe is recorded, none reads the host
    win32 = _gate(config, platform="win32", which=cmd_where, is_file=cmd_files)
    pathext, child_path = ".EXE", "C:\\P"
    win32.judge("git status", site="run_command_tool", search_path=child_path, cwd="C:\\work", pathext=pathext)  # cmd: its directory leads
    assert cmd_files.calls == ["C:\\work\\git.EXE", "C:\\P\\git.EXE"]
    cmd_files.calls.clear()
    win32.judge("git status", site="run_command_tool", search_path=child_path, pathext=pathext)  # ...or this process's, when it has none
    if sys.platform == "win32":  # host-named: a Windows path only on a Windows host
        assert cmd_files.calls == [ntpath.join(os.getcwd(), "git.EXE"), "C:\\P\\git.EXE"]
    else:
        assert cmd_files.calls == []
    cmd_files.calls.clear()
    win32.judge("git status", site="shell_command_agent", search_path=child_path, cwd="C:\\work", pathext=pathext)  # PowerShell: no lookup
    assert cmd_files.calls == []
    assert cmd_where.calls == []  # cmd and PowerShell never call which

    posix_where = _FakeWhich()
    linux = _gate(config, platform="linux", which=posix_where)
    _judge(linux, "git status", search_path="P", cwd="/work")
    assert posix_where.calls == [("git", "P")]
    _judge(linux, "git status", search_path=None)  # no PATH to search: no lookup, and the verdict still comes
    assert posix_where.calls == [("git", "P")]


# --------------------------------------------------------------------------------------
# 7-9. Verdicts, reason codes and the messages the agent is told
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "decision", "runs", "reason"),
    [
        pytest.param("echo hi", "allow", True, "", id="allow"),
        pytest.param("git push origin main", "escalate", False, "command_policy_escalate", id="escalate"),
        pytest.param("curl -sS example.com", "forbid", False, "command_policy_forbid", id="forbid"),
    ],
)
@pytest.mark.parametrize(("platform", "site"), [("win32", "run_command_tool"), ("win32", "shell_command_agent"), ("linux", "run_command_tool")])
def test_verdict_runs_only_for_allow(command: str, decision: str, runs: bool, reason: str, platform: str, site: CallSite) -> None:
    gate = _gate(
        _policy(
            _rule("echo-ok", ["echo"], "allow"),
            _rule("push", ["git", "push"], "escalate"),
            _rule("no-curl", ["curl"], "forbid"),
            unmatched="allow",
        ),
        platform=platform,
    )
    verdict = _judge(gate, command, site=site)
    assert verdict.status == "evaluated"  # premise: the command was read and decided
    assert verdict.evaluation.unparseable is None
    assert verdict.decision == decision
    assert verdict.runs is runs
    assert verdict.denial_reason == reason
    assert (verdict.refusal_message is None) is runs


def test_forbid_message_names_rule_justification_and_alternative() -> None:
    justification = "curl reaches the open network"
    alternative = "use the http_fetch tool"
    gate = _gate(
        _policy(
            _rule("no-curl", ["curl"], "forbid", justification=justification, alternative=alternative),
            _rule("push", ["git", "push"], "escalate", justification=_PUSH_JUSTIFICATION),
            unmatched="allow",
        ),
    )
    forbid_head, _ = _split_frame(_FORBID_FRAME)
    escalate_head, _ = _split_frame(_ESCALATE_FRAME)
    assert forbid_head != escalate_head  # premise: the two frames differ, so "starts with" says something

    escalated = _judge(gate, "git push origin main")  # the accepted neighbour: another decision, another frame
    assert escalated.decision == "escalate"
    assert escalated.refusal_message.startswith(escalate_head)
    assert not escalated.refusal_message.startswith(forbid_head)

    forbidden = _judge(gate, "curl -sS example.com")
    assert forbidden.decision == "forbid"
    message = forbidden.refusal_message
    assert message is not None
    assert message.startswith(forbid_head)
    assert not message.startswith(escalate_head)
    assert message.index("no-curl") < message.index(justification) < message.index(alternative)
    assert _CAPABILITY_GAP_RE.search(message) is None  # plain justifications: nothing in it reads as a capability gap


def test_message_names_only_the_rules_that_carry_the_decision() -> None:
    gate = _gate(
        _policy(
            _rule("git-ok", ["git"], "allow", justification="git is the sanctioned version control"),
            _rule("no-push", ["git", "push"], "forbid", justification="a push publishes work", alternative="open a pull request"),
            unmatched="allow",
        ),
    )
    allowed = _judge(gate, "git status")  # the accepted neighbour: only the allow rule matches, and the command runs
    assert [match.rule for match in allowed.evaluation.matched_rules] == ["git-ok"] and allowed.runs

    verdict = _judge(gate, "git push origin main")
    assert [match.rule for match in verdict.evaluation.matched_rules] == ["git-ok", "no-push"]  # premise: both match one segment
    assert verdict.decision == "forbid"  # the strictest wins
    assert [match.rule for match in verdict.evaluation.governing] == ["no-push"]
    assert [(cause.kind, cause.rule) for cause in verdict.causes] == [("rule", "no-push")]
    assert "no-push" in verdict.refusal_message
    assert "git-ok" not in verdict.refusal_message and "sanctioned" not in verdict.refusal_message
    record = verdict.record
    assert record["matched_rules"] == ["git-ok", "no-push"]  # the record lists every rule that matched...
    assert [cause["rule"] for cause in record["causes"]] == ["no-push"]  # ...and only the one that decided is a cause


def test_message_cuts_a_long_reason_and_closes_every_cause_as_a_sentence() -> None:
    long_justification = "a" * (_MAX_REASON_CHARS + 100)  # the policy model allows up to 500 characters of prose
    gate = _gate(
        _policy(
            _rule("no-curl", ["curl"], "forbid", justification=long_justification, alternative="use the http_fetch tool."),
            _rule("no-wget", ["wget"], "forbid", justification="wget is not sanctioned!", alternative="use the http_fetch tool"),
            unmatched="allow",
        ),
    )
    short = _judge(gate, "wget x").refusal_message  # the accepted neighbour first: short prose is quoted whole
    assert "wget is not sanctioned!" in short and "sanctioned!." not in short  # a sentence that ends is not ended twice
    assert "Instead: use the http_fetch tool." in short  # ...and one that does not gets its full stop

    message = _judge(gate, "curl x").refusal_message
    assert "a" * _MAX_REASON_CHARS in message
    assert "a" * (_MAX_REASON_CHARS + 1) not in message  # a reason is cut at the bound...
    assert "a" * _MAX_REASON_CHARS + "." in message  # ...and then closed as a sentence
    assert "use the http_fetch tool.." not in message


@pytest.mark.parametrize(
    ("command", "neighbour", "kind", "segment", "reason_head"),
    [
        pytest.param("git push origin main", "echo x", "rule", 0, f"Rule 'push': {_PUSH_JUSTIFICATION}.", id="rule"),
        pytest.param("ls", "echo x", "unmatched", 0, "No rule covers 'ls'", id="unmatched"),
        pytest.param('echo "x', 'echo "x"', "unparseable", None, "The policy could not read the command: ", id="unparseable_line"),
        pytest.param("eval x", "echo x", "unparseable", 0, "The policy could not read part 1: ", id="unparseable_segment"),
    ],
)
def test_escalate_message_names_the_rule_or_the_reason(
    command: str, neighbour: str, kind: str, segment: int | None, reason_head: str,
) -> None:
    gate = _gate(
        _policy(
            _rule("echo-ok", ["echo"], "allow"),
            _rule("push", ["git", "push"], "escalate", justification=_PUSH_JUSTIFICATION),
            unmatched="escalate",  # an allow-list
        ),
    )
    accepted = _judge(gate, neighbour)  # the accepted neighbour first: the gate does not refuse everything
    assert accepted.decision == "allow" and accepted.runs

    verdict = _judge(gate, command)
    assert verdict.decision == "escalate"  # premise
    assert verdict.runs is False
    assert verdict.denial_reason == "command_policy_escalate"
    assert [(cause.kind, cause.segment) for cause in verdict.causes] == [(kind, segment)]
    evaluation = verdict.evaluation
    if kind == "rule":
        assert [match.rule for match in evaluation.governing] == ["push"]
    else:
        assert evaluation.governing == ()  # O-S1-11: no rule decided it, yet the message says why
    if kind == "unparseable" and segment is None:
        assert evaluation.unparseable is not None and evaluation.segments == ()  # the whole line could not be read
        reason = evaluation.unparseable
    elif kind == "unparseable":
        assert evaluation.unparseable is None  # the line reads; one part of it does not
        reason = evaluation.segments[0].segment.unparseable
    else:
        reason = None

    message = verdict.refusal_message
    assert "no approval was requested" in message
    causes = _cause_text(message, _ESCALATE_FRAME)
    assert causes.startswith(reason_head)
    if reason is not None:
        assert reason in causes  # S1's own reason, quoted as is
    # only the fixed frame is pinned against the capability-gap regex: S1's reason text may use such words
    head, tail = _split_frame(_ESCALATE_FRAME)
    assert _CAPABILITY_GAP_RE.search(head + tail) is None


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(_FORBID_FRAME.format(causes=""), id="forbid"),
        pytest.param(_ESCALATE_FRAME.format(causes=""), id="escalate"),
        pytest.param(COMMAND_POLICY_UNAVAILABLE_MESSAGE, id="unavailable"),
    ],
)
def test_fixed_frames_do_not_read_as_a_capability_gap(text: str) -> None:
    assert _CAPABILITY_GAP_RE.search("I cannot run that command") is not None  # control: the pattern is live
    assert _CAPABILITY_GAP_RE.search(text) is None
    assert COMMAND_POLICY_UNAVAILABLE == "command_policy_unavailable"


def test_causes_list_every_non_rule_segment_at_the_decision() -> None:
    escalate_push = _rule("push", ["git", "push"], "escalate", justification=_PUSH_JUSTIFICATION)
    for platform, site in (("linux", "run_command_tool"), ("win32", "shell_command_agent")):  # posix, then PowerShell
        gate = _gate(_policy(escalate_push, unmatched="escalate"), platform=platform)
        alone = _judge(gate, "git push", site=site)  # the accepted neighbour first: one segment, one cause
        assert [(cause.kind, cause.segment) for cause in alone.causes] == [("rule", 0)]

        both = _judge(gate, "git push; ls", site=site)
        assert both.evaluation.unparseable is None  # premise: the line reads as two segments
        assert [verdict.segment.tokens[0] for verdict in both.evaluation.segments] == ["git", "ls"]
        assert both.decision == "escalate"
        assert [(cause.kind, cause.segment, cause.rule) for cause in both.causes] == [("rule", 0, "push"), ("unmatched", 1, None)]
        message = both.refusal_message
        assert message.index("Rule 'push'") < message.index("'ls'")  # segment order
        assert [cause["kind"] for cause in both.record["causes"]] == ["rule", "unmatched"]


def test_causes_leave_out_a_segment_that_took_a_different_decision() -> None:
    gate = _gate(_policy(_rule("push", ["git", "push"], "escalate", justification=_PUSH_JUSTIFICATION), unmatched="allow"))
    verdict = _judge(gate, "git push; ls")
    unmatched_part = verdict.evaluation.segments[1]
    assert (unmatched_part.basis, unmatched_part.decision) == ("unmatched", "allow")  # premise: `ls` is allowed by default
    assert verdict.decision == "escalate"  # ...and the command escalates
    assert [(cause.kind, cause.segment) for cause in verdict.causes] == [("rule", 0)]  # `ls` took no part in it
    assert "'ls'" not in verdict.refusal_message


def test_causes_at_an_allow_decision_are_the_allow_matches_when_every_segment_has_a_rule() -> None:
    gate = _gate(_policy(_rule("git-ok", ["git"], "allow"), _rule("ls-ok", ["ls"], "allow"), unmatched="allow"))
    verdict = _judge(gate, "git status; ls")
    assert verdict.decision == "allow" and verdict.runs
    assert [segment.basis for segment in verdict.evaluation.segments] == ["rule", "rule"]  # premise: no unmatched segment
    assert [(cause.kind, cause.segment, cause.rule) for cause in verdict.causes] == [("rule", 0, "git-ok"), ("rule", 1, "ls-ok")]
    assert verdict.refusal_message is None


def test_causes_at_an_allow_decision_also_list_a_segment_no_rule_covers() -> None:
    # D7: "each segment whose decision equals the command's and whose basis is `unmatched`" -- at `allow` too. The contract's
    # M1 #10 sentence ("causes are the allow matches only") contradicts D7 for this input; D7 and the installed gate agree.
    gate = _gate(_policy(_rule("git-ok", ["git", "status"], "allow"), unmatched="allow"))
    verdict = _judge(gate, "git status; ls")
    assert verdict.decision == "allow" and verdict.runs
    assert [segment.basis for segment in verdict.evaluation.segments] == ["rule", "unmatched"]
    assert [(cause.kind, cause.segment, cause.rule) for cause in verdict.causes] == [("rule", 0, "git-ok"), ("unmatched", 1, None)]
    assert verdict.refusal_message is None  # a command that runs is told nothing
    assert [cause["kind"] for cause in verdict.record["causes"]] == ["rule", "unmatched"]


@pytest.mark.parametrize(
    ("count", "tail"),
    [pytest.param(5, None, id="five"), pytest.param(6, "(and 1 more)", id="six"), pytest.param(7, "(and 2 more)", id="seven")],
)
def test_message_shows_five_causes_then_a_count(count: int, tail: str | None) -> None:
    programs = ["curl", "wget", "scp", "nc", "ftp", "telnet", "rm"]
    names = [f"no-{program}" for program in programs]
    gate = _gate(_policy(*[_rule(name, [program], "forbid") for name, program in zip(names, programs)], unmatched="allow"))

    verdict = _judge(gate, "; ".join(f"{program} x" for program in programs[:count]))
    assert verdict.decision == "forbid"  # premise: every segment was read and forbidden by its own rule
    assert len(verdict.evaluation.segments) == count
    assert len(verdict.causes) == count

    message = verdict.refusal_message
    assert message.count("Rule '") == 5  # five shown, however many there are
    for shown in names[:5]:
        assert f"Rule '{shown}'" in message
    for hidden in names[5:count]:
        assert hidden not in message
    if tail is None:
        assert "more)" not in message  # control: five causes need no count
    else:
        assert tail in message


# --------------------------------------------------------------------------------------
# 12-15. The AD-1224 record: shape, no command text, bounds, validation
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "kind"),
    [pytest.param("curl SENTINEL-7Q", "argv", id="argv"), pytest.param("echo ok; curl SENTINEL-7Q", "script", id="script")],
)
@pytest.mark.parametrize("resolved", [None, "/usr/bin/curl"], ids=["unresolved", "resolved"])
def test_record_shape_and_no_command_text(command: str, kind: str, resolved: str | None) -> None:
    justification = "curl reaches the open network"
    alternative = "use the http_fetch tool"
    config = _policy(_rule("no-curl", ["curl"], "forbid", justification=justification, alternative=alternative), unmatched="allow")
    gate = _gate(config, platform="linux", which=_FakeWhich(fallback=resolved))
    assert "SENTINEL-7Q" not in justification + alternative  # premise: the sentinel can only come from the command

    verdict = _judge(gate, command, search_path="/bin")
    assert verdict.decision == "forbid"
    record = verdict.record

    assert set(record) == _RECORD_KEYS
    # AD-1328 S2b: the record schema is v2 now that the record carries "approval".
    assert record["schema"] == RECORD_SCHEMA == "probos.command_policy.record/v2"
    assert record["call_site"] == "run_command_tool"
    assert record["decision"] == "forbid"
    assert record["dialect"] == "posix"
    assert record["policy_digest"] == gate.digest == policy_digest(config)
    assert record["canonical_kind"] == kind
    engine = CommandPolicy(config, dialect="posix")
    assert record["canonical_key"] == engine.canonical(command, resolve_program=lambda name: resolved).key
    assert record["canonical_key"] == verdict.canonical.key
    if kind == "argv" and resolved is not None:
        # control: the key is of the program the child's PATH finds, not of the bare name
        assert record["canonical_key"] != engine.canonical(command).key
    assert record["matched_rules"] == ["no-curl"]  # control: the record is not empty, so what is absent is absent
    assert record["matched_rules_omitted"] == 0
    assert record["causes"] == [{"kind": "rule", "segment": len(verdict.evaluation.segments) - 1, "rule": "no-curl"}]
    assert record["causes_omitted"] == 0

    text = json.dumps(record)
    assert "SENTINEL-7Q" not in text  # no command text
    assert justification not in text  # and no rule prose: that is told to the agent, never recorded
    assert alternative not in text
    assert "curl SENTINEL" not in text


def test_record_is_bounded() -> None:
    names = [chr(ord("a") + index) + "x" * 63 for index in range(20)]
    programs = [f"p{index:02d}" for index in range(20)]
    gate = _gate(_policy(*[_rule(name, [program], "forbid") for name, program in zip(names, programs)], unmatched="allow"))

    few = _judge(gate, "; ".join(programs[:3])).record  # control: a handful of rules are all recorded
    assert few["matched_rules"] == names[:3] and few["matched_rules_omitted"] == 0
    assert len(few["causes"]) == 3 and few["causes_omitted"] == 0

    verdict = _judge(gate, "; ".join(programs))
    assert all(len(name) == 64 for name in names)  # premise: 20 matched rules with 64-character names over 20 segments
    assert len(verdict.evaluation.segments) == 20
    assert len(verdict.evaluation.matched_rules) == 20
    assert len(verdict.causes) == 20
    record = verdict.record
    assert record["matched_rules"] == names[:8]
    assert record["matched_rules_omitted"] == 12
    assert [cause["segment"] for cause in record["causes"]] == list(range(8))
    assert record["causes_omitted"] == 12
    assert len(json.dumps(record, sort_keys=True)) <= MAX_RECORD_CHARS
    # the bounded record is one the AD-1224 sink accepts, unchanged
    assert command_policy_record_of(SimpleNamespace(metadata={"command_policy": record}), tool_id=RUN_COMMAND_TOOL_ID) == record


def test_record_names_each_rule_once_but_every_segment_is_a_cause() -> None:
    gate = _gate(_policy(_rule("no-rm", ["rm"], "forbid"), unmatched="allow"))
    verdict = _judge(gate, "; ".join(f"rm f{index}" for index in range(12)))
    assert len(verdict.evaluation.matched_rules) == 12  # premise: one rule matched twelve segments
    record = verdict.record
    assert record["matched_rules"] == ["no-rm"]
    assert record["matched_rules_omitted"] == 0
    assert len(record["causes"]) == 8 and record["causes_omitted"] == 4


def _recorded() -> dict:
    gate = _gate(_policy(_rule("no-curl", ["curl"], "forbid"), unmatched="allow"))
    record = _judge(gate, "curl x").record
    assert record is not None
    return record


@pytest.mark.parametrize(
    ("build", "accepted"),
    [
        pytest.param(lambda r: {"command_policy": r}, True, id="gate_record"),
        pytest.param(lambda r: {"command_policy": {**r, "command": "curl x"}}, False, id="extra_key"),
        pytest.param(lambda r: {"command_policy": {k: v for k, v in r.items() if k != "causes_omitted"}}, False, id="missing_key"),
        # AD-1328 S2b: v2 is the right schema now, so the wrong one this forges is the old v1.
        pytest.param(lambda r: {"command_policy": {**r, "schema": "probos.command_policy.record/v1"}}, False, id="wrong_schema"),
        pytest.param(lambda r: {"command_policy": {**r, "decision": "maybe"}}, False, id="bad_decision"),
        pytest.param(lambda r: {"command_policy": {**r, "call_site": "elsewhere"}}, False, id="bad_site"),
        pytest.param(lambda r: {"command_policy": {**r, "decision": ["allow"]}}, False, id="unhashable_decision"),
        pytest.param(lambda r: {"command_policy": {**r, "call_site": {"site": "run_command_tool"}}}, False, id="unhashable_site"),
        pytest.param(lambda r: {"command_policy": {**r, "causes": [object()]}}, False, id="not_json"),
        pytest.param(lambda r: {"command_policy": {**r, "policy_digest": float("nan")}}, False, id="not_finite"),
        pytest.param(lambda r: {"command_policy": {**r, "matched_rules": ["x" * MAX_RECORD_CHARS]}}, False, id="too_long"),
        pytest.param(lambda r: [r], False, id="metadata_not_dict"),
        pytest.param(lambda r: OrderedDict(command_policy=r), False, id="metadata_dict_subclass"),
        pytest.param(lambda r: {"command_policy": [r]}, False, id="record_not_dict"),
        pytest.param(lambda r: {"command_policy": OrderedDict(r)}, False, id="record_dict_subclass"),
        pytest.param(lambda r: {}, False, id="no_record"),
    ],
)
def test_record_validator(build: Callable[[dict], object], accepted: bool) -> None:
    record = _recorded()
    result = SimpleNamespace(metadata=build(record))

    checked = command_policy_record_of(result, tool_id=RUN_COMMAND_TOOL_ID)

    if accepted:
        assert checked == record  # the gate's own record passes...
        assert checked is not record  # ...as a copy: editing it leaves the gate's record alone
        checked["matched_rules"].append("tampered")
        assert record["matched_rules"] == ["no-curl"]
    else:
        assert checked is None  # anything else is dropped, never repaired


def test_record_validator_without_metadata() -> None:
    assert command_policy_record_of(SimpleNamespace(metadata={"command_policy": _recorded()}), tool_id=RUN_COMMAND_TOOL_ID) is not None  # control
    assert command_policy_record_of(SimpleNamespace(), tool_id=RUN_COMMAND_TOOL_ID) is None
    assert command_policy_record_of(SimpleNamespace(metadata=None), tool_id=RUN_COMMAND_TOOL_ID) is None
    assert command_policy_record_of(object(), tool_id=RUN_COMMAND_TOOL_ID) is None
    assert command_policy_record_of(None, tool_id=RUN_COMMAND_TOOL_ID) is None


def test_policy_result_metadata() -> None:
    gate = _gate(_policy(_rule("no-curl", ["curl"], "forbid"), _rule("echo-ok", ["echo"], "allow"), unmatched="allow"))
    refused = _judge(gate, "curl x")
    allowed = _judge(gate, "echo x")
    assert refused.status == allowed.status == "evaluated"  # premise: both are evaluated verdicts

    assert policy_result_metadata(None) == {}
    assert policy_result_metadata(NO_POLICY) == {}
    assert policy_result_metadata(refused) == {"command_policy": refused.record}
    assert policy_result_metadata(allowed) == {"command_policy": allowed.record}
    assert allowed.record["decision"] == "allow"  # an allowed command is recorded too

    # across the seam: the metadata a result carries is what the AD-1224 validator hands the sink
    for verdict in (refused, allowed):
        result = SimpleNamespace(metadata=policy_result_metadata(verdict))
        assert command_policy_record_of(result, tool_id=RUN_COMMAND_TOOL_ID) == verdict.record


def test_refusal_log_names_the_rules_not_the_command(caplog: pytest.LogCaptureFixture) -> None:
    gate = _gate(_policy(_rule("no-curl", ["curl"], "forbid"), unmatched="allow"))
    with caplog.at_level(logging.INFO, logger="probos.execution.command_gate"):
        _judge(gate, "echo SENTINEL-7Q")  # control: a command that runs logs nothing
        assert [r for r in caplog.records if r.name == "probos.execution.command_gate"] == []
        _judge(gate, "curl SENTINEL-7Q")
    logged = [r.getMessage() for r in caplog.records if r.name == "probos.execution.command_gate"]
    assert len(logged) == 1
    assert "forbids" in logged[0] and "run_command_tool" in logged[0] and "no-curl" in logged[0]
    assert "SENTINEL-7Q" not in logged[0]


# --------------------------------------------------------------------------------------
# The call site decides how the same line is read
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("platform", "site", "dialect"), _SITE_MATRIX)
def test_judge_records_the_dialect_of_its_call_site(platform: str, site: CallSite, dialect: str) -> None:
    gate = _gate(_policy(_rule("no-curl", ["curl"], "forbid"), unmatched="allow"), platform=platform)
    assert _judge(gate, "echo hi", site=site).runs is True  # the accepted neighbour first
    verdict = _judge(gate, "curl x", site=site)
    assert verdict.evaluation.dialect == dialect
    assert verdict.record["dialect"] == dialect
    assert verdict.record["call_site"] == site


def test_the_same_line_is_read_in_the_dialect_of_its_call_site() -> None:
    gate = _gate(_policy(_rule("no-curl", ["curl"], "forbid"), unmatched="allow"), platform="win32")
    semicolon = "echo a; curl x"
    ampersand = "echo a & curl x"

    # the tool's cmd reads `&` and refuses an unquoted `;`; the agent's PowerShell is the other way round
    assert _judge(gate, ampersand, site="run_command_tool").decision == "forbid"
    assert _judge(gate, semicolon, site="run_command_tool").evaluation.unparseable is not None
    assert _judge(gate, semicolon, site="shell_command_agent").decision == "forbid"
    assert _judge(gate, ampersand, site="shell_command_agent").evaluation.unparseable is not None
    # premise: the lines that are read were read as two commands, the second of them the forbidden one
    for line, site in ((ampersand, "run_command_tool"), (semicolon, "shell_command_agent")):
        verdict = _judge(gate, line, site=site)
        assert [part.segment.tokens[0] for part in verdict.evaluation.segments] == ["echo", "curl"]
        assert [(cause.kind, cause.segment) for cause in verdict.causes] == [("rule", 1)]


# --------------------------------------------------------------------------------------
# 16. What `probos doctor` reports
# --------------------------------------------------------------------------------------


def _gate_builds(config: object, platform: str) -> bool:
    try:
        CommandPolicyGate(config, platform=platform, which=_FakeWhich())  # type: ignore[arg-type]
    except (CommandPolicySelfTestError, TypeError):
        return False
    return True


def _push_policy(*, holds: bool) -> CommandPolicyConfig:
    example = "git push origin main" if holds else "git status"
    return _policy(_rule("no-push", ["git", "push"], "forbid", match=[example], not_match=["git status"] if holds else []))


@pytest.mark.parametrize(
    ("make_config", "platform", "rule_name", "dialects", "failing", "error"),
    [
        pytest.param(CommandPolicyConfig, "win32", None, (), (), None, id="none"),
        pytest.param(lambda: _push_policy(holds=True), "win32", "no-push", ("cmd", "powershell"), (), None, id="passing"),
        pytest.param(lambda: _push_policy(holds=True), "linux", "no-push", ("posix",), (), None, id="passing_linux"),
        pytest.param(lambda: _push_policy(holds=False), "win32", "no-push", ("cmd", "powershell"), ("cmd", "powershell"), None, id="failing"),
        pytest.param(lambda: _push_policy(holds=False), "linux", "no-push", ("posix",), ("posix",), None, id="failing_linux"),
        pytest.param(_amp_policy, "win32", "amp", ("cmd", "powershell"), ("powershell",), None, id="failing_in_one_dialect"),
        pytest.param(_amp_policy, "linux", "amp", ("posix",), (), None, id="same_rule_passing_on_linux"),
        pytest.param(lambda: {"rules": []}, "win32", None, (), (), "dict", id="wrong_type"),
        pytest.param(lambda: None, "win32", None, (), (), "NoneType", id="wrong_type_none"),
    ],
)
def test_describe_command_policy(
    make_config: Callable[[], object],
    platform: str,
    rule_name: str | None,
    dialects: tuple[str, ...],
    failing: tuple[str, ...],
    error: str | None,
) -> None:
    config = make_config()

    report = describe_command_policy(config, platform=platform)  # never raises, whatever it is given

    assert report.rule_count == (len(config.rules) if isinstance(config, CommandPolicyConfig) else 0)
    assert report.digest == (policy_digest(config) if report.rule_count else None)
    assert [item.dialect for item in report.reports] == list(dialects)  # one report per dialect the call sites use
    assert [item.dialect for item in report.reports if not item.passed] == list(failing)
    if error is None:
        assert report.error is None
    else:
        assert error in report.error
    assert report.passed is (error is None and not failing)
    if isinstance(config, CommandPolicyConfig):
        assert report.reports == tuple(self_test(config, dialect=dialect) for dialect in dialects)  # the engine's own reports
    for item in report.reports:
        if not item.passed:  # the failing report names the rule
            assert [failure.rule for failure in item.failures] == [rule_name]
            assert f"rule '{rule_name}'" in item.failures[0].message
    # across the seam: what the doctor says is what startup does
    assert _gate_builds(config, platform) is report.passed


def test_describe_command_policy_never_raises_when_the_self_test_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _push_policy(holds=True)
    assert describe_command_policy(config, platform="win32").passed is True  # control: the same config passes

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(command_gate, "policy_digest", _boom)
    report = describe_command_policy(config, platform="win32")
    assert report.error == "RuntimeError: boom"
    assert report.rule_count == 1
    assert report.digest is None
    assert report.reports == ()
    assert report.passed is False


# --------------------------------------------------------------------------------------
# 16. S2a repair r1 (R1-M1): the judged object, the cmd lookup, PowerShell, and the typed record projection
# --------------------------------------------------------------------------------------


class _Stateful:
    """Not text: its ``__str__`` answers a different command each time it is called, and counts the calls."""

    def __init__(self) -> None:
        self.calls = 0

    def __str__(self) -> str:
        self.calls += 1
        return "echo hi"


class _CountingStr(str):
    """A ``str`` subclass whose ``__str__`` is not its value: a caller that converts it runs another command."""

    calls = 0

    def __str__(self) -> str:
        self.calls += 1
        return "echo hi"


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda: 5, id="int"),
        pytest.param(lambda: b"echo hi", id="bytes"),
        pytest.param(lambda: _CountingStr("curl x"), id="str_subclass"),
        pytest.param(_Stateful, id="stateful"),
    ],
)
def test_r1_judge_takes_exactly_a_str(make: Callable[[], object]) -> None:
    gate = _gate(_policy(_rule("no-curl", ["curl"], "forbid"), unmatched="allow"))
    control = _judge(gate, "echo hi")
    assert control.decision == "allow" and control.runs  # control: text is judged
    value = make()

    with pytest.raises(TypeError, match="command_policy_command_type_invalid"):
        _judge(gate, value)  # type: ignore[arg-type]
    assert getattr(value, "calls", 0) == 0  # the gate never converted it

    unconfigured = _gate(CommandPolicyConfig())
    assert _judge(unconfigured, value) is NO_POLICY  # type: ignore[arg-type]  # no policy: nothing is read, nothing converted
    assert getattr(value, "calls", 0) == 0


_WORK = "C:\\work"
_D1 = "C:\\d1"
_D2 = "C:\\d2"
_UNC = "\\\\srv\\share"
_DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"
_ALL_EXTENSIONS = (".COM", ".EXE", ".BAT", ".CMD")


def _cands(directory: str, extensions: tuple[str, ...] = _ALL_EXTENSIONS, name: str = "tool") -> list[str]:
    """The files ``cmd`` would look for ``name`` as in ``directory``, in order."""
    return [ntpath.join(directory, name + extension) for extension in extensions]


@pytest.mark.parametrize(
    ("name", "cwd", "path", "pathext", "files", "answer", "probes"),
    [
        pytest.param(
            "tool", _WORK, _D1, _DEFAULT_PATHEXT, {f"{_WORK}\\tool.BAT", f"{_D1}\\tool.EXE"},
            f"{_WORK}\\tool.BAT", _cands(_WORK)[:3], id="cwd_first",
        ),
        pytest.param(
            "tool", _WORK, f"{_D1};{_D2}", _DEFAULT_PATHEXT, {f"{_D1}\\tool.CMD", f"{_D2}\\tool.EXE"},
            f"{_D1}\\tool.CMD", _cands(_WORK) + _cands(_D1), id="path_order",
        ),
        pytest.param(
            "tool", _WORK, _D1, _DEFAULT_PATHEXT, {f"{_D1}\\tool.BAT", f"{_D1}\\tool.CMD"},
            f"{_D1}\\tool.BAT", _cands(_WORK) + _cands(_D1)[:3], id="pathext_order_default",
        ),
        pytest.param(
            "tool", _WORK, _D1, ".CMD;.BAT", {f"{_D1}\\tool.BAT", f"{_D1}\\tool.CMD"},
            f"{_D1}\\tool.CMD", _cands(_WORK, (".CMD", ".BAT")) + _cands(_D1, (".CMD",)), id="pathext_order_custom",
        ),
        pytest.param(
            "tool", _WORK, _D1, _DEFAULT_PATHEXT, {f"{_D1}\\tool.ps1"},
            None, _cands(_WORK) + _cands(_D1), id="never_ps1",
        ),
        pytest.param(
            "tool", _WORK, f"{_D1};;{_D2}", _DEFAULT_PATHEXT, {f"{_D2}\\tool.EXE"},
            f"{_D2}\\tool.EXE", _cands(_WORK) + _cands(_D1) + _cands(_D2)[:2], id="empty_entry_skipped",
        ),
        pytest.param(
            "tool", _WORK, f"bin;{_D2}", _DEFAULT_PATHEXT, {"bin\\tool.EXE", f"{_D2}\\tool.EXE"},
            None, _cands(_WORK), id="relative_entry_before_hit",
        ),
        pytest.param(
            "tool", _WORK, f"{_D1};bin", _DEFAULT_PATHEXT, {f"{_D1}\\tool.EXE", "bin\\tool.EXE"},
            f"{_D1}\\tool.EXE", _cands(_WORK) + _cands(_D1)[:2], id="relative_entry_after_hit",
        ),
        pytest.param(
            "tool", _WORK, f'"{_D1}";{_D2}', _DEFAULT_PATHEXT, {f"{_D2}\\tool.EXE", f'"{_D1}"\\tool.EXE'},
            None, _cands(_WORK), id="quoted_entry_before_hit",
        ),
        pytest.param(
            "tool", _WORK, f"%T%;{_D2}", _DEFAULT_PATHEXT, {f"{_D2}\\tool.EXE", "%T%\\tool.EXE"},
            None, _cands(_WORK), id="percent_entry_before_hit",
        ),
        pytest.param(
            "tool", _WORK, _UNC, _DEFAULT_PATHEXT, {f"{_UNC}\\tool.EXE"},
            f"{_UNC}\\tool.EXE", _cands(_WORK) + _cands(_UNC)[:2], id="unc_entry",
        ),
        pytest.param("tool.exe", _WORK, _D1, _DEFAULT_PATHEXT, {f"{_WORK}\\tool.exe.EXE", f"{_D1}\\tool.exe.EXE"}, None, [], id="name_with_extension"),
        pytest.param("bin\\tool", _WORK, _D1, _DEFAULT_PATHEXT, {f"{_WORK}\\bin\\tool.EXE", f"{_D1}\\bin\\tool.EXE"}, None, [], id="name_with_path"),
        pytest.param("tool", _WORK, _D1, None, {f"{_WORK}\\tool.EXE", f"{_D1}\\tool.EXE"}, None, [], id="missing_pathext"),
        pytest.param("tool", _WORK, _D1, "COM;.EXE", {f"{_WORK}\\tool.EXE", f"{_D1}\\tool.EXE"}, None, [], id="malformed_pathext"),
        pytest.param("tool", "work", _D1, _DEFAULT_PATHEXT, {f"{_D1}\\tool.EXE", "work\\tool.EXE"}, None, [], id="relative_cwd"),
    ],
)
def test_r1_cmd_lookup(
    name: str, cwd: str, path: str, pathext: str | None, files: set[str], answer: str | None, probes: list[str],
) -> None:
    which = _FakeWhich(fallback="C:\\fake\\tool.EXE")
    is_file = _RecordingIsFile(files)
    resolve = make_program_resolver(dialect="cmd", search_path=path, cwd=cwd, pathext=pathext, which=which, is_file=is_file)

    assert resolve(name) == answer
    assert is_file.calls == probes  # each probe, in order, up to the answer; none past a proof that cannot be made
    assert not any(probe.lower().endswith(".ps1") for probe in is_file.calls)  # cmd never runs a .ps1
    assert which.calls == []  # cmd never calls which


@pytest.mark.parametrize("cwd", [None, ""])
def test_r1_cmd_without_cwd_starts_in_this_process_directory(
    cwd: str | None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    is_file = _RecordingIsFile()
    resolve = make_program_resolver(
        dialect="cmd", search_path="C:\\P", cwd=cwd, pathext=".EXE", which=_FakeWhich(), is_file=is_file,
    )

    assert resolve("tool") is None

    if sys.platform == "win32":  # host-named: this process's directory is a Windows path here, and it leads
        assert is_file.calls == [ntpath.join(os.getcwd(), "tool.EXE"), "C:\\P\\tool.EXE"]
        assert ntpath.dirname(is_file.calls[0]) == os.getcwd()
    else:  # os.getcwd() is not a Windows path: nothing after it is proven, so nothing is probed
        assert is_file.calls == []


def test_r1_powershell_never_answers() -> None:
    pin = "C:\\tools\\git.EXE"
    which = _FakeWhich(fallback=pin)
    is_file = _RecordingIsFile({pin})
    kwargs: dict[str, object] = {"search_path": "C:\\tools", "cwd": _WORK, "pathext": ".EXE", "which": which, "is_file": is_file}
    assert make_program_resolver(dialect="cmd", **kwargs)("git") == pin  # type: ignore[arg-type]  # control: cmd names the file
    assert is_file.calls == [f"{_WORK}\\git.EXE", pin]
    is_file.calls.clear()

    assert make_program_resolver(dialect="powershell", **kwargs)("git") is None  # type: ignore[arg-type]
    assert which.calls == [] and is_file.calls == []  # neither probe would have answered, and neither was asked

    # through a win32 gate with a pin
    config = _policy(_rule("pinned-git", ["git"], "allow", host_executable=[pin]), unmatched="escalate")
    gate_where = _FakeWhich(fallback=pin)
    gate_files = _RecordingIsFile({pin})
    gate = _gate(config, platform="win32", which=gate_where, is_file=gate_files)

    def judge(command: str, site: CallSite) -> CommandGateVerdict:
        return gate.judge(command, site=site, search_path="C:\\tools", cwd=_WORK, pathext=".EXE")

    bare = judge("git status", "shell_command_agent")
    assert bare.decision == "forbid" and bare.runs is False  # PowerShell does not find the pin for a bare name
    assert pin in bare.refusal_message  # and names the path to write instead
    assert bare.canonical.parts[0] == "git"  # the key is of the bare name, not of a path
    written = judge(f"{pin} status", "shell_command_agent")
    assert written.decision == "allow" and written.runs is True  # premise: S1 reads the written path as the pinned one
    assert gate_files.calls == [] and gate_where.calls == []  # PowerShell never looked a program up

    at_tool = judge("git status", "run_command_tool")
    assert at_tool.decision == "allow" and at_tool.runs is True  # cmd proves the same bare name
    assert gate_files.calls == [f"{_WORK}\\git.EXE", pin]
    assert gate_where.calls == []


@pytest.mark.parametrize("answer", ["git", "./git", "bin/git", "/usr/bin/git"])
def test_r1_posix_lookup_needs_an_absolute_answer(answer: str) -> None:
    resolve = make_program_resolver(dialect="posix", search_path="/usr/bin", cwd=None, which=_FakeWhich(fallback=answer))
    assert resolve("git") == ("/usr/bin/git" if answer == "/usr/bin/git" else None)


def _forge(**fields: object) -> Callable[[dict], dict]:
    return lambda record: {**record, **fields}


def _forge_cause(**fields: object) -> Callable[[dict], dict]:
    return lambda record: {**record, "causes": [{**record["causes"][0], **fields}]}


def _a_cause(index: int) -> dict:
    return {"kind": "rule", "segment": index, "rule": "no-curl"}


_FORGERIES = [
    # AD-1328 S2b: v2 is the right schema now, so the forged one is the old v1 (the id was schema_v2).
    pytest.param(_forge(schema="probos.command_policy.record/v1"), id="schema_v1"),
    pytest.param(_forge(call_site="shell_command_agent"), id="call_site_agent"),
    pytest.param(_forge(decision="Allow"), id="decision_case"),
    pytest.param(_forge(dialect="powershell"), id="dialect_powershell"),
    pytest.param(_forge(dialect="bash"), id="dialect_bash"),
    pytest.param(_forge(canonical_kind="argv x"), id="kind_text"),
    pytest.param(_forge(policy_digest="a" * 63), id="digest_63"),
    pytest.param(_forge(policy_digest="ABCDEF" * 10 + "ABCD"), id="digest_upper"),
    pytest.param(_forge(policy_digest="SENTINEL text"), id="digest_text"),
    pytest.param(_forge(canonical_key="echo REVIEW_RAW_COMMAND --token=abc"), id="canonical_key_command_text"),
    *[
        pytest.param(_forge(**{field: value}), id=f"{field}_{label}")
        for field in ("matched_rules_omitted", "causes_omitted")
        for label, value in (("true", True), ("negative", -1), ("over_max", 2**31), ("float", 1.0), ("text", "1"))
    ],
    pytest.param(_forge(matched_rules=["a" * 65]), id="rule_65_chars"),
    pytest.param(_forge(matched_rules=["Has-Upper"]), id="rule_upper"),
    pytest.param(_forge(matched_rules=["two words"]), id="rule_space"),
    pytest.param(_forge(matched_rules=[7]), id="rule_int"),
    pytest.param(_forge(matched_rules=[f"rule-{index}" for index in range(9)]), id="rules_nine"),
    pytest.param(_forge(matched_rules=("no-curl",)), id="rules_tuple"),
    pytest.param(_forge(causes="rule"), id="causes_string"),
    pytest.param(_forge(causes=[_a_cause(index) for index in range(9)]), id="causes_nine"),
    pytest.param(_forge_cause(text="curl evil --token=abc"), id="cause_extra_key"),
    pytest.param(_forge_cause(kind="evil", rule=None), id="cause_kind_evil"),
    pytest.param(_forge_cause(kind="rule", rule=None), id="cause_rule_without_name"),
    pytest.param(_forge_cause(kind="unmatched"), id="cause_unmatched_with_name"),
    pytest.param(_forge_cause(segment=None), id="cause_rule_without_segment"),
    pytest.param(_forge_cause(segment=-1), id="cause_segment_negative"),
    pytest.param(_forge_cause(segment=True), id="cause_segment_bool"),
    pytest.param(_forge_cause(rule="curl evil --token=abc"), id="cause_rule_text"),
]


@pytest.mark.parametrize("forge", _FORGERIES)
def test_r1_record_projection_admits_only_typed_fields(forge: Callable[[dict], dict]) -> None:
    record = _recorded()
    control = command_policy_record_of(SimpleNamespace(metadata={"command_policy": record}), tool_id=RUN_COMMAND_TOOL_ID)
    assert control == record  # control: the genuine record is accepted, equal...
    assert control is not record and control["matched_rules"] is not record["matched_rules"]
    assert control["causes"] is not record["causes"] and control["causes"][0] is not record["causes"][0]  # ...and new objects

    forged = forge(record)
    assert forged != record  # premise: the forgery changed a field
    assert command_policy_record_of(SimpleNamespace(metadata={"command_policy": forged}), tool_id=RUN_COMMAND_TOOL_ID) is None


def test_r1_record_projection_accepts_each_closed_cause_shape() -> None:
    record = _recorded()
    causes = [
        {"kind": "rule", "segment": 0, "rule": "no-curl"},
        {"kind": "unmatched", "segment": 1, "rule": None},
        {"kind": "unparseable", "segment": None, "rule": None},
        {"kind": "unparseable", "segment": 2, "rule": None},
    ]
    checked = command_policy_record_of(
        SimpleNamespace(metadata={"command_policy": {**record, "causes": causes}}), tool_id=RUN_COMMAND_TOOL_ID,
    )
    assert checked == {**record, "causes": causes}  # control for the segment and rule rows above: these shapes are admitted


class _RunCommandId(str):
    """A ``str`` subclass equal to 'run_command' that is not exactly a ``str``."""


@pytest.mark.parametrize(
    "tool_id",
    [
        pytest.param("write_file", id="write_file"),
        pytest.param(None, id="none"),
        pytest.param(_RunCommandId("run_command"), id="str_subclass_of_run_command"),
        pytest.param("", id="empty"),
    ],
)
def test_r1_record_projection_reads_only_the_run_command_tool(tool_id: object) -> None:
    result = SimpleNamespace(metadata={"command_policy": _recorded()})
    assert tool_id != RUN_COMMAND_TOOL_ID or type(tool_id) is not str  # premise: nothing here is exactly the tool id
    assert command_policy_record_of(result, tool_id="run_command") == _recorded()  # control: the genuine record is read
    assert command_policy_record_of(result, tool_id=tool_id) is None
    assert RUN_COMMAND_TOOL_ID == RunCommandTool.tool_id == "run_command"


def test_r1_record_rule_name_grammar_is_the_config_grammar() -> None:
    assert command_gate._RECORD_RULE_NAME.pattern == operations._COMMAND_RULE_NAME_PATTERN


def _twenty_rule_record() -> dict:
    names = [chr(ord("a") + index) + "x" * 63 for index in range(20)]
    programs = [f"p{index:02d}" for index in range(20)]
    gate = _gate(_policy(*[_rule(name, [program], "forbid") for name, program in zip(names, programs)], unmatched="allow"))
    record = _judge(gate, "; ".join(programs)).record
    assert record is not None
    return record


def test_r1_compact_record() -> None:
    record = _twenty_rule_record()
    assert len(record["matched_rules"]) == 8 and record["matched_rules_omitted"] == 12  # premise: M1 #13's record
    assert len(record["causes"]) == 8 and record["causes_omitted"] == 12
    before = json.dumps(record, sort_keys=True)

    compact = compact_command_policy_record(record)

    assert compact["matched_rules"] == [] and compact["causes"] == []
    assert compact["matched_rules_omitted"] == 20 and compact["causes_omitted"] == 20  # the entries moved into the counts
    kept = set(_RECORD_KEYS) - {"matched_rules", "matched_rules_omitted", "causes", "causes_omitted"}
    # AD-1328 S2b: this pinned the seven kept keys of the v1 record; "approval" is kept too (the contract's "unchanged" missed it).
    assert len(kept) == 8
    assert {key: compact[key] for key in compact if key in kept} == {key: record[key] for key in kept}
    assert set(compact) == _RECORD_KEYS
    assert json.dumps(record, sort_keys=True) == before  # the full record is left as it was
    assert command_policy_record_of(SimpleNamespace(metadata={"command_policy": compact}), tool_id=RUN_COMMAND_TOOL_ID) == compact


def test_r1_the_largest_admitted_record_is_within_the_bound() -> None:
    top = 2**31 - 1
    names = [f"{index}" + "x" * 63 for index in range(8)]
    assert all(len(name) == 64 for name in names)
    record = {
        **_recorded(),
        "decision": "escalate",
        "dialect": "posix",
        "canonical_kind": "script",
        "policy_digest": "0123456789abcdef" * 4,
        "canonical_key": "fedcba9876543210" * 4,
        "matched_rules": names,
        "matched_rules_omitted": top,
        "causes": [{"kind": "rule", "segment": top, "rule": name} for name in names],
        "causes_omitted": top,
    }

    checked = command_policy_record_of(SimpleNamespace(metadata={"command_policy": record}), tool_id=RUN_COMMAND_TOOL_ID)

    assert checked == record  # accepted
    assert len(json.dumps(record, sort_keys=True)) <= MAX_RECORD_CHARS  # and the typed maximum is within the bound
    over = {**record, "matched_rules": ["x" * 65, *names[1:]]}
    assert command_policy_record_of(SimpleNamespace(metadata={"command_policy": over}), tool_id=RUN_COMMAND_TOOL_ID) is None


# --------------------------------------------------------------------------------------
# S2a repair r2, R2-M1: the PATHEXT grammar (F1), the built-in lists (F2) and S1 r3's two causes (H7)
# --------------------------------------------------------------------------------------

_R2_ENTRIES_65 = ";".join(f".E{i}" for i in range(64)) + ";.CMD"
_R2_ENTRIES_64 = ";".join(f".E{i}" for i in range(63)) + ";.CMD"
_R2_TOOL_FILES = {"C:\\d1\\tool.CMD", "C:\\d1\\tool.BAT"}


def _r2_pathext_probes(value: str, answer: str) -> list[str]:
    """The probes the lookup makes for ``value``: every extension in the cwd, then each in C:\\d1 up to the answer."""
    extensions = [entry.upper() for entry in value.split(";")]
    probes = [ntpath.join(_WORK, "tool" + extension) for extension in extensions]
    for extension in extensions:
        probes.append(ntpath.join(_D1, "tool" + extension))
        if probes[-1] == answer:
            break
    return probes


_R2_PATHEXT_REFUSED = [
    pytest.param(".EXE; .CMD;.BAT", id="lead_blank"),
    pytest.param(".EXE;.CMD ;.BAT", id="trail_blank"),
    pytest.param(".E XE;.CMD", id="inner_blank"),
    pytest.param(".EXE;\t.CMD", id="tab"),
    pytest.param(".EXE;.CMD\n", id="newline"),
    pytest.param(".EXE;;.CMD", id="empty_entry"),
    pytest.param(";.CMD", id="leading_semicolon"),
    pytest.param(".CMD;", id="trailing_semicolon"),
    pytest.param("", id="empty"),
    pytest.param(".EXE;.", id="bare_dot"),
    pytest.param('".CMD"', id="quoted"),
    pytest.param("%PE%;.CMD", id="percent"),
    pytest.param(".E_X;.CMD", id="underscore"),
    pytest.param(".ÉXE;.CMD", id="non_ascii"),
    pytest.param(".ＣＭＤ", id="fullwidth"),
    pytest.param(".ABCDEFGHIJKLMNOP;.CMD", id="entry_16_chars"),
    pytest.param(_R2_ENTRIES_65, id="entries_65"),
]


@pytest.mark.parametrize(
    ("value", "answer"),
    [
        *[pytest.param(param.values[0], None, id=param.id) for param in _R2_PATHEXT_REFUSED],
        pytest.param(".EXE;.CMD;.BAT", "C:\\d1\\tool.CMD", id="plain"),
        pytest.param(".exe;.cmd", "C:\\d1\\tool.CMD", id="lower_case"),
        pytest.param(".CMD;.CMD;.BAT", "C:\\d1\\tool.CMD", id="duplicates"),
        pytest.param(_R2_ENTRIES_64, "C:\\d1\\tool.CMD", id="entries_64"),
        pytest.param(".ABCDEFGHIJKLMNO;.BAT", "C:\\d1\\tool.BAT", id="entry_15_chars"),
    ],
)
def test_r2_cmd_pathext_grammar(value: str, answer: str | None) -> None:
    which = _FakeWhich(fallback="C:\\fake\\tool.EXE")
    is_file = _RecordingIsFile(_R2_TOOL_FILES)
    resolve = make_program_resolver(dialect="cmd", search_path=_D1, cwd=_WORK, pathext=value, which=which, is_file=is_file)

    assert resolve("tool") == answer
    if answer is None:  # cmd keeps a blank in an extension and reads nothing it cannot name: nothing is proven
        assert is_file.calls == []  # and no file was probed
    else:
        assert is_file.calls == _r2_pathext_probes(value, answer)  # upper-case, in order, up to the answer
    assert which.calls == []


def test_r2_cmd_internal_commands_never_answer() -> None:
    internal = [*sorted(command_gate._CMD_INTERNAL_COMMANDS), "ECHO", "Echo", "echo+x", "echo,", "echo=", "echo(", "echo["]
    for name in internal:
        is_file = _RecordingIsFile({f"C:\\d1\\{name}.CMD"})
        resolve = make_program_resolver(
            dialect="cmd", search_path=_D1, cwd=_WORK, pathext=".CMD", which=_FakeWhich(), is_file=is_file,
        )
        assert resolve(name) is None, f"{name!r}: cmd runs its internal command, so no file answers"
        assert is_file.calls == [], f"{name!r}: an internal command is never looked up as a file"

    for name in ("echo1", "echoes", "xecho", "cdx", "tool"):  # a word that only starts like one is a program
        is_file = _RecordingIsFile({f"C:\\d1\\{name}.CMD"})
        resolve = make_program_resolver(
            dialect="cmd", search_path=_D1, cwd=_WORK, pathext=".CMD", which=_FakeWhich(), is_file=is_file,
        )
        assert resolve(name) == f"C:\\d1\\{name}.CMD", f"{name!r}: not an internal command"
        assert is_file.calls == [f"C:\\work\\{name}.CMD", f"C:\\d1\\{name}.CMD"], f"{name!r}: probed cwd then PATH"


def test_r2_posix_builtins_never_answer() -> None:
    for name in sorted(command_gate._POSIX_SHELL_BUILTINS):
        which = _FakeWhich(fallback="/usr/bin/x")
        resolve = make_program_resolver(dialect="posix", search_path="/usr/bin", cwd=None, which=which)
        assert resolve(name) is None, f"{name!r}: /bin/sh runs its built-in, not a file"
        assert which.calls == [], f"{name!r}: a built-in is never looked up"

    for name in ("git", "ECHO", "echo.cmd", "printf2"):  # exact case, exact name
        which = _FakeWhich(fallback="/usr/bin/x")
        resolve = make_program_resolver(dialect="posix", search_path="/usr/bin", cwd=None, which=which)
        assert resolve(name) == "/usr/bin/x", f"{name!r}: not a built-in"
        assert which.calls == [(name, "/usr/bin")], f"{name!r}: one lookup"


def test_r2_builtin_lists_are_pinned() -> None:
    assert command_gate._CMD_INTERNAL_COMMANDS == command_policy._CMD_INTERNAL  # H9: S1's reviewed list; a test may read it
    assert len(command_gate._CMD_INTERNAL_COMMANDS) == 45

    literal = frozenset({
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
    assert command_gate._POSIX_SHELL_BUILTINS == literal
    assert len(command_gate._POSIX_SHELL_BUILTINS) == 96

    special = {"break", ":", "continue", ".", "eval", "exec", "exit", "export", "readonly", "return", "set", "shift", "times", "trap", "unset"}
    intrinsic = {"alias", "bg", "cd", "command", "fc", "fg", "getopts", "hash", "jobs", "kill", "read", "type", "ulimit", "umask", "unalias", "wait"}
    assert special <= command_gate._POSIX_SHELL_BUILTINS  # POSIX 2.15 special built-ins
    assert intrinsic <= command_gate._POSIX_SHELL_BUILTINS  # POSIX 1.7 intrinsic utilities


@pytest.mark.parametrize("dialect", ["cmd", "posix"])
def test_r2_a_pinned_builtin_name_never_proves(dialect: str) -> None:
    config = _policy(_rule("echo-pinned", ["echo"], "allow", host_executable=[
        "C:\\d1\\echo.CMD" if dialect == "cmd" else "/bin/echo",
    ]), unmatched="escalate")

    if dialect == "cmd":
        pin = "C:\\d1\\echo.CMD"
        is_file = _RecordingIsFile({pin})
        gate = _gate(config, platform="win32", is_file=is_file)  # premise: the gate builds with the pin

        def judge(command: str) -> CommandGateVerdict:
            return gate.judge(command, site="run_command_tool", search_path=_D1, cwd=_WORK, pathext=".CMD")

        bare = judge("echo hi")
        assert bare.decision == "forbid" and bare.runs is False  # cmd runs its internal echo, never the pinned file
        assert f"run the pinned executable: {pin}" in bare.refusal_message
        assert is_file.calls == []  # an internal command is not looked up
        written = judge(f"{pin} hi")
        assert written.decision == "allow"  # the written path is the file
        assert bare.canonical.kind == "script" and written.canonical.kind == "script"  # S1 reads an internal stem as a script
    else:
        pin = "/bin/echo"
        which = _FakeWhich(fallback=pin)
        gate = _gate(config, platform="linux", which=which)  # premise: the gate builds with the pin
        for site in ("run_command_tool", "shell_command_agent"):
            bare = gate.judge("echo hi", site=site, search_path="/bin", cwd=None)
            assert bare.decision == "forbid" and bare.runs is False, site  # /bin/sh runs its built-in
            assert pin in bare.refusal_message, site
            assert bare.canonical.parts[0] == "echo", site
            written = gate.judge("/bin/echo hi", site=site, search_path="/bin", cwd=None)
            assert written.decision == "allow", site
            assert written.canonical.parts[0] == "/bin/echo", site  # the two keys differ
            assert written.canonical.key != bare.canonical.key, site
        assert which.calls == []


def test_r2_unparseable_segment_with_matches_gives_both_causes() -> None:
    config = _policy(_rule("no-tool", ["tool"], "forbid"), _rule("no-curl", ["curl"], "forbid"), unmatched="allow")
    gate = _gate(config, platform="linux")

    verdict = gate.judge("tool curl", site="run_command_tool", search_path="/usr/bin")

    first = verdict.evaluation.segments[0]
    assert first.basis == "unparseable"  # premise (S1 r3): a segment it could not read ...
    assert [match.rule for match in first.matches] == ["no-tool"]  # ... that a rule still matched
    assert verdict.decision == "forbid"
    expected = [("rule", 0, "no-tool"), ("unparseable", 0, None)]
    assert [(cause.kind, cause.segment, cause.rule) for cause in verdict.causes] == expected
    message = verdict.refusal_message
    assert "Rule 'no-tool'" in message and "could not read part 1" in message
    record = command_policy_record_of(ToolResult(metadata=policy_result_metadata(verdict)), tool_id=RUN_COMMAND_TOOL_ID)
    assert [(cause["kind"], cause["segment"], cause["rule"]) for cause in record["causes"]] == expected

    control = gate.judge("tool x", site="run_command_tool", search_path="/usr/bin")
    assert control.evaluation.segments[0].basis == "rule"
    assert [(cause.kind, cause.segment, cause.rule) for cause in control.causes] == [("rule", 0, "no-tool")]
