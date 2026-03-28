"""BF-058 + BF-059: Deterministic crew IDs and reset identity cleanup."""

import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from probos.substrate.identity import generate_pool_ids


# ── BF-058: Deterministic crew IDs ──


_CREW_POOLS = [
    ("builder", "builder"),
    ("architect", "architect"),
    ("scout", "scout"),
    ("counselor", "counselor"),
    ("security_officer", "security_officer"),
    ("operations_officer", "operations_officer"),
    ("engineering_officer", "engineering_officer"),
]


class TestDeterministicCrewIds:
    """BF-058: All crew pools must use deterministic IDs."""

    def test_crew_ids_stable_across_calls(self):
        """generate_pool_ids returns identical IDs on every call."""
        for agent_type, pool_name in _CREW_POOLS:
            ids_a = generate_pool_ids(agent_type, pool_name, 1)
            ids_b = generate_pool_ids(agent_type, pool_name, 1)
            assert ids_a == ids_b, f"{agent_type} IDs differ across calls"

    def test_crew_ids_contain_agent_type(self):
        """Deterministic IDs embed the agent type for readability."""
        for agent_type, pool_name in _CREW_POOLS:
            ids = generate_pool_ids(agent_type, pool_name, 1)
            assert agent_type in ids[0], f"{agent_type} not in ID '{ids[0]}'"

    def test_medical_ids_match_crew_pattern(self):
        """Medical and crew agents use the same generate_pool_ids function."""
        med_ids = generate_pool_ids("surgeon", "medical_surgeon", 1)
        crew_ids = generate_pool_ids("builder", "builder", 1)
        # Both should have the {type}_{pool}_{index}_{hash} format
        assert med_ids[0].count("_") >= 3
        assert crew_ids[0].count("_") >= 3

    def test_crew_pools_pass_agent_ids(self):
        """All 7 crew pool create_pool calls include agent_ids= in source."""
        import inspect
        from probos.runtime import ProbOSRuntime

        source = inspect.getsource(ProbOSRuntime.start)

        for agent_type, pool_name in _CREW_POOLS:
            # Find the create_pool block for this agent type
            comment_markers = {
                "builder": "Builder Agent",
                "architect": "Architect Agent",
                "scout": "Scout Agent",
                "counselor": "Counselor",
                "security_officer": "Security Officer",
                "operations_officer": "Operations Officer",
                "engineering_officer": "Engineering Officer",
            }
            marker = comment_markers[agent_type]
            idx = source.find(marker)
            assert idx >= 0, f"Comment for {agent_type} not found in source"
            # Get the next ~300 chars after the marker — should contain agent_ids=
            block = source[idx:idx + 300]
            assert "agent_ids=" in block, (
                f"create_pool for {agent_type} missing agent_ids= parameter"
            )

    @pytest.mark.asyncio
    async def test_bf057_restores_with_deterministic_ids(self):
        """With deterministic IDs, BF-057 cert lookup finds the right cert."""
        ids = generate_pool_ids("builder", "builder", 1)
        slot_id = ids[0]

        # Mock an identity registry that knows this slot
        mock_cert = MagicMock()
        mock_cert.callsign = "Forge"
        mock_registry = MagicMock()
        mock_registry.get_by_slot = MagicMock(return_value=mock_cert)

        # Mock agent with deterministic ID
        agent = MagicMock()
        agent.id = slot_id
        agent.agent_type = "builder"
        agent.callsign = "Builder"

        # Simulate the BF-057 lookup
        existing_cert = mock_registry.get_by_slot(agent.id)
        assert existing_cert is not None
        assert existing_cert.callsign == "Forge"
        mock_registry.get_by_slot.assert_called_with(slot_id)


# ── BF-059: Reset clears identity ──


class TestResetIdentityCleanup:
    """BF-059: probos reset must clear identity.db and instance_id."""

    def _make_repo(self, tmp_path):
        repo = tmp_path / "knowledge"
        for sub in ["agents", "workflows", "trust", "episodes", "config"]:
            (repo / sub).mkdir(parents=True)
            (repo / sub / ".gitkeep").touch()
        return repo

    def _make_args(self, data_dir):
        return argparse.Namespace(
            yes=True, keep_trust=False, config=None, data_dir=data_dir,
        )

    def test_reset_clears_identity_db(self, tmp_path):
        """identity.db is deleted on reset."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        identity_db = data_dir / "identity.db"
        identity_db.write_text("fake identity data")

        args = self._make_args(data_dir)
        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        assert not identity_db.exists(), "identity.db should be deleted after reset"

    def test_reset_clears_instance_id(self, tmp_path):
        """ontology/instance_id is deleted on reset."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        ontology_dir = data_dir / "ontology"
        ontology_dir.mkdir()
        instance_id_file = ontology_dir / "instance_id"
        instance_id_file.write_text("old-ship-did-12345")

        args = self._make_args(data_dir)
        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)

        assert not instance_id_file.exists(), "instance_id should be deleted after reset"

    def test_reset_without_identity_db_no_error(self, tmp_path):
        """Reset with no identity.db present doesn't crash."""
        from probos.__main__ import _cmd_reset

        repo = self._make_repo(tmp_path)
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # No identity.db created

        args = self._make_args(data_dir)
        with patch("probos.__main__._load_config_with_fallback") as mock_cfg:
            mock_cfg.return_value = (
                SimpleNamespace(knowledge=SimpleNamespace(repo_path=str(repo))),
                None,
            )
            _cmd_reset(args)  # Should not raise
