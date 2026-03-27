"""BF-037: Ontology context gathered but never rendered — verification tests."""

from __future__ import annotations

from probos.cognitive.cognitive_agent import CognitiveAgent


def _make_agent() -> CognitiveAgent:
    """Create minimal CognitiveAgent for _build_user_message testing."""
    agent = CognitiveAgent.__new__(CognitiveAgent)
    agent._agent_type = "test_agent"
    return agent


def _base_observation(context_parts: dict | None = None) -> dict:
    """Build a proactive_think observation with given context_parts."""
    return {
        "intent": "proactive_think",
        "params": {
            "context_parts": context_parts or {},
            "trust_score": 0.5,
            "agency_level": "suggestive",
            "rank": "Ensign",
            "duty": None,
        },
    }


WORF_ONTOLOGY = {
    "identity": {"agent_type": "security_officer", "callsign": "Worf", "post": "Chief of Security"},
    "department": {"id": "security", "name": "Security"},
    "vessel": {"name": "ProbOS", "version": "0.4.0", "alert_condition": "GREEN"},
    "chain_of_command": ["Chief of Security", "First Officer", "Captain"],
    "reports_to": "First Officer (Number One)",
    "direct_reports": [],
    "peers": [],
    "adjacent_departments": ["Engineering", "Operations"],
}


class TestBF037OntologyRendering:
    def test_ontology_rendered_in_proactive_think(self) -> None:
        """Ontology identity grounding appears in proactive think prompt."""
        agent = _make_agent()
        obs = _base_observation({"ontology": WORF_ONTOLOGY})
        msg = agent._build_user_message(obs)
        assert "You are Worf, Chief of Security in Security department." in msg

    def test_ontology_reports_to_rendered(self) -> None:
        """reports_to is rendered when populated."""
        agent = _make_agent()
        obs = _base_observation({"ontology": WORF_ONTOLOGY})
        msg = agent._build_user_message(obs)
        assert "You report to First Officer (Number One)." in msg

    def test_ontology_direct_reports_rendered(self) -> None:
        """direct_reports list is rendered when populated."""
        agent = _make_agent()
        ontology = {
            **WORF_ONTOLOGY,
            "identity": {"callsign": "Number One", "post": "First Officer"},
            "direct_reports": ["Chief Engineer", "Chief Science Officer"],
        }
        obs = _base_observation({"ontology": ontology})
        msg = agent._build_user_message(obs)
        assert "Your direct reports: Chief Engineer, Chief Science Officer." in msg

    def test_ontology_peers_rendered(self) -> None:
        """Department peers list is rendered when populated."""
        agent = _make_agent()
        ontology = {
            **WORF_ONTOLOGY,
            "identity": {"callsign": "Bones", "post": "Chief Medical Officer"},
            "department": {"id": "medical", "name": "Medical"},
            "peers": ["Nurse Chapel", "Dr. Crusher"],
        }
        obs = _base_observation({"ontology": ontology})
        msg = agent._build_user_message(obs)
        assert "Department peers: Nurse Chapel, Dr. Crusher." in msg

    def test_skill_profile_rendered(self) -> None:
        """Skill profile list is rendered in prompt."""
        agent = _make_agent()
        skills = ["system_analysis: level 3 (competent)", "security: level 4 (proficient)"]
        obs = _base_observation({"skill_profile": skills})
        msg = agent._build_user_message(obs)
        assert "Your skills: system_analysis: level 3 (competent), security: level 4 (proficient)." in msg

    def test_ontology_absent_no_crash(self) -> None:
        """No ontology key in context_parts — prompt still generates."""
        agent = _make_agent()
        obs = _base_observation({})
        msg = agent._build_user_message(obs)
        assert "Proactive Review" in msg or "Duty Cycle" in msg

    def test_skill_profile_absent_no_crash(self) -> None:
        """No skill_profile key in context_parts — prompt still generates."""
        agent = _make_agent()
        obs = _base_observation({"ontology": WORF_ONTOLOGY})
        msg = agent._build_user_message(obs)
        assert "Your skills:" not in msg
        assert "You are Worf" in msg

    def test_ontology_before_memories(self) -> None:
        """Ontology identity appears before recent memories section."""
        agent = _make_agent()
        obs = _base_observation({
            "ontology": WORF_ONTOLOGY,
            "recent_memories": [{"reflection": "Reviewed security logs."}],
        })
        msg = agent._build_user_message(obs)
        identity_pos = msg.index("You are Worf")
        memory_pos = msg.index("Recent memories")
        assert identity_pos < memory_pos
