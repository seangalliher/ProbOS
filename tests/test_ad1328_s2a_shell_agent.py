"""AD-1328 S2a (#1530), M3: the shell agent and the red team's re-run under the command policy.

Tests only. The contract is ``prompts/ad-1328-s2a-command-policy-wiring.md`` ("Tests", M3). Nothing here starts a process
or reads the real PATH: ``ShellCommandAgent._run_sync`` and ``RedTeamAgent._run_verify_sync`` are replaced by recorders,
``build_command_env`` (where each agent module imports it) by a spy that answers a fixed PATH, and every gate is built
with a ``which`` that finds nothing. A gate takes its platform explicitly (``win32`` or ``linux``) wherever a test is about
a dialect. Two tests name their host dependence: the python rewrite is the host's (the gate is built for the host's own
platform, and the outcome is the same on every host), and the PowerShell unwrap patches ``sys.platform``.

Each test asserts its own premise (what the gate says about the very text it is about) and a control: the neighbour that
runs, so a test cannot pass because the whole machine refuses everything or runs nothing.

Mutation map (the contract's campaign of record, run on a scratch copy outside the repository): S1m ``if refusal is not
None:`` -> ``if False:`` in the shell agent is killed by #2 and also by #3, #5, #6 and #7; S2m ``if gate is None or not
gate.configured:`` -> ``if gate is None:`` in the shell agent by #1 alone (it is observable only through the extra
``build_command_env`` and ``judge`` calls, so #1 spies on both); R1 ``if refused is not None:`` -> ``if False:`` in the red
team by #8, and also by #10 and the addition at the end.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable
from typing import Any

import pytest

from probos.agents.red_team import RedTeamAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.cognitive.decomposer import _CAPABILITY_GAP_RE
from probos.config_models.operations import CommandPolicyConfig
from probos.execution.command_gate import (
    COMMAND_POLICY_UNAVAILABLE_MESSAGE,
    CommandGateVerdict,
    CommandPolicyGate,
)
from probos.execution.process_tree import ProcessTreeSlot
from probos.types import IntentMessage, IntentResult, VerificationResult

# --------------------------------------------------------------------------------------
# Helpers (the S1 shapes are copied, not imported: tests do not import each other)
# --------------------------------------------------------------------------------------


def _policy(*rules: dict, unmatched: str = "allow", **extra: object) -> CommandPolicyConfig:
    return CommandPolicyConfig.model_validate({"rules": list(rules), "unmatched_decision": unmatched, **extra})


def _rule(name: str, pattern: list, decision: str, **extra: object) -> dict:
    base = {"name": name, "pattern": pattern, "decision": decision, "justification": f"{name} because"}
    if decision == "forbid":
        base["alternative"] = "use the governed path"
    return {**base, **extra}


def _no_which(name: str, path: str | None = None) -> None:
    """A PATH lookup that finds nothing: no test here reads the real PATH."""
    return None


def _gate(config: CommandPolicyConfig, *, platform: str | None = None) -> CommandPolicyGate:
    """A gate for ``platform`` (this host's when None) whose program lookup never touches the real PATH."""
    return CommandPolicyGate(config, platform=sys.platform if platform is None else platform, which=_no_which)


# Plain justifications: the fixed frames and these words must not read as a capability gap (AD-1154 DD-2).
_FORBID_PUSH = _rule(
    "no-push", ["git", "push"], "forbid",
    justification="pushes go through the release agent", alternative="ask the release agent to push",
)
_ESCALATE_PUSH = _rule("ask-push", ["git", "push"], "escalate", justification="a push waits for the chain of command")
_ALLOW_GIT_STATUS = _rule("ok-git-status", ["git", "status"], "allow")
_PLAIN_NAME = "M3_PLAIN_NAME"  # a declared passthrough name: it only has to reach build_command_env
# The characters S1's closed grammar reads in an interpreter path, in both dialects a rewritten command is judged in. Anything
# else (a non-ASCII user name, a quote, one of $ & ; ( ) [ ] ` %) makes the rewritten text unparseable there, so the cause of
# the escalation is ``unparseable`` rather than ``unmatched``: the decision is the same, the cause is not.
_READABLE_INTERPRETER_PATH = re.compile(r"[A-Za-z0-9_.:/\\ -]+")


def _ran(command: str) -> dict[str, Any]:
    """What the recorder's ``_run_sync`` answers: the shape the real one returns on success."""
    return {"success": True, "data": {"stdout": "ok", "stderr": "", "exit_code": 0, "command": command}}


class _Runs:
    """Every ``(command, deadline, slot)`` ``ShellCommandAgent._run_sync`` was asked to run."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, Any]] = []

    def __call__(self, command: str, deadline: Any, slot: Any) -> dict[str, Any]:
        self.calls.append((command, deadline, slot))
        return _ran(command)

    @property
    def commands(self) -> list[str]:
        return [call[0] for call in self.calls]


class _Reruns:
    """Every ``(command, env, deadline, slot)`` ``RedTeamAgent._run_verify_sync`` was asked to re-run."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, Any, Any]] = []

    def __call__(self, command: str, env: Any, deadline: Any, slot: Any) -> tuple[int, str]:
        self.calls.append((command, env, deadline, slot))
        return (0, "ok")

    @property
    def commands(self) -> list[str]:
        return [call[0] for call in self.calls]


class _EnvSpy:
    """Stands in for ``build_command_env`` where an agent module imports it: records each call, answers a fixed PATH."""

    PATH = "/spy/bin"

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self, declared: Iterable[str] = (), *, source: Any = None, platform: str | None = None,
    ) -> dict[str, str]:
        self.calls.append(tuple(declared))
        return {"PATH": self.PATH}


class _JudgeSpy:
    """Wraps ``CommandPolicyGate.judge``: delegates, and records each call's arguments and the verdict it answered."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.verdicts: list[CommandGateVerdict] = []

    def reset(self) -> None:
        self.calls.clear()
        self.verdicts.clear()


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> _Runs:
    recorder = _Runs()
    monkeypatch.setattr(
        ShellCommandAgent, "_run_sync",
        lambda self, command, deadline=None, slot=None: recorder(command, deadline, slot),
    )
    return recorder


@pytest.fixture
def reruns(monkeypatch: pytest.MonkeyPatch) -> _Reruns:
    recorder = _Reruns()
    monkeypatch.setattr(
        RedTeamAgent, "_run_verify_sync",
        staticmethod(lambda command, env, deadline=None, slot=None: recorder(command, env, deadline, slot)),
    )
    return recorder


@pytest.fixture
def env_spy(monkeypatch: pytest.MonkeyPatch) -> _EnvSpy:
    spy = _EnvSpy()
    monkeypatch.setattr("probos.agents.shell_command.build_command_env", spy)
    monkeypatch.setattr("probos.agents.red_team.build_command_env", spy)
    return spy


@pytest.fixture
def judge_spy(monkeypatch: pytest.MonkeyPatch) -> _JudgeSpy:
    spy = _JudgeSpy()
    real_judge = CommandPolicyGate.judge

    def judge(
        self: CommandPolicyGate, command: str, *, site: str, search_path: str | None, cwd: str | None = None,
    ) -> CommandGateVerdict:
        verdict = real_judge(self, command, site=site, search_path=search_path, cwd=cwd)
        spy.calls.append({"command": command, "site": site, "search_path": search_path, "cwd": cwd})
        spy.verdicts.append(verdict)
        return verdict

    monkeypatch.setattr(CommandPolicyGate, "judge", judge)
    return spy


def _explode(
    self: CommandPolicyGate, command: str, *, site: str, search_path: str | None, cwd: str | None = None,
) -> CommandGateVerdict:
    raise RuntimeError("the judgement exploded")


def _env_explodes(declared: Iterable[str] = (), **kwargs: Any) -> dict[str, str]:
    raise RuntimeError("the environment builder exploded")


def _break_the_judgement(monkeypatch: pytest.MonkeyPatch, failure: str, module: str) -> None:
    """Make the policy's judgement raise: ``judge`` itself, or the ``build_command_env`` call made just before it."""
    if failure == "judge_raises":
        monkeypatch.setattr(CommandPolicyGate, "judge", _explode)
    else:
        monkeypatch.setattr(f"{module}.build_command_env", _env_explodes)


async def _verify(
    agent: RedTeamAgent, command: str, *, claimed_success: bool = True, claimed_stdout: str = "ok",
) -> VerificationResult:
    """The red team's verdict on a claimed run of ``command`` (exit 0, output ``claimed_stdout``), by its public entry."""
    intent = IntentMessage(intent="run_command", params={"command": command})
    claimed = IntentResult(
        intent_id=intent.id, agent_id="shell-1", success=claimed_success,
        result={"exit_code": 0, "stdout": claimed_stdout}, confidence=0.8,
    )
    return await agent.verify("shell-1", intent, claimed)


# --------------------------------------------------------------------------------------
# 1. No policy: byte-identical
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("gate_kind", ["no_gate", "unconfigured_gate"])
async def test_no_policy_is_byte_identical(
    runs: _Runs, env_spy: _EnvSpy, judge_spy: _JudgeSpy, gate_kind: str,
) -> None:
    """No gate, or a gate with no rules: ``_run_sync`` runs the command as today and nothing else is called. Kills S2m."""
    gate = None if gate_kind == "no_gate" else _gate(CommandPolicyConfig())
    if gate is not None:
        assert gate.configured is False  # premise: a gate with no rules is no policy
    agent = ShellCommandAgent(pool="shell", command_env_passthrough=(_PLAIN_NAME,), command_policy_gate=gate)

    result = await agent._run_command("git status")

    assert result == _ran("git status")  # the recorder's answer, unchanged
    assert runs.commands == ["git status"]
    _, deadline, slot = runs.calls[0]
    assert isinstance(deadline, float) and isinstance(slot, ProcessTreeSlot)  # the BF-893 hand-over, as before
    assert env_spy.calls == []  # only _run_sync builds the child's environment on this path, and it is replaced
    assert judge_spy.calls == []

    # control: a configured gate IS judged and builds the child's environment once, so the spies can see it
    governed = ShellCommandAgent(
        pool="shell", command_env_passthrough=(_PLAIN_NAME,),
        command_policy_gate=_gate(_policy(_rule("no-curl", ["curl"], "forbid"))),
    )
    assert await governed._run_command("git status") == _ran("git status")
    assert env_spy.calls == [(_PLAIN_NAME,)]
    assert len(judge_spy.calls) == 1
    assert runs.commands == ["git status", "git status"]


# --------------------------------------------------------------------------------------
# 2. forbid and escalate are not run
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("decision", ["forbid", "escalate"])
async def test_forbid_and_escalate_are_not_run(runs: _Runs, env_spy: _EnvSpy, decision: str) -> None:
    """A refused command is answered, not run; the answer names the rule, its justification and (forbid) the alternative."""
    rule = _FORBID_PUSH if decision == "forbid" else _ESCALATE_PUSH
    gate = _gate(_policy(rule))
    agent = ShellCommandAgent(pool="shell", command_policy_gate=gate)
    # premise: the policy itself refuses this very command at the agent's call site, by this rule
    verdict = gate.judge("git push", site="shell_command_agent", search_path=env_spy.PATH)
    assert (verdict.decision, verdict.runs) == (decision, False)
    assert [(cause.kind, cause.rule) for cause in verdict.causes] == [("rule", rule["name"])]

    result = await agent._run_command("git push")

    assert runs.calls == []
    assert result == {"success": False, "error": verdict.refusal_message}
    error = result["error"]
    assert f"Rule '{rule['name']}'" in error
    assert rule["justification"] in error
    if decision == "forbid":
        assert rule["alternative"] in error
    else:
        assert "no approval was requested" in error  # truthful: S2a asks nobody
    assert not _CAPABILITY_GAP_RE.search(error)

    # control: a command the policy does not refuse runs through the same agent
    assert await agent._run_command("git status") == _ran("git status")
    assert runs.commands == ["git status"]


# --------------------------------------------------------------------------------------
# 3. Through the intent
# --------------------------------------------------------------------------------------


async def test_through_handle_intent(runs: _Runs, env_spy: _EnvSpy) -> None:
    """The mesh path: ``handle_intent`` answers a refused command as a failed result naming the rule, running nothing."""
    gate = _gate(_policy(_ESCALATE_PUSH))
    agent = ShellCommandAgent(pool="shell", command_policy_gate=gate)
    intent = IntentMessage(intent="run_command", params={"command": "git push"})
    # premise: decide() plans to run it (git is one of its builtins on every host), so the refusal below is the policy's
    plan = await agent.decide(await agent.perceive(intent.__dict__))
    assert plan == {"action": "run", "command": "git push"}

    result = await agent.handle_intent(intent)

    assert isinstance(result, IntentResult)
    assert result.success is False
    assert result.result is None
    assert result.intent_id == intent.id and result.agent_id == agent.id
    assert result.error == gate.judge("git push", site="shell_command_agent", search_path=env_spy.PATH).refusal_message
    assert "ask-push" in result.error and "a push waits for the chain of command" in result.error
    assert runs.calls == []

    # control: the same intent path runs a command the policy does not refuse
    ran = await agent.handle_intent(IntentMessage(intent="run_command", params={"command": "git status"}))
    assert ran is not None and ran.success is True and ran.error is None
    assert ran.result == _ran("git status")["data"]
    assert runs.commands == ["git status"]


# --------------------------------------------------------------------------------------
# 4. The call site
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gate_platform", "dialect"), [("win32", "powershell"), ("linux", "posix")], ids=["win32", "linux"],
)
async def test_shell_agent_judges_at_its_own_call_site(
    runs: _Runs, env_spy: _EnvSpy, judge_spy: _JudgeSpy, gate_platform: str, dialect: str,
) -> None:
    """The agent asks the gate as ``shell_command_agent`` (PowerShell on Windows, POSIX elsewhere), on the child's PATH."""
    gate = _gate(_policy(_ALLOW_GIT_STATUS, unmatched="escalate"), platform=gate_platform)
    assert gate.dialect_for("shell_command_agent") == dialect  # premise

    result = await ShellCommandAgent(pool="shell", command_policy_gate=gate)._run_command("git status")

    assert result == _ran("git status")  # behavioural control: an allowed command runs under either gate
    assert judge_spy.calls == [
        {"command": "git status", "site": "shell_command_agent", "search_path": env_spy.PATH, "cwd": None},
    ]
    (verdict,) = judge_spy.verdicts
    assert (verdict.call_site, verdict.decision) == ("shell_command_agent", "allow")
    assert verdict.evaluation is not None and verdict.evaluation.dialect == dialect  # it was read in that shell's dialect
    # control: the other call site reads another dialect on Windows, so the check above can tell the two apart there
    other = gate.judge("git status", site="run_command_tool", search_path=env_spy.PATH)
    assert other.evaluation is not None
    assert other.evaluation.dialect == ("cmd" if gate_platform == "win32" else "posix")


# --------------------------------------------------------------------------------------
# 5 and 6. Judged as it will run: after the rewrites
# --------------------------------------------------------------------------------------


async def test_judged_after_the_python_rewrite(
    monkeypatch: pytest.MonkeyPatch, runs: _Runs, env_spy: _EnvSpy, judge_spy: _JudgeSpy,
) -> None:
    """``python`` becomes the interpreter's path before the policy reads it; an unpinned ``allow`` does not match a path.

    Host-dependent mechanism (the rewrite and the shell the policy reads it in are this host's), same outcome on every
    host: the gate is built for this host's platform, and the result is an escalation whose cause is ``unmatched``.
    """
    if _READABLE_INTERPRETER_PATH.fullmatch(sys.executable) is None:
        # neighbouring input: this host's interpreter path is one S1's closed grammar refuses (the cause would be
        # ``unparseable``, same decision), so stand in a path it reads; the rewrite still embeds ``sys.executable``
        monkeypatch.setattr(sys, "executable", "C:\\Python312\\python.exe" if sys.platform == "win32" else "/usr/bin/python3")
    gate = _gate(_policy(_rule("py-ok", ["python"], "allow"), unmatched="escalate"))
    agent = ShellCommandAgent(pool="shell", command_policy_gate=gate)
    asked = 'python -c "print(1)"'
    # premise: the agent rewrites the bare name to the interpreter's path
    rewritten = ShellCommandAgent._rewrite_python_interpreter(asked)
    assert rewritten != asked and sys.executable in rewritten

    result = await agent._run_command(asked)

    assert runs.calls == []
    assert [call["command"] for call in judge_spy.calls] == [rewritten]  # the policy read the rewritten text
    (verdict,) = judge_spy.verdicts
    assert verdict.evaluation is not None
    assert verdict.decision == "escalate"
    assert [cause.kind for cause in verdict.causes] == ["unmatched"]
    assert verdict.evaluation.governing == ()  # O-S1-11: no rule decided it, and the refusal still says why
    assert result == {"success": False, "error": verdict.refusal_message}
    assert "no approval was requested" in result["error"]
    # control: the text as asked IS allowed by that rule, so the rewrite is what changed the outcome
    as_asked = gate.judge(asked, site="shell_command_agent", search_path=env_spy.PATH)
    assert (as_asked.decision, as_asked.runs) == ("allow", True)
    # control: a rule that matches the program runs the same agent's next command
    git_agent = ShellCommandAgent(
        pool="shell", command_policy_gate=_gate(_policy(_rule("git-ok", ["git"], "allow"), unmatched="escalate")),
    )
    assert await git_agent._run_command("git status") == _ran("git status")
    assert runs.commands == ["git status"]


async def test_judged_after_the_powershell_unwrap(
    monkeypatch: pytest.MonkeyPatch, runs: _Runs, env_spy: _EnvSpy, judge_spy: _JudgeSpy,
) -> None:
    """On Windows the agent strips a redundant ``powershell -Command`` wrapper first, and the policy reads what is left."""
    gate = _gate(_policy(_ALLOW_GIT_STATUS, unmatched="escalate"), platform="win32")
    agent = ShellCommandAgent(pool="shell", command_policy_gate=gate)
    wrapped = 'powershell -Sta -Command "git status"'
    # premise: the strip leaves the bare command, and S1 itself cannot read the wrapped text (-Sta is an option it does not
    # model, so it escalates), which is why the result below can only come from the strip
    assert ShellCommandAgent._strip_ps_wrapper(wrapped) == "git status"
    refused = gate.judge(wrapped, site="shell_command_agent", search_path=env_spy.PATH)
    assert (refused.decision, refused.runs) == ("escalate", False)
    assert [cause.kind for cause in refused.causes] == ["unparseable"]
    judge_spy.reset()

    # ``sys`` is shared, so this is process-wide for the block only; the policy's own dialect comes from the gate
    with monkeypatch.context() as patched:
        patched.setattr("probos.agents.shell_command.sys.platform", "win32")
        result = await agent._run_command(wrapped)

    assert result == _ran("git status")
    assert runs.commands == ["git status"]  # _run_sync got the stripped text
    assert [call["command"] for call in judge_spy.calls] == ["git status"]  # and so did the policy

    # control: with the strip taken away the same text reaches the policy as it is, and is escalated, not run
    runs.calls.clear()
    judge_spy.reset()
    with monkeypatch.context() as patched:
        patched.setattr("probos.agents.shell_command.sys.platform", "win32")
        patched.setattr(ShellCommandAgent, "_strip_ps_wrapper", staticmethod(lambda command: command))
        unstripped = await agent._run_command(wrapped)

    assert runs.calls == []
    assert [call["command"] for call in judge_spy.calls] == [wrapped]
    assert unstripped == {"success": False, "error": refused.refusal_message}


# --------------------------------------------------------------------------------------
# 7. A judgement that fails is a refusal
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("failure", ["judge_raises", "env_raises"])
async def test_judgement_error_is_a_refusal(
    monkeypatch: pytest.MonkeyPatch, runs: _Runs, env_spy: _EnvSpy, caplog: pytest.LogCaptureFixture, failure: str,
) -> None:
    """Fail closed: when the judgement cannot be made the command is not run, and the agent is told so."""
    agent = ShellCommandAgent(
        pool="shell", command_policy_gate=_gate(_policy(_rule("no-curl", ["curl"], "forbid"))),
    )
    # control first: with the judgement working, the same command runs
    assert await agent._run_command("git status") == _ran("git status")
    assert runs.commands == ["git status"]

    _break_the_judgement(monkeypatch, failure, "probos.agents.shell_command")
    with caplog.at_level(logging.WARNING, logger="probos.agents.shell_command"):
        result = await agent._run_command("git status")

    assert result == {"success": False, "error": COMMAND_POLICY_UNAVAILABLE_MESSAGE}
    assert runs.commands == ["git status"]  # still only the control's run: this one never started
    assert not _CAPABILITY_GAP_RE.search(COMMAND_POLICY_UNAVAILABLE_MESSAGE)
    assert any(
        record.levelno == logging.WARNING and "could not judge a run_command intent" in record.getMessage()
        for record in caplog.records
    )


# --------------------------------------------------------------------------------------
# 8, 9 and 10. The red team's re-run
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("claimed_success", [False, True], ids=["claimed_failure", "claimed_success"])
async def test_red_team_does_not_rerun_a_refused_command(
    reruns: _Reruns, env_spy: _EnvSpy, judge_spy: _JudgeSpy, claimed_success: bool,
) -> None:
    """The re-run is a third place a command executes: a refused one is answered from the verdict, never re-run. Kills R1."""
    agent = RedTeamAgent(pool="red_team", command_policy_gate=_gate(_policy(_FORBID_PUSH)))

    result = await _verify(agent, "git push", claimed_success=claimed_success)

    assert reruns.calls == []
    # premise, from the call itself: the policy was asked as the shell agent's call site, about the text it would re-run
    assert judge_spy.calls == [
        {"command": "git push", "site": "shell_command_agent", "search_path": env_spy.PATH, "cwd": None},
    ]
    assert judge_spy.verdicts[0].decision == "forbid"
    assert result.verifier_id == agent.id and result.target_agent_id == "shell-1"
    if claimed_success:  # the agent says it ran a command the policy forbids: the claim does not hold
        assert result.verified is False
        assert "command policy" in result.discrepancy and "forbid" in result.discrepancy
    else:  # the agent says it did not run it: consistent with the policy
        assert result.verified is True
        assert result.discrepancy == ""

    # control: an allowed command is re-run, exactly once, and the matching claim is verified
    control = await _verify(agent, "git status", claimed_success=True, claimed_stdout="ok")
    assert reruns.commands == ["git status"]
    assert control.verified is True


@pytest.mark.parametrize("gate_kind", ["no_gate", "unconfigured"])
async def test_red_team_without_policy_reruns_as_before(
    reruns: _Reruns, env_spy: _EnvSpy, judge_spy: _JudgeSpy, gate_kind: str,
) -> None:
    """No gate, or a gate with no rules: the re-run starts with ``(command, env, deadline, slot)`` as today, nothing else."""
    gate = None if gate_kind == "no_gate" else _gate(CommandPolicyConfig())
    if gate is not None:
        assert gate.configured is False  # premise
    agent = RedTeamAgent(pool="red_team", command_env_passthrough=(_PLAIN_NAME,), command_policy_gate=gate)

    result = await _verify(agent, "git status")

    assert result.verified is True
    (command, env, deadline, slot) = reruns.calls[0]
    assert command == "git status"
    assert env == {"PATH": env_spy.PATH}  # what build_command_env(declared) answered
    assert isinstance(deadline, float) and isinstance(slot, ProcessTreeSlot)
    assert len(reruns.calls) == 1
    assert env_spy.calls == [(_PLAIN_NAME,)]  # one call, the re-run's own: the policy built no second environment
    assert judge_spy.calls == []

    # control: a configured gate builds the environment for its judgement too, so the spies can see the difference
    governed = RedTeamAgent(
        pool="red_team", command_env_passthrough=(_PLAIN_NAME,),
        command_policy_gate=_gate(_policy(_rule("no-curl", ["curl"], "forbid"))),
    )
    env_calls_before = len(env_spy.calls)
    assert (await _verify(governed, "git status")).verified is True
    assert env_spy.calls[env_calls_before:] == [(_PLAIN_NAME,)] * 2  # the judgement's, then the re-run's
    assert len(judge_spy.calls) == 1
    assert reruns.commands == ["git status", "git status"]


@pytest.mark.parametrize("claimed_success", [False, True], ids=["claimed_failure", "claimed_success"])
@pytest.mark.parametrize("failure", ["judge_raises", "env_raises"])
async def test_red_team_judgement_error_does_not_rerun(
    monkeypatch: pytest.MonkeyPatch, reruns: _Reruns, env_spy: _EnvSpy, caplog: pytest.LogCaptureFixture,
    failure: str, claimed_success: bool,
) -> None:
    """A judgement that cannot be made is not a re-run, and not a verification either: the claim is left unverified."""
    agent = RedTeamAgent(pool="red_team", command_policy_gate=_gate(_policy(_FORBID_PUSH)))
    # control first: with the judgement working, the allowed command is re-run
    assert (await _verify(agent, "git status")).verified is True
    assert reruns.commands == ["git status"]

    _break_the_judgement(monkeypatch, failure, "probos.agents.red_team")
    with caplog.at_level(logging.WARNING, logger="probos.agents.red_team"):
        result = await _verify(agent, "git status", claimed_success=claimed_success)

    assert reruns.commands == ["git status"]  # still only the control's re-run
    assert result.verified is False
    assert "command policy" in result.discrepancy and "not re-run" in result.discrepancy
    assert any(
        record.levelno == logging.WARNING and "could not judge a run_command re-run" in record.getMessage()
        for record in caplog.records
    )


# --------------------------------------------------------------------------------------
# Addition (not a numbered M3 test): D5's one asymmetry between the two agents
# --------------------------------------------------------------------------------------


async def test_red_team_judges_the_text_it_reruns_unmodified(
    reruns: _Reruns, env_spy: _EnvSpy, judge_spy: _JudgeSpy,
) -> None:
    """D5: the re-run starts ``params["command"]`` as given, so that is the text the policy reads: no unwrap, no rewrite.

    The shell agent judges what is left after its own rewrites, so ``powershell -Sta -Command "git status"`` runs there
    (``test_judged_after_the_powershell_unwrap``) while the red team, which would re-run the wrapped text as given, judges
    that text and refuses it.
    """
    gate = _gate(_policy(_ALLOW_GIT_STATUS, unmatched="escalate"), platform="win32")
    agent = RedTeamAgent(pool="red_team", command_policy_gate=gate)
    wrapped = 'powershell -Sta -Command "git status"'
    # premise: the shell agent's unwrap would hand the policy `git status`, which this policy allows
    assert ShellCommandAgent._strip_ps_wrapper(wrapped) == "git status"

    result = await _verify(agent, wrapped, claimed_success=True)

    assert [call["command"] for call in judge_spy.calls] == [wrapped]  # judged as given
    assert (judge_spy.verdicts[0].decision, judge_spy.verdicts[0].runs) == ("escalate", False)
    assert reruns.calls == []
    assert result.verified is False and "escalate" in result.discrepancy
    # control: the unwrapped text, which the policy allows as given, is re-run
    assert (await _verify(agent, "git status")).verified is True
    assert reruns.commands == ["git status"]


# --------------------------------------------------------------------------------------
# Repair r1 (review F1, F3): the object judged is the object run; a bare pinned name is not proven under PowerShell
# --------------------------------------------------------------------------------------


class _TextWithAnotherStr(str):
    """A ``str`` subclass whose value is ``curl x`` and whose ``__str__`` answers ``echo ok``: a conversion hides the value."""

    def __str__(self) -> str:
        return "echo ok"


async def test_r1_red_team_judges_the_object_it_reruns(reruns: _Reruns, env_spy: _EnvSpy) -> None:
    """B17. The re-run starts the object it was given, so that object is what the policy reads: a ``str`` subclass is not
    judged by its ``str()`` conversion (``echo ok``, which the policy allows) and re-run as ``curl x``. Kills R2."""
    agent = RedTeamAgent(pool="red_team", command_policy_gate=_gate(_policy(_rule("no-curl", ["curl"], "forbid"))))
    command = _TextWithAnotherStr("curl x")
    # premise: the two readings of the object differ, and the policy allows one and forbids the other
    assert str.__str__(command) == "curl x" and str(command) == "echo ok"
    assert _gate(_policy(_rule("no-curl", ["curl"], "forbid"))).judge(
        "curl x", site="shell_command_agent", search_path=None,
    ).decision == "forbid"

    result = await _verify(agent, command, claimed_success=True)  # type: ignore[arg-type]

    assert reruns.calls == []
    assert result.verified is False
    assert "command policy" in result.discrepancy

    # control: a plain str is judged and re-run, once, as the very object given
    plain = "".join(["echo ", "ok"])
    control = await _verify(agent, plain, claimed_success=True)
    assert control.verified is True
    assert len(reruns.calls) == 1
    assert reruns.calls[0][0] is plain


async def test_r1_shell_agent_refuses_a_command_that_is_not_text(runs: _Runs, env_spy: _EnvSpy) -> None:
    """B18. A ``str`` subclass is not text the policy reads: the shell agent refuses it and ``_run_sync`` is not called."""
    agent = ShellCommandAgent(
        pool="shell", command_policy_gate=_gate(_policy(_rule("no-curl", ["curl"], "forbid"))),
    )

    result = await agent._run_command(_TextWithAnotherStr("curl x"))

    assert result == {"success": False, "error": COMMAND_POLICY_UNAVAILABLE_MESSAGE}
    assert runs.calls == []

    # control: a plain str runs, as the identical object
    plain = "".join(["echo ", "ok"])
    assert await agent._run_command(plain) == _ran(plain)
    assert len(runs.calls) == 1
    assert runs.calls[0][0] is plain


async def test_r1_agents_refuse_a_pinned_bare_name_under_powershell(
    runs: _Runs, reruns: _Reruns, env_spy: _EnvSpy,
) -> None:
    """B19. Under PowerShell no lookup names the file a bare name runs, so a rule pinned to a path does not allow the bare
    name, whatever ``which`` and ``is_file`` would answer: both agents refuse it and name the pinned path. Kills G12."""
    pin = "C:\\d1\\tool.CMD"
    posix_pin = "/d1/tool.CMD"  # what a posix lookup would answer; S1 r3 counts a pin only where it is absolute, never this one under cmd or PowerShell
    config = _policy(_rule("pinned-tool", ["tool"], "allow", host_executable=[pin, posix_pin]), unmatched="escalate")

    def which(name: str, path: str | None = None) -> str:
        return posix_pin

    gate = CommandPolicyGate(config, platform="win32", which=which, is_file=lambda path: path == pin)
    shell = ShellCommandAgent(pool="shell", command_policy_gate=gate)
    red_team = RedTeamAgent(pool="red_team", command_policy_gate=gate)

    refused = await shell._run_command("tool")

    assert refused["success"] is False
    assert pin in refused["error"]
    assert "a program that does not resolve" in refused["error"]  # PowerShell's lookup answered nothing (a posix lookup would give '/d1/tool.CMD', refused as not absolute)
    assert runs.calls == []
    verified = await _verify(red_team, "tool", claimed_success=True)
    assert verified.verified is False and "command policy" in verified.discrepancy
    assert reruns.calls == []

    # control: the pinned path written out is the program the policy allows, at both agents
    assert (await shell._run_command(pin)) == _ran(pin)
    assert (await _verify(red_team, pin, claimed_success=True)).verified is True
    assert runs.commands == [pin]
    assert reruns.commands == [pin]


async def test_r2_agents_refuse_a_pinned_posix_builtin_bare(runs: _Runs, reruns: _Reruns, env_spy: _EnvSpy) -> None:
    """B32. Under posix a built-in runs in place of the PATH file, so a rule pinned to ``/bin/echo`` does not allow the bare
    ``echo``, whatever ``which`` answers: both agents refuse it and name the pin; the written path runs. Kills G49."""
    pin = "/bin/echo"
    config = _policy(_rule("echo", ["echo"], "allow", host_executable=[pin]), unmatched="escalate")

    def which(name: str, path: str | None = None) -> str:
        return pin

    gate = CommandPolicyGate(config, platform="linux", which=which, is_file=lambda path: False)
    shell = ShellCommandAgent(pool="shell", command_policy_gate=gate)
    red_team = RedTeamAgent(pool="red_team", command_policy_gate=gate)

    refused = await shell._run_command("echo hi")

    assert refused["success"] is False
    assert pin in refused["error"]
    assert runs.calls == []
    verified = await _verify(red_team, "echo hi", claimed_success=True)
    assert verified.verified is False
    assert reruns.calls == []

    # control: the pinned path written out runs at both agents
    written = f"{pin} hi"
    assert (await shell._run_command(written)) == _ran(written)
    assert (await _verify(red_team, written, claimed_success=True)).verified is True
    assert runs.commands == [written]
    assert reruns.commands == [written]
