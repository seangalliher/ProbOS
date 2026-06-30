"""AD-481 v1: Extension-First Architecture tests.

Eight test classes covering:
- TestExtensionProtocol — ExtensionType / ExtensionRiskLevel / ExtensionState /
  ExtensionManifest / EXTENSION_API_VERSION / ExtensionsConfig.
- TestExtensionRegistry — register/approve/disable/enable/remove + listing.
- TestExtensionDiscovery — filesystem scan + manifest validation + semver.
- TestExtensionStateStore — extension_states SQLite persistence.
- TestSkillManifest — skill.yaml + load_skill_from_manifest adapter.
- TestSealedCore — sealed_modules.yaml + is_sealed_path helper +
  Builder _check_sealed_path warn behaviour.
- TestExtensionProfiles — minimal / developer / full preset YAMLs.
- TestSlashExtensionsCommand — /extensions list/enable/disable/remove/profile/info.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from rich.console import Console

from probos.extensions.discovery import ExtensionDiscovery
from probos.extensions.profiles import (
    ExtensionProfile,
    apply_profile,
    load_profile,
)
from probos.extensions.protocol import (
    EXTENSION_API_VERSION,
    Extension,
    ExtensionManifest,
    ExtensionRiskLevel,
    ExtensionState,
    ExtensionType,
    ExtensionsConfig,
)
from probos.extensions.registry import ExtensionRegistry, ExtensionRegistryError
from probos.extensions.sealed_core import is_sealed_path, load_sealed_globs
from probos.extensions.skill_manifest import SkillManifest, load_skill_from_manifest
from probos.extensions.state_store import ExtensionStateStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(
    extension_id: str = "ext_demo",
    extension_type: ExtensionType = ExtensionType.AGENT,
    risk_level: ExtensionRiskLevel = ExtensionRiskLevel.LOW,
    name: str = "Demo Extension",
    version: str = "1.0.0",
    required_api_version: str = EXTENSION_API_VERSION,
    **kwargs,
) -> ExtensionManifest:
    return ExtensionManifest(
        extension_id=extension_id,
        extension_type=extension_type,
        risk_level=risk_level,
        name=name,
        version=version,
        required_api_version=required_api_version,
        **kwargs,
    )


class _FakeExtension(Extension):
    """Minimal Extension implementation for registry tests."""

    def __init__(self, manifest: ExtensionManifest) -> None:
        self._manifest = manifest
        self.activate_calls = 0
        self.deactivate_calls = 0

    @property
    def manifest(self) -> ExtensionManifest:
        return self._manifest

    async def activate(self, runtime) -> None:  # noqa: ANN001
        self.activate_calls += 1

    async def deactivate(self, runtime) -> None:  # noqa: ANN001
        self.deactivate_calls += 1


class _FakeStateStore:
    def __init__(self) -> None:
        self.records: list[tuple[str, ExtensionState, ExtensionManifest]] = []
        self.profile_set: str | None = None

    async def record_state(
        self,
        extension_id: str,
        state: ExtensionState,
        manifest: ExtensionManifest,
        profile: str = "",
    ) -> None:
        self.records.append((extension_id, state, manifest))

    async def set_profile(self, profile: str) -> None:
        self.profile_set = profile


# ---------------------------------------------------------------------------
# TestExtensionProtocol — ~10 tests
# ---------------------------------------------------------------------------


class TestExtensionProtocol:
    def test_extension_type_values(self) -> None:
        assert ExtensionType.AGENT.value == "agent"
        assert ExtensionType.TOOL.value == "tool"
        assert ExtensionType.SKILL.value == "skill"
        assert ExtensionType.CHANNEL_ADAPTER.value == "channel_adapter"
        assert ExtensionType.MODEL_PROVIDER.value == "model_provider"
        assert ExtensionType.PERCEPTION_PROCESSOR.value == "perception_processor"
        assert ExtensionType.INTENT_SUBSCRIBER.value == "intent_subscriber"
        assert ExtensionType.EVENT_HOOK.value == "event_hook"

    def test_extension_risk_level_values(self) -> None:
        assert ExtensionRiskLevel.LOW.value == "low"
        assert ExtensionRiskLevel.MEDIUM.value == "medium"
        assert ExtensionRiskLevel.HIGH.value == "high"

    def test_extension_state_values(self) -> None:
        assert ExtensionState.PENDING_APPROVAL.value == "pending_approval"
        assert ExtensionState.ENABLED.value == "enabled"
        assert ExtensionState.DISABLED.value == "disabled"
        assert ExtensionState.REMOVED.value == "removed"

    def test_extension_manifest_happy_path(self) -> None:
        m = _make_manifest()
        assert m.extension_id == "ext_demo"
        assert m.extension_type == ExtensionType.AGENT
        assert m.risk_level == ExtensionRiskLevel.LOW
        assert m.dependencies == []

    def test_extension_manifest_rejects_bad_id(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _make_manifest(extension_id="bad id with spaces!")

    def test_extension_manifest_rejects_bad_semver(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _make_manifest(version="not-a-version")

    def test_extension_manifest_default_values(self) -> None:
        m = _make_manifest()
        assert m.author == ""
        assert m.license == ""
        assert m.description == ""
        assert m.metadata == {}
        assert m.platform_constraints == []

    def test_extension_api_version_format(self) -> None:
        parts = EXTENSION_API_VERSION.split(".")
        assert 1 <= len(parts) <= 3
        assert all(p.isdigit() for p in parts)

    def test_extensions_config_defaults_all_safe(self) -> None:
        cfg = ExtensionsConfig()
        assert cfg.enabled is False
        assert cfg.enforce_sealed_core is False
        assert cfg.default_profile == "minimal"
        assert cfg.extensions_dir == "src/probos/extensions"

    def test_extensions_config_rejects_unknown_profile(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ExtensionsConfig(default_profile="bogus")


# ---------------------------------------------------------------------------
# TestExtensionRegistry — ~12 tests
# ---------------------------------------------------------------------------


class TestExtensionRegistry:
    @pytest.mark.asyncio
    async def test_register_low_risk_auto_enables(self) -> None:
        registry = ExtensionRegistry(runtime=object(), state_store=_FakeStateStore())
        ext = _FakeExtension(_make_manifest("ext1", risk_level=ExtensionRiskLevel.LOW))
        state = await registry.register(ext)
        assert state == ExtensionState.ENABLED
        assert ext.activate_calls == 1

    @pytest.mark.asyncio
    async def test_register_medium_risk_pending(self) -> None:
        registry = ExtensionRegistry(runtime=object())
        ext = _FakeExtension(_make_manifest("ext1", risk_level=ExtensionRiskLevel.MEDIUM))
        state = await registry.register(ext)
        assert state == ExtensionState.PENDING_APPROVAL
        assert ext.activate_calls == 0

    @pytest.mark.asyncio
    async def test_register_high_risk_raises(self) -> None:
        registry = ExtensionRegistry(runtime=object())
        ext = _FakeExtension(_make_manifest("ext1", risk_level=ExtensionRiskLevel.HIGH))
        with pytest.raises(ExtensionRegistryError):
            await registry.register(ext)

    @pytest.mark.asyncio
    async def test_register_duplicate_raises(self) -> None:
        registry = ExtensionRegistry(runtime=object())
        await registry.register(_FakeExtension(_make_manifest("dup")))
        with pytest.raises(ExtensionRegistryError):
            await registry.register(_FakeExtension(_make_manifest("dup")))

    @pytest.mark.asyncio
    async def test_approve_extension_transitions_to_enabled(self) -> None:
        registry = ExtensionRegistry(runtime=object())
        ext = _FakeExtension(_make_manifest("ext1", risk_level=ExtensionRiskLevel.MEDIUM))
        await registry.register(ext)
        await registry.approve_extension("ext1")
        assert registry.get_state("ext1") == ExtensionState.ENABLED
        assert ext.activate_calls == 1

    @pytest.mark.asyncio
    async def test_approve_extension_non_pending_raises(self) -> None:
        registry = ExtensionRegistry(runtime=object())
        await registry.register(_FakeExtension(_make_manifest("ext1")))  # LOW → already ENABLED
        with pytest.raises(ExtensionRegistryError):
            await registry.approve_extension("ext1")

    @pytest.mark.asyncio
    async def test_disable_then_enable_round_trip(self) -> None:
        registry = ExtensionRegistry(runtime=object())
        ext = _FakeExtension(_make_manifest("ext1"))
        await registry.register(ext)
        await registry.disable("ext1")
        assert registry.get_state("ext1") == ExtensionState.DISABLED
        await registry.enable("ext1")
        assert registry.get_state("ext1") == ExtensionState.ENABLED
        assert ext.activate_calls == 2

    @pytest.mark.asyncio
    async def test_remove_transitions_to_removed_drops_instance(self) -> None:
        registry = ExtensionRegistry(runtime=object())
        await registry.register(_FakeExtension(_make_manifest("ext1")))
        await registry.remove("ext1")
        assert registry.get_state("ext1") == ExtensionState.REMOVED
        # Manifest preserved as audit row
        assert registry.get_manifest("ext1") is not None
        # Instance dropped — second remove raises
        with pytest.raises(ExtensionRegistryError):
            await registry.remove("ext1")

    @pytest.mark.asyncio
    async def test_list_extensions_returns_all(self) -> None:
        registry = ExtensionRegistry(runtime=object())
        await registry.register(_FakeExtension(_make_manifest("a")))
        await registry.register(_FakeExtension(_make_manifest("b")))
        await registry.register(
            _FakeExtension(_make_manifest("c", risk_level=ExtensionRiskLevel.MEDIUM))
        )
        ids = sorted(m.extension_id for m in registry.list_extensions())
        assert ids == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_list_by_type_filters(self) -> None:
        registry = ExtensionRegistry(runtime=object())
        await registry.register(
            _FakeExtension(_make_manifest("a", extension_type=ExtensionType.AGENT))
        )
        await registry.register(
            _FakeExtension(_make_manifest("t", extension_type=ExtensionType.TOOL))
        )
        agents = registry.list_by_type(ExtensionType.AGENT)
        assert len(agents) == 1 and agents[0].extension_id == "a"

    @pytest.mark.asyncio
    async def test_list_enabled_excludes_disabled_pending_removed(self) -> None:
        registry = ExtensionRegistry(runtime=object())
        await registry.register(_FakeExtension(_make_manifest("on")))
        await registry.register(_FakeExtension(_make_manifest("off")))
        await registry.disable("off")
        await registry.register(
            _FakeExtension(_make_manifest("pending", risk_level=ExtensionRiskLevel.MEDIUM))
        )
        enabled = [m.extension_id for m in registry.list_enabled()]
        assert enabled == ["on"]

    @pytest.mark.asyncio
    async def test_state_store_called_on_every_transition(self) -> None:
        store = _FakeStateStore()
        registry = ExtensionRegistry(runtime=object(), state_store=store)
        await registry.register(_FakeExtension(_make_manifest("ext1")))
        await registry.disable("ext1")
        await registry.enable("ext1")
        await registry.remove("ext1")
        # 4 transitions recorded
        assert len(store.records) == 4
        states = [r[1] for r in store.records]
        assert states == [
            ExtensionState.ENABLED,
            ExtensionState.DISABLED,
            ExtensionState.ENABLED,
            ExtensionState.REMOVED,
        ]


# ---------------------------------------------------------------------------
# TestExtensionDiscovery — ~10 tests
# ---------------------------------------------------------------------------


def _write_manifest(dir_path: Path, **fields) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    manifest_path = dir_path / "extension.yaml"
    defaults: dict = {
        "extension_id": "test_ext",
        "extension_type": "agent",
        "name": "Test",
        "version": "1.0.0",
        "required_api_version": EXTENSION_API_VERSION,
    }
    defaults.update(fields)
    manifest_path.write_text(yaml.safe_dump(defaults), encoding="utf-8")
    return manifest_path


class TestExtensionDiscovery:
    def test_scan_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        d = ExtensionDiscovery(tmp_path / "does-not-exist")
        assert d.scan() == []

    def test_scan_dir_without_subdirs_returns_empty(self, tmp_path: Path) -> None:
        d = ExtensionDiscovery(tmp_path)
        assert d.scan() == []

    def test_scan_valid_manifest_under_agents(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path / "agents" / "demo")
        d = ExtensionDiscovery(tmp_path)
        manifests = d.scan()
        assert len(manifests) == 1
        assert manifests[0].extension_id == "test_ext"

    def test_scan_invalid_yaml_logged_and_skipped(
        self, tmp_path: Path, caplog
    ) -> None:
        sub = tmp_path / "agents" / "broken"
        sub.mkdir(parents=True)
        (sub / "extension.yaml").write_text(": :: invalid yaml ::", encoding="utf-8")
        d = ExtensionDiscovery(tmp_path)
        with caplog.at_level(logging.WARNING):
            assert d.scan() == []

    def test_scan_failing_pydantic_validation_skipped(self, tmp_path: Path) -> None:
        sub = tmp_path / "agents" / "bad"
        sub.mkdir(parents=True)
        (sub / "extension.yaml").write_text(
            yaml.safe_dump({"extension_id": "bad", "name": "X"}),  # missing required fields
            encoding="utf-8",
        )
        d = ExtensionDiscovery(tmp_path)
        assert d.scan() == []

    def test_scan_major_version_mismatch_rejected(self, tmp_path: Path) -> None:
        _write_manifest(
            tmp_path / "agents" / "future", required_api_version="2.0.0"
        )
        d = ExtensionDiscovery(tmp_path)
        assert d.scan() == []

    def test_scan_minor_version_drift_accepted(self, tmp_path: Path) -> None:
        major = EXTENSION_API_VERSION.split(".")[0]
        _write_manifest(
            tmp_path / "agents" / "tweaked", required_api_version=f"{major}.99.99"
        )
        d = ExtensionDiscovery(tmp_path)
        assert len(d.scan()) == 1

    def test_scan_all_five_subdirs(self, tmp_path: Path) -> None:
        cases = [
            ("agents", "agent", "a"),
            ("tools", "tool", "b"),
            ("skills", "skill", "c"),
            ("channels", "channel_adapter", "d"),
            ("hooks", "event_hook", "e"),
        ]
        for sub, etype, eid in cases:
            _write_manifest(
                tmp_path / sub / eid,
                extension_id=eid,
                extension_type=etype,
            )
        d = ExtensionDiscovery(tmp_path)
        manifests = d.scan()
        assert len(manifests) == 5

    def test_scan_nested_extension_dir_supported_via_rglob(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path / "agents" / "vendor" / "deep" / "demo")
        d = ExtensionDiscovery(tmp_path)
        assert len(d.scan()) == 1

    def test_scan_non_mapping_yaml_rejected(self, tmp_path: Path) -> None:
        sub = tmp_path / "agents" / "list"
        sub.mkdir(parents=True)
        (sub / "extension.yaml").write_text("- item1\n- item2\n", encoding="utf-8")
        d = ExtensionDiscovery(tmp_path)
        assert d.scan() == []


# ---------------------------------------------------------------------------
# TestExtensionStateStore — ~10 tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def state_store(tmp_path: Path):
    store = ExtensionStateStore(db_path=str(tmp_path / "ext.db"))
    await store.start()
    try:
        yield store
    finally:
        await store.stop()


class TestExtensionStateStore:
    @pytest.mark.asyncio
    async def test_start_creates_table(self, tmp_path: Path) -> None:
        store = ExtensionStateStore(db_path=str(tmp_path / "ext.db"))
        await store.start()
        try:
            # If start succeeded, get_state on unknown id returns None (no exception)
            assert await store.get_state("anything") is None
        finally:
            await store.stop()

    @pytest.mark.asyncio
    async def test_record_state_inserts_new_row(self, state_store) -> None:
        m = _make_manifest("e1")
        await state_store.record_state("e1", ExtensionState.ENABLED, m)
        assert await state_store.get_state("e1") == ExtensionState.ENABLED

    @pytest.mark.asyncio
    async def test_record_state_upserts_existing(self, state_store) -> None:
        m = _make_manifest("e1")
        await state_store.record_state("e1", ExtensionState.ENABLED, m)
        await state_store.record_state("e1", ExtensionState.DISABLED, m)
        assert await state_store.get_state("e1") == ExtensionState.DISABLED

    @pytest.mark.asyncio
    async def test_enabled_at_set_on_enable(self, state_store) -> None:
        m = _make_manifest("e1")
        await state_store.record_state("e1", ExtensionState.ENABLED, m)
        async with state_store._db.execute(  # noqa: SLF001 — internal verification
            "SELECT enabled_at FROM extension_states WHERE extension_id = 'e1'"
        ) as cur:
            row = await cur.fetchone()
        assert row[0] > 0

    @pytest.mark.asyncio
    async def test_disabled_at_set_on_disable_or_remove(self, state_store) -> None:
        m = _make_manifest("e1")
        await state_store.record_state("e1", ExtensionState.DISABLED, m)
        async with state_store._db.execute(  # noqa: SLF001
            "SELECT disabled_at FROM extension_states WHERE extension_id = 'e1'"
        ) as cur:
            row = await cur.fetchone()
        assert row[0] > 0

    @pytest.mark.asyncio
    async def test_get_state_unknown_returns_none(self, state_store) -> None:
        assert await state_store.get_state("nope") is None

    @pytest.mark.asyncio
    async def test_list_enabled_excludes_disabled(self, state_store) -> None:
        await state_store.record_state(
            "on", ExtensionState.ENABLED, _make_manifest("on")
        )
        await state_store.record_state(
            "off", ExtensionState.DISABLED, _make_manifest("off")
        )
        rows = await state_store.list_enabled()
        ids = [r[0] for r in rows]
        assert ids == ["on"]

    @pytest.mark.asyncio
    async def test_manifest_json_round_trips(self, state_store) -> None:
        m = _make_manifest("e1", description="hello world")
        await state_store.record_state("e1", ExtensionState.ENABLED, m)
        rows = await state_store.list_enabled()
        assert len(rows) == 1
        assert rows[0][1].description == "hello world"

    @pytest.mark.asyncio
    async def test_set_profile_updates_all_rows(self, state_store) -> None:
        await state_store.record_state(
            "a", ExtensionState.ENABLED, _make_manifest("a")
        )
        await state_store.record_state(
            "b", ExtensionState.DISABLED, _make_manifest("b")
        )
        await state_store.set_profile("developer")
        async with state_store._db.execute(  # noqa: SLF001
            "SELECT DISTINCT profile FROM extension_states"
        ) as cur:
            rows = await cur.fetchall()
        assert [r[0] for r in rows] == ["developer"]

    @pytest.mark.asyncio
    async def test_stop_closes_connection(self, tmp_path: Path) -> None:
        store = ExtensionStateStore(db_path=str(tmp_path / "ext.db"))
        await store.start()
        await store.stop()
        # After stop, _db is None — record_state is a no-op
        await store.record_state("x", ExtensionState.ENABLED, _make_manifest("x"))
        # No exception ⇒ pass

    @pytest.mark.asyncio
    async def test_real_db_roundtrip_persists_and_reloads(self, tmp_path: Path) -> None:
        """A new store over the same DB reloads the enabled row from disk and
        re-deserializes the manifest JSON (model_validate_json) — the
        TestExtensionStateStore fixture only ever proves same-connection state."""
        db = str(tmp_path / "ext_roundtrip.db")
        store = ExtensionStateStore(db_path=db)
        await store.start()
        manifest = _make_manifest("e1", name="Demo Extension", version="2.3.0")
        await store.record_state("e1", ExtensionState.ENABLED, manifest)
        await store.stop()

        store2 = ExtensionStateStore(db_path=db)
        await store2.start()
        try:
            assert await store2.get_state("e1") == ExtensionState.ENABLED
            rows = await store2.list_enabled()
            assert len(rows) == 1
            ext_id, loaded_manifest = rows[0]
            assert ext_id == "e1"
            # manifest_json re-deserialized into an ExtensionManifest on reload
            assert isinstance(loaded_manifest, ExtensionManifest)
            assert loaded_manifest.extension_id == "e1"
            assert loaded_manifest.name == "Demo Extension"
            assert loaded_manifest.version == "2.3.0"
        finally:
            await store2.stop()


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
        assert profile.enabled_extensions == ["ext_a", "ext_b"]


# ---------------------------------------------------------------------------
# TestSlashExtensionsCommand — ~12 tests
# ---------------------------------------------------------------------------


class _CapturingConsole:
    """Console stand-in that captures console.print output."""

    def __init__(self) -> None:
        self.output: list[str] = []

    def print(self, *args, **kwargs) -> None:
        # Render args to plain strings; ignore Rich markup
        for a in args:
            self.output.append(str(a))

    def text(self) -> str:
        return "\n".join(self.output)


def _make_runtime_with_registry() -> SimpleNamespace:
    registry = ExtensionRegistry(runtime=object())
    return SimpleNamespace(extension_registry=registry, extension_state_store=None)


class TestSlashExtensionsCommand:
    @pytest.mark.asyncio
    async def test_no_args_prints_usage(self) -> None:
        from probos.experience.commands.commands_extensions import cmd_extensions
        rt = _make_runtime_with_registry()
        con = _CapturingConsole()
        await cmd_extensions(rt, con, "")
        assert "Usage: /extensions" in con.text()

    @pytest.mark.asyncio
    async def test_list_no_extensions_prints_none(self) -> None:
        from probos.experience.commands.commands_extensions import cmd_extensions
        rt = _make_runtime_with_registry()
        con = _CapturingConsole()
        await cmd_extensions(rt, con, "list")
        assert "No extensions registered" in con.text()

    @pytest.mark.asyncio
    async def test_list_with_extensions_renders(self) -> None:
        from probos.experience.commands.commands_extensions import cmd_extensions
        rt = _make_runtime_with_registry()
        await rt.extension_registry.register(_FakeExtension(_make_manifest("a")))
        await rt.extension_registry.register(_FakeExtension(_make_manifest("b")))
        await rt.extension_registry.register(_FakeExtension(_make_manifest("c")))
        con = _CapturingConsole()
        await cmd_extensions(rt, con, "list")
        # Output is a Rich Table object; we just check no error
        assert con.output  # at least one print happened

    @pytest.mark.asyncio
    async def test_enable_unknown_id_prints_error(self) -> None:
        from probos.experience.commands.commands_extensions import cmd_extensions
        rt = _make_runtime_with_registry()
        con = _CapturingConsole()
        await cmd_extensions(rt, con, "enable nonexistent")
        assert "Failed to enable" in con.text()

    @pytest.mark.asyncio
    async def test_enable_disabled_extension_transitions(self) -> None:
        from probos.experience.commands.commands_extensions import cmd_extensions
        rt = _make_runtime_with_registry()
        await rt.extension_registry.register(_FakeExtension(_make_manifest("ext1")))
        await rt.extension_registry.disable("ext1")
        con = _CapturingConsole()
        await cmd_extensions(rt, con, "enable ext1")
        assert rt.extension_registry.get_state("ext1") == ExtensionState.ENABLED

    @pytest.mark.asyncio
    async def test_disable_enabled_extension_transitions(self) -> None:
        from probos.experience.commands.commands_extensions import cmd_extensions
        rt = _make_runtime_with_registry()
        await rt.extension_registry.register(_FakeExtension(_make_manifest("ext1")))
        con = _CapturingConsole()
        await cmd_extensions(rt, con, "disable ext1")
        assert rt.extension_registry.get_state("ext1") == ExtensionState.DISABLED

    @pytest.mark.asyncio
    async def test_remove_drops_from_registry(self) -> None:
        from probos.experience.commands.commands_extensions import cmd_extensions
        rt = _make_runtime_with_registry()
        await rt.extension_registry.register(_FakeExtension(_make_manifest("ext1")))
        con = _CapturingConsole()
        await cmd_extensions(rt, con, "remove ext1")
        assert rt.extension_registry.get_state("ext1") == ExtensionState.REMOVED

    @pytest.mark.asyncio
    async def test_profile_minimal_disables_listed(self) -> None:
        from probos.experience.commands.commands_extensions import cmd_extensions
        rt = _make_runtime_with_registry()
        await rt.extension_registry.register(_FakeExtension(_make_manifest("a")))
        con = _CapturingConsole()
        await cmd_extensions(rt, con, "profile minimal")
        # Minimal has empty enable list — "a" gets disabled
        assert rt.extension_registry.get_state("a") == ExtensionState.DISABLED

    @pytest.mark.asyncio
    async def test_profile_unknown_name_prints_error(self) -> None:
        from probos.experience.commands.commands_extensions import cmd_extensions
        rt = _make_runtime_with_registry()
        con = _CapturingConsole()
        await cmd_extensions(rt, con, "profile bogus")
        assert "Failed to load profile" in con.text()

    @pytest.mark.asyncio
    async def test_info_unknown_id_prints_error(self) -> None:
        from probos.experience.commands.commands_extensions import cmd_extensions
        rt = _make_runtime_with_registry()
        con = _CapturingConsole()
        await cmd_extensions(rt, con, "info nope")
        assert "Unknown extension" in con.text()

    @pytest.mark.asyncio
    async def test_info_known_id_renders_manifest(self) -> None:
        from probos.experience.commands.commands_extensions import cmd_extensions
        rt = _make_runtime_with_registry()
        await rt.extension_registry.register(
            _FakeExtension(_make_manifest("ext1", description="Hello"))
        )
        con = _CapturingConsole()
        await cmd_extensions(rt, con, "info ext1")
        text = con.text()
        assert "ext1" in text
        assert "Hello" in text

    @pytest.mark.asyncio
    async def test_unknown_subcommand_prints_help(self) -> None:
        from probos.experience.commands.commands_extensions import cmd_extensions
        rt = _make_runtime_with_registry()
        con = _CapturingConsole()
        await cmd_extensions(rt, con, "frobnicate")
        assert "Usage: /extensions" in con.text()
