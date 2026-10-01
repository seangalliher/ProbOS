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
Python release removes or renames them the patch degrades to the stock graceful close with a warning
instead of breaking every test.
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
_HOOK = "_make_self_pipe"
_MARKER = "_abortive_self_pipe"
_LOOP_CLASSES = (
    ("asyncio.proactor_events", "BaseProactorEventLoop"),
    ("asyncio.selector_events", "BaseSelectorEventLoop"),
)


def _nothing() -> None:
    """The restore function of an install that changed nothing."""


def _abortive(original: SelfPipeFactory) -> SelfPipeFactory:
    @functools.wraps(original)
    def make_self_pipe(loop: Any) -> None:
        original(loop)
        try:
            for end in (loop._ssock, loop._csock):
                end.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _ABORT_ON_CLOSE)
        except (AttributeError, OSError):
            # Log-and-degrade: a graceful close only costs one TIME_WAIT port.
            logger.warning(
                "Could not set SO_LINGER on the self-pipe of %s; closing the loop will leave a TIME_WAIT port behind",
                type(loop).__name__,
                exc_info=True,
            )

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
    gets the abortive close and nothing else does. A no-op off Windows, where the self-pipe is not a TCP pair.
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
