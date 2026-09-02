"""AD-1270e2 -- the ``core`` batch left ``config.py`` without moving the surface.

Eight leaf models now live in ``probos.config_models.core`` and are re-exported
from ``probos.config``. The property under test is that no consumer can tell:
same class object, same qualname, same MRO, same ordered fields, same dumped
defaults. A name-only check would pass a wrapper or a re-declared copy, so the
identity assertions here compare ``is``, and the behaviour assertions compare
against written-out literals rather than a dump re-derived from the same code.

The two tripwires ``check_config_facade`` installed in e1 fire the moment
``src/probos/config_models/`` exists. Their emptiness on this tree is asserted
as a list, not as an exit code: a checker that returned a *different* problem
would still be "not green", and the list says which.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

import probos.config as config_facade
import probos.config_models.core as config_core
from probos.config import SystemConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASELINE = _REPO_ROOT / "docs" / "development" / "config-facade-baseline.yaml"
_CORE_SOURCE = _REPO_ROOT / "src" / "probos" / "config_models" / "core.py"

#: The batch, named once. Every parametrised case walks exactly these eight.
MOVED_MODELS: tuple[str, ...] = (
    "CircuitBreakerConfig",
    "ConcurrencyConfig",
    "ConsensusConfig",
    "EventLogConfig",
    "MeshConfig",
    "PoolConfig",
    "ScalingConfig",
    "SystemInfo",
)

#: ``SystemConfig`` field -> moved model, so a dump assertion names both ends.
FIELD_TO_MODEL: dict[str, str] = {
    "system": "SystemInfo",
    "pools": "PoolConfig",
    "mesh": "MeshConfig",
    "consensus": "ConsensusConfig",
    "scaling": "ScalingConfig",
    "circuit_breaker": "CircuitBreakerConfig",
    "concurrency": "ConcurrencyConfig",
    "event_log": "EventLogConfig",
}

#: Pre-move ``SystemConfig().model_dump(mode="json")`` sub-dicts, written out.
#: Deriving these from the models would make the assertion tautological: the
#: point is to compare against what the values were before the file moved.
EXPECTED_DUMPS: dict[str, dict[str, object]] = {
    "system": {"name": "ProbOS", "version": "0.1.0", "log_level": "INFO"},
    "pools": {
        "default_pool_size": 3,
        "max_pool_size": 7,
        "min_pool_size": 2,
        "spawn_cooldown_ms": 500,
        "health_check_interval_seconds": 5.0,
    },
    "mesh": {
        "gossip_interval_ms": 1000,
        "hebbian_decay_rate": 0.995,
        "hebbian_social_decay_rate": 0.995,
        "intent_skill_map": {},
        "hebbian_reward": 0.05,
        "signal_ttl_seconds": 30.0,
        "capability_broadcast_interval_seconds": 5.0,
        "semantic_matching": True,
        "handler_latency_deterministic_ms": 100.0,
        "handler_latency_network_ms": 10000.0,
        "handler_latency_cognitive_ms": 30000.0,
    },
    "consensus": {
        "min_votes": 3,
        "approval_threshold": 0.6,
        "use_confidence_weights": True,
        "verification_timeout_seconds": 5.0,
        "red_team_pool_size": 2,
        "trust_prior_alpha": 2.0,
        "trust_prior_beta": 2.0,
        "trust_decay_rate": 0.999,
    },
    "scaling": {
        "enabled": True,
        "scale_up_threshold": 0.8,
        "scale_down_threshold": 0.2,
        "scale_up_step": 1,
        "scale_down_step": 1,
        "cooldown_seconds": 30.0,
        "observation_window_seconds": 60.0,
        "idle_scale_down_seconds": 120.0,
    },
    "circuit_breaker": {
        "velocity_threshold": 8,
        "velocity_window_seconds": 300.0,
        "similarity_threshold": 0.6,
        "similarity_min_events": 4,
        "base_cooldown_seconds": 900.0,
        "max_cooldown_seconds": 3600.0,
        "amber_similarity_ratio": 0.25,
        "amber_velocity_ratio": 0.6,
        "amber_decay_seconds": 900.0,
        "red_decay_seconds": 1800.0,
        "critical_decay_seconds": 3600.0,
        "critical_trip_window_seconds": 3600.0,
        "critical_trip_count": 3,
    },
    "concurrency": {
        "enabled": True,
        "default_max_concurrent": 4,
        "queue_max_size": 10,
        "capacity_warning_ratio": 0.75,
        "role_overrides": {
            "bridge": 3,
            "operations": 6,
            "engineering": 5,
            "science": 4,
            "medical": 3,
            "security": 3,
        },
    },
    "event_log": {
        "retention_days": 7,
        "max_rows": 100000,
        "prune_interval_seconds": 3600.0,
    },
}


def _load(name: str, path: Path) -> ModuleType:
    """Import a ``scripts/`` module by path; ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


facade = _load("_ad1270e2_facade", _REPO_ROOT / "scripts" / "check_config_facade.py")


@pytest.fixture(scope="module")
def baseline_models() -> dict[str, dict]:
    document = yaml.safe_load(_BASELINE.read_text(encoding="utf-8"))
    return document["models"]


# ---------------------------------------------------------------------------
# Identity and re-export -- the contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_facade_reexports_the_same_object_not_a_copy(name: str) -> None:
    """``is``, not ``==``: a re-declared clone would satisfy equality."""
    assert getattr(config_facade, name) is getattr(config_core, name)


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
    """The 600+ call sites spell it exactly this way."""
    from probos.config import (  # noqa: F401
        CircuitBreakerConfig,
        ConcurrencyConfig,
        ConsensusConfig,
        EventLogConfig,
        MeshConfig,
        PoolConfig,
        ScalingConfig,
        SystemInfo,
    )

    assert PoolConfig is config_core.PoolConfig
    assert SystemInfo is config_core.SystemInfo


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_moved_module_is_still_owned_by_the_facade_contract(name: str) -> None:
    """The assertion that would have caught the round-1 e1 defect.

    ``owns()`` cannot key on ``__module__ == probos.config``, because that is
    the predicate this very move breaks. If it did, all eight would reclassify
    as import leakage and the baseline would demand a regeneration that proves
    nothing.
    """
    model = getattr(config_facade, name)

    assert model.__module__ == "probos.config_models.core"
    assert facade.owns(model.__module__) is True


# ---------------------------------------------------------------------------
# Behaviour preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field_name", sorted(FIELD_TO_MODEL))
def test_system_config_dump_is_unchanged_for_the_moved_field(field_name: str) -> None:
    dumped = SystemConfig().model_dump(mode="json")

    assert dumped[field_name] == EXPECTED_DUMPS[field_name]


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_constructing_with_no_arguments_yields_the_declared_defaults(
    name: str,
) -> None:
    """Empty input: every field falls back to its own default."""
    model = getattr(config_facade, name)

    instance = model()

    for field_name, info in model.model_fields.items():
        expected = (
            info.default_factory() if info.default_factory else info.default
        )
        assert getattr(instance, field_name) == expected


def test_mesh_validator_accepts_a_finite_positive_threshold() -> None:
    mesh = config_facade.MeshConfig(handler_latency_network_ms=250.0)

    assert mesh.handler_latency_network_ms == 250.0


@pytest.mark.parametrize(
    "value", [0.0, -1.0, float("inf"), float("nan"), True, "abc", None]
)
def test_mesh_validator_rejects_non_finite_or_non_positive(value: object) -> None:
    with pytest.raises(ValueError):
        config_facade.MeshConfig(handler_latency_deterministic_ms=value)


def test_mesh_validator_boundary_is_strictly_greater_than_zero() -> None:
    """The smallest positive float passes; zero does not. That is the edge."""
    assert (
        config_facade.MeshConfig(
            handler_latency_cognitive_ms=5e-324
        ).handler_latency_cognitive_ms
        == 5e-324
    )
    with pytest.raises(ValueError):
        config_facade.MeshConfig(handler_latency_cognitive_ms=0.0)


def test_pool_health_interval_floor_survived_the_move() -> None:
    """BF-846's ``ge=0.01`` is a decision; a move must not drop it."""
    assert config_facade.PoolConfig(health_check_interval_seconds=0.01)
    with pytest.raises(ValueError):
        config_facade.PoolConfig(health_check_interval_seconds=0.009)


def test_each_system_config_gets_its_own_moved_submodel() -> None:
    """e1 measured that ``SystemConfig()`` deep-copies its class defaults."""
    first = SystemConfig()
    second = SystemConfig()

    assert first.pools is not second.pools
    assert first.concurrency.role_overrides is not second.concurrency.role_overrides

    first.concurrency.role_overrides["bridge"] = 99

    assert second.concurrency.role_overrides["bridge"] == 3


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


def test_core_module_does_not_import_the_facade() -> None:
    """The direction is facade -> package. A cycle here is a build failure."""
    tree = ast.parse(_CORE_SOURCE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert "probos.config" not in imported
    assert not any(name.startswith("probos.config.") for name in imported)


def test_both_e2_tripwires_are_satisfied_on_this_tree() -> None:
    """Assert the list, not the exit code: which problem matters."""
    assert facade.tripwire_problems(_REPO_ROOT) == []


def test_the_selector_selects_broadly_for_a_config_model_change() -> None:
    """Tripwire 1's subject: a model change must still select the full suite."""
    selector = _load("_ad1270e2_selector", _REPO_ROOT / "scripts" / "select_tests.py")

    assert selector.matches_any(
        "src/probos/config_models/core.py", selector.BLAST_RADIUS_PATTERNS
    )


def test_the_profiles_env_scan_now_covers_the_moved_package() -> None:
    """Tripwire 2's subject: the scan must not terminate at ``config.py``.

    The ``PROBOS_LLM_URL`` row is the one proving the widened instrument still
    discriminates -- it is read from a ``model_validator`` in ``config.py``, so
    a scan that silently matched nothing would drop it.
    """
    profiles = _load(
        "_ad1270e2_profiles", _REPO_ROOT / "scripts" / "check_config_profiles.py"
    )
    package = _REPO_ROOT / "src" / "probos"

    scanned = [path.name for path in profiles._env_scan_paths(package)]

    assert "config.py" in scanned
    assert "core.py" in scanned
    assert profiles.env_reads_reaching_defaults(package)["PROBOS_LLM_URL"] == (
        "model-validator"
    )
