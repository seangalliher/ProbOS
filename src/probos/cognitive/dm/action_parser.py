"""AD-745: ``[ACTION: <json>]`` bracket-marker parser for DM replies.

Mirrors the AD-728d / AD-730-3 / AD-743 bracket-marker family. Extracts
zero or more action envelopes from agent reply text and returns them as
frozen ``ActionEnvelope`` dataclasses. Malformed JSON is Tier-2
log-and-degrade (skipped with WARNING, never raises).

Wave 178 / GATE 1 — Captain ruling: per-action ACK is the canonical
posture; the parser is dumb (no execution), the pipeline stage owns the
classification + dispatch decision.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Literal-prefix regex so JSON code blocks containing the words "action"
# do not false-positive. The bracket `[ACTION:` must appear verbatim with
# the ACTION token uppercase, followed by optional whitespace and an
# opening brace. Non-greedy JSON capture; DOTALL so multiline envelopes
# survive newline-formatting from the LLM.
_ACTION_RE = re.compile(r"\[ACTION:\s*(\{.*?\})\s*\]", re.DOTALL)


@dataclass(frozen=True)
class ActionEnvelope:
    """One parsed ``[ACTION:]`` marker.

    ``raw_intent`` is the human-readable "intent" field — surfaced on the
    Captain-facing ACK / confirm modal so the operator can decide without
    having to read JSON.
    """

    verb: str
    args: dict[str, Any]
    raw_intent: str


def parse_action_envelopes(reply_text: str) -> list[ActionEnvelope]:
    """Extract well-formed ``[ACTION:]`` envelopes from ``reply_text``.

    Tier-2 honest-degrade: malformed JSON or missing ``verb`` skipped
    with a WARNING; remainder of the text is processed normally. Empty
    input returns ``[]`` without logging.
    """
    if not reply_text:
        return []
    envelopes: list[ActionEnvelope] = []
    for match in _ACTION_RE.finditer(reply_text):
        raw = match.group(1)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as ex:
            logger.warning(
                "AD-745: skipping malformed [ACTION:] envelope (json decode "
                "failed: %s); raw=%r",
                ex, raw[:200],
            )
            continue
        if not isinstance(payload, dict):
            logger.warning(
                "AD-745: skipping [ACTION:] envelope (expected JSON object, "
                "got %s)",
                type(payload).__name__,
            )
            continue
        verb = payload.get("verb")
        if not isinstance(verb, str) or not verb:
            logger.warning(
                "AD-745: skipping [ACTION:] envelope (missing or non-string "
                "'verb' field)"
            )
            continue
        args = payload.get("args") or payload.get("params") or {}
        if not isinstance(args, dict):
            logger.warning(
                "AD-745: skipping [ACTION:] envelope verb=%r (args must be "
                "object, got %s)",
                verb, type(args).__name__,
            )
            continue
        raw_intent = payload.get("intent") or ""
        if not isinstance(raw_intent, str):
            raw_intent = str(raw_intent)
        envelopes.append(
            ActionEnvelope(verb=verb, args=args, raw_intent=raw_intent),
        )
    return envelopes


def strip_action_markers(reply_text: str) -> str:
    """Remove every ``[ACTION:]`` marker from the reply text.

    Called by the pipeline AFTER dispatch so the Captain-visible reply
    does not leak JSON. Even malformed markers are stripped (regex match,
    not parse-match) so the Captain never sees broken JSON.
    """
    if not reply_text:
        return reply_text
    return _ACTION_RE.sub("", reply_text).strip()
