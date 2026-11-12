"""BF-934 (#1673): what a model is told when the triage has already decided to take an action.

The triage (ANALYZE) names the actions a turn will take (``intended_actions``). COMPOSE tells the model the proposal format when ``proposal`` is among them
(AD-651a), but a triage that names no communication action skips COMPOSE (AD-643a), and a chain that fails falls back to the single call. Neither passed the
decision on: the single call treats silence as the expected default and decided again, mostly for silence. ``decision_billet`` is the text the single call is
given instead. Nothing is added for any other set of actions.
"""

from __future__ import annotations

from collections.abc import Iterable

#: The block ``ProactiveCognitiveLoop._extract_and_execute_actions`` reads as a proposal. COMPOSE's AD-651a billet shows the same block
#: (tests/test_bf934_s1_decision_routing.py pins the two equal).
PROPOSAL_FORMAT = (
    "```\n"
    "[PROPOSAL]\n"
    "Title: <short descriptive title>\n"
    "Rationale: <why this matters and what it would improve \u2014 be specific, "
    "cite evidence from your analysis>\n"
    "Affected Systems: <comma-separated subsystem names>\n"
    "Priority: low|medium|high\n"
    "[/PROPOSAL]\n"
    "```\n"
)

#: The block the notebook writer reads (``proactive._NOTEBOOK_PATTERN``); the optional scope word is taught by the standing orders.
NOTEBOOK_FORMAT = (
    "```\n"
    "[NOTEBOOK topic-slug]\n"
    "<your analysis, findings or report>\n"
    "[/NOTEBOOK]\n"
    "```\n"
)

#: The heading of the billet; tests/bf934_world.py answers a prompt that carries it, as a model that obeys a decision it is shown.
DECISION_HEADING = "Your triage already decided this turn"

_BLOCK_TAGS = ("proposal", "notebook")  # the tags whose block the single call has no other reason to write
_COMPANION_TAGS = ("ward_room_post", "ward_room_reply", "endorse", "dm")  # written in the formats the standing orders already give


def decision_billet(intended: Iterable[object] | None) -> str:
    """The text that gives the single call the triage's decision, or "" when the decision names no proposal or notebook entry.

    Every other set of intended actions leaves the call as it was: ``silent`` never reaches it, and ``oracle_query``, ``ward_room_lookup``,
    ``speak_freely`` and ``leadership_review`` alone ask it for no block.
    """
    if intended is None:
        return ""
    tags = list(dict.fromkeys(str(tag).strip().lower() for tag in intended))
    if not any(tag in tags for tag in _BLOCK_TAGS):
        return ""
    lines = [
        f"\n\n## {DECISION_HEADING}",
        f"Before this step you decided to take these actions: {', '.join(tags)}.",
        "That decision stands for this turn, so the usual default of silence does not apply here: carry it out with the blocks below, "
        "after any observation text you also write. If you find that the evidence no longer supports an action, answer exactly "
        "[NO_RESPONSE]; that withdrawal is recorded.",
    ]
    if "proposal" in tags:
        lines += ["", "**You decided to file an improvement proposal.** Use this exact format as a SEPARATE block:", PROPOSAL_FORMAT.rstrip("\n")]
    if "notebook" in tags:
        lines += ["", "**You decided to write a notebook entry.** Use this format as a SEPARATE block:", NOTEBOOK_FORMAT.rstrip("\n")]
    companions = [tag for tag in tags if tag in _COMPANION_TAGS]
    if companions:
        lines += ["", f"You also decided: {', '.join(companions)}. Use the formats your standing orders give for them."]
    return "\n".join(lines)
