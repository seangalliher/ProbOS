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

#: BF-904a (#1585): the options every git process of the build pipeline starts with. Code under
#: test runs as the operator's user in the tree it builds, so it can plant a hook or set
#: core.fsmonitor in the repository; neither may run at a later git command of the pipeline.
#: Nothing can be planted under the null device (the value execution/authority.py uses too).
HARDENED_GIT_CONFIG_ARGS: tuple[str, ...] = (
    "-c", f"core.hooksPath={os.devnull}",  # BF-904a: no repository hook runs
    "-c", "core.fsmonitor=false",  # BF-904a: no fsmonitor hook runs
)

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


def trusted_command_env() -> dict[str, str]:
    """BF-892 (#1543): the runtime's whole environment, for a command ProbOS builds itself.

    For a launch whose program and argument shape ProbOS fixes -- ``git`` on its own
    repositories, ``gh``, ``docker``, ``ollama``, ``nats-server``, ``rg``, ``blender``,
    ``rhubarb``, ``piper``, ``soffice``, a credential helper, ProbOS's own probe, an
    operator-approved MCP server -- that may need the operator's toolchain variables
    (credentials, proxies, config paths). Never for a command or code the model or an
    agent wrote: those use :func:`build_command_env`.

    Returns a copy, so a caller's additions never reach ``os.environ``. Every caller is
    listed with its reason in ``tests/test_bf892_spawn_env_guard.py``
    (``TRUSTED_ENV_SITES``); a new caller fails that guard until it is listed, so choosing
    this environment is always a reviewed decision.
    """
    return dict(os.environ)
