"""BF-890 (#1529): the shell agent, the red team's re-run and the two wiring sites start commands from an allowlist.

Before the fix ``ShellCommandAgent`` and the red team's re-run of its command inherited the runtime's whole process
environment, so ``echo``, ``set`` or ``env`` in a command carried a provider key into an agent's context. Both now
start from ``probos.execution.command_env`` (``build_command_env``) plus the names an operator declares in
``execution.command_env_passthrough``. ``ProbOSRuntime.create_pool`` injects those names into every shell pool (a
caller's own value wins, no other pool type gets them, and a config with no ``execution`` section declares nothing),
a real ``ResourcePool`` hands them to each member it makes (initial, replacement, added), and
``ProbOSRuntime._spawn_red_team`` injects them into the red team.

The tests plant a credential-shaped variable and a plain one with ``monkeypatch.setenv``. Every test that probes a
planted variable in a child asserts its inheriting-child premise first -- a child that INHERITS this process's
environment shows the plant, so the probe can see what it looks for -- and carries a control that shows what changes
the outcome. The two tests that plant nothing assert their own premises instead (the sandbox set cannot resolve
``git``; the agent runs ``sys.executable``, not a bare ``python``). The pure wiring checks (the recorder pool, which
only records the kwarg names its members were built with) start no child.

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
import types
from dataclasses import dataclass
from typing import Any

import pytest

from probos.agents.red_team import RedTeamAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.config import ExecutionConfig, PoolConfig, SystemConfig
from probos.execution.command_env import SANDBOX_ENV_PASSTHROUGH
from probos.runtime import ProbOSRuntime
from probos.substrate.agent import BaseAgent
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
# The red team's wiring site: ProbOSRuntime._spawn_red_team
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
# The shell pool's wiring site: ProbOSRuntime.create_pool, and the real pool behind it
# ---------------------------------------------------------------------------


class _RecorderAgent(BaseAgent):
    """A pool member that records the NAMES of the spawn kwargs its pool handed its constructor.

    It does nothing else: a pool of this type is how the tests see what ``create_pool`` hands a non-shell pool.
    """

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

    ``declared`` is ``execution.command_env_passthrough``. There is deliberately no ``onboarding`` attribute: the
    factory reads it with ``getattr``, and without it a pool is wired to nothing.
    """

    def __init__(self, declared: tuple[str, ...] = ()) -> None:
        self.config = SystemConfig(
            execution=ExecutionConfig(command_env_passthrough=list(declared)),
            pools=PoolConfig(default_pool_size=2, min_pool_size=1, max_pool_size=3),
        )
        self.pools: dict[str, ResourcePool] = {}
        self.registry = AgentRegistry()
        self.spawner = AgentSpawner(self.registry)
        self.spawner.register_template("shell_command", ShellCommandAgent)
        self.spawner.register_template("recorder", _RecorderAgent)
        self.acm = None
        self.ontology = None
        self.event_log = _FakeEventLog()


class _FakePoolRuntimeWithoutExecution(_FakePoolRuntime):
    """A fake runtime whose config has no ``execution`` section at all: a namespace that holds only ``pools``."""

    def __init__(self) -> None:
        super().__init__()
        self.config = types.SimpleNamespace(
            pools=PoolConfig(default_pool_size=2, min_pool_size=1, max_pool_size=3),
        )


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
    """``ProbOSRuntime.create_pool`` and a real ``ResourcePool`` hand the declared names to every shell member.

    Each pool is made through the public factory with NO explicit kwarg: the names come from the runtime's config.
    The checks are behavioural, not attribute reads: a member's command goes through ``handle_intent`` and the plain
    value is looked for in what its child printed. The members checked are an initial one, the replacement of a
    recycled one, and one added later; a pool made on a runtime whose config declares nothing is the control.

    Kills two mutants, both reasoned, not run (no campaign in the repo):

    * M29, ``src/probos/runtime.py``: the line
      ``        if agent_type == ShellCommandAgent.agent_type and "command_env_passthrough" not in spawn_kwargs:``
      replaced by ``        if False:``. The factory then never injects the names, so all three positive probes see
      ``[]`` instead of ``[PLAIN_NAME]``.
    * M32, ``src/probos/substrate/pool.py``: the line ``        self._spawn_kwargs = spawn_kwargs`` replaced by
      ``        self._spawn_kwargs = {}``. The factory injects the names but the pool drops them, so every member it
      builds -- initial (``_start_inner``), replacement (``_recycle_registered_agent_inner``) and added
      (``_add_agent_inner``) -- prints ``[]``, which is exactly what the control pool's member shows below.
    """
    command = _marked(shell.echo(PLAIN_NAME))
    declared_runtime = _FakePoolRuntime(declared=(PLAIN_NAME,))
    control_runtime = _FakePoolRuntime()
    try:
        # No explicit kwarg anywhere: the factory takes the names from the runtime's config.
        declared_pool = await ProbOSRuntime.create_pool(declared_runtime, "shell", "shell_command", target_size=2)
        await ProbOSRuntime.create_pool(control_runtime, "shell-control", "shell_command", target_size=2)

        # Premise: both pools came up with two members each.
        initial = declared_runtime.registry.get_by_pool("shell")
        control_members = control_runtime.registry.get_by_pool("shell-control")
        sizes = (len(initial), len(control_members))
        assert sizes == (2, 2)

        # An initial member carries the declared names.
        victim, kept = initial
        initial_probe = await _probe_member(kept, command)
        assert initial_probe == (0, True, [PLAIN_NAME])

        # The replacement of a recycled member does too.
        victim_id = victim.id
        await declared_pool._recycle_registered_agent_inner(victim_id)
        replacement = declared_runtime.registry.get(victim_id)
        # Premise: the recycle put a different object under the same id.
        swapped = replacement is not None and replacement is not victim and replacement.id == victim_id
        assert swapped
        replacement_probe = await _probe_member(replacement, command)
        assert replacement_probe == (0, True, [PLAIN_NAME])

        # So does a member added later.
        new_id = await declared_pool.add_agent()
        added = declared_runtime.registry.get(new_id) if new_id else None
        # Premise: add_agent returned an id, and the registry holds the member it names.
        registered = added is not None and added.id == new_id
        assert registered
        added_probe = await _probe_member(added, command)
        assert added_probe == (0, True, [PLAIN_NAME])

        # Control: a pool made on a runtime whose config declares nothing builds members that print nothing.
        control_probe = await _probe_member(control_members[0], command)
        assert control_probe == (0, True, [])
    finally:
        await _stop_pools(declared_runtime, control_runtime)


@pytest.mark.usefixtures("plants")
async def test_create_pool_hands_names_to_shell_pools_only_and_a_callers_value_wins(shell: _Shell) -> None:
    """``ProbOSRuntime.create_pool`` injects the declared names into shell pools only, and a caller's own value wins.

    Kills two mutants in ``src/probos/runtime.py``, both reasoned, not run (no campaign in the repo). Each replaces
    the line
    ``        if agent_type == ShellCommandAgent.agent_type and "command_env_passthrough" not in spawn_kwargs:``

    * M33, with ``        if "command_env_passthrough" not in spawn_kwargs:`` (the shell-type check dropped). The
      ``recorder`` pool's members would then be built with ``command_env_passthrough``, which their recorded kwarg
      names would show.
    * M34, with ``        if agent_type == ShellCommandAgent.agent_type:`` (the presence check dropped). The declared
      names would then overwrite the caller's explicit ``()``, so the caller's pool would print the plain value.

    The recorder pool starts no child. It is created with a marker kwarg (``recorded_marker``) that its members must
    record, which proves the recorder sees what the pool hands over, so "no ``command_env_passthrough``" means
    something.
    """
    command = _marked(shell.echo(PLAIN_NAME))
    runtime = _FakePoolRuntime(declared=(PLAIN_NAME,))
    try:
        await ProbOSRuntime.create_pool(runtime, "shell", "shell_command", target_size=1)
        await ProbOSRuntime.create_pool(
            runtime, "shell-caller", "shell_command", target_size=1, command_env_passthrough=(),
        )
        await ProbOSRuntime.create_pool(runtime, "recorder-pool", "recorder", target_size=2, recorded_marker=True)

        # Premise: a shell pool from this runtime, made without the kwarg, carries the declared names.
        shell_member = runtime.registry.get_by_pool("shell")[0]
        shell_probe = await _probe_member(shell_member, command)
        assert shell_probe == (0, True, [PLAIN_NAME])

        # A pool of another type is not handed them. Premise: it has members, and they recorded the kwargs the pool
        # handed over (the marker), so an absent ``command_env_passthrough`` is not just an empty record.
        recorded = [member.received_kwarg_names for member in runtime.registry.get_by_pool("recorder-pool")]
        saw_the_marker = (len(recorded) > 0, all("recorded_marker" in names for names in recorded))
        assert saw_the_marker == (True, True)
        handed_the_names = [names for names in recorded if "command_env_passthrough" in names]
        assert handed_the_names == []

        # The caller's own value wins: a pool created with an explicit ``()`` builds members that print nothing.
        caller_member = runtime.registry.get_by_pool("shell-caller")[0]
        caller_probe = await _probe_member(caller_member, command)
        assert caller_probe == (0, True, [])
    finally:
        await _stop_pools(runtime)


@pytest.mark.usefixtures("plants")
async def test_create_pool_tolerates_a_config_without_an_execution_section(shell: _Shell) -> None:
    """``ProbOSRuntime.create_pool`` works on a config with no ``execution`` section, and that config declares nothing.

    Review round 2 found that the factory read the config's ``execution`` section even when the caller supplied
    ``command_env_passthrough``, so a config without that section raised for a caller who needed nothing from it. Now a
    caller's value is respected without the ``execution`` section being read, and no section means no declared names.

    * (a) A shell pool made with an explicit ``command_env_passthrough=()`` on a config with no ``execution`` section
      is created and prints nothing. It pins the caller-supplied path: the ``execution`` section is not read.
    * (b) A shell pool made with no kwarg on that runtime is created and prints nothing. It kills two mutants in
      ``src/probos/runtime.py``, both reasoned, not run (no campaign in the repo): M35, the line
      ``            execution = getattr(self.config, "execution", None)`` replaced by
      ``            execution = self.config.execution`` (``AttributeError`` on the missing section), and M36, the line
      ``                getattr(execution, "command_env_passthrough", ()),`` replaced by
      ``                execution.command_env_passthrough,`` (``AttributeError`` on ``None``).
    * (c) Control: a normal runtime that declares the name, with a pool made the same way as (b), prints the plain
      value, so the probe can see it.
    """
    command = _marked(shell.echo(PLAIN_NAME))
    bare_runtime = _FakePoolRuntimeWithoutExecution()
    declared_runtime = _FakePoolRuntime(declared=(PLAIN_NAME,))
    try:
        # Premise: this runtime's config has no execution section at all.
        has_execution = hasattr(bare_runtime.config, "execution")
        assert not has_execution

        await ProbOSRuntime.create_pool(
            bare_runtime, "shell-explicit", "shell_command", target_size=2, command_env_passthrough=(),
        )
        await ProbOSRuntime.create_pool(bare_runtime, "shell-default", "shell_command", target_size=2)
        await ProbOSRuntime.create_pool(declared_runtime, "shell-control", "shell_command", target_size=2)

        explicit_members = bare_runtime.registry.get_by_pool("shell-explicit")
        default_members = bare_runtime.registry.get_by_pool("shell-default")
        control_members = declared_runtime.registry.get_by_pool("shell-control")
        # Premise: each pool was created, with two members.
        sizes = (len(explicit_members), len(default_members), len(control_members))
        assert sizes == (2, 2, 2)

        # (a) The caller's explicit value is respected: its member prints nothing.
        explicit_probe = await _probe_member(explicit_members[0], command)
        assert explicit_probe == (0, True, [])

        # (b) With no kwarg, a config with no execution section declares nothing: its member prints nothing.
        default_probe = await _probe_member(default_members[0], command)
        assert default_probe == (0, True, [])

        # (c) Control: the same call on a runtime that declares the name prints it, so the probe can see it.
        control_probe = await _probe_member(control_members[0], command)
        assert control_probe == (0, True, [PLAIN_NAME])
    finally:
        await _stop_pools(bare_runtime, declared_runtime)
