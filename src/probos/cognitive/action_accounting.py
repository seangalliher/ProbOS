"""BF-934 (#1673): the inverse of AD-643b -- the actions a decision intended that nothing carried out.

AD-643b names an action an output took that its triage had not declared. This module names the other half: an action the triage declared (``intended_actions``)
that nothing carried out, so that a decision cannot be lost without a record. A proactive think's triage writes one ``declared`` row where the decision is made
(``record_declared``); the loop that executes the output writes one ``dropped`` row for each intended action nothing carried out, with a reason
(``settle_intended_actions``), and says it in the log. Both are EventLog rows (events.db), so the crew counts them per agent and action and reconciles them
against what Improvement Proposals and Ship's Records hold: ``declared`` = posted + ``dropped``, and a gap is the alarm.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

logger = logging.getLogger(__name__)

#: The EventLog rows this module writes. Best effort: Improvement Proposals and Ship's Records are authoritative for what was posted, and a
#: row that could not be written is logged at WARNING (the write never blocks a think).
CATEGORY = "intended_actions"
DECLARED_EVENT = "declared"
DROPPED_EVENT = "dropped"


@dataclass(frozen=True)
class ActionTag:
    """How the output of a proactive think carries out one tag the ANALYZE prompts offer."""

    evidence: frozenset[str] = frozenset()  # the ``type`` of the entry that records it carried out; empty: not carried out as a block or a post
    suppressed: str = ""  # the ``type`` of the entry that records a deliberate suppression, with its own ``reason``
    how: str = ""  # for a tag with no evidence: what carries it out instead


#: Every tag of analyze.py's two ``intended_actions`` vocabularies; tests/test_bf934_s3_intended_actions_ledger.py pins the set equal to the prompts'.
ACTION_TAGS: Mapping[str, ActionTag] = MappingProxyType({
    "ward_room_post": ActionTag(frozenset({"ward_room_post"})),
    "ward_room_reply": ActionTag(frozenset({"reply"})),
    "endorse": ActionTag(frozenset({"endorse"})),
    "dm": ActionTag(frozenset({"dm"})),
    "notebook": ActionTag(frozenset({"notebook_write"}), suppressed="notebook_suppressed"),
    "proposal": ActionTag(frozenset({"proposal"}), suppressed="proposal_suppressed"),
    "silent": ActionTag(how="nothing to carry out"),
    "speak_freely": ActionTag(how="a register shift COMPOSE applies (AD-653)"),
    "leadership_review": ActionTag(how="a quality skill the triage loads (AD-643a)"),
    "oracle_query": ActionTag(how="a lookup run between triage and COMPOSE (AD-696)"),
    "ward_room_lookup": ActionTag(how="a lookup run between triage and COMPOSE (AD-1347 S4)"),
})

#: The reasons of an exit taken before the output was read for blocks: they apply to every tag.
PRE_EXTRACTION = frozenset({"think_failed", "no_output", "no_response", "raw_intent_json"})


def _normalised(intended: Iterable[object]) -> list[str]:
    return list(dict.fromkeys(str(tag).strip().lower() for tag in intended))


def intended_tags(intended: Iterable[object]) -> list[str]:
    """The registry's tags among the actions a triage named, each once, in the order named: the one list that the decision record, the result's metadata and the settlement share.

    A tag the registry does not know is left out. It is the model's own word, which S1's billet never repeats either; it has no evidence, so nothing is ever dropped for it
    (``unaccounted``); and keeping it would leave the list as long as the model chose to make it. The list is at most ``len(ACTION_TAGS)`` short strings from a closed set, so no
    recognised action can be pushed out of it and a row that holds it stays far under the EventLog's governed reader's cap of 4096 bytes a row.
    """
    return [tag for tag in _normalised(intended) if tag in ACTION_TAGS]


def unaccounted(intended: Iterable[object], executed: Sequence[Mapping[str, Any]], reason: str) -> list[dict[str, Any]]:
    """The drop entry of each intended action that nothing in *executed* carried out.

    *executed* is what ``ProactiveCognitiveLoop`` recorded (the extractor's entries, and ``{"type": "ward_room_post"}`` once the observation was posted);
    *reason* is why the think ended where it did. A tag with no evidence (``silent``, ``speak_freely``, ...) is never dropped. A tag whose extractor recorded a
    suppression with its own reason keeps that reason; any other block tag that nothing carried out after the output was read is ``no_block_executed``.
    """
    done = {str(entry.get("type", "")) for entry in executed if isinstance(entry, Mapping)}
    drops: list[dict[str, Any]] = []
    for tag in _normalised(intended):
        spec = ACTION_TAGS.get(tag)
        if spec is None or not spec.evidence or done & spec.evidence:
            continue
        drop: dict[str, Any] = {
            "type": "action_dropped", "action": tag,
            "reason": reason if tag == "ward_room_post" or reason in PRE_EXTRACTION else "no_block_executed",
        }
        for entry in executed:
            if spec.suppressed and isinstance(entry, Mapping) and entry.get("type") == spec.suppressed:
                drop["reason"] = str(entry.get("reason") or drop["reason"])
                if spec.suppressed == "notebook_suppressed":
                    drop["by_design"] = True  # AD-550's dedup and AD-552's repetition gate: counted, and only noted
                break
        drops.append(drop)
    return drops


async def record_declared(
    runtime: Any, *, agent_id: str, agent_type: str, callsign: str, intent: str, intent_id: str,
    intended: Sequence[object], path: str,
) -> None:
    """The decision record: one ``declared`` row when a proactive think's triage intends an action that a block or a post carries out."""
    tags = intended_tags(intended)
    log = getattr(runtime, "event_log", None)
    if intent != "proactive_think" or log is None or not any(ACTION_TAGS.get(tag, ActionTag()).evidence for tag in tags):
        return
    try:
        row_id = await log.log(
            category=CATEGORY, event=DECLARED_EVENT, agent_id=agent_id, agent_type=agent_type,
            detail=f"{callsign} intended {', '.join(tags)} ({path})", correlation_id=intent_id or None,
            data={"intended": tags, "path": path, "intent": intent, "intent_id": intent_id, "callsign": callsign},
        )
        if row_id is None:  # an EventLog that is not open returns None, it does not raise
            logger.warning("BF-934: the declared row for %s (%s) was not recorded: the event log returned no row id", callsign, agent_type)
    except Exception:
        logger.warning("BF-934: the declared row for %s (%s) was not recorded", callsign, agent_type, exc_info=True)


async def settle_intended_actions(
    runtime: Any, agent: Any, intent_id: str, metadata: object, executed: Sequence[Mapping[str, Any]], reason: str,
) -> list[dict[str, Any]]:
    """Say, and record, each action the think's triage intended that nothing carried out; return the drop entries.

    *metadata* is the ``IntentResult.metadata`` of the think: it holds ``intended_actions`` only when a triage ran for it, and a think without one has nothing to
    account for. A drop of ``ward_room_post`` (the usual quality gates) or a by-design notebook suppression is logged at INFO; any other drop is a lost decision and
    is logged at WARNING. Nothing here raises.
    """
    intended = metadata.get("intended_actions") if isinstance(metadata, dict) else None
    if not isinstance(intended, list):
        return []
    drops = unaccounted(intended, executed, reason)
    agent_type = getattr(agent, "agent_type", "")
    callsign = getattr(agent, "callsign", "") or agent_type
    log = getattr(runtime, "event_log", None)
    for drop in drops:
        level = logging.INFO if drop["action"] == "ward_room_post" or drop.get("by_design") else logging.WARNING
        logger.log(level, "BF-934: %s (%s) intended %s and nothing carried it out: %s", callsign, agent_type, drop["action"], drop["reason"])
        if log is None:
            continue
        try:
            row_id = await log.log(
                category=CATEGORY, event=DROPPED_EVENT, agent_id=getattr(agent, "id", None), agent_type=agent_type,
                detail=f"{callsign} intended {drop['action']}: {drop['reason']}", correlation_id=intent_id or None,
                data={**drop, "intent": "proactive_think", "intent_id": intent_id, "callsign": callsign},
            )
            if row_id is None:  # an EventLog that is not open returns None, it does not raise
                logger.warning("BF-934: the dropped row for %s (%s) was not recorded: the event log returned no row id", callsign, agent_type)
        except Exception:
            logger.warning("BF-934: the dropped row for %s (%s) was not recorded", callsign, agent_type, exc_info=True)
    return drops
