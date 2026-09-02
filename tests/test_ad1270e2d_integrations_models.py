"""AD-1270e2 batch 4 -- the ``integrations`` batch left ``config.py`` unchanged.

Eighteen leaf models -- the federation surfaces (ARD catalogue, peer trust, TLS,
multicast discovery, cluster monitor, the federated MCP server and A2A peers),
the two MCP registration models, the credential vault, chat attachments, the
cloud-picker providers, lifecycle hooks, agent packs, the observability bridge,
and the communications/benchmark/Bill trio -- now live in
``probos.config_models.integrations`` and are re-exported from ``probos.config``.

The property under test is that no consumer can tell: same class object, same
qualname, same MRO, same ordered fields, same dumped defaults. A name-only check
would pass a wrapper or a re-declared copy, so the identity assertions compare
``is``.

``EXPECTED_DUMPS`` is generated from ``git show HEAD:src/probos/config.py`` at
authoring time -- the class text *before* the move, compiled in a throwaway
module and evaluated on its own. Had it been derived from the moved module the
assertion would compare the code against itself and pass for any value.

Two of the eighteen are list *element* types with a validator that rejects the
empty instance (``A2APeerConfig`` needs an address, ``MCPServerConfig`` needs a
transport). They carry no default dump, so they are excluded from the
default-dump cases by construction rather than by an exception list that could
silently grow -- see ``MODELS_WITH_DEFAULTS``.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

import probos.config as config_facade
import probos.config_models as config_pkg
import probos.config_models.integrations as config_integrations
from probos.config import SystemConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASELINE = _REPO_ROOT / "docs" / "development" / "config-facade-baseline.yaml"
_INTEGRATIONS_SOURCE = (
    _REPO_ROOT / "src" / "probos" / "config_models" / "integrations.py"
)

#: The batch, named once. Every parametrised case walks exactly these eighteen.
MOVED_MODELS: tuple[str, ...] = (
    "A2APeerConfig",
    "AttachmentsConfig",
    "BillConfig",
    "CloudPickerProviderConfig",
    "CommunicationBenchmarksConfig",
    "CommunicationsConfig",
    "CredentialVaultConfig",
    "FederationArdConfig",
    "FederationClusterMonitorConfig",
    "FederationDiscoveryConfig",
    "FederationMCPServerConfig",
    "FederationPeerTrustConfig",
    "FederationTLSConfig",
    "HooksConfig",
    "MCPAppHostConfig",
    "MCPServerConfig",
    "ObservabilityBridgeConfig",
    "PacksConfig",
)

#: Moved model -> its dotted path under ``SystemConfig``. Ten of the eighteen
#: hang one or two levels down (``federation.*``, ``browser_tool.*``,
#: ``cloud_pickers.*``, ``qualification.*``) rather than off the root.
MODEL_TO_PATH: dict[str, str] = {
    "A2APeerConfig": "federation.a2a.outbound_peers",
    "AttachmentsConfig": "attachments",
    "BillConfig": "bill",
    "CloudPickerProviderConfig": "cloud_pickers.google_drive",
    "CommunicationBenchmarksConfig": "qualification.communication_benchmarks",
    "CommunicationsConfig": "communications",
    "CredentialVaultConfig": "browser_tool.credential_vault",
    "FederationArdConfig": "federation.ard",
    "FederationClusterMonitorConfig": "federation.cluster_monitor",
    "FederationDiscoveryConfig": "federation.discovery",
    "FederationMCPServerConfig": "federation.mcp_server",
    "FederationPeerTrustConfig": "federation.peer_trust",
    "FederationTLSConfig": "federation.tls",
    "HooksConfig": "hooks",
    "MCPAppHostConfig": "mcp_app_host",
    "MCPServerConfig": "mcp.servers",
    "ObservabilityBridgeConfig": "observability_bridge",
    "PacksConfig": "packs",
}

#: The two list-element types. Their validators reject the empty instance, so
#: they compose into ``SystemConfig`` as empty lists and have no default dump.
LIST_ELEMENT_MODELS: tuple[str, ...] = ("A2APeerConfig", "MCPServerConfig")

#: Pre-move ``model_dump(mode="json")`` for each moved model that HAS defaults,
#: measured against ``HEAD``'s ``config.py`` source rather than this module.
EXPECTED_DUMPS: dict[str, dict[str, object]] = {
    "AttachmentsConfig": {
        "enabled": True,
        "serve_remote_enabled": False,
        "auto_resolve_remote_enabled": False,
        "attachments_dir": "data/attachments",
        "max_attachment_bytes": 10485760,
        "allowed_mime_types": [
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/gif",
            "application/pdf",
            "text/plain",
            "text/markdown",
            "application/json",
            "text/csv",
            "audio/webm",
            "audio/wav",
            "audio/mpeg",
            "audio/mp4",
            "audio/ogg",
        ],
        "vision_tier": "vision",
        "text_extraction_max_bytes": 1048576,
        "pdf_extraction_enabled": False,
        "multi_image_warn_threshold": 5,
        "images_per_dm_hard_cap": 8,
        "image_max_dimension": 1024,
        "daily_image_budget_per_captain": 50,
        "image_budget_path": None,
        "vision_tier_overrides": {},
        "max_store_bytes": 5368709120,
    },
    "BillConfig": {
        "max_concurrent_instances": 10,
        "default_step_timeout_seconds": 300.0,
        "allow_partial_assignment": False,
    },
    "CloudPickerProviderConfig": {
        "enabled": False,
        "client_id": "",
        "client_secret": "",
        "redirect_uri": (
            "http://127.0.0.1:8081/api/cloud-pickers/{provider}/callback"
        ),
    },
    "CommunicationBenchmarksConfig": {
        "enabled": True,
        "frequency_hours": 12.0,
        "probes": [
            "thread_relevance",
            "memory_grounding",
            "memory_absence",
            "expertise",
            "silence_appropriateness",
            "dm_action",
        ],
    },
    "CommunicationsConfig": {
        "dm_min_rank": "ensign",
        "recreation_min_rank": "ensign",
        "group_chat_min_rank": "commander",
        "artifact_min_rank": "lieutenant",
        "artifact_max_per_turn": 3,
        "artifact_max_bytes": 262144,
        "a2ui_enabled": False,
        "a2ui_min_rank": "lieutenant",
        "a2ui_max_options": 10,
        "room_todos_enabled": False,
        "room_todos_min_rank": "commander",
        "room_todos_seed_min_rank": "ensign",
        "office_backend": "python-docx",
        "libreoffice_path": "",
        "status_min_rank": "lieutenant",
        "status_max_per_turn": 3,
        "status_max_bytes": 4096,
        "presence_working_window_seconds": 90.0,
        "proactive_conversation_enabled": True,
        "conversational_memory_enabled": True,
        "room_awareness_enabled": True,
        "recall_interpretation_enabled": False,
        "dream_interpretation_enabled": False,
    },
    "CredentialVaultConfig": {
        "enabled": False,
        "backend": "file",
        "file_path": "data/credential_vault.json",
        "keyring_index_path": "data/credential_keyring_index.json",
        "keyring_service_name": "probos.credentials",
        "max_credentials": 100,
        "require_https_for_fill": True,
    },
    "FederationArdConfig": {
        "enabled": False,
        "well_known_path": "/.well-known/ai-catalog.json",
        "discovery_endpoints": [],
        "registry_url": "",
        "publisher_namespace_domain": "",
        "discovery_before_design": False,
        "federation_mode": "none",
        "max_referral_peers": 5,
    },
    "FederationClusterMonitorConfig": {
        "enabled": True,
        "peer_unreachable_seconds": 60.0,
    },
    "FederationDiscoveryConfig": {
        "multicast_enabled": False,
        "multicast_group": "239.255.42.99",
        "multicast_port": 5556,
        "announce_interval_seconds": 5.0,
    },
    "FederationMCPServerConfig": {
        "enabled": False,
        "bind_host": "127.0.0.1",
        "bind_port": 8765,
        "path_prefix": "/mcp",
    },
    "FederationPeerTrustConfig": {
        "probationary_alpha": 1.0,
        "probationary_beta": 3.0,
    },
    "FederationTLSConfig": {
        "enabled": False,
        "cert_file": None,
        "key_file": None,
        "ca_file": None,
        "verify_peer": True,
    },
    "HooksConfig": {"enabled": False},
    "MCPAppHostConfig": {
        "enabled": False,
        "serve_internal_games": True,
        "discover_external_apps": False,
        "internal_default_csp": (
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'"
        ),
        "external_default_csp": (
            "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'"
        ),
        "bundles_dir": "",
    },
    "ObservabilityBridgeConfig": {
        "enabled": True,
        "publish_interval_seconds": 60.0,
        "system_channel": "system_observability",
    },
    "PacksConfig": {"enabled": False, "packs_dir": "data/packs"},
}

#: Derived, never hand-listed: the models that have a default dump are exactly
#: the ones that are not list-element types. Asserting the partition here means
#: a future batch cannot quietly drop a model out of the dump cases.
MODELS_WITH_DEFAULTS: tuple[str, ...] = tuple(
    name for name in MOVED_MODELS if name not in LIST_ELEMENT_MODELS
)


def _load(name: str, path: Path) -> ModuleType:
    """Import a ``scripts/`` module by path; ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _walk(dumped: dict[str, Any], dotted: str) -> Any:
    """Follow a ``MODEL_TO_PATH`` entry into a ``model_dump`` result."""
    node: Any = dumped
    for part in dotted.split("."):
        node = node[part]
    return node


facade = _load("_ad1270e2d_facade", _REPO_ROOT / "scripts" / "check_config_facade.py")


@pytest.fixture(scope="module")
def baseline_models() -> dict[str, dict]:
    document = yaml.safe_load(_BASELINE.read_text(encoding="utf-8"))
    return document["models"]


def test_the_dump_partition_is_exhaustive_and_disjoint() -> None:
    """Guard the guard: EXPECTED_DUMPS must cover exactly the non-element models.

    Without this, dropping a model from ``EXPECTED_DUMPS`` would silently
    shrink the parametrised dump cases instead of failing.
    """
    assert set(EXPECTED_DUMPS) == set(MODELS_WITH_DEFAULTS)
    assert set(LIST_ELEMENT_MODELS).isdisjoint(MODELS_WITH_DEFAULTS)
    assert set(MOVED_MODELS) == set(MODELS_WITH_DEFAULTS) | set(LIST_ELEMENT_MODELS)
    assert set(MODEL_TO_PATH) == set(MOVED_MODELS)


# ---------------------------------------------------------------------------
# Identity and re-export -- the contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_facade_reexports_the_same_object_not_a_copy(name: str) -> None:
    """``is``, not ``==``: a re-declared clone would satisfy equality."""
    assert getattr(config_facade, name) is getattr(config_integrations, name)


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_package_namespace_reexports_the_same_object(name: str) -> None:
    """``config_models/__init__`` must not shadow the module with a copy."""
    assert getattr(config_pkg, name) is getattr(config_integrations, name)
    assert name in config_pkg.__all__


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_identity_matches_the_e1_baseline(
    name: str, baseline_models: dict[str, dict]
) -> None:
    """Qualname, MRO bases and ordered fields are what e1 froze."""
    stored = baseline_models[name]
    model = getattr(config_facade, name)

    assert model.__qualname__ == stored["qualname"]
    assert [base.__name__ for base in model.__mro__[1:]] == stored["bases"]
    assert list(model.model_fields) == [field["name"] for field in stored["fields"]]


def test_the_literal_consumer_spelling_still_imports() -> None:
    """The existing call sites spell it exactly this way."""
    from probos.config import (  # noqa: F401
        A2APeerConfig,
        AttachmentsConfig,
        BillConfig,
        CloudPickerProviderConfig,
        CommunicationBenchmarksConfig,
        CommunicationsConfig,
        CredentialVaultConfig,
        FederationArdConfig,
        FederationClusterMonitorConfig,
        FederationDiscoveryConfig,
        FederationMCPServerConfig,
        FederationPeerTrustConfig,
        FederationTLSConfig,
        HooksConfig,
        MCPAppHostConfig,
        MCPServerConfig,
        ObservabilityBridgeConfig,
        PacksConfig,
    )

    assert A2APeerConfig is config_integrations.A2APeerConfig
    assert PacksConfig is config_integrations.PacksConfig


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_moved_module_is_still_owned_by_the_facade_contract(name: str) -> None:
    """``owns()`` cannot key on ``__module__ == probos.config``.

    That is the one predicate this move breaks. If it did, all eighteen would
    reclassify as import leakage and the baseline would demand a regeneration
    that proves nothing.
    """
    model = getattr(config_facade, name)

    assert model.__module__ == "probos.config_models.integrations"
    assert facade.owns(model.__module__) is True


# ---------------------------------------------------------------------------
# Behaviour preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MODELS_WITH_DEFAULTS)
def test_system_config_dump_is_unchanged_for_the_moved_model(name: str) -> None:
    """Reached through the real composition path, nested ones included."""
    dumped = SystemConfig().model_dump(mode="json")

    assert _walk(dumped, MODEL_TO_PATH[name]) == EXPECTED_DUMPS[name]


@pytest.mark.parametrize("name", LIST_ELEMENT_MODELS)
def test_list_element_models_compose_as_empty_lists(name: str) -> None:
    """The two element types are reached as a list, not as a submodel dict."""
    dumped = SystemConfig().model_dump(mode="json")

    assert _walk(dumped, MODEL_TO_PATH[name]) == []


@pytest.mark.parametrize("name", MODELS_WITH_DEFAULTS)
def test_constructing_with_no_arguments_yields_the_declared_defaults(
    name: str,
) -> None:
    """Empty input: every field falls back to its own default."""
    model = getattr(config_facade, name)

    instance = model()

    for field_name, info in model.model_fields.items():
        expected = info.default_factory() if info.default_factory else info.default
        assert getattr(instance, field_name) == expected


@pytest.mark.parametrize("name", MODELS_WITH_DEFAULTS)
def test_constructing_with_no_arguments_matches_the_pre_move_dump(name: str) -> None:
    """The direct instance, not just the one ``SystemConfig`` composes."""
    model = getattr(config_facade, name)

    assert model().model_dump(mode="json") == EXPECTED_DUMPS[name]


# ---------------------------------------------------------------------------
# The three validators in this batch, both branches each
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", ["file", "keychain"])
def test_credential_vault_backend_accepts_both_supported_backends(
    backend: str,
) -> None:
    assert config_facade.CredentialVaultConfig(backend=backend).backend == backend


def test_credential_vault_backend_rejects_an_unsupported_backend() -> None:
    """AD-1016: the field is a plain ``str``, so only the validator guards it."""
    with pytest.raises(ValueError, match="must be one of"):
        config_facade.CredentialVaultConfig(backend="dpapi")


@pytest.mark.parametrize("tier", ["fast", "standard", "deep", "vision"])
def test_attachments_vision_tier_accepts_every_declared_tier(tier: str) -> None:
    assert config_facade.AttachmentsConfig(vision_tier=tier).vision_tier == tier


def test_attachments_vision_tier_rejects_an_unknown_tier() -> None:
    with pytest.raises(ValueError, match="vision_tier must be one of"):
        config_facade.AttachmentsConfig(vision_tier="opus")


def test_mcp_server_http_requires_a_url() -> None:
    """``model_validator(mode="after")`` -- the empty default must not pass."""
    with pytest.raises(ValueError, match="requires a non-empty 'url'"):
        config_facade.MCPServerConfig()
    with pytest.raises(ValueError, match="requires a non-empty 'url'"):
        config_facade.MCPServerConfig(type="http", url="")

    accepted = config_facade.MCPServerConfig(url="https://example.test/mcp")

    assert accepted.type == "http"
    assert accepted.url == "https://example.test/mcp"


def test_mcp_server_stdio_requires_a_command() -> None:
    with pytest.raises(ValueError, match="requires a non-empty 'command'"):
        config_facade.MCPServerConfig(type="stdio")

    accepted = config_facade.MCPServerConfig(type="stdio", command="probos-mcp")

    assert accepted.command == "probos-mcp"
    assert accepted.url == ""


def test_mcp_server_transport_literal_still_rejects_an_unlisted_value() -> None:
    """``Literal`` is the type constraint the validator sits behind."""
    with pytest.raises(ValueError):
        config_facade.MCPServerConfig(type="websocket", url="wss://example.test")


def test_a2a_peer_requires_its_identity_fields() -> None:
    """The other element type: a bare instance must not validate."""
    with pytest.raises(ValueError):
        config_facade.A2APeerConfig()


# ---------------------------------------------------------------------------
# Field constraints that a careless move would silently widen
# ---------------------------------------------------------------------------


def test_federation_peer_trust_bounds_survived_the_move() -> None:
    """Beta(alpha, beta) must stay strictly positive -- ``gt``, not ``ge``."""
    assert (
        config_facade.FederationPeerTrustConfig(probationary_alpha=0.5)
        .probationary_alpha
        == 0.5
    )
    with pytest.raises(ValueError):
        config_facade.FederationPeerTrustConfig(probationary_alpha=0.0)
    with pytest.raises(ValueError):
        config_facade.FederationPeerTrustConfig(probationary_beta=0.0)


def test_federation_mcp_server_port_bounds_survived_the_move() -> None:
    assert config_facade.FederationMCPServerConfig(bind_port=1).bind_port == 1
    assert config_facade.FederationMCPServerConfig(bind_port=65535).bind_port == 65535
    with pytest.raises(ValueError):
        config_facade.FederationMCPServerConfig(bind_port=0)
    with pytest.raises(ValueError):
        config_facade.FederationMCPServerConfig(bind_port=65536)


def test_attachments_store_bound_is_inclusive_of_zero() -> None:
    """``max_store_bytes`` is ``ge=0``, not ``gt=0``: zero means "no cap".

    Measured, not assumed -- ``max_attachment_bytes`` beside it carries no
    bound at all, so this is the only byte field a move could silently widen.
    """
    assert config_facade.AttachmentsConfig(max_store_bytes=0).max_store_bytes == 0
    with pytest.raises(ValueError):
        config_facade.AttachmentsConfig(max_store_bytes=-1)


def test_credential_vault_max_credentials_bounds_survived_the_move() -> None:
    assert config_facade.CredentialVaultConfig(max_credentials=1).max_credentials == 1
    assert (
        config_facade.CredentialVaultConfig(max_credentials=10000).max_credentials
        == 10000
    )
    with pytest.raises(ValueError):
        config_facade.CredentialVaultConfig(max_credentials=0)
    with pytest.raises(ValueError):
        config_facade.CredentialVaultConfig(max_credentials=10001)


def test_federation_ard_referral_bounds_survived_the_move() -> None:
    assert config_facade.FederationArdConfig(max_referral_peers=0).max_referral_peers == 0
    assert (
        config_facade.FederationArdConfig(max_referral_peers=50).max_referral_peers == 50
    )
    with pytest.raises(ValueError):
        config_facade.FederationArdConfig(max_referral_peers=51)
    with pytest.raises(ValueError):
        config_facade.FederationArdConfig(max_referral_peers=-1)


def test_communications_a2ui_option_bounds_survived_the_move() -> None:
    """``ge=2`` -- a one-option choice is not a choice."""
    assert config_facade.CommunicationsConfig(a2ui_max_options=2).a2ui_max_options == 2
    assert config_facade.CommunicationsConfig(a2ui_max_options=20).a2ui_max_options == 20
    with pytest.raises(ValueError):
        config_facade.CommunicationsConfig(a2ui_max_options=1)
    with pytest.raises(ValueError):
        config_facade.CommunicationsConfig(a2ui_max_options=21)


@pytest.mark.parametrize("value", ["not-a-number", None, [1]])
def test_moved_models_still_reject_wrong_types(value: object) -> None:
    """Error path: the move must not have loosened coercion."""
    with pytest.raises(ValueError):
        config_facade.FederationDiscoveryConfig(multicast_port=value)


def test_list_defaults_are_not_shared_between_instances() -> None:
    """``discovery_endpoints`` is a mutable default; sharing it would leak."""
    first = config_facade.FederationArdConfig()
    second = config_facade.FederationArdConfig()

    assert first.discovery_endpoints is not second.discovery_endpoints

    first.discovery_endpoints.append("https://example.test/.well-known")

    assert second.discovery_endpoints == []


def test_dict_defaults_are_not_shared_between_instances() -> None:
    """``vision_tier_overrides`` is the batch's mutable dict default."""
    first = config_facade.AttachmentsConfig()
    second = config_facade.AttachmentsConfig()

    assert first.vision_tier_overrides is not second.vision_tier_overrides

    first.vision_tier_overrides["png"] = "fast"

    assert second.vision_tier_overrides == {}


def test_each_system_config_gets_its_own_moved_submodel() -> None:
    """e1 measured that ``SystemConfig()`` deep-copies its class defaults."""
    first = SystemConfig()
    second = SystemConfig()

    assert first.communications is not second.communications
    assert first.federation.tls is not second.federation.tls

    first.communications.a2ui_enabled = not first.communications.a2ui_enabled

    assert (
        second.communications.a2ui_enabled
        == EXPECTED_DUMPS["CommunicationsConfig"]["a2ui_enabled"]
    )


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


def test_integrations_module_does_not_import_the_facade() -> None:
    """The direction is facade -> package. A cycle here is a build failure."""
    tree = ast.parse(_INTEGRATIONS_SOURCE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert "probos.config" not in imported
    assert not any(name.startswith("probos") for name in imported)


def test_the_moved_classes_are_gone_from_the_facade_source() -> None:
    """A re-export beside a surviving definition would shadow silently."""
    tree = ast.parse(
        (_REPO_ROOT / "src" / "probos" / "config.py").read_text(encoding="utf-8")
    )
    defined = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}

    assert defined.isdisjoint(MOVED_MODELS)


def test_no_name_is_defined_in_more_than_one_domain_module() -> None:
    """Four batches now share one namespace; a collision would shadow one."""
    owners: dict[str, list[str]] = {}
    for module in ("core", "cognition", "experience", "integrations"):
        source = (
            _REPO_ROOT / "src" / "probos" / "config_models" / f"{module}.py"
        ).read_text(encoding="utf-8")
        for node in ast.parse(source).body:
            if isinstance(node, ast.ClassDef):
                owners.setdefault(node.name, []).append(module)

    assert {name: mods for name, mods in owners.items() if len(mods) > 1} == {}


def test_both_e2_tripwires_are_satisfied_on_this_tree() -> None:
    """Assert the list, not the exit code: which problem matters."""
    assert facade.tripwire_problems(_REPO_ROOT) == []


def test_the_selector_selects_broadly_for_an_integrations_model_change() -> None:
    """A model change must still select the full suite."""
    selector = _load("_ad1270e2d_selector", _REPO_ROOT / "scripts" / "select_tests.py")

    assert selector.matches_any(
        "src/probos/config_models/integrations.py", selector.BLAST_RADIUS_PATTERNS
    )


def test_the_profiles_env_scan_covers_the_new_module() -> None:
    """The widened scan must reach every file in the package, not just core."""
    profiles = _load(
        "_ad1270e2d_profiles", _REPO_ROOT / "scripts" / "check_config_profiles.py"
    )
    package = _REPO_ROOT / "src" / "probos"

    scanned = [path.name for path in profiles._env_scan_paths(package)]

    assert "config.py" in scanned
    assert "integrations.py" in scanned
    assert profiles.env_reads_reaching_defaults(package)["PROBOS_LLM_URL"] == (
        "model-validator"
    )
