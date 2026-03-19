"""Tests for Standing Orders -- ProbOS agent instruction system (AD-339)."""

from __future__ import annotations

import pytest
from pathlib import Path

from probos.cognitive.standing_orders import (
    compose_instructions,
    get_department,
    register_department,
    clear_cache,
    _AGENT_DEPARTMENTS,
)


class TestComposeInstructions:
    """Tests for compose_instructions() composition logic."""

    def test_compose_with_all_tiers(self, tmp_path: Path):
        """All four tiers compose in order when files exist."""
        (tmp_path / "federation.md").write_text("Federation rules", encoding="utf-8")
        (tmp_path / "ship.md").write_text("Ship customs", encoding="utf-8")
        (tmp_path / "engineering.md").write_text("Engineering protocols", encoding="utf-8")
        (tmp_path / "builder.md").write_text("Builder learned rules", encoding="utf-8")
        clear_cache()

        result = compose_instructions(
            "builder",
            "I am the Builder.",
            orders_dir=tmp_path,
        )

        assert "I am the Builder." in result
        assert "Federation rules" in result
        assert "Ship customs" in result
        assert "Engineering protocols" in result
        assert "Builder learned rules" in result
        # Verify order: hardcoded first
        idx_hardcoded = result.index("I am the Builder.")
        idx_federation = result.index("Federation rules")
        idx_ship = result.index("Ship customs")
        idx_dept = result.index("Engineering protocols")
        idx_agent = result.index("Builder learned rules")
        assert idx_hardcoded < idx_federation < idx_ship < idx_dept < idx_agent

    def test_compose_without_department(self, tmp_path: Path):
        """Agent without department mapping gets federation + ship but no department."""
        (tmp_path / "federation.md").write_text("Federation", encoding="utf-8")
        (tmp_path / "ship.md").write_text("Ship", encoding="utf-8")
        clear_cache()

        result = compose_instructions(
            "unknown_agent_xyz",
            "I am unknown.",
            orders_dir=tmp_path,
        )

        assert "Federation" in result
        assert "Ship" in result
        assert "Department Protocols" not in result

    def test_compose_with_unknown_agent(self, tmp_path: Path):
        """No agent-specific .md file means no personal standing orders section."""
        (tmp_path / "federation.md").write_text("Federation", encoding="utf-8")
        (tmp_path / "ship.md").write_text("Ship", encoding="utf-8")
        clear_cache()

        result = compose_instructions(
            "nonexistent_agent",
            "Core identity.",
            orders_dir=tmp_path,
        )

        assert "Core identity." in result
        assert "Federation" in result
        assert "Personal Standing Orders" not in result

    def test_compose_empty_directory(self, tmp_path: Path):
        """Empty orders dir returns just the hardcoded instructions."""
        clear_cache()
        result = compose_instructions(
            "builder",
            "I am the Builder.",
            orders_dir=tmp_path,
        )
        assert result == "I am the Builder."

    def test_compose_missing_directory(self, tmp_path: Path):
        """Non-existent orders dir returns just hardcoded instructions."""
        clear_cache()
        missing = tmp_path / "does_not_exist"
        result = compose_instructions(
            "builder",
            "I am the Builder.",
            orders_dir=missing,
        )
        assert result == "I am the Builder."

    def test_compose_preserves_hardcoded_first(self, tmp_path: Path):
        """Hardcoded instructions always appear before standing orders."""
        (tmp_path / "federation.md").write_text("Federation", encoding="utf-8")
        clear_cache()

        result = compose_instructions(
            "builder",
            "HARDCODED_IDENTITY",
            orders_dir=tmp_path,
        )

        assert result.startswith("HARDCODED_IDENTITY")

    def test_compose_with_override_department(self, tmp_path: Path):
        """Override department loads that department's protocols."""
        (tmp_path / "medical.md").write_text("Medical protocols", encoding="utf-8")
        clear_cache()

        result = compose_instructions(
            "builder",
            "I am the Builder.",
            orders_dir=tmp_path,
            department="medical",
        )

        assert "Medical protocols" in result
        assert "Medical Department Protocols" in result


class TestDepartmentLookup:
    """Tests for department mapping functions."""

    def test_department_lookup_builder(self):
        assert get_department("builder") == "engineering"

    def test_department_lookup_architect(self):
        assert get_department("architect") == "science"

    def test_department_lookup_diagnostician(self):
        assert get_department("diagnostician") == "medical"

    def test_department_lookup_unknown(self):
        assert get_department("unknown_agent_xyz") is None

    def test_register_department(self):
        """register_department() adds a new agent-department mapping."""
        register_department("new_test_agent", "engineering")
        try:
            assert get_department("new_test_agent") == "engineering"
        finally:
            _AGENT_DEPARTMENTS.pop("new_test_agent", None)


class TestCacheBehavior:
    """Tests for cache management."""

    def test_cache_clear_reloads(self, tmp_path: Path):
        """After clear_cache(), modified files are re-read."""
        f = tmp_path / "federation.md"
        f.write_text("Version 1", encoding="utf-8")
        clear_cache()

        result1 = compose_instructions("test", "base", orders_dir=tmp_path)
        assert "Version 1" in result1

        f.write_text("Version 2", encoding="utf-8")
        clear_cache()

        result2 = compose_instructions("test", "base", orders_dir=tmp_path)
        assert "Version 2" in result2
