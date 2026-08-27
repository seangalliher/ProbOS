"""AD-1274: redeliver promoted-run reports that ``chat_threads.db`` refused.

``turn_promotion._post_report`` posts a promoted run's report into the thread
the request came from. When that write fails past its bounded retry the report
is not lost -- it is written to ``promoted_report_outbox`` in ``workforce.db``,
a different file behind a different lock, because an error path must not fail
the way the thing it reports on failed.

This service is what turns "preserved" into "retried". Without a drainer the
row is a durable grave.

**Exactly-once is inherited, not implemented here.** Every row carries the
``message_id`` and ``created_at`` the reporter minted for its first attempt, and
redelivery replays them verbatim through ``ChatThreadStore.append_message_once``.
A row whose original write actually committed -- but whose acknowledgement was
lost -- finds the existing message on its exact-match check and returns it
without inserting. That is why this drainer needs none of the acknowledgement
authority ceremony ``crew_session_delivery`` carries: there, a replayed
notification would be a second notification; here it is a no-op.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Bounded so one pass cannot monopolise the loop or the store lock. A backlog
# larger than this is logged and left for the next trigger.
DEFAULT_PROMOTED_REPORT_DRAIN_LIMIT = 25

PROMOTED_REPORT_SOURCE_KEY = "source"


class PromotedReportDeliveryService:
    """Bounded redelivery of durably pending promoted-run reports."""

    def __init__(
        self,
        *,
        outbox: Any,
        threads: Any,
        drain_limit: int = DEFAULT_PROMOTED_REPORT_DRAIN_LIMIT,
    ) -> None:
        self._outbox = outbox
        self._threads = threads
        self._drain_limit = int(drain_limit)

    async def drain_pending(self, *, limit: int | None = None) -> int:
        """Attempt one bounded batch. Returns how many rows were delivered.

        A row that fails **stays pending**. That includes the two permanent
        failures -- a thread that no longer exists, and a message the store
        rejects -- which are logged at ERROR and left in place rather than
        marked delivered. Marking them would record a delivery that never
        happened, and the pending count is the only signal an operator has that
        a Captain is owed a report nothing can post.
        """
        bounded_limit = self._drain_limit if limit is None else limit
        if type(bounded_limit) is not int or bounded_limit < 1:
            raise ValueError("promoted_report_outbox_limit_invalid")

        # +1 so a full batch is distinguishable from a backlog.
        entries = await self._outbox.list_pending_promoted_reports(
            limit=bounded_limit + 1,
        )
        if len(entries) > bounded_limit:
            logger.warning(
                "AD-1274: promoted report backlog exceeds the bounded drain "
                "limit=%d; this pass processes only the oldest rows and a "
                "later trigger or startup will retry the remainder",
                bounded_limit,
            )

        delivered = 0
        for entry in entries[:bounded_limit]:
            try:
                message = await asyncio.to_thread(
                    self._threads.append_message_once,
                    entry.thread_id,
                    message_id=entry.message_id,
                    author_id=entry.agent_id,
                    role="agent",
                    body=entry.body,
                    created_at=entry.created_at,
                    metadata={
                        "work_item_id": entry.work_item_id,
                        PROMOTED_REPORT_SOURCE_KEY: _promotion_source(),
                    },
                )
            except asyncio.CancelledError:
                raise
            except ValueError:
                logger.error(
                    "AD-1274: thread %s rejected the pending report for work "
                    "item %s; it can never be delivered, so the row is retired "
                    "as UNDELIVERABLE rather than recorded as delivered",
                    entry.thread_id, entry.work_item_id, exc_info=True,
                )
                await self._retire(entry)
                continue
            except Exception:
                logger.warning(
                    "AD-1274: redelivery of the report for work item %s failed; "
                    "the durable row remains pending and the next bounded drain "
                    "will retry",
                    entry.work_item_id, exc_info=True,
                )
                continue

            if message is None:
                logger.error(
                    "AD-1274: thread %s no longer exists, so the pending report "
                    "for work item %s has nowhere to land; the row is retired "
                    "as UNDELIVERABLE rather than recorded as delivered",
                    entry.thread_id, entry.work_item_id,
                )
                await self._retire(entry)
                continue

            try:
                await self._outbox.mark_promoted_report_delivered(
                    entry.message_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                # Safe to leave pending: the next pass replays the same
                # message_id, the store recognises it, and nothing is posted
                # twice. That is the whole reason the id is minted once.
                logger.warning(
                    "AD-1274: the report for work item %s was posted but could "
                    "not be marked delivered; the next drain replays the same "
                    "message_id, which the thread store recognises without "
                    "inserting a second copy",
                    entry.work_item_id, exc_info=True,
                )
                continue
            delivered += 1

        return delivered

    async def _retire(self, entry: Any) -> None:
        """Take a permanently undeliverable row out of the pending set.

        Never raises, and never falls back to marking the row DELIVERED. If
        retirement fails the row simply stays pending: a poison row that keeps
        its place is the bug this method exists to fix, but a false delivery
        record is worse -- the pending count is the only signal an operator has
        that a Captain is owed a report, and a lie there cannot be detected
        later.
        """
        retire = getattr(self._outbox, "mark_promoted_report_undeliverable", None)
        if not callable(retire):
            logger.warning(
                "AD-1274: this outbox cannot retire undeliverable rows, so the "
                "report for work item %s stays pending and will be retried on "
                "every drain",
                entry.work_item_id,
            )
            return
        try:
            await retire(entry.message_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "AD-1274: could not retire the undeliverable report for work "
                "item %s; it stays pending and the next drain will retry it",
                entry.work_item_id, exc_info=True,
            )


def _promotion_source() -> str:
    """The metadata tag a first-attempt post uses, so a redelivery matches it.

    Imported lazily: ``turn_promotion`` pulls in the reply pipeline, and this
    module is constructed during startup wiring where that import order is not
    guaranteed.
    """
    from probos.cognitive.turn_promotion import PROMOTION_SOURCE

    return PROMOTION_SOURCE
