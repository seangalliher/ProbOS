"""AD-651: Step-specific standing order instruction routing tests."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from probos.config import StepInstructionConfig
from probos.cognitive.step_instruction_router import StepInstructionRouter


_SAMPLE_INSTRUCTIONS = """Hardcoded identity block.

---

<!-- category: identity -->
## Identity
You are a test agent.

<!-- category: core_directives -->
## Core
Follow core directives.

<!-- category: observation_guidelines -->
## Observation
Analyze observations carefully.

<!-- category: communication_style -->
## Communication
Speak clearly.

<!-- category: ward_room_actions -->
## Actions
Use Ward Room action tags.
"""


def _config(enabled: bool = True, log_token_savings: bool = False) -> StepInstructionConfig:
    return StepInstructionConfig(enabled=enabled, log_token_savings=log_token_savings)


def _router(enabled: bool = True, log_token_savings: bool = False) -> StepInstructionRouter:
    return StepInstructionRouter(_config(enabled=enabled, log_token_savings=log_token_savings))


class TestStepInstructionRouter:
    def test_route_disabled_returns_full(self) -> None:
        router = _router(enabled=False)

        result = router.route(_SAMPLE_INSTRUCTIONS, "analyze")

        assert result == _SAMPLE_INSTRUCTIONS

    def test_route_no_markers_returns_full(self) -> None:
        router = _router()
        text = "\nPlain standing orders with no category markers.\n"

        result = router.route(text, "analyze")

        assert result == text

    def test_route_unknown_step_returns_full(self) -> None:
        router = _router()

        result = router.route(_SAMPLE_INSTRUCTIONS, "unknown")

        assert result == _SAMPLE_INSTRUCTIONS

    def test_route_analyze_filters_correctly(self) -> None:
        router = _router()

        result = router.route(_SAMPLE_INSTRUCTIONS, "analyze")

        assert "Hardcoded identity block." in result
        assert "You are a test agent." in result
        assert "Follow core directives." in result
        assert "Analyze observations carefully." in result
        assert "Speak clearly." not in result
        assert "Use Ward Room action tags." not in result

    def test_route_compose_filters_correctly(self) -> None:
        router = _router()

        result = router.route(_SAMPLE_INSTRUCTIONS, "compose")

        assert "Hardcoded identity block." in result
        assert "You are a test agent." in result
        assert "Follow core directives." in result
        assert "Speak clearly." in result
        assert "Use Ward Room action tags." in result
        assert "Analyze observations carefully." not in result

    def test_route_query_receives_minimal(self) -> None:
        router = _router()

        result = router.route(_SAMPLE_INSTRUCTIONS, "query")

        assert "Hardcoded identity block." in result
        assert "You are a test agent." in result
        assert "Follow core directives." in result
        assert "Analyze observations carefully." not in result
        assert "Speak clearly." not in result
        assert "Use Ward Room action tags." not in result

    def test_untagged_content_always_included(self) -> None:
        router = _router()

        analyze = router.route(_SAMPLE_INSTRUCTIONS, "analyze")
        compose = router.route(_SAMPLE_INSTRUCTIONS, "compose")

        assert "Hardcoded identity block." in analyze
        assert "Hardcoded identity block." in compose

    def test_universal_categories_always_included(self) -> None:
        router = _router()

        analyze = router.route(_SAMPLE_INSTRUCTIONS, "analyze")
        compose = router.route(_SAMPLE_INSTRUCTIONS, "compose")

        assert "You are a test agent." in analyze
        assert "You are a test agent." in compose
        assert "Follow core directives." in analyze
        assert "Follow core directives." in compose

    def test_parse_sections_single_category(self) -> None:
        router = _router()
        text = "<!-- category: identity -->\n## Identity\nBody"

        result = router._parse_sections(text)

        assert result == [(frozenset({"identity"}), "## Identity\nBody")]

    def test_parse_sections_multi_category(self) -> None:
        router = _router()
        text = "<!-- category: identity, core_directives -->\nShared body"

        result = router._parse_sections(text)

        assert result == [(frozenset({"identity", "core_directives"}), "Shared body")]

    def test_parse_sections_tier_separator(self) -> None:
        router = _router()
        text = "Intro\n---\n<!-- category: communication_style -->\nSpeak clearly"

        result = router._parse_sections(text)

        assert result == [
            (frozenset(), "Intro"),
            (frozenset({"communication_style"}), "Speak clearly"),
        ]

    def test_has_markers_true(self) -> None:
        router = _router()

        assert router.has_markers("<!-- category: identity -->\nBody") is True

    def test_has_markers_false(self) -> None:
        router = _router()

        assert router.has_markers("Body only") is False

    def test_token_savings_logged(self, caplog) -> None:
        router = _router(log_token_savings=True)

        with caplog.at_level(logging.DEBUG, logger="probos.cognitive.step_instruction_router"):
            router.route(_SAMPLE_INSTRUCTIONS, "analyze")

        assert "AD-651: step='analyze'" in caplog.text
        assert "savings=" in caplog.text

    def test_get_step_instructions_no_router(self, tmp_path: Path) -> None:
        from probos.cognitive import standing_orders

        orders_dir = tmp_path / "standing_orders"
        orders_dir.mkdir()
        (orders_dir / "federation.md").write_text("Federation text", encoding="utf-8")
        old_router = standing_orders._step_router
        try:
            standing_orders._step_router = None
            standing_orders.clear_cache()
            result = standing_orders.get_step_instructions(
                agent_type="agent",
                hardcoded_instructions="Hardcoded",
                step_name="analyze",
                orders_dir=orders_dir,
            )
        finally:
            standing_orders._step_router = old_router
            standing_orders.clear_cache()

        assert "Hardcoded" in result
        assert "Federation text" in result

    def test_get_step_instructions_with_router(self, tmp_path: Path) -> None:
        from probos.cognitive import standing_orders

        orders_dir = tmp_path / "standing_orders"
        orders_dir.mkdir()
        (orders_dir / "federation.md").write_text(
            "<!-- category: observation_guidelines -->\nAnalyze this.\n"
            "<!-- category: communication_style -->\nCompose this.",
            encoding="utf-8",
        )
        old_router = standing_orders._step_router
        try:
            standing_orders._step_router = _router()
            standing_orders.clear_cache()
            result = standing_orders.get_step_instructions(
                agent_type="agent",
                hardcoded_instructions="Hardcoded",
                step_name="analyze",
                orders_dir=orders_dir,
            )
        finally:
            standing_orders._step_router = old_router
            standing_orders.clear_cache()

        assert "Hardcoded" in result
        assert "Analyze this." in result
        assert "Compose this." not in result

    def test_category_markers_in_ship_md(self) -> None:
        router = _router()
        text = Path("config/standing_orders/ship.md").read_text(encoding="utf-8")

        assert router.has_markers(text) is True
        for category in (
            "core_directives",
            "situation_assessment",
            "knowledge_capture",
            "communication_style",
            "ward_room_actions",
            "when_to_act_vs_observe",
            "scope_discipline",
            "self_monitoring",
            "source_attribution",
            "duty_reporting",
        ):
            assert re.search(rf"<!--\s*category:\s*{category}\s*-->", text)

    def test_category_markers_in_federation_md(self) -> None:
        router = _router()
        text = Path("config/standing_orders/federation.md").read_text(encoding="utf-8")

        assert router.has_markers(text) is True
        for category in (
            "identity",
            "chain_of_command",
            "observation_guidelines",
            "duty_reporting",
            "memory_anchoring",
            "audience_awareness",
            "situation_assessment",
            "core_directives",
            "source_attribution",
            "encoding_safety",
            "communication_style",
        ):
            assert re.search(rf"<!--\s*category:\s*{category}\s*-->", text)

    def test_compose_analyze_disjoint(self) -> None:
        router = _router()

        analyze = router.route(_SAMPLE_INSTRUCTIONS, "analyze")
        compose = router.route(_SAMPLE_INSTRUCTIONS, "compose")

        assert "You are a test agent." in analyze
        assert "You are a test agent." in compose
        assert "Analyze observations carefully." in analyze
        assert "Analyze observations carefully." not in compose
        assert "Speak clearly." in compose
        assert "Speak clearly." not in analyze

    def test_empty_instructions_returns_empty(self) -> None:
        router = _router()

        assert router.route("", "analyze") == ""
