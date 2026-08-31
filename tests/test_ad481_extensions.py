"""AD-481 v1: extension substrate tests, reduced by AD-1215 (#1172).

The ExtensionRegistry model was removed because no runtime ever assigned
``runtime.extension_registry`` — ``registry.py`` / ``discovery.py`` /
``state_store.py`` and the six ``/extensions`` slash handlers were constructed
only here, which is exactly why this file stayed green while the feature was
inert in production. Their five test classes went with them
(TestExtensionProtocol, TestExtensionRegistry, TestExtensionDiscovery,
TestExtensionStateStore, TestSlashExtensionsCommand).

What remains covers the modules that still have live production consumers:
- TestSkillManifest — skill.yaml + load_skill_from_manifest (skill_framework.py)
- TestSealedCore — sealed_modules.yaml + is_sealed_path (cognitive/builder.py)
- TestExtensionProfiles — the preset YAML loader (pure; see #1172 for its
  residual-consumer status now that /extensions is gone)
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from probos.extensions.profiles import (
    ExtensionProfile,
    apply_profile,
    load_profile,
)
from probos.extensions.sealed_core import is_sealed_path, load_sealed_globs
from probos.extensions.skill_manifest import SkillManifest, load_skill_from_manifest



# ---------------------------------------------------------------------------
# TestSkillManifest — ~8 tests
# ---------------------------------------------------------------------------


def _write_skill_yaml(tmp_path: Path, **fields) -> Path:
    defaults = {
        "skill_id": "demo_skill",
        "name": "Demo Skill",
        "version": "1.0.0",
    }
    defaults.update(fields)
    p = tmp_path / "skill.yaml"
    p.write_text(yaml.safe_dump(defaults), encoding="utf-8")
    return p


class TestSkillManifest:
    def test_load_skill_happy_path(self, tmp_path: Path) -> None:
        p = _write_skill_yaml(tmp_path, description="A demo")
        defn = load_skill_from_manifest(p)
        assert defn.skill_id == "demo_skill"
        assert defn.description == "A demo"
        assert defn.origin == "acquired"

    def test_load_skill_missing_required_field_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "skill.yaml"
        p.write_text(yaml.safe_dump({"name": "X"}), encoding="utf-8")  # no skill_id
        with pytest.raises(ValueError):
            load_skill_from_manifest(p)

    def test_load_skill_bad_category_raises(self, tmp_path: Path) -> None:
        p = _write_skill_yaml(tmp_path, category="invalid_cat")
        with pytest.raises(ValueError):
            load_skill_from_manifest(p)

    def test_load_skill_negative_decay_raises(self, tmp_path: Path) -> None:
        p = _write_skill_yaml(tmp_path, decay_rate_days=-1)
        with pytest.raises(ValueError):
            load_skill_from_manifest(p)

    def test_load_skill_preferred_tools_translated(self, tmp_path: Path) -> None:
        p = _write_skill_yaml(
            tmp_path,
            preferred_tools=[
                {"tool_id": "t1", "priority": 1, "context": "primary"},
                {"tool_id": "t2", "priority": 2, "context": ""},
            ],
        )
        defn = load_skill_from_manifest(p)
        assert len(defn.preferred_tools) == 2
        assert defn.preferred_tools[0].tool_id == "t1"
        assert defn.preferred_tools[0].priority == 1

    def test_skill_manifest_dependencies_preserved(self) -> None:
        m = SkillManifest(
            skill_id="x", name="X", version="1.0.0",
            dependencies=["pkg_a>=1.0", "pkg_b"],
        )
        assert m.dependencies == ["pkg_a>=1.0", "pkg_b"]

    def test_load_skill_composite_and_synergy_passthrough(self, tmp_path: Path) -> None:
        p = _write_skill_yaml(
            tmp_path,
            composite_skill_ids=["a", "b"],
            synergy_partners=["c", "d"],
        )
        defn = load_skill_from_manifest(p)
        assert defn.composite_skill_ids == ["a", "b"]
        assert defn.synergy_partners == ["c", "d"]

    @pytest.mark.asyncio
    async def test_skill_registry_register_from_manifest_end_to_end(
        self, tmp_path: Path
    ) -> None:
        from probos.skill_framework import SkillRegistry
        registry = SkillRegistry()
        p = _write_skill_yaml(tmp_path, skill_id="onboarded")
        defn = await registry.register_from_manifest(p)
        assert defn.skill_id == "onboarded"
        looked_up = registry.get_skill("onboarded")
        assert looked_up is not None
        assert looked_up.skill_id == "onboarded"


# ---------------------------------------------------------------------------
# TestSealedCore — ~10 tests
# ---------------------------------------------------------------------------


class TestSealedCore:
    def setup_method(self) -> None:
        load_sealed_globs.cache_clear()

    def teardown_method(self) -> None:
        load_sealed_globs.cache_clear()

    def test_load_sealed_globs_reads_yaml(self, tmp_path: Path) -> None:
        p = tmp_path / "sealed.yaml"
        p.write_text(
            yaml.safe_dump({"sealed_globs": ["src/foo/**", "src/bar.py"]}),
            encoding="utf-8",
        )
        globs = load_sealed_globs(str(p))
        assert "src/foo/**" in globs
        assert "src/bar.py" in globs

    def test_load_sealed_globs_missing_file_returns_empty(
        self, tmp_path: Path
    ) -> None:
        assert load_sealed_globs(str(tmp_path / "nope.yaml")) == ()

    def test_load_sealed_globs_malformed_yaml_returns_empty(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text(": ::not yaml::", encoding="utf-8")
        assert load_sealed_globs(str(p)) == ()

    def test_is_sealed_path_matches_substrate_glob(self) -> None:
        globs = ("src/probos/substrate/**",)
        assert is_sealed_path("src/probos/substrate/agent.py", globs) is True

    def test_is_sealed_path_matches_exact_file(self) -> None:
        globs = ("src/probos/identity.py",)
        assert is_sealed_path("src/probos/identity.py", globs) is True

    def test_is_sealed_path_rejects_extension_subdirs(self) -> None:
        globs = (
            "src/probos/substrate/**",
            "src/probos/extensions/sealed_core.py",
        )
        assert is_sealed_path("src/probos/extensions/agents/foo.py", globs) is False

    def test_is_sealed_path_normalizes_backslashes(self) -> None:
        globs = ("src/probos/substrate/**",)
        assert is_sealed_path("src\\probos\\substrate\\agent.py", globs) is True

    def test_is_sealed_path_unmatched_paths_return_false(self) -> None:
        globs = ("src/probos/substrate/**",)
        assert is_sealed_path("docs/development/roadmap.md", globs) is False

    def test_load_sealed_globs_lru_cache(self, tmp_path: Path) -> None:
        p = tmp_path / "sealed.yaml"
        p.write_text(yaml.safe_dump({"sealed_globs": ["a/**"]}), encoding="utf-8")
        first = load_sealed_globs(str(p))
        second = load_sealed_globs(str(p))
        assert first is second

    def test_check_sealed_path_warns_when_enforce_true(self, caplog) -> None:
        from probos.cognitive.builder import _check_sealed_path
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                extensions=SimpleNamespace(enforce_sealed_core=True)
            )
        )
        # Force a sealed glob that matches our test path — patch the helper to
        # bypass the project sealed_modules.yaml lookup by providing the glob
        # via the underlying is_sealed_path. We use the real function with a
        # path we know is in the default sealed list.
        load_sealed_globs.cache_clear()
        with caplog.at_level(logging.WARNING):
            _check_sealed_path(Path("src/probos/substrate/agent.py"), runtime)
        assert any("sealed-core" in r.message for r in caplog.records)

    def test_check_sealed_path_silent_when_enforce_false(self, caplog) -> None:
        from probos.cognitive.builder import _check_sealed_path
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                extensions=SimpleNamespace(enforce_sealed_core=False)
            )
        )
        with caplog.at_level(logging.WARNING):
            _check_sealed_path(Path("src/probos/substrate/agent.py"), runtime)
        assert not any("sealed-core" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# TestExtensionProfiles — ~8 tests
# ---------------------------------------------------------------------------


class TestExtensionProfiles:
    def test_load_profile_minimal(self) -> None:
        p = load_profile("minimal")
        assert p.profile_name == "minimal"
        assert p.enabled_extensions == []

    def test_load_profile_developer(self) -> None:
        p = load_profile("developer")
        assert p.profile_name == "developer"

    def test_load_profile_full(self) -> None:
        p = load_profile("full")
        assert p.profile_name == "full"

    def test_load_profile_unknown_raises(self) -> None:
        with pytest.raises(ValueError):
            load_profile("bogus")

    def test_apply_profile_returns_enable_list(self) -> None:
        result = apply_profile("minimal")
        assert result == []

    def test_extension_profile_validator_rejects_bad_name(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ExtensionProfile(profile_name="not-real")

    def test_load_profile_missing_required_field_raises(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "minimal.yaml"
        p.write_text(yaml.safe_dump({"description": "no name"}), encoding="utf-8")
        with pytest.raises(Exception):
            load_profile("minimal", profiles_dir=tmp_path)

    def test_load_profile_uses_profiles_dir_param(self, tmp_path: Path) -> None:
        p = tmp_path / "developer.yaml"
        p.write_text(
            yaml.safe_dump({
                "profile_name": "developer",
                "enabled_extensions": ["ext_a", "ext_b"],
            }),
            encoding="utf-8",
        )
        profile = load_profile("developer", profiles_dir=tmp_path)
