"""BF-934 (#1673): the one reading of a ``[PROPOSAL]`` block.

``ProactiveCognitiveLoop._extract_and_execute_actions`` files a proposal from the first strict block of an output, and the proactive loop must also tell whether an
output carries a valid one before it reads ``[NO_RESPONSE]`` as silence. Both ask here, so the rule is written once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The strict shape of the block: newlines between the tags (AD-412).
PROPOSAL_PATTERN = r'\[PROPOSAL\]\s*\n(.*?)\n\s*\[/PROPOSAL\]'


@dataclass(frozen=True)
class ProposalParse:
    """What an output's proposal block is. ``problem`` is "" for a block that can be filed, else why not: "no_block" (no ``[PROPOSAL]`` at all),
    "malformed_block" (one without the strict shape), "missing_title" or "missing_rationale". ``extra_blocks`` counts the strict blocks after the
    first, which are not filed."""

    problem: str
    title: str = ""
    rationale: str = ""
    affected: tuple[str, ...] = ()
    priority: str = "medium"
    extra_blocks: int = 0

    @property
    def valid(self) -> bool:
        return self.problem == ""

    @property
    def found(self) -> bool:
        """True when the strict shape matched, whether or not the block can be filed."""
        return self.problem not in ("no_block", "malformed_block")


def parse_proposal_block(text: str) -> ProposalParse:
    """Read the first strict ``[PROPOSAL]`` block of *text*, as AD-412's extractor always has."""
    matches = list(re.finditer(PROPOSAL_PATTERN, text, re.DOTALL))
    if not matches:
        return ProposalParse("malformed_block" if re.search(r'\[PROPOSAL\]', text) else "no_block")
    title = ""
    affected: list[str] = []
    priority = "medium"
    in_rationale = False
    rationale_lines: list[str] = []
    for line in matches[0].group(1).split('\n'):
        stripped = line.strip()
        if stripped.lower().startswith("title:"):
            title = stripped[6:].strip()
            in_rationale = False
        elif stripped.lower().startswith("affected systems:"):
            affected = [s.strip() for s in stripped[17:].strip().split(",") if s.strip()]
            in_rationale = False
        elif stripped.lower().startswith("priority:"):
            p = stripped[9:].strip().lower()
            if p in ("low", "medium", "high"):
                priority = p
            in_rationale = False
        elif stripped.lower().startswith("rationale:"):
            rest = stripped[10:].strip()
            if rest:
                rationale_lines.append(rest)
            in_rationale = True
        elif in_rationale:
            rationale_lines.append(stripped)
    rationale = "\n".join(rationale_lines).strip()
    problem = "missing_title" if not title else "missing_rationale" if not rationale else ""
    return ProposalParse(problem, title, rationale, tuple(affected), priority, len(matches) - 1)
