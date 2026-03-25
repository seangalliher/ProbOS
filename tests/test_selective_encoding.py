"""AD-433: Selective Encoding Gate — tests for EpisodicMemory.should_store()."""

from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.types import Episode


def test_gate_allows_captain_1_1():
    episode = Episode(
        user_input="[1:1 with Counselor] Captain: How are you?",
        outcomes=[{"intent": "conversation", "success": True, "response": "I'm well"}],
    )
    assert EpisodicMemory.should_store(episode) is True


def test_gate_blocks_proactive_no_response():
    episode = Episode(
        user_input="[Proactive thought — no response] Counselor: reviewed context, nothing to report",
        outcomes=[{"intent": "proactive_think", "success": True, "response": "[NO_RESPONSE]"}],
    )
    assert EpisodicMemory.should_store(episode) is False


def test_gate_allows_proactive_with_response():
    episode = Episode(
        user_input="[Proactive thought] Counselor: I've noticed trust variance",
        outcomes=[{"intent": "proactive_think", "success": True, "response": "I've noticed trust variance across departments"}],
    )
    assert EpisodicMemory.should_store(episode) is True


def test_gate_blocks_qa_routine_pass():
    episode = Episode(
        user_input="[SystemQA] Smoke test: code_search",
        outcomes=[{"intent": "smoke_test", "success": True, "status": "completed"}],
    )
    assert EpisodicMemory.should_store(episode) is False


def test_gate_allows_qa_failure():
    episode = Episode(
        user_input="[SystemQA] Smoke test: code_search",
        outcomes=[{"intent": "smoke_test", "success": False, "status": "failed"}],
    )
    assert EpisodicMemory.should_store(episode) is True


def test_gate_allows_failure_outcome():
    episode = Episode(
        user_input="[Action: health_check] Chapel: ran diagnostics",
        outcomes=[{"intent": "health_check", "success": False, "response": "Timeout"}],
    )
    assert EpisodicMemory.should_store(episode) is True


def test_gate_blocks_empty_no_response_outcomes():
    episode = Episode(
        user_input="[Action: status_check] O'Brien: routine check",
        outcomes=[{"intent": "status_check", "success": True, "response": "[NO_RESPONSE]"}],
    )
    assert EpisodicMemory.should_store(episode) is False


def test_gate_allows_real_response():
    episode = Episode(
        user_input="[Action: code_review] Number One: reviewing module",
        outcomes=[{"intent": "code_review", "success": True, "response": "Found 3 issues in the routing module"}],
    )
    assert EpisodicMemory.should_store(episode) is True


def test_gate_allows_no_outcomes_conservative():
    episode = Episode(
        user_input="Some unexpected episode format",
        outcomes=[],
    )
    assert EpisodicMemory.should_store(episode) is True


def test_gate_ward_room_no_response_not_stored():
    """Ward Room episodes without response content are filtered by the gate.

    This is correct — Sites 9/10 (Ward Room) are NOT gated at the call site,
    so this path never runs in production. The gate correctly identifies that
    an episode with no response text has no content worth storing.
    """
    episode = Episode(
        user_input="[Ward Room] All Hands — Counselor: Trust report",
        outcomes=[{"intent": "ward_room_post", "success": True}],
    )
    assert EpisodicMemory.should_store(episode) is False


def test_mock_should_store_delegates():
    episode = Episode(
        user_input="[Proactive thought — no response] Counselor: nothing to report",
        outcomes=[{"intent": "proactive_think", "success": True, "response": "[NO_RESPONSE]"}],
    )
    assert MockEpisodicMemory.should_store(episode) is False
