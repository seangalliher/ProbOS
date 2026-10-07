"""BF-885 (#1468): identity.db's units of work -- each writer's statements and their commit, one unit at a time.

identity.db's writers -- the identity registry and its key binding -- share one aiosqlite connection, and Python's
sqlite3 keeps one transaction per connection. With no lock common to them, one writer's commit carried another's
pending statements, a writer that failed left its own for the next commit, and SQLite's rollback of a full disk
discarded every writer's. A unit holds the writer lock from before its first statement until its commit or rollback has
ended, so its transaction holds its own statements only: they commit together, or they are rolled back and nothing else
with them.

A unit ends -- its commit, then ``committed`` (what memory holds once it has committed), or its rollback -- in a task the
writer owns: aiosqlite completes a COMMIT whose caller was cancelled, so a cancellation of the caller is kept until the
unit has ended and raised then, and memory never parts from what committed. The caller waits for the lock, and for that
end, at most ``IDENTITY_UNIT_SETTLE_S`` each; past it the caller is refused (``IdentityUnitUnsettled``), and a unit still
ending ends all the same, memory following what it committed. A rollback that fails may leave a unit's statements in the
connection's transaction, so every later unit is refused until a restart.

Amendment A-1: a caller that stops waiting releases the locks it held while its unit may still commit, so until that
unit has ended the writer admits nothing -- no unit, no read -- and refuses at once, as the envelope store refuses while
one of its writes is unsettled (AD-1198 A-2); once it has ended, memory holds what it committed and units are admitted
again. Callers derive inside the unit, once admitted -- when no other unit has a statement pending -- every value their
statements depend on that another unit could change: a ledger tip, a key event's block, a stored chain. ``read`` sees
committed state only, admitted as a unit is. An end cancelled before its commit or
rollback is known to have ended -- the event loop's teardown cancels it -- may leave its statements pending, or committed
without ``committed``, so it latches the writer as a failed rollback does.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

logger = logging.getLogger(__name__)

IDENTITY_UNIT_SETTLE_S = 6.0  # BF-885 SQLite's 5 s busy timeout bounds a COMMIT that waits for another connection; the margin is the envelope store's (AD-1198 A-2)
_END_TASK_NAME = "bf885-identity-unit-end"


class UnitConnection(Protocol):
    """What a unit needs of identity.db's connection (aiosqlite's): ``rollback`` does nothing when SQLite has already
    rolled the transaction back, as it does on a full disk, where a ``ROLLBACK`` statement would fail."""

    def execute(self, sql: str, parameters: Any = ...) -> Any: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class IdentityUnitUnsettled(RuntimeError):
    """BF-885: a unit of identity.db that was not run, or whose outcome is not known when its caller stops waiting."""


def _ended_late(ending: asyncio.Task[BaseException | None]) -> None:
    """BF-885: once a unit whose caller stopped waiting at the bound has ended, say how; memory follows what committed."""
    if ending.cancelled():
        logger.warning(
            "BF-885: a unit of identity.db whose caller stopped waiting for it has ended: its end was cancelled before "
            "its outcome was known, so identity.db refuses every write until a restart",
        )
        return
    failure = ending.exception() or ending.result()
    outcome = "it committed" if failure is None else f"it did not commit ({type(failure).__name__})"
    logger.warning(
        "BF-885: a unit of identity.db whose caller stopped waiting for it has ended: %s; memory holds what committed",
        outcome,
    )


class IdentityWriter:
    """BF-885: identity.db's writes, one unit at a time, on the registry's connection -- ``connection()``, read at each
    unit, ``None`` once the registry has stopped -- or on a connection of the caller's own; and reads of what committed."""

    def __init__(self, connection: Callable[[], UnitConnection | None]) -> None:
        self._connection = connection
        self._lock = asyncio.Lock()
        self._ending: asyncio.Task[BaseException | None] | None = None  # BF-885 the newest unit's end, owned until it has ended
        self._unsettled: asyncio.Task[BaseException | None] | None = None  # BF-885 A-1 the end of a unit whose caller stopped waiting
        self._broken = ""  # BF-885 why every unit is refused until a restart; empty while none is

    @contextlib.asynccontextmanager
    async def unit(
        self, committed: Callable[[], object] | None = None, *, connection: UnitConnection | None = None,
    ) -> AsyncIterator[UnitConnection]:
        """One unit of work: the body's statements on the connection it is given, then their commit and ``committed`` --
        or, when the body raises, their rollback and the body's exception. ``connection`` is a connection of the caller's
        own (AD-1198 slice 2c's deletion); the registry's otherwise. Raises ``IdentityUnitUnsettled`` at once while a unit
        whose caller stopped waiting has not ended (A-1), when the lock or the unit's end outlasts
        ``IDENTITY_UNIT_SETTLE_S`` or writes are refused, the commit's failure once the unit has been rolled back, and a
        cancellation of the caller once the unit has ended.
        """
        db = connection if connection is not None else self._connection()
        if db is None:  # BF-885 as every writer of a registry not started: nothing is written
            raise RuntimeError("identity.db is not open: the identity registry is not started")
        await self._admitted()  # BF-885 A-1 a unit is admitted only while no unit is unsettled
        ran = False
        try:
            yield db
            ran = True
        finally:
            await self._end(db, ran, committed)

    @contextlib.asynccontextmanager
    async def read(self) -> AsyncIterator[None]:
        """BF-885 A-1: a read of what committed -- admitted as a unit is, so no unit has a statement pending while it
        reads -- that commits and rolls back nothing; the lock is released when the read ends, however it ends."""
        await self._admitted()  # BF-885 A-1 a read is admitted as a unit is
        try:
            yield
        finally:
            self._lock.release()  # BF-885 A-1 a read holds the lock for its own reads only

    async def _admitted(self) -> None:
        """Take the writer lock for a unit or a read: refused at once while a unit whose caller stopped waiting has not
        ended, after ``IDENTITY_UNIT_SETTLE_S`` while an earlier unit holds the lock, and while writes are refused."""
        unsettled = self._unsettled
        if unsettled is not None and not unsettled.done():  # BF-885 A-1 fail closed while a unit's outcome is unknown
            raise IdentityUnitUnsettled(
                "identity.db: a unit whose caller stopped waiting for it has not ended; nothing is admitted until it has",
            )
        self._unsettled = None
        try:
            async with asyncio.timeout(IDENTITY_UNIT_SETTLE_S):  # BF-885 a unit waits for an earlier one's end at most the bound
                await self._lock.acquire()
        except TimeoutError:
            raise IdentityUnitUnsettled(
                f"identity.db: an earlier unit has not ended within {IDENTITY_UNIT_SETTLE_S:g} s; nothing was written",
            ) from None
        if self._broken:  # BF-885 a transaction that may hold another unit's statements is never committed
            self._lock.release()
            raise IdentityUnitUnsettled(f"identity.db refuses every write until a restart: {self._broken}")

    async def _end(self, db: UnitConnection, commit: bool, committed: Callable[[], object] | None) -> None:
        """End the unit in a task of its own and wait for that end, whatever happens to the caller, at most the bound."""
        ending = asyncio.create_task(self._ended(db, commit, committed), name=_END_TASK_NAME)
        ending.add_done_callback(self._released)  # BF-885 A-1 the lock is released once the end is done, however it ended
        self._ending = ending
        loop = asyncio.get_running_loop()
        deadline = loop.time() + IDENTITY_UNIT_SETTLE_S
        cancelled: asyncio.CancelledError | None = None
        while not ending.done() and loop.time() < deadline:
            try:
                await asyncio.wait({ending}, timeout=deadline - loop.time())  # BF-885 a wait that never cancels the end
            except asyncio.CancelledError as exc:
                cancelled = cancelled or exc  # BF-885 the caller's cancellation is kept, and raised once the unit has ended
        if not ending.done():
            self._unsettled = ending  # BF-885 A-1 nothing is admitted until it has ended
            ending.add_done_callback(_ended_late)
            logger.error(
                "BF-885: a unit of identity.db has not ended within %g s; whether it commits is not known yet, so its "
                "caller is refused, nothing else is admitted until it ends, and memory then follows what it committed",
                IDENTITY_UNIT_SETTLE_S,
            )
            if cancelled is not None:
                raise cancelled
            raise IdentityUnitUnsettled(
                f"identity.db: the unit has not ended within {IDENTITY_UNIT_SETTLE_S:g} s; whether it committed is not known",
            )
        if cancelled is not None:
            raise cancelled
        failure = ending.result()  # BF-885 an end that raised (its rollback failed) raises here
        if failure is not None:
            raise failure

    def _released(self, ending: asyncio.Task[BaseException | None]) -> None:
        """BF-885 A-1: once a unit's end is done, release the lock -- first latching the writer when the end was cancelled
        before its commit or rollback was known to have ended: its statements may be pending, or committed without
        ``committed``, so no later unit may commit them or read through them."""
        if ending.cancelled() and not self._broken:
            self._broken = "a unit's end was cancelled before its outcome was known"
            logger.error(
                "BF-885: a unit of identity.db was cancelled while it ended; whether it committed is not known and its "
                "statements may still be pending, so identity.db refuses every write until a restart",
            )
        self._lock.release()  # BF-885 the next unit begins only once this one has ended

    async def _ended(
        self, db: UnitConnection, commit: bool, committed: Callable[[], object] | None,
    ) -> BaseException | None:
        """Commit the unit, then ``committed``; or roll it back. ``None`` once it committed or, as asked, was rolled back;
        the commit's failure once the unit has been rolled back after it. The writer lock is held until this is done."""
        failure: BaseException | None = None
        if commit:
            try:
                await db.commit()
            except Exception as exc:  # noqa: BLE001 -- e.g. SQLITE_BUSY at COMMIT, which leaves the transaction open
                failure = exc
            else:
                if committed is not None:
                    committed()  # BF-885 memory follows exactly what committed, whatever happened to the caller
                return None
        try:
            await db.rollback()  # BF-885 no other unit has a statement pending: this unit's, and only they, are discarded
        except Exception as exc:
            self._broken = f"a unit's rollback failed ({type(exc).__name__})"
            logger.error(
                "BF-885: a unit of identity.db could not be rolled back (%s); its statements may still be pending, so "
                "identity.db refuses every write until a restart",
                type(exc).__name__,
            )
            raise
        return failure

    async def stop(self) -> None:
        """Wait for a unit still ending, at most ``IDENTITY_UNIT_SETTLE_S``: the registry closes the connection next, and
        aiosqlite runs that close only after the unit's commit or rollback."""
        ending = self._ending
        if ending is not None and not ending.done():
            await asyncio.wait({ending}, timeout=IDENTITY_UNIT_SETTLE_S)  # BF-885 the end is owned until it has ended
