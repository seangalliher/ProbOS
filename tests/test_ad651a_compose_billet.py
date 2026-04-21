"""AD-651a: Compose billet instructions — proposal format & duty report framing."""
import pytest
from probos.cognitive.sub_task import SubTaskResult, SubTaskType
from probos.cognitive.sub_tasks.compose import _build_proactive_compose_prompt


def _make_prior_results(intended_actions=None, extra_fields=None):
    """Build a prior_results list with an ANALYZE result containing intended_actions."""
    result = {
        "composition_brief": {
            "situation": "Test situation",
            "key_evidence": "Test evidence",
            "response_should_cover": "Test coverage",
            "tone": "professional",
            "sources_to_draw_on": "episodic memory",
        },
        "contribution_assessment": "RESPOND",
    }
    if intended_actions is not None:
        result["intended_actions"] = intended_actions
    if extra_fields:
        result.update(extra_fields)
    return [SubTaskResult(
        sub_task_type=SubTaskType.ANALYZE,
        name="analyze-test",
        success=True,
        result=result,
    )]


class TestProposalBilletInjection:
    """Verify proposal format is injected when analyze requests it."""

    def test_proposal_format_injected_when_analyze_requests_proposal(self):
        """Proposal format block injected when intended_actions includes 'proposal'."""
        ctx = {"context": "test", "mode": "proactive_observation"}
        prior = _make_prior_results(intended_actions=["ward_room_post", "proposal"])
        system, _ = _build_proactive_compose_prompt(ctx, prior, "Keiko", "medical")
        assert "[PROPOSAL]" in system
        assert "Title:" in system
        assert "Rationale:" in system
        assert "Affected Systems:" in system
        assert "Priority:" in system

    def test_proposal_format_not_injected_when_no_proposal_action(self):
        """Proposal format NOT injected when intended_actions lacks 'proposal'."""
        ctx = {"context": "test", "mode": "proactive_observation"}
        prior = _make_prior_results(intended_actions=["ward_room_post"])
        system, _ = _build_proactive_compose_prompt(ctx, prior, "Keiko", "medical")
        # The standing orders may contain [PROPOSAL] upstream, but the
        # billet-injected "You decided to file" marker should be absent
        assert "You decided to file an improvement proposal" not in system

    def test_proposal_format_not_injected_when_silent(self):
        """Proposal format NOT injected when intended_actions is ['silent']."""
        ctx = {"context": "test", "mode": "proactive_observation"}
        prior = _make_prior_results(intended_actions=["silent"])
        system, _ = _build_proactive_compose_prompt(ctx, prior, "Keiko", "medical")
        assert "You decided to file an improvement proposal" not in system

    def test_proposal_format_injected_during_duty_cycle(self):
        """Proposal format injected even during a duty cycle."""
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
            "_active_duty": {"duty_id": "systems_check", "description": "Review engineering systems health"},
        }
        prior = _make_prior_results(intended_actions=["ward_room_post", "proposal"])
        system, _ = _build_proactive_compose_prompt(ctx, prior, "LaForge", "engineering")
        # Should have BOTH duty report framing AND proposal format
        assert "Duty Report:" in system
        assert "[PROPOSAL]" in system
        assert "You decided to file an improvement proposal" in system

    def test_proposal_format_handles_missing_intended_actions(self):
        """No crash when intended_actions key is absent from analyze result."""
        ctx = {"context": "test", "mode": "proactive_observation"}
        prior = _make_prior_results(intended_actions=None)
        system, _ = _build_proactive_compose_prompt(ctx, prior, "Keiko", "medical")
        assert "You decided to file an improvement proposal" not in system


class TestDutyReportFraming:
    """Verify duty report structured format replaces old 2-4 sentence framing."""

    def test_duty_report_structured_format(self):
        """Duty report prompt includes Findings/Assessment/Recommendation structure."""
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
            "_active_duty": {"duty_id": "systems_check", "description": "Review engineering systems health"},
        }
        system, _ = _build_proactive_compose_prompt(ctx, [], "LaForge", "engineering")
        assert "Duty Report:" in system
        assert "Findings:" in system
        assert "Assessment:" in system
        assert "Recommendation:" in system

    def test_duty_report_no_no_response_option(self):
        """Duty report framing does NOT offer [NO_RESPONSE] as an option."""
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
            "_active_duty": {"duty_id": "systems_check", "description": "Review engineering systems health"},
        }
        system, _ = _build_proactive_compose_prompt(ctx, [], "LaForge", "engineering")
        # The duty framing should NOT say "respond with exactly: [NO_RESPONSE]"
        assert "respond with exactly: [NO_RESPONSE]" not in system

    def test_duty_report_mentions_dereliction(self):
        """Duty report framing mentions dereliction to reinforce reporting obligation."""
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
            "_active_duty": {"duty_id": "systems_check", "description": "Review engineering systems health"},
        }
        system, _ = _build_proactive_compose_prompt(ctx, [], "LaForge", "engineering")
        assert "dereliction" in system

    def test_non_duty_still_allows_actions(self):
        """Non-duty framing still mentions observation, proposal, reply, etc."""
        ctx = {"context": "test", "mode": "proactive_observation"}
        system, _ = _build_proactive_compose_prompt(ctx, [], "Keiko", "medical")
        assert "proposal" in system.lower()
        assert "standing orders" in system.lower()

    def test_duty_report_includes_duty_description(self):
        """Duty description is injected into the report framing."""
        ctx = {
            "context": "test",
            "mode": "proactive_observation",
            "_active_duty": {"duty_id": "security_audit", "description": "Review system security posture"},
        }
        system, _ = _build_proactive_compose_prompt(ctx, [], "Worf", "security")
        assert "Review system security posture" in system
