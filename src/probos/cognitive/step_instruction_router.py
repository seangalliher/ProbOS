"""AD-651: Step-specific standing order instruction routing.

Decomposes monolithic standing orders into step-relevant slices.
Each cognitive chain step (analyze, compose, reflect, etc.) receives
only the instruction categories relevant to its role.

Backward compatible: returns full text when no category markers exist.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import StepInstructionConfig

logger = logging.getLogger(__name__)

# Pattern matches: <!-- category: name --> or <!-- category: name1, name2 -->
_CATEGORY_MARKER_RE = re.compile(
    r"<!--\s*category:\s*([\w,\s]+?)\s*-->",
    re.IGNORECASE,
)


class StepInstructionRouter:
    """Routes composed standing orders to chain steps by category relevance.

    Consumes the full output of compose_instructions() and extracts
    category-tagged sections. Each chain step name maps to a set of
    categories via config; the router returns only matching sections.

    Parameters
    ----------
    config : StepInstructionConfig
        Step-to-category mappings and universal categories.
    """

    def __init__(self, config: "StepInstructionConfig") -> None:
        self._config = config
        self._step_categories: dict[str, frozenset[str]] = {}
        self._universal: frozenset[str] = frozenset(config.universal_categories)
        for step, cats in config.step_categories.items():
            self._step_categories[step] = frozenset(cats) | self._universal

    def route(self, full_instructions: str, step_name: str) -> str:
        """Extract step-relevant instructions from the full composed text.

        Parameters
        ----------
        full_instructions : str
            The complete output of compose_instructions().
        step_name : str
            The chain step name (e.g., "analyze", "compose", "reflect").

        Returns
        -------
        str
            The filtered instructions containing only categories relevant
            to the given step. Returns full_instructions unchanged if:
            - The feature is disabled
            - No category markers are found in the text
            - The step_name is not in the config
        """
        if not self._config.enabled:
            return full_instructions

        if not self.has_markers(full_instructions):
            logger.debug(
                "AD-651: No category markers found, returning full instructions for step '%s'",
                step_name,
            )
            return full_instructions

        # Parse category-tagged sections
        sections = self._parse_sections(full_instructions)

        if not sections:
            # No markers found — backward-compatible fallback
            logger.debug(
                "AD-651: No category markers found, returning full instructions for step '%s'",
                step_name,
            )
            return full_instructions

        # Resolve target categories for this step
        target_cats = self._step_categories.get(step_name)
        if target_cats is None:
            # Unknown step — return full instructions
            logger.debug(
                "AD-651: Unknown step '%s', returning full instructions",
                step_name,
            )
            return full_instructions

        # Filter sections by category membership
        matched_parts: list[str] = []
        untagged_parts: list[str] = []

        for categories, text in sections:
            if not categories:
                # Untagged content (e.g., hardcoded instructions, personality block)
                # Always included — these are tier 1/1.5 content without markers
                untagged_parts.append(text)
            elif categories & target_cats:
                matched_parts.append(text)

        # Compose result: untagged (always) + matched tagged sections
        result_parts = untagged_parts + matched_parts
        result = "\n\n---\n\n".join(part for part in result_parts if part.strip())

        if self._config.log_token_savings:
            full_len = len(full_instructions)
            result_len = len(result)
            savings_pct = ((full_len - result_len) / full_len * 100) if full_len > 0 else 0
            logger.debug(
                "AD-651: step='%s' full=%d chars, filtered=%d chars, savings=%.1f%%",
                step_name, full_len, result_len, savings_pct,
            )

        return result

    def _parse_sections(
        self, text: str,
    ) -> list[tuple[frozenset[str], str]]:
        """Parse text into (categories, content) pairs.

        Sections are delimited by:
        - ``<!-- category: name -->`` markers
        - ``---`` separators (from compose_instructions tier joins)

        Content before any category marker is returned with an empty
        frozenset (untagged). A marker's categories apply to all content
        until the next marker or ``---`` separator.

        Returns
        -------
        list[tuple[frozenset[str], str]]
            Each element is (category_set, section_text). category_set is
            empty for untagged sections.
        """
        sections: list[tuple[frozenset[str], str]] = []
        # Split on --- separators first (these come from compose_instructions)
        tier_blocks = re.split(r"\n---\n", text)

        for block in tier_blocks:
            if not block.strip():
                continue
            # Find all category markers in this block
            markers = list(_CATEGORY_MARKER_RE.finditer(block))

            if not markers:
                # No markers in this block — untagged
                sections.append((frozenset(), block.strip()))
                continue

            # Content before first marker is untagged
            pre_marker = block[:markers[0].start()].strip()
            if pre_marker:
                sections.append((frozenset(), pre_marker))

            # Process each marker and its content
            for i, match in enumerate(markers):
                # Parse comma-separated category names
                raw_cats = match.group(1)
                cats = frozenset(
                    c.strip().lower() for c in raw_cats.split(",") if c.strip()
                )

                # Content runs from after this marker to start of next marker
                # (or end of block)
                content_start = match.end()
                if i + 1 < len(markers):
                    content_end = markers[i + 1].start()
                else:
                    content_end = len(block)

                content = block[content_start:content_end].strip()
                if content:
                    sections.append((cats, content))

        return sections

    def has_markers(self, text: str) -> bool:
        """Check whether text contains any category markers.

        Useful for diagnostics and testing.
        """
        return bool(_CATEGORY_MARKER_RE.search(text))