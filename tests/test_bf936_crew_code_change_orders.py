"""BF-936 (#1677): the standing orders tell the crew what they can do about code changes.

The real loader (``compose_instructions`` and ``get_step_instructions``) runs over this repository's own
``config/standing_orders``, the files the crew are composed from: no mock of the loader, of a file read or of the
composition, and no model is called. The class holds the cases the unwritten orders fail; the functions before it pass
on both trees (they are the controls). No BF-936 name is imported.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from probos.cognitive import standing_orders
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.standing_orders import compose_instructions, get_step_instructions, standing_order_names
from probos.cognitive.step_instruction_router import StepInstructionRouter
from probos.config import AgentTierConfig, StepInstructionConfig

ORDERS = Path(__file__).resolve().parents[1] / "config" / "standing_orders"
HEADING = "## What Crew Can Do About Code Changes"
_PROFILES = sorted(p.stem for p in (ORDERS / "crew_profiles").glob("*.yaml") if not p.stem.startswith("_"))
# Every crew type the product names (the seed profiles and the tier list), the Yeoman (a personal file and no profile) and a
# type that has no orders file at all.
CREW = sorted({*_PROFILES, *AgentTierConfig().crew_types, "yeoman"}) + ["a_type_with_no_orders_file"]
# The steps the router is configured for ("query" is deterministic and takes no orders). Today ANALYZE and COMPOSE are the
# steps that call get_step_instructions; EVALUATE and REFLECT list categories but build their own prompts.
STEPS = [step for step in StepInstructionConfig().step_categories if step != "query"]
PHRASES = (  # one for each part of the rule; a text is flattened to single spaces before they are looked for
    "propose improvements, review designs, specify acceptance tests",
    "Crew do not build, commit or merge code to the ProbOS repository on their own initiative",
    "Changes to the ProbOS repository are made by the engineering pipeline under the Captain's direction",
    "Forge can build a candidate when the Captain dispatches a build; it is not merged until the GitHub delivery route exists",
    "Agent self-modification requires the Captain's approval",
    "only when the record shows you did it",
    "a direction, not a date",
)
_CLAIM = re.compile(r"you've built|builds you've run|\bi(?:'ll| will) (?:implement|build|merge|ship|commit)\b", re.IGNORECASE)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", _flat(text))


def _section(text: str) -> str:
    """The section's text, flattened, from its heading to the next category marker or heading; "" when there is none."""
    start = text.find(HEADING)
    if start < 0:
        return ""
    rest = text[start + len(HEADING):]
    cuts = [i for i in (rest.find("\n<!--"), rest.find("\n## ")) if i != -1]
    return _flat(rest[: min(cuts)] if cuts else rest)


def _carries(text: str) -> bool:
    section = _section(text)
    return all(phrase in section for phrase in PHRASES)


def _unqualified_claims(text: str) -> list[str]:
    """The sentences that claim a build, or promise one, with no dispatch in the same sentence (a quoted example is no claim)."""
    claims = []
    for sentence in _sentences(text):
        unquoted = re.sub(r'"[^"]*"', " ", sentence)
        if _CLAIM.search(unquoted) and "dispatch" not in unquoted.lower():
            claims.append(sentence)
    return claims


@pytest.fixture(autouse=True)
def _the_repository_orders_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loader reads this repository's orders, and nothing that another test wired into the module is in the way."""
    monkeypatch.setattr(standing_orders, "_DEFAULT_ORDERS_DIR", ORDERS)
    for name in ("_directive_store", "_skill_catalog", "_billet_registry", "_task_context", "_step_router"):
        monkeypatch.setattr(standing_orders, name, None)
    standing_orders.clear_cache()


@pytest.mark.parametrize(
    ("sentence", "flagged"),
    [
        ("You've built enough to know where the pitfalls are.", True),
        ("You back your opinions with evidence from builds you've run.", True),
        ("I will merge the change myself.", True),
        ("I'll implement it tonight, and then I'll ship it.", True),
        ("You build only when the Captain dispatches a build, and you've built nothing else.", False),
        ("Understand the spec before you build.", False),
        ('Say "I\'ll implement it" only when the record shows you did.', False),
    ],
)
def test_the_scan_flags_a_claim_with_no_dispatch_and_spares_the_rest(sentence: str, flagged: bool) -> None:
    assert bool(_unqualified_claims(sentence)) is flagged


def test_the_check_fails_on_orders_without_the_section_and_holds_on_orders_with_it(tmp_path: Path) -> None:
    """Control: the same real loader over a directory of its own, so a pass in the class cannot come from the check."""
    bare, full = tmp_path / "bare", tmp_path / "full"
    for directory, text in (
        (bare, "# Ship Standing Orders\n\nOther orders only.\n"),
        (full, f"{HEADING}\n\n" + "\n".join(PHRASES) + "\n"),
    ):
        directory.mkdir()
        (directory / "ship.md").write_text(text, encoding="utf-8")
    composed_bare = compose_instructions("builder", "", orders_dir=bare)
    composed_full = compose_instructions("builder", "", orders_dir=full)
    assert "Other orders only." in composed_bare and not _carries(composed_bare)
    assert _carries(composed_full)


def test_step_routing_drops_a_section_whose_tag_the_step_does_not_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: with the router on, a section survives a step only through its tag, so T2 is not vacuous."""
    assert "core_directives" in StepInstructionConfig().universal_categories, "premise: the tag the section carries is universal"
    monkeypatch.setattr(standing_orders, "_step_router", StepInstructionRouter(StepInstructionConfig(enabled=True)))
    kept = get_step_instructions(agent_type="builder", hardcoded_instructions="", step_name="analyze")
    dropped = get_step_instructions(agent_type="builder", hardcoded_instructions="", step_name="compose")
    assert "## Startup Sequence" in kept and "## Startup Sequence" not in dropped


class TestTheCrewKnowWhatTheyMayDoAboutCodeChanges:
    # BF-936 M1: xfail until M2 writes the orders (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-936 M2 writes the orders")

    @pytest.mark.parametrize("agent_type", CREW)
    def test_the_section_is_composed_into_each_crew_members_ship_tier(self, agent_type: str) -> None:
        composed = compose_instructions(agent_type=agent_type, hardcoded_instructions="")
        assert "## Ship Standing Orders\n\n" in composed, "premise: the ship tier is composed"
        tier = composed.split("## Ship Standing Orders\n\n", 1)[1].split("\n\n---\n\n", 1)[0]
        assert _carries(tier), f"{agent_type}: the ship tier lacks the section or one of its phrases"

    @pytest.mark.parametrize("step", STEPS)
    def test_the_section_survives_step_routing_when_it_is_on(self, monkeypatch: pytest.MonkeyPatch, step: str) -> None:
        monkeypatch.setattr(standing_orders, "_step_router", StepInstructionRouter(StepInstructionConfig(enabled=True)))
        routed = get_step_instructions(agent_type="builder", hardcoded_instructions="", step_name=step)
        assert _carries(routed), f"step {step}: the routed orders lack the section or one of its phrases"

    @pytest.mark.parametrize(
        ("name", "phrases"),
        [
            (
                "builder",
                (
                    "You build only when the Captain dispatches a build",
                    "not merged until the GitHub delivery route exists",
                    "only when the record shows you did it",
                ),
            ),
            (
                "engineering",
                (
                    "a build the Captain dispatches",
                    "not merged until the GitHub delivery route exists",
                    "Engineering crew propose, review, specify and verify changes",
                ),
            ),
        ],
    )
    def test_the_builder_and_engineering_orders_agree_with_the_crew_wide_section(
        self, name: str, phrases: tuple[str, ...],
    ) -> None:
        text = _flat((ORDERS / f"{name}.md").read_text(encoding="utf-8"))
        missing = [phrase for phrase in phrases if phrase not in text]
        assert not missing, f"{name}.md lacks {missing}"

    def test_no_standing_order_claims_a_build_with_no_dispatch(self) -> None:
        names = standing_order_names(ORDERS)
        assert {"builder", "engineering", "ship"} <= set(names), "premise: the scan reads the orders the crew are composed from"
        found = {
            name: hits
            for name in names
            if (hits := _unqualified_claims((ORDERS / f"{name}.md").read_text(encoding="utf-8")))
        }
        assert not found, found

    @pytest.mark.parametrize("name", ["ship", "builder", "engineering"])
    def test_the_new_text_is_ascii_and_names_no_issue_number(self, name: str) -> None:
        text = (ORDERS / f"{name}.md").read_text(encoding="utf-8")
        added = (
            _section(text)
            if name == "ship"
            else " ".join(s for s in _sentences(text) if "dispatch" in s or "the record" in s)
        )
        assert added, f"{name}.md: the new text is absent"
        assert added.isascii(), f"{name}.md: the new text is not ASCII"
        assert not re.search(r"\b(?:AD|BF)-\d+\b|#\d+", added), f"{name}.md: the new text names an issue number"

    def test_the_section_is_capability_gap_clean(self) -> None:
        section = _section((ORDERS / "ship.md").read_text(encoding="utf-8"))
        assert section, "the section is absent"
        assert is_capability_gap(section) is False
