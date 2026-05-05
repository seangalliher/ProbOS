"""AD-459b: SheddableSubsystem Protocol + LifecycleAdapter helper.

The Protocol defines the contract DegradationManager invokes on tier-mask
transitions: ``async pause()`` when the subsystem's tier enters the shed
mask, ``async resume()`` when it leaves. Both methods MUST be idempotent.

The LifecycleAdapter wraps existing ``start()`` / ``stop()`` methods
(sync or async) so subsystems do not need to learn the Protocol. Adoption
is one-line at finalize time:

    runtime.degradation_manager.register_subsystem(
        "dream_scheduler",
        LifecycleAdapter(
            "dream_scheduler",
            on_pause=runtime.dream_scheduler.stop,
            on_resume=runtime.dream_scheduler.start,
        ),
    )
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class SheddableSubsystem(Protocol):
    """Contract for subsystems that can be paused/resumed by DegradationManager.

    Both methods MUST be idempotent. Calling ``pause()`` on an already-paused
    subsystem MUST be a no-op (not an error). Same for ``resume()``.
    """

    async def pause(self) -> None: ...

    async def resume(self) -> None: ...


class LifecycleAdapter:
    """Adapts existing ``start()`` / ``stop()`` callables to SheddableSubsystem.

    Both ``on_pause`` and ``on_resume`` may be sync or async callables.
    Dispatch uses ``asyncio.iscoroutinefunction(...)`` (BF-254 pattern).

    Tracks an internal ``_paused`` bool to enforce idempotency: pause() on
    a paused subsystem is a no-op + DEBUG log; resume() on a running
    subsystem is a no-op + DEBUG log.
    """

    def __init__(
        self,
        name: str,
        *,
        on_pause: Callable[[], Any],
        on_resume: Callable[[], Any],
    ) -> None:
        self._name = name
        self._on_pause = on_pause
        self._on_resume = on_resume
        self._paused = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_paused(self) -> bool:
        return self._paused

    async def pause(self) -> None:
        if self._paused:
            logger.debug("AD-459b: %s already paused; no-op", self._name)
            return
        await self._invoke(self._on_pause)
        self._paused = True

    async def resume(self) -> None:
        if not self._paused:
            logger.debug("AD-459b: %s already running; no-op", self._name)
            return
        await self._invoke(self._on_resume)
        self._paused = False

    @staticmethod
    async def _invoke(callable_: Callable[[], Any]) -> None:
        if asyncio.iscoroutinefunction(callable_):
            await callable_()
        else:
            callable_()
