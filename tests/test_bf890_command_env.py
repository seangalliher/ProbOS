"""BF-890 (#1529): the command environment allowlist -- unit and one-owner tests.

Covers ``probos.execution.command_env`` (the one owner of the environment a
spawned command starts with), the literal twins of its credential rule in
``config_models/operations.py``, its relation to the ``run_python`` sandbox
constant in ``execution/isolation.py``, the spawn sites that must pass it, and
one crossing test: a changed shared set reaches a real ``run_command`` child and
a real ``ShellCommandAgent`` child.

Secrets rule for every test in this file: a child's raw output and the content
of ``os.environ`` are never placed in an ``assert`` expression, an assert
message, a print or a log. A test derives a list of NAMES (or a boolean) first
and asserts on that. Variables are planted with ``monkeypatch.setenv`` and every
planted value is synthetic.
"""

from __future__ import annotations

import ast
import importlib.util
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from probos.agents.shell_command import ShellCommandAgent
from probos.cognitive.swe_harness.tools import RunCommandTool
from probos.config_models import operations
from probos.credential_store import CredentialSpec, CredentialStore
from probos.execution import command_env, isolation
from probos.execution.command_env import (
    build_command_env,
    command_env_allowlist,
    env_name_refusal,
)
from probos.types import IntentMessage

# The expected sets are written out here on purpose: the tests compare the module
# against these literals, never against itself.
_SANDBOX_NAMES: tuple[str, ...] = (
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "TZ",
)
_WINDOWS_EXTRA_NAMES: tuple[str, ...] = (
    "COMSPEC", "PATHEXT", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "COMMONPROGRAMFILES", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS",
    "PSMODULEPATH", "USERNAME", "COMPUTERNAME",
)
_POSIX_EXTRA_NAMES: tuple[str, ...] = (
    "HOME", "USER", "LOGNAME", "SHELL", "TERM", "TMPDIR", "LC_CTYPE",
    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
)

# The two plants the BF-890 tests share: one credential-shaped, one plain.
_API_KEY_NAME = "BF890_PROBE_API_KEY"
_API_KEY_VALUE = "bf890-planted-secret-7d1"
_PLAIN_NAME = "BF890_PROBE_PLAIN"
_PLAIN_VALUE = "bf890-plain-value-3c2"
_PLANTS: dict[str, str] = {_API_KEY_NAME: _API_KEY_VALUE, _PLAIN_NAME: _PLAIN_VALUE}

# The real-child test: one name added to the shared set, one set but never added.
_SHARED_NAME = "BF890_SHARED_PROBE"
_SHARED_VALUE = "bf890-shared-value-5a8"
_CONTROL_NAME = "BF890_SHARED_CONTROL"
_CONTROL_VALUE = "bf890-control-value-9e4"

_COMMAND_ENV_LOGGER = "probos.execution.command_env"
_IS_WINDOWS = sys.platform == "win32"

_SPAWN_CALL_NAMES = frozenset({"Popen", "create_subprocess_shell", "create_subprocess_exec"})
# Module -> the least number of spawn calls it is known to hold (a search that
# finds fewer has not looked at the code the contract is about).
_MIN_SPAWN_CALLS: dict[str, int] = {
    "probos.cognitive.swe_harness.tools": 1,
    "probos.agents.shell_command": 2,
    "probos.agents.red_team": 2,
}


class _FakeRuntime:
    """RunCommandTool keeps its runtime but never reads it to run a shell command."""


class _RecordingCredentialStore(CredentialStore):
    """A real CredentialStore that remembers every spec registered on it, built-ins included."""

    def __init__(self) -> None:
        # Set before the base constructor: it registers the built-ins through register().
        self.recorded_specs: list[CredentialSpec] = []
        super().__init__()

    def register(self, spec: CredentialSpec) -> None:
        self.recorded_specs.append(spec)
        super().register(spec)


def _names_seen_in(text: str, values_by_name: dict[str, str]) -> list[str]:
    """The NAMES whose planted value occurs in *text* -- all a test may assert on."""
    return sorted(name for name, value in values_by_name.items() if value in text)


def _source_text(module_name: str) -> str:
    spec = importlib.util.find_spec(module_name)
    assert spec is not None and spec.origin is not None, f"{module_name} has no source file"
    return Path(spec.origin).read_text(encoding="utf-8")


def _spawn_calls_and_missing_env(source: str) -> tuple[int, list[int]]:
    """(spawn calls found in *source*, line numbers of those without a real ``env=``).

    A real ``env=`` is an ``env`` keyword whose value is not the constant None. A
    ``**kwargs`` splat cannot be proven to carry one, so it counts as missing.
    """
    spawns = 0
    missing: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            callee: str | None = func.attr
        elif isinstance(func, ast.Name):
            callee = func.id
        else:
            callee = None
        if callee not in _SPAWN_CALL_NAMES:
            continue
        spawns += 1
        env_values = [kw.value for kw in node.keywords if kw.arg == "env"]
        passes_env = bool(env_values) and not any(
            isinstance(value, ast.Constant) and value.value is None for value in env_values
        )
        if not passes_env:
            missing.append(node.lineno)
    return spawns, sorted(missing)


# --------------------------------------------------------------------------
# The shared sandbox set and the per-platform allowlists
# --------------------------------------------------------------------------


def test_sandbox_set_is_the_isolation_constant() -> None:
    owner = command_env.SANDBOX_ENV_PASSTHROUGH
    # Premise: the owner is the 8-name tuple the run_python sandbox has always used.
    assert isinstance(owner, tuple)
    assert len(owner) == 8
    assert owner == _SANDBOX_NAMES
    # One owner, not two equal copies.
    assert isolation._ENV_PASSTHROUGH is owner
    # Negative control: an equal copy is a different object, so the `is` above is a
    # real one-owner check and not an equality check in disguise.
    equal_copy = tuple(list(owner))
    assert equal_copy == owner
    assert equal_copy is not owner


def test_windows_allowlist_is_exact() -> None:
    expected = _SANDBOX_NAMES + _WINDOWS_EXTRA_NAMES
    # Premise: the literal written out in this file is 8 + 18 distinct names.
    assert len(_WINDOWS_EXTRA_NAMES) == 18
    assert len(set(expected)) == len(expected) == 26
    assert command_env_allowlist("win32") == expected
    # Negative control: the neighbouring platform is a different, smaller set.
    assert command_env_allowlist("linux") != expected


def test_posix_allowlist_is_exact() -> None:
    expected = _SANDBOX_NAMES + _POSIX_EXTRA_NAMES
    # Premise: the literal written out in this file is 8 + 10 distinct names.
    assert len(_POSIX_EXTRA_NAMES) == 10
    assert len(set(expected)) == len(expected) == 18
    assert command_env_allowlist("linux") == expected
    # Every platform that is not win32 takes the POSIX branch.
    assert command_env_allowlist("darwin") == expected
    # The two names the contract keeps out on purpose: they lead to agent sockets.
    deliberately_absent = [
        name for name in ("SSH_AUTH_SOCK", "XDG_RUNTIME_DIR") if name in command_env_allowlist("linux")
    ]
    assert deliberately_absent == []
    # Negative control: the Windows set is a different one.
    assert command_env_allowlist("win32") != expected


def test_allowlist_defaults_to_the_running_platform() -> None:
    running = "win32" if _IS_WINDOWS else "linux"
    other = "linux" if _IS_WINDOWS else "win32"
    # Premise: the two platforms really differ, so the comparison below can tell them apart.
    assert command_env_allowlist(running) != command_env_allowlist(other)
    assert command_env_allowlist() == command_env_allowlist(running)
    assert command_env_allowlist(None) == command_env_allowlist(running)
    assert command_env_allowlist() != command_env_allowlist(other)


def test_no_default_name_is_credential_shaped() -> None:
    windows = command_env_allowlist("win32")
    posix = command_env_allowlist("linux")
    # Premise: the one default that is not a plain variable name is present, and
    # that is the only reason it is left out of the check below.
    assert "PROGRAMFILES(X86)" in windows
    assert env_name_refusal("PROGRAMFILES(X86)") == "unknown_shape"
    # PATH and PATHEXT are named on purpose: both hold the letters PAT, which only
    # a whole-segment rule tolerates.
    assert "PATH" in windows
    assert "PATH" in posix
    assert "PATHEXT" in windows
    names = sorted((set(windows) | set(posix)) - {"PROGRAMFILES(X86)"})
    refused = {name: env_name_refusal(name) for name in names if env_name_refusal(name) is not None}
    assert refused == {}
    assert env_name_refusal("PATH") is None
    assert env_name_refusal("PATHEXT") is None
    # Negative control: the rule is live, so the empty result above is not vacuous.
    assert env_name_refusal("GH_TOKEN") == "credential_shaped"


# --------------------------------------------------------------------------
# The name rule
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "neighbour"),
    [
        pytest.param("OPENAI_API_KEY", "OPENAI_API_BASE", id="OPENAI_API_KEY"),
        pytest.param("ANTHROPIC_API_KEY", "ANTHROPIC_API_URL", id="ANTHROPIC_API_KEY"),
        pytest.param("LLM_API_KEY", "LLM_API_URL", id="LLM_API_KEY"),
        pytest.param("GH_TOKEN", "GH_HOST", id="GH_TOKEN"),
        pytest.param("GITHUB_TOKEN", "GITHUB_ORG", id="GITHUB_TOKEN"),
        pytest.param("gh_token", "gh_host", id="gh_token"),
        pytest.param("AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION", id="AWS_SECRET_ACCESS_KEY"),
        pytest.param("AWS_SESSION_TOKEN", "AWS_PROFILE", id="AWS_SESSION_TOKEN"),
        pytest.param("DB_PASSWORD", "DB_HOST", id="DB_PASSWORD"),
        pytest.param(
            "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT", id="GOOGLE_APPLICATION_CREDENTIALS",
        ),
        pytest.param("NPM_CONFIG__AUTH", "NPM_CONFIG__REGISTRY", id="NPM_CONFIG__AUTH"),
        pytest.param("GH_PAT", "GH_PATH", id="GH_PAT"),
        pytest.param("DB_PASS", "DB_PASSIVE", id="DB_PASS"),
        pytest.param("MYSQL_PWD", "MYSQL_HOME", id="MYSQL_PWD"),
        pytest.param("SENTRY_DSN", "SENTRY_ORG", id="SENTRY_DSN"),
        pytest.param("PROBOS_DATA_DIR", "PROBOSDATA_DIR", id="PROBOS_DATA_DIR"),
        pytest.param("PROBOS_FETCH_TOKEN", "PROBOSFETCH_URL", id="PROBOS_FETCH_TOKEN"),
    ],
)
def test_credential_shaped_names_are_refused(name: str, neighbour: str) -> None:
    # Premise: the pair is two different plain names, so the verdict below can only
    # come from the credential rule and not from the shape rule.
    assert name != neighbour
    assert env_name_refusal(name) == "credential_shaped"
    # Negative control: the accepted neighbour (same shape, no credential word).
    assert env_name_refusal(neighbour) is None


@pytest.mark.parametrize(
    "name",
    [
        "JAVA_HOME", "GOPATH", "NODE_ENV", "CARGO_HOME", "RUSTUP_HOME",
        "DOTNET_ROOT", "PYTHONPATH", "COMPASS_DIR", "MY_PATH_DIR",
    ],
)
def test_ordinary_names_are_not_refused(name: str) -> None:
    # Premise: the rule is live, so None below means "looked and found nothing".
    assert env_name_refusal("GH_TOKEN") == "credential_shaped"
    assert env_name_refusal(name) is None


@pytest.mark.parametrize(
    ("value", "neighbour"),
    [
        pytest.param("", "A", id="empty"),
        pytest.param("A B", "A_B", id="space"),
        pytest.param("X=Y", "X_Y", id="equals"),
        pytest.param("1ABC", "ABC1", id="leading_digit"),
        pytest.param("NAME;X", "NAME_X", id="semicolon"),
        pytest.param("PROGRAMFILES(X86)", "PROGRAMFILES_X86", id="parenthesis"),
        # The owner anchors the whole name: a trailing newline is not a plain name.
        pytest.param("NAME\n", "NAME", id="trailing_newline"),
        pytest.param(5, "FIVE", id="int"),
        pytest.param(None, "NONE", id="none"),
    ],
)
def test_unknown_shapes_are_refused(value: object, neighbour: str) -> None:
    # Premise: the neighbour is a str, so the accepted control below is a real name.
    assert isinstance(neighbour, str)
    assert env_name_refusal(value) == "unknown_shape"
    # Negative control: the accepted neighbour.
    assert env_name_refusal(neighbour) is None


def _credential_store_names_not_refused(store: _RecordingCredentialStore) -> dict[str, str | None]:
    names: list[str] = []
    for spec in store.recorded_specs:
        if spec.env_var is not None:
            names.append(spec.env_var)
        names.extend(spec.env_var_aliases)
    return {name: env_name_refusal(name) for name in names if env_name_refusal(name) != "credential_shaped"}


def test_every_credential_store_env_name_is_refused() -> None:
    store = _RecordingCredentialStore()
    recorded_env_names = sorted(
        {spec.env_var for spec in store.recorded_specs if spec.env_var}
        | {alias for spec in store.recorded_specs for alias in spec.env_var_aliases}
    )
    # Premise: the recorder saw the built-in specs, an alias among them.
    assert "GH_TOKEN" in recorded_env_names
    assert "GITHUB_TOKEN" in recorded_env_names
    assert "LLM_API_KEY" in recorded_env_names
    assert _credential_store_names_not_refused(store) == {}
    # Negative control: a spec carrying a plain env name IS reported by the same check.
    store.register(CredentialSpec(name="bf890_probe", env_var=_PLAIN_NAME))
    assert _credential_store_names_not_refused(store) == {_PLAIN_NAME: None}


# --------------------------------------------------------------------------
# build_command_env
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("plat", "expected_names"),
    [
        pytest.param("linux", ["HOME", "PATH"], id="linux"),
        pytest.param("win32", ["PATH"], id="win32"),
    ],
)
def test_build_env_copies_only_the_allowlist(plat: str, expected_names: list[str]) -> None:
    source = {
        "PATH": "/synthetic/bin",
        "HOME": "/synthetic/home",
        "BF890_PLANT": "bf890-plant-value",
    }
    # Premise: the plant is in the source and is not an allowlisted name here.
    assert "BF890_PLANT" in source
    assert "BF890_PLANT" not in command_env_allowlist(plat)
    env = build_command_env(source=source, platform=plat)
    assert "BF890_PLANT" not in env
    assert "PATH" in env
    # Negative control: HOME is in the source on both platforms but allowlisted only
    # on POSIX, so the result follows the allowlist and not the source.
    assert sorted(env) == expected_names
    assert env == {name: source[name] for name in expected_names}


def test_build_env_passes_a_declared_name_and_omits_an_unset_one() -> None:
    unset_name = "BF890_PROBE_UNSET"
    source = {"PATH": "/synthetic/bin", _PLAIN_NAME: _PLAIN_VALUE}
    # Premise: both declared names pass the rule, and only one of them is set.
    assert env_name_refusal(_PLAIN_NAME) is None
    assert env_name_refusal(unset_name) is None
    assert unset_name not in source
    env = build_command_env((_PLAIN_NAME, unset_name), source=source, platform="linux")
    assert env.get(_PLAIN_NAME) == _PLAIN_VALUE
    assert unset_name not in env
    # Negative control: undeclared, the very same set name is not passed.
    undeclared = build_command_env((), source=source, platform="linux")
    assert _PLAIN_NAME not in undeclared


def test_build_env_refuses_a_declared_credential_name_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    source = {"PATH": "/synthetic/bin", _API_KEY_NAME: _API_KEY_VALUE, _PLAIN_NAME: _PLAIN_VALUE}
    # Premise: the credential-shaped name is set in the source and the rule refuses it.
    assert _API_KEY_NAME in source
    assert env_name_refusal(_API_KEY_NAME) == "credential_shaped"
    with caplog.at_level(logging.WARNING, logger=_COMMAND_ENV_LOGGER):
        env = build_command_env((_API_KEY_NAME,), source=source, platform="linux")
    warnings = [
        record for record in caplog.records
        if record.name == _COMMAND_ENV_LOGGER and record.levelno == logging.WARNING
    ]
    assert _API_KEY_NAME not in env
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    names_in_message = [name for name in (_API_KEY_NAME, _PLAIN_NAME) if name in message]
    assert names_in_message == [_API_KEY_NAME]
    assert "credential_shaped" in message
    value_in_message = _API_KEY_VALUE in message
    assert value_in_message is False
    # Negative control: the accepted neighbour is passed and warns about nothing.
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_COMMAND_ENV_LOGGER):
        neighbour_env = build_command_env((_PLAIN_NAME,), source=source, platform="linux")
    assert neighbour_env.get(_PLAIN_NAME) == _PLAIN_VALUE
    assert [record for record in caplog.records if record.levelno >= logging.WARNING] == []


def test_build_env_refuses_a_declared_unknown_shape_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    bad_name = "BF890 PROBE"
    source = {"PATH": "/synthetic/bin", bad_name: "synthetic-value", _PLAIN_NAME: _PLAIN_VALUE}
    # Premise: the odd name is set in the source and the rule refuses it as a shape.
    assert bad_name in source
    assert env_name_refusal(bad_name) == "unknown_shape"
    # The refused name comes first: the accepted one after it must still be passed.
    with caplog.at_level(logging.WARNING, logger=_COMMAND_ENV_LOGGER):
        env = build_command_env((bad_name, _PLAIN_NAME), source=source, platform="linux")
    warnings = [
        record for record in caplog.records
        if record.name == _COMMAND_ENV_LOGGER and record.levelno == logging.WARNING
    ]
    assert bad_name not in env
    assert env.get(_PLAIN_NAME) == _PLAIN_VALUE
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "unknown_shape" in message
    assert bad_name in message


def test_build_env_defaults_to_os_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PLAIN_NAME, _PLAIN_VALUE)
    monkeypatch.setenv(_API_KEY_NAME, _API_KEY_VALUE)
    # Premise (derived, never the environment itself): both plants reached this
    # process's environment and PATH is there to be copied.
    planted = sorted(name for name, value in _PLANTS.items() if os.environ.get(name) == value)
    assert planted == sorted(_PLANTS)
    path_is_set = "PATH" in os.environ
    assert path_is_set is True
    env = build_command_env((_PLAIN_NAME, _API_KEY_NAME))
    carried = sorted(name for name, value in _PLANTS.items() if env.get(name) == value)
    assert carried == [_PLAIN_NAME]
    path_copied = env.get("PATH") == os.environ.get("PATH")
    assert path_copied is True
    # Nothing but the allowlist and the one accepted declared name came across.
    unexpected_names = sorted(set(env) - set(command_env_allowlist()) - {_PLAIN_NAME})
    assert unexpected_names == []
    # Negative control: undeclared, the same plain plant stays behind.
    undeclared = build_command_env()
    carried_undeclared = sorted(name for name, value in _PLANTS.items() if undeclared.get(name) == value)
    assert carried_undeclared == []


# --------------------------------------------------------------------------
# One owner
# --------------------------------------------------------------------------


def test_config_twins_equal_the_owner() -> None:
    # Premise: the owner holds real values, and the word the twin must not lose is there.
    assert command_env.CREDENTIAL_NAME_WORDS
    assert command_env.CREDENTIAL_NAME_SEGMENTS
    assert command_env.RUNTIME_NAME_PREFIX
    assert command_env.ENV_NAME_SHAPE_PATTERN
    assert "TOKEN" in command_env.CREDENTIAL_NAME_WORDS
    pairs = {
        "words": (operations._CREDENTIAL_ENV_NAME_WORDS, command_env.CREDENTIAL_NAME_WORDS),
        "segments": (operations._CREDENTIAL_ENV_NAME_SEGMENTS, command_env.CREDENTIAL_NAME_SEGMENTS),
        "prefix": (operations._RUNTIME_ENV_NAME_PREFIX, command_env.RUNTIME_NAME_PREFIX),
        "shape": (operations._ENV_NAME_SHAPE_PATTERN, command_env.ENV_NAME_SHAPE_PATTERN),
    }
    differing = [
        label for label, (twin, owner) in pairs.items()
        if twin != owner or type(twin) is not type(owner)
    ]
    assert differing == []


def test_isolation_does_not_read_the_operator_extension() -> None:
    isolation_source = _source_text("probos.execution.isolation")
    # Premise: this is the sandbox module (it names its own constant) ...
    assert "_ENV_PASSTHROUGH" in isolation_source
    # ... and the search can find the operator extension where it is consumed.
    assert "command_env_passthrough" in _source_text("probos.cognitive.swe_harness.tools")
    assert "command_env_passthrough" not in isolation_source


def test_every_command_spawn_in_the_three_files_passes_an_env() -> None:
    found: dict[str, int] = {}
    missing_env: list[str] = []
    for module_name in _MIN_SPAWN_CALLS:
        spawns, missing = _spawn_calls_and_missing_env(_source_text(module_name))
        found[module_name] = spawns
        missing_env.extend(f"{module_name}:{line}" for line in missing)
    # Premise: the search reached the spawn calls it is about (at least 1, 2 and 2).
    short = {name: found[name] for name in _MIN_SPAWN_CALLS if found[name] < _MIN_SPAWN_CALLS[name]}
    assert short == {}
    assert missing_env == []
    # Negative control: the same detector flags each way a spawn can lose its env,
    # and accepts the shapes the three files use.
    assert _spawn_calls_and_missing_env("import subprocess\nsubprocess.Popen(['x'])\n") == (1, [2])
    assert _spawn_calls_and_missing_env("import subprocess\nsubprocess.Popen(['x'], env=None)\n") == (1, [2])
    assert _spawn_calls_and_missing_env("import subprocess\nsubprocess.Popen(['x'], **opts)\n") == (1, [2])
    assert _spawn_calls_and_missing_env("import asyncio\nasyncio.create_subprocess_shell('x')\n") == (1, [2])
    assert _spawn_calls_and_missing_env("import subprocess\nsubprocess.Popen(['x'], env=env)\n") == (1, [])
    assert _spawn_calls_and_missing_env("import asyncio\nasyncio.create_subprocess_shell('x', env=f())\n") == (1, [])


# --------------------------------------------------------------------------
# A changed shared set reaches both shell paths (real children)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    [
        pytest.param(
            "windows",
            marks=pytest.mark.skipif(
                not _IS_WINDOWS,
                reason="cmd.exe (%VAR%) and PowerShell ($env:VAR) echo syntax exist only on Windows",
            ),
        ),
        pytest.param(
            "posix",
            marks=pytest.mark.skipif(
                _IS_WINDOWS,
                reason="the /bin/sh ($VAR) variant needs a POSIX host; this host is Windows",
            ),
        ),
    ],
)
async def test_a_changed_shared_set_reaches_both_shell_paths(
    monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    if variant == "windows":
        # RunCommandTool runs under cmd.exe, ShellCommandAgent under PowerShell.
        tool_command = f"echo %{_SHARED_NAME}% %{_CONTROL_NAME}%"
        agent_command = f"echo $env:{_SHARED_NAME} $env:{_CONTROL_NAME}"
    else:
        tool_command = f"echo ${_SHARED_NAME} ${_CONTROL_NAME}"
        agent_command = tool_command
    plants = {_SHARED_NAME: _SHARED_VALUE, _CONTROL_NAME: _CONTROL_VALUE}

    # Premise (before the change): neither probe is allowlisted yet.
    assert _SHARED_NAME not in command_env_allowlist()
    assert _CONTROL_NAME not in command_env_allowlist()
    monkeypatch.setattr(
        command_env, "SANDBOX_ENV_PASSTHROUGH", command_env.SANDBOX_ENV_PASSTHROUGH + (_SHARED_NAME,),
    )
    monkeypatch.setenv(_SHARED_NAME, _SHARED_VALUE)
    monkeypatch.setenv(_CONTROL_NAME, _CONTROL_VALUE)
    # Premise (after the change, derived): the owner's allowlist now holds the shared
    # probe and not the control, and both are set in this process's environment.
    assert _SHARED_NAME in command_env_allowlist()
    assert _CONTROL_NAME not in command_env_allowlist()
    planted = sorted(name for name, value in plants.items() if os.environ.get(name) == value)
    assert planted == sorted(plants)
    # Premise (an inheriting child): a child that INHERITS this process's environment sees
    # BOTH planted values. Without it, the control's absence below could mean only that the
    # probe cannot see what it says is hidden. No env argument: inheriting is the point.
    # Only the derived NAMES are asserted on, never the child's output.
    if variant == "windows":
        inheriting_runs: dict[str, tuple[str | list[str], bool]] = {
            "cmd.exe": (tool_command, True),
            "PowerShell": (["powershell", "-NoProfile", "-Command", agent_command], False),
        }
    else:
        inheriting_runs = {"sh": (tool_command, True)}
    inheriting_seen: dict[str, list[str]] = {}
    for label, (inheriting_command, uses_shell) in inheriting_runs.items():
        inheriting_child = subprocess.run(
            inheriting_command, shell=uses_shell, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=60,
        )
        inheriting_seen[label] = _names_seen_in(
            inheriting_child.stdout.decode("utf-8", errors="replace"), plants,
        )
    assert inheriting_seen == {label: sorted(plants) for label in inheriting_runs}

    tool_result = await RunCommandTool(_FakeRuntime()).invoke({"command": tool_command, "timeout": 30})
    assert tool_result.success is True, f"run_command did not run: {tool_result.error}"
    tool_exit_code = tool_result.output["exit_code"]
    assert tool_exit_code == 0
    # The shared probe reached the child; the control, set in the parent too, did not.
    tool_seen = _names_seen_in(tool_result.output["stdout"], plants)
    assert tool_seen == [_SHARED_NAME]

    agent_result = await ShellCommandAgent().handle_intent(
        IntentMessage(intent="run_command", params={"command": agent_command})
    )
    assert agent_result is not None
    assert agent_result.success is True, f"shell agent did not run: {agent_result.error}"
    agent_exit_code = agent_result.result["exit_code"]
    assert agent_exit_code == 0
    agent_seen = _names_seen_in(agent_result.result["stdout"], plants)
    assert agent_seen == [_SHARED_NAME]
