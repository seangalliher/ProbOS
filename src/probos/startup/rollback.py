"""Roll back a ``ProbOSRuntime.start()`` that failed or was cancelled (BF-882, #1419 G-2).

``start()`` has no unwind. A boot that raises halfway leaves everything it started
running: the Phase-1 aiosqlite workers (non-daemon, so the interpreter cannot exit),
every pool and agent, the loops, the YeomanAgent singleton slot (the next boot in the
process raises the AD-766 error), and, when the failure is the ``started`` event-log row,
``_started`` already True.

``rollback_on_failed_start`` decorates ``ProbOSRuntime.start`` and runs the production
teardown (``startup.shutdown.shutdown`` with ``rollback=True``) when the body raises, then
re-raises. The decorator is the only change to ``start``: its body is not moved or edited,
so ``inspect.getsource(ProbOSRuntime.start)`` still reads the body (six tests rely on it).
The owned teardown includes any Phase-1 protected-execution authority, so a later
startup failure closes its witness through the same ordered lifecycle.

Module-level imports are the standard library only: ``runtime`` imports this module, and
the teardown module imports back from the runtime package.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)

START_FAILED_MESSAGE = (
    "BF-882: start() already failed and was rolled back; construct a new ProbOSRuntime"
)
ROLLBACK_TASK_NAME = "bf882-startup-rollback"


def rollback_on_failed_start(
    start: Callable[[ProbOSRuntime], Awaitable[None]],
) -> Callable[[ProbOSRuntime], Awaitable[None]]:
    """Wrap ``ProbOSRuntime.start`` so that a start which raises is rolled back first.

    A runtime whose start failed cannot start again: the rollback released what the
    boot had built, and nothing rebuilds it. ``GeneratorExit`` is passed through
    untouched, because a coroutine that is being closed cannot await a teardown.
    """

    @functools.wraps(start)
    async def start_with_rollback(self: ProbOSRuntime) -> None:
        if getattr(self, "_start_failed", False):
            raise RuntimeError(START_FAILED_MESSAGE)
        try:
            await start(self)
        except GeneratorExit:
            raise
        except BaseException as error:
            await rollback_failed_start(self, error)
            raise

    return start_with_rollback


async def rollback_failed_start(runtime: ProbOSRuntime, error: BaseException) -> None:
    """Tear down everything a failed or cancelled ``start()`` started; never raises the failure.

    The runtime is flagged first, so nothing that runs during the teardown, or after it,
    treats it as startable. The teardown runs in a task of its own: a cancelled start task
    keeps a positive cancel count, which would otherwise leak into every ``asyncio.timeout``
    and cancellation check the teardown makes. If the task awaiting this is cancelled, it
    keeps waiting for the same teardown rather than abandoning it half done (the BF-663
    pattern), and raises the ``CancelledError`` once it has finished. A teardown that
    itself raises is logged, not re-raised: the original failure is what the caller needs.
    """
    runtime._start_failed = True
    started_at = time.monotonic()
    if isinstance(error, Exception):
        logger.error(
            "BF-882: start() failed (%s: %s); rolling back everything the partial boot "
            "started so the process can exit and a new runtime can boot. The runtime "
            "cannot be started again, and the original error is re-raised.",
            type(error).__name__, error, exc_info=error,
        )
    else:
        logger.warning(
            "BF-882: start() was interrupted (%s); rolling back everything the partial "
            "boot started so the process can exit and a new runtime can boot. The "
            "runtime cannot be started again.",
            type(error).__name__,
        )

    from probos.startup.shutdown import shutdown

    current = asyncio.current_task()
    cancelling_at_entry = current.cancelling() if current is not None else 0
    rollback_task = asyncio.create_task(
        shutdown(runtime, reason="startup_failed", rollback=True),
        name=ROLLBACK_TASK_NAME,
    )
    outer_cancellation: asyncio.CancelledError | None = None
    try:
        while not rollback_task.done():
            try:
                await asyncio.shield(rollback_task)
            except asyncio.CancelledError as cancelled:
                # Either this task was cancelled (its count rose: keep waiting) or the
                # rollback task itself ended cancelled (done() ends the loop).
                if (
                    outer_cancellation is None
                    and current is not None
                    and current.cancelling() > cancelling_at_entry
                ):
                    outer_cancellation = cancelled
            except Exception:
                pass  # the rollback failed; its outcome is read from the task below
        try:
            rollback_task.result()
        except asyncio.CancelledError:
            logger.warning(
                "BF-882: the startup rollback was itself cancelled; whatever it had not "
                "yet released stays held until the process exits."
            )
        except Exception:
            logger.exception(
                "BF-882: the startup rollback raised; the components it had not yet "
                "stopped stay running until the process exits. The start() failure is "
                "still raised."
            )
    finally:
        runtime._started = False
        logger.info(
            "BF-882: startup rollback finished in %.2fs", time.monotonic() - started_at,
        )
    if outer_cancellation is not None:
        raise outer_cancellation
