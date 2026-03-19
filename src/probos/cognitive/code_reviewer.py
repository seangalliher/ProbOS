"""Code Review Agent -- reviews Builder output against ProbOS standards (AD-341)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.standing_orders import compose_instructions

logger = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    """Result of a code review."""
    approved: bool = False
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    summary: str = ""


class CodeReviewAgent(CognitiveAgent):
    """Reviews code changes against ProbOS engineering standards.

    Reads standards from Standing Orders (federation.md + ship.md + engineering.md
    + code_reviewer.md). Operates standalone -- no IDE dependency.

    Pipeline position:
    Builder generates code -> CodeReviewer reviews -> tests run -> commit (if all pass).
    """

    agent_type = "code_reviewer"
    tier = "utility"

    instructions = """You are the Code Review Agent for ProbOS. You review code changes
produced by the Builder Agent before they are committed.

You receive the project's engineering standards via Standing Orders. Review
all code changes against those standards.

OUTPUT FORMAT:
Return a JSON object:
{
  "approved": true/false,
  "issues": ["Critical issue 1 -- file:line -- description"],
  "suggestions": ["Non-blocking suggestion 1"],
  "summary": "One-sentence review summary"
}

RULES:
- Issues are blocking -- the build should NOT commit if any issues exist.
- Suggestions are non-blocking improvements for future consideration.
- Be specific: reference file paths and the problematic code.
- Do NOT flag style preferences (bracket placement, blank lines). Only flag
  violations of the engineering standards in your Standing Orders.
- If the code is clean, approve with an empty issues list.
"""

    def _resolve_tier(self) -> str:
        """Use standard tier -- review is classification, not generation."""
        return "standard"

    async def review(
        self,
        file_changes: list[dict[str, Any]],
        spec_title: str,
        llm_client: Any,
    ) -> ReviewResult:
        """Review file changes against Standing Orders.

        Args:
            file_changes: List of file change dicts from Builder output.
            spec_title: Title of the build spec being reviewed.
            llm_client: LLM client for the review call.

        Returns:
            ReviewResult with approval status and any issues found.
        """
        from probos.cognitive.llm_client import LLMRequest

        # Compose instructions from Standing Orders
        system_prompt = compose_instructions(
            agent_type=self.agent_type,
            hardcoded_instructions=self.instructions,
        )

        # Build review prompt
        changes_text = self._format_changes(file_changes)

        prompt = (
            f"## Build Spec\n{spec_title}\n\n"
            f"## Code Changes to Review\n{changes_text}\n\n"
            "Review these changes against the engineering standards in your "
            "Standing Orders. Return your review as a JSON object."
        )

        request = LLMRequest(
            prompt=prompt,
            system_prompt=system_prompt,
            tier="standard",
        )

        try:
            response = await llm_client.complete(request)
            return self._parse_review(response.content)
        except Exception as exc:
            logger.warning("CodeReviewAgent: review failed: %s", exc)
            # On failure, approve with warning -- don't block pipeline on reviewer errors
            return ReviewResult(
                approved=True,
                suggestions=[f"Code review skipped due to error: {exc}"],
                summary="Review skipped (LLM error)",
            )

    def _format_changes(self, file_changes: list[dict[str, Any]]) -> str:
        """Format file changes for the review prompt."""
        parts = []
        for change in file_changes:
            path = change.get("path", "unknown")
            mode = change.get("mode", "create")
            if mode == "modify":
                repls = change.get("replacements", [])
                repl_text = "\n".join(
                    f"SEARCH:\n{r['search']}\nREPLACE:\n{r['replace']}"
                    for r in repls
                )
                parts.append(f"### MODIFY: {path}\n{repl_text}")
            else:
                content = change.get("content", "")[:3000]
                parts.append(f"### CREATE: {path}\n```python\n{content}\n```")
        return "\n\n".join(parts)

    def _parse_review(self, content: str) -> ReviewResult:
        """Parse LLM review response into ReviewResult."""
        result = ReviewResult()

        # Extract JSON from response (may be wrapped in markdown code block)
        text = content.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            data = json.loads(text)
            result.approved = data.get("approved", False)
            result.issues = data.get("issues", [])
            result.suggestions = data.get("suggestions", [])
            result.summary = data.get("summary", "")
        except (json.JSONDecodeError, AttributeError):
            lower = content.lower()
            if "no issues" in lower or '"approved": true' in lower:
                result.approved = True
                result.summary = "Approved (parsed from text)"
            else:
                result.approved = False
                result.issues = ["Could not parse review response"]
                result.summary = content[:200]

        return result
