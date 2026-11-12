"""BF-934 (#1673): what a model is told when the triage has already decided to take an action.

The triage (ANALYZE) names the actions a turn will take (``intended_actions``). COMPOSE tells the model the proposal format when ``proposal`` is among them
(AD-651a), but a triage that names no communication action skips COMPOSE (AD-643a), and a chain that fails falls back to the single call. Neither passed the
decision on: the single call treats silence as the expected default and decided again, mostly for silence. ``decision_billet`` is the text the single call is
given instead. Nothing is added for any other set of actions. The triage's tags are a model's free text and the billet is part of what BF-922's grounding gate counts as
shown to the call, so the billet repeats none of them: it names a decision only by the constants of this module (``BILLET_TAGS``).
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
#: The only tags a billet names, in this order: the six it has a format or a standing order for, all of them tags the ANALYZE prompts offer (the tests pin both).
#: The triage's tags are a model's free text, so ``decision_billet`` writes these constants for the tags it recognises and repeats no other string.
BILLET_TAGS = (*_BLOCK_TAGS, *_COMPANION_TAGS)


def decision_billet(intended: Iterable[object] | None) -> str:
    """The text that gives the single call the triage's decision, or "" when the decision names no proposal or notebook entry.

    Every other set of intended actions leaves the call as it was: ``silent`` never reaches it, and ``oracle_query``, ``ward_room_lookup``,
    ``speak_freely`` and ``leadership_review`` alone ask it for no block.

    The tags are the ANALYZE model's own words (``_extract_intended_actions`` keeps whatever it wrote), and this text is part of what BF-922's gate counts as shown
    to the call: an identifier the triage made up, repeated here, would ground the answer's citation of it. So the billet writes the constant of ``BILLET_TAGS`` for each
    tag it recognises, in their order, and a tag that is none of them changes nothing.
    """
    if intended is None:
        return ""
    tags = list(dict.fromkeys(str(tag).strip().lower() for tag in intended))
    if not any(tag in tags for tag in _BLOCK_TAGS):
        return ""
    named = [tag for tag in BILLET_TAGS if tag in tags]  # the constant for each decided tag, never the triage's own string
    lines = [
        f"\n\n## {DECISION_HEADING}",
        f"Before this step you decided to take these actions: {', '.join(named)}.",
        "That decision stands for this turn, so the usual default of silence does not apply here: carry it out with the blocks below, "
        "after any observation text you also write. If you find that the evidence no longer supports an action, answer exactly "
        "[NO_RESPONSE]; that withdrawal is recorded.",
    ]
    if "proposal" in tags:
        lines += ["", "**You decided to file an improvement proposal.** Use this exact format as a SEPARATE block:", PROPOSAL_FORMAT.rstrip("\n")]
    if "notebook" in tags:
        lines += ["", "**You decided to write a notebook entry.** Use this format as a SEPARATE block:", NOTEBOOK_FORMAT.rstrip("\n")]
    companions = [tag for tag in _COMPANION_TAGS if tag in tags]  # constants again, in their order
    if companions:
        lines += ["", f"You also decided: {', '.join(companions)}. Use the formats your standing orders give for them."]
    return "\n".join(lines)
