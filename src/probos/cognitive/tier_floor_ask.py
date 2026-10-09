"""AD-1324: the chain-of-command ask filed when no model exists at the stakes floor.

Composes the existing ``kind="continue"`` request; it adds no request kind, schema
or approval path. The rationale is built from closed tokens and integers only, never
from model-produced text. Authority routes capability: the agent escalates to the
chain of command rather than answering with a refusal or silently downgrading.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from probos.capability_request import RATIONALE_MAX_CHARS, store_canonical_rationale
from probos.cognitive.continue_or_ask import (
    CONTINUE_REQUEST_KIND,
    _park_work_item,
    _task_excerpt,
    continue_payload,
    file_continue_request,
)

logger = logging.getLogger(__name__)

_STAKES_TOKENS = frozenset({"low", "moderate", "high", "severe"})
_TIER_TOKENS = frozenset({"fast", "standard", "deep"})
_PROVENANCE_TOKENS = frozenset(
    {"captain", "agent_captain_confirmed", "agent_chain_confirmed", "agent_unconfirmed", "unrecorded"}
)


def _token(value: object, allowed: frozenset[str], default: str) -> str:
    return value if type(value) is str and value in allowed else default


# Closed vocabulary: refusal-cause token -> fixed sentence. No model text can reach a card.
# "floor_unmet", None and any unknown token keep the legacy text, so pending asks still join.
# A cause-bearing ask uses a compact template: the store keeps only RATIONALE_MAX_CHARS (280), and the
# legacy text plus a sentence would be cut mid-sentence and could never be joined again.
_CAUSE_REASONS = {
    "ceiling": "the configured cost ceiling excludes every model at or above that tier",
    "exact_unavailable": "the tier chosen for the step could not serve the request",
    "ineligible": "the request exceeds what the available model at that tier accepts",
    "redo_floor_unmet": "a sub-floor answer was re-issued at the floor and still could not be served",
    "route_unverifiable": "the model route for the step could not be verified",
}

_RATIONALE_TEMPLATE = (
    "No available model at or above the '{floor}' tier for work with {stakes} stakes "
    "(source: {source}). The run stopped after {tried} model step(s) rather than answer from a "
    "lower tier. Please make a model at that tier available, or approve and decide how this "
    "should proceed."
)


_CAUSE_TEMPLATE = (
    "No model at or above the '{floor}' tier for {stakes} stakes (source: {source}). Cause: {reason}. "
    "Stopped after {tried} step(s). Make a model at that tier available, or decide how to proceed."
)


def _template(cause: str | None) -> str:
    """The rationale template for ``cause``: the legacy one unless the cause has a closed sentence."""
    reason = _CAUSE_REASONS.get(cause) if type(cause) is str else None
    return _CAUSE_TEMPLATE.replace("{reason}", reason) if reason else _RATIONALE_TEMPLATE


def tier_floor_rationale(
    *, floor: str, stakes: str | None, stakes_provenance: str | None, tried: int, cause: str | None = None,
) -> str:
    """The ask text: closed tokens and one integer, so no model text can reach a card."""
    return _template(cause).format(
        floor=_token(floor, _TIER_TOKENS, "unknown"),
        stakes=_token(stakes, _STAKES_TOKENS, "unrecorded"),
        source=_token(stakes_provenance, _PROVENANCE_TOKENS, "unrecorded"),
        tried=max(0, int(tried)),
    )


def tier_floor_target(floor: str, display: str) -> str:
    """The request target of a tier-floor ask: the stable identity the join matches on.

    Identical to what ``file_continue_request`` builds from ``display_task_text`` of
    ``tier floor [<floor>]: <display>``, so the parked and unparked paths store the same string.
    """
    floor_token = _token(floor, _TIER_TOKENS, "unknown")
    return f"continue: {_task_excerpt(f'tier floor [{floor_token}]: {display}')}"


def _rationale_pattern(floor: str, cause: str | None = None) -> re.Pattern[str]:
    """The exact rationale template for ``floor`` and ``cause`` with its tokens and integer left open."""
    text = _template(cause).format(
        floor=_token(floor, _TIER_TOKENS, "unknown"), stakes="STAKESX", source="SOURCEX", tried="TRIEDX",
    )
    body = re.escape(text)
    body = body.replace("STAKESX", "(?:" + "|".join(sorted(_STAKES_TOKENS | {"unrecorded"})) + ")")
    body = body.replace("SOURCEX", "(?:" + "|".join(sorted(_PROVENANCE_TOKENS)) + ")")
    body = body.replace("TRIEDX", r"[0-9]{1,9}")
    return re.compile(body)


def _truncated_pattern(floor: str, cause: str | None) -> re.Pattern[str]:
    """The template up to the tried integer, with named groups for the tokens: all the store kept of a long render."""
    text = _template(cause).format(
        floor=_token(floor, _TIER_TOKENS, "unknown"), stakes="STAKESX", source="SOURCEX", tried="TRIEDX",
    )
    body = re.escape(text.split("TRIEDX", 1)[0])
    body = body.replace("STAKESX", "(?P<stakes>" + "|".join(sorted(_STAKES_TOKENS | {"unrecorded"})) + ")")
    body = body.replace("SOURCEX", "(?P<source>" + "|".join(sorted(_PROVENANCE_TOKENS)) + ")")
    return re.compile(body + r"(?P<tried>[0-9]{1,9})")


def _matches_template(floor: str, cause: str | None, stored: str) -> bool:
    """Whether ``stored`` is a tier-floor rationale for ``floor`` and ``cause`` as the store keeps it.

    A text shorter than the store limit was never cut, so it must match the whole template. A text at the
    limit may have been cut: it matches only if it equals the store-canonical form of a full render of
    this same template, so only the tail the store never kept is left unchecked.
    """
    if len(stored) < RATIONALE_MAX_CHARS:
        return _rationale_pattern(floor, cause).fullmatch(stored) is not None
    if len(stored) > RATIONALE_MAX_CHARS:
        return False
    found = _truncated_pattern(floor, cause).match(stored)
    if found is None:
        return False
    rendered = tier_floor_rationale(
        floor=floor, stakes=found["stakes"], stakes_provenance=found["source"],
        tried=int(found["tried"]), cause=cause,
    )
    return stored == store_canonical_rationale(rendered)

async def file_tier_floor_request(
    runtime: Any,
    *,
    agent_id: str,
    thread_id: str,
    work_item_id: str | None,
    floor: str,
    stakes: str | None,
    stakes_provenance: str | None,
    tried: int,
    display_task_text: str = "",
    park: bool = True,
    parked: dict[str, str] | None = None,
    cause: str | None = None,
) -> str:
    """File the ask (or join the pending one for this agent, item and floor); returns its id or ``""``. Never raises.

    ``park=True`` (a promoted DM turn) parks the linked item blocked through the
    existing continue path, so an approval resumes it. ``park=False`` (a crew child,
    whose terminal state is owned elsewhere) files the linked ask without parking.
    """
    rationale = tier_floor_rationale(
        floor=floor, stakes=stakes, stakes_provenance=stakes_provenance, tried=tried, cause=cause,
    )
    store = getattr(runtime, "capability_request_store", None)
    lock = getattr(store, "gap_filing_lock", None)
    if store is None or lock is None:
        logger.warning(
            "AD-1324: no capability-request store with a filing lock is wired, so the tier-floor ask "
            "for agent %s could not be filed; the run has already stopped without a lower-tier answer",
            agent_id[:12],
        )
        return ""
    async with lock:
        existing = await _pending_floor_ask(store, agent_id, work_item_id, thread_id, floor, cause)
        if existing:
            if parked is not None and park and work_item_id and await _verify_parked(runtime, work_item_id, existing):
                parked["request_id"] = existing
            return existing
        return await _file_floor_ask(
            runtime, store, agent_id=agent_id, thread_id=thread_id, work_item_id=work_item_id,
            floor=floor, rationale=rationale, tried=tried, display_task_text=display_task_text,
            park=park, parked=parked,
        )


async def _verify_parked(runtime: Any, work_item_id: str, request_id: str) -> bool:
    """Whether the item is parked ``blocked`` on ``request_id``, repairing a failed earlier park.

    An item still ``in_progress`` was never parked (the earlier park failed), so approving the
    ask would resume nothing: it is parked now. Parked on another request, absent, or
    in any other state is NOT claimed. Never raises.
    """
    try:
        work_items = getattr(runtime, "work_item_store", None)
        item = await work_items.get_work_item(work_item_id) if work_items is not None else None
        if item is None:
            return False
        status = getattr(item, "status", None)
        if status == "blocked":
            if (getattr(item, "metadata", None) or {}).get("capability_request_id") == request_id:
                return True
            logger.warning(
                "AD-1324: work item %s is blocked on a different request than tier-floor ask %s; "
                "it is not reported as parked on this ask", work_item_id, request_id[:12],
            )
            return False
        if status == "in_progress":
            return bool(await _park_work_item(runtime, work_item_id=work_item_id, request_id=request_id))
        return False
    except Exception:
        logger.warning(
            "AD-1324: could not verify work item %s is parked on tier-floor ask %s; it is not "
            "reported as parked", work_item_id, request_id[:12], exc_info=True,
        )
        return False


async def _pending_floor_ask(
    store: Any, agent_id: str, work_item_id: str | None, thread_id: str, floor: str, cause: str | None = None,
) -> str:
    """The id of a pending tier-floor ask for this agent, item (else thread) and floor, or ``""``.

    Identity is the target prefix AND the exact rationale template, so an ordinary continue
    request that merely quotes the rationale is never joined.
    """
    target_prefix = f"continue: tier floor [{_token(floor, _TIER_TOKENS, 'unknown')}]"
    try:
        pending = await store.list_pending()
    except Exception:
        logger.warning("AD-1324: could not list pending requests for agent %s; filing a new tier-floor ask", agent_id[:12], exc_info=True)
        return ""
    for req in pending:
        if getattr(req, "kind", None) != CONTINUE_REQUEST_KIND or getattr(req, "agent_id", None) != agent_id:
            continue
        if not str(getattr(req, "target", "") or "").startswith(target_prefix):
            continue
        if not _matches_template(floor, cause, str(getattr(req, "rationale", "") or "")):
            continue
        item = getattr(req, "work_item_id", None)
        payload = getattr(req, "payload", None) or {}
        same = item == work_item_id if work_item_id else (not item and payload.get("thread_id") == thread_id)
        if same:
            return str(req.id)
    return ""


async def _file_floor_ask(
    runtime: Any, store: Any, *, agent_id: str, thread_id: str, work_item_id: str | None,
    floor: str, rationale: str, tried: int, display_task_text: str, park: bool,
    parked: dict[str, str] | None,
) -> str:
    if park:
        return await file_continue_request(
            runtime,
            agent_id=agent_id,
            thread_id=thread_id,
            base_task_text="tier floor",
            passes=max(1, int(tried)),
            display_task_text=f"tier floor [{_token(floor, _TIER_TOKENS, 'unknown')}]: {display_task_text}",
            work_item_id=work_item_id,
            rationale=rationale,
            parked=parked,
        )
    try:
        request = await store.file_request(
            agent_id=agent_id,
            kind=CONTINUE_REQUEST_KIND,
            target=tier_floor_target(floor, display_task_text),
            rationale=rationale,
            work_item_id=work_item_id,
            payload=continue_payload(thread_id),
        )
    except Exception:
        logger.warning(
            "AD-1324: filing the tier-floor ask for agent %s failed; the run has already "
            "stopped without a lower-tier answer", agent_id[:12], exc_info=True,
        )
        return ""
    request_id = getattr(request, "id", "")
    return request_id if type(request_id) is str else ""
