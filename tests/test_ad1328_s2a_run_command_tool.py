"""AD-1328 S2a (#1530), M2: the command policy on the ``run_command`` tool path, in front of the AD-1316 broker, and in the
AD-1224 tool record.

Tests only. The contract is ``prompts/ad-1328-s2a-command-policy-wiring.md`` ("Tests", M2). Nothing here starts a shell:
``asyncio.create_subprocess_shell`` and the tool module's ``ProcessTree`` are replaced by recorders, and every gate is built
with an explicit ``platform=`` and an injected recording ``which``, so the file reads the same on any host. The few
host-dependent values (``process_tree_popen_kwargs()``, ``os.pathsep``, ``os.getcwd()``) are computed in the test with the same
function the tool uses, and the child's ``PATH`` is pinned to a sentinel with ``monkeypatch`` where it matters.

Each test asserts its premise (what the tokenizer made of the text, which dialect the gate serves) and a control: the accepted
neighbour of every refusal and the refused neighbour of every run is checked, so a test cannot pass because the whole machine
refuses (or runs) everything. The helpers are copies, because tests do not import each other: S1's ``_policy`` / ``_rule``, and
AD-1315 / AD-1316's ``strict_runtime`` chain with ``_register`` and ``_invoke`` (``_invoke`` gains a ``params`` argument).

Two tests cross a whole seam: #11 follows tool -> shell adapter -> broker -> effect record, and #12 follows tool -> executor
hook -> AD-1224 record. The closed grammar of S1 reads every command used here in the dialect it is written for.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive import decomposer
from probos.cognitive.swe_harness import tools as swe_tools
from probos.cognitive.swe_harness.tools import RunCommandTool
from probos.config_models.operations import CommandPolicyConfig
from probos.events import EventType
from probos.execution.authority import (
    REQUIRED_ENFORCEMENT_KINDS,
    AdmissionRequest,
    EnforcementSourceSnapshot,
    ManifestPublicationRequest,
    ProtectedExecutionAuthority,
)
from probos.execution.command_env import build_command_env
from probos.execution.command_gate import CommandPolicyGate, compact_command_policy_record
from probos.execution.command_policy import CommandPolicy, parse_command
from probos.execution.effect_adapters import _EffectAdapterRegistry
from probos.execution.effect_broker import GovernedEffectBroker
from probos.execution.process_tree import process_tree_popen_kwargs
from probos.substrate.event_log import EventLog
from probos.tools import executor as executor_module
from probos.tools.executor import DEFAULT_MAX_RECORDS_PER_RUN, ToolExecutor, make_audit_hook, make_start_hook
from probos.tools.protocol import ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry

# --------------------------------------------------------------------------------------
# Helpers (copied; tests do not import each other)
# --------------------------------------------------------------------------------------


def _policy(*rules: dict, unmatched: str = "allow", **extra: object) -> CommandPolicyConfig:
    """S1's helper (tests/test_ad1328_s1_policy_evaluation.py)."""
    return CommandPolicyConfig.model_validate({"rules": list(rules), "unmatched_decision": unmatched, **extra})


def _rule(name: str, pattern: list, decision: str, **extra: object) -> dict:
    """S1's helper (tests/test_ad1328_s1_policy_evaluation.py)."""
    base = {"name": name, "pattern": pattern, "decision": decision, "justification": f"{name} because"}
    if decision == "forbid":
        base["alternative"] = "use the governed path"
    return {**base, **extra}


_NO_CURL_WHY = "curl reaches the network outside the governed fetch path"
_NO_CURL_INSTEAD = "use the fetch_url tool"
_ASK_PUSH_WHY = "a push publishes work outside this session"
_CHILD_PATH = "S2A-SENTINEL-PATH"
_PRISTINE_REASON = "shell_isolation_unproven"  # the AD-1316 shell adapter's reason before any policy existed


def _stack(unmatched: str = "allow") -> CommandPolicyConfig:
    """``echo`` and ``git`` allowed, ``curl`` forbidden, ``git push`` escalated; the strictest matching rule wins."""
    return _policy(
        _rule("allow-echo", ["echo"], "allow"),
        _rule("allow-git", ["git"], "allow"),
        _rule("no-curl", ["curl"], "forbid", justification=_NO_CURL_WHY, alternative=_NO_CURL_INSTEAD),
        _rule("ask-push", ["git", "push"], "escalate", justification=_ASK_PUSH_WHY),
        unmatched=unmatched,
    )


class _Which:
    """A recording ``which``: the program lookup a gate is built with. It never reads the real PATH."""

    def __init__(self, answers: dict[str, str | None] | None = None) -> None:
        self.answers: dict[str, str | None] = dict(answers or {})
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, name: str, path: str | None = None) -> str | None:
        self.calls.append((name, path))
        return self.answers.get(name)


class _IsFile:
    """A recording ``is_file``: the cmd lookup's file probe. It answers from ``present`` and never reads this host's files."""

    def __init__(self, present: set[str] | None = None) -> None:
        self.present: set[str] = set(present or ())
        self.calls: list[str] = []

    def __call__(self, path: str) -> bool:
        self.calls.append(path)
        return path in self.present


def _gate(
    config: CommandPolicyConfig, *, platform: str = "linux", which: _Which | None = None,
    is_file: _IsFile | None = None,
) -> CommandPolicyGate:
    return CommandPolicyGate(
        config, platform=platform, which=which if which is not None else _Which(),
        is_file=is_file if is_file is not None else _IsFile(),
    )


def _tool(gate: CommandPolicyGate | None = None) -> RunCommandTool:
    return RunCommandTool(SimpleNamespace(), command_policy_gate=gate)  # type: ignore[arg-type]


def _words(command: str, dialect: str, config: CommandPolicyConfig) -> list[list[str]]:
    """The simple commands S1's closed grammar reads ``command`` as under ``dialect``: the premise of a test that names one."""
    parsed = parse_command(command, dialect=dialect, limits=config)  # type: ignore[arg-type]
    assert parsed.unparseable is None, parsed.unparseable
    assert all(segment.unparseable is None for segment in parsed.segments), command
    return [list(segment.tokens) for segment in parsed.segments]


def _not_a_capability_gap(text: str) -> None:
    """The refusal frames are error-shaped, not a capability gap (AD-1154 DD-2): the real decomposer regex must not fire."""
    assert decomposer._CAPABILITY_GAP_RE.search(text) is None, text


def _boom(*args: object, **kwargs: object) -> object:
    raise RuntimeError("judge exploded")


class _EnvSpy:
    """Wraps the tool module's ``build_command_env`` and counts its calls; the answer is the real one."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, declared: Any = (), **kwargs: Any) -> dict[str, str]:
        self.calls.append(tuple(declared))
        return build_command_env(declared, **kwargs)


# --------------------------------------------------------------------------------------
# The spawn recorder (no real shell)
# --------------------------------------------------------------------------------------


class _Process:
    """What ``create_subprocess_shell`` returns: ``communicate()`` gives ``(b"out", b"")`` and the exit code is 0."""

    pid = 4242
    returncode = 0

    def __init__(self, hang: bool) -> None:
        self._hang = hang

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.Event().wait()  # never finishes: only the tool's own timeout ends it
        return b"out", b""

    def kill(self) -> None:
        raise AssertionError("the tool ends the tree through ProcessTree, never the process directly")


class _Tree:
    """What the fake ``ProcessTree.attach`` returns."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    def kill(self) -> None:
        self._events.append("kill")

    def close(self) -> None:
        self._events.append("close")


class _Spawns:
    """Records every spawn ``(args, kwargs)``, every tree attached, and what was done to each tree."""

    def __init__(self) -> None:
        self.hang = False
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.attached: list[_Process] = []
        self.tree_events: list[str] = []

    async def create_subprocess_shell(self, *args: Any, **kwargs: Any) -> _Process:
        self.calls.append((args, kwargs))
        return _Process(self.hang)

    def attach(self, proc: _Process) -> _Tree:
        self.attached.append(proc)
        return _Tree(self.tree_events)

    def reset(self) -> None:
        self.calls.clear()
        self.attached.clear()
        self.tree_events.clear()


@pytest.fixture
def spawns(monkeypatch: pytest.MonkeyPatch) -> _Spawns:
    recorder = _Spawns()
    monkeypatch.setattr(asyncio, "create_subprocess_shell", recorder.create_subprocess_shell)
    monkeypatch.setattr(swe_tools, "ProcessTree", SimpleNamespace(attach=recorder.attach))
    return recorder


@pytest.fixture
def child_path(monkeypatch: pytest.MonkeyPatch) -> str:
    """The child's PATH comes from ``build_command_env``, i.e. from this process's: pin it so a test can name it."""
    monkeypatch.setenv("PATH", _CHILD_PATH)
    return _CHILD_PATH


def _spawn_of(command: str, *, cwd: str | None = None) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """The one spawn the tool makes for ``command``: the args and the exact keyword arguments (BF-890, BF-893)."""
    return (
        (command,),
        {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "cwd": cwd,
            "env": build_command_env(()),
            **process_tree_popen_kwargs(),
        },
    )


def _ran() -> ToolResult:
    """What a command that ran returns when the recorder's process answered ``(b"out", b"")`` with exit code 0."""
    return ToolResult(output={"stdout": "out", "stderr": "", "exit_code": 0})


# --------------------------------------------------------------------------------------
# 1. No policy: byte for byte what the tool did before S2a
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["no_gate", "unconfigured_gate"])
async def test_no_policy_is_byte_identical(
    variant: str, spawns: _Spawns, child_path: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("S2A_PROBE_SECRET", "planted")
    expected_env = build_command_env(())
    # premise: the process holds a planted secret that the child's allowlisted environment leaves out, and the child's PATH is ours
    assert os.environ["S2A_PROBE_SECRET"] == "planted"
    assert "S2A_PROBE_SECRET" not in expected_env
    assert expected_env["PATH"] == child_path
    env_spy = _EnvSpy()
    monkeypatch.setattr(swe_tools, "build_command_env", env_spy)
    which = _Which()
    gate = None if variant == "no_gate" else _gate(CommandPolicyConfig(), which=which)
    if gate is not None:
        assert gate.configured is False  # premise: no rules, so no policy
        assert gate.digest is None
    tool = _tool(gate)

    result = await tool.invoke({"command": "echo hi"})

    assert spawns.calls == [_spawn_of("echo hi")]  # one spawn: the command text and every keyword argument, exactly
    assert result == _ran()
    assert result.metadata == {}
    assert len(spawns.attached) == 1  # the BF-893 tree is attached to the spawned process and released
    assert spawns.tree_events == ["close"]
    assert env_spy.calls == [()]  # exactly one child environment was built: the spawn's (kills T3)
    assert which.calls == []


@pytest.mark.asyncio
async def test_no_policy_variants_are_equal_and_a_policy_is_not_no_policy(
    spawns: _Spawns, child_path: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_spy = _EnvSpy()
    monkeypatch.setattr(swe_tools, "build_command_env", env_spy)

    async def observe(gate: CommandPolicyGate | None) -> tuple[Any, ...]:
        spawns.reset()
        env_spy.calls.clear()
        result = await _tool(gate).invoke({"command": "echo hi"})
        return list(spawns.calls), result, list(spawns.tree_events), len(env_spy.calls)

    none = await observe(None)
    unconfigured = await observe(_gate(CommandPolicyConfig()))
    allowing = await observe(_gate(_stack()))
    forbidding = await observe(_gate(_policy(_rule("no-echo", ["echo"], "forbid"))))

    assert none == unconfigured  # the two ways of having no policy are indistinguishable
    assert none == ([_spawn_of("echo hi")], _ran(), ["close"], 1)
    # control: a configured policy is observable, so the equality above is not a machine that always answers the same
    assert allowing[0] == none[0] and allowing[2] == none[2]  # the allowed command spawns exactly as before ...
    assert allowing[1].output == none[1].output and allowing[1].metadata != {}  # ... but its result carries the decision
    assert allowing[3] == 2  # and the child's environment was built twice: once to judge, once to launch
    assert forbidding[0] == [] and forbidding[1].error is not None  # a forbidding policy spawns nothing


# --------------------------------------------------------------------------------------
# 2-6. The verdict decides whether the command is spawned
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "dialect"),
    [pytest.param("linux", "posix", id="posix_gate"), pytest.param("win32", "cmd", id="cmd_gate")],
)
async def test_allow_runs_once_and_records(platform: str, dialect: str, spawns: _Spawns, child_path: str) -> None:
    config = _stack(unmatched="escalate")
    gate = _gate(config, platform=platform)
    assert gate.dialect_for("run_command_tool") == dialect  # premise: the tool's call site is served in this dialect
    assert _words("echo hi", dialect, config) == [["echo", "hi"]]
    tool = _tool(gate)

    result = await tool.invoke({"command": "echo hi"})

    assert spawns.calls == [_spawn_of("echo hi")]  # one spawn, the keyword arguments unchanged by the policy (kills G2)
    assert result.error is None
    assert result.output == _ran().output
    assert set(result.metadata) == {"command_policy"}
    record = result.metadata["command_policy"]
    assert record["decision"] == "allow"
    assert record["dialect"] == dialect
    assert record["call_site"] == "run_command_tool"
    assert record["matched_rules"] == ["allow-echo"]
    assert record["policy_digest"] == gate.digest
    # the key is the one the gate's own dialect computes for this command (``echo`` is a cmd builtin, so cmd and posix differ)
    assert record["canonical_key"] == CommandPolicy(config, dialect=dialect).canonical(  # type: ignore[arg-type]
        "echo hi", resolve_program=lambda name: None,
    ).key
    # control: a command no rule covers is refused under the same gate, so the allow above came from the rule
    refused = await tool.invoke({"command": "ls"})
    assert refused.error is not None
    assert len(spawns.calls) == 1


@pytest.mark.asyncio
async def test_forbid_is_not_spawned_and_tells_the_alternative(spawns: _Spawns, child_path: str) -> None:
    config = _stack()
    gate = _gate(config)
    tool = _tool(gate)
    command = "curl -sS example.com"
    assert _words(command, "posix", config) == [["curl", "-sS", "example.com"]]  # premise: one curl segment, which a rule forbids

    refused = await tool.invoke({"command": command})

    assert spawns.calls == []  # not spawned (kills T1) ...
    assert spawns.attached == []  # ... and no process tree was ever attached
    assert refused.output is None
    assert refused.error is not None
    assert "Rule 'no-curl'" in refused.error
    assert _NO_CURL_WHY in refused.error
    assert _NO_CURL_INSTEAD in refused.error
    expected = gate.judge(command, site="run_command_tool", search_path=child_path)
    assert expected.decision == "forbid"
    assert refused.error == expected.refusal_message  # the agent is told exactly what the gate says
    _not_a_capability_gap(refused.error)
    assert set(refused.metadata) == {"command_policy"}
    record = refused.metadata["command_policy"]
    assert record["decision"] == "forbid"
    assert record["call_site"] == "run_command_tool"
    assert record["matched_rules"] == ["no-curl"]
    assert record["causes"] == [{"kind": "rule", "segment": 0, "rule": "no-curl"}]
    # control: the accepted neighbour runs under the same gate, once
    ran = await tool.invoke({"command": "echo hi"})
    assert ran.error is None
    assert ran.metadata["command_policy"]["decision"] == "allow"
    assert spawns.calls == [_spawn_of("echo hi")]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["rule", "unmatched"])
async def test_escalate_is_not_spawned_and_names_its_cause(case: str, spawns: _Spawns, child_path: str) -> None:
    if case == "rule":
        config = _stack(unmatched="allow")
        command = "git push origin"
        expected_causes = [{"kind": "rule", "segment": 0, "rule": "ask-push"}]
        expected_rules = ["allow-git", "ask-push"]
    else:
        config = _policy(_rule("allow-git", ["git"], "allow"), unmatched="escalate")
        command = "ls"
        expected_causes = [{"kind": "unmatched", "segment": 0, "rule": None}]
        expected_rules = []
    assert _words(command, "posix", config) == [command.split()]  # premise: one plain simple command
    tool = _tool(_gate(config))

    refused = await tool.invoke({"command": command})

    assert spawns.calls == []
    assert spawns.attached == []
    assert refused.output is None
    assert refused.error is not None
    assert "no approval was requested" in refused.error  # S2a refuses an escalate truthfully, without asking anyone
    _not_a_capability_gap(refused.error)
    if case == "rule":
        assert "Rule 'ask-push'" in refused.error
        assert _ASK_PUSH_WHY in refused.error
    else:
        assert "'ls'" in refused.error  # names the program no rule covers (O-S1-11) ...
        assert "Rule '" not in refused.error  # ... and no rule, because none decided it
    record = refused.metadata["command_policy"]
    assert record["decision"] == "escalate"
    assert record["matched_rules"] == expected_rules
    assert record["causes"] == expected_causes
    # control: an accepted command runs under the same gate
    ran = await tool.invoke({"command": "git status"})
    assert ran.error is None
    assert ran.metadata["command_policy"]["decision"] == "allow"
    assert spawns.calls == [_spawn_of("git status")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "dialect", "compound", "clean"),
    [
        pytest.param("linux", "posix", "git status && curl x", "git status && git log", id="posix"),
        pytest.param("win32", "cmd", "git status & curl x", "git status & git log", id="cmd"),
    ],
)
async def test_compound_with_one_forbidden_segment_is_forbidden(
    platform: str, dialect: str, compound: str, clean: str, spawns: _Spawns, child_path: str,
) -> None:
    config = _stack()
    gate = _gate(config, platform=platform)
    assert gate.dialect_for("run_command_tool") == dialect
    # premise: the grammar reads the compound as two simple commands, each decided on its own
    assert _words(compound, dialect, config) == [["git", "status"], ["curl", "x"]]
    assert _words(clean, dialect, config) == [["git", "status"], ["git", "log"]]
    assert gate.judge("git status", site="run_command_tool", search_path=child_path).decision == "allow"
    assert gate.judge("curl x", site="run_command_tool", search_path=child_path).decision == "forbid"
    tool = _tool(gate)

    refused = await tool.invoke({"command": compound})

    assert spawns.calls == []  # the allowed segment does not carry the forbidden one past the policy
    assert refused.error is not None
    assert "Rule 'no-curl'" in refused.error
    assert "Rule 'allow-git'" not in refused.error  # only the segment that decided is a cause
    record = refused.metadata["command_policy"]
    assert record["decision"] == "forbid"
    assert record["dialect"] == dialect
    assert record["matched_rules"] == ["allow-git", "no-curl"]
    assert record["causes"] == [{"kind": "rule", "segment": 1, "rule": "no-curl"}]
    # control: the same shape with an allowed second segment runs, as one command line
    ran = await tool.invoke({"command": clean})
    assert ran.error is None
    assert ran.metadata["command_policy"]["decision"] == "allow"
    assert spawns.calls == [_spawn_of(clean)]


@pytest.mark.asyncio
async def test_judgement_error_does_not_spawn(spawns: _Spawns, child_path: str) -> None:
    gate = _gate(_stack())
    tool = _tool(gate)
    assert gate.configured is True  # premise: with a policy the tool does judge (an unconfigured gate never reaches judge)

    with pytest.MonkeyPatch.context() as broken:
        broken.setattr(gate, "judge", _boom)
        result = await tool.invoke({"command": "echo hi"})

    assert spawns.calls == []
    assert spawns.attached == []
    assert result.error is not None
    assert result.error.startswith("run_command failed:")
    assert result.error == "run_command failed: judge exploded"
    assert result.output is None
    assert result.metadata == {}  # no verdict, so no decision is recorded
    # control: the same tool and command with the judgement working spawns once
    ran = await tool.invoke({"command": "echo hi"})
    assert ran.error is None
    assert spawns.calls == [_spawn_of("echo hi")]


# --------------------------------------------------------------------------------------
# 7. The lookup is the child's: its PATH, and for cmd its working directory first
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "pin", "evil", "working_directory"),
    [
        # AD-1328 S2a repair r1: the cmd rows moved to the next test (D-s2a-1: cmd no longer calls ``which``; its lookup is
        # ``is_file`` over the working directory then the child's PATH, with the child's PATHEXT). The row without a working
        # directory is host-named (its first probe is this process's directory) and B3 in the gate file covers it.
        pytest.param("linux", "/usr/bin/git", "/tmp/evil/git", "/work", id="posix_with_working_directory"),
    ],
)
async def test_resolver_uses_the_child_path_and_working_directory(
    platform: str, pin: str, evil: str, working_directory: str | None, spawns: _Spawns, child_path: str,
) -> None:
    assert build_command_env(())["PATH"] == child_path  # premise: the child's PATH is the sentinel, not the host's
    config = _policy(_rule("pinned-git", ["git"], "allow", host_executable=[pin]), unmatched="escalate")
    which = _Which({"git": pin})
    gate = _gate(config, platform=platform, which=which)
    tool = _tool(gate)
    expected_path = child_path  # a posix shell searches PATH only
    params: dict[str, Any] = {"command": "git status"}
    if working_directory is not None:
        params["working_directory"] = working_directory

    result = await tool.invoke(params)

    assert result.error is None, result.error  # the pinned rule allowed the program the child's lookup found
    assert result.metadata["command_policy"]["decision"] == "allow"
    assert which.calls  # the pinned rule made the gate look the program up
    assert {name for name, _ in which.calls} == {"git"}
    assert {path for _, path in which.calls} == {expected_path}  # and only on the child's path (kills G3 for cmd)
    assert spawns.calls == [_spawn_of("git status", cwd=working_directory)]
    # control: the answer the lookup gives is what is judged. Another path for the same program is refused, not spawned
    which.answers["git"] = evil
    which.calls.clear()
    refused = await tool.invoke(params)
    assert refused.error is not None
    assert "evil" in refused.error  # the path the lookup found is named (S1 formats it; the gate's own tests pin how) ...
    assert pin in refused.error  # ... beside the pinned path the rule allows, as written
    assert refused.metadata["command_policy"]["decision"] == "forbid"
    assert {path for _, path in which.calls} == {expected_path}
    assert len(spawns.calls) == 1


@pytest.mark.asyncio
async def test_resolver_cmd_searches_the_working_directory_then_the_child_path_with_its_pathext(
    spawns: _Spawns, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-s2a-1: cmd's lookup is ``is_file`` over ``<cwd>`` then the child's PATH, with the child's PATHEXT (kills G3, T7)."""
    monkeypatch.setenv("PATH", "C:\\tools")
    monkeypatch.setenv("PATHEXT", ".COM;.EXE")
    pin = "C:\\tools\\git.EXE"
    work = "C:\\work"
    passthrough = ("PATHEXT",)
    child_env = build_command_env(passthrough)
    # premise: the child carries this PATH and, through the declared passthrough, this PATHEXT on every host
    assert child_env["PATH"] == "C:\\tools"
    assert child_env["PATHEXT"] == ".COM;.EXE"
    config = _policy(_rule("pinned-git", ["git"], "allow", host_executable=[pin]), unmatched="escalate")
    which = _Which({"git": "C:\\elsewhere\\git.exe"})  # must never be asked: cmd does not use ``which``
    is_file = _IsFile({pin})
    gate = _gate(config, platform="win32", which=which, is_file=is_file)
    tool = RunCommandTool(SimpleNamespace(), command_env_passthrough=passthrough, command_policy_gate=gate)  # type: ignore[arg-type]
    params = {"command": "git status", "working_directory": work}

    result = await tool.invoke(params)

    assert result.error is None, result.error  # the pinned rule allowed the file the child's lookup found
    assert result.metadata["command_policy"]["decision"] == "allow"
    assert is_file.calls == ["C:\\work\\git.COM", "C:\\work\\git.EXE", "C:\\tools\\git.COM", "C:\\tools\\git.EXE"]
    assert which.calls == []
    args, kwargs = _spawn_of("git status", cwd=work)
    assert spawns.calls == [(args, {**kwargs, "env": child_env})]  # the spawn carries the passthrough too
    # control: a file in the working directory is found first; it is not the pinned one, so it is refused and not spawned
    is_file.present.add("C:\\work\\git.EXE")
    is_file.calls.clear()
    refused = await tool.invoke(params)
    assert refused.error is not None
    assert repr("C:\\work\\git.EXE") in refused.error  # named as the policy words a path: quoted, backslashes escaped
    assert refused.metadata["command_policy"]["decision"] == "forbid"
    assert is_file.calls == ["C:\\work\\git.COM", "C:\\work\\git.EXE"]
    assert which.calls == []
    assert len(spawns.calls) == 1


# --------------------------------------------------------------------------------------
# 8. A timeout still records the decision
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_still_records_the_decision(spawns: _Spawns, child_path: str) -> None:
    spawns.hang = True  # premise: communicate() never finishes, so only the tool's timeout can end the call
    gate = _gate(_stack())

    result = await _tool(gate).invoke({"command": "echo hi", "timeout": 0.01})

    assert result.error == "run_command timed out after 0.01s"
    assert result.output is None
    assert spawns.calls == [_spawn_of("echo hi")]  # the command was allowed and started before it timed out
    assert spawns.tree_events == ["kill", "close"]  # BF-893: the tree is ended, then released
    assert set(result.metadata) == {"command_policy"}
    assert result.metadata["command_policy"]["decision"] == "allow"
    assert result.metadata["command_policy"]["policy_digest"] == gate.digest
    # control: with no policy the same timeout says the same and records nothing
    spawns.reset()
    unguarded = await _tool(None).invoke({"command": "echo hi", "timeout": 0.01})
    assert unguarded.error == "run_command timed out after 0.01s"
    assert unguarded.metadata == {}


# --------------------------------------------------------------------------------------
# 9-10. The preflight and the AD-1316 shell adapter
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("no_gate", ""),
        ("unconfigured", ""),
        ("allow", ""),
        ("forbid", "command_policy_forbid"),
        ("escalate", "command_policy_escalate"),
        ("raises", "command_policy_unavailable"),
        ("blank_command", ""),
        ("missing_command", ""),
        ("non_string_command", ""),
        ("params_not_a_dict", ""),
    ],
)
def test_preflight_reason_codes(case: str, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    forbidden = {"command": "curl -sS example.com"}
    live = _gate(_stack())
    # control: the live policy does refuse curl, so a "" below comes from the case and not from a lenient policy
    assert _tool(live).command_policy_preflight(forbidden) == "command_policy_forbid"
    params: Any = forbidden  # the default: a command a live policy would forbid
    if case == "no_gate":
        tool = _tool(None)
    elif case == "unconfigured":
        tool = _tool(_gate(CommandPolicyConfig()))
    elif case == "allow":
        tool, params = _tool(live), {"command": "echo hi"}
    elif case == "forbid":
        tool = _tool(live)
    elif case == "escalate":
        tool, params = _tool(live), {"command": "git push origin"}
    elif case == "raises":
        broken = _gate(_stack())
        monkeypatch.setattr(broken, "judge", _boom)
        tool, params = _tool(broken), {"command": "echo hi"}
    elif case == "blank_command":
        tool, params = _tool(live), {"command": "   "}
    elif case == "missing_command":
        tool, params = _tool(live), {}
    elif case == "non_string_command":
        tool, params = _tool(live), {"command": 5}
    else:
        tool, params = _tool(live), None

    assert tool.command_policy_preflight(params) == expected


@pytest.mark.parametrize(
    "case",
    [
        "forbid",
        "escalate",
        "allow",
        "unconfigured",
        "no_policy",
        "no_preflight",
        "preflight_raises",
        "preflight_not_a_string",
    ],
)
def test_shell_adapter_uses_the_policy_reason(case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    reasons = {
        "forbid": "command_policy_forbid",
        "escalate": "command_policy_escalate",
        "allow": _PRISTINE_REASON,
        "unconfigured": _PRISTINE_REASON,
        "no_policy": _PRISTINE_REASON,
        "no_preflight": _PRISTINE_REASON,
        "preflight_raises": "command_policy_unavailable",
        "preflight_not_a_string": "command_policy_unavailable",
    }
    live = _gate(_stack())
    params: dict[str, Any] = {"command": "curl -sS example.com"}  # forbidden by the live policy
    if case == "forbid":
        tool = _tool(live)
    elif case == "escalate":
        tool, params = _tool(live), {"command": "git push origin"}
    elif case == "allow":
        tool, params = _tool(live), {"command": "echo hi"}
    elif case == "unconfigured":
        tool = _tool(_gate(CommandPolicyConfig()))
    elif case == "no_policy":
        tool = _tool(None)
    elif case == "no_preflight":
        tool = _tool(live)
        monkeypatch.setattr(tool, "command_policy_preflight", None)
    elif case == "preflight_raises":
        tool = _tool(live)
        monkeypatch.setattr(tool, "command_policy_preflight", _boom)
    else:
        tool = _tool(live)
        monkeypatch.setattr(tool, "command_policy_preflight", lambda params: 7)
    registry = _EffectAdapterRegistry()

    adapter = registry.for_tool(tool, "run_command")
    prepared = adapter.prepare(tool_id="run_command", params=params, context={})

    assert type(adapter).__name__ == "_ShellEffectAdapter"  # premise: the real tool is routed to the shell adapter
    assert prepared.effect_class == "shell"
    assert prepared.denial_reason == reasons[case]  # kills A1
    # control: the policy only adds gates. The pristine adapter refuses an unproven shell, and nothing else about the effect moves
    pristine = registry.for_tool(_tool(None), "run_command").prepare(tool_id="run_command", params=params, context={})
    assert pristine.denial_reason == _PRISTINE_REASON
    assert dataclasses.replace(prepared, denial_reason="") == dataclasses.replace(pristine, denial_reason="")


# --------------------------------------------------------------------------------------
# 11. Tool -> shell adapter -> broker -> effect record (copied from tests/test_ad1315 and test_ad1316)
# --------------------------------------------------------------------------------------


def _digest(domain: str, content: bytes) -> str:
    value = hashlib.sha256()
    value.update(domain.encode("ascii"))
    value.update(b"\x00")
    value.update(content)
    return value.hexdigest()


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_repository(root: Path, source_text: str = "agent source") -> Path:
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "authority@example.invalid")
    _git(root, "config", "user.name", "Authority Test")
    source = root / "agent.py"
    source.write_text(source_text, encoding="utf-8")
    _git(root, "add", "agent.py")
    _git(root, "commit", "-q", "-m", "seed")
    return source


def _make_layout(
    tmp_path: Path,
    *,
    policy: dict[str, object] | None = None,
    source_text: str = "agent source",
) -> dict[str, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    repository = tmp_path / "repository"
    selected_source = _make_repository(repository, source_text)
    protected = tmp_path / "protected"
    protected.mkdir()
    issuer = protected / "authority.py"
    issuer.write_text("issuer", encoding="utf-8")
    policy_path = protected / "policy.json"
    policy_payload = policy or {
        "operations": [
            {"operation_kind": "read", "handler": "read_handler", "allow": True},
            {"operation_kind": "write", "handler": "write_handler", "allow": False},
        ]
    }
    policy_path.write_text(json.dumps(policy_payload), encoding="utf-8")
    sources: list[EnforcementSourceSnapshot] = []
    paths: list[Path] = []
    for kind in REQUIRED_ENFORCEMENT_KINDS:
        path = protected / f"{kind}.metadata"
        content = f"{kind}:metadata".encode()
        path.write_bytes(content)
        paths.append(path)
        sources.append(
            EnforcementSourceSnapshot(
                kind=kind,
                name=f"{kind}-effective",
                sha256=_digest(f"probos.enforcement-source.{kind}.v1", content),
                version="1",
                item_count=1,
            )
        )
    return {
        "repository": repository,
        "selected_source": selected_source,
        "protected": protected,
        "issuer": issuer,
        "policy": policy_path,
        "sources": tuple(sources),
        "source_paths": tuple(paths),
        "db": tmp_path / "execution_authority.db",
        "worker": tmp_path / "worker",
    }


def _authority(
    layout: dict[str, Any],
    *,
    session: str = "runtime-session",
    timeout_ms: int = 5000,
    connection_factory: Any = None,
) -> ProtectedExecutionAuthority:
    return ProtectedExecutionAuthority(
        db_path=layout["db"],
        runtime_session_id=session,
        witness_busy_timeout_ms=timeout_ms,
        protected_installation_root=layout["protected"],
        policy_path=layout["policy"],
        worker_write_roots=(layout["worker"],),
        connection_factory=connection_factory,
        issuer_module_path=layout["issuer"],
    )


def _publication(layout: dict[str, Any], **overrides: Any) -> ManifestPublicationRequest:
    values = {
        "repository_root": layout["repository"],
        "selected_agent_id": "selected-agent-canary",
        "selected_agent_type": "Builder",
        "selected_agent_source_path": layout["selected_source"],
        "enforcement_sources": layout["sources"],
        "enforcement_source_paths": layout["source_paths"],
        "policy_path": layout["policy"],
        "protected_installation_root": layout["protected"],
        "worker_write_roots": (layout["worker"],),
    }
    values.update(overrides)
    return ManifestPublicationRequest(**values)


def _admission(
    manifest: Any,
    *,
    session: object = "runtime-session",
    operation: object = "read",
    target: object = "target",
    shape: object | None = None,
) -> AdmissionRequest:
    return AdmissionRequest(
        manifest_id=manifest.manifest_id,
        generation=manifest.generation,
        runtime_session_id=session,
        operation_kind=operation,
        target_identity=target,
        parameter_shape_sha256=shape or hashlib.sha256(b"shape").hexdigest(),
    )


@pytest.fixture
async def strict_runtime(tmp_path: Path) -> Any:
    operations = [
        {
            "operation_kind": kind,
            "handler": f"{kind}_handler",
            "allow": True,
        }
        for kind in (
            "filesystem", "shell", "code", "network", "mcp",
            "browser", "delegation", "tool",
        )
    ]
    layout = _make_layout(tmp_path, policy={"operations": operations})
    layout["worker"].mkdir()
    authority = _authority(layout)
    await authority.start()
    manifest = await authority.publish_manifest(_publication(layout))
    layout["manifest"] = manifest
    decision = await authority.admit(
        _admission(manifest, operation="filesystem")
    )
    assert decision.grant is not None
    broker = GovernedEffectBroker(
        authority=authority,
        runtime_session_id="runtime-session",
        lease_seconds=120,
        max_attempts=3,
        permit_secret=b"p" * 32,
    )
    await broker.start()
    registry = ToolRegistry()
    registry.arm_effect_broker(broker)
    executor = ToolExecutor(registry=registry, effect_broker=broker)
    try:
        yield layout, authority, broker, registry, executor
    finally:
        registry.disarm_effect_broker()
        await broker.stop()
        await authority.stop()


def _register(
    registry: ToolRegistry,
    tool: Any,
    *,
    permissions: dict[str, str] | None = None,
) -> None:
    registry.register(tool, default_permissions=permissions)


async def _invoke(
    executor: ToolExecutor,
    tool_id: str,
    params: dict[str, Any],
    logical_key: str,
    *,
    provider_id: str = "provider-call",
) -> ToolResult:
    return await executor.invoke(
        "selected-agent-canary",
        tool_id,
        params,
        protected_logical_key=logical_key,
        protected_provider_call_id=provider_id,
        required=ToolPermission.READ,
        context={},
    )


@pytest.mark.asyncio
async def test_broker_denies_before_admission_with_the_policy_reason(
    strict_runtime: Any, spawns: _Spawns, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, authority, _, registry, executor = strict_runtime
    live = _gate(_stack())
    broken = _gate(_stack())
    monkeypatch.setattr(broken, "judge", _boom)
    cases = [  # label, the tool registered as run_command, the command, the reason the broker records
        ("forbid", _tool(live), "curl -sS example.com", "command_policy_forbid"),
        ("escalate", _tool(live), "git push origin", "command_policy_escalate"),
        ("judge_raises", _tool(broken), "echo hi", "command_policy_unavailable"),
        # controls: an allowed command, and a forbidden-looking one with no policy, are still refused as an unproven shell
        ("allow", _tool(live), "echo hi", _PRISTINE_REASON),
        ("no_policy", _tool(None), "curl -sS example.com", _PRISTINE_REASON),
    ]
    seen: dict[str, tuple[Any, ...]] = {}

    for label, tool, command, _ in cases:
        assert type(tool).__module__ == "probos.cognitive.swe_harness.tools"  # premise: the real tool, routed by its class
        _register(registry, tool)
        result = await _invoke(
            executor, "run_command", {"command": command}, f"key-{label}", provider_id=f"call-{label}",
        )
        operation_id = result.metadata["operation_id"]
        operations = await authority.query_effect_operations(operation_id)
        attempts = await authority.query_effect_attempts(operation_id)
        assert len(operations) == len(attempts) == 1
        operation, attempt = operations[0], attempts[0]
        seen[label] = (
            result.error,
            result.metadata["effect_outcome"],
            operation.state,
            operation.reason_code,
            operation.effect_class,
            attempt.state,
            attempt.reason_code,
            attempt.started_at_ms,
        )

    # the result error and the effect record (operation and attempt) carry the reason the shell adapter put on the request,
    # and the attempt never started: the broker refused before it admitted the tool
    assert seen == {label: (reason, "denied", "denied", reason, "shell", "denied", reason, None) for label, _, _, reason in cases}
    assert len({reason for _, _, _, reason in cases}) == 4  # the reasons differ, so one fixed refusal would not pass
    assert spawns.calls == []  # nothing was spawned: the broker refused every one before the tool ran
    assert spawns.attached == []


# --------------------------------------------------------------------------------------
# 12. Tool -> executor hook -> the AD-1224 record
# --------------------------------------------------------------------------------------

_SHELL_PERMISSIONS = {"ensign": "none", "lieutenant": "none", "commander": "write", "senior_officer": "full"}
_SENTINEL = "SENTINEL-7Q"


class _StandInTool:
    """Not a RunCommandTool: a tool whose result metadata is whatever the test hands it."""

    tool_id = "stand_in_tool"
    name = "Stand In"
    tool_type = ToolType.UTILITY_AGENT
    description = "returns the metadata it was given"
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}
    output_schema: dict[str, Any] = {"type": "object"}

    def __init__(self, metadata: Any) -> None:
        self._metadata = metadata

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(error="stand-in refusal", metadata=self._metadata)


def _recorded(tool: Any) -> tuple[ToolRegistry, ToolExecutor, list[tuple[Any, dict[str, Any]]]]:
    """A real executor over a real registry holding ``tool`` (shell permission by rank), with the AD-1224 hook on the bus."""
    registry = ToolRegistry()
    registry.register(tool, default_permissions=dict(_SHELL_PERMISSIONS))
    executor = ToolExecutor(registry=registry)
    emitted: list[tuple[Any, dict[str, Any]]] = []
    executor.add_post_hook(make_audit_hook(lambda event, payload: emitted.append((event, payload))))
    return registry, executor, emitted


async def _call(executor: ToolExecutor, tool_id: str, params: dict[str, Any]) -> ToolResult:
    return await executor.invoke(
        "agent-1", tool_id, params, required=ToolPermission.WRITE, agent_rank="commander", context={},
    )


@pytest.mark.asyncio
async def test_ad1224_record_carries_the_decision(spawns: _Spawns, child_path: str) -> None:
    config = _stack()
    gate = _gate(config)
    forbidden = f"curl {_SENTINEL}"
    registry, executor, emitted = _recorded(_tool(gate))
    # premise: the permission ladder is real, and this rank holds the shell permission the call needs
    assert registry.check_permission("agent-1", "run_command", ToolPermission.WRITE, agent_rank="commander")
    assert not registry.check_permission("agent-1", "run_command", ToolPermission.WRITE, agent_rank="ensign")
    assert _words(forbidden, "posix", config) == [["curl", _SENTINEL]]

    refused = await _call(executor, "run_command", {"command": forbidden})

    assert refused.error is not None
    assert spawns.calls == []
    assert len(emitted) == 1
    event, payload = emitted[0]
    assert event is EventType.TOOL_INVOKED
    assert payload["is_error"] is True
    assert payload["agent_id"] == "agent-1"
    record = refused.metadata["command_policy"]
    assert record["decision"] == "forbid"
    assert payload["command_policy"] == record  # the record the tool reported is the one retained (kills X1)
    encoded = json.dumps(payload, sort_keys=True)
    assert _SENTINEL not in encoded  # no command text ...
    assert _NO_CURL_WHY not in encoded and _NO_CURL_INSTEAD not in encoded  # ... and no justification or alternative
    assert len(encoded.encode("utf-8")) <= 4096  # one AD-1224 record is at most 4,096 bytes
    # control: a command that runs is recorded too, as an allow
    ran = await _call(executor, "run_command", {"command": "echo hi"})
    assert ran.error is None
    assert emitted[1][1]["command_policy"] == ran.metadata["command_policy"]
    assert emitted[1][1]["command_policy"]["decision"] == "allow"
    assert emitted[1][1]["is_error"] is False

    # no policy: the payload has no command_policy key at all (and the result carries no metadata for it)
    _, bare_executor, bare_emitted = _recorded(_tool(None))
    bare = await _call(bare_executor, "run_command", {"command": "echo hi"})
    assert bare == _ran()
    assert len(bare_emitted) == 1
    assert bare_emitted[0][0] is EventType.TOOL_INVOKED
    assert "command_policy" not in bare_emitted[0][1]
    assert bare_emitted[0][1]["is_error"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("forgery", ["valid_control", "extra_key_with_command_text", "wrong_schema", "metadata_not_a_dict"])
async def test_ad1224_record_drops_a_record_the_tool_result_forged(forgery: str) -> None:
    gate = _gate(_stack())
    genuine = gate.judge(f"curl {_SENTINEL}", site="run_command_tool", search_path=_CHILD_PATH).record
    assert genuine is not None and genuine["decision"] == "forbid"
    if forgery == "valid_control":
        metadata: Any = {"command_policy": genuine}
    elif forgery == "extra_key_with_command_text":
        metadata = {"command_policy": {**genuine, "command": f"curl {_SENTINEL}"}}
    elif forgery == "wrong_schema":
        metadata = {"command_policy": {**genuine, "schema": "probos.command_policy.record/v0"}}
    else:
        metadata = "command_policy"
    _, executor, emitted = _recorded(_StandInTool(metadata))

    result = await _call(executor, "stand_in_tool", {})

    assert result.error == "stand-in refusal"
    assert len(emitted) == 1  # the event is still emitted: only the forged record is dropped
    payload = emitted[0][1]
    if forgery == "valid_control":
        # r1 (F4): this row used to assert the record was retained ("a well-formed record from any tool"), which pinned the
        # defect. The AD-1224 sink reads a record only from the resolved ``run_command`` tool, so a well-formed record
        # from this stand-in tool is not read. The positive control (the same record from ``run_command``) is B14.
        assert "command_policy" not in payload
    else:
        assert "command_policy" not in payload
    assert _SENTINEL not in json.dumps(payload, sort_keys=True)


# --------------------------------------------------------------------------------------
# 13. Repair r1 (review F2-F5): the object judged is the object spawned; a failed spawn keeps its decision;
#     the AD-1224 sink reads only run_command's record and keeps the whole envelope in budget
# --------------------------------------------------------------------------------------


def _no_curl_gate() -> CommandPolicyGate:
    """``forbid curl``, everything else allowed (the gate of B11-B13)."""
    return _gate(_policy(_rule("no-curl", ["curl"], "forbid"), unmatched="allow"))


class _LyingStr(str):
    """A ``str`` subclass whose text is ``curl x`` and whose ``__str__`` says ``echo hi``."""

    def __str__(self) -> str:
        return "echo hi"


class _Stateful:
    """Not a ``str``: each ``__str__`` call answers the next text (the last one repeats) and is counted."""

    def __init__(self, *texts: str) -> None:
        self._texts = texts
        self.calls = 0

    def __str__(self) -> str:
        text = self._texts[min(self.calls, len(self._texts) - 1)]
        self.calls += 1
        return text


@pytest.mark.asyncio
async def test_r1_policy_spawns_the_object_it_judged(spawns: _Spawns, child_path: str) -> None:
    command = "".join(["echo", " hi"])  # built at run time: a distinct object, not an interned literal
    tool = _tool(_no_curl_gate())

    result = await tool.invoke({"command": command})

    assert result.error is None
    assert result.metadata["command_policy"]["decision"] == "allow"
    assert len(spawns.calls) == 1
    assert spawns.calls[0][0][0] is command  # the very object the policy judged is the one spawned
    assert spawns.calls == [_spawn_of("echo hi")]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["number", "str_subclass", "stateful"])
async def test_r1_policy_refuses_a_command_that_is_not_text(
    variant: str, spawns: _Spawns, child_path: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The tool's failure handler logs ``command=%s``, which converts a non-text command once per log handler (observed: 4 calls
    # under pytest, not 1). The count below is about what the policy and the spawn read, so that line is silenced.
    monkeypatch.setattr(swe_tools.logger, "disabled", True)
    stateful = _Stateful("echo ok", "curl x")
    command: Any = {"number": 5, "str_subclass": _LyingStr("curl x"), "stateful": stateful}[variant]
    tool = _tool(_no_curl_gate())

    result = await tool.invoke({"command": command})

    assert result.error == "run_command failed: command_policy_command_type_invalid"
    assert result.output is None
    assert result.metadata == {}  # nothing was judged, so no decision is recorded
    assert spawns.calls == []
    assert spawns.attached == []
    if variant == "stateful":
        assert stateful.calls == 1  # only the tool's own "is it empty" line converted it; the policy never read it
    # control: a plain str of the text the stateful object first said is judged and run
    ran = await tool.invoke({"command": "echo ok"})
    assert ran.error is None
    assert spawns.calls == [_spawn_of("echo ok")]


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["no_gate", "unconfigured_gate"])
async def test_r1_no_policy_converts_as_before(variant: str, spawns: _Spawns, child_path: str) -> None:
    gate = None if variant == "no_gate" else _gate(CommandPolicyConfig())
    if gate is not None:
        assert gate.configured is False  # premise: an unconfigured gate is no policy
    tool = _tool(gate)
    stateful = _Stateful("echo a", "echo b")

    result = await tool.invoke({"command": stateful})

    assert stateful.calls == 2  # the base's two conversions: the "is it empty" line, then the spawn (kills T5)
    assert spawns.calls == [_spawn_of("echo b")]
    assert result.error is None
    assert result.metadata == {}
    spawns.reset()
    number = await tool.invoke({"command": 5})
    assert spawns.calls == [_spawn_of("5")]
    assert number.error is None
    assert number.metadata == {}


@pytest.mark.asyncio
async def test_r1_spawn_failure_keeps_the_decision(
    spawns: _Spawns, child_path: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def refuse(*args: Any, **kwargs: Any) -> Any:
        raise OSError("spawn refused")

    monkeypatch.setattr(asyncio, "create_subprocess_shell", refuse)
    gate = _no_curl_gate()

    # (a) the spawn raises after the policy allowed the command: the failure is reported with the decision
    failed = await _tool(gate).invoke({"command": "echo hi"})

    assert failed.error == "run_command failed: spawn refused"
    assert failed.output is None
    assert set(failed.metadata) == {"command_policy"}
    assert failed.metadata["command_policy"]["decision"] == "allow"  # kills T6
    assert spawns.calls == []
    # ... and the AD-1224 hook retains that decision (through the real executor)
    _, executor, emitted = _recorded(_tool(gate))
    recorded = await _call(executor, "run_command", {"command": "echo hi"})
    assert recorded.error == "run_command failed: spawn refused"
    assert len(emitted) == 1
    assert emitted[0][1]["is_error"] is True
    assert emitted[0][1]["command_policy"] == recorded.metadata["command_policy"]
    assert emitted[0][1]["command_policy"]["decision"] == "allow"
    # controls: with no policy the same failure carries no metadata; a judgement that raises records no decision
    assert await _tool(None).invoke({"command": "echo hi"}) == ToolResult(error="run_command failed: spawn refused")
    with pytest.MonkeyPatch.context() as broken:
        broken.setattr(gate, "judge", _boom)
        unjudged = await _tool(gate).invoke({"command": "echo hi"})
    assert unjudged.error == "run_command failed: judge exploded"
    assert unjudged.metadata == {}


@pytest.mark.asyncio
async def test_r1_real_spawn_failure_keeps_the_decision(tmp_path: Path) -> None:
    """(b) A REAL failing spawn (no recorder): the working directory does not exist, so the shell cannot start."""
    missing = tmp_path / "missing"
    assert not missing.exists()  # premise
    tool = _tool(_no_curl_gate())

    result = await tool.invoke({"command": "echo hi", "working_directory": str(missing)})

    assert result.error is not None
    assert result.error.startswith("run_command failed:")
    assert result.output is None
    assert set(result.metadata) == {"command_policy"}
    assert result.metadata["command_policy"]["decision"] == "allow"  # kills T6 against the real asyncio
    # control: with no policy the same real failure carries no metadata
    bare = await _tool(None).invoke({"command": "echo hi", "working_directory": str(missing)})
    assert bare.error is not None and bare.error.startswith("run_command failed:")
    assert bare.metadata == {}


class _RunCommandStandIn(_StandInTool):
    """A tool that registers as ``run_command`` and reports the metadata it was given."""

    tool_id = "run_command"


class _WriteFileStandIn(_StandInTool):
    """A tool that registers as ``write_file`` and reports the metadata it was given."""

    tool_id = "write_file"


@pytest.mark.asyncio
async def test_r1_ad1224_reads_only_the_run_command_tool() -> None:
    genuine = _gate(_stack()).judge(f"curl {_SENTINEL}", site="run_command_tool", search_path=_CHILD_PATH).record
    assert genuine is not None and genuine["decision"] == "forbid"
    # control: the genuine record from the tool that is run_command is retained
    _, executor, emitted = _recorded(_RunCommandStandIn({"command_policy": genuine}))
    await _call(executor, "run_command", {})
    assert len(emitted) == 1
    assert emitted[0][1]["command_policy"] == genuine
    # the review's forgery: well-typed fields holding command text; the whole record is dropped, never repaired
    forgery = {
        **genuine,
        "canonical_key": "echo REVIEW_RAW_COMMAND --token=abc",
        "dialect": "bash",
        "causes": [{"kind": "rule", "segment": 0, "rule": "curl evil --token=abc"}],
    }
    _, executor, emitted = _recorded(_RunCommandStandIn({"command_policy": forgery}))
    await _call(executor, "run_command", {})
    assert len(emitted) == 1  # the event is still emitted
    assert "command_policy" not in emitted[0][1]
    encoded = json.dumps(emitted[0][1], sort_keys=True)
    assert "REVIEW_RAW_COMMAND" not in encoded
    assert "--token=abc" not in encoded
    # a genuine record from any other tool is not read (kills X2)
    _, executor, emitted = _recorded(_WriteFileStandIn({"command_policy": genuine}))
    await _call(executor, "write_file", {})
    assert len(emitted) == 1
    assert "command_policy" not in emitted[0][1]


def _wide_gate() -> CommandPolicyGate:
    """M1 #13's gate: twenty ``forbid`` rules with 64-character names, each matching one of twenty segments."""
    rules = [_rule(f"r{index:02d}-" + "x" * 60, [f"c{index:02d}"], "forbid") for index in range(20)]
    return _gate(_policy(*rules, unmatched="allow"))


_WIDE_COMMAND = ";".join(f"c{index:02d}" for index in range(20))


def _wide_record() -> dict[str, Any]:
    record = _wide_gate().judge(_WIDE_COMMAND, site="run_command_tool", search_path=_CHILD_PATH).record
    assert record is not None and record["decision"] == "forbid"
    # premise: the maximal record, eight names of 64 characters and eight causes, with twelve of each omitted
    assert [len(name) for name in record["matched_rules"]] == [64] * 8
    assert len(record["causes"]) == 8
    assert record["matched_rules_omitted"] == 12
    assert record["causes_omitted"] == 12
    return record


def _policy_payload(record: dict[str, Any] | None, pad: int) -> dict[str, Any]:
    payload: dict[str, Any] = {"tool_id": "run_command", "agent_id": "agent-1", "invocation_id": "inv-1", "pad": "x" * pad}
    if record is not None:
        payload["command_policy"] = record
    return payload


def test_r1_bounded_policy_record_steps() -> None:
    bound = executor_module._RECORD_MAX_BYTES
    size = executor_module._record_size
    record = _wide_record()
    compact = compact_command_policy_record(record)
    assert compact != record  # premise: the compact form is a different (smaller) record
    # premise: a record in an envelope with no padding fits whole, and the compact form is smaller than the whole
    assert size(_policy_payload(record, 0)) <= bound
    assert size(_policy_payload(compact, 0)) < size(_policy_payload(record, 0))

    # (i) a payload that fits is returned as the same object (kills X4)
    fits = _policy_payload(record, 0)
    assert executor_module._bounded_policy_record(fits) is fits

    # (ii) over with the whole record, within the bound with the compact one: the compact record, every other key equal
    pad = bound - size(_policy_payload(compact, 0))
    over = _policy_payload(record, pad)
    assert size(over) > bound  # premise
    assert size(_policy_payload(compact, pad)) == bound  # premise
    stepped = executor_module._bounded_policy_record(over)
    assert stepped["command_policy"] == compact
    assert stepped == {**over, "command_policy": compact}
    assert {key: value for key, value in stepped.items() if key != "command_policy"} == {
        key: value for key, value in over.items() if key != "command_policy"
    }

    # (iii) over even with the compact record: no command_policy, every other key unchanged (kills X5)
    pad = bound - size(_policy_payload(compact, 0)) + 1
    way_over = _policy_payload(record, pad)
    assert size(_policy_payload(compact, pad)) > bound  # premise
    dropped = executor_module._bounded_policy_record(way_over)
    assert "command_policy" not in dropped
    assert dropped == {key: value for key, value in way_over.items() if key != "command_policy"}

    # (iv) an oversized payload with no record is returned as the same object
    no_record = _policy_payload(None, bound * 2)
    assert size(no_record) > bound
    assert executor_module._bounded_policy_record(no_record) is no_record


def _paired(executor: ToolExecutor, log: Any, *, max_records_per_run: int = DEFAULT_MAX_RECORDS_PER_RUN) -> None:
    """tests/test_ad1224_durable_tool_start.py:114-125 (copied; tests do not import each other)."""
    executor.add_pre_hook(make_start_hook(event_log=log, max_records_per_run=max_records_per_run))
    audit = make_audit_hook(event_log=log)
    executor.add_post_hook(audit)
    executor.add_terminal_hook(audit)


async def _rows(log: EventLog, event: str) -> list[dict[str, Any]]:
    """tests/test_ad1224_durable_tool_start.py:110-112 (copied)."""
    return [row for row in await log.query(category="tool", limit=1000) if row["event"] == event]


async def _wide_call(executor: ToolExecutor, provenance: str) -> ToolResult:
    return await executor.invoke(
        provenance, "run_command", {"command": _WIDE_COMMAND}, required=ToolPermission.WRITE, agent_rank="commander",
        context={"thread_id": provenance, "_crew_work_item_id": provenance, "_agentic_run_id": provenance},
    )


def _without_error(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "error"}


@pytest.mark.asyncio
async def test_r1_the_envelope_stays_within_budget_at_maximal_fields(
    spawns: _Spawns, child_path: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AD-1224 envelope budget (F5) under a LOWERED bound: the real typed record cannot overflow 4,096 (B16b)."""
    monkeypatch.setattr(executor_module, "_RECORD_MAX_BYTES", 3000)
    bound = executor_module._RECORD_MAX_BYTES
    assert bound == 3000  # premise: the patch is the bound the executor reads
    size = executor_module._record_size
    quotes = '"' * 200  # every character of caller-chosen provenance doubles when escaped into the envelope
    _, executor, emitted = _recorded(_tool(_wide_gate()))

    refused = await _wide_call(executor, quotes)

    assert refused.error is not None
    assert spawns.calls == []
    full = refused.metadata["command_policy"]
    assert full["decision"] == "forbid"
    compact = compact_command_policy_record(full)
    assert len(emitted) == 1
    payload = _without_error(emitted[0][1])
    # premises: with the whole record this envelope is over the bound; with the compact record it is within it
    assert size({**payload, "command_policy": full}) > bound
    assert size({**payload, "command_policy": compact}) <= bound
    # the emitted envelope is within budget and its record is the compact form of the whole one (kills X3)
    assert size(payload) <= bound
    assert payload["command_policy"] == compact
    assert payload["command_policy"]["decision"] == "forbid"
    assert payload["command_policy"]["matched_rules"] == []
    assert payload["command_policy"]["matched_rules_omitted"] == 20
    if "params" in payload:
        assert payload["params"]["detail_omitted"] is True  # the first step (parameter detail) ran before the record's
    # control: the same call with plain provenance keeps the whole record
    _, plain_executor, plain_emitted = _recorded(_tool(_wide_gate()))
    plain = await _wide_call(plain_executor, "t")
    plain_payload = _without_error(plain_emitted[0][1])
    assert plain_payload["command_policy"] == plain.metadata["command_policy"] == full
    assert size(plain_payload) <= bound

    # durable: a real EventLog persists the same compact record, within the same bound
    log = EventLog(db_path=tmp_path / "events.db")
    await log.start()
    try:
        registry = ToolRegistry()
        registry.register(_tool(_wide_gate()), default_permissions=dict(_SHELL_PERMISSIONS))
        durable_executor = ToolExecutor(registry=registry)
        _paired(durable_executor, log)

        await _wide_call(durable_executor, quotes)

        rows = await _rows(log, EventType.TOOL_INVOKED.value)
        assert len(rows) == 1
        data = rows[0]["data"]
        assert size({**data, "command_policy": full}) > bound  # premise, on the persisted envelope
        assert size(data) <= bound
        assert data["command_policy"] == compact
        assert data["command_policy"]["decision"] == "forbid"
    finally:
        await log.stop()

    # drop step: a bound below even the compact envelope removes the record and leaves the rest of the payload
    monkeypatch.setattr(executor_module, "_RECORD_MAX_BYTES", 1500)
    assert executor_module._RECORD_MAX_BYTES == 1500
    _, drop_executor, drop_emitted = _recorded(_tool(_wide_gate()))
    dropped = await _wide_call(drop_executor, quotes)
    assert dropped.metadata["command_policy"] == full  # the tool still reported the record; only the sink drops it
    drop_payload = _without_error(drop_emitted[0][1])
    assert size({**drop_payload, "command_policy": compact}) > 1500  # premise: the compact envelope is over 1,500
    assert "command_policy" not in drop_payload
    assert set(drop_payload) == set(payload) - {"command_policy"}


@pytest.mark.asyncio
async def test_r1_the_typed_record_fits_the_real_envelope_at_maximal_provenance(
    spawns: _Spawns, child_path: str, tmp_path: Path,
) -> None:
    """No patch: at the real 4,096-byte bound the typed record is kept whole even at maximal provenance.

    Measured 2026-10-16 (review round 2): the durable envelope is about 3,900 bytes with this record and ``'"' * 200``
    provenance (``_bounded_text`` caps each string at 128 JSON bytes, so 63 quotes, the worst escaping case), and, with the
    largest admitted record (1,898 characters) in its place (B31), 3,994 bytes in the emitted envelope and 3,975 bytes in
    the durable EventLog row: about 100 bytes of headroom under 4,096, not the 207 first stated. A record that grows
    (S2b's ``approval`` field, about 200 characters) fails B31 and may fail this test; S2b must re-measure and re-anchor
    B16, B16b and B31.
    """
    bound = executor_module._RECORD_MAX_BYTES
    assert bound == 4096  # premise: the real bound
    size = executor_module._record_size
    quotes = '"' * 200
    _, executor, emitted = _recorded(_tool(_wide_gate()))

    refused = await _wide_call(executor, quotes)

    full = refused.metadata["command_policy"]
    assert full["decision"] == "forbid"
    assert len(emitted) == 1
    payload = _without_error(emitted[0][1])
    assert payload["command_policy"] == full  # kept whole, not compacted
    assert size(payload) <= bound
    assert "params" not in payload or "detail_omitted" not in payload["params"]  # no parameter detail dropped
    # control: the same call with plain provenance keeps the whole record
    _, plain_executor, plain_emitted = _recorded(_tool(_wide_gate()))
    plain = await _wide_call(plain_executor, "t")
    assert _without_error(plain_emitted[0][1])["command_policy"] == plain.metadata["command_policy"] == full

    # durable: the persisted row keeps the same whole record
    log = EventLog(db_path=tmp_path / "events.db")
    await log.start()
    try:
        registry = ToolRegistry()
        registry.register(_tool(_wide_gate()), default_permissions=dict(_SHELL_PERMISSIONS))
        durable_executor = ToolExecutor(registry=registry)
        _paired(durable_executor, log)

        await _wide_call(durable_executor, quotes)

        rows = await _rows(log, EventType.TOOL_INVOKED.value)
        assert len(rows) == 1
        data = rows[0]["data"]
        assert data["command_policy"] == full
        assert size(data) <= bound
        assert "params" not in data or "detail_omitted" not in data["params"]
    finally:
        await log.stop()


# --------------------------------------------------------------------------------------
# S2a repair r2 (R2-M2): the child's PATHEXT verbatim, a posix built-in, the largest admitted record
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "refused"),
    [
        pytest.param(".EXE; .CMD;.BAT", True, id="lead_blank"),
        pytest.param(".EXE;.CMD ;.BAT", True, id="trail_blank"),
        pytest.param(".EXE;.CMD;.BAT", False, id="control"),
    ],
)
async def test_r2_tool_reads_the_childs_pathext_verbatim(
    value: str, refused: bool, spawns: _Spawns, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A PATHEXT with a blank is outside the grammar: the lookup answers nothing and the pinned rule refuses (kills G39)."""
    monkeypatch.setenv("PATH", "C:\\d1")
    monkeypatch.setenv("PATHEXT", value)
    passthrough = ("PATHEXT",)
    # premise: the child carries this exact PATHEXT, blanks included, on every host
    assert build_command_env(passthrough)["PATHEXT"] == value
    pin = "C:\\d1\\tool.CMD"
    config = _policy(_rule("pinned-tool", ["tool"], "allow", host_executable=[pin]), unmatched="escalate")
    gate = _gate(config, platform="win32", is_file=_IsFile({pin, "C:\\d1\\tool.BAT"}))
    tool = RunCommandTool(SimpleNamespace(), command_env_passthrough=passthrough, command_policy_gate=gate)  # type: ignore[arg-type]

    result = await tool.invoke({"command": "tool", "working_directory": "C:\\work"})

    if refused:
        assert result.error is not None
        assert result.metadata["command_policy"]["decision"] == "forbid"
        assert spawns.calls == []
    else:
        assert result.error is None, result.error
        assert result.metadata["command_policy"]["decision"] == "allow"
        assert len(spawns.calls) == 1


@pytest.mark.asyncio
async def test_r2_tool_refuses_a_pinned_posix_builtin_bare(spawns: _Spawns, child_path: str) -> None:
    """The shell runs its built-in ``echo``, not the file ``which`` names, so a bare pinned ``echo`` is refused (kills G49)."""
    config = _policy(_rule("echo", ["echo"], "allow", host_executable=["/bin/echo"]), unmatched="escalate")
    which = _Which({"echo": "/bin/echo"})
    tool = _tool(_gate(config, platform="linux", which=which))

    refused = await tool.invoke({"command": "echo hi"})

    assert refused.error is not None
    assert "/bin/echo" in refused.error
    assert refused.metadata["command_policy"]["decision"] == "forbid"
    assert spawns.calls == []
    assert which.calls == []  # a built-in is never looked up
    # control: the pinned absolute path is the file itself, and it runs
    allowed = await tool.invoke({"command": "/bin/echo hi"})
    assert allowed.error is None, allowed.error
    assert allowed.metadata["command_policy"]["decision"] == "allow"
    assert len(spawns.calls) == 1
    assert spawns.calls[0][0] == ("/bin/echo hi",)


class _MaximalRecordTool(_RunCommandStandIn):
    """Registers as ``run_command`` and returns a successful result carrying the metadata it was given."""

    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(output={}, metadata=self._metadata)


@pytest.mark.asyncio
async def test_r2_the_largest_admitted_record_fits_the_real_envelope(tmp_path: Path) -> None:
    """No patch: the largest record ``command_policy_record_of`` admits is kept whole at maximal provenance."""
    from probos.execution.command_gate import MAX_RECORD_CHARS, command_policy_record_of

    names = [    f"r{index}-" + "x" * 61 for index in range(8)]
    assert [len(name) for name in names] == [64] * 8
    record: dict[str, Any] = {
        "schema": "probos.command_policy.record/v1",
        "call_site": "run_command_tool",
        "decision": "escalate",
        "dialect": "posix",
        "policy_digest": "a" * 64,
        "canonical_key": "b" * 64,
        "canonical_kind": "script",
        "matched_rules": list(names),
        "matched_rules_omitted": 2**31 - 1,
        "causes": [{"kind": "rule", "segment": 2**31 - 1, "rule": name} for name in names],
        "causes_omitted": 2**31 - 1,
    }
    # premise: the record is admitted unchanged and is within its own character bound
    result = ToolResult(output={}, metadata={"command_policy": record})
    assert command_policy_record_of(result, tool_id="run_command") == record
    assert len(json.dumps(record, sort_keys=True)) <= MAX_RECORD_CHARS
    bound = executor_module._RECORD_MAX_BYTES
    assert bound == 4096  # premise: the real bound
    size = executor_module._record_size
    quotes = '"' * 200
    _, executor, emitted = _recorded(_MaximalRecordTool({"command_policy": record}))

    await _wide_call(executor, quotes)

    assert len(emitted) == 1
    payload = emitted[0][1]
    assert payload["command_policy"] == record  # kept whole, not compacted
    assert size(payload) <= bound

    # durable: the persisted row keeps the same whole record, within the same bound
    log = EventLog(db_path=tmp_path / "events.db")
    await log.start()
    try:
        registry = ToolRegistry()
        registry.register(_MaximalRecordTool({"command_policy": record}), default_permissions=dict(_SHELL_PERMISSIONS))
        durable_executor = ToolExecutor(registry=registry)
        _paired(durable_executor, log)

        await _wide_call(durable_executor, quotes)

        rows = await _rows(log, EventType.TOOL_INVOKED.value)
        assert len(rows) == 1
        data = rows[0]["data"]
        assert data["command_policy"] == record
        # measured by review round 2: 3,994 bytes emitted, 3,975 bytes durable (1,898-character record, 200-quote provenance)
        assert size(data) <= bound
    finally:
        await log.stop()
