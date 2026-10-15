"""BF-890 (#1529): the environment a real ``run_command`` child starts with.

Every test here starts a REAL child process through a REAL ``RunCommandTool``
(cmd.exe on Windows, /bin/sh on POSIX) after planting two variables of its own
in the process environment, then asks what the child can see:

* ``BF890_PROBE_API_KEY`` -- credential-shaped: never reaches a command.
* ``BF890_PROBE_PLAIN``   -- ordinary: reaches a command only when declared.

SECRETS RULE. The machine running these tests holds real secrets, and a defect
(or a mutant) can make a child inherit all of them. So nothing here prints a
child's output, the process environment or a ``ToolResult``, and no ``assert``
expression or message holds one. ``_Child`` keeps the text in ``repr=False``
fields and answers only derived questions (which planted NAMES printed, which
variable names a listing holds); a test derives first and asserts on the
derived value.

PREMISE FIRST. Every test proves, with a child that inherits this process's
environment, that its probe can see what the test then claims is hidden.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

import pytest

from probos.cognitive.swe_harness.tools import RunCommandTool, register_native_swe_tools
from probos.tools.protocol import Tool
from probos.tools.registry import ToolRegistry

SECRET_NAME = "BF890_PROBE_API_KEY"
SECRET_VALUE = "bf890-planted-secret-7d1"
PLAIN_NAME = "BF890_PROBE_PLAIN"
PLAIN_VALUE = "bf890-plain-value-3c2"
PLANTS: dict[str, str] = {SECRET_NAME: SECRET_VALUE, PLAIN_NAME: PLAIN_VALUE}
PLANT_NAMES: list[str] = list(PLANTS)

#: Printed ahead of an echoed variable: proves the echo ran even when the
#: variable expands to nothing, so "no value printed" is never a vacuous pass.
_ECHO_SENTINEL = "BF890-ECHO"
_FILE_MARKER = "bf890-file-marker-9e4"
_CHILD_TIMEOUT_SECONDS = 60.0
#: ``sys.executable``, quoted -- never a bare ``python`` (under a stripped Windows
#: environment the Python install manager's shim installs an interpreter into
#: the working directory).
_PYTHON = f'"{sys.executable}"'
_ON_WINDOWS = sys.platform == "win32"


def _same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(os.path.realpath(left)) == os.path.normcase(os.path.realpath(right))


def _sleeping_python(marker: Path) -> str:
    """A ``sys.executable`` child that sleeps about a second, then writes *marker* and exits."""
    code = f"import pathlib, time; time.sleep(1); pathlib.Path(r'{marker}').write_text('done')"
    return f'{_PYTHON} -c "{code}"'


async def _wait_out_the_orphan(marker: Path, *, seconds: float = 5.0) -> None:
    """Let the child a timed-out call left behind finish, while the event loop still runs.

    ``RunCommandTool`` kills the shell on a timeout, not the command under it, so
    the command keeps the output pipes open until it exits. Waiting for it here
    lets the pipes reach EOF and asyncio close the transport normally, instead of
    leaving it for a finalizer that runs after the loop is closed.
    """
    deadline = time.monotonic() + seconds
    while not marker.exists() and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.25)  # the loop now sees the pipes close and finishes the transport


@dataclass(frozen=True)
class _Child:
    """What one child process printed.

    The text fields are ``repr=False`` so a failing assertion can never print
    them; tests ask the derived questions below instead.
    """

    succeeded: bool
    exit_code: int | None  # None: no child result (the call was refused or timed out)
    stdout: str = field(repr=False)
    stderr: str = field(repr=False)
    error: str = field(repr=False)

    def says(self, text: str) -> bool:
        return text in self.stdout

    def failed_saying(self, text: str) -> bool:
        return text in self.error

    def ran_the_echo(self) -> bool:
        return self.succeeded and self.exit_code == 0 and _ECHO_SENTINEL in self.stdout

    def printed_plants(self) -> list[str]:
        """The NAMES of the planted variables whose VALUES this child printed."""
        printed = f"{self.stdout}\n{self.stderr}"
        return [name for name, value in PLANTS.items() if value in printed]

    def listed_names(self) -> frozenset[str]:
        """Upper-cased variable names in a ``set`` / ``env`` listing (Windows names are case-insensitive)."""
        names = (
            line.split("=", 1)[0].strip().upper()
            for line in self.stdout.splitlines()
            if "=" in line
        )
        return frozenset(name for name in names if name)

    def echoed(self, expected: str) -> bool:
        return self.stdout.strip() == expected.strip()

    def printed_directory(self, expected: Path) -> bool:
        printed = self.stdout.strip()
        return bool(printed) and _same_path(printed, expected)


def _inherit(command: str) -> _Child:
    """The premise probe: a shell child started with NO ``env`` argument, so it inherits ours."""
    done = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=_CHILD_TIMEOUT_SECONDS,
    )
    return _Child(
        succeeded=done.returncode == 0,
        exit_code=done.returncode,
        stdout=done.stdout.decode("utf-8", errors="replace"),
        stderr=done.stderr.decode("utf-8", errors="replace"),
        error="",
    )


async def _run(tool: Tool, command: str, **params: Any) -> _Child:
    """Invoke *tool* once and keep only a ``_Child`` -- never the ``ToolResult`` itself."""
    result = await tool.invoke({"command": command, "timeout": _CHILD_TIMEOUT_SECONDS, **params})
    output = result.output if isinstance(result.output, dict) else {}
    exit_code = output.get("exit_code")
    return _Child(
        succeeded=result.success,
        exit_code=exit_code if isinstance(exit_code, int) else None,
        stdout=str(output.get("stdout", "")),
        stderr=str(output.get("stderr", "")),
        error=result.error or "",
    )


class _FakeRuntime:
    """``RunCommandTool`` stores the runtime but never reads it on the command path."""


class _FakeExecutor:
    """Stands in for the ToolExecutor: ``_wire_native_swe_harness`` only calls ``add_pre_hook`` on it."""

    def __init__(self) -> None:
        self.pre_hooks: list[Any] = []

    def add_pre_hook(self, hook: Any) -> None:
        self.pre_hooks.append(hook)


def _wire(config: Any) -> tuple[bool, Tool | None]:
    """Run the real ``_wire_native_swe_harness``; return its result and the ``run_command`` it registered."""
    from probos.startup.finalize import _wire_native_swe_harness

    registry = ToolRegistry()
    # No llm_client: the wiring registers the tools, then returns False before building a harness.
    runtime = SimpleNamespace(tool_registry=registry, config=config)
    wired = _wire_native_swe_harness(runtime=runtime, config=config, tool_executor=_FakeExecutor())
    return wired, registry.get_tool("run_command")


# --------------------------------------------------------------------------
# The two shells run_command can be under
# --------------------------------------------------------------------------


class _Shell(Protocol):
    def echo(self, *names: str) -> str: ...
    def echo_bare(self, name: str) -> str: ...
    def listing(self) -> str: ...
    def cwd(self) -> str: ...
    def read_file(self, path: Path) -> str: ...


class _CmdShell:
    """cmd.exe: what ``run_command`` runs its command under on Windows."""

    def echo(self, *names: str) -> str:
        return " ".join(["echo", _ECHO_SENTINEL, *(f"%{name}%" for name in names)])

    def echo_bare(self, name: str) -> str:
        return f"echo %{name}%"

    def listing(self) -> str:
        return "set"

    def cwd(self) -> str:
        return "cd"

    def read_file(self, path: Path) -> str:
        return f'type "{path}"'


class _PosixShell:
    """/bin/sh: what ``run_command`` runs its command under on POSIX."""

    def echo(self, *names: str) -> str:
        return " ".join(["echo", _ECHO_SENTINEL, *(f'"${name}"' for name in names)])

    def echo_bare(self, name: str) -> str:
        return f"printf '%s\\n' \"${name}\""

    def listing(self) -> str:
        return "env"

    def cwd(self) -> str:
        return "pwd"

    def read_file(self, path: Path) -> str:
        return f'cat "{path}"'


_SHELLS = [
    pytest.param(
        _CmdShell(),
        id="cmd",
        marks=pytest.mark.skipif(
            not _ON_WINDOWS, reason="cmd.exe variant: run_command runs commands under cmd.exe only on Windows",
        ),
    ),
    pytest.param(
        _PosixShell(),
        id="sh",
        marks=pytest.mark.skipif(
            _ON_WINDOWS, reason="/bin/sh variant: run_command runs commands under /bin/sh only on POSIX",
        ),
    ),
]


@pytest.fixture(params=_SHELLS)
def shell(request: pytest.FixtureRequest) -> _Shell:
    return request.param


@pytest.fixture(autouse=True)
def _plant_the_probe_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in PLANTS.items():
        monkeypatch.setenv(name, value)


# --------------------------------------------------------------------------
# The probe discriminates
# --------------------------------------------------------------------------


def test_premise_an_inheriting_shell_child_sees_the_plants(shell: _Shell) -> None:
    """A shell child started without ``env`` inherits both plants, so an echo CAN reveal them."""
    inherited = _inherit(shell.echo(*PLANT_NAMES))

    printed = inherited.printed_plants()
    assert printed == PLANT_NAMES


# --------------------------------------------------------------------------
# What the default environment hides, and keeps
# --------------------------------------------------------------------------


async def test_echo_does_not_reveal_a_planted_secret(shell: _Shell) -> None:
    """Contract mutant M14 (``env=None``): the child must not echo either planted value."""
    command = shell.echo(*PLANT_NAMES)
    inherited_printed = _inherit(command).printed_plants()
    assert inherited_printed == PLANT_NAMES, "premise: an inheriting child echoes both planted values"

    ran = await _run(RunCommandTool(_FakeRuntime()), command)

    echo_ran = ran.ran_the_echo()
    leaked = ran.printed_plants()
    assert echo_ran, "control: the echo must run in the child, or an empty result proves nothing"
    assert leaked == []


async def test_listing_omits_planted_names_and_keeps_path(shell: _Shell) -> None:
    """``set`` / ``env`` in the child lists neither plant, and still lists PATH."""
    for name in PLANT_NAMES:  # premise: one targeted echo per plant, never a listing of the real environment
        inherited_printed = _inherit(shell.echo(name)).printed_plants()
        assert inherited_printed == [name], "premise: an inheriting child holds this plant"

    listing = await _run(RunCommandTool(_FakeRuntime()), shell.listing())

    listing_ran = listing.succeeded and listing.exit_code == 0
    names = listing.listed_names()
    keeps_path = "PATH" in names
    listed_plants = [name for name in PLANT_NAMES if name in names]
    printed_values = listing.printed_plants()
    assert listing_ran, "control: the listing command must run in the child"
    assert keeps_path, "control: the allowlist keeps PATH, so the listing parse can see a name"
    assert listed_plants == []
    assert printed_values == []

    declared = await _run(
        RunCommandTool(_FakeRuntime(), command_env_passthrough=(PLAIN_NAME,)), shell.listing(),
    )
    declared_names = declared.listed_names()
    declared_plants = [name for name in PLANT_NAMES if name in declared_names]
    assert declared_plants == [PLAIN_NAME], "negative control: a declared plain name does show in the listing"


async def test_path_reaches_the_child(shell: _Shell) -> None:
    """PATH is on the allowlist: the child echoes exactly the PATH this process has."""
    expected = os.environ["PATH"]
    command = shell.echo_bare("PATH")
    inherited_echoes_path = _inherit(command).echoed(expected)
    if not inherited_echoes_path:
        pytest.skip(
            "the shell's own echo does not reproduce this machine's PATH (length or shell "
            "metacharacters), so the comparison cannot discriminate here"
        )

    ran = await _run(RunCommandTool(_FakeRuntime()), command)

    reached = ran.echoed(expected)
    assert reached


_ORDINARY_COMMANDS = [
    pytest.param(f"{_PYTHON} --version", "Python", id="python-version"),
    pytest.param(
        "git --version",
        "git version",
        id="git-version",
        marks=pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed on this machine"),
    ),
]


@pytest.mark.parametrize(("command", "banner"), _ORDINARY_COMMANDS)
async def test_ordinary_commands_still_run(command: str, banner: str) -> None:
    """Trimming the environment does not break the commands an engineer actually runs."""
    inherited = _inherit(command)
    inherited_ok = inherited.succeeded and inherited.says(banner)
    assert inherited_ok, "premise: the command itself is valid on this machine"

    ran = await _run(RunCommandTool(_FakeRuntime()), command)

    ran_ok = ran.succeeded and ran.exit_code == 0
    printed_banner = ran.says(banner)
    assert ran_ok
    assert printed_banner


# --------------------------------------------------------------------------
# Declared names
# --------------------------------------------------------------------------


async def test_declared_plain_name_reaches_the_child(shell: _Shell) -> None:
    """Contract mutant M16 (declared names dropped in ``__init__``): a declared plain name arrives."""
    command = shell.echo(*PLANT_NAMES)
    inherited_printed = _inherit(command).printed_plants()
    assert inherited_printed == PLANT_NAMES, "premise: an inheriting child echoes both planted values"

    undeclared = await _run(RunCommandTool(_FakeRuntime()), command)
    declared = await _run(RunCommandTool(_FakeRuntime(), command_env_passthrough=(PLAIN_NAME,)), command)

    undeclared_ran = undeclared.ran_the_echo()
    declared_ran = declared.ran_the_echo()
    undeclared_printed = undeclared.printed_plants()
    declared_printed = declared.printed_plants()
    assert undeclared_ran and declared_ran, "control: both echoes run in the child"
    assert undeclared_printed == [], "negative control: without a declaration the plain name is hidden too"
    assert declared_printed == [PLAIN_NAME], "the declared plain name arrives; the secret plant still does not"


async def test_declared_credential_name_does_not_reach_the_child(shell: _Shell) -> None:
    """Declaring a credential-shaped name does not pass it on, whatever the operator wrote."""
    command = shell.echo(*PLANT_NAMES)
    inherited_printed = _inherit(command).printed_plants()
    assert inherited_printed == PLANT_NAMES, "premise: an inheriting child echoes both planted values"

    declared_secret = await _run(
        RunCommandTool(_FakeRuntime(), command_env_passthrough=(SECRET_NAME,)), command,
    )

    secret_echo_ran = declared_secret.ran_the_echo()
    leaked = declared_secret.printed_plants()
    assert secret_echo_ran, "control: the echo must run in the child"
    assert leaked == []

    both = await _run(
        RunCommandTool(_FakeRuntime(), command_env_passthrough=(SECRET_NAME, PLAIN_NAME)), command,
    )
    both_printed = both.printed_plants()
    assert both_printed == [PLAIN_NAME], "negative control: the same declaration passes the plain name, not the secret"


async def test_a_model_cannot_declare_names_through_params() -> None:
    """``command_env_passthrough`` is an operator setting; a call carrying it as a parameter is refused."""
    tool = RunCommandTool(_FakeRuntime())
    command = f"{_PYTHON} --version"
    schema_declares_it = "command_env_passthrough" in tool.input_schema["properties"]
    assert not schema_declares_it, "premise: the schema the model is shown has no such parameter"

    clean = await _run(tool, command)
    clean_ok = clean.succeeded and clean.exit_code == 0
    assert clean_ok, "negative control: the same command without the key runs"

    refused = await _run(tool, command, command_env_passthrough=[PLAIN_NAME])

    named_the_key = refused.failed_saying("command_env_passthrough")
    started_a_child = refused.exit_code is not None
    assert not refused.succeeded
    assert named_the_key
    assert not started_a_child


# --------------------------------------------------------------------------
# The declared names travel registration and startup wiring
# --------------------------------------------------------------------------


async def test_register_native_swe_tools_threads_declared_names(shell: _Shell) -> None:
    """Contract mutant M15 (``RunCommandTool(runtime)``): the registered tool carries the declared names."""
    command = shell.echo(*PLANT_NAMES)
    inherited_printed = _inherit(command).printed_plants()
    assert inherited_printed == PLANT_NAMES, "premise: an inheriting child echoes both planted values"

    declared_registry = ToolRegistry()
    register_native_swe_tools(declared_registry, _FakeRuntime(), command_env_passthrough=(PLAIN_NAME,))
    plain_registry = ToolRegistry()
    register_native_swe_tools(plain_registry, _FakeRuntime())
    declared_tool = declared_registry.get_tool("run_command")
    plain_tool = plain_registry.get_tool("run_command")
    assert declared_tool is not None and plain_tool is not None, "premise: run_command was registered"

    declared = await _run(declared_tool, command)
    undeclared = await _run(plain_tool, command)

    declared_printed = declared.printed_plants()
    undeclared_printed = undeclared.printed_plants()
    assert declared_printed == [PLAIN_NAME]
    assert undeclared_printed == [], "negative control: a registry given no names hides the plain name"


async def test_wire_native_swe_harness_reads_execution_config(shell: _Shell) -> None:
    """Contract mutant M31 (``command_env_passthrough=()``): startup wiring reads ``execution`` config."""
    from probos.config import SystemConfig

    command = shell.echo(*PLANT_NAMES)
    inherited_printed = _inherit(command).printed_plants()
    assert inherited_printed == PLANT_NAMES, "premise: an inheriting child echoes both planted values"

    declared_config = SystemConfig(execution={"command_env_passthrough": [PLAIN_NAME]})
    config_keeps_the_name = list(declared_config.execution.command_env_passthrough) == [PLAIN_NAME]
    assert config_keeps_the_name, "premise: the config accepts a plain name"

    wired, declared_tool = _wire(declared_config)
    _, default_tool = _wire(SystemConfig())
    assert wired is False, "premise: without an llm_client the wiring stops after registering the tools"
    assert declared_tool is not None and default_tool is not None, "premise: run_command was registered"

    declared = await _run(declared_tool, command)
    default = await _run(default_tool, command)

    declared_printed = declared.printed_plants()
    default_printed = default.printed_plants()
    assert declared_printed == [PLAIN_NAME]
    assert default_printed == [], "negative control: the default config declares no names"


# --------------------------------------------------------------------------
# What BF-890 did not change
# --------------------------------------------------------------------------


async def test_working_directory_and_timeout_unchanged(shell: _Shell, tmp_path: Path) -> None:
    """``working_directory`` still sets the child's cwd and ``timeout`` still ends a slow child."""
    process_cwd_is_tmp = _same_path(os.getcwd(), tmp_path)
    assert not process_cwd_is_tmp, "premise: this process is not already in tmp_path"
    tool = RunCommandTool(_FakeRuntime())

    default_dir = await _run(tool, shell.cwd())
    in_tmp = await _run(tool, shell.cwd(), working_directory=str(tmp_path))

    default_is_tmp = default_dir.printed_directory(tmp_path)
    in_tmp_is_tmp = in_tmp.printed_directory(tmp_path)
    assert not default_is_tmp, "negative control: without working_directory the child is not in tmp_path"
    assert in_tmp_is_tmp

    marker = tmp_path / "bf890_slept.marker"
    try:
        slow = await _run(tool, _sleeping_python(marker), timeout=0.5)

        timed_out = slow.failed_saying("timed out")
        assert not slow.succeeded
        assert timed_out
    finally:
        await _wait_out_the_orphan(marker)


async def test_not_a_file_boundary(shell: _Shell, tmp_path: Path) -> None:
    """The allowlist hides environment variables, not files: the child runs as the same user and can read them."""
    readable = tmp_path / "bf890_not_a_boundary.txt"
    readable.write_text(f"{_FILE_MARKER}\n", encoding="utf-8")
    command = shell.read_file(readable)
    inherited_read_it = _inherit(command).says(_FILE_MARKER)
    assert inherited_read_it, "premise: the read command works on this machine"

    ran = await _run(RunCommandTool(_FakeRuntime()), command)

    read_it = ran.succeeded and ran.says(_FILE_MARKER)
    assert read_it
