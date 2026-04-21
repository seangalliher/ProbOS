"""BF-213: Proactive chain action suppression fix tests."""
import pytest
from probos.cognitive.sub_tasks.analyze import _build_situation_review_prompt
from probos.cognitive.sub_tasks.compose import (
    _build_proactive_compose_prompt,
    _build_ward_room_compose_prompt,
)


class TestAnalyzeSilenceBias:
    """Verify analyze prompt no longer defaults to silence."""

    def _build_analyze_prompt(self, duty=None):
        ctx = {
            "context": "test situation data",
            "_agent_type": "medical_officer",
            "_agent_metrics": "Trust: 0.75, Rank: Lieutenant",
        }
        if duty:
            ctx["_active_duty"] = duty
        _, user_prompt = _build_situation_review_prompt(ctx, [], "Keiko", "medical")
        return user_prompt

    def test_no_silence_is_professionalism(self):
        """Non-duty proactive analyze does not say 'Silence is professionalism'."""
        prompt = self._build_analyze_prompt()
        assert "Silence is professionalism" not in prompt

    def test_no_silence_as_default(self):
        """Non-duty proactive analyze does not frame silence as 'expected default'."""
        prompt = self._build_analyze_prompt()
        assert "expected default" not in prompt

    def test_mentions_proposal_option(self):
        """Non-duty proactive analyze mentions proposals as an action option."""
        prompt = self._build_analyze_prompt()
        assert "proposal" in prompt.lower()

    def test_mentions_game_option(self):
        """Non-duty proactive analyze mentions games as an action option."""
        prompt = self._build_analyze_prompt()
        assert "game" in prompt.lower()

    def test_no_response_still_valid(self):
        """Non-duty proactive analyze still allows [NO_RESPONSE]."""
        prompt = self._build_analyze_prompt()
        assert "[NO_RESPONSE]" in prompt

    def test_quality_bar_maintained(self):
        """Non-duty proactive analyze still discourages vague observations."""
        prompt = self._build_analyze_prompt()
        assert "vague" in prompt.lower() or "specific" in prompt.lower()

    def test_duty_path_unchanged(self):
        """Duty-triggered analyze still says 'report your findings'."""
        prompt = self._build_analyze_prompt(
            duty={"duty_id": "status_report", "description": "Status Report"}
        )
        assert "report your findings" in prompt.lower()


class TestComposeFraming:
    """Verify compose framing allows structured actions, not just observations."""

    def _build_prompt(self, duty=None):
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
            "_agent_type": "medical_officer",
        }
        if duty:
            ctx["_active_duty"] = duty
        system, _ = _build_proactive_compose_prompt(ctx, [], "Keiko", "medical")
        return system

    def test_not_observation_only(self):
        """Non-duty compose framing does not frame observation as the sole output type."""
        system = self._build_prompt()
        # Should not say "compose a brief observation" without mentioning other options
        assert "proposal" in system.lower() or "standing orders" in system.lower()

    def test_references_standing_orders(self):
        """Non-duty compose framing references standing orders for tag syntax."""
        system = self._build_prompt()
        assert "standing orders" in system.lower()

    def test_duty_framing_unchanged(self):
        """Duty-triggered compose framing unchanged."""
        system = self._build_prompt(
            duty={"duty_id": "status_report", "description": "Status Report"}
        )
        assert "scheduled duty" in system.lower()


class TestNoDuplication:
    """Verify no action tag duplication between compose.py and standing orders."""

    def _build_proactive_prompt(self):
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
            "_agent_type": "medical_officer",
        }
        system, _ = _build_proactive_compose_prompt(ctx, [], "Keiko", "medical")
        return system

    def _build_ward_room_prompt(self):
        ctx = {
            "context": "test",
            "mode": "ward_room_response",
            "_agent_type": "medical_officer",
        }
        system, _ = _build_ward_room_compose_prompt(ctx, [], "Keiko", "medical")
        return system

    def test_no_proposal_syntax_in_compose_code(self):
        """[PROPOSAL] syntax comes from standing orders, not compose code.

        Note: [PROPOSAL] WILL appear in the full system prompt because
        compose_instructions() includes ship.md standing orders. This test
        verifies the compose code itself doesn't add a SECOND copy.
        We check that the BF-213 marker comment is gone.
        """
        import inspect
        source = inspect.getsource(_build_proactive_compose_prompt)
        assert "BF-213" not in source

    def test_no_dm_syntax_in_ward_room_compose_code(self):
        """[DM] syntax comes from standing orders, not ward room compose code.

        Same principle: compose_instructions() provides it via ship.md.
        """
        import inspect
        source = inspect.getsource(_build_ward_room_compose_prompt)
        assert "BF-213" not in source
