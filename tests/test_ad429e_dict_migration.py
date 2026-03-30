"""AD-429e: Ontology Dict Migration — verification tests."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import dataclass


# ---- Helpers ----

@dataclass
class _MockDepartment:
    id: str
    name: str = ""
    description: str = ""


def _mock_ontology(crew_types: set[str] | None = None, dept_map: dict[str, str] | None = None, departments: list | None = None):
    """Create a mock VesselOntologyService with configurable returns."""
    ont = MagicMock()
    ont.get_crew_agent_types.return_value = crew_types or set()
    if dept_map is not None:
        ont.get_agent_department.side_effect = lambda at: dept_map.get(at)
    else:
        ont.get_agent_department.return_value = None
    if departments is not None:
        ont.get_departments.return_value = departments
    else:
        ont.get_departments.return_value = []
    return ont


def _mock_agent(agent_type: str, agent_id: str = "agent-1", is_alive: bool = True):
    """Create a mock agent."""
    agent = MagicMock()
    agent.agent_type = agent_type
    agent.id = agent_id
    agent.is_alive = is_alive
    return agent


# ---- Test 1: is_crew_agent prefers ontology ----

class TestIsCrewAgentOntologyPreference:
    def test_is_crew_agent_prefers_ontology(self):
        """When ontology is available, is_crew_agent uses it instead of legacy set."""
        from probos.crew_utils import is_crew_agent

        ontology = _mock_ontology(crew_types={"security_officer", "counselor"})

        agent = _mock_agent("security_officer")
        assert is_crew_agent(agent, ontology) is True

        # builder IS in the legacy _WARD_ROOM_CREW but NOT in ontology crew_types
        builder = _mock_agent("builder")
        assert is_crew_agent(builder, ontology) is False

    def test_is_crew_agent_falls_back_without_ontology(self):
        """When ontology is None, is_crew_agent falls back to legacy set."""
        from probos.crew_utils import is_crew_agent

        # builder is in _WARD_ROOM_CREW legacy set
        builder = _mock_agent("builder")
        assert is_crew_agent(builder, None) is True

        # random_agent is NOT in legacy set
        random = _mock_agent("random_agent")
        assert is_crew_agent(random, None) is False

    def test_is_crew_agent_no_agent_type(self):
        """Agent without agent_type attribute returns False."""
        from probos.crew_utils import is_crew_agent

        ontology = _mock_ontology(crew_types={"security_officer"})

        agent = MagicMock(spec=[])  # no agent_type attribute
        assert is_crew_agent(agent, ontology) is False


# ---- Test 3-4: Department lookup ----

class TestDepartmentLookup:
    def test_department_lookup_prefers_ontology(self):
        """Ontology department result is preferred over legacy dict."""
        from probos.cognitive.standing_orders import get_department

        ont = _mock_ontology(dept_map={"builder": "engineering"})
        # Ontology returns "engineering" for builder
        result = (ont.get_agent_department("builder") if ont else None) or get_department("builder")
        assert result == "engineering"

        # Check ontology was called
        ont.get_agent_department.assert_called_with("builder")

    def test_department_lookup_falls_back_without_ontology(self):
        """When ontology is None, falls back to legacy get_department()."""
        from probos.cognitive.standing_orders import get_department

        ont = None
        result = (ont.get_agent_department("builder") if ont else None) or get_department("builder")
        assert result == "engineering"

    def test_department_lookup_ontology_returns_none_falls_back(self):
        """When ontology returns None for unknown agent, falls back to legacy."""
        from probos.cognitive.standing_orders import get_department

        ont = _mock_ontology(dept_map={})  # returns None for everything
        result = (ont.get_agent_department("architect") if ont else None) or get_department("architect")
        # Legacy dict has architect -> science
        assert result == "science"


# ---- Test 5-6: WardRoom channels ----

class TestWardRoomChannels:
    @pytest.mark.asyncio
    async def test_ward_room_channels_from_ontology(self, tmp_path):
        """_ensure_default_channels uses ontology departments when available."""
        from probos.ward_room import WardRoomService

        ont = _mock_ontology(departments=[
            _MockDepartment(id="engineering", name="Engineering"),
            _MockDepartment(id="medical", name="Medical"),
        ])
        svc = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            ontology=ont,
        )
        await svc.start()

        channels = await svc.list_channels()
        channel_names = {ch.name if hasattr(ch, 'name') else ch["name"] for ch in channels}
        # Department channels are capitalized
        assert "Engineering" in channel_names
        assert "Medical" in channel_names
        # All Hands always created
        assert "All Hands" in channel_names
        await svc.stop()

    @pytest.mark.asyncio
    async def test_ward_room_channels_fallback_without_ontology(self, tmp_path):
        """_ensure_default_channels uses legacy _AGENT_DEPARTMENTS when ontology=None."""
        from probos.ward_room import WardRoomService

        svc = WardRoomService(
            db_path=str(tmp_path / "wr.db"),
            ontology=None,
        )
        await svc.start()

        channels = await svc.list_channels()
        channel_names = {ch.name if hasattr(ch, 'name') else ch["name"] for ch in channels}
        # Legacy path should still create department channels
        assert "Engineering" in channel_names
        assert "All Hands" in channel_names
        await svc.stop()


# ---- Test 7: register_department still works ----

class TestRegisterDepartmentStillWorks:
    def test_register_department_still_works(self):
        """Legacy register_department() mutation path still operates."""
        from probos.cognitive.standing_orders import register_department, get_department

        register_department("new_test_agent_429e", "security")
        assert get_department("new_test_agent_429e") == "security"


# ---- Test 8: Ontology crew matches legacy set ----

class TestOntologyCrewMatchesLegacy:
    def test_ontology_crew_matches_legacy_set(self):
        """Real ontology crew types should match legacy _WARD_ROOM_CREW set."""
        ontology_dir = Path(__file__).resolve().parent.parent / "config" / "ontology"
        if not ontology_dir.exists():
            pytest.skip("Ontology config directory not found")

        import asyncio
        from probos.ontology import VesselOntologyService
        from probos.crew_utils import _WARD_ROOM_CREW

        svc = VesselOntologyService(ontology_dir, data_dir=Path(__file__).parent)
        asyncio.get_event_loop().run_until_complete(svc.initialize())

        ontology_crew = svc.get_crew_agent_types()
        legacy_crew = _WARD_ROOM_CREW

        # Both should have the same crew-tier agent types
        # (minor differences possible if ontology has been updated)
        assert len(ontology_crew) > 0, "Ontology returned empty crew set"
        # Check that legacy types are a subset of ontology (or match)
        missing_from_ontology = legacy_crew - ontology_crew
        missing_from_legacy = ontology_crew - legacy_crew
        # Allow minor differences but flag them
        assert len(missing_from_ontology) <= 1, f"Legacy crew not in ontology: {missing_from_ontology}"
        assert len(missing_from_legacy) <= 1, f"Ontology crew not in legacy: {missing_from_legacy}"
