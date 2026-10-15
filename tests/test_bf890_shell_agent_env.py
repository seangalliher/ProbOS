"""BF-890 (#1529): the shell agent, the red team's re-run and the two wiring sites start commands from an allowlist.

Before the fix ``ShellCommandAgent`` and the red team's re-run of its command inherited the runtime's whole process
environment, so ``echo``, ``set`` or ``env`` in a command carried a provider key into an agent's context. Both now
start from ``probos.execution.command_env`` (``build_command_env``) plus the names an operator declares in
``execution.command_env_passthrough``; ``create_agent_fleet`` injects those names into the shell pool, a real
``ResourcePool`` hands them to each member it makes (initial, replacement, added), and
``ProbOSRuntime._spawn_red_team`` injects them into the red team.

Every test plants a credential-shaped variable and a plain one with ``monkeypatch.setenv`` and drives a real child
process. Each asserts its own premise first -- a child that INHERITS this process's environment shows the plant, so
the probe can see what it looks for -- and carries a control that shows what changes the outcome.

SECRETS RULE: a child's output, an ``IntentResult`` and ``os.environ`` never appear in an ``assert``, an assert
message, a ``print`` or a log. Each test derives first (the NAMES of the plants whose value is in the output, an exit
code, a boolean) and asserts on the derived value. A premise child prints one plant, never the environment.

On Windows the agent and the red team's re-run use PowerShell (``echo $env:VAR``); on POSIX, /bin/sh (``echo $VAR``).
Each platform's variant is a fixture parameter, and the other platform's variant is skipped with a reason.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any

import pytest

from probos.agents.red_team import RedTeamAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.config import ExecutionConfig, PoolConfig, SystemConfig
from probos.execution.command_env import SANDBOX_ENV_PASSTHROUGH
from probos.runtime import ProbOSRuntime
from probos.startup.agent_fleet import create_agent_fleet
from probos.substrate.pool import ResourcePool
from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.types import IntentMessage, IntentResult

SECRET_NAME = "BF890_PROBE_API_KEY"  # credential-shaped: never reaches a command, declared or not
PLAIN_NAME = "BF890_PROBE_PLAIN"  # plain: reaches a command only when the operator declares it
PLANTS: dict[str, str] = {
    SECRET_NAME: "bf890-planted-secret-7d1",
    PLAIN_NAME: "bf890-plain-value-3c2",
}
#: A command that ends with ``echo RAN_MARK`` proves the shell ran it to its end.
RAN_MARK = "bf890-ran-ok"
#: red_team.py gives a re-run this long; running out of it surfaces as one of these two discrepancies
#: (see _rerun_verdict).
RERUN_WAIT_S = 5.0
RERUN_TIMED_OUT = ("Verification command timed out", "Verification error: ")


# ---------------------------------------------------------------------------
# Plants, shell syntax and the child-process helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def plants(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plant the two variables in this process's environment, for one test."""
    for name, value in PLANTS.items():
        monkeypatch.setenv(name, value)


@dataclass(frozen=True)
class _Shell:
    """How one platform's shell reads a variable and lists the environment; the agent and the re-run use it."""

    echo_template: str
    listing: str
    one_name_listing_template: str

    def echo(self, name: str) -> str:
        return self.echo_template.format(name=name)

    def one_name_listing(self, name: str) -> str:
        """The listing narrowed to one variable: the most a premise child may print."""
        return self.one_name_listing_template.format(name=name)


_POWERSHELL = _Shell("echo $env:{name}", "Get-ChildItem env:", "Get-ChildItem env:{name}")
_POSIX_SH = _Shell("echo ${name}", "env", "env | grep '^{name}='")


@pytest.fixture(
    params=[
        pytest.param(
            _POWERSHELL,
            id="powershell",
            marks=pytest.mark.skipif(
                sys.platform != "win32",
                reason="PowerShell variant: the agent and the re-run use PowerShell on Windows only",
            ),
        ),
        pytest.param(
            _POSIX_SH,
            id="sh",
            marks=pytest.mark.skipif(
                sys.platform == "win32",
                reason="POSIX /bin/sh variant: the agent and the re-run use /bin/sh on POSIX hosts only",
            ),
        ),
    ]
)
def shell(request: pytest.FixtureRequest) -> _Shell:
    return request.param


def _marked(command: str) -> str:
    """*command* followed by a statement that prints RAN_MARK (``;`` separates statements in PowerShell and sh)."""
    return f"{command}; echo {RAN_MARK}"


def _planted(text: str, *, by_name: bool = False) -> list[str]:
    """The NAMES of the plants *text* carries: by value, and by name too when *by_name* (a listing prints names)."""
    lowered = text.lower()
    return [
        name for name, value in PLANTS.items()
        if value in text or (by_name and name.lower() in lowered)
    ]


def _inheriting_child_stdout(command: str) -> str:
    """stdout of *command* in a child that INHERITS this process's environment, the plants included.

    Premise only: callers pass a command that prints one plant, never one that lists the environment.
    """
    if sys.platform == "win32":
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            env=None, stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
        )
    else:
        proc = subprocess.run(
            command, shell=True,
            env=None, stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
        )
    return proc.stdout.decode("utf-8", errors="replace")


async def _run_in_shell_agent(agent: ShellCommandAgent, command: str) -> tuple[int | None, str]:
    """Run *command* through the agent's intent path: ``(exit code, stdout)``, or ``(None, "")`` if it did not run."""
    result = await agent.handle_intent(IntentMessage(intent="run_command", params={"command": command}))
    if result is None or not result.success or not isinstance(result.result, dict):
        return None, ""
    return result.result.get("exit_code"), str(result.result.get("stdout", ""))


async def _rerun_verdict(agent: RedTeamAgent, command: str, claimed_stdout: str) -> tuple[bool, str]:
    """The red team's verdict on a claimed run of *command*, as ``(verified, discrepancy)``.

    The claim is exit code 0 and stdout *claimed_stdout*. Skips the test when the re-run ran out of the red team's own
    5 s: that is a loaded host, not a verdict, and no mutant makes the re-run slower (one that leaks the environment
    gives a stdout mismatch). The brief names "Verification command timed out", but that string is the losing side of
    a race: ``asyncio.wait_for`` starts its 5 s clock before ``communicate(timeout=5)`` does, so a real timeout
    surfaces as ``"Verification error: "`` (a bare ``TimeoutError``; measured). Both count, and only after the wait
    was really spent, so an instant error never skips.
    """
    intent = IntentMessage(intent="run_command", params={"command": command})
    claimed = IntentResult(
        intent_id=intent.id, agent_id="shell-1", success=True,
        result={"exit_code": 0, "stdout": claimed_stdout}, confidence=0.8,
    )
    started = time.monotonic()
    verdict = await agent._verify_run_command("shell-1", intent, claimed, intent.params)
    waited = time.monotonic() - started
    if verdict.discrepancy in RERUN_TIMED_OUT and waited >= RERUN_WAIT_S - 0.5:
        pytest.skip(
            f"the red team's re-run ran out of its {RERUN_WAIT_S:.0f} s wait "
            f"(discrepancy {verdict.discrepancy!r}): environmental under load, not a verdict"
        )
    return verdict.verified, verdict.discrepancy


# ---------------------------------------------------------------------------
# Premise: why the Windows names are in the allowlist
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="premise about PowerShell command resolution: Windows only")
@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed on this host")
def test_premise_sandbox_set_alone_does_not_resolve_git_in_powershell() -> None:
    """With only the run_python sandbox's base names PowerShell cannot run ``git``: the Windows extras are needed."""
    sandbox_only = {name: os.environ[name] for name in SANDBOX_ENV_PASSTHROUGH if name in os.environ}

    def run(command: str) -> int:
        return subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            env=sandbox_only, stdin=subprocess.DEVNULL, capture_output=True, timeout=60,
        ).returncode

    git_exit_code = run("git --version")
    # Control: PowerShell itself starts and runs a cmdlet in this environment, so the failure above is about ``git``.
    control_exit_code = run("Write-Output ok")
    assert (git_exit_code != 0, control_exit_code) == (True, 0)


# ---------------------------------------------------------------------------
# ShellCommandAgent
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("plants")
async def test_shell_agent_echo_does_not_reveal_a_planted_secret(shell: _Shell) -> None:
    """Kills M17 (``env = None``): the agent's child must not inherit the runtime's environment."""
    command = _marked(shell.echo(SECRET_NAME))

    # Premise: a child that inherits this process's environment prints the secret, so this probe can see it.
    premise_out = _inheriting_child_stdout(command)
    premise_seen = _planted(premise_out)
    assert premise_seen == [SECRET_NAME]

    exit_code, out = await _run_in_shell_agent(ShellCommandAgent(pool="shell"), command)
    finished, leaked = RAN_MARK in out, _planted(out)
    assert (exit_code, finished, leaked) == (0, True, [])


@pytest.mark.usefixtures("plants")
async def test_shell_agent_listing_omits_planted_names(shell: _Shell) -> None:
    """Kills M17: a listing of the agent's child's environment carries neither plant, by name or by value."""
    # Premise: a listing in a child that inherits this process's environment carries the plant. Narrowed to one name,
    # so nothing else is printed.
    premise_out = _inheriting_child_stdout(shell.one_name_listing(SECRET_NAME))
    premise_seen = _planted(premise_out, by_name=True)
    assert premise_seen == [SECRET_NAME]

    exit_code, out = await _run_in_shell_agent(ShellCommandAgent(pool="shell"), shell.listing)
    # Control: it listed an environment (the allowlisted PATH is in it), so an empty result is not a failed run.
    lists_the_allowlist = "path" in out.lower()
    leaked = _planted(out, by_name=True)
    assert (exit_code, lists_the_allowlist, leaked) == (0, True, [])


@pytest.mark.parametrize(
    ("command", "expected_stdout_start", "agent_rewrites_it"),
    [
        pytest.param(
            "git --version", "git version", False, id="git",
            marks=pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed on this host"),
        ),
        pytest.param('python -c "print(42)"', "42", True, id="interpreter"),
    ],
)
async def test_shell_agent_runs_git_and_the_interpreter(
    command: str, expected_stdout_start: str, agent_rewrites_it: bool,
) -> None:
    """The allowlist is enough for the tools a command reaches for: ``git``, and ``python`` as ``sys.executable``."""
    # Premise: the agent runs the interpreter that is running this test, never a bare ``python`` (under a narrow
    # environment the Python install manager's shim would install an interpreter into the working directory); git is
    # run as written. Asserted before anything is run.
    as_run = ShellCommandAgent._rewrite_python_interpreter(command)
    premise = (as_run != command, sys.executable in as_run)
    assert premise == (agent_rewrites_it, agent_rewrites_it)

    exit_code, out = await _run_in_shell_agent(ShellCommandAgent(pool="shell"), command)
    produced = out.strip().startswith(expected_stdout_start)
    assert (exit_code, produced) == (0, True)


@pytest.mark.usefixtures("plants")
async def test_shell_agent_declared_plain_name_reaches_the_child(shell: _Shell) -> None:
    """Kills M18 (injected names dropped in ``__init__``): a declared plain name reaches the child, and only then."""
    command = _marked(shell.echo(PLAIN_NAME))

    # Premise: a child that inherits this process's environment prints the plain value.
    premise_out = _inheriting_child_stdout(command)
    premise_seen = _planted(premise_out)
    assert premise_seen == [PLAIN_NAME]

    # Control: undeclared, the plain name is not in the allowlist, so the value does not reach the child.
    exit_code, out = await _run_in_shell_agent(ShellCommandAgent(pool="shell"), command)
    finished, seen = RAN_MARK in out, _planted(out)
    assert (exit_code, finished, seen) == (0, True, [])

    # Declared through the spawn kwarg the pool injects: the value reaches the child.
    declared = ShellCommandAgent(pool="shell", command_env_passthrough=(PLAIN_NAME,))
    exit_code, out = await _run_in_shell_agent(declared, command)
    finished, seen = RAN_MARK in out, _planted(out)
    assert (exit_code, finished, seen) == (0, True, [PLAIN_NAME])


# ---------------------------------------------------------------------------
# The red team's re-run
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("plants")
async def test_red_team_verifies_against_the_allowlisted_env(shell: _Shell) -> None:
    """Kills M19, M20, M21: the re-run's child gets the allowlisted environment, so it sees what the shell agent saw."""
    command = shell.echo(PLAIN_NAME)

    # Premise: a child that inherits this process's environment prints the plain value, so a re-run that inherited
    # it would not match the claim below.
    premise_out = _inheriting_child_stdout(command)
    premise_seen = _planted(premise_out)
    assert premise_seen == [PLAIN_NAME]

    # The shell agent ran this under the allowlist and printed nothing: the re-run must agree.
    agent = RedTeamAgent(pool="red_team")
    verified, discrepancy = await _rerun_verdict(agent, command, claimed_stdout="")
    assert verified is True, f"the re-run did not match the claim: {discrepancy!r}"

    # Control: the verdict can fail -- a claim that carries the value does not match the allowlisted re-run.
    verified, discrepancy = await _rerun_verdict(agent, command, claimed_stdout=PLANTS[PLAIN_NAME])
    assert (verified, discrepancy) == (False, "Stdout mismatch")


@pytest.mark.usefixtures("plants")
async def test_red_team_declared_name_reaches_the_rerun(shell: _Shell) -> None:
    """Kills M22 (the injected names dropped in ``__init__``): a declared plain name reaches the re-run's child."""
    command = shell.echo(PLAIN_NAME)
    value = PLANTS[PLAIN_NAME]

    # Premise: a child that inherits this process's environment prints the plain value.
    premise_out = _inheriting_child_stdout(command)
    premise_seen = _planted(premise_out)
    assert premise_seen == [PLAIN_NAME]

    # Control: undeclared, the re-run prints nothing, so a claim that carries the value is a stdout mismatch.
    verified, discrepancy = await _rerun_verdict(RedTeamAgent(pool="red_team"), command, claimed_stdout=value)
    assert (verified, discrepancy) == (False, "Stdout mismatch")

    # Declared: the same claim now matches what the re-run printed.
    declared = RedTeamAgent(pool="red_team", command_env_passthrough=(PLAIN_NAME,))
    verified, discrepancy = await _rerun_verdict(declared, command, claimed_stdout=value)
    assert verified is True, f"the declared name did not reach the re-run: {discrepancy!r}"


# ---------------------------------------------------------------------------
# The two wiring sites
# ---------------------------------------------------------------------------


class _StopAfterShell(Exception):
    """Raised by the fake ``create_pool`` at the shell pool, which ends ``create_agent_fleet`` there."""


class _FakeCreatePool:
    """Records ``(pool, agent_type, kwargs)`` for each pool ``create_agent_fleet`` asks for; stops at "shell"."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def __call__(self, pool: str, agent_type: str, **kwargs: Any) -> None:
        self.calls.append((pool, agent_type, kwargs))
        if pool == "shell":
            raise _StopAfterShell


async def test_agent_fleet_injects_declared_names_into_the_shell_pool_only() -> None:
    """Kills M29 (``{}`` for the shell pool's spawn kwargs): the declared names reach the shell pool, no other."""
    config = SystemConfig(execution=ExecutionConfig(command_env_passthrough=[PLAIN_NAME]))
    create_pool = _FakeCreatePool()

    with pytest.raises(_StopAfterShell):
        await create_agent_fleet(
            config=config, pools={}, llm_client=None, decomposer=None, strategy_advisor=None, runtime=None,
            create_pool_fn=create_pool, spawn_red_team_fn=None, collect_intent_descriptors_fn=None,
        )

    *earlier, (stop_pool, stop_agent_type, shell_kwargs) = create_pool.calls
    # Premise: the walk ended at the shell pool after other pools, so "no earlier pool got the names" is not vacuous.
    assert (stop_pool, stop_agent_type, len(earlier) > 0) == ("shell", "shell_command", True)

    assert shell_kwargs.get("command_env_passthrough") == (PLAIN_NAME,)
    earlier_pools_with_names = [pool for pool, _, kwargs in earlier if "command_env_passthrough" in kwargs]
    assert earlier_pools_with_names == []


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
    """The attributes ``ProbOSRuntime._spawn_red_team`` reads, around a real ``SystemConfig``."""

    def __init__(self, config: SystemConfig) -> None:
        self.config = config
        self.registry = _FakeAgentRegistry()
        self.capability_registry = _FakeCapabilityRegistry()
        self.gossip = _FakeGossip()
        self.trust_network = _FakeTrustNetwork()
        self.event_log = _FakeEventLog()
        self.red_team_agents: list[RedTeamAgent] = []


@pytest.mark.usefixtures("plants")
async def test_spawn_red_team_injects_declared_names(shell: _Shell) -> None:
    """Kills M30 (``()`` for the spawned agent's names): config -> ``_spawn_red_team`` -> agent -> re-run's child."""
    command = shell.echo(PLAIN_NAME)
    value = PLANTS[PLAIN_NAME]

    # Premise: a child that inherits this process's environment prints the plain value.
    premise_out = _inheriting_child_stdout(command)
    premise_seen = _planted(premise_out)
    assert premise_seen == [PLAIN_NAME]

    declaring = _FakeRuntimeSelf(SystemConfig(execution=ExecutionConfig(command_env_passthrough=[PLAIN_NAME])))
    declaring_nothing = _FakeRuntimeSelf(SystemConfig())
    try:
        await ProbOSRuntime._spawn_red_team(declaring, 1)
        await ProbOSRuntime._spawn_red_team(declaring_nothing, 1)
        spawned = (len(declaring.red_team_agents), len(declaring_nothing.red_team_agents))
        assert spawned == (1, 1)

        # Control: spawned from a config that declares nothing, the agent's re-run prints nothing, so a claim that
        # carries the value is a stdout mismatch.
        agent = declaring_nothing.red_team_agents[0]
        verified, discrepancy = await _rerun_verdict(agent, command, claimed_stdout=value)
        assert (verified, discrepancy) == (False, "Stdout mismatch")

        # Spawned from a config that declares the name: the same claim matches what the re-run printed.
        verified, discrepancy = await _rerun_verdict(declaring.red_team_agents[0], command, claimed_stdout=value)
        assert verified is True, f"the declared name did not reach the spawned agent's re-run: {discrepancy!r}"
    finally:
        for runtime_self in (declaring, declaring_nothing):
            for agent in runtime_self.red_team_agents:
                await agent.stop()


# ---------------------------------------------------------------------------
# The real pool seam
# ---------------------------------------------------------------------------


def _shell_pool(name: str, **spawn_kwargs: Any) -> tuple[ResourcePool, AgentRegistry]:
    """A real pool of two ``ShellCommandAgent`` members, not yet started, with its own registry and spawner."""
    registry = AgentRegistry()
    spawner = AgentSpawner(registry)
    spawner.register_template("shell_command", ShellCommandAgent)
    pool = ResourcePool(
        name=name,
        agent_type="shell_command",
        spawner=spawner,
        registry=registry,
        config=PoolConfig(default_pool_size=2, min_pool_size=1, max_pool_size=3),
        target_size=2,
        **spawn_kwargs,
    )
    return pool, registry


async def _probe_member(member: Any, command: str) -> tuple[int | None, bool, list[str]]:
    """Run *command* through a pool member's intent path: ``(exit code, ran to its end, plant names it printed)``.

    Asserts the premise first: a child that inherits this process's environment prints the plain value, so this probe
    can see what it looks for.
    """
    premise_out = _inheriting_child_stdout(command)
    premise_seen = _planted(premise_out)
    assert premise_seen == [PLAIN_NAME]

    exit_code, out = await _run_in_shell_agent(member, command)
    return exit_code, RAN_MARK in out, _planted(out)


@pytest.mark.usefixtures("plants")
async def test_real_pool_hands_declared_names_to_members_replacements_and_additions(shell: _Shell) -> None:
    """A real ``ResourcePool`` hands its spawn kwarg ``command_env_passthrough`` to every member it makes.

    The fleet test reaches only a fake ``create_pool``, so nothing else proves that a real member -- or the replacement
    of a recycled one, or a member added later -- gets the declared names. This checks behaviour, not attributes: each
    member's command goes through ``handle_intent`` and the plain value is looked for in what its child printed. A
    second pool made without the kwarg is the control.

    Kills the mutant in ``src/probos/substrate/pool.py`` that replaces the line
    ``        self._spawn_kwargs = spawn_kwargs`` with ``        self._spawn_kwargs = {}``.
    Reasoned, not run (no campaign in the repo): the pool then builds every member -- initial (``_start_inner``),
    replacement (``_recycle_registered_agent_inner``) and added (``_add_agent_inner``) -- without the names, which is
    exactly what the control pool's member shows below, so each of the three positive probes would see ``[]`` instead
    of ``[PLAIN_NAME]``.
    """
    command = _marked(shell.echo(PLAIN_NAME))
    declared_pool, declared_registry = _shell_pool("shell", command_env_passthrough=(PLAIN_NAME,))
    control_pool, control_registry = _shell_pool("shell-control")
    try:
        await declared_pool.start()
        await control_pool.start()

        # Premise: both pools came up with two members each.
        initial = declared_registry.get_by_pool("shell")
        control_members = control_registry.get_by_pool("shell-control")
        sizes = (len(initial), len(control_members))
        assert sizes == (2, 2)

        # An initial member carries the declared names.
        victim, kept = initial
        initial_probe = await _probe_member(kept, command)
        assert initial_probe == (0, True, [PLAIN_NAME])

        # The replacement of a recycled member does too.
        victim_id = victim.id
        await declared_pool._recycle_registered_agent_inner(victim_id)
        replacement = declared_registry.get(victim_id)
        # Premise: the recycle put a different object under the same id.
        swapped = replacement is not None and replacement is not victim and replacement.id == victim_id
        assert swapped
        replacement_probe = await _probe_member(replacement, command)
        assert replacement_probe == (0, True, [PLAIN_NAME])

        # So does a member added later.
        new_id = await declared_pool.add_agent()
        added = declared_registry.get(new_id) if new_id else None
        # Premise: add_agent returned an id, and the registry holds the member it names.
        registered = added is not None and added.id == new_id
        assert registered
        added_probe = await _probe_member(added, command)
        assert added_probe == (0, True, [PLAIN_NAME])

        # Control: a pool made without the kwarg builds members that print nothing.
        control_probe = await _probe_member(control_members[0], command)
        assert control_probe == (0, True, [])
    finally:
        try:
            await declared_pool.stop()
        finally:
            await control_pool.stop()
