"""AD-1022: WorkstationTypeRegistry + tiered OSS/commercial registration seam.

Covers (real objects throughout — no MagicMock at the registry/overlay boundary,
BF-287): registry register/resolve/list_available incl. tiered resolution and
availability gating; the ``GET /api/workstations/types`` handler (dormant when
disabled, OSS-only in OSS mode, commercial appears when loaded, render target
never serialized); the **mode-toggle proof** driven through the real AD-697
``reset_for_tests()`` + a real finalize-hook registration; default-OFF config;
and the ``_wire_workstation_types`` finalize step.
"""

from __future__ import annotations

import types

import pytest

from probos.config import SystemConfig, WorkstationsConfig
from probos.routers.workstations import (
    WorkstationTypesResponse,
    list_workstation_types,
)
from probos.startup.finalize import _wire_workstation_types
from probos.workstations.registry import (
    COMMERCIAL_TIER,
    OSS_TIER,
    WorkstationRender,
    WorkstationType,
    WorkstationTypeRegistry,
)


# ---------------------------------------------------------------------------
# Helpers (real objects — no MagicMock at the boundary)
# ---------------------------------------------------------------------------


def _native(type_id: str, label: str, *, tier: str = OSS_TIER) -> WorkstationType:
    return WorkstationType(
        id=type_id,
        label=label,
        tier=tier,
        render=WorkstationRender(kind="native", component_key=type_id),
    )


def _iframe(type_id: str, label: str, *, tier: str = COMMERCIAL_TIER, url: str = "") -> WorkstationType:
    return WorkstationType(
        id=type_id,
        label=label,
        tier=tier,
        render=WorkstationRender(kind="iframe", url=url or f"/overlay/{type_id}"),
    )


def _fake_runtime(*, enabled: bool, registry: object, commercial_loaded: bool) -> object:
    """A real-attribute fake runtime (config is a real SystemConfig, not a mock)."""
    config = SystemConfig()
    config.workstations = WorkstationsConfig(enabled=enabled)
    return types.SimpleNamespace(
        config=config,
        workstation_type_registry=registry,
        commercial_overlay_loaded=commercial_loaded,
    )


@pytest.fixture(autouse=True)
def _clean_overlay():
    """Isolate every test from the process-global AD-697 overlay registry."""
    from probos.extensions.overlay import reset_for_tests

    reset_for_tests()
    yield
    reset_for_tests()


# ---------------------------------------------------------------------------
# Registry: register
# ---------------------------------------------------------------------------


def test_register_accepts_valid_oss_baseline():
    reg = WorkstationTypeRegistry()
    assert reg.register(_native("monaco", "Code Editor")) is True
    assert reg.all_type_ids() == ("monaco",)


def test_register_rejects_empty_id():
    reg = WorkstationTypeRegistry()
    bad = WorkstationType(id="", label="x", tier=OSS_TIER, render=WorkstationRender(kind="native"))
    assert reg.register(bad) is False
    assert reg.all_type_ids() == ()


def test_register_rejects_bad_tier():
    reg = WorkstationTypeRegistry()
    bad = WorkstationType(id="x", label="x", tier="premium", render=WorkstationRender(kind="native"))
    assert reg.register(bad) is False


def test_register_rejects_bad_render_kind():
    reg = WorkstationTypeRegistry()
    bad = WorkstationType(id="x", label="x", tier=OSS_TIER, render=WorkstationRender(kind="webgl"))
    assert reg.register(bad) is False


def test_register_rejects_non_descriptor():
    reg = WorkstationTypeRegistry()
    assert reg.register("not-a-descriptor") is False  # type: ignore[arg-type]


def test_register_last_wins_per_id_tier():
    reg = WorkstationTypeRegistry()
    reg.register(_native("browser", "Old Browser"))
    reg.register(_native("browser", "New Browser"))
    resolved = reg.resolve("browser", commercial_loaded=False)
    assert resolved is not None
    assert resolved.label == "New Browser"
    assert reg.all_type_ids() == ("browser",)  # same (id, tier) key — not duplicated


# ---------------------------------------------------------------------------
# Registry: resolve (tiered)
# ---------------------------------------------------------------------------


def test_resolve_unknown_returns_none():
    reg = WorkstationTypeRegistry()
    assert reg.resolve("nope", commercial_loaded=False) is None
    assert reg.resolve("nope", commercial_loaded=True) is None


def test_resolve_oss_baseline_when_not_loaded():
    reg = WorkstationTypeRegistry()
    reg.register(_native("browser", "Browser", tier=OSS_TIER))
    resolved = reg.resolve("browser", commercial_loaded=False)
    assert resolved is not None and resolved.tier == OSS_TIER


def test_resolve_commercial_wins_when_loaded():
    reg = WorkstationTypeRegistry()
    reg.register(_native("browser", "Browser", tier=OSS_TIER))
    reg.register(_iframe("browser", "Immersive Browser", tier=COMMERCIAL_TIER))
    # Loaded -> commercial variant wins for the SAME id.
    loaded = reg.resolve("browser", commercial_loaded=True)
    assert loaded is not None and loaded.tier == COMMERCIAL_TIER
    # Not loaded -> OSS baseline.
    unloaded = reg.resolve("browser", commercial_loaded=False)
    assert unloaded is not None and unloaded.tier == OSS_TIER


def test_resolve_commercial_only_absent_when_not_loaded():
    reg = WorkstationTypeRegistry()
    reg.register(_iframe("immersive-demo", "Immersive (demo)", tier=COMMERCIAL_TIER))
    assert reg.resolve("immersive-demo", commercial_loaded=False) is None
    assert reg.resolve("immersive-demo", commercial_loaded=True) is not None


# ---------------------------------------------------------------------------
# Registry: list_available (availability gating + dedupe)
# ---------------------------------------------------------------------------


def test_list_available_oss_mode_excludes_commercial_only():
    reg = WorkstationTypeRegistry()
    reg.register(_native("monaco", "Code Editor"))
    reg.register(_iframe("immersive-demo", "Immersive (demo)"))
    ids = [t.id for t in reg.list_available(commercial_loaded=False)]
    assert ids == ["monaco"]


def test_list_available_overlay_mode_includes_commercial_only():
    reg = WorkstationTypeRegistry()
    reg.register(_native("monaco", "Code Editor"))
    reg.register(_iframe("immersive-demo", "Immersive (demo)"))
    ids = sorted(t.id for t in reg.list_available(commercial_loaded=True))
    assert ids == ["immersive-demo", "monaco"]


def test_list_available_dedupes_same_id_to_resolved_variant():
    reg = WorkstationTypeRegistry()
    reg.register(_native("browser", "Browser", tier=OSS_TIER))
    reg.register(_iframe("browser", "Immersive Browser", tier=COMMERCIAL_TIER))
    # Overlay mode: the id appears ONCE, as the commercial variant.
    overlay = reg.list_available(commercial_loaded=True)
    assert [t.id for t in overlay] == ["browser"]
    assert overlay[0].tier == COMMERCIAL_TIER
    # OSS mode: the id appears ONCE, as the OSS baseline.
    oss = reg.list_available(commercial_loaded=False)
    assert [t.id for t in oss] == ["browser"]
    assert oss[0].tier == OSS_TIER


# ---------------------------------------------------------------------------
# Config: default-OFF
# ---------------------------------------------------------------------------


def test_workstations_config_default_off():
    assert WorkstationsConfig().enabled is False
    assert SystemConfig().workstations.enabled is False


# ---------------------------------------------------------------------------
# finalize: _wire_workstation_types
# ---------------------------------------------------------------------------


def test_wire_disabled_constructs_dormant_registry():
    runtime = types.SimpleNamespace()
    config = SystemConfig()
    config.workstations = WorkstationsConfig(enabled=False)
    result = _wire_workstation_types(runtime=runtime, config=config)
    assert result is False
    # Registry is still constructed (so an overlay hook can register), just empty.
    assert isinstance(runtime.workstation_type_registry, WorkstationTypeRegistry)
    assert runtime.workstation_type_registry.all_type_ids() == ()


def test_wire_enabled_registers_oss_baselines():
    runtime = types.SimpleNamespace()
    config = SystemConfig()
    config.workstations = WorkstationsConfig(enabled=True)
    result = _wire_workstation_types(runtime=runtime, config=config)
    assert result is True
    reg = runtime.workstation_type_registry
    assert reg.all_type_ids() == ("browser", "chat", "monaco")
    # All baselines are OSS-tier native types.
    for wtype in reg.list_available(commercial_loaded=False):
        assert wtype.tier == OSS_TIER
        assert wtype.render.kind == "native"


# ---------------------------------------------------------------------------
# API handler: gating, OSS-only, commercial appears, no url leak
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_dormant_when_disabled():
    reg = WorkstationTypeRegistry()
    reg.register(_native("monaco", "Code Editor"))
    runtime = _fake_runtime(enabled=False, registry=reg, commercial_loaded=False)
    resp = await list_workstation_types(runtime=runtime)
    assert isinstance(resp, WorkstationTypesResponse)
    assert resp.types == []


@pytest.mark.asyncio
async def test_api_registry_absent_returns_empty():
    runtime = _fake_runtime(enabled=True, registry=None, commercial_loaded=False)
    resp = await list_workstation_types(runtime=runtime)
    assert resp.types == []


@pytest.mark.asyncio
async def test_api_oss_mode_returns_only_oss_types():
    reg = WorkstationTypeRegistry()
    reg.register(_native("monaco", "Code Editor"))
    reg.register(_iframe("immersive-demo", "Immersive (demo)"))
    runtime = _fake_runtime(enabled=True, registry=reg, commercial_loaded=False)
    resp = await list_workstation_types(runtime=runtime)
    ids = [v.id for v in resp.types]
    assert ids == ["monaco"]
    assert all(v.tier == OSS_TIER for v in resp.types)


@pytest.mark.asyncio
async def test_api_overlay_mode_includes_commercial_type():
    reg = WorkstationTypeRegistry()
    reg.register(_native("monaco", "Code Editor"))
    reg.register(_iframe("immersive-demo", "Immersive (demo)"))
    runtime = _fake_runtime(enabled=True, registry=reg, commercial_loaded=True)
    resp = await list_workstation_types(runtime=runtime)
    ids = sorted(v.id for v in resp.types)
    assert ids == ["immersive-demo", "monaco"]


@pytest.mark.asyncio
async def test_api_never_serializes_commercial_render_target():
    secret_url = "/overlay/immersive-demo-secret-path"
    reg = WorkstationTypeRegistry()
    reg.register(_iframe("immersive-demo", "Immersive (demo)", url=secret_url))
    runtime = _fake_runtime(enabled=True, registry=reg, commercial_loaded=True)
    resp = await list_workstation_types(runtime=runtime)
    dumped = resp.model_dump()
    blob = str(dumped)
    # The render target (url/resource_uri/component_key) must NEVER be serialized.
    assert secret_url not in blob
    assert "resource_uri" not in blob
    assert "component_key" not in blob
    assert "url" not in blob
    # Each item carries exactly the DD-4 catalog keys.
    for item in dumped["types"]:
        assert set(item.keys()) == {"id", "label", "tier", "available", "render_kind"}
        assert item["render_kind"] == "iframe"


# ---------------------------------------------------------------------------
# THE HEADLINE: mode-toggle proof via the real AD-697 finalize-hook seam
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mode_toggle_proof_demo_absent_in_oss_present_in_overlay():
    """Demo commercial type is ABSENT in OSS mode and PRESENT in overlay mode.

    Driven through the REAL overlay seam (``register_finalize_hook`` +
    ``run_finalize_hooks`` + ``is_commercial_loaded``) on a REAL registry — no
    MagicMock at the overlay boundary (BF-287). Simulates exactly what the private
    commercial overlay's finalize hook does (the OSS test must not import the
    commercial package — boundary rule).
    """
    from probos.extensions.overlay import (
        is_commercial_loaded,
        register_finalize_hook,
        run_finalize_hooks,
    )

    registry = WorkstationTypeRegistry()
    registry.register(_native("browser", "Browser", tier=OSS_TIER))

    # Before any overlay: pure-OSS — flag false, demo absent.
    assert is_commercial_loaded() is False
    oss_ids = [t.id for t in registry.list_available(commercial_loaded=is_commercial_loaded())]
    assert "immersive-demo" not in oss_ids
    assert oss_ids == ["browser"]

    # Simulate the commercial overlay's AD-697 finalize hook (provider="commercial").
    def _demo_hook(runtime: object, _config: object) -> None:
        runtime.workstation_type_registry.register(  # type: ignore[attr-defined]
            WorkstationType(
                id="immersive-demo",
                label="Immersive Cockpit (demo)",
                tier=COMMERCIAL_TIER,
                render=WorkstationRender(kind="iframe", url="/overlay/immersive-demo"),
            )
        )

    register_finalize_hook("test.workstation_demo", _demo_hook, provider="commercial")
    fake_runtime = types.SimpleNamespace(workstation_type_registry=registry)
    await run_finalize_hooks(fake_runtime, object())

    # After the overlay registered: flag true, demo present.
    assert is_commercial_loaded() is True
    overlay_ids = sorted(
        t.id for t in registry.list_available(commercial_loaded=is_commercial_loaded())
    )
    assert "immersive-demo" in overlay_ids
    assert overlay_ids == ["browser", "immersive-demo"]

    # The toggle is the ONLY difference: in pure-OSS resolution the demo stays absent
    # even though it is now registered.
    still_oss = [t.id for t in registry.list_available(commercial_loaded=False)]
    assert "immersive-demo" not in still_oss
