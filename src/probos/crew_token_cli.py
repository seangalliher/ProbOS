"""BF-908 (#1605): ``probos crew-token`` -- the Captain sets, rotates, clears or inspects the crew-scope token.

The token is read from a no-echo prompt (twice) or, with ``--stdin``, from one line
of standard input; never from the command line, so it reaches neither shell history
nor the process list. It is stored in the OS keyring through
``probos.security.crew_scope``; nothing here writes a config file. A change takes
effect when the vessel next starts.

This is the Captain's action. No route, crew tool or MCP server reaches it: only
``probos/__main__.py`` imports this module (pinned by
``tests/test_bf908_crew_scope_token.py``), and it imports nothing from
``probos.doctor`` (AD-1137: only ``__main__`` does, ``tests/test_ad1137_doctor.py``).
An agent's shell command runs as the same
user and could run this command, or call ``keyring`` directly; that residual is
recorded in DECISIONS.md, BF-908.
"""

from __future__ import annotations

import getpass
import hmac
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from rich.console import Console
from rich.markup import escape

from probos.security.crew_scope import (
    MIN_TOKEN_CHARS,
    CrewScopeKeyringError,
    CrewScopeSource,
    KeyringRead,
    clear_keyring_token,
    configured_crew_scope_token,
    crew_scope_posture,
    read_keyring_token,
    store_keyring_token,
    token_refusal,
)

_RESTART = "Restart the vessel for this to take effect; until then it keeps the token it started with."


def file_vault_entries(config: Any) -> tuple[Path, int] | None:
    """The browser file vault's path and entry count when it is enabled (-1: unreadable), else None.

    Resolved as the vessel resolves it: relative to the current directory.
    """
    vault = config.browser_tool.credential_vault
    if not vault.enabled or vault.backend != "file":
        return None
    path = Path(vault.file_path).resolve()
    if not path.exists():
        return path, 0
    try:
        refs = json.loads(path.read_text(encoding="utf-8")).get("refs", {})
    except (OSError, ValueError, AttributeError):
        return path, -1
    return (path, len(refs)) if isinstance(refs, dict) else (path, -1)


def _vault_note(count: int) -> str:
    return "cannot be read" if count < 0 else f"holds {count} entr{'y' if count == 1 else 'ies'}"


def _load(config_path: Path, console: Console) -> Any | None:
    """The config at ``config_path``, or None after saying it does not load.

    BF-908 A1 (D19): only the exception's type is shown, because its text can quote a
    value from the file (Pydantic's input_value). ``probos doctor`` names the setting at
    fault without its value; only ``__main__`` imports the doctor package (AD-1137).
    """
    from probos.config import load_config

    try:
        return load_config(config_path)
    except Exception as exc:  # noqa: BLE001 -- BF-908 A1: the type name only, never the exception's text
        console.print(escape(f"Config {config_path} does not load ({type(exc).__name__}); `probos doctor --config {config_path}` names the setting at fault."), style="red")
        return None


def _read_new_token(
    *, use_stdin: bool, stdin: TextIO, stdin_is_tty: Callable[[], bool],
    read_secret: Callable[[str], str], console: Console,
) -> tuple[str | None, int]:
    if use_stdin:
        return stdin.readline().rstrip("\r\n"), 0
    if not stdin_is_tty():
        console.print("Standard input is not a terminal: pass --stdin to read the token from it.", style="red")
        return None, 2
    first = read_secret("New crew-scope token (not shown): ")
    second = read_secret("The same token again: ")
    if not hmac.compare_digest(first.encode("utf-8"), second.encode("utf-8")):
        console.print("The two entries differ; nothing was stored.", style="red")
        return None, 1
    return first, 0


def _status(current: KeyringRead, config: Any, config_path: Path, console: Console) -> int:
    posture = crew_scope_posture(
        current, config_holds_token=bool(configured_crew_scope_token(config)), config_file=str(config_path),
    )
    console.print(escape(posture.message))
    if posture.remediation:
        console.print(escape(posture.remediation), style="dim")
    vault = file_vault_entries(config)
    if vault is not None:
        console.print(escape(f"Browser file vault {vault[0]} {_vault_note(vault[1])}."))
    return 0


def _set(
    command: str, current: KeyringRead, config: Any, config_path: Path, console: Console, backend: Any, *,
    use_stdin: bool, stdin: TextIO, stdin_is_tty: Callable[[], bool], read_secret: Callable[[str], str],
) -> int:
    if current.source is CrewScopeSource.NO_SECURE_BACKEND:
        console.print("This host has no secure OS keyring, so the token cannot be stored there; nothing was stored.", style="red")
        return 1
    if current.source is CrewScopeSource.UNAVAILABLE:
        console.print(escape(f"The OS keyring could not be read ({current.reason}); nothing was stored."), style="red")
        return 1
    if command == "set" and current.source is CrewScopeSource.KEYRING:
        console.print("The OS keyring already holds a crew-scope token: use `probos crew-token rotate` to replace it.", style="red")
        return 1
    if command == "rotate" and current.source is not CrewScopeSource.KEYRING:
        console.print("The OS keyring holds no crew-scope token to rotate: use `probos crew-token set`.", style="red")
        return 1
    value, code = _read_new_token(
        use_stdin=use_stdin, stdin=stdin, stdin_is_tty=stdin_is_tty, read_secret=read_secret, console=console,
    )
    if value is None:
        return code
    refusal = token_refusal(value)
    if refusal is not None:
        console.print(
            escape(f"Not stored: the token is {refusal}; use at least {MIN_TOKEN_CHARS} printable ASCII characters and no spaces."),
            style="red",
        )
        return 1
    in_use = current.token if current.source is CrewScopeSource.KEYRING else configured_crew_scope_token(config)
    changes_key = not hmac.compare_digest(value.encode("utf-8"), in_use.encode("utf-8"))
    vault = file_vault_entries(config)
    if changes_key and vault is not None and vault[1] != 0:
        console.print(
            escape(
                f"Not stored: the browser file vault {vault[0]} {_vault_note(vault[1])}, encrypted under the token in "
                "use; a different token would leave them unreadable. Remove them first, or enter the token in use."
            ),
            style="red",
        )
        return 1
    try:
        name = store_keyring_token(value, backend=backend)
    except CrewScopeKeyringError as exc:
        console.print(escape(f"Not stored: {exc}."), style="red")
        return 1
    console.print(escape(f"Stored the crew-scope token in the OS keyring ({name}). {_RESTART}"))
    if configured_crew_scope_token(config):
        console.print(escape(
            f"auth.crew_scope_token is still set in {config_path}: delete that line (ProbOS never edits the file). "
            "While the keyring holds a token, the file's is not used."
        ))
    console.print("HXI panels must send this token: while any token is set, a panel that sends none answers 401.")
    return 0


def _clear(current: KeyringRead, config: Any, config_path: Path, console: Console, backend: Any) -> int:
    if current.source is CrewScopeSource.NO_SECURE_BACKEND:
        console.print("This host has no secure OS keyring, so no keyring token exists to clear.")
        return 0
    try:
        removed = clear_keyring_token(backend=backend)
    except CrewScopeKeyringError as exc:
        console.print(escape(f"Not cleared: {exc}."), style="red")
        return 1
    if not removed:
        console.print("The OS keyring held no crew-scope token; nothing was cleared.")
        return 0
    if configured_crew_scope_token(config):
        after = f"the vessel reads auth.crew_scope_token from {config_path}"
    else:
        after = "the Captain-only routes answer 403 and the other API routes take no token, until a token is set again"
    console.print(escape(f"Cleared the crew-scope token from the OS keyring. {_RESTART} After the restart, {after}."))
    vault = file_vault_entries(config)
    if vault is not None and vault[1] != 0:
        console.print(escape(
            f"The browser file vault {vault[0]} {_vault_note(vault[1])}, encrypted under the cleared token; "
            "set that token again to read them."
        ))
    return 0


def run(
    command: str,
    *,
    config_path: Path,
    console: Console,
    use_stdin: bool = False,
    read_secret: Callable[[str], str] = getpass.getpass,
    stdin: TextIO | None = None,
    stdin_is_tty: Callable[[], bool] | None = None,
    backend: Any | None = None,
) -> int:
    """``probos crew-token <command>``: 0 done, 1 refused, 2 usage or an unreadable config."""
    config = _load(config_path, console)
    if config is None:
        return 2
    current = read_keyring_token(backend)
    if command == "status":
        return _status(current, config, config_path, console)
    if command == "clear":
        return _clear(current, config, config_path, console, backend)
    if command not in ("set", "rotate"):
        console.print(escape(f"Unknown crew-token command: {command}"), style="red")
        return 2
    source = sys.stdin if stdin is None else stdin
    is_tty = source.isatty if stdin_is_tty is None else stdin_is_tty
    return _set(
        command, current, config, config_path, console, backend,
        use_stdin=use_stdin, stdin=source, stdin_is_tty=is_tty, read_secret=read_secret,
    )
