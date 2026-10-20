"""BF-908 (#1605): the crew-scope token's entry in the OS keyring.

The crew-scope token guards every Captain route (``require_crew_scope``) and keys
the browser's file credential vault. Until BF-908 it lived only in the config
file, which any process running as the vessel's user can read, agents' shell
commands included. This module owns its keyring entry: the one place that reads,
stores or clears it, and the one read of ``auth.crew_scope_token`` from a config
(:func:`configured_crew_scope_token`).

* :class:`CrewScopeKeyring` is ``CredentialStore``'s keyring step. Startup reads
  the entry once (:meth:`CrewScopeKeyring.load`); a change takes effect at the next
  start, because the browser vault's key is fixed then.
* :func:`store_keyring_token` and :func:`clear_keyring_token` are the Captain's:
  only ``probos crew-token`` (``probos/crew_token_cli.py``) calls them. No route,
  crew tool, federation surface or MCP server imports this module
  (``tests/test_bf908_crew_scope_token.py`` pins both).

The keyring is used through a recommended (secure) backend only, by the AD-1196
rule (:func:`probos.identity_key_store.secure_keyring_backend`). A host with no
secure backend has no keyring step, and the token can come only from the config
file. A secure backend that fails or does not answer is UNAVAILABLE, never "no
token": with no token in the config file either, every route that needs the
token refuses every caller instead of letting every caller through. So does a
keyring step startup has not read yet (UNREAD). The read runs on a daemon thread,
so a keyring that never answers cannot hold the vessel or ``probos doctor`` open
at exit.

What this does not defend: any process running as the vessel's OS user can read
and write this entry with the ``keyring`` package, agents' shell commands and
``run_python`` included. Moving the token here takes it out of files and out of
every child's environment; it does not separate one user's processes.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

#: The keyring entry. Distinct from the browser vault's ``probos.credentials`` and
#: the identity keys' ``probos.identity:<kid>``.
CREW_SCOPE_KEYRING_SERVICE = "probos.crew_scope"
CREW_SCOPE_KEYRING_USERNAME = "crew_scope_token"
#: A keyring that has not answered by then is unavailable (a locked keychain can prompt).
CREW_SCOPE_READ_TIMEOUT_SECONDS = 10.0
#: The shortest token ``probos crew-token`` stores.
MIN_TOKEN_CHARS = 16
#: What every crew-scope route answers while the keyring is unreadable and no token is configured.
CREW_SCOPE_UNAVAILABLE = "crew_scope_token_unavailable"
_NO_SECURE_BACKEND = "no recommended (secure) keyring backend"
#: The daemon thread a bounded read runs on (BF-908 A2, D20). Never joined, so it never holds up exit.
CREW_SCOPE_READ_THREAD_NAME = "probos-crew-scope-keyring-read"


class CrewScopeSource(Enum):
    """What the keyring step found."""

    UNREAD = "unread"  # startup has not read it yet
    KEYRING = "keyring"  # a secure keyring holds the token
    ABSENT = "absent"  # a secure keyring holds no token
    NO_SECURE_BACKEND = "no_secure_backend"  # this host has no recommended keyring backend
    UNAVAILABLE = "unavailable"  # a secure keyring failed, did not answer, or holds a malformed entry


#: BF-908 A2 (D21): with no token in the config, these refuse every caller. UNREAD is one of them, so a runtime
#: whose startup never read the keyring refuses loudly instead of opening every crew-scope route.
_LOCKED_SOURCES = frozenset({CrewScopeSource.UNREAD, CrewScopeSource.UNAVAILABLE})


@dataclass(frozen=True)
class KeyringRead:
    """One read of the entry. ``token`` is never in the repr; ``reason`` never holds a value."""

    source: CrewScopeSource
    token: str = field(default="", repr=False)
    backend: str = ""
    reason: str = ""


@dataclass(frozen=True)
class CrewScopePosture:
    """Where the token comes from, said without its value. ``severity``: ok, warning or error."""

    severity: str
    message: str
    remediation: str = ""


class CrewScopeKeyringError(Exception):
    """A store or clear the keyring refused. The message never holds the token."""


def configured_crew_scope_token(config: Any) -> str:
    """``auth.crew_scope_token`` from ``config``; ``""`` when the config or its auth section is absent.

    The only read of that setting in ``src/probos`` (pinned by the BF-908 guard test).
    """
    auth = getattr(config, "auth", None) if config is not None else None
    if auth is None:
        return ""
    return auth.crew_scope_token


def token_refusal(value: object) -> str | None:
    """Why ``value`` may not be stored as the token, or ``None`` when it may."""
    if not isinstance(value, str):
        return "not text"
    if len(value) < MIN_TOKEN_CHARS:
        return f"shorter than {MIN_TOKEN_CHARS} characters"
    if any(not ("!" <= char <= "~") for char in value):
        return "not printable ASCII without spaces"
    return None


def _backend_name(backend: Any) -> str:
    kind = type(backend)
    return f"{kind.__module__}.{kind.__qualname__}"


def _secure_backend(backend: Any | None) -> Any:
    """The recommended backend to call, by the AD-1196 rule; raises ``KeyStoreUnavailable``."""
    from probos.identity_key_store import secure_keyring_backend

    return secure_keyring_backend(backend)


def read_keyring_token(backend: Any | None = None) -> KeyringRead:
    """Read the entry once, synchronously. Never raises and never logs the value."""
    from probos.identity_keys import KeyStoreUnavailable

    try:
        chosen = _secure_backend(backend)
    except KeyStoreUnavailable:
        return KeyringRead(CrewScopeSource.NO_SECURE_BACKEND, reason=_NO_SECURE_BACKEND)
    except Exception as exc:  # noqa: BLE001 -- fail closed: an unresolvable keyring is unavailable
        return KeyringRead(CrewScopeSource.UNAVAILABLE, reason=f"the keyring failed ({type(exc).__name__})")
    name = _backend_name(chosen)
    try:
        value = chosen.get_password(CREW_SCOPE_KEYRING_SERVICE, CREW_SCOPE_KEYRING_USERNAME)
    except Exception as exc:  # noqa: BLE001 -- fail closed: a failing read is never "no token"
        return KeyringRead(CrewScopeSource.UNAVAILABLE, backend=name, reason=f"the keyring failed ({type(exc).__name__})")
    if value is None:
        return KeyringRead(CrewScopeSource.ABSENT, backend=name)
    refusal = token_refusal(value)
    if refusal is not None:
        return KeyringRead(CrewScopeSource.UNAVAILABLE, backend=name, reason=f"the keyring entry is malformed ({refusal})")
    return KeyringRead(CrewScopeSource.KEYRING, token=value, backend=name)


def _hand_over(future: asyncio.Future[KeyringRead], read: KeyringRead) -> None:
    """On ``future``'s loop: deliver ``read`` unless the caller has stopped waiting for it."""
    if not future.done():  # timed out or cancelled: nobody waits for this read any more
        future.set_result(read)


def _read_on_daemon_thread(
    backend: Any | None, loop: asyncio.AbstractEventLoop, future: asyncio.Future[KeyringRead],
) -> None:
    """The worker: the blocking read (it never raises), handed to ``loop`` if that loop still runs."""
    read = read_keyring_token(backend)
    try:
        loop.call_soon_threadsafe(_hand_over, future, read)
    except RuntimeError:  # the loop closed after the caller gave up: nothing to deliver to
        return


async def read_keyring_token_bounded(
    backend: Any | None = None, *, timeout_seconds: float = CREW_SCOPE_READ_TIMEOUT_SECONDS,
) -> KeyringRead:
    """:func:`read_keyring_token` on a daemon thread, bounded in time. Raises only ``CancelledError``.

    BF-908 A2 (D20): not ``asyncio.to_thread``. A timed-out ``wait_for`` stops waiting but cannot stop the
    blocking call, and the default executor's worker is joined when ``asyncio.run`` closes its loop (up to
    300 s) and again, without a limit, at interpreter exit, so a keyring that never answers would hold the
    vessel or ``probos doctor`` open. A daemon thread is never joined; a late answer is dropped quietly.
    One thread per read: startup reads once, the doctor once (AD-1137 A-3 measured the same remedy).
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[KeyringRead] = loop.create_future()
    try:
        worker = threading.Thread(
            target=_read_on_daemon_thread, args=(backend, loop, future), name=CREW_SCOPE_READ_THREAD_NAME, daemon=True,
        )
        worker.start()
        return await asyncio.wait_for(future, timeout=timeout_seconds)
    except TimeoutError:
        return KeyringRead(
            CrewScopeSource.UNAVAILABLE, reason=f"the keyring did not answer within {timeout_seconds:g} s",
        )
    except Exception as exc:  # noqa: BLE001 -- the worker could not run: unavailable, fail closed
        return KeyringRead(CrewScopeSource.UNAVAILABLE, reason=f"the keyring read did not run ({type(exc).__name__})")


def store_keyring_token(value: str, *, backend: Any | None = None) -> str:
    """Store ``value`` as the entry and read it back; return the backend's name.

    The Captain's action only (``probos crew-token``). Raises :class:`CrewScopeKeyringError`.
    """
    from probos.identity_keys import KeyStoreUnavailable

    if token_refusal(value) is not None:
        raise CrewScopeKeyringError("the token does not meet the stored-token rule")
    try:
        chosen = _secure_backend(backend)
    except KeyStoreUnavailable:
        raise CrewScopeKeyringError(f"this host has {_NO_SECURE_BACKEND}") from None
    name = _backend_name(chosen)
    try:
        chosen.set_password(CREW_SCOPE_KEYRING_SERVICE, CREW_SCOPE_KEYRING_USERNAME, value)
        stored = chosen.get_password(CREW_SCOPE_KEYRING_SERVICE, CREW_SCOPE_KEYRING_USERNAME)
    except Exception as exc:  # noqa: BLE001 -- the type only: a backend's text could quote the value
        raise CrewScopeKeyringError(f"the keyring {name} refused the token ({type(exc).__name__})") from None
    if not isinstance(stored, str) or not hmac.compare_digest(stored.encode("utf-8"), value.encode("utf-8")):
        raise CrewScopeKeyringError(f"the keyring {name} did not keep the token")
    return name


def _entry_absent(chosen: Any) -> bool:
    """True only when ``chosen`` answers that it holds no entry. A read-back that fails is not "absent"."""
    try:
        held = chosen.get_password(CREW_SCOPE_KEYRING_SERVICE, CREW_SCOPE_KEYRING_USERNAME)
    except Exception:  # noqa: BLE001 -- fail closed: never report "none was there" without an answer
        return False  # BF-908 A2: an entry that cannot be read back is not "absent"
    return held is None


def clear_keyring_token(*, backend: Any | None = None) -> bool:
    """Delete the entry: ``True`` when one was removed, ``False`` when a read-back shows there was none.

    The Captain's action only. ``PasswordDeleteError`` alone does not mean "none was there": keyring's macOS
    backend raises it for every refusal, a denied keychain included (BF-908 A2, D22). Raises
    :class:`CrewScopeKeyringError`, whose message names the exception's type only.
    """
    import keyring.errors

    from probos.identity_keys import KeyStoreUnavailable

    try:
        chosen = _secure_backend(backend)
    except KeyStoreUnavailable:
        raise CrewScopeKeyringError(f"this host has {_NO_SECURE_BACKEND}") from None
    name = _backend_name(chosen)
    try:
        chosen.delete_password(CREW_SCOPE_KEYRING_SERVICE, CREW_SCOPE_KEYRING_USERNAME)
    except Exception as exc:  # noqa: BLE001 -- the type only: a backend's text could quote the value
        if isinstance(exc, keyring.errors.PasswordDeleteError) and _entry_absent(chosen):
            return False
        raise CrewScopeKeyringError(f"the keyring {name} refused to clear the token ({type(exc).__name__})") from None
    return True


def crew_scope_posture(read: KeyringRead, *, config_holds_token: bool, config_file: str) -> CrewScopePosture:
    """Where the token comes from, for the startup log, ``probos doctor`` and ``probos crew-token status``."""
    source = read.source
    if source is CrewScopeSource.KEYRING and config_holds_token:
        return CrewScopePosture(
            "warning",
            f"BF-908: auth.crew_scope_token in {config_file} is not used: the OS keyring holds the crew-scope "
            "token. Delete that line; any process running as this user can read the file.",
            f"Delete auth.crew_scope_token from {config_file}. ProbOS never edits the file.",
        )
    if source is CrewScopeSource.KEYRING:
        return CrewScopePosture("ok", f"crew-scope token: held in the OS keyring ({read.backend})")
    if not config_holds_token and source is CrewScopeSource.UNAVAILABLE:
        return CrewScopePosture(
            "error",
            f"BF-908: the OS keyring could not be read ({read.reason}) and {config_file} sets no crew-scope token, "
            f"so every route that needs the token refuses every caller (403 {CREW_SCOPE_UNAVAILABLE}) until the "
            "vessel restarts with the keyring readable.",
            "Unlock or repair the OS keyring, then restart the vessel; `probos crew-token status` shows what it answers.",
        )
    if not config_holds_token:
        return CrewScopePosture(
            "ok", "crew-scope token: not set; the Captain-only routes answer 403 and the other API routes take no token",
        )
    exposed = (
        f"BF-908: the crew-scope token is read from auth.crew_scope_token in {config_file}, which any process "
        "running as this user can read, agents' shell commands included."
    )
    if source is CrewScopeSource.NO_SECURE_BACKEND:
        return CrewScopePosture(
            "warning", f"{exposed} This host has no secure OS keyring to move it to.",
            "Keep the file readable by your user only; `probos crew-token set` needs a secure OS keyring.",
        )
    if source is CrewScopeSource.UNAVAILABLE:
        exposed = f"{exposed} The OS keyring could not be read ({read.reason})."
    return CrewScopePosture(
        "warning", exposed,
        "Run `probos crew-token set` and enter the same token, so HXI and the browser vault keep working, then "
        f"delete auth.crew_scope_token from {config_file} and restart. ProbOS never edits the file. While any "
        "token is set, an HXI panel that sends none answers 401, as it does now.",
    )


class CrewScopeKeyring:
    """BF-908: ``CredentialStore``'s keyring step for the crew-scope token, read once at startup."""

    def __init__(
        self, *, backend: Any | None = None, timeout_seconds: float = CREW_SCOPE_READ_TIMEOUT_SECONDS,
    ) -> None:
        self._backend = backend
        self._timeout_seconds = timeout_seconds
        self._read = KeyringRead(CrewScopeSource.UNREAD)

    @property
    def source(self) -> CrewScopeSource:
        """What the last read found (``UNREAD`` before startup reads it)."""
        return self._read.source

    async def load(self, *, config: Any = None, config_path: str | None = None) -> KeyringRead:
        """Read the entry (bounded; raises only ``CancelledError``) and log where the token comes from.

        The one line logged also says how to move the token (D7).
        """
        read = await read_keyring_token_bounded(self._backend, timeout_seconds=self._timeout_seconds)
        self._read = read
        posture = crew_scope_posture(
            read, config_holds_token=bool(configured_crew_scope_token(config)),
            config_file=config_path or "the loaded configuration",
        )
        # D7: the logged line itself says how to move the token, so it carries the remediation (fixed text and the
        # config path, never a value). One record at the posture's level: startup logs exactly one line (test E1).
        line = f"{posture.message} {posture.remediation}" if posture.remediation else posture.message
        if posture.severity == "ok":
            logger.info("%s", line)
        elif posture.severity == "warning":
            logger.warning("%s", line)
        else:
            logger.error("%s", line)
        return read

    def token(self, config: Any) -> str:
        """The token to enforce: the keyring's when it holds one, else ``config``'s (``""`` when neither)."""
        if self._read.source is CrewScopeSource.KEYRING:
            return self._read.token
        return configured_crew_scope_token(config)

    def locked(self, config: Any) -> bool:
        """True when ``config`` holds no token and the keyring is unreadable or not read yet: refuse every caller.

        BF-908 A2 (D21): ``UNREAD`` counts, so a runtime whose startup never read the keyring refuses instead of
        letting every caller through. A token in ``config`` is enforced in every state, as before.
        """
        return self._read.source in _LOCKED_SOURCES and not configured_crew_scope_token(config)
