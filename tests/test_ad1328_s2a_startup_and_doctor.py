"""AD-1328 S2a (#1530), milestone M4 -- the runtime's one command policy: wiring, startup, doctor and the starter.

Tests only. The contract is ``prompts/ad-1328-s2a-command-policy-wiring.md`` ("Tests", M4). The gate itself, the tool
path, the broker preflight and the shell agent are the other S2a files' targets; this file checks that the runtime builds
the one gate, that every place a ``run_command`` executes is handed it (the shell pool, the red team, the native tool),
that a wrong example stops startup, that ``probos doctor`` reports the policy, and that the starter policy holds. M4 #8
(the config surface) is ``test_policy_models_are_on_the_config_surface`` in ``tests/test_ad1328_s1_policy_models.py``,
which replaces S1's off-surface test; it is the one home of that assertion and is not repeated here.

No real shell starts: ``ShellCommandAgent._run_sync`` and ``RedTeamAgent._run_verify_sync`` are replaced by recorders, and
``asyncio.create_subprocess_shell`` and the tool's ``ProcessTree`` by stand-ins. Gates are built with an explicit
``platform=`` and a ``which`` that finds nothing, so no verdict depends on the host's shell or PATH. The exceptions are
the two tests that build a real ``ProbOSRuntime`` (its gate serves this host's dialects, ``_HOST_DIALECTS``) and the doctor
check, which reports for this host.

Each test asserts its premise and carries a control, so that it cannot pass because the whole machine refuses everything
or runs everything. The runtime doubles are copied from ``tests/test_bf890_shell_agent_env.py`` (no import across tests).
"""

from __future__ import annotations

import ast
import asyncio
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from probos.agents.red_team import RedTeamAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.cognitive.swe_harness.tools import register_native_swe_tools
from probos.config import ExecutionConfig, PoolConfig, SystemConfig, load_config
from probos.config_models.operations import CommandPolicyConfig
from probos.doctor import checks as _doctor_checks  # noqa: F401  (registers every check)
from probos.doctor.checks import command_policy_check
from probos.doctor.protocol import CheckOutcome, DoctorCheck, DoctorContext
from probos.doctor.registry import iter_checks
from probos.execution.command_gate import CommandPolicyGate, describe_command_policy
from probos.execution.command_policy import (
    CommandPolicySelfTestError,
    evaluate_command,
    policy_digest,
    self_test,
)
from probos.runtime import ProbOSRuntime
from probos.startup.finalize import _wire_native_swe_harness
from probos.substrate.agent import BaseAgent
from probos.substrate.pool import ResourcePool
from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.tools.registry import ToolRegistry
from probos.types import IntentMessage, IntentResult

_REPO = Path(__file__).resolve().parent.parent
_SRC_PROBOS = _REPO / "src" / "probos"
_STARTER = _REPO / "config" / "command_policy" / "starter.yaml"
#: The dialects a real runtime's gate serves on this host: ``cmd`` for the tool and PowerShell for the agents on Windows.
_HOST_DIALECTS = ("cmd", "powershell") if sys.platform == "win32" else ("posix",)

# ---------------------------------------------------------------------------
# Helpers (the policy builders copy the S1 shape; tests do not import each other)
# ---------------------------------------------------------------------------


def _rule(name: str, pattern: list[Any], decision: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "pattern": pattern,
        "decision": decision,
        "justification": f"{name} because",
    }
    if decision == "forbid":
        base["alternative"] = "use the governed path"
    return {**base, **extra}


def _policy_raw(*rules: dict[str, Any], unmatched: str = "allow", **extra: Any) -> dict[str, Any]:
    return {"rules": list(rules), "unmatched_decision": unmatched, **extra}


def _policy(*rules: dict[str, Any], unmatched: str = "allow", **extra: Any) -> CommandPolicyConfig:
    return CommandPolicyConfig.model_validate(_policy_raw(*rules, unmatched=unmatched, **extra))


def _config_with(*rules: dict[str, Any]) -> SystemConfig:
    return SystemConfig.model_validate({"execution": {"command_policy": _policy_raw(*rules)}})


def _no_curl(**override: Any) -> dict[str, Any]:
    """Forbids ``curl`` and names ``http_fetch``; its examples hold under every dialect."""
    return {
        **_rule(
            "no-curl", ["curl"], "forbid",
            justification="a download from a shell skips the governed fetch", alternative="use http_fetch",
            match=["curl example.com"], not_match=["git status"],
        ),
        **override,
    }


def _push_waits(**override: Any) -> dict[str, Any]:
    """Escalates ``git push``; its examples hold under every dialect."""
    return {
        **_rule(
            "push-waits", ["git", "push"], "escalate",
            justification="a push publishes the ship's work", match=["git push"], not_match=["git pull"],
        ),
        **override,
    }


def _which_nothing(name: str, path: str | None = None) -> None:
    """A program lookup that finds nothing: no verdict here depends on the host's PATH."""
    return None


def _gate(*rules: dict[str, Any], platform: str = "linux") -> CommandPolicyGate:
    return CommandPolicyGate(_policy(*rules), platform=platform, which=_which_nothing, is_file=lambda path: False)


def _starter_raw() -> dict[str, Any]:
    loaded = yaml.safe_load(_STARTER.read_text(encoding="utf-8"))
    assert set(loaded) == {"command_policy"}  # the file holds the one mapping an operator copies under ``execution:``
    raw: dict[str, Any] = loaded["command_policy"]
    return raw


# ---------------------------------------------------------------------------
# Doubles copied from tests/test_bf890_shell_agent_env.py (the BF-890 wiring-site fakes)
# ---------------------------------------------------------------------------


class _FakeAgentRegistry:
    def __init__(self) -> None:
        self.registered: list[Any] = []

    async def register(self, agent: Any) -> None:
        self.registered.append(agent)


class _FakeCapabilityRegistry:
    def __init__(self) -> None:
        self.registered: list[str] = []

    def register(self, agent_id: str, capabilities: Any) -> None:
        self.registered.append(agent_id)


class _FakeGossip:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def update_local(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)


class _FakeTrustNetwork:
    def __init__(self) -> None:
        self.created: list[str] = []

    def get_or_create(self, agent_id: str) -> None:
        self.created.append(agent_id)


class _FakeEventLog:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> None:
        self.entries.append(kwargs)


class _FakeRuntimeSelf:
    """The attributes ``ProbOSRuntime._spawn_red_team`` reads, around a real ``SystemConfig``.

    With ``gate`` the double also carries ``command_policy_gate``; without it, like a runtime double written before the
    gate existed, it has no such attribute.
    """

    def __init__(self, config: SystemConfig, gate: CommandPolicyGate | None = None) -> None:
        self.config = config
        self.registry = _FakeAgentRegistry()
        self.capability_registry = _FakeCapabilityRegistry()
        self.gossip = _FakeGossip()
        self.trust_network = _FakeTrustNetwork()
        self.event_log = _FakeEventLog()
        self.red_team_agents: list[RedTeamAgent] = []
        if gate is not None:
            self.command_policy_gate = gate


class _RecorderAgent(BaseAgent):
    """A pool member that records the NAMES of the spawn kwargs its pool handed its constructor, and does nothing else."""

    agent_type = "recorder"

    def __init__(self, pool: str = "default", **kwargs: Any) -> None:
        self.received_kwarg_names: tuple[str, ...] = tuple(sorted(kwargs))
        super().__init__(pool, **kwargs)

    async def perceive(self, intent: dict[str, Any]) -> Any:
        return None

    async def decide(self, observation: Any) -> Any:
        return None

    async def act(self, plan: Any) -> Any:
        return None

    async def report(self, result: Any) -> dict[str, Any]:
        return {}


class _FakePoolRuntime:
    """The attributes ``ProbOSRuntime.create_pool`` reads, around a real ``SystemConfig``, registry and spawner.

    With ``gate`` the double also carries ``command_policy_gate``; without it the attribute does not exist. There is
    deliberately no ``onboarding`` attribute: the factory reads it with ``getattr``, and without it a pool is wired to
    nothing.
    """

    def __init__(self, gate: CommandPolicyGate | None = None) -> None:
        self.config = SystemConfig(pools=PoolConfig(default_pool_size=2, min_pool_size=1, max_pool_size=3))
        self.pools: dict[str, ResourcePool] = {}
        self.registry = AgentRegistry()
        self.spawner = AgentSpawner(self.registry)
        self.spawner.register_template("shell_command", ShellCommandAgent)
        self.spawner.register_template("recorder", _RecorderAgent)
        self.acm = None
        self.ontology = None
        self.event_log = _FakeEventLog()
        if gate is not None:
            self.command_policy_gate = gate


async def _stop_pools(*runtimes: _FakePoolRuntime) -> None:
    """Stop every pool the fake runtimes hold; a stop that raises does not skip the pools after it."""
    errors: list[Exception] = []
    for runtime in runtimes:
        for pool in list(runtime.pools.values()):
            try:
                await pool.stop()
            except Exception as error:  # reported below, once every pool has been asked to stop
                errors.append(error)
    if errors:
        raise errors[0]


class _FakeExecutor:
    """Stands in for the ToolExecutor: ``_wire_native_swe_harness`` only calls ``add_pre_hook`` on it."""

    def __init__(self) -> None:
        self.pre_hooks: list[Any] = []

    def add_pre_hook(self, hook: Any) -> None:
        self.pre_hooks.append(hook)


class _FakeProcess:
    """What ``asyncio.create_subprocess_shell`` is replaced by returns: a finished command with some output."""

    returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"out", b""


class _FakeTree:
    def kill(self) -> None:
        return None

    def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Recorders: no test here starts a shell
# ---------------------------------------------------------------------------


@pytest.fixture
def shell_runs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace ``ShellCommandAgent._run_sync`` with a recorder; the commands that reached it, in order."""
    ran: list[str] = []

    def record(self: ShellCommandAgent, command: str, deadline: float | None = None, slot: Any = None) -> dict[str, Any]:
        ran.append(command)
        return {"success": True, "data": {"stdout": "ok", "stderr": "", "exit_code": 0, "command": command}}

    monkeypatch.setattr(ShellCommandAgent, "_run_sync", record)
    return ran


@pytest.fixture
def reruns(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace ``RedTeamAgent._run_verify_sync`` with a recorder of the commands it was asked to re-run."""
    seen: list[str] = []

    def record(command: str, env: Any, deadline: float | None = None, slot: Any = None) -> tuple[int, str]:
        seen.append(command)
        return (0, "")

    monkeypatch.setattr(RedTeamAgent, "_run_verify_sync", staticmethod(record))
    return seen


@pytest.fixture
def spawns(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    """Replace ``asyncio.create_subprocess_shell`` (and the tool's ``ProcessTree``): each spawn, as ``(args, kwargs)``."""
    spawned: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def fake_spawn(*args: Any, **kwargs: Any) -> _FakeProcess:
        spawned.append((args, kwargs))
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_spawn)
    monkeypatch.setattr(
        "probos.cognitive.swe_harness.tools.ProcessTree", SimpleNamespace(attach=lambda proc: _FakeTree()),
    )
    return spawned


async def _through_the_shell_agent(member: ShellCommandAgent, command: str, ran: list[str]) -> tuple[bool, dict[str, Any]]:
    """Run ``command`` through ``member._run_command``: ``(reached the shell stand-in, the result)``."""
    before = len(ran)
    result = await member._run_command(command)
    return ran[before:] == [command], result


# ---------------------------------------------------------------------------
# M4 #1: the runtime builds the gate, and a wrong example stops startup
# ---------------------------------------------------------------------------


def test_runtime_builds_the_gate_and_a_wrong_example_stops_startup(tmp_path: Path) -> None:
    """``ProbOSRuntime.__init__`` builds the one gate: inert by default, loaded from the config, and a wrong example raises.

    A runtime built with no rules has an unconfigured gate; one built with rules has a configured gate carrying the
    policy's digest and a passing self-test per dialect this host's call sites use; one built with a rule whose
    ``match`` example cannot match under any dialect raises ``CommandPolicySelfTestError`` naming the rule and the
    example, before the runtime touched the disk.
    """
    default = ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path / "default" / "data")
    assert isinstance(default.command_policy_gate, CommandPolicyGate)
    assert default.command_policy_gate.configured is False
    assert default.command_policy_gate.digest is None
    assert default.command_policy_gate.self_test_reports == ()
    # premise: constructing a runtime does write to the disk, so a construction that stopped early is told apart by it
    assert any((tmp_path / "default").rglob("*"))

    configured = _config_with(_no_curl(), _push_waits())
    loaded = ProbOSRuntime(config=configured, data_dir=tmp_path / "loaded" / "data")
    gate = loaded.command_policy_gate
    assert gate.configured is True
    assert gate.config is configured.execution.command_policy
    assert gate.digest == policy_digest(configured.execution.command_policy)
    assert gate.dialects == _HOST_DIALECTS
    assert [(report.dialect, report.passed) for report in gate.self_test_reports] == [(d, True) for d in _HOST_DIALECTS]

    # the neighbour above, one change away: the first rule's match example cannot match under any dialect
    wrong = _config_with(_no_curl(match=["wget example.com"]), _push_waits())
    with pytest.raises(CommandPolicySelfTestError) as raised:
        ProbOSRuntime(config=wrong, data_dir=tmp_path / "wrong" / "data")
    assert "'no-curl'" in str(raised.value)
    assert "'wget example.com'" in str(raised.value)
    assert "'push-waits'" not in str(raised.value)  # the rule whose examples hold is not named
    assert not (tmp_path / "wrong").exists()  # startup stopped before the runtime wrote anything


# ---------------------------------------------------------------------------
# M4 #2: only the runtime builds the gate
# ---------------------------------------------------------------------------


def _callee(call: ast.Call) -> str:
    func = call.func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def _gate_call_scopes(node: ast.AST, scope: tuple[str, ...] = ()) -> Iterator[str]:
    """The enclosing scope of every ``CommandPolicyGate(...)`` call under ``node``: ``Class.method``, ``<module>`` at top level."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Call) and _callee(child) == "CommandPolicyGate":
            yield ".".join(scope) or "<module>"
        named = isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        yield from _gate_call_scopes(child, (*scope, child.name) if named else scope)  # type: ignore[attr-defined]


def _gate_calls(root: Path) -> tuple[list[str], list[tuple[str, str]]]:
    """``(parsed, calls)`` for every ``*.py`` under ``root``.

    ``parsed`` is each relative posix path whose text names the gate (no other file can call it); ``calls`` is each call
    as ``(relative path, enclosing scope)``.
    """
    parsed: list[str] = []
    calls: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8-sig")
        if "CommandPolicyGate" not in text:
            continue
        relative = path.relative_to(root).as_posix()
        parsed.append(relative)
        calls.extend((relative, scope) for scope in _gate_call_scopes(ast.parse(text, filename=str(path))))
    return parsed, calls


def test_only_the_runtime_builds_the_gate(tmp_path: Path) -> None:
    """Exactly one call of ``CommandPolicyGate`` exists under ``src/probos``, in ``ProbOSRuntime.__init__``.

    The scan is AST-based, so a docstring, a string, an annotation, an ``isinstance`` check, an import or a near-miss
    name is not a call, and it is not vacuous: a scratch tree shows each way of building the gate flagged.
    """
    scratch = tmp_path / "scratch"
    files = {
        "runtime.py": "class ProbOSRuntime:\n    def __init__(self, cfg):\n        self.gate = CommandPolicyGate(cfg)\n",
        "extra/by_name.py": "def build(cfg):\n    return CommandPolicyGate(cfg)\n",
        "extra/by_attribute.py": "import probos.execution.command_gate as gate\nGATE = gate.CommandPolicyGate(None)\n",
        "extra/in_a_method.py": "class Factory:\n    async def make(self, cfg):\n        return CommandPolicyGate(cfg)\n",
        "extra/near_misses.py": '"""A docstring: CommandPolicyGate(cfg) is built by the runtime."""\n'
        "from x import CommandPolicyGate\nNAME = 'CommandPolicyGate(cfg)'\n"
        "def accepts(gate: CommandPolicyGate | None) -> bool:\n    return isinstance(gate, CommandPolicyGate)\n"
        "OTHER = CommandPolicyGateFactory(None)\n",
        "extra/unrelated.py": "VALUE = 1\n",
    }
    for relative, text in files.items():
        target = scratch / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    parsed, calls = _gate_calls(scratch)
    assert calls == [
        ("extra/by_attribute.py", "<module>"),
        ("extra/by_name.py", "build"),
        ("extra/in_a_method.py", "Factory.make"),
        ("runtime.py", "ProbOSRuntime.__init__"),
    ]
    assert "extra/near_misses.py" in parsed  # premise: the file of near misses was read, and nothing in it was flagged
    assert "extra/unrelated.py" not in parsed  # it names nothing: not parsed

    parsed, calls = _gate_calls(_SRC_PROBOS)
    # premise: the scan reached the tree: the gate's own module, and the places that hold the gate without building it
    assert {"execution/command_gate.py", "runtime.py", "agents/shell_command.py", "agents/red_team.py"} <= set(parsed)
    assert calls == [("runtime.py", "ProbOSRuntime.__init__")]


# ---------------------------------------------------------------------------
# M4 #3: create_pool hands the gate to shell members
# ---------------------------------------------------------------------------


async def test_create_pool_hands_the_gate_to_shell_members(shell_runs: list[str]) -> None:
    """``ProbOSRuntime.create_pool`` hands the runtime's gate to every shell member, and to nothing else.

    Each pool is made through the public factory with NO explicit gate: it comes from the runtime. The checks are
    behavioural: a command goes through a member's ``_run_command`` and the shell stand-in either sees it or does not.
    The members checked are the initial ones, the replacement of a recycled one and one added later (the pool keeps its
    spawn kwargs). A caller's own gate wins, a pool of another type is handed none, and a runtime double without the
    attribute builds members that run everything.
    """
    gate = _gate(_no_curl())  # the runtime's: forbids curl, runs the rest
    other = _gate(_rule("no-wget", ["wget"], "forbid"))  # a caller's: forbids wget, runs the rest
    runtime = _FakePoolRuntime(gate)
    bare = _FakePoolRuntime()
    try:
        pool = await ProbOSRuntime.create_pool(runtime, "shell", "shell_command", target_size=2)
        await ProbOSRuntime.create_pool(
            runtime, "shell-caller", "shell_command", target_size=1, command_policy_gate=other,
        )
        await ProbOSRuntime.create_pool(runtime, "recorder-pool", "recorder", target_size=2, recorded_marker=True)
        await ProbOSRuntime.create_pool(bare, "shell-bare", "shell_command", target_size=2)

        # premise: the pools came up with the members this test counts on
        initial = runtime.registry.get_by_pool("shell")
        assert (len(initial), len(runtime.registry.get_by_pool("shell-caller"))) == (2, 1)
        assert not hasattr(bare, "command_policy_gate")

        async def runtime_gate_holds(member: ShellCommandAgent) -> None:
            ran_curl, refused = await _through_the_shell_agent(member, "curl example.com", shell_runs)
            assert ran_curl is False
            assert refused["success"] is False
            assert "no-curl" in refused["error"] and "use http_fetch" in refused["error"]
            ran_wget, allowed = await _through_the_shell_agent(member, "wget example.com", shell_runs)  # the control
            assert (ran_wget, allowed["success"]) == (True, True)

        # every initial member judges against the runtime's gate
        for member in initial:
            await runtime_gate_holds(member)

        # the replacement of a recycled member does too
        victim = initial[0]
        await pool._recycle_registered_agent_inner(victim.id)
        replacement = runtime.registry.get(victim.id)
        assert replacement is not None and replacement is not victim  # premise: a different object under the same id
        await runtime_gate_holds(replacement)

        # so does a member added later
        new_id = await pool.add_agent()
        added = runtime.registry.get(new_id) if new_id else None
        assert added is not None and added.id == new_id  # premise: add_agent returned an id the registry knows
        await runtime_gate_holds(added)

        # the caller's own gate wins: its member runs what the runtime's gate forbids, and refuses what that one runs
        caller_member = runtime.registry.get_by_pool("shell-caller")[0]
        ran_curl, result = await _through_the_shell_agent(caller_member, "curl example.com", shell_runs)
        assert (ran_curl, result["success"]) == (True, True)
        ran_wget, result = await _through_the_shell_agent(caller_member, "wget example.com", shell_runs)
        assert ran_wget is False and "no-wget" in result["error"]

        # a pool of another type is not handed the gate; premise: its members recorded the kwargs the pool handed over
        recorded = [member.received_kwarg_names for member in runtime.registry.get_by_pool("recorder-pool")]
        assert (len(recorded), all("recorded_marker" in names for names in recorded)) == (2, True)
        assert [names for names in recorded if "command_policy_gate" in names] == []

        # a runtime double with no gate builds members that run everything, the forbidden command included
        for member in bare.registry.get_by_pool("shell-bare"):
            ran_curl, result = await _through_the_shell_agent(member, "curl example.com", shell_runs)
            assert (ran_curl, result["success"]) == (True, True)
    finally:
        await _stop_pools(runtime, bare)


# ---------------------------------------------------------------------------
# M4 #4: _spawn_red_team hands the gate
# ---------------------------------------------------------------------------


async def _verdict(agent: RedTeamAgent, command: str, *, claimed_success: bool) -> Any:
    """The red team's verdict on a claimed run of ``command`` (a claimed success carries exit code 0 and no output)."""
    intent = IntentMessage(intent="run_command", params={"command": command})
    claimed = IntentResult(
        intent_id=intent.id, agent_id="shell-1", success=claimed_success,
        result={"exit_code": 0, "stdout": ""} if claimed_success else None, confidence=0.8,
    )
    return await agent._verify_run_command("shell-1", intent, claimed, intent.params)


async def test_spawn_red_team_hands_the_gate(reruns: list[str]) -> None:
    """``ProbOSRuntime._spawn_red_team`` hands the runtime's gate to the agent it builds: no re-run of a forbidden command.

    A forbidden command is not re-run: the verdict alone answers the claim (consistent with a claimed failure, a
    discrepancy for a claimed success). An allowed command is re-run once, and an agent spawned by a runtime double with
    no gate re-runs the forbidden command too.
    """
    gated = _FakeRuntimeSelf(SystemConfig(), gate=_gate(_no_curl()))
    ungated = _FakeRuntimeSelf(SystemConfig())
    try:
        await ProbOSRuntime._spawn_red_team(gated, 1)
        await ProbOSRuntime._spawn_red_team(ungated, 1)
        assert (len(gated.red_team_agents), len(ungated.red_team_agents)) == (1, 1)  # premise
        agent, plain = gated.red_team_agents[0], ungated.red_team_agents[0]

        claimed_failure = await _verdict(agent, "curl example.com", claimed_success=False)
        assert (claimed_failure.verified, claimed_failure.discrepancy) == (True, "")
        claimed_success = await _verdict(agent, "curl example.com", claimed_success=True)
        assert claimed_success.verified is False
        assert "command policy" in claimed_success.discrepancy and "forbid" in claimed_success.discrepancy
        assert reruns == []  # a forbidden command was never re-run

        control = await _verdict(agent, "wget example.com", claimed_success=True)  # the control: the policy lets it run
        assert control.verified is True
        assert reruns == ["wget example.com"]

        reruns.clear()
        ungated_verdict = await _verdict(plain, "curl example.com", claimed_success=True)  # no gate: re-run as before
        assert ungated_verdict.verified is True
        assert reruns == ["curl example.com"]
    finally:
        for runtime_self in (gated, ungated):
            for red_team in runtime_self.red_team_agents:
                await red_team.stop()


# ---------------------------------------------------------------------------
# M4 #5: the native SWE tools registration hands the gate
# ---------------------------------------------------------------------------


async def test_native_swe_registration_hands_the_gate(spawns: list[tuple[tuple[Any, ...], dict[str, Any]]]) -> None:
    """The registered ``run_command`` tool refuses what the gate forbids, whether registered directly or by the startup wiring.

    ``register_native_swe_tools(..., command_policy_gate=gate)`` and ``_wire_native_swe_harness`` (which passes
    ``runtime.command_policy_gate``) each end in a tool that refuses a forbidden command without spawning anything and
    spawns an allowed one; a registration given no gate (and a runtime stand-in with no gate attribute) spawns both.
    """
    gate = _gate(_no_curl())

    async def refuses_curl_and_runs_wget(tool: Any) -> None:
        spawns.clear()
        refused = await tool.invoke({"command": "curl example.com"})
        assert refused.output is None and "no-curl" in refused.error and "use http_fetch" in refused.error
        assert refused.metadata["command_policy"]["decision"] == "forbid"
        assert spawns == []
        allowed = await tool.invoke({"command": "wget example.com"})  # the control: the policy lets it run
        assert allowed.error is None and allowed.output["exit_code"] == 0
        assert allowed.metadata["command_policy"]["decision"] == "allow"
        assert [args for args, _ in spawns] == [("wget example.com",)]

    registered = ToolRegistry()
    register_native_swe_tools(registered, SimpleNamespace(), command_policy_gate=gate)
    direct = registered.get_tool("run_command")
    assert direct is not None  # premise: the tool was registered
    await refuses_curl_and_runs_wget(direct)

    config = SystemConfig()
    wired_registry = ToolRegistry()
    stand_in = SimpleNamespace(tool_registry=wired_registry, config=config, command_policy_gate=gate)
    # No llm_client: the wiring registers the tools, then returns False before building a harness.
    assert _wire_native_swe_harness(runtime=stand_in, config=config, tool_executor=_FakeExecutor()) is False
    wired = wired_registry.get_tool("run_command")
    assert wired is not None  # premise: the wiring registered the tool
    await refuses_curl_and_runs_wget(wired)

    # the controls: with no gate handed over, the same command is spawned and the result carries no policy record
    spawns.clear()
    ungated_registry = ToolRegistry()
    register_native_swe_tools(ungated_registry, SimpleNamespace())
    ungated_direct = await ungated_registry.get_tool("run_command").invoke({"command": "curl example.com"})
    assert ungated_direct.error is None and ungated_direct.metadata == {}
    bare_registry = ToolRegistry()
    bare_stand_in = SimpleNamespace(tool_registry=bare_registry, config=config)
    assert _wire_native_swe_harness(runtime=bare_stand_in, config=config, tool_executor=_FakeExecutor()) is False
    ungated_wired = await bare_registry.get_tool("run_command").invoke({"command": "curl example.com"})
    assert ungated_wired.error is None and ungated_wired.metadata == {}
    assert [args for args, _ in spawns] == [("curl example.com",), ("curl example.com",)]


# ---------------------------------------------------------------------------
# M4 #6: probos doctor reports the policy
# ---------------------------------------------------------------------------


def _registered_check() -> DoctorCheck:
    return next(check for check in iter_checks() if check.name == "command_policy")


def _doctor_ctx(config: Any, tmp_path: Path) -> DoctorContext:
    return DoctorContext(config=config, home_dir=tmp_path, data_dir=tmp_path, config_path=None)


_DOCTOR_CASES: list[Any] = [
    pytest.param(lambda: SystemConfig(), CheckOutcome.OK, "none configured", id="none"),
    pytest.param(
        lambda: _config_with(_no_curl(), _push_waits()), CheckOutcome.OK, "2 rules, self-test passed", id="passing",
    ),
    pytest.param(
        lambda: _config_with(_no_curl(match=["wget example.com"]), _push_waits()),
        CheckOutcome.FAIL, "self-test failed", id="failing",
    ),
    pytest.param(lambda: None, CheckOutcome.WARN, "not checked", id="no_config"),
    pytest.param(
        lambda: SimpleNamespace(execution=SimpleNamespace(command_policy={"rules": []})),
        CheckOutcome.FAIL, "could not be checked", id="wrong_type",
    ),
]


@pytest.mark.parametrize(("make_config", "outcome", "fragment"), _DOCTOR_CASES)
async def test_doctor_reports_the_policy(
    make_config: Callable[[], Any], outcome: CheckOutcome, fragment: str, tmp_path: Path,
) -> None:
    """The registered ``command_policy`` check: OK without or with a passing policy, FAIL for a wrong example or a
    policy that is not one, WARN when the configuration did not load; the remediation is there exactly when it is not OK."""
    result = await _registered_check().run(_doctor_ctx(make_config(), tmp_path))
    assert result.outcome is outcome
    assert result.message.startswith("Command policy:")
    assert fragment in result.message
    assert bool(result.remediation) is (outcome is not CheckOutcome.OK)


async def test_doctor_passing_report_names_the_count_the_dialects_and_the_digest(tmp_path: Path) -> None:
    config = _config_with(_no_curl(), _push_waits())
    result = await _registered_check().run(_doctor_ctx(config, tmp_path))

    assert result.outcome is CheckOutcome.OK
    assert "2 rules" in result.message
    assert f"under {', '.join(_HOST_DIALECTS)}" in result.message
    assert f"({4 * len(_HOST_DIALECTS)} examples)" in result.message  # four examples per dialect
    assert f"digest {policy_digest(config.execution.command_policy)}" in result.message
    assert result.remediation == ""


async def test_doctor_failing_report_names_the_rule_the_example_and_what_to_correct(tmp_path: Path) -> None:
    passing = await _registered_check().run(_doctor_ctx(_config_with(_no_curl(), _push_waits()), tmp_path))
    assert passing.outcome is CheckOutcome.OK  # the neighbour: the same two rules with their examples correct

    result = await _registered_check().run(
        _doctor_ctx(_config_with(_no_curl(match=["wget example.com"]), _push_waits()), tmp_path),
    )

    assert result.outcome is CheckOutcome.FAIL
    assert "'no-curl'" in result.message and "'wget example.com'" in result.message
    assert "'push-waits'" not in result.message  # the rule whose examples hold is not named
    assert f"under {_HOST_DIALECTS[0]}:" in result.message
    assert "execution.command_policy" in result.remediation
    assert ", ".join(_HOST_DIALECTS) in result.remediation


def test_the_doctor_check_is_registered_once_and_keeps_the_ad1327_order() -> None:
    names = [check.name for check in iter_checks()]

    assert names.count("command_policy") == 1
    assert names[names.index("extras") + 1] == "verifier_independence"  # the neighbours this check must not displace
    registered = _registered_check()
    assert isinstance(registered, command_policy_check._CommandPolicyCheck)
    assert isinstance(registered, DoctorCheck)


# ---------------------------------------------------------------------------
# M4 #7: the starter policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dialect", ["posix", "cmd", "powershell"])
def test_starter_policy_holds_under_every_dialect(dialect: str) -> None:
    """The starter's own examples hold, a download is forbidden naming ``http_fetch`` and a push escalates, in each dialect."""
    config = CommandPolicyConfig.model_validate(_starter_raw())
    assert [rule.name for rule in config.rules] == ["shell-download", "git-push"]  # premise: the rules this test judges
    examples = sum(len(rule.match) + len(rule.not_match) for rule in config.rules)
    assert examples == 9

    report = self_test(config, dialect=dialect)  # type: ignore[arg-type]
    assert [failure.message for failure in report.failures] == []
    assert report.examples_checked == examples

    download = evaluate_command(config, "curl -sS example.com", dialect=dialect)  # type: ignore[arg-type]
    assert download.decision == "forbid"
    assert [(match.rule, match.alternative) for match in download.governing] == [
        ("shell-download", "use http_fetch, the ship's governed fetch"),
    ]
    push = evaluate_command(config, "git push origin main", dialect=dialect)  # type: ignore[arg-type]
    assert push.decision == "escalate"
    assert [match.rule for match in push.governing] == ["git-push"]
    for neighbour in ("git status", "git pull", "curlie example.com"):  # the controls: the policy lets these run
        assert evaluate_command(config, neighbour, dialect=dialect).decision == "allow", neighbour  # type: ignore[arg-type]


def test_the_starter_policy_is_opt_in() -> None:
    """Nothing adopts the starter by default: no rules in the model's default, the system config or the shipped file."""
    assert ExecutionConfig().command_policy.rules == ()
    assert SystemConfig().execution.command_policy.rules == ()
    assert load_config(_REPO / "config" / "system.yaml").execution.command_policy.rules == ()
    # the control: the starter is a policy, so "no rules" above is the default and not an empty file
    assert len(CommandPolicyConfig.model_validate(_starter_raw()).rules) == 2


async def test_starter_policy_reaches_run_command_through_the_runtime_gate(
    tmp_path: Path, spawns: list[tuple[tuple[Any, ...], dict[str, Any]]],
) -> None:
    """The starter file, copied under ``execution:`` of a config file, governs a ``run_command`` through the whole chain.

    The chain: ``starter.yaml`` -> ``load_config`` -> ``ProbOSRuntime`` (which builds its gate, self-tested under this
    host's dialects) -> ``_wire_native_swe_harness`` (which hands that gate to the tool) -> the registered tool's refusal;
    and the same config -> the doctor's report, which carries the same digest the runtime's gate holds.
    """
    system_yaml = tmp_path / "system.yaml"
    system_yaml.write_text(
        yaml.safe_dump({"execution": {"command_policy": _starter_raw()}}), encoding="utf-8",
    )
    config = load_config(system_yaml)
    assert len(config.execution.command_policy.rules) == 2  # premise: the policy came through the file

    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "runtime" / "data")
    gate = runtime.command_policy_gate
    assert gate.configured is True
    assert gate.digest == policy_digest(config.execution.command_policy)
    assert [(report.dialect, report.passed) for report in gate.self_test_reports] == [(d, True) for d in _HOST_DIALECTS]

    registry = ToolRegistry()
    stand_in = SimpleNamespace(tool_registry=registry, config=config, command_policy_gate=gate)
    assert _wire_native_swe_harness(runtime=stand_in, config=config, tool_executor=_FakeExecutor()) is False
    tool = registry.get_tool("run_command")
    assert tool is not None  # premise: the wiring registered the tool

    download = await tool.invoke({"command": "curl -sS example.com"})
    assert download.output is None
    assert "shell-download" in download.error and "use http_fetch" in download.error
    assert download.metadata["command_policy"]["decision"] == "forbid"
    push = await tool.invoke({"command": "git push origin main"})
    assert push.output is None and "git-push" in push.error and "approval" in push.error
    assert push.metadata["command_policy"]["decision"] == "escalate"
    assert spawns == []  # neither was started

    allowed = await tool.invoke({"command": "git status"})  # the control: a command no starter rule names runs
    assert allowed.error is None and allowed.output["exit_code"] == 0
    assert [args for args, _ in spawns] == [("git status",)]
    assert allowed.metadata["command_policy"]["decision"] == "allow"
    assert allowed.metadata["command_policy"]["policy_digest"] == gate.digest

    report = await _registered_check().run(_doctor_ctx(config, tmp_path))
    assert report.outcome is CheckOutcome.OK
    assert f"digest {gate.digest}" in report.message


# ---------------------------------------------------------------------------
# B33 (S2a repair r2, S1 r3 H5): a rule pinned only to the other platform's path stops startup and fails the doctor
# ---------------------------------------------------------------------------

_POSIX_GIT = "/usr/bin/git"
_WINDOWS_GIT = "C:\\Git\\cmd\\git.exe"


@pytest.mark.parametrize(
    ("platform", "pin", "other_pin", "failing_dialects"),
    [
        pytest.param("win32", _POSIX_GIT, _WINDOWS_GIT, ["cmd", "powershell"], id="win32"),
        pytest.param("linux", _WINDOWS_GIT, _POSIX_GIT, ["posix"], id="linux"),
    ],
)
def test_r2_a_rule_pinned_only_to_the_other_platform_stops_startup_and_fails_the_doctor(
    platform: str, pin: str, other_pin: str, failing_dialects: list[str],
) -> None:
    """B33. A rule whose only pinned path is the other platform's can never allow its program, so the gate refuses to
    build under the platform, the doctor report fails once per serving dialect, and (host half) a real runtime does not
    start and its doctor check fails with the remediation naming the pinned path. A rule listing both paths builds."""
    rule = _rule("pinned-git", ["git"], "allow", host_executable=[pin])
    policy = _config_with(rule).execution.command_policy

    with pytest.raises(CommandPolicySelfTestError) as raised:
        CommandPolicyGate(policy, platform=platform, is_file=lambda path: False)
    assert "'pinned-git'" in str(raised.value)
    assert f"host_executable {pin}" in str(raised.value)

    report = describe_command_policy(policy, platform=platform)
    assert report.passed is False
    failures = [(r.dialect, failure) for r in report.reports for failure in r.failures]
    assert [dialect for dialect, _ in failures] == failing_dialects
    assert all(failure.expectation == "host_executable" for _, failure in failures)

    # control: the same rule pinned to both platforms' paths builds, and its report passes
    both = _config_with(_rule("pinned-git", ["git"], "allow", host_executable=[pin, other_pin])).execution.command_policy
    CommandPolicyGate(both, platform=platform, is_file=lambda path: False)
    assert describe_command_policy(both, platform=platform).passed is True


async def test_r2_a_rule_pinned_only_to_the_other_platform_stops_the_real_runtime_and_fails_the_doctor(
    tmp_path: Path,
) -> None:
    """B33, host half: the pin for the platform this host is not, at the real runtime and the registered doctor check."""
    pin = _POSIX_GIT if sys.platform == "win32" else _WINDOWS_GIT
    config = _config_with(_rule("pinned-git", ["git"], "allow", host_executable=[pin]))

    with pytest.raises(CommandPolicySelfTestError):
        ProbOSRuntime(config=config, data_dir=tmp_path / "pinned" / "data")
    assert not (tmp_path / "pinned").exists()  # startup stopped before the runtime wrote anything

    result = await _registered_check().run(_doctor_ctx(config, tmp_path))
    assert result.outcome is CheckOutcome.FAIL
    assert "host_executable" in result.message
    assert "pattern, example or host_executable path" in result.remediation
    assert ", ".join(_HOST_DIALECTS) in result.remediation
