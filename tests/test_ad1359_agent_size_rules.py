"""AD-1359 (#1766): the composed instructions of the Builder, Code Review and Architect billets carry the new rules."""

from __future__ import annotations

import pytest

from probos.cognitive.builder import BuilderAgent
from probos.cognitive.code_reviewer import CodeReviewAgent
from probos.cognitive.standing_orders import clear_cache, compose_instructions


@pytest.mark.parametrize(
    ("agent_type", "hardcoded", "required"),
    [
        (
            "builder",
            BuilderAgent.instructions,
            (
                "your own change made unused",
                "take the reading that changes least and list it in your report",
                "If something is ambiguous where a design choice is needed, ask for clarification rather than guessing.",
            ),
        ),
        (
            "code_reviewer",
            CodeReviewAgent.instructions,
            (
                "13. Size — no code the spec does not need",
                "is never a size finding",
                "Report size in `suggestions`, never in blocking `issues`",
            ),
        ),
        (
            "architect",
            "",
            ("Specify the smallest design that settles the spec.",),
        ),
    ],
)
def test_composed_billet_instructions_carry_the_rules(
    agent_type: str, hardcoded: str, required: tuple[str, ...],
) -> None:
    clear_cache()
    composed = compose_instructions(agent_type=agent_type, hardcoded_instructions=hardcoded)
    missing = [text for text in required if text not in composed]
    assert not missing, f"{agent_type}: composed instructions lack {missing}"
