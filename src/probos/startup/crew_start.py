"""BF-941 (#1324 slice 4d): whether this boot starts a new crew, and the crew's Fresh Start thread.

``is_new_crew_start`` is the one predicate for a new crew: no previous session record (AD-502's
lifecycle state is ``first_boot``, or ``reset``) and an empty episode store. BF-034's cold-start
detector (``startup/dreaming.py``, Phase 5) and the AD-638 boot-camp enrolment
(``startup/finalize.py``, Phase 8) both ask it. It fails warm, because the two errors are not
alike: a false new crew tells agents their memory is empty, while a false warm start omits the
fresh-start notes and, at finalization, the boot camp's activation.

``announce_fresh_start`` posts BF-034's "Fresh Start" thread to All Hands. Finalization calls it
after the AD-435 startup announcement: at Phase 5 the Ward Room does not exist yet.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# AD-502 lifecycle states with no previous session record. Phase 4 writes ``first_boot`` or
# ``stasis_recovery``; Phase 5 writes ``reset`` for a new crew.
NEW_CREW_LIFECYCLE_STATES: frozenset[str] = frozenset({"first_boot", "reset"})

FRESH_START_TITLE = "Fresh Start — New Crew"
FRESH_START_BODY = (
    "This crew is starting fresh: there is no previous session record and the episode "
    "store is empty. All crew are being created through the Construct. "
    "Each role's trust starts at its initial level; this is normal initialization, "
    "not a demotion, and trust is built through demonstrated competence. "
    "No previous experiences are available."
)


async def is_new_crew_start(lifecycle_state: str, episodic_memory: Any) -> bool:
    """True when this boot starts a new crew: no previous session record and no episodes.

    Fails warm: a session record, a missing memory, an unreadable count, or an answer whose
    ``get("total")`` is not ``== 0`` (``None``, a list, an int, a mapping without ``total``) is
    not a new crew. Trust is not read: AD-640 gives bridge and chief roles their own priors, and
    the default ``probos reset`` tier deletes the trust store with the session record.
    """
    if lifecycle_state not in NEW_CREW_LIFECYCLE_STATES:
        return False  # BF-941: a session record means this crew has served before
    try:
        stats = await episodic_memory.get_stats()
        return stats.get("total") == 0
    except Exception:  # BF-941: no memory, or an unreadable or malformed answer, is not a new crew
        logger.debug("BF-941: episode count unavailable or malformed; not treated as a new crew", exc_info=True)
        return False


async def announce_fresh_start(ward_room: Any) -> bool:
    """BF-034 / BF-941: post the Fresh Start thread to All Hands; True when it was posted.

    Log-and-degrade: a Ward Room failure is logged and startup continues.
    """
    try:
        all_hands = await ward_room.get_channel_by_name("All Hands")
        if not all_hands:
            return False
        await ward_room.create_thread(
            channel_id=all_hands.id,
            author_id="system",
            title=FRESH_START_TITLE,
            body=FRESH_START_BODY,
            author_callsign="Ship's Computer",
            thread_mode="announce",
            max_responders=0,
        )
        return True
    except Exception:  # BF-941: a failed announcement must not fail the boot
        logger.warning("BF-941: the Fresh Start announcement failed; startup continues", exc_info=True)
        return False
