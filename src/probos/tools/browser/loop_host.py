"""BF-695: run Playwright on an event loop that can actually spawn subprocesses.

``__main__.py`` installs ``WindowsSelectorEventLoopPolicy`` because ``pyzmq``
needs ``add_reader``. That loop has no subprocess transport — ``BaseEventLoop.
_make_subprocess_transport`` raises ``NotImplementedError`` — and Playwright's
transport launches its driver with ``asyncio.create_subprocess_exec``. So the
browser tool has never started inside ``probos serve`` on Windows.

Changing the global policy would trade one platform bug for another across
NATS, aiosqlite, uvicorn and every agent, so the incompatibility is isolated to
the component that has it: a single daemon thread running its own
subprocess-capable loop, which owns every Playwright object. Callers stay on
their own loop and marshal across.

Marshalling happens at :attr:`BrowserSession.page` rather than at the tool's
dispatch point. Two of the four dispatch branches interleave Playwright with
``store.write()`` and ``llm_client.complete()``, whose locks, semaphores and
httpx pools are bound to the main loop; moving those across would raise
``RuntimeError: ... is bound to a different event loop`` inside an
``except Exception:`` honest-degrade block and degrade silently forever. The
MJPEG streamer never passes through ``invoke`` at all. A proxy at the page
boundary covers every Playwright touch with no call-site edits and leaves the
main-loop-bound services where they belong.

The decisive property is failure *direction*. Call-site marshalling fails open:
a future handler that adds ``await page.something_new()`` is a silent
Windows-only break. A proxy fails closed — there is no site to forget, and an
attribute kind the proxy does not recognise raises rather than leaking a
host-bound object back to the caller's loop.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from asyncio import BaseEventLoop
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# How long to wait for the host thread to come up, and to go back down.
_THREAD_TIMEOUT_SECONDS: float = 5.0

# Depth budget when deciding whether a returned value is inert data. A value
# nested deeper than this is treated as NOT plain and therefore wrapped, which
# is the fail-closed direction: wrapping inert data is ugly, leaking a
# host-bound object is the bug this module exists to remove.
_MAX_PLAIN_DEPTH: int = 12

_PLAIN_SCALARS: tuple[type, ...] = (str, bytes, bytearray, bool, int, float)

# Sync Playwright calls the proxy may run inline on the caller's thread.
#
# Membership requires proving the call is a pure constructor: it must not touch
# the loop, schedule a task, or write to the driver transport. ``locator`` and
# ``frame_locator`` qualify — both only build a ``Locator`` holding a selector
# string and a frame reference.
#
# ``set_default_timeout`` deliberately does NOT qualify: it calls
# ``channel.send_no_reply``, which writes to the driver transport. It is safe
# only because ``BrowserSession.start``/``connect`` call it while already
# running on the host loop, never through this proxy.
_INLINE_SYNC_CALLABLES: frozenset[str] = frozenset({"locator", "frame_locator"})

# ``page.expect_download()`` and its siblings look like pure constructors and
# are not: ``Waiter.reject_on_timeout`` calls ``loop.create_task`` during
# construction, so building one off the host loop schedules host work from a
# foreign thread. The whole construct-then-enter sequence is deferred onto the
# host loop by :class:`_DeferredAsyncContextManager`.
_DEFERRED_CM_PREFIX: str = "expect_"


class PlaywrightProxyError(RuntimeError):
    """The marshalling proxy met an attribute kind it does not recognise.

    Raised instead of returning the raw host-bound object. A permissive default
    would reintroduce the cross-loop bug this module removes, visible only on
    Windows and only at runtime; a raise is visible wherever it happens.
    """


# ----------------------------------------------------------------------
# Capability predicate
# ----------------------------------------------------------------------


def loop_supports_subprocess(loop: asyncio.AbstractEventLoop) -> bool:
    """True when ``loop`` can launch a subprocess transport.

    Tests the capability rather than ``sys.platform``: a Windows process that
    kept the Proactor loop is perfectly able to run Playwright, and a future
    loop implementation should be judged on what it does, not where it runs.
    ``BaseEventLoop._make_subprocess_transport`` is the version that raises
    ``NotImplementedError``, so inheriting it unchanged means "incapable".
    """
    impl = getattr(type(loop), "_make_subprocess_transport", None)
    if impl is None:
        return False
    return impl is not BaseEventLoop._make_subprocess_transport


def _new_subprocess_capable_loop() -> asyncio.AbstractEventLoop:
    """Build a loop for the host thread, preferring Proactor where it exists."""
    factory = getattr(asyncio, "ProactorEventLoop", None)
    if factory is not None:
        loop = factory()
        if loop_supports_subprocess(loop):
            return loop
        loop.close()
    return asyncio.new_event_loop()


# ----------------------------------------------------------------------
# The host
# ----------------------------------------------------------------------


class PlaywrightLoopHost:
    """Owns a subprocess-capable loop on a private daemon thread."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        """True when a host loop is live and accepting work."""
        loop = self._loop
        return loop is not None and not loop.is_closed()

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """The host loop, or None when the host has not been started."""
        return self._loop

    def start(self) -> None:
        """Start the host thread. Idempotent; safe to call from any thread."""
        with self._lock:
            if self._loop is not None:
                return
            ready = threading.Event()
            box: dict[str, Any] = {}

            def _run() -> None:
                try:
                    loop = _new_subprocess_capable_loop()
                except BaseException as exc:  # noqa: BLE001 - reported to start()
                    box["error"] = exc
                    ready.set()
                    return
                box["loop"] = loop
                asyncio.set_event_loop(loop)
                ready.set()
                try:
                    loop.run_forever()
                finally:
                    try:
                        loop.run_until_complete(loop.shutdown_asyncgens())
                    except Exception:
                        logger.debug(
                            "BF-695: shutting down async generators on the "
                            "Playwright host loop failed; closing it anyway",
                            exc_info=True,
                        )
                    loop.close()

            thread = threading.Thread(
                target=_run, name="probos-playwright-host", daemon=True,
            )
            thread.start()
            ready.wait(_THREAD_TIMEOUT_SECONDS)
            error = box.get("error")
            if error is not None:
                raise RuntimeError(
                    "BF-695: could not build a subprocess-capable loop for the "
                    "Playwright host thread; the browser tool stays unavailable"
                ) from error
            loop = box.get("loop")
            if loop is None:
                raise RuntimeError(
                    "BF-695: the Playwright host thread did not report a loop "
                    f"within {_THREAD_TIMEOUT_SECONDS:.1f}s; the browser tool "
                    "stays unavailable"
                )
            self._loop = loop
            self._thread = thread
        logger.info(
            "BF-695: Playwright host loop started (%s) on thread %s",
            type(loop).__name__, thread.name,
        )

    async def run(self, factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
        """Run ``factory()`` on the host loop and return its result here.

        Takes a factory rather than a coroutine so the coroutine is created on
        the host thread. The caller's loop is never blocked: submission is
        threadsafe and the wait is a normal ``await``. Cancelling the caller
        cancels the host-side task; exceptions cross with their original type
        and traceback.
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            raise RuntimeError(
                "BF-695: the Playwright host loop is not running; call start() "
                "before marshalling work onto it"
            )

        async def _invoke() -> T:
            return await factory()

        future = asyncio.run_coroutine_threadsafe(_invoke(), loop)
        try:
            return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            future.cancel()
            raise

    async def aclose(self) -> None:
        """Stop the host loop and join its thread. Idempotent."""
        with self._lock:
            loop = self._loop
            thread = self._thread
            self._loop = None
            self._thread = None
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            logger.debug(
                "BF-695: the Playwright host loop was already closed when "
                "aclose() asked it to stop",
                exc_info=True,
            )
        if thread is None:
            return
        await asyncio.get_running_loop().run_in_executor(
            None, thread.join, _THREAD_TIMEOUT_SECONDS,
        )
        if thread.is_alive():
            logger.warning(
                "BF-695: the Playwright host thread %s did not exit within "
                "%.1fs. It is a daemon so it cannot block interpreter exit, but "
                "any Playwright driver process it still owns will not be closed "
                "cleanly; a stray chromium may survive this shutdown.",
                thread.name, _THREAD_TIMEOUT_SECONDS,
            )


# ----------------------------------------------------------------------
# Process-wide singleton
# ----------------------------------------------------------------------

_HOST: PlaywrightLoopHost | None = None
_HOST_LOCK = threading.Lock()


def get_playwright_host() -> PlaywrightLoopHost:
    """Return the process-wide Playwright host (created on first call).

    One host serves every session because one driver thread is all Playwright
    needs. ``BrowserTool.stop()`` closes it; a later ``start()`` builds a fresh
    thread, so the singleton is reusable rather than one-shot.
    """
    global _HOST
    with _HOST_LOCK:
        if _HOST is None:
            _HOST = PlaywrightLoopHost()
        return _HOST


async def shutdown_playwright_host() -> None:
    """Close the process-wide host if one was ever started."""
    with _HOST_LOCK:
        host = _HOST
    if host is None:
        return
    await host.aclose()


# ----------------------------------------------------------------------
# The marshalling proxy
# ----------------------------------------------------------------------


def _is_plain(value: Any, depth: int = 0) -> bool:
    """True when ``value`` is inert data that may cross loops unwrapped."""
    if value is None or isinstance(value, _PLAIN_SCALARS):
        return True
    if depth >= _MAX_PLAIN_DEPTH:
        return False
    if isinstance(value, dict):
        return all(
            _is_plain(k, depth + 1) and _is_plain(v, depth + 1)
            for k, v in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return all(_is_plain(item, depth + 1) for item in value)
    return False


def _static_lookup(target: Any, name: str) -> Any:
    """Look ``name`` up without firing descriptors, or None when unavailable."""
    try:
        return inspect.getattr_static(target, name)
    except AttributeError:
        return None
    except Exception:
        logger.debug(
            "BF-695: static lookup of %r on %s failed; classifying by value "
            "instead", name, type(target).__name__, exc_info=True,
        )
        return None


def _unwrap(value: Any) -> Any:
    """Return the host-bound object behind a proxy, or ``value`` unchanged.

    Arguments travel the other way across the boundary: ``locator_a.drag_to(
    locator_b)`` hands Playwright a proxy unless it is unwrapped first, and
    Playwright would then look for ``_impl_obj`` on the proxy.
    """
    if isinstance(value, _HostBoundProxy):
        return value._bf695_target  # noqa: SLF001 - same-module private
    return value


def wrap_host_object(target: Any, host: PlaywrightLoopHost) -> Any:
    """Wrap a host-loop-owned Playwright object for use from another loop."""
    return _HostBoundProxy(target, host)


def _wrap_result(value: Any, host: PlaywrightLoopHost) -> Any:
    """Pass inert data straight through; wrap anything else."""
    if _is_plain(value):
        return value
    return _HostBoundProxy(value, host)


def _resolve_attribute(target: Any, host: PlaywrightLoopHost, name: str) -> Any:
    """Classify one attribute of a host-bound object and adapt it.

    Every branch either marshals, wraps, or passes inert data through. The
    final ``raise`` is the point of the design: an unrecognised kind must not
    reach the caller's loop as a raw host-bound object.
    """
    # An async property (``AsyncEventInfo.value``) creates its coroutine the
    # moment the attribute is read, so the read itself is deferred too. The
    # static lookup finds the descriptor without firing it.
    static = _static_lookup(target, name)
    if isinstance(static, property) and inspect.iscoroutinefunction(static.fget):
        return _HostBoundAwaitable(target, host, name)

    # A genuinely absent attribute must still raise AttributeError, because
    # several handlers probe with ``hasattr`` before choosing a code path.
    value = getattr(target, name)

    if inspect.iscoroutinefunction(value):
        return _make_async_call(value, host)

    if inspect.isawaitable(value):
        raise PlaywrightProxyError(
            f"{type(target).__name__}.{name} is an already-created awaitable; "
            "the proxy cannot re-home it onto the Playwright host loop. Expose "
            "it as an async method or an async property instead."
        )

    if callable(value):
        if name.startswith(_DEFERRED_CM_PREFIX):
            return _make_deferred_context_manager(value, host)
        if name in _INLINE_SYNC_CALLABLES:
            return _make_inline_call(value, host)
        raise PlaywrightProxyError(
            f"{type(target).__name__}.{name} is a synchronous call the proxy "
            "cannot marshal: doing so would need an await the caller does not "
            "have. Add it to _INLINE_SYNC_CALLABLES only after proving it "
            "neither touches the event loop nor writes to the driver transport."
        )

    if _is_plain(value):
        return value

    # A sub-object reached by plain attribute access (page.mouse, page.keyboard)
    # is host-bound too, so it gets a proxy rather than being handed over raw.
    return _HostBoundProxy(value, host)


def _make_async_call(
    bound_method: Callable[..., Coroutine[Any, Any, Any]],
    host: PlaywrightLoopHost,
) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Adapt an async Playwright method into one that runs on the host loop."""

    async def _call(*args: Any, **kwargs: Any) -> Any:
        real_args = tuple(_unwrap(a) for a in args)
        real_kwargs = {k: _unwrap(v) for k, v in kwargs.items()}
        result = await host.run(lambda: bound_method(*real_args, **real_kwargs))
        return _wrap_result(result, host)

    return _call


def _make_inline_call(
    fn: Callable[..., Any], host: PlaywrightLoopHost,
) -> Callable[..., Any]:
    """Adapt a pure sync constructor; the result is wrapped like any other."""

    def _call(*args: Any, **kwargs: Any) -> Any:
        real_args = tuple(_unwrap(a) for a in args)
        real_kwargs = {k: _unwrap(v) for k, v in kwargs.items()}
        return _wrap_result(fn(*real_args, **real_kwargs), host)

    return _call


def _make_deferred_context_manager(
    fn: Callable[..., Any], host: PlaywrightLoopHost,
) -> Callable[..., Any]:
    """Adapt ``expect_*``: construction is deferred to ``__aenter__``."""

    def _call(*args: Any, **kwargs: Any) -> _DeferredAsyncContextManager:
        return _DeferredAsyncContextManager(
            fn,
            tuple(_unwrap(a) for a in args),
            {k: _unwrap(v) for k, v in kwargs.items()},
            host,
        )

    return _call


class _HostBoundProxy:
    """Marshalling proxy for one host-loop-owned Playwright object.

    ``__slots__`` and no ``__dict__`` mean an attribute *write* fails loudly,
    which is correct: nothing in the browser tool assigns to a Playwright
    object, and silently writing through would be another way to lose the
    boundary.
    """

    __slots__ = ("_bf695_target", "_bf695_host")

    def __init__(self, target: Any, host: PlaywrightLoopHost) -> None:
        self._bf695_target = target
        self._bf695_host = host

    def __getattr__(self, name: str) -> Any:
        # Slot reads never reach here; a name in this namespace means the slot
        # itself is unset, so report it rather than recursing.
        if name.startswith("_bf695_"):
            raise AttributeError(name)
        return _resolve_attribute(self._bf695_target, self._bf695_host, name)

    async def __aenter__(self) -> Any:
        target = self._bf695_target
        host = self._bf695_host

        async def _enter() -> Any:
            return await target.__aenter__()

        return _wrap_result(await host.run(_enter), host)

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        target = self._bf695_target

        async def _exit() -> Any:
            return await target.__aexit__(exc_type, exc, tb)

        return await self._bf695_host.run(_exit)

    def __repr__(self) -> str:
        return f"<BF-695 host-bound {type(self._bf695_target).__name__}>"


class _HostBoundAwaitable:
    """An async property read, deferred so both read and await run on the host."""

    __slots__ = ("_bf695_target", "_bf695_host", "_bf695_name")

    def __init__(self, target: Any, host: PlaywrightLoopHost, name: str) -> None:
        self._bf695_target = target
        self._bf695_host = host
        self._bf695_name = name

    async def _bf695_resolve(self) -> Any:
        target = self._bf695_target
        name = self._bf695_name
        host = self._bf695_host

        async def _fetch() -> Any:
            return await getattr(target, name)

        return _wrap_result(await host.run(_fetch), host)

    def __await__(self) -> Any:
        return self._bf695_resolve().__await__()

    def __repr__(self) -> str:
        return (
            f"<BF-695 host-bound await "
            f"{type(self._bf695_target).__name__}.{self._bf695_name}>"
        )


class _DeferredAsyncContextManager:
    """``async with page.expect_download()`` — built and entered on the host loop."""

    __slots__ = (
        "_bf695_factory", "_bf695_args", "_bf695_kwargs",
        "_bf695_host", "_bf695_cm",
    )

    def __init__(
        self,
        factory: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        host: PlaywrightLoopHost,
    ) -> None:
        self._bf695_factory = factory
        self._bf695_args = args
        self._bf695_kwargs = kwargs
        self._bf695_host = host
        self._bf695_cm: Any = None

    async def __aenter__(self) -> Any:
        host = self._bf695_host

        async def _enter() -> Any:
            cm = self._bf695_factory(*self._bf695_args, **self._bf695_kwargs)
            self._bf695_cm = cm
            return await cm.__aenter__()

        return _wrap_result(await host.run(_enter), host)

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        cm = self._bf695_cm
        if cm is None:
            return False

        async def _exit() -> Any:
            return await cm.__aexit__(exc_type, exc, tb)

        return await self._bf695_host.run(_exit)

    def __repr__(self) -> str:
        return "<BF-695 deferred host-bound async context manager>"
