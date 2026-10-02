"""Stop test-suite event-loop churn from exhausting Windows' ephemeral TCP ports.

On Windows ``socket.socketpair()`` is a loopback TCP connection (the stdlib
``_fallback_socketpair``) and every asyncio loop -- Proactor or Selector -- builds its
self-pipe from one. Closing a loop therefore closes a TCP connection gracefully: the
end that closes first lands in TIME_WAIT and pins one ephemeral port for ``TcpTimedWaitDelay``
(120 s by default). The dynamic range holds 16,384 ports. API-heavy test files create about one loop
per test (a bare ``TestClient`` creates one per request); one worker was measured creating up to 785
loops inside a single 120 s window, so 16 workers can pin about 12,000 ports between them, and any
other test run on the machine tips the next ``socketpair()`` into failing inside ``connect()`` with
``WinError 10055`` while a test is being set up.

The self-pipe carries only one-byte wake-ups, so nothing in it has to survive ``close()``. Its two
ends are closed abortively (``SO_LINGER`` on, 0 s): ``close()`` sends RST, the connection never
reaches TIME_WAIT, and the port is free the moment the loop closes.

Only the self-pipe is touched, never ``socket.socketpair`` itself. A test's own socketpair must keep
graceful-close semantics: with ``SO_LINGER(1, 0)`` the RST that follows ``writer.close()`` discards bytes
the reader has not read yet (measured: ``recv`` raises ``ConnectionResetError`` instead of returning the
payload). So this wraps asyncio's ``_make_self_pipe`` on the two base loop classes and lingers
``_ssock`` / ``_csock`` there. That reaches into asyncio internals on purpose, in this one module; if a
Python release removes or renames them, or a ``setsockopt`` fails, the patch warns instead of breaking every
test and tries to leave the self-pipe as asyncio built it: it attempts to put any end that was already switched
back to the default linger. Only a successful put-back makes the self-pipe stock again; a put-back that fails
is logged too, so a half-switched self-pipe is never silent.
"""

from __future__ import annotations

import functools
import importlib
import logging
import socket
import struct
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

SelfPipeFactory = Callable[[Any], None]

_ABORT_ON_CLOSE = struct.pack("HH", 1, 0)  # Windows LINGER {u_short l_onoff=1; u_short l_linger=0}
_GRACEFUL_CLOSE = struct.pack("HH", 0, 0)  # the default every new socket starts with: linger off
_HOOK = "_make_self_pipe"
_MARKER = "_abortive_self_pipe"
_LOOP_CLASSES = (
    ("asyncio.proactor_events", "BaseProactorEventLoop"),
    ("asyncio.selector_events", "BaseSelectorEventLoop"),
)


def _nothing() -> None:
    """The restore function of an install that changed nothing."""


def _make_graceful(switched: list[socket.socket], loop_name: str) -> None:
    """Best effort: put the default linger back on every end already switched; a put-back that fails is logged."""
    for end in switched:
        try:
            end.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _GRACEFUL_CLOSE)
        except OSError:
            logger.warning(
                "Could not restore the default SO_LINGER on a self-pipe end of %s; that end still closes abortively",
                loop_name,
                exc_info=True,
            )


def _abortive(original: SelfPipeFactory) -> SelfPipeFactory:
    @functools.wraps(original)
    def make_self_pipe(loop: Any) -> None:
        original(loop)
        switched: list[socket.socket] = []
        try:
            for end in (loop._ssock, loop._csock):
                end.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _ABORT_ON_CLOSE)
                switched.append(end)
        except (AttributeError, OSError):
            # Log-and-degrade: aim for asyncio's own graceful close on BOTH ends (it only costs one TIME_WAIT
            # port), so a put-back of any end that already switched is attempted; a failed put-back is logged.
            logger.warning(
                "Could not set SO_LINGER on the self-pipe of %s; trying to put any end already switched back to "
                "the default linger (a graceful close leaves one TIME_WAIT port behind)",
                type(loop).__name__,
                exc_info=True,
            )
            _make_graceful(switched, type(loop).__name__)

    setattr(make_self_pipe, _MARKER, True)
    return make_self_pipe


def _loop_class(module_name: str, class_name: str) -> type | None:
    try:
        return getattr(importlib.import_module(module_name), class_name, None)
    except ImportError:
        return None


def install_abortive_self_pipe() -> Callable[[], None]:
    """Make asyncio loops close their self-pipe abortively; return the function that undoes it.

    Wraps ``_make_self_pipe`` on the Proactor and Selector base loop classes, so every loop built afterwards
    tries for the abortive close and nothing else does (a failed attempt is logged and a rollback is attempted,
    see the module docstring). A no-op off Windows, where the self-pipe is not a TCP pair.
    A class whose hook is missing or not callable is left unpatched with a warning; a class that is already
    wrapped is left alone, so repeated installs never stack wrappers and the returned restore undoes only
    what this call did.
    """
    if sys.platform != "win32":
        return _nothing
    patched: list[tuple[type, SelfPipeFactory, bool]] = []
    for module_name, class_name in _LOOP_CLASSES:
        loop_class = _loop_class(module_name, class_name)
        original = getattr(loop_class, _HOOK, None)
        if not callable(original):
            logger.warning(
                "%s.%s has no callable %s in this Python; its loops keep the graceful self-pipe close and each "
                "one leaves a TIME_WAIT port behind",
                module_name,
                class_name,
                _HOOK,
            )
            continue
        if getattr(original, _MARKER, False):
            continue
        patched.append((loop_class, original, _HOOK in vars(loop_class)))
        setattr(loop_class, _HOOK, _abortive(original))

    def restore() -> None:
        while patched:
            loop_class, original, owned = patched.pop()
            if owned:
                setattr(loop_class, _HOOK, original)
            else:
                delattr(loop_class, _HOOK)

    return restore


@contextmanager
def abortive_self_pipe() -> Iterator[None]:
    """Scoped ``install_abortive_self_pipe`` for tests that need asyncio's own behaviour back afterwards."""
    restore = install_abortive_self_pipe()
    try:
        yield
    finally:
        restore()
