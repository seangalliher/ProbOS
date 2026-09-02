"""AD-1270e2 batch 5 -- the ``operations`` batch preserved every public value.

Twenty leaf models -- sandboxed execution, QA smoke tests, telemetry and its
post-budget companion, confidence, lint, the quality trigger/router pair, the
validation framework and pre-flight gates, engineering and its sensors,
infrastructure backups, degradation, operations intervals, model routing,
threshold alerts, SPC, the anomaly window and operational status -- now live in
``probos.config_models.operations`` and are re-exported from ``probos.config``.

What is preserved is the PUBLIC FACADE and every value behind it: same class
object, same qualname, same MRO, same ordered fields, same dumped defaults.
What deliberately CHANGES is the declaration site -- ``config.py`` loses 342
lines and each model's ``__module__`` becomes
``probos.config_models.operations``. That relocation is observable, and one
case below asserts it on purpose rather than pretending otherwise. A name-only
check would pass a wrapper or a re-declared copy, so the identity assertions
compare ``is``.

``EXPECTED_DUMPS`` is generated from ``git show HEAD:src/probos/config.py`` at
authoring time -- the class text *before* the move, compiled in a throwaway
module and evaluated on its own. Had it been derived from the moved module the
assertion would compare the code against itself and pass for any value.

One case here is not about this batch at all. ``CodebaseIndex`` reads config
model definitions as *source text* rather than importing them, so the facade
re-export that keeps every import consumer whole did nothing for it, and
batches 1-3 shipped with their models missing from the system's own config
self-knowledge before an adversarial review caught it at batch 4. Every batch
from here on asserts that consumer explicitly.
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
import probos.config_models.operations as config_operations
from probos.cognitive.codebase_index import CodebaseIndex
from probos.config import SystemConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASELINE = _REPO_ROOT / "docs" / "development" / "config-facade-baseline.yaml"
_SOURCE_ROOT = _REPO_ROOT / "src" / "probos"
_OPERATIONS_SOURCE = _SOURCE_ROOT / "config_models" / "operations.py"

#: The batch, named once. Every parametrised case walks exactly these twenty.
MOVED_MODELS: tuple[str, ...] = (
    "AnomalyWindowConfig",
    "ConfidenceConfig",
    "DegradationConfig",
    "EngineeringConfig",
    "EngineeringSensorsConfig",
    "ExecutionConfig",
    "InfrastructureConfig",
    "LintConfig",
    "ModelRoutingConfig",
    "OperationalStatusConfig",
    "OperationsConfig",
    "PostBudgetTelemetryConfig",
    "PreFlightConfig",
    "QAConfig",
    "QualityRouterConfig",
    "QualityTriggerConfig",
    "SPCConfig",
    "TelemetryConfig",
    "ThresholdAlertConfig",
    "ValidationFrameworkConfig",
)

#: Moved model -> its dotted path under ``SystemConfig``. All twenty hang
#: directly off the root in this batch, which is why every one has a dump.
MODEL_TO_PATH: dict[str, str] = {
    "AnomalyWindowConfig": "anomaly_window",
    "ConfidenceConfig": "confidence",
    "DegradationConfig": "degradation",
    "EngineeringConfig": "engineering",
    "EngineeringSensorsConfig": "engineering_sensors",
    "ExecutionConfig": "execution",
    "InfrastructureConfig": "infrastructure",
    "LintConfig": "lint",
    "ModelRoutingConfig": "model_routing",
    "OperationalStatusConfig": "operational_status",
    "OperationsConfig": "operations",
    "PostBudgetTelemetryConfig": "post_budget_telemetry",
    "PreFlightConfig": "pre_flight",
    "QAConfig": "qa",
    "QualityRouterConfig": "quality_router",
    "QualityTriggerConfig": "quality_trigger",
    "SPCConfig": "spc",
    "TelemetryConfig": "telemetry",
    "ThresholdAlertConfig": "threshold_alerts",
    "ValidationFrameworkConfig": "validation_framework",
}

#: Pre-move ``model_dump(mode="json")``, measured against ``HEAD``'s
#: ``config.py`` source rather than the module this file imports.
EXPECTED_DUMPS: dict[str, dict[str, object]] = {
    "AnomalyWindowConfig": {
        "enabled": True,
        "max_window_duration_seconds": 1800.0,
        "lookback_seconds": 60.0,
    },
    "ConfidenceConfig": {
        "enabled": True,
        "default_confidence": 0.5,
        "confirm_delta": 0.15,
        "contradict_delta": 0.25,
        "auto_supersede_threshold": 0.1,
        "auto_apply_threshold": 0.8,
        "suppress_threshold": 0.5,
    },
    "DegradationConfig": {"auto_pause_enabled": False},
    "EngineeringConfig": {
        "enabled": True,
        "performance_interval_seconds": 10.0,
        "maintenance_interval_seconds": 300.0,
        "damage_control_cooldown_seconds": 60.0,
    },
    "EngineeringSensorsConfig": {
        "enabled": True,
        "report_interval_seconds": 60.0,
        "auto_start_periodic_report": False,
    },
    "ExecutionConfig": {
        "enabled": False,
        "default_tier": 1,
        "scratch_dir": "data/execution",
        "persistent_workspaces": True,
        "workspace_root": "data/execution/workspaces",
        "fetch_broker_enabled": False,
        "fetch_broker_max_body_bytes": 8388608,
        "workspace_write_enabled": False,
        "timeout_seconds": 30.0,
        "max_output_bytes": 65536,
        "max_memory_mb": 512,
        "stage_thread_artifacts": False,
        "max_staged_artifacts": 20,
        "allow_package_install": False,
        "pip_index_url": "https://pypi.org/simple",
        "install_timeout_seconds": 180.0,
    },
    "InfrastructureConfig": {
        "enabled": True,
        "backup_enabled": True,
        "backup_subdir": "backups",
        "backup_interval_seconds": 21600.0,
        "backup_warmup_seconds": 120.0,
        "backup_retain_days": 3,
        "backup_max_total_bytes": 8589934592,
        "backup_include_archive_root": True,
        "backup_orphan_alert_bytes": 4294967296,
    },
    "LintConfig": {
        "enabled": True,
        "min_coverage_per_department": 5,
        "inconsistency_keywords": {
            "increased": "decreased",
            "improved": "degraded",
            "rising": "falling",
            "positive": "negative",
            "success": "failure",
        },
    },
    "ModelRoutingConfig": {
        "enabled": True,
        "cost_ceiling_per_million_output_tokens": None,
    },
    "OperationalStatusConfig": {
        "sample_window_size": 50,
        "available_success_rate": 0.85,
        "degraded_p95_latency_ms": 5000.0,
        "offline_consecutive_errors": 5,
    },
    "OperationsConfig": {
        "enabled": True,
        "resource_interval_seconds": 30.0,
        "resource_emit_interval_seconds": 60.0,
        "scheduler_interval_seconds": 60.0,
        "coordinator_interval_seconds": 60.0,
    },
    "PostBudgetTelemetryConfig": {
        "enabled": True,
        "exhaustion_alert_threshold": 0.5,
        "min_samples_for_alert": 10,
        "recent_suppressions_max": 100,
    },
    "PreFlightConfig": {
        "enabled": True,
        "llm_tier_check_enabled": True,
        "required_llm_tier": "deep",
        "token_budget_check_enabled": True,
        "token_budget_blocking": False,
    },
    "QAConfig": {
        "enabled": True,
        "smoke_test_count": 5,
        "timeout_per_test_seconds": 10.0,
        "total_timeout_seconds": 30.0,
        "pass_threshold": 0.6,
        "trust_reward_weight": 1.0,
        "trust_penalty_weight": 2.0,
        "flag_on_fail": True,
        "auto_remove_on_total_fail": False,
    },
    "QualityRouterConfig": {
        "enabled": True,
        "min_weight": 0.5,
        "max_weight": 1.5,
        "concern_threshold": 0.3,
    },
    "QualityTriggerConfig": {
        "enabled": True,
        "min_quality_threshold": 0.4,
        "max_stale_rate": 0.3,
        "max_repetition_rate": 0.2,
        "cooldown_seconds": 1800.0,
        "max_forced_per_day": 5,
    },
    "SPCConfig": {"enabled": True, "sample_window": 100},
    "TelemetryConfig": {
        "enabled": True,
        "report_interval_seconds": 60.0,
        "max_samples_per_bucket": 1000,
    },
    "ThresholdAlertConfig": {
        "enabled": False,
        "pool_saturation_floor": 0.9,
        "degradation_min_severity": "degraded",
        "attention_queue_depth": 20,
        "dedup_window_seconds": 300.0,
    },
    "ValidationFrameworkConfig": {
        "enabled": True,
        "metadata_threshold": 0.85,
        "min_confidence_delta": 0.2,
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


def _walk(dumped: dict[str, Any], dotted: str) -> Any:
    """Follow a ``MODEL_TO_PATH`` entry into a ``model_dump`` result."""
    node: Any = dumped
    for part in dotted.split("."):
        node = node[part]
    return node


facade = _load("_ad1270e2e_facade", _REPO_ROOT / "scripts" / "check_config_facade.py")


@pytest.fixture(scope="module")
def baseline_models() -> dict[str, dict]:
    return yaml.safe_load(_BASELINE.read_text(encoding="utf-8"))["models"]


def test_the_batch_tables_agree_with_each_other() -> None:
    """Guard the guard: a model dropped from a table must fail, not vanish."""
    assert set(EXPECTED_DUMPS) == set(MOVED_MODELS)
    assert set(MODEL_TO_PATH) == set(MOVED_MODELS)
    assert len(MOVED_MODELS) == len(set(MOVED_MODELS)) == 20


# ---------------------------------------------------------------------------
# Identity and re-export -- the contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_facade_reexports_the_same_object_not_a_copy(name: str) -> None:
    """``is``, not ``==``: a re-declared clone would satisfy equality."""
    assert getattr(config_facade, name) is getattr(config_operations, name)


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_package_namespace_reexports_the_same_object(name: str) -> None:
    """``config_models/__init__`` must not shadow the module with a copy."""
    assert getattr(config_pkg, name) is getattr(config_operations, name)
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
        AnomalyWindowConfig,
        ConfidenceConfig,
        DegradationConfig,
        EngineeringConfig,
        EngineeringSensorsConfig,
        ExecutionConfig,
        InfrastructureConfig,
        LintConfig,
        ModelRoutingConfig,
        OperationalStatusConfig,
        OperationsConfig,
        PostBudgetTelemetryConfig,
        PreFlightConfig,
        QAConfig,
        QualityRouterConfig,
        QualityTriggerConfig,
        SPCConfig,
        TelemetryConfig,
        ThresholdAlertConfig,
        ValidationFrameworkConfig,
    )

    assert AnomalyWindowConfig is config_operations.AnomalyWindowConfig
    assert ValidationFrameworkConfig is config_operations.ValidationFrameworkConfig


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_moved_module_is_still_owned_by_the_facade_contract(name: str) -> None:
    """``owns()`` cannot key on ``__module__ == probos.config``."""
    model = getattr(config_facade, name)

    assert model.__module__ == "probos.config_models.operations"
    assert facade.owns(model.__module__) is True


# ---------------------------------------------------------------------------
# The source-reading consumer (BF at batch 4) -- not an import consumer
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def config_schema() -> dict[str, Any]:
    index = CodebaseIndex(_SOURCE_ROOT)
    index.build()
    return index.get_config_schema()


def test_the_index_still_sees_a_never_moved_model(config_schema: dict) -> None:
    """Control. Without it, the next assertion proves nothing on failure."""
    assert "CognitiveConfig" in config_schema


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_the_source_reading_consumer_still_sees_the_moved_model(
    name: str, config_schema: dict
) -> None:
    """``CodebaseIndex`` parses source; the facade re-export does nothing here.

    Compares the ORDERED field set, not mere presence. Presence alone passes on
    a single surviving field, which would hide exactly the partial loss this
    guard exists to catch.
    """
    assert name in config_schema

    model = getattr(config_operations, name)

    assert list(config_schema[name]) == list(model.model_fields)


# ---------------------------------------------------------------------------
# Behaviour preserved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_system_config_dump_is_unchanged_for_the_moved_model(name: str) -> None:
    """Reached through the real composition path."""
    dumped = SystemConfig().model_dump(mode="json")

    assert _walk(dumped, MODEL_TO_PATH[name]) == EXPECTED_DUMPS[name]


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_constructing_with_no_arguments_yields_the_declared_defaults(
    name: str,
) -> None:
    """Empty input: every field falls back to its own default."""
    model = getattr(config_facade, name)

    instance = model()

    for field_name, info in model.model_fields.items():
        expected = info.default_factory() if info.default_factory else info.default
        assert getattr(instance, field_name) == expected


@pytest.mark.parametrize("name", MOVED_MODELS)
def test_constructing_with_no_arguments_matches_the_pre_move_dump(name: str) -> None:
    """The direct instance, not just the one ``SystemConfig`` composes."""
    assert getattr(config_facade, name)().model_dump(mode="json") == EXPECTED_DUMPS[name]


# ---------------------------------------------------------------------------
# Field constraints a careless move would silently widen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model_name", "field_name", "lo", "hi"),
    [
        ("ValidationFrameworkConfig", "metadata_threshold", 0.0, 1.0),
        ("ValidationFrameworkConfig", "min_confidence_delta", 0.0, 1.0),
        ("ThresholdAlertConfig", "pool_saturation_floor", 0.0, 1.0),
    ],
)
def test_inclusive_unit_interval_bounds_survived_the_move(
    model_name: str, field_name: str, lo: float, hi: float
) -> None:
    """``ge``/``le`` are inclusive -- both endpoints must still be accepted."""
    model = getattr(config_facade, model_name)

    assert getattr(model(**{field_name: lo}), field_name) == lo
    assert getattr(model(**{field_name: hi}), field_name) == hi
    with pytest.raises(ValueError):
        model(**{field_name: lo - 0.01})
    with pytest.raises(ValueError):
        model(**{field_name: hi + 0.01})


@pytest.mark.parametrize(
    ("model_name", "field_name", "floor"),
    [
        ("EngineeringConfig", "performance_interval_seconds", 1.0),
        ("EngineeringConfig", "maintenance_interval_seconds", 60.0),
        ("EngineeringConfig", "damage_control_cooldown_seconds", 1.0),
        ("InfrastructureConfig", "backup_interval_seconds", 300.0),
        ("OperationsConfig", "resource_interval_seconds", 1.0),
        ("OperationsConfig", "resource_emit_interval_seconds", 10.0),
        ("OperationsConfig", "scheduler_interval_seconds", 10.0),
        ("OperationsConfig", "coordinator_interval_seconds", 10.0),
        ("ThresholdAlertConfig", "dedup_window_seconds", 1.0),
    ],
)
def test_interval_floors_survived_the_move(
    model_name: str, field_name: str, floor: float
) -> None:
    """Each floor differs; a shared floor would be a silent widening."""
    model = getattr(config_facade, model_name)

    assert getattr(model(**{field_name: floor}), field_name) == floor
    with pytest.raises(ValueError):
        model(**{field_name: floor - 0.5})


@pytest.mark.parametrize(
    ("model_name", "field_name"),
    [
        ("InfrastructureConfig", "backup_warmup_seconds"),
        ("InfrastructureConfig", "backup_orphan_alert_bytes"),
        ("ThresholdAlertConfig", "attention_queue_depth"),
    ],
)
def test_zero_is_accepted_where_the_bound_is_ge_not_gt(
    model_name: str, field_name: str
) -> None:
    """``ge=0`` means zero is legal -- a careless ``gt=0`` would reject it."""
    model = getattr(config_facade, model_name)

    assert getattr(model(**{field_name: 0}), field_name) == 0
    with pytest.raises(ValueError):
        model(**{field_name: -1})


def test_backup_retention_bounds_survived_the_move() -> None:
    """``ge=1, le=365`` -- both ends, and both just outside."""
    assert config_facade.InfrastructureConfig(backup_retain_days=1).backup_retain_days == 1
    assert (
        config_facade.InfrastructureConfig(backup_retain_days=365).backup_retain_days
        == 365
    )
    with pytest.raises(ValueError):
        config_facade.InfrastructureConfig(backup_retain_days=0)
    with pytest.raises(ValueError):
        config_facade.InfrastructureConfig(backup_retain_days=366)


def test_backup_size_floor_survived_the_move() -> None:
    """``ge=64 MiB`` is an expression, not a literal -- it must still evaluate."""
    floor = 64 * 1024**2

    assert (
        config_facade.InfrastructureConfig(
            backup_max_total_bytes=floor
        ).backup_max_total_bytes
        == floor
    )
    with pytest.raises(ValueError):
        config_facade.InfrastructureConfig(backup_max_total_bytes=floor - 1)


@pytest.mark.parametrize("value", ["not-a-number", None, [1]])
def test_moved_models_still_reject_wrong_types(value: object) -> None:
    """Error path: the move must not have loosened coercion."""
    with pytest.raises(ValueError):
        config_facade.TelemetryConfig(max_samples_per_bucket=value)


def test_optional_none_default_survived_the_move() -> None:
    """``cost_ceiling_...`` is the batch's only ``| None`` default."""
    assert config_facade.ModelRoutingConfig().cost_ceiling_per_million_output_tokens is None
    assert (
        config_facade.ModelRoutingConfig(
            cost_ceiling_per_million_output_tokens=12.5
        ).cost_ceiling_per_million_output_tokens
        == 12.5
    )


def test_dict_default_is_not_shared_between_instances() -> None:
    """``inconsistency_keywords`` is the batch's mutable dict default."""
    first = config_facade.LintConfig()
    second = config_facade.LintConfig()

    assert first.inconsistency_keywords is not second.inconsistency_keywords

    first.inconsistency_keywords["up"] = "down"

    assert "up" not in second.inconsistency_keywords
    assert second.inconsistency_keywords == (
        EXPECTED_DUMPS["LintConfig"]["inconsistency_keywords"]
    )


def test_each_system_config_gets_its_own_moved_submodel() -> None:
    """e1 measured that ``SystemConfig()`` deep-copies its class defaults."""
    first = SystemConfig()
    second = SystemConfig()

    assert first.qa is not second.qa
    assert first.execution is not second.execution

    first.qa.enabled = not first.qa.enabled

    assert second.qa.enabled == EXPECTED_DUMPS["QAConfig"]["enabled"]


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


def test_operations_module_does_not_import_the_facade() -> None:
    """The direction is facade -> package. A cycle here is a build failure."""
    tree = ast.parse(_OPERATIONS_SOURCE.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert not any(name.startswith("probos") for name in imported)


def test_the_moved_classes_are_gone_from_the_facade_source() -> None:
    """A re-export beside a surviving definition would shadow silently."""
    tree = ast.parse((_SOURCE_ROOT / "config.py").read_text(encoding="utf-8"))
    defined = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}

    assert defined.isdisjoint(MOVED_MODELS)


def test_no_name_is_defined_in_more_than_one_domain_module() -> None:
    """Five batches now share one namespace; a collision would shadow one."""
    owners: dict[str, list[str]] = {}
    for module in sorted((_SOURCE_ROOT / "config_models").glob("*.py")):
        if module.name == "__init__.py":
            continue
        for node in ast.parse(module.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef):
                owners.setdefault(node.name, []).append(module.name)

    assert {name: mods for name, mods in owners.items() if len(mods) > 1} == {}


def test_the_package_exports_exactly_what_it_imports() -> None:
    """``__all__`` drift is how a re-export silently stops being public."""
    tree = ast.parse(
        (_SOURCE_ROOT / "config_models" / "__init__.py").read_text(encoding="utf-8")
    )
    imported: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("probos.config_models"):
                imported.extend(alias.name for alias in node.names)

    assert sorted(set(imported)) == list(config_pkg.__all__)
    assert len(imported) == len(set(imported))


def test_both_e2_tripwires_are_satisfied_on_this_tree() -> None:
    """Assert the list, not the exit code: which problem matters."""
    assert facade.tripwire_problems(_REPO_ROOT) == []


def test_the_selector_selects_broadly_for_an_operations_model_change() -> None:
    """A model change must still select the full suite."""
    selector = _load("_ad1270e2e_selector", _REPO_ROOT / "scripts" / "select_tests.py")

    assert selector.matches_any(
        "src/probos/config_models/operations.py", selector.BLAST_RADIUS_PATTERNS
    )


def test_the_profiles_env_scan_covers_the_new_module() -> None:
    """The widened scan must reach every file in the package, not just core."""
    profiles = _load(
        "_ad1270e2e_profiles", _REPO_ROOT / "scripts" / "check_config_profiles.py"
    )

    scanned = [path.name for path in profiles._env_scan_paths(_SOURCE_ROOT)]

    assert "config.py" in scanned
    assert "operations.py" in scanned
    assert profiles.env_reads_reaching_defaults(_SOURCE_ROOT)["PROBOS_LLM_URL"] == (
        "model-validator"
    )
