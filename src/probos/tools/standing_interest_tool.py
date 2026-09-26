"""AD-1228 (#1201): the ``standing_interest`` tool -- register, list or revoke a standing interest.

Follows the AD-1209 duck-typed ``Tool`` protocol and never raises out of
``invoke``: every miss is an honest receipt the loop can reason over. Listing
works at every rank; registering and revoking need ``write``, which the default
matrix grants from Lieutenant, because notices arrive in proactive thinking and
proactive thinking starts at Lieutenant.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.cognitive.standing_interest_store import KINDS
from probos.cognitive.standing_interests import (
    DELIVERY_TEXT,
    REASON_OFFLINE,
    REASON_REVOKE,
    REASON_TTL,
    StandingInterestService,
    format_utc,
)
from probos.tools.protocol import ToolResult, ToolType, refuse_undeclared_params

logger = logging.getLogger(__name__)

STANDING_INTEREST_TOOL_DEFAULT_PERMISSIONS: dict[str, str] = {
    "ensign": "read",
    "lieutenant": "write",
    "commander": "write",
    "senior_officer": "write",
}
ACTIONS: tuple[str, ...] = ("register", "list", "revoke")
_WRITE_PERMISSIONS: frozenset[str] = frozenset({"write", "full"})

# Model-facing text (contract P-I). Every string is clean against the
# decomposer's capability-gap pattern (test T5).
REASON_RANK = (
    "registering starts at Lieutenant, because notices arrive in proactive thinking, which starts "
    "at Lieutenant; list works at every rank"
)
REASON_ACTION = "action must be one of: " + ", ".join(ACTIONS)
REASON_NO_AGENT = "the caller's identity is unknown, so nothing was registered, listed or revoked"
REASON_OFFLINE_LIST = "standing interests are offline right now; nothing was listed"
REASON_OFFLINE_REVOKE = "standing interests are offline right now; nothing was revoked"
_DESCRIPTION = (
    "Register, list or revoke a standing interest: a declared condition you want to be told about "
    "when it becomes true, so you do not have to keep checking. Kinds: work_item_finished (one of "
    "your own tasks reaches a final state; subject is its id), trust_falling (another crew member's "
    "trust is on a significant downward trend; subject is their callsign or id), self_similarity_high "
    "(another crew member's recent posts have become repetitive; subject is their callsign or id). "
    "The two crew-member kinds are clinical indicators: they are open to the Counselor and to holders "
    "of a Captain-issued clinical grant, and the crew member is told that you registered one. When a "
    "condition becomes true you receive a SYSTEM NOTE in your next proactive think. Registrations "
    "expire (24 hours unless you ask for longer, up to a ceiling) and there is a per-agent limit. "
    "Registering and revoking start at Lieutenant; listing works at every rank and also shows who "
    "holds an interest in you."
)


class StandingInterestTool:
    """AD-1228: one tool, three actions, over a :class:`StandingInterestService`."""

    def __init__(self, *, service: StandingInterestService) -> None:
        self._service = service

    # ── Tool protocol ─────────────────────────────────────────────
    @property
    def tool_id(self) -> str:
        return "standing_interest"

    @property
    def name(self) -> str:
        return "Standing Interest"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": list(ACTIONS),
                    "description": (
                        "register a new standing interest, list the ones you hold and the ones held "
                        "about you, or revoke one by its registration_id"
                    ),
                },
                "kind": {
                    "type": "string",
                    "enum": sorted(KINDS),
                    "description": "register only: which condition to follow",
                },
                "subject": {
                    "type": "string",
                    "description": (
                        "register only: for work_item_finished, one of your own task ids (a prefix of "
                        "at least 8 characters works); for the other kinds, a crew member's callsign or id"
                    ),
                },
                "ttl_hours": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "register only: how many hours the interest lasts; the default applies when "
                        "omitted, and a longer request is clamped to the ceiling"
                    ),
                },
                "registration_id": {
                    "type": "string",
                    "description": "revoke only: the registration_id that register or list returned",
                },
            },
            "required": ["action"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    # ── Execution ─────────────────────────────────────────────────
    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        t0 = time.monotonic()
        # AD-1179: an undeclared key (a "condition" string, say) is refused, never ignored.
        refusal = refuse_undeclared_params(self, params)
        if refusal is not None:
            return refusal
        ctx = context or {}
        agent_id = str(ctx.get("agent_id") or "")
        context_permission = str(ctx.get("permission") or "")
        raw = params if isinstance(params, dict) else {}
        action = raw.get("action")
        wanted = raw.get("registration_id")
        registration_id = wanted if isinstance(wanted, str) else ""

        def _done(output: dict[str, Any]) -> ToolResult:
            return ToolResult(
                output=output, error=None, duration_ms=(time.monotonic() - t0) * 1000.0,
            )

        if not agent_id:
            # An anonymous caller is not a wildcard: nothing is registered, listed or revoked.
            return _done({"reason": REASON_NO_AGENT})
        if action not in ACTIONS:
            return _done({"reason": REASON_ACTION})
        if action != "list":
            if context_permission not in _WRITE_PERMISSIONS:
                if action == "register":
                    return _done({"registered": False, "reason": REASON_RANK})
                return _done({"revoked": False, "registration_id": registration_id[:64], "reason": REASON_RANK})
        try:
            if action == "list":
                return _done(self._service.describe(agent_id))
            if action == "register":
                return _done(await self._register(agent_id, raw))
            return _done(await self._revoke(agent_id, registration_id))
        except Exception:  # noqa: BLE001 -- a store fault must not fail the turn
            logger.warning(
                "AD-1228: standing_interest %s by %s failed; the agent receives an offline receipt "
                "and the turn continues",
                action, agent_id[:32], exc_info=True,
            )
            if action == "list":
                return _done({"reason": REASON_OFFLINE_LIST})
            if action == "register":
                return _done({"registered": False, "reason": REASON_OFFLINE})
            return _done({"revoked": False, "registration_id": registration_id[:64], "reason": REASON_OFFLINE_REVOKE})

    # ── Internals ─────────────────────────────────────────────────
    async def _register(self, agent_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        ttl = raw.get("ttl_hours")
        if ttl is not None and (type(ttl) is not int or ttl < 1):
            return {"registered": False, "reason": REASON_TTL}
        outcome = await self._service.register(
            holder_id=agent_id, kind=raw.get("kind"), subject=raw.get("subject"), ttl_hours=ttl,
        )
        if not outcome.registered or outcome.record is None:
            return {"registered": False, "reason": outcome.reason}
        record = outcome.record
        return {
            "registered": True,
            "registration_id": record.id,
            "kind": record.kind,
            "subject": outcome.subject_label,
            "expires_at_utc": format_utc(record.expires_at),
            "renewed": outcome.renewed,
            "clamped": outcome.clamped,
            "delivery": DELIVERY_TEXT,
        }

    async def _revoke(self, agent_id: str, registration_id: str) -> dict[str, Any]:
        if await self._service.revoke(holder_id=agent_id, registration_id=registration_id):
            return {"revoked": True, "registration_id": registration_id}
        return {"revoked": False, "registration_id": registration_id[:64], "reason": REASON_REVOKE}
